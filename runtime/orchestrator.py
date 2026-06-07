from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import msgpack

from eval.metrics import TaskMetrics
from memory.store import EmbeddingProvider, MemoryStore
from runtime.contracts import CapabilityTable, SchemaInterceptor
from runtime.llm import LLMResult
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
    metrics: TaskMetrics = field(default_factory=TaskMetrics)
    results: dict[str, StepResult] = field(default_factory=dict)
    state_refs: dict[str, StateRef] = field(default_factory=dict)
    memory_hits: list[MemoryHit] = field(default_factory=list)
    memory_search_cache: dict[tuple[object, ...], list[MemoryHit]] = field(default_factory=dict)
    pruned_step_ids: list[str] = field(default_factory=list)
    reuse_hit: MemoryHit | None = None

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

    def commit_memory(self, commit: MemoryCommit) -> None:
        self.emit(commit)
        self.memory_store.commit_memory(commit)

    def record_llm_result(self, result: LLMResult) -> None:
        self.metrics.llm_request_count += 1
        self.metrics.llm_prompt_tokens += result.usage.prompt_tokens
        self.metrics.llm_completion_tokens += result.usage.completion_tokens
        self.metrics.llm_total_tokens += result.usage.total_tokens

    def note_reuse(self, hit: MemoryHit, skipped_step_ids: list[str]) -> None:
        hit.reused_as_plan_patch = True
        hit.skipped_step_ids = list(skipped_step_ids)
        self.reuse_hit = hit
        self.pruned_step_ids = list(skipped_step_ids)
        self.metrics.skipped_step_count += len(skipped_step_ids)


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
        )

    async def run_task(self, task: object, ctx: RunContext) -> dict[str, StepResult]:
        started = time.perf_counter()
        self._ensure_handshake(ctx)
        plan = await self._plan_task(task, ctx)
        SchemaInterceptor.validate_plan(plan, ctx.session.capability_table)
        ctx.metrics.planned_step_count = len(plan.steps)
        plan = self._apply_memory_reuse(plan, ctx)
        results = await self._execute_plan(plan, ctx)
        ctx.metrics.task_ms = (time.perf_counter() - started) * 1000.0
        return results

    async def run_plan(self, plan: Plan, ctx: RunContext) -> dict[str, StepResult]:
        started = time.perf_counter()
        self._ensure_handshake(ctx)
        SchemaInterceptor.validate_plan(plan, ctx.session.capability_table)
        ctx.metrics.planned_step_count = len(plan.steps)
        plan = self._apply_memory_reuse(plan, ctx)
        results = await self._execute_plan(plan, ctx)
        ctx.metrics.task_ms = (time.perf_counter() - started) * 1000.0
        return results

    async def _execute_plan(self, plan: Plan, ctx: RunContext) -> dict[str, StepResult]:
        ctx.emit(plan)
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
            ctx.emit(step)
            agent = self.agents[step.owner_agent]
            result = await agent.execute_step(step, ctx)
            SchemaInterceptor.validate_result(
                step=step,
                result=result,
                capability_table=ctx.session.capability_table,
            )
            self._register_step_outputs(result, ctx)
            maybe_commit = result.memory_commit
            if isinstance(maybe_commit, MemoryCommit):
                SchemaInterceptor.validate_memory_commit(maybe_commit)
                ctx.commit_memory(maybe_commit)
                ctx.emit(Ack(related_id=maybe_commit.memory_id, detail="memory committed"))
            ctx.emit(result)
            ctx.results[step.step_id] = result
            if not result.success:
                error = Error(
                    code="step_failed",
                    detail=result.error or "step failed",
                    related_id=step.step_id,
                )
                ctx.emit(error)
                break
        return ctx.results

    async def _plan_task(self, task: object, ctx: RunContext) -> Plan:
        planner = self.agents.get("planner")
        if planner is not None and hasattr(planner, "plan_task"):
            return await planner.plan_task(task, ctx)
        from tasks.sample_tasks import build_plan

        return build_plan(task)

    def _apply_memory_reuse(self, plan: Plan, ctx: RunContext) -> Plan:
        retrieve_step = next(
            (
                step
                for step in plan.steps
                if step.step_id == "retrieve" and step.params.get("allow_memory_reuse")
            ),
            None,
        )
        if retrieve_step is None:
            return plan
        hits = ctx.search_memory(
            task_theme=ctx.task_theme,
            query_text=str(retrieve_step.params["query"]),
            top_k=1,
            tags=list(retrieve_step.params.get("tags", [])),
            tags_any=list(retrieve_step.params.get("tags", [])),
            tags_all=list(retrieve_step.params.get("reuse_tags", retrieve_step.params.get("tags", []))),
            min_confidence=0.6,
            encoder_id=ctx.memory_store.embedder.encoder_id,
            required_metadata={
                "reuse_signature": str(retrieve_step.params.get("reuse_signature", "")),
            },
        )
        if not hits:
            return plan
        hit = hits[0]
        refs_by_kind = self._group_refs_by_kind(hit.evidence_state_refs)
        skipped_step_ids: list[str] = []
        if "retrieve" in hit.reusable_steps and refs_by_kind.get("DENSE_EVIDENCE"):
            skipped_step_ids.append("retrieve")
        if "execute" in hit.reusable_steps and refs_by_kind.get("TOOL_ARTIFACT"):
            skipped_step_ids.append("execute")
        if not skipped_step_ids:
            return plan
        self._seed_reused_results(ctx, hit, skipped_step_ids)
        ctx.note_reuse(hit, skipped_step_ids)
        ctx.emit(Ack(related_id=hit.memory_id, detail=f"memory reuse applied: {','.join(skipped_step_ids)}"))
        return Plan(
            task_id=plan.task_id,
            goal=plan.goal,
            steps=[step for step in plan.steps if step.step_id not in skipped_step_ids],
        )

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

    @staticmethod
    def _group_refs_by_kind(refs: list[StateRef]) -> dict[str, list[StateRef]]:
        grouped: dict[str, list[StateRef]] = {}
        for ref in refs:
            grouped.setdefault(ref.kind, []).append(ref)
        return grouped

    def _seed_reused_results(
        self,
        ctx: RunContext,
        hit: MemoryHit,
        skipped_step_ids: list[str],
    ) -> None:
        refs_by_kind = self._group_refs_by_kind(hit.evidence_state_refs)
        evidence_refs = list(refs_by_kind.get("DENSE_EVIDENCE", []))
        feature_refs = list(refs_by_kind.get("FEATURE_BUNDLE", []))
        embedding_refs = list(refs_by_kind.get("EMBEDDING", []))
        artifact_refs = list(refs_by_kind.get("TOOL_ARTIFACT", []))
        if "retrieve" in skipped_step_ids:
            retrieve_refs = evidence_refs + feature_refs + embedding_refs
            result = StepResult(
                step_id="retrieve",
                success=True,
                output_state_refs=retrieve_refs,
                payload={
                    "memory_hits": [hit.memory_id],
                    "reused_memory": True,
                    "reuse_source": hit.reuse_source,
                },
                skipped=True,
                reused_from_memory_id=hit.memory_id,
            )
            self._register_step_outputs(result, ctx)
            ctx.results["retrieve"] = result
        if "execute" in skipped_step_ids and artifact_refs:
            actions = []
            artifact_text = ctx.get_text_state(artifact_refs[0]).strip()
            if artifact_text:
                actions = [line for line in artifact_text.splitlines() if line.strip()]
            result = StepResult(
                step_id="execute",
                success=True,
                output_state_refs=[artifact_refs[0]],
                payload={
                    "actions": actions,
                    "reusable_steps": list(hit.reusable_steps),
                    "reused_memory": True,
                    "reuse_source": hit.reuse_source,
                },
                skipped=True,
                reused_from_memory_id=hit.memory_id,
            )
            self._register_step_outputs(result, ctx)
            ctx.results["execute"] = result
