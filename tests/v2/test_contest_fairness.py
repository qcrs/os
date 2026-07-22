from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from v2.benchmark.contest_fairness import (
    EXPECTED_LAYER_FEATURE_FLAGS,
    audit_role_request_gold_visibility,
    build_continuous_fairness_manifest,
)
from v2.benchmark.contest_evidence_closure import (
    _AUDIT_DIRS,
    _materialize_artifact_contract,
    _stage_acceptance,
    _stage_command,
)
from v2.benchmark.models import (
    BenchmarkCaseReport,
    BenchmarkFamilyReport,
    BenchmarkLayer,
    BenchmarkLayerProfile,
    QualityFloorResult,
)


def _fairness_report(layer: BenchmarkLayer) -> BenchmarkFamilyReport:
    invariants = {
        "task_contract_digest": "task-contract",
        "source_content_digest": "source-content",
        "prior_fact_digest": "prior-facts",
        "role_graph_digest": "role-graph",
        "message_boundary_digest": "message-boundary",
        "model_config_digest": "model-config",
        "executor_validator_digest": "executor-validator",
        "capability_surface_digest": "capability-surface",
        "executor_transport": "subprocess",
        "control_carrier": "utf8_text" if layer == BenchmarkLayer.L0 else "protobuf",
        "gold_visibility_audit": {"ok": True},
    }
    case = BenchmarkCaseReport(
        task_id="fairness-task",
        task_family="fairness-family",
        quality_floor=QualityFloorResult(
            quality_floor_pass=True,
            deterministic_checks_passed=True,
            fact_coverage_passed=True,
        ),
        replay_class="disallowed",
        telemetry_event_count=1,
        output_artifact_hash="output-hash",
        output_artifact_path="outputs/result.json",
        workspace_root="workspace",
        audit_summary={
            "fairness_contract": invariants,
            "fairness_runtime_contract": {
                "feature_flags": dict(EXPECTED_LAYER_FEATURE_FLAGS[layer]),
            },
        },
    )
    flags = EXPECTED_LAYER_FEATURE_FLAGS[layer]
    return BenchmarkFamilyReport(
        suite_id="fairness-suite",
        layer=layer,
        task_family="fairness-family",
        profile=BenchmarkLayerProfile(
            layer=layer,
            description="fairness fixture",
            structured_control_enabled=bool(flags["structured_control_enabled"]),
            semantic_pruning_enabled=bool(flags["semantic_pruning_enabled"]),
            replay_enabled=bool(flags["replay_enabled"]),
        ),
        cases=(case,),
    )


def test_fairness_manifest_accepts_only_declared_lane_differences() -> None:
    manifest = build_continuous_fairness_manifest(
        family_id="fairness-family",
        layer_reports=tuple(_fairness_report(layer) for layer in BenchmarkLayer),
    )

    assert manifest["comparison_valid"] is True
    assert manifest["unexpected_difference_count"] == 0
    lanes = manifest["cases"]["fairness-task"]
    for field in manifest["invariant_fields"]:
        assert len({lane[field] for lane in lanes.values()}) == 1


def test_fairness_manifest_rejects_unexpected_extra_feature_difference() -> None:
    reports = [_fairness_report(layer) for layer in BenchmarkLayer]
    l2_index = next(index for index, report in enumerate(reports) if report.layer == BenchmarkLayer.L2)
    l2_report = reports[l2_index]
    l2_case = l2_report.cases[0]
    runtime_contract = dict(l2_case.audit_summary["fairness_runtime_contract"])
    runtime_contract["feature_flags"] = {
        **dict(runtime_contract["feature_flags"]),
        "unexpected_controller_hint": True,
    }
    reports[l2_index] = replace(
        l2_report,
        cases=(
            replace(
                l2_case,
                audit_summary={
                    **l2_case.audit_summary,
                    "fairness_runtime_contract": runtime_contract,
                },
            ),
        ),
    )

    manifest = build_continuous_fairness_manifest(
        family_id="fairness-family",
        layer_reports=tuple(reports),
    )

    assert manifest["comparison_valid"] is False
    assert manifest["headline_eligible"] is False
    assert any(
        difference["field"] == "feature_flags" and difference["layer"] == "L2"
        for difference in manifest["unexpected_differences"]
    )


