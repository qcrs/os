from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from eval.runner import run_benchmark
from memory.store import DeterministicEmbeddingProvider
from runtime.llm import DeterministicLLMClient
from tasks.contest_family_spec import (
    SUPERIORITY_COMMUNICATION_MAINLINE_NAME,
    SUPERIORITY_MEMORY_MAINLINE_NAME,
    UNCERTAINTY_AUDIT_NAME,
    generate_superiority_comm_v1_payload,
    generate_superiority_memory_v1_payload,
    generate_uncertainty_audit_v1_payload,
)
from tasks.sample_tasks import load_task_set_bundle


def test_generated_taskset_split_payloads_match_frozen_object_boundaries() -> None:
    communication = generate_superiority_comm_v1_payload()
    memory = generate_superiority_memory_v1_payload()
    uncertainty = generate_uncertainty_audit_v1_payload()

    assert communication["task_set"]["name"] == SUPERIORITY_COMMUNICATION_MAINLINE_NAME
    assert communication["task_set"]["pack_type"] == "superiority_comm_v1"
    assert communication["task_set"]["claim_lanes"] == ["communication"]
    assert communication["task_set"]["plan_source_default"] == "llm"
    assert {task["complexity_bucket"] for task in communication["tasks"]} == {"simple", "distractor", "ambiguous"}
    assert all(task["expected_reuse_mode"] == "none" for task in communication["tasks"])
    assert all(task["runtime_reuse_contract"] == "reuse_disabled" for task in communication["tasks"])

    assert memory["task_set"]["name"] == SUPERIORITY_MEMORY_MAINLINE_NAME
    assert memory["task_set"]["pack_type"] == "superiority_memory_v1"
    assert memory["task_set"]["claim_lanes"] == ["memory"]
    assert memory["task_set"]["public_surface"] == "formal_secondary_memory"
    assert memory["task_set"]["plan_source_default"] == "llm"
    assert {task["complexity_bucket"] for task in memory["tasks"]} == {"simple", "reusable"}
    assert all(task["plan_source"] == "llm" for task in memory["tasks"])
    reusable_rows = [task for task in memory["tasks"] if task["complexity_bucket"] == "reusable"]
    assert reusable_rows
    assert all(task["expected_reuse_mode"] == "skip_execute" for task in reusable_rows)
    assert all(task["runtime_reuse_contract"] == "validated_replay" for task in reusable_rows)

    assert uncertainty["task_set"]["name"] == UNCERTAINTY_AUDIT_NAME
    assert uncertainty["task_set"]["pack_type"] == "uncertainty_audit_v1"
    assert uncertainty["task_set"]["public_surface"] == "audit_only"
    assert uncertainty["task_set"]["evidence_tier"] == "audit_only"
    assert {task["complexity_bucket"] for task in uncertainty["tasks"]} == {"ambiguous", "reusable", "distractor"}


def test_taskset_split_bundles_load_with_expected_metadata_and_case_surface() -> None:
    communication = load_task_set_bundle("superiority_comm_v1")
    memory = load_task_set_bundle("superiority_memory_v1")
    uncertainty = load_task_set_bundle("uncertainty_audit_v1")

    assert communication.metadata.pack_type == "superiority_comm_v1"
    assert communication.metadata.claim_lanes == ("communication",)
    assert communication.metadata.public_surface == "formal_headline"
    assert communication.metadata.plan_source_default == "llm"
    assert all(task.benchmark_lane == "communication" for task in communication.tasks)
    assert all(task.expected_reuse_mode == "none" for task in communication.tasks)
    assert {task.complexity_bucket for task in communication.tasks} == {"simple", "distractor", "ambiguous"}

    assert memory.metadata.pack_type == "superiority_memory_v1"
    assert memory.metadata.claim_lanes == ("memory",)
    assert memory.metadata.public_surface == "formal_secondary_memory"
    assert memory.metadata.plan_source_default == "llm"
    assert all(task.benchmark_lane == "memory" for task in memory.tasks)
    assert all(task.plan_source == "llm" for task in memory.tasks)
    assert {task.complexity_bucket for task in memory.tasks} == {"simple", "reusable"}
    assert all(task.required_prior_case_ids for task in memory.tasks if task.complexity_bucket == "reusable")
    assert all(task.required_prior_rejections for task in memory.tasks if task.complexity_bucket == "reusable")
    assert all(task.required_prior_routes for task in memory.tasks if task.complexity_bucket == "reusable")

    assert uncertainty.metadata.pack_type == "uncertainty_audit_v1"
    assert uncertainty.metadata.audit_only is True
    assert uncertainty.metadata.plan_source_default == "llm"
    assert all(task.benchmark_lane == "communication" for task in uncertainty.tasks)
    assert len(uncertainty.tasks) == len(uncertainty_payload_tasks())


