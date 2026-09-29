"""Runtime-owned route selection and evidence for contest-core variants.

The route is a control-plane request.  It never grants a capability or
executes a provider; the existing Dispatcher/Runtime still owns those steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from statebus.contracts import ExecutionKind, RiskClass


ROUTE_RUNTIME_POLICY = "runtime_policy"
ROUTE_REGISTERED_DSL = "registered_dsl"
ROUTE_BOUNDED_PYTHON = "bounded_python"
ROUTE_CODEACT_OFF = "codeact_off"
ROUTE_WRONG = "wrong_route"
ROUTES = frozenset(
    {
        ROUTE_RUNTIME_POLICY,
        ROUTE_REGISTERED_DSL,
        ROUTE_BOUNDED_PYTHON,
        ROUTE_CODEACT_OFF,
        ROUTE_WRONG,
    }
)


@dataclass(frozen=True)
class RouteDecision:
    requested_route: str
    effective_route: str
    execution_kind: str
    accepted: bool
    failure_reason: str = ""

    def canonical_payload(self) -> dict[str, object]:
        return {
            "requested_route": self.requested_route,
            "effective_route": self.effective_route,
            "execution_kind": self.execution_kind,
            "accepted": self.accepted,
            "failure_reason": self.failure_reason,
        }


def _kind(value: Any) -> str:
    if isinstance(value, ExecutionKind):
        return value.value
    return str(value or "").strip()


def resolve_execution_route(
    requested_route: str | None,
    *,
    descriptor_execution_kind: Any,
    selected_execution_kind: Any = None,
    allow_llm_python: bool = False,
    risk_class: Any = None,
) -> RouteDecision:
    """Resolve a requested route without silently changing its meaning."""

    requested = str(requested_route or ROUTE_RUNTIME_POLICY).strip().lower()
    if requested == "auto":
        requested = ROUTE_RUNTIME_POLICY
    selected = _kind(selected_execution_kind) or _kind(descriptor_execution_kind)
    descriptor = _kind(descriptor_execution_kind)
    if requested not in ROUTES:
        return RouteDecision(
            requested_route=requested,
            effective_route="",
            execution_kind=selected,
            accepted=False,
            failure_reason="unknown_route",
        )
    if requested == ROUTE_WRONG:
        return RouteDecision(
            requested_route=requested,
            effective_route="",
            execution_kind=selected,
            accepted=False,
            failure_reason="wrong_route_negative_control",
        )
    if requested == ROUTE_RUNTIME_POLICY:
        if selected == ExecutionKind.LLM_BOUNDED_PYTHON.value:
            if not allow_llm_python or _kind(risk_class) != RiskClass.BOUNDED_CODE.value:
                return RouteDecision(
                    requested_route=requested,
                    effective_route="",
                    execution_kind=selected,
                    accepted=False,
                    failure_reason="bounded_python_not_authorized",
                )
            effective = ROUTE_BOUNDED_PYTHON
        elif selected == ExecutionKind.TRANSFORM_DSL.value:
            effective = ROUTE_REGISTERED_DSL
        else:
            effective = ROUTE_RUNTIME_POLICY
        return RouteDecision(requested, effective, selected, True)
    if requested == ROUTE_REGISTERED_DSL:
        accepted = selected == ExecutionKind.TRANSFORM_DSL.value and descriptor == selected
        return RouteDecision(
            requested_route=requested,
            effective_route=requested if accepted else "",
            execution_kind=selected,
            accepted=accepted,
            failure_reason="registered_dsl_route_mismatch" if not accepted else "",
        )
    if requested == ROUTE_BOUNDED_PYTHON:
        accepted = (
            selected == ExecutionKind.LLM_BOUNDED_PYTHON.value
            and descriptor == selected
            and allow_llm_python
            and _kind(risk_class) == RiskClass.BOUNDED_CODE.value
        )
        reason = "bounded_python_route_mismatch" if not accepted else ""
        if selected == ExecutionKind.LLM_BOUNDED_PYTHON.value and not allow_llm_python:
            reason = "bounded_python_not_authorized"
        return RouteDecision(
            requested_route=requested,
            effective_route=requested if accepted else "",
            execution_kind=selected,
            accepted=accepted,
            failure_reason=reason,
        )
    # codeact_off is an explicit negative/control route.  It may select a
    # registered DSL, but it must never turn a bounded-Python capability into
    # a direct success or a hidden provider fallback.
    if selected == ExecutionKind.LLM_BOUNDED_PYTHON.value:
        return RouteDecision(
            requested_route=requested,
            effective_route="",
            execution_kind=selected,
            accepted=False,
            failure_reason="codeact_disabled_for_bounded_python",
        )
    effective = ROUTE_REGISTERED_DSL if selected == ExecutionKind.TRANSFORM_DSL.value else ROUTE_RUNTIME_POLICY
    return RouteDecision(requested, effective, selected, True)

