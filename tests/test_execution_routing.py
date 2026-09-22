from statebus.contracts import ExecutionKind, RiskClass
from statebus.runtime.execution_routing import (
    ROUTE_BOUNDED_PYTHON,
    ROUTE_CODEACT_OFF,
    ROUTE_REGISTERED_DSL,
    ROUTE_RUNTIME_POLICY,
    ROUTE_WRONG,
    resolve_execution_route,
)


def test_runtime_policy_selects_registered_dsl() -> None:
    decision = resolve_execution_route(
        ROUTE_RUNTIME_POLICY,
        descriptor_execution_kind=ExecutionKind.TRANSFORM_DSL,
    )

    assert decision.accepted
    assert decision.effective_route == ROUTE_REGISTERED_DSL
    assert decision.execution_kind == ExecutionKind.TRANSFORM_DSL.value


def test_explicit_bounded_python_requires_authorized_codeact() -> None:
    decision = resolve_execution_route(
        ROUTE_BOUNDED_PYTHON,
        descriptor_execution_kind=ExecutionKind.LLM_BOUNDED_PYTHON,
        allow_llm_python=True,
        risk_class=RiskClass.BOUNDED_CODE,
    )

    assert decision.accepted
    assert decision.effective_route == ROUTE_BOUNDED_PYTHON


def test_codeact_off_fails_closed_for_bounded_python() -> None:
    decision = resolve_execution_route(
        ROUTE_CODEACT_OFF,
        descriptor_execution_kind=ExecutionKind.LLM_BOUNDED_PYTHON,
        allow_llm_python=True,
        risk_class=RiskClass.BOUNDED_CODE,
    )

    assert not decision.accepted
    assert decision.effective_route == ""
    assert decision.failure_reason == "codeact_disabled_for_bounded_python"


def test_wrong_route_is_an_explicit_negative_control() -> None:
    decision = resolve_execution_route(
        ROUTE_WRONG,
        descriptor_execution_kind=ExecutionKind.TRANSFORM_DSL,
    )

    assert not decision.accepted
    assert decision.effective_route == ""
    assert decision.failure_reason == "wrong_route_negative_control"
