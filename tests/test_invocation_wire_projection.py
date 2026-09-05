from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re

from statebus.contracts import CONTROL_PLANE_SCHEMA_VERSION
from statebus.control import (
    ControlHeader,
    ErrorResult,
    EventType,
    ExecRequest,
    RefHandle,
    deframe_control_message,
    frame_control_message,
)
from statebus.control.schema import message_class
from statebus.control.transport import SubprocessExecutorTransport


_HEADER_FIELD_NUMBERS = {
    "trace_id": 1,
    "task_id": 2,
    "step_id": 3,
    "attempt_id": 4,
    "target_role": 5,
    "timeout_ms": 6,
    "schema_version": 7,
    "event_type": 8,
    "run_id": 9,
    "session_id": 10,
    "invocation_id": 11,
    "execution_binding_hash": 12,
    "capability_grant_hash": 13,
}


def _canonical_request(tmp_path: Path) -> ExecRequest:
    grant_hash = "sha256:grant-05a"
    return ExecRequest(
        header=ControlHeader(
            trace_id="trace-05a",
            task_id="runtime-task-05a",
            step_id="retrieve",
            attempt_id="attempt-run-05a-1",
            target_role="executor",
            timeout_ms=5_000,
            event_type=EventType.REQ_EXEC,
            run_id="run-05a",
            session_id="session-05a",
            invocation_id="invocation-05a",
            execution_binding_hash="sha256:binding-05a",
            capability_grant_hash=grant_hash,
            schema_version=CONTROL_PLANE_SCHEMA_VERSION,
        ),
        state_refs=(RefHandle(ref_id="semantic-05a", ref_kind="semantic_state"),),
        runtime_reuse_contract="semantic_state_required",
        output_contract_version="statebus.evidence_selection.v1",
        workspace_root=str(tmp_path / "workspace"),
        input_manifest_hash="sha256:manifest-05a",
        operation="semantic_select_v1",
        state_root=str(tmp_path / "state"),
        hydrate_manifest_id="manifest-05a",
        semantic_top_k=1,
        evidence_budget_bytes=1_024,
        expected_encoder_signature="encoder-05a",
        capability_grant_hash=grant_hash,
    )


def test_control_header_roundtrip_preserves_runtime_invocation_scope_and_schema_parity(
    tmp_path: Path,
) -> None:
    request = _canonical_request(tmp_path)

    decoded = deframe_control_message(frame_control_message(request))

    assert isinstance(decoded, ExecRequest)
    assert decoded.header == request.header
    assert decoded.capability_grant_hash == request.capability_grant_hash
    assert decoded.header.capability_grant_hash == decoded.capability_grant_hash

    dynamic_fields = {
        field.name: field.number
        for field in message_class("ControlHeader").DESCRIPTOR.fields
    }
    proto_path = (
        Path(__file__).resolve().parents[1]
        / "statebus"
        / "control"
        / "statebus_control.proto"
    )
    header_block = proto_path.read_text(encoding="utf-8").split(
        "message ControlHeader {", 1
    )[1].split("}", 1)[0]
    proto_fields = {
        name: int(number)
        for name, number in re.findall(
            r"^\s*(?:string|uint32|EventType)\s+(\w+)\s*=\s*(\d+);",
            header_block,
            flags=re.MULTILINE,
        )
    }
    assert dynamic_fields == _HEADER_FIELD_NUMBERS
    assert proto_fields == _HEADER_FIELD_NUMBERS
    scope = {
        "task_id": decoded.header.task_id,
        "run_id": decoded.header.run_id,
        "session_id": decoded.header.session_id,
        "step_id": decoded.header.step_id,
        "attempt_id": decoded.header.attempt_id,
        "invocation_id": decoded.header.invocation_id,
        "execution_binding_hash": decoded.header.execution_binding_hash,
        "capability_grant_hash": decoded.header.capability_grant_hash,
        "schema_version": decoded.header.schema_version,
    }
    (tmp_path / "wire_roundtrip.json").write_text(
        json.dumps(
            {
                "request_scope": scope,
                "decoded_scope": scope,
                "header_field_numbers": dynamic_fields,
                "header_equal": decoded.header == request.header,
                "duplicate_grant_hash_equal": (
                    decoded.header.capability_grant_hash
                    == decoded.capability_grant_hash
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_subprocess_worker_rejects_invalid_canonical_invocation_scope(
    tmp_path: Path,
) -> None:
    request = _canonical_request(tmp_path)
    cases = (
        (
            "missing-session",
            replace(request, header=replace(request.header, session_id="")),
            "session_id_missing",
        ),
        (
            "missing-invocation",
            replace(request, header=replace(request.header, invocation_id="")),
            "invocation_id_missing",
        ),
        (
            "missing-binding",
            replace(request, header=replace(request.header, execution_binding_hash="")),
            "execution_binding_hash_missing",
        ),
        (
            "grant-mismatch",
            replace(request, capability_grant_hash="sha256:different-grant"),
            "capability_grant_hash_mismatch",
        ),
        (
            "missing-schema",
            replace(request, header=replace(request.header, schema_version="")),
            "schema_version_missing",
        ),
        (
            "unsupported-schema",
            replace(
                request,
                header=replace(request.header, schema_version="statebus.control.v2"),
            ),
            "schema_version_unsupported",
        ),
    )

    for case_name, invalid_request, expected_error in cases:
        response = SubprocessExecutorTransport(
            socket_path=tmp_path / f"{case_name}.sock",
            timeout_s=10.0,
        ).execute(invalid_request)
        assert isinstance(response, ErrorResult), case_name
        assert response.error_code == "invalid_exec_request", case_name
        assert expected_error in response.error_detail.split(","), case_name
        assert response.header == replace(
            invalid_request.header,
            event_type=EventType.RES_ERR,
        )
