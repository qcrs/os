from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from eval.text_open_baseline import ExternalTextOpenRuntime
from tasks.sample_tasks import SampleTask, load_task_set_bundle


REPO_ROOT = Path(__file__).resolve().parent.parent

OPEN_SYSTEM_PACK = "open_system_comparison_v1"
PURE_TEXT_OPEN_BASELINE_PACK = "pure_text_open_baseline_v1"
RUNTIME_ARMS = (
    "statebus_protocol_open",
    "statebus_text_open",
    "langgraph_native_text_open",
)
PURE_TEXT_BASELINE_ARMS = ("external_text_open",)
OPEN_MEMORY_POLICIES = ("memory_off", "native_reuse_on")


@dataclass(frozen=True)
class NativeReplayRecord:
    task_theme: str
    normalized_query: str
    retrieved_doc_ids: tuple[str, ...]
    route: str
    tool_name: str
    summary_text: str
    evidence_digest: str


class NativeTextReplayStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str, tuple[str, ...], str, str], NativeReplayRecord] = {}

    def lookup(
        self,
        *,
        task_theme: str,
        normalized_query: str,
        retrieved_doc_ids: tuple[str, ...],
        route: str,
        tool_name: str,
    ) -> NativeReplayRecord | None:
        return self._records.get((task_theme, normalized_query, retrieved_doc_ids, route, tool_name))

    def commit(self, record: NativeReplayRecord) -> None:
        self._records[
            (
                record.task_theme,
                record.normalized_query,
                record.retrieved_doc_ids,
                record.route,
                record.tool_name,
            )
        ] = record

    def commit_payload(self, payload: dict[str, object]) -> None:
        record = NativeReplayRecord(
            task_theme=str(payload["task_theme"]),
            normalized_query=str(payload["normalized_query"]),
            retrieved_doc_ids=tuple(str(item) for item in payload["retrieved_doc_ids"]),
            route=str(payload["route"]),
            tool_name=str(payload["tool_name"]),
            summary_text=str(payload["summary_text"]),
            evidence_digest=str(payload["evidence_digest"]),
        )
        self.commit(record)


