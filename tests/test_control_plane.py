from __future__ import annotations

import os
import platform
import sys
import tempfile
import struct
from pathlib import Path

import pytest

from statebus.control import (
    ControlHeader,
    EventType,
    ExecRequest,
    RefHandle,
    ReusePolicy,
    deframe_control_message,
    frame_control_message,
    decode_control_message,
)
from statebus.control.messages import MAX_CONTROL_FRAME_PAYLOAD_BYTES
from statebus.control.transport import (
    ControlPlaneLoopbackServer,
    SubprocessExecutorTransport,
    decode_memfd_ref,
    encode_memfd_ref,
)
from statebus.control.messages import SuccessResult
from statebus.contracts import StorageKind
from statebus.contracts import StateAccessGrant
from statebus.memory import StructuredEmbedding
from statebus.refs import FragmentLocator, HydrateManifest, HydrateManifestEntry
from statebus.state import LayeredStateStore, LayeredStoragePolicy
from statebus.state import publish_dense_semantic_state


def test_control_plane_frame_round_trip_preserves_typed_refs() -> None:
    message = ExecRequest(
        header=ControlHeader(
            trace_id="trace-1",
            task_id="task-1",
            step_id="step-1",
            attempt_id="attempt-1",
            target_role="executor",
            timeout_ms=5000,
            event_type=EventType.REQ_EXEC,
        ),
        reuse_policy=ReusePolicy(
            allow_assist=True,
            allow_validated_replay=True,
            allow_exact_replay=False,
        ),
        state_refs=(RefHandle(ref_id="state-1", ref_kind="semantic_state"),),
        artifact_refs=(RefHandle(ref_id="artifact-1", ref_kind="execution_artifact"),),
        memory_refs=(RefHandle(ref_id="memory-1", ref_kind="memory"),),
        runtime_reuse_contract="benchmark_strict:exact_replay_allowed",
        output_contract_version="output-v1",
        workspace_root="/statebus/workspaces/task-1",
        input_manifest_hash="sha256:manifest",
        operation="semantic_select_v1",
        state_root="/statebus/work/statepool/task-1",
        hydrate_manifest_id="manifest-1",
        semantic_top_k=3,
        evidence_budget_bytes=4096,
        expected_encoder_signature="encoder-signature",
        capability_grant_hash="grant-hash",
    )

    parsed = deframe_control_message(frame_control_message(message))
    assert isinstance(parsed, ExecRequest)
    assert parsed.header.event_type == EventType.REQ_EXEC
    assert parsed.state_refs[0].ref_kind == "semantic_state"
    assert parsed.artifact_refs[0].ref_kind == "execution_artifact"
    assert parsed.memory_refs[0].ref_kind == "memory"
    assert parsed.reuse_policy.allow_validated_replay is True
    assert parsed.runtime_reuse_contract == "benchmark_strict:exact_replay_allowed"
    assert parsed.workspace_root == "/statebus/workspaces/task-1"
    assert parsed.operation == "semantic_select_v1"
    assert parsed.state_root == "/statebus/work/statepool/task-1"
    assert parsed.hydrate_manifest_id == "manifest-1"
    assert parsed.semantic_top_k == 3
    assert parsed.evidence_budget_bytes == 4096
    assert parsed.expected_encoder_signature == "encoder-signature"
    assert parsed.capability_grant_hash == "grant-hash"


def test_control_plane_framing_rejects_truncated_oversized_and_invalid_digest() -> None:
    with pytest.raises(ValueError, match="frame_header_truncated"):
        deframe_control_message(b"\x00\x01")
    with pytest.raises(ValueError, match="frame_payload_truncated"):
        deframe_control_message(struct.pack(">I", 3) + b"x")
    with pytest.raises(ValueError, match="frame_oversized"):
        deframe_control_message(struct.pack(">I", MAX_CONTROL_FRAME_PAYLOAD_BYTES + 1))
    with pytest.raises(ValueError, match="control_body_missing"):
        decode_control_message(b"\x08\x01")


def test_control_plane_schema_and_event_are_strict() -> None:
    message = ExecRequest(
        header=ControlHeader(
            trace_id="trace-schema",
            task_id="task-schema",
            step_id="step-1",
            attempt_id="attempt-1",
            target_role="executor",
            timeout_ms=1,
            event_type=EventType.REQ_EXEC,
        ),
        runtime_reuse_contract="no_semantic_state",
        output_contract_version="output-v1",
        workspace_root="/tmp/ws",
        input_manifest_hash="sha256:input",
        artifact_refs=(RefHandle(ref_id="a", ref_kind="artifact"),),
    )
    payload = bytearray(frame_control_message(message)[4:])
    # The header is nested; replacing a valid typed message with random bytes
    # must fail closed rather than silently defaulting schema/version.
    with pytest.raises(ValueError):
        decode_control_message(bytes(payload[:2]))


