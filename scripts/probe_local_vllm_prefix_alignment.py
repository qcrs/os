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

from v2.runtime.role_path import compile_prefix_layout  # noqa: E402
from v2.runtime.vllm_metrics import parse_vllm_prefix_cache_metrics  # noqa: E402
from v2.utils import sha256_digest, stable_json_dumps  # noqa: E402


DEFAULT_EVIDENCE_FILE = Path(
    "v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/"
    "orion_factory_ops_report_2026.md"
)
DEFAULT_ARTIFACT_ROOT = Path(
    "docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts"
)
DEFAULT_ROLES = ("planner", "retriever", "executor", "summarizer", "verifier")
JSON_RESPONSE_FORMAT = {"type": "json_object"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe local vLLM prefix-cache behavior for shared_evidence_prefix on/off."
    )
    parser.add_argument("--mode", choices=("shared_evidence_prefix", "independent"), required=True)
    parser.add_argument("--evidence-file", type=Path, default=DEFAULT_EVIDENCE_FILE)
    parser.add_argument("--base-url", default="http://127.0.0.1:53334/v1")
    parser.add_argument("--health-url", default="http://127.0.0.1:53334/health")
    parser.add_argument("--metrics-url", default="http://127.0.0.1:53334/metrics")
    parser.add_argument("--model", default="qwen3-32b")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--max-tokens", type=int, default=24)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--evidence-repeat", type=int, default=4)
    parser.add_argument("--timeout-s", type=float, default=10.0)
    parser.add_argument("--request-timeout-s", type=float, default=120.0)
    parser.add_argument("--run-salt", default="")
    parser.add_argument("--output-json", type=Path, default=None)
    args = parser.parse_args()

    run_salt = args.run_salt or f"{args.mode}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    output_path = args.output_json or (
        DEFAULT_ARTIFACT_ROOT / f"e2_prefix_alignment_{args.mode}_{run_salt}.json"
    )
    evidence_text = _evidence_text(
        evidence_file=args.evidence_file,
        evidence_repeat=args.evidence_repeat,
        run_salt=run_salt,
    )
    prompts = [
        _compile_role_prompt(role=role, mode=args.mode, evidence_text=evidence_text, run_salt=run_salt)
        for role in DEFAULT_ROLES
    ]

    health = _fetch_url(args.health_url, timeout_s=args.timeout_s)
    metrics_before = _fetch_metrics(args.metrics_url, timeout_s=args.timeout_s)
    client = OpenAI(base_url=args.base_url, api_key=args.api_key, timeout=args.request_timeout_s)
    requests: list[dict[str, Any]] = []
    started_ns = time.perf_counter_ns()
    for index, item in enumerate(prompts):
        metrics_pre_request = _fetch_metrics(args.metrics_url, timeout_s=args.timeout_s)
        response = _run_prompt(
            client=client,
            model=args.model,
            expected_role=item["role"],
            prompt=item["prompt"],
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
        metrics_post_request = _fetch_metrics(args.metrics_url, timeout_s=args.timeout_s)
        counter_delta = _counter_delta(metrics_pre_request, metrics_post_request)
        requests.append(
            {
                "index": index,
                "role": item["role"],
                "layout_plan": item["layout_plan"],
                "prompt": {
                    "bytes": len(item["prompt"].encode("utf-8")),
                    "sha256": sha256_digest(item["prompt"]),
                    "byte_estimated_tokens": max(len(item["prompt"].encode("utf-8")) // 4, 1),
                },
                "metrics_before_request": metrics_pre_request,
                "metrics_after_request": metrics_post_request,
                "prefix_counter_delta": counter_delta,
                **response,
            }
        )

    metrics_after = _fetch_metrics(args.metrics_url, timeout_s=args.timeout_s)
    payload = {
        "schema_version": "statebus.local_vllm_prefix_alignment_probe.v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_boundary": (
            "shared_evidence_prefix_layout_probe_only_no_kv_tensor_export; "
            "task-local cache attribution uses only explicit query/hit counter deltas"
        ),
        "mode": args.mode,
        "model": args.model,
        "base_url": args.base_url,
        "health_url": args.health_url,
        "metrics_url": args.metrics_url,
        "run_salt": run_salt,
        "evidence_file": str(args.evidence_file),
        "evidence_sha256": sha256_digest(evidence_text),
        "evidence_repeat": args.evidence_repeat,
        "evidence_bytes": len(evidence_text.encode("utf-8")),
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "response_format": JSON_RESPONSE_FORMAT,
        "roles": list(DEFAULT_ROLES),
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


def _evidence_text(*, evidence_file: Path, evidence_repeat: int, run_salt: str) -> str:
    path = evidence_file if evidence_file.is_absolute() else (REPO_ROOT / evidence_file).resolve()
    source = path.read_text(encoding="utf-8").rstrip()
    copies = [
        f"[E2_EVIDENCE_COPY:{copy_index + 1}/{evidence_repeat};run_salt={run_salt}]\n{source}"
        for copy_index in range(evidence_repeat)
    ]
    return "\n\n".join(copies)


def _compile_role_prompt(*, role: str, mode: str, evidence_text: str, run_salt: str) -> dict[str, Any]:
    instruction = (
        "Use the evidence to return compact JSON with keys role, status, and cited_metric_count. "
        "Do not add prose outside JSON."
    )
    payload = {
        "role": role,
        "probe": "e2_shared_evidence_prefix",
        "run_salt": run_salt,
        "e": evidence_text,
    }
    compiled = compile_prefix_layout(
        role_label=role,
        instruction=instruction,
        payload_tag=f"statebus-e2-{role}-v1",
        payload=payload,
        text_sections=(("Probe", "shared_evidence_prefix_ablation"),),
        evidence_blocks=(),
        handoff_mode="structured_collaboration",
        prefix_alignment_mode=mode,
        shared_prefix_text=evidence_text,
    )
    return {
        "role": role,
        "prompt": compiled.prompt,
        "layout_plan": compiled.layout_plan.canonical_payload(),
    }


def _run_prompt(
    *,
    client: OpenAI,
    model: str,
    expected_role: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    started_ns = time.perf_counter_ns()
    ttft_ms = 0.0
    completion_chunks: list[str] = []
    finish_reason = ""
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=JSON_RESPONSE_FORMAT,
            stream=True,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            if choice is not None and getattr(choice, "finish_reason", None):
                finish_reason = str(choice.finish_reason)
            delta = getattr(choice, "delta", None) if choice is not None else None
            content = getattr(delta, "content", None) or ""
            if content and ttft_ms == 0.0:
                ttft_ms = _elapsed_ms(started_ns)
            if content:
                completion_chunks.append(content)
        completion = "".join(completion_chunks)
        try:
            completion_payload = json.loads(completion)
        except json.JSONDecodeError:
            completion_payload = None
        completion_contract_valid = (
            isinstance(completion_payload, dict)
            and completion_payload.get("role") == expected_role
            and isinstance(completion_payload.get("status"), str)
            and isinstance(completion_payload.get("cited_metric_count"), int)
        )
        return {
            "ok": True,
            "error": "",
            "latency_ms": _elapsed_ms(started_ns),
            "ttft_ms": ttft_ms,
            "completion_bytes": len(completion.encode("utf-8")),
            "completion_sample": completion[:500],
            "completion_json_valid": isinstance(completion_payload, dict),
            "completion_contract_valid": completion_contract_valid,
            "finish_reason": finish_reason,
        }
    except Exception as exc:  # noqa: BLE001 - mechanism probe records request failures.
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "latency_ms": _elapsed_ms(started_ns),
            "ttft_ms": ttft_ms,
            "completion_bytes": 0,
            "completion_sample": "",
            "completion_json_valid": False,
            "completion_contract_valid": False,
            "finish_reason": "",
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
    parsed = parse_vllm_prefix_cache_metrics(str(fetched["body"]))
    return {
        "ok": True,
        "status_code": fetched["status_code"],
        "error": "",
        "raw_metric_lines": lines,
        "raw_metric_values": values,
        "raw_metric_names": sorted(values),
        "prefix_cache": parsed.canonical_payload(),
    }


def _counter_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_cache = before.get("prefix_cache", {}) if isinstance(before, dict) else {}
    after_cache = after.get("prefix_cache", {}) if isinstance(after, dict) else {}
    query_delta = float(after_cache.get("queries_total", 0.0)) - float(
        before_cache.get("queries_total", 0.0)
    )
    hit_delta = float(after_cache.get("hits_total", 0.0)) - float(
        before_cache.get("hits_total", 0.0)
    )
    before_counter_names = set(before_cache.get("counter_metric_names", []))
    after_counter_names = set(after_cache.get("counter_metric_names", []))
    has_before_pair = any("queries_total" in name for name in before_counter_names) and any(
        "hits_total" in name for name in before_counter_names
    )
    has_after_pair = any("queries_total" in name for name in after_counter_names) and any(
        "hits_total" in name for name in after_counter_names
    )
    available = has_before_pair and has_after_pair
    valid = available and query_delta > 0.0 and 0.0 <= hit_delta <= query_delta
    return {
        "available": available,
        "valid": valid,
        "queries": query_delta if valid else 0.0,
        "hits": hit_delta if valid else 0.0,
        "hit_rate": hit_delta / query_delta if valid else None,
        "unavailable_reason": (
            ""
            if valid
            else (
                "invalid_counter_delta"
                if available
                else (
                    "service_lifetime_gauge_only"
                    if before_cache.get("gauge_metric_names") or after_cache.get("gauge_metric_names")
                    else "query_hit_counters_not_exposed"
                )
            )
        ),
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
    valid_deltas = [
        request["prefix_counter_delta"]
        for request in requests
        if request.get("prefix_counter_delta", {}).get("valid") is True
    ]
    delta_queries = sum(float(item["queries"]) for item in valid_deltas)
    delta_hits = sum(float(item["hits"]) for item in valid_deltas)
    cold_reference = ok_requests[:1]
    warm_candidates = ok_requests[1:]
    cold_ttft_ms = float(cold_reference[0]["ttft_ms"]) if cold_reference else 0.0
    cold_latency_ms = float(cold_reference[0]["latency_ms"]) if cold_reference else 0.0
    warm_ttft_values = [
        float(item["ttft_ms"]) for item in warm_candidates if float(item["ttft_ms"]) > 0.0
    ]
    warm_latency_values = [float(item["latency_ms"]) for item in warm_candidates]
    warm_mean_ttft_ms = (
        sum(warm_ttft_values) / len(warm_ttft_values) if warm_ttft_values else 0.0
    )
    warm_mean_latency_ms = (
        sum(warm_latency_values) / len(warm_latency_values) if warm_latency_values else 0.0
    )
    unavailable_reasons: dict[str, int] = {}
    for request in requests:
        reason = str(request.get("prefix_counter_delta", {}).get("unavailable_reason", "")).strip()
        if reason:
            unavailable_reasons[reason] = unavailable_reasons.get(reason, 0) + 1
    return {
        "request_count": len(requests),
        "ok_count": len(ok_requests),
        "error_count": len(requests) - len(ok_requests),
        "completion_json_valid_count": sum(
            int(request.get("completion_json_valid") is True) for request in requests
        ),
        "completion_contract_valid_count": sum(
            int(request.get("completion_contract_valid") is True) for request in requests
        ),
        "mean_ttft_ms": sum(ttfts) / len(ttfts) if ttfts else 0.0,
        "mean_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
        "counter_delta_valid_request_count": len(valid_deltas),
        "counter_delta_unavailable_request_count": len(requests) - len(valid_deltas),
        "counter_delta_queries": delta_queries,
        "counter_delta_hits": delta_hits,
        "counter_delta_hit_rate": delta_hits / delta_queries if delta_queries > 0.0 else None,
        "counter_delta_unavailable_reasons": dict(sorted(unavailable_reasons.items())),
        "serialized_cold_reference_count": len(cold_reference),
        "serialized_warm_candidate_count": len(warm_candidates),
        "cold_reference_ttft_ms": cold_ttft_ms,
        "warm_candidate_mean_ttft_ms": warm_mean_ttft_ms,
        "observed_warm_ttft_reduction_ms": cold_ttft_ms - warm_mean_ttft_ms,
        "observed_warm_ttft_reduction_ratio": (
            (cold_ttft_ms - warm_mean_ttft_ms) / cold_ttft_ms if cold_ttft_ms > 0.0 else None
        ),
        "cold_reference_latency_ms": cold_latency_ms,
        "warm_candidate_mean_latency_ms": warm_mean_latency_ms,
        "observed_warm_latency_reduction_ms": cold_latency_ms - warm_mean_latency_ms,
        "latency_observation_valid": bool(cold_reference and warm_candidates),
        "latency_claim_boundary": (
            "serialized_same_run_cold_first_vs_later_shared-prefix-eligible_requests; "
            "requires independent-mode paired run for causal attribution"
        ),
        "final_gpu_prefix_cache_hit_rate": values.get("vllm:gpu_prefix_cache_hit_rate"),
        "final_cpu_prefix_cache_hit_rate": values.get("vllm:cpu_prefix_cache_hit_rate"),
        "final_gpu_cache_usage_perc": values.get("vllm:gpu_cache_usage_perc"),
        "final_cpu_cache_usage_perc": values.get("vllm:cpu_cache_usage_perc"),
    }


def _elapsed_ms(start_ns: int) -> float:
    return (time.perf_counter_ns() - start_ns) / 1_000_000.0


if __name__ == "__main__":
    raise SystemExit(main())