def test_fairness_manifest_rejects_logit_policy_confounded_lane() -> None:
    reports = [_fairness_report(layer) for layer in BenchmarkLayer]
    l3_index = next(
        index for index, report in enumerate(reports) if report.layer == BenchmarkLayer.L3
    )
    l3_report = reports[l3_index]
    l3_case = l3_report.cases[0]
    runtime_contract = dict(l3_case.audit_summary["fairness_runtime_contract"])
    runtime_contract["feature_flags"] = {
        **dict(runtime_contract["feature_flags"]),
        "logit_policy": "telemetry_only",
    }
    reports[l3_index] = replace(
        l3_report,
        cases=(
            replace(
                l3_case,
                audit_summary={
                    **l3_case.audit_summary,
                    "fairness_runtime_contract": runtime_contract,
                },
            ),
        ),
    )

    manifest = build_continuous_fairness_manifest(
        family_id="fairness-family",
        layer_reports=tuple(reports),
    )

    assert manifest["comparison_valid"] is False
    assert any(
        difference["field"] == "feature_flags"
        and difference["layer"] == "L3"
        and difference["observed"]["logit_policy"] == "telemetry_only"
        for difference in manifest["unexpected_differences"]
    )


def test_gold_visibility_audit_scans_persisted_role_requests_with_provenance(tmp_path: Path) -> None:
    role_relpaths: dict[str, str] = {}
    for role in ("planner", "retriever", "executor", "summarizer"):
        relpath = f"logs/rendered_llm_requests/{role}.json"
        path = tmp_path / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "requests": [
                    {
                        "messages": [
                            {"role": "user", "content": "Authorized source revenue is 128.6."}
                        ]
                    }
                ]
            }),
            encoding="utf-8",
        )
        role_relpaths[role] = relpath

    clean = audit_role_request_gold_visibility(
        task_id="gold-audit-task",
        workspace_root=tmp_path,
        role_request_relpaths=role_relpaths,
        expected_facts={
            "revenue_value": "128.6",
            "private_benchmark_marker": "gold-secret-729",
        },
        quality_checks=("exact:revenue_value",),
        expected_metric_effects={"L3_memory_consumed_count_min": 1},
        public_provenance_payloads=("Authorized source revenue is 128.6.",),
    )
    assert clean["ok"] is True
    assert clean["expected_value_provenance"]["128.6"]["authorized"] is True
    assert clean["expected_value_provenance"]["gold-secret-729"]["authorized"] is False

    executor_path = tmp_path / role_relpaths["executor"]
    leaked = json.loads(executor_path.read_text(encoding="utf-8"))
    leaked["requests"][0]["expected_facts"] = {"private_benchmark_marker": "gold-secret-729"}
    executor_path.write_text(json.dumps(leaked), encoding="utf-8")
    rejected = audit_role_request_gold_visibility(
        task_id="gold-audit-task",
        workspace_root=tmp_path,
        role_request_relpaths=role_relpaths,
        expected_facts={"private_benchmark_marker": "gold-secret-729"},
        quality_checks=(),
        expected_metric_effects={},
        public_provenance_payloads=(),
    )

    assert rejected["ok"] is False
    assert any(
        violation["role"] == "executor"
        and violation["kind"] == "benchmark_only_key_visible"
        for violation in rejected["violations"]
    )


def test_contest_stage_commands_encode_the_prescribed_formal_objects(tmp_path: Path) -> None:
    _causal_name, causal = _stage_command("causal", tmp_path)
    _stress_name, stress = _stage_command("stress", tmp_path)
    _adaptive_name, adaptive = _stage_command("adaptive", tmp_path)

    assert causal[causal.index("--round-view") + 1] == "causal_core"
    assert causal[causal.index("--executor-mode") + 1] == "deterministic_codeact"
    assert causal[causal.index("--transport") + 1] == "subprocess"
    assert stress[stress.index("--round-view") + 1] == "long_horizon"
    assert stress[stress.index("--layer") + 1] == "L3"
    assert adaptive[adaptive.index("--max-cases") + 1] == "25"
    assert adaptive[adaptive.index("--exit-gate") + 1] == "all-correct"


