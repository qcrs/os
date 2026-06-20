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
import yaml

from agents.base_agent import BaseAgent
from agents.sample_agents import (
    _build_memory_assist_hint,
    _build_protocol_summary_handoff,
    _build_text_whole_lane_retriever_handoff,
    _strip_text_whole_lane_evidence_text,
    _build_transfer_brief,
    _headline_s2_prior_action_boundary,
    build_sample_agents_with_executor,
)
from eval.runner import (
    DEFAULT_BENCHMARK_TASK_SET,
    _build_case_contract_audit,
    _contest_formal_coverage_gate,
    _mode_order_for_run,
    _summarize_case_contract_rows,
    _whole_lane_text_guard_payload,
    run_benchmark,
)
from eval.open_runner import (
    OPEN_MEMORY_POLICIES,
    PURE_TEXT_OPEN_BASELINE_PACK,
    PURE_TEXT_OPEN_LIVE_API_PACK,
    RUNTIME_ARMS,
    run_langgraph_native_text_open_smoke,
    run_open_comparison,
    run_pure_text_open_baseline,
    run_pure_text_open_live_api_slice,
)
from memory.store import DeterministicEmbeddingProvider, MemoryStore
from protocol.messages import MemoryCommit, MemoryHit
from protocol.messages import (
    Plan,
    PlanStep,
    RemoteStepRequest,
    RemoteStepResponse,
    StateRef,
    StepResult,
    text_frame,
)
from runtime.contracts import SchemaValidationError, default_state_contract_registry
from runtime.langgraph_adapter import StateBusGraphRunner, langgraph_available
from runtime.llm import DeterministicLLMClient, LLMResult, LLMUsage
from runtime.orchestrator import Orchestrator, RunContext, RunSession, _route_is_replay_eligible
from runtime.task_profile import RuntimeTaskProfile
from runtime import executor_runtime
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
    extract_corpus_eval_labels,
    load_corpus_docs,
    render_corpus_evidence,
    retrieve_corpus_docs,
)
from tasks.contest_family_spec import (
    CONTEST_BENCHMARK_PATH,
    CONTEST_CORPUS_PATH,
    CONTEST_HONEST_HEADLINE_NAME,
    generate_contest_benchmark_payload,
    generate_contest_corpus_payload,
    generate_contest_honest_headline_payload,
    load_contest_family_spec,
)
from tasks.sample_tasks import (
    TASK_SET_ALIASES,
    SampleTask,
    default_task_chain,
    load_task_set_bundle,
)

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
            semantic_role="retrieve",
        )
    )
    assert rendered.startswith("Instruction for retriever:")
    assert '"query": "cache invalidation lag"' in rendered


def test_benchmark_runner_writes_outputs() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-benchmark-") as tmpdir:
        out_dir = Path(tmpdir) / "runs"
        result = asyncio.run(
            run_benchmark(
                task_set_path="contest_dual_mode_controlled_v3",
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
        task_chain = list(load_task_set_bundle("contest_dual_mode_controlled_v3").tasks)
        expected_lane_counts = {
            "internal_regression": sum(1 for task in task_chain if task.benchmark_lane == "internal_regression"),
            "communication": sum(1 for task in task_chain if task.benchmark_lane == "communication"),
            "state_transfer": sum(1 for task in task_chain if task.benchmark_lane == "state_transfer"),
            "memory": sum(1 for task in task_chain if task.benchmark_lane == "memory"),
            "integrity": 0,
        }
        expected_transfer_strategy_counts = {
            "text_strict_pure_lane": sum(
                1 for task in task_chain if task.transfer_strategy == "text_strict_pure_lane"
            ),
            "text_whole_lane": sum(
                1 for task in task_chain if task.transfer_strategy == "text_whole_lane"
            ),
            "inline_text_handoff": sum(
                1 for task in task_chain if task.transfer_strategy == "inline_text_handoff"
            ),
            "natural_handoff_text": sum(
                1 for task in task_chain if task.transfer_strategy == "natural_handoff_text"
            ),
            "channel_store_hashref": sum(
                1 for task in task_chain if task.transfer_strategy == "state_ref"
            ),
            "text_brief": sum(1 for task in task_chain if task.transfer_strategy == "text_brief"),
            "text_packet_minimal": sum(1 for task in task_chain if task.transfer_strategy == "text_packet_minimal"),
            "state_packet_minimal": sum(1 for task in task_chain if task.transfer_strategy == "state_packet_minimal"),
            "flat_state_ref": 0,
        }
        expected_memory_policy_counts = {
            "memory_off": sum(1 for task in task_chain if task.runtime_reuse_contract == "reuse_disabled"),
            "working_assist": sum(1 for task in task_chain if task.runtime_reuse_contract == "assist_allowed"),
            "long_term_assist": 0,
            "validated_replay": sum(1 for task in task_chain if task.runtime_reuse_contract == "validated_replay"),
            "exact_replay": sum(1 for task in task_chain if task.runtime_reuse_contract == "exact_replay"),
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
        assert payload["manifest"]["engine"] == "langgraph"
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
        manifest_transfer_counts = payload["manifest"]["transfer_strategy_counts"]
        assert manifest_transfer_counts == expected_transfer_strategy_counts
        assert "text_strict_pure_lane" in manifest_transfer_counts
        assert payload["manifest"]["channel_form_counts"]["typed_channel"] >= 1
        manifest_memory_counts = payload["manifest"]["memory_policy_counts"]
        assert manifest_memory_counts["memory_off"] == expected_memory_policy_counts["memory_off"]
        assert "working_assist" in manifest_memory_counts
        assert payload["manifest"]["artifact_expectation_counts"] == expected_artifact_expectation_counts
        assert payload["manifest"]["artifact_expectation_task_count"] == sum(
            1 for task in task_chain if any(task.artifact_expectations.values())
        )
        assert payload["manifest"]["task_groups"] == sorted({task.task_group for task in task_chain})
        assert payload["manifest"]["task_pack_type"] == "contest_dual_mode_controlled_v3"
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
        assert "## Contest Controlled Composite V3" in report_text
        assert "handoff_wire_bytes" in report_text
        assert "handoff_payload_bytes" in report_text
        assert "whole-lane text guard pass rate" in report_text.lower()
        task_run = payload["mode_runs"]["protocol"][0]["tasks"][0]
        assert task_run["engine"] == "langgraph"
        assert task_run["graph_state"]["metrics"] == task_run["metrics"]
        assert sorted(task_run["state_refs"]) == sorted(task_run["graph_state"]["state_ref_ids"])
        assert task_run["state_channels"]
        assert set(task_run["graph_state"]["role_context_slices"]) >= {
            "planner",
            "retriever",
            "executor",
            "summarizer",
        }
        executor_slice = task_run["graph_state"]["role_context_slices"]["executor"]
        assert executor_slice["projection_class"]
        assert executor_slice["included_fields"]
        assert executor_slice["omitted_fields"]
        assert executor_slice["role_visible_contract"]
        assert task_run["graph_state"]["fairness_gate"]["passed"] is True
        assert "logical_replay_reuse" in task_run["reuse"]
        assert "physical_blob_reuse" in task_run["reuse"]
        protocol_tasks = payload["mode_runs"]["protocol"][0]["tasks"]
        assert max(task["metrics"]["trajectory_commit_count"] for task in protocol_tasks) > 1
        assert max(task["metrics"]["trajectory_diff_count"] for task in protocol_tasks) > 0


def test_benchmark_runner_is_langgraph_only() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-benchmark-langgraph-") as tmpdir:
        out_dir = Path(tmpdir) / "runs"
        result = asyncio.run(
            run_benchmark(
                repeat=1,
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
                engine="langgraph",
            )
        )
        payload = json.loads((out_dir / "benchmark_results.json").read_text(encoding="utf-8"))
        assert result["manifest"]["engine"] == "langgraph"
        assert payload["manifest"]["engine"] == "langgraph"


def test_benchmark_runner_default_task_set_is_carrier_pack() -> None:
    assert DEFAULT_BENCHMARK_TASK_SET.name == "contest_dual_mode_controlled_v3_benchmark.yaml"


def test_langgraph_runner_requires_real_langgraph_dependency(monkeypatch) -> None:
    if not langgraph_available():
        pytest.skip("host env already lacks langgraph")
    task = load_task_set_bundle("contest_dual_mode_controlled_v3").tasks[1]
    runner = StateBusGraphRunner(
        llm_client=DeterministicLLMClient(),
        embedder=DeterministicEmbeddingProvider(),
    )
    monkeypatch.setattr("runtime.langgraph_adapter.langgraph_available", lambda: False)
    with pytest.raises(RuntimeError, match="langgraph is not installed"):
        asyncio.run(runner.run_task(task, mode="protocol"))


def test_default_task_set_is_contest_dual_mode_controlled_v3_pack() -> None:
    bundle = load_task_set_bundle()
    assert bundle.metadata.name == "contest_dual_mode_controlled_v3_pack"
    assert bundle.metadata.pack_type == "contest_dual_mode_controlled_v3"
    assert bundle.metadata.support_only is False
    assert bundle.metadata.claim_lanes == ("communication", "state_transfer")
    assert len(bundle.tasks) == 40
    assert bundle.metadata.formal_secondary is False
    task_ids = {task.task_id for task in bundle.tasks}
    assert "rr-checkout-clean-text-001" in task_ids
    assert "rr-checkout-clean-protocol-001" in task_ids
    assert {task.transfer_strategy for task in bundle.tasks} == {"text_strict_pure_lane", "state_packet_minimal"}
    assert {task.summary_contract for task in bundle.tasks} == {"actions_plus_evidence"}


def test_active_v3_pack_aliases_all_load_with_explicit_metadata() -> None:
    active_aliases = sorted(alias for alias in TASK_SET_ALIASES if alias != "default")
    loaded = {alias: load_task_set_bundle(alias) for alias in active_aliases}
    loaded["typed_state_consumer_sensitivity_v3"] = load_task_set_bundle(
        "typed_state_consumer_sensitivity_v3"
    )
    assert len(loaded) == 17
    assert all(bundle.metadata.pack_type != "ad_hoc" for bundle in loaded.values())
    assert all(bundle.metadata.public_surface for bundle in loaded.values())
    assert all(bundle.metadata.evidence_tier for bundle in loaded.values())
    assert all(bundle.metadata.variable_axes for bundle in loaded.values())
    assert all(bundle.metadata.plan_source_default == "yaml" for bundle in loaded.values())


def test_contest_family_spec_generates_committed_benchmark_and_corpus() -> None:
    benchmark_payload = yaml.safe_load(CONTEST_BENCHMARK_PATH.read_text(encoding="utf-8"))
    corpus_payload = yaml.safe_load(CONTEST_CORPUS_PATH.read_text(encoding="utf-8"))

    assert generate_contest_benchmark_payload() == benchmark_payload
    assert generate_contest_corpus_payload() == corpus_payload


def test_contest_family_spec_generates_honest_headline_payload() -> None:
    payload = generate_contest_honest_headline_payload()
    assert payload["task_set"]["name"] == CONTEST_HONEST_HEADLINE_NAME
    assert payload["task_set"]["pack_type"] == "contest_honest_headline_v1"
    assert payload["task_set"]["single_variable"] is True
    assert payload["task_set"]["variable_axes"] == ["mode"]
    text_rows = [task for task in payload["tasks"] if task["allowed_modes"] == ["text"]]
    protocol_rows = [task for task in payload["tasks"] if task["allowed_modes"] == ["protocol"]]
    assert len(text_rows) == 20
    assert len(protocol_rows) == 20
    assert all(task["transfer_strategy"] == "text_whole_lane" for task in text_rows)
    assert all(task["handoff_profile"] == "text_whole_lane" for task in text_rows)
    assert all(task["transfer_strategy"] == "state_packet_minimal" for task in protocol_rows)
    assert all(task["handoff_profile"] == "protocol_minimal_state_packet" for task in protocol_rows)


def test_contest_family_spec_is_single_source_of_truth_for_family_contracts() -> None:
    spec = load_contest_family_spec()
    assert spec["task_set"]["pack_type"] == "contest_dual_mode_controlled_v3"
    assert spec["task_set"]["formal_structure_clean_retrieval"] is True
    assert spec["corpus_metadata"]["formal_structure_clean"] is True
    assert len(spec["families"]) == 5

    for family in spec["families"]:
        assert set(family["cases"]) == {"clean", "distractor", "ambiguous", "replay_reusable"}
        assert len(family["route_competition"]) >= 2
        assert len(family["tool_competition"]) >= 2
        assert family["thickness_contract"] == {
            "route_competition_min": 2,
            "tool_competition_min": 3,
        }
        assert len(family["docs"]) == 8
        normalized_roles = {
            {
                "rotation": "structural_anchor",
                "runbook": "structural_anchor",
                "config": "structural_anchor",
                "flag-diff": "structural_anchor",
                "rate-limit-false": "cross_family_distractor",
                "db-false": "cross_family_distractor",
                "worker-false": "cross_family_distractor",
                "replica-false": "cross_family_distractor",
                "ambiguous": "ambiguity_note",
                "scope": "scope_note",
                "reuse": "reuse_dependency_note",
            }.get(role, role)
            for role in family["docs"]
        }
        assert normalized_roles == {
            "incident",
            "metrics",
            "logs",
            "structural_anchor",
            "cross_family_distractor",
            "ambiguity_note",
            "scope_note",
            "reuse_dependency_note",
        }
        case = family["cases"]["replay_reusable"]
        assert case["required_prior_case_ids"]
        assert case["required_prior_rejections"]
        assert case["required_prior_routes"]
        for case_key, case in family["cases"].items():
            if case_key == "replay_reusable":
                assert case["thickness_setting"] == "S2"
                assert case["dependency_depth"] >= 2
            else:
                assert case["thickness_setting"] == "S1"
                assert case["dependency_depth"] == 1
            assert case["reasoning_hops_min"] >= 2
            assert case["required_plan_semantic_roles"] == [
                "retrieve",
                "validate",
                "execute",
                "summarize",
            ]
            assert len(case["expected_intermediate_decisions"]) >= 2
            assert case["abstention_boundary"]


def test_task_pack_aliases_and_support_only_flags() -> None:
    expectations = {
        "default": ("contest_dual_mode_controlled_v3", False, False, False, 40),
        "contest_dual_mode_controlled_v3": ("contest_dual_mode_controlled_v3", False, False, False, 40),
        "memory_dual_mode_fairness_v3": ("memory_dual_mode_fairness_v3", False, True, False, 40),
        "typed_state_mechanism_v3": ("typed_state_mechanism_v3", False, False, True, 8),
        "external_text_baseline_audit_v3": ("external_text_baseline_audit_v3", False, True, False, 4),
        "text_definition_audit_v3": ("text_definition_audit_v3", False, True, False, 40),
        "typed_state_authenticity_v3": ("typed_state_authenticity_v3", False, False, True, 40),
        "carrier_microbench_v3": ("carrier_microbench_v3", False, True, False, 40),
        "memory_reuse_v3": ("memory_reuse_v3", False, False, True, 4),
        "memory_policy_controlled_v3": ("memory_policy_controlled_v3", False, False, True, 8),
        "planner_support_v3": ("planner_support_v3", False, False, True, 11),
        "pure_text_open_live_api_slice_v1": ("pure_text_open_live_api_slice_v1", False, True, False, 8),
        "route_corpus_stress_whole_lane_audit_v1": ("route_corpus_stress_whole_lane_audit_v1", False, True, False, 4),
    }
    for alias, (pack_type, support_only, audit_only, formal_secondary, task_count) in expectations.items():
        bundle = load_task_set_bundle(alias)
        assert bundle.metadata.pack_type == pack_type
        assert bundle.metadata.support_only is support_only
        assert bundle.metadata.audit_only is audit_only
        assert bundle.metadata.formal_secondary is formal_secondary
        assert len(bundle.tasks) == task_count


def test_pack_metadata_exposes_single_variable_and_variable_axes() -> None:
    fairness = load_task_set_bundle("memory_dual_mode_fairness_v3").metadata
    contest = load_task_set_bundle("contest_dual_mode_controlled_v3").metadata
    mechanism = load_task_set_bundle("typed_state_mechanism_v3").metadata
    authenticity = load_task_set_bundle("typed_state_authenticity_v3").metadata
    external_text = load_task_set_bundle("external_text_baseline_audit_v3").metadata
    planner = load_task_set_bundle("planner_support_v3").metadata

    assert fairness.single_variable is False
    assert fairness.variable_axes == ("mode", "runtime_reuse_contract", "restore_object_class")
    assert fairness.public_surface == "audit_only"

    assert contest.single_variable is False
    assert contest.variable_axes == ("mode", "handoff_object")
    assert contest.public_surface == "formal_headline"

    assert mechanism.single_variable is True
    assert mechanism.variable_axes == ("handoff_object",)
    assert mechanism.public_surface == "formal_secondary"
    assert mechanism.plan_source_default == "yaml"

    assert authenticity.single_variable is True
    assert authenticity.variable_axes == ("handoff_object",)
    assert authenticity.public_surface == "formal_secondary"
    assert authenticity.plan_source_default == "yaml"

    assert external_text.single_variable is True
    assert external_text.variable_axes == ("external_text_surface",)
    assert external_text.public_surface == "audit_only"

    assert planner.single_variable is True
    assert planner.variable_axes == ("plan_source",)
    assert planner.public_surface == "formal_secondary_planner"


def test_active_v3_pack_rejects_public_surface_alias_metadata() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-public-surface-alias-") as tmpdir:
        pack_path = Path(tmpdir) / "alias_pack.yaml"
        pack_path.write_text(
            """
task_set:
  name: alias_pack
  pack_type: typed_state_mechanism_v3
  description: alias contract probe
  reading_contract: alias contract probe
  claim_lanes: [state_transfer]
  single_variable: true
  variable_axes: [handoff_object]
  public_surface: formal_secondary_typed_state_mechanism
  plan_source_default: yaml
  evidence_tier: formal_secondary
  benchmark_version: v3
tasks:
- task_id: alias-pack-row-001
  task_group: alias_pack_group
  task_order: 1
  task_theme: contest_release_checkout_regression
  benchmark_lane: state_transfer
  allowed_modes: [protocol]
  transfer_strategy: state_packet_minimal
  handoff_profile: protocol_minimal_state_packet
  goal: Alias metadata should fail active-v3 validation.
  query: checkout canary order confirmations slowed after the rollout, and operators need the safest first validation action
  corpus_doc_ids: [rr-checkout-incident, rr-checkout-metrics, rr-checkout-logs, rr-checkout-worker-false]
  corpus_path: contest_release_regression_corpus.yaml
  summary_hint: Return the safest first action only.
  evidence_text: Alias metadata contract probe.
  tags: [release, checkout, latency, clean]
  reuse_tags: [release, checkout, latency]
  expected_reuse_mode: none
  runtime_reuse_contract: reuse_disabled
  case_id: alias-pack-case
  case_type: bounded_alternative
  eval_scope: case_level
  expected_family: db_pool_saturation
  primary_expected_route: db_pool_saturation
  primary_expected_tool: tool.db_pool_triage
  acceptable_routes: [db_pool_saturation, worker_queue_starvation]
  acceptable_tools: [tool.db_pool_triage, tool.worker_queue_triage]
  disallowed_families: []
  abstention_allowed: false
  allowed_abstain_tool: ""
  abstain_only_when: ""
  complexity_bucket: simple
  summary_contract: actions_plus_evidence
""".strip(),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="canonical public_surface"):
            load_task_set_bundle(pack_path)


def test_legacy_task_pack_aliases_fail() -> None:
    for alias in (
        "carrier_controlled_v2",
        "semantic_retention_v2",
        "strict_pure_text_boundary_v2",
        "memory_reuse_v2",
        "planner_support_v2",
        "langgraph_native_text_support_v2",
        "formal_controlled",
    ):
        with pytest.raises((FileNotFoundError, ValueError)):
            load_task_set_bundle(alias)


def test_archived_benchmark_files_remain_loadable_by_explicit_path() -> None:
    for relpath, task_count in (
        ("tasks/communication_benchmark.yaml", 2),
        ("tasks/internal_regression_benchmark.yaml", 21),
        ("tasks/state_transfer_inline_text_support_benchmark.yaml", 6),
    ):
        bundle = load_task_set_bundle(relpath)
        assert len(bundle.tasks) == task_count
        assert bundle.metadata.pack_type == "ad_hoc"
        assert bundle.metadata.benchmark_version == "historical_v1"
        assert bundle.metadata.historical_pack_type != ""


def test_pack_boundary_split_keeps_v3_formal_surface_separate_from_internal_regression() -> None:
    formal_bundle = load_task_set_bundle("contest_dual_mode_controlled_v3")
    internal_bundle = load_task_set_bundle("tasks/internal_regression_benchmark.yaml")

    formal_ids = {task.task_id for task in formal_bundle.tasks}
    internal_ids = {task.task_id for task in internal_bundle.tasks}

    assert "rr-checkout-clean-text-001" in formal_ids
    assert "rr-checkout-clean-protocol-001" in formal_ids
    assert not any(task_id.startswith("regr-") for task_id in formal_ids)

    assert {
        "regr-lexical-override-cache-001",
        "regr-lexical-override-latency-001",
        "regr-lexical-override-session-001",
    }.issubset(internal_ids)


def test_orchestrator_respects_yaml_vs_llm_plan_source() -> None:
    agents = build_sample_agents_with_executor(llm_client=DeterministicLLMClient())
    orchestrator = Orchestrator(agents)
    base_task = load_task_set_bundle("contest_dual_mode_controlled_v3").tasks[1]
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
        assert yaml_ctx.metrics.planned_step_count == 4
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
        assert llm_ctx.metrics.planned_step_count == 4
        llm_ctx.memory_store.close()
        llm_ctx.session.cleanup()


def test_planner_support_v3_pack_contract() -> None:
    bundle = load_task_set_bundle("planner_support_v3")
    assert bundle.metadata.name == "planner_support_v3_pack"
    assert bundle.metadata.pack_type == "planner_support_v3"
    assert bundle.metadata.support_only is False
    assert bundle.metadata.formal_secondary is True
    assert bundle.metadata.claim_lanes == ("communication",)
    assert len(bundle.tasks) == 11
    assert {task.plan_source for task in bundle.tasks} == {"yaml", "llm"}
    assert {task.allowed_modes for task in bundle.tasks} == {("protocol",)}
    assert {task.transfer_strategy for task in bundle.tasks} == {"state_packet_minimal"}
    assert {task.summary_contract for task in bundle.tasks} == {"actions_plus_evidence"}
    deploy_llm = next(task for task in bundle.tasks if task.task_id == "planner-support-deploy-llm-001")
    assert "four-step" in deploy_llm.goal
    assert deploy_llm.required_plan_semantic_roles == (
        "retrieve",
        "validate",
        "execute",
        "summarize",
    )
    auth_llm = next(task for task in bundle.tasks if task.task_id == "planner-support-auth-llm-002")
    assert "validate the route before execution" in auth_llm.query
    assert auth_llm.required_plan_semantic_roles == (
        "retrieve",
        "validate",
        "execute",
        "summarize",
    )


def test_state_transfer_packs_fill_default_route_and_tool_expectations() -> None:
    expected_by_theme = {
        "contest_release_checkout_regression": ("db_pool_saturation", "tool.db_pool_triage"),
        "contest_release_auth_rotation": ("auth_session_drift", "tool.auth_session_repair"),
        "contest_release_inventory_rollout": ("cache_invalidation", "tool.cache_invalidation_playbook"),
        "contest_release_billing_queue_backlog": ("worker_queue_starvation", "tool.worker_queue_triage"),
        "contest_release_deployment_config_drift": ("db_pool_saturation", "tool.db_pool_triage"),
    }
    for pack_name in (
        "contest_dual_mode_controlled_v3",
        "text_definition_audit_v3",
        "typed_state_authenticity_v3",
        "typed_state_mechanism_v3",
        "external_text_baseline_audit_v3",
    ):
        bundle = load_task_set_bundle(pack_name)
        for task in bundle.tasks:
            expected_route, expected_tool_name = expected_by_theme[task.task_theme]
            assert task.expected_route == expected_route
            assert task.expected_tool_name == expected_tool_name
            assert task.expected_route_source == ""


def test_typed_state_authenticity_v3_emits_step_truth_and_transfer_truth_audit() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-transfer-truth-v3-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="typed_state_authenticity_v3",
                repeat=1,
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    task_rows = result["mode_runs"]["protocol"][0]["tasks"]
    typed_task = next(task for task in task_rows if task["transfer_strategy"] == "state_packet_minimal")
    for task in task_rows[:2]:
        assert {"retrieve", "execute", "summarize"} <= set(task["step_truth"])
        assert "input_refs" in task["step_truth"]["execute"]
        assert "output_refs" in task["step_truth"]["retrieve"]
        truth = task["transfer_truth_audit"]
        assert "question_answered" in truth
        assert "actual_compared_object" in truth
        assert "executor_input_kinds" in truth
        assert "summarizer_input_kinds" in truth
    assert "DENSE_EVIDENCE" in typed_task["transfer_truth_audit"]["executor_input_kinds"]
    assert "EXECUTOR_DECISION_PACKET" in typed_task["transfer_truth_audit"]["executor_input_kinds"]
    assert result["summary"]["protocol"]["transfer_truth"]["summarizer_visibility_asymmetry_rate"] >= 0.0
    assert result["summary"]["protocol"]["transfer_truth"]["typed_executor_minimal_expected_consumption_rate"] > 0.0
    assert result["summary"]["protocol"]["transfer_truth"]["executor_unexpected_kind_seen_rate"] == 0.0


def test_typed_state_authenticity_v3_uses_natural_text_vs_minimal_state_packet_pairs() -> None:
    tasks = list(load_task_set_bundle("typed_state_authenticity_v3").tasks)
    assert len(tasks) == 40

    def _normalize_case(task_id: str) -> str:
        for suffix in ("-pure-text-001", "-state-packet-001"):
            if task_id.endswith(suffix):
                return task_id[: -len(suffix)]
        raise AssertionError(f"unexpected authenticity task id: {task_id}")

    grouped: dict[str, list[SampleTask]] = {}
    for task in tasks:
        grouped.setdefault(_normalize_case(task.task_id), []).append(task)

    assert len(grouped) == 20
    for pair in grouped.values():
        assert len(pair) == 2
        assert {task.transfer_strategy for task in pair} == {"natural_handoff_text", "state_packet_minimal"}
        assert {task.handoff_profile for task in pair} == {
            "protocol_natural_handoff_text",
            "protocol_minimal_state_packet",
        }
        assert all(task.supports_mode("protocol") for task in pair)
        assert all(not task.supports_mode("text") for task in pair)


def test_typed_state_mechanism_v3_uses_protocol_only_natural_text_vs_minimal_pairs() -> None:
    tasks = list(load_task_set_bundle("typed_state_mechanism_v3").tasks)
    assert len(tasks) == 8
    assert {task.runtime_reuse_contract for task in tasks} == {"reuse_disabled"}
    grouped: dict[str, list[SampleTask]] = {}
    for task in tasks:
        grouped.setdefault(task.case_id, []).append(task)
    assert len(grouped) == 4
    for pair in grouped.values():
        assert len(pair) == 2
        assert {task.transfer_strategy for task in pair} == {"natural_handoff_text", "state_packet_minimal"}
        assert {task.handoff_profile for task in pair} == {
            "protocol_natural_handoff_text",
            "protocol_minimal_state_packet",
        }
        assert all(task.supports_mode("protocol") for task in pair)
        assert all(not task.supports_mode("text") for task in pair)


def test_external_text_baseline_audit_v3_is_text_only_and_reuse_disabled() -> None:
    tasks = list(load_task_set_bundle("external_text_baseline_audit_v3").tasks)
    assert len(tasks) == 4
    assert {task.transfer_strategy for task in tasks} == {"text_strict_pure_lane"}
    assert {task.runtime_reuse_contract for task in tasks} == {"reuse_disabled"}
    assert all(task.supports_mode("text") for task in tasks)
    assert all(not task.supports_mode("protocol") for task in tasks)


def test_audit_handoff_carrier_truth_report_marks_audit_only_boundary() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-audit-carrier-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/audit_handoff_carrier_truth_benchmark.yaml",
                repeat=1,
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (Path(tmpdir) / "benchmark_report.md").read_text(encoding="utf-8")
    assert result["manifest"]["task_pack_type"] == "ad_hoc"
    assert result["manifest"]["benchmark_version"] == "v3"
    assert "Task pack type: `ad_hoc`" in report_text
    assert "State Transfer Strategies" in report_text
    assert "inline_text_handoff" in report_text
    assert "natural_handoff_text" in report_text
    assert "text_packet_minimal" in report_text
    assert "state_packet_minimal" in report_text
    assert "Case Contract Audit" in report_text


def test_audit_state_visibility_truth_report_marks_audit_only_boundary() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-audit-visibility-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/audit_state_visibility_truth_benchmark.yaml",
                repeat=1,
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (Path(tmpdir) / "benchmark_report.md").read_text(encoding="utf-8")
    assert result["manifest"]["task_pack_type"] == "ad_hoc"
    assert result["manifest"]["benchmark_version"] == "v3"
    assert "Task pack type: `ad_hoc`" in report_text
    assert "state_packet_minimal" in report_text
    assert "channel_store_hashref" in report_text
    assert "State Transfer Strategies" in report_text
    assert "Case Contract Audit" in report_text


def test_case_contract_audit_requires_route_tool_pair_for_admissible_match() -> None:
    bounded_task = {
        "task_id": "bounded-case-001",
        "task_theme": "contest_release_checkout_regression",
        "results": {
            "retrieve": {"payload": {"feature_route": "db_pool_saturation", "feature_route_source": "hint_consensus"}},
            "execute": {"payload": {"tool_name": "tool.worker_queue_triage"}},
        },
        "case_contract": {
            "case_id": "bounded-case-001",
            "case_type": "bounded_alternative",
            "expected_family": "db_pool_saturation",
            "primary_expected_route": "db_pool_saturation",
            "primary_expected_tool": "tool.db_pool_triage",
            "acceptable_routes": ["db_pool_saturation"],
            "acceptable_tools": ["tool.db_pool_triage"],
            "disallowed_families": [],
            "abstention_allowed": False,
            "allowed_abstain_tool": "",
        },
    }
    route_only = _build_case_contract_audit(bounded_task)
    assert route_only["acceptable_route_match"] is True
    assert route_only["acceptable_tool_match"] is False
    assert route_only["alternate_pair_admissible"] is False
    assert route_only["admissible_match"] is False
    tool_only_task = {
        **bounded_task,
        "results": {
            "retrieve": {"payload": {"feature_route": "worker_queue_starvation", "feature_route_source": "hint_consensus"}},
            "execute": {"payload": {"tool_name": "tool.db_pool_triage"}},
        },
    }
    tool_only = _build_case_contract_audit(tool_only_task)
    assert tool_only["acceptable_route_match"] is False
    assert tool_only["acceptable_tool_match"] is True
    assert tool_only["alternate_pair_admissible"] is False
    assert tool_only["admissible_match"] is False
    abstain_task = {
        **bounded_task,
        "case_contract": {
            **bounded_task["case_contract"],
            "case_type": "abstention_allowed",
            "abstention_allowed": True,
            "allowed_abstain_tool": "tool.collect_more_evidence",
        },
        "results": {
            "retrieve": {"payload": {"feature_route": "worker_queue_starvation", "feature_route_source": "hint_consensus"}},
            "execute": {"payload": {"tool_name": "tool.collect_more_evidence"}},
        },
    }
    abstain = _build_case_contract_audit(abstain_task)
    assert abstain["abstention_match"] is True
    assert abstain["admissible_match"] is True


def test_case_contract_audit_marks_empty_contracts_as_not_evaluated() -> None:
    audit = _build_case_contract_audit(
        {
            "task_id": "audit-only-001",
            "task_theme": "contest_release_checkout_regression",
            "results": {
                "retrieve": {"payload": {"feature_route": "db_pool_saturation"}},
                "execute": {"payload": {"tool_name": "tool.db_pool_triage"}},
            },
            "case_contract": {
                "case_id": "audit-only-001",
                "case_type": "exact_single_solution",
                "expected_family": "",
                "primary_expected_route": "",
                "primary_expected_tool": "",
                "acceptable_routes": [],
                "acceptable_tools": [],
                "disallowed_families": [],
                "abstention_allowed": False,
                "allowed_abstain_tool": "",
            },
        }
    )
    assert audit["correctness_label"] == "not_evaluated"
    assert audit["admissible_match"] is False
    assert audit["route_exact"] is False
    assert audit["tool_exact"] is False


def test_case_contract_summary_includes_not_evaluated_label() -> None:
    summary = _summarize_case_contract_rows(
        [
            {
                "case_contract_audit": {
                    "case_id": "audit-only-001",
                    "case_type": "exact_single_solution",
                    "correctness_label": "not_evaluated",
                    "route_exact": False,
                    "tool_exact": False,
                    "exact_match": False,
                    "admissible_match": False,
                    "abstention_match": False,
                    "wrong_family": False,
                }
            }
        ]
    )
    assert summary["label_counts"].get("not_evaluated", 0) == 1

def test_reuse_modes_cover_assist_reject_and_skip_paths() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-test-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/internal_regression_benchmark.yaml",
                repeat=1,
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    task_specs = {task.task_id: task for task in load_task_set_bundle("tasks/internal_regression_benchmark.yaml").tasks}
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
                task_set_path="tasks/internal_regression_benchmark.yaml",
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
        assert task["results"]["retrieve"]["payload"]["feature_route_source"] == "lexical_match"
        assert task["results"]["retrieve"]["payload"]["feature_route_confidence"] >= 0.8
        route_provenance = task["results"]["retrieve"]["payload"]["feature_route_provenance"]
        assert "lexical" in route_provenance
        assert task["results"]["retrieve"]["payload"]["feature_hint_doc_ids"] == []
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
        assert task["results"]["execute"]["payload"]["route_source"] == "lexical_match"
        assert task["results"]["execute"]["payload"]["route_confidence"] >= 0.8
        assert task["results"]["execute"]["payload"]["route_provenance"] == ["lexical"]
        assert task["results"]["execute"]["payload"]["hint_doc_ids"] == []
        copied_refs = [
            ref
            for ref in task["state_refs"].values()
            if ref["metadata"].get("reused_from_memory_id") == reused_memory_id
        ]
        assert len(copied_refs) == 8
        assert {ref["kind"] for ref in copied_refs} == {
            "CHANNEL_SNAPSHOT",
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
            if ref["storage"] != "CAS_BLOB":
                assert "sample-cache-006" in ref["handle"]
            assert Path(ref["handle"]).exists()
        cas_refs = [ref for ref in copied_refs if ref["storage"] == "CAS_BLOB"]
        assert cas_refs
        assert {"FEATURE_BUNDLE", "TOOL_ARTIFACT"}.issubset({ref["kind"] for ref in cas_refs})
        assert task["reuse"]["logical_replay_reuse"] is True
        assert task["reuse"]["physical_blob_reuse"] is True
        assert task["reuse"]["dedup_bytes_saved"] > 0
        assert task["reuse"]["cas_hit_rate"] > 0
        assert task["cas_summary"]["physical_blob_count"] >= 1
        copied_artifact = next(ref for ref in copied_refs if ref["kind"] == "TOOL_ARTIFACT")
        assert copied_artifact["metadata"]["tool_name"] == "tool.cache_invalidation_playbook"
        assert copied_artifact["metadata"]["route"] == "cache_invalidation"
        assert copied_artifact["metadata"]["source_evidence"]
        assert task["results"]["summarize"]["success"] is True
        assert task["results"]["summarize"]["skipped"] is False


def test_exact_replay_no_longer_requires_explicit_source_task_id() -> None:
    exact_replay_tasks = [
        task
        for task in load_task_set_bundle("tasks/internal_regression_benchmark.yaml").tasks
        if task.expected_reuse_mode == "skip_retrieve_execute"
    ]
    assert exact_replay_tasks
    assert all(task.replay_source_task_id == "" for task in exact_replay_tasks)

    with tempfile.TemporaryDirectory(prefix="statebus-test-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/internal_regression_benchmark.yaml",
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
        for task in load_task_set_bundle("tasks/internal_regression_benchmark.yaml").tasks
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
        for task in load_task_set_bundle("tasks/internal_regression_benchmark.yaml").tasks
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
        for task in load_task_set_bundle("tasks/internal_regression_benchmark.yaml").tasks
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


def test_text_whole_lane_strips_memory_assist_hint_and_guard_detects_marker() -> None:
    evidence = _strip_text_whole_lane_evidence_text(
        "\n".join(
            [
                "[doc-1] Plain customer-visible evidence.",
                "MEMORY_ASSIST_HINT mem-cache-001: hidden assist summary",
                "BENCHMARK_NOTE hidden benchmark metadata",
                "[doc-2] More visible evidence.",
            ]
        )
    )
    assert "Plain customer-visible evidence" in evidence
    assert "More visible evidence" in evidence
    assert "MEMORY_ASSIST_HINT" not in evidence
    assert "BENCHMARK_NOTE" not in evidence

    ctx = Orchestrator.create_context(
        mode="text",
        task_id="whole-lane-marker-001",
        task_group="guard_group",
        task_theme="guard_theme",
        state_root=Path(tempfile.mkdtemp(prefix="statebus-whole-lane-marker-state-")),
        memory_db_path=Path(tempfile.mkdtemp(prefix="statebus-whole-lane-marker-db-")) / "memory.sqlite3",
        embedder=DeterministicEmbeddingProvider(),
        runtime_profile={"transfer_strategy": "text_whole_lane", "handoff_profile": "text_whole_lane"},
    )
    try:
        ctx.results["retrieve"] = StepResult(
            step_id="retrieve",
            success=True,
            payload={"inline_handoff_text": "MEMORY_ASSIST_HINT mem-cache-001: hidden assist summary"},
        )
        ctx.results["execute"] = StepResult(
            step_id="execute",
            success=True,
            payload={},
            output_state_refs=[
                ctx.put_text_state(
                    state_id="whole-lane-marker-001-artifact",
                    kind="TOOL_ARTIFACT",
                    text="Executor plain output.",
                )
            ],
        )
        guard = _whole_lane_text_guard_payload(ctx, "text_whole_lane")["whole_lane_text_guard"]
        assert guard["hidden_field_leak"] is True
        assert "hidden_field_leak" in guard["failed_reasons"]
    finally:
        ctx.memory_store.close()
        ctx.session.cleanup()


def test_text_whole_lane_guard_detects_template_slot_rewrite() -> None:
    ctx = Orchestrator.create_context(
        mode="text",
        task_id="whole-lane-template-slot-001",
        task_group="guard_group",
        task_theme="guard_theme",
        state_root=Path(tempfile.mkdtemp(prefix="statebus-whole-lane-template-state-")),
        memory_db_path=Path(tempfile.mkdtemp(prefix="statebus-whole-lane-template-db-")) / "memory.sqlite3",
        embedder=DeterministicEmbeddingProvider(),
        runtime_profile={"transfer_strategy": "text_whole_lane", "handoff_profile": "text_whole_lane"},
    )
    try:
        ctx.results["retrieve"] = StepResult(
            step_id="retrieve",
            success=True,
            payload={
                "inline_handoff_text": (
                    "Retriever handoff in plain language for the contest headline lane.\n"
                    "The user goal is: triage checkout regression\n"
                    "The visible request is about this situation: checkout confirmations slowed after rollout\n"
                    "The current working hypothesis is db pool saturation.\n"
                    "The first playbook to try is db pool triage.\n"
                )
            },
        )
        ctx.results["execute"] = StepResult(
            step_id="execute",
            success=True,
            payload={},
            output_state_refs=[
                ctx.put_text_state(
                    state_id="whole-lane-template-slot-001-artifact",
                    kind="TOOL_ARTIFACT",
                    text="Executor handoff in plain language.\nRequest: checkout regression\nChosen playbook: db pool triage.\n",
                )
            ],
        )
        guard = _whole_lane_text_guard_payload(ctx, "text_whole_lane")["whole_lane_text_guard"]
        assert guard["template_slot_leak"] is True
        assert "template_slot_leak" in guard["failed_reasons"]
    finally:
        ctx.memory_store.close()
        ctx.session.cleanup()


def test_memory_assist_uses_compact_hint_and_keeps_feature_bundle_fresh() -> None:
    cache_prefix = [
        task
        for task in load_task_set_bundle("tasks/internal_regression_benchmark.yaml").tasks
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
                task_set_path="memory_reuse_v3",
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
        for task in load_task_set_bundle("tasks/internal_regression_benchmark.yaml").tasks
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
                task_set_path="tasks/communication_benchmark.yaml",
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
                task_set_path="tasks/communication_benchmark.yaml",
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
        expected = embedder.embed_text(load_task_set_bundle("tasks/communication_benchmark.yaml").tasks[0].query)
        assert np.allclose(vector, expected)


def test_feature_bundle_state_is_real_msgpack_payload() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-test-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/internal_regression_benchmark.yaml",
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
        assert payload["route_source"] == "lexical_match"
        assert payload["route_confidence"] >= 0.8
        assert payload["route_provenance"] == ["lexical"]
        assert payload["hint_doc_ids"] == []
        assert payload["tool_candidates"][0]["tool_name"] == "tool.cache_invalidation_playbook"
        assert payload["tool_candidates"][0]["source"] == "lexical_match"
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
                task_set_path="tasks/internal_regression_benchmark.yaml",
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


def test_contest_formal_corpus_exposes_eval_labels_but_not_runtime_hints() -> None:
    corpus_docs = load_corpus_docs(REPO_ROOT / "tasks" / "contest_release_regression_corpus.yaml")
    doc = corpus_docs["rr-checkout-incident"]
    assert doc.eval_route_label == "db_pool_saturation"
    assert doc.eval_tool_label == "tool.db_pool_triage"
    assert doc.runtime_route_hint == ""
    assert doc.runtime_tool_name == ""
    assert extract_corpus_feature_hints([doc]) == []
    assert extract_corpus_eval_labels([doc]) == [
        {
            "doc_id": "rr-checkout-incident",
            "eval_route_label": "db_pool_saturation",
            "eval_tool_label": "tool.db_pool_triage",
        }
    ]


def test_memory_policy_controlled_v3_covers_two_families_with_four_policies_each() -> None:
    tasks = list(load_task_set_bundle("memory_policy_controlled_v3").tasks)
    assert {task.task_group for task in tasks} == {"checkout_release_chain", "auth_rotation_chain"}
    by_group: dict[str, list[SampleTask]] = {}
    for task in tasks:
        by_group.setdefault(task.task_group, []).append(task)
    for group_tasks in by_group.values():
        assert len(group_tasks) == 4
        assert [task.runtime_reuse_contract for task in group_tasks] == [
            "reuse_disabled",
            "assist_allowed",
            "validated_replay",
            "exact_replay",
        ]
        assert {task.transfer_strategy for task in group_tasks} == {"state_packet_minimal"}
        assert {task.handoff_profile for task in group_tasks} == {"protocol_minimal_state_packet"}
        assert {task.allowed_modes for task in group_tasks} == {("protocol",)}


def test_tasks_readme_keeps_active_mechanism_memory_and_legacy_boundary_wording() -> None:
    text = (REPO_ROOT / "tasks" / "README.md").read_text(encoding="utf-8")
    assert "typed_state_mechanism_v3" in text
    assert "正式机制 claim 仍优先读 `typed_state_mechanism_v3`" in text
    assert "typed_state_authenticity_v3` 只保留 legacy compatibility surface" in text
    assert "`memory_policy_controlled_v3` 只读 protocol + state_packet_minimal 固定后的 memory policy 单变量归因" in text
    assert "external_text_baseline_audit_v3" in text
    assert "不并入 formal headline" in text


def test_formal_runtime_context_disables_preferred_doc_bias_and_runtime_hints() -> None:
    formal_bundle = load_task_set_bundle("contest_dual_mode_controlled_v3")
    task = formal_bundle.tasks[0]
    metadata = formal_bundle.metadata
    assert metadata.runtime_hint_allowed is False
    assert metadata.formal_structure_clean_retrieval is True
    docs = retrieve_corpus_docs(
        query=task.query,
        tags=list(task.tags),
        task_group=task.task_group,
        task_theme=task.task_theme,
        corpus_doc_ids=task.corpus_doc_ids,
        embedder=DeterministicEmbeddingProvider(),
        corpus_path=REPO_ROOT / "tasks" / "contest_release_regression_corpus.yaml",
        top_k=4,
        allow_preferred_doc_bias=metadata.runtime_hint_allowed,
        formal_structure_clean_retrieval=metadata.formal_structure_clean_retrieval,
    )
    assert all(doc.runtime_route_hint == "" for doc in docs)
    assert all(doc.runtime_tool_name == "" for doc in docs)


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
                "channel_snapshot_hash": "snapshot-ok",
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
                task_set_path="tasks/internal_regression_benchmark.yaml",
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


def test_execute_playbook_step_ignores_tool_candidate_state_on_feature_only_mainline() -> None:
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
                semantic_role="execute",
            ),
            statepool=statepool,
            input_state_refs=[evidence_ref, feature_ref, tool_candidate_ref],
            transfer_strategy="state_ref",
        )
    assert result.payload["tool_name"] == "tool.collect_more_evidence"
    assert result.payload["route"] == "generic_triage"
    assert result.output_state_refs[0].metadata["source_tool_candidates"] == ""


def test_execute_playbook_step_full_rich_audit_can_merge_tool_candidate_state() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-tool-candidate-state-audit-") as tmpdir:
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
                semantic_role="execute",
            ),
            statepool=statepool,
            input_state_refs=[evidence_ref, feature_ref, tool_candidate_ref],
            transfer_strategy="state_ref",
            handoff_profile="protocol_full_rich_audit",
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
                    semantic_role="retrieve",
                ),
                PlanStep(
                    step_id="execute",
                    owner_agent="executor",
                    action="EXECUTE_PLAYBOOK",
                    input_state_refs=[],
                    params={},
                    depends_on=["retrieve"],
                    semantic_role="execute",
                ),
            ],
        )
        with pytest.raises(
            SchemaValidationError,
            match="missing required input kinds|registered contract|schema mismatch",
        ):
            asyncio.run(orchestrator.run_plan(plan, ctx))
        assert exploding.called is False


