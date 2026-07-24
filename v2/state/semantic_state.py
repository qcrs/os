from __future__ import annotations

from dataclasses import dataclass, replace
import json
from mmap import ACCESS_READ, mmap
from multiprocessing.shared_memory import SharedMemory
import os
from pathlib import Path
import time
from typing import Any

import numpy as np

from v2.contracts import StorageKind
from v2.memory import StructuredEmbedding
from v2.provenance import manifest_from_dict, manifest_to_dict
from v2.refs import HydrateManifest, SemanticStateRef
from v2.state.store import LayeredStateStore, MaterializedStateHandle
from v2.utils import sha256_digest, stable_json_dumps


DENSE_SEMANTIC_STATE_SCHEMA_VERSION = "statebus.dense_semantic_state.v1"


class SemanticStateValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DenseSemanticStateContract:
    state_id: str
    shape: tuple[int, int]
    encoder_id: str
    encoder_revision: str
    encoder_signature: str
    source_text_hashes: tuple[str, ...]
    hydrate_manifest_id: str
    hydrate_manifest_hash: str
    blob_hash: str
    size_bytes: int
    owner_session_id: str
    lease_expires_at_ns: int
    producer_pid: int
    storage_kind: str = ""
    dtype: str = "float32"
    byte_order: str = "little"
    row_layout: str = "query_then_candidates"
    normalized: bool = True
    schema_version: str = DENSE_SEMANTIC_STATE_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state_id": self.state_id,
            "state_kind": "DENSE_SEMANTIC_STATE",
            "storage_kind": self.storage_kind,
            "dtype": self.dtype,
            "byte_order": self.byte_order,
            "shape": list(self.shape),
            "row_layout": self.row_layout,
            "normalized": self.normalized,
            "encoder_id": self.encoder_id,
            "encoder_revision": self.encoder_revision,
            "encoder_signature": self.encoder_signature,
            "source_text_hashes": list(self.source_text_hashes),
            "hydrate_manifest_id": self.hydrate_manifest_id,
            "hydrate_manifest_hash": self.hydrate_manifest_hash,
            "blob_hash": self.blob_hash,
            "size_bytes": self.size_bytes,
            "owner_session_id": self.owner_session_id,
            "lease_expires_at_ns": self.lease_expires_at_ns,
            "producer_pid": self.producer_pid,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DenseSemanticStateContract":
        shape = payload.get("shape", ())
        if not isinstance(shape, (list, tuple)) or len(shape) != 2:
            raise SemanticStateValidationError("dense_state_shape_invalid")
        return cls(
            state_id=str(payload.get("state_id", "")),
            shape=(int(shape[0]), int(shape[1])),
            encoder_id=str(payload.get("encoder_id", "")),
            encoder_revision=str(payload.get("encoder_revision", "")),
            encoder_signature=str(payload.get("encoder_signature", "")),
            source_text_hashes=tuple(str(value) for value in payload.get("source_text_hashes", ())),
            hydrate_manifest_id=str(payload.get("hydrate_manifest_id", "")),
            hydrate_manifest_hash=str(payload.get("hydrate_manifest_hash", "")),
            blob_hash=str(payload.get("blob_hash", "")),
            size_bytes=int(payload.get("size_bytes", 0)),
            owner_session_id=str(payload.get("owner_session_id", "")),
            lease_expires_at_ns=int(payload.get("lease_expires_at_ns", 0)),
            producer_pid=int(payload.get("producer_pid", 0)),
            storage_kind=str(payload.get("storage_kind", "")),
            dtype=str(payload.get("dtype", "")),
            byte_order=str(payload.get("byte_order", "")),
            row_layout=str(payload.get("row_layout", "")),
            normalized=bool(payload.get("normalized", False)),
            schema_version=str(payload.get("schema_version", "")),
        )


@dataclass(frozen=True)
class DenseSemanticStatePublication:
    ref: SemanticStateRef
    handle: MaterializedStateHandle
    contract: DenseSemanticStateContract
    manifest_path: Path


@dataclass(frozen=True)
class DenseSemanticSelection:
    state_id: str
    selected_candidate_ids: tuple[str, ...]
    selected_scores: tuple[float, ...]
    selected_row_indices: tuple[int, ...]
    selected_evidence_bytes: int
    consumer_pid: int
    producer_pid: int
    encoder_signature: str


