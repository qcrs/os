from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from v2.contracts import (
    CANONICAL_EVIDENCE_PACK_SCHEMA_VERSION,
    HYDRATE_MANIFEST_SCHEMA_VERSION,
    RefKind,
    RefRegistryEntry,
    RefStatus,
    StorageKind,
)
from v2.contracts.constants import LATENT_STATE_REF_SCHEMA_VERSION
from v2.contracts.neural import LatentLifecycleState
from v2.utils import sha256_digest


@dataclass(frozen=True)
class TextSpanLocator:
    locator_type: Literal["text_span"] = "text_span"
    source_doc_hash: str = ""
    canonical_text_id: str = ""
    start_char: int = 0
    end_char: int = 0
    extractor_version: str = ""


@dataclass(frozen=True)
class TableCellLocator:
    locator_type: Literal["table_cell"] = "table_cell"
    source_doc_hash: str = ""
    table_id: str = ""
    sheet_name: str = ""
    row_idx: int = 0
    col_idx: int = 0
    extractor_version: str = ""


@dataclass(frozen=True)
class FragmentLocator:
    locator_type: Literal["fragment"] = "fragment"
    source_doc_hash: str = ""
    fragment_id: str = ""
    extractor_version: str = ""
    page_no: int | None = None


SourceLocator = TextSpanLocator | TableCellLocator | FragmentLocator


@dataclass(frozen=True)
class SemanticStateRef:
    state_id: str
    state_kind: str
    storage_kind: StorageKind
    length: int
    blob_hash: str
    manifest_id: str = ""
    channel: str = "semantic_state"
    source_doc_hashes: tuple[str, ...] = ()
    compatibility_hint: str = ""
    exact_replay_ready: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def registry_entry(self) -> RefRegistryEntry:
        return RefRegistryEntry(
            ref_id=self.state_id,
            ref_kind=RefKind.SEMANTIC_STATE,
            storage_kind=self.storage_kind,
            status=RefStatus.ACTIVE,
            blob_hash=self.blob_hash,
            manifest_hash=self.manifest_id,
            schema_version=self.metadata.get("schema_version", ""),
        )


@dataclass(frozen=True)
class LogitStateRef:
    """Executor 输出层 logprob 向量的非文本状态 ref。
    传递 top-k token 的 log 概率 float32 向量（binary），
    是 LLM 输出分布的直接投影，不是文本字符串。
    """
    state_id: str
    producer_role: str
    consumer_role: str
    storage_kind: StorageKind
    length: int
    blob_hash: str
    top_k: int = 20
    entropy: float = 0.0
    confidence_proxy: float = 0.0
    channel: str = "logit_state"
    metadata: dict[str, Any] = field(default_factory=dict)

    def registry_entry(self) -> RefRegistryEntry:
        return RefRegistryEntry(
            ref_id=self.state_id,
            ref_kind=RefKind.LOGIT_STATE,
            storage_kind=self.storage_kind,
            status=RefStatus.ACTIVE,
            blob_hash=self.blob_hash,
            schema_version=self.metadata.get("schema_version", "logit_state.v1"),
        )


@dataclass(frozen=True)
class LatentStateRef:
    ref_id: str
    status: LatentLifecycleState
    backend_handle: str
    producer_role: str
    consumer_role: str
    source_task_id: str
    source_step_id: str
    source_evidence_pack_hash: str
    anchor_item_ids: tuple[str, ...]
    anchor_locator_digest: str
    model_id: str
    model_revision: str
    tokenizer_revision: str
    chat_template_digest: str
    hidden_size: int
    source_layer_index: int
    latent_step_count: int
    alignment_method: str
    alignment_config_digest: str
    position_contract_digest: str
    dtype: str
    shape: tuple[int, ...]
    tensor_bytes: int
    tensor_digest: str
    producer_pid: int
    engine_id: str
    created_at_ns: int
    expires_at_ns: int
    compatibility_digest: str
    storage_kind: StorageKind = StorageKind.ENGINE_LOCAL
    schema_version: str = LATENT_STATE_REF_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.storage_kind != StorageKind.ENGINE_LOCAL:
            raise ValueError("latent_state_requires_engine_local_storage")
        if len(self.shape) != 2:
            raise ValueError("latent_state_shape_must_be_rank_two")
        if self.shape != (self.latent_step_count, self.hidden_size):
            raise ValueError("latent_state_shape_contract_mismatch")
        if self.tensor_bytes != self.latent_step_count * self.hidden_size * 2:
            raise ValueError("latent_state_tensor_byte_count_mismatch")
        if not self.tensor_digest:
            raise ValueError("latent_state_tensor_digest_required")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "ref_kind": RefKind.LATENT_STATE.value,
            "status": self.status.value,
            "storage_kind": self.storage_kind.value,
            "backend_handle": self.backend_handle,
            "producer_role": self.producer_role,
            "consumer_role": self.consumer_role,
            "source_task_id": self.source_task_id,
            "source_step_id": self.source_step_id,
            "source_evidence_pack_hash": self.source_evidence_pack_hash,
            "anchor_item_ids": list(self.anchor_item_ids),
            "anchor_locator_digest": self.anchor_locator_digest,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "tokenizer_revision": self.tokenizer_revision,
            "chat_template_digest": self.chat_template_digest,
            "hidden_size": self.hidden_size,
            "source_layer_index": self.source_layer_index,
            "latent_step_count": self.latent_step_count,
            "alignment_method": self.alignment_method,
            "alignment_config_digest": self.alignment_config_digest,
            "position_contract_digest": self.position_contract_digest,
            "dtype": self.dtype,
            "shape": list(self.shape),
            "tensor_bytes": self.tensor_bytes,
            "tensor_digest": self.tensor_digest,
            "producer_pid": self.producer_pid,
            "engine_id": self.engine_id,
            "created_at_ns": self.created_at_ns,
            "expires_at_ns": self.expires_at_ns,
            "compatibility_digest": self.compatibility_digest,
            "schema_version": self.schema_version,
            "metadata": dict(sorted(self.metadata.items())),
        }

    @property
    def ref_hash(self) -> str:
        return sha256_digest(self.canonical_payload())

    def registry_entry(self) -> RefRegistryEntry:
        invalid_states = {
            LatentLifecycleState.REJECTED,
            LatentLifecycleState.INVALIDATED,
            LatentLifecycleState.EXPIRED,
            LatentLifecycleState.RELEASED,
        }
        return RefRegistryEntry(
            ref_id=self.ref_id,
            ref_kind=RefKind.LATENT_STATE,
            storage_kind=StorageKind.ENGINE_LOCAL,
            status=(
                RefStatus.INVALIDATED
                if self.status in invalid_states
                else RefStatus.ACTIVE
            ),
            blob_hash=self.tensor_digest,
            manifest_hash=self.ref_hash,
            schema_version=self.schema_version,
        )


