from __future__ import annotations

import asyncio
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.sample_agents import build_sample_agents_with_executor
from memory.store import EmbeddingProvider
from protocol.messages import Plan, StepResult
from runtime.llm import DeterministicLLMClient, LLMClient
from runtime.orchestrator import Orchestrator, RunContext, RunSession
from statepool.store import StatePoolConfig
from tasks.sample_tasks import SampleTask

STATEBUS_GRAPH_NODES = ("planner", "retriever", "executor", "summarizer")


@dataclass(frozen=True)
class GraphRunnerResult:
    task_id: str
    mode: str
    engine: str
    node_order: tuple[str, ...]
    results: dict[str, StepResult]
    metrics: dict[str, int | float]
    state_channels: dict[str, dict[str, object]]
    graph_state: dict[str, object]
    state_refs: dict[str, dict[str, object]]
    memory_hits: list[str]
    ctx: RunContext
    langgraph_available: bool


class StateBusGraphRunner:
    """LangGraph-backed StateBus runtime.

    The graph owns task execution state. It reuses public StateBus runtime
    primitives for schema validation, replay gates, step invocation, result
    registration, and StatePool/MemoryStore effects.
    """

    def __init__(
        self,
        *,
        llm_client: LLMClient | None = None,
        embedder: EmbeddingProvider | None = None,
        statepool_config: StatePoolConfig | None = None,
        executor_transport: str | None = None,
        executor_socket_path: str | None = None,
    ) -> None:
        self.llm_client = llm_client or DeterministicLLMClient()
        self.embedder = embedder
        self.statepool_config = statepool_config
        self.agents = build_sample_agents_with_executor(
            llm_client=self.llm_client,
            executor_transport=executor_transport,
            executor_socket_path=executor_socket_path,
        )
        self.orchestrator = Orchestrator(self.agents)

    async def run_task(
        self,
        task: SampleTask,
        *,
        mode: str = "protocol",
        state_root: str | Path | None = None,
        memory_db_path: str | Path | None = None,
        session: RunSession | None = None,
        ctx: RunContext | None = None,
    ) -> GraphRunnerResult:
        if ctx is not None:
            return await self._run_task_with_context(task, ctx)
        with _maybe_temp_runtime_paths(
            state_root=state_root,
            memory_db_path=memory_db_path,
        ) as paths:
            ctx = Orchestrator.create_context(
                mode=mode,
                task_id=task.task_id,
                task_group=task.task_group,
                task_theme=task.task_theme,
                state_root=paths["state_root"],
                memory_db_path=paths["memory_db_path"],
                embedder=self.embedder,
                session=session,
                statepool_config=self.statepool_config,
                task_corpus_doc_ids=list(task.corpus_doc_ids),
                task_corpus_path=task.corpus_path,
                runtime_profile=task.runtime_profile,
            )
            return await self._run_task_with_context(task, ctx)

    async def _run_task_with_context(
        self,
        task: SampleTask,
        ctx: RunContext,
    ) -> GraphRunnerResult:
        started = time.perf_counter()
        results = await self._run_compiled_graph(task, ctx)
        ctx.metrics.task_ms = (time.perf_counter() - started) * 1000.0
        return GraphRunnerResult(
            task_id=task.task_id,
            mode=ctx.mode,
            engine="langgraph",
            node_order=STATEBUS_GRAPH_NODES,
            results=results,
            metrics=ctx.metrics.to_dict(),
            state_channels=_state_channel_summary(ctx),
            graph_state=_graph_state_snapshot(task, ctx, results),
            state_refs={
                state_id: {
                    "kind": ref.kind,
                    "storage": ref.storage,
                    "handle": ref.handle,
                    "length": ref.length,
                    "metadata": dict(ref.metadata),
                }
                for state_id, ref in ctx.state_refs.items()
            },
            memory_hits=[hit.memory_id for hit in ctx.memory_hits],
            ctx=ctx,
            langgraph_available=langgraph_available(),
        )

    async def _run_compiled_graph(
        self,
        task: SampleTask,
        ctx: RunContext,
    ) -> dict[str, StepResult]:
        state = await self._invoke_graph(task, ctx)
        results = state.get("results", {})
        return results if isinstance(results, dict) else {}

    def build_langgraph(self) -> Any:
        """Return a compiled LangGraph StateGraph when langgraph is installed.

        Tests and host benchmark paths can still use the graph-native fallback
        when the optional dependency is absent.
        """
        try:
            from langgraph.graph import END, StateGraph
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("langgraph is not installed in this host env") from exc

        async def planner_node(state: dict[str, Any]) -> dict[str, Any]:
            return await self._planner_node(state)

        async def retriever_node(state: dict[str, Any]) -> dict[str, Any]:
            return await self._retriever_node(state)

        async def executor_node(state: dict[str, Any]) -> dict[str, Any]:
            return await self._executor_node(state)

        async def summarizer_node(state: dict[str, Any]) -> dict[str, Any]:
            return await self._summarizer_node(state)

        graph = StateGraph(dict)
        graph.add_node("planner", planner_node)
        graph.add_node("retriever", retriever_node)
        graph.add_node("executor", executor_node)
        graph.add_node("summarizer", summarizer_node)
        graph.set_entry_point("planner")
        graph.add_edge("planner", "retriever")
        graph.add_edge("retriever", "executor")
        graph.add_edge("executor", "summarizer")
        graph.add_edge("summarizer", END)
        return graph.compile()

    async def _invoke_graph(self, task: SampleTask, ctx: RunContext) -> dict[str, Any]:
        state = {
            "task": task,
            "ctx": ctx,
            "task_id": task.task_id,
            "plan": None,
            "step_results": {},
            "results": {},
            "state_refs": {},
            "memory_hits": [],
            "replay_decision": {
                "mode": "none",
                "candidate_count": 0,
                "reject_reason": "not_probed",
                "restored_state_ref_count": 0,
            },
            "metrics": ctx.metrics.to_dict(),
            "status": "running",
        }
        if langgraph_available():
            graph = self.build_langgraph()
            return await graph.ainvoke(state)
        for node in (
            self._planner_node,
            self._retriever_node,
            self._executor_node,
            self._summarizer_node,
        ):
            state = await node(state)
        return state

    async def _planner_node(self, state: dict[str, Any]) -> dict[str, Any]:
        ctx: RunContext = state["ctx"]
        plan = await self.orchestrator.compile_task_plan(state["task"], ctx)
        state["plan"] = plan
        self._refresh_state_snapshot(state)
        return state

    async def _retriever_node(self, state: dict[str, Any]) -> dict[str, Any]:
        plan = _require_plan(state)
        ctx: RunContext = state["ctx"]
        if state.get("status") == "failed":
            return state
        gate_started = time.perf_counter()
        precomputed_skip = self.orchestrator.resolve_skip_retrieve_execute(plan, ctx)
        gate_elapsed_ms = (time.perf_counter() - gate_started) * 1000.0
        if precomputed_skip is not None:
            ctx.record_phase_duration("retrieve", gate_elapsed_ms)
            for result in precomputed_skip:
                step = _step_by_id(plan, result.step_id)
                self.orchestrator.register_step_result(
                    step=step,
                    result=result,
                    ctx=ctx,
                    emit_step=True,
                )
            self._refresh_state_snapshot(state)
            return state
        step = _step_by_id(plan, "retrieve")
        await self._invoke_normal_step(state, step)
        return state

    async def _executor_node(self, state: dict[str, Any]) -> dict[str, Any]:
        plan = _require_plan(state)
        ctx: RunContext = state["ctx"]
        if state.get("status") == "failed":
            return state
        if "execute" in ctx.results:
            self._refresh_state_snapshot(state)
            return state
        step = _step_by_id(plan, "execute")
        gate_started = time.perf_counter()
        maybe_skip = self.orchestrator.resolve_skip_execute(plan, ctx)
        gate_elapsed_ms = (time.perf_counter() - gate_started) * 1000.0
        if maybe_skip is not None:
            ctx.record_phase_duration("execute", gate_elapsed_ms)
            self.orchestrator.register_step_result(
                step=step,
                result=maybe_skip,
                ctx=ctx,
                emit_step=True,
            )
            self._refresh_state_snapshot(state)
            return state
        await self._invoke_normal_step(state, step)
        return state

    async def _summarizer_node(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") == "failed":
            return state
        plan = _require_plan(state)
        step = _step_by_id(plan, "summarize")
        await self._invoke_normal_step(state, step)
        state["status"] = "completed"
        return state

    async def _invoke_normal_step(
        self,
        state: dict[str, Any],
        step: Any,
    ) -> None:
        plan = _require_plan(state)
        ctx: RunContext = state["ctx"]
        self.orchestrator.ensure_step_ready(step, ctx)
        result, elapsed_ms = await self.orchestrator.invoke_plan_step(plan, step, ctx)
        phase_name = self.orchestrator.phase_name_for_step(step.step_id)
        if phase_name is not None:
            ctx.record_phase_duration(phase_name, elapsed_ms)
        self.orchestrator.register_step_result(
            step=step,
            result=result,
            ctx=ctx,
            emit_step=False,
        )
        if not result.success:
            state["status"] = "failed"
        self._refresh_state_snapshot(state)

    @staticmethod
    def _refresh_state_snapshot(state: dict[str, Any]) -> None:
        ctx: RunContext = state["ctx"]
        state["step_results"] = dict(ctx.results)
        state["results"] = dict(ctx.results)
        state["state_refs"] = dict(ctx.state_refs)
        state["memory_hits"] = [hit.memory_id for hit in ctx.memory_hits]
        state["metrics"] = ctx.metrics.to_dict()
        state["replay_decision"] = {
            "mode": ctx.reuse_mode if ctx.reuse_hit is not None else "none",
            "candidate_count": ctx.metrics.replay_probe_hits,
            "memory_id": None if ctx.reuse_hit is None else ctx.reuse_hit.memory_id,
            "reject_reason": "" if ctx.reuse_hit is not None else (
                "no_candidate" if ctx.metrics.replay_probe_count > 0 else "not_probed"
            ),
            "restored_state_ref_count": (
                len(ctx.reuse_hit.step_output_state_refs) if ctx.reuse_hit is not None else 0
            ),
        }


def run_task_sync(
    task: SampleTask,
    *,
    mode: str = "protocol",
    llm_client: LLMClient | None = None,
    embedder: EmbeddingProvider | None = None,
) -> GraphRunnerResult:
    runner = StateBusGraphRunner(llm_client=llm_client, embedder=embedder)
    return asyncio.run(runner.run_task(task, mode=mode))


def langgraph_available() -> bool:
    try:
        import langgraph  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


class _maybe_temp_runtime_paths:
    def __init__(
        self,
        *,
        state_root: str | Path | None,
        memory_db_path: str | Path | None,
    ) -> None:
        self.state_root = Path(state_root) if state_root is not None else None
        self.memory_db_path = Path(memory_db_path) if memory_db_path is not None else None
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> dict[str, Path]:
        if self.state_root is not None and self.memory_db_path is not None:
            return {
                "state_root": self.state_root,
                "memory_db_path": self.memory_db_path,
            }
        self._tmpdir = tempfile.TemporaryDirectory(prefix="statebus-graph-")
        root = Path(self._tmpdir.name)
        return {
            "state_root": self.state_root or root / "state",
            "memory_db_path": self.memory_db_path or root / "memory.sqlite3",
        }

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._tmpdir is not None:
            self._tmpdir.cleanup()


def _state_channel_summary(ctx: RunContext) -> dict[str, dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    for ref in ctx.state_refs.values():
        channel_name = str(ref.metadata.get("channel_name", "")).strip() or "unclassified"
        row = summary.setdefault(
            channel_name,
            {
                "channel_kind": str(ref.metadata.get("channel_kind", "")),
                "state_ref_count": 0,
                "state_bytes": 0,
                "state_kinds": [],
            },
        )
        row["state_ref_count"] = int(row["state_ref_count"]) + 1
        row["state_bytes"] = int(row["state_bytes"]) + ref.length
        state_kinds = list(row["state_kinds"])
        if ref.kind not in state_kinds:
            state_kinds.append(ref.kind)
        row["state_kinds"] = sorted(state_kinds)
    return summary


def _graph_state_snapshot(
    task: SampleTask,
    ctx: RunContext,
    results: dict[str, StepResult],
) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "plan_step_ids": list(results),
        "state_ref_ids": sorted(ctx.state_refs),
        "memory_hit_ids": [hit.memory_id for hit in ctx.memory_hits],
        "replay_decision": {
            "mode": ctx.reuse_mode if ctx.reuse_hit is not None else "none",
            "candidate_count": ctx.metrics.replay_probe_hits,
            "memory_id": None if ctx.reuse_hit is None else ctx.reuse_hit.memory_id,
            "reject_reason": "" if ctx.reuse_hit is not None else (
                "no_candidate" if ctx.metrics.replay_probe_count > 0 else "not_probed"
            ),
            "restored_state_ref_count": (
                len(ctx.reuse_hit.step_output_state_refs) if ctx.reuse_hit is not None else 0
            ),
        },
        "metrics": ctx.metrics.to_dict(),
        "status": "completed" if "summarize" in results else "running",
    }


def _require_plan(state: dict[str, Any]) -> Plan:
    plan = state.get("plan")
    if not isinstance(plan, Plan):
        raise RuntimeError("graph state is missing compiled plan")
    return plan


def _step_by_id(plan: Plan, step_id: str) -> Any:
    for step in plan.steps:
        if step.step_id == step_id:
            return step
    raise KeyError(f"missing step in graph plan: {step_id}")
