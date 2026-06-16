from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import msgpack

from protocol.channels import attach_channel_metadata
from protocol.messages import PlanStep, StateRef, StepResult
from statepool.store import MMAP_FILE_STORAGE, PY_SHARED_MEMORY_STORAGE, StatePool

MIN_DIRECT_ROUTE_CONFIDENCE = 0.70
MIN_DIRECT_EVIDENCE_SIGNALS = 2
DECISION_PACKET_REQUIRED_KEYS = (
    "route",
    "tool_name",
    "route_source",
    "route_confidence",
    "route_provenance",
    "tool_candidates",
    "retrieved_doc_ids",
    "matched_signals",
    "feature_fresh_evidence_sha256",
)
CHANNEL_LAST_VALUE = "last_value"
CHANNEL_TOPIC_ACCUMULATE = "topic_accumulate"
CHANNEL_TOPIC_REPLACE = "topic_replace"
CHANNEL_EPHEMERAL = "ephemeral"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    timeout_s: float = 5.0
    route: str = "generic_triage"
    match_patterns: tuple[str, ...] = ()
    tag_hints: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    reusable_steps: tuple[str, ...] = ("retrieve", "execute")
    is_fallback: bool = False


@dataclass(frozen=True)
class ToolMatch:
    tool_name: str
    route: str
    matched_signals: tuple[str, ...]
    matched_tags: tuple[str, ...]
    score: int


@dataclass
class ToolExecutionResult:
    tool_name: str
    route: str
    actions: list[str]
    reusable_steps: list[str]
    diagnostics: dict[str, Any] = field(default_factory=dict)
    sandbox_mode: str = "subprocess"


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._routes: dict[str, str] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec
        self._routes.setdefault(spec.route, spec.name)

    def get(self, tool_name: str) -> ToolSpec:
        try:
            return self._tools[tool_name]
        except KeyError as exc:
            raise KeyError(f"unknown executor tool: {tool_name}") from exc

    def get_for_route(self, route: str) -> ToolSpec:
        tool_name = self._routes.get(route)
        if tool_name is None:
            return self.fallback()
        return self.get(tool_name)

    def maybe_get_for_route(self, route: str) -> ToolSpec | None:
        tool_name = self._routes.get(route)
        if tool_name is None:
            return None
        return self.get(tool_name)

    def fallback(self) -> ToolSpec:
        for spec in self._tools.values():
            if spec.is_fallback:
                return spec
        raise KeyError("executor tool registry is missing a fallback tool")

    def names(self) -> list[str]:
        return sorted(self._tools)

    def retrieve_candidates(
        self,
        *,
        query_text: str,
        primary_evidence_text: str,
        evidence_text: str,
        tags: list[str],
        limit: int = 3,
    ) -> list[ToolMatch]:
        normalized_tags = {tag.lower() for tag in tags if tag}
        candidates: list[ToolMatch] = []
        for spec in self._tools.values():
            if spec.is_fallback:
                continue
            primary_hits = _match_signals(primary_evidence_text, spec.match_patterns)
            query_hits = _match_signals(query_text, spec.match_patterns)
            all_hits = _match_signals(evidence_text, spec.match_patterns)
            matched_tags = tuple(
                sorted(normalized_tags & {tag.lower() for tag in spec.tag_hints})
                )
            score = (5 * len(primary_hits)) + (3 * len(query_hits)) + len(all_hits) + (2 * len(matched_tags))
            if score <= 0:
                continue
            matched_signals = tuple(dict.fromkeys([*primary_hits, *query_hits, *all_hits]))
            candidates.append(
                ToolMatch(
                    tool_name=spec.name,
                    route=spec.route,
                    matched_signals=matched_signals,
                    matched_tags=matched_tags,
                    score=score,
                )
            )
        candidates.sort(key=lambda item: (-item.score, item.tool_name))
        return candidates[:limit]

    def infer_match(
        self,
        *,
        query_text: str,
        primary_evidence_text: str,
        evidence_text: str,
        tags: list[str],
    ) -> ToolMatch:
        candidates = self.retrieve_candidates(
            query_text=query_text,
            primary_evidence_text=primary_evidence_text,
            evidence_text=evidence_text,
            tags=tags,
            limit=1,
        )
        if candidates:
            return candidates[0]
        return self.fallback_match()

    def fallback_match(self) -> ToolMatch:
        fallback = self.fallback()
        return ToolMatch(
            tool_name=fallback.name,
            route=fallback.route,
            matched_signals=(),
            matched_tags=(),
            score=0,
        )


def default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="tool.cache_invalidation_playbook",
            description="Repo-local playbook for cache invalidation and stale inventory incidents.",
            route="cache_invalidation",
            match_patterns=(
                "cache invalidation",
                "inventory aggregate",
                "aggregate invalidation",
                "invalidation hook",
                "batch sync",
                "stale inventory",
            ),
            tag_hints=("cache", "inventory", "invalidation"),
            actions=(
                "force inventory aggregate invalidation",
                "rerun post-sync invalidation hook",
                "verify cache freshness after batch sync",
            ),
        )
    )
    registry.register(
        ToolSpec(
            name="tool.db_pool_triage",
            description="Repo-local playbook for DB pool saturation and contention incidents.",
            route="db_pool_saturation",
            match_patterns=(
                "db pool saturation",
                "database pool contention",
                "connection pool",
                "slow orders query",
                "orders_created_at",
                "db wait profile",
                "sql wait",
            ),
            tag_hints=("latency", "database", "orders"),
            actions=(
                "rollback release-17",
                "create orders_created_at index",
                "check database pool sizing",
            ),
        )
    )
    registry.register(
        ToolSpec(
            name="tool.db_query_hotfix",
            description="Repo-local hotfix playbook for slow-query/index incidents inside the DB saturation route.",
            route="db_pool_saturation",
            match_patterns=(
                "slow orders query",
                "orders_created_at",
                "missing index",
                "slower query path",
            ),
            tag_hints=("latency", "database", "orders", "config"),
            actions=(
                "rollback the slower query path",
                "create the missing query index",
                "recheck the hot query latency before widening rollback",
            ),
        )
    )
    registry.register(
        ToolSpec(
            name="tool.auth_session_repair",
            description="Repo-local playbook for stale JWKS and callback session drift incidents.",
            route="auth_session_drift",
            match_patterns=(
                "stale jwks",
                "issuer mismatch",
                "session cookies",
                "callback verification",
                "session drift",
                "jwks refresh",
            ),
            tag_hints=("auth", "session", "jwks", "sso"),
            actions=(
                "refresh JWKS cache",
                "clear stale session cookies",
                "rerun callback verification",
            ),
        )
    )
    registry.register(
        ToolSpec(
            name="tool.auth_jwks_refresh",
            description="Repo-local focused playbook for JWKS refresh and callback verification drift.",
            route="auth_session_drift",
            match_patterns=(
                "stale jwks",
                "jwks refresh",
                "callback verification",
                "issuer mismatch",
            ),
            tag_hints=("auth", "jwks", "sso"),
            actions=(
                "force JWKS refresh on the canary slice",
                "rerun callback verification with fresh metadata",
                "verify issuer mismatch clears before broader session cleanup",
            ),
        )
    )
    registry.register(
        ToolSpec(
            name="tool.replica_stale_read_triage",
            description="Repo-local playbook for stale reads caused by lagging replicas after failover.",
            route="cache_replica_stale_read",
            match_patterns=(
                "read replica",
                "replica lag",
                "stale reads on the replica path",
                "reporting replica",
                "replica path",
                "failover",
            ),
            tag_hints=("cache", "inventory", "replica", "failover"),
            actions=(
                "route reads away from lagging replica",
                "verify replica catch-up after failover",
                "recheck inventory counts on writer path",
            ),
        )
    )
    registry.register(
        ToolSpec(
            name="tool.worker_queue_triage",
            description="Repo-local playbook for worker queue starvation during release-window reloads.",
            route="worker_queue_starvation",
            match_patterns=(
                "worker queue starvation",
                "worker queue stall",
                "tls certificate reload",
                "tls reload",
            ),
            tag_hints=("latency", "worker", "release-17"),
            actions=(
                "pause release-window TLS reload",
                "drain and rebalance worker queue",
                "verify worker saturation clears before DB rollback",
            ),
        )
    )
    registry.register(
        ToolSpec(
            name="tool.retry_storm_relief",
            description="Repo-local focused playbook for retry-storm relief within the worker queue route.",
            route="worker_queue_starvation",
            match_patterns=(
                "retry storm",
                "retry scheduling",
                "invoice queue backlog",
                "rebalance invoice consumers",
            ),
            tag_hints=("billing", "queue", "worker"),
            actions=(
                "pause the retry storm trigger",
                "drain the most affected worker slice",
                "rebalance consumers before widening rollback",
            ),
        )
    )
    registry.register(
        ToolSpec(
            name="tool.auth_rate_limit_triage",
            description="Repo-local playbook for overly aggressive auth rate limiting.",
            route="auth_rate_limit",
            match_patterns=(
                "rate limiter",
                "rate limiting",
                "backoff window",
                "auth rate limiter",
                "aggressive backoff",
            ),
            tag_hints=("auth", "session", "rate-limit", "sso"),
            actions=(
                "lower auth rate-limiter aggressiveness",
                "clear the affected backoff window",
                "verify login recovery after rate-limit reset",
            ),
        )
    )
    registry.register(
        ToolSpec(
            name="tool.cache_hook_repair",
            description="Repo-local focused playbook for missing aggregate invalidation hook regressions.",
            route="cache_invalidation",
            match_patterns=(
                "aggregate invalidation",
                "invalidation hook",
                "inventory aggregate key",
                "post-sync hook",
            ),
            tag_hints=("cache", "inventory", "invalidation", "config"),
            actions=(
                "repair the missing aggregate invalidation hook",
                "force the skipped aggregate key refresh",
                "rerun the post-sync validation window",
            ),
        )
    )
    registry.register(
        ToolSpec(
            name="tool.collect_more_evidence",
            description="Fallback playbook when the current evidence is still too weak.",
            timeout_s=3.0,
            route="generic_triage",
            actions=("collect more evidence",),
            reusable_steps=("retrieve",),
            is_fallback=True,
        )
    )
    return registry


