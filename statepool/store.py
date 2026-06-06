from __future__ import annotations

import hashlib
import json
import mmap
from pathlib import Path

import numpy as np

from protocol.messages import StateRef


class FileBackedStatePool:
    """First host-side StatePool implementation.

    This deliberately starts with file-backed state artifacts so host-side
    development does not depend on privileged transports.
    """

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
            storage="MMAP_FILE",
            handle=str(path),
            length=len(payload),
            checksum=checksum,
            metadata=dict(metadata or {}),
        )
        meta_path.write_text(
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
        return ref

    def get_bytes(self, ref: StateRef) -> bytes:
        with Path(ref.handle).open("rb") as handle:
            with mmap.mmap(handle.fileno(), length=0, access=mmap.ACCESS_READ) as mm:
                return mm[:]

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
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        return StateRef(**payload)
