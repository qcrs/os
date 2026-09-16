from __future__ import annotations

from pathlib import Path

from statebus.benchmark.g6b2_live_validation import (
    _embedding_rows_valid,
    _g6b2_campaign_slots,
    _g6b2_gpu_preflight_projection,
    _g6b2_live_failure_denominator,
    _g6b2_live_manifest,
    _g6b2_live_pair_projection,
    _g6b2_make_live_request,
    _g6b2_service_identity,
    _g6b2_write_artifacts,
    QWEN3_8B_U050_PROFILE,
    run_g6b2_live_campaign,
)
from statebus.benchmark.metric_aggregation import _g6b2_metric_availability
from statebus.benchmark.scoring import _g6b2_validate_live_pair
from statebus.utils import sha256_digest


def _rows() -> tuple[dict[str, object], dict[str, object]]:
    grant = {"grant_id": "grant-live", "attempt_id": "replay-attempt"}
    binding = {"binding_id": "binding-live", "attempt_id": "replay-attempt"}
    eligibility = {"receipt_id": "eligibility-live", "decision": "ELIGIBLE"}
    baseline = {
        "row_id": "live-baseline:one", "lane": "live-baseline", "memory_policy": "off", "runtime_memory_policy": "none",
        "family_id": "cross_period_financial", "round_number": 1, "repeat_id": 1, "cache_epoch": "base-epoch",
        "task_contract_hash": "task", "input_lineage_hashes": ["input"], "quality_contract_hash": "quality", "deterministic_seed": 7,
        "runtime_root": "/runtime/base", "workspace_root": "/workspace/base", "memory_root": "/memory/base", "session_id": "base-session", "attempt_id": "base-attempt", "terminal_status": "success",
        "model_identity": "qwen3-8b", "service_profile_id": QWEN3_8B_U050_PROFILE["profile_id"],
        "provider_invocation_evidence": {"status": "observed", "invocation_status": "completed", "recorded_by": "benchmark_bound_provider_adapter", "provider_id": "provider", "invocation_id": "invoke-live", "evidence_hash": "evidence-live", "request_reference": "requests/base.request.json", "response_reference": "requests/base.response.json", "served_model": "qwen3-8b", "source": "Runtime provider call boundary"},
        "quality_evidence": {"status": "observed", "passed": True, "report_hash": "quality-live", "current_input_recomputed": True},
        "result_admission": {"status": "observed", "receipt_hash": "base-admission"},
    }
    replay = {
        **baseline,
        "row_id": "live-replay:one", "lane": "live-validated-replay", "memory_policy": "validated_replay", "runtime_memory_policy": "validated_replay",
        "runtime_root": "/runtime/replay", "workspace_root": "/workspace/replay", "memory_root": "/memory/replay", "session_id": "replay-session", "attempt_id": "replay-attempt", "cache_epoch": "replay-epoch",
        "runtime_authority": "AdaptiveRuntimeEngine", "provider_invocation_evidence": None,
        "provider_not_started_observation": {"status": "observed", "provider_invocation_status": "not_started", "observation_id": "not-started-live", "execution_binding_hash": sha256_digest(binding), "capability_grant_hash": sha256_digest(grant), "memory_admission_receipt_hash": "memory-live", "replay_eligibility_receipt_hash": sha256_digest(eligibility), "quality_report_hash": "quality-live", "attempt_result_admission_receipt_hash": "replay-admission", "recipe_step_status": "unknown", "artifact_restore_status": "not_applicable"},
        "quality_evidence": {"status": "observed", "passed": True, "report_hash": "quality-live", "current_input_recomputed": True},
        "result_admission": {"status": "observed", "receipt_hash": "replay-admission"},
        "capability_grant": grant, "execution_binding": binding, "replay_eligibility_receipt": eligibility,
        "memory_consumption_receipt": {"memory_admission_receipt_hash": "memory-live", "attempt_result_admission_receipt_hash": "replay-admission"},
        "consumer_provider_boundary_call_count": 0,
        "recipe_recomputed": True,
    }
    return baseline, replay


