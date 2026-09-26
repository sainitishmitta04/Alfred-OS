"""FastAPI app. Run: `uvicorn orchestrator.main:app --port 8000`."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from orchestrator import __version__
from orchestrator.agents.registry import AgentRegistry
from orchestrator.config import Settings, get_settings
from orchestrator.db import Database
from orchestrator.engine import Orchestrator
from orchestrator.events import EventBus
from orchestrator.router import JevClient, JevVerifier, build_router
from orchestrator.schemas import ConfirmRequest, OrchestratorResponse, TranscriptRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("alfred")


def build_orchestrator(settings: Settings) -> tuple[Orchestrator, JevClient | None]:
    jev = JevClient(settings.typesafe_api_key, settings.jev_timeout_s, settings.jev_model) if settings.typesafe_api_key else None
    if jev is None:
        log.warning("TYPESAFE_API_KEY not set — routing falls back to Claude/keywords")
    orchestrator = Orchestrator(
        settings=settings,
        db=Database(settings.db_path),
        registry=AgentRegistry.discover(settings.agent_overrides),
        router=build_router(settings, jev),
        bus=EventBus(),
        verifier=JevVerifier(jev) if jev else None,
    )
    return orchestrator, jev


def create_app(orchestrator: Orchestrator | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or (orchestrator.settings if orchestrator else get_settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        jev = None
        if app.state.orchestrator is None:
            app.state.orchestrator, jev = build_orchestrator(settings)
        engine: Orchestrator = app.state.orchestrator
        for agent in engine.registry:
            try:
                await agent.startup()
            except Exception:
                log.exception("agent %s failed to start", agent.name)
        log.info("Alfred orchestrator ready with agents: %s", ", ".join(engine.registry.names()))
        yield
        for agent in engine.registry:
            try:
                await agent.shutdown()
            except Exception:
                log.exception("agent %s failed to shut down", agent.name)
        if jev:
            await jev.aclose()

    app = FastAPI(title="Alfred OS Orchestration Engine", version=__version__, lifespan=lifespan)
    app.state.orchestrator = orchestrator
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

    def engine() -> Orchestrator:
        return app.state.orchestrator

    @app.get("/health")
    async def health() -> dict:
        e = engine()
        return {"status": "ok", "version": __version__, "agents": e.registry.names(),
                "jev": e.verifier is not None, "claude_fallback": bool(e.settings.anthropic_api_key)}

    @app.get("/agents")
    async def agents() -> list[dict]:
        return [{"name": a.name, "description": a.description, "always_confirm": a.always_confirm,
                 "timeout_s": a.timeout_s or engine().settings.agent_timeout_s} for a in engine().registry]

    @app.post("/transcript", response_model=OrchestratorResponse, response_model_exclude_none=True)
    async def transcript(req: TranscriptRequest) -> dict:
        return await engine().handle_transcript(req.transcript)

    @app.post("/confirm", response_model=OrchestratorResponse, response_model_exclude_none=True)
    async def confirm(req: ConfirmRequest) -> dict:
        result = await engine().confirm(req.session_id, req.approved)
        if result is None:
            raise HTTPException(404, "session not found")
        return result

    @app.get("/sessions")
    async def sessions(limit: int = Query(20, ge=1, le=200)) -> list[dict]:
        return engine().db.list_sessions(limit)

    @app.get("/sessions/{session_id}")
    async def session(session_id: str) -> dict:
        found = engine().db.get_session(session_id)
        if found is None:
            raise HTTPException(404, "session not found")
        found["errors"] = engine().db.get_errors(session_id)
        return found

    @app.get("/sessions/{session_id}/steps")
    async def steps(session_id: str) -> list[dict]:
        return engine().db.get_steps(session_id)

    @app.get("/events")
    async def events() -> StreamingResponse:
        """Server-Sent Events: live action log for the UI (`new EventSource('/events')`)."""
        async def stream():
            async with engine().bus.subscribe() as queue:
                yield ": connected\n\n"
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                        yield f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


app = create_app()
