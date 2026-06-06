from __future__ import annotations

from dataclasses import dataclass, field

from protocol.messages import Capability, MemoryCommit, Plan, PlanStep, StepResult


class SchemaValidationError(ValueError):
    pass


@dataclass
class CapabilityTable:
    by_agent: dict[str, Capability] = field(default_factory=dict)
    by_action: dict[tuple[str, str], object] = field(default_factory=dict)

    def register(self, capability: Capability) -> None:
        self.by_agent[capability.agent_id] = capability
        for item in capability.items:
            self.by_action[(capability.agent_id, item.name)] = item

    def action_item(self, agent_id: str, action: str) -> object:
        key = (agent_id, action)
        if key not in self.by_action:
            raise SchemaValidationError(f"capability not registered for {agent_id}:{action}")
        return self.by_action[key]


class SchemaInterceptor:
    @staticmethod
    def validate_plan(plan: Plan, capability_table: CapabilityTable) -> None:
        if not plan.task_id.strip():
            raise SchemaValidationError("plan.task_id is required")
        if not plan.goal.strip():
            raise SchemaValidationError("plan.goal is required")
        if not plan.steps:
            raise SchemaValidationError("plan.steps must not be empty")
        seen_step_ids: set[str] = set()
        known_step_ids: set[str] = set()
        for step in plan.steps:
            SchemaInterceptor.validate_step(step, capability_table)
            if step.step_id in seen_step_ids:
                raise SchemaValidationError(f"duplicate plan step_id: {step.step_id}")
            missing_deps = [dep for dep in step.depends_on if dep not in known_step_ids]
            if missing_deps:
                raise SchemaValidationError(
                    f"plan step {step.step_id} depends on unknown steps: {', '.join(missing_deps)}"
                )
            seen_step_ids.add(step.step_id)
            known_step_ids.add(step.step_id)

    @staticmethod
    def validate_step(step: PlanStep, capability_table: CapabilityTable) -> None:
        if not step.step_id.strip():
            raise SchemaValidationError("plan_step.step_id is required")
        if not step.owner_agent.strip():
            raise SchemaValidationError(f"plan_step {step.step_id} missing owner_agent")
        if not step.action.strip():
            raise SchemaValidationError(f"plan_step {step.step_id} missing action")
        capability_table.action_item(step.owner_agent, step.action)

    @staticmethod
    def validate_result(
        *,
        step: PlanStep,
        result: StepResult,
        capability_table: CapabilityTable,
    ) -> None:
        if result.step_id != step.step_id:
            raise SchemaValidationError(
                f"step result mismatch: expected {step.step_id}, got {result.step_id}"
            )
        item = capability_table.action_item(step.owner_agent, step.action)
        allowed = set(getattr(item, "produced_state_kinds", []))
        if allowed:
            for ref in result.output_state_refs:
                if ref.kind not in allowed:
                    raise SchemaValidationError(
                        f"step {step.step_id} emitted unsupported state kind {ref.kind}"
                    )

    @staticmethod
    def validate_memory_commit(commit: MemoryCommit) -> None:
        if not commit.memory_id.strip():
            raise SchemaValidationError("memory_commit.memory_id is required")
        if not commit.source_agent_id.strip():
            raise SchemaValidationError("memory_commit.source_agent_id is required")
        if not commit.source_task_id.strip():
            raise SchemaValidationError("memory_commit.source_task_id is required")
        if not commit.task_theme.strip():
            raise SchemaValidationError("memory_commit.task_theme is required")
        if not commit.summary.strip():
            raise SchemaValidationError("memory_commit.summary is required")
        if not commit.evidence_state_ids:
            raise SchemaValidationError("memory_commit.evidence_state_ids must not be empty")
        if commit.evidence_state_refs:
            ref_ids = {ref.state_id for ref in commit.evidence_state_refs}
            missing = [state_id for state_id in commit.evidence_state_ids if state_id not in ref_ids]
            if missing:
                raise SchemaValidationError(
                    "memory_commit.evidence_state_ids missing refs for: " + ", ".join(missing)
                )
