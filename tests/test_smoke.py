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

from eval.runner import _mode_order_for_run, run_benchmark
from memory.store import DeterministicEmbeddingProvider
from protocol.messages import PlanStep, RemoteStepRequest, RemoteStepResponse, StateRef, text_frame
from runtime.llm import DeterministicLLMClient
from runtime.uds_transport import request_response
from runtime.smoke import main
from runtime.executor_runtime import build_feature_bundle
from statepool.store import FileBackedStatePool, StatePool, StatePoolConfig
from tasks.sample_tasks import default_task_chain


def test_smoke_runs(capsys) -> None:
    main()
    captured = capsys.readouterr()
    assert "statebus smoke ok" in captured.out


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
        assert payload["manifest"]["repeat"] == 1
        assert payload["manifest"]["llm_backend"] == "deterministic"
        assert payload["manifest"]["continuous_task_count"] == 12
        assert payload["manifest"]["expected_reuse_task_count"] == 6
        assert payload["manifest"]["task_groups"] == [
            "cache_chain",
            "latency_chain",
            "session_chain",
        ]
        assert result["summary"]["text"]["run_count"] == 1
        assert len(result["mode_runs"]["text"][0]["memory_db_paths"]) == 3
        assert "__aggregate__" in (out_dir / "benchmark_compare.csv").read_text(encoding="utf-8")
        assert "StateBus Benchmark Report" in (out_dir / "benchmark_report.md").read_text(
            encoding="utf-8"
        )
        assert "latency_chain" in (out_dir / "benchmark_compare.csv").read_text(encoding="utf-8")
        assert "session_chain" in (out_dir / "benchmark_compare.csv").read_text(encoding="utf-8")
        assert "Stability Summary" in (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "Reuse Query Accounting" in (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert (
            result["summary"]["protocol"]["steady_state"]["protocol_bytes"]
            < result["summary"]["text"]["steady_state"]["text_bytes"]
        )

def test_follow_up_tasks_use_memory_assist_or_reject_when_needed() -> None:
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
    expected_followups = {
        task_id for task_id, task in task_specs.items() if task.expected_reuse_mode == "assist"
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
        for task_id in expected_followups:
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
            assert task["reuse"]["rejected_memory_id"] is not None
            assert task["reuse_validation"]["matched_expectation"] is True


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
        assert "cache invalidation" in payload["matched_signals"]


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
