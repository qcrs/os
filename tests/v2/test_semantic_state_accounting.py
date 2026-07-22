from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from v2.control import (
    ControlHeader,
    ErrorResult,
    EventType,
    ExecRequest,
    RefHandle,
    SubprocessExecutorTransport,
    SuccessResult,
)
from v2.memory import StructuredEmbedding
from v2.refs import FragmentLocator, HydrateManifest, HydrateManifestEntry
from v2.runtime.state_consumption import (
    StateConsumptionValidationError,
    build_state_consumption_record,
    close_state_consumption_record,
    summarize_state_consumption,
    validate_state_consumption_record,
)
from v2.state import LayeredStateStore, LayeredStoragePolicy, publish_dense_semantic_state
from v2.utils import sha256_digest, stable_json_dumps


def _embedding(embedding_id: str, vector: tuple[float, float]) -> StructuredEmbedding:
    return StructuredEmbedding(
        embedding_id=embedding_id,
        vector=vector,
        dims=2,
        source_text_hash=sha256_digest({"embedding_id": embedding_id}),
        encoding="semantic-accounting-fixture-v1",
    )


def _publication(
    root: Path,
    *,
    state_id: str,
    query_vector: tuple[float, float],
    candidate_order: tuple[str, str] = ("candidate-a", "candidate-b"),
):
    vectors = {
        "candidate-a": (1.0, 0.0),
        "candidate-b": (0.0, 1.0),
    }
    manifest = HydrateManifest(
        manifest_id=f"manifest-{state_id}",
        source_doc_hashes=("doc-semantic-accounting",),
        entries=tuple(
            HydrateManifestEntry(
                row_idx=index,
                candidate_id=candidate_id,
                locator=FragmentLocator(
                    source_doc_hash="doc-semantic-accounting",
                    fragment_id=candidate_id,
                    extractor_version="fixture-v1",
                ),
                stable_key=candidate_id,
                byte_hint=32,
                importance_score=1.0,
            )
            for index, candidate_id in enumerate(candidate_order, start=1)
        ),
        canonicalizer_version="fixture-v1",
        extractor_version="fixture-v1",
    )
    store = LayeredStateStore(
        root=root / state_id,
        policy=LayeredStoragePolicy.for_state_pool_mode("mmap"),
    )
    publication = publish_dense_semantic_state(
        store=store,
        state_id=state_id,
        query_embedding=_embedding(f"query-{state_id}", query_vector),
        candidate_embeddings=tuple(
            _embedding(candidate_id, vectors[candidate_id])
            for candidate_id in candidate_order
        ),
        hydrate_manifest=manifest,
        owner_session_id="semantic-accounting-session",
        encoder_revision="fixture-v1",
    )
    return store, publication


def _consume(root: Path, publication, *, expected_signature: str = ""):
    request = ExecRequest(
        header=ControlHeader(
            trace_id=f"trace-{publication.ref.state_id}",
            task_id="semantic-accounting-task",
            step_id="retrieve",
            attempt_id="attempt-1",
            target_role="executor",
            timeout_ms=20_000,
            event_type=EventType.REQ_EXEC,
        ),
        state_refs=(
            RefHandle(ref_id=publication.ref.state_id, ref_kind="semantic_state"),
        ),
        runtime_reuse_contract="semantic_state_required",
        output_contract_version="statebus.evidence_selection.v1",
        workspace_root=str(root / "workspace"),
        input_manifest_hash=publication.contract.hydrate_manifest_hash,
        operation="semantic_select_v1",
        state_root=str(publication.manifest_path.parent.parent),
        hydrate_manifest_id=publication.contract.hydrate_manifest_id,
        semantic_top_k=1,
        evidence_budget_bytes=64,
        expected_encoder_signature=(
            expected_signature or publication.contract.encoder_signature
        ),
        capability_grant_hash="semantic-accounting-grant",
    )
    return SubprocessExecutorTransport(
        socket_path=root / f"{publication.ref.state_id}.sock",
        timeout_s=20.0,
    ).execute(request)


