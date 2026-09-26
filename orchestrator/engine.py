"""The orchestrator: route -> confirm-if-destructive -> dispatch -> verify -> log -> respond. Never raises."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
import traceback
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from orchestrator.agents.base import AgentContext, AgentResult, ConfirmationRequired
from orchestrator.agents.registry import AgentRegistry
from orchestrator.config import Settings
from orchestrator.db import Database
from orchestrator.events import EventBus
from orchestrator.router import JevVerifier, RouteDecision, Router

log = logging.getLogger(__name__)

HOOKS = ("before_route", "after_route", "before_dispatch", "after_dispatch", "on_error")
Hook = Callable[..., Any | Awaitable[Any]]

FALLBACK_ERROR = "Sorry, something went wrong while handling that. Please try again."
FALLBACK_TIMEOUT = "Sorry, that took too long, so I stopped. Please try again."
ENGINE = "orchestrator"
_FRESH = object()  # sentinel: dispatch a new run rather than resuming a paused one


class Orchestrator:
    def __init__(self, settings: Settings, db: Database, registry: AgentRegistry, router: Router,
                 bus: EventBus | None = None, verifier: JevVerifier | None = None) -> None:
        self.settings, self.db, self.registry, self.router = settings, db, registry, router
        self.bus = bus or EventBus()
        self.verifier = verifier
        self._hooks: dict[str, list[Hook]] = defaultdict(list)
        self._confirm_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # session_id -> agent state for tasks paused mid-run by ConfirmationRequired
        self._paused: dict[str, Any] = {}

    # --- extension points -------------------------------------------------------------------------
    def add_hook(self, event: str, fn: Hook) -> Hook:
        """Hooks receive a mutable `state` dict (session_id, transcript, goal, decision, result...).
        Mutating `state["goal"]` in before_dispatch rewrites what the agent receives."""
        if event not in HOOKS:
            raise ValueError(f"unknown hook {event!r}; expected one of {HOOKS}")
        self._hooks[event].append(fn)
        return fn

    async def _run_hooks(self, event: str, state: dict[str, Any]) -> None:
        for fn in self._hooks[event]:
            try:
                result = fn(state)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # hooks are best-effort
                log.exception("hook %s failed", event)
                self.db.log_error(state.get("session_id"), f"hook {event} failed: {exc}", traceback.format_exc())

    # --- logging helpers --------------------------------------------------------------------------
    def _step(self, session_id: str, agent: str, action: str, detail: str | None = None,
              success: bool | None = True) -> None:
        step = self.db.log_step(session_id, agent, self.db.next_step_number(session_id), action, detail, success)
        self.bus.publish("step", session_id=session_id, step=step)

    def _status(self, session_id: str, status: str, **fields: Any) -> None:
        self.db.update_session_status(session_id, status, **fields)
        self.bus.publish("status", session_id=session_id, status=status,
                         **{k: v for k, v in fields.items() if k != "completed_at"})

    def _error(self, session_id: str | None, message: str, exc: BaseException | None = None) -> None:
        stack = "".join(traceback.format_exception(exc)) if exc else None
        self.db.log_error(session_id, message, stack)
        self.bus.publish("error", session_id=session_id, message=message)

    def _response(self, session_id: str, **extra: Any) -> dict[str, Any]:
        session = self.db.get_session(session_id) or {}
        return {
            "session_id": session_id,
            "status": session.get("status"),
            "route": session.get("route"),
            "route_source": session.get("route_source"),
            "route_confidence": session.get("route_confidence"),
            "is_destructive": bool(session.get("is_destructive")),
            "response_text": session.get("response_text") or "",
            "latency_ms": session.get("latency_ms"),
            "jev_latency_ms": session.get("jev_latency_ms"),
            "agent_latency_ms": session.get("agent_latency_ms"),
            "steps": session.get("steps", []),
            **extra,
        }

    # --- public API -------------------------------------------------------------------------------
    async def handle_transcript(self, transcript: str, session_id: str | None = None) -> dict[str, Any]:
        """`session_id` lets a caller that runs this in the background (POST /tasks) hand out the id first."""
        start = time.perf_counter()
        session_id = session_id or uuid.uuid4().hex
        transcript = transcript.strip()
        self.db.log_session(session_id, transcript)
        self.bus.publish("session", session_id=session_id, transcript=transcript)
        state: dict[str, Any] = {"session_id": session_id, "transcript": transcript, "goal": transcript}

        try:
            await self._run_hooks("before_route", state)
            decision = await self.router.route(transcript, self.registry.descriptions())
            state["decision"] = decision
            agent = self.registry.get(decision.route)
            needs_confirmation = decision.is_destructive or bool(agent and agent.always_confirm)
            self._log_route(session_id, decision, needs_confirmation)
            self._status(session_id, "routed", route=decision.route, route_source=decision.source,
                         route_confidence=round(decision.confidence, 4), goal=state["goal"],
                         is_destructive=needs_confirmation, jev_latency_ms=decision.latency_ms)
            await self._run_hooks("after_route", state)

            if needs_confirmation:
                self._step(session_id, ENGINE, "confirmation_requested", f"Proposed action: {transcript}", None)
                msg = f"This looks irreversible. Should I go ahead and {transcript.rstrip('.?!')}?"
                self._status(session_id, "needs_confirmation", response_text=msg,
                             latency_ms=int((time.perf_counter() - start) * 1000))
                return self._response(session_id, proposed_action=transcript)

            return await self._dispatch(session_id, state, start)
        except Exception as exc:
            return await self._fail(session_id, state, start, FALLBACK_ERROR, exc)

    async def confirm(self, session_id: str, approved: bool) -> dict[str, Any] | None:
        """Second step of the destructive flow. Returns None for an unknown session."""
        async with self._confirm_locks[session_id]:  # a double-click must not dispatch twice
            session = self.db.get_session(session_id, with_steps=False)
            if session is None:
                return None
            if session["status"] != "needs_confirmation":
                return self._response(session_id, detail=f"session is {session['status']}, nothing to confirm")

            start = time.perf_counter()
            paused = self._paused.pop(session_id, _FRESH)
            self.db.update_session(session_id, confirmed=approved)
            self._step(session_id, ENGINE, "confirmation_received", "approved" if approved else "declined", approved)
            if not approved:
                if paused is not _FRESH and (agent := self.registry.get(session["route"])):
                    try:
                        await agent.cancel(paused)
                    except Exception as exc:
                        self._error(session_id, f"{agent.name}.cancel failed: {exc}", exc)
                self._status(session_id, "cancelled", response_text="Okay, I won't do that.", latency_ms=0)
                return self._response(session_id)

            state = {"session_id": session_id, "transcript": session["transcript"],
                     "goal": session["goal"] or session["transcript"], "route": session["route"]}
            try:
                return await self._dispatch(session_id, state, start, resume_state=paused)
            except Exception as exc:
                return await self._fail(session_id, state, start, FALLBACK_ERROR, exc)
            finally:
                self._confirm_locks.pop(session_id, None)

    # --- internals --------------------------------------------------------------------------------
    def _log_route(self, session_id: str, d: RouteDecision, needs_confirmation: bool) -> None:
        detail = f"route={d.route} source={d.source} confidence={d.confidence:.2f} latency={d.latency_ms}ms"
        if d.destructive_score is not None:
            detail += f" destructive={d.destructive_score:.2f}"
        if d.notes:
            detail += " | " + "; ".join(d.notes)
        self._step(session_id, ENGINE, "route", detail, True)
        if needs_confirmation:
            self._step(session_id, ENGINE, "destructive_check", "flagged as destructive", None)

    async def _dispatch(self, session_id: str, state: dict[str, Any], start: float,
                        resume_state: Any = _FRESH) -> dict[str, Any]:
        resuming = resume_state is not _FRESH
        if not resuming:
            await self._run_hooks("before_dispatch", state)
        route = state.get("route") or state["decision"].route
        agent = self.registry.get(route)
        if agent is None:
            return await self._fail(session_id, state, start, f"Sorry, I don't have a {route} agent available yet.")

        goal = state["goal"]
        self.db.update_session(session_id, goal=goal)
        self._step(session_id, route, "resume" if resuming else "dispatch", goal)
        ctx = AgentContext(session_id=session_id, agent=route, transcript=state["transcript"], settings=self.settings,
                           _log_step=lambda action, detail=None, success=True: self._step(session_id, route, action, detail, success))

        timeout = agent.timeout_s or self.settings.agent_timeout_s
        agent_start = time.perf_counter()
        try:
            call = agent.resume(resume_state, ctx) if resuming else agent.run(goal, ctx)
            raw = await asyncio.wait_for(call, timeout=timeout)
        except ConfirmationRequired as pause:
            self._paused[session_id] = pause.state
            self._step(session_id, route, "confirmation_requested", pause.prompt, None)
            self._status(session_id, "needs_confirmation", response_text=pause.prompt, is_destructive=True,
                         agent_latency_ms=int((time.perf_counter() - agent_start) * 1000),
                         latency_ms=int((time.perf_counter() - start) * 1000))
            return self._response(session_id, proposed_action=pause.prompt)
        except asyncio.TimeoutError as exc:
            self.db.update_session(session_id, agent_latency_ms=int((time.perf_counter() - agent_start) * 1000))
            return await self._fail(session_id, state, start, FALLBACK_TIMEOUT, exc, f"{route} agent timed out after {timeout}s")
        agent_ms = int((time.perf_counter() - agent_start) * 1000)

        result = raw if isinstance(raw, AgentResult) else AgentResult(text=str(raw))
        state["result"] = result
        self._step(session_id, route, "result", result.text[:500], result.success)
        await self._run_hooks("after_dispatch", state)

        if self.verifier and self.settings.jev_verify:
            await self._verify(session_id, goal, result.text)

        self._status(session_id, "completed" if result.success else "failed", response_text=result.text,
                     agent_latency_ms=agent_ms, latency_ms=int((time.perf_counter() - start) * 1000))
        return self._response(session_id)

    async def _verify(self, session_id: str, goal: str, text: str) -> None:
        try:
            score, ms = await asyncio.wait_for(self.verifier.verify(goal, text), timeout=self.settings.jev_timeout_s)
            self._step(session_id, ENGINE, "jev_verify", f"goal_satisfied={score:.2f} latency={ms}ms", score >= 0.5)
        except Exception as exc:  # verification is advisory only
            self._step(session_id, ENGINE, "jev_verify", f"skipped: {exc}", None)

    async def _fail(self, session_id: str, state: dict[str, Any], start: float, spoken: str,
                    exc: BaseException | None = None, message: str | None = None) -> dict[str, Any]:
        message = message or (f"{type(exc).__name__}: {exc}" if exc else spoken)
        log.warning("session %s failed: %s", session_id, message)
        try:
            state["error"] = message
            self._error(session_id, message, exc)
            self._step(session_id, ENGINE, "error", message, False)
            self._status(session_id, "failed", response_text=spoken, latency_ms=int((time.perf_counter() - start) * 1000))
            await self._run_hooks("on_error", state)
        except Exception:  # even logging failed — still answer the user
            log.exception("failed while recording failure")
            return {"session_id": session_id, "status": "failed", "response_text": spoken, "steps": []}
        return self._response(session_id)