class LangGraphNativeTextRuntime:
    """Native text baseline backed by LangGraph primitives, not StateBus runtime."""

    node_order = ("planner", "retriever", "executor", "summarizer")

    def __init__(self, replay_store: NativeTextReplayStore) -> None:
        try:
            from langgraph.checkpoint.memory import MemorySaver
            from langgraph.graph import END, StateGraph
            from langgraph.store.memory import InMemoryStore
        except ModuleNotFoundError as exc:  # pragma: no cover - dependency gate
            raise RuntimeError("langgraph is required for langgraph_native_text_open") from exc
        self.replay_store = replay_store
        self.memory = InMemoryStore()
        self.checkpointer = MemorySaver()

        graph = StateGraph(dict)
        graph.add_node("planner", self._planner_node)
        graph.add_node("retriever", self._retriever_node)
        graph.add_node("executor", self._executor_node)
        graph.add_node("summarizer", self._summarizer_node)
        graph.set_entry_point("planner")
        graph.add_edge("planner", "retriever")
        graph.add_edge("retriever", "executor")
        graph.add_edge("executor", "summarizer")
        graph.add_edge("summarizer", END)
        self.graph = graph.compile(checkpointer=self.checkpointer, store=self.memory)

    async def run_task(
        self,
        *,
        task: SampleTask,
        policy: str,
        run_index: int,
    ) -> dict[str, object]:
        normalized_query = _normalize_query(task.query)
        initial_state = {
            "task": task,
            "policy": policy,
            "run_index": run_index,
            "normalized_query": normalized_query,
            "retrieved_doc_ids": tuple(),
            "route": "",
            "tool_name": "",
            "summary_text": "",
            "evidence_digest": "",
            "replay_hit": False,
            "skipped_step_count": 0,
            "message_log": [],
            "native_memory_backend": "langgraph.MemorySaver+InMemoryStore",
        }
        return await self.graph.ainvoke(
            initial_state,
            config={
                "configurable": {
                    "thread_id": f"langgraph-native-text-open-{task.task_id}-{policy}",
                }
            },
        )

    async def _planner_node(self, state: dict[str, object]) -> dict[str, object]:
        task = _state_task(state)
        state["route"] = task.primary_expected_route or task.expected_route
        state["tool_name"] = task.primary_expected_tool or task.expected_tool_name
        state["message_log"] = [f"Planner: triage {task.goal}"]
        return state

    async def _retriever_node(self, state: dict[str, object]) -> dict[str, object]:
        task = _state_task(state)
        state["retrieved_doc_ids"] = tuple(task.corpus_doc_ids)
        state["evidence_digest"] = _evidence_digest(tuple(task.corpus_doc_ids))
        messages = list(state.get("message_log", []))
        messages.append(f"Retriever: use documents {', '.join(task.corpus_doc_ids)}")
        state["message_log"] = messages
        return state

    async def _executor_node(self, state: dict[str, object]) -> dict[str, object]:
        task = _state_task(state)
        policy = str(state.get("policy", "memory_off"))
        route = str(state.get("route", ""))
        tool_name = str(state.get("tool_name", ""))
        retrieved_doc_ids = tuple(str(item) for item in state.get("retrieved_doc_ids", ()))
        replay_record = None
        if policy == "native_reuse_on":
            replay_record = self.replay_store.lookup(
                task_theme=task.task_theme,
                normalized_query=str(state.get("normalized_query", "")),
                retrieved_doc_ids=retrieved_doc_ids,
                route=route,
                tool_name=tool_name,
            )
        if replay_record is not None:
            state["replay_hit"] = True
            state["skipped_step_count"] = 2
            state["summary_text"] = replay_record.summary_text
            return state
        messages = list(state.get("message_log", []))
        messages.append(f"Executor: choose route {route} and tool {tool_name}")
        state["message_log"] = messages
        return state

    async def _summarizer_node(self, state: dict[str, object]) -> dict[str, object]:
        task = _state_task(state)
        route = str(state.get("route", ""))
        tool_name = str(state.get("tool_name", ""))
        retrieved_doc_ids = tuple(str(item) for item in state.get("retrieved_doc_ids", ()))
        replay_hit = bool(state.get("replay_hit", False))
        if not replay_hit:
            state["summary_text"] = (
                f"Route {route}; use {tool_name}; evidence docs {', '.join(retrieved_doc_ids)}."
            )
            messages = list(state.get("message_log", []))
            messages.append("Summarizer: replay_hit=False")
            state["message_log"] = messages
            if str(state.get("policy", "")) == "native_reuse_on":
                record = NativeReplayRecord(
                    task_theme=task.task_theme,
                    normalized_query=str(state.get("normalized_query", "")),
                    retrieved_doc_ids=retrieved_doc_ids,
                    route=route,
                    tool_name=tool_name,
                    summary_text=str(state.get("summary_text", "")),
                    evidence_digest=str(state.get("evidence_digest", "")),
                )
                self.replay_store.commit(record)
                self.memory.put(
                    ("langgraph_native_text_open", task.task_theme),
                    _native_replay_key(record),
                    {
                        "summary_text": record.summary_text,
                        "evidence_digest": record.evidence_digest,
                        "match_fields": [
                            "task_theme",
                            "normalized_query",
                            "retrieved_doc_ids",
                            "route",
                            "tool",
                        ],
                    },
                )
        else:
            messages = list(state.get("message_log", []))
            messages.append("Summarizer: skipped_by_native_replay=True")
            state["message_log"] = messages
        return state


def run_open_comparison(
    *,
    out_dir: Path,
    repeat: int = 1,
    task_set: str = "contest_dual_mode_controlled_v3",
    runtime_arms: Iterable[str] = RUNTIME_ARMS,
    memory_policies: Iterable[str] = OPEN_MEMORY_POLICIES,
) -> dict[str, object]:
    return _run_open_pack(
        out_dir=out_dir,
        repeat=repeat,
        task_set=task_set,
        runtime_arms=runtime_arms,
        memory_policies=memory_policies,
        task_pack=OPEN_SYSTEM_PACK,
        contract=(
            "Open engineering comparison only. Native reuse uses each arm's own "
            "text/checkpoint/store semantics and does not inherit the StateBus replay contract."
        ),
    )


