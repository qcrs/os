from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from protocol.messages import Plan
from runtime.role_contracts import FOUR_ROLE_COMPARATOR_ORDER, normalize_comparator_role_name

ALLOWED_AUXILIARY_ROLES = frozenset({"validate"})
TEXT_LANE_CARRIERS = frozenset(
    {
        "text",
        "text_whole_lane",
        "text_brief",
        "text_packet_minimal",
        "text_strict_pure_lane",
        "natural_handoff_text",
        "inline_text_handoff",
    }
)
PROTOCOL_LANE_CARRIERS = frozenset(
    {
        "state_ref",
        "state_packet_minimal",
        "protocol_feature_only_typed_state",
        "protocol_full_rich_audit",
        "protocol_minimal_state_packet",
    }
)


@dataclass(frozen=True)
class CarrierFairnessGate:
    passed: bool
    fail_closed: bool = True
    required_roles: tuple[str, ...] = FOUR_ROLE_COMPARATOR_ORDER
    observed_roles: tuple[str, ...] = ()
    missing_plan_roles: tuple[str, ...] = ()
    missing_context_roles: tuple[str, ...] = ()
    missing_trace_roles: tuple[str, ...] = ()
    graph_mismatch_roles: tuple[str, ...] = ()
    mega_prompt_roles: tuple[str, ...] = ()
    text_typed_state_leak_roles: tuple[str, ...] = ()
    unbounded_projection_roles: tuple[str, ...] = ()
    model_visibility_mismatch_roles: tuple[str, ...] = ()
    tool_visibility_mismatch_roles: tuple[str, ...] = ()
    corpus_visibility_mismatch_roles: tuple[str, ...] = ()
    hidden_helper_roles: tuple[str, ...] = ()
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
            "graph_mismatch_roles": list(self.graph_mismatch_roles),
            "mega_prompt_roles": list(self.mega_prompt_roles),
            "text_typed_state_leak_roles": list(self.text_typed_state_leak_roles),
            "unbounded_projection_roles": list(self.unbounded_projection_roles),
            "model_visibility_mismatch_roles": list(self.model_visibility_mismatch_roles),
            "tool_visibility_mismatch_roles": list(self.tool_visibility_mismatch_roles),
            "corpus_visibility_mismatch_roles": list(self.corpus_visibility_mismatch_roles),
            "hidden_helper_roles": list(self.hidden_helper_roles),
            "contract_errors": list(self.contract_errors),
        }


