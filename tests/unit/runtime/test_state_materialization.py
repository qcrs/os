from __future__ import annotations

import gc
from pathlib import Path

import pytest

from statebus.contracts import StorageKind
from statebus.runtime.smoke import run_smoke
from statebus.state import LayeredStateStore, LayeredStoragePolicy


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


def test_layered_state_store_memfd_mode_round_trip(tmp_path: Path) -> None:
    store = LayeredStateStore(
        root=tmp_path / "state",
        policy=LayeredStoragePolicy.for_state_pool_mode("memfd"),
    )
    handle = store.publish(ref_id="state-memfd", object_kind="EMBEDDING_STATE", payload=b"memfd-payload")
    assert handle.storage_kind in {StorageKind.MEMFD, StorageKind.SHARED_MEMORY}
    assert store.load("state-memfd") == b"memfd-payload"
    if handle.storage_kind == StorageKind.MEMFD:
        assert store.backend_name == "memfd"
        assert store.memfd_transfer_count == 1
        assert store.memfd_bytes_transferred == len(b"memfd-payload")
    store.teardown()


def test_layered_state_store_explicit_mmap_mode_never_selects_memory_backend(tmp_path: Path) -> None:
    store = LayeredStateStore(
        root=tmp_path / "state",
        policy=LayeredStoragePolicy.for_state_pool_mode("mmap_file"),
    )
    handle = store.publish(ref_id="state-mmap", object_kind="DENSE_SEMANTIC_STATE", payload=b"mmap-payload")

    assert store.policy.state_pool_mode == "mmap"
    assert handle.storage_kind == StorageKind.MMAP_FILE
    assert handle.decision.fallback_used is False
    assert store.backend_name == StorageKind.MMAP_FILE.value
    assert store.load("state-mmap") == b"mmap-payload"
    store.teardown()


def test_layered_state_store_backend_name_survives_release(tmp_path: Path) -> None:
    store = LayeredStateStore(
        root=tmp_path / "state",
        policy=LayeredStoragePolicy.for_state_pool_mode("auto"),
    )
    store.publish(ref_id="state-auto", object_kind="EMBEDDING_STATE", payload=b"auto-payload")
    assert store.backend_name == StorageKind.SHARED_MEMORY.value
    store.release("state-auto")
    assert store.backend_name == StorageKind.SHARED_MEMORY.value


def test_layered_state_store_memfd_unavailable_reports_fallback_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("statebus.state.store._memfd_create_safe", lambda _name: None)
    store = LayeredStateStore(
        root=tmp_path / "state",
        policy=LayeredStoragePolicy.for_state_pool_mode("memfd"),
    )
    store.publish(ref_id="state-fallback", object_kind="EMBEDDING_STATE", payload=b"fallback")
    assert store.backend_name == StorageKind.SHARED_MEMORY.value
    assert store.memfd_transfer_count == 0
    store.release("state-fallback")
    assert store.backend_name == StorageKind.SHARED_MEMORY.value


def test_layered_state_store_memfd_fallback_honors_shared_memory_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("statebus.state.store._memfd_create_safe", lambda _name: None)
    policy = LayeredStoragePolicy.for_state_pool_mode("memfd")
    policy.shared_memory_budget_bytes = 4
    store = LayeredStateStore(root=tmp_path / "state", policy=policy)
    handle = store.publish(ref_id="state-large", object_kind="EMBEDDING_STATE", payload=b"large-payload")
    assert handle.storage_kind == StorageKind.MMAP_FILE
    assert handle.decision.fallback_used is True
    assert handle.decision.reason == "memfd_unavailable"
    assert store.backend_name == StorageKind.MMAP_FILE.value
    assert store.load("state-large") == b"large-payload"
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
