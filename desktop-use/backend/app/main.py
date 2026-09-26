from __future__ import annotations

import importlib.util
import platform

from fastapi import BackgroundTasks, FastAPI, HTTPException

from app import config
from app.agent.engine import TOOL_HANDLERS, AgentEngine
from app.schemas import (
    AgentExecuteRequest,
    AgentExecuteResponse,
    AgentTaskReceipt,
    AgentTaskRequest,
    AgentTaskStatus,
    HealthResponse,
    TaskStatus,
)
from app.task_store import TASK_STORE

app = FastAPI(title="Alfred", version="0.1.0", description="Desktop-use agent backend for Alfred-OS.")


def _playwright_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def _registered_tools() -> list[str]:
    return sorted(TOOL_HANDLERS.keys())


async def _run_background_task(task_id: str, message: str) -> None:
    TASK_STORE.update(task_id, status=TaskStatus.RUNNING)
    try:
        result = await AgentEngine().run(message)
        TASK_STORE.update(
            task_id,
            status=TaskStatus.COMPLETED,
            summary=result["summary"],
            tool_results=result["tool_results"],
        )
    except Exception as error:  # noqa: BLE001
        TASK_STORE.update(task_id, status=TaskStatus.FAILED, error=str(error))


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="alfred",
        platform=platform.system(),
        anthropic_configured=bool(config.ANTHROPIC_API_KEY),
        playwright_available=_playwright_available(),
        tools=_registered_tools(),
    )


@app.post("/api/v1/agent/execute", response_model=AgentExecuteResponse)
async def agent_execute(body: AgentExecuteRequest) -> AgentExecuteResponse:
    engine = AgentEngine()
    try:
        result = await engine.run(body.message)
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    return AgentExecuteResponse(**result)


@app.post("/api/v1/agent/task", response_model=AgentTaskReceipt)
async def agent_task(body: AgentTaskRequest, background_tasks: BackgroundTasks) -> AgentTaskReceipt:
    record = TASK_STORE.create(body.message)
    background_tasks.add_task(_run_background_task, record.task_id, body.message)
    return AgentTaskReceipt(task_id=record.task_id, status=record.status)


@app.get("/api/v1/agent/task/{task_id}", response_model=AgentTaskStatus)
def agent_task_status(task_id: str) -> AgentTaskStatus:
    record = TASK_STORE.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return AgentTaskStatus(
        task_id=record.task_id,
        status=record.status,
        summary=record.summary,
        tool_results=record.tool_results,
        error=record.error,
    )
