from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import replace
import os
from pathlib import Path
import time
from typing import Any

from statebus.benchmark.continuous_runner import (
    _c2c_baseline_pairing,
    _c2c_pair_key,
    _g5b_make_request,
    _g5b_terminal_status,
)
from statebus.utils import sha256_digest, stable_json_dumps


VARIANTS = ("memory_off", "validated_replay")
DEFAULT_ROUNDS_PER_FAMILY = 3
DETERMINISTIC_SEED_BASE = 6_240_000
FAMILY_CONFIGS: tuple[dict[str, object], ...] = (
    {
        "family_id": "cross_period_financial",
        "task_family": "financial_report_analysis",
        "base_value": 1_000.0,
        "no_effect_rounds": (2,),
    },
    {
        "family_id": "incident_diagnosis",
        "task_family": "incident_diagnosis",
        "base_value": 2_000.0,
        "no_effect_rounds": (3,),
    },
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.monotonic_ns()}")
    temporary.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")
    temporary.replace(path)


def _prepare_output_root(output_root: Path) -> None:
    if output_root.exists():
        if not output_root.is_dir() or any(output_root.iterdir()):
            raise FileExistsError(f"p4_output_root_must_be_new_or_empty:{output_root}")
        return
    output_root.mkdir(parents=True, exist_ok=False)


def _planned_pairs(rounds_per_family: int) -> tuple[dict[str, object], ...]:
    pairs: list[dict[str, object]] = []
    for family_index, family in enumerate(FAMILY_CONFIGS, start=1):
        family_id = str(family["family_id"])
        no_effect_rounds = {int(item) for item in family["no_effect_rounds"]}
        for round_number in range(1, rounds_per_family + 1):
            pairs.append(
                {
                    "pair_id": f"{family_id}:round-{round_number:02d}",
                    "family_id": family_id,
                    "task_family": str(family["task_family"]),
                    "round_number": round_number,
                    "repeat_id": 1,
                    "deterministic_seed": (
                        DETERMINISTIC_SEED_BASE
                        + family_index * 1_000
                        + round_number
                    ),
                    "expected_behavioral_effect": (
                        "no_effect" if round_number in no_effect_rounds else "changed"
                    ),
                    "current_value": float(family["base_value"]) + round_number,
                }
            )
    return tuple(pairs)


def _manifest(rounds_per_family: int) -> dict[str, object]:
    pairs = _planned_pairs(rounds_per_family)
    return {
        "schema_version": "statebus.p4.memory_ablation_manifest.v1",
        "scope": "deterministic_runtime_matched_pair_validation",
        "families": [dict(item) for item in FAMILY_CONFIGS],
        "rounds_per_family": rounds_per_family,
        "producer_warmup_count": len(FAMILY_CONFIGS),
        "planned_pair_count": len(pairs),
        "planned_measured_row_count": len(pairs) * len(VARIANTS),
        "variants": list(VARIANTS),
        "pair_fields": [
            "task_contract_hash",
            "input_lineage_hashes",
            "quality_contract_hash",
            "deterministic_seed",
            "family_id",
            "round_number",
            "repeat_id",
            "current_value",
            "source_payload_sha256",
        ],
        "producer_rows_in_denominator": False,
        "provider_boundary": "deterministic bound Runtime provider",
        "claim_boundary": (
            "provider boundary avoidance, Memory actual-use/effect, quality, and "
            "receipt closure only; no live-vLLM, latency, throughput, or superiority claim"
        ),
        "feature_flags": {
            "semantic_state": False,
            "codeact": False,
            "apc_prefix": False,
            "kv_hidden_latent": False,
        },
        "negative_controls": [
            {
                "name": name,
                "headline_denominator": False,
                "status": (
                    "executed" if name == "no_effect_round" else "retained_by_runtime_targeted_tests"
                ),
            }
            for name in (
                "incompatible",
                "stale",
                "schema_drift",
                "wrong_task_or_role",
                "no_admission_receipt",
                "expired_artifact",
                "no_effect_round",
            )
        ],
        "planned_pairs": [dict(item) for item in pairs],
    }


