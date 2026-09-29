from __future__ import annotations

from pathlib import Path

import pytest

from statebus.benchmark.model_assist_utility.runtime_path import (
    UTILITY_EXECUTOR_CAPABILITY,
    UTILITY_SUITE_ID,
    run_utility_runtime,
)
from statebus.contracts.adaptive import TransformProgram, TransformStep
from statebus.runtime.role_providers import (
    ExecutorCandidateReviewBinding,
    ExecutorCandidateReviewDecision,
    ProviderCandidate,
)
from statebus.utils import sha256_digest


_ROWS = ({"candidate_id": "alpha", "label": "authorized source", "source_locator": "source.md#alpha"},)
_INPUT_FIELDS = {key: "string" for key in _ROWS[0]}
_OUTPUT_SCHEMA = {"candidate_id": "string", "source_locator": "string"}


def _run_utility(
    tmp_path: Path,
    *,
    executor_handler,
    review,
    allow_replan: bool,
    repair_factory=None,
):
    return run_utility_runtime(
        slot_id="utility-review-test",
        run_id="utility-review-test-run",
        runtime_root=tmp_path / "runtime",
        workspace_root=tmp_path / "workspace",
        task_question="Select the authorized source.",
        task_family="evidence-routing:test",
        task_arguments={"case_id": "test"},
        source_hash=sha256_digest(_ROWS),
        rows=_ROWS,
        input_fields=_INPUT_FIELDS,
        output_schema=_OUTPUT_SCHEMA,
        executor_handler=executor_handler,
        summarizer_handler=lambda _request: ProviderCandidate(
            False, "failure", error_code="test_summarizer_stop"
        ),
        executor_candidate_review=ExecutorCandidateReviewBinding(
            suite_id=UTILITY_SUITE_ID,
            capability_id=UTILITY_EXECUTOR_CAPABILITY,
            review=review,
        ),
        transform_program_repair_factory=repair_factory,
        allow_evidence_replan=allow_replan,
    )


def _program_candidate(request) -> ProviderCandidate:
    evidence_ref = next(
        str(item["ref_id"])
        for item in request.role_context.verified_input_payloads
        if item.get("kind") == "canonical_evidence_pack"
    )
    return ProviderCandidate(
        True,
        "executor_program",
        TransformProgram(
            program_id=f"candidate:{request.step.step_id}",
            input_artifact_refs=(evidence_ref,),
            operations=(TransformStep("select", {"columns": ["candidate_id", "source_locator"]}),),
            output_contract_version=request.step.output_contract_version,
        ),
    )


