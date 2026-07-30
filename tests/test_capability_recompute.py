from __future__ import annotations

from statebus.contracts import TransformProgram, TransformStep
from statebus.runtime.capability_recompute import recompute_transform_program
from statebus.runtime.transform_dsl import TransformDslInterpreter


def test_independent_recompute_matches_the_registered_dsl_data_contract() -> None:
    program = TransformProgram(
        program_id="independent-recompute",
        input_artifact_refs=("metrics",),
        output_contract_version="statebus.metric_series.v1",
        operations=(
            TransformStep("filter_range", {"column": "revenue_musd", "min": 100.0, "max": 200.0}),
            TransformStep("sort", {"columns": ["quarter"]}),
            TransformStep("select", {"columns": ["quarter", "revenue_musd"]}),
        ),
    )

    rows = recompute_transform_program(
        program,
        inputs={
            "metrics": [
                {"quarter": "2026Q2", "revenue_musd": 130.0},
                {"quarter": "2026Q1", "revenue_musd": 120.0},
                {"quarter": "2025Q4", "revenue_musd": 90.0},
            ],
        },
    )

    assert rows == (
        {"quarter": "2026Q1", "revenue_musd": 120.0},
        {"quarter": "2026Q2", "revenue_musd": 130.0},
    )


def test_independent_recompute_matches_interpreter_for_field_rename() -> None:
    program = TransformProgram(
        program_id="independent-recompute-rename",
        input_artifact_refs=("metrics",),
        output_contract_version="statebus.analysis_result.v2",
        operations=(
            TransformStep("select", {"columns": ["metric", "value"]}),
            TransformStep("rename", {"source": "metric", "target": "metric_name"}),
            TransformStep("rename", {"source": "value", "target": "metric_value"}),
        ),
    )
    inputs = {"metrics": [{"metric": "revenue", "value": 120.0, "quarter": "2026Q1"}]}

    recomputed = recompute_transform_program(program, inputs=inputs)
    interpreted = TransformDslInterpreter().run(program, inputs=inputs)

    assert recomputed == tuple(interpreted) == ({"metric_name": "revenue", "metric_value": 120.0},)


def test_independent_recompute_matches_interpreter_for_invariant_comparison_fields() -> None:
    program = TransformProgram(
        program_id="independent-recompute-compare",
        input_artifact_refs=("metrics",),
        output_contract_version="statebus.analysis_result.v2",
        operations=(TransformStep("compare_periods", {
            "period_field": "quarter",
            "value_field": "value",
            "carry_fields": ["ticker"],
            "difference_output": "delta_value",
        }),),
    )
    inputs = {"metrics": [
        {"ticker": "BETA", "quarter": "2025Q3", "value": 72.0},
        {"ticker": "BETA", "quarter": "2026Q1", "value": 87.0},
    ]}

    recomputed = recompute_transform_program(program, inputs=inputs)
    interpreted = TransformDslInterpreter().run(program, inputs=inputs)

    assert recomputed == tuple(interpreted)
    assert recomputed[0]["ticker"] == "BETA"
    assert recomputed[0]["delta_value"] == 15.0