def test_contest_dual_mode_controlled_v3_runs_matched_text_and_protocol_pairs() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-transfer-lane-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="contest_dual_mode_controlled_v3",
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
    transfer_tasks = list(load_task_set_bundle("contest_dual_mode_controlled_v3").tasks)
    assert transfer_tasks
    protocol_transfer_ids = {
        task.task_id
        for task in transfer_tasks
        if task.benchmark_lane == "state_transfer" and task.supports_mode("protocol")
    }
    for task in transfer_tasks:
        if task.benchmark_lane != "state_transfer":
            continue
        if task.supports_mode("text"):
            assert task.task_id in text_tasks
            assert text_tasks[task.task_id]["transfer_strategy"] == "text_strict_pure_lane"
        if task.supports_mode("protocol"):
            assert task.task_id in protocol_tasks
            assert protocol_tasks[task.task_id]["benchmark_lane"] == "state_transfer"
            assert protocol_tasks[task.task_id]["transfer_strategy"] == "state_packet_minimal"
    assert protocol_transfer_ids == set(protocol_tasks)
    summary = result["summary"]
    assert int(summary["text"]["run_failure_count"]) == 0
    assert int(summary["protocol"]["run_failure_count"]) == 0


def test_contest_dual_mode_controlled_v3_pack_has_20_pairs_5_families_and_4_buckets() -> None:
    tasks = list(load_task_set_bundle("contest_dual_mode_controlled_v3").tasks)
    assert len(tasks) == 40
    assert len({task.case_id for task in tasks}) == 20
    assert len({task.task_theme for task in tasks}) == 5
    assert {task.complexity_bucket for task in tasks} == {
        "simple",
        "distractor",
        "ambiguous",
        "reusable",
    }
    assert {task.summary_contract for task in tasks} == {"actions_plus_evidence"}
    assert all(len(task.acceptable_routes) >= 2 for task in tasks if task.complexity_bucket in {"simple", "distractor", "ambiguous", "reusable"})
    assert any(len(task.acceptable_tools) >= 2 for task in tasks)
    assert {task.thickness_setting for task in tasks} == {"S1", "S2"}
    assert all(
        task.required_plan_semantic_roles == ("retrieve", "validate", "execute", "summarize")
        for task in tasks
    )
    assert all(task.reasoning_hops_min >= 2 for task in tasks)
    assert all(task.abstention_boundary for task in tasks)


def test_contest_dual_mode_controlled_v3_queries_avoid_direct_route_leak_tokens() -> None:
    tasks = list(load_task_set_bundle("contest_dual_mode_controlled_v3").tasks)
    banned_tokens = (
        "db_pool",
        "sql wait",
        "jwks",
        "issuer mismatch",
        "rate limit",
        "aggregate invalidation",
        "replica lag",
        "retry storm",
        "queue depth",
        "pool cap",
    )
    for task in tasks:
        if task.complexity_bucket not in {"simple", "reusable"}:
            continue
        lowered = task.query.lower()
        assert all(token not in lowered for token in banned_tokens), task.task_id


def test_contest_release_regression_corpus_keeps_formal_topology_per_family() -> None:
    corpus_docs = load_corpus_docs(REPO_ROOT / "tasks" / "contest_release_regression_corpus.yaml")
    required_suffixes = {"incident", "metrics", "logs", "scope"}
    required_cross_or_anchor = {
        "checkout": {"config", "worker-false", "reuse", "ambiguous"},
        "auth": {"rotation", "rate-limit-false", "reuse", "ambiguous"},
        "cache": {"flag-diff", "replica-false", "reuse", "ambiguous"},
        "billing": {"runbook", "db-false", "reuse", "ambiguous"},
        "deploy": {"config", "worker-false", "reuse", "ambiguous"},
    }
    by_family: dict[str, set[str]] = {}
    for doc_id in corpus_docs:
        family = doc_id.split("-")[1]
        suffix = doc_id.split("-", 2)[2]
        by_family.setdefault(family, set()).add(suffix)
    for family, suffixes in by_family.items():
        assert required_suffixes.issubset(suffixes), family
        assert required_cross_or_anchor[family].issubset(suffixes), family


