from __future__ import annotations

from dataclasses import dataclass, field
from mmap import ACCESS_READ, mmap
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path

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
    shared_memory_budget_bytes: int = 64 * 1024 * 1024
    kind_preferences: dict[str, tuple[StorageKind, ...]] = field(
        default_factory=lambda: {
            "EMBEDDING_STATE": (StorageKind.SHARED_MEMORY, StorageKind.MMAP_FILE),
            "DENSE_SEMANTIC_STATE": (StorageKind.SHARED_MEMORY, StorageKind.MMAP_FILE),
            "FEATURE_BUNDLE": (StorageKind.INLINE, StorageKind.MMAP_FILE),
            "MEMORY_MATCH_RESULT": (StorageKind.CAS_SIDECAR, StorageKind.MMAP_FILE),
            "MEMORY_COMMIT": (StorageKind.CAS_SIDECAR, StorageKind.MMAP_FILE),
            "HYDRATE_MANIFEST": (StorageKind.CAS_SIDECAR, StorageKind.MMAP_FILE),
            "CANONICAL_EVIDENCE_PACK": (StorageKind.CAS_SIDECAR, StorageKind.MMAP_FILE),
            "EXECUTION_ARTIFACT": (StorageKind.WORKSPACE_ROOT, StorageKind.CAS_SIDECAR),
        }
    )

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
    ) -> StorageDecision:
        preferences = self.kind_preferences.get(object_kind, (StorageKind.MMAP_FILE,))
        for candidate in preferences:
            if candidate != preferred:
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
    mmap_path: Path | None = None
    inline_payload: bytes = b""
    root_id: str = "state_root"

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
            "mmap_path": "" if self.mmap_path is None else str(self.mmap_path),
            "root_id": self.root_id,
        }


@dataclass
class LayeredStateStore:
    root: Path = Path("/tmp/statebus-v2-state")
    policy: LayeredStoragePolicy = field(default_factory=LayeredStoragePolicy)
    materializations: dict[str, MaterializedStateHandle] = field(default_factory=dict)
    shared_memory_bytes_used: int = 0
    _shared_segments: dict[str, SharedMemory] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.mmap_dir.mkdir(parents=True, exist_ok=True)

    @property
    def metadata_dir(self) -> Path:
        return self.root / "metadata"

    @property
    def mmap_dir(self) -> Path:
        return self.root / "mmap"

    def publish(self, *, ref_id: str, object_kind: str, payload: bytes) -> MaterializedStateHandle:
        decision = self.policy.decide(
            object_kind=object_kind,
            size_bytes=len(payload),
            shared_memory_bytes_used=self.shared_memory_bytes_used,
        )
        try:
            handle = self._materialize(ref_id=ref_id, object_kind=object_kind, payload=payload, decision=decision)
        except OSError:
            if decision.selected != StorageKind.SHARED_MEMORY:
                raise
            fallback = self.policy.fallback(
                object_kind=object_kind,
                preferred=decision.preferred,
                reason="shared_memory_unavailable",
            )
            handle = self._materialize(ref_id=ref_id, object_kind=object_kind, payload=payload, decision=fallback)
        self.materializations[ref_id] = handle
        return handle

    def load(self, ref_id: str) -> bytes:
        handle = self.materializations[ref_id]
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
        elif handle.storage_kind == StorageKind.MMAP_FILE and handle.mmap_path is not None:
            if handle.mmap_path.exists():
                handle.mmap_path.unlink()

    def teardown(self) -> None:
        for ref_id in tuple(self.materializations):
            self.release(ref_id)

    def count_by_storage(self, storage_kind: StorageKind) -> int:
        return sum(1 for handle in self.materializations.values() if handle.storage_kind == storage_kind)

    def _materialize(
        self,
        *,
        ref_id: str,
        object_kind: str,
        payload: bytes,
        decision: StorageDecision,
    ) -> MaterializedStateHandle:
        if decision.selected == StorageKind.SHARED_MEMORY:
            handle = self._materialize_shared_memory(
                ref_id=ref_id,
                object_kind=object_kind,
                payload=payload,
                decision=decision,
            )
        elif decision.selected == StorageKind.MMAP_FILE:
            handle = self._materialize_mmap_file(
                ref_id=ref_id,
                object_kind=object_kind,
                payload=payload,
                decision=decision,
            )
        else:
            handle = self._materialize_inline(
                ref_id=ref_id,
                object_kind=object_kind,
                payload=payload,
                decision=decision,
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
        )

    def _materialize_mmap_file(
        self,
        *,
        ref_id: str,
        object_kind: str,
        payload: bytes,
        decision: StorageDecision,
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
        )

    def _materialize_inline(
        self,
        *,
        ref_id: str,
        object_kind: str,
        payload: bytes,
        decision: StorageDecision,
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
        )

    def _write_metadata(self, handle: MaterializedStateHandle) -> None:
        handle.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        handle.metadata_path.write_text(stable_json_dumps(handle.metadata_payload()) + "\n", encoding="utf-8")
