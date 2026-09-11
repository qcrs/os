from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from statebus.control import (
    ErrorResult,
    SubprocessExecutorTransport,
    SuccessResult,
)
from statebus.control.transport import SubprocessTransportTimeout, effective_unix_socket_path
from statebus.contracts import STATE_ACCESS_AUTHORITY_CAPABILITY_INPUT, StepLifecycleState
from statebus.memory import DeterministicEmbeddingEncoder
from statebus.refs import FragmentLocator, HydrateManifest, HydrateManifestEntry
from statebus.runtime.identity import new_run_id, resolve_runtime_identity
from statebus.runtime.adaptive_runtime import AdaptiveRuntimeError, RuntimeStateAccessAuthority
from statebus.runtime.session import RuntimeSessionManager
from statebus.runtime.smoke import _build_legacy_semantic_consumer_request
from statebus.state import (
    LayeredStateStore,
    LayeredStoragePolicy,
    SemanticStateValidationError,
    publish_dense_semantic_state,
    resolve_dense_semantic_state,
    select_dense_semantic_state,
)


def _semantic_state(tmp_path: Path, *, mode: str = "shared_memory"):
    encoder = DeterministicEmbeddingEncoder(dims=16)
    query = encoder.encode(embedding_id="query", text="revenue growth outlook")
    texts = (
        "revenue growth outlook",
        "network timeout incident",
        "revenue forecast improved",
    )
    candidates = tuple(
        encoder.encode(embedding_id=f"candidate-{index}", text=text)
        for index, text in enumerate(texts, start=1)
    )
    manifest = HydrateManifest(
        manifest_id="manifest-cross-process",
        source_doc_hashes=("doc-hash",),
        entries=tuple(
            HydrateManifestEntry(
                row_idx=index,
                candidate_id=f"candidate-{index}",
                bucket="semantic_context",
                locator=FragmentLocator(
                    source_doc_hash="doc-hash",
                    fragment_id=f"fragment-{index}",
                    extractor_version="test-v1",
                ),
                stable_key=f"fragment-{index}",
                byte_hint=(40, 60, 50)[index - 1],
                importance_score=0.9,
            )
            for index in range(1, 4)
        ),
        canonicalizer_version="canon-v1",
        extractor_version="test-v1",
    )
    store = LayeredStateStore(
        root=tmp_path / "state",
        policy=LayeredStoragePolicy.for_state_pool_mode(mode),
    )
    comparator_identity = resolve_runtime_identity(
        task_id="task-semantic",
        trace_id=new_run_id(prefix="trace-semantic"),
        canonical_task_spec_hash="sha256:test-semantic-task-contract",
        run_id=new_run_id(prefix="legacy-comparator-run"),
        session_id=new_run_id(prefix="legacy-comparator-session"),
    )
    publication = publish_dense_semantic_state(
        store=store,
        state_id="dense-cross-process",
        query_embedding=query,
        candidate_embeddings=candidates,
        hydrate_manifest=manifest,
        owner_session_id=comparator_identity.session_id,
        encoder_revision="deterministic-v1",
    )
    return store, publication, comparator_identity


def _consumer_request(
    tmp_path: Path,
    store: LayeredStateStore,
    publication,
    comparator_identity,
    *,
    suffix: str,
    top_k: int = 2,
    evidence_budget_bytes: int = 100,
    socket_path: Path | None = None,
):
    configured_socket_path = socket_path or tmp_path / f"semantic-{suffix}.sock"
    transport = SubprocessExecutorTransport(
        socket_path=effective_unix_socket_path(configured_socket_path.absolute()),
        timeout_s=20.0,
    )
    authority, request = _build_legacy_semantic_consumer_request(
        comparator_identity=comparator_identity,
        publication=publication,
        state_store=store,
        runtime_root=tmp_path / f"runtime-{suffix}",
        semantic_top_k=top_k,
        evidence_budget_bytes=evidence_budget_bytes,
        transport=transport,
    )
    return transport, authority, request