def _bind_deterministic_provider(
    request: Any,
    boundary_rows: list[dict[str, object]],
) -> Any:
    from statebus.contracts import TransformProgram, TransformStep
    from statebus.runtime.provider_registry import (
        ExecutionProviderRegistry,
        PhysicalProviderImplementation,
        project_legacy_provider,
    )
    from statebus.runtime.role_providers import ProviderCandidate

    providers = ExecutionProviderRegistry()
    for capability_id in ("g5b-retrieve-memory", "g5b-execute-recipe"):
        descriptor = project_legacy_provider(
            request.registry.get(capability_id),
            provider_id=f"provider-{capability_id}",
        )
        providers.register(descriptor)
        providers.register_implementation(
            PhysicalProviderImplementation.from_descriptor(descriptor)
        )

    def provider(provider_request: Any) -> ProviderCandidate:
        grant = provider_request.bound_grant.grant
        invocation_id = f"p4-provider-invocation:{grant.attempt_id}"
        request_hash = sha256_digest(
            {
                "runtime_identity": provider_request.runtime_identity.canonical_payload(),
                "grant": grant.canonical_payload(),
                "provider_input_refs": list(provider_request.provider_input_refs),
            }
        )
        program = TransformProgram(
            program_id=f"p4-provider-program:{grant.attempt_id}",
            input_artifact_refs=(grant.input_ref_ids[0],),
            operations=(TransformStep("select", {"columns": ["value"]}),),
            output_contract_version=grant.output_contract_version,
        )
        evidence = {
            "status": "observed",
            "invocation_status": "completed",
            "provider_id": provider_request.bound_grant.provider_id,
            "provider_kind": "deterministic_bound_transform_provider",
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
        provider_registry=providers,
        bindings=replace(
            request.bindings,
            bound_provider_handlers={"g5b-execute-recipe": provider},
            g5c_c0_artifact_root=Path(request.runtime_root).parent / "g5c-c0",
            g5c_c1_artifact_root=Path(request.runtime_root).parent / "g5c-c1",
        ),
    )


def _run_runtime(request: Any) -> Any:
    from statebus.runtime.driver import RuntimeDriver

    return RuntimeDriver().run_mode("adaptive_bounded", adaptive_request=request)


def _before_surface_hash(request: Any, task_id: str) -> str:
    execute_step = next(
        step for step in request.propose_plan().steps if step.step_id == "execute"
    )
    source_ref_id = f"source:{task_id}"
    source_artifact = request.bindings.artifacts[source_ref_id].artifact
    return sha256_digest(
        {
            "step": execute_step.canonical_payload(),
            "input_ref_id": source_ref_id,
            "input_hashes": [source_artifact.blob_hash],
        }
    )


def _execute_projection(result: Any, request: Any, value: float) -> dict[str, object]:
    execute_grant = next(
        (
            item.grant
            for item in result.runtime.bound_grants
            if item.grant.step_id == "execute"
        ),
        None,
    )
    execute_binding = next(
        (
            item
            for item in result.runtime.execution_bindings
            if item.step_id == "execute"
        ),
        None,
    )
    execute_admission = next(
        (
            item
            for item in result.runtime.attempt_result_admissions
            if item.step_id == "execute"
        ),
        None,
    )
    execute_dispatch = next(
        (
            item
            for item in result.runtime.dispatches
            if item.step_id == "execute"
        ),
        None,
    )
    output_ref_id = (
        ""
        if execute_dispatch is None or not execute_dispatch.output_refs
        else execute_dispatch.output_refs[0]
    )
    stored_output = result.context.artifacts.get(output_ref_id)
    output_rows = (
        [] if stored_output is None else [dict(item) for item in stored_output.rows]
    )
    verification = result.context.artifact_verification_receipts.get(output_ref_id)
    quality_hash = (
        ""
        if verification is None or not verification.validator_report_hashes
        else verification.validator_report_hashes[0]
    )
    terminal_status, failure_stage, reason = _g5b_terminal_status(result)
    current_input_recomputed = output_rows == [{"value": value}]
    if terminal_status == "success" and not current_input_recomputed:
        terminal_status = "quality_fail"
        failure_stage = "execute"
        reason = "current_input_result_mismatch"
    return {
        "execute_grant": execute_grant,
        "execute_binding": execute_binding,
        "execute_admission": execute_admission,
        "output_ref_id": output_ref_id,
        "output_rows": output_rows,
        "verification": verification,
        "quality_hash": quality_hash,
        "terminal_status": terminal_status,
        "failure_stage": failure_stage,
        "reason": reason,
        "current_input_recomputed": current_input_recomputed,
    }


