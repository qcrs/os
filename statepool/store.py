from __future__ import annotations

import hashlib
import json
import mmap
import os
from dataclasses import dataclass
from multiprocessing import shared_memory
from pathlib import Path

import numpy as np

from protocol.messages import StateRef

MMAP_FILE_STORAGE = "MMAP_FILE"
PY_SHARED_MEMORY_STORAGE = "PY_SHARED_MEMORY"
DEFAULT_STATEPOOL_BACKEND = "mmap"
DEFAULT_EMBED_STATE_BACKEND = "mmap"


@dataclass(frozen=True)
class StatePoolConfig:
    default_backend: str = MMAP_FILE_STORAGE
    embedding_backend: str = MMAP_FILE_STORAGE

    @classmethod
    def from_env(
        cls,
        *,
        default_backend: str | None = None,
        embedding_backend: str | None = None,
    ) -> StatePoolConfig:
        return cls(
            default_backend=resolve_statepool_backend(default_backend),
            embedding_backend=resolve_embedding_state_backend(embedding_backend),
        )


def resolve_statepool_backend(value: str | None = None) -> str:
    candidate = (value or os.getenv("STATEBUS_STATEPOOL_BACKEND") or DEFAULT_STATEPOOL_BACKEND).strip().lower()
    if candidate in {"mmap", "mmap_file", MMAP_FILE_STORAGE.lower()}:
        return MMAP_FILE_STORAGE
    if candidate in {"shared_memory", "py_shared_memory", PY_SHARED_MEMORY_STORAGE.lower()}:
        return PY_SHARED_MEMORY_STORAGE
    raise ValueError(f"unsupported statepool backend: {candidate}")


def resolve_embedding_state_backend(value: str | None = None) -> str:
    candidate = (
        value
        or os.getenv("STATEBUS_EMBED_STATE_BACKEND")
        or DEFAULT_EMBED_STATE_BACKEND
    ).strip().lower()
    if candidate in {"mmap", "mmap_file", MMAP_FILE_STORAGE.lower()}:
        return MMAP_FILE_STORAGE
    if candidate in {"shared_memory", "py_shared_memory", PY_SHARED_MEMORY_STORAGE.lower()}:
        return PY_SHARED_MEMORY_STORAGE
    raise ValueError(f"unsupported embedding state backend: {candidate}")


def cleanup_shared_memory_handles(handles: set[str]) -> None:
    for handle in sorted(handles):
        try:
            segment = shared_memory.SharedMemory(name=handle)
        except FileNotFoundError:
            continue
        try:
            segment.unlink()
        finally:
            segment.close()


