from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

from protocol import statebus_pb2


@dataclass
class StateRef:
    state_id: str
    kind: str
    length: int
    blob_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    storage: str = ""
    handle: str = ""
    checksum: str | None = None
    channel: str = ""
    compatibility: dict[str, Any] = field(default_factory=dict)
    fetch_uri: str = ""
    local_only: bool = False
    exact_replay_ready: bool = False
    created_at_ns: int | None = None

    def __post_init__(self) -> None:
        if not self.blob_hash and self.checksum:
            self.blob_hash = self.checksum
        if self.blob_hash and not self.checksum:
            self.checksum = self.blob_hash
        if not self.channel:
            self.channel = str(self.metadata.get("channel_name", ""))

    @property
    def canonical_hash(self) -> str:
        return self.blob_hash or self.checksum or ""

    @property
    def checksum_or_hash(self) -> str:
        return self.canonical_hash

    @property
    def payload_key(self) -> str:
        return self.canonical_hash or self.state_id

    @property
    def casf_dict(self) -> dict[str, Any]:
        return {
            "state_id": self.state_id,
            "blob_hash": self.canonical_hash,
            "kind": self.kind,
            "length": self.length,
            "metadata": dict(self.metadata),
            "channel": self.channel,
            "compatibility": dict(self.compatibility),
        }

    @property
    def legacy_dict(self) -> dict[str, Any]:
        return {
            "state_id": self.state_id,
            "kind": self.kind,
            "storage": self.storage,
            "handle": self.handle,
            "length": self.length,
            "checksum": self.checksum,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_casf(
        cls,
        *,
        state_id: str,
        blob_hash: str,
        kind: str,
        length: int,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> "StateRef":
        return cls(
            state_id=state_id,
            kind=kind,
            length=length,
            blob_hash=blob_hash,
            checksum=blob_hash,
            metadata=dict(metadata or {}),
            **kwargs,
        )

    @property
    def is_cas(self) -> bool:
        return bool(self.canonical_hash) and self.storage == "CAS_BLOB"


@dataclass
class Hello:
    agent_id: str
    mode: str
    protocol_version: str = "statebus.v0"


@dataclass
class CapabilityItem:
    name: str
    kind: str
    input_schema: str
    output_schema: str
    accepted_state_kinds: list[str] = field(default_factory=list)
    produced_state_kinds: list[str] = field(default_factory=list)


@dataclass
class Capability:
    agent_id: str
    items: list[CapabilityItem]


@dataclass
class Ack:
    related_id: str
    detail: str = "ok"


@dataclass
class Error:
    code: str
    detail: str
    related_id: str | None = None


@dataclass
class Heartbeat:
    agent_id: str
    sent_at_ns: int = field(default_factory=time.time_ns)


@dataclass
class PlanStep:
    step_id: str
    owner_agent: str
    action: str
    input_state_refs: list[str]
    params: dict[str, Any]
    depends_on: list[str]
    semantic_role: str = ""


@dataclass
class DeltaPlanStep:
    step_id: str
    base_step_id: str
    owner_agent: str = ""
    action: str = ""
    delta_params: dict[str, Any] = field(default_factory=dict)
    delta_depends_on: list[str] = field(default_factory=list)
    delta_input_state_refs: list[str] = field(default_factory=list)
    input_patch_mode: str = "replace"
    delta_version: int = 1


@dataclass
class Plan:
    task_id: str
    goal: str
    steps: list[PlanStep]


@dataclass
class PlanDelta:
    task_id: str
    base_task_id: str
    goal: str
    steps: list[DeltaPlanStep]
    full_plan_fallback: Plan | None = None
    frame_preference: str = "delta"


@dataclass
class StepResult:
    step_id: str
    success: bool
    output_state_refs: list[StateRef] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    memory_commit: MemoryCommit | None = None
    memory_commits: list[MemoryCommit] = field(default_factory=list)
    error: str | None = None
    skipped: bool = False
    reused_from_memory_id: str | None = None


@dataclass
class MemoryQuery:
    task_theme: str
    query_text: str
    top_k: int
    tags: list[str] = field(default_factory=list)
    tags_any: list[str] = field(default_factory=list)
    tags_all: list[str] = field(default_factory=list)
    min_confidence: float = 0.0
    source_agent_id: str | None = None
    created_after_ns: int | None = None
    encoder_id: str | None = None
    limit_active_only: bool = True
    required_metadata: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    tier: str = "working_memories"
    route_target: str = ""


@dataclass
class MemoryHit:
    memory_id: str
    confidence: float
    embedding_id: int | None = None
    faiss_score: float = 0.0
    combined_score: float = 0.0
    reuse_source: str = ""
    reused_as_plan_patch: bool = False
    skipped_step_ids: list[str] = field(default_factory=list)
    reusable_steps: list[str] = field(default_factory=list)
    evidence_state_ids: list[str] = field(default_factory=list)
    evidence_state_refs: list[StateRef] = field(default_factory=list)
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    task_theme: str = ""
    created_at_ns: int | None = None
    source_task_id: str | None = None
    replay_class: str = ""
    route: str = ""
    route_source: str = ""
    route_provenance: list[str] = field(default_factory=list)
    route_confidence: float = 0.0
    retrieved_doc_ids: list[str] = field(default_factory=list)
    fresh_evidence_sha256: str = ""
    reuse_signature: str = ""
    step_output_state_ids: list[str] = field(default_factory=list)
    step_output_state_refs: list[StateRef] = field(default_factory=list)
    tool_name: str = ""
    source_session_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryCommit:
    memory_id: str
    source_agent_id: str
    source_task_id: str
    task_theme: str
    summary: str
    tags: list[str]
    evidence_state_ids: list[str]
    reusable_steps: list[str] = field(default_factory=list)
    confidence: float = 1.0
    embedding_text: str | None = None
    embedding_state_id: str | None = None
    encoder_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence_state_refs: list[StateRef] = field(default_factory=list)
    created_at_ns: int | None = None
    memory_purpose: str = ""
    memory_layer: str = ""
    replay_class: str = ""
    route: str = ""
    route_source: str = ""
    route_provenance: list[str] = field(default_factory=list)
    route_confidence: float = 0.0
    retrieved_doc_ids: list[str] = field(default_factory=list)
    fresh_evidence_sha256: str = ""
    reuse_signature: str = ""
    step_output_state_ids: list[str] = field(default_factory=list)
    step_output_state_refs: list[StateRef] = field(default_factory=list)
    tool_name: str = ""
    source_session_id: str = ""
    tier: str = ""
    commit_ref: str = ""


@dataclass
class FetchRequest:
    blob_hash: str
    requester_id: str
    state_id: str = ""
    accepted_kinds: list[str] = field(default_factory=list)
    prefer_local_short_circuit: bool = True


@dataclass
class FetchResponse:
    blob_hash: str
    found: bool
    payload_ref: StateRef | None = None
    bytes_sent: int = 0
    cache_hit: bool = False
    responder_id: str = ""


@dataclass
class ChannelPatch:
    channel_name: str
    ops: dict[str, Any] = field(default_factory=dict)
    patch_id: str = ""
    schema_version: str = "statebus.channel_patch.v2"


@dataclass
class ChannelSnapshot:
    channel_name: str
    kind: str
    values: dict[str, Any] = field(default_factory=dict)
    snapshot_hash: str = ""
    state_ref_ids: list[str] = field(default_factory=list)
    schema_version: str = "statebus.channel_snapshot.v2"


@dataclass
class RemoteStepRequest:
    mode: str
    task_id: str
    task_theme: str
    state_root: str
    step: PlanStep
    input_state_refs: list[StateRef] = field(default_factory=list)


@dataclass
class RemoteStepResponse:
    result: StepResult


def to_wire(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_wire(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_wire(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_wire(item) for item in value]
    return value


def message_type(message: Any) -> str:
    return type(message).__name__


def protocol_frame(message: Any) -> dict[str, Any]:
    return {
        "type": message_type(message),
        "payload": to_wire(message),
    }


def protocol_bytes(message: Any) -> bytes:
    envelope = to_protocol_envelope(message)
    if envelope is not None:
        return envelope.SerializeToString()
    return json.dumps(
        protocol_frame(message),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def state_ref_lite_wire_bytes(ref: StateRef) -> int:
    # Keep the benchmark wire-size helper stable as a pointer-only counter even
    # though the formal protobuf path now carries CASF metadata.
    return statebus_pb2.StateRefLite(
        state_id=ref.state_id,
        kind=ref.kind,
        length=ref.length,
    ).ByteSize()


def total_state_ref_lite_wire_bytes(refs: list[StateRef]) -> int:
    return sum(state_ref_lite_wire_bytes(ref) for ref in refs)


def parse_protocol_bytes(payload: bytes) -> Any:
    if not payload:
        raise ValueError("protocol payload is empty")
    envelope = statebus_pb2.WireEnvelope()
    try:
        envelope.ParseFromString(payload)
    except Exception:
        return _parse_json_protocol_frame(payload)
    body = envelope.WhichOneof("body")
    if body is None:
        return _parse_json_protocol_frame(payload)
    if body == "hello":
        message = envelope.hello
        return Hello(
            agent_id=message.agent_id,
            mode=message.mode,
            protocol_version=message.protocol_version,
        )
    if body == "capability":
        message = envelope.capability
        return Capability(
            agent_id=message.agent_id,
            items=[
                CapabilityItem(
                    name=item.name,
                    kind=item.kind,
                    input_schema=item.input_schema,
                    output_schema=item.output_schema,
                    accepted_state_kinds=list(item.accepted_state_kinds),
                    produced_state_kinds=list(item.produced_state_kinds),
                )
                for item in message.items
            ],
        )
    if body == "ack":
        message = envelope.ack
        return Ack(related_id=message.related_id, detail=message.detail)
    if body == "error":
        message = envelope.error
        return Error(
            code=message.code,
            detail=message.detail,
            related_id=message.related_id or None,
        )
    if body == "heartbeat":
        message = envelope.heartbeat
        return Heartbeat(agent_id=message.agent_id, sent_at_ns=message.sent_at_ns)
    if body == "plan":
        message = envelope.plan
        return Plan(
            task_id=message.task_id,
            goal=message.goal,
            steps=[_from_proto_plan_step(item) for item in message.steps],
        )
    if body == "plan_delta":
        message = envelope.plan_delta
        return PlanDelta(
            task_id=message.task_id,
            base_task_id=message.base_task_id,
            goal=message.goal,
            steps=[_from_proto_delta_plan_step(item) for item in message.steps],
            full_plan_fallback=(
                Plan(
                    task_id=message.full_plan_fallback.task_id,
                    goal=message.full_plan_fallback.goal,
                    steps=[_from_proto_plan_step(item) for item in message.full_plan_fallback.steps],
                )
                if message.HasField("full_plan_fallback")
                else None
            ),
            frame_preference=message.frame_preference or "delta",
        )
    if body == "plan_step":
        return _from_proto_plan_step(envelope.plan_step)
    if body == "step_result":
        message = envelope.step_result
        return StepResult(
            step_id=message.step_id,
            success=message.success,
            output_state_refs=[_from_proto_state_ref(item) for item in message.output_state_refs],
            payload=_parse_json_object(message.payload_json),
            error=message.error or None,
            skipped=message.skipped,
            reused_from_memory_id=message.reused_from_memory_id or None,
        )
    if body == "remote_step_request":
        message = envelope.remote_step_request
        return RemoteStepRequest(
            mode=message.mode,
            task_id=message.task_id,
            task_theme=message.task_theme,
            state_root=message.state_root,
            step=_from_proto_plan_step(message.step),
            input_state_refs=[
                _from_proto_state_ref_full(item) for item in message.input_state_refs
            ],
        )
    if body == "remote_step_response":
        message = envelope.remote_step_response
        return RemoteStepResponse(result=_from_proto_remote_step_result(message.result))
    if body == "fetch_request":
        message = envelope.fetch_request
        return FetchRequest(
            blob_hash=message.blob_hash,
            requester_id=message.requester_id,
            state_id=message.state_id,
            accepted_kinds=list(message.accepted_kinds),
            prefer_local_short_circuit=message.prefer_local_short_circuit,
        )
    if body == "fetch_response":
        message = envelope.fetch_response
        return FetchResponse(
            blob_hash=message.blob_hash,
            found=message.found,
            payload_ref=(
                _from_proto_state_ref_full(message.payload_ref)
                if message.HasField("payload_ref")
                else None
            ),
            bytes_sent=int(message.bytes_sent),
            cache_hit=message.cache_hit,
            responder_id=message.responder_id,
        )
    if body == "channel_patch":
        message = envelope.channel_patch
        return ChannelPatch(
            channel_name=message.channel_name,
            ops=_parse_json_object(message.ops_json),
            patch_id=message.patch_id,
            schema_version=message.schema_version or "statebus.channel_patch.v2",
        )
    if body == "channel_snapshot":
        message = envelope.channel_snapshot
        return ChannelSnapshot(
            channel_name=message.channel_name,
            kind=message.kind,
            values=_parse_json_object(message.values_json),
            snapshot_hash=message.snapshot_hash,
            state_ref_ids=list(message.state_ref_ids),
            schema_version=message.schema_version or "statebus.channel_snapshot.v2",
        )
    if body == "memory_query":
        message = envelope.memory_query
        return MemoryQuery(
            task_theme=message.task_theme,
            query_text=message.query_text,
            top_k=message.top_k,
            tags=list(message.tags),
            tags_any=list(message.tags_any),
            tags_all=list(message.tags_all),
            min_confidence=message.min_confidence,
            source_agent_id=message.source_agent_id or None,
            created_after_ns=message.created_after_ns or None,
            encoder_id=message.encoder_id or None,
            limit_active_only=message.limit_active_only,
            required_metadata=_parse_json_object(message.required_metadata_json),
        )
    if body == "memory_commit":
        message = envelope.memory_commit
        return _from_proto_memory_commit(message)
    raise ValueError(f"unsupported protocol body: {body}")


def text_frame(message: Any) -> str:
    if isinstance(message, Hello):
        return (
            f"Agent {message.agent_id} joined the text collaboration channel in {message.mode} mode "
            f"using protocol {message.protocol_version}."
        )
    if isinstance(message, Capability):
        parts = []
        for item in message.items:
            accepted = ", ".join(item.accepted_state_kinds) or "none"
            produced = ", ".join(item.produced_state_kinds) or "none"
            parts.append(
                f"{item.name} ({item.kind}) accepts {accepted} and produces {produced}"
            )
        return f"Agent {message.agent_id} advertised capabilities: " + "; ".join(parts) + "."
    if isinstance(message, Ack):
        return f"Acknowledged {message.related_id}: {message.detail}."
    if isinstance(message, Error):
        related = f" Related object: {message.related_id}." if message.related_id else ""
        return f"Error {message.code}: {message.detail}.{related}"
    if isinstance(message, Heartbeat):
        return f"Heartbeat from {message.agent_id} at {message.sent_at_ns}."
    if isinstance(message, Plan):
        steps = []
        for index, step in enumerate(message.steps, start=1):
            depends = f" after {', '.join(step.depends_on)}" if step.depends_on else ""
            steps.append(
                f"{index}. Ask {step.owner_agent} to {step.action}{depends}. "
                f"Use params {json.dumps(step.params, ensure_ascii=False, sort_keys=True)}."
            )
        return (
            f"Plan for task {message.task_id}: {message.goal}\n"
            + "\n".join(steps)
        )
    if isinstance(message, PlanDelta):
        return (
            f"PlanDelta for task {message.task_id} from {message.base_task_id}: "
            f"{len(message.steps)} step patches."
        )
    if isinstance(message, PlanStep):
        depends = ", ".join(message.depends_on) or "none"
        refs = ", ".join(message.input_state_refs) or "none"
        return (
            f"Instruction for {message.owner_agent}: complete step {message.step_id} with action "
            f"{message.action}. Dependencies: {depends}. Input states: {refs}. "
            f"Parameters: {json.dumps(message.params, ensure_ascii=False, sort_keys=True)}."
        )
    if isinstance(message, StepResult):
        refs = ", ".join(
            f"{ref.state_id}:{ref.kind}:{ref.length}" for ref in message.output_state_refs
        ) or "none"
        status = "skipped via reused memory" if message.skipped else "succeeded" if message.success else "failed"
        payload = json.dumps(to_wire(message.payload), ensure_ascii=False, sort_keys=True)
        return (
            f"Step {message.step_id} {status}. Output states: {refs}. "
            f"Payload: {payload}."
        )
    if isinstance(message, MemoryQuery):
        tags_any = ", ".join(message.tags_any or []) or "none"
        tags_all = ", ".join(message.tags_all or []) or "none"
        required_metadata = _compact_json(_wire_required_metadata(message.required_metadata))
        return (
            f"Memory lookup for theme {message.task_theme} using query '{message.query_text}'. "
            f"Top-k {message.top_k}, minimum confidence {message.min_confidence:.2f}, "
            f"tags-any {tags_any}, tags-all {tags_all}, encoder {message.encoder_id or 'default'}, "
            f"required metadata {required_metadata}."
        )
    if isinstance(message, MemoryCommit):
        tags = ", ".join(message.tags) or "none"
        reusable = ", ".join(message.reusable_steps) or "none"
        evidence = ", ".join(message.evidence_state_ids) or "none"
        metadata = _compact_json(_wire_commit_metadata(message.metadata))
        return (
            f"Commit memory {message.memory_id} for theme {message.task_theme} from "
            f"{message.source_agent_id}. Tags: {tags}. Confidence: {message.confidence:.2f}. "
            f"Embedding state: {message.embedding_state_id or 'none'}. Evidence ids: {evidence}. "
            f"Reusable steps: {reusable}. Required metadata: {metadata}. Summary: {message.summary}"
        )
    if isinstance(message, FetchRequest):
        return f"Fetch blob {message.blob_hash} for state {message.state_id or 'unknown'}."
    if isinstance(message, FetchResponse):
        return (
            f"Fetch response for {message.blob_hash}: "
            f"{'hit' if message.found else 'miss'}, bytes={message.bytes_sent}."
        )
    if isinstance(message, ChannelPatch):
        return f"ChannelPatch {message.channel_name}: {sorted(message.ops)}."
    if isinstance(message, ChannelSnapshot):
        return (
            f"ChannelSnapshot {message.channel_name} ({message.kind}) "
            f"hash={message.snapshot_hash or 'pending'}."
        )
    payload = json.dumps(to_wire(message), ensure_ascii=False, sort_keys=True)
    return f"{message_type(message)} {payload}"


def to_protocol_envelope(message: Any) -> statebus_pb2.WireEnvelope | None:
    if isinstance(message, Hello):
        return statebus_pb2.WireEnvelope(
            hello=statebus_pb2.Hello(
                agent_id=message.agent_id,
                mode=message.mode,
                protocol_version=message.protocol_version,
            )
        )
    if isinstance(message, Capability):
        return statebus_pb2.WireEnvelope(
            capability=statebus_pb2.Capability(
                agent_id=message.agent_id,
                items=[
                    statebus_pb2.CapabilityItem(
                        name=item.name,
                        kind=item.kind,
                        input_schema=item.input_schema,
                        output_schema=item.output_schema,
                        accepted_state_kinds=item.accepted_state_kinds,
                        produced_state_kinds=item.produced_state_kinds,
                    )
                    for item in message.items
                ],
            )
        )
    if isinstance(message, Ack):
        return statebus_pb2.WireEnvelope(
            ack=statebus_pb2.Ack(related_id=message.related_id, detail=message.detail)
        )
    if isinstance(message, Error):
        return statebus_pb2.WireEnvelope(
            error=statebus_pb2.Error(
                code=message.code,
                detail=message.detail,
                related_id=message.related_id or "",
            )
        )
    if isinstance(message, Heartbeat):
        return statebus_pb2.WireEnvelope(
            heartbeat=statebus_pb2.Heartbeat(
                agent_id=message.agent_id,
                sent_at_ns=message.sent_at_ns,
            )
        )
    if isinstance(message, Plan):
        return statebus_pb2.WireEnvelope(
            plan=statebus_pb2.Plan(
                task_id=message.task_id,
                goal=message.goal,
                steps=[_to_proto_plan_step(step) for step in message.steps],
            )
        )
    if isinstance(message, PlanDelta):
        proto = statebus_pb2.PlanDelta(
            task_id=message.task_id,
            base_task_id=message.base_task_id,
            goal=message.goal,
            steps=[_to_proto_delta_plan_step(step) for step in message.steps],
            frame_preference=message.frame_preference,
        )
        if message.full_plan_fallback is not None:
            proto.full_plan_fallback.CopyFrom(
                statebus_pb2.Plan(
                    task_id=message.full_plan_fallback.task_id,
                    goal=message.full_plan_fallback.goal,
                    steps=[_to_proto_plan_step(step) for step in message.full_plan_fallback.steps],
                )
            )
        return statebus_pb2.WireEnvelope(plan_delta=proto)
    if isinstance(message, PlanStep):
        return statebus_pb2.WireEnvelope(plan_step=_to_proto_plan_step(message))
    if isinstance(message, StepResult):
        return statebus_pb2.WireEnvelope(
            step_result=statebus_pb2.StepResult(
                step_id=message.step_id,
                success=message.success,
                output_state_refs=[_to_proto_state_ref(ref) for ref in message.output_state_refs],
                payload_json=_compact_json(message.payload),
                error=message.error or "",
                skipped=message.skipped,
                reused_from_memory_id=message.reused_from_memory_id or "",
            )
        )
    if isinstance(message, RemoteStepRequest):
        return statebus_pb2.WireEnvelope(
            remote_step_request=statebus_pb2.RemoteStepRequest(
                mode=message.mode,
                task_id=message.task_id,
                task_theme=message.task_theme,
                state_root=message.state_root,
                step=_to_proto_plan_step(message.step),
                input_state_refs=[
                    _to_proto_state_ref_full(ref) for ref in message.input_state_refs
                ],
            )
        )
    if isinstance(message, RemoteStepResponse):
        return statebus_pb2.WireEnvelope(
            remote_step_response=statebus_pb2.RemoteStepResponse(
                result=_to_proto_remote_step_result(message.result),
            )
        )
    if isinstance(message, FetchRequest):
        return statebus_pb2.WireEnvelope(
            fetch_request=statebus_pb2.FetchRequest(
                blob_hash=message.blob_hash,
                requester_id=message.requester_id,
                state_id=message.state_id,
                accepted_kinds=message.accepted_kinds,
                prefer_local_short_circuit=message.prefer_local_short_circuit,
            )
        )
    if isinstance(message, FetchResponse):
        proto = statebus_pb2.FetchResponse(
            blob_hash=message.blob_hash,
            found=message.found,
            bytes_sent=message.bytes_sent,
            cache_hit=message.cache_hit,
            responder_id=message.responder_id,
        )
        if message.payload_ref is not None:
            proto.payload_ref.CopyFrom(_to_proto_state_ref_full(message.payload_ref))
        return statebus_pb2.WireEnvelope(fetch_response=proto)
    if isinstance(message, ChannelPatch):
        return statebus_pb2.WireEnvelope(
            channel_patch=statebus_pb2.ChannelPatch(
                channel_name=message.channel_name,
                ops_json=_compact_json(message.ops),
                patch_id=message.patch_id,
                schema_version=message.schema_version,
            )
        )
    if isinstance(message, ChannelSnapshot):
        return statebus_pb2.WireEnvelope(
            channel_snapshot=statebus_pb2.ChannelSnapshot(
                channel_name=message.channel_name,
                kind=message.kind,
                values_json=_compact_json(message.values),
                snapshot_hash=message.snapshot_hash,
                state_ref_ids=message.state_ref_ids,
                schema_version=message.schema_version,
            )
        )
    if isinstance(message, MemoryQuery):
        return statebus_pb2.WireEnvelope(
            memory_query=statebus_pb2.MemoryQuery(
                task_theme=message.task_theme,
                query_text=message.query_text,
                top_k=message.top_k,
                tags=message.tags,
                tags_any=message.tags_any,
                tags_all=message.tags_all,
                min_confidence=message.min_confidence,
                source_agent_id=message.source_agent_id or "",
                created_after_ns=message.created_after_ns or 0,
                encoder_id="",
                limit_active_only=message.limit_active_only,
                required_metadata_json=_compact_json(_wire_required_metadata(message.required_metadata)),
            )
        )
    if isinstance(message, MemoryCommit):
        return statebus_pb2.WireEnvelope(
            memory_commit=_to_proto_memory_commit(message)
        )
    return None


def _to_proto_state_ref(ref: StateRef) -> statebus_pb2.StateRefLite:
    return statebus_pb2.StateRefLite(
        state_id=ref.state_id,
        kind=ref.kind,
        length=ref.length,
        blob_hash=ref.canonical_hash,
        channel=ref.channel,
        exact_replay_ready=ref.exact_replay_ready,
    )


def _to_proto_state_ref_full(ref: StateRef) -> statebus_pb2.StateRefFull:
    return statebus_pb2.StateRefFull(
        state_id=ref.state_id,
        kind=ref.kind,
        storage=ref.storage,
        handle=ref.handle,
        length=ref.length,
        checksum=ref.checksum or "",
        metadata_json=_compact_json(ref.metadata),
        blob_hash=ref.canonical_hash,
        channel=ref.channel,
        compatibility_json=_compact_json(ref.compatibility),
        fetch_uri=ref.fetch_uri,
        local_only=ref.local_only,
        exact_replay_ready=ref.exact_replay_ready,
        created_at_ns=ref.created_at_ns or 0,
    )


def _to_proto_delta_plan_step(step: DeltaPlanStep) -> statebus_pb2.DeltaPlanStep:
    return statebus_pb2.DeltaPlanStep(
        step_id=step.step_id,
        base_step_id=step.base_step_id,
        owner_agent=step.owner_agent,
        action=step.action,
        delta_params_json=_compact_json(step.delta_params),
        delta_depends_on=step.delta_depends_on,
        delta_input_state_refs=step.delta_input_state_refs,
        input_patch_mode=step.input_patch_mode,
        delta_version=step.delta_version,
    )


def _to_proto_plan_step(step: PlanStep) -> statebus_pb2.PlanStep:
    return statebus_pb2.PlanStep(
        step_id=step.step_id,
        owner_agent=step.owner_agent,
        action=step.action,
        input_state_refs=step.input_state_refs,
        params_json=_compact_json(step.params),
        depends_on=step.depends_on,
        semantic_role=step.semantic_role,
    )


def _compact_json(value: Any) -> str:
    return json.dumps(
        to_wire(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _wire_required_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return _filtered_memory_metadata(metadata)


def _wire_commit_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return _filtered_memory_metadata(metadata)


def _filtered_memory_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    filtered: dict[str, Any] = {}
    for key in ("reuse_signature", "memory_purpose", "memory_layer"):
        value = metadata.get(key)
        if value in (None, "", [], {}):
            continue
        filtered[key] = value
    return filtered


def _to_proto_memory_commit(message: MemoryCommit) -> statebus_pb2.MemoryCommit:
    return statebus_pb2.MemoryCommit(
        memory_id=message.memory_id,
        source_agent_id=message.source_agent_id,
        source_task_id=message.source_task_id,
        task_theme=message.task_theme,
        summary=message.summary,
        tags=message.tags,
        evidence_state_ids=message.evidence_state_ids,
        reusable_steps=message.reusable_steps,
        confidence=message.confidence,
        embedding_state_id=message.embedding_state_id or "",
        encoder_id="",
        metadata_json=_compact_json(_wire_commit_metadata(message.metadata)),
        created_at_ns=message.created_at_ns or 0,
    )


def _from_proto_state_ref(ref: statebus_pb2.StateRefLite) -> StateRef:
    return StateRef(
        state_id=ref.state_id,
        kind=ref.kind,
        storage="",
        handle="",
        length=int(ref.length),
        blob_hash=ref.blob_hash,
        channel=ref.channel,
        exact_replay_ready=ref.exact_replay_ready,
    )


def _from_proto_state_ref_full(ref: statebus_pb2.StateRefFull) -> StateRef:
    return StateRef(
        state_id=ref.state_id,
        kind=ref.kind,
        storage=ref.storage,
        handle=ref.handle,
        length=int(ref.length),
        checksum=ref.checksum or None,
        metadata=_parse_json_object(ref.metadata_json),
        blob_hash=ref.blob_hash or ref.checksum,
        channel=ref.channel,
        compatibility=_parse_json_object(ref.compatibility_json),
        fetch_uri=ref.fetch_uri,
        local_only=ref.local_only,
        exact_replay_ready=ref.exact_replay_ready,
        created_at_ns=ref.created_at_ns or None,
    )


def _from_proto_delta_plan_step(step: statebus_pb2.DeltaPlanStep) -> DeltaPlanStep:
    return DeltaPlanStep(
        step_id=step.step_id,
        base_step_id=step.base_step_id,
        owner_agent=step.owner_agent,
        action=step.action,
        delta_params=_parse_json_object(step.delta_params_json),
        delta_depends_on=list(step.delta_depends_on),
        delta_input_state_refs=list(step.delta_input_state_refs),
        input_patch_mode=step.input_patch_mode or "replace",
        delta_version=int(step.delta_version or 1),
    )


def _from_proto_plan_step(step: statebus_pb2.PlanStep) -> PlanStep:
    return PlanStep(
        step_id=step.step_id,
        owner_agent=step.owner_agent,
        action=step.action,
        input_state_refs=list(step.input_state_refs),
        params=_parse_json_object(step.params_json),
        depends_on=list(step.depends_on),
        semantic_role=str(step.semantic_role),
    )


def _from_proto_memory_commit(message: statebus_pb2.MemoryCommit) -> MemoryCommit:
    return MemoryCommit(
        memory_id=message.memory_id,
        source_agent_id=message.source_agent_id,
        source_task_id=message.source_task_id,
        task_theme=message.task_theme,
        summary=message.summary,
        tags=list(message.tags),
        evidence_state_ids=list(message.evidence_state_ids),
        reusable_steps=list(message.reusable_steps),
        confidence=message.confidence,
        embedding_state_id=message.embedding_state_id or None,
        encoder_id=message.encoder_id or None,
        metadata=_parse_json_object(message.metadata_json),
        created_at_ns=message.created_at_ns or None,
    )


def _to_proto_remote_step_result(result: StepResult) -> statebus_pb2.RemoteStepResult:
    proto = statebus_pb2.RemoteStepResult(
        step_id=result.step_id,
        success=result.success,
        output_state_refs=[_to_proto_state_ref_full(ref) for ref in result.output_state_refs],
        payload_json=_compact_json(result.payload),
        error=result.error or "",
        skipped=result.skipped,
        reused_from_memory_id=result.reused_from_memory_id or "",
    )
    if result.memory_commit is not None:
        proto.memory_commit.CopyFrom(_to_proto_memory_commit(result.memory_commit))
    return proto


def _from_proto_remote_step_result(message: statebus_pb2.RemoteStepResult) -> StepResult:
    has_memory_commit = message.HasField("memory_commit")
    return StepResult(
        step_id=message.step_id,
        success=message.success,
        output_state_refs=[_from_proto_state_ref_full(item) for item in message.output_state_refs],
        payload=_parse_json_object(message.payload_json),
        memory_commit=(
            _from_proto_memory_commit(message.memory_commit) if has_memory_commit else None
        ),
        error=message.error or None,
        skipped=message.skipped,
        reused_from_memory_id=message.reused_from_memory_id or None,
    )


def _parse_json_protocol_frame(payload: bytes) -> Any:
    frame = json.loads(payload.decode("utf-8"))
    if not isinstance(frame, dict):
        raise ValueError("protocol frame must be a JSON object")
    message_name = str(frame.get("type", "")).strip()
    message_payload = frame.get("payload", {})
    if not isinstance(message_payload, dict):
        raise ValueError("protocol frame payload must be an object")
    return _message_from_wire_frame(message_name, message_payload)


def _message_from_wire_frame(message_name: str, payload: dict[str, Any]) -> Any:
    if message_name == "Hello":
        return Hello(
            agent_id=str(payload.get("agent_id", "")),
            mode=str(payload.get("mode", "")),
            protocol_version=str(payload.get("protocol_version", "statebus.v0")),
        )
    if message_name == "Capability":
        return Capability(
            agent_id=str(payload.get("agent_id", "")),
            items=[
                CapabilityItem(
                    name=str(item.get("name", "")),
                    kind=str(item.get("kind", "")),
                    input_schema=str(item.get("input_schema", "")),
                    output_schema=str(item.get("output_schema", "")),
                    accepted_state_kinds=[str(value) for value in item.get("accepted_state_kinds", [])],
                    produced_state_kinds=[str(value) for value in item.get("produced_state_kinds", [])],
                )
                for item in payload.get("items", [])
                if isinstance(item, dict)
            ],
        )
    if message_name == "Ack":
        return Ack(
            related_id=str(payload.get("related_id", "")),
            detail=str(payload.get("detail", "ok")),
        )
    if message_name == "Error":
        related_id = payload.get("related_id")
        return Error(
            code=str(payload.get("code", "")),
            detail=str(payload.get("detail", "")),
            related_id=None if related_id in (None, "") else str(related_id),
        )
    if message_name == "Heartbeat":
        return Heartbeat(
            agent_id=str(payload.get("agent_id", "")),
            sent_at_ns=int(payload.get("sent_at_ns", 0)),
        )
    if message_name == "PlanStep":
        return PlanStep(
            step_id=str(payload.get("step_id", "")),
            owner_agent=str(payload.get("owner_agent", "")),
            action=str(payload.get("action", "")),
            input_state_refs=[str(value) for value in payload.get("input_state_refs", [])],
            params=dict(payload.get("params", {}) or {}),
            depends_on=[str(value) for value in payload.get("depends_on", [])],
            semantic_role=str(payload.get("semantic_role", "")),
        )
    if message_name == "Plan":
        return Plan(
            task_id=str(payload.get("task_id", "")),
            goal=str(payload.get("goal", "")),
            steps=[
                _message_from_wire_frame("PlanStep", item)
                for item in payload.get("steps", [])
                if isinstance(item, dict)
            ],
        )
    if message_name == "PlanDelta":
        fallback_payload = payload.get("full_plan_fallback")
        return PlanDelta(
            task_id=str(payload.get("task_id", "")),
            base_task_id=str(payload.get("base_task_id", "")),
            goal=str(payload.get("goal", "")),
            steps=[
                DeltaPlanStep(
                    step_id=str(item.get("step_id", "")),
                    base_step_id=str(item.get("base_step_id", "")),
                    owner_agent=str(item.get("owner_agent", "")),
                    action=str(item.get("action", "")),
                    delta_params=dict(item.get("delta_params", {}) or {}),
                    delta_depends_on=[str(value) for value in item.get("delta_depends_on", [])],
                    delta_input_state_refs=[str(value) for value in item.get("delta_input_state_refs", [])],
                    input_patch_mode=str(item.get("input_patch_mode", "replace")),
                    delta_version=int(item.get("delta_version", 1)),
                )
                for item in payload.get("steps", [])
                if isinstance(item, dict)
            ],
            full_plan_fallback=(
                _message_from_wire_frame("Plan", fallback_payload)
                if isinstance(fallback_payload, dict)
                else None
            ),
            frame_preference=str(payload.get("frame_preference", "delta")),
        )
    if message_name == "StateRef":
        return _state_ref_from_payload(payload)
    if message_name == "StepResult":
        memory_commit = payload.get("memory_commit")
        memory_commits = payload.get("memory_commits", [])
        return StepResult(
            step_id=str(payload.get("step_id", "")),
            success=bool(payload.get("success", False)),
            output_state_refs=[
                _state_ref_from_payload(item)
                for item in payload.get("output_state_refs", [])
                if isinstance(item, dict)
            ],
            payload=dict(payload.get("payload", {}) or {}),
            memory_commit=(
                None
                if not isinstance(memory_commit, dict)
                else _message_from_wire_frame("MemoryCommit", memory_commit)
            ),
            memory_commits=[
                _message_from_wire_frame("MemoryCommit", item)
                for item in memory_commits
                if isinstance(item, dict)
            ],
            error=None if payload.get("error") in (None, "") else str(payload.get("error")),
            skipped=bool(payload.get("skipped", False)),
            reused_from_memory_id=(
                None
                if payload.get("reused_from_memory_id") in (None, "")
                else str(payload.get("reused_from_memory_id"))
            ),
        )
    if message_name == "MemoryQuery":
        return MemoryQuery(
            task_theme=str(payload.get("task_theme", "")),
            query_text=str(payload.get("query_text", "")),
            top_k=int(payload.get("top_k", 0)),
            tags=[str(value) for value in payload.get("tags", [])],
            tags_any=[str(value) for value in payload.get("tags_any", [])],
            tags_all=[str(value) for value in payload.get("tags_all", [])],
            min_confidence=float(payload.get("min_confidence", 0.0)),
            source_agent_id=(
                None
                if payload.get("source_agent_id") in (None, "")
                else str(payload.get("source_agent_id"))
            ),
            created_after_ns=(
                None
                if payload.get("created_after_ns") in (None, 0)
                else int(payload.get("created_after_ns"))
            ),
            encoder_id=None if payload.get("encoder_id") in (None, "") else str(payload.get("encoder_id")),
            limit_active_only=bool(payload.get("limit_active_only", True)),
            required_metadata=dict(payload.get("required_metadata", {}) or {}),
            session_id=str(payload.get("session_id", "")).strip(),
        )
    if message_name == "MemoryCommit":
        return MemoryCommit(
            memory_id=str(payload.get("memory_id", "")),
            source_agent_id=str(payload.get("source_agent_id", "")),
            source_task_id=str(payload.get("source_task_id", "")),
            task_theme=str(payload.get("task_theme", "")),
            summary=str(payload.get("summary", "")),
            tags=[str(value) for value in payload.get("tags", [])],
            evidence_state_ids=[str(value) for value in payload.get("evidence_state_ids", [])],
            reusable_steps=[str(value) for value in payload.get("reusable_steps", [])],
            confidence=float(payload.get("confidence", 1.0)),
            embedding_text=(
                None if payload.get("embedding_text") in (None, "") else str(payload.get("embedding_text"))
            ),
            embedding_state_id=(
                None
                if payload.get("embedding_state_id") in (None, "")
                else str(payload.get("embedding_state_id"))
            ),
            encoder_id=None if payload.get("encoder_id") in (None, "") else str(payload.get("encoder_id")),
            metadata=dict(payload.get("metadata", {}) or {}),
            evidence_state_refs=[
                _state_ref_from_payload(item)
                for item in payload.get("evidence_state_refs", [])
                if isinstance(item, dict)
            ],
            created_at_ns=(
                None
                if payload.get("created_at_ns") in (None, 0)
                else int(payload.get("created_at_ns"))
            ),
            memory_purpose=str(payload.get("memory_purpose", "")),
            memory_layer=str(payload.get("memory_layer", "")),
            replay_class=str(payload.get("replay_class", "")),
            route=str(payload.get("route", "")),
            route_source=str(payload.get("route_source", "")),
            route_provenance=[str(value) for value in payload.get("route_provenance", [])],
            route_confidence=float(payload.get("route_confidence", 0.0)),
            retrieved_doc_ids=[str(value) for value in payload.get("retrieved_doc_ids", [])],
            fresh_evidence_sha256=str(payload.get("fresh_evidence_sha256", "")),
            reuse_signature=str(payload.get("reuse_signature", "")),
            step_output_state_ids=[str(value) for value in payload.get("step_output_state_ids", [])],
            step_output_state_refs=[
                _state_ref_from_payload(item)
                for item in payload.get("step_output_state_refs", [])
                if isinstance(item, dict)
            ],
            tool_name=str(payload.get("tool_name", "")),
            source_session_id=str(payload.get("source_session_id", "")),
            tier=str(payload.get("tier", "")),
            commit_ref=str(payload.get("commit_ref", "")),
        )
    if message_name == "FetchRequest":
        return FetchRequest(
            blob_hash=str(payload.get("blob_hash", "")),
            requester_id=str(payload.get("requester_id", "")),
            state_id=str(payload.get("state_id", "")),
            accepted_kinds=[str(value) for value in payload.get("accepted_kinds", [])],
            prefer_local_short_circuit=bool(payload.get("prefer_local_short_circuit", True)),
        )
    if message_name == "FetchResponse":
        payload_ref = payload.get("payload_ref")
        return FetchResponse(
            blob_hash=str(payload.get("blob_hash", "")),
            found=bool(payload.get("found", False)),
            payload_ref=_state_ref_from_payload(payload_ref) if isinstance(payload_ref, dict) else None,
            bytes_sent=int(payload.get("bytes_sent", 0)),
            cache_hit=bool(payload.get("cache_hit", False)),
            responder_id=str(payload.get("responder_id", "")),
        )
    if message_name == "ChannelPatch":
        return ChannelPatch(
            channel_name=str(payload.get("channel_name", "")),
            ops=dict(payload.get("ops", {}) or {}),
            patch_id=str(payload.get("patch_id", "")),
            schema_version=str(payload.get("schema_version", "statebus.channel_patch.v2")),
        )
    if message_name == "ChannelSnapshot":
        return ChannelSnapshot(
            channel_name=str(payload.get("channel_name", "")),
            kind=str(payload.get("kind", "")),
            values=dict(payload.get("values", {}) or {}),
            snapshot_hash=str(payload.get("snapshot_hash", "")),
            state_ref_ids=[str(value) for value in payload.get("state_ref_ids", [])],
            schema_version=str(payload.get("schema_version", "statebus.channel_snapshot.v2")),
        )
    if message_name == "RemoteStepRequest":
        return RemoteStepRequest(
            mode=str(payload.get("mode", "protocol")),
            task_id=str(payload.get("task_id", "")),
            task_theme=str(payload.get("task_theme", "")),
            state_root=str(payload.get("state_root", "")),
            step=_message_from_wire_frame("PlanStep", dict(payload.get("step", {}) or {})),
            input_state_refs=[
                _state_ref_from_payload(item)
                for item in payload.get("input_state_refs", [])
                if isinstance(item, dict)
            ],
        )
    if message_name == "RemoteStepResponse":
        result_payload = payload.get("result", {})
        if not isinstance(result_payload, dict):
            raise ValueError("remote step response missing result payload")
        return RemoteStepResponse(
            result=_message_from_wire_frame("StepResult", result_payload),
        )
    raise ValueError(f"unsupported JSON protocol message: {message_name}")


def _state_ref_from_payload(payload: dict[str, Any]) -> StateRef:
    return StateRef(
        state_id=str(payload.get("state_id", "")),
        kind=str(payload.get("kind", "")),
        length=int(payload.get("length", 0)),
        blob_hash=str(payload.get("blob_hash", payload.get("checksum", "") or "")),
        metadata=dict(payload.get("metadata", {}) or {}),
        storage=str(payload.get("storage", "")),
        handle=str(payload.get("handle", "")),
        checksum=None if payload.get("checksum") in (None, "") else str(payload.get("checksum")),
        channel=str(payload.get("channel", "")),
        compatibility=dict(payload.get("compatibility", {}) or {}),
        fetch_uri=str(payload.get("fetch_uri", "")),
        local_only=bool(payload.get("local_only", False)),
        exact_replay_ready=bool(payload.get("exact_replay_ready", False)),
        created_at_ns=(
            None if payload.get("created_at_ns") in (None, 0) else int(payload.get("created_at_ns"))
        ),
    )


def _parse_json_object(payload: str) -> dict[str, Any]:
    if not payload:
        return {}
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("expected JSON object payload")
    return value


@dataclass
class StepTree:
    step_id: str
    agent_id: str
    action: str
    input_blobs: dict[str, str] = field(default_factory=dict)
    output_blobs: dict[str, str] = field(default_factory=dict)
    started_at: float = 0.0
    finished_at: float = 0.0
    phase_timing: dict[str, float] = field(default_factory=dict)
    channel_snapshots: dict[str, str] = field(default_factory=dict)
    invariants: dict[str, bool] = field(default_factory=dict)

    def compute_tree_hash(self) -> str:
        import hashlib, msgpack
        payload = msgpack.packb({
            "step_id": self.step_id,
            "agent_id": self.agent_id,
            "action": self.action,
            "input_blobs": sorted(self.input_blobs.items()),
            "output_blobs": sorted(self.output_blobs.items()),
            "channel_snapshots": sorted(self.channel_snapshots.items()),
            "invariants": sorted(self.invariants.items()),
        })
        return hashlib.sha256(payload).hexdigest()


@dataclass
class TaskCommit:
    task_id: str
    task_group: str
    task_theme: str
    step_trees: list[StepTree] = field(default_factory=list)
    parent_hash: str = ""
    commit_hash: str = ""
    mode: str = "protocol"
    created_at: float = 0.0
    task_metrics: dict[str, Any] = field(default_factory=dict)
    memory_queries: list[dict[str, Any]] = field(default_factory=list)
    channel_snapshot_hash: str = ""
    invariant_summary: dict[str, int] = field(default_factory=dict)

    def compute_commit_hash(self) -> str:
        import hashlib, msgpack
        payload = msgpack.packb({
            "task_id": self.task_id,
            "task_group": self.task_group,
            "task_theme": self.task_theme,
            "step_hashes": [st.compute_tree_hash() for st in self.step_trees],
            "parent_hash": self.parent_hash,
            "mode": self.mode,
            "channel_snapshot_hash": self.channel_snapshot_hash,
            "invariant_summary": sorted(self.invariant_summary.items()),
        })
        return hashlib.sha256(payload).hexdigest()

    def seal(self) -> str:
        self.commit_hash = self.compute_commit_hash()
        return self.commit_hash


@dataclass
class ExecutionDAG:
    dag_id: str
    task_commits: dict[str, TaskCommit] = field(default_factory=dict)
    task_order: list[str] = field(default_factory=list)

    @property
    def root_hashes(self) -> list[str]:
        return [tc.commit_hash for tc in self.task_commits.values()
                if not tc.parent_hash]

    def verify_integrity(self) -> bool:
        for tc in self.task_commits.values():
            if tc.commit_hash != tc.compute_commit_hash():
                return False
            if tc.parent_hash:
                if tc.parent_hash not in self.task_commits:
                    return False
        return True

    def add_commit(self, commit: TaskCommit) -> None:
        if not commit.commit_hash:
            commit.seal()
        self.task_commits[commit.commit_hash] = commit
        self.task_order.append(commit.commit_hash)

    def find_similar_subtree(
        self, task_theme: str, query_terms: set[str], min_similarity: float = 0.5
    ) -> list[tuple[TaskCommit, float]]:
        results: list[tuple[TaskCommit, float]] = []
        for tc in self.task_commits.values():
            if tc.task_theme != task_theme:
                continue
            sim = self._structural_similarity(tc, query_terms)
            if sim >= min_similarity:
                results.append((tc, sim))
        results.sort(key=lambda x: -x[1])
        return results

    @staticmethod
    def _structural_similarity(commit: TaskCommit, query_terms: set[str]) -> float:
        score = 0.0
        if not commit.step_trees:
            return 0.0
        actions = [st.action for st in commit.step_trees]
        expected = ["RETRIEVE_EVIDENCE", "EXECUTE_PLAYBOOK", "SUMMARIZE_AND_COMMIT"]
        for i, act in enumerate(actions):
            if i < len(expected) and act == expected[i]:
                score += 0.15
        for st in commit.step_trees:
            input_kinds = set(st.input_blobs.keys())
            if "DENSE_EVIDENCE" in input_kinds:
                score += 0.10
            if "FEATURE_BUNDLE" in st.output_blobs:
                score += 0.10
        stored_terms: set[str] = set()
        for st in commit.step_trees:
            for blob_hash in st.input_blobs.values():
                stored_terms.update(t for t in blob_hash.split("_") if len(t) >= 4)
        if query_terms and stored_terms:
            overlap = len(query_terms & stored_terms)
            score += 0.15 * (overlap / max(len(query_terms), 1))
        return min(score, 1.0)
