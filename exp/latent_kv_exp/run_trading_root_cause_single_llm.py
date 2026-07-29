#!/usr/bin/env python3
"""Run a single-LLM baseline on the trading root-cause task."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests


PROJECT = Path(__file__).resolve().parent.parent.parent
TASK_FILE = PROJECT / "task/lantent/trading_root_cause_1round/trading_root_cause_task.json"
DEFAULT_BASE_URL = os.getenv("CHAT_BASE_URL", "http://localhost:8101/v1")
DEFAULT_API_KEY = os.getenv("CHAT_API_KEY", "token-abc")
DEFAULT_MODEL = os.getenv("CHAT_MODEL", "/data/models/Qwen3-8B")
REQUIRED_FIELDS = ["root_cause", "severity", "first_bad_component"]


@dataclass
class SingleLLMStats:
    mode: str
    task_id: str
    title: str
    wall_time_s: float
    llm_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    message_count: int
    logical_agent_handoffs: int
    latent_steps: int
    nontext_transfer_count: int
    nontext_transfer_bytes: int
    prompt_chars: int
    response_chars: int
    text_comm_chars: int
    text_comm_tokens_est: int
    answer: dict[str, Any]
    expected: dict[str, Any]
    correct_fields: int
    total_fields: int
    ok: bool
    raw_response: str
    error: str = ""


def compact_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def load_suite(task_file: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = json.loads(task_file.read_text(encoding="utf-8"))
    return data, data["tasks"]


def build_prompt(task: dict[str, Any], suite: dict[str, Any]) -> str:
    shared = suite["shared_context"]
    evidence = task["evidence_packet"]
    parts = [
        "单LLM根因定位。只能使用以下证据；不得执行代码、shell、SQL或外部工具。",
        "请在一次回答内完成时间线综合、候选排除、恢复相关性判断和严重性判断；最终只输出JSON，不要markdown，不要解释。",
        f"任务:{task['prompt']}",
        f"系统:{shared['system']}",
        f"窗口:{evidence['incident_window']}",
        f"输入画像:{compact_json(evidence['raw_input_profile'])}",
        f"标签:{compact_json(shared['allowed_root_cause_labels'])}",
        f"组件:{compact_json(shared['allowed_components'])}",
        f"严重性规则:{compact_json(shared['severity_rule'])}",
        f"影响:{compact_json(evidence['business_impact_summary'])}",
        "候选:" + ";".join(
            f"{item['label']}={item['plain_name']}" for item in evidence["candidate_root_causes"]
        ),
        "日志:",
    ]
    for item in evidence["log_digest"]:
        parts.append(f"{item['id']} {item['time']} {item['component']}: {item['summary']}")
    parts.append("指标:")
    for item in evidence["metric_snapshots"]:
        parts.append(compact_json(item))
    parts.append("变更:")
    for item in evidence["change_records"]:
        parts.append(f"{item['id']} {item['time']} {item['component']}: {item['summary']}")
    parts.extend(
        [
            "排除观察:" + ";".join(evidence["triage_observations"]),
            f"输出JSON字段:{compact_json(shared['final_answer_contract'])}",
            "只允许从给定标签和组件中选择；reference_answer 不在 prompt 中。",
        ]
    )
    return "\n".join(part for part in parts if part != "")


def find_json_objects(text: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
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


def extract_answer(text: str) -> dict[str, Any]:
    for obj in find_json_objects(text):
        if all(field in obj for field in REQUIRED_FIELDS):
            return normalize_answer(obj)

    fallback: dict[str, Any] = {}
    patterns = {
        "root_cause": r"\b(ordergateway_auth_cache_key_normalization|riskengine_false_positive_rule|matchingcore_queue_starvation|marketdata_provider_skew|clearing_batch_backpressure|settlement_deadlock|auditlogger_index_lag|unknown)\b",
        "severity": r"\b(P0|P1|P2)\b",
        "first_bad_component": r"\b(OrderGateway|RiskEngine|MatchingCore|ClearingService|SettlementService|MarketDataFeed|AuditLogger|PositionManager|RegulatoryReporter)\b",
    }
    for field, pattern in patterns.items():
        matches = re.findall(pattern, text or "")
        if matches:
            fallback[field] = matches[-1]
    return normalize_answer(fallback)


def grade(answer: dict[str, Any], expected: dict[str, Any]) -> tuple[int, int, bool]:
    answer_n = normalize_answer(answer)
    expected_n = normalize_answer(expected)
    correct = sum(1 for field in REQUIRED_FIELDS if answer_n.get(field) == expected_n.get(field))
    return correct, len(REQUIRED_FIELDS), correct == len(REQUIRED_FIELDS)


def chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    timeout: int,
) -> tuple[str, dict[str, int]]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a precise incident root-cause analyst. Use only the provided task evidence. "
                    "Return only valid JSON for the requested final contract."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    text = data["choices"][0]["message"]["content"]
    usage = data.get("usage") or {}
    return text, {
        "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "output_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }


def run_single_llm(
    task: dict[str, Any],
    suite: dict[str, Any],
    *,
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int,
    temperature: float,
    timeout: int,
) -> SingleLLMStats:
    prompt = build_prompt(task, suite)
    t0 = time.perf_counter()
    error = ""
    raw_response = ""
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    try:
        raw_response, usage = chat_completion(
            base_url=base_url,
            api_key=api_key,
            model=model,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    wall_time_s = round(time.perf_counter() - t0, 3)
    answer = extract_answer(raw_response)
    correct_fields, total_fields, ok = grade(answer, task["reference_answer"])
    prompt_chars = len(prompt)
    response_chars = len(raw_response)
    text_comm_chars = prompt_chars + response_chars
    return SingleLLMStats(
        mode="single_llm",
        task_id=task["task_id"],
        title=task["title"],
        wall_time_s=wall_time_s,
        llm_calls=1 if not error else 0,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        total_tokens=usage["total_tokens"],
        message_count=2 if not error else 0,
        logical_agent_handoffs=0,
        latent_steps=0,
        nontext_transfer_count=0,
        nontext_transfer_bytes=0,
        prompt_chars=prompt_chars,
        response_chars=response_chars,
        text_comm_chars=text_comm_chars,
        text_comm_tokens_est=math.ceil(text_comm_chars / 4),
        answer=answer,
        expected=task["reference_answer"],
        correct_fields=correct_fields,
        total_fields=total_fields,
        ok=ok,
        raw_response=raw_response,
        error=error[:500],
    )


def generate_report(row: dict[str, Any], output_dir: Path, suite: dict[str, Any], manifest: dict[str, Any]) -> None:
    lines = [
        "# Trading Root Cause Single-LLM Baseline",
        "",
        f"Suite: `{suite['suite_id']}`",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "This baseline uses one direct OpenAI-compatible chat completion call. It does not use the multi-agent graph, latent KV handles, or executor tools.",
        "",
        "| Mode | Time(s) | Token in | Token out | Msgs | Handoffs | Text chars | Non-text MB | Fields | Answer |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        (
            f"| {row['mode']} | {row['wall_time_s']:.3f} | {row.get('input_tokens', 0)} | "
            f"{row.get('output_tokens', 0)} | {row.get('message_count', 0)} | "
            f"{row.get('logical_agent_handoffs', 0)} | {row.get('text_comm_chars', 0)} | "
            f"{(row.get('nontext_transfer_bytes', 0) or 0) / 1024 / 1024:.2f} | "
            f"{row.get('correct_fields', 0)}/{row.get('total_fields', 0)} | "
            f"`{json.dumps(row.get('answer', {}), ensure_ascii=False)}` |"
        ),
        "",
        "Expected:",
        "",
        f"`{json.dumps(row.get('expected', {}), ensure_ascii=False)}`",
        "",
        "Run config:",
        "",
        f"`{json.dumps(manifest, ensure_ascii=False)}`",
    ]
    if row.get("error"):
        lines.extend(["", "Error:", "", f"`{row['error']}`"])
    (output_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run single-LLM baseline on the root-cause task.")
    parser.add_argument("--task-file", type=Path, default=TASK_FILE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    task_file = args.task_file if args.task_file.is_absolute() else PROJECT / args.task_file
    output_dir = args.output_dir if args.output_dir.is_absolute() else PROJECT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    suite, tasks = load_suite(task_file)
    task = tasks[0]
    manifest = {
        "suite_id": suite["suite_id"],
        "task_file": str(task_file),
        "output_dir": str(output_dir),
        "mode": "single_llm",
        "base_url": args.base_url,
        "model": args.model,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "chat_disable_thinking": os.getenv("CHAT_DISABLE_THINKING", "1"),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (output_dir / "RUN_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 72)
    print("Trading Root Cause single-LLM baseline")
    print(f"task={task_file}")
    print(f"output={output_dir}")
    print(f"base_url={args.base_url}")
    print(f"model={args.model}")
    print("=" * 72)

    row = asdict(
        run_single_llm(
            task,
            suite,
            base_url=args.base_url,
            api_key=args.api_key,
            model=args.model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            timeout=args.timeout,
        )
    )
    (output_dir / "single_llm.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    generate_report(row, output_dir, suite, manifest)

    print(
        f"  {'OK' if row['ok'] else 'MISS'} {row['wall_time_s']:.1f}s "
        f"fields={row['correct_fields']}/{row['total_fields']} answer={row['answer']}"
    )
    if row.get("error"):
        print(f"  error: {row['error']}")
    print(f"\nDONE: {output_dir}")
    return 0 if not row.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
