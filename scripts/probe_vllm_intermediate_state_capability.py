#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.runtime.logit_state import serialize_logit_state  # noqa: E402
from v2.utils import stable_json_dumps  # noqa: E402


DEFAULT_ARTIFACT = Path(
    "docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/"
    "vllm_intermediate_state_capability_20260711.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe local vLLM OpenAI-compatible intermediate-state capability boundaries."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:53334/v1")
    parser.add_argument("--model", default="qwen3-32b")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--top-logprobs", type=int, default=5)
    parser.add_argument("--timeout-s", type=float, default=30.0)
    parser.add_argument("--request-timeout-s", type=float, default=180.0)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_ARTIFACT)
    args = parser.parse_args()

    health_url = f"{args.base_url.removesuffix('/v1')}/health"
    metrics_url = f"{args.base_url.removesuffix('/v1')}/metrics"
    models_url = f"{args.base_url}/models"
    completion_url = f"{args.base_url}/chat/completions"

    health = _fetch_text(health_url, timeout_s=args.timeout_s)
    models = _fetch_json(models_url, timeout_s=args.timeout_s, api_key=args.api_key)
    metrics = _fetch_text(metrics_url, timeout_s=args.timeout_s)
    metric_summary = _summarize_metrics(metrics)

    base_payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": 'Return JSON only: {"ok": true}'}],
        "max_tokens": args.max_tokens,
        "temperature": 0,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    cases = [
        ("logprobs_only", {"logprobs": True, "top_logprobs": args.top_logprobs}),
        ("return_hidden_states_top", {"return_hidden_states": True}),
        ("output_hidden_states_top", {"output_hidden_states": True}),
        (
            "return_hidden_states_plus_logprobs",
            {
                "return_hidden_states": True,
                "logprobs": True,
                "top_logprobs": args.top_logprobs,
            },
        ),
        (
            "output_hidden_states_plus_logprobs",
            {
                "output_hidden_states": True,
                "logprobs": True,
                "top_logprobs": args.top_logprobs,
            },
        ),
        ("unknown_field_control", {"statebus_probe_unknown_flag": True}),
    ]

    case_results = [
        _probe_case(
            case_name=name,
            url=completion_url,
            api_key=args.api_key,
            payload={**base_payload, **extra},
            timeout_s=args.request_timeout_s,
            top_k=args.top_logprobs,
        )
        for name, extra in cases
    ]

    logprobs_case = _case_by_name(case_results, "logprobs_only")
    hidden_state_cases = [
        result
        for result in case_results
        if result["case_name"] in {"return_hidden_states_top", "output_hidden_states_top"}
    ]
    unknown_case = _case_by_name(case_results, "unknown_field_control")
    payload = {
        "schema_version": "statebus.vllm_intermediate_state_capability_probe.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_boundary": "openai_compatible_logprobs_probe_only_no_hidden_state_tensor_no_kv_tensor_export",
        "service": {
            "base_url": args.base_url,
            "model": args.model,
            "health_url": health_url,
            "metrics_url": metrics_url,
            "models_url": models_url,
            "health": health,
            "models": {
                "status_code": models["status_code"],
                "model_ids": _model_ids(models["body"]),
                "selected_model": _selected_model(models["body"], args.model),
            },
            "metrics": metric_summary,
        },
        "request_contract": {
            "messages": base_payload["messages"],
            "max_tokens": args.max_tokens,
            "temperature": 0,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        "cases": case_results,
        "summary": {
            "health_ok": bool(health["ok"]),
            "health_status_code": health["status_code"],
            "allow_logprobs": bool(_selected_model(models["body"], args.model).get("allow_logprobs")),
            "max_model_len": _selected_model(models["body"], args.model).get("max_model_len"),
            "gpu_prefix_cache_hit_rate_present": metric_summary["has_gpu_prefix_cache_hit_rate"],
            "cache_config_info_present": metric_summary["has_cache_config_info"],
            "raw_prefix_hit_miss_counters_present": metric_summary["has_raw_prefix_hit_miss_counters"],
            "logprobs_supported": bool(logprobs_case.get("has_logprobs")),
            "logprobs_parseable": bool(logprobs_case.get("final_token_top_logprobs_count", 0) > 0),
            "logit_state_bytes": int(logprobs_case.get("logit_state_bytes", 0) or 0),
            "logit_entropy": logprobs_case.get("logit_entropy"),
            "logit_confidence_proxy": logprobs_case.get("logit_confidence_proxy"),
            "hidden_states_supported": any(result.get("has_hidden_states_field") for result in hidden_state_cases),
            "hidden_state_flags_silently_ignored": all(
                result.get("status_code") == 200 and not result.get("has_hidden_states_field")
                for result in hidden_state_cases
            )
            and unknown_case.get("status_code") == 200,
            "lightweight_logit_state_viable": bool(
                logprobs_case.get("has_logprobs")
                and (logprobs_case.get("final_token_top_logprobs_count", 0) or 0) >= 2
                and (logprobs_case.get("logit_state_bytes", 0) or 0) > 0
            ),
            "recommended_boundary": (
                "Engine-Local Prefix Reuse + output-distribution logprob/confidence proxy; "
                "no hidden-state tensor export"
            ),
        },
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")
    print(args.output_json)
    return 0


def _fetch_text(url: str, *, timeout_s: float) -> dict[str, Any]:
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=timeout_s) as response:  # nosec B310 - local endpoint.
            body = response.read().decode("utf-8", errors="replace")
            return {
                "ok": 200 <= int(response.status) < 400,
                "status_code": int(response.status),
                "body": body,
                "body_sample": body[:500],
                "error": "",
            }
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "status_code": exc.code, "body": body, "body_sample": body[:500], "error": ""}
    except URLError as exc:
        return {"ok": False, "status_code": None, "body": "", "body_sample": "", "error": f"{type(exc).__name__}: {exc}"}