def _memory_projection(
    result: Any,
    *,
    prior_memory_ids: set[str],
    source_round_by_memory_id: dict[str, int],
    round_number: int,
) -> dict[str, object]:
    match = next(iter(result.context.memory_match_results.values()), None)
    query = next(iter(result.context.memory_queries_by_task.values()), None)
    record = next(iter(result.context.memory_consumption_records), None)
    memory_id = "" if record is None else str(record.memory_id)
    candidate_ids = (
        []
        if match is None or match.candidate_pool is None
        else list(match.candidate_pool.candidate_memory_ids)
    )
    decisions = (
        []
        if match is None
        else [item.canonical_payload() for item in match.compatibility_decisions]
    )
    decision = next(
        (item for item in decisions if str(item.get("memory_id", "")) == memory_id),
        None,
    )
    compatible = bool(decision and decision.get("verdict") != "incompatible")
    policy_approved = bool(decision and decision.get("policy_approved"))
    admitted = result.context.memory_store.get_admitted(memory_id) if memory_id else None
    commit = None if admitted is None else admitted[0]
    admission = None if admitted is None else admitted[1]
    read_evidence = (
        result.context.memory_read_evidence_by_id.get(memory_id, {})
        if memory_id
        else {}
    )
    execute_grant = next(
        (
            item.grant
            for item in result.runtime.bound_grants
            if item.grant.step_id == "execute"
        ),
        None,
    )
    execute_binding = next(
        (
            item
            for item in result.runtime.execution_bindings
            if item.step_id == "execute"
        ),
        None,
    )
    execute_admission = next(
        (
            item
            for item in result.runtime.attempt_result_admissions
            if item.step_id == "execute"
        ),
        None,
    )
    eligibility = next(
        (
            item
            for item in result.runtime.replay_eligibility_receipts
            if item.memory_id == memory_id
        ),
        None,
    )
    observation = next(
        (
            dict(item)
            for item in result.context.replay_observations
            if str(item.get("memory_id", "")) == memory_id
        ),
        {},
    )
    source_round = source_round_by_memory_id.get(memory_id)
    actual_use = bool(
        record is not None
        and commit is not None
        and admission is not None
        and read_evidence.get("artifact_read") == "observed"
        and bool(record.attempt_result_admission_receipt_hash)
        and bool(record.downstream_ref_ids)
        and execute_grant is not None
        and execute_binding is not None
        and execute_admission is not None
        and record.capability_grant_hash == execute_grant.grant_hash
        and record.attempt_result_admission_receipt_hash
        == execute_admission.receipt_hash
        and record.consumer_attempt_id == execute_grant.attempt_id
        and memory_id in prior_memory_ids
        and source_round is not None
        and source_round < round_number
        and compatible
        and policy_approved
    )
    validated_replay = bool(
        actual_use
        and getattr(record.replay_class, "value", record.replay_class)
        == "validated_replay"
        and eligibility is not None
        and record.replay_eligibility_receipt_hash == eligibility.receipt_hash
        and observation.get("provider_invocation_status") == "not_started"
        and observation.get("attempt_result_admission_receipt_hash")
        == execute_admission.receipt_hash
    )
    return {
        "query": None if query is None else query.canonical_payload(),
        "candidate": bool(candidate_ids),
        "candidate_memory_ids": candidate_ids,
        "compatibility_decisions": decisions,
        "compatible": compatible,
        "policy_approved": policy_approved,
        "actual_use": actual_use,
        "memory_id": memory_id,
        "source_round": source_round,
        "behavioral_effect": (
            "not_applicable" if not actual_use else str(record.behavioral_effect)
        ),
        "validated_replay": validated_replay,
        "recipe_recomputed": bool(record and record.recipe_recomputed),
        "memory_read_evidence": dict(read_evidence),
        "memory_consumption_receipt": (
            None if record is None else record.canonical_payload()
        ),
        "memory_admission_receipt": (
            None if admission is None else admission.canonical_payload()
        ),
        "replay_eligibility_receipt": (
            None if eligibility is None else eligibility.canonical_payload()
        ),
        "provider_not_started_observation": observation,
    }


