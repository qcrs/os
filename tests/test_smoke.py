from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import msgpack
import numpy as np
import pytest

from agents.sample_agents import build_sample_agents_with_executor
from eval.runner import _mode_order_for_run, run_benchmark
from memory.store import DeterministicEmbeddingProvider, MemoryStore
from protocol.messages import PlanStep, RemoteStepRequest, RemoteStepResponse, StateRef, text_frame
from runtime.llm import DeterministicLLMClient
from runtime.orchestrator import Orchestrator, RunSession
from runtime.uds_transport import request_response
from runtime.smoke import main
from runtime.executor_runtime import build_feature_bundle, select_tool_name
from statepool.store import FileBackedStatePool, StatePool, StatePoolConfig
from tasks.local_corpus import extract_corpus_feature_hints, load_corpus_docs, retrieve_corpus_docs
from tasks.sample_tasks import SampleTask, default_task_chain


def test_smoke_runs(capsys) -> None:
    main()
    captured = capsys.readouterr()
    assert "statebus smoke ok" in captured.out
    assert "statebus smoke scope:" in captured.out


def test_runtime_smoke_module_entry_emits_stdout() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "runtime.smoke"],
        cwd="/home/qcrs/statebus/project",
        capture_output=True,
        text=True,
        check=True,
    )
    assert "statebus smoke scope:" in completed.stdout
    assert "statebus smoke ok:" in completed.stdout


def test_text_frame_is_natural_language_for_control_messages() -> None:
    rendered = text_frame(
        PlanStep(
            step_id="retrieve",
            owner_agent="retriever",
            action="RETRIEVE_EVIDENCE",
            input_state_refs=[],
            params={"query": "cache invalidation lag"},
            depends_on=[],
        )
    )
    assert rendered.startswith("Instruction for retriever:")
    assert '"query": "cache invalidation lag"' in rendered


