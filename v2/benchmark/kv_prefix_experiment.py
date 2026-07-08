from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI

from v2.runtime.vllm_metrics import VllmPrefixCacheMetrics, fetch_vllm_prefix_cache_metrics
from v2.utils import sha256_digest, stable_json_dumps


DEFAULT_ROLE_SUFFIXES = {
    "executor": "Based on the shared evidence prefix, return a compact JSON execution plan.",
    "summarizer": "Based on the shared evidence prefix, return a compact JSON management summary.",
    "verifier": "Based on the shared evidence prefix, return a compact JSON risk check.",
}


@dataclass(frozen=True)
class PrefixExperimentPrompt:
    role: str
    content: str
    content_hash: str
    content_bytes: int


def build_shared_prefix_role_suffix_prompts(
    *,
    shared_prefix: str,
    role_suffixes: dict[str, str] | None = None,
) -> tuple[PrefixExperimentPrompt, ...]:
    suffixes = role_suffixes or DEFAULT_ROLE_SUFFIXES
    return tuple(
        _prompt(role=role, content=f"{shared_prefix.rstrip()}\n\n[ROLE_SUFFIX:{role}]\n{suffix.strip()}")
        for role, suffix in suffixes.items()
    )


def build_chain_inheritance_prompts(
    *,
    shared_prefix: str,
    role_suffixes: dict[str, str] | None = None,
) -> tuple[PrefixExperimentPrompt, ...]:
    suffixes = role_suffixes or DEFAULT_ROLE_SUFFIXES
    running_prefix = shared_prefix.rstrip()
    prompts: list[PrefixExperimentPrompt] = []
    for role, suffix in suffixes.items():
        content = f"{running_prefix}\n\n[ROLE_SUFFIX:{role}]\n{suffix.strip()}"
        prompts.append(_prompt(role=role, content=content))
        running_prefix = content
    return tuple(prompts)


def run_prefix_alignment_experiment(
    *,
    prompts: tuple[PrefixExperimentPrompt, ...],
    base_url: str,
    model: str,
    api_key: str = "EMPTY",
    metrics_url: str = "http://127.0.0.1:8000/metrics",
    max_tokens: int = 64,
    temperature: float = 0.0,
    stream: bool = True,
) -> dict[str, Any]:
    client = OpenAI(base_url=base_url, api_key=api_key)
    metrics_before = _fetch_metrics(metrics_url)
    started_ns = time.perf_counter_ns()
    responses: list[dict[str, Any]] = []
    for prompt in prompts:
        responses.append(
            _run_prompt(
                client=client,
                prompt=prompt,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=stream,
            )
        )
    metrics_after = _fetch_metrics(metrics_url)
    return {
        "schema_version": "statebus.kv_prefix_alignment_experiment.v1",
        "claim_boundary": "mechanism_probe_requires_local_vllm_prefix_caching_enabled",
        "model": model,
        "base_url": base_url,
        "metrics_url": metrics_url,
        "prompt_count": len(prompts),
        "prompt_hashes": [prompt.content_hash for prompt in prompts],
        "shared_prefix_strategy": "shared_prefix_role_suffix_or_chain",
        "streaming_ttft_enabled": stream,
        "wall_ms": _elapsed_ms(started_ns),
        "metrics_before": metrics_before.canonical_payload(),
        "metrics_after": metrics_after.canonical_payload(),
        "metrics_delta": _metrics_delta(metrics_before, metrics_after),
        "responses": responses,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local vLLM prefix-alignment probe.")
    parser.add_argument("--shared-prefix-file", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--metrics-url", default="http://127.0.0.1:8000/metrics")
    parser.add_argument("--model", default="qwen3-32b")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--strategy", choices=("shared-prefix", "chain"), default="shared-prefix")
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--no-stream", action="store_true")
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args()

    shared_prefix = Path(args.shared_prefix_file).read_text(encoding="utf-8")
    prompts = (
        build_chain_inheritance_prompts(shared_prefix=shared_prefix)
        if args.strategy == "chain"
        else build_shared_prefix_role_suffix_prompts(shared_prefix=shared_prefix)
    )
    payload = run_prefix_alignment_experiment(
        prompts=prompts,
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        metrics_url=args.metrics_url,
        max_tokens=args.max_tokens,
        stream=not args.no_stream,
    )
    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")


def _prompt(*, role: str, content: str) -> PrefixExperimentPrompt:
    return PrefixExperimentPrompt(
        role=role,
        content=content,
        content_hash=sha256_digest(content),
        content_bytes=len(content.encode("utf-8")),
    )


def _fetch_metrics(metrics_url: str) -> VllmPrefixCacheMetrics:
    try:
        return fetch_vllm_prefix_cache_metrics(metrics_url)
    except Exception:
        return VllmPrefixCacheMetrics()


def _run_prompt(
    *,
    client: OpenAI,
    prompt: PrefixExperimentPrompt,
    model: str,
    max_tokens: int,
    temperature: float,
    stream: bool,
) -> dict[str, Any]:
    request_started_ns = time.perf_counter_ns()
    if not stream:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt.content}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return {
            "role": prompt.role,
            "content_hash": prompt.content_hash,
            "content_bytes": prompt.content_bytes,
            "latency_ms": _elapsed_ms(request_started_ns),
            "ttft_ms": 0.0,
            "model": getattr(response, "model", model),
            "usage": _usage_payload(getattr(response, "usage", None)),
            "streamed_completion_bytes": 0,
        }

    ttft_ms = 0.0
    completion_chunks: list[str] = []
    stream_response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt.content}],
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    for chunk in stream_response:
        choice = chunk.choices[0] if chunk.choices else None
        delta = getattr(choice, "delta", None) if choice is not None else None
        content = getattr(delta, "content", None) or ""
        if content and ttft_ms == 0.0:
            ttft_ms = _elapsed_ms(request_started_ns)
        if content:
            completion_chunks.append(content)
    completion_text = "".join(completion_chunks)
    return {
        "role": prompt.role,
        "content_hash": prompt.content_hash,
        "content_bytes": prompt.content_bytes,
        "latency_ms": _elapsed_ms(request_started_ns),
        "ttft_ms": ttft_ms,
        "model": model,
        "usage": {},
        "streamed_completion_bytes": len(completion_text.encode("utf-8")),
    }


def _metrics_delta(before: VllmPrefixCacheMetrics, after: VllmPrefixCacheMetrics) -> dict[str, float]:
    queries_delta = max(after.queries_total - before.queries_total, 0.0)
    hits_delta = max(after.hits_total - before.hits_total, 0.0)
    return {
        "queries_total_delta": queries_delta,
        "hits_total_delta": hits_delta,
        "hit_rate_delta_window": hits_delta / queries_delta if queries_delta else 0.0,
    }


def _usage_payload(usage: object | None) -> dict[str, int]:
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }


def _elapsed_ms(start_ns: int) -> float:
    return (time.perf_counter_ns() - start_ns) / 1_000_000.0


if __name__ == "__main__":
    main()
