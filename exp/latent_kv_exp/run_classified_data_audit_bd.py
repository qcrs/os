#!/usr/bin/env python3
"""Classified data audit structured vs latent_kv benchmark.

Task file:
  task/lantent/classified_data_audit_10round/classified_data_audit_tasks.json

The task is synthetic. It is designed to preserve long intermediate reasoning
while keeping the final answer short and exactly gradeable.
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

TASK_FILE = PROJECT / "task/lantent/classified_data_audit_10round/classified_data_audit_tasks.json"
RESULT_ROOT = PROJECT / "exp/latent_kv_exp"

SERVER_PORT = os.getenv("LATENT_KV_SERVER_PORT", "8101")
UNIFIED_BASE_URL = f"http://localhost:{SERVER_PORT}/v1"
UNIFIED_API_KEY = os.getenv("CHAT_API_KEY", "token-abc")
UNIFIED_MODEL = os.getenv("CHAT_MODEL", "/data/models/Qwen3-8B")

REQUIRED_FIELDS = ["case_id", "risk_score", "tier", "action"]
TIER_ACTION = {
    "CRITICAL": "isolate_account_and_open_major_incident",
    "HIGH": "freeze_export_and_start_review",
    "MEDIUM": "require_manager_reapproval",
    "LOW": "log_and_monitor",
}


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
    final_answer: str = ""
    summary: str = ""
    error: str = ""


def load_suite(task_file: Path = TASK_FILE) -> tuple[dict, list[dict]]:
    data = json.loads(task_file.read_text(encoding="utf-8"))
    return data, data["tasks"]


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


def compact_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


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
        "execution_code",
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


def build_prompt(task: dict, suite: dict, history: dict[int, dict]) -> str:
    shared = suite["shared_context"]
    parts = [
        f"# {suite.get('suite_name', 'Classified Data Audit')}",
        "",
        "本任务集为合成脱敏场景，不包含真实涉密数据。你正在运行多 Agent 涉密访问审计流水线。",
        "中间 Agent 必须进行长证据整理、长风险分析和计算矩阵；最终答案必须是短 JSON。",
        "",
        "## Required Intermediate Work",
        "- researcher: 输出 900-1300 中文字证据报告，覆盖每个候选 case 的访问路径、涉密等级、异常原因和历史继承。",
        "- analyst: 输出 900-1300 中文字风险分析，比较 3 个候选 case，并说明最高风险 case 的排序依据。",
        "- executor: 输出计算矩阵，逐 case 列出公式各项、risk_score、tier 和 action。",
        "- summarizer: return only the final JSON object matching the schema.",
        "",
        "## System",
        shared["system"],
        "",
        "## Confidentiality Policy",
        compact_json(shared["confidentiality_policy"]),
        "",
        "## Domain Points",
        compact_json(shared["domain_points"]),
        "",
        "## Channel Points",
        compact_json(shared["channel_points"]),
        "",
        "## Risk Formula",
        shared["risk_formula"],
        "",
        "## Tier Rule",
        compact_json(shared["tier_rule"]),
        "",
        "## Action Rule",
        compact_json(shared["action_rule"]),
        "",
        "## Valid Actions",
        compact_json(shared["valid_actions"]),
    ]

    if history:
        parts.extend(["", "## Prior Round Decisions"])
        for round_id in sorted(history):
            h = history[round_id]
            parts.append(
                f"Round {round_id}: case_id={h.get('case_id')} "
                f"risk_score={h.get('risk_score')} tier={h.get('tier')} action={h.get('action')}"
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
        compact_json(shared["final_answer_contract"]),
        "Use an integer for risk_score. Do not include markdown or explanatory text.",
    ])
    return "\n".join(parts)


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


def normalize_answer(obj: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    out["case_id"] = str(obj.get("case_id", "")).strip()
    try:
        out["risk_score"] = int(str(obj.get("risk_score", "")).replace(",", "").strip())
    except Exception:
        out["risk_score"] = obj.get("risk_score", "")
    out["tier"] = str(obj.get("tier", "")).strip().upper()
    out["action"] = str(obj.get("action", "")).strip()
    return out


def extract_answer(result: Any) -> dict[str, Any]:
    texts: list[str] = []
    if isinstance(result, dict):
        for key in ("final_answer", "summary", "execution_summary"):
            value = result.get(key)
            if value:
                texts.append(str(value))
        extracted = result.get("extracted_answers")
        if isinstance(extracted, dict):
            texts.append(json.dumps(extracted, ensure_ascii=False))
        texts.append(json.dumps(result, ensure_ascii=False))
    else:
        texts.append(str(result))

    for text in texts:
        for obj in find_json_objects(text):
            if all(field in obj for field in REQUIRED_FIELDS):
                return normalize_answer(obj)
            for nested_key in ("summary", "final_answer", "answer"):
                nested = obj.get(nested_key)
                if isinstance(nested, str):
                    for nested_obj in find_json_objects(nested):
                        if all(field in nested_obj for field in REQUIRED_FIELDS):
                            return normalize_answer(nested_obj)

    joined = "\n".join(texts)
    fallback: dict[str, Any] = {}
    patterns = {
        "case_id": r"\b(C-\d{3})\b",
        "risk_score": r"risk_score\W+(\d+)",
        "tier": r"\b(CRITICAL|HIGH|MEDIUM|LOW)\b",
        "action": r"\b(isolate_account_and_open_major_incident|freeze_export_and_start_review|require_manager_reapproval|log_and_monitor)\b",
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
    total = len(REQUIRED_FIELDS)
    return correct, total, correct == total


def run_mode(mode: str, task: dict, suite: dict, history: dict[int, dict], round_id: int) -> RoundStats:
    mode_name = {"B": "B_structured", "D": "D_latent_kv"}[mode]
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

        if mode == "B":
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
                "ANALYST_LATENT_STEPS": os.getenv("ANALYST_LATENT_STEPS", "48"),
                "EXECUTOR_LATENT_STEPS": os.getenv("EXECUTOR_LATENT_STEPS", "24"),
                "POST_EXEC_LATENT_STEPS": os.getenv("POST_EXEC_LATENT_STEPS", "8"),
                "SUMMARIZER_LATENT_STEPS": os.getenv("SUMMARIZER_LATENT_STEPS", "0"),
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
        if isinstance(result, dict):
            stats.final_answer = str(result.get("final_answer", ""))[:2000]
            stats.summary = str(result.get("summary", ""))[:2000]
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


def generate_report(results: list[dict], output_dir: Path, suite: dict) -> None:
    from collections import defaultdict

    by_mode: dict[str, list[dict]] = defaultdict(list)
    for row in results:
        by_mode[row["mode"]].append(row)

    lines = [
        f"# {suite.get('suite_name', 'Classified Data Audit')} B/D Comparison",
        "",
        f"Suite: `{suite['suite_id']}`",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Task note: synthetic classified-data audit; no real sensitive data is included.",
        "Current latent_kv topology: planner/researcher explicit structured packets, then analyst_latent -> executor_latent -> summarizer_latent through server-side KV handles.",
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

    if "B_structured" in by_mode and "D_latent_kv" in by_mode:
        b = sum(r["wall_time_s"] for r in by_mode["B_structured"]) / len(by_mode["B_structured"])
        d = sum(r["wall_time_s"] for r in by_mode["D_latent_kv"]) / len(by_mode["D_latent_kv"])
        lines.extend(["", "## Speed", "", f"- latent_kv vs structured: {(b - d) / b * 100:.1f}%"])

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
            f"answer={json.dumps(row.get('answer', {}), ensure_ascii=False)} "
            f"expected={json.dumps(row.get('expected', {}), ensure_ascii=False)} "
            f"msgs={row.get('message_count', 0)} text_chars={row.get('text_comm_chars', 0)} "
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
    parser = argparse.ArgumentParser(description="Run classified data audit B/D benchmark.")
    parser.add_argument("--modes", nargs="+", default=["B", "D"], choices=["B", "D"])
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--task-file", type=Path, default=TASK_FILE)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    task_file = args.task_file
    if not task_file.is_absolute():
        task_file = PROJECT / task_file
    suite, tasks = load_suite(task_file)
    tasks = tasks[:args.rounds]

    if args.output_dir is None:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        output_dir = RESULT_ROOT / f"classified_data_audit_bd_{stamp}"
    else:
        output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("Classified Data Audit B/D benchmark")
    print(f"modes={args.modes} rounds={len(tasks)}")
    print(f"task={task_file}")
    print(f"output={output_dir}")
    print(f"server={UNIFIED_BASE_URL}")
    print("=" * 72)

    run_manifest = {
        "suite_id": suite["suite_id"],
        "task_file": str(task_file),
        "modes": args.modes,
        "rounds": len(tasks),
        "output_dir": str(output_dir),
        "server_base_url": UNIFIED_BASE_URL,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "resume": args.resume,
        "synthetic_notice": suite.get("synthetic_notice", ""),
    }
    (output_dir / "RUN_MANIFEST.json").write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    all_results: list[dict] = []
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
                f"answer={stats.answer} tok_out={stats.output_tokens} latent={stats.latent_steps}"
            )
            if stats.error:
                print(f"  error: {stats.error[:160]}")

        (output_dir / f"mode_{mode}_all_rounds.json").write_text(
            json.dumps(mode_rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    (output_dir / "all_results.json").write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    generate_report(all_results, output_dir, suite)
    print(f"\nDONE: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
