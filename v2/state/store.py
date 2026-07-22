from __future__ import annotations

from dataclasses import dataclass, field
from mmap import ACCESS_READ, mmap
from multiprocessing.shared_memory import SharedMemory
import os
from pathlib import Path
import platform
import weakref

from v2.contracts import StorageKind
from v2.utils import sha256_digest, stable_json_dumps


@dataclass(frozen=True)
class StorageDecision:
    object_kind: str
    selected: StorageKind
    preferred: StorageKind
    fallback_used: bool
    reason: str


@dataclass
class LayeredStoragePolicy:
    state_pool_mode: str = "auto"
    shared_memory_budget_bytes: int = 64 * 1024 * 1024
    kind_preferences: dict[str, tuple[StorageKind, ...]] = field(
        default_factory=lambda: {
            "EMBEDDING_STATE": (StorageKind.SHARED_MEMORY, StorageKind.MMAP_FILE),
            "DENSE_SEMANTIC_STATE": (StorageKind.SHARED_MEMORY, StorageKind.MMAP_FILE),
            "LOGIT_STATE": (StorageKind.SHARED_MEMORY, StorageKind.MMAP_FILE),
            "FEATURE_BUNDLE": (StorageKind.INLINE, StorageKind.MMAP_FILE),
            "MEMORY_MATCH_RESULT": (StorageKind.CAS_SIDECAR, StorageKind.MMAP_FILE),
            "MEMORY_COMMIT": (StorageKind.CAS_SIDECAR, StorageKind.MMAP_FILE),
            "HYDRATE_MANIFEST": (StorageKind.CAS_SIDECAR, StorageKind.MMAP_FILE),
            "CANONICAL_EVIDENCE_PACK": (StorageKind.CAS_SIDECAR, StorageKind.MMAP_FILE),
            "EXECUTION_ARTIFACT": (StorageKind.WORKSPACE_ROOT, StorageKind.CAS_SIDECAR),
        }
    )

    @classmethod
    def for_state_pool_mode(cls, mode: str = "auto") -> "LayeredStoragePolicy":
        normalized = _normalize_state_pool_mode(mode)
        policy = cls(state_pool_mode=normalized)
        if normalized == "memfd":
            policy.kind_preferences.update(
                {
                    "EMBEDDING_STATE": (StorageKind.MEMFD, StorageKind.SHARED_MEMORY, StorageKind.MMAP_FILE),
                    # Dense semantic state is consumed through a registry
                    # resolver in another PID.  Keep it on a named backend;
                    # anonymous memfd transfer remains available for the
                    # legacy embedding/logit paths.
                    "DENSE_SEMANTIC_STATE": (StorageKind.SHARED_MEMORY, StorageKind.MMAP_FILE),
                    "LOGIT_STATE": (StorageKind.SHARED_MEMORY, StorageKind.MMAP_FILE),
                }
            )
        elif normalized == "shared_memory":
            policy.kind_preferences.update(
                {
                    "EMBEDDING_STATE": (StorageKind.SHARED_MEMORY, StorageKind.MMAP_FILE),
                    "DENSE_SEMANTIC_STATE": (StorageKind.SHARED_MEMORY, StorageKind.MMAP_FILE),
                    "LOGIT_STATE": (StorageKind.SHARED_MEMORY, StorageKind.MMAP_FILE),
                }
            )
        elif normalized == "mmap":
            # Explicit durable-file control for matched backend experiments.
            # Do not silently select an in-memory backend in this mode.
            policy.kind_preferences.update(
                {
                    "EMBEDDING_STATE": (StorageKind.MMAP_FILE,),
                    "DENSE_SEMANTIC_STATE": (StorageKind.MMAP_FILE,),
                    "LOGIT_STATE": (StorageKind.MMAP_FILE,),
                }
            )
        return policy

    def decide(
        self,
        *,
        object_kind: str,
        size_bytes: int,
        shared_memory_bytes_used: int = 0,
    ) -> StorageDecision:
        preferences = self.kind_preferences.get(object_kind, (StorageKind.MMAP_FILE,))
        preferred = preferences[0]
        if (
            preferred == StorageKind.SHARED_MEMORY
            and shared_memory_bytes_used + size_bytes > self.shared_memory_budget_bytes
            and len(preferences) > 1
        ):
            return StorageDecision(
                object_kind=object_kind,
                selected=preferences[1],
                preferred=preferred,
                fallback_used=True,
                reason="shared_memory_budget_exceeded",
            )
        return StorageDecision(
            object_kind=object_kind,
            selected=preferred,
            preferred=preferred,
            fallback_used=False,
            reason="preferred_storage_selected",
        )

    def fallback(
        self,
        *,
        object_kind: str,
        preferred: StorageKind,
        reason: str,
        size_bytes: int = 0,
        shared_memory_bytes_used: int = 0,
    ) -> StorageDecision:
        preferences = self.kind_preferences.get(object_kind, (StorageKind.MMAP_FILE,))
        for candidate in preferences:
            if candidate != preferred:
                if (
                    candidate == StorageKind.SHARED_MEMORY
                    and shared_memory_bytes_used + size_bytes > self.shared_memory_budget_bytes
                ):
                    continue
                return StorageDecision(
                    object_kind=object_kind,
                    selected=candidate,
                    preferred=preferred,
                    fallback_used=True,
                    reason=reason,
                )
        return StorageDecision(
            object_kind=object_kind,
            selected=preferred,
            preferred=preferred,
            fallback_used=False,
            reason=reason,
        )


