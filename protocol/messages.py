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
    storage: str
    handle: str
    length: int
    checksum: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


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


@dataclass
class Plan:
    task_id: str
    goal: str
    steps: list[PlanStep]


@dataclass
class StepResult:
    step_id: str
    success: bool
    output_state_refs: list[StateRef] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    memory_commit: MemoryCommit | None = None
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


@dataclass
class MemoryHit:
    memory_id: str
    confidence: float
    embedding_id: int | None = None
    faiss_score: float = 0.0
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
        tags = ", ".join(message.tags_any or message.tags or []) or "none"
        return (
            f"Memory lookup for theme {message.task_theme} using query '{message.query_text}'. "
            f"Top-k {message.top_k}, minimum confidence {message.min_confidence:.2f}, tags {tags}."
        )
    if isinstance(message, MemoryCommit):
        tags = ", ".join(message.tags) or "none"
        reusable = ", ".join(message.reusable_steps) or "none"
        return (
            f"Commit memory {message.memory_id} for theme {message.task_theme} from "
            f"{message.source_agent_id}. Tags: {tags}. Reusable steps: {reusable}. "
            f"Summary: {message.summary}"
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
                encoder_id=message.encoder_id or "",
                limit_active_only=message.limit_active_only,
                required_metadata_json=_compact_json(message.required_metadata),
            )
        )
    if isinstance(message, MemoryCommit):
        return statebus_pb2.WireEnvelope(
            memory_commit=statebus_pb2.MemoryCommit(
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
                encoder_id=message.encoder_id or "",
                metadata_json=_compact_json(message.metadata),
                created_at_ns=message.created_at_ns or 0,
            )
        )
    return None


def _to_proto_state_ref(ref: StateRef) -> statebus_pb2.StateRefLite:
    return statebus_pb2.StateRefLite(
        state_id=ref.state_id,
        kind=ref.kind,
        length=ref.length,
    )


def _to_proto_plan_step(step: PlanStep) -> statebus_pb2.PlanStep:
    return statebus_pb2.PlanStep(
        step_id=step.step_id,
        owner_agent=step.owner_agent,
        action=step.action,
        input_state_refs=step.input_state_refs,
        params_json=_compact_json(step.params),
        depends_on=step.depends_on,
    )


def _compact_json(value: Any) -> str:
    return json.dumps(
        to_wire(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