def _project_row(
    *,
    result: Any,
    request: Any,
    pair: Mapping[str, object],
    variant: str,
    cache_epoch: str,
    provider_boundary_rows: list[dict[str, object]],
    prior_memory_ids: set[str],
    source_round_by_memory_id: dict[str, int],
) -> dict[str, object]:
    value = float(pair["current_value"])
    task_id = request.task_id
    source_artifact = request.bindings.artifacts[f"source:{task_id}"].artifact
    execution = _execute_projection(result, request, value)
    verification = execution["verification"]
    execute_grant = execution["execute_grant"]
    execute_binding = execution["execute_binding"]
    execute_admission = execution["execute_admission"]
    quality_hash = str(execution["quality_hash"])
    quality_passed = bool(
        quality_hash
        and execution["terminal_status"] == "success"
        and execution["current_input_recomputed"]
        and execute_admission is not None
    )
    memory = (
        {
            "query": None,
            "candidate": False,
            "candidate_memory_ids": [],
            "compatibility_decisions": [],
            "compatible": False,
            "policy_approved": False,
            "actual_use": False,
            "memory_id": "",
            "source_round": None,
            "behavioral_effect": "not_applicable",
            "validated_replay": False,
            "recipe_recomputed": False,
            "memory_read_evidence": {},
            "memory_consumption_receipt": None,
            "memory_admission_receipt": None,
            "replay_eligibility_receipt": None,
            "provider_not_started_observation": {},
        }
        if variant == "memory_off"
        else _memory_projection(
            result,
            prior_memory_ids=prior_memory_ids,
            source_round_by_memory_id=source_round_by_memory_id,
            round_number=int(pair["round_number"]),
        )
    )
    row = {
        "schema_version": "statebus.p4.memory_ablation_row.v1",
        "row_id": f"{pair['pair_id']}:{variant}",
        "pair_id": pair["pair_id"],
        "variant": variant,
        "lane": variant,
        "provenance_scope": (
            "p4_memory_off_runtime"
            if variant == "memory_off"
            else "p4_validated_replay_runtime"
        ),
        "family_id": pair["family_id"],
        "round_number": pair["round_number"],
        "repeat_id": pair["repeat_id"],
        "deterministic_seed": pair["deterministic_seed"],
        "expected_behavioral_effect": pair["expected_behavioral_effect"],
        "current_value": value,
        "source_payload_sha256": source_artifact.blob_hash,
        "task_contract_hash": result.runtime_identity.task_contract.contract_hash,
        "input_lineage_hashes": [source_artifact.blob_hash],
        "quality_contract_hash": sha256_digest(
            {
                "validator_ids": (
                    [] if verification is None else list(verification.validator_ids)
                ),
                "output_contract_version": (
                    ""
                    if execute_grant is None
                    else execute_grant.output_contract_version
                ),
            }
        ),
        "runtime_root": str(request.runtime_root),
        "workspace_root": str(request.workspace_root),
        "memory_root": str(request.memory_store_root),
        "session_id": result.runtime_identity.session_id,
        "run_id": result.runtime_identity.run_id,
        "attempt_id": "" if execute_grant is None else execute_grant.attempt_id,
        "cache_epoch": cache_epoch,
        "memory_policy": "off" if variant == "memory_off" else "validated_replay",
        "runtime_memory_policy": "none" if variant == "memory_off" else "validated_replay",
        "terminal_status": execution["terminal_status"],
        "failure_stage": execution["failure_stage"],
        "reason": execution["reason"],
        "provider_boundary_call_count": len(provider_boundary_rows),
        "current_input_recomputed": execution["current_input_recomputed"],
        "quality_evidence": {
            "status": "observed" if quality_hash else "unsupported",
            "passed": quality_passed,
            "report_hash": quality_hash,
            "current_input_recomputed": execution["current_input_recomputed"],
            "observed_output_rows": execution["output_rows"],
        },
        "result_admission": {
            "status": "observed" if execute_admission is not None else "unsupported",
            "receipt_hash": (
                "" if execute_admission is None else execute_admission.receipt_hash
            ),
            "step_id": "execute",
        },
        "candidate": memory["candidate"],
        "candidate_memory_ids": memory["candidate_memory_ids"],
        "compatible": memory["compatible"],
        "compatibility_decisions": memory["compatibility_decisions"],
        "policy_approved": memory["policy_approved"],
        "actual_use": memory["actual_use"],
        "behavioral_effect": memory["behavioral_effect"],
        "validated_replay": memory["validated_replay"],
        "recipe_recomputed": memory["recipe_recomputed"],
        "query": memory["query"],
        "memory_id": memory["memory_id"],
        "source_round": memory["source_round"],
        "memory_read_evidence": memory["memory_read_evidence"],
        "memory_consumption_receipt": memory["memory_consumption_receipt"],
        "memory_admission_receipt": memory["memory_admission_receipt"],
        "replay_eligibility_receipt": memory["replay_eligibility_receipt"],
        "capability_grant": (
            None if execute_grant is None else execute_grant.canonical_payload()
        ),
        "execution_binding": (
            None if execute_binding is None else execute_binding.canonical_payload()
        ),
        "provider_not_started_observation": memory[
            "provider_not_started_observation"
        ],
        "work_avoided": {
            "status": "pending_matched_pair_validation",
            "value": None,
        },
        "verified_recipe_work_avoided": {
            "status": "unsupported",
            "value": None,
            "reason": "recipe_step_skip_not_observed",
        },
        "feature_flags": {
            "semantic_state": False,
            "memory": variant != "memory_off",
            "codeact": False,
            "apc_prefix": False,
            "kv_hidden_latent": False,
        },
        "runtime_authority": "AdaptiveRuntimeEngine",
        "memory_authority": "MemoryIndexStore",
    }
    if variant == "memory_off":
        row["provider_invocation_evidence"] = (
            dict(provider_boundary_rows[0])
            if len(provider_boundary_rows) == 1
            else {}
        )
    row["pair_key"] = _c2c_pair_key(row)
    return row


