from __future__ import annotations

from types import SimpleNamespace

from statebus.benchmark.stage2_contract import canonical_output_projection, compare_slot_sets, public_case_projection, validate_public_case


def test_public_projection_excludes_gold_and_summary_hint() -> None:
    spec = SimpleNamespace(
        task_family="financial_report_analysis",
        intent_op="extract_metric",
        arguments={"metric": "revenue", "expected_facts": {"revenue": "999"}, "quality_checks": ["exact:revenue"], "document_path": "public.md"},
        required_outputs=("summary_text",),
    )
    sample = SimpleNamespace(canonical_task_spec=spec, task_id="case-1", task_family="financial_report_analysis", dataset_id="d", dataset_version="v1", dataset_split="test", request_text="find revenue", summary_hint="gold answer")
    projection = public_case_projection(sample)
    assert not validate_public_case(projection)
    assert "expected_facts" not in repr(projection)
    assert "summary_hint" not in repr(projection)


def test_output_projection_only_aliases_observed_revenue() -> None:
    revenue = canonical_output_projection({"summary_text": "ok", "metric_name": "revenue"}, observed_metric_name="revenue", observed_metric_value="12", output_path="out", report_path="report")
    other = canonical_output_projection({"summary_text": "ok", "metric_name": "assets", "revenue_value": "12"}, observed_metric_name="assets", observed_metric_value="12", output_path="out", report_path="report")
    assert revenue["revenue_value"] == "12"
    assert "revenue_value" not in other


def test_output_projection_keeps_source_identity_mismatch_non_blocking() -> None:
    projection = canonical_output_projection(
        {"summary_text": "correct result"},
        selected_doc_ids=("sha256:observed",),
        allowed_doc_ids=("public-task:case-1",),
        required_outputs=("summary_text",),
    )

    assert projection["projection_valid"] is True
    assert projection["projection_errors"] == []
    assert projection["provenance_valid"] is False
    assert projection["provenance_errors"] == ["unknown_doc_id:sha256:observed"]


def test_slot_set_reports_missing_extra_duplicate() -> None:
    result = compare_slot_sets(["a", "b"], ["a", "a", "c"])
    assert result == {"closed": False, "missing": ["b"], "extra": ["c"], "duplicate": ["a"]}
