from __future__ import annotations

from dataclasses import dataclass, field, replace
from contextlib import AbstractContextManager, nullcontext
import asyncio
import inspect
import json
from pathlib import Path
import time
from typing import Callable, TYPE_CHECKING
from uuid import uuid4

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    ApprovedPlan,
    ArtifactVerificationDecision,
    ArtifactVerificationReceipt,
    BoundCapabilityGrant,
    CapabilityGrant,
    CanonicalTaskSpec,
    ClaimSet,
    CodeGenerationPolicy,
    CodeGenerationRequest,
    CompatibilityVerdict,
    CONTROL_PLANE_SCHEMA_VERSION,
    EvidenceCoverageStatus,
    EvidenceProjectionRequest,
    EvidenceRequest,
    ExecutionKind,
    GeneratedCodeCandidate,
    PlanStepProposal,
    RefStatus,
    ReplayClass,
    RiskClass,
    RuntimeIdentity,
    STATE_ACCESS_AUTHORITY_RUNTIME_INTERMEDIATE,
    StateAccessGrant,
    StorageKind,
    TransformProgram,
    TransformStep,
    PlannerHandoff,
)
from statebus.memory import MemoryConsumptionRecord, ReplayEligibilityDecision, ReplayEligibilityReceipt
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
from statebus.runtime.provider_registry import (
    ExecutionProviderRegistry,
    ProviderBindingError,
)
from statebus.runtime.role_providers import (
    ExecutorCandidateReviewBinding,
    ExecutorCandidateReviewDecision,
    ProviderCandidate,
    ProviderRequest,
    ProviderStateReadFacade,
    RoleProviderContext,
    detach_provider_candidate,
)
from statebus.runtime.transform_dsl import TransformDslInterpreter, TransformProgramError
from statebus.runtime.telemetry import TelemetryEmitter, TelemetryEvent
from statebus.runtime.execution_routing import resolve_execution_route
from statebus.runtime.claims import ClaimSetValidator
from statebus.runtime.workspace import ArtifactLifecycleManager
from statebus.utils import sha256_digest, stable_json_dumps

if TYPE_CHECKING:
    from statebus.memory import MemoryIndexStore
    from statebus.runtime.adaptive_runtime import AdaptiveStepResult
    from statebus.runtime.workspace import WorkspaceManager
    from statebus.state import LayeredStateStore
    from statebus.runtime.adaptive_runtime import RuntimeStateAccessAuthority
    from statebus.runtime.session import RuntimeSessionManager


class AdaptiveDispatchError(RuntimeError):
    pass


_DSL_REPAIR_NON_BUSINESS_FAILURES = {
    "invalid_schema_version",
    "unauthorized_input_ref",
    "input_column_budget_exceeded",
    "output_column_budget_exceeded",
    "unsafe_argument_key",
    "unsafe_argument_value",
    "deterministic_fixture_not_allowed",
    "missing_fixture_id",
    "invalid_fixture_arguments",
    "unauthorized_join_ref",
    "input_row_budget_exceeded",
    "output_row_budget_exceeded",
    "output_byte_budget_exceeded",
    "join_budget_exceeded",
    "recompute_input_missing",
}


def _dsl_repair_exhausted_code(error: BaseException) -> str:
    if not isinstance(error, (CapabilityRecomputeError, TransformProgramError)):
        return ""
    failure = str(error)
    root = failure.split(":", 1)[0]
    if root in _DSL_REPAIR_NON_BUSINESS_FAILURES:
        return ""
    return f"dsl_repair_exhausted:{failure}"


def _classify_provider_exception(
    role: str,
    exc: BaseException,
) -> tuple[str, bool, bool] | None:
    """Map provider-boundary failures to stable Runtime result semantics.

    Only exceptions that identify the provider boundary are converted here.
    Runtime/programming errors from the handler continue through the normal
    dispatcher error path so they are not silently reclassified as timeouts.
    """

    if isinstance(exc, (APITimeoutError, TimeoutError, asyncio.TimeoutError)):
        return f"{role}_timeout", True, False
    if isinstance(exc, (APIConnectionError, ConnectionError)):
        return f"{role}_provider_connection_error", False, True
    if isinstance(exc, APIStatusError):
        status_code = int(getattr(exc, "status_code", 0) or 0)
        retryable = status_code in {408, 409, 429, 500, 502, 503, 504}
        return (
            f"{role}_provider_http_{status_code or 'error'}",
            False,
            retryable,
        )
    if isinstance(exc, APIError):
        return (
            f"provider_invocation_failed:{role}:{type(exc).__name__}",
            False,
            False,
        )
    return None


@dataclass(frozen=True)
class StoredAdaptiveArtifact:
    artifact: ExecutionArtifactRef
    rows: tuple[dict[str, object], ...]
    provenance_item_ids: tuple[str, ...] = ()


RetrievalRequestFactory = Callable[[PlanStepProposal, CapabilityGrant], "EvidenceRequest"]
RetrievalExpansionFactory = Callable[["EvidenceRequest", "EvidenceCoverageReport"], "EvidenceRequest | None"]
RetrievalResultObserver = Callable[[AdaptiveRetrievalResult, PlanStepProposal, CapabilityGrant], tuple["StateConsumptionRecord", ...]]
TransformProgramFactory = Callable[..., TransformProgram]
# The first five positional arguments are the stable legacy contract.  New
# callers may accept keyword-only repair context (``previous_program``,
# ``repair_stage`` and ``input_tables``) so a repair provider can make a
# minimally-scoped correction instead of regenerating blindly.
TransformProgramRepairFactory = Callable[..., TransformProgram]
DeterministicFixtureRunner = Callable[
    [TransformStep, list[dict[str, object]]], list[dict[str, object]]
]
CodeSourceFactory = Callable[[CodeGenerationRequest, str], str]
CodeRepairFactory = Callable[[CodeGenerationRequest, str, str, tuple[str, ...]], str]
BuiltinHandler = Callable[[AdaptiveTaskEnvelope, ApprovedPlan, PlanStepProposal, CapabilityGrant, Path], "AdaptiveStepResult"]
ClaimSetFactory = Callable[..., ClaimSet]
BoundProviderHandler = Callable[[ProviderRequest], ProviderCandidate]


_SEMANTIC_STATE_MODES = frozenset({"off", "on", "consumer_off"})


@dataclass
class AdaptiveDispatchContext:
    registry: CapabilityRegistry
    # Matched-ablation control.  ``on`` is the production path; ``off``
    # suppresses publication and consumption; ``consumer_off`` keeps the
    # producer path observable while disabling the cross-process consumer.
    semantic_state_mode: str = "on"
    # Optional bounded experiment policy for the Executor-side semantic-state
    # consumer. Production callers leave these unset and retain the historical
    # reference-pack-derived selection policy.
    semantic_state_executor_top_k: int | None = None
    semantic_state_executor_budget_bytes: int | None = None
    validator_registry: CapabilityValidatorRegistry = field(default_factory=default_capability_validator_registry)
    evidence_packs: dict[str, CanonicalEvidencePack] = field(default_factory=dict)
    evidence_statuses: dict[str, EvidenceCoverageStatus] = field(default_factory=dict)
    evidence_ref_scopes: dict[str, tuple[str, str]] = field(default_factory=dict)
    artifacts: dict[str, StoredAdaptiveArtifact] = field(default_factory=dict)
    artifact_verification_receipts: dict[str, ArtifactVerificationReceipt] = field(
        default_factory=dict
    )
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
    # Explicitly disable the Memory query projection for a matched control.
    # Keep the default enabled for compatibility with existing mainline runs.
    memory_query_enabled: bool = True
    transform_program_factory: TransformProgramFactory | None = None
    transform_program_repair_factory: TransformProgramRepairFactory | None = None
    # Offline benchmark fixtures may provide a source-derived transform for a
    # deterministic smoke.  The callback is absent for live/provider paths;
    # the DSL validator therefore rejects the fixture-only operation there.
    deterministic_fixture_runner: DeterministicFixtureRunner | None = None
    code_source_factory: CodeSourceFactory | None = None
    code_repair_factory: CodeRepairFactory | None = None
    code_policy_factory: Callable[[PlanStepProposal], CodeGenerationPolicy] | None = None
    # Controller-owned semantic contracts for registered bounded-Python
    # capabilities.  The Planner chooses a capability, never these formulas.
    codeact_contracts: dict[str, dict[str, object]] = field(default_factory=dict)
    quality_semantics_by_capability: dict[str, dict[str, object]] = field(default_factory=dict)
    output_schema_by_capability: dict[str, dict[str, str]] = field(default_factory=dict)
    output_schema_by_step: dict[str, dict[str, str]] = field(default_factory=dict)
    input_schema_by_step: dict[str, dict[str, str]] = field(default_factory=dict)
    # The caller supplies an LLM-backed candidate factory only.  The Runtime
    # continues to select verified inputs, validate citations/numerics and
    # issue the final cited-report ArtifactRef.
    claim_set_factory: ClaimSetFactory | None = None
    claim_memory_selector: Callable[[tuple[dict[str, object], ...]], tuple[str, ...]] | None = None
    # Explicit Runtime-side allowlist for capabilities that may read an
    # admitted validated-replay candidate as bounded assist context.  This is
    # intentionally separate from ``CapabilityDescriptor.supports_replay``:
    # a consumer such as a summarizer may verify a producer artifact without
    # being allowed to reuse the producer procedure or skip its own work.
    memory_assist_capability_ids: tuple[str, ...] = ()
    builtin_handlers: dict[str, BuiltinHandler] = field(default_factory=dict)
    # Disjoint from legacy BuiltinHandler: bound providers receive the full
    # BoundCapabilityGrant through ProviderRequest and return a candidate.
    bound_provider_handlers: dict[str, BoundProviderHandler] = field(default_factory=dict)
    executor_candidate_review: ExecutorCandidateReviewBinding | None = None
    executor_candidate_review_enabled: bool = False
    executor_candidate_review_records: list[dict[str, object]] = field(default_factory=list)
    planner_handoffs: dict[str, PlannerHandoff] = field(default_factory=dict)
    provider_registry: ExecutionProviderRegistry | None = None
    provider_state_reader_factory: Callable[[ProviderRequest], ProviderStateReadFacade | None] | None = None
    # Dispatcher/transport-owned evidence keyed by the current grant.  A
    # provider cannot self-assert CodeAct response hashes.
    provider_invocation_evidence: dict[str, dict[str, str]] = field(default_factory=dict)
    # Product-runtime infrastructure. Handlers receive authority through the
    # context assembled by AdaptiveMainlineRunner, never by diagnostics code.
    state_store: "LayeredStateStore | None" = None
    memory_store: "MemoryIndexStore | None" = None
    session_manager: "RuntimeSessionManager | None" = None
    telemetry: TelemetryEmitter | None = None
    runtime_identity: RuntimeIdentity | None = None
    workspace_manager: "WorkspaceManager | None" = None
    socket_path: Path | None = None
    semantic_state_publications: dict[str, object] = field(default_factory=dict)
    semantic_state_selections: dict[str, object] = field(default_factory=dict)
    component_activation_receipts: dict[str, dict[str, object]] = field(default_factory=dict)
    state_access_grants: dict[str, tuple[StateAccessGrant, ...]] = field(default_factory=dict)
    control_response_admissions: dict[str, tuple[object, ...]] = field(default_factory=dict)
    # Physical worker observations are retained for audit only.  They do not
    # mutate the outer semantic Step lifecycle unless that worker is the
    # explicitly bound execution boundary (which semantic-select is not).
    physical_lifecycle_observations: list[dict[str, object]] = field(default_factory=list)
    memory_match_results: dict[str, object] = field(default_factory=dict)
    memory_queries_by_task: dict[str, object] = field(default_factory=dict)
    replay_eligibility_receipts_by_step: dict[str, tuple[ReplayEligibilityReceipt, ...]] = field(
        default_factory=dict
    )
    memory_selection_modes_by_step: dict[str, dict[str, ReplayClass]] = field(
        default_factory=dict
    )
    memory_role_inputs_by_step: dict[str, tuple[dict[str, object], ...]] = field(
        default_factory=dict
    )
    memory_consumption_records: list[MemoryConsumptionRecord] = field(default_factory=list)
    # Runtime consumer observations are deliberately separate from role input
    # construction.  A role input is an approved descriptor; only an explicit
    # read observation can promote it to a MemoryConsumptionRecord.
    memory_read_observations_by_step: dict[str, tuple[str, ...]] = field(default_factory=dict)
    memory_approved_unused_by_step: dict[str, tuple[str, ...]] = field(default_factory=dict)
    memory_read_evidence_by_id: dict[str, dict[str, object]] = field(default_factory=dict)
    execution_recipes_by_artifact: dict[str, dict[str, object]] = field(default_factory=dict)
    canonical_task_spec: CanonicalTaskSpec | None = None
    input_lineage_hashes: tuple[str, ...] = ()
    input_schema_digest: str = ""
    validator_digest: str = ""
    runtime_compatibility_signature: str = ""
    state_consumption_records: list[object] = field(default_factory=list)
    state_publication_receipts: dict[str, dict[str, object]] = field(default_factory=dict)
    state_pin_receipts: dict[str, tuple[dict[str, object], ...]] = field(default_factory=dict)
    semantic_consumer_receipts: dict[str, dict[str, object]] = field(default_factory=dict)
    state_release_reclaim_receipts: dict[str, dict[str, object]] = field(default_factory=dict)
    state_lifecycle_timestamps: dict[str, dict[str, int]] = field(default_factory=dict)
    downstream_effects: dict[str, dict[str, object]] = field(default_factory=dict)
    # Deterministic acceptance fixtures may provide an observed before/after
    # surface pair for a specific verified Memory ref. Runtime still owns the
    # read, Grant validation and result-admission join.
    memory_after_surface_hash_by_memory_id: dict[str, str] = field(default_factory=dict)
    g5a_artifact_root: Path | None = None
    # G5-C staged evidence is a Runtime projection only.  These roots are
    # allocated by the mainline writer and never participate in authority or
    # admission decisions.
    g5c_c0_artifact_root: Path | None = None
    g5c_c1_artifact_root: Path | None = None
    replay_observations: list[dict[str, object]] = field(default_factory=list)
    # Route requests are controller-owned metadata.  The dispatcher records
    # the effective route; it never grants a new capability from this map.
    requested_routes_by_step: dict[str, str] = field(default_factory=dict)
    route_evidence_by_step: dict[str, list[dict[str, object]]] = field(default_factory=dict)


