from __future__ import annotations

import json
import platform
from pathlib import Path

import pytest

from runtime.llm import LLMResult, LLMUsage, parse_tagged_json, tagged_json_block
from v2.contracts import CanonicalTaskSpec
from v2.runtime.smoke import SmokeLayerConfig, run_smoke
from v2.runtime.role_path import (
    ExecutorRoleDecision,
    PlannerRoleResult,
    RetrieverRoleDecision,
    RolePathRunner,
    SummarizerRoleDecision,
)
from v2.runtime.smoke import _driver_profile_from_layer_config
from v2.state import JsonContractStore


def test_v2_smoke_runs_vertical_slice(tmp_path: Path) -> None:
    result = run_smoke(
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        seed_replay_memory=True,
    )
    assert result.compiler_status == "compiled"
    assert result.supervisor_state == "GC_DONE"
    assert result.response_sequence == (
        "ACK_RECV",
        "RUN_START",
        "HEARTBEAT",
        "TRAP_FATAL",
        "ACK_RECV",
        "RUN_START",
        "HEARTBEAT",
        "RES_SUCC",
    )
    assert result.replay_class == "exact_replay"
    assert result.artifact_state == "verified"
    assert result.reloaded_manifest_id == "manifest-smoke-task"
    assert result.reloaded_pack_id == "pack-smoke-task"
    assert result.reloaded_input_manifest_hash
    assert result.canonical_task_spec_path
    assert result.output_artifact_hash
    assert result.telemetry_event_count == 40
    assert Path(result.canonical_task_spec_path).exists()
    assert Path(result.input_manifest_path).exists()
    assert Path(result.artifact_manifest_path).exists()
    assert Path(result.evidence_pack_path).exists()
    assert Path(result.hydrate_manifest_path).exists()
    assert Path(result.output_artifact_path).exists()
    assert Path(result.telemetry_path).exists()
    assert Path(result.runtime_event_log_path).exists()
    assert Path(result.runtime_fact_log_path).exists()
    assert Path(result.replay_audit_path).exists()
    assert Path(result.hydration_audit_path).exists()
    assert Path(result.hydration_debug_audit_path).exists()
    assert Path(result.artifact_audit_path).exists()
    assert Path(result.embedding_path).exists()
    assert Path(result.memory_commit_path).exists()
    assert Path(result.memory_match_result_path).exists()
    assert Path(result.retrieval_log_path).exists()
    assert Path(result.retrieval_candidate_pool_path).exists()
    assert Path(result.retrieval_rerank_result_path).exists()
    assert Path(result.retrieval_pruning_profile_path).exists()
    assert Path(result.session_path).exists()
    assert Path(result.replay_ledger_path).exists()
    assert Path(result.execution_step_path).exists()
    assert Path(result.fallback_dag_path).exists()
    assert Path(result.state_metadata_path).exists()
    assert len(result.validator_report_paths) == 2
    assert len(result.input_validator_report_paths) == 1
    assert result.state_storage_kind in {"shared_memory", "mmap_file"}
    assert result.quality_floor.quality_floor_pass is True
    assert result.session_state == "GC_DONE"
    assert result.task_metrics["heartbeat_count"] == 2.0
    assert result.task_metrics["memory_ref_count"] == 1.0
    assert result.task_metrics["retrieval_log_count"] == 1.0
    assert result.task_metrics["retrieval_pruning_profile_count"] == 1.0
    assert result.task_metrics["runtime_session_count"] == 1.0
    assert result.task_metrics["workflow_step_count"] == 4.0
    assert result.task_metrics["runtime_replan_count"] == 1.0
    assert result.task_metrics["runtime_fallback_count"] == 1.0
    assert result.task_metrics["attempt_count"] == 2.0
    assert result.task_metrics["replan_history_count"] == 1.0
    assert result.task_metrics["planner_generated_retrieval_objective_count"] == 1.0
    assert result.task_metrics["memory_candidate_count"] == 1.0
    assert result.task_metrics["memory_rerank_selected_count"] == 1.0
    assert result.task_metrics["memory_exact_replay_candidate_count"] == 1.0
    assert result.task_metrics["codeact_plan_stage_count"] == 0.0
    assert result.task_metrics["codeact_plan_action_count"] == 0.0
    assert result.task_metrics["planner_call_count"] == 1.0
    assert result.task_metrics["retriever_call_count"] == 0.0
    assert result.task_metrics["executor_call_count"] == 0.0
    assert result.task_metrics["summarizer_call_count"] == 0.0
    assert result.task_metrics["llm_call_count"] == 1.0
    assert result.task_metrics["answer_restoration_replay_count"] == 0.0
    assert result.task_metrics["llm_total_tokens"] == 0.0
    assert result.task_metrics["stdout_log_count"] == 1.0
    assert result.task_metrics["stderr_log_count"] == 1.0
    assert result.task_metrics["downgrade_execution_goal_count"] == 1.0
    assert result.workflow_step_count == 4
    assert result.completed_workflow_step_count == 4
    assert result.attempt_count == 2
    assert result.runtime_replan_count == 1
    assert result.runtime_fallback_count == 1
    assert result.replan_history_count == 1
    assert result.memory_replay_class == "exact_replay"
    assert result.memory_match_count == 1
    assert result.codeact_script_path == ""
    assert result.codeact_request_path == ""
    assert result.codeact_plan_path == ""
    assert result.audit_summary["replay"]["replay_class"] == "exact_replay"
    assert result.audit_summary["artifact"]["replay_ready"] is True
    assert result.runtime_stage_metrics["workspace_input_stage_ms"] >= 0.0
    assert result.runtime_stage_metrics["runtime_signature_capture_stage_ms"] >= 0.0
    assert result.runtime_stage_metrics["runtime_signature_materialize_stage_ms"] >= 0.0
    assert result.runtime_stage_metrics["workspace_output_stage_ms"] >= 0.0
    assert result.runtime_stage_metrics["codeact_execution_stage_ms"] >= 0.0
    assert result.runtime_stage_metrics["runtime_driver_stage_ms"] >= 0.0
    assert result.runtime_stage_metrics["persist_and_reload_stage_ms"] >= 0.0
    assert result.runtime_stage_metrics["registry_query_stage_ms"] == 0.0
    assert result.task_metrics["persist_bundle_write_stage_ms"] >= 0.0
    assert result.task_metrics["persist_core_reload_stage_ms"] >= 0.0
    assert result.task_metrics["persist_retrieval_verification_stage_ms"] >= 0.0
    assert result.task_metrics["persist_session_ledger_reload_stage_ms"] >= 0.0
    assert result.task_metrics["persist_validator_reload_stage_ms"] >= 0.0
    assert result.task_metrics["persist_semantic_manifest_reload_stage_ms"] >= 0.0
    assert result.task_metrics["persist_integrity_check_stage_ms"] >= 0.0
    assert result.task_metrics["persist_unbucketed_stage_ms"] >= 0.0
    assert result.task_metrics["runtime_non_executor_stage_ms"] >= 0.0
    assert result.task_metrics["runtime_data_plane_event_stage_ms"] >= 0.0
    assert result.task_metrics["control_plane_exchange_stage_ms"] >= 0.0
    assert result.task_metrics["executor_state_machine_stage_ms"] >= 0.0
    assert result.task_metrics["runtime_commit_finalize_stage_ms"] >= 0.0
    assert result.task_metrics["runtime_post_executor_stage_ms"] >= 0.0
    assert result.task_metrics["runtime_replay_ledger_stage_ms"] >= 0.0
    assert result.task_metrics["telemetry_emit_stage_ms"] >= 0.0
    assert result.task_metrics["telemetry_event_write_count"] >= 1.0
    assert result.task_metrics["telemetry_fact_write_count"] >= 1.0
    assert result.task_metrics["telemetry_log_handle_open_count"] == 2.0
    assert result.task_metrics["workspace_input_direct_write_count"] == 3.0
    assert result.task_metrics["workspace_input_bundle_write_count"] == 2.0
    assert result.task_metrics["workspace_input_bundle_reused_count"] == 0.0
    assert result.task_metrics["workspace_output_bundle_write_count"] == 1.0
    assert result.task_metrics["workspace_output_bundle_reused_count"] >= 2.0
    assert result.task_metrics["workspace_files"] >= 9.0
    assert result.task_metrics["role_prompt_slice_artifact_count"] == 4.0
    assert result.task_metrics["role_prompt_slice_artifact_bytes_total"] > 0.0
    assert result.reloaded_execution_goal == "downgrade_execution_goal"
    assert result.reloaded_fallback_dag_id == "fallback-smoke-task-step-execute"
    assert result.lineage_view.verified_artifact_ids == ("artifact-smoke",)
    assert Path(result.runtime_root).exists()

    output_payload = json.loads(Path(result.output_artifact_path).read_text(encoding="utf-8"))
    assert output_payload["task_id"] == "smoke-task"
    assert "summary ready" in output_payload["summary_text"]
    assert output_payload["execution_goal"] == "full_execution_goal"
    assert output_payload["action_contract"] == "restore_verified_artifact"
    memory_commit_payload = json.loads(Path(result.memory_commit_path).read_text(encoding="utf-8"))
    metadata = memory_commit_payload["memory_ref"]["metadata"]
    assert metadata["runtime_signature_hash"]
    assert metadata["runtime_signature_manifest_bundle_hash"]
    assert metadata["runtime_signature_manifest_bundle_relpath"] == "inputs/runtime_signature_manifest_bundle.json"
    assert "runtime_signature_manifest_bundle" not in metadata
    assert "planner_handoff_hash" not in metadata
    assert "input_artifact_hashes" not in metadata
    assert "runtime_signature" not in metadata
    assert "workspace_root" not in metadata
    assert "output_relpath" not in metadata
    assert "output_sha256" not in metadata
    replay_ledger_payload = json.loads(Path(result.replay_ledger_path).read_text(encoding="utf-8"))
    assert len(replay_ledger_payload["input_artifact_hashes"]) == 3
    assert replay_ledger_payload["planner_handoff_hash"]
    assert replay_ledger_payload["runtime_signature_manifest_bundle_hash"]
    assert replay_ledger_payload["runtime_signature"]["tool_registry_digest"]
    assert replay_ledger_payload["code_template_version"]
    assert replay_ledger_payload["extractor_version"]
    replay_audit_payload = json.loads(Path(result.replay_audit_path).read_text(encoding="utf-8"))
    assert replay_audit_payload["replay_class"] == "exact_replay"
    assert replay_audit_payload["candidate_id"]
    assert replay_audit_payload["history_runtime_root_count"] == 0
    assert replay_audit_payload["runtime_signature"]["combined_digest"]
    observation_hashes = replay_audit_payload["retrieval_observation_hashes"]
    assert observation_hashes["planner_handoff_replay_hash"]
    assert observation_hashes["evidence_pack_replay_hash"]
    assert observation_hashes["evidence_execution_input_replay_hash"] == replay_ledger_payload[
        "input_artifact_hashes"
    ][0]
    hydration_audit_payload = json.loads(Path(result.hydration_audit_path).read_text(encoding="utf-8"))
    assert hydration_audit_payload["counting_scope"] == "hydrated_external_evidence_only"
    assert hydration_audit_payload["raw_evidence_bytes_seen_by_llm"] == result.task_metrics["raw_evidence_bytes_seen_by_llm"]
    assert hydration_audit_payload["prompt_visible_total_bytes"] == result.task_metrics["prompt_visible_total_bytes"]
    assert (
        hydration_audit_payload["non_external_prompt_visible_bytes"]
        == result.task_metrics["non_external_prompt_visible_bytes"]
    )
    assert hydration_audit_payload["prompt_scaffolding_bytes_total"] == result.task_metrics["prompt_scaffolding_bytes_total"]
    role_accounting_by_name = {item["role"]: item for item in hydration_audit_payload["roles"]}
    assert role_accounting_by_name["planner"]["prompt_bytes"] >= role_accounting_by_name["planner"]["total_prompt_visible_bytes"]
    assert hydration_audit_payload["raw_evidence_bytes_seen_by_llm"] == (
        role_accounting_by_name["planner"]["external_evidence_bytes"]
    )
    assert role_accounting_by_name["summarizer"]["artifact_bytes"] == 0
    assert (
        role_accounting_by_name["planner"]["non_external_prompt_visible_bytes"]
        <= role_accounting_by_name["planner"]["total_prompt_visible_bytes"]
    )
    store = JsonContractStore(Path(result.runtime_root))
    reloaded_session = store.read_runtime_session(Path(result.session_path).stem)
    assert reloaded_session.workspace_root == result.workspace_root
    for role in ("planner", "retriever", "executor", "summarizer"):
        role_accounting = role_accounting_by_name[role]
        prompt_slice_path = Path(result.workspace_root) / role_accounting["prompt_slice_relpath"]
        assert role_accounting["prompt_slice_ref_id"] == f"prompt-slice-smoke-task-{role}"
        assert role_accounting["prompt_slice_root_id"] == "workspace-root"
        assert role_accounting["prompt_slice_blob_hash"]
        assert role_accounting["prompt_slice_size_bytes"] > 0
        assert prompt_slice_path.exists()
        prompt_slice_payload = json.loads(prompt_slice_path.read_text(encoding="utf-8"))
        assert prompt_slice_payload["role"] == role
        assert prompt_slice_payload["prompt_bytes"] == role_accounting["prompt_bytes"]
        registry_entry = store.get_ref_registry_entry(role_accounting["prompt_slice_ref_id"])
        assert registry_entry.relpath == role_accounting["prompt_slice_relpath"]
        assert registry_entry.root_id == "workspace-root"
    hydration_debug_payload = json.loads(Path(result.hydration_debug_audit_path).read_text(encoding="utf-8"))
    assert hydration_debug_payload["task_id"] == hydration_audit_payload["task_id"]
    assert hydration_debug_payload["roles"]["planner"]["external_evidence_bytes"] == (
        role_accounting_by_name["planner"]["external_evidence_bytes"]
    )
    assert hydration_debug_payload["roles"]["planner"]["prompt_slice_ref_id"] == "prompt-slice-smoke-task-planner"
    artifact_audit_payload = json.loads(Path(result.artifact_audit_path).read_text(encoding="utf-8"))
    assert artifact_audit_payload["replay_ready"] is True
    assert artifact_audit_payload["verification_state"] == "verified"
    assert artifact_audit_payload["output_artifact_hash"] == result.output_artifact_hash
    session_payload = json.loads(Path(result.session_path).read_text(encoding="utf-8"))
    assert session_payload["planner_handoff_hash"]
    assert session_payload["runtime_signature_hash"]
    assert session_payload["runtime_signature_manifest_bundle_hash"]
    assert "workspace_root" not in session_payload
    assert "state_root" not in session_payload
    assert session_payload["workspace_root_relpath"]
    assert session_payload["state_root_relpath"]
    assert len(session_payload["replay_input_artifact_hashes"]) == 3
    assert session_payload["workflow_steps"][0]["output_ref_hash"]
    assert "output_ref_sample_count" not in session_payload["workflow_steps"][0]
    assert "output_ref_sample" not in session_payload["workflow_steps"][0]
    assert "input_refs" not in session_payload["workflow_steps"][2]
    assert session_payload["attempt_records"][0]["workspace_dir_hash"]
    assert "workspace_dir_sample_count" not in session_payload["attempt_records"][0]
    assert "workspace_dir_sample" not in session_payload["attempt_records"][0]
    assert "workspace_dirs" not in session_payload["attempt_records"][0]
    assert "task_id" not in session_payload["attempt_records"][0]
    runtime_fact_lines = Path(result.runtime_fact_log_path).read_text(encoding="utf-8").strip().splitlines()
    assert any('"event_type":"STEP_DISPATCHED"' in line for line in runtime_fact_lines)
    assert any('"event_type":"REPLAY_DECIDED"' in line for line in runtime_fact_lines)
    assert any('"canonical_task_spec_hash":"' in line for line in runtime_fact_lines)
    assert any('"step_id":"planner.plan"' in line for line in runtime_fact_lines)
    assert any('"step_id":"summarizer.commit"' in line for line in runtime_fact_lines)
    assert sum('"event_type":"STATE_PUBLISHED"' in line for line in runtime_fact_lines) == 1
    assert sum('"event_type":"STATE_RESOLVED"' in line for line in runtime_fact_lines) == 1
    assert sum('"event_type":"STATE_CONSUMED"' in line for line in runtime_fact_lines) == 1
    assert sum('"event_type":"STATE_RELEASED"' in line for line in runtime_fact_lines) == 1
    assert not any('"event_type":"STATE_HYDRATED"' in line for line in runtime_fact_lines)
    stdout_payload = json.loads((Path(result.workspace_root) / "logs" / "step-execute.stdout.json").read_text(encoding="utf-8"))
    assert "stdout_preview" not in stdout_payload
    assert "stdout" in stdout_payload


