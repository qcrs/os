#!/usr/bin/env python3
"""Run a single-LLM full-artifact baseline for the intermediate audit task."""

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

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from verify_intermediate_audit_artifacts import verify_artifact


PROJECT = Path(__file__).resolve().parent.parent.parent
TASK_FILE = PROJECT / "task/lantent/intermediate_audit_1round/intermediate_audit_task.json"
DEFAULT_BASE_URL = os.getenv("CHAT_BASE_URL", "http://localhost:8101/v1")
DEFAULT_API_KEY = os.getenv("CHAT_API_KEY", "token-abc")
DEFAULT_MODEL = os.getenv("CHAT_MODEL", "/data/models/Qwen3-8B")


@dataclass
class RunStats:
    mode: str
    task_id: str
    title: str
    wall_time_s: float
    llm_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    prompt_chars: int
    response_chars: int
    text_comm_chars: int
    text_comm_tokens_est: int
    artifact_parse_ok: bool
    verifier_ok: bool
    verifier_errors: list[str]
    final_answer: dict[str, Any]
    expected: dict[str, Any]
    raw_response: str
    error: str = ""


def compact_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def load_suite(task_file: Path) -> dict[str, Any]:
    return json.loads(task_file.read_text(encoding="utf-8"))


def build_prompt(suite: dict[str, Any]) -> str:
    shared = suite["shared_context"]
    task = suite["tasks"][0]
    evidence = task["evidence_packet"]
    parts = [
        "你是本轮唯一的审计分析模型。只能使用下方 evidence_packet，不得使用外部知识。",
        "必须一次性输出一个合法 JSON object，不要 markdown，不要代码块，不要解释 JSON 之外的文字。",
        "JSON 顶层必须且只能包含 researcher_report、analyst_analysis、executor_matrix、final_answer 四个字段。",
        "researcher_report 必须是 900-1300 中文字，覆盖 4 个 case，并显式引用关键 evidence_id。",
        "analyst_analysis 必须是 900-1300 中文字，比较 4 个 case，包含排序 C-117 > C-118 > C-119 > C-120，并说明后三个为什么不是最高风险。",
        "executor_matrix 必须是 4 行数组，每行列出 case_id、7 个 points 字段、risk_score、tier、action、supporting_evidence_ids。",
        "risk_score = sensitivity_points + volume_points + channel_points + anomaly_points + repeat_points + exposure_points - mitigation_points。",
        "tier 规则和 action 必须严格按下方配置计算。final_answer 必须与 executor_matrix 中最高 risk_score 的 case 一致。",
        f"任务:{task['prompt']}",
        f"系统:{shared['system']}",
        f"case_id_space:{compact_json(shared['case_id_space'])}",
        f"valid_tiers:{compact_json(shared['valid_tiers'])}",
        f"valid_actions:{compact_json(shared['valid_actions'])}",
        f"tier_rule:{compact_json(shared['tier_rule'])}",
        f"required_intermediate_artifacts:{compact_json(shared['required_intermediate_artifacts'])}",
        f"final_contract:{compact_json(shared['final_contract'])}",
        f"audit_window:{evidence['audit_window']}",
        f"audit_scope:{evidence['audit_scope']}",
        f"policy_notes:{compact_json(evidence['policy_notes'])}",
        "candidate_cases:",
    ]
    for case in evidence["candidate_cases"]:
        parts.append(
            "\n".join(
                [
                    f"case_id={case['case_id']}",
                    f"subject={case['subject']}",
                    f"department={case['department']}",
                    f"dataset={case['dataset']}",
                    f"sensitivity={case['sensitivity']}",
                    f"access_path={case['access_path']}",
                    f"score_terms={compact_json(case['score_terms'])}",
                    f"primary_control_gap={case['primary_control_gap']}",
                    "evidence:",
                    *[
                        f"{item['evidence_id']} {item['time']} {item['source']}: {item['text']}"
                        for item in case["evidence"]
                    ],
                ]
            )
        )
    parts.append("triage_notes:" + ";".join(evidence["triage_notes"]))
    parts.append(
        "输出 JSON schema:"
        + compact_json(
            {
                "researcher_report": "string",
                "analyst_analysis": "string",
                "executor_matrix": [
                    {
                        "case_id": "string",
                        "sensitivity_points": "integer",
                        "volume_points": "integer",
                        "channel_points": "integer",
                        "anomaly_points": "integer",
                        "repeat_points": "integer",
                        "exposure_points": "integer",
                        "mitigation_points": "integer",
                        "risk_score": "integer",
                        "tier": "LOW|MEDIUM|HIGH|CRITICAL",
                        "action": "string",
                        "supporting_evidence_ids": ["E001"],
                    }
                ],
                "final_answer": {
                    "case_id": "string",
                    "risk_score": "integer",
                    "tier": "LOW|MEDIUM|HIGH|CRITICAL",
                    "action": "string",
                    "primary_control_gap": "string",
                },
            }
        )
    )
    return "\n".join(parts)


def find_json_objects(text: str) -> list[Any]:
    objects: list[Any] = []
    decoder = json.JSONDecoder()
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    for i, ch in enumerate(cleaned):
        if ch not in "{[":
            continue
        try:
            obj, _ = decoder.raw_decode(cleaned[i:])
        except json.JSONDecodeError:
            continue
        objects.append(obj)
    return objects


