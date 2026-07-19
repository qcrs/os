from __future__ import annotations

from v2.contracts import CanonicalTaskSpec
from v2.retrieval import RetrieverFanoutPipeline
from v2.runtime.evidence_projection import EvidenceProjectionAdapter


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
