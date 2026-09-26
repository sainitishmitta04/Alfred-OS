"""Alfred Browser Agent: plan -> per-sub-task tool loop (Gemini/OpenRouter LLM + MCP tools, Jev decisions) -> synthesize.

Plug in with:  AGENT_OVERRIDES=browser=browser_agent:BrowserAgent
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from browser_agent import prompts
from browser_agent.config import BrowserSettings, load_mcp_servers
from browser_agent.decisions import JevDecider
from browser_agent.llm import DailyQuotaExceeded, LLMUnavailable, LLMRouter, ToolCall, build_llm
from browser_agent.mcp_pool import MCPPool
from browser_agent.planner import Planner
from browser_agent.tools import ASK_USER, CONTROL_TOOLS, FINISH, ToolResult, ToolSpec, builtin_tools
from orchestrator.agents.base import Agent, AgentContext, AgentResult, ConfirmationRequired

log = logging.getLogger(__name__)

RISKY_WORDS = re.compile(r"\b(submit|buy|purchase|pay|checkout|order|place order|send|post|publish|tweet|delete|remove|"
                         r"confirm|book|transfer|unsubscribe|sign up|register)\b", re.I)
KEEP_FULL_RESULTS = 2      # older tool outputs are shortened to keep the prompt small
OLD_RESULT_CHARS = 400


@dataclass
class RunState:
    """Everything needed to resume a paused run (lives in the engine while waiting for confirmation)."""

    goal: str
    subtasks: list[str]
    index: int = 0
    results: list[tuple[str, str]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    steps_used: int = 0
    pending_calls: list[ToolCall] = field(default_factory=list)   # calls from the last LLM turn not yet executed
    approved_call_id: str | None = None
    last_page: str = ""
    pre_approval_used: bool = False


def describe_target(arguments: dict[str, Any], page: str) -> str:
    """Resolve snapshot refs (e.g. "e44") in tool args to the matching snapshot line, so risk checks see
    'button "Submit order" [ref=e44]' instead of an opaque id."""
    described = [str(arguments.get("element") or "")]
    for key in ("target", "ref"):
        ref = arguments.get(key)
        if isinstance(ref, str) and page:
            line = next((ln.strip() for ln in page.splitlines() if f"[ref={ref}]" in ln), "")
            described.append(line)
    for field_ in arguments.get("fields", []) if isinstance(arguments.get("fields"), list) else []:
        if isinstance(field_, dict):
            described.append(str(field_.get("name", "")))
    if arguments.get("submit"):
        described.append("and press Enter to submit")
    return " ".join(d for d in described if d)[:300]


def _summarize_args(args: dict[str, Any], limit: int = 160) -> str:
    text = json.dumps(args, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


class BrowserAgent(Agent):
    name = "browser"
    description = ("Requires live website interaction — web search, social media, forms, "
                   "looking things up or reading pages online")

    def __init__(self, settings: BrowserSettings | None = None, *, llm: LLMRouter | None = None,
                 decider: JevDecider | None = None, pool: MCPPool | None = None,
                 extra_tools: list[ToolSpec] | None = None) -> None:
        self.settings = settings or BrowserSettings.from_env()
        self.timeout_s = self.settings.timeout_s
        self.llm = llm
        self.decider = decider
        self.pool = pool
        self._extra_tools = extra_tools or []
        self.tools: dict[str, ToolSpec] = {}
        self._lock = asyncio.Lock()   # one shared browser -> one browser task at a time
        self._started = False

    # --- lifecycle --------------------------------------------------------------------------------
    async def startup(self) -> None:
        if self._started:
            return
        s = self.settings
        if self.llm is None:
            self.llm = build_llm(s)   # Gemini first, OpenRouter fallback (LLM_PROVIDERS)
            await self.llm.validate_models()
        if self.decider is None:
            jev = None
            if s.typesafe_api_key:
                from orchestrator.router import JevClient
                jev = JevClient(s.typesafe_api_key, timeout_s=5.0)
            self.decider = JevDecider(jev, s.jev_confidence_threshold, s.risky_threshold)
        if self.pool is None:
            self.pool = MCPPool(load_mcp_servers(s.mcp_config_path))
            await self.pool.start()
        self._refresh_tools()
        self._started = True
        log.info("browser agent ready: models=%s tools=%d mcp=%s jev=%s", self.llm.models, len(self.tools),
                 self.pool.status, self.decider.enabled)

    def _refresh_tools(self) -> None:
        specs = builtin_tools() + (self.pool.tool_specs() if self.pool else []) + self._extra_tools + CONTROL_TOOLS
        self.tools = {t.name: t for t in specs if t.name not in self.settings.tool_denylist}

    async def shutdown(self) -> None:
        if self.pool:
            await self.pool.stop()
        jev = getattr(self.decider, "jev", None)
        if jev and hasattr(jev, "aclose"):
            await jev.aclose()
        self._started = False

    # --- Agent API --------------------------------------------------------------------------------
    async def run(self, goal: str, ctx: AgentContext) -> AgentResult:
        await self.startup()
        async with self._lock:
            try:
                subtasks, why = await Planner(self.llm, self.decider, self.settings.planner_model).plan(goal)
            except DailyQuotaExceeded as exc:
                ctx.step("llm_unavailable", str(exc), False)
                return AgentResult("My free AI model quota for today is used up, so I can't browse right now.", success=False)
            ctx.step("plan", f"{len(subtasks)} sub-task(s) [{why}]: " + " | ".join(subtasks))
            return await self._drive(RunState(goal=goal, subtasks=subtasks), ctx)

    async def resume(self, state: RunState, ctx: AgentContext) -> AgentResult:
        await self.startup()
        async with self._lock:
            if state.pending_calls:
                state.approved_call_id = state.pending_calls[0].id
            return await self._drive(state, ctx)

    async def cancel(self, state: RunState) -> None:
        state.pending_calls.clear()

    # --- core loop --------------------------------------------------------------------------------
    async def _drive(self, state: RunState, ctx: AgentContext) -> AgentResult:
        deadline = time.monotonic() + self.timeout_s - 5  # leave room to answer before the engine times out
        ok = True
        while state.index < len(state.subtasks):
            subtask = state.subtasks[state.index]
            if not state.messages:
                ctx.step("subtask", f"{state.index + 1}/{len(state.subtasks)}: {subtask}")
                state.messages = self._initial_messages(state, subtask)
            try:
                answer, success = await self._run_subtask(state, subtask, ctx, deadline)
            except DailyQuotaExceeded as exc:
                ctx.step("llm_unavailable", str(exc), False)
                answer, success = "My free AI model quota for today is used up, so I can't browse right now.", False
            except LLMUnavailable as exc:
                ctx.step("llm_unavailable", str(exc)[:300], False)
                answer, success = "I couldn't reach a free language model right now.", False
            ok = ok and success
            state.results.append((subtask, answer))
            state.index += 1
            state.messages, state.pending_calls = [], []
            if not success and state.index < len(state.subtasks):
                ctx.step("chain_stopped", "stopping the chain because a sub-task failed", False)
                break

        text = await Planner(self.llm, self.decider, self.settings.planner_model).synthesize(state.goal, state.results)
        ctx.step("synthesize", text[:300], ok)
        return AgentResult(text=text, success=ok, data={"subtasks": [{"task": t, "answer": a} for t, a in state.results],
                                                        "steps_used": state.steps_used})

    def _initial_messages(self, state: RunState, subtask: str) -> list[dict[str, Any]]:
        context = ""
        if state.results:
            context = prompts.PRIOR_CONTEXT.format(results="\n".join(f"- {t}: {a}" for t, a in state.results))
        return [{"role": "system", "content": prompts.SYSTEM},
                {"role": "user", "content": prompts.SUBTASK.format(subtask=subtask, context=context, goal=state.goal)}]

    async def _run_subtask(self, state: RunState, subtask: str, ctx: AgentContext, deadline: float) -> tuple[str, bool]:
        schemas = [t.openai_schema() for t in self.tools.values()]
        while True:
            # 1) finish executing any calls left from the previous LLM turn (e.g. after a confirmation pause)
            while state.pending_calls:
                call = state.pending_calls[0]
                outcome = await self._execute(call, state, subtask, ctx)
                state.pending_calls.pop(0)
                if outcome is not None:
                    state.pending_calls.clear()
                    return outcome

            if state.steps_used >= self.settings.max_steps:
                return await self._wrap_up(state, ctx, f"step limit ({self.settings.max_steps}) reached")
            if time.monotonic() > deadline:
                return await self._wrap_up(state, ctx, "time budget exhausted")

            # 2) ask the LLM for the next action(s)
            self._compact(state.messages)
            result = await self.llm.chat(state.messages, schemas)
            state.steps_used += 1
            if not result.tool_calls:
                ctx.step("answer", f"[{result.model}] {result.content[:200]}")
                return result.content or "I couldn't find an answer.", bool(result.content)
            ctx.step("think", f"[{result.model} {result.latency_ms}ms] " +
                     ", ".join(f"{c.name}({_summarize_args(c.arguments, 80)})" for c in result.tool_calls))
            state.messages.append(result.assistant_message())
            state.pending_calls = list(result.tool_calls)

    async def _execute(self, call: ToolCall, state: RunState, subtask: str, ctx: AgentContext) -> tuple[str, bool] | None:
        """Run one tool call. Returns (answer, success) when the sub-task ends, else None."""
        if call.name == FINISH:
            answer = str(call.arguments.get("answer", "")).strip() or "Done."
            self._tool_reply(state, call, "ok")
            ctx.step("finish", answer[:300])
            return answer, True
        if call.name == ASK_USER:
            question = str(call.arguments.get("question", "")).strip() or "I need more details to continue."
            self._tool_reply(state, call, "asked user")
            ctx.step("ask_user", question, None)
            return question, True

        spec = self.tools.get(call.name)
        if call.parse_error or spec is None:
            error = call.parse_error or f"unknown tool {call.name!r}. Available: {', '.join(self.tools)}"
            self._tool_reply(state, call, f"ERROR: {error}")
            ctx.step("tool_error", f"{call.name}: {error}"[:300], False)
            return None

        # Risky action gate: Jev decides (typed Noul); approval pauses the whole run via the engine.
        if not spec.read_only and call.id != state.approved_call_id:
            target = describe_target(call.arguments, state.last_page)
            args = {**call.arguments, "target_element": target} if target else call.arguments
            score = await self.decider.risky(state.goal, call.name, args, state.last_page)
            keyword = bool(RISKY_WORDS.search(target))  # deterministic safety floor next to Jev
            risky = keyword or (score is not None and score >= self.settings.risky_threshold)
            ctx.step("jev_risk_check", f"{call.name} on {target or '?'}: jev={'n/a' if score is None else f'{score:.2f}'}"
                     f" keyword={keyword}", not risky)
            if risky and ctx.approved and not state.pre_approval_used:
                # The user already approved this exact request up front; don't ask twice for the first risky step.
                state.pre_approval_used = True
                ctx.step("risk_pre_approved", "user approved this request before dispatch", True)
                risky = False
            if risky:
                action = call.name.split("__")[-1].replace("browser_", "").replace("_", " ")
                raise ConfirmationRequired(f"Before I continue: {action} {target or _summarize_args(call.arguments, 120)}"
                                           " may be irreversible. Should I go ahead?", state)

        started = time.perf_counter()
        try:
            raw = await spec.fn(**call.arguments)
            outcome = raw if isinstance(raw, ToolResult) else ToolResult(str(raw))
        except Exception as exc:  # tool errors are observations for the LLM, not crashes
            outcome = ToolResult(f"{type(exc).__name__}: {exc}", is_error=True)
        ms = int((time.perf_counter() - started) * 1000)
        text = outcome.text[: self.settings.snapshot_chars]
        if len(outcome.text) > self.settings.snapshot_chars:
            text += f"\n…[truncated {len(outcome.text) - self.settings.snapshot_chars} chars]"
        if spec.source.startswith("mcp:playwright") and not outcome.is_error:
            state.last_page = text
        self._tool_reply(state, call, ("ERROR: " if outcome.is_error else "") + text)
        ctx.step(call.name, f"{_summarize_args(call.arguments)} -> {ms}ms, {len(outcome.text)} chars"
                 + (f" ERROR {outcome.text[:150]}" if outcome.is_error else ""), not outcome.is_error)

        await self._review(state, subtask, call, text, ctx)
        return None

    async def _review(self, state: RunState, subtask: str, call: ToolCall, text: str, ctx: AgentContext) -> None:
        """Jev per-step review; confident verdicts become short hints that steer the LLM's next turn."""
        if call.name in (FINISH, ASK_USER) or state.pending_calls[1:]:  # only review the last call of a turn
            return
        review = await self.decider.review_step(subtask, f"{call.name} {_summarize_args(call.arguments)}", text)
        if review is None:
            return
        ctx.step("jev_review", f"step_ok={review.step_ok:.2f} next={review.progress}({review.confidence:.2f}) "
                 f"{review.latency_ms}ms", review.step_ok >= 0.5)
        if review.confidence < self.settings.jev_confidence_threshold:
            return  # unsure -> let the LLM judge on its own
        hint = {
            "done": "Check: the result needed for this task appears to be available now. If so, call finish with the answer.",
            "stuck": "Check: no progress is being made. Try a different approach (web_search, another link, fetch_url) or finish with what you have.",
        }.get(review.progress)
        if review.step_ok < 0.3 and not hint:
            hint = "Check: the last action appears to have failed. Look at the result and adjust."
        if hint:
            state.messages.append({"role": "user", "content": hint})

    async def _wrap_up(self, state: RunState, ctx: AgentContext, reason: str) -> tuple[str, bool]:
        ctx.step("budget", reason, False)
        state.messages.append({"role": "user", "content": f"Stop now ({reason}). Reply with the best answer you have "
                                                          "from the results so far, in 1-3 sentences, without calling tools."})
        try:
            result = await self.llm.chat(state.messages, None, max_tokens=300)
            if result.content:
                return result.content, False
        except LLMUnavailable:
            pass
        return "I ran out of time before finishing that.", False

    @staticmethod
    def _tool_reply(state: RunState, call: ToolCall, content: str) -> None:
        state.messages.append({"role": "tool", "tool_call_id": call.id, "content": content})

    @staticmethod
    def _compact(messages: list[dict[str, Any]]) -> None:
        tool_idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        for i in tool_idx[:-KEEP_FULL_RESULTS]:
            content = messages[i]["content"]
            if len(content) > OLD_RESULT_CHARS:
                messages[i]["content"] = content[:OLD_RESULT_CHARS] + " …[older result shortened]"
