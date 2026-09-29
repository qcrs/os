from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str = Field(min_length=1, max_length=80)


class RunEvent(BaseModel):
    sequence: int
    timestamp: str
    event_type: str
    role: str = ""
    task_id: str = ""
    step_id: str = ""
    message: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class RunView(BaseModel):
    run_id: str
    recipe_id: str
    recipe_name: str
    mode: str
    status: RunStatus
    created_at: str
    started_at: str = ""
    completed_at: str = ""
    progress: float = 0.0
    current_stage: str = ""
    run_dir: str
    error: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    latest_events: list[RunEvent] = Field(default_factory=list)

