from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from statebus.contracts import (
    MEMORY_CANDIDATE_POOL_SCHEMA_VERSION,
    MEMORY_COMMIT_SCHEMA_VERSION,
    MEMORY_MATCH_RESULT_SCHEMA_VERSION,
    MEMORY_RERANK_RESULT_SCHEMA_VERSION,
    MEMORY_REF_SCHEMA_VERSION,
    STRUCTURED_EMBEDDING_SCHEMA_VERSION,
    CanonicalTaskSpec,
    CompatibilityVerdict,
    RefKind,
    RefRegistryEntry,
    RefStatus,
    ReplayClass,
    StorageKind,
)
from statebus.utils import compact_json_payload, sha256_digest

_MATCH_METADATA_KEYS = (
    "code_template_version",
    "extractor_version",
    "output_contract_version",
    "replay_ready",
    "runtime_signature_hash",
    "runtime_signature_manifest_bundle_hash",
    "runtime_signature_manifest_bundle_relpath",
)


class MemoryType(StrEnum):
    EVIDENCE = "evidence"
    OUTCOME = "outcome"
    STRATEGY = "strategy"
    STRATEGY_CACHE = "strategy_cache"
    SEMANTIC_EVIDENCE = "semantic_evidence"
    NUMERIC_FACT = "numeric_fact"
    TEXT_CONTEXT = "text_context"
    ROUTE_HINT = "route_hint"
    EXECUTION_ARTIFACT = "execution_artifact"
    VALIDATED_REPLAY = "validated_replay"
    EXACT_REPLAY = "exact_replay"


class MemoryCommitStatus(StrEnum):
    CANDIDATE = "candidate"
    COMMITTED = "committed"
    INVALIDATED = "invalidated"


class MemoryValidationStatus(StrEnum):
    UNCHECKED = "unchecked"
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True)
class StructuredEmbedding:
    embedding_id: str
    vector: tuple[float, ...]
    dims: int
    source_text_hash: str
    encoding: str = "hashed-bow-v1"
    schema_version: str = STRUCTURED_EMBEDDING_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "embedding_id": self.embedding_id,
            "vector": list(self.vector),
            "dims": self.dims,
            "source_text_hash": self.source_text_hash,
            "encoding": self.encoding,
            "schema_version": self.schema_version,
        }

    @property
    def embedding_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class MemoryQuery:
    """The single memory-plane query issued by Runtime for one task.

    The query deliberately carries the three independent retrieval signals
    (text, tags, and an optional dense vector) together.  MemoryIndexStore
    fuses their *ranks*; callers must not combine the source score spaces.
    """

    query_task_id: str
    query_spec_hash: str
    query_text: str = ""
    tags: tuple[str, ...] = ()
    query_embedding: StructuredEmbedding | None = None
    limit: int = 3
    allowed_memory_types: tuple[str, ...] = ()
    allow_assist: bool = True
    allow_validated_replay: bool = False
    allow_exact_replay: bool = False
    compatibility_signature: str = ""
    output_contract_version: str = ""
    canonical_task_spec: CanonicalTaskSpec | None = None
    input_lineage_hashes: tuple[str, ...] = ()
    input_schema_digest: str = ""
    validator_digest: str = ""

    def canonical_payload(self) -> dict[str, object]:
        return {
            "query_task_id": self.query_task_id,
            "query_spec_hash": self.query_spec_hash,
            "query_text": self.query_text.strip(),
            "tags": sorted({str(tag).strip() for tag in self.tags if str(tag).strip()}),
            "query_embedding_ref": (
                "" if self.query_embedding is None else self.query_embedding.embedding_hash
            ),
            "limit": int(self.limit),
            "allowed_memory_types": sorted({str(value) for value in self.allowed_memory_types}),
            "allow_assist": bool(self.allow_assist),
            "allow_validated_replay": bool(self.allow_validated_replay),
            "allow_exact_replay": bool(self.allow_exact_replay),
            "compatibility_signature": self.compatibility_signature,
            "output_contract_version": self.output_contract_version,
            "canonical_task_spec": (
                None
                if self.canonical_task_spec is None
                else self.canonical_task_spec.canonical_payload()
            ),
            "input_lineage_hashes": sorted(set(self.input_lineage_hashes)),
            "input_schema_digest": self.input_schema_digest,
            "validator_digest": self.validator_digest,
        }

    @property
    def query_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


# The longer name is useful at protocol boundaries while retaining the short
# name used by the existing MemoryProxy code.
HybridMemoryQuery = MemoryQuery


