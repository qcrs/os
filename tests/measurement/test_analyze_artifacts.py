from __future__ import annotations

import json
from pathlib import Path

from tools.measurement.analyze_artifacts import analyze_artifacts


def test_analyzer_keeps_roots_separate_and_deduplicates_slot_copies(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    manifest = {"schema_version": "statebus.stage2_manifest.v2", "planned_slots": [{"slot_id": "s1"}]}
    row = {"schema_version": "statebus.stage2_raw.v2", "slot_id": "s1", "pair_id": "p1", "lane": "direct_single_agent", "terminal_class": "success", "status": "success"}
    for root in (root_a, root_b):
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (root / "raw_rows.json").write_text(json.dumps([row]), encoding="utf-8")
        (root / "slot").mkdir()
        (root / "slot" / "raw_row.json").write_text(json.dumps(row), encoding="utf-8")
    summary = analyze_artifacts(artifact_roots=[root_a, root_b], output_root=tmp_path / "analysis")
    assert summary["hashes_computed"] is False
    assert summary["summary_to_raw_fallback"] is False
    assert len(summary["root_summaries"]) == 2
    assert all(item["canonical_raw_row_count"] == 1 for item in summary["root_summaries"])
    assert summary["diagnostic_counts"]["expected_mirror"] == 2
    assert summary["diagnostic_counts"].get("duplicate_identity", 0) == 0
    assert summary["blocking_diagnostic_count"] == 0
    assert summary["audited_gate_status"] == "recomputed_without_blocking_diagnostics"


def test_analyzer_reports_malformed_scope_and_conflicting_status(tmp_path: Path) -> None:
    root = tmp_path / "input"
    root.mkdir()
    (root / "events.jsonl").write_text('{"event":"ok"}\nnot-json\n', encoding="utf-8")
    (root / "receipt.json").write_text(json.dumps({"receipt_id": "", "owner": "invented"}), encoding="utf-8")
    (root / "raw_rows.json").write_text(
        json.dumps([
            {"slot_id": "s1", "status": "success", "terminal_class": "success"},
            {"slot_id": "s1", "status": "failed", "terminal_class": "mystery"},
        ]),
        encoding="utf-8",
    )
    summary = analyze_artifacts(artifact_roots=[root], output_root=tmp_path / "analysis")
    codes = summary["diagnostic_counts"]
    assert codes["malformed"] >= 1
    assert codes["empty_receipt"] == 1
    assert codes["wrong_scope"] == 1
    assert codes["duplicate_identity"] >= 1
    assert codes["conflicting_status"] >= 1


def test_analyzer_reports_conflicting_aggregate_and_slot_payloads(tmp_path: Path) -> None:
    root = tmp_path / "input"
    root.mkdir()
    aggregate = {
        "slot_id": "s1",
        "pair_id": "p1",
        "lane": "direct_single_agent",
        "status": "success",
        "terminal_class": "success",
        "provider_calls": 1,
    }
    conflict = {**aggregate, "provider_calls": 2}
    (root / "raw_rows.json").write_text(json.dumps([aggregate]), encoding="utf-8")
    (root / "slot").mkdir()
    (root / "slot" / "raw_row.json").write_text(json.dumps(conflict), encoding="utf-8")

    summary = analyze_artifacts(artifact_roots=[root], output_root=tmp_path / "analysis")

    assert summary["diagnostic_counts"]["duplicate_identity"] >= 1
    assert summary["diagnostic_counts"]["duplicate_payload_conflict"] >= 1
    assert summary["diagnostic_counts"].get("expected_mirror", 0) == 0


def test_analyzer_rejects_extra_identical_raw_row_copy(tmp_path: Path) -> None:
    root = tmp_path / "input"
    root.mkdir()
    row = {"slot_id": "s1", "pair_id": "p1", "lane": "direct_single_agent", "status": "success"}
    (root / "raw_rows.json").write_text(json.dumps([row]), encoding="utf-8")
    for dirname in ("slot-a", "slot-b"):
        slot = root / dirname
        slot.mkdir()
        (slot / "raw_row.json").write_text(json.dumps(row), encoding="utf-8")

    summary = analyze_artifacts(artifact_roots=[root], output_root=tmp_path / "analysis")

    assert summary["diagnostic_counts"]["duplicate_identity"] == 1
    assert summary["diagnostic_counts"].get("expected_mirror", 0) == 0
    assert summary["audited_gate_status"] == "inconclusive"


def test_analyzer_does_not_count_trace_or_valid_receipts_as_raw_rows(tmp_path: Path) -> None:
    root = tmp_path / "input"
    adaptive = root / "families" / "financial" / "adaptive_routed" / "case"
    adaptive.mkdir(parents=True)
    row = {"schema_version": "statebus.stage2_pilot_raw.v2", "slot_id": "s1", "pair_id": "p1", "lane": "adaptive_routed", "status": "success", "terminal_class": "success"}
    (root / "planned_slots.json").write_text(json.dumps({"slots": [{"slot_id": "s1"}]}), encoding="utf-8")
    (root / "raw_rows.json").write_text(json.dumps([row]), encoding="utf-8")
    (adaptive / "raw_row.json").write_text(json.dumps(row), encoding="utf-8")
    (adaptive / "runtime_trace.json").write_text(json.dumps({"schema_version": "statebus.canonical_trace.v1", "lane": "adaptive_routed", "terminal_status": "success"}), encoding="utf-8")
    receipts = {
        "binding_receipts.json": [{"schema_version": "statebus.execution_binding_receipt.v1", "binding_id": "b1", "attempt_id": "a1", "session_id": "session1", "step_id": "step1"}],
        "grant_receipts.json": [{"schema_version": "statebus.capability_grant.v1", "grant_id": "g1", "attempt_id": "a1", "session_id": "session1", "step_id": "step1"}],
        "artifact_verification_receipts.json": [{"schema_version": "statebus.artifact_verification_receipt.v1", "artifact_id": "artifact1", "run_id": "run1", "session_id": "session1", "decision": "VERIFIED"}],
        "semantic_consumer_receipt.json": {},
        "state_pin_receipts.json": {},
    }
    for name, payload in receipts.items():
        (adaptive / name).write_text(json.dumps(payload), encoding="utf-8")

    summary = analyze_artifacts(artifact_roots=[root], output_root=tmp_path / "analysis")

    observed = summary["root_summaries"][0]
    assert observed["raw_rows_read"] == 2
    assert observed["canonical_raw_row_count"] == observed["planned_count"] == 1
    assert observed["extra_slot_count"] == observed["missing_slot_count"] == 0
    assert observed["record_counts"]["receipts"] == 3
    assert summary["diagnostic_counts"] == {"expected_mirror": 1}
    assert summary["audited_gate_status"] == "recomputed_without_blocking_diagnostics"


def test_analyzer_rejects_incomplete_contract_receipt(tmp_path: Path) -> None:
    root = tmp_path / "input"
    root.mkdir()
    (root / "binding_receipts.json").write_text(json.dumps([{"schema_version": "statebus.execution_binding_receipt.v1", "binding_id": "b1", "attempt_id": "a1", "step_id": "step1"}]), encoding="utf-8")

    summary = analyze_artifacts(artifact_roots=[root], output_root=tmp_path / "analysis")

    assert summary["diagnostic_counts"]["empty_receipt"] == 1
