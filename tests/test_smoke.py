from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
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
import hashlib

from agents.base_agent import BaseAgent
from agents.sample_agents import (
    _build_memory_assist_hint,
    _build_protocol_summary_handoff,
    _build_transfer_brief,
    build_sample_agents_with_executor,
)
from eval.runner import _mode_order_for_run, run_benchmark
from memory.store import DeterministicEmbeddingProvider, MemoryStore
from protocol.messages import MemoryHit
from protocol.messages import (
    Plan,
    PlanStep,
    RemoteStepRequest,
    RemoteStepResponse,
    StateRef,
    StepResult,
    text_frame,
)
from runtime.contracts import SchemaValidationError
from runtime.llm import DeterministicLLMClient
from runtime.orchestrator import Orchestrator, RunSession, _route_is_replay_eligible
from runtime.uds_transport import request_response
from runtime.smoke import main
from runtime.executor_runtime import (
    _feature_bundle_from_transfer_brief,
    build_feature_bundle,
    default_tool_registry,
    execute_playbook_step,
    select_tool_name,
)
from statepool.store import FileBackedStatePool, StatePool, StatePoolConfig
from tasks.local_corpus import (
    extract_corpus_feature_hints,
    load_corpus_docs,
    render_corpus_evidence,
    retrieve_corpus_docs,
)
from tasks.sample_tasks import SampleTask, default_task_chain, load_task_set_bundle

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_smoke_runs(capsys) -> None:
    main()
    captured = capsys.readouterr()
    assert "statebus smoke ok" in captured.out
    assert "statebus smoke scope:" in captured.out


def test_runtime_smoke_module_entry_emits_stdout() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "runtime.smoke"],
        cwd=REPO_ROOT,
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
        task_chain = default_task_chain()
        expected_lane_counts = {
            "internal_regression": sum(1 for task in task_chain if task.benchmark_lane == "internal_regression"),
            "communication": sum(1 for task in task_chain if task.benchmark_lane == "communication"),
            "state_transfer": sum(1 for task in task_chain if task.benchmark_lane == "state_transfer"),
            "memory": sum(1 for task in task_chain if task.benchmark_lane == "memory"),
        }
        expected_transfer_strategy_counts = {
            "state_ref": sum(1 for task in task_chain if task.transfer_strategy == "state_ref"),
            "text_brief": sum(1 for task in task_chain if task.transfer_strategy == "text_brief"),
            "state_packet_minimal": sum(
                1 for task in task_chain if task.transfer_strategy == "state_packet_minimal"
            ),
            "text_packet_minimal": sum(
                1 for task in task_chain if task.transfer_strategy == "text_packet_minimal"
            ),
            "natural_handoff_text": sum(
                1 for task in task_chain if task.transfer_strategy == "natural_handoff_text"
            ),
            "mode_split_text_brief_vs_state_ref": sum(
                1 for task in task_chain if task.transfer_strategy == "mode_split_text_brief_vs_state_ref"
            ),
        }
        expected_memory_policy_counts = {
            "memory_off": sum(1 for task in task_chain if task.runtime_reuse_contract == "reuse_disabled"),
            "assist_only": sum(1 for task in task_chain if task.runtime_reuse_contract == "assist_allowed"),
            "replay_enabled": sum(
                1 for task in task_chain if task.runtime_reuse_contract in {"validated_replay", "exact_replay"}
            ),
        }
        expected_artifact_expectation_counts = {
            "route": sum(1 for task in task_chain if task.expected_route),
            "route_source": sum(1 for task in task_chain if task.expected_route_source),
            "tool_name": sum(1 for task in task_chain if task.expected_tool_name),
            "top_doc_id": sum(1 for task in task_chain if task.expected_top_doc_id),
        }
        expected_task_contract_counts = {
            "allow_memory_assist": sum(1 for task in task_chain if task.runtime_gates["allow_memory_assist"]),
            "allow_execute_prune": sum(1 for task in task_chain if task.runtime_gates["allow_execute_prune"]),
            "allow_exact_replay": sum(1 for task in task_chain if task.runtime_gates["allow_exact_replay"]),
        }
        expected_task_mode_counts = {
            mode: sum(1 for task in task_chain if task.supports_mode(mode))
            for mode in ("text", "protocol")
        }
        assert payload["manifest"]["repeat"] == 1
        assert payload["manifest"]["llm_backend"] == "deterministic"
        assert payload["manifest"]["continuous_task_count"] == len(task_chain)
        assert payload["manifest"]["task_mode_counts"] == expected_task_mode_counts
        assert payload["manifest"]["expected_reuse_task_count"] == sum(1 for task in task_chain if task.expected_reuse)
        assert payload["manifest"]["expected_reuse_mode_counts"] == {
            "assist": sum(1 for task in task_chain if task.expected_reuse_mode == "assist"),
            "none": sum(1 for task in task_chain if task.expected_reuse_mode == "none"),
            "skip_execute": sum(1 for task in task_chain if task.expected_reuse_mode == "skip_execute"),
            "skip_retrieve_execute": sum(
                1 for task in task_chain if task.expected_reuse_mode == "skip_retrieve_execute"
            ),
        }
        assert payload["manifest"]["task_contract_counts"] == expected_task_contract_counts
        assert payload["manifest"]["benchmark_lane_counts"] == expected_lane_counts
        assert payload["manifest"]["transfer_strategy_counts"] == expected_transfer_strategy_counts
        assert payload["manifest"]["memory_policy_counts"] == expected_memory_policy_counts
        assert payload["manifest"]["artifact_expectation_counts"] == expected_artifact_expectation_counts
        assert payload["manifest"]["artifact_expectation_task_count"] == sum(
            1 for task in task_chain if any(task.artifact_expectations.values())
        )
        assert payload["manifest"]["task_groups"] == sorted({task.task_group for task in task_chain})
        assert payload["manifest"]["task_pack_type"] == "formal_controlled"
        assert result["summary"]["text"]["run_count"] == 1
        if expected_task_mode_counts["text"] == 0:
            assert result["mode_runs"]["text"][0]["tasks"] == []
        else:
            assert len(result["mode_runs"]["text"][0]["memory_db_paths"]) == len(
                {task.task_group for task in task_chain if task.supports_mode("text")}
            )
        assert "__aggregate__" in compare_csv
        assert "planner_total_tokens" in compare_csv
        assert "summarizer_total_tokens" in compare_csv
        assert "phase_overhead_ms" in compare_csv
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "StateBus Benchmark Report" in report_text
        assert "## Structured-vs-Text By Reuse Axis" in report_text
        assert "## Contest Claim Lane Deltas" in report_text
        assert "## Typed-Handoff State-Transfer Headline" in report_text
        assert "## Aggregate" in report_text
        assert "## Diagnostic Appendix" in report_text
        assert "## Benchmark Lane Diagnostics" in report_text
        assert "handoff_wire_bytes" in report_text
        assert "handoff_payload_bytes" in report_text
        assert "serialized StateRefLite pointers on the wire" in report_text
        assert "## Contest Benchmark Lanes" not in report_text
        assert report_text.index("## Structured-vs-Text By Reuse Axis") < report_text.index(
            "## Contest Claim Lane Deltas"
        )
        assert report_text.index("## Contest Claim Lane Deltas") < report_text.index(
            "## Typed-Handoff State-Transfer Headline"
        )
        assert report_text.index("## Typed-Handoff State-Transfer Headline") < report_text.index(
            "## Aggregate"
        )
        assert report_text.index("## Aggregate") < report_text.index("## Diagnostic Appendix")


def test_default_task_set_is_formal_controlled_pack() -> None:
    bundle = load_task_set_bundle()
    assert bundle.metadata.name == "formal_controlled_pack"
    assert bundle.metadata.pack_type == "formal_controlled"
    assert bundle.metadata.support_only is False
    assert "communication" in bundle.metadata.claim_lanes
    assert len(bundle.tasks) == 24
    task_ids = {task.task_id for task in bundle.tasks}
    assert not any(task_id.startswith("open-plan-") for task_id in task_ids)
    assert not any("lexical-override" in task_id for task_id in task_ids)


def test_task_pack_aliases_and_support_only_flags() -> None:
    expectations = {
        "default": ("formal_controlled", False, 24),
        "formal_controlled": ("formal_controlled", False, 24),
        "formal_controlled_pack": ("formal_controlled", False, 24),
        "state_transfer_carrier": ("state_transfer_carrier", False, 18),
        "state_transfer_carrier_pack": ("state_transfer_carrier", False, 18),
        "contest_release_regression_carrier": ("state_transfer_carrier", False, 18),
        "contest_release_regression_carrier_pack": ("state_transfer_carrier", False, 18),
        "state_transfer_authenticity": ("state_transfer_authenticity", False, 6),
        "state_transfer_authenticity_pack": ("state_transfer_authenticity", False, 6),
        "contest_release_regression_authenticity": ("state_transfer_authenticity", False, 18),
        "contest_release_regression_authenticity_pack": ("state_transfer_authenticity", False, 18),
        "state_transfer_pure_text": ("state_transfer_pure_text", False, 6),
        "state_transfer_pure_text_pack": ("state_transfer_pure_text", False, 6),
        "state_transfer_natural_support": ("state_transfer_natural_support", True, 6),
        "state_transfer_natural_support_pack": ("state_transfer_natural_support", True, 6),
        "contest_release_regression_natural_support": ("state_transfer_natural_support", True, 18),
        "contest_release_regression_natural_support_pack": ("state_transfer_natural_support", True, 18),
        "communication": ("communication", False, 2),
        "communication_pack": ("communication", False, 2),
        "memory": ("memory", False, 3),
        "memory_pack": ("memory", False, 3),
        "internal_regression": ("internal_regression", False, 21),
        "internal_regression_pack": ("internal_regression", False, 21),
        "open_validation": ("open_validation", True, 15),
        "open_validation_pack": ("open_validation", True, 15),
    }
    for alias, (pack_type, support_only, task_count) in expectations.items():
        bundle = load_task_set_bundle(alias)
        assert bundle.metadata.pack_type == pack_type
        assert bundle.metadata.support_only is support_only
        assert len(bundle.tasks) == task_count


def test_pack_boundary_split_keeps_headline_regression_and_open_validation_separate() -> None:
    formal_bundle = load_task_set_bundle("formal_controlled")
    internal_bundle = load_task_set_bundle("internal_regression")
    open_bundle = load_task_set_bundle("open_validation")

    formal_ids = {task.task_id for task in formal_bundle.tasks}
    internal_ids = {task.task_id for task in internal_bundle.tasks}
    open_ids = {task.task_id for task in open_bundle.tasks}

    assert "open-plan-cache-001" not in formal_ids
    assert "open-plan-latency-001" not in formal_ids
    assert "open-plan-session-001" not in formal_ids
    assert not any("lexical-override" in task_id for task_id in formal_ids)

    assert {
        "regr-lexical-override-cache-001",
        "regr-lexical-override-latency-001",
        "regr-lexical-override-session-001",
    }.issubset(internal_ids)
    assert {
        "open-plan-cache-001",
        "open-plan-latency-001",
        "open-plan-session-001",
    }.issubset(open_ids)


def test_orchestrator_respects_yaml_vs_llm_plan_source() -> None:
    agents = build_sample_agents_with_executor(llm_client=DeterministicLLMClient())
    orchestrator = Orchestrator(agents)
    base_task = default_task_chain()[0]
    llm_task = replace(base_task, task_id="open-plan-probe-001", plan_source="llm")

    with tempfile.TemporaryDirectory(prefix="statebus-plan-source-") as tmpdir:
        root = Path(tmpdir)
        yaml_ctx = Orchestrator.create_context(
            mode="protocol",
            task_id=base_task.task_id,
            task_group=base_task.task_group,
            task_theme=base_task.task_theme,
            state_root=root / "yaml-state",
            memory_db_path=root / "yaml.sqlite3",
            embedder=DeterministicEmbeddingProvider(),
            session=RunSession(mode="protocol"),
            runtime_profile=base_task.runtime_profile,
            task_corpus_doc_ids=base_task.corpus_doc_ids,
            task_corpus_path=base_task.corpus_path,
        )
        asyncio.run(orchestrator.run_task(base_task, yaml_ctx))
        assert yaml_ctx.metrics.planner_llm_request_count == 0
        assert yaml_ctx.metrics.planned_step_count == 3
        yaml_ctx.memory_store.close()
        yaml_ctx.session.cleanup()

        llm_ctx = Orchestrator.create_context(
            mode="protocol",
            task_id=llm_task.task_id,
            task_group=llm_task.task_group,
            task_theme=llm_task.task_theme,
            state_root=root / "llm-state",
            memory_db_path=root / "llm.sqlite3",
            embedder=DeterministicEmbeddingProvider(),
            session=RunSession(mode="protocol"),
            runtime_profile=llm_task.runtime_profile,
            task_corpus_doc_ids=llm_task.corpus_doc_ids,
            task_corpus_path=llm_task.corpus_path,
        )
        asyncio.run(orchestrator.run_task(llm_task, llm_ctx))
        assert llm_ctx.metrics.planner_llm_request_count == 1
        assert llm_ctx.metrics.planned_step_count == 3
        llm_ctx.memory_store.close()
        llm_ctx.session.cleanup()