def test_contest_dual_mode_controlled_v3_formal_cases_expose_route_and_tool_branching() -> None:
    tasks = list(load_task_set_bundle("contest_dual_mode_controlled_v3").tasks)
    by_id = {task.task_id: task for task in tasks}

    checkout_ambiguous = by_id["rr-checkout-ambiguous-protocol-001"]
    assert set(checkout_ambiguous.acceptable_routes) == {
        "db_pool_saturation",
        "worker_queue_starvation",
    }
    assert set(checkout_ambiguous.acceptable_tools) == {
        "tool.db_pool_triage",
        "tool.db_query_hotfix",
        "tool.worker_queue_triage",
    }

    auth_distractor = by_id["rr-auth-distractor-protocol-001"]
    assert set(auth_distractor.acceptable_routes) == {
        "auth_session_drift",
        "auth_rate_limit",
    }
    assert set(auth_distractor.acceptable_tools) == {
        "tool.auth_session_repair",
        "tool.auth_jwks_refresh",
        "tool.auth_rate_limit_triage",
    }

    cache_reusable = by_id["rr-cache-replay_reusable-protocol-001"]
    assert set(cache_reusable.acceptable_tools) == {
        "tool.cache_invalidation_playbook",
        "tool.cache_hook_repair",
        "tool.replica_stale_read_triage",
        "tool.collect_more_evidence",
    }
    assert cache_reusable.required_prior_case_ids == ("rr-cache-clean",)
    assert cache_reusable.required_prior_rejections == ("cache_replica_stale_read",)

    billing_reusable = by_id["rr-billing-replay_reusable-protocol-001"]
    assert set(billing_reusable.acceptable_tools) == {
        "tool.worker_queue_triage",
        "tool.retry_storm_relief",
        "tool.db_pool_triage",
        "tool.collect_more_evidence",
    }
    assert billing_reusable.required_prior_case_ids == ("rr-billing-clean",)
    assert billing_reusable.required_prior_rejections == ("db_pool_saturation",)


def test_contest_dual_mode_controlled_v3_thickness_settings_match_case_roles() -> None:
    tasks = list(load_task_set_bundle("contest_dual_mode_controlled_v3").tasks)
    by_case_id: dict[str, list[SampleTask]] = {}
    for task in tasks:
        by_case_id.setdefault(task.case_id, []).append(task)
    assert len(by_case_id) == 20
    for case_id, rows in by_case_id.items():
        assert len(rows) == 2
        expected_setting = "S2" if "replay_reusable" in case_id else "S1"
        assert {row.thickness_setting for row in rows} == {expected_setting}
        if expected_setting == "S2":
            assert {row.dependency_depth for row in rows} == {2}
            assert all(row.required_prior_routes for row in rows)
        else:
            assert {row.dependency_depth for row in rows} == {1}
            assert all(not row.required_prior_routes for row in rows)


def test_contest_honest_headline_v1_preserves_thickness_contract() -> None:
    tasks = list(load_task_set_bundle("contest_honest_headline_v1").tasks)
    assert {task.thickness_setting for task in tasks} == {"S1", "S2"}
    assert all(
        task.required_plan_semantic_roles == ("retrieve", "validate", "execute", "summarize")
        for task in tasks
    )
    assert all(task.reasoning_hops_min >= 2 for task in tasks)
    assert all(task.abstention_boundary for task in tasks)


def test_reusable_dependency_gate_requires_prior_case_and_rejection_match() -> None:
    task = next(
        task
        for task in load_task_set_bundle("contest_dual_mode_controlled_v3").tasks
        if task.task_id == "rr-checkout-replay_reusable-protocol-001"
    )
    assert task.complexity_bucket == "reusable"
    orchestrator = Orchestrator(build_sample_agents_with_executor(llm_client=DeterministicLLMClient()))

    with tempfile.TemporaryDirectory(prefix="statebus-reusable-gate-") as tmpdir:
        root = Path(tmpdir)
        ctx = Orchestrator.create_context(
            mode="protocol",
            task_id=task.task_id,
            task_group=task.task_group,
            task_theme=task.task_theme,
            state_root=root / "state",
            memory_db_path=root / "memory.sqlite3",
            embedder=DeterministicEmbeddingProvider(),
            runtime_profile=task.runtime_profile,
            task_corpus_doc_ids=task.corpus_doc_ids,
            task_corpus_path=task.corpus_path,
        )
        with pytest.raises(ValueError, match="prior reusable dependency unsatisfied"):
            asyncio.run(orchestrator.run_task(task, ctx))
        ctx.memory_store.close()
        ctx.session.cleanup()


def test_reusable_dependency_gate_allows_matching_prior_commit() -> None:
    task = next(
        task
        for task in load_task_set_bundle("contest_dual_mode_controlled_v3").tasks
        if task.task_id == "rr-checkout-replay_reusable-protocol-001"
    )
    orchestrator = Orchestrator(build_sample_agents_with_executor(llm_client=DeterministicLLMClient()))

    with tempfile.TemporaryDirectory(prefix="statebus-reusable-gate-match-") as tmpdir:
        root = Path(tmpdir)
        ctx = Orchestrator.create_context(
            mode="protocol",
            task_id=task.task_id,
            task_group=task.task_group,
            task_theme=task.task_theme,
            state_root=root / "state",
            memory_db_path=root / "memory.sqlite3",
            embedder=DeterministicEmbeddingProvider(),
            runtime_profile=task.runtime_profile,
            task_corpus_doc_ids=task.corpus_doc_ids,
            task_corpus_path=task.corpus_path,
        )
        ctx.memory_store.commit_memory(
            MemoryCommit(
                memory_id="mem-prior-clean",
                source_agent_id="runtime",
                source_task_id="rr-checkout-clean",
                task_theme=task.task_theme,
                summary="prior clean task commit",
                tags=["task_commit"],
                evidence_state_ids=[],
                reusable_steps=[],
                confidence=1.0,
                embedding_text="prior clean task commit",
                metadata={
                    "memory_purpose": "task_commit",
                    "memory_layer": "task_commit",
                    "case_id": "rr-checkout-clean",
                    "rejected_routes": ["worker_queue_starvation"],
                },
                evidence_state_refs=[],
                source_session_id="session-commit",
                tier="task_commits",
                commit_ref="commit-prior-clean",
            )
        )
        assert orchestrator._prior_dependency_satisfied(task=task, ctx=ctx) is True
        results = asyncio.run(orchestrator.run_task(task, ctx))
        assert results["summarize"].success is True
        ctx.memory_store.close()
        ctx.session.cleanup()


def test_s2_prior_dependency_changes_admissible_action_boundary() -> None:
    task = next(
        task
        for task in load_task_set_bundle("contest_honest_headline_v1").tasks
        if task.task_id == "rr-checkout-replay_reusable-protocol-001"
    )
    assert task.thickness_setting == "S2"
    assert task.allowed_abstain_tool == "tool.collect_more_evidence"
    orchestrator = Orchestrator(build_sample_agents_with_executor(llm_client=DeterministicLLMClient()))

    def make_ctx(root: Path, *, memory_db_name: str) -> RunContext:
        return Orchestrator.create_context(
            mode="protocol",
            task_id=task.task_id,
            task_group=task.task_group,
            task_theme=task.task_theme,
            state_root=root / memory_db_name / "state",
            memory_db_path=root / f"{memory_db_name}.sqlite3",
            embedder=DeterministicEmbeddingProvider(),
            runtime_profile=task.runtime_profile,
            task_corpus_doc_ids=task.corpus_doc_ids,
            task_corpus_path=task.corpus_path,
        )

    with tempfile.TemporaryDirectory(prefix="statebus-s2-prior-action-") as tmpdir:
        root = Path(tmpdir)

        no_prior_ctx = make_ctx(root, memory_db_name="no-prior")
        no_prior_results = asyncio.run(orchestrator.run_task(task, no_prior_ctx))
        no_prior_validate = no_prior_results["validate"].payload
        no_prior_execute = no_prior_results["execute"].payload
        assert no_prior_validate["s2_prior_dependency_required"] is True
        assert no_prior_validate["s2_prior_dependency_satisfied"] is False
        assert no_prior_validate["validated_tool_name"] == "tool.collect_more_evidence"
        assert no_prior_validate["validated_action_contract"] == "abstain_collect_more_evidence"
        assert no_prior_validate["s2_without_prior_tool_name"] == "tool.collect_more_evidence"
        assert no_prior_validate["s2_prior_dependent_action_change"] is True
        assert no_prior_execute["tool_name"] == "tool.collect_more_evidence"
        assert no_prior_execute["validation_gate_applied"] is True
        assert no_prior_execute["s2_prior_dependency_satisfied"] is False
        no_prior_ctx.memory_store.close()
        no_prior_ctx.session.cleanup()

        with_prior_ctx = make_ctx(root, memory_db_name="with-prior")
        with_prior_ctx.memory_store.commit_memory(
            MemoryCommit(
                memory_id="mem-prior-checkout-clean",
                source_agent_id="runtime",
                source_task_id="rr-checkout-clean-protocol-001",
                task_theme=task.task_theme,
                summary="prior checkout clean task commit",
                tags=["task_commit"],
                evidence_state_ids=[],
                reusable_steps=[],
                confidence=1.0,
                embedding_text="prior checkout clean task commit",
                metadata={
                    "memory_purpose": "task_commit",
                    "memory_layer": "task_commit",
                    "case_id": "rr-checkout-clean",
                    "chosen_route": "db_pool_saturation",
                    "rejected_routes": ["worker_queue_starvation"],
                },
                evidence_state_refs=[],
                source_session_id="session-commit",
                tier="task_commits",
                commit_ref="commit-prior-checkout-clean",
            )
        )
        with_prior_results = asyncio.run(orchestrator.run_task(task, with_prior_ctx))
        with_prior_validate = with_prior_results["validate"].payload
        with_prior_execute = with_prior_results["execute"].payload
        assert with_prior_validate["s2_prior_dependency_required"] is True
        assert with_prior_validate["s2_prior_dependency_satisfied"] is True
        assert with_prior_validate["s2_observed_prior_case_ids"] == ["rr-checkout-clean"]
        assert with_prior_validate["s2_observed_prior_routes"] == ["db_pool_saturation"]
        assert with_prior_validate["s2_observed_prior_rejections"] == ["worker_queue_starvation"]
        assert with_prior_validate["s2_without_prior_tool_name"] == "tool.collect_more_evidence"
        assert with_prior_validate["s2_with_prior_tool_name"] == "tool.db_query_hotfix"
        assert with_prior_validate["validated_tool_name"] == "tool.db_query_hotfix"
        assert with_prior_validate["validated_action_contract"] == "execute_validated_tool"
        assert with_prior_validate["s2_prior_dependent_action_change"] is True
        assert with_prior_execute["tool_name"] == "tool.db_query_hotfix"
        assert with_prior_execute["s2_prior_dependency_satisfied"] is True
        assert with_prior_execute["s2_without_prior_tool_name"] == "tool.collect_more_evidence"
        assert with_prior_execute["s2_with_prior_tool_name"] == "tool.db_query_hotfix"
        assert with_prior_execute["s2_prior_dependent_action_change"] is True
        with_prior_ctx.memory_store.close()
        with_prior_ctx.session.cleanup()


@pytest.mark.parametrize(
    ("case_name", "commit_theme", "metadata", "missing_key", "missing_value"),
    [
        (
            "missing_prior_case",
            None,
            None,
            "s2_missing_prior_case_ids",
            "rr-checkout-clean",
        ),
        (
            "wrong_prior_route",
            "contest_release_checkout_regression",
            {
                "case_id": "rr-checkout-clean",
                "chosen_route": "worker_queue_starvation",
                "rejected_routes": ["worker_queue_starvation"],
            },
            "s2_missing_prior_routes",
            "db_pool_saturation",
        ),
        (
            "missing_required_rejection",
            "contest_release_checkout_regression",
            {
                "case_id": "rr-checkout-clean",
                "chosen_route": "db_pool_saturation",
                "rejected_routes": [],
            },
            "s2_missing_prior_rejections",
            "worker_queue_starvation",
        ),
        (
            "wrong_rejected_route",
            "contest_release_checkout_regression",
            {
                "case_id": "rr-checkout-clean",
                "chosen_route": "db_pool_saturation",
                "rejected_routes": ["auth_rate_limit"],
            },
            "s2_missing_prior_rejections",
            "worker_queue_starvation",
        ),
        (
            "task_family_mismatch",
            "contest_release_auth_rotation",
            {
                "case_id": "rr-checkout-clean",
                "chosen_route": "db_pool_saturation",
                "rejected_routes": ["worker_queue_starvation"],
            },
            "s2_missing_prior_case_ids",
            "rr-checkout-clean",
        ),
    ],
)
def test_s2_negative_controls_do_not_upgrade_without_valid_prior(
    case_name: str,
    commit_theme: str | None,
    metadata: dict[str, object] | None,
    missing_key: str,
    missing_value: str,
) -> None:
    task = next(
        task
        for task in load_task_set_bundle("contest_honest_headline_v1").tasks
        if task.task_id == "rr-checkout-replay_reusable-protocol-001"
    )
    with tempfile.TemporaryDirectory(prefix=f"statebus-s2-negative-{case_name}-") as tmpdir:
        root = Path(tmpdir)
        ctx = Orchestrator.create_context(
            mode="protocol",
            task_id=task.task_id,
            task_group=task.task_group,
            task_theme=task.task_theme,
            state_root=root / "state",
            memory_db_path=root / "memory.sqlite3",
            embedder=DeterministicEmbeddingProvider(),
            runtime_profile=task.runtime_profile,
            task_corpus_doc_ids=task.corpus_doc_ids,
            task_corpus_path=task.corpus_path,
        )
        if metadata is not None and commit_theme is not None:
            ctx.memory_store.commit_memory(
                MemoryCommit(
                    memory_id=f"mem-s2-negative-{case_name}",
                    source_agent_id="runtime",
                    source_task_id=str(metadata.get("case_id", "prior-case")),
                    task_theme=commit_theme,
                    summary=f"S2 negative-control prior for {case_name}",
                    tags=["task_commit"],
                    evidence_state_ids=[],
                    reusable_steps=[],
                    confidence=1.0,
                    embedding_text=f"S2 negative-control prior for {case_name}",
                    metadata={
                        "memory_purpose": "task_commit",
                        "memory_layer": "task_commit",
                        **metadata,
                    },
                    evidence_state_refs=[],
                    source_session_id="session-s2-negative",
                    tier="task_commits",
                    commit_ref=f"commit-s2-negative-{case_name}",
                )
            )

        boundary = _headline_s2_prior_action_boundary(
            task=task,
            ctx=ctx,
            selected_route="db_pool_saturation",
            selected_tool="tool.db_pool_triage",
        )
        assert boundary["s2_prior_dependency_required"] is True
        assert boundary["s2_prior_dependency_satisfied"] is False
        assert boundary["validated_route"] == "generic_triage"
        assert boundary["validated_tool_name"] == "tool.collect_more_evidence"
        assert boundary["validated_action_contract"] == "abstain_collect_more_evidence"
        assert boundary["s2_with_prior_tool_name"] == ""
        assert boundary["s2_prior_dependent_action_change"] is True
        assert missing_value in boundary[missing_key]
        ctx.memory_store.close()
        ctx.session.cleanup()


def test_s2_replay_negative_controls_require_prior_contract_and_replay_artifact() -> None:
    task = next(
        task
        for task in load_task_set_bundle("contest_honest_headline_v1").tasks
        if task.task_id == "rr-checkout-replay_reusable-protocol-001"
    )
    with tempfile.TemporaryDirectory(prefix="statebus-s2-replay-negative-") as tmpdir:
        root = Path(tmpdir)
        ctx = Orchestrator.create_context(
            mode="protocol",
            task_id=task.task_id,
            task_group=task.task_group,
            task_theme=task.task_theme,
            state_root=root / "state",
            memory_db_path=root / "memory.sqlite3",
            embedder=DeterministicEmbeddingProvider(),
            runtime_profile=task.runtime_profile,
            task_corpus_doc_ids=task.corpus_doc_ids,
            task_corpus_path=task.corpus_path,
        )
        replay_ref = ctx.put_text_state(
            state_id="s2-replay-compatible-artifact",
            kind="TOOL_ARTIFACT",
            text="validated checkout remediation artifact",
            metadata={"channel_replay_compatible": True},
        )
        incompatible_ref = ctx.put_text_state(
            state_id="s2-replay-incompatible-artifact",
            kind="TOOL_ARTIFACT",
            text="artifact intentionally excluded from replay restore",
            metadata={"channel_replay_compatible": False},
        )
        non_artifact_ref = ctx.put_replay_eligibility_state(
            state_id="s2-replay-non-artifact",
            replay_eligibility_bundle={
                "schema": "statebus.replay_eligibility_bundle.v1",
                "query": task.query,
                "route": "db_pool_saturation",
            },
        )

        def make_hit(
            *,
            case_id: str = "rr-checkout-clean",
            rejected_routes: list[str] | None = None,
            evidence_refs: list[StateRef] | None = None,
            replay_class: str = "validated_replay",
        ) -> MemoryHit:
            return MemoryHit(
                memory_id=f"mem-s2-replay-{case_id}-{replay_class}",
                confidence=0.95,
                reusable_steps=["execute"],
                evidence_state_refs=list([replay_ref] if evidence_refs is None else evidence_refs),
                task_theme=task.task_theme,
                replay_class=replay_class,
                route="db_pool_saturation",
                route_confidence=0.95,
                route_provenance=["corpus_metadata", "lexical"],
                metadata={
                    "case_id": case_id,
                    "rejected_routes": rejected_routes
                    if rejected_routes is not None
                    else ["worker_queue_starvation"],
                    "feature_route": "db_pool_saturation",
                    "feature_route_confidence": 0.95,
                    "feature_route_provenance": ["corpus_metadata", "lexical"],
                },
            )

        assert Orchestrator._matches_headline_s2_prior_replay(
            hit=make_hit(),
            task=task,
            feature_route="db_pool_saturation",
            reusable_steps={"execute"},
            route_confidence=0.95,
            route_provenance=["corpus_metadata", "lexical"],
        )
        assert not Orchestrator._matches_headline_s2_prior_replay(
            hit=make_hit(case_id="rr-auth-clean"),
            task=task,
            feature_route="db_pool_saturation",
            reusable_steps={"execute"},
            route_confidence=0.95,
            route_provenance=["corpus_metadata", "lexical"],
        )
        assert not Orchestrator._matches_headline_s2_prior_replay(
            hit=make_hit(rejected_routes=["auth_rate_limit"]),
            task=task,
            feature_route="db_pool_saturation",
            reusable_steps={"execute"},
            route_confidence=0.95,
            route_provenance=["corpus_metadata", "lexical"],
        )
        assert not Orchestrator._matches_headline_s2_prior_replay(
            hit=make_hit(evidence_refs=[]),
            task=task,
            feature_route="db_pool_saturation",
            reusable_steps={"execute"},
            route_confidence=0.95,
            route_provenance=["corpus_metadata", "lexical"],
        )
        assert not Orchestrator._matches_headline_s2_prior_replay(
            hit=make_hit(evidence_refs=[incompatible_ref]),
            task=task,
            feature_route="db_pool_saturation",
            reusable_steps={"execute"},
            route_confidence=0.95,
            route_provenance=["corpus_metadata", "lexical"],
        )
        assert not Orchestrator._matches_headline_s2_prior_replay(
            hit=make_hit(evidence_refs=[non_artifact_ref]),
            task=task,
            feature_route="db_pool_saturation",
            reusable_steps={"execute"},
            route_confidence=0.95,
            route_provenance=["corpus_metadata", "lexical"],
        )
        assert not Orchestrator._matches_headline_s2_prior_replay(
            hit=make_hit(replay_class="assist"),
            task=task,
            feature_route="db_pool_saturation",
            reusable_steps={"execute"},
            route_confidence=0.95,
            route_provenance=["corpus_metadata", "lexical"],
        )
        assert not Orchestrator._matches_headline_s2_prior_replay(
            hit=make_hit(),
            task=task,
            feature_route="worker_queue_starvation",
            reusable_steps={"execute"},
            route_confidence=0.95,
            route_provenance=["corpus_metadata", "lexical"],
        )
        assert not Orchestrator._matches_headline_s2_prior_replay(
            hit=make_hit(),
            task=task,
            feature_route="db_pool_saturation",
            reusable_steps={"retrieve"},
            route_confidence=0.95,
            route_provenance=["corpus_metadata", "lexical"],
        )
        ctx.memory_store.close()
        ctx.session.cleanup()


def test_memory_dual_mode_fairness_v3_pack_has_40_rows_5_families_and_4_memory_buckets() -> None:
    tasks = list(load_task_set_bundle("memory_dual_mode_fairness_v3").tasks)
    assert len(tasks) == 40
    assert len({task.case_id for task in tasks}) == 20
    assert len({task.task_theme for task in tasks}) == 5
    assert {task.summary_contract for task in tasks} == {"actions_plus_evidence"}
    assert {task.transfer_strategy for task in tasks} == {"text_whole_lane", "state_packet_minimal"}
    assert {task.runtime_reuse_contract for task in tasks} == {
        "reuse_disabled",
        "assist_allowed",
        "validated_replay",
        "exact_replay",
    }


def test_memory_dual_mode_fairness_v3_report_has_specialized_title_and_stopline() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-memory-dual-fairness-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="memory_dual_mode_fairness_v3",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (Path(tmpdir) / "benchmark_report.md").read_text(encoding="utf-8")
    assert result["manifest"]["task_pack_type"] == "memory_dual_mode_fairness_v3"
    assert "Memory Dual-Mode Fairness V3" in report_text
    assert "This is the dual-mode fairness/object-parity surface." in report_text
    assert "protocol-only replay proof surface" in report_text
    assert "formal_controlled" not in report_text
    assert "open_validation" not in report_text
    assert "feature-only typed state" not in report_text
    assert result["manifest"]["memory_replay_evidence_gate"]["applicable"] is False
    assert "memory_replay_expectation_failed" not in result["manifest"]["withheld_headline_reason"]


def test_memory_dual_mode_fairness_v3_replay_restore_visibility_matches_mode_contract() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-memory-dual-restore-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="memory_dual_mode_fairness_v3",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    text_tasks = result["mode_runs"]["text"][0]["tasks"]
    protocol_tasks = result["mode_runs"]["protocol"][0]["tasks"]
    text_replay_tasks = [
        task for task in text_tasks if task["reuse"]["mode"] in {"skip_execute", "skip_retrieve_execute"}
    ]
    protocol_exact_tasks = [
        task for task in protocol_tasks if task["reuse"]["mode"] == "skip_retrieve_execute"
    ]
    for task in text_replay_tasks:
        visibility = task["memory_restore_visibility"]
        assert visibility["typed_restore_visible"] is False
        assert visibility["restore_compatible_with_mode"] is True
        assert visibility["forbidden_restored_kinds"] == []
        assert visibility["restored_kinds"] == ["TOOL_ARTIFACT"]
    for task in protocol_exact_tasks:
        visibility = task["memory_restore_visibility"]
        assert visibility["restore_compatible_with_mode"] is True
        assert visibility["forbidden_restored_kinds"] == []
        assert set(visibility["restored_kinds"]) == {
            "DENSE_EVIDENCE",
            "EXECUTOR_DECISION_PACKET",
            "TOOL_ARTIFACT",
        }


def test_memory_dual_mode_fairness_v3_skip_execute_replay_persists_executor_input_refs() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-memory-dual-skip-execute-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="memory_dual_mode_fairness_v3",
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    protocol_tasks = result["mode_runs"]["protocol"][0]["tasks"]
    skip_execute_tasks = [task for task in protocol_tasks if task["reuse"]["mode"] == "skip_execute"]
    assert skip_execute_tasks
    for task in skip_execute_tasks:
        kinds = task["transfer_truth_audit"]["executor_input_kinds"]
        assert kinds == ["DENSE_EVIDENCE", "EXECUTOR_DECISION_PACKET"]


