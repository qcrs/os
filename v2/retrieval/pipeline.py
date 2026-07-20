from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import ceil
from pathlib import Path
from typing import Callable

from v2.contracts import (
    CanonicalTaskSpec,
    EvidenceCoverageReport,
    EvidenceCoverageStatus,
    EvidenceRequest,
)
from v2.memory import DeterministicEmbeddingEncoder, EmbeddingEncoder, build_embedding_encoder
from v2.memory.embedding import cosine_similarity as _cosine_sim
from v2.provenance import DeterministicFanInBuilder, EvidenceCandidate
from v2.refs import CanonicalEvidencePack, EvidenceItem, HydrateManifest, HydrateManifestEntry
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
from v2.utils import sha256_digest
from v2.runtime.evidence_coverage import EvidenceCoverageVerifier, validate_evidence_request


PRUNING_IMPORTANCE_THRESHOLD = 0.6
KV_ESTIMATE_BYTES_PER_TOKEN = 4


@dataclass(frozen=True)
class MultiQueryRetrievalResult:
    query_hashes: tuple[str, ...]
    bundles: tuple[RetrievalBundle, ...]
    evidence_pack: CanonicalEvidencePack


@dataclass(frozen=True)
class BoundedRetrievalDecision:
    decision: str
    expansion_index: int
    before_status: EvidenceCoverageStatus
    after_status: EvidenceCoverageStatus
    before_candidate_count: int
    after_candidate_count: int
    missing_evidence_types: tuple[str, ...]
    query_hashes: tuple[str, ...]

    def canonical_payload(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "expansion_index": self.expansion_index,
            "before_status": self.before_status.value,
            "after_status": self.after_status.value,
            "before_candidate_count": self.before_candidate_count,
            "after_candidate_count": self.after_candidate_count,
            "missing_evidence_types": list(self.missing_evidence_types),
            "query_hashes": list(self.query_hashes),
        }


@dataclass(frozen=True)
class BoundedRetrievalResult:
    request: EvidenceRequest
    bundles: tuple[RetrievalBundle, ...]
    evidence_pack: CanonicalEvidencePack
    query_hashes: tuple[str, ...]
    coverage_reports: tuple[EvidenceCoverageReport, ...]
    decisions: tuple[BoundedRetrievalDecision, ...]