def test_open_validation_task_set_is_support_only() -> None:
    bundle = load_task_set_bundle("open_validation")
    assert bundle.metadata.name == "open_validation_pack"
    assert bundle.metadata.pack_type == "open_validation"
    assert bundle.metadata.support_only is True
    assert bundle.metadata.claim_lanes == ()
    assert len(bundle.tasks) == 15
    assert sum(1 for task in bundle.tasks if task.plan_source == "llm") == 3


def test_open_validation_report_marks_support_only_boundary() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-open-pack-") as tmpdir:
        out_dir = Path(tmpdir) / "runs"
        result = asyncio.run(
            run_benchmark(
                task_set_path="open_validation",
                repeat=1,
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        payload = json.loads((out_dir / "benchmark_results.json").read_text(encoding="utf-8"))
        assert payload["manifest"]["task_set_name"] == "open_validation_pack"
        assert payload["manifest"]["task_pack_type"] == "open_validation"
        assert payload["manifest"]["support_evidence_only"] is True
        assert "support evidence only" in report_text
        assert "Task pack type: `open_validation`" in report_text
        assert "Task set name: `open_validation_pack`" in report_text
        assert "this frozen formal_controlled pack is lane-first" not in report_text

def test_reuse_modes_cover_assist_reject_and_skip_paths() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-test-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="internal_regression",
                repeat=1,
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    task_specs = {task.task_id: task for task in load_task_set_bundle("internal_regression").tasks}
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
        if task.benchmark_lane == "internal_regression" and task.expected_reuse_mode == "none" and task.task_order == 1
    }
    expected_reject_controls = {
        task_id
        for task_id, task in task_specs.items()
        if (
            task.benchmark_lane == "internal_regression"
            and task.expected_reuse_mode == "none"
            and task.task_order > 1
            and task.runtime_reuse_contract != "reuse_disabled"
        )
    }
    expected_memory_off_diagnostics = {
        task_id
        for task_id, task in task_specs.items()
        if (
            task.benchmark_lane == "internal_regression"
            and task.expected_reuse_mode == "none"
            and task.runtime_reuse_contract == "reuse_disabled"
        )
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
        for task_id in expected_memory_off_diagnostics:
            task = tasks[task_id]
            assert task["metrics"]["memory_hits"] == 0
            assert task["metrics"]["memory_assist_task_count"] == 0
            assert task["metrics"]["memory_rejected_task_count"] == 0
            assert task["metrics"]["skipped_step_count"] == 0
            assert task["reuse"]["applied"] is False
            assert task["reuse"]["mode"] == "none"
            assert task["reuse"]["rejected_memory_id"] is None
            assert task["reuse_validation"]["matched_expectation"] is True


def test_exact_replay_copies_reused_state_into_current_task_root() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-test-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="internal_regression",
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
        observability = task["results"]["retrieve"]["feature_observability"]
        assert observability["matched_signals"] == [
            "inventory aggregate",
            "aggregate invalidation",
            "invalidation hook",
            "stale inventory",
            "cache invalidation",
            "batch sync",
        ]
        assert observability["matched_tags"] == [
            "cache",
            "invalidation",
            "inventory",
        ]
        assert observability["match_score"] == 35
        assert observability["tool_candidates"][0]["tool_name"] == (
            "tool.cache_invalidation_playbook"
        )
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
        assert len(copied_refs) == 7
        assert {ref["kind"] for ref in copied_refs} == {
            "DENSE_EVIDENCE",
            "FEATURE_BUNDLE",
            "RANKED_EVIDENCE_BUNDLE",
            "TOOL_CANDIDATE_SET",
            "REPLAY_ELIGIBILITY_BUNDLE",
            "EMBEDDING",
            "TOOL_ARTIFACT",
        }
        for ref in copied_refs:
            assert ref["metadata"]["reused_from_memory_id"] == reused_memory_id
            assert "sample-cache-006" in ref["handle"]
            assert Path(ref["handle"]).exists()
        copied_artifact = next(ref for ref in copied_refs if ref["kind"] == "TOOL_ARTIFACT")
        assert copied_artifact["metadata"]["tool_name"] == "tool.cache_invalidation_playbook"
        assert copied_artifact["metadata"]["route"] == "cache_invalidation"
        assert copied_artifact["metadata"]["source_evidence"]
        assert task["results"]["summarize"]["success"] is True
        assert task["results"]["summarize"]["skipped"] is False


def test_exact_replay_no_longer_requires_explicit_source_task_id() -> None:
    exact_replay_tasks = [
        task
        for task in load_task_set_bundle("internal_regression").tasks
        if task.expected_reuse_mode == "skip_retrieve_execute"
    ]
    assert exact_replay_tasks
    assert all(task.replay_source_task_id == "" for task in exact_replay_tasks)

    with tempfile.TemporaryDirectory(prefix="statebus-test-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="internal_regression",
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
        for task in load_task_set_bundle("internal_regression").tasks
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


def test_memory_assist_hint_is_compact() -> None:
    hit = MemoryHit(
        memory_id="mem-sample-cache-001-assist",
        confidence=0.95,
        summary=(
            "Fresh evidence should identify delayed aggregate invalidation after batch sync "
            "and recommend forcing the post-sync invalidation hook with extra rollout detail "
            "that should not be copied into the live prompt verbatim."
        ),
    )
    hint = _build_memory_assist_hint(hit)
    assert hint.startswith("MEMORY_ASSIST_HINT mem-sample-cache-001-assist:")
    assert len(hint) <= 240
    assert hint.endswith("...")
def test_memory_assist_uses_compact_hint_and_keeps_feature_bundle_fresh() -> None:
    cache_prefix = [
        task
        for task in load_task_set_bundle("internal_regression").tasks
        if task.task_group == "cache_chain" and task.task_order <= 2
    ]
    orchestrator = Orchestrator(
        build_sample_agents_with_executor(
            llm_client=DeterministicLLMClient(),
            executor_transport="local",
        )
    )
    session = RunSession(mode="text")
    embedder = DeterministicEmbeddingProvider()

    with tempfile.TemporaryDirectory(prefix="statebus-assist-compact-") as tmpdir:
        root = Path(tmpdir)
        memory_db_path = root / "cache_chain.sqlite3"
        final_ctx = None
        assist_task = None
        evidence_text = ""
        feature_bundle: dict[str, object] | None = None
        for task in cache_prefix:
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
            if task.task_id == "sample-cache-002":
                final_ctx = ctx
                assist_task = task
                retrieve_result = final_ctx.results["retrieve"]
                evidence_ref = next(
                    ref for ref in retrieve_result.output_state_refs if ref.kind == "DENSE_EVIDENCE"
                )
                feature_ref = next(
                    ref for ref in retrieve_result.output_state_refs if ref.kind == "FEATURE_BUNDLE"
                )
                evidence_text = final_ctx.get_text_state(evidence_ref)
                feature_bundle = msgpack.unpackb(
                    final_ctx.statepool.get_bytes(feature_ref),
                    raw=False,
                    strict_map_key=False,
                )

    assert final_ctx is not None
    assert assist_task is not None
    retrieve_result = final_ctx.results["retrieve"]
    assert retrieve_result.payload["memory_assist_ids"] == ["mem-sample-cache-001-assist"]
    assert feature_bundle is not None
    fresh_docs = retrieve_corpus_docs(
        query=assist_task.query,
        tags=list(assist_task.tags),
        task_group=assist_task.task_group,
        task_theme=assist_task.task_theme,
        corpus_doc_ids=assist_task.corpus_doc_ids,
        embedder=embedder,
    )
    fresh_evidence_text = render_corpus_evidence(fresh_docs)
    expected_fresh_sha256 = hashlib.sha256(fresh_evidence_text.encode("utf-8")).hexdigest()

    assert "MEMORY_ASSIST_HINT mem-sample-cache-001-assist:" in evidence_text
    assert "MEMORY_ASSIST mem-sample-cache-001-assist:" not in evidence_text
    assert "should not be copied into the live prompt verbatim" not in evidence_text
    assert feature_bundle["memory_assist_ids"] == ["mem-sample-cache-001-assist"]
    assert feature_bundle["memory_assist_hint"].startswith(
        "MEMORY_ASSIST_HINT mem-sample-cache-001-assist:"
    )
    assert feature_bundle["evidence_sha256"] == expected_fresh_sha256


def test_protocol_summary_handoff_is_compact() -> None:
    handoff = _build_protocol_summary_handoff(
        query="validated replay stale inventory aggregate invalidation after sync burst",
        route="cache_invalidation",
        route_source="hint_consensus",
        route_confidence=0.95,
        retrieved_doc_ids=["cache-invalid-anchor", "cache-invalid-replay", "cache-extra"],
        matched_signals=["aggregate invalidation", "stale inventory", "sync burst", "follow-up", "extra"],
        memory_assist_hint="MEMORY_ASSIST_HINT mem-memory-cache-001-assist: Confirm prior invalidation summary.",
        evidence_preview="This should stay short and not expand into the full retrieved corpus evidence body.",
    )
    assert "StateBus protocol summary handoff" in handoff
    assert "Route: cache_invalidation" in handoff
    assert "Retrieved docs: cache-invalid-anchor, cache-invalid-replay, cache-extra" in handoff
    assert "Matched signals: aggregate invalidation, stale inventory, sync burst, follow-up" in handoff
    assert "MEMORY_ASSIST_HINT mem-memory-cache-001-assist:" in handoff
    assert "full retrieved corpus evidence body" in handoff
    assert handoff.count("\n") <= 9


def test_protocol_summarizer_uses_compact_evidence_handoff() -> None:
    summary_text = ""
    with tempfile.TemporaryDirectory(prefix="statebus-protocol-summary-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="memory",
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        tasks = {task["task_id"]: task for task in result["mode_runs"]["protocol"][0]["tasks"]}
        task = tasks["memory-cache-002"]
        summary_state_id = task["results"]["summarize"]["payload"]["summary_state_id"]
        summary_ref = task["state_refs"][summary_state_id]
        summary_text = Path(summary_ref["handle"]).read_text(encoding="utf-8")
    assert "StateBus protocol summary handoff" not in summary_text
    assert "MEMORY_ASSIST_HINT mem-memory-cache-001-assist:" not in summary_text
    assert "[cache-invalid-anchor]" not in summary_text
    assert "Actions:" in summary_text
    assert "Evidence:" not in summary_text


def test_exact_replay_respects_runtime_reuse_contract_gate() -> None:
    cache_prefix = [
        task
        for task in load_task_set_bundle("internal_regression").tasks
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
                task_set_path="communication",
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
                task_set_path="communication",
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
        expected = embedder.embed_text(load_task_set_bundle("communication").tasks[0].query)
        assert np.allclose(vector, expected)


def test_feature_bundle_state_is_real_msgpack_payload() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-test-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="internal_regression",
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


def test_protocol_state_ref_path_writes_split_feature_family_states() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-feature-family-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="internal_regression",
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        task = {
            item["task_id"]: item for item in result["mode_runs"]["protocol"][0]["tasks"]
        }["sample-cache-001"]
        refs = task["state_refs"]
        retrieve_payload = task["results"]["retrieve"]["payload"]
        split_state_ids = {
            retrieve_payload["ranked_evidence_state_id"]: "RANKED_EVIDENCE_BUNDLE",
            retrieve_payload["tool_candidate_state_id"]: "TOOL_CANDIDATE_SET",
            retrieve_payload["replay_eligibility_state_id"]: "REPLAY_ELIGIBILITY_BUNDLE",
        }
        for state_id, kind in split_state_ids.items():
            assert state_id
            assert refs[state_id]["kind"] == kind
        tool_candidate_payload = msgpack.unpackb(
            Path(refs[retrieve_payload["tool_candidate_state_id"]]["handle"]).read_bytes(),
            raw=False,
            strict_map_key=False,
        )
        replay_payload = msgpack.unpackb(
            Path(refs[retrieve_payload["replay_eligibility_state_id"]]["handle"]).read_bytes(),
            raw=False,
            strict_map_key=False,
        )
        assert tool_candidate_payload["schema"] == "statebus.tool_candidate_set.v1"
        assert tool_candidate_payload["tool_candidates"][0]["tool_name"] == "tool.cache_invalidation_playbook"
        assert replay_payload["schema"] == "statebus.replay_eligibility_bundle.v1"
        assert replay_payload["validated_replay_eligible"] is True
        assert replay_payload["exact_replay_eligible"] is True


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


def test_feature_bundle_abstains_on_low_confidence_single_route_match() -> None:
    payload = build_feature_bundle(
        query="investigate a vague release issue",
        evidence_text=(
            "The current note is still inconclusive.\n\n"
            "[latency-db-anchor] slow orders query"
        ),
        tags=[],
        reuse_signature="generic_triage:none",
        reused_memory=False,
    )
    assert payload["route"] == "generic_triage"
    assert payload["tool_name"] == "tool.collect_more_evidence"
    assert payload["route_source"] == "low_confidence_abstain"
    assert payload["route_confidence"] == 0.0
    assert payload["route_provenance"] == ["lexical_below_threshold"]
    assert payload["tool_candidates"][0]["tool_name"] == "tool.collect_more_evidence"
    assert payload["tool_candidates"][0]["source"] == "low_confidence_abstain"
    assert payload["tool_candidates"][1]["tool_name"] == "tool.db_pool_triage"


def test_feature_bundle_abstains_on_thin_query_only_route_without_hints() -> None:
    payload = build_feature_bundle(
        query="follow-up stale jwks callback issue",
        evidence_text="The current note is vague and still does not confirm a stable route.",
        tags=["auth", "session"],
        reuse_signature="repo_local_auth_session_drift:auth|session",
        reused_memory=False,
    )
    assert payload["route"] == "generic_triage"
    assert payload["tool_name"] == "tool.collect_more_evidence"
    assert payload["route_source"] == "low_confidence_abstain"
    assert payload["route_confidence"] == 0.0
    assert payload["route_provenance"] == ["lexical_thin_support"]
    assert payload["tool_candidates"][0]["tool_name"] == "tool.collect_more_evidence"
    assert payload["tool_candidates"][0]["source"] == "low_confidence_abstain"
    assert payload["tool_candidates"][1]["tool_name"] == "tool.auth_session_repair"


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


def test_feature_bundle_keeps_hint_consensus_with_weak_but_aligned_support() -> None:
    corpus_docs = load_corpus_docs()
    hints = extract_corpus_feature_hints([corpus_docs["latency-db-anchor"]])
    payload = build_feature_bundle(
        query="investigate a vague release issue",
        evidence_text="The current note is too terse to isolate a route.",
        tags=["database"],
        reuse_signature="generic_triage:database",
        reused_memory=False,
        retrieved_hints=hints,
    )
    assert payload["route"] == "db_pool_saturation"
    assert payload["tool_name"] == "tool.db_pool_triage"
    assert payload["route_source"] == "hint_consensus"
    assert payload["route_confidence"] == 0.8
    assert payload["route_provenance"] == ["corpus_metadata", "lexical"]
    assert payload["hint_doc_ids"] == ["latency-db-anchor"]
    assert payload["tool_candidates"][0]["tool_name"] == "tool.db_pool_triage"
    assert payload["tool_candidates"][0]["source"] == "hint_consensus"


def test_transfer_brief_round_trip_preserves_executor_snapshot() -> None:
    corpus_docs = load_corpus_docs()
    hints = extract_corpus_feature_hints([corpus_docs["latency-db-anchor"]])
    query = "investigate a vague release issue"
    evidence_text = "The current note is too terse to isolate a route."
    payload = build_feature_bundle(
        query=query,
        evidence_text=evidence_text,
        tags=["database"],
        reuse_signature="generic_triage:database",
        reused_memory=False,
        retrieved_hints=hints,
    )
    brief = _build_transfer_brief(
        query=query,
        retrieved_doc_ids=["latency-db-anchor"],
        route=str(payload["route"]),
        tool_name=str(payload["tool_name"]),
        route_source=str(payload["route_source"]),
        route_confidence=float(payload["route_confidence"]),
        route_provenance=[str(item) for item in payload["route_provenance"]],
        matched_signals=[str(item) for item in payload["matched_signals"]],
        matched_tags=[str(item) for item in payload["matched_tags"]],
        match_score=int(payload["match_score"]),
        hint_doc_ids=[str(item) for item in payload["hint_doc_ids"]],
        hint_route=str(payload["hint_route"]),
        hint_tool_name=str(payload["hint_tool_name"]),
        tool_candidates=[dict(item) for item in payload["tool_candidates"]],
        memory_assist_ids=[],
        evidence_text=evidence_text,
    )
    assert "Suggested tool: tool.db_pool_triage" in brief
    assert "Route confidence: 0.80" in brief
    assert "Tool candidates: tool.db_pool_triage@db_pool_saturation#hint_consensus#" in brief
    rebuilt = _feature_bundle_from_transfer_brief(
        query_text=query,
        evidence_text=evidence_text,
        brief_text=brief,
        registry=default_tool_registry(),
    )
    assert rebuilt["route"] == payload["route"]
    assert rebuilt["tool_name"] == payload["tool_name"]
    assert rebuilt["route_source"] == payload["route_source"]
    assert rebuilt["route_confidence"] == payload["route_confidence"]
    assert rebuilt["route_provenance"] == payload["route_provenance"]
    assert rebuilt["matched_tags"] == payload["matched_tags"]
    assert rebuilt["hint_doc_ids"] == payload["hint_doc_ids"]
    assert [candidate["tool_name"] for candidate in rebuilt["tool_candidates"]] == [
        candidate["tool_name"] for candidate in payload["tool_candidates"]
    ]
    assert select_tool_name(rebuilt) == payload["tool_name"]


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


def test_feature_bundle_memory_prior_can_prune_ambiguous_candidates_upstream() -> None:
    payload = build_feature_bundle(
        query="release-17 orders latency db wait profile plus worker queue stall",
        evidence_text=(
            "The incident notes mention db pool saturation, slow orders query behavior, "
            "and a concurrent worker queue starvation during tls reload."
        ),
        tags=["latency", "database", "worker", "release-17"],
        reuse_signature="repo_local_latency_triage:database|latency|worker",
        reused_memory=False,
        memory_prior={
            "memory_id": "mem-worker-prior",
            "route": "worker_queue_starvation",
            "tool_name": "tool.worker_queue_triage",
            "confidence": 0.91,
            "summary": "Prior aligned worker-queue diagnosis.",
        },
    )
    assert payload["route"] == "worker_queue_starvation"
    assert payload["tool_name"] == "tool.worker_queue_triage"
    assert payload["route_source"] == "lexical_match"
    assert payload["memory_prior_id"] == "mem-worker-prior"
    assert payload["memory_prior_route"] == "worker_queue_starvation"
    assert payload["memory_prior_tool_name"] == "tool.worker_queue_triage"
    assert payload["memory_prior_applied"] is True
    assert payload["memory_candidate_count_before"] >= 2
    assert payload["memory_candidate_count_after"] == 1
    assert payload["memory_candidate_reduction"] >= 1
    assert payload["memory_prior_route_agreement"] is True
    assert payload["memory_prior_rescue"] is True
    assert payload["tool_candidates"][0]["tool_name"] == "tool.worker_queue_triage"
    assert payload["tool_candidates"][0]["source"] == "lexical_match"


def test_feature_bundle_memory_prior_does_not_override_without_live_support() -> None:
    payload = build_feature_bundle(
        query="investigate an unclear incident",
        evidence_text="The current note is too vague to isolate a route.",
        tags=["triage"],
        reuse_signature="generic_triage:triage",
        reused_memory=False,
        memory_prior={
            "memory_id": "mem-db-prior",
            "route": "db_pool_saturation",
            "tool_name": "tool.db_pool_triage",
            "confidence": 0.93,
            "summary": "Prior DB saturation diagnosis.",
        },
    )
    assert payload["route"] == "generic_triage"
    assert payload["tool_name"] == "tool.collect_more_evidence"
    assert payload["route_source"] == "fallback"
    assert payload["memory_prior_id"] == "mem-db-prior"
    assert payload["memory_prior_route"] == "db_pool_saturation"
    assert payload["memory_prior_tool_name"] == "tool.db_pool_triage"
    assert payload["memory_prior_applied"] is False
    assert payload["memory_candidate_count_after"] == payload["memory_candidate_count_before"]
    assert payload["memory_candidate_reduction"] == 0
    assert payload["memory_prior_route_agreement"] is False
    assert payload["memory_prior_rescue"] is False


def test_route_replay_eligibility_requires_lexical_provenance() -> None:
    assert _route_is_replay_eligible(
        route_confidence=0.95,
        route_provenance=["corpus_metadata", "lexical"],
        minimum_confidence=0.80,
    )
    assert not _route_is_replay_eligible(
        route_confidence=0.95,
        route_provenance=["corpus_metadata_unverified"],
        minimum_confidence=0.80,
    )
    assert not _route_is_replay_eligible(
        route_confidence=0.79,
        route_provenance=["corpus_metadata", "lexical"],
        minimum_confidence=0.80,
    )


def test_exact_replay_route_gate_requires_lexical_provenance() -> None:
    orchestrator = Orchestrator({})
    with tempfile.TemporaryDirectory(prefix="statebus-replay-gate-") as tmpdir:
        root = Path(tmpdir)
        ctx = Orchestrator.create_context(
            mode="protocol",
            task_id="replay-gate-exact",
            task_group="replay_route_diag",
            task_theme="executor_metadata_only",
            state_root=root / "state",
            memory_db_path=root / "memory.sqlite3",
            embedder=DeterministicEmbeddingProvider(),
        )
        exact_ok_ref = ctx.put_replay_eligibility_state(
            state_id="exact-ok",
            replay_eligibility_bundle={
                "schema": "statebus.replay_eligibility_bundle.v1",
                "query": "investigate an unclear incident",
                "route": "db_pool_saturation",
                "route_source": "hint_consensus",
                "route_confidence": 0.95,
                "route_provenance": ["corpus_metadata", "lexical"],
                "retrieved_doc_ids": [
                    "exec-metadata-only-anchor",
                    "exec-metadata-only-followup",
                ],
                "feature_fresh_evidence_sha256": "seeded-provenance-evidence",
            },
        )
        exact_bad_ref = ctx.put_replay_eligibility_state(
            state_id="exact-bad",
            replay_eligibility_bundle={
                "schema": "statebus.replay_eligibility_bundle.v1",
                "query": "investigate an unclear incident",
                "route": "db_pool_saturation",
                "route_source": "metadata_only_abstain",
                "route_confidence": 0.95,
                "route_provenance": ["corpus_metadata_unverified"],
                "retrieved_doc_ids": [
                    "exec-metadata-only-anchor",
                    "exec-metadata-only-followup",
                ],
                "feature_fresh_evidence_sha256": "seeded-provenance-evidence",
            },
        )
        hit = MemoryHit(
            memory_id="mem-provenance-exact-anchor",
            confidence=0.95,
            task_theme="executor_metadata_only",
            reusable_steps=["retrieve", "execute"],
            evidence_state_refs=[exact_ok_ref],
            metadata={
                "feature_route": "db_pool_saturation",
                "retrieved_doc_ids": [
                    "exec-metadata-only-anchor",
                    "exec-metadata-only-followup",
                ],
                "feature_query": "investigate an unclear incident",
                "feature_route_confidence": 0.95,
                "feature_route_provenance": ["corpus_metadata_unverified"],
                "feature_fresh_evidence_sha256": "seeded-provenance-evidence",
            },
        )
        assert orchestrator._matches_skip_retrieve_execute(
            hit=hit,
            task_theme="executor_metadata_only",
            current_query="investigate an unclear incident",
            ctx=ctx,
        )
        hit.evidence_state_refs = [exact_bad_ref]
        hit.metadata["feature_route_provenance"] = ["corpus_metadata", "lexical"]
        assert not orchestrator._matches_skip_retrieve_execute(
            hit=hit,
            task_theme="executor_metadata_only",
            current_query="investigate an unclear incident",
            ctx=ctx,
        )


def test_validated_replay_route_gate_requires_lexical_provenance_on_both_sides() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-validated-gate-") as tmpdir:
        root = Path(tmpdir)
        ctx = Orchestrator.create_context(
            mode="protocol",
            task_id="replay-gate-validated",
            task_group="replay_route_diag",
            task_theme="executor_metadata_only",
            state_root=root / "state",
            memory_db_path=root / "memory.sqlite3",
            embedder=DeterministicEmbeddingProvider(),
        )
        stored_ok_ref = ctx.put_replay_eligibility_state(
            state_id="stored-ok",
            replay_eligibility_bundle={
                "schema": "statebus.replay_eligibility_bundle.v1",
                "query": "investigate an unclear incident",
                "route": "db_pool_saturation",
                "route_source": "hint_consensus",
                "route_confidence": 0.95,
                "route_provenance": ["corpus_metadata", "lexical"],
                "retrieved_doc_ids": [
                    "exec-metadata-only-anchor",
                    "exec-metadata-only-followup",
                ],
                "feature_fresh_evidence_sha256": "seeded-provenance-evidence",
            },
        )
        stored_bad_ref = ctx.put_replay_eligibility_state(
            state_id="stored-bad",
            replay_eligibility_bundle={
                "schema": "statebus.replay_eligibility_bundle.v1",
                "query": "investigate an unclear incident",
                "route": "db_pool_saturation",
                "route_source": "metadata_only_abstain",
                "route_confidence": 0.95,
                "route_provenance": ["corpus_metadata_unverified"],
                "retrieved_doc_ids": [
                    "exec-metadata-only-anchor",
                    "exec-metadata-only-followup",
                ],
                "feature_fresh_evidence_sha256": "seeded-provenance-evidence",
            },
        )
        fresh_ok_ref = ctx.put_replay_eligibility_state(
            state_id="fresh-ok",
            replay_eligibility_bundle={
                "schema": "statebus.replay_eligibility_bundle.v1",
                "query": "investigate an unclear incident",
                "route": "db_pool_saturation",
                "route_source": "hint_consensus",
                "route_confidence": 0.95,
                "route_provenance": ["corpus_metadata", "lexical"],
                "retrieved_doc_ids": [
                    "exec-metadata-only-anchor",
                    "exec-metadata-only-followup",
                ],
                "feature_fresh_evidence_sha256": "seeded-provenance-evidence",
            },
        )
        fresh_bad_ref = ctx.put_replay_eligibility_state(
            state_id="fresh-bad",
            replay_eligibility_bundle={
                "schema": "statebus.replay_eligibility_bundle.v1",
                "query": "investigate an unclear incident",
                "route": "db_pool_saturation",
                "route_source": "metadata_only_abstain",
                "route_confidence": 0.95,
                "route_provenance": ["corpus_metadata_unverified"],
                "retrieved_doc_ids": [
                    "exec-metadata-only-anchor",
                    "exec-metadata-only-followup",
                ],
                "feature_fresh_evidence_sha256": "seeded-provenance-evidence",
            },
        )
        hit = MemoryHit(
            memory_id="mem-provenance-validated-anchor",
            confidence=0.95,
            reusable_steps=["execute"],
            evidence_state_refs=[stored_ok_ref],
            metadata={
                "feature_route": "db_pool_saturation",
                "retrieved_doc_ids": [
                    "exec-metadata-only-anchor",
                    "exec-metadata-only-followup",
                ],
                "feature_query": "investigate an unclear incident",
                "feature_route_confidence": 0.95,
                "feature_route_provenance": ["corpus_metadata_unverified"],
                "feature_fresh_evidence_sha256": "seeded-provenance-evidence",
            },
        )
        retrieve_result = StepResult(
            step_id="retrieve",
            success=True,
            output_state_refs=[fresh_ok_ref],
            payload={
                "feature_route": "db_pool_saturation",
                "retrieved_doc_ids": [
                    "exec-metadata-only-anchor",
                    "exec-metadata-only-followup",
                ],
                "feature_route_confidence": 0.95,
                "feature_route_provenance": ["corpus_metadata_unverified"],
                "feature_fresh_evidence_sha256": "seeded-provenance-evidence",
            },
        )
        assert Orchestrator._matches_skip_execute(
            hit=hit,
            retrieve_result=retrieve_result,
            current_query="investigate an unclear incident",
            ctx=ctx,
        )
        retrieve_result.output_state_refs = [fresh_bad_ref]
        retrieve_result.payload["feature_route_provenance"] = ["corpus_metadata", "lexical"]
        assert not Orchestrator._matches_skip_execute(
            hit=hit,
            retrieve_result=retrieve_result,
            current_query="investigate an unclear incident",
            ctx=ctx,
        )
        retrieve_result.output_state_refs = [fresh_ok_ref]
        hit.evidence_state_refs = [stored_bad_ref]
        assert not Orchestrator._matches_skip_execute(
            hit=hit,
            retrieve_result=retrieve_result,
            current_query="investigate an unclear incident",
            ctx=ctx,
        )


def test_feature_bundle_abstains_on_conflicting_hint_with_thin_lexical_override() -> None:
    corpus_docs = load_corpus_docs()
    hints = extract_corpus_feature_hints([corpus_docs["session-auth-anchor"]])
    payload = build_feature_bundle(
        query="aggressive backoff window login issue",
        evidence_text="The current note remains vague and does not confirm a stable route.",
        tags=["auth", "session"],
        reuse_signature="repo_local_auth_session_drift:auth|session",
        reused_memory=False,
        retrieved_hints=hints,
    )
    assert payload["route"] == "generic_triage"
    assert payload["tool_name"] == "tool.collect_more_evidence"
    assert payload["route_source"] == "low_confidence_abstain"
    assert payload["route_confidence"] == 0.0
    assert payload["route_provenance"] == ["lexical_thin_support", "corpus_metadata_conflict"]
    assert payload["hint_doc_ids"] == ["session-auth-anchor"]
    assert payload["hint_route"] == "auth_session_drift"
    assert payload["hint_tool_name"] == "tool.auth_session_repair"
    assert payload["tool_candidates"][0]["tool_name"] == "tool.collect_more_evidence"
    assert payload["tool_candidates"][0]["source"] == "low_confidence_abstain"
    candidate_names = [candidate["tool_name"] for candidate in payload["tool_candidates"]]
    assert "tool.auth_session_repair" in candidate_names
    assert "tool.auth_rate_limit_triage" in candidate_names


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
                task_set_path="internal_regression",
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


def test_execute_playbook_step_prefers_tool_candidate_state_when_present() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-tool-candidate-state-") as tmpdir:
        statepool = StatePool(Path(tmpdir), config=StatePoolConfig.from_env())
        evidence_ref = statepool.put_text(
            state_id="case-1-evidence",
            kind="DENSE_EVIDENCE",
            text=(
                "Release-17 orders latency shows database pool contention and the slow orders query. "
                "Treat this as a DB pool saturation incident."
            ),
        )
        feature_ref = statepool.put_bytes(
            state_id="case-1-features",
            kind="FEATURE_BUNDLE",
            payload=msgpack.packb(
                {
                    "schema": "statebus.feature_bundle.v1",
                    "route": "generic_triage",
                    "tool_name": "tool.collect_more_evidence",
                    "tool_candidates": [
                        {
                            "tool_name": "tool.collect_more_evidence",
                            "route": "generic_triage",
                            "score": 0,
                            "source": "fallback",
                        }
                    ],
                },
                use_bin_type=True,
            ),
            metadata={"schema": "statebus.feature_bundle.v1", "encoding": "msgpack"},
        )
        tool_candidate_ref = statepool.put_bytes(
            state_id="case-1-tool-candidates",
            kind="TOOL_CANDIDATE_SET",
            payload=msgpack.packb(
                {
                    "schema": "statebus.tool_candidate_set.v1",
                    "route": "db_pool_saturation",
                    "tool_name": "tool.db_pool_triage",
                    "route_source": "hint_consensus",
                    "route_confidence": 0.92,
                    "route_provenance": ["corpus_metadata", "lexical"],
                    "matched_signals": ["slow orders query", "connection pool"],
                    "matched_tags": ["database", "orders"],
                    "match_score": 18,
                    "tool_candidates": [
                        {
                            "tool_name": "tool.db_pool_triage",
                            "route": "db_pool_saturation",
                            "score": 18,
                            "source": "hint_consensus",
                        }
                    ],
                },
                use_bin_type=True,
            ),
            metadata={"schema": "statebus.tool_candidate_set.v1", "encoding": "msgpack"},
        )
        result = execute_playbook_step(
            task_id="case-1",
            task_theme="repo_local_latency_triage",
            step=PlanStep(
                step_id="execute",
                owner_agent="executor",
                action="EXECUTE_PLAYBOOK",
                input_state_refs=[evidence_ref.state_id, feature_ref.state_id, tool_candidate_ref.state_id],
                params={},
                depends_on=["retrieve"],
            ),
            statepool=statepool,
            input_state_refs=[evidence_ref, feature_ref, tool_candidate_ref],
            transfer_strategy="state_ref",
        )
    assert result.payload["tool_name"] == "tool.db_pool_triage"
    assert result.payload["route"] == "db_pool_saturation"
    assert result.output_state_refs[0].metadata["source_tool_candidates"] == tool_candidate_ref.state_id


def test_invalid_handoff_state_is_rejected_before_executor_runs() -> None:
    @dataclass
    class ExplodingExecutor(BaseAgent):
        called: bool = False

        async def execute_step(self, step: PlanStep, ctx: object) -> StepResult:
            self.called = True
            raise AssertionError("executor should not run when handoff validation fails")

    with tempfile.TemporaryDirectory(prefix="statebus-invalid-handoff-") as tmpdir:
        agents = build_sample_agents_with_executor(llm_client=DeterministicLLMClient())
        exploding = ExplodingExecutor(
            agent_id="executor",
            capability=agents["executor"].capability,
        )
        agents["executor"] = exploding
        orchestrator = Orchestrator(agents)
        root = Path(tmpdir)
        ctx = Orchestrator.create_context(
            mode="protocol",
            task_id="invalid-handoff-001",
            task_group="contract_chain",
            task_theme="repo_local_cache_triage",
            state_root=root / "state",
            memory_db_path=root / "memory.sqlite3",
            embedder=DeterministicEmbeddingProvider(),
        )
        evidence_ref = ctx.put_text_state(
            state_id="invalid-handoff-001-retrieve-evidence",
            kind="DENSE_EVIDENCE",
            text="Inventory invalidation evidence for a replayable cache incident.",
        )
        bad_tool_candidate_ref = ctx.put_bytes_state(
            state_id="invalid-handoff-001-retrieve-tool-candidates",
            kind="TOOL_CANDIDATE_SET",
            payload=msgpack.packb(
                {
                    "schema": "statebus.not_tool_candidate.v1",
                    "tool_candidates": [],
                },
                use_bin_type=True,
            ),
            metadata={
                "encoding": "msgpack",
                "schema": "statebus.not_tool_candidate.v1",
                "query": "inventory invalidation",
                "feature_route": "cache_invalidation",
                "feature_route_source": "hint_consensus",
                "feature_route_confidence": 0.91,
            },
        )
        ctx.results["retrieve"] = StepResult(
            step_id="retrieve",
            success=True,
            output_state_refs=[evidence_ref, bad_tool_candidate_ref],
            payload={"query": "inventory invalidation"},
        )
        plan = Plan(
            task_id="invalid-handoff-001",
            goal="Validate that executor input contracts are enforced before execution.",
            steps=[
                PlanStep(
                    step_id="retrieve",
                    owner_agent="retriever",
                    action="RETRIEVE_EVIDENCE",
                    input_state_refs=[],
                    params={"query": "inventory invalidation"},
                    depends_on=[],
                ),
                PlanStep(
                    step_id="execute",
                    owner_agent="executor",
                    action="EXECUTE_PLAYBOOK",
                    input_state_refs=[],
                    params={},
                    depends_on=["retrieve"],
                ),
            ],
        )
        with pytest.raises(SchemaValidationError, match="registered contract|schema mismatch"):
            asyncio.run(orchestrator.run_plan(plan, ctx))
        assert exploding.called is False


def test_state_transfer_carrier_pack_runs_mode_split_handoff_pairs() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-transfer-lane-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="state_transfer_carrier",
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
    transfer_tasks = list(load_task_set_bundle("state_transfer_carrier").tasks)
    assert transfer_tasks
    transfer_ids = {task.task_id for task in transfer_tasks if task.benchmark_lane == "state_transfer"}
    assert text_tasks == {}
    for task in transfer_tasks:
        if task.benchmark_lane != "state_transfer":
            continue
        assert task.allowed_modes == ("protocol",)
        assert task.task_id in protocol_tasks
        proto_task = protocol_tasks[task.task_id]
        assert proto_task["benchmark_lane"] == "state_transfer"
        assert proto_task["transfer_strategy"] in {"text_packet_minimal", "state_packet_minimal"}
    assert transfer_ids == set(protocol_tasks)
    # Verify the benchmark ran without failures
    summary = result["summary"]
    assert int(summary["text"]["failure_count"]) == 0
    assert int(summary["protocol"]["failure_count"]) == 0


def test_benchmark_supports_shared_memory_statepool_backend() -> None:
    try:
        from multiprocessing import shared_memory as _shm
        _shm.SharedMemory(name="statebus_test_probe", create=True, size=64).unlink()
    except Exception:
        pytest.skip("shared_memory not available")


def test_state_transfer_text_brief_preserves_retriever_executor_snapshot() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-transfer-brief-fidelity-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="state_transfer_authenticity",
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        tasks = {task["task_id"]: task for task in result["mode_runs"]["protocol"][0]["tasks"]}
        for task_id in (
            "transfer-cache-text-001",
            "transfer-latency-text-001",
            "transfer-session-text-001",
        ):
            task = tasks[task_id]
            retrieve_payload = task["results"]["retrieve"]["payload"]
            execute_payload = task["results"]["execute"]["payload"]
            brief_state_id = retrieve_payload["transfer_brief_state_id"]
            assert brief_state_id
            brief_ref = task["state_refs"][brief_state_id]
            brief_text = Path(brief_ref["handle"]).read_text(encoding="utf-8")
            assert "Suggested tool:" in brief_text
            assert "Route confidence:" in brief_text
            assert "Tool candidates:" in brief_text
            evidence_ref = next(
                ref for ref in task["state_refs"].values() if ref["kind"] == "DENSE_EVIDENCE"
            )
            evidence_text = Path(evidence_ref["handle"]).read_text(encoding="utf-8")
            rebuilt = _feature_bundle_from_transfer_brief(
                query_text=retrieve_payload["query"],
                evidence_text=evidence_text,
                brief_text=brief_text,
                registry=default_tool_registry(),
            )
            assert rebuilt["route"] == retrieve_payload["feature_route"]
            assert rebuilt["route_source"] == retrieve_payload["feature_route_source"]
            assert rebuilt["route_confidence"] == retrieve_payload["feature_route_confidence"]
            assert rebuilt["route_provenance"] == retrieve_payload["feature_route_provenance"]
            assert select_tool_name(rebuilt) == execute_payload["tool_name"]
            assert rebuilt["tool_candidates"][0]["tool_name"] == execute_payload["tool_name"]


def test_natural_handoff_removes_route_and_tool_side_channels() -> None:
    forbidden_tokens = (
        "Route:",
        "Tool:",
        "route_source",
        "tool_candidates",
        "matched_signals",
        "matched_tags",
    )
    with tempfile.TemporaryDirectory(prefix="statebus-natural-support-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="state_transfer_natural_support",
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        tasks = {task["task_id"]: task for task in result["mode_runs"]["protocol"][0]["tasks"]}
        for task_id in (
            "transfer-cache-natural-001",
            "transfer-latency-natural-001",
            "transfer-session-natural-001",
        ):
            task = tasks[task_id]
            retrieve_payload = task["results"]["retrieve"]["payload"]
            execute_payload = task["results"]["execute"]["payload"]
            brief_state_id = retrieve_payload["transfer_brief_state_id"]
            assert brief_state_id
            brief_ref = task["state_refs"][brief_state_id]
            assert set(brief_ref["metadata"]) == {"query", "retrieved_doc_ids", "transfer_strategy"}
            brief_text = Path(brief_ref["handle"]).read_bytes().decode("utf-8")
            for token in forbidden_tokens:
                assert token not in brief_text
            evidence_ref = next(ref for ref in task["state_refs"].values() if ref["kind"] == "DENSE_EVIDENCE")
            evidence_text = Path(evidence_ref["handle"]).read_text(encoding="utf-8")
            rebuilt = build_feature_bundle(
                query=retrieve_payload["query"],
                evidence_text=f"{evidence_text}\n{brief_text}",
                tags=[],
                reuse_signature="natural_handoff_transfer",
                reused_memory=False,
                registry=default_tool_registry(),
            )
            assert select_tool_name(rebuilt) == execute_payload["tool_name"]
            assert rebuilt["route"] == execute_payload["route"]


def test_state_transfer_pure_text_pack_runs_natural_text_against_state_ref() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-pure-text-formal-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="state_transfer_pure_text",
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    protocol_tasks = {
        task["task_id"]: task for task in result["mode_runs"]["protocol"][0]["tasks"]
    }
    transfer_tasks = list(load_task_set_bundle("state_transfer_pure_text").tasks)
    assert len(transfer_tasks) == 6
    for task in transfer_tasks:
        assert task.allowed_modes == ("protocol",)
        assert task.task_id in protocol_tasks
        observed = protocol_tasks[task.task_id]
        assert observed["benchmark_lane"] == "state_transfer"
        assert observed["transfer_strategy"] in {"natural_handoff_text", "state_ref"}
    assert {
        task.transfer_strategy for task in transfer_tasks
    } == {"natural_handoff_text", "state_ref"}
    assert int(result["summary"]["protocol"]["failure_count"]) == 0


def test_communication_lane_keeps_memory_disabled_in_both_modes() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-communication-lane-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="communication",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    for mode in ("text", "protocol"):
        tasks = {task["task_id"]: task for task in result["mode_runs"][mode][0]["tasks"]}
        for task_id in ("communication-cache-001", "communication-cache-002"):
            task = tasks[task_id]
            assert task["benchmark_lane"] == "communication"
            assert task["runtime_reuse_contract"] == "reuse_disabled"
            assert task["reuse"]["mode"] == "none"
            assert task["metrics"]["memory_query_count"] == 0
            assert task["metrics"]["memory_hit_rate"] == 0.0


def test_memory_lane_separates_memory_policies() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-memory-lane-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="memory",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    assert result["mode_runs"]["text"][0]["tasks"] == []
    tasks = {task["task_id"]: task for task in result["mode_runs"]["protocol"][0]["tasks"]}
    memory_off = tasks["memory-cache-001"]
    assist_only = tasks["memory-cache-002"]
    replay_enabled = tasks["memory-cache-003"]
    assert memory_off["benchmark_lane"] == "memory"
    assert memory_off["runtime_reuse_contract"] == "reuse_disabled"
    assert memory_off["reuse"]["mode"] == "none"
    assert memory_off["metrics"]["memory_query_count"] == 0
    assert assist_only["runtime_reuse_contract"] == "assist_allowed"
    assert assist_only["reuse"]["mode"] == "assist"
    assert assist_only["results"]["retrieve"]["skipped"] is False
    assert assist_only["results"]["execute"]["skipped"] is False
    assert replay_enabled["runtime_reuse_contract"] == "validated_replay"
    assert replay_enabled["reuse"]["mode"] == "skip_execute"
    assert replay_enabled["results"]["retrieve"]["skipped"] is False
    assert replay_enabled["results"]["execute"]["skipped"] is True


def test_pack_specific_reports_do_not_mix_claim_surfaces() -> None:
    cases = {
        "memory": ("StateBus Benchmark Report", ()),
        "communication": ("StateBus Benchmark Report", ()),
        "state_transfer_pure_text": ("Protocol-Only Pure-Text Versus Typed-State", ("Support note:",)),
    }
    for task_set_path, (present, absent) in cases.items():
        with tempfile.TemporaryDirectory(prefix="statebus-pack-report-") as tmpdir:
            out_dir = Path(tmpdir)
            result = asyncio.run(
                run_benchmark(
                    task_set_path=task_set_path,
                    repeat=1,
                    out_dir=out_dir,
                    embedder=DeterministicEmbeddingProvider(),
                    llm_client=DeterministicLLMClient(),
                )
            )
            assert result["manifest"]["task_pack_type"] == load_task_set_bundle(task_set_path).metadata.pack_type
            report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
            assert present in report_text
            for token in absent:
                assert token not in report_text


def test_benchmark_supports_shared_memory_statepool_backend() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-shm-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="communication",
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
            cwd=REPO_ROOT,
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


def test_executor_diagnostic_task_set_covers_abstain_boundaries() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-executor-diag-") as tmpdir:
        out_dir = Path(tmpdir)
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/executor_diagnostic_tasks.yaml",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "Executor Feature Observability" in report_text
        assert "| text | low_confidence_abstain | 3 | 6 |" in report_text
        assert "| protocol | metadata_only_abstain | 1 | 6 |" in report_text
        assert "| text | 1 | 1 | 1 | 1 | 1 | 1 |" in report_text
    expected = {
        "exec-low-confidence-001": ("low_confidence_abstain", "tool.collect_more_evidence", 0.0),
        "exec-thin-support-001": ("low_confidence_abstain", "tool.collect_more_evidence", 0.0),
        "exec-conflict-thin-override-001": ("low_confidence_abstain", "tool.collect_more_evidence", 0.0),
        "exec-metadata-only-001": ("metadata_only_abstain", "tool.collect_more_evidence", 0.0),
        "exec-ambiguous-001": ("ambiguous_candidates_abstain", "tool.collect_more_evidence", 0.0),
        "exec-clear-worker-001": ("hint_consensus", "tool.worker_queue_triage", 0.95),
    }
    for mode in ("text", "protocol"):
        tasks = {task["task_id"]: task for task in result["mode_runs"][mode][0]["tasks"]}
        assert set(tasks) == set(expected)
        for task_id, (route_source, tool_name, confidence) in expected.items():
            task = tasks[task_id]
            retrieve_payload = task["results"]["retrieve"]["payload"]
            execute_payload = task["results"]["execute"]["payload"]
            observability = task["results"]["retrieve"]["feature_observability"]
            assert task["corpus_path"].endswith("tasks/executor_diagnostic_corpus.yaml")
            assert retrieve_payload["feature_route_source"] == route_source
            assert "matched_signals" in observability
            assert "matched_tags" in observability
            assert "match_score" in observability
            assert "tool_candidates" in observability
            assert execute_payload["tool_name"] == tool_name
            assert retrieve_payload["feature_route_confidence"] == confidence
            artifact_misfire = task["artifact_misfire"]
            assert artifact_misfire["fields"]["route_source"]["matched"] is True
            assert artifact_misfire["fields"]["tool_name"]["matched"] is True
            assert artifact_misfire["fields"]["route"]["enabled"] is False
            assert artifact_misfire["fields"]["top_doc_id"]["enabled"] is False


def test_retrieval_replay_diagnostic_task_set_covers_p1_boundaries() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-retrieval-replay-diag-") as tmpdir:
        out_dir = Path(tmpdir)
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/retrieval_replay_diagnostic_tasks.yaml",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "fresh_retrieval" in report_text
        assert "step_skipping" in report_text
        assert "replay_enabled" in report_text
    expected_tasks = {
        "diag-retrieval-out-of-hint-001",
        "diag-replay-no-doc-pref-001",
        "diag-replay-validated-001",
        "diag-replay-validated-docset-drift-001",
        "diag-replay-no-doc-pref-002",
        "diag-replay-tag-drift-001",
        "diag-replay-query-drift-001",
        "diag-replay-theme-drift-001",
    }
    for mode in ("text", "protocol"):
        tasks = {task["task_id"]: task for task in result["mode_runs"][mode][0]["tasks"]}
        assert set(tasks) == expected_tasks

        retrieval_diag = tasks["diag-retrieval-out-of-hint-001"]
        assert retrieval_diag["reuse"]["mode"] == "none"
        assert retrieval_diag["results"]["retrieve"]["skipped"] is False
        assert retrieval_diag["results"]["retrieve"]["payload"]["retrieved_doc_ids"][0] == "cache-replica-false"
        assert retrieval_diag["results"]["retrieve"]["payload"]["feature_route"] == "cache_replica_stale_read"
        assert retrieval_diag["results"]["execute"]["payload"]["tool_name"] == "tool.replica_stale_read_triage"
        assert retrieval_diag["artifact_misfire"]["all_matched"] is True

        validated_diag = tasks["diag-replay-validated-001"]
        assert validated_diag["reuse"]["mode"] == "skip_execute"
        assert validated_diag["results"]["retrieve"]["skipped"] is False
        assert validated_diag["results"]["execute"]["skipped"] is True
        assert validated_diag["artifact_misfire"]["fields"]["route"]["matched"] is True

        validated_docset_drift_diag = tasks["diag-replay-validated-docset-drift-001"]
        assert validated_docset_drift_diag["reuse"]["mode"] == "none"
        assert validated_docset_drift_diag["results"]["retrieve"]["skipped"] is False
        assert validated_docset_drift_diag["results"]["execute"]["skipped"] is False
        assert sorted(validated_docset_drift_diag["results"]["retrieve"]["payload"]["retrieved_doc_ids"]) == [
            "cache-invalid-anchor",
            "cache-invalid-followup",
        ]
        assert validated_docset_drift_diag["reuse_validation"]["matched_expectation"] is True
        assert validated_docset_drift_diag["artifact_misfire"]["fields"]["route"]["matched"] is True

        exact_diag = tasks["diag-replay-no-doc-pref-002"]
        assert exact_diag["reuse"]["mode"] == "skip_retrieve_execute"
        assert exact_diag["results"]["retrieve"]["skipped"] is True
        assert exact_diag["results"]["execute"]["skipped"] is True
        assert sorted(exact_diag["results"]["retrieve"]["payload"]["retrieved_doc_ids"]) == [
            "cache-invalid-anchor",
            "cache-invalid-replay",
        ]
        assert "preferred_corpus_doc_ids" not in exact_diag["results"]["retrieve"]["payload"]
        assert "candidate_corpus_doc_ids" not in exact_diag["results"]["retrieve"]["payload"]
        assert exact_diag["artifact_misfire"]["fields"]["route"]["matched"] is True

        tag_drift_diag = tasks["diag-replay-tag-drift-001"]
        assert tag_drift_diag["reuse"]["mode"] == "skip_retrieve_execute"
        assert tag_drift_diag["results"]["retrieve"]["skipped"] is True
        assert tag_drift_diag["results"]["execute"]["skipped"] is True
        assert sorted(tag_drift_diag["results"]["retrieve"]["payload"]["retrieved_doc_ids"]) == [
            "cache-invalid-anchor",
            "cache-invalid-replay",
        ]
        assert tag_drift_diag["task_theme"] == "repo_local_cache_staleness"
        assert tag_drift_diag["reuse_validation"]["matched_expectation"] is True
        assert tag_drift_diag["artifact_misfire"]["fields"]["route"]["matched"] is True

        drift_diag = tasks["diag-replay-query-drift-001"]
        assert drift_diag["reuse"]["mode"] == "none"
        assert drift_diag["results"]["retrieve"]["skipped"] is False
        assert drift_diag["results"]["execute"]["skipped"] is False

        theme_drift_diag = tasks["diag-replay-theme-drift-001"]
        assert theme_drift_diag["task_theme"] == "repo_local_cache_staleness_variant"
        assert theme_drift_diag["reuse"]["mode"] == "none"
        assert theme_drift_diag["results"]["retrieve"]["skipped"] is False
        assert theme_drift_diag["results"]["execute"]["skipped"] is False
        assert theme_drift_diag["reuse_validation"]["matched_expectation"] is True


def test_retrieval_hint_diagnostic_task_set_covers_weakened_hint_boundaries() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-retrieval-hint-diag-") as tmpdir:
        out_dir = Path(tmpdir)
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/retrieval_hint_diagnostic_tasks.yaml",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "fresh_retrieval" in report_text
        assert "internal_regression" in report_text
    expected_tasks = {
        "diag-retrieval-no-tags-001",
        "diag-retrieval-misleading-tags-001",
        "diag-retrieval-invalidation-control-001",
        "diag-retrieval-latency-no-tags-001",
        "diag-retrieval-latency-misleading-tags-001",
        "diag-retrieval-latency-db-control-001",
        "diag-retrieval-session-no-tags-001",
        "diag-retrieval-session-misleading-tags-001",
        "diag-retrieval-session-drift-control-001",
    }
    for mode in ("text", "protocol"):
        tasks = {task["task_id"]: task for task in result["mode_runs"][mode][0]["tasks"]}
        assert set(tasks) == expected_tasks

        no_tags_diag = tasks["diag-retrieval-no-tags-001"]
        assert no_tags_diag["reuse"]["mode"] == "none"
        assert no_tags_diag["results"]["retrieve"]["skipped"] is False
        assert no_tags_diag["results"]["retrieve"]["payload"]["retrieved_doc_ids"][0] == "cache-replica-false"
        assert no_tags_diag["results"]["retrieve"]["payload"]["feature_route"] == "cache_replica_stale_read"
        assert no_tags_diag["results"]["execute"]["payload"]["tool_name"] == "tool.replica_stale_read_triage"
        assert no_tags_diag["artifact_misfire"]["all_matched"] is True

        misleading_tags_diag = tasks["diag-retrieval-misleading-tags-001"]
        assert misleading_tags_diag["reuse"]["mode"] == "none"
        assert misleading_tags_diag["results"]["retrieve"]["skipped"] is False
        assert misleading_tags_diag["results"]["retrieve"]["payload"]["retrieved_doc_ids"][0] == "cache-replica-false"
        assert misleading_tags_diag["results"]["retrieve"]["payload"]["feature_route"] == "cache_replica_stale_read"
        assert misleading_tags_diag["results"]["execute"]["payload"]["tool_name"] == "tool.replica_stale_read_triage"
        assert misleading_tags_diag["artifact_misfire"]["all_matched"] is True

        invalidation_control = tasks["diag-retrieval-invalidation-control-001"]
        assert invalidation_control["reuse"]["mode"] == "none"
        assert invalidation_control["results"]["retrieve"]["skipped"] is False
        assert invalidation_control["results"]["retrieve"]["payload"]["retrieved_doc_ids"][0] == "cache-invalid-anchor"
        assert invalidation_control["results"]["retrieve"]["payload"]["feature_route"] == "cache_invalidation"
        assert invalidation_control["results"]["execute"]["payload"]["tool_name"] == "tool.cache_invalidation_playbook"
        assert invalidation_control["artifact_misfire"]["all_matched"] is True

        latency_no_tags_diag = tasks["diag-retrieval-latency-no-tags-001"]
        assert latency_no_tags_diag["reuse"]["mode"] == "none"
        assert latency_no_tags_diag["results"]["retrieve"]["skipped"] is False
        assert latency_no_tags_diag["results"]["retrieve"]["payload"]["retrieved_doc_ids"][0] == "latency-worker-false"
        assert latency_no_tags_diag["results"]["retrieve"]["payload"]["feature_route"] == "worker_queue_starvation"
        assert latency_no_tags_diag["results"]["execute"]["payload"]["tool_name"] == "tool.worker_queue_triage"
        assert latency_no_tags_diag["artifact_misfire"]["all_matched"] is True

        latency_misleading_tags_diag = tasks["diag-retrieval-latency-misleading-tags-001"]
        assert latency_misleading_tags_diag["reuse"]["mode"] == "none"
        assert latency_misleading_tags_diag["results"]["retrieve"]["skipped"] is False
        assert latency_misleading_tags_diag["results"]["retrieve"]["payload"]["retrieved_doc_ids"][0] == "latency-worker-false"
        assert latency_misleading_tags_diag["results"]["retrieve"]["payload"]["feature_route"] == "worker_queue_starvation"
        assert latency_misleading_tags_diag["results"]["execute"]["payload"]["tool_name"] == "tool.worker_queue_triage"
        assert latency_misleading_tags_diag["artifact_misfire"]["all_matched"] is True

        latency_db_control = tasks["diag-retrieval-latency-db-control-001"]
        assert latency_db_control["reuse"]["mode"] == "none"
        assert latency_db_control["results"]["retrieve"]["skipped"] is False
        assert latency_db_control["results"]["retrieve"]["payload"]["retrieved_doc_ids"][0] == "latency-db-anchor"
        assert latency_db_control["results"]["retrieve"]["payload"]["feature_route"] == "db_pool_saturation"
        assert latency_db_control["results"]["execute"]["payload"]["tool_name"] == "tool.db_pool_triage"
        assert latency_db_control["artifact_misfire"]["all_matched"] is True

        session_no_tags_diag = tasks["diag-retrieval-session-no-tags-001"]
        assert session_no_tags_diag["reuse"]["mode"] == "none"
        assert session_no_tags_diag["results"]["retrieve"]["skipped"] is False
        assert session_no_tags_diag["results"]["retrieve"]["payload"]["retrieved_doc_ids"][0] == "session-rate-limit-false"
        assert session_no_tags_diag["results"]["retrieve"]["payload"]["feature_route"] == "auth_rate_limit"
        assert session_no_tags_diag["results"]["execute"]["payload"]["tool_name"] == "tool.auth_rate_limit_triage"
        assert session_no_tags_diag["artifact_misfire"]["all_matched"] is True

        session_misleading_tags_diag = tasks["diag-retrieval-session-misleading-tags-001"]
        assert session_misleading_tags_diag["reuse"]["mode"] == "none"
        assert session_misleading_tags_diag["results"]["retrieve"]["skipped"] is False
        assert session_misleading_tags_diag["results"]["retrieve"]["payload"]["retrieved_doc_ids"][0] == "session-rate-limit-false"
        assert session_misleading_tags_diag["results"]["retrieve"]["payload"]["feature_route"] == "auth_rate_limit"
        assert session_misleading_tags_diag["results"]["execute"]["payload"]["tool_name"] == "tool.auth_rate_limit_triage"
        assert session_misleading_tags_diag["artifact_misfire"]["all_matched"] is True

        session_drift_control = tasks["diag-retrieval-session-drift-control-001"]
        assert session_drift_control["reuse"]["mode"] == "none"
        assert session_drift_control["results"]["retrieve"]["skipped"] is False
        assert session_drift_control["results"]["retrieve"]["payload"]["retrieved_doc_ids"][0] == "session-auth-anchor"
        assert session_drift_control["results"]["retrieve"]["payload"]["feature_route"] == "auth_session_drift"
        assert session_drift_control["results"]["execute"]["payload"]["tool_name"] == "tool.auth_session_repair"
        assert session_drift_control["artifact_misfire"]["all_matched"] is True


def test_retrieval_context_diagnostic_task_set_covers_wrong_family_context_boundaries() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-retrieval-context-diag-") as tmpdir:
        out_dir = Path(tmpdir)
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/retrieval_context_diagnostic_tasks.yaml",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "fresh_retrieval" in report_text
        assert "internal_regression" in report_text
    expected_tasks = {
        "diag-retrieval-session-context-rate-limit-001",
        "diag-retrieval-session-context-drift-control-001",
        "diag-retrieval-latency-context-worker-001",
        "diag-retrieval-latency-context-db-control-001",
        "diag-retrieval-cache-context-replica-001",
        "diag-retrieval-cache-context-invalidation-control-001",
    }
    for mode in ("text", "protocol"):
        tasks = {task["task_id"]: task for task in result["mode_runs"][mode][0]["tasks"]}
        assert set(tasks) == expected_tasks

        session_rate_limit = tasks["diag-retrieval-session-context-rate-limit-001"]
        assert session_rate_limit["reuse"]["mode"] == "none"
        assert session_rate_limit["results"]["retrieve"]["skipped"] is False
        assert session_rate_limit["results"]["retrieve"]["payload"]["retrieved_doc_ids"][0] == "session-rate-limit-false"
        assert session_rate_limit["results"]["retrieve"]["payload"]["feature_route"] == "auth_rate_limit"
        assert session_rate_limit["results"]["execute"]["payload"]["tool_name"] == "tool.auth_rate_limit_triage"
        assert session_rate_limit["task_group"] == "cache_chain"
        assert session_rate_limit["task_theme"] == "repo_local_cache_staleness"

        session_drift = tasks["diag-retrieval-session-context-drift-control-001"]
        assert session_drift["reuse"]["mode"] == "none"
        assert session_drift["results"]["retrieve"]["skipped"] is False
        assert session_drift["results"]["retrieve"]["payload"]["retrieved_doc_ids"][0] == "session-auth-anchor"
        assert session_drift["results"]["retrieve"]["payload"]["feature_route"] == "auth_session_drift"
        assert session_drift["results"]["execute"]["payload"]["tool_name"] == "tool.auth_session_repair"
        assert session_drift["task_group"] == "cache_chain"
        assert session_drift["task_theme"] == "repo_local_cache_staleness"

        latency_worker = tasks["diag-retrieval-latency-context-worker-001"]
        assert latency_worker["reuse"]["mode"] == "none"
        assert latency_worker["results"]["retrieve"]["skipped"] is False
        assert latency_worker["results"]["retrieve"]["payload"]["retrieved_doc_ids"][0] == "latency-worker-false"
        assert latency_worker["results"]["retrieve"]["payload"]["feature_route"] == "worker_queue_starvation"
        assert latency_worker["results"]["execute"]["payload"]["tool_name"] == "tool.worker_queue_triage"
        assert latency_worker["task_group"] == "session_chain"
        assert latency_worker["task_theme"] == "repo_local_auth_session_drift"

        latency_db = tasks["diag-retrieval-latency-context-db-control-001"]
        assert latency_db["reuse"]["mode"] == "none"
        assert latency_db["results"]["retrieve"]["skipped"] is False
        assert latency_db["results"]["retrieve"]["payload"]["retrieved_doc_ids"][0] == "latency-db-anchor"
        assert latency_db["results"]["retrieve"]["payload"]["feature_route"] == "db_pool_saturation"
        assert latency_db["results"]["execute"]["payload"]["tool_name"] == "tool.db_pool_triage"
        assert latency_db["task_group"] == "session_chain"
        assert latency_db["task_theme"] == "repo_local_auth_session_drift"

        cache_replica = tasks["diag-retrieval-cache-context-replica-001"]
        assert cache_replica["reuse"]["mode"] == "none"
        assert cache_replica["results"]["retrieve"]["skipped"] is False
        assert cache_replica["results"]["retrieve"]["payload"]["retrieved_doc_ids"][0] == "cache-replica-false"
        assert cache_replica["results"]["retrieve"]["payload"]["feature_route"] == "cache_replica_stale_read"
        assert cache_replica["results"]["execute"]["payload"]["tool_name"] == "tool.replica_stale_read_triage"
        assert cache_replica["task_group"] == "latency_chain"
        assert cache_replica["task_theme"] == "repo_local_latency_triage"

        cache_invalidation = tasks["diag-retrieval-cache-context-invalidation-control-001"]
        assert cache_invalidation["reuse"]["mode"] == "none"
        assert cache_invalidation["results"]["retrieve"]["skipped"] is False
        assert cache_invalidation["results"]["retrieve"]["payload"]["retrieved_doc_ids"][0] == "cache-invalid-anchor"
        assert cache_invalidation["results"]["retrieve"]["payload"]["feature_route"] == "cache_invalidation"
        assert cache_invalidation["results"]["execute"]["payload"]["tool_name"] == "tool.cache_invalidation_playbook"
        assert cache_invalidation["task_group"] == "latency_chain"
        assert cache_invalidation["task_theme"] == "repo_local_latency_triage"


def test_retrieval_mixed_docset_diagnostic_task_set_covers_widened_docset_boundaries() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-retrieval-mixed-docset-") as tmpdir:
        out_dir = Path(tmpdir)
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/retrieval_mixed_docset_diagnostic_tasks.yaml",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "internal_regression" in report_text
        assert "fresh_retrieval" in report_text
    expected_routes = {
        "diag-retrieval-mixed-latency-worker-001": ("worker_queue_starvation", "tool.worker_queue_triage"),
        "diag-retrieval-mixed-latency-db-control-001": ("db_pool_saturation", "tool.db_pool_triage"),
        "diag-retrieval-mixed-cache-replica-001": ("cache_replica_stale_read", "tool.replica_stale_read_triage"),
        "diag-retrieval-mixed-cache-invalidation-control-001": (
            "cache_invalidation",
            "tool.cache_invalidation_playbook",
        ),
        "diag-retrieval-mixed-session-rate-limit-001": ("auth_rate_limit", "tool.auth_rate_limit_triage"),
        "diag-retrieval-mixed-session-drift-control-001": ("auth_session_drift", "tool.auth_session_repair"),
    }
    expected_top_docs = {
        "diag-retrieval-mixed-latency-worker-001": "latency-worker-false",
        "diag-retrieval-mixed-latency-db-control-001": "latency-db-anchor",
        "diag-retrieval-mixed-cache-replica-001": "cache-replica-false",
        "diag-retrieval-mixed-cache-invalidation-control-001": "cache-invalid-anchor",
        "diag-retrieval-mixed-session-rate-limit-001": "session-rate-limit-false",
        "diag-retrieval-mixed-session-drift-control-001": "session-auth-anchor",
    }
    expected_contexts = {
        "diag-retrieval-mixed-latency-worker-001": ("cache_chain", "repo_local_cache_staleness"),
        "diag-retrieval-mixed-latency-db-control-001": ("cache_chain", "repo_local_cache_staleness"),
        "diag-retrieval-mixed-cache-replica-001": ("session_chain", "repo_local_auth_session_drift"),
        "diag-retrieval-mixed-cache-invalidation-control-001": ("session_chain", "repo_local_auth_session_drift"),
        "diag-retrieval-mixed-session-rate-limit-001": ("latency_chain", "repo_local_latency_triage"),
        "diag-retrieval-mixed-session-drift-control-001": ("latency_chain", "repo_local_latency_triage"),
    }
    for mode in ("text", "protocol"):
        tasks = {task["task_id"]: task for task in result["mode_runs"][mode][0]["tasks"]}
        assert set(tasks) == set(expected_routes)
        for task_id, (route, tool_name) in expected_routes.items():
            task = tasks[task_id]
            retrieve_payload = task["results"]["retrieve"]["payload"]
            execute_payload = task["results"]["execute"]["payload"]
            assert task["reuse"]["mode"] == "none"
            assert task["reuse_validation"]["matched_expectation"] is True
            assert retrieve_payload["retrieved_doc_ids"][0] == expected_top_docs[task_id]
            assert retrieve_payload["feature_route"] == route
            assert execute_payload["route"] == route
            assert execute_payload["tool_name"] == tool_name
            assert (task["task_group"], task["task_theme"]) == expected_contexts[task_id]


def test_retrieval_weak_route_diagnostic_task_set_surfaces_route_family_sensitivity() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-retrieval-weak-route-") as tmpdir:
        out_dir = Path(tmpdir)
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/retrieval_weak_route_diagnostic_tasks.yaml",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "internal_regression" in report_text
        assert "fresh_retrieval" in report_text
    expected_routes = {
        "diag-retrieval-weak-route-cache-invalidation-001": (
            "cache-invalid-anchor",
            "cache_invalidation",
            "tool.cache_invalidation_playbook",
        ),
        "diag-retrieval-weak-route-cache-replica-001": (
            "cache-replica-false",
            "cache_replica_stale_read",
            "tool.replica_stale_read_triage",
        ),
        "diag-retrieval-weak-route-latency-db-001": (
            "latency-db-anchor",
            "db_pool_saturation",
            "tool.db_pool_triage",
        ),
        "diag-retrieval-weak-route-latency-worker-001": (
            "latency-worker-false",
            "worker_queue_starvation",
            "tool.worker_queue_triage",
        ),
        "diag-retrieval-weak-route-session-drift-001": (
            "session-auth-anchor",
            "auth_session_drift",
            "tool.auth_session_repair",
        ),
        "diag-retrieval-weak-route-session-rate-limit-001": (
            "session-rate-limit-false",
            "auth_rate_limit",
            "tool.auth_rate_limit_triage",
        ),
    }
    expected_contexts = {
        "diag-retrieval-weak-route-cache-invalidation-001": ("session_chain", "repo_local_auth_session_drift"),
        "diag-retrieval-weak-route-cache-replica-001": ("session_chain", "repo_local_auth_session_drift"),
        "diag-retrieval-weak-route-latency-db-001": ("cache_chain", "repo_local_cache_staleness"),
        "diag-retrieval-weak-route-latency-worker-001": ("cache_chain", "repo_local_cache_staleness"),
        "diag-retrieval-weak-route-session-drift-001": ("latency_chain", "repo_local_latency_triage"),
        "diag-retrieval-weak-route-session-rate-limit-001": ("latency_chain", "repo_local_latency_triage"),
    }
    for mode in ("text", "protocol"):
        tasks = {task["task_id"]: task for task in result["mode_runs"][mode][0]["tasks"]}
        assert set(tasks) == set(expected_routes)
        for task_id, (top_doc_id, route, tool_name) in expected_routes.items():
            task = tasks[task_id]
            retrieve_payload = task["results"]["retrieve"]["payload"]
            execute_payload = task["results"]["execute"]["payload"]
            assert task["reuse"]["mode"] == "none"
            assert task["reuse_validation"]["matched_expectation"] is True
            assert retrieve_payload["retrieved_doc_ids"][0] == top_doc_id
            assert retrieve_payload["feature_route"] == route
            assert execute_payload["route"] == route
            assert execute_payload["tool_name"] == tool_name
            assert (task["task_group"], task["task_theme"]) == expected_contexts[task_id]


def test_retrieval_theme_variant_diagnostic_task_set_shows_theme_is_not_a_primary_route_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-retrieval-theme-variant-") as tmpdir:
        out_dir = Path(tmpdir)
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/retrieval_theme_variant_diagnostic_tasks.yaml",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "internal_regression" in report_text
        assert "fresh_retrieval" in report_text
    expected_routes = {
        "diag-retrieval-theme-variant-latency-db-001": ("latency-db-anchor", "db_pool_saturation"),
        "diag-retrieval-theme-variant-latency-worker-001": ("latency-worker-false", "worker_queue_starvation"),
        "diag-retrieval-theme-variant-session-drift-001": ("session-auth-anchor", "auth_session_drift"),
        "diag-retrieval-theme-variant-session-rate-limit-001": ("session-rate-limit-false", "auth_rate_limit"),
        "diag-retrieval-theme-variant-cache-invalidation-001": ("cache-invalid-anchor", "cache_invalidation"),
        "diag-retrieval-theme-variant-cache-replica-001": ("cache-replica-false", "cache_replica_stale_read"),
    }
    expected_themes = {
        "diag-retrieval-theme-variant-latency-db-001": "repo_local_latency_triage_variant",
        "diag-retrieval-theme-variant-latency-worker-001": "repo_local_latency_triage_variant",
        "diag-retrieval-theme-variant-session-drift-001": "repo_local_auth_session_variant",
        "diag-retrieval-theme-variant-session-rate-limit-001": "repo_local_auth_session_variant",
        "diag-retrieval-theme-variant-cache-invalidation-001": "repo_local_cache_variant",
        "diag-retrieval-theme-variant-cache-replica-001": "repo_local_cache_variant",
    }
    for mode in ("text", "protocol"):
        tasks = {task["task_id"]: task for task in result["mode_runs"][mode][0]["tasks"]}
        assert set(tasks) == set(expected_routes)
        for task_id, (top_doc_id, route) in expected_routes.items():
            task = tasks[task_id]
            retrieve_payload = task["results"]["retrieve"]["payload"]
            assert task["reuse"]["mode"] == "none"
            assert task["reuse_validation"]["matched_expectation"] is True
            assert retrieve_payload["retrieved_doc_ids"][0] == top_doc_id
            assert retrieve_payload["feature_route"] == route
            assert task["task_theme"] == expected_themes[task_id]


def test_retrieval_replay_multi_anchor_task_set_surfaces_anchor_selection_behavior() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-replay-multi-anchor-diag-") as tmpdir:
        out_dir = Path(tmpdir)
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/retrieval_replay_multi_anchor_tasks.yaml",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "step_skipping" in report_text
        assert "replay_enabled" in report_text
    expected_tasks = {
        "diag-replay-multi-anchor-a-001",
        "diag-replay-multi-anchor-b-001",
        "diag-replay-multi-anchor-exact-001",
    }
    for mode in ("text", "protocol"):
        tasks = {task["task_id"]: task for task in result["mode_runs"][mode][0]["tasks"]}
        assert set(tasks) == expected_tasks

        anchor_a = tasks["diag-replay-multi-anchor-a-001"]
        assert anchor_a["reuse"]["mode"] == "none"
        assert anchor_a["results"]["retrieve"]["skipped"] is False
        assert anchor_a["results"]["execute"]["skipped"] is False
        assert sorted(anchor_a["results"]["retrieve"]["payload"]["retrieved_doc_ids"]) == [
            "cache-invalid-anchor",
            "cache-invalid-replay",
        ]

        anchor_b = tasks["diag-replay-multi-anchor-b-001"]
        assert anchor_b["reuse"]["mode"] == "none"
        assert anchor_b["results"]["retrieve"]["skipped"] is False
        assert anchor_b["results"]["execute"]["skipped"] is False
        assert sorted(anchor_b["results"]["retrieve"]["payload"]["retrieved_doc_ids"]) == [
            "cache-invalid-anchor",
            "cache-invalid-followup",
        ]

        exact = tasks["diag-replay-multi-anchor-exact-001"]
        assert exact["reuse"]["mode"] == "skip_retrieve_execute"
        assert exact["results"]["retrieve"]["skipped"] is True
        assert exact["results"]["execute"]["skipped"] is True
        assert sorted(exact["results"]["retrieve"]["payload"]["retrieved_doc_ids"]) == [
            "cache-invalid-anchor",
            "cache-invalid-followup",
        ]
        assert exact["results"]["retrieve"]["reused_from_memory_id"] == "mem-diag-replay-multi-anchor-b-001-replay"


def test_retrieval_replay_route_diagnostic_task_set_covers_route_eligibility_boundaries() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-replay-route-diag-") as tmpdir:
        out_dir = Path(tmpdir)
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/retrieval_replay_route_diagnostic_tasks.yaml",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "step_skipping" in report_text
        assert "replay_enabled" in report_text
    expected_tasks = {
        "diag-replay-route-weak-anchor-001",
        "diag-replay-route-weak-exact-001",
        "diag-replay-route-clear-anchor-001",
        "diag-replay-route-clear-exact-001",
    }
    for mode in ("text", "protocol"):
        tasks = {task["task_id"]: task for task in result["mode_runs"][mode][0]["tasks"]}
        assert set(tasks) == expected_tasks

        weak_anchor = tasks["diag-replay-route-weak-anchor-001"]
        assert weak_anchor["reuse"]["mode"] == "none"
        assert weak_anchor["results"]["retrieve"]["skipped"] is False
        assert weak_anchor["results"]["execute"]["skipped"] is False
        assert weak_anchor["results"]["retrieve"]["payload"]["feature_route"] == "generic_triage"
        assert weak_anchor["results"]["retrieve"]["payload"]["feature_route_source"] == "low_confidence_abstain"

        weak_exact = tasks["diag-replay-route-weak-exact-001"]
        assert weak_exact["reuse"]["mode"] == "none"
        assert weak_exact["results"]["retrieve"]["skipped"] is False
        assert weak_exact["results"]["execute"]["skipped"] is False
        assert weak_exact["results"]["retrieve"]["payload"]["feature_route"] == "generic_triage"
        assert weak_exact["results"]["retrieve"]["payload"]["feature_route_source"] == "low_confidence_abstain"
        assert weak_exact["reuse_validation"]["matched_expectation"] is True

        clear_anchor = tasks["diag-replay-route-clear-anchor-001"]
        assert clear_anchor["reuse"]["mode"] == "none"
        assert clear_anchor["results"]["retrieve"]["skipped"] is False
        assert clear_anchor["results"]["execute"]["skipped"] is False
        assert clear_anchor["results"]["retrieve"]["payload"]["feature_route"] == "worker_queue_starvation"
        assert clear_anchor["results"]["retrieve"]["payload"]["feature_route_source"] == "hint_consensus"

        clear_exact = tasks["diag-replay-route-clear-exact-001"]
        assert clear_exact["reuse"]["mode"] == "skip_retrieve_execute"
        assert clear_exact["results"]["retrieve"]["skipped"] is True
        assert clear_exact["results"]["execute"]["skipped"] is True
        assert clear_exact["results"]["retrieve"]["payload"]["feature_route"] == "worker_queue_starvation"
        assert clear_exact["results"]["retrieve"]["payload"]["feature_route_source"] == "hint_consensus"
        assert clear_exact["results"]["retrieve"]["reused_from_memory_id"] == "mem-diag-replay-route-clear-anchor-001-replay"


def test_retrieval_replay_override_task_set_covers_lexical_override_route_provenance() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-replay-override-diag-") as tmpdir:
        out_dir = Path(tmpdir)
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/retrieval_replay_override_tasks.yaml",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "fresh_retrieval" in report_text
        assert "step_skipping" in report_text
        assert "replay_enabled" in report_text
    expected_tasks = {
        "diag-replay-override-anchor-001",
        "diag-replay-override-validated-001",
        "diag-replay-override-exact-001",
    }
    for mode in ("text", "protocol"):
        tasks = {task["task_id"]: task for task in result["mode_runs"][mode][0]["tasks"]}
        assert set(tasks) == expected_tasks

        anchor = tasks["diag-replay-override-anchor-001"]
        assert anchor["reuse"]["mode"] == "none"
        assert anchor["results"]["retrieve"]["skipped"] is False
        assert anchor["results"]["execute"]["skipped"] is False
        assert anchor["results"]["retrieve"]["payload"]["feature_route"] == "auth_rate_limit"
        assert anchor["results"]["retrieve"]["payload"]["feature_route_source"] == "lexical_override"
        assert anchor["results"]["retrieve"]["payload"]["feature_route_provenance"] == [
            "lexical",
            "corpus_metadata_conflict",
        ]

        validated = tasks["diag-replay-override-validated-001"]
        assert validated["reuse"]["mode"] == "skip_execute"
        assert validated["results"]["retrieve"]["skipped"] is False
        assert validated["results"]["execute"]["skipped"] is True
        assert validated["results"]["retrieve"]["payload"]["feature_route"] == "auth_rate_limit"
        assert validated["results"]["retrieve"]["payload"]["feature_route_source"] == "lexical_override"
        assert validated["results"]["retrieve"]["payload"]["feature_route_provenance"] == [
            "lexical",
            "corpus_metadata_conflict",
        ]
        assert validated["reuse_validation"]["matched_expectation"] is True

        exact = tasks["diag-replay-override-exact-001"]
        assert exact["reuse"]["mode"] == "skip_retrieve_execute"
        assert exact["results"]["retrieve"]["skipped"] is True
        assert exact["results"]["execute"]["skipped"] is True
        assert exact["results"]["retrieve"]["payload"]["feature_route"] == "auth_rate_limit"
        assert exact["results"]["retrieve"]["payload"]["feature_route_source"] == "lexical_override"
        assert exact["results"]["retrieve"]["payload"]["feature_route_provenance"] == [
            "lexical",
            "corpus_metadata_conflict",
        ]
        assert exact["results"]["retrieve"]["reused_from_memory_id"] == (
            "mem-diag-replay-override-validated-001-replay"
        )


def test_retrieval_replay_override_cache_task_set_covers_cross_family_lexical_override() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-replay-override-cache-diag-") as tmpdir:
        out_dir = Path(tmpdir)
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/retrieval_replay_override_cache_tasks.yaml",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "fresh_retrieval" in report_text
        assert "step_skipping" in report_text
        assert "replay_enabled" in report_text
    expected_tasks = {
        "diag-replay-override-cache-anchor-001",
        "diag-replay-override-cache-validated-001",
        "diag-replay-override-cache-exact-001",
    }
    for mode in ("text", "protocol"):
        tasks = {task["task_id"]: task for task in result["mode_runs"][mode][0]["tasks"]}
        assert set(tasks) == expected_tasks

        anchor = tasks["diag-replay-override-cache-anchor-001"]
        assert anchor["reuse"]["mode"] == "none"
        assert anchor["results"]["retrieve"]["skipped"] is False
        assert anchor["results"]["execute"]["skipped"] is False
        assert anchor["results"]["retrieve"]["payload"]["feature_route"] == "cache_replica_stale_read"
        assert anchor["results"]["retrieve"]["payload"]["feature_route_source"] == "lexical_override"
        assert anchor["results"]["retrieve"]["payload"]["feature_route_provenance"] == [
            "lexical",
            "corpus_metadata_conflict",
        ]

        validated = tasks["diag-replay-override-cache-validated-001"]
        assert validated["reuse"]["mode"] == "skip_execute"
        assert validated["results"]["retrieve"]["skipped"] is False
        assert validated["results"]["execute"]["skipped"] is True
        assert validated["results"]["retrieve"]["payload"]["feature_route"] == "cache_replica_stale_read"
        assert validated["results"]["retrieve"]["payload"]["feature_route_source"] == "lexical_override"
        assert validated["results"]["retrieve"]["payload"]["feature_route_provenance"] == [
            "lexical",
            "corpus_metadata_conflict",
        ]
        assert validated["reuse_validation"]["matched_expectation"] is True

        exact = tasks["diag-replay-override-cache-exact-001"]
        assert exact["reuse"]["mode"] == "skip_retrieve_execute"
        assert exact["results"]["retrieve"]["skipped"] is True
        assert exact["results"]["execute"]["skipped"] is True
        assert exact["results"]["retrieve"]["payload"]["feature_route"] == "cache_replica_stale_read"
        assert exact["results"]["retrieve"]["payload"]["feature_route_source"] == "lexical_override"
        assert exact["results"]["retrieve"]["payload"]["feature_route_provenance"] == [
            "lexical",
            "corpus_metadata_conflict",
        ]
        assert exact["results"]["retrieve"]["reused_from_memory_id"] == (
            "mem-diag-replay-override-cache-validated-001-replay"
        )


def test_retrieval_replay_override_cross_family_task_set_preserves_lexical_led_replay() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-replay-override-cross-family-") as tmpdir:
        out_dir = Path(tmpdir)
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/retrieval_replay_override_cross_family_tasks.yaml",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "step_skipping" in report_text
        assert "replay_enabled" in report_text
        assert "| text | lexical_override | 6 | 6 |" in report_text
        assert "| protocol | lexical_override | 6 | 6 |" in report_text
    expected_modes = {
        "diag-replay-override-validated-001": "skip_execute",
        "diag-replay-override-exact-001": "skip_retrieve_execute",
        "diag-replay-override-cache-validated-001": "skip_execute",
        "diag-replay-override-cache-exact-001": "skip_retrieve_execute",
    }
    expected_routes = {
        "diag-replay-override-anchor-001": "auth_rate_limit",
        "diag-replay-override-validated-001": "auth_rate_limit",
        "diag-replay-override-exact-001": "auth_rate_limit",
        "diag-replay-override-cache-anchor-001": "cache_replica_stale_read",
        "diag-replay-override-cache-validated-001": "cache_replica_stale_read",
        "diag-replay-override-cache-exact-001": "cache_replica_stale_read",
    }
    for mode in ("text", "protocol"):
        tasks = {task["task_id"]: task for task in result["mode_runs"][mode][0]["tasks"]}
        for task_id, route in expected_routes.items():
            retrieve_payload = tasks[task_id]["results"]["retrieve"]["payload"]
            assert retrieve_payload["feature_route"] == route
            assert retrieve_payload["feature_route_source"] == "lexical_override"
            assert retrieve_payload["feature_route_provenance"] == [
                "lexical",
                "corpus_metadata_conflict",
            ]
        for task_id, reuse_mode in expected_modes.items():
            assert tasks[task_id]["reuse"]["mode"] == reuse_mode
            assert tasks[task_id]["reuse_validation"]["matched_expectation"] is True


def test_retrieval_replay_override_theme_drift_task_set_blocks_exact_replay_across_families() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-replay-override-theme-drift-") as tmpdir:
        out_dir = Path(tmpdir)
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/retrieval_replay_override_theme_drift_tasks.yaml",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "fresh_retrieval" in report_text
        assert "internal_regression" in report_text
    expected_tasks = {
        "diag-replay-override-theme-auth-anchor-001",
        "diag-replay-override-theme-auth-drift-001",
        "diag-replay-override-theme-cache-anchor-001",
        "diag-replay-override-theme-cache-drift-001",
    }
    for mode in ("text", "protocol"):
        tasks = {task["task_id"]: task for task in result["mode_runs"][mode][0]["tasks"]}
        assert set(tasks) == expected_tasks
        for task_id in (
            "diag-replay-override-theme-auth-drift-001",
            "diag-replay-override-theme-cache-drift-001",
        ):
            task = tasks[task_id]
            assert task["reuse"]["mode"] == "none"
            assert task["results"]["retrieve"]["skipped"] is False
            assert task["results"]["execute"]["skipped"] is False
            retrieve_payload = task["results"]["retrieve"]["payload"]
            assert retrieve_payload["feature_route_source"] == "lexical_override"
            assert retrieve_payload["feature_route_provenance"] == [
                "lexical",
                "corpus_metadata_conflict",
            ]
            assert task["reuse_validation"]["matched_expectation"] is True


def test_retrieval_replay_override_matched_task_set_pairs_exact_replay_and_theme_drift() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-replay-override-matched-") as tmpdir:
        out_dir = Path(tmpdir)
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/retrieval_replay_override_matched_tasks.yaml",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
        assert "step_skipping" in report_text
        assert "fresh_retrieval" in report_text
        assert "| text | lexical_override | 6 | 6 |" in report_text
        assert "| protocol | lexical_override | 6 | 6 |" in report_text
    exact_positive = {
        "diag-replay-override-exact-001": "auth_rate_limit",
        "diag-replay-override-cache-exact-001": "cache_replica_stale_read",
    }
    exact_negative = {
        "diag-replay-override-theme-auth-drift-001": "auth_rate_limit",
        "diag-replay-override-theme-cache-drift-001": "cache_replica_stale_read",
    }
    for mode in ("text", "protocol"):
        tasks = {task["task_id"]: task for task in result["mode_runs"][mode][0]["tasks"]}
        for task_id, route in exact_positive.items():
            task = tasks[task_id]
            assert task["reuse"]["mode"] == "skip_retrieve_execute"
            retrieve_payload = task["results"]["retrieve"]["payload"]
            assert retrieve_payload["feature_route"] == route
            assert retrieve_payload["feature_route_source"] == "lexical_override"
            assert retrieve_payload["feature_route_provenance"] == [
                "lexical",
                "corpus_metadata_conflict",
            ]
            assert task["reuse_validation"]["matched_expectation"] is True
        for task_id, route in exact_negative.items():
            task = tasks[task_id]
            assert task["reuse"]["mode"] == "none"
            retrieve_payload = task["results"]["retrieve"]["payload"]
            assert retrieve_payload["feature_route"] == route
            assert retrieve_payload["feature_route_source"] == "lexical_override"
            assert retrieve_payload["feature_route_provenance"] == [
                "lexical",
                "corpus_metadata_conflict",
            ]
            assert task["reuse_validation"]["matched_expectation"] is True


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
                task_set_path="internal_regression",
                repeat=1,
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        second = asyncio.run(
            run_benchmark(
                task_set_path="internal_regression",
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
                task_set_path="communication",
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