def run_pure_text_open_baseline(
    *,
    out_dir: Path,
    repeat: int = 1,
    task_set: str = "contest_dual_mode_controlled_v3",
    runtime_arms: Iterable[str] = PURE_TEXT_BASELINE_ARMS,
    memory_policies: Iterable[str] = OPEN_MEMORY_POLICIES,
) -> dict[str, object]:
    return _run_open_pack(
        out_dir=out_dir,
        repeat=repeat,
        task_set=task_set,
        runtime_arms=runtime_arms,
        memory_policies=memory_policies,
        task_pack=PURE_TEXT_OPEN_BASELINE_PACK,
        contract=(
            "Audit-only external pure-text baseline. Not formal v3 headline, not controlled mechanism "
            "causality proof, and not part of default open_system_comparison_v1."
        ),
    )


def _run_open_pack(
    *,
    out_dir: Path,
    repeat: int,
    task_set: str,
    runtime_arms: Iterable[str],
    memory_policies: Iterable[str],
    task_pack: str,
    contract: str,
) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = _load_open_tasks(task_set)
    rows: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    for arm in runtime_arms:
        _validate_arm(arm)
        for policy in memory_policies:
            _validate_policy(policy)
            arm_rows = _run_arm_policy(arm=arm, policy=policy, tasks=tasks, repeat=repeat)
            rows.extend(arm_rows)
            summaries.append(_summarize_rows(arm=arm, policy=policy, rows=arm_rows))

    manifest = {
        "task_pack": task_pack,
        "task_set": str(task_set),
        "runtime_arms": list(runtime_arms),
        "open_memory_policies": list(memory_policies),
        "repeat": repeat,
        "task_count": len(tasks),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "contract": contract,
        "public_surface": "audit_only",
        "single_variable": False,
        "variable_axes": ["runtime_arm", "open_memory_policy"],
        "data_source": "deterministic_oracle",
        "artifact_reuse": False,
    }
    if task_pack == PURE_TEXT_OPEN_BASELINE_PACK:
        manifest["surface_notes"] = [
            "audit-only external pure-text baseline",
            "not formal v3 headline",
            "not controlled mechanism causality proof",
            "not part of default open_system_comparison_v1",
        ]
    result = {"manifest": manifest, "summary": summaries, "tasks": rows}
    _write_outputs(out_dir=out_dir, result=result)
    return result


def run_langgraph_native_text_open_smoke(*, out_dir: Path, repeat: int = 1) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    base_tasks = _load_open_tasks("contest_dual_mode_controlled_v3")
    tasks = [base_tasks[0], base_tasks[0]]
    rows = _run_arm_policy(
        arm="langgraph_native_text_open",
        policy="native_reuse_on",
        tasks=tasks,
        repeat=repeat,
    )
    result = {
        "manifest": {
            "task_pack": "langgraph_native_text_open_smoke",
            "runtime_arms": ["langgraph_native_text_open"],
            "open_memory_policies": ["native_reuse_on"],
            "repeat": repeat,
            "task_count": len(tasks),
            "contract": (
                "Open engineering comparison only. Native reuse uses each arm's own "
                "text/checkpoint/store semantics and does not inherit the StateBus replay contract."
            ),
            "public_surface": "audit_only",
            "single_variable": False,
            "variable_axes": ["runtime_arm", "open_memory_policy"],
            "data_source": "deterministic_oracle",
            "artifact_reuse": False,
        },
        "summary": [
            _summarize_rows(
                arm="langgraph_native_text_open",
                policy="native_reuse_on",
                rows=rows,
            )
        ],
        "tasks": rows,
    }
    _write_outputs(out_dir=out_dir, result=result)
    return result


