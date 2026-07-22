#!/usr/bin/env python3
"""Run all group tasks for a single protocol and output results as JSON.

Usage (inside SynapseX-wmw container):
    # Protocol A (text mode):
    CHAT_BACKEND=transformers python3 run_group1_single.py --group 1 --mode text

    # Protocol B (structured, compressed text only):
    CHAT_BACKEND=transformers ENABLE_EMBEDDING_TRANSFER=0 \
        python3 run_group1_single.py --group 1 --mode structured
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
os.environ.setdefault("ENABLE_CODEACT_EXECUTOR", "1")
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
PROJECT_ROOT = TASK_DIR.parents[1]

for p in (
    PROJECT_ROOT,
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "third_party" / "langgraph" / "libs" / "langgraph",
    PROJECT_ROOT / "third_party" / "langgraph" / "libs" / "checkpoint",
):
    sys.path.insert(0, str(p))

# ── Now safe to import project modules ───────────────────────────────
from graph import build_graph          # noqa: E402
from metrics import metrics            # noqa: E402

# ── Constants ────────────────────────────────────────────────────────
CSV_DIR = TASK_DIR / "csv"
CSV_SAMPLE_ROWS = 40                   # rows included in the query context
TASK_TOPIC = "CSV analysis"


# ── Helpers ──────────────────────────────────────────────────────────

def load_csv_context(path: Path, max_rows: int = CSV_SAMPLE_ROWS) -> str:
    """Read CSV and return a compact text table for the query context."""
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    header = lines[0]
    sample = lines[1 : max_rows + 1]
    return f"Columns: {header}\n" + "\n".join(sample)


def build_query(task: dict, csv_context: str, csv_file_name: str) -> str:
    """Compose the full query including question, constraints, and data."""
    parts = [
        task["question"],
        f"\nConstraints: {task['constraints']}",
        f"\nExpected answer format: {task['answer_format']}",
        f"\nSample data (first {CSV_SAMPLE_ROWS} rows of {csv_file_name}):\n{csv_context}",
        "\nPlease compute the required statistics from the data above and "
        "return ONLY the answer in the exact format specified.",
    ]
    return "\n".join(parts)


ANSWER_RE = re.compile(r"@(\w+)\[([^\]]*)\]")


def extract_answers(text: str) -> dict[str, str]:
    """Extract @field[value] pairs from the summary text."""
    return dict(ANSWER_RE.findall(text or ""))


def _task_files(group: int) -> tuple[Path, Path]:
    tasks_file = TASK_DIR / f"group{group}_tasks.json"
    gold_file = TASK_DIR / f"group{group}_gold.json"
    if not tasks_file.exists():
        raise FileNotFoundError(f"Missing tasks file: {tasks_file}")
    if not gold_file.exists():
        raise FileNotFoundError(f"Missing gold file: {gold_file}")
    return tasks_file, gold_file


def run_all_tasks(group: int, mode: str) -> dict:
    """Build graph, run one task group, and collect raw results and metrics."""
    graph, store = build_graph(mode=mode)

    tasks_file, _ = _task_files(group)
    tasks = json.loads(tasks_file.read_text(encoding="utf-8"))["tasks"]

    round_results = []
    total = len(tasks)
    for task in tasks:
        rd = task["round"]
        print(
            f"  [{mode}] Round {rd}/{total} start: {task['question'][:60]}...",
            file=sys.stderr,
            flush=True,
        )
        csv_file_name = str(task["csv_file"]).strip()
        csv_file = CSV_DIR / csv_file_name
        csv_context = load_csv_context(csv_file)
        query = build_query(task, csv_context, csv_file_name)
        csv_label = Path(csv_file_name).stem
        task_group = f"group{group}_{csv_label}_round_{rd}"

        t0 = time.perf_counter()
        try:
            result = graph.invoke({
                "query": query,
                "task_group": task_group,
                "task_topic": f"{TASK_TOPIC}: {csv_label}",
                "mode": mode,
                "artifact_refs": [{
                    "id": f"{task_group}_csv",
                    "kind": "csv",
                    "label": csv_label,
                    "path": str(csv_file.resolve()),
                }],
            })
        except Exception as exc:
            result = {"summary": "", "analysis": "", "error": str(exc)}
            print(
                f"  [{mode}] Round {rd}/{total} error: {exc}",
                file=sys.stderr,
                flush=True,
            )
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
            "error": result.get("error", ""),
            "summary": summary_text,
            "final_answer": final_answer,
            "answer_source": "executor",
            "analysis": analysis_text[:500],
            "execution_summary": result.get("execution_summary", ""),
            "memory_hit": result.get("memory_hit", False),
            "reduced_research": result.get("reduced_research", False),
            "memory_validation": result.get("memory_validation", {}),
            "validated_memory_ids": result.get("validated_memory_ids", []),
            "execution_result": result.get("execution_result", {}),
            "execution_trace": result.get("execution_trace", []),
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
        "group": group,
        "mode": mode,
        "rounds": round_results,
        "metrics_summary": summary_dict,
        "metrics_report": metrics_report,
    }


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Run one group of CSV tasks for one protocol")
    parser.add_argument("--group", type=int, choices=[1, 2, 3], default=1)
    parser.add_argument("--mode", choices=["text", "structured"], required=True)
    args = parser.parse_args()

    result = run_all_tasks(args.group, args.mode)
    # Output JSON to stdout (wrapper script captures it)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