@dataclass(frozen=True)
class MemoryCandidatePool:
    query_task_id: str
    query_spec_hash: str
    candidate_memory_ids: tuple[str, ...]
    candidate_types: tuple[str, ...]
    candidate_taxonomy: dict[str, int] = field(default_factory=dict)
    schema_version: str = MEMORY_CANDIDATE_POOL_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "query_task_id": self.query_task_id,
            "query_spec_hash": self.query_spec_hash,
            "candidate_memory_ids": list(self.candidate_memory_ids),
            "candidate_types": list(self.candidate_types),
            "candidate_taxonomy": dict(sorted(self.candidate_taxonomy.items())),
            "schema_version": self.schema_version,
        }

    @property
    def pool_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class MemoryRerankItem:
    memory_id: str
    rank: int
    score: float
    replay_class: ReplayClass
    selected: bool

    def canonical_payload(self) -> dict[str, object]:
        return {
            "memory_id": self.memory_id,
            "rank": self.rank,
            "score": self.score,
            "replay_class": self.replay_class.value,
            "selected": self.selected,
        }


@dataclass(frozen=True)
class MemoryRerankResult:
    query_task_id: str
    selected_memory_ids: tuple[str, ...]
    items: tuple[MemoryRerankItem, ...]
    selected_taxonomy: dict[str, int] = field(default_factory=dict)
    schema_version: str = MEMORY_RERANK_RESULT_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "query_task_id": self.query_task_id,
            "selected_memory_ids": list(self.selected_memory_ids),
            "items": [item.canonical_payload() for item in self.items],
            "selected_taxonomy": dict(sorted(self.selected_taxonomy.items())),
            "schema_version": self.schema_version,
        }

    @property
    def rerank_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class MemoryCompatibilityDecision:
    memory_id: str
    raw_rank: int
    verdict: CompatibilityVerdict
    replay_class: ReplayClass
    policy_approved: bool
    reasons: tuple[str, ...] = ()

    def canonical_payload(self) -> dict[str, object]:
        return {
            "memory_id": self.memory_id,
            "raw_rank": self.raw_rank,
            "verdict": self.verdict.value,
            "replay_class": self.replay_class.value,
            "policy_approved": self.policy_approved,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class MemoryConsumptionRecord:
    consumption_id: str
    query_hash: str
    memory_id: str
    consumer_role: str
    consumer_step_id: str
    input_ref_id: str
    replay_class: ReplayClass
    compatibility_verdict: CompatibilityVerdict
    input_payload_hash: str
    before_decision_surface_hash: str
    after_decision_surface_hash: str
    behavioral_effect: str
    downstream_ref_ids: tuple[str, ...] = ()
    skipped_generation_step_count: int = 0
    skipped_llm_call_count: int = 0
    recipe_recomputed: bool = False
    consumed_at_ns: int = 0
    schema_version: str = "statebus.memory_consumption_record.v1"

    def canonical_payload(self) -> dict[str, object]:
        return {
            "consumption_id": self.consumption_id,
            "query_hash": self.query_hash,
            "memory_id": self.memory_id,
            "consumer_role": self.consumer_role,
            "consumer_step_id": self.consumer_step_id,
            "input_ref_id": self.input_ref_id,
            "replay_class": self.replay_class.value,
            "compatibility_verdict": self.compatibility_verdict.value,
            "input_payload_hash": self.input_payload_hash,
            "before_decision_surface_hash": self.before_decision_surface_hash,
            "after_decision_surface_hash": self.after_decision_surface_hash,
            "behavioral_effect": self.behavioral_effect,
            "downstream_ref_ids": list(self.downstream_ref_ids),
            "skipped_generation_step_count": self.skipped_generation_step_count,
            "skipped_llm_call_count": self.skipped_llm_call_count,
            "recipe_recomputed": self.recipe_recomputed,
            "consumed_at_ns": self.consumed_at_ns,
            "schema_version": self.schema_version,
        }

    @property
    def record_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class MemoryRef:
    memory_id: str
    memory_type: MemoryType
    replay_class: ReplayClass
    score: float
    source_task_id: str
    summary: str
    canonical_task_spec_hash: str
    source_agent: str = ""
    created_at_ns: int = 0
    task_theme: str = ""
    tags: tuple[str, ...] = ()
    source_role_path: tuple[str, ...] = ()
    producer_run_id: str = ""
    artifact_ref_id: str = ""
    semantic_state_ref_id: str = ""
    embedding_ref_id: str = ""
    manifest_hash: str = ""
    commit_status: MemoryCommitStatus = MemoryCommitStatus.CANDIDATE
    validation_status: MemoryValidationStatus = MemoryValidationStatus.UNCHECKED
    answer_adopted: bool = False
    schema_version: str = MEMORY_REF_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def registry_entry(self) -> RefRegistryEntry:
        status = {
            MemoryCommitStatus.CANDIDATE: RefStatus.CANDIDATE,
            MemoryCommitStatus.COMMITTED: RefStatus.VERIFIED,
            MemoryCommitStatus.INVALIDATED: RefStatus.INVALIDATED,
        }[self.commit_status]
        return RefRegistryEntry(
            ref_id=self.memory_id,
            ref_kind=RefKind.MEMORY,
            storage_kind=StorageKind.CAS_SIDECAR,
            status=status,
            blob_hash=self.memory_hash,
            manifest_hash=self.manifest_hash,
            schema_version=self.schema_version,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "memory_id": self.memory_id,
            "memory_type": self.memory_type.value,
            "replay_class": self.replay_class.value,
            "score": self.score,
            "source_task_id": self.source_task_id,
            "source_agent": self.source_agent,
            "created_at_ns": self.created_at_ns,
            "task_theme": self.task_theme,
            "tags": list(self.tags),
            "source_role_path": list(self.source_role_path),
            "producer_run_id": self.producer_run_id,
            "summary": self.summary,
            "canonical_task_spec_hash": self.canonical_task_spec_hash,
            "artifact_ref_id": self.artifact_ref_id,
            "semantic_state_ref_id": self.semantic_state_ref_id,
            "embedding_ref_id": self.embedding_ref_id,
            "manifest_hash": self.manifest_hash,
            "commit_status": self.commit_status.value,
            "validation_status": self.validation_status.value,
            "answer_adopted": self.answer_adopted,
            "schema_version": self.schema_version,
            "metadata": dict(sorted(self.metadata.items())),
        }

    def match_payload(self) -> dict[str, object]:
        metadata = {
            key: self.metadata[key]
            for key in _MATCH_METADATA_KEYS
            if key in self.metadata
        }
        return compact_json_payload(
            {
                "memory_id": self.memory_id,
                "memory_type": self.memory_type.value,
                "source_task_id": self.source_task_id,
                "source_agent": self.source_agent,
                "task_theme": self.task_theme,
                "tags": list(self.tags),
                "summary": self.summary,
                "canonical_task_spec_hash": self.canonical_task_spec_hash,
                "artifact_ref_id": self.artifact_ref_id,
                "semantic_state_ref_id": self.semantic_state_ref_id,
                "manifest_hash": self.manifest_hash,
                "schema_version": self.schema_version,
                "metadata": metadata,
            }
        )

    @property
    def memory_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class MemoryCommit:
    memory_ref: MemoryRef
    canonical_task_spec: CanonicalTaskSpec
    required_outputs: tuple[str, ...]
    quality_floor_pass: bool
    created_from_artifact_hash: str
    schema_version: str = MEMORY_COMMIT_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "memory_ref": self.memory_ref.canonical_payload(),
            "canonical_task_spec": self.canonical_task_spec.canonical_payload(),
            "required_outputs": list(self.required_outputs),
            "quality_floor_pass": self.quality_floor_pass,
            "created_from_artifact_hash": self.created_from_artifact_hash,
            "schema_version": self.schema_version,
        }

    @property
    def commit_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class MemoryMatch:
    memory_ref: MemoryRef
    matched_on: str
    score: float
    replay_class: ReplayClass

    def canonical_payload(self) -> dict[str, object]:
        return {
            "memory_ref": self.memory_ref.match_payload(),
            "matched_on": self.matched_on,
            "score": self.score,
            "replay_class": self.replay_class.value,
        }


