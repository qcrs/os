from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any


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
