from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Callable

from agents.sample_agents import build_sample_agents
from memory.store import (
    DEFAULT_EMBEDDING_MODEL_PATH,
    EmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
)
from runtime.llm import LLMClient, LLMConfig, build_llm_client
from runtime.orchestrator import Orchestrator, RunSession
from statepool.store import StatePoolConfig
from tasks.sample_tasks import DEFAULT_TASK_SET, SampleTask, load_task_set

METRIC_FIELDS = (
    "message_count",
    "text_chars",
    "text_bytes",
    "protocol_bytes",
    "mmap_state_ref_count",
    "mmap_state_bytes",
    "shared_memory_state_ref_count",
    "shared_memory_state_bytes",
    "state_ref_count",
    "state_bytes",
    "memory_hits",
    "memory_query_count",
    "memory_hit_task_count",
    "planned_step_count",
    "skipped_step_count",
    "llm_request_count",
    "llm_prompt_tokens",
    "llm_completion_tokens",
    "llm_total_tokens",
    "task_ms",
)

COUNTER_FIELDS = (
    "message_count",
    "text_chars",
    "text_bytes",
    "protocol_bytes",
)


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _task_sort_key(task: SampleTask) -> tuple[str, int, str]:
    return (task.task_group, task.task_order, task.task_id)


def _control_metric_key(mode: str) -> str:
    return "text_bytes" if mode == "text" else "protocol_bytes"


def _relative_reduction(current: float, baseline: float) -> float:
    if baseline <= 0.0:
        return 0.0
    return 1.0 - (current / baseline)


def _zero_metric_row() -> dict[str, float]:
    payload = {field: 0.0 for field in METRIC_FIELDS}
    payload["memory_hit_rate"] = 0.0
    payload["reuse_gain"] = 0.0
    return payload


def _zero_counter_row() -> dict[str, float]:
    return {field: 0.0 for field in COUNTER_FIELDS}


def _sum_metric_rows(metric_rows: list[dict[str, object]]) -> dict[str, float]:
    if not metric_rows:
        return _zero_metric_row()
    totals = {
        field: float(sum(float(row.get(field, 0.0)) for row in metric_rows))
        for field in METRIC_FIELDS
    }
    totals["memory_hit_rate"] = (
        totals["memory_hit_task_count"] / totals["memory_query_count"]
        if totals["memory_query_count"] > 0.0
        else 0.0
    )
    totals["reuse_gain"] = (
        totals["skipped_step_count"] / totals["planned_step_count"]
        if totals["planned_step_count"] > 0.0
        else 0.0
    )
    return totals


def _average_metric_rows(metric_rows: list[dict[str, object]]) -> dict[str, float]:
    if not metric_rows:
        return _zero_metric_row()
    averaged = {
        field: float(mean(float(row.get(field, 0.0)) for row in metric_rows))
        for field in METRIC_FIELDS
    }
    averaged["memory_hit_rate"] = (
        averaged["memory_hit_task_count"] / averaged["memory_query_count"]
        if averaged["memory_query_count"] > 0.0
        else 0.0
    )
    averaged["reuse_gain"] = (
        averaged["skipped_step_count"] / averaged["planned_step_count"]
        if averaged["planned_step_count"] > 0.0
        else 0.0
    )
    return averaged


def _sum_counter_rows(counter_rows: list[dict[str, object]]) -> dict[str, float]:
    if not counter_rows:
        return _zero_counter_row()
    return {
        field: float(sum(float(row.get(field, 0.0)) for row in counter_rows))
        for field in COUNTER_FIELDS
    }


def _average_counter_rows(counter_rows: list[dict[str, object]]) -> dict[str, float]:
    if not counter_rows:
        return _zero_counter_row()
    return {
        field: float(mean(float(row.get(field, 0.0)) for row in counter_rows))
        for field in COUNTER_FIELDS
    }


def _combine_setup_and_steady(
    setup: dict[str, float],
    steady: dict[str, float],
) -> dict[str, float]:
    combined = dict(steady)
    for field in COUNTER_FIELDS:
        combined[field] = float(setup.get(field, 0.0)) + float(steady.get(field, 0.0))
    combined["setup_message_count"] = float(setup["message_count"])
    combined["setup_text_chars"] = float(setup["text_chars"])
    combined["setup_text_bytes"] = float(setup["text_bytes"])
    combined["setup_protocol_bytes"] = float(setup["protocol_bytes"])
    combined["steady_state_message_count"] = float(steady["message_count"])
    combined["steady_state_text_chars"] = float(steady["text_chars"])
    combined["steady_state_text_bytes"] = float(steady["text_bytes"])
    combined["steady_state_protocol_bytes"] = float(steady["protocol_bytes"])
    return combined


def _merge_reuse_summary(
    target: dict[str, float],
    rows: list[dict[str, object]],
    mode: str,
) -> dict[str, float]:
    target.update(_summarize_reuse_rows(rows, mode))
    return target


def _build_run_session(mode: str) -> RunSession:
    return RunSession(mode=mode)


def _mode_order_for_run(modes: tuple[str, ...], run_index: int) -> tuple[str, ...]:
    if run_index % 2 == 0:
        return modes
    return tuple(reversed(modes))