def test_causal_stage_acceptance_requires_40_quality_cases_and_mechanism_gates() -> None:
    family_reports = []
    for family_index in range(2):
        task_family = f"family-{family_index}"
        family_reports.append({
            "task_family": task_family,
            "metadata": {
                "fairness_manifest": {
                    "comparison_valid": True,
                    "schema_version": "statebus.continuous_fairness_manifest.v1",
                }
            },
            "layers": [
                {
                    "layer": layer.value,
                    "task_family": task_family,
                    "cases": [
                        {
                            "task_id": f"{task_family}-{layer.value}-{case_index}",
                            "quality_floor": {"quality_floor_pass": True},
                        }
                        for case_index in range(5)
                    ],
                }
                for layer in BenchmarkLayer
            ],
        })
    payload = {
        "metadata": {"formal_headline_eligible": True},
        "collection_summary": {
            "L2_semantic_state_transfer_count": 10,
            "L3_memory_consumed_count": 4,
            "L3_memory_behavioral_effect_count": 2,
            "validated_replay_count": 2,
        },
        "family_reports": family_reports,
    }

    gates = _stage_acceptance("causal", payload)
    assert all(gates.values()), gates

    payload["metadata"]["formal_headline_eligible"] = False
    payload["family_reports"][0]["layers"][0]["cases"][0]["quality_floor"][
        "quality_floor_pass"
    ] = False
    rejected = _stage_acceptance("causal", payload)
    assert rejected["formal_causal_scope"] is False
    assert rejected["each_lane_10_of_10"] is False


def test_contest_artifact_contract_keeps_same_task_across_all_four_layers(tmp_path: Path) -> None:
    payload = {
        "family_reports": [{
            "suite_id": "causal-family",
            "task_family": "financial",
            "metadata": {
                "fairness_manifest": {
                    "comparison_valid": True,
                    "schema_version": "statebus.continuous_fairness_manifest.v1",
                }
            },
            "layers": [
                {
                    "layer": layer.value,
                    "task_family": "financial",
                    "cases": [{
                        "task_id": "round-1",
                        "quality_floor": {"quality_floor_pass": True},
                        "audit_summary": {},
                        "metrics": {},
                        "output_artifact_hash": f"sha256:{layer.value}",
                    }],
                }
                for layer in BenchmarkLayer
            ],
        }],
        "formal_headline_eligible": True,
    }
    run_manifest = {
        "exit_status": "passed",
        "serial_execution": True,
    }

    _materialize_artifact_contract(
        run_root=tmp_path,
        stage="causal",
        payload=payload,
        run_manifest=run_manifest,
    )

    assert len(list((tmp_path / "case_reports").glob("*.json"))) == 4
    for directory in _AUDIT_DIRS:
        assert len(list((tmp_path / directory).glob("*.json"))) == 4
    for filename in (
        "run_manifest.json",
        "environment.json",
        "fairness_manifest.json",
        "capability_registry.json",
        "summary.json",
        "summary.md",
        "pytest.log",
        "console.log",
        "checksums.sha256",
    ):
        assert (tmp_path / filename).is_file(), filename


def test_contest_artifact_contract_prefers_full_adaptive_case_over_stub(
    tmp_path: Path,
) -> None:
    native_summary = tmp_path / "raw" / "case-1" / "summary.json"
    native_summary.parent.mkdir(parents=True)
    native_summary.write_text(json.dumps({
        "schema_version": "statebus.adaptive_formal_case.v1",
        "task_id": "adaptive-case-1",
        "task_family": "financial_report_analysis",
        "ok": True,
        "native_marker": "full-case",
        "terminal_quality_reports": [{"verified": True}],
    }), encoding="utf-8")
    payload = {
        "schema_version": "statebus.adaptive_memory_summary.v1",
        "case_summaries": [{
            "task_id": "adaptive-case-1",
            "ok": True,
            "summary_path": str(native_summary),
        }],
    }
    run_manifest = {
        "experiment_id": "E3",
        "lane": "adaptive",
        "exit_status": "passed",
        "serial_execution": True,
    }

    _materialize_artifact_contract(
        run_root=tmp_path,
        stage="adaptive-memory",
        payload=payload,
        run_manifest=run_manifest,
    )

    for directory in _AUDIT_DIRS:
        assert len(list((tmp_path / directory).glob("*.json"))) == 1
    case_path = next((tmp_path / "case_reports").glob("*.json"))
    case = json.loads(case_path.read_text(encoding="utf-8"))
    assert case["native_marker"] == "full-case"
    assert case["contest_evidence_context"] == {
        "experiment_id": "E3",
        "lane": "adaptive",
        "run_id": tmp_path.name,
        "serial_execution": True,
        "stage": "adaptive-memory",
    }