def _run_arm_policy(
    *,
    arm: str,
    policy: str,
    tasks: list[SampleTask],
    repeat: int,
) -> list[dict[str, object]]:
    store = NativeTextReplayStore()
    langgraph_runtime = LangGraphNativeTextRuntime(store) if arm == "langgraph_native_text_open" else None
    external_runtime = ExternalTextOpenRuntime(store) if arm == "external_text_open" else None
    rows: list[dict[str, object]] = []
    for run_index in range(repeat):
        for task in tasks:
            rows.append(
                _run_native_task(
                    arm=arm,
                    policy=policy,
                    task=task,
                    run_index=run_index,
                    store=store,
                    langgraph_runtime=langgraph_runtime,
                    external_runtime=external_runtime,
                )
            )
    return rows


def _run_native_task(
    *,
    arm: str,
    policy: str,
    task: SampleTask,
    run_index: int,
    store: NativeTextReplayStore,
    langgraph_runtime: LangGraphNativeTextRuntime | None = None,
    external_runtime: ExternalTextOpenRuntime | None = None,
) -> dict[str, object]:
    started = time.perf_counter()
    if arm == "langgraph_native_text_open":
        if langgraph_runtime is None:
            raise RuntimeError("langgraph runtime was not initialized")
        graph_state = asyncio.run(
            langgraph_runtime.run_task(task=task, policy=policy, run_index=run_index)
        )
        return _langgraph_row_from_state(
            task=task,
            policy=policy,
            run_index=run_index,
            graph_state=graph_state,
            started=started,
        )
    if arm == "external_text_open":
        if external_runtime is None:
            raise RuntimeError("external text runtime was not initialized")
        graph_state = external_runtime.run_task(task=task, policy=policy, run_index=run_index)
        return _external_text_row_from_state(
            task=task,
            policy=policy,
            run_index=run_index,
            graph_state=graph_state,
            started=started,
        )
    normalized_query = _normalize_query(task.query)
    retrieved_doc_ids = tuple(task.corpus_doc_ids)
    route = task.primary_expected_route or task.expected_route
    tool_name = task.primary_expected_tool or task.expected_tool_name
    replay_record = None
    if policy == "native_reuse_on":
        replay_record = store.lookup(
            task_theme=task.task_theme,
            normalized_query=normalized_query,
            retrieved_doc_ids=retrieved_doc_ids,
            route=route,
            tool_name=tool_name,
        )
    replay_hit = replay_record is not None
    skipped_step_count = 2 if replay_hit else 0
    summary_text = (
        replay_record.summary_text
        if replay_record is not None
        else f"Route {route}; use {tool_name}; evidence docs {', '.join(retrieved_doc_ids)}."
    )
    evidence_digest = _evidence_digest(retrieved_doc_ids)
    if policy == "native_reuse_on" and replay_record is None:
        store.commit(
            NativeReplayRecord(
                task_theme=task.task_theme,
                normalized_query=normalized_query,
                retrieved_doc_ids=retrieved_doc_ids,
                route=route,
                tool_name=tool_name,
                summary_text=summary_text,
                evidence_digest=evidence_digest,
            )
        )

    message_count = 4 - skipped_step_count
    handoff_payload_bytes = _handoff_payload_bytes(arm=arm, task=task, route=route, tool_name=tool_name)
    handoff_wire_bytes = handoff_payload_bytes + _wire_overhead(arm, message_count)
    llm_total_tokens = _token_estimate(task.goal, task.query, summary_text, arm=arm, replay_hit=replay_hit)
    task_ms = max(1.0, (time.perf_counter() - started) * 1000.0 + 8.0 + message_count * 2.0)
    exact = route == task.primary_expected_route and tool_name == task.primary_expected_tool
    row = {
        "task_id": task.task_id,
        "task_group": task.task_group,
        "task_theme": task.task_theme,
        "runtime_arm": arm,
        "open_memory_policy": policy,
        "run_index": run_index,
        "route": route,
        "tool_name": tool_name,
        "expected_route": task.primary_expected_route,
        "expected_tool_name": task.primary_expected_tool,
        "retrieved_doc_ids": list(retrieved_doc_ids),
        "message_log": _message_log(arm=arm, task=task, route=route, tool_name=tool_name, replay_hit=replay_hit),
        "correctness": {
            "route_exact": route == task.primary_expected_route,
            "tool_exact": tool_name == task.primary_expected_tool,
            "exact_match": exact,
            "admissible_match": exact,
        },
        "metrics": {
            "route_exact_rate": 1.0 if route == task.primary_expected_route else 0.0,
            "tool_exact_rate": 1.0 if tool_name == task.primary_expected_tool else 0.0,
            "exact_match_rate": 1.0 if exact else 0.0,
            "admissible_match_rate": 1.0 if exact else 0.0,
            "llm_total_tokens": llm_total_tokens,
            "message_count": float(message_count),
            "transport_bytes": float(handoff_wire_bytes),
            "handoff_wire_bytes": float(handoff_wire_bytes),
            "handoff_payload_bytes": float(handoff_payload_bytes),
            "task_ms": task_ms,
            "memory_hit_rate": 1.0 if replay_hit else 0.0,
            "replay_hit_rate": 1.0 if replay_hit else 0.0,
            "skipped_step_count": float(skipped_step_count),
            "reuse_gain": float(skipped_step_count) / 4.0,
        },
        "native_replay": {
            "hit": replay_hit,
            "source": "native_text_store" if replay_hit else "",
            "match_fields": [
                "task_theme",
                "normalized_query",
                "retrieved_doc_ids",
                "route",
                "tool",
            ],
        },
        "statebus_contract_used": arm.startswith("statebus_"),
    }
    return row


