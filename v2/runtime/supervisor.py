from __future__ import annotations

from dataclasses import dataclass, field

from v2.contracts import StepLifecycleState


@dataclass
class StepRuntimeRecord:
    task_id: str
    step_id: str
    attempt_id: str
    role: str
    state: StepLifecycleState = StepLifecycleState.PENDING
    last_error: str = ""


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
        return self._transition(step_id, StepLifecycleState.DISPATCHED)

    def ack(self, step_id: str) -> StepRuntimeRecord:
        return self._transition(step_id, StepLifecycleState.ACKED)

    def run_start(self, step_id: str) -> StepRuntimeRecord:
        return self._transition(step_id, StepLifecycleState.RUNNING)

    def complete(self, step_id: str) -> StepRuntimeRecord:
        return self._transition(step_id, StepLifecycleState.COMPLETED)

    def fail(self, step_id: str, error: str) -> StepRuntimeRecord:
        return self._transition(step_id, StepLifecycleState.FAILED, error)

    def trap(self, step_id: str, error: str) -> StepRuntimeRecord:
        return self._transition(step_id, StepLifecycleState.TRAPPED, error)

    def cancel(self, step_id: str, error: str = "") -> StepRuntimeRecord:
        return self._transition(step_id, StepLifecycleState.CANCELLED, error)

    def gc_pending(self, step_id: str) -> StepRuntimeRecord:
        return self._transition(step_id, StepLifecycleState.GC_PENDING)

    def gc_done(self, step_id: str) -> StepRuntimeRecord:
        return self._transition(step_id, StepLifecycleState.GC_DONE)

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