def test_gpu_preflight_does_not_assume_gpu_two() -> None:
    profile = {**QWEN3_8B_U050_PROFILE, "physical_gpu": 1, "gpu_uuid": "GPU-test-1"}
    projection = _g6b2_gpu_preflight_projection(
        [{"index": 1, "uuid": "GPU-test-1", "memory.free": "70000 MiB"}], [], model_path_readable=True, vllm_executable_available=True,
        resolved_config={"model_path": "/data/models/Qwen3-8B", "served_model": "qwen3-8b", "host": "127.0.0.1", "port": 53334, "dtype": "bfloat16", "max_model_len": 4096, "max_num_seqs": 1, "max_num_batched_tokens": 4096, "gpu_memory_utilization": 0.50, "cpu_offload_gb": 0, "enforce_eager": True},
        model_profile=profile, authorized_gpu_indices=(1,), target_service_pids=(42,),
    )
    assert projection["status"] == "observed"
    assert projection["selected_physical_gpu"] == 1
    shared = _g6b2_gpu_preflight_projection(
        [{"index": 1, "uuid": "GPU-test-1", "memory.free": "1 MiB"}],
        [{"pid": 3, "gpu_uuid": "GPU-test-1"}],
        model_path_readable=True,
        vllm_executable_available=True,
        resolved_config=projection["resolved_config"],
        model_profile=profile,
        authorized_gpu_indices=(1,),
        authorized_competing_processes=({"pid": 999},),
        target_service_pids=(42,),
    )
    assert shared["status"] == "observed"
    assert shared["coexistence_policy"] == "operator_managed_not_checked"
    assert shared["compute_processes_checked"] is False
    assert shared["compute_processes"] == []
    assert shared["unrecognized_processes"] == []


def test_gpu_preflight_still_requires_target_vllm_identity() -> None:
    profile = {
        **QWEN3_8B_U050_PROFILE,
        "physical_gpu": 1,
        "gpu_uuid": "GPU-test-1",
    }
    missing = _g6b2_gpu_preflight_projection(
        [{"index": 1, "uuid": "GPU-test-1", "memory.free": "70000 MiB"}],
        [],
        model_path_readable=True,
        vllm_executable_available=True,
        resolved_config={},
        model_profile=profile,
        authorized_gpu_indices=(1,),
        target_service_pids=(),
    )
    assert missing["status"] == "environment_fail"
    assert "target_service_process_missing" in missing["reason"]
    assert "service_config_mismatch" in missing["reason"]


def test_service_identity_does_not_inspect_coexisting_processes(
    tmp_path: Path, monkeypatch
) -> None:
    import json
    import os
    import statebus.benchmark.g6b2_live_validation as module

    runtime = tmp_path / "service"
    runtime.mkdir()
    (runtime / "service.pid").write_text("101\n", encoding="utf-8")
    proc_calls: list[int] = []
    run_calls: list[list[str]] = []
    argv = (
        "/env/bin/vllm serve /data/models/Qwen3-8B "
        "--served-model-name qwen3-8b --host 127.0.0.1 --port 53334 "
        "--dtype bfloat16 --max-model-len 4096 --max-num-seqs 1 "
        "--max-num-batched-tokens 4096 --gpu-memory-utilization 0.50 "
        "--cpu-offload-gb 0 --enforce-eager"
    )

    def fake_proc(pid: int, *, include_start_time: bool = False):
        del include_start_time
        proc_calls.append(pid)
        return {"pid": pid, "uid": os.getuid(), "argv": argv}

    def fake_run(command):
        run_calls.append(list(command))
        return (
            0,
            f"0, {QWEN3_8B_U050_PROFILE['gpu_uuid']}, A100, 81920 MiB, 80000 MiB, 1 MiB, 100 %\n",
            "",
        )

    def fake_http(_method: str, url: str, **_kwargs):
        if url.endswith("/health"):
            return {"status": "observed", "http_status": 200, "body": ""}
        return {
            "status": "observed",
            "http_status": 200,
            "body": json.dumps({
                "data": [{
                    "id": "qwen3-8b",
                    "root": "/data/models/Qwen3-8B",
                    "max_model_len": 4096,
                }]
            }),
        }

    monkeypatch.setattr(module, "_proc_snapshot", fake_proc)
    monkeypatch.setattr(module, "_descendant_pids", lambda _pid: {101, 102})
    monkeypatch.setattr(module, "_run", fake_run)
    monkeypatch.setattr(module, "_g6b2_http_request", fake_http)
    monkeypatch.setattr(module.os, "access", lambda *_args: True)

    identity, preflight, _probes = _g6b2_service_identity(
        runtime, (999,)
    )

    assert preflight["status"] == "observed"
    assert identity["requested_coexist_pids"] == [999]
    assert identity["coexistence_process_inspection"] is False
    assert identity["authorized_coexisting_processes"] == []
    assert 999 not in proc_calls
    assert len(run_calls) == 1
    assert "--query-compute-apps" not in " ".join(run_calls[0])


