from __future__ import annotations

from dataclasses import dataclass

from protocol.messages import Capability, PlanStep, StateRef, StepResult


@dataclass
class BaseAgent:
    agent_id: str
    capability: Capability

    async def execute_step(self, step: PlanStep, ctx: object) -> StepResult:
        raise NotImplementedError

    def select_input_state_refs(self, step: PlanStep, ctx: object) -> list[StateRef]:
        return []

    def required_input_state_kind_groups(self, step: PlanStep, ctx: object) -> list[tuple[str, ...]]:
        return []
