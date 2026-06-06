from __future__ import annotations

from dataclasses import dataclass

from protocol.messages import Capability, PlanStep, StepResult


@dataclass
class BaseAgent:
    agent_id: str
    capability: Capability

    async def execute_step(self, step: PlanStep, ctx: object) -> StepResult:
        raise NotImplementedError