def _closed_record(publication, selection: SuccessResult):
    output_hash = sha256_digest({
        "selected_candidate_ids": selection.selected_candidate_ids,
        "selected_scores": selection.selected_scores,
    })
    record = build_state_consumption_record(
        state_ref_id=publication.ref.state_id,
        consumer_role="executor",
        consumer_step_id="retrieve",
        operation="cosine_topk_budget_pruning",
        read_field_ids=tuple(
            f"row:{index}" for index in (0, *selection.selected_row_indices)
        ),
        input_decision_surface_hash=sha256_digest({
            "manifest_hash": publication.contract.hydrate_manifest_hash,
        }),
        output_decision_surface_hash=output_hash,
        selected_ids=selection.selected_candidate_ids,
        downstream_ref_ids=("evidence:semantic-accounting-task:retrieve",),
        logical_owner_role="retriever",
        logical_step_id="retrieve",
        producer_role="retriever",
        producer_pid=selection.producer_pid,
        physical_consumer_component="runtime_semantic_selector",
        physical_consumer_pid=selection.consumer_pid,
        physical_consumer_uid=os.getuid(),
        downstream_role="executor",
        logical_target_role="executor",
        downstream_hydration_roles=("executor",),
        hydrate_manifest_id=publication.contract.hydrate_manifest_id,
        hydrate_manifest_hash=publication.contract.hydrate_manifest_hash,
        hydration_receipt_id=(
            f"state-hydration:{publication.ref.state_id}:retrieve:attempt-1"
        ),
    )
    return close_state_consumption_record(
        record,
        released_by_component="runtime_semantic_state_owner",
        release_reason="selection_hydrated",
    )


def test_semantic_state_s1_cross_pid_hydration_and_release_are_one_closed_record(
    tmp_path: Path,
) -> None:
    store, publication = _publication(
        tmp_path,
        state_id="semantic-s1",
        query_vector=(1.0, 0.0),
    )
    selection = _consume(tmp_path, publication)
    assert isinstance(selection, SuccessResult)
    assert selection.selected_candidate_ids == ("candidate-a",)
    assert selection.producer_pid == os.getpid()
    assert selection.consumer_pid != selection.producer_pid

    store.release(publication.ref.state_id)
    record = _closed_record(publication, selection)
    accounting = summarize_state_consumption([record])

    assert record.producer_role == "retriever"
    assert record.physical_consumer_component == "runtime_semantic_selector"
    assert record.logical_target_role == "executor"
    assert record.downstream_hydration_roles == ("executor",)
    assert record.hydration_receipt_hash
    assert record.release_receipt_hash
    assert accounting["hydrated_count"] == 1
    assert accounting["released_count"] == 1
    assert accounting["cross_process_count"] == 1
    assert accounting["producer_pids"] == [os.getpid()]
    assert accounting["physical_consumer_pids"] == [selection.consumer_pid]
    assert publication.ref.state_id not in store.materializations


def test_semantic_state_s2_perturbation_changes_selected_id_but_matching_permutation_does_not(
    tmp_path: Path,
) -> None:
    normal_store, normal = _publication(
        tmp_path,
        state_id="semantic-s2-normal",
        query_vector=(1.0, 0.0),
    )
    perturbed_store, perturbed = _publication(
        tmp_path,
        state_id="semantic-s2-perturbed",
        query_vector=(0.0, 1.0),
    )
    permuted_store, permuted = _publication(
        tmp_path,
        state_id="semantic-s2-permuted",
        query_vector=(1.0, 0.0),
        candidate_order=("candidate-b", "candidate-a"),
    )
    try:
        normal_selection = _consume(tmp_path, normal)
        perturbed_selection = _consume(tmp_path, perturbed)
        permuted_selection = _consume(tmp_path, permuted)
        assert isinstance(normal_selection, SuccessResult)
        assert isinstance(perturbed_selection, SuccessResult)
        assert isinstance(permuted_selection, SuccessResult)
        assert normal_selection.selected_candidate_ids == ("candidate-a",)
        assert perturbed_selection.selected_candidate_ids == ("candidate-b",)
        assert permuted_selection.selected_candidate_ids == ("candidate-a",)
        assert sha256_digest(normal_selection.selected_candidate_ids) != sha256_digest(
            perturbed_selection.selected_candidate_ids
        )
    finally:
        normal_store.teardown()
        perturbed_store.teardown()
        permuted_store.teardown()


