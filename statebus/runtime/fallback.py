from __future__ import annotations

from dataclasses import dataclass

from statebus.contracts import FALLBACK_DAG_SCHEMA_VERSION, FALLBACK_RESOLUTION_RECORD_SCHEMA_VERSION
from statebus.utils import sha256_digest


@dataclass(frozen=True)
class FallbackAction:
    action_name: str
    target_step_id: str
    reason: str
    next_capability: str = ""
    skip_downstream_step_ids: tuple[str, ...] = ()
    downgrade_outputs: tuple[str, ...] = ()

    def canonical_payload(self) -> dict[str, object]:
        return {
            "action_name": self.action_name,
            "target_step_id": self.target_step_id,
            "reason": self.reason,
            "next_capability": self.next_capability,
            "skip_downstream_step_ids": list(self.skip_downstream_step_ids),
            "downgrade_outputs": list(self.downgrade_outputs),
        }


@dataclass(frozen=True)
class FallbackDag:
    dag_id: str
    task_id: str
    source_step_id: str
    actions: tuple[FallbackAction, ...]
    schema_version: str = FALLBACK_DAG_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "dag_id": self.dag_id,
            "task_id": self.task_id,
            "source_step_id": self.source_step_id,
            "actions": [action.canonical_payload() for action in self.actions],
            "schema_version": self.schema_version,
        }

    @property
    def dag_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class FallbackResolutionRecord:
    resolution_id: str
    task_id: str
    source_step_id: str
    attempt_id: str
    selected_action_name: str
    selected_reason: str
    downgraded_execution_goal: bool
    skipped_downstream_step_ids: tuple[str, ...] = ()
    schema_version: str = FALLBACK_RESOLUTION_RECORD_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "resolution_id": self.resolution_id,
            "task_id": self.task_id,
            "source_step_id": self.source_step_id,
            "attempt_id": self.attempt_id,
            "selected_action_name": self.selected_action_name,
            "selected_reason": self.selected_reason,
            "downgraded_execution_goal": self.downgraded_execution_goal,
            "skipped_downstream_step_ids": list(self.skipped_downstream_step_ids),
            "schema_version": self.schema_version,
        }


@dataclass
class FallbackPlanner:
    def plan_for_trap(
        self,
        *,
        task_id: str,
        source_step_id: str,
        requested_outputs: tuple[str, ...],
        fallback_action: str,
    ) -> FallbackDag:
        if fallback_action == "retry_same_step":
            actions = (
                FallbackAction(
                    action_name="retry_same_step",
                    target_step_id=source_step_id,
                    reason="transient_runtime_failure",
                ),
                FallbackAction(
                    action_name="downgrade_execution_goal",
                    target_step_id=source_step_id,
                    reason="retry_budget_spent",
                    next_capability="materialize_text_summary_only",
                    downgrade_outputs=tuple(
                        output_name
                        for output_name in requested_outputs
                        if output_name not in {"summary_text", "summary_json"}
                    ),
                ),
            )
        else:
            actions = (
                FallbackAction(
                    action_name="skip_downstream_branch",
                    target_step_id=source_step_id,
                    reason=fallback_action or "unknown_fallback",
                ),
            )
        return FallbackDag(
            dag_id=f"fallback-{task_id}-{source_step_id}",
            task_id=task_id,
            source_step_id=source_step_id,
            actions=actions,
        )
