from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

from runtime.llm import LLMConfig, build_llm_client
from v2.contracts import (
    AdaptiveTaskEnvelope,
    Claim,
    ClaimFieldSupport,
    ClaimSet,
    ClaimSetStatus,
    EvidenceCoverageStatus,
    EvidenceProjectionRequest,
    ExecutionKind,
    PlanProposal,
    PlanStepProposal,
    RiskClass,
    TransformProgram,
    TransformStep,
    WorkflowMode,
)
from v2.refs import ExecutionArtifactRef
from v2.retrieval import RetrieverFanoutPipeline
from v2.runtime.adaptive_runtime import AdaptiveRuntimeRequest, AdaptiveStepResult
from v2.runtime.adaptive_dispatcher import (
    AdaptiveCapabilityDispatcher,
    AdaptiveDispatchContext,
    StoredAdaptiveArtifact,
)
from v2.runtime.capability_registry import CapabilityRegistry
from v2.runtime.claims import ClaimSetValidator
from v2.runtime.capability_validators import CapabilityQualityContext, default_capability_validator_registry
from v2.runtime.domain_packs import register_long_doc_analysis_capabilities
from v2.runtime.driver import RuntimeDriver
from v2.runtime.evidence_projection import EvidenceProjectionAdapter
from v2.runtime.plan_policy import PlanPolicyValidator
from v2.runtime.role_path import RolePathRunner
from v2.runtime.retrieval_adapter import AdaptiveRetrievalAdapter, AdaptiveRetrievalResult
from v2.runtime.state_consumption import build_state_consumption_record
from v2.runtime.transform_dsl import TransformDslInterpreter
from v2.runtime.workspace import WorkspaceManager
from v2.contracts import CanonicalTaskSpec, EvidenceRequest
from v2.utils import sha256_digest, stable_json_dumps


_SMOKE_CAPABILITY_IDS = (
    "retrieve_semantic_evidence_v1",
    "extract_metric_series_v1",
    "compose_cited_report_v1",
)
_SMOKE_TASK_GOAL = (
    "Find cited operating-metric evidence in the approved Acme long document, "
    "derive a small revenue series, and report only cited facts."
)
# The fixture has no normalized entity/time metadata.  The task goal still
# carries ACME and the quarters semantically, but these empty authority fields
# intentionally mean the verifier must not invent an entity/time acceptance
# requirement.  A domain pack that has normalized metadata can pass non-empty
# constraints here.
_SMOKE_TARGET_ENTITIES: tuple[str, ...] = ()
_SMOKE_TIME_SCOPE = ""


def _capability_output_contracts(
    registry: CapabilityRegistry,
    capability_ids: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                registry.get(capability_id).output_contract_version
                for capability_id in capability_ids
            }
        )
    )


@dataclass(frozen=True)
class RoleWorkerResult:
    candidate: dict[str, object]
    attempts: tuple[dict[str, object], ...]
    request_audit: dict[str, object]
    error: str = ""


class _RecordingLlmClient:
    def __init__(self, delegate: object) -> None:
        self.delegate = delegate
        self.attempts: list[dict[str, object]] = []

    async def complete(
        self,
        messages,
        *,
        purpose: str,
        temperature: float | None = None,
        response_schema: dict[str, object] | None = None,
    ):
        try:
            result = await self.delegate.complete(
                messages,
                purpose=purpose,
                temperature=temperature,
                response_schema=response_schema,
            )
        except Exception as exc:
            self.attempts.append({
                "attempt_index": len(self.attempts) + 1,
                "purpose": purpose,
                "error": f"{type(exc).__name__}:{exc}",
            })
            raise
        self.attempts.append({
            "attempt_index": len(self.attempts) + 1,
            "purpose": purpose,
            "model": result.model,
            "prompt_tokens": result.usage.prompt_tokens,
            "completion_tokens": result.usage.completion_tokens,
            "total_tokens": result.usage.total_tokens,
            "raw_response": result.text,
            "raw_response_hash": sha256_digest(result.text.encode("utf-8")),
        })
        return result

    def describe(self) -> dict[str, object]:
        return self.delegate.describe()


def _fallback_evidence_request(task_id: str, step_id: str) -> EvidenceRequest:
    return EvidenceRequest(
        request_id=f"fallback-evidence-{task_id}", task_id=task_id, step_id=step_id,
        queries=("Acme operating metrics revenue table",), evidence_types=("semantic_context", "table"),
        corpus_scope_ids=("local-long-doc",), max_candidates=8, source_plan_step_id=step_id,
    )


def _coverage_completion_error(coverage: object, criteria: dict[str, object]) -> str:
    locator_count = int(getattr(coverage, "locator_count", 0))
    covered_types = set(getattr(coverage, "covered_evidence_types", ()))
    conflict_count = len(getattr(coverage, "conflict_item_ids", ()))
    minimum = criteria.get("min_locator_count")
    if isinstance(minimum, int) and locator_count < minimum:
        return f"min_locator_count:{locator_count}<{minimum}"
    required_types = criteria.get("required_evidence_types")
    if isinstance(required_types, (list, tuple)):
        missing_types = sorted(set(str(item) for item in required_types) - covered_types)
        if missing_types:
            return f"required_evidence_types_missing:{','.join(missing_types)}"
    maximum_conflicts = criteria.get("max_conflicts")
    if isinstance(maximum_conflicts, int) and conflict_count > maximum_conflicts:
        return f"max_conflicts:{conflict_count}>{maximum_conflicts}"
    return ""


def _metric_completion_error(rows: list[dict[str, object]], criteria: dict[str, object]) -> str:
    minimum = criteria.get("min_rows")
    if isinstance(minimum, int) and len(rows) < minimum:
        return f"min_rows:{len(rows)}<{minimum}"
    required_fields = criteria.get("required_fields")
    if isinstance(required_fields, (list, tuple)):
        required = {str(item) for item in required_fields}
        missing = sorted(required - {str(key) for row in rows for key in row})
        if missing:
            return f"required_fields_missing:{','.join(missing)}"
    return ""


def _citation_repair_eligible(errors: tuple[str, ...]) -> bool:
    repairable_prefixes = (
        "invalid_evidence_reference:",
        "invalid_locator:",
        "missing_support:",
        "unverified_artifact:",
    )
    return bool(errors) and all(error.startswith(repairable_prefixes) for error in errors)


def _controlled_expansion_request(
    request: EvidenceRequest,
    *,
    task_goal: str,
    existing_query_hashes: tuple[str, ...],
) -> EvidenceRequest | None:
    """Issue at most one controller-authored query within the original grant.

    This is deliberately not another LLM turn.  The Retriever already supplied
    its bounded candidate; when coverage is insufficient, the controller may
    add one deduplicated, auditable query without changing corpus, evidence,
    entity, time, memory, or candidate-budget authority.
    """
    normalized_existing = set(existing_query_hashes)
    bases = (
        f"{task_goal} cited table values and locators",
        f"{task_goal} evidence coverage follow-up",
    )
    for index, query in enumerate(bases, start=1):
        bounded_query = query[:512].strip()
        if bounded_query and sha256_digest(bounded_query.lower()) not in normalized_existing:
            return EvidenceRequest(
                request_id=f"{request.request_id}-controller-expansion-{index}",
                task_id=request.task_id,
                step_id=request.step_id,
                queries=(bounded_query,),
                evidence_types=request.evidence_types,
                target_entities=request.target_entities,
                time_scope=request.time_scope,
                corpus_scope_ids=request.corpus_scope_ids,
                memory_policy=request.memory_policy,
                max_candidates=request.max_candidates,
                max_prompt_visible_bytes=request.max_prompt_visible_bytes,
                required_locator=request.required_locator,
                source_plan_step_id=request.source_plan_step_id,
            )
    return None


