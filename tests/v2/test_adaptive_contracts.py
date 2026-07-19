from __future__ import annotations

from v2.contracts import (
    AdaptiveTaskEnvelope,
    CapabilityGrant,
    RiskClass,
    WorkflowMode,
)


def test_adaptive_contracts_have_stable_digests() -> None:
    envelope = AdaptiveTaskEnvelope(
        task_id="adaptive-001", canonical_task_spec_hash="spec", workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="long_doc_analysis_v1", allowed_capability_ids=("cap",),
        allowed_output_contracts=("statebus.out.v1",), risk_class=RiskClass.WORKSPACE_WRITE,
    )
    assert envelope.envelope_hash == envelope.envelope_hash
    grant = CapabilityGrant(
        grant_id="grant", task_id="adaptive-001", session_id="session", step_id="step", attempt_id="attempt",
        capability_id="cap", capability_version="v1", input_ref_ids=("input",),
        output_contract_version="statebus.out.v1", workspace_root_id="workspace", max_runtime_ms=1000,
        expires_at_ns=1, approved_plan_hash="plan",
    )
    assert grant.grant_hash == grant.grant_hash
    assert grant.canonical_payload()["schema_version"] == "statebus.capability_grant.v1"