def test_candidate_review_replan_uses_a_fresh_attempt_and_grant(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STATEBUS_MODEL_ASSIST_UTILITY_ENABLED", "1")
    invocations: list[tuple[str, str, str]] = []
    decisions: list[str] = []

    def executor_handler(request):
        grant = request.bound_grant.grant
        invocations.append((request.step.step_id, grant.attempt_id, grant.grant_hash))
        return _program_candidate(request)

    def review(request, _candidate):
        decisions.append(request.step.step_id)
        action = "request_evidence_recheck" if request.step.step_id == "execute" else "continue"
        return ExecutorCandidateReviewDecision(action, "test_review")

    result = _run_utility(tmp_path, executor_handler=executor_handler, review=review, allow_replan=True)

    records = result.context.executor_candidate_review_records
    assert decisions == ["execute", "execute_full"]
    assert [item["step_id"] for item in records] == decisions
    assert len({item["attempt_id"] for item in records}) == 2
    assert len({item["grant_hash"] for item in records}) == 2
    assert invocations[0][1:] == (records[0]["attempt_id"], records[0]["grant_hash"])
    assert invocations[1][1:] == (records[1]["attempt_id"], records[1]["grant_hash"])


def test_candidate_review_abstain_stops_before_verified_executor_artifact(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STATEBUS_MODEL_ASSIST_UTILITY_ENABLED", "1")
    calls: list[str] = []

    def executor_handler(_request):
        calls.append("executor")
        return ProviderCandidate(False, "failure", error_code="model_assist_insufficient_evidence")

    def review(_request, _candidate):
        return ExecutorCandidateReviewDecision("abstain", "unresolved_test_case")

    result = _run_utility(tmp_path, executor_handler=executor_handler, review=review, allow_replan=True)

    assert calls == ["executor"]
    assert result.context.executor_candidate_review_records[0]["action"] == "abstain"
    assert result.runtime.dispatches[-1].error_code == "need_more_evidence"
    assert not any(
        getattr(item, "artifact", None) is not None
        and item.artifact.produced_by == "executor"
        for item in result.context.artifacts.values()
    )


def test_candidate_review_binding_is_off_without_utility_flag(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("STATEBUS_MODEL_ASSIST_UTILITY_ENABLED", raising=False)
    with pytest.raises(ValueError, match="model_assist_utility_flag_required_for_candidate_review"):
        _run_utility(
            tmp_path,
            executor_handler=lambda _request: pytest.fail("provider must not run"),
            review=lambda _request, _candidate: ExecutorCandidateReviewDecision("continue"),
            allow_replan=False,
        )


def test_transform_program_repair_factory_is_wired_and_bounded_to_one_call(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STATEBUS_MODEL_ASSIST_UTILITY_ENABLED", "1")
    repair_calls: list[dict[str, object]] = []

    def executor_handler(request):
        evidence_ref = next(
            str(item["ref_id"])
            for item in request.role_context.verified_input_payloads
            if item.get("kind") == "canonical_evidence_pack"
        )
        return ProviderCandidate(
            True,
            "executor_program",
            TransformProgram(
                program_id="rejected-candidate",
                input_artifact_refs=(evidence_ref,),
                operations=(TransformStep("select", {"columns": ["missing_column"]}),),
                output_contract_version=request.step.output_contract_version,
            ),
        )

    def repair_factory(
        step,
        grant,
        input_ref_id,
        rows,
        validation_errors,
        *,
        previous_program,
        repair_stage,
        input_tables,
    ):
        repair_calls.append({
            "step_id": step.step_id,
            "attempt_id": grant.attempt_id,
            "input_ref_id": input_ref_id,
            "row_count": len(rows),
            "validation_errors": validation_errors,
            "previous_program_hash": previous_program.program_hash,
            "repair_stage": repair_stage,
            "input_tables": tuple(input_tables),
        })
        return TransformProgram(
            program_id="repaired-candidate",
            input_artifact_refs=(input_ref_id,),
            operations=(TransformStep("select", {"columns": ["candidate_id", "source_locator"]}),),
            output_contract_version=step.output_contract_version,
        )

    result = run_utility_runtime(
        slot_id="utility-transform-repair-test",
        run_id="utility-transform-repair-test-run",
        runtime_root=tmp_path / "runtime",
        workspace_root=tmp_path / "workspace",
        task_question="Select the authorized source.",
        task_family="evidence-routing:test",
        task_arguments={"case_id": "test"},
        source_hash=sha256_digest(_ROWS),
        rows=_ROWS,
        input_fields=_INPUT_FIELDS,
        output_schema=_OUTPUT_SCHEMA,
        executor_handler=executor_handler,
        summarizer_handler=lambda _request: ProviderCandidate(
            False, "failure", error_code="test_summarizer_stop"
        ),
        transform_program_repair_factory=repair_factory,
    )

    assert len(repair_calls) == 1
    assert repair_calls[0]["step_id"] == "execute"
    assert repair_calls[0]["repair_stage"] == "execution_validation"
    assert repair_calls[0]["validation_errors"]
    assert any(
        getattr(item, "artifact", None) is not None
        and item.artifact.produced_by == "executor"
        for item in result.context.artifacts.values()
    )


def test_nova_transform_contract_runs_through_runtime_with_derived_rate_schema(tmp_path, monkeypatch) -> None:
    from statebus.benchmark.model_assist_utility.runner import _runtime_input_schema

    monkeypatch.delenv("STATEBUS_MODEL_ASSIST_UTILITY_ENABLED", raising=False)
    active_rule_id = "R-NOV-SAMPLE-2026"
    rows = (
        {
            "quarter": "2026Q1", "status": "APPROVED", "scope": "approved_sample_cohort",
            "effective_rule_id": active_rule_id, "on_time_orders": 80, "committed_orders": 100,
            "source_locator": "ledger/nova.json#q1-valid",
        },
        {
            "quarter": "2026Q3", "status": "APPROVED", "scope": "approved_sample_cohort",
            "effective_rule_id": active_rule_id, "on_time_orders": 90, "committed_orders": 120,
            "source_locator": "ledger/nova.json#q3-valid",
        },
        {
            "quarter": "2026Q3", "status": "CANCELLED", "scope": "approved_sample_cohort",
            "effective_rule_id": active_rule_id, "on_time_orders": 100, "committed_orders": 100,
            "source_locator": "ledger/nova.json#q3-cancelled",
        },
    )
    output_schema = {
        "quarter": "string",
        "on_time": "number",
        "committed": "number",
        "record_count": "number",
        "rate_pct": "number",
    }
    rule = {
        "rule_id": active_rule_id,
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
        "eligible_scope": "approved_sample_cohort",
        "source_locator": "rules/nova.json#active",
    }

    def executor_handler(request):
        evidence_ref = next(
            str(item["ref_id"])
            for item in request.role_context.verified_input_payloads
            if item.get("kind") == "canonical_evidence_pack"
        )
        return ProviderCandidate(
            True,
            "executor_program",
            TransformProgram(
                program_id="nova-contract-program",
                input_artifact_refs=(evidence_ref,),
                operations=(
                    TransformStep("filter_eq", {"column": "status", "value": "APPROVED"}),
                    TransformStep("filter_eq", {"column": "scope", "value": "approved_sample_cohort"}),
                    TransformStep("filter_eq", {"column": "effective_rule_id", "value": active_rule_id}),
                    TransformStep("filter_in", {"column": "quarter", "values": ["2026Q1", "2026Q3"]}),
                    TransformStep("aggregate_grouped", {
                        "group_fields": ["quarter"],
                        "value_fields": ["on_time_orders", "committed_orders", "on_time_orders"],
                        "functions": ["sum", "sum", "count"],
                        "outputs": ["on_time", "committed", "record_count"],
                    }),
                    TransformStep("derive_safe", {
                        "calculations": [["rate_pct", "ratio", "on_time", "committed", 100, 4]],
                    }),
                    TransformStep("select", {
                        "columns": ["quarter", "on_time", "committed", "record_count", "rate_pct"],
                    }),
                ),
                output_contract_version=request.step.output_contract_version,
            ),
        )

    result = run_utility_runtime(
        slot_id="utility-nova-contract-test",
        run_id="utility-nova-contract-test-run",
        runtime_root=tmp_path / "runtime",
        workspace_root=tmp_path / "workspace",
        task_question="Calculate weighted Q1 and Q3 delivery rates.",
        task_family="approved sample weighted delivery rate analysis",
        task_arguments={"case_id": "MU-NOVA-TEST"},
        source_hash=sha256_digest(rows),
        rows=rows,
        additional_evidence=({**rule, "text": "Active rule for approved sample cohort."},),
        input_fields=_runtime_input_schema(rows),
        output_schema=output_schema,
        executor_handler=executor_handler,
        summarizer_handler=lambda _request: ProviderCandidate(
            False, "failure", error_code="test_summarizer_stop"
        ),
    )

    executor_stored = next(
        item for item in result.context.artifacts.values()
        if item.artifact.produced_by == "executor"
    )
    actual = {str(row["quarter"]): dict(row) for row in executor_stored.rows}
    assert actual == {
        "2026Q1": {"quarter": "2026Q1", "on_time": 80, "committed": 100, "record_count": 1, "rate_pct": 80.0},
        "2026Q3": {"quarter": "2026Q3", "on_time": 90, "committed": 120, "record_count": 1, "rate_pct": 75.0},
    }