def _fallback_program(input_ref_id: str) -> TransformProgram:
    return TransformProgram(
        program_id="fallback-transform", input_artifact_refs=(input_ref_id,),
        output_contract_version="statebus.metric_series.v1",
        operations=(
            TransformStep("select", {"columns": ["quarter", "revenue_musd"]}),
            TransformStep("sort", {"columns": ["quarter"]}),
        ),
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value)


def _evidence_locator_string(item: object) -> str:
    locator = getattr(item, "locator", None)
    fragment_id = getattr(locator, "fragment_id", "")
    if fragment_id:
        return str(fragment_id)
    canonical_text_id = getattr(locator, "canonical_text_id", "")
    if canonical_text_id:
        return f"{canonical_text_id}:{getattr(locator, 'start_char', 0)}-{getattr(locator, 'end_char', 0)}"
    table_id = getattr(locator, "table_id", "")
    if table_id:
        return f"{table_id}:{getattr(locator, 'row_idx', 0)}:{getattr(locator, 'col_idx', 0)}"
    return ""


def _envelope_from_payload(payload: dict[str, object]) -> AdaptiveTaskEnvelope:
    return AdaptiveTaskEnvelope(
        task_id=str(payload["task_id"]),
        canonical_task_spec_hash=str(payload["canonical_task_spec_hash"]),
        workflow_mode=WorkflowMode(str(payload["workflow_mode"])),
        domain_pack_id=str(payload["domain_pack_id"]),
        allowed_capability_ids=_string_tuple(payload.get("allowed_capability_ids")),
        allowed_output_contracts=_string_tuple(payload.get("allowed_output_contracts")),
        allowed_memory_policies=_string_tuple(payload.get("allowed_memory_policies")) or (
            "none", "assist", "artifact", "strategy"
        ),
        role_cardinality={
            str(role): (
                int(bounds.get("minimum", 1)),
                int(bounds.get("maximum", 1)),
            )
            for role, bounds in payload.get("role_cardinality", {}).items()
            if isinstance(bounds, dict)
        } if isinstance(payload.get("role_cardinality"), dict) else {},
        max_plan_steps=int(payload.get("max_plan_steps", 4)),
        max_dependency_depth=int(payload.get("max_dependency_depth", 4)),
        max_planner_prompt_tokens=int(payload.get("max_planner_prompt_tokens", 8_192)),
        max_planner_completion_tokens=int(payload.get("max_planner_completion_tokens", 2_048)),
        max_retrieval_steps=int(payload.get("max_retrieval_steps", 2)),
        max_execution_runtime_ms=int(payload.get("max_execution_runtime_ms", 96_000)),
        max_replans=int(payload.get("max_replans", 1)),
        max_retrieval_expansions=int(payload.get("max_retrieval_expansions", 1)),
        max_total_attempts=int(payload.get("max_total_attempts", 5)),
        risk_class=RiskClass(str(payload.get("risk_class", RiskClass.WORKSPACE_WRITE.value))),
        allow_llm_python=bool(payload.get("allow_llm_python", False)),
        policy_version=str(payload.get("policy_version", "statebus.plan_policy.v1")),
    )


def _proposal_from_payload(payload: dict[str, object]) -> PlanProposal:
    raw_steps = payload.get("steps", [])
    if not isinstance(raw_steps, list):
        raise ValueError("worker_plan_steps_not_list")
    steps: list[PlanStepProposal] = []
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            raise ValueError("worker_plan_step_not_object")
        criteria = raw_step.get("completion_criteria", {})
        steps.append(PlanStepProposal(
            step_id=str(raw_step.get("step_id", "")),
            role=str(raw_step.get("role", "")),
            capability_id=str(raw_step.get("capability_id", "")),
            goal=str(raw_step.get("goal", "")),
            depends_on=_string_tuple(raw_step.get("depends_on")),
            input_ref_ids=_string_tuple(raw_step.get("input_ref_ids")),
            input_ref_kinds=_string_tuple(raw_step.get("input_ref_kinds")),
            output_contract_version=str(raw_step.get("output_contract_version", "")),
            completion_criteria=dict(criteria) if isinstance(criteria, dict) else {},
            on_failure=str(raw_step.get("on_failure", "fail")),
            required_input_fields=_string_tuple(raw_step.get("required_input_fields")),
        ))
    return PlanProposal(
        proposal_id=str(payload.get("proposal_id", "")),
        task_id=str(payload.get("task_id", "")),
        steps=tuple(steps),
        final_output_contract_version=str(payload.get("final_output_contract_version", "")),
        requested_memory_policy=str(payload.get("requested_memory_policy", "none")),
        planner_notes=str(payload.get("planner_notes", "")),
        model_id=str(payload.get("model_id", "")),
        prompt_tokens=int(payload.get("prompt_tokens", 0)),
        completion_tokens=int(payload.get("completion_tokens", 0)),
        latency_ms=float(payload.get("latency_ms", 0.0)),
        raw_output_hash=str(payload.get("raw_output_hash", "")),
        schema_version=str(payload.get("schema_version", "statebus.plan_proposal.v1")),
    )


def _evidence_request_from_payload(payload: dict[str, object]) -> EvidenceRequest:
    return EvidenceRequest(
        request_id=str(payload.get("request_id", "")),
        task_id=str(payload.get("task_id", "")),
        step_id=str(payload.get("step_id", "")),
        queries=_string_tuple(payload.get("queries")),
        evidence_types=_string_tuple(payload.get("evidence_types")),
        target_entities=_string_tuple(payload.get("target_entities")),
        time_scope=str(payload.get("time_scope", "")),
        corpus_scope_ids=_string_tuple(payload.get("corpus_scope_ids")),
        memory_policy=str(payload.get("memory_policy", "none")),
        max_candidates=int(payload.get("max_candidates", 12)),
        max_prompt_visible_bytes=int(payload.get("max_prompt_visible_bytes", 16_384)),
        required_locator=bool(payload.get("required_locator", True)),
        source_plan_step_id=str(payload.get("source_plan_step_id", "")),
        schema_version=str(payload.get("schema_version", "statebus.evidence_request.v1")),
    )


