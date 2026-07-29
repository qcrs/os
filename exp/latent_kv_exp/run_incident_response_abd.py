#!/usr/bin/env python3
"""Trading incident-response A/B/D benchmark.

Task file:
  task/lantent/incident_response_10round/incident_response_tasks.json

This runner intentionally uses the current repository graph implementations:
  A: build_graph(mode="text")
  B: build_graph(mode="structured")
  D: build_latent_kv_graph()
"""

from __future__ import annotations

import argparse
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

TASK_FILE = PROJECT / "task/lantent/incident_response_10round/incident_response_tasks.json"
RESULT_ROOT = PROJECT / "exp/latent_kv_exp"

SERVER_PORT = os.getenv("LATENT_KV_SERVER_PORT", "8101")
UNIFIED_BASE_URL = f"http://localhost:{SERVER_PORT}/v1"
UNIFIED_API_KEY = os.getenv("CHAT_API_KEY", "token-abc")
UNIFIED_MODEL = os.getenv("CHAT_MODEL", "/data/models/Qwen3-8B")

REQUIRED_FIELDS = [
    "root_cause_service",
    "root_cause_code",
    "severity",
    "primary_action",
    "report_deadline_minutes",
    "estimated_loss_usd",
]


@dataclass
class RoundStats:
    round_id: int
    task_id: str
    title: str
    mode: str
    wall_time_s: float = 0.0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latent_steps: int = 0
    kv_bytes_transfer: int = 0
    logical_agent_handoffs: int = 0
    message_count: int = 0
    message_param_chars: int = 0
    message_result_chars: int = 0
    text_comm_chars: int = 0
    text_comm_tokens_est: int = 0
    context_original_chars: int = 0
    context_compressed_chars: int = 0
    context_saved_chars: int = 0
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
    summary: str = ""
    error: str = ""


def load_suite(task_file: Path = TASK_FILE) -> tuple[dict, list[dict]]:
    data = json.loads(task_file.read_text(encoding="utf-8"))
    return data, data["tasks"]


def set_unified_env(comm_mode: str, extra: dict | None = None):
    env = {
        "COMM_MODE": comm_mode,
        "CHAT_BASE_URL": UNIFIED_BASE_URL,
        "CHAT_API_KEY": UNIFIED_API_KEY,
        "CHAT_MODEL": UNIFIED_MODEL,
        "CHAT_DISABLE_THINKING": "1",
        "LATENT_KV_SERVER_PORT": SERVER_PORT,
        "LATENT_KV_SERVER_HOST": "localhost",
    }
    if extra:
        env.update(extra)
    os.environ.update(env)


def collect_metrics(stats: RoundStats, metrics_obj) -> RoundStats:
    d = metrics_obj.summary_dict()
    if not isinstance(d, dict):
        return stats
    stats.llm_calls = d.get("llm_calls", 0)
    stats.input_tokens = d.get("input_tokens", 0)
    stats.output_tokens = d.get("output_tokens", 0)
    stats.latent_steps = d.get("latent_steps_total", 0)
    stats.kv_bytes_transfer = d.get("latent_kv_bytes_transferred", 0)
    stats.message_count = d.get("message_count", 0)
    stats.message_param_chars = d.get("param_chars", 0)
    stats.message_result_chars = d.get("result_chars", 0)
    stats.context_original_chars = d.get("context_original_chars", 0)
    stats.context_compressed_chars = d.get("context_compressed_chars", 0)
    stats.context_saved_chars = d.get("context_saved_chars", 0)
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
    """Estimate text/JSON state payload chars passed through agent handoffs."""
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
        if isinstance(value, str):
            total += len(value)
        else:
            total += len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    return total


def compact_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def build_prompt(task: dict, suite: dict, history: dict[int, dict]) -> str:
    shared = suite["shared_context"]
    parts = [
        f"# {suite.get('suite_name', 'Incident Response Benchmark')}",
        "",
        "You are running a multi-agent incident-response pipeline.",
        "The intermediate agents must be verbose; the final answer must be short structured JSON.",
        "",
        "## Required Intermediate Work",
        "- researcher: produce a 1200-1600 Chinese-character evidence report citing metrics/logs/changes.",
        "- analyst: produce a 1000-1400 Chinese-character causal analysis comparing at least 3 candidate root causes.",
        "- executor: produce a 600-900 Chinese-character calculation and action matrix.",
        "- summarizer: return only the final JSON object matching the schema.",
        "",
        "## Platform",
        shared["system"],
        "",
        "## Severity Rules",
        compact_json(shared["severity_rules"]),
        "",
        "## Loss Formula",
        shared["loss_formula"],
        "",
        "## Reporting Deadline Rule",
        compact_json(shared["reporting_deadline_rule"]),
        "",
        "## Valid Actions",
        compact_json(shared["valid_actions"]),
        "",
        "## Final Output Schema",
        compact_json(shared["final_output_schema"]),
    ]

    if history:
        parts.extend(["", "## Prior Round Decisions"])
        for round_id in sorted(history):
            h = history[round_id]
            parts.append(
                f"Round {round_id}: service={h.get('root_cause_service')} "
                f"severity={h.get('severity')} action={h.get('primary_action')}"
            )

    parts.extend([
        "",
        f"## Current Round {task['round']}: {task['title']}",
        task["prompt"],
        "",
        "## Evidence Packet",
        compact_json(task["evidence_packet"]),
        "",
        "## Final Answer Contract",
        "Return only JSON with exactly these fields:",
        compact_json({field: f"<{field}>" for field in REQUIRED_FIELDS}),
        "Use integer values for report_deadline_minutes and estimated_loss_usd.",
    ])
    return "\n".join(parts)