class AdaptiveCapabilityDispatcher:
    """Execute only an already-approved capability under a one-attempt Grant."""

    def _measure_phase(self, phase: str, grant: CapabilityGrant) -> AbstractContextManager:
        if self.context.telemetry is None:
            return nullcontext()
        return self.context.telemetry.measure_phase(
            phase,
            trace_id=self.context.runtime_identity.trace_id if self.context.runtime_identity else "",
            task_id=grant.task_id, step_id=grant.step_id, attempt_id=grant.attempt_id,
        )

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
        self.transform_interpreter = transform_interpreter or TransformDslInterpreter(
            deterministic_fixture_runner=context.deterministic_fixture_runner,
        )
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

    @staticmethod
    def _invoke_transform_program_repair(
        factory: TransformProgramRepairFactory,
        *,
        step: PlanStepProposal,
        grant: CapabilityGrant,
        input_ref_id: str,
        rows: tuple[dict[str, object], ...],
        validation_errors: tuple[str, ...],
        input_tables: dict[str, tuple[dict[str, object], ...]],
        previous_program: TransformProgram,
        repair_stage: str,
    ) -> TransformProgram:
        """Invoke a DSL repair factory with the rejected candidate attached.

        Existing integrations use the original five positional parameters.
        Optional keyword arguments are capability-neutral metadata and are
        supplied only when the callback declares them (or accepts ``**kwargs``).
        This keeps older fixtures working while making the repair boundary
        auditable and useful for provider-backed implementations.
        """
        try:
            parameters = inspect.signature(factory).parameters
        except (TypeError, ValueError):
            parameters = {}
        accepts_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

        optional = {
            "input_tables": input_tables,
            "previous_program": previous_program,
            "repair_stage": repair_stage,
        }
        kwargs = {
            name: value
            for name, value in optional.items()
            if accepts_kwargs
            or (
                name in parameters
                and parameters[name].kind is not inspect.Parameter.POSITIONAL_ONLY
            )
        }
        return factory(
            step,
            grant,
            input_ref_id,
            rows,
            tuple(validation_errors),
            **kwargs,
        )

    def dispatch(
        self,
        *,
        envelope: AdaptiveTaskEnvelope,
        approved_plan: ApprovedPlan,
        step: PlanStepProposal,
        grant: BoundCapabilityGrant | CapabilityGrant,
        attempt_workspace: Path,
        runtime_identity: RuntimeIdentity,
        state_access_authority: "RuntimeStateAccessAuthority | None" = None,
    ) -> "AdaptiveStepResult":
        from statebus.runtime.adaptive_runtime import AdaptiveStepResult

        plain_grant = grant.grant if isinstance(grant, BoundCapabilityGrant) else grant
        self.context.runtime_identity = runtime_identity
        try:
            if not isinstance(grant, BoundCapabilityGrant):
                raise AdaptiveDispatchError("execution_binding_required")
            descriptor = self.context.registry.get(step.capability_id)
            bound_handler = self.context.bound_provider_handlers.get(step.capability_id)
            selected_kind = (
                grant.execution_binding.selected_implementation_kind
                if isinstance(grant, BoundCapabilityGrant)
                else descriptor.execution_kind.value
            )
            route_decision = resolve_execution_route(
                self.context.requested_routes_by_step.get(step.step_id, "runtime_policy"),
                descriptor_execution_kind=descriptor.execution_kind,
                selected_execution_kind=selected_kind,
                allow_llm_python=envelope.allow_llm_python,
                risk_class=envelope.risk_class,
            )
            route_evidence = {
                "schema_version": "statebus.execution_route_evidence.v1",
                "route_evidence_id": f"route:{plain_grant.attempt_id}:{step.step_id}",
                "task_id": plain_grant.task_id,
                "step_id": step.step_id,
                "attempt_id": plain_grant.attempt_id,
                "capability_grant_hash": plain_grant.grant_hash,
                "requested_route": route_decision.requested_route,
                "effective_route": route_decision.effective_route,
                "execution_kind": route_decision.execution_kind,
                "accepted": route_decision.accepted,
                "failure_reason": route_decision.failure_reason,
                "fallback_or_replan": "none",
                "artifact_ref_ids": [],
                "quality_report_hashes": [],
                "terminal_status": "dispatching" if route_decision.accepted else "route_rejected",
            }
            self.context.route_evidence_by_step.setdefault(step.step_id, []).append(route_evidence)
            if not route_decision.accepted:
                raise AdaptiveDispatchError(f"route_rejected:{route_decision.failure_reason}")
            execution_kind = self._validate_dispatch(
                envelope,
                approved_plan,
                step,
                plain_grant,
                grant,
                runtime_identity,
            )
            if execution_kind.value != route_decision.execution_kind:
                route_evidence.update({
                    "accepted": False,
                    "terminal_status": "route_rejected",
                    "failure_reason": "effective_route_implementation_mismatch",
                })
                raise AdaptiveDispatchError("route_rejected:effective_route_implementation_mismatch")
            if bound_handler is not None:
                # C1 is deliberately a Runtime-owned branch before the
                # provider candidate call.  Only a fully validated procedure
                # selection may take it; ordinary ASSIST inputs continue to
                # the provider handler unchanged.
                memory_inputs = self._memory_inputs_for_step(
                    step=step,
                    grant=plain_grant,
                )
                replay_recipe, replay_memory_id = self._validated_recipe(
                    memory_inputs,
                    execution_kind=execution_kind.value,
                    capability_id=step.capability_id,
                    output_contract_version=plain_grant.output_contract_version,
                )
                if any(
                    item.get("replay_class") == ReplayClass.VALIDATED_REPLAY.value
                    for item in memory_inputs
                ) and replay_recipe is None:
                    raise AdaptiveDispatchError("validated_replay_recipe_match_missing")
                if replay_recipe is not None and replay_memory_id:
                    self._record_replay_observation(
                        bound_grant=grant,
                        step=step,
                        memory_input=next(
                            item for item in memory_inputs
                            if str(item.get("ref_id", "")) == replay_memory_id
                        ),
                        observation_kind="provider_invocation",
                        provider_invocation_status="not_started",
                        recipe_step_status="skipped_generation",
                        artifact_restore_status="not_applicable",
                        reason="validated_procedure_reuse_provider_bypass",
                        skip_evidence={
                            "status": "observed",
                            "recipe_hash": str(replay_recipe.get("recipe_hash", ""))
                            or str(
                                next(
                                    item.get("execution_recipe_hash", "")
                                    for item in memory_inputs
                                    if str(item.get("ref_id", "")) == replay_memory_id
                                )
                            ),
                            "generation_boundary": "skipped",
                            "provider_boundary": "skipped",
                        },
                    )
                    if execution_kind == ExecutionKind.TRANSFORM_DSL:
                        result = self._dispatch_transform_dsl(
                            envelope,
                            approved_plan,
                            step,
                            plain_grant,
                            attempt_workspace,
                        )
                        return replace(
                            result,
                            metrics={
                                **result.metrics,
                                "provider_invocation_not_started_count": 1.0,
                            },
                        )
                    if execution_kind == ExecutionKind.LLM_BOUNDED_PYTHON:
                        result = self._dispatch_llm_python(
                            envelope,
                            approved_plan,
                            step,
                            plain_grant,
                            attempt_workspace,
                        )
                        return replace(
                            result,
                            metrics={
                                **result.metrics,
                                "provider_invocation_not_started_count": 1.0,
                            },
                        )
                return self._dispatch_bound_provider(
                    handler=bound_handler,
                    envelope=envelope,
                    approved_plan=approved_plan,
                    step=step,
                    bound_grant=grant,
                    attempt_workspace=attempt_workspace,
                    runtime_identity=runtime_identity,
                    state_access_authority=state_access_authority,
                )
            if execution_kind == ExecutionKind.RETRIEVAL_ADAPTER:
                return self._dispatch_retrieval(
                    envelope,
                    approved_plan,
                    step,
                    plain_grant,
                    attempt_workspace,
                    runtime_identity=runtime_identity,
                    execution_binding_hash=grant.execution_binding_hash,
                    bound_grant=grant,
                    state_access_authority=state_access_authority,
                )
            handler = self._handlers[execution_kind]
            return handler(envelope, approved_plan, step, plain_grant, attempt_workspace)
        except (AdaptiveDispatchError, ValueError) as exc:
            for route_row in reversed(
                self.context.route_evidence_by_step.get(step.step_id, ())
            ):
                if str(route_row.get("attempt_id", "")) == plain_grant.attempt_id:
                    route_row["terminal_status"] = (
                        "route_rejected"
                        if str(exc).startswith("route_rejected:")
                        else "runtime_fail"
                    )
                    route_row["failure_reason"] = str(exc) or type(exc).__name__
                    break
            return AdaptiveStepResult(
                grant_hash=plain_grant.grant_hash,
                success=False,
                attempt_id=plain_grant.attempt_id,
                error_code=str(exc) or type(exc).__name__,
            )

    def _record_replay_observation(
        self,
        *,
        bound_grant: BoundCapabilityGrant,
        step: PlanStepProposal,
        memory_input: dict[str, object],
        observation_kind: str,
        provider_invocation_status: str,
        recipe_step_status: str,
        artifact_restore_status: str,
        reason: str,
        skip_evidence: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Record a Runtime-owned, row-local execution observation.

        This projection is intentionally written at the dispatch boundary,
        before any provider handler is callable.  It carries existing
        identity/receipt hashes but owns no policy, admission, or settlement
        authority.
        """
        grant = bound_grant.grant
        memory_id = str(memory_input.get("ref_id", ""))
        observation = {
            "schema_version": "statebus.g5c.replay_observation.v1",
            "observation_id": f"replay-observation:{grant.attempt_id}:{memory_id}:{observation_kind}",
            "status": "observed",
            "observation_kind": observation_kind,
            "provider_invocation_status": provider_invocation_status,
            "recipe_step_status": recipe_step_status,
            "skip_evidence": dict(skip_evidence or {}),
            "artifact_restore_status": artifact_restore_status,
            "runtime_task_id": grant.task_id,
            "run_id": self.context.runtime_identity.run_id if self.context.runtime_identity else "",
            "session_id": grant.session_id,
            "step_id": step.step_id,
            "attempt_id": grant.attempt_id,
            "execution_binding_hash": bound_grant.execution_binding_hash,
            "capability_grant_hash": grant.grant_hash,
            "memory_id": memory_id,
            "memory_commit_hash": str(memory_input.get("memory_commit_hash", "")),
            "memory_admission_receipt_hash": str(memory_input.get("memory_admission_receipt_hash", "")),
            "replay_eligibility_receipt_hash": str(memory_input.get("replay_eligibility_receipt_hash", "")),
            "source_artifact_id": str(
                dict(memory_input.get("artifact_lineage", {})).get("artifact_ref_id", "")
            ),
            "source_artifact_blob_hash": str(
                dict(memory_input.get("artifact_lineage", {})).get("artifact_hash", "")
            ),
            "recipe_hash": str(memory_input.get("execution_recipe_hash", "")),
            "provider_id": bound_grant.provider_id,
            "provider_version": bound_grant.provider_version,
            "invocation_id": "",
            "attempt_result_admission_receipt_hash": "",
            "baseline_pair_key": "",
            "created_at_ns": time.time_ns(),
            "reason": reason,
        }
        self.context.replay_observations.append(observation)
        return observation

    def _dispatch_bound_provider(
        self,
        *,
        handler: BoundProviderHandler,
        envelope: AdaptiveTaskEnvelope,
        approved_plan: ApprovedPlan,
        step: PlanStepProposal,
        bound_grant: BoundCapabilityGrant,
        attempt_workspace: Path,
        runtime_identity: RuntimeIdentity,
        state_access_authority: "RuntimeStateAccessAuthority | None",
    ) -> "AdaptiveStepResult":
        from statebus.runtime.adaptive_runtime import AdaptiveStepResult

        binding = bound_grant.execution_binding
        descriptor = self.context.registry.get(step.capability_id)
        provider_registry = self.context.provider_registry
        if provider_registry is None:
            provider_registry = ExecutionProviderRegistry.from_legacy_capability_registry(
                self.context.registry
            )
        try:
            provider_registry.resolve_bound(binding=binding)
        except ProviderBindingError as exc:
            code = str(exc)
            if step.role == "planner" and code in {
                "bound_provider_snapshot_missing",
                "provider_binding_not_registered",
            }:
                code = "planner_binding_mismatch"
            raise AdaptiveDispatchError(code) from exc
        role = step.role
        if role not in {"planner", "retriever", "executor", "summarizer"}:
            raise AdaptiveDispatchError("provider_role_not_supported")
        planner_handoff = None
        if role == "retriever":
            planner_refs = tuple(
                ref_id for ref_id in bound_grant.grant.input_ref_ids
                if ref_id.startswith("plan-output:")
            )
            if len(planner_refs) != 1 or planner_refs[0] not in self.context.planner_handoffs:
                raise AdaptiveDispatchError("planner_handoff_ref_missing")
            planner_handoff = self.context.planner_handoffs[planner_refs[0]]
        verified_input_payloads: list[dict[str, object]] = []
        for ref_id in bound_grant.grant.input_ref_ids:
            if ref_id in self.context.evidence_packs:
                evidence = self._verified_evidence_pack(ref_id, bound_grant.grant)
                if evidence is not None:
                    verified_input_payloads.append({
                        "ref_id": ref_id,
                        "kind": "canonical_evidence_pack",
                        "payload": evidence.canonical_payload(),
                    })
            elif ref_id in self.context.artifacts:
                stored = self.context.artifacts[ref_id]
                if not self._artifact_in_grant_scope(stored, bound_grant.grant):
                    raise AdaptiveDispatchError("provider_input_artifact_not_verified")
                verified_input_payloads.append({
                    "ref_id": ref_id,
                    "kind": "execution_artifact",
                    "payload": {
                        "rows": [dict(row) for row in self._read_verified_artifact_rows(stored)],
                        # Provenance is a Runtime-owned projection of the
                        # verified artifact, not provider-authored metadata.
                        "provenance_item_ids": list(stored.provenance_item_ids),
                    },
                })
        role_context = RoleProviderContext(
            role=role,
            input_contract_version=descriptor.input_contract_version,
            output_contract_version=descriptor.output_contract_version,
            mechanism_kind=binding.selected_implementation_kind,
            verified_input_refs=tuple(bound_grant.grant.input_ref_ids),
            planner_handoff=planner_handoff,
            canonical_task_spec=self.context.canonical_task_spec,
            verified_input_payloads=tuple(verified_input_payloads),
        )
        request = ProviderRequest(
            envelope=envelope,
            approved_plan=approved_plan,
            step=step,
            bound_grant=bound_grant,
            runtime_identity=runtime_identity,
            attempt_workspace=attempt_workspace,
            provider_input_refs=tuple(bound_grant.grant.input_ref_ids),
            role_context=role_context,
            state_reader=None,
        )
        if self.context.provider_state_reader_factory is not None:
            request = replace(
                request,
                state_reader=self.context.provider_state_reader_factory(request),
            )
        try:
            with self._measure_phase("provider_invocation", bound_grant.grant):
                raw_candidate = handler(request)
        except BaseException as exc:
            classified = _classify_provider_exception(role, exc)
            if classified is None:
                raise
            error_code, timed_out, retryable = classified
            return AdaptiveStepResult(
                grant_hash=bound_grant.grant.grant_hash,
                success=False,
                attempt_id=bound_grant.grant.attempt_id,
                error_code=error_code,
                retryable=retryable,
                timed_out=timed_out,
                metrics={
                    "provider_invocation_error_count": 1.0,
                    "provider_timeout_count": 1.0 if timed_out else 0.0,
                },
            )
        if not isinstance(raw_candidate, ProviderCandidate):
            raise AdaptiveDispatchError("provider_candidate_payload_type_mismatch")
        candidate = detach_provider_candidate(raw_candidate)
        # Invocation evidence is a Runtime projection of the detached return
        # value.  Tests/adapters may pre-seed it to assert provenance; a
        # missing projection is filled once, never overwritten by the provider.
        if (
            candidate.candidate_kind == "executor_program"
            and isinstance(candidate.payload, GeneratedCodeCandidate)
        ):
            self.context.provider_invocation_evidence.setdefault(
                bound_grant.grant.grant_hash,
                {
                    "request_hash": candidate.payload.request_hash,
                    "source_hash": candidate.payload.source_hash,
                    "raw_response_hash": candidate.payload.raw_response_hash,
                },
            )
        expected_kind = {
            "planner": "planner_handoff",
            "retriever": "retrieval_request",
            "executor": "executor_program",
            "summarizer": "summary_claim_set",
        }[role]
        if candidate.candidate_kind not in {expected_kind, "failure", "diagnostic"}:
            raise AdaptiveDispatchError("provider_candidate_payload_type_mismatch")
        review_binding = self.context.executor_candidate_review
        review_candidate = (
            candidate.candidate_kind == "executor_program"
            or (
                candidate.candidate_kind == "failure"
                and candidate.error_code == "model_assist_insufficient_evidence"
            )
        )
        if (
            role == "executor"
            and review_candidate
            and self.context.executor_candidate_review_enabled
            and review_binding is not None
            and envelope.domain_pack_id == review_binding.suite_id
            and step.capability_id == review_binding.capability_id
        ):
            decision = review_binding.review(request, candidate)
            if not isinstance(decision, ExecutorCandidateReviewDecision):
                raise AdaptiveDispatchError("executor_candidate_review_decision_invalid")
            review_record = {
                "suite_id": review_binding.suite_id,
                "capability_id": review_binding.capability_id,
                "step_id": step.step_id,
                "attempt_id": bound_grant.grant.attempt_id,
                "grant_hash": bound_grant.grant.grant_hash,
                "candidate_kind": candidate.candidate_kind,
                "candidate_diagnostics": [[key, value] for key, value in candidate.diagnostics],
                "action": decision.action,
                "reason": decision.reason,
                "diagnostics": [[key, value] for key, value in decision.diagnostics],
            }
            self.context.executor_candidate_review_records.append(review_record)
            if self.context.telemetry is not None:
                self.context.telemetry.emit(TelemetryEvent.create(
                    trace_id=runtime_identity.trace_id,
                    task_id=bound_grant.grant.task_id,
                    step_id=step.step_id,
                    attempt_id=bound_grant.grant.attempt_id,
                    event_type="EXECUTOR_CANDIDATE_REVIEW",
                    role="runtime_driver",
                    payload={
                        "action": decision.action,
                        "reason": decision.reason,
                        "grant_hash": bound_grant.grant.grant_hash,
                    },
                    metrics={"executor_candidate_review_count": 1.0},
                ))
            if decision.action == "request_evidence_recheck":
                return AdaptiveStepResult(
                    grant_hash=bound_grant.grant.grant_hash,
                    success=False,
                    attempt_id=bound_grant.grant.attempt_id,
                    error_code="model_assist_review_required",
                )
            if decision.action == "abstain":
                return AdaptiveStepResult(
                    grant_hash=bound_grant.grant.grant_hash,
                    success=False,
                    attempt_id=bound_grant.grant.attempt_id,
                    error_code="need_more_evidence",
                )
        if candidate.candidate_kind == "failure":
            timed_out = candidate.error_code in {
                "planner_timeout",
                "retriever_timeout",
                "executor_timeout",
                "summarizer_timeout",
            }
            return AdaptiveStepResult(
                grant_hash=bound_grant.grant.grant_hash,
                success=False,
                attempt_id=bound_grant.grant.attempt_id,
                error_code=candidate.error_code,
                retryable=candidate.retryable,
                timed_out=timed_out,
            )
        if candidate.candidate_kind == "diagnostic":
            return AdaptiveStepResult(
                grant_hash=bound_grant.grant.grant_hash,
                success=False,
                attempt_id=bound_grant.grant.attempt_id,
                error_code="provider_diagnostic_only",
            )
        if candidate.candidate_kind == "planner_handoff":
            assert isinstance(candidate.payload, PlannerHandoff)
            handoff = candidate.payload
            if (
                handoff.task_id != bound_grant.grant.task_id
                or handoff.canonical_task_spec_hash != envelope.canonical_task_spec_hash
                or not handoff.retrieval_objective
                or any(str(key).lower().startswith("expected_") for key in handoff.planner_scope_payload)
                or any(token in str(handoff.canonical_payload()).lower() for token in ("gold", "future_round"))
            ):
                raise AdaptiveDispatchError("planner_candidate_invalid")
            ref_id = f"plan-output:{handoff.task_id}:{bound_grant.grant.attempt_id}"
            self.context.planner_handoffs[ref_id] = handoff
            return AdaptiveStepResult(
                grant_hash=bound_grant.grant.grant_hash,
                success=True,
                attempt_id=bound_grant.grant.attempt_id,
                output_refs=(ref_id,),
                output_ref_kinds=("planner_handoff",),
                metrics={"planner_provider_invocation_count": 1.0},
            )
        payload = candidate.payload
        if candidate.candidate_kind == "retrieval_request":
            assert isinstance(payload, EvidenceRequest)
            if payload.task_id != bound_grant.grant.task_id or payload.step_id != step.step_id:
                raise AdaptiveDispatchError("provider_candidate_scope_mismatch")
            return self._dispatch_retrieval(
                envelope,
                approved_plan,
                step,
                bound_grant.grant,
                attempt_workspace,
                runtime_identity=runtime_identity,
                execution_binding_hash=bound_grant.execution_binding_hash,
                bound_grant=bound_grant,
                state_access_authority=state_access_authority,
                candidate_request=payload,
            )
        if candidate.candidate_kind == "executor_program":
            if isinstance(payload, TransformProgram):
                return self._dispatch_transform_dsl(
                    envelope,
                    approved_plan,
                    step,
                    bound_grant.grant,
                    attempt_workspace,
                    candidate_program=payload,
                )
            if isinstance(payload, GeneratedCodeCandidate):
                evidence = self.context.provider_invocation_evidence.get(
                    bound_grant.grant.grant_hash
                )
                if evidence is None:
                    raise AdaptiveDispatchError("provider_candidate_hash_mismatch")
                if (
                    evidence.get("request_hash") != payload.request_hash
                    or evidence.get("source_hash") != payload.source_hash
                    or evidence.get("raw_response_hash") != payload.raw_response_hash
                    or sha256_digest(payload.source.encode("utf-8")) != payload.source_hash
                ):
                    raise AdaptiveDispatchError("provider_candidate_hash_mismatch")
                # The provider candidate is already the generated program.  The
                # dispatcher owns the one CodeAct execution, so pass the
                # detached source directly into the existing CodeAct seam rather
                # than invoking the provider/model a second time.
                if not envelope.allow_llm_python or envelope.risk_class != RiskClass.BOUNDED_CODE:
                    raise AdaptiveDispatchError("llm_python_not_program_enabled")
                return self._dispatch_llm_python(
                    envelope,
                    approved_plan,
                    step,
                    bound_grant.grant,
                    attempt_workspace,
                    source_override=payload.source,
                )
            raise AdaptiveDispatchError("provider_candidate_payload_type_mismatch")
        if candidate.candidate_kind == "summary_claim_set":
            assert isinstance(payload, ClaimSet)
            if payload.task_id != bound_grant.grant.task_id:
                raise AdaptiveDispatchError("provider_candidate_scope_mismatch")
            return self._dispatch_summarizer(
                step,
                bound_grant.grant,
                attempt_workspace,
                candidate_claim_set=payload,
            )
        raise AdaptiveDispatchError("provider_candidate_kind_invalid")

    def _dispatch_retrieval(
        self,
        envelope: AdaptiveTaskEnvelope,
        approved_plan: ApprovedPlan,
        step: PlanStepProposal,
        grant: CapabilityGrant,
        attempt_workspace: Path,
        *,
        runtime_identity: RuntimeIdentity,
        execution_binding_hash: str,
        bound_grant: BoundCapabilityGrant,
        state_access_authority: "RuntimeStateAccessAuthority | None",
        candidate_request: "EvidenceRequest | None" = None,
    ) -> "AdaptiveStepResult":
        from statebus.runtime.adaptive_runtime import AdaptiveStepResult

        if self.context.retrieval_adapter is None or (
            candidate_request is None and self.context.retrieval_request_factory is None
        ):
            raise AdaptiveDispatchError("retrieval_handler_not_registered")
        request = candidate_request or self.context.retrieval_request_factory(step, grant)
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
                runtime_identity=runtime_identity,
                execution_binding_hash=execution_binding_hash,
                bound_grant=bound_grant,
                state_access_authority=state_access_authority,
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
        # The dispatcher returns the physical SemanticState lifecycle events
        # below.  Those events are the sole telemetry authority for the
        # publish/transfer/consume headline counters; copying the same
        # counters into STEP_COMPLETED metrics would make TelemetryEmitter's
        # additive aggregation count one physical operation twice.
        step_metrics = {
            key: value
            for key, value in state_metrics.items()
            if key not in {
                "semantic_state_publish_count",
                "semantic_state_transfer_count",
                "semantic_state_consume_count",
            }
        }
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
                **step_metrics,
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
        runtime_identity: RuntimeIdentity,
        execution_binding_hash: str,
        bound_grant: BoundCapabilityGrant,
        state_access_authority: "RuntimeStateAccessAuthority | None",
    ) -> tuple[
        AdaptiveRetrievalResult,
        tuple[object, ...],
        tuple[dict[str, object], ...],
        dict[str, float],
    ]:
        from statebus.control import (
            ControlHeader,
            ControlResponseAdmissionError,
            ErrorResult,
            EventType,
            ExecRequest,
            RefHandle,
            SubprocessExecutorTransport,
            SuccessResult,
        )
        from statebus.memory import MemoryQuery
        from statebus.retrieval import apply_semantic_state_selection
        from statebus.runtime.state_consumption import build_state_consumption_record
        from statebus.runtime.state_consumption import (
            build_semantic_consumer_receipt,
            build_state_pin_receipt,
            build_state_publication_receipt,
        )

        mode = str(self.context.semantic_state_mode).strip()
        if mode not in _SEMANTIC_STATE_MODES:
            raise AdaptiveDispatchError(f"semantic_state_mode_invalid:{mode}")
        if self.context.state_store is None or self.context.memory_store is None:
            raise AdaptiveDispatchError("adaptive_product_state_infrastructure_missing")
        if mode != "off" and self.context.socket_path is None:
            raise AdaptiveDispatchError("adaptive_product_control_socket_missing")
        if mode != "off" and state_access_authority is None:
            raise AdaptiveDispatchError("state_access_authority_required")

        semantic_requested = bool(
            {str(value).strip() for value in result.request.evidence_types}
            & {"semantic", "semantic_chunk", "semantic_context", "citation", "narrative"}
        )
        selected_bundles = []
        records = []
        data_plane_events: list[dict[str, object]] = []
        transfer_count = 0
        publish_count = 0
        consume_count = 0
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
            # ``off`` is a true producer/consumer disable: the retriever's
            # typed result remains the input, with no state publication.
            if mode == "off":
                selected_bundles.append(bundle)
                continue
            state_id = (
                f"semantic-{grant.task_id}-{grant.step_id}-{grant.attempt_id}-{index}"
                .replace(":", "-")
                .replace("/", "-")
            )
            publication = state_access_authority.publish_dense_semantic_state(
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
            self.context.state_publication_receipts[state_id] = build_state_publication_receipt(
                publication=publication,
                runtime_identity=runtime_identity,
                producer_grant=bound_grant,
                producer_binding_id=bound_grant.execution_binding.binding_id,
                execution_binding_hash=execution_binding_hash,
                cache_epoch=f"{runtime_identity.run_id}:{grant.attempt_id}",
            )
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
            # ``consumer_off`` is the negative control for the matched
            # ablation.  It publishes a real state reference and receipt, but
            # deliberately does not issue a read grant or start a worker.
            # Mainline cleanup still owns the eventual release/reclaim.
            if mode == "consumer_off":
                selected_bundles.append(bundle)
                publish_count += 1
                continue
            entries = bundle.semantic_state_manifest.entries
            configured_top_k = self.context.semantic_state_executor_top_k
            top_k = (
                max(1, min(len(entries), int(configured_top_k)))
                if configured_top_k is not None
                else max(1, min(len(entries), max(len(bundle.evidence_pack.semantic_contexts), 1)))
            )
            configured_budget = self.context.semantic_state_executor_budget_bytes
            if configured_budget is not None:
                evidence_budget_bytes = max(int(configured_budget), 0)
            else:
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
            invocation_id = f"invocation-{uuid4().hex}"
            worker_access_grant = state_access_authority.issue_read(
                ref=publication.ref,
                authority_basis=STATE_ACCESS_AUTHORITY_RUNTIME_INTERMEDIATE,
                consumer_role="executor",
                physical_invocation_id=invocation_id,
            )
            request = ExecRequest(
                header=ControlHeader(
                    trace_id=runtime_identity.trace_id,
                    task_id=runtime_identity.runtime_task_id,
                    step_id=grant.step_id,
                    attempt_id=grant.attempt_id,
                    target_role="executor",
                    timeout_ms=min(max(grant.max_runtime_ms, 5_000), 30_000),
                    event_type=EventType.REQ_EXEC,
                    schema_version=CONTROL_PLANE_SCHEMA_VERSION,
                    run_id=runtime_identity.run_id,
                    session_id=runtime_identity.session_id,
                    invocation_id=invocation_id,
                    execution_binding_hash=execution_binding_hash,
                    capability_grant_hash=grant.grant_hash,
                ),
                state_refs=(RefHandle(ref_id=state_id, ref_kind="semantic_state"),),
                state_access_grants=(worker_access_grant,),
                consumer_provider_id=bound_grant.provider_id,
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
            transport = SubprocessExecutorTransport(
                socket_path=self.context.socket_path.with_name(
                    f"{self.context.socket_path.stem}-semantic-{index}{self.context.socket_path.suffix}"
                ),
                timeout_s=max(request.header.timeout_ms / 1000.0, 5.0),
            )
            worker_pin = state_access_authority.acquire_pin(
                store=self.context.state_store,
                ref=publication.ref,
                access_grant=worker_access_grant,
                consumer_role="executor",
                physical_invocation_id=invocation_id,
            )
            pin_receipts = [build_state_pin_receipt(pin=worker_pin, phase="downstream_use", status="acquired")]
            try:
                memfd_refs = None
                if (
                    publication.handle.storage_kind == StorageKind.MEMFD
                    and publication.handle.memfd_fd is not None
                ):
                    memfd_refs = {
                        state_id: (
                            publication.handle.memfd_fd,
                            publication.handle.size_bytes,
                        )
                    }
                response = transport.execute(request, memfd_refs=memfd_refs)
            except ControlResponseAdmissionError as exc:
                self.context.control_response_admissions[state_id] = exc.receipts
                state_access_authority.unpin(
                    store=self.context.state_store,
                    pin_id=worker_pin.pin_id,
                )
                pin_receipts.append(build_state_pin_receipt(
                    pin=worker_pin,
                    phase="response_admission",
                    status="released_on_admission_error",
                    released_at_ns=time.time_ns(),
                ))
                self.context.state_pin_receipts[state_id] = tuple(pin_receipts)
                raise AdaptiveDispatchError(str(exc)) from exc
            receipts = transport.last_admission_receipts
            self.context.control_response_admissions[state_id] = receipts
            lifecycle_timestamps = self.context.state_lifecycle_timestamps.setdefault(state_id, {})
            lifecycle_timestamps["response_admitted_at_ns"] = time.time_ns()
            from statebus.runtime.supervisor import LifecycleOrigin

            origin_by_control_origin = {
                "NATIVE_TYPED_WORKER": LifecycleOrigin.WORKER_OBSERVED.value,
                "ADAPTER_DERIVED": LifecycleOrigin.ADAPTER_DERIVED.value,
                "LEGACY_COMPATIBILITY": LifecycleOrigin.ADAPTER_DERIVED.value,
            }
            self.context.physical_lifecycle_observations.extend(
                {
                    **receipt.canonical_payload(),
                    "physical_invocation_scope": {
                        "task_id": grant.task_id,
                        "session_id": grant.session_id,
                        "step_id": grant.step_id,
                        "attempt_id": grant.attempt_id,
                        "invocation_id": receipt.invocation_id,
                    },
                    "runtime_origin": origin_by_control_origin.get(
                        receipt.origin.value,
                        LifecycleOrigin.ADAPTER_DERIVED.value,
                    ),
                    "outer_semantic_step_mutated": False,
                }
                for receipt in receipts
            )
            terminal_receipts = tuple(receipt for receipt in receipts if receipt.terminal)
            if len(terminal_receipts) != 1 or not terminal_receipts[0].admitted:
                state_access_authority.unpin(store=self.context.state_store, pin_id=worker_pin.pin_id)
                pin_receipts.append(build_state_pin_receipt(
                    pin=worker_pin, phase="response_admission", status="released_on_admission_failure", released_at_ns=time.time_ns()
                ))
                raise AdaptiveDispatchError("semantic_state_response_admission_missing")
            if isinstance(response, ErrorResult):
                state_access_authority.unpin(store=self.context.state_store, pin_id=worker_pin.pin_id)
                pin_receipts.append(build_state_pin_receipt(
                    pin=worker_pin, phase="response_admission", status="released_on_worker_error", released_at_ns=time.time_ns()
                ))
                raise AdaptiveDispatchError(
                    f"semantic_state_consume_failed:{response.error_code}:{response.error_detail}"
                )
            if not isinstance(response, SuccessResult):
                state_access_authority.unpin(store=self.context.state_store, pin_id=worker_pin.pin_id)
                pin_receipts.append(build_state_pin_receipt(
                    pin=worker_pin, phase="response_admission", status="released_on_invalid_result", released_at_ns=time.time_ns()
                ))
                raise AdaptiveDispatchError("semantic_state_consumer_result_invalid")
            if response.consumed_state_ref_id != state_id:
                state_access_authority.unpin(store=self.context.state_store, pin_id=worker_pin.pin_id)
                pin_receipts.append(build_state_pin_receipt(
                    pin=worker_pin, phase="response_admission", status="released_on_ref_mismatch", released_at_ns=time.time_ns()
                ))
                raise AdaptiveDispatchError("semantic_state_consumer_ref_mismatch")
            if response.consumer_pid <= 0 or response.consumer_pid == response.producer_pid:
                state_access_authority.unpin(store=self.context.state_store, pin_id=worker_pin.pin_id)
                pin_receipts.append(build_state_pin_receipt(
                    pin=worker_pin, phase="response_admission", status="released_on_topology_failure", released_at_ns=time.time_ns()
                ))
                raise AdaptiveDispatchError("semantic_state_consumer_not_cross_process")
            selected = apply_semantic_state_selection(
                bundle,
                selected_candidate_ids=response.selected_candidate_ids,
                selected_scores=response.selected_scores,
                consumer_pid=response.consumer_pid,
            )
            # Keep a Runtime-owned read grant for the downstream input
            # projection. The worker already performed the canonical matrix
            # read; Runtime reuses the producer's immutable query embedding
            # rather than hydrating the state a second time.
            local_access_grant = state_access_authority.issue_read(
                ref=publication.ref,
                authority_basis=STATE_ACCESS_AUTHORITY_RUNTIME_INTERMEDIATE,
                consumer_role="runtime",
            )
            runtime_pin = state_access_authority.acquire_pin(
                store=self.context.state_store,
                ref=publication.ref,
                access_grant=local_access_grant,
                consumer_role="runtime",
            )
            pin_receipts.append(build_state_pin_receipt(
                pin=runtime_pin, phase="downstream_projection", status="acquired"
            ))
            self.context.state_access_grants[state_id] = (
                worker_access_grant,
                local_access_grant,
            )
            selected = replace(
                selected,
                memory_query_embedding=bundle.query_embedding,
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
            # Compare the same decision surface on both sides. A candidate
            # pool hash and an evidence-pack hash differ by construction and
            # cannot establish an effect. Scores/PIDs/provenance are audit
            # metadata, not a change to the ordered evidence selection.
            before_selected_ids = tuple(item.item_id for item in bundle.evidence_pack.semantic_contexts)
            input_surface_hash = sha256_digest({"selected_candidate_ids": before_selected_ids})
            output_surface_hash = sha256_digest({"selected_candidate_ids": response.selected_candidate_ids})
            records.append(build_state_consumption_record(
                state_ref_id=state_id,
                consumer_role="executor",
                consumer_step_id=step.step_id,
                operation="cosine_topk_budget_pruning",
                read_field_ids=tuple(
                    f"row:{row_index}" for row_index in (0, *response.selected_row_indices)
                ),
                input_decision_surface_hash=input_surface_hash,
                output_decision_surface_hash=output_surface_hash,
                selected_ids=response.selected_candidate_ids,
                downstream_ref_ids=(downstream_ref_id,),
            ))
            run_start = next(
                (message for message in transport.last_response_messages if type(message).__name__ == "RunStart"),
                None,
            )
            terminal_admission = terminal_receipts[0]
            descriptor_identity = {
                "ref_id": publication.ref.state_id,
                "state_ref_id": publication.ref.state_id,
                "state_identity_hash": publication.ref.state_identity_hash,
                "storage_kind": publication.handle.storage_kind.value,
                "size_bytes": publication.handle.size_bytes,
                "shape": list(publication.contract.shape),
                "dtype": publication.contract.dtype,
                "blob_hash": publication.contract.blob_hash,
                "manifest_id": publication.contract.hydrate_manifest_id,
                "manifest_hash": publication.contract.hydrate_manifest_hash,
                "encoder_hash": publication.contract.encoder_signature,
                "encoder_signature": publication.contract.encoder_signature,
                "cache_epoch": f"{runtime_identity.run_id}:{grant.attempt_id}",
                "binding_id": bound_grant.execution_binding.binding_id,
                "handle_identity": publication.handle.metadata_payload(),
                "socket_session_identity": {
                    "socket_path": str(transport.last_exchange_audit.socket_path_effective)
                    if transport.last_exchange_audit else "",
                    "session_id": runtime_identity.session_id,
                },
            }
            self.context.semantic_consumer_receipts[state_id] = build_semantic_consumer_receipt(
                publication=publication,
                response=response,
                runtime_identity=runtime_identity,
                grant=grant,
                state_access_grant_hash=worker_access_grant.access_grant_hash,
                execution_binding_hash=execution_binding_hash,
                pin_id=worker_pin.pin_id,
                downstream_ref_ids=(downstream_ref_id,),
                input_decision_surface_hash=input_surface_hash,
                output_decision_surface_hash=output_surface_hash,
                response_admission_hash=sha256_digest(terminal_admission.canonical_payload()),
                descriptor_identity=descriptor_identity,
                read_started_at_ns=int(getattr(run_start, "started_at_ns", 0)),
                read_completed_at_ns=int(getattr(response, "completed_at_ns", 0)),
            )
            downstream_effect_completed_at_ns = time.time_ns()
            lifecycle_timestamps["downstream_effect_completed_at_ns"] = downstream_effect_completed_at_ns
            self.context.downstream_effects[state_id] = {
                "state_ref_id": state_id,
                "downstream_ref_ids": [downstream_ref_id],
                "before_decision_surface_hash": input_surface_hash,
                "after_decision_surface_hash": output_surface_hash,
                "effect_scope": "ordered_semantic_candidate_selection_not_quality_or_causal_gain",
                "before_selected_candidate_ids": list(before_selected_ids),
                "after_selected_candidate_ids": list(response.selected_candidate_ids),
                "candidate_pool_hash": bundle.candidate_pool.candidate_surface_hash,
                "downstream_input_hash": sha256_digest(selected.evidence_pack.canonical_payload()),
                "behavioral_effect": self.context.semantic_consumer_receipts[state_id]["behavioral_effect"],
                "response_admitted": True,
                "completed_at_ns": downstream_effect_completed_at_ns,
            }
            state_access_authority.unpin(store=self.context.state_store, pin_id=worker_pin.pin_id)
            lifecycle_timestamps["worker_pin_released_at_ns"] = time.time_ns()
            pin_receipts.append(build_state_pin_receipt(
                pin=worker_pin,
                phase="downstream_use",
                status="released_after_downstream_effect",
                released_at_ns=lifecycle_timestamps["worker_pin_released_at_ns"],
            ))
            state_access_authority.unpin(store=self.context.state_store, pin_id=runtime_pin.pin_id)
            lifecycle_timestamps["runtime_pin_released_at_ns"] = time.time_ns()
            pin_receipts.append(build_state_pin_receipt(
                pin=runtime_pin,
                phase="downstream_projection",
                status="released_after_input_projection",
                released_at_ns=lifecycle_timestamps["runtime_pin_released_at_ns"],
            ))
            self.context.state_pin_receipts[state_id] = tuple(pin_receipts)
            publish_count += 1
            consume_count += 1
            transfer_count += int(response.consumer_pid != response.producer_pid)
            selected_count += len(response.selected_candidate_ids)
            selected_bytes += int(response.selected_evidence_bytes)

        if not selected_bundles:
            selected_bundles = list(result.retrieval_bundles)
        self.context.component_activation_receipts["semantic_state"] = {
            "component": "semantic_state",
            "requested_mode": mode,
            "effective_mode": mode if semantic_requested else "not_applicable",
            "producer_active": bool(publish_count),
            "consumer_active": bool(consume_count),
            "publish_count": int(publish_count),
            "consume_count": int(consume_count),
            "transfer_count": int(transfer_count),
            "disable_reason": (
                "requested_off"
                if mode == "off"
                else "consumer_disabled_negative_control"
                if mode == "consumer_off"
                else ""
                if consume_count
                else "no_semantic_state_payload"
            ),
        }
        selected_pack = stable_fan_in_evidence_packs(
            task_id=result.request.task_id,
            packs=tuple(bundle.evidence_pack for bundle in selected_bundles),
        )
        memory_result = None
        if self.context.memory_query_enabled:
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
            with self._measure_phase("memory_lookup_including_compatibility", grant):
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
        compatibility_decisions = (
            tuple(memory_result.compatibility_decisions)
            if memory_result is not None else ()
        )
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
        source_ranks = memory_result.source_ranks if memory_result is not None else {}
        candidate_memory_ids = (
            memory_result.candidate_pool.candidate_memory_ids
            if memory_result is not None and memory_result.candidate_pool is not None
            else ()
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
                "semantic_state_consume_count": float(consume_count),
                "semantic_state_selected_count": float(selected_count),
                "semantic_state_selected_bytes": float(selected_bytes),
                "raw_evidence_bytes_seen_by_llm": float(raw_evidence_bytes),
                "embedding_encode_count": float(embedding_encode_count),
                "hybrid_memory_query_count": float(memory_result is not None),
                "memory_keyword_candidate_count": float(len(source_ranks.get("keyword", ()))),
                "memory_tag_candidate_count": float(len(source_ranks.get("tags", ()))),
                "memory_vector_candidate_count": float(len(source_ranks.get("vector", ()))),
                "memory_candidate_count": float(len(candidate_memory_ids)),
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
        if not grant.memory_ref_ids:
            return ()
        with self._measure_phase("memory_authorization_and_hydration", grant):
            return self._load_memory_inputs_for_step(step=step, grant=grant)

    def _load_memory_inputs_for_step(
        self, *, step: PlanStepProposal, grant: CapabilityGrant,
    ) -> tuple[dict[str, object], ...]:
        if self.context.memory_store is None:
            raise AdaptiveDispatchError("memory_store_required_for_grant_memory")
        if self.context.runtime_identity is not None and (
            grant.task_id != self.context.runtime_identity.runtime_task_id
            or grant.session_id != self.context.runtime_identity.session_id
        ):
            raise AdaptiveDispatchError("grant_memory_runtime_identity_mismatch")
        if grant.expires_at_ns and time.time_ns() >= grant.expires_at_ns:
            raise AdaptiveDispatchError("grant_memory_expired")
        if self.context.session_manager is not None and self.context.session_manager.active_attempt_id(
            grant.session_id, step.step_id
        ) != grant.attempt_id:
            raise AdaptiveDispatchError("grant_memory_attempt_not_active")
        role_inputs: list[dict[str, object]] = []
        seen: set[str] = set()
        matches_by_id: dict[str, tuple[object, str, object]] = {}
        for retrieval_step_id, result in sorted(self.context.memory_match_results.items()):
            decisions = {
                decision.memory_id: decision
                for decision in getattr(result, "compatibility_decisions", ())
            }
            for match in getattr(result, "matches", ()):
                memory_id = match.memory_ref.memory_id
                decision = decisions.get(memory_id)
                if decision is None:
                    continue
                matches_by_id.setdefault(memory_id, (match, retrieval_step_id, decision))
        eligibility_by_id = {
            receipt.memory_id: receipt
            for receipt in self.context.replay_eligibility_receipts_by_step.get(
                step.step_id, ()
            )
        }
        for memory_id in grant.memory_ref_ids:
            if memory_id in seen:
                continue
            match_data = matches_by_id.get(memory_id)
            if match_data is None:
                raise AdaptiveDispatchError("grant_memory_match_missing")
            match, retrieval_step_id, decision = match_data
            if not decision.policy_approved:
                raise AdaptiveDispatchError("grant_memory_policy_rejected")
            admitted = self.context.memory_store.get_admitted(memory_id)
            if admitted is None:
                raise AdaptiveDispatchError("grant_memory_admission_missing")
            commit, admission_receipt = admitted
            if (
                admission_receipt.memory_id != memory_id
                or admission_receipt.memory_commit_hash != commit.commit_hash
                or str(getattr(admission_receipt.decision, "value", admission_receipt.decision))
                != "ADMITTED"
            ):
                raise AdaptiveDispatchError("grant_memory_admission_mismatch")
            mode = self.context.memory_selection_modes_by_step.get(step.step_id, {}).get(
                memory_id,
                match.replay_class,
            )
            if mode == ReplayClass.VALIDATED_REPLAY:
                eligibility = eligibility_by_id.get(memory_id)
                if (
                    eligibility is None
                    or eligibility.decision != ReplayEligibilityDecision.ELIGIBLE
                    or eligibility.memory_admission_receipt_hash
                    != admission_receipt.receipt_hash
                    or eligibility.consumer_capability_grant_hash != grant.grant_hash
                    or eligibility.consumer_runtime_task_id
                    != (
                        self.context.runtime_identity.runtime_task_id
                        if self.context.runtime_identity is not None
                        else grant.task_id
                    )
                    or eligibility.consumer_session_id != grant.session_id
                    or eligibility.consumer_attempt_id != grant.attempt_id
                    or eligibility.consumer_step_id != step.step_id
                ):
                    raise AdaptiveDispatchError("validated_replay_eligibility_mismatch")
            elif mode == ReplayClass.EXACT_REPLAY:
                mode = ReplayClass.ASSIST
            if mode not in {ReplayClass.ASSIST, ReplayClass.VALIDATED_REPLAY}:
                raise AdaptiveDispatchError("grant_memory_reuse_mode_invalid")
            recipe = commit.memory_ref.metadata.get("execution_recipe")
            recipe_payload = dict(recipe) if isinstance(recipe, dict) else {}
            recipe_hash = str(commit.memory_ref.metadata.get("execution_recipe_hash", ""))
            artifact_verification_receipt_hash = str(
                commit.memory_ref.metadata.get("artifact_verification_receipt_hash", "")
            )
            payload = {
                "ref_id": memory_id,
                "ref_kind": "memory",
                "source_task_id": commit.memory_ref.source_task_id,
                "source_agent": commit.memory_ref.source_agent,
                "summary": commit.memory_ref.summary,
                "tags": list(commit.memory_ref.tags),
                "replay_class": mode.value,
                "compatibility_verdict": decision.verdict.value,
                "compatibility_reasons": list(decision.reasons),
                "artifact_lineage": {
                    "artifact_ref_id": commit.memory_ref.artifact_ref_id,
                    "artifact_hash": commit.created_from_artifact_hash,
                    "manifest_hash": commit.memory_ref.manifest_hash,
                    "artifact_root_id": str(commit.memory_ref.metadata.get("artifact_root_id", "")),
                    "artifact_relpath": str(commit.memory_ref.metadata.get("artifact_relpath", "")),
                    "input_lineage_hashes": list(
                        commit.memory_ref.metadata.get("input_lineage_hashes", ())
                    ),
                },
                "execution_recipe": recipe_payload,
                "execution_recipe_hash": recipe_hash,
                "input_schema_digest": str(commit.memory_ref.metadata.get("input_schema_digest", "")),
                "runtime_signature_hash": str(commit.memory_ref.metadata.get("runtime_signature_hash", "")),
                "validator_digest": str(commit.memory_ref.metadata.get("validator_digest", "")),
                "output_contract_version": str(commit.memory_ref.metadata.get("output_contract_version", "")),
                "artifact_verification_receipt_hash": artifact_verification_receipt_hash,
                "query_source_step_id": retrieval_step_id,
                "consumer_role": step.role,
                "consumer_step_id": step.step_id,
                "grant_hash": grant.grant_hash,
                "memory_commit_hash": commit.commit_hash,
                "memory_admission_receipt_hash": admission_receipt.receipt_hash,
                "replay_eligibility_receipt_hash": (
                    "" if mode != ReplayClass.VALIDATED_REPLAY else eligibility.receipt_hash
                ),
                "query_hash": next(
                    (
                        query.query_hash
                        for query in self.context.memory_queries_by_task.values()
                        if query.query_task_id == grant.task_id
                    ),
                    "",
                ),
            }
            if mode == ReplayClass.VALIDATED_REPLAY:
                if not recipe_payload or not recipe_hash:
                    raise AdaptiveDispatchError("validated_replay_recipe_integrity_missing")
                if sha256_digest(recipe_payload) != recipe_hash:
                    raise AdaptiveDispatchError("validated_replay_recipe_checksum_mismatch")
                if payload["input_schema_digest"] and self.context.input_schema_digest and payload["input_schema_digest"] != self.context.input_schema_digest:
                    raise AdaptiveDispatchError("validated_replay_input_schema_mismatch")
                if payload["runtime_signature_hash"] and self.context.runtime_compatibility_signature and payload["runtime_signature_hash"] != self.context.runtime_compatibility_signature:
                    raise AdaptiveDispatchError("validated_replay_runtime_signature_mismatch")
                if payload["validator_digest"] and self.context.validator_digest and payload["validator_digest"] != self.context.validator_digest:
                    raise AdaptiveDispatchError("validated_replay_validator_digest_mismatch")
                if payload["output_contract_version"] and payload["output_contract_version"] != grant.output_contract_version:
                    raise AdaptiveDispatchError("validated_replay_output_contract_mismatch")
            if not payload["query_hash"]:
                raise AdaptiveDispatchError("grant_memory_query_binding_missing")
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
            recipe_hash = str(memory_input.get("execution_recipe_hash", ""))
            if not recipe_hash or sha256_digest(recipe) != recipe_hash:
                raise AdaptiveDispatchError("validated_replay_recipe_checksum_mismatch")
            return dict(recipe), str(memory_input["ref_id"])
        return None, ""

    @staticmethod
    def _require_validated_recipe_match(
        memory_inputs: tuple[dict[str, object], ...],
        replay_recipe: dict[str, object] | None,
    ) -> None:
        if replay_recipe is None and any(
            item.get("replay_class") == ReplayClass.VALIDATED_REPLAY.value
            for item in memory_inputs
        ):
            raise AdaptiveDispatchError("validated_replay_recipe_match_missing")

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
        grant: CapabilityGrant,
        downstream_ref_ids: tuple[str, ...],
        before_surface_hash: str,
        replay_memory_id: str = "",
        consumed_memory_ids: tuple[str, ...] | None = None,
        after_surface_hash: str = "",
        recipe_step_status: str = "",
        skip_evidence_by_memory_id: dict[str, dict[str, object]] | None = None,
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
                "skipped_provider_call_count": 0.0,
            }
        if consumed_memory_ids is None:
            consumed_memory_ids = self.context.memory_read_observations_by_step.get(
                step.step_id, ()
            )
        consumed_memory_ids = tuple(dict.fromkeys(str(item) for item in consumed_memory_ids))
        input_ids = {str(item.get("ref_id", "")) for item in memory_inputs}
        if not set(consumed_memory_ids).issubset(input_ids):
            raise AdaptiveDispatchError("memory_read_observation_scope_mismatch")
        approved_unused_ids = tuple(sorted(input_ids.difference(consumed_memory_ids)))
        self.context.memory_approved_unused_by_step[step.step_id] = approved_unused_ids
        if not consumed_memory_ids:
            return {
                "memory_consumed_count": 0.0,
                "memory_actual_use_count": 0.0,
                "memory_approved_but_unused_count": float(len(approved_unused_ids)),
                "memory_behavioral_effect_count": 0.0,
                "memory_assist_count": 0.0,
                "validated_replay_count": 0.0,
                "exact_replay_count": 0.0,
                "skipped_step_count": 0.0,
                "skipped_llm_call_count": 0.0,
                "skipped_provider_call_count": 0.0,
            }
        if self.context.session_manager is not None:
            for memory_input in memory_inputs:
                memory_id = str(memory_input.get("ref_id", ""))
                if memory_id not in consumed_memory_ids:
                    continue
                if self.context.session_manager.active_attempt_id(
                    grant.session_id, step.step_id
                ) != grant.attempt_id:
                    raise AdaptiveDispatchError("stale_attempt_during_memory_read")
        consumed_ids = {
            record.memory_id
            for record in self.context.memory_consumption_records
            if record.consumer_step_id == step.step_id
        }
        for memory_input in memory_inputs:
            memory_id = str(memory_input["ref_id"])
            if memory_id not in consumed_memory_ids:
                continue
            if memory_id in consumed_ids:
                continue
            record_after_surface_hash = self.context.memory_after_surface_hash_by_memory_id.get(
                memory_id,
                after_surface_hash,
            )
            if not record_after_surface_hash:
                record_after_surface_hash = sha256_digest({
                    "before_surface_hash": before_surface_hash,
                    "memory_input_hashes": [
                        item["input_payload_hash"]
                        for item in memory_inputs
                        if str(item.get("ref_id", "")) in consumed_memory_ids
                    ],
                    "downstream_ref_ids": list(downstream_ref_ids),
                })
            replay_class = ReplayClass(str(memory_input["replay_class"]))
            recipe_recomputed = memory_id == replay_memory_id
            evidence = dict((skip_evidence_by_memory_id or {}).get(memory_id, {}))
            observation = next(
                (
                    item
                    for item in self.context.replay_observations
                    if str(item.get("memory_id", "")) == memory_id
                    and str(item.get("attempt_id", "")) == grant.attempt_id
                ),
                None,
            )
            if observation is not None:
                evidence = {
                    **dict(observation.get("skip_evidence", {})),
                    **evidence,
                    "observation_id": str(observation.get("observation_id", "")),
                    "provider_invocation_status": str(
                        observation.get("provider_invocation_status", "")
                    ),
                    "provider_id": str(observation.get("provider_id", "")),
                }
            effective_recipe_step_status = (
                recipe_step_status
                or ("skipped_generation" if recipe_recomputed else "recomputed_current_input")
            )
            skipped_generation = int(effective_recipe_step_status == "skipped_generation")
            skipped_provider = int(
                evidence.get("provider_invocation_status") == "not_started"
            )
            skipped_llm = int(
                skipped_generation
                and isinstance(memory_input.get("execution_recipe"), dict)
                and str(
                    dict(memory_input.get("execution_recipe", {})).get("execution_kind", "")
                ) == ExecutionKind.LLM_BOUNDED_PYTHON.value
            )
            if skipped_generation and not evidence:
                evidence = {
                    "status": "observed",
                    "recipe_hash": str(memory_input.get("execution_recipe_hash", "")),
                    "generation_boundary": "skipped",
                    "provider_boundary": "not_observed",
                    "reason": "validated_recipe_current_input_execution",
                }
            behavioral_effect = (
                "no_effect" if record_after_surface_hash == before_surface_hash else "changed"
            )
            consumer_runtime_task_id = (
                self.context.runtime_identity.runtime_task_id
                if self.context.runtime_identity is not None
                else grant.task_id
            )
            consumer_run_id = (
                self.context.runtime_identity.run_id
                if self.context.runtime_identity is not None
                else ""
            )
            query_hash = str(memory_input.get("query_hash", ""))
            occurrence_identity = sha256_digest({
                "consumer_runtime_task_id": consumer_runtime_task_id,
                "consumer_run_id": consumer_run_id,
                "consumer_session_id": grant.session_id,
                "consumer_step_id": step.step_id,
                "consumer_attempt_id": grant.attempt_id,
                "memory_id": memory_id,
                "query_hash": query_hash,
                "input_payload_hash": str(memory_input.get("input_payload_hash", "")),
            })
            record = MemoryConsumptionRecord(
                consumption_id=f"memory-consumption:{occurrence_identity}",
                query_hash=query_hash,
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
                after_decision_surface_hash=record_after_surface_hash,
                behavioral_effect=behavioral_effect,
                downstream_ref_ids=downstream_ref_ids,
                skipped_generation_step_count=skipped_generation,
                skipped_llm_call_count=skipped_llm,
                skipped_provider_call_count=skipped_provider,
                recipe_step_status=effective_recipe_step_status,
                skip_evidence=evidence,
                recipe_recomputed=recipe_recomputed,
                consumed_at_ns=time.time_ns(),
                consumer_runtime_task_id=consumer_runtime_task_id,
                consumer_run_id=consumer_run_id,
                consumer_session_id=grant.session_id,
                consumer_attempt_id=grant.attempt_id,
                capability_grant_hash=grant.grant_hash,
                memory_commit_hash=str(memory_input.get("memory_commit_hash", "")),
                memory_admission_receipt_hash=str(
                    memory_input.get("memory_admission_receipt_hash", "")
                ),
                replay_eligibility_receipt_hash=str(
                    memory_input.get("replay_eligibility_receipt_hash", "")
                ),
            )
            self.context.memory_consumption_records.append(record)
        task_records = [
            record
            for record in self.context.memory_consumption_records
            if record.consumer_step_id == step.step_id
        ]
        return {
            "memory_consumed_count": float(len(task_records)),
            "memory_actual_use_count": float(
                sum(
                    bool(record.attempt_result_admission_receipt_hash)
                    for record in task_records
                )
            ),
            "memory_approved_but_unused_count": float(len(approved_unused_ids)),
            "memory_behavioral_effect_count": float(
                sum(record.behavioral_effect == "changed" for record in task_records)
            ),
            "memory_assist_count": float(
                sum(record.replay_class == ReplayClass.ASSIST for record in task_records)
            ),
            "validated_replay_count": float(
                0
            ),
            "exact_replay_count": float(
                0
            ),
            "skipped_step_count": float(
                sum(record.skipped_generation_step_count for record in task_records)
            ),
            "skipped_llm_call_count": float(
                sum(record.skipped_llm_call_count for record in task_records)
            ),
            "skipped_provider_call_count": float(
                sum(record.skipped_provider_call_count for record in task_records)
            ),
        }

    def _observe_memory_read(
        self,
        memory_input: dict[str, object],
        *,
        grant: CapabilityGrant,
        step: PlanStepProposal,
        read_rows: bool = False,
    ) -> tuple[dict[str, object], ...]:
        """Perform and record the bounded, verified Memory-side read.

        This is intentionally Runtime-owned.  Metadata/descriptor creation is
        not a read; a consumption observation verifies the persisted recipe and
        artifact bytes (when an artifact path is available) before recording
        the downstream handoff.
        """
        if str(memory_input.get("grant_hash", "")) != grant.grant_hash:
            raise AdaptiveDispatchError("memory_read_grant_mismatch")
        if str(memory_input.get("consumer_step_id", "")) != step.step_id:
            raise AdaptiveDispatchError("memory_read_step_mismatch")
        if self.context.memory_store is not None:
            admitted = self.context.memory_store.get_admitted(str(memory_input.get("ref_id", "")))
            if admitted is None:
                raise AdaptiveDispatchError("memory_read_invalidation_or_admission_missing")
            commit, admission_receipt = admitted
            if (
                commit.commit_hash != str(memory_input.get("memory_commit_hash", ""))
                or admission_receipt.receipt_hash != str(memory_input.get("memory_admission_receipt_hash", ""))
            ):
                raise AdaptiveDispatchError("memory_read_admission_changed_before_read")
        recipe = memory_input.get("execution_recipe")
        recipe_hash = str(memory_input.get("execution_recipe_hash", ""))
        if str(memory_input.get("replay_class", "")) == ReplayClass.VALIDATED_REPLAY.value and (
            not isinstance(recipe, dict) or not recipe_hash
        ):
            raise AdaptiveDispatchError("memory_read_recipe_integrity_missing")
        if recipe_hash and isinstance(recipe, dict) and sha256_digest(recipe) != recipe_hash:
            raise AdaptiveDispatchError("memory_read_recipe_checksum_mismatch")
        expected_recipe_hash = str(memory_input.get("replay_eligibility_receipt_hash", ""))
        if expected_recipe_hash:
            eligibility = next(
                (
                    receipt
                    for receipt in self.context.replay_eligibility_receipts_by_step.get(step.step_id, ())
                    if receipt.memory_id == str(memory_input.get("ref_id", ""))
                ),
                None,
            )
            if eligibility is None or eligibility.receipt_hash != expected_recipe_hash:
                raise AdaptiveDispatchError("memory_read_eligibility_receipt_mismatch")
        lineage = memory_input.get("artifact_lineage")
        artifact_read = "not_applicable"
        artifact_hash = ""
        artifact_ref_id = ""
        artifact_rows = ()
        artifact_size = 0
        if isinstance(lineage, dict):
            artifact_ref_id = str(lineage.get("artifact_ref_id", ""))
            root_id = str(lineage.get("artifact_root_id", ""))
            relpath = str(lineage.get("artifact_relpath", ""))
            expected_hash = str(lineage.get("artifact_hash", ""))
            if root_id and relpath:
                artifact_path = Path(root_id) / relpath
                if not artifact_path.is_file():
                    raise AdaptiveDispatchError("memory_read_artifact_missing")
                artifact_bytes = artifact_path.read_bytes()
                artifact_size = len(artifact_bytes)
                artifact_hash = sha256_digest(artifact_bytes)
                if expected_hash and artifact_hash != expected_hash:
                    raise AdaptiveDispatchError("memory_read_artifact_checksum_mismatch")
                artifact_read = "observed"
                if read_rows:
                    payload = json.loads(artifact_bytes)
                    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
                        raise AdaptiveDispatchError("memory_read_artifact_rows_invalid")
                    artifact_rows = tuple(dict(row) for row in payload)
            expected_manifest_hash = str(lineage.get("manifest_hash", ""))
            if expected_manifest_hash and str(memory_input.get("artifact_verification_receipt_hash", "")):
                if self.context.memory_store is not None:
                    admitted = self.context.memory_store.get_admitted(str(memory_input.get("ref_id", "")))
                    if admitted is not None:
                        _commit, admission_receipt = admitted
                        if admission_receipt.artifact_verification_receipt_hash != str(memory_input.get("artifact_verification_receipt_hash", "")):
                            raise AdaptiveDispatchError("memory_read_artifact_verification_receipt_mismatch")
        self.context.memory_read_evidence_by_id[str(memory_input["ref_id"])] = {
            "status": "observed",
            "memory_id": str(memory_input["ref_id"]),
            "step_id": step.step_id,
            "attempt_id": grant.attempt_id,
            "grant_hash": grant.grant_hash,
            "artifact_read": artifact_read,
            "artifact_ref_id": artifact_ref_id,
            "artifact_hash": artifact_hash,
            "artifact_read_bytes": artifact_size,
            "recipe_hash": recipe_hash,
            "artifact_verification_receipt_hash": str(memory_input.get("artifact_verification_receipt_hash", "")),
            "manifest_hash": str(lineage.get("manifest_hash", "")) if isinstance(lineage, dict) else "",
            "read_at_ns": time.time_ns(),
        }
        prior = self.context.memory_read_observations_by_step.get(step.step_id, ())
        if str(memory_input["ref_id"]) not in prior:
            self.context.memory_read_observations_by_step[step.step_id] = (*prior, str(memory_input["ref_id"]))
        return artifact_rows

    def _dispatch_transform_dsl(
        self,
        envelope: AdaptiveTaskEnvelope,
        approved_plan: ApprovedPlan,
        step: PlanStepProposal,
        grant: CapabilityGrant,
        attempt_workspace: Path,
        candidate_program: TransformProgram | None = None,
    ) -> "AdaptiveStepResult":
        from statebus.runtime.adaptive_runtime import AdaptiveStepResult

        with self._measure_phase("execution_input_hydration", grant):
            input_tables, input_hashes, provenance, projection_hashes = self._typed_transform_inputs(
                step=step,
                grant=grant,
                attempt_workspace=attempt_workspace,
            )
        input_ref_id = next(iter(input_tables))
        rows = input_tables[input_ref_id]
        data_refs = tuple(input_tables)
        memory_inputs = self._memory_inputs_for_step(step=step, grant=grant)
        before_memory_surface_hash = sha256_digest({
            "step": step.canonical_payload(),
            "input_ref_id": input_ref_id,
            "input_hashes": list(input_hashes),
        })
        replay_recipe, replay_memory_id = self._validated_recipe(
            memory_inputs,
            execution_kind=ExecutionKind.TRANSFORM_DSL.value,
            capability_id=step.capability_id,
            output_contract_version=grant.output_contract_version,
        )
        self._require_validated_recipe_match(memory_inputs, replay_recipe)
        if replay_recipe is not None and replay_memory_id:
            replay_input = next(
                item for item in memory_inputs if str(item.get("ref_id", "")) == replay_memory_id
            )
            with self._measure_phase("memory_read_verification", grant):
                self._observe_memory_read(replay_input, grant=grant, step=step)
        if candidate_program is not None:
            program = candidate_program
        elif replay_recipe is not None:
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
            if len(data_refs) > 1 and tuple(replay_recipe.get("input_artifact_refs", ())) != data_refs:
                raise AdaptiveDispatchError("validated_replay_input_bindings_mismatch")
            program = TransformProgram(
                program_id=f"validated-replay-{grant.attempt_id}",
                input_artifact_refs=data_refs,
                operations=operations,
                output_contract_version=grant.output_contract_version,
            )
        elif self.context.transform_program_factory is None:
            raise AdaptiveDispatchError("transform_program_handler_not_registered")
        else:
            factory = self.context.transform_program_factory
            args = (step, grant, input_ref_id, rows)
            if self._factory_accepts_memory_inputs(factory):
                args = (*args, memory_inputs)
            kwargs = {"input_tables": input_tables} if "input_tables" in inspect.signature(factory).parameters else {}
            program = factory(*args, **kwargs)
        schema = self._output_schema(step.capability_id, rows, step.step_id)
        projected_inputs = {ref: [dict(row) for row in table] for ref, table in input_tables.items()}
        dsl_repair_count = 0
        dsl_quality_repair_count = 0
        quality_rejection_count = 0
        quality_hashes: list[str] = []
        program_hashes = [program.program_hash]
        validator_id = self._business_validator_id(step.capability_id)
        while True:
            try:
                # Check every generated/repaired candidate before executing it.
                # Evidence may accompany data in a Grant but is not a data table.
                program_data_refs = tuple(ref for ref in program.input_artifact_refs if ref in input_tables)
                if (program_data_refs != data_refs
                        or any(ref not in grant.input_ref_ids for ref in program.input_artifact_refs)):
                    raise AdaptiveDispatchError("provider_candidate_input_scope_mismatch")
                self._validate_transform_semantics(
                    program,
                    self.context.quality_semantics_by_capability.get(step.capability_id, {}),
                )
                with self._measure_phase("transform_execution", grant):
                    transformed = tuple(self.transform_interpreter.run(program, inputs=projected_inputs))
                if any(operation.op == "deterministic_fixture" for operation in program.operations):
                    # The fixture operation is available only to an explicitly
                    # configured offline smoke.  The registered business
                    # validator still performs its own source-row
                    # recomputation; this value is only the generic
                    # dispatcher context projection.
                    recomputed = tuple(transformed)
                else:
                    with self._measure_phase("transform_recompute", grant):
                        recomputed = recompute_transform_program(program, inputs=projected_inputs)
            except (AdaptiveDispatchError, CapabilityRecomputeError, TransformProgramError) as exc:
                if self.context.transform_program_repair_factory is None or dsl_repair_count >= 1:
                    exhausted_error = (
                        _dsl_repair_exhausted_code(exc)
                        if dsl_repair_count >= 1
                        else ""
                    )
                    raise AdaptiveDispatchError(exhausted_error or str(exc)) from exc
                program = self._invoke_transform_program_repair(
                    self.context.transform_program_repair_factory,
                    step=step,
                    grant=grant,
                    input_ref_id=input_ref_id,
                    rows=rows,
                    validation_errors=(str(exc),),
                    input_tables=input_tables,
                    previous_program=program,
                    repair_stage="execution_validation",
                )
                dsl_repair_count += 1
                program_hashes.append(program.program_hash)
                continue
            with self._measure_phase("quality_validation", grant):
                quality = self.context.validator_registry.validate(
                    CapabilityQualityContext(
                        capability_id=step.capability_id,
                        validator_id=validator_id,
                        input_rows=tuple(input_tables.values()),
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
                    error_code=(
                        "dsl_repair_exhausted:capability_quality_rejected"
                        if dsl_repair_count >= 1
                        else "capability_quality_rejected"
                    ),
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
            program = self._invoke_transform_program_repair(
                self.context.transform_program_repair_factory,
                step=step,
                grant=grant,
                input_ref_id=input_ref_id,
                rows=rows,
                validation_errors=quality.error_codes,
                input_tables=input_tables,
                previous_program=program,
                repair_stage="quality_validation",
            )
            dsl_repair_count += 1
            dsl_quality_repair_count += 1
            program_hashes.append(program.program_hash)
        with self._measure_phase("transform_verified_materialization", grant):
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
            "recipe_id": f"{step.capability_id}:{ExecutionKind.TRANSFORM_DSL.value}",
            "recipe_version": "v1",
            "step_ids": [step.step_id],
            "operation_names": [operation.op for operation in program.operations],
            "execution_kind": ExecutionKind.TRANSFORM_DSL.value,
            "capability_id": step.capability_id,
            "capability_version": self.context.registry.get(step.capability_id).version,
            "output_contract_version": grant.output_contract_version,
            "input_schema_digest": self.context.input_schema_digest,
            "validator_digest": self.context.validator_digest,
            "runtime_signature_hash": self.context.runtime_compatibility_signature,
            "operations": [operation.canonical_payload() for operation in program.operations],
            "source_program_hash": program.program_hash,
            "input_artifact_refs": list(data_refs),
            "input_artifact_hashes": list(input_hashes),
        }
        memory_metrics = self._record_memory_consumption(
            memory_inputs=memory_inputs,
            step=step,
            grant=grant,
            downstream_ref_ids=(artifact.artifact_id,),
            before_surface_hash=before_memory_surface_hash,
            replay_memory_id=(replay_memory_id if dsl_repair_count == 0 else ""),
            consumed_memory_ids=(
                (replay_memory_id,)
                if replay_memory_id and dsl_repair_count == 0
                else ()
            ),
            recipe_step_status=(
                "skipped_generation"
                if replay_memory_id and dsl_repair_count == 0
                else "recomputed_current_input"
            ),
        )
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            attempt_id=grant.attempt_id,
            output_refs=(
                (artifact.artifact_id, input_ref_id)
                if "canonical_evidence_pack"
                in self.context.registry.get(step.capability_id).output_ref_kinds
                else (artifact.artifact_id,)
            ),
            output_ref_kinds=(
                ("execution_artifact", "canonical_evidence_pack")
                if "canonical_evidence_pack"
                in self.context.registry.get(step.capability_id).output_ref_kinds
                else ("execution_artifact",)
            ),
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
        *,
        source_override: str | None = None,
    ) -> "AdaptiveStepResult":
        from statebus.runtime.adaptive_runtime import AdaptiveStepResult

        if not envelope.allow_llm_python or envelope.risk_class != RiskClass.BOUNDED_CODE:
            raise AdaptiveDispatchError("llm_python_not_program_enabled")
        if self.context.code_policy_factory is None:
            raise AdaptiveDispatchError("llm_python_handler_not_registered")
        if not grant.input_ref_ids:
            raise AdaptiveDispatchError("llm_python_requires_verified_artifact")
        # ``CodeAct`` normally consumes a verified execution artifact.  A
        # fixed four-role recipe can also hand the executor a verified
        # evidence pack directly, in which case the pack is projected into a
        # typed input.  When an execution artifact is already present, the
        # evidence pack is retrieval context only: it must not be silently
        # mounted as executable data or make CodeAct depend on fields that are
        # not part of the artifact contract.
        artifact_ref_ids = tuple(
            ref_id for ref_id in grant.input_ref_ids if ref_id in self.context.artifacts
        )
        project_evidence_as_input = not artifact_ref_ids
        stored_inputs: list[StoredAdaptiveArtifact] = []
        verified_inputs: list[tuple[dict[str, object], ...]] = []
        retrieval_context: list[dict[str, object]] = []
        evidence_manifest: dict[str, str] = {}
        evidence_provenance: list[str] = []
        for input_index, ref_id in enumerate(grant.input_ref_ids):
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
            if not project_evidence_as_input:
                continue
            input_schema = self._configured_input_schema(step.capability_id, step.step_id)
            projection_request = EvidenceProjectionRequest(
                task_id=grant.task_id,
                session_id=grant.session_id,
                step_id=grant.step_id,
                evidence_pack_ref_id=ref_id,
                evidence_pack_hash=evidence_pack.pack_hash,
                requested_fields=tuple(input_schema),
                output_contract_version="statebus.transform_input.v1",
            )
            rows, projected_artifact, projection_report = self.projection_adapter.project(
                request=projection_request,
                evidence_pack=evidence_pack,
                coverage_status=self.context.evidence_statuses.get(
                    ref_id,
                    EvidenceCoverageStatus.INSUFFICIENT_EVIDENCE,
                ),
                grant=grant,
                attempt_workspace=attempt_workspace / "evidence_projection" / str(input_index),
            )
            projected = StoredAdaptiveArtifact(
                artifact=projected_artifact,
                rows=rows,
                provenance_item_ids=projection_report.consumed_evidence_item_ids,
            )
            self.context.artifacts[projected_artifact.artifact_id] = projected
            self.context.projection_reports[projection_report.report_hash] = projection_report
            stored_inputs.append(projected)
            verified_inputs.append(rows)
        if not verified_inputs:
            raise AdaptiveDispatchError("llm_python_requires_verified_input")
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
        self._require_validated_recipe_match(memory_inputs, replay_recipe)
        if replay_recipe is not None and replay_memory_id:
            replay_input = next(
                item for item in memory_inputs if str(item.get("ref_id", "")) == replay_memory_id
            )
            self._observe_memory_read(replay_input, grant=grant, step=step)
        validator_id = self._business_validator_id(step.capability_id)
        policy = self.context.code_policy_factory(step)
        if not policy.enabled or not policy.require_bwrap:
            raise AdaptiveDispatchError("llm_python_policy_not_bwrap_required")
        if len(policy.allowed_input_relpaths) == 1 and len(verified_inputs) > 1:
            policy = replace(
                policy,
                allowed_input_relpaths=(
                    policy.allowed_input_relpaths[0],
                    *(f"inputs/upstream-{index}.json" for index in range(1, len(stored_inputs))),
                ),
            )
        if len(policy.allowed_input_relpaths) != len(verified_inputs):
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
        if source_override is not None:
            source = source_override
        elif replay_recipe is not None:
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
                    "llm_codeact_verified_count": 0.0,
                    "llm_codeact_sandbox_fallback_count": float(outcome.record.sandbox_actual_backend != "bwrap"),
                },
            )
        if sha256_digest(outcome.accepted_source.encode("utf-8")) != outcome.record.source_hash:
            raise AdaptiveDispatchError("llm_python_accepted_source_hash_mismatch")
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
            "recipe_id": f"{step.capability_id}:{ExecutionKind.LLM_BOUNDED_PYTHON.value}",
            "recipe_version": "v1",
            "step_ids": [step.step_id],
            "operation_names": ["bounded_python_program"],
            "execution_kind": ExecutionKind.LLM_BOUNDED_PYTHON.value,
            "capability_id": step.capability_id,
            "capability_version": self.context.registry.get(step.capability_id).version,
            "output_contract_version": grant.output_contract_version,
            "input_schema_digest": self.context.input_schema_digest,
            "validator_digest": self.context.validator_digest,
            "runtime_signature_hash": self.context.runtime_compatibility_signature,
            "source": outcome.accepted_source,
            "source_hash": outcome.record.source_hash,
        }
        memory_metrics = self._record_memory_consumption(
            memory_inputs=memory_inputs,
            step=step,
            grant=grant,
            downstream_ref_ids=(artifact.artifact_id,),
            before_surface_hash=before_memory_surface_hash,
            replay_memory_id=(replay_memory_id if not outcome.repairs else ""),
            consumed_memory_ids=(
                (replay_memory_id,)
                if replay_memory_id and not outcome.repairs
                else ()
            ),
            recipe_step_status=(
                "skipped_generation"
                if replay_memory_id and not outcome.repairs
                else "recomputed_current_input"
            ),
        )
        output_kinds = self.context.registry.get(step.capability_id).output_ref_kinds
        # An evidence ref may be an executor input used as retrieval context,
        # but it is only an output when the capability contract explicitly
        # declares ``canonical_evidence_pack`` in ``output_ref_kinds``.  The
        # executor's public contract normally produces only its artifact; a
        # previous implementation appended every evidence input while still
        # declaring one output kind, so Runtime rejected an otherwise valid
        # CodeAct artifact with a generic ``step_validator_failed``.
        passthrough_evidence_refs = (
            tuple(
                ref_id
                for ref_id in grant.input_ref_ids
                if ref_id in self.context.evidence_packs
            )
            if "canonical_evidence_pack" in output_kinds
            else ()
        )
        if "canonical_evidence_pack" in output_kinds and not passthrough_evidence_refs:
            raise AdaptiveDispatchError("llm_python_evidence_passthrough_missing")
        output_refs = (artifact.artifact_id, *passthrough_evidence_refs)
        output_ref_kinds = (
            ("execution_artifact",)
            + ("canonical_evidence_pack",) * len(passthrough_evidence_refs)
        )
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            attempt_id=grant.attempt_id,
            output_refs=output_refs,
            output_ref_kinds=output_ref_kinds,
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
                "llm_codeact_candidate_count": 1.0,
                "llm_codeact_verified_count": float(
                    outcome.quality_report is not None
                    and outcome.quality_report.verified
                ),
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
        candidate_claim_set: ClaimSet | None = None,
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
        if not artifacts:
            raise AdaptiveDispatchError("summarizer_verified_input_set_invalid")
        if len(evidence_ref_ids) != 1:
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
        if candidate_claim_set is not None:
            claim_set = candidate_claim_set
        else:
            assert self.context.claim_set_factory is not None
            memory_artifacts = {}
            if self.context.claim_memory_selector is not None:
                if "memory_artifacts" not in inspect.signature(self.context.claim_set_factory).parameters:
                    raise AdaptiveDispatchError("summarizer_memory_reader_not_registered")
                selected_ids = self.context.claim_memory_selector(memory_inputs)
                granted_inputs = {str(item["ref_id"]): item for item in memory_inputs}
                if len(selected_ids) != len(set(selected_ids)) or not set(selected_ids) <= set(granted_inputs):
                    raise AdaptiveDispatchError("summarizer_memory_selection_outside_grant")
                for memory_id in selected_ids:
                    with self._measure_phase("memory_read_verification", grant):
                        memory_artifacts[memory_id] = self._observe_memory_read(
                            granted_inputs[memory_id], grant=grant, step=step, read_rows=True,
                        )
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
                        **({"memory_artifacts": memory_artifacts} if self.context.claim_memory_selector is not None else {}),
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
        self.context.artifacts[candidate.artifact_id] = StoredAdaptiveArtifact(
            artifact=candidate,
            rows=(claim_set.canonical_payload(),),
            provenance_item_ids=tuple(dict.fromkeys(
                evidence_id
                for claim in claim_set.claims
                for evidence_id in claim.supporting_evidence_item_ids
            )),
        )
        self.context.claim_sets[candidate.artifact_id] = claim_set
        memory_metrics = self._record_memory_consumption(
            memory_inputs=memory_inputs,
            step=step,
            grant=grant,
            downstream_ref_ids=(candidate.artifact_id,),
            before_surface_hash=before_memory_surface_hash,
        )
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            attempt_id=grant.attempt_id,
            output_refs=(candidate.artifact_id,),
            output_ref_kinds=("execution_artifact",),
            validator_report_hashes=(audit_hash,),
            metrics=memory_metrics,
        )

    def _typed_transform_inputs(
        self,
        *,
        step: PlanStepProposal,
        grant: CapabilityGrant,
        attempt_workspace: Path,
    ) -> tuple[dict[str, tuple[dict[str, object], ...]], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        """Hydrate all current data artifacts under the same verified Grant.

        Evidence-only projection keeps its existing single-pack contract. When
        data artifacts exist, evidence is context and never silently unioned
        into a table. Each data file is re-read and checked independently.
        """
        refs = tuple(ref for ref in grant.input_ref_ids if ref in self.context.artifacts)
        if len(refs) <= 1:
            ref, rows, hashes, provenance, projections = self._typed_input(
                step=step, grant=grant, attempt_workspace=attempt_workspace,
            )
            return {ref: rows}, hashes, provenance, projections
        unknown = set(grant.input_ref_ids) - set(refs) - set(self.context.evidence_packs)
        if unknown:
            raise AdaptiveDispatchError("transform_input_ref_unknown")
        for ref in grant.input_ref_ids:
            if ref in self.context.evidence_packs:
                self._verified_evidence_pack(ref, grant)
        tables = {}
        hashes = []
        provenance = []
        for ref in refs:
            stored = self.context.artifacts[ref]
            if not self._artifact_in_grant_scope(stored, grant):
                raise AdaptiveDispatchError("transform_input_not_verified")
            tables[ref] = self._read_verified_artifact_rows(stored)
            hashes.append(stored.artifact.blob_hash)
            provenance.extend(stored.provenance_item_ids)
        return tables, tuple(hashes), tuple(dict.fromkeys(provenance)), ()

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
                requested_fields=tuple(
                    self._configured_input_schema(step.capability_id, step.step_id).keys()
                ),
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

    def _configured_input_schema(self, capability_id: str, step_id: str = "") -> dict[str, str]:
        if step_id:
            configured = self.context.input_schema_by_step.get(step_id)
            if configured:
                return configured
        return self._output_schema(capability_id, (), step_id)

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

    def _artifact_in_grant_scope(
        self,
        stored: StoredAdaptiveArtifact | None,
        grant: CapabilityGrant,
    ) -> bool:
        if stored is None:
            return False
        metadata = stored.artifact.metadata
        receipt = self.context.artifact_verification_receipts.get(
            stored.artifact.artifact_id
        )
        return (
            receipt is not None
            and receipt.decision == ArtifactVerificationDecision.VERIFIED
            and receipt.artifact_id == stored.artifact.artifact_id
            and receipt.runtime_task_id == grant.task_id
            and receipt.session_id == grant.session_id
            and receipt.producer_step_id == stored.artifact.step_id
            and receipt.producer_attempt_id == metadata.get("attempt_id")
            and receipt.capability_grant_hash == metadata.get("grant_hash")
            and receipt.candidate_blob_hash == stored.artifact.blob_hash
            and metadata.get("artifact_verification_receipt_hash") == receipt.receipt_hash
            and stored.artifact.verification_state == RefStatus.VERIFIED
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
        runtime_identity: RuntimeIdentity,
    ) -> ExecutionKind:
        descriptor = self.context.registry.get(step.capability_id)
        logical_capability = project_legacy_capability(descriptor)
        binding = bound_grant.execution_binding
        runtime_identity.validate_legacy_projection(
            task_id=grant.task_id,
            canonical_task_spec_hash=envelope.canonical_task_spec_hash,
        )
        if runtime_identity.session_id != grant.session_id:
            raise AdaptiveDispatchError("runtime_identity_grant_scope_mismatch")
        if (
            self.context.session_manager is not None
            and self.context.session_manager.active_attempt_id(
                grant.session_id, grant.step_id
            )
            != grant.attempt_id
        ):
            raise AdaptiveDispatchError("stale_attempt_before_dispatch")
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
        if step.capability_id in self.context.bound_provider_handlers:
            provider_registry = self.context.provider_registry
            if provider_registry is None:
                provider_registry = ExecutionProviderRegistry.from_legacy_capability_registry(
                    self.context.registry
                )
            try:
                provider_registry.resolve_bound(binding=binding)
            except ProviderBindingError as exc:
                code = str(exc)
                if step.role == "planner" and code in {
                    "bound_provider_snapshot_missing",
                    "provider_binding_not_registered",
                }:
                    code = "planner_binding_mismatch"
                raise AdaptiveDispatchError(code) from exc
            if descriptor.owner_role != step.role:
                raise AdaptiveDispatchError("capability_descriptor_mismatch")
            return descriptor.execution_kind
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
        # The deterministic fixture is an explicit offline-only seam.  Its
        # source-derived runner owns the operation semantics; live requests do
        # not have this operation available because their interpreter has no
        # fixture runner.
        if (
            len(program.operations) == 1
            and program.operations[0].op == "deterministic_fixture"
        ):
            return
        dsl_operation = str(semantics.get("dsl_operation", ""))
        dsl_arguments = semantics.get("dsl_arguments")
        if dsl_operation:
            if (
                len(program.operations) != 1
                or program.operations[0].op != dsl_operation
            ):
                raise AdaptiveDispatchError("transform_program_semantics_operation_mismatch")
            if not isinstance(dsl_arguments, dict):
                raise AdaptiveDispatchError("transform_program_semantics_arguments_missing")
            arguments = dict(program.operations[0].arguments)
            for field, expected in dsl_arguments.items():
                if arguments.get(field) != expected:
                    raise AdaptiveDispatchError(
                        f"transform_program_semantics_argument_mismatch:{field}"
                    )
            if set(arguments) != set(dsl_arguments):
                raise AdaptiveDispatchError("transform_program_semantics_arguments_mismatch")
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