@dataclass(frozen=True)
class MaterializedStateHandle:
    ref_id: str
    object_kind: str
    storage_kind: StorageKind
    size_bytes: int
    blob_hash: str
    decision: StorageDecision
    metadata_path: Path
    shared_memory_name: str = ""
    memfd_name: str = ""
    memfd_fd: int | None = field(default=None, compare=False, repr=False)
    mmap_path: Path | None = None
    inline_payload: bytes = b""
    root_id: str = "state_root"
    contract_metadata: dict[str, object] = field(default_factory=dict)

    def metadata_payload(self) -> dict[str, object]:
        return {
            "ref_id": self.ref_id,
            "object_kind": self.object_kind,
            "storage_kind": self.storage_kind.value,
            "size_bytes": self.size_bytes,
            "blob_hash": self.blob_hash,
            "decision": {
                "object_kind": self.decision.object_kind,
                "selected": self.decision.selected.value,
                "preferred": self.decision.preferred.value,
                "fallback_used": self.decision.fallback_used,
                "reason": self.decision.reason,
            },
            "shared_memory_name": self.shared_memory_name,
            "memfd_name": self.memfd_name,
            "memfd_descriptor_available": self.memfd_fd is not None,
            "mmap_path": "" if self.mmap_path is None else str(self.mmap_path),
            "root_id": self.root_id,
            "contract_metadata": dict(sorted(self.contract_metadata.items())),
        }


