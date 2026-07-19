from __future__ import annotations

from v2.contracts import Claim, ClaimSet, ClaimSetStatus, RefStatus
from v2.refs import CanonicalEvidencePack, EvidenceItem, ExecutionArtifactRef, FragmentLocator
from v2.runtime.claims import ClaimSetValidator
from v2.runtime.state_consumption import build_state_consumption_record


def test_claim_set_requires_current_evidence_and_verified_numeric_artifact() -> None:
    evidence = CanonicalEvidencePack(
        pack_id="pack", task_id="task", source_doc_hashes=("doc",),
        hard_facts=(EvidenceItem(item_id="e1", bucket="fact", locator=FragmentLocator(fragment_id="e1")),),
    )
    claims = ClaimSet(
        claim_set_id="claims", task_id="task",
        claims=(Claim("c1", "Revenue was 12.", "fact", ("e1",), ("artifact",), ("e1",), {"revenue": 12.0}),),
    )
    assert ClaimSetValidator().validate(claims, evidence_pack=evidence, verified_artifacts={"artifact": {"revenue": 12}}).ok
    record = build_state_consumption_record(
        state_ref_id="state", consumer_role="retriever", consumer_step_id="retrieve", operation="rerank_candidates",
        read_field_ids=("embedding",), input_decision_surface_hash="before", output_decision_surface_hash="after", selected_ids=("e1",),
    )
    assert record.behavioral_effect == "changed"


def test_claim_set_rejects_fabricated_locator() -> None:
    evidence = CanonicalEvidencePack(pack_id="pack", task_id="task", source_doc_hashes=("doc",))
    claims = ClaimSet(claim_set_id="claims", task_id="task", claims=(Claim("c", "claim", "fact", citation_locators=("fake",)),))
    assert not ClaimSetValidator().validate(claims, evidence_pack=evidence, verified_artifacts={}).ok


def test_claims_bind_numeric_values_and_artifacts_to_current_task_and_session() -> None:
    evidence = CanonicalEvidencePack(
        pack_id="pack", task_id="task", source_doc_hashes=("doc",),
        hard_facts=(EvidenceItem(item_id="e1", bucket="fact", locator=FragmentLocator(fragment_id="fragment-1")),),
    )
    artifact = ExecutionArtifactRef(
            artifact_id="artifact", task_id="other-task", step_id="step", artifact_type="json", root_id="root",
            relpath="outputs/result.json", blob_hash="hash", size_bytes=1, produced_by="executor",
            verification_state=RefStatus.VERIFIED, metadata={"session_id": "other-session"},
    )
    claims = ClaimSet(
        claim_set_id="claims", task_id="task",
        claims=(Claim("c", "Revenue was 12.", "fact", ("e1",), ("artifact",), ("fragment-1",), {"revenue": 12.0}),),
    )
    report = ClaimSetValidator().validate(
        claims, evidence_pack=evidence, verified_artifacts={"artifact": (artifact, {"revenue": 12})},
        current_task_id="task", current_session_id="session", evidence_session_id="session",
    )
    assert not report.ok
    assert any("provenance_mismatch" in error for error in report.errors)
    # A numeric claim must be supported by its own artifact, not another verified artifact.
    wrong_numeric = ClaimSet(
        claim_set_id="wrong", task_id="task",
        claims=(Claim("c", "Revenue was 12.", "fact", ("e1",), ("other",), ("fragment-1",), {"revenue": 12.0}),),
    )
    assert not ClaimSetValidator().validate(
        wrong_numeric, evidence_pack=evidence, verified_artifacts={"other": {"revenue": 11}, "artifact": {"revenue": 12}},
    ).ok


def test_insufficient_evidence_and_state_modes_are_explicit() -> None:
    evidence = CanonicalEvidencePack(pack_id="pack", task_id="task", source_doc_hashes=("doc",))
    insufficient = ClaimSet(
        claim_set_id="claims", task_id="task", claims=(), status=ClaimSetStatus.INSUFFICIENT_EVIDENCE,
    )
    report = ClaimSetValidator().validate(insufficient, evidence_pack=evidence, verified_artifacts={})
    assert not report.ok and report.status == ClaimSetStatus.INSUFFICIENT_EVIDENCE
    normal = build_state_consumption_record(
        state_ref_id="state", consumer_role="retriever", consumer_step_id="step", operation="rerank",
        read_field_ids=("embedding",), input_decision_surface_hash="before", output_decision_surface_hash="after", selected_ids=("a",),
        consumed_at_ns=1,
    )
    perturbed = build_state_consumption_record(
        state_ref_id="state", consumer_role="retriever", consumer_step_id="step", operation="rerank",
        read_field_ids=("embedding",), input_decision_surface_hash="before", output_decision_surface_hash="different", selected_ids=("b",),
        consumed_at_ns=2,
    )
    off = build_state_consumption_record(
        state_ref_id="state", consumer_role="retriever", consumer_step_id="step", operation="rerank",
        read_field_ids=(), input_decision_surface_hash="before", output_decision_surface_hash="before", selected_ids=(),
        consumed_at_ns=3,
    )
    assert normal.behavioral_effect == "changed"
    assert perturbed.selected_ids != normal.selected_ids
    assert off.behavioral_effect == "no_effect" and off.read_field_ids == ()
