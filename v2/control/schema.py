from __future__ import annotations

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.descriptor import FieldDescriptor


PACKAGE = "statebus.v2.control"
FILE_NAME = "statebus_v2_control.proto"


def _field(
    *,
    name: str,
    number: int,
    field_type: int,
    label: int = FieldDescriptor.LABEL_OPTIONAL,
    type_name: str = "",
    oneof_index: int | None = None,
) -> descriptor_pb2.FieldDescriptorProto:
    field = descriptor_pb2.FieldDescriptorProto(
        name=name,
        number=number,
        type=field_type,
        label=label,
    )
    if type_name:
        field.type_name = type_name
    if oneof_index is not None:
        field.oneof_index = oneof_index
    return field


def _message(
    *,
    name: str,
    fields: list[descriptor_pb2.FieldDescriptorProto],
    oneof_name: str | None = None,
) -> descriptor_pb2.DescriptorProto:
    message = descriptor_pb2.DescriptorProto(name=name)
    if oneof_name:
        message.oneof_decl.add(name=oneof_name)
    message.field.extend(fields)
    return message


def build_control_file_descriptor() -> descriptor_pb2.FileDescriptorProto:
    file_proto = descriptor_pb2.FileDescriptorProto(
        name=FILE_NAME,
        package=PACKAGE,
        syntax="proto3",
    )

    event_enum = file_proto.enum_type.add(name="EventType")
    for number, name in enumerate(
        [
            "EVENT_TYPE_UNSPECIFIED",
            "REQ_EXEC",
            "ACK_RECV",
            "RUN_START",
            "HEARTBEAT",
            "RES_SUCC",
            "RES_ERR",
            "CMD_CANCEL",
            "TRAP_FATAL",
            "CMD_GC",
            "HELLO",
            "HELLO_ACK",
        ]
    ):
        event_enum.value.add(name=name, number=number)

    file_proto.message_type.extend(
        [
            _message(
                name="ControlHeader",
                fields=[
                    _field(name="trace_id", number=1, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="task_id", number=2, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="step_id", number=3, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="attempt_id", number=4, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="target_role", number=5, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="timeout_ms", number=6, field_type=FieldDescriptor.TYPE_UINT32),
                    _field(name="schema_version", number=7, field_type=FieldDescriptor.TYPE_STRING),
                    _field(
                        name="event_type",
                        number=8,
                        field_type=FieldDescriptor.TYPE_ENUM,
                        type_name=f".{PACKAGE}.EventType",
                    ),
                ],
            ),
            _message(
                name="RefHandle",
                fields=[
                    _field(name="ref_id", number=1, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="ref_kind", number=2, field_type=FieldDescriptor.TYPE_STRING),
                ],
            ),
            _message(
                name="ReusePolicy",
                fields=[
                    _field(name="allow_assist", number=1, field_type=FieldDescriptor.TYPE_BOOL),
                    _field(
                        name="allow_validated_replay",
                        number=2,
                        field_type=FieldDescriptor.TYPE_BOOL,
                    ),
                    _field(name="allow_exact_replay", number=3, field_type=FieldDescriptor.TYPE_BOOL),
                ],
            ),
            _message(
                name="Hello",
                fields=[
                    _field(
                        name="header",
                        number=1,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.ControlHeader",
                    ),
                    _field(
                        name="protocol_versions",
                        number=2,
                        field_type=FieldDescriptor.TYPE_STRING,
                        label=FieldDescriptor.LABEL_REPEATED,
                    ),
                    _field(
                        name="schema_versions",
                        number=3,
                        field_type=FieldDescriptor.TYPE_STRING,
                        label=FieldDescriptor.LABEL_REPEATED,
                    ),
                    _field(
                        name="controller_registry_digest",
                        number=4,
                        field_type=FieldDescriptor.TYPE_STRING,
                    ),
                    _field(
                        name="required_capability_ids",
                        number=5,
                        field_type=FieldDescriptor.TYPE_STRING,
                        label=FieldDescriptor.LABEL_REPEATED,
                    ),
                    _field(
                        name="controller_pid",
                        number=6,
                        field_type=FieldDescriptor.TYPE_INT64,
                    ),
                ],
            ),
            _message(
                name="HelloAck",
                fields=[
                    _field(
                        name="header",
                        number=1,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.ControlHeader",
                    ),
                    _field(name="accepted", number=2, field_type=FieldDescriptor.TYPE_BOOL),
                    _field(
                        name="accepted_protocol_version",
                        number=3,
                        field_type=FieldDescriptor.TYPE_STRING,
                    ),
                    _field(
                        name="accepted_schema_version",
                        number=4,
                        field_type=FieldDescriptor.TYPE_STRING,
                    ),
                    _field(
                        name="worker_registry_digest",
                        number=5,
                        field_type=FieldDescriptor.TYPE_STRING,
                    ),
                    _field(
                        name="supported_capability_ids",
                        number=6,
                        field_type=FieldDescriptor.TYPE_STRING,
                        label=FieldDescriptor.LABEL_REPEATED,
                    ),
                    _field(
                        name="error_detail",
                        number=7,
                        field_type=FieldDescriptor.TYPE_STRING,
                    ),
                    _field(
                        name="worker_pid",
                        number=8,
                        field_type=FieldDescriptor.TYPE_INT64,
                    ),
                ],
            ),
            _message(
                name="ExecRequest",
                fields=[
                    _field(
                        name="header",
                        number=1,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.ControlHeader",
                    ),
                    _field(
                        name="reuse_policy",
                        number=2,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.ReusePolicy",
                    ),
                    _field(
                        name="state_refs",
                        number=3,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        label=FieldDescriptor.LABEL_REPEATED,
                        type_name=f".{PACKAGE}.RefHandle",
                    ),
                    _field(
                        name="artifact_refs",
                        number=4,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        label=FieldDescriptor.LABEL_REPEATED,
                        type_name=f".{PACKAGE}.RefHandle",
                    ),
                    _field(
                        name="memory_refs",
                        number=5,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        label=FieldDescriptor.LABEL_REPEATED,
                        type_name=f".{PACKAGE}.RefHandle",
                    ),
                    _field(
                        name="runtime_reuse_contract",
                        number=6,
                        field_type=FieldDescriptor.TYPE_STRING,
                    ),
                    _field(
                        name="output_contract_version",
                        number=7,
                        field_type=FieldDescriptor.TYPE_STRING,
                    ),
                    _field(
                        name="workspace_root",
                        number=8,
                        field_type=FieldDescriptor.TYPE_STRING,
                    ),
                    _field(
                        name="input_manifest_hash",
                        number=9,
                        field_type=FieldDescriptor.TYPE_STRING,
                    ),
                    _field(name="operation", number=10, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="state_root", number=11, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="hydrate_manifest_id", number=12, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="semantic_top_k", number=13, field_type=FieldDescriptor.TYPE_UINT32),
                    _field(name="evidence_budget_bytes", number=14, field_type=FieldDescriptor.TYPE_UINT64),
                    _field(name="expected_encoder_signature", number=15, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="capability_grant_hash", number=16, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="capability_grant_token", number=17, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="capability_grant_session_id", number=18, field_type=FieldDescriptor.TYPE_STRING),
                ],
            ),
            _message(
                name="AckReceived",
                fields=[
                    _field(
                        name="header",
                        number=1,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.ControlHeader",
                    ),
                    _field(name="acked_at_ns", number=2, field_type=FieldDescriptor.TYPE_INT64),
                ],
            ),
            _message(
                name="RunStart",
                fields=[
                    _field(
                        name="header",
                        number=1,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.ControlHeader",
                    ),
                    _field(name="started_at_ns", number=2, field_type=FieldDescriptor.TYPE_INT64),
                    _field(
                        name="heartbeat_interval_ms",
                        number=3,
                        field_type=FieldDescriptor.TYPE_UINT32,
                    ),
                    _field(name="lease_timeout_ms", number=4, field_type=FieldDescriptor.TYPE_UINT32),
                ],
            ),
            _message(
                name="Heartbeat",
                fields=[
                    _field(
                        name="header",
                        number=1,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.ControlHeader",
                    ),
                    _field(name="sent_at_ns", number=2, field_type=FieldDescriptor.TYPE_INT64),
                    _field(name="worker_state", number=3, field_type=FieldDescriptor.TYPE_STRING),
                ],
            ),
            _message(
                name="NumericSummaryResult",
                fields=[
                    _field(name="input_ref_id", number=1, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="input_payload_hash", number=2, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="row_count", number=3, field_type=FieldDescriptor.TYPE_UINT64),
                    _field(name="total", number=4, field_type=FieldDescriptor.TYPE_DOUBLE),
                    _field(name="mean", number=5, field_type=FieldDescriptor.TYPE_DOUBLE),
                    _field(name="minimum", number=6, field_type=FieldDescriptor.TYPE_DOUBLE),
                    _field(name="maximum", number=7, field_type=FieldDescriptor.TYPE_DOUBLE),
                    _field(name="schema_digest", number=8, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="output_artifact_hash", number=9, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="validator_receipt_hash", number=10, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="worker_pid", number=11, field_type=FieldDescriptor.TYPE_INT64),
                    _field(name="worker_compute_ns", number=12, field_type=FieldDescriptor.TYPE_UINT64),
                ],
            ),
            _message(
                name="SuccessResult",
                fields=[
                    _field(
                        name="header",
                        number=1,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.ControlHeader",
                    ),
                    _field(
                        name="state_refs",
                        number=2,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        label=FieldDescriptor.LABEL_REPEATED,
                        type_name=f".{PACKAGE}.RefHandle",
                    ),
                    _field(
                        name="artifact_refs",
                        number=3,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        label=FieldDescriptor.LABEL_REPEATED,
                        type_name=f".{PACKAGE}.RefHandle",
                    ),
                    _field(
                        name="output_contract_version",
                        number=4,
                        field_type=FieldDescriptor.TYPE_STRING,
                    ),
                    _field(name="completed_at_ns", number=5, field_type=FieldDescriptor.TYPE_INT64),
                    _field(name="consumed_state_ref_id", number=6, field_type=FieldDescriptor.TYPE_STRING),
                    _field(
                        name="selected_candidate_ids",
                        number=7,
                        field_type=FieldDescriptor.TYPE_STRING,
                        label=FieldDescriptor.LABEL_REPEATED,
                    ),
                    _field(
                        name="selected_scores",
                        number=8,
                        field_type=FieldDescriptor.TYPE_DOUBLE,
                        label=FieldDescriptor.LABEL_REPEATED,
                    ),
                    _field(
                        name="selected_row_indices",
                        number=9,
                        field_type=FieldDescriptor.TYPE_UINT32,
                        label=FieldDescriptor.LABEL_REPEATED,
                    ),
                    _field(name="selected_evidence_bytes", number=10, field_type=FieldDescriptor.TYPE_UINT64),
                    _field(name="consumer_pid", number=11, field_type=FieldDescriptor.TYPE_INT64),
                    _field(name="producer_pid", number=12, field_type=FieldDescriptor.TYPE_INT64),
                    _field(name="encoder_signature", number=13, field_type=FieldDescriptor.TYPE_STRING),
                    _field(
                        name="numeric_summary",
                        number=14,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.NumericSummaryResult",
                    ),
                ],
            ),
            _message(
                name="ErrorResult",
                fields=[
                    _field(
                        name="header",
                        number=1,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.ControlHeader",
                    ),
                    _field(name="error_code", number=2, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="error_detail", number=3, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="failed_at_ns", number=4, field_type=FieldDescriptor.TYPE_INT64),
                ],
            ),
            _message(
                name="CancelCommand",
                fields=[
                    _field(
                        name="header",
                        number=1,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.ControlHeader",
                    ),
                    _field(name="reason", number=2, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="issued_at_ns", number=3, field_type=FieldDescriptor.TYPE_INT64),
                ],
            ),
            _message(
                name="TrapFatal",
                fields=[
                    _field(
                        name="header",
                        number=1,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.ControlHeader",
                    ),
                    _field(name="trap_reason", number=2, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="error_detail", number=3, field_type=FieldDescriptor.TYPE_STRING),
                    _field(name="trapped_at_ns", number=4, field_type=FieldDescriptor.TYPE_INT64),
                ],
            ),
            _message(
                name="GarbageCollectCommand",
                fields=[
                    _field(
                        name="header",
                        number=1,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.ControlHeader",
                    ),
                    _field(
                        name="ref_ids",
                        number=2,
                        field_type=FieldDescriptor.TYPE_STRING,
                        label=FieldDescriptor.LABEL_REPEATED,
                    ),
                    _field(name="issued_at_ns", number=3, field_type=FieldDescriptor.TYPE_INT64),
                ],
            ),
            _message(
                name="ControlEnvelope",
                oneof_name="body",
                fields=[
                    _field(
                        name="req_exec",
                        number=1,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.ExecRequest",
                        oneof_index=0,
                    ),
                    _field(
                        name="ack_recv",
                        number=2,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.AckReceived",
                        oneof_index=0,
                    ),
                    _field(
                        name="run_start",
                        number=3,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.RunStart",
                        oneof_index=0,
                    ),
                    _field(
                        name="heartbeat",
                        number=4,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.Heartbeat",
                        oneof_index=0,
                    ),
                    _field(
                        name="res_succ",
                        number=5,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.SuccessResult",
                        oneof_index=0,
                    ),
                    _field(
                        name="res_err",
                        number=6,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.ErrorResult",
                        oneof_index=0,
                    ),
                    _field(
                        name="cmd_cancel",
                        number=7,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.CancelCommand",
                        oneof_index=0,
                    ),
                    _field(
                        name="trap_fatal",
                        number=8,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.TrapFatal",
                        oneof_index=0,
                    ),
                    _field(
                        name="cmd_gc",
                        number=9,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.GarbageCollectCommand",
                        oneof_index=0,
                    ),
                    _field(
                        name="hello",
                        number=10,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.Hello",
                        oneof_index=0,
                    ),
                    _field(
                        name="hello_ack",
                        number=11,
                        field_type=FieldDescriptor.TYPE_MESSAGE,
                        type_name=f".{PACKAGE}.HelloAck",
                        oneof_index=0,
                    ),
                ],
            ),
        ]
    )
    return file_proto


_POOL = descriptor_pool.DescriptorPool()
_POOL.AddSerializedFile(build_control_file_descriptor().SerializeToString())


def message_class(name: str) -> type:
    descriptor = _POOL.FindMessageTypeByName(f"{PACKAGE}.{name}")
    return message_factory.GetMessageClass(descriptor)