def encoder_signature_for(
    *,
    encoder_id: str,
    encoder_revision: str,
    dims: int,
    normalized: bool = True,
) -> str:
    return sha256_digest({
        "encoder_id": encoder_id,
        "encoder_revision": encoder_revision,
        "dims": dims,
        "normalized": normalized,
        "dtype": "float32",
    })


def encode_dense_semantic_matrix(
    query_embedding: StructuredEmbedding,
    candidate_embeddings: tuple[StructuredEmbedding, ...],
) -> bytes:
    if not candidate_embeddings:
        raise SemanticStateValidationError("dense_state_candidates_required")
    rows = (query_embedding, *candidate_embeddings)
    if query_embedding.dims <= 0 or any(item.dims != query_embedding.dims for item in rows):
        raise SemanticStateValidationError("dense_state_embedding_dims_mismatch")
    if any(item.encoding != query_embedding.encoding for item in rows):
        raise SemanticStateValidationError("dense_state_encoder_mismatch")
    matrix = np.asarray([item.vector for item in rows], dtype="<f4", order="C")
    if matrix.shape != (len(rows), query_embedding.dims):
        raise SemanticStateValidationError("dense_state_shape_mismatch")
    if not np.isfinite(matrix).all():
        raise SemanticStateValidationError("dense_state_non_finite")
    norms = np.linalg.norm(matrix, axis=1)
    if np.any(np.abs(norms - 1.0) > 1e-4):
        raise SemanticStateValidationError("dense_state_not_normalized")
    return matrix.tobytes(order="C")


def publish_dense_semantic_state(
    *,
    store: LayeredStateStore,
    state_id: str,
    query_embedding: StructuredEmbedding,
    candidate_embeddings: tuple[StructuredEmbedding, ...],
    hydrate_manifest: HydrateManifest,
    owner_session_id: str,
    encoder_revision: str = "",
    lease_ttl_ms: int = 60_000,
) -> DenseSemanticStatePublication:
    payload = encode_dense_semantic_matrix(query_embedding, candidate_embeddings)
    expected_rows = len(candidate_embeddings) + 1
    manifest_rows = tuple(entry.row_idx for entry in hydrate_manifest.entries)
    if manifest_rows != tuple(range(1, expected_rows)):
        raise SemanticStateValidationError("hydrate_manifest_rows_must_match_candidate_rows")
    if any(not entry.candidate_id for entry in hydrate_manifest.entries):
        raise SemanticStateValidationError("hydrate_manifest_candidate_id_required")
    signature = encoder_signature_for(
        encoder_id=query_embedding.encoding,
        encoder_revision=encoder_revision,
        dims=query_embedding.dims,
    )
    contract = DenseSemanticStateContract(
        state_id=state_id,
        shape=(expected_rows, query_embedding.dims),
        encoder_id=query_embedding.encoding,
        encoder_revision=encoder_revision,
        encoder_signature=signature,
        source_text_hashes=tuple(
            item.source_text_hash for item in (query_embedding, *candidate_embeddings)
        ),
        hydrate_manifest_id=hydrate_manifest.manifest_id,
        hydrate_manifest_hash=hydrate_manifest.manifest_hash,
        blob_hash=sha256_digest(payload),
        size_bytes=len(payload),
        owner_session_id=owner_session_id,
        lease_expires_at_ns=time.time_ns() + lease_ttl_ms * 1_000_000,
        producer_pid=os.getpid(),
    )
    manifest_path = persist_hydrate_manifest(store.root, hydrate_manifest)
    try:
        handle = store.publish(
            ref_id=state_id,
            object_kind="DENSE_SEMANTIC_STATE",
            payload=payload,
            contract_metadata={"dense_semantic_state": contract.canonical_payload()},
        )
    except Exception:
        manifest_path.unlink(missing_ok=True)
        raise
    if handle.blob_hash != contract.blob_hash or handle.size_bytes != contract.size_bytes:
        store.release(state_id)
        manifest_path.unlink(missing_ok=True)
        raise SemanticStateValidationError("dense_state_materialization_mismatch")
    contract = replace(contract, storage_kind=handle.storage_kind.value)
    ref = SemanticStateRef(
        state_id=state_id,
        state_kind="DENSE_SEMANTIC_STATE",
        storage_kind=handle.storage_kind,
        length=handle.size_bytes,
        blob_hash=handle.blob_hash,
        manifest_id=hydrate_manifest.manifest_id,
        source_doc_hashes=hydrate_manifest.source_doc_hashes,
        compatibility_hint=signature,
        metadata=contract.canonical_payload(),
    )
    return DenseSemanticStatePublication(
        ref=ref,
        handle=handle,
        contract=contract,
        manifest_path=manifest_path,
    )