def test_semantic_state_s3_wrong_signature_and_manifest_fail_closed_then_release(
    tmp_path: Path,
) -> None:
    wrong_signature_store, wrong_signature = _publication(
        tmp_path,
        state_id="semantic-s3-signature",
        query_vector=(1.0, 0.0),
    )
    result = _consume(tmp_path, wrong_signature, expected_signature="wrong-signature")
    assert isinstance(result, ErrorResult)
    assert "encoder_signature_mismatch" in result.error_detail
    wrong_signature_store.release(wrong_signature.ref.state_id)
    assert wrong_signature.ref.state_id not in wrong_signature_store.materializations

    manifest_store, bad_manifest = _publication(
        tmp_path,
        state_id="semantic-s3-manifest",
        query_vector=(1.0, 0.0),
    )
    manifest_payload = json.loads(bad_manifest.manifest_path.read_text(encoding="utf-8"))
    manifest_payload["entries"][0]["candidate_id"] = "candidate-tampered"
    bad_manifest.manifest_path.write_text(
        stable_json_dumps(manifest_payload) + "\n",
        encoding="utf-8",
    )
    result = _consume(tmp_path, bad_manifest)
    assert isinstance(result, ErrorResult)
    assert "hydrate_manifest_hash_mismatch" in result.error_detail
    manifest_store.release(bad_manifest.ref.state_id)
    assert bad_manifest.ref.state_id not in manifest_store.materializations


def test_semantic_accounting_rejects_same_pid_and_tampered_hydration_receipt() -> None:
    with pytest.raises(
        StateConsumptionValidationError,
        match="state_consumer_not_cross_process",
    ):
        build_state_consumption_record(
            state_ref_id="state",
            consumer_role="executor",
            consumer_step_id="retrieve",
            operation="cosine_topk_budget_pruning",
            read_field_ids=("row:0", "row:1"),
            input_decision_surface_hash="before",
            output_decision_surface_hash="after",
            selected_ids=("candidate-a",),
            producer_role="retriever",
            producer_pid=42,
            physical_consumer_component="runtime_semantic_selector",
            physical_consumer_pid=42,
            logical_target_role="executor",
            downstream_hydration_roles=("executor",),
            hydrate_manifest_hash="manifest-hash",
            hydration_receipt_id="hydration-receipt",
        )

    record = build_state_consumption_record(
        state_ref_id="state",
        consumer_role="executor",
        consumer_step_id="retrieve",
        operation="cosine_topk_budget_pruning",
        read_field_ids=("row:0", "row:1"),
        input_decision_surface_hash="before",
        output_decision_surface_hash="after",
        selected_ids=("candidate-a",),
        producer_role="retriever",
        producer_pid=41,
        physical_consumer_component="runtime_semantic_selector",
        physical_consumer_pid=42,
        logical_target_role="executor",
        downstream_hydration_roles=("executor",),
        hydrate_manifest_hash="manifest-hash",
        hydration_receipt_id="hydration-receipt",
    )
    with pytest.raises(
        StateConsumptionValidationError,
        match="state_hydration_receipt_hash_mismatch",
    ):
        validate_state_consumption_record(
            replace(record, hydration_receipt_hash="tampered"),
            require_release=False,
        )

    closed = close_state_consumption_record(
        record,
        released_by_component="runtime_semantic_state_owner",
        release_reason="selection_hydrated",
    )
    with pytest.raises(
        StateConsumptionValidationError,
        match="state_release_receipt_hash_mismatch",
    ):
        validate_state_consumption_record(
            replace(closed, release_receipt_hash="tampered"),
            require_release=True,
        )
    with pytest.raises(
        StateConsumptionValidationError,
        match="state_release_receipt_missing",
    ):
        validate_state_consumption_record(
            replace(closed, release_reason=""),
            require_release=True,
        )
