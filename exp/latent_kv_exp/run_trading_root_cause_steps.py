#!/usr/bin/env python3
"""Run structured vs kv_latent latent-step ablation on one root-cause task."""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parent.parent.parent
SRC = PROJECT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TASK_FILE = PROJECT / "task/lantent/trading_root_cause_1round/trading_root_cause_task.json"
SERVER_PORT = os.getenv("LATENT_KV_SERVER_PORT", "8101")
UNIFIED_BASE_URL = f"http://localhost:{SERVER_PORT}/v1"
UNIFIED_API_KEY = os.getenv("CHAT_API_KEY", "token-abc")
UNIFIED_MODEL = os.getenv("CHAT_MODEL", "/data/models/Qwen3-8B")

REQUIRED_FIELDS = ["root_cause", "severity", "first_bad_component"]
STEP_CONFIGS = {
    "kv_latent_0": {"ANALYST_LATENT_STEPS": "0", "EXECUTOR_LATENT_STEPS": "0", "POST_EXEC_LATENT_STEPS": "0", "SUMMARIZER_LATENT_STEPS": "0"},
    "kv_latent_16": {"ANALYST_LATENT_STEPS": "8", "EXECUTOR_LATENT_STEPS": "8", "POST_EXEC_LATENT_STEPS": "0", "SUMMARIZER_LATENT_STEPS": "0"},
    "kv_latent_32": {"ANALYST_LATENT_STEPS": "16", "EXECUTOR_LATENT_STEPS": "16", "POST_EXEC_LATENT_STEPS": "0", "SUMMARIZER_LATENT_STEPS": "0"},
    "kv_latent_56": {"ANALYST_LATENT_STEPS": "32", "EXECUTOR_LATENT_STEPS": "16", "POST_EXEC_LATENT_STEPS": "8", "SUMMARIZER_LATENT_STEPS": "0"},
    "kv_latent_80": {"ANALYST_LATENT_STEPS": "48", "EXECUTOR_LATENT_STEPS": "24", "POST_EXEC_LATENT_STEPS": "8", "SUMMARIZER_LATENT_STEPS": "0"},
    "kv_latent_120": {"ANALYST_LATENT_STEPS": "64", "EXECUTOR_LATENT_STEPS": "32", "POST_EXEC_LATENT_STEPS": "16", "SUMMARIZER_LATENT_STEPS": "8"},
}


@dataclass
class RunStats:
    mode: str
    task_id: str
    title: str
    wall_time_s: float = 0.0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latent_steps: int = 0
    kv_bytes_transfer: int = 0
    message_count: int = 0
    logical_agent_handoffs: int = 4
    text_comm_chars: int = 0
    text_comm_tokens_est: int = 0
    embedding_transfer_count: int = 0
    embedding_transfer_bytes: int = 0
    latent_kv_transfer_count: int = 0
    latent_kv_transfer_bytes: int = 0
    nontext_transfer_count: int = 0
    nontext_transfer_bytes: int = 0
    answer: dict[str, Any] | None = None
    expected: dict[str, Any] | None = None
    correct_fields: int = 0
    total_fields: int = 0
    ok: bool = False
    final_answer: str = ""
    summary: str = ""
    execution_tool: str = ""
    step_config: dict[str, str] | None = None
    error: str = ""


def load_suite(task_file: Path) -> tuple[dict, list[dict]]:
    data = json.loads(task_file.read_text(encoding="utf-8"))
    return data, data["tasks"]


def compact_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def build_prompt(task: dict, suite: dict) -> str:
    shared = suite["shared_context"]
    parts = [
        f"# {suite.get('suite_name', 'Trading Root Cause Benchmark')}",
        "",
        suite.get("synthetic_notice", ""),
        "",
        "## Benchmark Goal",
        suite.get("design_goal", ""),
        "",
        "## Fairness Controls",
        compact_json(suite.get("fairness_controls", [])),
        "",
        "## Required Intermediate Work",
        *[f"- {item}" for item in shared.get("required_intermediate_work", [])],
        "",
        "## Platform",
        shared["system"],
        "",
        "## Allowed Root Cause Labels",
        compact_json(shared["allowed_root_cause_labels"]),
        "",
        "## Allowed Components",
        compact_json(shared["allowed_components"]),
        "",
        "## Severity Rule",
        compact_json(shared["severity_rule"]),
        "",
        f"## Current Round {task['round']}: {task['title']}",
        task["prompt"],
        "",
        "## Evidence Packet",
        compact_json(task["evidence_packet"]),
        "",
        "## Final Answer Contract",
        "Return only JSON with exactly these fields:",
        compact_json(shared["final_answer_contract"]),
        "Do not include markdown or explanatory text.",
    ]
    return "\n".join(part for part in parts if part != "")


