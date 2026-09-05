from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from statebus.contracts import CONTROL_PLANE_SCHEMA_VERSION
from statebus.control import (
    AckReceived,
    ControlHeader,
    ControlResponseOrigin,
    ErrorResult,
    EventType,
    ExecRequest,
    Heartbeat,
    RefHandle,
    RunStart,
    SubprocessExecutorTransport,
    SuccessResult,
    admit_control_response_sequence,
)


def _semantic_request(tmp_path: Path) -> ExecRequest:
    grant_hash = "sha256:grant-05b"
    return ExecRequest(
        header=ControlHeader(
            trace_id="trace-05b",
            task_id="runtime-task-05b",
            run_id="run-05b",
            session_id="session-05b",
            step_id="retrieve",
            attempt_id="attempt-05b-1",
            invocation_id="invocation-05b-1",
            target_role="executor",
            timeout_ms=5_000,
            execution_binding_hash="sha256:binding-05b",
            capability_grant_hash=grant_hash,
            event_type=EventType.REQ_EXEC,
            schema_version=CONTROL_PLANE_SCHEMA_VERSION,
        ),
        state_refs=(RefHandle(ref_id="semantic-05b", ref_kind="semantic_state"),),
        runtime_reuse_contract="semantic_state_required",
        output_contract_version="statebus.evidence_selection.v1",
        workspace_root=str(tmp_path / "workspace"),
        input_manifest_hash="sha256:manifest-05b",
        operation="semantic_select_v1",
        state_root=str(tmp_path / "state"),
        hydrate_manifest_id="manifest-05b",
        semantic_top_k=2,
        evidence_budget_bytes=1_024,
        expected_encoder_signature="encoder-05b",
        capability_grant_hash=grant_hash,
    )


def _success(request: ExecRequest) -> SuccessResult:
    return SuccessResult(
        header=replace(request.header, event_type=EventType.RES_SUCC),
        state_refs=request.state_refs,
        output_contract_version=request.output_contract_version,
        completed_at_ns=4,
        consumed_state_ref_id=request.state_refs[0].ref_id,
        selected_candidate_ids=("candidate-1", "candidate-2"),
        selected_scores=(0.9, 0.8),
        selected_row_indices=(1, 2),
        selected_evidence_bytes=128,
        consumer_pid=200,
        producer_pid=100,
        encoder_signature=request.expected_encoder_signature,
    )


def _valid_sequence(request: ExecRequest) -> tuple[object, ...]:
    return (
        AckReceived(
            header=replace(request.header, event_type=EventType.ACK_RECV),
            acked_at_ns=1,
        ),
        RunStart(
            header=replace(request.header, event_type=EventType.RUN_START),
            started_at_ns=2,
            heartbeat_interval_ms=2_000,
            lease_timeout_ms=30_000,
        ),
        Heartbeat(
            header=replace(request.header, event_type=EventType.HEARTBEAT),
            sent_at_ns=3,
            worker_state="running",
        ),
        _success(request),
    )


def test_control_response_admission_accepts_valid_semantic_lifecycle(tmp_path: Path) -> None:
    request = _semantic_request(tmp_path)
    sequence = _valid_sequence(request)

    admitted, receipts = admit_control_response_sequence(
        request,
        sequence,
        origin=ControlResponseOrigin.NATIVE_TYPED_WORKER,
    )

    assert admitted == sequence
    assert all(receipt.admitted for receipt in receipts)
    assert [receipt.event_type for receipt in receipts] == [
        "ACK_RECV",
        "RUN_START",
        "HEARTBEAT",
        "RES_SUCC",
    ]
    assert receipts[-1].terminal
    assert receipts[-1].terminal_count == 1
    assert receipts[-1].output_contract_decision == "matched"
    assert receipts[-1].canonical_payload()["expected_scope"] == dict(
        receipts[-1].expected_scope
    )


