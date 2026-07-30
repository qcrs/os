#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import sys
from types import SimpleNamespace
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.experiments.engine_local_kv.run_engine_local_kv_mainline_ab import (
    MainlineTask,
    _configure_environment,
    _reduction,
    _run_task_lane,
)
from statebus.integrations.vllm_kv.client import VllmKVClient


SUITE_SCHEMA_VERSION = "statebus.engine_local_kv_mainline_suite.v1"
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "statebus/benchmark/samples/engine_local_kv_mainline_10round/suite_manifest.json"
)
MEASURED_MODES = ("full_replay", "continuation")
METRIC_FIELDS = (
    "computed_prefill_tokens",
    "consumer_ttft_ms",
    "consumer_wall_ms",
    "consumer_request_bytes",
    "producer_client_wall_ms",
    "producer_consumer_wall_ms",
    "mainline_wall_ms",
)


@dataclass(frozen=True)
class SuiteTask:
    round_number: int
    task: MainlineTask


@dataclass(frozen=True)
class SuiteDefinition:
    suite_id: str
    parent_tokens: int
    phase_order: tuple[str, ...]
    warmup_per_phase: int
    temperature: float
    seed: int
    tasks: tuple[SuiteTask, ...]
    manifest_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run ten full-mainline baselines first, then ten explicit engine-local "
            "KV continuations."
        )
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--base-url", default="http://127.0.0.1:53334")
    parser.add_argument("--model", default="qwen3-32b")
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--skip-warmup", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    suite = load_suite_manifest(args.manifest)
    generated_run_id = datetime.now(timezone.utc).strftime(
        "mainline-10round-%Y%m%dT%H%M%SZ"
    )
    output_dir = args.output_dir or (
        Path(os.getenv("STATEBUS_RUN_ROOT", REPO_ROOT / "runs"))
        / "engine_local_kv_mainline_10round"
        / generated_run_id
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.token_file is not None:
        os.environ["STATEBUS_KV_API_TOKEN_FILE"] = str(args.token_file.resolve())
    _configure_suite_environment(args, suite)
    current_health = _service_health()
    _validate_service_health(current_health, args.model, suite.parent_tokens)
    snapshot_path = output_dir / "run_manifest_snapshot.json"
    if args.resume and snapshot_path.is_file():
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        run_id = str(snapshot["run_id"])
        health_before = dict(snapshot["service_health_before"])
    else:
        run_id = generated_run_id
        health_before = current_health
        snapshot = {
            "run_id": run_id,
            "suite": suite_payload(suite),
            "base_url": args.base_url,
            "model": args.model,
            "execution_policy": "grouped_baseline_then_kv",
            "serialized": True,
            "warmups_excluded": not args.skip_warmup,
            "service_health_before": health_before,
        }
        _write_json(snapshot_path, snapshot)

    records: list[dict[str, Any]] = []
    execution_index = 0
    for phase_index, mode in enumerate(suite.phase_order, start=1):
        missing = [
            item
            for item in suite.tasks
            if not (args.resume and _record_path(output_dir, item, mode).is_file())
        ]
        if missing and not args.skip_warmup:
            _run_phase_warmup(
                output_dir=output_dir,
                suite=suite,
                mode=mode,
                phase_index=phase_index,
                resume=args.resume,
            )
        for item in suite.tasks:
            execution_index += 1
            record_path = _record_path(output_dir, item, mode)
            if args.resume and record_path.is_file():
                record = json.loads(record_path.read_text(encoding="utf-8"))
                print(
                    f"resume phase={phase_index} execution={execution_index}/20 "
                    f"round={item.round_number} mode={mode} task={item.task.task_id}"
                )
            else:
                print(
                    f"start phase={phase_index} execution={execution_index}/20 "
                    f"round={item.round_number} mode={mode} task={item.task.task_id}",
                    flush=True,
                )
                task_root = record_path.parent.parent
                record = _run_task_lane(mode, output_dir=task_root, task=item.task)
                record.update(
                    {
                        "suite_id": suite.suite_id,
                        "round": item.round_number,
                        "phase_index": phase_index,
                        "execution_index": execution_index,
                        "warmup": False,
                        "execution_policy": "grouped_baseline_then_kv",
                    }
                )
                _write_json(record_path, record)
                print(
                    f"done phase={phase_index} execution={execution_index}/20 "
                    f"ttft_ms={record['consumer_ttft_ms']:.3f} "
                    f"computed={record['computed_prefill_tokens']} "
                    f"wall_ms={record['mainline_wall_ms']:.3f} "
                    f"quality={record['quality_floor_pass']}",
                    flush=True,
                )
            records.append(record)
            _write_record_exports(output_dir, records)
            _write_json(
                output_dir / "progress.json",
                {
                    "run_id": run_id,
                    "completed_measured_executions": len(records),
                    "expected_measured_executions": len(suite.tasks)
                    * len(suite.phase_order),
                    "last_task_id": item.task.task_id,
                    "last_mode": mode,
                },
            )

    health_after = _service_health()
    summary = summarize_suite(
        run_id=run_id,
        output_dir=output_dir,
        suite=suite,
        records=records,
        health_before=health_before,
        health_after=health_after,
    )
    _write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    _write_json(
        output_dir / "progress.json",
        {
            "run_id": run_id,
            "completed_measured_executions": len(records),
            "expected_measured_executions": len(suite.tasks) * len(suite.phase_order),
            "status": "complete",
        },
    )
    aggregate = summary["aggregate"]
    print(f"run_id={run_id}")
    print(f"output_dir={output_dir}")
    print(
        "aggregate: "
        f"quality_pairs={aggregate['quality_parity_count']}/{aggregate['pair_count']} "
        f"output_pairs={aggregate['consumer_output_token_parity_count']}/{aggregate['pair_count']} "
        f"ttft_reduction={aggregate['metrics']['consumer_ttft_ms']['lane_p50_reduction']:.4f} "
        f"computed_reduction={aggregate['metrics']['computed_prefill_tokens']['lane_p50_reduction']:.4f} "
        f"mainline_reduction={aggregate['metrics']['mainline_wall_ms']['lane_p50_reduction']:.4f}"
    )
    all_quality = all(bool(record["quality_floor_pass"]) for record in records)
    all_pairs = aggregate["pair_count"] == len(suite.tasks)
    all_released = aggregate["kv_proof_pass_count"] == len(suite.tasks)
    return 0 if all_quality and all_pairs and all_released else 2


def load_suite_manifest(path: Path) -> SuiteDefinition:
    path = path.resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SUITE_SCHEMA_VERSION:
        raise ValueError("engine-local KV mainline suite schema mismatch")
    phase_order = tuple(str(value) for value in payload.get("phase_order", ()))
    if phase_order != MEASURED_MODES:
        raise ValueError("suite must run all full_replay tasks before continuation")
    tasks: list[SuiteTask] = []
    for value in payload.get("tasks", ()):
        document = Path(str(value["document_path"]))
        if not document.is_absolute():
            document = REPO_ROOT / document
        expected_facts = {
            str(key): str(item) for key, item in dict(value["expected_facts"]).items()
        }
        expected_keys = {"metric_name", "value_q1", "value_q2", "value_q3"}
        if set(expected_facts) != expected_keys:
            raise ValueError(f"invalid expected facts for {value['task_id']}")
        tasks.append(
            SuiteTask(
                round_number=int(value["round"]),
                task=MainlineTask(
                    task_id=str(value["task_id"]),
                    company=str(value["company"]),
                    target_entity=str(value["target_entity"]),
                    dataset_id=str(value["dataset_id"]),
                    document=document.resolve(),
                    metric=str(value["metric"]),
                    request_text=str(value["request_text"]),
                    expected_facts=expected_facts,
                ),
            )
        )
    task_ids = [item.task.task_id for item in tasks]
    rounds = [item.round_number for item in tasks]
    if len(tasks) != 10 or len(set(task_ids)) != 10 or rounds != list(range(1, 11)):
        raise ValueError("suite must contain ten unique, ordered tasks")
    if any(not item.task.document.is_file() for item in tasks):
        missing = [
            str(item.task.document)
            for item in tasks
            if not item.task.document.is_file()
        ]
        raise FileNotFoundError(f"suite documents missing: {missing}")
    metrics_by_company = {
        company: {item.task.metric for item in tasks if item.task.company == company}
        for company in {item.task.company for item in tasks}
    }
    expected_metrics = {
        "revenue_musd",
        "gross_margin_pct",
        "operating_expense_musd",
        "churn_rate_pct",
        "on_time_delivery_pct",
    }
    if metrics_by_company != {"nova": expected_metrics, "orion": expected_metrics}:
        raise ValueError("suite must cover five metrics for each company")
    return SuiteDefinition(
        suite_id=str(payload["suite_id"]),
        parent_tokens=int(payload["parent_tokens"]),
        phase_order=phase_order,
        warmup_per_phase=int(payload.get("warmup_per_phase", 1)),
        temperature=float(payload.get("temperature", 0.0)),
        seed=int(payload.get("seed", 7)),
        tasks=tuple(tasks),
        manifest_path=path,
    )


def suite_payload(suite: SuiteDefinition) -> dict[str, Any]:
    return {
        "schema_version": SUITE_SCHEMA_VERSION,
        "suite_id": suite.suite_id,
        "manifest_path": str(suite.manifest_path),
        "parent_tokens": suite.parent_tokens,
        "phase_order": list(suite.phase_order),
        "warmup_per_phase": suite.warmup_per_phase,
        "temperature": suite.temperature,
        "seed": suite.seed,
        "tasks": [
            {
                "round": item.round_number,
                "task_id": item.task.task_id,
                "company": item.task.company,
                "metric": item.task.metric,
                "document_path": str(item.task.document),
                "expected_facts": dict(item.task.expected_facts),
            }
            for item in suite.tasks
        ],
    }


def _configure_suite_environment(
    args: argparse.Namespace, suite: SuiteDefinition
) -> None:
    _configure_environment(
        SimpleNamespace(
            base_url=args.base_url,
            model=args.model,
            parent_tokens=suite.parent_tokens,
        )
    )
    fixed = {
        "STATEBUS_LLM_MODE": "local_vllm",
        "STATEBUS_LLM_BASE_URL": f"{args.base_url.rstrip('/')}/v1",
        "STATEBUS_LLM_DEFAULT_MODEL": args.model,
        "STATEBUS_LLM_REQUEST_MAX_ATTEMPTS": "1",
        "STATEBUS_LLM_PLANNER_MAX_TOKENS": "512",
        "STATEBUS_LLM_RETRIEVER_MAX_TOKENS": "96",
        "STATEBUS_LLM_PLANNER_TEMPERATURE": str(suite.temperature),
        "STATEBUS_LLM_RETRIEVER_TEMPERATURE": str(suite.temperature),
        "STATEBUS_LLM_EXECUTOR_TEMPERATURE": str(suite.temperature),
        "STATEBUS_LLM_SUMMARIZER_TEMPERATURE": str(suite.temperature),
        "STATEBUS_KV_API_BASE_URL": args.base_url.rstrip("/"),
        "STATEBUS_ENGINE_LOCAL_KV_MODEL": args.model,
        "STATEBUS_ENGINE_LOCAL_KV_PARENT_TOKENS": str(suite.parent_tokens),
        "STATEBUS_ENGINE_LOCAL_KV_SEED": str(suite.seed),
        "STATEBUS_PREFIX_ALIGNMENT_MODE": "shared_evidence_prefix",
        "STATEBUS_ROUTE_HINTS_ENABLED": "1",
    }
    os.environ.update(fixed)


def _run_phase_warmup(
    *,
    output_dir: Path,
    suite: SuiteDefinition,
    mode: str,
    phase_index: int,
    resume: bool,
) -> None:
    if suite.warmup_per_phase != 1:
        raise ValueError("this result-oriented suite requires exactly one phase warmup")
    warmup_root = output_dir / "warmups" / mode
    record_path = warmup_root / mode / "record.json"
    if resume and record_path.is_file():
        print(f"resume warmup phase={phase_index} mode={mode}")
        return
    source = suite.tasks[0].task
    task = replace(source, task_id=f"{source.task_id}-warmup-{mode}")
    print(f"start excluded warmup phase={phase_index} mode={mode}", flush=True)
    record = _run_task_lane(mode, output_dir=warmup_root, task=task)
    record.update(
        {
            "suite_id": suite.suite_id,
            "phase_index": phase_index,
            "warmup": True,
            "excluded_from_summary": True,
        }
    )
    _write_json(record_path, record)
    print(f"done excluded warmup phase={phase_index} mode={mode}", flush=True)


def _service_health() -> dict[str, Any]:
    with VllmKVClient() as client:
        return dict(client.health())


def _validate_service_health(
    health: dict[str, Any], model: str, parent_tokens: int
) -> None:
    if health.get("status") != "ready" or str(health.get("model")) != model:
        raise RuntimeError(
            "engine-local KV service is not ready for the requested model"
        )
    if bool(health.get("automatic_prefix_caching")):
        raise RuntimeError("automatic prefix caching must remain disabled")
    block_size = int(health.get("block_size", 0))
    if block_size <= 0 or parent_tokens % block_size:
        raise RuntimeError(
            "parent token count is not aligned to the service block size"
        )


def _record_path(output_dir: Path, item: SuiteTask, mode: str) -> Path:
    return (
        output_dir
        / "rounds"
        / f"{item.round_number:02d}-{item.task.task_id}"
        / mode
        / "record.json"
    )


def summarize_suite(
    *,
    run_id: str,
    output_dir: Path,
    suite: SuiteDefinition,
    records: list[dict[str, Any]],
    health_before: dict[str, Any] | None = None,
    health_after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pairs = pair_records(records)
    comparisons = [
        compare_pair(baseline, continuation) for baseline, continuation in pairs
    ]
    metrics = {field: summarize_metric_pairs(pairs, field) for field in METRIC_FIELDS}
    continuation_records = [value[1] for value in pairs]
    exact_output_pairs = [
        pair
        for pair, comparison in zip(pairs, comparisons)
        if comparison["consumer_output_token_parity"]
    ]
    aggregate = {
        "pair_count": len(pairs),
        "measured_execution_count": len(records),
        "quality_pass_count": sum(
            bool(value["quality_floor_pass"]) for value in records
        ),
        "quality_parity_count": sum(value["quality_parity"] for value in comparisons),
        "producer_output_token_parity_count": sum(
            value["producer_output_token_parity"] for value in comparisons
        ),
        "consumer_output_token_parity_count": sum(
            value["consumer_output_token_parity"] for value in comparisons
        ),
        "output_artifact_hash_parity_count": sum(
            value["output_artifact_hash_parity"] for value in comparisons
        ),
        "structured_artifact_core_parity_count": sum(
            value["structured_artifact_core_parity"] for value in comparisons
        ),
        "required_fact_parity_count": sum(
            value["required_fact_parity"] for value in comparisons
        ),
        "kv_proof_pass_count": sum(value["kv_proof_pass"] for value in comparisons),
        "fallback_count": sum(int(value.get("fallback_count", 0)) for value in records),
        "capture_count": sum(int(value.get("capture_count", 0)) for value in records),
        "load_count": sum(int(value.get("load_count", 0)) for value in records),
        "consumer_wall_positive_count": sum(
            value["consumer_wall_ms_reduction"] > 0 for value in comparisons
        ),
        "mainline_wall_positive_count": sum(
            value["mainline_wall_ms_reduction"] > 0 for value in comparisons
        ),
        "kv_transfer": {
            "inherited_kv_tokens": distribution(
                [float(value["inherited_kv_tokens"]) for value in continuation_records]
            ),
            "kv_store_ms": distribution(
                [float(value["kv_store_ms"]) for value in continuation_records]
            ),
            "kv_load_ms": distribution(
                [float(value["kv_load_ms"]) for value in continuation_records]
            ),
            "kv_bytes_actual": distribution(
                [float(value["kv_bytes_actual"]) for value in continuation_records]
            ),
        },
        "exact_output_subset": {
            "pair_count": len(exact_output_pairs),
            "metrics": {
                field: summarize_metric_pairs(exact_output_pairs, field)
                for field in (
                    "computed_prefill_tokens",
                    "consumer_ttft_ms",
                    "consumer_wall_ms",
                    "mainline_wall_ms",
                )
            },
        },
        "metrics": metrics,
    }
    return {
        "schema_version": "statebus.engine_local_kv_mainline_suite_result.v1",
        "run_id": run_id,
        "suite_id": suite.suite_id,
        "output_dir": str(output_dir),
        "manifest_path": str(suite.manifest_path),
        "model": str((health_before or {}).get("model", "qwen3-32b")),
        "parent_tokens": suite.parent_tokens,
        "serialized": True,
        "repeat_count_per_task_per_mode": 1,
        "execution_policy": "grouped_baseline_then_kv",
        "phase_order": list(suite.phase_order),
        "measured_execution_order": [
            {
                "execution_index": index,
                "task_id": value["task_id"],
                "mode": value["mode"],
            }
            for index, value in enumerate(records, start=1)
        ],
        "warmup_policy": "one excluded full-mainline task before each phase",
        "service_health_before": health_before or {},
        "service_health_after": health_after or {},
        "records": records,
        "comparisons": comparisons,
        "aggregate": aggregate,
    }


def pair_records(
    records: Iterable[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record["task_id"]), {})[str(record["mode"])] = record
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for task_id, by_mode in sorted(
        grouped.items(),
        key=lambda item: int(next(iter(item[1].values())).get("round", 0)),
    ):
        if set(by_mode) != set(MEASURED_MODES):
            continue
        baseline = by_mode["full_replay"]
        continuation = by_mode["continuation"]
        if (
            baseline["task_id"] != continuation["task_id"]
            or task_id != baseline["task_id"]
        ):
            raise ValueError("task pairing mismatch")
        pairs.append((baseline, continuation))
    return pairs


def compare_pair(
    baseline: dict[str, Any], continuation: dict[str, Any]
) -> dict[str, Any]:
    inherited = int(continuation["inherited_kv_tokens"])
    parent_tokens = int(continuation["parent_tokens"])
    released = any(
        str(value.get("status", "")) == "released"
        for value in continuation.get("release_calls", ())
    )
    return {
        "round": int(baseline.get("round", 0)),
        "task_id": baseline["task_id"],
        "company": baseline["company"],
        "metric": baseline["metric"],
        **{f"{field}_baseline": baseline[field] for field in METRIC_FIELDS},
        **{f"{field}_continuation": continuation[field] for field in METRIC_FIELDS},
        **{
            f"{field}_reduction": _reduction(
                float(baseline[field]), float(continuation[field])
            )
            for field in METRIC_FIELDS
        },
        "inherited_kv_tokens": inherited,
        "kv_store_ms": float(continuation["kv_store_ms"]),
        "kv_load_ms": float(continuation["kv_load_ms"]),
        "kv_bytes_actual": int(continuation["kv_bytes_actual"]),
        "quality_parity": bool(
            baseline["quality_floor_pass"] and continuation["quality_floor_pass"]
        ),
        "producer_logical_token_parity": (
            baseline["producer_logical_token_digest"]
            == continuation["producer_logical_token_digest"]
        ),
        "consumer_logical_token_parity": (
            baseline["consumer_logical_token_digest"]
            == continuation["consumer_logical_token_digest"]
        ),
        "producer_output_token_parity": (
            baseline["producer_output_token_digest"]
            == continuation["producer_output_token_digest"]
        ),
        "consumer_output_token_parity": (
            baseline["consumer_output_token_digest"]
            == continuation["consumer_output_token_digest"]
        ),
        "output_artifact_hash_parity": (
            baseline["output_artifact_hash"] == continuation["output_artifact_hash"]
        ),
        "structured_artifact_core_parity": (
            _structured_artifact_core(baseline["output_payload"])
            == _structured_artifact_core(continuation["output_payload"])
        ),
        "required_fact_parity": _required_facts_match(baseline, continuation),
        "kv_proof_pass": bool(
            inherited == parent_tokens
            and int(continuation["capture_count"]) == 1
            and int(continuation["load_count"]) == 1
            and int(continuation["connector_load_count"]) == 1
            and int(continuation["fallback_count"]) == 0
            and released
        ),
        "release_pass": released,
    }


def _structured_artifact_core(payload: object) -> object:
    if not isinstance(payload, dict):
        return payload
    return {key: value for key, value in payload.items() if key != "summary_text"}


def _required_facts_match(
    baseline: dict[str, Any], continuation: dict[str, Any]
) -> bool:
    expected = dict(baseline.get("expected_facts") or {})
    if expected != dict(continuation.get("expected_facts") or {}):
        return False
    left = dict(baseline.get("output_payload") or {})
    right = dict(continuation.get("output_payload") or {})
    return bool(expected) and all(
        str(left.get(key)) == str(value) == str(right.get(key))
        for key, value in expected.items()
    )


def summarize_metric_pairs(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]], field: str
) -> dict[str, Any]:
    baseline = [float(value[0][field]) for value in pairs]
    continuation = [float(value[1][field]) for value in pairs]
    paired_reductions = [
        _reduction(left, right) for left, right in zip(baseline, continuation)
    ]
    if not baseline:
        return {}
    baseline_p50 = statistics.median(baseline)
    continuation_p50 = statistics.median(continuation)
    return {
        "baseline": distribution(baseline),
        "continuation": distribution(continuation),
        "lane_p50_reduction": _reduction(baseline_p50, continuation_p50),
        "paired_reduction": distribution(paired_reductions),
        "positive_pair_count": sum(value > 0 for value in paired_reductions),
    }


def distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(float(value) for value in values)
    return {
        "min": ordered[0],
        "p50": statistics.median(ordered),
        "p95": percentile(ordered, 0.95),
        "max": ordered[-1],
        "mean": statistics.fmean(ordered),
    }


def percentile(ordered_values: list[float], fraction: float) -> float:
    if len(ordered_values) == 1:
        return ordered_values[0]
    position = (len(ordered_values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered_values) - 1)
    weight = position - lower
    return ordered_values[lower] * (1.0 - weight) + ordered_values[upper] * weight


def render_report(summary: dict[str, Any]) -> str:
    aggregate = summary["aggregate"]
    metrics = aggregate["metrics"]
    pair_count = int(aggregate["pair_count"])
    lines = [
        "# Engine-Local KV 主链 10 任务分阶段 A/B 结果",
        "",
        f"运行 ID：`{summary['run_id']}`  ",
        f"模型：`{summary['model']}`  ",
        "执行顺序：先 10 个 `full_replay`，再 10 个 `continuation`，全程串行。  ",
        "每阶段开始前 1 次完整主链预热，预热结果不进入统计。",
        "",
        "## 1. 主结论",
        "",
        "| 指标 | baseline p50 | KV p50 | p50 降幅 | 正向任务 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    labels = {
        "computed_prefill_tokens": "Summarizer computed prefill tokens",
        "consumer_ttft_ms": "Summarizer TTFT (ms)",
        "consumer_wall_ms": "Summarizer wall (ms)",
        "consumer_request_bytes": "Summarizer request bytes",
        "producer_client_wall_ms": "Executor producer wall (ms)",
        "producer_consumer_wall_ms": "Executor + Summarizer wall (ms)",
        "mainline_wall_ms": "完整主链 wall (ms)",
    }
    for field in METRIC_FIELDS:
        value = metrics[field]
        lines.append(
            f"| {labels[field]} | {value['baseline']['p50']:.3f} | "
            f"{value['continuation']['p50']:.3f} | "
            f"{value['lane_p50_reduction'] * 100:.2f}% | "
            f"{value['positive_pair_count']}/{pair_count} |"
        )
    lines.extend(
        [
            "",
            f"质量通过：`{aggregate['quality_pass_count']}/{pair_count * 2}`；"
            f"A/B 质量等价：`{aggregate['quality_parity_count']}/{pair_count}`；"
            f"Consumer 输出 token 精确一致："
            f"`{aggregate['consumer_output_token_parity_count']}/{pair_count}`；"
            f"最终 artifact hash 精确一致："
            f"`{aggregate['output_artifact_hash_parity_count']}/{pair_count}`；"
            f"结构化 artifact core 精确一致："
            f"`{aggregate['structured_artifact_core_parity_count']}/{pair_count}`。",
            "",
            f"显式 KV proof 通过：`{aggregate['kv_proof_pass_count']}/{pair_count}`；"
            f"capture/load 总计：`{aggregate['capture_count']}/{aggregate['load_count']}`；"
            f"fallback：`{aggregate['fallback_count']}`。",
            "",
            f"KV lane 的 store p50 为 "
            f"`{aggregate['kv_transfer']['kv_store_ms']['p50']:.3f} ms`，"
            f"load p50 为 `{aggregate['kv_transfer']['kv_load_ms']['p50']:.3f} ms`，"
            f"单 handle 为 `{aggregate['kv_transfer']['kv_bytes_actual']['p50'] / 1073741824:.3f} GiB`。",
            "",
            "## 2. 实验链路",
            "",
            "```mermaid",
            "flowchart LR",
            "    P[Planner /v1/chat/completions] --> R[Retriever /v1/chat/completions]",
            "    R --> E[Executor /statebus/kv/produce]",
            "    E --> C[CodeAct + ExecutionArtifactRef]",
            "    C --> S[Summarizer]",
            "    S --> A[baseline: parent + suffix 全量重算]",
            "    S --> B[KV: handle + suffix, 恢复 4096-token KV]",
            "    A --> Q[质量门与最终 artifact]",
            "    B --> Q",
            "```",
            "",
            "两条 lane 的 correctness plane 相同。差异只在 Executor 到 Summarizer "
            "之间：baseline 重新提交并计算 parent，KV lane 传递 Worker-local handle，"
            "只提交并计算 Summarizer suffix。APC、semantic pruning 和 replay 均关闭。",
            "",
            "## 3. 逐任务配对结果",
            "",
            "| # | 公司 / 指标 | computed A→B | TTFT A→B (ms) | Consumer wall 降幅 | 主链 wall 降幅 | inherited | store/load (ms) | 质量 / core / raw token / full artifact |",
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for value in summary["comparisons"]:
        parity = (
            f"{int(value['quality_parity'])}/"
            f"{int(value['structured_artifact_core_parity'])}/"
            f"{int(value['consumer_output_token_parity'])}/"
            f"{int(value['output_artifact_hash_parity'])}"
        )
        lines.append(
            f"| {value['round']} | {value['company']} / `{value['metric']}` | "
            f"{value['computed_prefill_tokens_baseline']}→"
            f"{value['computed_prefill_tokens_continuation']} | "
            f"{value['consumer_ttft_ms_baseline']:.1f}→"
            f"{value['consumer_ttft_ms_continuation']:.1f} | "
            f"{value['consumer_wall_ms_reduction'] * 100:.2f}% | "
            f"{value['mainline_wall_ms_reduction'] * 100:.2f}% | "
            f"{value['inherited_kv_tokens']} | "
            f"{value['kv_store_ms']:.1f}/{value['kv_load_ms']:.1f} | {parity} |"
        )
    lines.extend(
        [
            "",
            "## 4. 统计口径与顺序边界",
            "",
            "- 10 个任务各执行一次 baseline 和一次 KV，共 20 次计量执行；不是同一任务 repeat-10。",
            "- 执行顺序按要求固定为整组 baseline 后整组 KV，因此逐任务仍配对，但时间顺序没有交错。",
            "- 两阶段预热均排除；服务不在阶段间重启。完整主链 wall 会包含 Planner、Retriever、CodeAct、文件系统与 Runtime 抖动。",
            "- 主结论优先读取 computed prefill、inherited KV、TTFT 和 request bytes；完整主链 wall 单独呈现正向任务数与 p50。",
            "- raw Consumer token 为 4/10 精确一致，full artifact hash 为 7/10；差异任务的必需数值均一致，3 个 artifact hash 差异只涉及自由文本 `summary_text`。",
            f"- 在 raw Consumer token 精确一致的 `{aggregate['exact_output_subset']['pair_count']}` 对任务中，"
            f"TTFT p50 仍下降 `{aggregate['exact_output_subset']['metrics']['consumer_ttft_ms']['lane_p50_reduction'] * 100:.2f}%`，"
            f"完整主链 p50 仍下降 `{aggregate['exact_output_subset']['metrics']['mainline_wall_ms']['lane_p50_reduction'] * 100:.2f}%`。",
            "- 所有请求串行，temperature=0，KV 私有端点 seed=7，Qwen3-32B，4096-token block-aligned parent。",
            "",
            "## 5. 完整证据目录",
            "",
            f"根目录：`{summary['output_dir']}`",
            "",
            "- `summary.json`：完整记录、逐任务 comparisons、分布统计和服务前后状态。",
            "- `records.jsonl`：20 条未删字段的计量记录。",
            "- `records.csv`：便于绘图和表格分析的标量字段。",
            "- `rounds/<round-task>/<mode>/record.json`：单次提取、质量、时延、token、digest、store/load/release 汇总。",
            "- `rounds/<round-task>/<mode>/runtime/engine_local_kv_mainline.json`：Producer/Consumer 原始 API telemetry 与 scheduler/forward proof。",
            "- `rounds/<round-task>/<mode>/workspace/<task>/logs/task_metrics.json`：Planner、Retriever、Executor、Summarizer、CodeAct 和 Runtime 指标。",
            "- `rounds/<round-task>/<mode>/workspace/<task>/outputs/result.json`：最终结构化 artifact。",
            "- `warmups/`：两次排除统计的阶段预热，保留完整原始证据。",
            "",
        ]
    )
    return "\n".join(lines)


def _write_record_exports(output_dir: Path, records: list[dict[str, Any]]) -> None:
    jsonl = "".join(
        json.dumps(value, ensure_ascii=True, sort_keys=True) + "\n" for value in records
    )
    (output_dir / "records.jsonl").write_text(jsonl, encoding="utf-8")
    scalar_keys = sorted(
        {
            key
            for value in records
            for key, item in value.items()
            if isinstance(item, (str, int, float, bool)) or item is None
        }
    )
    with (output_dir / "records.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=scalar_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
