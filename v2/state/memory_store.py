from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from v2.memory import MemoryCommit, MemoryMatchResult


@dataclass
class MemorySidecarStore:
    root: Path
    commits: dict[str, dict[str, object]] = field(default_factory=dict)
    match_results: dict[str, dict[str, object]] = field(default_factory=dict)
    candidate_pools: dict[str, dict[str, object]] = field(default_factory=dict)
    rerank_results: dict[str, dict[str, object]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def commit_registry_path(self) -> Path:
        return self.root / "commit_registry.json"

    @property
    def match_registry_path(self) -> Path:
        return self.root / "match_registry.json"

    @property
    def candidate_pool_registry_path(self) -> Path:
        return self.root / "candidate_pool_registry.json"

    @property
    def rerank_registry_path(self) -> Path:
        return self.root / "rerank_registry.json"

    def put_commit(self, commit: MemoryCommit) -> Path:
        self.commits[commit.memory_ref.memory_id] = commit.canonical_payload()
        self._write_registry(self.commit_registry_path, self.commits)
        return self.commit_registry_path

    def put_match_result(self, result: MemoryMatchResult) -> Path:
        self.match_results[result.result_hash] = result.canonical_payload()
        self._write_registry(self.match_registry_path, self.match_results)
        if result.candidate_pool is not None:
            self.candidate_pools[result.candidate_pool.pool_hash] = result.candidate_pool.canonical_payload()
            self._write_registry(self.candidate_pool_registry_path, self.candidate_pools)
        if result.rerank_result is not None:
            self.rerank_results[result.rerank_result.rerank_hash] = result.rerank_result.canonical_payload()
            self._write_registry(self.rerank_registry_path, self.rerank_results)
        return self.match_registry_path

    def load(self) -> None:
        self.commits = self._read_registry(self.commit_registry_path)
        self.match_results = self._read_registry(self.match_registry_path)
        self.candidate_pools = self._read_registry(self.candidate_pool_registry_path)
        self.rerank_results = self._read_registry(self.rerank_registry_path)

    def get_commit(self, memory_id: str) -> dict[str, object]:
        return dict(self.commits[memory_id])

    def get_match_result(self, result_hash: str) -> dict[str, object]:
        return dict(self.match_results[result_hash])

    def get_candidate_pool(self, pool_hash: str) -> dict[str, object]:
        return dict(self.candidate_pools[pool_hash])

    def get_rerank_result(self, rerank_hash: str) -> dict[str, object]:
        return dict(self.rerank_results[rerank_hash])

    def _read_registry(self, path: Path) -> dict[str, dict[str, object]]:
        if not path.exists():
            return {}
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return {str(key): dict(value) for key, value in dict(loaded).items()}

    def _write_registry(self, path: Path, payload: dict[str, dict[str, object]]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