def normalize_answer(obj: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in REQUIRED_FIELDS:
        value = obj.get(field, "")
        if field in {"report_deadline_minutes", "estimated_loss_usd"}:
            try:
                out[field] = int(str(value).replace(",", "").strip())
            except Exception:
                out[field] = value
        else:
            out[field] = str(value).strip()
    return out


def find_json_objects(text: str) -> list[dict]:
    objects = []
    if not text:
        return objects
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            objects.append(obj)
    return objects


def extract_answer(result: Any) -> dict[str, Any]:
    texts: list[str] = []
    if isinstance(result, dict):
        for key in ("final_answer", "summary", "execution_summary"):
            value = result.get(key)
            if value:
                texts.append(str(value))
        texts.append(json.dumps(result, ensure_ascii=False))
    else:
        texts.append(str(result))

    for text in texts:
        for obj in find_json_objects(text):
            if all(field in obj for field in REQUIRED_FIELDS):
                return normalize_answer(obj)
            # Summarizer may return {"summary": "{...}", ...}
            for nested_key in ("summary", "final_answer", "answer"):
                nested = obj.get(nested_key)
                if isinstance(nested, str):
                    for nested_obj in find_json_objects(nested):
                        if all(field in nested_obj for field in REQUIRED_FIELDS):
                            return normalize_answer(nested_obj)

    joined = "\n".join(texts)
    fallback = {}
    patterns = {
        "root_cause_service": r"root_cause_service\W+([A-Za-z]+)",
        "root_cause_code": r"root_cause_code\W+([A-Za-z0-9_]+)",
        "severity": r"\b(P0|P1|P2)\b",
        "primary_action": r"primary_action\W+([A-Za-z0-9_]+)",
        "report_deadline_minutes": r"report_deadline_minutes\W+(\d+)",
        "estimated_loss_usd": r"estimated_loss_usd\W+([\d,]+)",
    }
    for field, pattern in patterns.items():
        m = re.search(pattern, joined)
        if m:
            fallback[field] = m.group(1)
    return normalize_answer(fallback)


def grade(answer: dict[str, Any], expected: dict[str, Any]) -> tuple[int, int, bool]:
    answer_n = normalize_answer(answer)
    expected_n = normalize_answer(expected)
    correct = sum(1 for f in REQUIRED_FIELDS if answer_n.get(f) == expected_n.get(f))
    total = len(REQUIRED_FIELDS)
    return correct, total, correct == total


def run_mode(mode: str, task: dict, suite: dict, history: dict[int, dict], round_id: int) -> RoundStats:
    mode_name = {"A": "A_text", "B": "B_structured", "D": "D_latent_kv"}[mode]
    stats = RoundStats(
        round_id=round_id,
        task_id=task["task_id"],
        title=task["title"],
        mode=mode_name,
        expected=task["reference_answer"],
        total_fields=len(REQUIRED_FIELDS),
    )
    t0 = time.perf_counter()
    try:
        import importlib
        import config as cfg_mod

        if mode == "A":
            state_mode = "text"
            set_unified_env("text")
            importlib.reload(cfg_mod)
            from graph import build_graph
            from metrics import metrics as m

            m.reset()
            graph, _ = build_graph(mode="text")
        elif mode == "B":
            state_mode = "structured"
            set_unified_env("structured", {"ENABLE_CONTEXT_PACKETS": "1"})
            importlib.reload(cfg_mod)
            from graph import build_graph
            from metrics import metrics as m

            m.reset()
            graph, _ = build_graph(mode="structured")
        else:
            state_mode = "latent_kv"
            set_unified_env("latent_kv", {
                "PLANNER_LATENT_STEPS": os.getenv("PLANNER_LATENT_STEPS", "16"),
                "RESEARCHER_LATENT_STEPS": os.getenv("RESEARCHER_LATENT_STEPS", "32"),
                "ANALYST_LATENT_STEPS": os.getenv("ANALYST_LATENT_STEPS", "64"),
                "EXECUTOR_LATENT_STEPS": os.getenv("EXECUTOR_LATENT_STEPS", "32"),
                "POST_EXEC_LATENT_STEPS": os.getenv("POST_EXEC_LATENT_STEPS", "16"),
                "SUMMARIZER_LATENT_STEPS": os.getenv("SUMMARIZER_LATENT_STEPS", "8"),
            })
            importlib.reload(cfg_mod)
            from graph import build_latent_kv_graph
            from metrics import metrics as m

            m.reset()
            graph, _ = build_latent_kv_graph()

        prompt = build_prompt(task, suite, history)
        result = graph.invoke({
            "query": prompt,
            "task_group": task["task_id"],
            "mode": state_mode,
        })
        stats.logical_agent_handoffs = 4
        stats.text_comm_chars = estimate_text_comm_chars(result)
        stats.text_comm_tokens_est = math.ceil(stats.text_comm_chars / 4)
        stats.summary = str(result.get("summary", ""))[:1000] if isinstance(result, dict) else str(result)[:1000]
        answer = extract_answer(result)
        stats.answer = answer
        correct, total, ok = grade(answer, task["reference_answer"])
        stats.correct_fields = correct
        stats.total_fields = total
        stats.ok = ok
        collect_metrics(stats, m)
    except Exception as exc:  # noqa: BLE001
        import traceback

        stats.error = f"{type(exc).__name__}: {exc}"[:500]
        print(f"[TRACEBACK {mode_name} round {round_id}]\n{traceback.format_exc()}")

    stats.wall_time_s = round(time.perf_counter() - t0, 3)
    return stats


def generate_report(results: list[dict], output_dir: Path, suite: dict):
    from collections import defaultdict

    by_mode: dict[str, list[dict]] = defaultdict(list)
    for row in results:
        by_mode[row["mode"]].append(row)

    lines = [
        f"# {suite.get('suite_name', 'Incident Response')} Comparison",
        "",
        f"Suite: `{suite['suite_id']}`",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Current D implementation note: planner -> researcher use explicit structured packets, then analyst_latent -> executor_latent -> summarizer_latent pass Delta KV sequentially. No explicit reducer agent is used.",
        "",
        "## Summary",
        "",
        "| Mode | Rounds | Avg time(s) | Token in | Token out | Latent steps | KV MB | Field accuracy | Full correct |",
        "|------|-------:|------------:|---------:|----------:|-------------:|------:|---------------:|-------------:|",
    ]
    for mode in sorted(by_mode):
        rows = by_mode[mode]
        n = len(rows)
        avg = lambda k: sum(float(r.get(k, 0) or 0) for r in rows) / n if n else 0
        correct_fields = sum(int(r.get("correct_fields", 0) or 0) for r in rows)
        total_fields = sum(int(r.get("total_fields", 0) or 0) for r in rows)
        full_correct = sum(1 for r in rows if r.get("ok"))
        lines.append(
            f"| {mode} | {n} | {avg('wall_time_s'):.1f} | {avg('input_tokens'):.0f} | "
            f"{avg('output_tokens'):.0f} | {avg('latent_steps'):.0f} | "
            f"{avg('kv_bytes_transfer') / 1024 / 1024:.0f} | "
            f"{correct_fields}/{total_fields} | {full_correct}/{n} |"
        )

    if "A_text" in by_mode and "D_latent_kv" in by_mode:
        a = sum(r["wall_time_s"] for r in by_mode["A_text"]) / len(by_mode["A_text"])
        d = sum(r["wall_time_s"] for r in by_mode["D_latent_kv"]) / len(by_mode["D_latent_kv"])
        lines.extend(["", "## D Speed", "", f"- D vs A: {(a - d) / a * 100:.1f}%"])
    if "B_structured" in by_mode and "D_latent_kv" in by_mode:
        b = sum(r["wall_time_s"] for r in by_mode["B_structured"]) / len(by_mode["B_structured"])
        d = sum(r["wall_time_s"] for r in by_mode["D_latent_kv"]) / len(by_mode["D_latent_kv"])
        lines.append(f"- D vs B: {(b - d) / b * 100:.1f}%")

    lines.extend([
        "",
        "## Communication",
        "",
        "| Mode | Msgs | Handoffs | Text chars | Text tok est | Non-text transfers | Non-text MB | Context chars orig/comp |",
        "|------|-----:|---------:|-----------:|-------------:|-------------------:|------------:|------------------------:|",
    ])
    for mode in sorted(by_mode):
        rows = by_mode[mode]
        n = len(rows)
        avg = lambda k: sum(float(r.get(k, 0) or 0) for r in rows) / n if n else 0
        lines.append(
            f"| {mode} | {avg('message_count'):.1f} | {avg('logical_agent_handoffs'):.1f} | "
            f"{avg('text_comm_chars'):.0f} | {avg('text_comm_tokens_est'):.0f} | "
            f"{avg('nontext_transfer_count'):.1f} | "
            f"{avg('nontext_transfer_bytes') / 1024 / 1024:.2f} | "
            f"{avg('context_original_chars'):.0f}/{avg('context_compressed_chars'):.0f} |"
        )

    lines.extend(["", "## Rounds", ""])
    for row in results:
        lines.append(
            f"- {row['mode']} R{row['round_id']:02d} {row['wall_time_s']:.1f}s "
            f"fields={row['correct_fields']}/{row['total_fields']} "
            f"msgs={row.get('message_count', 0)} "
            f"text_chars={row.get('text_comm_chars', 0)} "
            f"nontext={row.get('nontext_transfer_count', 0)}/"
            f"{row.get('nontext_transfer_bytes', 0) // 1024}KB "
            f"latent={row['latent_steps']} err={row.get('error', '')[:80]}"
        )

    (output_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def _round_file(output_dir: Path, mode: str, i: int, task: dict) -> Path:
    return output_dir / f"round_{mode}_{i:02d}_{task['task_id']}.json"


def _load_existing_round(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    required = {"round_id", "task_id", "mode", "wall_time_s"}
    if not isinstance(row, dict) or not required.issubset(row):
        return None
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Run incident response A/B/D benchmark.")
    parser.add_argument("--modes", nargs="+", default=["A", "B", "D"], choices=["A", "B", "D"])
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--task-file", type=Path, default=TASK_FILE)
    parser.add_argument("--resume", action="store_true", help="Skip completed round_*.json files in output-dir.")
    args = parser.parse_args()

    task_file = args.task_file
    if not task_file.is_absolute():
        task_file = PROJECT / task_file
    suite, tasks = load_suite(task_file)
    tasks = tasks[:args.rounds]
    if args.output_dir is None:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        output_dir = RESULT_ROOT / f"incident_response_abd_{stamp}"
    else:
        output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("Incident Response ABD benchmark")
    print(f"modes={args.modes} rounds={len(tasks)}")
    print(f"task={task_file}")
    print(f"output={output_dir}")
    print(f"server={UNIFIED_BASE_URL}")
    print("=" * 72)

    all_results: list[dict] = []
    run_manifest = {
        "suite_id": suite["suite_id"],
        "task_file": str(task_file),
        "modes": args.modes,
        "rounds": len(tasks),
        "output_dir": str(output_dir),
        "server_base_url": UNIFIED_BASE_URL,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "resume": args.resume,
        "current_d_topology": (
            "planner -> researcher are explicit structured; analyst -> executor -> "
            "summarizer continue sequentially through Delta KV; no reducer agent"
        ),
    }
    (output_dir / "RUN_MANIFEST.json").write_text(json.dumps(run_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    for mode in args.modes:
        print(f"\n--- Mode {mode} ---")
        history: dict[int, dict] = {}
        mode_rows = []
        for i, task in enumerate(tasks, 1):
            path = _round_file(output_dir, mode, i, task)
            if args.resume:
                existing = _load_existing_round(path)
                if existing is not None:
                    all_results.append(existing)
                    mode_rows.append(existing)
                    if existing.get("answer"):
                        history[i] = existing["answer"]
                    print(
                        f"[{mode} {i:02d}/{len(tasks):02d}] {task['title']}\n"
                        f"  SKIP existing {existing.get('wall_time_s', 0):.1f}s "
                        f"fields={existing.get('correct_fields', 0)}/{existing.get('total_fields', 0)}"
                    )
                    continue

            print(f"[{mode} {i:02d}/{len(tasks):02d}] {task['title']}")
            stats = run_mode(mode, task, suite, history, i)
            row = asdict(stats)
            all_results.append(row)
            mode_rows.append(row)
            if stats.answer:
                history[i] = stats.answer

            path.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                f"  {'OK' if stats.ok else 'MISS'} {stats.wall_time_s:.1f}s "
                f"fields={stats.correct_fields}/{stats.total_fields} "
                f"tok_out={stats.output_tokens} latent={stats.latent_steps}"
            )
            if stats.error:
                print(f"  error: {stats.error[:160]}")

        (output_dir / f"mode_{mode}_all_rounds.json").write_text(
            json.dumps(mode_rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    (output_dir / "all_results.json").write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    generate_report(all_results, output_dir, suite)
    print(f"\nDONE: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
