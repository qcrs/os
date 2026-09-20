from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    ApprovedPlanBundle,
    CapabilityGrant,
    CapabilityDescriptor,
    Claim,
    ClaimSet,
    CanonicalTaskSpec,
    EvidenceRequest,
    ExecutionKind,
    RiskClass,
    RuntimeIdentity,
    TransformProgram,
    TransformStep,
    PlannerHandoff,
    PlanStepProposal,
    WorkflowMode,
)
from statebus.refs import CanonicalEvidencePack, EvidenceItem, TableCellLocator
from statebus.runtime.adaptive_mainline import (
    AdaptiveMainlineBindings,
    AdaptiveMainlineRequest,
)
from statebus.runtime.adaptive_runtime import AdaptiveStepResult
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.provider_registry import (
    ExecutionProviderRegistry,
    PhysicalProviderImplementation,
    project_legacy_provider,
)
from statebus.runtime.retrieval_adapter import AdaptiveRetrievalAdapter
from statebus.runtime.role_providers import (
    ProviderRequest,
    RolePathExecutorProvider,
    RolePathRetrieverProvider,
    RolePathSummarizerProvider,
    RolePathPlannerProvider,
)
from statebus.runtime.role_path import RolePathRunner
from statebus.runtime.semantic_plan import resolve_semantic_task_plan
from statebus.integrations.llm import LLMConfig, build_llm_client
from statebus.utils import sha256_digest, stable_json_dumps
from statebus.runtime.static_role_recipe import (
    StaticRoleRecipe,
    StaticRoleRecipeStep,
    compile_static_role_recipe_plan,
)


class FixedMainlineError(ValueError):
    pass


_DEFAULT_OPERATION_CATALOG = (
    "select",
    "rename",
    "sort",
    "filter_eq",
    "filter_in",
    "filter_range",
    "aggregate",
    "aggregate_grouped",
    "derive_safe",
    "compare_periods",
    "trend_series",
    "join_by_key",
    "anomaly_check",
    "anomaly_zscore",
    "limit",
)

_DETERMINISTIC_CAPABILITY_RUNTIME_MS = 1_000
_LIVE_PROVIDER_SETTLEMENT_BUDGET_MS = 5_000


def _public_provider_mapping(value: object) -> object:
    """Remove scorer-only fields before a live role sees controller context."""

    forbidden_tokens = (
        "expected",
        "gold",
        "oracle",
        "quality_check",
        "future_round",
        "hidden",
    )
    if isinstance(value, Mapping):
        projected: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            lowered = key.lower()
            if any(token in lowered for token in forbidden_tokens):
                continue
            projected[key] = _public_provider_mapping(raw_value)
        return projected
    if isinstance(value, (tuple, list)):
        return [_public_provider_mapping(item) for item in value]
    return value