def _program_from_payload(payload: dict[str, object]) -> TransformProgram:
    raw_operations = payload.get("operations", [])
    if not isinstance(raw_operations, list):
        raise ValueError("worker_transform_operations_not_list")
    operations = tuple(
        TransformStep(
            op=str(raw.get("op", "")),
            arguments=dict(raw.get("arguments", {})) if isinstance(raw, dict) and isinstance(raw.get("arguments", {}), dict) else {},
        )
        for raw in raw_operations
        if isinstance(raw, dict)
    )
    return TransformProgram(
        program_id=str(payload.get("program_id", "")),
        input_artifact_refs=_string_tuple(payload.get("input_artifact_refs")),
        operations=operations,
        output_contract_version=str(payload.get("output_contract_version", "")),
        schema_version=str(payload.get("schema_version", "statebus.transform_program.v1")),
    )


def _claim_set_from_payload(payload: dict[str, object]) -> ClaimSet:
    raw_claims = payload.get("claims", [])
    if not isinstance(raw_claims, list):
        raise ValueError("worker_claims_not_list")
    claims: list[Claim] = []
    for raw in raw_claims:
        if not isinstance(raw, dict):
            continue
        numeric_fields = raw.get("numeric_fields", {})
        factual_fields_raw = raw.get("factual_fields", {})
        factual_fields = (
            {
                str(key): value
                for key, value in factual_fields_raw.items()
                if value is None or isinstance(value, (str, int, float, bool))
            }
            if isinstance(factual_fields_raw, dict)
            else {}
        )
        field_support_raw = raw.get("field_support", [])
        field_support = tuple(
            ClaimFieldSupport(
                field_path=str(item.get("field_path", "")),
                normalized_value_hash=str(item.get("normalized_value_hash", "")),
                support_kind=str(item.get("support_kind", "")),
                evidence_item_ids=_string_tuple(item.get("evidence_item_ids")),
                artifact_ref_id=str(item.get("artifact_ref_id", "")),
                artifact_field_path=str(item.get("artifact_field_path", "")),
                source_locators=_string_tuple(item.get("source_locators")),
                schema_version=str(item.get("schema_version", "statebus.claim_set.v2")),
            )
            for item in field_support_raw
            if isinstance(item, dict)
        ) if isinstance(field_support_raw, list) else ()
        claims.append(Claim(
            claim_id=str(raw.get("claim_id", "")),
            claim_text=str(raw.get("claim_text", "")),
            claim_type=str(raw.get("claim_type", "fact")),
            supporting_evidence_item_ids=_string_tuple(raw.get("supporting_evidence_item_ids")),
            supporting_artifact_ref_ids=_string_tuple(raw.get("supporting_artifact_ref_ids")),
            citation_locators=_string_tuple(raw.get("citation_locators")),
            numeric_fields={str(key): float(value) for key, value in numeric_fields.items()} if isinstance(numeric_fields, dict) else {},
            uncertainty_note=str(raw.get("uncertainty_note", "")),
            status=str(raw.get("status", "ready")),
            factual_fields=factual_fields,
            field_support=field_support,
        ))
    return ClaimSet(
        claim_set_id=str(payload.get("claim_set_id", "")),
        task_id=str(payload.get("task_id", "")),
        claims=tuple(claims),
        status=ClaimSetStatus(str(payload.get("status", ClaimSetStatus.READY.value))),
        schema_version=str(payload.get("schema_version", "statebus.claim_set.v1")),
    )


def _isolated_role_completion(role: str, payload: dict[str, object]) -> RoleWorkerResult:
    worker_timeout_s = float(os.getenv("STATEBUS_ADAPTIVE_ROLE_WORKER_TIMEOUT_S", "105"))
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--role-worker", role],
            input=stable_json_dumps(payload),
            text=True,
            capture_output=True,
            timeout=worker_timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        error = f"{role}_worker_timeout:{worker_timeout_s:.1f}s"
        return RoleWorkerResult(
            candidate={},
            attempts=({"attempt_index": 1, "purpose": role, "error": error},),
            request_audit={
                "schema_version": "statebus.rendered_role_request.v1",
                "role": role,
                "content_persisted": False,
                "request_count": 0,
                "requests": [],
            },
            error=error,
        )
    if completed.returncode != 0:
        error = (
            f"{role}_worker_failed:exit={completed.returncode}:"
            f"stdout={completed.stdout[-1000:]}:stderr={completed.stderr[-1000:]}"
        )
        return RoleWorkerResult(candidate={}, attempts=(), request_audit={}, error=error)
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        error = f"{role}_worker_invalid_json:{completed.stdout[-1000:]}:{type(exc).__name__}"
        return RoleWorkerResult(candidate={}, attempts=(), request_audit={}, error=error)
    if not isinstance(result, dict):
        return RoleWorkerResult(candidate={}, attempts=(), request_audit={}, error=f"{role}_worker_result_not_object")
    candidate = result.get("candidate")
    attempts = result.get("attempts", [])
    request_audit = result.get("request_audit", {})
    worker_error = str(result.get("error", ""))
    if not isinstance(candidate, dict):
        raise RuntimeError(f"{role}_worker_candidate_not_object")
    if not isinstance(attempts, list) or not all(isinstance(item, dict) for item in attempts):
        raise RuntimeError(f"{role}_worker_attempts_not_list")
    if not isinstance(request_audit, dict):
        raise RuntimeError(f"{role}_worker_request_audit_not_object")
    return RoleWorkerResult(
        candidate={str(key): value for key, value in candidate.items()},
        attempts=tuple({str(key): value for key, value in item.items()} for item in attempts),
        request_audit={str(key): value for key, value in request_audit.items()},
        error=worker_error,
    )


def _role_max_tokens_override(role: str) -> int | None:
    value = os.getenv(f"STATEBUS_ADAPTIVE_{role.upper()}_MAX_TOKENS")
    if value is None or not value.strip():
        return None
    try:
        max_tokens = int(value)
    except ValueError as exc:
        raise ValueError(f"adaptive_{role}_max_tokens_not_integer") from exc
    if max_tokens <= 0:
        raise ValueError(f"adaptive_{role}_max_tokens_not_positive")
    return max_tokens


