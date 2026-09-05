from __future__ import annotations

from dataclasses import dataclass, field, replace
import inspect
import json
from pathlib import Path
import time
from typing import Callable, TYPE_CHECKING

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    ApprovedPlan,
    BoundCapabilityGrant,
    CapabilityGrant,
    CanonicalTaskSpec,
    ClaimSet,
    CodeGenerationPolicy,
    CodeGenerationRequest,
    CompatibilityVerdict,
    EvidenceCoverageStatus,
    EvidenceProjectionRequest,
    ExecutionKind,
    PlanStepProposal,
    RefStatus,
    ReplayClass,
    RiskClass,
    TransformProgram,
    TransformStep,
)
from statebus.memory import MemoryConsumptionRecord
from statebus.refs import CanonicalEvidencePack, ExecutionArtifactRef
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.capability_recompute import CapabilityRecomputeError, recompute_transform_program
from statebus.runtime.capability_validators import (
    CapabilityQualityContext,
    CapabilityValidatorRegistry,
    default_capability_validator_registry,
)
from statebus.runtime.evidence_projection import EvidenceProjectionAdapter
from statebus.runtime.llm_codeact import (
    LlmCodeActRunner,
    build_code_generation_prompt,
    code_generation_prompt_bundle_digest,
)
from statebus.runtime.evidence_coverage import EvidenceCoverageVerifier
from statebus.runtime.retrieval_adapter import (
    AdaptiveRetrievalAdapter,
    AdaptiveRetrievalResult,
    stable_fan_in_evidence_packs,
)
from statebus.runtime.provider_registry import project_legacy_capability
from statebus.runtime.transform_dsl import TransformDslInterpreter, TransformProgramError
from statebus.runtime.claims import ClaimSetValidator
from statebus.runtime.workspace import ArtifactLifecycleManager
from statebus.utils import sha256_digest, stable_json_dumps

if TYPE_CHECKING:
    from statebus.memory import MemoryIndexStore
    from statebus.runtime.adaptive_runtime import AdaptiveStepResult
    from statebus.runtime.workspace import WorkspaceManager
    from statebus.state import LayeredStateStore


class AdaptiveDispatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredAdaptiveArtifact:
    artifact: ExecutionArtifactRef
    rows: tuple[dict[str, object], ...]
    provenance_item_ids: tuple[str, ...] = ()


RetrievalRequestFactory = Callable[[PlanStepProposal, CapabilityGrant], "EvidenceRequest"]
RetrievalExpansionFactory = Callable[["EvidenceRequest", "EvidenceCoverageReport"], "EvidenceRequest | None"]
RetrievalResultObserver = Callable[[AdaptiveRetrievalResult, PlanStepProposal, CapabilityGrant], tuple["StateConsumptionRecord", ...]]
TransformProgramFactory = Callable[..., TransformProgram]
TransformProgramRepairFactory = Callable[
    [PlanStepProposal, CapabilityGrant, str, tuple[dict[str, object], ...], tuple[str, ...]],
    TransformProgram,
]
CodeSourceFactory = Callable[[CodeGenerationRequest, str], str]
CodeRepairFactory = Callable[[CodeGenerationRequest, str, str, tuple[str, ...]], str]
BuiltinHandler = Callable[[AdaptiveTaskEnvelope, ApprovedPlan, PlanStepProposal, CapabilityGrant, Path], "AdaptiveStepResult"]
ClaimSetFactory = Callable[..., ClaimSet]


@dataclass
class AdaptiveDispatchContext:
    registry: CapabilityRegistry
    validator_registry: CapabilityValidatorRegistry = field(default_factory=default_capability_validator_registry)
    evidence_packs: dict[str, CanonicalEvidencePack] = field(default_factory=dict)
    evidence_statuses: dict[str, EvidenceCoverageStatus] = field(default_factory=dict)
    evidence_ref_scopes: dict[str, tuple[str, str]] = field(default_factory=dict)
    artifacts: dict[str, StoredAdaptiveArtifact] = field(default_factory=dict)
    projection_reports: dict[str, object] = field(default_factory=dict)
    quality_reports: dict[str, object] = field(default_factory=dict)
    code_execution_records: dict[str, object] = field(default_factory=dict)
    code_policy_reports: dict[str, object] = field(default_factory=dict)
    claim_sets: dict[str, ClaimSet] = field(default_factory=dict)
    claim_validation_reports: dict[str, dict[str, object]] = field(default_factory=dict)
    retrieval_adapter: AdaptiveRetrievalAdapter | None = None
    retrieval_request_factory: RetrievalRequestFactory | None = None
    retrieval_expansion_factory: RetrievalExpansionFactory | None = None
    retrieval_result_observer: RetrievalResultObserver | None = None
    allowed_corpus_scope_ids: tuple[str, ...] = ()
    transform_program_factory: TransformProgramFactory | None = None
    transform_program_repair_factory: TransformProgramRepairFactory | None = None
    code_source_factory: CodeSourceFactory | None = None
    code_repair_factory: CodeRepairFactory | None = None
    code_policy_factory: Callable[[PlanStepProposal], CodeGenerationPolicy] | None = None
    # Controller-owned semantic contracts for registered bounded-Python
    # capabilities.  The Planner chooses a capability, never these formulas.
    codeact_contracts: dict[str, dict[str, object]] = field(default_factory=dict)
    quality_semantics_by_capability: dict[str, dict[str, object]] = field(default_factory=dict)
    output_schema_by_capability: dict[str, dict[str, str]] = field(default_factory=dict)
    output_schema_by_step: dict[str, dict[str, str]] = field(default_factory=dict)
    # The caller supplies an LLM-backed candidate factory only.  The Runtime
    # continues to select verified inputs, validate citations/numerics and
    # issue the final cited-report ArtifactRef.
    claim_set_factory: ClaimSetFactory | None = None
    builtin_handlers: dict[str, BuiltinHandler] = field(default_factory=dict)
    # Product-runtime infrastructure. Handlers receive authority through the
    # context assembled by AdaptiveMainlineRunner, never by diagnostics code.
    state_store: "LayeredStateStore | None" = None
    memory_store: "MemoryIndexStore | None" = None
    workspace_manager: "WorkspaceManager | None" = None
    socket_path: Path | None = None
    semantic_state_publications: dict[str, object] = field(default_factory=dict)
    semantic_state_selections: dict[str, object] = field(default_factory=dict)
    memory_match_results: dict[str, object] = field(default_factory=dict)
    memory_queries_by_task: dict[str, object] = field(default_factory=dict)
    memory_role_inputs_by_step: dict[str, tuple[dict[str, object], ...]] = field(
        default_factory=dict
    )
    memory_consumption_records: list[MemoryConsumptionRecord] = field(default_factory=list)
    execution_recipes_by_artifact: dict[str, dict[str, object]] = field(default_factory=dict)
    canonical_task_spec: CanonicalTaskSpec | None = None
    input_lineage_hashes: tuple[str, ...] = ()
    input_schema_digest: str = ""
    validator_digest: str = ""
    runtime_compatibility_signature: str = ""
    state_consumption_records: list[object] = field(default_factory=list)