def build_feature_bundle(
    *,
    query: str,
    evidence_text: str,
    tags: list[str],
    reuse_signature: str,
    reused_memory: bool,
    retrieved_hints: list[dict[str, Any]] | None = None,
    memory_prior: dict[str, Any] | None = None,
    registry: ToolRegistry | None = None,
) -> dict[str, Any]:
    normalized_query = query.strip()
    normalized_tags = sorted({str(tag).strip() for tag in tags if str(tag).strip()})
    query_text = normalized_query.lower()
    evidence_lower = evidence_text.lower()
    primary_evidence_text = evidence_lower.split("\n\n[", 1)[0]
    active_registry = registry or default_tool_registry()
    lexical_candidates = active_registry.retrieve_candidates(
        query_text=query_text,
        primary_evidence_text=primary_evidence_text,
        evidence_text=evidence_lower,
        tags=normalized_tags,
        limit=3,
    )
    selected_hint = _select_retrieved_hint(retrieved_hints or [], registry=active_registry)
    candidate_pool = list(lexical_candidates)
    baseline_lexical_match = (
        candidate_pool[0] if candidate_pool else active_registry.fallback_match()
    )
    memory_prior_match = _normalize_memory_prior(memory_prior, registry=active_registry)
    memory_prior_id = str((memory_prior or {}).get("memory_id", "")).strip()
    memory_prior_route = "" if memory_prior_match is None else memory_prior_match.route
    memory_prior_tool_name = "" if memory_prior_match is None else memory_prior_match.tool_name
    memory_prior_source_task_id = str((memory_prior or {}).get("source_task_id", "")).strip()
    memory_prior_summary = str((memory_prior or {}).get("summary", "")).strip()
    memory_prior_confidence = _parse_float_or_default(
        (memory_prior or {}).get("confidence"),
        default=0.0,
    )
    memory_prior_applied = False
    memory_candidate_reduction = 0
    if memory_prior_match is not None and candidate_pool:
        supported_by_hint = False
        if selected_hint is not None:
            hint_match_for_prior, _ = selected_hint
            supported_by_hint = (
                hint_match_for_prior.route == memory_prior_match.route
                and hint_match_for_prior.tool_name == memory_prior_match.tool_name
            )
        supported_candidates = [
            candidate
            for candidate in candidate_pool
            if candidate.route == memory_prior_match.route
            and candidate.tool_name == memory_prior_match.tool_name
        ]
        if supported_candidates and (
            supported_by_hint
            or (
                baseline_lexical_match.route == memory_prior_match.route
                and baseline_lexical_match.tool_name == memory_prior_match.tool_name
            )
        ):
            original_count = len(candidate_pool)
            candidate_pool = supported_candidates
            memory_candidate_reduction = max(0, original_count - len(candidate_pool))
            memory_prior_applied = memory_candidate_reduction > 0
    lexical_match = candidate_pool[0] if candidate_pool else active_registry.fallback_match()
    lexical_ambiguous = _has_ambiguous_tool_candidates(candidate_pool)
    hint_doc_ids: list[str] = []
    hint_route = ""
    hint_tool_name = ""
    tool_candidates: list[dict[str, Any]]
    if selected_hint is None:
        if lexical_ambiguous:
            match = active_registry.fallback_match()
            route_source = "ambiguous_candidates_abstain"
            route_provenance = ["lexical_ambiguous"]
            route_confidence = 0.0
            tool_candidates = _serialize_tool_candidates(
                selected_match=match,
                lexical_candidates=candidate_pool,
                selected_source=route_source,
            )
        elif lexical_match.score > 0 and not _match_passes_threshold(lexical_match):
            match = active_registry.fallback_match()
            route_source = "low_confidence_abstain"
            route_provenance = ["lexical_below_threshold"]
            route_confidence = 0.0
            tool_candidates = _serialize_tool_candidates(
                selected_match=match,
                lexical_candidates=candidate_pool,
                selected_source=route_source,
            )
        elif lexical_match.score > 0 and not _match_has_minimum_evidence_support(
            lexical_match,
            primary_evidence_text=primary_evidence_text,
            evidence_text=evidence_lower,
            registry=active_registry,
        ):
            match = active_registry.fallback_match()
            route_source = "low_confidence_abstain"
            route_provenance = ["lexical_thin_support"]
            route_confidence = 0.0
            tool_candidates = _serialize_tool_candidates(
                selected_match=match,
                lexical_candidates=candidate_pool,
                selected_source=route_source,
            )
        else:
            match = lexical_match
            route_source = "lexical_match" if lexical_match.score > 0 else "fallback"
            route_provenance = ["lexical"] if lexical_match.score > 0 else ["fallback"]
            route_confidence = _route_confidence_from_match(lexical_match)
            tool_candidates = _serialize_tool_candidates(
                selected_match=match,
                lexical_candidates=candidate_pool,
                selected_source=route_source,
            )
    else:
        hint_match, hint_doc_ids = selected_hint
        hint_route = hint_match.route
        hint_tool_name = hint_match.tool_name
        lexical_supported = lexical_match.score > 0 and lexical_match.route != "generic_triage"
        hint_consensus = (
            lexical_supported
            and lexical_match.route == hint_match.route
            and lexical_match.tool_name == hint_match.tool_name
        )
        if hint_consensus:
            match = lexical_match
            route_source = "hint_consensus"
            route_provenance = ["corpus_metadata", "lexical"]
            route_confidence = max(0.80, _route_confidence_from_match(lexical_match))
            tool_candidates = _serialize_tool_candidates(
                selected_match=match,
                lexical_candidates=candidate_pool,
                selected_source=route_source,
            )
        elif lexical_supported:
            if not _match_passes_threshold(lexical_match):
                match = active_registry.fallback_match()
                route_source = "low_confidence_abstain"
                route_provenance = ["lexical_below_threshold", "corpus_metadata_conflict"]
                route_confidence = 0.0
                tool_candidates = _serialize_tool_candidates(
                    selected_match=match,
                    lexical_candidates=candidate_pool,
                    selected_source=route_source,
                    extra_candidates=[(hint_match, "corpus_metadata_conflict")],
                )
            elif lexical_ambiguous:
                match = active_registry.fallback_match()
                route_source = "ambiguous_candidates_abstain"
                route_provenance = ["lexical_ambiguous", "corpus_metadata_conflict"]
                route_confidence = 0.0
                tool_candidates = _serialize_tool_candidates(
                    selected_match=match,
                    lexical_candidates=candidate_pool,
                    selected_source=route_source,
                    extra_candidates=[(hint_match, "corpus_metadata_conflict")],
                )
            elif not _match_has_minimum_evidence_support(
                lexical_match,
                primary_evidence_text=primary_evidence_text,
                evidence_text=evidence_lower,
                registry=active_registry,
            ):
                match = active_registry.fallback_match()
                route_source = "low_confidence_abstain"
                route_provenance = ["lexical_thin_support", "corpus_metadata_conflict"]
                route_confidence = 0.0
                tool_candidates = _serialize_tool_candidates(
                    selected_match=match,
                    lexical_candidates=candidate_pool,
                    selected_source=route_source,
                    extra_candidates=[(hint_match, "corpus_metadata_conflict")],
                )
            else:
                match = lexical_match
                route_source = "lexical_override"
                route_provenance = ["lexical", "corpus_metadata_conflict"]
                route_confidence = _route_confidence_from_match(lexical_match)
                tool_candidates = _serialize_tool_candidates(
                    selected_match=match,
                    lexical_candidates=candidate_pool,
                    selected_source=route_source,
                    extra_candidates=[(hint_match, "corpus_metadata_conflict")],
                )
        else:
            match = active_registry.fallback_match()
            route_source = "metadata_only_abstain"
            route_provenance = ["corpus_metadata_unverified"]
            route_confidence = 0.0
            tool_candidates = _serialize_tool_candidates(
                selected_match=match,
                lexical_candidates=[],
                selected_source=route_source,
                extra_candidates=[(hint_match, "corpus_metadata_unverified")],
            )

    query_terms = [
        token.strip(".,:;!?()[]{}")
        for token in normalized_query.lower().split()
        if len(token.strip(".,:;!?()[]{}")) >= 4
    ]
    return {
        "schema": "statebus.feature_bundle.v1",
        "route": match.route,
        "tool_name": match.tool_name,
        "query": normalized_query,
        "query_terms": sorted(dict.fromkeys(query_terms)),
        "tags": normalized_tags,
        "matched_signals": list(match.matched_signals),
        "matched_tags": list(match.matched_tags),
        "match_score": match.score,
        "route_source": route_source,
        "route_confidence": route_confidence,
        "route_provenance": route_provenance,
        "hint_doc_ids": hint_doc_ids,
        "hint_route": hint_route,
        "hint_tool_name": hint_tool_name,
        "tool_candidates": tool_candidates,
        "memory_prior_id": memory_prior_id,
        "memory_prior_route": memory_prior_route,
        "memory_prior_tool_name": memory_prior_tool_name,
        "memory_prior_source_task_id": memory_prior_source_task_id,
        "memory_prior_summary": memory_prior_summary,
        "memory_prior_confidence": memory_prior_confidence,
        "memory_prior_applied": bool(memory_prior_applied),
        "memory_candidate_count_before": len(lexical_candidates),
        "memory_candidate_count_after": len(candidate_pool),
        "memory_candidate_reduction": int(memory_candidate_reduction),
        "memory_prior_route_agreement": bool(
            memory_prior_match is not None
            and match.route == memory_prior_match.route
            and match.tool_name == memory_prior_match.tool_name
        ),
        "memory_prior_rescue": bool(
            memory_prior_applied
            and memory_candidate_reduction > 0
            and match.route != "generic_triage"
        ),
        "reuse_signature": reuse_signature,
        "reused_memory": bool(reused_memory),
        "evidence_chars": len(evidence_text),
        "evidence_lines": len([line for line in evidence_text.splitlines() if line.strip()]),
        "evidence_preview": evidence_text[:240],
        "evidence_sha256": hashlib.sha256(evidence_text.encode("utf-8")).hexdigest(),
        "_channel_schema": {
            "route": CHANNEL_LAST_VALUE,
            "tool_name": CHANNEL_LAST_VALUE,
            "route_source": CHANNEL_LAST_VALUE,
            "route_confidence": CHANNEL_LAST_VALUE,
            "route_provenance": CHANNEL_LAST_VALUE,
            "evidence_sha256": CHANNEL_LAST_VALUE,
            "hint_route": CHANNEL_LAST_VALUE,
            "hint_tool_name": CHANNEL_LAST_VALUE,
            "hint_doc_ids": CHANNEL_LAST_VALUE,
            "query": CHANNEL_LAST_VALUE,
            "query_terms": CHANNEL_TOPIC_ACCUMULATE,
            "tool_candidates": CHANNEL_TOPIC_REPLACE,
            "matched_signals": CHANNEL_TOPIC_REPLACE,
            "matched_tags": CHANNEL_TOPIC_REPLACE,
            "match_score": CHANNEL_TOPIC_REPLACE,
            "evidence_preview": CHANNEL_EPHEMERAL,
            "evidence_chars": CHANNEL_EPHEMERAL,
            "evidence_lines": CHANNEL_EPHEMERAL,
            "reused_memory": CHANNEL_LAST_VALUE,
            "reuse_signature": CHANNEL_LAST_VALUE,
            "memory_prior_id": CHANNEL_LAST_VALUE,
            "memory_prior_route": CHANNEL_LAST_VALUE,
            "memory_prior_applied": CHANNEL_LAST_VALUE,
        },
    }