@dataclass(frozen=True)
class ExecutionArtifactRef:
    artifact_id: str
    task_id: str
    step_id: str
    artifact_type: str
    root_id: str
    relpath: str
    blob_hash: str
    size_bytes: int
    produced_by: str
    verification_state: RefStatus = RefStatus.CANDIDATE
    replay_ready: bool = False
    workspace_relpath: str = ""
    manifest_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def registry_entry(self) -> RefRegistryEntry:
        return RefRegistryEntry(
            ref_id=self.artifact_id,
            ref_kind=RefKind.EXECUTION_ARTIFACT,
            storage_kind=StorageKind.WORKSPACE_ROOT,
            status=self.verification_state,
            blob_hash=self.blob_hash,
            manifest_hash=self.manifest_hash,
            root_id=self.root_id,
            relpath=self.relpath,
            workspace_relpath=self.workspace_relpath or self.relpath,
            schema_version=self.metadata.get("schema_version", ""),
        )


@dataclass(frozen=True)
class HydrateManifestEntry:
    row_idx: int
    locator: SourceLocator
    stable_key: str
    byte_hint: int = 0
    candidate_id: str = ""
    bucket: str = "semantic_context"
    importance_score: float = 0.0


@dataclass(frozen=True)
class HydrateManifest:
    manifest_id: str
    source_doc_hashes: tuple[str, ...]
    entries: tuple[HydrateManifestEntry, ...]
    canonicalizer_version: str
    extractor_version: str
    schema_version: str = HYDRATE_MANIFEST_SCHEMA_VERSION
    created_at_ns: int = 0

    @property
    def manifest_hash(self) -> str:
        return sha256_digest(
            {
                "manifest_id": self.manifest_id,
                "source_doc_hashes": list(self.source_doc_hashes),
                "entries": [
                    {
                        "row_idx": entry.row_idx,
                        "stable_key": entry.stable_key,
                        "byte_hint": entry.byte_hint,
                        "candidate_id": entry.candidate_id,
                        "bucket": entry.bucket,
                        "importance_score": entry.importance_score,
                        "locator": entry.locator,
                    }
                    for entry in self.entries
                ],
                "canonicalizer_version": self.canonicalizer_version,
                "extractor_version": self.extractor_version,
                "schema_version": self.schema_version,
                "created_at_ns": self.created_at_ns,
            }
        )


@dataclass(frozen=True)
class EvidenceItem:
    item_id: str
    bucket: str
    locator: SourceLocator | None
    rendered_text: str = ""
    source_name: str = ""
    rank: int = 0
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalEvidencePack:
    pack_id: str
    task_id: str
    source_doc_hashes: tuple[str, ...]
    hard_facts: tuple[EvidenceItem, ...] = ()
    structured_evidence: tuple[EvidenceItem, ...] = ()
    semantic_contexts: tuple[EvidenceItem, ...] = ()
    lexical_hints: tuple[EvidenceItem, ...] = ()
    conflicts: tuple[EvidenceItem, ...] = ()
    budget_meta: dict[str, Any] = field(default_factory=dict)
    pack_hash: str = ""
    schema_version: str = CANONICAL_EVIDENCE_PACK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.pack_hash:
            object.__setattr__(self, "pack_hash", sha256_digest(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "task_id": self.task_id,
            "source_doc_hashes": list(self.source_doc_hashes),
            "hard_facts": [self._item_payload(item) for item in self.hard_facts],
            "structured_evidence": [self._item_payload(item) for item in self.structured_evidence],
            "semantic_contexts": [self._item_payload(item) for item in self.semantic_contexts],
            "lexical_hints": [self._item_payload(item) for item in self.lexical_hints],
            "conflicts": [self._item_payload(item) for item in self.conflicts],
            "budget_meta": dict(sorted(self.budget_meta.items())),
            "schema_version": self.schema_version,
        }

    @staticmethod
    def _item_payload(item: EvidenceItem) -> dict[str, Any]:
        return {
            "item_id": item.item_id,
            "bucket": item.bucket,
            "locator": item.locator,
            "rendered_text": item.rendered_text,
            "source_name": item.source_name,
            "rank": item.rank,
            "score": item.score,
            "metadata": dict(sorted(item.metadata.items())),
        }
