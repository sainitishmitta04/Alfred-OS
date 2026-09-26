from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from threading import Lock

from app.schemas import TaskStatus


@dataclass
class TaskRecord:
    task_id: str
    message: str
    status: TaskStatus = TaskStatus.PENDING
    summary: str | None = None
    tool_results: list[dict] = field(default_factory=list)
    error: str | None = None


class InMemoryTaskStore:
    """Thread-safe in-memory store for background agent tasks."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = Lock()

    def create(self, message: str) -> TaskRecord:
        task_id = str(uuid.uuid4())
        record = TaskRecord(task_id=task_id, message=message)
        with self._lock:
            self._tasks[task_id] = record
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def update(self, task_id: str, **fields: object) -> None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return
            for key, value in fields.items():
                setattr(record, key, value)


TASK_STORE = InMemoryTaskStore()
