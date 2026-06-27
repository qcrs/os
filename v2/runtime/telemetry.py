from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from v2.contracts import TELEMETRY_EVENT_SCHEMA_VERSION


@dataclass(frozen=True)
class TelemetryEvent:
    event_id: str
    trace_id: str
    task_id: str
    step_id: str = ""
    attempt_id: str = ""
    span_id: str = ""
    parent_span_id: str = ""
    event_type: str = ""
    event_ts_ns: int = 0
    role: str = ""
    channel: str = ""
    severity: str = "info"
    payload: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float | int] = field(default_factory=dict)
    schema_version: str = TELEMETRY_EVENT_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        trace_id: str,
        task_id: str,
        event_type: str,
        step_id: str = "",
        attempt_id: str = "",
        role: str = "",
        channel: str = "",
        severity: str = "info",
        payload: dict[str, Any] | None = None,
        metrics: dict[str, float | int] | None = None,
    ) -> "TelemetryEvent":
        return cls(
            event_id=str(uuid.uuid4()),
            trace_id=trace_id,
            task_id=task_id,
            step_id=step_id,
            attempt_id=attempt_id,
            event_type=event_type,
            event_ts_ns=time.time_ns(),
            role=role,
            channel=channel,
            severity=severity,
            payload=payload or {},
            metrics=metrics or {},
        )


@dataclass
class TelemetryEmitter:
    events: list[TelemetryEvent] = field(default_factory=list)

    def emit(self, event: TelemetryEvent) -> TelemetryEvent:
        self.events.append(event)
        return event

    def summarize_task(self, task_id: str) -> dict[str, float]:
        relevant = [event for event in self.events if event.task_id == task_id]
        totals: dict[str, float] = {}
        for event in relevant:
            for key, value in event.metrics.items():
                totals[key] = totals.get(key, 0.0) + float(value)
        return totals