def test_replay_restore_allowlist_respects_text_and_protocol_minimal_contracts() -> None:
    orchestrator = Orchestrator(build_sample_agents_with_executor(llm_client=DeterministicLLMClient()))
    text_ctx = Orchestrator.create_context(
        mode="text",
        task_id="restore-text-001",
        task_group="restore_group",
        task_theme="contest_release_checkout_regression",
        state_root=Path(tempfile.mkdtemp(prefix="statebus-restore-text-state-")),
        memory_db_path=Path(tempfile.mkdtemp(prefix="statebus-restore-text-db-")) / "memory.sqlite3",
        embedder=DeterministicEmbeddingProvider(),
        runtime_profile={"transfer_strategy": "text_whole_lane", "handoff_profile": "text_whole_lane"},
    )
    protocol_ctx = Orchestrator.create_context(
        mode="protocol",
        task_id="restore-protocol-001",
        task_group="restore_group",
        task_theme="contest_release_checkout_regression",
        state_root=Path(tempfile.mkdtemp(prefix="statebus-restore-proto-state-")),
        memory_db_path=Path(tempfile.mkdtemp(prefix="statebus-restore-proto-db-")) / "memory.sqlite3",
        embedder=DeterministicEmbeddingProvider(),
        runtime_profile={
            "transfer_strategy": "state_packet_minimal",
            "handoff_profile": "protocol_minimal_state_packet",
        },
    )
    try:
        assert orchestrator._replay_restore_kind_allowed(
            ctx=text_ctx,
            replay_mode="skip_execute",
            replay_step_id="execute",
            source_kind="TOOL_ARTIFACT",
        ) is True
        assert orchestrator._replay_restore_kind_allowed(
            ctx=text_ctx,
            replay_mode="skip_retrieve_execute",
            replay_step_id="retrieve",
            source_kind="FEATURE_BUNDLE",
        ) is False
        assert orchestrator._replay_restore_kind_allowed(
            ctx=protocol_ctx,
            replay_mode="skip_retrieve_execute",
            replay_step_id="retrieve",
            source_kind="DENSE_EVIDENCE",
        ) is True
        assert orchestrator._replay_restore_kind_allowed(
            ctx=protocol_ctx,
            replay_mode="skip_retrieve_execute",
            replay_step_id="retrieve",
            source_kind="EXECUTOR_DECISION_PACKET",
        ) is True
        assert orchestrator._replay_restore_kind_allowed(
            ctx=protocol_ctx,
            replay_mode="skip_retrieve_execute",
            replay_step_id="retrieve",
            source_kind="FEATURE_BUNDLE",
        ) is False
    finally:
        text_ctx.memory_store.close()
        text_ctx.session.cleanup()
        protocol_ctx.memory_store.close()
        protocol_ctx.session.cleanup()


def test_executor_decision_packet_is_replay_compatible_for_state_packet_minimal_restore() -> None:
    registry = default_state_contract_registry()
    ctx = Orchestrator.create_context(
        mode="protocol",
        task_id="replay-contract-001",
        task_group="restore_group",
        task_theme="contest_release_checkout_regression",
        state_root=Path(tempfile.mkdtemp(prefix="statebus-replay-contract-state-")),
        memory_db_path=Path(tempfile.mkdtemp(prefix="statebus-replay-contract-db-")) / "memory.sqlite3",
        embedder=DeterministicEmbeddingProvider(),
        runtime_profile={
            "transfer_strategy": "state_packet_minimal",
            "handoff_profile": "protocol_minimal_state_packet",
        },
    )
    try:
        packet = {
            "schema": "statebus.executor_decision_packet.v1",
            "query": "checkout release 17.4 canary shows connection pool waits",
            "route": "db_pool_saturation",
            "tool_name": "tool.db_pool_triage",
            "route_source": "hint_consensus",
            "route_confidence": 0.91,
            "route_provenance": ["corpus_metadata", "lexical"],
            "matched_signals": ["connection pool"],
            "matched_tags": ["database"],
            "match_score": 9,
            "hint_doc_ids": ["rr-checkout-incident"],
            "hint_route": "db_pool_saturation",
            "hint_tool_name": "tool.db_pool_triage",
            "tool_candidates": [{"tool_name": "tool.db_pool_triage", "route": "db_pool_saturation", "score": 9}],
            "retrieved_doc_ids": ["rr-checkout-incident"],
            "feature_evidence_sha256": "a" * 64,
            "feature_fresh_evidence_sha256": "b" * 64,
        }
        ref = ctx.put_executor_decision_state(
            state_id="replay-contract-001-decision",
            decision_packet=packet,
            metadata={
                "query": packet["query"],
                "transfer_strategy": "state_packet_minimal",
                "retrieved_doc_ids": packet["retrieved_doc_ids"],
                "feature_route": packet["route"],
                "feature_route_source": packet["route_source"],
                "feature_route_confidence": packet["route_confidence"],
                "feature_fresh_evidence_sha256": packet["feature_fresh_evidence_sha256"],
            },
        )
        contract = registry.validate_state_ref(
            ref,
            producer_agent="retriever",
            consumer_agent="executor",
            require_replay_compatible=True,
            statepool=ctx.statepool,
        )
        assert contract.kind == "EXECUTOR_DECISION_PACKET"
        assert contract.replay_compatible is True
    finally:
        ctx.memory_store.close()
        ctx.session.cleanup()


def test_executor_decision_packet_requires_non_empty_route_provenance() -> None:
    with pytest.raises(ValueError, match="non-empty route_provenance"):
        executor_runtime._validate_executor_decision_packet(
            packet={
                "route": "db_pool_saturation",
                "tool_name": "tool.db_pool_triage",
                "route_source": "hint_consensus",
                "route_confidence": 0.91,
                "route_provenance": [],
                "tool_candidates": [
                    {
                        "tool_name": "tool.db_pool_triage",
                        "route": "db_pool_saturation",
                        "score": 9,
                        "matched_signals": ["connection pool"],
                        "matched_tags": ["database"],
                        "source": "hint_consensus",
                    }
                ],
                "retrieved_doc_ids": ["rr-checkout-incident"],
                "matched_signals": ["connection pool"],
                "feature_fresh_evidence_sha256": "b" * 64,
            }
        )


def test_executor_decision_packet_override_mode_requires_audit_override_provenance() -> None:
    ctx = Orchestrator.create_context(
        mode="protocol",
        task_id="audit-override-contract-001",
        task_group="typed_state_consumer_sensitivity_checkout",
        task_theme="contest_release_checkout_regression",
        state_root=Path(tempfile.mkdtemp(prefix="statebus-audit-override-state-")),
        memory_db_path=Path(tempfile.mkdtemp(prefix="statebus-audit-override-db-")) / "memory.sqlite3",
        embedder=DeterministicEmbeddingProvider(),
        runtime_profile={
            "transfer_strategy": "state_packet_minimal",
            "handoff_profile": "protocol_minimal_state_packet",
        },
    )
    try:
        ref = ctx.put_executor_decision_state(
            state_id="audit-override-contract-001-decision",
            decision_packet={
                "schema": "statebus.executor_decision_packet.v1",
                "query": "checkout release canary shows slow p95 and queueing",
                "route": "worker_queue_starvation",
                "tool_name": "tool.worker_queue_triage",
                "route_source": "hint_consensus",
                "route_confidence": 0.62,
                "route_provenance": ["corpus_metadata", "lexical"],
                "matched_signals": ["worker backlog"],
                "matched_tags": ["queue"],
                "match_score": 7,
                "tool_candidates": [
                    {
                        "tool_name": "tool.worker_queue_triage",
                        "route": "worker_queue_starvation",
                        "score": 7,
                        "matched_signals": ["worker backlog"],
                        "matched_tags": ["queue"],
                        "source": "audit_override",
                    }
                ],
                "retrieved_doc_ids": ["rr-billing-incident"],
                "feature_fresh_evidence_sha256": "b" * 64,
                "audit_mode": "override_mismatch_abstain",
            },
            metadata={
                "feature_route": "db_pool_saturation",
                "feature_route_source": "hint_consensus",
                "feature_route_confidence": 0.91,
                "feature_fresh_evidence_sha256": "b" * 64,
                "audit_decision_packet_mode": "override_mismatch_abstain",
            },
        )
        packet = ctx.get_executor_decision_state(ref)
        with pytest.raises(ValueError, match="audit_override provenance"):
            executor_runtime._validate_executor_decision_packet(packet=packet, ref=ref)
    finally:
        ctx.memory_store.close()
        ctx.session.cleanup()


def test_object_parity_gate_fails_when_text_restore_visibility_is_incompatible() -> None:
    from eval.runner import _object_parity_gate

    gate = _object_parity_gate(
        pack_type="memory_dual_mode_fairness_v3",
        task_rows_by_mode={
            "text": [
                {
                    "task_id": "bad-text-restore-001",
                    "status": "completed",
                    "summary_contract": "actions_plus_evidence",
                    "memory_restore_visibility": {
                        "typed_restore_visible": True,
                        "restore_compatible_with_mode": False,
                        "forbidden_restored_kinds": ["FEATURE_BUNDLE"],
                    },
                }
            ],
            "protocol": [
                {
                    "task_id": "ok-protocol-001",
                    "status": "completed",
                    "summary_contract": "actions_plus_evidence",
                    "transfer_truth_audit": {
                        "executor_input_kinds": ["DENSE_EVIDENCE", "EXECUTOR_DECISION_PACKET"],
                    },
                }
            ],
        },
        text_guard_audit={
            "hidden_field_leak_rate": 0.0,
            "summarizer_typed_visibility_rate": 0.0,
        },
    )
    assert gate["text_memory_restore_compat_ok"] is False
    assert gate["passed"] is False
    assert "bad-text-restore-001" in gate["failing_task_ids"]


def test_memory_replay_evidence_gate_fails_on_expected_replay_mismatch() -> None:
    from eval.runner import _memory_replay_evidence_gate

    gate = _memory_replay_evidence_gate(
        pack_type="memory_policy_controlled_v3",
        task_rows_by_mode={
            "protocol": [
                {
                    "task_id": "memory-policy-bad-001",
                    "expected_reuse_mode": "skip_execute",
                    "status": "completed",
                    "reuse": {"mode": "assist"},
                },
                {
                    "task_id": "memory-policy-ok-001",
                    "expected_reuse_mode": "skip_retrieve_execute",
                    "status": "completed",
                    "reuse": {"mode": "skip_retrieve_execute"},
                },
            ],
        },
    )
    assert gate["applicable"] is True
    assert gate["passed"] is False
    assert gate["expected_rows"] == 2
    assert gate["matched_rows"] == 1
    assert gate["failing_task_ids"] == ["memory-policy-bad-001"]


def test_memory_replay_evidence_gate_fails_on_incomplete_expected_replay_row() -> None:
    from eval.runner import _memory_replay_evidence_gate

    gate = _memory_replay_evidence_gate(
        pack_type="memory_reuse_v3",
        task_rows_by_mode={
            "protocol": [
                {
                    "task_id": "memory-reuse-failed-001",
                    "status": "failed",
                    "expected_reuse_mode": "skip_retrieve_execute",
                    "reuse": {"mode": "none"},
                }
            ],
        },
    )
    assert gate["applicable"] is True
    assert gate["passed"] is False
    assert gate["expected_rows"] == 1
    assert gate["matched_rows"] == 0
    assert gate["failing_task_ids"] == ["memory-reuse-failed-001"]


@pytest.mark.parametrize("task_set_path", ("memory_reuse_v3", "typed_state_mechanism_v3"))
def test_protocol_only_packs_do_not_withhold_on_absent_text_guard(task_set_path: str) -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-protocol-only-guard-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path=task_set_path,
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )

    withheld = str(result["manifest"].get("withheld_headline_reason", ""))
    assert "whole_lane_text_guard_incomplete" not in withheld
    assert result["manifest"]["task_mode_counts"].get("text", 0) == 0


def test_headline_gates_split_memory_replay_from_generic_state_transfer_flag() -> None:
    from eval.runner import _build_headline_gates

    gates = _build_headline_gates(
        pack_type="memory_policy_controlled_v3",
        withheld_reasons=[],
        formal_stability_gate={"passed": False},
        object_parity_gate={"passed": False},
        memory_replay_evidence_gate={"applicable": True, "passed": True, "expected_rows": 2, "matched_rows": 2},
        contest_formal_coverage_gate={"passed": False},
    )
    assert gates["communication_gate"]["applicable"] is False
    assert gates["memory_replay_gate"]["applicable"] is True
    assert gates["memory_replay_gate"]["allowed"] is True
    assert gates["memory_replay_gate"]["memory_replay_evidence_gate"]["passed"] is True


def test_active_docs_reference_memory_dual_mode_fairness_v3_and_drop_old_formal_wording() -> None:
    readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    tasks_readme_text = (REPO_ROOT / "tasks" / "README.md").read_text(encoding="utf-8")
    master_text = (REPO_ROOT / "docs" / "reports" / "MASTER_PRESENTATION_GUIDE.md").read_text(encoding="utf-8")
    task_design_text = (
        REPO_ROOT / "docs" / "reports" / "task_design_and_mode_comparison.md"
    ).read_text(encoding="utf-8")

    for text in (readme_text, tasks_readme_text, master_text, task_design_text):
        assert "memory_dual_mode_fairness_v3" in text
        assert "memory_policy_controlled_v3" in text
        assert "typed_state_mechanism_v3" in text
        assert "external_text_baseline_audit_v3" in text

    assert "protocol_feature_only_typed_state" not in readme_text
    assert "当前唯一正式 benchmark surface" not in readme_text
    assert "当前正式 benchmark surface 只保留 6 个 v3 对象" not in task_design_text
    assert "whole-lane pure text vs rich typed-state protocol" not in task_design_text
    assert "只让通信格式不同" not in master_text
    assert "单一通信载体变量对照" in master_text
    assert "external traditional baseline" not in readme_text


def test_benchmark_supports_shared_memory_statepool_backend() -> None:
    try:
        from multiprocessing import shared_memory as _shm
        _shm.SharedMemory(name="statebus_test_probe", create=True, size=64).unlink()
    except Exception:
        pytest.skip("shared_memory not available")


