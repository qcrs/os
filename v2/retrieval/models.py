from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from v2.contracts import (
    RETRIEVAL_CANDIDATE_POOL_SCHEMA_VERSION,
    RETRIEVAL_LOG_SCHEMA_VERSION,
    RETRIEVAL_PRUNING_PROFILE_SCHEMA_VERSION,
    RETRIEVAL_RERANK_RESULT_SCHEMA_VERSION,
)
from v2.memory import StructuredEmbedding
from v2.refs import CanonicalEvidencePack, HydrateManifest
from v2.utils import compact_json_payload, sha256_digest


EVIDENCE_PRUNING_HINT_SCHEMA_VERSION = "statebus.evidence_pruning_hint.v1"
EVIDENCE_PRUNING_CLAIM_BOUNDARY = (
    "input_level_evidence_pruning_only_no_model_internal_kv_tensor_pruning"
)
_PLANNER_SCOPE_TEXT_KEYS = (
    "text_context",
    "table_context",
    "artifact_context",
    "history_artifact_summaries",
)
_PLANNER_SCOPE_AUDIT_KEYS = (
    "required_tools",
    "candidate_keys",
    "supporting_doc_ids",
    "source_doc_hashes",
    "text_bytes",
    "text_item_count",
    "table_bytes",
    "table_item_count",
    "artifact_bytes",
    "artifact_item_count",
    "history_runtime_root_count",
    "required_lineage",
    "objective_source",
    "planner_semantic_plan_hash",
    "planner_fallback_semantic_plan_hash",
    "planner_effective_semantic_plan_hash",
)
_CANDIDATE_METADATA_AUDIT_KEYS = (
    "hint",
    "metric_name",
    "value",
    "source_doc_hash",
    "score",
    "lineage_ref",
)
_CANDIDATE_AUDIT_SAMPLE_LIMIT = 4
_RETRIEVAL_CANDIDATE_ID_SAMPLE_LIMIT = 6
_RETRIEVAL_SELECTED_AUDIT_SAMPLE_LIMIT = 2


def _planner_scope_text_payload_hash(planner_scope_payload: dict[str, Any]) -> str:
    text_payload = {
        key: planner_scope_payload[key]
        for key in _PLANNER_SCOPE_TEXT_KEYS
        if key in planner_scope_payload
    }
    return "" if not text_payload else sha256_digest(text_payload)


def planner_scope_audit_payload(planner_scope_payload: dict[str, Any]) -> dict[str, object]:
    payload = {
        key: planner_scope_payload[key]
        for key in _PLANNER_SCOPE_AUDIT_KEYS
        if key in planner_scope_payload
    }
    text_payload_hash = _planner_scope_text_payload_hash(planner_scope_payload)
    if text_payload_hash:
        payload["hydrated_context_payload_hash"] = text_payload_hash
    return compact_json_payload(payload)


def planner_scope_audit_hash(planner_scope_payload: dict[str, Any]) -> str:
    payload = planner_scope_audit_payload(planner_scope_payload)
    return sha256_digest(payload)


def _candidate_metadata_audit(metadata: dict[str, Any]) -> dict[str, object]:
    return {
        key: metadata[key]
        for key in _CANDIDATE_METADATA_AUDIT_KEYS
        if key in metadata
    }


class RetrieverKind(StrEnum):
    LEXICAL_METADATA = "lexical_metadata"
    SEMANTIC_CHUNK = "semantic_chunk"
    TABLE_STRUCTURE = "table_structure"


@dataclass(frozen=True)
class RetrievalCandidateRecord:
    candidate_id: str
    retriever_kind: RetrieverKind
    bucket: str
    rendered_text: str
    source_name: str
    rank: int
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "retriever_kind": self.retriever_kind.value,
            "bucket": self.bucket,
            "rendered_text": self.rendered_text,
            "source_name": self.source_name,
            "rank": self.rank,
            "score": self.score,
            "metadata": dict(self.metadata),
        }

    def audit_payload(self) -> dict[str, object]:
        rendered_bytes = len(self.rendered_text.encode("utf-8"))
        return compact_json_payload(
            {
            "candidate_id": self.candidate_id,
            "retriever_kind": self.retriever_kind.value,
            "bucket": self.bucket,
            "source_name": self.source_name,
            "rank": self.rank,
            "score": self.score,
            "rendered_text_hash": sha256_digest(self.rendered_text),
            "rendered_text_bytes": rendered_bytes,
            "metadata": _candidate_metadata_audit(self.metadata),
            "metadata_hash": sha256_digest(self.metadata),
            }
        )


