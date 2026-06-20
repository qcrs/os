from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from protocol.messages import Plan
from runtime.role_contracts import FOUR_ROLE_COMPARATOR_ORDER, normalize_comparator_role_name


@dataclass(frozen=True)
class CarrierFairnessGate:
    passed: bool
    fail_closed: bool = True
    required_roles: tuple[str, ...] = FOUR_ROLE_COMPARATOR_ORDER
    observed_roles: tuple[str, ...] = ()
    missing_plan_roles: tuple[str, ...] = ()
    missing_context_roles: tuple[str, ...] = ()
    missing_trace_roles: tuple[str, ...] = ()
    contract_errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "fail_closed": self.fail_closed,
            "required_roles": list(self.required_roles),
            "observed_roles": list(self.observed_roles),
            "missing_plan_roles": list(self.missing_plan_roles),
            "missing_context_roles": list(self.missing_context_roles),
            "missing_trace_roles": list(self.missing_trace_roles),
            "contract_errors": list(self.contract_errors),
        }


def evaluate_plan_fairness_gate(plan: Plan) -> CarrierFairnessGate:
    observed: list[str] = ["planner"]
    for step in plan.steps:
        raw_role = (step.semantic_role or step.step_id).strip().lower()
        if not raw_role:
            continue
        try:
            normalized = normalize_comparator_role_name(raw_role)
        except ValueError:
            continue
        observed.append(normalized)
    observed_roles = tuple(dict.fromkeys(observed))
    missing_plan_roles = tuple(
        role for role in FOUR_ROLE_COMPARATOR_ORDER if role not in observed_roles
    )
    return CarrierFairnessGate(
        passed=not missing_plan_roles,
        observed_roles=observed_roles,
        missing_plan_roles=missing_plan_roles,
    )


def evaluate_execution_fairness_gate(
    *,
    plan: Plan,
    role_context_slices: dict[str, Any],
    role_trace: list[dict[str, Any]],
    contract_errors: list[str] | tuple[str, ...],
) -> CarrierFairnessGate:
    plan_gate = evaluate_plan_fairness_gate(plan)
    traced_roles: set[str] = set()
    for item in role_trace:
        raw_role = str(item.get("role", "")).strip().lower()
        if not raw_role:
            continue
        try:
            traced_roles.add(normalize_comparator_role_name(raw_role))
        except ValueError:
            continue
    missing_context_roles = tuple(
        role for role in FOUR_ROLE_COMPARATOR_ORDER if role not in role_context_slices
    )
    missing_trace_roles = tuple(
        role for role in FOUR_ROLE_COMPARATOR_ORDER if role not in traced_roles
    )
    normalized_errors = tuple(str(item).strip() for item in contract_errors if str(item).strip())
    passed = not (
        plan_gate.missing_plan_roles
        or missing_context_roles
        or missing_trace_roles
        or normalized_errors
    )
    observed_roles = tuple(
        dict.fromkeys(
            [
                *plan_gate.observed_roles,
                *tuple(role_context_slices.keys()),
                *tuple(sorted(traced_roles)),
            ]
        )
    )
    return CarrierFairnessGate(
        passed=passed,
        observed_roles=observed_roles,
        missing_plan_roles=plan_gate.missing_plan_roles,
        missing_context_roles=missing_context_roles,
        missing_trace_roles=missing_trace_roles,
        contract_errors=normalized_errors,
    )
