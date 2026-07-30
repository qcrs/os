from __future__ import annotations

import pytest
import time

from statebus.contracts import CapabilityGrant, RefStatus, TransformProgram, TransformStep
from statebus.runtime.transform_dsl import TransformDslInterpreter, TransformProgramError, TransformProgramValidator


def test_transform_dsl_produces_stable_metric_result() -> None:
    program = TransformProgram(
        program_id="program", input_artifact_refs=("table",), output_contract_version="statebus.metric_series.v1",
        operations=(
            TransformStep("filter_in", {"column": "quarter", "values": ["2026Q1", "2026Q2"]}),
            TransformStep("sort", {"columns": ["quarter"]}),
            TransformStep("select", {"columns": ["quarter", "revenue"]}),
        ),
    )
    result = TransformDslInterpreter().run(program, inputs={"table": [{"quarter": "2026Q2", "revenue": 12}, {"quarter": "2026Q1", "revenue": 10}]})
    assert result == [{"quarter": "2026Q1", "revenue": 10}, {"quarter": "2026Q2", "revenue": 12}]


def test_transform_dsl_renames_fields_without_changing_values() -> None:
    program = TransformProgram(
        program_id="rename",
        input_artifact_refs=("table",),
        output_contract_version="statebus.analysis_result.v2",
        operations=(
            TransformStep("select", {"columns": ["metric", "value"]}),
            TransformStep("rename", {"source": "metric", "target": "metric_name"}),
            TransformStep("rename", {"source": "value", "target": "metric_value"}),
        ),
    )

    result = TransformDslInterpreter().run(
        program,
        inputs={"table": [{"metric": "revenue", "value": 120.0}]},
    )

    assert result == [{"metric_name": "revenue", "metric_value": 120.0}]


def test_transform_dsl_rejects_rename_over_existing_field() -> None:
    program = TransformProgram(
        program_id="rename-collision",
        input_artifact_refs=("table",),
        output_contract_version="statebus.analysis_result.v2",
        operations=(TransformStep("rename", {"source": "value", "target": "metric"}),),
    )

    with pytest.raises(TransformProgramError, match="rename_target_exists"):
        TransformDslInterpreter().run(
            program,
            inputs={"table": [{"metric": "revenue", "value": 120.0}]},
        )


def test_transform_dsl_rejects_embedded_python_and_unapproved_ref() -> None:
    program = TransformProgram(
        program_id="bad", input_artifact_refs=("not-authorized",), output_contract_version="statebus.metric_series.v1",
        operations=(TransformStep("derive_safe", {"formula": "__import__('os')"}),),
    )
    with pytest.raises(TransformProgramError):
        TransformDslInterpreter().run(program, inputs={"table": [{"x": 1}]})


def test_transform_dsl_rejects_nested_code_paths_types_and_scale() -> None:
    inputs = {"table": [{"x": 1}, {"x": 2}], "other": [{"x": 1}, {"x": 2}]}
    nested_code = TransformProgram(
        program_id="nested", input_artifact_refs=("table",), output_contract_version="statebus.metric_series.v1",
        operations=(TransformStep("filter_in", {"column": "x", "values": ["__import__('os')"]}),),
    )
    with pytest.raises(TransformProgramError, match="unsafe_argument_value"):
        TransformDslInterpreter().run(nested_code, inputs=inputs)
    oversized_limit = TransformProgram(
        program_id="limit", input_artifact_refs=("table",), output_contract_version="statebus.metric_series.v1",
        operations=(TransformStep("limit", {"count": 100_001}),),
    )
    with pytest.raises(TransformProgramError, match="limit_exceeded"):
        TransformDslInterpreter(TransformProgramValidator(max_rows=2)).run(oversized_limit, inputs=inputs)
    oversized_join = TransformProgram(
        program_id="join", input_artifact_refs=("table", "other"), output_contract_version="statebus.metric_series.v1",
        operations=(TransformStep("join_by_key", {"right_ref": "other", "left_key": "x", "right_key": "x"}),),
    )
    with pytest.raises(TransformProgramError, match="join_budget_exceeded"):
        TransformDslInterpreter(TransformProgramValidator(max_join_rows=2)).run(oversized_join, inputs=inputs)


def test_transform_dsl_signs_only_schema_and_quality_valid_fixed_output(tmp_path) -> None:
    program = TransformProgram(
        program_id="verified", input_artifact_refs=("table",), output_contract_version="statebus.metric_series.v1",
        operations=(TransformStep("select", {"columns": ["quarter", "revenue"]}),),
    )
    grant = CapabilityGrant(
        grant_id="grant", task_id="task", session_id="session", step_id="step", attempt_id="attempt",
        capability_id="extract_metric_series_v1", capability_version="v1", input_ref_ids=("table",),
        output_contract_version="statebus.metric_series.v1", workspace_root_id="workspace", max_runtime_ms=1_000,
        expires_at_ns=time.time_ns() + 1_000_000_000, approved_plan_hash="plan",
    )
    interpreter = TransformDslInterpreter()
    result = interpreter.run_verified(
        program, inputs={"table": [{"quarter": "2026Q1", "revenue": 12.0}]}, grant=grant,
        attempt_workspace=tmp_path, output_schema={"quarter": "string", "revenue": "number"},
        quality_validator=lambda rows: len(rows) == 1,
    )
    assert result.artifact.verification_state == RefStatus.VERIFIED
    assert (tmp_path / "outputs" / "transform_result.json").is_file()
    with pytest.raises(TransformProgramError, match="output_schema_fields_mismatch"):
        interpreter.run_verified(
            program, inputs={"table": [{"quarter": "2026Q1", "revenue": 12.0}]}, grant=grant,
            attempt_workspace=tmp_path / "bad", output_schema={"revenue": "number"},
        )


