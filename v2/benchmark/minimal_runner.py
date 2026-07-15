from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from v2.benchmark.models import (
    BenchmarkCaseReport,
    BenchmarkFamilyReport,
    BenchmarkLayer,
    BenchmarkLayerProfile,
    BenchmarkRunReport,
    BenchmarkSuiteReport,
    QualityFloorResult,
)
from v2.benchmark.metric_aggregation import finalize_case_telemetry_summary
from v2.benchmark.reporting import family_report_to_dict, suite_report_to_dict, write_json_report
from v2.contracts import CanonicalTaskSpec
from v2.runtime import TelemetryEmitter, TelemetryEvent
from v2.runtime.smoke import SmokeLayerConfig, SmokeResult, run_smoke
from v2.utils import stable_json_dumps


LAYER_PROFILES: dict[BenchmarkLayer, BenchmarkLayerProfile] = {
    BenchmarkLayer.L0: BenchmarkLayerProfile(
        layer=BenchmarkLayer.L0,
        description="pure text cold baseline",
        structured_control_enabled=False,
        semantic_pruning_enabled=False,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L1: BenchmarkLayerProfile(
        layer=BenchmarkLayer.L1,
        description="typed control only",
        structured_control_enabled=True,
        semantic_pruning_enabled=False,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L2: BenchmarkLayerProfile(
        layer=BenchmarkLayer.L2,
        description="typed control plus semantic pruning",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L3: BenchmarkLayerProfile(
        layer=BenchmarkLayer.L3,
        description="full replay stack",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=True,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
}


LAYER_SMOKE_CONFIGS: dict[BenchmarkLayer, SmokeLayerConfig] = {
    BenchmarkLayer.L0: SmokeLayerConfig(
        layer_name="L0",
        handoff_mode="text_collaboration",
        structured_control_enabled=False,
        semantic_pruning_enabled=False,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L1: SmokeLayerConfig(
        layer_name="L1",
        structured_control_enabled=True,
        semantic_pruning_enabled=False,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L2: SmokeLayerConfig(
        layer_name="L2",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L3: SmokeLayerConfig(
        layer_name="L3",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=True,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
}


def _default_canonical_task_spec_schema_version() -> str:
    return CanonicalTaskSpec(task_family="", intent_op="").schema_version


def _canonical_task_spec_from_payload(payload: dict[str, object]) -> CanonicalTaskSpec:
    schema_version = payload.get("schema_version")
    return CanonicalTaskSpec(
        task_family=str(payload["task_family"]),
        intent_op=str(payload["intent_op"]),
        target_entities=tuple(str(item) for item in payload.get("target_entities", [])),
        time_scope=str(payload.get("time_scope", "")),
        required_outputs=tuple(str(item) for item in payload.get("required_outputs", [])),
        required_tools=tuple(str(item) for item in payload.get("required_tools", [])),
        arguments=dict(payload.get("arguments", {})),
        schema_version=str(schema_version) if schema_version is not None else _default_canonical_task_spec_schema_version(),
    )


@dataclass(frozen=True)
class MinimalBenchmarkSample:
    task_id: str
    request_text: str
    canonical_task_spec: CanonicalTaskSpec | None = None
    expected_artifact_type: str = "json"
    task_family: str = "financial_report_analysis"
    expected_facts: dict[str, object] | None = None
    scenario_tags: tuple[str, ...] = ()

    @classmethod
    def from_path(cls, path: Path) -> "MinimalBenchmarkSample":
        payload = json.loads(path.read_text(encoding="utf-8"))
        request_text = payload["request_text"]
        if not isinstance(request_text, str):
            request_text = stable_json_dumps(request_text)
        canonical_payload = payload.get("canonical_task_spec")
        canonical_task_spec = None
        if isinstance(canonical_payload, dict):
            canonical_task_spec = _canonical_task_spec_from_payload(canonical_payload)
        return cls(
            task_id=str(payload["task_id"]),
            request_text=request_text,
            canonical_task_spec=canonical_task_spec,
            expected_artifact_type=str(payload.get("expected_artifact_type", "json")),
            task_family=str(payload.get("task_family", "financial_report_analysis")),
            expected_facts=dict(payload.get("expected_facts", {})) or None,
            scenario_tags=tuple(str(tag) for tag in payload.get("scenario_tags", [])),
        )


def load_sample_family(directory: Path) -> list[MinimalBenchmarkSample]:
    return [
        MinimalBenchmarkSample.from_path(path)
        for path in sorted(directory.glob("*.json"))
    ]


def _quality_floor_from_smoke(smoke: SmokeResult) -> QualityFloorResult:
    return smoke.quality_floor


def _report_from_smoke(
    sample: MinimalBenchmarkSample,
    smoke: SmokeResult,
    *,
    task_ms: float | None = None,
) -> BenchmarkRunReport:
    metrics = {
        "telemetry_event_count": float(smoke.telemetry_event_count),
        "registry_path_length": float(len(smoke.registry_path)),
        "output_artifact_path_length": float(len(smoke.output_artifact_path)),
        "workflow_step_count": float(smoke.workflow_step_count),
        "attempt_count": float(smoke.attempt_count),
        "runtime_replan_count": float(smoke.runtime_replan_count),
    }
    if task_ms is not None:
        metrics["task_ms"] = float(task_ms)
    return BenchmarkRunReport(
        layer=BenchmarkLayer.L3,
        task_family=sample.task_family,
        quality_floor=_quality_floor_from_smoke(smoke),
        metrics=metrics,
    )


def _case_from_smoke(
    sample: MinimalBenchmarkSample,
    smoke: SmokeResult,
    *,
    task_ms: float,
) -> BenchmarkCaseReport:
    return BenchmarkCaseReport(
        task_id=sample.task_id,
        task_family=sample.task_family,
        quality_floor=_quality_floor_from_smoke(smoke),
        replay_class=smoke.replay_class,
        telemetry_event_count=smoke.telemetry_event_count,
        output_artifact_hash=smoke.output_artifact_hash,
        output_artifact_path=smoke.output_artifact_path,
        workspace_root=smoke.workspace_root,
        session_state=smoke.session_state,
        comparison_tags=sample.scenario_tags,
        audit_paths={
            "replay": smoke.replay_audit_path,
            "hydration": smoke.hydration_audit_path,
            "hydration_debug": smoke.hydration_debug_audit_path,
            "artifact": smoke.artifact_audit_path,
        },
        audit_summary=smoke.audit_summary,
        metrics={
            **dict(sorted(smoke.task_metrics.items())),
            "response_count": float(len(smoke.response_sequence)),
            "lineage_verified_artifact_count": float(len(smoke.lineage_view.verified_artifact_ids)),
            "workflow_step_count": float(smoke.workflow_step_count),
            "completed_workflow_step_count": float(smoke.completed_workflow_step_count),
            "replan_history_count": float(smoke.replan_history_count),
            "task_ms": float(task_ms),
        },
    )


def _prepare_case_root(root: Path) -> Path:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def run_minimal_benchmark(
    *,
    sample: MinimalBenchmarkSample,
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    role_path_mode: str = "deterministic",
    embedding_mode: str = "deterministic",
    seed_replay_memory: bool = False,
    state_pool_mode: str = "auto",
    persistence_profile: str = "audit_full",
    executor_transport: str = "loopback",
) -> tuple[SmokeResult, BenchmarkRunReport]:
    _prepare_case_root(workspace_root)
    _prepare_case_root(runtime_root)
    layer_config = SmokeLayerConfig(
        **{
            **LAYER_SMOKE_CONFIGS[BenchmarkLayer.L3].__dict__,
            "role_path_mode": role_path_mode,
            "embedding_mode": embedding_mode,
            "state_pool_mode": state_pool_mode,
            "persistence_profile": persistence_profile,
            "executor_transport": executor_transport,
        }
    )
    start_ns = time.perf_counter_ns()
    smoke = run_smoke(
        workspace_root=workspace_root,
        runtime_root=runtime_root,
        socket_path=socket_path,
        request_text=sample.request_text,
        canonical_task_spec=sample.canonical_task_spec,
        task_id=sample.task_id,
        layer_config=layer_config,
        expected_facts=sample.expected_facts,
        seed_replay_memory=seed_replay_memory,
    )
    task_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
    return smoke, _report_from_smoke(sample, smoke, task_ms=task_ms)


def run_minimal_benchmark_family(
    *,
    samples: list[MinimalBenchmarkSample],
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str = "minimal-family",
    layer: BenchmarkLayer = BenchmarkLayer.L3,
    role_path_mode: str = "deterministic",
    embedding_mode: str = "deterministic",
    seed_replay_memory: bool = False,
    benchmark_tier: str = "formal",
    claim_level: str = "first_pass",
    state_pool_mode: str = "auto",
    persistence_profile: str = "audit_full",
    executor_transport: str = "loopback",
) -> BenchmarkFamilyReport:
    profile = LAYER_PROFILES[layer]
    cases: list[BenchmarkCaseReport] = []
    suite_emitter = TelemetryEmitter()
    layer_workspace_root = _prepare_case_root(workspace_root)
    for sample in samples:
        case_runtime_root = _prepare_case_root(runtime_root / sample.task_id)
        start_ns = time.perf_counter_ns()
        smoke = run_smoke(
            workspace_root=layer_workspace_root,
            runtime_root=case_runtime_root,
            socket_path=socket_path.with_name(
                f"{socket_path.stem}-{layer.value.lower()}-{sample.task_id}{socket_path.suffix}"
            ),
            request_text=sample.request_text,
            canonical_task_spec=sample.canonical_task_spec,
            task_id=sample.task_id,
            layer_config=SmokeLayerConfig(
                **{
                    **LAYER_SMOKE_CONFIGS[layer].__dict__,
                    "role_path_mode": role_path_mode,
                    "embedding_mode": embedding_mode,
                    "state_pool_mode": state_pool_mode,
                    "persistence_profile": persistence_profile,
                    "executor_transport": executor_transport,
                }
            ),
            expected_facts=sample.expected_facts,
            seed_replay_memory=seed_replay_memory,
        )
        task_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
        cases.append(_case_from_smoke(sample, smoke, task_ms=task_ms))
        suite_emitter.emit(
            TelemetryEvent.create(
                trace_id=f"suite:{suite_id}",
                task_id=sample.task_id,
                event_type="TASK_SUMMARY_METRICS",
                metrics=smoke.task_metrics,
            )
        )

    aggregated_metrics = {
        "case_count": float(len(cases)),
        "quality_floor_pass_count": float(sum(1 for case in cases if case.quality_floor.quality_floor_pass)),
        "telemetry_event_count": float(sum(case.telemetry_event_count for case in cases)),
    }
    telemetry_summary = finalize_case_telemetry_summary(
        suite_emitter.summarize_suite([case.task_id for case in cases]),
        cases,
    )
    replay_class_distribution: dict[str, float] = {}
    quality_floor_breakdown = {
        "deterministic_checks_passed_count": float(
            sum(1 for case in cases if case.quality_floor.deterministic_checks_passed)
        ),
        "fact_coverage_passed_count": float(sum(1 for case in cases if case.quality_floor.fact_coverage_passed)),
        "quality_floor_pass_count": aggregated_metrics["quality_floor_pass_count"],
    }
    for case in cases:
        replay_class_distribution[case.replay_class] = replay_class_distribution.get(case.replay_class, 0.0) + 1.0
    state_pool_mode_used = (
        "memfd"
        if telemetry_summary.get("memfd_transfer_count", 0.0) > 0.0
        else "shared_memory"
        if telemetry_summary.get("state_pool_shared_memory_mode_count", 0.0) > 0.0
        else "mmap_file"
        if telemetry_summary.get("state_pool_mmap_mode_count", 0.0) > 0.0
        else state_pool_mode
    )
    task_family = cases[0].task_family if cases else "financial_report_analysis"
    family_tier = (
        "formal_registry"
        if benchmark_tier == "formal" and len({case.task_family for case in cases}) > 1
        else "formal_financial"
        if benchmark_tier == "formal"
        else "dev"
    )
    report_path = runtime_root / "benchmark_reports" / f"{suite_id}-{layer.value}.json"
    family_report = BenchmarkFamilyReport(
        suite_id=suite_id,
        layer=layer,
        task_family=task_family,
        profile=profile,
        cases=tuple(cases),
        aggregated_metrics=aggregated_metrics,
        telemetry_summary=telemetry_summary,
        replay_class_distribution=replay_class_distribution,
        quality_floor_breakdown=quality_floor_breakdown,
        metadata={
            "benchmark_tier": benchmark_tier,
            "claim_level": claim_level,
            "embedding_mode": embedding_mode,
            "formal_comparator_eligible": False,
            "quality_floor_contract": "statebus_smoke_quality_floor_v1",
            "role_graph": "planner->retriever->executor->summarizer",
            "role_path_mode": role_path_mode,
            "state_pool_mode": state_pool_mode,
            "state_pool_mode_requested": state_pool_mode,
            "state_pool_mode_used": state_pool_mode_used,
            "transport": executor_transport,
            "scoring_contract": "statebus_smoke_quality_floor_v1",
            "seed_replay_memory": seed_replay_memory,
            "task_family_tier": family_tier,
            "uses_internal_helpers": False,
        },
        report_path=str(report_path),
    )
    write_json_report(report_path, family_report_to_dict(family_report))
    return family_report


def run_minimal_benchmark_suite(
    *,
    samples: list[MinimalBenchmarkSample],
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str = "minimal-suite",
    role_path_mode: str = "deterministic",
    embedding_mode: str = "deterministic",
    seed_replay_memory_by_layer: dict[BenchmarkLayer, bool] | None = None,
    benchmark_tier: str = "formal",
    claim_level: str = "first_pass",
    state_pool_mode: str = "auto",
    persistence_profile: str = "audit_full",
    executor_transport: str = "loopback",
) -> BenchmarkSuiteReport:
    seed_replay_memory_by_layer = seed_replay_memory_by_layer or {}
    layer_reports = tuple(
        run_minimal_benchmark_family(
            samples=samples,
            workspace_root=workspace_root / layer.value,
            runtime_root=runtime_root / layer.value,
            socket_path=socket_path.with_name(f"{socket_path.stem}-{layer.value}{socket_path.suffix}"),
            suite_id=suite_id,
            layer=layer,
            role_path_mode=role_path_mode,
            embedding_mode=embedding_mode,
            seed_replay_memory=seed_replay_memory_by_layer.get(layer, False),
            benchmark_tier=benchmark_tier,
            claim_level=claim_level,
            state_pool_mode=state_pool_mode,
            persistence_profile=persistence_profile,
            executor_transport=executor_transport,
        )
        for layer in BenchmarkLayer
    )
    l3_report = layer_reports[3]
    formal_families = tuple(dict.fromkeys(sample.task_family for sample in samples))
    state_pool_mode_used = (
        "memfd"
        if l3_report.telemetry_summary.get("memfd_transfer_count", 0.0) > 0.0
        else "shared_memory"
        if l3_report.telemetry_summary.get("state_pool_shared_memory_mode_count", 0.0) > 0.0
        else "mmap_file"
        if l3_report.telemetry_summary.get("state_pool_mmap_mode_count", 0.0) > 0.0
        else state_pool_mode
    )
    text_l0_report = layer_reports[0]
    protocol_l3_report = layer_reports[3]
    text_l0_total_tokens = text_l0_report.telemetry_summary.get("llm_total_tokens", 0.0)
    text_l0_prompt_tokens = text_l0_report.telemetry_summary.get("llm_prompt_tokens", 0.0)
    text_l0_prompt_bytes = text_l0_report.telemetry_summary.get("llm_prompt_bytes", 0.0)
    text_l0_control_bytes = text_l0_report.telemetry_summary.get("control_bytes", 0.0)
    text_l0_quality_pass_count = text_l0_report.aggregated_metrics.get("quality_floor_pass_count", 0.0)
    protocol_l3_total_tokens = protocol_l3_report.telemetry_summary.get("llm_total_tokens", 0.0)
    protocol_l3_prompt_tokens = protocol_l3_report.telemetry_summary.get("llm_prompt_tokens", 0.0)
    protocol_l3_prompt_bytes = protocol_l3_report.telemetry_summary.get("llm_prompt_bytes", 0.0)
    protocol_l3_control_bytes = protocol_l3_report.telemetry_summary.get("control_bytes", 0.0)
    protocol_l3_quality_pass_count = protocol_l3_report.aggregated_metrics.get("quality_floor_pass_count", 0.0)
    waterfall_metrics = {
        "L0_case_count": float(len(layer_reports[0].cases)),
        "L0_raw_evidence_bytes_seen_by_llm": layer_reports[0].telemetry_summary.get(
            "raw_evidence_bytes_seen_by_llm", 0.0
        ),
        "L1_control_bytes": layer_reports[1].telemetry_summary.get("control_bytes", 0.0),
        "L1_control_message_count": layer_reports[1].telemetry_summary.get("control_message_count", 0.0),
        "L2_semantic_state_transfer_count": layer_reports[2].telemetry_summary.get(
            "semantic_state_transfer_count", 0.0
        ),
        "L2_memory_match_count": layer_reports[2].telemetry_summary.get("memory_match_count", 0.0),
        "L3_quality_floor_pass_count": layer_reports[3].aggregated_metrics.get("quality_floor_pass_count", 0.0),
        "L3_artifact_reuse_count": layer_reports[3].telemetry_summary.get("artifact_reuse_count", 0.0),
        "L3_reuse_gain": layer_reports[3].telemetry_summary.get("reuse_gain", 0.0),
        "text_L0_total_tokens": text_l0_total_tokens,
        "text_L0_prompt_tokens": text_l0_prompt_tokens,
        "text_L0_prompt_bytes": text_l0_prompt_bytes,
        "text_L0_control_bytes": text_l0_control_bytes,
        "text_L0_quality_pass_count": text_l0_quality_pass_count,
        "protocol_L3_total_tokens": protocol_l3_total_tokens,
        "protocol_L3_prompt_tokens": protocol_l3_prompt_tokens,
        "protocol_L3_prompt_bytes": protocol_l3_prompt_bytes,
        "protocol_L3_control_bytes": protocol_l3_control_bytes,
        "protocol_L3_quality_pass_count": protocol_l3_quality_pass_count,
    }
    comparison_summary = {
        "pruning_bytes_saved_vs_l0": max(
            layer_reports[0].telemetry_summary.get("raw_evidence_bytes_seen_by_llm", 0.0)
            - layer_reports[2].telemetry_summary.get("raw_evidence_bytes_seen_by_llm", 0.0),
            0.0,
        ),
        "control_bytes_delta_l0_to_l1": max(
            layer_reports[0].telemetry_summary.get("control_bytes", 0.0)
            - layer_reports[1].telemetry_summary.get("control_bytes", 0.0),
            0.0,
        ),
        "reuse_gain_delta_l2_to_l3": max(
            layer_reports[3].telemetry_summary.get("reuse_gain", 0.0)
            - layer_reports[2].telemetry_summary.get("reuse_gain", 0.0),
            0.0,
        ),
        "artifact_reuse_delta_l2_to_l3": max(
            layer_reports[3].telemetry_summary.get("artifact_reuse_count", 0.0)
            - layer_reports[2].telemetry_summary.get("artifact_reuse_count", 0.0),
            0.0,
        ),
        "quality_floor_pass_delta_l0_to_l3": (
            layer_reports[3].aggregated_metrics.get("quality_floor_pass_count", 0.0)
            - layer_reports[0].aggregated_metrics.get("quality_floor_pass_count", 0.0)
        ),
        "selected_evidence_bytes_delta_l0_to_l2": max(
            layer_reports[0].telemetry_summary.get("selected_evidence_bytes", 0.0)
            - layer_reports[2].telemetry_summary.get("selected_evidence_bytes", 0.0),
            0.0,
        ),
        "replan_history_delta_l0_to_l3": (
            layer_reports[3].telemetry_summary.get("replan_history_count", 0.0)
            - layer_reports[0].telemetry_summary.get("replan_history_count", 0.0)
        ),
        "codeact_action_delta_l0_to_l3": (
            layer_reports[3].telemetry_summary.get("codeact_plan_action_count", 0.0)
            - layer_reports[0].telemetry_summary.get("codeact_plan_action_count", 0.0)
        ),
        "text_L0_total_tokens": text_l0_total_tokens,
        "text_L0_prompt_tokens": text_l0_prompt_tokens,
        "text_L0_prompt_bytes": text_l0_prompt_bytes,
        "text_L0_control_bytes": text_l0_control_bytes,
        "text_L0_quality_pass_count": text_l0_quality_pass_count,
        "protocol_L3_total_tokens": protocol_l3_total_tokens,
        "protocol_L3_prompt_tokens": protocol_l3_prompt_tokens,
        "protocol_L3_prompt_bytes": protocol_l3_prompt_bytes,
        "protocol_L3_control_bytes": protocol_l3_control_bytes,
        "protocol_L3_quality_pass_count": protocol_l3_quality_pass_count,
        "protocol_vs_text_token_delta": protocol_l3_total_tokens - text_l0_total_tokens,
        "protocol_vs_text_prompt_token_delta": protocol_l3_prompt_tokens - text_l0_prompt_tokens,
        "protocol_vs_text_prompt_bytes_delta": protocol_l3_prompt_bytes - text_l0_prompt_bytes,
        "protocol_vs_text_control_bytes_delta": protocol_l3_control_bytes - text_l0_control_bytes,
        "protocol_vs_text_quality_pass_delta": protocol_l3_quality_pass_count - text_l0_quality_pass_count,
    }
    report_path = runtime_root / "benchmark_reports" / f"{suite_id}-suite.json"
    family_tier = (
        "formal_registry"
        if benchmark_tier == "formal" and len(formal_families) > 1
        else "formal_financial"
        if benchmark_tier == "formal"
        else "dev"
    )
    suite_report = BenchmarkSuiteReport(
        suite_id=suite_id,
        task_family=samples[0].task_family if samples else "financial_report_analysis",
        layer_reports=layer_reports,
        waterfall_metrics=waterfall_metrics,
        comparison_summary=comparison_summary,
        metadata={
            "benchmark_tier": benchmark_tier,
            "claim_level": claim_level,
            "embedding_mode": embedding_mode,
            "comparison_contract": "same_mainline_internal_attribution_ladder",
            "ladder_claim_scope": "internal_attribution_only_not_external_superiority",
            "role_path_mode": role_path_mode,
            "transport": executor_transport,
            "state_pool_mode_requested": state_pool_mode,
            "state_pool_mode_used": state_pool_mode_used,
            "memfd_transfer_count": l3_report.telemetry_summary.get("memfd_transfer_count", 0.0),
            "memfd_publish_count": l3_report.telemetry_summary.get("memfd_publish_count", 0.0),
            "memfd_bytes_transferred": l3_report.telemetry_summary.get("memfd_bytes_transferred", 0.0),
            "seed_replay_memory_by_layer": {
                layer.value: seed_replay_memory_by_layer.get(layer, False)
                for layer in BenchmarkLayer
            },
            "formal_task_families": list(formal_families),
            "formal_task_family_count": len(formal_families),
            "formal_text_protocol_benchmark": benchmark_tier == "formal",
            "task_family_tier": family_tier,
        },
        family_case_count=len(samples),
        report_path=str(report_path),
    )
    write_json_report(report_path, suite_report_to_dict(suite_report))
    return suite_report


def main() -> None:
    sample = MinimalBenchmarkSample.from_path(
        Path(__file__).with_name("samples") / "minimal_financial_report_sample.json"
    )
    smoke, report = run_minimal_benchmark(
        sample=sample,
        workspace_root=Path("/tmp/statebus-v2-benchmark/workspaces"),
        runtime_root=Path("/tmp/statebus-v2-benchmark/runtime"),
        socket_path=Path("/tmp/statebus-v2-benchmark/control.sock"),
    )
    family = run_minimal_benchmark_family(
        samples=load_sample_family(Path(__file__).with_name("samples") / "formal_financial_family"),
        workspace_root=Path("/tmp/statebus-v2-benchmark-family/workspaces"),
        runtime_root=Path("/tmp/statebus-v2-benchmark-family/runtime"),
        socket_path=Path("/tmp/statebus-v2-benchmark-family/control.sock"),
        layer=BenchmarkLayer.L3,
    )
    suite = run_minimal_benchmark_suite(
        samples=load_sample_family(Path(__file__).with_name("samples") / "formal_financial_family"),
        workspace_root=Path("/tmp/statebus-v2-benchmark-suite/workspaces"),
        runtime_root=Path("/tmp/statebus-v2-benchmark-suite/runtime"),
        socket_path=Path("/tmp/statebus-v2-benchmark-suite/control.sock"),
    )
    print(f"task_id={sample.task_id}")
    print(f"quality_floor_pass={report.quality_floor.quality_floor_pass}")
    print(f"replay_class={smoke.replay_class}")
    print(f"telemetry_event_count={smoke.telemetry_event_count}")
    print(f"family_case_count={len(family.cases)}")
    print(f"family_quality_floor_pass_count={int(family.aggregated_metrics['quality_floor_pass_count'])}")
    print(f"family_report_path={family.report_path}")
    print(f"suite_layer_count={len(suite.layer_reports)}")
    print(f"suite_report_path={suite.report_path}")
    print(json.dumps(suite_report_to_dict(suite), ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
