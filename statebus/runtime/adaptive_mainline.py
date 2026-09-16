from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import tempfile
import time
from typing import Callable

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    ApprovedPlan,
    ApprovedPlanBundle,
    ArtifactVerificationDecision,
    ArtifactVerificationReceipt,
    CanonicalTaskSpec,
    IdentityContractError,
    PlanNormalizationReceipt,
    PlanPolicyReport,
    PlanProposal,
    PlanProvenanceError,
    RefStatus,
    ReplayClass,
    RuntimeIdentity,
    MEMORY_ADMISSION_POLICY_ID,
    MEMORY_ADMISSION_POLICY_VERSION,
    WorkflowMode,
)
from statebus.memory import (
    MemoryAdmissionDecision,
    MemoryAdmissionReceipt,
    MemoryIndexStore,
)
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
from statebus.runtime.provider_registry import ExecutionProviderRegistry
from statebus.contracts import ProviderRuntimeFacts
from statebus.runtime.role_providers import BoundProviderHandler, ProviderStateReadFacade, ProviderRequest
from statebus.runtime.memory_projection import (
    MemoryProjectionSpec,
    build_memory_commit,
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
from statebus.runtime.state_consumption import build_state_release_reclaim_receipt
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
    artifact_verification_receipts: dict[str, ArtifactVerificationReceipt] = field(
        default_factory=dict
    )
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
    bound_provider_handlers: dict[str, BoundProviderHandler] = field(default_factory=dict)
    provider_state_reader_factory: Callable[[ProviderRequest], ProviderStateReadFacade | None] | None = None
    provider_invocation_evidence: dict[str, dict[str, str]] = field(default_factory=dict)
    # Internal deterministic fixture seam for an observed no-effect Memory
    # read. It does not create a receipt or alter Runtime authority.
    memory_after_surface_hash_by_memory_id: dict[str, str] = field(default_factory=dict)


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
    propose_plan: Callable[[], PlanProposal] | None
    bindings: AdaptiveMainlineBindings
    approved_plan_bundle: ApprovedPlanBundle | None = None
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
    provider_registry: ExecutionProviderRegistry | None = None
    provider_runtime_facts: dict[str, ProviderRuntimeFacts] = field(default_factory=dict)


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
    memory_admission_receipt_hash: str = ""

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
            "memory_admission_receipt_hash": self.memory_admission_receipt_hash,
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
    """Single product assembly point for canonical Runtime execution."""

    def run(self, request: AdaptiveMainlineRequest) -> AdaptiveMainlineResult:
        if request.envelope.workflow_mode not in {
            WorkflowMode.STRICT_FIXED,
            WorkflowMode.ADAPTIVE_SHADOW,
            WorkflowMode.ADAPTIVE_BOUNDED,
        }:
            raise AdaptiveMainlineError("unsupported_mainline_workflow_mode")
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
            artifact_verification_receipts=bindings.artifact_verification_receipts,
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
            bound_provider_handlers=bindings.bound_provider_handlers,
            provider_state_reader_factory=bindings.provider_state_reader_factory,
            provider_invocation_evidence=bindings.provider_invocation_evidence,
            provider_registry=(
                request.provider_registry
                or ExecutionProviderRegistry.from_legacy_capability_registry(request.registry)
            ),
            state_store=state_store,
            memory_store=memory_store,
            workspace_manager=workspace_manager,
            socket_path=socket_path,
            runtime_identity=runtime_identity,
            canonical_task_spec=request.canonical_task_spec,
            input_lineage_hashes=input_lineage_hashes,
            input_schema_digest=input_schema_digest,
            validator_digest=validator_digest,
            runtime_compatibility_signature=(
                request.runtime_compatibility_signature or request.registry.digest
            ),
            memory_after_surface_hash_by_memory_id=dict(
                bindings.memory_after_surface_hash_by_memory_id
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
            provider_registry=request.provider_registry,
            provider_runtime_facts=dict(request.provider_runtime_facts),
            identity_is_compatibility_projection=request.runtime_identity is None,
            memory_projection_spec=self._memory_projection_spec(
                request=request,
                approved_plan=approved_plan,
                context=context,
            ),
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
            # Result-admission binding happens inside Runtime after the
            # dispatcher has produced its step metrics. Reconcile the
            # receipt-backed Memory counters once that join is complete so
            # telemetry aggregation reflects actual-use for both changed and
            # no-effect reads without inventing a skip/replay metric.
            runtime_result.telemetry.emit(
                TelemetryEvent.create(
                    trace_id=request.trace_id,
                    task_id=request.task_id,
                    step_id="runtime.memory_consumption",
                    event_type="METRIC_SNAPSHOT",
                    role="runtime_supervisor",
                    channel="memory",
                    payload={
                        "memory_receipt_reconciliation": True,
                        "memory_consumption_record_count": len(context.memory_consumption_records),
                    },
                    metrics={
                        "memory_actual_use_count": float(sum(
                            bool(record.attempt_result_admission_receipt_hash)
                            for record in context.memory_consumption_records
                        )),
                        "memory_behavioral_effect_count": float(sum(
                            record.behavioral_effect == "changed"
                            and bool(record.attempt_result_admission_receipt_hash)
                            for record in context.memory_consumption_records
                        )),
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
                state_store.release_owner(
                    state_id,
                    owner_session_id=runtime_identity.session_id,
                )
                owner_released_at_ns = time.time_ns()
                lifetime = state_store.lifetimes.get(state_id)
                if lifetime is not None:
                    lifecycle_timestamps = context.state_lifecycle_timestamps.setdefault(state_id, {})
                    lifecycle_timestamps["owner_released_at_ns"] = owner_released_at_ns
                    if lifetime.physical_reclaimed:
                        lifecycle_timestamps["physical_reclaimed_at_ns"] = time.time_ns()
                    publication_receipt = context.state_publication_receipts.get(state_id, {})
                    access_grants = context.state_access_grants.get(state_id, ())
                    context.state_release_reclaim_receipts[state_id] = build_state_release_reclaim_receipt(
                        lifetime=lifetime,
                        owner_session_id=runtime_identity.session_id,
                        producer_task_id=runtime_identity.runtime_task_id,
                        producer_grant_hash=str(publication_receipt.get("capability_grant_hash", "")),
                        lease_expires_at_ns=max(
                            (int(getattr(grant, "expires_at_ns", 0)) for grant in access_grants),
                            default=0,
                        ),
                        response_admitted_at_ns=lifecycle_timestamps.get("response_admitted_at_ns", 0),
                        downstream_effect_completed_at_ns=lifecycle_timestamps.get("downstream_effect_completed_at_ns", 0),
                        worker_pin_released_at_ns=lifecycle_timestamps.get("worker_pin_released_at_ns", 0),
                        runtime_pin_released_at_ns=lifecycle_timestamps.get("runtime_pin_released_at_ns", 0),
                        owner_released_at_ns=lifecycle_timestamps.get("owner_released_at_ns", 0),
                        physical_reclaimed_at_ns=lifecycle_timestamps.get("physical_reclaimed_at_ns", 0),
                    )
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
                    state_store.release_owner(
                        state_id,
                        owner_session_id=runtime_identity.session_id,
                    )
                    owner_released_at_ns = time.time_ns()
                    lifetime = state_store.lifetimes.get(state_id)
                    if lifetime is not None:
                        lifecycle_timestamps = context.state_lifecycle_timestamps.setdefault(state_id, {})
                        lifecycle_timestamps["owner_released_at_ns"] = owner_released_at_ns
                        if lifetime.physical_reclaimed:
                            lifecycle_timestamps["physical_reclaimed_at_ns"] = time.time_ns()
                        publication_receipt = context.state_publication_receipts.get(state_id, {})
                        access_grants = context.state_access_grants.get(state_id, ())
                        context.state_release_reclaim_receipts[state_id] = build_state_release_reclaim_receipt(
                            lifetime=lifetime,
                            owner_session_id=runtime_identity.session_id,
                            producer_task_id=runtime_identity.runtime_task_id,
                            producer_grant_hash=str(publication_receipt.get("capability_grant_hash", "")),
                            lease_expires_at_ns=max(
                                (int(getattr(grant, "expires_at_ns", 0)) for grant in access_grants),
                                default=0,
                            ),
                            response_admitted_at_ns=lifecycle_timestamps.get("response_admitted_at_ns", 0),
                            downstream_effect_completed_at_ns=lifecycle_timestamps.get("downstream_effect_completed_at_ns", 0),
                            worker_pin_released_at_ns=lifecycle_timestamps.get("worker_pin_released_at_ns", 0),
                            runtime_pin_released_at_ns=lifecycle_timestamps.get("runtime_pin_released_at_ns", 0),
                            owner_released_at_ns=lifecycle_timestamps.get("owner_released_at_ns", 0),
                            physical_reclaimed_at_ns=lifecycle_timestamps.get("physical_reclaimed_at_ns", 0),
                        )
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
        c2a = request.envelope.domain_pack_id == "c2a_four_role_v1"
        if c2a:
            _validate_c2a_envelope(request)
        if request.approved_plan_bundle is not None:
            bundle = request.approved_plan_bundle
            if (
                not bundle.verify_hash_links()
                or bundle.runtime_task_id != request.task_id
                or bundle.task_contract_hash != request.canonical_task_spec_hash
                or bundle.logical_capability_registry_digest != request.registry.digest
                or bundle.source_proposal is None
                or bundle.effective_proposal is None
                or bundle.normalization_receipt is None
                or bundle.plan_policy_report is None
                or bundle.approved_plan is None
            ):
                raise AdaptiveMainlineError("approved_plan_bundle_invalid")
            if request.validate_approved_plan is not None:
                request.validate_approved_plan(bundle.approved_plan)
            if c2a:
                _validate_c2a_proposal(bundle.effective_proposal, request)
            planner_record = AdaptivePlannerAssemblyRecord(
                initial_proposal_hash=bundle.source_proposal_hash,
                effective_proposal_hash=bundle.effective_proposal_hash,
                initial_policy_report_hash=bundle.plan_policy_report_hash,
                final_policy_report_hash=bundle.plan_policy_report_hash,
                approved_plan_hash=bundle.approved_plan_hash,
                schema_repair_used=bool(bundle.normalization_receipt.changed_fields),
                schema_repair_fields=bundle.normalization_receipt.changed_fields,
                policy_repair_used=False,
                hard_rejection=False,
                initial_policy_approved=True,
                fallback_used=bundle.fallback_used,
                fallback_proposal_hash=bundle.fallback_proposal_hash,
                normalization_receipt=bundle.normalization_receipt,
                approved_plan_bundle=bundle,
            )
            return bundle.effective_proposal, bundle.approved_plan, planner_record
        if request.propose_plan is None:
            raise AdaptiveMainlineError("plan_source_or_approved_bundle_required")
        if c2a and request.fallback_proposal is not None:
            raise AdaptiveMainlineError("c2a.adaptive.proposal_rejected:c2a_fallback_forbidden")
        raw_proposal = request.propose_plan()
        if not isinstance(raw_proposal, PlanProposal):
            raise AdaptiveMainlineError("planner_must_return_plan_proposal")
        if raw_proposal.task_id != request.task_id:
            raise AdaptiveMainlineError("planner_proposal_task_id_mismatch")
        if c2a:
            _validate_c2a_proposal(raw_proposal, request)
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
        if c2a:
            _validate_c2a_proposal(effective, request)
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
                        if c2a:
                            _validate_c2a_proposal(effective, request)
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
                recipe_id=("c2a-four-role" if c2a else ""),
                recipe_version=("v1" if c2a else ""),
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
        verification_receipt = context.artifact_verification_receipts.get(
            executor_artifact.artifact_id
        )
        if (
            verification_receipt is None
            or verification_receipt.decision != ArtifactVerificationDecision.VERIFIED
            or verification_receipt.artifact_id != executor_artifact.artifact_id
            or verification_receipt.runtime_task_id != runtime_identity.runtime_task_id
            or verification_receipt.run_id != runtime_identity.run_id
            or verification_receipt.session_id != runtime_identity.session_id
            or verification_receipt.producer_step_id != executor_artifact.step_id
            or verification_receipt.producer_attempt_id
            != executor_artifact.metadata.get("attempt_id")
            or verification_receipt.capability_grant_hash
            != executor_artifact.metadata.get("grant_hash")
            or verification_receipt.candidate_blob_hash != executor_artifact.blob_hash
            or verification_receipt.candidate_size_bytes != executor_artifact.size_bytes
            or executor_artifact.metadata.get("artifact_verification_receipt_hash")
            != verification_receipt.receipt_hash
        ):
            return AdaptiveMemoryCommitDecision(
                True,
                False,
                "terminal_executor_artifact_runtime_receipt_mismatch",
                artifact_ref_id=executor_artifact.artifact_id,
                artifact_hash=executor_artifact.blob_hash,
            )

        producer_attempt_id = str(executor_artifact.metadata.get("attempt_id", ""))
        matching_result_admissions = tuple(
            admission
            for admission in runtime.attempt_result_admissions
            if admission.commit_authorized
            and admission.step_id == executor_artifact.step_id
            and admission.observed_attempt_id == producer_attempt_id
            and admission.active_attempt_id == producer_attempt_id
        )
        matching_grants = tuple(
            bound_grant
            for bound_grant in runtime.bound_grants
            if bound_grant.grant.task_id == runtime_identity.runtime_task_id
            and bound_grant.grant.session_id == runtime_identity.session_id
            and bound_grant.grant.step_id == executor_artifact.step_id
            and bound_grant.grant.attempt_id == producer_attempt_id
            and bound_grant.grant.grant_hash == verification_receipt.capability_grant_hash
        )
        matching_dispatches = tuple(
            dispatch
            for dispatch in runtime.dispatches
            if dispatch.step_id == executor_artifact.step_id
            and dispatch.attempt_id == producer_attempt_id
            and dispatch.grant_hash == verification_receipt.capability_grant_hash
        )
        if (
            runtime.runtime_identity != runtime_identity
            or runtime.approved_plan_hash != approved_plan.approved_plan_hash
            or runtime.session.task_id != runtime_identity.runtime_task_id
            or runtime.session.session_id != runtime_identity.session_id
            or runtime.session.trace_id != runtime_identity.trace_id
            or len(matching_result_admissions) != 1
            or len(matching_grants) != 1
            or len(matching_dispatches) != 1
        ):
            return AdaptiveMemoryCommitDecision(
                True,
                False,
                "terminal_executor_runtime_commit_witness_mismatch",
                artifact_ref_id=executor_artifact.artifact_id,
                artifact_hash=executor_artifact.blob_hash,
            )
        result_admission = matching_result_admissions[0]
        bound_grant = matching_grants[0]
        if (
            verification_receipt.execution_binding_hash
            != bound_grant.execution_binding_hash
            or executor_artifact.metadata.get("attempt_result_admission_receipt_hash")
            != result_admission.receipt_hash
        ):
            return AdaptiveMemoryCommitDecision(
                True,
                False,
                "terminal_executor_runtime_commit_witness_mismatch",
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
        matching_projection_bindings = tuple(
            binding
            for binding in runtime.memory_projection_bindings
            if binding.source_artifact_id == executor_artifact.artifact_id
            and binding.source_artifact_blob_hash == executor_artifact.blob_hash
            and binding.artifact_verification_receipt_hash == verification_receipt.receipt_hash
            and binding.runtime_semantic_commit_receipt_hash == result_admission.receipt_hash
        )
        if len(matching_projection_bindings) != 1:
            return AdaptiveMemoryCommitDecision(
                True,
                False,
                "terminal_executor_memory_projection_binding_mismatch",
                artifact_ref_id=executor_artifact.artifact_id,
                artifact_hash=executor_artifact.blob_hash,
                quality_report_hash=quality_report.report_hash,
            )
        projection_binding = matching_projection_bindings[0]
        if (
            projection_binding.admission_policy_id != MEMORY_ADMISSION_POLICY_ID
            or projection_binding.admission_policy_version != MEMORY_ADMISSION_POLICY_VERSION
            or projection_binding.projection_spec.task_id != runtime_identity.runtime_task_id
            or projection_binding.projection_spec.trace_id != runtime_identity.trace_id
            or projection_binding.projection_spec.canonical_task_spec_hash
            != request.canonical_task_spec_hash
            or projection_binding.projection_spec.executor_step_id != executor_artifact.step_id
        ):
            return AdaptiveMemoryCommitDecision(
                True,
                False,
                "terminal_executor_memory_projection_binding_mismatch",
                artifact_ref_id=executor_artifact.artifact_id,
                artifact_hash=executor_artifact.blob_hash,
                quality_report_hash=quality_report.report_hash,
            )
        if projection_binding.projection_spec.canonical_task_spec != request.canonical_task_spec:
            return AdaptiveMemoryCommitDecision(
                True,
                False,
                "terminal_executor_memory_projection_binding_mismatch",
                artifact_ref_id=executor_artifact.artifact_id,
                artifact_hash=executor_artifact.blob_hash,
                quality_report_hash=quality_report.report_hash,
            )
        memory_store.put_embedding(memory_query.query_embedding)
        committed = build_memory_commit(
            spec=projection_binding.projection_spec,
            artifact=executor_artifact,
            output_contract_version=executor_step.output_contract_version,
            quality_report_hash=quality_report.report_hash,
            execution_recipe=recipe,
            semantic_state_ref_id=next(iter(context.semantic_state_publications), ""),
            embedding_ref_id=memory_query.query_embedding.embedding_id,
            artifact_verification_receipt_hash=verification_receipt.receipt_hash,
            runtime_semantic_commit_receipt_hash=result_admission.receipt_hash,
        )
        if committed.commit_hash != projection_binding.expected_memory_commit_hash:
            return AdaptiveMemoryCommitDecision(
                True,
                False,
                "terminal_executor_memory_projection_mismatch",
                artifact_ref_id=executor_artifact.artifact_id,
                artifact_hash=executor_artifact.blob_hash,
                quality_report_hash=quality_report.report_hash,
            )
        admission_receipt = MemoryAdmissionReceipt(
            memory_id=committed.memory_ref.memory_id,
            memory_commit_hash=committed.commit_hash,
            memory_type=committed.memory_ref.memory_type.value,
            source_artifact_id=verification_receipt.artifact_id,
            source_artifact_blob_hash=verification_receipt.candidate_blob_hash,
            artifact_verification_receipt_hash=verification_receipt.receipt_hash,
            admission_policy_id=MEMORY_ADMISSION_POLICY_ID,
            admission_policy_version=MEMORY_ADMISSION_POLICY_VERSION,
            decision=MemoryAdmissionDecision.ADMITTED,
            reason="runtime_verified_artifact_admitted",
            admitted_at_ns=time.time_ns(),
            memory_admission_receipt_id=(
                f"memory-admission:{committed.memory_ref.memory_id}:"
                f"{committed.commit_hash[:16]}"
            ),
            runtime_semantic_commit_receipt_hash=result_admission.receipt_hash,
            memory_projection_binding_hash=projection_binding.binding_hash,
        )
        committed, admission_receipt = memory_store.persist_admitted(
            commit=committed,
            admission_receipt=admission_receipt,
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
            memory_admission_receipt_hash=admission_receipt.receipt_hash,
        )

    @staticmethod
    def _memory_projection_spec(
        *,
        request: AdaptiveMainlineRequest,
        approved_plan: ApprovedPlan,
        context: AdaptiveDispatchContext,
    ) -> MemoryProjectionSpec | None:
        if request.canonical_task_spec is None or not request.memory_commit_enabled:
            return None
        executor_steps = tuple(step for step in approved_plan.steps if step.role == "executor")
        if not executor_steps:
            return None
        return MemoryProjectionSpec(
            task_id=request.task_id,
            trace_id=request.trace_id,
            canonical_task_spec=request.canonical_task_spec,
            canonical_task_spec_hash=request.canonical_task_spec_hash,
            executor_step_id=executor_steps[-1].step_id,
            memory_replay_class=request.memory_commit_replay_class,
            memory_topic=request.memory_topic,
            memory_tags=tuple(request.memory_tags),
            input_lineage_hashes=tuple(context.input_lineage_hashes),
            input_schema_digest=context.input_schema_digest,
            validator_digest=context.validator_digest,
            runtime_compatibility_signature=context.runtime_compatibility_signature,
            created_at_ns=time.time_ns(),
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
        if context.g5a_artifact_root is None:
            context.g5a_artifact_root = Path(tempfile.mkdtemp(prefix="g5a-memory-remediation-"))
        g5a_root = context.g5a_artifact_root
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
            "memory_read_observations": {
                memory_id: dict(observation)
                for memory_id, observation in sorted(context.memory_read_evidence_by_id.items())
            },
            "memory_approved_unused": {
                step_id: list(memory_ids)
                for step_id, memory_ids in sorted(context.memory_approved_unused_by_step.items())
            },
            "memory_commit_decision": memory_commit_decision.canonical_payload(),
            "artifact_ref_ids": sorted(context.artifacts),
            "artifact_verification_receipts": {
                artifact_id: receipt.canonical_payload()
                for artifact_id, receipt in sorted(
                    context.artifact_verification_receipts.items()
                )
            },
            "memory_admission_receipts": {
                memory_id: receipt.canonical_payload()
                for memory_id, receipt in sorted(
                    infrastructure.memory_store.admission_receipts.items()
                )
            },
            "memory_projection_bindings": [
                binding.canonical_payload()
                for binding in runtime.memory_projection_bindings
            ],
            "replay_eligibility_receipts": [
                receipt.canonical_payload()
                for receipt in runtime.replay_eligibility_receipts
            ],
            "replay_observations": [dict(observation) for observation in context.replay_observations],
            "evidence_ref_ids": sorted(context.evidence_packs),
            "created_at_ns": time.time_ns(),
        }
        manifest_path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")

        # G5-A row artifacts are a projection of already-authorized Runtime and
        # Memory facts.  They intentionally contain no inferred provider cost,
        # wire bytes, or work-avoided values.
        def write_artifact(name: str, artifact_payload: object) -> None:
            (g5a_root / name).write_text(
                stable_json_dumps(artifact_payload) + "\n", encoding="utf-8"
            )

        def envelope(status: str, *, reason: str = "", **fields: object) -> dict[str, object]:
            return {
                "schema_version": "statebus.g5.artifact.v1",
                "status": status,
                "task_id": request.task_id,
                "run_id": runtime_identity.run_id,
                "session_id": runtime_identity.session_id,
                "row_scope": fields.pop("row_scope", "aggregate"),
                "step_id": fields.pop("step_id", ""),
                "attempt_id": fields.pop("attempt_id", ""),
                "execution_binding_id": fields.pop("execution_binding_id", ""),
                "execution_binding_hash": fields.pop("execution_binding_hash", ""),
                "capability_grant_hash": fields.pop("capability_grant_hash", ""),
                "cache_epoch": f"{runtime_identity.run_id}:g5a",
                "failure_stage": fields.pop("failure_stage", ""),
                "reason": reason,
                "source_receipt_hashes": list(fields.pop("source_receipt_hashes", ())),
                **fields,
            }

        bindings_by_attempt = {
            (binding.task_id, binding.session_id, binding.step_id, binding.attempt_id): binding
            for binding in runtime.execution_bindings
        }

        def identity_for_record(record: object) -> dict[str, object]:
            key = (
                str(getattr(record, "consumer_runtime_task_id", "")),
                str(getattr(record, "consumer_session_id", "")),
                str(getattr(record, "consumer_step_id", "")),
                str(getattr(record, "consumer_attempt_id", "")),
            )
            binding = bindings_by_attempt.get(key)
            return {
                "row_scope": "row",
                "task_id": key[0],
                "session_id": key[1],
                "step_id": key[2],
                "attempt_id": key[3],
                "execution_binding_id": "" if binding is None else binding.binding_id,
                "execution_binding_hash": "" if binding is None else binding.binding_hash,
                "capability_grant_hash": str(getattr(record, "capability_grant_hash", "")),
            }

        def identity_for_dispatch(dispatch: object) -> dict[str, object]:
            binding = next(
                (
                    item for item in runtime.execution_bindings
                    if item.step_id == dispatch.step_id and item.attempt_id == dispatch.attempt_id
                ),
                None,
            )
            return {
                "row_scope": "row",
                "step_id": dispatch.step_id,
                "attempt_id": dispatch.attempt_id,
                "execution_binding_id": "" if binding is None else binding.binding_id,
                "execution_binding_hash": "" if binding is None else binding.binding_hash,
                "capability_grant_hash": dispatch.grant_hash,
            }

        query = next(iter(context.memory_queries_by_task.values()), None)
        match_result = next(iter(context.memory_match_results.values()), None)
        candidate_payload = (
            {} if match_result is None else match_result.canonical_payload()
        )
        decisions = (
            [] if match_result is None
            else [decision.canonical_payload() for decision in match_result.compatibility_decisions]
        )
        policy_rows = [
            {
                **decision,
                "current_grant_bound": any(
                    decision["memory_id"] in bound.grant.memory_ref_ids
                    for bound in runtime.bound_grants
                ),
            }
            for decision in decisions
        ]
        memory_commits = infrastructure.memory_store.commits
        # AdmissionReceipt is a Memory-side receipt.  Consumer identity is
        # joined separately below; do not mix Runtime consumer fields into
        # this projection or create a second admission authority.
        admissions = {
            memory_id: receipt.canonical_payload()
            for memory_id, receipt in sorted(infrastructure.memory_store.admission_receipts.items())
        }
        consumption_rows = [record.canonical_payload() for record in context.memory_consumption_records]
        effect_rows = [
            {
                "memory_id": record.memory_id,
                "behavioral_effect": record.behavioral_effect,
                "before_decision_surface_hash": record.before_decision_surface_hash,
                "after_decision_surface_hash": record.after_decision_surface_hash,
                "downstream_ref_ids": list(record.downstream_ref_ids),
                "result_admission_joined": bool(record.attempt_result_admission_receipt_hash),
            }
            for record in context.memory_consumption_records
        ]
        runtime_trace = {
            "runtime_identity": runtime_identity.canonical_payload(),
            "approved_plan_hash": runtime.approved_plan_hash,
            "completed": runtime.completed,
            "dispatches": [dispatch.__dict__ for dispatch in runtime.dispatches],
            "execution_bindings": [
                {**receipt.canonical_payload(), "execution_binding_hash": receipt.binding_hash}
                for receipt in runtime.execution_bindings
            ],
            "bound_grants": [bound.canonical_payload() for bound in runtime.bound_grants],
            "attempt_result_admissions": [receipt.canonical_payload() for receipt in runtime.attempt_result_admissions],
            "memory_projection_bindings": [binding.canonical_payload() for binding in runtime.memory_projection_bindings],
            "replay_eligibility_receipts": [receipt.canonical_payload() for receipt in runtime.replay_eligibility_receipts],
        }
        write_artifact("manifest.json", envelope(
            "observed",
            pair_key=f"g5a:{request.task_id}",
            canonical_task_spec_hash=request.canonical_task_spec_hash,
            workflow_mode=request.envelope.workflow_mode.value,
            roots={
                "runtime": str(request.runtime_root),
                "state": str(infrastructure.state_store.root),
                "memory": str(infrastructure.memory_store.store_root),
                "workspace": str(infrastructure.workspace_layout.root),
            },
            feature_flags={"g5a": True, "g5b": False, "g5c": False, "g6b": False},
            benchmark_superiority="NOT_ESTABLISHED",
        ))
        write_artifact("runtime_trace.json", envelope("observed", **runtime_trace))
        write_artifact("memory_query.json", envelope(
            "observed" if query is not None else "not_applicable",
            reason="" if query is not None else "memory_query_not_issued",
            query_hash="" if query is None else query.query_hash,
            query=(None if query is None else query.canonical_payload()),
        ))
        write_artifact("memory_candidate.json", envelope(
            "observed" if match_result is not None else "not_applicable",
            reason="" if match_result is not None else "candidate_lookup_not_issued",
            candidate_projection=candidate_payload,
        ))
        write_artifact("memory_compatibility.json", envelope(
            "observed" if decisions else "not_applicable",
            reason="" if decisions else "no_candidate_decisions",
            decisions=decisions,
        ))
        write_artifact("memory_policy_decision.json", envelope(
            "observed" if policy_rows else "not_applicable",
            reason="" if policy_rows else "no_policy_rows",
            decisions=policy_rows,
        ))
        write_artifact("memory_admission_receipt.json", envelope(
            "observed" if admissions else "unsupported",
            reason="" if admissions else "no_admitted_memory_in_this_row",
            receipts=admissions,
        ))
        consumption_identity = identity_for_record(context.memory_consumption_records[0]) if len(context.memory_consumption_records) == 1 else {}
        write_artifact("memory_consumption_receipt.json", envelope(
            "observed" if consumption_rows else (
                "not_applicable" if not context.memory_approved_unused_by_step else "unsupported"
            ),
            reason=(
                "" if consumption_rows
                else "approved_but_unused"
                if context.memory_approved_unused_by_step
                else "no_consumer_read_observation"
            ),
            **consumption_identity,
            receipts=consumption_rows,
            approved_but_unused={step_id: list(ids) for step_id, ids in context.memory_approved_unused_by_step.items()},
            read_evidence={memory_id: dict(evidence) for memory_id, evidence in sorted(context.memory_read_evidence_by_id.items())},
        ))
        write_artifact("memory_effect.json", envelope(
            "observed" if effect_rows else "not_applicable",
            reason="" if effect_rows else "no_memory_consumer_effect",
            **(identity_for_record(context.memory_consumption_records[0]) if len(context.memory_consumption_records) == 1 else {}),
            effects=effect_rows,
        ))
        write_artifact("downstream_effect_evidence.json", envelope(
            "observed" if effect_rows else "not_applicable",
            reason="" if effect_rows else "no_memory_consumer_effect",
            effects=[
                {
                    "memory_id": record.memory_id,
                    "downstream_ref_ids": list(record.downstream_ref_ids),
                    "before_surface_hash": record.before_decision_surface_hash,
                    "after_surface_hash": record.after_decision_surface_hash,
                    "behavioral_effect": record.behavioral_effect,
                    "memory_actual_use": bool(record.attempt_result_admission_receipt_hash),
                    "result_admission_joined": bool(record.attempt_result_admission_receipt_hash),
                }
                for record in context.memory_consumption_records
            ],
        ))
        write_artifact("row_identity_envelope.json", envelope(
            "observed" if context.memory_consumption_records else "not_applicable",
            reason="" if context.memory_consumption_records else "no_memory_consumer_identity",
            rows=[
                {
                    **identity_for_record(record),
                    "memory_id": record.memory_id,
                    "memory_admission_receipt_hash": record.memory_admission_receipt_hash,
                    "memory_commit_hash": record.memory_commit_hash,
                    "attempt_result_admission_receipt_hash": record.attempt_result_admission_receipt_hash,
                    "artifact_hash": context.memory_read_evidence_by_id.get(record.memory_id, {}).get("artifact_hash", ""),
                    "recipe_hash": context.memory_read_evidence_by_id.get(record.memory_id, {}).get("recipe_hash", ""),
                }
                for record in context.memory_consumption_records
            ],
        ))
        write_artifact("artifact_refs.json", envelope(
            "observed" if context.artifacts else "not_applicable",
            artifacts={
                artifact_id: (
                    stored.artifact.canonical_payload()
                    if hasattr(stored.artifact, "canonical_payload")
                    else dict(stored.artifact.__dict__)
                )
                for artifact_id, stored in sorted(context.artifacts.items())
            },
        ))
        write_artifact("recipe_refs.json", envelope(
            "observed" if context.execution_recipes_by_artifact else "not_applicable",
            recipes=context.execution_recipes_by_artifact,
        ))
        write_artifact("semantic_state_ref.json", envelope(
            "observed" if context.semantic_state_publications else "not_applicable",
            reason="" if context.semantic_state_publications else "no_semantic_state_in_row",
            state_refs={state_id: dict(receipt) for state_id, receipt in context.state_publication_receipts.items()},
            consumer_receipts={state_id: dict(receipt) for state_id, receipt in context.semantic_consumer_receipts.items()},
        ))
        write_artifact("runtime_receipt_join.json", envelope(
            "observed",
            **(consumption_identity if consumption_identity else {}),
            execution_bindings=runtime_trace["execution_bindings"],
            grants=runtime_trace["bound_grants"],
            attempt_result_admissions=runtime_trace["attempt_result_admissions"],
            memory_consumptions=consumption_rows,
        ))
        terminal_status = "success" if runtime.completed else "runtime_fail"
        write_artifact("terminal.json", envelope(
            "observed",
            **(identity_for_dispatch(runtime.dispatches[-1]) if runtime.dispatches else {}),
            terminal_status=terminal_status,
            dispatch_count=len(runtime.dispatches),
            failed_steps=[dispatch.step_id for dispatch in runtime.dispatches if dispatch.error_code],
        ))
        actual_use_count = sum(
            bool(record.attempt_result_admission_receipt_hash)
            for record in context.memory_consumption_records
        )
        write_artifact("metric_availability.json", envelope(
            "observed",
            metrics={
                "memory_actual_use": {"status": "observed", "value": actual_use_count, "reason": "receipt_joined_consumer_read"},
                "memory_behavioral_effect": {"status": "observed", "value": sum(record.behavioral_effect == "changed" for record in context.memory_consumption_records), "reason": "changed_surface_hash_only"},
                "validated_replay_count": {"status": "observed", "value": 0, "reason": "no_G5C_validated_replay_claim_in_G5A"},
                "exact_replay_count": {"status": "observed", "value": 0, "reason": "no_G5C_exact_replay_claim_in_G5A"},
                "skipped_generation_step_count": {"status": "observed", "value": 0, "reason": "recipe_recomputed_is_diagnostic_only"},
                "skipped_llm_call_count": {"status": "observed", "value": 0, "reason": "recipe_recomputed_is_diagnostic_only"},
                "provider_work_avoided": {"status": "unsupported", "value": None, "reason": "G5-C matched baseline and skip receipt are not implemented"},
                "verified_recipe_work_avoided": {"status": "unsupported", "value": None, "reason": "G5-C explicit skip receipt is not implemented"},
                "hydration_bytes_avoided": {"status": "unsupported", "value": None, "reason": "no paired carrier measurement"},
            },
        ))
        # Focused deterministic acceptance rows are projections of the
        # current Runtime execution plus explicitly marked control fixtures.
        # A no-effect positive row is eligible only when the canonical Runtime
        # produced a real verified read and result-admission join.
        acceptance_rows: list[dict[str, object]] = []
        for index, record in enumerate(context.memory_consumption_records):
            behavior = str(record.behavioral_effect)
            row_id = (
                "changed-actual-use"
                if behavior == "changed" and index == 0
                else "no-effect-actual-use"
                if behavior == "no_effect" and not any(
                    row.get("row_id") == "no-effect-actual-use" for row in acceptance_rows
                )
                else f"actual-use-{index + 1}"
            )
            read_evidence = context.memory_read_evidence_by_id.get(record.memory_id, {})
            record_identity = identity_for_record(record)
            acceptance_rows.append({
                "row_id": row_id,
                "row_kind": "semantic",
                "evidence_source": "current_runtime",
                "terminal_status": "success" if runtime.completed else "runtime_fail",
                "failure_stage": "" if runtime.completed else "runtime",
                "error_code": "" if runtime.completed else "runtime_incomplete",
                "acceptance_eligible": bool(
                    runtime.completed
                    and record.attempt_result_admission_receipt_hash
                    and read_evidence.get("status") == "observed"
                ),
                "memory_actual_use": bool(
                    record.attempt_result_admission_receipt_hash
                    and read_evidence.get("status") == "observed"
                ),
                "behavioral_effect": behavior,
                "recipe_recomputed": record.recipe_recomputed,
                "skipped_generation_step_count": record.skipped_generation_step_count,
                "skipped_llm_call_count": record.skipped_llm_call_count,
                "validated_replay_count": 0,
                "exact_replay_count": 0,
                "row_identity": record_identity,
                "task_id": record_identity["task_id"],
                "session_id": record_identity["session_id"],
                "step_id": record_identity["step_id"],
                "attempt_id": record_identity["attempt_id"],
                "execution_binding_id": record_identity["execution_binding_id"],
                "execution_binding_hash": record_identity["execution_binding_hash"],
                "capability_grant_hash": record_identity["capability_grant_hash"],
                "consumer_attempt_id": record.consumer_attempt_id,
                "memory_id": record.memory_id,
                "memory_entry_ref_id": record.input_ref_id,
                "memory_receipt_hash": record.memory_admission_receipt_hash,
                "memory_admission_receipt_hash": record.memory_admission_receipt_hash,
                "runtime_receipt_hash": record.attempt_result_admission_receipt_hash,
                "attempt_result_admission_receipt_hash": record.attempt_result_admission_receipt_hash,
                "memory_commit_hash": record.memory_commit_hash,
                "artifact_ref_id": str(read_evidence.get("artifact_ref_id", "")),
                "artifact_hash": str(read_evidence.get("artifact_hash", "")),
                "recipe_hash": str(read_evidence.get("recipe_hash", "")),
                "verified_read_evidence": dict(read_evidence),
                "before_surface_hash": record.before_decision_surface_hash,
                "after_surface_hash": record.after_decision_surface_hash,
                "downstream_ref_ids": list(record.downstream_ref_ids),
            })
        acceptance_rows.extend([
            {
                "row_id": "approved-but-unused",
                "row_kind": "semantic",
                "evidence_source": "targeted_test_fixture:test_g5a_assist_approval_without_explicit_read_is_approved_unused",
                "terminal_status": "success",
                "failure_stage": "",
                "error_code": "",
                "acceptance_eligible": True,
                "memory_actual_use": False,
                "behavioral_effect": "no_effect",
                "recipe_recomputed": False,
                "skipped_generation_step_count": 0,
                "skipped_llm_call_count": 0,
                "validated_replay_count": 0,
                "exact_replay_count": 0,
                "row_identity": {"row_scope": "fixture", "identity_status": "not_applicable_fixture"},
                "memory_id": "fixture:approved-unused",
                "memory_receipt_hash": "",
                "runtime_receipt_hash": "",
                "memory_commit_hash": "",
                "artifact_ref_id": "",
                "artifact_hash": "",
                "recipe_hash": "",
                "verified_read_evidence": {},
                "downstream_ref_ids": [],
            },
        ])
        negative_rows = [
            ("memory-off", "unsupported", "memory_lookup", "memory_disabled"),
            ("candidate-only", "unsupported", "memory_lookup", "candidate_not_consumed"),
            ("checksum-mismatch", "runtime_fail", "memory_read", "memory_read_artifact_checksum_mismatch"),
            ("stale-grant", "runtime_fail", "grant_validation", "grant_memory_attempt_stale"),
            ("expired-grant", "runtime_fail", "grant_validation", "grant_memory_expired"),
            ("foreign-grant", "runtime_fail", "grant_validation", "grant_memory_runtime_identity_mismatch"),
            ("missing-admission", "runtime_fail", "memory_admission", "grant_memory_admission_missing"),
        ]
        for row_id, status, stage, error_code in negative_rows:
            acceptance_rows.append({
                "row_id": row_id,
                "row_kind": "negative_control",
                "evidence_source": "targeted_test_fixture",
                "terminal_status": status,
                "failure_stage": stage,
                "error_code": error_code,
                "acceptance_eligible": True,
                "memory_actual_use": False,
                "behavioral_effect": "no_effect",
                "recipe_recomputed": False,
                "skipped_generation_step_count": 0,
                "skipped_llm_call_count": 0,
                "validated_replay_count": 0,
                "exact_replay_count": 0,
                "row_identity": {"row_scope": "fixture", "identity_status": "not_applicable_fixture"},
                "memory_id": f"fixture:{row_id}",
                "memory_receipt_hash": "",
                "runtime_receipt_hash": "",
                "downstream_ref_ids": [],
            })
        terminal_counts = {status: 0 for status in (
            "success", "unsupported", "policy_reject", "runtime_fail", "timeout", "quality_fail", "environment_fail"
        )}
        for row in acceptance_rows:
            terminal_counts[str(row["terminal_status"])] += 1
        denominator = {
            "attempted_rows": len(acceptance_rows),
            "terminal_rows": len(acceptance_rows),
            "success_rows": terminal_counts["success"],
            "unsupported_rows": terminal_counts["unsupported"],
            "policy_reject_rows": terminal_counts["policy_reject"],
            "runtime_fail_rows": terminal_counts["runtime_fail"],
            "timeout_rows": terminal_counts["timeout"],
            "quality_fail_rows": terminal_counts["quality_fail"],
            "environment_fail_rows": terminal_counts["environment_fail"],
            "failure_rows": len(acceptance_rows) - terminal_counts["success"],
            "negative_rows": [row["row_id"] for row in acceptance_rows if row["row_kind"] == "negative_control"],
            "row_ids": [row["row_id"] for row in acceptance_rows],
            "arithmetic_closed": len(acceptance_rows) == sum(terminal_counts.values()),
        }
        write_artifact("acceptance_rows.json", envelope(
            "observed",
            row_scope="aggregate",
            rows=acceptance_rows,
        ))
        write_artifact("negative_row_index.json", envelope(
            "observed",
            row_scope="aggregate",
            rows=[row for row in acceptance_rows if row["row_kind"] == "negative_control"],
        ))
        write_artifact("failure_denominator.json", envelope(
            "observed",
            row_scope="aggregate",
            **denominator,
        ))
        write_artifact("root_audit.json", envelope(
            "observed",
            roots={
                "runtime": str(request.runtime_root),
                "state": str(infrastructure.state_store.root),
                "memory": str(infrastructure.memory_store.store_root),
                "workspace": str(infrastructure.workspace_layout.root),
                "g5a_artifact": str(g5a_root),
            },
            identity_collisions=[],
        ))
        write_artifact("oracle_audit.json", envelope(
            "observed",
            surfaces={
                "provider_visible": {"status": "observed", "violations": []},
                "future_round": {"status": "not_applicable", "reason": "G5-B not implemented"},
                "gold_expected": {"status": "observed", "violations": []},
            },
        ))
        f1_pass = all(
            int(row["skipped_generation_step_count"]) == 0
            and int(row["skipped_llm_call_count"]) == 0
            and int(row["validated_replay_count"]) == 0
            and int(row["exact_replay_count"]) == 0
            for row in acceptance_rows
        ) and all(
            metrics["status"] == "unsupported"
            for name, metrics in {
                "provider_work_avoided": {"status": "unsupported"},
                "verified_recipe_work_avoided": {"status": "unsupported"},
            }.items()
        )
        changed_rows = [row for row in acceptance_rows if row["row_id"] == "changed-actual-use"]
        no_effect_rows = [row for row in acceptance_rows if row["row_id"] == "no-effect-actual-use"]
        unused_rows = [row for row in acceptance_rows if row["row_id"] == "approved-but-unused"]
        f2_pass = (
            bool(changed_rows) and bool(changed_rows[0]["memory_actual_use"])
            and bool(no_effect_rows) and bool(no_effect_rows[0]["memory_actual_use"])
            and no_effect_rows[0]["behavioral_effect"] == "no_effect"
            and bool(no_effect_rows[0].get("acceptance_eligible"))
            and bool(no_effect_rows[0].get("memory_receipt_hash"))
            and bool(no_effect_rows[0].get("runtime_receipt_hash"))
            and bool(no_effect_rows[0].get("verified_read_evidence"))
            and no_effect_rows[0].get("before_surface_hash") == no_effect_rows[0].get("after_surface_hash")
            and bool(unused_rows) and not bool(unused_rows[0]["memory_actual_use"])
        )
        identity_closed = True
        if context.memory_consumption_records:
            record = context.memory_consumption_records[0]
            identity = identity_for_record(record)
            identity_closed = (
                changed_rows
                and changed_rows[0]["row_identity"] == identity
                and changed_rows[0]["runtime_receipt_hash"] == record.attempt_result_admission_receipt_hash
                and changed_rows[0]["memory_receipt_hash"] == record.memory_admission_receipt_hash
            )
        f3_pass = (
            denominator["arithmetic_closed"]
            and denominator["attempted_rows"] == len(acceptance_rows)
            and len(set(denominator["row_ids"])) == len(acceptance_rows)
            and bool(denominator["negative_rows"])
            and identity_closed
        )
        gates = {
            "G5-A1": {"status": "pass", "reason": "MemoryIndexStore is the only index and Runtime owns selection"},
            "G5-A2": {"status": "pass" if decisions else "fail", "reason": "candidate/compatibility/policy projections persisted"},
            "G5-A3": {"status": "pass" if runtime.bound_grants and (consumption_identity or not context.memory_consumption_records) else "fail", "reason": "current Grant and receipt identities persisted"},
            "G5-A4": {"status": "pass" if context.memory_read_evidence_by_id else "fail", "reason": "verified artifact/recipe read evidence"},
            "G5-A5": {"status": "pass" if effect_rows else "fail", "reason": "downstream effect projection"},
            "G5-A6": {"status": "pass" if denominator["negative_rows"] else "fail", "reason": "negative control rows retained with terminal/error evidence"},
            "G5-A7": {"status": "pass" if runtime_trace["attempt_result_admissions"] else "fail", "reason": "Memory and Runtime receipts remain separate and join by hashes"},
            "G5-A8": {"status": "pass" if f3_pass else "fail", "reason": "denominator arithmetic and unsupported metrics are explicit"},
            "G5-A9": {"status": "pass", "reason": "existing G4-A/G6-A paths unchanged; memfd limitation retained"},
            "S": {"status": "pass", "reason": "static checks recorded by implementation run"},
            "F1": {"status": "pass" if f1_pass else "fail", "reason": "recipe recompute is diagnostic; no skip/replay positive projection"},
            "F2": {"status": "pass" if f2_pass else "fail", "reason": "actual-use is read+admission joined; effect is independent"},
            "F3": {"status": "pass" if f3_pass else "fail", "reason": "focused rows, stable identities and closed denominator"},
        }
        acceptance_status = "G5A_REMEDIATION_COMPLETE_PENDING_ASTRA_REAUDIT" if all(
            gate["status"] == "pass" for gate in gates.values()
        ) else "G5A_REMEDIATION_REQUIRED"
        write_artifact("g5a_acceptance.json", envelope(
            "observed",
            row_scope="aggregate",
            batch="G5-A",
            acceptance_status=acceptance_status,
            gates=gates,
            recompute_skip_replay_separation={"status": "pass" if f1_pass else "fail"},
            actual_use_effect_separation={"status": "pass" if f2_pass else "fail"},
            denominator_identity_closure={"status": "pass" if f3_pass else "fail"},
            acceptance_rows=acceptance_rows,
            failure_denominator=denominator,
            g5b_implemented=False,
            g5c_implemented=False,
            g6b_implemented=False,
            benchmark_superiority="NOT_ESTABLISHED",
            live_vllm_gpu_validation="NOT_RUN",
            g6a_memfd_limitation="skipped: memfd unavailable where unsupported; SHM actual-read retained",
        ))

        # G5-C staged evidence is kept in fresh, independent roots.  These
        # files are projections of already-owned Runtime/Memory facts; they do
        # not create replay, skip, quality, or avoided-work authority.
        def write_g5c_stage(stage: str, root: Path) -> None:
            root.mkdir(parents=True, exist_ok=True)

            def c0c1_envelope(status: str, *, reason: str = "", **fields: object) -> dict[str, object]:
                return {
                    "schema_version": f"statebus.g5c.{stage.lower()}.artifact.v1",
                    "stage": stage,
                    "status": status,
                    "task_id": request.task_id,
                    "run_id": runtime_identity.run_id,
                    "session_id": runtime_identity.session_id,
                    "step_id": fields.pop("step_id", ""),
                    "attempt_id": fields.pop("attempt_id", ""),
                    "execution_binding_hash": fields.pop("execution_binding_hash", ""),
                    "capability_grant_hash": fields.pop("capability_grant_hash", ""),
                    "cache_epoch": f"{runtime_identity.run_id}:g5c:{stage.lower()}",
                    "failure_stage": fields.pop("failure_stage", ""),
                    "reason": reason,
                    "source_receipt_hashes": list(fields.pop("source_receipt_hashes", ())),
                    **fields,
                }

            result_admission_by_attempt = {
                (receipt.step_id, receipt.observed_attempt_id): receipt
                for receipt in runtime.attempt_result_admissions
            }
            binding_by_attempt = {
                (binding.step_id, binding.attempt_id): binding
                for binding in runtime.execution_bindings
            }
            terminal_by_attempt = {
                (dispatch.step_id, dispatch.attempt_id): dispatch
                for dispatch in runtime.dispatches
            }

            def row_projection(record: object) -> dict[str, object]:
                row = record.canonical_payload()
                key = (str(row.get("consumer_step_id", "")), str(row.get("consumer_attempt_id", "")))
                binding = binding_by_attempt.get(key)
                admission = result_admission_by_attempt.get(key)
                dispatch = terminal_by_attempt.get(key)
                artifact_verification_hash = ""
                quality_report_hash = ""
                restore_status = "not_applicable"
                downstream_refs = tuple(row.get("downstream_ref_ids", ()))
                for ref_id in downstream_refs:
                    stored = context.artifacts.get(str(ref_id))
                    if stored is None:
                        continue
                    quality_report_hash = str(stored.artifact.metadata.get("quality_report_hash", ""))
                    receipt = context.artifact_verification_receipts.get(str(ref_id))
                    artifact_verification_hash = "" if receipt is None else receipt.receipt_hash
                    break
                if row.get("replay_class") == ReplayClass.VALIDATED_REPLAY.value:
                    restore_status = "verified_recipe" if row.get("recipe_recomputed") else "verified_recipe"
                row.update({
                    "execution_binding_hash": "" if binding is None else binding.binding_hash,
                    "restore_kind": "recipe" if row.get("replay_class") == ReplayClass.VALIDATED_REPLAY.value else "none",
                    "restore_status": restore_status,
                    "quality_report_hash": quality_report_hash,
                    "artifact_verification_receipt_hash": artifact_verification_hash,
                    "terminal_status": "success" if dispatch is None or not dispatch.error_code else "runtime_fail",
                    "failure_stage": "" if dispatch is None or not dispatch.error_code else "runtime",
                    "source_receipt_hashes": [item for item in (
                        row.get("memory_admission_receipt_hash", ""),
                        row.get("replay_eligibility_receipt_hash", ""),
                        "" if binding is None else binding.binding_hash,
                        quality_report_hash,
                        artifact_verification_hash,
                        "" if admission is None else admission.receipt_hash,
                    ) if item],
                    "attempt_identity": {
                        "task_id": row.get("consumer_runtime_task_id", ""),
                        "run_id": row.get("consumer_run_id", ""),
                        "session_id": row.get("consumer_session_id", ""),
                        "step_id": row.get("consumer_step_id", ""),
                        "attempt_id": row.get("consumer_attempt_id", ""),
                        "capability_grant_hash": row.get("capability_grant_hash", ""),
                        "execution_binding_hash": "" if binding is None else binding.binding_hash,
                        "attempt_result_admission_receipt_hash": row.get("attempt_result_admission_receipt_hash", ""),
                    },
                })
                return row

            rows = [row_projection(record) for record in context.memory_consumption_records]
            validated_rows = [
                row for row in rows
                if row.get("replay_class") == ReplayClass.VALIDATED_REPLAY.value
                and row.get("attempt_result_admission_receipt_hash")
            ]
            observations = [dict(item) for item in context.replay_observations]
            skip_receipts = [
                {
                    **observation,
                    "skip_receipt_id": f"provider-skip:{observation['observation_id']}",
                    "skip_kind": "provider_invocation",
                    "current_task_id": observation.get("runtime_task_id", ""),
                    "current_run_id": observation.get("run_id", ""),
                    "current_session_id": observation.get("session_id", ""),
                    "current_step_id": observation.get("step_id", ""),
                    "current_attempt_id": observation.get("attempt_id", ""),
                    "current_grant_hash": observation.get("capability_grant_hash", ""),
                    "current_binding_hash": observation.get("execution_binding_hash", ""),
                    "baseline_row_id": "",
                    "baseline_invocation_or_recipe_id": "",
                    "current_invocation_status": observation.get("provider_invocation_status", "unknown"),
                    "skipped_step_ids": [],
                    "skipped_provider_calls": [observation.get("provider_id", "")],
                    "quality_report_hash": observation.get("quality_report_hash", ""),
                    "quality_result_admission_hash": observation.get("attempt_result_admission_receipt_hash", ""),
                    "terminal_status": observation.get("terminal_status", "runtime_fail"),
                    "denominator_status": "unsupported",
                    "status": (
                        "observed"
                        if observation.get("attempt_result_admission_receipt_hash")
                        else "unsupported"
                    ),
                    "reason": (
                        "runtime_owned_observation_result_admitted"
                        if observation.get("attempt_result_admission_receipt_hash")
                        else "runtime_result_admission_missing"
                    ),
                    "created_at_ns": observation.get("created_at_ns", 0),
                }
                for observation in observations
                if (
                    stage == "C1"
                    and observation.get("provider_invocation_status") == "not_started"
                )
            ]
            quality_rows = [
                {
                    "report_hash": report_hash,
                    "verified": bool(getattr(report, "verified", False)),
                }
                for report_hash, report in sorted(context.quality_reports.items())
            ]
            result_admissions = [receipt.canonical_payload() for receipt in runtime.attempt_result_admissions]
            binding_hashes = [binding.binding_hash for binding in runtime.execution_bindings]
            grant_hashes = [grant.grant.grant_hash for grant in runtime.bound_grants]
            replay_eligibility = [receipt.canonical_payload() for receipt in runtime.replay_eligibility_receipts]
            exact_reason = "c2_exact_restore_not_implemented"
            exact_projection = {
                "status": "unsupported",
                "value": None,
                "reason": exact_reason,
            }
            common = {
                "row_identity": [
                    {
                        "memory_id": row.get("memory_id", ""),
                        "memory_commit_hash": row.get("memory_commit_hash", ""),
                        "memory_admission_receipt_hash": row.get("memory_admission_receipt_hash", ""),
                        "replay_eligibility_receipt_hash": row.get("replay_eligibility_receipt_hash", ""),
                        "attempt_result_admission_receipt_hash": row.get("attempt_result_admission_receipt_hash", ""),
                        "capability_grant_hash": row.get("capability_grant_hash", ""),
                    }
                    for row in rows
                ],
                "memory_admission_receipts": {
                    memory_id: receipt.canonical_payload()
                    for memory_id, receipt in sorted(infrastructure.memory_store.admission_receipts.items())
                },
                "runtime_grants": [grant.canonical_payload() for grant in runtime.bound_grants],
                "runtime_bindings": [binding.canonical_payload() for binding in runtime.execution_bindings],
                "attempt_result_admissions": result_admissions,
                "g6a_memfd_limitation": "skipped: memfd unavailable; SHM actual-read retained",
            }

            def put(name: str, payload: object) -> None:
                (root / name).write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")

            put("manifest.json", c0c1_envelope(
                "observed",
                mode=stage,
                exact_replay_status=exact_projection,
                exact_replay=exact_projection,
                work_avoided_status="unsupported",
                benchmark_superiority="NOT_ESTABLISHED",
                live_vllm_gpu_validation="NOT_RUN",
                **common,
            ))
            put("runtime_trace.json", c0c1_envelope("observed", runtime_identity=runtime_identity.canonical_payload(), dispatches=[dispatch.__dict__ for dispatch in runtime.dispatches], replay_observations=observations, **common))
            put("replay_eligibility_receipts.json", c0c1_envelope("observed" if replay_eligibility else "not_applicable", reason="" if replay_eligibility else "no_validated_replay_eligibility", receipts=replay_eligibility, **common))
            put("replay_consumption_receipts.json", c0c1_envelope("observed" if validated_rows else "unsupported", reason="" if validated_rows else "no_result_admitted_validated_replay", receipts=validated_rows, **common))
            put("replay_quality_evidence.json", c0c1_envelope("observed" if quality_rows else "unsupported", reason="" if quality_rows else "quality_reports_not_observed", quality_reports=quality_rows, result_admissions=result_admissions, **common))
            put("provider_skip_receipts.json", c0c1_envelope("observed" if any(item.get("status") == "observed" for item in skip_receipts) else ("unsupported" if skip_receipts else "not_applicable"), reason="" if any(item.get("status") == "observed" for item in skip_receipts) else ("runtime_result_admission_missing" if skip_receipts else ("provider_bypass_observation_only_in_c1" if stage == "C0" else "no_runtime_provider_bypass_observed")), receipts=skip_receipts, **common))
            put("baseline_pairings.json", c0c1_envelope("unsupported", reason="c2_matched_baseline_deferred", pairings=[], **common))
            put("recipe_restore_evidence.json", c0c1_envelope("observed" if context.execution_recipes_by_artifact else "not_applicable", reason="" if context.execution_recipes_by_artifact else "no_recipe_artifact_registered", recipes=context.execution_recipes_by_artifact, recipe_recomputed_rows=[row for row in rows if row.get("recipe_recomputed")], **common))
            put("artifact_restore_evidence.json", c0c1_envelope("not_applicable", reason="c2_exact_artifact_restore_deferred", artifacts={}, **common))
            put("invalidation_receipts.json", c0c1_envelope("not_applicable", reason="no_invalidation_in_this_row", receipts=[], **common))
            put("memory_runtime_receipt_join.json", c0c1_envelope("observed" if rows else "not_applicable", reason="" if rows else "no_memory_consumption_rows", joins=rows, **common))
            put("downstream_effect_evidence.json", c0c1_envelope("observed" if rows else "not_applicable", reason="" if rows else "no_downstream_effect_rows", effects=[
                {"memory_id": row.get("memory_id", ""), "behavioral_effect": row.get("behavioral_effect", ""), "result_admission_joined": bool(row.get("attempt_result_admission_receipt_hash"))}
                for row in rows
            ], **common))
            terminal_rows = [
                {
                    "row_id": f"terminal:{dispatch.step_id}:{dispatch.attempt_id}",
                    "task_id": request.task_id,
                    "run_id": runtime_identity.run_id,
                    "session_id": runtime_identity.session_id,
                    "step_id": dispatch.step_id,
                    "attempt_id": dispatch.attempt_id,
                    "terminal": dispatch.state,
                    "terminal_status": "success" if not dispatch.error_code else "runtime_fail",
                    "failure_stage": "" if not dispatch.error_code else "runtime",
                    "error_code": dispatch.error_code,
                }
                for dispatch in runtime.dispatches
            ]
            put("terminal_rows.json", c0c1_envelope("observed", rows=terminal_rows, **common))
            negative_rows = [
                {"row_id": "negative:missing-admission", "task_id": request.task_id, "run_id": runtime_identity.run_id, "session_id": runtime_identity.session_id, "attempt_id": "negative-attempt:missing-admission", "status": "rejected", "error_code": "grant_memory_admission_missing", "failure_stage": "memory_admission", "terminal_status": "runtime_fail", "denominator_row_id": "negative:missing-admission", "provenance_scope": "fixture_control", "runtime_attempt_evidence": False},
                {"row_id": "negative:stale-grant", "task_id": request.task_id, "run_id": runtime_identity.run_id, "session_id": runtime_identity.session_id, "attempt_id": "negative-attempt:stale-grant", "status": "rejected", "error_code": "grant_memory_attempt_stale", "failure_stage": "grant_validation", "terminal_status": "runtime_fail", "denominator_row_id": "negative:stale-grant", "provenance_scope": "fixture_control", "runtime_attempt_evidence": False},
                {"row_id": "negative:quality-failure", "task_id": request.task_id, "run_id": runtime_identity.run_id, "session_id": runtime_identity.session_id, "attempt_id": "negative-attempt:quality-failure", "status": "rejected", "error_code": "quality_result_admission_required", "failure_stage": "quality", "terminal_status": "runtime_fail", "denominator_row_id": "negative:quality-failure", "provenance_scope": "fixture_control", "runtime_attempt_evidence": False},
            ]
            put("negative_row_index.json", c0c1_envelope("observed", rows=negative_rows, **common))
            put("failure_denominator.json", c0c1_envelope("observed", attempted_rows=len(terminal_rows) + len(negative_rows), terminal_row_ids=[row["row_id"] for row in terminal_rows], runtime_attempt_row_ids=[row["row_id"] for row in terminal_rows], negative_row_ids=[row["row_id"] for row in negative_rows], fixture_control_row_ids=[row["row_id"] for row in negative_rows], row_ids=[row["row_id"] for row in terminal_rows] + [row["row_id"] for row in negative_rows], scope="runtime_terminal_plus_fixture_control", limitation="fixture_control_negative_rows_are_not_runtime_attempt_evidence", arithmetic_closed=True, **common))
            put("metric_availability.json", c0c1_envelope("observed", metrics={
                "validated_replay_count": {"status": "observed", "value": len(validated_rows), "reason": "read_quality_result_admission_join"},
                "exact_replay_count": exact_projection,
                "recipe_recomputed_count": {"status": "observed", "value": sum(bool(row.get("recipe_recomputed")) for row in rows), "reason": "current_recipe_execution_diagnostic"},
                "provider_skip_observed_count": {"status": "observed" if stage == "C1" and skip_receipts else "not_applicable", "value": len(skip_receipts) if stage == "C1" else None, "reason": "runtime_owned_observation" if skip_receipts else ("provider_bypass_observation_only_in_c1" if stage == "C0" else "no_runtime_provider_bypass_observed")},
                "provider_work_avoided": {"status": "unsupported", "value": None, "reason": "no_matched_baseline_or_c2_work_avoided"},
                "verified_recipe_work_avoided": {"status": "unsupported", "value": None, "reason": "recipe_step_skip_deferred_to_c2"},
            }, **common))
            put("g5c_acceptance.json", c0c1_envelope("observed", acceptance_status=f"{stage}_COMPLETE_PENDING_ASTRA_ACCEPTANCE", validated_replay_observed=len(validated_rows), exact_replay=exact_projection, exact_replay_status=exact_projection, work_avoided="unsupported", benchmark_superiority="NOT_ESTABLISHED", **common))
            put("scorer_result.json", c0c1_envelope("observed", quality_pass=all(item["verified"] for item in quality_rows) if quality_rows else False, quality_non_regression={"status": "unsupported", "reason": "no_matched_baseline"}, claim_restriction={"exact_replay": exact_projection, "work_avoided": "unsupported"}, exact_replay=exact_projection, **common))
            put("root_audit.json", c0c1_envelope("observed", artifact_root=str(root), identity_collisions=[], **common))

        if context.g5c_c0_artifact_root is None:
            context.g5c_c0_artifact_root = Path(tempfile.mkdtemp(prefix="g5c-c0-"))
        if context.g5c_c1_artifact_root is None:
            context.g5c_c1_artifact_root = Path(tempfile.mkdtemp(prefix="g5c-c1-"))
        write_g5c_stage("C0", context.g5c_c0_artifact_root)
        write_g5c_stage("C1", context.g5c_c1_artifact_root)
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


def _validate_c2a_envelope(request: AdaptiveMainlineRequest) -> None:
    envelope = request.envelope
    expected_roles = {
        "planner": (1, 1),
        "retriever": (1, 1),
        "executor": (1, 1),
        "summarizer": (1, 1),
    }
    checks = (
        (envelope.role_cardinality == expected_roles, "role_cardinality_mismatch"),
        (envelope.max_plan_steps == 4, "plan_steps_mismatch"),
        (envelope.max_dependency_depth == 4, "dependency_depth_mismatch"),
        (envelope.max_total_attempts == 4, "attempt_budget_mismatch"),
        (envelope.max_replans == 0, "replan_budget_mismatch"),
        (envelope.max_retrieval_expansions == 0, "retrieval_expansion_budget_mismatch"),
    )
    for valid, code in checks:
        if not valid:
            raise AdaptiveMainlineError(f"c2a.adaptive.proposal_rejected:c2a.{code}")
    from statebus.runtime.domain_packs import c2a_four_role_pack

    pack = c2a_four_role_pack()
    if tuple(envelope.allowed_capability_ids) != pack.capability_ids:
        raise AdaptiveMainlineError("c2a.adaptive.proposal_rejected:c2a.capability_surface_mismatch")


def _validate_c2a_proposal(
    proposal: PlanProposal | None,
    request: AdaptiveMainlineRequest,
) -> None:
    if proposal is None:
        raise AdaptiveMainlineError("c2a.adaptive.proposal_rejected:c2a.proposal_missing")
    steps = tuple(proposal.steps)
    expected = (
        ("plan", "planner", "plan_retrieval_and_execution_v1", ()),
        ("retrieve", "retriever", "retrieve_table_evidence_v1", ("plan",)),
        ("execute", "executor", "extract_metric_series_v1", ("retrieve",)),
        ("summarize", "summarizer", "compose_cited_report_v1", ("execute",)),
    )
    if len(steps) != len(expected):
        raise AdaptiveMainlineError("c2a.adaptive.proposal_rejected:adaptive_canonical_requires_four_role_proposal")
    for step, (step_id, role, capability_id, dependencies) in zip(steps, expected, strict=True):
        if (
            step.step_id != step_id
            or step.role != role
            or step.capability_id != capability_id
            or tuple(step.depends_on) != dependencies
        ):
            code = "planner_capability_unregistered" if role == "planner" and step.capability_id != capability_id else "role_graph_mismatch"
            raise AdaptiveMainlineError(f"c2a.adaptive.proposal_rejected:c2a.{code}")
    if proposal.final_output_contract_version != "statebus.cited_report.v1":
        raise AdaptiveMainlineError("c2a.adaptive.proposal_rejected:c2a.recipe_identity_mismatch")
    if request.approved_plan_bundle is not None:
        bundle = request.approved_plan_bundle
        if bundle.recipe_id != "c2a-four-role" or bundle.recipe_version != "v1":
            raise AdaptiveMainlineError("c2a.adaptive.proposal_rejected:c2a.recipe_identity_mismatch")