def _pin_request(store, publication, authority, request):
    return authority.acquire_pin(
        store=store,
        ref=publication.ref,
        access_grant=request.state_access_grants[0],
        consumer_role="executor",
        physical_invocation_id=request.header.invocation_id,
    )


def _settle(authority, request, terminal_state: str) -> None:
    authority.session_manager.settle_attempt(
        request.header.session_id,
        step_id=request.header.step_id,
        attempt_id=request.header.attempt_id,
        terminal_state=terminal_state,
        lifecycle_origin="LOCAL_RUNTIME",
    )


@pytest.mark.parametrize("mode", ["shared_memory", "mmap"])
def test_typed_uds_worker_resolves_and_consumes_dense_state_in_another_pid(
    tmp_path: Path,
    mode: str,
) -> None:
    store, publication, comparator_identity = _semantic_state(tmp_path, mode=mode)
    try:
        reference = select_dense_semantic_state(
            state_root=store.root,
            ref=publication.ref,
            manifest_id=publication.ref.manifest_id,
            top_k=2,
            evidence_budget_bytes=100,
            expected_encoder_signature=publication.ref.compatibility_hint,
        )
        transport, authority, request = _consumer_request(
            tmp_path,
            store,
            publication,
            comparator_identity,
            suffix=mode,
        )
        access_grant = request.state_access_grants[0]
        bound_grant = authority.bound_grant
        assert request.header.run_id == comparator_identity.run_id
        assert request.header.session_id != comparator_identity.session_id
        assert request.header.execution_binding_hash == bound_grant.execution_binding_hash
        assert request.header.execution_binding_hash == access_grant.execution_binding_hash
        assert request.header.capability_grant_hash == request.capability_grant_hash
        assert request.header.capability_grant_hash == bound_grant.grant.grant_hash
        assert request.header.capability_grant_hash == access_grant.capability_grant_hash
        assert request.header.invocation_id == access_grant.physical_invocation_id
        assert access_grant.authority_basis == STATE_ACCESS_AUTHORITY_CAPABILITY_INPUT
        pin = _pin_request(store, publication, authority, request)
        assert pin.pin_id in store.lifetimes[publication.ref.state_id].live_pins
        responses = transport.exchange_sequence(request)
        assert [response.header.event_type.name for response in responses] == [
            "ACK_RECV",
            "RUN_START",
            "HEARTBEAT",
            "RES_SUCC",
        ]
        result = responses[-1]
        assert isinstance(result, SuccessResult)
        assert result.consumed_state_ref_id == publication.ref.state_id
        assert result.selected_candidate_ids == reference.selected_candidate_ids
        assert result.selected_scores == reference.selected_scores
        assert result.selected_row_indices == reference.selected_row_indices
        assert result.consumer_pid != os.getpid()
        assert result.consumer_pid != result.producer_pid
        assert result.producer_pid == os.getpid()
        assert result.encoder_signature == publication.ref.compatibility_hint
        assert transport.last_exchange_audit is not None
        assert result.consumer_pid == transport.last_exchange_audit.worker_pid
        terminal_receipts = tuple(
            receipt for receipt in transport.last_admission_receipts if receipt.terminal
        )
        assert len(terminal_receipts) == 1
        assert terminal_receipts[0].admitted
        attempt_receipt = authority.session_manager.admit_attempt_result(
            request.header.session_id,
            step_id=request.header.step_id,
            observed_attempt_id=result.header.attempt_id,
            invocation_id=result.header.invocation_id,
        )
        assert attempt_receipt.commit_authorized
        assert authority.unpin(store=store, pin_id=pin.pin_id)

        runtime_access = authority.issue_read(
            ref=publication.ref,
            authority_basis=STATE_ACCESS_AUTHORITY_CAPABILITY_INPUT,
            consumer_role="runtime",
        )
        query = authority.read_query_embedding(
            ref=publication.ref,
            access_grant=runtime_access,
            embedding_id="query",
            expected_encoder_signature=publication.ref.compatibility_hint,
            store=store,
        )
        assert query.embedding_id == "query"
        assert query.dims == 16
        _settle(authority, request, StepLifecycleState.COMPLETED.value)
        assert store.lifetimes[publication.ref.state_id].live_pin_count == 0

        # A consumer only closes its mapping. The producer remains owner and
        # can resolve the state again until explicit release.
        with resolve_dense_semantic_state(state_root=store.root, ref=publication.ref) as resolved:
            assert resolved.matrix.shape == (4, 16)
    finally:
        store.teardown()


