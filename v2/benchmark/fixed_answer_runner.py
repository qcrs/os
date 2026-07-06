from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from v2.benchmark.models import (
    BenchmarkCaseReport,
    BenchmarkComparatorModeReport,
    BenchmarkComparatorSuiteReport,
    BenchmarkFamilyReport,
    BenchmarkLayer,
    BenchmarkLayerProfile,
    BenchmarkSuiteReport,
)
from v2.benchmark.scoring import FixedAnswerLaneResult, score_fixed_answer_case
from v2.benchmark.reporting import (
    comparator_mode_report_to_dict,
    comparator_suite_report_to_dict,
    family_report_to_dict,
    suite_report_to_dict,
    write_json_report,
    write_markdown_report,
)
from v2.benchmark.runtime_modes import benchmark_runtime_missing_reason
from v2.contracts import CanonicalTaskSpec
from v2.runtime.smoke import SmokeLayerConfig, run_smoke
from v2.runtime.driver import RuntimeDriverProfile
from v2.utils import stable_json_dumps


FIXED_ANSWER_LAYER_PROFILES: dict[BenchmarkLayer, BenchmarkLayerProfile] = {
    BenchmarkLayer.L0: BenchmarkLayerProfile(
        layer=BenchmarkLayer.L0,
        description="dev fixed-answer full-text collaboration baseline",
        structured_control_enabled=False,
        semantic_pruning_enabled=False,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L1: BenchmarkLayerProfile(
        layer=BenchmarkLayer.L1,
        description="dev fixed-answer structured collaboration full-text evidence",
        structured_control_enabled=True,
        semantic_pruning_enabled=False,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L2: BenchmarkLayerProfile(
        layer=BenchmarkLayer.L2,
        description="dev fixed-answer structured collaboration plus semantic pruning",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L3: BenchmarkLayerProfile(
        layer=BenchmarkLayer.L3,
        description="dev fixed-answer full StateBus runtime",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=True,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
}

FIXED_ANSWER_SMOKE_CONFIGS: dict[BenchmarkLayer, SmokeLayerConfig] = {
    BenchmarkLayer.L0: SmokeLayerConfig(
        layer_name="L0-fixed-answer",
        handoff_mode="text_collaboration",
        structured_control_enabled=False,
        semantic_pruning_enabled=False,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L1: SmokeLayerConfig(
        layer_name="L1-fixed-answer",
        handoff_mode="structured_collaboration",
        structured_control_enabled=True,
        semantic_pruning_enabled=False,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L2: SmokeLayerConfig(
        layer_name="L2-fixed-answer",
        handoff_mode="structured_collaboration",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
    BenchmarkLayer.L3: SmokeLayerConfig(
        layer_name="L3-fixed-answer",
        handoff_mode="structured_collaboration",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=True,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    ),
}

FIXED_ANSWER_TEXT_SEMANTIC_SELECTION_PROFILE = BenchmarkLayerProfile(
    layer=BenchmarkLayer.L2,
    description="dev fixed-answer text handoff with same semantic selection and no semantic state transfer",
    structured_control_enabled=False,
    semantic_pruning_enabled=True,
    replay_enabled=False,
    multi_attempt_enabled=False,
    force_first_attempt_trap=False,
)

FIXED_ANSWER_TEXT_SEMANTIC_SELECTION_SMOKE_CONFIG = SmokeLayerConfig(
    layer_name="T2-fixed-answer-text-semantic-selection",
    handoff_mode="text_collaboration",
    structured_control_enabled=False,
    semantic_pruning_enabled=True,
    semantic_state_transfer_enabled=False,
    replay_enabled=False,
    multi_attempt_enabled=False,
    force_first_attempt_trap=False,
)


def normalize_statebus_mode(statebus_mode: str) -> str:
    normalized = statebus_mode.strip().lower().replace("-", "_")
    if normalized not in {"replay_ready", "cold_start"}:
        raise ValueError(f"unsupported statebus mode: {statebus_mode}")
    return normalized


def _fixed_answer_profile(*, layer: BenchmarkLayer, statebus_mode: str) -> BenchmarkLayerProfile:
    normalized = normalize_statebus_mode(statebus_mode)
    base = FIXED_ANSWER_LAYER_PROFILES[layer]
    description = base.description
    if layer == BenchmarkLayer.L3 and normalized == "cold_start":
        description = f"{description} (cold-start)"
    return BenchmarkLayerProfile(
        layer=base.layer,
        description=description,
        structured_control_enabled=base.structured_control_enabled,
        semantic_pruning_enabled=base.semantic_pruning_enabled,
        replay_enabled=base.replay_enabled,
        multi_attempt_enabled=base.multi_attempt_enabled,
        force_first_attempt_trap=base.force_first_attempt_trap,
        hermetic_runtime_root=base.hermetic_runtime_root,
    )


def _fixed_answer_smoke_config(
    *,
    layer: BenchmarkLayer,
    statebus_mode: str,
    role_path_mode: str,
    embedding_mode: str,
    state_pool_mode: str = "auto",
    persistence_profile: str = "audit_full",
) -> SmokeLayerConfig:
    normalized = normalize_statebus_mode(statebus_mode)
    base = FIXED_ANSWER_SMOKE_CONFIGS[layer]
    return SmokeLayerConfig(
        layer_name=(
            base.layer_name
            if layer != BenchmarkLayer.L3 or normalized == "replay_ready"
            else f"{base.layer_name}-cold-start"
        ),
        handoff_mode=base.handoff_mode,
        structured_control_enabled=base.structured_control_enabled,
        semantic_pruning_enabled=base.semantic_pruning_enabled,
        semantic_state_transfer_enabled=base.semantic_state_transfer_enabled,
        replay_enabled=base.replay_enabled,
        multi_attempt_enabled=base.multi_attempt_enabled,
        force_first_attempt_trap=base.force_first_attempt_trap,
        role_path_mode=role_path_mode,
        embedding_mode=embedding_mode,
        state_pool_mode=state_pool_mode,
        persistence_profile=persistence_profile,
    )


def _fixed_answer_driver_profile(layer_config: SmokeLayerConfig) -> RuntimeDriverProfile:
    return RuntimeDriverProfile(
        layer_name=layer_config.layer_name,
        handoff_mode=layer_config.handoff_mode,
        structured_control_enabled=layer_config.structured_control_enabled,
        semantic_pruning_enabled=layer_config.semantic_pruning_enabled,
        semantic_state_transfer_enabled=layer_config.semantic_state_transfer_enabled,
        replay_enabled=layer_config.replay_enabled,
        multi_attempt_enabled=layer_config.multi_attempt_enabled,
        force_first_attempt_trap=layer_config.force_first_attempt_trap,
        persistence_verification_level="core_roundtrip",
        persistence_profile=layer_config.persistence_profile,
    )


def _fixed_answer_metadata(
    *,
    layer: BenchmarkLayer,
    handoff_mode: str,
    benchmark_tier: str,
    claim_level: str,
    role_path_mode: str,
    embedding_mode: str,
    statebus_mode: str,
    synthetic_replay_seed_enabled: bool,
    history_backed_replay_enabled: bool,
    replay_history_source: str,
) -> dict[str, object]:
    return {
        "baseline_kind": "statebus_fixed_answer_dev",
        "benchmark_tier": benchmark_tier,
        "carrier_kind": "typed_statebus" if handoff_mode == "structured_collaboration" else "text_collaboration",
        "claim_level": claim_level,
        "comparison_contract": "same_mainline_internal_attribution_ladder",
        "embedding_mode": embedding_mode,
        "formal_comparator_eligible": True,
        "benchmark_layer": layer.value,
        "handoff_mode": handoff_mode,
        "ladder_claim_scope": "internal_attribution_only_not_external_superiority",
        "quality_floor_contract": "fixed_answer_shared_quality_floor_v1",
        "role_graph": "planner->retriever->executor->summarizer",
        "role_path_mode": role_path_mode,
        "scoring_contract": "fixed_answer_shared_case_scorer_v1",
        "statebus_mode": normalize_statebus_mode(statebus_mode),
        "history_backed_replay_enabled": history_backed_replay_enabled,
        "replay_history_source": replay_history_source,
        "synthetic_replay_seed_enabled": synthetic_replay_seed_enabled,
        "task_family_tier": "dev_fixed_answer",
        "uses_internal_helpers": False,
    }


def _default_canonical_task_spec_schema_version() -> str:
    return CanonicalTaskSpec(task_family="", intent_op="").schema_version


@dataclass(frozen=True)
class FixedAnswerSample:
    task_id: str
    request_text: str
    canonical_task_spec: CanonicalTaskSpec
    task_family: str
    expected_facts: dict[str, object]
    expected_route: str
    expected_tool_name: str
    summary_hint: str
    scenario_tags: tuple[str, ...] = ()

    @classmethod
    def from_path(cls, path: Path) -> "FixedAnswerSample":
        payload = json.loads(path.read_text(encoding="utf-8"))
        canonical_payload = payload.get("canonical_task_spec")
        if not isinstance(canonical_payload, dict):
            raise ValueError(f"fixed-answer sample must include canonical_task_spec: {path}")
        arguments = dict(canonical_payload.get("arguments", {}))
        natural_language_request = str(payload.get("request_text", "")).strip()
        canonical_task_spec = CanonicalTaskSpec(
            task_family=str(canonical_payload["task_family"]),
            intent_op=str(canonical_payload["intent_op"]),
            target_entities=tuple(str(item) for item in canonical_payload.get("target_entities", [])),
            time_scope=str(canonical_payload.get("time_scope", "")),
            required_outputs=tuple(str(item) for item in canonical_payload.get("required_outputs", [])),
            required_tools=tuple(str(item) for item in canonical_payload.get("required_tools", [])),
            arguments=arguments,
            schema_version=str(canonical_payload.get("schema_version", _default_canonical_task_spec_schema_version())),
        )
        return cls(
            task_id=str(payload["task_id"]),
            request_text=natural_language_request or stable_json_dumps(canonical_payload),
            canonical_task_spec=canonical_task_spec,
            task_family=str(payload.get("task_family", "fixed_answer_route_tool")),
            expected_facts=dict(payload.get("expected_facts", {})),
            expected_route=str(payload["expected_route"]),
            expected_tool_name=str(payload["expected_tool_name"]),
            summary_hint=str(payload.get("summary_hint", "")),
            scenario_tags=tuple(str(item) for item in payload.get("scenario_tags", [])),
        )


def load_fixed_answer_family(directory: Path) -> list[FixedAnswerSample]:
    return [FixedAnswerSample.from_path(path) for path in sorted(directory.glob("*.json"))]


def _metric(report: BenchmarkFamilyReport, key: str) -> float:
    if key in report.telemetry_summary:
        return float(report.telemetry_summary[key])
    if key in report.aggregated_metrics:
        return float(report.aggregated_metrics[key])
    return 0.0


def _build_internal_carrier_debug_metrics(
    *,
    text_report: BenchmarkFamilyReport,
    structured_report: BenchmarkFamilyReport,
) -> dict[str, float]:
    if text_report.missing_reason or structured_report.missing_reason:
        return {}
    return {
        "case_count": max(
            text_report.aggregated_metrics.get("case_count", 0.0),
            structured_report.aggregated_metrics.get("case_count", 0.0),
        ),
        "quality_floor_pass_delta": structured_report.aggregated_metrics.get("quality_floor_pass_count", 0.0)
        - text_report.aggregated_metrics.get("quality_floor_pass_count", 0.0),
        "exact_match_delta": _metric(structured_report, "exact_match") - _metric(text_report, "exact_match"),
        "route_exact_delta": _metric(structured_report, "route_exact") - _metric(text_report, "route_exact"),
        "tool_exact_delta": _metric(structured_report, "tool_exact") - _metric(text_report, "tool_exact"),
        "llm_total_tokens_delta": _metric(structured_report, "llm_total_tokens")
        - _metric(text_report, "llm_total_tokens"),
        "llm_prompt_bytes_delta": _metric(structured_report, "llm_prompt_bytes")
        - _metric(text_report, "llm_prompt_bytes"),
        "task_ms_delta": _metric(structured_report, "task_ms") - _metric(text_report, "task_ms"),
        "control_bytes_delta": _metric(structured_report, "control_bytes") - _metric(text_report, "control_bytes"),
        "raw_evidence_bytes_seen_by_llm_delta": _metric(structured_report, "raw_evidence_bytes_seen_by_llm")
        - _metric(text_report, "raw_evidence_bytes_seen_by_llm"),
        "prompt_visible_total_bytes_delta": _metric(structured_report, "prompt_visible_total_bytes")
        - _metric(text_report, "prompt_visible_total_bytes"),
        "non_external_prompt_visible_bytes_delta": _metric(structured_report, "non_external_prompt_visible_bytes")
        - _metric(text_report, "non_external_prompt_visible_bytes"),
        "prompt_scaffolding_bytes_total_delta": _metric(structured_report, "prompt_scaffolding_bytes_total")
        - _metric(text_report, "prompt_scaffolding_bytes_total"),
        "planner_prompt_scaffolding_bytes_delta": _metric(structured_report, "planner_prompt_scaffolding_bytes")
        - _metric(text_report, "planner_prompt_scaffolding_bytes"),
        "retriever_prompt_scaffolding_bytes_delta": _metric(structured_report, "retriever_prompt_scaffolding_bytes")
        - _metric(text_report, "retriever_prompt_scaffolding_bytes"),
        "executor_prompt_scaffolding_bytes_delta": _metric(structured_report, "executor_prompt_scaffolding_bytes")
        - _metric(text_report, "executor_prompt_scaffolding_bytes"),
        "summarizer_prompt_scaffolding_bytes_delta": _metric(structured_report, "summarizer_prompt_scaffolding_bytes")
        - _metric(text_report, "summarizer_prompt_scaffolding_bytes"),
    }


def _internal_carrier_fairness_manifest(
    *,
    text_report: BenchmarkFamilyReport,
    structured_report: BenchmarkFamilyReport,
    benchmark_tier: str,
) -> dict[str, object]:
    text_metadata = text_report.metadata
    structured_metadata = structured_report.metadata
    text_case_payload = text_report.cases[0].metrics if text_report.cases else {}
    structured_case_payload = structured_report.cases[0].metrics if structured_report.cases else {}
    same_task_family = text_report.task_family == structured_report.task_family
    same_role_graph = text_metadata.get("role_graph") == structured_metadata.get("role_graph")
    same_scoring_contract = text_metadata.get("scoring_contract") == structured_metadata.get("scoring_contract")
    same_quality_floor_contract = (
        text_metadata.get("quality_floor_contract") == structured_metadata.get("quality_floor_contract")
    )
    same_tier = text_metadata.get("benchmark_tier") == structured_metadata.get("benchmark_tier") == benchmark_tier
    same_role_path_mode = text_metadata.get("role_path_mode") == structured_metadata.get("role_path_mode")
    same_embedding_mode = text_metadata.get("embedding_mode") == structured_metadata.get("embedding_mode")
    same_statebus_mode = text_metadata.get("statebus_mode") == structured_metadata.get("statebus_mode")
    text_handoff_mode = text_metadata.get("handoff_mode") == "text_collaboration"
    structured_handoff_mode = structured_metadata.get("handoff_mode") == "structured_collaboration"
    same_semantic_pruning = (
        text_report.profile.semantic_pruning_enabled == structured_report.profile.semantic_pruning_enabled
    )
    same_replay_policy = text_report.profile.replay_enabled == structured_report.profile.replay_enabled
    same_four_role_counts = all(
        _metric(report, f"{role}_call_count") > 0.0
        for report in (text_report, structured_report)
        for role in ("planner", "retriever", "executor", "summarizer")
    )
    pass_hard_gate = all(
        (
            same_task_family,
            same_role_graph,
            same_scoring_contract,
            same_quality_floor_contract,
            same_tier,
            same_role_path_mode,
            same_embedding_mode,
            same_statebus_mode,
            text_handoff_mode,
            structured_handoff_mode,
            same_semantic_pruning,
            same_replay_policy,
            same_four_role_counts,
        )
    )
    return {
        "benchmark_tier": benchmark_tier,
        "comparison_contract": "same_mainline_internal_text_vs_structured_carrier",
        "claim_restriction": "internal_carrier_only_not_external_superiority",
        "pass_hard_gate": pass_hard_gate,
        "same_task_family": same_task_family,
        "same_role_graph": same_role_graph,
        "same_scoring_contract": same_scoring_contract,
        "same_quality_floor_contract": same_quality_floor_contract,
        "same_tier": same_tier,
        "same_role_path_mode": same_role_path_mode,
        "same_embedding_mode": same_embedding_mode,
        "same_statebus_mode": same_statebus_mode,
        "same_semantic_pruning": same_semantic_pruning,
        "same_replay_policy": same_replay_policy,
        "same_four_role_counts": same_four_role_counts,
        "text_handoff_mode": text_metadata.get("handoff_mode", ""),
        "structured_handoff_mode": structured_metadata.get("handoff_mode", ""),
        "text_case_metric_keys": list(sorted(text_case_payload.keys())),
        "structured_case_metric_keys": list(sorted(structured_case_payload.keys())),
    }


def _build_internal_carrier_markdown(
    *,
    role_path_mode: str,
    statebus_mode: str,
    comparison_valid: bool,
    missing_reason: str,
    invalid_reason: str,
    debug_metrics: dict[str, float],
) -> str:
    if missing_reason:
        return (
            "# Fixed-Answer Internal Carrier Compare\n\n"
            f"- mode: `{role_path_mode}`\n"
            f"- statebus_mode: `{statebus_mode}`\n"
            "- status: `skipped`\n"
            f"- missing_reason: `{missing_reason}`\n"
        )
    rows = "\n".join(f"| {name} | {value:.3f} |" for name, value in sorted(debug_metrics.items()))
    status = "valid" if comparison_valid else "invalid"
    lines = [
        "# Fixed-Answer Internal Carrier Compare",
        "",
        f"- mode: `{role_path_mode}`",
        f"- statebus_mode: `{statebus_mode}`",
        f"- status: `{status}`",
        "- comparator_claim: `same_mainline_internal_text_vs_structured_carrier_only`",
    ]
    if invalid_reason:
        lines.append(f"- invalid_reason: `{invalid_reason}`")
    lines.extend(["", "## Debug Metrics", ""])
    if rows:
        lines.extend(["| Metric | Delta |", "| --- | ---: |", rows])
    else:
        lines.append("No debug metrics emitted.")
    return "\n".join(lines).rstrip() + "\n"


def run_fixed_answer_benchmark_family(
    *,
    samples: list[FixedAnswerSample],
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str = "fixed-answer-family",
    layer: BenchmarkLayer = BenchmarkLayer.L3,
    role_path_mode: str = "deterministic",
    embedding_mode: str = "deterministic",
    statebus_mode: str = "cold_start",
    seed_replay_memory: bool = False,
    benchmark_tier: str = "dev",
    claim_level: str = "prototype",
    profile_override: BenchmarkLayerProfile | None = None,
    smoke_config_override: SmokeLayerConfig | None = None,
    metadata_extra: dict[str, object] | None = None,
    state_pool_mode: str = "auto",
    persistence_profile: str = "audit_full",
) -> BenchmarkFamilyReport:
    normalized_statebus_mode = normalize_statebus_mode(statebus_mode)
    if layer != BenchmarkLayer.L3:
        normalized_statebus_mode = "cold_start"
        seed_replay_memory = False
    if normalized_statebus_mode == "cold_start" and seed_replay_memory:
        raise ValueError("synthetic replay seed is dev-only and requires replay_ready statebus_mode")
    task_family = samples[0].task_family if samples else "fixed_answer_route_tool"
    report_path = runtime_root / "benchmark_reports" / f"{suite_id}.json"
    profile = profile_override or _fixed_answer_profile(layer=layer, statebus_mode=normalized_statebus_mode)
    smoke_layer_config = smoke_config_override or _fixed_answer_smoke_config(
        layer=layer,
        statebus_mode=normalized_statebus_mode,
        role_path_mode=role_path_mode,
        embedding_mode=embedding_mode,
        state_pool_mode=state_pool_mode,
        persistence_profile=persistence_profile,
    )
    history_backed_replay_enabled = (
        layer == BenchmarkLayer.L3 and normalized_statebus_mode == "replay_ready" and not seed_replay_memory
    )
    replay_history_source = (
        "synthetic_seed"
        if normalized_statebus_mode == "replay_ready" and seed_replay_memory
        else "history_bootstrap"
        if history_backed_replay_enabled
        else "none"
    )
    metadata = _fixed_answer_metadata(
        layer=layer,
        handoff_mode=smoke_layer_config.handoff_mode,
        benchmark_tier=benchmark_tier,
        claim_level=claim_level,
        role_path_mode=role_path_mode,
        embedding_mode=embedding_mode,
        statebus_mode=normalized_statebus_mode,
        synthetic_replay_seed_enabled=bool(seed_replay_memory and normalized_statebus_mode == "replay_ready"),
        history_backed_replay_enabled=history_backed_replay_enabled,
        replay_history_source=replay_history_source,
    )
    if metadata_extra:
        metadata.update(metadata_extra)
    missing_reason = benchmark_runtime_missing_reason(
        role_path_mode=role_path_mode,
        embedding_mode=embedding_mode,
    )
    if missing_reason:
        report = BenchmarkFamilyReport(
            suite_id=suite_id,
            layer=layer,
            task_family=task_family,
            profile=profile,
            cases=(),
            aggregated_metrics={
                "case_count": 0.0,
                "quality_floor_pass_count": 0.0,
                "telemetry_event_count": 0.0,
            },
            telemetry_summary={},
            replay_class_distribution={},
            quality_floor_breakdown={
                "deterministic_checks_passed_count": 0.0,
                "fact_coverage_passed_count": 0.0,
                "quality_floor_pass_count": 0.0,
            },
            metadata=metadata,
            report_path=str(report_path),
            missing_reason=missing_reason,
        )
        write_json_report(report_path, family_report_to_dict(report))
        return report

    cases: list[BenchmarkCaseReport] = []
    layer_workspace_root = workspace_root
    if layer_workspace_root.exists():
        shutil.rmtree(layer_workspace_root)
    layer_workspace_root.mkdir(parents=True, exist_ok=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    for sample in samples:
        history_runtime_roots: tuple[Path, ...] = ()
        sample_runtime_root = runtime_root / sample.task_id
        if history_backed_replay_enabled:
            bootstrap_runtime_root = runtime_root / "_history_bootstrap" / sample.task_id
            bootstrap_workspace_root = layer_workspace_root / "_history_bootstrap"
            run_smoke(
                workspace_root=bootstrap_workspace_root,
                runtime_root=bootstrap_runtime_root,
                socket_path=socket_path.with_name(
                    f"fx-bootstrap-{len(sample.task_id)}-{abs(hash(sample.task_id)) % 10000}.sock"
                ),
                request_text=sample.request_text,
                canonical_task_spec=sample.canonical_task_spec,
                task_id=sample.task_id,
                layer_config=_fixed_answer_smoke_config(
                    layer=BenchmarkLayer.L0,
                    statebus_mode="cold_start",
                    role_path_mode=role_path_mode,
                    embedding_mode=embedding_mode,
                    state_pool_mode=state_pool_mode,
                    persistence_profile=persistence_profile,
                ),
                expected_facts=sample.expected_facts,
                seed_replay_memory=False,
                driver_profile_override=_fixed_answer_driver_profile(
                    _fixed_answer_smoke_config(
                        layer=BenchmarkLayer.L0,
                        statebus_mode="cold_start",
                        role_path_mode=role_path_mode,
                        embedding_mode=embedding_mode,
                        state_pool_mode=state_pool_mode,
                        persistence_profile=persistence_profile,
                    )
                ),
            )
            history_runtime_roots = (bootstrap_runtime_root,)
        start_ns = time.perf_counter_ns()
        smoke = run_smoke(
            workspace_root=layer_workspace_root,
            runtime_root=sample_runtime_root,
            socket_path=socket_path.with_name(f"fx-{len(sample.task_id)}-{abs(hash(sample.task_id)) % 10000}.sock"),
            request_text=sample.request_text,
            canonical_task_spec=sample.canonical_task_spec,
            task_id=sample.task_id,
            layer_config=smoke_layer_config,
            expected_facts=sample.expected_facts,
            seed_replay_memory=seed_replay_memory,
            history_runtime_roots=history_runtime_roots,
            driver_profile_override=_fixed_answer_driver_profile(smoke_layer_config),
        )
        task_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
        output_payload = json.loads(Path(smoke.output_artifact_path).read_text(encoding="utf-8"))
        observed_route = str(output_payload.get("route", "")).strip()
        observed_tool_name = str(output_payload.get("tool_name", "")).strip()
        shared_score = score_fixed_answer_case(
            observed=FixedAnswerLaneResult(
                task_id=sample.task_id,
                route=observed_route,
                tool_name=observed_tool_name,
                summary_text=str(output_payload.get("summary_text", "")),
                revenue_value=str(output_payload.get("revenue_value", "")),
                selected_doc_hashes=tuple(
                    str(item).strip() for item in output_payload.get("selected_doc_hashes", []) if str(item).strip()
                ),
                supporting_doc_ids=tuple(
                    str(item).strip() for item in output_payload.get("supporting_doc_ids", []) if str(item).strip()
                ),
            ),
            expected_route=sample.expected_route,
            expected_tool_name=sample.expected_tool_name,
            expected_facts=sample.expected_facts,
        )
        smoke_metrics = dict(sorted(smoke.task_metrics.items()))
        smoke_metrics["message_count"] = float(
            smoke.task_metrics.get("control_message_count", smoke.task_metrics.get("response_count", 0.0))
        )
        smoke_metrics["prompt_tokens"] = float(smoke.task_metrics.get("llm_prompt_tokens", 0.0))
        smoke_metrics["completion_tokens"] = float(smoke.task_metrics.get("llm_completion_tokens", 0.0))
        smoke_metrics["llm_total_tokens"] = float(smoke.task_metrics.get("llm_total_tokens", 0.0))
        smoke_metrics["task_ms"] = float(task_ms)
        cases.append(
            BenchmarkCaseReport(
                task_id=sample.task_id,
                task_family=sample.task_family,
                quality_floor=shared_score.quality_floor,
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
                    **smoke_metrics,
                    "route_exact": 1.0 if shared_score.route_exact else 0.0,
                    "tool_exact": 1.0 if shared_score.tool_exact else 0.0,
                    "revenue_exact": 1.0 if shared_score.revenue_exact else 0.0,
                    "selected_doc_hashes_exact": 1.0 if shared_score.selected_doc_hashes_exact else 0.0,
                    "summary_present": 1.0 if shared_score.summary_present else 0.0,
                    "exact_match": 1.0 if shared_score.exact_match else 0.0,
                    "admissible_match": 1.0 if shared_score.admissible_match else 0.0,
                },
            )
        )

    aggregated_metrics = {
        "case_count": float(len(cases)),
        "quality_floor_pass_count": float(sum(1 for case in cases if case.quality_floor.quality_floor_pass)),
        "telemetry_event_count": float(sum(case.telemetry_event_count for case in cases)),
    }
    telemetry_summary: dict[str, float] = {}
    for case in cases:
        for key, value in case.metrics.items():
            telemetry_summary[key] = telemetry_summary.get(key, 0.0) + float(value)
    state_pool_mode_used = (
        "memfd"
        if telemetry_summary.get("memfd_transfer_count", 0.0) > 0.0
        else "shared_memory"
        if telemetry_summary.get("state_pool_shared_memory_mode_count", 0.0) > 0.0
        else "mmap_file"
        if telemetry_summary.get("state_pool_mmap_mode_count", 0.0) > 0.0
        else state_pool_mode
    )
    metadata.update(
        {
            "state_pool_mode_requested": state_pool_mode,
            "state_pool_mode_used": state_pool_mode_used,
            "memfd_transfer_count": telemetry_summary.get("memfd_transfer_count", 0.0),
            "memfd_publish_count": telemetry_summary.get("memfd_publish_count", 0.0),
            "memfd_bytes_transferred": telemetry_summary.get("memfd_bytes_transferred", 0.0),
        }
    )
    replay_class_distribution: dict[str, float] = {}
    for case in cases:
        replay_class_distribution[case.replay_class] = replay_class_distribution.get(case.replay_class, 0.0) + 1.0
    quality_floor_breakdown = {
        "deterministic_checks_passed_count": float(
            sum(1 for case in cases if case.quality_floor.deterministic_checks_passed)
        ),
        "fact_coverage_passed_count": float(sum(1 for case in cases if case.quality_floor.fact_coverage_passed)),
        "quality_floor_pass_count": aggregated_metrics["quality_floor_pass_count"],
    }
    report = BenchmarkFamilyReport(
            suite_id=suite_id,
            layer=layer,
            task_family=task_family,
            profile=profile,
            cases=tuple(cases),
        aggregated_metrics=aggregated_metrics,
        telemetry_summary=telemetry_summary,
            replay_class_distribution=replay_class_distribution,
            quality_floor_breakdown=quality_floor_breakdown,
            metadata=metadata,
            report_path=str(report_path),
        )
    write_json_report(report_path, family_report_to_dict(report))
    return report


def run_fixed_answer_text_semantic_selection_family(
    *,
    samples: list[FixedAnswerSample],
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str = "fixed-answer-text-semantic-selection",
    role_path_mode: str = "deterministic",
    embedding_mode: str = "deterministic",
    benchmark_tier: str = "dev",
    claim_level: str = "diagnostic",
    persistence_profile: str = "audit_full",
) -> BenchmarkFamilyReport:
    smoke_config = SmokeLayerConfig(
        **{
            **FIXED_ANSWER_TEXT_SEMANTIC_SELECTION_SMOKE_CONFIG.__dict__,
            "role_path_mode": role_path_mode,
            "embedding_mode": embedding_mode,
            "persistence_profile": persistence_profile,
        }
    )
    return run_fixed_answer_benchmark_family(
        samples=samples,
        workspace_root=workspace_root,
        runtime_root=runtime_root,
        socket_path=socket_path,
        suite_id=suite_id,
        layer=BenchmarkLayer.L2,
        role_path_mode=role_path_mode,
        embedding_mode=embedding_mode,
        statebus_mode="cold_start",
        seed_replay_memory=False,
        benchmark_tier=benchmark_tier,
        claim_level=claim_level,
        profile_override=FIXED_ANSWER_TEXT_SEMANTIC_SELECTION_PROFILE,
        smoke_config_override=smoke_config,
        metadata_extra={
            "baseline_kind": "internal_text_same_semantic_selection",
            "carrier_kind": "text_collaboration_same_selected_evidence",
            "comparison_contract": "same_mainline_text_handoff_semantic_selection_without_state_ref",
            "diagnostic_claim_scope": "isolates_semantic_selection_from_non_text_state_transfer",
            "formal_comparator_eligible": False,
            "semantic_state_transfer_enabled": False,
            "uses_semantic_state_ref": False,
        },
        persistence_profile=persistence_profile,
    )


def run_fixed_answer_suite(
    *,
    samples: list[FixedAnswerSample],
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str = "fixed-answer-suite",
    role_path_modes: tuple[str, ...] = ("deterministic",),
    embedding_mode: str = "deterministic",
    statebus_mode: str = "cold_start",
    seed_replay_memory: bool = False,
    benchmark_tier: str = "dev",
    claim_level: str = "prototype",
    state_pool_mode: str = "auto",
    persistence_profile: str = "audit_full",
) -> BenchmarkSuiteReport:
    normalized_statebus_mode = normalize_statebus_mode(statebus_mode)
    primary_role_path_mode = role_path_modes[0] if role_path_modes else "deterministic"
    layer_reports = tuple(
        run_fixed_answer_benchmark_family(
            samples=samples,
            workspace_root=workspace_root / layer.value,
            runtime_root=runtime_root / layer.value,
            socket_path=socket_path.with_name(f"fx-{layer.value.lower()}.sock"),
            suite_id=f"{suite_id}-{layer.value.lower()}",
            layer=layer,
            role_path_mode=primary_role_path_mode,
            embedding_mode=embedding_mode,
            statebus_mode=normalized_statebus_mode,
            seed_replay_memory=seed_replay_memory if layer == BenchmarkLayer.L3 else False,
            benchmark_tier=benchmark_tier,
            claim_level=claim_level,
            state_pool_mode=state_pool_mode,
            persistence_profile=persistence_profile,
        )
        for layer in BenchmarkLayer
    )
    l3_report = layer_reports[3]
    successful_mode_count = float(sum(1 for layer in layer_reports if not layer.missing_reason))
    suite_metadata = {
        "benchmark_tier": benchmark_tier,
        "claim_level": claim_level,
        "comparison_contract": "same_mainline_internal_attribution_ladder",
        "ladder_claim_scope": "internal_attribution_only_not_external_superiority",
        "seed_replay_memory": seed_replay_memory,
        "statebus_mode": normalized_statebus_mode,
        "role_path_mode": primary_role_path_mode,
        "state_pool_mode_requested": state_pool_mode,
        "state_pool_mode_used": str(l3_report.metadata.get("state_pool_mode_used", state_pool_mode)),
        "memfd_transfer_count": l3_report.telemetry_summary.get("memfd_transfer_count", 0.0),
        "memfd_publish_count": l3_report.telemetry_summary.get("memfd_publish_count", 0.0),
        "memfd_bytes_transferred": l3_report.telemetry_summary.get("memfd_bytes_transferred", 0.0),
        "task_family_tier": "dev_fixed_answer",
    }
    report = BenchmarkSuiteReport(
        suite_id=suite_id,
        task_family=samples[0].task_family if samples else "fixed_answer_route_tool",
        layer_reports=layer_reports,
        waterfall_metrics={
            "L0_case_count": float(len(layer_reports[0].cases)),
            "L0_role_handoff_bytes_total": layer_reports[0].telemetry_summary.get("role_handoff_bytes_total", 0.0),
            "L0_prompt_visible_total_bytes": layer_reports[0].telemetry_summary.get("prompt_visible_total_bytes", 0.0),
            "L0_prompt_scaffolding_bytes_total": layer_reports[0].telemetry_summary.get(
                "prompt_scaffolding_bytes_total", 0.0
            ),
            "L1_control_bytes": layer_reports[1].telemetry_summary.get("control_bytes", 0.0),
            "L1_role_handoff_bytes_total": layer_reports[1].telemetry_summary.get("role_handoff_bytes_total", 0.0),
            "L1_prompt_visible_total_bytes": layer_reports[1].telemetry_summary.get("prompt_visible_total_bytes", 0.0),
            "L1_prompt_scaffolding_bytes_total": layer_reports[1].telemetry_summary.get(
                "prompt_scaffolding_bytes_total", 0.0
            ),
            "L2_raw_evidence_bytes_seen_by_llm": layer_reports[2].telemetry_summary.get(
                "raw_evidence_bytes_seen_by_llm", 0.0
            ),
            "L2_semantic_state_transfer_count": layer_reports[2].telemetry_summary.get(
                "semantic_state_transfer_count", 0.0
            ),
            "L3_quality_floor_pass_count": layer_reports[3].aggregated_metrics.get("quality_floor_pass_count", 0.0),
            "L3_reuse_gain": layer_reports[3].telemetry_summary.get("reuse_gain", 0.0),
        },
        comparison_summary={
            "layer_count": float(len(layer_reports)),
            "successful_layer_count": successful_mode_count,
            "handoff_bytes_delta_l0_to_l1": max(
                layer_reports[0].telemetry_summary.get("role_handoff_bytes_total", 0.0)
                - layer_reports[1].telemetry_summary.get("role_handoff_bytes_total", 0.0),
                0.0,
            ),
            "prompt_visible_bytes_delta_l0_to_l1": max(
                layer_reports[0].telemetry_summary.get("prompt_visible_total_bytes", 0.0)
                - layer_reports[1].telemetry_summary.get("prompt_visible_total_bytes", 0.0),
                0.0,
            ),
            "prompt_scaffolding_bytes_delta_l0_to_l1": max(
                layer_reports[0].telemetry_summary.get("prompt_scaffolding_bytes_total", 0.0)
                - layer_reports[1].telemetry_summary.get("prompt_scaffolding_bytes_total", 0.0),
                0.0,
            ),
            "control_bytes_delta_l0_to_l1": max(
                layer_reports[0].telemetry_summary.get("control_bytes", 0.0)
                - layer_reports[1].telemetry_summary.get("control_bytes", 0.0),
                0.0,
            ),
            "raw_evidence_bytes_delta_l1_to_l2": max(
                layer_reports[1].telemetry_summary.get("raw_evidence_bytes_seen_by_llm", 0.0)
                - layer_reports[2].telemetry_summary.get("raw_evidence_bytes_seen_by_llm", 0.0),
                0.0,
            ),
            "reuse_gain_delta_l2_to_l3": max(
                layer_reports[3].telemetry_summary.get("reuse_gain", 0.0)
                - layer_reports[2].telemetry_summary.get("reuse_gain", 0.0),
                0.0,
            ),
        },
        metadata=suite_metadata,
        family_case_count=len(samples),
        report_path=str(runtime_root / "benchmark_reports" / f"{suite_id}.json"),
    )
    write_json_report(Path(report.report_path), suite_report_to_dict(report))
    return report


def run_fixed_answer_internal_carrier_compare_suite(
    *,
    samples: list[FixedAnswerSample],
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str = "fixed-answer-internal-carrier-compare",
    role_path_modes: tuple[str, ...] = ("deterministic",),
    embedding_mode: str = "deterministic",
    statebus_mode: str = "cold_start",
    benchmark_tier: str = "dev",
    claim_level: str = "prototype",
    state_pool_mode: str = "auto",
    persistence_profile: str = "audit_full",
) -> BenchmarkComparatorSuiteReport:
    normalized_statebus_mode = normalize_statebus_mode(statebus_mode)
    mode_reports: list[BenchmarkComparatorModeReport] = []
    benchmark_report_root = runtime_root / "benchmark_reports"
    task_family = samples[0].task_family if samples else "fixed_answer_route_tool"
    for role_path_mode in role_path_modes:
        mode_runtime_root = runtime_root / role_path_mode
        text_report = run_fixed_answer_benchmark_family(
            samples=samples,
            workspace_root=workspace_root / role_path_mode / "text-collaboration",
            runtime_root=mode_runtime_root / "text-collaboration",
            socket_path=socket_path.with_name(f"{socket_path.stem}-{role_path_mode}-text{socket_path.suffix}"),
            suite_id=f"{suite_id}-text-{role_path_mode}",
            layer=BenchmarkLayer.L0,
            role_path_mode=role_path_mode,
            embedding_mode=embedding_mode,
            statebus_mode="cold_start",
            seed_replay_memory=False,
            benchmark_tier=benchmark_tier,
            claim_level=claim_level,
            state_pool_mode=state_pool_mode,
            persistence_profile=persistence_profile,
        )
        structured_report = run_fixed_answer_benchmark_family(
            samples=samples,
            workspace_root=workspace_root / role_path_mode / "structured-collaboration",
            runtime_root=mode_runtime_root / "structured-collaboration",
            socket_path=socket_path.with_name(f"{socket_path.stem}-{role_path_mode}-structured{socket_path.suffix}"),
            suite_id=f"{suite_id}-structured-{role_path_mode}",
            layer=BenchmarkLayer.L1,
            role_path_mode=role_path_mode,
            embedding_mode=embedding_mode,
            statebus_mode="cold_start",
            seed_replay_memory=False,
            benchmark_tier=benchmark_tier,
            claim_level=claim_level,
            state_pool_mode=state_pool_mode,
            persistence_profile=persistence_profile,
        )
        mode_missing_reason = text_report.missing_reason or structured_report.missing_reason
        fairness_manifest = _internal_carrier_fairness_manifest(
            text_report=text_report,
            structured_report=structured_report,
            benchmark_tier=benchmark_tier,
        )
        debug_metrics = _build_internal_carrier_debug_metrics(
            text_report=text_report,
            structured_report=structured_report,
        )
        invalid_reason = "" if fairness_manifest.get("pass_hard_gate", False) else "internal_carrier_gate_failed"
        comparison_valid = not mode_missing_reason and not invalid_reason
        comparison_summary = {
            "case_count": debug_metrics.get("case_count", 0.0),
            "comparison_valid": 1.0 if comparison_valid else 0.0,
            "debug_metric_count": float(len(debug_metrics)),
        }
        comparison_summary.update(debug_metrics)
        report_path = benchmark_report_root / f"{suite_id}-{role_path_mode}.json"
        markdown_report_path = benchmark_report_root / f"{suite_id}-{role_path_mode}.md"
        mode_report = BenchmarkComparatorModeReport(
            suite_id=suite_id,
            role_path_mode=role_path_mode,
            task_family=task_family,
            external_report=text_report,
            statebus_report=structured_report,
            comparison_summary=comparison_summary,
            headline_metrics={},
            debug_metrics=debug_metrics,
            fairness_manifest=fairness_manifest,
            comparison_valid=comparison_valid,
            invalid_reason=invalid_reason,
            benchmark_tier=benchmark_tier,
            claim_level=claim_level,
            report_path=str(report_path),
            markdown_report_path=str(markdown_report_path),
            missing_reason=mode_missing_reason,
        )
        write_json_report(report_path, comparator_mode_report_to_dict(mode_report))
        write_markdown_report(
            markdown_report_path,
            _build_internal_carrier_markdown(
                role_path_mode=role_path_mode,
                statebus_mode=normalized_statebus_mode,
                comparison_valid=comparison_valid,
                missing_reason=mode_missing_reason,
                invalid_reason=invalid_reason,
                debug_metrics=debug_metrics,
            ),
        )
        mode_reports.append(mode_report)

    suite_comparison_summary: dict[str, float] = {
        "mode_count": float(len(mode_reports)),
        "valid_mode_count": float(sum(1 for report in mode_reports if report.comparison_valid)),
        "successful_mode_count": float(sum(1 for report in mode_reports if not report.missing_reason)),
    }
    if mode_reports:
        metric_keys = set().union(*(report.debug_metrics.keys() for report in mode_reports))
        for key in sorted(metric_keys):
            suite_comparison_summary[key] = sum(report.debug_metrics.get(key, 0.0) for report in mode_reports)
    report = BenchmarkComparatorSuiteReport(
        suite_id=suite_id,
        task_family=task_family,
        mode_reports=tuple(mode_reports),
        comparison_summary=suite_comparison_summary,
        benchmark_tier=benchmark_tier,
        claim_level=claim_level,
        report_path=str(benchmark_report_root / f"{suite_id}.json"),
        markdown_report_path=str(benchmark_report_root / f"{suite_id}.md"),
    )
    write_json_report(Path(report.report_path), comparator_suite_report_to_dict(report))
    write_markdown_report(
        Path(report.markdown_report_path),
        "# Fixed-Answer Internal Carrier Compare Suite\n\n"
        + "\n".join(
            f"- `{mode.role_path_mode}`: `{'valid' if mode.comparison_valid else 'invalid'}`"
            for mode in mode_reports
        )
        + "\n",
    )
    return report