def test_benchmark_runner_writes_outputs() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-benchmark-") as tmpdir:
        out_dir = Path(tmpdir) / "runs"
        result = asyncio.run(
            run_benchmark(
                repeat=1,
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        assert (out_dir / "benchmark_results.json").exists()
        assert (out_dir / "benchmark_compare.csv").exists()
        assert (out_dir / "benchmark_report.md").exists()
        payload = json.loads((out_dir / "benchmark_results.json").read_text(encoding="utf-8"))
        compare_csv = (out_dir / "benchmark_compare.csv").read_text(encoding="utf-8")
        assert payload["manifest"]["repeat"] == 1
        assert payload["manifest"]["llm_backend"] == "deterministic"
        assert payload["manifest"]["continuous_task_count"] == 19
        assert payload["manifest"]["expected_reuse_task_count"] == 12
        assert payload["manifest"]["expected_reuse_mode_counts"] == {
            "assist": 6,
            "none": 7,
            "skip_execute": 3,
            "skip_retrieve_execute": 3,
        }
        assert payload["manifest"]["task_contract_counts"] == {
            "allow_memory_assist": 12,
            "allow_execute_prune": 3,
            "allow_exact_replay": 3,
        }
        assert payload["manifest"]["benchmark_lane_counts"] == {
            "internal_regression": 18,
            "communication": 0,
            "state_transfer": 1,
            "memory": 0,
        }
        assert payload["manifest"]["transfer_strategy_counts"] == {
            "state_ref": 18,
            "text_brief": 0,
            "mode_split_text_brief_vs_state_ref": 1,
        }
        assert payload["manifest"]["task_groups"] == [
            "cache_chain",
            "latency_chain",
            "session_chain",
            "transfer_lane",
        ]
        assert result["summary"]["text"]["run_count"] == 1
        assert len(result["mode_runs"]["text"][0]["memory_db_paths"]) == 4
        assert "__aggregate__" in compare_csv
        assert "text_planner_total_tokens" in compare_csv
        assert "protocol_summarizer_total_tokens" in compare_csv
        assert "text_phase_overhead_ms" in compare_csv
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "StateBus Benchmark Report" in report_text
        assert "latency_chain" in (out_dir / "benchmark_compare.csv").read_text(encoding="utf-8")
        assert "session_chain" in (out_dir / "benchmark_compare.csv").read_text(encoding="utf-8")
        assert "Stability Summary" in report_text
        assert "Reuse Query Accounting" in report_text
        assert "Replay Contract Slice Summary" in report_text
        assert "Communication Vs Replay Axes" in report_text
        assert "Contest Benchmark Lanes" in report_text
        assert "State Transfer Strategies" in report_text
        assert "Memory Reuse Decisions By Mode" in report_text
        assert "Role-Level LLM Tokens" in report_text
        assert "Phase Timing Breakdown" in report_text
        assert result["summary"]["text"]["aggregate"]["skipped_step_count"] > 0
        assert result["summary"]["protocol"]["aggregate"]["skipped_step_count"] > 0
        assert result["summary"]["text"]["aggregate"]["reuse_gain"] > 0.0
        assert result["summary"]["protocol"]["aggregate"]["reuse_gain"] > 0.0
        assert result["summary"]["text"]["aggregate"]["planner_llm_request_count"] > 0
        assert result["summary"]["text"]["aggregate"]["summarizer_llm_request_count"] > 0
        assert result["summary"]["text"]["aggregate"]["planner_total_tokens"] == 0
        assert result["summary"]["text"]["aggregate"]["summarizer_total_tokens"] == 0
        assert result["summary"]["text"]["aggregate"]["planner_ms"] >= 0.0
        assert result["summary"]["text"]["aggregate"]["retrieve_ms"] >= 0.0
        assert result["summary"]["text"]["aggregate"]["execute_ms"] >= 0.0
        assert result["summary"]["text"]["aggregate"]["summarize_ms"] >= 0.0
        assert result["summary"]["text"]["aggregate"]["phase_overhead_ms"] >= 0.0
        assert (
            result["summary"]["text"]["aggregate"]["phase_accounted_ms"]
            <= result["summary"]["text"]["aggregate"]["task_ms"] + 1e-6
        )
        assert (
            result["summary"]["protocol"]["steady_state"]["protocol_bytes"]
            < result["summary"]["text"]["steady_state"]["text_bytes"]
        )

def test_reuse_modes_cover_assist_reject_and_skip_paths() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-test-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                repeat=1,
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    task_specs = {task.task_id: task for task in default_task_chain()}
    expected_assists = {task_id for task_id, task in task_specs.items() if task.expected_reuse_mode == "assist"}
    expected_skip_execute = {
        task_id for task_id, task in task_specs.items() if task.expected_reuse_mode == "skip_execute"
    }
    expected_skip_retrieve_execute = {
        task_id
        for task_id, task in task_specs.items()
        if task.expected_reuse_mode == "skip_retrieve_execute"
    }
    expected_anchors = {
        task_id
        for task_id, task in task_specs.items()
        if task.expected_reuse_mode == "none" and task.task_order == 1
    }
    expected_reject_controls = {
        task_id
        for task_id, task in task_specs.items()
        if task.expected_reuse_mode == "none" and task.task_order > 1
    }
    for mode in ("text", "protocol"):
        run = result["mode_runs"][mode][0]
        tasks = {task["task_id"]: task for task in run["tasks"]}
        for task_id in expected_assists:
            task = tasks[task_id]
            assert task["metrics"]["memory_hits"] >= 1
            assert task["metrics"]["memory_assist_task_count"] == 1
            assert task["metrics"]["skipped_step_count"] == 0
            assert task["reuse"]["applied"] is True
            assert task["reuse"]["mode"] == "assist"
            assert task["reuse"]["rejected_memory_id"] is None
            assert task["reuse_validation"]["matched_expectation"] is True
            assert task["results"]["retrieve"]["skipped"] is False
            assert task["results"]["execute"]["skipped"] is False
        for task_id in expected_skip_execute:
            task = tasks[task_id]
            assert task["metrics"]["memory_hits"] >= 1
            assert task["metrics"]["memory_assist_task_count"] == 0
            assert task["metrics"]["skipped_step_count"] == 1
            assert task["reuse"]["applied"] is True
            assert task["reuse"]["mode"] == "skip_execute"
            assert task["reuse"]["rejected_memory_id"] is None
            assert task["reuse_validation"]["matched_expectation"] is True
            assert task["results"]["retrieve"]["skipped"] is False
            assert task["results"]["execute"]["skipped"] is True
            assert task["results"]["execute"]["reused_from_memory_id"]
        for task_id in expected_skip_retrieve_execute:
            task = tasks[task_id]
            assert task["metrics"]["memory_hits"] >= 1
            assert task["metrics"]["memory_assist_task_count"] == 0
            assert task["metrics"]["skipped_step_count"] == 2
            assert task["reuse"]["applied"] is True
            assert task["reuse"]["mode"] == "skip_retrieve_execute"
            assert task["reuse"]["rejected_memory_id"] is None
            assert task["reuse_validation"]["matched_expectation"] is True
            assert task["results"]["retrieve"]["skipped"] is True
            assert task["results"]["execute"]["skipped"] is True
            assert task["results"]["retrieve"]["reused_from_memory_id"]
            assert task["results"]["execute"]["reused_from_memory_id"]
        for task_id in expected_anchors:
            task = tasks[task_id]
            assert task["metrics"]["memory_hits"] == 0
            assert task["metrics"]["skipped_step_count"] == 0
            assert task["metrics"]["memory_assist_task_count"] == 0
            assert task["reuse"]["applied"] is False
            assert task["reuse"]["rejected_memory_id"] is None
            assert task["reuse_validation"]["matched_expectation"] is True
        for task_id in expected_reject_controls:
            task = tasks[task_id]
            assert task["metrics"]["memory_hits"] >= 1
            assert task["metrics"]["memory_assist_task_count"] == 0
            assert task["metrics"]["memory_rejected_task_count"] == 1
            assert task["metrics"]["skipped_step_count"] == 0
            assert task["reuse"]["applied"] is False
            assert task["reuse"]["mode"] == "none"
            assert task["reuse"]["rejected_memory_id"] is not None
            assert task["reuse_validation"]["matched_expectation"] is True


def test_exact_replay_copies_reused_state_into_current_task_root() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-test-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                repeat=1,
                modes=("text",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        task = {
            item["task_id"]: item
            for item in result["mode_runs"]["text"][0]["tasks"]
        }["sample-cache-006"]
        reused_memory_id = task["reuse"]["memory_id"]
        assert reused_memory_id
        assert task["results"]["retrieve"]["payload"]["feature_route_source"] == "hint_consensus"
        assert task["results"]["retrieve"]["payload"]["feature_route_confidence"] >= 0.8
        assert task["results"]["retrieve"]["payload"]["feature_route_provenance"] == [
            "corpus_metadata",
            "lexical",
        ]
        assert task["results"]["retrieve"]["payload"]["feature_hint_doc_ids"] == [
            "cache-invalid-replay",
            "cache-invalid-anchor",
        ]
        assert task["results"]["execute"]["payload"]["route_source"] == "hint_consensus"
        assert task["results"]["execute"]["payload"]["route_confidence"] >= 0.8
        assert task["results"]["execute"]["payload"]["route_provenance"] == [
            "corpus_metadata",
            "lexical",
        ]
        assert task["results"]["execute"]["payload"]["hint_doc_ids"] == [
            "cache-invalid-replay",
            "cache-invalid-anchor",
        ]
        copied_refs = [
            ref
            for ref in task["state_refs"].values()
            if ref["metadata"].get("reused_from_memory_id") == reused_memory_id
        ]
        assert len(copied_refs) == 4
        for ref in copied_refs:
            assert ref["metadata"]["reused_from_memory_id"] == reused_memory_id
            assert "sample-cache-006" in ref["handle"]
            assert Path(ref["handle"]).exists()
        assert task["results"]["summarize"]["success"] is True
        assert task["results"]["summarize"]["skipped"] is False


def test_exact_replay_no_longer_requires_explicit_source_task_id() -> None:
    exact_replay_tasks = [task for task in default_task_chain() if task.expected_reuse_mode == "skip_retrieve_execute"]
    assert exact_replay_tasks
    assert all(task.replay_source_task_id == "" for task in exact_replay_tasks)

    with tempfile.TemporaryDirectory(prefix="statebus-test-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                repeat=1,
                modes=("text",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )

    tasks = {item["task_id"]: item for item in result["mode_runs"]["text"][0]["tasks"]}
    for task_id in ("sample-cache-006", "sample-latency-006", "sample-session-006"):
        task = tasks[task_id]
        assert task["reuse"]["mode"] == "skip_retrieve_execute"
        assert task["results"]["retrieve"]["skipped"] is True
        assert task["results"]["execute"]["skipped"] is True


def test_exact_replay_no_longer_requires_preferred_corpus_doc_ids() -> None:
    cache_prefix = [
        task
        for task in default_task_chain()
        if task.task_group == "cache_chain" and task.task_order <= 5
    ]
    exact_replay_without_doc_pref = SampleTask(
        task_id="sample-cache-006-no-pref",
        task_group="cache_chain",
        task_order=6,
        task_theme="repo_local_cache_staleness",
        goal="Run exact replay without benchmark-provided corpus doc preferences.",
        query="validated replay stale inventory aggregate invalidation after sync burst",
        tags=("cache", "inventory", "invalidation", "exact-replay"),
        reuse_tags=("cache", "inventory", "invalidation"),
        summary_hint=(
            "This exact replay should reuse the prior validated replay end to end "
            "without relying on current corpus doc preferences."
        ),
        corpus_doc_ids=(),
        expected_reuse_mode="skip_retrieve_execute",
        runtime_reuse_contract_override="exact_replay",
        evidence_text=(
            "Use the stored replay evidence plus current task inputs only; exact replay "
            "may skip retrieve and execute when the validated replay route matches exactly."
        ),
    )

    orchestrator = Orchestrator(
        build_sample_agents_with_executor(
            llm_client=DeterministicLLMClient(),
            executor_transport="local",
        )
    )
    session = RunSession(mode="text")
    embedder = DeterministicEmbeddingProvider()

    with tempfile.TemporaryDirectory(prefix="statebus-exact-replay-") as tmpdir:
        root = Path(tmpdir)
        memory_db_path = root / "cache_chain.sqlite3"
        final_ctx = None
        for task in [*cache_prefix, exact_replay_without_doc_pref]:
            ctx = Orchestrator.create_context(
                mode="text",
                task_id=task.task_id,
                task_group=task.task_group,
                task_theme=task.task_theme,
                state_root=root / task.task_id,
                memory_db_path=memory_db_path,
                embedder=embedder,
                session=session,
                task_corpus_doc_ids=task.corpus_doc_ids,
                runtime_profile=task.runtime_profile,
            )
            asyncio.run(orchestrator.run_task(task, ctx))
            if task.task_id == exact_replay_without_doc_pref.task_id:
                final_ctx = ctx

    assert final_ctx is not None
    assert final_ctx.reuse_mode == "skip_retrieve_execute"
    assert final_ctx.results["retrieve"].skipped is True
    assert final_ctx.results["execute"].skipped is True
    assert "candidate_corpus_doc_ids" not in final_ctx.results["retrieve"].payload
    assert "preferred_corpus_doc_ids" not in final_ctx.results["retrieve"].payload
    assert sorted(final_ctx.results["retrieve"].payload["retrieved_doc_ids"]) == [
        "cache-invalid-anchor",
        "cache-invalid-replay",
    ]


def test_validated_replay_respects_runtime_reuse_contract_gate() -> None:
    cache_prefix = [
        task
        for task in default_task_chain()
        if task.task_group == "cache_chain" and task.task_order <= 4
    ]
    validated_replay_without_contract = SampleTask(
        task_id="sample-cache-005-no-contract",
        task_group="cache_chain",
        task_order=5,
        task_theme="repo_local_cache_staleness",
        goal="Run validated replay from runtime evidence without a skip contract.",
        query="validated replay stale inventory aggregate invalidation after sync burst",
        tags=("cache", "inventory", "invalidation", "validated-replay"),
        reuse_tags=("cache", "inventory", "invalidation"),
        summary_hint=(
            "This validated replay should not prune execute when the runtime contract "
            "explicitly disables reuse."
        ),
        corpus_doc_ids=("cache-invalid-anchor", "cache-invalid-replay"),
        expected_reuse_mode="skip_execute",
        runtime_reuse_contract_override="reuse_disabled",
        evidence_text=(
            "Use the referenced corpus docs only; validated replay must still confirm "
            "the route from fresh retrieval."
        ),
    )

    orchestrator = Orchestrator(
        build_sample_agents_with_executor(
            llm_client=DeterministicLLMClient(),
            executor_transport="local",
        )
    )
    session = RunSession(mode="text")
    embedder = DeterministicEmbeddingProvider()

    with tempfile.TemporaryDirectory(prefix="statebus-validated-replay-") as tmpdir:
        root = Path(tmpdir)
        memory_db_path = root / "cache_chain.sqlite3"
        final_ctx = None
        for task in [*cache_prefix, validated_replay_without_contract]:
            ctx = Orchestrator.create_context(
                mode="text",
                task_id=task.task_id,
                task_group=task.task_group,
                task_theme=task.task_theme,
                state_root=root / task.task_id,
                memory_db_path=memory_db_path,
                embedder=embedder,
                session=session,
                task_corpus_doc_ids=task.corpus_doc_ids,
                runtime_profile=task.runtime_profile,
            )
            asyncio.run(orchestrator.run_task(task, ctx))
            if task.task_id == validated_replay_without_contract.task_id:
                final_ctx = ctx

    assert final_ctx is not None
    assert final_ctx.runtime_profile.runtime_reuse_contract == "reuse_disabled"
    assert final_ctx.reuse_mode == "none"
    assert final_ctx.results["retrieve"].skipped is False
    assert final_ctx.results["execute"].skipped is False
    assert final_ctx.results["execute"].reused_from_memory_id is None


def test_memory_assist_respects_runtime_reuse_contract_gate() -> None:
    cache_prefix = [
        task
        for task in default_task_chain()
        if task.task_group == "cache_chain" and task.task_order <= 1
    ]
    assist_without_contract = SampleTask(
        task_id="sample-cache-002-no-contract",
        task_group="cache_chain",
        task_order=2,
        task_theme="repo_local_cache_staleness",
        goal="Run memory assist from runtime evidence without an assist contract.",
        query="follow-up inventory stale counts shared aggregate invalidation hook",
        tags=("cache", "inventory", "invalidation", "followup"),
        reuse_tags=("cache", "inventory", "invalidation"),
        summary_hint=(
            "This follow-up should not accept assist memory when the runtime "
            "contract disables reuse."
        ),
        corpus_doc_ids=(
            "cache-invalid-anchor",
            "cache-invalid-followup",
            "cache-replica-false",
            "cache-invalid-replay",
        ),
        expected_reuse_mode="assist",
        runtime_reuse_contract_override="reuse_disabled",
        evidence_text=(
            "Use the referenced corpus docs only; matching assist memory may still "
            "be accepted after fresh retrieval."
        ),
    )

    orchestrator = Orchestrator(
        build_sample_agents_with_executor(
            llm_client=DeterministicLLMClient(),
            executor_transport="local",
        )
    )
    session = RunSession(mode="text")
    embedder = DeterministicEmbeddingProvider()

    with tempfile.TemporaryDirectory(prefix="statebus-assist-replay-") as tmpdir:
        root = Path(tmpdir)
        memory_db_path = root / "cache_chain.sqlite3"
        final_ctx = None
        for task in [*cache_prefix, assist_without_contract]:
            ctx = Orchestrator.create_context(
                mode="text",
                task_id=task.task_id,
                task_group=task.task_group,
                task_theme=task.task_theme,
                state_root=root / task.task_id,
                memory_db_path=memory_db_path,
                embedder=embedder,
                session=session,
                task_corpus_doc_ids=task.corpus_doc_ids,
                runtime_profile=task.runtime_profile,
            )
            asyncio.run(orchestrator.run_task(task, ctx))
            if task.task_id == assist_without_contract.task_id:
                final_ctx = ctx

    assert final_ctx is not None
    assert final_ctx.runtime_profile.runtime_reuse_contract == "reuse_disabled"
    assert final_ctx.reuse_mode == "none"
    assert final_ctx.results["retrieve"].skipped is False
    assert final_ctx.results["execute"].skipped is False
    assert final_ctx.results["retrieve"].payload["memory_assist_ids"] == []


def test_exact_replay_respects_runtime_reuse_contract_gate() -> None:
    cache_prefix = [
        task
        for task in default_task_chain()
        if task.task_group == "cache_chain" and task.task_order <= 5
    ]
    exact_replay_without_contract = SampleTask(
        task_id="sample-cache-006-no-contract",
        task_group="cache_chain",
        task_order=6,
        task_theme="repo_local_cache_staleness",
        goal="Run exact replay from runtime evidence without a skip contract.",
        query="validated replay stale inventory aggregate invalidation after sync burst",
        tags=("cache", "inventory", "invalidation", "exact-replay"),
        reuse_tags=("cache", "inventory", "invalidation"),
        summary_hint=(
            "This exact replay should not skip retrieve or execute when the runtime "
            "contract disables reuse."
        ),
        corpus_doc_ids=("cache-invalid-anchor", "cache-invalid-replay"),
        expected_reuse_mode="skip_retrieve_execute",
        runtime_reuse_contract_override="reuse_disabled",
        evidence_text=(
            "Use the stored replay evidence plus current task inputs only; exact replay "
            "may skip retrieve and execute when the validated replay route matches exactly."
        ),
    )

    orchestrator = Orchestrator(
        build_sample_agents_with_executor(
            llm_client=DeterministicLLMClient(),
            executor_transport="local",
        )
    )
    session = RunSession(mode="text")
    embedder = DeterministicEmbeddingProvider()

    with tempfile.TemporaryDirectory(prefix="statebus-exact-replay-") as tmpdir:
        root = Path(tmpdir)
        memory_db_path = root / "cache_chain.sqlite3"
        final_ctx = None
        for task in [*cache_prefix, exact_replay_without_contract]:
            ctx = Orchestrator.create_context(
                mode="text",
                task_id=task.task_id,
                task_group=task.task_group,
                task_theme=task.task_theme,
                state_root=root / task.task_id,
                memory_db_path=memory_db_path,
                embedder=embedder,
                session=session,
                task_corpus_doc_ids=task.corpus_doc_ids,
                runtime_profile=task.runtime_profile,
            )
            asyncio.run(orchestrator.run_task(task, ctx))
            if task.task_id == exact_replay_without_contract.task_id:
                final_ctx = ctx

    assert final_ctx is not None
    assert final_ctx.runtime_profile.runtime_reuse_contract == "reuse_disabled"
    assert final_ctx.reuse_mode == "none"
    assert final_ctx.results["retrieve"].skipped is False
    assert final_ctx.results["execute"].skipped is False
    assert final_ctx.results["retrieve"].reused_from_memory_id is None
    assert final_ctx.results["execute"].reused_from_memory_id is None


def test_statepool_writes_file_backed_artifacts() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-test-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                repeat=1,
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        first_text_run = result["mode_runs"]["text"][0]["tasks"][0]
        evidence_state_id = next(
            state_id
            for state_id, ref in first_text_run["state_refs"].items()
            if ref["kind"] == "DENSE_EVIDENCE"
        )
        evidence_ref = first_text_run["state_refs"][evidence_state_id]
        artifact_path = Path(evidence_ref["handle"])
        assert artifact_path.exists()
        assert "Sample incident" in artifact_path.read_text(encoding="utf-8")


def test_embedding_state_is_real_float32_vector() -> None:
    embedder = DeterministicEmbeddingProvider()
    with tempfile.TemporaryDirectory(prefix="statebus-test-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                repeat=1,
                out_dir=Path(tmpdir),
                embedder=embedder,
                llm_client=DeterministicLLMClient(),
            )
        )
        first_task = result["mode_runs"]["text"][0]["tasks"][0]
        embedding_state_id, embedding_payload = next(
            (state_id, ref)
            for state_id, ref in first_task["state_refs"].items()
            if ref["kind"] == "EMBEDDING"
        )
        ref = StateRef(
            state_id=embedding_state_id,
            kind="EMBEDDING",
            storage="MMAP_FILE",
            handle=embedding_payload["handle"],
            length=int(embedding_payload["length"]),
            metadata=dict(embedding_payload["metadata"]),
        )
        pool = FileBackedStatePool(Path(ref.handle).parent.parent)
        vector = pool.get_embedding(ref)
        assert vector.dtype == np.float32
        assert vector.shape == (embedder.vector_dim,)
        expected = embedder.embed_text(default_task_chain()[0].query)
        assert np.allclose(vector, expected)


def test_feature_bundle_state_is_real_msgpack_payload() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-test-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                repeat=1,
                modes=("text",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        first_task = result["mode_runs"]["text"][0]["tasks"][0]
        feature_state_id, feature_payload = next(
            (state_id, ref)
            for state_id, ref in first_task["state_refs"].items()
            if ref["kind"] == "FEATURE_BUNDLE"
        )
        payload = msgpack.unpackb(
            Path(feature_payload["handle"]).read_bytes(),
            raw=False,
            strict_map_key=False,
        )
        assert feature_state_id.endswith("-retrieve-features")
        assert payload["schema"] == "statebus.feature_bundle.v1"
        assert payload["route"] == "cache_invalidation"
        assert payload["tool_name"] == "tool.cache_invalidation_playbook"
        assert payload["route_source"] == "hint_consensus"
        assert payload["route_confidence"] >= 0.8
        assert payload["route_provenance"] == ["corpus_metadata", "lexical"]
        assert payload["hint_doc_ids"] == [
            "cache-invalid-anchor",
            "cache-invalid-followup",
        ]
        assert payload["tool_candidates"][0]["tool_name"] == "tool.cache_invalidation_playbook"
        assert payload["tool_candidates"][0]["source"] == "hint_consensus"
        assert "runtime_reuse_contract" not in payload
        assert "candidate_corpus_doc_ids" not in payload
        assert "preferred_corpus_doc_ids" not in payload
        assert "runtime_reuse_contract" not in feature_payload["metadata"]
        assert "candidate_corpus_doc_ids" not in feature_payload["metadata"]
        assert "preferred_corpus_doc_ids" not in feature_payload["metadata"]
        assert "tool_candidates" not in first_task["results"]["execute"]["payload"]


def test_feature_bundle_falls_back_to_generic_tool_when_signals_are_weak() -> None:
    payload = build_feature_bundle(
        query="investigate a vague incident with insufficient local evidence",
        evidence_text="Symptoms remain inconclusive and the current notes do not isolate one route.",
        tags=["triage"],
        reuse_signature="generic_triage:triage",
        reused_memory=False,
    )
    assert payload["route"] == "generic_triage"
    assert payload["tool_name"] == "tool.collect_more_evidence"
    assert payload["matched_signals"] == []
    assert payload["matched_tags"] == []
    assert payload["tool_candidates"][0]["tool_name"] == "tool.collect_more_evidence"
    assert payload["tool_candidates"][0]["source"] == "fallback"
    assert select_tool_name(payload) == "tool.collect_more_evidence"


def test_corpus_retrieval_can_surface_stronger_out_of_hint_docs() -> None:
    docs = retrieve_corpus_docs(
        query="reporting replica lag after failover caused stale reads",
        tags=["cache", "inventory", "replica"],
        task_group="cache_chain",
        task_theme="repo_local_cache_staleness",
        corpus_doc_ids=["cache-invalid-anchor", "cache-invalid-followup"],
        embedder=DeterministicEmbeddingProvider(),
        top_k=2,
    )
    doc_ids = [doc.doc_id for doc in docs]
    assert "cache-replica-false" in doc_ids
    assert doc_ids[0] == "cache-replica-false"


def test_corpus_retrieval_no_longer_preprunes_to_task_group_or_theme() -> None:
    docs = retrieve_corpus_docs(
        query="login failures from aggressive backoff window and auth rate limiter",
        tags=["auth", "session", "rate-limit"],
        task_group="cache_chain",
        task_theme="repo_local_cache_staleness",
        corpus_doc_ids=["cache-invalid-anchor", "cache-invalid-followup"],
        embedder=DeterministicEmbeddingProvider(),
        top_k=2,
    )
    doc_ids = [doc.doc_id for doc in docs]
    assert doc_ids[0] == "session-rate-limit-false"
    assert "session-rate-limit-false" in doc_ids


def test_feature_bundle_prefers_retrieved_corpus_hints() -> None:
    corpus_docs = load_corpus_docs()
    hints = extract_corpus_feature_hints(
        [corpus_docs["latency-worker-false"], corpus_docs["latency-db-anchor"]]
    )
    payload = build_feature_bundle(
        query="latency burst around release window",
        evidence_text="The current note is terse and does not name the failure family.",
        tags=["latency", "release-17"],
        reuse_signature="repo_local_latency_triage:latency|release-17",
        reused_memory=False,
        retrieved_hints=hints,
    )
    assert payload["route"] == "worker_queue_starvation"
    assert payload["tool_name"] == "tool.worker_queue_triage"
    assert payload["route_source"] == "hint_consensus"
    assert payload["route_confidence"] >= 0.8
    assert payload["route_provenance"] == ["corpus_metadata", "lexical"]
    assert payload["hint_doc_ids"] == ["latency-worker-false"]
    assert payload["matched_signals"] == []
    assert payload["matched_tags"] == ["latency", "release-17"]
    assert payload["tool_candidates"][0]["tool_name"] == "tool.worker_queue_triage"
    assert payload["tool_candidates"][0]["source"] == "hint_consensus"


def test_feature_bundle_abstains_on_metadata_only_hints_without_supporting_signals() -> None:
    corpus_docs = load_corpus_docs()
    hints = extract_corpus_feature_hints([corpus_docs["latency-db-anchor"]])
    payload = build_feature_bundle(
        query="investigate an unclear incident",
        evidence_text="The current note is too vague to isolate a route.",
        tags=["triage"],
        reuse_signature="generic_triage:triage",
        reused_memory=False,
        retrieved_hints=hints,
    )
    assert payload["route"] == "generic_triage"
    assert payload["tool_name"] == "tool.collect_more_evidence"
    assert payload["route_source"] == "metadata_only_abstain"
    assert payload["route_confidence"] == 0.0
    assert payload["route_provenance"] == ["corpus_metadata_unverified"]
    assert payload["hint_doc_ids"] == ["latency-db-anchor"]
    assert payload["hint_route"] == "db_pool_saturation"
    assert payload["hint_tool_name"] == "tool.db_pool_triage"
    assert payload["tool_candidates"][0]["tool_name"] == "tool.collect_more_evidence"
    assert payload["tool_candidates"][0]["source"] == "metadata_only_abstain"
    assert payload["tool_candidates"][1]["tool_name"] == "tool.db_pool_triage"


def test_feature_bundle_ignores_invalid_hints_and_falls_back_to_lexical_match() -> None:
    payload = build_feature_bundle(
        query="inventory looks stale after sync window",
        evidence_text=(
            "The post-sync cache invalidation hook missed the shared inventory aggregate key."
        ),
        tags=["cache", "inventory"],
        reuse_signature="repo_local_cache_staleness:cache|inventory",
        reused_memory=False,
        retrieved_hints=[
            {"doc_id": "bad-1", "route": "does_not_exist", "tool_name": ""},
            {"doc_id": "bad-2", "route": "cache_invalidation", "tool_name": "tool.db_pool_triage"},
        ],
    )
    assert payload["route"] == "cache_invalidation"
    assert payload["tool_name"] == "tool.cache_invalidation_playbook"
    assert payload["route_source"] == "lexical_match"
    assert payload["hint_doc_ids"] == []
    assert "cache invalidation" in payload["matched_signals"]
    assert payload["tool_candidates"][0]["tool_name"] == "tool.cache_invalidation_playbook"


def test_feature_bundle_emits_small_ranked_tool_candidate_set() -> None:
    payload = build_feature_bundle(
        query="release-17 latency db wait profile plus worker queue stall",
        evidence_text=(
            "The latest report mentions db pool saturation, slow orders query behavior, "
            "and a concurrent worker queue starvation during tls reload."
        ),
        tags=["latency", "database", "worker", "release-17"],
        reuse_signature="repo_local_latency_triage:database|latency|worker",
        reused_memory=False,
    )
    candidate_names = [candidate["tool_name"] for candidate in payload["tool_candidates"]]
    assert len(payload["tool_candidates"]) <= 3
    assert payload["tool_candidates"][0]["tool_name"] == payload["tool_name"]
    assert "tool.db_pool_triage" in candidate_names
    assert "tool.worker_queue_triage" in candidate_names


def test_feature_bundle_abstains_on_ambiguous_cross_route_candidates() -> None:
    payload = build_feature_bundle(
        query="release-17 orders latency db wait profile plus worker queue stall",
        evidence_text=(
            "The incident notes mention db pool saturation, slow orders query behavior, "
            "and a concurrent worker queue starvation during tls reload."
        ),
        tags=["latency", "database", "worker", "release-17"],
        reuse_signature="repo_local_latency_triage:database|latency|worker",
        reused_memory=False,
    )
    assert payload["route"] == "generic_triage"
    assert payload["tool_name"] == "tool.collect_more_evidence"
    assert payload["route_source"] == "ambiguous_candidates_abstain"
    assert payload["route_confidence"] == 0.0
    assert payload["route_provenance"] == ["lexical_ambiguous"]
    assert payload["tool_candidates"][0]["tool_name"] == "tool.collect_more_evidence"
    assert payload["tool_candidates"][0]["source"] == "ambiguous_candidates_abstain"
    candidate_names = [candidate["tool_name"] for candidate in payload["tool_candidates"]]
    assert "tool.db_pool_triage" in candidate_names
    assert "tool.worker_queue_triage" in candidate_names
    assert select_tool_name(payload) == "tool.collect_more_evidence"


def test_feature_bundle_keeps_single_route_selection_when_gap_is_clear() -> None:
    payload = build_feature_bundle(
        query="release-17 latency tls reload worker queue stall not database",
        evidence_text=(
            "Fresh evidence shows worker queue starvation, worker queue stall, "
            "and a tls reload cascade without db wait profile support."
        ),
        tags=["latency", "release-17", "orders", "worker"],
        reuse_signature="repo_local_latency_triage:latency|worker",
        reused_memory=False,
    )
    assert payload["route"] == "worker_queue_starvation"
    assert payload["tool_name"] == "tool.worker_queue_triage"
    assert payload["route_source"] == "lexical_match"
    assert payload["route_confidence"] > 0.0
    assert payload["tool_candidates"][0]["tool_name"] == "tool.worker_queue_triage"
    assert select_tool_name(payload) == "tool.worker_queue_triage"


def test_memory_commits_drop_runtime_contract_and_doc_hint_metadata() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-memory-metadata-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                repeat=1,
                modes=("text",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        cache_db_path = Path(result["mode_runs"]["text"][0]["memory_db_paths"]["cache_chain"])
        store = MemoryStore(cache_db_path, embedder=DeterministicEmbeddingProvider())
        try:
            rows = store.list_memories()
        finally:
            store.close()

    assist_row = next(row for row in rows if row["memory_id"] == "mem-sample-cache-001-assist")
    replay_row = next(row for row in rows if row["memory_id"] == "mem-sample-cache-001-replay")

    for row in (assist_row, replay_row):
        metadata = row["metadata"]
        assert metadata["memory_purpose"] in {"assist", "replay"}
        assert "runtime_reuse_contract" not in metadata
        assert "candidate_corpus_doc_ids" not in metadata
        assert "preferred_corpus_doc_ids" not in metadata
        assert metadata["retrieved_doc_ids"] == [
            "cache-invalid-anchor",
            "cache-invalid-followup",
        ]


def test_select_tool_name_prefers_ranked_tool_candidates() -> None:
    payload = {
        "route": "generic_triage",
        "tool_name": "",
        "tool_candidates": [
            {"tool_name": "tool.db_pool_triage", "route": "db_pool_saturation"},
            {"tool_name": "tool.collect_more_evidence", "route": "generic_triage"},
        ],
    }
    assert select_tool_name(payload) == "tool.db_pool_triage"


def test_state_transfer_lane_uses_text_brief_only_for_text_mode() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-transfer-lane-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                repeat=1,
                modes=("text", "protocol"),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    text_tasks = {task["task_id"]: task for task in result["mode_runs"]["text"][0]["tasks"]}
    protocol_tasks = {
        task["task_id"]: task for task in result["mode_runs"]["protocol"][0]["tasks"]
    }
    text_task = text_tasks["transfer-cache-001"]
    protocol_task = protocol_tasks["transfer-cache-001"]
    assert text_task["benchmark_lane"] == "state_transfer"
    assert protocol_task["benchmark_lane"] == "state_transfer"
    assert text_task["transfer_strategy"] == "text_brief"
    assert protocol_task["transfer_strategy"] == "state_ref"
    assert text_task["results"]["execute"]["payload"]["transfer_strategy"] == "text_brief"
    assert protocol_task["results"]["execute"]["payload"]["transfer_strategy"] == "state_ref"


def test_benchmark_supports_shared_memory_statepool_backend() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-shm-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                repeat=1,
                modes=("text",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
                statepool_config=StatePoolConfig.from_env(
                    default_backend="shared_memory",
                    embedding_backend="shared_memory",
                ),
            )
        )
    aggregate = result["summary"]["text"]["aggregate"]
    assert result["manifest"]["statepool_backend"] == "PY_SHARED_MEMORY"
    assert result["manifest"]["embed_state_backend"] == "PY_SHARED_MEMORY"
    assert aggregate["shared_memory_state_ref_count"] > 0
    first_task = result["mode_runs"]["text"][0]["tasks"][0]
    assert any(
        ref["storage"] == "PY_SHARED_MEMORY"
        for ref in first_task["state_refs"].values()
    )


def test_remote_executor_serves_over_uds() -> None:
    if not _unix_sockets_available():
        pytest.skip("AF_UNIX sockets are unavailable in the current sandbox; verify on host")
    with tempfile.TemporaryDirectory(prefix="statebus-uds-") as tmpdir:
        tmp_path = Path(tmpdir)
        socket_path = tmp_path / "executor.sock"
        state_root = tmp_path / "state"
        statepool = StatePool(state_root, config=StatePoolConfig.from_env())
        evidence_text = (
            "Sample incident: stale inventory persisted after batch sync. "
            "cache invalidation missed the inventory aggregate refresh."
        )
        evidence_ref = statepool.put_text(
            state_id="case-1-evidence",
            kind="DENSE_EVIDENCE",
            text=evidence_text,
        )
        bundle = build_feature_bundle(
            query="cache staleness stale inventory invalidation lag",
            evidence_text=evidence_text,
            tags=["cache", "inventory"],
            reuse_signature="repo_local_cache_triage:cache|inventory",
            reused_memory=False,
        )
        feature_ref = statepool.put_bytes(
            state_id="case-1-features",
            kind="FEATURE_BUNDLE",
            payload=msgpack.packb(bundle, use_bin_type=True),
            metadata={"schema": "statebus.feature_bundle.v1", "encoding": "msgpack"},
        )
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "runtime.remote_executor",
                "--socket-path",
                str(socket_path),
                "--max-requests",
                "1",
            ],
            cwd="/home/qcrs/statebus/project",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.time() + 5.0
            while time.time() < deadline and not socket_path.exists():
                if server.poll() is not None:
                    stderr = server.stderr.read() if server.stderr is not None else ""
                    stdout = server.stdout.read() if server.stdout is not None else ""
                    raise AssertionError(
                        "remote executor exited before binding socket: "
                        f"stdout={stdout!r} stderr={stderr!r}"
                    )
                time.sleep(0.05)
            assert socket_path.exists()
            response = request_response(
                socket_path,
                RemoteStepRequest(
                    mode="protocol",
                    task_id="case-1",
                    task_theme="repo_local_cache_triage",
                    state_root=str(state_root),
                    step=PlanStep(
                        step_id="execute",
                        owner_agent="executor",
                        action="EXECUTE_PLAYBOOK",
                        input_state_refs=[evidence_ref.state_id, feature_ref.state_id],
                        params={"transport": "uds"},
                        depends_on=["retrieve"],
                    ),
                    input_state_refs=[evidence_ref, feature_ref],
                ),
            )
            assert isinstance(response, RemoteStepResponse)
            assert response.result.success is True
            assert response.result.payload["tool_name"] == "tool.cache_invalidation_playbook"
            artifact_ref = response.result.output_state_refs[0]
            assert artifact_ref.kind == "TOOL_ARTIFACT"
            assert artifact_ref.storage == "MMAP_FILE"
        finally:
            if server.poll() is None:
                server.wait(timeout=5)


def test_benchmark_supports_uds_executor_transport() -> None:
    if not _unix_sockets_available():
        pytest.skip("AF_UNIX sockets are unavailable in the current sandbox; verify on host")
    with tempfile.TemporaryDirectory(prefix="statebus-benchmark-uds-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
                executor_transport="uds",
            )
        )
    assert result["manifest"]["executor_transport"] == "uds"
    assert result["manifest"]["executor_socket_path"]
    first_task = result["mode_runs"]["protocol"][0]["tasks"][0]
    assert first_task["results"]["execute"]["payload"]["sandbox_mode"] == "subprocess"


def _unix_sockets_available() -> bool:
    with tempfile.TemporaryDirectory(prefix="statebus-uds-probe-") as tmpdir:
        socket_path = Path(tmpdir) / "probe.sock"
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.bind(str(socket_path))
        except (PermissionError, OSError):
            return False
        finally:
            try:
                probe.close()
            except Exception:
                pass
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass
        return True


def test_benchmark_rerun_clears_old_group_memory() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-test-") as tmpdir:
        out_dir = Path(tmpdir) / "rerun"
        first = asyncio.run(
            run_benchmark(
                repeat=1,
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        second = asyncio.run(
            run_benchmark(
                repeat=1,
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    for payload in (first, second):
        for mode in ("text", "protocol"):
            tasks = {task["task_id"]: task for task in payload["mode_runs"][mode][0]["tasks"]}
            assert tasks["sample-cache-001"]["metrics"]["memory_hits"] == 0
            assert tasks["sample-latency-001"]["metrics"]["memory_hits"] == 0


def test_benchmark_repeat_ten_records_stability() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-repeat10-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                repeat=10,
                modes=("text",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    assert result["manifest"]["repeat"] == 10
    assert result["summary"]["text"]["run_count"] == 10
    assert result["summary"]["text"]["aggregate"]["expectation_match_rate"] == 1.0
    assert result["summary"]["text"]["stability"]["control_bytes"]["mean"] > 0.0


def test_mode_order_alternates_by_run() -> None:
    assert _mode_order_for_run(("text", "protocol"), 0) == ("text", "protocol")
    assert _mode_order_for_run(("text", "protocol"), 1) == ("protocol", "text")
