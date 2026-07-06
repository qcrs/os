#!/usr/bin/env python3
"""Orchestrate Protocol A vs Protocol B comparison on one task group.

Runs run_group1_single.py as a subprocess for each protocol, extracts answers,
compares with gold, and saves results to task/result/group{n}_comparison.json.

Usage (inside SynapseX-wmw container):
    cd /data/mingwei/SynapseX/task
    python3 run_group1_comparison.py
"""

import json
import os
import subprocess
import sys
import re
from datetime import datetime, timezone
from json import JSONDecodeError
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TASK_DIR.parent.parent
RESULT_DIR = TASK_DIR / "result"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# ── Base environment for container runs ──────────────────────────────
def _env_default(name: str, default: str) -> str:
    return os.environ.get(name, default)


BASE_ENV = {
    "CHAT_BACKEND": _env_default("CHAT_BACKEND", "transformers"),
    "CHAT_API_KEY": _env_default("CHAT_API_KEY", "EMPTY"),
    "CHAT_BASE_URL": _env_default("CHAT_BASE_URL", "http://127.0.0.1:8000/v1"),
    "CHAT_MODEL": _env_default("CHAT_MODEL", "/data/models/Qwen3-8B"),
    "CHAT_DISABLE_THINKING": _env_default("CHAT_DISABLE_THINKING", "1"),
    "LOCAL_MODEL_PATH": _env_default("LOCAL_MODEL_PATH", "/data/models/Qwen3-8B"),
    "LOCAL_MODEL_DEVICE": _env_default("LOCAL_MODEL_DEVICE", "cuda:0"),
    "LOCAL_MODEL_DTYPE": _env_default("LOCAL_MODEL_DTYPE", "bfloat16"),
    "LOCAL_TRANSFORMERS_MAX_NEW_TOKENS": _env_default("LOCAL_TRANSFORMERS_MAX_NEW_TOKENS", "512"),
    "ENABLE_CODEACT_EXECUTOR": _env_default("ENABLE_CODEACT_EXECUTOR", "1"),
    "DASHSCOPE_API_KEY": "",
    "PYTHONPATH": os.pathsep.join([
        str(PROJECT_ROOT / "src"),
        str(PROJECT_ROOT / "third_party" / "langgraph" / "libs" / "langgraph"),
        str(PROJECT_ROOT / "third_party" / "langgraph" / "libs" / "checkpoint"),
    ]),
}


def _group_files(group: int) -> tuple[Path, Path, Path]:
    tasks_file = TASK_DIR / f"group{group}_tasks.json"
    gold_file = TASK_DIR / f"group{group}_gold.json"
    output_file = RESULT_DIR / f"group{group}_comparison.json"
    return tasks_file, gold_file, output_file


def _single_protocol_output_file(group: int, mode: str) -> Path:
    return RESULT_DIR / f"group{group}_{mode}_only.json"


def _coerce_subprocess_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _parse_protocol_json(stdout_text: str, mode: str) -> dict:
    json_start = stdout_text.find("{")
    if json_start < 0:
        print("[ERROR] subprocess did not emit JSON", file=sys.stderr)
        print(f"STDOUT tail:\n{stdout_text[-1000:]}", file=sys.stderr)
        return {"mode": mode, "rounds": [], "error": "missing_json_output"}

    try:
        return json.loads(stdout_text[json_start:])
    except JSONDecodeError as exc:
        print(f"[ERROR] bad JSON: {exc}", file=sys.stderr)
        print(f"STDOUT tail:\n{stdout_text[-1000:]}", file=sys.stderr)
        return {"mode": mode, "rounds": [], "error": str(exc)}