def _run_role_worker(role: str) -> None:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("worker_payload_not_object")
    llm_config = LLMConfig.from_runtime().with_mode("local_vllm")
    provider_name = llm_config.role_config(role).provider
    llm_config = llm_config.with_provider_override(
        provider_name,
        timeout_s=float(os.getenv("STATEBUS_ADAPTIVE_ROLE_HTTP_TIMEOUT_S", "90")),
        request_max_attempts=1,
    )
    max_tokens = _role_max_tokens_override(role)
    if max_tokens is not None:
        llm_config = llm_config.with_role_override(role, max_tokens=max_tokens)
    recording_client = _RecordingLlmClient(build_llm_client(llm_config))
    runner = RolePathRunner(llm_client=recording_client, json_response_max_attempts=1)
    worker_error = ""
    try:
        if role == "planner":
            envelope = _envelope_from_payload(dict(payload["envelope"]))
            result = runner.propose_plan(
                envelope=envelope,
                task_goal=str(payload["task_goal"]),
                allowed_inputs=tuple(payload.get("allowed_inputs", ())),
                capability_surface=tuple(payload.get("capability_surface", ())),
                required_roles=_string_tuple(payload.get("required_roles")),
                role_cardinality=(
                    {
                        str(role): (
                            int(bounds.get("minimum", 1)),
                            int(bounds.get("maximum", 1)),
                        )
                        for role, bounds in payload["role_cardinality"].items()
                        if isinstance(bounds, dict)
                    }
                    if isinstance(payload.get("role_cardinality"), dict)
                    else None
                ),
                replan_context=(
                    {str(key): value for key, value in payload["replan_context"].items()}
                    if isinstance(payload.get("replan_context"), dict)
                    else None
                ),
                role_slot_layout=bool(payload.get("role_slot_layout", False)),
            ).canonical_payload()
        elif role == "retriever":
            result = runner.build_evidence_request(
                task_id=str(payload["task_id"]),
                step_id=str(payload["step_id"]),
                step_goal=str(payload["step_goal"]),
                corpus_scope_ids=_string_tuple(payload.get("corpus_scope_ids")),
                evidence_types=_string_tuple(payload.get("evidence_types")),
                target_entities=_string_tuple(payload.get("target_entities")),
                time_scope=str(payload.get("time_scope", "")),
                task_goal=str(payload.get("task_goal", "")),
                gap_context=(
                    {str(key): value for key, value in payload["gap_context"].items()}
                    if isinstance(payload.get("gap_context"), dict)
                    else None
                ),
            ).canonical_payload()
        elif role == "executor":
            input_schema = payload.get("input_schema", {})
            if not isinstance(input_schema, dict):
                raise ValueError("worker_input_schema_not_object")
            result = runner.build_transform_program(
                program_id=str(payload["program_id"]),
                authorized_input_refs=_string_tuple(payload.get("authorized_input_refs")),
                input_schema={str(key): _string_tuple(value) for key, value in input_schema.items()},
                output_contract_version=str(payload["output_contract_version"]),
                operation_catalog=_string_tuple(payload.get("operation_catalog")),
                step_goal=str(payload.get("step_goal", "")),
                desired_output_fields=_string_tuple(payload.get("desired_output_fields")),
                input_preview=tuple(
                    {str(key): value for key, value in item.items()}
                    for item in payload.get("input_preview", [])
                    if isinstance(item, dict)
                ),
                operation_semantics=(
                    {str(key): value for key, value in payload["operation_semantics"].items()}
                    if isinstance(payload.get("operation_semantics"), dict)
                    else None
                ),
                repair_context=(
                    {str(key): value for key, value in payload["repair_context"].items()}
                    if isinstance(payload.get("repair_context"), dict)
                    else None
                ),
            ).canonical_payload()
        elif role == "summarizer":
            raw_items = payload.get("evidence_items", [])
            if not isinstance(raw_items, list):
                raise ValueError("worker_evidence_items_not_list")
            evidence_items = tuple(
                {str(key): str(value) for key, value in item.items()}
                for item in raw_items
                if isinstance(item, dict)
            )
            raw_artifact_summaries = payload.get("artifact_summaries", [])
            if not isinstance(raw_artifact_summaries, list):
                raise ValueError("worker_artifact_summaries_not_list")
            if payload.get("operation") == "repair_citations":
                raw_claim_set = payload.get("claim_set")
                if not isinstance(raw_claim_set, dict):
                    raise ValueError("worker_claim_set_not_object")
                repaired = runner.repair_claim_citations(
                    claim_set=_claim_set_from_payload(raw_claim_set),
                    verified_artifact_refs=_string_tuple(payload.get("verified_artifact_refs")),
                    evidence_items=evidence_items,
                    validation_errors=_string_tuple(payload.get("validation_errors")),
                )
                result = repaired.canonical_payload()
            else:
                result = runner.build_claim_set(
                    task_id=str(payload["task_id"]),
                    claim_set_id=str(payload["claim_set_id"]),
                    verified_artifact_refs=_string_tuple(payload.get("verified_artifact_refs")),
                    evidence_items=evidence_items,
                    task_goal=str(payload.get("task_goal", "")),
                    artifact_summaries=tuple(
                        {str(key): value for key, value in item.items()}
                        for item in raw_artifact_summaries
                        if isinstance(item, dict)
                    ),
                    expected_claim_count=(
                        int(payload["expected_claim_count"])
                        if payload.get("expected_claim_count") is not None
                        else None
                    ),
                    claim_set_schema_version=str(
                        payload.get("claim_set_schema_version", "statebus.claim_set.v1")
                    ),
                ).canonical_payload()
        else:
            raise ValueError(f"unsupported_role_worker:{role}")
    except Exception as exc:
        result = {}
        worker_error = f"{type(exc).__name__}:{exc}"
    print(stable_json_dumps({
        "candidate": result,
        "attempts": recording_client.attempts,
        "request_audit": runner.rendered_request_audit_payload(role, include_content=True),
        "error": worker_error,
    }), flush=True)


def _write_role_trace(
    run_dir: Path,
    role: str,
    *,
    worker: RoleWorkerResult | None = None,
    selected: dict[str, object] | None = None,
    validation: dict[str, object] | None = None,
    fallback_used: bool = False,
    error: str = "",
) -> str:
    role_dir = run_dir / "roles"
    role_dir.mkdir(exist_ok=True)
    path = role_dir / f"{role}.json"
    payload = {
        "schema_version": "statebus.adaptive_role_smoke_trace.v1",
        "role": role,
        "fallback_used": fallback_used,
        "error": error,
        "worker_error": worker.error if worker is not None else "",
        "candidate": worker.candidate if worker is not None else {},
        "attempts": list(worker.attempts) if worker is not None else [],
        "request_audit": worker.request_audit if worker is not None else {},
        "selected": selected or {},
        "validation": validation or {},
    }
    path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")
    return str(path)