def _producer_projection(
    *,
    result: Any,
    request: Any,
    family_id: str,
    provider_boundary_rows: list[dict[str, object]],
) -> dict[str, object]:
    decision = result.memory_commit_decision
    terminal_status, failure_stage, reason = _g5b_terminal_status(result)
    return {
        "schema_version": "statebus.p4.memory_producer_row.v1",
        "row_id": f"{family_id}:producer-warmup",
        "family_id": family_id,
        "row_scope": "producer_warmup",
        "denominator_eligible": False,
        "runtime_root": str(request.runtime_root),
        "workspace_root": str(request.workspace_root),
        "memory_root": str(request.memory_store_root),
        "terminal_status": terminal_status,
        "failure_stage": failure_stage,
        "reason": reason,
        "provider_boundary_call_count": len(provider_boundary_rows),
        "provider_invocation_evidence": (
            dict(provider_boundary_rows[0])
            if len(provider_boundary_rows) == 1
            else {}
        ),
        "memory_commit": decision.canonical_payload(),
    }


def _build_denominator(
    *,
    planned_pairs: tuple[dict[str, object], ...],
    rows: list[dict[str, object]],
    producer_rows: list[dict[str, object]],
    failures: list[dict[str, object]],
    pair_projection: Mapping[str, object],
) -> dict[str, object]:
    planned_pair_ids = {str(item["pair_id"]) for item in planned_pairs}
    eligible_pair_ids = {
        f"{item.get('family_id', '')}:round-{int(item.get('round_number', 0)):02d}"
        for item in pair_projection.get("pairings", ())
        if isinstance(item, Mapping) and item.get("status") == "eligible"
    }
    rejected_pair_ids = {
        f"{item.get('family_id', '')}:round-{int(item.get('round_number', 0)):02d}"
        for item in pair_projection.get("pairings", ())
        if isinstance(item, Mapping) and item.get("status") != "eligible"
    }
    measured_failures = [
        item for item in failures if item.get("row_scope") == "measured"
    ]
    planned_row_count = len(planned_pairs) * len(VARIANTS)
    arithmetic_closed = len(rows) + len(measured_failures) == planned_row_count
    incomplete_pair_ids = sorted(planned_pair_ids.difference(eligible_pair_ids))
    return {
        "schema_version": "statebus.p4.memory_ablation_denominator.v1",
        "status": "observed" if arithmetic_closed else "unsupported",
        "planned_pairs": len(planned_pairs),
        "closed_pairs": len(eligible_pair_ids),
        "rejected_pairs": len(rejected_pair_ids),
        "incomplete_pairs": len(incomplete_pair_ids),
        "incomplete_pair_ids": incomplete_pair_ids,
        "planned_measured_rows": planned_row_count,
        "observed_measured_rows": len(rows),
        "failed_measured_rows": len(measured_failures),
        "producer_rows": len(producer_rows),
        "producer_rows_excluded": True,
        "row_ids": [str(item.get("row_id", "")) for item in rows],
        "failure_ids": [str(item.get("failure_id", "")) for item in failures],
        "arithmetic_closed": arithmetic_closed,
        "provider_pairing_arithmetic_closed": bool(
            dict(pair_projection.get("denominator", {})).get("arithmetic_closed")
        ),
    }


