from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import msgpack

from eval.fairness_gates import (
    CarrierFairnessGate,
    evaluate_execution_fairness_gate,
    evaluate_plan_fairness_gate,
)
from eval.metrics import TaskMetrics
from memory.store import EmbeddingProvider, MemoryStore
from protocol.channels import attach_channel_metadata
from runtime.contracts import (
    CapabilityTable,
    SchemaInterceptor,
    SchemaValidationError,
    StateContractRegistry,
    default_state_contract_registry,
)
from runtime.context_slice import LLMContextSlice, build_context_slice
from runtime.llm import LLMResult
from runtime.role_contracts import (
    RoleExecutionContract,
    default_role_execution_contracts,
    normalize_comparator_role_name,
)
from runtime.reuse_contract import resolve_runtime_reuse_contract
from runtime.reuse_contract import runtime_reuse_contract_gates
from runtime.task_profile import RuntimeTaskProfile, build_reuse_signature
from protocol.messages import (
    Ack,
    ChannelPatch,
    ChannelSnapshot,
    ExecutionDAG,
    Error,
    FetchRequest,
    FetchResponse,
    Hello,
    MemoryCommit,
    MemoryHit,
    Plan,
    PlanDelta,
    PlanStep,
    StateRef,
    StepTree,
    StepResult,
    TaskCommit,
    message_type,
    protocol_bytes,
    total_state_ref_lite_wire_bytes,
    text_frame,
)
from statepool.store import (
    CAS_BLOB_STORAGE,
    MMAP_FILE_STORAGE,
    PY_SHARED_MEMORY_STORAGE,
    StatePool,
    StatePoolConfig,
    cleanup_shared_memory_handles,
)


def _stable_json_hash(value: object) -> str:
    import hashlib
    import json

    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_ROUTE_SNAPSHOT_REPLAY_KEYS = frozenset(
    {
        "route",
        "tool_name",
        "route_source",
        "route_confidence",
        "route_provenance",
        "matched_signals",
        "matched_tags",
        "match_score",
        "hint_doc_ids",
        "hint_route",
        "hint_tool_name",
        "tool_candidates",
        "retrieved_doc_ids",
        "feature_evidence_sha256",
        "feature_fresh_evidence_sha256",
    }
)


def _channel_snapshot_hash(channel_name: str, values: dict[str, Any]) -> str:
    if channel_name == "route":
        replay_core = {
            key: values[key]
            for key in sorted(_ROUTE_SNAPSHOT_REPLAY_KEYS)
            if key in values
        }
        candidates = values.get("tool_candidates")
        if isinstance(candidates, list):
            route = str(values.get("route", "")).strip()
            tool_name = str(values.get("tool_name", "")).strip()
            selected_candidates = [
                dict(item)
                for item in candidates
                if isinstance(item, dict)
                and str(item.get("route", "")).strip() == route
                and str(item.get("tool_name", "")).strip() == tool_name
            ]
            if selected_candidates:
                replay_core["tool_candidates"] = selected_candidates
        return _stable_json_hash(replay_core)
    return _stable_json_hash(values)


@dataclass
class RunSession:
    mode: str
    handshake_complete: bool = False
    capability_table: CapabilityTable = field(default_factory=CapabilityTable)
    execution_dag: ExecutionDAG = field(
        default_factory=lambda: ExecutionDAG(dag_id=f"dag-{uuid4().hex[:8]}")
    )
    setup_message_count: int = 0
    setup_text_chars: int = 0
    setup_text_bytes: int = 0
    setup_protocol_bytes: int = 0
    message_breakdown: dict[str, dict[str, int]] = field(default_factory=dict)
    owned_shared_handles: set[str] = field(default_factory=set)

    def record_message(self, message: object, *, phase: str) -> tuple[int, int, int]:
        protocol_size = len(protocol_bytes(message))
        rendered = text_frame(message)
        text_chars = len(rendered)
        text_size = len(rendered.encode("utf-8"))
        name = message_type(message)
        row = self.message_breakdown.setdefault(
            name,
            {
                "message_count": 0,
                "protocol_bytes": 0,
                "text_bytes": 0,
                "setup_message_count": 0,
                "setup_protocol_bytes": 0,
                "setup_text_bytes": 0,
                "steady_message_count": 0,
                "steady_protocol_bytes": 0,
                "steady_text_bytes": 0,
            },
        )
        row["message_count"] += 1
        row["protocol_bytes"] += protocol_size
        row["text_bytes"] += text_size
        phase_prefix = "setup" if phase == "setup" else "steady"
        row[f"{phase_prefix}_message_count"] += 1
        row[f"{phase_prefix}_protocol_bytes"] += protocol_size
        row[f"{phase_prefix}_text_bytes"] += text_size
        if phase == "setup":
            self.setup_message_count += 1
            self.setup_text_chars += text_chars
            self.setup_text_bytes += text_size
            self.setup_protocol_bytes += protocol_size
        return protocol_size, text_chars, text_size

    def setup_metrics(self) -> dict[str, int]:
        return {
            "message_count": self.setup_message_count,
            "text_chars": self.setup_text_chars,
            "text_bytes": self.setup_text_bytes,
            "protocol_bytes": self.setup_protocol_bytes,
        }

    def message_breakdown_rows(self) -> list[dict[str, int | str]]:
        rows: list[dict[str, int | str]] = []
        for name in sorted(self.message_breakdown):
            row = dict(self.message_breakdown[name])
            row["message_type"] = name
            rows.append(row)
        return rows

    def cleanup(self) -> None:
        cleanup_shared_memory_handles(self.owned_shared_handles)
        self.owned_shared_handles.clear()


