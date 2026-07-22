"""Executor subprocess worker entry point for StateBus v2 control plane.

The worker is launched by SubprocessExecutorTransport and communicates
with the main process over a Unix Domain Socket using typed Protobuf frames.

Protocol (worker-side):
  1. Connect to the UDS path supplied via --socket-path.
  2. Receive HELLO and return HELLO_ACK after version/capability checks.
  3. Receive one ExecRequest only after successful negotiation.
  4. Validate required fields; send ErrorResult on failure.
  5. Read any memfd state refs (``memfd_fd:{fd}:{length}:{state_id}``).
  6. On success: send AckReceived → RunStart → Heartbeat → SuccessResult.
  7. Close connection and exit.

memfd refs
----------
When the ExecRequest contains state_refs with ``memfd_fd:`` prefixed
ref_ids the worker reads the embedding bytes directly from the inherited
file descriptor using ``os.read(fd, length)``.  The bytes never touch the
filesystem; the FD was created with ``memfd_create`` in the main process
and forwarded via ``pass_fds`` in ``subprocess.Popen``.

Usage:
  python -m v2.control.subprocess_worker --socket-path /tmp/statebus-exec.sock
"""
from __future__ import annotations

import argparse
import binascii
import os
from pathlib import Path
import resource
import socket
import sys
import time
from dataclasses import replace

from v2.contracts import CONTROL_PLANE_SCHEMA_VERSION
from v2.control.messages import (
    AckReceived,
    CONTROL_PROTOCOL_VERSION,
    DEFAULT_WORKER_CAPABILITY_IDS,
    ErrorResult,
    EventType,
    ExecRequest,
    Hello,
    HelloAck,
    Heartbeat,
    RefHandle,
    RunStart,
    SuccessResult,
    worker_capability_registry_digest,
)
from v2.control.transport import (
    decode_memfd_ref,
    recv_control_message,
    recv_text_message,
    send_control_message,
    send_text_message,
)
from v2.control.worker_operations import (
    TYPED_NUMERIC_OUTPUT_CONTRACT_VERSION,
    TypedNumericOperationError,
    compute_typed_numeric_summary,
)
from v2.state import (
    SemanticStateValidationError,
    select_dense_semantic_state,
    semantic_ref_from_sidecar,
)


def _apply_worker_limits() -> None:
    """Apply defense-in-depth limits inside the worker process."""

    os.umask(0o077)
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(38, 1, 0, 0, 0)  # Linux PR_SET_NO_NEW_PRIVS
    except (AttributeError, OSError, TypeError):
        pass
    try:
        cpu_limit = max(2, int(os.environ.get("STATEBUS_WORKER_CPU_LIMIT_S", "60")))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit))
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    except (AttributeError, OSError, ValueError):
        pass


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
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            data = os.read(fd, length)
        except OSError as exc:
            print(
                f"subprocess_worker: failed to read memfd fd={fd} state_id={state_id}: {exc}",
                file=sys.stderr,
            )
            continue
        result[state_id] = data
    return result


def _negotiate_hello(message: Hello) -> HelloAck:
    errors: list[str] = []
    protocol_version = (
        CONTROL_PROTOCOL_VERSION
        if CONTROL_PROTOCOL_VERSION in message.protocol_versions
        else ""
    )
    schema_version = (
        CONTROL_PLANE_SCHEMA_VERSION
        if CONTROL_PLANE_SCHEMA_VERSION in message.schema_versions
        else ""
    )
    registry_digest = worker_capability_registry_digest(
        DEFAULT_WORKER_CAPABILITY_IDS
    )
    if message.header.event_type != EventType.HELLO:
        errors.append("hello_event_type_invalid")
    if not protocol_version:
        errors.append("protocol_version_mismatch")
    if not schema_version:
        errors.append("schema_version_mismatch")
    if message.controller_registry_digest != registry_digest:
        errors.append("capability_registry_digest_mismatch")
    missing = sorted(
        set(message.required_capability_ids)
        - set(DEFAULT_WORKER_CAPABILITY_IDS)
    )
    if missing:
        errors.append(f"missing_required_capability:{'|'.join(missing)}")
    return HelloAck(
        header=replace(message.header, event_type=EventType.HELLO_ACK),
        accepted=not errors,
        accepted_protocol_version=protocol_version,
        accepted_schema_version=schema_version,
        worker_registry_digest=registry_digest,
        supported_capability_ids=DEFAULT_WORKER_CAPABILITY_IDS,
        error_detail=",".join(errors),
        worker_pid=os.getpid(),
    )