@dataclass
class LayeredStateStore:
    root: Path = Path("/tmp/statebus-v2-state")
    policy: LayeredStoragePolicy = field(default_factory=LayeredStoragePolicy)
    materializations: dict[str, MaterializedStateHandle] = field(default_factory=dict)
    shared_memory_bytes_used: int = 0
    memfd_transfer_count: int = 0
    memfd_bytes_transferred: int = 0
    storage_publish_counts: dict[StorageKind, int] = field(default_factory=dict)
    last_published_storage_kind: StorageKind | None = None
    _shared_segments: dict[str, SharedMemory] = field(default_factory=dict, init=False, repr=False)
    _memfd_fds: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _finalizer: weakref.finalize | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.mmap_dir.mkdir(parents=True, exist_ok=True)
        self._finalizer = weakref.finalize(
            self,
            _cleanup_orphan_state_resources,
            self._shared_segments,
            self._memfd_fds,
        )

    @property
    def metadata_dir(self) -> Path:
        return self.root / "metadata"

    @property
    def mmap_dir(self) -> Path:
        return self.root / "mmap"

    @property
    def backend_name(self) -> str:
        if self.last_published_storage_kind is not None:
            return self.last_published_storage_kind.value
        if self.storage_publish_counts.get(StorageKind.MEMFD, 0) > 0:
            return StorageKind.MEMFD.value
        if self.storage_publish_counts.get(StorageKind.SHARED_MEMORY, 0) > 0:
            return StorageKind.SHARED_MEMORY.value
        if self.storage_publish_counts.get(StorageKind.MMAP_FILE, 0) > 0:
            return StorageKind.MMAP_FILE.value
        return self.policy.state_pool_mode

    def publish(
        self,
        *,
        ref_id: str,
        object_kind: str,
        payload: bytes,
        contract_metadata: dict[str, object] | None = None,
    ) -> MaterializedStateHandle:
        decision = self.policy.decide(
            object_kind=object_kind,
            size_bytes=len(payload),
            shared_memory_bytes_used=self.shared_memory_bytes_used,
        )
        try:
            handle = self._materialize(
                ref_id=ref_id,
                object_kind=object_kind,
                payload=payload,
                decision=decision,
                contract_metadata=contract_metadata,
            )
        except OSError:
            if decision.selected not in {StorageKind.SHARED_MEMORY, StorageKind.MEMFD}:
                raise
            fallback = self.policy.fallback(
                object_kind=object_kind,
                preferred=decision.preferred,
                reason=f"{decision.selected.value}_unavailable",
                size_bytes=len(payload),
                shared_memory_bytes_used=self.shared_memory_bytes_used,
            )
            handle = self._materialize(
                ref_id=ref_id,
                object_kind=object_kind,
                payload=payload,
                decision=fallback,
                contract_metadata=contract_metadata,
            )
        self.materializations[ref_id] = handle
        self.storage_publish_counts[handle.storage_kind] = self.storage_publish_counts.get(handle.storage_kind, 0) + 1
        self.last_published_storage_kind = handle.storage_kind
        return handle

    def load(self, ref_id: str) -> bytes:
        handle = self.materializations[ref_id]
        if handle.storage_kind == StorageKind.MEMFD:
            fd = self._memfd_fds[ref_id]
            os.lseek(fd, 0, os.SEEK_SET)
            return os.read(fd, handle.size_bytes)
        if handle.storage_kind == StorageKind.SHARED_MEMORY:
            shared = self._shared_segments.get(ref_id)
            if shared is None:
                shared = SharedMemory(name=handle.shared_memory_name)
                try:
                    return bytes(shared.buf[: handle.size_bytes])
                finally:
                    shared.close()
            return bytes(shared.buf[: handle.size_bytes])
        if handle.storage_kind == StorageKind.MMAP_FILE and handle.mmap_path is not None:
            with handle.mmap_path.open("rb") as buffer_file:
                with mmap(buffer_file.fileno(), 0, access=ACCESS_READ) as mapped:
                    return mapped[: handle.size_bytes]
        return handle.inline_payload

    def get(self, ref_id: str) -> bytes:
        return self.load(ref_id)

    def release(self, ref_id: str) -> None:
        handle = self.materializations.pop(ref_id)
        if handle.storage_kind == StorageKind.SHARED_MEMORY:
            shared = self._shared_segments.pop(ref_id, None)
            if shared is None:
                shared = SharedMemory(name=handle.shared_memory_name)
            try:
                shared.close()
            finally:
                shared.unlink()
            self.shared_memory_bytes_used = max(0, self.shared_memory_bytes_used - handle.size_bytes)
        elif handle.storage_kind == StorageKind.MEMFD:
            fd = self._memfd_fds.pop(ref_id, None)
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        elif handle.storage_kind == StorageKind.MMAP_FILE and handle.mmap_path is not None:
            if handle.mmap_path.exists():
                handle.mmap_path.unlink()

    def teardown(self) -> None:
        for ref_id in tuple(self.materializations):
            self.release(ref_id)
        if self._finalizer is not None and self._finalizer.alive:
            self._finalizer()

    def count_by_storage(self, storage_kind: StorageKind) -> int:
        return sum(1 for handle in self.materializations.values() if handle.storage_kind == storage_kind)

    def _materialize(
        self,
        *,
        ref_id: str,
        object_kind: str,
        payload: bytes,
        decision: StorageDecision,
        contract_metadata: dict[str, object] | None = None,
    ) -> MaterializedStateHandle:
        if decision.selected == StorageKind.SHARED_MEMORY:
            handle = self._materialize_shared_memory(
                ref_id=ref_id,
                object_kind=object_kind,
                payload=payload,
                decision=decision,
                contract_metadata=contract_metadata,
            )
        elif decision.selected == StorageKind.MEMFD:
            handle = self._materialize_memfd(
                ref_id=ref_id,
                object_kind=object_kind,
                payload=payload,
                decision=decision,
                contract_metadata=contract_metadata,
            )
        elif decision.selected == StorageKind.MMAP_FILE:
            handle = self._materialize_mmap_file(
                ref_id=ref_id,
                object_kind=object_kind,
                payload=payload,
                decision=decision,
                contract_metadata=contract_metadata,
            )
        else:
            handle = self._materialize_inline(
                ref_id=ref_id,
                object_kind=object_kind,
                payload=payload,
                decision=decision,
                contract_metadata=contract_metadata,
            )
        self._write_metadata(handle)
        return handle

    def _materialize_shared_memory(
        self,
        *,
        ref_id: str,
        object_kind: str,
        payload: bytes,
        decision: StorageDecision,
        contract_metadata: dict[str, object] | None = None,
    ) -> MaterializedStateHandle:
        shared = SharedMemory(create=True, size=max(1, len(payload)))
        if payload:
            shared.buf[: len(payload)] = payload
        self._shared_segments[ref_id] = shared
        self.shared_memory_bytes_used += len(payload)
        return MaterializedStateHandle(
            ref_id=ref_id,
            object_kind=object_kind,
            storage_kind=StorageKind.SHARED_MEMORY,
            size_bytes=len(payload),
            blob_hash=sha256_digest(payload),
            decision=decision,
            metadata_path=self.metadata_dir / f"{ref_id}.json",
            shared_memory_name=shared.name,
            contract_metadata=dict(contract_metadata or {}),
        )

    def _materialize_memfd(
        self,
        *,
        ref_id: str,
        object_kind: str,
        payload: bytes,
        decision: StorageDecision,
        contract_metadata: dict[str, object] | None = None,
    ) -> MaterializedStateHandle:
        memfd_name = f"statebus_v2_{ref_id[:48]}"
        fd = _memfd_create_safe(memfd_name)
        if fd is None:
            raise OSError("memfd_create_unavailable")
        os.ftruncate(fd, max(1, len(payload)))
        _write_all(fd, payload)
        os.lseek(fd, 0, os.SEEK_SET)
        self._memfd_fds[ref_id] = fd
        self.memfd_transfer_count += 1
        self.memfd_bytes_transferred += len(payload)
        return MaterializedStateHandle(
            ref_id=ref_id,
            object_kind=object_kind,
            storage_kind=StorageKind.MEMFD,
            size_bytes=len(payload),
            blob_hash=sha256_digest(payload),
            decision=decision,
            metadata_path=self.metadata_dir / f"{ref_id}.json",
            memfd_name=memfd_name,
            memfd_fd=fd,
            contract_metadata=dict(contract_metadata or {}),
        )

    def _materialize_mmap_file(
        self,
        *,
        ref_id: str,
        object_kind: str,
        payload: bytes,
        decision: StorageDecision,
        contract_metadata: dict[str, object] | None = None,
    ) -> MaterializedStateHandle:
        path = self.mmap_dir / f"{ref_id}.bin"
        with path.open("w+b") as buffer_file:
            buffer_file.truncate(max(1, len(payload)))
            with mmap(buffer_file.fileno(), max(1, len(payload))) as mapped:
                if payload:
                    mapped[: len(payload)] = payload
                mapped.flush()
        return MaterializedStateHandle(
            ref_id=ref_id,
            object_kind=object_kind,
            storage_kind=StorageKind.MMAP_FILE,
            size_bytes=len(payload),
            blob_hash=sha256_digest(payload),
            decision=decision,
            metadata_path=self.metadata_dir / f"{ref_id}.json",
            mmap_path=path,
            contract_metadata=dict(contract_metadata or {}),
        )

    def _materialize_inline(
        self,
        *,
        ref_id: str,
        object_kind: str,
        payload: bytes,
        decision: StorageDecision,
        contract_metadata: dict[str, object] | None = None,
    ) -> MaterializedStateHandle:
        return MaterializedStateHandle(
            ref_id=ref_id,
            object_kind=object_kind,
            storage_kind=decision.selected,
            size_bytes=len(payload),
            blob_hash=sha256_digest(payload),
            decision=decision,
            metadata_path=self.metadata_dir / f"{ref_id}.json",
            inline_payload=payload,
            contract_metadata=dict(contract_metadata or {}),
        )

    def _write_metadata(self, handle: MaterializedStateHandle) -> None:
        handle.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        handle.metadata_path.write_text(stable_json_dumps(handle.metadata_payload()) + "\n", encoding="utf-8")


def _normalize_state_pool_mode(mode: str) -> str:
    normalized = mode.strip().lower().replace("-", "_")
    if normalized == "mmap_file":
        normalized = "mmap"
    if normalized not in {"auto", "mmap", "shared_memory", "memfd"}:
        raise ValueError(f"unsupported state pool mode: {mode}")
    return normalized


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


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    total = 0
    while total < len(payload):
        written = os.write(fd, view[total:])
        if written <= 0:
            raise OSError("memfd_write_failed")
        total += written


def _cleanup_orphan_state_resources(shared_segments: dict[str, SharedMemory], memfd_fds: dict[str, int]) -> None:
    for ref_id, shared in list(shared_segments.items()):
        try:
            shared.close()
        except FileNotFoundError:
            pass
        try:
            shared.unlink()
        except FileNotFoundError:
            pass
        shared_segments.pop(ref_id, None)
    for ref_id, fd in list(memfd_fds.items()):
        try:
            os.close(fd)
        except OSError:
            pass
        memfd_fds.pop(ref_id, None)
