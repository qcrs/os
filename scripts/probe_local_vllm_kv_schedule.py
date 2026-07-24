#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.benchmark.continuous_task_family import (  # noqa: E402
    ContinuousTaskFamily,
    ContinuousTaskRound,
    load_continuous_task_family,
)
from v2.benchmark.kv_prefix_schedule import build_kv_prefix_schedule_plan  # noqa: E402
from v2.utils import sha256_digest, stable_json_dumps  # noqa: E402


DEFAULT_FAMILY_DIR = Path("v2/benchmark/samples/continuous_task_families/kv_prefix_reuse")
DEFAULT_ARTIFACT_ROOT = Path(
    "docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe local vLLM prefix-cache behavior for cache-friendly/cache-hostile schedules."
    )
    parser.add_argument("--family-dir", type=Path, default=DEFAULT_FAMILY_DIR)
    parser.add_argument("--mode", choices=("cache_friendly", "cache_hostile"), required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:53334/v1")
    parser.add_argument("--health-url", default="http://127.0.0.1:53334/health")
    parser.add_argument("--metrics-url", default="http://127.0.0.1:53334/metrics")
    parser.add_argument("--model", default="qwen3-32b")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--max-tokens", type=int, default=24)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--corpus-repeat", type=int, default=3)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--timeout-s", type=float, default=10.0)
    parser.add_argument("--request-timeout-s", type=float, default=120.0)
    parser.add_argument("--run-salt", default="")
    parser.add_argument("--output-json", type=Path, default=None)
    args = parser.parse_args()

    family = load_continuous_task_family(args.family_dir)
    plan = build_kv_prefix_schedule_plan(family, mode=args.mode)
    run_salt = args.run_salt or f"{args.mode}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    output_path = args.output_json or (
        DEFAULT_ARTIFACT_ROOT / f"e1_kv_schedule_{args.mode}_{run_salt}.json"
    )

    ordered_rounds = _ordered_rounds(family=family, task_ids=plan.task_ids[: args.limit])
    health = _fetch_url(args.health_url, timeout_s=args.timeout_s)
    metrics_before = _fetch_metrics(args.metrics_url, timeout_s=args.timeout_s)

    client = OpenAI(base_url=args.base_url, api_key=args.api_key, timeout=args.request_timeout_s)
    requests: list[dict[str, Any]] = []
    started_ns = time.perf_counter_ns()
    for index, family_round in enumerate(ordered_rounds):
        metrics_pre_request = _fetch_metrics(args.metrics_url, timeout_s=args.timeout_s)
        prompt = _build_prompt(
            family_round=family_round,
            family=family,
            mode=args.mode,
            run_salt=run_salt,
            corpus_repeat=args.corpus_repeat,
        )
        request_payload = _run_prompt(
            client=client,
            model=args.model,
            prompt=prompt,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
        metrics_post_request = _fetch_metrics(args.metrics_url, timeout_s=args.timeout_s)
        requests.append(
            {
                "index": index,
                "task_id": family_round.task_id,
                "round": family_round.round,
                "dataset_id": family_round.dataset_id,
                "intent_op": family_round.canonical_task_spec.intent_op,
                "prompt": {
                    "bytes": len(prompt.encode("utf-8")),
                    "sha256": sha256_digest(prompt),
                    "byte_estimated_tokens": max(len(prompt.encode("utf-8")) // 4, 1),
                    "corpus_repeat": args.corpus_repeat,
                },
                "metrics_before_request": metrics_pre_request,
                "metrics_after_request": metrics_post_request,
                **request_payload,
            }
        )

    metrics_after = _fetch_metrics(args.metrics_url, timeout_s=args.timeout_s)
    payload = {
        "schema_version": "statebus.local_vllm_kv_schedule_probe.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_boundary": (
            "engine_local_prefix_reuse_probe_only_no_kv_tensor_export; "
            "raw vLLM metrics are gauges unless explicit hit/miss counters are exposed"
        ),
        "mode": args.mode,
        "model": args.model,
        "base_url": args.base_url,
        "health_url": args.health_url,
        "metrics_url": args.metrics_url,
        "run_salt": run_salt,
        "family": {
            "family_id": family.family_id,
            "manifest_path": family.manifest_path,
            "claim_tier": family.claim_tier,
        },
        "schedule_plan": plan.canonical_payload(),
        "prompt_policy": {
            "shared_prefix_policy": "system_plus_static_corpus_evidence",
            "role_suffix_policy": "compact_task_instruction_json_only",
            "corpus_repeat": args.corpus_repeat,
            "cross_mode_cache_contamination_control": "mode-specific run_salt in shared prefix",
        },
        "service_health_before": health,
        "metrics_before": metrics_before,
        "metrics_after": metrics_after,
        "summary": _summarize_requests(requests),
        "requests": requests,
        "wall_ms": _elapsed_ms(started_ns),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")
    print(output_path)
    return 0


def _ordered_rounds(
    *,
    family: ContinuousTaskFamily,
    task_ids: tuple[str, ...],
) -> tuple[ContinuousTaskRound, ...]:
    by_task_id = {family_round.task_id: family_round for family_round in family.rounds}
    return tuple(by_task_id[task_id] for task_id in task_ids)


def _build_prompt(
    *,
    family_round: ContinuousTaskRound,
    family: ContinuousTaskFamily,
    mode: str,
    run_salt: str,
    corpus_repeat: int,
) -> str:
    document_path = _document_path(family_round)
    document_text = document_path.read_text(encoding="utf-8")
    repeated_corpus = "\n\n".join(
        f"[CORPUS_COPY:{copy_index + 1}/{corpus_repeat}]\n{document_text.rstrip()}"
        for copy_index in range(corpus_repeat)
    )
    arguments = dict(family_round.canonical_task_spec.arguments)
    corpus_group = str(arguments.get("kv_probe_corpus_group", family_round.dataset_id))
    return "\n".join(
        [
            "STATEBUS_LOCAL_VLLM_KV_PREFIX_PROBE",
            f"family_id={family.family_id}",
            f"mode={mode}",
            f"run_salt={run_salt}",
            f"corpus_group={corpus_group}",
            "claim_boundary=engine_local_prefix_reuse_only_no_kv_tensor_export",
            "",
            "[STATIC_CORPUS_EVIDENCE_BEGIN]",
            repeated_corpus,
            "[STATIC_CORPUS_EVIDENCE_END]",
            "",
            "[ROLE_SUFFIX_BEGIN]",
            f"task_id={family_round.task_id}",
            f"round={family_round.round}",
            f"intent_op={family_round.canonical_task_spec.intent_op}",
            f"request={family_round.request_text}",
            "Return compact JSON with keys task_id, dataset_id, intent_op, status.",
            "[ROLE_SUFFIX_END]",
        ]
    )


def _document_path(family_round: ContinuousTaskRound) -> Path:
    document_path = str(family_round.canonical_task_spec.arguments.get("document_path", "")).strip()
    path = Path(document_path)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def _run_prompt(
    *,
    client: OpenAI,
    model: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    started_ns = time.perf_counter_ns()
    ttft_ms = 0.0
    completion_chunks: list[str] = []
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            delta = getattr(choice, "delta", None) if choice is not None else None
            content = getattr(delta, "content", None) or ""
            if content and ttft_ms == 0.0:
                ttft_ms = _elapsed_ms(started_ns)
            if content:
                completion_chunks.append(content)
        completion = "".join(completion_chunks)
        return {
            "ok": True,
            "error": "",
            "latency_ms": _elapsed_ms(started_ns),
            "ttft_ms": ttft_ms,
            "completion_bytes": len(completion.encode("utf-8")),
            "completion_sample": completion[:500],
        }
    except Exception as exc:  # noqa: BLE001 - mechanism probe records request failures.
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "latency_ms": _elapsed_ms(started_ns),
            "ttft_ms": ttft_ms,
            "completion_bytes": 0,
            "completion_sample": "",
        }


def _fetch_url(url: str, *, timeout_s: float) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=timeout_s) as response:  # nosec B310 - local audit endpoint.
            body = response.read().decode("utf-8", errors="replace")
            return {
                "ok": 200 <= int(response.status) < 400,
                "status_code": int(response.status),
                "body_sample": body[:500],
                "error": "",
            }
    except URLError as exc:
        return {"ok": False, "status_code": None, "body_sample": "", "error": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status_code": None, "body_sample": "", "error": f"{type(exc).__name__}: {exc}"}


def _fetch_metrics(url: str, *, timeout_s: float) -> dict[str, Any]:
    fetched = _fetch_raw_metrics(url, timeout_s=timeout_s)
    if not fetched["ok"]:
        return {
            **fetched,
            "raw_metric_lines": [],
            "raw_metric_values": {},
            "raw_metric_names": [],
        }
    values: dict[str, float] = {}
    lines: list[str] = []
    for raw_line in str(fetched["body"]).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        metric_name = line.split("{", 1)[0].split(" ", 1)[0]
        if not _is_cache_metric(metric_name):
            continue
        lines.append(line)
        try:
            values[metric_name] = float(line.rsplit(" ", 1)[-1])
        except ValueError:
            continue
    return {
        "ok": True,
        "status_code": fetched["status_code"],
        "error": "",
        "raw_metric_lines": lines,
        "raw_metric_values": values,
        "raw_metric_names": sorted(values),
    }


def _fetch_raw_metrics(url: str, *, timeout_s: float) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=timeout_s) as response:  # nosec B310 - local audit endpoint.
            return {
                "ok": 200 <= int(response.status) < 400,
                "status_code": int(response.status),
                "body": response.read().decode("utf-8", errors="replace"),
                "error": "",
            }
    except URLError as exc:
        return {"ok": False, "status_code": None, "body": "", "error": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status_code": None, "body": "", "error": f"{type(exc).__name__}: {exc}"}


def _is_cache_metric(metric_name: str) -> bool:
    lowered = metric_name.lower()
    return "prefix" in lowered or "cache" in lowered or "kv" in lowered


def _summarize_requests(requests: list[dict[str, Any]]) -> dict[str, Any]:
    ok_requests = [request for request in requests if request["ok"]]
    ttfts = [float(request["ttft_ms"]) for request in ok_requests if float(request["ttft_ms"]) > 0.0]
    latencies = [float(request["latency_ms"]) for request in ok_requests]
    final_metrics = requests[-1]["metrics_after_request"] if requests else {}
    values = final_metrics.get("raw_metric_values", {}) if isinstance(final_metrics, dict) else {}
    return {
        "request_count": len(requests),
        "ok_count": len(ok_requests),
        "error_count": len(requests) - len(ok_requests),
        "mean_ttft_ms": sum(ttfts) / len(ttfts) if ttfts else 0.0,
        "mean_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
        "final_gpu_prefix_cache_hit_rate": values.get("vllm:gpu_prefix_cache_hit_rate"),
        "final_cpu_prefix_cache_hit_rate": values.get("vllm:cpu_prefix_cache_hit_rate"),
        "final_gpu_cache_usage_perc": values.get("vllm:gpu_cache_usage_perc"),
        "final_cpu_cache_usage_perc": values.get("vllm:cpu_cache_usage_perc"),
    }


def _elapsed_ms(start_ns: int) -> float:
    return (time.perf_counter_ns() - start_ns) / 1_000_000.0


if __name__ == "__main__":
    raise SystemExit(main())
