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


def test_independent_recompute_matches_interpreter_for_trend_series() -> None:
    program = TransformProgram(
        program_id="independent-recompute-trend",
        input_artifact_refs=("metrics",),
        output_contract_version="statebus.analysis_result.v2",
        operations=(TransformStep("trend_series", {
            "ticker_field": "ticker",
            "period_field": "quarter",
            "metric_field": "metric",
            "value_field": "value",
            "tickers": ["ACME"],
            "periods": ["2025Q3", "2025Q4", "2026Q1"],
            "metric": "revenue",
            "ticker_output": "ticker",
            "period_output": "quarter",
            "value_output": "metric_value",
            "direction_output": "trend_direction",
        }),),
    )
    inputs = {"metrics": [
        {"ticker": "ACME", "quarter": "2025Q4", "metric": "revenue", "value": 109.0},
        {"ticker": "ACME", "quarter": "2025Q3", "metric": "revenue", "value": 98.0},
        {"ticker": "ACME", "quarter": "2026Q1", "metric": "revenue", "value": 120.0},
    ]}

    recomputed = recompute_transform_program(program, inputs=inputs)
    interpreted = TransformDslInterpreter().run(program, inputs=inputs)

    assert recomputed == tuple(interpreted)
    assert all(row["trend_direction"] == "increasing" for row in recomputed)


def test_independent_recompute_matches_interpreter_for_compare_metric() -> None:
    program = TransformProgram(
        program_id="independent-recompute-compare-metric",
        input_artifact_refs=("metrics",),
        output_contract_version="statebus.analysis_result.v2",
        operations=(TransformStep("compare_metric", {
            "ticker_field": "ticker",
            "period_field": "quarter",
            "metric_field": "metric",
            "value_field": "value",
            "left_ticker": "ACME",
            "right_ticker": "BETA",
            "period": "2026Q1",
            "metric": "revenue",
            "period_output": "quarter",
            "left_output": "acme_revenue_value",
            "right_output": "beta_revenue_value",
            "gap_output": "gap_value",
        }),),
    )
    inputs = {"metrics": [
        {"ticker": "ACME", "quarter": "2026Q1", "metric": "revenue", "value": 120.0},
        {"ticker": "BETA", "quarter": "2026Q1", "metric": "revenue", "value": 87.0},
    ]}

    recomputed = recompute_transform_program(program, inputs=inputs)
    interpreted = TransformDslInterpreter().run(program, inputs=inputs)

    assert recomputed == tuple(interpreted) == ({
        "quarter": "2026Q1",
        "acme_revenue_value": 120.0,
        "beta_revenue_value": 87.0,
        "gap_value": 33.0,
    },)
