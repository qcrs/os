from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Callable

from v2.contracts import (
    AdaptiveTaskEnvelope,
    ApprovedPlan,
    PlanPolicyReport,
    PlanProposal,
    WorkflowMode,
)
from v2.memory import MemoryIndexStore
from v2.refs import ExecutionArtifactRef
from v2.runtime.adaptive_dispatcher import (
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
from v2.runtime.adaptive_runtime import (
    AdaptiveRuntimeEngine,
    AdaptiveRuntimeRequest,
    AdaptiveRuntimeResult,
)
from v2.runtime.capability_registry import CapabilityRegistry
from v2.runtime.capability_validators import (
    CapabilityValidatorRegistry,
    default_capability_validator_registry,
)
from v2.runtime.plan_policy import PlanPolicyValidator
from v2.runtime.retrieval_adapter import AdaptiveRetrievalAdapter
from v2.runtime.telemetry import TelemetryEvent
from v2.runtime.workspace import WorkspaceLayout, WorkspaceManager
from v2.state import LayeredStateStore, LayeredStoragePolicy
from v2.utils import sha256_digest, stable_json_dumps


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


@dataclass(frozen=True)
class AdaptiveMainlineInfrastructure:
    state_store: LayeredStateStore
    memory_store: MemoryIndexStore
    workspace_manager: WorkspaceManager
    workspace_layout: WorkspaceLayout
    socket_path: Path


@dataclass(frozen=True)
class AdaptiveMainlineResult:
    runtime: AdaptiveRuntimeResult
    planner: AdaptivePlannerAssemblyRecord
    context: AdaptiveDispatchContext
    infrastructure: AdaptiveMainlineInfrastructure
    manifest_path: Path
    state_cleanup_completed: bool

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

        runtime_root = Path(request.runtime_root)
        runtime_root.mkdir(parents=True, exist_ok=True)
        workspace_manager = WorkspaceManager(Path(request.workspace_root))
        workspace_layout = workspace_manager.ensure_layout(request.task_id)
        state_store = LayeredStateStore(
            root=runtime_root / "state",
            policy=LayeredStoragePolicy.for_state_pool_mode(request.state_pool_mode),
        )
        memory_store = MemoryIndexStore(store_root=runtime_root / "memory_index")
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
            proposal_valid=not planner_record.policy_repair_used,
            policy_rejected=planner_record.policy_repair_used,
            repair_used=planner_record.policy_repair_used,
            fallback_used=(
                request.fallback_proposal is not None
                and approved_plan.source_proposal_id == request.fallback_proposal.proposal_id
            ),
            dispatcher=AdaptiveCapabilityDispatcher(context=context),
            layer_name=request.layer_name,
        )

        state_cleanup_completed = False
        released_state_ids: set[str] = set()
        runtime_result = None
        manifest_path: Path | None = None
        try:
            runtime_result = AdaptiveRuntimeEngine().run(runtime_request)
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
        )

    @staticmethod
    def _assemble_plan(
        request: AdaptiveMainlineRequest,
    ) -> tuple[PlanProposal, ApprovedPlan, AdaptivePlannerAssemblyRecord]:
        raw_proposal = request.propose_plan()
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
        if request.normalize_plan is not None:
            effective, normalization_fields = request.normalize_plan(raw_proposal)
        outcome = validator.validate(
            effective,
            request.envelope,
            available_input_refs=request.available_input_refs,
        )
        policy_repair_used = False
        if outcome.approved_plan is None and request.repair_plan is not None:
            repaired = request.repair_plan(effective, outcome.report, normalization_fields)
            if repaired is not None:
                effective = repaired
                repair_fields: tuple[str, ...] = ()
                if request.normalize_plan is not None:
                    effective, repair_fields = request.normalize_plan(repaired)
                normalization_fields = (*normalization_fields, *repair_fields)
                outcome = validator.validate(
                    effective,
                    request.envelope,
                    available_input_refs=request.available_input_refs,
                )
                policy_repair_used = True
        if outcome.approved_plan is None and request.fallback_proposal is not None:
            effective = request.fallback_proposal
            outcome = validator.validate(
                effective,
                request.envelope,
                available_input_refs=request.available_input_refs,
            )
        if outcome.approved_plan is None:
            category = _planner_rejection_category(outcome.report)
            raise AdaptiveMainlineError(f"planner_hard_rejection:{category}")
        if request.validate_approved_plan is not None:
            request.validate_approved_plan(outcome.approved_plan)
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
        )
        return effective, outcome.approved_plan, planner_record

    @staticmethod
    def _persist_manifest(
        *,
        request: AdaptiveMainlineRequest,
        planner: AdaptivePlannerAssemblyRecord,
        runtime: AdaptiveRuntimeResult,
        context: AdaptiveDispatchContext,
        infrastructure: AdaptiveMainlineInfrastructure,
    ) -> Path:
        manifest_path = Path(request.runtime_root) / "adaptive_mainline_manifest.json"
        payload = {
            "schema_version": "statebus.adaptive_mainline_manifest.v1",
            "trace_id": request.trace_id,
            "task_id": request.task_id,
            "workflow_mode": request.envelope.workflow_mode.value,
            "planner": planner.canonical_payload(),
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
