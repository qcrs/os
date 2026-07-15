from __future__ import annotations

from dataclasses import dataclass
from math import ceil
import os


TEXT_BYTES_PER_TOKEN_ESTIMATE = 4
DEFAULT_AVAILABLE_KV_CACHE_BYTES = 8 * 1024**3
DEFAULT_KV_BYTES_PER_TOKEN = 256


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "")
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def estimate_tokens_from_bytes(byte_count: int) -> int:
    if byte_count <= 0:
        return 0
    return int(ceil(byte_count / TEXT_BYTES_PER_TOKEN_ESTIMATE))


def capacity_decision_label(capacity_ratio: float) -> str:
    if capacity_ratio >= 1.5:
        return "capacity_headroom"
    if capacity_ratio >= 1.0:
        return "capacity_near_target"
    if capacity_ratio >= 0.7:
        return "capacity_tight"
    return "capacity_critical"


@dataclass(frozen=True)
class DynamicPruningConfig:
    enabled: bool = False
    available_kv_cache_bytes: int = DEFAULT_AVAILABLE_KV_CACHE_BYTES
    kv_bytes_per_token: int = DEFAULT_KV_BYTES_PER_TOKEN
    base_threshold: float = 0.6
    capacity_buffer: float = 0.2
    min_keep_semantic_contexts: int = 1
    min_keep_lexical_hints: int = 0

    @classmethod
    def from_env(cls) -> "DynamicPruningConfig":
        return cls(
            enabled=_env_flag("STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED", False),
            available_kv_cache_bytes=_env_int(
                "STATEBUS_EVIDENCE_AVAILABLE_KV_CACHE_BYTES",
                DEFAULT_AVAILABLE_KV_CACHE_BYTES,
            ),
            kv_bytes_per_token=_env_int(
                "STATEBUS_EVIDENCE_KV_BYTES_PER_TOKEN",
                DEFAULT_KV_BYTES_PER_TOKEN,
            ),
            base_threshold=_env_float("STATEBUS_EVIDENCE_BASE_IMPORTANCE_THRESHOLD", 0.6),
            capacity_buffer=_env_float("STATEBUS_EVIDENCE_CAPACITY_BUFFER", 0.2),
            min_keep_semantic_contexts=_env_int(
                "STATEBUS_EVIDENCE_MIN_KEEP_SEMANTIC_CONTEXTS",
                1,
            ),
            min_keep_lexical_hints=_env_int(
                "STATEBUS_EVIDENCE_MIN_KEEP_LEXICAL_HINTS",
                0,
            ),
        )


@dataclass(frozen=True)
class PrunableEvidenceCandidate:
    candidate_id: str
    bucket: str
    importance_score: float
    rendered_text_bytes: int
    estimated_tokens: int = 0

    def normalized(self) -> "PrunableEvidenceCandidate":
        if self.estimated_tokens > 0:
            return self
        return PrunableEvidenceCandidate(
            candidate_id=self.candidate_id,
            bucket=self.bucket,
            importance_score=self.importance_score,
            rendered_text_bytes=self.rendered_text_bytes,
            estimated_tokens=estimate_tokens_from_bytes(self.rendered_text_bytes),
        )


@dataclass(frozen=True)
class DynamicPruningDecision:
    enabled: bool
    base_threshold: float
    dynamic_threshold: float
    available_kv_cache_bytes: int
    kv_bytes_per_token: int
    capacity_buffer: float
    target_sequence_tokens_estimate: int
    capacity_ratio: float
    budget_decision: str
    kept_candidate_ids: tuple[str, ...]
    dropped_candidate_ids: tuple[str, ...]


