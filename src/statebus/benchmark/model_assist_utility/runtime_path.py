from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import re
from typing import Callable, Mapping

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    CanonicalTaskSpec,
    CapabilityDescriptor,
    EvidenceRequest,
    ExecutionKind,
    PlanProposal,
    PlanStepProposal,
    RiskClass,
    RuntimeIdentity,
    TaskContractIdentity,
    WorkflowMode,
)
from statebus.refs import CanonicalEvidencePack, EvidenceItem, FragmentLocator
from statebus.runtime.adaptive_mainline import (
    AdaptiveMainlineBindings,
    AdaptiveMainlineRequest,
)
from statebus.runtime.adaptive_dispatcher import (
    AdaptiveDispatchError,
    TransformProgramRepairFactory,
)
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.driver import RuntimeDriver
from statebus.runtime.plan_policy import PlanPolicyValidator
from statebus.runtime.provider_registry import (
    ExecutionProviderRegistry,
    PhysicalProviderImplementation,
    project_legacy_provider,
)
from statebus.runtime.retrieval_adapter import AdaptiveRetrievalAdapter
from statebus.runtime.role_providers import (
    BoundProviderHandler,
    ExecutorCandidateReviewBinding,
    ProviderRequest,
)
from statebus.utils import sha256_digest


UTILITY_SUITE_ID = "model_assist_utility_v1"
UTILITY_RETRIEVE_CAPABILITY = "model_assist_utility.retrieve"
UTILITY_EXECUTOR_CAPABILITY = "model_assist_utility.executor"
UTILITY_SUMMARIZER_CAPABILITY = "model_assist_utility.summarizer"
UTILITY_EVIDENCE_CONTRACT = "statebus.model_assist_utility.evidence.v1"
UTILITY_ARTIFACT_CONTRACT = "statebus.model_assist_utility.artifact.v1"
UTILITY_REPORT_CONTRACT = "statebus.model_assist_utility.report.v1"
UTILITY_CORPUS_SCOPE = "model_assist_utility_frozen_sources"


def _safe_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_.-")
    return normalized or "utility"


def _evidence_pack(
    *,
    task_id: str,
    source_hash: str,
    rows: tuple[dict[str, object], ...],
    additional_evidence: tuple[dict[str, object], ...],
) -> CanonicalEvidencePack:
    items: list[EvidenceItem] = []
    for index, row in enumerate(rows):
        locator = str(row.get("source_locator", "")).strip()
        if not locator:
            raise ValueError(f"utility_source_locator_missing:{index}")
        items.append(EvidenceItem(
            item_id=f"{task_id}:row:{index:05d}",
            bucket="structured_evidence",
            locator=FragmentLocator(source_doc_hash=source_hash, fragment_id=locator),
            rendered_text=str(row),
            source_name=locator.split("#", 1)[0],
            rank=index,
            metadata={"structured_row": dict(row)},
        ))
    facts: list[EvidenceItem] = []
    for index, fact in enumerate(additional_evidence):
        locator = str(fact.get("source_locator", "")).strip()
        if not locator:
            raise ValueError(f"utility_fact_locator_missing:{index}")
        facts.append(EvidenceItem(
            item_id=f"{task_id}:fact:{index:04d}",
            bucket="hard_facts",
            locator=FragmentLocator(source_doc_hash=source_hash, fragment_id=locator),
            rendered_text=str(fact.get("text", fact)),
            source_name=locator.split("#", 1)[0],
            rank=index,
            metadata={"utility_fact": dict(fact)},
        ))
    return CanonicalEvidencePack(
        pack_id=f"utility-evidence-{task_id}",
        task_id=task_id,
        source_doc_hashes=(source_hash,),
        hard_facts=tuple(facts),
        structured_evidence=tuple(items),
        budget_meta={"suite_id": UTILITY_SUITE_ID, "source_row_count": len(items)},
    )


