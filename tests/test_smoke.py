from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import numpy as np

from eval.runner import run_benchmark
from memory.store import DeterministicEmbeddingProvider
from protocol.messages import PlanStep, StateRef, text_frame
from runtime.llm import DeterministicLLMClient
from runtime.smoke import main
from statepool.store import FileBackedStatePool
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
        assert payload["manifest"]["continuous_task_count"] == 10
        assert payload["manifest"]["expected_reuse_task_count"] == 8
        assert payload["manifest"]["task_groups"] == ["cache_chain", "latency_chain"]
        assert result["summary"]["text"]["run_count"] == 1
        assert len(result["mode_runs"]["text"][0]["memory_db_paths"]) == 2
        assert "__aggregate__" in (out_dir / "benchmark_compare.csv").read_text(encoding="utf-8")
        assert "StateBus Benchmark Report" in (out_dir / "benchmark_report.md").read_text(
            encoding="utf-8"
        )
        assert "latency_chain" in (out_dir / "benchmark_compare.csv").read_text(encoding="utf-8")
        assert "Stability Summary" in (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert (
            result["summary"]["protocol"]["steady_state"]["protocol_bytes"]
            < result["summary"]["text"]["steady_state"]["text_bytes"]
        )

def test_follow_up_tasks_reuse_memory_and_skip_steps() -> None:
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
    expected_followups = {task_id for task_id, task in task_specs.items() if task.expected_reuse}
    expected_cold_starts = set(task_specs) - expected_followups
    for mode in ("text", "protocol"):
        run = result["mode_runs"][mode][0]
        tasks = {task["task_id"]: task for task in run["tasks"]}
        for task_id in expected_followups:
            task = tasks[task_id]
            assert task["metrics"]["memory_hits"] >= 1
            assert task["metrics"]["skipped_step_count"] >= 1
            assert task["reuse"]["applied"] is True
            assert set(task["reuse"]["skipped_step_ids"]) == {"retrieve", "execute"}
            assert task["reuse_validation"]["matched_expectation"] is True
            assert task["results"]["retrieve"]["skipped"] is True
            assert task["results"]["execute"]["skipped"] is True
        for task_id in expected_cold_starts:
            task = tasks[task_id]
            assert task["metrics"]["memory_hits"] == 0
            assert task["metrics"]["skipped_step_count"] == 0
            assert task["reuse"]["applied"] is False
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
        expected = embedder.embed_text("cache staleness stale inventory invalidation lag")
        assert np.allclose(vector, expected)


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