def test_inline_text_support_removes_executor_facing_state_refs() -> None:
    forbidden_tokens = (
        "Route:",
        "Tool:",
        "route_source",
        "tool_candidates",
        "matched_signals",
        "matched_tags",
    )
    with tempfile.TemporaryDirectory(prefix="statebus-inline-support-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/state_transfer_inline_text_support_benchmark.yaml",
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        tasks = {task["task_id"]: task for task in result["mode_runs"]["protocol"][0]["tasks"]}
        for task_id in (
            "transfer-cache-inline-text-001",
            "transfer-latency-inline-text-001",
            "transfer-session-inline-text-001",
        ):
            task = tasks[task_id]
            retrieve_payload = task["results"]["retrieve"]["payload"]
            execute_payload = task["results"]["execute"]["payload"]
            assert retrieve_payload["transfer_brief_state_id"] == ""
            assert retrieve_payload["inline_handoff_text"]
            assert task["pure_text_guard"]["passed"] is True
            assert "TOOL_ARTIFACT" not in task["pure_text_guard"]["executor_input_kinds"]
            assert task["pure_text_guard"]["forbidden_ref_kinds"] == []
            brief_text = retrieve_payload["inline_handoff_text"]
            for token in forbidden_tokens:
                assert token not in brief_text
            rebuilt = build_feature_bundle(
                query=retrieve_payload["query"],
                evidence_text=brief_text,
                tags=[],
                reuse_signature="natural_handoff_transfer",
                reused_memory=False,
                registry=default_tool_registry(),
            )
            assert rebuilt["tool_name"].startswith("tool.")
            assert rebuilt["route"]
            assert execute_payload["tool_name"].startswith("tool.")
            assert execute_payload["route"]
            assert execute_payload["tool_name"] != ""
            assert execute_payload["route"] != ""


def test_text_definition_audit_v3_enforces_inline_executor_boundary() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-strict-pure-text-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="text_definition_audit_v3",
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (Path(tmpdir) / "benchmark_report.md").read_text(encoding="utf-8")
    assert result["manifest"]["task_pack_type"] == "text_definition_audit_v3"
    assert result["manifest"]["support_evidence_only"] is False
    assert "Text Definition Audit V3" in report_text
    assert "- Modes: `protocol`" in report_text
    assert "- Modes: `text, protocol`" not in report_text
    assert "executor_handoff_text_bytes" in report_text
    assert result["manifest"]["artifact_expectation_counts"]["route"] == 40
    assert result["manifest"]["artifact_expectation_counts"]["tool_name"] == 40
    assert result["manifest"]["artifact_expectation_task_count"] == 40
    assert int(result["summary"]["protocol"]["run_failure_count"]) == 0
    protocol_tasks = result["mode_runs"]["protocol"][0]["tasks"]
    assert len(protocol_tasks) == 40
    inline_tasks = [
        task for task in protocol_tasks if task["transfer_strategy"] == "inline_text_handoff"
    ]
    state_packet_tasks = [
        task for task in protocol_tasks if task["transfer_strategy"] == "state_packet_minimal"
    ]
    assert len(inline_tasks) == len(state_packet_tasks) == 20
    for task in inline_tasks:
        guard = task["pure_text_guard"]
        retrieve_payload = task["results"]["retrieve"]["payload"]
        execute_payload = task["results"]["execute"]["payload"]
        assert guard["enabled"] is True
        assert guard["guard_scope"] == "executor_boundary"
        assert retrieve_payload["transfer_brief_state_id"] == ""
        assert retrieve_payload["inline_handoff_text"]
        assert execute_payload["tool_name"].startswith("tool.")
        assert task["artifact_misfire"]["has_expectations"] is True
        assert task["artifact_misfire"]["fields"]["route"]["enabled"] is True
        assert task["artifact_misfire"]["fields"]["tool_name"]["enabled"] is True
    for task in state_packet_tasks:
        assert task["pure_text_guard"]["enabled"] is False
        assert task["results"]["execute"]["payload"]["tool_name"].startswith("tool.")
        assert task["artifact_misfire"]["has_expectations"] is True


def test_text_whole_lane_guard_passes_for_text_mode_task() -> None:
    base_task = load_task_set_bundle("contest_dual_mode_controlled_v3").tasks[0]
    task = replace(base_task, transfer_strategy="text_whole_lane", handoff_profile="text_whole_lane")
    orchestrator = Orchestrator(build_sample_agents_with_executor(llm_client=DeterministicLLMClient()))
    with tempfile.TemporaryDirectory(prefix="statebus-text-whole-lane-guard-") as tmpdir:
        root = Path(tmpdir)
        ctx = Orchestrator.create_context(
            mode="text",
            task_id=task.task_id,
            task_group=task.task_group,
            task_theme=task.task_theme,
            state_root=root / "state",
            memory_db_path=root / "memory.sqlite3",
            embedder=DeterministicEmbeddingProvider(),
            runtime_profile=task.runtime_profile,
        )
        asyncio.run(orchestrator.run_task(task, ctx))
        guard = _whole_lane_text_guard_payload(ctx, "text_whole_lane")["whole_lane_text_guard"]
        assert guard["enabled"] is True
        assert guard["forbidden_ref_kinds"] == []
        assert guard["summarizer_input_kinds"] == ["TOOL_ARTIFACT"]
        assert guard["hidden_field_leak"] is False
        assert guard["template_slot_leak"] is False
        assert guard["summarizer_typed_visibility"] is False
        assert guard["failed_reasons"] == []


def test_text_whole_lane_headline_handoff_avoids_structural_slot_markers() -> None:
    handoff = _build_text_whole_lane_retriever_handoff(
        goal="triage checkout regression and recommend the first action",
        query="checkout confirmations slowed after rollout",
        evidence_text="Visible release evidence only.",
        route="db_pool_saturation",
        tool_name="tool.db_pool_triage",
        route_confidence=0.91,
        retrieved_doc_ids=["rr-checkout-incident", "rr-checkout-scope"],
    )
    assert "Route:" not in handoff
    assert "Tool:" not in handoff
    assert "Route source:" not in handoff
    assert "Route confidence:" not in handoff
    assert "Retrieved docs:" not in handoff
    assert "route field" in handoff
    assert "tool field" in handoff
    assert "structured packet" in handoff
    assert "The visible request concerns checkout confirmations slowed after rollout." in handoff
    assert "db pool saturation is the leading explanation so far" in handoff
    assert "Starting with db pool triage is the safest next step for now." in handoff


def test_text_whole_lane_executor_recovers_route_and_tool_from_headline_handoff() -> None:
    bundle = executor_runtime._feature_bundle_from_text_whole_lane_handoff(
        query_text="checkout confirmations slowed after rollout",
        evidence_text="Visible release evidence only.",
        handoff_text=(
            "Retriever handoff in plain language for the contest headline lane.\n"
            "The user is trying to triage checkout regression and recommend the first action.\n"
            "The visible request concerns checkout confirmations slowed after rollout.\n"
            "Based on the visible evidence, db pool saturation is the leading explanation so far, and the strongest competing explanation has not overtaken it.\n"
            "Starting with db pool triage is the safest next step for now.\n"
            "This read stays at high confidence and depends only on rr-checkout-incident, rr-checkout-scope.\n"
            "Stay inside the visible evidence below and do not rely on any hidden structured packet, route field, tool field, or retrieval shortcut.\n"
            "The visible evidence appears below.\n"
            "Visible release evidence only.\n"
        ),
        registry=default_tool_registry(),
    )
    assert bundle["route"] == "db_pool_saturation"
    assert bundle["tool_name"] == "tool.db_pool_triage"
    assert bundle["route_source"] == "headline_natural_language_handoff"


def test_text_whole_lane_executor_helper_disabled_does_not_recover_route_or_tool() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-text-helper-off-exec-") as tmpdir:
        pool = StatePool(Path(tmpdir) / "state")
        result = execute_playbook_step(
            task_id="audit-text-helper-off",
            task_theme="contest_release_checkout_regression",
            step=PlanStep(
                step_id="execute",
                owner_agent="executor",
                action="EXECUTE_PLAYBOOK",
                input_state_refs=[],
                params={
                    "query": "checkout confirmations slowed after rollout",
                    "inline_handoff_text": (
                        "Retriever handoff in plain language for the contest headline lane.\n"
                        "The user is trying to triage checkout regression and recommend the first action.\n"
                        "The visible request concerns checkout confirmations slowed after rollout.\n"
                        "Based on the visible evidence, db pool saturation is the leading explanation so far, and the strongest competing explanation has not overtaken it.\n"
                        "Starting with db pool triage is the safest next step for now.\n"
                        "This read stays at high confidence and depends only on rr-checkout-incident, rr-checkout-scope.\n"
                        "Stay inside the visible evidence below and do not rely on any hidden structured packet, route field, tool field, or retrieval shortcut.\n"
                        "The visible evidence appears below.\n"
                        "Visible release evidence only.\n"
                    ),
                },
                depends_on=["retrieve"],
                semantic_role="execute",
            ),
            statepool=pool,
            input_state_refs=[],
            transfer_strategy="text_whole_lane",
            handoff_profile="text_whole_lane",
            audit_text_helper_disabled=True,
        )
    assert result.success is True
    assert result.payload["route"] == "generic_triage"
    assert result.payload["tool_name"] == "tool.collect_more_evidence"
    assert result.payload["feature_route_source"] == "audit_text_helper_disabled"
    assert result.payload["audit_text_helper_mode"] == "disabled"
    assert result.output_state_refs[0].metadata["audit_text_helper_mode"] == "disabled"


def test_text_helper_ablation_audit_pack_is_audit_only_and_keeps_helper_flag_single_variable() -> None:
    bundle = load_task_set_bundle("text_helper_ablation_audit_v1")
    assert bundle.metadata.public_surface == "audit_only"
    assert bundle.metadata.evidence_tier == "audit_only"
    assert bundle.metadata.single_variable is True
    assert bundle.metadata.variable_axes == ("text_route_tool_recovery_helper",)
    helper_on = [
        task
        for task in bundle.tasks
        if task.supports_mode("text") and task.audit_text_helper_mode == ""
    ]
    helper_off = [
        task
        for task in bundle.tasks
        if task.supports_mode("text") and task.audit_text_helper_mode == "disabled"
    ]
    protocol_controls = [task for task in bundle.tasks if task.supports_mode("protocol")]
    assert len(helper_on) == len(helper_off) == len(protocol_controls) == 2
    assert {task.transfer_strategy for task in helper_on + helper_off} == {"text_whole_lane"}
    assert {task.handoff_profile for task in helper_on + helper_off} == {"text_whole_lane"}
    assert {task.transfer_strategy for task in protocol_controls} == {"state_packet_minimal"}
    assert {task.runtime_profile.audit_text_helper_disabled for task in helper_off} == {True}
    assert {task.runtime_profile.audit_text_helper_disabled for task in helper_on} == {False}


def test_route_corpus_stress_audit_pack_is_audit_only_and_pair_matched() -> None:
    bundle = load_task_set_bundle("route_corpus_stress_audit_v1")
    assert bundle.metadata.public_surface == "audit_only"
    assert bundle.metadata.evidence_tier == "audit_only"
    assert bundle.metadata.single_variable is True
    assert bundle.metadata.variable_axes == ("corpus_evidence_surface",)
    assert len(bundle.tasks) == 4
    by_case: dict[str, list[SampleTask]] = {}
    for task in bundle.tasks:
        by_case.setdefault(task.case_id, []).append(task)
        assert task.plan_source == "yaml"
        assert task.runtime_reuse_contract == "reuse_disabled"
        assert task.complexity_bucket == "ambiguous"
        assert task.required_plan_semantic_roles == (
            "retrieve",
            "validate",
            "execute",
            "summarize",
        )
        assert "stress" in task.tags
    assert set(by_case) == {"stress-auth-ambiguous", "stress-billing-ambiguous"}
    for rows in by_case.values():
        assert {row.allowed_modes for row in rows} == {("text",), ("protocol",)}
        text_row = next(row for row in rows if row.supports_mode("text"))
        protocol_row = next(row for row in rows if row.supports_mode("protocol"))
        assert text_row.query == protocol_row.query
        assert text_row.corpus_doc_ids == protocol_row.corpus_doc_ids
        assert text_row.primary_expected_route == protocol_row.primary_expected_route
        assert text_row.primary_expected_tool == protocol_row.primary_expected_tool
        assert text_row.transfer_strategy == "text_strict_pure_lane"
        assert protocol_row.transfer_strategy == "state_packet_minimal"


def test_contest_dual_mode_controlled_v3_report_uses_current_state_transfer_label() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-formal-controlled-") as tmpdir:
        asyncio.run(
            run_benchmark(
                task_set_path="contest_dual_mode_controlled_v3",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (Path(tmpdir) / "benchmark_report.md").read_text(encoding="utf-8")
    assert "Contest Controlled Composite V3" in report_text
    assert "text_strict_pure_lane" in report_text
    assert "state_packet_minimal" in report_text


def test_text_strict_pure_lane_explicitly_reuses_internal_helper_path_without_memory_prior() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-text-strict-helper-path-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="contest_dual_mode_controlled_v3",
                repeat=1,
                modes=("text",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    task = result["mode_runs"]["text"][0]["tasks"][0]
    retrieve_payload = task["results"]["retrieve"]["payload"]
    observability = task["results"]["retrieve"]["feature_observability"]
    validate_payload = task["results"]["validate"]["payload"]
    execute_payload = task["results"]["execute"]["payload"]

    assert task["transfer_strategy"] == "text_strict_pure_lane"
    assert task["transfer_truth_audit"]["executor_input_kinds"] == []
    assert retrieve_payload["transfer_brief_state_id"]
    assert retrieve_payload["inline_handoff_text"]
    assert retrieve_payload["feature_route_source"] == "lexical_match"
    assert retrieve_payload["memory_assist_ids"] == []
    assert retrieve_payload["memory_prior_applied"] is False
    assert validate_payload["validation_success"] is True
    assert validate_payload["validated_tool_name"] == execute_payload["tool_name"]
    assert observability["matched_signals"]
    assert observability["tool_candidates"]
    assert observability["tool_candidates"][0]["tool_name"] == execute_payload["tool_name"]
    assert observability["tool_candidates"][0]["source"] == "text_brief"
    assert execute_payload["tool_name"].startswith("tool.")
    assert execute_payload["actions"]


def test_planner_support_v3_runs_llm_planner_in_protocol_mode() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-open-planner-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="planner_support_v3",
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (Path(tmpdir) / "benchmark_report.md").read_text(encoding="utf-8")
    assert result["manifest"]["task_pack_type"] == "planner_support_v3"
    assert result["manifest"]["support_evidence_only"] is False
    assert result["manifest"]["formal_secondary_evidence"] is True
    assert result["manifest"]["task_mode_counts"]["protocol"] == 11
    assert result["manifest"]["modes"] == ["protocol"]
    assert "Planner Support V3" in report_text
    assert "yaml_control_admissible_match_rate" in report_text
    assert "llm_plan_admissible_match_rate" in report_text
    assert "text_admissible_match_rate" not in report_text
    assert "protocol_admissible_match_rate" not in report_text
    assert "combined_admissible_match_rate" not in report_text
    assert "- Public surface: `formal_secondary_planner`" in report_text
    assert "- Evidence tier: `formal_secondary`" in report_text
    assert "- Formal structure clean retrieval: `no`" in report_text
    assert "- Plan source default: `yaml`" in report_text
    assert "- Observed planner sources: `llm, yaml`" in report_text
    assert "- Planner one-shot valid rate:" in report_text
    assert "- Planner repair attempts:" in report_text


def test_planner_support_v3_report_uses_row_level_one_shot_rate() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-open-planner-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="planner_support_v3",
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (Path(tmpdir) / "benchmark_report.md").read_text(encoding="utf-8")
    assert "| planner_one_shot_valid_rate | 1.00 |" in report_text
    assert "| planner_repair_attempt_total | 0 |" in report_text
    summary = result["summary"]["protocol"]
    assert int(summary["run_failure_count"]) == 0
    assert len(summary["tasks"]) == 11
    aggregate = summary["aggregate"]
    assert aggregate["planner_llm_request_count"] == 6
    yaml_tasks = [task for task in result["mode_runs"]["protocol"][0]["tasks"] if task["plan_source"] == "yaml"]
    llm_tasks = [task for task in result["mode_runs"]["protocol"][0]["tasks"] if task["plan_source"] == "llm"]
    assert len(yaml_tasks) == 5
    assert len(llm_tasks) == 6
    assert all(task["metrics"]["planner_llm_request_count"] == 0 for task in yaml_tasks)
    yaml_validate_tasks = [task for task in yaml_tasks if "validate" in task["results"]]
    yaml_plain_tasks = [task for task in yaml_tasks if "validate" not in task["results"]]
    assert all(task["metrics"]["planned_step_count"] == 4 for task in yaml_validate_tasks)
    assert all(task["metrics"]["planned_step_count"] == 3 for task in yaml_plain_tasks)
    assert all(task["metrics"]["planner_llm_request_count"] >= 1 for task in llm_tasks)
    four_step_llm_tasks = [task for task in llm_tasks if task["metrics"]["planned_step_count"] == 4]
    assert len(four_step_llm_tasks) >= 2
    assert any("validate" in task["results"] for task in llm_tasks)
    assert aggregate["planned_step_count"] == sum(
        int(task["metrics"]["planned_step_count"])
        for task in result["mode_runs"]["protocol"][0]["tasks"]
    )
    for task in result["mode_runs"]["protocol"][0]["tasks"]:
        assert task["transfer_strategy"] == "state_packet_minimal"
        assert "retrieve" in task["results"]
        assert task["results"]["retrieve"]["success"] is True
        if "validate" in task["results"]:
            assert task["results"]["validate"]["success"] is True
            assert task["results"]["validate"]["payload"]["validated_tool_name"].startswith("tool.")
        assert {"execute", "summarize"}.issubset(task["results"])
        assert task["results"]["execute"]["success"] is True
        assert task["results"]["summarize"]["success"] is True
        assert task["results"]["execute"]["payload"]["tool_name"].startswith("tool.")
    deploy_llm = next(
        task
        for task in result["mode_runs"]["protocol"][0]["tasks"]
        if task["task_id"] == "planner-support-deploy-llm-001"
    )
    assert deploy_llm["metrics"]["planned_step_count"] == 4
    assert "validate" in deploy_llm["results"]
    assert deploy_llm["results"]["validate"]["success"] is True
    assert deploy_llm["results"]["validate"]["payload"]["validated_tool_name"] == "tool.db_pool_triage"
    assert deploy_llm["results"]["validate"]["payload"]["validation_failure_reason"] == ""
    assert "execute" in deploy_llm["results"]
    auth_validate_llm = next(
        task
        for task in result["mode_runs"]["protocol"][0]["tasks"]
        if task["task_id"] == "planner-support-auth-llm-002"
    )
    assert auth_validate_llm["metrics"]["planned_step_count"] == 4
    assert "validate" in auth_validate_llm["results"]
    assert auth_validate_llm["results"]["validate"]["success"] is True
    assert auth_validate_llm["results"]["validate"]["payload"]["validated_tool_name"] == "tool.auth_session_repair"
    assert auth_validate_llm["planner_contract_valid_final"] is True


def test_validate_route_emits_gate_packet_and_execute_requires_successful_validation() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-validate-gate-") as tmpdir:
        pool = StatePool(Path(tmpdir) / "state")
        memory_store = MemoryStore(Path(tmpdir) / "memory.sqlite3", embedder=DeterministicEmbeddingProvider())
        memory_store.init_schema()
        session = RunSession(mode="protocol")
        ctx = RunContext(
            mode="protocol",
            trace_id="validate-test-trace",
            task_id="planner-support-auth-llm-002",
            task_group="planner_support_v3_lane",
            task_theme="contest_release_auth_rotation",
            session=session,
            statepool=pool,
            memory_store=memory_store,
            runtime_profile=RuntimeTaskProfile(transfer_strategy="state_packet_minimal"),
        )
        task = next(
            item
            for item in load_task_set_bundle("planner_support_v3").tasks
            if item.task_id == "planner-support-auth-llm-002"
        )
        ctx.task = task
        retrieve_result = StepResult(
            step_id="retrieve",
            success=True,
            output_state_refs=[
                ctx.put_text_state(
                    state_id="evidence-1",
                    kind="DENSE_EVIDENCE",
                    text="auth issuer mismatch with stale jwks and callback failures",
                    metadata={"query": task.query},
                ),
                ctx.put_executor_decision_state(
                    state_id="decision-1",
                    decision_packet={
                        "route": "auth_session_drift",
                        "tool_name": "tool.auth_session_repair",
                        "route_source": "lexical_match",
                        "route_confidence": 0.82,
                        "route_provenance": ["feature_bundle", "tool_candidates"],
                        "tool_candidates": [
                            {
                                "tool_name": "tool.auth_session_repair",
                                "route": "auth_session_drift",
                                "score": 8,
                                "matched_signals": ["stale jwks", "issuer mismatch"],
                                "matched_tags": ["auth"],
                            }
                        ],
                        "retrieved_doc_ids": ["rr-auth-incident"],
                        "matched_signals": ["stale jwks", "issuer mismatch"],
                        "feature_fresh_evidence_sha256": "abc123",
                    },
                    metadata={
                        "feature_route": "auth_session_drift",
                        "feature_route_source": "lexical_match",
                        "feature_route_confidence": 0.82,
                        "feature_fresh_evidence_sha256": "abc123",
                    },
                ),
            ],
            payload={
                "feature_route": "auth_session_drift",
                "feature_tool_name": "tool.auth_session_repair",
                "feature_route_source": "lexical_match",
                "feature_route_confidence": 0.82,
                "retrieved_doc_ids": ["rr-auth-incident"],
            },
        )
        ctx.results["retrieve"] = retrieve_result
        ctx.set_step_role("retrieve", "retrieve")
        ctx.set_step_input_refs("validate", list(retrieve_result.output_state_refs))
        validate_step = PlanStep(
            step_id="validate",
            semantic_role="validate",
            owner_agent="executor",
            action="VALIDATE_ROUTE",
            input_state_refs=[],
            params={},
            depends_on=["retrieve"],
        )
        executor = build_sample_agents_with_executor()["executor"]
        validate_result = asyncio.run(executor.execute_step(validate_step, ctx))
        assert validate_result.success is True
        assert validate_result.output_state_refs[0].kind == "VALIDATION_GATE_PACKET"
        assert validate_result.payload["validated_action_contract"] == "execute_validated_tool"
        assert validate_result.payload["validated_tool_candidates"]
        ctx.results["validate"] = validate_result
        ctx.set_step_role("validate", "validate")
        execute_step = PlanStep(
            step_id="execute",
            semantic_role="execute",
            owner_agent="executor",
            action="EXECUTE_PLAYBOOK",
            input_state_refs=[],
            params={},
            depends_on=["retrieve", "validate"],
        )
        execute_refs = list(retrieve_result.output_state_refs) + list(validate_result.output_state_refs)
        ctx.set_step_input_refs("execute", execute_refs)
        execute_result = asyncio.run(executor.execute_step(execute_step, ctx))
        assert execute_result.success is True
        failed_validation_ref = ctx.put_validation_gate_state(
            state_id="validation-failed",
            validation_packet={
                "validated_route": "generic_triage",
                "validated_tool_name": "",
                "route_source": "lexical_match",
                "route_confidence": 0.0,
                "retrieved_doc_ids": [],
                "validation_checks": [],
                "validation_success": False,
                "validation_failure_reason": "validate route confidence below threshold",
            },
            metadata={
                "validated_route": "generic_triage",
                "validated_tool_name": "",
                "route_confidence": 0.0,
                "validation_success": False,
            },
        )
        ctx.set_step_input_refs("execute", list(retrieve_result.output_state_refs) + [failed_validation_ref])
        with pytest.raises(ValueError, match="validate route confidence below threshold"):
            asyncio.run(executor.execute_step(execute_step, ctx))
        assert ctx.metrics.expected_gate_block_count == 1
        assert ctx.metrics.true_invariant_violation_count == 0


def test_execute_consumes_validation_gate_as_authoritative_action_decision() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-validated-execute-decision-") as tmpdir:
        pool = StatePool(Path(tmpdir) / "state")
        memory_store = MemoryStore(Path(tmpdir) / "memory.sqlite3", embedder=DeterministicEmbeddingProvider())
        memory_store.init_schema()
        session = RunSession(mode="protocol")
        ctx = RunContext(
            mode="protocol",
            trace_id="validated-execute-decision",
            task_id="rr-checkout-clean-protocol-001",
            task_group="contest_honest_headline",
            task_theme="contest_release_checkout_regression",
            session=session,
            statepool=pool,
            memory_store=memory_store,
            runtime_profile=RuntimeTaskProfile(transfer_strategy="state_packet_minimal"),
        )
        ctx.task = next(
            task
            for task in load_task_set_bundle("contest_honest_headline_v1").tasks
            if task.task_id == "rr-checkout-clean-protocol-001"
        )
        retrieve_result = StepResult(
            step_id="retrieve",
            success=True,
            output_state_refs=[
                ctx.put_text_state(
                    state_id="evidence-validated-decision",
                    kind="DENSE_EVIDENCE",
                    text="checkout orders slow, pool waits climb, missing index evidence remains visible",
                    metadata={"query": ctx.task.query},
                ),
                ctx.put_executor_decision_state(
                    state_id="decision-validated-decision",
                    decision_packet={
                        "schema": "statebus.executor_decision_packet.v1",
                        "route": "db_pool_saturation",
                        "tool_name": "tool.db_pool_triage",
                        "route_source": "lexical_match",
                        "route_confidence": 0.95,
                        "route_provenance": ["lexical"],
                        "tool_candidates": [
                            {
                                "tool_name": "tool.db_pool_triage",
                                "route": "db_pool_saturation",
                                "score": 11,
                                "matched_signals": ["connection pool"],
                                "matched_tags": ["checkout"],
                            },
                            {
                                "tool_name": "tool.db_query_hotfix",
                                "route": "db_pool_saturation",
                                "score": 9,
                                "matched_signals": ["missing index"],
                                "matched_tags": ["checkout"],
                            },
                        ],
                        "retrieved_doc_ids": ["rr-checkout-incident", "rr-checkout-scope"],
                        "matched_signals": ["connection pool", "missing index"],
                        "matched_tags": ["checkout"],
                        "feature_fresh_evidence_sha256": "validated-action-sha",
                    },
                    metadata={
                        "feature_route": "db_pool_saturation",
                        "feature_route_source": "lexical_match",
                        "feature_route_confidence": 0.95,
                        "feature_fresh_evidence_sha256": "validated-action-sha",
                    },
                ),
            ],
            payload={
                "feature_route": "db_pool_saturation",
                "feature_tool_name": "tool.db_pool_triage",
                "feature_route_source": "lexical_match",
                "feature_route_confidence": 0.95,
                "retrieved_doc_ids": ["rr-checkout-incident", "rr-checkout-scope"],
            },
        )
        validation_ref = ctx.put_validation_gate_state(
            state_id="validation-authoritative-decision",
            validation_packet={
                "schema": "statebus.validation_gate_packet.v1",
                "validated_route": "db_pool_saturation",
                "validated_tool_name": "tool.db_query_hotfix",
                "validated_action_contract": "execute_validated_tool",
                "validated_tool_candidates": [
                    {
                        "tool_name": "tool.db_query_hotfix",
                        "route": "db_pool_saturation",
                        "score": 9,
                        "matched_signals": ["missing index"],
                        "matched_tags": ["checkout"],
                        "source": "validation_gate",
                    }
                ],
                "route_source": "validation_gate",
                "route_confidence": 0.95,
                "retrieved_doc_ids": ["rr-checkout-incident", "rr-checkout-scope"],
                "validation_checks": ["validated scoped action changes executable tool"],
                "validation_success": True,
                "validation_failure_reason": "",
            },
            metadata={
                "validated_route": "db_pool_saturation",
                "validated_tool_name": "tool.db_query_hotfix",
                "route_confidence": 0.95,
                "validation_success": True,
            },
        )
        ctx.results["retrieve"] = retrieve_result
        ctx.set_step_role("retrieve", "retrieve")
        ctx.set_step_role("validate", "validate")
        execute_step = PlanStep(
            step_id="execute",
            semantic_role="execute",
            owner_agent="executor",
            action="EXECUTE_PLAYBOOK",
            input_state_refs=[],
            params={},
            depends_on=["retrieve", "validate"],
        )
        ctx.set_step_input_refs("execute", list(retrieve_result.output_state_refs) + [validation_ref])
        executor = build_sample_agents_with_executor()["executor"]
        execute_result = asyncio.run(executor.execute_step(execute_step, ctx))
        assert execute_result.success is True
        assert execute_result.payload["tool_name"] == "tool.db_query_hotfix"
        assert execute_result.payload["validation_gate_applied"] is True
        assert execute_result.payload["validation_decision_source"] == "validation_gate"
        assert execute_result.payload["validated_action_contract"] == "execute_validated_tool"


def test_s1_changed_action_requires_validation_hop() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-s1-validation-hop-") as tmpdir:
        pool = StatePool(Path(tmpdir) / "state")
        memory_store = MemoryStore(Path(tmpdir) / "memory.sqlite3", embedder=DeterministicEmbeddingProvider())
        memory_store.init_schema()
        session = RunSession(mode="protocol")
        ctx = RunContext(
            mode="protocol",
            trace_id="s1-validation-hop",
            task_id="rr-checkout-clean-protocol-001",
            task_group="contest_honest_headline",
            task_theme="contest_release_checkout_regression",
            session=session,
            statepool=pool,
            memory_store=memory_store,
            runtime_profile=RuntimeTaskProfile(transfer_strategy="state_packet_minimal"),
        )
        ctx.task = next(
            task
            for task in load_task_set_bundle("contest_honest_headline_v1").tasks
            if task.task_id == "rr-checkout-clean-protocol-001"
        )
        retrieve_result = StepResult(
            step_id="retrieve",
            success=True,
            output_state_refs=[
                ctx.put_text_state(
                    state_id="s1-hop-evidence",
                    kind="DENSE_EVIDENCE",
                    text="checkout pool wait climbs, slow orders query persists, and missing index evidence narrows the action",
                    metadata={"query": ctx.task.query},
                ),
                ctx.put_executor_decision_state(
                    state_id="s1-hop-decision",
                    decision_packet={
                        "schema": "statebus.executor_decision_packet.v1",
                        "route": "db_pool_saturation",
                        "tool_name": "tool.db_pool_triage",
                        "route_source": "lexical_match",
                        "route_confidence": 0.95,
                        "route_provenance": ["lexical"],
                        "tool_candidates": [
                            {
                                "tool_name": "tool.db_pool_triage",
                                "route": "db_pool_saturation",
                                "score": 11,
                                "matched_signals": ["pool wait"],
                                "matched_tags": ["checkout"],
                            },
                            {
                                "tool_name": "tool.db_query_hotfix",
                                "route": "db_pool_saturation",
                                "score": 9,
                                "matched_signals": ["missing index"],
                                "matched_tags": ["checkout"],
                            },
                        ],
                        "retrieved_doc_ids": ["rr-checkout-incident", "rr-checkout-scope"],
                        "matched_signals": ["pool wait", "slow orders query", "missing index"],
                        "matched_tags": ["checkout"],
                        "feature_fresh_evidence_sha256": "s1-validation-hop-sha",
                    },
                    metadata={
                        "feature_route": "db_pool_saturation",
                        "feature_route_source": "lexical_match",
                        "feature_route_confidence": 0.95,
                        "feature_fresh_evidence_sha256": "s1-validation-hop-sha",
                    },
                ),
            ],
            payload={
                "feature_route": "db_pool_saturation",
                "feature_tool_name": "tool.db_pool_triage",
                "feature_route_source": "lexical_match",
                "feature_route_confidence": 0.95,
                "retrieved_doc_ids": ["rr-checkout-incident", "rr-checkout-scope"],
            },
        )
        ctx.results["retrieve"] = retrieve_result
        ctx.set_step_role("retrieve", "retrieve")
        execute_step = PlanStep(
            step_id="execute",
            semantic_role="execute",
            owner_agent="executor",
            action="EXECUTE_PLAYBOOK",
            input_state_refs=[],
            params={},
            depends_on=["retrieve"],
        )
        executor = build_sample_agents_with_executor()["executor"]
        ctx.set_step_input_refs("execute", list(retrieve_result.output_state_refs))
        without_validation = asyncio.run(executor.execute_step(execute_step, ctx))

        ctx.set_step_input_refs("validate", list(retrieve_result.output_state_refs))
        validate_step = PlanStep(
            step_id="validate",
            semantic_role="validate",
            owner_agent="executor",
            action="VALIDATE_ROUTE",
            input_state_refs=[],
            params={},
            depends_on=["retrieve"],
        )
        validate_result = asyncio.run(executor.execute_step(validate_step, ctx))
        ctx.results["validate"] = validate_result
        ctx.set_step_role("validate", "validate")
        execute_step.depends_on = ["retrieve", "validate"]
        ctx.set_step_input_refs(
            "execute",
            list(retrieve_result.output_state_refs) + list(validate_result.output_state_refs),
        )
        with_validation = asyncio.run(executor.execute_step(execute_step, ctx))

        assert without_validation.payload["tool_name"] == "tool.db_pool_triage"
        assert without_validation.payload["validation_gate_applied"] is False
        assert validate_result.payload["pre_validation_tool_name"] == "tool.db_pool_triage"
        assert validate_result.payload["validated_tool_name"] == "tool.db_query_hotfix"
        assert validate_result.payload["validation_changed_action"] is True
        assert with_validation.payload["tool_name"] == "tool.db_query_hotfix"
        assert with_validation.payload["validation_gate_applied"] is True
        assert with_validation.payload["validation_changed_action"] is True


def test_validate_route_can_fallback_to_decision_packet_tool_when_retrieve_payload_omits_it() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-validate-tool-fallback-") as tmpdir:
        pool = StatePool(Path(tmpdir) / "state")
        memory_store = MemoryStore(Path(tmpdir) / "memory.sqlite3", embedder=DeterministicEmbeddingProvider())
        memory_store.init_schema()
        session = RunSession(mode="protocol")
        ctx = RunContext(
            mode="protocol",
            trace_id="validate-tool-fallback",
            task_id="planner-support-checkout-llm-001",
            task_group="planner_support_v3_lane",
            task_theme="contest_release_checkout_release",
            session=session,
            statepool=pool,
            memory_store=memory_store,
        )
        retrieve_result = StepResult(
            step_id="retrieve",
            success=True,
            output_state_refs=[
                ctx.statepool.put_text(
                    state_id="evidence",
                    kind="DENSE_EVIDENCE",
                    text="checkout pool waits and slow orders query after rollout",
                    metadata={"retrieved_doc_ids": ["rr-checkout-incident", "rr-checkout-scope"]},
                ),
                ctx.put_executor_decision_state(
                    state_id="decision",
                    decision_packet={
                        "schema": "statebus.executor_decision_packet.v1",
                        "route": "db_pool_saturation",
                        "tool_name": "tool.db_pool_triage",
                        "route_source": "lexical_match",
                        "route_confidence": 0.95,
                        "retrieved_doc_ids": ["rr-checkout-incident", "rr-checkout-scope"],
                        "matched_signals": ["pool wait", "slow orders query"],
                        "matched_tags": ["checkout"],
                        "feature_fresh_evidence_sha256": "abc123",
                    },
                    metadata={
                        "feature_route": "db_pool_saturation",
                        "feature_route_source": "lexical_match",
                        "feature_route_confidence": 0.95,
                        "feature_fresh_evidence_sha256": "abc123",
                    },
                ),
            ],
            payload={
                "feature_route": "db_pool_saturation",
                "feature_tool_name": "",
                "feature_route_source": "lexical_match",
                "feature_route_confidence": 0.95,
                "retrieved_doc_ids": ["rr-checkout-incident", "rr-checkout-scope"],
            },
        )
        ctx.results["retrieve"] = retrieve_result
        ctx.set_step_role("retrieve", "retrieve")
        ctx.set_step_input_refs("validate", list(retrieve_result.output_state_refs))
        validate_step = PlanStep(
            step_id="validate",
            semantic_role="validate",
            owner_agent="executor",
            action="VALIDATE_ROUTE",
            input_state_refs=[],
            params={},
            depends_on=["retrieve"],
        )
        executor = build_sample_agents_with_executor()["executor"]
        validate_result = asyncio.run(executor.execute_step(validate_step, ctx))
        assert validate_result.success is True
        assert {ref.kind for ref in validate_result.output_state_refs} == {"VALIDATION_GATE_PACKET"}
        assert validate_result.payload["validated_route"] == "db_pool_saturation"
        assert validate_result.payload["validated_tool_name"] == "tool.db_pool_triage"
        assert validate_result.payload["validation_failure_reason"] == ""


def test_validate_route_can_recover_text_whole_lane_route_and_tool_without_decision_packet() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-validate-whole-lane-") as tmpdir:
        pool = StatePool(Path(tmpdir) / "state")
        memory_store = MemoryStore(Path(tmpdir) / "memory.sqlite3", embedder=DeterministicEmbeddingProvider())
        memory_store.init_schema()
        session = RunSession(mode="text")
        ctx = RunContext(
            mode="text",
            trace_id="validate-whole-lane",
            task_id="rr-checkout-clean-text-001",
            task_group="contest_honest_headline",
            task_theme="contest_release_checkout_regression",
            session=session,
            statepool=pool,
            memory_store=memory_store,
            runtime_profile=RuntimeTaskProfile(
                transfer_strategy="text_whole_lane",
                handoff_profile="text_whole_lane",
            ),
        )
        ctx.task = next(
            task
            for task in load_task_set_bundle("contest_honest_headline_v1").tasks
            if task.task_id == "rr-checkout-clean-text-001"
        )
        retrieve_result = StepResult(
            step_id="retrieve",
            success=True,
            output_state_refs=[
                ctx.put_text_state(
                    state_id="evidence",
                    kind="DENSE_EVIDENCE",
                    text="checkout orders slow, pool wait climbs, db saturation signs persist",
                    metadata={"query": ctx.task.query},
                ),
                ctx.put_text_state(
                    state_id="handoff",
                    kind="TOOL_ARTIFACT",
                    text=(
                        "Retriever handoff in plain language for the contest headline lane.\n"
                        "The user is trying to triage checkout regression and recommend the first action.\n"
                        "The visible request concerns checkout confirmations slowed after rollout.\n"
                        "Based on the visible evidence, db pool saturation is the leading explanation so far, and the strongest competing explanation has not overtaken it.\n"
                        "Starting with db pool triage is the safest next step for now.\n"
                        "This read stays at high confidence and depends only on rr-checkout-incident, rr-checkout-scope.\n"
                        "Stay inside the visible evidence below and do not rely on any hidden structured packet, route field, tool field, or retrieval shortcut.\n"
                        "The visible evidence appears below.\n"
                        "checkout orders slow, pool wait climbs, db saturation signs persist\n"
                    ),
                    metadata={
                        "query": ctx.task.query,
                        "transfer_strategy": "text_whole_lane",
                        "handoff_profile": "text_whole_lane",
                        "retrieved_doc_ids": ["rr-checkout-incident", "rr-checkout-scope"],
                    },
                ),
            ],
            payload={
                "query": ctx.task.query,
                "feature_route": "db_pool_saturation",
                "feature_tool_name": "tool.db_pool_triage",
                "feature_route_source": "lexical_match",
                "feature_route_confidence": 0.95,
                "retrieved_doc_ids": ["rr-checkout-incident", "rr-checkout-scope"],
            },
        )
        ctx.results["retrieve"] = retrieve_result
        ctx.set_step_role("retrieve", "retrieve")
        ctx.set_step_input_refs("validate", list(retrieve_result.output_state_refs))
        validate_step = PlanStep(
            step_id="validate",
            semantic_role="validate",
            owner_agent="executor",
            action="VALIDATE_ROUTE",
            input_state_refs=[],
            params={},
            depends_on=["retrieve"],
        )
        executor = build_sample_agents_with_executor()["executor"]
        validate_result = asyncio.run(executor.execute_step(validate_step, ctx))
        assert validate_result.success is True
        assert validate_result.payload["validated_route"] == "db_pool_saturation"
        assert validate_result.payload["pre_validation_tool_name"] == "tool.db_pool_triage"
        assert validate_result.payload["validated_tool_name"] == "tool.db_query_hotfix"
        assert validate_result.payload["validation_changed_action"] is True
        assert validate_result.payload["validation_failure_reason"] == ""


def test_validate_route_helper_disabled_does_not_recover_text_whole_lane_tool() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-validate-whole-lane-helper-off-") as tmpdir:
        pool = StatePool(Path(tmpdir) / "state")
        memory_store = MemoryStore(Path(tmpdir) / "memory.sqlite3", embedder=DeterministicEmbeddingProvider())
        memory_store.init_schema()
        session = RunSession(mode="text")
        ctx = RunContext(
            mode="text",
            trace_id="validate-whole-lane-helper-off",
            task_id="rr-checkout-clean-text-001",
            task_group="contest_honest_headline",
            task_theme="contest_release_checkout_regression",
            session=session,
            statepool=pool,
            memory_store=memory_store,
            runtime_profile=RuntimeTaskProfile(
                transfer_strategy="text_whole_lane",
                handoff_profile="text_whole_lane",
                audit_text_helper_mode="disabled",
            ),
        )
        ctx.task = next(
            task
            for task in load_task_set_bundle("contest_honest_headline_v1").tasks
            if task.task_id == "rr-checkout-clean-text-001"
        )
        retrieve_result = StepResult(
            step_id="retrieve",
            success=True,
            output_state_refs=[
                ctx.put_text_state(
                    state_id="evidence",
                    kind="DENSE_EVIDENCE",
                    text="checkout orders slow, pool wait climbs, db saturation signs persist",
                    metadata={"query": ctx.task.query},
                ),
                ctx.put_text_state(
                    state_id="handoff",
                    kind="TOOL_ARTIFACT",
                    text=(
                        "Retriever handoff in plain language for the contest headline lane.\n"
                        "The user is trying to triage checkout regression and recommend the first action.\n"
                        "The visible request concerns checkout confirmations slowed after rollout.\n"
                        "Based on the visible evidence, db pool saturation is the leading explanation so far, and the strongest competing explanation has not overtaken it.\n"
                        "Starting with db pool triage is the safest next step for now.\n"
                        "This read stays at high confidence and depends only on rr-checkout-incident, rr-checkout-scope.\n"
                        "Stay inside the visible evidence below and do not rely on any hidden structured packet, route field, tool field, or retrieval shortcut.\n"
                        "The visible evidence appears below.\n"
                        "checkout orders slow, pool wait climbs, db saturation signs persist\n"
                    ),
                    metadata={
                        "query": ctx.task.query,
                        "transfer_strategy": "text_whole_lane",
                        "handoff_profile": "text_whole_lane",
                        "retrieved_doc_ids": ["rr-checkout-incident", "rr-checkout-scope"],
                    },
                ),
            ],
            payload={
                "query": ctx.task.query,
                "feature_route": "",
                "feature_tool_name": "",
                "feature_route_source": "lexical_match",
                "feature_route_confidence": 0.95,
                "retrieved_doc_ids": ["rr-checkout-incident", "rr-checkout-scope"],
            },
        )
        ctx.results["retrieve"] = retrieve_result
        ctx.set_step_role("retrieve", "retrieve")
        ctx.set_step_input_refs("validate", list(retrieve_result.output_state_refs))
        validate_step = PlanStep(
            step_id="validate",
            semantic_role="validate",
            owner_agent="executor",
            action="VALIDATE_ROUTE",
            input_state_refs=[],
            params={},
            depends_on=["retrieve"],
        )
        executor = build_sample_agents_with_executor()["executor"]
        validate_result = asyncio.run(executor.execute_step(validate_step, ctx))
        assert validate_result.success is False
        assert validate_result.payload["validated_route"] == ""
        assert validate_result.payload["pre_validation_tool_name"] == ""
        assert validate_result.payload["validated_tool_name"] == ""
        assert validate_result.payload["validation_refinement_reason"] == ""
        assert validate_result.payload["validation_failure_reason"] == "validate route requires executor decision packet"


def test_validate_route_allows_contract_abstention_for_text_whole_lane() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-validate-whole-lane-abstain-") as tmpdir:
        pool = StatePool(Path(tmpdir) / "state")
        memory_store = MemoryStore(Path(tmpdir) / "memory.sqlite3", embedder=DeterministicEmbeddingProvider())
        memory_store.init_schema()
        session = RunSession(mode="text")
        ctx = RunContext(
            mode="text",
            trace_id="validate-whole-lane-abstain",
            task_id="rr-checkout-ambiguous-text-001",
            task_group="contest_honest_headline",
            task_theme="contest_release_checkout_regression",
            session=session,
            statepool=pool,
            memory_store=memory_store,
            runtime_profile=RuntimeTaskProfile(
                transfer_strategy="text_whole_lane",
                handoff_profile="text_whole_lane",
            ),
        )
        ctx.task = next(
            task
            for task in load_task_set_bundle("contest_honest_headline_v1").tasks
            if task.task_id == "rr-checkout-ambiguous-text-001"
        )
        retrieve_result = StepResult(
            step_id="retrieve",
            success=True,
            output_state_refs=[
                ctx.put_text_state(
                    state_id="evidence",
                    kind="DENSE_EVIDENCE",
                    text="mixed checkout evidence keeps db and worker routes open",
                    metadata={"query": ctx.task.query},
                ),
                ctx.put_text_state(
                    state_id="handoff",
                    kind="TOOL_ARTIFACT",
                    text=(
                        "Retriever handoff in plain language for the contest headline lane.\n"
                        "The user is trying to re-evaluate the checkout slowdown under conflicting queue and database signals.\n"
                        "The visible request concerns checkout confirmations slowed after rollout while queue saturation and query wait evidence both remain live.\n"
                        "Based on the visible evidence, generic triage is the leading explanation so far, and the strongest competing explanation has not overtaken it.\n"
                        "Starting with collect more evidence is the safest next step for now.\n"
                        "This read stays at low confidence and depends only on rr-checkout-ambiguous, rr-checkout-metrics.\n"
                        "Stay inside the visible evidence below and do not rely on any hidden structured packet, route field, tool field, or retrieval shortcut.\n"
                        "The visible evidence appears below.\n"
                        "mixed checkout evidence keeps db and worker routes open\n"
                    ),
                    metadata={
                        "query": ctx.task.query,
                        "transfer_strategy": "text_whole_lane",
                        "handoff_profile": "text_whole_lane",
                        "retrieved_doc_ids": ["rr-checkout-ambiguous", "rr-checkout-metrics"],
                    },
                ),
            ],
            payload={
                "query": ctx.task.query,
                "feature_route": "generic_triage",
                "feature_tool_name": "tool.collect_more_evidence",
                "feature_route_source": "low_confidence_abstain",
                "feature_route_confidence": 0.0,
                "retrieved_doc_ids": ["rr-checkout-ambiguous", "rr-checkout-metrics"],
            },
        )
        ctx.results["retrieve"] = retrieve_result
        ctx.set_step_role("retrieve", "retrieve")
        ctx.set_step_input_refs("validate", list(retrieve_result.output_state_refs))
        validate_step = PlanStep(
            step_id="validate",
            semantic_role="validate",
            owner_agent="executor",
            action="VALIDATE_ROUTE",
            input_state_refs=[],
            params={},
            depends_on=["retrieve"],
        )
        executor = build_sample_agents_with_executor()["executor"]
        validate_result = asyncio.run(executor.execute_step(validate_step, ctx))
        assert validate_result.success is True
        assert validate_result.payload["validated_route"] == "generic_triage"
        assert validate_result.payload["validated_tool_name"] == "tool.collect_more_evidence"
        assert validate_result.payload["validation_failure_reason"] == ""
        assert "abstention allowed by task contract" in validate_result.payload["validation_checks"]


def test_object_parity_gate_accepts_validated_minimal_protocol_executor_kinds() -> None:
    from eval.runner import _object_parity_gate

    gate = _object_parity_gate(
        pack_type="contest_honest_headline_v1",
        task_rows_by_mode={
            "protocol": [
                {
                    "task_id": "validated-minimal-001",
                    "status": "completed",
                    "summary_contract": "actions_plus_evidence",
                    "transfer_strategy": "state_packet_minimal",
                    "handoff_profile": "protocol_minimal_state_packet",
                    "step_truth": {
                        "retrieve": {},
                        "validate": {},
                        "execute": {},
                        "summarize": {},
                    },
                    "transfer_truth_audit": {
                        "executor_input_kinds": [
                            "DENSE_EVIDENCE",
                            "EXECUTOR_DECISION_PACKET",
                            "VALIDATION_GATE_PACKET",
                        ],
                    },
                }
            ],
            "text": [],
        },
        text_guard_audit={
            "hidden_field_leak_rate": 0.0,
            "template_slot_leak_rate": 0.0,
            "summarizer_typed_visibility_rate": 0.0,
        },
    )
    assert gate["executor_mainline_object_ok"] is True
    assert gate["passed"] is True


def test_contest_headline_and_planner_support_surface_boundaries_are_explicit() -> None:
    contest = load_task_set_bundle("contest_dual_mode_controlled_v3").metadata
    planner = load_task_set_bundle("planner_support_v3").metadata

    assert contest.public_surface == "formal_headline"
    assert contest.plan_source_default == "yaml"
    assert contest.variable_axes == ("mode", "handoff_object")

    assert planner.public_surface == "formal_secondary_planner"
    assert planner.evidence_tier == "formal_secondary"
    assert planner.plan_source_default == "yaml"
    assert planner.variable_axes == ("plan_source",)


def test_contest_release_state_transfer_packs_share_family_case_contract() -> None:
    carrier = list(load_task_set_bundle("tasks/contest_release_regression_carrier_benchmark.yaml").tasks)
    authenticity = list(load_task_set_bundle("tasks/contest_release_regression_authenticity_benchmark.yaml").tasks)
    pure_text = list(load_task_set_bundle("typed_state_authenticity_v3").tasks)
    strict_pure_text = list(load_task_set_bundle("text_definition_audit_v3").tasks)
    support = list(load_task_set_bundle("tasks/contest_release_regression_natural_support_benchmark.yaml").tasks)

    assert len(carrier) == len(authenticity) == len(pure_text) == len(strict_pure_text) == len(support) == 40

    def _normalize_case(task_id: str) -> str:
        normalized = task_id
        for suffix in (
            "-text-packet-001",
            "-state-packet-001",
            "-text-brief-001",
            "-state-ref-001",
            "-pure-text-001",
            "-inline-text-001",
            "-state-packet-002",
        ):
            if normalized.endswith(suffix):
                return normalized[: -len(suffix)]
        raise AssertionError(f"unexpected contest task id: {task_id}")

    def _by_case(tasks: list[SampleTask]) -> dict[str, list[SampleTask]]:
        grouped: dict[str, list[SampleTask]] = {}
        for task in tasks:
            grouped.setdefault(_normalize_case(task.task_id), []).append(task)
        return grouped

    carrier_cases = _by_case(carrier)
    authenticity_cases = _by_case(authenticity)
    pure_text_cases = _by_case(pure_text)
    strict_pure_text_cases = _by_case(strict_pure_text)
    support_cases = _by_case(support)

    assert (
        set(carrier_cases)
        == set(authenticity_cases)
        == set(pure_text_cases)
        == set(strict_pure_text_cases)
        == set(support_cases)
    )
    assert len(carrier_cases) == 20

    for case_id in sorted(carrier_cases):
        c_pair = sorted(carrier_cases[case_id], key=lambda item: item.task_order)
        a_pair = sorted(authenticity_cases[case_id], key=lambda item: item.task_order)
        p_pair = sorted(pure_text_cases[case_id], key=lambda item: item.task_order)
        strict_pair = sorted(strict_pure_text_cases[case_id], key=lambda item: item.task_order)
        s_pair = sorted(support_cases[case_id], key=lambda item: item.task_order)
        assert len(c_pair) == len(a_pair) == len(p_pair) == len(strict_pair) == len(s_pair) == 2

        baseline = c_pair[0]
        for peer in (*c_pair[1:], *a_pair, *p_pair, *strict_pair, *s_pair):
            assert peer.goal == baseline.goal
            assert peer.query == baseline.query
            assert peer.corpus_doc_ids == baseline.corpus_doc_ids
            assert peer.task_group == baseline.task_group
            assert peer.task_theme == baseline.task_theme
            assert peer.summary_hint == baseline.summary_hint

        assert {task.transfer_strategy for task in c_pair} == {"text_packet_minimal", "state_packet_minimal"}
        assert {task.transfer_strategy for task in a_pair} == {"text_brief", "state_ref"}
        assert {task.transfer_strategy for task in p_pair} == {"natural_handoff_text", "state_packet_minimal"}
        assert {task.transfer_strategy for task in strict_pair} == {"inline_text_handoff", "state_packet_minimal"}
        assert {task.transfer_strategy for task in s_pair} == {"inline_text_handoff", "state_packet_minimal"}


def test_contest_dual_mode_controlled_v3_withholds_headline_when_pair_coverage_is_seed_only() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-contest-v3-withheld-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="contest_dual_mode_controlled_v3",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (Path(tmpdir) / "benchmark_report.md").read_text(encoding="utf-8")
    assert result["manifest"]["state_transfer_headline_allowed"] is False
    assert "contest_repeat_insufficient" in result["manifest"]["withheld_headline_reason"]
    assert "contest_case_surface_incomplete" not in result["manifest"]["withheld_headline_reason"]
    assert result["manifest"]["headline_gates"]["communication_gate"]["allowed"] is False
    assert result["manifest"]["contest_formal_coverage_gate"]["matched_pair_count"] == 20
    assert result["manifest"]["contest_formal_coverage_gate"]["family_coverage"] == 5
    assert result["manifest"]["contest_formal_coverage_gate"]["surface_complete"] is True
    assert result["manifest"]["contest_formal_coverage_gate"]["repeat_sufficient"] is False
    assert "internal controlled composite surface" in report_text
    assert "contest-facing honest headline should read from `contest_honest_headline_v1`" in report_text


def test_memory_policy_controlled_v3_manifest_exposes_replay_headline_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-memory-policy-v3-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="memory_policy_controlled_v3",
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (Path(tmpdir) / "benchmark_report.md").read_text(encoding="utf-8")
    replay_gate = result["manifest"]["headline_gates"]["memory_replay_gate"]
    assert replay_gate["applicable"] is True
    assert replay_gate["memory_replay_evidence_gate"]["applicable"] is True
    assert replay_gate["memory_replay_evidence_gate"]["passed"] is True
    assert replay_gate["memory_replay_evidence_gate"]["expected_rows"] == 4
    assert replay_gate["memory_replay_evidence_gate"]["matched_rows"] == 4
    assert "Replay headline gate" in report_text


def test_state_ref_consumer_sensitivity_audit_changes_executor_visibility_by_kind() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-consumer-sensitivity-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/state_ref_consumer_sensitivity_audit_benchmark.yaml",
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    tasks = {task["task_id"]: task for task in result["mode_runs"]["protocol"][0]["tasks"]}
    mechanism = result["summary"]["protocol"]["mechanism_audit"]["disabled_kind_variants"]
    full = tasks["audit-sensitivity-rich-full-001"]
    no_channel = tasks["audit-sensitivity-no-channel-snapshot-001"]
    no_tool_candidates = tasks["audit-sensitivity-no-tool-candidates-001"]
    no_ranked = tasks["audit-sensitivity-no-ranked-evidence-001"]
    no_replay = tasks["audit-sensitivity-no-replay-eligibility-001"]
    minimal = tasks["audit-sensitivity-minimal-baseline-001"]
    missing_decision = tasks["audit-sensitivity-minimal-missing-decision-001"]
    wrong_decision = tasks["audit-sensitivity-minimal-wrong-decision-001"]

    assert "FEATURE_BUNDLE" in full["transfer_truth_audit"]["executor_input_kinds"]
    assert "CHANNEL_SNAPSHOT" in full["transfer_truth_audit"]["executor_input_kinds"]
    assert "TOOL_CANDIDATE_SET" in full["transfer_truth_audit"]["executor_input_kinds"]

    assert no_channel["status"] == "completed"
    assert no_channel["mode"] == "protocol"
    assert no_channel["audit_disable_state_kinds"] == ["CHANNEL_SNAPSHOT"]
    assert "CHANNEL_SNAPSHOT" not in no_channel["transfer_truth_audit"]["executor_input_kinds"]
    assert no_tool_candidates["audit_disable_state_kinds"] == ["TOOL_CANDIDATE_SET"]
    assert "TOOL_CANDIDATE_SET" not in no_tool_candidates["transfer_truth_audit"]["executor_input_kinds"]
    assert no_ranked["audit_disable_state_kinds"] == ["RANKED_EVIDENCE_BUNDLE"]
    assert "RANKED_EVIDENCE_BUNDLE" not in no_ranked["transfer_truth_audit"]["executor_input_kinds"]
    assert no_replay["audit_disable_state_kinds"] == ["REPLAY_ELIGIBILITY_BUNDLE"]
    assert "REPLAY_ELIGIBILITY_BUNDLE" not in no_replay["transfer_truth_audit"]["executor_input_kinds"]
    assert set(mechanism) == {
        "disable_channel_snapshot",
        "disable_tool_candidate_set",
        "disable_ranked_evidence_bundle",
        "disable_replay_eligibility_bundle",
        "disable_executor_decision_packet",
        "wrong_executor_decision_packet",
    }
    assert "disable_feature_bundle" not in mechanism
    assert minimal["status"] == "completed"
    assert "EXECUTOR_DECISION_PACKET" in minimal["transfer_truth_audit"]["executor_input_kinds"]
    assert missing_decision["status"] == "failed"
    assert missing_decision["audit_disable_state_kinds"] == ["EXECUTOR_DECISION_PACKET"]
    assert "EXECUTOR_DECISION_PACKET" in str(missing_decision["error"])
    assert wrong_decision["status"] == "completed"
    assert wrong_decision["results"]["execute"]["payload"]["route"] == "worker_queue_starvation"
    assert wrong_decision["results"]["execute"]["payload"]["tool_name"] == "tool.collect_more_evidence"
    assert wrong_decision["artifact_misfire"]["fields"]["tool_name"]["matched"] is False


def test_typed_state_consumer_sensitivity_v3_alias_expands_to_5_families_and_reports_secondary_metrics() -> None:
    tasks = list(load_task_set_bundle("typed_state_consumer_sensitivity_v3").tasks)
    assert len(tasks) == 40
    assert len({task.task_theme for task in tasks}) == 5
    assert {task.transfer_strategy for task in tasks} == {"state_ref", "state_packet_minimal"}
    assert {
        task.task_id
        for task in tasks
        if task.audit_disable_state_kinds == ("EXECUTOR_DECISION_PACKET",)
    }

    with tempfile.TemporaryDirectory(prefix="statebus-typed-consumer-v3-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="typed_state_consumer_sensitivity_v3",
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (Path(tmpdir) / "benchmark_report.md").read_text(encoding="utf-8")

    assert result["manifest"]["task_pack_type"] == "typed_state_consumer_sensitivity_v3"
    assert result["manifest"]["support_evidence_only"] is False
    assert result["manifest"]["task_set_evidence_tier"] == "formal_secondary"
    consumer = result["summary"]["protocol"]["mechanism_audit"]["typed_state_consumer_sensitivity_v3"]
    assert consumer["missing_decision_failure_rate"] == 1.0
    assert consumer["wrong_decision_mistool_rate"] > 0.0
    assert result["summary"]["protocol"]["expected_negative_task_failure_count"] > 0
    assert result["summary"]["protocol"]["negative_control_trigger_rate"] > 0.0
    assert result["summary"]["protocol"]["unexpected_task_failure_count"] == 0
    assert result["summary"]["protocol"]["run_failure_count"] == 0
    assert "disable_channel_snapshot" in consumer["rich_helper_disable_impact_summary"]
    assert "Typed State Consumer Sensitivity V3" in report_text
    assert "formal-secondary support" in report_text


def test_typed_state_consumer_sensitivity_v3_bundle_and_expanded_rows_keep_metadata_consistent() -> None:
    bundle = load_task_set_bundle("typed_state_consumer_sensitivity_v3")
    metadata = bundle.metadata
    for task in bundle.tasks:
        child_metadata = task.task_set_metadata
        assert child_metadata is not None
        assert child_metadata.pack_type == metadata.pack_type
        assert child_metadata.public_surface == metadata.public_surface
        assert child_metadata.evidence_tier == metadata.evidence_tier
        assert child_metadata.variable_axes == metadata.variable_axes
        assert child_metadata.benchmark_version == metadata.benchmark_version
        assert (
            child_metadata.formal_structure_clean_retrieval
            == metadata.formal_structure_clean_retrieval
        )


def test_retrieval_weak_route_diagnostic_task_set_keeps_exact_route_and_tool_pairs() -> None:
    expected = {
        "diag-retrieval-weak-route-cache-replica-001": (
            "cache_replica_stale_read",
            "tool.replica_stale_read_triage",
        ),
        "diag-retrieval-weak-route-session-drift-001": (
            "auth_session_drift",
            "tool.auth_session_repair",
        ),
        "diag-retrieval-weak-route-session-rate-limit-001": (
            "auth_session_drift",
            "tool.auth_session_repair",
        ),
        "diag-retrieval-weak-route-cache-invalidation-001": (
            "cache_replica_stale_read",
            "tool.replica_stale_read_triage",
        ),
        "diag-retrieval-weak-route-latency-db-001": (
            "worker_queue_starvation",
            "tool.worker_queue_triage",
        ),
        "diag-retrieval-weak-route-latency-worker-001": (
            "worker_queue_starvation",
            "tool.worker_queue_triage",
        ),
    }
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
    for mode in ("text", "protocol"):
        tasks = {task["task_id"]: task for task in result["mode_runs"][mode][0]["tasks"]}
        for task_id, (route, tool_name) in expected.items():
            retrieve_payload = tasks[task_id]["results"]["retrieve"]["payload"]
            execute_payload = tasks[task_id]["results"]["execute"]["payload"]
            assert retrieve_payload["feature_route"] == route
            assert execute_payload["route"] == route
            assert execute_payload["tool_name"] == tool_name


def test_open_system_comparison_v1_runs_three_arms_and_two_native_reuse_policies() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-open-system-v1-") as tmpdir:
        result = run_open_comparison(out_dir=Path(tmpdir), repeat=1)
        assert (Path(tmpdir) / "open_results.json").exists()
        assert (Path(tmpdir) / "open_compare.csv").exists()
        assert (Path(tmpdir) / "open_report.md").exists()

    assert result["manifest"]["task_pack"] == "open_system_comparison_v1"
    assert tuple(result["manifest"]["runtime_arms"]) == RUNTIME_ARMS
    assert tuple(result["manifest"]["open_memory_policies"]) == OPEN_MEMORY_POLICIES
    summary = {
        (row["runtime_arm"], row["open_memory_policy"]): row
        for row in result["summary"]
    }
    assert len(summary) == 6
    assert "external_text_open" not in result["manifest"]["runtime_arms"]
    for arm in RUNTIME_ARMS:
        assert summary[(arm, "memory_off")]["replay_hit_rate"] == 0.0
        assert summary[(arm, "native_reuse_on")]["replay_hit_rate"] > 0.0
        assert summary[(arm, "native_reuse_on")]["skipped_step_count"] > 0.0
    metric_keys = set(result["summary"][0])
    for row in result["summary"]:
        assert set(row) == metric_keys


def test_pure_text_open_baseline_v1_runs_one_external_arm_and_writes_outputs() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-pure-text-open-") as tmpdir:
        result = run_pure_text_open_baseline(out_dir=Path(tmpdir), repeat=1)
        assert (Path(tmpdir) / "open_results.json").exists()
        assert (Path(tmpdir) / "open_compare.csv").exists()
        assert (Path(tmpdir) / "open_report.md").exists()

    assert result["manifest"]["task_pack"] == PURE_TEXT_OPEN_BASELINE_PACK
    assert tuple(result["manifest"]["runtime_arms"]) == ("external_text_open",)
    assert "external pure-text baseline" in result["manifest"]["contract"].lower()
    assert result["manifest"]["data_source"] == "lexical_stub"
    assert result["manifest"]["selected_complexity_buckets"] == [
        "ambiguous",
        "reusable",
        "simple",
    ]
    summary = {(row["runtime_arm"], row["open_memory_policy"]): row for row in result["summary"]}
    assert len(summary) == 2
    for policy in OPEN_MEMORY_POLICIES:
        assert summary[("external_text_open", policy)]["runtime_arm"] == "external_text_open"
        assert summary[("external_text_open", policy)]["data_source"] == "lexical_stub"
    for row in result["tasks"]:
        assert row["runtime_arm"] == "external_text_open"
        assert row["statebus_contract_used"] is False
        assert row["metadata_oracle_used"] is False
        assert row["decision_source"] == "text_only_lexical_playbook"
        assert row["data_source"] == "lexical_stub"
        assert all(isinstance(message, str) for message in row["message_log"])
        assert all("StateRef" not in message for message in row["message_log"])
        assert all("EXECUTOR_DECISION_PACKET" not in message for message in row["message_log"])


def test_pure_text_open_baseline_v1_selects_text_rows_across_small_mixed_complexity_slice() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-pure-text-open-slice-") as tmpdir:
        result = run_pure_text_open_baseline(out_dir=Path(tmpdir), repeat=1)
    tasks_by_id = {
        task.task_id: task
        for task in load_task_set_bundle("contest_dual_mode_controlled_v3").tasks
    }
    selected_ids = tuple(result["manifest"]["selected_task_ids"])
    assert selected_ids
    assert all(tasks_by_id[task_id].supports_mode("text") for task_id in selected_ids)
    assert all(not tasks_by_id[task_id].supports_mode("protocol") for task_id in selected_ids)
    assert {tasks_by_id[task_id].complexity_bucket for task_id in selected_ids} == {
        "simple",
        "ambiguous",
        "reusable",
    }
    assert len({tasks_by_id[task_id].task_theme for task_id in selected_ids}) == 2


def test_pure_text_open_baseline_v1_rejects_too_narrow_task_surface() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-pure-text-open-narrow-") as tmpdir:
        custom_pack = Path(tmpdir) / "narrow_pack.yaml"
        corpus_path = (REPO_ROOT / "tasks" / "contest_release_regression_corpus.yaml").resolve()
        custom_pack.write_text(
            f"""
task_set:
  name: narrow_pack
  pack_type: ad_hoc
  description: Too narrow pure-text baseline pack.
  reading_contract: Use this pack only to test pure-text selection gates.
  claim_lanes: [state_transfer]
  evidence_tier: audit_only
  benchmark_version: v3
tasks:
- task_id: narrow-simple-001
  task_group: narrow_group
  task_order: 1
  task_theme: contest_release_checkout_regression
  benchmark_lane: internal_regression
  allowed_modes: [text]
  corpus_path: {corpus_path}
  goal: Use the local corpus to diagnose the checkout regression and recommend the first action.
  query: checkout release 17.4 canary shows connection pool waits and slow orders query after rollout
  corpus_doc_ids: [rr-checkout-incident, rr-checkout-metrics, rr-checkout-logs]
  summary_hint: Return the first action only.
  transfer_strategy: text_strict_pure_lane
  handoff_profile: text_strict_pure_lane
  complexity_bucket: simple
  primary_expected_route: db_pool_saturation
  primary_expected_tool: tool.db_pool_triage
""".strip(),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="missing complexity buckets"):
            run_pure_text_open_baseline(out_dir=Path(tmpdir) / "out", repeat=1, task_set=custom_pack)


def test_pure_text_open_live_api_slice_v1_selects_frozen_headline_text_rows_only() -> None:
    bundle = load_task_set_bundle("pure_text_open_live_api_slice_v1")
    source_tasks = {task.task_id: task for task in load_task_set_bundle("contest_honest_headline_v1").tasks}
    assert bundle.metadata.pack_type == "pure_text_open_live_api_slice_v1"
    assert bundle.metadata.audit_only is True
    assert len(bundle.tasks) == 8
    assert all(task.supports_mode("text") for task in bundle.tasks)
    assert all(task.transfer_strategy == "text_whole_lane" for task in bundle.tasks)
    assert all(task.expected_reuse_mode == "none" for task in bundle.tasks)
    assert all(task.task_id in source_tasks for task in bundle.tasks)
    assert {task.complexity_bucket for task in bundle.tasks} == {"simple", "ambiguous", "distractor"}


def test_route_corpus_stress_whole_lane_audit_v1_keeps_protocol_side_and_moves_text_side_to_whole_lane() -> None:
    bundle = load_task_set_bundle("route_corpus_stress_whole_lane_audit_v1")
    assert bundle.metadata.pack_type == "route_corpus_stress_whole_lane_audit_v1"
    text_tasks = [task for task in bundle.tasks if task.supports_mode("text")]
    protocol_tasks = [task for task in bundle.tasks if task.supports_mode("protocol")]
    assert text_tasks
    assert protocol_tasks
    assert all(task.transfer_strategy == "text_whole_lane" for task in text_tasks)
    assert all(task.handoff_profile == "text_whole_lane" for task in text_tasks)
    assert all(task.transfer_strategy == "state_packet_minimal" for task in protocol_tasks)
    assert all(task.runtime_reuse_contract == "reuse_disabled" for task in bundle.tasks)


def test_external_text_open_ignores_expected_metadata_oracle_fields() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-pure-text-oracle-") as tmpdir:
        custom_pack = Path(tmpdir) / "oracle_pack.yaml"
        corpus_path = (REPO_ROOT / "tasks" / "contest_release_regression_corpus.yaml").resolve()
        custom_pack.write_text(
            f"""
task_set:
  name: oracle_pack
  pack_type: ad_hoc
  description: Oracle leakage test pack.
  reading_contract: Use this pack only to test metadata leakage.
  claim_lanes: [state_transfer]
  evidence_tier: audit_only
  benchmark_version: v3
tasks:
- task_id: oracle-leak-001
  task_group: oracle_leak_group
  task_order: 1
  task_theme: contest_release_checkout_regression
  benchmark_lane: internal_regression
  allowed_modes: [text]
  corpus_path: {corpus_path}
  goal: Use the local corpus to diagnose the checkout regression and recommend the first action.
  query: checkout release 17.4 canary shows connection pool waits and slow orders query after rollout
  corpus_doc_ids: [rr-checkout-incident, rr-checkout-metrics, rr-checkout-logs]
  summary_hint: Return the first action only.
  transfer_strategy: text_strict_pure_lane
  handoff_profile: text_strict_pure_lane
  complexity_bucket: simple
  expected_route: wrong_expected_route
  expected_tool_name: tool.wrong_expected_tool
  primary_expected_route: wrong_primary_route
  primary_expected_tool: tool.wrong_primary_tool
- task_id: oracle-leak-002
  task_group: oracle_leak_group
  task_order: 2
  task_theme: contest_release_checkout_regression
  benchmark_lane: internal_regression
  allowed_modes: [text]
  corpus_path: {corpus_path}
  goal: Use the local corpus to diagnose the checkout regression and recommend the first action.
  query: checkout canary shows both sql wait growth and queue pressure after rollout, but orders filter changes still line up with the failures
  corpus_doc_ids: [rr-checkout-metrics, rr-checkout-logs, rr-checkout-worker-false, rr-checkout-ambiguous]
  summary_hint: Return the first action only.
  transfer_strategy: text_strict_pure_lane
  handoff_profile: text_strict_pure_lane
  complexity_bucket: ambiguous
  expected_route: wrong_expected_route
  expected_tool_name: tool.wrong_expected_tool
  primary_expected_route: wrong_primary_route
  primary_expected_tool: tool.wrong_primary_tool
- task_id: oracle-leak-003
  task_group: oracle_leak_group
  task_order: 3
  task_theme: contest_release_checkout_regression
  benchmark_lane: internal_regression
  allowed_modes: [text]
  corpus_path: {corpus_path}
  goal: Use the local corpus to diagnose the checkout regression and recommend the first action.
  query: checkout canary blast radius stays on the new shard with the same connection wait and slow orders pattern
  corpus_doc_ids: [rr-checkout-metrics, rr-checkout-config, rr-checkout-scope, rr-checkout-logs]
  summary_hint: Return the first action only.
  transfer_strategy: text_strict_pure_lane
  handoff_profile: text_strict_pure_lane
  complexity_bucket: reusable
  required_prior_case_ids: [rr-checkout-clean]
  required_prior_rejections: [worker_queue_starvation]
  expected_route: wrong_expected_route
  expected_tool_name: tool.wrong_expected_tool
  primary_expected_route: wrong_primary_route
  primary_expected_tool: tool.wrong_primary_tool
""".strip(),
            encoding="utf-8",
        )
        result = run_pure_text_open_baseline(out_dir=Path(tmpdir) / "out", repeat=1, task_set=custom_pack)
    row = result["tasks"][0]
    assert row["route"] == "db_pool_saturation"
    assert row["tool_name"] == "tool.db_pool_triage"
    assert row["metadata_oracle_used"] is False
    assert row["correctness"]["route_exact"] is False
    assert row["correctness"]["tool_exact"] is False


def test_external_text_open_native_reuse_requires_same_retrieved_doc_set() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-pure-text-reuse-") as tmpdir:
        result = run_pure_text_open_baseline(out_dir=Path(tmpdir), repeat=2)
    second_run = [row for row in result["tasks"] if row["run_index"] == 1]
    assert any(row["native_replay"]["hit"] for row in second_run)
    assert any(row["metrics"]["skipped_step_count"] > 0 for row in second_run)


def test_external_text_open_message_log_stays_text_only_and_without_markers() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-pure-text-messages-") as tmpdir:
        result = run_pure_text_open_baseline(out_dir=Path(tmpdir), repeat=1)
    forbidden_markers = (
        "MEMORY_ASSIST_HINT",
        "Suggested route:",
        "Tool candidates:",
        "StateRef",
        "EXECUTOR_DECISION_PACKET",
    )
    for row in result["tasks"]:
        for message in row["message_log"]:
            assert isinstance(message, str)
            assert all(marker not in message for marker in forbidden_markers)


def test_external_text_open_source_stays_outside_statebus_runtime_and_structured_packets() -> None:
    source_text = (REPO_ROOT / "eval" / "text_open_baseline.py").read_text(encoding="utf-8")
    forbidden = (
        "Orchestrator",
        "StatePool",
        "from protocol",
        "from statepool",
    )
    for token in forbidden:
        assert token not in source_text


class _LiveTextOpenFakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def complete(self, messages, *, purpose: str, temperature=None):  # type: ignore[no-untyped-def]
        del temperature
        prompt = messages[-1].content
        self.calls.append((purpose, prompt))
        if purpose == "planner":
            assert "expected_route" not in prompt
            assert "expected_tool_name" not in prompt
            assert "primary_expected_route" not in prompt
            assert "primary_expected_tool" not in prompt
            return LLMResult(
                text=json.dumps(
                    {
                        "route": "db_pool_saturation",
                        "tool_name": "tool.db_pool_triage",
                        "strongest_competing_route": "worker_queue_starvation",
                        "validation_check": "confirm the slow orders query and pool wait evidence align",
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                usage=LLMUsage(prompt_tokens=17, completion_tokens=9, total_tokens=26),
            )
        assert purpose == "summarizer"
        return LLMResult(
            text="Use the database triage playbook first after checking the slow orders query evidence.",
            model="fake",
            usage=LLMUsage(prompt_tokens=11, completion_tokens=8, total_tokens=19),
        )

    def describe(self) -> dict[str, object]:
        return {"backend": "fake-live-text"}


def test_pure_text_open_live_api_slice_v1_runs_text_only_pack_and_writes_manifest_fields() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-live-text-open-") as tmpdir:
        result = run_pure_text_open_live_api_slice(
            out_dir=Path(tmpdir),
            repeat=1,
            llm_mode="deterministic",
        )
    assert result["manifest"]["task_pack"] == PURE_TEXT_OPEN_LIVE_API_PACK
    assert result["manifest"]["runtime_arms"] == ["external_text_live_api_open"]
    assert result["manifest"]["open_memory_policies"] == ["memory_off"]
    assert result["manifest"]["data_source"] == "live_api_text_only"
    assert result["manifest"]["runtime_contract"] == "pure_text_message_log_only"
    assert result["manifest"]["artifact_reuse"] is False
    assert result["manifest"]["statebus_contract_used"] is False
    assert result["manifest"]["selected_complexity_buckets"] == ["ambiguous", "distractor", "simple"]
    assert all(row["runtime_arm"] == "external_text_live_api_open" for row in result["tasks"])


def test_pure_text_open_live_api_slice_v1_does_not_send_oracle_fields_and_keeps_text_only_logs() -> None:
    fake = _LiveTextOpenFakeClient()
    with tempfile.TemporaryDirectory(prefix="statebus-live-text-open-fake-") as tmpdir:
        custom_pack = Path(tmpdir) / "custom_live_pack.yaml"
        custom_pack.write_text(
            """
task_set:
  name: custom_live_pack
  pack_type: pure_text_open_live_api_slice_v1
  description: test-only live text slice
  reading_contract: test-only
  claim_lanes: [communication, state_transfer]
  single_variable: true
  variable_axes: [external_text_runtime_contract]
  public_surface: audit_only
  plan_source_default: yaml
  evidence_tier: audit_only
  benchmark_version: v3
source_task_set: contest_honest_headline_v1
selected_task_ids:
  - rr-checkout-clean-text-001
  - rr-checkout-ambiguous-text-001
  - rr-deploy-distractor-text-001
tasks: []
""".strip(),
            encoding="utf-8",
        )
        result = run_pure_text_open_live_api_slice(
            out_dir=Path(tmpdir) / "out",
            repeat=1,
            task_set=custom_pack,
            llm_mode="api",
            llm_client=fake,
        )
    assert any(purpose == "planner" for purpose, _prompt in fake.calls)
    assert any(purpose == "summarizer" for purpose, _prompt in fake.calls)
    for row in result["tasks"]:
        assert row["data_source"] == "live_api_text_only"
        assert row["runtime_contract"] == "pure_text_message_log_only"
        assert row["statebus_contract_used"] is False
        assert row["metadata_oracle_used"] is False
        assert row["decision_source"] == "live_api_text_only"
        assert row["metrics"]["llm_total_tokens"] > 0
        assert all(isinstance(message, str) for message in row["message_log"])
        assert all("StateRef" not in message for message in row["message_log"])
        assert all("EXECUTOR_DECISION_PACKET" not in message for message in row["message_log"])
        assert all("FEATURE_BUNDLE" not in message for message in row["message_log"])


def test_langgraph_native_text_open_smoke_is_independent_from_statebus_replay_contract() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-langgraph-native-open-") as tmpdir:
        result = run_langgraph_native_text_open_smoke(out_dir=Path(tmpdir), repeat=1)
    assert result["manifest"]["runtime_arms"] == ["langgraph_native_text_open"]
    assert result["summary"][0]["replay_hit_rate"] > 0.0
    source_text = (REPO_ROOT / "eval" / "open_runner.py").read_text(encoding="utf-8")
    assert "from runtime.orchestrator import" not in source_text
    assert "Orchestrator" not in source_text
    assert "StateRef" not in source_text
    assert "StatePool" not in source_text
    assert "EXECUTOR_DECISION_PACKET" not in source_text
    for row in result["tasks"]:
        assert row["runtime_arm"] == "langgraph_native_text_open"
        assert row["statebus_contract_used"] is False
        assert all(isinstance(message, str) for message in row["message_log"])
        assert row["native_replay"]["backend"] == "langgraph.MemorySaver+InMemoryStore"


def test_audit_only_pack_keeps_failed_row_metadata_and_continues_remaining_tasks() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-audit-failure-continue-") as tmpdir:
        custom_pack = Path(tmpdir) / "audit_failure_pack.yaml"
        corpus_path = Path("tasks/contest_release_regression_corpus.yaml").resolve()
        custom_pack.write_text(
            (
                """
task_set:
  name: audit_failure_pack
  pack_type: ad_hoc
  description: Audit-only regression pack for failure-row metadata preservation.
  reading_contract: Read only as a runner regression for failed audit rows.
  claim_lanes: [state_transfer]
  evidence_tier: audit_only
  benchmark_version: v3
tasks:
- task_id: audit-failure-no-feature-001
  task_group: audit_failure_group
  task_order: 1
  task_theme: contest_release_checkout_regression
  benchmark_lane: state_transfer
  transfer_strategy: state_ref
  handoff_profile: protocol_full_rich_audit
  runtime_reuse_contract: reuse_disabled
  allowed_modes: [protocol]
  audit_disable_state_kinds: [FEATURE_BUNDLE]
  corpus_path: {corpus_path}
  goal: Use the cited release artifacts to triage the checkout regression and recommend the first action.
  query: checkout release 17.4 canary shows connection pool waits and slow orders query after rollout
  corpus_doc_ids: [rr-checkout-incident, rr-checkout-metrics, rr-checkout-logs, rr-checkout-worker-false]
  evidence_text: Force executor-side failure by deleting FEATURE_BUNDLE.
  tags: [release, checkout, latency, database, audit-failure]
  reuse_tags: [release, checkout, database]
  expected_reuse_mode: none
  summary_hint: 'Return four concise points only: most likely cause, strongest competing explanation ruled out, first action, and first validation check.'
  case_id: audit-failure-no-feature-001
  case_type: exact_single_solution
  eval_scope: case_level
  expected_family: db_pool_saturation
  primary_expected_route: db_pool_saturation
  primary_expected_tool: tool.db_pool_triage
  acceptable_routes: [db_pool_saturation]
  acceptable_tools: [tool.db_pool_triage]
  disallowed_families: []
  abstention_allowed: false
  allowed_abstain_tool: ""
  abstain_only_when: ""
  summary_contract: protocol_handoff_audit
- task_id: audit-failure-followup-001
  task_group: audit_failure_group
  task_order: 2
  task_theme: contest_release_checkout_regression
  benchmark_lane: state_transfer
  transfer_strategy: state_ref
  handoff_profile: protocol_full_rich_audit
  runtime_reuse_contract: reuse_disabled
  allowed_modes: [protocol]
  audit_disable_state_kinds: [CHANNEL_SNAPSHOT]
  corpus_path: {corpus_path}
  goal: Use the cited release artifacts to triage the checkout regression and recommend the first action.
  query: checkout release 17.4 canary shows connection pool waits and slow orders query after rollout
  corpus_doc_ids: [rr-checkout-incident, rr-checkout-metrics, rr-checkout-logs, rr-checkout-worker-false]
  evidence_text: This row should still run after the failed audit row.
  tags: [release, checkout, latency, database, audit-failure]
  reuse_tags: [release, checkout, database]
  expected_reuse_mode: none
  summary_hint: 'Return four concise points only: most likely cause, strongest competing explanation ruled out, first action, and first validation check.'
  case_id: audit-failure-followup-001
  case_type: exact_single_solution
  eval_scope: case_level
  expected_family: db_pool_saturation
  primary_expected_route: db_pool_saturation
  primary_expected_tool: tool.db_pool_triage
  acceptable_routes: [db_pool_saturation]
  acceptable_tools: [tool.db_pool_triage]
  disallowed_families: []
  abstention_allowed: false
  allowed_abstain_tool: ""
  abstain_only_when: ""
  summary_contract: protocol_handoff_audit
""".strip()
            ).format(corpus_path=corpus_path),
            encoding="utf-8",
        )
        result = asyncio.run(
            run_benchmark(
                task_set_path=custom_pack,
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir) / "out",
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    tasks = {task["task_id"]: task for task in result["mode_runs"]["protocol"][0]["tasks"]}
    failed = tasks["audit-failure-no-feature-001"]
    followup = tasks["audit-failure-followup-001"]
    mechanism = result["summary"]["protocol"]["mechanism_audit"]["disabled_kind_variants"]

    assert failed["status"] == "failed"
    assert failed["mode"] == "protocol"
    assert failed["handoff_profile"] == "protocol_full_rich_audit"
    assert failed["transfer_strategy"] == "channel_store_hashref"
    assert failed["audit_disable_state_kinds"] == ["FEATURE_BUNDLE"]
    assert "missing required input kinds" in str(failed["error"]) or "missing FEATURE_BUNDLE input" in str(failed["error"])
    assert followup["status"] == "completed"
    assert followup["audit_disable_state_kinds"] == ["CHANNEL_SNAPSHOT"]
    assert set(mechanism) >= {"disable_feature_bundle", "disable_channel_snapshot"}


def test_state_ref_minimal_slimming_audit_compares_minimal_feature_only_and_rich_variants() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-slimming-audit-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/state_ref_minimal_slimming_audit_benchmark.yaml",
                repeat=1,
                modes=("protocol",),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    tasks = {task["task_id"]: task for task in result["mode_runs"]["protocol"][0]["tasks"]}
    mechanism = result["summary"]["protocol"]["mechanism_audit"]["slimming_variants"]
    minimal = tasks["audit-slim-state-packet-minimal-001"]
    feature_only = tasks["audit-slim-feature-bundle-only-001"]
    rich = tasks["audit-slim-rich-state-ref-001"]

    assert minimal["transfer_strategy"] == "state_packet_minimal"
    assert "EXECUTOR_DECISION_PACKET" in minimal["transfer_truth_audit"]["executor_input_kinds"]
    assert "FEATURE_BUNDLE" in feature_only["transfer_truth_audit"]["executor_input_kinds"]
    assert "CHANNEL_SNAPSHOT" not in feature_only["transfer_truth_audit"]["executor_input_kinds"]
    assert "TOOL_CANDIDATE_SET" not in feature_only["transfer_truth_audit"]["executor_input_kinds"]
    assert "FEATURE_BUNDLE" in rich["transfer_truth_audit"]["executor_input_kinds"]
    assert "CHANNEL_SNAPSHOT" in rich["transfer_truth_audit"]["executor_input_kinds"]
    assert "TOOL_CANDIDATE_SET" in rich["transfer_truth_audit"]["executor_input_kinds"]

    assert 0.0 <= mechanism["state_packet_minimal"]["admissible_match_rate"] <= 1.0
    assert 0.0 <= mechanism["feature_bundle_only"]["admissible_match_rate"] <= 1.0
    assert 0.0 <= mechanism["full_rich_audit"]["admissible_match_rate"] <= 1.0
    assert mechanism["state_packet_minimal"]["admissible_match_rate"] <= mechanism["feature_bundle_only"]["admissible_match_rate"]
    assert mechanism["feature_bundle_only"]["admissible_match_rate"] <= mechanism["full_rich_audit"]["admissible_match_rate"]
    assert mechanism["state_packet_minimal"]["control_bytes"] < mechanism["feature_bundle_only"]["control_bytes"]
    assert mechanism["feature_bundle_only"]["control_bytes"] < mechanism["full_rich_audit"]["control_bytes"]
    assert mechanism["state_packet_minimal"]["state_transfer_count"] == mechanism["feature_bundle_only"]["state_transfer_count"]
    assert mechanism["feature_bundle_only"]["state_transfer_count"] < mechanism["full_rich_audit"]["state_transfer_count"]


def test_contest_dual_mode_controlled_v3_repeat_ten_exposes_formal_stability_metrics() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-contest-v3-repeat10-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="contest_dual_mode_controlled_v3",
                repeat=10,
                modes=("text", "protocol"),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (Path(tmpdir) / "benchmark_report.md").read_text(encoding="utf-8")
    for mode in ("text", "protocol"):
        stability = result["summary"][mode]["stability"]
        assert stability["message_count"]["mean"] > 0.0
        assert stability["control_bytes"]["mean"] > 0.0
        assert stability["task_ms"]["mean"] > 0.0
        assert "assist_memory_hit_rate" in stability
    assert result["summary"]["protocol"]["stability"]["state_transfer_count"]["mean"] > 0.0
    assert result["summary"]["text"]["run_failure_count"] == 0
    assert result["summary"]["protocol"]["run_failure_count"] == 0
    gate = result["manifest"]["formal_stability_gate"]
    assert gate["required_repeat"] == 10
    assert gate["repeat_satisfied"] is True
    assert gate["passed"] is True
    assert gate["mode_checks"]["text"]["passed"] is True
    assert gate["mode_checks"]["protocol"]["passed"] is True
    assert "Formal Stability Gate" in report_text


def test_contest_dual_mode_controlled_v3_repeat_one_does_not_pass_formal_stability_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-contest-v3-repeat1-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="contest_dual_mode_controlled_v3",
                repeat=1,
                modes=("text", "protocol"),
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    gate = result["manifest"]["formal_stability_gate"]
    assert gate["required_repeat"] == 10
    assert gate["repeat_satisfied"] is False
    assert gate["passed"] is False
    assert result["manifest"]["contest_formal_coverage_gate"]["matched_pair_count"] == 20
    assert result["manifest"]["contest_formal_coverage_gate"]["surface_complete"] is True
    assert result["manifest"]["contest_formal_coverage_gate"]["repeat_sufficient"] is False
    assert result["manifest"]["contest_formal_coverage_gate"]["passed"] is False
    assert result["manifest"]["object_parity_gate"]["passed"] is False
    assert result["manifest"]["object_parity_gate"]["text_hidden_field_leak_zero"] is False


def test_contest_formal_coverage_gate_distinguishes_surface_from_repeat() -> None:
    bundle = load_task_set_bundle("contest_honest_headline_v1")
    gate_full = _contest_formal_coverage_gate(list(bundle.tasks), repeat=1)
    assert gate_full["surface_complete"] is True
    assert gate_full["repeat_sufficient"] is False
    assert gate_full["passed"] is False

    reduced_tasks = [
        task
        for task in bundle.tasks
        if not str(task.task_id).startswith(("rr-cache-", "rr-deploy-"))
    ]
    gate_reduced = _contest_formal_coverage_gate(reduced_tasks, repeat=10)
    assert gate_reduced["surface_complete"] is False
    assert gate_reduced["repeat_sufficient"] is True
    assert gate_reduced["passed"] is False


def test_text_strict_pure_lane_consumes_explicit_handoff_without_executor_reroute() -> None:
    bundle = executor_runtime._feature_bundle_from_strict_pure_text_handoff(
        query_text="checkout canary order confirmations slowed after the rollout",
        handoff_text=(
            "Retriever handoff in plain language.\n"
            "User goal: triage checkout regression\n"
            "Query: checkout canary order confirmations slowed after the rollout\n"
            "Route: generic_triage\n"
            "Tool: tool.collect_more_evidence\n"
            "Route source: low_confidence_abstain\n"
            "Route confidence: 0.00\n"
            "Route provenance: lexical_below_threshold\n"
            "Matched signals: none\n"
            "Matched tags: none\n"
            "Retrieved docs: rr-checkout-incident, rr-checkout-scope\n"
            "Use only the cited evidence below. Do not assume any hidden route, tool, memory hint, or structured packet exists.\n"
            "Evidence:\n"
            "checkout confirmation path slowed after rollout\n"
        ),
        registry=default_tool_registry(),
    )
    assert bundle["route"] == "generic_triage"
    assert bundle["tool_name"] == "tool.collect_more_evidence"
    assert bundle["route_source"] == "low_confidence_abstain"


def test_natural_handoff_text_normalizes_sentence_punctuation_for_route_and_tool() -> None:
    bundle = executor_runtime._feature_bundle_from_natural_handoff(
        query_text="checkout canary order confirmations slowed after the rollout",
        evidence_text="checkout confirmation path slowed after rollout",
        handoff_text=(
            "Retriever handoff in plain language.\n"
            "Query: checkout canary order confirmations slowed after the rollout\n"
            "Route: db_pool_saturation.\n"
            "Tool: tool.db_pool_triage.\n"
            "Route source: lexical_match.\n"
            "Route confidence: 0.95\n"
            "Route provenance: lexical.\n"
            "Matched signals: pool wait, slow orders query.\n"
            "Matched tags: checkout.\n"
            "Retrieved docs: rr-checkout-incident, rr-checkout-scope.\n"
            "Evidence follows:\n"
            "checkout confirmation path slowed after rollout\n"
        ),
        registry=default_tool_registry(),
    )
    assert bundle["route"] == "db_pool_saturation"
    assert bundle["tool_name"] == "tool.db_pool_triage"
    assert bundle["route_source"] == "lexical_match"
    assert bundle["route_provenance"] == ["lexical"]
    assert select_tool_name(bundle) == "tool.db_pool_triage"


def test_communication_lane_keeps_memory_disabled_in_both_modes() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-communication-lane-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/communication_benchmark.yaml",
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
            assert task["metrics"]["assist_memory_hit_rate"] == 0.0


def test_memory_lane_separates_memory_policies() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-memory-lane-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="memory_reuse_v3",
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
    exact_replay = tasks["memory-cache-004"]
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
    assert exact_replay["runtime_reuse_contract"] == "exact_replay"
    assert exact_replay["reuse"]["mode"] in {"skip_retrieve_execute", "skip_execute", "none"}


def test_pack_specific_reports_do_not_mix_claim_surfaces() -> None:
    cases = {
        "memory_reuse_v3": ("Memory Reuse V3", ("task_match_rate", "formal_controlled", "open_validation")),
        "memory_policy_controlled_v3": (
            "Memory Policy Controlled V3",
            ("task_match_rate", "formal_controlled", "open_validation"),
        ),
        "typed_state_mechanism_v3": (
            "Typed State Mechanism V3",
            ("Support note:", "formal_controlled", "open_validation"),
        ),
        "external_text_baseline_audit_v3": (
            "External Text Baseline Audit V3",
            ("formal_controlled", "open_validation"),
        ),
        "typed_state_authenticity_v3": (
            "Legacy Compatibility",
            ("Support note:", "task_match_rate", "formal_controlled"),
        ),
        "text_definition_audit_v3": (
            "Text Definition Audit V3",
            ("Support note:", "task_match_rate", "formal_controlled"),
        ),
        "planner_support_v3": ("Planner Support V3", ("formal_controlled", "open_validation")),
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


def test_memory_policy_controlled_v3_report_stays_protocol_fixed() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-memory-policy-report-") as tmpdir:
        out_dir = Path(tmpdir)
        result = asyncio.run(
            run_benchmark(
                task_set_path="memory_policy_controlled_v3",
                repeat=1,
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (out_dir / "benchmark_report.md").read_text(encoding="utf-8")
    assert result["manifest"]["task_pack_type"] == "memory_policy_controlled_v3"
    assert "Memory Policy Controlled V3" in report_text
    assert "state_packet_minimal" in report_text
    assert "reuse_disabled" in report_text
    assert "Replay proof" in report_text
    assert "auth_rotation_chain" in report_text


def test_benchmark_supports_shared_memory_statepool_backend() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-shm-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="tasks/communication_benchmark.yaml",
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
                        semantic_role="execute",
                    ),
                    input_state_refs=[evidence_ref, feature_ref],
                ),
            )
            assert isinstance(response, RemoteStepResponse)
            assert response.result.success is True
            assert response.result.payload["tool_name"] == "tool.cache_invalidation_playbook"
            artifact_ref = response.result.output_state_refs[0]
            assert artifact_ref.kind == "TOOL_ARTIFACT"
            assert artifact_ref.storage == "CAS_BLOB"
            assert artifact_ref.blob_hash
            assert statepool.has_blob(artifact_ref.blob_hash)
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
    assert first_task["metrics"]["blob_fetch_count"] > 0
    assert first_task["metrics"]["blob_fetch_bytes"] > 0
    aggregate = result["summary"]["protocol"]["aggregate"]
    assert aggregate["blob_fetch_count"] > 0
    assert aggregate["blob_fetch_bytes"] > 0
    assert 0.0 <= aggregate["blob_cache_hit_rate"] <= 1.0


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
    expected = {
        "exec-low-confidence-001": ("low_confidence_abstain", "tool.collect_more_evidence", 0.0),
        "exec-thin-support-001": ("low_confidence_abstain", "tool.collect_more_evidence", 0.0),
        "exec-conflict-thin-override-001": ("low_confidence_abstain", "tool.collect_more_evidence", 0.0),
        "exec-metadata-only-001": ("fallback", "tool.collect_more_evidence", 0.0),
        "exec-ambiguous-001": ("ambiguous_candidates_abstain", "tool.collect_more_evidence", 0.0),
        "exec-clear-worker-001": ("lexical_match", "tool.worker_queue_triage", 0.95),
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
        assert "validated_replay" in report_text
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
            "cache-invalid-replay",
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
        assert "Protocol Compliance" in report_text
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
        assert "Protocol Compliance" in report_text
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
        assert "Protocol Compliance" in report_text
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
        assert "Protocol Compliance" in report_text
        assert "fresh_retrieval" in report_text
    expected_task_ids = {
        "diag-retrieval-weak-route-cache-invalidation-001",
        "diag-retrieval-weak-route-cache-replica-001",
        "diag-retrieval-weak-route-latency-db-001",
        "diag-retrieval-weak-route-latency-worker-001",
        "diag-retrieval-weak-route-session-drift-001",
        "diag-retrieval-weak-route-session-rate-limit-001",
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
        assert set(tasks) == expected_task_ids
        for task_id in expected_task_ids:
            task = tasks[task_id]
            retrieve_payload = task["results"]["retrieve"]["payload"]
            execute_payload = task["results"]["execute"]["payload"]
            assert task["reuse"]["mode"] == "none"
            assert task["reuse_validation"]["matched_expectation"] is True
            assert retrieve_payload["feature_route"]
            assert execute_payload["route"] == retrieve_payload["feature_route"]
            assert execute_payload["tool_name"].startswith("tool.")
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
        assert "Protocol Compliance" in report_text
        assert "fresh_retrieval" in report_text
    expected_task_ids = {
        "diag-retrieval-theme-variant-latency-db-001",
        "diag-retrieval-theme-variant-latency-worker-001",
        "diag-retrieval-theme-variant-session-drift-001",
        "diag-retrieval-theme-variant-session-rate-limit-001",
        "diag-retrieval-theme-variant-cache-invalidation-001",
        "diag-retrieval-theme-variant-cache-replica-001",
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
        assert set(tasks) == expected_task_ids
        for task_id in expected_task_ids:
            task = tasks[task_id]
            retrieve_payload = task["results"]["retrieve"]["payload"]
            assert task["reuse"]["mode"] == "none"
            assert task["reuse_validation"]["matched_expectation"] is True
            assert retrieve_payload["feature_route"]
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
        assert "validated_replay" in report_text
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
        assert anchor_b["reuse"]["mode"] == "skip_execute"
        assert anchor_b["results"]["retrieve"]["skipped"] is False
        assert anchor_b["results"]["execute"]["skipped"] is True
        assert anchor_b["results"]["retrieve"]["payload"]["retrieved_doc_ids"]

        exact = tasks["diag-replay-multi-anchor-exact-001"]
        assert exact["reuse"]["mode"] == "skip_retrieve_execute"
        assert exact["results"]["retrieve"]["skipped"] is True
        assert exact["results"]["execute"]["skipped"] is True
        assert exact["results"]["retrieve"]["payload"]["retrieved_doc_ids"]
        assert exact["results"]["retrieve"]["reused_from_memory_id"] in {
            "mem-diag-replay-multi-anchor-a-001-replay",
            "mem-diag-replay-multi-anchor-b-001-replay",
        }


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
        assert "validated_replay" in report_text
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
        assert clear_anchor["results"]["retrieve"]["payload"]["feature_route_source"] == "lexical_match"

        clear_exact = tasks["diag-replay-route-clear-exact-001"]
        assert clear_exact["reuse"]["mode"] == "skip_retrieve_execute"
        assert clear_exact["results"]["retrieve"]["skipped"] is True
        assert clear_exact["results"]["execute"]["skipped"] is True
        assert clear_exact["results"]["retrieve"]["payload"]["feature_route"] == "worker_queue_starvation"
        assert clear_exact["results"]["retrieve"]["payload"]["feature_route_source"] == "lexical_match"
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
        assert "validated_replay" in report_text
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
        assert anchor["results"]["retrieve"]["payload"]["feature_route"]
        assert "lexical" in anchor["results"]["retrieve"]["payload"]["feature_route_source"]
        assert "lexical" in anchor["results"]["retrieve"]["payload"]["feature_route_provenance"]

        validated = tasks["diag-replay-override-validated-001"]
        assert validated["reuse"]["mode"] == "skip_execute"
        assert validated["results"]["retrieve"]["skipped"] is False
        assert validated["results"]["execute"]["skipped"] is True
        assert validated["results"]["retrieve"]["payload"]["feature_route"] == anchor["results"]["retrieve"]["payload"]["feature_route"]
        assert "lexical" in validated["results"]["retrieve"]["payload"]["feature_route_source"]
        assert "lexical" in validated["results"]["retrieve"]["payload"]["feature_route_provenance"]
        assert validated["reuse_validation"]["matched_expectation"] is True

        exact = tasks["diag-replay-override-exact-001"]
        assert exact["reuse"]["mode"] == "skip_retrieve_execute"
        assert exact["results"]["retrieve"]["skipped"] is True
        assert exact["results"]["execute"]["skipped"] is True
        assert exact["results"]["retrieve"]["payload"]["feature_route"] == anchor["results"]["retrieve"]["payload"]["feature_route"]
        assert "lexical" in exact["results"]["retrieve"]["payload"]["feature_route_source"]
        assert "lexical" in exact["results"]["retrieve"]["payload"]["feature_route_provenance"]
        assert exact["results"]["retrieve"]["reused_from_memory_id"]


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
        assert "validated_replay" in report_text
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
        assert anchor["results"]["retrieve"]["payload"]["feature_route"]
        assert "lexical" in anchor["results"]["retrieve"]["payload"]["feature_route_source"]
        assert "lexical" in anchor["results"]["retrieve"]["payload"]["feature_route_provenance"]

        validated = tasks["diag-replay-override-cache-validated-001"]
        assert validated["reuse"]["mode"] == "skip_execute"
        assert validated["results"]["retrieve"]["skipped"] is False
        assert validated["results"]["execute"]["skipped"] is True
        assert validated["results"]["retrieve"]["payload"]["feature_route"] == anchor["results"]["retrieve"]["payload"]["feature_route"]
        assert "lexical" in validated["results"]["retrieve"]["payload"]["feature_route_source"]
        assert "lexical" in validated["results"]["retrieve"]["payload"]["feature_route_provenance"]
        assert validated["reuse_validation"]["matched_expectation"] is True

        exact = tasks["diag-replay-override-cache-exact-001"]
        assert exact["reuse"]["mode"] == "skip_retrieve_execute"
        assert exact["results"]["retrieve"]["skipped"] is True
        assert exact["results"]["execute"]["skipped"] is True
        assert exact["results"]["retrieve"]["payload"]["feature_route"] == anchor["results"]["retrieve"]["payload"]["feature_route"]
        assert "lexical" in exact["results"]["retrieve"]["payload"]["feature_route_source"]
        assert "lexical" in exact["results"]["retrieve"]["payload"]["feature_route_provenance"]
        assert exact["results"]["retrieve"]["reused_from_memory_id"]


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
        assert "validated_replay" in report_text
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
            assert "lexical" in retrieve_payload["feature_route_source"]
            assert "lexical" in retrieve_payload["feature_route_provenance"]
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
        assert "Protocol Compliance" in report_text
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
            assert "lexical" in retrieve_payload["feature_route_source"]
            assert "lexical" in retrieve_payload["feature_route_provenance"]
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
            assert "lexical" in retrieve_payload["feature_route_source"]
            assert "lexical" in retrieve_payload["feature_route_provenance"]
            assert task["reuse_validation"]["matched_expectation"] is True
        for task_id, route in exact_negative.items():
            task = tasks[task_id]
            assert task["reuse"]["mode"] == "none"
            retrieve_payload = task["results"]["retrieve"]["payload"]
            assert retrieve_payload["feature_route"] == route
            assert "lexical" in retrieve_payload["feature_route_source"]
            assert "lexical" in retrieve_payload["feature_route_provenance"]
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
                task_set_path="tasks/internal_regression_benchmark.yaml",
                repeat=1,
                out_dir=out_dir,
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        second = asyncio.run(
            run_benchmark(
                task_set_path="tasks/internal_regression_benchmark.yaml",
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
                task_set_path="tasks/communication_benchmark.yaml",
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
def test_contest_honest_headline_v1_uses_text_whole_lane_and_protocol_minimal() -> None:
    bundle = load_task_set_bundle("contest_honest_headline_v1")
    assert bundle.metadata.pack_type == "contest_honest_headline_v1"
    assert bundle.metadata.public_surface == "formal_headline"
    assert bundle.metadata.single_variable is True
    assert bundle.metadata.variable_axes == ("mode",)
    text_tasks = [task for task in bundle.tasks if task.supports_mode("text")]
    protocol_tasks = [task for task in bundle.tasks if task.supports_mode("protocol")]
    assert text_tasks
    assert protocol_tasks
    assert all(task.transfer_strategy == "text_whole_lane" for task in text_tasks)
    assert all(task.handoff_profile == "text_whole_lane" for task in text_tasks)
    assert all(task.transfer_strategy == "state_packet_minimal" for task in protocol_tasks)
    assert all(task.handoff_profile == "protocol_minimal_state_packet" for task in protocol_tasks)


def test_contest_honest_headline_v1_report_uses_new_surface_name() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-contest-honest-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="contest_honest_headline_v1",
                repeat=1,
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
        report_text = (Path(tmpdir) / "benchmark_report.md").read_text(encoding="utf-8")
    assert result["manifest"]["task_pack_type"] == "contest_honest_headline_v1"
    assert "Contest Honest Headline V1" in report_text
    assert "Formal headline reads `text_whole_lane` vs `state_packet_minimal` only." in report_text
    assert "## State-Transfer Headline" in report_text
    assert "this contest-facing v3 state-transfer read compares natural whole-lane text against protocol minimal state packets on the same controlled tasks." in report_text
    assert "## Thickness Admission Gate" in report_text
    assert "static_contract_complete" in report_text
    assert "runtime_shape_ready" in report_text
    assert "| mode / handoff | task_count | control_bytes | handoff_wire_bytes |" in report_text
    assert "| text / text_whole_lane |" in report_text
    assert "| delta(protocol/state_packet_minimal - text/text_whole_lane) |" in report_text


def test_contest_honest_headline_v1_rows_emit_thickness_contract_fields() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-contest-honest-rows-") as tmpdir:
        result = asyncio.run(
            run_benchmark(
                task_set_path="contest_honest_headline_v1",
                repeat=1,
                out_dir=Path(tmpdir),
                embedder=DeterministicEmbeddingProvider(),
                llm_client=DeterministicLLMClient(),
            )
        )
    text_task = result["mode_runs"]["text"][0]["tasks"][0]
    manifest_gate = result["manifest"]["headline_thickness_admission_gate"]
    s1_runtime_gate = result["manifest"]["headline_s1_runtime_behavior_gate"]
    s2_prior_gate = result["manifest"]["headline_s2_prior_action_gate"]
    memory_replay_gate = result["manifest"]["headline_memory_replay_effect_gate"]
    assert text_task["case_id"]
    assert text_task["case_type"] == "bounded_alternative"
    assert text_task["thickness_setting"] in {"S1", "S2"}
    assert int(text_task["reasoning_hops_min"]) >= 2
    assert int(text_task["dependency_depth"]) >= 1
    assert len(text_task["expected_intermediate_decisions"]) >= 2
    assert text_task["abstention_boundary"]
    assert text_task["required_plan_semantic_roles"] == [
        "retrieve",
        "validate",
        "execute",
        "summarize",
    ]
    for mode in ("text", "protocol"):
        task_rows = [
            task
            for run in result["mode_runs"][mode]
            for task in run["tasks"]
            if task["thickness_setting"] == "S1"
        ]
        assert task_rows
        assert all(task["results"]["validate"]["success"] is True for task in task_rows)
        assert all(
            task["results"]["validate"]["payload"]["validated_action_contract"]
            in {"execute_validated_tool", "abstain_collect_more_evidence"}
            for task in task_rows
        )
        assert all(
            task["results"]["execute"]["payload"]["validation_gate_applied"] is True
            for task in task_rows
        )
        assert any(
            task["results"]["validate"]["payload"]["validation_changed_action"] is True
            and task["results"]["execute"]["payload"]["validation_changed_action"] is True
            for task in task_rows
        )
        if mode == "text":
            assert all(
                task["results"]["execute"]["payload"]["validation_decision_source"]
                == "validation_text_handoff"
                for task in task_rows
            )
            assert all(task["whole_lane_text_guard"]["passed"] is True for task in task_rows)
            assert all(
                task["whole_lane_text_guard"]["executor_input_kinds"] == ["TOOL_ARTIFACT"]
                for task in task_rows
            )
        else:
            assert all(
                task["results"]["execute"]["payload"]["validation_decision_source"]
                == "validation_gate"
                for task in task_rows
            )
        changed_rows = [
            task
            for task in task_rows
            if task["results"]["validate"]["payload"]["validation_changed_action"] is True
        ]
        assert changed_rows
        assert all(
            task["results"]["validate"]["payload"]["pre_validation_tool_name"]
            != task["results"]["validate"]["payload"]["validated_tool_name"]
            for task in changed_rows
        )
        assert all(
            task["results"]["execute"]["payload"]["pre_validation_tool_name"]
            != task["results"]["execute"]["payload"]["tool_name"]
            for task in changed_rows
        )
        assert all(
            task["results"]["execute"]["payload"]["tool_name"]
            == task["results"]["validate"]["payload"]["validated_tool_name"]
            for task in task_rows
        )
        decisive_rows = [
            task
            for task in task_rows
            if task["results"]["validate"]["payload"]["validated_action_contract"]
            == "execute_validated_tool"
        ]
        assert decisive_rows
    assert manifest_gate["applicable"] is True
    assert manifest_gate["static_contract_complete"] is True
    assert manifest_gate["runtime_shape_ready"] is True
    assert manifest_gate["admission_ready"] is True
    assert s1_runtime_gate["s1_runtime_behavior_ready"] is True
    assert s1_runtime_gate["changed_action_by_mode"]["text"] > 0
    assert s1_runtime_gate["changed_action_by_mode"]["protocol"] > 0
    assert s2_prior_gate["applicable"] is True
    assert s2_prior_gate["s2_prior_action_ready"] is True
    assert s2_prior_gate["prior_dependent_action_change_by_mode"]["text"] > 0
    assert s2_prior_gate["prior_dependent_action_change_by_mode"]["protocol"] > 0
    assert memory_replay_gate["applicable"] is True
    assert memory_replay_gate["s2_row_count"] == 10
    assert memory_replay_gate["expected_replay_row_count"] == 10
    assert memory_replay_gate["actual_replay_row_count"] == 10
    assert memory_replay_gate["actual_replay_by_mode"] == {"protocol": 5, "text": 5}
    assert memory_replay_gate["skipped_step_count"] > 0
    assert memory_replay_gate["reuse_gain_positive_count"] == 10
    for mode in ("text", "protocol"):
        s2_rows = [
            task
            for run in result["mode_runs"][mode]
            for task in run["tasks"]
            if task["thickness_setting"] == "S2"
        ]
        assert s2_rows
        assert all(task["expected_reuse_mode"] == "skip_execute" for task in s2_rows)
        assert all(task["runtime_reuse_contract"] == "validated_replay" for task in s2_rows)
        assert all(
            task["results"]["validate"]["payload"]["s2_prior_dependency_required"] is True
            for task in s2_rows
        )
        assert all(
            task["results"]["validate"]["payload"]["s2_prior_dependency_satisfied"] is True
            for task in s2_rows
        )
        assert all(
            task["results"]["validate"]["payload"]["s2_without_prior_tool_name"]
            == "tool.collect_more_evidence"
            for task in s2_rows
        )
        assert all(
            task["results"]["validate"]["payload"]["s2_with_prior_tool_name"]
            != task["results"]["validate"]["payload"]["s2_without_prior_tool_name"]
            for task in s2_rows
        )
        assert all(
            task["results"]["execute"]["payload"]["s2_prior_dependent_action_change"] is True
            for task in s2_rows
        )
        assert all(task["reuse"]["mode"] == "skip_execute" for task in s2_rows)
        assert all(task["metrics"]["skipped_step_count"] == 1 for task in s2_rows)
        assert all(task["metrics"]["reuse_gain"] > 0 for task in s2_rows)
