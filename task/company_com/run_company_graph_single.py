#!/usr/bin/env python3
"""Run company_com sessions through the main multi-agent graph.

Unit of work: one financial QA session. A session contains one shared
table/text context and multiple ordered turns, so this runner invokes the graph
once per session and asks for @turn_1[...] @turn_2[...] fields.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Defaults are compatible with the local vLLM OpenAI-compatible setup used by
# existing task runners. Environment variables supplied by the caller win.
os.environ.setdefault("CHAT_BACKEND", "openai")
os.environ.setdefault("CHAT_API_KEY", "EMPTY")
os.environ.setdefault("CHAT_BASE_URL", "http://127.0.0.1:8000/v1")
os.environ.setdefault("CHAT_MODEL", "/data/models/Qwen3-8B")
os.environ.setdefault("CHAT_DISABLE_THINKING", "1")
os.environ.setdefault("PERSISTENT_MEMORY_ENABLED", "0")
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)


TASK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TASK_DIR.parents[1]
TASKS_FILE = TASK_DIR / "eval_sequences.json"
RESULT_DIR = TASK_DIR / "result"
DEFAULT_OUTPUT = RESULT_DIR / "company_graph_single.json"

for path in (
    PROJECT_ROOT,
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "third_party" / "langgraph" / "libs" / "langgraph",
    PROJECT_ROOT / "third_party" / "langgraph" / "libs" / "checkpoint",
):
    sys.path.insert(0, str(path))

from graph import build_graph  # noqa: E402
from metrics import metrics  # noqa: E402
from adapter import build_company_graph_input, clip_text  # noqa: E402


ANSWER_RE = re.compile(r"@(\w+)\[([^\]]*)\]")
NUMBER_RE = re.compile(r"-?\(?\$?\s*\d[\d,]*(?:\.\d+)?\s*\)?%?")


def load_dataset() -> list[dict[str, Any]]:
    return json.loads(TASKS_FILE.read_text(encoding="utf-8"))


def normalize_number(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    negative = raw.startswith("-") or (raw.startswith("(") and ")" in raw)
    match = re.search(r"\d[\d,]*(?:\.\d+)?", raw)
    if not match:
        return re.sub(r"\s+", " ", raw).strip().lower()
    try:
        number = float(match.group(0).replace(",", ""))
    except ValueError:
        return re.sub(r"\s+", " ", raw).strip().lower()
    if negative:
        number = -number
    if number.is_integer():
        return str(int(number))
    return f"{number:.8f}".rstrip("0").rstrip(".")


def compare_value(extracted: object, gold: object, *, tolerance: float = 1e-4) -> bool:
    left = normalize_number(extracted)
    right = normalize_number(gold)
    try:
        return abs(float(left) - float(right)) <= tolerance
    except ValueError:
        return left == right


def extract_answers(text: str) -> dict[str, str]:
    return dict(ANSWER_RE.findall(text or ""))


def select_companies(dataset: list[dict[str, Any]], selector: str) -> list[dict[str, Any]]:
    if not selector or selector.lower() == "all":
        return dataset
    wanted = {item.strip().upper() for item in selector.split(",") if item.strip()}
    return [entry for entry in dataset if entry.get("company", "").upper() in wanted]


def iter_sessions(
    dataset: list[dict[str, Any]],
    *,
    companies: str,
    max_sessions: int,
    session_orders: str,
):
    selected_orders = {
        int(item.strip())
        for item in session_orders.split(",")
        if item.strip()
    } if session_orders else set()
    for entry in select_companies(dataset, companies):
        company = entry["company"]
        sessions = sorted(
            entry.get("sessions", []),
            key=lambda item: int(item.get("session_order", 0)),
        )
        if selected_orders:
            sessions = [
                session for session in sessions
                if int(session.get("session_order", 0)) in selected_orders
            ]
        if max_sessions:
            sessions = sessions[:max_sessions]
        for session in sessions:
            yield company, session


def evaluate_session(result: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    final_answer = result.get("final_answer", "") or ""
    extracted = result.get("extracted_answers", {}) or extract_answers(final_answer)
    summary_extracted = extract_answers(result.get("summary", "") or "")
    if not extracted and summary_extracted:
        extracted = summary_extracted

    details = []
    for idx, turn in enumerate(session.get("turns", []) or [], start=1):
        field = f"turn_{idx}"
        raw_value = extracted.get(field, "")
        gold = turn.get("gold_answer")
        details.append({
            "field": field,
            "question": turn.get("question"),
            "gold_answer": gold,
            "gold_program": turn.get("gold_program"),
            "extracted": raw_value,
            "match": compare_value(raw_value, gold) if raw_value else False,
            "has_internal_ref": bool(turn.get("has_internal_ref")),
        })

    correct = sum(1 for item in details if item["match"])
    total = len(details)
    return {
        "correct": correct,
        "total": total,
        "accuracy": round(correct / max(total, 1), 4),
        "details": details,
        "extracted_answers": extracted,
    }


def run_sessions(args: argparse.Namespace) -> dict[str, Any]:
    metrics.reset()
    dataset = load_dataset()
    selected = list(iter_sessions(
        dataset,
        companies=args.companies,
        max_sessions=args.max_sessions,
        session_orders=args.session_orders,
    ))

    if args.dry_run:
        dry_sessions = []
        for company, session in selected:
            graph_input = build_company_graph_input(
                session,
                company,
                mode=args.mode,
                max_context_chars=args.max_context_chars,
            )
            dry_sessions.append({
                "company": company,
                "session_order": session.get("session_order"),
                "task_topic": graph_input["task_topic"],
                "source_id": session.get("id"),
                "turn_count": len(session.get("turns", []) or []),
                "query_chars": len(graph_input["query"]),
                "source_context_chars": len(graph_input["source_context"]),
                "analyst_instructions_chars": len(graph_input.get("analyst_instructions", "")),
                "query_preview": graph_input["query"][: args.preview_chars],
                "source_context_preview": graph_input["source_context"][: args.preview_chars],
            })
        return {
            "experiment": {
                "name": "company_com_graph_single",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "mode": args.mode,
                "dry_run": True,
                "memory_strategy": "fresh_graph_per_session"
                if args.fresh_graph_per_session else "shared_graph_store",
            },
            "sessions": dry_sessions,
        }

    graph = None
    if not args.fresh_graph_per_session:
        graph, _store = build_graph(mode=args.mode)
    session_results = []
    started = time.perf_counter()

    for index, (company, session) in enumerate(selected, start=1):
        if args.fresh_graph_per_session:
            graph, _store = build_graph(mode=args.mode)
        order = int(session.get("session_order", 0))
        graph_input = build_company_graph_input(
            session,
            company,
            mode=args.mode,
            max_context_chars=args.max_context_chars,
        )
        query = graph_input["query"]
        task_group = graph_input["task_group"]
        task_topic = graph_input["task_topic"]
        print(
            f"[{args.mode}] session {index}/{len(selected)} "
            f"{company}#{order} turns={len(session.get('turns', []) or [])}",
            file=sys.stderr,
            flush=True,
        )

        t0 = time.perf_counter()
        error = ""
        try:
            result = graph.invoke(graph_input)
        except Exception as exc:  # noqa: BLE001 - runner should keep reporting.
            result = {"final_answer": "", "summary": "", "analysis": ""}
            error = repr(exc)
            print(f"[{args.mode}] session {company}#{order} error: {error}", file=sys.stderr)
        duration = time.perf_counter() - t0

        eval_result = evaluate_session(result, session)
        metrics.record_timing(f"company_session_{company}_{order}", duration)
        session_results.append({
            "company": company,
            "year": session.get("year"),
            "session_order": order,
            "source_id": session.get("id"),
            "turn_count": len(session.get("turns", []) or []),
            "task_group": task_group,
            "task_topic": task_topic,
            "duration_s": round(duration, 3),
            "query_chars": len(query),
            "source_context_chars": len(graph_input["source_context"]),
            "analyst_instructions_chars": len(graph_input.get("analyst_instructions", "")),
            "error": error,
            "memory_hit": result.get("memory_hit", False),
            "reduced_research": result.get("reduced_research", False),
            "reused_memory_ids": result.get("reused_memory_ids", []),
            "memory_validation": result.get("memory_validation", {}),
            "validated_memory_ids": result.get("validated_memory_ids", []),
            "final_answer": result.get("final_answer", ""),
            "summary": clip_text(result.get("summary", ""), args.result_text_chars),
            "analysis": clip_text(result.get("analysis", ""), args.result_text_chars),
            "evaluation": eval_result,
            "cumulative_metrics": metrics.summary_dict(),
        })

    total_correct = sum(item["evaluation"]["correct"] for item in session_results)
    total_fields = sum(item["evaluation"]["total"] for item in session_results)
    elapsed = time.perf_counter() - started
    return {
        "experiment": {
            "name": "company_com_graph_single",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "mode": args.mode,
            "companies": args.companies,
            "max_sessions": args.max_sessions,
            "session_orders": args.session_orders,
            "backend": os.environ.get("CHAT_BACKEND"),
            "base_url": os.environ.get("CHAT_BASE_URL"),
            "model": os.environ.get("CHAT_MODEL"),
            "persistent_memory_enabled": os.environ.get("PERSISTENT_MEMORY_ENABLED"),
            "long_term_memory_enabled": os.environ.get("LONG_TERM_MEMORY_ENABLED"),
            "long_term_memory_qdrant_path": os.environ.get("LONG_TERM_MEMORY_QDRANT_PATH"),
            "long_term_memory_collection": os.environ.get("LONG_TERM_MEMORY_COLLECTION"),
            "long_term_memory_search_mode": os.environ.get("LONG_TERM_MEMORY_SEARCH_MODE"),
            "long_term_memory_top_k": os.environ.get("LONG_TERM_MEMORY_TOP_K"),
            "enable_context_packets": os.environ.get("ENABLE_CONTEXT_PACKETS"),
            "enable_embedding_transfer": os.environ.get("ENABLE_EMBEDDING_TRANSFER"),
            "memory_strategy": "fresh_graph_per_session"
            if args.fresh_graph_per_session else "shared_graph_store",
        },
        "summary": {
            "session_count": len(session_results),
            "turn_count": total_fields,
            "correct": total_correct,
            "accuracy": round(total_correct / max(total_fields, 1), 4),
            "elapsed_s": round(elapsed, 3),
            "metrics": metrics.summary_dict(),
        },
        "sessions": session_results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run company_com sessions through the main multi-agent graph."
    )
    parser.add_argument("--mode", choices=["text", "structured"], default="text")
    parser.add_argument("--companies", default="ETR", help="Comma-separated tickers, or all.")
    parser.add_argument("--max-sessions", type=int, default=1)
    parser.add_argument(
        "--session-orders",
        default="",
        help="Comma-separated session_order values. Applied before max-sessions.",
    )
    parser.add_argument("--max-context-chars", type=int, default=12000)
    parser.add_argument("--result-text-chars", type=int, default=1200)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preview-chars", type=int, default=1200)
    parser.add_argument(
        "--fresh-graph-per-session",
        action="store_true",
        help="Rebuild graph/store for every session. Use as memory-off baseline.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = run_sessions(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "experiment": output.get("experiment", {}),
        "summary": output.get("summary", {}),
        "dry_session_count": len(output.get("sessions", [])) if args.dry_run else None,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
