from __future__ import annotations

from dataclasses import replace

import pytest

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    ApprovedPlanBundle,
    PlanNormalizationReceipt,
    PlanPolicyStatus,
    PlanProvenanceError,
    PlanProposal,
    RiskClass,
    RuntimeIdentity,
    TaskContractIdentity,
    WorkflowMode,
    mechanical_semantic_plan_hash,
    semantic_plan_hash,
)
from statebus.runtime.adaptive_plan_compiler import compile_required_input_wiring
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.domain_packs import register_long_doc_analysis_capabilities
from statebus.runtime.plan_policy import PlanPolicyValidator
from statebus.runtime.static_role_recipe import (
    StaticRoleRecipeCompiler,
    compile_static_role_recipe_plan,
    default_fixed_role_recipe,
)


def _context() -> tuple[CapabilityRegistry, AdaptiveTaskEnvelope]:
    registry = CapabilityRegistry()
    pack = register_long_doc_analysis_capabilities(registry)
    envelope = AdaptiveTaskEnvelope(
        task_id="provenance-task",
        canonical_task_spec_hash="sha256:provenance-contract",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id=pack.pack_id,
        allowed_capability_ids=pack.capability_ids,
        allowed_output_contracts=tuple(
            sorted(
                {
                    registry.get(capability_id).output_contract_version
                    for capability_id in pack.capability_ids
                }
            )
        ),
        allowed_memory_policies=("none", "assist"),
        role_cardinality={
            "retriever": (1, 1),
            "executor": (1, 1),
            "summarizer": (1, 1),
        },
        max_plan_steps=3,
        max_execution_runtime_ms=100_000,
        risk_class=RiskClass.WORKSPACE_WRITE,
    )
    return registry, envelope


def _proposal_and_incomplete_normalization() -> tuple[
    CapabilityRegistry,
    AdaptiveTaskEnvelope,
    PlanProposal,
    PlanProposal,
]:
    registry, envelope = _context()
    proposal = StaticRoleRecipeCompiler().compile(
        envelope.task_id,
        envelope,
        default_fixed_role_recipe(),
    )
    incomplete = replace(
        proposal,
        steps=(
            proposal.steps[0],
            proposal.steps[1],
            replace(
                proposal.steps[2],
                depends_on=("execute",),
                input_ref_ids=(),
                input_ref_kinds=(),
            ),
        ),
    )
    return registry, envelope, incomplete, proposal


def test_required_input_wiring_is_mechanical() -> None:
    registry, envelope, incomplete, _ = _proposal_and_incomplete_normalization()
    normalized, fields = compile_required_input_wiring(incomplete, registry)

    assert normalized.steps[-1].depends_on == ("retrieve", "execute")
    assert fields == (
        "steps.summarize.depends_on.required_input_kind.canonical_evidence_pack",
        "steps.summarize.depends_on.controller_order",
    )
    assert semantic_plan_hash(
        incomplete,
        runtime_task_id=envelope.task_id,
        task_contract_hash=envelope.canonical_task_spec_hash,
    ) != semantic_plan_hash(
        normalized,
        runtime_task_id=envelope.task_id,
        task_contract_hash=envelope.canonical_task_spec_hash,
    )
    assert mechanical_semantic_plan_hash(
        incomplete,
        registry=registry,
    ) == mechanical_semantic_plan_hash(
        normalized,
        registry=registry,
    )

    receipt = PlanNormalizationReceipt.from_proposals(
        incomplete,
        normalized,
        changed_fields=fields,
        runtime_task_id=envelope.task_id,
        task_contract_hash=envelope.canonical_task_spec_hash,
        registry=registry,
    )
    assert receipt.before_semantic_hash == receipt.after_semantic_hash
    assert receipt.source_proposal_hash == incomplete.proposal_hash
    assert receipt.effective_proposal_hash == normalized.proposal_hash
    assert "steps.summarize.depends_on" in receipt.changed_fields


