from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    ApprovedPlanBundle,
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
from statebus.runtime.static_role_recipe import (
    StaticRoleRecipe,
    StaticRoleRecipeStep,
    compile_static_role_recipe_plan,
)


class FixedMainlineError(ValueError):
    pass


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

    def __post_init__(self) -> None:
        if (self.recipe is None) == (self.approved_plan_bundle is None):
            raise FixedMainlineError("fixed_plan_source_required")
        if self.runtime_identity.task_contract.contract_hash != self.canonical_task_spec.spec_hash:
            raise FixedMainlineError("fixed_task_contract_identity_mismatch")

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


def _compatibility_registry(recipe: StaticRoleRecipe) -> CapabilityRegistry:
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
                max_runtime_ms=1_000,
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
) -> ExecutionProviderRegistry:
    """Build the session-frozen physical snapshots for the fixed providers."""
    registry = ExecutionProviderRegistry()
    for step in recipe.steps:
        provider = project_legacy_provider(capability_registry.get(step.capability_id))
        registry.register(provider)
        handler = _FIXED_BOUND_PROVIDER_BY_ROLE[step.role]
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
        max_execution_runtime_ms=1_000 * len(recipe.steps),
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
    registry = _compatibility_registry(recipe)
    provider_registry = request.provider_registry or _fixed_provider_registry(
        recipe=recipe, capability_registry=registry
    )
    envelope = _strict_envelope(
        runtime_identity=request.runtime_identity,
        canonical_task_spec=request.canonical_task_spec,
        recipe=recipe,
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
        bindings=(request.bindings or AdaptiveMainlineBindings(
            retrieval_adapter=AdaptiveRetrievalAdapter(_fixed_retrieve_query),
            allowed_corpus_scope_ids=("fixed-local",),
            output_schema_by_step={
                "execute": {
                    "quarter": "string",
                    "revenue_musd": "number",
                },
            },
            bound_provider_handlers={
                step.capability_id: _FIXED_BOUND_PROVIDER_BY_ROLE[step.role]
                for step in recipe.steps
            }
        )),
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
