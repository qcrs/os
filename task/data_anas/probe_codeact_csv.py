#!/usr/bin/env python3
"""Probe CodeAct on an arbitrary CSV question in the current branch."""

import argparse
import json
import os
import sys
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

for p in (
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "third_party" / "langgraph" / "libs" / "langgraph",
    PROJECT_ROOT / "third_party" / "langgraph" / "libs" / "checkpoint",
):
    sys.path.insert(0, str(p))

from agent.codeact import codeact  # noqa: E402


def load_csv_context(path: Path, max_rows: int) -> str:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    header = lines[0]
    sample = lines[1:max_rows + 1]
    return f"Columns: {header}\n" + "\n".join(sample)


def build_query(question: str, answer_format: str, csv_context: str) -> str:
    return "\n".join([
        question,
        f"\nExpected answer format: {answer_format}",
        f"\nSample data:\n{csv_context}",
        "\nPlease compute the required result from the CSV artifact and return only the exact answer format.",
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--answer-format", required=True)
    parser.add_argument("--label", default="csv_artifact")
    parser.add_argument("--sample-rows", type=int, default=20)
    parser.add_argument("--backend", choices=["transformers", "openai"], default=None)
    args = parser.parse_args()

    csv_path = Path(args.csv).resolve()
    if args.backend:
        os.environ["CHAT_BACKEND"] = args.backend

    query = build_query(
        question=args.question,
        answer_format=args.answer_format,
        csv_context=load_csv_context(csv_path, args.sample_rows),
    )

    result = codeact({
        "query": query,
        "task_group": f"probe_{csv_path.stem}",
        "mode": "text",
        "analysis": "",
        "analysis_digest": "",
        "candidate_answers": {},
        "evidence": [],
        "selected_context_packets": [],
        "hidden_guidance": {},
        "artifact_refs": [{
            "id": f"probe_{csv_path.stem}",
            "kind": "csv",
            "label": args.label,
            "path": str(csv_path),
        }],
    }, store=None)

    print(json.dumps({
        "csv": str(csv_path),
        "question": args.question,
        "answer_format": args.answer_format,
        "final_answer": result.get("final_answer", ""),
        "extracted_answers": result.get("extracted_answers", {}),
        "execution_summary": result.get("execution_summary", ""),
        "selected_strategy": (result.get("execution_result") or {}).get("selected_strategy", ""),
        "fallback_answer_used": (result.get("execution_result") or {}).get("fallback_answer_used", False),
        "answer_format_rebuilt": (result.get("execution_result") or {}).get("answer_format_rebuilt", False),
        "execution_result": result.get("execution_result", {}),
        "execution_trace": result.get("execution_trace", []),
        "execution_code": result.get("execution_code", ""),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
