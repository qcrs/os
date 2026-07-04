from __future__ import annotations

import os
import socket
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from statepool.store import (
    MEMFD_STORAGE,
    PY_SHARED_MEMORY_STORAGE,
    MemfdStatePool,
    StatePool,
    StatePoolConfig,
    cleanup_shared_memory_handles,
    memfd_create_available,
    resolve_embedding_state_backend,
    resolve_statepool_backend,
)


def _cleanup_pool(pool: StatePool) -> None:
    pool.memfd_pool.close_all()
    cleanup_shared_memory_handles(set(pool.shared_pool.owned_handles))


def test_backend_resolvers_accept_memfd() -> None:
    assert resolve_statepool_backend("memfd") == MEMFD_STORAGE
    assert resolve_embedding_state_backend("memfd") == MEMFD_STORAGE


def test_memfd_statepool_round_trip_or_shared_memory_fallback(tmp_path: Path) -> None:
    pool = MemfdStatePool(tmp_path / "memfd")
    try:
        ref = pool.put_bytes(
            "artifact-1",
            "TOOL_ARTIFACT",
            b"startup profile payload",
            metadata={"tool_name": "boot_timing_probe"},
        )
        loaded = pool.load_ref("artifact-1")
        assert loaded.storage == ref.storage
        assert pool.get_bytes(loaded) == b"startup profile payload"
        assert loaded.storage in {MEMFD_STORAGE, PY_SHARED_MEMORY_STORAGE}
    finally:
        pool.close_all()
        cleanup_shared_memory_handles(set(pool._fallback_pool.owned_handles))


def test_statepool_memfd_embedding_backend_round_trip(tmp_path: Path) -> None:
    pool = StatePool(
        tmp_path / "state",
        config=StatePoolConfig(
            default_backend=MEMFD_STORAGE,
            embedding_backend=MEMFD_STORAGE,
        ),
    )
    try:
        text_ref = pool.put_text("summary-1", "TOOL_ARTIFACT", "diagnosis summary")
        assert text_ref.storage in {MEMFD_STORAGE, PY_SHARED_MEMORY_STORAGE}
        assert pool.get_text(pool.load_ref("summary-1")) == "diagnosis summary"

        vector = np.asarray([0.0, 1.0, 2.5, 4.0], dtype=np.float32)
        embedding_ref = pool.put_embedding(
            state_id="embedding-1",
            payload=vector.tobytes(),
            metadata={"vector_dim": int(vector.shape[0]), "dtype": "float32"},
        )
        assert embedding_ref.storage in {MEMFD_STORAGE, PY_SHARED_MEMORY_STORAGE}
        restored = pool.get_embedding(pool.load_ref("embedding-1"))
        assert restored.shape == vector.shape
        assert np.allclose(restored, vector)
    finally:
        _cleanup_pool(pool)


@pytest.mark.skipif(
    not hasattr(socket, "SCM_RIGHTS") or not hasattr(socket, "socketpair"),
    reason="SCM_RIGHTS socket transfer is unavailable on this platform",
)
def test_memfd_statepool_transfers_fd_via_scm_rights(tmp_path: Path) -> None:
    if not memfd_create_available():
        pytest.skip("memfd_create unavailable; shared_memory fallback has separate coverage")

    sender = MemfdStatePool(tmp_path / "sender")
    receiver = MemfdStatePool(tmp_path / "receiver")
    left, right = socket.socketpair()
    try:
        ref = sender.put_bytes(
            "artifact-2",
            "TOOL_ARTIFACT",
            b"cross-process memfd payload",
            metadata={"tool_name": "boot_timing_probe"},
        )
        assert ref.storage == MEMFD_STORAGE
        sender.send_fd_via_socket(ref.state_id, left)
        received_state_id = receiver.receive_fd_via_socket(right)
        assert received_state_id == ref.state_id
        assert receiver.get_bytes(ref) == b"cross-process memfd payload"
    finally:
        left.close()
        right.close()
        sender.close_all()
        receiver.close_all()
