from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentExecuteRequest(BaseModel):
    message: str = Field(min_length=1, description="Natural-language chore for Alfred to run.")


class AgentExecuteResponse(BaseModel):
    summary: str
    tool_results: list[dict] = Field(default_factory=list)
    latency_ms: int


class AgentTaskRequest(BaseModel):
    message: str = Field(min_length=1, description="Longer multi-step chore executed in the background.")


class AgentTaskReceipt(BaseModel):
    task_id: str
    status: TaskStatus


class AgentTaskStatus(BaseModel):
    task_id: str
    status: TaskStatus
    summary: str | None = None
    tool_results: list[dict] = Field(default_factory=list)
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    platform: str
    anthropic_configured: bool
    playwright_available: bool
    tools: list[str]
