from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from v2.retrieval import RetrievalBundle


@dataclass
class RetrievalSidecarStore:
    root: Path
    candidate_pools: dict[str, dict[str, object]] = field(default_factory=dict)
    rerank_results: dict[str, dict[str, object]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def candidate_pool_registry_path(self) -> Path:
        return self.root / "candidate_pool_registry.json"

    @property
    def rerank_registry_path(self) -> Path:
        return self.root / "rerank_registry.json"

    def put_bundle(self, bundle: RetrievalBundle) -> tuple[Path, Path]:
        candidate_payload = bundle.candidate_pool.audit_payload()
        rerank_payload = bundle.rerank_result.canonical_payload()
        self.candidate_pools[bundle.candidate_pool.pool_hash] = candidate_payload
        self.rerank_results[bundle.rerank_result.rerank_hash] = rerank_payload
        self._write_registry(self.candidate_pool_registry_path, self.candidate_pools)
        self._write_registry(self.rerank_registry_path, self.rerank_results)
        return self.candidate_pool_registry_path, self.rerank_registry_path

    def load(self) -> None:
        self.candidate_pools = self._read_registry(self.candidate_pool_registry_path)
        self.rerank_results = self._read_registry(self.rerank_registry_path)

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
