from __future__ import annotations

from pathlib import Path
import time

import pytest

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    ArtifactVerificationDecision,
    BoundCapabilityGrant,
    CapabilityDescriptor,
    CapabilityGrant,
    CapabilityQualityReport,
    ExecutionBindingReceipt,
    ExecutionKind,
    PlanProposal,
    PlanStepProposal,
    RefStatus,
    RiskClass,
    RuntimeIdentity,
    StepLifecycleState,
    TaskContractIdentity,
    TransformProgram,
    TransformStep,
    WorkflowMode,
)
from statebus.refs import ExecutionArtifactRef
from statebus.runtime.adaptive_dispatcher import (
    AdaptiveCapabilityDispatcher,
    AdaptiveDispatchContext,
    StoredAdaptiveArtifact,
)
from statebus.runtime.adaptive_runtime import (
    AdaptiveRuntimeEngine,
    AdaptiveRuntimeRequest,
    AdaptiveStepResult,
)
from statebus.runtime.artifact_verification import (
    ArtifactVerificationError,
    RuntimeArtifactVerificationAuthority,
)
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.plan_policy import PlanPolicyValidator
from statebus.runtime.session import RuntimeSessionManager, StepAttemptRecord
from statebus.runtime.workspace import ArtifactLifecycleManager
from statebus.utils import sha256_digest, stable_json_dumps


def _identity() -> RuntimeIdentity:
    return RuntimeIdentity(
        runtime_task_id="task-08",
        run_id="run-08",
        session_id="session-08",
        trace_id="trace-08",
        task_contract=TaskContractIdentity.from_hash("task-contract-08"),
    )


def _active_candidate_case(tmp_path: Path) -> dict[str, object]:
    identity = _identity()
    manager = RuntimeSessionManager()
    attempt_workspace = tmp_path / "adaptive_attempts" / "attempt-a"
    output_dir = attempt_workspace / "outputs"
    output_dir.mkdir(parents=True)
    payload = stable_json_dumps({"value": 8}).encode("utf-8")
    output_path = output_dir / "result.json"
    output_path.write_bytes(payload)
    manager.start(
        session_id=identity.session_id,
        trace_id=identity.trace_id,
        task_id=identity.runtime_task_id,
        layer_name="L3",
        canonical_task_spec_hash=identity.task_contract_hash,
        workspace_root=str(tmp_path / "workspace"),
        state_root=str(tmp_path / "state"),
    )
    manager.append_attempt_record(
        identity.session_id,
        record=StepAttemptRecord(
            task_id=identity.runtime_task_id,
            step_id="execute",
            attempt_id="attempt-a",
            owner_role="executor",
            state=StepLifecycleState.RUNNING.value,
        ),
    )
    manager.activate_attempt(
        identity.session_id,
        step_id="execute",
        attempt_id="attempt-a",
    )
    grant = CapabilityGrant(
        grant_id="grant-08-a",
        task_id=identity.runtime_task_id,
        session_id=identity.session_id,
        step_id="execute",
        attempt_id="attempt-a",
        capability_id="execute-artifact-v1",
        capability_version="v1",
        input_ref_ids=(),
        output_contract_version="artifact-v1",
        workspace_root_id="workspace-08",
        max_runtime_ms=30_000,
        expires_at_ns=time.time_ns() + 30_000_000_000,
        approved_plan_hash="approved-plan-08",
    )
    binding = ExecutionBindingReceipt(
        binding_id="binding-08-a",
        task_id=identity.runtime_task_id,
        session_id=identity.session_id,
        step_id="execute",
        attempt_id="attempt-a",
        approved_plan_hash="approved-plan-08",
        logical_capability_id="execute-artifact-v1",
        logical_capability_version="v1",
        semantic_contract_hash="semantic-contract-08",
        provider_registry_digest="provider-registry-08",
        provider_runtime_facts_digest="provider-facts-08",
        eligibility_projection_hash="eligibility-08",
        selected_provider_id="provider-08",
        selected_provider_version="v1",
        selected_provider_kind="runtime",
        selected_implementation_kind=ExecutionKind.RUNTIME_BUILTIN.value,
    )
    quality = CapabilityQualityReport(
        capability_id=grant.capability_id,
        validator_id="artifact-validator-08",
        input_artifact_hashes=(),
        output_artifact_hash=sha256_digest(payload),
        schema_passed=True,
        recomputation_passed=True,
        provenance_passed=True,
        completion_criteria_passed=True,
        verified=True,
    )
    candidate = ArtifactLifecycleManager().register_candidate(
        ExecutionArtifactRef(
            artifact_id="artifact-08-a",
            task_id=identity.runtime_task_id,
            step_id="execute",
            artifact_type="json",
            root_id=str(attempt_workspace),
            relpath="outputs/result.json",
            blob_hash=sha256_digest(payload),
            size_bytes=len(payload),
            produced_by="executor",
            replay_ready=True,
            workspace_relpath="outputs/result.json",
            manifest_hash="manifest-08-a",
            metadata={
                "schema_version": "statebus.test_artifact.v1",
                "session_id": identity.session_id,
                "attempt_id": "attempt-a",
                "grant_hash": grant.grant_hash,
                "quality_report_hash": quality.report_hash,
            },
        )
    )
    admission = manager.admit_attempt_result(
        identity.session_id,
        step_id="execute",
        observed_attempt_id="attempt-a",
    )
    return {
        "identity": identity,
        "manager": manager,
        "workspace": attempt_workspace,
        "candidate": candidate,
        "quality": quality,
        "bound_grant": BoundCapabilityGrant(grant=grant, execution_binding=binding),
        "admission": admission,
    }


