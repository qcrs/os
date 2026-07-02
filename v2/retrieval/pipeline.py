from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from v2.contracts import CanonicalTaskSpec
from v2.memory import DeterministicEmbeddingEncoder, EmbeddingEncoder, build_embedding_encoder
from v2.provenance import DeterministicFanInBuilder, EvidenceCandidate
from v2.refs import CanonicalEvidencePack, HydrateManifest, HydrateManifestEntry
from v2.retrieval.corpus import (
    CsvTableDocument,
    FinancialReportDocument,
    OfflineMarkdownLongDocCorpus,
    OfflineCsvTableCorpus,
    OfflineFinancialReportCorpus,
)
from v2.retrieval.models import (
    RetrievalBundle,
    RetrievalCandidatePool,
    RetrievalCandidateRecord,
    RetrievalLogEntry,
    RetrievalPruningBucketStat,
    RetrievalPruningProfile,
    RetrievalRerankItem,
    RetrievalRerankResult,
    RetrieverKind,
    RetrieverOutput,
)


def _stable_entry_key(candidate: EvidenceCandidate) -> str:
    if candidate.locator is None:
        return f"hint:{candidate.item_id}"
    locator = candidate.locator
    if hasattr(locator, "canonical_text_id"):
        return f"text:{locator.source_doc_hash}:{locator.canonical_text_id}:{locator.start_char}:{locator.end_char}"
    return (
        f"table:{locator.source_doc_hash}:{locator.table_id}:{locator.sheet_name}:"
        f"{locator.row_idx}:{locator.col_idx}"
    )


@dataclass(frozen=True)
class LexicalMetadataRetriever:
    def retrieve(self, *, spec: CanonicalTaskSpec, document: FinancialReportDocument | CsvTableDocument) -> RetrieverOutput:
        ticker = str(spec.arguments.get("ticker", getattr(document, "ticker", "")))
        quarter = str(spec.arguments.get("quarter", getattr(document, "quarter", "")))
        dataset_id = str(spec.arguments.get("dataset_id", getattr(document, "dataset_id", "")))
        hints = tuple(
            EvidenceCandidate(
                item_id=f"hint-{index + 1}",
                bucket="lexical_hint",
                locator=None,
                rendered_text=f"Route to {ticker or dataset_id} {quarter} via {hint}.",
                source_name="lexical",
                rank=index + 1,
                metadata={"hint": hint},
            )
            for index, hint in enumerate(document.metadata_hints[:2])
        )
        return RetrieverOutput(
            retriever_kind=RetrieverKind.LEXICAL_METADATA,
            candidates=tuple(candidate.__dict__ for candidate in hints),
            log_entry=RetrievalLogEntry(
                retriever_kind=RetrieverKind.LEXICAL_METADATA,
                candidate_count=len(document.metadata_hints),
                selected_count=len(hints),
                selected_ids=tuple(candidate.item_id for candidate in hints),
                diagnostics={"title": document.title},
            ),
        )