def test_v2_smoke_default_driver_profile_keeps_strict_roundtrip() -> None:
    profile = _driver_profile_from_layer_config(SmokeLayerConfig())
    assert profile.persistence_verification_level == "strict_roundtrip"


def test_v2_smoke_benchmark_balanced_profile_hashes_prompt_slices(tmp_path: Path) -> None:
    result = run_smoke(
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        layer_config=SmokeLayerConfig(
            persistence_profile="benchmark_balanced",
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
    )
    assert result.quality_floor.quality_floor_pass is True
    role_payload = json.loads(
        (Path(result.workspace_root) / "logs" / "prompt_slices" / "planner.prompt_slice.json").read_text(
            encoding="utf-8"
        )
    )
    assert role_payload["persistence_profile"] == "benchmark_balanced"
    assert role_payload["combined_text_sha256"]
    assert "hydrated_text" not in role_payload
    assert "table_text" not in role_payload
    assert "artifact_text" not in role_payload
    assert "memory_text" not in role_payload
    rendered_request_payload = json.loads(
        (
            Path(result.workspace_root)
            / "logs"
            / "rendered_llm_requests"
            / "planner.rendered_request.json"
        ).read_text(encoding="utf-8")
    )
    assert rendered_request_payload["content_persisted"] is False
    assert rendered_request_payload["request_count"] >= 1
    assert "messages" not in rendered_request_payload["requests"][0]
    assert rendered_request_payload["requests"][0]["prompt_sha256"]
    telemetry_payload = json.loads(Path(result.telemetry_path).read_text(encoding="utf-8"))
    assert telemetry_payload["persistence_profile"] == "benchmark_balanced"
    assert telemetry_payload["event_count"] == result.telemetry_event_count
    assert telemetry_payload["events_sha256"]


def test_v2_smoke_l0_layer_disables_semantic_state_and_replay(tmp_path: Path) -> None:
    result = run_smoke(
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        layer_config=SmokeLayerConfig(
            layer_name="L0",
            handoff_mode="text_collaboration",
            structured_control_enabled=False,
            semantic_pruning_enabled=False,
            replay_enabled=False,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
    )
    assert result.replay_class == "disallowed"
    assert result.task_metrics["semantic_state_transfer_count"] == 0.0
    assert result.task_metrics["artifact_reuse_count"] == 0.0
    assert result.memory_replay_class == "assist"
    assert result.memory_match_count == 0
    assert result.task_metrics["memory_candidate_count"] == 0.0
    assert result.task_metrics["memory_exact_replay_candidate_count"] == 0.0
    assert result.quality_floor.quality_floor_pass is True
    assert result.state_storage_kind == "disabled"
    assert result.lineage_view.semantic_state_ids == ()
    assert result.reloaded_execution_goal == "full_execution_goal"
    assert result.task_metrics["handoff_mode_text_collaboration"] == 1.0
    assert result.task_metrics["handoff_mode_structured_collaboration"] == 0.0
    assert result.task_metrics["planner_handoff_bytes"] > 0.0
    assert result.task_metrics["role_handoff_bytes_total"] >= result.task_metrics["planner_handoff_bytes"]
    assert result.task_metrics["planner_prompt_bytes"] >= result.task_metrics["planner_prompt_visible_bytes"]
    assert (
        result.task_metrics["planner_prompt_scaffolding_bytes"]
        == result.task_metrics["planner_prompt_bytes"] - result.task_metrics["planner_prompt_visible_bytes"]
    )


def test_v2_smoke_formal_single_attempt_profile_is_distinct_from_resilience(tmp_path: Path) -> None:
    result = run_smoke(
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        layer_config=SmokeLayerConfig(
            layer_name="L2-role-path",
            handoff_mode="structured_collaboration",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=False,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
    )
    assert result.response_sequence == ("ACK_RECV", "RUN_START", "HEARTBEAT", "RES_SUCC")
    assert result.attempt_count == 1
    assert result.runtime_replan_count == 0
    assert result.runtime_fallback_count == 0
    assert result.replan_history_count == 0
    assert result.reloaded_execution_goal == "full_execution_goal"
    assert result.quality_floor.quality_floor_pass is True
    assert result.task_metrics["handoff_mode_text_collaboration"] == 0.0
    assert result.task_metrics["handoff_mode_structured_collaboration"] == 1.0


def test_v2_smoke_no_route_hints_is_auditable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STATEBUS_ROUTE_HINTS_ENABLED", "0")
    result = run_smoke(
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        layer_config=SmokeLayerConfig(
            layer_name="L3-no-route-hints",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=False,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
    )
    assert result.quality_floor.quality_floor_pass is True
    assert result.task_metrics["route_hints_enabled"] == 0.0
    assert result.task_metrics["planner_objective_present"] == 1.0
    assert result.task_metrics["planner_semantic_plan_valid"] == 1.0
    assert result.task_metrics["planner_retriever_consumed_hash_match_count"] == 4.0
    assert result.task_metrics["planner_behavioral_effect"] == 1.0
    assert result.task_metrics["rendered_role_request_artifact_count"] == 4.0
    assert result.task_metrics["rendered_role_request_count"] >= 4.0
    role_tags = {
        "planner": "sb-plan-v1",
        "retriever": "sb-retriever-v1",
        "executor": "sb-executor-v1",
        "summarizer": "sb-summary-v1",
    }
    for role, tag in role_tags.items():
        request_path = (
            Path(result.workspace_root)
            / "logs"
            / "rendered_llm_requests"
            / f"{role}.rendered_request.json"
        )
        request_artifact = json.loads(request_path.read_text(encoding="utf-8"))
        assert request_artifact["content_persisted"] is True
        assert request_artifact["request_count"] >= 1
        for request in request_artifact["requests"]:
            prompt = request["messages"][-1]["content"]
            payload = parse_tagged_json(prompt, tag)
            if role in {"retriever", "executor"}:
                assert "pc" not in payload
                assert "rh" not in payload
                assert "Preferred Candidate" not in prompt
                assert "Treat pc" not in prompt

    from scripts.run_v2_genericity_holdout import _prompt_taint_audit

    request_audit = _prompt_taint_audit((tmp_path / "workspaces",))
    assert request_audit["pass"] is True
    assert request_audit["scanned_task_count"] == 1
    assert request_audit["scanned_role_request_file_count"] == 4
    assert request_audit["no_hint_preferred_candidate_absent"] is True

    retriever_path = (
        Path(result.workspace_root)
        / "logs"
        / "rendered_llm_requests"
        / "retriever.rendered_request.json"
    )
    retriever_artifact = json.loads(retriever_path.read_text(encoding="utf-8"))
    prompt = retriever_artifact["requests"][0]["messages"][-1]["content"]
    retriever_payload = parse_tagged_json(prompt, "sb-retriever-v1")
    tainted_payload = {**retriever_payload, "oracle_answer": "fixture-only"}
    modified_prompt = prompt.replace(
        tagged_json_block("sb-retriever-v1", retriever_payload),
        tagged_json_block("sb-retriever-v1", tainted_payload),
        1,
    )
    assert modified_prompt != prompt
    retriever_artifact["requests"][0]["messages"][-1]["content"] = modified_prompt
    retriever_path.write_text(json.dumps(retriever_artifact), encoding="utf-8")
    rejected_audit = _prompt_taint_audit((tmp_path / "workspaces",))
    assert rejected_audit["pass"] is False
    assert any(
        item["kind"] == "forbidden_oracle_field" and item["detail"] == "oracle_answer"
        for item in rejected_audit["violations"]
    )

    shared_prefix = "fixture shared evidence"
    invalid_sp_payload = {
        **retriever_payload,
        "sp": {
            "contract": "statebus-shared-prefix-v1",
            "contains": "oracle_answer",
            "bytes": len(shared_prefix.encode("utf-8")),
        },
    }
    invalid_sp_prompt = (
        f"<statebus-shared-prefix-v1>\n{shared_prefix}\n"
        "</statebus-shared-prefix-v1>\n\n"
        + prompt.replace(
            tagged_json_block("sb-retriever-v1", retriever_payload),
            tagged_json_block("sb-retriever-v1", invalid_sp_payload),
            1,
        )
    )
    retriever_artifact["requests"][0]["messages"][-1]["content"] = invalid_sp_prompt
    retriever_path.write_text(json.dumps(retriever_artifact), encoding="utf-8")
    invalid_sp_audit = _prompt_taint_audit((tmp_path / "workspaces",))
    assert invalid_sp_audit["pass"] is False
    assert any(
        item["kind"] == "invalid_shared_prefix_metadata"
        and item["detail"]["reason"] == "contains"
        for item in invalid_sp_audit["violations"]
    )


@pytest.mark.skipif(
    platform.system() != "Linux",
    reason="subprocess transport + memfd validation is Linux-only",
)
def test_v2_smoke_subprocess_transport_avoids_loopback(tmp_path: Path, monkeypatch) -> None:
    calls = {"subprocess_exchange_count": 0}

    def _unexpected_loopback(*args, **kwargs):
        del args, kwargs
        raise AssertionError("loopback transport should not be used when executor_transport=subprocess")

    from v2.control.transport import SubprocessExecutorTransport

    original_exchange = SubprocessExecutorTransport.exchange_sequence

    def _recording_exchange(
        self,
        request,
        *,
        memfd_refs=None,
        carrier="protobuf",
        text_payload="",
    ):
        calls["subprocess_exchange_count"] += 1
        return original_exchange(
            self,
            request,
            memfd_refs=memfd_refs,
            carrier=carrier,
            text_payload=text_payload,
        )

    monkeypatch.setattr(
        "v2.runtime.driver.ControlPlaneLoopbackServer.exchange_sequence_by_contract",
        _unexpected_loopback,
    )
    monkeypatch.setattr(
        "v2.runtime.driver.SubprocessExecutorTransport.exchange_sequence",
        _recording_exchange,
    )

    result = run_smoke(
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        layer_config=SmokeLayerConfig(
            layer_name="L3-subprocess",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=False,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
            state_pool_mode="memfd",
            executor_transport="subprocess",
        ),
    )

    # One subprocess is the semantic consumer and one is the executor.
    assert calls["subprocess_exchange_count"] == 2
    assert result.response_sequence == ("ACK_RECV", "RUN_START", "HEARTBEAT", "RES_SUCC")
    assert result.quality_floor.quality_floor_pass is True
    assert result.task_metrics["control_message_count"] == 4.0
    assert result.task_metrics["semantic_state_transfer_count"] == 1.0
    assert result.state_storage_kind == "shared_memory"


def test_v2_smoke_aggregates_role_path_token_usage(tmp_path: Path, monkeypatch) -> None:
    class StubRolePathRunner(RolePathRunner):
        def __init__(self, llm_client=None):
            del llm_client

        def plan_workflow(self, **kwargs):
            del kwargs
            return PlannerRoleResult(
                workflow_payload={"steps": []},
                retrieval_objective={"query_text": "stub retrieval objective"},
                raw_text='{"steps":[]}',
                model="stub-model",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            )

        def choose_retrieval_candidate(self, **kwargs):
            visible_candidates = kwargs["visible_candidates"]
            candidate = visible_candidates[0]
            return RetrieverRoleDecision(
                route=candidate.route,
                tool_name=candidate.tool_name,
                supporting_doc_ids=candidate.supporting_doc_ids,
                reason="stub-retriever",
                candidate_rank=candidate.helper_rank,
                raw_text='{"ok":true}',
                model="stub-model",
                prompt_tokens=11,
                completion_tokens=6,
                total_tokens=17,
            )

        def validate_execution_choice(self, **kwargs):
            return ExecutorRoleDecision(
                route=kwargs["route"],
                tool_name=kwargs["tool_name"],
                action_contract=kwargs["action_contract"],
                reason="stub-executor",
                raw_text='{"ok":true}',
                model="stub-model",
                prompt_tokens=12,
                completion_tokens=7,
                total_tokens=19,
                logit_sequence_length=6,
                logit_decision_entropy=0.75,
            )

        def summarize(self, **kwargs):
            del kwargs
            return SummarizerRoleDecision(
                summary_text="stub summary ready",
                reusable_steps=("retrieve", "execute"),
                confidence=0.9,
                tags=("stub",),
                raw_text='{"summary":"stub summary ready"}',
                model="stub-model",
                prompt_tokens=13,
                completion_tokens=8,
                total_tokens=21,
            )

    monkeypatch.setattr("v2.runtime.smoke.RolePathRunner", StubRolePathRunner)

    result = run_smoke(
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        layer_config=SmokeLayerConfig(
            layer_name="L2-role-path",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=False,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
    )

    assert result.task_metrics["planner_call_count"] == 1.0
    assert result.task_metrics["retriever_call_count"] == 1.0
    assert result.task_metrics["executor_call_count"] == 1.0
    assert result.task_metrics["summarizer_call_count"] == 1.0
    assert result.task_metrics["planner_generated_retrieval_objective_count"] == 1.0
    assert result.task_metrics["retriever_hydrated_bytes"] > 0.0
    assert result.task_metrics["executor_hydrated_bytes"] == 0.0
    assert result.task_metrics["summarizer_hydrated_bytes"] > 0.0
    assert result.task_metrics["planner_hydrated_bytes"] == 0.0
    assert result.task_metrics["retriever_hydrated_item_count"] > 0.0
    assert result.task_metrics["executor_hydrated_item_count"] == 0.0
    assert result.task_metrics["summarizer_hydrated_item_count"] > 0.0
    assert result.task_metrics["planner_hydrated_item_count"] == 0.0
    assert result.task_metrics["planner_table_bytes"] == 0.0
    assert result.task_metrics["retriever_table_bytes"] > 0.0
    assert result.task_metrics["executor_table_bytes"] > 0.0
    assert result.task_metrics["summarizer_table_bytes"] > 0.0
    assert result.task_metrics["summarizer_artifact_bytes"] > 0.0
    assert result.task_metrics["llm_prompt_tokens"] == 46.0
    assert result.task_metrics["llm_completion_tokens"] == 26.0
    assert result.task_metrics["llm_total_tokens"] == 72.0
    assert result.task_metrics["logit_sequence_length"] == 6.0
    assert result.task_metrics["logit_decision_entropy"] == 0.75
    persisted_task_metrics = json.loads(
        Path(result.task_metrics_path).read_text(encoding="utf-8")
    )
    assert persisted_task_metrics["logit_sequence_length"] == 6.0
    assert persisted_task_metrics["logit_decision_entropy"] == 0.75
    assert result.task_metrics["raw_evidence_bytes_seen_by_llm"] == (
        result.task_metrics["planner_hydrated_bytes"]
        + result.task_metrics["planner_table_bytes"]
        + result.task_metrics["retriever_hydrated_bytes"]
        + result.task_metrics["retriever_table_bytes"]
        + result.task_metrics["executor_hydrated_bytes"]
        + result.task_metrics["executor_table_bytes"]
        + result.task_metrics["summarizer_hydrated_bytes"]
        + result.task_metrics["summarizer_table_bytes"]
    )


def test_v2_smoke_cold_start_mode_executes_role_path_without_seeded_replay(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class StubRolePathRunner(RolePathRunner):
        def __init__(self, llm_client=None):
            del llm_client

        def plan_workflow(self, **kwargs):
            del kwargs
            return PlannerRoleResult(
                workflow_payload={"steps": []},
                retrieval_objective={"query_text": "stub retrieval objective"},
                raw_text='{"steps":[]}',
                model="stub-model",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            )

        def choose_retrieval_candidate(self, **kwargs):
            candidate = kwargs["visible_candidates"][0]
            return RetrieverRoleDecision(
                route=candidate.route,
                tool_name=candidate.tool_name,
                supporting_doc_ids=candidate.supporting_doc_ids,
                reason="stub-retriever",
                candidate_rank=candidate.helper_rank,
                raw_text='{"ok":true}',
                model="stub-model",
                prompt_tokens=11,
                completion_tokens=6,
                total_tokens=17,
            )

        def validate_execution_choice(self, **kwargs):
            return ExecutorRoleDecision(
                route=kwargs["route"],
                tool_name=kwargs["tool_name"],
                action_contract=kwargs["action_contract"],
                reason="stub-executor",
                raw_text='{"ok":true}',
                model="stub-model",
                prompt_tokens=12,
                completion_tokens=7,
                total_tokens=19,
            )

        def summarize(self, **kwargs):
            del kwargs
            return SummarizerRoleDecision(
                summary_text="stub summary ready",
                reusable_steps=("retrieve", "execute"),
                confidence=0.9,
                tags=("stub",),
                raw_text='{"summary":"stub summary ready"}',
                model="stub-model",
                prompt_tokens=13,
                completion_tokens=8,
                total_tokens=21,
            )

    monkeypatch.setattr("v2.runtime.smoke.RolePathRunner", StubRolePathRunner)

    result = run_smoke(
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        layer_config=SmokeLayerConfig(
            layer_name="L3-cold-start",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=True,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
        seed_replay_memory=False,
    )

    assert result.replay_class == "disallowed"
    assert result.task_metrics["planner_call_count"] == 1.0
    assert result.task_metrics["retriever_call_count"] == 1.0
    assert result.task_metrics["executor_call_count"] == 1.0
    assert result.task_metrics["summarizer_call_count"] == 1.0
    assert result.task_metrics["planner_generated_retrieval_objective_count"] == 1.0
    assert result.task_metrics["llm_total_tokens"] == 72.0
    assert result.task_metrics["artifact_reuse_count"] == 0.0
    assert result.task_metrics["reuse_gain"] == 0.0
    assert result.task_metrics["skipped_step_count"] == 0.0
    assert result.task_metrics["codeact_plan_stage_count"] > 0.0
    assert result.task_metrics["codeact_plan_action_count"] > 0.0
    assert result.task_metrics["memory_candidate_count"] == 0.0
    assert result.task_metrics["memory_exact_replay_candidate_count"] == 0.0
    assert result.memory_match_count == 0
    assert result.memory_replay_class == "assist"
    assert result.codeact_request_path.endswith(".codeact_bundle.json")
    assert result.codeact_plan_path == result.codeact_request_path
    assert Path(result.codeact_request_path).exists()
    assert Path(result.codeact_script_path).exists()


def test_v2_smoke_history_backed_exact_replay_restores_prior_output(tmp_path: Path) -> None:
    bootstrap_runtime_root = tmp_path / "runtime-bootstrap"
    bootstrap_workspace_root = tmp_path / "workspaces-bootstrap"
    bootstrap = run_smoke(
        workspace_root=bootstrap_workspace_root,
        runtime_root=bootstrap_runtime_root,
        socket_path=tmp_path / "bootstrap.sock",
        task_id="smoke-task",
        layer_config=SmokeLayerConfig(
            layer_name="L3-fixed-answer-cold-start",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=True,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
        seed_replay_memory=False,
    )
    replay = run_smoke(
        workspace_root=tmp_path / "workspaces-replay",
        runtime_root=tmp_path / "runtime-replay",
        socket_path=tmp_path / "replay.sock",
        task_id="smoke-task",
        layer_config=SmokeLayerConfig(
            layer_name="L3-fixed-answer",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=True,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
        seed_replay_memory=False,
        history_runtime_roots=(bootstrap_runtime_root,),
    )

    assert bootstrap.replay_class == "disallowed"
    assert replay.replay_class == "exact_replay"
    assert replay.task_metrics["planner_call_count"] == 1.0
    assert replay.task_metrics["retriever_call_count"] == 0.0
    assert replay.task_metrics["executor_call_count"] == 0.0
    assert replay.task_metrics["summarizer_call_count"] == 0.0
    assert replay.task_metrics["llm_call_count"] == 1.0
    assert replay.task_metrics["answer_restoration_replay_count"] == 1.0
    assert replay.task_metrics["artifact_reuse_count"] == 1.0
    assert replay.task_metrics["memory_candidate_count"] == 1.0
    assert replay.task_metrics["memory_exact_replay_candidate_count"] == 1.0
    bootstrap_output = json.loads(Path(bootstrap.output_artifact_path).read_text(encoding="utf-8"))
    replay_output = json.loads(Path(replay.output_artifact_path).read_text(encoding="utf-8"))
    assert replay_output["task_id"] == "smoke-task"
    assert replay_output["restored_replay_class"] == "exact_replay"
    assert replay_output["summary_text"] == bootstrap_output["summary_text"]
    assert replay_output["revenue_value"] == bootstrap_output["revenue_value"]
    replay_commit_payload = json.loads(Path(replay.memory_commit_path).read_text(encoding="utf-8"))
    assert replay_commit_payload["memory_ref"]["metadata"]["runtime_signature_hash"]
    assert replay_commit_payload["memory_ref"]["metadata"]["runtime_signature_manifest_bundle_hash"]
    assert (
        replay_commit_payload["memory_ref"]["metadata"]["runtime_signature_manifest_bundle_relpath"]
        == "inputs/runtime_signature_manifest_bundle.json"
    )
    assert "runtime_signature_manifest_bundle" not in replay_commit_payload["memory_ref"]["metadata"]
    assert "planner_handoff_hash" not in replay_commit_payload["memory_ref"]["metadata"]
    assert "input_artifact_hashes" not in replay_commit_payload["memory_ref"]["metadata"]


def test_v2_smoke_memory_slice_is_visible_to_retriever_and_executor(tmp_path: Path) -> None:
    bootstrap_runtime_root = tmp_path / "runtime-bootstrap"
    bootstrap_workspace_root = tmp_path / "workspaces-bootstrap"
    run_smoke(
        workspace_root=bootstrap_workspace_root,
        runtime_root=bootstrap_runtime_root,
        socket_path=tmp_path / "bootstrap.sock",
        task_id="smoke-task",
        layer_config=SmokeLayerConfig(
            layer_name="L3-fixed-answer-cold-start",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=True,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
        seed_replay_memory=False,
    )
    assist_spec = CanonicalTaskSpec(
        task_family="financial_report_analysis",
        intent_op="compare_metric",
        required_outputs=("summary_text",),
        required_tools=("table_retriever", "semantic_retriever"),
        arguments={
            "ticker": "ACME",
            "quarter": "2026Q1",
            "metric": "gross_margin",
            "reuse_contract": {"minimum_reuse_class": "assist"},
        },
    )
    result = run_smoke(
        workspace_root=tmp_path / "workspaces-reuse",
        runtime_root=tmp_path / "runtime-reuse",
        socket_path=tmp_path / "reuse.sock",
        task_id="smoke-task-fresh",
        canonical_task_spec=assist_spec,
        layer_config=SmokeLayerConfig(
            layer_name="L3-cold-start",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=True,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
        seed_replay_memory=False,
        history_runtime_roots=(bootstrap_runtime_root,),
    )

    assert result.replay_class == "disallowed"
    assert result.task_metrics["memory_candidate_count"] == 1.0
    assert result.task_metrics["memory_compatible_match_count"] == 1.0
    # This legacy smoke path exposes the candidate in role slices but has no
    # role receipt proving behavioral consumption. F-03 therefore keeps the
    # assist visible while refusing to count it as consumed.
    assert result.task_metrics["memory_consumed_count"] == 0.0
    assert result.task_metrics["memory_assist_count"] == 0.0
    assert result.task_metrics["skipped_step_count"] == 0.0
    assert result.task_metrics["retriever_memory_bytes"] > 0.0
    assert result.task_metrics["executor_memory_bytes"] > 0.0
    assert result.task_metrics["summarizer_memory_bytes"] > 0.0
    assert result.task_metrics["retriever_memory_item_count"] > 0.0
    assert result.task_metrics["executor_memory_item_count"] > 0.0
    assert result.task_metrics["summarizer_memory_item_count"] > 0.0
    hydration_audit_payload = json.loads(Path(result.hydration_audit_path).read_text(encoding="utf-8"))
    role_accounting_by_name = {item["role"]: item for item in hydration_audit_payload["roles"]}
    assert hydration_audit_payload["raw_evidence_bytes_seen_by_llm"] == result.task_metrics["raw_evidence_bytes_seen_by_llm"]
    assert role_accounting_by_name["retriever"]["memory_bytes"] > 0
    assert role_accounting_by_name["executor"]["memory_bytes"] > 0
    assert role_accounting_by_name["summarizer"]["memory_bytes"] > 0
    assert hydration_audit_payload["non_external_prompt_visible_bytes"] >= (
        role_accounting_by_name["retriever"]["memory_bytes"]
        + role_accounting_by_name["executor"]["memory_bytes"]
        + role_accounting_by_name["summarizer"]["memory_bytes"]
    )


def test_v2_smoke_planner_scope_is_materialized_into_retrieval_sidecars(tmp_path: Path) -> None:
    result = run_smoke(
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        layer_config=SmokeLayerConfig(
            layer_name="L3-cold-start",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=False,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
    )

    retrieval_log_payload = json.loads(Path(result.retrieval_log_path).read_text(encoding="utf-8"))
    candidate_pool_payload = json.loads(Path(result.retrieval_candidate_pool_path).read_text(encoding="utf-8"))

    assert retrieval_log_payload["query_text"]
    assert "planner_scope_payload" not in retrieval_log_payload
    assert retrieval_log_payload["planner_scope_payload_hash"]
    assert retrieval_log_payload["candidate_pool_relpath"]
    assert retrieval_log_payload["outputs"]
    assert "candidates" not in retrieval_log_payload["outputs"][0]
    assert "query_embedding" not in retrieval_log_payload["outputs"][0]
    assert "log_entry" not in retrieval_log_payload["outputs"][0]
    assert retrieval_log_payload["outputs"][0]["candidate_ids_hash"]
    assert retrieval_log_payload["outputs"][0]["candidate_id_sample_count"] == len(
        retrieval_log_payload["outputs"][0]["candidate_id_sample"]
    )
    assert retrieval_log_payload["outputs"][0]["selected_ids_hash"]
    assert "selected_id_sample_count" not in retrieval_log_payload["outputs"][0]
    assert "selected_id_sample" not in retrieval_log_payload["outputs"][0]
    assert retrieval_log_payload["outputs"][0]["selected_candidate_audit_hash"]
    assert retrieval_log_payload["outputs"][0]["selected_candidate_audit_sample_count"] == len(
        retrieval_log_payload["outputs"][0]["selected_candidate_audit_sample"]
    )
    assert "candidate_ids" not in retrieval_log_payload["outputs"][0]
    assert "selected_candidate_audit" not in retrieval_log_payload["outputs"][0]
    assert retrieval_log_payload["candidate_surface_hash"]
    assert candidate_pool_payload["planner_scope_payload"]["supporting_doc_ids"]
    assert candidate_pool_payload["planner_scope_payload"]["required_tools"]
    assert candidate_pool_payload["planner_scope_payload_hash"] == retrieval_log_payload["planner_scope_payload_hash"]
    assert candidate_pool_payload["candidate_surface_hash"]
    assert candidate_pool_payload["candidate_surface_relpath"]
    assert candidate_pool_payload["candidate_audit_hash"]
    assert candidate_pool_payload["candidate_audit_sample_count"] == len(
        candidate_pool_payload["candidate_audit_sample"]
    )
    assert candidate_pool_payload["candidate_count"] >= candidate_pool_payload["candidate_audit_sample_count"]
    assert candidate_pool_payload["candidate_rendered_text_bytes_total"] > 0
    assert "text_context" not in candidate_pool_payload["planner_scope_payload"]


def test_v2_smoke_external_gold_mismatch_does_not_change_runtime_commit(tmp_path: Path) -> None:
    layer_config = SmokeLayerConfig(
        layer_name="gold-boundary",
        structured_control_enabled=True,
        semantic_pruning_enabled=False,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    )
    common = {
        "request_text": "Extract the current revenue metric from the authorized source.",
        "task_id": "gold-boundary-task",
        "layer_config": layer_config,
        "seed_replay_memory": False,
    }
    control = run_smoke(
        workspace_root=tmp_path / "control-workspaces",
        runtime_root=tmp_path / "control-runtime",
        socket_path=tmp_path / "control.sock",
        **common,
    )
    wrong_value = "benchmark-only-wrong-value-7f3a9c"
    mismatch = run_smoke(
        workspace_root=tmp_path / "mismatch-workspaces",
        runtime_root=tmp_path / "mismatch-runtime",
        socket_path=tmp_path / "mismatch.sock",
        expected_facts={"revenue_value": wrong_value},
        **common,
    )

    assert control.quality_floor.quality_floor_pass is True
    assert mismatch.quality_floor.quality_floor_pass is False
    assert control.output_artifact_hash == mismatch.output_artifact_hash
    assert control.replay_class == mismatch.replay_class
    assert control.task_metrics["memory_commit_count"] == mismatch.task_metrics["memory_commit_count"]
    assert mismatch.task_metrics["memory_commit_count"] > 0.0
    assert mismatch.task_metrics["runtime_quality_floor_pass"] == 1.0
    assert mismatch.task_metrics["benchmark_external_gold_pass_count"] == 0.0
    assert mismatch.task_metrics["benchmark_gold_runtime_decision_input_count"] == 0.0
    control_artifact_audit = json.loads(Path(control.artifact_audit_path).read_text(encoding="utf-8"))
    mismatch_artifact_audit = json.loads(Path(mismatch.artifact_audit_path).read_text(encoding="utf-8"))
    assert control_artifact_audit["verification_state"] == "verified"
    assert mismatch_artifact_audit["verification_state"] == "verified"
    assert control_artifact_audit["replay_ready"] is True
    assert mismatch_artifact_audit["replay_ready"] is True
    assert Path(mismatch.memory_commit_path).is_file()
    gold_boundary = mismatch.audit_summary["benchmark_gold_boundary"]
    assert gold_boundary["runtime_decision_input"] is False
    assert gold_boundary["runtime_memory_commit_preceded_external_score"] is True
    assert gold_boundary["runtime_artifact_verification_state"] == "verified"
    for relpath in mismatch.audit_summary["rendered_llm_requests"]["role_relpaths"].values():
        rendered = (Path(mismatch.workspace_root) / relpath).read_text(encoding="utf-8")
        assert wrong_value not in rendered
        assert '"expected_facts"' not in rendered


def test_v2_smoke_continuous_validated_reuse_metrics_are_output_backed(tmp_path: Path) -> None:
    first_spec = CanonicalTaskSpec(
        task_family="continuous_csv_table_analysis",
        intent_op="profile_table",
        required_outputs=("schema_profile_ref", "missingness_summary", "summary_text"),
        required_tools=("csv_profiler", "codeact_executor"),
        arguments={
            "dataset_id": "disease_estimates",
            "csv_path": "task/csv/estimated_numbers.csv",
            "columns": ["No. of cases_min", "No. of deaths_max"],
            "quality_checks": ["artifact_exists:schema_profile_ref"],
            "reuse_contract": {
                "produces": ["schema_profile:disease_estimates", "strategy:missingness_profile"],
                "consumes": [],
                "minimum_reuse_class": "none",
            },
        },
    )
    bootstrap = run_smoke(
        workspace_root=tmp_path / "workspaces-bootstrap",
        runtime_root=tmp_path / "runtime-bootstrap",
        socket_path=tmp_path / "bootstrap.sock",
        task_id="csv-profile-001",
        request_text="profile disease table",
        canonical_task_spec=first_spec,
        layer_config=SmokeLayerConfig(
            layer_name="L3-continuous",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=True,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
        expected_facts={"percentage_cases_min": "36.45", "percentage_deaths_max": "38.79"},
        seed_replay_memory=False,
    )
    second_spec = CanonicalTaskSpec(
        task_family="continuous_csv_table_analysis",
        intent_op="correlate_columns",
        required_outputs=("correlation_artifact_ref", "correlation_coefficient"),
        required_tools=("table_retriever", "codeact_executor"),
        arguments={
            "dataset_id": "disease_estimates",
            "csv_path": "task/csv/estimated_numbers.csv",
            "left_column": "No. of cases",
            "right_column": "No. of deaths",
            "method": "pearson",
            "quality_checks": ["numeric_tolerance:correlation_coefficient:0.01"],
            "reuse_contract": {
                "produces": ["strategy:pearson_correlation", "correlation_artifact:disease_cases_deaths"],
                "consumes": ["schema_profile:disease_estimates", "strategy:missingness_profile"],
                "minimum_reuse_class": "assist",
            },
        },
    )
    result = run_smoke(
        workspace_root=tmp_path / "workspaces-reuse",
        runtime_root=tmp_path / "runtime-reuse",
        socket_path=tmp_path / "reuse.sock",
        task_id="csv-profile-003",
        request_text="correlate disease columns",
        canonical_task_spec=second_spec,
        layer_config=SmokeLayerConfig(
            layer_name="L3-continuous",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=True,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
        expected_facts={"correlation_coefficient": "0.97"},
        seed_replay_memory=False,
        history_runtime_roots=(Path(bootstrap.runtime_root),),
    )

    assert result.replay_class == "disallowed"
    assert result.task_metrics["history_artifact_reuse_count"] == 1.0
    assert result.task_metrics["history_strategy_reuse_count"] == 1.0
    assert result.task_metrics["artifact_reuse_count"] == 1.0
    assert result.task_metrics["skipped_step_count"] == 0.0
    assert result.task_metrics["reuse_gain"] == 0.0
    output_payload = json.loads(Path(result.output_artifact_path).read_text(encoding="utf-8"))
    assert output_payload["consumed_artifact_refs"] == ["schema_profile:disease_estimates"]
    assert output_payload["consumed_strategy_refs"] == ["strategy:missingness_profile"]


def test_v2_smoke_history_backed_validated_replay_uses_contract_compatible_prior_run(
    tmp_path: Path,
) -> None:
    first_spec = CanonicalTaskSpec(
        task_family="continuous_csv_table_analysis",
        intent_op="detect_outliers",
        required_outputs=("outlier_artifact_ref", "baro_outlier_count"),
        required_tools=("table_retriever", "codeact_executor"),
        arguments={
            "dataset_id": "weather_baro_2015",
            "csv_path": "task/csv/baro_2015.csv",
            "column": "BARO",
            "method": "iqr",
            "threshold": 3,
            "quality_checks": ["exact:baro_outlier_count"],
            "reuse_contract": {
                "produces": ["outlier_artifact:weather_baro"],
                "consumes": ["strategy:iqr_outlier", "schema_profile:weather_baro_2015"],
                "minimum_reuse_class": "validated_replay",
            },
        },
    )
    bootstrap = run_smoke(
        workspace_root=tmp_path / "workspaces-bootstrap",
        runtime_root=tmp_path / "runtime-bootstrap",
        socket_path=tmp_path / "bootstrap.sock",
        task_id="csv-profile-008-bootstrap",
        request_text="detect weather baro outliers",
        canonical_task_spec=first_spec,
        layer_config=SmokeLayerConfig(
            layer_name="L3-continuous",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=True,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
        expected_facts={"baro_outlier_count": "111"},
        seed_replay_memory=False,
    )
    second_spec = CanonicalTaskSpec(
        task_family="continuous_csv_table_analysis",
        intent_op="detect_outliers",
        required_outputs=("outlier_artifact_ref", "baro_outlier_count"),
        required_tools=("table_retriever", "codeact_executor"),
        arguments={
            "dataset_id": "weather_baro_2015",
            "csv_path": "task/csv/baro_2015.csv",
            "column": "BARO",
            "method": "iqr",
            "threshold": 3,
            "quality_checks": ["exact:baro_outlier_count"],
            "reuse_contract": {
                "produces": ["outlier_artifact:weather_baro_followup"],
                "consumes": ["strategy:iqr_outlier", "schema_profile:weather_baro_2015"],
                "minimum_reuse_class": "validated_replay",
            },
        },
    )
    result = run_smoke(
        workspace_root=tmp_path / "workspaces-reuse",
        runtime_root=tmp_path / "runtime-reuse",
        socket_path=tmp_path / "reuse.sock",
        task_id="csv-profile-008-followup",
        request_text="detect weather baro outliers followup",
        canonical_task_spec=second_spec,
        layer_config=SmokeLayerConfig(
            layer_name="L3-continuous",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=True,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
        expected_facts={"baro_outlier_count": "111"},
        seed_replay_memory=False,
        history_runtime_roots=(Path(bootstrap.runtime_root),),
    )

    assert bootstrap.replay_class == "disallowed"
    assert result.replay_class == "validated_replay"
    assert result.task_metrics["validated_replay_count"] == 1.0
    assert result.task_metrics["exact_replay_count"] == 0.0
    replay_audit_payload = json.loads(Path(result.replay_audit_path).read_text(encoding="utf-8"))
    assert replay_audit_payload["replay_class"] == "validated_replay"
    assert replay_audit_payload["history_candidate_selection"]["selection_reason"] == "validated_replay_contract_match"


def test_v2_smoke_quality_checks_support_contains_and_fail_closed_for_unknown_checks(tmp_path: Path) -> None:
    spec = CanonicalTaskSpec(
        task_family="continuous_long_doc_table_analysis",
        intent_op="retrieve_narrative_evidence",
        required_outputs=("evidence_pack_ref", "churn_driver", "churn_delta_note"),
        required_tools=("semantic_retriever",),
        arguments={
            "dataset_id": "acme_ops_2026",
            "document_path": "v2/benchmark/samples/continuous_task_families/long_doc_table/acme_ops_report_2026.md",
            "topic": "enterprise churn Q3",
            "quality_checks": [
                "contains:churn_driver:delayed onboarding",
                "contains:churn_delta_note:1.1",
            ],
            "reuse_contract": {
                "produces": ["evidence_pack:churn_narrative"],
                "consumes": ["semantic_state:acme_ops_2026"],
                "minimum_reuse_class": "assist",
            },
        },
    )
    ok_result = run_smoke(
        workspace_root=tmp_path / "workspaces-ok",
        runtime_root=tmp_path / "runtime-ok",
        socket_path=tmp_path / "ok.sock",
        task_id="longdoc-006",
        request_text="find churn narrative evidence",
        canonical_task_spec=spec,
        layer_config=SmokeLayerConfig(
            layer_name="L2-longdoc",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=False,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
        expected_facts={
            "churn_driver": "delayed onboarding",
            "churn_delta_note": "1.1 percentage points",
        },
        seed_replay_memory=False,
    )
    assert ok_result.quality_floor.quality_floor_pass is True

    bad_spec = CanonicalTaskSpec(
        task_family=spec.task_family,
        intent_op=spec.intent_op,
        required_outputs=spec.required_outputs,
        required_tools=spec.required_tools,
        arguments={
            **spec.arguments,
            "quality_checks": ["unsupported_check:foo"],
        },
    )
    bad_result = run_smoke(
        workspace_root=tmp_path / "workspaces-bad",
        runtime_root=tmp_path / "runtime-bad",
        socket_path=tmp_path / "bad.sock",
        task_id="longdoc-006-bad",
        request_text="find churn narrative evidence",
        canonical_task_spec=bad_spec,
        layer_config=SmokeLayerConfig(
            layer_name="L2-longdoc",
            structured_control_enabled=True,
            semantic_pruning_enabled=True,
            replay_enabled=False,
            multi_attempt_enabled=False,
            force_first_attempt_trap=False,
        ),
        expected_facts={
            "churn_driver": "delayed onboarding",
            "churn_delta_note": "1.1 percentage points",
        },
        seed_replay_memory=False,
    )
    assert bad_result.quality_floor.quality_floor_pass is False