def test_active_admitted_candidate_is_runtime_verified(tmp_path: Path) -> None:
    registry = CapabilityRegistry()
    registry.register(CapabilityDescriptor(
        capability_id="produce-artifact-v1",
        owner_role="executor",
        description="produce one candidate artifact",
        input_ref_kinds=(),
        required_input_ref_kinds=(),
        input_contract_version="input-v1",
        output_ref_kinds=("execution_artifact",),
        output_contract_version="artifact-v1",
        execution_kind=ExecutionKind.RUNTIME_BUILTIN,
        side_effect_class=RiskClass.WORKSPACE_WRITE,
        max_runtime_ms=30_000,
        supports_replay=False,
        validator_ids=("artifact-validator-08",),
    ))
    registry.register(CapabilityDescriptor(
        capability_id="consume-verified-artifact-v1",
        owner_role="summarizer",
        description="consume one Runtime-verified artifact",
        input_ref_kinds=("execution_artifact",),
        required_input_ref_kinds=("execution_artifact",),
        input_contract_version="artifact-v1",
        output_ref_kinds=("execution_artifact",),
        output_contract_version="artifact-consumption-v1",
        execution_kind=ExecutionKind.TRANSFORM_DSL,
        side_effect_class=RiskClass.READ_ONLY,
        max_runtime_ms=30_000,
        supports_replay=False,
        validator_ids=("generic_analysis",),
    ))
    identity = _identity()
    envelope = AdaptiveTaskEnvelope(
        task_id=identity.runtime_task_id,
        canonical_task_spec_hash=identity.task_contract_hash,
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="mrr-08-pack",
        allowed_capability_ids=("produce-artifact-v1", "consume-verified-artifact-v1"),
        allowed_output_contracts=("artifact-v1", "artifact-consumption-v1"),
        role_cardinality={"executor": (1, 1), "summarizer": (1, 1)},
        max_plan_steps=2,
        max_total_attempts=2,
    )
    proposal = PlanProposal(
        proposal_id="proposal-08",
        task_id=identity.runtime_task_id,
        final_output_contract_version="artifact-consumption-v1",
        steps=(PlanStepProposal(
            step_id="execute",
            role="executor",
            capability_id="produce-artifact-v1",
            goal="produce candidate",
            output_contract_version="artifact-v1",
        ), PlanStepProposal(
            step_id="consume",
            role="summarizer",
            capability_id="consume-verified-artifact-v1",
            goal="consume the Runtime-verified artifact",
            depends_on=("execute",),
            output_contract_version="artifact-consumption-v1",
        )),
    )
    approved = PlanPolicyValidator(registry).validate(proposal, envelope).approved_plan
    assert approved is not None

    context: AdaptiveDispatchContext
    consumed: dict[str, object] = {}

    def produce(_envelope, _plan, step, grant, attempt_workspace):
        payload = stable_json_dumps({"value": 8}).encode("utf-8")
        output_path = attempt_workspace / "outputs" / "result.json"
        output_path.parent.mkdir(parents=True)
        output_path.write_bytes(payload)
        quality = CapabilityQualityReport(
            capability_id=grant.capability_id,
            validator_id="artifact-validator-08",
            input_artifact_hashes=(),
            output_artifact_hash=sha256_digest(payload),
            schema_passed=True,
            recomputation_passed=True,
            provenance_passed=True,
            completion_criteria_passed=True,
            verified=True,
        )
        candidate = ArtifactLifecycleManager().register_candidate(
            ExecutionArtifactRef(
                artifact_id=f"artifact-{grant.attempt_id}",
                task_id=grant.task_id,
                step_id=step.step_id,
                artifact_type="json",
                root_id=str(attempt_workspace),
                relpath="outputs/result.json",
                blob_hash=sha256_digest(payload),
                size_bytes=len(payload),
                produced_by="executor",
                workspace_relpath="outputs/result.json",
                manifest_hash="manifest-08",
                metadata={
                    "schema_version": "statebus.test_artifact.v1",
                    "session_id": grant.session_id,
                    "attempt_id": grant.attempt_id,
                    "grant_hash": grant.grant_hash,
                    "quality_report_hash": quality.report_hash,
                },
            )
        )
        context.artifacts[candidate.artifact_id] = StoredAdaptiveArtifact(
            artifact=candidate,
            rows=({"value": 8},),
            provenance_item_ids=("producer-value",),
        )
        context.quality_reports[quality.report_hash] = quality
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            attempt_id=grant.attempt_id,
            output_refs=(candidate.artifact_id,),
            output_ref_kinds=("execution_artifact",),
            validator_report_hashes=(quality.report_hash,),
        )

    def consume(step, grant, input_ref_id, rows):
        stored = context.artifacts[input_ref_id]
        receipt = context.artifact_verification_receipts.get(stored.artifact.artifact_id)
        assert receipt is not None
        consumed["receipt_hash"] = receipt.receipt_hash
        consumed["rows"] = rows
        return TransformProgram(
            program_id=f"consume-{grant.attempt_id}",
            input_artifact_refs=(input_ref_id,),
            operations=(TransformStep("select", {"columns": ["value"]}),),
            output_contract_version=step.output_contract_version,
        )

    context = AdaptiveDispatchContext(
        registry=registry,
        builtin_handlers={"produce-artifact-v1": produce},
        transform_program_factory=consume,
        output_schema_by_step={"consume": {"value": "number"}},
    )
    result = AdaptiveRuntimeEngine().run(AdaptiveRuntimeRequest(
        trace_id=identity.trace_id,
        task_id=identity.runtime_task_id,
        canonical_task_spec_hash=identity.task_contract_hash,
        envelope=envelope,
        approved_plan=approved,
        registry=registry,
        runtime_root=str(tmp_path / "runtime"),
        workspace_root_id=str(tmp_path / "workspace"),
        dispatcher=AdaptiveCapabilityDispatcher(context=context),
        runtime_identity=identity,
    ))

    assert result.completed
    artifact = next(
        stored.artifact
        for stored in context.artifacts.values()
        if stored.artifact.produced_by == "executor"
    )
    receipt = context.artifact_verification_receipts[artifact.artifact_id]
    assert artifact.verification_state == RefStatus.VERIFIED
    assert artifact.replay_ready is False
    assert receipt.decision == ArtifactVerificationDecision.VERIFIED
    assert receipt.producer_attempt_id == result.dispatches[0].attempt_id
    assert receipt.candidate_blob_hash == artifact.blob_hash
    assert len(result.dispatches) == 2
    assert consumed == {
        "receipt_hash": receipt.receipt_hash,
        "rows": ({"value": 8},),
    }


