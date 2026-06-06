from __future__ import annotations

import argparse
import asyncio
import csv
import json
import shutil
from pathlib import Path
from statistics import mean
from typing import Any

from agents.sample_agents import build_sample_agents
from memory.store import (
    DEFAULT_EMBEDDING_MODEL_PATH,
    EmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
)
from runtime.llm import LLMClient, LLMConfig, build_llm_client
from runtime.orchestrator import Orchestrator
from tasks.sample_tasks import DEFAULT_TASK_SET, SampleTask, load_task_set

METRIC_FIELDS = (
    "message_count",
    "text_chars",
    "text_bytes",
    "protocol_bytes",
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


def _sum_metric_rows(metric_rows: list[dict[str, object]]) -> dict[str, float]:
    if not metric_rows:
        return {field: 0.0 for field in (*METRIC_FIELDS, "memory_hit_rate", "reuse_gain")}
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
        return {field: 0.0 for field in (*METRIC_FIELDS, "memory_hit_rate", "reuse_gain")}
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


async def _run_mode_once(
    *,
    mode: str,
    run_index: int,
    root: Path,
    tasks: list[SampleTask],
    embedder: EmbeddingProvider,
    llm_client: LLMClient,
) -> dict[str, object]:
    orchestrator = Orchestrator(build_sample_agents(llm_client=llm_client))
    ordered_tasks = sorted(tasks, key=_task_sort_key)
    task_runs: list[dict[str, object]] = []
    group_db_paths = {
        task.task_group: root / f"{task.task_group}.sqlite3" for task in ordered_tasks
    }
    for task in ordered_tasks:
        ctx = Orchestrator.create_context(
            mode=mode,
            task_id=task.task_id,
            task_theme=task.task_theme,
            state_root=root / task.task_group / task.task_id,
            memory_db_path=group_db_paths[task.task_group],
            embedder=embedder,
        )
        try:
            await orchestrator.run_task(task, ctx)
            task_runs.append(
                {
                    "task_id": task.task_id,
                    "task_group": task.task_group,
                    "task_order": task.task_order,
                    "task_theme": task.task_theme,
                    "goal": task.goal,
                    "memory_db_path": str(group_db_paths[task.task_group]),
                    "metrics": ctx.metrics.to_dict(),
                    "memory_hits": [hit.memory_id for hit in ctx.memory_hits],
                    "reuse": {
                        "applied": ctx.reuse_hit is not None,
                        "memory_id": None if ctx.reuse_hit is None else ctx.reuse_hit.memory_id,
                        "reuse_source": None if ctx.reuse_hit is None else ctx.reuse_hit.reuse_source,
                        "skipped_step_ids": list(ctx.pruned_step_ids),
                    },
                    "state_refs": {
                        state_id: {
                            "kind": ref.kind,
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
                            "payload": _sanitize_payload(
                                {
                                    key: value
                                    for key, value in result.payload.items()
                                    if key != "memory_commit"
                                }
                            ),
                        }
                        for step_id, result in ctx.results.items()
                    },
                }
            )
        finally:
            ctx.memory_store.close()
    aggregate = _sum_metric_rows([task_run["metrics"] for task_run in task_runs])
    return {
        "mode": mode,
        "run_index": run_index,
        "memory_db_paths": {
            group: str(path) for group, path in sorted(group_db_paths.items(), key=lambda item: item[0])
        },
        "aggregate": aggregate,
        "task_groups": _aggregate_task_groups(task_runs),
        "tasks": task_runs,
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
                "aggregate": _sum_metric_rows([item["metrics"] for item in rows]),
            }
        )
    return summaries


