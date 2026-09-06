from __future__ import annotations

from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
import time

import pytest

from statebus.contracts import (
    BoundCapabilityGrant,
    CapabilityGrant,
    ExecutionBindingReceipt,
    RuntimeIdentity,
    STATE_ACCESS_AUTHORITY_CAPABILITY_INPUT,
    STATE_ACCESS_AUTHORITY_RUNTIME_INTERMEDIATE,
    StepLifecycleState,
    StorageKind,
    TaskContractIdentity,
)
from statebus.memory import DeterministicEmbeddingEncoder
from statebus.refs import FragmentLocator, HydrateManifest, HydrateManifestEntry
from statebus.runtime.adaptive_runtime import (
    AdaptiveRuntimeEngine,
    AdaptiveRuntimeError,
    RuntimeStateAccessAuthority,
)
from statebus.runtime.session import RuntimeSessionManager, StepAttemptRecord
from statebus.state import LayeredStateStore, LayeredStoragePolicy


def _runtime(tmp_path: Path) -> tuple[
    LayeredStateStore,
    RuntimeSessionManager,
    RuntimeIdentity,
]:
    store = LayeredStateStore(
        root=tmp_path / "state",
        policy=LayeredStoragePolicy.for_state_pool_mode("shared_memory"),
    )
    identity = RuntimeIdentity(
        runtime_task_id="task-07b",
        run_id="run-07b",
        session_id="session-07b",
        trace_id="trace-07b",
        task_contract=TaskContractIdentity.from_hash("task-contract-07b"),
    )
    manager = RuntimeSessionManager()
    manager.start(
        session_id=identity.session_id,
        trace_id=identity.trace_id,
        task_id=identity.runtime_task_id,
        layer_name="L3",
        canonical_task_spec_hash=identity.task_contract_hash,
        workspace_root=str(tmp_path / "workspace"),
        state_root=str(store.root),
    )
    return store, manager, identity


def _authority(
    manager: RuntimeSessionManager,
    identity: RuntimeIdentity,
    *,
    step_id: str,
    attempt_id: str,
    provider_id: str,
    input_ref_ids: tuple[str, ...] = (),
    allow_dense_semantic_intermediate: bool = False,
) -> RuntimeStateAccessAuthority:
    manager.append_attempt_record(
        identity.session_id,
        record=StepAttemptRecord(
            task_id=identity.runtime_task_id,
            step_id=step_id,
            attempt_id=attempt_id,
            owner_role="retriever",
            state=StepLifecycleState.PENDING.value,
        ),
    )
    manager.activate_attempt(
        identity.session_id,
        step_id=step_id,
        attempt_id=attempt_id,
    )
    grant = CapabilityGrant(
        grant_id=f"grant-{attempt_id}",
        task_id=identity.runtime_task_id,
        session_id=identity.session_id,
        step_id=step_id,
        attempt_id=attempt_id,
        capability_id="retrieve-v1",
        capability_version="v1",
        input_ref_ids=input_ref_ids,
        output_contract_version="evidence-v1",
        workspace_root_id="workspace-07b",
        max_runtime_ms=30_000,
        expires_at_ns=time.time_ns() + 30_000_000_000,
        approved_plan_hash="approved-plan-07b",
    )
    binding = ExecutionBindingReceipt(
        binding_id=f"binding-{attempt_id}",
        task_id=identity.runtime_task_id,
        session_id=identity.session_id,
        step_id=step_id,
        attempt_id=attempt_id,
        approved_plan_hash="approved-plan-07b",
        logical_capability_id="retrieve-v1",
        logical_capability_version="v1",
        semantic_contract_hash="semantic-contract-07b",
        provider_registry_digest="provider-registry-07b",
        provider_runtime_facts_digest="provider-facts-07b",
        eligibility_projection_hash=f"eligibility-{attempt_id}",
        selected_provider_id=provider_id,
        selected_provider_version="v1",
        selected_provider_kind="runtime",
        selected_implementation_kind="retrieval_adapter",
    )
    return RuntimeStateAccessAuthority(
        session_manager=manager,
        runtime_identity=identity,
        bound_grant=BoundCapabilityGrant(grant=grant, execution_binding=binding),
        allow_dense_semantic_intermediate=allow_dense_semantic_intermediate,
    )