def set_unified_env(comm_mode: str, extra: dict[str, str] | None = None) -> None:
    env = {
        "COMM_MODE": comm_mode,
        "CHAT_BASE_URL": UNIFIED_BASE_URL,
        "CHAT_API_KEY": UNIFIED_API_KEY,
        "CHAT_MODEL": UNIFIED_MODEL,
        "CHAT_DISABLE_THINKING": "1",
        "LATENT_KV_BACKEND": os.getenv("LATENT_KV_BACKEND", "real"),
        "LATENT_KV_SERVER_PORT": SERVER_PORT,
        "LATENT_KV_SERVER_HOST": "localhost",
        "ENABLE_CONTEXT_PACKETS": "1",
    }
    if extra:
        env.update(extra)
    os.environ.update(env)


def collect_metrics(stats: RunStats, metrics_obj) -> RunStats:
    d = metrics_obj.summary_dict()
    if not isinstance(d, dict):
        return stats
    stats.llm_calls = d.get("llm_calls", 0)
    stats.input_tokens = d.get("input_tokens", 0)
    stats.output_tokens = d.get("output_tokens", 0)
    stats.latent_steps = d.get("latent_steps_total", 0)
    stats.kv_bytes_transfer = d.get("latent_kv_bytes_transferred", 0)
    stats.message_count = d.get("message_count", 0)
    stats.embedding_transfer_count = d.get("embedding_transfers", 0)
    stats.embedding_transfer_bytes = sum(
        int(msg.get("embedding_dims", 0) or 0) * 4
        for msg in getattr(metrics_obj, "message_log", [])
        if msg.get("has_embedding")
    )
    stats.latent_kv_transfer_count = len(getattr(metrics_obj, "latent_kv_bytes_log", []))
    stats.latent_kv_transfer_bytes = d.get("latent_kv_bytes_transferred", 0)
    stats.nontext_transfer_count = stats.embedding_transfer_count + stats.latent_kv_transfer_count
    stats.nontext_transfer_bytes = stats.embedding_transfer_bytes + stats.latent_kv_transfer_bytes
    return stats


def estimate_text_comm_chars(result: Any) -> int:
    if not isinstance(result, dict):
        return len(str(result))
    fields = [
        "plan",
        "sub_queries",
        "documents",
        "document_payloads",
        "context_packets",
        "research_evidence",
        "analysis",
        "analysis_digest",
        "candidate_answers",
        "evidence",
        "selected_context_packets",
        "execution_summary",
        "execution_result",
        "final_answer",
        "extracted_answers",
        "summary",
        "key_findings",
    ]
    total = 0
    for field in fields:
        value = result.get(field)
        if value in (None, "", [], {}):
            continue
        total += len(value) if isinstance(value, str) else len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    return total


def find_json_objects(text: str) -> list[dict]:
    objects: list[dict] = []
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text or ""):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            objects.append(obj)
    return objects


def normalize_answer(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "root_cause": str(obj.get("root_cause", "")).strip(),
        "severity": str(obj.get("severity", "")).strip().upper(),
        "first_bad_component": str(obj.get("first_bad_component", "")).strip(),
    }


def extract_answer(result: Any) -> dict[str, Any]:
    texts: list[str] = []
    if isinstance(result, dict):
        for key in ("final_answer", "summary", "execution_summary"):
            if result.get(key):
                texts.append(str(result[key]))
        if isinstance(result.get("extracted_answers"), dict):
            texts.append(json.dumps(result["extracted_answers"], ensure_ascii=False))
        texts.append(json.dumps(result, ensure_ascii=False))
    else:
        texts.append(str(result))
    for text in texts:
        for obj in find_json_objects(text):
            if all(field in obj for field in REQUIRED_FIELDS):
                return normalize_answer(obj)
    joined = "\n".join(texts)
    fallback: dict[str, Any] = {}
    patterns = {
        "root_cause": r"\b(ordergateway_auth_cache_key_normalization|riskengine_false_positive_rule|matchingcore_queue_starvation|marketdata_provider_skew|clearing_batch_backpressure|settlement_deadlock|auditlogger_index_lag|unknown)\b",
        "severity": r"\b(P0|P1|P2)\b",
        "first_bad_component": r"\b(OrderGateway|RiskEngine|MatchingCore|ClearingService|SettlementService|MarketDataFeed|AuditLogger|PositionManager|RegulatoryReporter)\b",
    }
    for field, pattern in patterns.items():
        matches = re.findall(pattern, joined)
        if matches:
            fallback[field] = matches[-1]
    return normalize_answer(fallback)


def grade(answer: dict[str, Any], expected: dict[str, Any]) -> tuple[int, int, bool]:
    answer_n = normalize_answer(answer)
    expected_n = normalize_answer(expected)
    correct = sum(1 for field in REQUIRED_FIELDS if answer_n.get(field) == expected_n.get(field))
    return correct, len(REQUIRED_FIELDS), correct == len(REQUIRED_FIELDS)


