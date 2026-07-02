from __future__ import annotations

from pathlib import Path

from v2.contracts import StorageKind
from v2.state import LayeredStateStore, LayeredStoragePolicy


def test_layered_state_store_prefers_shared_memory_under_budget(tmp_path: Path) -> None:
    store = LayeredStateStore(
        root=tmp_path / "state",
        policy=LayeredStoragePolicy(shared_memory_budget_bytes=4096),
    )
    handle = store.publish(ref_id="state-1", object_kind="EMBEDDING_STATE", payload=b"abc")
    assert handle.storage_kind == StorageKind.SHARED_MEMORY
    assert store.load("state-1") == b"abc"
    assert Path(handle.metadata_path).exists()
    store.release("state-1")


def test_layered_state_store_falls_back_to_mmap_when_budget_exceeded(tmp_path: Path) -> None:
    store = LayeredStateStore(
        root=tmp_path / "state",
        policy=LayeredStoragePolicy(shared_memory_budget_bytes=4),
    )
    store.publish(ref_id="state-1", object_kind="EMBEDDING_STATE", payload=b"1234")
    handle = store.publish(ref_id="state-2", object_kind="EMBEDDING_STATE", payload=b"5678")
    assert handle.storage_kind == StorageKind.MMAP_FILE
    assert handle.decision.fallback_used is True
    assert store.load("state-2") == b"5678"
    store.teardown()