def _metrics(
    *,
    rows: list[dict[str, object]],
    pair_projection: Mapping[str, object],
) -> dict[str, object]:
    replay_rows = [item for item in rows if item.get("variant") == "validated_replay"]
    effects = {
        "changed": sum(item.get("behavioral_effect") == "changed" for item in replay_rows),
        "no_effect": sum(item.get("behavioral_effect") == "no_effect" for item in replay_rows),
    }
    unsupported = {
        "status": "unsupported",
        "value": None,
    }
    return {
        "schema_version": "statebus.p4.memory_ablation_metrics.v1",
        "memory_actual_use": {
            "status": "observed",
            "value": sum(bool(item.get("actual_use")) for item in replay_rows),
        },
        "validated_replay": {
            "status": "observed",
            "value": sum(bool(item.get("validated_replay")) for item in replay_rows),
        },
        "behavioral_effect": {"status": "observed", **effects},
        "provider_boundary_calls": {
            "status": "observed",
            "memory_off": sum(
                int(item.get("provider_boundary_call_count", 0))
                for item in rows
                if item.get("variant") == "memory_off"
            ),
            "validated_replay": sum(
                int(item.get("provider_boundary_call_count", 0))
                for item in replay_rows
            ),
        },
        "provider_work_avoided": dict(
            pair_projection.get(
                "provider_work_avoided",
                {
                    "status": "unsupported",
                    "value": None,
                    "reason": "no_matched_baseline_or_runtime_skip_receipt",
                },
            )
        ),
        "quality_non_regression": dict(
            pair_projection.get(
                "quality_non_regression",
                {"status": "unsupported", "reason": "no_matched_baseline"},
            )
        ),
        "verified_recipe_work_avoided": {
            **unsupported,
            "reason": "recipe_step_skip_not_observed",
        },
        "hydration_bytes_avoided": {
            **unsupported,
            "reason": "hydration_bytes_not_observed",
        },
        "embedding_work_avoided": {
            **unsupported,
            "reason": "embedding_work_not_observed",
        },
        "rerank_work_avoided": {
            **unsupported,
            "reason": "rerank_work_not_observed",
        },
        "compatibility_work_avoided": {
            **unsupported,
            "reason": "compatibility_work_not_observed",
        },
        "exact_replay": {
            **unsupported,
            "reason": "exact_replay_excluded",
        },
        "recipe_step_skip": {
            "status": "deferred",
            "value": None,
            "reason": "recipe_step_skip_excluded",
        },
        "benchmark_superiority": "NOT_ESTABLISHED",
        "statistical_superiority": "NOT_ESTABLISHED",
    }