def test_transform_dsl_schema_gate_accepts_only_real_boolean_anomaly_flags(tmp_path) -> None:
    program = TransformProgram(
        program_id="anomaly", input_artifact_refs=("table",), output_contract_version="statebus.anomaly_report.v1",
        operations=(TransformStep("anomaly_check", {"column": "revenue", "output": "is_anomaly"}),),
    )
    grant = CapabilityGrant(
        grant_id="grant", task_id="task", session_id="session", step_id="step", attempt_id="attempt",
        capability_id="detect_anomaly_v1", capability_version="v1", input_ref_ids=("table",),
        output_contract_version="statebus.anomaly_report.v1", workspace_root_id="workspace", max_runtime_ms=1_000,
        expires_at_ns=time.time_ns() + 1_000_000_000, approved_plan_hash="plan",
    )
    result = TransformDslInterpreter().run_verified(
        program,
        inputs={"table": [{"revenue": 10.0}, {"revenue": 11.0}, {"revenue": 100.0}]},
        grant=grant,
        attempt_workspace=tmp_path,
        output_schema={"revenue": "number", "is_anomaly": "boolean"},
    )
    assert all(isinstance(row["is_anomaly"], bool) for row in result.rows)


def test_transform_dsl_supports_bounded_compare_grouped_aggregate_and_zscore_fallbacks() -> None:
    interpreter = TransformDslInterpreter()
    comparison = TransformProgram(
        program_id="compare", input_artifact_refs=("metrics",), output_contract_version="statebus.comparison.v1",
        operations=(TransformStep("compare_periods", {
            "period_field": "quarter", "value_field": "revenue", "carry_fields": ["ticker"],
        }),),
    )
    compared = interpreter.run(comparison, inputs={"metrics": [
        {"ticker": "ACME", "quarter": "2026Q2", "revenue": 125.0},
        {"ticker": "ACME", "quarter": "2026Q1", "revenue": 100.0},
    ]})[0]
    assert compared["ticker"] == "ACME"
    assert compared["growth_pct"] == 25.0
    with pytest.raises(TransformProgramError, match="comparison_carry_field_not_invariant"):
        interpreter.run(comparison, inputs={"metrics": [
            {"ticker": "ACME", "quarter": "2026Q1", "revenue": 100.0},
            {"ticker": "BETA", "quarter": "2026Q2", "revenue": 125.0},
        ]})
    aggregation = TransformProgram(
        program_id="aggregate", input_artifact_refs=("metrics",), output_contract_version="statebus.aggregation.v1",
        operations=(TransformStep("aggregate_grouped", {"group_field": "segment", "value_field": "revenue"}),),
    )
    rows = interpreter.run(aggregation, inputs={"metrics": [
        {"segment": "a", "revenue": 10.0}, {"segment": "a", "revenue": 30.0},
    ]})
    assert rows == [{"count": 2, "max": 30.0, "mean": 20.0, "min": 10.0, "segment": "a", "sum": 40.0}]


def test_transform_validator_tracks_columns_across_operations() -> None:
    valid = TransformProgram(
        program_id="derived-columns",
        input_artifact_refs=("metrics",),
        output_contract_version="statebus.comparison.v1",
        operations=(
            TransformStep("compare_periods", {
                "period_field": "quarter",
                "value_field": "revenue",
                "growth_pct_output": "requested_growth_pct",
            }),
            TransformStep("select", {"columns": ["difference", "requested_growth_pct"]}),
        ),
    )
    report = TransformProgramValidator().validate(
        valid,
        authorized_input_refs=("metrics",),
        available_columns={"metrics": ("quarter", "revenue")},
    )
    assert report.ok

    invalid = TransformProgram(
        program_id="dropped-column",
        input_artifact_refs=("metrics",),
        output_contract_version="statebus.aggregation.v1",
        operations=(
            TransformStep("aggregate", {"column": "revenue", "function": "mean", "output": "mean_revenue"}),
            TransformStep("sort", {"columns": ["quarter"]}),
        ),
    )
    report = TransformProgramValidator().validate(
        invalid,
        authorized_input_refs=("metrics",),
        available_columns={"metrics": ("quarter", "revenue")},
    )
    assert not report.ok
    assert report.error_code == "unknown_column"
    assert report.operation_index == 1
