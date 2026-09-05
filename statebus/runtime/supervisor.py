from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time

from statebus.contracts import StepLifecycleState


class LifecycleOrigin(StrEnum):
    """Source of one Runtime lifecycle observation."""

    WORKER_OBSERVED = "WORKER_OBSERVED"
    LOCAL_RUNTIME = "LOCAL_RUNTIME"
    ADAPTER_DERIVED = "ADAPTER_DERIVED"


AttemptKey = tuple[str, str, str]


@dataclass
class StepRuntimeRecord:
    task_id: str
    step_id: str
    attempt_id: str
    role: str
    session_id: str = ""
    state: StepLifecycleState = StepLifecycleState.PENDING
    lifecycle_origin: LifecycleOrigin | None = None
    last_error: str = ""
    dispatched_at_ns: int = 0
    acked_at_ns: int = 0
    started_at_ns: int = 0
    last_heartbeat_ns: int = 0
    completed_at_ns: int = 0
    cancelled_at_ns: int = 0
    trapped_at_ns: int = 0
    gc_done_at_ns: int = 0


@dataclass(frozen=True)
class WorkerSessionSnapshot:
    task_id: str
    step_id: str
    attempt_id: str
    role: str
    state: str
    dispatched_at_ns: int
    acked_at_ns: int
    started_at_ns: int
    last_heartbeat_ns: int
    completed_at_ns: int
    cancelled_at_ns: int
    trapped_at_ns: int
    last_error: str
    session_id: str = ""
    origin: LifecycleOrigin | None = None


