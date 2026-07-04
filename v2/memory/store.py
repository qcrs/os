from __future__ import annotations

import json
import re
import sqlite3
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
    _db: sqlite3.Connection | None = field(default=None, init=False, repr=False, compare=False)
    _fts5_enabled: bool = field(default=False, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.store_root is not None:
            self.store_root.mkdir(parents=True, exist_ok=True)
        self._init_db()

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

    @property
    def sqlite_index_path(self) -> Path | None:
        if self.store_root is None:
            return None
        return self.store_root / "memory_index.sqlite3"

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
        status = MemoryCommitStatus.COMMITTED if quality_floor_pass else MemoryCommitStatus.CANDIDATE
        validation_status = MemoryValidationStatus.PASSED if quality_floor_pass else MemoryValidationStatus.FAILED
        # replay_class is preserved regardless of commit status.
        # CANDIDATE entries are served as ASSIST by lookup() at match time,
        # but the stored class must not be permanently downgraded so that
        # Round N+1 intra-session lookups can still see the original intent.
        committed_ref = replace(
            commit.memory_ref,
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
            # CANDIDATE entries are allowed into the candidate pool so that
            # intra-session Round N+1 can find what Round N wrote.
            # Their replay_class is clamped to ASSIST at lines 123-124 below.
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
            self._index_commit(commit)

    def lookup_by_keyword(self, keyword: str, *, limit: int = 3) -> list[MemoryCommit]:
        needle = keyword.strip().lower()
        if not needle:
            return []
        if self._db is None:
            return []
        if self._fts5_enabled:
            query = self._fts_query(needle)
            rows = self._db.execute(
                """
                SELECT memories.memory_id
                FROM memories_fts
                JOIN memories ON memories.memory_id = memories_fts.memory_id
                WHERE memories_fts MATCH ?
                  AND memories.commit_status != ?
                ORDER BY bm25(memories_fts), memories.created_at_ns DESC
                LIMIT ?
                """,
                (query, MemoryCommitStatus.INVALIDATED.value, limit),
            ).fetchall()
        else:
            like = f"%{needle}%"
            rows = self._db.execute(
                """
                SELECT memory_id
                FROM memories
                WHERE commit_status != ?
                  AND (
                    lower(summary) LIKE ?
                    OR lower(task_theme) LIKE ?
                    OR lower(source_task_id) LIKE ?
                    OR lower(source_agent) LIKE ?
                  )
                ORDER BY created_at_ns DESC
                LIMIT ?
                """,
                (
                    MemoryCommitStatus.INVALIDATED.value,
                    like,
                    like,
                    like,
                    like,
                    limit,
                ),
            ).fetchall()
        return [self.commits[memory_id] for (memory_id,) in rows if memory_id in self.commits]

    def lookup_by_tags(
        self,
        tags: set[str],
        *,
        require_all: bool = False,
        limit: int = 3,
    ) -> list[MemoryCommit]:
        if not tags:
            return []
        if self._db is None:
            return []
        normalized_tags = {self._normalize_tag(tag) for tag in tags if self._normalize_tag(tag)}
        if not normalized_tags:
            return []
        hits: list[tuple[int, int, str]] = []
        rows = self._db.execute(
            """
            SELECT memory_id, tags_text, created_at_ns
            FROM memories
            WHERE commit_status != ?
            """,
            (MemoryCommitStatus.INVALIDATED.value,),
        ).fetchall()
        for memory_id, tags_text, created_at_ns in rows:
            ref_tags = set(str(tags_text or "").split())
            overlap = len(normalized_tags & ref_tags)
            if require_all and overlap < len(normalized_tags):
                continue
            if overlap == 0:
                continue
            hits.append((overlap, int(created_at_ns), str(memory_id)))
        hits.sort(key=lambda item: (-item[0], -item[1]))
        return [self.commits[memory_id] for _, _, memory_id in hits[:limit] if memory_id in self.commits]

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
        self._index_commit(commit)
        if self.store_root is None:
            return
        payload = self._read_registry(self.commit_registry_path)
        payload[commit.memory_ref.memory_id] = commit.canonical_payload()
        self._write_registry(self.commit_registry_path, payload)

    def _init_db(self) -> None:
        db_target = ":memory:" if self.sqlite_index_path is None else str(self.sqlite_index_path)
        self._db = sqlite3.connect(db_target)
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                memory_id TEXT PRIMARY KEY,
                task_theme TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                source_task_id TEXT NOT NULL DEFAULT '',
                source_agent TEXT NOT NULL DEFAULT '',
                created_at_ns INTEGER NOT NULL DEFAULT 0,
                memory_type TEXT NOT NULL DEFAULT '',
                replay_class TEXT NOT NULL DEFAULT '',
                commit_status TEXT NOT NULL DEFAULT '',
                validation_status TEXT NOT NULL DEFAULT '',
                answer_adopted INTEGER NOT NULL DEFAULT 0,
                tags_json TEXT NOT NULL DEFAULT '[]',
                tags_text TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_created_at_ns ON memories(created_at_ns DESC)"
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_commit_status ON memories(commit_status)"
        )
        try:
            self._db.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(memory_id UNINDEXED, task_theme, summary, source_task_id, source_agent, tags)
                """
            )
        except sqlite3.OperationalError:
            self._fts5_enabled = False
        else:
            self._fts5_enabled = True
        self._db.commit()

    def _index_commit(self, commit: MemoryCommit) -> None:
        if self._db is None:
            return
        ref = commit.memory_ref
        tags_json = json.dumps(list(ref.tags), ensure_ascii=True, sort_keys=False)
        tags_text = self._normalize_tags(ref.tags)
        self._db.execute(
            """
            INSERT OR REPLACE INTO memories (
                memory_id,
                task_theme,
                summary,
                source_task_id,
                source_agent,
                created_at_ns,
                memory_type,
                replay_class,
                commit_status,
                validation_status,
                answer_adopted,
                tags_json,
                tags_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ref.memory_id,
                ref.task_theme,
                ref.summary,
                ref.source_task_id,
                ref.source_agent,
                ref.created_at_ns,
                ref.memory_type.value,
                ref.replay_class.value,
                ref.commit_status.value,
                ref.validation_status.value,
                1 if ref.answer_adopted else 0,
                tags_json,
                tags_text,
            ),
        )
        if self._fts5_enabled:
            self._db.execute("DELETE FROM memories_fts WHERE memory_id = ?", (ref.memory_id,))
            self._db.execute(
                """
                INSERT INTO memories_fts(memory_id, task_theme, summary, source_task_id, source_agent, tags)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ref.memory_id,
                    ref.task_theme,
                    ref.summary,
                    ref.source_task_id,
                    ref.source_agent,
                    tags_text,
                ),
            )
        self._db.commit()

    def _fts_query(self, keyword: str) -> str:
        tokens = [token for token in re.findall(r"[a-z0-9_]+", keyword.lower()) if token]
        if not tokens:
            return f'"{keyword}"'
        return " AND ".join(f'"{token}"' for token in tokens)

    def _normalize_tag(self, value: str) -> str:
        return re.sub(r"\s+", "_", value.strip().lower())

    def _normalize_tags(self, values: tuple[str, ...] | set[str] | list[str]) -> str:
        normalized = [self._normalize_tag(str(value)) for value in values]
        return " ".join(value for value in normalized if value)

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