def build_ranked_evidence_bundle(
    *,
    query: str,
    feature_bundle: dict[str, Any],
    ranked_docs: list[dict[str, Any]],
    retrieved_doc_ids: list[str],
    evidence_text: str,
) -> dict[str, Any]:
    return {
        "schema": "statebus.ranked_evidence_bundle.v1",
        "query": str(query).strip(),
        "route": str(feature_bundle.get("route", "")).strip(),
        "route_source": str(feature_bundle.get("route_source", "")).strip(),
        "route_confidence": float(feature_bundle.get("route_confidence", 0.0)),
        "route_provenance": [str(item) for item in feature_bundle.get("route_provenance", [])],
        "retrieved_doc_ids": [str(doc_id) for doc_id in retrieved_doc_ids if str(doc_id).strip()],
        "hint_doc_ids": [str(doc_id) for doc_id in feature_bundle.get("hint_doc_ids", [])],
        "ranked_docs": [dict(item) for item in ranked_docs if isinstance(item, dict)],
        "evidence_chars": len(evidence_text),
        "evidence_sha256": hashlib.sha256(evidence_text.encode("utf-8")).hexdigest(),
    }


def build_tool_candidate_set(feature_bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "statebus.tool_candidate_set.v1",
        "route": str(feature_bundle.get("route", "")).strip(),
        "tool_name": str(feature_bundle.get("tool_name", "")).strip(),
        "route_source": str(feature_bundle.get("route_source", "")).strip(),
        "route_confidence": float(feature_bundle.get("route_confidence", 0.0)),
        "route_provenance": [str(item) for item in feature_bundle.get("route_provenance", [])],
        "matched_signals": [str(item) for item in feature_bundle.get("matched_signals", [])],
        "matched_tags": [str(item) for item in feature_bundle.get("matched_tags", [])],
        "match_score": int(feature_bundle.get("match_score", 0)),
        "hint_doc_ids": [str(item) for item in feature_bundle.get("hint_doc_ids", [])],
        "hint_route": str(feature_bundle.get("hint_route", "")).strip(),
        "hint_tool_name": str(feature_bundle.get("hint_tool_name", "")).strip(),
        "tool_candidates": [
            dict(item)
            for item in feature_bundle.get("tool_candidates", [])
            if isinstance(item, dict)
        ],
        "memory_prior_id": str(feature_bundle.get("memory_prior_id", "")).strip(),
        "memory_prior_route": str(feature_bundle.get("memory_prior_route", "")).strip(),
        "memory_prior_tool_name": str(feature_bundle.get("memory_prior_tool_name", "")).strip(),
        "memory_prior_applied": bool(feature_bundle.get("memory_prior_applied", False)),
        "memory_candidate_reduction": int(feature_bundle.get("memory_candidate_reduction", 0)),
    }


def build_replay_eligibility_bundle(
    *,
    query: str,
    feature_bundle: dict[str, Any],
    retrieved_doc_ids: list[str],
    fresh_evidence_sha256: str,
) -> dict[str, Any]:
    route = str(feature_bundle.get("route", "")).strip()
    route_confidence = float(feature_bundle.get("route_confidence", 0.0))
    route_provenance = [str(item) for item in feature_bundle.get("route_provenance", [])]
    validated_replay_eligible = route != "generic_triage" and _is_route_replay_eligible(
        route_confidence=route_confidence,
        route_provenance=route_provenance,
        minimum_confidence=0.70,
    )
    exact_replay_eligible = bool(retrieved_doc_ids) and route != "generic_triage" and _is_route_replay_eligible(
        route_confidence=route_confidence,
        route_provenance=route_provenance,
        minimum_confidence=0.80,
    )
    return {
        "schema": "statebus.replay_eligibility_bundle.v1",
        "query": str(query).strip(),
        "route": route,
        "tool_name": str(feature_bundle.get("tool_name", "")).strip(),
        "route_source": str(feature_bundle.get("route_source", "")).strip(),
        "route_confidence": route_confidence,
        "route_provenance": route_provenance,
        "retrieved_doc_ids": [str(doc_id) for doc_id in retrieved_doc_ids if str(doc_id).strip()],
        "feature_evidence_sha256": str(feature_bundle.get("evidence_sha256", "")).strip(),
        "feature_fresh_evidence_sha256": str(fresh_evidence_sha256).strip(),
        "validated_replay_eligible": validated_replay_eligible,
        "exact_replay_eligible": exact_replay_eligible,
    }


def build_executor_decision_packet(
    *,
    query: str,
    feature_bundle: dict[str, Any],
    retrieved_doc_ids: list[str],
) -> dict[str, Any]:
    return {
        "schema": "statebus.executor_decision_packet.v1",
        "query": str(query).strip(),
        "route": str(feature_bundle.get("route", "")).strip(),
        "tool_name": str(feature_bundle.get("tool_name", "")).strip(),
        "route_source": str(feature_bundle.get("route_source", "")).strip(),
        "route_confidence": float(feature_bundle.get("route_confidence", 0.0)),
        "route_provenance": [str(item) for item in feature_bundle.get("route_provenance", [])],
        "matched_signals": [str(item) for item in feature_bundle.get("matched_signals", [])],
        "matched_tags": [str(item) for item in feature_bundle.get("matched_tags", [])],
        "match_score": int(feature_bundle.get("match_score", 0)),
        "hint_doc_ids": [str(item) for item in feature_bundle.get("hint_doc_ids", [])],
        "hint_route": str(feature_bundle.get("hint_route", "")).strip(),
        "hint_tool_name": str(feature_bundle.get("hint_tool_name", "")).strip(),
        "tool_candidates": [
            dict(item)
            for item in feature_bundle.get("tool_candidates", [])
            if isinstance(item, dict)
        ],
        "retrieved_doc_ids": [str(doc_id) for doc_id in retrieved_doc_ids if str(doc_id).strip()],
        "feature_evidence_sha256": str(feature_bundle.get("evidence_sha256", "")).strip(),
        "feature_fresh_evidence_sha256": str(
            feature_bundle.get("fresh_evidence_sha256", "")
        ).strip(),
    }


