from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Callable

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    ApprovedPlan,
    ApprovedPlanBundle,
    CanonicalTaskSpec,
    IdentityContractError,
    PlanNormalizationReceipt,
    PlanPolicyReport,
    PlanProposal,
    PlanProvenanceError,
    RefStatus,
    ReplayClass,
    RuntimeIdentity,
    WorkflowMode,
)
from statebus.memory import MemoryCommit, MemoryIndexStore, MemoryRef, MemoryType
from statebus.refs import ExecutionArtifactRef
from statebus.runtime.adaptive_dispatcher import (
    AdaptiveCapabilityDispatcher,
    AdaptiveDispatchContext,
    BuiltinHandler,
    ClaimSetFactory,
    CodeRepairFactory,
    CodeSourceFactory,
    RetrievalExpansionFactory,
    RetrievalRequestFactory,
    RetrievalResultObserver,
    StoredAdaptiveArtifact,
    TransformProgramFactory,
    TransformProgramRepairFactory,
)
from statebus.runtime.adaptive_runtime import (
    AdaptiveRuntimeEngine,
    AdaptiveRuntimeRequest,
    AdaptiveRuntimeResult,
)
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.capability_validators import (
    CapabilityValidatorRegistry,
    default_capability_validator_registry,
)
from statebus.runtime.identity import RuntimeIdentityResolutionError, resolve_runtime_identity
from statebus.runtime.plan_policy import PlanPolicyValidator
from statebus.runtime.retrieval_adapter import AdaptiveRetrievalAdapter
from statebus.runtime.telemetry import TelemetryEvent
from statebus.runtime.workspace import WorkspaceLayout, WorkspaceManager
from statebus.state import LayeredStateStore, LayeredStoragePolicy
from statebus.utils import sha256_digest, stable_json_dumps


class AdaptiveMainlineError(RuntimeError):
    pass


PlanNormalizer = Callable[[PlanProposal], tuple[PlanProposal, tuple[str, ...]]]
PlanRepair = Callable[[PlanProposal, PlanPolicyReport, tuple[str, ...]], PlanProposal | None]
ApprovedPlanValidator = Callable[[ApprovedPlan], None]


@dataclass
class AdaptiveMainlineBindings:
    """Domain handlers supplied to the product-owned adaptive assembly point."""

    validator_registry: CapabilityValidatorRegistry = field(
        default_factory=default_capability_validator_registry
    )
    artifacts: dict[str, StoredAdaptiveArtifact] = field(default_factory=dict)
    retrieval_adapter: AdaptiveRetrievalAdapter | None = None
    retrieval_request_factory: RetrievalRequestFactory | None = None
    retrieval_expansion_factory: RetrievalExpansionFactory | None = None
    retrieval_result_observer: RetrievalResultObserver | None = None
    allowed_corpus_scope_ids: tuple[str, ...] = ()
    transform_program_factory: TransformProgramFactory | None = None
    transform_program_repair_factory: TransformProgramRepairFactory | None = None
    code_source_factory: CodeSourceFactory | None = None
    code_repair_factory: CodeRepairFactory | None = None
    code_policy_factory: Callable | None = None
    codeact_contracts: dict[str, dict[str, object]] = field(default_factory=dict)
    quality_semantics_by_capability: dict[str, dict[str, object]] = field(default_factory=dict)
    output_schema_by_capability: dict[str, dict[str, str]] = field(default_factory=dict)
    output_schema_by_step: dict[str, dict[str, str]] = field(default_factory=dict)
    claim_set_factory: ClaimSetFactory | None = None
    builtin_handlers: dict[str, BuiltinHandler] = field(default_factory=dict)


@dataclass(frozen=True)
class AdaptivePlannerAssemblyRecord:
    initial_proposal_hash: str
    effective_proposal_hash: str
    initial_policy_report_hash: str
    final_policy_report_hash: str
    approved_plan_hash: str
    schema_repair_used: bool
    schema_repair_fields: tuple[str, ...]
    policy_repair_used: bool
    hard_rejection: bool
    rejection_category: str = ""
    initial_policy_approved: bool = False
    fallback_used: bool = False
    semantic_replan_required: bool = False
    fallback_proposal_hash: str = ""
    normalization_receipt: PlanNormalizationReceipt | None = None
    approved_plan_bundle: ApprovedPlanBundle | None = None

    def canonical_payload(self) -> dict[str, object]:
        return {
            "initial_proposal_hash": self.initial_proposal_hash,
            "effective_proposal_hash": self.effective_proposal_hash,
            "initial_policy_report_hash": self.initial_policy_report_hash,
            "final_policy_report_hash": self.final_policy_report_hash,
            "approved_plan_hash": self.approved_plan_hash,
            "schema_repair_used": self.schema_repair_used,
            "schema_repair_fields": list(self.schema_repair_fields),
            "policy_repair_used": self.policy_repair_used,
            "hard_rejection": self.hard_rejection,
            "rejection_category": self.rejection_category,
            "initial_policy_approved": self.initial_policy_approved,
            "fallback_used": self.fallback_used,
            "semantic_replan_required": self.semantic_replan_required,
            "fallback_proposal_hash": self.fallback_proposal_hash,
            "normalization_receipt_hash": (
                "" if self.normalization_receipt is None else self.normalization_receipt.receipt_hash
            ),
            "approved_plan_bundle_hash": (
                "" if self.approved_plan_bundle is None else self.approved_plan_bundle.bundle_hash
            ),
        }