class FileBackedStatePool:
    """First host-side StatePool implementation using file-backed mmap artifacts."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.meta_dir = self.root / "meta"
        self.data_dir = self.root / "data"
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def put_bytes(
        self,
        state_id: str,
        kind: str,
        payload: bytes,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        path = self.data_dir / f"{state_id}.bin"
        meta_path = self.meta_dir / f"{state_id}.json"
        with path.open("wb") as handle:
            handle.write(payload)
        checksum = hashlib.sha256(payload).hexdigest()
        ref = StateRef(
            state_id=state_id,
            kind=kind,
            storage=MMAP_FILE_STORAGE,
            handle=str(path),
            length=len(payload),
            checksum=checksum,
            metadata=dict(metadata or {}),
        )
        _write_ref_meta(meta_path, ref)
        return ref

    def get_bytes(self, ref: StateRef) -> bytes:
        with Path(ref.handle).open("rb") as handle:
            with mmap.mmap(handle.fileno(), length=0, access=mmap.ACCESS_READ) as mm:
                return mm[:]

    def get_text(self, ref: StateRef) -> str:
        return self.get_bytes(ref).decode("utf-8")

    def get_embedding(self, ref: StateRef) -> np.ndarray:
        dtype = str(ref.metadata.get("dtype", "float32"))
        vector_dim = int(ref.metadata["vector_dim"])
        vector = np.frombuffer(self.get_bytes(ref), dtype=dtype)
        if vector.shape != (vector_dim,):
            raise ValueError(
                f"embedding state {ref.state_id} shape mismatch:"
                f" expected {(vector_dim,)}, got {vector.shape}"
            )
        return np.asarray(vector, dtype="float32")

    def load_ref(self, state_id: str) -> StateRef:
        meta_path = self.meta_dir / f"{state_id}.json"
        return _read_ref_meta(meta_path)


class SharedMemoryStatePool:
    def __init__(self, root: str | Path, *, owned_handles: set[str] | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.meta_dir = self.root / "meta"
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.owned_handles = owned_handles if owned_handles is not None else set()

    def put_bytes(
        self,
        state_id: str,
        kind: str,
        payload: bytes,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        segment = shared_memory.SharedMemory(create=True, size=len(payload))
        try:
            segment.buf[: len(payload)] = payload
        finally:
            segment.close()
        checksum = hashlib.sha256(payload).hexdigest()
        ref = StateRef(
            state_id=state_id,
            kind=kind,
            storage=PY_SHARED_MEMORY_STORAGE,
            handle=segment.name,
            length=len(payload),
            checksum=checksum,
            metadata=dict(metadata or {}),
        )
        self.owned_handles.add(segment.name)
        _write_ref_meta(self.meta_dir / f"{state_id}.json", ref)
        return ref

    def get_bytes(self, ref: StateRef) -> bytes:
        segment = shared_memory.SharedMemory(name=ref.handle)
        try:
            return bytes(segment.buf[: ref.length])
        finally:
            segment.close()

    def get_text(self, ref: StateRef) -> str:
        return self.get_bytes(ref).decode("utf-8")

    def get_embedding(self, ref: StateRef) -> np.ndarray:
        dtype = str(ref.metadata.get("dtype", "float32"))
        vector_dim = int(ref.metadata["vector_dim"])
        vector = np.frombuffer(self.get_bytes(ref), dtype=dtype)
        if vector.shape != (vector_dim,):
            raise ValueError(
                f"embedding state {ref.state_id} shape mismatch:"
                f" expected {(vector_dim,)}, got {vector.shape}"
            )
        return np.asarray(vector, dtype="float32")

    def load_ref(self, state_id: str) -> StateRef:
        return _read_ref_meta(self.meta_dir / f"{state_id}.json")


class StatePool:
    def __init__(
        self,
        root: str | Path,
        *,
        config: StatePoolConfig | None = None,
        owned_shared_handles: set[str] | None = None,
    ) -> None:
        self.root = Path(root)
        self.config = config or StatePoolConfig.from_env()
        self.file_pool = FileBackedStatePool(self.root / "mmap")
        self.shared_pool = SharedMemoryStatePool(
            self.root / "shared_memory",
            owned_handles=owned_shared_handles,
        )
        self.cas_blobs = ContentAddressedBlobStore(self.root / "cas")

    def put_bytes(
        self,
        state_id: str,
        kind: str,
        payload: bytes,
        metadata: dict[str, object] | None = None,
        *,
        storage: str | None = None,
    ) -> StateRef:
        backend = storage or self.config.default_backend
        if backend == PY_SHARED_MEMORY_STORAGE:
            return self.shared_pool.put_bytes(state_id, kind, payload, metadata=metadata)
        return self.file_pool.put_bytes(state_id, kind, payload, metadata=metadata)

    def put_cas(
        self,
        state_id: str,
        kind: str,
        payload: bytes,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        """Content-addressed put: dedup via SHA-256, Git-style blob storage."""
        return self.cas_blobs.put(state_id, kind, payload, metadata=metadata)

    def get_by_hash(self, blob_hash: str) -> bytes | None:
        """Lookup blob by SHA-256 hash. Returns None if not found."""
        return self.cas_blobs.get_bytes_by_hash(blob_hash)

    def has_blob(self, blob_hash: str) -> bool:
        return self.cas_blobs.has_blob(blob_hash)

    def cas_refcount(self, blob_hash: str) -> int:
        return self.cas_blobs.blob_refcount(blob_hash)

    def put_or_dedup_bytes(
        self,
        state_id: str,
        kind: str,
        payload: bytes,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        """Content-addressed put with automatic dedup.

        Computes SHA-256 of payload. If an identical blob already exists,
        returns a ref to the existing blob (refcount +1). Otherwise stores
        a new blob under its content hash.
        """
        return self.cas_blobs.put(state_id, kind, payload, metadata=metadata)

    def put_text(
        self,
        state_id: str,
        kind: str,
        text: str,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        return self.put_bytes(
            state_id=state_id,
            kind=kind,
            payload=text.encode("utf-8"),
            metadata=metadata,
        )

    def put_embedding(
        self,
        *,
        state_id: str,
        payload: bytes,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        return self.put_bytes(
            state_id=state_id,
            kind="EMBEDDING",
            payload=payload,
            metadata=metadata,
            storage=self.config.embedding_backend,
        )

    def get_bytes(self, ref: StateRef) -> bytes:
        if ref.storage == PY_SHARED_MEMORY_STORAGE:
            return self.shared_pool.get_bytes(ref)
        return self.file_pool.get_bytes(ref)

    def get_text(self, ref: StateRef) -> str:
        if ref.storage == PY_SHARED_MEMORY_STORAGE:
            return self.shared_pool.get_text(ref)
        return self.file_pool.get_text(ref)

    def get_embedding(self, ref: StateRef) -> np.ndarray:
        if ref.storage == PY_SHARED_MEMORY_STORAGE:
            return self.shared_pool.get_embedding(ref)
        return self.file_pool.get_embedding(ref)

    def load_ref(self, state_id: str) -> StateRef:
        mmap_meta = self.file_pool.meta_dir / f"{state_id}.json"
        if mmap_meta.exists():
            return self.file_pool.load_ref(state_id)
        return self.shared_pool.load_ref(state_id)


class ContentAddressedBlobStore:
    """Git-style content-addressed blob storage.

    Every blob is stored at ``blobs/<hash[0:2]>/<hash[2:]>``.
    Identical content produces the same SHA-256 hash → automatic dedup.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.blobs_dir = self.root / "blobs"
        self.meta_dir = self.root / "meta"
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self._refcount: dict[str, int] = {}

    def _blob_path(self, blob_hash: str) -> Path:
        return self.blobs_dir / blob_hash[:2] / blob_hash[2:]

    def _blob_meta_path(self, blob_hash: str) -> Path:
        return self.meta_dir / f"{blob_hash}.json"

    def has_blob(self, blob_hash: str) -> bool:
        return self._blob_path(blob_hash).exists()

    def get_bytes_by_hash(self, blob_hash: str) -> bytes | None:
        path = self._blob_path(blob_hash)
        if not path.exists():
            return None
        with path.open("rb") as handle:
            with mmap.mmap(handle.fileno(), length=0, access=mmap.ACCESS_READ) as mm:
                return mm[:]

    def put(
        self,
        state_id: str,
        kind: str,
        payload: bytes,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        """Content-addressed put. Returns existing blob ref if content matches."""
        blob_hash = hashlib.sha256(payload).hexdigest()
        blob_path = self._blob_path(blob_hash)
        meta = dict(metadata or {})

        if not blob_path.exists():
            blob_path.parent.mkdir(parents=True, exist_ok=True)
            with blob_path.open("wb") as handle:
                handle.write(payload)
            self._refcount[blob_hash] = 1
        else:
            self._refcount[blob_hash] = self._refcount.get(blob_hash, 0) + 1

        ref = StateRef(
            state_id=state_id,
            kind=kind,
            storage="CAS_BLOB",
            handle=str(blob_path),
            length=len(payload),
            checksum=blob_hash,
            metadata=meta,
        )
        meta["blob_hash"] = blob_hash
        meta["blob_refcount"] = self._refcount.get(blob_hash, 1)
        _write_ref_meta(self._blob_meta_path(blob_hash), ref)
        return ref

    def blob_refcount(self, blob_hash: str) -> int:
        return self._refcount.get(blob_hash, 0)

    def load_ref_by_hash(self, blob_hash: str) -> StateRef | None:
        meta_path = self._blob_meta_path(blob_hash)
        if not meta_path.exists():
            return None
        return _read_ref_meta(meta_path)


def _write_ref_meta(path: Path, ref: StateRef) -> None:
    path.write_text(
        json.dumps(
            {
                "state_id": ref.state_id,
                "kind": ref.kind,
                "storage": ref.storage,
                "handle": ref.handle,
                "length": ref.length,
                "checksum": ref.checksum,
                "metadata": ref.metadata,
            },
            ensure_ascii=True,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _read_ref_meta(path: Path) -> StateRef:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return StateRef(**payload)
