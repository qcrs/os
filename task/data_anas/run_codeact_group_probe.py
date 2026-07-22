#!/usr/bin/env python3
"""Run CodeAct-only evaluation on one CSV task group.

This bypasses the full LangGraph pipeline and directly invokes `agent.codeact`
with minimal state, so the result reflects executor/codeact/runtime ability
more directly than the full multi-agent benchmark.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

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

TASK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TASK_DIR.parent.parent
RESULT_DIR = TASK_DIR / "result"
RESULT_DIR.mkdir(parents=True, exist_ok=True)
CSV_DIR = TASK_DIR / "csv"
CSV_SAMPLE_ROWS = 40

for p in (
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "third_party" / "langgraph" / "libs" / "langgraph",
    PROJECT_ROOT / "third_party" / "langgraph" / "libs" / "checkpoint",
):
    sys.path.insert(0, str(p))

from agent.codeact import codeact  # noqa: E402
from metrics import metrics  # noqa: E402


ANSWER_RE = re.compile(r"@(\w+)\[([^\]]*)\]")
FLOAT_RE = re.compile(r"^-?\d+\.\d+$")
BOOL_MAP = {"true": "True", "false": "False", "1": "True", "0": "False"}


def load_csv_context(path: Path, max_rows: int = CSV_SAMPLE_ROWS) -> str:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    header = lines[0]
    sample = lines[1 : max_rows + 1]
    return f"Columns: {header}\n" + "\n".join(sample)


def build_query(task: dict, csv_context: str, csv_file_name: str) -> str:
    return "\n".join([
        task["question"],
        f"\nConstraints: {task['constraints']}",
        f"\nExpected answer format: {task['answer_format']}",
        f"\nSample data (first {CSV_SAMPLE_ROWS} rows of {csv_file_name}):\n{csv_context}",
        "\nPlease compute the required statistics from the CSV artifact and return ONLY the exact answer format.",
    ])


def extract_answers(text: str) -> dict[str, str]:
    return dict(ANSWER_RE.findall(text or ""))


def normalize_value(raw: str, gold_val: str) -> str:
    value = raw.strip()
    if gold_val.lower() in ("true", "false"):
        return BOOL_MAP.get(value.lower(), value)
    if FLOAT_RE.match(gold_val):
        try:
            decimals = len(gold_val.split(".")[1])
            return f"{float(value):.{decimals}f}"
        except (ValueError, IndexError):
            return value
    return value


def compare_answers(extracted: dict[str, str], gold_items: list[list[str]]) -> dict:
    details = []
    for field_name, gold_val in gold_items:
        extracted_val = extracted.get(field_name, "")
        if not extracted_val:
            details.append({
                "field": field_name,
                "gold": gold_val,
                "extracted": "",
                "match": False,
                "reason": "not_found",
            })
            continue
        norm = normalize_value(extracted_val, gold_val)
        details.append({
            "field": field_name,
            "gold": gold_val,
            "extracted": extracted_val,
            "normalized": norm,
            "match": norm == gold_val,
        })
    correct = sum(1 for item in details if item["match"])
    return {
        "details": details,
        "correct": correct,
        "total": len(details),
        "accuracy": round(correct / max(len(details), 1), 4),
    }


def run_group(group: int) -> dict:
    tasks_file = TASK_DIR / f"group{group}_tasks.json"
    gold_file = TASK_DIR / f"group{group}_gold.json"
    tasks = json.loads(tasks_file.read_text(encoding="utf-8"))["tasks"]
    gold = json.loads(gold_file.read_text(encoding="utf-8"))

    rounds = []
    for task in tasks:
        csv_file_name = str(task["csv_file"]).strip()
        csv_path = (CSV_DIR / csv_file_name).resolve()
        csv_context = load_csv_context(csv_path)
        query = build_query(task, csv_context, csv_file_name)
        csv_label = Path(csv_file_name).stem
        task_group = f"probe_group{group}_{csv_label}_round_{task['round']}"

        started_at = time.perf_counter()
        result = codeact({
            "query": query,
            "task_group": task_group,
            "mode": "text",
            "analysis": "",
            "analysis_digest": "",
            "candidate_answers": {},
            "evidence": [],
            "selected_context_packets": [],
            "hidden_guidance": {},
            "artifact_refs": [{
                "id": f"{task_group}_csv",
                "kind": "csv",
                "label": csv_label,
                "path": str(csv_path),
            }],
        }, store=None)
        duration_s = round(time.perf_counter() - started_at, 2)

        final_answer = result.get("final_answer", "")
        extracted_answers = result.get("extracted_answers", {}) or extract_answers(final_answer)
        gold_items = gold.get(str(task["id"]), [])
        comparison = compare_answers(extracted_answers, gold_items)

        rounds.append({
            "round": task["round"],
            "task_id": task["id"],
            "csv_file": csv_file_name,
            "question": task["question"],
            "expected_format": task["answer_format"],
            "final_answer": final_answer,
            "extracted_answers": extracted_answers,
            "execution_summary": result.get("execution_summary", ""),
            "execution_result": result.get("execution_result", {}),
            "execution_trace": result.get("execution_trace", []),
            "execution_code": result.get("execution_code", ""),
            "duration_s": duration_s,
            "comparison": comparison,
        })

    total_correct = sum(r["comparison"]["correct"] for r in rounds)
    total_fields = sum(r["comparison"]["total"] for r in rounds)
    durations = [r["duration_s"] for r in rounds]
    summary = metrics.summary_dict()

    return {
        "group": group,
        "mode": "codeact_only",
        "accuracy": {
            "total_correct": total_correct,
            "total_fields": total_fields,
            "overall_accuracy": round(total_correct / max(total_fields, 1), 4),
        },
        "stats": {
            "total_rounds": len(rounds),
            "total_duration_s": round(sum(durations), 2),
            "avg_duration_s": round(sum(durations) / max(len(durations), 1), 2),
            "min_duration_s": round(min(durations), 2) if durations else 0,
            "max_duration_s": round(max(durations), 2) if durations else 0,
        },
        "metrics": {
            "llm_calls": summary.get("llm_calls", 0),
            "input_tokens": summary.get("input_tokens", 0),
            "output_tokens": summary.get("output_tokens", 0),
            "total_tokens": summary.get("total_tokens", 0),
        },
        "rounds": rounds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CodeAct-only evaluation on one group")
    parser.add_argument("--group", type=int, choices=[1, 2, 3], required=True)
    args = parser.parse_args()

    result = run_group(args.group)
    output_path = RESULT_DIR / f"group{args.group}_codeact_only.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "saved_to": str(output_path),
        "accuracy": result["accuracy"],
        "stats": result["stats"],
        "metrics": result["metrics"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
