from __future__ import annotations

import json
from pathlib import Path

from scripts.v2_diagnostics.role_contract_audit import build_role_contract_audit_bundle
from v2.runtime.role_contract import audit_role_contract_report, role_contracts_payload


def _report_payload() -> dict[str, object]:
    return {
        "metadata": {"role_graph": "planner->retriever->executor->summarizer"},
        "telemetry_summary": {
            "planner_call_count": 1.0,
            "planner_generated_retrieval_objective_count": 1.0,
            "retriever_call_count": 1.0,
            "retrieval_log_count": 1.0,
            "retrieval_candidate_pool_count": 1.0,
            "executor_call_count": 1.0,
            "artifact_count": 1.0,
            "verified_artifact_ref_count": 1.0,
            "summarizer_call_count": 1.0,
            "memory_ref_count": 1.0,
            "runtime_session_count": 1.0,
        },
        "cases": [],
    }


def test_role_contract_payload_exposes_four_roles() -> None:
    payload = role_contracts_payload()
    assert payload["role_graph"] == "planner->retriever->executor->summarizer"
    assert [role["role"] for role in payload["roles"]] == ["planner", "retriever", "executor", "summarizer"]


def test_role_contract_audit_passes_expected_metrics() -> None:
    audit = audit_role_contract_report(_report_payload())
    assert audit["pass"] is True
    assert audit["failed_checks"] == []
    assert audit["observed_role_graphs"] == ["planner->retriever->executor->summarizer"]


def test_role_contract_audit_accepts_suite_layers() -> None:
    payload = {
        "metadata": {"benchmark_tier": "dev"},
        "layers": [
            _report_payload(),
        ],
    }
    audit = audit_role_contract_report(payload)
    assert audit["pass"] is True
    assert audit["failed_checks"] == []


def test_role_contract_audit_fails_missing_executor_artifact() -> None:
    payload = _report_payload()
    telemetry = dict(payload["telemetry_summary"])
    telemetry["verified_artifact_ref_count"] = 0.0
    payload["telemetry_summary"] = telemetry
    audit = audit_role_contract_report(payload)
    assert audit["pass"] is False
    assert "executor_metrics" in audit["failed_checks"]


def test_role_contract_audit_bundle_writes_outputs(tmp_path: Path) -> None:
    report_path = tmp_path / "family.json"
    report_path.write_text(json.dumps(_report_payload(), ensure_ascii=True), encoding="utf-8")
    bundle_dir = build_role_contract_audit_bundle(
        report_path=report_path,
        output_root=tmp_path / "diagnostics",
    )
    assert (bundle_dir / "role_contracts.json").exists()
    assert (bundle_dir / "summary.json").exists()
    assert (bundle_dir / "summary.md").exists()