def persist_hydrate_manifest(state_root: Path, manifest: HydrateManifest) -> Path:
    path = Path(state_root) / "manifests" / f"{manifest.manifest_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json_dumps(manifest_to_dict(manifest)) + "\n", encoding="utf-8")
    return path


def load_hydrate_manifest(state_root: Path, manifest_id: str) -> HydrateManifest:
    path = Path(state_root) / "manifests" / f"{manifest_id}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SemanticStateValidationError("hydrate_manifest_missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise SemanticStateValidationError("hydrate_manifest_corrupt") from exc
    manifest = manifest_from_dict(payload)
    if manifest.manifest_id != manifest_id:
        raise SemanticStateValidationError("hydrate_manifest_id_mismatch")
    return manifest


class ResolvedDenseSemanticState:
    def __init__(
        self,
        *,
        contract: DenseSemanticStateContract,
        matrix: np.ndarray,
        buffer_view=None,
        shared_memory: SharedMemory | None = None,
        mapped: mmap | None = None,
        mapped_file=None,
    ) -> None:
        self.contract = contract
        self._matrix: np.ndarray | None = matrix
        self._buffer_view = buffer_view
        self._shared_memory = shared_memory
        self._mapped = mapped
        self._mapped_file = mapped_file

    @property
    def matrix(self) -> np.ndarray:
        if self._matrix is None:
            raise SemanticStateValidationError("dense_state_view_closed")
        return self._matrix

    def close(self) -> None:
        self._matrix = None
        if self._buffer_view is not None:
            try:
                self._buffer_view.release()
            except (AttributeError, ValueError):
                pass
            self._buffer_view = None
        if self._mapped is not None:
            self._mapped.close()
            self._mapped = None
        if self._mapped_file is not None:
            self._mapped_file.close()
            self._mapped_file = None
        if self._shared_memory is not None:
            self._shared_memory.close()
            self._shared_memory = None

    def __enter__(self) -> "ResolvedDenseSemanticState":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def resolve_dense_semantic_state(
    *,
    state_root: Path,
    ref: SemanticStateRef,
    expected_encoder_signature: str = "",
    now_ns: int | None = None,
    unregister_shared_memory_tracker: bool = False,
) -> ResolvedDenseSemanticState:
    metadata_path = Path(state_root) / "metadata" / f"{ref.state_id}.json"
    try:
        sidecar = json.loads(metadata_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SemanticStateValidationError("dense_state_metadata_missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise SemanticStateValidationError("dense_state_metadata_corrupt") from exc
    contract_payload = dict(sidecar.get("contract_metadata", {})).get("dense_semantic_state")
    if not isinstance(contract_payload, dict):
        raise SemanticStateValidationError("dense_state_contract_missing")
    contract = DenseSemanticStateContract.from_payload(contract_payload)
    storage_kind = str(sidecar.get("storage_kind", ""))
    contract = replace(contract, storage_kind=storage_kind)
    _validate_contract(contract, ref, expected_encoder_signature, now_ns=now_ns)

    shared: SharedMemory | None = None
    mapped = None
    mapped_file = None
    buffer = None
    matrix = None
    try:
        if storage_kind == StorageKind.SHARED_MEMORY.value:
            name = str(sidecar.get("shared_memory_name", ""))
            if not name:
                raise SemanticStateValidationError("dense_state_shared_memory_name_missing")
            try:
                shared = SharedMemory(name=name)
            except FileNotFoundError as exc:
                raise SemanticStateValidationError("dense_state_payload_missing") from exc
            if unregister_shared_memory_tracker:
                from multiprocessing import resource_tracker

                resource_tracker.unregister(shared._name, "shared_memory")
            buffer = shared.buf[: contract.size_bytes]
        elif storage_kind == StorageKind.MMAP_FILE.value:
            candidate = Path(str(sidecar.get("mmap_path", "")))
            allowed_root = (Path(state_root) / "mmap").resolve()
            try:
                resolved = candidate.resolve(strict=True)
            except FileNotFoundError as exc:
                raise SemanticStateValidationError("dense_state_payload_missing") from exc
            if resolved.parent != allowed_root:
                raise SemanticStateValidationError("dense_state_mmap_path_outside_state_root")
            mapped_file = resolved.open("rb")
            mapped = mmap(mapped_file.fileno(), 0, access=ACCESS_READ)
            buffer = memoryview(mapped)[: contract.size_bytes]
        else:
            raise SemanticStateValidationError("dense_state_storage_not_cross_process_resolvable")
        payload = bytes(buffer)
        if len(payload) != contract.size_bytes or sha256_digest(payload) != contract.blob_hash:
            raise SemanticStateValidationError("dense_state_blob_hash_mismatch")
        matrix = np.ndarray(contract.shape, dtype="<f4", buffer=buffer, order="C")
        matrix.flags.writeable = False
        if not np.isfinite(matrix).all():
            raise SemanticStateValidationError("dense_state_non_finite")
        if contract.normalized:
            norms = np.linalg.norm(matrix, axis=1)
            if np.any(np.abs(norms - 1.0) > 1e-4):
                raise SemanticStateValidationError("dense_state_not_normalized")
        return ResolvedDenseSemanticState(
            contract=contract,
            matrix=matrix,
            buffer_view=buffer,
            shared_memory=shared,
            mapped=mapped,
            mapped_file=mapped_file,
        )
    except Exception:
        matrix = None
        if buffer is not None:
            try:
                buffer.release()
            except (AttributeError, ValueError):
                pass
            buffer = None
        if mapped is not None:
            mapped.close()
        if mapped_file is not None:
            mapped_file.close()
        if shared is not None:
            shared.close()
        raise


def select_dense_semantic_state(
    *,
    state_root: Path,
    ref: SemanticStateRef,
    manifest_id: str,
    top_k: int,
    evidence_budget_bytes: int = 0,
    expected_encoder_signature: str = "",
    unregister_shared_memory_tracker: bool = False,
) -> DenseSemanticSelection:
    if top_k <= 0:
        raise SemanticStateValidationError("semantic_top_k_must_be_positive")
    manifest = load_hydrate_manifest(state_root, manifest_id)
    if manifest.manifest_hash != str(ref.metadata.get("hydrate_manifest_hash", "")):
        raise SemanticStateValidationError("hydrate_manifest_hash_mismatch")
    with resolve_dense_semantic_state(
        state_root=state_root,
        ref=ref,
        expected_encoder_signature=expected_encoder_signature,
        unregister_shared_memory_tracker=unregister_shared_memory_tracker,
    ) as resolved:
        matrix = resolved.matrix
        if len(manifest.entries) != matrix.shape[0] - 1:
            raise SemanticStateValidationError("hydrate_manifest_matrix_row_mismatch")
        entries_by_row = {entry.row_idx: entry for entry in manifest.entries}
        if set(entries_by_row) != set(range(1, matrix.shape[0])):
            raise SemanticStateValidationError("hydrate_manifest_row_index_mismatch")
        scores = matrix[1:] @ matrix[0]
        ranked = sorted(
            (
                (float(scores[row_idx - 1]), row_idx, entries_by_row[row_idx])
                for row_idx in range(1, matrix.shape[0])
            ),
            key=lambda item: (-item[0], item[2].candidate_id),
        )
        selected: list[tuple[float, int, object]] = []
        used_bytes = 0
        for score, row_idx, entry in ranked:
            if len(selected) >= top_k:
                break
            protected = entry.bucket in {"hard_fact", "structured_evidence"}
            if evidence_budget_bytes > 0 and not protected and used_bytes + entry.byte_hint > evidence_budget_bytes:
                continue
            selected.append((score, row_idx, entry))
            used_bytes += max(entry.byte_hint, 0)
        if not selected:
            raise SemanticStateValidationError("semantic_selection_empty")
        return DenseSemanticSelection(
            state_id=ref.state_id,
            selected_candidate_ids=tuple(item[2].candidate_id for item in selected),
            selected_scores=tuple(round(item[0], 6) for item in selected),
            selected_row_indices=tuple(item[1] for item in selected),
            selected_evidence_bytes=used_bytes,
            consumer_pid=os.getpid(),
            producer_pid=resolved.contract.producer_pid,
            encoder_signature=resolved.contract.encoder_signature,
        )


def semantic_ref_from_sidecar(state_root: Path, state_id: str) -> SemanticStateRef:
    path = Path(state_root) / "metadata" / f"{state_id}.json"
    try:
        sidecar = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SemanticStateValidationError("dense_state_metadata_missing") from exc
    contract_payload = dict(sidecar.get("contract_metadata", {})).get("dense_semantic_state")
    if not isinstance(contract_payload, dict):
        raise SemanticStateValidationError("dense_state_contract_missing")
    contract = DenseSemanticStateContract.from_payload(contract_payload)
    storage_kind = StorageKind(str(sidecar.get("storage_kind", "")))
    return SemanticStateRef(
        state_id=state_id,
        state_kind="DENSE_SEMANTIC_STATE",
        storage_kind=storage_kind,
        length=contract.size_bytes,
        blob_hash=contract.blob_hash,
        manifest_id=contract.hydrate_manifest_id,
        compatibility_hint=contract.encoder_signature,
        metadata=replace(contract, storage_kind=storage_kind.value).canonical_payload(),
    )


def query_embedding_from_dense_state(
    *,
    state_root: Path,
    ref: SemanticStateRef,
    embedding_id: str,
    expected_encoder_signature: str = "",
) -> StructuredEmbedding:
    """Read row 0 for MemoryProxy without invoking the encoder again."""
    with resolve_dense_semantic_state(
        state_root=state_root,
        ref=ref,
        expected_encoder_signature=expected_encoder_signature,
    ) as resolved:
        vector = tuple(float(value) for value in resolved.matrix[0].tolist())
        contract = resolved.contract
    return StructuredEmbedding(
        embedding_id=embedding_id,
        vector=vector,
        dims=contract.shape[1],
        source_text_hash=contract.source_text_hashes[0],
        encoding=contract.encoder_id,
    )


def _validate_contract(
    contract: DenseSemanticStateContract,
    ref: SemanticStateRef,
    expected_encoder_signature: str,
    *,
    now_ns: int | None,
) -> None:
    if contract.schema_version != DENSE_SEMANTIC_STATE_SCHEMA_VERSION:
        raise SemanticStateValidationError("dense_state_schema_version_mismatch")
    if contract.state_id != ref.state_id or contract.state_id == "":
        raise SemanticStateValidationError("dense_state_id_mismatch")
    if contract.dtype != "float32" or contract.byte_order != "little":
        raise SemanticStateValidationError("dense_state_dtype_or_byte_order_mismatch")
    if contract.row_layout != "query_then_candidates" or not contract.normalized:
        raise SemanticStateValidationError("dense_state_layout_mismatch")
    rows, dims = contract.shape
    if rows < 2 or dims <= 0 or contract.size_bytes != rows * dims * 4:
        raise SemanticStateValidationError("dense_state_size_shape_mismatch")
    if contract.size_bytes != ref.length or contract.blob_hash != ref.blob_hash:
        raise SemanticStateValidationError("dense_state_ref_contract_mismatch")
    contract_payload = contract.canonical_payload()
    for key in (
        "schema_version",
        "state_kind",
        "dtype",
        "byte_order",
        "shape",
        "row_layout",
        "normalized",
        "encoder_id",
        "encoder_revision",
        "encoder_signature",
        "hydrate_manifest_id",
        "hydrate_manifest_hash",
        "blob_hash",
        "size_bytes",
        "owner_session_id",
        "lease_expires_at_ns",
        "producer_pid",
    ):
        if key in ref.metadata and ref.metadata[key] != contract_payload[key]:
            raise SemanticStateValidationError(f"dense_state_ref_contract_mismatch:{key}")
    if ref.manifest_id and ref.manifest_id != contract.hydrate_manifest_id:
        raise SemanticStateValidationError("dense_state_ref_contract_mismatch:manifest_id")
    if not contract.encoder_id or not contract.encoder_signature:
        raise SemanticStateValidationError("dense_state_encoder_contract_missing")
    if expected_encoder_signature and contract.encoder_signature != expected_encoder_signature:
        raise SemanticStateValidationError("dense_state_encoder_signature_mismatch")
    if ref.compatibility_hint and ref.compatibility_hint != contract.encoder_signature:
        raise SemanticStateValidationError("dense_state_ref_encoder_signature_mismatch")
    if contract.lease_expires_at_ns <= (time.time_ns() if now_ns is None else now_ns):
        raise SemanticStateValidationError("dense_state_expired")
