from __future__ import annotations

from v2.contracts import CLAIM_SET_V2_SCHEMA_VERSION, Claim, ClaimFieldSupport, ClaimSet, ClaimSetStatus, RefStatus
from v2.refs import CanonicalEvidencePack, EvidenceItem, ExecutionArtifactRef, FragmentLocator, TableCellLocator
from v2.runtime.claims import ClaimSetValidator
from v2.runtime.state_consumption import build_state_consumption_record
from v2.utils import sha256_digest


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


def _strict_claim_fixture(*, include_qualifier_source: bool = True, wrong_qualifier_locator: bool = False) -> tuple[ClaimSet, CanonicalEvidencePack, dict[str, object]]:
    table_locator = TableCellLocator(source_doc_hash="doc", table_id="throughput", row_idx=4, col_idx=2)
    qualifier_locator = FragmentLocator(source_doc_hash="doc", fragment_id="operating-constraint")
    evidence = CanonicalEvidencePack(
        pack_id="s4-pack",
        task_id="task",
        source_doc_hashes=("doc",),
        hard_facts=(EvidenceItem(
            item_id="throughput-table",
            bucket="hard_fact",
            locator=table_locator,
            rendered_text="Throughput table: 760 units.",
        ),),
        semantic_contexts=((EvidenceItem(
            item_id="operating-constraint",
            bucket="semantic_context",
            locator=qualifier_locator,
            rendered_text="Capacity-capped pending rail-slot approval.",
        ),) if include_qualifier_source else ()),
    )
    artifact = ExecutionArtifactRef(
        artifact_id="artifact",
        task_id="task",
        step_id="extract",
        artifact_type="json",
        root_id="root",
        relpath="rows.json",
        blob_hash="hash",
        size_bytes=1,
        produced_by="executor",
        verification_state=RefStatus.VERIFIED,
        metadata={"session_id": "session"},
    )
    qualifier_source = repr(table_locator) if wrong_qualifier_locator else repr(qualifier_locator)
    support = (
        ClaimFieldSupport(
            field_path="throughput_units",
            normalized_value_hash=sha256_digest(760),
            support_kind="source_and_verified_artifact",
            evidence_item_ids=("throughput-table",),
            artifact_ref_id="artifact",
            artifact_field_path="rows[0].throughput_units",
            source_locators=(repr(table_locator),),
        ),
        ClaimFieldSupport(
            field_path="shipment_qualifier",
            normalized_value_hash=sha256_digest("capacity-capped pending rail-slot approval"),
            support_kind="source_and_verified_artifact",
            evidence_item_ids=(("operating-constraint",) if include_qualifier_source else ()),
            artifact_ref_id="artifact",
            artifact_field_path="rows[0].shipment_qualifier",
            source_locators=(qualifier_source,),
        ),
    )
    claim = Claim(
        claim_id="s4",
        claim_text="Throughput was 760 units, capacity-capped pending rail-slot approval.",
        claim_type="fact",
        supporting_evidence_item_ids=("throughput-table", "operating-constraint"),
        supporting_artifact_ref_ids=("artifact",),
        citation_locators=(repr(table_locator), repr(qualifier_locator)),
        numeric_fields={"throughput_units": 760.0},
        factual_fields={
            "throughput_units": 760,
            "shipment_qualifier": "capacity-capped pending rail-slot approval",
        },
        field_support=support,
    )
    claim_set = ClaimSet(
        claim_set_id="claims",
        task_id="task",
        claims=(claim,),
        schema_version=CLAIM_SET_V2_SCHEMA_VERSION,
    )
    artifacts = {
        "artifact": (artifact, [{
            "throughput_units": 760,
            "shipment_qualifier": "capacity-capped pending rail-slot approval",
        }]),
    }
    return claim_set, evidence, artifacts


def test_claim_set_v2_requires_field_level_support_for_table_and_qualifier() -> None:
    claims, evidence, artifacts = _strict_claim_fixture()
    report = ClaimSetValidator().validate(
        claims,
        evidence_pack=evidence,
        verified_artifacts=artifacts,
        current_task_id="task",
        current_session_id="session",
        evidence_session_id="session",
    )
    assert report.ok, report.errors


def test_claim_set_v2_rejects_missing_qualifier_source_even_with_verified_artifact() -> None:
    claims, evidence, artifacts = _strict_claim_fixture(include_qualifier_source=False)
    report = ClaimSetValidator().validate(
        claims,
        evidence_pack=evidence,
        verified_artifacts=artifacts,
        current_task_id="task",
        current_session_id="session",
        evidence_session_id="session",
    )
    assert not report.ok
    assert any(error.startswith("claim_field_source_lineage_incomplete:s4:shipment_qualifier") for error in report.errors)


def test_claim_set_v2_rejects_locator_borrowed_from_another_evidence_item() -> None:
    claims, evidence, artifacts = _strict_claim_fixture(wrong_qualifier_locator=True)
    report = ClaimSetValidator().validate(
        claims,
        evidence_pack=evidence,
        verified_artifacts=artifacts,
        current_task_id="task",
        current_session_id="session",
        evidence_session_id="session",
    )
    assert not report.ok
    assert "claim_field_locator_mismatch:s4:shipment_qualifier" in report.errors


def test_claim_set_v2_rejects_value_hash_mismatch() -> None:
    claims, evidence, artifacts = _strict_claim_fixture()
    broken = ClaimSet(
        claim_set_id=claims.claim_set_id,
        task_id=claims.task_id,
        claims=(Claim(
            **{
                **claims.claims[0].__dict__,
                "field_support": (
                    ClaimFieldSupport(
                        **{
                            **claims.claims[0].field_support[0].__dict__,
                            "normalized_value_hash": sha256_digest(759),
                        }
                    ),
                    claims.claims[0].field_support[1],
                ),
            }
        ),),
        schema_version=CLAIM_SET_V2_SCHEMA_VERSION,
    )
    report = ClaimSetValidator().validate(
        broken,
        evidence_pack=evidence,
        verified_artifacts=artifacts,
        current_task_id="task",
        current_session_id="session",
        evidence_session_id="session",
    )
    assert not report.ok
    assert "claim_field_value_hash_mismatch:s4:throughput_units" in report.errors