def run_memory_ablation(
    *,
    output_root: Path,
    rounds_per_family: int = DEFAULT_ROUNDS_PER_FAMILY,
) -> dict[str, object]:
    if rounds_per_family < 1:
        raise ValueError("p4_rounds_per_family_must_be_positive")
    output_root = Path(output_root)
    _prepare_output_root(output_root)
    manifest = _manifest(rounds_per_family)
    planned_pairs = _planned_pairs(rounds_per_family)
    _write_json(output_root / "manifest.json", manifest)

    rows: list[dict[str, object]] = []
    producer_rows: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    family_pairs: dict[str, list[dict[str, object]]] = {}
    for pair in planned_pairs:
        family_pairs.setdefault(str(pair["family_id"]), []).append(dict(pair))

    for family in FAMILY_CONFIGS:
        family_id = str(family["family_id"])
        task_family = str(family["task_family"])
        family_root = output_root / "runtime" / family_id
        memory_root = family_root / "shared-memory"
        known_memory_ids: set[str] = set()
        source_round_by_memory_id: dict[str, int] = {}

        producer_task_id = f"p4:{family_id}:producer"
        producer_boundary: list[dict[str, object]] = []
        producer_request = _bind_deterministic_provider(
            _g5b_make_request(
                row_root=family_root / "producer",
                family_id=family_id,
                task_family=task_family,
                task_id=producer_task_id,
                session_id=f"p4-producer-session:{family_id}",
                run_id=f"p4-producer-run:{family_id}",
                value=float(family["base_value"]),
                memory_root=memory_root,
                memory_policy="validated_replay",
            ),
            producer_boundary,
        )
        try:
            producer_result = _run_runtime(producer_request)
            producer_rows.append(
                _producer_projection(
                    result=producer_result,
                    request=producer_request,
                    family_id=family_id,
                    provider_boundary_rows=producer_boundary,
                )
            )
            if producer_result.memory_commit_decision.committed:
                memory_id = producer_result.memory_commit_decision.memory_id
                known_memory_ids.add(memory_id)
                source_round_by_memory_id[memory_id] = 0
        except Exception as exc:  # benchmark failure accounting is explicit
            failures.append(
                {
                    "failure_id": f"{family_id}:producer:{type(exc).__name__}",
                    "row_scope": "producer",
                    "family_id": family_id,
                    "variant": "producer",
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )
            for pair in family_pairs[family_id]:
                for variant in VARIANTS:
                    failures.append(
                        {
                            "failure_id": f"{pair['pair_id']}:{variant}:not_started",
                            "row_scope": "measured",
                            "pair_id": pair["pair_id"],
                            "family_id": family_id,
                            "round_number": pair["round_number"],
                            "variant": variant,
                            "error": "family_producer_failed",
                        }
                    )
            continue

        for pair in family_pairs[family_id]:
            round_number = int(pair["round_number"])
            value = float(pair["current_value"])
            pair_slug = f"round-{round_number:02d}"
            for variant in VARIANTS:
                task_id = f"p4:{family_id}:{pair_slug}:{variant}"
                boundary_rows: list[dict[str, object]] = []
                row_root = family_root / "measured" / pair_slug / variant
                baseline = variant == "memory_off"
                request = _g5b_make_request(
                    row_root=row_root,
                    family_id=family_id,
                    task_family=task_family,
                    task_id=task_id,
                    session_id=f"p4-session:{family_id}:{pair_slug}:{variant}",
                    run_id=f"p4-run:{family_id}:{pair_slug}:{variant}",
                    value=value,
                    memory_root=(row_root / "cold-memory") if baseline else memory_root,
                    memory_policy="none" if baseline else "validated_replay",
                    memory_after_surface_hash_by_memory_id={},
                )
                prior_ids = set() if baseline else set(known_memory_ids)
                if (
                    not baseline
                    and pair["expected_behavioral_effect"] == "no_effect"
                ):
                    before_hash = _before_surface_hash(request, task_id)
                    request = replace(
                        request,
                        bindings=replace(
                            request.bindings,
                            memory_after_surface_hash_by_memory_id={
                                memory_id: before_hash for memory_id in prior_ids
                            },
                        ),
                    )
                request = _bind_deterministic_provider(request, boundary_rows)
                try:
                    result = _run_runtime(request)
                    row = _project_row(
                        result=result,
                        request=request,
                        pair=pair,
                        variant=variant,
                        cache_epoch=f"p4-{variant}-epoch:{family_id}:{pair_slug}",
                        provider_boundary_rows=boundary_rows,
                        prior_memory_ids=prior_ids,
                        source_round_by_memory_id=source_round_by_memory_id,
                    )
                    rows.append(row)
                    _write_json(row_root / "measurement_row.json", row)
                    if not baseline and result.memory_commit_decision.committed:
                        memory_id = result.memory_commit_decision.memory_id
                        known_memory_ids.add(memory_id)
                        source_round_by_memory_id[memory_id] = round_number
                except Exception as exc:  # benchmark failure accounting is explicit
                    failures.append(
                        {
                            "failure_id": f"{pair['pair_id']}:{variant}:{type(exc).__name__}",
                            "row_scope": "measured",
                            "pair_id": pair["pair_id"],
                            "family_id": family_id,
                            "round_number": round_number,
                            "variant": variant,
                            "error": f"{type(exc).__name__}:{exc}",
                        }
                    )

    baseline_rows = [item for item in rows if item["variant"] == "memory_off"]
    replay_rows = [item for item in rows if item["variant"] == "validated_replay"]
    pair_projection = _c2c_baseline_pairing(baseline_rows, replay_rows)
    denominator = _build_denominator(
        planned_pairs=planned_pairs,
        rows=rows,
        producer_rows=producer_rows,
        failures=failures,
        pair_projection=pair_projection,
    )
    metrics = _metrics(rows=rows, pair_projection=pair_projection)

    rows_by_pair: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        rows_by_pair.setdefault(str(row["pair_id"]), []).append(row)
    checks = {
        "planned_exact_set": (
            len(rows) == int(manifest["planned_measured_row_count"])
            and {str(item["pair_id"]) for item in rows} == {
                str(item["pair_id"]) for item in planned_pairs
            }
        ),
        "producer_warmups_complete_and_excluded": (
            len(producer_rows) == len(FAMILY_CONFIGS)
            and denominator["producer_rows_excluded"] is True
            and all(item["provider_boundary_call_count"] == 1 for item in producer_rows)
        ),
        "matched_variants_complete": all(
            {item["variant"] for item in group} == set(VARIANTS)
            for group in rows_by_pair.values()
        ) and len(rows_by_pair) == len(planned_pairs),
        "pair_inputs_identical": all(
            len(
                {
                    (
                        item["task_contract_hash"],
                        tuple(item["input_lineage_hashes"]),
                        item["quality_contract_hash"],
                        item["deterministic_seed"],
                        item["current_value"],
                        item["source_payload_sha256"],
                    )
                    for item in group
                }
            )
            == 1
            for group in rows_by_pair.values()
        ),
        "provider_boundary_matched": (
            all(item["provider_boundary_call_count"] == 1 for item in baseline_rows)
            and all(item["provider_boundary_call_count"] == 0 for item in replay_rows)
        ),
        "memory_funnel_closed": all(
            item["candidate"]
            and item["compatible"]
            and item["policy_approved"]
            and item["actual_use"]
            and item["validated_replay"]
            for item in replay_rows
        ),
        "current_input_and_quality_closed": all(
            item["current_input_recomputed"]
            and dict(item["quality_evidence"])["passed"]
            and dict(item["result_admission"])["status"] == "observed"
            for item in rows
        ),
        "effect_controls_observed": (
            metrics["behavioral_effect"]["changed"] > 0
            and metrics["behavioral_effect"]["no_effect"] > 0
            and all(
                item["behavioral_effect"] == item["expected_behavioral_effect"]
                for item in replay_rows
            )
        ),
        "denominator_closed": (
            denominator["arithmetic_closed"]
            and denominator["provider_pairing_arithmetic_closed"]
            and denominator["closed_pairs"] == denominator["planned_pairs"]
        ),
        "provider_work_avoidance_receipt_backed": (
            metrics["provider_work_avoided"].get("status") == "observed"
            and metrics["provider_work_avoided"].get("value")
            == denominator["closed_pairs"]
        ),
        "unsupported_metrics_not_zero_filled": all(
            metrics[name]["status"] == "unsupported"
            and metrics[name]["value"] is None
            for name in (
                "verified_recipe_work_avoided",
                "hydration_bytes_avoided",
                "embedding_work_avoided",
                "rerank_work_avoided",
                "compatibility_work_avoided",
                "exact_replay",
            )
        ),
    }
    ok = not failures and all(checks.values())
    acceptance = {
        "schema_version": "statebus.p4.memory_ablation_acceptance.v1",
        "status": "passed" if ok else "failed",
        "ok": ok,
        "checks": checks,
        "denominator": denominator,
        "metrics": metrics,
        "formal_campaign_executed": False,
        "live_vllm_validation": "NOT_RUN",
        "benchmark_superiority": "NOT_ESTABLISHED",
        "statistical_superiority": "NOT_ESTABLISHED",
    }

    _write_json(output_root / "producer_rows.json", producer_rows)
    _write_json(output_root / "rows.json", rows)
    _write_json(output_root / "pair_projection.json", pair_projection)
    _write_json(output_root / "denominator.json", denominator)
    _write_json(output_root / "metrics.json", metrics)
    _write_json(output_root / "failures.json", failures)
    _write_json(output_root / "acceptance.json", acceptance)
    return {
        **acceptance,
        "output_root": str(output_root),
        "row_count": len(rows),
        "producer_row_count": len(producer_rows),
        "failure_count": len(failures),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the deterministic P4 Memory matched-pair ablation."
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--rounds-per-family",
        type=int,
        default=DEFAULT_ROUNDS_PER_FAMILY,
    )
    args = parser.parse_args()
    summary = run_memory_ablation(
        output_root=args.output_root,
        rounds_per_family=args.rounds_per_family,
    )
    print(stable_json_dumps(summary))
    if not summary["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