@dataclass(frozen=True)
class RetrievalCandidatePool:
    task_id: str
    query_text: str
    candidates: tuple[RetrievalCandidateRecord, ...]
    planner_scope_payload: dict[str, Any] = field(default_factory=dict)
    schema_version: str = RETRIEVAL_CANDIDATE_POOL_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "query_text": self.query_text,
            "candidates": [candidate.canonical_payload() for candidate in self.candidates],
            "planner_scope_payload": dict(self.planner_scope_payload),
            "schema_version": self.schema_version,
        }

    def candidate_surface_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "query_text": self.query_text,
            "candidates": [candidate.canonical_payload() for candidate in self.candidates],
            "schema_version": self.schema_version,
        }

    @property
    def pool_relpath(self) -> str:
        return f"sidecars/retrieval_candidate_pools/{self.pool_hash}.json"

    @property
    def candidate_surface_relpath(self) -> str:
        return f"retrieval_candidate_payloads/{self.candidate_surface_hash}.json"

    @property
    def candidate_surface_hash(self) -> str:
        return sha256_digest(self.candidate_surface_payload())

    def audit_payload(self) -> dict[str, object]:
        bucket_counts: dict[str, int] = {}
        retriever_counts: dict[str, int] = {}
        top_candidate_ids_by_bucket: dict[str, list[str]] = {}
        candidate_audit_payloads: list[dict[str, object]] = []
        candidate_rendered_text_bytes_total = 0
        for candidate in self.candidates:
            bucket_counts[candidate.bucket] = bucket_counts.get(candidate.bucket, 0) + 1
            retriever_name = candidate.retriever_kind.value
            retriever_counts[retriever_name] = retriever_counts.get(retriever_name, 0) + 1
            bucket_top = top_candidate_ids_by_bucket.setdefault(candidate.bucket, [])
            if len(bucket_top) < 3:
                bucket_top.append(candidate.candidate_id)
            candidate_audit = candidate.audit_payload()
            candidate_audit_payloads.append(candidate_audit)
            candidate_rendered_text_bytes_total += int(candidate_audit.get("rendered_text_bytes", 0))
        candidate_audit_sample = candidate_audit_payloads[:_CANDIDATE_AUDIT_SAMPLE_LIMIT]
        return compact_json_payload(
            {
            "task_id": self.task_id,
            "query_text": self.query_text,
            "planner_scope_payload": planner_scope_audit_payload(self.planner_scope_payload),
            "planner_scope_payload_hash": planner_scope_audit_hash(self.planner_scope_payload),
            "candidate_count": len(self.candidates),
            "candidate_surface_hash": self.candidate_surface_hash,
            "candidate_surface_relpath": self.candidate_surface_relpath,
            "candidate_audit_hash": sha256_digest(candidate_audit_payloads),
            "candidate_audit_sample_count": len(candidate_audit_sample),
            "candidate_audit_sample": candidate_audit_sample,
            "candidate_rendered_text_bytes_total": candidate_rendered_text_bytes_total,
            "bucket_counts": dict(sorted(bucket_counts.items())),
            "retriever_counts": dict(sorted(retriever_counts.items())),
            "top_candidate_ids_by_bucket": {
                key: value for key, value in sorted(top_candidate_ids_by_bucket.items())
            },
            "schema_version": self.schema_version,
            }
        )

    @property
    def pool_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class RetrievalRerankItem:
    candidate_id: str
    rank: int
    fused_score: float
    selected: bool
    rationale: str = ""

    def canonical_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "rank": self.rank,
            "fused_score": self.fused_score,
            "selected": self.selected,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class RetrievalRerankResult:
    task_id: str
    selected_candidate_ids: tuple[str, ...]
    items: tuple[RetrievalRerankItem, ...]
    schema_version: str = RETRIEVAL_RERANK_RESULT_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "selected_candidate_ids": list(self.selected_candidate_ids),
            "items": [item.canonical_payload() for item in self.items],
            "schema_version": self.schema_version,
        }

    @property
    def rerank_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class RetrievalPruningBucketStat:
    bucket: str
    candidate_count: int
    selected_count: int
    selected_bytes: int
    dropped_count: int

    def canonical_payload(self) -> dict[str, object]:
        return {
            "bucket": self.bucket,
            "candidate_count": self.candidate_count,
            "selected_count": self.selected_count,
            "selected_bytes": self.selected_bytes,
            "dropped_count": self.dropped_count,
        }