@dataclass(frozen=True)
class AdaptiveMainlineRequest:
    trace_id: str
    task_id: str
    canonical_task_spec_hash: str
    envelope: AdaptiveTaskEnvelope
    registry: CapabilityRegistry
    runtime_root: Path
    workspace_root: Path
    propose_plan: Callable[[], PlanProposal]
    bindings: AdaptiveMainlineBindings
    available_input_refs: dict[str, str] = field(default_factory=dict)
    normalize_plan: PlanNormalizer | None = None
    repair_plan: PlanRepair | None = None
    validate_approved_plan: ApprovedPlanValidator | None = None
    fallback_proposal: PlanProposal | None = None
    state_pool_mode: str = "auto"
    socket_path: Path | None = None
    planner_model_id: str = ""
    planner_raw_output_hash: str = ""
    runtime_compatibility_signature: str = ""
    layer_name: str = "L3"
    cleanup_state: bool = True
    canonical_task_spec: CanonicalTaskSpec | None = None
    memory_store_root: Path | None = None
    memory_commit_enabled: bool = True
    memory_commit_replay_class: ReplayClass = ReplayClass.ASSIST
    memory_topic: str = ""
    memory_tags: tuple[str, ...] = ()
    input_lineage_hashes: tuple[str, ...] = ()
    input_schema_digest: str = ""
    validator_digest: str = ""
    runtime_identity: RuntimeIdentity | None = None


@dataclass(frozen=True)
class AdaptiveMainlineInfrastructure:
    state_store: LayeredStateStore
    memory_store: MemoryIndexStore
    workspace_manager: WorkspaceManager
    workspace_layout: WorkspaceLayout
    socket_path: Path


@dataclass(frozen=True)
class AdaptiveMemoryCommitDecision:
    attempted: bool
    committed: bool
    reason: str
    memory_id: str = ""
    artifact_ref_id: str = ""
    artifact_hash: str = ""
    quality_report_hash: str = ""
    input_lineage_hashes: tuple[str, ...] = ()
    output_contract_version: str = ""
    validator_digest: str = ""
    benchmark_gold_used: bool = False

    def canonical_payload(self) -> dict[str, object]:
        return {
            "attempted": self.attempted,
            "committed": self.committed,
            "reason": self.reason,
            "memory_id": self.memory_id,
            "artifact_ref_id": self.artifact_ref_id,
            "artifact_hash": self.artifact_hash,
            "quality_report_hash": self.quality_report_hash,
            "input_lineage_hashes": list(self.input_lineage_hashes),
            "output_contract_version": self.output_contract_version,
            "validator_digest": self.validator_digest,
            "benchmark_gold_used": self.benchmark_gold_used,
        }


@dataclass(frozen=True)
class AdaptiveMainlineResult:
    runtime: AdaptiveRuntimeResult
    planner: AdaptivePlannerAssemblyRecord
    context: AdaptiveDispatchContext
    infrastructure: AdaptiveMainlineInfrastructure
    manifest_path: Path
    state_cleanup_completed: bool
    memory_commit_decision: AdaptiveMemoryCommitDecision
    runtime_identity: RuntimeIdentity | None = None
    approved_plan_bundle: ApprovedPlanBundle | None = None

    @property
    def completed(self) -> bool:
        return self.runtime.completed


