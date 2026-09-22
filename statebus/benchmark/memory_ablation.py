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
                    "executed"
                    if name in {
                        "no_effect_round",
                        "recipe_hash_mismatch",
                        "capability_mismatch",
                        "output_contract_mismatch",
                    }
                    else "retained_by_runtime_targeted_tests"
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
                "recipe_hash_mismatch",
                "capability_mismatch",
                "output_contract_mismatch",
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
        "recipe_step_status": (
            "not_applicable" if record is None else record.recipe_step_status
        ),
        "skipped_generation_step_count": (
            0 if record is None else record.skipped_generation_step_count
        ),
        "skipped_llm_call_count": (
            0 if record is None else record.skipped_llm_call_count
        ),
        "skipped_provider_call_count": (
            0 if record is None else record.skipped_provider_call_count
        ),
        "skip_evidence": {} if record is None else dict(record.skip_evidence),
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
    runtime_elapsed_ms: float,
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
            "recipe_step_status": "not_applicable",
            "skipped_generation_step_count": 0,
            "skipped_llm_call_count": 0,
            "skipped_provider_call_count": 0,
            "skip_evidence": {},
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
        "runtime_elapsed_ms": runtime_elapsed_ms,
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
        "recipe_step_status": memory["recipe_step_status"],
        "skipped_generation_step_count": memory["skipped_generation_step_count"],
        "skipped_llm_call_count": memory["skipped_llm_call_count"],
        "skipped_provider_call_count": memory["skipped_provider_call_count"],
        "skip_evidence": memory["skip_evidence"],
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
    runtime_elapsed_ms: float,
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
        "runtime_elapsed_ms": runtime_elapsed_ms,
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
    producer_rows: list[dict[str, object]],
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
    pair_by_replay_row_id = {
        str(pair.get("replay_row_id", "")): pair
        for pair in pair_projection.get("pairings", ())
        if isinstance(pair, Mapping)
    }
    recipe_evidence_rows = []
    for row in replay_rows:
        pair = pair_by_replay_row_id.get(str(row.get("row_id", "")), {})
        quality = row.get("quality_evidence", {})
        admission = row.get("result_admission", {})
        read_evidence = row.get("memory_read_evidence", {})
        skip_evidence = row.get("skip_evidence", {})
        observation = row.get("provider_not_started_observation", {})
        if (
            pair.get("status") == "eligible"
            and row.get("actual_use")
            and row.get("validated_replay")
            and row.get("recipe_step_status") == "skipped_generation"
            and int(row.get("skipped_generation_step_count", 0)) > 0
            and isinstance(row.get("memory_consumption_receipt"), Mapping)
            and bool(row.get("memory_admission_receipt"))
            and bool(row.get("replay_eligibility_receipt"))
            and isinstance(quality, Mapping)
            and quality.get("passed") is True
            and isinstance(admission, Mapping)
            and admission.get("status") == "observed"
            and isinstance(read_evidence, Mapping)
            and read_evidence.get("status") == "observed"
            and isinstance(skip_evidence, Mapping)
            and skip_evidence.get("status") == "observed"
            and isinstance(observation, Mapping)
            and observation.get("attempt_result_admission_receipt_hash")
        ):
            recipe_evidence_rows.append(row)
    if recipe_evidence_rows and len(recipe_evidence_rows) == len(replay_rows):
        verified_recipe_work_avoided = {
            "status": "observed",
            "value": len(recipe_evidence_rows),
            "eligible_matched_pair_count": len(recipe_evidence_rows),
            "reason": "current_input_recipe_reuse_skip_evidence_closed",
            "source_row_ids": [str(row.get("row_id", "")) for row in recipe_evidence_rows],
        }
    else:
        verified_recipe_work_avoided = {
            **unsupported,
            "reason": (
                "recipe_skip_evidence_incomplete"
                if recipe_evidence_rows
                else "recipe_step_skip_not_observed"
            ),
        }
    producer_setup_ms = sum(float(row.get("runtime_elapsed_ms", 0.0)) for row in producer_rows)
    baseline_elapsed = [
        float(row.get("runtime_elapsed_ms", 0.0))
        for row in rows
        if row.get("variant") == "memory_off"
    ]
    replay_elapsed = [
        float(row.get("runtime_elapsed_ms", 0.0))
        for row in replay_rows
    ]
    baseline_mean_ms = sum(baseline_elapsed) / len(baseline_elapsed) if baseline_elapsed else None
    replay_mean_ms = sum(replay_elapsed) / len(replay_elapsed) if replay_elapsed else None
    marginal_delta_ms = (
        baseline_mean_ms - replay_mean_ms
        if baseline_mean_ms is not None and replay_mean_ms is not None
        else None
    )
    break_even = (
        max(1, int(producer_setup_ms / marginal_delta_ms) + int(producer_setup_ms % marginal_delta_ms > 0))
        if marginal_delta_ms is not None and marginal_delta_ms > 0
        else None
    )
    timing = {
        "status": "observed" if baseline_elapsed and replay_elapsed else "unsupported",
        "producer_setup_ms": producer_setup_ms,
        "baseline_total_ms": sum(baseline_elapsed),
        "replay_total_ms": sum(replay_elapsed),
        "baseline_mean_ms": baseline_mean_ms,
        "marginal_replay_cost_ms": replay_mean_ms,
        "producer_inclusive_replay_cost_ms": producer_setup_ms + sum(replay_elapsed),
        "break_even_reuse_count": {
            "status": "observed" if break_even is not None else "unsupported",
            "value": break_even,
            "reason": "positive_baseline_minus_replay_delta"
            if break_even is not None
            else "replay_not_cheaper_than_baseline_or_timing_missing",
        },
        "claim_boundary": "observed elapsed accounting only; no latency superiority claim",
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
            status="unsupported",
            value=None,
            reason="provider_work_units_not_observed",
        ),
        "quality_non_regression": dict(
            pair_projection.get(
                "quality_non_regression",
                {"status": "unsupported", "reason": "no_matched_baseline"},
            )
        ),
        "verified_recipe_work_avoided": verified_recipe_work_avoided,
        "recipe_step_status_counts": {
            status: sum(row.get("recipe_step_status") == status for row in rows)
            for status in (
                "recomputed_current_input",
                "skipped_generation",
                "incompatible",
                "rejected",
                "failed",
            )
        },
        "timing_accounting": timing,
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