@dataclass
class RuntimeSupervisor:
    """Track lifecycle for concrete ``(session, step, attempt)`` records.

    ``steps`` remains a read-only latest-record projection for legacy callers
    that have not yet supplied an explicit session/Attempt scope. New runtime
    paths use ``attempts`` plus explicit scope and cannot overwrite a prior
    Attempt for the same Step.
    """

    attempts: dict[AttemptKey, StepRuntimeRecord] = field(default_factory=dict)
    transition_trace: list[dict[str, object]] = field(default_factory=list)
    _latest_key_by_step: dict[str, AttemptKey] = field(default_factory=dict, init=False, repr=False)

    _ALLOWED_TRANSITIONS: dict[StepLifecycleState, tuple[StepLifecycleState, ...]] = field(
        default_factory=lambda: {
            StepLifecycleState.PENDING: (StepLifecycleState.DISPATCHED,),
            StepLifecycleState.DISPATCHED: (
                StepLifecycleState.ACKED,
                StepLifecycleState.RUNNING,
                StepLifecycleState.TRAPPED,
                StepLifecycleState.CANCELLED,
            ),
            StepLifecycleState.ACKED: (
                StepLifecycleState.RUNNING,
                StepLifecycleState.TRAPPED,
                StepLifecycleState.CANCELLED,
            ),
            StepLifecycleState.RUNNING: (
                StepLifecycleState.COMPLETED,
                StepLifecycleState.FAILED,
                StepLifecycleState.TRAPPED,
                StepLifecycleState.CANCELLED,
            ),
            StepLifecycleState.COMPLETED: (StepLifecycleState.GC_PENDING,),
            StepLifecycleState.FAILED: (StepLifecycleState.GC_PENDING,),
            StepLifecycleState.TRAPPED: (StepLifecycleState.GC_PENDING,),
            StepLifecycleState.CANCELLED: (StepLifecycleState.GC_PENDING,),
            StepLifecycleState.GC_PENDING: (StepLifecycleState.GC_DONE,),
            StepLifecycleState.GC_DONE: (),
        }
    )

    @property
    def steps(self) -> dict[str, StepRuntimeRecord]:
        """Compatibility projection of the latest registered Attempt per Step."""

        return {
            step_id: self.attempts[key]
            for step_id, key in self._latest_key_by_step.items()
            if key in self.attempts
        }

    @staticmethod
    def _normalize_origin(
        origin: LifecycleOrigin | str | None,
        *,
        default: LifecycleOrigin,
    ) -> LifecycleOrigin:
        if origin is None:
            return default
        if isinstance(origin, LifecycleOrigin):
            return origin
        try:
            return LifecycleOrigin(str(origin))
        except ValueError as exc:
            raise ValueError("lifecycle_origin_invalid") from exc

    def register(
        self,
        *,
        task_id: str,
        step_id: str,
        attempt_id: str,
        role: str,
        session_id: str = "",
    ) -> StepRuntimeRecord:
        normalized_session_id = str(session_id).strip()
        normalized_step_id = str(step_id).strip()
        normalized_attempt_id = str(attempt_id).strip()
        if not normalized_step_id or not normalized_attempt_id:
            raise ValueError("attempt_scope_required")
        key = (normalized_session_id, normalized_step_id, normalized_attempt_id)
        if key in self.attempts:
            raise ValueError("attempt_already_registered")
        record = StepRuntimeRecord(
            task_id=task_id,
            step_id=normalized_step_id,
            attempt_id=normalized_attempt_id,
            role=role,
            session_id=normalized_session_id,
        )
        self.attempts[key] = record
        self._latest_key_by_step[normalized_step_id] = key
        return record

    def dispatch(
        self,
        step_id: str,
        *,
        session_id: str = "",
        attempt_id: str | None = None,
        origin: LifecycleOrigin | str | None = None,
    ) -> StepRuntimeRecord:
        record = self._transition(
            step_id,
            StepLifecycleState.DISPATCHED,
            session_id=session_id,
            attempt_id=attempt_id,
            origin=self._normalize_origin(origin, default=LifecycleOrigin.LOCAL_RUNTIME),
        )
        record.dispatched_at_ns = time.time_ns()
        return record

    def ack(
        self,
        step_id: str,
        *,
        session_id: str = "",
        attempt_id: str | None = None,
        origin: LifecycleOrigin | str | None = None,
    ) -> StepRuntimeRecord:
        normalized_origin = self._normalize_origin(origin, default=LifecycleOrigin.ADAPTER_DERIVED)
        if normalized_origin == LifecycleOrigin.LOCAL_RUNTIME:
            raise ValueError("local_runtime_cannot_ack")
        record = self._transition(
            step_id,
            StepLifecycleState.ACKED,
            session_id=session_id,
            attempt_id=attempt_id,
            origin=normalized_origin,
        )
        record.acked_at_ns = time.time_ns()
        return record

    def run_start(
        self,
        step_id: str,
        *,
        session_id: str = "",
        attempt_id: str | None = None,
        origin: LifecycleOrigin | str | None = None,
    ) -> StepRuntimeRecord:
        normalized_origin = self._normalize_origin(origin, default=LifecycleOrigin.ADAPTER_DERIVED)
        record = self._transition(
            step_id,
            StepLifecycleState.RUNNING,
            session_id=session_id,
            attempt_id=attempt_id,
            origin=normalized_origin,
        )
        now = time.time_ns()
        record.started_at_ns = now
        record.last_heartbeat_ns = now
        return record

    def heartbeat(
        self,
        step_id: str,
        *,
        session_id: str = "",
        attempt_id: str | None = None,
        origin: LifecycleOrigin | str | None = None,
    ) -> StepRuntimeRecord:
        normalized_origin = self._normalize_origin(origin, default=LifecycleOrigin.ADAPTER_DERIVED)
        if normalized_origin == LifecycleOrigin.LOCAL_RUNTIME:
            raise ValueError("local_runtime_cannot_observe_heartbeat")
        record = self._record(step_id, session_id=session_id, attempt_id=attempt_id)
        if record.state not in {StepLifecycleState.ACKED, StepLifecycleState.RUNNING}:
            raise ValueError(f"cannot record heartbeat for state {record.state.value}")
        record.last_heartbeat_ns = time.time_ns()
        self._record_trace(
            record,
            old_state=record.state,
            new_state=record.state,
            origin=normalized_origin,
            timestamp_ns=record.last_heartbeat_ns,
        )
        return record

    def complete(
        self,
        step_id: str,
        *,
        session_id: str = "",
        attempt_id: str | None = None,
        origin: LifecycleOrigin | str | None = None,
    ) -> StepRuntimeRecord:
        record = self._transition(
            step_id,
            StepLifecycleState.COMPLETED,
            session_id=session_id,
            attempt_id=attempt_id,
            origin=self._normalize_origin(origin, default=LifecycleOrigin.LOCAL_RUNTIME),
        )
        record.completed_at_ns = time.time_ns()
        return record

    def fail(
        self,
        step_id: str,
        error: str,
        *,
        session_id: str = "",
        attempt_id: str | None = None,
        origin: LifecycleOrigin | str | None = None,
    ) -> StepRuntimeRecord:
        record = self._transition(
            step_id,
            StepLifecycleState.FAILED,
            error,
            session_id=session_id,
            attempt_id=attempt_id,
            origin=self._normalize_origin(origin, default=LifecycleOrigin.LOCAL_RUNTIME),
        )
        record.completed_at_ns = time.time_ns()
        return record

    def trap(
        self,
        step_id: str,
        error: str,
        *,
        session_id: str = "",
        attempt_id: str | None = None,
        origin: LifecycleOrigin | str | None = None,
    ) -> StepRuntimeRecord:
        record = self._transition(
            step_id,
            StepLifecycleState.TRAPPED,
            error,
            session_id=session_id,
            attempt_id=attempt_id,
            origin=self._normalize_origin(origin, default=LifecycleOrigin.LOCAL_RUNTIME),
        )
        record.trapped_at_ns = time.time_ns()
        record.completed_at_ns = record.trapped_at_ns
        return record

    def cancel(
        self,
        step_id: str,
        error: str = "",
        *,
        session_id: str = "",
        attempt_id: str | None = None,
        origin: LifecycleOrigin | str | None = None,
    ) -> StepRuntimeRecord:
        record = self._transition(
            step_id,
            StepLifecycleState.CANCELLED,
            error,
            session_id=session_id,
            attempt_id=attempt_id,
            origin=self._normalize_origin(origin, default=LifecycleOrigin.LOCAL_RUNTIME),
        )
        record.cancelled_at_ns = time.time_ns()
        record.completed_at_ns = record.cancelled_at_ns
        return record

    def gc_pending(
        self,
        step_id: str,
        *,
        session_id: str = "",
        attempt_id: str | None = None,
        origin: LifecycleOrigin | str | None = None,
    ) -> StepRuntimeRecord:
        return self._transition(
            step_id,
            StepLifecycleState.GC_PENDING,
            session_id=session_id,
            attempt_id=attempt_id,
            origin=self._normalize_origin(origin, default=LifecycleOrigin.LOCAL_RUNTIME),
        )

    def gc_done(
        self,
        step_id: str,
        *,
        session_id: str = "",
        attempt_id: str | None = None,
        origin: LifecycleOrigin | str | None = None,
    ) -> StepRuntimeRecord:
        record = self._transition(
            step_id,
            StepLifecycleState.GC_DONE,
            session_id=session_id,
            attempt_id=attempt_id,
            origin=self._normalize_origin(origin, default=LifecycleOrigin.LOCAL_RUNTIME),
        )
        record.gc_done_at_ns = time.time_ns()
        return record

    def snapshot(
        self,
        step_id: str,
        *,
        session_id: str = "",
        attempt_id: str | None = None,
    ) -> WorkerSessionSnapshot:
        record = self._record(step_id, session_id=session_id, attempt_id=attempt_id)
        return WorkerSessionSnapshot(
            task_id=record.task_id,
            step_id=record.step_id,
            attempt_id=record.attempt_id,
            role=record.role,
            state=record.state.value,
            dispatched_at_ns=record.dispatched_at_ns,
            acked_at_ns=record.acked_at_ns,
            started_at_ns=record.started_at_ns,
            last_heartbeat_ns=record.last_heartbeat_ns,
            completed_at_ns=record.completed_at_ns,
            cancelled_at_ns=record.cancelled_at_ns,
            trapped_at_ns=record.trapped_at_ns,
            last_error=record.last_error,
            session_id=record.session_id,
            origin=record.lifecycle_origin,
        )

    def trap_if_ack_timed_out(
        self,
        step_id: str,
        *,
        ack_timeout_ms: int,
        now_ns: int | None = None,
        session_id: str = "",
        attempt_id: str | None = None,
    ) -> StepRuntimeRecord | None:
        record = self._record(step_id, session_id=session_id, attempt_id=attempt_id)
        if record.state != StepLifecycleState.DISPATCHED or record.dispatched_at_ns == 0:
            return None
        current_ns = time.time_ns() if now_ns is None else now_ns
        if current_ns - record.dispatched_at_ns < ack_timeout_ms * 1_000_000:
            return None
        record = self._transition(
            step_id,
            StepLifecycleState.TRAPPED,
            "ack_timeout",
            session_id=session_id,
            attempt_id=attempt_id,
            origin=LifecycleOrigin.LOCAL_RUNTIME,
        )
        record.trapped_at_ns = current_ns
        record.completed_at_ns = current_ns
        return record

    def trap_if_lease_expired(
        self,
        step_id: str,
        *,
        lease_timeout_ms: int,
        now_ns: int | None = None,
        session_id: str = "",
        attempt_id: str | None = None,
    ) -> StepRuntimeRecord | None:
        record = self._record(step_id, session_id=session_id, attempt_id=attempt_id)
        if record.state not in {StepLifecycleState.ACKED, StepLifecycleState.RUNNING}:
            return None
        lease_anchor_ns = record.last_heartbeat_ns or record.started_at_ns
        if lease_anchor_ns == 0:
            return None
        current_ns = time.time_ns() if now_ns is None else now_ns
        if current_ns - lease_anchor_ns < lease_timeout_ms * 1_000_000:
            return None
        record = self._transition(
            step_id,
            StepLifecycleState.TRAPPED,
            "heartbeat_timeout",
            session_id=session_id,
            attempt_id=attempt_id,
            origin=LifecycleOrigin.LOCAL_RUNTIME,
        )
        record.trapped_at_ns = current_ns
        record.completed_at_ns = current_ns
        return record

    def _record(
        self,
        step_id: str,
        *,
        session_id: str = "",
        attempt_id: str | None = None,
    ) -> StepRuntimeRecord:
        key = self._resolve_key(step_id, session_id=session_id, attempt_id=attempt_id)
        return self.attempts[key]

    def _resolve_key(
        self,
        step_id: str,
        *,
        session_id: str = "",
        attempt_id: str | None = None,
    ) -> AttemptKey:
        normalized_step_id = str(step_id).strip()
        normalized_session_id = str(session_id).strip()
        normalized_attempt_id = None if attempt_id is None else str(attempt_id).strip()
        if normalized_attempt_id is not None and normalized_session_id:
            key = (normalized_session_id, normalized_step_id, normalized_attempt_id)
            if key in self.attempts:
                return key
            raise KeyError(key)
        if normalized_attempt_id is not None:
            candidates = [
                key
                for key in self.attempts
                if key[1] == normalized_step_id and key[2] == normalized_attempt_id
            ]
            if len(candidates) == 1:
                return candidates[0]
            if not candidates:
                raise KeyError((normalized_session_id, normalized_step_id, normalized_attempt_id))
            raise ValueError("attempt_scope_ambiguous")
        if normalized_session_id:
            candidates = [
                key
                for key in self.attempts
                if key[0] == normalized_session_id and key[1] == normalized_step_id
            ]
            if len(candidates) == 1:
                return candidates[0]
            if not candidates:
                raise KeyError((normalized_session_id, normalized_step_id))
            return candidates[-1]
        key = self._latest_key_by_step.get(normalized_step_id)
        if key is None or key not in self.attempts:
            raise KeyError(normalized_step_id)
        return key

    def _transition(
        self,
        step_id: str,
        next_state: StepLifecycleState,
        error: str = "",
        *,
        session_id: str = "",
        attempt_id: str | None = None,
        origin: LifecycleOrigin | str,
    ) -> StepRuntimeRecord:
        record = self._record(step_id, session_id=session_id, attempt_id=attempt_id)
        allowed = self._ALLOWED_TRANSITIONS[record.state]
        if next_state not in allowed:
            raise ValueError(f"invalid transition {record.state.value} -> {next_state.value}")
        old_state = record.state
        record.state = next_state
        normalized_origin = self._normalize_origin(origin, default=LifecycleOrigin.LOCAL_RUNTIME)
        record.lifecycle_origin = normalized_origin
        if error:
            record.last_error = error
        self._record_trace(
            record,
            old_state=old_state,
            new_state=next_state,
            origin=normalized_origin,
            timestamp_ns=time.time_ns(),
        )
        return record

    def _record_trace(
        self,
        record: StepRuntimeRecord,
        *,
        old_state: StepLifecycleState,
        new_state: StepLifecycleState,
        origin: LifecycleOrigin,
        timestamp_ns: int,
    ) -> None:
        self.transition_trace.append(
            {
                "session_id": record.session_id,
                "step_id": record.step_id,
                "attempt_id": record.attempt_id,
                "old_state": old_state.value,
                "new_state": new_state.value,
                "origin": origin.value,
                "timestamp_ns": timestamp_ns,
            }
        )