@dataclass(frozen=True)
class EvidencePruningHint:
    candidate_id: str
    bucket: str
    importance_score: float
    rendered_text_bytes: int
    keep_in_budget: bool
    threshold: float
    estimated_tokens: int = 0
    estimated_kv_tokens_saved_if_dropped: int = 0
    available_kv_cache_bytes: int = 0
    kv_bytes_per_token: int = 0
    dynamic_threshold: float = 0.0
    capacity_ratio: float = 0.0
    budget_decision: str = ""
    pruning_class: str = "candidate"
    quality_guard: str = ""
    reason: str = ""
    claim_boundary: str = EVIDENCE_PRUNING_CLAIM_BOUNDARY
    schema_version: str = EVIDENCE_PRUNING_HINT_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "bucket": self.bucket,
            "importance_score": self.importance_score,
            "rendered_text_bytes": self.rendered_text_bytes,
            "keep_in_budget": self.keep_in_budget,
            "threshold": self.threshold,
            "estimated_tokens": self.estimated_tokens,
            "estimated_kv_tokens_saved_if_dropped": self.estimated_kv_tokens_saved_if_dropped,
            "available_kv_cache_bytes": self.available_kv_cache_bytes,
            "kv_bytes_per_token": self.kv_bytes_per_token,
            "dynamic_threshold": self.dynamic_threshold,
            "capacity_ratio": self.capacity_ratio,
            "budget_decision": self.budget_decision,
            "pruning_class": self.pruning_class,
            "quality_guard": self.quality_guard,
            "reason": self.reason,
            "claim_boundary": self.claim_boundary,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class RetrievalPruningProfile:
    task_id: str
    full_corpus_bytes: int
    selected_evidence_bytes: int
    raw_evidence_bytes_seen_by_llm: int
    pruning_gain_bytes: int
    selected_candidate_ids: tuple[str, ...]
    bucket_stats: tuple[RetrievalPruningBucketStat, ...]
    importance_threshold: float = 0.6
    base_importance_threshold: float = 0.6
    dynamic_pruning_enabled: bool = False
    pruning_hints: tuple[EvidencePruningHint, ...] = ()
    full_corpus_tokens_estimate: int = 0
    selected_evidence_tokens_estimate: int = 0
    dropped_candidate_bytes: int = 0
    dropped_candidate_tokens_estimate: int = 0
    estimated_kv_tokens_saved: int = 0
    pruning_gain_ratio: float = 0.0
    available_kv_cache_bytes: int = 0
    kv_bytes_per_token: int = 0
    target_sequence_tokens_estimate: int = 0
    capacity_ratio: float = 0.0
    budget_decision: str = ""
    policy_name: str = "statebus_input_level_evidence_pruning_v1"
    claim_boundary: str = EVIDENCE_PRUNING_CLAIM_BOUNDARY
    schema_version: str = RETRIEVAL_PRUNING_PROFILE_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "full_corpus_bytes": self.full_corpus_bytes,
            "selected_evidence_bytes": self.selected_evidence_bytes,
            "raw_evidence_bytes_seen_by_llm": self.raw_evidence_bytes_seen_by_llm,
            "pruning_gain_bytes": self.pruning_gain_bytes,
            "selected_candidate_ids": list(self.selected_candidate_ids),
            "bucket_stats": [bucket.canonical_payload() for bucket in self.bucket_stats],
            "importance_threshold": self.importance_threshold,
            "base_importance_threshold": self.base_importance_threshold,
            "dynamic_pruning_enabled": self.dynamic_pruning_enabled,
            "pruning_hints": [hint.canonical_payload() for hint in self.pruning_hints],
            "full_corpus_tokens_estimate": self.full_corpus_tokens_estimate,
            "selected_evidence_tokens_estimate": self.selected_evidence_tokens_estimate,
            "dropped_candidate_bytes": self.dropped_candidate_bytes,
            "dropped_candidate_tokens_estimate": self.dropped_candidate_tokens_estimate,
            "estimated_kv_tokens_saved": self.estimated_kv_tokens_saved,
            "pruning_gain_ratio": self.pruning_gain_ratio,
            "available_kv_cache_bytes": self.available_kv_cache_bytes,
            "kv_bytes_per_token": self.kv_bytes_per_token,
            "target_sequence_tokens_estimate": self.target_sequence_tokens_estimate,
            "capacity_ratio": self.capacity_ratio,
            "budget_decision": self.budget_decision,
            "policy_name": self.policy_name,
            "claim_boundary": self.claim_boundary,
            "schema_version": self.schema_version,
        }

    @property
    def profile_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class RetrievalLogEntry:
    retriever_kind: RetrieverKind
    candidate_count: int
    selected_count: int
    selected_ids: tuple[str, ...]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def canonical_payload(self) -> dict[str, object]:
        return compact_json_payload(
            {
            "retriever_kind": self.retriever_kind.value,
            "candidate_count": self.candidate_count,
            "selected_count": self.selected_count,
            "selected_ids": list(self.selected_ids),
            "diagnostics": dict(self.diagnostics),
            }
        )


