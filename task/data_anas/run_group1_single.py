#!/usr/bin/env python3
"""Run all Group 1 tasks for a single protocol and output results as JSON.

Usage (inside SynapseX-wmw container):
    # Protocol A (text mode):
    CHAT_BACKEND=transformers python3 run_group1_single.py --mode text

    # Protocol B (structured, compressed text only):
    CHAT_BACKEND=transformers ENABLE_EMBEDDING_TRANSFER=0 \
        python3 run_group1_single.py --mode structured
"""

# ── Env vars MUST be set before any project imports ──────────────────
import os
import sys

os.environ.setdefault("CHAT_BACKEND", "transformers")
os.environ.setdefault("CHAT_API_KEY", "EMPTY")
os.environ.setdefault("CHAT_BASE_URL", "http://127.0.0.1:8000/v1")
os.environ.setdefault("CHAT_MODEL", "/data/models/Qwen3-8B")
os.environ.setdefault("CHAT_DISABLE_THINKING", "1")
os.environ.setdefault("LOCAL_MODEL_PATH", "/data/models/Qwen3-8B")
os.environ.setdefault("LOCAL_MODEL_DEVICE", "cuda:0")
os.environ.setdefault("LOCAL_MODEL_DTYPE", "bfloat16")
os.environ.setdefault("LOCAL_TRANSFORMERS_MAX_NEW_TOKENS", "512")
os.environ.pop("DASHSCOPE_API_KEY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)

# ── Path setup ───────────────────────────────────────────────────────
import argparse
import json
import re
import time
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TASK_DIR.parent

for p in (
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "langgraph" / "libs" / "langgraph",
    PROJECT_ROOT / "langgraph" / "libs" / "checkpoint",
):
    sys.path.insert(0, str(p))

# ── Now safe to import project modules ───────────────────────────────
from graph import build_graph          # noqa: E402
from metrics import metrics            # noqa: E402

# ── Constants ────────────────────────────────────────────────────────
TASKS_FILE = TASK_DIR / "group1_tasks.json"
CSV_FILE = TASK_DIR / "csv" / "titanic.csv"
CSV_SAMPLE_ROWS = 40                   # rows included in the query context


# ── Helpers ──────────────────────────────────────────────────────────

def load_csv_context(path: Path, max_rows: int = CSV_SAMPLE_ROWS) -> str:
    """Read CSV and return a compact text table for the query context."""
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    header = lines[0]
    sample = lines[1 : max_rows + 1]
    return f"Columns: {header}\n" + "\n".join(sample)


def build_query(task: dict, csv_context: str) -> str:
    """Compose the full query including question, constraints, and data."""
    parts = [
        task["question"],
        f"\nConstraints: {task['constraints']}",
        f"\nExpected answer format: {task['answer_format']}",
        f"\nSample data (first {CSV_SAMPLE_ROWS} rows of titanic.csv):\n{csv_context}",
        "\nPlease compute the required statistics from the data above and "
        "return ONLY the answer in the exact format specified.",
    ]
    return "\n".join(parts)


ANSWER_RE = re.compile(r"@(\w+)\[([^\]]*)\]")


def extract_answers(text: str) -> dict[str, str]:
    """Extract @field[value] pairs from the summary text."""
    return dict(ANSWER_RE.findall(text or ""))


def run_all_tasks(mode: str) -> dict:
    """Build graph, run 10 tasks, collect raw results and metrics."""
    graph, store = build_graph(mode=mode)

    tasks = json.loads(TASKS_FILE.read_text(encoding="utf-8"))["tasks"]
    csv_context = load_csv_context(CSV_FILE)

    round_results = []
    total = len(tasks)
    for task in tasks:
        rd = task["round"]
        print(
            f"  [{mode}] Round {rd}/{total} start: {task['question'][:60]}...",
            file=sys.stderr,
            flush=True,
        )
        query = build_query(task, csv_context)
        task_group = f"titanic_round_{rd}"

        t0 = time.perf_counter()
        try:
            result = graph.invoke({
                "query": query,
                "task_group": task_group,
                "mode": mode,
            })
        except Exception as exc:
            result = {"summary": "", "analysis": "", "error": str(exc)}
        duration = time.perf_counter() - t0

        summary_text = result.get("summary", "")
        analysis_text = result.get("analysis", "")
        final_answer = result.get("final_answer", "")
        answers = result.get("extracted_answers", {}) or extract_answers(final_answer)

        round_results.append({
            "round": rd,
            "task_id": task["id"],
            "question": task["question"],
            "expected_format": task["answer_format"],
            "summary": summary_text,
            "final_answer": final_answer,
            "answer_source": "executor",
            "analysis": analysis_text[:500],
            "execution_summary": result.get("execution_summary", ""),
            "extracted_answers": answers,
            "summary_extracted_answers": extract_answers(summary_text),
            "duration_s": round(duration, 2),
        })

        print(
            f"  [{mode}] Round {rd}/{total} done ({duration:.1f}s) answers={answers}",
            file=sys.stderr,
            flush=True,
        )
        metrics.record_timing(f"round_{rd}", duration)

    # Collect global metrics
    summary_dict = metrics.summary_dict()
    metrics_report = metrics.report()

    return {
        "mode": mode,
        "rounds": round_results,
        "metrics_summary": summary_dict,
        "metrics_report": metrics_report,
    }


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Run Group 1 tasks for one protocol")
    parser.add_argument("--mode", choices=["text", "structured"], required=True)
    args = parser.parse_args()

    result = run_all_tasks(args.mode)
    # Output JSON to stdout (wrapper script captures it)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