def run_utility_runtime(
    *,
    slot_id: str,
    run_id: str,
    runtime_root: Path,
    workspace_root: Path,
    task_question: str,
    task_family: str,
    task_arguments: Mapping[str, object],
    source_hash: str,
    rows: tuple[dict[str, object], ...],
    additional_evidence: tuple[dict[str, object], ...] = (),
    input_fields: Mapping[str, str],
    output_schema: Mapping[str, str],
    executor_handler: BoundProviderHandler,
    summarizer_handler: BoundProviderHandler,
    executor_candidate_review: ExecutorCandidateReviewBinding | None = None,
    transform_program_repair_factory: TransformProgramRepairFactory | None = None,
    allow_evidence_replan: bool = False,
):
    """Execute one utility slot through the canonical bounded Runtime path."""
    if executor_candidate_review is not None and os.environ.get("STATEBUS_MODEL_ASSIST_UTILITY_ENABLED") != "1":
        raise ValueError("model_assist_utility_flag_required_for_candidate_review")
    safe_slot = _safe_id(slot_id)
    runtime_task_id = f"utility-{safe_slot}"
    task_spec = CanonicalTaskSpec(
        task_family=task_family,
        intent_op="analyze_authorized_evidence",
        target_entities=(task_family,),
        time_scope="2026Q1,2026Q3",
        required_outputs=tuple(output_schema),
        arguments={"question": task_question, **dict(task_arguments)},
    )
    identity = RuntimeIdentity(
        external_case_id=slot_id,
        runtime_task_id=runtime_task_id,
        run_id=_safe_id(run_id),
        session_id=f"{runtime_task_id}-session",
        trace_id=f"{runtime_task_id}-trace",
        task_contract=TaskContractIdentity.from_canonical_task_spec(task_spec),
    )
    evidence_pack = _evidence_pack(
        task_id=runtime_task_id,
        source_hash=source_hash,
        rows=rows,
        additional_evidence=additional_evidence,
    )

    registry = CapabilityRegistry()
    registry.register(CapabilityDescriptor(
        capability_id=UTILITY_RETRIEVE_CAPABILITY,
        owner_role="retriever",
        description="Retrieve the frozen, task-authorized utility evidence pack.",
        input_ref_kinds=(),
        input_contract_version="statebus.model_assist_utility.input.v1",
        output_ref_kinds=("canonical_evidence_pack",),
        output_contract_version=UTILITY_EVIDENCE_CONTRACT,
        execution_kind=ExecutionKind.RETRIEVAL_ADAPTER,
        side_effect_class=RiskClass.READ_ONLY,
        max_runtime_ms=30_000,
        supports_replay=False,
    ))
    registry.register(CapabilityDescriptor(
        capability_id=UTILITY_EXECUTOR_CAPABILITY,
        owner_role="executor",
        description="Generate a bounded TransformProgram for authorized utility evidence.",
        input_ref_kinds=("canonical_evidence_pack",),
        input_contract_version=UTILITY_EVIDENCE_CONTRACT,
        output_ref_kinds=("execution_artifact",),
        output_contract_version=UTILITY_ARTIFACT_CONTRACT,
        execution_kind=ExecutionKind.TRANSFORM_DSL,
        side_effect_class=RiskClass.WORKSPACE_WRITE,
        max_runtime_ms=60_000,
        supports_replay=False,
        required_input_ref_kinds=("canonical_evidence_pack",),
        validator_ids=("generic_analysis",),
    ))
    registry.register(CapabilityDescriptor(
        capability_id=UTILITY_SUMMARIZER_CAPABILITY,
        owner_role="summarizer",
        description="Compose a cited ClaimSet from verified utility artifacts.",
        input_ref_kinds=("canonical_evidence_pack", "execution_artifact"),
        input_contract_version=UTILITY_ARTIFACT_CONTRACT,
        output_ref_kinds=("execution_artifact",),
        output_contract_version=UTILITY_REPORT_CONTRACT,
        execution_kind=ExecutionKind.RUNTIME_BUILTIN,
        side_effect_class=RiskClass.WORKSPACE_WRITE,
        max_runtime_ms=60_000,
        supports_replay=False,
        required_input_ref_kinds=("canonical_evidence_pack", "execution_artifact"),
    ))

    provider_registry = ExecutionProviderRegistry()
    for capability in registry.descriptors():
        provider = project_legacy_provider(capability)
        provider_registry.register(provider)
        provider_registry.register_implementation(
            PhysicalProviderImplementation.from_descriptor(provider)
        )

    replan_budget = 1 if allow_evidence_replan else 0
    role_cardinality = {
        "retriever": (1, 1),
        "executor": (1, 2 if allow_evidence_replan else 1),
        "summarizer": (1, 1),
    }
    envelope = AdaptiveTaskEnvelope(
        task_id=runtime_task_id,
        canonical_task_spec_hash=task_spec.spec_hash,
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id=UTILITY_SUITE_ID,
        allowed_capability_ids=(
            UTILITY_RETRIEVE_CAPABILITY,
            UTILITY_EXECUTOR_CAPABILITY,
            UTILITY_SUMMARIZER_CAPABILITY,
        ),
        allowed_output_contracts=(
            UTILITY_EVIDENCE_CONTRACT,
            UTILITY_ARTIFACT_CONTRACT,
            UTILITY_REPORT_CONTRACT,
        ),
        allowed_memory_policies=("none",),
        role_cardinality=role_cardinality,
        max_plan_steps=3,
        max_dependency_depth=3,
        max_retrieval_steps=1,
        max_execution_runtime_ms=150_000,
        max_replans=replan_budget,
        max_retrieval_expansions=0,
        max_total_attempts=3 + replan_budget,
        risk_class=RiskClass.WORKSPACE_WRITE,
    )

    retrieve_step = PlanStepProposal(
        step_id="retrieve",
        role="retriever",
        capability_id=UTILITY_RETRIEVE_CAPABILITY,
        goal="retrieve all authorized evidence refs for this frozen utility case",
        output_contract_version=UTILITY_EVIDENCE_CONTRACT,
    )
    executor_step = PlanStepProposal(
        step_id="execute",
        role="executor",
        capability_id=UTILITY_EXECUTOR_CAPABILITY,
        goal="generate and validate the deterministic transform over authorized evidence",
        depends_on=("retrieve",),
        input_ref_ids=("retrieve-output",),
        input_ref_kinds=("canonical_evidence_pack",),
        output_contract_version=UTILITY_ARTIFACT_CONTRACT,
        on_failure="request_replan" if allow_evidence_replan else "fail",
    )
    summarizer_step = PlanStepProposal(
        step_id="summarize",
        role="summarizer",
        capability_id=UTILITY_SUMMARIZER_CAPABILITY,
        goal="compose a cited ClaimSet from the verified artifact and authorized evidence",
        depends_on=("execute", "retrieve"),
        input_ref_ids=("execute-output", "retrieve-output"),
        input_ref_kinds=("execution_artifact", "canonical_evidence_pack"),
        output_contract_version=UTILITY_REPORT_CONTRACT,
    )
    proposal = PlanProposal(
        proposal_id=f"{runtime_task_id}-proposal",
        task_id=runtime_task_id,
        steps=(retrieve_step, executor_step, summarizer_step),
        final_output_contract_version=UTILITY_REPORT_CONTRACT,
        requested_memory_policy="none",
        model_id="utility-controller",
        raw_output_hash=sha256_digest({"task_spec": task_spec.canonical_payload(), "slot_id": slot_id}),
    )

    def retrieve_query(_query: str, request: EvidenceRequest) -> CanonicalEvidencePack:
        if request.task_id != runtime_task_id or request.corpus_scope_ids != (UTILITY_CORPUS_SCOPE,):
            raise ValueError("utility_retrieval_scope_mismatch")
        return evidence_pack

    def retrieval_request(step: PlanStepProposal, grant) -> EvidenceRequest:
        return EvidenceRequest(
            request_id=f"{runtime_task_id}-{step.step_id}-{grant.attempt_id}",
            task_id=grant.task_id,
            step_id=step.step_id,
            queries=(task_question,),
            evidence_types=("table",),
            corpus_scope_ids=(UTILITY_CORPUS_SCOPE,),
            memory_policy="none",
            max_candidates=max(1, len(rows) + len(additional_evidence)),
            max_prompt_visible_bytes=262_144,
            required_locator=True,
        )

    def replan_for_evidence_review(current_plan, completed_step_ids, failed_step, error_code):
        if (
            not allow_evidence_replan
            or error_code != "model_assist_review_required"
            or failed_step.step_id != "execute"
            or "retrieve" not in completed_step_ids
        ):
            return None
        full_executor = replace(
            failed_step,
            step_id="execute_full",
            goal="recheck the evidence choice with the full authorized bundle",
            on_failure="fail",
        )
        preserved_retriever = next(
            step for step in current_plan.steps if step.step_id == "retrieve"
        )
        new_summarizer = replace(
            next(step for step in current_plan.steps if step.role == "summarizer"),
            depends_on=("execute_full", "retrieve"),
            input_ref_ids=("execute_full-output", "retrieve-output"),
        )
        replacement_proposal = PlanProposal(
            proposal_id=f"{runtime_task_id}-full-evidence-replan",
            task_id=runtime_task_id,
            steps=(preserved_retriever, full_executor, new_summarizer),
            final_output_contract_version=UTILITY_REPORT_CONTRACT,
            requested_memory_policy="none",
            model_id="utility-controller",
            raw_output_hash=sha256_digest({"source_plan": current_plan.approved_plan_hash, "reason": error_code}),
        )
        outcome = PlanPolicyValidator(registry).validate(
            replacement_proposal,
            envelope,
        )
        return outcome.approved_plan

    bindings = AdaptiveMainlineBindings(
        retrieval_adapter=AdaptiveRetrievalAdapter(retrieve_query),
        retrieval_request_factory=retrieval_request,
        allowed_corpus_scope_ids=(UTILITY_CORPUS_SCOPE,),
        bound_provider_handlers={
            UTILITY_EXECUTOR_CAPABILITY: executor_handler,
            UTILITY_SUMMARIZER_CAPABILITY: summarizer_handler,
        },
        transform_program_repair_factory=transform_program_repair_factory,
        executor_candidate_review=executor_candidate_review,
        executor_candidate_review_enabled=executor_candidate_review is not None,
        input_schema_by_step={
            "execute": dict(input_fields),
            "execute_full": dict(input_fields),
        },
        output_schema_by_step={
            "execute": dict(output_schema),
            "execute_full": dict(output_schema),
        },
    )
    request = AdaptiveMainlineRequest(
        trace_id=identity.trace_id,
        task_id=runtime_task_id,
        canonical_task_spec_hash=task_spec.spec_hash,
        canonical_task_spec=task_spec,
        envelope=envelope,
        registry=registry,
        runtime_root=runtime_root,
        workspace_root=workspace_root,
        propose_plan=lambda: proposal,
        bindings=bindings,
        available_input_refs={},
        provider_registry=provider_registry,
        replan_for_step=replan_for_evidence_review,
        runtime_identity=identity,
        memory_commit_enabled=False,
        state_pool_mode="mmap",
    )
    return RuntimeDriver().run_mode("adaptive_bounded", adaptive_request=request)


__all__ = [
    "UTILITY_ARTIFACT_CONTRACT",
    "UTILITY_EVIDENCE_CONTRACT",
    "UTILITY_EXECUTOR_CAPABILITY",
    "UTILITY_REPORT_CONTRACT",
    "UTILITY_SUITE_ID",
    "run_utility_runtime",
]
