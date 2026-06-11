from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.sample_agents import build_sample_agents_with_executor
from memory.store import EmbeddingProvider
from protocol.messages import Plan, StepResult
from runtime.llm import DeterministicLLMClient, LLMClient
from runtime.orchestrator import Orchestrator, RunContext, RunSession
from statepool.store import StatePoolConfig
from tasks.sample_tasks import SampleTask, build_plan, normalize_plan_source

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
    langgraph_available: bool


class StateBusGraphRunner:
    """LangGraph-compatible facade over the host-side StateBus orchestrator.

    LangGraph is an optional orchestration surface here. The authoritative data
    path remains the existing Orchestrator, StateRef, StatePool, and MemoryStore
    implementation used by the benchmark runner.
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
    ) -> GraphRunnerResult:
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
            results = await self._run_compiled_graph(task, ctx)
            return GraphRunnerResult(
                task_id=task.task_id,
                mode=mode,
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

    async def _compile_plan(self, task: SampleTask, ctx: RunContext) -> Plan:
        if normalize_plan_source(task.plan_source) == "yaml":
            return build_plan(task)
        planner = self.agents.get("planner")
        if planner is None or not hasattr(planner, "plan_task"):
            raise KeyError("planner agent is required for plan_source=llm")
        return await planner.plan_task(task, ctx)

    def build_langgraph(self) -> Any:
        """Return a compiled LangGraph StateGraph when langgraph is installed.

        The nodes are intentionally thin labels around the existing StateBus
        phases. Tests and host benchmark paths do not require this optional
        dependency.
        """
        try:
            from langgraph.graph import END, StateGraph
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("langgraph is not installed in this host env") from exc

        async def planner_node(state: dict[str, Any]) -> dict[str, Any]:
            plan = await self._compile_plan(state["task"], state["ctx"])
            state["plan"] = plan
            state["ctx"].metrics.planned_step_count = len(plan.steps)
            state["metrics"] = state["ctx"].metrics.to_dict()
            return state

        async def retriever_node(state: dict[str, Any]) -> dict[str, Any]:
            plan: Plan = state["plan"]
            retrieve_step = next(step for step in plan.steps if step.step_id == "retrieve")
            result = await self.agents["retriever"].execute_step(retrieve_step, state["ctx"])
            self.orchestrator._register_result(result, state["ctx"])
            state["results"]["retrieve"] = result
            return state

        async def executor_node(state: dict[str, Any]) -> dict[str, Any]:
            plan: Plan = state["plan"]
            execute_step = next(step for step in plan.steps if step.step_id == "execute")
            self.orchestrator._prepare_step_input_refs(plan, execute_step, state["ctx"])
            result = await self.agents["executor"].execute_step(execute_step, state["ctx"])
            self.orchestrator._register_result(result, state["ctx"])
            state["results"]["execute"] = result
            return state

        async def summarizer_node(state: dict[str, Any]) -> dict[str, Any]:
            plan: Plan = state["plan"]
            summarize_step = next(step for step in plan.steps if step.step_id == "summarize")
            self.orchestrator._prepare_step_input_refs(plan, summarize_step, state["ctx"])
            result = await self.agents["summarizer"].execute_step(summarize_step, state["ctx"])
            self.orchestrator._register_result(result, state["ctx"])
            state["results"]["summarize"] = result
            state["metrics"] = state["ctx"].metrics.to_dict()
            return state

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
        self.orchestrator._ensure_handshake(ctx)
        state = {
            "task": task,
            "ctx": ctx,
            "task_id": task.task_id,
            "plan": None,
            "results": {},
            "state_refs": {},
            "memory_hits": [],
            "metrics": ctx.metrics.to_dict(),
        }
        if langgraph_available():
            graph = self.build_langgraph()
            return await graph.ainvoke(state)
        plan = await self._compile_plan(task, ctx)
        results = await self.orchestrator.run_plan(plan, ctx)
        state["plan"] = plan
        state["results"] = results
        state["state_refs"] = dict(ctx.state_refs)
        state["memory_hits"] = [hit.memory_id for hit in ctx.memory_hits]
        state["metrics"] = ctx.metrics.to_dict()
        return state


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
        "metrics": ctx.metrics.to_dict(),
    }