def _publish(
    store: LayeredStateStore,
    authority: RuntimeStateAccessAuthority,
    identity: RuntimeIdentity,
    *,
    state_id: str,
):
    encoder = DeterministicEmbeddingEncoder(dims=8)
    query = encoder.encode(embedding_id="query-07b", text="revenue outlook")
    candidates = (
        encoder.encode(embedding_id="candidate-a", text="revenue increased"),
        encoder.encode(embedding_id="candidate-b", text="cost increased"),
    )
    manifest = HydrateManifest(
        manifest_id=f"manifest-{state_id}",
        source_doc_hashes=("doc-07b",),
        entries=tuple(
            HydrateManifestEntry(
                row_idx=index,
                candidate_id=f"candidate-{index}",
                locator=FragmentLocator(
                    source_doc_hash="doc-07b",
                    fragment_id=f"fragment-{index}",
                    extractor_version="test-v1",
                ),
                stable_key=f"fragment-{index}",
                byte_hint=32,
                importance_score=0.8,
            )
            for index in (1, 2)
        ),
        canonicalizer_version="canon-v1",
        extractor_version="test-v1",
    )
    publication = authority.publish_dense_semantic_state(
        store=store,
        state_id=state_id,
        query_embedding=query,
        candidate_embeddings=candidates,
        hydrate_manifest=manifest,
        owner_session_id=identity.session_id,
        encoder_revision="deterministic-v1",
    )
    return publication


def test_authorized_pin_defers_shared_memory_reclaim_until_unpin(
    tmp_path: Path,
) -> None:
    store, manager, identity = _runtime(tmp_path)
    authority = _authority(
        manager,
        identity,
        step_id="produce",
        attempt_id="attempt-a",
        provider_id="provider-a",
        allow_dense_semantic_intermediate=True,
    )
    publication = _publish(store, authority, identity, state_id="state-pin-protects")
    access_grant = authority.issue_read(
        ref=publication.ref,
        authority_basis=STATE_ACCESS_AUTHORITY_RUNTIME_INTERMEDIATE,
        consumer_role="runtime",
    )
    pin = authority.acquire_pin(
        store=store,
        ref=publication.ref,
        access_grant=access_grant,
        consumer_role="runtime",
    )
    lifetime = store.lifetimes[publication.ref.state_id]

    assert publication.handle.storage_kind == StorageKind.SHARED_MEMORY
    assert store.release_owner(
        publication.ref.state_id,
        owner_session_id=identity.session_id,
    )
    assert lifetime.owner_released
    assert lifetime.live_pin_count == 1
    assert not lifetime.physical_reclaimed
    assert store.load(publication.ref.state_id) == bytes(
        store._shared_segments[publication.ref.state_id].buf[
            : publication.handle.size_bytes
        ]
    )
    probe = SharedMemory(name=publication.handle.shared_memory_name)
    probe.close()

    assert authority.unpin(store=store, pin_id=pin.pin_id)
    assert lifetime.live_pin_count == 0
    assert lifetime.physical_reclaimed
    assert publication.ref.state_id not in store.materializations
    with pytest.raises(FileNotFoundError):
        SharedMemory(name=publication.handle.shared_memory_name)
    store.teardown()