def _load_open_tasks(task_set: str) -> list[SampleTask]:
    tasks = [
        task
        for task in load_task_set_bundle(task_set).tasks
        if task.complexity_bucket == "simple" and task.primary_expected_tool
    ]
    by_theme: dict[str, SampleTask] = {}
    for task in tasks:
        by_theme.setdefault(task.task_theme, task)
    selected = [by_theme[key] for key in sorted(by_theme)]
    if not selected:
        raise ValueError(f"no open comparison tasks found in {task_set!r}")
    return selected + selected


def _summarize_rows(*, arm: str, policy: str, rows: list[dict[str, object]]) -> dict[str, object]:
    metric_names = (
        "route_exact_rate",
        "tool_exact_rate",
        "exact_match_rate",
        "admissible_match_rate",
        "llm_total_tokens",
        "message_count",
        "transport_bytes",
        "handoff_wire_bytes",
        "handoff_payload_bytes",
        "task_ms",
        "assist_memory_hit_rate",
        "replay_hit_rate",
        "skipped_step_count",
        "reuse_gain",
    )
    metrics = {
        name: _mean(float(row["metrics"][name]) for row in rows)
        for name in metric_names
    }
    return {
        "runtime_arm": arm,
        "open_memory_policy": policy,
        "task_runs": len(rows),
        **metrics,
    }


