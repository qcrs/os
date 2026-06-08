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

from protocol.messages import PlanStep, StateRef, StepResult
from statepool.store import MMAP_FILE_STORAGE, PY_SHARED_MEMORY_STORAGE, StatePool


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
        self._routes[spec.route] = spec.name

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
    lexical_match = lexical_candidates[0] if lexical_candidates else active_registry.fallback_match()
    lexical_ambiguous = _has_ambiguous_tool_candidates(lexical_candidates)
    selected_hint = _select_retrieved_hint(retrieved_hints or [], registry=active_registry)
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
                lexical_candidates=lexical_candidates,
                selected_source=route_source,
            )
        else:
            match = lexical_match
            route_source = "lexical_match" if lexical_match.score > 0 else "fallback"
            route_provenance = ["lexical"] if lexical_match.score > 0 else ["fallback"]
            route_confidence = _route_confidence_from_match(lexical_match)
            tool_candidates = _serialize_tool_candidates(
                selected_match=match,
                lexical_candidates=lexical_candidates,
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
                lexical_candidates=lexical_candidates,
                selected_source=route_source,
            )
        elif lexical_supported:
            if lexical_ambiguous:
                match = active_registry.fallback_match()
                route_source = "ambiguous_candidates_abstain"
                route_provenance = ["lexical_ambiguous", "corpus_metadata_conflict"]
                route_confidence = 0.0
                tool_candidates = _serialize_tool_candidates(
                    selected_match=match,
                    lexical_candidates=lexical_candidates,
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
                    lexical_candidates=lexical_candidates,
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
        "reuse_signature": reuse_signature,
        "reused_memory": bool(reused_memory),
        "evidence_chars": len(evidence_text),
        "evidence_lines": len([line for line in evidence_text.splitlines() if line.strip()]),
        "evidence_preview": evidence_text[:240],
        "evidence_sha256": hashlib.sha256(evidence_text.encode("utf-8")).hexdigest(),
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
) -> StepResult:
    evidence_ref = next((ref for ref in input_state_refs if ref.kind == "DENSE_EVIDENCE"), None)
    feature_ref = next((ref for ref in input_state_refs if ref.kind == "FEATURE_BUNDLE"), None)
    if evidence_ref is None:
        raise ValueError(f"step {step.step_id} missing DENSE_EVIDENCE input")
    if feature_ref is None:
        raise ValueError(f"step {step.step_id} missing FEATURE_BUNDLE input")

    feature_bundle = _load_feature_bundle(statepool, feature_ref)
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
            "evidence_text": statepool.get_text(evidence_ref),
        },
        timeout_s=tool_spec.timeout_s,
    )
    artifact_text = "\n".join(execution.actions)
    preferred_storage = (
        output_storage
        or (
        evidence_ref.storage
        if evidence_ref.storage in {MMAP_FILE_STORAGE, PY_SHARED_MEMORY_STORAGE}
        else None
        )
    )
    artifact_ref = statepool.put_bytes(
        state_id=f"{task_id}-{step.step_id}-artifact",
        kind="TOOL_ARTIFACT",
        payload=artifact_text.encode("utf-8"),
        metadata={
            "source_evidence": evidence_ref.state_id,
            "source_features": feature_ref.state_id,
            "tool_name": execution.tool_name,
            "route": execution.route,
            "sandbox_mode": execution.sandbox_mode,
        },
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
            "feature_state_id": feature_ref.state_id,
        },
    )


def _load_feature_bundle(statepool: StatePool, ref: StateRef) -> dict[str, Any]:
    payload = statepool.get_bytes(ref)
    feature_bundle = msgpack.unpackb(payload, raw=False, strict_map_key=False)
    if not isinstance(feature_bundle, dict):
        raise ValueError(f"feature bundle {ref.state_id} is not a map")
    return dict(feature_bundle)


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


def _route_confidence_from_match(match: ToolMatch) -> float:
    if match.score <= 0 or match.route == "generic_triage":
        return 0.0
    return min(0.95, 0.45 + (0.05 * float(match.score)))


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
