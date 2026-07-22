from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Protocol

from .schemas import Memory


class AddLogger(Protocol):
    def log_add(self, memory: Memory) -> None:
        """Record a newly added memory."""


class JsonlAddLogger:
    """Append newly added memories to a local JSONL file."""

    def __init__(
        self,
        path: str | Path = "memory_module/logs/memory_add.jsonl",
    ) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def log_add(self, memory: Memory) -> None:
        payload = memory.payload
        record = {
            "memory_id": memory.id,
            "content": payload.content,
            "keywords": payload.keywords,
            "memory_type": payload.memory_type,
            "source_agent": payload.source_agent,
            "source_task_id": payload.source_task_id,
            "task_topic": payload.task_topic,
            "created_at": payload.created_at.isoformat(),
        }
        line = json.dumps(record, ensure_ascii=False)

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as log_file:
                log_file.write(f"{line}\n")