def _aggregate_mode_runs(runs: list[dict[str, object]]) -> dict[str, object]:
    task_order_lookup = [
        (str(task["task_id"]), str(task["task_group"]), int(task["task_order"]))
        for task in runs[0]["tasks"]
    ]
    group_lookup = [str(group["task_group"]) for group in runs[0]["task_groups"]]
    task_summaries = []
    for task_id, task_group, task_order in task_order_lookup:
        matching = [
            task_run
            for run in runs
            for task_run in run["tasks"]
            if task_run["task_id"] == task_id
        ]
        task_summaries.append(
            {
                "task_id": task_id,
                "task_group": task_group,
                "task_order": task_order,
                **_average_metric_rows([item["metrics"] for item in matching]),
            }
        )
    group_summaries = []
    for task_group in group_lookup:
        matching = [
            group_summary
            for run in runs
            for group_summary in run["task_groups"]
            if group_summary["task_group"] == task_group
        ]
        group_summaries.append(
            {
                "task_group": task_group,
                "task_ids": list(matching[0]["task_ids"]),
                **_average_metric_rows([item["aggregate"] for item in matching]),
            }
        )
    return {
        "run_count": len(runs),
        "aggregate": _average_metric_rows([run["aggregate"] for run in runs]),
        "task_groups": group_summaries,
        "tasks": task_summaries,
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
) -> dict[str, object]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    tasks = load_task_set(task_set_path)
    active_embedder = embedder or SentenceTransformerEmbeddingProvider(embedder_model_path)
    active_llm = llm_client or build_llm_client(llm_config)
    mode_runs: dict[str, list[dict[str, object]]] = {mode: [] for mode in modes}
    for mode in modes:
        for run_index in range(repeat):
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
                )
            )
    llm_description = active_llm.describe()
    summary = {mode: _aggregate_mode_runs(runs) for mode, runs in mode_runs.items()}
    result = {
        "manifest": {
            "task_set_path": str(Path(task_set_path)),
            "task_count": len(tasks),
            "task_groups": sorted({task.task_group for task in tasks}),
            "modes": list(modes),
            "text_baseline": "natural_language_briefs_and_narrative_frames",
            "protocol_baseline": "structured_json_control_frames",
            "repeat": repeat,
            "seed": seed,
            "embedding_model_path": None if embedder is not None else str(Path(embedder_model_path)),
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
        },
        "mode_runs": mode_runs,
        "summary": summary,
    }
    _write_results(out_path, result)
    return result