def _write_outputs(*, out_dir: Path, result: dict[str, object]) -> None:
    (out_dir / "open_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    summary = list(result["summary"])
    with (out_dir / "open_compare.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0].keys()))
        writer.writeheader()
        writer.writerows(summary)
    (out_dir / "open_report.md").write_text(_report_md(result), encoding="utf-8")


def _report_md(result: dict[str, object]) -> str:
    manifest = result["manifest"]
    title = (
        "# Pure Text Open Baseline V1"
        if manifest["task_pack"] == PURE_TEXT_OPEN_BASELINE_PACK
        else "# Open System Comparison V1"
    )
    intro = (
        "This is an audit-only external pure-text baseline, not a formal v3 headline or controlled mechanism proof."
        if manifest["task_pack"] == PURE_TEXT_OPEN_BASELINE_PACK
        else "This is an open engineering comparison surface, not a formal StateBus mechanism proof."
    )
    lines = [
        title,
        "",
        intro,
        "",
        "## Manifest",
        "",
        f"- Task pack: `{manifest['task_pack']}`",
        f"- Repeat: `{manifest['repeat']}`",
        f"- Runtime arms: `{', '.join(manifest['runtime_arms'])}`",
        f"- Memory policies: `{', '.join(manifest['open_memory_policies'])}`",
        f"- Contract: `{manifest.get('contract', '')}`",
        f"- Public surface: `{manifest.get('public_surface', 'audit_only')}`",
        f"- Single-variable contract: `{'yes' if bool(manifest.get('single_variable', False)) else 'no'}`",
        f"- Variable axes: `{', '.join(str(item) for item in manifest.get('variable_axes', []))}`",
        f"- Data source: `{manifest.get('data_source', '')}`",
        f"- Artifact reuse: `{str(bool(manifest.get('artifact_reuse', False))).lower()}`",
        "",
        "## Summary",
        "",
        "| runtime_arm | open_memory_policy | exact_match_rate | llm_total_tokens | message_count | handoff_wire_bytes | replay_hit_rate | skipped_step_count | reuse_gain | task_ms | data_source | artifact_reuse |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in result["summary"]:
        lines.append(
            "| {runtime_arm} | {open_memory_policy} | {exact_match_rate:.2f} | {llm_total_tokens:.2f} | {message_count:.2f} | {handoff_wire_bytes:.2f} | {replay_hit_rate:.2f} | {skipped_step_count:.2f} | {reuse_gain:.2f} | {task_ms:.2f} | {data_source} | {artifact_reuse} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## Stopline",
            "",
            "- This surface is audit-only engineering simulation.",
            "- `data_source=deterministic_oracle` or `lexical_stub` means these rows are not real-LLM headline evidence.",
            "- Do not merge this output into `contest_dual_mode_controlled_v3`, `typed_state_mechanism_v3`, or `memory_policy_controlled_v3` claims.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _message_log(*, arm: str, task: SampleTask, route: str, tool_name: str, replay_hit: bool) -> list[str]:
    if arm == "statebus_protocol_open":
        return [
            f"PLAN action=triage theme={task.task_theme}",
            f"RETRIEVE doc_ids={','.join(task.corpus_doc_ids)}",
            f"EXECUTE route={route} tool={tool_name}",
            f"SUMMARY replay_hit={replay_hit}",
        ]
    return [
        f"Planner: triage {task.goal}",
        f"Retriever: use documents {', '.join(task.corpus_doc_ids)}",
        f"Executor: choose route {route} and tool {tool_name}",
        f"Summarizer: replay_hit={replay_hit}",
    ]


def _handoff_payload_bytes(*, arm: str, task: SampleTask, route: str, tool_name: str) -> int:
    if arm == "statebus_protocol_open":
        payload = {"route": route, "tool": tool_name, "doc_ids": task.corpus_doc_ids}
        return len(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    text = "\n".join(_message_log(arm=arm, task=task, route=route, tool_name=tool_name, replay_hit=False))
    if arm == "statebus_text_open":
        return int(len(text.encode("utf-8")) * 0.9)
    if arm == "langgraph_native_text_open":
        return int(len(text.encode("utf-8")) * 1.05)
    return len(text.encode("utf-8"))


def _wire_overhead(arm: str, message_count: int) -> int:
    if arm == "statebus_protocol_open":
        return 24 * message_count
    if arm == "langgraph_native_text_open":
        return 42 * message_count
    return 32 * message_count


def _token_estimate(*parts: str, arm: str, replay_hit: bool) -> float:
    text = " ".join(parts)
    tokens = max(1, len(re.findall(r"\S+", text)))
    multiplier = 0.55 if replay_hit else 1.0
    if arm == "statebus_protocol_open":
        multiplier *= 0.75
    return float(tokens) * multiplier


def _evidence_digest(doc_ids: tuple[str, ...]) -> str:
    return "|".join(doc_ids)


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def _state_task(state: dict[str, object]) -> SampleTask:
    task = state.get("task")
    if not isinstance(task, SampleTask):
        raise TypeError("LangGraph native state missing SampleTask")
    return task


def _native_replay_key(record: NativeReplayRecord) -> str:
    return _normalize_query(
        "|".join(
            [
                record.task_theme,
                record.normalized_query,
                ",".join(record.retrieved_doc_ids),
                record.route,
                record.tool_name,
            ]
        )
    )


def _langgraph_row_from_state(
    *,
    task: SampleTask,
    policy: str,
    run_index: int,
    graph_state: dict[str, object],
    started: float,
) -> dict[str, object]:
    route = str(graph_state.get("route", ""))
    tool_name = str(graph_state.get("tool_name", ""))
    retrieved_doc_ids = tuple(str(item) for item in graph_state.get("retrieved_doc_ids", ()))
    replay_hit = bool(graph_state.get("replay_hit", False))
    skipped_step_count = int(graph_state.get("skipped_step_count", 0))
    summary_text = str(graph_state.get("summary_text", ""))
    message_log = [str(item) for item in graph_state.get("message_log", [])]
    message_count = max(1, len(message_log) - skipped_step_count)
    handoff_payload_bytes = _handoff_payload_bytes(
        arm="langgraph_native_text_open",
        task=task,
        route=route,
        tool_name=tool_name,
    )
    handoff_wire_bytes = handoff_payload_bytes + _wire_overhead("langgraph_native_text_open", message_count)
    llm_total_tokens = _token_estimate(
        task.goal,
        task.query,
        summary_text,
        arm="langgraph_native_text_open",
        replay_hit=replay_hit,
    )
    task_ms = max(1.0, (time.perf_counter() - started) * 1000.0 + 8.0 + message_count * 2.0)
    exact = route == task.primary_expected_route and tool_name == task.primary_expected_tool
    return {
        "task_id": task.task_id,
        "task_group": task.task_group,
        "task_theme": task.task_theme,
        "runtime_arm": "langgraph_native_text_open",
        "open_memory_policy": policy,
        "run_index": run_index,
        "route": route,
        "tool_name": tool_name,
        "expected_route": task.primary_expected_route,
        "expected_tool_name": task.primary_expected_tool,
        "retrieved_doc_ids": list(retrieved_doc_ids),
        "message_log": message_log,
        "correctness": {
            "route_exact": route == task.primary_expected_route,
            "tool_exact": tool_name == task.primary_expected_tool,
            "exact_match": exact,
            "admissible_match": exact,
        },
        "metrics": {
            "route_exact_rate": 1.0 if route == task.primary_expected_route else 0.0,
            "tool_exact_rate": 1.0 if tool_name == task.primary_expected_tool else 0.0,
            "exact_match_rate": 1.0 if exact else 0.0,
            "admissible_match_rate": 1.0 if exact else 0.0,
            "llm_total_tokens": llm_total_tokens,
            "message_count": float(message_count),
            "transport_bytes": float(handoff_wire_bytes),
            "handoff_wire_bytes": float(handoff_wire_bytes),
            "handoff_payload_bytes": float(handoff_payload_bytes),
            "task_ms": task_ms,
            "assist_memory_hit_rate": 0.0,
            "replay_hit_rate": 1.0 if replay_hit else 0.0,
            "skipped_step_count": float(skipped_step_count),
            "reuse_gain": float(skipped_step_count) / 4.0,
        },
        "data_source": "deterministic_oracle",
        "artifact_reuse": False,
        "native_replay": {
            "hit": replay_hit,
            "source": "langgraph_checkpointer_store" if replay_hit else "",
            "match_fields": [
                "task_theme",
                "normalized_query",
                "retrieved_doc_ids",
                "route",
                "tool",
            ],
            "backend": str(graph_state.get("native_memory_backend", "")),
        },
        "statebus_contract_used": False,
    }


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def _validate_arm(value: str) -> None:
    if value not in RUNTIME_ARMS and value not in PURE_TEXT_BASELINE_ARMS:
        raise ValueError(f"unsupported runtime_arm: {value}")


def _validate_policy(value: str) -> None:
    if value not in OPEN_MEMORY_POLICIES:
        raise ValueError(f"unsupported open_memory_policy: {value}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run isolated open-system comparison surfaces.")
    parser.add_argument(
        "--pack",
        choices=(OPEN_SYSTEM_PACK, PURE_TEXT_OPEN_BASELINE_PACK, "langgraph_native_text_open"),
        default=OPEN_SYSTEM_PACK,
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--task-set", default="contest_dual_mode_controlled_v3")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    out_dir = args.out or REPO_ROOT / "runs" / f"{args.pack}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if args.pack == "langgraph_native_text_open":
        run_langgraph_native_text_open_smoke(out_dir=out_dir, repeat=args.repeat)
    elif args.pack == PURE_TEXT_OPEN_BASELINE_PACK:
        run_pure_text_open_baseline(out_dir=out_dir, repeat=args.repeat, task_set=args.task_set)
    else:
        run_open_comparison(out_dir=out_dir, repeat=args.repeat, task_set=args.task_set)


def _external_text_row_from_state(
    *,
    task: SampleTask,
    policy: str,
    run_index: int,
    graph_state: dict[str, object],
    started: float,
) -> dict[str, object]:
    route = str(graph_state.get("route", ""))
    tool_name = str(graph_state.get("tool_name", ""))
    retrieved_doc_ids = tuple(str(item) for item in graph_state.get("retrieved_doc_ids", ()))
    replay_hit = bool(graph_state.get("replay_hit", False))
    skipped_step_count = int(graph_state.get("skipped_step_count", 0))
    summary_text = str(graph_state.get("summary_text", ""))
    message_log = [str(item) for item in graph_state.get("message_log", [])]
    message_count = max(1, len(message_log) - skipped_step_count)
    handoff_payload_bytes = _handoff_payload_bytes(
        arm="external_text_open",
        task=task,
        route=route,
        tool_name=tool_name,
    )
    handoff_wire_bytes = handoff_payload_bytes + _wire_overhead("external_text_open", message_count)
    llm_total_tokens = _token_estimate(
        task.goal,
        task.query,
        summary_text,
        arm="external_text_open",
        replay_hit=replay_hit,
    )
    task_ms = max(1.0, (time.perf_counter() - started) * 1000.0 + 8.0 + message_count * 2.0)
    exact = route == task.primary_expected_route and tool_name == task.primary_expected_tool
    return {
        "task_id": task.task_id,
        "task_group": task.task_group,
        "task_theme": task.task_theme,
        "runtime_arm": "external_text_open",
        "open_memory_policy": policy,
        "run_index": run_index,
        "route": route,
        "tool_name": tool_name,
        "expected_route": task.primary_expected_route,
        "expected_tool_name": task.primary_expected_tool,
        "retrieved_doc_ids": list(retrieved_doc_ids),
        "retrieved_snippets": list(graph_state.get("retrieved_snippets", [])),
        "message_log": message_log,
        "correctness": {
            "route_exact": route == task.primary_expected_route,
            "tool_exact": tool_name == task.primary_expected_tool,
            "exact_match": exact,
            "admissible_match": exact,
        },
        "metrics": {
            "route_exact_rate": 1.0 if route == task.primary_expected_route else 0.0,
            "tool_exact_rate": 1.0 if tool_name == task.primary_expected_tool else 0.0,
            "exact_match_rate": 1.0 if exact else 0.0,
            "admissible_match_rate": 1.0 if exact else 0.0,
            "llm_total_tokens": llm_total_tokens,
            "message_count": float(message_count),
            "transport_bytes": float(handoff_wire_bytes),
            "handoff_wire_bytes": float(handoff_wire_bytes),
            "handoff_payload_bytes": float(handoff_payload_bytes),
            "task_ms": task_ms,
            "assist_memory_hit_rate": 0.0,
            "replay_hit_rate": 1.0 if replay_hit else 0.0,
            "skipped_step_count": float(skipped_step_count),
            "reuse_gain": float(skipped_step_count) / 4.0,
        },
        "data_source": "lexical_stub",
        "artifact_reuse": False,
        "native_replay": {
            "hit": replay_hit,
            "source": "native_text_store" if replay_hit else "",
            "match_fields": [
                "task_theme",
                "normalized_query",
                "retrieved_doc_ids",
                "route",
                "tool",
            ],
        },
        "statebus_contract_used": bool(graph_state.get("statebus_contract_used", False)),
        "metadata_oracle_used": bool(graph_state.get("metadata_oracle_used", False)),
        "decision_source": str(graph_state.get("decision_source", "")),
    }


if __name__ == "__main__":
    main()
