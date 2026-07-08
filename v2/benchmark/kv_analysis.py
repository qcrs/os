from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from v2.benchmark.models import BenchmarkCaseReport


KV_ANALYSIS_SCHEMA_VERSION = "statebus.kv_reuse_analysis.v1"
KV_ANALYSIS_CLAIM_BOUNDARY = (
    "theoretical_prefix_reuse_analysis_only_actual_vllm_metrics_required_for_mechanism_claim"
)


def summarize_case_kv_reuse(cases: tuple[BenchmarkCaseReport, ...] | list[BenchmarkCaseReport]) -> dict[str, Any]:
    prefix_counts: Counter[str] = Counter()
    prefix_tokens_by_hash: dict[str, float] = {}
    by_replay_class: dict[str, dict[str, float]] = defaultdict(_empty_replay_summary)
    engine_local_saved_tokens = 0.0
    engine_local_query_count = 0.0
    engine_local_hit_count = 0.0

    for case in cases:
        prefix_payload = _case_prefix_payload(case)
        prefix_hash = str(prefix_payload.get("prefix_hash", "")).strip()
        prefix_tokens = float(
            prefix_payload.get(
                "estimated_prefix_tokens",
                case.metrics.get("neural_prefix_estimated_prefix_tokens", 0.0),
            )
            or 0.0
        )
        if prefix_hash:
            prefix_counts[prefix_hash] += 1
            prefix_tokens_by_hash.setdefault(prefix_hash, prefix_tokens)

        saved_tokens = float(case.metrics.get("neural_prefix_prefill_saved_tokens_estimate", 0.0))
        query_count = float(case.metrics.get("neural_prefix_cache_query_count_estimate", 0.0))
        hit_count = float(case.metrics.get("neural_prefix_cache_hit_count_estimate", 0.0))
        engine_local_saved_tokens += saved_tokens
        engine_local_query_count += query_count
        engine_local_hit_count += hit_count

        replay_bucket = by_replay_class[str(case.replay_class or "unknown")]
        replay_bucket["case_count"] += 1.0
        replay_bucket["engine_local_prefill_saved_tokens_estimate"] += saved_tokens
        replay_bucket["engine_local_prefix_cache_query_count_estimate"] += query_count
        replay_bucket["engine_local_prefix_cache_hit_count_estimate"] += hit_count
        replay_bucket["prefix_token_count_estimate"] += prefix_tokens

    corpus_reuse_count = sum(max(count - 1, 0) for count in prefix_counts.values())
    corpus_saved_tokens = sum(
        max(count - 1, 0) * prefix_tokens_by_hash.get(prefix_hash, 0.0)
        for prefix_hash, count in prefix_counts.items()
    )
    engine_local_hit_rate = engine_local_hit_count / engine_local_query_count if engine_local_query_count else 0.0
    metrics = {
        "kv_corpus_prefix_hash_unique_count": float(len(prefix_counts)),
        "kv_corpus_prefix_hash_reuse_count": float(corpus_reuse_count),
        "kv_corpus_level_prefill_saved_tokens_estimate": float(corpus_saved_tokens),
        "kv_engine_local_prefill_saved_tokens_estimate": float(engine_local_saved_tokens),
        "kv_engine_local_prefix_cache_query_count_estimate": float(engine_local_query_count),
        "kv_engine_local_prefix_cache_hit_count_estimate": float(engine_local_hit_count),
        "kv_engine_local_prefix_cache_hit_rate_estimate": float(engine_local_hit_rate),
    }
    return {
        "schema_version": KV_ANALYSIS_SCHEMA_VERSION,
        "claim_boundary": KV_ANALYSIS_CLAIM_BOUNDARY,
        "corpus_prefix_hash_unique_count": len(prefix_counts),
        "corpus_prefix_hash_reuse_count": corpus_reuse_count,
        "corpus_prefix_hash_counts": dict(sorted(prefix_counts.items())),
        "estimated_corpus_level_prefill_saved_tokens": corpus_saved_tokens,
        "estimated_engine_local_prefill_saved_tokens": engine_local_saved_tokens,
        "estimated_engine_local_prefix_cache_hit_rate": engine_local_hit_rate,
        "by_replay_class": {
            replay_class: _finalize_replay_summary(summary)
            for replay_class, summary in sorted(by_replay_class.items())
        },
        "metrics": metrics,
    }


def _case_prefix_payload(case: BenchmarkCaseReport) -> dict[str, Any]:
    payload = case.audit_summary.get("neural_prefix_reuse", {})
    return dict(payload) if isinstance(payload, dict) else {}


def _empty_replay_summary() -> dict[str, float]:
    return {
        "case_count": 0.0,
        "prefix_token_count_estimate": 0.0,
        "engine_local_prefill_saved_tokens_estimate": 0.0,
        "engine_local_prefix_cache_query_count_estimate": 0.0,
        "engine_local_prefix_cache_hit_count_estimate": 0.0,
    }


def _finalize_replay_summary(summary: dict[str, float]) -> dict[str, float]:
    query_count = summary["engine_local_prefix_cache_query_count_estimate"]
    hit_count = summary["engine_local_prefix_cache_hit_count_estimate"]
    return {
        **summary,
        "engine_local_prefix_cache_hit_rate_estimate": hit_count / query_count if query_count else 0.0,
    }