def test_runner_reports_respect_new_mainline_split_boundaries() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-taskset-mainline-split-") as tmpdir:
        communication_result = asyncio.run(
            run_benchmark(
                task_set_path="superiority_comm_v1",
                repeat=1,
                out_dir=Path(tmpdir) / "comm",
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        communication_report = ((Path(tmpdir) / "comm") / "benchmark_report.md").read_text(encoding="utf-8")

        memory_result = asyncio.run(
            run_benchmark(
                task_set_path="superiority_memory_v1",
                repeat=1,
                out_dir=Path(tmpdir) / "memory",
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        memory_report = ((Path(tmpdir) / "memory") / "benchmark_report.md").read_text(encoding="utf-8")

        uncertainty_result = asyncio.run(
            run_benchmark(
                task_set_path="uncertainty_audit_v1",
                repeat=1,
                out_dir=Path(tmpdir) / "uncertainty",
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        uncertainty_report = ((Path(tmpdir) / "uncertainty") / "benchmark_report.md").read_text(encoding="utf-8")

    assert communication_result["manifest"]["task_pack_type"] == "superiority_comm_v1"
    assert communication_result["manifest"]["task_set_claim_lanes"] == ["communication"]
    assert communication_result["manifest"]["cross_lane_actual_parity_headline_blocking"] is False
    assert communication_result["manifest"]["contest_formal_coverage_gate"]["benchmark_lane"] == "communication"
    assert communication_result["manifest"]["contest_formal_coverage_gate"]["matched_pair_count"] == 12
    assert communication_result["manifest"]["contest_formal_coverage_gate"]["surface_complete"] is True
    assert communication_result["manifest"]["contest_formal_coverage_gate"]["repeat_sufficient"] is False
    assert communication_result["manifest"]["headline_gates"]["communication_gate"]["withheld_reasons"] == [
        "contest_repeat_insufficient"
    ]
    assert "## Communication Mainline" in communication_report
    assert "memory superiority remains out of scope" in communication_report

    assert memory_result["manifest"]["task_pack_type"] == "superiority_memory_v1"
    assert memory_result["manifest"]["task_set_claim_lanes"] == ["memory"]
    assert memory_result["manifest"]["contest_formal_coverage_gate"]["benchmark_lane"] == "memory"
    assert memory_result["manifest"]["contest_formal_coverage_gate"]["matched_pair_count"] == 10
    assert memory_result["manifest"]["contest_formal_coverage_gate"]["surface_complete"] is True
    assert "## Memory Mainline Scaffold" in memory_report
    assert "## Memory Mainline Metrics" in memory_report
    assert "## Replay Effect Gate" in memory_report
    assert "Real-effect requirement" in memory_report
    assert "assist_memory_hit_rate or memory_hit_rate alone does not count" in memory_report
    assert "This pack is only the memory mainline scaffold" in memory_report
    replay_gate = memory_result["manifest"]["headline_gates"]["memory_replay_gate"]["memory_replay_evidence_gate"]
    assert replay_gate["effect_required"] is True

    assert uncertainty_result["manifest"]["task_pack_type"] == "uncertainty_audit_v1"
    assert uncertainty_result["manifest"]["task_set_public_surface"] == "audit_only"
    assert uncertainty_result["manifest"]["cross_lane_actual_parity_headline_blocking"] is False
    assert uncertainty_result["manifest"]["contest_formal_coverage_gate"]["benchmark_lane"] == "communication"
    assert uncertainty_result["manifest"]["contest_formal_coverage_gate"]["matched_pair_count"] == 15
    assert uncertainty_result["manifest"]["contest_formal_coverage_gate"]["surface_complete"] is True
    assert "## Uncertainty Audit" in uncertainty_report
    assert "diagnostic-only" in uncertainty_report


def uncertainty_payload_tasks() -> list[dict[str, object]]:
    return generate_uncertainty_audit_v1_payload()["tasks"]