def _send_pre_execution_error(
    sock: socket.socket,
    *,
    header,
    error_code: str,
    error_detail: str,
) -> None:
    send_control_message(
        sock,
        ErrorResult(
            header=replace(header, event_type=EventType.RES_ERR),
            error_code=error_code,
            error_detail=error_detail,
            failed_at_ns=time.time_ns(),
        ),
    )


def run(socket_path: str, *, carrier: str = "protobuf") -> int:
    """Connect to supervisor, process one ExecRequest, return exit code."""
    _apply_worker_limits()
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
        first_message = recv_control_message(sock)
    except Exception as exc:
        print(f"subprocess_worker: recv failed: {exc}", file=sys.stderr)
        sock.close()
        return 1

    if not isinstance(first_message, Hello):
        if isinstance(first_message, ExecRequest):
            _send_pre_execution_error(
                sock,
                header=first_message.header,
                error_code="hello_required_before_exec",
                error_detail="typed Protobuf ExecRequest received before HELLO",
            )
        print(
            f"subprocess_worker: expected Hello, got {type(first_message).__name__}",
            file=sys.stderr,
        )
        sock.close()
        return 1

    hello_ack = _negotiate_hello(first_message)
    send_control_message(sock, hello_ack)
    if not hello_ack.accepted:
        sock.close()
        return 1

    try:
        message = recv_control_message(sock)
    except Exception as exc:
        print(f"subprocess_worker: exec recv failed: {exc}", file=sys.stderr)
        sock.close()
        return 1
    if not isinstance(message, ExecRequest):
        _send_pre_execution_error(
            sock,
            header=first_message.header,
            error_code="exec_request_required_after_hello",
            error_detail=type(message).__name__,
        )
        sock.close()
        return 1

    header = message.header
    send_message = send_control_message
    runtime_reuse_contract = message.runtime_reuse_contract or ""
    semantic_optional = "no_semantic_state" in runtime_reuse_contract
    semantic_selection = message.operation == "semantic_select_v1"
    logit_gate = message.operation == "logit_gate_v1"
    typed_numeric_summary = message.operation == "typed_numeric_summary_v1"
    negotiated_capability = message.operation.strip() or "echo_refs_v1"
    grant_required = semantic_selection or logit_gate or typed_numeric_summary

    grant_authenticator = None
    if grant_required:
        secret_hex = os.environ.get("STATEBUS_CAPABILITY_GRANT_SECRET_HEX", "")
        if not secret_hex:
            # A semantic selector is a cross-process capability consumer.  It
            # must never accept a random non-empty hash as authorization.
            send_message(
                sock,
                ErrorResult(
                    header=replace(header, event_type=EventType.RES_ERR),
                    error_code="capability_grant_auth_required",
                    error_detail="capability_grant_secret_missing",
                    failed_at_ns=time.time_ns(),
                ),
            )
            sock.close()
            return 1
        try:
            from v2.runtime.capability_grants import CapabilityGrantAuthenticator

            grant_authenticator = CapabilityGrantAuthenticator(
                secret=binascii.unhexlify(secret_hex),
                nonce_registry_dir=Path(os.environ["STATEBUS_CAPABILITY_GRANT_NONCE_DIR"])
                if os.environ.get("STATEBUS_CAPABILITY_GRANT_NONCE_DIR")
                else None,
            )
        except (ValueError, binascii.Error):
            send_message(
                sock,
                ErrorResult(
                    header=replace(header, event_type=EventType.RES_ERR),
                    error_code="capability_grant_auth_required",
                    error_detail="capability_grant_secret_invalid",
                    failed_at_ns=time.time_ns(),
                ),
            )
            sock.close()
            return 1

    errors: list[str] = []
    if header.event_type != EventType.REQ_EXEC:
        errors.append("exec_event_type_invalid")
    if header.schema_version != hello_ack.accepted_schema_version:
        errors.append("exec_schema_version_not_negotiated")
    if negotiated_capability not in first_message.required_capability_ids:
        errors.append("exec_capability_not_negotiated")
    if negotiated_capability not in hello_ack.supported_capability_ids:
        errors.append("exec_capability_unsupported")
    if not message.workspace_root.strip():
        errors.append("workspace_root_missing")
    if not message.input_manifest_hash.strip():
        errors.append("input_manifest_hash_missing")
    if not message.output_contract_version.strip():
        errors.append("output_contract_version_missing")
    if not semantic_optional and not message.state_refs:
        errors.append("state_refs_missing")
    if not semantic_selection and not logit_gate and not typed_numeric_summary and not message.artifact_refs:
        errors.append("artifact_refs_missing")
    if semantic_selection:
        if not message.state_root.strip():
            errors.append("state_root_missing")
        if not message.hydrate_manifest_id.strip():
            errors.append("hydrate_manifest_id_missing")
        if message.semantic_top_k <= 0:
            errors.append("semantic_top_k_missing")
        if not message.capability_grant_hash.strip():
            errors.append("capability_grant_hash_missing")
        if len(message.state_refs) != 1:
            errors.append("semantic_state_ref_count_invalid")

        if not message.capability_grant_token.strip():
            errors.append("capability_grant_token_missing")
    if logit_gate:
        if message.output_contract_version != "statebus.gate_decision.v1":
            errors.append("logit_gate_output_contract_invalid")
        if not message.state_root.strip():
            errors.append("state_root_missing")
        if len(message.state_refs) != 1:
            errors.append("logit_state_ref_count_invalid")
        elif message.state_refs[0].ref_kind != "logit_state":
            errors.append("logit_state_ref_kind_invalid")
        if message.logit_state_ref is None:
            errors.append("logit_control_ref_missing")
        if message.logit_state_grant is None:
            errors.append("logit_control_grant_missing")
        if message.artifact_refs or message.memory_refs:
            errors.append("logit_gate_scope_violation")
        if not message.capability_grant_hash.strip():
            errors.append("capability_grant_hash_missing")
        if not message.capability_grant_token.strip():
            errors.append("capability_grant_token_missing")
    if typed_numeric_summary:
        if message.output_contract_version != TYPED_NUMERIC_OUTPUT_CONTRACT_VERSION:
            errors.append("typed_numeric_output_contract_invalid")
        if len(message.state_refs) != 1:
            errors.append("typed_numeric_input_ref_count_invalid")
        elif decode_memfd_ref(message.state_refs[0]) is None:
            errors.append("typed_numeric_input_fd_required")
        if message.artifact_refs or message.memory_refs:
            errors.append("typed_numeric_scope_violation")
        if not message.capability_grant_hash.strip():
            errors.append("capability_grant_hash_missing")
        if not message.capability_grant_token.strip():
            errors.append("capability_grant_token_missing")

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

    if grant_required and grant_authenticator is not None:
        bound_ref_ids = tuple(
            ref.ref_id.split(":", 3)[-1]
            if ref.ref_id.startswith("memfd_fd:")
            else ref.ref_id
            for ref in (*message.state_refs, *message.artifact_refs, *message.memory_refs)
        )
        try:
            grant_authenticator.verify(
                message.capability_grant_token,
                expected_grant_hash=message.capability_grant_hash,
                expected_task_id=header.task_id,
                expected_session_id=message.capability_grant_session_id,
                expected_step_id=header.step_id,
                expected_attempt_id=header.attempt_id,
                expected_ref_ids=bound_ref_ids,
                expected_output_contract=message.output_contract_version,
                consume=True,
            )
        except Exception as exc:
            error_code = getattr(exc, "code", "capability_grant_verification_failed")
            send_message(
                sock,
                ErrorResult(
                    header=replace(header, event_type=EventType.RES_ERR),
                    error_code=str(error_code),
                    error_detail=str(error_code),
                    failed_at_ns=time.time_ns(),
                ),
            )
            sock.close()
            return 1

    # Read any memfd state refs passed by the main process.
    memfd_payloads = _read_memfd_refs(message.state_refs)
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
    if logit_gate:
        try:
            import json

            from v2.runtime.confidence_gate import (
                FrozenGatePolicy,
                decide_from_resolved_logit_state,
                gate_decision_to_control,
                logit_grant_from_control,
                persist_gate_action_decision,
                validate_logit_control_ref,
            )
            from v2.state.logit_state import (
                LogitStateValidationError,
                logit_ref_from_sidecar,
                resolve_logit_state,
            )

            state_ref = logit_ref_from_sidecar(
                Path(message.state_root),
                message.state_refs[0].ref_id,
            )
            validate_logit_control_ref(state_ref, message.logit_state_ref)
            grant = logit_grant_from_control(message.logit_state_grant)
            policy_payload = (
                json.loads(message.logit_gate_policy_json)
                if message.logit_gate_policy_json
                else None
            )
            if policy_payload is not None and not isinstance(policy_payload, dict):
                raise ValueError("logit_gate_policy_object_required")
            policy = FrozenGatePolicy.from_payload(policy_payload) if policy_payload else None
            resolved = resolve_logit_state(
                state_root=Path(message.state_root),
                ref=state_ref,
                grant=grant,
                unregister_shared_memory_tracker=True,
            )
            decision = decide_from_resolved_logit_state(resolved, policy=policy)
            decision, reused = persist_gate_action_decision(
                Path(message.state_root),
                decision,
            )
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
                consumed_state_ref_id=state_ref.state_id,
                consumer_pid=decision.consumer_pid,
                producer_pid=decision.producer_pid,
                logit_gate_result=gate_decision_to_control(decision),
                logit_grant_hash=grant.grant_hash,
                logit_action_reused=reused,
            ),
        )
    elif semantic_selection:
        try:
            state_ref = semantic_ref_from_sidecar(
                Path(message.state_root),
                message.state_refs[0].ref_id,
            )
            selection = select_dense_semantic_state(
                state_root=Path(message.state_root),
                ref=state_ref,
                manifest_id=message.hydrate_manifest_id,
                top_k=message.semantic_top_k,
                evidence_budget_bytes=message.evidence_budget_bytes,
                expected_encoder_signature=message.expected_encoder_signature,
                unregister_shared_memory_tracker=True,
            )
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
    elif typed_numeric_summary:
        input_ref_id = next(iter(memfd_payloads), "")
        try:
            compute_started_ns = time.perf_counter_ns()
            numeric_summary = compute_typed_numeric_summary(
                memfd_payloads[input_ref_id],
                input_ref_id=input_ref_id,
                worker_pid=os.getpid(),
            )
            numeric_summary = replace(
                numeric_summary,
                worker_compute_ns=time.perf_counter_ns() - compute_started_ns,
            )
        except (KeyError, TypedNumericOperationError) as exc:
            error_detail = str(exc) or "typed_numeric_input_unreadable"
            send_message(
                sock,
                ErrorResult(
                    header=replace(header, event_type=EventType.RES_ERR),
                    error_code="typed_numeric_compute_failed",
                    error_detail=error_detail,
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
                consumed_state_ref_id=input_ref_id,
                consumer_pid=os.getpid(),
                numeric_summary=numeric_summary,
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
    parser = argparse.ArgumentParser(description="StateBus v2 Executor subprocess worker")
    parser.add_argument("--socket-path", required=True, help="UDS path to connect to")
    parser.add_argument("--carrier", choices=("protobuf", "utf8_text"), default="protobuf")
    args = parser.parse_args()
    sys.exit(run(args.socket_path, carrier=args.carrier))


if __name__ == "__main__":
    main()
