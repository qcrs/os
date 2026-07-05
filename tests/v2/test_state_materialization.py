from __future__ import annotations

import gc
from pathlib import Path

import pytest

from v2.contracts import StorageKind
from v2.runtime.smoke import run_smoke
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


def test_layered_state_store_finalizer_cleans_orphan_shared_memory(tmp_path: Path) -> None:
    from multiprocessing.shared_memory import SharedMemory

    store = LayeredStateStore(
        root=tmp_path / "state",
        policy=LayeredStoragePolicy(shared_memory_budget_bytes=4096),
    )
    handle = store.publish(ref_id="state-orphan", object_kind="EMBEDDING_STATE", payload=b"cleanup")
    probe = SharedMemory(name=handle.shared_memory_name)
    probe.close()

    del store
    gc.collect()

    with pytest.raises(FileNotFoundError):
        SharedMemory(name=handle.shared_memory_name)


def test_run_smoke_tears_down_state_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_teardown = LayeredStateStore.teardown
    calls: list[Path] = []

    def recording_teardown(self: LayeredStateStore) -> None:
        calls.append(self.root)
        original_teardown(self)

    monkeypatch.setattr(LayeredStateStore, "teardown", recording_teardown)

    run_smoke(
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        task_id="state-store-cleanup-smoke",
    )

    assert calls == [tmp_path / "runtime" / "state"]