def _recipe_negative_controls() -> list[dict[str, object]]:
    """Run small, deterministic fail-closed checks for recipe admission.

    These rows are deliberately negative evidence.  They do not enter the
    measured pair denominator and they never manufacture an eligible replay.
    The checks exercise the same narrow recipe matcher used by the dispatcher
    so a mismatch remains recomputable from the emitted artifact.
    """

    from statebus.runtime.adaptive_dispatcher import (
        AdaptiveCapabilityDispatcher,
        AdaptiveDispatchError,
    )

    recipe = {
        "execution_kind": "transform_dsl",
        "capability_id": "g5b-execute-recipe",
        "output_contract_version": "statebus.metric_series.v1",
        "operations": [{"op": "select", "arguments": {"columns": ["value"]}}],
    }
    base_input = {
        "ref_id": "negative-memory",
        "replay_class": "validated_replay",
        "execution_recipe": recipe,
        "execution_recipe_hash": sha256_digest(recipe),
    }
    cases: tuple[tuple[str, dict[str, object], str, str], ...] = (
        (
            "recipe_hash_mismatch",
            {**base_input, "execution_recipe_hash": "stale-recipe-hash"},
            "_validated_recipe",
            "validated_replay_recipe_checksum_mismatch",
        ),
        (
            "capability_mismatch",
            {
                **base_input,
                "execution_recipe": {
                    **recipe,
                    "capability_id": "wrong-capability",
                },
                "execution_recipe_hash": sha256_digest(
                    {**recipe, "capability_id": "wrong-capability"}
                ),
            },
            "_require_validated_recipe_match",
            "validated_replay_recipe_match_missing",
        ),
        (
            "output_contract_mismatch",
            {
                **base_input,
                "execution_recipe": {
                    **recipe,
                    "output_contract_version": "statebus.other_contract.v1",
                },
                "execution_recipe_hash": sha256_digest(
                    {**recipe, "output_contract_version": "statebus.other_contract.v1"}
                ),
            },
            "_require_validated_recipe_match",
            "validated_replay_recipe_match_missing",
        ),
    )
    rows: list[dict[str, object]] = []
    for control_id, memory_input, operation, expected_error in cases:
        observed_error = ""
        terminal_status = "unexpected_success"
        try:
            replay_recipe, _memory_id = AdaptiveCapabilityDispatcher._validated_recipe(
                (memory_input,),
                execution_kind="transform_dsl",
                capability_id="g5b-execute-recipe",
                output_contract_version="statebus.metric_series.v1",
            )
            if operation == "_require_validated_recipe_match":
                AdaptiveCapabilityDispatcher._require_validated_recipe_match(
                    (memory_input,), replay_recipe
                )
            else:
                terminal_status = "unexpected_success"
        except AdaptiveDispatchError as exc:
            observed_error = str(exc)
            terminal_status = (
                "policy_reject" if observed_error == expected_error else "runtime_fail"
            )
        rows.append(
            {
                "schema_version": "statebus.p4.memory_negative_control_row.v1",
                "control_id": control_id,
                "operation": operation,
                "expected_error": expected_error,
                "observed_error": observed_error,
                "terminal_status": terminal_status,
                "fail_closed": terminal_status == "policy_reject",
                "headline_denominator": False,
                "recomputable": True,
                "authority": "AdaptiveCapabilityDispatcher",
            }
        )
    return rows


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
            started_ns = time.perf_counter_ns()
            producer_result = _run_runtime(producer_request)
            producer_elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
            producer_rows.append(
                _producer_projection(
                    result=producer_result,
                    request=producer_request,
                    family_id=family_id,
                    provider_boundary_rows=producer_boundary,
                    runtime_elapsed_ms=producer_elapsed_ms,
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
                    started_ns = time.perf_counter_ns()
                    result = _run_runtime(request)
                    runtime_elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
                    row = _project_row(
                        result=result,
                        request=request,
                        pair=pair,
                        variant=variant,
                        cache_epoch=f"p4-{variant}-epoch:{family_id}:{pair_slug}",
                        provider_boundary_rows=boundary_rows,
                        prior_memory_ids=prior_ids,
                        source_round_by_memory_id=source_round_by_memory_id,
                        runtime_elapsed_ms=runtime_elapsed_ms,
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
    provider_work_unobserved = {
        "status": "unsupported",
        "value": None,
        "reason": "provider_work_units_not_observed",
    }
    pair_projection["provider_work_avoided"] = dict(provider_work_unobserved)
    pair_metrics = dict(pair_projection.get("metrics", {}))
    pair_metrics["provider_work_avoided"] = dict(provider_work_unobserved)
    pair_projection["metrics"] = pair_metrics
    denominator = _build_denominator(
        planned_pairs=planned_pairs,
        rows=rows,
        producer_rows=producer_rows,
        failures=failures,
        pair_projection=pair_projection,
    )
    metrics = _metrics(
        rows=rows,
        pair_projection=pair_projection,
        producer_rows=producer_rows,
    )
    negative_controls = _recipe_negative_controls()

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
        "provider_work_avoided_unclaimed": (
            metrics["provider_work_avoided"].get("status") == "unsupported"
            and metrics["provider_work_avoided"].get("value") is None
            and metrics["provider_work_avoided"].get("reason")
            == "provider_work_units_not_observed"
        ),
        "verified_recipe_evidence_closed": (
            metrics["verified_recipe_work_avoided"].get("status") == "observed"
            and metrics["verified_recipe_work_avoided"].get("value")
            == len(replay_rows)
            and all(
                row.get("recipe_step_status") == "skipped_generation"
                and int(row.get("skipped_generation_step_count", 0)) == 1
                for row in replay_rows
            )
        ),
        "unsupported_metrics_not_zero_filled": all(
            metrics[name]["status"] == "unsupported"
            and metrics[name]["value"] is None
            for name in (
                "hydration_bytes_avoided",
                "embedding_work_avoided",
                "rerank_work_avoided",
                "compatibility_work_avoided",
                "exact_replay",
            )
        ),
        "negative_controls_fail_closed": all(
            bool(item.get("fail_closed"))
            and item.get("headline_denominator") is False
            for item in negative_controls
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
        "negative_control_count": len(negative_controls),
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
    _write_json(output_root / "negative_controls.json", negative_controls)
    _write_json(output_root / "failures.json", failures)
    _write_json(output_root / "acceptance.json", acceptance)
    return {
        **acceptance,
        "output_root": str(output_root),
        "row_count": len(rows),
        "producer_row_count": len(producer_rows),
        "failure_count": len(failures),
        "negative_control_count": len(negative_controls),
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
