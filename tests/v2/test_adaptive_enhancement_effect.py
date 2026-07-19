from __future__ import annotations

from scripts.v2_diagnostics import run_adaptive_enhancement_effect as effect


def test_effect_probe_is_single_case_and_not_legacy_matrix_or_formal() -> None:
    assert effect._PROBE_TASK_NAME == "anomaly"
    source = effect.Path(effect.__file__).read_text(encoding="utf-8")
    assert "run_adaptive_mode_matrix.py" not in source
    assert '"--formal"' not in source
    assert '"--compare"' not in source


def test_counterfactual_changes_only_the_last_authorized_metric() -> None:
    rows = (
        {"quarter": "2026Q1", "on_time_delivery_pct": 95.0},
        {"quarter": "2026Q2", "on_time_delivery_pct": 80.0},
    )
    changed = effect._counterfactual_rows(rows, value_field="on_time_delivery_pct")

    assert changed[0] == rows[0]
    assert changed[1]["quarter"] == rows[1]["quarter"]
    assert changed[1]["on_time_delivery_pct"] != rows[1]["on_time_delivery_pct"]
    assert rows[1]["on_time_delivery_pct"] == 80.0


def test_source_profile_distinguishes_analysis_from_identity_copy() -> None:
    analysis = """
import json
from pathlib import Path
def transform(rows):
    values = [row["value"] for row in rows]
    mean = sum(values) / len(values)
    return [{"value": value, "delta": value - mean, "flag": value > mean} for value in values]
rows = json.loads(Path("inputs/task.json").read_text(encoding="utf-8"))
Path("outputs/result.json").write_text(json.dumps(transform(rows)), encoding="utf-8")
"""
    identity = """
import json
from pathlib import Path
rows = json.loads(Path("inputs/task.json").read_text(encoding="utf-8"))
Path("outputs/result.json").write_text(json.dumps(rows), encoding="utf-8")
"""

    assert effect._source_profile(analysis)["computational"]
    assert not effect._source_profile(identity)["computational"]


def test_claim_row_coverage_rejects_duplicate_row_claims() -> None:
    rows = (
        {"quarter": "2026Q1", "on_time_delivery_pct": 95.0},
        {"quarter": "2026Q2", "on_time_delivery_pct": 80.0},
    )
    good_claim = {
        "claim_id": "q1",
        "status": "ready",
        "numeric_fields": {"on_time_delivery_pct": 95.0},
        "supporting_artifact_ref_ids": ["artifact"],
        "supporting_evidence_item_ids": ["evidence-q1"],
        "citation_locators": ["locator-q1"],
    }
    second_claim = {
        **good_claim,
        "claim_id": "q2",
        "numeric_fields": {"on_time_delivery_pct": 80.0},
        "supporting_evidence_item_ids": ["evidence-q2"],
        "citation_locators": ["locator-q2"],
    }
    valid = effect._claim_row_coverage([{"claims": [good_claim, second_claim]}], rows, value_field="on_time_delivery_pct")
    duplicate = effect._claim_row_coverage(
        [{"claims": [good_claim, {**good_claim, "claim_id": "other-q1"}]}],
        rows,
        value_field="on_time_delivery_pct",
    )

    assert valid["passed"]
    assert not duplicate["passed"]
    assert duplicate["matches_by_row"] == [2, 0]


def test_anomaly_quality_gate_accepts_recomputed_output_and_rejects_tampering() -> None:
    task = effect._task_definition("anomaly")
    inputs = (
        {"quarter": "2026Q1", "on_time_delivery_pct": 10.0},
        {"quarter": "2026Q2", "on_time_delivery_pct": 20.0},
    )
    outputs = (
        {
            "quarter": "2026Q1",
            "on_time_delivery_pct": 10.0,
            "baseline_mean": 15.0,
            "threshold": 5.0,
            "is_anomaly": False,
        },
        {
            "quarter": "2026Q2",
            "on_time_delivery_pct": 20.0,
            "baseline_mean": 15.0,
            "threshold": 5.0,
            "is_anomaly": False,
        },
    )
    valid = effect._quality_report(task=task, input_rows=inputs, output_rows=outputs, output_hash="valid")
    tampered = tuple([outputs[0], {**outputs[1], "baseline_mean": 16.0}])
    invalid = effect._quality_report(task=task, input_rows=inputs, output_rows=tampered, output_hash="invalid")

    assert valid.verified
    assert not invalid.verified
    assert "anomaly_recomputation_mismatch" in invalid.error_codes