@dataclass
class RunContext:
    mode: str
    trace_id: str
    task_id: str
    task_group: str
    task_theme: str
    session: RunSession
    statepool: StatePool
    memory_store: MemoryStore
    summary_contract: str = "actions_plus_evidence"
    task_corpus_doc_ids: tuple[str, ...] = ()
    task_corpus_path: str = ""
    task: object | None = None
    metrics: TaskMetrics = field(default_factory=TaskMetrics)
    results: dict[str, StepResult] = field(default_factory=dict)
    prepared_input_refs: dict[str, list[StateRef]] = field(default_factory=dict)
    step_roles: dict[str, str] = field(default_factory=dict)
    state_refs: dict[str, StateRef] = field(default_factory=dict)
    memory_hits: list[MemoryHit] = field(default_factory=list)
    memory_search_cache: dict[tuple[object, ...], list[MemoryHit]] = field(default_factory=dict)
    replay_candidate_cache: dict[tuple[object, ...], list[MemoryHit]] = field(default_factory=dict)
    pruned_step_ids: list[str] = field(default_factory=list)
    reuse_hit: MemoryHit | None = None
    reuse_mode: str = "none"
    rejected_memory_hit: MemoryHit | None = None
    runtime_profile: RuntimeTaskProfile = field(default_factory=RuntimeTaskProfile)
    channel_store: dict[str, dict[str, Any]] = field(default_factory=dict)
    channel_snapshots: dict[str, ChannelSnapshot] = field(default_factory=dict)
    trajectory_steps: list[StepTree] = field(default_factory=list)
    execution_dag: ExecutionDAG = field(default_factory=lambda: ExecutionDAG(dag_id=f"dag-{uuid4().hex[:8]}"))
    memory_tiers: dict[str, list[str]] = field(
        default_factory=lambda: {
            "working_memories": [],
            "long_term_memories": [],
            "replay_episodes": [],
            "task_commits": [],
        }
    )
    replay_decision: dict[str, Any] = field(default_factory=dict)
    sealed_task_commit_hash: str = ""
    planner_source: str = ""
    planner_step_count: int = 0
    planner_contract_valid: bool = False
    planner_contract_valid_final: bool = False
    planner_one_shot_valid: bool = True
    planner_repair_attempt_count: int = 0
    planner_last_output: str = ""
    planner_last_error: str = ""
    llm_raw_outputs: dict[str, str] = field(default_factory=dict)
    llm_parse_status: dict[str, str] = field(default_factory=dict)
    blob_fetch_metrics: dict[str, Any] = field(
        default_factory=lambda: {
            "blob_fetch_count": 0,
            "blob_fetch_bytes": 0,
            "blob_fetch_hits": 0,
        }
    )
    role_contracts: dict[str, RoleExecutionContract] = field(
        default_factory=default_role_execution_contracts
    )
    role_context_slices: dict[str, LLMContextSlice] = field(default_factory=dict)
    role_trace: list[dict[str, Any]] = field(default_factory=list)
    contract_errors: list[str] = field(default_factory=list)
    fairness_gate: CarrierFairnessGate | None = None
    plan_fairness_gate: CarrierFairnessGate | None = None

    def emit(self, message: object) -> None:
        protocol_size, text_chars, text_size = self.session.record_message(message, phase="steady")
        self.metrics.message_count += 1
        self.metrics.protocol_bytes += protocol_size
        self.metrics.text_chars += text_chars
        self.metrics.text_bytes += text_size

    def register_state(self, ref: StateRef) -> None:
        if ref.state_id in self.state_refs:
            self.state_refs[ref.state_id] = ref
            return
        self.state_refs[ref.state_id] = ref
        self.metrics.state_ref_count += 1
        self.metrics.state_bytes += ref.length
        if ref.storage == PY_SHARED_MEMORY_STORAGE:
            self.metrics.shared_memory_state_ref_count += 1
            self.metrics.shared_memory_state_bytes += ref.length
        elif ref.storage == MMAP_FILE_STORAGE:
            self.metrics.mmap_state_ref_count += 1
            self.metrics.mmap_state_bytes += ref.length

    def record_transfer_inputs(self, refs: list[StateRef]) -> None:
        textual_kinds = {"DENSE_EVIDENCE", "TOOL_ARTIFACT"}
        nontext_kinds = {
            "FEATURE_BUNDLE",
            "EMBEDDING",
            "RANKED_EVIDENCE_BUNDLE",
            "TOOL_CANDIDATE_SET",
            "REPLAY_ELIGIBILITY_BUNDLE",
            "EXECUTOR_DECISION_PACKET",
            "VALIDATION_GATE_PACKET",
        }
        self.metrics.handoff_ref_count += len(refs)
        self.metrics.handoff_wire_bytes += total_state_ref_lite_wire_bytes(refs)
        for ref in refs:
            self.metrics.handoff_payload_bytes += ref.length
            if ref.kind in nontext_kinds:
                self.metrics.handoff_nontext_ref_count += 1
                self.metrics.handoff_nontext_bytes += ref.length
            elif ref.kind in textual_kinds:
                self.metrics.handoff_textual_ref_count += 1
                self.metrics.handoff_textual_bytes += ref.length

    def resolve_ref(self, state_id: str) -> StateRef:
        ref = self.state_refs.get(state_id)
        if ref is not None:
            return ref
        ref = self.statepool.load_ref(state_id)
        self.state_refs[state_id] = ref
        return ref

    def set_step_input_refs(self, step_id: str, refs: list[StateRef]) -> None:
        self.prepared_input_refs[step_id] = list(refs)

    def step_input_refs(self, step_id: str) -> list[StateRef]:
        return list(self.prepared_input_refs.get(step_id, []))

    def set_step_role(self, step_id: str, semantic_role: str) -> None:
        role = str(semantic_role).strip().lower()
        if role:
            self.step_roles[step_id] = role

    def semantic_role_for_step(self, step_id: str) -> str:
        return str(self.step_roles.get(step_id, "")).strip().lower()

    def step_input_refs_for_role(self, semantic_role: str) -> list[StateRef]:
        role = str(semantic_role).strip().lower()
        for step_id, mapped_role in self.step_roles.items():
            if mapped_role == role:
                return self.step_input_refs(step_id)
        if role:
            return self.step_input_refs(role)
        return []

    def result_for_role(self, semantic_role: str) -> StepResult | None:
        role = str(semantic_role).strip().lower()
        for step_id, mapped_role in self.step_roles.items():
            if mapped_role == role:
                return self.results.get(step_id)
        if role:
            return self.results.get(role)
        return None

    def put_text_state(
        self,
        *,
        state_id: str,
        kind: str,
        text: str,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        ref = self.statepool.put_replay_restorable_bytes(
            state_id=state_id,
            kind=kind,
            payload=text.encode("utf-8"),
            metadata=attach_channel_metadata(metadata, state_kind=kind),
        )
        self.register_state(ref)
        return ref

    def put_bytes_state(
        self,
        *,
        state_id: str,
        kind: str,
        payload: bytes,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        ref = self.statepool.put_bytes(
            state_id,
            kind,
            payload,
            metadata=attach_channel_metadata(metadata, state_kind=kind),
        )
        self.register_state(ref)
        return ref

    def get_text_state(self, ref: StateRef) -> str:
        return self.statepool.get_text(ref)

    def put_embedding_state(
        self,
        *,
        state_id: str,
        text: str,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        vector = self.memory_store.embedder.embed_text(text)
        ref = self.statepool.put_replay_restorable_bytes(
            state_id=state_id,
            kind="EMBEDDING",
            payload=vector.astype("float32").tobytes(),
            metadata={
                "encoder_id": self.memory_store.embedder.encoder_id,
                "vector_dim": int(vector.shape[0]),
                "dtype": "float32",
                **attach_channel_metadata(None, state_kind="EMBEDDING"),
                **dict(metadata or {}),
            },
        )
        self.register_state(ref)
        return ref

    def get_embedding_state(self, ref: StateRef) -> object:
        return self.statepool.get_embedding(ref)

    def put_feature_state(
        self,
        *,
        state_id: str,
        feature_bundle: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        return self._put_msgpack_state(
            state_id=state_id,
            kind="FEATURE_BUNDLE",
            schema="statebus.feature_bundle.v1",
            payload=feature_bundle,
            metadata=metadata,
        )

    def get_feature_state(self, ref: StateRef) -> dict[str, object]:
        return self._get_msgpack_state(ref)

    def get_channel_snapshot_state(self, ref: StateRef) -> ChannelSnapshot:
        payload = self._get_msgpack_state(ref)
        return ChannelSnapshot(
            channel_name=str(payload.get("channel_name", "")),
            kind=str(payload.get("kind", "")),
            values=dict(payload.get("values", {}) or {}),
            snapshot_hash=str(payload.get("snapshot_hash", "")),
            state_ref_ids=[str(item) for item in payload.get("state_ref_ids", [])],
            schema_version=str(
                payload.get("schema", payload.get("schema_version", "statebus.channel_snapshot.v2"))
            ),
        )

    def put_channel_patch(
        self,
        *,
        state_id: str,
        patch: ChannelPatch,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        ref = self._put_msgpack_state(
            state_id=state_id,
            kind="CHANNEL_PATCH",
            schema=patch.schema_version,
            payload={
                "schema": patch.schema_version,
                "channel_name": patch.channel_name,
                "ops": dict(patch.ops),
                "patch_id": patch.patch_id,
            },
            metadata=metadata,
        )
        self.apply_channel_patch(patch)
        return ref

    def put_channel_snapshot(
        self,
        *,
        state_id: str,
        snapshot: ChannelSnapshot,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        if not snapshot.snapshot_hash:
            snapshot.snapshot_hash = _channel_snapshot_hash(
                snapshot.channel_name,
                snapshot.values,
            )
        self.channel_snapshots[snapshot.channel_name] = snapshot
        return self._put_msgpack_state(
            state_id=state_id,
            kind="CHANNEL_SNAPSHOT",
            schema=snapshot.schema_version,
            payload={
                "schema": snapshot.schema_version,
                "channel_name": snapshot.channel_name,
                "kind": snapshot.kind,
                "values": dict(snapshot.values),
                "snapshot_hash": snapshot.snapshot_hash,
                "state_ref_ids": list(snapshot.state_ref_ids),
            },
            metadata=metadata,
        )

    def apply_channel_patch(self, patch: ChannelPatch) -> ChannelSnapshot:
        current = dict(self.channel_store.get(patch.channel_name, {}))
        current.update(dict(patch.ops))
        self.channel_store[patch.channel_name] = current
        snapshot = ChannelSnapshot(
            channel_name=patch.channel_name,
            kind="LAST_VALUE",
            values=current,
            snapshot_hash=_channel_snapshot_hash(patch.channel_name, current),
        )
        self.channel_snapshots[patch.channel_name] = snapshot
        return snapshot

    def get_channel_snapshot(self, channel_name: str) -> ChannelSnapshot | None:
        return self.channel_snapshots.get(channel_name)

    def resolve_channel_snapshot(self, refs: list[StateRef], channel_name: str) -> ChannelSnapshot | None:
        snapshot = self.channel_snapshots.get(channel_name)
        if snapshot is not None:
            return snapshot
        for ref in refs:
            if ref.kind != "CHANNEL_SNAPSHOT":
                continue
            if str(ref.metadata.get("channel_name", ref.channel)).strip() != channel_name:
                continue
            snapshot = self.get_channel_snapshot_state(ref)
            self.channel_snapshots[channel_name] = snapshot
            self.channel_store[channel_name] = dict(snapshot.values)
            return snapshot
        return None

    def fetch_blob(self, ref: StateRef, *, requester_id: str = "runtime") -> FetchResponse:
        request = FetchRequest(
            blob_hash=ref.canonical_hash,
            requester_id=requester_id,
            state_id=ref.state_id,
            accepted_kinds=[ref.kind],
        )
        self.emit(request)
        cache_hit = bool(ref.canonical_hash and self.statepool.has_blob(ref.canonical_hash))
        if cache_hit:
            bytes_sent = int(ref.length)
        else:
            payload = self.statepool.get_bytes(ref)
            bytes_sent = len(payload)
        self.record_blob_fetch(bytes_count=bytes_sent, cache_hit=cache_hit)
        response = FetchResponse(
            blob_hash=ref.canonical_hash,
            found=True,
            payload_ref=ref,
            bytes_sent=bytes_sent,
            cache_hit=cache_hit,
            responder_id="local_statepool",
        )
        self.emit(response)
        return response

    def record_blob_fetch(self, *, bytes_count: int, cache_hit: bool) -> None:
        self.blob_fetch_metrics["blob_fetch_count"] += 1
        self.blob_fetch_metrics["blob_fetch_bytes"] += int(bytes_count)
        if cache_hit:
            self.blob_fetch_metrics["blob_fetch_hits"] += 1
        self.metrics.blob_fetch_count += 1
        self.metrics.blob_fetch_bytes += int(bytes_count)
        if cache_hit:
            self.metrics.blob_fetch_hits += 1

    def put_ranked_evidence_state(
        self,
        *,
        state_id: str,
        ranked_evidence_bundle: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        return self._put_msgpack_state(
            state_id=state_id,
            kind="RANKED_EVIDENCE_BUNDLE",
            schema="statebus.ranked_evidence_bundle.v1",
            payload=ranked_evidence_bundle,
            metadata=metadata,
        )

    def get_ranked_evidence_state(self, ref: StateRef) -> dict[str, object]:
        return self._get_msgpack_state(ref)

    def put_tool_candidate_state(
        self,
        *,
        state_id: str,
        tool_candidate_set: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        return self._put_msgpack_state(
            state_id=state_id,
            kind="TOOL_CANDIDATE_SET",
            schema="statebus.tool_candidate_set.v1",
            payload=tool_candidate_set,
            metadata=metadata,
        )

    def get_tool_candidate_state(self, ref: StateRef) -> dict[str, object]:
        return self._get_msgpack_state(ref)

    def put_replay_eligibility_state(
        self,
        *,
        state_id: str,
        replay_eligibility_bundle: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        return self._put_msgpack_state(
            state_id=state_id,
            kind="REPLAY_ELIGIBILITY_BUNDLE",
            schema="statebus.replay_eligibility_bundle.v1",
            payload=replay_eligibility_bundle,
            metadata=metadata,
        )

    def get_replay_eligibility_state(self, ref: StateRef) -> dict[str, object]:
        return self._get_msgpack_state(ref)

    def put_executor_decision_state(
        self,
        *,
        state_id: str,
        decision_packet: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        return self._put_msgpack_state(
            state_id=state_id,
            kind="EXECUTOR_DECISION_PACKET",
            schema="statebus.executor_decision_packet.v1",
            payload=decision_packet,
            metadata=metadata,
        )

    def get_executor_decision_state(self, ref: StateRef) -> dict[str, object]:
        return self._get_msgpack_state(ref)

    def put_validation_gate_state(
        self,
        *,
        state_id: str,
        validation_packet: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        return self._put_msgpack_state(
            state_id=state_id,
            kind="VALIDATION_GATE_PACKET",
            schema="statebus.validation_gate_packet.v1",
            payload=validation_packet,
            metadata=metadata,
        )

    def get_validation_gate_state(self, ref: StateRef) -> dict[str, object]:
        return self._get_msgpack_state(ref)

    def _put_msgpack_state(
        self,
        *,
        state_id: str,
        kind: str,
        schema: str,
        payload: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        ref = self.statepool.put_replay_restorable_bytes(
            state_id=state_id,
            kind=kind,
            payload=msgpack.packb(payload, use_bin_type=True),
            metadata={
                "encoding": "msgpack",
                "schema": schema,
                **attach_channel_metadata(None, state_kind=kind),
                **dict(metadata or {}),
            },
        )
        self.register_state(ref)
        return ref

    def _get_msgpack_state(self, ref: StateRef) -> dict[str, object]:
        payload = self.statepool.get_bytes(ref)
        return dict(msgpack.unpackb(payload, raw=False, strict_map_key=False))

    def search_memory(
        self,
        *,
        task_theme: str,
        query_text: str,
        top_k: int = 3,
        tags: list[str] | None = None,
        tags_any: list[str] | None = None,
        tags_all: list[str] | None = None,
        min_confidence: float = 0.0,
        encoder_id: str | None = None,
        required_metadata: dict[str, object] | None = None,
        session_id: str = "",
    ) -> list[MemoryHit]:
        from protocol.messages import MemoryQuery

        cache_key = (
            task_theme,
            query_text,
            top_k,
            tuple(tags or []),
            tuple(tags_any or []),
            tuple(tags_all or []),
            min_confidence,
            encoder_id,
            tuple(sorted((required_metadata or {}).items())),
            session_id,
        )
        if cache_key in self.memory_search_cache:
            return list(self.memory_search_cache[cache_key])
        query = MemoryQuery(
            task_theme=task_theme,
            query_text=query_text,
            top_k=top_k,
            tags=list(tags or []),
            tags_any=list(tags_any or []),
            tags_all=list(tags_all or []),
            min_confidence=min_confidence,
            encoder_id=encoder_id,
            required_metadata=dict(required_metadata or {}),
            session_id=session_id,
        )
        self.metrics.memory_query_count += 1
        self.emit(query)
        hits = self.memory_store.search(query)
        self.memory_search_cache[cache_key] = list(hits)
        if hits:
            self.metrics.memory_hits += len(hits)
            self.metrics.memory_hit_task_count += 1
            self.memory_hits.extend(hits)
        return hits

    def replay_candidates(
        self,
        *,
        task_theme: str,
        encoder_id: str | None = None,
        required_metadata: dict[str, object] | None = None,
    ) -> list[MemoryHit]:
        cache_key = (
            task_theme,
            encoder_id,
            tuple(sorted((required_metadata or {}).items())),
        )
        if cache_key in self.replay_candidate_cache:
            return list(self.replay_candidate_cache[cache_key])
        self.metrics.replay_probe_count += 1
        hits = self.memory_store.replay_candidates(
            task_theme=task_theme,
            encoder_id=encoder_id,
            required_metadata=required_metadata,
        )
        self.replay_candidate_cache[cache_key] = list(hits)
        if hits:
            self.metrics.memory_hits += len(hits)
            self.metrics.replay_probe_hits += len(hits)
            self.metrics.replay_probe_hit_task_count += 1
            self.memory_hits.extend(hits)
        return hits

    def commit_memory(self, commit: MemoryCommit) -> None:
        self.emit(commit)
        self.memory_store.commit_memory(commit)
        tier = _normalize_runtime_memory_tier(
            commit.tier
            or commit.memory_purpose
            or commit.memory_layer
            or str(commit.metadata.get("memory_purpose", ""))
            or str(commit.metadata.get("memory_layer", ""))
        )
        if tier in self.memory_tiers:
            self.memory_tiers[tier].append(commit.memory_id)

    def record_llm_result(
        self,
        result: LLMResult,
        *,
        purpose: str | None = None,
    ) -> None:
        self.metrics.llm_request_count += 1
        self.metrics.llm_prompt_tokens += result.usage.prompt_tokens
        self.metrics.llm_completion_tokens += result.usage.completion_tokens
        self.metrics.llm_total_tokens += result.usage.total_tokens
        normalized_purpose = (purpose or "").strip().lower()
        if normalized_purpose:
            self.llm_raw_outputs[normalized_purpose] = result.text
        if normalized_purpose == "planner":
            self.metrics.planner_llm_request_count += 1
            self.metrics.planner_prompt_tokens += result.usage.prompt_tokens
            self.metrics.planner_completion_tokens += result.usage.completion_tokens
            self.metrics.planner_total_tokens += result.usage.total_tokens
            self.planner_last_output = result.text
        elif normalized_purpose == "summarizer":
            self.metrics.summarizer_llm_request_count += 1
            self.metrics.summarizer_prompt_tokens += result.usage.prompt_tokens
            self.metrics.summarizer_completion_tokens += result.usage.completion_tokens
            self.metrics.summarizer_total_tokens += result.usage.total_tokens
        if normalized_purpose:
            try:
                normalized_role = normalize_comparator_role_name(normalized_purpose)
            except ValueError:
                normalized_role = ""
        else:
            normalized_role = ""
        if normalized_role and normalized_role in self.role_contracts:
            self.metrics.record_role_llm_usage(
                role=normalized_role,
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
                total_tokens=result.usage.total_tokens,
            )

    def record_phase_duration(self, phase: str, elapsed_ms: float) -> None:
        normalized_phase = phase.strip().lower()
        if normalized_phase == "planner":
            self.metrics.planner_ms += elapsed_ms
            self.metrics.record_role_latency(role="planner", elapsed_ms=elapsed_ms)
            return
        if normalized_phase == "retrieve":
            self.metrics.retrieve_ms += elapsed_ms
            self.metrics.record_role_latency(role="retriever", elapsed_ms=elapsed_ms)
            return
        if normalized_phase == "execute":
            self.metrics.execute_ms += elapsed_ms
            self.metrics.record_role_latency(role="executor", elapsed_ms=elapsed_ms)
            return
        if normalized_phase == "summarize":
            self.metrics.summarize_ms += elapsed_ms
            self.metrics.record_role_latency(role="summarizer", elapsed_ms=elapsed_ms)
            return
        raise ValueError(f"unsupported phase timing bucket: {phase}")

    def set_role_context_slice(self, slice_view: LLMContextSlice) -> None:
        self.role_context_slices[slice_view.role] = slice_view

    def add_contract_error(self, detail: str) -> None:
        normalized = str(detail).strip()
        if normalized:
            self.contract_errors.append(normalized)

    def record_role_trace(
        self,
        *,
        role: str,
        step_id: str,
        phase: str,
        input_state_refs: list[StateRef],
        output_state_refs: list[StateRef],
        carrier: str,
        slice_kind: str = "",
        projection_class: str = "",
        included_fields: tuple[str, ...] = (),
        omitted_fields: tuple[str, ...] = (),
        helper_visibility: str = "",
        semantic_trace: dict[str, Any] | None = None,
    ) -> None:
        self.role_trace.append(
            {
                "role": role,
                "step_id": step_id,
                "phase": phase,
                "carrier": carrier,
                "input_state_ids": [ref.state_id for ref in input_state_refs],
                "output_state_ids": [ref.state_id for ref in output_state_refs],
                "slice_kind": slice_kind,
                "projection_class": projection_class,
                "included_fields": list(included_fields),
                "omitted_fields": list(omitted_fields),
                "helper_visibility": helper_visibility,
                "semantic_trace": dict(semantic_trace or {}),
            }
        )

    def note_reuse(self, hit: MemoryHit, *, reuse_mode: str) -> None:
        prior_mode = self.reuse_mode
        hit.reused_as_plan_patch = False
        hit.skipped_step_ids = []
        self.reuse_hit = hit
        self.reuse_mode = reuse_mode
        self.pruned_step_ids = []
        if (
            prior_mode == "assist"
            and reuse_mode in {"skip_execute", "skip_retrieve_execute"}
            and self.metrics.memory_assist_task_count > 0
        ):
            self.metrics.memory_assist_task_count -= 1
        if reuse_mode == "assist":
            self.metrics.memory_assist_task_count += 1
        if reuse_mode in {"assist", "skip_execute", "skip_retrieve_execute"}:
            self.metrics.validated_reuse_task_count += 1

    def note_rejected_memory(self, hit: MemoryHit) -> None:
        if self.rejected_memory_hit is not None:
            return
        self.rejected_memory_hit = hit
        self.metrics.memory_rejected_task_count += 1

    def preferred_corpus_doc_ids(self, step: PlanStep | None = None) -> list[str]:
        if self.task_corpus_doc_ids:
            return list(self.task_corpus_doc_ids)
        if step is None:
            return []
        return _normalize_string_list(step.params.get("corpus_doc_ids", []))

    def corpus_path(self) -> str:
        return self.task_corpus_path.strip()

    def reuse_signature(self, step: PlanStep | None = None) -> str:
        tags: list[str] = []
        if step is not None:
            fallback = step.params.get("tags", [])
            tags = _normalize_string_list(step.params.get("reuse_tags", fallback))
        return build_reuse_signature(self.task_theme, tags)

    def runtime_reuse_contract(self, step: PlanStep | None = None) -> str:
        if self.runtime_profile.runtime_reuse_contract:
            return self.runtime_profile.runtime_reuse_contract
        if step is None:
            return resolve_runtime_reuse_contract({})
        return resolve_runtime_reuse_contract(step.params)

    @property
    def runtime_gates(self) -> dict[str, bool]:
        return runtime_reuse_contract_gates(self.runtime_reuse_contract())

    def transfer_strategy(self) -> str:
        return self.runtime_profile.effective_transfer_strategy(self.mode)

    def handoff_profile(self) -> str:
        return self.runtime_profile.resolved_handoff_profile


class Orchestrator:
    """Host-side orchestrator for planner-driven benchmark tasks."""

    def __init__(
        self,
        agents: dict[str, object],
        *,
        state_contract_registry: StateContractRegistry | None = None,
    ) -> None:
        self.agents = agents
        self.state_contract_registry = state_contract_registry or default_state_contract_registry()

    @classmethod
    def create_context(
        cls,
        *,
        mode: str,
        task_id: str,
        task_group: str,
        task_theme: str,
        state_root: str | Path,
        memory_db_path: str | Path,
        trace_id: str | None = None,
        embedder: EmbeddingProvider | None = None,
        session: RunSession | None = None,
        statepool_config: StatePoolConfig | None = None,
        task_corpus_doc_ids: list[str] | tuple[str, ...] | None = None,
        task_corpus_path: str = "",
        summary_contract: str = "actions_plus_evidence",
        runtime_profile: RuntimeTaskProfile | dict[str, Any] | None = None,
    ) -> RunContext:
        active_session = session or RunSession(mode=mode)
        statepool = StatePool(
            state_root,
            config=statepool_config or StatePoolConfig.from_env(),
            owned_shared_handles=active_session.owned_shared_handles,
        )
        memory_store = MemoryStore(memory_db_path, embedder=embedder)
        memory_store.init_schema()
        return RunContext(
            mode=mode,
            trace_id=trace_id or f"{task_id}-{uuid4().hex[:8]}",
            task_id=task_id,
            task_group=task_group,
            task_theme=task_theme,
            summary_contract=str(summary_contract).strip() or "actions_plus_evidence",
            session=active_session,
            statepool=statepool,
            memory_store=memory_store,
            task_corpus_doc_ids=tuple(
                str(doc_id).strip() for doc_id in (task_corpus_doc_ids or []) if str(doc_id).strip()
            ),
            task_corpus_path=str(task_corpus_path).strip(),
            runtime_profile=(
                runtime_profile
                if isinstance(runtime_profile, RuntimeTaskProfile)
                else RuntimeTaskProfile.from_mapping(runtime_profile)
            ),
            execution_dag=active_session.execution_dag,
        )

    async def run_task(self, task: object, ctx: RunContext) -> dict[str, StepResult]:
        started = time.perf_counter()
        self._ensure_prior_dependency_for_fresh_execution(task=task, ctx=ctx)
        plan = await self.compile_task_plan(task, ctx)
        results = await self._execute_plan(plan, ctx)
        ctx.metrics.task_ms = (time.perf_counter() - started) * 1000.0
        self.seal_task_commit(ctx)
        return results

    async def run_plan(self, plan: Plan, ctx: RunContext) -> dict[str, StepResult]:
        started = time.perf_counter()
        self._ensure_prior_dependency_for_fresh_execution(task=getattr(ctx, "task", None), ctx=ctx)
        self.prepare_plan(plan, ctx)
        results = await self._execute_plan(plan, ctx)
        ctx.metrics.task_ms = (time.perf_counter() - started) * 1000.0
        self.seal_task_commit(ctx)
        return results

    async def compile_task_plan(self, task: object, ctx: RunContext) -> Plan:
        from tasks.sample_tasks import normalize_plan_source

        ctx.task = task
        if ctx.runtime_profile.is_empty and hasattr(task, "runtime_profile"):
            maybe_profile = getattr(task, "runtime_profile")
            if isinstance(maybe_profile, RuntimeTaskProfile):
                ctx.runtime_profile = maybe_profile
        ctx.planner_source = normalize_plan_source(getattr(task, "plan_source", "yaml"))
        self._ensure_handshake(ctx)
        plan_started = time.perf_counter()
        plan = await self._plan_task(task, ctx)
        ctx.record_phase_duration("planner", (time.perf_counter() - plan_started) * 1000.0)
        self.prepare_plan(plan, ctx)
        return plan

    def prepare_plan(self, plan: Plan, ctx: RunContext) -> None:
        self._ensure_handshake(ctx)
        ctx.plan = plan
        SchemaInterceptor.validate_plan(plan, ctx.session.capability_table)
        ctx.metrics.planned_step_count = len(plan.steps)
        ctx.planner_step_count = len(plan.steps)
        ctx.planner_contract_valid = True
        ctx.planner_contract_valid_final = True
        ctx.plan_fairness_gate = evaluate_plan_fairness_gate(plan)
        for step in plan.steps:
            ctx.set_step_role(step.step_id, self._semantic_role_for_step(step))
        ctx.set_role_context_slice(
            build_context_slice(
                role="planner",
                task_id=plan.task_id,
                mode=ctx.mode,
                carrier=ctx.transfer_strategy(),
                visible_text=plan.goal,
                upstream_roles=(),
                slice_kind="planner_contract_view",
                projection_class="planner_statebus_brief",
                included_fields=("goal", "query", "role_graph"),
                omitted_fields=("typed_state_payloads", "executor_artifact"),
                text_budget_class="brief",
                typed_state_budget_class="none",
                role_visible_contract="planner_contract_v1",
                helper_visibility="declared_only",
                model_visibility="same_model_required",
                tool_visibility="catalog_visible",
                corpus_visibility="task_scope_only",
                metadata={
                    "step_count": len(plan.steps),
                    "summary_contract": ctx.summary_contract,
                },
            )
        )
        ctx.record_role_trace(
            role="planner",
            step_id="planner",
            phase="plan",
            input_state_refs=[],
            output_state_refs=[],
            carrier=ctx.transfer_strategy(),
            slice_kind="planner_contract_view",
            projection_class="planner_statebus_brief",
            included_fields=("goal", "query", "role_graph"),
            omitted_fields=("typed_state_payloads", "executor_artifact"),
            helper_visibility="declared_only",
        )
        if getattr(ctx, "_statebus_plan_emitted", False):
            return
        ctx.emit(plan)
        setattr(ctx, "_statebus_plan_emitted", True)

    async def _execute_plan(self, plan: Plan, ctx: RunContext) -> dict[str, StepResult]:
        self.prepare_plan(plan, ctx)
        retrieve_gate_started = time.perf_counter()
        precomputed_skip = self.resolve_skip_retrieve_execute(plan, ctx)
        ctx.record_phase_duration(
            "retrieve",
            (time.perf_counter() - retrieve_gate_started) * 1000.0,
        )
        for step in plan.steps:
            self.ensure_step_ready(step, ctx)
            if step.step_id in ctx.results:
                continue
            step_role = self._semantic_role_for_step(step)
            if step_role == "retrieve" and precomputed_skip is not None:
                for synthetic_step in precomputed_skip:
                    synthetic_plan_step = self._step_for_emit(
                        plan,
                        self._semantic_role_for_result(ctx, synthetic_step),
                    )
                    self.register_step_result(
                        step=synthetic_plan_step,
                        result=synthetic_step,
                        ctx=ctx,
                        emit_step=True,
                    )
                continue
            if step_role == "execute":
                execute_phase_ms = 0.0
                execute_gate_started = time.perf_counter()
                maybe_skip = self.resolve_skip_execute(plan, ctx)
                execute_phase_ms += (time.perf_counter() - execute_gate_started) * 1000.0
                if maybe_skip is not None:
                    ctx.record_phase_duration("execute", execute_phase_ms)
                    self.register_step_result(
                        step=step,
                        result=maybe_skip,
                        ctx=ctx,
                        emit_step=True,
                    )
                    continue
            result, step_elapsed_ms = await self.invoke_plan_step(plan, step, ctx)
            if step_role == "execute":
                step_elapsed_ms += execute_phase_ms
            phase_name = self._phase_name_for_step(step)
            if phase_name is not None:
                ctx.record_phase_duration(phase_name, step_elapsed_ms)
            self.register_step_result(
                step=step,
                result=result,
                ctx=ctx,
                emit_step=False,
            )
            if not result.success:
                error = Error(
                    code="step_failed",
                    detail=result.error or "step failed",
                    related_id=step.step_id,
                )
                ctx.emit(error)
                break
        return ctx.results

    def ensure_step_ready(self, step: PlanStep, ctx: RunContext) -> None:
        if step.owner_agent not in self.agents:
            error = Error(
                code="unknown_agent",
                detail=f"missing agent {step.owner_agent}",
                related_id=step.step_id,
            )
            ctx.emit(error)
            raise KeyError(error.detail)
        self._ensure_dependencies(step, ctx)

    async def invoke_plan_step(
        self,
        plan: Plan,
        step: PlanStep,
        ctx: RunContext,
    ) -> tuple[StepResult, float]:
        self.prepare_step_input_refs(plan, step, ctx)
        ctx.emit(step)
        agent = self.agents[step.owner_agent]
        step_started = time.perf_counter()
        result = await agent.execute_step(step, ctx)
        return result, (time.perf_counter() - step_started) * 1000.0

    def register_step_result(
        self,
        *,
        step: PlanStep,
        result: StepResult,
        ctx: RunContext,
        emit_step: bool = False,
    ) -> None:
        if emit_step:
            ctx.emit(step)
        SchemaInterceptor.validate_result(
            step=step,
            result=result,
            capability_table=ctx.session.capability_table,
            state_contract_registry=self.state_contract_registry,
            statepool=ctx.statepool,
        )
        self.register_result(result, ctx)
        self._record_role_context(step=step, result=result, ctx=ctx)
        self.register_step_tree(step=step, result=result, ctx=ctx)

    @staticmethod
    def register_step_tree(
        *,
        step: PlanStep,
        result: StepResult,
        ctx: RunContext,
    ) -> None:
        input_refs = ctx.step_input_refs(step.step_id)
        input_blobs = {
            ref.kind: ref.canonical_hash or ref.state_id
            for ref in input_refs
            if ref.canonical_hash or ref.state_id
        }
        output_blobs = {
            ref.kind: ref.canonical_hash or ref.state_id
            for ref in result.output_state_refs
            if ref.canonical_hash or ref.state_id
        }
        channel_snapshots = {
            name: snapshot.snapshot_hash
            for name, snapshot in ctx.channel_snapshots.items()
            if snapshot.snapshot_hash
        }
        invariants = {
            "step_success": bool(result.success),
            "output_refs_registered": all(ref.state_id in ctx.state_refs for ref in result.output_state_refs),
            "channel_route_snapshot_present": bool(
                Orchestrator._semantic_role_for_step(step) != "execute"
                or ctx.transfer_strategy() != "state_ref"
                or ctx.get_channel_snapshot("route") is not None
            ),
        }
        ctx.trajectory_steps.append(
            StepTree(
                step_id=step.step_id,
                agent_id=step.owner_agent,
                action=step.action,
                input_blobs=input_blobs,
                output_blobs=output_blobs,
                channel_snapshots=channel_snapshots,
                invariants=invariants,
            )
        )
        ctx.metrics.trajectory_step_count = len(ctx.trajectory_steps)
        ctx.metrics.invariant_check_count += len(invariants)
        violations = sum(1 for ok in invariants.values() if not ok)
        ctx.metrics.true_invariant_violation_count += violations
        ctx.metrics.invariant_violation_count = ctx.metrics.true_invariant_violation_count

    @staticmethod
    def seal_task_commit(ctx: RunContext) -> TaskCommit:
        if ctx.sealed_task_commit_hash:
            existing = ctx.execution_dag.task_commits[ctx.sealed_task_commit_hash]
            ctx.metrics.dag_integrity_check_count += 1
            ctx.metrics.dag_integrity_violation_count += int(not ctx.execution_dag.verify_integrity())
            return existing
        channel_hashes = {
            name: snapshot.snapshot_hash
            for name, snapshot in sorted(ctx.channel_snapshots.items())
            if snapshot.snapshot_hash
        }
        invariant_total = sum(len(step.invariants) for step in ctx.trajectory_steps)
        invariant_violations = sum(
            1
            for step in ctx.trajectory_steps
            for ok in step.invariants.values()
            if not ok
        )
        commit = TaskCommit(
            task_id=ctx.task_id,
            task_group=ctx.task_group,
            task_theme=ctx.task_theme,
            step_trees=list(ctx.trajectory_steps),
            mode=ctx.mode,
            created_at=time.time(),
            task_metrics=ctx.metrics.to_dict(),
            channel_snapshot_hash=_stable_json_hash(channel_hashes),
            invariant_summary={
                "checks": invariant_total,
                "violations": invariant_violations,
            },
        )
        commit.seal()
        previous_hashes = list(ctx.execution_dag.task_order)
        ctx.execution_dag.add_commit(commit)
        ctx.sealed_task_commit_hash = commit.commit_hash
        ctx.metrics.trajectory_commit_count = len(ctx.execution_dag.task_commits)
        ctx.metrics.trajectory_diff_count = sum(
            1 for prior in previous_hashes if prior != commit.commit_hash
        )
        ctx.metrics.dag_integrity_check_count += 1
        ctx.metrics.dag_integrity_violation_count += int(not ctx.execution_dag.verify_integrity())
        ctx.commit_memory(
            MemoryCommit(
                memory_id=f"commit-{ctx.task_id}-{commit.commit_hash[:12]}",
                source_agent_id="runtime",
                source_task_id=ctx.task_id,
                task_theme=ctx.task_theme,
                summary=f"TaskCommit {commit.commit_hash} for {ctx.task_id}",
                tags=[ctx.task_group, "task_commit"],
                evidence_state_ids=sorted(ctx.state_refs),
                reusable_steps=[],
                confidence=1.0,
                embedding_text=(
                    f"task_commit {ctx.task_theme} {ctx.task_id} "
                    f"{commit.commit_hash} {commit.channel_snapshot_hash}"
                ),
                encoder_id=ctx.memory_store.embedder.encoder_id,
                metadata={
                    "memory_purpose": "task_commit",
                    "memory_layer": "task_commit",
                    "tier": "task_commits",
                    "trajectory_commit_hash": commit.commit_hash,
                    "channel_snapshot_hash": commit.channel_snapshot_hash,
                    "dag_integrity_ok": ctx.execution_dag.verify_integrity(),
                    "case_id": str(getattr(ctx.task, "case_id", "")).strip(),
                    "chosen_route": Orchestrator._payload_string(
                        ctx.result_for_role("execute"),
                        "route",
                    ),
                    "rejected_routes": Orchestrator._rejected_routes_for_task(ctx),
                    "safe_first_action": Orchestrator._safe_first_action(ctx),
                    "first_validation_check": Orchestrator._first_validation_check(ctx),
                },
                evidence_state_refs=list(ctx.state_refs.values()),
                memory_purpose="task_commit",
                memory_layer="task_commit",
                source_session_id=ctx.trace_id,
                tier="task_commits",
                commit_ref=commit.commit_hash,
            )
        )
        return commit

    def resolve_skip_retrieve_execute(
        self,
        plan: Plan,
        ctx: RunContext,
    ) -> list[StepResult] | None:
        if not ctx.runtime_gates["allow_exact_replay"]:
            return None
        retrieve_step = self._find_step(plan, "retrieve")
        execute_step = self._find_step(plan, "execute")
        hits = ctx.replay_candidates(
            task_theme=ctx.task_theme,
            encoder_id=ctx.memory_store.embedder.encoder_id,
            required_metadata={"memory_purpose": "replay"},
        )
        current_query = str(retrieve_step.params.get("query", ""))
        for hit in hits:
            if not self._prior_dependency_satisfied(task=ctx.task, ctx=ctx, hit=hit):
                continue
            if not self._matches_skip_retrieve_execute(
                hit=hit,
                task_theme=ctx.task_theme,
                current_query=current_query,
                ctx=ctx,
            ):
                continue
            ctx.note_reuse(hit, reuse_mode="skip_retrieve_execute")
            try:
                retrieve_result, execute_result = self._build_skip_retrieve_execute_results(
                    hit=hit,
                    retrieve_step=retrieve_step,
                    execute_step=execute_step,
                    ctx=ctx,
                )
            except ValueError:
                continue
            self._prepare_step_input_refs(
                plan,
                execute_step,
                ctx,
                result_overrides={"retrieve": retrieve_result},
                persist=True,
            )
            try:
                summarize_step = self._find_step(plan, "summarize")
            except KeyError:
                summarize_step = None
            if summarize_step is not None:
                self._prepare_step_input_refs(
                    plan,
                    summarize_step,
                    ctx,
                    result_overrides={
                        "retrieve": retrieve_result,
                        "execute": execute_result,
                    },
                    persist=True,
                )
            hit.skipped_step_ids = ["retrieve", "execute"]
            ctx.pruned_step_ids = ["retrieve", "execute"]
            ctx.metrics.skipped_step_count += 2
            return [retrieve_result, execute_result]
        return None

    def resolve_skip_execute(
        self,
        plan: Plan,
        ctx: RunContext,
    ) -> StepResult | None:
        if not ctx.runtime_gates["allow_execute_prune"]:
            return None
        retrieve_step = self._find_step(plan, "retrieve")
        execute_step = self._find_step(plan, "execute")
        retrieve_result = ctx.result_for_role("retrieve")
        if retrieve_result is None:
            return None
        hits = ctx.replay_candidates(
            task_theme=ctx.task_theme,
            encoder_id=ctx.memory_store.embedder.encoder_id,
            required_metadata={"memory_purpose": "replay"},
        )
        current_query = str(retrieve_step.params.get("query", ""))
        for hit in hits:
            if not self._prior_dependency_satisfied(task=ctx.task, ctx=ctx, hit=hit):
                continue
            if not self._matches_skip_execute(
                hit=hit,
                retrieve_result=retrieve_result,
                current_query=current_query,
                ctx=ctx,
            ):
                continue
            ctx.note_reuse(hit, reuse_mode="skip_execute")
            try:
                result = self._build_skip_execute_result(hit=hit, execute_step=execute_step, ctx=ctx)
            except ValueError:
                continue
            self._prepare_step_input_refs(
                plan,
                execute_step,
                ctx,
                result_overrides={"retrieve": retrieve_result},
                persist=True,
            )
            try:
                summarize_step = self._find_step(plan, "summarize")
            except KeyError:
                summarize_step = None
            if summarize_step is not None:
                self._prepare_step_input_refs(
                    plan,
                    summarize_step,
                    ctx,
                    result_overrides={"execute": result},
                    persist=True,
                )
            hit.skipped_step_ids = ["execute"]
            ctx.pruned_step_ids = ["execute"]
            ctx.metrics.skipped_step_count += 1
            return result
        return None

    async def _plan_task(self, task: object, ctx: RunContext) -> Plan:
        from tasks.sample_tasks import build_plan, normalize_plan_source

        plan_source = normalize_plan_source(getattr(task, "plan_source", "yaml"))
        if plan_source == "yaml":
            return build_plan(task)
        # plan_source=llm compiles the plan up front; the resulting DAG still runs
        # through the normal retriever/executor/summarizer step path.
        # This is the required planner-open path for superiority comparators.
        planner = self.agents.get("planner")
        if planner is None or not hasattr(planner, "plan_task"):
            raise KeyError("planner agent is required for plan_source=llm pre-plan compilation")
        return await planner.plan_task(task, ctx)

    def _ensure_handshake(self, ctx: RunContext) -> None:
        if ctx.session.handshake_complete:
            return
        seen: set[str] = set()
        for step_agent in self.agents.values():
            agent_id = getattr(step_agent, "agent_id")
            if agent_id in seen:
                continue
            seen.add(agent_id)
            hello = Hello(agent_id=agent_id, mode=ctx.mode)
            capability = getattr(step_agent, "capability")
            ack = Ack(related_id=agent_id, detail="capability registered")
            ctx.session.record_message(hello, phase="setup")
            ctx.session.record_message(capability, phase="setup")
            ctx.session.capability_table.register(capability)
            ctx.session.record_message(ack, phase="setup")
        ctx.session.handshake_complete = True

    @staticmethod
    def _ensure_dependencies(step: PlanStep, ctx: RunContext) -> None:
        for dep_id in step.depends_on:
            if dep_id not in ctx.results:
                raise ValueError(f"step {step.step_id} missing dependency {dep_id}")
            if not ctx.results[dep_id].success:
                raise ValueError(f"step {step.step_id} dependency {dep_id} failed")

    @staticmethod
    def _register_step_outputs(result: StepResult, ctx: RunContext) -> None:
        for ref in result.output_state_refs:
            ctx.register_state(ref)

    def register_result(self, result: StepResult, ctx: RunContext) -> None:
        self._register_step_outputs(result, ctx)
        commits: list[MemoryCommit] = []
        maybe_commit = result.memory_commit
        if isinstance(maybe_commit, MemoryCommit):
            commits.append(maybe_commit)
        commits.extend(result.memory_commits)
        SchemaInterceptor.validate_result_memory_commits(result)
        for commit in commits:
            ctx.commit_memory(commit)
            ctx.emit(Ack(related_id=commit.memory_id, detail="memory committed"))
        ctx.emit(result)
        ctx.results[result.step_id] = result

    _register_result = register_result

    @staticmethod
    def _find_step(plan: Plan, semantic_role_or_step_id: str) -> PlanStep:
        target = str(semantic_role_or_step_id).strip().lower()
        for step in plan.steps:
            if Orchestrator._semantic_role_for_step(step) == target:
                return step
        for step in plan.steps:
            if step.step_id == semantic_role_or_step_id:
                return step
        raise KeyError(f"missing step in plan: {semantic_role_or_step_id}")

    @staticmethod
    def _step_for_emit(plan: Plan, semantic_role_or_step_id: str) -> PlanStep:
        return Orchestrator._find_step(plan, semantic_role_or_step_id)

    @staticmethod
    def phase_name_for_step(step: PlanStep | str) -> str | None:
        role = (
            Orchestrator._semantic_role_for_step(step)
            if isinstance(step, PlanStep)
            else str(step).strip().lower()
        )
        if role == "retrieve":
            return "retrieve"
        if role == "execute":
            return "execute"
        if role == "summarize":
            return "summarize"
        return None

    _phase_name_for_step = phase_name_for_step

    def prepare_step_input_refs(
        self,
        plan: Plan,
        step: PlanStep,
        ctx: RunContext,
        *,
        result_overrides: dict[str, StepResult] | None = None,
        persist: bool = True,
    ) -> list[StateRef]:
        if not step.depends_on:
            if persist:
                ctx.set_step_input_refs(step.step_id, [])
            return []
        contract = self.state_contract_registry.step_input_contract(
            agent_id=step.owner_agent,
            action=step.action,
            variant=self._step_input_contract_variant(step, ctx),
        )
        selected_refs: list[StateRef] = []
        producer_agents_by_state_id: dict[str, str] = {}
        overrides = result_overrides or {}
        for source in contract.sources:
            source_step = self._find_step(plan, source.step_id)
            source_result = overrides.get(source.step_id, ctx.result_for_role(source.step_id))
            if source_result is None:
                raise SchemaValidationError(
                    f"step {step.step_id} missing source result {source.step_id}"
                )
            source_refs = [
                ref for ref in source_result.output_state_refs if ref.kind in source.include_kinds
            ]
            missing_groups = [
                group
                for group in source.required_kind_groups
                if not any(ref.kind in group for ref in source_refs)
            ]
            if missing_groups:
                formatted_groups = ", ".join("/".join(group) for group in missing_groups)
                raise SchemaValidationError(
                    f"step {step.step_id} missing required input kinds from {source.step_id}: "
                    f"{formatted_groups}"
                )
            for ref in source_refs:
                producer_agents_by_state_id[ref.state_id] = source_step.owner_agent
            selected_refs.extend(source_refs)
        SchemaInterceptor.validate_input_state_refs(
            step=step,
            input_state_refs=selected_refs,
            capability_table=ctx.session.capability_table,
            state_contract_registry=self.state_contract_registry,
            statepool=ctx.statepool,
            producer_agents_by_state_id=producer_agents_by_state_id,
        )
        raw_role = self._semantic_role_for_step(step)
        try:
            role = normalize_comparator_role_name(raw_role)
        except ValueError:
            role = raw_role
        contract = ctx.role_contracts.get(role)
        if contract is not None:
            if selected_refs and not contract.consumes_typed_state:
                detail = f"role {role} cannot consume typed state"
                ctx.add_contract_error(detail)
                raise SchemaValidationError(detail)
            if contract.allowed_input_state_kinds:
                disallowed = [
                    ref.kind
                    for ref in selected_refs
                    if ref.kind not in contract.allowed_input_state_kinds
                ]
                if disallowed:
                    detail = (
                        f"role {role} received disallowed input state kinds: "
                        + ", ".join(sorted(dict.fromkeys(disallowed)))
                    )
                    ctx.add_contract_error(detail)
                    raise SchemaValidationError(detail)
        if persist:
            ctx.set_step_input_refs(step.step_id, selected_refs)
        return selected_refs

    _prepare_step_input_refs = prepare_step_input_refs

    @staticmethod
    def _step_input_contract_variant(step: PlanStep, ctx: RunContext) -> str:
        if step.owner_agent == "executor" and step.action == "EXECUTE_PLAYBOOK":
            if ctx.transfer_strategy() == "state_ref":
                return ctx.handoff_profile()
            required_roles = {
                str(role).strip().lower()
                for role in getattr(getattr(ctx, "task", None), "required_plan_semantic_roles", ())
                if str(role).strip()
            }
            if ctx.transfer_strategy() == "text_whole_lane" and "validate" in required_roles:
                return "text_whole_lane_validated"
            if ctx.transfer_strategy() == "state_packet_minimal" and "validate" in required_roles:
                return "state_packet_minimal_validated"
            return ctx.transfer_strategy()
        if step.owner_agent == "summarizer" and step.action == "SUMMARIZE_AND_COMMIT":
            if ctx.transfer_strategy() == "state_ref":
                return ctx.handoff_profile()
            return ctx.transfer_strategy()
        return "default"

    @staticmethod
    def _record_role_context(
        *,
        step: PlanStep,
        result: StepResult,
        ctx: RunContext,
    ) -> None:
        raw_role = Orchestrator._semantic_role_for_step(step)
        try:
            role = normalize_comparator_role_name(raw_role)
        except ValueError:
            role = raw_role
        contract = ctx.role_contracts.get(role)
        if contract is None:
            return
        if contract.allowed_output_state_kinds:
            disallowed = [
                ref.kind
                for ref in result.output_state_refs
                if ref.kind not in contract.allowed_output_state_kinds
            ]
            if disallowed:
                detail = (
                    f"role {role} produced disallowed output state kinds: "
                    + ", ".join(sorted(dict.fromkeys(disallowed)))
                )
                ctx.add_contract_error(detail)
                raise SchemaValidationError(detail)
        input_refs = ctx.step_input_refs(step.step_id)
        slice_view = Orchestrator._build_role_context_slice(
            role=role,
            step=step,
            ctx=ctx,
            input_refs=input_refs,
            result=result,
        )
        ctx.set_role_context_slice(
            slice_view
        )
        ctx.record_role_trace(
            role=role,
            step_id=step.step_id,
            phase=Orchestrator.phase_name_for_step(step) or role,
            input_state_refs=input_refs,
            output_state_refs=result.output_state_refs,
            carrier=ctx.transfer_strategy(),
            slice_kind=slice_view.slice_kind,
            projection_class=slice_view.projection_class,
            included_fields=slice_view.included_fields,
            omitted_fields=slice_view.omitted_fields,
            helper_visibility=slice_view.helper_visibility,
            semantic_trace=dict(result.semantic_trace),
        )

    @staticmethod
    def finalize_fairness_gate(plan: Plan, ctx: RunContext) -> CarrierFairnessGate:
        gate = evaluate_execution_fairness_gate(
            plan=plan,
            role_context_slices=ctx.role_context_slices,
            role_trace=ctx.role_trace,
            contract_errors=ctx.contract_errors,
        )
        ctx.fairness_gate = gate
        return gate

    @staticmethod
    def _build_role_context_slice(
        *,
        role: str,
        step: PlanStep,
        ctx: RunContext,
        input_refs: list[StateRef],
        result: StepResult | None = None,
    ) -> LLMContextSlice:
        contract = ctx.role_contracts[role]
        visibility = contract.visibility_contract
        included_fields: tuple[str, ...]
        omitted_fields: tuple[str, ...]
        visible_text_parts: list[str]
        carrier = ctx.transfer_strategy()
        if role == "retriever":
            included_fields = ("query", "planner_goal", "tags")
            omitted_fields = ("typed_state_payloads", "executor_artifact", "summary_hint")
            visible_text_parts = [
                str(step.params.get("query", "")).strip(),
                str(step.params.get("evidence_text", "")).strip(),
            ]
        elif role == "executor":
            included_fields = ("retrieval_evidence", "route_projection", "tool_projection")
            omitted_fields = ("full_feature_bundle_payload", "full_channel_snapshot_payload", "memory_hidden_hints")
            visible_text_parts = []
        elif role == "summarizer":
            included_fields = ("summary_hint", "retrieval_evidence", "executor_artifact")
            omitted_fields = ("planner_hidden_state", "route_search_space", "full_typed_packet_dump")
            visible_text_parts = [
                str(step.params.get("summary_hint", "")).strip(),
            ]
        else:
            included_fields = ("goal", "query", "role_graph")
            omitted_fields = ("typed_state_payloads", "executor_artifact")
            visible_text_parts = [
                str(getattr(getattr(ctx, "plan", None), "goal", "")).strip(),
            ]
        projection_class = (
            visibility.text_lane_projection_class
            if carrier in {"text", "text_whole_lane", "text_brief", "text_packet_minimal", "text_strict_pure_lane", "natural_handoff_text", "inline_text_handoff"}
            else visibility.protocol_lane_projection_class
        )
        typed_refs = tuple(input_refs) if contract.consumes_typed_state and carrier not in {"text", "text_whole_lane", "text_brief", "text_packet_minimal", "text_strict_pure_lane", "natural_handoff_text", "inline_text_handoff"} else ()
        visible_text = "\n".join(part for part in visible_text_parts if part)
        result_for_role = result if result is not None else ctx.result_for_role(role)
        return build_context_slice(
            role=role,
            task_id=ctx.task_id,
            mode=ctx.mode,
            carrier=carrier,
            visible_text=visible_text,
            visible_state_refs=typed_refs,
            upstream_roles=tuple(
                normalized_role
                for dep in step.depends_on
                for normalized_role in [_maybe_normalize_comparator_role(ctx.semantic_role_for_step(dep) or dep)]
                if normalized_role
            ),
            slice_kind=f"{role}_visible_slice",
            projection_class=projection_class,
            included_fields=included_fields,
            omitted_fields=omitted_fields,
            text_budget_class="brief" if carrier in {"text", "text_whole_lane", "text_brief", "text_packet_minimal", "text_strict_pure_lane", "natural_handoff_text", "inline_text_handoff"} else "bounded_projection",
            typed_state_budget_class="none" if not typed_refs else "bounded_typed_refs_only",
            role_visible_contract=f"{role}_visible_contract_v1",
            helper_visibility=visibility.helper_visibility_policy if visibility is not None else "declared_only",
            model_visibility=visibility.model_visibility if visibility is not None else "same_model_required",
            tool_visibility=visibility.tool_visibility if visibility is not None else "",
            corpus_visibility=visibility.corpus_visibility if visibility is not None else "",
            metadata={
                "step_id": step.step_id,
                "owner_agent": step.owner_agent,
                "action": step.action,
                "actual_llm_model": str(getattr(result_for_role, "payload", {}).get("actual_llm_model", "")) if result_for_role is not None else "",
                "actual_tool_catalog": list(getattr(result_for_role, "payload", {}).get("actual_tool_catalog", [])) if result_for_role is not None else [],
                "actual_tool_candidates": list(getattr(result_for_role, "payload", {}).get("actual_tool_candidates", [])) if result_for_role is not None else [],
                "actual_corpus_scope": list(getattr(result_for_role, "payload", {}).get("actual_corpus_scope", [])) if result_for_role is not None else [],
                "decision_source": str(getattr(result_for_role, "payload", {}).get("decision_source", "")) if result_for_role is not None else "",
                "semantic_selected_route": str(getattr(result_for_role, "payload", {}).get("semantic_selected_route", "")) if result_for_role is not None else "",
                "semantic_selected_tool_name": str(getattr(result_for_role, "payload", {}).get("semantic_selected_tool_name", "")) if result_for_role is not None else "",
            },
        )

    @staticmethod
    def _matches_skip_execute(
        *,
        hit: MemoryHit,
        retrieve_result: StepResult,
        current_query: str,
        ctx: RunContext,
    ) -> bool:
        stored_bundle = _find_state_bundle(
            ctx=ctx,
            refs=hit.evidence_state_refs,
            kind="REPLAY_ELIGIBILITY_BUNDLE",
        )
        fresh_bundle = _find_state_bundle(
            ctx=ctx,
            refs=retrieve_result.output_state_refs,
            kind="REPLAY_ELIGIBILITY_BUNDLE",
        )
        feature_route = hit.route or _bundle_string(
            stored_bundle,
            "route",
            fallback=hit.metadata.get("feature_route", ""),
        )
        retrieved_doc_ids = sorted(
            hit.retrieved_doc_ids
            or _bundle_string_list(
                stored_bundle,
                "retrieved_doc_ids",
                fallback=hit.metadata.get("retrieved_doc_ids", []),
            )
        )
        fresh_route = _bundle_string(
            fresh_bundle,
            "route",
            fallback=retrieve_result.payload.get("feature_route", ""),
        )
        fresh_doc_ids = sorted(
            _bundle_string_list(
                fresh_bundle,
                "retrieved_doc_ids",
                fallback=retrieve_result.payload.get("retrieved_doc_ids", []),
            )
        )
        stored_query = _bundle_string(
            stored_bundle,
            "query",
            fallback=hit.metadata.get("feature_query", ""),
        )
        stored_evidence_sha256 = hit.fresh_evidence_sha256 or _bundle_string(
            stored_bundle,
            "feature_fresh_evidence_sha256",
            fallback=hit.metadata.get(
                "feature_fresh_evidence_sha256",
                hit.metadata.get("feature_evidence_sha256", ""),
            ),
        )
        fresh_evidence_sha256 = _bundle_string(
            fresh_bundle,
            "feature_fresh_evidence_sha256",
            fallback=retrieve_result.payload.get(
                "feature_fresh_evidence_sha256",
                retrieve_result.payload.get("feature_evidence_sha256", ""),
            ),
        )
        stored_route_confidence = hit.route_confidence or _bundle_float(
            stored_bundle,
            "route_confidence",
            fallback=hit.metadata.get("feature_route_confidence"),
            default=0.0,
        )
        fresh_route_confidence = _bundle_float(
            fresh_bundle,
            "route_confidence",
            fallback=retrieve_result.payload.get("feature_route_confidence"),
            default=0.0,
        )
        stored_route_provenance = hit.route_provenance or _bundle_string_list(
            stored_bundle,
            "route_provenance",
            fallback=hit.metadata.get("feature_route_provenance", []),
        )
        fresh_route_provenance = _bundle_string_list(
            fresh_bundle,
            "route_provenance",
            fallback=retrieve_result.payload.get("feature_route_provenance", []),
        )
        stored_channel_snapshot_hash = str(hit.metadata.get("channel_snapshot_hash", "")).strip()
        fresh_channel_snapshot_hash = str(retrieve_result.payload.get("channel_snapshot_hash", "")).strip()
        stored_replay_blob_hash = _ref_hash_for_kind(hit.evidence_state_refs, "REPLAY_ELIGIBILITY_BUNDLE")
        fresh_replay_blob_hash = _ref_hash_for_kind(
            retrieve_result.output_state_refs,
            "REPLAY_ELIGIBILITY_BUNDLE",
        )
        stored_replay_certificate_hash = str(hit.metadata.get("replay_certificate_hash", "")).strip()
        fresh_replay_certificate_hash = str(retrieve_result.payload.get("replay_certificate_hash", "")).strip()
        stored_proof_hash = stored_replay_blob_hash or stored_replay_certificate_hash
        fresh_proof_hash = fresh_replay_blob_hash or fresh_replay_certificate_hash
        reusable_steps = {str(step_id).strip() for step_id in (hit.reusable_steps or []) if str(step_id).strip()}
        if Orchestrator._matches_formal_prior_contract_replay(
            hit=hit,
            task=getattr(ctx, "task", None),
            feature_route=feature_route,
            reusable_steps=reusable_steps,
            route_confidence=stored_route_confidence,
            route_provenance=stored_route_provenance,
            fresh_route=fresh_route,
            fresh_route_confidence=fresh_route_confidence,
            fresh_route_provenance=fresh_route_provenance,
        ):
            return True
        return (
            feature_route
            and feature_route != "generic_triage"
            and feature_route == fresh_route
            and "execute" in reusable_steps
            and _query_is_validated_replay_match(stored_query=stored_query, current_query=current_query)
            and _replay_class_allows(hit.replay_class, required="validated_replay")
            and retrieved_doc_ids == fresh_doc_ids
            and stored_evidence_sha256
            and stored_evidence_sha256 == fresh_evidence_sha256
            and _route_is_replay_eligible(
                route_confidence=stored_route_confidence,
                route_provenance=stored_route_provenance,
                minimum_confidence=0.70,
            )
            and _route_is_replay_eligible(
                route_confidence=fresh_route_confidence,
                route_provenance=fresh_route_provenance,
                minimum_confidence=0.70,
            )
            and _optional_hash_match(stored_channel_snapshot_hash, fresh_channel_snapshot_hash)
            and bool(stored_proof_hash)
            and bool(fresh_proof_hash)
        )

    @staticmethod
    def _matches_formal_prior_contract_replay(
        *,
        hit: MemoryHit,
        task: object | None,
        feature_route: str,
        reusable_steps: set[str],
        route_confidence: float,
        route_provenance: list[str],
        fresh_route: str,
        fresh_route_confidence: float,
        fresh_route_provenance: list[str],
    ) -> bool:
        if task is None:
            return False
        pack_type = str(getattr(getattr(task, "task_set_metadata", None), "pack_type", "")).strip()
        if pack_type not in {"contest_honest_headline_v1", "superiority_memory_v1"}:
            return False
        if (
            str(getattr(task, "thickness_setting", "")).strip() != "S2"
            and str(getattr(task, "complexity_bucket", "")).strip() != "reusable"
        ):
            return False
        match_contract = Orchestrator._prior_contract_replay_match(
            hit=hit,
            task=task,
            feature_route=feature_route,
        )
        required_routes = {
            str(item).strip()
            for item in getattr(task, "required_prior_routes", ())
            if str(item).strip()
        }
        return (
            match_contract
            and bool(fresh_route)
            and fresh_route == feature_route
            and (not required_routes or fresh_route in required_routes)
            and "execute" in reusable_steps
            and _replay_class_allows(hit.replay_class, required="validated_replay")
            and _route_is_replay_eligible(
                route_confidence=route_confidence,
                route_provenance=route_provenance,
                minimum_confidence=0.70,
            )
            and _route_is_replay_eligible(
                route_confidence=fresh_route_confidence,
                route_provenance=fresh_route_provenance,
                minimum_confidence=0.70,
            )
            and any(
                ref.kind == "TOOL_ARTIFACT"
                and bool(ref.metadata.get("channel_replay_compatible", True))
                for ref in hit.evidence_state_refs
            )
        )

    @staticmethod
    def _matches_headline_s2_prior_replay(
        *,
        hit: MemoryHit,
        task: object | None,
        feature_route: str,
        reusable_steps: set[str],
        route_confidence: float,
        route_provenance: list[str],
        fresh_route: str,
        fresh_route_confidence: float,
        fresh_route_provenance: list[str],
    ) -> bool:
        return Orchestrator._matches_formal_prior_contract_replay(
            hit=hit,
            task=task,
            feature_route=feature_route,
            reusable_steps=reusable_steps,
            route_confidence=route_confidence,
            route_provenance=route_provenance,
            fresh_route=fresh_route,
            fresh_route_confidence=fresh_route_confidence,
            fresh_route_provenance=fresh_route_provenance,
        )

    @staticmethod
    def _prior_contract_replay_match(
        *,
        hit: MemoryHit,
        task: object | None,
        feature_route: str,
    ) -> bool:
        if task is None:
            return False
        required_case_ids = {
            str(item).strip()
            for item in getattr(task, "required_prior_case_ids", ())
            if str(item).strip()
        }
        required_routes = {
            str(item).strip()
            for item in getattr(task, "required_prior_routes", ())
            if str(item).strip()
        }
        required_rejections = {
            str(item).strip()
            for item in getattr(task, "required_prior_rejections", ())
            if str(item).strip()
        }
        source_case_id = str(hit.metadata.get("case_id", "")).strip()
        source_rejections = {
            str(item).strip()
            for item in hit.metadata.get("rejected_routes", [])
            if str(item).strip()
        }
        return (
            bool(required_case_ids)
            and source_case_id in required_case_ids
            and bool(required_routes)
            and feature_route in required_routes
            and (not required_rejections or required_rejections.issubset(source_rejections))
        )

    def _matches_skip_retrieve_execute(
        self,
        *,
        hit: MemoryHit,
        task_theme: str,
        current_query: str,
        ctx: RunContext,
    ) -> bool:
        replay_bundle = _find_state_bundle(
            ctx=ctx,
            refs=hit.evidence_state_refs,
            kind="REPLAY_ELIGIBILITY_BUNDLE",
        )
        feature_route = hit.route or _bundle_string(
            replay_bundle,
            "route",
            fallback=hit.metadata.get("feature_route", ""),
        )
        retrieved_doc_ids = sorted(
            hit.retrieved_doc_ids
            or _bundle_string_list(
                replay_bundle,
                "retrieved_doc_ids",
                fallback=hit.metadata.get("retrieved_doc_ids", []),
            )
        )
        stored_query = _normalize_replay_query(
            _bundle_string(
                replay_bundle,
                "query",
                fallback=hit.metadata.get("feature_query", ""),
            )
        )
        normalized_query = _normalize_replay_query(current_query)
        route_confidence = hit.route_confidence or _bundle_float(
            replay_bundle,
            "route_confidence",
            fallback=hit.metadata.get("feature_route_confidence"),
            default=0.0,
        )
        route_provenance = hit.route_provenance or _bundle_string_list(
            replay_bundle,
            "route_provenance",
            fallback=hit.metadata.get("feature_route_provenance", []),
        )
        evidence_sha256 = hit.fresh_evidence_sha256 or _bundle_string(
            replay_bundle,
            "feature_fresh_evidence_sha256",
            fallback=hit.metadata.get(
                "feature_fresh_evidence_sha256",
                hit.metadata.get("feature_evidence_sha256", ""),
            )
        )
        channel_snapshot_hash = str(hit.metadata.get("channel_snapshot_hash", "")).strip()
        replay_blob_hash = _ref_hash_for_kind(hit.evidence_state_refs, "REPLAY_ELIGIBILITY_BUNDLE")
        replay_certificate_hash = str(hit.metadata.get("replay_certificate_hash", "")).strip()
        replay_proof_hash = replay_blob_hash or replay_certificate_hash
        reusable_steps = {str(step_id).strip() for step_id in (hit.reusable_steps or []) if str(step_id).strip()}
        inferred_source_match = (
            bool(normalized_query)
            and stored_query == normalized_query
        )
        return (
            hit.task_theme == task_theme
            and feature_route
            and feature_route != "generic_triage"
            and {"retrieve", "execute"}.issubset(reusable_steps)
            and bool(retrieved_doc_ids)
            and inferred_source_match
            and _replay_class_allows(hit.replay_class, required="exact_replay")
            and bool(evidence_sha256)
            and _route_is_replay_eligible(
                route_confidence=route_confidence,
                route_provenance=route_provenance,
                minimum_confidence=0.80,
            )
            and bool(channel_snapshot_hash or replay_certificate_hash)
            and bool(replay_proof_hash)
        )

    def _build_skip_execute_result(
        self,
        *,
        hit: MemoryHit,
        execute_step: PlanStep,
        ctx: RunContext,
    ) -> StepResult:
        retrieve_result = ctx.results.get("retrieve")
        feature_state_id = ""
        channel_snapshot_state_id = ""
        tool_candidate_state_id = ""
        if retrieve_result is not None:
            feature_state_id = next(
                (
                    ref.state_id
                    for ref in retrieve_result.output_state_refs
                    if ref.kind == "FEATURE_BUNDLE"
                ),
                "",
            )
            channel_snapshot_state_id = next(
                (
                    ref.state_id
                    for ref in retrieve_result.output_state_refs
                    if ref.kind == "CHANNEL_SNAPSHOT"
                    and str(ref.metadata.get("channel_name", ref.channel)).strip() == "route"
                ),
                "",
            )
            tool_candidate_state_id = next(
                (
                    ref.state_id
                    for ref in retrieve_result.output_state_refs
                    if ref.kind == "TOOL_CANDIDATE_SET"
                ),
                "",
            )
        artifact_ref = self._copy_memory_ref(
            ctx=ctx,
            hit=hit,
            source_kind="TOOL_ARTIFACT",
            target_state_id=f"{ctx.task_id}-{execute_step.step_id}-artifact",
            replay_mode="skip_execute",
            replay_step_id="execute",
        )
        replay_bundle = _find_state_bundle(
            ctx=ctx,
            refs=hit.evidence_state_refs,
            kind="REPLAY_ELIGIBILITY_BUNDLE",
        )
        validation_result = ctx.result_for_role("validate")
        validation_payload = validation_result.payload if validation_result is not None else {}
        route = hit.route or _bundle_string(replay_bundle, "route", fallback=hit.metadata.get("feature_route", ""))
        route_source = hit.route_source or _bundle_string(
            replay_bundle,
            "route_source",
            fallback=hit.metadata.get("feature_route_source", ""),
        )
        route_confidence = hit.route_confidence or _bundle_float(
            replay_bundle,
            "route_confidence",
            fallback=hit.metadata.get("feature_route_confidence"),
            default=0.0,
        )
        route_provenance = hit.route_provenance or _bundle_string_list(
            replay_bundle,
            "route_provenance",
            fallback=hit.metadata.get("feature_route_provenance", []),
        )
        hint_doc_ids = [str(doc_id) for doc_id in hit.metadata.get("feature_hint_doc_ids", [])]
        return StepResult(
            step_id=execute_step.step_id,
            success=True,
            output_state_refs=[artifact_ref],
            payload={
                "actions": ctx.get_text_state(artifact_ref).splitlines(),
                "reusable_steps": list(hit.reusable_steps or ["retrieve", "execute"]),
                "tool_name": artifact_ref.metadata.get("tool_name", ""),
                "route": route,
                "route_source": route_source,
                "route_confidence": route_confidence,
                "route_provenance": route_provenance,
                "hint_doc_ids": hint_doc_ids,
                "sandbox_mode": artifact_ref.metadata.get("sandbox_mode", "reused"),
                "matched_signals": [],
                "feature_state_id": feature_state_id,
                "channel_snapshot_state_id": channel_snapshot_state_id,
                "tool_candidate_state_id": tool_candidate_state_id,
                "reused_memory": True,
                "reuse_mode": "skip_execute",
                "validated_action_contract": str(
                    validation_payload.get("validated_action_contract", "")
                ).strip(),
                "validation_gate_applied": validation_result is not None,
                "validation_decision_source": (
                    "validation_text_handoff"
                    if ctx.transfer_strategy() == "text_whole_lane"
                    else "validation_gate"
                    if validation_result is not None
                    else ""
                ),
                "pre_validation_route": str(validation_payload.get("pre_validation_route", "")).strip(),
                "pre_validation_tool_name": str(
                    validation_payload.get("pre_validation_tool_name", "")
                ).strip(),
                "pre_validation_action_contract": str(
                    validation_payload.get("pre_validation_action_contract", "")
                ).strip(),
                "validation_changed_action": bool(
                    validation_payload.get("validation_changed_action", False)
                ),
                "validation_refinement_reason": str(
                    validation_payload.get("validation_refinement_reason", "")
                ).strip(),
                "s2_prior_dependency_required": bool(
                    validation_payload.get("s2_prior_dependency_required", False)
                ),
                "s2_prior_dependency_satisfied": bool(
                    validation_payload.get("s2_prior_dependency_satisfied", False)
                ),
                "s2_prior_dependent_action_change": bool(
                    validation_payload.get("s2_prior_dependent_action_change", False)
                ),
                "s2_without_prior_action_contract": str(
                    validation_payload.get("s2_without_prior_action_contract", "")
                ).strip(),
                "s2_without_prior_tool_name": str(
                    validation_payload.get("s2_without_prior_tool_name", "")
                ).strip(),
                "s2_with_prior_action_contract": str(
                    validation_payload.get("s2_with_prior_action_contract", "")
                ).strip(),
                "s2_with_prior_tool_name": str(
                    validation_payload.get("s2_with_prior_tool_name", "")
                ).strip(),
            },
            skipped=True,
            reused_from_memory_id=hit.memory_id,
        )

    def _build_skip_retrieve_execute_results(
        self,
        *,
        hit: MemoryHit,
        retrieve_step: PlanStep,
        execute_step: PlanStep,
        ctx: RunContext,
    ) -> tuple[StepResult, StepResult]:
        evidence_ref = self._maybe_copy_memory_ref(
            ctx=ctx,
            hit=hit,
            source_kind="DENSE_EVIDENCE",
            target_state_id=f"{ctx.task_id}-{retrieve_step.step_id}-evidence",
            replay_mode="skip_retrieve_execute",
            replay_step_id="retrieve",
        )
        decision_ref = self._maybe_copy_memory_ref(
            ctx=ctx,
            hit=hit,
            source_kind="EXECUTOR_DECISION_PACKET",
            target_state_id=f"{ctx.task_id}-{retrieve_step.step_id}-decision",
            replay_mode="skip_retrieve_execute",
            replay_step_id="retrieve",
        )
        feature_ref = self._maybe_copy_memory_ref(
            ctx=ctx,
            hit=hit,
            source_kind="FEATURE_BUNDLE",
            target_state_id=f"{ctx.task_id}-{retrieve_step.step_id}-features",
            replay_mode="skip_retrieve_execute",
            replay_step_id="retrieve",
        )
        channel_snapshot_ref = self._maybe_copy_memory_ref(
            ctx=ctx,
            hit=hit,
            source_kind="CHANNEL_SNAPSHOT",
            target_state_id=f"{ctx.task_id}-{retrieve_step.step_id}-route-snapshot",
            replay_mode="skip_retrieve_execute",
            replay_step_id="retrieve",
        )
        channel_snapshot_hash = ""
        if channel_snapshot_ref is not None:
            try:
                snapshot = ctx.get_channel_snapshot_state(channel_snapshot_ref)
                ctx.channel_snapshots[snapshot.channel_name] = snapshot
                ctx.channel_store[snapshot.channel_name] = dict(snapshot.values)
                channel_snapshot_hash = snapshot.snapshot_hash
            except Exception:
                channel_snapshot_hash = str(hit.metadata.get("channel_snapshot_hash", "")).strip()
        ranked_evidence_ref = self._maybe_copy_memory_ref(
            ctx=ctx,
            hit=hit,
            source_kind="RANKED_EVIDENCE_BUNDLE",
            target_state_id=f"{ctx.task_id}-{retrieve_step.step_id}-ranked-evidence",
            replay_mode="skip_retrieve_execute",
            replay_step_id="retrieve",
        )
        tool_candidate_ref = self._maybe_copy_memory_ref(
            ctx=ctx,
            hit=hit,
            source_kind="TOOL_CANDIDATE_SET",
            target_state_id=f"{ctx.task_id}-{retrieve_step.step_id}-tool-candidates",
            replay_mode="skip_retrieve_execute",
            replay_step_id="retrieve",
        )
        replay_eligibility_ref = self._maybe_copy_memory_ref(
            ctx=ctx,
            hit=hit,
            source_kind="REPLAY_ELIGIBILITY_BUNDLE",
            target_state_id=f"{ctx.task_id}-{retrieve_step.step_id}-replay-eligibility",
            replay_mode="skip_retrieve_execute",
            replay_step_id="retrieve",
        )
        embedding_ref = self._maybe_copy_memory_ref(
            ctx=ctx,
            hit=hit,
            source_kind="EMBEDDING",
            target_state_id=f"{ctx.task_id}-{retrieve_step.step_id}-embedding",
            replay_mode="skip_retrieve_execute",
            replay_step_id="retrieve",
        )
        artifact_ref = self._copy_memory_ref(
            ctx=ctx,
            hit=hit,
            source_kind="TOOL_ARTIFACT",
            target_state_id=f"{ctx.task_id}-{execute_step.step_id}-artifact",
            replay_mode="skip_retrieve_execute",
            replay_step_id="execute",
        )
        replay_bundle = _find_state_bundle(
            ctx=ctx,
            refs=hit.evidence_state_refs,
            kind="REPLAY_ELIGIBILITY_BUNDLE",
        )
        validation_result = ctx.result_for_role("validate")
        validation_payload = validation_result.payload if validation_result is not None else {}
        route = hit.route or _bundle_string(replay_bundle, "route", fallback=hit.metadata.get("feature_route", ""))
        route_source = hit.route_source or _bundle_string(
            replay_bundle,
            "route_source",
            fallback=hit.metadata.get("feature_route_source", ""),
        )
        route_confidence = hit.route_confidence or _bundle_float(
            replay_bundle,
            "route_confidence",
            fallback=hit.metadata.get("feature_route_confidence"),
            default=0.0,
        )
        route_provenance = hit.route_provenance or _bundle_string_list(
            replay_bundle,
            "route_provenance",
            fallback=hit.metadata.get("feature_route_provenance", []),
        )
        hint_doc_ids = [str(doc_id) for doc_id in hit.metadata.get("feature_hint_doc_ids", [])]
        retrieved_doc_ids = hit.retrieved_doc_ids or _bundle_string_list(
            replay_bundle,
            "retrieved_doc_ids",
            fallback=hit.metadata.get("retrieved_doc_ids", []),
        )
        retrieve_refs: list[StateRef] = []
        if evidence_ref is not None:
            retrieve_refs.append(evidence_ref)
        if decision_ref is not None:
            retrieve_refs.append(decision_ref)
        if feature_ref is not None:
            retrieve_refs.append(feature_ref)
        if channel_snapshot_ref is not None:
            retrieve_refs.append(channel_snapshot_ref)
        if ranked_evidence_ref is not None:
            retrieve_refs.append(ranked_evidence_ref)
        if tool_candidate_ref is not None:
            retrieve_refs.append(tool_candidate_ref)
        if replay_eligibility_ref is not None:
            retrieve_refs.append(replay_eligibility_ref)
        if embedding_ref is not None:
            retrieve_refs.append(embedding_ref)
        if ctx.transfer_strategy() == "state_packet_minimal" and (
            evidence_ref is None or decision_ref is None
        ):
            raise ValueError(
                f"memory {hit.memory_id} missing mode-compatible minimal replay refs"
            )
        retrieve_result = StepResult(
            step_id=retrieve_step.step_id,
            success=True,
            output_state_refs=retrieve_refs,
            payload={
                "query": retrieve_step.params.get("query", ""),
                "inline_handoff_text": str(
                    hit.metadata.get("retrieve_inline_handoff_text", "")
                    or hit.metadata.get("inline_handoff_text", "")
                    or ""
                ).strip(),
                "memory_hits": [hit.memory_id],
                "memory_assist_ids": [hit.memory_id],
                "reused_memory": True,
                "reuse_mode": "skip_retrieve_execute",
                "feature_route": route,
                "feature_route_source": route_source,
                "feature_route_confidence": route_confidence,
                "feature_route_provenance": route_provenance,
                "feature_hint_doc_ids": hint_doc_ids,
                "feature_evidence_sha256": str(hit.metadata.get("feature_evidence_sha256", "")).strip(),
                "feature_fresh_evidence_sha256": str(
                    hit.metadata.get(
                        "feature_fresh_evidence_sha256",
                        hit.metadata.get("feature_evidence_sha256", ""),
                    )
                ).strip(),
                "retrieved_doc_ids": retrieved_doc_ids,
                "corpus_doc_count": len(retrieved_doc_ids),
                "memory_hint_route": route,
                "feature_state_id": (
                    "" if feature_ref is None else feature_ref.state_id
                ),
                "executor_decision_state_id": (
                    "" if decision_ref is None else decision_ref.state_id
                ),
                "channel_snapshot_state_id": (
                    "" if channel_snapshot_ref is None else channel_snapshot_ref.state_id
                ),
                "channel_snapshot_hash": channel_snapshot_hash,
                "ranked_evidence_state_id": (
                    "" if ranked_evidence_ref is None else ranked_evidence_ref.state_id
                ),
                "tool_candidate_state_id": (
                    "" if tool_candidate_ref is None else tool_candidate_ref.state_id
                ),
                "replay_eligibility_state_id": (
                    "" if replay_eligibility_ref is None else replay_eligibility_ref.state_id
                ),
            },
            skipped=True,
            reused_from_memory_id=hit.memory_id,
        )
        execute_result = StepResult(
            step_id=execute_step.step_id,
            success=True,
            output_state_refs=[artifact_ref],
            payload={
                "actions": ctx.get_text_state(artifact_ref).splitlines(),
                "reusable_steps": list(hit.reusable_steps or ["retrieve", "execute"]),
                "tool_name": artifact_ref.metadata.get("tool_name", ""),
                "route": route,
                "route_source": route_source,
                "route_confidence": route_confidence,
                "route_provenance": route_provenance,
                "hint_doc_ids": hint_doc_ids,
                "sandbox_mode": artifact_ref.metadata.get("sandbox_mode", "reused"),
                "matched_signals": [],
                "feature_state_id": "" if feature_ref is None else feature_ref.state_id,
                "executor_decision_state_id": "" if decision_ref is None else decision_ref.state_id,
                "channel_snapshot_state_id": (
                    "" if channel_snapshot_ref is None else channel_snapshot_ref.state_id
                ),
                "tool_candidate_state_id": (
                    "" if tool_candidate_ref is None else tool_candidate_ref.state_id
                ),
                "reused_memory": True,
                "reuse_mode": "skip_retrieve_execute",
                "validated_action_contract": str(
                    validation_payload.get("validated_action_contract", "")
                ).strip(),
                "validation_gate_applied": validation_result is not None,
                "validation_decision_source": (
                    "validation_text_handoff"
                    if ctx.transfer_strategy() == "text_whole_lane"
                    else "validation_gate"
                    if validation_result is not None
                    else ""
                ),
                "pre_validation_route": str(validation_payload.get("pre_validation_route", "")).strip(),
                "pre_validation_tool_name": str(
                    validation_payload.get("pre_validation_tool_name", "")
                ).strip(),
                "pre_validation_action_contract": str(
                    validation_payload.get("pre_validation_action_contract", "")
                ).strip(),
                "validation_changed_action": bool(
                    validation_payload.get("validation_changed_action", False)
                ),
                "validation_refinement_reason": str(
                    validation_payload.get("validation_refinement_reason", "")
                ).strip(),
                "s2_prior_dependency_required": bool(
                    validation_payload.get("s2_prior_dependency_required", False)
                ),
                "s2_prior_dependency_satisfied": bool(
                    validation_payload.get("s2_prior_dependency_satisfied", False)
                ),
                "s2_prior_dependent_action_change": bool(
                    validation_payload.get("s2_prior_dependent_action_change", False)
                ),
                "s2_without_prior_action_contract": str(
                    validation_payload.get("s2_without_prior_action_contract", "")
                ).strip(),
                "s2_without_prior_tool_name": str(
                    validation_payload.get("s2_without_prior_tool_name", "")
                ).strip(),
                "s2_with_prior_action_contract": str(
                    validation_payload.get("s2_with_prior_action_contract", "")
                ).strip(),
                "s2_with_prior_tool_name": str(
                    validation_payload.get("s2_with_prior_tool_name", "")
                ).strip(),
            },
            skipped=True,
            reused_from_memory_id=hit.memory_id,
        )
        return retrieve_result, execute_result

    def _copy_memory_ref(
        self,
        *,
        ctx: RunContext,
        hit: MemoryHit,
        source_kind: str,
        target_state_id: str,
        replay_mode: str,
        replay_step_id: str,
    ) -> StateRef:
        source_ref = self._select_replay_source_ref(
            ctx=ctx,
            hit=hit,
            source_kind=source_kind,
            required=True,
            replay_mode=replay_mode,
            replay_step_id=replay_step_id,
        )
        metadata: dict[str, Any] = dict(source_ref.metadata)
        metadata["reused_from_memory_id"] = hit.memory_id
        metadata["reused_from_source_task_id"] = hit.source_task_id or ""
        metadata["replay_restore_mode"] = replay_mode
        metadata["replay_restore_step_id"] = replay_step_id
        ref = self._restore_replay_ref(
            ctx=ctx,
            source_ref=source_ref,
            target_state_id=target_state_id,
            metadata=metadata,
        )
        ctx.register_state(ref)
        return ref

    def _maybe_copy_memory_ref(
        self,
        *,
        ctx: RunContext,
        hit: MemoryHit,
        source_kind: str,
        target_state_id: str,
        replay_mode: str,
        replay_step_id: str,
    ) -> StateRef | None:
        source_ref = self._select_replay_source_ref(
            ctx=ctx,
            hit=hit,
            source_kind=source_kind,
            required=False,
            replay_mode=replay_mode,
            replay_step_id=replay_step_id,
        )
        if source_ref is None:
            return None
        metadata: dict[str, Any] = dict(source_ref.metadata)
        metadata["reused_from_memory_id"] = hit.memory_id
        metadata["reused_from_source_task_id"] = hit.source_task_id or ""
        metadata["replay_restore_mode"] = replay_mode
        metadata["replay_restore_step_id"] = replay_step_id
        ref = self._restore_replay_ref(
            ctx=ctx,
            source_ref=source_ref,
            target_state_id=target_state_id,
            metadata=metadata,
        )
        ctx.register_state(ref)
        return ref

    @staticmethod
    def _restore_replay_ref(
        *,
        ctx: RunContext,
        source_ref: StateRef,
        target_state_id: str,
        metadata: dict[str, Any],
    ) -> StateRef:
        if source_ref.storage == CAS_BLOB_STORAGE and source_ref.blob_hash:
            ctx.fetch_blob(source_ref, requester_id="replay_restore")
            return ctx.statepool.link_cas_ref(
                state_id=target_state_id,
                source_ref=source_ref,
                metadata=metadata,
            )
        payload = ctx.statepool.get_bytes(source_ref)
        return ctx.statepool.put_replay_restorable_bytes(
            state_id=target_state_id,
            kind=source_ref.kind,
            payload=payload,
            metadata=metadata,
            storage=source_ref.storage,
        )

    def _select_replay_source_ref(
        self,
        *,
        ctx: RunContext,
        hit: MemoryHit,
        source_kind: str,
        required: bool,
        replay_mode: str,
        replay_step_id: str,
    ) -> StateRef | None:
        if not self._replay_restore_kind_allowed(
            ctx=ctx,
            replay_mode=replay_mode,
            replay_step_id=replay_step_id,
            source_kind=source_kind,
        ):
            if required:
                raise ValueError(
                    f"memory {hit.memory_id} restore kind {source_kind} is incompatible with "
                    f"{ctx.mode}/{ctx.transfer_strategy()}/{replay_mode}/{replay_step_id}"
                )
            return None
        candidates = [ref for ref in hit.evidence_state_refs if ref.kind == source_kind]
        if not candidates:
            if required:
                raise ValueError(
                    f"memory {hit.memory_id} missing required state kind {source_kind}"
                )
            return None
        for ref in candidates:
            try:
                self.state_contract_registry.validate_state_ref(
                    ref,
                    require_replay_compatible=True,
                    statepool=ctx.statepool,
                )
                return ref
            except SchemaValidationError:
                continue
        if required:
            raise ValueError(
                f"memory {hit.memory_id} missing replay-compatible state kind {source_kind}"
            )
        return None

    @staticmethod
    def _replay_restore_kind_allowed(
        *,
        ctx: RunContext,
        replay_mode: str,
        replay_step_id: str,
        source_kind: str,
    ) -> bool:
        strategy = ctx.transfer_strategy()
        if strategy == "text_strict_pure_lane":
            return replay_step_id == "execute" and source_kind == "TOOL_ARTIFACT"
        if strategy == "text_whole_lane":
            return replay_step_id == "execute" and source_kind == "TOOL_ARTIFACT"
        if strategy == "state_packet_minimal":
            if replay_step_id == "execute":
                return source_kind == "TOOL_ARTIFACT"
            if replay_step_id == "retrieve" and replay_mode == "skip_retrieve_execute":
                return source_kind in {"DENSE_EVIDENCE", "EXECUTOR_DECISION_PACKET"}
            return False
        return True

    @staticmethod
    def _semantic_role_for_step(step: PlanStep | str) -> str:
        if isinstance(step, str):
            return step.strip().lower()
        return (step.semantic_role or step.step_id).strip().lower()

    @staticmethod
    def _semantic_role_for_result(ctx: RunContext, result: StepResult) -> str:
        return ctx.semantic_role_for_step(result.step_id) or result.step_id

    @staticmethod
    def _payload_string(result: StepResult | None, key: str) -> str:
        if result is None:
            return ""
        return str(result.payload.get(key, "")).strip()

    @staticmethod
    def _safe_first_action(ctx: RunContext) -> str:
        execute_result = ctx.result_for_role("execute")
        if execute_result is None:
            return ""
        actions = execute_result.payload.get("actions", [])
        if isinstance(actions, list):
            for action in actions:
                text = str(action).strip()
                if text:
                    return text
        return ""

    @staticmethod
    def _first_validation_check(ctx: RunContext) -> str:
        summarize_result = ctx.result_for_role("summarize")
        if summarize_result is None:
            return ""
        summary = str(summarize_result.payload.get("summary", "")).strip()
        if not summary:
            return ""
        for line in summary.splitlines():
            lowered = line.lower()
            if "validation" in lowered or "check" in lowered:
                return line.strip()
        return ""

    @staticmethod
    def _rejected_routes_for_task(ctx: RunContext) -> list[str]:
        task = getattr(ctx, "task", None)
        if task is None:
            return []
        primary = str(getattr(task, "primary_expected_route", "")).strip()
        acceptable = [
            str(item).strip()
            for item in getattr(task, "acceptable_routes", ())
            if str(item).strip()
        ]
        if not primary:
            return []
        return [route for route in acceptable if route != primary]

    def _ensure_prior_dependency_for_fresh_execution(
        self,
        *,
        task: object | None,
        ctx: RunContext,
    ) -> None:
        if (
            str(getattr(getattr(task, "task_set_metadata", None), "pack_type", "")).strip()
            == "contest_honest_headline_v1"
            and str(getattr(task, "thickness_setting", "")).strip() == "S2"
        ):
            return
        if self._prior_dependency_satisfied(task=task, ctx=ctx):
            return
        task_id = str(getattr(task, "task_id", ctx.task_id or "task")).strip() or "task"
        required_case_ids = [
            str(item).strip()
            for item in getattr(task, "required_prior_case_ids", ())
            if str(item).strip()
        ]
        required_rejections = [
            str(item).strip()
            for item in getattr(task, "required_prior_rejections", ())
            if str(item).strip()
        ]
        detail_parts = ["prior reusable dependency unsatisfied"]
        if required_case_ids:
            detail_parts.append(f"required_prior_case_ids={required_case_ids}")
        if required_rejections:
            detail_parts.append(f"required_prior_rejections={required_rejections}")
        error = Error(
            code="prior_dependency_unsatisfied",
            detail="; ".join(detail_parts),
            related_id=task_id,
        )
        ctx.emit(error)
        raise ValueError(error.detail)

    def _prior_dependency_satisfied(
        self,
        *,
        task: object | None,
        ctx: RunContext,
        hit: MemoryHit | None = None,
    ) -> bool:
        if task is None:
            return True
        required_case_ids = tuple(
            str(item).strip()
            for item in getattr(task, "required_prior_case_ids", ())
            if str(item).strip()
        )
        required_rejections = {
            str(item).strip()
            for item in getattr(task, "required_prior_rejections", ())
            if str(item).strip()
        }
        if not required_case_ids and not required_rejections:
            return True
        commits = ctx.memory_store.task_commit_candidates(
            task_theme=ctx.task_theme,
            required_metadata={"memory_purpose": "task_commit"},
        )
        by_case_id: dict[str, MemoryHit] = {}
        for candidate in commits:
            case_id = str(candidate.metadata.get("case_id", "")).strip()
            if case_id:
                by_case_id.setdefault(case_id, candidate)
        for case_id in required_case_ids:
            prior = by_case_id.get(case_id)
            if prior is None:
                return False
            rejected_routes = {
                str(item).strip()
                for item in prior.metadata.get("rejected_routes", [])
                if str(item).strip()
            }
            if required_rejections and not required_rejections.issubset(rejected_routes):
                return False
        if hit is not None and required_rejections:
            hit_rejected = {
                str(item).strip()
                for item in hit.metadata.get("rejected_routes", [])
                if str(item).strip()
            }
            if hit_rejected and not required_rejections.issubset(hit_rejected):
                return False
        return True

def _normalize_replay_query(text: str) -> str:
    return " ".join(text.lower().split())


def _normalized_replay_query_terms(text: str) -> set[str]:
    return {
        token.strip(".,:;!?()[]{}").lower()
        for token in text.split()
        if token.strip(".,:;!?()[]{}")
    }


def _query_is_validated_replay_match(*, stored_query: str, current_query: str) -> bool:
    stored_terms = _normalized_replay_query_terms(stored_query)
    current_terms = _normalized_replay_query_terms(current_query)
    if not stored_terms or not current_terms:
        return False
    overlap = stored_terms & current_terms
    coverage = len(overlap) / max(len(stored_terms), len(current_terms))
    return coverage >= 0.85


def _normalize_replay_class(value: object) -> str:
    text = str(value or "").strip().lower()
    alias_map = {
        "": "",
        "validated": "validated_replay",
        "validated_replay": "validated_replay",
        "skip_execute": "validated_replay",
        "exact": "exact_replay",
        "exact_replay": "exact_replay",
        "skip_retrieve_execute": "exact_replay",
    }
    return alias_map.get(text, text)


def _replay_class_allows(value: object, *, required: str) -> bool:
    normalized = _normalize_replay_class(value)
    if not normalized:
        return True
    required_normalized = _normalize_replay_class(required)
    if normalized == required_normalized:
        return True
    return required_normalized == "validated_replay" and normalized == "exact_replay"


def _normalize_route_provenance(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [text]


def _normalize_string_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [text]


def _ref_hash_for_kind(refs: list[StateRef], kind: str) -> str:
    for ref in refs:
        if ref.kind == kind and ref.canonical_hash:
            return ref.canonical_hash
    return ""


def _optional_hash_match(left: str, right: str) -> bool:
    left_hash = str(left or "").strip()
    right_hash = str(right or "").strip()
    if not left_hash or not right_hash:
        return True
    return left_hash == right_hash


def _normalize_runtime_memory_tier(value: object) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "": "long_term_memories",
        "assist": "working_memories",
        "summary": "long_term_memories",
        "working": "working_memories",
        "working_memories": "working_memories",
        "long_term": "long_term_memories",
        "long_term_memories": "long_term_memories",
        "replay": "replay_episodes",
        "episode": "replay_episodes",
        "replay_episodes": "replay_episodes",
        "task_commit": "task_commits",
        "task_commits": "task_commits",
    }
    return mapping.get(text, text)


def _route_is_replay_eligible(
    *,
    route_confidence: float,
    route_provenance: list[str],
    minimum_confidence: float,
) -> bool:
    provenance = set(route_provenance)
    return (
        route_confidence >= minimum_confidence
        and "lexical" in provenance
    )


def _coerce_float(value: object, *, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _find_state_bundle(
    *,
    ctx: RunContext,
    refs: list[StateRef],
    kind: str,
) -> dict[str, Any] | None:
    ref = next((item for item in refs if item.kind == kind), None)
    if ref is None:
        return None
    try:
        payload = ctx.statepool.get_bytes(ref)
        parsed = msgpack.unpackb(payload, raw=False, strict_map_key=False)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return dict(parsed)


def _bundle_string(
    bundle: dict[str, Any] | None,
    key: str,
    *,
    fallback: object,
) -> str:
    if bundle is not None and key in bundle:
        return str(bundle.get(key, "")).strip()
    return str(fallback or "").strip()


def _bundle_string_list(
    bundle: dict[str, Any] | None,
    key: str,
    *,
    fallback: object,
) -> list[str]:
    if bundle is not None and key in bundle:
        return _normalize_string_list(bundle.get(key, []))
    return _normalize_string_list(fallback)


def _bundle_float(
    bundle: dict[str, Any] | None,
    key: str,
    *,
    fallback: object,
    default: float,
) -> float:
    if bundle is not None and key in bundle:
        return _coerce_float(bundle.get(key), default=default)
    return _coerce_float(fallback, default=default)


def _maybe_normalize_comparator_role(role: str) -> str:
    try:
        return normalize_comparator_role_name(role)
    except ValueError:
        return ""