async def _run_mode_once(
    *,
    mode: str,
    run_index: int,
    root: Path,
    tasks: list[SampleTask],
    embedder: EmbeddingProvider,
    llm_client: LLMClient,
    statepool_config: StatePoolConfig,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    session = _build_run_session(mode)
    orchestrator = Orchestrator(build_sample_agents(llm_client=llm_client))
    ordered_tasks = sorted(tasks, key=_task_sort_key)
    task_runs: list[dict[str, object]] = []
    group_db_paths = {
        task.task_group: root / f"{task.task_group}.sqlite3" for task in ordered_tasks
    }
    run_status = "completed"
    run_error: str | None = None
    for task_index, task in enumerate(ordered_tasks, start=1):
        ctx = Orchestrator.create_context(
            mode=mode,
            task_id=task.task_id,
            task_group=task.task_group,
            task_theme=task.task_theme,
            state_root=root / task.task_group / task.task_id,
            memory_db_path=group_db_paths[task.task_group],
            embedder=embedder,
            session=session,
            statepool_config=statepool_config,
        )
        task_payload: dict[str, object]
        try:
            await orchestrator.run_task(task, ctx)
            task_payload = {
                "task_id": task.task_id,
                "task_group": task.task_group,
                "task_order": task.task_order,
                "task_theme": task.task_theme,
                "goal": task.goal,
                "memory_db_path": str(group_db_paths[task.task_group]),
                "expected_reuse": task.expected_reuse,
                "status": "completed",
                "error": None,
                "metrics": ctx.metrics.to_dict(),
                "memory_hits": [hit.memory_id for hit in ctx.memory_hits],
                "reuse": {
                    "applied": ctx.reuse_hit is not None,
                    "memory_id": None if ctx.reuse_hit is None else ctx.reuse_hit.memory_id,
                    "reuse_source": None if ctx.reuse_hit is None else ctx.reuse_hit.reuse_source,
                    "skipped_step_ids": list(ctx.pruned_step_ids),
                },
                "reuse_validation": {
                    "expected_reuse": task.expected_reuse,
                    "matched_expectation": (ctx.reuse_hit is not None) == task.expected_reuse,
                },
                "state_refs": {
                    state_id: {
                        "kind": ref.kind,
                        "storage": ref.storage,
                        "handle": ref.handle,
                        "length": ref.length,
                        "metadata": dict(ref.metadata),
                    }
                    for state_id, ref in ctx.state_refs.items()
                },
                "results": {
                    step_id: {
                        "success": result.success,
                        "skipped": result.skipped,
                        "reused_from_memory_id": result.reused_from_memory_id,
                        "has_memory_commit": result.memory_commit is not None,
                        "payload": _sanitize_payload(result.payload),
                    }
                    for step_id, result in ctx.results.items()
                },
            }
            if progress_callback is not None:
                progress_callback(
                    {
                        "mode": mode,
                        "run_index": run_index,
                        "task_index": task_index,
                        "task_count": len(ordered_tasks),
                        "task_id": task.task_id,
                        "status": "completed",
                        "llm_total_tokens": ctx.metrics.llm_total_tokens,
                        "task_ms": ctx.metrics.task_ms,
                    }
                )
        except Exception as exc:
            run_status = "failed"
            run_error = f"{type(exc).__name__}: {exc}"
            task_payload = {
                "task_id": task.task_id,
                "task_group": task.task_group,
                "task_order": task.task_order,
                "task_theme": task.task_theme,
                "goal": task.goal,
                "memory_db_path": str(group_db_paths[task.task_group]),
                "expected_reuse": task.expected_reuse,
                "status": "failed",
                "error": run_error,
                "metrics": ctx.metrics.to_dict(),
                "memory_hits": [hit.memory_id for hit in ctx.memory_hits],
                "reuse": {
                    "applied": ctx.reuse_hit is not None,
                    "memory_id": None if ctx.reuse_hit is None else ctx.reuse_hit.memory_id,
                    "reuse_source": None if ctx.reuse_hit is None else ctx.reuse_hit.reuse_source,
                    "skipped_step_ids": list(ctx.pruned_step_ids),
                },
                "reuse_validation": {
                    "expected_reuse": task.expected_reuse,
                    "matched_expectation": False,
                },
                "state_refs": {
                    state_id: {
                        "kind": ref.kind,
                        "storage": ref.storage,
                        "handle": ref.handle,
                        "length": ref.length,
                        "metadata": dict(ref.metadata),
                    }
                    for state_id, ref in ctx.state_refs.items()
                },
                "results": {},
            }
            if progress_callback is not None:
                progress_callback(
                    {
                        "mode": mode,
                        "run_index": run_index,
                        "task_index": task_index,
                        "task_count": len(ordered_tasks),
                        "task_id": task.task_id,
                        "status": "failed",
                        "error": run_error,
                        "llm_total_tokens": ctx.metrics.llm_total_tokens,
                        "task_ms": ctx.metrics.task_ms,
                    }
                )
            task_runs.append(task_payload)
            ctx.memory_store.close()
            break
        finally:
            if not ctx.memory_store.conn is None:
                try:
                    ctx.memory_store.close()
                except Exception:
                    pass
        task_runs.append(task_payload)

    _annotate_reuse_effects(task_runs, mode)
    setup_metrics = session.setup_metrics()
    steady_rows = [task_run["metrics"] for task_run in task_runs]
    steady_aggregate = _merge_reuse_summary(_sum_metric_rows(steady_rows), task_runs, mode)
    aggregate = _merge_reuse_summary(
        _combine_setup_and_steady(setup_metrics, steady_aggregate),
        task_runs,
        mode,
    )
    message_breakdown = session.message_breakdown_rows()
    session.cleanup()
    return {
        "mode": mode,
        "run_index": run_index,
        "status": run_status,
        "error": run_error,
        "memory_db_paths": {
            group: str(path) for group, path in sorted(group_db_paths.items(), key=lambda item: item[0])
        },
        "setup_metrics": setup_metrics,
        "steady_state_aggregate": steady_aggregate,
        "aggregate": aggregate,
        "message_breakdown": message_breakdown,
        "task_groups": _aggregate_task_groups(task_runs),
        "tasks": task_runs,
    }


def _annotate_reuse_effects(task_runs: list[dict[str, object]], mode: str) -> None:
    control_key = _control_metric_key(mode)
    grouped: dict[str, list[dict[str, object]]] = {}
    for task_run in task_runs:
        if task_run["status"] != "completed":
            continue
        grouped.setdefault(str(task_run["task_group"]), []).append(task_run)
    for task_group in sorted(grouped):
        rows = sorted(grouped[task_group], key=lambda item: (int(item["task_order"]), str(item["task_id"])))
        baseline = rows[0]
        baseline_metrics = baseline["metrics"]
        baseline_control = float(baseline_metrics[control_key])
        baseline_tokens = float(baseline_metrics["llm_total_tokens"])
        baseline_task_ms = float(baseline_metrics["task_ms"])
        for row in rows:
            metrics = row["metrics"]
            applied = bool(row["reuse"]["applied"])
            row["reuse_effect"] = {
                "baseline_task_id": str(baseline["task_id"]),
                "applied": applied,
                "control_bytes_reduction_vs_cold": _relative_reduction(
                    float(metrics[control_key]),
                    baseline_control,
                )
                if applied
                else 0.0,
                "llm_total_tokens_reduction_vs_cold": _relative_reduction(
                    float(metrics["llm_total_tokens"]),
                    baseline_tokens,
                )
                if applied
                else 0.0,
                "task_ms_reduction_vs_cold": _relative_reduction(
                    float(metrics["task_ms"]),
                    baseline_task_ms,
                )
                if applied
                else 0.0,
            }
    for task_run in task_runs:
        task_run.setdefault(
            "reuse_effect",
            {
                "baseline_task_id": str(task_run["task_id"]),
                "applied": False,
                "control_bytes_reduction_vs_cold": 0.0,
                "llm_total_tokens_reduction_vs_cold": 0.0,
                "task_ms_reduction_vs_cold": 0.0,
            },
        )


def _summarize_reuse_rows(
    rows: list[dict[str, object]],
    mode: str,
) -> dict[str, float]:
    del mode
    completed_rows = [row for row in rows if row["status"] == "completed"]
    if not completed_rows:
        return {
            "reuse_apply_rate": 0.0,
            "expectation_match_rate": 0.0,
            "control_bytes_reduction_vs_cold": 0.0,
            "llm_total_tokens_reduction_vs_cold": 0.0,
            "task_ms_reduction_vs_cold": 0.0,
        }
    return {
        "reuse_apply_rate": float(
            mean(1.0 if bool(row["reuse"]["applied"]) else 0.0 for row in completed_rows)
        ),
        "expectation_match_rate": float(
            mean(
                1.0 if bool(row["reuse_validation"]["matched_expectation"]) else 0.0
                for row in completed_rows
            )
        ),
        "control_bytes_reduction_vs_cold": float(
            mean(float(row["reuse_effect"]["control_bytes_reduction_vs_cold"]) for row in completed_rows)
        ),
        "llm_total_tokens_reduction_vs_cold": float(
            mean(float(row["reuse_effect"]["llm_total_tokens_reduction_vs_cold"]) for row in completed_rows)
        ),
        "task_ms_reduction_vs_cold": float(
            mean(float(row["reuse_effect"]["task_ms_reduction_vs_cold"]) for row in completed_rows)
        ),
    }


def _aggregate_task_groups(task_runs: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for task_run in task_runs:
        grouped.setdefault(str(task_run["task_group"]), []).append(task_run)
    summaries: list[dict[str, object]] = []
    for task_group in sorted(grouped):
        rows = sorted(grouped[task_group], key=lambda item: (int(item["task_order"]), str(item["task_id"])))
        summaries.append(
            {
                "task_group": task_group,
                "task_ids": [str(item["task_id"]) for item in rows],
                "aggregate": _merge_reuse_summary(
                    _sum_metric_rows([item["metrics"] for item in rows]),
                    rows,
                    "protocol",
                ),
            }
        )
    return summaries


def _aggregate_message_breakdown(runs: list[dict[str, object]]) -> list[dict[str, float | str]]:
    grouped: dict[str, dict[str, float]] = {}
    for run in runs:
        if run["status"] != "completed":
            continue
        for row in run["message_breakdown"]:
            name = str(row["message_type"])
            entry = grouped.setdefault(
                name,
                {
                    "message_count": 0.0,
                    "protocol_bytes": 0.0,
                    "text_bytes": 0.0,
                    "setup_message_count": 0.0,
                    "setup_protocol_bytes": 0.0,
                    "setup_text_bytes": 0.0,
                    "steady_message_count": 0.0,
                    "steady_protocol_bytes": 0.0,
                    "steady_text_bytes": 0.0,
                },
            )
            for key in entry:
                entry[key] += float(row[key])
    rows: list[dict[str, float | str]] = []
    for name in sorted(grouped):
        entry = grouped[name]
        rows.append(
            {
                "message_type": name,
                **entry,
                "delta": entry["protocol_bytes"] - entry["text_bytes"],
            }
        )
    return rows


def _aggregate_mode_runs(runs: list[dict[str, object]]) -> dict[str, object]:
    completed_runs = [run for run in runs if run["status"] == "completed"]
    failures = [
        {
            "run_index": run["run_index"],
            "error": run["error"],
        }
        for run in runs
        if run["status"] != "completed"
    ]
    if not completed_runs:
        return {
            "run_count": 0,
            "failure_count": len(failures),
            "failures": failures,
            "aggregate": _combine_setup_and_steady(_zero_counter_row(), _zero_metric_row()),
            "setup": _zero_counter_row(),
            "steady_state": _zero_metric_row(),
            "task_groups": [],
            "tasks": [],
            "message_breakdown": [],
            "stability": {},
        }

    task_order_lookup = [
        (str(task["task_id"]), str(task["task_group"]), int(task["task_order"]))
        for task in completed_runs[0]["tasks"]
        if task["status"] == "completed"
    ]
    group_lookup = [str(group["task_group"]) for group in completed_runs[0]["task_groups"]]
    task_summaries = []
    for task_id, task_group, task_order in task_order_lookup:
        matching = [
            task_run
            for run in completed_runs
            for task_run in run["tasks"]
            if task_run["task_id"] == task_id and task_run["status"] == "completed"
        ]
        task_summaries.append(
            {
                "task_id": task_id,
                "task_group": task_group,
                "task_order": task_order,
                **_average_metric_rows([item["metrics"] for item in matching]),
                **_summarize_reuse_rows(matching, str(completed_runs[0]["mode"])),
                "baseline_task_id": str(matching[0]["reuse_effect"]["baseline_task_id"]),
            }
        )
    group_summaries = []
    for task_group in group_lookup:
        matching = [
            group_summary
            for run in completed_runs
            for group_summary in run["task_groups"]
            if group_summary["task_group"] == task_group
        ]
        task_rows = [
            task_run
            for run in completed_runs
            for task_run in run["tasks"]
            if task_run["task_group"] == task_group and task_run["status"] == "completed"
        ]
        group_summaries.append(
            {
                "task_group": task_group,
                "task_ids": list(matching[0]["task_ids"]),
                **_average_metric_rows([item["aggregate"] for item in matching]),
                **_summarize_reuse_rows(task_rows, str(completed_runs[0]["mode"])),
                "baseline_task_id": str(matching[0]["task_ids"][0]),
            }
        )
    setup = _average_counter_rows([run["setup_metrics"] for run in completed_runs])
    steady_state = _merge_reuse_summary(
        _average_metric_rows([run["steady_state_aggregate"] for run in completed_runs]),
        [task_run for run in completed_runs for task_run in run["tasks"]],
        str(completed_runs[0]["mode"]),
    )
    aggregate = _merge_reuse_summary(
        _combine_setup_and_steady(setup, steady_state),
        [task_run for run in completed_runs for task_run in run["tasks"]],
        str(completed_runs[0]["mode"]),
    )
    return {
        "run_count": len(completed_runs),
        "failure_count": len(failures),
        "failures": failures,
        "aggregate": aggregate,
        "setup": setup,
        "steady_state": steady_state,
        "task_groups": group_summaries,
        "tasks": task_summaries,
        "message_breakdown": _aggregate_message_breakdown(completed_runs),
        "stability": _build_stability_summary(completed_runs),
    }


def _build_stability_summary(runs: list[dict[str, object]]) -> dict[str, dict[str, float]]:
    mode = str(runs[0]["mode"])
    steady_key = _control_metric_key(mode)
    summary: dict[str, dict[str, float]] = {}
    series_map = {
        "message_count": [float(run["aggregate"]["message_count"]) for run in runs],
        "control_bytes": [float(run["aggregate"][steady_key]) for run in runs],
        "steady_state_control_bytes": [float(run["steady_state_aggregate"][steady_key]) for run in runs],
        "setup_control_bytes": [float(run["setup_metrics"][steady_key]) for run in runs],
        "llm_total_tokens": [float(run["aggregate"]["llm_total_tokens"]) for run in runs],
        "memory_hit_rate": [float(run["aggregate"]["memory_hit_rate"]) for run in runs],
        "skipped_step_count": [float(run["aggregate"]["skipped_step_count"]) for run in runs],
        "reuse_gain": [float(run["aggregate"]["reuse_gain"]) for run in runs],
        "task_ms": [float(run["aggregate"]["task_ms"]) for run in runs],
    }
    for field, values in series_map.items():
        field_mean = mean(values)
        variance = mean((value - field_mean) ** 2 for value in values) if values else 0.0
        summary[field] = {
            "mean": float(field_mean),
            "min": float(min(values)) if values else 0.0,
            "max": float(max(values)) if values else 0.0,
            "stddev": float(variance ** 0.5),
        }
    return summary


def _progress_line(event: dict[str, object]) -> None:
    status = str(event["status"])
    if status == "completed":
        print(
            "[statebus] "
            f"mode={event['mode']} run={int(event['run_index']):02d} "
            f"task={int(event['task_index'])}/{int(event['task_count'])} "
            f"id={event['task_id']} llm_tokens={int(event['llm_total_tokens'])} "
            f"task_ms={float(event['task_ms']):.2f}"
        )
        return
    print(
        "[statebus] "
        f"mode={event['mode']} run={int(event['run_index']):02d} "
        f"task={int(event['task_index'])}/{int(event['task_count'])} "
        f"id={event['task_id']} failed={event.get('error', 'unknown')}"
    )


def _build_result(
    *,
    task_set_path: str | Path,
    tasks: list[SampleTask],
    modes: tuple[str, ...],
    repeat: int,
    seed: int,
    active_embedder: EmbeddingProvider,
    active_llm: LLMClient,
    llm_description: dict[str, object],
    statepool_config: StatePoolConfig,
    mode_runs: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    summary = {mode: _aggregate_mode_runs(runs) for mode, runs in mode_runs.items()}
    return {
        "manifest": {
            "task_set_path": str(Path(task_set_path)),
            "task_count": len(tasks),
            "continuous_task_count": len(tasks),
            "expected_reuse_task_count": sum(1 for task in tasks if task.expected_reuse),
            "task_groups": sorted({task.task_group for task in tasks}),
            "modes": list(modes),
            "mode_schedule": "paired_round_robin_alternating",
            "text_baseline": "natural_language_briefs_and_narrative_frames",
            "protocol_baseline": "protobuf_control_frames",
            "repeat": repeat,
            "seed": seed,
            "encoder_id": active_embedder.encoder_id,
            "vector_dim": active_embedder.vector_dim,
            "llm_backend": str(llm_description["backend"]),
            "llm_mode": str(llm_description["mode"]),
            "llm_config_source": str(llm_description["source"]),
            "llm_providers": llm_description["providers"],
            "planner_provider": str(llm_description["planner_provider"]),
            "planner_model": str(llm_description["planner_model"]),
            "summarizer_provider": str(llm_description["summarizer_provider"]),
            "summarizer_model": str(llm_description["summarizer_model"]),
            "statepool_backend": statepool_config.default_backend,
            "embed_state_backend": statepool_config.embedding_backend,
        },
        "mode_runs": mode_runs,
        "summary": summary,
    }


async def run_benchmark(
    *,
    task_set_path: str | Path = DEFAULT_TASK_SET,
    modes: tuple[str, ...] = ("text", "protocol"),
    repeat: int = 10,
    seed: int = 42,
    out_dir: str | Path,
    embedder: EmbeddingProvider | None = None,
    embedder_model_path: str | Path = DEFAULT_EMBEDDING_MODEL_PATH,
    llm_client: LLMClient | None = None,
    llm_config: LLMConfig | None = None,
    statepool_config: StatePoolConfig | None = None,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    tasks = load_task_set(task_set_path)
    active_embedder = embedder or SentenceTransformerEmbeddingProvider(embedder_model_path)
    active_llm = llm_client or build_llm_client(llm_config)
    llm_description = active_llm.describe()
    active_statepool_config = statepool_config or StatePoolConfig.from_env()
    mode_runs: dict[str, list[dict[str, object]]] = {mode: [] for mode in modes}
    for run_index in range(repeat):
        for mode in _mode_order_for_run(modes, run_index):
            run_root = out_path / "artifacts" / mode / f"run_{run_index:02d}"
            if run_root.exists():
                shutil.rmtree(run_root)
            run_root.mkdir(parents=True, exist_ok=True)
            mode_runs[mode].append(
                await _run_mode_once(
                    mode=mode,
                    run_index=run_index,
                    root=run_root,
                    tasks=tasks,
                    embedder=active_embedder,
                    llm_client=active_llm,
                    statepool_config=active_statepool_config,
                    progress_callback=progress_callback,
                )
            )
            partial = _build_result(
                task_set_path=task_set_path,
                tasks=tasks,
                modes=modes,
                repeat=repeat,
                seed=seed,
                active_embedder=active_embedder,
                active_llm=active_llm,
                llm_description=llm_description,
                statepool_config=active_statepool_config,
                mode_runs=mode_runs,
            )
            _write_results(out_path, partial)
    result = _build_result(
        task_set_path=task_set_path,
        tasks=tasks,
        modes=modes,
        repeat=repeat,
        seed=seed,
        active_embedder=active_embedder,
        active_llm=active_llm,
        llm_description=llm_description,
        statepool_config=active_statepool_config,
        mode_runs=mode_runs,
    )
    _write_results(out_path, result)
    return result


def _write_results(out_dir: Path, result: dict[str, object]) -> None:
    (out_dir / "benchmark_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_compare_csv(out_dir / "benchmark_compare.csv", result)
    _write_message_breakdown_csv(out_dir / "benchmark_message_breakdown.csv", result)
    (out_dir / "benchmark_message_sizes.md").write_text(_build_message_sizes_md(result), encoding="utf-8")
    (out_dir / "benchmark_report.md").write_text(_build_report(result), encoding="utf-8")


def _write_message_breakdown_csv(path: Path, result: dict[str, object]) -> None:
    fieldnames = [
        "mode",
        "message_type",
        "message_count",
        "protocol_bytes",
        "text_bytes",
        "delta",
        "setup_message_count",
        "setup_protocol_bytes",
        "setup_text_bytes",
        "steady_message_count",
        "steady_protocol_bytes",
        "steady_text_bytes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for mode in result["manifest"]["modes"]:
            mode_summary = result["summary"].get(mode)
            if not mode_summary:
                continue
            for row in mode_summary["message_breakdown"]:
                writer.writerow({"mode": mode, **row})


def _write_compare_csv(path: Path, result: dict[str, object]) -> None:
    summary = result["summary"]
    available_modes = [
        mode
        for mode in ("text", "protocol")
        if mode in summary and int(summary[mode].get("run_count", 0)) > 0
    ]
    if len(available_modes) < 2:
        _write_single_mode_csv(path, summary[available_modes[0]], available_modes[0])
        return
    text_tasks = {item["task_id"]: item for item in summary["text"]["tasks"]}
    protocol_tasks = {item["task_id"]: item for item in summary["protocol"]["tasks"]}
    text_groups = {item["task_group"]: item for item in summary["text"]["task_groups"]}
    protocol_groups = {item["task_group"]: item for item in summary["protocol"]["task_groups"]}
    fieldnames = [
        "row_kind",
        "row_id",
        "text_message_count",
        "protocol_message_count",
        "message_delta",
        "text_setup_control_bytes",
        "protocol_setup_control_bytes",
        "setup_control_bytes_delta",
        "text_steady_state_control_bytes",
        "protocol_steady_state_control_bytes",
        "steady_state_control_bytes_delta",
        "text_control_bytes",
        "protocol_control_bytes",
        "control_bytes_delta",
        "text_state_bytes",
        "protocol_state_bytes",
        "state_bytes_delta",
        "text_mmap_state_bytes",
        "protocol_mmap_state_bytes",
        "mmap_state_bytes_delta",
        "text_shared_memory_state_bytes",
        "protocol_shared_memory_state_bytes",
        "shared_memory_state_bytes_delta",
        "text_llm_total_tokens",
        "protocol_llm_total_tokens",
        "llm_total_tokens_delta",
        "text_memory_query_count",
        "protocol_memory_query_count",
        "memory_query_count_delta",
        "text_memory_hit_rate",
        "protocol_memory_hit_rate",
        "memory_hit_rate_delta",
        "text_planned_step_count",
        "protocol_planned_step_count",
        "planned_step_count_delta",
        "text_skipped_step_count",
        "protocol_skipped_step_count",
        "skipped_step_count_delta",
        "text_reuse_gain",
        "protocol_reuse_gain",
        "reuse_gain_delta",
        "text_reuse_apply_rate",
        "protocol_reuse_apply_rate",
        "reuse_apply_rate_delta",
        "text_expectation_match_rate",
        "protocol_expectation_match_rate",
        "expectation_match_rate_delta",
        "text_control_bytes_reduction_vs_cold",
        "protocol_control_bytes_reduction_vs_cold",
        "control_bytes_reduction_vs_cold_delta",
        "text_llm_total_tokens_reduction_vs_cold",
        "protocol_llm_total_tokens_reduction_vs_cold",
        "llm_total_tokens_reduction_vs_cold_delta",
        "text_task_ms_reduction_vs_cold",
        "protocol_task_ms_reduction_vs_cold",
        "task_ms_reduction_vs_cold_delta",
        "text_task_ms",
        "protocol_task_ms",
        "task_ms_delta",
    ]
    rows = []
    for task_id in sorted(text_tasks, key=lambda item: (text_tasks[item]["task_group"], text_tasks[item]["task_order"], item)):
        rows.append(_compare_row("task", task_id, text_tasks[task_id], protocol_tasks[task_id], summary["text"], summary["protocol"]))
    for task_group in sorted(text_groups):
        rows.append(_compare_row("task_group", task_group, text_groups[task_group], protocol_groups[task_group], summary["text"], summary["protocol"]))
    rows.append(_compare_row("aggregate", "__aggregate__", summary["text"]["aggregate"], summary["protocol"]["aggregate"], summary["text"], summary["protocol"]))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _compare_row(
    row_kind: str,
    row_id: str,
    text_row: dict[str, float],
    protocol_row: dict[str, float],
    text_summary: dict[str, object],
    protocol_summary: dict[str, object],
) -> dict[str, float | str]:
    del text_summary, protocol_summary
    return {
        "row_kind": row_kind,
        "row_id": row_id,
        "text_message_count": round(float(text_row["message_count"]), 4),
        "protocol_message_count": round(float(protocol_row["message_count"]), 4),
        "message_delta": round(float(protocol_row["message_count"]) - float(text_row["message_count"]), 4),
        "text_setup_control_bytes": round(float(text_row.get("setup_text_bytes", text_row.get("text_bytes", 0.0))), 4),
        "protocol_setup_control_bytes": round(float(protocol_row.get("setup_protocol_bytes", protocol_row.get("protocol_bytes", 0.0))), 4),
        "setup_control_bytes_delta": round(
            float(protocol_row.get("setup_protocol_bytes", protocol_row.get("protocol_bytes", 0.0)))
            - float(text_row.get("setup_text_bytes", text_row.get("text_bytes", 0.0))),
            4,
        ),
        "text_steady_state_control_bytes": round(float(text_row.get("steady_state_text_bytes", text_row.get("text_bytes", 0.0))), 4),
        "protocol_steady_state_control_bytes": round(float(protocol_row.get("steady_state_protocol_bytes", protocol_row.get("protocol_bytes", 0.0))), 4),
        "steady_state_control_bytes_delta": round(
            float(protocol_row.get("steady_state_protocol_bytes", protocol_row.get("protocol_bytes", 0.0)))
            - float(text_row.get("steady_state_text_bytes", text_row.get("text_bytes", 0.0))),
            4,
        ),
        "text_control_bytes": round(float(text_row["text_bytes"]), 4),
        "protocol_control_bytes": round(float(protocol_row["protocol_bytes"]), 4),
        "control_bytes_delta": round(float(protocol_row["protocol_bytes"]) - float(text_row["text_bytes"]), 4),
        "text_state_bytes": round(float(text_row["state_bytes"]), 4),
        "protocol_state_bytes": round(float(protocol_row["state_bytes"]), 4),
        "state_bytes_delta": round(float(protocol_row["state_bytes"]) - float(text_row["state_bytes"]), 4),
        "text_mmap_state_bytes": round(float(text_row["mmap_state_bytes"]), 4),
        "protocol_mmap_state_bytes": round(float(protocol_row["mmap_state_bytes"]), 4),
        "mmap_state_bytes_delta": round(float(protocol_row["mmap_state_bytes"]) - float(text_row["mmap_state_bytes"]), 4),
        "text_shared_memory_state_bytes": round(float(text_row["shared_memory_state_bytes"]), 4),
        "protocol_shared_memory_state_bytes": round(float(protocol_row["shared_memory_state_bytes"]), 4),
        "shared_memory_state_bytes_delta": round(
            float(protocol_row["shared_memory_state_bytes"]) - float(text_row["shared_memory_state_bytes"]),
            4,
        ),
        "text_llm_total_tokens": round(float(text_row["llm_total_tokens"]), 4),
        "protocol_llm_total_tokens": round(float(protocol_row["llm_total_tokens"]), 4),
        "llm_total_tokens_delta": round(float(protocol_row["llm_total_tokens"]) - float(text_row["llm_total_tokens"]), 4),
        "text_memory_query_count": round(float(text_row["memory_query_count"]), 4),
        "protocol_memory_query_count": round(float(protocol_row["memory_query_count"]), 4),
        "memory_query_count_delta": round(float(protocol_row["memory_query_count"]) - float(text_row["memory_query_count"]), 4),
        "text_memory_hit_rate": round(float(text_row["memory_hit_rate"]), 4),
        "protocol_memory_hit_rate": round(float(protocol_row["memory_hit_rate"]), 4),
        "memory_hit_rate_delta": round(float(protocol_row["memory_hit_rate"]) - float(text_row["memory_hit_rate"]), 4),
        "text_planned_step_count": round(float(text_row["planned_step_count"]), 4),
        "protocol_planned_step_count": round(float(protocol_row["planned_step_count"]), 4),
        "planned_step_count_delta": round(float(protocol_row["planned_step_count"]) - float(text_row["planned_step_count"]), 4),
        "text_skipped_step_count": round(float(text_row["skipped_step_count"]), 4),
        "protocol_skipped_step_count": round(float(protocol_row["skipped_step_count"]), 4),
        "skipped_step_count_delta": round(float(protocol_row["skipped_step_count"]) - float(text_row["skipped_step_count"]), 4),
        "text_reuse_gain": round(float(text_row["reuse_gain"]), 4),
        "protocol_reuse_gain": round(float(protocol_row["reuse_gain"]), 4),
        "reuse_gain_delta": round(float(protocol_row["reuse_gain"]) - float(text_row["reuse_gain"]), 4),
        "text_reuse_apply_rate": round(float(text_row["reuse_apply_rate"]), 4),
        "protocol_reuse_apply_rate": round(float(protocol_row["reuse_apply_rate"]), 4),
        "reuse_apply_rate_delta": round(float(protocol_row["reuse_apply_rate"]) - float(text_row["reuse_apply_rate"]), 4),
        "text_expectation_match_rate": round(float(text_row["expectation_match_rate"]), 4),
        "protocol_expectation_match_rate": round(float(protocol_row["expectation_match_rate"]), 4),
        "expectation_match_rate_delta": round(float(protocol_row["expectation_match_rate"]) - float(text_row["expectation_match_rate"]), 4),
        "text_control_bytes_reduction_vs_cold": round(float(text_row["control_bytes_reduction_vs_cold"]), 4),
        "protocol_control_bytes_reduction_vs_cold": round(float(protocol_row["control_bytes_reduction_vs_cold"]), 4),
        "control_bytes_reduction_vs_cold_delta": round(
            float(protocol_row["control_bytes_reduction_vs_cold"]) - float(text_row["control_bytes_reduction_vs_cold"]),
            4,
        ),
        "text_llm_total_tokens_reduction_vs_cold": round(float(text_row["llm_total_tokens_reduction_vs_cold"]), 4),
        "protocol_llm_total_tokens_reduction_vs_cold": round(float(protocol_row["llm_total_tokens_reduction_vs_cold"]), 4),
        "llm_total_tokens_reduction_vs_cold_delta": round(
            float(protocol_row["llm_total_tokens_reduction_vs_cold"]) - float(text_row["llm_total_tokens_reduction_vs_cold"]),
            4,
        ),
        "text_task_ms_reduction_vs_cold": round(float(text_row["task_ms_reduction_vs_cold"]), 4),
        "protocol_task_ms_reduction_vs_cold": round(float(protocol_row["task_ms_reduction_vs_cold"]), 4),
        "task_ms_reduction_vs_cold_delta": round(
            float(protocol_row["task_ms_reduction_vs_cold"]) - float(text_row["task_ms_reduction_vs_cold"]),
            4,
        ),
        "text_task_ms": round(float(text_row["task_ms"]), 4),
        "protocol_task_ms": round(float(protocol_row["task_ms"]), 4),
        "task_ms_delta": round(float(protocol_row["task_ms"]) - float(text_row["task_ms"]), 4),
    }


def _build_message_sizes_md(result: dict[str, object]) -> str:
    lines = [
        "# StateBus Message Size Breakdown",
        "",
    ]
    for mode in result["manifest"]["modes"]:
        mode_summary = result["summary"].get(mode)
        if not mode_summary:
            continue
        lines.extend(
            [
                f"## {mode}",
                "",
                "| message_type | count | protocol_bytes | text_bytes | delta | setup_count | steady_count |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in mode_summary["message_breakdown"]:
            lines.append(
                f"| {row['message_type']} | {row['message_count']:.0f} | {row['protocol_bytes']:.0f} | "
                f"{row['text_bytes']:.0f} | {row['delta']:.0f} | {row['setup_message_count']:.0f} | "
                f"{row['steady_message_count']:.0f} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def _build_report(result: dict[str, object]) -> str:
    summary = result["summary"]
    available_modes = [
        mode
        for mode in ("text", "protocol")
        if mode in summary and int(summary[mode].get("run_count", 0)) > 0
    ]
    lines = [
        "# StateBus Benchmark Report",
        "",
        f"- Task set: `{result['manifest']['task_set_path']}`",
        f"- Task groups: `{', '.join(result['manifest']['task_groups'])}`",
        f"- Modes: `{', '.join(result['manifest']['modes'])}`",
        f"- Mode schedule: `{result['manifest'].get('mode_schedule', 'legacy_blocked')}`",
        f"- Text baseline: `{result['manifest']['text_baseline']}`",
        f"- Protocol baseline: `{result['manifest']['protocol_baseline']}`",
        f"- Repeat: `{result['manifest']['repeat']}`",
        f"- Continuous tasks per run: `{result['manifest']['continuous_task_count']}`",
        f"- Expected reuse tasks per run: `{result['manifest']['expected_reuse_task_count']}`",
        f"- Encoder: `{result['manifest']['encoder_id']}`",
        f"- StatePool backend: `{result['manifest']['statepool_backend']}`",
        f"- Embedding state backend: `{result['manifest']['embed_state_backend']}`",
        f"- LLM backend: `{result['manifest']['llm_backend']}`",
        f"- LLM config: `{result['manifest']['llm_config_source']}`",
        f"- Planner provider: `{result['manifest']['planner_provider']}`",
        f"- Planner model: `{result['manifest']['planner_model']}`",
        f"- Summarizer provider: `{result['manifest']['summarizer_provider']}`",
        f"- Summarizer model: `{result['manifest']['summarizer_model']}`",
        "",
        "## Aggregate",
        "",
        "| mode | message_count | control_bytes | state_bytes | llm_total_tokens | memory_hit_rate | skipped_step_count | reuse_gain | task_ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode in available_modes:
        aggregate = summary[mode]["aggregate"]
        control_bytes = aggregate["text_bytes"] if mode == "text" else aggregate["protocol_bytes"]
        lines.append(
            f"| {mode} | {aggregate['message_count']:.2f} | {control_bytes:.2f} | "
            f"{aggregate['state_bytes']:.2f} | {aggregate['llm_total_tokens']:.2f} | "
            f"{aggregate['memory_hit_rate']:.2f} | {aggregate['skipped_step_count']:.2f} | "
            f"{aggregate['reuse_gain']:.2f} | {aggregate['task_ms']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Setup Vs Steady-State Control Bytes",
            "",
            "| mode | setup_control_bytes | steady_state_control_bytes | total_control_bytes |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        aggregate = summary[mode]["aggregate"]
        setup = summary[mode]["setup"]
        steady = summary[mode]["steady_state"]
        setup_control = setup["text_bytes"] if mode == "text" else setup["protocol_bytes"]
        steady_control = steady["text_bytes"] if mode == "text" else steady["protocol_bytes"]
        total_control = aggregate["text_bytes"] if mode == "text" else aggregate["protocol_bytes"]
        lines.append(
            f"| {mode} | {setup_control:.2f} | {steady_control:.2f} | {total_control:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Stability Summary",
            "",
            "| mode | runs | control_bytes_mean | steady_state_control_bytes_mean | setup_control_bytes_mean | llm_total_tokens_mean | task_ms_mean | expectation_match_rate | failure_count |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        stability = summary[mode]["stability"]
        aggregate = summary[mode]["aggregate"]
        lines.append(
            f"| {mode} | {summary[mode]['run_count']} | {stability['control_bytes']['mean']:.2f} | "
            f"{stability['steady_state_control_bytes']['mean']:.2f} | "
            f"{stability['setup_control_bytes']['mean']:.2f} | {stability['llm_total_tokens']['mean']:.2f} | "
            f"{stability['task_ms']['mean']:.2f} | {aggregate['expectation_match_rate']:.2f} | "
            f"{summary[mode]['failure_count']} |"
        )
    lines.extend(
        [
            "",
            "## Task Group Reuse Summary",
            "",
            "| task_group | mode | control_bytes | memory_hit_rate | skipped_step_count | reuse_gain | reuse_apply_rate | expectation_match_rate | task_ms |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        for group in summary[mode]["task_groups"]:
            control_bytes = group["text_bytes"] if mode == "text" else group["protocol_bytes"]
            lines.append(
                f"| {group['task_group']} | {mode} | {control_bytes:.2f} | "
                f"{group['memory_hit_rate']:.2f} | {group['skipped_step_count']:.2f} | "
                f"{group['reuse_gain']:.2f} | {group['reuse_apply_rate']:.2f} | "
                f"{group['expectation_match_rate']:.2f} | {group['task_ms']:.2f} |"
            )
    if len(available_modes) == 2:
        lines.extend(
            [
                "",
                "## Live Token Delta by Mode",
                "",
                f"- protocol minus text total tokens: {summary['protocol']['aggregate']['llm_total_tokens'] - summary['text']['aggregate']['llm_total_tokens']:.2f}",
            ]
        )
    lines.extend(
        [
            "",
            "## Message Type Breakdown",
            "",
            "| mode | message_type | count | protocol_bytes | text_bytes | delta |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        for row in summary[mode]["message_breakdown"]:
            lines.append(
                f"| {mode} | {row['message_type']} | {row['message_count']:.0f} | "
                f"{row['protocol_bytes']:.0f} | {row['text_bytes']:.0f} | {row['delta']:.0f} |"
            )
    lines.extend(["", "## Reuse Validation", ""])
    mismatch_rows: list[str] = []
    for mode in available_modes:
        lines.append(f"### {mode}")
        mode_mismatches = []
        for run in result["mode_runs"][mode]:
            for task_run in run["tasks"]:
                if not task_run["reuse_validation"]["matched_expectation"]:
                    mode_mismatches.append(
                        f"run={run['run_index']:02d} task={task_run['task_id']} "
                        f"expected_reuse={task_run['reuse_validation']['expected_reuse']} "
                        f"applied={task_run['reuse']['applied']}"
                    )
        if mode_mismatches:
            mismatch_rows.extend(mode_mismatches)
            lines.extend(f"- {row}" for row in mode_mismatches)
        else:
            lines.append("- all reuse outcomes matched expectations")
        lines.append("")
    lines.extend(["", "## Pruned Steps By Mode", ""])
    for mode in available_modes:
        lines.append(f"### {mode}")
        pruned_rows = []
        for run in result["mode_runs"][mode]:
            for task_run in run["tasks"]:
                if task_run["reuse"]["applied"]:
                    pruned_rows.append(
                        f"run={run['run_index']:02d} task={task_run['task_id']} "
                        f"memory={task_run['reuse']['memory_id']} "
                        f"skipped={','.join(task_run['reuse']['skipped_step_ids'])}"
                    )
        if pruned_rows:
            lines.extend(f"- {row}" for row in pruned_rows)
        else:
            lines.append("- none")
        lines.append("")
    lines.extend(["## Failure/Retry Summary", ""])
    failure_rows = []
    for mode in available_modes:
        for failure in summary[mode]["failures"]:
            failure_rows.append(f"{mode} run={failure['run_index']:02d} error={failure['error']}")
    if failure_rows:
        lines.extend(f"- {row}" for row in failure_rows)
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def _write_single_mode_csv(path: Path, mode_summary: dict[str, object], mode: str) -> None:
    control_key = _control_metric_key(mode)
    fieldnames = [
        "row_kind",
        "row_id",
        "mode",
        "message_count",
        "setup_control_bytes",
        "steady_state_control_bytes",
        "control_bytes",
        "state_bytes",
        "shared_memory_state_bytes",
        "mmap_state_bytes",
        "llm_total_tokens",
        "memory_query_count",
        "memory_hit_rate",
        "planned_step_count",
        "skipped_step_count",
        "reuse_gain",
        "reuse_apply_rate",
        "expectation_match_rate",
        "control_bytes_reduction_vs_cold",
        "llm_total_tokens_reduction_vs_cold",
        "task_ms_reduction_vs_cold",
        "task_ms",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for task in mode_summary["tasks"]:
            writer.writerow(
                {
                    "row_kind": "task",
                    "row_id": task["task_id"],
                    "mode": mode,
                    "message_count": round(float(task["message_count"]), 4),
                    "setup_control_bytes": 0.0,
                    "steady_state_control_bytes": round(float(task[control_key]), 4),
                    "control_bytes": round(float(task[control_key]), 4),
                    "state_bytes": round(float(task["state_bytes"]), 4),
                    "shared_memory_state_bytes": round(float(task["shared_memory_state_bytes"]), 4),
                    "mmap_state_bytes": round(float(task["mmap_state_bytes"]), 4),
                    "llm_total_tokens": round(float(task["llm_total_tokens"]), 4),
                    "memory_query_count": round(float(task["memory_query_count"]), 4),
                    "memory_hit_rate": round(float(task["memory_hit_rate"]), 4),
                    "planned_step_count": round(float(task["planned_step_count"]), 4),
                    "skipped_step_count": round(float(task["skipped_step_count"]), 4),
                    "reuse_gain": round(float(task["reuse_gain"]), 4),
                    "reuse_apply_rate": round(float(task["reuse_apply_rate"]), 4),
                    "expectation_match_rate": round(float(task["expectation_match_rate"]), 4),
                    "control_bytes_reduction_vs_cold": round(float(task["control_bytes_reduction_vs_cold"]), 4),
                    "llm_total_tokens_reduction_vs_cold": round(float(task["llm_total_tokens_reduction_vs_cold"]), 4),
                    "task_ms_reduction_vs_cold": round(float(task["task_ms_reduction_vs_cold"]), 4),
                    "task_ms": round(float(task["task_ms"]), 4),
                }
            )
        aggregate = mode_summary["aggregate"]
        setup = mode_summary["setup"]
        writer.writerow(
            {
                "row_kind": "aggregate",
                "row_id": "__aggregate__",
                "mode": mode,
                "message_count": round(float(aggregate["message_count"]), 4),
                "setup_control_bytes": round(float(setup[control_key]), 4),
                "steady_state_control_bytes": round(float(aggregate[f"steady_state_{control_key}"]), 4),
                "control_bytes": round(float(aggregate[control_key]), 4),
                "state_bytes": round(float(aggregate["state_bytes"]), 4),
                "shared_memory_state_bytes": round(float(aggregate["shared_memory_state_bytes"]), 4),
                "mmap_state_bytes": round(float(aggregate["mmap_state_bytes"]), 4),
                "llm_total_tokens": round(float(aggregate["llm_total_tokens"]), 4),
                "memory_query_count": round(float(aggregate["memory_query_count"]), 4),
                "memory_hit_rate": round(float(aggregate["memory_hit_rate"]), 4),
                "planned_step_count": round(float(aggregate["planned_step_count"]), 4),
                "skipped_step_count": round(float(aggregate["skipped_step_count"]), 4),
                "reuse_gain": round(float(aggregate["reuse_gain"]), 4),
                "reuse_apply_rate": round(float(aggregate["reuse_apply_rate"]), 4),
                "expectation_match_rate": round(float(aggregate["expectation_match_rate"]), 4),
                "control_bytes_reduction_vs_cold": round(float(aggregate["control_bytes_reduction_vs_cold"]), 4),
                "llm_total_tokens_reduction_vs_cold": round(float(aggregate["llm_total_tokens_reduction_vs_cold"]), 4),
                "task_ms_reduction_vs_cold": round(float(aggregate["task_ms_reduction_vs_cold"]), 4),
                "task_ms": round(float(aggregate["task_ms"]), 4),
            }
        )


def _default_out_dir() -> str:
    runs_dir = Path(os.getenv("STATEBUS_RUNS_DIR", str(Path.home() / "statebus" / "runs")))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(runs_dir / f"benchmark_{stamp}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the StateBus benchmark.")
    parser.add_argument("--task-set", default=str(DEFAULT_TASK_SET))
    parser.add_argument("--modes", default="text,protocol")
    parser.add_argument("--repeat", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=None)
    parser.add_argument("--embedding-model", default=str(DEFAULT_EMBEDDING_MODEL_PATH))
    parser.add_argument("--llm-config", default=None)
    parser.add_argument("--llm-mode", choices=("deterministic", "api"), default=None)
    parser.add_argument("--llm-base-url", default=None)
    parser.add_argument("--planner-model", default=None)
    parser.add_argument("--summarizer-model", default=None)
    parser.add_argument("--statepool-backend", default=None)
    parser.add_argument("--embed-state-backend", default=None)
    parser.add_argument("--quiet-progress", action="store_true")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    modes = tuple(part.strip() for part in args.modes.split(",") if part.strip())
    llm_config = LLMConfig.from_runtime(args.llm_config)
    if args.llm_mode is not None:
        llm_config = llm_config.with_mode(args.llm_mode)
    if args.llm_base_url is not None:
        for provider_name in llm_config.providers:
            llm_config = llm_config.with_provider_override(
                provider_name,
                base_url=args.llm_base_url,
            )
    if args.planner_model is not None:
        llm_config = llm_config.with_role_override("planner", model=args.planner_model)
    if args.summarizer_model is not None:
        llm_config = llm_config.with_role_override("summarizer", model=args.summarizer_model)
    statepool_config = StatePoolConfig.from_env(
        default_backend=args.statepool_backend,
        embedding_backend=args.embed_state_backend,
    )
    out_dir = args.out or _default_out_dir()
    asyncio.run(
        run_benchmark(
            task_set_path=args.task_set,
            modes=modes,
            repeat=args.repeat,
            seed=args.seed,
            out_dir=out_dir,
            embedder_model_path=args.embedding_model,
            llm_config=llm_config,
            statepool_config=statepool_config,
            progress_callback=None if args.quiet_progress else _progress_line,
        )
    )


if __name__ == "__main__":
    main()
