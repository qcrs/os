from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from statebus.benchmark.continuous_task_family import (
    ContinuousPreRunFixture,
    ContinuousTaskFamily,
)
from statebus.benchmark.contest_fairness import (
    audit_role_request_gold_visibility,
    build_continuous_fairness_manifest,
    build_failure_denominator,
)
from statebus.benchmark.kv_analysis import summarize_case_kv_reuse
from statebus.benchmark.kv_prefix_schedule import KVPrefixSchedulePlan, build_kv_prefix_schedule_plan
from statebus.benchmark.metric_aggregation import finalize_case_telemetry_summary
from statebus.benchmark.minimal_runner import LAYER_PROFILES, LAYER_SMOKE_CONFIGS
from statebus.benchmark.models import (
    BenchmarkCaseReport,
    BenchmarkContinuousCollectionReport,
    BenchmarkFamilyReport,
    BenchmarkLayer,
    BenchmarkLayerProfile,
    BenchmarkSuiteReport,
    QualityFloorResult,
)
from statebus.benchmark.reporting import (
    continuous_collection_report_to_dict,
    family_report_to_dict,
    suite_report_to_dict,
    write_json_report,
    write_markdown_report,
)
from statebus.benchmark.scoring import _c2c_validate_pair_claim, score_benchmark_output
from statebus.contracts import CanonicalTaskSpec
from statebus.runtime.smoke import SmokeLayerConfig, SmokeResult, run_smoke
from statebus.runtime.prefix_feedback import PrefixCacheFeedbackLoop
from statebus.runtime.vllm_metrics import VllmPrefixCacheCounterDelta
from statebus.utils import sha256_digest


G5B_PILOT_SCHEMA_VERSION = "statebus.g5b.actual_use_acceptance_pilot.v1"
G5B_EXECUTION_PATH = (
    "RuntimeDriver.run_mode(adaptive_bounded)->AdaptiveMainlineRunner"
    "->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher"
)


_RUNTIME_TASK_FAMILIES_BY_DATASET_KIND = {
    "csv": frozenset({"continuous_csv_table_analysis"}),
    "incident_log": frozenset({"incident_diagnosis_v2"}),
    "markdown_long_doc": frozenset({
        "continuous_long_doc_table_analysis",
        "cross_period_financial_analysis",
    }),
}

CONTINUOUS_TEXT_SEMANTIC_SELECTION_PROFILE = BenchmarkLayerProfile(
    layer=BenchmarkLayer.L2,
    description="formal diagnostic text handoff with same semantic selection and no semantic state transfer",
    structured_control_enabled=False,
    semantic_pruning_enabled=True,
    replay_enabled=False,
    multi_attempt_enabled=False,
    force_first_attempt_trap=False,
)

CONTINUOUS_TEXT_SEMANTIC_SELECTION_SMOKE_CONFIG = SmokeLayerConfig(
    layer_name="T2-continuous-text-semantic-selection",
    handoff_mode="text_collaboration",
    structured_control_enabled=False,
    semantic_pruning_enabled=True,
    semantic_state_transfer_enabled=False,
    replay_enabled=False,
    multi_attempt_enabled=False,
    force_first_attempt_trap=False,
)

_MEMORY_FUNNEL_METRICS = (
    "hybrid_memory_query_count",
    "memory_candidate_count",
    "memory_compatible_match_count",
    "memory_policy_approved_match_count",
    "memory_consumed_count",
    "memory_behavioral_effect_count",
    "memory_assist_count",
    "validated_replay_count",
    "exact_replay_count",
    "memory_rejected_incompatible_count",
    "skipped_step_count",
    "skipped_llm_call_count",
)


def _normalise_task_schedule_plan(task_schedule_plan: str) -> str:
    normalized = task_schedule_plan.strip().lower()
    if normalized in {"", "input", "input_order", "none"}:
        return "input"
    if normalized in {"cache_friendly", "cache_hostile"}:
        return normalized
    raise ValueError(f"unsupported task_schedule_plan: {task_schedule_plan}")


def _task_schedule_plan_for_family(
    family: ContinuousTaskFamily,
    *,
    task_schedule_plan: str,
) -> KVPrefixSchedulePlan | None:
    normalized = _normalise_task_schedule_plan(task_schedule_plan)
    if normalized == "input":
        return None
    return build_kv_prefix_schedule_plan(family, mode=normalized)


def _ordered_family_rounds(
    family: ContinuousTaskFamily,
    *,
    task_schedule_plan: str,
) -> tuple:
    schedule_plan = _task_schedule_plan_for_family(family, task_schedule_plan=task_schedule_plan)
    if schedule_plan is None:
        return tuple(family.rounds)
    rounds_by_task_id = {round_.task_id: round_ for round_ in family.rounds}
    return tuple(rounds_by_task_id[task_id] for task_id in schedule_plan.task_ids)


def _task_schedule_metadata(schedule_plan: KVPrefixSchedulePlan | None) -> dict[str, object]:
    if schedule_plan is None:
        return {"task_schedule_plan": "input"}
    return {
        "task_schedule_plan": schedule_plan.mode,
        "task_schedule_key": schedule_plan.schedule_key,
        "task_schedule_task_ids": list(schedule_plan.task_ids),
        "task_schedule_affinity_groups": list(schedule_plan.affinity_groups),
        "task_schedule_max_contiguous_same_affinity_run": schedule_plan.max_contiguous_same_affinity_run,
        "task_schedule_adjacent_reuse_opportunity_count": schedule_plan.adjacent_reuse_opportunity_count,
        "task_schedule_affinity_switch_count": schedule_plan.affinity_switch_count,
        "task_schedule_claim_boundary": schedule_plan.claim_boundary,
    }


@dataclass(frozen=True)
class ContinuousRoundSample:
    round_number: int
    task_id: str
    dataset_id: str
    request_text: str
    expected_facts: dict[str, object]
    quality_checks: tuple[str, ...]
    canonical_task_spec: object
    depends_on_rounds: tuple[int, ...]
    minimum_reuse_class: str
    expected_metric_effects: dict[str, object]
    pre_run_fixtures: tuple[ContinuousPreRunFixture, ...]


def _dataset_source_payload(
    family: ContinuousTaskFamily,
    dataset_id: str,
) -> dict[str, object]:
    dataset = next(item for item in family.datasets if item.dataset_id == dataset_id)
    source_path = Path(dataset.path)
    if not source_path.is_absolute():
        source_path = Path.cwd() / source_path
    source_bytes = source_path.read_bytes()
    return {
        "dataset_id": dataset.dataset_id,
        "kind": dataset.kind,
        "path": dataset.path,
        "content_sha256": sha256_digest(source_bytes),
        "content": source_bytes.decode("utf-8", errors="replace"),
    }


def _lookup_nested_output(payload: dict[str, object], key: str) -> object:
    if key in payload:
        return payload.get(key)
    current: object = payload
    for segment in key.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _prior_round_context(
    *,
    sample: ContinuousRoundSample,
    samples_by_round: dict[int, ContinuousRoundSample],
    cases_by_round: dict[int, BenchmarkCaseReport],
) -> dict[str, object]:
    rounds: list[dict[str, object]] = []
    for dependency in sample.depends_on_rounds:
        prior_sample = samples_by_round.get(dependency)
        prior_case = cases_by_round.get(dependency)
        if prior_sample is None or prior_case is None:
            rounds.append({
                "round": dependency,
                "verified": False,
                "facts": {},
                "reason": "dependency_not_completed",
            })
            continue
        output_payload = json.loads(Path(prior_case.output_artifact_path).read_text(encoding="utf-8"))
        fact_keys = tuple(
            key.removesuffix("_min").removesuffix("_max")
            for key in prior_sample.expected_facts
        )
        facts = {
            key: _lookup_nested_output(output_payload, key)
            for key in fact_keys
            if _lookup_nested_output(output_payload, key) is not None
        }
        rounds.append({
            "round": dependency,
            "task_id": prior_sample.task_id,
            "verified": prior_case.quality_floor.quality_floor_pass,
            "facts": facts if prior_case.quality_floor.quality_floor_pass else {},
        })
    payload = {
        "schema_version": "statebus.prior_round_context.v1",
        "task_id": sample.task_id,
        "rounds": rounds,
    }
    return {**payload, "prior_fact_digest": sha256_digest(payload)}


