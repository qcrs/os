from __future__ import annotations

import json
from pathlib import Path
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, TextIO

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

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "attempt_id": self.attempt_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "event_type": self.event_type,
            "event_ts_ns": self.event_ts_ns,
            "role": self.role,
            "channel": self.channel,
            "severity": self.severity,
            "payload": dict(self.payload),
            "metrics": dict(self.metrics),
            "schema_version": self.schema_version,
        }


@dataclass
class TelemetryEmitter:
    events: list[TelemetryEvent] = field(default_factory=list)
    runtime_event_log_path: Path | None = None
    runtime_fact_log_path: Path | None = None
    flush_interval: int = 1
    _append_handles: dict[Path, TextIO] = field(default_factory=dict, init=False, repr=False)
    _pending_flush_counts: dict[Path, int] = field(default_factory=dict, init=False, repr=False)
    _path_task_ids: dict[Path, str] = field(default_factory=dict, init=False, repr=False)
    _task_io_metrics: dict[str, dict[str, float]] = field(default_factory=dict, init=False, repr=False)
    additive_event_types: tuple[str, ...] = (
        "EVIDENCE_PACK_BUILT",
        "RETRIEVAL_CANDIDATE_POOL_BUILT",
        "RETRIEVAL_RERANKED",
        "MEMORY_HYBRID_QUERIED",
        "STATE_PUBLISHED",
        "STATE_RESOLVED",
        "STATE_CONSUMED",
        "STATE_HYDRATED",
        "STATE_RELEASED",
        "LOGIT_STATE_EXTRACTION_AVAILABLE",
        "LOGIT_STATE_PUBLISHED",
        "LOGIT_STATE_RESOLVED",
        "LOGIT_STATE_CONSUMED",
        "LOGIT_STATE_REJECTED",
        "LOGIT_GATE_ACTION_DECIDED",
        "LOGIT_GATE_EFFECT_RECORDED",
        "LOGIT_STATE_RELEASED",
        "LATENT_HANDOFF_DECIDED",
        "LATENT_STATE_COMMITTED",
        "LATENT_STATE_CONSUMED",
        "LATENT_OUTPUT_VALIDATED",
        "LATENT_HANDOFF_FALLBACK",
        "LATENT_STATE_RELEASED",
        "LATENT_STATE_RELEASE_FAILED",
        "ARTIFACT_MATERIALIZED",
        "ARTIFACT_PUBLISHED",
        "ARTIFACT_RESTORED",
        "ARTIFACT_VALIDATED",
        "ARTIFACT_COMMITTED",
        "STEP_ACKED",
        "STEP_DISPATCHED",
        "STEP_RUNNING",
        "STEP_HEARTBEAT",
        "STEP_COMPLETED",
        "STEP_FAILED",
        "STEP_TRAPPED",
        "STEP_CANCELLED",
        "STEP_REPLAN_REQUESTED",
        "STEP_FALLBACK_REGRANTED",
        "EVIDENCE_PROJECTED",
        "CAPABILITY_QUALITY_EVALUATED",
        "LLM_CODEACT_EXECUTED",
        "ADAPTIVE_PLAN_APPROVED",
        "ADAPTIVE_MAINLINE_ASSEMBLED",
        "ADAPTIVE_SHADOW_AUDITED",
        "EVIDENCE_COVERAGE_DECIDED",
        "REPLAY_DECIDED",
        "MEMORY_COMMIT_VERIFIED",
        "GC_ISSUED",
        "METRIC_SNAPSHOT",
    )
    snapshot_event_types: tuple[str, ...] = ("TASK_SUMMARY_METRICS",)

    def emit(self, event: TelemetryEvent) -> TelemetryEvent:
        emit_start_ns = time.perf_counter_ns()
        task_metrics = self._task_metrics(event.task_id)
        self.events.append(event)
        payload = event.canonical_payload()
        event_write_start_ns = time.perf_counter_ns()
        event_written = self._append_jsonl(self.runtime_event_log_path, payload, task_id=event.task_id)
        task_metrics["telemetry_event_write_stage_ms"] += self._elapsed_ms(event_write_start_ns)
        if event_written:
            task_metrics["telemetry_event_write_count"] += 1.0
        if self._is_runtime_fact_event(event):
            fact_write_start_ns = time.perf_counter_ns()
            fact_written = self._append_jsonl(self.runtime_fact_log_path, payload, task_id=event.task_id)
            task_metrics["telemetry_fact_write_stage_ms"] += self._elapsed_ms(fact_write_start_ns)
            if fact_written:
                task_metrics["telemetry_fact_write_count"] += 1.0
        task_metrics["telemetry_emit_stage_ms"] += self._elapsed_ms(emit_start_ns)
        return event

    def summarize_task(self, task_id: str) -> dict[str, float]:
        relevant = [event for event in self.events if event.task_id == task_id]
        return self._summarize_events(relevant)

    def summarize_suite(self, task_ids: list[str]) -> dict[str, float]:
        relevant = [event for event in self.events if event.task_id in set(task_ids)]
        return self._summarize_events(relevant)

    def _summarize_events(self, events: list[TelemetryEvent]) -> dict[str, float]:
        totals: dict[str, float] = {}
        latest_snapshot_by_task: dict[str, TelemetryEvent] = {}
        for event in events:
            if event.event_type in self.additive_event_types:
                for key, value in event.metrics.items():
                    totals[key] = totals.get(key, 0.0) + float(value)
                continue
            if event.event_type in self.snapshot_event_types:
                latest_snapshot_by_task[event.task_id] = event
        for event in latest_snapshot_by_task.values():
            for key, value in event.metrics.items():
                totals[key] = totals.get(key, 0.0) + float(value)
        # Process identity is a set/attribute, never a sum.  Keep only its
        # cardinality in the numeric summary; the actual PID members remain in
        # the event payloads and state-consumption records.
        consumer_pids = {
            int(event.payload["physical_consumer_pid"])
            for event in events
            if str(event.payload.get("physical_consumer_pid", "")).isdigit()
            and int(event.payload.get("physical_consumer_pid", 0)) > 0
        }
        if consumer_pids:
            totals["semantic_state_consumer_pid_count"] = float(len(consumer_pids))
        return totals

    def task_io_metrics(self, task_id: str) -> dict[str, float]:
        return dict(self._task_metrics(task_id))

    def close(self) -> None:
        for path, handle in self._append_handles.items():
            if self._pending_flush_counts.get(path, 0) > 0:
                handle.flush()
                task_id = self._path_task_ids.get(path)
                if task_id is not None:
                    self._task_metrics(task_id)["telemetry_log_flush_count"] += 1.0
            handle.close()
        self._append_handles.clear()
        self._pending_flush_counts.clear()
        self._path_task_ids.clear()

    def _append_jsonl(self, path: Path | None, payload: dict[str, Any], *, task_id: str) -> bool:
        if path is None:
            return False
        handle = self._append_handle(path, task_id=task_id)
        handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")
        pending_count = self._pending_flush_counts.get(path, 0) + 1
        if pending_count >= max(self.flush_interval, 1):
            handle.flush()
            pending_count = 0
            self._task_metrics(task_id)["telemetry_log_flush_count"] += 1.0
        self._pending_flush_counts[path] = pending_count
        return True

    def _append_handle(self, path: Path, *, task_id: str) -> TextIO:
        handle = self._append_handles.get(path)
        if handle is not None:
            return handle
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8")
        self._append_handles[path] = handle
        self._path_task_ids[path] = task_id
        self._task_metrics(task_id)["telemetry_log_handle_open_count"] += 1.0
        return handle

    @staticmethod
    def _elapsed_ms(start_ns: int) -> float:
        return (time.perf_counter_ns() - start_ns) / 1_000_000.0

    def _task_metrics(self, task_id: str) -> dict[str, float]:
        return self._task_io_metrics.setdefault(
            task_id,
            {
                "telemetry_emit_stage_ms": 0.0,
                "telemetry_event_write_stage_ms": 0.0,
                "telemetry_fact_write_stage_ms": 0.0,
                "telemetry_event_write_count": 0.0,
                "telemetry_fact_write_count": 0.0,
                "telemetry_log_flush_count": 0.0,
                "telemetry_log_handle_open_count": 0.0,
            },
        )

    @staticmethod
    def _is_runtime_fact_event(event: TelemetryEvent) -> bool:
        return event.event_type in {
            "STEP_DISPATCHED",
            "STEP_ACKED",
            "STEP_RUNNING",
            "STEP_HEARTBEAT",
            "STEP_COMPLETED",
            "STEP_FAILED",
            "STEP_TRAPPED",
            "STEP_CANCELLED",
            "STEP_FALLBACK_REGRANTED",
            "ADAPTIVE_PLAN_APPROVED",
            "ADAPTIVE_MAINLINE_ASSEMBLED",
            "ADAPTIVE_SHADOW_AUDITED",
            "EVIDENCE_COVERAGE_DECIDED",
            "REPLAY_DECIDED",
            "GC_ISSUED",
            "STATE_PUBLISHED",
            "STATE_RESOLVED",
            "STATE_CONSUMED",
            "STATE_HYDRATED",
            "STATE_RELEASED",
            "LATENT_HANDOFF_DECIDED",
            "LATENT_STATE_COMMITTED",
            "LATENT_STATE_CONSUMED",
            "LATENT_OUTPUT_VALIDATED",
            "LATENT_HANDOFF_FALLBACK",
            "LATENT_STATE_RELEASED",
            "LATENT_STATE_RELEASE_FAILED",
            "EVIDENCE_PACK_BUILT",
            "ARTIFACT_PUBLISHED",
            "ARTIFACT_RESTORED",
            "ARTIFACT_COMMITTED",
            "MEMORY_COMMIT_VERIFIED",
            "MEMORY_HYBRID_QUERIED",
        }