def compute_dynamic_pruning_threshold(
    *,
    available_kv_cache_bytes: int,
    target_sequence_len: int,
    kv_bytes_per_token: int,
    base_threshold: float = 0.6,
    capacity_buffer: float = 0.2,
) -> float:
    required_kv_bytes = max(target_sequence_len, 0) * max(kv_bytes_per_token, 1)
    safe_capacity = max(float(available_kv_cache_bytes) * max(0.0, 1.0 - capacity_buffer), 0.0)
    capacity_ratio = safe_capacity / required_kv_bytes if required_kv_bytes > 0 else 2.0

    if capacity_ratio >= 1.5:
        return base_threshold
    if capacity_ratio >= 1.0:
        return base_threshold + 0.1
    if capacity_ratio >= 0.7:
        return base_threshold + 0.2
    return 0.9


def apply_dynamic_pruning(
    candidates: list[PrunableEvidenceCandidate],
    *,
    available_kv_cache_bytes: int,
    kv_bytes_per_token: int,
    base_threshold: float = 0.6,
    capacity_buffer: float = 0.2,
    protected_candidate_ids: set[str] | None = None,
    min_keep_by_bucket: dict[str, int] | None = None,
) -> DynamicPruningDecision:
    normalized_candidates = [candidate.normalized() for candidate in candidates]
    target_sequence_tokens = sum(candidate.estimated_tokens for candidate in normalized_candidates)
    dynamic_threshold = compute_dynamic_pruning_threshold(
        available_kv_cache_bytes=available_kv_cache_bytes,
        target_sequence_len=target_sequence_tokens,
        kv_bytes_per_token=kv_bytes_per_token,
        base_threshold=base_threshold,
        capacity_buffer=capacity_buffer,
    )
    required_kv_bytes = max(target_sequence_tokens, 0) * max(kv_bytes_per_token, 1)
    safe_capacity = max(float(available_kv_cache_bytes) * max(0.0, 1.0 - capacity_buffer), 0.0)
    capacity_ratio = safe_capacity / required_kv_bytes if required_kv_bytes > 0 else 2.0
    protected_ids = set(protected_candidate_ids or ())
    bucket_min_keep = {bucket: max(count, 0) for bucket, count in (min_keep_by_bucket or {}).items()}

    ordered_candidates = sorted(
        normalized_candidates,
        key=lambda item: (-item.importance_score, item.rendered_text_bytes, item.candidate_id),
    )
    threshold_raised = dynamic_threshold > (base_threshold + 1e-9)
    kept: list[PrunableEvidenceCandidate] = []
    dropped: list[PrunableEvidenceCandidate] = []
    if not threshold_raised:
        kept = list(ordered_candidates)
    else:
        for candidate in ordered_candidates:
            if candidate.candidate_id in protected_ids or candidate.importance_score >= dynamic_threshold:
                kept.append(candidate)
            else:
                dropped.append(candidate)

    for bucket, minimum in sorted(bucket_min_keep.items()):
        if minimum <= 0:
            continue
        kept_in_bucket = [candidate for candidate in kept if candidate.bucket == bucket]
        if len(kept_in_bucket) >= minimum:
            continue
        bucket_dropped = sorted(
            [candidate for candidate in dropped if candidate.bucket == bucket],
            key=lambda item: (-item.importance_score, item.rendered_text_bytes, item.candidate_id),
        )
        needed = minimum - len(kept_in_bucket)
        for candidate in bucket_dropped[:needed]:
            dropped.remove(candidate)
            kept.append(candidate)

    kept_ids = tuple(sorted(candidate.candidate_id for candidate in kept))
    dropped_ids = tuple(sorted(candidate.candidate_id for candidate in dropped))
    return DynamicPruningDecision(
        enabled=True,
        base_threshold=base_threshold,
        dynamic_threshold=dynamic_threshold,
        available_kv_cache_bytes=available_kv_cache_bytes,
        kv_bytes_per_token=kv_bytes_per_token,
        capacity_buffer=capacity_buffer,
        target_sequence_tokens_estimate=target_sequence_tokens,
        capacity_ratio=capacity_ratio,
        budget_decision=capacity_decision_label(capacity_ratio),
        kept_candidate_ids=kept_ids,
        dropped_candidate_ids=dropped_ids,
    )
