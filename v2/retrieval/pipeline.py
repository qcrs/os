from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from pathlib import Path

from v2.contracts import CanonicalTaskSpec
from v2.memory import DeterministicEmbeddingEncoder, EmbeddingEncoder, build_embedding_encoder
from v2.memory.embedding import cosine_similarity as _cosine_sim
from v2.provenance import DeterministicFanInBuilder, EvidenceCandidate
from v2.refs import CanonicalEvidencePack, HydrateManifest, HydrateManifestEntry
from v2.retrieval.pruning import (
    DynamicPruningConfig,
    DynamicPruningDecision,
    PrunableEvidenceCandidate,
    apply_dynamic_pruning,
)
from v2.retrieval.corpus import (
    CsvTableDocument,
    FinancialReportDocument,
    IncidentLogDocument,
    OfflineIncidentLogCorpus,
    OfflineMarkdownLongDocCorpus,
    OfflineCsvTableCorpus,
    OfflineFinancialReportCorpus,
)
from v2.retrieval.models import (
    EvidencePruningHint,
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


PRUNING_IMPORTANCE_THRESHOLD = 0.6
KV_ESTIMATE_BYTES_PER_TOKEN = 4


def _default_dynamic_pruning_config() -> DynamicPruningConfig:
    return DynamicPruningConfig.from_env()


def _candidate_importance_score(candidate: RetrievalCandidateRecord) -> float:
    if candidate.bucket == "hard_fact":
        return max(float(candidate.score), 1.0)
    if candidate.bucket == "semantic_context":
        return float(candidate.score)
    if candidate.bucket == "structured_evidence":
        return max(float(candidate.score), 0.8)
    if candidate.bucket == "lexical_hint":
        return max(float(candidate.score), 0.25)
    return float(candidate.score)


def _estimate_tokens_from_bytes(byte_count: int) -> int:
    if byte_count <= 0:
        return 0
    return int(ceil(byte_count / KV_ESTIMATE_BYTES_PER_TOKEN))


def _candidate_quality_guard(candidate: RetrievalCandidateRecord, keep_in_budget: bool) -> str:
    if candidate.bucket == "hard_fact":
        return "hard_fact_retained_for_quality_floor" if keep_in_budget else "hard_fact_drop_requires_validator_gate"
    if candidate.bucket == "structured_evidence":
        return "structured_evidence_retained_when_selected" if keep_in_budget else "structured_evidence_drop_requires_lineage_check"
    if candidate.bucket == "semantic_context":
        return "semantic_context_ranked_by_query_similarity"
    if candidate.bucket == "lexical_hint":
        return "lexical_hint_can_drop_after_route_or_tool_is_bound"
    if candidate.bucket == "corpus_remainder":
        return "not_hydrated_into_llm_prompt_after_retrieval_scope_selection"
    return "candidate_policy_default"


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


def _cross_period_tickers(spec: CanonicalTaskSpec) -> tuple[str, ...]:
    tickers: list[str] = []
    single = str(spec.arguments.get("ticker", "")).strip()
    if single:
        tickers.append(single.upper())
    multi = spec.arguments.get("tickers", [])
    if isinstance(multi, (list, tuple)):
        tickers.extend(str(item).strip().upper() for item in multi if str(item).strip())
    return tuple(dict.fromkeys(tickers))


def _cross_period_quarters(spec: CanonicalTaskSpec) -> tuple[str, ...]:
    quarters: list[str] = []
    single = str(spec.arguments.get("quarter", "")).strip()
    if single:
        quarters.append(single.upper())
    period_from = str(spec.arguments.get("period_from", "")).strip()
    if period_from:
        quarters.append(period_from.upper())
    period_to = str(spec.arguments.get("period_to", "")).strip()
    if period_to:
        quarters.append(period_to.upper())
    multi = spec.arguments.get("quarters", [])
    if isinstance(multi, (list, tuple)):
        quarters.extend(str(item).strip().upper() for item in multi if str(item).strip())
    return tuple(dict.fromkeys(quarters))


def _cross_period_row_matches(
    row,
    *,
    tickers: tuple[str, ...],
    quarters: tuple[str, ...],
    metric: str,
) -> bool:
    if row.metric_name != metric:
        return False
    rendered = row.rendered_text.upper()
    ticker_ok = not tickers or any(f"FOR {ticker} " in rendered for ticker in tickers)
    quarter_ok = not quarters or any(
        f" {quarter}." in rendered or f" {quarter} " in rendered
        for quarter in quarters
    )
    return ticker_ok and quarter_ok


@dataclass(frozen=True)
class LexicalMetadataRetriever:
    def retrieve(
        self,
        *,
        spec: CanonicalTaskSpec,
        document: FinancialReportDocument | CsvTableDocument | IncidentLogDocument,
    ) -> RetrieverOutput:
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
    top_k: int = 1  # increase via SemanticChunkRetriever(top_k=3) for richer evidence

    def retrieve(
        self,
        *,
        spec: CanonicalTaskSpec,
        document: FinancialReportDocument | CsvTableDocument | IncidentLogDocument,
    ) -> RetrieverOutput:
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
            score = _cosine_sim(query_embedding, fragment_embedding)
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
    def retrieve(
        self,
        *,
        spec: CanonicalTaskSpec,
        document: FinancialReportDocument | CsvTableDocument | IncidentLogDocument,
    ) -> RetrieverOutput:
        requested_metric = str(
            spec.arguments.get(
                "metric",
                spec.arguments.get(
                    "column",
                    spec.arguments.get(
                        "value_column",
                        spec.arguments.get(
                            "mean_column",
                            spec.arguments.get("max_column", spec.arguments.get("phase_hint", "revenue")),
                        ),
                    ),
                ),
            )
        )
        if spec.task_family == "cross_period_financial_analysis":
            rows = tuple(
                row
                for row in document.table_rows
                if _cross_period_row_matches(
                    row,
                    tickers=_cross_period_tickers(spec),
                    quarters=_cross_period_quarters(spec),
                    metric=requested_metric,
                )
            )
        else:
            rows = tuple(
                row
                for row in document.table_rows
                if row.metric_name == requested_metric or requested_metric in {"revenue", "storage_mount"}
            )
        if not rows and document.table_rows:
            rows = tuple(document.table_rows[:1])
        row_limit = 3 if spec.intent_op in {"compute_delta", "compute_trend"} else 1
        if spec.task_family == "cross_period_financial_analysis" and rows:
            row_limit = max(row_limit, len(rows))
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
            for index, row in enumerate(rows[:row_limit])
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
    incident_corpus: OfflineIncidentLogCorpus = field(default_factory=OfflineIncidentLogCorpus)
    long_doc_corpus: OfflineMarkdownLongDocCorpus = field(default_factory=OfflineMarkdownLongDocCorpus)
    lexical_retriever: LexicalMetadataRetriever = field(default_factory=LexicalMetadataRetriever)
    semantic_retriever: SemanticChunkRetriever = field(default_factory=SemanticChunkRetriever)
    table_retriever: TableStructureRetriever = field(default_factory=TableStructureRetriever)
    fan_in_builder: DeterministicFanInBuilder = field(default_factory=DeterministicFanInBuilder)
    dynamic_pruning_config: DynamicPruningConfig = field(default_factory=_default_dynamic_pruning_config)

    @classmethod
    def with_embedding_mode(
        cls,
        mode: str = "deterministic",
        *,
        dims: int = 16,
        model_path: str | Path | None = None,
        device: str | None = None,
        top_k: int | None = None,
    ) -> "RetrieverFanoutPipeline":
        encoder = build_embedding_encoder(
            mode,
            dims=dims,
            model_path=model_path,
            device=device,
        )
        # api/local modes use top_k=3 for richer evidence diversity;
        # deterministic stays at 1 to preserve test/benchmark determinism.
        effective_top_k = top_k if top_k is not None else (3 if mode in {"api", "local"} else 1)
        return cls(semantic_retriever=SemanticChunkRetriever(encoder=encoder, top_k=effective_top_k))

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
            request_text = str(spec.arguments.get("request_text", "")).strip()
            if request_text:
                query_text = request_text
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
        pre_pruning_selected_candidate_ids: set[str],
        full_corpus_bytes: int,
        selected_evidence_bytes: int,
        dynamic_pruning_decision: DynamicPruningDecision | None = None,
    ) -> RetrievalPruningProfile:
        bucket_map: dict[str, list[RetrievalCandidateRecord]] = {}
        for candidate in candidate_pool.candidates:
            bucket_map.setdefault(candidate.bucket, []).append(candidate)
        bucket_stats = []
        pruning_hints: list[EvidencePruningHint] = []
        applied_threshold = (
            dynamic_pruning_decision.dynamic_threshold
            if dynamic_pruning_decision is not None
            else PRUNING_IMPORTANCE_THRESHOLD
        )
        base_threshold = self.dynamic_pruning_config.base_threshold
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
            for candidate in candidates:
                rendered_text_bytes = len(candidate.rendered_text.encode("utf-8"))
                importance_score = _candidate_importance_score(candidate)
                keep_in_budget = candidate.candidate_id in selected_candidate_ids
                estimated_tokens = _estimate_tokens_from_bytes(rendered_text_bytes)
                dynamically_pruned = (
                    dynamic_pruning_decision is not None
                    and candidate.candidate_id in dynamic_pruning_decision.dropped_candidate_ids
                    and candidate.candidate_id in pre_pruning_selected_candidate_ids
                )
                pruning_hints.append(
                    EvidencePruningHint(
                        candidate_id=candidate.candidate_id,
                        bucket=candidate.bucket,
                        importance_score=round(importance_score, 6),
                        rendered_text_bytes=rendered_text_bytes,
                        keep_in_budget=keep_in_budget,
                        threshold=applied_threshold,
                        estimated_tokens=estimated_tokens,
                        estimated_kv_tokens_saved_if_dropped=0 if keep_in_budget else estimated_tokens,
                        available_kv_cache_bytes=(
                            0 if dynamic_pruning_decision is None else dynamic_pruning_decision.available_kv_cache_bytes
                        ),
                        kv_bytes_per_token=(
                            0 if dynamic_pruning_decision is None else dynamic_pruning_decision.kv_bytes_per_token
                        ),
                        dynamic_threshold=applied_threshold,
                        capacity_ratio=(
                            0.0 if dynamic_pruning_decision is None else round(dynamic_pruning_decision.capacity_ratio, 6)
                        ),
                        budget_decision=(
                            "" if dynamic_pruning_decision is None else dynamic_pruning_decision.budget_decision
                        ),
                        pruning_class=(
                            "selected_candidate"
                            if keep_in_budget
                            else ("dynamic_budget_drop" if dynamically_pruned else "candidate_drop")
                        ),
                        quality_guard=_candidate_quality_guard(candidate, keep_in_budget),
                        reason=(
                            "selected_for_budget"
                            if keep_in_budget
                            else (
                                "candidate_pruned_by_dynamic_budget"
                                if dynamically_pruned
                                else "candidate_pruned_after_fan_in_or_scope_filter"
                            )
                        ),
                    )
                )
        raw_evidence_bytes_seen_by_llm = selected_evidence_bytes
        pruning_gain_bytes = max(full_corpus_bytes - raw_evidence_bytes_seen_by_llm, 0)
        dropped_candidate_bytes = sum(
            hint.rendered_text_bytes for hint in pruning_hints if not hint.keep_in_budget
        )
        corpus_remainder_bytes = max(pruning_gain_bytes - dropped_candidate_bytes, 0)
        if corpus_remainder_bytes:
            corpus_remainder_tokens = _estimate_tokens_from_bytes(corpus_remainder_bytes)
            bucket_stats.append(
                RetrievalPruningBucketStat(
                    bucket="corpus_remainder",
                    candidate_count=1,
                    selected_count=0,
                    selected_bytes=0,
                    dropped_count=1,
                )
            )
            pruning_hints.append(
                EvidencePruningHint(
                    candidate_id="__full_corpus_remainder__",
                    bucket="corpus_remainder",
                    importance_score=0.0,
                    rendered_text_bytes=corpus_remainder_bytes,
                    keep_in_budget=False,
                    threshold=applied_threshold,
                    estimated_tokens=corpus_remainder_tokens,
                    estimated_kv_tokens_saved_if_dropped=corpus_remainder_tokens,
                    available_kv_cache_bytes=(
                        0 if dynamic_pruning_decision is None else dynamic_pruning_decision.available_kv_cache_bytes
                    ),
                    kv_bytes_per_token=(
                        0 if dynamic_pruning_decision is None else dynamic_pruning_decision.kv_bytes_per_token
                    ),
                    dynamic_threshold=applied_threshold,
                    capacity_ratio=(
                        0.0 if dynamic_pruning_decision is None else round(dynamic_pruning_decision.capacity_ratio, 6)
                    ),
                    budget_decision=(
                        "" if dynamic_pruning_decision is None else dynamic_pruning_decision.budget_decision
                    ),
                    pruning_class="corpus_remainder_drop",
                    quality_guard="not_hydrated_into_llm_prompt_after_retrieval_scope_selection",
                    reason="not_materialized_after_retriever_scope_selection",
                )
            )
            dropped_candidate_bytes += corpus_remainder_bytes
        full_corpus_tokens = _estimate_tokens_from_bytes(full_corpus_bytes)
        selected_evidence_tokens = _estimate_tokens_from_bytes(raw_evidence_bytes_seen_by_llm)
        dropped_candidate_tokens = _estimate_tokens_from_bytes(dropped_candidate_bytes)
        return RetrievalPruningProfile(
            task_id=task_id,
            full_corpus_bytes=full_corpus_bytes,
            selected_evidence_bytes=selected_evidence_bytes,
            raw_evidence_bytes_seen_by_llm=raw_evidence_bytes_seen_by_llm,
            pruning_gain_bytes=pruning_gain_bytes,
            selected_candidate_ids=tuple(sorted(selected_candidate_ids)),
            bucket_stats=tuple(sorted(bucket_stats, key=lambda item: item.bucket)),
            importance_threshold=applied_threshold,
            base_importance_threshold=base_threshold,
            dynamic_pruning_enabled=dynamic_pruning_decision is not None,
            pruning_hints=tuple(sorted(pruning_hints, key=lambda hint: hint.candidate_id)),
            full_corpus_tokens_estimate=full_corpus_tokens,
            selected_evidence_tokens_estimate=selected_evidence_tokens,
            dropped_candidate_bytes=dropped_candidate_bytes,
            dropped_candidate_tokens_estimate=dropped_candidate_tokens,
            # NOTE: estimated_kv_tokens_saved 是输入侧算术估算，不是 GPU KV cache 实测。
            # 计算方式：max(full_corpus_tokens - selected_evidence_tokens, 0)
            # 不得表述为"节省了 N 个 GPU KV cache token"
            estimated_kv_tokens_saved=max(full_corpus_tokens - selected_evidence_tokens, 0),
            pruning_gain_ratio=(
                pruning_gain_bytes / full_corpus_bytes if full_corpus_bytes > 0 else 0.0
            ),
            available_kv_cache_bytes=(
                0 if dynamic_pruning_decision is None else dynamic_pruning_decision.available_kv_cache_bytes
            ),
            kv_bytes_per_token=(
                0 if dynamic_pruning_decision is None else dynamic_pruning_decision.kv_bytes_per_token
            ),
            target_sequence_tokens_estimate=(
                0 if dynamic_pruning_decision is None else dynamic_pruning_decision.target_sequence_tokens_estimate
            ),
            capacity_ratio=(
                0.0 if dynamic_pruning_decision is None else round(dynamic_pruning_decision.capacity_ratio, 6)
            ),
            budget_decision=(
                "" if dynamic_pruning_decision is None else dynamic_pruning_decision.budget_decision
            ),
            policy_name=(
                "statebus_budget_aware_dynamic_pruning_v1"
                if dynamic_pruning_decision is not None
                else "statebus_input_level_evidence_pruning_v1"
            ),
        )

    @staticmethod
    def _selected_evidence_bytes_for_pack(evidence_pack: CanonicalEvidencePack) -> int:
        visible_buckets = (
            evidence_pack.hard_facts,
            evidence_pack.structured_evidence,
            evidence_pack.semantic_contexts,
        )
        return sum(len(item.rendered_text.encode("utf-8")) for bucket in visible_buckets for item in bucket)

    def _apply_dynamic_pruning_to_evidence_pack(
        self,
        *,
        candidate_pool: RetrievalCandidatePool,
        evidence_pack: CanonicalEvidencePack,
        selected_candidate_ids: set[str],
    ) -> tuple[CanonicalEvidencePack, set[str], DynamicPruningDecision | None]:
        config = self.dynamic_pruning_config
        if not config.enabled:
            return evidence_pack, selected_candidate_ids, None
        selected_records = [
            candidate
            for candidate in candidate_pool.candidates
            if candidate.candidate_id in selected_candidate_ids
        ]
        if not selected_records:
            return evidence_pack, selected_candidate_ids, None
        decision = apply_dynamic_pruning(
            [
                PrunableEvidenceCandidate(
                    candidate_id=candidate.candidate_id,
                    bucket=candidate.bucket,
                    importance_score=round(_candidate_importance_score(candidate), 6),
                    rendered_text_bytes=len(candidate.rendered_text.encode("utf-8")),
                )
                for candidate in selected_records
            ],
            available_kv_cache_bytes=config.available_kv_cache_bytes,
            kv_bytes_per_token=config.kv_bytes_per_token,
            base_threshold=config.base_threshold,
            capacity_buffer=config.capacity_buffer,
            protected_candidate_ids={
                candidate.candidate_id
                for candidate in selected_records
                if candidate.bucket in {"hard_fact", "structured_evidence"}
            },
            min_keep_by_bucket={
                "semantic_context": config.min_keep_semantic_contexts,
                "lexical_hint": config.min_keep_lexical_hints,
            },
        )
        kept_candidate_ids = set(decision.kept_candidate_ids)
        filtered_pack = CanonicalEvidencePack(
            pack_id=evidence_pack.pack_id,
            task_id=evidence_pack.task_id,
            source_doc_hashes=evidence_pack.source_doc_hashes,
            hard_facts=tuple(item for item in evidence_pack.hard_facts if item.item_id in kept_candidate_ids),
            structured_evidence=tuple(
                item for item in evidence_pack.structured_evidence if item.item_id in kept_candidate_ids
            ),
            semantic_contexts=tuple(
                item for item in evidence_pack.semantic_contexts if item.item_id in kept_candidate_ids
            ),
            lexical_hints=tuple(
                item for item in evidence_pack.lexical_hints if item.item_id in kept_candidate_ids
            ),
            conflicts=evidence_pack.conflicts,
            budget_meta={
                **evidence_pack.budget_meta,
                "dynamic_pruning_enabled": True,
                "dynamic_threshold": round(decision.dynamic_threshold, 6),
                "capacity_ratio": round(decision.capacity_ratio, 6),
                "budget_decision": decision.budget_decision,
                "kept_candidate_count": len(decision.kept_candidate_ids),
                "dropped_candidate_count": len(decision.dropped_candidate_ids),
            },
        )
        return filtered_pack, kept_candidate_ids, decision

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
        pre_pruning_selected_candidate_ids = set(selected_candidate_ids)
        evidence_pack, selected_candidate_ids, dynamic_pruning_decision = self._apply_dynamic_pruning_to_evidence_pack(
            candidate_pool=candidate_pool,
            evidence_pack=evidence_pack,
            selected_candidate_ids=selected_candidate_ids,
        )
        rerank_result = self._rerank_candidate_pool(
            task_id=task_id,
            candidate_pool=candidate_pool,
            selected_candidate_ids=selected_candidate_ids,
        )
        selected_evidence_bytes = self._selected_evidence_bytes_for_pack(evidence_pack)
        full_corpus_bytes = selected_evidence_bytes + sum(len(item.encode("utf-8")) for item in lineage_items)
        pruning_profile = self._build_pruning_profile(
            task_id=task_id,
            candidate_pool=candidate_pool,
            selected_candidate_ids=selected_candidate_ids,
            pre_pruning_selected_candidate_ids=pre_pruning_selected_candidate_ids,
            full_corpus_bytes=full_corpus_bytes,
            selected_evidence_bytes=selected_evidence_bytes,
            dynamic_pruning_decision=dynamic_pruning_decision,
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
        elif spec.task_family == "incident_diagnosis_v2":
            dataset_id = str(spec.arguments.get("dataset_id", "")).strip()
            log_path = str(spec.arguments.get("log_path", "")).strip()
            journal_path = str(spec.arguments.get("journal_path", "")).strip()
            service_name = str(spec.arguments.get("service_name", "")).strip()
            document = self.incident_corpus.resolve(
                dataset_id=dataset_id,
                log_path=log_path,
                journal_path=journal_path,
                service_name=service_name,
            )
        elif spec.task_family == "continuous_long_doc_table_analysis":
            dataset_id = str(spec.arguments.get("dataset_id", "")).strip()
            document_path = str(spec.arguments.get("document_path", "")).strip()
            if not document_path:
                document_path = "v2/benchmark/samples/continuous_task_families/long_doc_table/acme_ops_report_2026.md"
            document = self.long_doc_corpus.resolve(dataset_id=dataset_id, document_path=document_path)
        elif spec.task_family == "cross_period_financial_analysis":
            dataset_id = str(spec.arguments.get("dataset_id", "")).strip()
            document_path = str(spec.arguments.get("document_path", "")).strip()
            if not document_path:
                document_path = (
                    "v2/benchmark/samples/continuous_task_families/"
                    "cross_period_financial/cross_period_financial_report.md"
                )
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
        pre_pruning_selected_candidate_ids = set(selected_candidate_ids)
        evidence_pack, selected_candidate_ids, dynamic_pruning_decision = self._apply_dynamic_pruning_to_evidence_pack(
            candidate_pool=candidate_pool,
            evidence_pack=evidence_pack,
            selected_candidate_ids=selected_candidate_ids,
        )
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
        selected_evidence_bytes = self._selected_evidence_bytes_for_pack(evidence_pack)
        pruning_profile = self._build_pruning_profile(
            task_id=task_id,
            candidate_pool=candidate_pool,
            selected_candidate_ids=selected_candidate_ids,
            pre_pruning_selected_candidate_ids=pre_pruning_selected_candidate_ids,
            full_corpus_bytes=document.full_corpus_bytes,
            selected_evidence_bytes=selected_evidence_bytes,
            dynamic_pruning_decision=dynamic_pruning_decision,
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