def extract_artifact(text: str) -> tuple[dict[str, Any], bool]:
    for obj in find_json_objects(text):
        if isinstance(obj, dict) and all(
            key in obj for key in ("researcher_report", "analyst_analysis", "executor_matrix", "final_answer")
        ):
            return obj, True
    return {"raw_response": text}, False


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
                "content": "Return only one valid JSON object. Do not include markdown or prose outside JSON.",
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


def run_once(
    suite: dict[str, Any],
    *,
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int,
    temperature: float,
    timeout: int,
) -> tuple[RunStats, dict[str, Any], dict[str, Any]]:
    task = suite["tasks"][0]
    prompt = build_prompt(suite)
    raw_response = ""
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    error = ""
    t0 = time.perf_counter()
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
    artifact, parse_ok = extract_artifact(raw_response)
    verifier_report = verify_artifact(artifact, suite) if parse_ok else {
        "ok": False,
        "errors": ["artifact JSON parse failed"],
        "warnings": [],
        "checks": {},
    }
    final_answer = artifact.get("final_answer") if isinstance(artifact.get("final_answer"), dict) else {}
    text_comm_chars = len(prompt) + len(raw_response)
    stats = RunStats(
        mode="single_llm_full_artifact",
        task_id=task["task_id"],
        title=task["title"],
        wall_time_s=wall_time_s,
        llm_calls=0 if error else 1,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        total_tokens=usage["total_tokens"],
        prompt_chars=len(prompt),
        response_chars=len(raw_response),
        text_comm_chars=text_comm_chars,
        text_comm_tokens_est=math.ceil(text_comm_chars / 4),
        artifact_parse_ok=parse_ok,
        verifier_ok=bool(verifier_report.get("ok")),
        verifier_errors=list(verifier_report.get("errors") or []),
        final_answer=final_answer,
        expected=task["reference_answer"],
        raw_response=raw_response,
        error=error[:500],
    )
    return stats, artifact, verifier_report


def generate_report(stats: RunStats, verifier_report: dict[str, Any], output_dir: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "# Intermediate Audit Single-LLM Full-Artifact Baseline",
        "",
        f"Mode: `{stats.mode}`",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "| Time(s) | Token in | Token out | Parse OK | Verifier OK | Final answer |",
        "|---:|---:|---:|---:|---:|---|",
        (
            f"| {stats.wall_time_s:.3f} | {stats.input_tokens} | {stats.output_tokens} | "
            f"{stats.artifact_parse_ok} | {stats.verifier_ok} | "
            f"`{json.dumps(stats.final_answer, ensure_ascii=False)}` |"
        ),
        "",
        "Expected:",
        "",
        f"`{json.dumps(stats.expected, ensure_ascii=False)}`",
        "",
        "Verifier errors:",
        "",
        *[f"- {error}" for error in stats.verifier_errors[:50]],
        "",
        "Run config:",
        "",
        f"`{json.dumps(manifest, ensure_ascii=False)}`",
        "",
        "Verifier check status:",
        "",
        f"`{json.dumps({k: v.get('ok') for k, v in verifier_report.get('checks', {}).items()}, ensure_ascii=False)}`",
    ]
    if stats.error:
        lines.extend(["", "Error:", "", f"`{stats.error}`"])
    (output_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run single-LLM full-artifact baseline.")
    parser.add_argument("--task-file", type=Path, default=TASK_FILE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    task_file = args.task_file if args.task_file.is_absolute() else PROJECT / args.task_file
    output_dir = args.output_dir if args.output_dir.is_absolute() else PROJECT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    suite = load_suite(task_file)
    manifest = {
        "suite_id": suite["suite_id"],
        "task_file": str(task_file),
        "output_dir": str(output_dir),
        "mode": "single_llm_full_artifact",
        "base_url": args.base_url,
        "model": args.model,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "chat_disable_thinking": os.getenv("CHAT_DISABLE_THINKING", "1"),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (output_dir / "RUN_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 72)
    print("Intermediate audit single-LLM full-artifact baseline")
    print(f"task={task_file}")
    print(f"output={output_dir}")
    print(f"base_url={args.base_url}")
    print(f"model={args.model}")
    print("=" * 72)

    stats, artifact, verifier_report = run_once(
        suite,
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        timeout=args.timeout,
    )
    (output_dir / "single_llm_full_artifact.json").write_text(json.dumps(asdict(stats), ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "artifact.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "verifier_report.json").write_text(json.dumps(verifier_report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "raw_response.txt").write_text(stats.raw_response, encoding="utf-8")
    generate_report(stats, verifier_report, output_dir, manifest)

    print(
        f"  parse={stats.artifact_parse_ok} verifier={stats.verifier_ok} "
        f"{stats.wall_time_s:.1f}s tokens={stats.input_tokens}/{stats.output_tokens} "
        f"answer={stats.final_answer}"
    )
    if stats.verifier_errors:
        print("  verifier errors:")
        for error in stats.verifier_errors[:8]:
            print(f"    - {error}")
    if stats.error:
        print(f"  error: {stats.error}")
    print(f"\nDONE: {output_dir}")
    return 0 if not stats.error else 1


if __name__ == "__main__":
    raise SystemExit(main())