class AdaptiveMainlineRunner:
    """Single product assembly point for bounded adaptive execution."""

    def run(self, request: AdaptiveMainlineRequest) -> AdaptiveMainlineResult:
        if request.envelope.workflow_mode != WorkflowMode.ADAPTIVE_BOUNDED:
            raise AdaptiveMainlineError("adaptive_bounded_workflow_mode_required")
        if request.envelope.task_id != request.task_id:
            raise AdaptiveMainlineError("adaptive_mainline_task_id_mismatch")
        if (
            request.canonical_task_spec is not None
            and request.canonical_task_spec.spec_hash != request.canonical_task_spec_hash
        ):
            raise AdaptiveMainlineError("adaptive_mainline_canonical_spec_hash_mismatch")
        try:
            runtime_identity = resolve_runtime_identity(
                request.runtime_identity,
                task_id=request.task_id,
                trace_id=request.trace_id,
                canonical_task_spec_hash=request.canonical_task_spec_hash,
            )
            runtime_identity.validate_legacy_projection(
                task_id=request.envelope.task_id,
                trace_id=request.trace_id,
                canonical_task_spec_hash=request.envelope.canonical_task_spec_hash,
            )
        except (RuntimeIdentityResolutionError, IdentityContractError) as exc:
            raise AdaptiveMainlineError(f"adaptive_mainline_identity_invalid:{exc}") from exc

        runtime_root = Path(request.runtime_root)
        runtime_root.mkdir(parents=True, exist_ok=True)
        workspace_manager = WorkspaceManager(Path(request.workspace_root))
        workspace_layout = workspace_manager.ensure_layout(runtime_identity.runtime_task_id)
        state_store = LayeredStateStore(
            root=runtime_root / "state",
            policy=LayeredStoragePolicy.for_state_pool_mode(request.state_pool_mode),
        )
        memory_store = MemoryIndexStore(
            store_root=(
                Path(request.memory_store_root)
                if request.memory_store_root is not None
                else runtime_root / "memory_index"
            )
        )
        memory_store.load_persisted_state()
        socket_path = request.socket_path or runtime_root / "control.sock"
        infrastructure = AdaptiveMainlineInfrastructure(
            state_store=state_store,
            memory_store=memory_store,
            workspace_manager=workspace_manager,
            workspace_layout=workspace_layout,
            socket_path=socket_path,
        )

        proposal, approved_plan, planner_record = self._assemble_plan(request)
        bindings = request.bindings
        input_lineage_hashes = tuple(dict.fromkeys((
            *request.input_lineage_hashes,
            *(
                stored.artifact.blob_hash
                for ref_id, stored in bindings.artifacts.items()
                if ref_id in request.available_input_refs
            ),
        )))
        input_schema_digest = request.input_schema_digest or sha256_digest(sorted(
            (
                sorted({key for row in stored.rows for key in row})
                for ref_id, stored in bindings.artifacts.items()
                if ref_id in request.available_input_refs
            ),
            key=lambda fields: tuple(fields),
        ))
        validator_digest = request.validator_digest or sha256_digest({
            "registry_digest": request.registry.digest,
            "quality_semantics": bindings.quality_semantics_by_capability,
            "output_schema_by_capability": bindings.output_schema_by_capability,
            "output_schema_by_step": bindings.output_schema_by_step,
        })
        context = AdaptiveDispatchContext(
            registry=request.registry,
            validator_registry=bindings.validator_registry,
            artifacts=bindings.artifacts,
            retrieval_adapter=bindings.retrieval_adapter,
            retrieval_request_factory=bindings.retrieval_request_factory,
            retrieval_expansion_factory=bindings.retrieval_expansion_factory,
            retrieval_result_observer=bindings.retrieval_result_observer,
            allowed_corpus_scope_ids=bindings.allowed_corpus_scope_ids,
            transform_program_factory=bindings.transform_program_factory,
            transform_program_repair_factory=bindings.transform_program_repair_factory,
            code_source_factory=bindings.code_source_factory,
            code_repair_factory=bindings.code_repair_factory,
            code_policy_factory=bindings.code_policy_factory,
            codeact_contracts=bindings.codeact_contracts,
            quality_semantics_by_capability=bindings.quality_semantics_by_capability,
            output_schema_by_capability=bindings.output_schema_by_capability,
            output_schema_by_step=bindings.output_schema_by_step,
            claim_set_factory=bindings.claim_set_factory,
            builtin_handlers=bindings.builtin_handlers,
            state_store=state_store,
            memory_store=memory_store,
            workspace_manager=workspace_manager,
            socket_path=socket_path,
            canonical_task_spec=request.canonical_task_spec,
            input_lineage_hashes=input_lineage_hashes,
            input_schema_digest=input_schema_digest,
            validator_digest=validator_digest,
            runtime_compatibility_signature=(
                request.runtime_compatibility_signature or request.registry.digest
            ),
        )
        runtime_request = AdaptiveRuntimeRequest(
            trace_id=request.trace_id,
            task_id=request.task_id,
            canonical_task_spec_hash=request.canonical_task_spec_hash,
            envelope=request.envelope,
            approved_plan=approved_plan,
            registry=request.registry,
            runtime_root=str(runtime_root),
            workspace_root_id=str(workspace_layout.root),
            state_root=str(state_store.root),
            available_input_refs=dict(request.available_input_refs),
            proposal_hash=proposal.proposal_hash,
            planner_model_id=request.planner_model_id or proposal.model_id,
            planner_raw_output_hash=request.planner_raw_output_hash or proposal.raw_output_hash,
            proposal_valid=planner_record.initial_policy_approved,
            policy_rejected=not planner_record.initial_policy_approved,
            repair_used=(planner_record.schema_repair_used or planner_record.policy_repair_used),
            fallback_used=planner_record.fallback_used,
            dispatcher=AdaptiveCapabilityDispatcher(context=context),
            layer_name=request.layer_name,
            runtime_identity=runtime_identity,
            identity_is_compatibility_projection=request.runtime_identity is None,
        )

        state_cleanup_completed = False
        released_state_ids: set[str] = set()
        runtime_result = None
        manifest_path: Path | None = None
        memory_commit_decision = AdaptiveMemoryCommitDecision(
            attempted=False,
            committed=False,
            reason="memory_commit_not_reached",
        )
        try:
            runtime_result = AdaptiveRuntimeEngine().run(runtime_request)
            memory_commit_decision = self._commit_verified_memory(
                request=request,
                approved_plan=approved_plan,
                runtime=runtime_result,
                context=context,
                memory_store=memory_store,
                runtime_identity=runtime_identity,
            )
            runtime_result.telemetry.emit(
                TelemetryEvent.create(
                    trace_id=request.trace_id,
                    task_id=request.task_id,
                    step_id="runtime.memory_commit",
                    event_type="MEMORY_COMMIT_VERIFIED",
                    role="runtime_supervisor",
                    channel="memory",
                    payload=memory_commit_decision.canonical_payload(),
                    metrics={
                        "memory_commit_gate_count": float(memory_commit_decision.attempted),
                        "memory_commit_count": float(memory_commit_decision.committed),
                        "memory_commit_rejected_count": float(
                            memory_commit_decision.attempted
                            and not memory_commit_decision.committed
                        ),
                        "memory_benchmark_gold_input_count": 0.0,
                    },
                )
            )
            runtime_result.telemetry.emit(
                TelemetryEvent.create(
                    trace_id=request.trace_id,
                    task_id=request.task_id,
                    step_id="planner.plan",
                    event_type="ADAPTIVE_MAINLINE_ASSEMBLED",
                    role="planner",
                    channel="control",
                    payload={
                        **planner_record.canonical_payload(),
                        "state_root": str(state_store.root),
                        "memory_root": str(memory_store.store_root),
                        "workspace_root": str(workspace_layout.root),
                        "socket_path": str(socket_path),
                    },
                    metrics={
                        "planner_step_completed": 1.0,
                        "planner_hard_rejection_count": float(planner_record.hard_rejection),
                        "planner_schema_repair_count": float(planner_record.schema_repair_used),
                        "planner_policy_repair_count": float(planner_record.policy_repair_used),
                        "planner_final_approved_count": 1.0,
                    },
                )
            )
            for state_id, publication in tuple(context.semantic_state_publications.items()):
                runtime_result.telemetry.emit(
                    TelemetryEvent.create(
                        trace_id=request.trace_id,
                        task_id=request.task_id,
                        step_id="retriever.fanout",
                        event_type="STATE_RELEASED",
                        role="runtime_supervisor",
                        channel="semantic_state",
                        payload={
                            "ref_id": state_id,
                            "owner": request.envelope.task_id,
                        },
                        metrics={
                            "semantic_state_release_count": 1.0,
                            "semantic_state_released_bytes": float(
                                getattr(publication.handle, "size_bytes", 0)
                            ),
                        },
                    )
                )
                state_store.release(state_id)
                released_state_ids.add(state_id)
            runtime_result.telemetry.close()
            manifest_path = self._persist_manifest(
                request=request,
                planner=planner_record,
                runtime=runtime_result,
                context=context,
                infrastructure=infrastructure,
                memory_commit_decision=memory_commit_decision,
                runtime_identity=runtime_identity,
            )
        finally:
            for state_id in tuple(context.semantic_state_publications):
                if state_id not in released_state_ids and state_id in state_store.materializations:
                    state_store.release(state_id)
            if request.cleanup_state:
                state_store.teardown()
                state_cleanup_completed = True

        return AdaptiveMainlineResult(
            runtime=runtime_result,
            planner=planner_record,
            context=context,
            infrastructure=infrastructure,
            manifest_path=manifest_path or (runtime_root / "adaptive_mainline_manifest.json"),
            state_cleanup_completed=state_cleanup_completed,
            memory_commit_decision=memory_commit_decision,
            runtime_identity=runtime_identity,
            approved_plan_bundle=planner_record.approved_plan_bundle,
        )

    @staticmethod
    def _assemble_plan(
        request: AdaptiveMainlineRequest,
    ) -> tuple[PlanProposal, ApprovedPlan, AdaptivePlannerAssemblyRecord]:
        raw_proposal = request.propose_plan()
        if not isinstance(raw_proposal, PlanProposal):
            raise AdaptiveMainlineError("planner_must_return_plan_proposal")
        if raw_proposal.task_id != request.task_id:
            raise AdaptiveMainlineError("planner_proposal_task_id_mismatch")
        validator = PlanPolicyValidator(
            request.registry,
            allow_llm_python=request.envelope.allow_llm_python,
        )
        raw_outcome = validator.validate(
            raw_proposal,
            request.envelope,
            available_input_refs=request.available_input_refs,
        )
        effective = raw_proposal
        normalization_fields: tuple[str, ...] = ()
        normalization_source = raw_proposal
        normalization_effective = raw_proposal

        def apply_normalizer(
            proposal: PlanProposal,
        ) -> tuple[PlanProposal, tuple[str, ...]]:
            if request.normalize_plan is None:
                return proposal, ()
            normalized_result = request.normalize_plan(proposal)
            if isinstance(normalized_result, PlanProposal):
                candidate, fields = normalized_result, ()
            elif (
                isinstance(normalized_result, tuple)
                and len(normalized_result) == 2
                and isinstance(normalized_result[0], PlanProposal)
            ):
                candidate = normalized_result[0]
                fields = tuple(str(item) for item in normalized_result[1])
            else:
                raise AdaptiveMainlineError("plan_normalizer_contract_invalid")
            if not validator.is_mechanically_equivalent(
                proposal,
                candidate,
                registry=request.registry,
                runtime_task_id=request.task_id,
                task_contract_hash=request.canonical_task_spec_hash,
            ):
                # A mechanical normalizer may complete typed edges, but it may
                # never alter the semantic graph.  A changed graph needs a new
                # PlanProposal and a fresh policy decision.
                raise AdaptiveMainlineError(
                    "planner_normalization_semantic_change_requires_new_proposal"
                )
            return candidate, tuple(dict.fromkeys(item for item in fields if item))

        if request.normalize_plan is not None:
            effective, normalization_fields = apply_normalizer(raw_proposal)
            normalization_effective = effective
        try:
            normalization_receipt = PlanNormalizationReceipt.from_proposals(
                normalization_source,
                normalization_effective,
                changed_fields=normalization_fields,
                runtime_task_id=request.task_id,
                task_contract_hash=request.canonical_task_spec_hash,
                task_identity=request.runtime_identity,
                registry=request.registry,
            )
        except PlanProvenanceError as exc:
            raise AdaptiveMainlineError(f"plan_normalization_provenance_invalid:{exc}") from exc
        normalization_fields = normalization_receipt.changed_fields
        outcome = validator.validate(
            effective,
            request.envelope,
            available_input_refs=request.available_input_refs,
        )
        policy_repair_used = False
        semantic_replan_required = False
        fallback_used = False
        fallback_proposal_hash = ""
        if outcome.approved_plan is None and request.repair_plan is not None:
            repaired = request.repair_plan(effective, outcome.report, normalization_fields)
            if repaired is not None and not isinstance(repaired, PlanProposal):
                raise AdaptiveMainlineError("plan_repair_contract_invalid")
            if repaired is not None:
                if not validator.is_semantically_equivalent(
                    effective,
                    repaired,
                    runtime_task_id=request.task_id,
                    task_contract_hash=request.canonical_task_spec_hash,
                    dependency_order_sensitive=True,
                ):
                    # Keep the rejection/fallback path available, but never
                    # record a semantic graph replacement as a schema repair.
                    semantic_replan_required = True
                else:
                    repaired_effective, repair_fields = apply_normalizer(repaired)
                    if not validator.is_mechanically_equivalent(
                        effective,
                        repaired_effective,
                        registry=request.registry,
                        runtime_task_id=request.task_id,
                        task_contract_hash=request.canonical_task_spec_hash,
                    ):
                        semantic_replan_required = True
                    else:
                        effective = repaired_effective
                        normalization_fields = tuple(dict.fromkeys((*normalization_fields, *repair_fields)))
                        outcome = validator.validate(
                            effective,
                            request.envelope,
                            available_input_refs=request.available_input_refs,
                        )
                        policy_repair_used = outcome.approved_plan is not None
                        if policy_repair_used:
                            normalization_effective = effective
                            try:
                                normalization_receipt = PlanNormalizationReceipt.from_proposals(
                                    normalization_source,
                                    normalization_effective,
                                    changed_fields=normalization_fields,
                                    runtime_task_id=request.task_id,
                                    task_contract_hash=request.canonical_task_spec_hash,
                                    task_identity=request.runtime_identity,
                                    registry=request.registry,
                                )
                            except PlanProvenanceError as exc:
                                raise AdaptiveMainlineError(
                                    f"plan_normalization_provenance_invalid:{exc}"
                                ) from exc
                            normalization_fields = normalization_receipt.changed_fields
        if outcome.approved_plan is None and request.fallback_proposal is not None:
            if not isinstance(request.fallback_proposal, PlanProposal):
                raise AdaptiveMainlineError("fallback_proposal_contract_invalid")
            effective = request.fallback_proposal
            # Keep fallback selection in the policy boundary so the final
            # report remains explicitly ``FALLBACK_FIXED_PLAN`` instead of
            # looking like an ordinary approved replacement.
            outcome = validator.fallback(
                raw_proposal,
                request.envelope,
                effective,
                available_input_refs=request.available_input_refs,
            )
            fallback_used = outcome.approved_plan is not None
            fallback_proposal_hash = effective.proposal_hash if fallback_used else ""
        if outcome.approved_plan is None:
            category = _planner_rejection_category(outcome.report)
            if semantic_replan_required:
                category = "semantic_replan_required"
            raise AdaptiveMainlineError(f"planner_hard_rejection:{category}")
        if request.validate_approved_plan is not None:
            request.validate_approved_plan(outcome.approved_plan)
        try:
            bundle = ApprovedPlanBundle.from_parts(
                runtime_task_id=request.task_id,
                task_contract_hash=request.canonical_task_spec_hash,
                source_proposal=raw_proposal,
                effective_proposal=effective,
                normalization_receipt=normalization_receipt,
                plan_policy_report=outcome.report,
                approved_plan=outcome.approved_plan,
                logical_capability_registry_digest=request.registry.digest,
                fallback_used=fallback_used,
                fallback_proposal_hash=fallback_proposal_hash,
            )
        except PlanProvenanceError as exc:
            raise AdaptiveMainlineError(f"approved_plan_provenance_invalid:{exc}") from exc
        planner_record = AdaptivePlannerAssemblyRecord(
            initial_proposal_hash=raw_proposal.proposal_hash,
            effective_proposal_hash=effective.proposal_hash,
            initial_policy_report_hash=raw_outcome.report.report_hash,
            final_policy_report_hash=outcome.report.report_hash,
            approved_plan_hash=outcome.approved_plan.approved_plan_hash,
            schema_repair_used=bool(normalization_fields),
            schema_repair_fields=tuple(normalization_fields),
            policy_repair_used=policy_repair_used,
            hard_rejection=False,
            initial_policy_approved=raw_outcome.approved_plan is not None,
            fallback_used=fallback_used,
            semantic_replan_required=semantic_replan_required,
            fallback_proposal_hash=fallback_proposal_hash,
            normalization_receipt=normalization_receipt,
            approved_plan_bundle=bundle,
        )
        return effective, outcome.approved_plan, planner_record

    @staticmethod
    def _commit_verified_memory(
        *,
        request: AdaptiveMainlineRequest,
        approved_plan: ApprovedPlan,
        runtime: AdaptiveRuntimeResult,
        context: AdaptiveDispatchContext,
        memory_store: MemoryIndexStore,
        runtime_identity: RuntimeIdentity | None = None,
    ) -> AdaptiveMemoryCommitDecision:
        if runtime_identity is None:
            runtime_identity = runtime.runtime_identity or resolve_runtime_identity(
                request.runtime_identity,
                task_id=request.task_id,
                trace_id=request.trace_id,
                canonical_task_spec_hash=request.canonical_task_spec_hash,
            )
        if not request.memory_commit_enabled:
            return AdaptiveMemoryCommitDecision(False, False, "memory_commit_disabled")
        if request.canonical_task_spec is None:
            return AdaptiveMemoryCommitDecision(False, False, "canonical_task_spec_not_supplied")
        if not runtime.completed:
            return AdaptiveMemoryCommitDecision(True, False, "runtime_not_completed")
        if not context.input_lineage_hashes:
            return AdaptiveMemoryCommitDecision(True, False, "input_lineage_missing")
        memory_query = context.memory_queries_by_task.get(request.task_id)
        if memory_query is None or memory_query.query_embedding is None:
            return AdaptiveMemoryCommitDecision(True, False, "memory_query_embedding_missing")

        role_by_step = {step.step_id: step.role for step in approved_plan.steps}
        executor_artifact = None
        for dispatch in reversed(runtime.dispatches):
            if role_by_step.get(dispatch.step_id) != "executor":
                continue
            executor_artifact = next(
                (
                    context.artifacts[ref_id].artifact
                    for ref_id in reversed(dispatch.output_refs)
                    if ref_id in context.artifacts
                ),
                None,
            )
            if executor_artifact is not None:
                break
        if executor_artifact is None:
            return AdaptiveMemoryCommitDecision(True, False, "terminal_executor_artifact_missing")
        if executor_artifact.verification_state != RefStatus.VERIFIED:
            return AdaptiveMemoryCommitDecision(
                True,
                False,
                "terminal_executor_artifact_not_verified",
                artifact_ref_id=executor_artifact.artifact_id,
                artifact_hash=executor_artifact.blob_hash,
            )

        artifact_path = Path(executor_artifact.root_id) / executor_artifact.relpath
        if not artifact_path.is_file() or sha256_digest(artifact_path.read_bytes()) != executor_artifact.blob_hash:
            return AdaptiveMemoryCommitDecision(
                True,
                False,
                "terminal_executor_artifact_hash_mismatch",
                artifact_ref_id=executor_artifact.artifact_id,
                artifact_hash=executor_artifact.blob_hash,
            )
        matching_quality_reports = [
            report
            for report in context.quality_reports.values()
            if getattr(report, "verified", False)
            and getattr(report, "output_artifact_hash", "") == executor_artifact.blob_hash
        ]
        expected_quality_hash = str(executor_artifact.metadata.get("quality_report_hash", ""))
        quality_report = next(
            (
                report
                for report in matching_quality_reports
                if report.report_hash == expected_quality_hash
            ),
            None,
        )
        if quality_report is None:
            return AdaptiveMemoryCommitDecision(
                True,
                False,
                "terminal_quality_report_artifact_hash_mismatch",
                artifact_ref_id=executor_artifact.artifact_id,
                artifact_hash=executor_artifact.blob_hash,
                quality_report_hash=expected_quality_hash,
            )
        recipe = context.execution_recipes_by_artifact.get(executor_artifact.artifact_id)
        if not isinstance(recipe, dict) or not recipe:
            return AdaptiveMemoryCommitDecision(
                True,
                False,
                "execution_recipe_missing",
                artifact_ref_id=executor_artifact.artifact_id,
                artifact_hash=executor_artifact.blob_hash,
                quality_report_hash=quality_report.report_hash,
            )

        executor_step = next(
            step for step in approved_plan.steps if step.step_id == executor_artifact.step_id
        )
        replay_class = request.memory_commit_replay_class
        memory_type = {
            ReplayClass.EXACT_REPLAY: MemoryType.EXACT_REPLAY,
            ReplayClass.VALIDATED_REPLAY: MemoryType.VALIDATED_REPLAY,
        }.get(replay_class, MemoryType.STRATEGY)
        memory_id = (
            f"memory:{request.task_id}:"
            f"{executor_artifact.blob_hash.removeprefix('sha256:')[:16]}"
        )
        created_at_ns = time.time_ns()
        tags = tuple(dict.fromkeys((
            request.canonical_task_spec.task_family,
            request.canonical_task_spec.intent_op,
            *request.canonical_task_spec.target_entities,
            *request.memory_tags,
        )))
        recipe_hash = sha256_digest(recipe)
        summary = (
            f"Verified {recipe.get('execution_kind', 'analysis')} recipe for "
            f"{request.canonical_task_spec.task_family}/"
            f"{request.canonical_task_spec.intent_op}; artifact lineage retained."
        )
        memory_store.put_embedding(memory_query.query_embedding)
        commit = MemoryCommit(
            memory_ref=MemoryRef(
                memory_id=memory_id,
                memory_type=memory_type,
                replay_class=replay_class,
                score=1.0,
                source_task_id=request.task_id,
                source_agent="executor",
                created_at_ns=created_at_ns,
                task_theme=request.memory_topic or request.canonical_task_spec.task_family,
                tags=tags,
                source_role_path=("planner", "retriever", "executor"),
                # Keep the legacy memory provenance projection in Batch 1;
                # RunID is recorded by the runtime identity/manifest without
                # changing MemoryRef hashing or replay semantics.
                producer_run_id=request.trace_id,
                summary=summary,
                canonical_task_spec_hash=request.canonical_task_spec_hash,
                artifact_ref_id=executor_artifact.artifact_id,
                semantic_state_ref_id=next(iter(context.semantic_state_publications), ""),
                embedding_ref_id=memory_query.query_embedding.embedding_id,
                manifest_hash=executor_artifact.manifest_hash,
                metadata={
                    "runtime_signature_hash": context.runtime_compatibility_signature,
                    "output_contract_version": executor_step.output_contract_version,
                    "validator_digest": context.validator_digest,
                    "quality_report_hash": quality_report.report_hash,
                    "input_lineage_hashes": list(context.input_lineage_hashes),
                    "input_schema_digest": context.input_schema_digest,
                    "execution_recipe": dict(recipe),
                    "execution_recipe_hash": recipe_hash,
                    "replay_ready": executor_artifact.replay_ready,
                    "artifact_root_id": executor_artifact.root_id,
                    "artifact_relpath": executor_artifact.relpath,
                    "artifact_blob_hash": executor_artifact.blob_hash,
                    "benchmark_gold_used": False,
                },
            ),
            canonical_task_spec=request.canonical_task_spec,
            required_outputs=request.canonical_task_spec.required_outputs,
            quality_floor_pass=True,
            created_from_artifact_hash=executor_artifact.blob_hash,
        )
        committed = memory_store.commit_candidate(
            commit=commit,
            quality_floor_pass=True,
            answer_adopted=True,
        )
        return AdaptiveMemoryCommitDecision(
            attempted=True,
            committed=True,
            reason="runtime_quality_and_artifact_hash_verified",
            memory_id=committed.memory_ref.memory_id,
            artifact_ref_id=executor_artifact.artifact_id,
            artifact_hash=executor_artifact.blob_hash,
            quality_report_hash=quality_report.report_hash,
            input_lineage_hashes=context.input_lineage_hashes,
            output_contract_version=executor_step.output_contract_version,
            validator_digest=context.validator_digest,
            benchmark_gold_used=False,
        )

    @staticmethod
    def _persist_manifest(
        *,
        request: AdaptiveMainlineRequest,
        planner: AdaptivePlannerAssemblyRecord,
        runtime: AdaptiveRuntimeResult,
        context: AdaptiveDispatchContext,
        infrastructure: AdaptiveMainlineInfrastructure,
        memory_commit_decision: AdaptiveMemoryCommitDecision,
        runtime_identity: RuntimeIdentity | None = None,
    ) -> Path:
        if runtime_identity is None:
            runtime_identity = runtime.runtime_identity or resolve_runtime_identity(
                request.runtime_identity,
                task_id=request.task_id,
                trace_id=request.trace_id,
                canonical_task_spec_hash=request.canonical_task_spec_hash,
            )
        manifest_path = Path(request.runtime_root) / "adaptive_mainline_manifest.json"
        payload = {
            "schema_version": "statebus.adaptive_mainline_manifest.v1",
            "trace_id": request.trace_id,
            "task_id": request.task_id,
            "runtime_identity": runtime_identity.canonical_payload(),
            "runtime_identity_hash": runtime_identity.identity_hash,
            "workflow_mode": request.envelope.workflow_mode.value,
            "planner": planner.canonical_payload(),
            "plan_normalization_receipt": (
                None
                if planner.normalization_receipt is None
                else planner.normalization_receipt.canonical_payload()
            ),
            "approved_plan_bundle": (
                None
                if planner.approved_plan_bundle is None
                else planner.approved_plan_bundle.canonical_payload()
            ),
            "approved_plan_bundle_hash": (
                ""
                if planner.approved_plan_bundle is None
                else planner.approved_plan_bundle.bundle_hash
            ),
            "runtime_completed": runtime.completed,
            "runtime_session_hash": sha256_digest(runtime.session.canonical_payload()),
            "dispatches": [dispatch.__dict__ for dispatch in runtime.dispatches],
            "roots": {
                "runtime": str(request.runtime_root),
                "state": str(infrastructure.state_store.root),
                "memory": str(infrastructure.memory_store.store_root),
                "workspace": str(infrastructure.workspace_layout.root),
            },
            "socket_path": str(infrastructure.socket_path),
            "runtime_compatibility_signature": context.runtime_compatibility_signature,
            "memory_query_hashes": {
                task_id: query.query_hash
                for task_id, query in sorted(context.memory_queries_by_task.items())
            },
            "memory_query_results": {
                step_id: result.canonical_payload()
                for step_id, result in sorted(context.memory_match_results.items())
            },
            "memory_consumption_records": [
                record.canonical_payload()
                for record in context.memory_consumption_records
            ],
            "memory_commit_decision": memory_commit_decision.canonical_payload(),
            "artifact_ref_ids": sorted(context.artifacts),
            "evidence_ref_ids": sorted(context.evidence_packs),
            "created_at_ns": time.time_ns(),
        }
        manifest_path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")
        return manifest_path


def _planner_rejection_category(report: PlanPolicyReport) -> str:
    codes = {issue.error_code for issue in report.issues}
    if any("capability" in code for code in codes):
        return "capability_missing"
    if any("contract" in code or "schema" in code for code in codes):
        return "invalid_contract"
    if any("risk" in code or "authority" in code or "scope" in code for code in codes):
        return "unsafe_or_out_of_scope"
    return "policy_false_reject"
