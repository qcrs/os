from __future__ import annotations

from dataclasses import dataclass, field

from v2.contracts import StorageKind


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


@dataclass
class LayeredStateStore:
    policy: LayeredStoragePolicy = field(default_factory=LayeredStoragePolicy)
    blobs: dict[str, bytes] = field(default_factory=dict)
    decisions: dict[str, StorageDecision] = field(default_factory=dict)
    shared_memory_bytes_used: int = 0

    def publish(self, *, ref_id: str, object_kind: str, payload: bytes) -> StorageDecision:
        decision = self.policy.decide(
            object_kind=object_kind,
            size_bytes=len(payload),
            shared_memory_bytes_used=self.shared_memory_bytes_used,
        )
        self.blobs[ref_id] = payload
        self.decisions[ref_id] = decision
        if decision.selected == StorageKind.SHARED_MEMORY:
            self.shared_memory_bytes_used += len(payload)
        return decision

    def get(self, ref_id: str) -> bytes:
        return self.blobs[ref_id]