class AdaptiveCapabilityDispatcher:
    """Execute only an already-approved capability under a one-attempt Grant."""

    def __init__(
        self,
        *,
        context: AdaptiveDispatchContext,
        projection_adapter: EvidenceProjectionAdapter | None = None,
        transform_interpreter: TransformDslInterpreter | None = None,
        codeact_runner: LlmCodeActRunner | None = None,
    ) -> None:
        self.context = context
        self.projection_adapter = projection_adapter or EvidenceProjectionAdapter()
        self.transform_interpreter = transform_interpreter or TransformDslInterpreter()
        self.codeact_runner = codeact_runner or LlmCodeActRunner(
            registry=context.registry,
            validator_registry=context.validator_registry,
        )
        self._handlers = {
            ExecutionKind.RETRIEVAL_ADAPTER: self._dispatch_retrieval,
            ExecutionKind.TRANSFORM_DSL: self._dispatch_transform_dsl,
            ExecutionKind.LLM_BOUNDED_PYTHON: self._dispatch_llm_python,
            ExecutionKind.RUNTIME_BUILTIN: self._dispatch_builtin,
        }

    def dispatch(
        self,
        *,
        envelope: AdaptiveTaskEnvelope,
        approved_plan: ApprovedPlan,
        step: PlanStepProposal,
        grant: BoundCapabilityGrant | CapabilityGrant,
        attempt_workspace: Path,
    ) -> "AdaptiveStepResult":
        from statebus.runtime.adaptive_runtime import AdaptiveStepResult

        plain_grant = grant.grant if isinstance(grant, BoundCapabilityGrant) else grant
        try:
            if not isinstance(grant, BoundCapabilityGrant):
                raise AdaptiveDispatchError("execution_binding_required")
            descriptor = self.context.registry.get(step.capability_id)
            execution_kind = self._validate_dispatch(
                envelope,
                approved_plan,
                step,
                plain_grant,
                grant,
            )
            handler = self._handlers[execution_kind]
            return handler(envelope, approved_plan, step, plain_grant, attempt_workspace)
        except (AdaptiveDispatchError, ValueError) as exc:
            return AdaptiveStepResult(
                grant_hash=plain_grant.grant_hash,
                success=False,
                attempt_id=plain_grant.attempt_id,
                error_code=str(exc) or type(exc).__name__,
            )

    def _dispatch_retrieval(
        self,
        envelope: AdaptiveTaskEnvelope,
        approved_plan: ApprovedPlan,
        step: PlanStepProposal,
        grant: CapabilityGrant,
        attempt_workspace: Path,
    ) -> "AdaptiveStepResult":
        from statebus.runtime.adaptive_runtime import AdaptiveStepResult

        if self.context.retrieval_adapter is None or self.context.retrieval_request_factory is None:
            raise AdaptiveDispatchError("retrieval_handler_not_registered")
        request = self.context.retrieval_request_factory(step, grant)
        def propose_expansion(report: "EvidenceCoverageReport") -> "EvidenceRequest | None":
            if self.context.retrieval_expansion_factory is None:
                return None
            return self.context.retrieval_expansion_factory(request, report)

        result: AdaptiveRetrievalResult = self.context.retrieval_adapter.run_with_single_expansion(
            request,
            allowed_corpus_scope_ids=self.context.allowed_corpus_scope_ids,
            propose_expansion=(propose_expansion if self.context.retrieval_expansion_factory is not None else None),
            max_expansions=1,
        )
        product_state_records: tuple[object, ...] = ()
        data_plane_events: tuple[dict[str, object], ...] = ()
        state_metrics: dict[str, float] = {}
        if result.retrieval_bundles:
            result, product_state_records, data_plane_events, state_metrics = self._consume_retrieval_semantic_state(
                result=result,
                envelope=envelope,
                approved_plan=approved_plan,
                step=step,
                grant=grant,
                attempt_workspace=attempt_workspace,
            )
            coverage_report = EvidenceCoverageVerifier().evaluate(result.evidence_pack, request)
            result = replace(
                result,
                coverage_reports=(
                    (*result.coverage_reports[:-1], coverage_report)
                    if result.coverage_reports
                    else (coverage_report,)
                ),
            )
        coverage = result.coverage_reports[-1] if result.coverage_reports else None
        if coverage is None or coverage.status != EvidenceCoverageStatus.COMPLETE:
            raise AdaptiveDispatchError("evidence_coverage_not_complete")
        ref_id = f"evidence:{grant.task_id}:{grant.step_id}:{grant.attempt_id}"
        self.context.evidence_packs[ref_id] = result.evidence_pack
        self.context.evidence_statuses[ref_id] = coverage.status
        self.context.evidence_ref_scopes[ref_id] = (grant.session_id, grant.attempt_id)
        observer_records = (
            self.context.retrieval_result_observer(result, step, grant)
            if self.context.retrieval_result_observer is not None
            else ()
        )
        state_consumption_records = tuple((*product_state_records, *observer_records))
        self.context.state_consumption_records.extend(state_consumption_records)
        evaluated_effect_records = tuple(
            record for record in state_consumption_records
            if record.behavioral_effect in {"changed", "no_effect"}
        )
        report_hashes = tuple(sha256_digest(report.canonical_payload()) for report in result.coverage_reports)
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            attempt_id=grant.attempt_id,
            output_refs=(ref_id,),
            output_ref_kinds=("canonical_evidence_pack",),
            validator_report_hashes=report_hashes,
            evidence_coverage_report_hashes=report_hashes,
            evidence_coverage_decision_records=tuple(
                decision.canonical_payload() for decision in result.coverage_decisions
            ),
            state_consumption_records=state_consumption_records,
            data_plane_events=data_plane_events,
            metrics={
                "retriever_model_query_count": float(len(result.query_hashes)),
                "retriever_model_query_consumed_count": float(len(result.query_hashes)),
                "retriever_counterfactual_effect_evaluated_count": float(len(evaluated_effect_records)),
                "retriever_query_changed_candidate_set_count": float(sum(
                    record.behavioral_effect == "changed"
                    for record in evaluated_effect_records
                )),
                **state_metrics,
            },
        )

    def _consume_retrieval_semantic_state(
        self,
        *,
        result: AdaptiveRetrievalResult,
        envelope: AdaptiveTaskEnvelope,
        approved_plan: ApprovedPlan,
        step: PlanStepProposal,
        grant: CapabilityGrant,
        attempt_workspace: Path,
    ) -> tuple[
        AdaptiveRetrievalResult,
        tuple[object, ...],
        tuple[dict[str, object], ...],
        dict[str, float],
    ]:
        from statebus.control import (
            ControlHeader,
            ErrorResult,
            EventType,
            ExecRequest,
            RefHandle,
            SubprocessExecutorTransport,
            SuccessResult,
        )
        from statebus.memory import MemoryQuery
        from statebus.retrieval import apply_semantic_state_selection
        from statebus.state import publish_dense_semantic_state, query_embedding_from_dense_state
        from statebus.runtime.state_consumption import build_state_consumption_record

        if self.context.state_store is None or self.context.memory_store is None:
            raise AdaptiveDispatchError("adaptive_product_state_infrastructure_missing")
        if self.context.socket_path is None:
            raise AdaptiveDispatchError("adaptive_product_control_socket_missing")

        semantic_requested = bool(
            {str(value).strip() for value in result.request.evidence_types}
            & {"semantic", "semantic_chunk", "semantic_context", "citation", "narrative"}
        )
        selected_bundles = []
        records = []
        data_plane_events: list[dict[str, object]] = []
        transfer_count = 0
        publish_count = 0
        selected_count = 0
        selected_bytes = 0
        for index, bundle in enumerate(result.retrieval_bundles, start=1):
            if (
                not semantic_requested
                or bundle.semantic_state_manifest is None
                or not bundle.semantic_candidate_embeddings
            ):
                selected_bundles.append(bundle)
                continue
            state_id = (
                f"semantic-{grant.task_id}-{grant.step_id}-{grant.attempt_id}-{index}"
                .replace(":", "-")
                .replace("/", "-")
            )
            publication = publish_dense_semantic_state(
                store=self.context.state_store,
                state_id=state_id,
                query_embedding=bundle.query_embedding,
                candidate_embeddings=tuple(
                    embedding for _candidate_id, embedding in bundle.semantic_candidate_embeddings
                ),
                hydrate_manifest=bundle.semantic_state_manifest,
                owner_session_id=grant.session_id,
                encoder_revision="retriever-fanout-v1",
            )
            self.context.semantic_state_publications[state_id] = publication
            data_plane_events.append({
                "event_type": "STATE_PUBLISHED",
                "role": "retriever",
                "payload": {
                    "ref_id": state_id,
                    "manifest_id": publication.ref.manifest_id,
                    "producer_pid": publication.contract.producer_pid,
                    "storage_kind": publication.handle.storage_kind.value,
                },
                "metrics": {
                    "semantic_state_publish_count": 1.0,
                    "semantic_state_bytes": float(publication.handle.size_bytes),
                    "semantic_state_transfer_count": 0.0,
                },
            })
            entries = bundle.semantic_state_manifest.entries
            top_k = max(1, min(len(entries), max(len(bundle.evidence_pack.semantic_contexts), 1)))
            reference_selected_ids = {
                item.item_id for item in bundle.evidence_pack.semantic_contexts
            }
            evidence_budget_bytes = sum(
                max(int(entry.byte_hint), 0)
                for entry in entries
                if entry.candidate_id in reference_selected_ids
            )
            if evidence_budget_bytes <= 0:
                evidence_budget_bytes = sum(
                    max(int(entry.byte_hint), 0) for entry in entries
                )
            request = ExecRequest(
                header=ControlHeader(
                    trace_id=f"adaptive:{grant.task_id}",
                    task_id=grant.task_id,
                    step_id=step.step_id,
                    attempt_id=grant.attempt_id,
                    target_role="executor",
                    timeout_ms=min(max(grant.max_runtime_ms, 5_000), 30_000),
                    event_type=EventType.REQ_EXEC,
                ),
                state_refs=(RefHandle(ref_id=state_id, ref_kind="semantic_state"),),
                artifact_refs=(),
                runtime_reuse_contract="semantic_state_required",
                output_contract_version="statebus.evidence_selection.v1",
                workspace_root=str(attempt_workspace),
                input_manifest_hash=publication.contract.hydrate_manifest_hash,
                operation="semantic_select_v1",
                state_root=str(self.context.state_store.root),
                hydrate_manifest_id=publication.contract.hydrate_manifest_id,
                semantic_top_k=top_k,
                evidence_budget_bytes=evidence_budget_bytes,
                expected_encoder_signature=publication.contract.encoder_signature,
                capability_grant_hash=grant.grant_hash,
            )
            response = SubprocessExecutorTransport(
                socket_path=self.context.socket_path.with_name(
                    f"{self.context.socket_path.stem}-semantic-{index}{self.context.socket_path.suffix}"
                ),
                timeout_s=max(request.header.timeout_ms / 1000.0, 5.0),
            ).execute(request)
            if isinstance(response, ErrorResult):
                raise AdaptiveDispatchError(
                    f"semantic_state_consume_failed:{response.error_code}:{response.error_detail}"
                )
            if not isinstance(response, SuccessResult):
                raise AdaptiveDispatchError("semantic_state_consumer_result_invalid")
            if response.consumed_state_ref_id != state_id:
                raise AdaptiveDispatchError("semantic_state_consumer_ref_mismatch")
            if response.consumer_pid <= 0 or response.consumer_pid == response.producer_pid:
                raise AdaptiveDispatchError("semantic_state_consumer_not_cross_process")
            selected = apply_semantic_state_selection(
                bundle,
                selected_candidate_ids=response.selected_candidate_ids,
                selected_scores=response.selected_scores,
                consumer_pid=response.consumer_pid,
            )
            query_embedding = query_embedding_from_dense_state(
                state_root=self.context.state_store.root,
                ref=publication.ref,
                embedding_id=bundle.query_embedding.embedding_id,
                expected_encoder_signature=publication.contract.encoder_signature,
            )
            selected = replace(
                selected,
                query_embedding=query_embedding,
                memory_query_embedding=query_embedding,
            )
            selected_bundles.append(selected)
            self.context.semantic_state_selections[state_id] = response
            data_plane_events.extend((
                {
                    "event_type": "STATE_RESOLVED",
                    "role": "executor",
                    "payload": {
                        "ref_id": state_id,
                        "producer_pid": response.producer_pid,
                        "consumer_pid": response.consumer_pid,
                    },
                    "metrics": {
                        "semantic_state_resolve_count": 1.0,
                        "semantic_state_transfer_count": 1.0,
                        "semantic_state_consumer_pid": float(response.consumer_pid),
                    },
                },
                {
                    "event_type": "STATE_CONSUMED",
                    "role": "executor",
                    "payload": {
                        "ref_id": state_id,
                        "selected_candidate_ids": list(response.selected_candidate_ids),
                    },
                    "metrics": {
                        "semantic_state_consume_count": 1.0,
                        "selected_candidate_count": float(len(response.selected_candidate_ids)),
                        "selected_evidence_bytes": float(response.selected_evidence_bytes),
                    },
                },
            ))
            downstream_ref_id = f"evidence:{grant.task_id}:{grant.step_id}:{grant.attempt_id}"
            records.append(build_state_consumption_record(
                state_ref_id=state_id,
                consumer_role="executor",
                consumer_step_id=step.step_id,
                operation="cosine_topk_budget_pruning",
                read_field_ids=tuple(
                    f"row:{row_index}" for row_index in (0, *response.selected_row_indices)
                ),
                input_decision_surface_hash=bundle.candidate_pool.candidate_surface_hash,
                output_decision_surface_hash=sha256_digest({
                    "selected_candidate_ids": response.selected_candidate_ids,
                    "selected_scores": response.selected_scores,
                }),
                selected_ids=response.selected_candidate_ids,
                downstream_ref_ids=(downstream_ref_id,),
            ))
            publish_count += 1
            transfer_count += int(response.consumer_pid != response.producer_pid)
            selected_count += len(response.selected_candidate_ids)
            selected_bytes += int(response.selected_evidence_bytes)

        if not selected_bundles:
            selected_bundles = list(result.retrieval_bundles)
        selected_pack = stable_fan_in_evidence_packs(
            task_id=result.request.task_id,
            packs=tuple(bundle.evidence_pack for bundle in selected_bundles),
        )
        query_bundle = selected_bundles[0]
        executor_output_contract = next(
            (
                candidate.output_contract_version
                for candidate in reversed(approved_plan.steps)
                if candidate.role == "executor"
            ),
            approved_plan.final_output_contract_version,
        )
        memory_query = MemoryQuery(
            query_task_id=grant.task_id,
            query_spec_hash=envelope.canonical_task_spec_hash,
            query_text=" ".join(result.request.queries),
            tags=tuple(result.request.target_entities),
            query_embedding=query_bundle.memory_query_embedding or query_bundle.query_embedding,
            limit=max(1, min(result.request.max_candidates, 5)),
            allow_assist=result.request.memory_policy != "none",
            allow_validated_replay=result.request.memory_policy in {"validated_replay", "exact_replay"},
            allow_exact_replay=result.request.memory_policy == "exact_replay",
            compatibility_signature=(
                self.context.runtime_compatibility_signature
                or self.context.registry.digest
            ),
            output_contract_version=executor_output_contract,
            canonical_task_spec=self.context.canonical_task_spec,
            input_lineage_hashes=self.context.input_lineage_hashes,
            input_schema_digest=self.context.input_schema_digest,
            validator_digest=self.context.validator_digest,
        )
        if grant.task_id in self.context.memory_queries_by_task:
            raise AdaptiveDispatchError("hybrid_memory_query_already_issued_for_task")
        memory_result = self.context.memory_store.lookup_hybrid(memory_query)
        self.context.memory_queries_by_task[grant.task_id] = memory_query
        self.context.memory_match_results[step.step_id] = memory_result
        raw_evidence_bytes = sum(
            len(item.rendered_text.encode("utf-8"))
            for bucket in (
                selected_pack.hard_facts,
                selected_pack.structured_evidence,
                selected_pack.semantic_contexts,
                selected_pack.lexical_hints,
                selected_pack.conflicts,
            )
            for item in bucket
        )
        embedding_encode_count = sum(
            1 + len(bundle.semantic_candidate_embeddings)
            for bundle in result.retrieval_bundles
        )
        compatibility_decisions = tuple(memory_result.compatibility_decisions)
        compatible_count = sum(
            decision.verdict != CompatibilityVerdict.INCOMPATIBLE
            for decision in compatibility_decisions
        )
        policy_approved_count = sum(
            decision.policy_approved for decision in compatibility_decisions
        )
        rejected_incompatible_count = sum(
            decision.verdict == CompatibilityVerdict.INCOMPATIBLE
            for decision in compatibility_decisions
        )
        return (
            replace(
                result,
                evidence_pack=selected_pack,
                retrieval_bundles=tuple(selected_bundles),
            ),
            tuple(records),
            tuple(data_plane_events),
            {
                "semantic_state_publish_count": float(publish_count),
                "semantic_state_transfer_count": float(transfer_count),
                "semantic_state_consume_count": float(publish_count),
                "semantic_state_selected_count": float(selected_count),
                "semantic_state_selected_bytes": float(selected_bytes),
                "raw_evidence_bytes_seen_by_llm": float(raw_evidence_bytes),
                "embedding_encode_count": float(embedding_encode_count),
                "hybrid_memory_query_count": 1.0,
                "memory_keyword_candidate_count": float(len(memory_result.source_ranks.get("keyword", ()))),
                "memory_tag_candidate_count": float(len(memory_result.source_ranks.get("tags", ()))),
                "memory_vector_candidate_count": float(len(memory_result.source_ranks.get("vector", ()))),
                "memory_candidate_count": float(
                    len(memory_result.candidate_pool.candidate_memory_ids)
                    if memory_result.candidate_pool is not None
                    else 0
                ),
                "memory_compatible_match_count": float(compatible_count),
                "memory_policy_approved_match_count": float(policy_approved_count),
                "memory_rejected_incompatible_count": float(rejected_incompatible_count),
            },
        )

    def _memory_inputs_for_step(
        self,
        *,
        step: PlanStepProposal,
        grant: CapabilityGrant,
    ) -> tuple[dict[str, object], ...]:
        if self.context.memory_store is None:
            return ()
        role_inputs: list[dict[str, object]] = []
        seen: set[str] = set()
        for retrieval_step_id, result in sorted(self.context.memory_match_results.items()):
            decisions = {
                decision.memory_id: decision
                for decision in getattr(result, "compatibility_decisions", ())
            }
            for match in getattr(result, "matches", ()):
                memory_id = match.memory_ref.memory_id
                if memory_id in seen:
                    continue
                commit = self.context.memory_store.commits.get(memory_id)
                decision = decisions.get(memory_id)
                if commit is None or decision is None or not decision.policy_approved:
                    continue
                recipe = commit.memory_ref.metadata.get("execution_recipe")
                recipe_payload = dict(recipe) if isinstance(recipe, dict) else {}
                payload = {
                    "ref_id": memory_id,
                    "ref_kind": "memory",
                    "source_task_id": commit.memory_ref.source_task_id,
                    "source_agent": commit.memory_ref.source_agent,
                    "summary": commit.memory_ref.summary,
                    "tags": list(commit.memory_ref.tags),
                    "replay_class": match.replay_class.value,
                    "compatibility_verdict": decision.verdict.value,
                    "compatibility_reasons": list(decision.reasons),
                    "artifact_lineage": {
                        "artifact_ref_id": commit.memory_ref.artifact_ref_id,
                        "artifact_hash": commit.created_from_artifact_hash,
                        "manifest_hash": commit.memory_ref.manifest_hash,
                        "input_lineage_hashes": list(
                            commit.memory_ref.metadata.get("input_lineage_hashes", ())
                        ),
                    },
                    "execution_recipe": recipe_payload,
                    "execution_recipe_hash": str(
                        commit.memory_ref.metadata.get("execution_recipe_hash", "")
                    ),
                    "query_source_step_id": retrieval_step_id,
                    "consumer_role": step.role,
                    "consumer_step_id": step.step_id,
                    "grant_hash": grant.grant_hash,
                }
                payload["input_payload_hash"] = sha256_digest(payload)
                role_inputs.append(payload)
                seen.add(memory_id)
        inputs = tuple(role_inputs)
        if inputs:
            self.context.memory_role_inputs_by_step[step.step_id] = inputs
        return inputs

    @staticmethod
    def _validated_recipe(
        memory_inputs: tuple[dict[str, object], ...],
        *,
        execution_kind: str,
        capability_id: str,
        output_contract_version: str,
    ) -> tuple[dict[str, object] | None, str]:
        for memory_input in memory_inputs:
            if memory_input.get("replay_class") not in {
                ReplayClass.VALIDATED_REPLAY.value,
                ReplayClass.EXACT_REPLAY.value,
            }:
                continue
            recipe = memory_input.get("execution_recipe")
            if not isinstance(recipe, dict):
                continue
            if str(recipe.get("execution_kind", "")) != execution_kind:
                continue
            if str(recipe.get("capability_id", "")) != capability_id:
                continue
            if str(recipe.get("output_contract_version", "")) != output_contract_version:
                continue
            return dict(recipe), str(memory_input["ref_id"])
        return None, ""

    @staticmethod
    def _factory_accepts_memory_inputs(
        factory: Callable[..., object],
        *,
        minimum_positional: int = 5,
    ) -> bool:
        try:
            parameters = tuple(inspect.signature(factory).parameters.values())
        except (TypeError, ValueError):
            return False
        return any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters) or sum(
            parameter.kind
            in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
            for parameter in parameters
        ) >= minimum_positional

    def _record_memory_consumption(
        self,
        *,
        memory_inputs: tuple[dict[str, object], ...],
        step: PlanStepProposal,
        downstream_ref_ids: tuple[str, ...],
        before_surface_hash: str,
        replay_memory_id: str = "",
    ) -> dict[str, float]:
        if not memory_inputs:
            return {
                "memory_consumed_count": 0.0,
                "memory_behavioral_effect_count": 0.0,
                "memory_assist_count": 0.0,
                "validated_replay_count": 0.0,
                "exact_replay_count": 0.0,
                "skipped_step_count": 0.0,
                "skipped_llm_call_count": 0.0,
            }
        after_surface_hash = sha256_digest({
            "before_surface_hash": before_surface_hash,
            "memory_input_hashes": [item["input_payload_hash"] for item in memory_inputs],
            "downstream_ref_ids": list(downstream_ref_ids),
        })
        consumed_ids = {
            record.memory_id
            for record in self.context.memory_consumption_records
            if record.consumer_step_id == step.step_id
        }
        for memory_input in memory_inputs:
            memory_id = str(memory_input["ref_id"])
            if memory_id in consumed_ids:
                continue
            replay_class = ReplayClass(str(memory_input["replay_class"]))
            recipe_recomputed = memory_id == replay_memory_id
            behavioral_effect = (
                "recipe_reused_current_input_recomputed"
                if recipe_recomputed
                else "role_input_augmented"
            )
            record = MemoryConsumptionRecord(
                consumption_id=(
                    f"memory-consumption:{step.step_id}:{memory_id}:"
                    f"{len(self.context.memory_consumption_records) + 1}"
                ),
                query_hash=next(
                    (
                        query.query_hash
                        for query in self.context.memory_queries_by_task.values()
                    ),
                    "",
                ),
                memory_id=memory_id,
                consumer_role=step.role,
                consumer_step_id=step.step_id,
                input_ref_id=memory_id,
                replay_class=replay_class,
                compatibility_verdict=CompatibilityVerdict(
                    str(memory_input["compatibility_verdict"])
                ),
                input_payload_hash=str(memory_input["input_payload_hash"]),
                before_decision_surface_hash=before_surface_hash,
                after_decision_surface_hash=after_surface_hash,
                behavioral_effect=behavioral_effect,
                downstream_ref_ids=downstream_ref_ids,
                skipped_generation_step_count=int(recipe_recomputed),
                skipped_llm_call_count=int(recipe_recomputed),
                recipe_recomputed=recipe_recomputed,
                consumed_at_ns=time.time_ns(),
            )
            self.context.memory_consumption_records.append(record)
        task_records = [
            record
            for record in self.context.memory_consumption_records
            if record.consumer_step_id == step.step_id
        ]
        return {
            "memory_consumed_count": float(len(task_records)),
            "memory_behavioral_effect_count": float(
                sum(record.behavioral_effect != "unchanged" for record in task_records)
            ),
            "memory_assist_count": float(
                sum(record.replay_class == ReplayClass.ASSIST for record in task_records)
            ),
            "validated_replay_count": float(
                sum(
                    record.replay_class == ReplayClass.VALIDATED_REPLAY
                    and record.recipe_recomputed
                    for record in task_records
                )
            ),
            "exact_replay_count": float(
                sum(
                    record.replay_class == ReplayClass.EXACT_REPLAY
                    and record.recipe_recomputed
                    for record in task_records
                )
            ),
            "skipped_step_count": float(
                sum(record.skipped_generation_step_count for record in task_records)
            ),
            "skipped_llm_call_count": float(
                sum(record.skipped_llm_call_count for record in task_records)
            ),
        }

    def _dispatch_transform_dsl(
        self,
        envelope: AdaptiveTaskEnvelope,
        approved_plan: ApprovedPlan,
        step: PlanStepProposal,
        grant: CapabilityGrant,
        attempt_workspace: Path,
    ) -> "AdaptiveStepResult":
        from statebus.runtime.adaptive_runtime import AdaptiveStepResult

        input_ref_id, rows, input_hashes, provenance, projection_hashes = self._typed_input(
            step=step,
            grant=grant,
            attempt_workspace=attempt_workspace,
        )
        memory_inputs = self._memory_inputs_for_step(step=step, grant=grant)
        before_memory_surface_hash = sha256_digest({
            "step": step.canonical_payload(),
            "input_ref_id": input_ref_id,
            "input_hashes": list(input_hashes),
        })
        if self.context.transform_program_factory is None:
            raise AdaptiveDispatchError("transform_program_handler_not_registered")
        replay_recipe, replay_memory_id = self._validated_recipe(
            memory_inputs,
            execution_kind=ExecutionKind.TRANSFORM_DSL.value,
            capability_id=step.capability_id,
            output_contract_version=grant.output_contract_version,
        )
        if replay_recipe is not None:
            operations = tuple(
                TransformStep(
                    op=str(item["op"]),
                    arguments=dict(item.get("arguments", {})),
                )
                for item in replay_recipe.get("operations", ())
                if isinstance(item, dict) and item.get("op")
            )
            if not operations:
                raise AdaptiveDispatchError("validated_replay_recipe_operations_missing")
            program = TransformProgram(
                program_id=f"validated-replay-{grant.attempt_id}",
                input_artifact_refs=(input_ref_id,),
                operations=operations,
                output_contract_version=grant.output_contract_version,
            )
        elif self._factory_accepts_memory_inputs(self.context.transform_program_factory):
            program = self.context.transform_program_factory(
                step,
                grant,
                input_ref_id,
                rows,
                memory_inputs,
            )
        else:
            program = self.context.transform_program_factory(step, grant, input_ref_id, rows)
        schema = self._output_schema(step.capability_id, rows, step.step_id)
        projected_inputs = {input_ref_id: [dict(row) for row in rows]}
        dsl_repair_count = 0
        dsl_quality_repair_count = 0
        quality_rejection_count = 0
        quality_hashes: list[str] = []
        program_hashes = [program.program_hash]
        validator_id = self._business_validator_id(step.capability_id)
        while True:
            try:
                self._validate_transform_semantics(
                    program,
                    self.context.quality_semantics_by_capability.get(step.capability_id, {}),
                )
                transformed = tuple(self.transform_interpreter.run(program, inputs=projected_inputs))
                recomputed = recompute_transform_program(program, inputs=projected_inputs)
            except (AdaptiveDispatchError, CapabilityRecomputeError, TransformProgramError) as exc:
                if self.context.transform_program_repair_factory is None or dsl_repair_count >= 1:
                    raise AdaptiveDispatchError(str(exc)) from exc
                program = self.context.transform_program_repair_factory(
                    step,
                    grant,
                    input_ref_id,
                    rows,
                    (str(exc),),
                )
                dsl_repair_count += 1
                program_hashes.append(program.program_hash)
                continue
            quality = self.context.validator_registry.validate(
                CapabilityQualityContext(
                    capability_id=step.capability_id,
                    validator_id=validator_id,
                    input_rows=(rows,),
                    output_rows=transformed,
                    input_artifact_hashes=input_hashes,
                    output_artifact_hash=sha256_digest(stable_json_dumps(transformed).encode("utf-8")),
                    expected_rows=recomputed,
                    required_fields=tuple(schema),
                    completion_criteria=step.completion_criteria,
                    operation_semantics=dict(self.context.quality_semantics_by_capability.get(step.capability_id, {})),
                    provenance_item_ids=provenance,
                )
            )
            self.context.quality_reports[quality.report_hash] = quality
            quality_hashes.append(quality.report_hash)
            if quality.verified:
                break
            quality_rejection_count += 1
            if self.context.transform_program_repair_factory is None or dsl_repair_count >= 1:
                return AdaptiveStepResult(
                    grant_hash=grant.grant_hash,
                    success=False,
                    attempt_id=grant.attempt_id,
                    error_code="capability_quality_rejected",
                    validator_report_hashes=tuple(quality_hashes),
                    quality_report_hashes=tuple(quality_hashes),
                    projection_report_hashes=projection_hashes,
                    program_hashes=tuple(program_hashes),
                    metrics={
                        "dsl_execution_count": 1.0,
                        "dsl_repair_count": float(dsl_repair_count),
                        "dsl_quality_repair_count": float(dsl_quality_repair_count),
                        "dsl_quality_rejected_count": float(quality_rejection_count),
                        "llm_codeact_quality_rejected_count": 0.0,
                    },
                )
            program = self.context.transform_program_repair_factory(
                step,
                grant,
                input_ref_id,
                rows,
                quality.error_codes,
            )
            dsl_repair_count += 1
            dsl_quality_repair_count += 1
            program_hashes.append(program.program_hash)
        result = self.transform_interpreter.run_verified(
            program,
            inputs=projected_inputs,
            grant=grant,
            attempt_workspace=attempt_workspace / "dsl",
            output_schema=schema,
            quality_report=quality,
        )
        artifact = result.artifact
        self.context.artifacts[artifact.artifact_id] = StoredAdaptiveArtifact(
            artifact=artifact,
            rows=result.rows,
            provenance_item_ids=provenance,
        )
        self.context.execution_recipes_by_artifact[artifact.artifact_id] = {
            "execution_kind": ExecutionKind.TRANSFORM_DSL.value,
            "capability_id": step.capability_id,
            "output_contract_version": grant.output_contract_version,
            "operations": [operation.canonical_payload() for operation in program.operations],
            "source_program_hash": program.program_hash,
        }
        memory_metrics = self._record_memory_consumption(
            memory_inputs=memory_inputs,
            step=step,
            downstream_ref_ids=(artifact.artifact_id,),
            before_surface_hash=before_memory_surface_hash,
            replay_memory_id=(replay_memory_id if dsl_repair_count == 0 else ""),
        )
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            attempt_id=grant.attempt_id,
            output_refs=(artifact.artifact_id,),
            output_ref_kinds=("execution_artifact",),
            validator_report_hashes=tuple(quality_hashes),
            quality_report_hashes=tuple(quality_hashes),
            projection_report_hashes=projection_hashes,
            program_hashes=tuple(program_hashes),
            metrics={
                "evidence_projection_count": float(bool(projection_hashes)),
                "dsl_execution_count": 1.0,
                "dsl_repair_count": float(dsl_repair_count),
                "dsl_quality_repair_count": float(dsl_quality_repair_count),
                "dsl_quality_rejected_count": float(quality_rejection_count),
                **memory_metrics,
            },
        )

    def _dispatch_llm_python(
        self,
        envelope: AdaptiveTaskEnvelope,
        approved_plan: ApprovedPlan,
        step: PlanStepProposal,
        grant: CapabilityGrant,
        attempt_workspace: Path,
    ) -> "AdaptiveStepResult":
        from statebus.runtime.adaptive_runtime import AdaptiveStepResult

        if not envelope.allow_llm_python or envelope.risk_class != RiskClass.BOUNDED_CODE:
            raise AdaptiveDispatchError("llm_python_not_program_enabled")
        if self.context.code_policy_factory is None:
            raise AdaptiveDispatchError("llm_python_handler_not_registered")
        if not grant.input_ref_ids:
            raise AdaptiveDispatchError("llm_python_requires_verified_artifact")
        stored_inputs: list[StoredAdaptiveArtifact] = []
        verified_inputs: list[tuple[dict[str, object], ...]] = []
        retrieval_context: list[dict[str, object]] = []
        evidence_manifest: dict[str, str] = {}
        evidence_provenance: list[str] = []
        for ref_id in grant.input_ref_ids:
            stored = self.context.artifacts.get(ref_id)
            if stored is not None:
                if not self._artifact_in_grant_scope(stored, grant):
                    raise AdaptiveDispatchError("llm_python_input_artifact_not_verified")
                stored_inputs.append(stored)
                verified_inputs.append(self._read_verified_artifact_rows(stored))
                continue
            evidence_pack = self._verified_evidence_pack(ref_id, grant)
            if evidence_pack is None:
                raise AdaptiveDispatchError("llm_python_input_ref_not_verified")
            evidence_manifest[ref_id] = evidence_pack.pack_hash
            for item in (
                *evidence_pack.hard_facts,
                *evidence_pack.structured_evidence,
                *evidence_pack.semantic_contexts,
            )[:8]:
                evidence_provenance.append(item.item_id)
                retrieval_context.append({
                    "item_id": item.item_id,
                    "bucket": item.bucket,
                    "locator": "" if item.locator is None else repr(item.locator),
                    "text": item.rendered_text[:800],
                })
        if not stored_inputs:
            raise AdaptiveDispatchError("llm_python_requires_verified_artifact")
        verified_rows = verified_inputs[-1]
        memory_inputs = self._memory_inputs_for_step(step=step, grant=grant)
        before_memory_surface_hash = sha256_digest({
            "step": step.canonical_payload(),
            "input_artifact_hashes": [stored.artifact.blob_hash for stored in stored_inputs],
            "evidence_manifest": evidence_manifest,
        })
        replay_recipe, replay_memory_id = self._validated_recipe(
            memory_inputs,
            execution_kind=ExecutionKind.LLM_BOUNDED_PYTHON.value,
            capability_id=step.capability_id,
            output_contract_version=grant.output_contract_version,
        )
        validator_id = self._business_validator_id(step.capability_id)
        policy = self.context.code_policy_factory(step)
        if not policy.enabled or not policy.require_bwrap:
            raise AdaptiveDispatchError("llm_python_policy_not_bwrap_required")
        if len(policy.allowed_input_relpaths) == 1 and len(stored_inputs) > 1:
            policy = replace(
                policy,
                allowed_input_relpaths=(
                    policy.allowed_input_relpaths[0],
                    *(f"inputs/upstream-{index}.json" for index in range(1, len(stored_inputs))),
                ),
            )
        if len(policy.allowed_input_relpaths) != len(stored_inputs):
            raise AdaptiveDispatchError("llm_python_input_path_arity_mismatch")
        input_files = {
            relpath: stable_json_dumps(list(rows)).encode("utf-8")
            for relpath, rows in zip(policy.allowed_input_relpaths, verified_inputs)
        }
        authorized_input_schemas = {
            relpath: self._input_schema(rows)
            for relpath, rows in zip(policy.allowed_input_relpaths, verified_inputs)
        }
        provenance = tuple(dict.fromkeys(
            item_id
            for stored in stored_inputs
            for item_id in stored.provenance_item_ids
        ))
        combined_provenance = tuple(dict.fromkeys((*provenance, *evidence_provenance)))
        schema = self._output_schema(step.capability_id, verified_rows, step.step_id)
        contract = self._codeact_contract(step.capability_id, verified_rows, step.step_id)
        request = CodeGenerationRequest(
            task_id=grant.task_id,
            step_id=grant.step_id,
            attempt_id=grant.attempt_id,
            approved_plan_hash=approved_plan.approved_plan_hash,
            capability_grant_hash=grant.grant_hash,
            capability_id=step.capability_id,
            input_ref_ids=grant.input_ref_ids,
            input_manifest_digest=sha256_digest({
                "artifacts": {
                    stored.artifact.artifact_id: stored.artifact.blob_hash
                    for stored in stored_inputs
                },
                "evidence": evidence_manifest,
                "memory": {
                    str(item["ref_id"]): str(item["input_payload_hash"])
                    for item in memory_inputs
                },
            }),
            output_schema=schema,
            model_signature="adaptive_executor",
            prompt_signature="",
            runtime_signature=sha256_digest(envelope.canonical_payload()),
            policy=policy,
            session_id=grant.session_id,
            task_goal=step.goal,
            operation_semantics=dict(contract.get("operation_semantics", {})),
            completion_criteria=dict(step.completion_criteria),
            output_contract_version=step.output_contract_version,
            validator_id=validator_id,
            quality_constraints=dict(contract.get("quality_constraints", {})),
            authorized_input_schema=self._input_schema(verified_inputs[0]),
            authorized_input_schemas=authorized_input_schemas,
            expected_output_shape=str(contract.get("expected_output_shape", "object")),
            provenance_item_ids=combined_provenance,
            retrieval_context=tuple(retrieval_context),
            memory_inputs=memory_inputs,
        )
        prompt = build_code_generation_prompt(request)
        request = replace(
            request,
            prompt_signature=code_generation_prompt_bundle_digest(
                request,
                rendered_prompt=prompt,
            ),
        )
        if replay_recipe is not None:
            source = str(replay_recipe.get("source", ""))
            if not source.strip():
                raise AdaptiveDispatchError("validated_replay_python_source_missing")
        else:
            if self.context.code_source_factory is None:
                raise AdaptiveDispatchError("llm_python_handler_not_registered")
            source = self.context.code_source_factory(request, prompt)

        def repair_source(previous_source: str, violations: tuple[str, ...]) -> str:
            if self.context.code_repair_factory is None:
                return ""
            return self.context.code_repair_factory(request, prompt, previous_source, violations)

        outcome = self.codeact_runner.execute(
            request=request,
            grant=grant,
            raw_response=source,
            attempt_workspace=attempt_workspace / "codeact",
            input_files=input_files,
            repair_source=(repair_source if self.context.code_repair_factory is not None else None),
            model_id="adaptive_executor",
        )
        quality_reports = outcome.quality_reports
        if not quality_reports and outcome.quality_report is not None:
            quality_reports = (outcome.quality_report,)
        quality_hashes = tuple(report.report_hash for report in quality_reports)
        self.context.code_execution_records[grant.grant_hash] = outcome.record
        self.context.code_policy_reports[grant.grant_hash] = outcome.policy_report
        for quality_report in quality_reports:
            self.context.quality_reports[quality_report.report_hash] = quality_report
        if outcome.artifact is None or outcome.output_payload is None:
            return AdaptiveStepResult(
                grant_hash=grant.grant_hash,
                success=False,
                attempt_id=grant.attempt_id,
                error_code=outcome.record.fallback_reason or "llm_codeact_failed",
                validator_report_hashes=quality_hashes,
                quality_report_hashes=quality_hashes,
                source_hashes=(outcome.record.source_hash,),
                metrics={
                    "llm_codeact_generation_count": float(replay_recipe is None),
                    "llm_codeact_repair_count": float(len(outcome.repairs)),
                    "llm_codeact_execution_count": float(outcome.record.exit_code == 0),
                    "llm_codeact_runtime_repair_count": float(sum(
                        item.repair_kind == "runtime" for item in outcome.repairs
                    )),
                    "llm_codeact_quality_repair_count": float(sum(
                        item.repair_kind == "quality" for item in outcome.repairs
                    )),
                    "llm_codeact_quality_rejected_count": float(sum(
                        not report.verified for report in quality_reports
                    )),
                    "llm_codeact_sandbox_fallback_count": float(outcome.record.sandbox_actual_backend != "bwrap"),
                },
            )
        artifact = outcome.artifact
        self.context.artifacts[artifact.artifact_id] = StoredAdaptiveArtifact(
            artifact=artifact,
            rows=(
                tuple(dict(row) for row in outcome.output_payload)
                if isinstance(outcome.output_payload, list)
                else (dict(outcome.output_payload),)
            ),
            provenance_item_ids=combined_provenance,
        )
        self.context.execution_recipes_by_artifact[artifact.artifact_id] = {
            "execution_kind": ExecutionKind.LLM_BOUNDED_PYTHON.value,
            "capability_id": step.capability_id,
            "output_contract_version": grant.output_contract_version,
            "source": source,
            "source_hash": sha256_digest(source.encode("utf-8")),
        }
        memory_metrics = self._record_memory_consumption(
            memory_inputs=memory_inputs,
            step=step,
            downstream_ref_ids=(artifact.artifact_id,),
            before_surface_hash=before_memory_surface_hash,
            replay_memory_id=(replay_memory_id if not outcome.repairs else ""),
        )
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            attempt_id=grant.attempt_id,
            output_refs=(artifact.artifact_id,),
            output_ref_kinds=("execution_artifact",),
            validator_report_hashes=quality_hashes,
            quality_report_hashes=quality_hashes,
            source_hashes=(outcome.record.source_hash,),
            metrics={
                "llm_codeact_generation_count": float(replay_recipe is None),
                "llm_codeact_repair_count": float(len(outcome.repairs)),
                "llm_codeact_runtime_repair_count": float(sum(
                    item.repair_kind == "runtime" for item in outcome.repairs
                )),
                "llm_codeact_quality_repair_count": float(sum(
                    item.repair_kind == "quality" for item in outcome.repairs
                )),
                "llm_codeact_quality_rejected_count": float(sum(
                    not report.verified for report in quality_reports
                )),
                "llm_codeact_execution_count": 1.0,
                "llm_codeact_verified_count": 1.0,
                "llm_codeact_sandbox_fallback_count": 0.0,
                **memory_metrics,
            },
        )

    def _dispatch_builtin(
        self,
        envelope: AdaptiveTaskEnvelope,
        approved_plan: ApprovedPlan,
        step: PlanStepProposal,
        grant: CapabilityGrant,
        attempt_workspace: Path,
    ) -> "AdaptiveStepResult":
        if step.role == "summarizer" and self.context.claim_set_factory is not None:
            return self._dispatch_summarizer(step, grant, attempt_workspace)
        try:
            handler = self.context.builtin_handlers[step.capability_id]
        except KeyError as exc:
            raise AdaptiveDispatchError("runtime_builtin_handler_not_registered") from exc
        return handler(envelope, approved_plan, step, grant, attempt_workspace)

    def _dispatch_summarizer(
        self,
        step: PlanStepProposal,
        grant: CapabilityGrant,
        attempt_workspace: Path,
    ) -> "AdaptiveStepResult":
        """Materialize only a validated ClaimSet from the verified input refs."""
        from statebus.runtime.adaptive_runtime import AdaptiveStepResult

        artifacts = [
            self.context.artifacts[ref_id]
            for ref_id in grant.input_ref_ids
            if ref_id in self.context.artifacts
        ]
        evidence_ref_ids = [
            ref_id for ref_id in grant.input_ref_ids if ref_id in self.context.evidence_packs
        ]
        if not artifacts or len(evidence_ref_ids) != 1:
            raise AdaptiveDispatchError("summarizer_verified_input_set_invalid")
        for candidate in artifacts:
            if not self._artifact_in_grant_scope(candidate, grant):
                raise AdaptiveDispatchError("summarizer_input_artifact_not_verified")
        # Grant input refs preserve dependency order. The final executor
        # artifact is the last artifact; intermediate artifacts remain part of
        # the auditable dependency chain and are never silently substituted.
        stored = artifacts[-1]
        evidence_ref_id = evidence_ref_ids[0]
        evidence_pack = self.context.evidence_packs[evidence_ref_id]
        evidence_scope = self.context.evidence_ref_scopes.get(evidence_ref_id)
        if (
            evidence_pack.task_id != grant.task_id
            or evidence_scope is None
            or evidence_scope[0] != grant.session_id
            or not evidence_scope[1]
            or self.context.evidence_statuses.get(evidence_ref_id, EvidenceCoverageStatus.INSUFFICIENT_EVIDENCE)
            != EvidenceCoverageStatus.COMPLETE
        ):
            raise AdaptiveDispatchError("summarizer_evidence_not_verified")
        rows = self._read_verified_artifact_rows(stored)
        memory_inputs = self._memory_inputs_for_step(step=step, grant=grant)
        before_memory_surface_hash = sha256_digest({
            "step": step.canonical_payload(),
            "artifact_hash": stored.artifact.blob_hash,
            "evidence_pack_hash": evidence_pack.pack_hash,
        })
        assert self.context.claim_set_factory is not None
        try:
            if self._factory_accepts_memory_inputs(
                self.context.claim_set_factory,
                minimum_positional=6,
            ):
                claim_set = self.context.claim_set_factory(
                    step,
                    grant,
                    stored.artifact,
                    rows,
                    evidence_pack,
                    memory_inputs,
                )
            else:
                claim_set = self.context.claim_set_factory(
                    step,
                    grant,
                    stored.artifact,
                    rows,
                    evidence_pack,
                )
        except Exception as exc:
            # A candidate-generation error is not an authorization to issue a
            # fallback report.  Surface it as a normal failed Runtime step so
            # the session and telemetry remain auditable and fail closed.
            raise AdaptiveDispatchError(
                f"summarizer_candidate_generation_failed:{type(exc).__name__}"
            ) from exc
        claim_report = ClaimSetValidator().validate(
            claim_set,
            evidence_pack=evidence_pack,
            verified_artifacts={stored.artifact.artifact_id: (stored.artifact, list(rows))},
            current_task_id=grant.task_id,
            current_session_id=grant.session_id,
            evidence_session_id=evidence_scope[0],
        )
        audit = {
            "claim_set": claim_set.canonical_payload(),
            "claim_set_hash": sha256_digest(claim_set.canonical_payload()),
            "claim_validation": {
                "ok": claim_report.ok,
                "status": claim_report.status.value,
                "errors": list(claim_report.errors),
            },
        }
        audit_hash = sha256_digest(audit)
        audit_path = attempt_workspace / "audits" / "summarizer_claim_candidate.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(stable_json_dumps(audit) + "\n", encoding="utf-8")
        self.context.claim_validation_reports[grant.grant_hash] = audit
        if not claim_report.ok:
            return AdaptiveStepResult(
                grant_hash=grant.grant_hash,
                success=False,
                attempt_id=grant.attempt_id,
                error_code="claim_validation_failed:" + ",".join(claim_report.errors[:4]),
                validator_report_hashes=(audit_hash,),
            )
        payload = stable_json_dumps(claim_set.canonical_payload()).encode("utf-8")
        output_dir = attempt_workspace / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "claim_set.json"
        output_path.write_bytes(payload)
        lifecycle = ArtifactLifecycleManager()
        candidate = lifecycle.register_candidate(ExecutionArtifactRef(
            artifact_id=f"claimset-{grant.task_id}-{grant.step_id}-{grant.attempt_id}",
            task_id=grant.task_id,
            step_id=grant.step_id,
            artifact_type="json",
            root_id=str(attempt_workspace),
            relpath=str(output_path.relative_to(attempt_workspace)),
            blob_hash=sha256_digest(payload),
            size_bytes=len(payload),
            produced_by="summarizer",
            workspace_relpath=str(output_path.relative_to(attempt_workspace)),
            manifest_hash=sha256_digest(claim_set.canonical_payload()),
            metadata={
                "schema_version": "statebus.claim_set_artifact.v1",
                "grant_hash": grant.grant_hash,
                "session_id": grant.session_id,
                "attempt_id": grant.attempt_id,
                "claim_set_hash": sha256_digest(claim_set.canonical_payload()),
                "claim_validation_audit_hash": audit_hash,
            },
        ))
        artifact = lifecycle.mark_verified(candidate.artifact_id)
        self.context.artifacts[artifact.artifact_id] = StoredAdaptiveArtifact(
            artifact=artifact,
            rows=(claim_set.canonical_payload(),),
            provenance_item_ids=tuple(dict.fromkeys(
                evidence_id
                for claim in claim_set.claims
                for evidence_id in claim.supporting_evidence_item_ids
            )),
        )
        self.context.claim_sets[artifact.artifact_id] = claim_set
        memory_metrics = self._record_memory_consumption(
            memory_inputs=memory_inputs,
            step=step,
            downstream_ref_ids=(artifact.artifact_id,),
            before_surface_hash=before_memory_surface_hash,
        )
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            attempt_id=grant.attempt_id,
            output_refs=(artifact.artifact_id,),
            output_ref_kinds=("execution_artifact",),
            validator_report_hashes=(audit_hash,),
            metrics=memory_metrics,
        )

    def _typed_input(
        self,
        *,
        step: PlanStepProposal,
        grant: CapabilityGrant,
        attempt_workspace: Path,
    ) -> tuple[str, tuple[dict[str, object], ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        artifact_ref_ids = tuple(
            ref_id for ref_id in grant.input_ref_ids if ref_id in self.context.artifacts
        )
        evidence_ref_ids = tuple(
            ref_id for ref_id in grant.input_ref_ids if ref_id in self.context.evidence_packs
        )
        unknown_ref_ids = set(grant.input_ref_ids) - set(artifact_ref_ids) - set(evidence_ref_ids)
        if unknown_ref_ids:
            raise AdaptiveDispatchError("transform_input_ref_unknown")
        for evidence_ref_id in evidence_ref_ids:
            self._verified_evidence_pack(evidence_ref_id, grant)
        if artifact_ref_ids:
            if len(artifact_ref_ids) != 1:
                raise AdaptiveDispatchError("transform_requires_one_data_artifact")
            ref_id = artifact_ref_ids[0]
        elif len(evidence_ref_ids) == 1:
            ref_id = evidence_ref_ids[0]
        else:
            raise AdaptiveDispatchError("transform_requires_one_input_ref")
        evidence_pack = self.context.evidence_packs.get(ref_id)
        if evidence_pack is not None:
            evidence_scope = self.context.evidence_ref_scopes.get(ref_id)
            if (
                evidence_pack.task_id != grant.task_id
                or evidence_scope is None
                or evidence_scope[0] != grant.session_id
                or not evidence_scope[1]
            ):
                raise AdaptiveDispatchError("transform_input_not_verified")
            request = EvidenceProjectionRequest(
                task_id=grant.task_id,
                session_id=grant.session_id,
                step_id=grant.step_id,
                evidence_pack_ref_id=ref_id,
                evidence_pack_hash=evidence_pack.pack_hash,
                requested_fields=tuple(self._output_schema(step.capability_id, (), step.step_id).keys()),
                output_contract_version="statebus.transform_input.v1",
            )
            rows, artifact, report = self.projection_adapter.project(
                request=request,
                evidence_pack=evidence_pack,
                coverage_status=self.context.evidence_statuses.get(ref_id, EvidenceCoverageStatus.INSUFFICIENT_EVIDENCE),
                grant=grant,
                attempt_workspace=attempt_workspace,
            )
            self.context.artifacts[artifact.artifact_id] = StoredAdaptiveArtifact(
                artifact=artifact,
                rows=rows,
                provenance_item_ids=report.consumed_evidence_item_ids,
            )
            self.context.projection_reports[report.report_hash] = report
            return ref_id, rows, (artifact.blob_hash,), report.consumed_evidence_item_ids, (report.report_hash,)
        stored = self.context.artifacts.get(ref_id)
        if not self._artifact_in_grant_scope(stored, grant):
            raise AdaptiveDispatchError("transform_input_not_verified")
        assert stored is not None
        rows = self._read_verified_artifact_rows(stored)
        return ref_id, rows, (stored.artifact.blob_hash,), stored.provenance_item_ids, ()

    def _verified_evidence_pack(
        self,
        ref_id: str,
        grant: CapabilityGrant,
    ) -> CanonicalEvidencePack | None:
        evidence_pack = self.context.evidence_packs.get(ref_id)
        evidence_scope = self.context.evidence_ref_scopes.get(ref_id)
        if evidence_pack is None:
            return None
        if (
            evidence_pack.task_id != grant.task_id
            or self.context.evidence_statuses.get(ref_id) != EvidenceCoverageStatus.COMPLETE
            or evidence_scope is None
            or evidence_scope[0] != grant.session_id
            or not evidence_scope[1]
        ):
            raise AdaptiveDispatchError("evidence_context_not_verified")
        return evidence_pack

    @staticmethod
    def _artifact_in_grant_scope(
        stored: StoredAdaptiveArtifact | None,
        grant: CapabilityGrant,
    ) -> bool:
        if stored is None:
            return False
        metadata = stored.artifact.metadata
        return (
            stored.artifact.verification_state == RefStatus.VERIFIED
            and stored.artifact.task_id == grant.task_id
            and metadata.get("session_id") == grant.session_id
            and isinstance(metadata.get("attempt_id"), str)
            and bool(str(metadata["attempt_id"]).strip())
        )

    @staticmethod
    def _read_verified_artifact_rows(stored: StoredAdaptiveArtifact) -> tuple[dict[str, object], ...]:
        """Rehydrate a verified JSON artifact; in-memory rows are never authoritative input."""
        artifact = stored.artifact
        root = Path(artifact.root_id)
        candidate = root / artifact.relpath
        try:
            resolved_root = root.resolve(strict=True)
            resolved_path = candidate.resolve(strict=True)
            if not resolved_path.is_relative_to(resolved_root) or candidate.is_symlink() or not candidate.is_file():
                raise AdaptiveDispatchError("artifact_path_not_readable")
            payload = candidate.read_bytes()
        except OSError as exc:
            raise AdaptiveDispatchError("artifact_path_not_readable") from exc
        if len(payload) != artifact.size_bytes or sha256_digest(payload) != artifact.blob_hash:
            raise AdaptiveDispatchError("artifact_blob_hash_mismatch")
        try:
            decoded = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdaptiveDispatchError("artifact_json_invalid") from exc
        if isinstance(decoded, dict):
            rows = (dict(decoded),)
        elif isinstance(decoded, list) and all(isinstance(row, dict) for row in decoded):
            rows = tuple(dict(row) for row in decoded)
        else:
            raise AdaptiveDispatchError("artifact_json_rows_invalid")
        if stable_json_dumps(list(rows)) != stable_json_dumps(list(stored.rows)):
            raise AdaptiveDispatchError("artifact_cached_rows_mismatch")
        return rows

    def _validate_dispatch(
        self,
        envelope: AdaptiveTaskEnvelope,
        approved_plan: ApprovedPlan,
        step: PlanStepProposal,
        grant: CapabilityGrant,
        bound_grant: BoundCapabilityGrant,
    ) -> ExecutionKind:
        descriptor = self.context.registry.get(step.capability_id)
        logical_capability = project_legacy_capability(descriptor)
        binding = bound_grant.execution_binding
        if step.capability_id != grant.capability_id or grant.approved_plan_hash != approved_plan.approved_plan_hash:
            raise AdaptiveDispatchError("capability_grant_mismatch")
        if grant.task_id != envelope.task_id or grant.step_id != step.step_id or grant.expires_at_ns <= __import__("time").time_ns():
            raise AdaptiveDispatchError("capability_grant_scope_or_expiry_mismatch")
        if (
            binding.task_id != grant.task_id
            or binding.session_id != grant.session_id
            or binding.step_id != step.step_id
            or binding.attempt_id != grant.attempt_id
            or binding.approved_plan_hash != approved_plan.approved_plan_hash
            or binding.logical_capability_id != logical_capability.capability_id
            or binding.logical_capability_version != logical_capability.version
            or binding.semantic_contract_hash != logical_capability.semantic_contract_hash
        ):
            raise AdaptiveDispatchError("execution_binding_scope_mismatch")
        try:
            execution_kind = ExecutionKind(binding.selected_implementation_kind)
        except ValueError as exc:
            raise AdaptiveDispatchError("execution_binding_implementation_unknown") from exc
        if descriptor.execution_kind != execution_kind:
            raise AdaptiveDispatchError("execution_binding_implementation_mismatch")
        if descriptor.owner_role != step.role:
            raise AdaptiveDispatchError("capability_descriptor_mismatch")
        if execution_kind == ExecutionKind.LLM_BOUNDED_PYTHON:
            if not envelope.allow_llm_python or envelope.risk_class != RiskClass.BOUNDED_CODE:
                raise AdaptiveDispatchError("llm_python_not_program_enabled")
            if not self.context.validator_registry.contains(self._business_validator_id(step.capability_id)):
                raise AdaptiveDispatchError("capability_quality_validator_unregistered")
        return execution_kind

    def _business_validator_id(self, capability_id: str) -> str:
        descriptor = self.context.registry.get(capability_id)
        for validator_id in descriptor.validator_ids:
            if self.context.validator_registry.contains(validator_id):
                return validator_id
        raise AdaptiveDispatchError("capability_quality_validator_unregistered")

    def _output_schema(
        self, capability_id: str, rows: tuple[dict[str, object], ...], step_id: str = "",
    ) -> dict[str, str]:
        if step_id:
            configured_by_step = self.context.output_schema_by_step.get(step_id)
            if configured_by_step:
                return configured_by_step
        configured = self.context.output_schema_by_capability.get(capability_id)
        if configured:
            return configured
        if capability_id in {"extract_metric_series_v1", "bounded_metric_python_v1"}:
            return {"quarter": "string", "revenue_musd": "number"}
        if rows:
            schema: dict[str, str] = {}
            for key, value in rows[0].items():
                schema[key] = "number" if isinstance(value, (int, float)) and not isinstance(value, bool) else "string"
            return schema
        raise AdaptiveDispatchError("output_schema_not_registered")

    def _codeact_contract(
        self, capability_id: str, rows: tuple[dict[str, object], ...], step_id: str = "",
    ) -> dict[str, object]:
        if step_id:
            configured_by_step = self.context.codeact_contracts.get(step_id)
            if configured_by_step is not None:
                return configured_by_step
        configured = self.context.codeact_contracts.get(capability_id)
        if configured is not None:
            return configured
        if capability_id == "bounded_metric_python_v1":
            return {
                "operation_semantics": {"operation": "copy_verified_metric_rows"},
                "quality_constraints": {"all_numeric_values_must_come_from_authorized_input": True},
                "expected_output_shape": "object",
            }
        raise AdaptiveDispatchError("codeact_semantic_contract_not_registered")

    @staticmethod
    def _validate_transform_semantics(
        program: TransformProgram,
        semantics: dict[str, object],
    ) -> None:
        """Reject a DSL program that changes a registered business operation."""
        operation = str(semantics.get("operation", ""))
        if not operation:
            return
        expected_ops = {
            "compare_periods": "compare_periods",
            "aggregate_metrics": "aggregate_grouped",
            "detect_anomaly": "anomaly_zscore",
        }
        expected_op = expected_ops.get(operation)
        if expected_op is None or len(program.operations) != 1 or program.operations[0].op != expected_op:
            raise AdaptiveDispatchError("transform_program_semantics_operation_mismatch")
        arguments = program.operations[0].arguments
        required_by_operation = {
            "compare_periods": ("period_field", "value_field"),
            "aggregate_metrics": ("group_field", "value_field"),
            "detect_anomaly": ("period_field", "value_field", "z_threshold"),
        }
        for field in required_by_operation[operation]:
            if arguments.get(field) != semantics.get(field):
                raise AdaptiveDispatchError(f"transform_program_semantics_argument_mismatch:{field}")
        default_outputs = {
            "baseline_period_output": "baseline_period",
            "comparison_period_output": "comparison_period",
            "baseline_value_output": "baseline_value",
            "comparison_value_output": "comparison_value",
            "difference_output": "difference",
            "ratio_output": "ratio",
            "growth_pct_output": "growth_pct",
            "group_output": str(semantics.get("group_field", "group")),
            "sum_output": "sum",
            "mean_output": "mean",
            "min_output": "min",
            "max_output": "max",
            "count_output": "count",
            "baseline_output": "baseline_mean",
            "threshold_output": "threshold",
            "flag_output": "is_anomaly",
        }
        for field, default in default_outputs.items():
            if field not in semantics:
                continue
            if arguments.get(field, default) != semantics[field]:
                raise AdaptiveDispatchError(f"transform_program_semantics_argument_mismatch:{field}")

    @staticmethod
    def _input_schema(rows: tuple[dict[str, object], ...]) -> dict[str, str]:
        schema: dict[str, str] = {}
        for row in rows:
            for key, value in row.items():
                value_type = (
                    "boolean" if isinstance(value, bool)
                    else "number" if isinstance(value, (int, float))
                    else "string"
                )
                prior = schema.get(key)
                if prior is not None and prior != value_type:
                    raise AdaptiveDispatchError("authorized_input_schema_type_conflict")
                schema[key] = value_type
        if not schema:
            raise AdaptiveDispatchError("authorized_input_schema_empty")
        return dict(sorted(schema.items()))
