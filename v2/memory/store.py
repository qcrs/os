from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from v2.contracts import ReplayClass
from v2.memory.embedding import cosine_similarity
from v2.memory.models import (
    MemoryCommit,
    MemoryCandidatePool,
    MemoryCommitStatus,
    MemoryMatch,
    MemoryMatchResult,
    MemoryRerankItem,
    MemoryRerankResult,
    MemoryRef,
    MemoryType,
    MemoryValidationStatus,
    StructuredEmbedding,
)


@dataclass
class MemoryIndexStore:
    embeddings: dict[str, StructuredEmbedding] = field(default_factory=dict)
    commits: dict[str, MemoryCommit] = field(default_factory=dict)
    store_root: Path | None = None

    def __post_init__(self) -> None:
        if self.store_root is not None:
            self.store_root.mkdir(parents=True, exist_ok=True)

    @property
    def persistent(self) -> bool:
        return self.store_root is not None

    @property
    def embedding_registry_path(self) -> Path | None:
        if self.store_root is None:
            return None
        return self.store_root / "embedding_registry.json"

    @property
    def commit_registry_path(self) -> Path | None:
        if self.store_root is None:
            return None
        return self.store_root / "commit_registry.json"

    def put_embedding(self, embedding: StructuredEmbedding) -> StructuredEmbedding:
        self.embeddings[embedding.embedding_id] = embedding
        self._persist_embedding(embedding)
        return embedding

    def put_commit(self, commit: MemoryCommit) -> MemoryCommit:
        self.commits[commit.memory_ref.memory_id] = commit
        self._persist_commit(commit)
        return commit

    def commit_candidate(
        self,
        *,
        commit: MemoryCommit,
        quality_floor_pass: bool,
        answer_adopted: bool,
    ) -> MemoryCommit:
        status = MemoryCommitStatus.COMMITTED if quality_floor_pass and answer_adopted else MemoryCommitStatus.CANDIDATE
        validation_status = MemoryValidationStatus.PASSED if quality_floor_pass else MemoryValidationStatus.FAILED
        replay_class = commit.memory_ref.replay_class
        if status != MemoryCommitStatus.COMMITTED and replay_class != ReplayClass.ASSIST:
            replay_class = ReplayClass.ASSIST
        committed_ref = replace(
            commit.memory_ref,
            replay_class=replay_class,
            commit_status=status,
            validation_status=validation_status,
            answer_adopted=answer_adopted,
        )
        committed = replace(commit, memory_ref=committed_ref, quality_floor_pass=quality_floor_pass)
        self.commits[committed.memory_ref.memory_id] = committed
        self._persist_commit(committed)
        return committed

    def invalidate(self, memory_id: str) -> MemoryCommit:
        commit = self.commits[memory_id]
        invalidated_ref = replace(
            commit.memory_ref,
            commit_status=MemoryCommitStatus.INVALIDATED,
            validation_status=MemoryValidationStatus.FAILED,
            answer_adopted=False,
            replay_class=ReplayClass.ASSIST,
        )
        invalidated = replace(commit, memory_ref=invalidated_ref, quality_floor_pass=False)
        self.commits[memory_id] = invalidated
        self._persist_commit(invalidated)
        return invalidated

    def lookup(
        self,
        *,
        query_task_id: str,
        query_spec_hash: str,
        query_embedding: StructuredEmbedding,
        limit: int = 3,
        allow_replay: bool = True,
    ) -> MemoryMatchResult:
        matches: list[MemoryMatch] = []
        candidate_memory_ids: list[str] = []
        candidate_types: list[str] = []
        candidate_taxonomy: dict[str, int] = {}
        for commit in self.commits.values():
            ref = commit.memory_ref
            if ref.commit_status == MemoryCommitStatus.INVALIDATED:
                continue
            if ref.embedding_ref_id not in self.embeddings:
                continue
            if ref.commit_status != MemoryCommitStatus.COMMITTED and ref.replay_class != ReplayClass.ASSIST:
                continue
            candidate_memory_ids.append(ref.memory_id)
            candidate_types.append(ref.memory_type.value)
            candidate_taxonomy[ref.memory_type.value] = candidate_taxonomy.get(ref.memory_type.value, 0) + 1
            score = cosine_similarity(query_embedding, self.embeddings[ref.embedding_ref_id])
            replay_class = ref.replay_class if allow_replay else ReplayClass.ASSIST
            if ref.commit_status != MemoryCommitStatus.COMMITTED:
                replay_class = ReplayClass.ASSIST
            matches.append(
                MemoryMatch(
                    memory_ref=replace(ref, replay_class=replay_class),
                    matched_on="embedding_similarity",
                    score=score,
                    replay_class=replay_class,
                )
            )
        matches.sort(key=lambda match: (-match.score, match.memory_ref.memory_id))
        top_matches = tuple(matches[:limit])
        candidate_pool = MemoryCandidatePool(
            query_task_id=query_task_id,
            query_spec_hash=query_spec_hash,
            candidate_memory_ids=tuple(candidate_memory_ids),
            candidate_types=tuple(candidate_types),
            candidate_taxonomy=candidate_taxonomy,
        )
        selected_taxonomy: dict[str, int] = {}
        for match in top_matches:
            key = match.memory_ref.memory_type.value
            selected_taxonomy[key] = selected_taxonomy.get(key, 0) + 1
        rerank_result = MemoryRerankResult(
            query_task_id=query_task_id,
            selected_memory_ids=tuple(match.memory_ref.memory_id for match in top_matches),
            items=tuple(
                MemoryRerankItem(
                    memory_id=match.memory_ref.memory_id,
                    rank=index + 1,
                    score=match.score,
                    replay_class=match.replay_class,
                    selected=index < len(top_matches),
                    )
                for index, match in enumerate(matches)
            ),
            selected_taxonomy=selected_taxonomy,
        )
        decision = "memory_match_found" if top_matches else "memory_match_missing"
        return MemoryMatchResult(
            query_task_id=query_task_id,
            query_spec_hash=query_spec_hash,
            matches=top_matches,
            retrieval_decision=decision,
            candidate_pool=candidate_pool,
            rerank_result=rerank_result,
        )

    def load_persisted_state(self) -> None:
        if self.store_root is None:
            return
        for payload in self._read_registry(self.embedding_registry_path).values():
            embedding = self._embedding_from_payload(payload)
            self.embeddings[embedding.embedding_id] = embedding
        for payload in self._read_registry(self.commit_registry_path).values():
            commit = self._commit_from_payload(payload)
            self.commits[commit.memory_ref.memory_id] = commit

    def list_commits(self) -> tuple[MemoryCommit, ...]:
        return tuple(sorted(self.commits.values(), key=lambda commit: commit.memory_ref.memory_id))

    def list_embeddings(self) -> tuple[StructuredEmbedding, ...]:
        return tuple(sorted(self.embeddings.values(), key=lambda embedding: embedding.embedding_id))

    def _persist_embedding(self, embedding: StructuredEmbedding) -> None:
        if self.store_root is None:
            return
        payload = self._read_registry(self.embedding_registry_path)
        payload[embedding.embedding_id] = embedding.canonical_payload()
        self._write_registry(self.embedding_registry_path, payload)

    def _persist_commit(self, commit: MemoryCommit) -> None:
        if self.store_root is None:
            return
        payload = self._read_registry(self.commit_registry_path)
        payload[commit.memory_ref.memory_id] = commit.canonical_payload()
        self._write_registry(self.commit_registry_path, payload)

    def _read_registry(self, path: Path | None) -> dict[str, dict[str, object]]:
        if path is None or not path.exists():
            return {}
        import json

        loaded = json.loads(path.read_text(encoding="utf-8"))
        return {str(key): dict(value) for key, value in dict(loaded).items()}

    def _write_registry(self, path: Path | None, payload: dict[str, dict[str, object]]) -> None:
        if path is None:
            return
        import json

        path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _embedding_from_payload(self, payload: dict[str, object]) -> StructuredEmbedding:
        vector = tuple(float(value) for value in payload.get("vector", []))
        return StructuredEmbedding(
            embedding_id=str(payload["embedding_id"]),
            vector=vector,
            dims=int(payload["dims"]),
            source_text_hash=str(payload["source_text_hash"]),
            encoding=str(payload.get("encoding", "hashed-bow-v1")),
            schema_version=str(payload.get("schema_version", "")),
        )

    def _memory_ref_from_payload(self, payload: dict[str, object]) -> MemoryRef:
        metadata = dict(payload.get("metadata", {}))
        return MemoryRef(
            memory_id=str(payload["memory_id"]),
            memory_type=MemoryType(str(payload["memory_type"])),
            replay_class=ReplayClass(str(payload["replay_class"])),
            score=float(payload["score"]),
            source_task_id=str(payload["source_task_id"]),
            summary=str(payload["summary"]),
            canonical_task_spec_hash=str(payload["canonical_task_spec_hash"]),
            source_agent=str(payload.get("source_agent", metadata.get("source_agent", ""))),
            created_at_ns=int(payload.get("created_at_ns", metadata.get("created_at_ns", 0))),
            task_theme=str(payload.get("task_theme", metadata.get("task_theme", ""))),
            tags=tuple(str(item) for item in payload.get("tags", metadata.get("tags", []))),
            source_role_path=tuple(
                str(item) for item in payload.get("source_role_path", metadata.get("source_role_path", []))
            ),
            producer_run_id=str(payload.get("producer_run_id", metadata.get("producer_run_id", ""))),
            artifact_ref_id=str(payload.get("artifact_ref_id", "")),
            semantic_state_ref_id=str(payload.get("semantic_state_ref_id", "")),
            embedding_ref_id=str(payload.get("embedding_ref_id", "")),
            manifest_hash=str(payload.get("manifest_hash", "")),
            commit_status=MemoryCommitStatus(str(payload.get("commit_status", MemoryCommitStatus.CANDIDATE.value))),
            validation_status=MemoryValidationStatus(
                str(payload.get("validation_status", MemoryValidationStatus.UNCHECKED.value))
            ),
            answer_adopted=bool(payload.get("answer_adopted", False)),
            schema_version=str(payload.get("schema_version", "")),
            metadata=metadata,
        )

    def _commit_from_payload(self, payload: dict[str, object]) -> MemoryCommit:
        from v2.contracts import CanonicalTaskSpec

        memory_payload = dict(payload["memory_ref"])
        memory_ref = self._memory_ref_from_payload(memory_payload)
        spec_payload = dict(payload["canonical_task_spec"])
        return MemoryCommit(
            memory_ref=memory_ref,
            canonical_task_spec=CanonicalTaskSpec(
                task_family=str(spec_payload["task_family"]),
                intent_op=str(spec_payload["intent_op"]),
                target_entities=tuple(spec_payload.get("target_entities", [])),
                time_scope=str(spec_payload.get("time_scope", "")),
                required_outputs=tuple(spec_payload.get("required_outputs", [])),
                required_tools=tuple(spec_payload.get("required_tools", [])),
                arguments=dict(spec_payload.get("arguments", {})),
                schema_version=str(spec_payload.get("schema_version", "")),
            ),
            required_outputs=tuple(payload.get("required_outputs", [])),
            quality_floor_pass=bool(payload.get("quality_floor_pass", False)),
            created_from_artifact_hash=str(payload.get("created_from_artifact_hash", "")),
            schema_version=str(payload.get("schema_version", "")),
        )