def run_protocol(group: int, mode: str, extra_env: dict | None = None, timeout_s: int = 1800) -> dict:
    """Invoke run_group1_single.py as a subprocess and parse its JSON output."""
    env = {
        **__import__("os").environ,
        **BASE_ENV,
        **(extra_env or {}),
    }
    cmd = [
        sys.executable, "-u",
        str(TASK_DIR / "run_group1_single.py"),
        "--group", str(group),
        "--mode", mode,
    ]
    print(f"\n{'='*60}")
    print(f"Running Protocol {'A' if mode == 'text' else 'B'} ({mode} mode)...")
    print(f"{'='*60}")

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_text = _coerce_subprocess_text(exc.stdout)
        stderr_text = _coerce_subprocess_text(exc.stderr)
        print(f"[ERROR] subprocess timed out after {timeout_s}s", file=sys.stderr)
        if stderr_text:
            print(f"STDERR tail:\n{stderr_text[-2000:]}", file=sys.stderr)

        partial = _parse_protocol_json(stdout_text, mode) if stdout_text else {"mode": mode, "rounds": []}
        partial["mode"] = mode
        partial["timed_out"] = True
        partial["timeout_s"] = timeout_s
        partial["error"] = f"timeout_after_{timeout_s}s"
        if stderr_text:
            partial["stderr_tail"] = stderr_text[-2000:]
        if stdout_text and "rounds" not in partial:
            partial["rounds"] = []
        return partial

    if proc.returncode != 0:
        print(f"[ERROR] subprocess exited {proc.returncode}", file=sys.stderr)
        print(f"STDERR:\n{proc.stderr[-2000:]}", file=sys.stderr)
        return {
            "mode": mode,
            "rounds": [],
            "error": proc.stderr[-500:],
            "returncode": proc.returncode,
        }

    return _parse_protocol_json(proc.stdout, mode)


# ── Answer comparison ────────────────────────────────────────────────

FLOAT_RE = re.compile(r"^-?\d+\.\d+$")
BOOL_MAP = {"true": "True", "false": "False", "1": "True", "0": "False"}


def normalize_value(raw: str, gold_val: str) -> str:
    """Normalize extracted value for comparison."""
    v = raw.strip()
    # Boolean normalization
    if gold_val.lower() in ("true", "false"):
        return BOOL_MAP.get(v.lower(), v)
    # Float normalization: match decimal places of gold
    if FLOAT_RE.match(gold_val):
        try:
            decimals = len(gold_val.split(".")[1])
            return f"{float(v):.{decimals}f}"
        except (ValueError, IndexError):
            return v
    return v


def compare_answers(extracted: dict[str, str], gold_items: list[list[str]]) -> dict:
    """Compare extracted answers against gold. Returns match details."""
    results = []
    for field_name, gold_val in gold_items:
        extracted_val = extracted.get(field_name, "")
        if not extracted_val:
            results.append({
                "field": field_name,
                "gold": gold_val,
                "extracted": "",
                "match": False,
                "reason": "not_found",
            })
            continue
        norm = normalize_value(extracted_val, gold_val)
        match = norm == gold_val
        results.append({
            "field": field_name,
            "gold": gold_val,
            "extracted": extracted_val,
            "normalized": norm,
            "match": match,
        })
    correct = sum(1 for r in results if r["match"])
    return {
        "details": results,
        "correct": correct,
        "total": len(results),
        "accuracy": round(correct / max(len(results), 1), 4),
    }


def compute_protocol_stats(rounds: list[dict]) -> dict:
    """Aggregate per-round stats into protocol-level summary."""
    durations = [r["duration_s"] for r in rounds if r.get("duration_s")]
    return {
        "total_rounds": len(rounds),
        "total_duration_s": round(sum(durations), 2),
        "avg_duration_s": round(sum(durations) / max(len(durations), 1), 2),
        "min_duration_s": round(min(durations), 2) if durations else 0,
        "max_duration_s": round(max(durations), 2) if durations else 0,
    }