def _write_results(out_dir: Path, result: dict[str, object]) -> None:
    (out_dir / "benchmark_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_compare_csv(out_dir / "benchmark_compare.csv", result)
    (out_dir / "benchmark_report.md").write_text(_build_report(result), encoding="utf-8")


def _write_compare_csv(path: Path, result: dict[str, object]) -> None:
    summary = result["summary"]
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
        "text_control_bytes",
        "protocol_control_bytes",
        "control_bytes_delta",
        "text_state_bytes",
        "protocol_state_bytes",
        "state_bytes_delta",
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
        "text_task_ms",
        "protocol_task_ms",
        "task_ms_delta",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for task in summary["text"]["tasks"]:
            task_id = task["task_id"]
            writer.writerow(
                _compare_row("task", task_id, text_tasks[task_id], protocol_tasks[task_id])
            )
        for group in summary["text"]["task_groups"]:
            task_group = group["task_group"]
            writer.writerow(
                _compare_row("group", task_group, text_groups[task_group], protocol_groups[task_group])
            )
        writer.writerow(
            _compare_row(
                "aggregate",
                "__aggregate__",
                summary["text"]["aggregate"],
                summary["protocol"]["aggregate"],
            )
        )


def _compare_row(
    row_kind: str,
    row_id: str,
    text_row: dict[str, float],
    protocol_row: dict[str, float],
) -> dict[str, float | str]:
    text_control_bytes = float(text_row["text_bytes"])
    protocol_control_bytes = float(protocol_row["protocol_bytes"])
    return {
        "row_kind": row_kind,
        "row_id": row_id,
        "text_message_count": round(float(text_row["message_count"]), 4),
        "protocol_message_count": round(float(protocol_row["message_count"]), 4),
        "message_delta": round(float(protocol_row["message_count"]) - float(text_row["message_count"]), 4),
        "text_control_bytes": round(text_control_bytes, 4),
        "protocol_control_bytes": round(protocol_control_bytes, 4),
        "control_bytes_delta": round(protocol_control_bytes - text_control_bytes, 4),
        "text_state_bytes": round(float(text_row["state_bytes"]), 4),
        "protocol_state_bytes": round(float(protocol_row["state_bytes"]), 4),
        "state_bytes_delta": round(float(protocol_row["state_bytes"]) - float(text_row["state_bytes"]), 4),
        "text_llm_total_tokens": round(float(text_row["llm_total_tokens"]), 4),
        "protocol_llm_total_tokens": round(float(protocol_row["llm_total_tokens"]), 4),
        "llm_total_tokens_delta": round(
            float(protocol_row["llm_total_tokens"]) - float(text_row["llm_total_tokens"]),
            4,
        ),
        "text_memory_query_count": round(float(text_row["memory_query_count"]), 4),
        "protocol_memory_query_count": round(float(protocol_row["memory_query_count"]), 4),
        "memory_query_count_delta": round(
            float(protocol_row["memory_query_count"]) - float(text_row["memory_query_count"]),
            4,
        ),
        "text_memory_hit_rate": round(float(text_row["memory_hit_rate"]), 4),
        "protocol_memory_hit_rate": round(float(protocol_row["memory_hit_rate"]), 4),
        "memory_hit_rate_delta": round(
            float(protocol_row["memory_hit_rate"]) - float(text_row["memory_hit_rate"]),
            4,
        ),
        "text_planned_step_count": round(float(text_row["planned_step_count"]), 4),
        "protocol_planned_step_count": round(float(protocol_row["planned_step_count"]), 4),
        "planned_step_count_delta": round(
            float(protocol_row["planned_step_count"]) - float(text_row["planned_step_count"]),
            4,
        ),
        "text_skipped_step_count": round(float(text_row["skipped_step_count"]), 4),
        "protocol_skipped_step_count": round(float(protocol_row["skipped_step_count"]), 4),
        "skipped_step_count_delta": round(
            float(protocol_row["skipped_step_count"]) - float(text_row["skipped_step_count"]),
            4,
        ),
        "text_reuse_gain": round(float(text_row["reuse_gain"]), 4),
        "protocol_reuse_gain": round(float(protocol_row["reuse_gain"]), 4),
        "reuse_gain_delta": round(float(protocol_row["reuse_gain"]) - float(text_row["reuse_gain"]), 4),
        "text_task_ms": round(float(text_row["task_ms"]), 4),
        "protocol_task_ms": round(float(protocol_row["task_ms"]), 4),
        "task_ms_delta": round(float(protocol_row["task_ms"]) - float(text_row["task_ms"]), 4),
    }


def _build_report(result: dict[str, object]) -> str:
    summary = result["summary"]
    lines = [
        "# StateBus Benchmark Report",
        "",
        f"- Task set: `{result['manifest']['task_set_path']}`",
        f"- Task groups: `{', '.join(result['manifest']['task_groups'])}`",
        f"- Modes: `{', '.join(result['manifest']['modes'])}`",
        f"- Text baseline: `{result['manifest']['text_baseline']}`",
        f"- Protocol baseline: `{result['manifest']['protocol_baseline']}`",
        f"- Repeat: `{result['manifest']['repeat']}`",
        f"- Encoder: `{result['manifest']['encoder_id']}`",
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
    for mode in ("text", "protocol"):
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
            "## Task Group Reuse Summary",
            "",
            "| task_group | mode | control_bytes | memory_hit_rate | skipped_step_count | reuse_gain | task_ms |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in ("text", "protocol"):
        for group in summary[mode]["task_groups"]:
            control_bytes = group["text_bytes"] if mode == "text" else group["protocol_bytes"]
            lines.append(
                f"| {group['task_group']} | {mode} | {control_bytes:.2f} | "
                f"{group['memory_hit_rate']:.2f} | {group['skipped_step_count']:.2f} | "
                f"{group['reuse_gain']:.2f} | {group['task_ms']:.2f} |"
            )
    lines.extend(
        [
            "",
            "## Task Compare",
            "",
            "| task_id | group | text_control_bytes | protocol_control_bytes | text_memory_hit_rate | protocol_memory_hit_rate | text_skipped_step_count | protocol_skipped_step_count | text_reuse_gain | protocol_reuse_gain | text_task_ms | protocol_task_ms |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    text_tasks = {item["task_id"]: item for item in summary["text"]["tasks"]}
    protocol_tasks = {item["task_id"]: item for item in summary["protocol"]["tasks"]}
    for task in summary["text"]["tasks"]:
        task_id = task["task_id"]
        text_row = text_tasks[task_id]
        protocol_row = protocol_tasks[task_id]
        lines.append(
            f"| {task_id} | {task['task_group']} | {text_row['text_bytes']:.2f} | "
            f"{protocol_row['protocol_bytes']:.2f} | {text_row['memory_hit_rate']:.2f} | "
            f"{protocol_row['memory_hit_rate']:.2f} | {text_row['skipped_step_count']:.2f} | "
            f"{protocol_row['skipped_step_count']:.2f} | {text_row['reuse_gain']:.2f} | "
            f"{protocol_row['reuse_gain']:.2f} | {text_row['task_ms']:.2f} | "
            f"{protocol_row['task_ms']:.2f} |"
        )
    lines.extend(["", "## Pruned Steps By Mode", ""])
    for mode in ("text", "protocol"):
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
    lines.extend(["## Failures", "", "- none"])
    return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run StateBus benchmark skeleton.")
    parser.add_argument("--task-set", default=str(DEFAULT_TASK_SET))
    parser.add_argument("--modes", default="text,protocol")
    parser.add_argument("--repeat", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", required=True)
    parser.add_argument("--embedding-model", default=str(DEFAULT_EMBEDDING_MODEL_PATH))
    parser.add_argument("--llm-config", default=None)
    parser.add_argument("--llm-mode", choices=("deterministic", "api"), default=None)
    parser.add_argument("--llm-base-url", default=None)
    parser.add_argument("--planner-model", default=None)
    parser.add_argument("--summarizer-model", default=None)
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
    asyncio.run(
        run_benchmark(
            task_set_path=args.task_set,
            modes=modes,
            repeat=args.repeat,
            seed=args.seed,
            out_dir=args.out,
            embedder_model_path=args.embedding_model,
            llm_config=llm_config,
        )
    )


if __name__ == "__main__":
    main()