def test_semantic_consumer_rejects_wrong_encoder_and_owner_release_removes_payload(
    tmp_path: Path,
) -> None:
    store, publication, comparator_identity = _semantic_state(tmp_path)
    transport, authority, valid_request = _consumer_request(
        tmp_path,
        store,
        publication,
        comparator_identity,
        suffix="wrong-encoder",
        top_k=1,
    )
    request = replace(valid_request, expected_encoder_signature="wrong-encoder")
    pin = _pin_request(store, publication, authority, request)
    try:
        result = transport.execute(request)
        assert isinstance(result, ErrorResult)
        assert result.error_code == "semantic_state_consume_failed"
        assert "encoder_signature_mismatch" in result.error_detail
    finally:
        authority.unpin(store=store, pin_id=pin.pin_id)
        _settle(authority, request, StepLifecycleState.FAILED.value)
        store.release_owner(
            publication.ref.state_id,
            owner_session_id=comparator_identity.session_id,
        )

    with pytest.raises(SemanticStateValidationError, match="payload_missing"):
        resolve_dense_semantic_state(state_root=store.root, ref=publication.ref)


def test_semantic_consumer_uses_effective_socket_for_snapshot_and_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, publication, comparator_identity = _semantic_state(tmp_path)
    configured_socket = (
        tmp_path
        / ("deep-runtime-segment-" * 8)
        / "semantic-consumer.sock"
    )
    expected_socket = effective_unix_socket_path(configured_socket.absolute())
    observed: dict[str, object] = {}

    from statebus.runtime.provider_registry import ExecutionProviderRegistry
    import statebus.control.transport as transport_module

    original_resolve_bound = ExecutionProviderRegistry.resolve_bound
    original_popen = transport_module.subprocess.Popen

    def observed_resolve_bound(self, **kwargs):
        resolved = original_resolve_bound(self, **kwargs)
        observed["implementation"] = resolved.implementation
        return resolved

    def observed_popen(command, **kwargs):
        observed["worker_socket"] = Path(command[command.index("--socket-path") + 1])
        return original_popen(command, **kwargs)

    monkeypatch.setattr(ExecutionProviderRegistry, "resolve_bound", observed_resolve_bound)
    monkeypatch.setattr(transport_module.subprocess, "Popen", observed_popen)
    transport, authority, request = _consumer_request(
        tmp_path,
        store,
        publication,
        comparator_identity,
        suffix="effective-socket",
        socket_path=configured_socket,
    )
    pin = _pin_request(store, publication, authority, request)
    try:
        result = transport.execute(request)
        assert isinstance(result, SuccessResult)
        implementation = observed["implementation"]
        assert transport.socket_path == expected_socket
        assert observed["worker_socket"] == expected_socket
        assert implementation.endpoint_origin == f"unix://{expected_socket.resolve()}"
    finally:
        authority.unpin(store=store, pin_id=pin.pin_id)
        _settle(authority, request, StepLifecycleState.COMPLETED.value)
        store.release_owner(
            publication.ref.state_id,
            owner_session_id=comparator_identity.session_id,
        )
        store.teardown()


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    (
        ("header_body_grant_mismatch", "capability_grant_hash_mismatch"),
        ("header_body_grant_changed_without_read", "state_access_capability_grant_mismatch"),
        ("missing_scope", "run_id_missing"),
        ("missing_read", "state_access_grant_count_invalid"),
        ("wrong_binding", "state_access_execution_binding_mismatch"),
        ("wrong_provider", "state_access_consumer_mismatch"),
        ("wrong_role", "state_access_consumer_mismatch"),
        ("wrong_invocation", "state_access_invocation_mismatch"),
        ("wrong_state_identity", "state_access_identity_mismatch"),
        ("expired", "state_access_expired"),
    ),
)
def test_semantic_consumer_authority_mutations_fail_closed(
    tmp_path: Path,
    mutation: str,
    expected_error: str,
) -> None:
    store, publication, comparator_identity = _semantic_state(tmp_path)
    transport, authority, request = _consumer_request(
        tmp_path,
        store,
        publication,
        comparator_identity,
        suffix=mutation,
    )
    access_grant = request.state_access_grants[0]
    pin = _pin_request(store, publication, authority, request)
    if mutation == "header_body_grant_mismatch":
        request = replace(request, capability_grant_hash="sha256:wrong-grant")
    elif mutation == "header_body_grant_changed_without_read":
        request = replace(
            request,
            header=replace(request.header, capability_grant_hash="sha256:wrong-grant"),
            capability_grant_hash="sha256:wrong-grant",
        )
    elif mutation == "missing_scope":
        request = replace(request, header=replace(request.header, run_id=""))
    elif mutation == "missing_read":
        request = replace(request, state_access_grants=())
    elif mutation == "wrong_binding":
        request = replace(
            request,
            state_access_grants=(replace(access_grant, execution_binding_hash="sha256:wrong-binding"),),
        )
    elif mutation == "wrong_provider":
        request = replace(request, consumer_provider_id="wrong-provider")
    elif mutation == "wrong_role":
        request = replace(request, header=replace(request.header, target_role="retriever"))
    elif mutation == "wrong_invocation":
        request = replace(
            request,
            state_access_grants=(replace(access_grant, physical_invocation_id="wrong-invocation"),),
        )
    elif mutation == "wrong_state_identity":
        request = replace(
            request,
            state_access_grants=(replace(access_grant, state_identity_hash="sha256:wrong-state"),),
        )
    else:
        request = replace(
            request,
            state_access_grants=(replace(access_grant, expires_at_ns=time.time_ns() - 1),),
        )

    try:
        result = transport.execute(request)
        assert isinstance(result, ErrorResult)
        assert expected_error in result.error_detail
        terminal_receipts = tuple(
            receipt for receipt in transport.last_admission_receipts if receipt.terminal
        )
        assert len(terminal_receipts) == 1
        assert terminal_receipts[0].admitted
        if mutation == "wrong_state_identity":
            assert result.error_code == "state_access_denied"
        else:
            assert result.error_code == "invalid_exec_request"
    finally:
        authority.unpin(store=store, pin_id=pin.pin_id)
        _settle(authority, request, StepLifecycleState.FAILED.value)
        store.release_owner(
            publication.ref.state_id,
            owner_session_id=comparator_identity.session_id,
        )