def _write_analysis(run_dir: Path, summary: dict[str, object]) -> Path:
    coverage = summary.get("coverage", {})
    coverage = coverage if isinstance(coverage, dict) else {}
    decisions = summary.get("coverage_decisions", [])
    decisions = decisions if isinstance(decisions, list) else []
    telemetry = summary.get("runtime_telemetry_metrics", {})
    telemetry = telemetry if isinstance(telemetry, dict) else {}
    role_calls = summary.get("role_calls", [])
    role_calls = role_calls if isinstance(role_calls, list) else []
    final_decision = decisions[-1] if decisions else {}
    final_decision = final_decision if isinstance(final_decision, dict) else {}
    lines = [
        "# Adaptive Agent Smoke Analysis",
        "",
        f"- Runtime completed: `{summary.get('runtime_completed', False)}`",
        f"- Runtime plan replaced: `{summary.get('runtime_plan_replaced', False)}`",
        f"- Elapsed time: `{float(summary.get('elapsed_ms', 0.0)):.2f} ms`",
        f"- Embedding device: `{summary.get('embedding_device', '')}`",
        f"- Embedding dimensions: `{summary.get('embedding_dims', 0)}`",
        f"- Evidence coverage: `{coverage.get('status', 'unknown')}`",
        f"- Evidence-type coverage: `{coverage.get('evidence_types_coverage', 'unknown')}`",
        f"- Entity coverage: `{coverage.get('entity_coverage_ok', 'unknown')}`",
        f"- Locator coverage: `{coverage.get('locator_coverage', 'unknown')}`",
        f"- Time-scope coverage: `{coverage.get('time_scope_coverage', 'unknown')}`",
        f"- Coverage decision: `{final_decision.get('decision', 'not_recorded')}`",
        f"- Role calls: `{', '.join(str(role) for role in role_calls) or 'none'}`",
        f"- Model-path success: `{summary.get('model_path_success', False)}`",
        f"- Planner fallback used: `{summary.get('proposal_used_fallback', False)}`",
        f"- Retriever fallback used: `{summary.get('retriever_fallback', False)}`",
        f"- Transform fallback used: `{summary.get('program_fallback', False)}`",
        f"- Claim fallback used: `{summary.get('claim_fallback', False)}`",
        f"- Citation-only repair used: `{summary.get('summarizer_citation_repair_used', False)}`",
        f"- Controlled replan used: `{summary.get('controlled_replan_used', False)}`",
        f"- Capability grants issued: `{telemetry.get('capability_grant_issued', 0.0)}`",
        f"- Completed adaptive steps: `{telemetry.get('adaptive_step_completed', 0.0)}`",
        "",
        "## Interpretation",
    ]
    if summary.get("runtime_completed") and coverage.get("status") == "complete":
        lines.append("- The bounded DAG completed with programmatically verified evidence coverage.")
    else:
        lines.append("- Inspect summary.json and telemetry/runtime_events.jsonl for the first failed decision.")
    if any(bool(summary.get(key)) for key in ("proposal_used_fallback", "retriever_fallback", "program_fallback", "claim_fallback", "controlled_replan_used")):
        lines.append("- A fallback or controller-owned replan was used; inspect roles/*.json and replan_records for the exact candidate and validator error.")
        fallback_reasons = summary.get("fallback_reasons", {})
        if isinstance(fallback_reasons, dict):
            for role, reason in sorted(fallback_reasons.items()):
                lines.append(f"- {role} fallback reason: `{reason}`")
    else:
        lines.append("- No planner, transform, or claim fallback was recorded.")
    path = run_dir / "analysis.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one bounded adaptive local-vLLM development smoke.")
    parser.add_argument("--output-root", type=Path, default=Path("/statebus/runs"))
    parser.add_argument(
        "--embedding-model-path",
        default=os.getenv("STATEBUS_EMBED_MODEL_PATH", "/statebus/models/Qwen3-Embedding-0.6B"),
    )
    parser.add_argument("--embedding-device", default=os.getenv("STATEBUS_EMBED_DEVICE", "cuda:0"))
    parser.add_argument("--role-worker", choices=("planner", "retriever", "executor", "summarizer"))
    parser.add_argument(
        "--require-model-success",
        action="store_true",
        help="Return exit code 2 when any adaptive role uses a deterministic fallback.",
    )
    args = parser.parse_args()
    if args.role_worker:
        _run_role_worker(args.role_worker)
        return
    run_started_ns = time.perf_counter_ns()
    run_dir = args.output_root / f"adaptive_agent_smoke_20260716_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=False)
    print(stable_json_dumps({"stage": "run_created", "run_dir": str(run_dir)}), flush=True)

    registry = CapabilityRegistry()
    pack = register_long_doc_analysis_capabilities(registry)
    phase_one_capability_ids = _SMOKE_CAPABILITY_IDS
    if any(registry.get(capability_id).execution_kind == ExecutionKind.LLM_BOUNDED_PYTHON for capability_id in phase_one_capability_ids):
        raise RuntimeError("phase-one smoke capability surface includes LLM bounded Python")
    task_id = "adaptive-live-longdoc-001"
    task_goal = _SMOKE_TASK_GOAL
    envelope = AdaptiveTaskEnvelope(
        task_id=task_id, canonical_task_spec_hash="live-longdoc-smoke-v1", workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id=pack.pack_id, allowed_capability_ids=phase_one_capability_ids,
        allowed_output_contracts=_capability_output_contracts(registry, phase_one_capability_ids),
        risk_class=RiskClass.WORKSPACE_WRITE,
        max_plan_steps=4, max_total_attempts=5,
    )
    print(stable_json_dumps({"stage": "planner_request"}), flush=True)
    planner_worker = _isolated_role_completion(
        "planner",
        {
            "envelope": envelope.canonical_payload(),
            "task_goal": task_goal,
            "allowed_inputs": [],
            "capability_surface": list(registry.public_view(phase_one_capability_ids)),
            "required_roles": ["retriever", "executor", "summarizer"],
        },
    )
    role_trace_paths: dict[str, str] = {}
    role_trace_paths["planner"] = _write_role_trace(
        run_dir,
        "planner",
        worker=planner_worker,
        selected=planner_worker.candidate,
        validation={"status": "candidate_received_policy_pending"},
        fallback_used=False,
        error=planner_worker.error,
    )
    proposal = _proposal_from_payload(planner_worker.candidate)
    policy = PlanPolicyValidator(registry)
    print(stable_json_dumps({"stage": "planner_received", "proposal_hash": proposal.proposal_hash}), flush=True)
    initial_outcome = policy.validate(proposal, envelope)
    outcome = initial_outcome
    required_roles = {"retriever", "executor", "summarizer"}
    used_fallback = (
        outcome.approved_plan is None
        or not required_roles <= {step.role for step in outcome.approved_plan.steps}
    )
    if used_fallback:
        outcome = policy.fallback(proposal, envelope, pack.fallback_proposal(envelope))
    if outcome.approved_plan is None:
        raise RuntimeError("domain-pack fallback plan was rejected")
    approved = outcome.approved_plan
    role_trace_paths["planner"] = _write_role_trace(
        run_dir,
        "planner",
        worker=planner_worker,
        selected=proposal.canonical_payload(),
        validation={
            "initial_policy_report": initial_outcome.report.canonical_payload(),
            "selected_policy_report": outcome.report.canonical_payload(),
            "approved_plan_hash": approved.approved_plan_hash,
        },
        fallback_used=used_fallback,
        error=(
            planner_worker.error
            or (
                ";".join(issue.error_code for issue in initial_outcome.report.issues)
                if initial_outcome.approved_plan is None
                else ""
            )
        ),
    )

    spec = CanonicalTaskSpec(
        task_family="continuous_long_doc_table_analysis", intent_op="analyze_document",
        required_outputs=("revenue_series",),
        arguments={
            "dataset_id": "long_doc_table",
            "document_path": "v2/benchmark/samples/continuous_task_families/long_doc_table/acme_ops_report_2026.md",
            "request_text": task_goal,
            "metric": "revenue",
        },
    )
    pipeline = RetrieverFanoutPipeline.with_embedding_mode(
        "local", model_path=args.embedding_model_path, device=args.embedding_device, top_k=2,
    )
    print(stable_json_dumps({"stage": "adaptive_dispatch"}), flush=True)
    state: dict[str, object] = {
        "role_calls": [],
        "retriever_fallback": False,
        "program_fallback": False,
        "claim_fallback": False,
        "summarizer_citation_repair_used": False,
        "fallback_reasons": {},
        "controlled_replan_used": False,
        "replan_records": [],
    }
    if used_fallback:
        fallback_reasons = state["fallback_reasons"]
        assert isinstance(fallback_reasons, dict)
        fallback_reasons["planner"] = planner_worker.error or ";".join(
            issue.error_code for issue in initial_outcome.report.issues
        ) or "required_roles_missing"
    workspace = WorkspaceManager(run_dir / "workspace")
    layout = workspace.ensure_layout(task_id)
    projection_adapter = EvidenceProjectionAdapter()
    capability_validators = default_capability_validator_registry()

    # The diagnostic supplies only model-facing request/program factories and a
    # registered report handler.  The Runtime owns execution through the
    # Dispatcher; this script never receives a generic Runtime callback.
    retrieval_bundles: dict[str, object] = {}

    def retrieval_request_factory(step: PlanStepProposal, grant) -> EvidenceRequest:
        del grant
        print(stable_json_dumps({"stage": "retriever_request", "step_id": step.step_id}), flush=True)
        role_calls = state["role_calls"]
        assert isinstance(role_calls, list)
        role_calls.append("retriever")
        retriever_worker: RoleWorkerResult | None = None
        retriever_error = ""
        try:
            retriever_worker = _isolated_role_completion(
                "retriever",
                {
                    "task_id": task_id,
                    "step_id": step.step_id,
                    "step_goal": step.goal,
                    "task_goal": task_goal,
                    "corpus_scope_ids": ["local-long-doc"],
                    "evidence_types": ["semantic_context", "table"],
                    "target_entities": list(_SMOKE_TARGET_ENTITIES),
                    "time_scope": _SMOKE_TIME_SCOPE,
                },
            )
            request = _evidence_request_from_payload(retriever_worker.candidate)
            if request.task_id != task_id or request.step_id != step.step_id:
                raise ValueError("evidence_request_task_or_step_mismatch")
            if not set(request.evidence_types) <= {"semantic_context", "table"}:
                raise ValueError("evidence_type_outside_smoke_surface")
            if not set(request.corpus_scope_ids) <= {"local-long-doc"}:
                raise ValueError("corpus_scope_outside_smoke_surface")
            if not 1 <= len(request.queries) <= 3:
                raise ValueError("query_count_outside_smoke_budget")
            if request.target_entities != _SMOKE_TARGET_ENTITIES:
                raise ValueError("target_entities_outside_smoke_authority")
            if request.time_scope != _SMOKE_TIME_SCOPE:
                raise ValueError("time_scope_outside_smoke_authority")
        except Exception as exc:
            state["retriever_fallback"] = True
            validation_error = f"{type(exc).__name__}:{exc}"
            retriever_error = (
                f"{retriever_worker.error};{validation_error}"
                if retriever_worker is not None and retriever_worker.error
                else validation_error
            )
            fallback_reasons = state["fallback_reasons"]
            assert isinstance(fallback_reasons, dict)
            fallback_reasons["retriever"] = retriever_error
            request = _fallback_evidence_request(task_id, step.step_id)
        role_trace_paths["retriever"] = _write_role_trace(
            run_dir,
            "retriever",
            worker=retriever_worker,
            selected=request.canonical_payload(),
            validation={
                "allowed_corpus_scope_ids": ["local-long-doc"],
                "allowed_evidence_types": ["semantic_context", "table"],
                "task_goal": task_goal,
                "authorized_target_entities": list(_SMOKE_TARGET_ENTITIES),
                "authorized_time_scope": _SMOKE_TIME_SCOPE,
                "query_count": len(request.queries),
            },
            fallback_used=bool(state["retriever_fallback"]),
            error=retriever_error,
        )
        return request

    def retrieve_query(query: str, request: EvidenceRequest):
        print(stable_json_dumps({"stage": "retrieval_pipeline", "query_hash": sha256_digest(query)}), flush=True)
        result = pipeline.run_multi_query(
            task_id=request.task_id,
            spec=spec,
            query_texts=(query,),
            planner_scope_payload={"query_text": query},
        )
        retrieval_bundles[sha256_digest(query.strip().lower())] = result.bundles[0]
        return result.evidence_pack

    def retrieval_expansion_factory(request: EvidenceRequest, coverage_report):
        if coverage_report.status != EvidenceCoverageStatus.INSUFFICIENT_EVIDENCE:
            return None
        return _controlled_expansion_request(
            request,
            task_goal=task_goal,
            existing_query_hashes=tuple(sha256_digest(query.strip().lower()) for query in request.queries),
        )

    def retrieval_result_observer(result: AdaptiveRetrievalResult, step: PlanStepProposal, grant):
        print(stable_json_dumps({"stage": "retrieval_coverage"}), flush=True)
        coverage = result.coverage_reports[-1]
        state["evidence_request"] = result.request.canonical_payload()
        state["coverage"] = coverage.canonical_payload()
        state["coverage_status"] = coverage.status
        state["coverage_decisions"] = [decision.canonical_payload() for decision in result.coverage_decisions]
        state["evidence_pack"] = result.evidence_pack
        bundle = next((retrieval_bundles.get(query_hash) for query_hash in result.query_hashes if query_hash in retrieval_bundles), None)
        if bundle is None:
            return ()
        state["embedding_dims"] = bundle.query_embedding.dims
        evidence_ref_id = f"evidence:{grant.task_id}:{grant.step_id}:{grant.attempt_id}"
        consumption = build_state_consumption_record(
            state_ref_id=bundle.query_embedding.embedding_id,
            consumer_role="retriever",
            consumer_step_id=step.step_id,
            operation="rerank_candidates",
            read_field_ids=tuple(item.item_id for item in result.evidence_pack.semantic_contexts[:2]),
            input_decision_surface_hash=bundle.candidate_pool.candidate_surface_hash,
            output_decision_surface_hash=bundle.rerank_result.rerank_hash,
            selected_ids=bundle.rerank_result.selected_candidate_ids,
            downstream_ref_ids=(evidence_ref_id,),
        )
        state["state_consumption"] = consumption.canonical_payload()
        return (consumption,)

    def transform_program_factory(step: PlanStepProposal, grant, input_ref_id: str, rows: tuple[dict[str, object], ...]) -> TransformProgram:
        print(stable_json_dumps({"stage": "executor_transform", "step_id": step.step_id}), flush=True)
        role_calls = state["role_calls"]
        assert isinstance(role_calls, list)
        role_calls.append("executor")
        executor_worker: RoleWorkerResult | None = None
        executor_error = ""
        dsl_interpreter = TransformDslInterpreter()
        try:
            executor_worker = _isolated_role_completion(
                "executor",
                {
                    "program_id": f"program-{step.step_id}",
                    "step_goal": step.goal,
                    "authorized_input_refs": [input_ref_id],
                    "input_schema": {input_ref_id: ["quarter", "revenue_musd"]},
                    "input_preview": [dict(row) for row in rows],
                    "desired_output_fields": ["quarter", "revenue_musd"],
                    "output_contract_version": grant.output_contract_version,
                    "operation_catalog": ["select", "sort"],
                },
            )
            program = _program_from_payload(executor_worker.candidate)
            model_report = dsl_interpreter.validator.validate(
                program,
                authorized_input_refs=(input_ref_id,),
                available_columns={input_ref_id: ("quarter", "revenue_musd")},
            )
            if not model_report.ok:
                raise ValueError(f"transform_program_invalid:{model_report.error_code}:{model_report.operation_index}")
        except Exception as exc:
            state["program_fallback"] = True
            validation_error = f"{type(exc).__name__}:{exc}"
            executor_error = (
                f"{executor_worker.error};{validation_error}"
                if executor_worker is not None and executor_worker.error
                else validation_error
            )
            fallback_reasons = state["fallback_reasons"]
            assert isinstance(fallback_reasons, dict)
            fallback_reasons["executor"] = executor_error
            program = _fallback_program(input_ref_id)
            model_report = dsl_interpreter.validator.validate(
                program,
                authorized_input_refs=(input_ref_id,),
                available_columns={input_ref_id: ("quarter", "revenue_musd")},
            )
        role_trace_paths["executor"] = _write_role_trace(
            run_dir,
            "executor",
            worker=executor_worker,
            selected=program.canonical_payload(),
            validation={
                "ok": model_report.ok,
                "error_code": model_report.error_code,
                "operation_index": model_report.operation_index,
                "completion_criteria": dict(step.completion_criteria),
                "input_artifact_ref": input_ref_id,
            },
            fallback_used=bool(state["program_fallback"]),
            error=executor_error,
        )
        state["transform_program"] = program.canonical_payload()
        return program

    # This builtin is an explicitly registered dispatcher handler, not a
    # Runtime callback.  It consumes only the verified refs held by the
    # dispatcher context after the Executor quality gate succeeds.
    def compose_report_handler(envelope, plan, step, grant, attempt_workspace) -> AdaptiveStepResult:
        del envelope, plan, attempt_workspace
        print(stable_json_dumps({"stage": "summarizer_claims", "step_id": step.step_id}), flush=True)
        role_calls = state["role_calls"]
        assert isinstance(role_calls, list)
        role_calls.append("summarizer")
        artifact_inputs = [
            dispatch_context.artifacts[ref_id]
            for ref_id in grant.input_ref_ids
            if ref_id in dispatch_context.artifacts
        ]
        evidence_inputs = [
            dispatch_context.evidence_packs[ref_id]
            for ref_id in grant.input_ref_ids
            if ref_id in dispatch_context.evidence_packs
        ]
        if len(artifact_inputs) != 1 or len(evidence_inputs) != 1:
            return AdaptiveStepResult(grant_hash=grant.grant_hash, success=False, attempt_id=grant.attempt_id, error_code="summarizer_verified_input_set_invalid")
        stored = artifact_inputs[0]
        evidence_pack = evidence_inputs[0]
        if stored is None or evidence_pack is None:
            return AdaptiveStepResult(grant_hash=grant.grant_hash, success=False, attempt_id=grant.attempt_id, error_code="missing_verified_artifact_or_evidence")
        artifact = stored.artifact
        artifact_payload = [dict(row) for row in stored.rows]
        if artifact.verification_state.value != "verified":
            return AdaptiveStepResult(grant_hash=grant.grant_hash, success=False, attempt_id=grant.attempt_id, error_code="artifact_not_verified")
        evidence_candidates = tuple(
            {"id": item.item_id, "locator": _evidence_locator_string(item), "text": item.rendered_text[:1_200]}
            for item in getattr(evidence_pack, "semantic_contexts", ())[:3]
            if _evidence_locator_string(item)
        )
        evidence_items = tuple(
            item for item in evidence_candidates if "2025Q4" in item["text"] and "2026Q1" in item["text"]
        ) or evidence_candidates[:1]
        summarizer_worker: RoleWorkerResult | None = None
        summarizer_repair_worker: RoleWorkerResult | None = None
        summarizer_error = ""
        citation_repair: dict[str, object] = {"attempted": False, "succeeded": False, "initial_errors": [], "repair_errors": []}
        try:
            summarizer_worker = _isolated_role_completion(
                "summarizer",
                {
                    "task_id": task_id,
                    "claim_set_id": "live-claims",
                    "task_goal": "Report the verified ACME revenue metric series using only supplied evidence and artifact values.",
                    "verified_artifact_refs": [artifact.artifact_id],
                    "artifact_summaries": [{"artifact_ref_id": artifact.artifact_id, "status": artifact.verification_state.value, "rows": artifact_payload}],
                    "evidence_items": list(evidence_items),
                },
            )
            claim_set = _claim_set_from_payload(summarizer_worker.candidate)
            claim_report = ClaimSetValidator().validate(
                claim_set,
                evidence_pack=evidence_pack,
                verified_artifacts={artifact.artifact_id: (artifact, artifact_payload)},
                current_task_id=task_id,
                current_session_id=grant.session_id,
                evidence_session_id=grant.session_id,
            )
        except Exception as exc:
            validation_error = f"{type(exc).__name__}:{exc}"
            summarizer_error = f"{summarizer_worker.error};{validation_error}" if summarizer_worker is not None and summarizer_worker.error else validation_error
            claim_report = None
        if claim_report is not None and not claim_report.ok and _citation_repair_eligible(claim_report.errors):
            citation_repair["attempted"] = True
            citation_repair["initial_errors"] = list(claim_report.errors)
            try:
                summarizer_repair_worker = _isolated_role_completion(
                    "summarizer",
                    {
                        "operation": "repair_citations",
                        "claim_set": claim_set.canonical_payload(),
                        "verified_artifact_refs": [artifact.artifact_id],
                        "evidence_items": list(evidence_items),
                        "validation_errors": list(claim_report.errors),
                    },
                )
                repaired_claim_set = _claim_set_from_payload(summarizer_repair_worker.candidate)
                repaired_report = ClaimSetValidator().validate(
                    repaired_claim_set,
                    evidence_pack=evidence_pack,
                    verified_artifacts={artifact.artifact_id: (artifact, artifact_payload)},
                    current_task_id=task_id,
                    current_session_id=grant.session_id,
                    evidence_session_id=grant.session_id,
                )
                citation_repair["repair_errors"] = list(repaired_report.errors)
                if repaired_report.ok:
                    claim_set, claim_report = repaired_claim_set, repaired_report
                    citation_repair["succeeded"] = True
                    state["summarizer_citation_repair_used"] = True
                else:
                    summarizer_error = ";".join(repaired_report.errors)
            except Exception as exc:
                summarizer_error = f"citation_repair_{type(exc).__name__}:{exc}"
                citation_repair["repair_errors"] = [summarizer_error]
        if claim_report is None or not claim_report.ok:
            state["claim_fallback"] = True
            fallback_reasons = state["fallback_reasons"]
            assert isinstance(fallback_reasons, dict)
            fallback_reasons["summarizer"] = summarizer_error or "claim_validation_failed"
            item_id = evidence_items[0]["id"] if evidence_items else ""
            item_locator = evidence_items[0]["locator"] if evidence_items else ""
            claim_set = ClaimSet(
                claim_set_id="fallback-claims",
                task_id=task_id,
                claims=(Claim(
                    claim_id="metric-series",
                    claim_text="A verified revenue metric series was materialized.",
                    claim_type="fact",
                    supporting_evidence_item_ids=(item_id,) if item_id else (),
                    supporting_artifact_ref_ids=(artifact.artifact_id,),
                    citation_locators=(item_locator,) if item_locator else (),
                ),),
            )
            claim_report = ClaimSetValidator().validate(
                claim_set,
                evidence_pack=evidence_pack,
                verified_artifacts={artifact.artifact_id: (artifact, artifact_payload)},
                current_task_id=task_id,
                current_session_id=grant.session_id,
                evidence_session_id=grant.session_id,
            )
        role_trace_paths["summarizer"] = _write_role_trace(
            run_dir,
            "summarizer",
            worker=summarizer_worker,
            selected=claim_set.canonical_payload(),
            validation={"ok": claim_report.ok, "status": claim_report.status.value, "errors": list(claim_report.errors), "citation_repair": citation_repair},
            fallback_used=bool(state["claim_fallback"]),
            error=summarizer_error,
        )
        if not claim_report.ok:
            return AdaptiveStepResult(grant_hash=grant.grant_hash, success=False, attempt_id=grant.attempt_id, error_code="claim_validation_failed")
        state["artifact"] = artifact
        state["artifact_payload"] = artifact_payload
        state["claim_set"] = claim_set.canonical_payload()
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            attempt_id=grant.attempt_id,
            output_refs=("claim-report",),
            output_ref_kinds=("execution_artifact",),
        )

    dispatch_context = AdaptiveDispatchContext(
        registry=registry,
        retrieval_adapter=AdaptiveRetrievalAdapter(retrieve_query),
        retrieval_request_factory=retrieval_request_factory,
        retrieval_expansion_factory=retrieval_expansion_factory,
        retrieval_result_observer=retrieval_result_observer,
        allowed_corpus_scope_ids=("local-long-doc",),
        transform_program_factory=transform_program_factory,
        output_schema_by_capability={"extract_metric_series_v1": {"quarter": "string", "revenue_musd": "number"}},
        builtin_handlers={"compose_cited_report_v1": compose_report_handler},
    )

    def controlled_replan(previous, completed_step_ids: tuple[str, ...], error_code: str):
        """Replace only an unexecuted failed subgraph with the registered plan.

        The replacement is deterministic and must pass the same PlanPolicy as a
        model proposal.  It is a recovery path, not evidence that the original
        model plan succeeded, so strict model-path acceptance records it.
        """
        replacement_outcome = policy.validate(
            pack.fallback_proposal(envelope),
            envelope,
        )
        records = state["replan_records"]
        assert isinstance(records, list)
        records.append({
            "trigger_error": error_code,
            "completed_step_ids": list(completed_step_ids),
            "replacement_policy_status": replacement_outcome.report.status.value,
            "replacement_plan_hash": (
                replacement_outcome.approved_plan.approved_plan_hash
                if replacement_outcome.approved_plan is not None
                else ""
            ),
        })
        if replacement_outcome.approved_plan is None:
            return None
        state["controlled_replan_used"] = True
        return replacement_outcome.approved_plan

    runtime_result = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id=f"trace-{task_id}", task_id=task_id, canonical_task_spec_hash=envelope.canonical_task_spec_hash,
        envelope=envelope, approved_plan=approved, registry=registry, runtime_root=str(run_dir),
        workspace_root_id="workspace-root", dispatcher=AdaptiveCapabilityDispatcher(context=dispatch_context),
        proposal_hash=proposal.proposal_hash,
        planner_model_id=proposal.model_id,
        planner_raw_output_hash=proposal.raw_output_hash,
        proposal_valid=initial_outcome.approved_plan is not None,
        policy_rejected=initial_outcome.approved_plan is None,
        repair_used=outcome.repair_used,
        fallback_used=outcome.fallback_used,
        replan=controlled_replan,
    ))
    artifact = state.get("artifact")
    model_path_success = (
        runtime_result.completed
        and not used_fallback
        and not bool(state["retriever_fallback"])
        and not bool(state["program_fallback"])
        and not bool(state["claim_fallback"])
        and not bool(state["controlled_replan_used"])
    )
    summary = {
        "schema_version": "statebus.adaptive_agent_live_smoke.v1",
        "workflow_mode": envelope.workflow_mode.value,
        "local_vllm_base_url": "http://127.0.0.1:53334/v1",
        "local_vllm_model": "qwen3-32b",
        "local_vllm_request_mode": "isolated_worker_per_completion",
        "embedding_mode": "local",
        "embedding_model_path": args.embedding_model_path,
        "embedding_device": args.embedding_device,
        "embedding_dims": state.get("embedding_dims", 0),
        "elapsed_ms": round((time.perf_counter_ns() - run_started_ns) / 1_000_000.0, 3),
        "proposal_hash": proposal.proposal_hash,
        "proposal_policy_status": initial_outcome.report.status.value,
        "initial_plan_policy_report": initial_outcome.report.canonical_payload(),
        "selected_plan_policy_status": outcome.report.status.value,
        "proposal_used_fallback": used_fallback,
        "approved_plan_hash": approved.approved_plan_hash,
        "approved_steps": [step.canonical_payload() for step in approved.steps],
        "runtime_signature": runtime_result.runtime_signature.canonical_payload() if runtime_result.runtime_signature else {},
        "runtime_completed": runtime_result.completed,
        "runtime_plan_replaced": runtime_result.plan_replaced,
        "runtime_final_approved_plan_hash": runtime_result.approved_plan_hash,
        "runtime_telemetry_metrics": runtime_result.telemetry.summarize_task(task_id),
        "role_calls": ["planner", *state["role_calls"]],
        "role_trace_paths": dict(sorted(role_trace_paths.items())),
        "coverage": state.get("coverage", {}),
        "coverage_decisions": state.get("coverage_decisions", []),
        "state_consumption": state.get("state_consumption", {}),
        "retriever_fallback": state["retriever_fallback"],
        "program_fallback": state["program_fallback"],
        "claim_fallback": state["claim_fallback"],
        "summarizer_citation_repair_used": state["summarizer_citation_repair_used"],
        "controlled_replan_used": state["controlled_replan_used"],
        "replan_records": state["replan_records"],
        "fallback_reasons": state["fallback_reasons"],
        "model_path_success": model_path_success,
        "artifact": (artifact.registry_entry().small_index_payload() if isinstance(artifact, ExecutionArtifactRef) else {}),
        "claim_set": state.get("claim_set", {}),
    }
    (run_dir / "summary.json").write_text(stable_json_dumps(summary) + "\n", encoding="utf-8")
    analysis_path = _write_analysis(run_dir, summary)
    summary["analysis_path"] = str(analysis_path)
    (run_dir / "summary.json").write_text(stable_json_dumps(summary) + "\n", encoding="utf-8")
    print(stable_json_dumps({
        "ok": model_path_success,
        "runtime_completed": runtime_result.completed,
        "model_path_success": model_path_success,
        "run_dir": str(run_dir),
        "summary": summary,
    }))
    if args.require_model_success and not model_path_success:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(stable_json_dumps({"ok": False, "exception_type": type(exc).__name__, "exception": str(exc)}), flush=True)
        traceback.print_exc()
        raise
