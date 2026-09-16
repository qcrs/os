"""Executor subprocess worker entry point for StateBus control plane.

The worker is launched by SubprocessExecutorTransport and communicates
with the main process over a Unix Domain Socket using typed Protobuf frames.

Protocol (worker-side):
  1. Connect to the UDS path supplied via --socket-path.
  2. Receive one ExecRequest frame from the main process.
  3. Validate required fields; send ErrorResult on failure.
  4. Read any memfd state refs (``memfd_fd:{fd}:{length}:{state_id}``).
  5. On success: send AckReceived → RunStart → Heartbeat → SuccessResult.
  6. Close connection and exit.

memfd refs
----------
When the ExecRequest contains state_refs with ``memfd_fd:`` prefixed
ref_ids the worker reads the embedding bytes directly from the inherited
file descriptor using ``os.read(fd, length)``.  The bytes never touch the
filesystem; the FD was created with ``memfd_create`` in the main process
and forwarded via ``pass_fds`` in ``subprocess.Popen``.

Usage:
  python -m statebus.control.subprocess_worker --socket-path /tmp/statebus-exec.sock
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import sys
import time
from dataclasses import replace

import numpy as np

from statebus.control.messages import (
    AckReceived,
    ErrorResult,
    EventType,
    ExecRequest,
    Heartbeat,
    RefHandle,
    RunStart,
    SuccessResult,
)
from statebus.control.transport import (
    decode_memfd_ref,
    recv_control_message,
    recv_text_message,
    send_control_message,
    send_text_message,
)
from statebus.contracts import (
    CONTROL_PLANE_SCHEMA_VERSION,
    StateAccessContractError,
    StateAccessGrant,
)
from statebus.state import (
    DenseSemanticSelection,
    LogitStateValidationError,
    SemanticStateValidationError,
    evaluate_logit_state,
    load_hydrate_manifest,
    logit_ref_from_sidecar,
    resolve_logit_state,
    select_dense_semantic_state,
    semantic_ref_from_sidecar,
)
from statebus.utils import sha256_digest


def _read_memfd_refs(state_refs: tuple[RefHandle, ...]) -> dict[str, bytes]:
    """Read bytes from any inherited memfd FDs in state_refs.

    Returns {state_id: payload_bytes} for each successfully read memfd ref.
    Non-memfd refs are silently skipped.
    """
    result: dict[str, bytes] = {}
    for ref in state_refs:
        parsed = decode_memfd_ref(ref)
        if parsed is None:
            continue
        fd, length, state_id = parsed
        if fd < 0 or length < 0:
            raise ValueError("memfd_descriptor_invalid")
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            data = os.read(fd, length)
        except OSError as exc:
            print(
                f"subprocess_worker: failed to read memfd fd={fd} state_id={state_id}: {exc}",
                file=sys.stderr,
            )
            raise RuntimeError("memfd_read_failed") from exc
        if len(data) != length:
            raise RuntimeError("memfd_payload_truncated")
        result[state_id] = data
    return result


def _select_memfd_semantic_state(
    *,
    state_root: Path,
    ref_handle: RefHandle,
    payload: bytes,
    manifest_id: str,
    top_k: int,
    evidence_budget_bytes: int,
    expected_encoder_signature: str,
) -> DenseSemanticSelection:
    """Validate and select a semantic matrix carried by an inherited memfd.

    ``resolve_dense_semantic_state`` intentionally resolves filesystem-backed
    SHM/mmap materializations.  A memfd has no sidecar path to open, so the
    worker validates the same sidecar contract against the bytes read from the
    inherited descriptor before applying the canonical selection rule.
    """
    parsed = decode_memfd_ref(ref_handle)
    if parsed is None:
        raise SemanticStateValidationError("memfd_semantic_ref_missing")
    _fd, declared_length, logical_state_id = parsed
    ref = semantic_ref_from_sidecar(state_root, logical_state_id)
    metadata = ref.metadata
    if ref_handle.ref_kind != "semantic_state":
        raise SemanticStateValidationError("semantic_ref_kind_invalid")
    if declared_length != ref.length or len(payload) != ref.length:
        raise SemanticStateValidationError("dense_state_size_shape_mismatch")
    if sha256_digest(payload) != ref.blob_hash:
        raise SemanticStateValidationError("dense_state_blob_hash_mismatch")
    if expected_encoder_signature and metadata.get("encoder_signature") != expected_encoder_signature:
        raise SemanticStateValidationError("dense_state_encoder_signature_mismatch")
    if int(metadata.get("lease_expires_at_ns", 0)) <= time.time_ns():
        raise SemanticStateValidationError("dense_state_expired")
    shape = tuple(int(value) for value in metadata.get("shape", ()))
    if len(shape) != 2 or shape[0] < 2 or shape[1] <= 0 or shape[0] * shape[1] * 4 != len(payload):
        raise SemanticStateValidationError("dense_state_size_shape_mismatch")
    if metadata.get("dtype") != "float32" or metadata.get("byte_order") != "little":
        raise SemanticStateValidationError("dense_state_dtype_or_byte_order_mismatch")
    matrix = np.frombuffer(payload, dtype="<f4").reshape(shape)
    if not np.isfinite(matrix).all():
        raise SemanticStateValidationError("dense_state_non_finite")
    if bool(metadata.get("normalized", False)):
        norms = np.linalg.norm(matrix, axis=1)
        if np.any(np.abs(norms - 1.0) > 1e-4):
            raise SemanticStateValidationError("dense_state_not_normalized")
    manifest = load_hydrate_manifest(state_root, manifest_id)
    if manifest.manifest_hash != str(metadata.get("hydrate_manifest_hash", "")):
        raise SemanticStateValidationError("hydrate_manifest_hash_mismatch")
    if len(manifest.entries) != shape[0] - 1:
        raise SemanticStateValidationError("hydrate_manifest_matrix_row_mismatch")
    entries_by_row = {entry.row_idx: entry for entry in manifest.entries}
    if set(entries_by_row) != set(range(1, shape[0])):
        raise SemanticStateValidationError("hydrate_manifest_row_index_mismatch")
    scores = matrix[1:] @ matrix[0]
    ranked = sorted(
        ((float(scores[row_idx - 1]), row_idx, entries_by_row[row_idx]) for row_idx in range(1, shape[0])),
        key=lambda item: (-item[0], item[2].candidate_id),
    )
    selected: list[tuple[float, int, object]] = []
    used_bytes = 0
    for score, row_idx, entry in ranked:
        if len(selected) >= top_k:
            break
        protected = entry.bucket in {"hard_fact", "structured_evidence"}
        if evidence_budget_bytes > 0 and not protected and used_bytes + entry.byte_hint > evidence_budget_bytes:
            continue
        selected.append((score, row_idx, entry))
        used_bytes += max(entry.byte_hint, 0)
    if not selected:
        raise SemanticStateValidationError("semantic_selection_empty")
    return DenseSemanticSelection(
        state_id=logical_state_id,
        selected_candidate_ids=tuple(item[2].candidate_id for item in selected),
        selected_scores=tuple(round(item[0], 6) for item in selected),
        selected_row_indices=tuple(item[1] for item in selected),
        selected_evidence_bytes=used_bytes,
        consumer_pid=os.getpid(),
        producer_pid=int(metadata.get("producer_pid", 0)),
        encoder_signature=str(metadata.get("encoder_signature", "")),
    )


def run(socket_path: str, *, carrier: str = "protobuf") -> int:
    """Connect to supervisor, process one ExecRequest, return exit code."""
    if carrier not in {"protobuf", "utf8_text"}:
        raise ValueError(f"unsupported subprocess carrier: {carrier}")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(socket_path)
    except OSError as exc:
        print(f"subprocess_worker: connect failed: {exc}", file=sys.stderr)
        return 1

    if carrier == "utf8_text":
        try:
            text_request = recv_text_message(sock)
        except Exception as exc:
            print(f"subprocess_worker: recv failed: {exc}", file=sys.stderr)
            sock.close()
            return 1
        required_sections = (
            "StateBus matched pure-text executor handoff.",
            "Task:",
            "Output contract:",
            "Current evidence:",
            "Verified prior context:",
        )
        forbidden_typed_fields = (
            '"message_type"',
            '"state_refs"',
            '"memory_refs"',
            '"artifact_refs"',
        )
        missing = [section for section in required_sections if section not in text_request]
        forbidden = [field for field in forbidden_typed_fields if field in text_request]
        if missing or forbidden:
            detail = ",".join(
                [*(f"missing:{item}" for item in missing), *(f"forbidden:{item}" for item in forbidden)]
            )
            send_text_message(sock, f"RESULT ERROR invalid_text_handoff {detail}")
            sock.close()
            return 1
        for response in (
            "ACK RECEIVED",
            "RUN START",
            "HEARTBEAT running",
            "RESULT SUCCESS",
        ):
            send_text_message(sock, response)
        sock.close()
        return 0

    try:
        message = recv_control_message(sock)
    except Exception as exc:
        print(f"subprocess_worker: recv failed: {exc}", file=sys.stderr)
        sock.close()
        return 1

    if not isinstance(message, ExecRequest):
        print(
            f"subprocess_worker: expected ExecRequest, got {type(message).__name__}",
            file=sys.stderr,
        )
        sock.close()
        return 1

    header = message.header
    send_message = send_control_message
    runtime_reuse_contract = message.runtime_reuse_contract or ""
    semantic_optional = "no_semantic_state" in runtime_reuse_contract
    semantic_selection = message.operation == "semantic_select_v1"
    logit_gate = message.operation == "logit_gate_v1"

    errors: list[str] = []
    semantic_access_grant: StateAccessGrant | None = None
    if not header.schema_version.strip():
        errors.append("schema_version_missing")
    elif header.schema_version != CONTROL_PLANE_SCHEMA_VERSION:
        errors.append("schema_version_unsupported")

    bound_invocation = (
        semantic_selection
        or bool(message.capability_grant_hash.strip())
        or bool(header.capability_grant_hash.strip())
    )
    if bound_invocation:
        for field_name in (
            "trace_id",
            "task_id",
            "run_id",
            "session_id",
            "step_id",
            "attempt_id",
            "invocation_id",
            "execution_binding_hash",
            "capability_grant_hash",
        ):
            if not str(getattr(header, field_name)).strip():
                errors.append(f"{field_name}_missing")
        if not message.capability_grant_hash.strip():
            errors.append("request_capability_grant_hash_missing")
    if message.capability_grant_hash != header.capability_grant_hash:
        errors.append("capability_grant_hash_mismatch")

    if not message.workspace_root.strip():
        errors.append("workspace_root_missing")
    if not message.input_manifest_hash.strip():
        errors.append("input_manifest_hash_missing")
    if not message.output_contract_version.strip():
        errors.append("output_contract_version_missing")
    if not semantic_optional and not message.state_refs:
        errors.append("state_refs_missing")
    if not semantic_selection and not logit_gate and not message.artifact_refs:
        errors.append("artifact_refs_missing")
    if semantic_selection:
        if not message.state_root.strip():
            errors.append("state_root_missing")
        if not message.hydrate_manifest_id.strip():
            errors.append("hydrate_manifest_id_missing")
        if message.semantic_top_k <= 0:
            errors.append("semantic_top_k_missing")
        if len(message.state_refs) != 1:
            errors.append("semantic_state_ref_count_invalid")
        if len(message.state_access_grants) != 1:
            errors.append("state_access_grant_count_invalid")
        if not message.consumer_provider_id.strip():
            errors.append("consumer_provider_id_missing")
        if len(message.state_refs) == 1 and len(message.state_access_grants) == 1:
            semantic_access_grant = message.state_access_grants[0]
            try:
                grant_ref_id = message.state_refs[0].ref_id
                parsed_grant_ref = decode_memfd_ref(message.state_refs[0])
                if parsed_grant_ref is not None:
                    grant_ref_id = parsed_grant_ref[2]
                semantic_access_grant.validate_read_scope(
                    runtime_task_id=header.task_id,
                    run_id=header.run_id,
                    session_id=header.session_id,
                    step_id=header.step_id,
                    attempt_id=header.attempt_id,
                    execution_binding_hash=header.execution_binding_hash,
                    capability_grant_hash=header.capability_grant_hash,
                    ref_id=grant_ref_id,
                    ref_kind=message.state_refs[0].ref_kind,
                    consumer_provider_id=message.consumer_provider_id,
                    consumer_role=header.target_role,
                    physical_invocation_id=header.invocation_id,
                )
            except StateAccessContractError as exc:
                errors.append(str(exc))
    if logit_gate:
        if not message.state_root.strip():
            errors.append("state_root_missing")
        if len(message.state_refs) != 1:
            errors.append("logit_state_ref_count_invalid")

    if errors:
        send_message(
            sock,
            ErrorResult(
                header=replace(header, event_type=EventType.RES_ERR),
                error_code="invalid_exec_request",
                error_detail=",".join(errors),
                failed_at_ns=0,
            ),
        )
        sock.close()
        return 1

    # Read any memfd state refs passed by the main process.
    read_started_at_ns = time.time_ns()
    try:
        memfd_payloads = _read_memfd_refs(message.state_refs)
    except (OSError, RuntimeError, ValueError) as exc:
        send_message(
            sock,
            ErrorResult(
                header=replace(header, event_type=EventType.RES_ERR),
                error_code="memfd_read_failed",
                error_detail=str(exc) or type(exc).__name__,
                failed_at_ns=time.time_ns(),
            ),
        )
        sock.close()
        return 1
    read_completed_at_ns = time.time_ns()
    if memfd_payloads:
        total_bytes = sum(len(v) for v in memfd_payloads.values())
        print(
            f"subprocess_worker: read {len(memfd_payloads)} memfd ref(s), "
            f"{total_bytes} bytes total: {list(memfd_payloads)}",
            file=sys.stderr,
        )

    now = time.time_ns()
    send_message(
        sock,
        AckReceived(
            header=replace(header, event_type=EventType.ACK_RECV),
            acked_at_ns=now,
        ),
    )
    send_message(
        sock,
        RunStart(
            header=replace(header, event_type=EventType.RUN_START),
            started_at_ns=now + 1,
            heartbeat_interval_ms=2000,
            lease_timeout_ms=30_000,
        ),
    )
    send_message(
        sock,
        Heartbeat(
            header=replace(header, event_type=EventType.HEARTBEAT),
            sent_at_ns=now + 2,
            worker_state="running",
        ),
    )
    if semantic_selection:
        try:
            ref_handle = message.state_refs[0]
            parsed_memfd = decode_memfd_ref(ref_handle)
            if parsed_memfd is not None:
                _fd, _length, logical_state_id = parsed_memfd
                state_ref = semantic_ref_from_sidecar(
                    Path(message.state_root), logical_state_id
                )
                semantic_access_grant.validate_state_identity(state_ref.state_identity_hash)
                selection = _select_memfd_semantic_state(
                    state_root=Path(message.state_root),
                    ref_handle=ref_handle,
                    payload=memfd_payloads.get(logical_state_id, b""),
                    manifest_id=message.hydrate_manifest_id,
                    top_k=message.semantic_top_k,
                    evidence_budget_bytes=message.evidence_budget_bytes,
                    expected_encoder_signature=message.expected_encoder_signature,
                )
            else:
                state_ref = semantic_ref_from_sidecar(
                    Path(message.state_root), ref_handle.ref_id
                )
                semantic_access_grant.validate_state_identity(state_ref.state_identity_hash)
                selection = select_dense_semantic_state(
                    state_root=Path(message.state_root),
                    ref=state_ref,
                    manifest_id=message.hydrate_manifest_id,
                    top_k=message.semantic_top_k,
                    evidence_budget_bytes=message.evidence_budget_bytes,
                    expected_encoder_signature=message.expected_encoder_signature,
                    unregister_shared_memory_tracker=True,
                )
        except StateAccessContractError as exc:
            send_message(
                sock,
                ErrorResult(
                    header=replace(header, event_type=EventType.RES_ERR),
                    error_code="state_access_denied",
                    error_detail=str(exc),
                    failed_at_ns=time.time_ns(),
                ),
            )
            sock.close()
            return 1
        except (SemanticStateValidationError, ValueError, OSError) as exc:
            send_message(
                sock,
                ErrorResult(
                    header=replace(header, event_type=EventType.RES_ERR),
                    error_code="semantic_state_consume_failed",
                    error_detail=str(exc) or type(exc).__name__,
                    failed_at_ns=time.time_ns(),
                ),
            )
            sock.close()
            return 1
        send_message(
            sock,
            SuccessResult(
                header=replace(header, event_type=EventType.RES_SUCC),
                state_refs=message.state_refs,
                artifact_refs=message.artifact_refs,
                output_contract_version=message.output_contract_version,
                completed_at_ns=time.time_ns(),
                consumed_state_ref_id=selection.state_id,
                selected_candidate_ids=selection.selected_candidate_ids,
                selected_scores=selection.selected_scores,
                selected_row_indices=selection.selected_row_indices,
                selected_evidence_bytes=selection.selected_evidence_bytes,
                consumer_pid=selection.consumer_pid,
                producer_pid=selection.producer_pid,
                encoder_signature=selection.encoder_signature,
            ),
        )
    elif logit_gate:
        try:
            state_ref = logit_ref_from_sidecar(
                Path(message.state_root),
                message.state_refs[0].ref_id,
            )
            resolved = resolve_logit_state(
                state_root=Path(message.state_root),
                ref=state_ref,
                unregister_shared_memory_tracker=True,
            )
            receipt = evaluate_logit_state(resolved)
        except (LogitStateValidationError, ValueError, OSError) as exc:
            send_message(
                sock,
                ErrorResult(
                    header=replace(header, event_type=EventType.RES_ERR),
                    error_code="logit_state_consume_failed",
                    error_detail=str(exc) or type(exc).__name__,
                    failed_at_ns=time.time_ns(),
                ),
            )
            sock.close()
            return 1
        send_message(
            sock,
            SuccessResult(
                header=replace(header, event_type=EventType.RES_SUCC),
                state_refs=message.state_refs,
                output_contract_version=message.output_contract_version,
                completed_at_ns=time.time_ns(),
                consumed_state_ref_id=receipt.state_id,
                consumer_pid=receipt.consumer_pid,
                producer_pid=receipt.producer_pid,
                gate_action=receipt.action.value,
                gate_reason=receipt.reason,
                selected_alias=receipt.selected_alias,
                selected_candidate_id=receipt.selected_candidate_id,
                top1_alias=receipt.top1_alias,
                selected_probability=receipt.selected_probability,
                top_margin=receipt.top_margin,
                normalized_entropy=receipt.normalized_entropy,
                other_mass=receipt.other_mass,
                decision_id=receipt.decision_id,
                margin_threshold=receipt.margin_threshold,
                gate_candidate_count=receipt.candidate_count,
            ),
        )
    else:
        send_message(
            sock,
            SuccessResult(
                header=replace(header, event_type=EventType.RES_SUCC),
                state_refs=message.state_refs,
                artifact_refs=message.artifact_refs,
                output_contract_version=message.output_contract_version,
                completed_at_ns=time.time_ns(),
            ),
        )
    sock.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="StateBus Executor subprocess worker")
    parser.add_argument("--socket-path", required=True, help="UDS path to connect to")
    parser.add_argument("--carrier", choices=("protobuf", "utf8_text"), default="protobuf")
    args = parser.parse_args()
    sys.exit(run(args.socket_path, carrier=args.carrier))


if __name__ == "__main__":
    main()