def test_loopback_transport_shortens_overlong_unix_socket_path(tmp_path: Path) -> None:
    requested_socket = tmp_path / ("nested-" + "x" * 80) / "control.sock"
    assert len(os.fsencode(requested_socket)) > 107
    message = ExecRequest(
        header=ControlHeader(
            trace_id="trace-overlong-socket",
            task_id="task-overlong-socket",
            step_id="step-1",
            attempt_id="attempt-1",
            target_role="executor",
            timeout_ms=5000,
            event_type=EventType.REQ_EXEC,
        ),
        runtime_reuse_contract="no_semantic_state",
        output_contract_version="output-v1",
        workspace_root="/statebus/workspaces/task-overlong-socket",
        input_manifest_hash="sha256:manifest",
        artifact_refs=(RefHandle(ref_id="artifact-1", ref_kind="execution_artifact"),),
    )

    echoed = ControlPlaneLoopbackServer(requested_socket).round_trip(message)

    assert echoed == message
    assert not requested_socket.exists()


def test_encode_decode_memfd_ref_round_trip() -> None:
    """encode_memfd_ref / decode_memfd_ref must be lossless."""
    ref = encode_memfd_ref(fd=7, length=64, state_id="emb-001", ref_kind="embedding")
    assert ref.ref_id == "memfd_fd:7:64:emb-001"
    assert ref.ref_kind == "embedding"

    parsed = decode_memfd_ref(ref)
    assert parsed == (7, 64, "emb-001")


def test_decode_memfd_ref_returns_none_for_plain_ref() -> None:
    ref = RefHandle(ref_id="plain-state-id", ref_kind="semantic_state")
    assert decode_memfd_ref(ref) is None


def _make_header(task_id: str = "task-memfd") -> ControlHeader:
    return ControlHeader(
        trace_id="trace-memfd",
        task_id=task_id,
        step_id="step-1",
        attempt_id="attempt-1",
        target_role="executor",
        timeout_ms=15000,
        event_type=EventType.REQ_EXEC,
    )


@pytest.mark.skipif(
    platform.system() != "Linux",
    reason="memfd_create is Linux-only",
)
def test_subprocess_transport_memfd_e2e(tmp_path: Path) -> None:
    """SubprocessExecutorTransport must forward memfd FDs to the worker subprocess.

    Flow:
      1. Main process writes test bytes to a memfd.
      2. SubprocessExecutorTransport rewrites state_refs to memfd_fd: handles
         and passes the FD via pass_fds.
      3. subprocess_worker reads the bytes from the inherited FD.
      4. Worker returns SuccessResult — proves the subprocess received and
         accepted the ExecRequest with memfd refs.
    """
    store = LayeredStateStore(
        root=tmp_path / "state",
        policy=LayeredStoragePolicy.for_state_pool_mode("memfd"),
    )
    payload = b"query_embedding_f32_bytes_" + bytes(range(32))
    handle = store.publish(
        ref_id="emb-subprocess-test",
        object_kind="EMBEDDING_STATE",
        payload=payload,
    )
    if handle.storage_kind != StorageKind.MEMFD or handle.memfd_fd is None:
        store.teardown()
        pytest.skip("memfd unavailable; shared-memory fallback has separate coverage")

    # Reuse the descriptor owned by the formal layered StateBus store.
    fd = handle.memfd_fd
    length = handle.size_bytes
    assert length == len(payload)

    socket_path = tmp_path / "memfd-test.sock"
    transport = SubprocessExecutorTransport(
        socket_path=socket_path,
        timeout_s=20.0,
    )
    request = ExecRequest(
        header=_make_header(),
        state_refs=(RefHandle(ref_id="emb-subprocess-test", ref_kind="embedding"),),
        artifact_refs=(RefHandle(ref_id="art-1", ref_kind="execution_artifact"),),
        runtime_reuse_contract="no_semantic_state",
        output_contract_version="output-v1",
        workspace_root=str(tmp_path / "ws"),
        input_manifest_hash="sha256:test",
    )
    try:
        result = transport.execute(request, memfd_refs={"emb-subprocess-test": (fd, length)})
    finally:
        store.teardown()

    assert isinstance(result, SuccessResult), (
        f"expected SuccessResult, got {type(result).__name__}: "
        f"{getattr(result, 'error_detail', '')}"
    )
    assert result.output_contract_version == "output-v1"
    # Worker echoes state_refs back — they should carry the memfd_fd: encoded ref.
    assert len(result.state_refs) == 1
    assert result.state_refs[0].ref_id.startswith("memfd_fd:")
    decoded = decode_memfd_ref(result.state_refs[0])
    assert decoded is not None
    _, echoed_length, echoed_state_id = decoded
    assert echoed_state_id == "emb-subprocess-test"
    assert echoed_length == length


