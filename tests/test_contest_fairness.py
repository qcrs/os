from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from statebus.benchmark.contest_fairness import (
    CANONICAL_LANES,
    FAIRNESS_LANES,
    EXPECTED_LAYER_FEATURE_FLAGS,
    audit_role_request_gold_visibility,
    audit_oracle_visibility,
    build_benchmark_manifest,
    build_failure_denominator,
    build_five_case_fairness_smoke,
    build_continuous_fairness_manifest,
    capture_source_identity,
    persist_test_evidence,
    validate_compile_evidence_projection,
    validate_test_evidence_projection,
    run_g6a2_correctness_fixture,
    validate_benchmark_manifest,
    validate_root_isolation,
)
from statebus.benchmark.contest_evidence_closure import (
    _AUDIT_DIRS,
    _materialize_artifact_contract,
    _stage_acceptance,
    _stage_command,
)
from statebus.benchmark.comparator_runner import canonical_aggregate_records
from statebus.benchmark.continuous_runner import run_g5b_actual_use_acceptance_pilot
from statebus.benchmark.models import (
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


def test_g5b_actual_use_acceptance_pilot_is_ordered_and_fail_closed(tmp_path: Path) -> None:
    root = run_g5b_actual_use_acceptance_pilot(root=tmp_path / "g5b")
    acceptance = json.loads((root / "g5b_acceptance.json").read_text(encoding="utf-8"))
    assert acceptance["status"] == "G5B_R4_REMEDIATION_COMPLETE_PENDING_ASTRA_REAUDIT"
    assert all(item["status"] == "PASS" for item in acceptance["gates"].values())
    assert acceptance["gate_values"]["G5-B2 ordered multi-round lifecycle"] is True
    assert acceptance["gate_values"]["G5-B8 negative rows and fail-closed behavior"] is True
    assert all(
        item["load_bearing_artifact"] and "recomputed_counts" in item and "failure_ids" in item
        for item in acceptance["gates"].values()
    )
    terminal = json.loads((root / "terminal_rows.json").read_text(encoding="utf-8"))["rows"]
    actual = [item for item in terminal if item.get("memory_actual_use")]
    assert len(terminal) == 72
    assert actual and {item["behavioral_effect"] for item in actual} == {"changed", "no_effect"}
    assert all(item["source_round"] < item["consumer_round"] for item in actual)
    assert len({item["attempt_id"] for item in terminal if item["row_scope"] == "attempt"}) == 60
    join_projection = json.loads((root / "receipt_join_projection.json").read_text(encoding="utf-8"))
    joins = join_projection["rows"]
    assert len({item["join_identity"] for item in joins}) == len(joins)
    observed_consumptions = [item["memory_consumption_id"] for item in joins if item.get("memory_consumption_id") not in {None, "", "not_applicable"}]
    assert len(set(observed_consumptions)) == len(observed_consumptions)
    required_join_dims = {
        "family_id", "repeat_id", "session_id", "source_round", "consumer_round",
        "cache_epoch", "memory_id", "memory_consumption_id", "memory_consumption_identity",
        "attempt_id", "capability_grant_hash", "memory_admission_receipt_hash",
        "execution_binding_hash", "attempt_result_admission_receipt_hash", "join_identity",
    }
    assert all(required_join_dims <= set(item) for item in joins)
    assert len(join_projection["control_rows"]) == 12
    denominator = json.loads((root / "failure_denominator.json").read_text(encoding="utf-8"))
    assert denominator["arithmetic_closed"] is True
    assert denominator["attempted_count"] == len(set(denominator["row_ids"]))
    metrics = json.loads((root / "metric_availability.json").read_text(encoding="utf-8"))["metrics"]
    assert metrics["provider_work_avoided"]["status"] == "unsupported"
    assert metrics["verified_recipe_work_avoided"]["status"] == "unsupported"
    oracle = json.loads((root / "future_round_isolation.json").read_text(encoding="utf-8"))["rows"]
    assert all(item["ok"] and not item["future_round_entry_ids_indexed"] for item in oracle)
    assert all(item["recursive_audit"]["audited_surfaces"] for item in oracle)
    assert all(
        item["expected_future_marker_set_hash"]
        == item["recursive_audit"]["expected_marker_set_hash"]
        and all(
            surface["future_marker_checks"]["expected_marker_set_hash"]
            == item["expected_future_marker_set_hash"]
            for surface in item["recursive_audit"]["audited_surfaces"]
        )
        for item in oracle
    )
    transition_projection = json.loads((root / "round_transition.json").read_text(encoding="utf-8"))
    transitions = transition_projection["rows"]
    assert len(transitions) == 72
    assert len(transition_projection["main_rows"]) == 60
    assert len(transition_projection["control_rows"]) == 12
    control_transitions = transition_projection["control_rows"]
    assert all(
        item["row_scope"] == "control_fixture"
        and item["terminal_status"]
        and "failure_stage" in item
        and "error_code" in item
        and item["control_identity"]
        and item["transition_evidence"]["status"] == "not_applicable"
        and item["transition_evidence"]["reason"] == "control_fixture_has_no_runtime_execution"
        and item["denominator_linkage"]["status"] == "observed"
        and item["next_round_start"]["status"] == "not_applicable"
        for item in control_transitions
    )
    assert all(
        item["memory_actual_use"] is False
        and item["denominator_linkage"]["status"] == "observed"
        and all(
            value["status"] == "not_applicable"
            and value["reason"] == "control_fixture_has_no_runtime_execution"
            for value in item["lifecycle_evidence"].values()
        )
        for item in terminal
        if item["row_scope"] == "control_fixture"
    )
    assert all(
        "lifecycle_evidence" in item
        and all(item["lifecycle_evidence"][name]["status"] in {"observed", "not_applicable", "failed"} for name in ("state_cleanup", "memory_cleanup", "root_cleanup", "socket_cleanup"))
        and "transition_timestamp_ns" not in item
        and "cleanup_observed_at_ns" not in item
        and item["lifecycle_evidence"]["terminal_settlement"]["status"] == "observed"
        and item["lifecycle_evidence"]["terminal_settlement"]["source_event_id"]
        and item["lifecycle_evidence"]["terminal_settlement"]["attempt_completed_at_ns_used_as_settlement"] is False
        and item["lifecycle_evidence"]["runtime_event_order"]["terminal_settlement_at_ns"] >= item["lifecycle_evidence"]["runtime_event_order"]["memory_commit_at_ns"]
        and item["lifecycle_evidence"]["runtime_event_order"]["terminal_settlement_at_ns"] >= item["lifecycle_evidence"]["runtime_event_order"]["downstream_completed_at_ns"]
        and item["terminal_settlement_source"]["settlement_identity"]
        and item["transition_identity"]
        for item in transition_projection["main_rows"]
    )
    assert sum(item["next_round_start"]["status"] == "not_applicable" for item in transition_projection["main_rows"]) == 6
    assert all(
        item["next_round_start"]["status"] == "not_applicable"
        or item["next_round_start"]["first_attempt_dispatched_at_ns"] >= item["lifecycle_evidence"]["runtime_event_order"]["terminal_settlement_at_ns"]
        for item in transition_projection["main_rows"]
    )


def test_c0_manifest_captures_source_and_validates_required_contract() -> None:
    source = capture_source_identity(Path("."))
    manifest = build_benchmark_manifest(
        lane="fixed_structured",
        dataset_id="dataset",
        dataset_version="v1",
        dataset_split="smoke",
        dataset_hash="sha256:dataset",
        task_contract_hash="sha256:task",
        provider_id="provider",
        provider_version="v1",
        model_id="model",
        model_revision="rev",
        source_identity=source,
        role_graph={"roles": ["planner", "retriever"], "edges": [["planner", "retriever"]]},
        agent_count=2,
        implementation_snapshot={"snapshot_id": "snap", "digest": "sha256:snap", "endpoint_fingerprint": "fp"},
        runtime_root=Path("/tmp/c0/runtime"),
        workspace_root=Path("/tmp/c0/workspace"),
        memory_root=Path("/tmp/c0/memory"),
        cache_epoch="cold:c0",
        validator_digest="sha256:validator",
        terminal_status="success",
    )
    assert manifest["schema_version"] == "statebus.fair_benchmark_manifest.v1"
    assert manifest["source_identity"]["commit"]
    assert validate_benchmark_manifest(manifest)["canonical_eligible"] is True


def test_c0_missing_identity_or_root_fields_are_diagnostic_only() -> None:
    manifest = build_benchmark_manifest(
        lane="adaptive_routed",
        dataset_id="dataset",
        dataset_version="v1",
        dataset_split="smoke",
        dataset_hash="sha256:dataset",
        task_contract_hash="sha256:task",
        provider_id="provider",
        provider_version="v1",
        model_id="model",
        model_revision="rev",
        source_identity={"commit": "", "branch_or_ref": ""},
        runtime_root="relative-runtime",
        workspace_root="relative-workspace",
        memory_root="relative-memory",
        validator_digest="",
        terminal_status="success",
    )
    result = validate_benchmark_manifest(manifest)
    assert result["canonical_eligible"] is False
    assert result["diagnostic_only"] is True
    assert "source_identity" in result["missing_fields"]
    assert any(error["field"] == "roots" for error in result["errors"])


def test_c0_oracle_visibility_gate_rejects_provider_visible_gold() -> None:
    clean = audit_oracle_visibility(
        provider_request={"messages": [{"role": "user", "content": "public input"}]},
        role_visible_input={"candidate_key": "route::tool"},
    )
    assert clean["ok"] is True
    leaked = audit_oracle_visibility(
        provider_request={"expected_route": "secret-route", "messages": []},
        role_visible_input={"future_rounds": [{"gold_answer": "secret"}]},
    )
    assert leaked["ok"] is False
    assert len(leaked["violations"]) >= 2
    assert leaked["gold_visible"] is False
    assert leaked["expected_route_visible"] is False
    assert leaked["expected_tool_visible"] is False
    assert leaked["future_rounds_visible"] is False


def test_c1_five_case_harness_keeps_common_inputs_and_excludes_legacy(tmp_path: Path) -> None:
    harness = build_five_case_fairness_smoke(
        root=tmp_path,
        terminal_status_by_lane={
            "direct_single_agent": "success",
            "pure_text_mas": "quality_fail",
            "fixed_structured": "timeout",
            "adaptive_routed": "unsupported",
            "legacy_comparator": "success",
        },
    )
    assert tuple(harness["lanes"]) == FAIRNESS_LANES
    assert len(harness["manifests"]) == 5
    assert {item["dataset_hash"] for item in harness["manifests"]} == {"sha256:c1-fixture"}
    assert {item["task_contract_hash"] for item in harness["manifests"]} == {"sha256:c1-task"}
    assert len(harness["invariant_digests"]) == 1
    assert harness["root_isolation"]["ok"] is True
    assert harness["canonical_aggregate"]["included_lanes"] == list(CANONICAL_LANES)
    assert harness["canonical_aggregate"]["excluded_lanes"] == ["legacy_comparator"]
    assert harness["canonical_aggregate"]["eligible"] is False
    assert all(item["manifest"]["lane"] != "legacy_comparator" for item in harness["canonical_records"])
    aggregate_records = canonical_aggregate_records(harness["terminal_records"])
    assert [record["lane"] for record in aggregate_records] == list(CANONICAL_LANES)
    assert all(record["lane"] != "legacy_comparator" for record in aggregate_records)
    assert len(harness["legacy_records"]) == 1
    assert harness["legacy_records"][0]["terminal_status"] == "success"
    fixed = next(item for item in harness["manifests"] if item["lane"] == "fixed_structured")
    legacy = next(item for item in harness["manifests"] if item["lane"] == "legacy_comparator")
    assert fixed["fixed_entrypoint"] == "FixedMainlineRequest->AdaptiveMainlineRunner->AdaptiveRuntimeEngine"
    assert fixed["uses_run_smoke"] is False
    assert legacy["uses_run_smoke"] is True
    assert harness["superiority_claim"] is False


def test_c1_terminal_failures_share_one_attempted_denominator() -> None:
    denominator = build_failure_denominator(
        {"terminal_status": status}
        for status in ("success", "quality_fail", "timeout", "unsupported", "runtime_fail", "policy_reject")
    )
    assert denominator["attempted_count"] == 6
    assert denominator["success_count"] == 1
    assert denominator["quality_fail_count"] == 1
    assert denominator["timeout_count"] == 1
    assert denominator["unsupported_count"] == 1
    assert denominator["runtime_fail_count"] == 1
    assert denominator["policy_reject_count"] == 1
    assert denominator["failure_count"] == 5


def test_c1_root_isolation_rejects_shared_mutable_roots() -> None:
    harness = build_five_case_fairness_smoke(root=Path("/tmp/c1-root-test"))
    manifests = list(harness["manifests"])
    manifests[1]["runtime_root"] = manifests[0]["runtime_root"]
    result = validate_root_isolation(manifests)
    assert result["ok"] is False
    assert "runtime_root" in result["collisions"]


def test_test_evidence_persists_independent_invocations_and_rejects_group_conflict(
    tmp_path: Path,
) -> None:
    first = persist_test_evidence(
        root=tmp_path,
        group="c1-c1b-regression",
        invocation_id="first",
        command=["python", "-m", "pytest", "tests/test_memory_runtime.py"],
        cwd=tmp_path,
        return_code=0,
        stdout="..\n2 passed in 0.10s\n",
        stderr="",
        test_nodes=["tests/test_memory_runtime.py::test_one", "tests/test_memory_runtime.py::test_two"],
    )
    assert validate_test_evidence_projection(first)["valid"] is True

    second = persist_test_evidence(
        root=tmp_path,
        group="c1-c1b-regression",
        invocation_id="second",
        command=["python", "-m", "pytest", "tests/test_memory_runtime.py"],
        cwd=tmp_path,
        return_code=124,
        stdout="FFFFFFF\n",
        stderr="",
        counts={"collected": 7, "failed": 7},
        test_nodes=[f"tests/test_memory_runtime.py::test_{i}" for i in range(7)],
        timeout=True,
        timeout_reason="command_timeout",
    )
    assert first["projection_path"] != second["projection_path"]
    assert Path(str(first["raw_stdout_path"])).read_text(encoding="utf-8") == "..\n2 passed in 0.10s\n"
    assert validate_test_evidence_projection(first)["valid"] is False
    second_validation = validate_test_evidence_projection(second)
    assert second_validation["valid"] is False
    assert "timeout" in second_validation["failed_checks"]
    index = json.loads(Path(str(second["index_path"])).read_text(encoding="utf-8"))
    assert index["conflict"] is True
    assert len(index["invocations"]) == 2


def test_test_evidence_requires_complete_nodes_and_pytest_summary(tmp_path: Path) -> None:
    projection = persist_test_evidence(
        root=tmp_path,
        group="targeted",
        invocation_id="missing-nodes",
        command=["python", "-m", "pytest"],
        cwd=tmp_path,
        return_code=0,
        stdout="2 passed in 0.10s\n",
        stderr="",
        test_nodes=[],
    )
    result = validate_test_evidence_projection(projection)
    assert result["valid"] is False
    assert "test_nodes_present" in result["failed_checks"]

    projection["raw_stdout_path"] = str(tmp_path / "missing.txt")
    result = validate_test_evidence_projection(projection)
    assert "raw_stdout_path" in result["failed_checks"]


def test_test_evidence_rejects_summary_count_mismatch(tmp_path: Path) -> None:
    projection = persist_test_evidence(
        root=tmp_path,
        group="targeted",
        invocation_id="summary-mismatch",
        command=["python", "-m", "pytest"],
        cwd=tmp_path,
        return_code=0,
        stdout="2 passed in 0.10s\n",
        stderr="",
        counts={"collected": 2, "passed": 1, "failed": 1},
        test_nodes=["tests/test_one.py::test_one", "tests/test_two.py::test_two"],
    )
    result = validate_test_evidence_projection(projection)
    assert result["valid"] is False
    assert "summary_count:passed" in result["failed_checks"]


def test_compile_evidence_validator_rejects_timeout_and_missing_output(tmp_path: Path) -> None:
    projection = {
        "schema_version": "statebus.c2a.pycompile.v1",
        "command": ["python", "-m", "py_compile", "module.py"],
        "cwd": str(tmp_path),
        "current_checkout": True,
        "return_code": 124,
        "compile_result": "PASS",
        "module_file_list": ["module.py"],
        "raw_stdout_path": str(tmp_path / "stdout.txt"),
        "raw_stderr_path": str(tmp_path / "stderr.txt"),
        "timeout": True,
    }
    assert validate_compile_evidence_projection(projection)["valid"] is False


def test_g6a2_remediation_fixture_closes_identity_collision_lifecycle_and_metrics(tmp_path: Path) -> None:
    result = run_g6a2_correctness_fixture(root=tmp_path / "g6a2-remediation")
    assert result["overall_pass"] is True
    assert all(result["remediation_gates"].values())
    collision = json.loads((tmp_path / "g6a2-remediation" / "rows" / "control_g6a2_isolation_collision" / "isolation_audit.json").read_text())
    assert collision["ok"] is False
    assert collision["collision_detected"] is True
    assert collision["foreign_residue_unlinked"] is False
    lifecycle = json.loads((tmp_path / "g6a2-remediation" / "rows" / "control_g6a2_lifecycle_success" / "state_release_reclaim.json").read_text())
    assert lifecycle["reclaim_attempt_while_live_pin"]["blocked"] is True
    assert lifecycle["reclaim_attempt_while_live_pin"]["physical_reclaimed_before_unpin"] is False
    assert lifecycle["release_count"] == lifecycle["reclaim_count"] == 1
    assert lifecycle["stale_handle_readable"] is False
    for row in (tmp_path / "g6a2-remediation" / "rows").iterdir():
        envelope = json.loads((row / "manifest.json").read_text())["identity_envelope"]
        assert envelope["task_id"] and envelope["session_id"]
        assert "identity_status_by_field" in envelope


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
