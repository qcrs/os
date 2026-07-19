from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from v2.contracts import (
    AdaptiveTaskEnvelope,
    ApprovedPlan,
    CapabilityGrant,
    ClaimSet,
    CodeGenerationPolicy,
    CodeGenerationRequest,
    EvidenceCoverageStatus,
    EvidenceProjectionRequest,
    ExecutionKind,
    PlanStepProposal,
    RefStatus,
    RiskClass,
    TransformProgram,
)
from v2.refs import CanonicalEvidencePack, ExecutionArtifactRef
from v2.runtime.capability_registry import CapabilityRegistry
from v2.runtime.capability_recompute import CapabilityRecomputeError, recompute_transform_program
from v2.runtime.capability_validators import (
    CapabilityQualityContext,
    CapabilityValidatorRegistry,
    default_capability_validator_registry,
)
from v2.runtime.evidence_projection import EvidenceProjectionAdapter
from v2.runtime.llm_codeact import LlmCodeActRunner, build_code_generation_prompt
from v2.runtime.retrieval_adapter import AdaptiveRetrievalAdapter, AdaptiveRetrievalResult
from v2.runtime.transform_dsl import TransformDslInterpreter, TransformProgramError
from v2.runtime.claims import ClaimSetValidator
from v2.runtime.workspace import ArtifactLifecycleManager
from v2.utils import sha256_digest, stable_json_dumps