def test_normalization_receipt_rejects_semantic_mutations() -> None:
    registry, envelope, proposal, _ = _proposal_and_incomplete_normalization()
    mutations = (
        replace(
            proposal,
            steps=(
                replace(proposal.steps[0], capability_id="retrieve_table_evidence_v1"),
                *proposal.steps[1:],
            ),
        ),
        replace(
            proposal,
            steps=(
                replace(proposal.steps[0], goal="change the approved goal"),
                *proposal.steps[1:],
            ),
        ),
        replace(
            proposal,
            steps=(
                replace(proposal.steps[0], role="executor"),
                *proposal.steps[1:],
            ),
        ),
        replace(
            proposal,
            steps=(
                replace(
                    proposal.steps[0],
                    completion_criteria={"min_locator_count": 2},
                ),
                *proposal.steps[1:],
            ),
        ),
        replace(
            proposal,
            steps=(
                replace(
                    proposal.steps[0],
                    output_contract_version="statebus.metric_series.v1",
                ),
                *proposal.steps[1:],
            ),
        ),
        replace(
            proposal,
            steps=(
                proposal.steps[0],
                replace(proposal.steps[1], on_failure="fail"),
                *proposal.steps[2:],
            ),
        ),
        replace(
            proposal,
            steps=(
                proposal.steps[0],
                replace(proposal.steps[1], required_input_fields=("metric",)),
                *proposal.steps[2:],
            ),
        ),
        replace(
            proposal,
            steps=(
                replace(proposal.steps[0], depends_on=("execute",)),
                *proposal.steps[1:],
            ),
        ),
        replace(
            proposal,
            steps=(*proposal.steps, replace(proposal.steps[-1], step_id="extra")),
        ),
        replace(proposal, requested_memory_policy="assist"),
        replace(proposal, final_output_contract_version="statebus.metric_series.v1"),
    )

    for candidate in mutations:
        with pytest.raises(PlanProvenanceError, match="mechanical_normalization"):
            PlanNormalizationReceipt.from_proposals(proposal, candidate, registry=registry)

    removed_dependency = replace(
        proposal,
        steps=(
            proposal.steps[0],
            replace(proposal.steps[1], depends_on=()),
            proposal.steps[2],
        ),
    )
    with pytest.raises(PlanProvenanceError, match="removed_dependency"):
        PlanNormalizationReceipt.from_proposals(proposal, removed_dependency, registry=registry)

    with pytest.raises(PlanProvenanceError, match="runtime_task_id_proposal_mismatch"):
        semantic_plan_hash(proposal, runtime_task_id="different-task")

    with pytest.raises(PlanProvenanceError, match="task_contract_hash_identity_mismatch"):
        identity = RuntimeIdentity(
            runtime_task_id=envelope.task_id,
            run_id="run-1",
            session_id="session-1",
            trace_id="trace-1",
            task_contract=TaskContractIdentity.from_hash(envelope.canonical_task_spec_hash),
        )
        semantic_plan_hash(
            proposal,
            task_contract_hash="sha256:other-contract",
            task_identity=identity,
        )


def test_approved_plan_bundle_hash_links_all_provenance() -> None:
    registry, envelope = _context()
    identity = RuntimeIdentity(
        external_case_id="case-17",
        runtime_task_id=envelope.task_id,
        run_id="run-17",
        session_id="session-17",
        trace_id="trace-17",
        task_contract=TaskContractIdentity.from_hash(envelope.canonical_task_spec_hash),
    )
    result = compile_static_role_recipe_plan(
        runtime_task_id=envelope.task_id,
        envelope=envelope,
        recipe=default_fixed_role_recipe(),
        registry=registry,
        runtime_identity=identity,
    )
    bundle = result.approved_plan_bundle

    assert bundle.verify_hash_links()
    assert bundle.source_proposal_hash == result.proposal.proposal_hash
    assert bundle.effective_proposal_hash == result.normalized_proposal.proposal_hash
    assert bundle.normalization_receipt_hash == result.normalization_receipt.receipt_hash
    assert bundle.plan_policy_report_hash == result.policy_report.report_hash
    assert bundle.approved_plan_hash == result.approved_plan.approved_plan_hash
    assert bundle.runtime_task_id == identity.runtime_task_id
    assert bundle.task_contract_hash == identity.task_contract.contract_hash

    with pytest.raises(PlanProvenanceError, match="effective_proposal_hash_mismatch"):
        replace(bundle, effective_proposal_hash="tampered-effective-hash").__post_init__()
    with pytest.raises(PlanProvenanceError, match="normalization_receipt_hash_mismatch"):
        replace(bundle, normalization_receipt_hash="tampered-receipt-hash").__post_init__()
    with pytest.raises(PlanProvenanceError, match="approved_plan_steps_mismatch"):
        tampered_plan = replace(
            bundle.approved_plan,
            steps=tuple(reversed(bundle.approved_plan.steps)),
        )
        replace(
            bundle,
            approved_plan=tampered_plan,
            approved_plan_hash=tampered_plan.approved_plan_hash,
        ).__post_init__()


