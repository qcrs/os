from __future__ import annotations

from dataclasses import replace

from v2.contracts import (
    AdaptiveTaskEnvelope,
    HandoffIntent,
    LatentAnchor,
    LatentHandoffMode,
    NeuralCompatibilitySignature,
    PlanProposal,
    PlanStepProposal,
    RiskClass,
    WorkflowMode,
)
from v2.runtime.capability_registry import CapabilityRegistry
from v2.runtime.domain_packs import register_long_doc_analysis_capabilities
from v2.runtime.latent_handoff import (
    LatentHandoffController,
    LatentHandoffPolicyConfig,
)
from v2.runtime.plan_policy import PlanPolicyValidator
from v2.runtime.role_model_backend import (
    FakeRoleModelBackend,
    LatentCompleteRequest,
    LatentProduceRequest,
)


def _registry_envelope_plan():
    registry = CapabilityRegistry()
    pack = register_long_doc_analysis_capabilities(registry)
    contracts = tuple(sorted({
        registry.get(capability_id).output_contract_version
        for capability_id in pack.capability_ids
    }))
    envelope = AdaptiveTaskEnvelope(
        task_id="task",
        canonical_task_spec_hash="spec",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id=pack.pack_id,
        allowed_capability_ids=pack.capability_ids,
        allowed_output_contracts=contracts,
        allowed_handoff_intents=("auto", "text", "latent_assist"),
        risk_class=RiskClass.WORKSPACE_WRITE,
    )
    proposal = PlanProposal(
        proposal_id="proposal",
        task_id="task",
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                "retrieve",
                "retriever",
                "retrieve_semantic_evidence_v1",
                "find evidence",
                output_contract_version="statebus.evidence_pack.v2",
                completion_criteria={"min_locator_count": 1},
                handoff_intent=HandoffIntent.LATENT_ASSIST,
            ),
            PlanStepProposal(
                "extract",
                "executor",
                "extract_metric_series_v1",
                "extract metric",
                depends_on=("retrieve",),
                output_contract_version="statebus.metric_series.v1",
                completion_criteria={"min_rows": 1},
            ),
            PlanStepProposal(
                "report",
                "summarizer",
                "compose_cited_report_v1",
                "cite",
                depends_on=("retrieve", "extract"),
                output_contract_version="statebus.cited_report.v1",
                completion_criteria={"min_locator_count": 1},
            ),
        ),
    )
    return registry, envelope, proposal


def _decision(
    signature: NeuralCompatibilitySignature,
    *,
    mode: LatentHandoffMode = LatentHandoffMode.PLANNER_ASSIST,
    intent: HandoffIntent = HandoffIntent.LATENT_ASSIST,
):
    backend = FakeRoleModelBackend(signature=signature)
    controller = LatentHandoffController(LatentHandoffPolicyConfig(mode=mode))
    return controller, backend, controller.decide(
        requested_policy=intent,
        producer_role="retriever",
        consumer_role="summarizer",
        evidence_kinds=("narrative", "conflict"),
        evidence_token_estimate=2048,
        exact_artifact_only=False,
        numeric_table_only=False,
        evidence_coverage_complete=True,
        producer_signature=signature,
        consumer_signature=signature,
        plugin_health=backend.health(),
        registry_budget_available=True,
        claim_validator_available=True,
        text_fallback_available=True,
    )


def test_planner_intent_cannot_expand_envelope_authority() -> None:
    registry, envelope, proposal = _registry_envelope_plan()
    restricted = replace(envelope, allowed_handoff_intents=("auto", "text"))

    outcome = PlanPolicyValidator(registry).validate(proposal, restricted)

    assert outcome.approved_plan is None
    assert "handoff_intent_not_allowed" in {
        issue.error_code for issue in outcome.report.issues
    }


def test_latent_gate_defaults_off_and_records_first_failed_check(
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    controller, _backend, decision = _decision(
        neural_signature,
        mode=LatentHandoffMode.OFF,
    )
    assert controller.config.mode == LatentHandoffMode.OFF
    assert decision.effective_policy == "text"
    assert decision.rejection_reason == "mode_enabled"
    assert decision.plugin_health_digest


def test_latent_gate_uses_semantics_and_exact_signature_not_task_identity(
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    _controller, _backend, decision = _decision(neural_signature)
    assert decision.effective_policy == "latent"
    assert all(check.passed for check in decision.checks)
    assert "task" not in {check.name for check in decision.checks}

    incompatible = replace(neural_signature, tokenizer_revision="sha256:other")
    backend = FakeRoleModelBackend(signature=neural_signature)
    controller = LatentHandoffController(
        LatentHandoffPolicyConfig(mode=LatentHandoffMode.FORCE)
    )
    rejected = controller.decide(
        requested_policy=HandoffIntent.AUTO,
        producer_role="retriever",
        consumer_role="summarizer",
        evidence_kinds=("narrative",),
        evidence_token_estimate=2048,
        exact_artifact_only=False,
        numeric_table_only=False,
        evidence_coverage_complete=True,
        producer_signature=neural_signature,
        consumer_signature=incompatible,
        plugin_health=backend.health(),
        registry_budget_available=True,
        claim_validator_available=True,
        text_fallback_available=True,
    )
    assert rejected.effective_policy == "text"
    assert rejected.rejection_reason == "signature_exact_match"


def test_fake_backend_can_never_be_recorded_as_real_latent_consumption(
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    controller, backend, decision = _decision(neural_signature)
    anchor = LatentAnchor(
        evidence_pack_hash="sha256:evidence",
        item_ids=("ev-1",),
        locator_digest="sha256:locators",
    )
    produce = LatentProduceRequest(
        request_id="produce-1",
        task_id="task-1",
        source_step_id="retrieve",
        producer_role="retriever",
        consumer_role="summarizer",
        messages=({"role": "user", "content": "evidence"},),
        latent_steps=8,
        alignment_method="soft_token_topk_v1",
        anchor=anchor,
        ttl_s=60,
        compatibility_signature=neural_signature,
    )

    outcome = controller.run(
        decision=decision,
        backend=backend,
        produce_request=produce,
        complete_request_factory=lambda ref_id: LatentCompleteRequest(
            request_id="complete-1",
            latent_ref_id=ref_id,
            rendered_prompt="anchors<|statebus_latent_v1|>claims",
            response_schema={"type": "object"},
            temperature=0.0,
            max_tokens=128,
            seed=7,
            expected_compatibility_digest=neural_signature.compatibility_digest,
            expected_anchor=anchor,
        ),
        validate_output=lambda _text: True,
        text_fallback=lambda: "text-fallback",
    )

    assert outcome.final_output == "text-fallback"
    assert outcome.latent_attempted is True
    assert outcome.latent_committed is True
    assert outcome.latent_consumed is False
    assert outcome.latent_quality_passed is False
    assert outcome.text_fallback_used is True
    assert outcome.fallback_reason == "latent_consumer_forward_not_observed"
