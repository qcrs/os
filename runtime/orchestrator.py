from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import msgpack

from eval.metrics import TaskMetrics
from memory.store import EmbeddingProvider, MemoryStore
from runtime.contracts import CapabilityTable, SchemaInterceptor
from runtime.llm import LLMResult
from runtime.reuse_contract import resolve_runtime_reuse_contract
from runtime.task_profile import RuntimeTaskProfile, build_reuse_signature
from protocol.messages import (
    Ack,
    Error,
    Hello,
    MemoryCommit,
    MemoryHit,
    Plan,
    PlanStep,
    StateRef,
    StepResult,
    message_type,
    protocol_bytes,
    text_frame,
)
from statepool.store import (
    MMAP_FILE_STORAGE,
    PY_SHARED_MEMORY_STORAGE,
    StatePool,
    StatePoolConfig,
    cleanup_shared_memory_handles,
)


@dataclass
class RunSession:
    mode: str
    handshake_complete: bool = False
    capability_table: CapabilityTable = field(default_factory=CapabilityTable)
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
    task_corpus_doc_ids: tuple[str, ...] = ()
    metrics: TaskMetrics = field(default_factory=TaskMetrics)
    results: dict[str, StepResult] = field(default_factory=dict)
    state_refs: dict[str, StateRef] = field(default_factory=dict)
    memory_hits: list[MemoryHit] = field(default_factory=list)
    memory_search_cache: dict[tuple[object, ...], list[MemoryHit]] = field(default_factory=dict)
    replay_candidate_cache: dict[tuple[object, ...], list[MemoryHit]] = field(default_factory=dict)
    pruned_step_ids: list[str] = field(default_factory=list)
    reuse_hit: MemoryHit | None = None
    reuse_mode: str = "none"
    rejected_memory_hit: MemoryHit | None = None
    runtime_profile: RuntimeTaskProfile = field(default_factory=RuntimeTaskProfile)

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
        else:
            self.metrics.mmap_state_ref_count += 1
            self.metrics.mmap_state_bytes += ref.length

    def resolve_ref(self, state_id: str) -> StateRef:
        ref = self.state_refs.get(state_id)
        if ref is not None:
            return ref
        ref = self.statepool.load_ref(state_id)
        self.state_refs[state_id] = ref
        return ref

    def put_text_state(
        self,
        *,
        state_id: str,
        kind: str,
        text: str,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        ref = self.statepool.put_text(
            state_id,
            kind,
            text,
            metadata=metadata,
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
            metadata=metadata,
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
        ref = self.statepool.put_embedding(
            state_id=state_id,
            payload=vector.astype("float32").tobytes(),
            metadata={
                "encoder_id": self.memory_store.embedder.encoder_id,
                "vector_dim": int(vector.shape[0]),
                "dtype": "float32",
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
        payload = msgpack.packb(feature_bundle, use_bin_type=True)
        ref = self.statepool.put_bytes(
            state_id=state_id,
            kind="FEATURE_BUNDLE",
            payload=payload,
            metadata={
                "encoding": "msgpack",
                "schema": "statebus.feature_bundle.v1",
                **dict(metadata or {}),
            },
        )
        self.register_state(ref)
        return ref

    def get_feature_state(self, ref: StateRef) -> dict[str, object]:
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
        if normalized_purpose == "planner":
            self.metrics.planner_llm_request_count += 1
            self.metrics.planner_prompt_tokens += result.usage.prompt_tokens
            self.metrics.planner_completion_tokens += result.usage.completion_tokens
            self.metrics.planner_total_tokens += result.usage.total_tokens
        elif normalized_purpose == "summarizer":
            self.metrics.summarizer_llm_request_count += 1
            self.metrics.summarizer_prompt_tokens += result.usage.prompt_tokens
            self.metrics.summarizer_completion_tokens += result.usage.completion_tokens
            self.metrics.summarizer_total_tokens += result.usage.total_tokens

    def record_phase_duration(self, phase: str, elapsed_ms: float) -> None:
        normalized_phase = phase.strip().lower()
        if normalized_phase == "planner":
            self.metrics.planner_ms += elapsed_ms
            return
        if normalized_phase == "retrieve":
            self.metrics.retrieve_ms += elapsed_ms
            return
        if normalized_phase == "execute":
            self.metrics.execute_ms += elapsed_ms
            return
        if normalized_phase == "summarize":
            self.metrics.summarize_ms += elapsed_ms
            return
        raise ValueError(f"unsupported phase timing bucket: {phase}")

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


class Orchestrator:
    """Host-side orchestrator for planner-driven benchmark tasks."""

    def __init__(self, agents: dict[str, object]) -> None:
        self.agents = agents

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
            session=active_session,
            statepool=statepool,
            memory_store=memory_store,
            task_corpus_doc_ids=tuple(
                str(doc_id).strip() for doc_id in (task_corpus_doc_ids or []) if str(doc_id).strip()
            ),
            runtime_profile=(
                runtime_profile
                if isinstance(runtime_profile, RuntimeTaskProfile)
                else RuntimeTaskProfile.from_mapping(runtime_profile)
            ),
        )

    async def run_task(self, task: object, ctx: RunContext) -> dict[str, StepResult]:
        started = time.perf_counter()
        if ctx.runtime_profile.is_empty and hasattr(task, "runtime_profile"):
            maybe_profile = getattr(task, "runtime_profile")
            if isinstance(maybe_profile, RuntimeTaskProfile):
                ctx.runtime_profile = maybe_profile
        self._ensure_handshake(ctx)
        plan_started = time.perf_counter()
        plan = await self._plan_task(task, ctx)
        ctx.record_phase_duration("planner", (time.perf_counter() - plan_started) * 1000.0)
        SchemaInterceptor.validate_plan(plan, ctx.session.capability_table)
        ctx.metrics.planned_step_count = len(plan.steps)
        results = await self._execute_plan(plan, ctx)
        ctx.metrics.task_ms = (time.perf_counter() - started) * 1000.0
        return results

    async def run_plan(self, plan: Plan, ctx: RunContext) -> dict[str, StepResult]:
        started = time.perf_counter()
        self._ensure_handshake(ctx)
        SchemaInterceptor.validate_plan(plan, ctx.session.capability_table)
        ctx.metrics.planned_step_count = len(plan.steps)
        results = await self._execute_plan(plan, ctx)
        ctx.metrics.task_ms = (time.perf_counter() - started) * 1000.0
        return results

    async def _execute_plan(self, plan: Plan, ctx: RunContext) -> dict[str, StepResult]:
        ctx.emit(plan)
        retrieve_gate_started = time.perf_counter()
        precomputed_skip = self._resolve_skip_retrieve_execute(plan, ctx)
        ctx.record_phase_duration(
            "retrieve",
            (time.perf_counter() - retrieve_gate_started) * 1000.0,
        )
        for step in plan.steps:
            if step.owner_agent not in self.agents:
                error = Error(
                    code="unknown_agent",
                    detail=f"missing agent {step.owner_agent}",
                    related_id=step.step_id,
                )
                ctx.emit(error)
                raise KeyError(error.detail)
            self._ensure_dependencies(step, ctx)
            if step.step_id in ctx.results:
                continue
            if step.step_id == "retrieve" and precomputed_skip is not None:
                for synthetic_step in precomputed_skip:
                    synthetic_plan_step = self._step_for_emit(plan, synthetic_step.step_id)
                    ctx.emit(synthetic_plan_step)
                    SchemaInterceptor.validate_result(
                        step=synthetic_plan_step,
                        result=synthetic_step,
                        capability_table=ctx.session.capability_table,
                    )
                    self._register_result(synthetic_step, ctx)
                continue
            if step.step_id == "execute":
                execute_phase_ms = 0.0
                execute_gate_started = time.perf_counter()
                maybe_skip = self._resolve_skip_execute(plan, ctx)
                execute_phase_ms += (time.perf_counter() - execute_gate_started) * 1000.0
                if maybe_skip is not None:
                    ctx.record_phase_duration("execute", execute_phase_ms)
                    ctx.emit(step)
                    SchemaInterceptor.validate_result(
                        step=step,
                        result=maybe_skip,
                        capability_table=ctx.session.capability_table,
                    )
                    self._register_result(maybe_skip, ctx)
                    continue
            ctx.emit(step)
            agent = self.agents[step.owner_agent]
            step_started = time.perf_counter()
            result = await agent.execute_step(step, ctx)
            step_elapsed_ms = (time.perf_counter() - step_started) * 1000.0
            if step.step_id == "execute":
                step_elapsed_ms += execute_phase_ms
            phase_name = self._phase_name_for_step(step.step_id)
            if phase_name is not None:
                ctx.record_phase_duration(phase_name, step_elapsed_ms)
            SchemaInterceptor.validate_result(
                step=step,
                result=result,
                capability_table=ctx.session.capability_table,
            )
            self._register_result(result, ctx)
            if not result.success:
                error = Error(
                    code="step_failed",
                    detail=result.error or "step failed",
                    related_id=step.step_id,
                )
                ctx.emit(error)
                break
        return ctx.results

    def _resolve_skip_retrieve_execute(
        self,
        plan: Plan,
        ctx: RunContext,
    ) -> list[StepResult] | None:
        retrieve_step = self._find_step(plan, "retrieve")
        execute_step = self._find_step(plan, "execute")
        hits = ctx.replay_candidates(
            task_theme=ctx.task_theme,
            encoder_id=ctx.memory_store.embedder.encoder_id,
            required_metadata={"memory_purpose": "replay"},
        )
        current_query = str(retrieve_step.params.get("query", ""))
        for hit in hits:
            if not self._matches_skip_retrieve_execute(
                hit=hit,
                task_theme=ctx.task_theme,
                current_query=current_query,
            ):
                continue
            ctx.note_reuse(hit, reuse_mode="skip_retrieve_execute")
            retrieve_result, execute_result = self._build_skip_retrieve_execute_results(
                hit=hit,
                retrieve_step=retrieve_step,
                execute_step=execute_step,
                ctx=ctx,
            )
            hit.skipped_step_ids = ["retrieve", "execute"]
            ctx.pruned_step_ids = ["retrieve", "execute"]
            ctx.metrics.skipped_step_count += 2
            return [retrieve_result, execute_result]
        return None

    def _resolve_skip_execute(
        self,
        plan: Plan,
        ctx: RunContext,
    ) -> StepResult | None:
        retrieve_step = self._find_step(plan, "retrieve")
        execute_step = self._find_step(plan, "execute")
        retrieve_result = ctx.results.get("retrieve")
        if retrieve_result is None:
            return None
        hits = ctx.replay_candidates(
            task_theme=ctx.task_theme,
            encoder_id=ctx.memory_store.embedder.encoder_id,
            required_metadata={"memory_purpose": "replay"},
        )
        current_query = str(retrieve_step.params.get("query", ""))
        for hit in hits:
            if not self._matches_skip_execute(
                hit=hit,
                retrieve_result=retrieve_result,
                current_query=current_query,
            ):
                continue
            ctx.note_reuse(hit, reuse_mode="skip_execute")
            result = self._build_skip_execute_result(hit=hit, execute_step=execute_step, ctx=ctx)
            hit.skipped_step_ids = ["execute"]
            ctx.pruned_step_ids = ["execute"]
            ctx.metrics.skipped_step_count += 1
            return result
        return None

    async def _plan_task(self, task: object, ctx: RunContext) -> Plan:
        planner = self.agents.get("planner")
        if planner is not None and hasattr(planner, "plan_task"):
            return await planner.plan_task(task, ctx)
        from tasks.sample_tasks import build_plan

        return build_plan(task)

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

    def _register_result(self, result: StepResult, ctx: RunContext) -> None:
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

    @staticmethod
    def _find_step(plan: Plan, step_id: str) -> PlanStep:
        for step in plan.steps:
            if step.step_id == step_id:
                return step
        raise KeyError(f"missing step in plan: {step_id}")

    @staticmethod
    def _step_for_emit(plan: Plan, step_id: str) -> PlanStep:
        for step in plan.steps:
            if step.step_id == step_id:
                return step
        raise KeyError(f"missing step in plan: {step_id}")

    @staticmethod
    def _phase_name_for_step(step_id: str) -> str | None:
        if step_id == "retrieve":
            return "retrieve"
        if step_id == "execute":
            return "execute"
        if step_id == "summarize":
            return "summarize"
        return None

    @staticmethod
    def _matches_skip_execute(
        *,
        hit: MemoryHit,
        retrieve_result: StepResult,
        current_query: str,
    ) -> bool:
        feature_route = str(hit.metadata.get("feature_route", "")).strip()
        retrieved_doc_ids = sorted(str(doc_id) for doc_id in hit.metadata.get("retrieved_doc_ids", []))
        fresh_route = str(retrieve_result.payload.get("feature_route", "")).strip()
        fresh_doc_ids = sorted(
            str(doc_id) for doc_id in retrieve_result.payload.get("retrieved_doc_ids", [])
        )
        stored_query = str(hit.metadata.get("feature_query", "")).strip()
        stored_evidence_sha256 = str(
            hit.metadata.get(
                "feature_fresh_evidence_sha256",
                hit.metadata.get("feature_evidence_sha256", ""),
            )
        ).strip()
        fresh_evidence_sha256 = str(
            retrieve_result.payload.get(
                "feature_fresh_evidence_sha256",
                retrieve_result.payload.get("feature_evidence_sha256", ""),
            )
        ).strip()
        stored_route_confidence = _coerce_float(hit.metadata.get("feature_route_confidence"), default=0.0)
        fresh_route_confidence = _coerce_float(
            retrieve_result.payload.get("feature_route_confidence"),
            default=0.0,
        )
        stored_route_provenance = _normalize_route_provenance(
            hit.metadata.get("feature_route_provenance", [])
        )
        fresh_route_provenance = _normalize_route_provenance(
            retrieve_result.payload.get("feature_route_provenance", [])
        )
        reusable_steps = {str(step_id).strip() for step_id in (hit.reusable_steps or []) if str(step_id).strip()}
        return (
            feature_route
            and feature_route != "generic_triage"
            and feature_route == fresh_route
            and "execute" in reusable_steps
            and _query_is_validated_replay_match(stored_query=stored_query, current_query=current_query)
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
        )

    def _matches_skip_retrieve_execute(
        self,
        *,
        hit: MemoryHit,
        task_theme: str,
        current_query: str,
    ) -> bool:
        feature_route = str(hit.metadata.get("feature_route", "")).strip()
        retrieved_doc_ids = sorted(str(doc_id) for doc_id in hit.metadata.get("retrieved_doc_ids", []))
        stored_query = _normalize_replay_query(str(hit.metadata.get("feature_query", "")))
        normalized_query = _normalize_replay_query(current_query)
        route_confidence = _coerce_float(hit.metadata.get("feature_route_confidence"), default=0.0)
        route_provenance = _normalize_route_provenance(
            hit.metadata.get("feature_route_provenance", [])
        )
        evidence_sha256 = str(
            hit.metadata.get(
                "feature_fresh_evidence_sha256",
                hit.metadata.get("feature_evidence_sha256", ""),
            )
        ).strip()
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
            and bool(evidence_sha256)
            and _route_is_replay_eligible(
                route_confidence=route_confidence,
                route_provenance=route_provenance,
                minimum_confidence=0.80,
            )
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
        if retrieve_result is not None:
            feature_state_id = next(
                (
                    ref.state_id
                    for ref in retrieve_result.output_state_refs
                    if ref.kind == "FEATURE_BUNDLE"
                ),
                "",
            )
        artifact_ref = self._copy_memory_ref(
            ctx=ctx,
            hit=hit,
            source_kind="TOOL_ARTIFACT",
            target_state_id=f"{ctx.task_id}-{execute_step.step_id}-artifact",
        )
        route = str(hit.metadata.get("feature_route", "")).strip()
        route_source = str(hit.metadata.get("feature_route_source", "")).strip()
        route_confidence = _coerce_float(hit.metadata.get("feature_route_confidence"), default=0.0)
        route_provenance = _normalize_route_provenance(
            hit.metadata.get("feature_route_provenance", [])
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
                "reused_memory": True,
                "reuse_mode": "skip_execute",
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
        evidence_ref = self._copy_memory_ref(
            ctx=ctx,
            hit=hit,
            source_kind="DENSE_EVIDENCE",
            target_state_id=f"{ctx.task_id}-{retrieve_step.step_id}-evidence",
        )
        feature_ref = self._copy_memory_ref(
            ctx=ctx,
            hit=hit,
            source_kind="FEATURE_BUNDLE",
            target_state_id=f"{ctx.task_id}-{retrieve_step.step_id}-features",
        )
        embedding_ref = self._copy_memory_ref(
            ctx=ctx,
            hit=hit,
            source_kind="EMBEDDING",
            target_state_id=f"{ctx.task_id}-{retrieve_step.step_id}-embedding",
        )
        artifact_ref = self._copy_memory_ref(
            ctx=ctx,
            hit=hit,
            source_kind="TOOL_ARTIFACT",
            target_state_id=f"{ctx.task_id}-{execute_step.step_id}-artifact",
        )
        route = str(hit.metadata.get("feature_route", "")).strip()
        route_source = str(hit.metadata.get("feature_route_source", "")).strip()
        route_confidence = _coerce_float(hit.metadata.get("feature_route_confidence"), default=0.0)
        route_provenance = _normalize_route_provenance(
            hit.metadata.get("feature_route_provenance", [])
        )
        hint_doc_ids = [str(doc_id) for doc_id in hit.metadata.get("feature_hint_doc_ids", [])]
        retrieved_doc_ids = list(hit.metadata.get("retrieved_doc_ids", []))
        retrieve_result = StepResult(
            step_id=retrieve_step.step_id,
            success=True,
            output_state_refs=[evidence_ref, feature_ref, embedding_ref],
            payload={
                "query": retrieve_step.params.get("query", ""),
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
                "feature_state_id": feature_ref.state_id,
                "reused_memory": True,
                "reuse_mode": "skip_retrieve_execute",
            },
            skipped=True,
            reused_from_memory_id=hit.memory_id,
        )
        return retrieve_result, execute_result

    @staticmethod
    def _copy_memory_ref(
        *,
        ctx: RunContext,
        hit: MemoryHit,
        source_kind: str,
        target_state_id: str,
    ) -> StateRef:
        source_ref = next(
            (ref for ref in hit.evidence_state_refs if ref.kind == source_kind),
            None,
        )
        if source_ref is None:
            raise ValueError(f"memory {hit.memory_id} missing required state kind {source_kind}")
        payload = ctx.statepool.get_bytes(source_ref)
        metadata: dict[str, Any] = dict(source_ref.metadata)
        metadata["reused_from_memory_id"] = hit.memory_id
        metadata["reused_from_source_task_id"] = hit.source_task_id or ""
        ref = ctx.statepool.put_bytes(
            state_id=target_state_id,
            kind=source_ref.kind,
            payload=payload,
            metadata=metadata,
            storage=source_ref.storage,
        )
        ctx.register_state(ref)
        return ref

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