@pytest.mark.skipif(platform.system() != "Linux", reason="memfd_create is Linux-only")
def test_subprocess_semantic_memfd_actual_read_and_selection(tmp_path: Path) -> None:
    """A memfd semantic ref must be mapped/read by the independent worker."""
    store = LayeredStateStore(
        root=tmp_path / "state",
        policy=LayeredStoragePolicy.for_state_pool_mode("memfd"),
    )
    query = StructuredEmbedding("query", (1.0, 0.0), 2, "query-hash")
    candidate = StructuredEmbedding("candidate", (1.0, 0.0), 2, "candidate-hash")
    manifest = HydrateManifest(
        manifest_id="semantic-memfd-manifest",
        source_doc_hashes=("doc-hash",),
        entries=(HydrateManifestEntry(
            row_idx=1,
            locator=FragmentLocator(source_doc_hash="doc-hash", fragment_id="frag-1"),
            stable_key="frag-1",
            byte_hint=17,
            candidate_id="candidate-1",
        ),),
        canonicalizer_version="test-canon",
        extractor_version="test-extractor",
    )
    publication = publish_dense_semantic_state(
        store=store,
        state_id="semantic-memfd-state",
        query_embedding=query,
        candidate_embeddings=(candidate,),
        hydrate_manifest=manifest,
        owner_session_id="session-memfd",
        producer_step_id="retrieve",
        producer_attempt_id="attempt-retrieve",
        encoder_revision="test-revision",
    )
    if publication.handle.memfd_fd is None:
        store.teardown()
        pytest.skip("memfd unavailable")
    invocation_id = "invocation-memfd"
    grant = StateAccessGrant(
        access_grant_id="state-access-memfd",
        runtime_task_id="task-memfd-semantic",
        run_id="run-memfd-semantic",
        session_id="session-memfd",
        step_id="execute",
        attempt_id="attempt-execute",
        execution_binding_hash="binding-memfd",
        capability_grant_hash="grant-memfd",
        ref_id=publication.ref.state_id,
        ref_kind="semantic_state",
        state_identity_hash=publication.ref.state_identity_hash,
        access_mode="READ",
        authority_basis="RUNTIME_INTERMEDIATE",
        consumer_provider_id="executor-provider",
        consumer_role="executor",
        physical_invocation_id=invocation_id,
        expires_at_ns=publication.contract.lease_expires_at_ns,
    )
    request = ExecRequest(
        header=ControlHeader(
            trace_id="trace-memfd-semantic",
            task_id="task-memfd-semantic",
            run_id="run-memfd-semantic",
            session_id="session-memfd",
            step_id="execute",
            attempt_id="attempt-execute",
            invocation_id=invocation_id,
            execution_binding_hash="binding-memfd",
            capability_grant_hash="grant-memfd",
            target_role="executor",
            timeout_ms=20_000,
            event_type=EventType.REQ_EXEC,
        ),
        state_refs=(RefHandle(publication.ref.state_id, "semantic_state"),),
        state_access_grants=(grant,),
        runtime_reuse_contract="semantic_state_required",
        output_contract_version="statebus.evidence_selection.v1",
        workspace_root=str(tmp_path / "workspace"),
        input_manifest_hash=publication.contract.hydrate_manifest_hash,
        operation="semantic_select_v1",
        state_root=str(store.root),
        hydrate_manifest_id=manifest.manifest_id,
        semantic_top_k=1,
        evidence_budget_bytes=128,
        expected_encoder_signature=publication.contract.encoder_signature,
        capability_grant_hash="grant-memfd",
        consumer_provider_id="executor-provider",
    )
    try:
        result = SubprocessExecutorTransport(tmp_path / "semantic-memfd.sock", timeout_s=20).execute(
            request,
            memfd_refs={publication.ref.state_id: (publication.handle.memfd_fd, publication.handle.size_bytes)},
        )
    finally:
        store.teardown()
    assert isinstance(result, SuccessResult)
    assert result.consumed_state_ref_id == publication.ref.state_id
    assert result.selected_candidate_ids == ("candidate-1",)
    assert result.selected_row_indices == (1,)
    assert result.selected_evidence_bytes == 17
    assert result.consumer_pid > 0 and result.consumer_pid != result.producer_pid
