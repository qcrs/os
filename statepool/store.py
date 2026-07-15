from __future__ import annotations

import hashlib
import json
import mmap
import os
import platform
from dataclasses import dataclass
from multiprocessing import shared_memory
from pathlib import Path

import numpy as np

from protocol.messages import StateRef

MMAP_FILE_STORAGE = "MMAP_FILE"
PY_SHARED_MEMORY_STORAGE = "PY_SHARED_MEMORY"
MEMFD_STORAGE = "MEMFD"
CAS_BLOB_STORAGE = "CAS_BLOB"
DEFAULT_STATEPOOL_BACKEND = "mmap"
# "mmap" (FileBackedStatePool) is the only backend that persists state across
# process restarts and therefore the only one that supports cross-session
# exact_replay and validated_replay.  shared_memory and memfd are available
# for experimentation (SubprocessExecutorTransport + MemfdStatePool pairing)
# but should not be used as the default for benchmark runs.
DEFAULT_EMBED_STATE_BACKEND = "mmap"
CAS_REPLAY_RESTORABLE_KINDS = frozenset(
    {
        "CHANNEL_PATCH",
        "CHANNEL_SNAPSHOT",
        "FEATURE_BUNDLE",
        "RANKED_EVIDENCE_BUNDLE",
        "TOOL_CANDIDATE_SET",
        "REPLAY_ELIGIBILITY_BUNDLE",
        "EMBEDDING",
    }
)


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
    if candidate in {"memfd", MEMFD_STORAGE.lower()}:
        return MEMFD_STORAGE
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
    if candidate in {"memfd", MEMFD_STORAGE.lower()}:
        return MEMFD_STORAGE
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


def memfd_create_available() -> bool:
    fd = _memfd_create_safe("statebus_probe")
    if fd is None:
        return False
    os.close(fd)
    return True


def _memfd_create(name: str) -> int:
    if hasattr(os, "memfd_create"):
        flags = int(getattr(os, "MFD_CLOEXEC", 0x0001))
        return int(os.memfd_create(name, flags=flags))
    import ctypes

    syscall_number = 319 if platform.machine() == "x86_64" else 385
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    fd = int(libc.syscall(syscall_number, name.encode("utf-8"), 0x0001))
    if fd < 0:
        raise OSError(ctypes.get_errno(), "memfd_create failed")
    return fd


def _memfd_create_safe(name: str) -> int | None:
    try:
        return _memfd_create(name)
    except (AttributeError, OSError):
        return None


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
            length=len(payload),
            metadata=dict(metadata or {}),
            storage=MMAP_FILE_STORAGE,
            handle=str(path),
            blob_hash=checksum,
            checksum=checksum,
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
            length=len(payload),
            metadata=dict(metadata or {}),
            storage=PY_SHARED_MEMORY_STORAGE,
            handle=segment.name,
            blob_hash=checksum,
            checksum=checksum,
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