@dataclass(frozen=True)
class SemanticChunkRetriever:
    encoder: EmbeddingEncoder = field(default_factory=lambda: DeterministicEmbeddingEncoder(dims=16))
    top_k: int = 1

    def retrieve(self, *, spec: CanonicalTaskSpec, document: FinancialReportDocument | CsvTableDocument) -> RetrieverOutput:
        doc_identity = getattr(document, "ticker", getattr(document, "dataset_id", "dataset"))
        doc_scope = getattr(document, "quarter", Path(getattr(document, "csv_path", "")).name or "scope")
        query_text = (
            f"{spec.task_family} {spec.intent_op} "
            f"{spec.arguments.get('ticker', doc_identity)} "
            f"{spec.arguments.get('quarter', doc_scope)}"
        )
        query_embedding = self.encoder.encode(
            embedding_id=f"embedding-query-{str(doc_identity).lower()}-{str(doc_scope).lower()}",
            text=query_text,
        )
        scored = []
        for fragment in document.text_fragments:
            fragment_embedding = self.encoder.encode(
                embedding_id=f"embedding-fragment-{fragment.fragment_id}-{str(doc_scope).lower()}",
                text=fragment.text,
            )
            score = sum(left * right for left, right in zip(query_embedding.vector, fragment_embedding.vector))
            scored.append((score, fragment))
        scored.sort(key=lambda item: (-item[0], item[1].fragment_id))
        selected = tuple(
            EvidenceCandidate(
                item_id=f"ctx-{fragment.fragment_id}",
                bucket="semantic_context",
                locator=fragment.locator(),
                rendered_text=fragment.text,
                source_name="semantic",
                rank=index + 1,
                metadata={"score": round(score, 6)},
            )
            for index, (score, fragment) in enumerate(scored[: self.top_k])
        )
        return RetrieverOutput(
            retriever_kind=RetrieverKind.SEMANTIC_CHUNK,
            candidates=tuple(candidate.__dict__ for candidate in selected),
            query_embedding=query_embedding,
            log_entry=RetrievalLogEntry(
                retriever_kind=RetrieverKind.SEMANTIC_CHUNK,
                candidate_count=len(document.text_fragments),
                selected_count=len(selected),
                selected_ids=tuple(candidate.item_id for candidate in selected),
                diagnostics={"top_k": self.top_k},
            ),
        )


@dataclass(frozen=True)
class TableStructureRetriever:
    def retrieve(self, *, spec: CanonicalTaskSpec, document: FinancialReportDocument | CsvTableDocument) -> RetrieverOutput:
        requested_metric = str(
            spec.arguments.get(
                "metric",
                spec.arguments.get(
                    "column",
                    spec.arguments.get(
                        "value_column",
                        spec.arguments.get("mean_column", spec.arguments.get("max_column", "revenue")),
                    ),
                ),
            )
        )
        rows = tuple(
            row
            for row in document.table_rows
            if row.metric_name == requested_metric or requested_metric == "revenue"
        )
        selected = tuple(
            EvidenceCandidate(
                item_id=f"fact-{row.metric_name}-{index + 1}",
                bucket="hard_fact",
                locator=row.locator(),
                rendered_text=row.rendered_text,
                source_name="table",
                rank=index + 1,
                metadata={"metric_name": row.metric_name, "value": row.value},
            )
            for index, row in enumerate(rows[:1])
        )
        return RetrieverOutput(
            retriever_kind=RetrieverKind.TABLE_STRUCTURE,
            candidates=tuple(candidate.__dict__ for candidate in selected),
            log_entry=RetrievalLogEntry(
                retriever_kind=RetrieverKind.TABLE_STRUCTURE,
                candidate_count=len(document.table_rows),
                selected_count=len(selected),
                selected_ids=tuple(candidate.item_id for candidate in selected),
                diagnostics={"metric": requested_metric},
            ),
        )


