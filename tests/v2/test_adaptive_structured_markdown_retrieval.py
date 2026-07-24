from __future__ import annotations

from v2.contracts import CanonicalTaskSpec, TransformProgram, TransformStep
from v2.benchmark.adaptive_formal import expected_facts_report
from v2.benchmark.semantic_holdout import (
    load_semantic_holdout_cases,
    runtime_freeze_audit,
)
from v2.benchmark.adaptive_formal_mainline import (
    _formal_recomputation_repair_guidance,
)
from v2.retrieval import RetrieverFanoutPipeline
from v2.runtime.evidence_projection import EvidenceProjectionAdapter
from v2.runtime.transform_dsl import TransformDslInterpreter
from v2.utils import stable_json_dumps


def test_repo_local_structured_markdown_rows_retain_full_row_metadata() -> None:
    pipeline = RetrieverFanoutPipeline.with_embedding_mode("deterministic")
    spec = CanonicalTaskSpec(
        task_family="continuous_long_doc_table_analysis",
        intent_op="analyze_document",
        required_outputs=("aggregation",),
        arguments={
            "dataset_id": "adaptive_operating_metrics",
            "document_path": (
                "v2/benchmark/samples/continuous_task_families/"
                "adaptive_operating_metrics/adaptive_operating_metrics_2026.md"
            ),
            "metric": "revenue_musd",
        },
    )
    bundle = pipeline.run(task_id="structured-markdown", spec=spec)
    rows = [
        EvidenceProjectionAdapter._extract_row(item.metadata, item.rendered_text)
        for item in bundle.evidence_pack.hard_facts
    ]
    assert len(rows) == 3
    assert all(row is not None for row in rows)
    assert {str(row["segment"]) for row in rows if row is not None} == {"enterprise"}
    assert all("quarter" in row and "revenue_musd" in row for row in rows if row is not None)


def test_repo_local_two_column_metric_table_is_available_for_bounded_anomaly_analysis() -> None:
    pipeline = RetrieverFanoutPipeline.with_embedding_mode("deterministic")
    spec = CanonicalTaskSpec(
        task_family="continuous_long_doc_table_analysis",
        intent_op="analyze_document",
        required_outputs=("anomaly",),
        arguments={
            "dataset_id": "adaptive_operating_metrics",
            "document_path": (
                "v2/benchmark/samples/continuous_task_families/"
                "adaptive_operating_metrics/adaptive_operating_metrics_2026.md"
            ),
            "metric": "on_time_delivery_pct",
            "table_row_limit": 4,
        },
    )
    bundle = pipeline.run(task_id="two-column-anomaly", spec=spec)
    rows = [
        EvidenceProjectionAdapter._extract_row(item.metadata, item.rendered_text)
        for item in bundle.evidence_pack.hard_facts
    ]
    assert len(rows) == 4
    assert all(row is not None for row in rows)
    assert {row["quarter"] for row in rows if row is not None} == {"2025Q4", "2026Q1", "2026Q2", "2026Q3"}
    assert all("on_time_delivery_pct" in row for row in rows if row is not None)


def test_semantic_holdout_loads_complete_sources_and_keeps_gold_external() -> None:
    cases = {case.task_id: case for case in load_semantic_holdout_cases()}

    assert set(cases) == {
        "semantic-holdout-s1",
        "semantic-holdout-s2",
        "semantic-holdout-s3",
        "semantic-holdout-s4",
    }
    for task_id in ("semantic-holdout-s1", "semantic-holdout-s2"):
        rows = cases[task_id].source_rows
        assert len(rows) == 7
        assert all(row["row_kind"] == "narrative_section" for row in rows)
        assert not any("|" in str(row["text"]) for row in rows)
        assert {row["section"] for row in rows} >= {
            "Commercial backdrop",
            "Inventory observation",
            "Audit note",
        }
    assert len(cases["semantic-holdout-s3"].source_rows) == 6
    assert all(
        isinstance(row["backlog_units"], int) and isinstance(row["sla_hours"], int)
        for row in cases["semantic-holdout-s3"].source_rows
    )
    mixed_rows = cases["semantic-holdout-s4"].source_rows
    assert sum(row.get("row_kind") == "narrative_section" for row in mixed_rows) == 4
    assert sum(row.get("row_kind") == "table_row" for row in mixed_rows) == 4
    assert all(
        isinstance(row["throughput_units"], int)
        for row in mixed_rows
        if row.get("row_kind") == "table_row"
    )
    assert all(
        expected_facts_report(case, case.expected_rows)["passed"]
        for case in cases.values()
    )


def test_semantic_holdout_exposes_exact_public_labeled_fact_contract_without_answer_values() -> None:
    cases = {case.task_id: case for case in load_semantic_holdout_cases()}

    for task_id in ("semantic-holdout-s1", "semantic-holdout-s2", "semantic-holdout-s4"):
        case = cases[task_id]
        algorithm = case.operation_semantics["labeled_fact_algorithm"]
        assert "selector.label case-insensitively" in algorithm["sentence_selection"]
        assert "minimal phrase after was/is" in algorithm["value_extraction"]
        assert "selector.section exactly" in algorithm["locator_output"]
        assert "Do not split the whole section" in algorithm["value_extraction"]
        assert "re.escape(label)" in algorithm["python_regex_template"]
        assert "do not replace it with lookbehind" in algorithm["python_regex_template"]

    hidden_answer_values = {
        value
        for task_id in ("semantic-holdout-s1", "semantic-holdout-s2")
        for key, value in (cases[task_id].sample.expected_facts or {}).items()
        if not key.endswith("_locator")
    }
    public_contract = stable_json_dumps({
        task_id: cases[task_id].operation_semantics
        for task_id in ("semantic-holdout-s1", "semantic-holdout-s2")
    })
    assert all(str(value) not in public_contract for value in hidden_answer_values)

    repair_guidance = _formal_recomputation_repair_guidance(
        cases["semantic-holdout-s4"].operation_semantics
    )
    assert "assign that output field from selector.section exactly" in repair_guidance
    assert "row's locator value is provenance metadata" in repair_guidance
    assert all(str(value) not in repair_guidance for value in hidden_answer_values)


def test_semantic_holdout_table_adapter_is_type_equivalent_for_natural_dsl_lookup() -> None:
    case = next(
        case
        for case in load_semantic_holdout_cases()
        if case.task_id == "semantic-holdout-s3"
    )
    program = TransformProgram(
        program_id="semantic-holdout-s3-natural-dsl",
        input_artifact_refs=(case.source_ref_id,),
        output_contract_version=case.output_contract_version,
        operations=(
            TransformStep("filter_eq", {"column": "facility", "value": "Harbor East"}),
            TransformStep("filter_eq", {"column": "period", "value": "2026Q2"}),
            TransformStep(
                "select",
                {"columns": ["facility", "period", "backlog_units", "sla_hours"]},
            ),
        ),
    )

    rows = TransformDslInterpreter().run(
        program,
        inputs={case.source_ref_id: [dict(row) for row in case.source_rows]},
    )

    assert tuple(rows) == case.expected_rows


def test_semantic_holdout_addition_does_not_change_frozen_runtime_directories() -> None:
    audit = runtime_freeze_audit()

    assert audit["ok"], audit
    assert audit["changed_directories"] == []
    assert audit["changed_files"] == []
    assert audit["added_files"] == []
    assert audit["removed_files"] == []
    assert audit["observed_per_file_count"] == 59
