from __future__ import annotations

import pytest

from runtime.role_contracts import (
    FOUR_ROLE_COMPARATOR_ORDER,
    RoleExecutionContract,
    default_role_execution_contracts,
    normalize_comparator_role_name,
)


def test_role_name_normalization_accepts_step_aliases() -> None:
    assert normalize_comparator_role_name("retrieve") == "retriever"
    assert normalize_comparator_role_name("execute") == "executor"
    assert normalize_comparator_role_name("summarize") == "summarizer"


def test_role_name_normalization_rejects_unknown_role() -> None:
    with pytest.raises(ValueError, match="unsupported comparator role"):
        normalize_comparator_role_name("validate")


def test_default_role_contracts_cover_four_role_comparator() -> None:
    contracts = default_role_execution_contracts()

    assert tuple(contracts) == FOUR_ROLE_COMPARATOR_ORDER
    assert contracts["retriever"].required_upstream_roles == ("planner",)
    assert "EXECUTOR_DECISION_PACKET" in contracts["executor"].allowed_input_state_kinds


def test_role_execution_contract_normalizes_role_and_upstream() -> None:
    contract = RoleExecutionContract(
        role="summarize",
        owner_agent="summarizer",
        consumes_text_handoff=True,
        consumes_typed_state=True,
        required_upstream_roles=("execute",),
    )

    assert contract.role == "summarizer"
    assert contract.required_upstream_roles == ("executor",)