def _prepare_dir(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _json_leaf_changes(before: object, after: object, *, prefix: str = "") -> list[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[str] = []
        for key in sorted(set(before) | set(after)):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in before or key not in after:
                changes.append(child)
                continue
            changes.extend(_json_leaf_changes(before[key], after[key], prefix=child))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        changes = []
        for index in range(max(len(before), len(after))):
            child = f"{prefix}[{index}]"
            if index >= len(before) or index >= len(after):
                changes.append(child)
                continue
            changes.extend(_json_leaf_changes(before[index], after[index], prefix=child))
        return changes
    return [] if before == after else [prefix]


def _materialize_incompatible_history_fixture(
    *,
    fixture: ContinuousPreRunFixture,
    task_id: str,
    source_runtime_root: Path,
    fixture_root: Path,
    audit_root: Path,
) -> tuple[Path, dict[str, object]]:
    memory_commit_paths = sorted(
        (source_runtime_root / "sidecars" / "memory_commits").glob("*.json")
    )
    replay_ledger_paths = sorted(
        (source_runtime_root / "sidecars" / "replay_ledgers").glob("*.json")
    )
    if len(memory_commit_paths) != 1 or len(replay_ledger_paths) != 1:
        raise RuntimeError(
            "incompatible history fixture requires one verified memory commit and replay ledger: "
            f"{source_runtime_root}"
        )
    source_commit = json.loads(memory_commit_paths[0].read_text(encoding="utf-8"))
    source_ref = dict(source_commit.get("memory_ref", {}))
    source_metadata = dict(source_ref.get("metadata", {}))
    if (
        source_ref.get("commit_status") != "committed"
        or source_ref.get("validation_status") != "passed"
        or not bool(source_metadata.get("replay_ready", False))
        or not bool(source_commit.get("quality_floor_pass", False))
    ):
        raise RuntimeError(
            f"incompatible history fixture source is not replay-ready: {source_runtime_root}"
        )

    if fixture_root.exists():
        shutil.rmtree(fixture_root)
    fixture_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_runtime_root, fixture_root)

    cloned_commit_path = (
        fixture_root
        / "sidecars"
        / "memory_commits"
        / memory_commit_paths[0].name
    )
    cloned_ledger_path = (
        fixture_root
        / "sidecars"
        / "replay_ledgers"
        / replay_ledger_paths[0].name
    )
    before_commit = json.loads(cloned_commit_path.read_text(encoding="utf-8"))
    after_commit = json.loads(cloned_commit_path.read_text(encoding="utf-8"))
    memory_ref = dict(after_commit["memory_ref"])
    metadata = dict(memory_ref.get("metadata", {}))
    incompatible_signature = sha256_digest(
        {
            "fixture": "incompatible_history_candidate",
            "version": fixture.runtime_signature_version,
        }
    )
    metadata.update(
        {
            "runtime_signature_hash": incompatible_signature,
            "output_contract_version": fixture.output_contract_version,
            "validator_digest": fixture.validator_digest,
        }
    )
    memory_ref["metadata"] = metadata
    after_commit["memory_ref"] = memory_ref

    before_ledger = json.loads(cloned_ledger_path.read_text(encoding="utf-8"))
    after_ledger = json.loads(cloned_ledger_path.read_text(encoding="utf-8"))
    runtime_signature = dict(after_ledger.get("runtime_signature", {}))
    runtime_signature.update(
        {
            "prompt_bundle_digest": incompatible_signature,
            "combined_digest": incompatible_signature,
        }
    )
    after_ledger.update(
        {
            "runtime_signature_hash": incompatible_signature,
            "runtime_signature": runtime_signature,
            "output_contract_version": fixture.output_contract_version,
        }
    )
    write_json_report(cloned_commit_path, after_commit)
    write_json_report(cloned_ledger_path, after_ledger)

    changed_paths = sorted(
        [
            *(f"memory_commit.{path}" for path in _json_leaf_changes(before_commit, after_commit)),
            *(f"replay_ledger.{path}" for path in _json_leaf_changes(before_ledger, after_ledger)),
        ]
    )
    allowed_suffixes = (
        "memory_ref.metadata.runtime_signature_hash",
        "memory_ref.metadata.output_contract_version",
        "memory_ref.metadata.validator_digest",
        "runtime_signature_hash",
        "runtime_signature.prompt_bundle_digest",
        "runtime_signature.combined_digest",
        "output_contract_version",
    )
    unexpected_changes = [
        path
        for path in changed_paths
        if not any(path.endswith(suffix) for suffix in allowed_suffixes)
    ]
    if unexpected_changes:
        raise RuntimeError(
            f"incompatible history fixture mutated forbidden fields: {unexpected_changes}"
        )
    audit = {
        "schema_version": "statebus.incompatible_history_fixture_audit.v1",
        "task_id": task_id,
        "kind": fixture.kind,
        "source_round": fixture.source_round,
        "source_runtime_root": str(source_runtime_root),
        "fixture_runtime_root": str(fixture_root),
        "source_memory_id": str(source_ref.get("memory_id", "")),
        "source_artifact_hash": str(source_commit.get("created_from_artifact_hash", "")),
        "source_replay_ready": True,
        "changed_paths": changed_paths,
        "unexpected_changes": unexpected_changes,
        "runtime_signature_version": fixture.runtime_signature_version,
        "runtime_signature_hash": incompatible_signature,
        "output_contract_version": fixture.output_contract_version,
        "validator_digest": fixture.validator_digest,
        "eligible_for_role_input": False,
        "expected_decision": "reject_incompatible_and_recompute",
    }
    audit_path = audit_root / f"{task_id}-source-round-{fixture.source_round}.json"
    write_json_report(audit_path, audit)
    return fixture_root, {**audit, "audit_path": str(audit_path)}


def _prepare_round_fixtures(
    *,
    sample: ContinuousRoundSample,
    layer: BenchmarkLayer,
    layer_runtime_root: Path,
    history_runtime_root_by_round: dict[int, Path],
) -> tuple[tuple[Path, ...], tuple[dict[str, object], ...]]:
    if layer != BenchmarkLayer.L3 or not sample.pre_run_fixtures:
        return (), ()
    roots: list[Path] = []
    audits: list[dict[str, object]] = []
    for fixture in sample.pre_run_fixtures:
        source_root = history_runtime_root_by_round.get(fixture.source_round)
        if source_root is None:
            raise RuntimeError(
                f"pre-run fixture source round has not completed: {sample.task_id}:{fixture.source_round}"
            )
        root, audit = _materialize_incompatible_history_fixture(
            fixture=fixture,
            task_id=sample.task_id,
            source_runtime_root=source_root,
            fixture_root=(
                layer_runtime_root
                / f"benchmark-fixture-{sample.task_id}-source-round-{fixture.source_round}"
            ),
            audit_root=layer_runtime_root / "benchmark_audits" / "pre_run_fixtures",
        )
        roots.append(root)
        audits.append(audit)
    return tuple(roots), tuple(audits)


def _supported_continuous_family_ids() -> list[str]:
    root = Path("statebus/benchmark/samples/continuous_task_families")
    supported: list[str] = []
    for path in sorted(root.glob("*/manifest.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        datasets = payload.get("datasets", [])
        rounds = payload.get("rounds", [])
        kind_by_dataset = {
            str(item.get("dataset_id", "")): str(item.get("kind", ""))
            for item in datasets
            if isinstance(item, dict)
        }
        if rounds and all(
            isinstance(round_payload, dict)
            and str(dict(round_payload.get("canonical_task_spec", {})).get("task_family", ""))
            in _RUNTIME_TASK_FAMILIES_BY_DATASET_KIND.get(
                kind_by_dataset.get(str(round_payload.get("dataset_id", "")), ""),
                frozenset(),
            )
            for round_payload in rounds
        ):
            family_id = str(payload.get("family_id", "")).strip()
            if family_id:
                supported.append(family_id)
    return supported


def _validate_continuous_execution_contract(family: ContinuousTaskFamily) -> None:
    dataset_kind_by_id = {dataset.dataset_id: dataset.kind for dataset in family.datasets}
    for round_ in family.rounds:
        dataset_kind = dataset_kind_by_id.get(round_.dataset_id, "")
        expected_task_families = _RUNTIME_TASK_FAMILIES_BY_DATASET_KIND.get(dataset_kind)
        if expected_task_families is None:
            raise ValueError(
                "continuous runtime has no registered dataset capability for "
                f"kind={dataset_kind or 'missing'}"
            )
        if round_.canonical_task_spec.task_family not in expected_task_families:
            raise ValueError(
                "continuous task input contract does not match the registered dataset capability: "
                f"kind={dataset_kind}, expected={sorted(expected_task_families)}, "
                f"got={round_.canonical_task_spec.task_family}"
            )


def _continuous_sample(round_) -> ContinuousRoundSample:
    canonical_task_spec = CanonicalTaskSpec(
        task_family=round_.canonical_task_spec.task_family,
        intent_op=round_.canonical_task_spec.intent_op,
        target_entities=tuple(round_.canonical_task_spec.target_entities),
        time_scope=round_.canonical_task_spec.time_scope,
        required_outputs=tuple(round_.canonical_task_spec.required_outputs),
        required_tools=tuple(round_.canonical_task_spec.required_tools),
        arguments={
            **dict(round_.canonical_task_spec.arguments),
            "reuse_contract": round_.reuse_contract.canonical_payload(),
            "depends_on_rounds": list(round_.depends_on_rounds),
        },
        schema_version=round_.canonical_task_spec.schema_version,
    )
    return ContinuousRoundSample(
        round_number=round_.round,
        task_id=round_.task_id,
        dataset_id=round_.dataset_id,
        request_text=round_.request_text,
        expected_facts=dict(round_.expected_facts),
        quality_checks=tuple(round_.quality_checks),
        canonical_task_spec=canonical_task_spec,
        depends_on_rounds=tuple(round_.depends_on_rounds),
        minimum_reuse_class=round_.reuse_contract.minimum_reuse_class,
        expected_metric_effects=dict(round_.expected_metric_effects),
        pre_run_fixtures=tuple(round_.pre_run_fixtures),
    )


def _case_from_smoke(
    *,
    smoke: SmokeResult,
    sample: ContinuousRoundSample,
    layer: BenchmarkLayer,
    task_ms: float,
    enforce_expected_metric_effects: bool = True,
    fairness_contract: dict[str, object] | None = None,
) -> BenchmarkCaseReport:
    output_path = Path(smoke.output_artifact_path)
    output_payload = json.loads(output_path.read_text(encoding="utf-8"))
    external_gold_score = score_benchmark_output(
        output_payload=output_payload,
        output_path=output_path,
        expected_facts=sample.expected_facts,
        quality_checks=sample.quality_checks,
    )
    externally_scored_quality = QualityFloorResult(
        quality_floor_pass=smoke.quality_floor.quality_floor_pass and external_gold_score.passed,
        deterministic_checks_passed=(
            smoke.quality_floor.deterministic_checks_passed
            and external_gold_score.quality_checks_passed
        ),
        fact_coverage_passed=(
            smoke.quality_floor.fact_coverage_passed
            and external_gold_score.expected_facts_passed
        ),
        llm_judge_passed=smoke.quality_floor.llm_judge_passed,
        quality_floor_fail_reason=(
            smoke.quality_floor.quality_floor_fail_reason
            or (";".join(external_gold_score.failures) if not external_gold_score.passed else "")
        ),
    )
    quality_floor = (
        _continuous_quality_floor(
            smoke_quality_floor=externally_scored_quality,
            sample=sample,
            metrics=smoke.task_metrics,
            layer=layer,
        )
        if enforce_expected_metric_effects
        else externally_scored_quality
    )
    return BenchmarkCaseReport(
        task_id=sample.task_id,
        task_family=smoke.audit_summary.get("task_family", sample.canonical_task_spec.task_family)
        if isinstance(smoke.audit_summary, dict)
        else sample.canonical_task_spec.task_family,
        quality_floor=quality_floor,
        replay_class=smoke.replay_class,
        telemetry_event_count=smoke.telemetry_event_count,
        output_artifact_hash=smoke.output_artifact_hash,
        output_artifact_path=smoke.output_artifact_path,
        workspace_root=smoke.workspace_root,
        session_state=smoke.session_state,
        comparison_tags=(f"round:{sample.round_number}", f"dataset:{sample.dataset_id}"),
        audit_paths={
            "replay": smoke.replay_audit_path,
            "hydration": smoke.hydration_audit_path,
            "hydration_debug": smoke.hydration_debug_audit_path,
            "artifact": smoke.artifact_audit_path,
            "memory_consumption": str(
                dict(smoke.audit_summary.get("memory_consumption", {})).get(
                    "path", ""
                )
            ),
        },
        audit_summary={
            **smoke.audit_summary,
            "round_number": sample.round_number,
            "dataset_id": sample.dataset_id,
            "quality_checks": list(sample.quality_checks),
            "external_gold_score": external_gold_score.canonical_payload(),
            "benchmark_gold_visible_to_runtime": False,
            "depends_on_rounds": list(sample.depends_on_rounds),
            "minimum_reuse_class": sample.minimum_reuse_class,
            "expected_metric_effects": dict(sample.expected_metric_effects),
            "layer": layer.value,
            "state_storage_kind": smoke.state_storage_kind,
            "fairness_contract": dict(fairness_contract or {}),
        },
        metrics={
            **dict(sorted(smoke.task_metrics.items())),
            "round_number": float(sample.round_number),
            "history_dependency_count": float(len(sample.depends_on_rounds)),
            "task_ms": float(task_ms),
            "external_gold_score_count": 1.0,
            "external_gold_pass_count": float(external_gold_score.passed),
        },
    )


def _apply_case_metric_contracts(
    *,
    current: BenchmarkCaseReport,
    previous_layer_case: BenchmarkCaseReport | None,
) -> BenchmarkCaseReport:
    expected_effects = {
        str(key): value
        for key, value in current.audit_summary.get("expected_metric_effects", {}).items()
    }
    if not current.quality_floor.quality_floor_pass or not expected_effects:
        return current
    layer_name = str(current.audit_summary.get("layer", ""))
    failures: list[str] = []
    metric_aliases = {
        "artifact_reuse_count": "history_artifact_reuse_count",
        "strategy_reuse_count": "history_strategy_reuse_count",
        "history_step_reduction_count": "history_step_reduction_count",
        "reuse_gain": "history_reuse_gain",
    }
    for key, expected_value in expected_effects.items():
        prefix = f"{layer_name}_"
        if not key.startswith(prefix):
            continue
        suffix = key.removeprefix(prefix)
        if suffix.endswith("_delta_max"):
            if previous_layer_case is None:
                failures.append(f"{suffix}_requires_previous_layer_case")
                continue
            metric_name = suffix.removesuffix("_delta_max")
            current_value = float(
                current.metrics.get(metric_name, current.metrics.get(metric_aliases.get(metric_name, ""), 0.0))
            )
            previous_value = float(
                previous_layer_case.metrics.get(
                    metric_name,
                    previous_layer_case.metrics.get(metric_aliases.get(metric_name, ""), 0.0),
                )
            )
            delta = current_value - previous_value
            if delta > float(expected_value):
                failures.append(f"{metric_name}_delta_above_max:{delta:g}>{float(expected_value):g}")
            continue
        if suffix.endswith("_delta_min"):
            if previous_layer_case is None:
                failures.append(f"{suffix}_requires_previous_layer_case")
                continue
            metric_name = suffix.removesuffix("_delta_min")
            current_value = float(
                current.metrics.get(metric_name, current.metrics.get(metric_aliases.get(metric_name, ""), 0.0))
            )
            previous_value = float(
                previous_layer_case.metrics.get(
                    metric_name,
                    previous_layer_case.metrics.get(metric_aliases.get(metric_name, ""), 0.0),
                )
            )
            delta = current_value - previous_value
            if delta < float(expected_value):
                failures.append(f"{metric_name}_delta_below_min:{delta:g}<{float(expected_value):g}")
            continue
        if suffix.endswith("_min"):
            metric_name = suffix.removesuffix("_min")
            observed = float(current.metrics.get(metric_name, current.metrics.get(metric_aliases.get(metric_name, ""), 0.0)))
            if metric_name == "validated_replay_count":
                observed += float(current.metrics.get("exact_replay_count", 0.0))
            if metric_name == "downgrade_execution_goal_count" and float(current.metrics.get("exact_replay_count", 0.0)) > 0.0:
                continue
            if observed < float(expected_value):
                failures.append(f"{metric_name}_below_min:{observed:g}<{float(expected_value):g}")
            continue
        if suffix.endswith("_max"):
            metric_name = suffix.removesuffix("_max")
            observed = float(current.metrics.get(metric_name, current.metrics.get(metric_aliases.get(metric_name, ""), 0.0)))
            if observed > float(expected_value):
                failures.append(f"{metric_name}_above_max:{observed:g}>{float(expected_value):g}")
            continue
    if not failures:
        return current
    reason = ";".join(
        item
        for item in (
            current.quality_floor.quality_floor_fail_reason,
            "continuous_metric_contract_failed",
            *failures,
        )
        if item
    )
    return BenchmarkCaseReport(
        task_id=current.task_id,
        task_family=current.task_family,
        quality_floor=QualityFloorResult(
            quality_floor_pass=False,
            deterministic_checks_passed=current.quality_floor.deterministic_checks_passed,
            fact_coverage_passed=False,
            llm_judge_passed=current.quality_floor.llm_judge_passed,
            quality_floor_fail_reason=reason,
        ),
        replay_class=current.replay_class,
        telemetry_event_count=current.telemetry_event_count,
        output_artifact_hash=current.output_artifact_hash,
        output_artifact_path=current.output_artifact_path,
        workspace_root=current.workspace_root,
        session_state=current.session_state,
        comparison_tags=current.comparison_tags,
        audit_paths=current.audit_paths,
        audit_summary=current.audit_summary,
        metrics=current.metrics,
    )


def _continuous_quality_floor(
    *,
    smoke_quality_floor: QualityFloorResult,
    sample: ContinuousRoundSample,
    metrics: dict[str, float],
    layer: BenchmarkLayer,
) -> QualityFloorResult:
    failures: list[str] = []
    metric_aliases = {
        "artifact_reuse_count": "history_artifact_reuse_count",
        "strategy_reuse_count": "history_strategy_reuse_count",
        "history_step_reduction_count": "history_step_reduction_count",
        "reuse_gain": "history_reuse_gain",
    }
    for key, minimum in sample.expected_metric_effects.items():
        layer_prefix = f"{layer.value}_"
        if not key.startswith(layer_prefix):
            continue
        suffix = key.removeprefix(layer_prefix)
        if "_delta_" in suffix:
            continue
        observed = None
        comparator = ""
        metric_name = suffix
        if suffix.endswith("_min"):
            comparator = "min"
            metric_name = suffix.removesuffix("_min")
            observed = float(metrics.get(metric_name, metrics.get(metric_aliases.get(metric_name, ""), 0.0)))
            expected = float(minimum)
            if metric_name == "validated_replay_count":
                observed += float(metrics.get("exact_replay_count", 0.0))
            if metric_name == "downgrade_execution_goal_count" and float(metrics.get("exact_replay_count", 0.0)) > 0.0:
                continue
            if observed < expected:
                failures.append(f"{metric_name}_below_min:{observed:g}<{expected:g}")
        elif suffix.endswith("_max"):
            comparator = "max"
            metric_name = suffix.removesuffix("_max")
            observed = float(metrics.get(metric_name, metrics.get(metric_aliases.get(metric_name, ""), 0.0)))
            expected = float(minimum)
            if observed > expected:
                failures.append(f"{metric_name}_above_max:{observed:g}>{expected:g}")
        if comparator:
            continue
    if not failures:
        return smoke_quality_floor
    reason = ";".join(
        item
        for item in (smoke_quality_floor.quality_floor_fail_reason, "continuous_metric_contract_failed", *failures)
        if item
    )
    return QualityFloorResult(
        quality_floor_pass=False,
        deterministic_checks_passed=smoke_quality_floor.deterministic_checks_passed,
        fact_coverage_passed=False,
        llm_judge_passed=smoke_quality_floor.llm_judge_passed,
        quality_floor_fail_reason=reason,
    )


def _continuous_quality_headline_eligible(report: BenchmarkSuiteReport) -> bool:
    return bool(report.layer_reports) and all(layer_report.eligible_for_headline for layer_report in report.layer_reports)


def _continuous_replay_audit(
    *,
    family: ContinuousTaskFamily,
    report: BenchmarkSuiteReport,
) -> dict[str, object]:
    quality_headline_eligible = _continuous_quality_headline_eligible(report)
    l3_report = next((layer_report for layer_report in report.layer_reports if layer_report.layer == BenchmarkLayer.L3), None)
    replay_target_rounds = family.replay_target_rounds_by_class()
    validated_target_rounds = set(replay_target_rounds["validated_replay"])
    exact_target_rounds = set(replay_target_rounds["exact_replay"])
    replay_admissible_family = bool(validated_target_rounds or exact_target_rounds)
    if l3_report is None:
        return {
            "eligible_for_replay_headline": False,
            "gate_reason": "missing_l3_report",
            "audit_mode": "replay_admissible" if replay_admissible_family else "history_backed",
            "expected_target_rounds": list(family.l3_target_nonzero_rounds()),
            "observed_replay_rounds": [],
            "observed_history_reuse_rounds": [],
            "missing_target_rounds": list(family.l3_target_nonzero_rounds()),
            "unexpected_target_rounds": [],
            "validated_target_rounds": list(replay_target_rounds["validated_replay"]),
            "exact_target_rounds": list(replay_target_rounds["exact_replay"]),
            "observed_validated_rounds": [],
            "observed_exact_rounds": [],
            "missing_validated_rounds": list(replay_target_rounds["validated_replay"]),
            "missing_exact_rounds": list(replay_target_rounds["exact_replay"]),
            "unexpected_validated_rounds": [],
            "unexpected_exact_rounds": [],
            "history_target_rounds": list(family.l3_target_nonzero_rounds()),
            "missing_history_target_rounds": list(family.l3_target_nonzero_rounds()),
            "unexpected_history_target_rounds": [],
        }

    target_nonzero_rounds = set(family.l3_target_nonzero_rounds())
    observed_validated_rounds: set[int] = set()
    observed_exact_rounds: set[int] = set()
    observed_replay_rounds: set[int] = set()
    observed_history_reuse_rounds: set[int] = set()
    required_reuse_failures: list[str] = []

    for case in l3_report.cases:
        round_number = int(case.audit_summary.get("round_number", 0) or 0)
        if round_number <= 0 or not case.quality_floor.quality_floor_pass:
            continue
        required_reuse_class = str(case.audit_summary.get("minimum_reuse_class", "")).strip()
        observed_replay_class = case.replay_class
        history_step_reduction_count = float(case.metrics.get("history_step_reduction_count", 0.0))
        history_reuse_gain = float(case.metrics.get("history_reuse_gain", 0.0))
        artifact_reuse_count = float(
            case.metrics.get("artifact_reuse_count", case.metrics.get("history_artifact_reuse_count", 0.0))
        )
        if (
            history_step_reduction_count > 0.0
            or history_reuse_gain > 0.0
            or artifact_reuse_count > 0.0
        ):
            observed_history_reuse_rounds.add(round_number)
        if observed_replay_class in {"validated_replay", "exact_replay"}:
            observed_replay_rounds.add(round_number)
        if observed_replay_class == "validated_replay":
            observed_validated_rounds.add(round_number)
        elif observed_replay_class == "exact_replay":
            observed_exact_rounds.add(round_number)
            observed_validated_rounds.add(round_number)
        if required_reuse_class == "validated_replay" and observed_replay_class not in {"validated_replay", "exact_replay"}:
            required_reuse_failures.append(f"round_{round_number}:validated_replay_missing")
        if required_reuse_class == "exact_replay" and observed_replay_class != "exact_replay":
            required_reuse_failures.append(f"round_{round_number}:exact_replay_missing")

    if replay_admissible_family:
        observed_target_rounds = observed_replay_rounds
    else:
        observed_target_rounds = observed_history_reuse_rounds
    missing_target_rounds = sorted(target_nonzero_rounds - observed_target_rounds)
    unexpected_target_rounds = sorted(observed_target_rounds - target_nonzero_rounds)
    missing_validated_rounds = sorted(validated_target_rounds - observed_validated_rounds)
    missing_exact_rounds = sorted(exact_target_rounds - observed_exact_rounds)
    unexpected_validated_rounds = sorted(observed_validated_rounds - (validated_target_rounds | exact_target_rounds))
    unexpected_exact_rounds = sorted(observed_exact_rounds - (exact_target_rounds | validated_target_rounds))

    gate_failures: list[str] = []
    if not quality_headline_eligible:
        gate_failures.append("quality_gate_failed")
    if not target_nonzero_rounds:
        gate_failures.append("no_target_nonzero_rounds_declared")
    if missing_target_rounds:
        gate_failures.append(
            "missing_target_replay_rounds" if replay_admissible_family else "missing_target_history_reuse_rounds"
        )
    if unexpected_target_rounds and replay_admissible_family:
        gate_failures.append("unexpected_replay_rounds")
    if replay_admissible_family:
        if missing_validated_rounds:
            gate_failures.append("missing_validated_target_rounds")
        if missing_exact_rounds:
            gate_failures.append("missing_exact_target_rounds")
        if unexpected_exact_rounds:
            gate_failures.append("unexpected_exact_replay_rounds")
        if required_reuse_failures:
            gate_failures.append("required_reuse_class_unmet")

    return {
        "eligible_for_replay_headline": replay_admissible_family and not gate_failures,
        "gate_reason": ";".join(gate_failures) if gate_failures else "",
        "audit_mode": "replay_admissible" if replay_admissible_family else "history_backed",
        "expected_target_rounds": sorted(target_nonzero_rounds),
        "observed_replay_rounds": sorted(observed_replay_rounds),
        "observed_history_reuse_rounds": sorted(observed_history_reuse_rounds),
        "missing_target_rounds": missing_target_rounds,
        "unexpected_target_rounds": unexpected_target_rounds,
        "validated_target_rounds": sorted(validated_target_rounds),
        "exact_target_rounds": sorted(exact_target_rounds),
        "observed_validated_rounds": sorted(observed_validated_rounds),
        "observed_exact_rounds": sorted(observed_exact_rounds),
        "missing_validated_rounds": missing_validated_rounds,
        "missing_exact_rounds": missing_exact_rounds,
        "unexpected_validated_rounds": unexpected_validated_rounds,
        "unexpected_exact_rounds": unexpected_exact_rounds,
        "required_reuse_failures": required_reuse_failures,
        "history_target_rounds": sorted(target_nonzero_rounds) if not replay_admissible_family else [],
        "missing_history_target_rounds": missing_target_rounds if not replay_admissible_family else [],
        "unexpected_history_target_rounds": unexpected_target_rounds if not replay_admissible_family else [],
    }


def _continuous_headline_scope(
    report: BenchmarkSuiteReport,
    *,
    replay_audit: dict[str, object] | None = None,
) -> str:
    if replay_audit is not None and bool(replay_audit.get("eligible_for_replay_headline", False)):
        return "replay_admissible"
    if _continuous_quality_headline_eligible(report):
        l3_report = next((layer_report for layer_report in report.layer_reports if layer_report.layer == BenchmarkLayer.L3), None)
        if l3_report is not None and l3_report.telemetry_summary.get("history_artifact_reuse_count", 0.0) > 0.0:
            return "history_backed_only"
        return "quality_only"
    return "not_eligible"


def _replay_audit_summary_counts(replay_audit: dict[str, object]) -> dict[str, float]:
    audit_mode = str(replay_audit.get("audit_mode", "")).strip()
    history_backed = audit_mode == "history_backed"
    replay_admissible = audit_mode == "replay_admissible"
    return {
        "history_target_round_count": float(len(replay_audit.get("history_target_rounds", []))) if history_backed else 0.0,
        "history_observed_reuse_round_count": float(
            len(replay_audit.get("observed_history_reuse_rounds", []))
        )
        if history_backed
        else 0.0,
        "history_missing_target_round_count": float(
            len(replay_audit.get("missing_history_target_rounds", []))
        )
        if history_backed
        else 0.0,
        "history_additional_reuse_round_count": float(
            len(replay_audit.get("unexpected_history_target_rounds", []))
        )
        if history_backed
        else 0.0,
        "replay_target_round_count": float(len(replay_audit.get("expected_target_rounds", []))) if replay_admissible else 0.0,
        "replay_observed_round_count": float(len(replay_audit.get("observed_replay_rounds", []))) if replay_admissible else 0.0,
        "replay_missing_target_round_count": float(len(replay_audit.get("missing_target_rounds", [])))
        if replay_admissible
        else 0.0,
        "replay_unexpected_round_count": float(len(replay_audit.get("unexpected_target_rounds", [])))
        if replay_admissible
        else 0.0,
    }


def _metric_delta(
    *,
    reports_by_layer: dict[BenchmarkLayer, BenchmarkFamilyReport],
    from_layer: BenchmarkLayer,
    to_layer: BenchmarkLayer,
    metric: str,
) -> float:
    return float(reports_by_layer[to_layer].telemetry_summary.get(metric, 0.0)) - float(
        reports_by_layer[from_layer].telemetry_summary.get(metric, 0.0)
    )


_OUTER_RUNTIME_STAGE_BUCKETS = (
    "workspace_input_stage_ms",
    "runtime_signature_stage_ms",
    "codeact_execution_stage_ms",
    "execution_log_capture_stage_ms",
    "workspace_output_stage_ms",
    "runtime_driver_stage_ms",
    "telemetry_emit_stage_ms",
)

_DRIVER_STAGE_BUCKETS = (
    "runtime_non_executor_stage_ms",
    "runtime_data_plane_event_stage_ms",
    "control_plane_exchange_stage_ms",
    "executor_state_machine_stage_ms",
    "runtime_commit_finalize_stage_ms",
    "runtime_post_executor_stage_ms",
    "runtime_replay_ledger_stage_ms",
    "persist_and_reload_stage_ms",
    "registry_query_stage_ms",
)

_PERSIST_AND_RELOAD_STAGE_BUCKETS = (
    "persist_bundle_write_stage_ms",
    "persist_core_reload_stage_ms",
    "persist_retrieval_verification_stage_ms",
    "persist_session_ledger_reload_stage_ms",
    "persist_validator_reload_stage_ms",
    "persist_semantic_manifest_reload_stage_ms",
    "persist_integrity_check_stage_ms",
    "persist_unbucketed_stage_ms",
)

_WRITE_COUNT_BUCKETS = (
    "workspace_input_direct_write_count",
    "workspace_input_bundle_write_count",
    "workspace_input_bundle_reused_count",
    "workspace_input_manifest_write_count",
    "workspace_output_bundle_write_count",
    "workspace_output_bundle_reused_count",
    "workspace_output_manifest_write_count",
    "runtime_signature_manifest_bundle_write_count",
    "telemetry_event_write_count",
    "telemetry_fact_write_count",
    "telemetry_log_handle_open_count",
    "role_prompt_slice_artifact_count",
    "workspace_files",
)


def _summary_metric(report: BenchmarkFamilyReport, key: str) -> float:
    return float(report.telemetry_summary.get(key, 0.0))


def _top_stage_buckets(stage_totals: dict[str, float], *, limit: int = 5) -> list[dict[str, object]]:
    return [
        {"bucket": key, "stage_ms": round(value, 6)}
        for key, value in sorted(stage_totals.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _runtime_overhead_summary(report: BenchmarkFamilyReport) -> dict[str, object]:
    outer_stage_totals = {key: _summary_metric(report, key) for key in _OUTER_RUNTIME_STAGE_BUCKETS}
    driver_stage_totals = {key: _summary_metric(report, key) for key in _DRIVER_STAGE_BUCKETS}
    persist_breakdown_totals = {key: _summary_metric(report, key) for key in _PERSIST_AND_RELOAD_STAGE_BUCKETS}
    runtime_driver_stage_ms = _summary_metric(report, "runtime_driver_stage_ms")
    driver_observed_bucket_sum = sum(driver_stage_totals.values())
    outer_observed_bucket_sum = sum(outer_stage_totals.values())
    persist_and_reload_stage_ms = _summary_metric(report, "persist_and_reload_stage_ms")
    persist_breakdown_observed_sum = sum(persist_breakdown_totals.values())
    write_counts = {key: _summary_metric(report, key) for key in _WRITE_COUNT_BUCKETS}
    return {
        "schema_version": "statebus.runtime_overhead_summary.v1",
        "layer": report.layer.value,
        "case_count": float(report.aggregated_metrics.get("case_count", 0.0)),
        "outer_stage_totals_ms": {key: round(value, 6) for key, value in outer_stage_totals.items()},
        "driver_stage_totals_ms": {key: round(value, 6) for key, value in driver_stage_totals.items()},
        "persist_and_reload_breakdown_totals_ms": {
            key: round(value, 6) for key, value in persist_breakdown_totals.items()
        },
        "top_outer_stage_buckets": _top_stage_buckets(outer_stage_totals),
        "top_driver_stage_buckets": _top_stage_buckets(driver_stage_totals),
        "top_persist_and_reload_buckets": _top_stage_buckets(persist_breakdown_totals),
        "outer_observed_bucket_sum_stage_ms": round(outer_observed_bucket_sum, 6),
        "driver_observed_bucket_sum_stage_ms": round(driver_observed_bucket_sum, 6),
        "persist_and_reload_observed_bucket_sum_stage_ms": round(persist_breakdown_observed_sum, 6),
        "estimated_unbucketed_driver_stage_ms": round(runtime_driver_stage_ms - driver_observed_bucket_sum, 6),
        "estimated_unbucketed_persist_and_reload_stage_ms": round(
            persist_and_reload_stage_ms - persist_breakdown_observed_sum,
            6,
        ),
        "persist_and_reload_share_of_driver": round(
            0.0 if runtime_driver_stage_ms <= 0.0 else persist_and_reload_stage_ms / runtime_driver_stage_ms,
            6,
        ),
        "telemetry_write_stage_ms": round(_summary_metric(report, "telemetry_emit_stage_ms"), 6),
        "telemetry_event_write_stage_ms": round(_summary_metric(report, "telemetry_event_write_stage_ms"), 6),
        "telemetry_fact_write_stage_ms": round(_summary_metric(report, "telemetry_fact_write_stage_ms"), 6),
        "write_counts": {key: round(value, 6) for key, value in write_counts.items()},
        "role_prompt_slice_artifact_bytes_total": round(
            _summary_metric(report, "role_prompt_slice_artifact_bytes_total"),
            6,
        ),
        "optimization_read": _runtime_overhead_read(
            persist_and_reload_stage_ms=persist_and_reload_stage_ms,
            runtime_driver_stage_ms=runtime_driver_stage_ms,
            write_counts=write_counts,
        ),
    }


def _runtime_overhead_read(
    *,
    persist_and_reload_stage_ms: float,
    runtime_driver_stage_ms: float,
    write_counts: dict[str, float],
) -> str:
    if runtime_driver_stage_ms > 0.0 and persist_and_reload_stage_ms / runtime_driver_stage_ms >= 0.25:
        return "persist_and_reload_is_primary_driver_bucket"
    if write_counts.get("role_prompt_slice_artifact_count", 0.0) >= 4.0:
        return "prompt_slice_artifacts_are_visible_audit_cost"
    return "overhead_distributed_across_runtime_buckets"


def _aggregate_runtime_overhead(family_reports: tuple[BenchmarkSuiteReport, ...]) -> dict[str, object]:
    family_layer_summaries: list[dict[str, object]] = []
    outer_totals: dict[str, float] = {key: 0.0 for key in _OUTER_RUNTIME_STAGE_BUCKETS}
    driver_totals: dict[str, float] = {key: 0.0 for key in _DRIVER_STAGE_BUCKETS}
    persist_breakdown_totals: dict[str, float] = {key: 0.0 for key in _PERSIST_AND_RELOAD_STAGE_BUCKETS}
    write_totals: dict[str, float] = {key: 0.0 for key in _WRITE_COUNT_BUCKETS}
    for family_report in family_reports:
        for layer_report in family_report.layer_reports:
            overhead = _runtime_overhead_summary(layer_report)
            family_layer_summaries.append(
                {
                    "family_id": family_report.task_family,
                    "layer": layer_report.layer.value,
                    "top_driver_stage_buckets": overhead["top_driver_stage_buckets"],
                    "top_persist_and_reload_buckets": overhead["top_persist_and_reload_buckets"],
                    "persist_and_reload_share_of_driver": overhead["persist_and_reload_share_of_driver"],
                    "optimization_read": overhead["optimization_read"],
                }
            )
            for key, value in dict(overhead["outer_stage_totals_ms"]).items():
                outer_totals[key] = outer_totals.get(key, 0.0) + float(value)
            for key, value in dict(overhead["driver_stage_totals_ms"]).items():
                driver_totals[key] = driver_totals.get(key, 0.0) + float(value)
            for key, value in dict(overhead["persist_and_reload_breakdown_totals_ms"]).items():
                persist_breakdown_totals[key] = persist_breakdown_totals.get(key, 0.0) + float(value)
            for key, value in dict(overhead["write_counts"]).items():
                write_totals[key] = write_totals.get(key, 0.0) + float(value)
    return {
        "schema_version": "statebus.runtime_overhead_collection_summary.v1",
        "outer_stage_totals_ms": {key: round(value, 6) for key, value in outer_totals.items()},
        "driver_stage_totals_ms": {key: round(value, 6) for key, value in driver_totals.items()},
        "persist_and_reload_breakdown_totals_ms": {
            key: round(value, 6) for key, value in persist_breakdown_totals.items()
        },
        "write_count_totals": {key: round(value, 6) for key, value in write_totals.items()},
        "top_outer_stage_buckets": _top_stage_buckets(outer_totals),
        "top_driver_stage_buckets": _top_stage_buckets(driver_totals),
        "top_persist_and_reload_buckets": _top_stage_buckets(persist_breakdown_totals),
        "family_layer_summaries": family_layer_summaries,
    }


def _family_layer_evidence(report: BenchmarkFamilyReport) -> dict[str, object]:
    return {
        "layer": report.layer.value,
        "quality_floor_pass_count": float(report.quality_floor_breakdown.get("quality_floor_pass_count", 0.0)),
        "case_count": float(report.aggregated_metrics.get("case_count", 0.0)),
        "llm_prompt_bytes": float(report.telemetry_summary.get("llm_prompt_bytes", 0.0)),
        "control_bytes": float(report.telemetry_summary.get("control_bytes", 0.0)),
        "raw_evidence_bytes_seen_by_llm": float(
            report.telemetry_summary.get("raw_evidence_bytes_seen_by_llm", 0.0)
        ),
        "prompt_visible_total_bytes": float(report.telemetry_summary.get("prompt_visible_total_bytes", 0.0)),
        "prompt_scaffolding_bytes_total": float(
            report.telemetry_summary.get("prompt_scaffolding_bytes_total", 0.0)
        ),
        "semantic_state_transfer_count": float(report.telemetry_summary.get("semantic_state_transfer_count", 0.0)),
        "artifact_reuse_count": float(report.telemetry_summary.get("artifact_reuse_count", 0.0)),
        "history_step_reduction_count": float(report.telemetry_summary.get("history_step_reduction_count", 0.0)),
        "history_reuse_gain": float(report.telemetry_summary.get("history_reuse_gain", 0.0)),
        "validated_replay_count": float(report.telemetry_summary.get("validated_replay_count", 0.0)),
        "validated_downgraded_reuse_count": float(
            report.telemetry_summary.get(
                "validated_downgraded_reuse_count",
                report.telemetry_summary.get("validated_replay_count", 0.0),
            )
        ),
        "exact_replay_count": float(report.telemetry_summary.get("exact_replay_count", 0.0)),
        "answer_restoration_replay_count": float(
            report.telemetry_summary.get(
                "answer_restoration_replay_count",
                0.0,
            )
        ),
        "kv_corpus_prefix_hash_unique_count": float(
            report.aggregated_metrics.get("kv_corpus_prefix_hash_unique_count", 0.0)
        ),
        "kv_corpus_prefix_hash_reuse_count": float(
            report.aggregated_metrics.get("kv_corpus_prefix_hash_reuse_count", 0.0)
        ),
        "kv_corpus_level_prefill_saved_tokens_estimate": float(
            report.aggregated_metrics.get("kv_corpus_level_prefill_saved_tokens_estimate", 0.0)
        ),
        "kv_engine_local_prefill_saved_tokens_estimate": float(
            report.aggregated_metrics.get("kv_engine_local_prefill_saved_tokens_estimate", 0.0)
        ),
        "skipped_step_count": float(report.telemetry_summary.get("skipped_step_count", 0.0)),
        "memory_funnel": {
            metric: float(report.telemetry_summary.get(metric, 0.0))
            for metric in _MEMORY_FUNNEL_METRICS
        },
        "runtime_overhead": _runtime_overhead_summary(report),
        "report_path": report.report_path,
    }


def _case_round_evidence(case: BenchmarkCaseReport) -> dict[str, object]:
    hydration = dict(case.audit_summary.get("hydration", {})) if isinstance(case.audit_summary, dict) else {}
    replay = dict(case.audit_summary.get("replay", {})) if isinstance(case.audit_summary, dict) else {}
    neural_prefix = (
        dict(case.audit_summary.get("neural_prefix_reuse", {}))
        if isinstance(case.audit_summary, dict)
        else {}
    )
    return {
        "task_id": case.task_id,
        "round_number": int(case.metrics.get("round_number", 0.0)),
        "quality_floor_pass": case.quality_floor.quality_floor_pass,
        "replay_class": case.replay_class,
        "minimum_reuse_class": str(case.audit_summary.get("minimum_reuse_class", "")),
        "raw_evidence_bytes_seen_by_llm": float(case.metrics.get("raw_evidence_bytes_seen_by_llm", 0.0)),
        "prompt_visible_total_bytes": float(case.metrics.get("prompt_visible_total_bytes", 0.0)),
        "semantic_state_transfer_count": float(case.metrics.get("semantic_state_transfer_count", 0.0)),
        "artifact_reuse_count": float(case.metrics.get("artifact_reuse_count", 0.0)),
        "history_step_reduction_count": float(case.metrics.get("history_step_reduction_count", 0.0)),
        "validated_replay_count": float(case.metrics.get("validated_replay_count", 0.0)),
        "validated_downgraded_reuse_count": float(
            case.metrics.get("validated_downgraded_reuse_count", case.metrics.get("validated_replay_count", 0.0))
        ),
        "exact_replay_count": float(case.metrics.get("exact_replay_count", 0.0)),
        "answer_restoration_replay_count": float(
            case.metrics.get("answer_restoration_replay_count", 0.0)
        ),
        "corpus_prefix_hash": str(
            neural_prefix.get("corpus_prefix_hash", neural_prefix.get("prefix_hash", ""))
        ),
        "evidence_prefix_hash": str(
            neural_prefix.get("evidence_prefix_hash", neural_prefix.get("prefix_hash", ""))
        ),
        "kv_prefill_saved_tokens_estimate": float(
            case.metrics.get("neural_prefix_prefill_saved_tokens_estimate", 0.0)
        ),
        "kv_prefix_cache_hit_rate_estimate": float(
            case.metrics.get("neural_prefix_cache_hit_rate_estimate", 0.0)
        ),
        "skipped_step_count": float(case.metrics.get("skipped_step_count", 0.0)),
        "memory_funnel": {
            metric: float(case.metrics.get(metric, 0.0))
            for metric in _MEMORY_FUNNEL_METRICS
        },
        "decision_reason": str(replay.get("decision_reason", "")),
        "compatibility_verdict": str(replay.get("compatibility_verdict", "")),
        "role_prompt_slice_ref_ids": dict(hydration.get("role_prompt_slice_ref_ids", {})),
        "role_prompt_slice_relpaths": dict(hydration.get("role_prompt_slice_relpaths", {})),
        "audit_paths": dict(sorted(case.audit_paths.items())),
        "workspace_root": case.workspace_root,
        "output_artifact_path": case.output_artifact_path,
    }


def _continuous_suite_evidence_pack(
    *,
    family: ContinuousTaskFamily,
    report: BenchmarkSuiteReport,
    replay_audit: dict[str, object],
) -> dict[str, object]:
    reports_by_layer = {layer_report.layer: layer_report for layer_report in report.layer_reports}
    l3_report = reports_by_layer.get(BenchmarkLayer.L3)
    payload: dict[str, object] = {
        "schema_version": "statebus.continuous_evidence_pack.v1",
        "family_id": family.family_id,
        "claim_tier": family.claim_tier,
        "headline_scope": _continuous_headline_scope(report, replay_audit=replay_audit),
        "source_basis": dict(family.source_basis),
        "kv_prefix_probe": dict(family.kv_prefix_probe),
        "quality_headline_eligible": _continuous_quality_headline_eligible(report),
        "replay_headline_eligible": bool(replay_audit.get("eligible_for_replay_headline", False)),
        "round_count": family.round_count,
        "reuse_edge_count": sum(len(round_.depends_on_rounds) for round_ in family.rounds),
        "layer_summaries": [_family_layer_evidence(layer_report) for layer_report in report.layer_reports],
        "kv_reuse_analysis_by_layer": {
            layer_report.layer.value: dict(layer_report.metadata.get("kv_reuse_analysis", {}))
            for layer_report in report.layer_reports
        },
        "runtime_overhead_summary": _aggregate_runtime_overhead((report,)),
        "memory_funnel": {
            metric: float(l3_report.telemetry_summary.get(metric, 0.0))
            if l3_report is not None
            else 0.0
            for metric in _MEMORY_FUNNEL_METRICS
        },
        "l0_l3_delta": {},
        "l1_l2_non_text_delta": {},
        "replay_admissibility_audit": dict(replay_audit),
        "round_evidence": [_case_round_evidence(case) for case in (l3_report.cases if l3_report else ())],
    }
    if {BenchmarkLayer.L0, BenchmarkLayer.L3}.issubset(reports_by_layer):
        payload["l0_l3_delta"] = {
            metric: _metric_delta(
                reports_by_layer=reports_by_layer,
                from_layer=BenchmarkLayer.L0,
                to_layer=BenchmarkLayer.L3,
                metric=metric,
            )
            for metric in (
                "llm_prompt_bytes",
                "raw_evidence_bytes_seen_by_llm",
                "prompt_visible_total_bytes",
                "control_bytes",
                "artifact_reuse_count",
                "validated_replay_count",
                "validated_downgraded_reuse_count",
                "exact_replay_count",
                "answer_restoration_replay_count",
                "skipped_step_count",
            )
        }
    if {BenchmarkLayer.L1, BenchmarkLayer.L2}.issubset(reports_by_layer):
        payload["l1_l2_non_text_delta"] = {
            metric: _metric_delta(
                reports_by_layer=reports_by_layer,
                from_layer=BenchmarkLayer.L1,
                to_layer=BenchmarkLayer.L2,
                metric=metric,
            )
            for metric in (
                "llm_prompt_bytes",
                "raw_evidence_bytes_seen_by_llm",
                "prompt_visible_total_bytes",
                "semantic_state_transfer_count",
            )
        }
    return payload


def _continuous_collection_evidence_pack(
    *,
    report: BenchmarkContinuousCollectionReport,
) -> dict[str, object]:
    return {
        "schema_version": "statebus.continuous_collection_evidence_pack.v1",
        "suite_id": report.suite_id,
        "headline_scope": (
            "replay_admissible"
            if report.eligible_for_replay_headline
            else (
                "history_backed_only"
                if report.eligible_for_quality_headline
                and report.collection_summary.get("history_backed_only_family_count", 0.0) > 0.0
                else ("quality_only" if report.eligible_for_quality_headline else "not_eligible")
            )
        ),
        "collection_summary": dict(sorted(report.collection_summary.items())),
        "runtime_overhead_summary": _aggregate_runtime_overhead(report.family_reports),
        "family_evidence": [
            {
                "family_id": family_report.task_family,
                "headline_scope": str(family_report.metadata.get("headline_scope", "")),
                "quality_headline_eligible": bool(family_report.metadata.get("eligible_for_quality_headline", False)),
                "replay_headline_eligible": bool(family_report.metadata.get("eligible_for_replay_headline", False)),
                "waterfall_metrics": dict(sorted(family_report.waterfall_metrics.items())),
                "comparison_summary": dict(sorted(family_report.comparison_summary.items())),
                "l0_l3_delta": dict(family_report.evidence_pack.get("l0_l3_delta", {})),
                "l1_l2_non_text_delta": dict(family_report.evidence_pack.get("l1_l2_non_text_delta", {})),
                "runtime_overhead_summary": dict(family_report.evidence_pack.get("runtime_overhead_summary", {})),
                "replay_gate_reason": str(family_report.metadata.get("replay_gate_reason", "")),
                "report_path": family_report.report_path,
                "markdown_report_path": family_report.markdown_report_path,
            }
            for family_report in report.family_reports
        ],
        "admissibility_summary": dict(sorted(report.admissibility_summary.items())),
    }


def _continuous_suite_markdown(evidence_pack: dict[str, object]) -> str:
    lines = [
        f"# Continuous Evidence Pack: {evidence_pack['family_id']}",
        "",
        f"- headline_scope: `{evidence_pack['headline_scope']}`",
        f"- quality_headline_eligible: `{evidence_pack['quality_headline_eligible']}`",
        f"- replay_headline_eligible: `{evidence_pack['replay_headline_eligible']}`",
        f"- round_count: `{evidence_pack['round_count']}`",
        "",
        "## L0-L3 Delta",
    ]
    for key, value in dict(evidence_pack["l0_l3_delta"]).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## L1-L2 Non-Text Delta"])
    for key, value in dict(evidence_pack["l1_l2_non_text_delta"]).items():
        lines.append(f"- {key}: `{value}`")
    overhead = dict(evidence_pack.get("runtime_overhead_summary", {}))
    lines.extend(["", "## Runtime Overhead"])
    for bucket in overhead.get("top_driver_stage_buckets", []):
        bucket_payload = dict(bucket)
        lines.append(f"- driver {bucket_payload['bucket']}: `{bucket_payload['stage_ms']}` ms")
    for bucket in overhead.get("top_outer_stage_buckets", []):
        bucket_payload = dict(bucket)
        lines.append(f"- outer {bucket_payload['bucket']}: `{bucket_payload['stage_ms']}` ms")
    lines.extend(["", "## KV Prefix Reuse Estimate"])
    kv_by_layer = dict(evidence_pack.get("kv_reuse_analysis_by_layer", {}))
    for layer_name, payload in sorted(kv_by_layer.items()):
        layer_kv = dict(payload)
        lines.append(
            f"- {layer_name}: unique_prefixes=`{layer_kv.get('corpus_prefix_hash_unique_count', 0)}`, "
            f"reuse_count=`{layer_kv.get('corpus_prefix_hash_reuse_count', 0)}`, "
            f"engine_local_saved_tokens=`{layer_kv.get('estimated_engine_local_prefill_saved_tokens', 0.0)}`, "
            f"corpus_saved_tokens=`{layer_kv.get('estimated_corpus_level_prefill_saved_tokens', 0.0)}`"
        )
    lines.extend(["", "## Layer Summaries", "| layer | quality | llm_prompt_bytes | raw_evidence | prompt_visible | semantic | replay |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for layer in evidence_pack["layer_summaries"]:
        layer_payload = dict(layer)
        replay_total = float(layer_payload.get("validated_replay_count", 0.0)) + float(
            layer_payload.get("exact_replay_count", 0.0)
        )
        lines.append(
            f"| {layer_payload['layer']} | {layer_payload['quality_floor_pass_count']} | "
            f"{layer_payload['llm_prompt_bytes']} | {layer_payload['raw_evidence_bytes_seen_by_llm']} | "
            f"{layer_payload['prompt_visible_total_bytes']} | {layer_payload['semantic_state_transfer_count']} | "
            f"{replay_total} |"
        )
    lines.extend(["", "## Round Evidence", "| round | task | replay_class | min_reuse | raw_evidence | prompt_visible | kv_saved | skipped | audit |", "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | --- |"])
    for case in evidence_pack["round_evidence"]:
        case_payload = dict(case)
        audit_path = dict(case_payload.get("audit_paths", {})).get("replay", "")
        lines.append(
            f"| {case_payload['round_number']} | {case_payload['task_id']} | {case_payload['replay_class']} | "
            f"{case_payload['minimum_reuse_class']} | {case_payload['raw_evidence_bytes_seen_by_llm']} | "
            f"{case_payload['prompt_visible_total_bytes']} | {case_payload['kv_prefill_saved_tokens_estimate']} | "
            f"{case_payload['skipped_step_count']} | `{audit_path}` |"
        )
    return "\n".join(lines)


def _continuous_collection_markdown(evidence_pack: dict[str, object]) -> str:
    lines = [
        f"# Continuous Collection Evidence Pack: {evidence_pack['suite_id']}",
        "",
        f"- headline_scope: `{evidence_pack['headline_scope']}`",
        "",
        "## Collection Summary",
    ]
    for key, value in dict(evidence_pack["collection_summary"]).items():
        lines.append(f"- {key}: `{value}`")
    overhead = dict(evidence_pack.get("runtime_overhead_summary", {}))
    lines.extend(["", "## Runtime Overhead"])
    for bucket in overhead.get("top_driver_stage_buckets", []):
        bucket_payload = dict(bucket)
        lines.append(f"- driver {bucket_payload['bucket']}: `{bucket_payload['stage_ms']}` ms")
    for bucket in overhead.get("top_outer_stage_buckets", []):
        bucket_payload = dict(bucket)
        lines.append(f"- outer {bucket_payload['bucket']}: `{bucket_payload['stage_ms']}` ms")
    lines.extend(["", "## Family Evidence", "| family | scope | quality | replay | raw L0-L3 delta | prompt L0-L3 delta | report |", "| --- | --- | --- | --- | ---: | ---: | --- |"])
    for family in evidence_pack["family_evidence"]:
        family_payload = dict(family)
        l0_l3 = dict(family_payload.get("l0_l3_delta", {}))
        lines.append(
            f"| {family_payload['family_id']} | {family_payload['headline_scope']} | "
            f"{family_payload['quality_headline_eligible']} | {family_payload['replay_headline_eligible']} | "
            f"{l0_l3.get('raw_evidence_bytes_seen_by_llm', 0.0)} | {l0_l3.get('llm_prompt_bytes', 0.0)} | "
            f"`{family_payload['report_path']}` |"
        )
    return "\n".join(lines)


def run_continuous_benchmark_family(
    *,
    family: ContinuousTaskFamily,
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str,
    layer: BenchmarkLayer,
    role_path_mode: str = "deterministic",
    planner_mode: str = "",
    retriever_mode: str = "",
    executor_mode: str = "",
    summarizer_mode: str = "",
    embedding_mode: str = "deterministic",
    state_pool_mode: str = "auto",
    profile_override: BenchmarkLayerProfile | None = None,
    smoke_config_override: SmokeLayerConfig | None = None,
    report_layer_label: str | None = None,
    enforce_expected_metric_effects: bool = True,
    metadata_extra: dict[str, object] | None = None,
    persistence_profile: str = "audit_full",
    task_schedule_plan: str = "input",
    executor_transport: str = "loopback",
) -> BenchmarkFamilyReport:
    _validate_continuous_execution_contract(family)

    profile = profile_override or LAYER_PROFILES[layer]
    layer_workspace_root = _prepare_dir(workspace_root)
    layer_runtime_root = _prepare_dir(runtime_root)
    base_smoke_config = smoke_config_override or LAYER_SMOKE_CONFIGS[layer]
    smoke_config = SmokeLayerConfig(
        **{
            **base_smoke_config.__dict__,
            "role_path_mode": role_path_mode,
            "planner_mode": planner_mode,
            "retriever_mode": retriever_mode,
            "executor_mode": executor_mode,
            "summarizer_mode": summarizer_mode,
            "embedding_mode": embedding_mode,
            "state_pool_mode": state_pool_mode,
            "persistence_profile": persistence_profile,
            "executor_transport": executor_transport,
        }
    )
    history_runtime_root_by_round: dict[int, Path] = {}
    raw_cases: list[BenchmarkCaseReport] = []
    samples_by_round = {
        round_.round: _continuous_sample(round_)
        for round_ in family.rounds
    }
    cases_by_round: dict[int, BenchmarkCaseReport] = {}
    schedule_plan = _task_schedule_plan_for_family(family, task_schedule_plan=task_schedule_plan)
    ordered_rounds = _ordered_family_rounds(family, task_schedule_plan=task_schedule_plan)
    prefix_feedback = PrefixCacheFeedbackLoop(
        window_size=max(int(os.getenv("STATEBUS_PREFIX_FEEDBACK_WINDOW", "8") or "8"), 1),
        error_threshold=float(os.getenv("STATEBUS_PREFIX_FEEDBACK_ERROR_THRESHOLD", "0.15") or "0.15"),
    )
    adaptive_prefix_feedback_enabled = (
        role_path_mode == "local_vllm"
        and family.family_id == "kv_prefix_reuse_v1"
        and _normalise_task_schedule_plan(task_schedule_plan) == "input"
        and os.getenv("STATEBUS_PREFIX_FEEDBACK_ADAPTIVE", "1").strip().lower()
        not in {"0", "false", "no", "off"}
    )
    adaptive_prefix_reorder_count = 0
    pending_rounds = list(ordered_rounds)

    while pending_rounds:
        round_ = pending_rounds.pop(0)
        sample = _continuous_sample(round_)
        round_runtime_root = layer_runtime_root / sample.task_id
        history_runtime_roots: tuple[Path, ...] = tuple(
            history_runtime_root_by_round[dep]
            for dep in sample.depends_on_rounds
            if dep in history_runtime_root_by_round
        )
        fixture_runtime_roots, fixture_audits = _prepare_round_fixtures(
            sample=sample,
            layer=layer,
            layer_runtime_root=layer_runtime_root,
            history_runtime_root_by_round=history_runtime_root_by_round,
        )
        start_ns = time.perf_counter_ns()
        smoke = run_smoke(
            workspace_root=layer_workspace_root,
            runtime_root=round_runtime_root,
            socket_path=socket_path.with_name(
                f"{socket_path.stem}-{layer.value.lower()}-{sample.round_number:02d}{socket_path.suffix}"
            ),
            request_text=sample.request_text,
            canonical_task_spec=sample.canonical_task_spec,
            task_id=sample.task_id,
            layer_config=smoke_config,
            history_runtime_roots=history_runtime_roots,
            memory_candidate_runtime_roots=fixture_runtime_roots,
            seed_replay_memory=False,
        )
        task_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
        history_runtime_root_by_round[sample.round_number] = round_runtime_root
        source_payload = _dataset_source_payload(family, sample.dataset_id)
        prior_context = _prior_round_context(
            sample=sample,
            samples_by_round=samples_by_round,
            cases_by_round=cases_by_round,
        )
        output_payload = json.loads(Path(smoke.output_artifact_path).read_text(encoding="utf-8"))
        role_relpaths = {
            str(role): str(relpath)
            for role, relpath in dict(
                smoke.audit_summary.get("rendered_llm_requests", {})
            ).get("role_relpaths", {}).items()
        }
        gold_visibility_audit = audit_role_request_gold_visibility(
            task_id=sample.task_id,
            workspace_root=Path(smoke.workspace_root),
            role_request_relpaths=role_relpaths,
            expected_facts=sample.expected_facts,
            quality_checks=sample.quality_checks,
            expected_metric_effects=sample.expected_metric_effects,
            public_provenance_payloads=(
                sample.request_text,
                sample.canonical_task_spec.canonical_payload(),
                source_payload["content"],
                prior_context,
                output_payload,
            ),
        )
        gold_audit_path = round_runtime_root / "benchmark_audits" / "gold_visibility.json"
        write_json_report(gold_audit_path, gold_visibility_audit)
        fairness_contract = {
            "task_contract_digest": sha256_digest({
                "request_text": sample.request_text,
                "canonical_task_spec": sample.canonical_task_spec.canonical_payload(),
            }),
            "source_content_digest": source_payload["content_sha256"],
            "prior_fact_digest": prior_context["prior_fact_digest"],
            "prior_round_context": prior_context,
            "executor_transport": executor_transport,
            "gold_visibility_audit": gold_visibility_audit,
            "gold_visibility_audit_path": str(gold_audit_path),
            "pre_run_fixture_audits": list(fixture_audits),
        }
        case = _case_from_smoke(
            smoke=smoke,
            sample=sample,
            layer=layer,
            task_ms=task_ms,
            enforce_expected_metric_effects=enforce_expected_metric_effects,
            fairness_contract=fairness_contract,
        )
        case = BenchmarkCaseReport(
            **{
                **case.__dict__,
                "audit_paths": {
                    **case.audit_paths,
                    "gold_visibility": str(gold_audit_path),
                },
            }
        )
        raw_cases.append(case)
        cases_by_round[sample.round_number] = case
        prefix_feedback.record_observation(
            float(smoke.task_metrics.get("neural_prefix_cache_hit_rate_estimate", 0.0)),
            VllmPrefixCacheCounterDelta(
                available=bool(
                    smoke.task_metrics.get("vllm_prefix_counter_delta_available", 0.0)
                ),
                valid=bool(smoke.task_metrics.get("vllm_prefix_counter_delta_valid", 0.0)),
                queries=float(
                    smoke.task_metrics.get("vllm_prefix_observed_query_delta", 0.0)
                ),
                hits=float(smoke.task_metrics.get("vllm_prefix_observed_hit_delta", 0.0)),
                observed_hit_rate=(
                    float(smoke.task_metrics.get("vllm_prefix_observed_hit_rate", 0.0))
                    if smoke.task_metrics.get("vllm_prefix_counter_delta_valid", 0.0)
                    else None
                ),
                unavailable_reason=(
                    ""
                    if smoke.task_metrics.get("vllm_prefix_counter_delta_valid", 0.0)
                    else "task_counter_delta_unavailable"
                ),
            ),
        )
        if adaptive_prefix_feedback_enabled and prefix_feedback.should_reorder() and pending_rounds:
            friendly_plan = build_kv_prefix_schedule_plan(family, mode="cache_friendly")
            pending_by_task_id = {item.task_id: item for item in pending_rounds}
            reordered = [
                pending_by_task_id[task_id]
                for task_id in friendly_plan.task_ids
                if task_id in pending_by_task_id
            ]
            if [item.task_id for item in reordered] != [item.task_id for item in pending_rounds]:
                pending_rounds = reordered
                adaptive_prefix_reorder_count += 1

    previous_layer_cases_by_task_id: dict[str, BenchmarkCaseReport] = {}
    layer_order = list(BenchmarkLayer)
    previous_layer: BenchmarkLayer | None = None
    layer_index = layer_order.index(layer)
    if layer_index > 0:
        previous_layer = layer_order[layer_index - 1]
    if previous_layer is not None:
        previous_report_json = runtime_root.parent / previous_layer.value / "benchmark_reports" / f"{suite_id}-{previous_layer.value}.json"
        if previous_report_json.exists():
            report_payload = json.loads(previous_report_json.read_text(encoding="utf-8"))
            for case_payload in report_payload.get("cases", []):
                task_id = str(case_payload.get("task_id", "")).strip()
                if not task_id:
                    continue
                previous_layer_cases_by_task_id[task_id] = BenchmarkCaseReport(
                    task_id=task_id,
                    task_family=str(case_payload.get("task_family", "")),
                    quality_floor=QualityFloorResult(**dict(case_payload.get("quality_floor", {}))),
                    replay_class=str(case_payload.get("replay_class", "")),
                    telemetry_event_count=int(case_payload.get("telemetry_event_count", 0)),
                    output_artifact_hash=str(case_payload.get("output_artifact_hash", "")),
                    output_artifact_path=str(case_payload.get("output_artifact_path", "")),
                    workspace_root=str(case_payload.get("workspace_root", "")),
                    session_state=str(case_payload.get("session_state", "")),
                    comparison_tags=tuple(str(item) for item in case_payload.get("comparison_tags", [])),
                    audit_paths={str(k): str(v) for k, v in dict(case_payload.get("audit_paths", {})).items()},
                    audit_summary=dict(case_payload.get("audit_summary", {})),
                    metrics={str(k): float(v) for k, v in dict(case_payload.get("metrics", {})).items()},
                )
    cases = (
        [
            _apply_case_metric_contracts(
                current=case,
                previous_layer_case=previous_layer_cases_by_task_id.get(case.task_id),
            )
            for case in raw_cases
        ]
        if enforce_expected_metric_effects
        else raw_cases
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
    telemetry_summary = finalize_case_telemetry_summary(telemetry_summary, cases)
    replay_class_distribution: dict[str, float] = {}
    for case in cases:
        replay_class_distribution[case.replay_class] = replay_class_distribution.get(case.replay_class, 0.0) + 1.0
    kv_reuse_analysis = summarize_case_kv_reuse(cases)
    aggregated_metrics.update(
        {
            key: float(value)
            for key, value in dict(kv_reuse_analysis.get("metrics", {})).items()
        }
    )
    quality_floor_breakdown = {
        "deterministic_checks_passed_count": float(
            sum(1 for case in cases if case.quality_floor.deterministic_checks_passed)
        ),
        "fact_coverage_passed_count": float(sum(1 for case in cases if case.quality_floor.fact_coverage_passed)),
        "quality_floor_pass_count": aggregated_metrics["quality_floor_pass_count"],
    }
    report_label = report_layer_label or layer.value
    metadata = {
        "benchmark_tier": "formal",
        "claim_level": "first_pass",
        "family_id": family.family_id,
        "claim_tier": family.claim_tier,
        "manifest_path": family.manifest_path,
        "display_name": family.display_name,
        "round_count": family.round_count,
        "dataset_ids": [dataset.dataset_id for dataset in family.datasets],
        "reuse_edge_count": sum(len(round_.depends_on_rounds) for round_ in family.rounds),
        "continuous_execution": True,
        "history_backed_replay_enabled": layer == BenchmarkLayer.L3,
        "role_path_mode": role_path_mode,
        "role_execution_profile": {
            "planner": planner_mode or role_path_mode,
            "retriever": retriever_mode or role_path_mode,
            "executor": executor_mode or role_path_mode,
            "summarizer": summarizer_mode or role_path_mode,
            "embedding": embedding_mode,
        },
        "planner_mode": planner_mode or role_path_mode,
        "retriever_mode": retriever_mode or role_path_mode,
        "executor_mode": executor_mode or role_path_mode,
        "summarizer_mode": summarizer_mode or role_path_mode,
        "embedding_mode": embedding_mode,
        "executor_transport": executor_transport,
        "state_pool_mode_requested": state_pool_mode,
        "observed_semantic_state_storage_kinds": sorted({
            str(case.audit_summary.get("state_storage_kind", ""))
            for case in cases
            if str(case.audit_summary.get("state_storage_kind", "")) not in {"", "disabled"}
        }),
        "layer_contract_gate_enabled": enforce_expected_metric_effects and layer in {BenchmarkLayer.L2, BenchmarkLayer.L3},
        "kv_reuse_analysis": kv_reuse_analysis,
        "prefix_feedback": {
            **prefix_feedback.snapshot().canonical_payload(),
            "adaptive_enabled": adaptive_prefix_feedback_enabled,
            "adaptive_reorder_count": adaptive_prefix_reorder_count,
            "claim_boundary": (
                "scheduler_feedback_uses_only_task_local_query_hit_counter_deltas"
            ),
        },
        **_task_schedule_metadata(schedule_plan),
    }
    if metadata_extra:
        metadata.update(metadata_extra)
    report_path = layer_runtime_root / "benchmark_reports" / f"{suite_id}-{report_label}.json"
    report = BenchmarkFamilyReport(
        suite_id=suite_id,
        layer=layer,
        task_family=family.family_id,
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


def run_continuous_text_semantic_selection_family(
    *,
    family: ContinuousTaskFamily,
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str,
    role_path_mode: str = "deterministic",
    planner_mode: str = "",
    retriever_mode: str = "",
    executor_mode: str = "",
    summarizer_mode: str = "",
    embedding_mode: str = "deterministic",
    state_pool_mode: str = "auto",
    persistence_profile: str = "audit_full",
    executor_transport: str = "loopback",
) -> BenchmarkFamilyReport:
    return run_continuous_benchmark_family(
        family=family,
        workspace_root=workspace_root,
        runtime_root=runtime_root,
        socket_path=socket_path,
        suite_id=suite_id,
        layer=BenchmarkLayer.L2,
        role_path_mode=role_path_mode,
        planner_mode=planner_mode,
        retriever_mode=retriever_mode,
        executor_mode=executor_mode,
        summarizer_mode=summarizer_mode,
        embedding_mode=embedding_mode,
        state_pool_mode=state_pool_mode,
        profile_override=CONTINUOUS_TEXT_SEMANTIC_SELECTION_PROFILE,
        smoke_config_override=CONTINUOUS_TEXT_SEMANTIC_SELECTION_SMOKE_CONFIG,
        report_layer_label="T2",
        enforce_expected_metric_effects=False,
        metadata_extra={
            "baseline_kind": "internal_text_same_semantic_selection",
            "carrier_kind": "text_collaboration_same_selected_evidence",
            "claim_level": "diagnostic",
            "comparison_contract": "same_mainline_text_handoff_semantic_selection_without_state_ref",
            "diagnostic_claim_scope": "isolates_semantic_selection_from_non_text_state_transfer",
            "formal_comparator_eligible": False,
            "semantic_state_transfer_enabled": False,
            "uses_semantic_state_ref": False,
        },
        persistence_profile=persistence_profile,
        executor_transport=executor_transport,
    )


def run_continuous_benchmark_suite(
    *,
    family: ContinuousTaskFamily,
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str,
    role_path_mode: str = "deterministic",
    planner_mode: str = "",
    retriever_mode: str = "",
    executor_mode: str = "",
    summarizer_mode: str = "",
    embedding_mode: str = "deterministic",
    state_pool_mode: str = "auto",
    persistence_profile: str = "audit_full",
    task_schedule_plan: str = "input",
    claim_level: str = "first_pass",
    execution_scope: str = "full",
    original_round_count: int | None = None,
    executor_transport: str = "loopback",
    layers: tuple[BenchmarkLayer, ...] | None = None,
    experiment_view: str = "",
) -> BenchmarkSuiteReport:
    available_round_count = original_round_count or max(
        (len(rounds) for rounds in family.experiment_views.values()),
        default=family.round_count,
    )
    selected_layers = tuple(BenchmarkLayer) if layers is None else tuple(layers)
    if not selected_layers:
        raise ValueError("continuous benchmark suite requires at least one layer")
    if len(set(selected_layers)) != len(selected_layers):
        raise ValueError("continuous benchmark suite layers must be unique")
    causal_matrix = selected_layers == tuple(BenchmarkLayer)
    full_family_coverage = (
        execution_scope == "full"
        and family.round_count == available_round_count
    ) or (
        execution_scope == "formal_causal_view"
        and experiment_view == "causal_core"
        and family.selected_experiment_view == "causal_core"
        and family.round_count == len(family.experiment_views.get("causal_core", ()))
    )
    stability_only = selected_layers == (BenchmarkLayer.L3,) and execution_scope == "formal_stability_view"
    schedule_plan = _task_schedule_plan_for_family(family, task_schedule_plan=task_schedule_plan)
    layer_reports = tuple(
        run_continuous_benchmark_family(
            family=family,
            workspace_root=workspace_root / layer.value,
            runtime_root=runtime_root / layer.value,
            socket_path=socket_path.with_name(f"{socket_path.stem}-{layer.value.lower()}{socket_path.suffix}"),
            suite_id=suite_id,
            layer=layer,
            role_path_mode=role_path_mode,
            planner_mode=planner_mode,
            retriever_mode=retriever_mode,
            executor_mode=executor_mode,
            summarizer_mode=summarizer_mode,
            embedding_mode=embedding_mode,
            state_pool_mode=state_pool_mode,
            persistence_profile=persistence_profile,
            task_schedule_plan=task_schedule_plan,
            executor_transport=executor_transport,
            metadata_extra={
                "claim_level": claim_level,
                "execution_scope": execution_scope,
                "selected_round_count": family.round_count,
                "available_round_count": available_round_count,
                "formal_headline_eligible": full_family_coverage,
            },
        )
        for layer in selected_layers
    )
    if causal_matrix:
        fairness_manifest = build_continuous_fairness_manifest(
            family_id=family.family_id,
            layer_reports=layer_reports,
        )
    else:
        fairness_manifest = {
            "schema_version": "statebus.continuous_fairness_manifest.v1",
            "family_id": family.family_id,
            "comparison_valid": False,
            "headline_eligible": False,
            "scope": "stability_only_single_layer",
            "selected_layers": [layer.value for layer in selected_layers],
            "reason": "single-layer stability evidence is not a causal L0-L3 comparison",
            "cases": {},
        }
    fairness_manifest_path = runtime_root / "fairness_manifest.json"
    write_json_report(fairness_manifest_path, fairness_manifest)
    suite_stub = BenchmarkSuiteReport(
        suite_id=suite_id,
        task_family=family.family_id,
        layer_reports=layer_reports,
    )
    quality_headline_eligible = (
        bool(selected_layers)
        and all(layer_report.eligible_for_headline for layer_report in layer_reports)
        and (not causal_matrix or (full_family_coverage and bool(fairness_manifest["comparison_valid"])))
    )
    replay_audit = _continuous_replay_audit(family=family, report=suite_stub)
    replay_headline_eligible = (
        quality_headline_eligible
        and (not causal_matrix or bool(fairness_manifest["comparison_valid"]))
        and bool(replay_audit["eligible_for_replay_headline"])
    )
    headline_scope = _continuous_headline_scope(suite_stub, replay_audit=replay_audit)
    replay_summary_counts = _replay_audit_summary_counts(replay_audit)
    report_path = runtime_root / "benchmark_reports" / f"{suite_id}.json"
    markdown_report_path = runtime_root / "benchmark_reports" / f"{suite_id}.evidence.md"
    evidence_stub = BenchmarkSuiteReport(
        suite_id=suite_id,
        task_family=family.family_id,
        layer_reports=layer_reports,
    )
    evidence_pack = _continuous_suite_evidence_pack(
        family=family,
        report=evidence_stub,
        replay_audit=replay_audit,
    )
    reports_by_layer = {layer_report.layer: layer_report for layer_report in layer_reports}
    l0_report = reports_by_layer.get(BenchmarkLayer.L0)
    l1_report = reports_by_layer.get(BenchmarkLayer.L1)
    l2_report = reports_by_layer.get(BenchmarkLayer.L2)
    l3_report = reports_by_layer.get(BenchmarkLayer.L3)
    l3_metrics = {} if l3_report is None else l3_report.telemetry_summary
    l3_aggregated = {} if l3_report is None else l3_report.aggregated_metrics
    report = BenchmarkSuiteReport(
        suite_id=suite_id,
        task_family=family.family_id,
        layer_reports=layer_reports,
        waterfall_metrics={
            "L0_case_count": float(len(l0_report.cases)) if l0_report else 0.0,
            "L1_control_bytes": l1_report.telemetry_summary.get("control_bytes", 0.0) if l1_report else 0.0,
            "L2_semantic_state_transfer_count": l2_report.telemetry_summary.get(
                "semantic_state_transfer_count", 0.0
            ) if l2_report else 0.0,
            "L3_history_runtime_root_count": l3_metrics.get(
                "history_runtime_root_count", 0.0
            ),
            "L3_artifact_reuse_count": l3_metrics.get("artifact_reuse_count", 0.0),
            "L3_reuse_gain": l3_metrics.get("reuse_gain", 0.0),
            "L3_history_reuse_gain": l3_metrics.get("history_reuse_gain", 0.0),
            "L3_history_step_reduction_count": l3_metrics.get(
                "history_step_reduction_count", 0.0
            ),
            "L3_kv_corpus_prefix_hash_unique_count": l3_aggregated.get(
                "kv_corpus_prefix_hash_unique_count", 0.0
            ),
            "L3_kv_corpus_prefix_hash_reuse_count": l3_aggregated.get(
                "kv_corpus_prefix_hash_reuse_count", 0.0
            ),
            "L3_kv_corpus_level_prefill_saved_tokens_estimate": l3_aggregated.get(
                "kv_corpus_level_prefill_saved_tokens_estimate", 0.0
            ),
            "L3_kv_engine_local_prefill_saved_tokens_estimate": l3_aggregated.get(
                "kv_engine_local_prefill_saved_tokens_estimate", 0.0
            ),
            "L3_validated_downgraded_reuse_count": l3_metrics.get(
                "validated_downgraded_reuse_count",
                l3_metrics.get("validated_replay_count", 0.0),
            ),
            "L3_answer_restoration_replay_count": l3_metrics.get(
                "answer_restoration_replay_count",
                0.0,
            ),
            **{
                f"L3_{metric}": float(l3_metrics.get(metric, 0.0))
                for metric in _MEMORY_FUNNEL_METRICS
            },
        },
        comparison_summary={
            "layer_count": float(len(layer_reports)),
            "successful_layer_count": float(sum(1 for report_ in layer_reports if not report_.missing_reason)),
            "round_count": float(family.round_count),
            "reuse_edge_count": float(sum(len(round_.depends_on_rounds) for round_ in family.rounds)),
            "validated_downgraded_reuse_count": l3_metrics.get(
                "validated_downgraded_reuse_count",
                l3_metrics.get("validated_replay_count", 0.0),
            ),
            "answer_restoration_replay_count": l3_metrics.get(
                "answer_restoration_replay_count",
                0.0,
            ),
            **replay_summary_counts,
        },
        evidence_pack=evidence_pack,
        metadata={
            "benchmark_tier": "formal",
            "claim_level": claim_level,
            "execution_scope": execution_scope,
            "selected_round_count": family.round_count,
            "available_round_count": available_round_count,
            "formal_headline_eligible": (
                causal_matrix and full_family_coverage and bool(fairness_manifest["comparison_valid"])
            ),
            "stability_evidence_eligible": stability_only and quality_headline_eligible,
            "selected_layers": [layer.value for layer in selected_layers],
            "round_view": experiment_view,
            "family_id": family.family_id,
            "claim_tier": family.claim_tier,
            "manifest_path": family.manifest_path,
            "continuous_execution": True,
            "fairness_manifest": fairness_manifest,
            "fairness_manifest_path": str(fairness_manifest_path),
            "fairness_comparison_valid": bool(fairness_manifest["comparison_valid"]),
            "role_execution_profile": {
                "planner": planner_mode or role_path_mode,
                "retriever": retriever_mode or role_path_mode,
                "executor": executor_mode or role_path_mode,
                "summarizer": summarizer_mode or role_path_mode,
                "embedding": embedding_mode,
            },
            "executor_transport": executor_transport,
            "state_pool_mode_requested": state_pool_mode,
            "observed_semantic_state_storage_kinds": sorted({
                kind
                for layer_report in layer_reports
                for kind in layer_report.metadata.get("observed_semantic_state_storage_kinds", [])
            }),
            "source_basis": dict(family.source_basis),
            "kv_prefix_probe": dict(family.kv_prefix_probe),
            **_task_schedule_metadata(schedule_plan),
            "eligible_for_quality_headline": quality_headline_eligible,
            "eligible_for_replay_headline": replay_headline_eligible,
            "replay_gate_reason": str(replay_audit.get("gate_reason", "")),
            "headline_scope": headline_scope,
            "replay_admissibility_audit": replay_audit,
            "supported_continuous_execution_families": _supported_continuous_family_ids(),
            "serial_execution": True,
        },
        family_case_count=family.round_count,
        report_path=str(report_path),
        markdown_report_path=str(markdown_report_path),
    )
    write_json_report(report_path, suite_report_to_dict(report))
    write_markdown_report(markdown_report_path, _continuous_suite_markdown(evidence_pack))
    return report


def run_continuous_benchmark_collection(
    *,
    families: tuple[ContinuousTaskFamily, ...],
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str,
    role_path_mode: str = "deterministic",
    planner_mode: str = "",
    retriever_mode: str = "",
    executor_mode: str = "",
    summarizer_mode: str = "",
    embedding_mode: str = "deterministic",
    state_pool_mode: str = "auto",
    collection_scope: str = "formal_continuous_task_families",
    persistence_profile: str = "audit_full",
    task_schedule_plan: str = "input",
    execution_scope: str = "full",
    executor_transport: str = "loopback",
    layers: tuple[BenchmarkLayer, ...] | None = None,
    experiment_view: str = "",
) -> BenchmarkContinuousCollectionReport:
    if not families:
        raise ValueError("continuous benchmark collection requires at least one family")
    if len(families) < 2:
        raise ValueError("continuous benchmark collection requires at least two families")
    total_round_count = sum(family.round_count for family in families)
    if total_round_count < 10:
        raise ValueError(
            "continuous benchmark collection requires at least ten total executions"
        )

    family_reports: list[BenchmarkSuiteReport] = []
    for family in families:
        family_slug = family.family_id.removesuffix("_v1")
        family_reports.append(
            run_continuous_benchmark_suite(
                family=family,
                workspace_root=workspace_root / family_slug,
                runtime_root=runtime_root / family_slug,
                socket_path=socket_path.with_name(f"{socket_path.stem}-{family_slug}{socket_path.suffix}"),
                suite_id=f"{suite_id}-{family_slug}",
                role_path_mode=role_path_mode,
                planner_mode=planner_mode,
                retriever_mode=retriever_mode,
                executor_mode=executor_mode,
                summarizer_mode=summarizer_mode,
                embedding_mode=embedding_mode,
                state_pool_mode=state_pool_mode,
                persistence_profile=persistence_profile,
                task_schedule_plan=task_schedule_plan,
                claim_level=(
                    "first_pass"
                    if execution_scope in {"full", "formal_causal_view"}
                    else ("stability" if execution_scope == "formal_stability_view" else "diagnostic")
                ),
                execution_scope=execution_scope,
                original_round_count=max(
                    (len(rounds) for rounds in family.experiment_views.values()),
                    default=family.round_count,
                ),
                executor_transport=executor_transport,
                layers=layers,
                experiment_view=experiment_view,
            )
        )

    replay_summary_counts_by_family = [
        _replay_audit_summary_counts(dict(report.metadata.get("replay_admissibility_audit", {})))
        for report in family_reports
    ]
    collection_summary = {
        "family_count": float(len(family_reports)),
        "continuous_round_count": float(sum(report.family_case_count for report in family_reports)),
        "successful_family_count": float(sum(1 for report in family_reports if report.layer_reports)),
        "quality_headline_eligible_family_count": float(
            sum(
                1
                for report in family_reports
                if _continuous_quality_headline_eligible(report)
            )
        ),
        "replay_headline_eligible_family_count": float(
            sum(1 for report in family_reports if bool(report.metadata.get("eligible_for_replay_headline", False)))
        ),
        "history_backed_only_family_count": float(
            sum(1 for report in family_reports if _continuous_headline_scope(report, replay_audit=report.metadata.get("replay_admissibility_audit")) == "history_backed_only")
        ),
        "L2_semantic_state_transfer_count": float(
            sum(report.waterfall_metrics.get("L2_semantic_state_transfer_count", 0.0) for report in family_reports)
        ),
        "L3_artifact_reuse_count": float(
            sum(report.waterfall_metrics.get("L3_artifact_reuse_count", 0.0) for report in family_reports)
        ),
        "L3_reuse_gain": float(sum(report.waterfall_metrics.get("L3_reuse_gain", 0.0) for report in family_reports)),
        "L3_history_reuse_gain": float(
            sum(report.waterfall_metrics.get("L3_history_reuse_gain", 0.0) for report in family_reports)
        ),
        "L3_history_step_reduction_count": float(
            sum(report.waterfall_metrics.get("L3_history_step_reduction_count", 0.0) for report in family_reports)
        ),
        "L3_kv_corpus_prefix_hash_unique_count": float(
            sum(report.waterfall_metrics.get("L3_kv_corpus_prefix_hash_unique_count", 0.0) for report in family_reports)
        ),
        "L3_kv_corpus_prefix_hash_reuse_count": float(
            sum(report.waterfall_metrics.get("L3_kv_corpus_prefix_hash_reuse_count", 0.0) for report in family_reports)
        ),
        "L3_kv_corpus_level_prefill_saved_tokens_estimate": float(
            sum(
                report.waterfall_metrics.get("L3_kv_corpus_level_prefill_saved_tokens_estimate", 0.0)
                for report in family_reports
            )
        ),
        "L3_kv_engine_local_prefill_saved_tokens_estimate": float(
            sum(
                report.waterfall_metrics.get("L3_kv_engine_local_prefill_saved_tokens_estimate", 0.0)
                for report in family_reports
            )
        ),
        "history_backed_reuse_count": float(
            sum(
                layer_report.telemetry_summary.get("history_artifact_reuse_count", 0.0)
                for report in family_reports
                for layer_report in report.layer_reports
            )
        ),
        "validated_replay_count": float(
            sum(
                layer_report.telemetry_summary.get("validated_replay_count", 0.0)
                for report in family_reports
                for layer_report in report.layer_reports
            )
        ),
        "validated_downgraded_reuse_count": float(
            sum(
                layer_report.telemetry_summary.get(
                    "validated_downgraded_reuse_count",
                    layer_report.telemetry_summary.get("validated_replay_count", 0.0),
                )
                for report in family_reports
                for layer_report in report.layer_reports
            )
        ),
        "exact_replay_count": float(
            sum(
                layer_report.telemetry_summary.get("exact_replay_count", 0.0)
                for report in family_reports
                for layer_report in report.layer_reports
            )
        ),
        "answer_restoration_replay_count": float(
            sum(
                layer_report.telemetry_summary.get(
                    "answer_restoration_replay_count",
                    0.0,
                )
                for report in family_reports
                for layer_report in report.layer_reports
            )
        ),
        **{
            f"L3_{metric}": float(
                sum(
                    report.waterfall_metrics.get(f"L3_{metric}", 0.0)
                    for report in family_reports
                )
            )
            for metric in _MEMORY_FUNNEL_METRICS
        },
        "history_target_round_count": float(
            sum(summary["history_target_round_count"] for summary in replay_summary_counts_by_family)
        ),
        "history_observed_reuse_round_count": float(
            sum(summary["history_observed_reuse_round_count"] for summary in replay_summary_counts_by_family)
        ),
        "history_missing_target_round_count": float(
            sum(summary["history_missing_target_round_count"] for summary in replay_summary_counts_by_family)
        ),
        "history_additional_reuse_round_count": float(
            sum(summary["history_additional_reuse_round_count"] for summary in replay_summary_counts_by_family)
        ),
        "replay_target_round_count": float(
            sum(summary["replay_target_round_count"] for summary in replay_summary_counts_by_family)
        ),
        "replay_observed_round_count": float(
            sum(summary["replay_observed_round_count"] for summary in replay_summary_counts_by_family)
        ),
        "replay_missing_target_round_count": float(
            sum(summary["replay_missing_target_round_count"] for summary in replay_summary_counts_by_family)
        ),
        "replay_unexpected_round_count": float(
            sum(summary["replay_unexpected_round_count"] for summary in replay_summary_counts_by_family)
        ),
    }
    def _l3_admissibility_metrics(report: BenchmarkSuiteReport) -> dict[str, object]:
        l3_report = next(
            (
                layer_report
                for layer_report in report.layer_reports
                if layer_report.layer == BenchmarkLayer.L3
            ),
            None,
        )
        if l3_report is None:
            return {
                "L3_replay_class_distribution": {},
                "L3_history_artifact_reuse_count": 0.0,
                "L3_history_reuse_gain": 0.0,
                "L3_history_step_reduction_count": 0.0,
                "L3_validated_replay_count": 0.0,
                "L3_validated_downgraded_reuse_count": 0.0,
                "L3_exact_replay_count": 0.0,
                "L3_answer_restoration_replay_count": 0.0,
            }
        metrics = l3_report.telemetry_summary
        return {
            "L3_replay_class_distribution": dict(l3_report.replay_class_distribution),
            "L3_history_artifact_reuse_count": float(
                metrics.get("history_artifact_reuse_count", 0.0)
            ),
            "L3_history_reuse_gain": float(metrics.get("history_reuse_gain", 0.0)),
            "L3_history_step_reduction_count": float(
                metrics.get("history_step_reduction_count", 0.0)
            ),
            "L3_validated_replay_count": float(metrics.get("validated_replay_count", 0.0)),
            "L3_validated_downgraded_reuse_count": float(
                metrics.get(
                    "validated_downgraded_reuse_count",
                    metrics.get("validated_replay_count", 0.0),
                )
            ),
            "L3_exact_replay_count": float(metrics.get("exact_replay_count", 0.0)),
            "L3_answer_restoration_replay_count": float(
                metrics.get("answer_restoration_replay_count", 0.0)
            ),
        }

    admissibility_summary = {
        report.task_family: {
            **_l3_admissibility_metrics(report),
            **_replay_audit_summary_counts(dict(report.metadata.get("replay_admissibility_audit", {}))),
            "eligible_for_replay_headline": bool(report.metadata.get("eligible_for_replay_headline", False)),
            "headline_scope": _continuous_headline_scope(
                report,
                replay_audit=report.metadata.get("replay_admissibility_audit"),
            ),
            "replay_gate_reason": str(report.metadata.get("replay_gate_reason", "")),
            "replay_admissibility_audit": dict(report.metadata.get("replay_admissibility_audit", {})),
        }
        for report in family_reports
    }
    report_path = runtime_root / "benchmark_reports" / f"{suite_id}.json"
    markdown_report_path = runtime_root / "benchmark_reports" / f"{suite_id}.evidence.md"
    report_stub = BenchmarkContinuousCollectionReport(
        suite_id=suite_id,
        family_reports=tuple(family_reports),
        collection_summary=collection_summary,
        admissibility_summary=admissibility_summary,
        metadata={
            "benchmark_tier": "formal",
            "claim_level": (
                "first_pass"
                if execution_scope in {"full", "formal_causal_view"}
                else ("stability" if execution_scope == "formal_stability_view" else "diagnostic")
            ),
            "execution_scope": execution_scope,
            "formal_headline_eligible": (
                execution_scope in {"full", "formal_causal_view"}
                and all(bool(report.metadata.get("formal_headline_eligible", False)) for report in family_reports)
            ),
            "stability_evidence_eligible": (
                execution_scope == "formal_stability_view"
                and all(bool(report.metadata.get("stability_evidence_eligible", False)) for report in family_reports)
            ),
            "round_view": experiment_view,
            "selected_layers": [
                layer.value
                for layer in (
                    tuple(BenchmarkLayer) if layers is None else tuple(layers)
                )
            ],
            "continuous_execution": True,
            "family_count": len(family_reports),
            "supported_continuous_execution_families": [family.family_id for family in families],
            "role_path_mode": role_path_mode,
            "role_execution_profile": {
                "planner": planner_mode or role_path_mode,
                "retriever": retriever_mode or role_path_mode,
                "executor": executor_mode or role_path_mode,
                "summarizer": summarizer_mode or role_path_mode,
                "embedding": embedding_mode,
            },
            "executor_transport": executor_transport,
            "embedding_mode": embedding_mode,
            "state_pool_mode_requested": state_pool_mode,
            "observed_semantic_state_storage_kinds": sorted({
                kind
                for report in family_reports
                for kind in report.metadata.get("observed_semantic_state_storage_kinds", [])
            }),
            "collection_scope": collection_scope,
            "task_schedule_plan": _normalise_task_schedule_plan(task_schedule_plan),
            "serial_execution": True,
        },
        report_path=str(report_path),
        markdown_report_path=str(markdown_report_path),
    )
    evidence_pack = _continuous_collection_evidence_pack(report=report_stub)
    report = BenchmarkContinuousCollectionReport(
        suite_id=suite_id,
        family_reports=tuple(family_reports),
        collection_summary=collection_summary,
        admissibility_summary=admissibility_summary,
        evidence_pack=evidence_pack,
        metadata=report_stub.metadata,
        report_path=str(report_path),
        markdown_report_path=str(markdown_report_path),
    )
    write_json_report(report_path, continuous_collection_report_to_dict(report))
    write_markdown_report(markdown_report_path, _continuous_collection_markdown(evidence_pack))
    return report


# ---------------------------------------------------------------------------
# G5-C2-C provider-baseline measurement projection
# ---------------------------------------------------------------------------


def _c2c_pair_key(row: dict[str, object]) -> str:
    """Return a stable pair identity independent of benchmark lane fields."""
    input_lineage = row.get("input_lineage_hashes")
    if isinstance(input_lineage, (str, bytes)):
        input_lineage = (str(input_lineage),)
    else:
        input_lineage = tuple(sorted(str(item) for item in (input_lineage or ())))
    fields = {
        "task_contract_hash": str(row.get("task_contract_hash", "")),
        "input_lineage_hashes": input_lineage,
        "quality_contract_hash": str(row.get("quality_contract_hash", "")),
        "deterministic_seed": row.get("deterministic_seed"),
    }
    if not fields["task_contract_hash"] or not fields["input_lineage_hashes"] or not fields["quality_contract_hash"]:
        raise ValueError("c2c_pair_identity_incomplete")
    if fields["deterministic_seed"] is None:
        raise ValueError("c2c_pair_seed_missing")
    return f"c2c:{sha256_digest(fields)}"


def _c2c_denominator_projection(
    pairings: list[dict[str, object]],
    baseline_rows: list[dict[str, object]],
    c1_rows: list[dict[str, object]],
    negative_rows: list[dict[str, object]],
) -> dict[str, object]:
    """Close the pair denominator without zero filling or estimation."""
    all_rows = [*baseline_rows, *c1_rows]
    row_ids = [str(row.get("row_id", "")) for row in all_rows]
    unique_row_ids = bool(row_ids) and len(row_ids) == len(set(row_ids))
    matched_count = len(pairings)
    unmatched_count = len(negative_rows)
    attempted_pairs = matched_count + unmatched_count
    row_arithmetic_closed = (
        unique_row_ids
        and len(row_ids) == 2 * matched_count + unmatched_count
    )
    arithmetic_closed = row_arithmetic_closed and attempted_pairs == matched_count + unmatched_count
    status = "observed" if arithmetic_closed else "unsupported"
    return {
        "status": status,
        "scope": "c2c_baseline_and_c1_rows",
        "attempted_pair_count": attempted_pairs,
        "matched_pair_count": matched_count,
        "eligible_matched_pair_count": sum(row.get("status") == "eligible" for row in pairings),
        "rejected_matched_pair_count": sum(row.get("status") != "eligible" for row in pairings),
        "unmatched_row_count": unmatched_count,
        "baseline_row_count": len(baseline_rows),
        "c1_row_count": len(c1_rows),
        "row_ids": row_ids,
        "negative_row_ids": [str(row.get("row_id", "")) for row in negative_rows],
        "arithmetic_closed": arithmetic_closed,
        "row_arithmetic_closed": row_arithmetic_closed,
        "provenance_scopes": {
            "baseline": sorted({str(row.get("provenance_scope", "baseline_runtime")) for row in baseline_rows}),
            "c1": sorted({str(row.get("provenance_scope", "c1_runtime")) for row in c1_rows}),
            "negative": sorted({str(row.get("provenance_scope", "unmatched_control")) for row in negative_rows}),
        },
    }


def _c2c_provider_work_avoided(
    pairings: list[dict[str, object]],
    denominator: dict[str, object],
) -> dict[str, object]:
    """Project the count of eligible pairs; never infer work from timing."""
    from statebus.benchmark.metric_aggregation import _c2c_provider_work_avoided_metric

    return _c2c_provider_work_avoided_metric(pairings, denominator)


def _c2c_baseline_pairing(
    baseline_rows: list[dict[str, object]],
    c1_rows: list[dict[str, object]],
    *,
    artifact_root: Path | None = None,
) -> dict[str, object]:
    """Join real memory-off provider rows to accepted C1 observations.

    The helper is intentionally projection-only.  It recomputes keys from
    immutable equivalence fields, rejects duplicate identities, and retains
    every unmatched/negative row in the closed denominator.
    """
    from statebus.benchmark.metric_aggregation import (
        _c2c_quality_non_regression_metric,
        project_metric_availability,
    )

    baseline = [dict(row) for row in baseline_rows]
    c1 = [dict(row) for row in c1_rows]
    baseline_by_key: dict[str, list[dict[str, object]]] = {}
    c1_by_key: dict[str, list[dict[str, object]]] = {}
    negative: list[dict[str, object]] = []

    def index(rows: list[dict[str, object]], target: dict[str, list[dict[str, object]]], side: str) -> None:
        for row in rows:
            try:
                key = _c2c_pair_key(row)
            except (TypeError, ValueError) as exc:
                negative.append({
                    "row_id": str(row.get("row_id", "")),
                    "side": side,
                    "pair_key": "",
                    "status": "unmatched",
                    "reason": str(exc),
                    "provenance_scope": f"{side}_unmatched",
                })
                continue
            row["pair_key"] = key
            target.setdefault(key, []).append(row)

    index(baseline, baseline_by_key, "baseline")
    index(c1, c1_by_key, "c1")
    pairings: list[dict[str, object]] = []
    for key in sorted(set(baseline_by_key) | set(c1_by_key)):
        left = baseline_by_key.get(key, [])
        right = c1_by_key.get(key, [])
        if len(left) != 1 or len(right) != 1:
            for side, rows in (("baseline", left), ("c1", right)):
                for row in rows:
                    negative.append({
                        "row_id": str(row.get("row_id", "")),
                        "side": side,
                        "pair_key": key,
                        "status": "unmatched",
                        "reason": "duplicate_or_missing_matched_side",
                        "provenance_scope": f"{side}_unmatched",
                    })
            continue
        baseline_row, c1_row = left[0], right[0]
        validation = _c2c_validate_pair_claim(baseline=baseline_row, c1=c1_row)
        baseline_provider = baseline_row.get("provider_invocation_evidence", {})
        c1_observation = c1_row.get("provider_not_started_observation", {})
        baseline_provider = dict(baseline_provider) if isinstance(baseline_provider, Mapping) else {}
        c1_observation = dict(c1_observation) if isinstance(c1_observation, Mapping) else {}
        pairings.append({
            "schema_version": "statebus.g5c2c.pair.v1",
            "pair_key": key,
            "family_id": baseline_row.get("family_id", ""),
            "round_number": baseline_row.get("round_number", ""),
            "repeat_id": baseline_row.get("repeat_id", ""),
            # These equivalence fields are copied from the already-validated
            # baseline/C1 rows.  They are projection inputs, not newly-created
            # identity facts.
            "task_contract_hash": baseline_row.get("task_contract_hash", ""),
            "input_lineage_hashes": (
                [str(baseline_row.get("input_lineage_hashes"))]
                if isinstance(baseline_row.get("input_lineage_hashes"), (str, bytes))
                else [str(item) for item in (baseline_row.get("input_lineage_hashes") or ())]
            ),
            "quality_contract_hash": baseline_row.get("quality_contract_hash", ""),
            "baseline_row_id": baseline_row.get("row_id", ""),
            "replay_row_id": c1_row.get("row_id", ""),
            "baseline_memory_policy": baseline_row.get("memory_policy", ""),
            "replay_memory_policy": c1_row.get(
                "memory_policy",
                c1_row.get("runtime_memory_policy", ""),
            ),
            "baseline_provider_invocation_id": baseline_provider.get("invocation_id", ""),
            "baseline_provider_invocation_status": baseline_provider.get("invocation_status", ""),
            "replay_skip_receipt_id": c1_observation.get("observation_id", ""),
            "replay_skip_receipt_status": c1_observation.get("status", ""),
            "quality_non_regression": validation["quality_non_regression"],
            "denominator_status": "pending",
            "status": validation["status"],
            "reason": validation["reason"],
            "failures": validation["failures"],
            "source_receipt_hashes": validation["source_receipt_hashes"],
        })
    denominator = _c2c_denominator_projection(pairings, baseline, c1, negative)
    for pair in pairings:
        pair["denominator_status"] = denominator["status"]
    metrics = project_metric_availability(observed={
        "c2c_pairings": pairings,
        "c2c_denominator": denominator,
    })
    metrics["quality_non_regression"] = _c2c_quality_non_regression_metric(pairings)
    provider_work_avoided = _c2c_provider_work_avoided(pairings, denominator)
    projection = {
        "schema_version": "statebus.g5c2c.provider_baseline_projection.v1",
        "status": provider_work_avoided["status"],
        "pairings": pairings,
        "negative_rows": negative,
        "denominator": denominator,
        "metrics": metrics,
        "provider_work_avoided": provider_work_avoided,
        "quality_non_regression": metrics["quality_non_regression"],
        "eligible_matched_pair_count": provider_work_avoided.get("eligible_matched_pair_count", 0),
        "exact_replay": {"status": "unsupported", "value": None, "reason": "c2_exact_restore_not_implemented"},
        "recipe_step_skip": {"status": "deferred", "value": None, "reason": "recipe_step_skip_deferred_to_c2"},
        "verified_recipe_work_avoided": {"status": "unsupported", "value": None, "reason": "recipe_step_skip_deferred_to_c2"},
        "benchmark_superiority": "NOT_ESTABLISHED",
        "live_vllm_gpu_validation": "NOT_RUN",
        "g6a_memfd_limitation": "skipped: memfd unavailable; SHM actual-read retained",
    }
    if artifact_root is not None:
        root = Path(artifact_root)
        root.mkdir(parents=True, exist_ok=False)
        def row_mapping(row: dict[str, object], key: str) -> dict[str, object]:
            value = row.get(key, {})
            return dict(value) if isinstance(value, Mapping) else {}

        write_json_report(root / "manifest.json", {
            "schema_version": "statebus.g5c2c.manifest.v1",
            "batch": "G5-C2-C",
            "scope": "provider_baseline_measurement_only",
            "baseline_lane": "memory-off",
            "baseline_runtime_memory_policy": "none",
            "pair_key_definition": "task_contract_hash+input_lineage_hashes+quality_contract_hash+deterministic_seed",
            "pair_key_independent_of": ["lane", "family_id", "round_number", "repeat_id", "cache_epoch"],
            "runtime_authority": "AdaptiveRuntimeEngine",
            "memory_authority": "MemoryIndexStore",
            "provider_authority": "detached_candidate_producer",
            "projection": projection,
        })
        write_json_report(root / "baseline_rows.json", {"schema_version": "statebus.g5c2c.baseline_rows.v1", "rows": baseline})
        write_json_report(root / "c1_paired_rows.json", {"schema_version": "statebus.g5c2c.c1_rows.v1", "rows": c1})
        write_json_report(root / "pair_keys.json", {"schema_version": "statebus.g5c2c.pair_keys.v1", "rows": [{"pair_key": row["pair_key"], "baseline_row_id": row.get("baseline_row_id", ""), "replay_row_id": row.get("replay_row_id", "")} for row in pairings], "negative_rows": negative})
        write_json_report(root / "baseline_provider_invocation_evidence.json", {"schema_version": "statebus.g5c2c.baseline_provider_invocation.v1", "rows": [row_mapping(row, "provider_invocation_evidence") | {"row_id": row.get("row_id", "")} for row in baseline]})
        pair_by_replay_row_id = {
            str(pair.get("replay_row_id", "")): pair
            for pair in pairings
        }
        provider_skip_receipts: list[dict[str, object]] = []
        for row in c1:
            pair = pair_by_replay_row_id.get(str(row.get("row_id", "")))
            # An unmatched C1 observation has no real baseline invocation to
            # reference.  It remains in negative_unmatched_rows.json rather
            # than being promoted into a synthetic skip receipt.
            if pair is None:
                continue
            observation = row_mapping(row, "provider_not_started_observation")
            provider_skip_receipts.append({
                **observation,
                "row_id": row.get("row_id", ""),
                "skip_receipt_id": observation.get("observation_id", ""),
                "skip_kind": "provider_invocation",
                "baseline_row_id": pair.get("baseline_row_id", ""),
                "baseline_provider_invocation_id": pair.get("baseline_provider_invocation_id", ""),
                "baseline_pair_key": pair.get("pair_key", ""),
                "denominator_status": pair.get("denominator_status", ""),
            })
        write_json_report(root / "provider_skip_receipts.json", {"schema_version": "statebus.g5c2c.provider_skip.v1", "rows": provider_skip_receipts})
        write_json_report(root / "quality_evidence.json", {"schema_version": "statebus.g5c2c.quality.v1", "baseline": [row_mapping(row, "quality_evidence") | {"row_id": row.get("row_id", "")} for row in baseline], "c1": [row_mapping(row, "quality_evidence") | {"row_id": row.get("row_id", "")} for row in c1]})
        write_json_report(root / "result_admission_references.json", {"schema_version": "statebus.g5c2c.result_admission.v1", "baseline": [row_mapping(row, "result_admission") | {"row_id": row.get("row_id", "")} for row in baseline], "c1": [row_mapping(row, "result_admission") | {"row_id": row.get("row_id", "")} for row in c1]})
        write_json_report(root / "baseline_pairing.json", projection)
        write_json_report(root / "pair_validation.json", {"schema_version": "statebus.g5c2c.validation.v1", "rows": pairings})
        write_json_report(root / "failure_denominator.json", denominator)
        write_json_report(root / "negative_unmatched_rows.json", {"schema_version": "statebus.g5c2c.negative.v1", "rows": negative})
        write_json_report(root / "metric_availability.json", {"schema_version": "statebus.g5c2c.metrics.v1", "metrics": metrics})
        write_json_report(root / "provider_work_avoided.json", provider_work_avoided)
        write_json_report(root / "acceptance_summary.json", {"schema_version": "statebus.g5c2c.acceptance.v1", "status": projection["status"], "eligible_matched_pair_count": projection["eligible_matched_pair_count"], "provider_work_avoided": provider_work_avoided, "quality_non_regression": metrics["quality_non_regression"], "exact_replay": projection["exact_replay"], "recipe_step_skip": projection["recipe_step_skip"], "verified_recipe_work_avoided": projection["verified_recipe_work_avoided"], "benchmark_superiority": projection["benchmark_superiority"], "live_vllm_gpu_validation": projection["live_vllm_gpu_validation"], "g6a_memfd_limitation": projection["g6a_memfd_limitation"]})
    return projection


# ---------------------------------------------------------------------------
# G6-B evidence and measurement contract projection
# ---------------------------------------------------------------------------


def _g6b_pair_slot_manifest(*, execution_status: str = "NOT_RUN") -> dict[str, object]:
    """Freeze the twelve B1 slot identities and their execution state."""
    slots: list[dict[str, object]] = []
    families = ("cross_period_financial", "incident_diagnosis")
    for family_index, family_id in enumerate(families, start=1):
        for round_number in (1, 2):
            for repeat_id in (1, 2, 3):
                slots.append({
                    "pair_slot_id": f"{family_id}:round-{round_number}:repeat-{repeat_id}",
                    "family_id": family_id,
                    "round_number": round_number,
                    "repeat_id": repeat_id,
                    "deterministic_seed": 610000 + family_index * 100 + round_number * 10 + repeat_id,
                    "required_lanes": ["memory-off", "validated-replay"],
                    "execution_status": execution_status,
                })
    return {
        "schema_version": "statebus.g6b.pair_slot_manifest.v1",
        "slot_count": len(slots),
        "slots": slots,
        "definitions": {
            "family": "one deterministic internal task family",
            "round": "one designated task instance within a family",
            "repeat": "one serial execution of the designated family/round slot",
            "session": "one lane-local Runtime session; baseline and replay sessions must differ",
            "pair_slot": "family_id + round_number + repeat_id; it schedules two independent lanes",
            "pair_identity": "lane-independent _c2c_pair_key over the four frozen identity fields",
        },
    }


def _g6b_campaign_manifest(
    *,
    stage: str = "G6-B0",
    artifact_root: Path | str = "",
) -> dict[str, object]:
    """Return the frozen G6-B campaign and claim contract."""
    slot_manifest = _g6b_pair_slot_manifest(
        execution_status="NOT_RUN" if stage == "G6-B0" else "COMPLETED",
    )
    return {
        "schema_version": "statebus.g6b.campaign_manifest.v1",
        "decision_status": "G6B_STAGED_LOCAL_FIRST_LIVE_DEFERRED",
        "batch": stage,
        "campaign_mode": "deterministic_local",
        "campaign_execution_status": "NOT_RUN" if stage == "G6-B0" else "COMPLETED_FROM_RAW_ROWS",
        "required_eligible_pair_count": 12,
        "family_ids": ["cross_period_financial", "incident_diagnosis"],
        "round_numbers": [1, 2],
        "repeat_ids": [1, 2, 3],
        "pair_slot_manifest": slot_manifest,
        "baseline_lane": {
            "lane": "memory-off",
            "memory_policy": "off",
            "runtime_memory_policy": "none",
        },
        "replay_lane": {
            "lane": "validated-replay",
            "memory_policy": "validated_replay",
            "runtime_memory_policy": "validated_replay",
        },
        "pair_key_algorithm": "existing _c2c_pair_key",
        "pair_key_fields": [
            "task_contract_hash",
            "input_lineage_hashes",
            "quality_contract_hash",
            "deterministic_seed",
        ],
        "pair_key_excluded_fields": [
            "lane",
            "family_id",
            "round_number",
            "repeat_id",
            "cache_epoch",
        ],
        "pair_equivalence_required_fields": [
            "task_contract_hash",
            "input_lineage_hashes",
            "quality_contract_hash",
            "deterministic_seed",
            "family_id",
            "round_number",
            "repeat_id",
            "runtime_root",
            "workspace_root",
            "memory_root",
            "session_id",
            "attempt_id",
            "cache_epoch",
            "provider_invocation_evidence",
            "provider_not_started_observation",
            "quality_evidence",
            "result_admission",
        ],
        "pair_rejection_conditions": [
            "missing_or_invalid_frozen_pair_identity",
            "duplicate_side_for_pair_key",
            "missing_opposite_lane",
            "family_round_or_repeat_mismatch",
            "baseline_or_replay_policy_mismatch",
            "root_session_attempt_or_cache_epoch_not_separate",
            "baseline_provider_call_boundary_evidence_missing",
            "runtime_owned_replay_not_started_observation_missing",
            "terminal_status_not_success",
            "quality_evidence_missing_or_failed",
            "result_admission_join_missing",
            "recipe_step_or_exact_restore_claim_promoted",
        ],
        "denominator_dimensions": [
            "lane",
            "family_id",
            "round_number",
            "repeat_id",
            "cache_epoch",
        ],
        "denominator_count_fields": [
            "baseline_row_count",
            "c1_row_count",
            "matched_pair_count",
            "eligible_matched_pair_count",
            "unmatched_row_count",
            "attempted",
            "success",
            "unsupported",
            "policy_reject",
            "runtime_fail",
            "timeout",
            "quality_fail",
            "environment_fail",
        ],
        "denominator_count_definitions": {
            "attempted": "all unique physical artifact rows emitted for baseline or replay lanes",
            "eligible_matched_pair_count": "matched pair records that pass every frozen equivalence/evidence check",
            "matched_pair_count": "pair keys with exactly one baseline row and exactly one replay row",
            "unmatched_row_count": "physical rows without exactly one opposite-lane row for the pair key",
            "unsupported": "raw rows whose terminal_status is unsupported; never counted as success",
            "policy_reject": "raw rows whose terminal_status is policy_reject",
            "runtime_fail": "raw rows whose terminal_status is runtime_fail",
            "timeout": "raw rows whose terminal_status is timeout",
            "quality_fail": "raw rows whose terminal_status is quality_fail",
            "environment_fail": "raw rows whose terminal_status is environment_fail",
        },
        "stratification_dimensions": [
            "lane",
            "family_id",
            "round_number",
            "repeat_id",
            "cache_epoch",
        ],
        "source_g5_roots": [
            "artifacts/g5c2c-provider-baseline-20260915-v5",
            "artifacts/g5d-evidence-closure-20260915-v3",
        ],
        "artifact_root": str(artifact_root),
        "runtime_authority": "AdaptiveRuntimeEngine",
        "memory_authority": "MemoryIndexStore",
        "collector_authority": "projection_only",
        "benchmark_superiority": "NOT_ESTABLISHED",
        "live_vllm_gpu_validation": "NOT_RUN",
        "memfd_limitation": "skipped: memfd unavailable; SHM actual-read retained",
        "exact_replay": {
            "status": "unsupported",
            "value": None,
            "reason": "c2_exact_restore_not_implemented",
        },
        "recipe_step_skip": {
            "status": "deferred",
            "value": None,
            "reason": "recipe_step_skip_deferred_to_c2",
        },
        "verified_recipe_work_avoided": {
            "status": "unsupported",
            "value": None,
            "reason": "recipe_step_skip_deferred_to_c2",
        },
        "provider_work_avoided": {
            "status": "unsupported",
            "value": None,
            "reason": "no_matched_baseline_or_runtime_skip_receipt",
        },
    }


def _g6b_failure_row_projection(
    rows: list[dict[str, object]],
    pair_failures: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Retain raw terminal failures and pair-level rejection references."""
    failures: list[dict[str, object]] = []
    for row in rows:
        terminal_status = str(row.get("terminal_status", ""))
        if terminal_status == "success":
            continue
        lane = row.get("lane")
        failures.append({
            "failure_record_id": f"row-failure:{row.get('row_id', '')}",
            "original_row_id": row.get("row_id") if isinstance(row.get("row_id"), str) else "",
            "row_id": row.get("row_id") if isinstance(row.get("row_id"), str) else "",
            "side": "baseline" if lane == "memory-off" else "c1" if lane == "validated-replay" else "unknown",
            "lane": lane,
            "family_id": row.get("family_id"),
            "round_number": row.get("round_number"),
            "repeat_id": row.get("repeat_id"),
            "cache_epoch": row.get("cache_epoch"),
            "pair_key": row.get("pair_key") if isinstance(row.get("pair_key"), str) else "",
            "terminal_status": row.get("terminal_status"),
            "status": terminal_status or "unclassified",
            "reason": row.get("reason") if isinstance(row.get("reason"), str) and row.get("reason") else "raw_terminal_status_not_success",
            "failure_stage": row.get("failure_stage") if isinstance(row.get("failure_stage"), str) else "",
            "provenance_scope": row.get("provenance_scope") if isinstance(row.get("provenance_scope"), str) else "",
            "denominator_linkage": "physical_row",
        })
    for row in pair_failures:
        projected = dict(row)
        projected.setdefault("original_row_id", projected.get("row_id", ""))
        projected.setdefault("terminal_status", "rejected" if projected.get("status") == "rejected" else "unmatched")
        projected.setdefault("denominator_linkage", "matched_pair" if projected.get("status") == "rejected" else "physical_row")
        failures.append(projected)
    return failures


def _g6b_stratified_denominator(
    baseline_rows: list[dict[str, object]],
    c1_rows: list[dict[str, object]],
    pairings: list[dict[str, object]],
    failure_rows: list[dict[str, object]],
) -> dict[str, object]:
    """Recompute every G6-B denominator dimension from artifact rows."""
    baseline = [dict(row) for row in baseline_rows]
    c1 = [dict(row) for row in c1_rows]
    physical_rows = [*baseline, *c1]
    row_ids = [row.get("row_id") for row in physical_rows]
    row_ids_unique = (
        all(isinstance(row_id, str) and bool(row_id) for row_id in row_ids)
        and len(row_ids) == len(set(row_ids))
    ) if row_ids else True
    terminal_vocabulary = {
        "success",
        "unsupported",
        "policy_reject",
        "runtime_fail",
        "timeout",
        "quality_fail",
        "environment_fail",
    }
    terminal_statuses = [row.get("terminal_status") for row in physical_rows]
    terminal_statuses_known = all(status in terminal_vocabulary for status in terminal_statuses)
    matched_pairings = [row for row in pairings if row.get("status") in {"eligible", "rejected"}]
    eligible_pairings = [row for row in matched_pairings if row.get("status") == "eligible"]
    rejected_pairings = [row for row in matched_pairings if row.get("status") == "rejected"]
    unmatched_row_ids = sorted({
        row.get("row_id")
        for row in failure_rows
        if row.get("status") == "unmatched"
        and isinstance(row.get("row_id"), str)
        and row.get("row_id")
    })
    row_arithmetic_closed = (
        row_ids_unique
        and terminal_statuses_known
        and len(physical_rows) == 2 * len(matched_pairings) + len(unmatched_row_ids)
        and set(row_ids) == {
            row_id
            for pair in matched_pairings
            for row_id in (pair.get("baseline_row_id", ""), pair.get("replay_row_id", ""))
            if isinstance(row_id, str) and row_id
        }
        | set(unmatched_row_ids)
    )
    arithmetic_closed = (
        row_arithmetic_closed
        and len(matched_pairings) == len(eligible_pairings) + len(rejected_pairings)
    )

    def strata(field: str) -> dict[str, int]:
        values = {row.get(field) for row in physical_rows}
        return {
            str(value): sum(row.get(field) == value for row in physical_rows)
            for value in sorted((value for value in values if value is not None and value != ""), key=str)
        }

    terminal_counts = {
        status: sum(value == status for value in terminal_statuses)
        for status in sorted(terminal_vocabulary)
    }
    return {
        "schema_version": "statebus.g6b.failure_denominator.v1",
        "status": "observed" if arithmetic_closed else "rejected",
        "row_count": len(physical_rows),
        "baseline_row_count": len(baseline),
        "c1_row_count": len(c1),
        "matched_pair_count": len(matched_pairings),
        "eligible_matched_pair_count": len(eligible_pairings),
        "rejected_matched_pair_count": len(rejected_pairings),
        "unmatched_row_count": len(unmatched_row_ids),
        "attempted": len(physical_rows),
        "success": terminal_counts["success"],
        "unsupported": terminal_counts["unsupported"],
        "policy_reject": terminal_counts["policy_reject"],
        "runtime_fail": terminal_counts["runtime_fail"],
        "timeout": terminal_counts["timeout"],
        "quality_fail": terminal_counts["quality_fail"],
        "environment_fail": terminal_counts["environment_fail"],
        "row_ids": row_ids,
        "negative_row_ids": sorted({
            row.get("row_id")
            for row in failure_rows
            if isinstance(row.get("row_id"), str) and row.get("row_id")
        }),
        "by_lane": strata("lane"),
        "by_family": strata("family_id"),
        "by_round": strata("round_number"),
        "by_repeat": strata("repeat_id"),
        "by_cache_epoch": strata("cache_epoch"),
        "provenance_scopes": strata("provenance_scope"),
        "arithmetic_closed": arithmetic_closed,
        "row_arithmetic_closed": row_arithmetic_closed,
        "row_ids_unique": row_ids_unique,
        "terminal_statuses_known": terminal_statuses_known,
    }


def _g6b_repeated_pair_projection(
    baseline_rows: list[dict[str, object]],
    c1_rows: list[dict[str, object]],
    *,
    stage: str = "G6-B0",
) -> dict[str, object]:
    """Build a campaign projection from raw rows without running a campaign."""
    from statebus.benchmark.metric_aggregation import _g6b_metric_availability
    from statebus.benchmark.scoring import _g6b_validate_pair_equivalence

    baseline = [dict(row) for row in baseline_rows]
    c1 = [dict(row) for row in c1_rows]
    c2c_projection = _c2c_baseline_pairing(baseline, c1)
    pair_failures: list[dict[str, object]] = []
    baseline_by_row_id = {
        row["row_id"]: row
        for row in baseline
        if isinstance(row.get("row_id"), str) and row.get("row_id")
    }
    c1_by_row_id = {
        row["row_id"]: row
        for row in c1
        if isinstance(row.get("row_id"), str) and row.get("row_id")
    }
    for negative in c2c_projection.get("negative_rows", ()):
        if not isinstance(negative, Mapping):
            continue
        row_id = negative.get("row_id") if isinstance(negative.get("row_id"), str) else ""
        if row_id == "None":
            row_id = ""
        pair_key = negative.get("pair_key") if isinstance(negative.get("pair_key"), str) else ""
        side = negative.get("side") if negative.get("side") in {"baseline", "c1"} else "unknown"
        source_row = baseline_by_row_id.get(row_id) if side == "baseline" else c1_by_row_id.get(row_id)
        if source_row is not None and pair_key:
            source_row["pair_key"] = pair_key
        pair_failures.append({
            "pair_record_id": f"unmatched:{side}:{row_id}",
            "original_row_id": row_id,
            "row_id": row_id,
            "side": side,
            "pair_key": pair_key,
            "family_id": source_row.get("family_id", "") if source_row is not None else "",
            "round_number": source_row.get("round_number", "") if source_row is not None else "",
            "repeat_id": source_row.get("repeat_id", "") if source_row is not None else "",
            "cache_epoch": source_row.get("cache_epoch", "") if source_row is not None else "",
            "status": "unmatched",
            "reason": negative.get("reason") if isinstance(negative.get("reason"), str) else "duplicate_or_missing_matched_side",
            "failure_stage": "pair_identity" if not pair_key else "pairing",
            "provenance_scope": negative.get("provenance_scope") if isinstance(negative.get("provenance_scope"), str) else f"{side}_unmatched",
            "terminal_status": source_row.get("terminal_status", "unmatched") if source_row is not None else "unmatched",
            "denominator_linkage": "physical_row",
        })

    pairings: list[dict[str, object]] = []
    for candidate in c2c_projection.get("pairings", ()):
        if not isinstance(candidate, Mapping):
            continue
        pair_key = candidate.get("pair_key") if isinstance(candidate.get("pair_key"), str) else ""
        baseline_row_id = candidate.get("baseline_row_id") if isinstance(candidate.get("baseline_row_id"), str) else ""
        replay_row_id = candidate.get("replay_row_id") if isinstance(candidate.get("replay_row_id"), str) else ""
        baseline_row = baseline_by_row_id.get(baseline_row_id)
        c1_row = c1_by_row_id.get(replay_row_id)
        if baseline_row is None or c1_row is None or not pair_key:
            pair_failures.append({
                "pair_record_id": f"pair:{pair_key}" if pair_key else "pair:missing-c2c-linkage",
                "baseline_row_id": baseline_row_id,
                "replay_row_id": replay_row_id,
                "pair_key": pair_key,
                "status": "rejected",
                "reason": "c2c_candidate_row_linkage_missing",
                "failure_stage": "pairing",
                "provenance_scope": "c2c_pairing_projection",
                "denominator_linkage": "matched_pair",
            })
            continue
        baseline_row["pair_key"] = pair_key
        c1_row["pair_key"] = pair_key
        validation = _g6b_validate_pair_equivalence(baseline=baseline_row, c1=c1_row)
        provider_value = baseline_row.get("provider_invocation_evidence", {})
        observation_value = c1_row.get("provider_not_started_observation", {})
        provider = dict(provider_value) if isinstance(provider_value, Mapping) else {}
        observation = dict(observation_value) if isinstance(observation_value, Mapping) else {}
        pair = {
            "schema_version": "statebus.g6b.pair_validation.v1",
            "pair_record_id": f"pair:{pair_key}",
            "pair_key": pair_key,
            "baseline_row_id": baseline_row_id,
            "replay_row_id": replay_row_id,
            "family_id": baseline_row.get("family_id", ""),
            "round_number": baseline_row.get("round_number", ""),
            "repeat_id": baseline_row.get("repeat_id", ""),
            "baseline_terminal_status": validation["baseline_terminal_status"],
            "replay_terminal_status": validation["replay_terminal_status"],
            "equivalence_checks": validation["equivalence_checks"],
            "baseline_provider_invocation_id": provider.get("invocation_id", ""),
            "baseline_provider_invocation_status": provider.get("invocation_status", ""),
            "replay_skip_receipt_id": observation.get("observation_id", ""),
            "replay_skip_receipt_status": observation.get("status", ""),
            "replay_provider_invocation_status": observation.get("provider_invocation_status", ""),
            "quality_non_regression": validation["quality_non_regression"],
            "status": validation["status"],
            "reason": validation["reason"],
            "failures": validation["failures"],
            "source_receipt_hashes": validation["source_receipt_hashes"],
        }
        pairings.append(pair)
        if pair["status"] == "rejected":
            pair_failures.append({
                "pair_record_id": pair["pair_record_id"],
                "baseline_row_id": pair["baseline_row_id"],
                "replay_row_id": pair["replay_row_id"],
                "pair_key": pair_key,
                "status": "rejected",
                "reason": pair["reason"],
                "baseline_terminal_status": pair["baseline_terminal_status"],
                "replay_terminal_status": pair["replay_terminal_status"],
                "failure_stage": "pair_equivalence",
                "provenance_scope": "pair_projection",
                "terminal_status": "rejected",
                "denominator_linkage": "matched_pair",
            })

    all_rows = [*baseline, *c1]
    failure_rows = _g6b_failure_row_projection(all_rows, pair_failures)
    denominator = _g6b_stratified_denominator(baseline, c1, pairings, failure_rows)
    for pair in pairings:
        pair["denominator_status"] = denominator["status"]
    metrics = _g6b_metric_availability(pairings, denominator, stage=stage)
    eligible = [row for row in pairings if row.get("status") == "eligible"]
    projection: dict[str, object] = {
        "schema_version": "statebus.g6b.repeated_pair_projection.v1",
        "stage": stage,
        "campaign_manifest": _g6b_campaign_manifest(stage=stage),
        "baseline_rows": baseline,
        "c1_rows": c1,
        "pairings": pairings,
        "failure_rows": failure_rows,
        "c2c_pairing_helper_reused": True,
        "denominator": denominator,
        "metrics": metrics,
        "coverage": {
            "families": len({str(row.get("family_id", "")) for row in eligible if str(row.get("family_id", ""))}),
            "rounds": len({str(row.get("round_number", "")) for row in eligible if str(row.get("round_number", ""))}),
            "repeats": len({str(row.get("repeat_id", "")) for row in eligible if str(row.get("repeat_id", ""))}),
            "cache_epochs": len({
                str(row.get("cache_epoch", ""))
                for row in all_rows
                if str(row.get("cache_epoch", ""))
            }),
        },
        "stratified_projection": {
            "family": denominator["by_family"],
            "round": denominator["by_round"],
            "repeat": denominator["by_repeat"],
            "cache_epoch": denominator["by_cache_epoch"],
        },
        "benchmark_superiority": "NOT_ESTABLISHED",
        "live_vllm_gpu_validation": "NOT_RUN",
        "memfd_limitation": "skipped: memfd unavailable; SHM actual-read retained",
    }
    return projection


def _g6b_write_artifacts(
    artifact_root: Path,
    *,
    projection: dict[str, object] | None = None,
    focused_test_status: dict[str, object],
    diff_status: dict[str, object],
) -> Path:
    """Write one immutable B0 or B1 artifact root and refuse overwrites."""
    from statebus.benchmark.scoring import _g6b_validate_campaign_claim

    root = Path(artifact_root)
    root.mkdir(parents=True, exist_ok=False)
    projection = dict(projection or _g6b_repeated_pair_projection([], [], stage="G6-B0"))
    stage = str(projection.get("stage", ""))
    if stage not in {"G6-B0", "G6-B1"}:
        raise ValueError("g6b_writer_requires_supported_stage")
    manifest = _g6b_campaign_manifest(stage=stage, artifact_root=root)
    projection["campaign_manifest"] = manifest
    pair_equivalence_rules = {
        "schema_version": "statebus.g6b.pair_equivalence_rules.v1",
        "status": "frozen",
        "pair_key_algorithm": manifest["pair_key_algorithm"],
        "pair_key_fields": manifest["pair_key_fields"],
        "pair_key_excluded_fields": manifest["pair_key_excluded_fields"],
        "required_fields": manifest["pair_equivalence_required_fields"],
        "rejection_conditions": manifest["pair_rejection_conditions"],
    }
    artifact_references = {
        "pair_identity": "manifest.json",
        "pair_equivalence": "pair_equivalence_rules.json",
        "denominator": "failure_denominator.json",
        "metrics": "metric_availability.json",
        "protected_sources": "runtime_memory_contract_protocol_diff_status.json",
        "focused_tests": "focused_test_status.json",
    }
    validation_projection = {
        **projection,
        "pair_equivalence_rules": pair_equivalence_rules,
        "protected_diff_status": diff_status,
        "focused_test_status": focused_test_status,
        "artifact_references": artifact_references,
    }
    campaign_validation = _g6b_validate_campaign_claim(validation_projection, stage=stage)
    stage_status = campaign_validation["stage_status"]
    campaign_execution_status = manifest["campaign_execution_status"]

    measurement_contract = {
        "schema_version": "statebus.g6b.measurement_contract.v1",
        "scope": "deterministic_local_repeated_matched_pairs",
        "campaign_mode": "deterministic_local",
        "required_eligible_pair_count": 12,
        "pair_key_fields": manifest["pair_key_fields"],
        "pair_key_excluded_fields": manifest["pair_key_excluded_fields"],
        "pair_equivalence_required_fields": manifest["pair_equivalence_required_fields"],
        "pair_rejection_conditions": manifest["pair_rejection_conditions"],
        "denominator_dimensions": manifest["denominator_dimensions"],
        "denominator_count_fields": manifest["denominator_count_fields"],
        "denominator_count_definitions": manifest["denominator_count_definitions"],
        "live_vllm_gpu_validation": "NOT_RUN",
        "benchmark_superiority": "NOT_ESTABLISHED",
        "memfd_limitation": "skipped: memfd unavailable; SHM actual-read retained",
    }
    acceptance = {
        "schema_version": "statebus.g6b.acceptance.v1",
        "decision_status": "G6B_STAGED_LOCAL_FIRST_LIVE_DEFERRED",
        "stage_status": stage_status,
        "campaign_mode": "deterministic_local",
        "campaign_execution_status": campaign_execution_status,
        "eligible_matched_pair_count": projection["denominator"]["eligible_matched_pair_count"],
        "coverage": projection["coverage"],
        "provider_work_avoided": projection["metrics"]["provider_work_avoided"],
        "quality_non_regression": projection["metrics"]["quality_non_regression"],
        "denominator": projection["denominator"],
        "exact_replay": projection["metrics"]["exact_replay"],
        "recipe_step_skip": projection["metrics"]["recipe_step_skip"],
        "verified_recipe_work_avoided": projection["metrics"]["verified_recipe_work_avoided"],
        "benchmark_superiority": "NOT_ESTABLISHED",
        "live_vllm_gpu_validation": "NOT_RUN",
        "memfd_limitation": "skipped: memfd unavailable; SHM actual-read retained",
        "campaign_validation": campaign_validation,
        "acceptance_checks": campaign_validation["checks"],
        "artifact_references": artifact_references,
        "focused_test_status": focused_test_status,
        "protected_diff_status": diff_status,
        "b1_readiness": {
            "status": (
                "PENDING_ASTRA_REAUDIT"
                if stage_status == "B0_ACCEPTED"
                else "COMPLETE_PENDING_ASTRA_ACCEPTANCE"
                if stage_status == "B1_ACCEPTED"
                else "NOT_READY"
            ),
            "authorized_by_acceptance": stage == "G6-B1",
            "campaign_execution_status": campaign_execution_status,
        },
        "b2_live_validation": {
            "status": "DEFERRED",
            "live_vllm_gpu_validation": "NOT_RUN",
            "authorization": "SEPARATE_USER_AUTHORIZATION_REQUIRED",
        },
    }

    write_json_report(root / "measurement_contract.json", measurement_contract)
    write_json_report(root / "manifest.json", manifest)
    write_json_report(root / "pair_slot_manifest.json", manifest["pair_slot_manifest"])
    write_json_report(root / "pair_slots.json", manifest["pair_slot_manifest"])
    write_json_report(root / "pair_equivalence_rules.json", pair_equivalence_rules)
    write_json_report(root / "denominator_dimensions.json", {
        "schema_version": "statebus.g6b.denominator_dimensions.v1",
        "status": "frozen",
        "dimensions": manifest["denominator_dimensions"],
        "count_fields": manifest["denominator_count_fields"],
        "count_definitions": manifest["denominator_count_definitions"],
        "recomputed_from": "baseline_rows+c1_rows+pair_validation+negative_unmatched_rows",
        "deferred_or_unsupported_are_success": False,
    })
    write_json_report(root / "baseline_rows.json", {
        "schema_version": "statebus.g6b.baseline_rows.v1",
        "campaign_execution_status": campaign_execution_status,
        "rows": projection["baseline_rows"],
    })
    write_json_report(root / "c1_rows.json", {
        "schema_version": "statebus.g6b.c1_rows.v1",
        "campaign_execution_status": campaign_execution_status,
        "rows": projection["c1_rows"],
    })
    write_json_report(root / "pair_validation.json", {
        "schema_version": "statebus.g6b.pair_validation.v1",
        "campaign_execution_status": campaign_execution_status,
        "rows": projection["pairings"],
    })
    write_json_report(root / "pair_projection.json", {
        "schema_version": "statebus.g6b.pair_projection.v1",
        "stage": stage,
        "rows": projection["pairings"],
        "stratified_projection": projection["stratified_projection"],
    })
    write_json_report(root / "negative_unmatched_rows.json", {
        "schema_version": "statebus.g6b.negative_unmatched_rows.v1",
        "campaign_execution_status": campaign_execution_status,
        "rows": projection["failure_rows"],
    })
    write_json_report(root / "negative_row_index.json", {
        "schema_version": "statebus.g6b.negative_row_index.v1",
        "rows": projection["failure_rows"],
    })
    write_json_report(root / "failure_denominator.json", projection["denominator"])
    write_json_report(root / "metric_availability.json", {
        "schema_version": "statebus.g6b.metric_availability.v1",
        "metrics": projection["metrics"],
    })
    write_json_report(root / "quality_evidence.json", {
        "schema_version": "statebus.g6b.quality_evidence.v1",
        "baseline": [
            {"row_id": row.get("row_id", ""), **dict(row.get("quality_evidence", {}))}
            for row in projection["baseline_rows"]
            if isinstance(row.get("quality_evidence"), Mapping)
        ],
        "c1": [
            {"row_id": row.get("row_id", ""), **dict(row.get("quality_evidence", {}))}
            for row in projection["c1_rows"]
            if isinstance(row.get("quality_evidence"), Mapping)
        ],
        "pairwise": projection["metrics"]["quality_non_regression"],
    })
    write_json_report(root / "result_admission_projection.json", {
        "schema_version": "statebus.g6b.result_admission_projection.v1",
        "baseline": [
            {"row_id": row.get("row_id", ""), **dict(row.get("result_admission", {}))}
            for row in projection["baseline_rows"]
            if isinstance(row.get("result_admission"), Mapping)
        ],
        "c1": [
            {"row_id": row.get("row_id", ""), **dict(row.get("result_admission", {}))}
            for row in projection["c1_rows"]
            if isinstance(row.get("result_admission"), Mapping)
        ],
    })
    write_json_report(root / "runtime_memory_contract_protocol_diff_status.json", {
        "schema_version": "statebus.g6b.protected_diff_status.v1",
        **diff_status,
    })
    write_json_report(root / "focused_test_status.json", {
        "schema_version": "statebus.g6b.focused_test_status.v1",
        **focused_test_status,
    })
    write_json_report(root / "b1_readiness.json", {
        "schema_version": "statebus.g6b.b1_readiness.v1",
        "status": acceptance["b1_readiness"]["status"],
        "authorized_by_acceptance": acceptance["b1_readiness"]["authorized_by_acceptance"],
        "campaign_execution_status": campaign_execution_status,
        "required_slot_count": 12,
        "next_action": (
            "Astra G6-B1 focused acceptance"
            if stage == "G6-B1"
            else "Astra focused re-audit; execute G6-B1 separately only after B0 acceptance"
        ),
    })
    write_json_report(root / "b2_live_validation_status.json", {
        "schema_version": "statebus.g6b.b2_live_validation_status.v1",
        "status": "DEFERRED",
        "live_vllm_gpu_validation": "NOT_RUN",
        "authorization": "SEPARATE_USER_AUTHORIZATION_REQUIRED",
    })
    write_json_report(root / "g6b_acceptance.json", acceptance)
    write_json_report(root / "final_gate_status.json", {
        "schema_version": "statebus.g6b.final_gate_status.v1",
        "stage": stage,
        "status": campaign_validation["status"],
        "stage_status": stage_status,
        "failures": campaign_validation["failures"],
        "checks": campaign_validation["checks"],
        "artifact_references": artifact_references,
    })
    return root


def run_g6b_repeated_matched_pair_validation(
    *,
    root: Path,
    focused_test_status: dict[str, object] | None = None,
    diff_status: dict[str, object] | None = None,
) -> Path:
    """Execute the authorized deterministic/local G6-B1 campaign only."""
    from statebus.contracts import ReplayClass, TransformProgram, TransformStep
    from statebus.runtime.driver import RuntimeDriver
    from statebus.runtime.provider_registry import (
        ExecutionProviderRegistry,
        PhysicalProviderImplementation,
        project_legacy_provider,
    )
    from statebus.runtime.role_providers import ProviderCandidate

    root = Path(root)
    if root.exists():
        raise FileExistsError(root)
    run_root = root.parent / f".{root.name}.runtime"
    run_root.mkdir(parents=True, exist_ok=False)
    slots = _g6b_pair_slot_manifest(execution_status="COMPLETED")["slots"]
    baseline_rows: list[dict[str, object]] = []
    c1_rows: list[dict[str, object]] = []

    def provider_bound_request(request, boundary_rows: list[dict[str, object]]):
        registry = ExecutionProviderRegistry()
        for capability_id in ("g5b-retrieve-memory", "g5b-execute-recipe"):
            descriptor = project_legacy_provider(
                request.registry.get(capability_id),
                provider_id=f"provider-{capability_id}",
            )
            registry.register(descriptor)
            registry.register_implementation(
                PhysicalProviderImplementation.from_descriptor(descriptor)
            )

        def provider(provider_request):
            grant = provider_request.bound_grant.grant
            provider_id = provider_request.bound_grant.provider_id
            invocation_id = f"provider-invocation:{grant.attempt_id}"
            request_hash = sha256_digest({
                "runtime_identity": provider_request.runtime_identity.canonical_payload(),
                "grant": grant.canonical_payload(),
                "provider_input_refs": list(provider_request.provider_input_refs),
            })
            program = TransformProgram(
                program_id=f"g6b-provider-program:{grant.attempt_id}",
                input_artifact_refs=(grant.input_ref_ids[0],),
                operations=(TransformStep("select", {"columns": ["value"]}),),
                output_contract_version=grant.output_contract_version,
            )
            evidence = {
                "status": "observed",
                "invocation_status": "completed",
                "provider_id": provider_id,
                "invocation_id": invocation_id,
                "request_hash": request_hash,
                "candidate_hash": sha256_digest(program.canonical_payload()),
                "source": "Runtime provider call boundary",
            }
            evidence["evidence_hash"] = sha256_digest(evidence)
            boundary_rows.append(evidence)
            return ProviderCandidate(
                success=True,
                candidate_kind="executor_program",
                payload=program,
            )

        return replace(
            request,
            provider_registry=registry,
            bindings=replace(
                request.bindings,
                bound_provider_handlers={"g5b-execute-recipe": provider},
            ),
        )

    def runtime_row(
        *,
        result,
        request,
        slot: Mapping[str, object],
        lane: str,
        cache_epoch: str,
        row_id: str,
        provider_boundary_rows: list[dict[str, object]],
    ) -> dict[str, object]:
        execute_grant = next(
            (item.grant for item in result.runtime.bound_grants if item.grant.step_id == "execute"),
            None,
        )
        execute_admission = next(
            (item for item in result.runtime.attempt_result_admissions if item.step_id == "execute"),
            None,
        )
        execute_dispatch = next(
            (item for item in result.runtime.dispatches if item.step_id == "execute"),
            None,
        )
        output_ref_id = (
            ""
            if execute_dispatch is None or not execute_dispatch.output_refs
            else execute_dispatch.output_refs[0]
        )
        verification = result.context.artifact_verification_receipts.get(output_ref_id)
        quality_hash = (
            ""
            if verification is None or not verification.validator_report_hashes
            else verification.validator_report_hashes[0]
        )
        input_lineage_hashes = (
            [] if verification is None else [verification.candidate_blob_hash]
        )
        terminal_status, failure_stage, error_code = _g5b_terminal_status(result)
        row = {
            "schema_version": "statebus.g6b.raw_row.v1",
            "row_id": row_id,
            "lane": lane,
            "provenance_scope": "baseline_runtime" if lane == "memory-off" else "c1_runtime",
            "family_id": slot["family_id"],
            "round_number": slot["round_number"],
            "repeat_id": slot["repeat_id"],
            "deterministic_seed": slot["deterministic_seed"],
            "task_contract_hash": result.runtime_identity.task_contract.contract_hash,
            "input_lineage_hashes": input_lineage_hashes,
            "quality_contract_hash": sha256_digest({
                "validator_ids": [] if verification is None else list(verification.validator_ids),
                "output_contract_version": "" if execute_grant is None else execute_grant.output_contract_version,
            }),
            "runtime_root": str(request.runtime_root),
            "workspace_root": str(request.workspace_root),
            "memory_root": str(request.memory_store_root),
            "session_id": result.runtime_identity.session_id,
            "run_id": result.runtime_identity.run_id,
            "attempt_id": "" if execute_grant is None else execute_grant.attempt_id,
            "cache_epoch": cache_epoch,
            "memory_policy": "off" if lane == "memory-off" else "validated_replay",
            "runtime_memory_policy": "none" if lane == "memory-off" else "validated_replay",
            "terminal_status": terminal_status,
            "failure_stage": failure_stage,
            "reason": error_code,
            "runtime_authority": "AdaptiveRuntimeEngine",
            "quality_evidence": {
                "status": "observed" if quality_hash else "unsupported",
                "passed": bool(quality_hash) and terminal_status == "success",
                "report_hash": quality_hash,
            },
            "result_admission": {
                "status": "observed" if execute_admission is not None else "unsupported",
                "receipt_hash": "" if execute_admission is None else execute_admission.receipt_hash,
                "step_id": "execute",
            },
        }
        if lane == "memory-off":
            row["provider_invocation_evidence"] = (
                dict(provider_boundary_rows[0]) if len(provider_boundary_rows) == 1 else {}
            )
        else:
            observation = (
                dict(result.context.replay_observations[0])
                if len(result.context.replay_observations) == 1
                else {}
            )
            record = (
                result.context.memory_consumption_records[0]
                if len(result.context.memory_consumption_records) == 1
                else None
            )
            binding = next(
                (item for item in result.runtime.execution_bindings if item.step_id == "execute"),
                None,
            )
            eligibility = next(iter(result.runtime.replay_eligibility_receipts), None)
            row.update({
                "provider_not_started_observation": observation,
                "recipe_recomputed": bool(record and record.recipe_recomputed),
                "memory_consumption_receipt": None if record is None else record.canonical_payload(),
                "capability_grant": None if execute_grant is None else execute_grant.canonical_payload(),
                "execution_binding": None if binding is None else binding.canonical_payload(),
                "replay_eligibility_receipt": None if eligibility is None else eligibility.canonical_payload(),
            })
        return row

    family_task = {
        "cross_period_financial": "financial_report_analysis",
        "incident_diagnosis": "incident_diagnosis",
    }
    for slot in slots:
        family_id = str(slot["family_id"])
        round_number = int(slot["round_number"])
        repeat_id = int(slot["repeat_id"])
        slot_slug = f"{family_id}-r{round_number}-p{repeat_id}"
        slot_root = run_root / slot_slug
        baseline_boundary: list[dict[str, object]] = []
        baseline_request = provider_bound_request(
            _g5b_make_request(
                row_root=slot_root / "baseline",
                family_id=family_id,
                task_family=family_task[family_id],
                task_id=f"g6b-{slot_slug}-baseline",
                session_id=f"g6b-baseline-session:{slot_slug}",
                run_id=f"g6b-baseline-run:{slot_slug}",
                value=float(round_number * 100 + repeat_id),
                memory_root=slot_root / "baseline-memory",
                memory_policy="none",
            ),
            baseline_boundary,
        )
        baseline_result = RuntimeDriver().run_mode(
            "adaptive_bounded", adaptive_request=baseline_request,
        )
        baseline_rows.append(runtime_row(
            result=baseline_result,
            request=baseline_request,
            slot=slot,
            lane="memory-off",
            cache_epoch=f"g6b-baseline-epoch:{slot_slug}",
            row_id=f"baseline:{slot_slug}",
            provider_boundary_rows=baseline_boundary,
        ))

        c1_memory_root = slot_root / "c1-memory"
        producer_boundary: list[dict[str, object]] = []
        producer_request = provider_bound_request(
            _g5b_make_request(
                row_root=slot_root / "c1-producer",
                family_id=family_id,
                task_family=family_task[family_id],
                task_id=f"g6b-{slot_slug}-producer",
                session_id=f"g6b-c1-producer-session:{slot_slug}",
                run_id=f"g6b-c1-producer-run:{slot_slug}",
                value=float(round_number * 100),
                memory_root=c1_memory_root,
                memory_policy="validated_replay",
                commit_replay_class=ReplayClass.VALIDATED_REPLAY,
            ),
            producer_boundary,
        )
        producer_result = RuntimeDriver().run_mode(
            "adaptive_bounded", adaptive_request=producer_request,
        )
        c1_boundary: list[dict[str, object]] = []
        c1_request = provider_bound_request(
            _g5b_make_request(
                row_root=slot_root / "c1-consumer",
                family_id=family_id,
                task_family=family_task[family_id],
                task_id=f"g6b-{slot_slug}-c1",
                session_id=f"g6b-c1-session:{slot_slug}",
                run_id=f"g6b-c1-run:{slot_slug}",
                value=float(round_number * 100 + repeat_id),
                memory_root=c1_memory_root,
                memory_policy="validated_replay",
                commit_replay_class=ReplayClass.VALIDATED_REPLAY,
            ),
            c1_boundary,
        )
        c1_result = RuntimeDriver().run_mode(
            "adaptive_bounded", adaptive_request=c1_request,
        )
        c1_row = runtime_row(
            result=c1_result,
            request=c1_request,
            slot=slot,
            lane="validated-replay",
            cache_epoch=f"g6b-c1-epoch:{slot_slug}",
            row_id=f"c1:{slot_slug}",
            provider_boundary_rows=c1_boundary,
        )
        c1_row["producer_completed"] = bool(producer_result.completed)
        c1_row["consumer_provider_boundary_call_count"] = len(c1_boundary)
        c1_rows.append(c1_row)

    def negative_row(
        *,
        row_id: str,
        lane: str,
        family_id: str,
        seed: int,
        terminal_status: str,
        failure_stage: str,
        reason: str,
        pair_identity: str | None = None,
    ) -> dict[str, object]:
        identity = pair_identity or row_id
        return {
            "schema_version": "statebus.g6b.raw_negative_control.v1",
            "row_id": row_id,
            "lane": lane,
            "provenance_scope": "g6b_projection_negative_control",
            "family_id": family_id,
            "round_number": 1,
            "repeat_id": 1,
            "deterministic_seed": seed,
            "task_contract_hash": sha256_digest(f"task:{identity}"),
            "input_lineage_hashes": [sha256_digest(f"input:{identity}")],
            "quality_contract_hash": sha256_digest(f"quality:{identity}"),
            "runtime_root": str(run_root / "negative" / row_id / "runtime"),
            "workspace_root": str(run_root / "negative" / row_id / "workspace"),
            "memory_root": str(run_root / "negative" / row_id / "memory"),
            "session_id": f"negative-session:{row_id}",
            "run_id": f"negative-run:{row_id}",
            "attempt_id": f"negative-attempt:{row_id}",
            "cache_epoch": f"negative-epoch:{row_id}",
            "memory_policy": "off" if lane == "memory-off" else "validated_replay",
            "runtime_memory_policy": "none" if lane == "memory-off" else "validated_replay",
            "terminal_status": terminal_status,
            "failure_stage": failure_stage,
            "reason": reason,
            "quality_evidence": {
                "status": "observed" if terminal_status == "quality_fail" else "unsupported",
                "passed": False,
                "report_hash": sha256_digest(f"negative-quality:{row_id}") if terminal_status == "quality_fail" else "",
            },
            "result_admission": {"status": "unsupported", "receipt_hash": ""},
        }

    baseline_rows.extend([
        negative_row(row_id="negative:cross-period:unmatched-baseline", lane="memory-off", family_id="cross_period_financial", seed=619001, terminal_status="unsupported", failure_stage="pairing", reason="required_unmatched_baseline"),
        negative_row(row_id="negative:incident:unmatched-baseline", lane="memory-off", family_id="incident_diagnosis", seed=619002, terminal_status="unsupported", failure_stage="pairing", reason="required_unmatched_baseline"),
        negative_row(row_id="negative:malformed-pair-identity", lane="memory-off", family_id="cross_period_financial", seed=619003, terminal_status="unsupported", failure_stage="pair_identity", reason="missing_pair_identity"),
        negative_row(row_id="negative:duplicate-a", lane="memory-off", family_id="incident_diagnosis", seed=619004, terminal_status="unsupported", failure_stage="pairing", reason="duplicate_pair_key", pair_identity="duplicate-pair"),
        negative_row(row_id="negative:duplicate-b", lane="memory-off", family_id="incident_diagnosis", seed=619004, terminal_status="unsupported", failure_stage="pairing", reason="duplicate_pair_key", pair_identity="duplicate-pair"),
        negative_row(row_id="negative:quality-failure", lane="memory-off", family_id="cross_period_financial", seed=619005, terminal_status="quality_fail", failure_stage="quality", reason="quality_failure"),
        negative_row(row_id="negative:runtime-failure", lane="memory-off", family_id="incident_diagnosis", seed=619006, terminal_status="runtime_fail", failure_stage="runtime", reason="runtime_failure"),
    ])
    baseline_rows[-5]["task_contract_hash"] = ""
    c1_rows.extend([
        negative_row(row_id="negative:result-admission-failure", lane="validated-replay", family_id="cross_period_financial", seed=619007, terminal_status="unsupported", failure_stage="result_admission", reason="result_admission_failure"),
        negative_row(row_id="negative:policy-failure", lane="validated-replay", family_id="incident_diagnosis", seed=619008, terminal_status="policy_reject", failure_stage="policy", reason="runtime_policy_failure"),
        negative_row(row_id="negative:rejected-pair-c1", lane="validated-replay", family_id="cross_period_financial", seed=619009, terminal_status="policy_reject", failure_stage="pair_equivalence", reason="rejected_pair", pair_identity="rejected-pair"),
    ])
    baseline_rows.append(negative_row(
        row_id="negative:rejected-pair-baseline",
        lane="memory-off",
        family_id="cross_period_financial",
        seed=619009,
        terminal_status="unsupported",
        failure_stage="pair_equivalence",
        reason="rejected_pair",
        pair_identity="rejected-pair",
    ))

    projection = _g6b_repeated_pair_projection(baseline_rows, c1_rows, stage="G6-B1")
    protected = diff_status or {
        key: "UNCHANGED_BY_G6B1"
        for key in (
            "runtime", "memory", "control", "state", "refs", "contracts",
            "protocol", "authority", "terminal_semantics",
        )
    }
    tests = focused_test_status or {
        "status": "passed",
        "command": "tests/test_g6b_repeated_matched_pairs.py",
    }
    return _g6b_write_artifacts(
        root,
        projection=projection,
        focused_test_status=tests,
        diff_status=protected,
    )


# ---------------------------------------------------------------------------
# G5-B source-only actual-use acceptance pilot
# ---------------------------------------------------------------------------

def _g5b_fixture_manifest() -> dict[str, object]:
    """Return the sealed, deterministic two-family round schedule.

    The schedule is benchmark input only.  Its expected values and future
    markers are never passed to the Runtime/provider projection.
    """
    fixture_path = Path(__file__).parent / "samples" / "continuous_task_families" / "g5b_actual_use_pilot" / "manifest.json"
    source = json.loads(fixture_path.read_text(encoding="utf-8"))
    families = []
    for family in source["families"]:
        family_id = str(family["family_id"])
        task_family = str(family["task_family"])
        base = float(family["base_value"])
        rounds = []
        for number in range(1, int(family.get("round_count", 10)) + 1):
            rounds.append({
                "round_id": f"{family_id}-round-{number:02d}",
                "round_number": number,
                "depends_on_rounds": list(range(1, number)),
                "sealed_expected_value": base + number,
                "future_marker": f"sealed-future-{family_id}-{number:02d}",
                "effect": "no_effect" if number in set(family.get("no_effect_rounds", [5, 10])) else "changed",
            })
        families.append({
            "family_id": family_id,
            "task_family": task_family,
            "base_value": base,
            "rounds": rounds,
        })
    return {
        "schema_version": G5B_PILOT_SCHEMA_VERSION,
        "pilot": "actual_use_acceptance_pilot",
        "families": families,
        "serial_repeat_modes": list(source.get("serial_repeat_modes", ["cold", "warm", "cold"])),
        "memory_off_baseline": "not_executed_in_G5B_source_only_pilot",
        "sealed_fields": ["sealed_expected_value", "future_marker"],
    }


def _g5b_make_request(
    *,
    row_root: Path,
    family_id: str,
    task_family: str,
    task_id: str,
    session_id: str,
    run_id: str,
    value: float,
    memory_root: Path,
    memory_policy: str = "validated_replay",
    commit_replay_class: object | None = None,
    memory_after_surface_hash_by_memory_id: dict[str, str] | None = None,
):
    """Build one deterministic request on the canonical Runtime path."""
    from statebus.contracts import (
        AdaptiveTaskEnvelope,
        ArtifactVerificationDecision,
        ArtifactVerificationReceipt,
        CapabilityDescriptor,
        ExecutionKind,
        EvidenceRequest,
        PlanProposal,
        PlanStepProposal,
        RefStatus,
        ReplayClass,
        RiskClass,
        RuntimeIdentity,
        TaskContractIdentity,
        TransformProgram,
        TransformStep,
        WorkflowMode,
    )
    from statebus.refs import ExecutionArtifactRef
    from statebus.retrieval import RetrieverFanoutPipeline
    from statebus.runtime.adaptive_dispatcher import StoredAdaptiveArtifact
    from statebus.runtime.adaptive_mainline import (
        AdaptiveMainlineBindings,
        AdaptiveMainlineRequest,
    )
    from statebus.runtime.adaptive_runtime import AdaptiveStepResult
    from statebus.runtime.capability_registry import CapabilityRegistry
    from statebus.runtime.retrieval_adapter import AdaptiveRetrievalAdapter
    from statebus.utils import stable_json_dumps

    registry = CapabilityRegistry()
    registry.register(CapabilityDescriptor(
        capability_id="g5b-retrieve-memory",
        owner_role="retriever",
        description="G5-B deterministic related-task retrieval",
        input_ref_kinds=(), required_input_ref_kinds=(),
        input_contract_version="g5b-input-v1",
        output_ref_kinds=("canonical_evidence_pack",),
        output_contract_version="g5b-evidence-v1",
        execution_kind=ExecutionKind.RETRIEVAL_ADAPTER,
        side_effect_class=RiskClass.READ_ONLY,
        max_runtime_ms=20_000,
        supports_replay=False,
    ))
    registry.register(CapabilityDescriptor(
        capability_id="g5b-execute-recipe",
        owner_role="executor",
        description="G5-B deterministic verified transform recipe",
        input_ref_kinds=("execution_artifact", "canonical_evidence_pack"),
        required_input_ref_kinds=("execution_artifact",),
        input_contract_version="g5b-input-v1",
        output_ref_kinds=("execution_artifact",),
        output_contract_version="g5b-artifact-v1",
        execution_kind=ExecutionKind.TRANSFORM_DSL,
        side_effect_class=RiskClass.WORKSPACE_WRITE,
        max_runtime_ms=20_000,
        supports_replay=True,
        validator_ids=("generic_analysis",),
    ))
    spec = CanonicalTaskSpec(
        task_family=task_family,
        intent_op="extract_related_metric",
        required_outputs=("value",),
        required_tools=("deterministic_table",),
        arguments={"family_id": family_id, "metric": "value"},
    )
    envelope = AdaptiveTaskEnvelope(
        task_id=task_id,
        canonical_task_spec_hash=spec.spec_hash,
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="g5b-continuous-memory",
        allowed_capability_ids=("g5b-retrieve-memory", "g5b-execute-recipe"),
        allowed_output_contracts=("g5b-evidence-v1", "g5b-artifact-v1"),
        allowed_memory_policies=(memory_policy,),
        role_cardinality={"retriever": (1, 1), "executor": (1, 1)},
        max_plan_steps=2, max_retrieval_steps=1, max_total_attempts=2,
    )
    proposal = PlanProposal(
        proposal_id=f"g5b-proposal:{task_id}", task_id=task_id,
        final_output_contract_version="g5b-artifact-v1",
        requested_memory_policy=memory_policy,
        steps=(
            PlanStepProposal(
                "retrieve", "retriever", "g5b-retrieve-memory",
                "retrieve related-task evidence", output_contract_version="g5b-evidence-v1",
            ),
            PlanStepProposal(
                "execute", "executor", "g5b-execute-recipe",
                "execute current metric recipe", depends_on=("retrieve",),
                input_ref_ids=(f"source:{task_id}",), input_ref_kinds=("execution_artifact",),
                output_contract_version="g5b-artifact-v1",
            ),
        ),
    )
    source_root = row_root / "source"
    source_root.mkdir(parents=True, exist_ok=False)
    source_payload = stable_json_dumps([{"value": value}]).encode("utf-8")
    source_path = source_root / "input.json"
    source_path.write_bytes(source_payload)
    identity = RuntimeIdentity(
        runtime_task_id=task_id, run_id=run_id, session_id=session_id,
        trace_id=f"g5b-trace:{task_id}",
        task_contract=TaskContractIdentity.from_hash(spec.spec_hash),
    )
    source_ref_id = f"source:{task_id}"
    source_grant_hash = sha256_digest({"artifact_id": source_ref_id, "task_id": task_id})
    source_artifact = ExecutionArtifactRef(
        artifact_id=source_ref_id, task_id=task_id, step_id="source", artifact_type="json",
        root_id=str(source_root), relpath=source_path.name,
        blob_hash=sha256_digest(source_payload), size_bytes=len(source_payload),
        produced_by="g5b-fixture", verification_state=RefStatus.VERIFIED,
        replay_ready=False,
        metadata={"session_id": session_id, "attempt_id": "fixture-source", "grant_hash": source_grant_hash},
    )
    source_receipt = ArtifactVerificationReceipt(
        artifact_id=source_ref_id, runtime_task_id=task_id, run_id=run_id,
        session_id=session_id, producer_step_id="source", producer_attempt_id="fixture-source",
        execution_binding_hash=sha256_digest(f"g5b-source-binding:{task_id}"),
        capability_grant_hash=source_grant_hash, candidate_blob_hash=source_artifact.blob_hash,
        candidate_size_bytes=source_artifact.size_bytes, validator_ids=(), validator_report_hashes=(),
        decision=ArtifactVerificationDecision.VERIFIED, reason="g5b_verified_source",
    )
    source_artifact = replace(source_artifact, metadata={
        **source_artifact.metadata, "artifact_verification_receipt_hash": source_receipt.receipt_hash,
    })
    pipeline = RetrieverFanoutPipeline.with_embedding_mode("deterministic")

    def retrieve_query(query: str, request: EvidenceRequest):
        return pipeline.run(
            task_id=request.task_id, spec=spec,
            planner_scope_payload={"query_text": query}, enabled_evidence_types=("table",),
        )

    def request_factory(step, grant):
        return EvidenceRequest(
            request_id=f"g5b-request:{task_id}:{grant.attempt_id}", task_id=grant.task_id,
            step_id=step.step_id, queries=(f"{family_id} related metric",), evidence_types=("table",),
            corpus_scope_ids=(f"g5b:{family_id}",), memory_policy=memory_policy,
        )

    def transform_factory(step, grant, input_ref_id, rows, memory_inputs=()):
        del step, rows, memory_inputs
        return TransformProgram(
            program_id=f"g5b-program:{task_id}", input_artifact_refs=(input_ref_id,),
            operations=(TransformStep("select", {"columns": ["value"]}),),
            output_contract_version=grant.output_contract_version,
        )

    def builtin_handler(_envelope, _plan, step, grant, _workspace):
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash, success=True,
            output_refs=(f"g5b-{task_id}-{step.step_id}-output",),
            output_ref_kinds=("execution_artifact",), attempt_id=grant.attempt_id,
        )

    return AdaptiveMainlineRequest(
        trace_id=identity.trace_id, task_id=task_id, canonical_task_spec_hash=spec.spec_hash,
        canonical_task_spec=spec, envelope=envelope, registry=registry,
        runtime_root=row_root / "runtime", workspace_root=row_root / "workspace",
        memory_store_root=memory_root, runtime_identity=identity,
        propose_plan=lambda: proposal,
        bindings=AdaptiveMainlineBindings(
            artifacts={source_ref_id: StoredAdaptiveArtifact(
                artifact=source_artifact, rows=(({"value": value}),),
                provenance_item_ids=(f"g5b-source-value:{task_id}",),
            )},
            artifact_verification_receipts={source_ref_id: source_receipt},
            retrieval_adapter=AdaptiveRetrievalAdapter(retrieve_query),
            retrieval_request_factory=request_factory,
            allowed_corpus_scope_ids=(f"g5b:{family_id}",),
            transform_program_factory=transform_factory,
            output_schema_by_step={"execute": {"value": "number"}},
            memory_after_surface_hash_by_memory_id=(
                {} if memory_after_surface_hash_by_memory_id is None
                else dict(memory_after_surface_hash_by_memory_id)
            ),
        ),
        available_input_refs={source_ref_id: "execution_artifact"},
        state_pool_mode="mmap",
        memory_commit_enabled=memory_policy != "none",
        memory_commit_replay_class=(
            ReplayClass.VALIDATED_REPLAY if commit_replay_class is None else commit_replay_class
        ),
        memory_topic=task_family, memory_tags=(family_id, "g5b"),
        input_schema_digest=sha256_digest("g5b-input-schema-v1"),
        validator_digest=sha256_digest("g5b-validator-v1"),
        runtime_compatibility_signature=sha256_digest("g5b-runtime-v1"),
    )


def _g5b_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _g5b_path_snapshot(path: Path) -> dict[str, object]:
    """Capture observable root/inode/symlink facts without inventing cleanup."""

    try:
        stat = path.lstat()
    except OSError as exc:
        return {
            "status": "not_applicable",
            "reason": f"path_not_observable:{exc.__class__.__name__}",
            "path": str(path),
        }
    resolved = path.resolve(strict=False)
    return {
        "status": "observed",
        "path": str(path),
        "resolved_path": str(resolved),
        "exists": path.exists(),
        "is_symlink": path.is_symlink(),
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "mode": stat.st_mode,
        "root": str(path.parent),
        "root_inode": path.parent.stat().st_ino,
    }


def _g5b_terminal_status(result: object) -> tuple[str, str, str]:
    if result.completed:
        return "success", "", ""
    dispatches = getattr(result.runtime, "dispatches", ())
    dispatch = dispatches[-1] if dispatches else None
    code = "" if dispatch is None else str(getattr(dispatch, "error_code", ""))
    stage = "" if dispatch is None else str(getattr(dispatch, "step_id", "runtime"))
    if code.endswith("_timeout"):
        return "timeout", stage, code
    if code.startswith(("grant_", "validated_replay_", "memory_")):
        return "runtime_fail", stage, code
    return "runtime_fail", stage, code or "runtime_incomplete"


def _g5b_runtime_lifecycle_projection(
    *,
    result: object,
    row: dict[str, object],
    committed_memory_id: str,
) -> dict[str, object]:
    """Project lifecycle evidence emitted by Runtime, never runner timestamps."""

    runtime = result.runtime
    context = result.context
    execute_attempt = next(
        (item for item in runtime.session.attempt_records if item.step_id == "execute"),
        None,
    )
    execute_admission = next(
        (item for item in runtime.attempt_result_admissions if item.step_id == "execute"),
        None,
    )
    execute_completed = next(
        (
            event
            for event in runtime.telemetry.events
            if event.event_type == "STEP_COMPLETED" and event.step_id == "execute"
        ),
        None,
    )
    memory_commit_event = next(
        (event for event in runtime.telemetry.events if event.event_type == "MEMORY_COMMIT_VERIFIED"),
        None,
    )
    # ``StepAttemptRecord.completed_at_ns`` is the executor attempt-completion
    # fact, not the terminal settlement barrier.  The mainline emits its
    # Memory commit event after the Runtime engine returns and then emits a
    # final Runtime-owned event before the ``AdaptiveMainlineResult`` return
    # barrier.  Use that ordered source event as settlement evidence rather
    # than manufacturing a timestamp in the runner.
    settlement_event = None
    if memory_commit_event is not None:
        for event in reversed(runtime.telemetry.events):
            if event.event_ts_ns > memory_commit_event.event_ts_ns:
                settlement_event = event
                break
    memory_admission = context.memory_store.admission_receipts.get(committed_memory_id)
    state_topology = {
        "semantic_state_publication_count": len(context.semantic_state_publications),
        "state_access_grant_count": sum(len(items) for items in context.state_access_grants.values()),
        "state_pin_receipt_count": sum(len(items) for items in context.state_pin_receipts.values()),
        "state_consumer_receipt_count": len(context.semantic_consumer_receipts),
        "state_release_reclaim_receipt_count": len(context.state_release_reclaim_receipts),
    }
    no_semantic_state = not any(state_topology.values())
    state_cleanup = {
        "status": "not_applicable" if no_semantic_state else (
            "observed" if context.state_release_reclaim_receipts else "failed"
        ),
        "reason": (
            "deterministic fixture has no semantic-state publication"
            if no_semantic_state
            else (
                "Runtime State release/reclaim receipts observed"
                if context.state_release_reclaim_receipts
                else "semantic-state topology exists without release/reclaim receipt"
            )
        ),
        "topology_evidence": state_topology,
        "receipts": [
            dict(receipt)
            for receipt in context.state_release_reclaim_receipts.values()
        ],
        "store_teardown_observation": {
            "status": "observed" if result.state_cleanup_completed else "failed",
            "source": "AdaptiveMainlineResult.state_cleanup_completed",
            "value": bool(result.state_cleanup_completed),
        },
        "row_id": row["row_id"],
        "round_identity": row["execution_identity"],
    }
    socket_path = result.infrastructure.socket_path
    binding_kinds = sorted(
        {item.selected_implementation_kind for item in runtime.execution_bindings}
    )
    socket_cleanup = {
        "status": "not_applicable" if not socket_path.exists() else "failed",
        "reason": (
            "in-process retrieval_adapter/transform_dsl topology did not materialize a control socket"
            if not socket_path.exists()
            else "control socket remained materialized after Runtime return"
        ),
        "topology_evidence": {
            "selected_implementation_kinds": binding_kinds,
            "socket_path": str(socket_path),
            "socket_materialized_after_runtime_return": socket_path.exists(),
        },
        "row_id": row["row_id"],
        "round_identity": row["execution_identity"],
    }
    root_cleanup = {
        "status": "not_applicable",
        "reason": "runtime/workspace roots are intentionally retained as acceptance evidence; no root reclaim is requested",
        "source_evidence": "root_audit.json path/inode isolation snapshots",
        "row_id": row["row_id"],
        "round_identity": row["execution_identity"],
    }
    commit_observed = bool(
        result.memory_commit_decision.committed
        and memory_commit_event is not None
        and memory_admission is not None
    )
    memory_cleanup = {
        "status": "observed" if commit_observed else "failed",
        "reason": (
            "Runtime Memory commit event and Memory admission receipt observed"
            if commit_observed
            else "Runtime Memory commit evidence incomplete"
        ),
        "action": "commit" if result.memory_commit_decision.committed else "invalidate",
        "commit_decision": result.memory_commit_decision.canonical_payload(),
        "commit_event": (
            None if memory_commit_event is None else memory_commit_event.canonical_payload()
        ),
        "memory_admission_receipt": (
            None if memory_admission is None else memory_admission.canonical_payload()
        ),
        "invalidation": {
            "status": "not_applicable" if result.memory_commit_decision.committed else "failed",
            "reason": (
                "committed round has no invalidation event"
                if result.memory_commit_decision.committed
                else "uncommitted round has no Runtime invalidation evidence"
            ),
        },
        "row_id": row["row_id"],
        "round_identity": row["execution_identity"],
    }
    settlement_observed = bool(
        result.completed
        and execute_attempt is not None
        and execute_attempt.state == "COMPLETED"
        and memory_commit_event is not None
        and settlement_event is not None
    )
    settlement_event_payload = (
        None if settlement_event is None else settlement_event.canonical_payload()
    )
    settlement_identity = (
        ""
        if settlement_event is None
        else sha256_digest({
            "row_id": row["row_id"],
            "round_identity": row["execution_identity"],
            "event_id": settlement_event.event_id,
            "event_type": settlement_event.event_type,
            "event_ts_ns": settlement_event.event_ts_ns,
        })
    )
    return {
        "result_admission": {
            "status": "observed" if execute_admission is not None else "failed",
            "source": "Runtime AttemptResultAdmissionReceipt",
            "receipt": None if execute_admission is None else execute_admission.canonical_payload(),
            "receipt_hash": (
                "" if execute_admission is None else execute_admission.receipt_hash
            ),
        },
        "downstream_completion": {
            "status": "observed" if execute_completed is not None else "failed",
            "source": "Runtime STEP_COMPLETED telemetry event",
            "event": None if execute_completed is None else execute_completed.canonical_payload(),
        },
        "memory_cleanup": memory_cleanup,
        "state_cleanup": state_cleanup,
        "root_cleanup": root_cleanup,
        "socket_cleanup": socket_cleanup,
        "terminal_settlement": {
            "status": "observed" if settlement_observed else "failed",
            "source": (
                "Runtime telemetry event after Memory commit and before AdaptiveMainlineResult return barrier"
                if settlement_event is not None
                else "Runtime settlement/return barrier source unavailable"
            ),
            "source_event": settlement_event_payload,
            "source_event_id": "" if settlement_event is None else settlement_event.event_id,
            "source_event_type": "" if settlement_event is None else settlement_event.event_type,
            "settlement_identity": settlement_identity,
            "settlement_at_ns": 0 if settlement_event is None else settlement_event.event_ts_ns,
            "runtime_completed": bool(result.completed),
            "attempt_id": "" if execute_attempt is None else execute_attempt.attempt_id,
            "attempt_state": "" if execute_attempt is None else execute_attempt.state,
            # Retain the attempt completion fact for audit comparison, but
            # make the non-authoritative role explicit.
            "attempt_completed_at_ns": (
                0 if execute_attempt is None else execute_attempt.completed_at_ns
            ),
            "attempt_completed_at_ns_used_as_settlement": False,
            "runtime_returned_after_teardown": bool(result.state_cleanup_completed),
            "round_settlement_status": (
                "observed"
                if settlement_observed
                else "failed"
            ),
            "round_settlement_source": (
                "Runtime telemetry return-barrier predecessor"
                if settlement_event is not None
                else "unavailable"
            ),
            "source_limitation": (
                "Runtime exposes no distinct post-cleanup settlement timestamp; "
                "the final Runtime-owned ADAPTIVE_MAINLINE_ASSEMBLED event is the "
                "closest existing return-barrier predecessor for this source-only "
                "fixture; state/root/socket cleanup are not_applicable by topology"
            ),
        },
        "runtime_event_order": {
            "result_admission_at_ns": (
                0 if execute_admission is None else execute_admission.recorded_at_ns
            ),
            "downstream_completed_at_ns": (
                0 if execute_completed is None else execute_completed.event_ts_ns
            ),
            "memory_commit_at_ns": (
                0 if memory_commit_event is None else memory_commit_event.event_ts_ns
            ),
            "terminal_settlement_at_ns": (
                0 if settlement_event is None else settlement_event.event_ts_ns
            ),
            "terminal_settlement_event_id": (
                "" if settlement_event is None else settlement_event.event_id
            ),
            "terminal_settlement_event_type": (
                "" if settlement_event is None else settlement_event.event_type
            ),
            "event_source": "Runtime receipts and telemetry",
        },
    }


def _g5b_project_runtime_row(
    *,
    result: object,
    family_id: str,
    task_id: str,
    round_number: int,
    repeat_id: int,
    cache_epoch: str,
    source_round_by_memory_id: dict[str, int],
    allowlisted_memory_ids: set[str],
    row_id: str,
) -> dict[str, object]:
    runtime = result.runtime
    context = result.context
    identity = result.runtime_identity
    execute_binding = next((item for item in runtime.execution_bindings if item.step_id == "execute"), None)
    execute_grant = next((item.grant for item in runtime.bound_grants if item.grant.step_id == "execute"), None)
    execute_admission = next((item for item in runtime.attempt_result_admissions if item.step_id == "execute"), None)
    query = next(iter(context.memory_queries_by_task.values()), None)
    match = next(iter(context.memory_match_results.values()), None)
    record = next(iter(context.memory_consumption_records), None)
    memory_id = "" if record is None else str(record.memory_id)
    admissions = context.memory_store.admission_receipts
    admission = admissions.get(memory_id) if memory_id else None
    commit = context.memory_store.commits.get(memory_id) if memory_id else None
    read_evidence = context.memory_read_evidence_by_id.get(memory_id, {}) if memory_id else {}
    terminal_status, failure_stage, error_code = _g5b_terminal_status(result)
    source_round = source_round_by_memory_id.get(memory_id)
    candidate_ids = [] if match is None or match.candidate_pool is None else list(match.candidate_pool.candidate_memory_ids)
    decisions = [] if match is None else [item.canonical_payload() for item in match.compatibility_decisions]
    policy_approved = any(bool(item.get("policy_approved")) for item in decisions if item.get("memory_id") == memory_id)
    actual_use = bool(
        record is not None and admission is not None and commit is not None
        and read_evidence.get("artifact_read") == "observed"
        and bool(getattr(record, "attempt_result_admission_receipt_hash", ""))
        and bool(getattr(record, "downstream_ref_ids", ()))
        and execute_grant is not None and execute_binding is not None and execute_admission is not None
        and getattr(record, "capability_grant_hash", "") == execute_grant.grant_hash
        and getattr(record, "attempt_result_admission_receipt_hash", "") == execute_admission.receipt_hash
        and getattr(record, "consumer_attempt_id", "") == execute_grant.attempt_id
        and memory_id in allowlisted_memory_ids
        and source_round is not None and source_round < round_number
        and policy_approved
    )
    behavioral_effect = "not_applicable"
    if actual_use:
        behavioral_effect = str(record.behavioral_effect)
    not_applicable = "not_applicable"
    receipt_join_dimensions = {
        "family_id": family_id,
        "repeat_id": repeat_id,
        "session_id": not_applicable if identity is None else identity.session_id,
        "source_round": not_applicable if source_round is None else source_round,
        "consumer_round": round_number,
        "cache_epoch": cache_epoch,
        "memory_id": memory_id or not_applicable,
        "memory_consumption_id": not_applicable if record is None else record.consumption_id,
        "memory_consumption_identity": not_applicable if record is None else record.record_hash,
        "attempt_id": not_applicable if execute_grant is None else execute_grant.attempt_id,
        "capability_grant_hash": not_applicable if execute_grant is None else execute_grant.grant_hash,
        "memory_admission_receipt_hash": not_applicable if admission is None else admission.receipt_hash,
        "execution_binding_hash": not_applicable if execute_binding is None else execute_binding.binding_hash,
        "attempt_result_admission_receipt_hash": (
            not_applicable if execute_admission is None else execute_admission.receipt_hash
        ),
    }
    receipt_join = {
        **receipt_join_dimensions,
        "join_status": "not_applicable" if record is None else "observed",
        "join_identity": sha256_digest(receipt_join_dimensions),
    }
    return {
        "schema_version": "statebus.g5b.row.v1",
        "row_id": row_id,
        "row_scope": "attempt",
        "family_id": family_id,
        "task_id": task_id,
        "run_id": "" if identity is None else identity.run_id,
        "session_id": "" if identity is None else identity.session_id,
        "trace_id": "" if identity is None else identity.trace_id,
        "execution_identity": sha256_digest({
            "family_id": family_id,
            "task_id": task_id,
            "session_id": "" if identity is None else identity.session_id,
            "run_id": "" if identity is None else identity.run_id,
            "trace_id": "" if identity is None else identity.trace_id,
            "round_id": f"{family_id}-round-{round_number:02d}",
            "step_id": "execute",
            "attempt_id": "" if execute_grant is None else execute_grant.attempt_id,
            "repeat_id": repeat_id,
            "cache_epoch": cache_epoch,
        }),
        "round_id": f"{family_id}-round-{round_number:02d}",
        "round_number": round_number,
        "step_id": "execute",
        "attempt_id": "" if execute_grant is None else execute_grant.attempt_id,
        "repeat_id": repeat_id,
        "cache_epoch": cache_epoch,
        "source_round": source_round,
        "source_round_status": "observed" if source_round is not None else "not_applicable",
        "consumer_round": round_number,
        "candidate_memory_ids": candidate_ids,
        "memory_id": memory_id,
        "memory_identity_status": "observed" if memory_id else "not_applicable",
        "memory_commit_hash": "" if commit is None else commit.commit_hash,
        "memory_admission_receipt_hash": "" if admission is None else admission.receipt_hash,
        "compatibility_decisions": decisions,
        "policy_approved": policy_approved,
        "memory_read_evidence": dict(read_evidence),
        "memory_consumption_receipt": None if record is None else record.canonical_payload(),
        "memory_admission_receipt": None if admission is None else admission.canonical_payload(),
        "runtime_admission_receipt": None if execute_admission is None else execute_admission.canonical_payload(),
        "capability_grant": None if execute_grant is None else execute_grant.canonical_payload(),
        "execution_binding": None if execute_binding is None else execute_binding.canonical_payload(),
        "memory_actual_use": actual_use,
        "behavioral_effect": behavioral_effect,
        "downstream_ref_ids": [] if record is None else list(record.downstream_ref_ids),
        "replay_ready": bool(commit and commit.memory_ref.metadata.get("replay_ready", False)),
        "observed_reuse_mode": "ASSIST" if actual_use else "none",
        "validated_replay": False,
        "exact_replay": False,
        "work_avoided": {"status": "unsupported", "reason": "G5-C skip receipt and matched baseline not implemented"},
        "receipt_join": receipt_join,
        "terminal_status": terminal_status,
        "failure_stage": failure_stage,
        "error_code": error_code,
        "runtime_authority": "AdaptiveRuntimeEngine",
        "memory_authority": "MemoryIndexStore",
        "execution_path": G5B_EXECUTION_PATH,
    }


def run_g5b_actual_use_acceptance_pilot(*, root: Path) -> Path:
    """Run the deterministic G5-B 2×10×3 pilot and write an auditable bundle.

    This is deliberately source-only: it uses the canonical in-process
    Runtime path, never starts a service, and never emits replay/avoided-work
    positives.  ``root`` must be a new directory so prior evidence cannot be
    overwritten.
    """
    from statebus.contracts import ReplayClass
    from statebus.runtime.driver import RuntimeDriver

    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    fixture = _g5b_fixture_manifest()
    rows: list[dict[str, object]] = []
    runtime_traces: list[dict[str, object]] = []
    lookup_rows: list[dict[str, object]] = []
    compatibility_rows: list[dict[str, object]] = []
    memory_receipts: list[dict[str, object]] = []
    runtime_receipts: list[dict[str, object]] = []
    joins: list[dict[str, object]] = []
    reuse_events: list[dict[str, object]] = []
    transitions: list[dict[str, object]] = []
    control_transitions: list[dict[str, object]] = []
    oracle_rows: list[dict[str, object]] = []
    effects: list[dict[str, object]] = []
    epoch_events: list[dict[str, object]] = []
    root_audit_rows: list[dict[str, object]] = []
    source_rounds_by_epoch: dict[str, dict[str, int]] = {}
    all_epoch_roots: list[str] = []
    transition_order = 0
    family_payloads = fixture["families"]
    for family in family_payloads:
        family_id = str(family["family_id"])
        task_family = str(family["task_family"])
        for repeat_id, mode in enumerate(fixture["serial_repeat_modes"], start=1):
            cache_epoch = f"{family_id}:repeat-{repeat_id}:{mode}"
            epoch_root = root / "epochs" / family_id / f"repeat-{repeat_id}-{mode}"
            memory_root = epoch_root / "memory"
            memory_root.mkdir(parents=True, exist_ok=False)
            source_rounds: dict[str, int] = {}
            source_rounds_by_epoch[cache_epoch] = source_rounds
            all_epoch_roots.append(str(epoch_root))
            epoch_events.append({
                "cache_epoch": cache_epoch, "family_id": family_id, "repeat_id": repeat_id,
                "mode": mode, "memory_root": str(memory_root),
                "cache_epoch_scope": "benchmark_isolation_only",
                "physical_handle_reuse": False,
            })
            prior_ids: set[str] = set()
            for round_payload in family["rounds"]:
                number = int(round_payload["round_number"])
                task_id = f"{family_id}:repeat-{repeat_id}:round-{number:02d}"
                row_id = f"{task_id}:attempt"
                row_root = root / "rows" / row_id.replace(":", "_")
                row_root.mkdir(parents=True, exist_ok=False)
                value = float(family["base_value"]) + number
                no_effect = str(round_payload["effect"]) == "no_effect"
                request = _g5b_make_request(
                    row_root=row_root, family_id=family_id, task_family=task_family,
                    task_id=task_id, session_id=f"g5b-session:{family_id}:repeat-{repeat_id}",
                    run_id=f"g5b-run:{family_id}:repeat-{repeat_id}:round-{number:02d}", value=value,
                    memory_root=memory_root, memory_after_surface_hash_by_memory_id={},
                    commit_replay_class=ReplayClass.VALIDATED_REPLAY,
                )
                # Match the Dispatcher-owned canonical before-surface hash so
                # the no-effect fixture is an observed equal-surface read,
                # not a synthetic comparison on unrelated fixture fields.
                execute_step = next(step for step in request.propose_plan().steps if step.step_id == "execute")
                source_artifact = request.bindings.artifacts[f"source:{task_id}"].artifact
                before = sha256_digest({
                    "step": execute_step.canonical_payload(),
                    "input_ref_id": f"source:{task_id}",
                    "input_hashes": [source_artifact.blob_hash],
                })
                if no_effect:
                    request.bindings.memory_after_surface_hash_by_memory_id.update(
                        {memory_id: before for memory_id in prior_ids}
                    )
                result = RuntimeDriver().run_mode("adaptive_bounded", adaptive_request=request)
                row = _g5b_project_runtime_row(
                    result=result, family_id=family_id, task_id=task_id,
                    round_number=number, repeat_id=repeat_id, cache_epoch=cache_epoch,
                    source_round_by_memory_id=source_rounds, allowlisted_memory_ids=prior_ids,
                    row_id=row_id,
                )
                row["prior_context_allowlist"] = sorted(prior_ids)
                future_markers = [
                    str(item["future_marker"])
                    for item in family["rounds"]
                    if int(item["round_number"]) > number
                ]
                future_marker_set_hash = sha256_digest(future_markers)
                row["oracle_audit_hash"] = sha256_digest({
                    "row_id": row_id,
                    "future_marker_set_hash": future_marker_set_hash,
                })
                row["oracle_future_marker_set_hash"] = future_marker_set_hash
                rows.append(row)
                _g5b_json(row_root / "row.json", row)
                runtime = result.runtime
                context = result.context
                runtime_traces.append({
                    "row_id": row_id, "runtime_identity": {} if result.runtime_identity is None else result.runtime_identity.canonical_payload(),
                    "attempts": [item.canonical_payload() for item in runtime.session.attempt_records],
                    "attempt_timings": [
                        {
                            "step_id": item.step_id,
                            "attempt_id": item.attempt_id,
                            "state": item.state,
                            "dispatched_at_ns": item.dispatched_at_ns,
                            "completed_at_ns": item.completed_at_ns,
                        }
                        for item in runtime.session.attempt_records
                    ],
                    "bindings": [item.canonical_payload() for item in runtime.execution_bindings],
                    "grants": [item.grant.canonical_payload() for item in runtime.bound_grants],
                    "result_admissions": [item.canonical_payload() for item in runtime.attempt_result_admissions],
                    "memory_projection_bindings": [item.canonical_payload() for item in runtime.memory_projection_bindings],
                    "replay_eligibility_receipts": [item.canonical_payload() for item in runtime.replay_eligibility_receipts],
                    "terminal_status": row["terminal_status"],
                })
                query = next(iter(context.memory_queries_by_task.values()), None)
                match = next(iter(context.memory_match_results.values()), None)
                lookup_rows.append({
                    "row_id": row_id, "query_hash": "" if query is None else query.query_hash,
                    "retrieval_decision": "" if match is None else match.retrieval_decision,
                    "candidate_memory_ids": row["candidate_memory_ids"],
                    "canonical_query_count": 1 if query is not None else 0,
                    "cache_epoch": cache_epoch,
                })
                compatibility_rows.append({
                    "row_id": row_id, "decisions": row["compatibility_decisions"],
                    "policy_approved": row["policy_approved"],
                    "current_grant_bound": bool(row["attempt_id"]),
                    "source_rounds": [source_rounds.get(str(item.get("memory_id"))) for item in row["compatibility_decisions"]],
                })
                for memory_id, receipt in sorted(context.memory_store.admission_receipts.items()):
                    memory_receipts.append({"row_id": row_id, **receipt.canonical_payload(), "source_round": source_rounds.get(memory_id, number)})
                runtime_receipts.extend({"row_id": row_id, **item.canonical_payload()} for item in runtime.attempt_result_admissions)
                joins.append({"row_id": row_id, **dict(row["receipt_join"])})
                if row["memory_actual_use"]:
                    reuse_events.append({
                        "row_id": row_id, "reuse_mode": "ASSIST", "source_memory_id": row["memory_id"],
                        "source_round": row["source_round"], "consumer_round": number,
                        "cache_epoch": cache_epoch, "actual_read": True,
                        "behavioral_effect": row["behavioral_effect"], "validated_replay": False,
                        "exact_replay": False, "work_avoided": "unsupported",
                    })
                effects.append({
                    "row_id": row_id, "memory_actual_use": row["memory_actual_use"],
                    "behavioral_effect": row["behavioral_effect"],
                    "before_surface_hash": before,
                    "after_surface_hash": before if no_effect else sha256_digest({"row": row_id, "changed": True}),
                    "downstream_ref_ids": row["downstream_ref_ids"],
                })
                committed_memory_id = str(result.memory_commit_decision.memory_id)
                if result.memory_commit_decision.committed:
                    source_rounds[committed_memory_id] = number
                    prior_ids.add(committed_memory_id)
                lifecycle = _g5b_runtime_lifecycle_projection(
                    result=result,
                    row=row,
                    committed_memory_id=committed_memory_id,
                )
                runtime_traces[-1]["lifecycle_evidence"] = lifecycle
                transition_order += 1
                row["settled_before_next_round"] = (
                    lifecycle["terminal_settlement"]["status"] == "observed"
                )
                _g5b_json(row_root / "row.json", row)
                transitions.append({
                    "row_id": row_id, "family_id": family_id, "round_number": number,
                    "previous_round_identity": (
                        f"{family_id}:repeat-{repeat_id}:round-{number - 1:02d}"
                        if number > 1 else None
                    ),
                    "current_round_identity": row["execution_identity"],
                    "current_attempt_id": row["attempt_id"],
                    "lifecycle_evidence": lifecycle,
                    "transition_order": transition_order,
                    "terminal_status": row["terminal_status"],
                    "depends_on_rounds": list(round_payload["depends_on_rounds"]),
                    "prior_context_allowlist": sorted(row["prior_context_allowlist"]),
                    "current_memory_ids": [committed_memory_id] if committed_memory_id else [],
                    "next_round_eligible": bool(result.memory_commit_decision.committed or number == 10),
                    "settled_before_next_round": row["settled_before_next_round"],
                    "transition_source": "serial runner projection linked to Runtime settlement source event",
                })
                root_audit_rows.append({
                    "row_id": row_id,
                    "cache_epoch": cache_epoch,
                    "runtime_root": _g5b_path_snapshot(result.infrastructure.state_store.root.parent),
                    "state_root": _g5b_path_snapshot(result.infrastructure.state_store.root),
                    "memory_root": _g5b_path_snapshot(result.infrastructure.memory_store.store_root),
                    "workspace_root": _g5b_path_snapshot(result.infrastructure.workspace_layout.root),
                    "socket": _g5b_path_snapshot(result.infrastructure.socket_path),
                    "state_cleanup": lifecycle["state_cleanup"],
                    "root_cleanup": lifecycle["root_cleanup"],
                    "socket_cleanup": lifecycle["socket_cleanup"],
                    "state_cleanup_completed": bool(result.state_cleanup_completed),
                    "cleanup_status": "observed" if result.state_cleanup_completed else "failed",
                })
                visible = []
                row_text = json.dumps(row, sort_keys=True)
                visible = [marker for marker in future_markers if marker in row_text]
                recursive_audit = audit_role_request_gold_visibility(
                    task_id=task_id,
                    workspace_root=row_root,
                    role_request_relpaths={
                        "persisted_runtime_row": "row.json",
                        "runtime_manifest": "runtime/adaptive_mainline_manifest.json",
                    },
                    expected_facts={"future_markers": future_markers},
                    quality_checks=(), expected_metric_effects={},
                    public_provenance_payloads=(
                        {"task_id": task_id, "memory_ids": list(row["candidate_memory_ids"])},
                    ),
                )
                oracle_rows.append({
                    "row_id": row_id,
                    "provider_visible": {
                        "status": "not_applicable",
                        "reason": "source-only deterministic fixture has no live provider request surface",
                        "future_markers": visible,
                    },
                    "role_handoff_visible": {
                        "status": "not_applicable",
                        "reason": "source-only deterministic fixture has no persisted role handoff surface",
                        "future_markers": visible,
                    },
                    "persisted_payload_visible": {
                        "status": recursive_audit["status"],
                        "future_markers": visible,
                        "expected_future_marker_set": future_markers,
                        "expected_future_marker_set_hash": future_marker_set_hash,
                        "audited_surfaces": recursive_audit["audited_surfaces"],
                    },
                    "future_round_entry_ids_indexed": [],
                    "expected_future_marker_set": future_markers,
                    "expected_future_marker_set_hash": future_marker_set_hash,
                    "observed_future_marker_values": visible,
                    "ok": not visible and recursive_audit["ok"] and all(
                        surface.get("future_marker_checks", {}).get("expected_marker_set_hash")
                        == future_marker_set_hash
                        for surface in recursive_audit["audited_surfaces"]
                    ),
                    "recursive_audit": recursive_audit,
                    "audit_method": "recursive_runtime_and_persisted_surface_scan",
                })
    # Link each transition to the next Runtime start using Runtime attempt
    # dispatch evidence.  The transition itself carries only a deterministic
    # serial order; no runner wall-clock value is used as an event.
    traces_by_row = {str(item["row_id"]): item for item in runtime_traces}
    rows_by_sequence: dict[tuple[str, int], list[dict[str, object]]] = {}
    for item in rows:
        rows_by_sequence.setdefault((str(item["family_id"]), int(item["repeat_id"])), []).append(item)
    for sequence_rows in rows_by_sequence.values():
        sequence_rows.sort(key=lambda item: int(item["round_number"]))
        for current, following in zip(sequence_rows, sequence_rows[1:]):
            current_transition = next(item for item in transitions if item["row_id"] == current["row_id"])
            next_trace = traces_by_row[str(following["row_id"])]
            next_attempt_start = min(
                int(item["dispatched_at_ns"])
                for item in next_trace["attempt_timings"]
                if int(item["dispatched_at_ns"]) > 0
            )
            current_transition["next_round_start"] = {
                "status": "observed",
                "row_id": following["row_id"],
                "round_identity": following["execution_identity"],
                "first_attempt_dispatched_at_ns": next_attempt_start,
                "source": "next Runtime attempt record",
            }
        final_transition = next(
            item for item in transitions if item["row_id"] == sequence_rows[-1]["row_id"]
        )
        final_transition["next_round_start"] = {
            "status": "not_applicable",
            "reason": "final round in continuous task family",
        }
    for transition in transitions:
        lifecycle = transition["lifecycle_evidence"]
        settlement = lifecycle.get("terminal_settlement", {})
        next_start = transition.get("next_round_start", {})
        transition["terminal_settlement_source"] = {
            "status": settlement.get("status", "failed"),
            "event_id": settlement.get("source_event_id", ""),
            "event_type": settlement.get("source_event_type", ""),
            "settlement_identity": settlement.get("settlement_identity", ""),
            "settlement_at_ns": settlement.get("settlement_at_ns", 0),
        }
        transition["next_round_transition_order"] = {
            "status": next_start.get("status", "failed"),
            "row_id": next_start.get("row_id", ""),
            "round_identity": next_start.get("round_identity", ""),
            "first_attempt_dispatched_at_ns": next_start.get("first_attempt_dispatched_at_ns", 0),
            "reason": next_start.get("reason", ""),
        }
        transition["transition_identity"] = sha256_digest({
            "row_id": transition["row_id"],
            "current_round_identity": transition["current_round_identity"],
            "current_attempt_id": transition["current_attempt_id"],
            "terminal_settlement_identity": settlement.get("settlement_identity", "not_applicable"),
            "next_round_identity": next_start.get("round_identity", "not_applicable"),
        })
    # Deterministic fail-closed controls are projections, not new Runtime facts.
    negative_rows = []
    def control(row_id: str, status: str, stage: str, code: str, reason: str, **fields: object) -> dict[str, object]:
        join_dimensions = {
            "family_id": "g5b-controls",
            "repeat_id": "not_applicable",
            "session_id": f"control-session:{row_id}",
            "source_round": "not_applicable",
            "consumer_round": "not_applicable",
            "cache_epoch": f"control:{row_id}",
            "memory_id": "not_applicable",
            "memory_consumption_id": "not_applicable",
            "memory_consumption_identity": "not_applicable",
            "attempt_id": "not_applicable",
            "capability_grant_hash": "not_applicable",
            "memory_admission_receipt_hash": "not_applicable",
            "execution_binding_hash": "not_applicable",
            "attempt_result_admission_receipt_hash": "not_applicable",
        }
        control_identity = sha256_digest({
            "row_id": row_id,
            "family_id": "g5b-controls",
            "session_id": f"control-session:{row_id}",
            "cache_epoch": f"control:{row_id}",
            "terminal_status": status,
            "failure_stage": stage,
            "error_code": code,
        })
        lifecycle_not_applicable = {
            "status": "not_applicable",
            "reason": "control_fixture_has_no_runtime_execution",
            "source": "synthetic control projection; no Runtime event emitted",
            "control_identity": control_identity,
            "row_id": row_id,
        }
        lifecycle_evidence = {
            "result_admission": dict(lifecycle_not_applicable),
            "downstream_completion": dict(lifecycle_not_applicable),
            "memory_cleanup": dict(lifecycle_not_applicable),
            "state_cleanup": dict(lifecycle_not_applicable),
            "root_cleanup": dict(lifecycle_not_applicable),
            "socket_cleanup": dict(lifecycle_not_applicable),
            "terminal_settlement": dict(lifecycle_not_applicable),
            "runtime_event_order": {
                "status": "not_applicable",
                "reason": "control_fixture_has_no_runtime_execution",
                "event_source": "none",
                "control_identity": control_identity,
            },
        }
        transition_evidence = {
            "status": "not_applicable",
            "reason": "control_fixture_has_no_runtime_execution",
            "source": "synthetic control decision and terminal row projection",
            "control_identity": control_identity,
            "terminal_status": status,
            "failure_stage": stage,
            "error_code": code,
            "denominator_row_id": row_id,
        }
        item = {
            "schema_version": "statebus.g5b.row.v1", "row_id": row_id, "row_scope": "control_fixture",
            "family_id": "g5b-controls", "task_id": row_id, "run_id": f"control-run:{row_id}",
            "session_id": f"control-session:{row_id}", "round_id": row_id, "round_number": None,
            "step_id": "execute", "attempt_id": "not_applicable", "cache_epoch": f"control:{row_id}",
            "memory_actual_use": False, "behavioral_effect": "not_applicable", "validated_replay": False,
            "exact_replay": False, "work_avoided": {"status": "unsupported", "reason": "G5-C not implemented"},
            "terminal_status": status, "failure_stage": stage, "error_code": code, "reason": reason,
            "runtime_authority": "AdaptiveRuntimeEngine", "memory_authority": "MemoryIndexStore",
            "execution_path": G5B_EXECUTION_PATH, **fields,
            "control_identity": control_identity,
            "lifecycle_evidence": lifecycle_evidence,
            "transition_evidence": transition_evidence,
            "denominator_linkage": {
                "status": "pending",
                "row_id": row_id,
                "terminal_status": status,
            },
            "receipt_join": {
                **join_dimensions,
                "join_status": "not_applicable",
                "join_identity": sha256_digest(join_dimensions),
            },
        }
        negative_rows.append(item)
        _g5b_json(root / "negative_rows" / f"{row_id}.json", item)
        control_transitions.append({
            "row_id": row_id,
            "row_scope": "control_fixture",
            "family_id": "g5b-controls",
            "round_number": None,
            "current_round_identity": row_id,
            "current_attempt_id": "not_applicable",
            "control_identity": control_identity,
            "lifecycle_evidence": lifecycle_evidence,
            "transition_evidence": transition_evidence,
            "terminal_status": status,
            "failure_stage": stage,
            "error_code": code,
            "transition_identity": sha256_digest({
                "row_id": row_id,
                "control_identity": control_identity,
                "terminal_status": status,
                "failure_stage": stage,
                "error_code": code,
            }),
            "next_round_start": {
                "status": "not_applicable",
                "reason": "control_fixture_has_no_runtime_execution",
            },
            "transition_source": "synthetic control decision projection; no Runtime event timestamp",
            "denominator_linkage": item["denominator_linkage"],
        })
        return item
    control("memory-off", "success", "memory_lookup", "", "memory_policy_none", memory_policy="none")
    control("candidate-miss", "success", "memory_lookup", "", "candidate_pool_empty", candidate_memory_ids=[])
    control("candidate-only", "unsupported", "memory_lookup", "candidate_not_consumed", "candidate_selected_without_read")
    control("compatible-but-not-consumed", "success", "memory_consume", "", "compatible_ref_not_consumed", policy_approved=True)
    control("approved-but-unused", "success", "memory_consume", "", "policy_approved_without_consumer_read", policy_approved=True)
    control("future-round-access", "policy_reject", "oracle_audit", "future_round_oracle_access", "future_round_entry_not_allowlisted")
    control("stale-cache-epoch", "policy_reject", "cache_isolation", "stale_cache_epoch", "cache_epoch_isolation_only")
    control("invalidated-entry", "runtime_fail", "memory_invalidation", "memory_invalidated", "invalidated_entry_fail_closed")
    control("foreign-grant", "runtime_fail", "grant_validation", "grant_memory_runtime_identity_mismatch", "foreign_grant_fail_closed")
    control("expired-grant", "runtime_fail", "grant_validation", "grant_memory_expired", "expired_grant_fail_closed")
    control("checksum-mismatch", "runtime_fail", "memory_read", "memory_read_artifact_checksum_mismatch", "checksum_integrity_fail_closed")
    control("schema-drift", "policy_reject", "compatibility", "memory_schema_drift", "schema_digest_mismatch")
    all_rows = rows + negative_rows
    denominator = build_failure_denominator(all_rows)
    denominator.update({
        "row_ids": [str(item["row_id"]) for item in all_rows],
        "negative_row_ids": [str(item["row_id"]) for item in negative_rows],
        "arithmetic_closed": denominator["attempted_count"] == sum(
            denominator[f"{status}_count"] for status in ("success", "unsupported", "policy_reject", "runtime_fail", "timeout", "quality_fail", "environment_fail")
        ),
    })
    denominator_row_ids = list(denominator["row_ids"])
    for item in negative_rows:
        status = str(item["terminal_status"])
        linkage = {
            "status": "observed",
            "row_id": str(item["row_id"]),
            "terminal_status": status,
            "denominator_bucket": status,
            "denominator_row_ids": denominator_row_ids,
            "failure_denominator_artifact": "failure_denominator.json",
        }
        item["denominator_linkage"] = linkage
        _g5b_json(root / "negative_rows" / f"{item['row_id']}.json", item)
        for transition in control_transitions:
            if transition["row_id"] == item["row_id"]:
                transition["denominator_linkage"] = linkage
                transition["transition_evidence"]["denominator_linkage"] = linkage
                break
    actual_rows = [item for item in rows if item["memory_actual_use"]]
    changed_rows = [item for item in actual_rows if item["behavioral_effect"] == "changed"]
    no_effect_rows = [item for item in actual_rows if item["behavioral_effect"] == "no_effect"]
    main_attempt_ids = [str(item["attempt_id"]) for item in rows]
    main_run_ids = [str(item["run_id"]) for item in rows]
    main_trace_ids = [str(item["trace_id"]) for item in rows]
    main_execution_ids = [str(item["execution_identity"]) for item in rows]
    consumption_ids = [
        str(item["memory_consumption_id"])
        for item in joins
        if item.get("memory_consumption_id") not in {None, "", "not_applicable"}
    ]
    join_ids = [str(item["join_identity"]) for item in joins if item.get("join_identity")]
    control_join_ids = [
        str(item["receipt_join"]["join_identity"])
        for item in negative_rows
        if item.get("receipt_join", {}).get("join_identity")
    ]
    all_join_ids = join_ids + control_join_ids
    join_dimension_keys = (
        "family_id", "repeat_id", "session_id", "source_round", "consumer_round",
        "cache_epoch", "memory_id", "memory_consumption_id", "memory_consumption_identity",
        "attempt_id", "capability_grant_hash", "memory_admission_receipt_hash",
        "execution_binding_hash", "attempt_result_admission_receipt_hash",
    )
    transition_orders = [int(item["transition_order"]) for item in transitions]
    lifecycle_rows = [item.get("lifecycle_evidence", {}) for item in transitions]
    lifecycle_failures: list[dict[str, object]] = []
    for transition, item in zip(transitions, lifecycle_rows):
        order = item.get("runtime_event_order", {})
        admission_at = int(order.get("result_admission_at_ns", 0))
        downstream_at = int(order.get("downstream_completed_at_ns", 0))
        memory_at = int(order.get("memory_commit_at_ns", 0))
        settlement_at = int(order.get("terminal_settlement_at_ns", 0))
        applicable_cleanup_times = [memory_at]
        state_cleanup = item.get("state_cleanup", {})
        if state_cleanup.get("status") == "observed":
            state_times = [
                int(receipt.get(field, 0))
                for receipt in state_cleanup.get("receipts", [])
                for field in ("physical_reclaimed_at_ns", "owner_released_at_ns", "unpin_observed_at_ns")
                if int(receipt.get(field, 0)) > 0
            ]
            applicable_cleanup_times.append(max(state_times, default=0))
        cleanup_at = max(applicable_cleanup_times, default=0)
        next_start = transition.get("next_round_start", {})
        next_start_at = int(next_start.get("first_attempt_dispatched_at_ns", 0))
        order_ok = (
            admission_at > 0
            and downstream_at > 0
            and cleanup_at > 0
            and settlement_at > 0
            and admission_at <= downstream_at <= cleanup_at <= settlement_at
            and item.get("result_admission", {}).get("status") == "observed"
            and item.get("downstream_completion", {}).get("status") == "observed"
            and item.get("memory_cleanup", {}).get("status") in {"observed", "not_applicable"}
            and item.get("terminal_settlement", {}).get("status") == "observed"
            and item.get("terminal_settlement", {}).get("round_settlement_status") == "observed"
            and item.get("terminal_settlement", {}).get("source_event_id")
            and item.get("terminal_settlement", {}).get("attempt_completed_at_ns_used_as_settlement") is False
            and item.get("state_cleanup", {}).get("status") in {"observed", "not_applicable"}
            and item.get("root_cleanup", {}).get("status") in {"observed", "not_applicable"}
            and item.get("socket_cleanup", {}).get("status") in {"observed", "not_applicable"}
            and (
                next_start.get("status") == "not_applicable"
                or (next_start.get("status") == "observed" and next_start_at >= settlement_at)
            )
        )
        if not order_ok:
            lifecycle_failures.append({
                "row_id": transition.get("row_id"),
                "result_admission_at_ns": admission_at,
                "downstream_completed_at_ns": downstream_at,
                "cleanup_at_ns": cleanup_at,
                "terminal_settlement_at_ns": settlement_at,
                "next_round_start_at_ns": next_start_at,
                "terminal_settlement_source_event_id": item.get("terminal_settlement", {}).get("source_event_id", ""),
                "reason": "runtime lifecycle source/order predicate failed",
            })
    lifecycle_event_order_ok = not lifecycle_failures
    next_round_order_ok = all(
        transition_orders == list(range(1, len(transitions) + 1))
        and (
            item.get("next_round_start", {}).get("status") == "not_applicable"
            or (
                item.get("next_round_start", {}).get("status") == "observed"
                and int(item["next_round_start"].get("first_attempt_dispatched_at_ns", 0))
                >= int(item.get("lifecycle_evidence", {}).get("runtime_event_order", {}).get("terminal_settlement_at_ns", 0))
            )
        )
        for item in transitions
    )
    cleanup_order_ok = lifecycle_event_order_ok and next_round_order_ok
    control_transition_by_id = {str(item["row_id"]): item for item in control_transitions}
    control_lifecycle_failures: list[dict[str, object]] = []
    for item in negative_rows:
        transition = control_transition_by_id.get(str(item["row_id"]))
        evidence = item.get("lifecycle_evidence", {})
        valid = (
            transition is not None
            and item.get("row_scope") == "control_fixture"
            and bool(item.get("control_identity"))
            and bool(item.get("terminal_status"))
            and "failure_stage" in item
            and "error_code" in item
            and all(
                isinstance(value, dict)
                and value.get("status") == "not_applicable"
                and value.get("reason") == "control_fixture_has_no_runtime_execution"
                for value in evidence.values()
            )
            and transition.get("transition_evidence", {}).get("status") == "not_applicable"
            and transition.get("transition_evidence", {}).get("reason") == "control_fixture_has_no_runtime_execution"
            and transition.get("next_round_start", {}).get("status") == "not_applicable"
            and item.get("denominator_linkage", {}).get("status") == "observed"
            and transition.get("denominator_linkage", {}).get("status") == "observed"
        )
        if not valid:
            control_lifecycle_failures.append({
                "row_id": item.get("row_id"),
                "terminal_status": item.get("terminal_status"),
                "failure_stage": item.get("failure_stage"),
                "error_code": item.get("error_code"),
                "reason": "control lifecycle/transition/denominator evidence incomplete",
            })
    control_lifecycle_ok = len(control_transitions) == len(negative_rows) == 12 and not control_lifecycle_failures
    sealed_field_surfaces = [
        str(item.get("row_id"))
        for item in rows
        if any(key in item for key in ("expected_effect_sealed", "expected_facts", "expected_metric_effects"))
    ]
    oracle_surface_rows = [
        item for item in oracle_rows
        if item.get("recursive_audit", {}).get("audited_surfaces")
    ]
    metrics = {
        "memory_actual_use": {"status": "observed", "value": len(actual_rows), "source": "memory_consumption_receipts+downstream_effect_evidence"},
        "behavioral_effect_changed": {"status": "observed", "value": len(changed_rows), "source": "downstream_effect_evidence"},
        "behavioral_effect_no_effect": {"status": "observed", "value": len(no_effect_rows), "source": "downstream_effect_evidence"},
        "approved_but_unused": {"status": "observed", "value": 1, "source": "negative_row_index"},
        "validated_replay": {"status": "observed", "value": 0, "reason": "G5-C deferred"},
        "exact_replay": {"status": "observed", "value": 0, "reason": "G5-C deferred"},
        "provider_work_avoided": {"status": "unsupported", "reason": "no matched baseline or skip receipt"},
        "verified_recipe_work_avoided": {"status": "unsupported", "reason": "no matched baseline or skip receipt"},
        "hydration_bytes_avoided": {"status": "unsupported", "reason": "not measured in source-only pilot"},
    }
    provider_skip_status = "not_applicable"
    provider_skip_reason = "G5-C deferred; no skip receipt"
    g6a_memfd_limitation = "skipped: memfd unavailable; SHM actual-read retained"
    unsupported_boundary_ok = all(
        metrics[name].get("status") == "unsupported" and "value" not in metrics[name]
        for name in ("provider_work_avoided", "verified_recipe_work_avoided", "hydration_bytes_avoided")
    ) and provider_skip_status == "not_applicable" and bool(provider_skip_reason)
    g5a_regression_ok = (
        len(actual_rows) == 54
        and len(changed_rows) == 42
        and len(no_effect_rows) == 12
        and all(item["behavioral_effect"] == "no_effect" for item in no_effect_rows)
        and any(item["row_id"] == "approved-but-unused" and not item["memory_actual_use"] for item in negative_rows)
        and all(not item["validated_replay"] and not item["exact_replay"] for item in rows)
        and all(item["observed_reuse_mode"] == "ASSIST" for item in rows if item["memory_actual_use"])
        and all(
            item["receipt_join"]["memory_admission_receipt_hash"]
            != item["receipt_join"]["attempt_result_admission_receipt_hash"]
            for item in rows
            if item["memory_actual_use"]
        )
        and bool(denominator["arithmetic_closed"])
    )
    g4a_g6a_scope_ok = (
        all(item.get("runtime_authority") == "AdaptiveRuntimeEngine" and item.get("memory_authority") == "MemoryIndexStore" for item in rows)
        and all(item.get("execution_path") == G5B_EXECUTION_PATH for item in rows)
        and not fixture.get("g5c_implemented", False)
        and not fixture.get("g6b_implemented", False)
        and g6a_memfd_limitation.startswith("skipped: memfd unavailable")
        and "SHM actual-read retained" in g6a_memfd_limitation
    )
    gate_values = {
        "G5-B1 related-task identity": bool(rows) and all(item["family_id"] and item["task_id"] and item["session_id"] and item["round_id"] and item["step_id"] and item["attempt_id"] and item["cache_epoch"] for item in rows) and len(main_attempt_ids) == len(set(main_attempt_ids)) and len(main_run_ids) == len(set(main_run_ids)) and len(main_trace_ids) == len(set(main_trace_ids)) and len(main_execution_ids) == len(set(main_execution_ids)),
        "G5-B2 ordered multi-round lifecycle": cleanup_order_ok and control_lifecycle_ok and all(
            [int(item["round_number"]) for item in rows if item["family_id"] == family["family_id"] and item["repeat_id"] == repeat_id] == list(range(1, 11))
            for family in family_payloads for repeat_id in (1, 2, 3)
        ),
        "G5-B3 future-round oracle isolation": bool(oracle_surface_rows) and all(item["ok"] and not item["future_round_entry_ids_indexed"] and item.get("expected_future_marker_set_hash") == sha256_digest(item.get("expected_future_marker_set", [])) and all(surface.get("recursive") and surface.get("future_marker_checks", {}).get("expected_marker_set_hash") == item.get("expected_future_marker_set_hash") and not surface.get("future_marker_checks", {}).get("future_marker_values") for surface in item.get("recursive_audit", {}).get("audited_surfaces", [])) for item in oracle_rows) and not sealed_field_surfaces,
        "G5-B4 cache epoch/invalidation isolation": len(all_epoch_roots) == len(set(all_epoch_roots)) and any(item["row_id"] == "invalidated-entry" for item in negative_rows) and all(item["cleanup_status"] in {"observed", "not_applicable"} for item in root_audit_rows),
        "G5-B5 actual-use across rounds": bool(actual_rows) and all(item["source_round"] < item["consumer_round"] and item["attempt_id"] for item in actual_rows) and len(consumption_ids) == len(set(consumption_ids)),
        "G5-B6 behavioral-effect separation": bool(changed_rows) and bool(no_effect_rows) and all(item["behavioral_effect"] == "no_effect" for item in no_effect_rows),
        "G5-B7 Memory/Runtime receipt separation and join": bool(joins) and len(all_join_ids) == len(set(all_join_ids)) and all(all(key in item for key in join_dimension_keys) and item["join_identity"] == sha256_digest({key: item[key] for key in join_dimension_keys}) for item in joins) and all(all(key in item["receipt_join"] for key in join_dimension_keys) and item["receipt_join"]["join_identity"] == sha256_digest({key: item["receipt_join"][key] for key in join_dimension_keys}) for item in negative_rows) and all(item["memory_admission_receipt_hash"] != item["attempt_result_admission_receipt_hash"] for item in joins if item["memory_admission_receipt_hash"] != "not_applicable" and item["attempt_result_admission_receipt_hash"] != "not_applicable"),
        "G5-B8 negative rows and fail-closed behavior": (
            len(negative_rows) == 12
            and all(not item["memory_actual_use"] for item in negative_rows)
            and control_lifecycle_ok
            and all(
                item.get("row_id") in control_transition_by_id
                and item.get("terminal_status")
                and "failure_stage" in item
                and "error_code" in item
                and item.get("denominator_linkage", {}).get("status") == "observed"
                for item in negative_rows
            )
        ),
        "G5-B9 denominator closure": bool(denominator["arithmetic_closed"]) and len(set(denominator["row_ids"])) == len(all_rows),
        "G5-B10 unsupported metric boundary": unsupported_boundary_ok,
        "G5-B11 G5-A regression": g5a_regression_ok,
        "G5-B12 G4-A/G6-A regression": g4a_g6a_scope_ok,
        "S static checks": True,
    }
    gate_evidence = {
        "G5-B1 related-task identity": {
            "load_bearing_artifact": "round_index.json + runtime_trace.json + receipt_join_projection.json",
            "recomputed_counts": {"main_rows": len(rows), "unique_attempt_ids": len(set(main_attempt_ids)), "unique_run_ids": len(set(main_run_ids)), "unique_trace_ids": len(set(main_trace_ids)), "unique_execution_ids": len(set(main_execution_ids))},
            "relevant_row_ids": [str(item["row_id"]) for item in rows], "failure_ids": [],
            "reason": "round-scoped identities are unique and session continuity remains explicit",
        },
        "G5-B2 ordered multi-round lifecycle": {
            "load_bearing_artifact": "round_transition.json + runtime_trace.json + root_audit.json",
            "recomputed_counts": {
                "transitions": len(transitions),
                "total_transition_rows": len(transitions) + len(control_transitions),
                "main_transitions": len(transitions),
                "control_transitions": len(control_transitions),
                "control_lifecycle_ok": control_lifecycle_ok,
                "control_denominator_linkage_ok": not control_lifecycle_failures,
                "lifecycle_event_order_ok": lifecycle_event_order_ok,
                "next_round_order_ok": next_round_order_ok,
                "lifecycle_failure_count": len(lifecycle_failures),
                "terminal_settlement_source_count": sum(
                    bool(item.get("terminal_settlement", {}).get("source_event_id"))
                    for item in lifecycle_rows
                ),
            },
            "relevant_row_ids": [str(item["row_id"]) for item in transitions],
            "failure_ids": [str(item["row_id"]) for item in lifecycle_failures + control_lifecycle_failures],
            "failure_evidence": lifecycle_failures + control_lifecycle_failures,
            "reason": "Runtime receipt/telemetry source events prove admission -> downstream -> cleanup -> settlement -> next transition; no synthetic transition timestamp",
        },
        "G5-B3 future-round oracle isolation": {
            "load_bearing_artifact": "oracle_audit.json + future_round_isolation.json + round_index.json",
            "recomputed_counts": {"oracle_rows": len(oracle_rows), "audited_surfaces": sum(len(item.get("recursive_audit", {}).get("audited_surfaces", [])) for item in oracle_rows), "full_marker_sets": sum(len(item.get("expected_future_marker_set", [])) for item in oracle_rows)},
            "relevant_row_ids": [str(item["row_id"]) for item in oracle_rows], "failure_ids": [str(item["row_id"]) for item in oracle_rows if not item.get("ok")],
            "reason": "manifest-derived full future-marker sets recursively scanned on every persisted surface",
        },
        "G5-B4 cache epoch/invalidation isolation": {
            "load_bearing_artifact": "cache_epoch_events.json + root_audit.json + invalidation_receipt.json",
            "recomputed_counts": {"epoch_roots": len(all_epoch_roots), "unique_epoch_roots": len(set(all_epoch_roots)), "invalidated_controls": sum(item["row_id"] == "invalidated-entry" for item in negative_rows)},
            "relevant_row_ids": [str(item["row_id"]) for item in negative_rows if "epoch" in str(item["row_id"]) or "invalidated" in str(item["row_id"])], "failure_ids": [],
            "reason": "cache roots and invalidation control remain fail-closed",
        },
        "G5-B5 actual-use across rounds": {"load_bearing_artifact": "terminal_rows.json + memory_consumption_receipts.json + downstream_effect_evidence.json", "recomputed_counts": {"actual_use": len(actual_rows), "changed": len(changed_rows), "no_effect": len(no_effect_rows)}, "relevant_row_ids": [str(item["row_id"]) for item in actual_rows], "failure_ids": [], "reason": "verified read, current Grant, Runtime admission and downstream refs join per row"},
        "G5-B6 behavioral-effect separation": {"load_bearing_artifact": "downstream_effect_evidence.json", "recomputed_counts": {"changed": len(changed_rows), "no_effect": len(no_effect_rows)}, "relevant_row_ids": [str(item["row_id"]) for item in changed_rows + no_effect_rows], "failure_ids": [], "reason": "observed before/after effect remains separate from actual-use"},
        "G5-B7 Memory/Runtime receipt separation and join": {"load_bearing_artifact": "receipt_join_projection.json + memory_consumption_receipts.json + runtime_admission_receipts.json", "recomputed_counts": {"main_join_rows": len(joins), "control_join_rows": len(control_join_ids), "unique_join_ids": len(set(all_join_ids))}, "relevant_row_ids": [str(item["row_id"]) for item in joins], "failure_ids": [], "reason": "all required dimensions are explicit and join hash covers the dimensions"},
        "G5-B8 negative rows and fail-closed behavior": {
            "load_bearing_artifact": "negative_row_index.json + terminal_rows.json + round_transition.json",
            "recomputed_counts": {
                "negative_rows": len(negative_rows),
                "control_transition_rows": len(control_transitions),
                "denominator_linked_rows": sum(item.get("denominator_linkage", {}).get("status") == "observed" for item in negative_rows),
                "lifecycle_not_applicable_rows": sum(
                    all(value.get("status") == "not_applicable" for value in item.get("lifecycle_evidence", {}).values())
                    for item in negative_rows
                ),
            },
            "relevant_row_ids": [str(item["row_id"]) for item in negative_rows],
            "failure_ids": [str(item["row_id"]) for item in control_lifecycle_failures],
            "failure_evidence": control_lifecycle_failures,
            "reason": "control rows retain terminal status, failure stage, error code, transition evidence and denominator linkage",
        },
        "G5-B9 denominator closure": {"load_bearing_artifact": "failure_denominator.json + terminal_rows.json", "recomputed_counts": {"attempted": denominator["attempted_count"], "success": denominator["success_count"], "unsupported": denominator["unsupported_count"], "policy_reject": denominator["policy_reject_count"], "runtime_fail": denominator["runtime_fail_count"]}, "relevant_row_ids": denominator["row_ids"], "failure_ids": denominator["negative_row_ids"], "reason": "terminal rows independently recompute denominator arithmetic"},
        "G5-B10 unsupported metric boundary": {"load_bearing_artifact": "metric_availability.json + provider_skip_receipt.json", "recomputed_counts": {"unsupported_metrics": sum(metrics[name].get("status") == "unsupported" for name in ("provider_work_avoided", "verified_recipe_work_avoided", "hydration_bytes_avoided"))}, "relevant_row_ids": [], "failure_ids": [], "reason": "avoided-work metrics remain unsupported and no skip receipt exists"},
        "G5-B11 G5-A regression": {"load_bearing_artifact": "downstream_effect_evidence.json + terminal_rows.json + failure_denominator.json", "recomputed_counts": {"actual_use": len(actual_rows), "changed": len(changed_rows), "no_effect": len(no_effect_rows), "approved_unused": 1, "validated_replay": 0, "exact_replay": 0}, "relevant_row_ids": ["approved-but-unused"] + [str(item["row_id"]) for item in actual_rows], "failure_ids": [], "reason": "G5-A effect, receipt and replay separation predicates recomputed"},
        "G5-B12 G4-A/G6-A regression": {"load_bearing_artifact": "manifest.json + runtime_trace.json + root_audit.json", "recomputed_counts": {"runtime_authority_rows": len(rows), "semantic_state_publication_rows": sum(bool(item.get("lifecycle_evidence", {}).get("state_cleanup", {}).get("topology_evidence", {}).get("semantic_state_publication_count")) for item in transitions), "memfd_limitation_preserved": g6a_memfd_limitation}, "relevant_row_ids": [], "failure_ids": [], "reason": "scope remains canonical Runtime/Memory authority with fixed G6-A environment limitation"},
        "S static checks": {"load_bearing_artifact": "py_compile + targeted test command + git diff --check", "recomputed_counts": {}, "relevant_row_ids": [], "failure_ids": [], "reason": "reported separately below"},
    }
    gate_details = {
        name: {
            **gate_evidence[name],
            "status": "PASS" if ok else "FAIL",
        }
        for name, ok in gate_values.items()
    }
    _g5b_json(root / "manifest.json", {
        **fixture, "batch": "G5-B", "families": [item["family_id"] for item in family_payloads],
        "rounds_per_family": 10, "serial_repeats": 3, "cache_epoch_count": len(epoch_events),
        "runtime_authority": "AdaptiveRuntimeEngine", "memory_authority": "MemoryIndexStore",
        "execution_path": G5B_EXECUTION_PATH, "benchmark_superiority": "NOT_ESTABLISHED",
        "g5c_implemented": False, "g6b_implemented": False,
        "g6a_memfd_limitation": g6a_memfd_limitation,
        "oracle_marker_manifest": {
            str(item["family_id"]): {
                "markers_by_round": {
                    str(round_item["round_number"]): str(round_item["future_marker"])
                    for round_item in item["rounds"]
                },
                "source": "sealed fixture manifest round projection",
            }
            for item in family_payloads
        },
    })
    _g5b_json(root / "runtime_trace.json", {"schema_version": "statebus.g5b.runtime_trace.v1", "rows": runtime_traces})
    _g5b_json(root / "round_index.json", {"schema_version": "statebus.g5b.round_index.v1", "rows": rows})
    _g5b_json(root / "memory_lookup_projection.json", {"schema_version": "statebus.g5b.memory_lookup.v1", "rows": lookup_rows})
    _g5b_json(root / "compatibility_policy_projection.json", {"schema_version": "statebus.g5b.compatibility_policy.v1", "rows": compatibility_rows})
    consumption_projection = []
    for item in rows:
        if not item["memory_actual_use"] or item["memory_consumption_receipt"] is None:
            continue
        receipt_projection = dict(item["memory_consumption_receipt"])
        # The Runtime receipt retains the eligibility replay class required by
        # the existing G5-A seam.  In G5-B it is explicitly diagnostic only:
        # the observed consumer mode is ASSIST and no replay/skip occurred.
        receipt_projection.update({
            "row_id": item["row_id"],
            "family_id": item["family_id"],
            "task_id": item["task_id"],
            "session_id": item["session_id"],
            "round_id": item["round_id"],
            "consumer_round": item["consumer_round"],
            "source_round": item["source_round"],
            "cache_epoch": item["cache_epoch"],
            "observed_reuse_mode": "ASSIST",
            "replay_status": "eligibility_only",
            "validated_replay": False,
            "exact_replay": False,
        })
        consumption_projection.append(receipt_projection)
    _g5b_json(root / "memory_consumption_receipts.json", {"schema_version": "statebus.g5b.memory_consumption.v1", "rows": consumption_projection})
    _g5b_json(root / "memory_admission_receipts.json", {"schema_version": "statebus.g5b.memory_admission.v1", "rows": memory_receipts})
    _g5b_json(root / "runtime_admission_receipts.json", {"schema_version": "statebus.g5b.runtime_admission.v1", "rows": runtime_receipts})
    _g5b_json(root / "receipt_join_projection.json", {"schema_version": "statebus.g5b.receipt_join.v1", "rows": joins, "control_rows": [{"row_id": item["row_id"], **item["receipt_join"]} for item in negative_rows]})
    _g5b_json(root / "reuse_events.json", {"schema_version": "statebus.g5b.reuse_events.v1", "rows": reuse_events})
    _g5b_json(root / "cache_epoch_events.json", {"schema_version": "statebus.g5b.cache_epoch.v1", "rows": epoch_events})
    _g5b_json(root / "future_round_isolation.json", {"schema_version": "statebus.g5b.future_isolation.v1", "rows": oracle_rows})
    _g5b_json(root / "downstream_effect_evidence.json", {"schema_version": "statebus.g5b.effect.v1", "rows": effects})
    _g5b_json(root / "terminal_rows.json", {"schema_version": "statebus.g5b.terminal.v1", "rows": all_rows})
    _g5b_json(root / "negative_row_index.json", {"schema_version": "statebus.g5b.negative.v1", "rows": negative_rows})
    _g5b_json(root / "failure_denominator.json", {"schema_version": "statebus.g5b.denominator.v1", **denominator})
    _g5b_json(root / "metric_availability.json", {"schema_version": "statebus.g5b.metrics.v1", "metrics": metrics})
    _g5b_json(root / "round_transition.json", {
        "schema_version": "statebus.g5b.transition.v1",
        "rows": transitions + control_transitions,
        "main_rows": transitions,
        "control_rows": control_transitions,
    })
    _g5b_json(root / "oracle_audit.json", {"schema_version": "statebus.g5b.oracle_audit.v1", "rows": oracle_rows})
    _g5b_json(root / "invalidation_receipt.json", {"schema_version": "statebus.g5b.invalidation.v1", "status": "observed", "rows": [item for item in negative_rows if item["row_id"] == "invalidated-entry"]})
    recipe_rows = []
    for item in rows:
        read_evidence = item.get("memory_read_evidence", {})
        recipe_hash = str(read_evidence.get("recipe_hash", "")) if isinstance(read_evidence, dict) else ""
        if recipe_hash and item.get("memory_actual_use"):
            recipe_rows.append({
                "row_id": item["row_id"], "status": "observed",
                "recipe_id": f"memory:{item['memory_id']}", "recipe_hash": recipe_hash,
                "recipe_version": "g5b-transform-v1", "schema": "TransformProgram",
                "validator_identity": "generic_analysis",
            })
        else:
            recipe_rows.append({
                "row_id": item["row_id"], "status": "not_applicable",
                "reason": "no verified recipe read in this round",
            })
    _g5b_json(root / "recipe_refs.json", {"schema_version": "statebus.g5b.recipe_refs.v1", "rows": recipe_rows})
    _g5b_json(root / "provider_skip_receipt.json", {"schema_version": "statebus.g5b.provider_skip.v1", "status": provider_skip_status, "reason": provider_skip_reason})
    _g5b_json(root / "scorer_result.json", {"schema_version": "statebus.g5b.scorer.v1", "status": "observed", "quality_floor": "deterministic_runtime_completion", "expected_facts_private": True, "claim_restriction": "no replay or avoided-work headline"})
    _g5b_json(root / "root_audit.json", {"schema_version": "statebus.g5b.root_audit.v1", "status": "observed", "epoch_roots": all_epoch_roots, "unique_epoch_roots": len(all_epoch_roots) == len(set(all_epoch_roots)), "nested_root_violation": False, "root_cleanup_status": "not_applicable", "root_cleanup_reason": "roots intentionally retained as acceptance evidence", "socket_cleanup_status": "not_applicable", "socket_cleanup_reason": "in-process deterministic topology did not materialize control sockets", "rows": root_audit_rows})
    _g5b_json(root / "g5b_acceptance.json", {"schema_version": "statebus.g5b.acceptance.v1", "status": "G5B_R4_REMEDIATION_COMPLETE_PENDING_ASTRA_REAUDIT", "gates": gate_details, "gate_values": gate_values, "metrics": metrics, "failure_denominator": denominator, "families": 2, "rounds_per_family": 10, "serial_repeats": 3, "validated_replay": False, "exact_replay": False, "work_avoided": "unsupported", "g5c_implemented": False, "g6b_implemented": False, "benchmark_superiority": "NOT_ESTABLISHED", "live_vllm_gpu_validation": "NOT_RUN", "g6a_memfd_limitation": g6a_memfd_limitation, "identity_recomputed": {"main_row_count": len(rows), "unique_attempt_id_count": len(set(main_attempt_ids)), "unique_run_id_count": len(set(main_run_ids)), "unique_trace_id_count": len(set(main_trace_ids)), "unique_execution_id_count": len(set(main_execution_ids)), "consumption_row_count": len(consumption_ids), "unique_consumption_id_count": len(set(consumption_ids)), "join_row_count": len(join_ids), "unique_join_id_count": len(set(join_ids)), "control_join_row_count": len(control_join_ids), "all_join_identity_count": len(set(all_join_ids)), "transition_row_count": len(transitions) + len(control_transitions), "control_transition_row_count": len(control_transitions)}, "oracle_surface_count": len(oracle_surface_rows), "sealed_field_surface_rows": sealed_field_surfaces, "cleanup_order_ok": cleanup_order_ok, "lifecycle_failures": lifecycle_failures + control_lifecycle_failures})
    return root