class MemfdStatePool:
    def __init__(
        self,
        root: str | Path,
        *,
        owned_fds: dict[str, int] | None = None,
        fallback_pool: SharedMemoryStatePool | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.meta_dir = self.root / "meta"
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.owned_fds = owned_fds if owned_fds is not None else {}
        self._handle_to_state_id: dict[str, str] = {}
        self._fallback_pool = fallback_pool or SharedMemoryStatePool(self.root / "shared_memory_fallback")

    def put_bytes(
        self,
        state_id: str,
        kind: str,
        payload: bytes,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        fd = _memfd_create_safe(f"statebus_{state_id[:32]}")
        if fd is None:
            return self._fallback_pool.put_bytes(state_id, kind, payload, metadata=metadata)
        os.ftruncate(fd, len(payload))
        _write_all(fd, payload)
        os.lseek(fd, 0, os.SEEK_SET)
        checksum = hashlib.sha256(payload).hexdigest()
        handle = f"memfd:{state_id}"
        ref = StateRef(
            state_id=state_id,
            kind=kind,
            length=len(payload),
            metadata=dict(metadata or {}),
            storage=MEMFD_STORAGE,
            handle=handle,
            blob_hash=checksum,
            checksum=checksum,
        )
        self.owned_fds[state_id] = fd
        self._handle_to_state_id[handle] = state_id
        _write_ref_meta(self.meta_dir / f"{state_id}.json", ref)
        return ref

    def get_bytes(self, ref: StateRef) -> bytes:
        fd = self._resolve_fd(ref)
        os.lseek(fd, 0, os.SEEK_SET)
        return os.read(fd, ref.length)

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

    def send_fd_via_socket(self, state_id: str, sock: object) -> None:
        import array
        import socket

        fd = self._resolve_fd_by_state_id(state_id)
        fds = array.array("i", [fd])
        sock.sendmsg(
            [state_id.encode("utf-8")],
            [(socket.SOL_SOCKET, socket.SCM_RIGHTS, fds.tobytes())],
        )

    def receive_fd_via_socket(self, sock: object, *, state_id: str | None = None) -> str:
        import array
        import socket

        message, ancillary, _flags, _addr = sock.recvmsg(256, socket.CMSG_SPACE(array.array("i", [0]).itemsize))
        resolved_state_id = state_id or message.decode("utf-8").strip()
        for level, message_type, data in ancillary:
            if level != socket.SOL_SOCKET or message_type != socket.SCM_RIGHTS:
                continue
            fds = array.array("i")
            usable = len(data) - (len(data) % fds.itemsize)
            fds.frombytes(data[:usable])
            if not fds:
                continue
            handle = f"memfd:{resolved_state_id}"
            self.owned_fds[resolved_state_id] = int(fds[0])
            self._handle_to_state_id[handle] = resolved_state_id
            return resolved_state_id
        raise RuntimeError("no memfd descriptor received via SCM_RIGHTS")

    def close_all(self) -> None:
        for state_id, fd in list(self.owned_fds.items()):
            try:
                os.close(fd)
            except OSError:
                pass
            self.owned_fds.pop(state_id, None)
        self._handle_to_state_id.clear()

    def _resolve_fd(self, ref: StateRef) -> int:
        state_id = ref.state_id
        return self._resolve_fd_by_state_id(state_id, handle=ref.handle)

    def _resolve_fd_by_state_id(self, state_id: str, *, handle: str | None = None) -> int:
        if state_id in self.owned_fds:
            return self.owned_fds[state_id]
        mapped_state_id = self._handle_to_state_id.get(handle or f"memfd:{state_id}")
        if mapped_state_id and mapped_state_id in self.owned_fds:
            return self.owned_fds[mapped_state_id]
        raise FileNotFoundError(
            f"memfd handle for state_id={state_id} is not available in this process;"
            " transfer it via SCM_RIGHTS or use shared_memory fallback"
        )


class StatePool:
    def __init__(
        self,
        root: str | Path,
        *,
        config: StatePoolConfig | None = None,
        owned_shared_handles: set[str] | None = None,
        owned_memfd_fds: dict[str, int] | None = None,
    ) -> None:
        self.root = Path(root)
        self.config = config or StatePoolConfig.from_env()
        self.file_pool = FileBackedStatePool(self.root / "mmap")
        self.shared_pool = SharedMemoryStatePool(
            self.root / "shared_memory",
            owned_handles=owned_shared_handles,
        )
        self.memfd_pool = MemfdStatePool(
            self.root / "memfd",
            owned_fds=owned_memfd_fds,
            fallback_pool=self.shared_pool,
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
        if backend == CAS_BLOB_STORAGE:
            return self.cas_blobs.put(state_id, kind, payload, metadata=metadata)
        if backend == MEMFD_STORAGE:
            return self.memfd_pool.put_bytes(state_id, kind, payload, metadata=metadata)
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

    def cas_summary(self) -> dict[str, object]:
        return self.cas_blobs.summary()

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

    def put_replay_restorable_bytes(
        self,
        state_id: str,
        kind: str,
        payload: bytes,
        metadata: dict[str, object] | None = None,
        *,
        storage: str | None = None,
    ) -> StateRef:
        if self.should_use_cas(kind=kind, metadata=metadata):
            return self.put_or_dedup_bytes(state_id, kind, payload, metadata=metadata)
        return self.put_bytes(
            state_id=state_id,
            kind=kind,
            payload=payload,
            metadata=metadata,
            storage=storage,
        )

    @staticmethod
    def should_use_cas(*, kind: str, metadata: dict[str, object] | None = None) -> bool:
        meta = dict(metadata or {})
        if kind in CAS_REPLAY_RESTORABLE_KINDS:
            return True
        if kind == "TOOL_ARTIFACT":
            return all(
                str(meta.get(key, "")).strip()
                for key in ("source_evidence", "tool_name", "route")
            )
        return False

    def link_cas_ref(
        self,
        *,
        state_id: str,
        source_ref: StateRef,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        return self.cas_blobs.link_ref(state_id=state_id, source_ref=source_ref, metadata=metadata)

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
        if ref.storage == CAS_BLOB_STORAGE:
            payload = self.cas_blobs.get_bytes_by_hash(ref.canonical_hash)
            if payload is not None:
                return payload
            handle_path = Path(ref.handle)
            if handle_path.exists():
                with handle_path.open("rb") as handle:
                    with mmap.mmap(handle.fileno(), length=0, access=mmap.ACCESS_READ) as mm:
                        return mm[:]
            raise FileNotFoundError(f"missing CAS blob: {ref.canonical_hash}")
        if ref.storage == MEMFD_STORAGE:
            return self.memfd_pool.get_bytes(ref)
        if ref.storage == PY_SHARED_MEMORY_STORAGE:
            return self.shared_pool.get_bytes(ref)
        return self.file_pool.get_bytes(ref)

    def get_text(self, ref: StateRef) -> str:
        if ref.storage == CAS_BLOB_STORAGE:
            return self.get_bytes(ref).decode("utf-8")
        if ref.storage == MEMFD_STORAGE:
            return self.memfd_pool.get_text(ref)
        if ref.storage == PY_SHARED_MEMORY_STORAGE:
            return self.shared_pool.get_text(ref)
        return self.file_pool.get_text(ref)

    def get_embedding(self, ref: StateRef) -> np.ndarray:
        if ref.storage == CAS_BLOB_STORAGE:
            dtype = str(ref.metadata.get("dtype", "float32"))
            vector_dim = int(ref.metadata["vector_dim"])
            vector = np.frombuffer(self.get_bytes(ref), dtype=dtype)
            if vector.shape != (vector_dim,):
                raise ValueError(
                    f"embedding state {ref.state_id} shape mismatch:"
                    f" expected {(vector_dim,)}, got {vector.shape}"
                )
            return np.asarray(vector, dtype="float32")
        if ref.storage == MEMFD_STORAGE:
            return self.memfd_pool.get_embedding(ref)
        if ref.storage == PY_SHARED_MEMORY_STORAGE:
            return self.shared_pool.get_embedding(ref)
        return self.file_pool.get_embedding(ref)

    def load_ref(self, state_id: str) -> StateRef:
        mmap_meta = self.file_pool.meta_dir / f"{state_id}.json"
        if mmap_meta.exists():
            return self.file_pool.load_ref(state_id)
        cas_meta = self.cas_blobs.ref_meta_path(state_id)
        if cas_meta.exists():
            return self.cas_blobs.load_ref(state_id)
        memfd_meta = self.memfd_pool.meta_dir / f"{state_id}.json"
        if memfd_meta.exists():
            return self.memfd_pool.load_ref(state_id)
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
        self.refs_dir = self.root / "refs"
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.refs_dir.mkdir(parents=True, exist_ok=True)
        self._refcount: dict[str, int] = {}
        self._logical_state_count = 0
        self._dedup_hits = 0
        self._dedup_bytes_saved = 0

    def _blob_path(self, blob_hash: str) -> Path:
        return self.blobs_dir / blob_hash[:2] / blob_hash[2:]

    def _blob_meta_path(self, blob_hash: str) -> Path:
        return self.meta_dir / f"{blob_hash}.json"

    def ref_meta_path(self, state_id: str) -> Path:
        return self.refs_dir / f"{state_id}.json"

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
            self._refcount[blob_hash] = self._load_refcount(blob_hash) + 1
            dedup_hit = False
        else:
            self._refcount[blob_hash] = self._load_refcount(blob_hash) + 1
            dedup_hit = True
            self._dedup_hits += 1
            self._dedup_bytes_saved += len(payload)
        self._logical_state_count += 1

        refcount = self._refcount[blob_hash]
        ref = StateRef(
            state_id=state_id,
            kind=kind,
            length=len(payload),
            metadata={
                **meta,
                "blob_hash": blob_hash,
                "blob_refcount": refcount,
                "dedup_hit": dedup_hit,
            },
            storage=CAS_BLOB_STORAGE,
            handle=str(blob_path),
            blob_hash=blob_hash,
            checksum=blob_hash,
            exact_replay_ready=True,
        )
        _write_ref_meta(self._blob_meta_path(blob_hash), ref)
        _write_ref_meta(self.ref_meta_path(state_id), ref)
        return ref

    def link_ref(
        self,
        *,
        state_id: str,
        source_ref: StateRef,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        blob_hash = source_ref.canonical_hash
        if not blob_hash:
            raise ValueError(f"source ref {source_ref.state_id} is missing a CAS blob hash")
        blob_path = self._blob_path(blob_hash)
        if not blob_path.exists():
            source_path = Path(source_ref.handle)
            if not source_path.exists():
                raise FileNotFoundError(f"missing CAS blob for link: {blob_hash}")
            blob_path.parent.mkdir(parents=True, exist_ok=True)
            with source_path.open("rb") as source_handle, blob_path.open("wb") as target_handle:
                target_handle.write(source_handle.read())
            _write_ref_meta(self._blob_meta_path(blob_hash), source_ref)
        self._refcount[blob_hash] = self._load_refcount(blob_hash) + 1
        self._logical_state_count += 1
        self._dedup_hits += 1
        self._dedup_bytes_saved += int(source_ref.length)
        meta = {
            **dict(source_ref.metadata),
            **dict(metadata or {}),
            "blob_hash": blob_hash,
            "blob_refcount": self._refcount[blob_hash],
            "dedup_hit": True,
            "cas_linked_from_state_id": source_ref.state_id,
        }
        ref = StateRef(
            state_id=state_id,
            kind=source_ref.kind,
            length=source_ref.length,
            metadata=meta,
            storage=CAS_BLOB_STORAGE,
            handle=str(blob_path),
            blob_hash=blob_hash,
            checksum=blob_hash,
            exact_replay_ready=True,
        )
        _write_ref_meta(self.ref_meta_path(state_id), ref)
        return ref

    def blob_refcount(self, blob_hash: str) -> int:
        return self._load_refcount(blob_hash)

    def load_ref(self, state_id: str) -> StateRef:
        return _read_ref_meta(self.ref_meta_path(state_id))

    def load_ref_by_hash(self, blob_hash: str) -> StateRef | None:
        meta_path = self._blob_meta_path(blob_hash)
        if not meta_path.exists():
            return None
        return _read_ref_meta(meta_path)

    def _load_refcount(self, blob_hash: str) -> int:
        in_memory = self._refcount.get(blob_hash)
        if in_memory is not None:
            return in_memory
        count = 0
        for path in self.refs_dir.glob("*.json"):
            try:
                ref = _read_ref_meta(path)
            except Exception:
                continue
            if ref.canonical_hash == blob_hash:
                count += 1
        self._refcount[blob_hash] = count
        return count

    def summary(self) -> dict[str, object]:
        shared_blobs = []
        for blob_hash in sorted(self._all_blob_hashes()):
            refcount = self.blob_refcount(blob_hash)
            if refcount <= 1:
                continue
            payload = self.get_bytes_by_hash(blob_hash) or b""
            shared_blobs.append(
                {
                    "blob_hash": blob_hash,
                    "refcount": refcount,
                    "bytes": len(payload),
                }
            )
        shared_blobs.sort(key=lambda item: (-int(item["refcount"]), -int(item["bytes"]), str(item["blob_hash"])))
        physical_blob_count = len(self._all_blob_hashes())
        logical_state_count = max(self._logical_state_count, sum(self._load_refcount(blob) for blob in self._all_blob_hashes()))
        return {
            "logical_state_count": logical_state_count,
            "physical_blob_count": physical_blob_count,
            "dedup_hit": self._dedup_hits > 0,
            "dedup_hit_count": self._dedup_hits,
            "dedup_bytes_saved": self._dedup_bytes_saved,
            "cas_hit_rate": (self._dedup_hits / logical_state_count) if logical_state_count else 0.0,
            "shared_blobs": shared_blobs[:10],
        }

    def _all_blob_hashes(self) -> list[str]:
        hashes: list[str] = []
        for path in self.meta_dir.glob("*.json"):
            hashes.append(path.stem)
        return hashes


def _write_ref_meta(path: Path, ref: StateRef) -> None:
    path.write_text(
        json.dumps(
            {
                "state_id": ref.state_id,
                "kind": ref.kind,
                "length": ref.length,
                "blob_hash": ref.canonical_hash,
                "metadata": ref.metadata,
                "storage": ref.storage,
                "handle": ref.handle,
                "checksum": ref.checksum,
                "channel": ref.channel,
                "compatibility": ref.compatibility,
                "fetch_uri": ref.fetch_uri,
                "local_only": ref.local_only,
                "exact_replay_ready": ref.exact_replay_ready,
                "created_at_ns": ref.created_at_ns,
            },
            ensure_ascii=True,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _read_ref_meta(path: Path) -> StateRef:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return StateRef(**payload)


def _write_all(fd: int, payload: bytes) -> None:
    if not payload:
        return
    view = memoryview(payload)
    total_written = 0
    while total_written < len(view):
        written = os.write(fd, view[total_written:])
        if written <= 0:
            raise OSError("failed to write memfd payload")
        total_written += written