def _payload_rows(payload: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    """Extract source-owned structured rows from a verified evidence payload."""

    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for bucket in ("hard_facts", "structured_evidence", "semantic_contexts", "lexical_hints"):
        items = payload.get(bucket, ())
        if not isinstance(items, (tuple, list)):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            metadata = item.get("metadata", {})
            row = metadata.get("structured_row") if isinstance(metadata, Mapping) else None
            if not isinstance(row, Mapping):
                continue
            normalized = {str(key): value for key, value in row.items()}
            identity = stable_json_dumps(normalized)
            if identity not in seen:
                seen.add(identity)
                rows.append(normalized)
    return tuple(rows)


def _live_observation(
    *,
    sink: dict[str, object] | None,
    runner: RolePathRunner,
    role: str,
    result: object | None = None,
    error: BaseException | None = None,
    role_observation: Mapping[str, object] | None = None,
) -> None:
    """Persist provider observations without changing Runtime authority."""

    if sink is None:
        return
    observed = dict(role_observation or {})
    result_usage = getattr(result, "usage", None)

    def _value(name: str) -> object | None:
        direct = getattr(result, name, None)
        if direct is not None:
            return direct
        if result_usage is not None:
            nested = getattr(result_usage, name, None)
            if nested is not None:
                return nested
        return observed.get(name)

    raw_text = _value("raw_text")
    raw_response_hash = _value("raw_response_hash")
    if not raw_response_hash and isinstance(raw_text, str) and raw_text:
        raw_response_hash = sha256_digest(raw_text.encode("utf-8"))
    invocation: dict[str, object] = {
        "role": role,
        "status": "error" if error is not None else "response_received",
        "model": str(_value("model") or ""),
        "latency_ms": _value("latency_ms"),
        "prompt_tokens": _value("prompt_tokens"),
        "completion_tokens": _value("completion_tokens"),
        "total_tokens": _value("total_tokens"),
        "raw_response_hash": raw_response_hash,
    }
    if error is not None:
        invocation.update({"error_type": type(error).__name__, "error": str(error)})
    sink.setdefault("role_invocations", []).append(invocation)
    sink["rendered_request_audit"] = {
        role_name: runner.rendered_request_audit_payload(role_name, include_content=False)
        for role_name in ("planner", "retriever", "executor", "summarizer")
    }
    sink["provider_request_events"] = [
        dict(event) for event in getattr(runner.llm_client, "request_events", ())
    ]


def _live_call(
    runner: RolePathRunner,
    sink: dict[str, object] | None,
    role: str,
    fn: Callable[[], Any],
) -> Any:
    take_role_observation = getattr(runner, "take_role_observation", None)
    if callable(take_role_observation):
        # A runner can be reused across cases; do not let a prior completion
        # satisfy the current role's telemetry contract.
        take_role_observation(role)
    try:
        result = fn()
    except BaseException as exc:
        observation = (
            take_role_observation(role)
            if callable(take_role_observation)
            else None
        )
        _live_observation(
            sink=sink,
            runner=runner,
            role=role,
            error=exc,
            role_observation=observation,
        )
        raise
    observation = (
        take_role_observation(role)
        if callable(take_role_observation)
        else None
    )
    _live_observation(
        sink=sink,
        runner=runner,
        role=role,
        result=result,
        role_observation=observation,
    )
    return result


_OUTPUT_REF_KIND_BY_ROLE = {
    "planner": "planner_handoff",
    "retriever": "canonical_evidence_pack",
    "executor": "execution_artifact",
    "summarizer": "execution_artifact",
}

_COMPLETION_CRITERIA_BY_ROLE = {
    "planner": {
    },
    "retriever": {
        "min_locator_count": {"type": "integer", "minimum": 1, "maximum": 3},
        "required_evidence_types": {
            "type": "string_list",
            "allowed_values": ["semantic_context", "table"],
            "min_items": 1,
            "max_items": 2,
        },
        "max_conflicts": {"type": "integer", "minimum": 0, "maximum": 0},
    },
    "executor": {
        "min_rows": {"type": "integer", "minimum": 1, "maximum": 10_000},
        "required_fields": {
            "type": "string_list",
            "min_items": 1,
            "max_items": 64,
        },
    },
    "summarizer": {
        "min_locator_count": {"type": "integer", "minimum": 1, "maximum": 3},
        "required_evidence_types": {
            "type": "string_list",
            "allowed_values": ["semantic_context", "table"],
            "min_items": 1,
            "max_items": 2,
        },
        "max_conflicts": {"type": "integer", "minimum": 0, "maximum": 0},
    },
}


def _compatibility_result(step, grant, output_ref_kind: str) -> AdaptiveStepResult:
    return AdaptiveStepResult(
        grant_hash=grant.grant_hash,
        success=True,
        output_refs=(
            f"fixed-compatibility:{grant.task_id}:{step.step_id}:{grant.attempt_id}",
        ),
        output_ref_kinds=(output_ref_kind,),
        attempt_id=grant.attempt_id,
        metrics={"fixed_compatibility_handler_count": 1.0},
    )


def deterministic_retrieve_handler(
    _envelope, _approved_plan, step, grant, _attempt_workspace
) -> AdaptiveStepResult:
    return _compatibility_result(step, grant, "canonical_evidence_pack")


def _fixed_planner_candidate(request: ProviderRequest) -> PlannerHandoff:
    return PlannerHandoff(
        task_id=request.envelope.task_id,
        canonical_task_spec_hash=request.envelope.canonical_task_spec_hash,
        retrieval_objective={"query": "revenue", "evidence_types": ["table"]},
        planner_plan_payload={"steps": ["retrieve", "execute", "summarize"]},
        planner_scope_payload={"corpus_scope_ids": ["fixed-local"]},
        summary_hint="cite the verified metric",
        planner_raw_output_hash="fixed-planner-v1",
    )


def deterministic_execute_handler(
    _envelope, _approved_plan, step, grant, _attempt_workspace
) -> AdaptiveStepResult:
    return _compatibility_result(step, grant, "execution_artifact")


def deterministic_summarize_handler(
    _envelope, _approved_plan, step, grant, _attempt_workspace
) -> AdaptiveStepResult:
    return _compatibility_result(step, grant, "execution_artifact")


def _fixed_retrieve_query(
    _query: str,
    request: EvidenceRequest,
) -> CanonicalEvidencePack:
    parts = _query.split(":", 2)
    ticker = parts[1] if len(parts) > 1 else "ACME"
    quarter = parts[2] if len(parts) > 2 else "2026Q1"
    values = {
        ("ACME", "2026Q1"): 120.0,
        ("ACME", "2026Q2"): 132.0,
        ("ACME", "2026Q3"): 145.0,
        ("ACME", "2025Q4"): 109.0,
        ("BETA", "2026Q1"): 87.0,
    }
    value = values.get((ticker, quarter), 120.0)
    item_id = f"fixed-{ticker.lower()}-{quarter.lower()}"
    return CanonicalEvidencePack(
        pack_id=f"fixed-pack-{request.task_id}",
        task_id=request.task_id,
        source_doc_hashes=(f"fixed-doc-{ticker.lower()}-{quarter.lower()}",),
        structured_evidence=(
            EvidenceItem(
                item_id=item_id,
                bucket="structured_evidence",
                locator=TableCellLocator(
                    source_doc_hash=f"fixed-doc-{ticker.lower()}-{quarter.lower()}",
                    table_id="income",
                    row_idx=1,
                    col_idx=1,
                ),
                metadata={
                    "structured_row": {
                        "quarter": quarter,
                        "revenue_musd": value,
                    }
                },
            ),
        ),
    )


def _fixed_retrieval_candidate(request: ProviderRequest) -> EvidenceRequest:
    spec = request.role_context.canonical_task_spec
    arguments = getattr(spec, "arguments", {}) if spec is not None else {}
    ticker = str(arguments.get("ticker", "ACME"))
    quarter = str(arguments.get("quarter", "2026Q1"))
    metric = str(arguments.get("metric", "revenue"))
    return EvidenceRequest(
        request_id=f"fixed-retrieval-{request.bound_grant.grant.attempt_id}",
        task_id=request.envelope.task_id,
        step_id=request.step.step_id,
        queries=(f"{metric}:{ticker}:{quarter}",),
        evidence_types=("table",),
        corpus_scope_ids=("fixed-local",),
        memory_policy="none",
        required_locator=True,
        source_plan_step_id=request.step.step_id,
    )


def _fixed_executor_candidate(request: ProviderRequest) -> TransformProgram:
    return TransformProgram(
        program_id=f"fixed-executor-{request.bound_grant.grant.attempt_id}",
        input_artifact_refs=(request.provider_input_refs[0],),
        operations=(
            TransformStep("select", {"columns": ["quarter", "revenue_musd"]}),
        ),
        output_contract_version=request.step.output_contract_version,
    )


def _fixed_summarizer_candidate(request: ProviderRequest) -> ClaimSet:
    # Dependency order is Runtime-owned. The final input is the verified
    # executor artifact once the dispatcher reaches this provider.
    if not request.provider_input_refs:
        raise ValueError("fixed_summarizer_requires_executor_input")
    artifact_ref = next(
        str(item["ref_id"])
        for item in reversed(request.role_context.verified_input_payloads)
        if item.get("kind") == "execution_artifact"
    )
    rows = next(
        (item["payload"].get("rows", ()) for item in request.role_context.verified_input_payloads
         if item.get("kind") == "execution_artifact"),
        (),
    )
    row = dict(rows[0]) if rows else {"quarter": "2026Q1", "revenue_musd": 120.0}
    evidence_payload = next(
        (item.get("payload", {}) for item in request.role_context.verified_input_payloads
         if item.get("kind") == "canonical_evidence_pack"),
        {},
    )
    evidence_items = evidence_payload.get("structured_evidence", ()) if isinstance(evidence_payload, dict) else ()
    evidence_item_id = str(evidence_items[0].get("item_id", "fixed-revenue-q1")) if evidence_items else "fixed-revenue-q1"
    quarter = str(row.get("quarter", "2026Q1"))
    value = float(row.get("revenue_musd", 0.0))
    return ClaimSet(
        claim_set_id=f"fixed-claims-{request.bound_grant.grant.attempt_id}",
        task_id=request.envelope.task_id,
        claims=(
            Claim(
                claim_id=evidence_item_id,
                claim_text=f"Revenue was {value:g} million USD in {quarter}.",
                claim_type="fact",
                supporting_evidence_item_ids=(evidence_item_id,),
                supporting_artifact_ref_ids=(artifact_ref,),
                citation_locators=(f"income:1:1",),
                numeric_fields={"revenue_musd": value},
            ),
        ),
    )


_FIXED_BOUND_PROVIDER_BY_ROLE = {
    "planner": RolePathPlannerProvider(_fixed_planner_candidate),
    "retriever": RolePathRetrieverProvider(_fixed_retrieval_candidate),
    "executor": RolePathExecutorProvider(_fixed_executor_candidate),
    "summarizer": RolePathSummarizerProvider(_fixed_summarizer_candidate),
}


def _live_provider_handlers(
    request: "FixedMainlineRequest",
    *,
    recipe: StaticRoleRecipe,
) -> tuple[
    dict[str, object],
    Callable[
        [PlanStepProposal, CapabilityGrant, str, tuple[dict[str, object], ...], tuple[str, ...]],
        TransformProgram,
    ],
]:
    """Build role-local live handlers over the existing RolePathRunner seam."""

    config = request.llm_config or LLMConfig.from_runtime().with_mode("local_vllm")
    if not config.use_api:
        raise FixedMainlineError("fixed_live_provider_requires_api_llm")
    runner = request.role_path_runner or RolePathRunner(
        llm_client=build_llm_client(config),
        json_response_max_attempts=1,
    )
    sink = request.provider_observation_sink
    spec = request.canonical_task_spec
    task_goal = request.task_goal.strip() or request.task_request.strip() or recipe.steps[0].goal
    task_theme = request.task_theme.strip() or spec.task_family
    corpus_scope_ids = tuple(request.corpus_scope_ids) or ("fixed-local",)
    evidence_types = tuple(request.evidence_types) or ("table",)
    output_fields = tuple(request.output_fields)
    operation_catalog = tuple(request.operation_catalog) or _DEFAULT_OPERATION_CATALOG
    operation_semantics = _public_provider_mapping(request.operation_semantics)
    if not isinstance(operation_semantics, dict):
        operation_semantics = {}

    def planner(request_: ProviderRequest) -> PlannerHandoff:
        query_text = request.task_request.strip() or task_goal
        result = _live_call(
            runner,
            sink,
            "planner",
            lambda: runner.plan_workflow(
                task_id=request_.envelope.task_id,
                task_group=spec.task_family,
                task_theme=task_theme,
                goal=task_goal,
                query_text=query_text,
                summary_hint=recipe.steps[-1].goal,
                visible_candidates=(),
                allowed_required_outputs=tuple(spec.required_outputs),
                target_entities=tuple(spec.target_entities),
                time_scope=spec.time_scope,
            ),
        )
        semantic_plan = resolve_semantic_task_plan(
            spec=spec,
            goal=task_goal,
            fallback_query_text=query_text,
            model_payload=result.workflow_payload,
        )
        if not semantic_plan.semantic_plan_valid:
            errors = ",".join(semantic_plan.validation_errors) or "unknown"
            raise FixedMainlineError(
                f"fixed_live_planner_semantic_plan_invalid:{errors}"
            )
        objectives = semantic_plan.effective_plan.get("retrieval_objectives", {})
        objective = (
            objectives.get("table_structure")
            if isinstance(objectives, Mapping) and "table" in evidence_types
            else objectives.get("semantic_chunk") if isinstance(objectives, Mapping) else None
        )
        if not isinstance(objective, Mapping) or not str(objective.get("query_text", "")).strip():
            raise FixedMainlineError("fixed_live_planner_effective_objective_missing")
        retrieval_objective = {
            "query": str(objective["query_text"]).strip(),
            "query_text": str(objective["query_text"]).strip(),
            "objective": str(objective.get("objective", "")).strip(),
            "evidence_types": list(objective.get("evidence_types", ())),
            "semantic_task_plan": semantic_plan.effective_plan,
            "objective_source": semantic_plan.objective_source,
        }
        handoff = PlannerHandoff(
            task_id=request_.envelope.task_id,
            canonical_task_spec_hash=request_.envelope.canonical_task_spec_hash,
            retrieval_objective=dict(_public_provider_mapping(retrieval_objective)),
            planner_plan_payload={
                "semantic_task_plan": dict(
                    _public_provider_mapping(semantic_plan.effective_plan)
                ),
                "objective_source": semantic_plan.objective_source,
            },
            planner_scope_payload={"corpus_scope_ids": list(corpus_scope_ids)},
            summary_hint=recipe.steps[-1].goal,
            semantic_plan_audit=dict(
                _public_provider_mapping(semantic_plan.audit_payload())
            ),
            planner_raw_output_hash=sha256_digest(result.raw_text.encode("utf-8")),
        )
        return handoff

    def retriever(request_: ProviderRequest) -> EvidenceRequest:
        result = _live_call(
            runner,
            sink,
            "retriever",
            lambda: runner.build_evidence_request(
                task_id=request_.envelope.task_id,
                step_id=request_.step.step_id,
                step_goal=request_.step.goal,
                corpus_scope_ids=corpus_scope_ids,
                evidence_types=evidence_types,
                target_entities=tuple(spec.target_entities),
                time_scope=spec.time_scope,
                task_goal=task_goal,
            ),
        )
        if result.memory_policy != "none":
            raise FixedMainlineError("fixed_live_retriever_memory_policy_not_allowed")
        return result

    def request_transform_program(
        step: PlanStepProposal,
        grant: CapabilityGrant,
        input_ref: str,
        rows: tuple[dict[str, object], ...],
        validation_errors: tuple[str, ...] = (),
    ) -> TransformProgram:
        input_schema = {input_ref: tuple(sorted({key for row in rows for key in row}))}
        desired_fields = output_fields or tuple(
            str(field)
            for field in step.completion_criteria.get("required_fields", ())
        ) or tuple(sorted(input_schema[input_ref]))
        repair_context: dict[str, object] = {}
        if validation_errors:
            repair_context = {
                "reason": "single_structured_dsl_repair",
                "validation_errors": list(validation_errors),
                "instruction": (
                    "Return a complete replacement program. Use only columns present in input_schema or produced "
                    "by an earlier operation, and preserve the same task goal and output contract."
                ),
            }
        return _live_call(
            runner,
            sink,
            "executor",
            lambda: runner.build_transform_program(
                program_id=(
                    f"live-fixed-repair-{grant.attempt_id}"
                    if validation_errors
                    else f"live-fixed-{grant.attempt_id}"
                ),
                authorized_input_refs=(input_ref,),
                input_schema=input_schema,
                output_contract_version=step.output_contract_version,
                operation_catalog=operation_catalog,
                step_goal=step.goal or task_goal,
                desired_output_fields=desired_fields,
                input_preview=rows[:4],
                operation_semantics=operation_semantics,
                repair_context=repair_context,
            ),
        )

    def executor(request_: ProviderRequest) -> TransformProgram:
        evidence_payload = next(
            (
                item.get("payload", {})
                for item in request_.role_context.verified_input_payloads
                if item.get("kind") == "canonical_evidence_pack"
            ),
            {},
        )
        if not isinstance(evidence_payload, Mapping):
            raise FixedMainlineError("fixed_live_executor_evidence_missing")
        rows = _payload_rows(evidence_payload)
        if not rows:
            raise FixedMainlineError("fixed_live_executor_source_rows_missing")
        input_ref = request_.provider_input_refs[0] if request_.provider_input_refs else ""
        if not input_ref:
            raise FixedMainlineError("fixed_live_executor_input_ref_missing")
        return request_transform_program(
            request_.step,
            request_.bound_grant.grant,
            input_ref,
            rows,
        )

    def repair_transform_program(
        step: PlanStepProposal,
        grant: CapabilityGrant,
        input_ref: str,
        rows: tuple[dict[str, object], ...],
        validation_errors: tuple[str, ...],
    ) -> TransformProgram:
        return request_transform_program(
            step,
            grant,
            input_ref,
            rows,
            validation_errors,
        )

    def summarizer(request_: ProviderRequest) -> ClaimSet:
        artifact_items = [
            item
            for item in request_.role_context.verified_input_payloads
            if item.get("kind") == "execution_artifact"
        ]
        evidence_items_payload = next(
            (
                item.get("payload", {})
                for item in request_.role_context.verified_input_payloads
                if item.get("kind") == "canonical_evidence_pack"
            ),
            {},
        )
        if not artifact_items or not isinstance(evidence_items_payload, Mapping):
            raise FixedMainlineError("fixed_live_summarizer_inputs_missing")
        final_artifact = artifact_items[-1]
        artifact_ref = str(final_artifact.get("ref_id", ""))
        rows = final_artifact.get("payload", {}).get("rows", ())
        if not artifact_ref or not isinstance(rows, (tuple, list)):
            raise FixedMainlineError("fixed_live_summarizer_artifact_rows_missing")
        evidence_items: list[dict[str, str]] = []
        for bucket in ("hard_facts", "structured_evidence", "semantic_contexts", "lexical_hints"):
            values = evidence_items_payload.get(bucket, ())
            if not isinstance(values, (tuple, list)):
                continue
            for item in values:
                if not isinstance(item, Mapping):
                    continue
                evidence_items.append({
                    "id": str(item.get("item_id", "")),
                    "locator": repr(item.get("locator")),
                    "text": str(item.get("rendered_text", "")),
                })
        artifact_summaries = ({
            "artifact_ref_id": artifact_ref,
            "status": "verified",
            "rows": [dict(row) for row in rows if isinstance(row, Mapping)],
        },)
        result = _live_call(
            runner,
            sink,
            "summarizer",
            lambda: runner.build_claim_set(
                task_id=request_.envelope.task_id,
                claim_set_id=f"live-fixed-claims-{request_.bound_grant.grant.attempt_id}",
                verified_artifact_refs=(artifact_ref,),
                evidence_items=tuple(evidence_items),
                task_goal=task_goal,
                artifact_summaries=artifact_summaries,
                expected_claim_count=len(artifact_summaries[0]["rows"]),
            ),
        )
        return result

    handlers_by_role = {
        "planner": RolePathPlannerProvider(planner),
        "retriever": RolePathRetrieverProvider(retriever),
        "executor": RolePathExecutorProvider(executor),
        "summarizer": RolePathSummarizerProvider(summarizer),
    }
    return (
        {
            step.capability_id: handlers_by_role[step.role]
            for step in recipe.steps
        },
        repair_transform_program,
    )


@dataclass(frozen=True)
class FixedMainlineRequest:
    runtime_identity: RuntimeIdentity
    canonical_task_spec: CanonicalTaskSpec
    runtime_root: Path
    workspace_root: Path
    recipe: StaticRoleRecipe | None = None
    approved_plan_bundle: ApprovedPlanBundle | None = None
    state_pool_mode: str = "mmap"
    cleanup_state: bool = True
    provider_registry: ExecutionProviderRegistry | None = None
    bindings: AdaptiveMainlineBindings | None = None
    provider_mode: str = "deterministic"
    llm_config: LLMConfig | None = None
    role_path_runner: RolePathRunner | None = None
    provider_observation_sink: dict[str, object] | None = None
    task_request: str = ""
    task_goal: str = ""
    task_theme: str = ""
    corpus_scope_ids: tuple[str, ...] = ("fixed-local",)
    evidence_types: tuple[str, ...] = ("table",)
    output_fields: tuple[str, ...] = ()
    operation_catalog: tuple[str, ...] = _DEFAULT_OPERATION_CATALOG
    operation_semantics: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (self.recipe is None) == (self.approved_plan_bundle is None):
            raise FixedMainlineError("fixed_plan_source_required")
        if self.runtime_identity.task_contract.contract_hash != self.canonical_task_spec.spec_hash:
            raise FixedMainlineError("fixed_task_contract_identity_mismatch")
        if self.provider_mode not in {"deterministic", "live"}:
            raise FixedMainlineError("fixed_provider_mode_invalid")

    def to_adaptive_mainline_request(self) -> AdaptiveMainlineRequest:
        return build_fixed_mainline_request(self)


def _recipe_from_bundle(bundle: ApprovedPlanBundle) -> StaticRoleRecipe:
    if (
        not bundle.verify_hash_links()
        or bundle.effective_proposal is None
        or bundle.approved_plan is None
        or not bundle.recipe_id
        or not bundle.recipe_version
    ):
        raise FixedMainlineError("fixed_approved_plan_bundle_invalid")
    recipe = StaticRoleRecipe(
        recipe_id=bundle.recipe_id,
        recipe_version=bundle.recipe_version,
        steps=tuple(
            StaticRoleRecipeStep.from_plan_step(step)
            for step in bundle.effective_proposal.steps
        ),
        final_output_contract=bundle.effective_proposal.final_output_contract_version,
        requested_memory_policy=bundle.effective_proposal.requested_memory_policy,
    )
    recipe.validate_fixed_topology()
    return recipe


def _fixed_role_runtime_budgets(
    request: FixedMainlineRequest,
    recipe: StaticRoleRecipe,
) -> dict[str, int]:
    if request.provider_mode == "deterministic":
        return {
            step.role: _DETERMINISTIC_CAPABILITY_RUNTIME_MS
            for step in recipe.steps
        }
    config = request.llm_config or LLMConfig.from_runtime().with_mode("local_vllm")
    return {
        step.role: max(
            _DETERMINISTIC_CAPABILITY_RUNTIME_MS,
            int(config.provider_config(config.role_config(step.role).provider).timeout_s * 1_000)
            + _LIVE_PROVIDER_SETTLEMENT_BUDGET_MS,
        )
        for step in recipe.steps
    }


def _compatibility_registry(
    recipe: StaticRoleRecipe,
    *,
    role_runtime_ms: Mapping[str, int] | None = None,
) -> CapabilityRegistry:
    runtime_budgets = dict(role_runtime_ms or {})
    output_kinds_by_step = {
        step.step_id: (
            ("execution_artifact", "canonical_evidence_pack")
            if step.role == "executor"
            else (_OUTPUT_REF_KIND_BY_ROLE[step.role],)
        )
        for step in recipe.steps
    }
    registry = CapabilityRegistry()
    for step in recipe.steps:
        dependency_kinds = tuple(
            dict.fromkeys(
                kind
                for dependency in step.depends_on
                for kind in output_kinds_by_step[dependency]
            )
        )
        accepted_input_kinds = tuple(
            dict.fromkeys((*step.input_ref_kinds, *dependency_kinds))
        )
        registry.register(
            CapabilityDescriptor(
                capability_id=step.capability_id,
                owner_role=step.role,
                description=f"Fixed typed {step.role} provider capability.",
                input_ref_kinds=accepted_input_kinds,
                required_input_ref_kinds=dependency_kinds,
                input_contract_version="statebus.fixed_compatibility_input.v1",
                output_ref_kinds=output_kinds_by_step[step.step_id],
                output_contract_version=step.output_contract_version,
                execution_kind={
                    "planner": ExecutionKind.RUNTIME_BUILTIN,
                    "retriever": ExecutionKind.RETRIEVAL_ADAPTER,
                    "executor": ExecutionKind.TRANSFORM_DSL,
                    # The bound provider seam dispatches the typed ClaimSet
                    # through the existing summarizer mechanism.
                    "summarizer": ExecutionKind.RUNTIME_BUILTIN,
                }[step.role],
                side_effect_class=RiskClass.READ_ONLY,
                max_runtime_ms=runtime_budgets.get(
                    step.role,
                    _DETERMINISTIC_CAPABILITY_RUNTIME_MS,
                ),
                supports_replay=False,
                validator_ids=("metric_series",) if step.role == "executor" else (),
                completion_criteria_contract=_COMPLETION_CRITERIA_BY_ROLE[step.role],
            )
        )
    return registry


def _fixed_provider_registry(
    *,
    recipe: StaticRoleRecipe,
    capability_registry: CapabilityRegistry,
    handlers_by_capability: Mapping[str, object] | None = None,
) -> ExecutionProviderRegistry:
    """Build the session-frozen physical snapshots for the fixed providers."""
    registry = ExecutionProviderRegistry()
    for step in recipe.steps:
        provider = project_legacy_provider(capability_registry.get(step.capability_id))
        registry.register(provider)
        handler = (handlers_by_capability or {}).get(
            step.capability_id,
            _FIXED_BOUND_PROVIDER_BY_ROLE[step.role],
        )
        registry.register_implementation(
            PhysicalProviderImplementation(
                provider_id=provider.provider_id,
                provider_version=provider.provider_version,
                implementation_kind=provider.implementation_kind,
                request_schema_version=provider.schema_version,
                client_factory_key=(
                    f"fixed_mainline:{step.role}:{type(handler).__qualname__}"
                ),
            )
        )
    return registry


def _strict_envelope(
    *,
    runtime_identity: RuntimeIdentity,
    canonical_task_spec: CanonicalTaskSpec,
    recipe: StaticRoleRecipe,
    registry: CapabilityRegistry,
) -> AdaptiveTaskEnvelope:
    role_counts = {
        role: sum(step.role == role for step in recipe.steps)
        for role in ("planner", "retriever", "executor", "summarizer")
    }
    return AdaptiveTaskEnvelope(
        task_id=runtime_identity.runtime_task_id,
        canonical_task_spec_hash=canonical_task_spec.spec_hash,
        workflow_mode=WorkflowMode.STRICT_FIXED,
        domain_pack_id="fixed-compatibility-bridge-v1",
        allowed_capability_ids=tuple(step.capability_id for step in recipe.steps),
        allowed_output_contracts=tuple(
            dict.fromkeys(step.output_contract_version for step in recipe.steps)
        ),
        allowed_memory_policies=("none",),
        role_cardinality={role: (count, count) for role, count in role_counts.items()},
        max_plan_steps=len(recipe.steps),
        max_dependency_depth=len(recipe.steps),
        max_retrieval_steps=role_counts["retriever"],
        max_execution_runtime_ms=sum(
            registry.get(step.capability_id).max_runtime_ms
            for step in recipe.steps
        ),
        max_replans=0,
        max_retrieval_expansions=0,
        max_total_attempts=len(recipe.steps),
        risk_class=RiskClass.READ_ONLY,
        allow_llm_python=False,
    )


def build_fixed_mainline_request(request: FixedMainlineRequest) -> AdaptiveMainlineRequest:
    bundle = request.approved_plan_bundle
    recipe = request.recipe if bundle is None else _recipe_from_bundle(bundle)
    assert recipe is not None
    if recipe.requested_memory_policy != "none":
        raise FixedMainlineError("fixed_compatibility_memory_policy_must_be_none")
    registry = _compatibility_registry(
        recipe,
        role_runtime_ms=_fixed_role_runtime_budgets(request, recipe),
    )
    default_handlers = {
        step.capability_id: _FIXED_BOUND_PROVIDER_BY_ROLE[step.role]
        for step in recipe.steps
    }
    live_handlers: Mapping[str, object] = {}
    live_transform_program_repair_factory = None
    if request.provider_mode == "live":
        (
            live_handlers,
            live_transform_program_repair_factory,
        ) = _live_provider_handlers(request, recipe=recipe)
    custom_handlers = (
        dict(request.bindings.bound_provider_handlers)
        if request.bindings is not None
        else {}
    )
    effective_handlers: dict[str, object] = {
        **default_handlers,
        **custom_handlers,
        **dict(live_handlers),
    }
    executor_step = next(
        (step for step in recipe.steps if step.role == "executor"),
        None,
    )
    runtime_quality_semantics: dict[str, dict[str, object]] = {}
    if executor_step is not None and request.operation_semantics.get("dsl_operation"):
        runtime_quality_semantics[executor_step.capability_id] = dict(
            request.operation_semantics
        )
    provider_registry = request.provider_registry or _fixed_provider_registry(
        recipe=recipe,
        capability_registry=registry,
        handlers_by_capability=effective_handlers,
    )
    envelope = _strict_envelope(
        runtime_identity=request.runtime_identity,
        canonical_task_spec=request.canonical_task_spec,
        recipe=recipe,
        registry=registry,
    )
    if bundle is None:
        bundle = compile_static_role_recipe_plan(
            runtime_task_id=request.runtime_identity.runtime_task_id,
            envelope=envelope,
            recipe=recipe,
            registry=registry,
            runtime_identity=request.runtime_identity,
        ).approved_plan_bundle
    elif (
        bundle.runtime_task_id != request.runtime_identity.runtime_task_id
        or bundle.task_contract_hash != request.canonical_task_spec.spec_hash
        or bundle.logical_capability_registry_digest != registry.digest
    ):
        raise FixedMainlineError("fixed_approved_plan_bundle_scope_mismatch")

    if request.bindings is None:
        bindings = AdaptiveMainlineBindings(
            retrieval_adapter=AdaptiveRetrievalAdapter(_fixed_retrieve_query),
            allowed_corpus_scope_ids=("fixed-local",),
            output_schema_by_step={
                "execute": {
                    "quarter": "string",
                    "revenue_musd": "number",
                },
            },
            transform_program_repair_factory=live_transform_program_repair_factory,
            quality_semantics_by_capability=runtime_quality_semantics,
            bound_provider_handlers=effective_handlers,
        )
    else:
        bindings = replace(
            request.bindings,
            transform_program_repair_factory=(
                request.bindings.transform_program_repair_factory
                or live_transform_program_repair_factory
            ),
            quality_semantics_by_capability={
                **request.bindings.quality_semantics_by_capability,
                **runtime_quality_semantics,
            },
            bound_provider_handlers=effective_handlers,
        )

    return AdaptiveMainlineRequest(
        trace_id=request.runtime_identity.trace_id,
        task_id=request.runtime_identity.runtime_task_id,
        canonical_task_spec_hash=request.canonical_task_spec.spec_hash,
        canonical_task_spec=request.canonical_task_spec,
        envelope=envelope,
        registry=registry,
        runtime_root=Path(request.runtime_root),
        workspace_root=Path(request.workspace_root),
        propose_plan=None,
        approved_plan_bundle=bundle,
        bindings=bindings,
        state_pool_mode=request.state_pool_mode,
        cleanup_state=request.cleanup_state,
        memory_commit_enabled=False,
        runtime_compatibility_signature=registry.digest,
        runtime_identity=request.runtime_identity,
        provider_registry=provider_registry,
    )


__all__ = [
    "FixedMainlineError",
    "FixedMainlineRequest",
    "build_fixed_mainline_request",
    "deterministic_execute_handler",
    "deterministic_retrieve_handler",
    "deterministic_summarize_handler",
]