# ── Main ─────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Compare text vs structured on one task group")
    parser.add_argument("--group", type=int, choices=[1, 2, 3], default=1)
    parser.add_argument(
        "--mode",
        choices=["both", "text", "structured"],
        default="both",
        help="Run both protocols, or only one protocol and save its standalone result.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Per-protocol subprocess timeout in seconds.",
    )
    args = parser.parse_args()

    tasks_file, gold_file, output_file = _group_files(args.group)
    tasks = json.loads(tasks_file.read_text(encoding="utf-8"))["tasks"]
    gold = json.loads(gold_file.read_text(encoding="utf-8"))

    if args.mode == "text":
        result_a = run_protocol(args.group, "text", timeout_s=args.timeout)
        standalone_path = _single_protocol_output_file(args.group, "text")
        standalone_path.write_text(json.dumps(result_a, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nResults saved to {standalone_path}")
        return

    if args.mode == "structured":
        result_b = run_protocol(args.group, "structured", {
            "ENABLE_CONTEXT_PACKETS": "1",
            "ENABLE_EMBEDDING_TRANSFER": "0",
        }, timeout_s=args.timeout)
        standalone_path = _single_protocol_output_file(args.group, "structured")
        standalone_path.write_text(json.dumps(result_b, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nResults saved to {standalone_path}")
        return

    # ── Protocol A: text mode ────────────────────────────────────────
    result_a = run_protocol(args.group, "text", timeout_s=args.timeout)
    text_output_path = _single_protocol_output_file(args.group, "text")
    text_output_path.write_text(json.dumps(result_a, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nText-only result saved to {text_output_path}")

    # ── Protocol B: structured, compressed text only ─────────────────
    result_b = run_protocol(args.group, "structured", {
        "ENABLE_CONTEXT_PACKETS": "1",
        "ENABLE_EMBEDDING_TRANSFER": "0",
    }, timeout_s=args.timeout)
    structured_output_path = _single_protocol_output_file(args.group, "structured")
    structured_output_path.write_text(json.dumps(result_b, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nStructured-only result saved to {structured_output_path}")

    # ── Compare answers with gold ────────────────────────────────────
    comparison_a = []
    comparison_b = []

    for task in tasks:
        tid = str(task["id"])
        gold_items = gold.get(tid, [])
        round_num = task["round"]

        # Protocol A
        ra = next((r for r in result_a.get("rounds", []) if r["round"] == round_num), {})
        comp_a = compare_answers(ra.get("extracted_answers", {}), gold_items)
        comp_a["round"] = round_num
        comp_a["task_id"] = task["id"]
        comp_a["question"] = task["question"]
        comp_a["duration_s"] = ra.get("duration_s", 0)
        comparison_a.append(comp_a)

        # Protocol B
        rb = next((r for r in result_b.get("rounds", []) if r["round"] == round_num), {})
        comp_b = compare_answers(rb.get("extracted_answers", {}), gold_items)
        comp_b["round"] = round_num
        comp_b["task_id"] = task["id"]
        comp_b["question"] = task["question"]
        comp_b["duration_s"] = rb.get("duration_s", 0)
        comparison_b.append(comp_b)

    # ── Aggregate ────────────────────────────────────────────────────
    total_correct_a = sum(c["correct"] for c in comparison_a)
    total_correct_b = sum(c["correct"] for c in comparison_b)
    total_fields = sum(c["total"] for c in comparison_a)

    stats_a = compute_protocol_stats(result_a.get("rounds", []))
    stats_b = compute_protocol_stats(result_b.get("rounds", []))

    metrics_a = result_a.get("metrics_summary", {})
    metrics_b = result_b.get("metrics_summary", {})

    output = {
        "experiment": {
            "name": f"group{args.group}_protocol_comparison",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "tasks": f"{tasks_file.name} ({len(tasks)} rounds)",
            "container": _env_default("EXPERIMENT_CONTAINER", "SynapseX-wang"),
            "backend": BASE_ENV["CHAT_BACKEND"],
            "base_url": BASE_ENV["CHAT_BASE_URL"],
            "model": BASE_ENV["CHAT_MODEL"],
        },
        "protocol_a": {
            "label": "Plain Text (mode=text)",
            "config": {"mode": "text"},
            "error": result_a.get("error", ""),
            "timed_out": bool(result_a.get("timed_out", False)),
            "stats": stats_a,
            "metrics": {
                "llm_calls": metrics_a.get("llm_calls", 0),
                "input_tokens": metrics_a.get("input_tokens", 0),
                "output_tokens": metrics_a.get("output_tokens", 0),
                "total_tokens": metrics_a.get("total_tokens", 0),
                "context_original_chars": metrics_a.get("context_original_chars", 0),
                "context_compressed_chars": metrics_a.get("context_compressed_chars", 0),
                "context_saved_chars": metrics_a.get("context_saved_chars", 0),
            },
            "accuracy": {
                "total_correct": total_correct_a,
                "total_fields": total_fields,
                "overall_accuracy": round(total_correct_a / max(total_fields, 1), 4),
            },
            "per_round": comparison_a,
        },
        "protocol_b": {
            "label": "Structured Compressed Text Only (mode=structured, context_packets only)",
            "config": {
                "mode": "structured",
                "ENABLE_CONTEXT_PACKETS": True,
                "ENABLE_EMBEDDING_TRANSFER": False,
            },
            "error": result_b.get("error", ""),
            "timed_out": bool(result_b.get("timed_out", False)),
            "stats": stats_b,
            "metrics": {
                "llm_calls": metrics_b.get("llm_calls", 0),
                "input_tokens": metrics_b.get("input_tokens", 0),
                "output_tokens": metrics_b.get("output_tokens", 0),
                "total_tokens": metrics_b.get("total_tokens", 0),
                "context_original_chars": metrics_b.get("context_original_chars", 0),
                "context_compressed_chars": metrics_b.get("context_compressed_chars", 0),
                "context_saved_chars": metrics_b.get("context_saved_chars", 0),
            },
            "accuracy": {
                "total_correct": total_correct_b,
                "total_fields": total_fields,
                "overall_accuracy": round(total_correct_b / max(total_fields, 1), 4),
            },
            "per_round": comparison_b,
        },
        "comparison": {
            "accuracy_diff": total_correct_b - total_correct_a,
            "token_diff": metrics_b.get("total_tokens", 0) - metrics_a.get("total_tokens", 0),
            "input_token_diff": metrics_b.get("input_tokens", 0) - metrics_a.get("input_tokens", 0),
            "duration_diff_s": round(
                stats_b.get("total_duration_s", 0) - stats_a.get("total_duration_s", 0), 2
            ),
        },
    }

    # Save to file
    output_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults saved to {output_file}")

    # Print summary
    print(f"\n{'='*60}")
    print("COMPARISON SUMMARY")
    print(f"{'='*60}")
    print(f"  Protocol A (text):       {total_correct_a}/{total_fields} correct, "
          f"{metrics_a.get('total_tokens', 0)} tokens, "
          f"{stats_a.get('total_duration_s', 0):.1f}s")
    if result_a.get("error"):
        print(f"    error: {result_a.get('error')}")
    print(f"  Protocol B (structured): {total_correct_b}/{total_fields} correct, "
          f"{metrics_b.get('total_tokens', 0)} tokens, "
          f"{stats_b.get('total_duration_s', 0):.1f}s")
    if result_b.get("error"):
        print(f"    error: {result_b.get('error')}")
    print(f"  Accuracy diff: {total_correct_b - total_correct_a:+d}")
    print(f"  Token diff:    {metrics_b.get('total_tokens', 0) - metrics_a.get('total_tokens', 0):+d}")
    print(f"  Input token diff: {metrics_b.get('input_tokens', 0) - metrics_a.get('input_tokens', 0):+d}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