def run_mode(mode: str, task: dict, suite: dict) -> RunStats:
    stats = RunStats(
        mode=mode,
        task_id=task["task_id"],
        title=task["title"],
        expected=task["reference_answer"],
        total_fields=len(REQUIRED_FIELDS),
        step_config=STEP_CONFIGS.get(mode),
    )
    t0 = time.perf_counter()
    try:
        import config as cfg_mod

        if mode == "structured":
            state_mode = "structured"
            set_unified_env("structured")
            importlib.reload(cfg_mod)
            from graph import build_graph
            from metrics import metrics as m

            m.reset()
            graph, _ = build_graph(mode="structured")
        else:
            state_mode = "latent_kv"
            set_unified_env("latent_kv", STEP_CONFIGS[mode])
            importlib.reload(cfg_mod)
            import agent.latent_kv_agents as latent_agents_mod

            importlib.reload(latent_agents_mod)
            from graph import build_latent_kv_graph
            from metrics import metrics as m

            m.reset()
            graph, _ = build_latent_kv_graph()
        result = graph.invoke({"query": build_prompt(task, suite), "task_group": f"{task['task_id']}_{mode}", "mode": state_mode})
        stats.text_comm_chars = estimate_text_comm_chars(result)
        stats.text_comm_tokens_est = math.ceil(stats.text_comm_chars / 4)
        if isinstance(result, dict):
            stats.final_answer = str(result.get("final_answer", ""))[:2000]
            stats.summary = str(result.get("summary", ""))[:2000]
            execution_result = result.get("execution_result")
            if isinstance(execution_result, dict) and isinstance(execution_result.get("metrics"), dict):
                stats.execution_tool = str(execution_result["metrics"].get("tool", ""))
        stats.answer = extract_answer(result)
        stats.correct_fields, stats.total_fields, stats.ok = grade(stats.answer, task["reference_answer"])
        collect_metrics(stats, m)
    except Exception as exc:  # noqa: BLE001
        import traceback

        stats.error = f"{type(exc).__name__}: {exc}"[:500]
        print(f"[TRACEBACK {mode}]\n{traceback.format_exc()}")
    stats.wall_time_s = round(time.perf_counter() - t0, 3)
    return stats


def generate_report(results: list[dict], output_dir: Path, suite: dict) -> None:
    lines = [
        "# Trading Root Cause structured vs kv_latent Step Ablation",
        "",
        f"Suite: `{suite['suite_id']}`",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Executor code/tools are disabled by prompt and by agent no-code path.",
        "",
        "| Mode | Steps A/E/P/S | Time(s) | Token in | Token out | Latent steps | KV MB | Msgs | Text chars | Non-text MB | Fields | Answer |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in results:
        cfg = row.get("step_config") or {}
        cfg_text = "-" if not cfg else f"{cfg['ANALYST_LATENT_STEPS']}/{cfg['EXECUTOR_LATENT_STEPS']}/{cfg['POST_EXEC_LATENT_STEPS']}/{cfg['SUMMARIZER_LATENT_STEPS']}"
        lines.append(
            f"| {row['mode']} | {cfg_text} | {row['wall_time_s']:.3f} | {row.get('input_tokens', 0)} | "
            f"{row.get('output_tokens', 0)} | {row.get('latent_steps', 0)} | "
            f"{(row.get('kv_bytes_transfer', 0) or 0) / 1024 / 1024:.2f} | "
            f"{row.get('message_count', 0)} | {row.get('text_comm_chars', 0)} | "
            f"{(row.get('nontext_transfer_bytes', 0) or 0) / 1024 / 1024:.2f} | "
            f"{row.get('correct_fields', 0)}/{row.get('total_fields', 0)} | "
            f"`{json.dumps(row.get('answer', {}), ensure_ascii=False)}` |"
        )
    lines.extend(["", "Expected:", "", f"`{json.dumps(results[0].get('expected', {}), ensure_ascii=False)}`"])
    (output_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run root-cause latent step ablation.")
    parser.add_argument("--task-file", type=Path, default=TASK_FILE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--modes", nargs="+", default=["structured", *STEP_CONFIGS.keys()])
    args = parser.parse_args()
    task_file = args.task_file if args.task_file.is_absolute() else PROJECT / args.task_file
    suite, tasks = load_suite(task_file)
    task = tasks[0]
    output_dir = args.output_dir if args.output_dir.is_absolute() else PROJECT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    print("=" * 72)
    print("Trading Root Cause structured vs kv_latent step ablation")
    print(f"modes={args.modes}")
    print(f"task={task_file}")
    print(f"output={output_dir}")
    print(f"server={UNIFIED_BASE_URL}")
    print("=" * 72)
    (output_dir / "RUN_MANIFEST.json").write_text(json.dumps({
        "suite_id": suite["suite_id"],
        "task_file": str(task_file),
        "modes": args.modes,
        "output_dir": str(output_dir),
        "server_base_url": UNIFIED_BASE_URL,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "step_configs": STEP_CONFIGS,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    results = []
    for mode in args.modes:
        print(f"\n--- {mode} ---")
        row = asdict(run_mode(mode, task, suite))
        results.append(row)
        (output_dir / f"{mode}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"  {'OK' if row['ok'] else 'MISS'} {row['wall_time_s']:.1f}s "
            f"fields={row['correct_fields']}/{row['total_fields']} answer={row['answer']} "
            f"latent={row['latent_steps']} tool={row.get('execution_tool') or '-'}"
        )
        if row.get("error"):
            print(f"  error: {row['error'][:180]}")
    (output_dir / "all_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    generate_report(results, output_dir, suite)
    print(f"\nDONE: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