@dataclass(frozen=True)
class RetrieverOutput:
    retriever_kind: RetrieverKind
    candidates: tuple[dict[str, object], ...]
    log_entry: RetrievalLogEntry
    query_embedding: StructuredEmbedding | None = None

    def log_payload(self) -> dict[str, object]:
        selected_id_set = set(self.log_entry.selected_ids)
        candidate_ids = [
            str(candidate.get("candidate_id", candidate.get("item_id", "")))
            for candidate in self.candidates
        ]
        selected_items = []
        for candidate in self.candidates:
            candidate_id = str(candidate.get("candidate_id", candidate.get("item_id", "")))
            if candidate_id in selected_id_set:
                selected_items.append(
                    {
                        "candidate_id": candidate_id,
                        "bucket": str(candidate.get("bucket", "")),
                        "rank": int(candidate.get("rank", 0)),
                        "rendered_text_hash": sha256_digest(str(candidate.get("rendered_text", ""))),
                        "rendered_text_bytes": len(str(candidate.get("rendered_text", "")).encode("utf-8")),
                        "metadata_hash": sha256_digest(candidate.get("metadata", {})),
                    }
                )
        candidate_id_sample = candidate_ids[:_RETRIEVAL_CANDIDATE_ID_SAMPLE_LIMIT]
        selected_candidate_audit_sample = selected_items[:_RETRIEVAL_SELECTED_AUDIT_SAMPLE_LIMIT]
        return compact_json_payload(
            {
                "retriever_kind": self.retriever_kind.value,
                "candidate_count": len(self.candidates),
                "selected_count": len(self.log_entry.selected_ids),
                "diagnostics": dict(self.log_entry.diagnostics),
                "candidate_ids_hash": sha256_digest(candidate_ids),
                "candidate_id_sample_count": len(candidate_id_sample),
                "candidate_id_sample": candidate_id_sample,
                "selected_ids_hash": sha256_digest(self.log_entry.selected_ids),
                "selected_candidate_audit_hash": sha256_digest(selected_items),
                "selected_candidate_audit_sample_count": len(selected_candidate_audit_sample),
                "selected_candidate_audit_sample": selected_candidate_audit_sample,
                "query_embedding_hash": (
                    "" if self.query_embedding is None else self.query_embedding.embedding_hash
                ),
            }
        )


@dataclass(frozen=True)
class RetrievalBundle:
    task_id: str
    query_text: str
    outputs: tuple[RetrieverOutput, ...]
    candidate_pool: RetrievalCandidatePool
    rerank_result: RetrievalRerankResult
    pruning_profile: RetrievalPruningProfile
    evidence_pack: CanonicalEvidencePack
    hydrate_manifest: HydrateManifest
    query_embedding: StructuredEmbedding
    selected_doc_hashes: tuple[str, ...]
    full_corpus_bytes: int
    selected_evidence_bytes: int
    planner_scope_payload: dict[str, Any] = field(default_factory=dict)
    consumed_objectives: dict[str, dict[str, Any]] = field(default_factory=dict)
    consumed_objective_hashes: dict[str, str] = field(default_factory=dict)
    memory_query_embedding: StructuredEmbedding | None = None
    schema_version: str = RETRIEVAL_LOG_SCHEMA_VERSION

    def log_payload(self) -> dict[str, object]:
        return compact_json_payload(
            {
            "task_id": self.task_id,
            "query_text": self.query_text,
            "planner_scope_payload_hash": planner_scope_audit_hash(self.planner_scope_payload),
            "consumed_objectives": dict(sorted(self.consumed_objectives.items())),
            "consumed_objective_hashes": dict(sorted(self.consumed_objective_hashes.items())),
            "selected_doc_hashes": list(self.selected_doc_hashes),
            "full_corpus_bytes": self.full_corpus_bytes,
            "selected_evidence_bytes": self.selected_evidence_bytes,
            "candidate_pool_hash": self.candidate_pool.pool_hash,
            "candidate_pool_relpath": self.candidate_pool.pool_relpath,
            "candidate_surface_hash": self.candidate_pool.candidate_surface_hash,
            "rerank_result_hash": self.rerank_result.rerank_hash,
            "pruning_profile_hash": self.pruning_profile.profile_hash,
            "outputs": [output.log_payload() for output in self.outputs],
            "evidence_pack_hash": self.evidence_pack.pack_hash,
            "hydrate_manifest_hash": self.hydrate_manifest.manifest_hash,
            "query_embedding_hash": self.query_embedding.embedding_hash,
            "memory_query_embedding_hash": (
                "" if self.memory_query_embedding is None else self.memory_query_embedding.embedding_hash
            ),
            "schema_version": self.schema_version,
            }
        )

    @property
    def log_hash(self) -> str:
        return sha256_digest(self.log_payload())
