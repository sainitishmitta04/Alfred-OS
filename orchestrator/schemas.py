"""Request/response models for the HTTP API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TranscriptRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=4000)


class ConfirmRequest(BaseModel):
    session_id: str
    approved: bool


class ConfirmAnswer(BaseModel):
    approved: bool


class TaskAccepted(BaseModel):
    """POST /tasks answers at once; follow the task through GET /events and GET /sessions/{session_id}."""

    session_id: str
    status: str


class DesktopRunRequest(BaseModel):
    """Bypass routing: invoke the desktop agent directly (desktop team / integration tests)."""

    command: str = Field(min_length=1, max_length=4000)


class DesktopRunResponse(BaseModel):
    success: bool
    summary: str
    steps: list[dict[str, Any]] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class OrchestratorResponse(BaseModel):
    session_id: str
    status: str
    route: str | None = None
    route_source: str | None = None
    route_confidence: float | None = None
    is_destructive: bool = False
    proposed_action: str | None = None
    response_text: str
    latency_ms: int | None = None
    jev_latency_ms: int | None = None
    agent_latency_ms: int | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)