def test_live_pair_requires_real_evidence_and_uses_c2c_key() -> None:
    baseline, replay = _rows()
    pair = _g6b2_validate_live_pair(baseline, replay, model_profile=QWEN3_8B_U050_PROFILE)
    assert pair["status"] == "eligible"
    assert pair["pair_key"]
    replay["provider_not_started_observation"]["status"] = "unsupported"
    assert _g6b2_validate_live_pair(baseline, replay, model_profile=QWEN3_8B_U050_PROFILE)["status"] == "rejected"


def test_campaign_and_metrics_keep_failure_rows() -> None:
    baseline, replay = _rows()
    projection = _g6b2_live_pair_projection([baseline], [replay], model_profile=QWEN3_8B_U050_PROFILE)
    denominator = _g6b2_live_failure_denominator([baseline], [replay], projection)
    metrics = _g6b2_metric_availability([baseline], [replay], projection["pairings"], projection["failure_rows"], denominator, {"status": "observed", "source_receipt_references": ["health"]})
    assert denominator["eligible_matched_pair_count"] == 1
    assert metrics["live_eligible_matched_pair_count"]["status"] == "observed"
    assert metrics["exact_replay"]["value"] is None
    assert metrics["recipe_step_skip"]["status"] == "deferred"


def test_artifact_writer_refuses_overwrite_and_writes_required_files(tmp_path: Path) -> None:
    baseline, replay = _rows()
    projection = _g6b2_live_pair_projection([baseline], [replay], model_profile=QWEN3_8B_U050_PROFILE)
    denominator = _g6b2_live_failure_denominator([baseline], [replay], projection)
    root = tmp_path / "g6b2-live-validation-20260916-v1"
    _g6b2_write_artifacts(root, gpu_preflight={"status": "environment_fail", "reason": "competing"}, vllm_health={"status": "environment_fail"}, vllm_model_identity={"identity_status": "not_run"}, baseline_rows=[baseline], replay_rows=[replay], pair_projection=projection, failure_denominator=denominator)
    assert (root / "g6b2_acceptance.json").is_file()
    try:
        _g6b2_write_artifacts(root, gpu_preflight={}, vllm_health={}, vllm_model_identity={})
    except FileExistsError:
        pass
    else:
        raise AssertionError("artifact root overwrite was accepted")


def test_manifest_fixed_boundaries() -> None:
    manifest = _g6b2_live_manifest()
    assert manifest["authorization"] == "user_authorized"
    assert manifest["b2_expansion_authorized"] is False
    assert manifest["exact_replay"]["status"] == "unsupported"
    assert manifest["recipe_step_skip"]["status"] == "deferred"
    assert manifest["benchmark_superiority"] == "NOT_ESTABLISHED"


def test_real_embedding_campaign_eight_covers_family_round_repeat_grid() -> None:
    slots = _g6b2_campaign_slots("campaign", 8)
    assert len(slots) == 8
    assert len({slot["deterministic_seed"] for slot in slots}) == 8
    assert {
        (slot["family_id"], slot["round_number"], slot["repeat_id"])
        for slot in slots
    } == {
        (family, round_number, repeat_id)
        for repeat_id in (1, 2)
        for round_number in (1, 2)
        for family in ("cross_period_financial", "incident_diagnosis")
    }


def test_real_embedding_request_replaces_only_retrieval_encoder(
    tmp_path: Path, monkeypatch
) -> None:
    import statebus.benchmark.g6b2_live_validation as module
    from statebus.memory.embedding import SentenceTransformerEmbeddingEncoder
    from statebus.retrieval import RetrieverFanoutPipeline

    monkeypatch.setattr(module, "EMBEDDING_MODE", "local")
    monkeypatch.setattr(module, "EMBEDDING_MODEL_PATH", "/models/Qwen3-Embedding-0.6B")
    monkeypatch.setattr(module, "EMBEDDING_DEVICE", "cuda:0")
    request, _provider = _g6b2_make_live_request(
        row_root=tmp_path / "row",
        artifact_root=tmp_path / "artifact",
        family_id="cross_period_financial",
        task_family="financial_report_analysis",
        task_id="real-embedding-request",
        session_id="session",
        run_id="run",
        value=101.0,
        memory_root=tmp_path / "memory",
        memory_policy="none",
        invocation_id="invocation",
    )
    closure_values = [
        cell.cell_contents
        for cell in request.bindings.retrieval_adapter._retrieve_query.__closure__
    ]
    pipeline = next(
        value for value in closure_values if isinstance(value, RetrieverFanoutPipeline)
    )
    assert isinstance(
        pipeline.semantic_retriever.encoder,
        SentenceTransformerEmbeddingEncoder,
    )
    assert pipeline.semantic_retriever.encoder.device == "cuda:0"
    assert request.bindings.retrieval_request_factory is not None
    assert request.bindings.bound_provider_handlers["g5b-execute-recipe"] is not None


