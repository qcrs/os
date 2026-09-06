from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time

import pytest

from statebus.contracts import (
    BoundCapabilityGrant,
    CapabilityGrant,
    ExecutionBindingReceipt,
    RuntimeIdentity,
    STATE_ACCESS_AUTHORITY_CAPABILITY_INPUT,
    StateAccessContractError,
    StepLifecycleState,
    StorageKind,
    TaskContractIdentity,
)
from statebus.refs import SemanticStateRef
from statebus.runtime.adaptive_runtime import (
    AdaptiveRuntimeError,
    RuntimeStateAccessAuthority,
)
from statebus.runtime.session import RuntimeSessionManager, StepAttemptRecord
from statebus.state import LayeredStateStore, LayeredStoragePolicy, StateRefReuseError


def _active_state_authority(tmp_path: Path) -> tuple[
    RuntimeStateAccessAuthority,
    RuntimeSessionManager,
    SemanticStateRef,
]:
    now_ns = time.time_ns()
    identity = RuntimeIdentity(
        runtime_task_id="task-07a",
        run_id="run-07a",
        session_id="session-07a",
        trace_id="trace-07a",
        task_contract=TaskContractIdentity.from_hash("task-contract-07a"),
    )
    manager = RuntimeSessionManager()
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
            step_id="retrieve",
            attempt_id="attempt-07a",
            owner_role="retriever",
            state=StepLifecycleState.PENDING.value,
        ),
    )
    manager.activate_attempt(
        identity.session_id,
        step_id="retrieve",
        attempt_id="attempt-07a",
    )
    grant = CapabilityGrant(
        grant_id="grant-07a",
        task_id=identity.runtime_task_id,
        session_id=identity.session_id,
        step_id="retrieve",
        attempt_id="attempt-07a",
        capability_id="retrieve-v1",
        capability_version="v1",
        input_ref_ids=("state-input-07a",),
        output_contract_version="evidence-v1",
        workspace_root_id="workspace-07a",
        max_runtime_ms=30_000,
        expires_at_ns=now_ns + 30_000_000_000,
        approved_plan_hash="approved-plan-07a",
    )
    binding = ExecutionBindingReceipt(
        binding_id="binding-07a",
        task_id=identity.runtime_task_id,
        session_id=identity.session_id,
        step_id="retrieve",
        attempt_id="attempt-07a",
        approved_plan_hash="approved-plan-07a",
        logical_capability_id="retrieve-v1",
        logical_capability_version="v1",
        semantic_contract_hash="semantic-contract-07a",
        provider_registry_digest="provider-registry-07a",
        provider_runtime_facts_digest="provider-facts-07a",
        eligibility_projection_hash="eligibility-07a",
        selected_provider_id="retrieval-provider-07a",
        selected_provider_version="v1",
        selected_provider_kind="runtime",
        selected_implementation_kind="retrieval_adapter",
    )
    ref = SemanticStateRef(
        state_id="state-input-07a",
        state_kind="DENSE_SEMANTIC_STATE",
        storage_kind=StorageKind.MMAP_FILE,
        length=16,
        blob_hash="blob-07a",
        manifest_id="manifest-07a",
        metadata={
            "schema_version": "statebus.dense_semantic_state.v1",
            "lease_expires_at_ns": now_ns + 60_000_000_000,
        },
    )
    return (
        RuntimeStateAccessAuthority(
            session_manager=manager,
            runtime_identity=identity,
            bound_grant=BoundCapabilityGrant(grant=grant, execution_binding=binding),
            allow_dense_semantic_intermediate=False,
        ),
        manager,
        ref,
    )


@pytest.mark.parametrize(
    "mismatch",
    (
        "stale_attempt",
        "wrong_attempt",
        "wrong_capability_grant",
        "wrong_execution_binding",
        "wrong_state_identity",
        "expired",
        "unauthorized_runtime_intermediate",
    ),
)
def test_state_access_authority_rejects_before_physical_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    authority, manager, ref = _active_state_authority(tmp_path)
    physical_acquisitions: list[str] = []
    monkeypatch.setattr(
        "statebus.state.query_embedding_from_dense_state",
        lambda **_kwargs: physical_acquisitions.append("acquired"),
    )

    if mismatch == "stale_attempt":
        manager.settle_attempt(
            "session-07a",
            step_id="retrieve",
            attempt_id="attempt-07a",
            terminal_state=StepLifecycleState.FAILED.value,
        )
        with pytest.raises(AdaptiveRuntimeError, match="state_access_attempt_not_active"):
            authority.issue_read(
                ref=ref,
                authority_basis=STATE_ACCESS_AUTHORITY_CAPABILITY_INPUT,
                consumer_role="runtime",
            )
    elif mismatch == "unauthorized_runtime_intermediate":
        with pytest.raises(
            AdaptiveRuntimeError,
            match="runtime_intermediate_state_kind_not_authorized",
        ):
            authority.publish_dense_semantic_state(
                store=object(),
                state_id=ref.state_id,
                query_embedding=object(),
                candidate_embeddings=(),
                hydrate_manifest=object(),
                owner_session_id="session-07a",
            )
    else:
        access_grant = authority.issue_read(
            ref=ref,
            authority_basis=STATE_ACCESS_AUTHORITY_CAPABILITY_INPUT,
            consumer_role="runtime",
        )
        replacements = {
            "wrong_attempt": {"attempt_id": "attempt-other"},
            "wrong_capability_grant": {"capability_grant_hash": "grant-other"},
            "wrong_execution_binding": {"execution_binding_hash": "binding-other"},
            "wrong_state_identity": {"state_identity_hash": "state-other"},
            "expired": {"expires_at_ns": time.time_ns() - 1},
        }
        invalid_access_grant = replace(access_grant, **replacements[mismatch])
        with pytest.raises(StateAccessContractError):
            authority.read_query_embedding(
                ref=ref,
                access_grant=invalid_access_grant,
                embedding_id="query-07a",
                expected_encoder_signature="encoder-07a",
            )

    assert physical_acquisitions == []


def test_layered_state_store_forbids_immutable_ref_reuse(tmp_path: Path) -> None:
    store = LayeredStateStore(
        root=tmp_path / "state",
        policy=LayeredStoragePolicy.for_state_pool_mode("mmap"),
    )
    original = store.publish(
        ref_id="immutable-state-07a",
        object_kind="DENSE_SEMANTIC_STATE",
        payload=b"original-publication",
    )
    original_metadata = original.metadata_path.read_bytes()

    with pytest.raises(StateRefReuseError, match="state_ref_reuse_forbidden"):
        store.publish(
            ref_id="immutable-state-07a",
            object_kind="DENSE_SEMANTIC_STATE",
            payload=b"replacement-forbidden",
        )

    assert store.materializations["immutable-state-07a"] is original
    assert store.load("immutable-state-07a") == b"original-publication"
    assert original.metadata_path.read_bytes() == original_metadata
    store.teardown()