def _fetch_json(url: str, *, timeout_s: float, api_key: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:  # nosec B310 - local endpoint.
            body = json.loads(response.read().decode("utf-8", errors="replace"))
            return {"ok": True, "status_code": int(response.status), "body": body, "error": ""}
    except HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            body = {"raw": ""}
        return {"ok": False, "status_code": exc.code, "body": body, "error": ""}
    except URLError as exc:
        return {"ok": False, "status_code": None, "body": {}, "error": f"{type(exc).__name__}: {exc}"}


def _probe_case(
    *,
    case_name: str,
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_s: float,
    top_k: int,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    result: dict[str, Any] = {
        "case_name": case_name,
        "request_payload": payload,
    }
    try:
        with urlopen(request, timeout=timeout_s) as response:  # nosec B310 - local endpoint.
            parsed = json.loads(response.read().decode("utf-8", errors="replace"))
            result.update(_parsed_case_summary(parsed, status_code=int(response.status), top_k=top_k))
            return result
    except HTTPError as exc:
        try:
            error_body = json.loads(exc.read().decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            error_body = {"raw": ""}
        result.update({"status_code": exc.code, "error": error_body})
        return result
    except URLError as exc:
        result.update({"status_code": None, "error": f"{type(exc).__name__}: {exc}"})
        return result


def _parsed_case_summary(parsed: dict[str, Any], *, status_code: int, top_k: int) -> dict[str, Any]:
    choice = (parsed.get("choices") or [{}])[0]
    logprobs = choice.get("logprobs") if isinstance(choice, dict) else None
    content = (logprobs or {}).get("content") if isinstance(logprobs, dict) else None
    payload_bytes, entropy, confidence = serialize_logit_state(content or [], top_k=top_k)
    final_token = (content or [])[-1] if content else None
    final_top_logprobs = []
    if isinstance(final_token, dict):
        final_top_logprobs = list(final_token.get("top_logprobs") or [])
    else:
        final_top_logprobs = list(getattr(final_token, "top_logprobs", None) or [])
    return {
        "status_code": status_code,
        "error": "",
        "response_keys": sorted(parsed.keys()),
        "choice_keys": sorted(choice.keys()) if isinstance(choice, dict) else [],
        "usage": parsed.get("usage"),
        "message_excerpt": json.dumps(choice.get("message", {}), ensure_ascii=False)[:300]
        if isinstance(choice, dict)
        else "",
        "has_logprobs": logprobs is not None,
        "has_hidden_states_field": "hidden_states" in parsed or (
            isinstance(choice, dict) and "hidden_states" in choice
        ),
        "content_item_count": len(content or []),
        "final_token_top_logprobs_count": len(final_top_logprobs),
        "logit_state_bytes": len(payload_bytes),
        "logit_entropy": entropy,
        "logit_confidence_proxy": confidence,
        "logprobs_preview": _logprobs_preview(content or []),
    }


def _logprobs_preview(content: list[object]) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for item in content[:3]:
        if isinstance(item, dict):
            top_items = list(item.get("top_logprobs") or [])
            preview.append(
                {
                    "token": item.get("token"),
                    "logprob": item.get("logprob"),
                    "top_logprobs_count": len(top_items),
                    "top_logprobs_preview": top_items[:3],
                }
            )
            continue
        top_items = list(getattr(item, "top_logprobs", None) or [])
        preview.append(
            {
                "token": getattr(item, "token", None),
                "logprob": getattr(item, "logprob", None),
                "top_logprobs_count": len(top_items),
                "top_logprobs_preview": [_object_preview(entry) for entry in top_items[:3]],
            }
        )
    return preview


def _object_preview(item: object) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    return {
        "token": getattr(item, "token", None),
        "logprob": getattr(item, "logprob", None),
        "bytes": getattr(item, "bytes", None),
    }


def _summarize_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    body = str(metrics.get("body", "") or "")
    relevant_lines = [
        line.strip()
        for line in body.splitlines()
        if line.strip() and not line.startswith("#") and _is_relevant_metric_line(line)
    ]
    names = sorted({line.split("{", 1)[0].split(" ", 1)[0] for line in relevant_lines})
    return {
        "status_code": metrics["status_code"],
        "ok": metrics["ok"],
        "error": metrics["error"],
        "relevant_metric_names": names,
        "relevant_metric_lines": relevant_lines,
        "has_gpu_prefix_cache_hit_rate": "vllm:gpu_prefix_cache_hit_rate" in names,
        "has_cache_config_info": "vllm:cache_config_info" in names,
        "has_raw_prefix_hit_miss_counters": any(
            name.endswith("hits_total") or name.endswith("misses_total") for name in names
        ),
    }


def _is_relevant_metric_line(line: str) -> bool:
    lowered = line.lower()
    return any(token in lowered for token in ("prefix", "cache", "kv"))


def _model_ids(payload: dict[str, Any]) -> list[str]:
    return [
        str(item.get("id", ""))
        for item in payload.get("data", [])
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    ]


def _selected_model(payload: dict[str, Any], model_id: str) -> dict[str, Any]:
    for item in payload.get("data", []):
        if isinstance(item, dict) and str(item.get("id", "")).strip() == model_id:
            permission = item.get("permission") or []
            allow_logprobs = any(bool(entry.get("allow_logprobs")) for entry in permission if isinstance(entry, dict))
            return {
                "id": item.get("id"),
                "max_model_len": item.get("max_model_len"),
                "allow_logprobs": allow_logprobs,
                "root": item.get("root"),
            }
    return {}


def _case_by_name(results: list[dict[str, Any]], case_name: str) -> dict[str, Any]:
    for result in results:
        if result.get("case_name") == case_name:
            return result
    return {}


if __name__ == "__main__":
    raise SystemExit(main())