def select_tool_name(
    feature_bundle: dict[str, Any],
    *,
    registry: ToolRegistry | None = None,
) -> str:
    active_registry = registry or default_tool_registry()
    for candidate in feature_bundle.get("tool_candidates", []):
        tool_name = str(candidate.get("tool_name", "")).strip()
        if not tool_name:
            continue
        try:
            return active_registry.get(tool_name).name
        except KeyError:
            continue
    tool_name = str(feature_bundle.get("tool_name", "")).strip()
    if tool_name:
        try:
            return active_registry.get(tool_name).name
        except KeyError:
            pass
    route = str(feature_bundle.get("route", "generic_triage")).strip() or "generic_triage"
    return active_registry.get_for_route(route).name


class LightweightSubprocessRunner:
    """Best-effort subprocess isolation for host-side tool execution.

    This is intentionally a lightweight host-only fallback and is not a secure
    sandbox equivalent to nsjail or container isolation.
    """

    def __init__(
        self,
        *,
        repo_root: str | Path | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent.parent
        self.python_executable = python_executable or sys.executable

    def execute(
        self,
        *,
        tool_name: str,
        payload: dict[str, Any],
        timeout_s: float,
    ) -> ToolExecutionResult:
        with tempfile.TemporaryDirectory(prefix="statebus-tool-run-") as tmpdir:
            request_path = Path(tmpdir) / "request.json"
            response_path = Path(tmpdir) / "response.json"
            request_path.write_text(
                json.dumps(payload, ensure_ascii=True, sort_keys=True),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    self.python_executable,
                    "-m",
                    "runtime.tool_worker",
                    "--tool",
                    tool_name,
                    "--request",
                    str(request_path),
                    "--response",
                    str(response_path),
                ],
                cwd=self.repo_root,
                env=self._sandbox_env(),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
            if completed.returncode != 0:
                stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown tool failure"
                raise RuntimeError(f"{tool_name} failed in lightweight sandbox: {stderr}")
            if not response_path.exists():
                raise RuntimeError(f"{tool_name} did not write response payload")
            response = json.loads(response_path.read_text(encoding="utf-8"))
        return ToolExecutionResult(
            tool_name=str(response.get("tool_name", tool_name)),
            route=str(response.get("route", payload.get("feature_bundle", {}).get("route", "generic_triage"))),
            actions=[str(item) for item in response.get("actions", [])],
            reusable_steps=[str(item) for item in response.get("reusable_steps", [])],
            diagnostics=dict(response.get("diagnostics", {}) or {}),
            sandbox_mode=str(response.get("sandbox_mode", "subprocess")),
        )

    def _sandbox_env(self) -> dict[str, str]:
        env: dict[str, str] = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", str(self.repo_root)),
            "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
            "PYTHONNOUSERSITE": "1",
        }
        current_pythonpath = os.environ.get("PYTHONPATH", "").strip()
        repo_root = str(self.repo_root)
        env["PYTHONPATH"] = (
            repo_root if not current_pythonpath else f"{repo_root}{os.pathsep}{current_pythonpath}"
        )
        return env