@dataclass
class RetrieverFanoutPipeline:
    corpus: OfflineFinancialReportCorpus = field(default_factory=OfflineFinancialReportCorpus)
    csv_corpus: OfflineCsvTableCorpus = field(default_factory=OfflineCsvTableCorpus)
    long_doc_corpus: OfflineMarkdownLongDocCorpus = field(default_factory=OfflineMarkdownLongDocCorpus)
    lexical_retriever: LexicalMetadataRetriever = field(default_factory=LexicalMetadataRetriever)
    semantic_retriever: SemanticChunkRetriever = field(default_factory=SemanticChunkRetriever)
    table_retriever: TableStructureRetriever = field(default_factory=TableStructureRetriever)
    fan_in_builder: DeterministicFanInBuilder = field(default_factory=DeterministicFanInBuilder)

    @classmethod
    def with_embedding_mode(
        cls,
        mode: str = "deterministic",
        *,
        dims: int = 16,
        model_path: str | Path | None = None,
        device: str | None = None,
    ) -> "RetrieverFanoutPipeline":
        encoder = build_embedding_encoder(
            mode,
            dims=dims,
            model_path=model_path,
            device=device,
        )
        return cls(semantic_retriever=SemanticChunkRetriever(encoder=encoder))

    def _build_candidate_pool(
        self,
        *,
        task_id: str,
        query_text: str,
        planner_scope_payload: dict[str, object],
        lexical_candidates: tuple[EvidenceCandidate, ...],
        semantic_candidates: tuple[EvidenceCandidate, ...],
        table_candidates: tuple[EvidenceCandidate, ...],
    ) -> RetrievalCandidatePool:
        candidates: list[RetrievalCandidateRecord] = []
        for candidate in lexical_candidates:
            candidates.append(
                RetrievalCandidateRecord(
                    candidate_id=candidate.item_id,
                    retriever_kind=RetrieverKind.LEXICAL_METADATA,
                    bucket=candidate.bucket,
                    rendered_text=candidate.rendered_text,
                    source_name=candidate.source_name,
                    rank=candidate.rank,
                    metadata=dict(candidate.metadata),
                )
            )
        for candidate in semantic_candidates:
            candidates.append(
                RetrievalCandidateRecord(
                    candidate_id=candidate.item_id,
                    retriever_kind=RetrieverKind.SEMANTIC_CHUNK,
                    bucket=candidate.bucket,
                    rendered_text=candidate.rendered_text,
                    source_name=candidate.source_name,
                    rank=candidate.rank,
                    score=float(candidate.metadata.get("score", 0.0)),
                    metadata=dict(candidate.metadata),
                )
            )
        for candidate in table_candidates:
            candidates.append(
                RetrievalCandidateRecord(
                    candidate_id=candidate.item_id,
                    retriever_kind=RetrieverKind.TABLE_STRUCTURE,
                    bucket=candidate.bucket,
                    rendered_text=candidate.rendered_text,
                    source_name=candidate.source_name,
                    rank=candidate.rank,
                    score=1.0 / max(candidate.rank, 1),
                    metadata=dict(candidate.metadata),
                )
            )
        candidates.sort(key=lambda item: (item.rank, item.candidate_id))
        return RetrievalCandidatePool(
            task_id=task_id,
            query_text=query_text,
            candidates=tuple(candidates),
            planner_scope_payload=dict(sorted(planner_scope_payload.items())),
        )

    @staticmethod
    def _normalize_planner_scope(
        *,
        spec: CanonicalTaskSpec,
        planner_scope_payload: dict[str, object] | None,
    ) -> dict[str, object]:
        payload = dict(planner_scope_payload or {})
        query_text = str(payload.get("query_text", "")).strip()
        if not query_text:
            ticker = str(spec.arguments.get("ticker", "ACME"))
            quarter = str(spec.arguments.get("quarter", "2026Q1"))
            query_text = f"{spec.task_family} {spec.intent_op} {ticker} {quarter}"
        required_tools = payload.get("required_tools")
        payload["required_tools"] = (
            [str(item).strip() for item in required_tools if str(item).strip()]
            if isinstance(required_tools, (list, tuple))
            else list(spec.required_tools)
        )
        candidate_keys = payload.get("candidate_keys")
        payload["candidate_keys"] = (
            [str(item).strip() for item in candidate_keys if str(item).strip()]
            if isinstance(candidate_keys, (list, tuple))
            else []
        )
        supporting_doc_ids = payload.get("supporting_doc_ids")
        payload["supporting_doc_ids"] = (
            [str(item).strip() for item in supporting_doc_ids if str(item).strip()]
            if isinstance(supporting_doc_ids, (list, tuple))
            else []
        )
        payload["query_text"] = query_text
        return payload

    @staticmethod
    def _filter_candidates_by_planner_scope(
        *,
        lexical_candidates: tuple[EvidenceCandidate, ...],
        semantic_candidates: tuple[EvidenceCandidate, ...],
        table_candidates: tuple[EvidenceCandidate, ...],
        planner_scope_payload: dict[str, object],
    ) -> tuple[tuple[EvidenceCandidate, ...], tuple[EvidenceCandidate, ...], tuple[EvidenceCandidate, ...]]:
        allowed_doc_ids = {
            str(item).strip()
            for item in planner_scope_payload.get("supporting_doc_ids", [])
            if str(item).strip()
        }
        if not allowed_doc_ids:
            return lexical_candidates, semantic_candidates, table_candidates

        def _candidate_allowed(candidate: EvidenceCandidate) -> bool:
            locator = candidate.locator
            if locator is None:
                return True
            return str(getattr(locator, "source_doc_hash", "")).strip() in allowed_doc_ids

        return (
            tuple(candidate for candidate in lexical_candidates if _candidate_allowed(candidate)),
            tuple(candidate for candidate in semantic_candidates if _candidate_allowed(candidate)),
            tuple(candidate for candidate in table_candidates if _candidate_allowed(candidate)),
        )

    def _rerank_candidate_pool(
        self,
        *,
        task_id: str,
        candidate_pool: RetrievalCandidatePool,
        selected_candidate_ids: set[str],
    ) -> RetrievalRerankResult:
        scored_candidates: list[tuple[float, RetrievalCandidateRecord]] = []
        for candidate in candidate_pool.candidates:
            score = candidate.score + (1.0 / (60 + candidate.rank))
            if candidate.bucket == "hard_fact":
                score += 100.0
            elif candidate.bucket == "semantic_context":
                score += 10.0
            elif candidate.bucket == "lexical_hint":
                score += 1.0
            scored_candidates.append((score, candidate))
        scored_candidates.sort(key=lambda item: (-item[0], item[1].candidate_id))
        return RetrievalRerankResult(
            task_id=task_id,
            selected_candidate_ids=tuple(sorted(selected_candidate_ids)),
            items=tuple(
                RetrievalRerankItem(
                    candidate_id=candidate.candidate_id,
                    rank=index + 1,
                    fused_score=round(score, 6),
                    selected=candidate.candidate_id in selected_candidate_ids,
                    rationale=(
                        "selected_for_canonical_pack"
                        if candidate.candidate_id in selected_candidate_ids
                        else "not_selected_after_fan_in"
                    ),
                )
                for index, (score, candidate) in enumerate(scored_candidates)
            ),
        )

    def _build_pruning_profile(
        self,
        *,
        task_id: str,
        candidate_pool: RetrievalCandidatePool,
        selected_candidate_ids: set[str],
        full_corpus_bytes: int,
        selected_evidence_bytes: int,
    ) -> RetrievalPruningProfile:
        bucket_map: dict[str, list[RetrievalCandidateRecord]] = {}
        for candidate in candidate_pool.candidates:
            bucket_map.setdefault(candidate.bucket, []).append(candidate)
        bucket_stats = []
        for bucket, candidates in sorted(bucket_map.items()):
            selected = [candidate for candidate in candidates if candidate.candidate_id in selected_candidate_ids]
            selected_bytes = sum(len(candidate.rendered_text.encode("utf-8")) for candidate in selected)
            bucket_stats.append(
                RetrievalPruningBucketStat(
                    bucket=bucket,
                    candidate_count=len(candidates),
                    selected_count=len(selected),
                    selected_bytes=selected_bytes,
                    dropped_count=len(candidates) - len(selected),
                )
            )
        raw_evidence_bytes_seen_by_llm = selected_evidence_bytes
        pruning_gain_bytes = max(full_corpus_bytes - raw_evidence_bytes_seen_by_llm, 0)
        return RetrievalPruningProfile(
            task_id=task_id,
            full_corpus_bytes=full_corpus_bytes,
            selected_evidence_bytes=selected_evidence_bytes,
            raw_evidence_bytes_seen_by_llm=raw_evidence_bytes_seen_by_llm,
            pruning_gain_bytes=pruning_gain_bytes,
            selected_candidate_ids=tuple(sorted(selected_candidate_ids)),
            bucket_stats=tuple(bucket_stats),
        )

    def _run_artifact_history_lineage(
        self,
        *,
        task_id: str,
        spec: CanonicalTaskSpec,
        normalized_scope: dict[str, object],
        query_text: str,
    ) -> RetrievalBundle:
        history_items = [
            str(item).strip()
            for item in normalized_scope.get("history_artifact_summaries", [])
            if str(item).strip()
        ]
        lineage_items = [
            str(item).strip()
            for item in spec.arguments.get("required_lineage", [])
            if str(item).strip()
        ]
        source_doc_hash = f"sha256:artifact-lineage-{task_id}"
        lexical_candidates = tuple(
            EvidenceCandidate(
                item_id=f"hint-lineage-{index + 1}",
                bucket="lexical_hint",
                locator=None,
                rendered_text=f"Lineage requirement: {item}.",
                source_name="artifact_history",
                rank=index + 1,
                metadata={"lineage_ref": item},
            )
            for index, item in enumerate(lineage_items[:4])
        )
        structured_candidates = tuple(
            EvidenceCandidate(
                item_id=f"artifact-history-{index + 1}",
                bucket="structured_evidence",
                locator=None,
                rendered_text=item,
                source_name="artifact_history",
                rank=index + 1,
                metadata={"source_doc_hash": source_doc_hash},
            )
            for index, item in enumerate(history_items[:8])
        )
        lexical = RetrieverOutput(
            retriever_kind=RetrieverKind.LEXICAL_METADATA,
            candidates=tuple(candidate.__dict__ for candidate in lexical_candidates),
            log_entry=RetrievalLogEntry(
                retriever_kind=RetrieverKind.LEXICAL_METADATA,
                candidate_count=len(lineage_items),
                selected_count=len(lexical_candidates),
                selected_ids=tuple(candidate.item_id for candidate in lexical_candidates),
                diagnostics={"source": "artifact_history_lineage"},
            ),
        )
        semantic = RetrieverOutput(
            retriever_kind=RetrieverKind.SEMANTIC_CHUNK,
            candidates=(),
            query_embedding=self.semantic_retriever.encoder.encode(
                embedding_id=f"embedding-query-artifact-lineage-{task_id}",
                text=" ".join([query_text, *history_items, *lineage_items]),
            ),
            log_entry=RetrievalLogEntry(
                retriever_kind=RetrieverKind.SEMANTIC_CHUNK,
                candidate_count=len(history_items),
                selected_count=0,
                selected_ids=(),
                diagnostics={"source": "artifact_history_lineage"},
            ),
        )
        table = RetrieverOutput(
            retriever_kind=RetrieverKind.TABLE_STRUCTURE,
            candidates=tuple(candidate.__dict__ for candidate in structured_candidates),
            log_entry=RetrievalLogEntry(
                retriever_kind=RetrieverKind.TABLE_STRUCTURE,
                candidate_count=len(history_items),
                selected_count=len(structured_candidates),
                selected_ids=tuple(candidate.item_id for candidate in structured_candidates),
                diagnostics={"source": "artifact_history_lineage"},
            ),
        )
        candidate_pool = self._build_candidate_pool(
            task_id=task_id,
            query_text=query_text,
            planner_scope_payload=normalized_scope,
            lexical_candidates=lexical_candidates,
            semantic_candidates=(),
            table_candidates=(),
        )
        candidate_pool = RetrievalCandidatePool(
            task_id=candidate_pool.task_id,
            query_text=candidate_pool.query_text,
            candidates=(
                *candidate_pool.candidates,
                *(
                    RetrievalCandidateRecord(
                        candidate_id=candidate.item_id,
                        retriever_kind=RetrieverKind.TABLE_STRUCTURE,
                        bucket=candidate.bucket,
                        rendered_text=candidate.rendered_text,
                        source_name=candidate.source_name,
                        rank=candidate.rank,
                        score=1.0 / max(candidate.rank, 1),
                        metadata=dict(candidate.metadata),
                    )
                    for candidate in structured_candidates
                ),
            ),
            planner_scope_payload=candidate_pool.planner_scope_payload,
        )
        evidence_pack = CanonicalEvidencePack(
            pack_id=f"pack-{task_id}",
            task_id=task_id,
            source_doc_hashes=(source_doc_hash,),
            structured_evidence=tuple(
                self.fan_in_builder._dedupe_stable(list(structured_candidates))
            ),
            lexical_hints=tuple(self.fan_in_builder._dedupe_stable(list(lexical_candidates))),
            budget_meta={
                "retriever_count": 3,
                "task_family": spec.task_family,
                "history_artifact_summary_count": len(history_items),
            },
        )
        selected_candidate_ids = {
            item.item_id
            for item in (*evidence_pack.structured_evidence, *evidence_pack.lexical_hints)
        }
        rerank_result = self._rerank_candidate_pool(
            task_id=task_id,
            candidate_pool=candidate_pool,
            selected_candidate_ids=selected_candidate_ids,
        )
        selected_evidence_bytes = sum(len(item.rendered_text.encode("utf-8")) for item in structured_candidates)
        full_corpus_bytes = selected_evidence_bytes + sum(len(item.encode("utf-8")) for item in lineage_items)
        pruning_profile = self._build_pruning_profile(
            task_id=task_id,
            candidate_pool=candidate_pool,
            selected_candidate_ids=selected_candidate_ids,
            full_corpus_bytes=full_corpus_bytes,
            selected_evidence_bytes=selected_evidence_bytes,
        )
        hydrate_manifest = HydrateManifest(
            manifest_id=f"manifest-{task_id}",
            source_doc_hashes=(source_doc_hash,),
            entries=(),
            canonicalizer_version="canon-v1",
            extractor_version="artifact-history-v1",
        )
        if semantic.query_embedding is None:
            raise RuntimeError("semantic retriever must emit query embedding")
        return RetrievalBundle(
            task_id=task_id,
            query_text=query_text,
            outputs=(lexical, semantic, table),
            candidate_pool=candidate_pool,
            rerank_result=rerank_result,
            pruning_profile=pruning_profile,
            evidence_pack=evidence_pack,
            hydrate_manifest=hydrate_manifest,
            query_embedding=semantic.query_embedding,
            selected_doc_hashes=(source_doc_hash,),
            full_corpus_bytes=full_corpus_bytes,
            selected_evidence_bytes=selected_evidence_bytes,
            planner_scope_payload=normalized_scope,
        )

    def run(
        self,
        *,
        task_id: str,
        spec: CanonicalTaskSpec,
        planner_scope_payload: dict[str, object] | None = None,
    ) -> RetrievalBundle:
        normalized_scope = self._normalize_planner_scope(
            spec=spec,
            planner_scope_payload=planner_scope_payload,
        )
        query_text = str(normalized_scope.get("query_text", "")).strip()
        if spec.task_family == "continuous_csv_table_analysis" and spec.intent_op == "summarize_reuse_lineage":
            return self._run_artifact_history_lineage(
                task_id=task_id,
                spec=spec,
                normalized_scope=normalized_scope,
                query_text=query_text,
            )
        if spec.task_family == "continuous_csv_table_analysis":
            dataset_id = str(spec.arguments.get("dataset_id", "")).strip()
            csv_path = str(spec.arguments.get("csv_path", "")).strip()
            document = self.csv_corpus.resolve(dataset_id=dataset_id, csv_path=csv_path)
        elif spec.task_family == "continuous_long_doc_table_analysis":
            dataset_id = str(spec.arguments.get("dataset_id", "")).strip()
            document_path = str(spec.arguments.get("document_path", "")).strip()
            if not document_path:
                document_path = "v2/benchmark/samples/continuous_task_families/long_doc_table/acme_ops_report_2026.md"
            document = self.long_doc_corpus.resolve(dataset_id=dataset_id, document_path=document_path)
        else:
            ticker = str(spec.arguments.get("ticker", "ACME"))
            quarter = str(spec.arguments.get("quarter", "2026Q1"))
            document = self.corpus.resolve(ticker=ticker, quarter=quarter)
        lexical = self.lexical_retriever.retrieve(spec=spec, document=document)
        semantic = self.semantic_retriever.retrieve(spec=spec, document=document)
        table = self.table_retriever.retrieve(spec=spec, document=document)

        lexical_candidates = tuple(
            EvidenceCandidate(**candidate) for candidate in lexical.candidates
        )
        semantic_candidates = tuple(
            EvidenceCandidate(**candidate) for candidate in semantic.candidates
        )
        table_candidates = tuple(
            EvidenceCandidate(**candidate) for candidate in table.candidates
        )
        lexical_candidates, semantic_candidates, table_candidates = self._filter_candidates_by_planner_scope(
            lexical_candidates=lexical_candidates,
            semantic_candidates=semantic_candidates,
            table_candidates=table_candidates,
            planner_scope_payload=normalized_scope,
        )
        candidate_pool = self._build_candidate_pool(
            task_id=task_id,
            query_text=query_text,
            planner_scope_payload=normalized_scope,
            lexical_candidates=lexical_candidates,
            semantic_candidates=semantic_candidates,
            table_candidates=table_candidates,
        )

        evidence_pack = self.fan_in_builder.build(
            pack_id=f"pack-{task_id}",
            task_id=task_id,
            hard_facts=list(table_candidates),
            text_candidates=list(semantic_candidates),
            hint_candidates=list(lexical_candidates),
            budget_meta={"retriever_count": 3, "task_family": spec.task_family},
        )
        selected_candidate_ids = {
            item.item_id
            for item in (
                *evidence_pack.hard_facts,
                *evidence_pack.structured_evidence,
                *evidence_pack.semantic_contexts,
                *evidence_pack.lexical_hints,
            )
        }
        rerank_result = self._rerank_candidate_pool(
            task_id=task_id,
            candidate_pool=candidate_pool,
            selected_candidate_ids=selected_candidate_ids,
        )
        manifest_entries = tuple(
            HydrateManifestEntry(
                row_idx=index,
                stable_key=_stable_entry_key(candidate),
                byte_hint=len(candidate.rendered_text.encode("utf-8")),
                locator=candidate.locator,
            )
            for index, candidate in enumerate(
                [candidate for candidate in (*semantic_candidates, *table_candidates) if candidate.locator is not None]
            )
        )
        hydrate_manifest = HydrateManifest(
            manifest_id=f"manifest-{task_id}",
            source_doc_hashes=(document.source_doc_hash,),
            entries=manifest_entries,
            canonicalizer_version="canon-v1",
            extractor_version="retriever-fanout-v1",
        )
        selected_evidence_bytes = sum(len(candidate.rendered_text.encode("utf-8")) for candidate in semantic_candidates) + sum(
            len(candidate.rendered_text.encode("utf-8")) for candidate in table_candidates
        )
        pruning_profile = self._build_pruning_profile(
            task_id=task_id,
            candidate_pool=candidate_pool,
            selected_candidate_ids=selected_candidate_ids,
            full_corpus_bytes=document.full_corpus_bytes,
            selected_evidence_bytes=selected_evidence_bytes,
        )
        if semantic.query_embedding is None:
            raise RuntimeError("semantic retriever must emit query embedding")
        return RetrievalBundle(
            task_id=task_id,
            query_text=query_text,
            outputs=(lexical, semantic, table),
            candidate_pool=candidate_pool,
            rerank_result=rerank_result,
            pruning_profile=pruning_profile,
            evidence_pack=evidence_pack,
            hydrate_manifest=hydrate_manifest,
            query_embedding=semantic.query_embedding,
            selected_doc_hashes=(document.source_doc_hash,),
            full_corpus_bytes=document.full_corpus_bytes,
            selected_evidence_bytes=selected_evidence_bytes,
            planner_scope_payload=normalized_scope,
        )