def test_local_embedding_evidence_rejects_deterministic_fallback(monkeypatch) -> None:
    import statebus.benchmark.g6b2_live_validation as module

    monkeypatch.setattr(module, "EMBEDDING_MODE", "local")
    monkeypatch.setattr(
        module,
        "EMBEDDING_MODEL_PATH",
        "/statebus/models/Qwen3-Embedding-0.6B",
    )
    real = {
        "embedding_evidence": {
            "status": "observed",
            "encoding": "sentence-transformers:Qwen3-Embedding-0.6B",
            "dims": 1024,
        }
    }
    assert _embedding_rows_valid([real], [real], [real])
    deterministic = {
        "embedding_evidence": {
            "status": "observed",
            "encoding": "hashed-bow-v1",
            "dims": 16,
        }
    }
    assert not _embedding_rows_valid([real], [deterministic], [real])


def test_ctrl_c_during_slot_interval_finalizes_partial_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    import json
    import statebus.benchmark.g6b2_live_validation as module

    root = tmp_path / "interrupted"
    root.mkdir()
    (root / "gpu_preflight.json").write_text('{"status":"observed"}\n')
    (root / "vllm_health.json").write_text('{"status":"observed"}\n')
    (root / "vllm_model_identity.json").write_text(
        '{"identity_status":"matched"}\n'
    )
    (root / "live_stage_rows.partial.json").write_text(
        json.dumps({
            "rows": [{
                "row_id": "stage:preflight",
                "lane": "stage",
                "stage": "B2-Preflight",
                "terminal_status": "success",
            }]
        }) + "\n"
    )
    (root / "live_smoke.json").write_text(
        '{"terminal_status":"success","status":"observed"}\n'
    )

    def fake_execute(_root, _runtime, slot, *, timeout_s):
        del _root, _runtime, timeout_s
        baseline, replay = _rows()
        common = {
            "slot_id": slot["slot_id"],
            "family_id": slot["family_id"],
            "round_number": slot["round_number"],
            "repeat_id": slot["repeat_id"],
            "deterministic_seed": slot["deterministic_seed"],
        }
        baseline.update(common, row_id=f"baseline:{slot['slot_id']}")
        replay.update(common, row_id=f"replay:{slot['slot_id']}")
        producer = {
            **baseline,
            "row_id": f"producer:{slot['slot_id']}",
            "lane": "live-producer",
        }
        return baseline, producer, replay

    monkeypatch.setattr(module, "_execute_slot", fake_execute)
    monkeypatch.setattr(
        module.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    result = run_g6b2_live_campaign(
        artifact_root=root,
        mode="soak",
        pairs=2,
        max_duration_s=600,
        min_slot_interval_s=60,
    )
    assert result["status"] == "INCOMPLETE"
    assert result["interrupted"] is True
    assert (root / "final_gate_status.json").is_file()
    slots = json.loads((root / "live_slots.json").read_text())["slots"]
    assert [slot["execution_status"] for slot in slots] == [
        "completed",
        "not_run",
    ]


def test_execute_cli_returns_130_for_interrupted_result(monkeypatch) -> None:
    import statebus.benchmark.g6b2_live_validation as module

    monkeypatch.setattr(
        module,
        "run_g6b2_live_campaign",
        lambda **_kwargs: {
            "status": "INCOMPLETE",
            "artifact_root": "/tmp/interrupted",
            "eligible_live_pair_count": 0,
            "interrupted": True,
        },
    )
    assert module.main([
        "execute",
        "--mode",
        "soak",
        "--artifact-root",
        "/tmp/interrupted",
        "--pairs",
        "2",
        "--max-duration-s",
        "600",
        "--min-slot-interval-s",
        "60",
    ]) == 130