def test_semantic_consumer_settled_attempt_cannot_issue_or_acquire_read(
    tmp_path: Path,
) -> None:
    store, publication, comparator_identity = _semantic_state(tmp_path)
    _transport, authority, request = _consumer_request(
        tmp_path,
        store,
        publication,
        comparator_identity,
        suffix="settled-attempt",
    )
    access_grant = request.state_access_grants[0]
    pin = _pin_request(store, publication, authority, request)
    authority.unpin(store=store, pin_id=pin.pin_id)
    _settle(authority, request, StepLifecycleState.FAILED.value)

    with pytest.raises(AdaptiveRuntimeError, match="state_access_attempt_not_active"):
        authority.issue_read(
            ref=publication.ref,
            authority_basis=STATE_ACCESS_AUTHORITY_CAPABILITY_INPUT,
            consumer_role="executor",
            physical_invocation_id=request.header.invocation_id,
        )
    with pytest.raises(AdaptiveRuntimeError, match="state_access_attempt_not_active"):
        authority.acquire_pin(
            store=store,
            ref=publication.ref,
            access_grant=access_grant,
            consumer_role="executor",
            physical_invocation_id=request.header.invocation_id,
        )

    store.release_owner(
        publication.ref.state_id,
        owner_session_id=comparator_identity.session_id,
    )
    store.teardown()