def evaluate_plan_fairness_gate(plan: Plan) -> CarrierFairnessGate:
    observed: list[str] = ["planner"]
    graph_mismatch_roles: list[str] = []
    for step in plan.steps:
        raw_role = (step.semantic_role or step.step_id).strip().lower()
        if not raw_role:
            continue
        try:
            normalized = normalize_comparator_role_name(raw_role)
        except ValueError:
            if raw_role not in ALLOWED_AUXILIARY_ROLES:
                graph_mismatch_roles.append(raw_role)
            continue
        observed.append(normalized)
    observed_roles = tuple(dict.fromkeys(observed))
    missing_plan_roles = tuple(
        role for role in FOUR_ROLE_COMPARATOR_ORDER if role not in observed_roles
    )
    graph_mismatch_roles_tuple = tuple(sorted(dict.fromkeys(graph_mismatch_roles)))
    passed = not missing_plan_roles and not graph_mismatch_roles_tuple
    return CarrierFairnessGate(
        passed=passed,
        observed_roles=observed_roles,
        missing_plan_roles=missing_plan_roles,
        graph_mismatch_roles=graph_mismatch_roles_tuple,
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
    trace_index: dict[str, dict[str, Any]] = {}
    for item in role_trace:
        raw_role = str(item.get("role", "")).strip().lower()
        if not raw_role:
            continue
        try:
            normalized = normalize_comparator_role_name(raw_role)
        except ValueError:
            continue
        traced_roles.add(normalized)
        trace_index[normalized] = dict(item)

    normalized_slices = {
        normalize_comparator_role_name(role): slice_view
        for role, slice_view in role_context_slices.items()
        if str(role).strip()
    }

    missing_context_roles = tuple(
        role for role in FOUR_ROLE_COMPARATOR_ORDER if role not in normalized_slices
    )
    missing_trace_roles = tuple(
        role for role in FOUR_ROLE_COMPARATOR_ORDER if role not in traced_roles
    )

    mega_prompt_roles: list[str] = []
    text_typed_state_leak_roles: list[str] = []
    unbounded_projection_roles: list[str] = []
    model_visibility_mismatch_roles: list[str] = []
    tool_visibility_mismatch_roles: list[str] = []
    corpus_visibility_mismatch_roles: list[str] = []
    hidden_helper_roles: list[str] = []

    for role, slice_view in normalized_slices.items():
        carrier = str(getattr(slice_view, "carrier", "")).strip()
        visible_state_ids = tuple(getattr(slice_view, "visible_state_ids", ()))
        projection_class = str(getattr(slice_view, "projection_class", "")).strip()
        included_fields = tuple(getattr(slice_view, "included_fields", ()))
        omitted_fields = tuple(getattr(slice_view, "omitted_fields", ()))
        role_visible_contract = str(getattr(slice_view, "role_visible_contract", "")).strip()
        helper_visibility = str(getattr(slice_view, "helper_visibility", "")).strip()
        model_visibility = str(getattr(slice_view, "model_visibility", "")).strip()
        tool_visibility = str(getattr(slice_view, "tool_visibility", "")).strip()
        corpus_visibility = str(getattr(slice_view, "corpus_visibility", "")).strip()
        input_state_ids = tuple(trace_index.get(role, {}).get("input_state_ids", ()))

        if role not in traced_roles or role not in normalized_slices:
            mega_prompt_roles.append(role)
        if visible_state_ids != input_state_ids:
            mega_prompt_roles.append(role)
        if carrier in TEXT_LANE_CARRIERS and visible_state_ids:
            text_typed_state_leak_roles.append(role)
        if carrier in PROTOCOL_LANE_CARRIERS and (
            not projection_class or not included_fields or not omitted_fields or not role_visible_contract
        ):
            unbounded_projection_roles.append(role)
        if model_visibility != "same_model_required":
            model_visibility_mismatch_roles.append(role)
        if not tool_visibility:
            tool_visibility_mismatch_roles.append(role)
        if not corpus_visibility:
            corpus_visibility_mismatch_roles.append(role)
        if helper_visibility not in {"declared_only", "none"}:
            hidden_helper_roles.append(role)

    normalized_errors = tuple(str(item).strip() for item in contract_errors if str(item).strip())
    passed = not (
        plan_gate.missing_plan_roles
        or plan_gate.graph_mismatch_roles
        or missing_context_roles
        or missing_trace_roles
        or mega_prompt_roles
        or text_typed_state_leak_roles
        or unbounded_projection_roles
        or model_visibility_mismatch_roles
        or tool_visibility_mismatch_roles
        or corpus_visibility_mismatch_roles
        or hidden_helper_roles
        or normalized_errors
    )
    observed_roles = tuple(
        dict.fromkeys(
            [
                *plan_gate.observed_roles,
                *tuple(normalized_slices.keys()),
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
        graph_mismatch_roles=plan_gate.graph_mismatch_roles,
        mega_prompt_roles=tuple(sorted(dict.fromkeys(mega_prompt_roles))),
        text_typed_state_leak_roles=tuple(sorted(dict.fromkeys(text_typed_state_leak_roles))),
        unbounded_projection_roles=tuple(sorted(dict.fromkeys(unbounded_projection_roles))),
        model_visibility_mismatch_roles=tuple(
            sorted(dict.fromkeys(model_visibility_mismatch_roles))
        ),
        tool_visibility_mismatch_roles=tuple(
            sorted(dict.fromkeys(tool_visibility_mismatch_roles))
        ),
        corpus_visibility_mismatch_roles=tuple(
            sorted(dict.fromkeys(corpus_visibility_mismatch_roles))
        ),
        hidden_helper_roles=tuple(sorted(dict.fromkeys(hidden_helper_roles))),
        contract_errors=normalized_errors,
    )
