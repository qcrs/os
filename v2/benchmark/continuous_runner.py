from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from v2.benchmark.continuous_task_family import (
    ContinuousPreRunFixture,
    ContinuousTaskFamily,
)
from v2.benchmark.contest_fairness import (
    audit_role_request_gold_visibility,
    build_continuous_fairness_manifest,
)
from v2.benchmark.kv_analysis import summarize_case_kv_reuse
from v2.benchmark.kv_prefix_schedule import KVPrefixSchedulePlan, build_kv_prefix_schedule_plan
from v2.benchmark.metric_aggregation import finalize_case_telemetry_summary
from v2.benchmark.minimal_runner import LAYER_PROFILES, LAYER_SMOKE_CONFIGS
from v2.benchmark.models import (
    BenchmarkCaseReport,
    BenchmarkContinuousCollectionReport,
    BenchmarkFamilyReport,
    BenchmarkLayer,
    BenchmarkLayerProfile,
    BenchmarkSuiteReport,
    QualityFloorResult,
)
from v2.benchmark.reporting import (
    continuous_collection_report_to_dict,
    family_report_to_dict,
    suite_report_to_dict,
    write_json_report,
    write_markdown_report,
)
from v2.benchmark.scoring import score_benchmark_output
from v2.contracts import CanonicalTaskSpec
from v2.runtime.smoke import SmokeLayerConfig, SmokeResult, run_smoke
from v2.runtime.prefix_feedback import PrefixCacheFeedbackLoop
from v2.runtime.vllm_metrics import VllmPrefixCacheCounterDelta
from v2.utils import sha256_digest


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
    root = Path("v2/benchmark/samples/continuous_task_families")
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