def test_semantic_replan_creates_new_proposal_plan_and_bundle_hashes() -> None:
    registry, envelope = _context()
    recipe = default_fixed_role_recipe()
    first = compile_static_role_recipe_plan(
        runtime_task_id=envelope.task_id,
        envelope=envelope,
        recipe=recipe,
        registry=registry,
    )
    repeated = compile_static_role_recipe_plan(
        runtime_task_id=envelope.task_id,
        envelope=envelope,
        recipe=recipe,
        registry=registry,
    )
    replanned_recipe = replace(
        recipe,
        recipe_version="v2",
        steps=(
            replace(recipe.steps[0], goal="retrieve the revised evidence scope"),
            *recipe.steps[1:],
        ),
    )
    second = compile_static_role_recipe_plan(
        runtime_task_id=envelope.task_id,
        envelope=envelope,
        recipe=replanned_recipe,
        registry=registry,
    )

    assert first.approved_plan_bundle.canonical_payload() == repeated.approved_plan_bundle.canonical_payload()
    assert first.approved_plan_bundle.bundle_hash == repeated.approved_plan_bundle.bundle_hash
    assert semantic_plan_hash(
        first.proposal,
        runtime_task_id=envelope.task_id,
        task_contract_hash=envelope.canonical_task_spec_hash,
    ) != semantic_plan_hash(
        second.proposal,
        runtime_task_id=envelope.task_id,
        task_contract_hash=envelope.canonical_task_spec_hash,
    )
    assert first.proposal.proposal_id != second.proposal.proposal_id
    assert first.proposal.proposal_hash != second.proposal.proposal_hash
    assert first.policy_report.report_hash != second.policy_report.report_hash
    assert first.approved_plan.approved_plan_hash != second.approved_plan.approved_plan_hash
    assert first.approved_plan_bundle.bundle_hash != second.approved_plan_bundle.bundle_hash
    assert first.approved_plan_bundle.verify_hash_links()
    assert second.approved_plan_bundle.verify_hash_links()
    assert second.approved_plan.plan_policy_report_hash == second.policy_report.report_hash


def test_fallback_provenance_is_not_plain_approval() -> None:
    registry, envelope, rejected, fallback = _proposal_and_incomplete_normalization()
    rejected = replace(
        rejected,
        steps=(
            replace(rejected.steps[0], capability_id="unauthorized-capability"),
            *rejected.steps[1:],
        ),
    )
    validator = PlanPolicyValidator(registry)
    outcome = validator.fallback(rejected, envelope, fallback)
    assert outcome.approved_plan is not None
    assert outcome.fallback_used
    assert outcome.report.status == PlanPolicyStatus.FALLBACK_FIXED_PLAN
    assert outcome.report.proposal_id == rejected.proposal_id

    receipt = PlanNormalizationReceipt.from_proposals(rejected, rejected, registry=registry)
    bundle = ApprovedPlanBundle.from_parts(
        runtime_task_id=envelope.task_id,
        task_contract_hash=envelope.canonical_task_spec_hash,
        source_proposal=rejected,
        effective_proposal=fallback,
        normalization_receipt=receipt,
        plan_policy_report=outcome.report,
        approved_plan=outcome.approved_plan,
        logical_capability_registry_digest=registry.digest,
        fallback_used=True,
        fallback_proposal_hash=fallback.proposal_hash,
    )
    assert bundle.verify_hash_links()
    assert bundle.fallback_used
    assert bundle.fallback_proposal_hash == bundle.effective_proposal_hash


def test_plan_only_static_compilation_stops_at_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    registry, envelope = _context()
    calls: list[str] = []

    def forbidden(name: str):
        def fail(*_args: object, **_kwargs: object) -> None:
            calls.append(name)
            raise AssertionError(f"plan-only compilation invoked {name}")

        return fail

    for target, name in (
        ("statebus.runtime.adaptive_runtime.AdaptiveRuntimeEngine.run", "runtime"),
        ("statebus.runtime.adaptive_runtime.AdaptiveRuntimeEngine._issue_grant", "grant"),
        ("statebus.runtime.adaptive_dispatcher.AdaptiveCapabilityDispatcher.dispatch", "dispatch"),
        ("statebus.runtime.session.RuntimeSessionManager.append_attempt_record", "attempt"),
        ("statebus.runtime.workspace.WorkspaceManager.layout_for_task", "workspace"),
        ("statebus.runtime.role_path.RolePathRunner.propose_plan", "role_llm"),
    ):
        monkeypatch.setattr(target, forbidden(name))

    result = compile_static_role_recipe_plan(
        runtime_task_id=envelope.task_id,
        envelope=envelope,
        recipe=default_fixed_role_recipe(),
        registry=registry,
    )
    assert calls == []
    assert result.approved_plan_bundle.verify_hash_links()
    assert result.approved_plan_bundle.approved_plan is not None


def test_static_plan_source_and_normalizer_cannot_bypass_plan_policy() -> None:
    registry, envelope = _context()
    recipe = default_fixed_role_recipe()
    unauthorized_recipe = replace(
        recipe,
        steps=(
            replace(recipe.steps[0], capability_id="unauthorized-capability"),
            *recipe.steps[1:],
        ),
    )
    proposal = StaticRoleRecipeCompiler().compile(
        envelope.task_id,
        envelope,
        unauthorized_recipe,
    )
    normalized, _ = compile_required_input_wiring(proposal, registry)
    outcome = PlanPolicyValidator(registry).validate(normalized, envelope)

    assert isinstance(proposal, PlanProposal)
    assert isinstance(normalized, PlanProposal)
    assert outcome.approved_plan is None
    assert "unknown_or_unauthorized_capability" in {
        issue.error_code for issue in outcome.report.issues
    }
    with pytest.raises(PlanProvenanceError, match="static_recipe_policy_rejected"):
        compile_static_role_recipe_plan(
            runtime_task_id=envelope.task_id,
            envelope=envelope,
            recipe=unauthorized_recipe,
            registry=registry,
        )