def run_registered_tool(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    feature_bundle = dict(payload.get("feature_bundle", {}) or {})
    active_registry = default_tool_registry()
    tool_spec = active_registry.get(tool_name)
    route = str(feature_bundle.get("route", tool_spec.route)).strip() or tool_spec.route
    matched_signals = [str(item) for item in feature_bundle.get("matched_signals", [])]
    return {
        "tool_name": tool_spec.name,
        "route": route,
        "actions": list(tool_spec.actions),
        "reusable_steps": list(tool_spec.reusable_steps),
        "diagnostics": {
            "matched_signals": matched_signals,
            "matched_tags": [str(item) for item in feature_bundle.get("matched_tags", [])],
            "match_score": int(feature_bundle.get("match_score", 0)),
            "evidence_sha256": feature_bundle.get("evidence_sha256"),
        },
        "sandbox_mode": "subprocess",
    }


def execute_playbook_step(
    *,
    task_id: str,
    task_theme: str,
    step: PlanStep,
    statepool: StatePool,
    input_state_refs: list[StateRef],
    runner: LightweightSubprocessRunner | None = None,
    registry: ToolRegistry | None = None,
    output_storage: str | None = None,
    transfer_strategy: str = "state_ref",
    handoff_profile: str = "",
    inline_handoff_text: str = "",
) -> StepResult:
    evidence_ref = next((ref for ref in input_state_refs if ref.kind == "DENSE_EVIDENCE"), None)
    channel_snapshot_ref = next(
        (
            ref
            for ref in input_state_refs
            if ref.kind == "CHANNEL_SNAPSHOT"
            and str(ref.metadata.get("channel_name", ref.channel)).strip() == "route"
        ),
        None,
    )
    feature_ref = next((ref for ref in input_state_refs if ref.kind == "FEATURE_BUNDLE"), None)
    tool_candidate_ref = next((ref for ref in input_state_refs if ref.kind == "TOOL_CANDIDATE_SET"), None)
    decision_packet_ref = next(
        (ref for ref in input_state_refs if ref.kind == "EXECUTOR_DECISION_PACKET"),
        None,
    )
    transfer_brief_ref = next((ref for ref in input_state_refs if ref.kind == "TOOL_ARTIFACT"), None)
    execution_evidence_text = ""
    if evidence_ref is None and transfer_strategy not in {"natural_handoff_text", "inline_text_handoff", "text_whole_lane", "text_strict_pure_lane"}:
        raise ValueError(f"step {step.step_id} missing DENSE_EVIDENCE input")
    if transfer_strategy == "text_brief":
        if transfer_brief_ref is None:
            raise ValueError(f"step {step.step_id} missing transfer brief input")
        feature_bundle = _feature_bundle_from_transfer_brief(
            query_text=step.params.get("query", ""),
            evidence_text=statepool.get_text(evidence_ref),
            brief_text=statepool.get_text(transfer_brief_ref),
            registry=registry or default_tool_registry(),
        )
        feature_state_id = transfer_brief_ref.state_id
        execution_evidence_text = statepool.get_text(evidence_ref)
    elif transfer_strategy == "text_packet_minimal":
        if transfer_brief_ref is None:
            raise ValueError(f"step {step.step_id} missing text packet input")
        feature_bundle = _feature_bundle_from_text_packet(
            query_text=step.params.get("query", ""),
            evidence_text=statepool.get_text(evidence_ref),
            packet_text=statepool.get_text(transfer_brief_ref),
            registry=registry or default_tool_registry(),
        )
        feature_state_id = transfer_brief_ref.state_id
        execution_evidence_text = statepool.get_text(evidence_ref)
    elif transfer_strategy == "natural_handoff_text":
        if transfer_brief_ref is None:
            raise ValueError(f"step {step.step_id} missing natural handoff input")
        handoff_text = statepool.get_text(transfer_brief_ref)
        feature_bundle = _feature_bundle_from_natural_handoff(
            query_text=step.params.get("query", ""),
            evidence_text=handoff_text,
            handoff_text=handoff_text,
            registry=registry or default_tool_registry(),
        )
        feature_state_id = transfer_brief_ref.state_id
        execution_evidence_text = handoff_text
    elif transfer_strategy == "inline_text_handoff":
        handoff_text = str(inline_handoff_text).strip()
        if not handoff_text:
            handoff_text = str(step.params.get("inline_handoff_text", "")).strip()
        if not handoff_text:
            raise ValueError(f"step {step.step_id} missing inline handoff text")
        feature_bundle = _feature_bundle_from_natural_handoff(
            query_text=step.params.get("query", ""),
            evidence_text=handoff_text,
            handoff_text=handoff_text,
            registry=registry or default_tool_registry(),
        )
        feature_state_id = ""
        execution_evidence_text = handoff_text
    elif transfer_strategy == "text_strict_pure_lane":
        handoff_text = str(inline_handoff_text).strip()
        if not handoff_text:
            handoff_text = str(step.params.get("inline_handoff_text", "")).strip()
        if not handoff_text:
            raise ValueError(f"step {step.step_id} missing strict pure-text handoff")
        feature_bundle = _feature_bundle_from_strict_pure_text_handoff(
            query_text=step.params.get("query", ""),
            handoff_text=handoff_text,
            registry=registry or default_tool_registry(),
        )
        feature_state_id = ""
        execution_evidence_text = handoff_text
    elif transfer_strategy == "text_whole_lane":
        handoff_text = str(inline_handoff_text).strip()
        if not handoff_text:
            handoff_text = str(step.params.get("inline_handoff_text", "")).strip()
        if not handoff_text:
            raise ValueError(f"step {step.step_id} missing whole-lane text handoff")
        feature_bundle = _feature_bundle_from_natural_handoff(
            query_text=step.params.get("query", ""),
            evidence_text=handoff_text,
            handoff_text=handoff_text,
            registry=registry or default_tool_registry(),
        )
        feature_bundle["transfer_strategy"] = "text_whole_lane"
        feature_state_id = ""
        execution_evidence_text = handoff_text
    elif transfer_strategy == "state_packet_minimal":
        if decision_packet_ref is None:
            raise ValueError(f"step {step.step_id} missing executor decision packet input")
        feature_bundle = _feature_bundle_from_executor_decision_packet(
            query_text=step.params.get("query", ""),
            evidence_text=statepool.get_text(evidence_ref),
            decision_packet=_load_executor_decision_packet(statepool, decision_packet_ref),
            registry=registry or default_tool_registry(),
            ref=decision_packet_ref,
        )
        feature_state_id = decision_packet_ref.state_id
        execution_evidence_text = statepool.get_text(evidence_ref)
    else:
        use_full_rich_audit = str(handoff_profile).strip() == "protocol_full_rich_audit"
        if feature_ref is not None:
            feature_bundle = _load_feature_bundle(statepool, feature_ref)
            feature_state_id = feature_ref.state_id
        elif use_full_rich_audit and channel_snapshot_ref is not None:
            feature_bundle = _feature_bundle_from_channel_snapshot(
                statepool=statepool,
                snapshot_ref=channel_snapshot_ref,
                query_text=step.params.get("query", ""),
                evidence_text=statepool.get_text(evidence_ref),
                registry=registry or default_tool_registry(),
            )
            feature_state_id = channel_snapshot_ref.state_id
        elif use_full_rich_audit and tool_candidate_ref is not None:
            feature_bundle = _merge_feature_bundle_with_tool_candidates(
                feature_bundle={},
                tool_candidate_set=_load_tool_candidate_set(statepool, tool_candidate_ref),
            )
            feature_state_id = tool_candidate_ref.state_id
        else:
            raise ValueError(
                f"step {step.step_id} missing FEATURE_BUNDLE input"
            )
        if use_full_rich_audit and tool_candidate_ref is not None:
            feature_bundle = _merge_feature_bundle_with_tool_candidates(
                feature_bundle=feature_bundle,
                tool_candidate_set=_load_tool_candidate_set(statepool, tool_candidate_ref),
            )
        execution_evidence_text = statepool.get_text(evidence_ref)
    active_registry = registry or default_tool_registry()
    tool_name = select_tool_name(feature_bundle, registry=active_registry)
    tool_spec = active_registry.get(tool_name)
    active_runner = runner or LightweightSubprocessRunner()
    execution = active_runner.execute(
        tool_name=tool_name,
        payload={
            "task_id": task_id,
            "task_theme": task_theme,
            "step_id": step.step_id,
            "feature_bundle": feature_bundle,
            "evidence_text": execution_evidence_text,
        },
        timeout_s=tool_spec.timeout_s,
    )
    artifact_text = (
        _build_executor_plaintext_handoff(
            query=str(step.params.get("query", "")),
            route=execution.route,
            tool_name=execution.tool_name,
            actions=execution.actions,
        )
        if transfer_strategy == "text_whole_lane"
        else "\n".join(execution.actions)
    )
    preferred_storage = (
        output_storage
        or (
        evidence_ref.storage
        if evidence_ref is not None and evidence_ref.storage in {MMAP_FILE_STORAGE, PY_SHARED_MEMORY_STORAGE}
        else transfer_brief_ref.storage
        if transfer_brief_ref is not None and transfer_brief_ref.storage in {MMAP_FILE_STORAGE, PY_SHARED_MEMORY_STORAGE}
        else None
        )
    )
    artifact_ref = statepool.put_replay_restorable_bytes(
        state_id=f"{task_id}-{step.step_id}-artifact",
        kind="TOOL_ARTIFACT",
        payload=artifact_text.encode("utf-8"),
        metadata=attach_channel_metadata(
            {
                "source_evidence": evidence_ref.state_id if evidence_ref is not None else "",
                "source_features": feature_state_id,
                "source_channel_snapshot": (
                    channel_snapshot_ref.state_id if channel_snapshot_ref is not None else ""
                ),
                "source_tool_candidates": (
                    tool_candidate_ref.state_id
                    if str(handoff_profile).strip() == "protocol_full_rich_audit"
                    and tool_candidate_ref is not None
                    else ""
                ),
                "tool_name": execution.tool_name,
                "route": execution.route,
                "sandbox_mode": execution.sandbox_mode,
                "transfer_strategy": transfer_strategy,
            },
            state_kind="TOOL_ARTIFACT",
        ),
        storage=preferred_storage,
    )
    return StepResult(
        step_id=step.step_id,
        success=True,
        output_state_refs=[artifact_ref],
        payload={
            "actions": execution.actions,
            "reusable_steps": execution.reusable_steps,
            "tool_name": execution.tool_name,
            "route": execution.route,
            "sandbox_mode": execution.sandbox_mode,
            "matched_signals": list(execution.diagnostics.get("matched_signals", [])),
            "feature_state_id": feature_state_id,
            "channel_snapshot_state_id": (
                channel_snapshot_ref.state_id
                if str(handoff_profile).strip() == "protocol_full_rich_audit"
                and channel_snapshot_ref is not None
                else ""
            ),
            "transfer_strategy": transfer_strategy,
            "handoff_profile": handoff_profile,
        },
    )


def _load_feature_bundle(statepool: StatePool, ref: StateRef) -> dict[str, Any]:
    return _load_structured_bundle(statepool, ref, expected_kind="FEATURE_BUNDLE")


def _build_executor_plaintext_handoff(
    *,
    query: str,
    route: str,
    tool_name: str,
    actions: list[str],
) -> str:
    normalized_route = route.replace("_", " ").strip() or "generic triage"
    normalized_tool = tool_name.split(".")[-1].replace("_", " ").strip() if tool_name else "unknown tool"
    action_lines = "\n".join(f"- {action}" for action in actions if str(action).strip())
    return (
        "Executor handoff in plain language.\n"
        f"Request: {query.strip()}\n"
        f"Most likely issue: {normalized_route}.\n"
        f"Chosen playbook: {normalized_tool}.\n"
        "Actions taken:\n"
        f"{action_lines}\n"
    )


def _load_tool_candidate_set(statepool: StatePool, ref: StateRef) -> dict[str, Any]:
    return _load_structured_bundle(statepool, ref, expected_kind="TOOL_CANDIDATE_SET")


def _load_executor_decision_packet(statepool: StatePool, ref: StateRef) -> dict[str, Any]:
    packet = _load_structured_bundle(statepool, ref, expected_kind="EXECUTOR_DECISION_PACKET")
    _validate_executor_decision_packet(packet=packet, ref=ref)
    return packet


def _feature_bundle_from_channel_snapshot(
    *,
    statepool: StatePool,
    snapshot_ref: StateRef,
    query_text: object,
    evidence_text: str,
    registry: ToolRegistry,
) -> dict[str, Any]:
    snapshot = _load_structured_bundle(statepool, snapshot_ref, expected_kind="CHANNEL_SNAPSHOT")
    values = dict(snapshot.get("values", {}) or {})
    bundle = build_feature_bundle(
        query=str(values.get("query", query_text or "")).strip(),
        evidence_text=evidence_text,
        tags=[],
        reuse_signature=str(values.get("reuse_signature", "channel_snapshot_transfer")),
        reused_memory=bool(values.get("reused_memory", False)),
        registry=registry,
    )
    for key in (
        "route",
        "tool_name",
        "route_source",
        "route_confidence",
        "route_provenance",
        "matched_signals",
        "matched_tags",
        "match_score",
        "hint_doc_ids",
        "hint_route",
        "hint_tool_name",
        "tool_candidates",
        "retrieved_doc_ids",
        "feature_evidence_sha256",
        "feature_fresh_evidence_sha256",
    ):
        if key in values:
            bundle[key] = values[key]
    bundle["transfer_strategy"] = "channel_store_hashref"
    bundle["channel_snapshot_hash"] = str(snapshot.get("snapshot_hash", "")).strip()
    return bundle


def _load_structured_bundle(
    statepool: StatePool,
    ref: StateRef,
    *,
    expected_kind: str,
) -> dict[str, Any]:
    if ref.kind != expected_kind:
        raise ValueError(f"expected {expected_kind} state, got {ref.kind}")
    payload = statepool.get_bytes(ref)
    bundle = msgpack.unpackb(payload, raw=False, strict_map_key=False)
    if not isinstance(bundle, dict):
        raise ValueError(f"{expected_kind.lower()} {ref.state_id} is not a map")
    return dict(bundle)


def _merge_feature_bundle_with_tool_candidates(
    *,
    feature_bundle: dict[str, Any],
    tool_candidate_set: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(feature_bundle)
    for key in (
        "route",
        "tool_name",
        "route_source",
        "route_confidence",
        "route_provenance",
        "matched_signals",
        "matched_tags",
        "match_score",
        "hint_doc_ids",
        "hint_route",
        "hint_tool_name",
        "tool_candidates",
        "memory_prior_id",
        "memory_prior_route",
        "memory_prior_tool_name",
        "memory_prior_applied",
        "memory_candidate_reduction",
    ):
        if key in tool_candidate_set:
            merged[key] = tool_candidate_set[key]
    return merged


def _select_retrieved_hint(
    retrieved_hints: list[dict[str, Any]],
    *,
    registry: ToolRegistry,
) -> tuple[ToolMatch, list[str]] | None:
    selected_match: ToolMatch | None = None
    hint_doc_ids: list[str] = []
    for raw_hint in retrieved_hints:
        normalized = _normalize_retrieved_hint(raw_hint, registry=registry)
        if normalized is None:
            continue
        doc_id = normalized["doc_id"]
        candidate = ToolMatch(
            tool_name=normalized["tool_name"],
            route=normalized["route"],
            matched_signals=(),
            matched_tags=(),
            score=1000,
        )
        if selected_match is None:
            selected_match = candidate
            if doc_id:
                hint_doc_ids.append(doc_id)
            continue
        if (
            candidate.tool_name == selected_match.tool_name
            and candidate.route == selected_match.route
        ):
            if doc_id:
                hint_doc_ids.append(doc_id)
            continue
        break
    if selected_match is None:
        return None
    return selected_match, hint_doc_ids


def _normalize_retrieved_hint(
    raw_hint: dict[str, Any],
    *,
    registry: ToolRegistry,
) -> dict[str, str] | None:
    doc_id = str(raw_hint.get("doc_id", "")).strip()
    tool_name = str(raw_hint.get("tool_name", "")).strip()
    route = str(raw_hint.get("route", "")).strip()
    if tool_name:
        try:
            tool_spec = registry.get(tool_name)
        except KeyError:
            return None
        if route and route != tool_spec.route:
            return None
        return {
            "doc_id": doc_id,
            "route": tool_spec.route,
            "tool_name": tool_spec.name,
        }
    if route:
        tool_spec = registry.maybe_get_for_route(route)
        if tool_spec is None:
            return None
        return {
            "doc_id": doc_id,
            "route": tool_spec.route,
            "tool_name": tool_spec.name,
        }
    return None


def _normalize_memory_prior(
    raw_prior: dict[str, Any] | None,
    *,
    registry: ToolRegistry,
) -> ToolMatch | None:
    if not raw_prior:
        return None
    route = str(raw_prior.get("route", "")).strip()
    tool_name = str(raw_prior.get("tool_name", "")).strip()
    if tool_name:
        try:
            tool_spec = registry.get(tool_name)
        except KeyError:
            return None
        if route and route != tool_spec.route:
            return None
        resolved_route = tool_spec.route
        resolved_tool_name = tool_spec.name
    elif route:
        tool_spec = registry.maybe_get_for_route(route)
        if tool_spec is None:
            return None
        resolved_route = tool_spec.route
        resolved_tool_name = tool_spec.name
    else:
        return None
    confidence = _parse_float_or_default(raw_prior.get("confidence"), default=0.0)
    score = max(1, int(round(100.0 * confidence)))
    return ToolMatch(
        tool_name=resolved_tool_name,
        route=resolved_route,
        matched_signals=(),
        matched_tags=(),
        score=score,
    )


def _route_confidence_from_match(match: ToolMatch) -> float:
    if match.score <= 0 or match.route == "generic_triage":
        return 0.0
    return min(0.95, 0.45 + (0.05 * float(match.score)))


def _match_passes_threshold(match: ToolMatch) -> bool:
    return _route_confidence_from_match(match) >= MIN_DIRECT_ROUTE_CONFIDENCE


def _match_has_minimum_evidence_support(
    match: ToolMatch,
    *,
    primary_evidence_text: str,
    evidence_text: str,
    registry: ToolRegistry,
) -> bool:
    if match.score <= 0 or match.route == "generic_triage":
        return False
    try:
        spec = registry.get(match.tool_name)
    except KeyError:
        return False
    evidence_hits = tuple(
        dict.fromkeys(
            [
                *_match_signals(primary_evidence_text, spec.match_patterns),
                *_match_signals(evidence_text, spec.match_patterns),
            ]
        )
    )
    return len(evidence_hits) >= MIN_DIRECT_EVIDENCE_SIGNALS


def _has_ambiguous_tool_candidates(candidates: list[ToolMatch]) -> bool:
    if len(candidates) < 2:
        return False
    top = candidates[0]
    runner_up = candidates[1]
    if top.route == runner_up.route:
        return False
    if top.route == "generic_triage" or runner_up.route == "generic_triage":
        return False
    top_support = len(top.matched_signals) + len(top.matched_tags)
    runner_up_support = len(runner_up.matched_signals) + len(runner_up.matched_tags)
    if min(top_support, runner_up_support) < 2:
        return False
    score_gap = top.score - runner_up.score
    if score_gap <= 2:
        return True
    return top.score > 0 and (score_gap / float(top.score)) <= 0.10 and runner_up_support >= 3


def _serialize_tool_candidates(
    *,
    selected_match: ToolMatch,
    lexical_candidates: list[ToolMatch],
    selected_source: str,
    extra_candidates: list[tuple[ToolMatch, str]] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add_candidate(match: ToolMatch, *, source: str) -> None:
        key = (match.tool_name, match.route)
        if key in seen or len(ordered) >= limit:
            return
        seen.add(key)
        ordered.append(
            {
                "tool_name": match.tool_name,
                "route": match.route,
                "score": match.score,
                "matched_signals": list(match.matched_signals),
                "matched_tags": list(match.matched_tags),
                "source": source,
            }
        )

    add_candidate(selected_match, source=selected_source)
    for match, source in extra_candidates or []:
        add_candidate(match, source=source)
    for match in lexical_candidates:
        if match.tool_name == selected_match.tool_name and match.route == selected_match.route:
            continue
        add_candidate(match, source="lexical_alternative")
    return ordered


def _match_signals(text: str, patterns: tuple[str, ...]) -> list[str]:
    return [pattern for pattern in patterns if pattern in text]


def _feature_bundle_from_transfer_brief(
    *,
    query_text: object,
    evidence_text: str,
    brief_text: str,
    registry: ToolRegistry,
) -> dict[str, Any]:
    lines = [line.strip() for line in brief_text.splitlines() if line.strip()]
    tags: list[str] = []
    query = str(query_text or "").strip()
    route = ""
    tool_name = ""
    route_source = "text_brief"
    route_confidence = 0.0
    route_provenance: list[str] = []
    matched_signals: list[str] = []
    matched_tags: list[str] = []
    hint_doc_ids: list[str] = []
    hint_route = ""
    hint_tool_name = ""
    tool_candidates: list[dict[str, Any]] = []
    match_score: int | None = None
    for line in lines:
        if line.startswith("Query: ") and not query:
            query = line.removeprefix("Query: ").strip()
        elif line.startswith("Suggested route: "):
            route = _normalize_brief_scalar(line.removeprefix("Suggested route: ").strip())
        elif line.startswith("Suggested tool: "):
            tool_name = _normalize_brief_scalar(line.removeprefix("Suggested tool: ").strip())
        elif line.startswith("Route source: "):
            route_source = line.removeprefix("Route source: ").strip() or "text_brief"
        elif line.startswith("Route confidence: "):
            route_confidence = _parse_float_or_default(
                line.removeprefix("Route confidence: ").strip(),
                default=0.0,
            )
        elif line.startswith("Route provenance: "):
            raw_provenance = line.removeprefix("Route provenance: ").strip()
            if raw_provenance and raw_provenance.lower() != "none":
                route_provenance = [item.strip() for item in raw_provenance.split(",") if item.strip()]
        elif line.startswith("Match score: "):
            match_score = _parse_int_or_default(
                line.removeprefix("Match score: ").strip(),
                default=0,
            )
        elif line.startswith("Tool candidates: "):
            tool_candidates = _parse_transfer_tool_candidates(
                line.removeprefix("Tool candidates: ").strip()
            )
        elif line.startswith("Matched signals: "):
            raw_signals = line.removeprefix("Matched signals: ").strip()
            if raw_signals and raw_signals.lower() != "none":
                matched_signals = [item.strip() for item in raw_signals.split(",") if item.strip()]
        elif line.startswith("Matched tags: "):
            raw_tags = line.removeprefix("Matched tags: ").strip()
            if raw_tags and raw_tags.lower() != "none":
                matched_tags = [item.strip() for item in raw_tags.split(",") if item.strip()]
        elif line.startswith("Retrieved docs: "):
            continue
        elif line.startswith("Hint docs: "):
            raw_doc_ids = line.removeprefix("Hint docs: ").strip()
            if raw_doc_ids and raw_doc_ids.lower() != "none":
                hint_doc_ids = [item.strip() for item in raw_doc_ids.split(",") if item.strip()]
        elif line.startswith("Hint route: "):
            hint_route = _normalize_brief_scalar(line.removeprefix("Hint route: ").strip())
        elif line.startswith("Hint tool: "):
            hint_tool_name = _normalize_brief_scalar(line.removeprefix("Hint tool: ").strip())
    bundle = build_feature_bundle(
        query=query,
        evidence_text=evidence_text,
        tags=tags,
        reuse_signature="text_brief_transfer",
        reused_memory=False,
        registry=registry,
    )
    if route:
        route_tool = registry.maybe_get_for_route(route)
        if route_tool is not None:
            bundle["route"] = route_tool.route
            bundle["tool_name"] = tool_name or route_tool.name
    elif tool_name:
        try:
            bundle["tool_name"] = registry.get(tool_name).name
        except KeyError:
            pass
    if matched_signals:
        bundle["matched_signals"] = matched_signals
    if matched_tags:
        bundle["matched_tags"] = matched_tags
    if hint_doc_ids:
        bundle["hint_doc_ids"] = hint_doc_ids
    if hint_route:
        bundle["hint_route"] = hint_route
    if hint_tool_name:
        bundle["hint_tool_name"] = hint_tool_name
    bundle["route_source"] = route_source
    if route_confidence > 0.0 or route_source.endswith("abstain"):
        bundle["route_confidence"] = route_confidence
    if route_provenance:
        bundle["route_provenance"] = route_provenance
    if match_score is not None:
        bundle["match_score"] = match_score
    bundle["transfer_strategy"] = "text_brief"
    bundle["tool_candidates"] = tool_candidates or _serialize_tool_candidates(
        selected_match=ToolMatch(
            tool_name=str(bundle.get("tool_name", "")),
            route=str(bundle.get("route", "generic_triage")),
            matched_signals=tuple(str(item) for item in bundle.get("matched_signals", [])),
            matched_tags=tuple(str(item) for item in bundle.get("matched_tags", [])),
            score=int(bundle.get("match_score", 0)),
        ),
        lexical_candidates=[],
        selected_source="text_brief",
    )
    return bundle


def _build_text_packet_minimal(packet: dict[str, Any]) -> str:
    lines = [
        "StateBus text packet",
        f"Query: {str(packet.get('query', '')).strip()}",
        f"Route: {str(packet.get('route', '')).strip() or 'generic_triage'}",
        f"Tool: {str(packet.get('tool_name', '')).strip() or 'none'}",
        f"Route source: {str(packet.get('route_source', '')).strip() or 'text_packet'}",
        f"Route confidence: {float(packet.get('route_confidence', 0.0)):.2f}",
        "Route provenance: "
        + (
            ", ".join(str(item) for item in packet.get("route_provenance", []))
            if packet.get("route_provenance")
            else "none"
        ),
        "Matched signals: "
        + (
            ", ".join(str(item) for item in packet.get("matched_signals", []))
            if packet.get("matched_signals")
            else "none"
        ),
        "Matched tags: "
        + (
            ", ".join(str(item) for item in packet.get("matched_tags", []))
            if packet.get("matched_tags")
            else "none"
        ),
        f"Match score: {int(packet.get('match_score', 0))}",
        "Hint docs: "
        + (
            ", ".join(str(item) for item in packet.get("hint_doc_ids", []))
            if packet.get("hint_doc_ids")
            else "none"
        ),
        f"Hint route: {str(packet.get('hint_route', '')).strip() or 'none'}",
        f"Hint tool: {str(packet.get('hint_tool_name', '')).strip() or 'none'}",
        "Tool candidates: " + _format_transfer_tool_candidates(
            [dict(item) for item in packet.get("tool_candidates", []) if isinstance(item, dict)]
        ),
        "Retrieved docs: "
        + (
            ", ".join(str(item) for item in packet.get("retrieved_doc_ids", []))
            if packet.get("retrieved_doc_ids")
            else "none"
        ),
        f"Fresh evidence sha: {str(packet.get('feature_fresh_evidence_sha256', '')).strip() or 'none'}",
    ]
    return "\n".join(lines) + "\n"


def _feature_bundle_from_text_packet(
    *,
    query_text: object,
    evidence_text: str,
    packet_text: str,
    registry: ToolRegistry,
) -> dict[str, Any]:
    lines = [line.strip() for line in packet_text.splitlines() if line.strip()]
    decision_packet: dict[str, Any] = {
        "schema": "statebus.executor_decision_packet.v1",
        "query": str(query_text or "").strip(),
        "tool_candidates": [],
    }
    for line in lines:
        if line.startswith("Query: ") and not decision_packet["query"]:
            decision_packet["query"] = line.removeprefix("Query: ").strip()
        elif line.startswith("Route: "):
            decision_packet["route"] = _normalize_brief_scalar(line.removeprefix("Route: ").strip())
        elif line.startswith("Tool: "):
            decision_packet["tool_name"] = _normalize_brief_scalar(line.removeprefix("Tool: ").strip())
        elif line.startswith("Route source: "):
            decision_packet["route_source"] = line.removeprefix("Route source: ").strip() or "text_packet"
        elif line.startswith("Route confidence: "):
            decision_packet["route_confidence"] = _parse_float_or_default(
                line.removeprefix("Route confidence: ").strip(),
                default=0.0,
            )
        elif line.startswith("Route provenance: "):
            raw = line.removeprefix("Route provenance: ").strip()
            decision_packet["route_provenance"] = [] if not raw or raw.lower() == "none" else [
                item.strip() for item in raw.split(",") if item.strip()
            ]
        elif line.startswith("Matched signals: "):
            raw = line.removeprefix("Matched signals: ").strip()
            decision_packet["matched_signals"] = [] if not raw or raw.lower() == "none" else [
                item.strip() for item in raw.split(",") if item.strip()
            ]
        elif line.startswith("Matched tags: "):
            raw = line.removeprefix("Matched tags: ").strip()
            decision_packet["matched_tags"] = [] if not raw or raw.lower() == "none" else [
                item.strip() for item in raw.split(",") if item.strip()
            ]
        elif line.startswith("Match score: "):
            decision_packet["match_score"] = _parse_int_or_default(
                line.removeprefix("Match score: ").strip(),
                default=0,
            )
        elif line.startswith("Hint docs: "):
            raw = line.removeprefix("Hint docs: ").strip()
            decision_packet["hint_doc_ids"] = [] if not raw or raw.lower() == "none" else [
                item.strip() for item in raw.split(",") if item.strip()
            ]
        elif line.startswith("Hint route: "):
            decision_packet["hint_route"] = _normalize_brief_scalar(
                line.removeprefix("Hint route: ").strip()
            )
        elif line.startswith("Hint tool: "):
            decision_packet["hint_tool_name"] = _normalize_brief_scalar(
                line.removeprefix("Hint tool: ").strip()
            )
        elif line.startswith("Tool candidates: "):
            decision_packet["tool_candidates"] = _parse_transfer_tool_candidates(
                line.removeprefix("Tool candidates: ").strip()
            )
        elif line.startswith("Retrieved docs: "):
            raw = line.removeprefix("Retrieved docs: ").strip()
            decision_packet["retrieved_doc_ids"] = [] if not raw or raw.lower() == "none" else [
                item.strip() for item in raw.split(",") if item.strip()
            ]
        elif line.startswith("Fresh evidence sha: "):
            decision_packet["feature_fresh_evidence_sha256"] = _normalize_brief_scalar(
                line.removeprefix("Fresh evidence sha: ").strip()
            )
    bundle = _feature_bundle_from_executor_decision_packet(
        query_text=query_text,
        evidence_text=evidence_text,
        decision_packet=decision_packet,
        registry=registry,
    )
    bundle["transfer_strategy"] = "text_packet_minimal"
    return bundle


def _build_natural_handoff_text(
    *,
    query: str,
    evidence_text: str,
) -> str:
    return (
        "Retriever handoff in plain language.\n"
        f"The downstream agent needs to answer this request: {query.strip()}.\n"
        "Use only the cited evidence below to decide the most likely issue, rule out the strongest competing explanation, and choose the first action.\n"
        "Evidence follows:\n"
        f"{evidence_text.strip()}\n"
    )


def _feature_bundle_from_natural_handoff(
    *,
    query_text: object,
    evidence_text: str,
    handoff_text: str,
    registry: ToolRegistry,
) -> dict[str, Any]:
    bundle = build_feature_bundle(
        query=query_text,
        evidence_text=f"{evidence_text}\n{handoff_text}",
        tags=[],
        reuse_signature="natural_handoff_transfer",
        reused_memory=False,
        registry=registry,
    )
    bundle["transfer_strategy"] = "natural_handoff_text"
    return bundle


def _feature_bundle_from_strict_pure_text_handoff(
    *,
    query_text: object,
    handoff_text: str,
    registry: ToolRegistry,
) -> dict[str, Any]:
    query = str(query_text).strip()
    evidence_text = handoff_text.strip()
    lexical_match = registry.retrieve_candidates(
        query_text=query.lower(),
        primary_evidence_text=evidence_text.lower(),
        evidence_text=evidence_text.lower(),
        tags=[],
        limit=1,
    )
    selected = lexical_match[0] if lexical_match else registry.fallback_match()
    route = selected.route or "generic_triage"
    tool_name = selected.tool_name or registry.get_for_route(route).name
    route_source = "strict_pure_text_lexical" if lexical_match else "strict_pure_text_fallback"
    route_provenance = ["pure_text_lexical"] if lexical_match else ["pure_text_fallback"]
    return {
        "route": route,
        "tool_name": tool_name,
        "query": query,
        "route_source": route_source,
        "route_provenance": route_provenance,
        "route_confidence": _route_confidence_from_match(selected) if lexical_match else 0.0,
        "matched_signals": list(selected.matched_signals),
        "transfer_strategy": "text_strict_pure_lane",
    }


def _feature_bundle_from_executor_decision_packet(
    *,
    query_text: object,
    evidence_text: str,
    decision_packet: dict[str, Any],
    registry: ToolRegistry,
    ref: StateRef | None = None,
) -> dict[str, Any]:
    del registry
    _validate_executor_decision_packet(packet=decision_packet, ref=ref)
    route = str(decision_packet.get("route", "")).strip()
    tool_name = str(decision_packet.get("tool_name", "")).strip()
    route_source = str(decision_packet.get("route_source", "")).strip() or "decision_packet"
    matched_signals = [str(item) for item in decision_packet.get("matched_signals", [])]
    matched_tags = [str(item) for item in decision_packet.get("matched_tags", [])]
    match_score = int(decision_packet.get("match_score", len(matched_signals)))
    tool_candidates = [
        dict(item)
        for item in decision_packet.get("tool_candidates", [])
        if isinstance(item, dict)
    ]
    audit_mode = str(decision_packet.get("audit_mode", "")).strip()
    if not audit_mode and ref is not None:
        audit_mode = str(ref.metadata.get("audit_decision_packet_mode", "")).strip()
    if audit_mode == "override_mismatch_abstain":
        fallback_tool = "tool.collect_more_evidence"
        fallback_candidate = {
            "tool_name": fallback_tool,
            "route": route or "generic_triage",
            "score": 0,
            "matched_signals": [],
            "matched_tags": [],
            "source": "audit_override_abstain",
        }
        tool_candidates = [fallback_candidate, *tool_candidates]
        if fallback_tool:
            tool_name = fallback_tool
            route_source = "audit_override_abstain"
    if not tool_candidates and route and tool_name:
        tool_candidates = [
            {
                "tool_name": tool_name,
                "route": route,
                "score": match_score,
                "matched_signals": matched_signals,
                "matched_tags": matched_tags,
                "source": route_source,
            }
        ]
    return {
        "schema": "statebus.feature_bundle.v1",
        "route": route,
        "tool_name": tool_name,
        "query": str(decision_packet.get("query", query_text or "")).strip(),
        "query_terms": [],
        "tags": [],
        "matched_signals": matched_signals,
        "matched_tags": matched_tags,
        "match_score": match_score,
        "route_source": route_source,
        "route_confidence": float(decision_packet.get("route_confidence", 0.0)),
        "route_provenance": [str(item) for item in decision_packet.get("route_provenance", [])],
        "hint_doc_ids": [str(item) for item in decision_packet.get("hint_doc_ids", [])],
        "hint_route": str(decision_packet.get("hint_route", "")).strip(),
        "hint_tool_name": str(decision_packet.get("hint_tool_name", "")).strip(),
        "tool_candidates": tool_candidates,
        "retrieved_doc_ids": [str(item) for item in decision_packet.get("retrieved_doc_ids", [])],
        "feature_evidence_sha256": str(decision_packet.get("feature_evidence_sha256", "")).strip(),
        "feature_fresh_evidence_sha256": str(
            decision_packet.get("feature_fresh_evidence_sha256", "")
        ).strip(),
        "evidence_sha256": hashlib.sha256(evidence_text.encode("utf-8")).hexdigest(),
        "transfer_strategy": "state_packet_minimal",
    }


def _validate_executor_decision_packet(
    *,
    packet: dict[str, Any],
    ref: StateRef | None = None,
) -> None:
    missing = [key for key in DECISION_PACKET_REQUIRED_KEYS if key not in packet]
    if missing:
        raise ValueError(f"executor decision packet missing fields: {', '.join(missing)}")
    route = str(packet.get("route", "")).strip()
    tool_name = str(packet.get("tool_name", "")).strip()
    if not route or not tool_name:
        raise ValueError("executor decision packet requires non-empty route and tool_name")
    if not isinstance(packet.get("retrieved_doc_ids", []), list):
        raise ValueError("executor decision packet retrieved_doc_ids must be a list")
    if not isinstance(packet.get("matched_signals", []), list):
        raise ValueError("executor decision packet matched_signals must be a list")
    if not isinstance(packet.get("route_provenance", []), list):
        raise ValueError("executor decision packet route_provenance must be a list")
    route_provenance = [str(item).strip() for item in packet.get("route_provenance", []) if str(item).strip()]
    if not route_provenance:
        raise ValueError("executor decision packet requires non-empty route_provenance")
    route_confidence = packet.get("route_confidence")
    if not isinstance(route_confidence, (int, float)):
        raise ValueError("executor decision packet route_confidence must be numeric")
    if not 0.0 <= float(route_confidence) <= 1.0:
        raise ValueError("executor decision packet route_confidence must be within [0,1]")
    tool_candidates = packet.get("tool_candidates", [])
    if not isinstance(tool_candidates, list):
        raise ValueError("executor decision packet tool_candidates must be a list")
    if not tool_candidates:
        raise ValueError("executor decision packet requires non-empty tool_candidates")
    matching_candidate = False
    for item in tool_candidates:
        if not isinstance(item, dict):
            raise ValueError("executor decision packet tool_candidates entries must be objects")
        candidate_tool = str(item.get("tool_name", "")).strip()
        candidate_route = str(item.get("route", "")).strip()
        if not candidate_tool or not candidate_route:
            raise ValueError("executor decision packet tool_candidates require route and tool_name")
        candidate_score = item.get("score")
        if candidate_score is not None and not isinstance(candidate_score, (int, float)):
            raise ValueError("executor decision packet tool_candidates score must be numeric")
        candidate_signals = item.get("matched_signals", [])
        if candidate_signals is not None and not isinstance(candidate_signals, list):
            raise ValueError(
                "executor decision packet tool_candidates matched_signals must be a list when present"
            )
        candidate_tags = item.get("matched_tags", [])
        if candidate_tags is not None and not isinstance(candidate_tags, list):
            raise ValueError(
                "executor decision packet tool_candidates matched_tags must be a list when present"
            )
        if candidate_tool == tool_name and candidate_route == route:
            matching_candidate = True
    if not matching_candidate:
        raise ValueError("executor decision packet selected route/tool must appear in tool_candidates")
    payload_sha = str(packet.get("feature_fresh_evidence_sha256", "")).strip()
    if not payload_sha:
        raise ValueError("executor decision packet missing feature_fresh_evidence_sha256")
    if ref is not None:
        metadata_sha = str(ref.metadata.get("feature_fresh_evidence_sha256", "")).strip()
        if metadata_sha and payload_sha and metadata_sha != payload_sha:
            raise ValueError("executor decision packet fresh evidence hash mismatch")
        metadata_route = str(ref.metadata.get("feature_route", "")).strip()
        metadata_route_source = str(ref.metadata.get("feature_route_source", "")).strip()
        metadata_confidence = ref.metadata.get("feature_route_confidence")
        audit_mode = str(ref.metadata.get("audit_decision_packet_mode", "")).strip()
        if audit_mode != "override_mismatch_abstain":
            if metadata_route and metadata_route != route:
                raise ValueError("executor decision packet route mismatch with state metadata")
            if metadata_route_source and metadata_route_source != str(packet.get("route_source", "")).strip():
                raise ValueError("executor decision packet route_source mismatch with state metadata")
            if isinstance(metadata_confidence, (int, float)) and float(metadata_confidence) != float(route_confidence):
                raise ValueError("executor decision packet route_confidence mismatch with state metadata")
        else:
            if route == "generic_triage":
                raise ValueError("executor decision packet override_mismatch_abstain requires explicit override route")
            if not tool_name:
                raise ValueError("executor decision packet override_mismatch_abstain requires explicit override tool_name")
            if "audit_override" not in set(route_provenance):
                raise ValueError(
                    "executor decision packet override_mismatch_abstain requires audit_override provenance"
                )
            if not packet.get("retrieved_doc_ids", []):
                raise ValueError(
                    "executor decision packet override_mismatch_abstain requires retrieved_doc_ids"
                )
            if not packet.get("matched_signals", []):
                raise ValueError(
                    "executor decision packet override_mismatch_abstain requires matched_signals"
                )


def _parse_transfer_tool_candidates(raw_value: str) -> list[dict[str, Any]]:
    text = str(raw_value).strip()
    if not text or text.lower() == "none":
        return []
    parsed: list[dict[str, Any]] = []
    for item in text.split(";"):
        token = item.strip()
        if not token:
            continue
        try:
            tool_and_route, source, score_text = token.rsplit("#", 2)
            tool_name, route = tool_and_route.split("@", 1)
        except ValueError:
            continue
        tool_name = tool_name.strip()
        route = route.strip()
        source = source.strip()
        if not tool_name or not route:
            continue
        parsed.append(
            {
                "tool_name": tool_name,
                "route": route,
                "score": _parse_int_or_default(score_text.strip(), default=0),
                "matched_signals": [],
                "matched_tags": [],
                "source": source,
            }
        )
    return parsed


def _format_transfer_tool_candidates(candidates: list[dict[str, Any]]) -> str:
    serialized: list[str] = []
    for candidate in candidates:
        tool_name = str(candidate.get("tool_name", "")).strip()
        route = str(candidate.get("route", "")).strip()
        source = str(candidate.get("source", "")).strip()
        score = int(candidate.get("score", 0))
        if not tool_name or not route:
            continue
        serialized.append(f"{tool_name}@{route}#{source}#{score}")
    return "; ".join(serialized) if serialized else "none"


def _parse_float_or_default(raw_value: str, *, default: float) -> float:
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default


def _parse_int_or_default(raw_value: str, *, default: int) -> int:
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def _is_route_replay_eligible(
    *,
    route_confidence: float,
    route_provenance: list[str],
    minimum_confidence: float,
) -> bool:
    return route_confidence >= minimum_confidence and "lexical" in set(route_provenance)


def _normalize_brief_scalar(raw_value: str) -> str:
    text = str(raw_value).strip()
    return "" if text.lower() == "none" else text