if TYPE_CHECKING:
    from v2.runtime.adaptive_runtime import AdaptiveStepResult


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
TransformProgramFactory = Callable[[PlanStepProposal, CapabilityGrant, str, tuple[dict[str, object], ...]], TransformProgram]
TransformProgramRepairFactory = Callable[
    [PlanStepProposal, CapabilityGrant, str, tuple[dict[str, object], ...], tuple[str, ...]],
    TransformProgram,
]
CodeSourceFactory = Callable[[CodeGenerationRequest, str], str]
CodeRepairFactory = Callable[[CodeGenerationRequest, str, str, tuple[str, ...]], str]
BuiltinHandler = Callable[[AdaptiveTaskEnvelope, ApprovedPlan, PlanStepProposal, CapabilityGrant, Path], "AdaptiveStepResult"]
ClaimSetFactory = Callable[[PlanStepProposal, CapabilityGrant, ExecutionArtifactRef, tuple[dict[str, object], ...], CanonicalEvidencePack], ClaimSet]


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
        grant: CapabilityGrant,
        attempt_workspace: Path,
    ) -> "AdaptiveStepResult":
        from v2.runtime.adaptive_runtime import AdaptiveStepResult

        try:
            descriptor = self.context.registry.get(step.capability_id)
            self._validate_dispatch(envelope, approved_plan, step, grant, descriptor.execution_kind)
            handler = self._handlers[descriptor.execution_kind]
            return handler(envelope, approved_plan, step, grant, attempt_workspace)
        except (AdaptiveDispatchError, ValueError) as exc:
            return AdaptiveStepResult(
                grant_hash=grant.grant_hash,
                success=False,
                attempt_id=grant.attempt_id,
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
        del envelope, approved_plan, attempt_workspace
        from v2.runtime.adaptive_runtime import AdaptiveStepResult

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
        coverage = result.coverage_reports[-1] if result.coverage_reports else None
        if coverage is None or coverage.status != EvidenceCoverageStatus.COMPLETE:
            raise AdaptiveDispatchError("evidence_coverage_not_complete")
        ref_id = f"evidence:{grant.task_id}:{grant.step_id}:{grant.attempt_id}"
        self.context.evidence_packs[ref_id] = result.evidence_pack
        self.context.evidence_statuses[ref_id] = coverage.status
        self.context.evidence_ref_scopes[ref_id] = (grant.session_id, grant.attempt_id)
        state_consumption_records = (
            self.context.retrieval_result_observer(result, step, grant)
            if self.context.retrieval_result_observer is not None
            else ()
        )
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
            metrics={
                "retriever_model_query_count": float(len(result.query_hashes)),
                "retriever_model_query_consumed_count": float(len(result.query_hashes)),
                "retriever_counterfactual_effect_evaluated_count": float(len(evaluated_effect_records)),
                "retriever_query_changed_candidate_set_count": float(sum(
                    record.behavioral_effect == "changed"
                    for record in evaluated_effect_records
                )),
            },
        )

    def _dispatch_transform_dsl(
        self,
        envelope: AdaptiveTaskEnvelope,
        approved_plan: ApprovedPlan,
        step: PlanStepProposal,
        grant: CapabilityGrant,
        attempt_workspace: Path,
    ) -> "AdaptiveStepResult":
        from v2.runtime.adaptive_runtime import AdaptiveStepResult

        input_ref_id, rows, input_hashes, provenance, projection_hashes = self._typed_input(
            step=step,
            grant=grant,
            attempt_workspace=attempt_workspace,
        )
        if self.context.transform_program_factory is None:
            raise AdaptiveDispatchError("transform_program_handler_not_registered")
        program = self.context.transform_program_factory(step, grant, input_ref_id, rows)
        schema = self._output_schema(step.capability_id, rows, step.step_id)
        projected_inputs = {input_ref_id: [dict(row) for row in rows]}
        dsl_repair_count = 0
        while True:
            try:
                self._validate_transform_semantics(
                    program,
                    self.context.quality_semantics_by_capability.get(step.capability_id, {}),
                )
                transformed = tuple(self.transform_interpreter.run(program, inputs=projected_inputs))
                recomputed = recompute_transform_program(program, inputs=projected_inputs)
                break
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
        validator_id = self._business_validator_id(step.capability_id)
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
        if not quality.verified:
            return AdaptiveStepResult(
                grant_hash=grant.grant_hash,
                success=False,
                attempt_id=grant.attempt_id,
                error_code="capability_quality_rejected",
                validator_report_hashes=(quality.report_hash,),
                quality_report_hashes=(quality.report_hash,),
                projection_report_hashes=projection_hashes,
                metrics={
                    "dsl_execution_count": 1.0,
                    "dsl_repair_count": float(dsl_repair_count),
                    "llm_codeact_quality_rejected_count": 0.0,
                },
            )
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
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            attempt_id=grant.attempt_id,
            output_refs=(artifact.artifact_id,),
            output_ref_kinds=("execution_artifact",),
            validator_report_hashes=(quality.report_hash,),
            quality_report_hashes=(quality.report_hash,),
            projection_report_hashes=projection_hashes,
            program_hashes=(program.program_hash,),
            metrics={
                "evidence_projection_count": float(bool(projection_hashes)),
                "dsl_execution_count": 1.0,
                "dsl_repair_count": float(dsl_repair_count),
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
        from v2.runtime.adaptive_runtime import AdaptiveStepResult

        if not envelope.allow_llm_python or envelope.risk_class != RiskClass.BOUNDED_CODE:
            raise AdaptiveDispatchError("llm_python_not_program_enabled")
        if self.context.code_source_factory is None or self.context.code_policy_factory is None:
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
            }),
            output_schema=schema,
            model_signature="adaptive_executor",
            prompt_signature=sha256_digest(step.goal),
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
        )
        prompt = build_code_generation_prompt(request)
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
        quality_hashes = () if outcome.quality_report is None else (outcome.quality_report.report_hash,)
        self.context.code_execution_records[grant.grant_hash] = outcome.record
        self.context.code_policy_reports[grant.grant_hash] = outcome.policy_report
        if outcome.quality_report is not None:
            self.context.quality_reports[outcome.quality_report.report_hash] = outcome.quality_report
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
                    "llm_codeact_generation_count": 1.0,
                    "llm_codeact_repair_count": float(len(outcome.repairs)),
                    "llm_codeact_execution_count": float(outcome.record.exit_code == 0),
                    "llm_codeact_runtime_repair_count": float(sum(
                        item.repair_kind == "runtime" for item in outcome.repairs
                    )),
                    "llm_codeact_quality_rejected_count": float(outcome.record.fallback_reason == "capability_quality_rejected"),
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
                "llm_codeact_generation_count": 1.0,
                "llm_codeact_repair_count": float(len(outcome.repairs)),
                "llm_codeact_runtime_repair_count": float(sum(
                    item.repair_kind == "runtime" for item in outcome.repairs
                )),
                "llm_codeact_execution_count": 1.0,
                "llm_codeact_verified_count": 1.0,
                "llm_codeact_sandbox_fallback_count": 0.0,
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
        from v2.runtime.adaptive_runtime import AdaptiveStepResult

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
        assert self.context.claim_set_factory is not None
        try:
            claim_set = self.context.claim_set_factory(step, grant, stored.artifact, rows, evidence_pack)
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
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            attempt_id=grant.attempt_id,
            output_refs=(artifact.artifact_id,),
            output_ref_kinds=("execution_artifact",),
            validator_report_hashes=(audit_hash,),
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
        execution_kind: ExecutionKind,
    ) -> None:
        descriptor = self.context.registry.get(step.capability_id)
        if step.capability_id != grant.capability_id or grant.approved_plan_hash != approved_plan.approved_plan_hash:
            raise AdaptiveDispatchError("capability_grant_mismatch")
        if grant.task_id != envelope.task_id or grant.step_id != step.step_id or grant.expires_at_ns <= __import__("time").time_ns():
            raise AdaptiveDispatchError("capability_grant_scope_or_expiry_mismatch")
        if descriptor.owner_role != step.role or descriptor.execution_kind != execution_kind:
            raise AdaptiveDispatchError("capability_descriptor_mismatch")
        if execution_kind == ExecutionKind.LLM_BOUNDED_PYTHON:
            if not envelope.allow_llm_python or envelope.risk_class != RiskClass.BOUNDED_CODE:
                raise AdaptiveDispatchError("llm_python_not_program_enabled")
            if not self.context.validator_registry.contains(self._business_validator_id(step.capability_id)):
                raise AdaptiveDispatchError("capability_quality_validator_unregistered")

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