def test_control_response_admission_rejects_scope_event_and_contract_mismatches(
    tmp_path: Path,
) -> None:
    request = _semantic_request(tmp_path)
    success = _success(request)
    scope_cases = {
        "trace_id": "wrong-trace",
        "task_id": "wrong-task",
        "run_id": "wrong-run",
        "session_id": "wrong-session",
        "step_id": "wrong-step",
        "attempt_id": "wrong-attempt",
        "invocation_id": "wrong-invocation",
        "execution_binding_hash": "sha256:wrong-binding",
        "capability_grant_hash": "sha256:wrong-grant",
        "schema_version": "statebus.control.v2",
    }
    cases = [
        (
            f"scope-{field_name}",
            replace(success, header=replace(success.header, **{field_name: value})),
            f"scope_mismatch:{field_name}",
        )
        for field_name, value in scope_cases.items()
    ]
    cases.extend(
        (
            (
                "event-type",
                replace(success, header=replace(success.header, event_type=EventType.RES_ERR)),
                "event_type_mismatch",
            ),
            (
                "illegal-message",
                request,
                "illegal_message_type",
            ),
            (
                "output-contract",
                replace(success, output_contract_version="statebus.wrong.v1"),
                "output_contract_mismatch",
            ),
            (
                "state-ref-count",
                replace(success, state_refs=()),
                "semantic_response_state_ref_count_invalid",
            ),
            (
                "state-ref-kind",
                replace(
                    success,
                    state_refs=(RefHandle(ref_id="semantic-05b", ref_kind="wrong_kind"),),
                ),
                "semantic_state_ref_mismatch",
            ),
            (
                "consumed-ref",
                replace(success, consumed_state_ref_id="wrong-state"),
                "semantic_consumed_state_ref_mismatch",
            ),
            (
                "cardinality",
                replace(success, selected_scores=(0.9,)),
                "semantic_result_cardinality_mismatch",
            ),
            (
                "top-k",
                replace(
                    success,
                    selected_candidate_ids=("a", "b", "c"),
                    selected_scores=(0.9, 0.8, 0.7),
                    selected_row_indices=(1, 2, 3),
                ),
                "semantic_result_top_k_exceeded",
            ),
        )
    )

    rejection_records = []
    for case_name, candidate, expected_reason in cases:
        admitted, receipts = admit_control_response_sequence(
            request,
            (*_valid_sequence(request)[:-1], candidate),
            origin=ControlResponseOrigin.NATIVE_TYPED_WORKER,
        )
        assert admitted == (), case_name
        assert receipts[-1].reason_code == expected_reason, case_name
        assert not receipts[-1].admitted, case_name
        rejection_records.append(
            {
                "case": case_name,
                "expected_reason": expected_reason,
                "receipt": receipts[-1].canonical_payload(),
            }
        )

    wrong_request_ref = replace(
        request,
        state_refs=(RefHandle(ref_id="semantic-05b", ref_kind="wrong_kind"),),
    )
    admitted, receipts = admit_control_response_sequence(
        wrong_request_ref,
        _valid_sequence(wrong_request_ref),
        origin=ControlResponseOrigin.NATIVE_TYPED_WORKER,
    )
    assert admitted == ()
    assert receipts[-1].reason_code == "semantic_request_state_ref_kind_invalid"
    rejection_records.append(
        {
            "case": "request-state-ref-kind",
            "expected_reason": "semantic_request_state_ref_kind_invalid",
            "receipt": receipts[-1].canonical_payload(),
        }
    )
    (tmp_path / "response_mismatch_rejection.txt").write_text(
        json.dumps(rejection_records, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_control_response_admission_rejects_illegal_order_and_duplicate_terminal(
    tmp_path: Path,
) -> None:
    request = _semantic_request(tmp_path)
    success = _success(request)
    admitted, receipts = admit_control_response_sequence(
        request,
        (success,),
        origin=ControlResponseOrigin.NATIVE_TYPED_WORKER,
    )
    assert admitted == ()
    assert receipts[0].reason_code == "illegal_event_order"

    partial_scope_request = replace(
        request,
        header=replace(request.header, invocation_id=""),
    )
    admitted, receipts = admit_control_response_sequence(
        partial_scope_request,
        _valid_sequence(partial_scope_request),
        origin=ControlResponseOrigin.LEGACY_COMPATIBILITY,
    )
    assert admitted == ()
    assert receipts[0].reason_code == "expected_scope_missing:invocation_id"

    request_error = ErrorResult(
        header=replace(partial_scope_request.header, event_type=EventType.RES_ERR),
        error_code="invalid_exec_request",
        error_detail="invocation_id_missing",
        failed_at_ns=1,
    )
    admitted, receipts = admit_control_response_sequence(
        partial_scope_request,
        (request_error,),
        origin=ControlResponseOrigin.LEGACY_COMPATIBILITY,
    )
    assert admitted == (request_error,)
    assert receipts[0].admitted

    duplicate = ErrorResult(
        header=replace(request.header, event_type=EventType.RES_ERR),
        error_code="late-error",
        error_detail="duplicate terminal",
        failed_at_ns=5,
    )
    admitted, receipts = admit_control_response_sequence(
        request,
        (*_valid_sequence(request), duplicate),
        origin=ControlResponseOrigin.NATIVE_TYPED_WORKER,
    )
    assert admitted == ()
    assert receipts[-1].reason_code == "duplicate_terminal"
    assert receipts[-1].terminal_count == 2
    (tmp_path / "duplicate_terminal_rejection.txt").write_text(
        json.dumps(
            {
                "admitted_message_count": len(admitted),
                "candidate_terminal_count": 2,
                "receipts": [receipt.canonical_payload() for receipt in receipts],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_real_subprocess_success_is_natively_admitted(tmp_path: Path) -> None:
    request = replace(
        _semantic_request(tmp_path),
        operation="",
        state_refs=(),
        artifact_refs=(RefHandle(ref_id="artifact-05b", ref_kind="artifact"),),
        runtime_reuse_contract="no_semantic_state",
    )
    transport = SubprocessExecutorTransport(
        socket_path=tmp_path / "native-admission.sock",
        timeout_s=10.0,
    )

    response = transport.execute(request)

    assert isinstance(response, SuccessResult)
    assert transport.last_admission_receipts
    assert all(receipt.admitted for receipt in transport.last_admission_receipts)
    assert all(
        receipt.origin == ControlResponseOrigin.NATIVE_TYPED_WORKER
        for receipt in transport.last_admission_receipts
    )
    terminal_receipts = tuple(
        receipt for receipt in transport.last_admission_receipts if receipt.terminal
    )
    assert len(terminal_receipts) == 1
    assert terminal_receipts[0].output_contract_decision == "matched"
    assert transport.last_exchange_audit is not None
    (tmp_path / "valid_response_admission.json").write_text(
        json.dumps(
            {
                "mechanism": "UDS -> protobuf -> real subprocess_worker -> admission",
                "transport": transport.last_exchange_audit.canonical_payload(),
                "request_scope": dict(transport.last_admission_receipts[0].expected_scope),
                "admitted_message_count": len(transport.last_admission_receipts),
                "receipts": [
                    receipt.canonical_payload()
                    for receipt in transport.last_admission_receipts
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
