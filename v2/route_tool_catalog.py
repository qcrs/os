from __future__ import annotations

from dataclasses import dataclass

from v2.contracts import CanonicalTaskSpec
from v2.retrieval.models import RetrievalCandidatePool


def _dedupe_preserve_order(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(item for item in dict.fromkeys(value for value in values if value))


def _normalize_surface(text: str) -> str:
    return (
        text.lower()
        .replace("::", " ")
        .replace(".", " ")
        .replace("_", " ")
        .replace("-", " ")
        .replace("/", " ")
    )


@dataclass(frozen=True)
class RouteToolSurfaceCandidate:
    route: str
    tool_name: str
    helper_rank: int = 0
    score: float = 0.0
    support_doc_count: int = 0
    supporting_doc_ids: tuple[str, ...] = ()
    support_terms: tuple[str, ...] = ()
    matched_issue_ids: tuple[str, ...] = ()
    rationale: str = ""

    def candidate_key(self) -> str:
        return f"{self.route}::{self.tool_name}"

    def note_payload(self, *, include_helper_fields: bool = True) -> str:
        segments = [
            self.candidate_key(),
            f"support_doc_count={self.support_doc_count}",
        ]
        if include_helper_fields:
            segments.insert(1, f"helper_rank={self.helper_rank}")
            segments.insert(2, f"score={int(round(self.score * 1000))}")
        if self.support_terms:
            segments.append(f"support_terms={','.join(self.support_terms)}")
        if self.supporting_doc_ids:
            segments.append(f"support_docs={','.join(self.supporting_doc_ids)}")
        if include_helper_fields and self.matched_issue_ids:
            segments.append(f"matched_issue_ids={','.join(self.matched_issue_ids)}")
        if include_helper_fields and self.rationale:
            segments.append(f"rationale={self.rationale.replace('|', '/').replace(';', ',')}")
        return "|".join(segments)


@dataclass(frozen=True)
class RouteToolProfile:
    route: str
    tool_name: str
    issue_terms: tuple[str, ...]
    rationale: str
    bucket_preference: str

    def registry_entry_id(self) -> str:
        return f"{self.route}::{self.tool_name}"

    def registry_payload(self) -> dict[str, object]:
        return {
            "route": self.route,
            "tool_name": self.tool_name,
            "bucket_preference": self.bucket_preference,
            "issue_terms": list(self.issue_terms),
            "tool_contract_version": "statebus.route_tool_contract.v1",
            "input_schema_version": "statebus.route_tool_input.v1",
            "output_schema_version": "statebus.route_tool_output.v1",
        }


INCIDENT_ROUTE_PROFILES: tuple[RouteToolProfile, ...] = (
    RouteToolProfile(
        route="cache_replica_stale_read",
        tool_name="semantic_retriever",
        issue_terms=("cache", "replica", "lag", "stale", "failover", "read"),
        rationale="semantic incident evidence points to stale reads after replica failover",
        bucket_preference="semantic_context",
    ),
    RouteToolProfile(
        route="worker_queue_starvation",
        tool_name="semantic_retriever",
        issue_terms=("worker", "queue", "starvation", "latency", "stall", "reload"),
        rationale="semantic incident evidence points to worker saturation and queue starvation",
        bucket_preference="semantic_context",
    ),
    RouteToolProfile(
        route="auth_session_drift",
        tool_name="semantic_retriever",
        issue_terms=("auth", "session", "cookie", "issuer", "jwks", "callback"),
        rationale="semantic incident evidence points to authentication session drift",
        bucket_preference="semantic_context",
    ),
)


FINANCIAL_ROUTE_PROFILES: tuple[RouteToolProfile, ...] = (
    RouteToolProfile(
        route="compare_metric",
        tool_name="table_retriever",
        issue_terms=("compare", "metric", "revenue", "quarter", "gross", "operating"),
        rationale="table evidence is the primary source for fixed-answer financial metric comparison",
        bucket_preference="hard_fact",
    ),
    RouteToolProfile(
        route="summarize_risk",
        tool_name="semantic_retriever",
        issue_terms=("risk", "headwind", "collections", "backlog", "renewals", "channel"),
        rationale="semantic narrative evidence is the primary source for financial risk summarization",
        bucket_preference="semantic_context",
    ),
    RouteToolProfile(
        route="generate_chart",
        tool_name="table_retriever",
        issue_terms=("plot", "chart", "trend", "series", "quarterly", "visualize"),
        rationale="table evidence is the primary source for chart generation",
        bucket_preference="hard_fact",
    ),
)


CONTINUOUS_CSV_ROUTE_PROFILES: tuple[RouteToolProfile, ...] = (
    RouteToolProfile(
        route="profile_table",
        tool_name="csv_profiler",
        issue_terms=("profile", "schema", "missing", "csv", "column"),
        rationale="csv profiling is the primary capability for schema and missingness artifacts",
        bucket_preference="structured_evidence",
    ),
    RouteToolProfile(
        route="aggregate_and_extreme",
        tool_name="table_retriever",
        issue_terms=("mean", "highest", "max", "country", "year"),
        rationale="aggregations and extrema require structured table evidence plus execution",
        bucket_preference="hard_fact",
    ),
    RouteToolProfile(
        route="correlate_columns",
        tool_name="table_retriever",
        issue_terms=("pearson", "correlation", "columns"),
        rationale="column correlation relies on structured table evidence and execution",
        bucket_preference="hard_fact",
    ),
    RouteToolProfile(
        route="detect_outliers",
        tool_name="table_retriever",
        issue_terms=("outlier", "iqr", "threshold"),
        rationale="outlier detection uses structured column evidence and reusable strategy",
        bucket_preference="hard_fact",
    ),
    RouteToolProfile(
        route="materialize_clean_table",
        tool_name="artifact_writer",
        issue_terms=("cleaned", "materialize", "imputing", "remove"),
        rationale="clean table creation is an artifact-writing execution step",
        bucket_preference="structured_evidence",
    ),
    RouteToolProfile(
        route="profile_and_mean",
        tool_name="csv_profiler",
        issue_terms=("profile", "mean", "windspeed"),
        rationale="joint profile and mean uses csv profiler plus codeact execution",
        bucket_preference="structured_evidence",
    ),
    RouteToolProfile(
        route="groupby_aggregate",
        tool_name="table_retriever",
        issue_terms=("groupby", "month", "average"),
        rationale="groupby aggregation relies on table evidence and execution",
        bucket_preference="hard_fact",
    ),
    RouteToolProfile(
        route="summarize_reuse_lineage",
        tool_name="artifact_reader",
        issue_terms=("reuse", "lineage", "artifacts", "strategies"),
        rationale="reuse lineage summary reads prior artifacts and summarizes reuse",
        bucket_preference="structured_evidence",
    ),
)

CONTINUOUS_LONG_DOC_ROUTE_PROFILES: tuple[RouteToolProfile, ...] = (
    RouteToolProfile(
        route="build_semantic_index",
        tool_name="table_extractor",
        issue_terms=("ingest", "semantic", "index", "metric table", "entity", "locator"),
        rationale="long-doc bootstrap requires semantic indexing plus metric-table extraction",
        bucket_preference="structured_evidence",
    ),
    RouteToolProfile(
        route="extract_metric_series",
        tool_name="table_retriever",
        issue_terms=("retrieve", "metric", "series", "quarter", "revenue", "margin"),
        rationale="metric-series lookup should read the extracted metric table",
        bucket_preference="hard_fact",
    ),
    RouteToolProfile(
        route="extract_and_compute_metric_delta",
        tool_name="table_retriever",
        issue_terms=("compute", "delta", "growth", "expense", "quarter"),
        rationale="metric-delta rounds require structured table lookup and derived calculation",
        bucket_preference="hard_fact",
    ),
    RouteToolProfile(
        route="compare_metric_trends",
        tool_name="artifact_reader",
        issue_terms=("compare", "trend", "artifact", "revenue", "gross margin"),
        rationale="trend comparison should read prior metric artifacts instead of re-reading the full document",
        bucket_preference="structured_evidence",
    ),
    RouteToolProfile(
        route="retrieve_narrative_evidence",
        tool_name="semantic_retriever",
        issue_terms=("narrative", "evidence", "churn", "supply chain", "mitigation"),
        rationale="narrative rounds should be driven by semantic evidence rather than table-only retrieval",
        bucket_preference="semantic_context",
    ),
    RouteToolProfile(
        route="join_metrics_and_narrative",
        tool_name="artifact_reader",
        issue_terms=("combine", "metrics", "narrative", "explain", "citations"),
        rationale="joined evidence rounds should reuse trend and narrative artifacts as first-class inputs",
        bucket_preference="structured_evidence",
    ),
    RouteToolProfile(
        route="draft_risk_memo",
        tool_name="artifact_reader",
        issue_terms=("risk memo", "q4", "risk", "actions", "memo"),
        rationale="risk memo rounds should synthesize previously materialized evidence artifacts",
        bucket_preference="structured_evidence",
    ),
    RouteToolProfile(
        route="final_cited_report",
        tool_name="artifact_reader",
        issue_terms=("final report", "cited", "operations report", "artifacts"),
        rationale="final report should consume prior artifacts and preserve citation lineage",
        bucket_preference="structured_evidence",
    ),
)


def route_labels() -> tuple[str, ...]:
    return tuple(profile.route for profile in (*INCIDENT_ROUTE_PROFILES, *FINANCIAL_ROUTE_PROFILES))


def stable_tool_registry_profiles() -> tuple[RouteToolProfile, ...]:
    catalog = {
        profile.registry_entry_id(): profile
        for profile in (
            *INCIDENT_ROUTE_PROFILES,
            *FINANCIAL_ROUTE_PROFILES,
            *CONTINUOUS_CSV_ROUTE_PROFILES,
            *CONTINUOUS_LONG_DOC_ROUTE_PROFILES,
        )
    }
    return tuple(catalog[key] for key in sorted(catalog))


def select_route_profiles(spec: CanonicalTaskSpec) -> tuple[RouteToolProfile, ...]:
    intent = spec.intent_op.strip().lower()
    task_family = spec.task_family.strip().lower()
    if task_family == "continuous_csv_table_analysis":
        return CONTINUOUS_CSV_ROUTE_PROFILES
    if task_family == "continuous_long_doc_table_analysis":
        exact = tuple(profile for profile in CONTINUOUS_LONG_DOC_ROUTE_PROFILES if profile.route == intent)
        return exact or CONTINUOUS_LONG_DOC_ROUTE_PROFILES
    if intent in {"triage_route_tool", "incident_triage", "classify_route_tool"}:
        return INCIDENT_ROUTE_PROFILES
    if intent in {profile.route for profile in INCIDENT_ROUTE_PROFILES}:
        return INCIDENT_ROUTE_PROFILES
    return FINANCIAL_ROUTE_PROFILES


def build_route_tool_surface(
    spec: CanonicalTaskSpec,
    *,
    query_text: str,
    candidate_pool: RetrievalCandidatePool | None = None,
    supporting_doc_ids: tuple[str, ...] = (),
) -> tuple[RouteToolSurfaceCandidate, ...]:
    profiles = select_route_profiles(spec)
    metric = str(spec.arguments.get("metric", "revenue")).strip().lower()
    ticker = str(spec.arguments.get("ticker", "ACME")).strip()
    quarter = str(spec.arguments.get("quarter", "2026Q1")).strip()
    freeform = str(spec.arguments.get("request_text", "")).strip()
    query_surface = _normalize_surface(
        " ".join(
            part
            for part in (
                spec.task_family,
                spec.intent_op,
                metric,
                ticker,
                quarter,
                freeform,
                query_text,
            )
            if part
        )
    )
    document_ids = list(supporting_doc_ids)
    if candidate_pool is not None:
        document_ids.extend(
            str(candidate.metadata.get("source_doc_hash", "")).strip()
            for candidate in candidate_pool.candidates
            if candidate.bucket in {"hard_fact", "semantic_context"}
        )
    dedup_doc_ids = _dedupe_preserve_order(document_ids)
    visible_candidates: list[RouteToolSurfaceCandidate] = []
    for index, profile in enumerate(profiles, start=1):
        matched_terms = tuple(
            term
            for term in profile.issue_terms
            if term and _normalize_surface(term) in query_surface
        )
        support_terms = _dedupe_preserve_order(
            [
                *profile.issue_terms,
                metric,
                ticker.lower(),
                quarter.lower(),
                *query_surface.split()[:6],
            ]
        )
        bucket_scores = [
            float(candidate.score or 0.0)
            for candidate in (candidate_pool.candidates if candidate_pool is not None else ())
            if candidate.bucket == profile.bucket_preference
        ]
        score = float(len(matched_terms)) + (max(bucket_scores) if bucket_scores else 0.0)
        visible_candidates.append(
            RouteToolSurfaceCandidate(
                route=profile.route,
                tool_name=profile.tool_name,
                helper_rank=index,
                score=score,
                support_doc_count=len(dedup_doc_ids),
                supporting_doc_ids=dedup_doc_ids,
                support_terms=support_terms,
                matched_issue_ids=matched_terms,
                rationale=profile.rationale,
            )
        )
    return tuple(visible_candidates)
