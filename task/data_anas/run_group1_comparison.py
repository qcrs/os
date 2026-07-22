#!/usr/bin/env python3
"""Orchestrate Protocol A vs Protocol B comparison on Group 1 tasks.

Runs run_group1_single.py as a subprocess for each protocol, extracts answers,
compares with gold, and saves results to task/result/group1_comparison.json.

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
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TASK_DIR.parents[1]
RESULT_DIR = TASK_DIR / "result"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

TASKS_FILE = TASK_DIR / "group1_tasks.json"
GOLD_FILE = TASK_DIR / "group1_gold.json"
OUTPUT_FILE = RESULT_DIR / "group1_comparison.json"

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
    "PYTHONPATH": ":".join([
        str(PROJECT_ROOT),
        str(PROJECT_ROOT / "src"),
        str(PROJECT_ROOT / "third_party" / "langgraph" / "libs" / "langgraph"),
        str(PROJECT_ROOT / "third_party" / "langgraph" / "libs" / "checkpoint"),
    ]),
}


def run_protocol(mode: str, extra_env: dict | None = None) -> dict:
    """Invoke run_group1_single.py as a subprocess and parse its JSON output."""
    env = {
        **__import__("os").environ,
        **BASE_ENV,
        **(extra_env or {}),
    }
    cmd = [
        sys.executable, "-u",
        str(TASK_DIR / "run_group1_single.py"),
        "--mode", mode,
    ]
    print(f"\n{'='*60}")
    print(f"Running Protocol {'A' if mode == 'text' else 'B'} ({mode} mode)...")
    print(f"{'='*60}")

    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,  # 30 min per protocol
    )

    if proc.returncode != 0:
        print(f"[ERROR] subprocess exited {proc.returncode}", file=sys.stderr)
        print(f"STDERR:\n{proc.stderr[-2000:]}", file=sys.stderr)
        return {"mode": mode, "rounds": [], "error": proc.stderr[-500:]}

    json_start = proc.stdout.find("{")
    if json_start < 0:
        print("[ERROR] subprocess did not emit JSON", file=sys.stderr)
        print(f"STDOUT tail:\n{proc.stdout[-1000:]}", file=sys.stderr)
        return {"mode": mode, "rounds": [], "error": "missing_json_output"}

    try:
        return json.loads(proc.stdout[json_start:])
    except json.JSONDecodeError as exc:
        print(f"[ERROR] bad JSON: {exc}", file=sys.stderr)
        print(f"STDOUT tail:\n{proc.stdout[-1000:]}", file=sys.stderr)
        return {"mode": mode, "rounds": [], "error": str(exc)}


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


def sanitize_for_json(value):
    """Replace invalid surrogate characters before writing UTF-8 JSON."""
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(value, list):
        return [sanitize_for_json(item) for item in value]
    if isinstance(value, dict):
        return {
            sanitize_for_json(key): sanitize_for_json(item)
            for key, item in value.items()
        }
    return value


# ── Main ─────────────────────────────────────────────────────────────

def main():
    tasks = json.loads(TASKS_FILE.read_text(encoding="utf-8"))["tasks"]
    gold = json.loads(GOLD_FILE.read_text(encoding="utf-8"))

    # ── Protocol A: text mode ────────────────────────────────────────
    result_a = run_protocol("text")

    # ── Protocol B: structured, compressed text only ─────────────────
    result_b = run_protocol("structured", {
        "ENABLE_CONTEXT_PACKETS": "1",
        "ENABLE_EMBEDDING_TRANSFER": "0",
    })

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
        comp_a["error"] = ra.get("error", "")
        comp_a["final_answer"] = ra.get("final_answer", "")
        comp_a["memory_hit"] = ra.get("memory_hit", False)
        comp_a["reduced_research"] = ra.get("reduced_research", False)
        comp_a["memory_validation"] = ra.get("memory_validation", {})
        comp_a["validated_memory_ids"] = ra.get("validated_memory_ids", [])
        comparison_a.append(comp_a)

        # Protocol B
        rb = next((r for r in result_b.get("rounds", []) if r["round"] == round_num), {})
        comp_b = compare_answers(rb.get("extracted_answers", {}), gold_items)
        comp_b["round"] = round_num
        comp_b["task_id"] = task["id"]
        comp_b["question"] = task["question"]
        comp_b["duration_s"] = rb.get("duration_s", 0)
        comp_b["error"] = rb.get("error", "")
        comp_b["final_answer"] = rb.get("final_answer", "")
        comp_b["memory_hit"] = rb.get("memory_hit", False)
        comp_b["reduced_research"] = rb.get("reduced_research", False)
        comp_b["memory_validation"] = rb.get("memory_validation", {})
        comp_b["validated_memory_ids"] = rb.get("validated_memory_ids", [])
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
            "name": "group1_protocol_comparison",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "tasks": "group1_tasks.json (10 rounds, titanic.csv)",
            "container": _env_default("EXPERIMENT_CONTAINER", "SynapseX-wang"),
            "backend": BASE_ENV["CHAT_BACKEND"],
            "base_url": BASE_ENV["CHAT_BASE_URL"],
            "model": BASE_ENV["CHAT_MODEL"],
            "persistent_memory_enabled": _env_default("PERSISTENT_MEMORY_ENABLED", ""),
            "long_term_memory_enabled": _env_default("LONG_TERM_MEMORY_ENABLED", ""),
            "long_term_memory_qdrant_path": _env_default("LONG_TERM_MEMORY_QDRANT_PATH", ""),
            "long_term_memory_collection": _env_default("LONG_TERM_MEMORY_COLLECTION", ""),
            "long_term_memory_search_mode": _env_default("LONG_TERM_MEMORY_SEARCH_MODE", ""),
            "reduce_research_on_memory_hit": _env_default("REDUCE_RESEARCH_ON_MEMORY_HIT", ""),
            "dashscope_api_key_set": bool(_env_default("DASHSCOPE_API_KEY", "")),
        },
        "protocol_a": {
            "label": "Plain Text (mode=text)",
            "config": {"mode": "text"},
            "stats": stats_a,
            "metrics": {
                "llm_calls": metrics_a.get("llm_calls", 0),
                "input_tokens": metrics_a.get("input_tokens", 0),
                "output_tokens": metrics_a.get("output_tokens", 0),
                "total_tokens": metrics_a.get("total_tokens", 0),
                "context_original_chars": metrics_a.get("context_original_chars", 0),
                "context_compressed_chars": metrics_a.get("context_compressed_chars", 0),
                "context_saved_chars": metrics_a.get("context_saved_chars", 0),
                "memory_reuse_hits": metrics_a.get("memory_reuse_hits", 0),
                "research_fanout_reduced": metrics_a.get("research_fanout_reduced", 0),
                "research_subqueries_saved": metrics_a.get("research_subqueries_saved", 0),
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
            "stats": stats_b,
            "metrics": {
                "llm_calls": metrics_b.get("llm_calls", 0),
                "input_tokens": metrics_b.get("input_tokens", 0),
                "output_tokens": metrics_b.get("output_tokens", 0),
                "total_tokens": metrics_b.get("total_tokens", 0),
                "context_original_chars": metrics_b.get("context_original_chars", 0),
                "context_compressed_chars": metrics_b.get("context_compressed_chars", 0),
                "context_saved_chars": metrics_b.get("context_saved_chars", 0),
                "memory_reuse_hits": metrics_b.get("memory_reuse_hits", 0),
                "research_fanout_reduced": metrics_b.get("research_fanout_reduced", 0),
                "research_subqueries_saved": metrics_b.get("research_subqueries_saved", 0),
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
        "raw_errors": {
            "protocol_a": [r.get("error", "") for r in result_a.get("rounds", []) if r.get("error")],
            "protocol_b": [r.get("error", "") for r in result_b.get("rounds", []) if r.get("error")],
        },
    }

    # Save to file
    output = sanitize_for_json(output)
    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults saved to {OUTPUT_FILE}")

    # Print summary
    print(f"\n{'='*60}")
    print("COMPARISON SUMMARY")
    print(f"{'='*60}")
    print(f"  Protocol A (text):       {total_correct_a}/{total_fields} correct, "
          f"{metrics_a.get('total_tokens', 0)} tokens, "
          f"{stats_a.get('total_duration_s', 0):.1f}s")
    print(f"  Protocol B (structured): {total_correct_b}/{total_fields} correct, "
          f"{metrics_b.get('total_tokens', 0)} tokens, "
          f"{stats_b.get('total_duration_s', 0):.1f}s")
    print(f"  Accuracy diff: {total_correct_b - total_correct_a:+d}")
    print(f"  Token diff:    {metrics_b.get('total_tokens', 0) - metrics_a.get('total_tokens', 0):+d}")
    print(f"  Input token diff: {metrics_b.get('input_tokens', 0) - metrics_a.get('input_tokens', 0):+d}")
    print(f"  Research calls saved A/B: "
          f"{metrics_a.get('research_subqueries_saved', 0)} / "
          f"{metrics_b.get('research_subqueries_saved', 0)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
