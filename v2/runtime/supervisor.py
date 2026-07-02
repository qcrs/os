from __future__ import annotations

from dataclasses import dataclass, field
import time

from v2.contracts import StepLifecycleState


@dataclass
class StepRuntimeRecord:
    task_id: str
    step_id: str
    attempt_id: str
    role: str
    state: StepLifecycleState = StepLifecycleState.PENDING
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


@dataclass
class RuntimeSupervisor:
    steps: dict[str, StepRuntimeRecord] = field(default_factory=dict)

    _ALLOWED_TRANSITIONS: dict[StepLifecycleState, tuple[StepLifecycleState, ...]] = field(
        default_factory=lambda: {
            StepLifecycleState.PENDING: (StepLifecycleState.DISPATCHED,),
            StepLifecycleState.DISPATCHED: (
                StepLifecycleState.ACKED,
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

    def register(self, *, task_id: str, step_id: str, attempt_id: str, role: str) -> StepRuntimeRecord:
        record = StepRuntimeRecord(task_id=task_id, step_id=step_id, attempt_id=attempt_id, role=role)
        self.steps[step_id] = record
        return record

    def dispatch(self, step_id: str) -> StepRuntimeRecord:
        record = self._transition(step_id, StepLifecycleState.DISPATCHED)
        record.dispatched_at_ns = time.time_ns()
        return record

    def ack(self, step_id: str) -> StepRuntimeRecord:
        record = self._transition(step_id, StepLifecycleState.ACKED)
        record.acked_at_ns = time.time_ns()
        return record

    def run_start(self, step_id: str) -> StepRuntimeRecord:
        record = self._transition(step_id, StepLifecycleState.RUNNING)
        now = time.time_ns()
        record.started_at_ns = now
        record.last_heartbeat_ns = now
        return record

    def heartbeat(self, step_id: str) -> StepRuntimeRecord:
        record = self.steps[step_id]
        if record.state not in {StepLifecycleState.ACKED, StepLifecycleState.RUNNING}:
            raise ValueError(f"cannot record heartbeat for state {record.state.value}")
        record.last_heartbeat_ns = time.time_ns()
        return record

    def complete(self, step_id: str) -> StepRuntimeRecord:
        record = self._transition(step_id, StepLifecycleState.COMPLETED)
        record.completed_at_ns = time.time_ns()
        return record

    def fail(self, step_id: str, error: str) -> StepRuntimeRecord:
        record = self._transition(step_id, StepLifecycleState.FAILED, error)
        record.completed_at_ns = time.time_ns()
        return record

    def trap(self, step_id: str, error: str) -> StepRuntimeRecord:
        record = self._transition(step_id, StepLifecycleState.TRAPPED, error)
        record.trapped_at_ns = time.time_ns()
        record.completed_at_ns = record.trapped_at_ns
        return record

    def cancel(self, step_id: str, error: str = "") -> StepRuntimeRecord:
        record = self._transition(step_id, StepLifecycleState.CANCELLED, error)
        record.cancelled_at_ns = time.time_ns()
        record.completed_at_ns = record.cancelled_at_ns
        return record

    def gc_pending(self, step_id: str) -> StepRuntimeRecord:
        return self._transition(step_id, StepLifecycleState.GC_PENDING)

    def gc_done(self, step_id: str) -> StepRuntimeRecord:
        record = self._transition(step_id, StepLifecycleState.GC_DONE)
        record.gc_done_at_ns = time.time_ns()
        return record

    def snapshot(self, step_id: str) -> WorkerSessionSnapshot:
        record = self.steps[step_id]
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
        )

    def trap_if_ack_timed_out(
        self,
        step_id: str,
        *,
        ack_timeout_ms: int,
        now_ns: int | None = None,
    ) -> StepRuntimeRecord | None:
        record = self.steps[step_id]
        if record.state != StepLifecycleState.DISPATCHED or record.dispatched_at_ns == 0:
            return None
        current_ns = time.time_ns() if now_ns is None else now_ns
        if current_ns - record.dispatched_at_ns < ack_timeout_ms * 1_000_000:
            return None
        record = self._transition(step_id, StepLifecycleState.TRAPPED, "ack_timeout")
        record.trapped_at_ns = current_ns
        record.completed_at_ns = current_ns
        return record

    def trap_if_lease_expired(
        self,
        step_id: str,
        *,
        lease_timeout_ms: int,
        now_ns: int | None = None,
    ) -> StepRuntimeRecord | None:
        record = self.steps[step_id]
        if record.state not in {StepLifecycleState.ACKED, StepLifecycleState.RUNNING}:
            return None
        lease_anchor_ns = record.last_heartbeat_ns or record.started_at_ns
        if lease_anchor_ns == 0:
            return None
        current_ns = time.time_ns() if now_ns is None else now_ns
        if current_ns - lease_anchor_ns < lease_timeout_ms * 1_000_000:
            return None
        record = self._transition(step_id, StepLifecycleState.TRAPPED, "heartbeat_timeout")
        record.trapped_at_ns = current_ns
        record.completed_at_ns = current_ns
        return record

    def _transition(
        self,
        step_id: str,
        next_state: StepLifecycleState,
        error: str = "",
    ) -> StepRuntimeRecord:
        record = self.steps[step_id]
        allowed = self._ALLOWED_TRANSITIONS[record.state]
        if next_state not in allowed:
            raise ValueError(f"invalid transition {record.state.value} -> {next_state.value}")
        record.state = next_state
        if error:
            record.last_error = error
        return record