@dataclass(frozen=True)
class MemoryMatchResult:
    query_task_id: str
    query_spec_hash: str
    matches: tuple[MemoryMatch, ...]
    retrieval_decision: str
    candidate_pool: MemoryCandidatePool | None = None
    rerank_result: MemoryRerankResult | None = None
    candidate_pool_hash: str = ""
    rerank_result_hash: str = ""
    source_ranks: dict[str, tuple[str, ...]] = field(default_factory=dict)
    compatibility_decisions: tuple[MemoryCompatibilityDecision, ...] = ()
    schema_version: str = MEMORY_MATCH_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.candidate_pool_hash and self.candidate_pool is not None:
            object.__setattr__(self, "candidate_pool_hash", self.candidate_pool.pool_hash)
        if not self.rerank_result_hash and self.rerank_result is not None:
            object.__setattr__(self, "rerank_result_hash", self.rerank_result.rerank_hash)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "query_task_id": self.query_task_id,
            "query_spec_hash": self.query_spec_hash,
            "matches": [match.canonical_payload() for match in self.matches],
            "retrieval_decision": self.retrieval_decision,
            "candidate_pool": (
                None if self.candidate_pool is None else self.candidate_pool.canonical_payload()
            ),
            "rerank_result": (
                None if self.rerank_result is None else self.rerank_result.canonical_payload()
            ),
            "candidate_pool_hash": self.candidate_pool_hash,
            "rerank_result_hash": self.rerank_result_hash,
            "source_ranks": {
                str(source): list(ids)
                for source, ids in sorted(self.source_ranks.items())
            },
            "compatibility_decisions": [
                decision.canonical_payload()
                for decision in self.compatibility_decisions
            ],
            "schema_version": self.schema_version,
        }

    @property
    def result_hash(self) -> str:
        return sha256_digest(self.canonical_payload())