@pytest.mark.parametrize("termination_confirmed", (True, False))
def test_semantic_consumer_timeout_preserves_lifetime_until_termination_confirmed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    termination_confirmed: bool,
) -> None:
    trace: list[str] = []
    captured: dict[str, object] = {}
    original_settle = RuntimeSessionManager.settle_attempt
    original_acquire = RuntimeStateAccessAuthority.acquire_pin
    original_unpin = RuntimeStateAccessAuthority.unpin
    original_release_owner = LayeredStateStore.release_owner

    def observed_settle(self, *args, **kwargs):
        trace.append("settle")
        return original_settle(self, *args, **kwargs)

    def observed_acquire(self, **kwargs):
        pin = original_acquire(self, **kwargs)
        captured.update(authority=self, store=kwargs["store"], ref=kwargs["ref"], pin=pin)
        return pin

    def observed_unpin(self, **kwargs):
        trace.append("unpin")
        return original_unpin(self, **kwargs)

    def observed_release_owner(self, ref_id, *, owner_session_id):
        trace.append("release_owner")
        return original_release_owner(self, ref_id, owner_session_id=owner_session_id)

    def timeout_execute(transport, request, **_kwargs):
        raise SubprocessTransportTimeout(
            transport=transport,
            request=request,
            thread=SimpleNamespace(),
            process=SimpleNamespace(pid=98765),
            responses=[],
            response_wire_bytes=[],
            carrier="protobuf",
            request_wire_bytes=1,
        )

    def controlled_terminate(self, *, grace_s=1.0):
        del self, grace_s
        trace.append("terminate")
        return termination_confirmed

    monkeypatch.setattr(RuntimeSessionManager, "settle_attempt", observed_settle)
    monkeypatch.setattr(RuntimeStateAccessAuthority, "acquire_pin", observed_acquire)
    monkeypatch.setattr(RuntimeStateAccessAuthority, "unpin", observed_unpin)
    monkeypatch.setattr(LayeredStateStore, "release_owner", observed_release_owner)
    monkeypatch.setattr(SubprocessExecutorTransport, "execute", timeout_execute)
    monkeypatch.setattr(SubprocessTransportTimeout, "terminate", controlled_terminate)

    from statebus.runtime.smoke import run_smoke

    expected_error = (
        SubprocessTransportTimeout
        if termination_confirmed
        else RuntimeError
    )
    expected_match = (
        "subprocess_transport_timeout"
        if termination_confirmed
        else "semantic_state_timeout_worker_termination_unconfirmed"
    )
    with pytest.raises(expected_error, match=expected_match):
        run_smoke(
            workspace_root=tmp_path / "workspaces",
            runtime_root=tmp_path / "runtime",
            socket_path=tmp_path / "control.sock",
        )

    store = captured["store"]
    ref = captured["ref"]
    pin = captured["pin"]
    authority = captured["authority"]
    lifetime = store.lifetimes[ref.state_id]
    if termination_confirmed:
        assert trace[-4:] == ["settle", "terminate", "unpin", "release_owner"]
        assert lifetime.live_pin_count == 0
        assert lifetime.owner_released
    else:
        assert trace[-2:] == ["settle", "terminate"]
        assert pin.pin_id in lifetime.live_pins
        assert not lifetime.owner_released
        original_unpin(authority, store=store, pin_id=pin.pin_id)
        original_release_owner(
            store,
            ref.state_id,
            owner_session_id=lifetime.owner_session_id,
        )
    store.teardown()