def _consumed_retrieval_objectives(
    planner_scope_payload: dict[str, object],
    *,
    fallback_query_text: str,
) -> dict[str, dict[str, object]]:
    semantic_plan = planner_scope_payload.get("semantic_task_plan", {})
    semantic_plan = semantic_plan if isinstance(semantic_plan, dict) else {}
    raw_objectives = semantic_plan.get("retrieval_objectives", {})
    raw_objectives = raw_objectives if isinstance(raw_objectives, dict) else {}
    result: dict[str, dict[str, object]] = {}
    defaults = {
        "lexical_metadata": ("lexical_metadata",),
        "semantic_chunk": ("semantic_context",),
        "table_structure": ("table_cell", "table_schema"),
        "memory": ("memory_artifact", "memory_strategy"),
    }
    for name, evidence_types in defaults.items():
        raw = raw_objectives.get(name, {})
        objective = dict(raw) if isinstance(raw, dict) else {}
        objective["query_text"] = str(objective.get("query_text", "")).strip() or fallback_query_text
        objective["objective"] = str(objective.get("objective", "")).strip() or f"retrieve {name} evidence"
        raw_evidence = objective.get("evidence_types", [])
        objective["evidence_types"] = (
            [str(item).strip() for item in raw_evidence if str(item).strip()]
            if isinstance(raw_evidence, (list, tuple))
            else list(evidence_types)
        )
        if name == "memory":
            objective["reuse_intent"] = str(objective.get("reuse_intent", "assist")).strip() or "assist"
        result[name] = objective
    return result


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
        objective: dict[str, object] | None = None,
    ) -> RetrieverOutput:
        objective = dict(objective or {})
        objective_query = str(objective.get("query_text", "")).strip()
        ticker = str(spec.arguments.get("ticker", getattr(document, "ticker", "")))
        quarter = str(spec.arguments.get("quarter", getattr(document, "quarter", "")))
        dataset_id = str(spec.arguments.get("dataset_id", getattr(document, "dataset_id", "")))
        metadata_hints = list(document.metadata_hints)
        query_tokens = set(objective_query.casefold().replace("_", " ").split())
        if query_tokens:
            metadata_hints.sort(
                key=lambda hint: (
                    -len(query_tokens & set(str(hint).casefold().replace("_", " ").split())),
                    str(hint),
                )
            )
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
            for index, hint in enumerate(metadata_hints[:2])
        )
        return RetrieverOutput(
            retriever_kind=RetrieverKind.LEXICAL_METADATA,
            candidates=tuple(candidate.__dict__ for candidate in hints),
            log_entry=RetrievalLogEntry(
                retriever_kind=RetrieverKind.LEXICAL_METADATA,
                candidate_count=len(document.metadata_hints),
                selected_count=len(hints),
                selected_ids=tuple(candidate.item_id for candidate in hints),
                diagnostics={
                    "title": document.title,
                    "consumed_objective_hash": sha256_digest(objective),
                    "objective_query_hash": sha256_digest(objective_query) if objective_query else "",
                },
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
        objective: dict[str, object] | None = None,
    ) -> RetrieverOutput:
        objective = dict(objective or {})
        doc_identity = getattr(document, "ticker", getattr(document, "dataset_id", "dataset"))
        doc_scope = getattr(document, "quarter", Path(getattr(document, "csv_path", "")).name or "scope")
        fallback_query_text = (
            f"{spec.task_family} {spec.intent_op} "
            f"{spec.arguments.get('ticker', doc_identity)} "
            f"{spec.arguments.get('quarter', doc_scope)}"
        )
        query_text = str(objective.get("query_text", "")).strip() or fallback_query_text
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
            scored.append((score, fragment, fragment_embedding))
        scored.sort(key=lambda item: (-item[0], item[1].fragment_id))
        ranked_candidates = tuple(
            EvidenceCandidate(
                item_id=f"ctx-{fragment.fragment_id}",
                bucket="semantic_context",
                locator=fragment.locator(),
                rendered_text=fragment.text,
                source_name="semantic",
                rank=index + 1,
                metadata={"score": round(score, 6)},
            )
            for index, (score, fragment, _embedding) in enumerate(scored)
        )
        candidate_embeddings = tuple(
            (f"ctx-{fragment.fragment_id}", embedding)
            for _score, fragment, embedding in scored
        )
        selected = ranked_candidates[: self.top_k]
        return RetrieverOutput(
            retriever_kind=RetrieverKind.SEMANTIC_CHUNK,
            # Publish the complete ranked candidate surface. The Runtime's
            # cross-process semantic consumer, not this producer, owns the
            # authoritative top-k decision and downstream hydration.
            candidates=tuple(candidate.__dict__ for candidate in ranked_candidates),
            query_embedding=query_embedding,
            candidate_embeddings=candidate_embeddings,
            log_entry=RetrievalLogEntry(
                retriever_kind=RetrieverKind.SEMANTIC_CHUNK,
                candidate_count=len(document.text_fragments),
                selected_count=len(selected),
                selected_ids=tuple(candidate.item_id for candidate in selected),
                diagnostics={
                    "top_k": self.top_k,
                    "consumed_objective_hash": sha256_digest(objective),
                    "objective_query_hash": sha256_digest(query_text),
                },
            ),
        )


@dataclass(frozen=True)
class TableStructureRetriever:
    def retrieve(
        self,
        *,
        spec: CanonicalTaskSpec,
        document: FinancialReportDocument | CsvTableDocument | IncidentLogDocument,
        objective: dict[str, object] | None = None,
    ) -> RetrieverOutput:
        objective = dict(objective or {})
        objective_query = str(objective.get("query_text", "")).strip()
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
            normalized_metric = requested_metric.strip().lower().replace(" ", "_")

            def metric_matches(row_metric_name: str) -> bool:
                # Markdown-table extraction carries the period as a suffix
                # (for example ``revenue_musd:2026Q1``).  Match the requested
                # metric family, never every table cell merely because the
                # request used a short name such as ``revenue``.
                base_name = row_metric_name.split(":", 1)[0].lower()
                return (
                    base_name == normalized_metric
                    or base_name.startswith(f"{normalized_metric}_")
                )

            rows = tuple(row for row in document.table_rows if metric_matches(row.metric_name))
        if not rows and document.table_rows:
            rows = tuple(document.table_rows[:1])
        # Table evidence is a bounded data object, not a single-answer hint.
        # Retain up to three matching rows so any approved comparison,
        # aggregation, or anomaly capability can consume the same verified
        # EvidencePack.  The controller still limits the corpus and later
        # validates rows through projection and capability-specific quality
        # gates.
        # This is Controller-owned task metadata, never an LLM retrieval
        # request field.  It lets a registered grouped-analysis task retain a
        # bounded complete table while the normal long-document path remains
        # capped at three rows.
        configured_limit = spec.arguments.get("table_row_limit", 3)
        row_limit = int(configured_limit) if isinstance(configured_limit, int) else 3
        row_limit = min(max(row_limit, 1), 16)
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
                metadata={
                    "metric_name": row.metric_name,
                    "value": row.value,
                    **dict(row.metadata),
                },
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
                diagnostics={
                    "metric": requested_metric,
                    "consumed_objective_hash": sha256_digest(objective),
                    "objective_query_hash": sha256_digest(objective_query) if objective_query else "",
                },
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
    def _enabled_retrievers(
        planner_scope_payload: dict[str, object],
    ) -> frozenset[str]:
        """Resolve the controller-selected document retrievers.

        ``memory_*`` evidence types intentionally do not enable a document
        fan-out path; MemoryProxy owns that plane.  An absent selector keeps
        the historical all-three default for strict callers.
        """
        explicit = planner_scope_payload.get("enabled_evidence_types")
        if isinstance(explicit, (list, tuple, set)):
            values = {str(item).strip().lower() for item in explicit if str(item).strip()}
        else:
            semantic_plan = planner_scope_payload.get("semantic_task_plan", {})
            semantic_plan = semantic_plan if isinstance(semantic_plan, dict) else {}
            objectives = semantic_plan.get("retrieval_objectives", {})
            objectives = objectives if isinstance(objectives, dict) else {}
            values = set()
            saw_explicit = False
            for name in ("lexical_metadata", "semantic_chunk", "table_structure"):
                objective = objectives.get(name, {})
                objective = objective if isinstance(objective, dict) else {}
                raw = objective.get("evidence_types")
                if isinstance(raw, (list, tuple)) and raw:
                    saw_explicit = True
                    values.update(str(item).strip().lower() for item in raw if str(item).strip())
            if not saw_explicit:
                return frozenset({"lexical", "semantic", "table"})
        enabled: set[str] = set()
        if values & {"lexical", "lexical_metadata", "lexical_hint", "metadata", "citation"}:
            enabled.add("lexical")
        if values & {"semantic", "semantic_chunk", "semantic_context", "narrative", "citation"}:
            enabled.add("semantic")
        if values & {"table", "table_cell", "table_schema", "structured_evidence", "hard_fact"}:
            enabled.add("table")
        return frozenset(enabled)

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
        consumed_objectives = _consumed_retrieval_objectives(
            normalized_scope,
            fallback_query_text=query_text,
        )
        consumed_objective_hashes = {
            name: sha256_digest(objective)
            for name, objective in consumed_objectives.items()
        }
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
                diagnostics={
                    "source": "artifact_history_lineage",
                    "consumed_objective_hash": consumed_objective_hashes["lexical_metadata"],
                },
            ),
        )
        semantic = RetrieverOutput(
            retriever_kind=RetrieverKind.SEMANTIC_CHUNK,
            candidates=(),
            query_embedding=self.semantic_retriever.encoder.encode(
                embedding_id=f"embedding-query-artifact-lineage-{task_id}",
                text=" ".join(
                    [
                        str(consumed_objectives["semantic_chunk"]["query_text"]),
                        *history_items,
                        *lineage_items,
                    ]
                ),
            ),
            log_entry=RetrievalLogEntry(
                retriever_kind=RetrieverKind.SEMANTIC_CHUNK,
                candidate_count=len(history_items),
                selected_count=0,
                selected_ids=(),
                diagnostics={
                    "source": "artifact_history_lineage",
                    "consumed_objective_hash": consumed_objective_hashes["semantic_chunk"],
                },
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
                diagnostics={
                    "source": "artifact_history_lineage",
                    "consumed_objective_hash": consumed_objective_hashes["table_structure"],
                },
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
        memory_query_embedding = semantic.query_embedding
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
            consumed_objectives=consumed_objectives,
            consumed_objective_hashes=consumed_objective_hashes,
            memory_query_embedding=memory_query_embedding,
        )

    def run(
        self,
        *,
        task_id: str,
        spec: CanonicalTaskSpec,
        planner_scope_payload: dict[str, object] | None = None,
        enabled_evidence_types: tuple[str, ...] | None = None,
    ) -> RetrievalBundle:
        if enabled_evidence_types is not None:
            planner_scope_payload = {
                **dict(planner_scope_payload or {}),
                "enabled_evidence_types": list(enabled_evidence_types),
            }
        normalized_scope = self._normalize_planner_scope(
            spec=spec,
            planner_scope_payload=planner_scope_payload,
        )
        query_text = str(normalized_scope.get("query_text", "")).strip()
        consumed_objectives = _consumed_retrieval_objectives(
            normalized_scope,
            fallback_query_text=query_text,
        )
        consumed_objective_hashes = {
            name: sha256_digest(objective)
            for name, objective in consumed_objectives.items()
        }
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
        enabled_retrievers = self._enabled_retrievers(normalized_scope)
        if "lexical" in enabled_retrievers:
            lexical = self.lexical_retriever.retrieve(
                spec=spec,
                document=document,
                objective=consumed_objectives["lexical_metadata"],
            )
        else:
            lexical = RetrieverOutput(
                retriever_kind=RetrieverKind.LEXICAL_METADATA,
                candidates=(),
                log_entry=RetrievalLogEntry(
                    retriever_kind=RetrieverKind.LEXICAL_METADATA,
                    candidate_count=0,
                    selected_count=0,
                    selected_ids=(),
                    diagnostics={"dispatch": "disabled_by_evidence_types"},
                ),
            )
        if "semantic" in enabled_retrievers:
            semantic = self.semantic_retriever.retrieve(
                spec=spec,
                document=document,
                objective=consumed_objectives["semantic_chunk"],
            )
        else:
            semantic = RetrieverOutput(
                retriever_kind=RetrieverKind.SEMANTIC_CHUNK,
                candidates=(),
                query_embedding=None,
                candidate_embeddings=(),
                log_entry=RetrievalLogEntry(
                    retriever_kind=RetrieverKind.SEMANTIC_CHUNK,
                    candidate_count=0,
                    selected_count=0,
                    selected_ids=(),
                    diagnostics={"dispatch": "disabled_by_evidence_types"},
                ),
            )
        if "table" in enabled_retrievers:
            table = self.table_retriever.retrieve(
                spec=spec,
                document=document,
                objective=consumed_objectives["table_structure"],
            )
        else:
            table = RetrieverOutput(
                retriever_kind=RetrieverKind.TABLE_STRUCTURE,
                candidates=(),
                log_entry=RetrievalLogEntry(
                    retriever_kind=RetrieverKind.TABLE_STRUCTURE,
                    candidate_count=0,
                    selected_count=0,
                    selected_ids=(),
                    diagnostics={"dispatch": "disabled_by_evidence_types"},
                ),
            )

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
        producer_selected_semantic_ids = set(semantic.log_entry.selected_ids)
        producer_selected_semantic_candidates = tuple(
            candidate
            for candidate in semantic_candidates
            if candidate.item_id in producer_selected_semantic_ids
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
            # This is only the in-process reference pack. The complete
            # semantic candidate surface is carried below in the binary state
            # manifest, and the consumer's selected IDs replace this slice.
            text_candidates=list(producer_selected_semantic_candidates),
            hint_candidates=list(lexical_candidates),
            budget_meta={
                "retriever_count": len(enabled_retrievers),
                "enabled_retrievers": sorted(enabled_retrievers),
                "task_family": spec.task_family,
            },
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
                candidate_id=candidate.item_id,
                bucket=candidate.bucket,
                importance_score=float(candidate.metadata.get("score", 0.0)),
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
        semantic_embedding_by_id = dict(semantic.candidate_embeddings)
        semantic_manifest_entries = tuple(
            HydrateManifestEntry(
                row_idx=index,
                stable_key=_stable_entry_key(candidate),
                byte_hint=len(candidate.rendered_text.encode("utf-8")),
                candidate_id=candidate.item_id,
                bucket=candidate.bucket,
                importance_score=float(candidate.metadata.get("score", 0.0)),
                locator=candidate.locator,
            )
            for index, candidate in enumerate(
                (
                    candidate
                    for candidate in semantic_candidates
                    if candidate.locator is not None
                    and candidate.item_id in semantic_embedding_by_id
                ),
                start=1,
            )
        )
        semantic_state_manifest = (
            HydrateManifest(
                manifest_id=f"semantic-manifest-{task_id}",
                source_doc_hashes=(document.source_doc_hash,),
                entries=semantic_manifest_entries,
                canonicalizer_version="canon-v1",
                extractor_version="retriever-fanout-v1",
            )
            if semantic_manifest_entries
            else None
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
        # MemoryProxy still needs a query vector when semantic document
        # retrieval is disabled.  Encode that control-plane query directly;
        # no semantic candidate matrix/state is produced in this branch.
        memory_query_embedding = semantic.query_embedding
        if memory_query_embedding is None:
            memory_query_embedding = self.semantic_retriever.encoder.encode(
                embedding_id=f"embedding-query-{task_id}",
                text=query_text,
            )
        query_embedding = semantic.query_embedding or memory_query_embedding
        semantic_candidate_ids = {
            entry.candidate_id for entry in semantic_manifest_entries
        }
        return RetrievalBundle(
            task_id=task_id,
            query_text=query_text,
            outputs=(lexical, semantic, table),
            candidate_pool=candidate_pool,
            rerank_result=rerank_result,
            pruning_profile=pruning_profile,
            evidence_pack=evidence_pack,
            hydrate_manifest=hydrate_manifest,
            query_embedding=query_embedding,
            selected_doc_hashes=(document.source_doc_hash,),
            full_corpus_bytes=document.full_corpus_bytes,
            selected_evidence_bytes=selected_evidence_bytes,
            planner_scope_payload=normalized_scope,
            consumed_objectives=consumed_objectives,
            consumed_objective_hashes=consumed_objective_hashes,
            memory_query_embedding=memory_query_embedding,
            semantic_state_manifest=semantic_state_manifest,
            semantic_candidate_embeddings=tuple(
                (candidate_id, embedding)
                for candidate_id, embedding in semantic.candidate_embeddings
                if candidate_id in semantic_candidate_ids
            ),
        )

    def run_multi_query(
        self,
        *,
        task_id: str,
        spec: CanonicalTaskSpec,
        query_texts: tuple[str, ...],
        planner_scope_payload: dict[str, object] | None = None,
        enabled_evidence_types: tuple[str, ...] | None = None,
    ) -> MultiQueryRetrievalResult:
        """Run at most three approved queries and merge evidence deterministically without changing `run()`."""
        normalized_queries = tuple(query.strip() for query in query_texts if query.strip())
        if not 1 <= len(normalized_queries) <= 3:
            raise ValueError("adaptive_multi_query_count_out_of_bounds")
        if len(set(query.lower() for query in normalized_queries)) != len(normalized_queries):
            raise ValueError("adaptive_multi_query_duplicate")
        bundles: list[RetrievalBundle] = []
        for index, query in enumerate(normalized_queries):
            scope = dict(planner_scope_payload or {})
            semantic_plan = scope.get("semantic_task_plan", {})
            semantic_plan = dict(semantic_plan) if isinstance(semantic_plan, dict) else {}
            objectives = semantic_plan.get("retrieval_objectives", {})
            objectives = dict(objectives) if isinstance(objectives, dict) else {}
            for objective_name in ("lexical_metadata", "semantic_chunk", "table_structure", "memory"):
                objective = objectives.get(objective_name, {})
                objective = dict(objective) if isinstance(objective, dict) else {}
                objective["query_text"] = query
                objectives[objective_name] = objective
            semantic_plan["retrieval_objectives"] = objectives
            scope["semantic_task_plan"] = semantic_plan
            scope["query_text"] = query
            bundles.append(
                self.run(
                    task_id=f"{task_id}-q{index + 1}",
                    spec=spec,
                    planner_scope_payload=scope,
                    enabled_evidence_types=enabled_evidence_types,
                )
            )
        return MultiQueryRetrievalResult(
            query_hashes=tuple(sha256_digest(query.lower()) for query in normalized_queries),
            bundles=tuple(bundles),
            evidence_pack=self._stable_fan_in_packs(task_id=task_id, packs=tuple(bundle.evidence_pack for bundle in bundles)),
        )

    def run_bounded_evidence_request(
        self,
        *,
        request: EvidenceRequest,
        spec: CanonicalTaskSpec,
        allowed_corpus_scope_ids: tuple[str, ...],
        planner_scope_payload: dict[str, object] | None = None,
        propose_expansion: Callable[[EvidenceCoverageReport], EvidenceRequest | None] | None = None,
        verifier: EvidenceCoverageVerifier | None = None,
        max_expansions: int = 1,
        decision_sink: Callable[[BoundedRetrievalDecision], None] | None = None,
    ) -> BoundedRetrievalResult:
        """Run registered fan-out for an approved request and allow one controller-owned retry.

        The optional callback produces an untrusted *candidate* request only. This
        method validates its scope and query hashes before it can reach any corpus,
        then computes coverage exclusively from the resulting canonical pack.
        """
        if max_expansions not in {0, 1}:
            raise ValueError("max_expansions_must_be_zero_or_one")
        validate_evidence_request(request, allowed_corpus_scope_ids=allowed_corpus_scope_ids)
        verifier = verifier or EvidenceCoverageVerifier()
        initial = self.run_multi_query(
            task_id=request.task_id,
            spec=spec,
            query_texts=request.queries,
            planner_scope_payload=planner_scope_payload,
            enabled_evidence_types=tuple(request.evidence_types),
        )
        initial_report = verifier.evaluate(initial.evidence_pack, request)
        reports = [initial_report]
        decisions: list[BoundedRetrievalDecision] = []

        def finish(
            *,
            decision: str,
            expansion_index: int,
            evidence_pack: CanonicalEvidencePack,
            query_hashes: tuple[str, ...],
            bundles: tuple[RetrievalBundle, ...],
            after_report: EvidenceCoverageReport,
        ) -> BoundedRetrievalResult:
            record = BoundedRetrievalDecision(
                decision=decision,
                expansion_index=expansion_index,
                before_status=initial_report.status,
                after_status=after_report.status,
                before_candidate_count=self._evidence_item_count(initial.evidence_pack),
                after_candidate_count=self._evidence_item_count(evidence_pack),
                missing_evidence_types=after_report.missing_evidence_types,
                query_hashes=query_hashes,
            )
            decisions.append(record)
            if decision_sink is not None:
                decision_sink(record)
            return BoundedRetrievalResult(
                request=request,
                bundles=bundles,
                evidence_pack=evidence_pack,
                query_hashes=query_hashes,
                coverage_reports=tuple(reports),
                decisions=tuple(decisions),
            )

        if initial_report.status != EvidenceCoverageStatus.INSUFFICIENT_EVIDENCE:
            return finish(
                decision="coverage_complete_no_expansion",
                expansion_index=0,
                evidence_pack=initial.evidence_pack,
                query_hashes=initial.query_hashes,
                bundles=initial.bundles,
                after_report=initial_report,
            )
        if max_expansions == 0 or propose_expansion is None:
            return finish(
                decision="coverage_insufficient_no_expansion_authorized",
                expansion_index=0,
                evidence_pack=initial.evidence_pack,
                query_hashes=initial.query_hashes,
                bundles=initial.bundles,
                after_report=initial_report,
            )
        expansion = propose_expansion(initial_report)
        if expansion is None:
            return finish(
                decision="coverage_insufficient_expansion_not_proposed",
                expansion_index=0,
                evidence_pack=initial.evidence_pack,
                query_hashes=initial.query_hashes,
                bundles=initial.bundles,
                after_report=initial_report,
            )
        self._validate_expansion_scope(request, expansion)
        validate_evidence_request(
            expansion,
            allowed_corpus_scope_ids=allowed_corpus_scope_ids,
            previous_query_hashes=initial.query_hashes,
        )
        follow_up = self.run_multi_query(
            task_id=f"{request.task_id}-expansion-1",
            spec=spec,
            query_texts=expansion.queries,
            planner_scope_payload=planner_scope_payload,
            enabled_evidence_types=tuple(expansion.evidence_types),
        )
        merged_pack = self._stable_fan_in_packs(
            task_id=request.task_id,
            packs=(initial.evidence_pack, follow_up.evidence_pack),
        )
        final_report = verifier.evaluate(merged_pack, request)
        reports.append(final_report)
        return finish(
            decision=(
                "coverage_complete_after_single_expansion"
                if final_report.status == EvidenceCoverageStatus.COMPLETE
                else "coverage_insufficient_after_single_expansion"
            ),
            expansion_index=1,
            evidence_pack=merged_pack,
            query_hashes=initial.query_hashes + follow_up.query_hashes,
            bundles=initial.bundles + follow_up.bundles,
            after_report=final_report,
        )

    @staticmethod
    def _validate_expansion_scope(initial: EvidenceRequest, expansion: EvidenceRequest) -> None:
        if expansion.task_id != initial.task_id or expansion.step_id != initial.step_id:
            raise ValueError("expansion_request_scope_mismatch")
        if set(expansion.corpus_scope_ids) - set(initial.corpus_scope_ids):
            raise ValueError("expansion_corpus_scope_escalation")
        if set(expansion.evidence_types) != set(initial.evidence_types):
            raise ValueError("expansion_evidence_type_escalation")
        if expansion.target_entities != initial.target_entities or expansion.time_scope != initial.time_scope:
            raise ValueError("expansion_entity_or_time_scope_escalation")
        if expansion.memory_policy != initial.memory_policy:
            raise ValueError("expansion_memory_policy_escalation")

    @staticmethod
    def _evidence_item_count(pack: CanonicalEvidencePack) -> int:
        return sum(
            len(getattr(pack, bucket))
            for bucket in (
                "hard_facts",
                "structured_evidence",
                "semantic_contexts",
                "lexical_hints",
                "conflicts",
            )
        )

    @staticmethod
    def _stable_fan_in_packs(
        *, task_id: str, packs: tuple[CanonicalEvidencePack, ...],
    ) -> CanonicalEvidencePack:
        def merge(bucket_name: str):
            seen: set[tuple[str, str]] = set()
            items = []
            for pack in sorted(packs, key=lambda item: (item.pack_hash, item.pack_id)):
                for item in getattr(pack, bucket_name):
                    key = (item.item_id, repr(item.locator))
                    if key not in seen:
                        seen.add(key)
                        items.append(item)
            return tuple(sorted(items, key=lambda item: (item.rank, -item.score, item.item_id)))

        return CanonicalEvidencePack(
            pack_id=f"pack-{task_id}-multi-query", task_id=task_id,
            source_doc_hashes=tuple(sorted({doc_hash for pack in packs for doc_hash in pack.source_doc_hashes})),
            hard_facts=merge("hard_facts"), structured_evidence=merge("structured_evidence"),
            semantic_contexts=merge("semantic_contexts"), lexical_hints=merge("lexical_hints"),
            conflicts=merge("conflicts"), budget_meta={"query_count": len(packs), "fan_in": "stable"},
        )


def apply_semantic_state_selection(
    bundle: RetrievalBundle,
    *,
    selected_candidate_ids: tuple[str, ...],
    selected_scores: tuple[float, ...],
    consumer_pid: int,
) -> RetrievalBundle:
    """Make the cross-process semantic consumer's selected set authoritative."""
    if len(selected_candidate_ids) != len(selected_scores):
        raise ValueError("semantic_selection_id_score_arity_mismatch")
    if len(set(selected_candidate_ids)) != len(selected_candidate_ids):
        raise ValueError("semantic_selection_duplicate_candidate_id")
    available_ids = {
        candidate_id for candidate_id, _embedding in bundle.semantic_candidate_embeddings
    }
    if not selected_candidate_ids or not set(selected_candidate_ids) <= available_ids:
        raise ValueError("semantic_selection_candidate_outside_manifest")

    score_by_id = dict(zip(selected_candidate_ids, selected_scores, strict=True))
    rank_by_id = {
        candidate_id: index
        for index, candidate_id in enumerate(selected_candidate_ids, start=1)
    }
    semantic_output = next(
        (
            output
            for output in bundle.outputs
            if output.retriever_kind == RetrieverKind.SEMANTIC_CHUNK
        ),
        None,
    )
    if semantic_output is None:
        raise ValueError("semantic_selection_output_missing")
    candidates_by_id = {
        candidate.item_id: candidate
        for candidate in (
            EvidenceCandidate(**payload) for payload in semantic_output.candidates
        )
        if candidate.item_id in available_ids
    }
    if not set(selected_candidate_ids) <= set(candidates_by_id):
        raise ValueError("semantic_selection_hydration_candidate_missing")
    semantic_contexts = tuple(
        EvidenceItem(
            item_id=candidate.item_id,
            bucket=candidate.bucket,
            locator=candidate.locator,
            rendered_text=candidate.rendered_text,
            source_name=candidate.source_name,
            rank=rank_by_id[candidate_id],
            score=score_by_id[candidate_id],
            metadata=dict(candidate.metadata),
        )
        for candidate_id in selected_candidate_ids
        for candidate in (candidates_by_id[candidate_id],)
    )
    pack = CanonicalEvidencePack(
        pack_id=bundle.evidence_pack.pack_id,
        task_id=bundle.evidence_pack.task_id,
        source_doc_hashes=bundle.evidence_pack.source_doc_hashes,
        hard_facts=bundle.evidence_pack.hard_facts,
        structured_evidence=bundle.evidence_pack.structured_evidence,
        semantic_contexts=semantic_contexts,
        lexical_hints=bundle.evidence_pack.lexical_hints,
        conflicts=bundle.evidence_pack.conflicts,
        budget_meta={
            **bundle.evidence_pack.budget_meta,
            "semantic_selection_source": "cross_process_dense_state",
            "semantic_consumer_pid": consumer_pid,
            "semantic_selected_count": len(selected_candidate_ids),
        },
    )
    non_semantic_selected = {
        candidate_id
        for candidate_id in bundle.rerank_result.selected_candidate_ids
        if candidate_id not in available_ids
    }
    selected_set = non_semantic_selected | set(selected_candidate_ids)
    rerank_items = tuple(
        replace(
            item,
            selected=item.candidate_id in selected_set,
            fused_score=score_by_id.get(item.candidate_id, item.fused_score),
            rationale=(
                "selected_by_cross_process_dense_semantic_consumer"
                if item.candidate_id in score_by_id
                else item.rationale
            ),
        )
        for item in bundle.rerank_result.items
    )
    rerank = replace(
        bundle.rerank_result,
        selected_candidate_ids=tuple(
            item.candidate_id for item in rerank_items if item.selected
        ),
        items=rerank_items,
    )
    selected_bytes = sum(
        len(item.rendered_text.encode("utf-8"))
        for item in (
            *pack.hard_facts,
            *pack.structured_evidence,
            *pack.semantic_contexts,
            *pack.lexical_hints,
            *pack.conflicts,
        )
    )
    pruning = replace(
        bundle.pruning_profile,
        selected_evidence_bytes=selected_bytes,
        raw_evidence_bytes_seen_by_llm=selected_bytes,
        pruning_gain_bytes=max(bundle.full_corpus_bytes - selected_bytes, 0),
        selected_candidate_ids=rerank.selected_candidate_ids,
    )
    return replace(
        bundle,
        evidence_pack=pack,
        rerank_result=rerank,
        pruning_profile=pruning,
        selected_evidence_bytes=selected_bytes,
    )