def test_stale_producer_candidate_cannot_be_runtime_verified(tmp_path: Path) -> None:
    case = _active_candidate_case(tmp_path)
    identity = case["identity"]
    manager = case["manager"]
    assert isinstance(identity, RuntimeIdentity)
    assert isinstance(manager, RuntimeSessionManager)
    manager.settle_attempt(
        identity.session_id,
        step_id="execute",
        attempt_id="attempt-a",
        terminal_state=StepLifecycleState.FAILED.value,
    )
    manager.append_attempt_record(
        identity.session_id,
        record=StepAttemptRecord(
            task_id=identity.runtime_task_id,
            step_id="execute",
            attempt_id="attempt-b",
            owner_role="executor",
            state=StepLifecycleState.RUNNING.value,
        ),
    )
    manager.activate_attempt(identity.session_id, step_id="execute", attempt_id="attempt-b")
    authority = RuntimeArtifactVerificationAuthority(manager, identity)

    with pytest.raises(
        ArtifactVerificationError,
        match="artifact_producer_attempt_not_active",
    ):
        authority.verify_candidate(
            candidate=case["candidate"],
            artifact_id="artifact-08-a",
            bound_grant=case["bound_grant"],
            result_admission=case["admission"],
            attempt_workspace=case["workspace"],
            validator_report_hashes=(case["quality"].report_hash,),
            quality_reports={case["quality"].report_hash: case["quality"]},
            claim_validation_reports={},
        )

    assert case["candidate"].verification_state == RefStatus.CANDIDATE
    assert manager.active_attempt_id(identity.session_id, "execute") == "attempt-b"


def test_verified_projection_keeps_other_truth_dimensions_separate(tmp_path: Path) -> None:
    case = _active_candidate_case(tmp_path)
    identity = case["identity"]
    manager = case["manager"]
    assert isinstance(identity, RuntimeIdentity)
    assert isinstance(manager, RuntimeSessionManager)
    verified, receipt = RuntimeArtifactVerificationAuthority(
        manager,
        identity,
    ).verify_candidate(
        candidate=case["candidate"],
        artifact_id="artifact-08-a",
        bound_grant=case["bound_grant"],
        result_admission=case["admission"],
        attempt_workspace=case["workspace"],
        validator_report_hashes=(case["quality"].report_hash,),
        quality_reports={case["quality"].report_hash: case["quality"]},
        claim_validation_reports={},
    )

    assert verified.verification_state == RefStatus.VERIFIED
    assert verified.replay_ready is False
    assert set(receipt.canonical_payload()).isdisjoint(
        {"replay_ready", "memory_admitted", "memory_id", "final_adopted"}
    )