def test_owner_release_and_unpin_are_idempotent(tmp_path: Path) -> None:
    store, manager, identity = _runtime(tmp_path)
    authority = _authority(
        manager,
        identity,
        step_id="produce",
        attempt_id="attempt-a",
        provider_id="provider-a",
        allow_dense_semantic_intermediate=True,
    )
    publication = _publish(store, authority, identity, state_id="state-idempotent")
    access_grant = authority.issue_read(
        ref=publication.ref,
        authority_basis=STATE_ACCESS_AUTHORITY_RUNTIME_INTERMEDIATE,
        consumer_role="runtime",
    )
    pin = authority.acquire_pin(
        store=store,
        ref=publication.ref,
        access_grant=access_grant,
        consumer_role="runtime",
    )
    lifetime = store.lifetimes[publication.ref.state_id]

    assert store.release_owner(
        publication.ref.state_id,
        owner_session_id=identity.session_id,
    )
    assert not store.release_owner(
        publication.ref.state_id,
        owner_session_id=identity.session_id,
    )
    assert authority.unpin(store=store, pin_id=pin.pin_id)
    assert not authority.unpin(store=store, pin_id=pin.pin_id)
    assert lifetime.live_pin_count == 0
    assert lifetime.physical_reclaimed
    assert store.shared_memory_bytes_used == 0
    assert not store.release_owner(
        publication.ref.state_id,
        owner_session_id=identity.session_id,
    )
    store.teardown()


def test_attempt_settlement_cleans_own_pin_and_preserves_other_consumer(
    tmp_path: Path,
) -> None:
    store, manager, identity = _runtime(tmp_path)
    authority_a = _authority(
        manager,
        identity,
        step_id="consumer-a",
        attempt_id="attempt-a",
        provider_id="provider-a",
        allow_dense_semantic_intermediate=True,
    )
    publication = _publish(store, authority_a, identity, state_id="state-shared")
    authority_b = _authority(
        manager,
        identity,
        step_id="consumer-b",
        attempt_id="attempt-b",
        provider_id="provider-b",
        input_ref_ids=(publication.ref.state_id,),
    )
    access_a = authority_a.issue_read(
        ref=publication.ref,
        authority_basis=STATE_ACCESS_AUTHORITY_RUNTIME_INTERMEDIATE,
        consumer_role="runtime",
    )
    access_b = authority_b.issue_read(
        ref=publication.ref,
        authority_basis=STATE_ACCESS_AUTHORITY_CAPABILITY_INPUT,
        consumer_role="runtime",
    )
    pin_a = authority_a.acquire_pin(
        store=store,
        ref=publication.ref,
        access_grant=access_a,
        consumer_role="runtime",
    )
    pin_b = authority_b.acquire_pin(
        store=store,
        ref=publication.ref,
        access_grant=access_b,
        consumer_role="runtime",
    )
    lifetime = store.lifetimes[publication.ref.state_id]

    AdaptiveRuntimeEngine._settle_attempt(
        session_manager=manager,
        session_id=identity.session_id,
        step_id="consumer-a",
        attempt_id="attempt-a",
        terminal_state=StepLifecycleState.COMPLETED.value,
        completed_at_ns=time.time_ns(),
        lifecycle_origin="LOCAL_RUNTIME",
        state_access_authority=authority_a,
        state_store=store,
    )

    assert pin_a.pin_id in lifetime.released_pins
    assert pin_b.pin_id in lifetime.live_pins
    assert lifetime.live_pin_count == 1
    assert not lifetime.owner_released
    assert not lifetime.physical_reclaimed
    assert publication.ref.state_id in store.materializations
    with pytest.raises(AdaptiveRuntimeError, match="state_access_attempt_not_active"):
        authority_a.acquire_pin(
            store=store,
            ref=publication.ref,
            access_grant=access_a,
            consumer_role="runtime",
        )

    assert store.release_owner(
        publication.ref.state_id,
        owner_session_id=identity.session_id,
    )
    assert publication.ref.state_id in store.materializations
    assert authority_b.unpin(store=store, pin_id=pin_b.pin_id)
    assert lifetime.physical_reclaimed
    assert publication.ref.state_id not in store.materializations
    store.teardown()
