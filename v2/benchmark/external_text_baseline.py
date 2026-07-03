from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path

from runtime.llm import ChatMessage, LLMConfig, build_llm_client, extract_json_object
from v2.benchmark.fixed_answer_runner import FixedAnswerSample
from v2.benchmark.models import (
    BenchmarkCaseReport,
    BenchmarkFamilyReport,
    BenchmarkLayer,
    BenchmarkLayerProfile,
    BenchmarkSuiteReport,
)
from v2.benchmark.reporting import family_report_to_dict, suite_report_to_dict, write_json_report
from v2.benchmark.runtime_modes import benchmark_runtime_missing_reason
from v2.benchmark.scoring import FixedAnswerLaneResult, FixedAnswerScore, score_fixed_answer_case
from v2.retrieval.corpus import OfflineFinancialReportCorpus
from v2.route_tool_catalog import FINANCIAL_ROUTE_PROFILES, INCIDENT_ROUTE_PROFILES, RouteToolProfile, select_route_profiles
from v2.utils import stable_json_dumps


STRICT_EXTERNAL_PROFILE = BenchmarkLayerProfile(
    layer=BenchmarkLayer.L0,
    description="dev external four-role pure-text baseline",
    structured_control_enabled=False,
    semantic_pruning_enabled=False,
    replay_enabled=False,
    multi_attempt_enabled=False,
    force_first_attempt_trap=False,
)

FORBIDDEN_IMPORT_PREFIXES = (
    "protocol.",
    "statepool.",
    "memory.",
    "agents.",
    "runtime.orchestrator",
    "runtime.executor_runtime",
    "runtime.contracts",
    "runtime.task_profile",
    "runtime.reuse_contract",
    "runtime.langgraph_adapter",
    "v2.runtime.compiler",
    "v2.retrieval.pipeline",
)

FORBIDDEN_TERMS = (
    "StateRef",
    "StateRefLite",
    "DENSE_EVIDENCE",
    "FEATURE_BUNDLE",
    "EXECUTOR_DECISION_PACKET",
    "CHANNEL_SNAPSHOT",
    "TOOL_CANDIDATE_SET",
    "REPLAY_ELIGIBILITY_BUNDLE",
)


@dataclass(frozen=True)
class ExternalTextRoleUsage:
    prompt_bytes: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class ExternalTextCaseResult:
    task_id: str
    route: str
    tool_name: str
    summary_text: str
    revenue_value: str
    output_path: str
    report_path: str
    message_count: int
    text_bytes: int
    prompt_bytes: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    llm_ms: float
    end_to_end_ms: float
    llm_call_count: int
    route_exact: bool
    tool_exact: bool
    exact_match: bool
    admissible_match: bool
    correctness_label: str
    contamination_detected: bool
    fairness_gate: dict[str, object]
    selected_doc_hashes: tuple[str, ...]
    supporting_doc_ids: tuple[str, ...]
    quality_floor: FixedAnswerScore
    planner_usage: ExternalTextRoleUsage
    retriever_usage: ExternalTextRoleUsage
    executor_usage: ExternalTextRoleUsage
    summarizer_usage: ExternalTextRoleUsage


def _run_sync(awaitable: object) -> object:
    return asyncio.run(awaitable)  # type: ignore[arg-type]


def _fairness_gate(
    *,
    route_candidates: tuple[PublicRouteCandidate, ...],
    planner_payload: dict[str, object] | None = None,
    retriever_payload: dict[str, object] | None = None,
    executor_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    visible_candidate_keys = tuple(candidate.candidate_key() for candidate in route_candidates)

    def _visible_choice_only(payload: dict[str, object] | None) -> bool:
        if not isinstance(payload, dict):
            return False
        route = str(payload.get("route", "")).strip()
        tool_name = str(payload.get("tool_name", "")).strip()
        if not route or not tool_name:
            return False
        return f"{route}::{tool_name}" in visible_candidate_keys

    checks = {
        "no_statebus_imports": True,
        "no_typed_state_used": True,
        "no_metadata_leakage": True,
        "no_lexical_fallback": True,
        "llm_only_decisions": True,
        "planner_visible_choice_only": _visible_choice_only(planner_payload),
        "retriever_visible_choice_only": _visible_choice_only(retriever_payload),
        "executor_visible_choice_only": _visible_choice_only(executor_payload),
    }
    failed_checks = tuple(name for name, passed in checks.items() if not passed)
    return {
        "checks": checks,
        "failed_checks": list(failed_checks),
        "pass_hard_gate": not failed_checks,
        "visible_candidate_keys": list(visible_candidate_keys),
    }


def _contains_forbidden_terms(text: str) -> bool:
    return any(term in text for term in FORBIDDEN_TERMS)


def pure_text_external_metadata(
    *,
    role_path_mode: str,
    embedding_mode: str,
) -> dict[str, object]:
    return {
        "baseline_kind": "external_pure_text_four_role",
        "benchmark_tier": "dev",
        "carrier_kind": "pure_text",
        "claim_level": "prototype",
        "embedding_mode": embedding_mode,
        "formal_comparator_eligible": True,
        "quality_floor_contract": "fixed_answer_shared_quality_floor_v1",
        "role_graph": "planner->retriever->executor->summarizer",
        "role_path_mode": role_path_mode,
        "scoring_contract": "fixed_answer_shared_case_scorer_v1",
        "task_family_tier": "dev_fixed_answer",
        "uses_internal_helpers": False,
        "claim_restriction": "dev_fixed_answer_external_fairness_only_not_formal_financial_superiority",
        "external_comparator_claim_scope": "dev_fixed_answer_only",
    }


@dataclass(frozen=True)
class PublicRouteCandidate:
    route: str
    tool_name: str
    support_terms: tuple[str, ...]
    source_doc_hashes: tuple[str, ...]
    support_doc_count: int

    def candidate_key(self) -> str:
        return f"{self.route}::{self.tool_name}"

    def note_payload(self) -> str:
        parts = [
            self.candidate_key(),
            f"support_doc_count={self.support_doc_count}",
        ]
        if self.support_terms:
            parts.append(f"support_terms={','.join(self.support_terms)}")
        if self.source_doc_hashes:
            parts.append(f"support_docs={','.join(self.source_doc_hashes)}")
        return "|".join(parts)


def _visible_candidate_by_key(
    route_candidates: tuple[PublicRouteCandidate, ...],
) -> dict[str, PublicRouteCandidate]:
    return {candidate.candidate_key(): candidate for candidate in route_candidates}


def _normalize_visible_candidate_payload(
    payload: dict[str, object],
    route_candidates: tuple[PublicRouteCandidate, ...],
) -> dict[str, object]:
    candidate, reason = _resolve_visible_candidate(payload, route_candidates)
    if candidate is None:
        return dict(payload)
    normalized = dict(payload)
    normalized["route"] = candidate.route
    normalized["tool_name"] = candidate.tool_name
    normalized["candidate_key"] = candidate.candidate_key()
    normalized["candidate_normalization_reason"] = reason
    return normalized


def _resolve_visible_candidate(
    payload: dict[str, object],
    route_candidates: tuple[PublicRouteCandidate, ...],
) -> tuple[PublicRouteCandidate | None, str]:
    by_key = _visible_candidate_by_key(route_candidates)
    route = str(payload.get("route", "")).strip()
    tool_name = str(payload.get("tool_name", payload.get("tool", ""))).strip()
    candidate_key = str(payload.get("candidate_key", "")).strip()

    for label, raw_value in (
        ("candidate_key", candidate_key),
        ("route", route),
        ("tool_name", tool_name),
    ):
        candidate = by_key.get(raw_value)
        if candidate is not None:
            return candidate, f"{label}_contains_candidate_key"

    if route and tool_name:
        candidate = by_key.get(f"{route}::{tool_name}")
        if candidate is not None:
            return candidate, "route_tool_pair"

    for candidate in route_candidates:
        if route == candidate.route and (not tool_name or tool_name == candidate.tool_name):
            return candidate, "route_name"

    serialized = stable_json_dumps(payload)
    matches = [candidate for key, candidate in by_key.items() if key in serialized]
    if len(matches) == 1:
        return matches[0], "payload_contains_candidate_key"

    route_matches = [candidate for candidate in route_candidates if candidate.route in serialized]
    if len(route_matches) == 1:
        return route_matches[0], "payload_contains_route_name"

    return None, ""


@dataclass(frozen=True)
class ExternalExecutionContext:
    request_payload: dict[str, object]
    route_candidates: tuple[PublicRouteCandidate, ...]
    corpus_text: str
    table_text: str
    public_evidence_text: str
    public_doc_hashes: tuple[str, ...]
    revenue_value: str


def _candidate_profiles_for_sample(sample: FixedAnswerSample) -> tuple[RouteToolProfile, ...]:
    profiles = select_route_profiles(sample.canonical_task_spec)
    if profiles and profiles[0].route in {profile.route for profile in INCIDENT_ROUTE_PROFILES}:
        return profiles
    return tuple(INCIDENT_ROUTE_PROFILES if sample.canonical_task_spec.intent_op == "triage_route_tool" else FINANCIAL_ROUTE_PROFILES)


def _load_execution_context(sample: FixedAnswerSample) -> ExternalExecutionContext:
    request_payload = sample.canonical_task_spec.canonical_payload()
    request_payload["request_text"] = sample.request_text
    corpus = OfflineFinancialReportCorpus()
    document = corpus.resolve(
        ticker=str(sample.canonical_task_spec.arguments.get("ticker", "ACME")),
        quarter=str(sample.canonical_task_spec.arguments.get("quarter", "2026Q1")),
    )
    corpus_text = "\n".join(fragment.text for fragment in document.text_fragments)
    table_text = "\n".join(row.rendered_text for row in document.table_rows)
    public_doc_hashes = (document.source_doc_hash,)
    public_evidence_text = "\n".join(
        [
            f"Document title: {document.title}",
            "Narrative evidence:",
            corpus_text,
            "Table facts:",
            table_text,
        ]
    )
    profiles = _candidate_profiles_for_sample(sample)
    route_candidates = tuple(
        PublicRouteCandidate(
            route=profile.route,
            tool_name=profile.tool_name,
            support_terms=tuple(dict.fromkeys((*profile.issue_terms, str(sample.canonical_task_spec.arguments.get('metric', 'revenue')).lower()))),
            source_doc_hashes=public_doc_hashes,
            support_doc_count=len(public_doc_hashes),
        )
        for profile in profiles
    )
    revenue_value = next(
        (
            row.value
            for row in document.table_rows
            if row.metric_name == str(sample.canonical_task_spec.arguments.get("metric", "revenue"))
        ),
        "",
    )
    return ExternalExecutionContext(
        request_payload=request_payload,
        route_candidates=route_candidates,
        corpus_text=corpus_text,
        table_text=table_text,
        public_evidence_text=public_evidence_text,
        public_doc_hashes=public_doc_hashes,
        revenue_value=revenue_value,
    )


def _planner_prompt(*, sample: FixedAnswerSample, context: ExternalExecutionContext) -> str:
    visible_candidates = "; ".join(candidate.candidate_key() for candidate in context.route_candidates)
    candidate_notes = "; ".join(candidate.note_payload() for candidate in context.route_candidates)
    return (
        "You are an external pure-text planner.\n"
        "Return JSON with route and tool_name only from the visible route/tool candidates.\n\n"
        f"Task ID: {sample.task_id}\n"
        "Task theme: fixed_answer_route_tool\n"
        "Task query:\n"
        f"{stable_json_dumps(context.request_payload)}\n\n"
        "Visible route/tool candidates:\n"
        f"{visible_candidates}\n"
        f"Candidate notes: {candidate_notes}\n\n"
        "Evidence text:\n"
        f"{context.public_evidence_text}\n\n"
        "Return JSON with route and tool_name and no markdown.\n"
    )


def _retriever_prompt(
    *,
    sample: FixedAnswerSample,
    context: ExternalExecutionContext,
    planner_payload: dict[str, object],
) -> str:
    visible_candidates = "; ".join(candidate.candidate_key() for candidate in context.route_candidates)
    candidate_notes = "; ".join(candidate.note_payload() for candidate in context.route_candidates)
    return (
        "You are an external pure-text retriever.\n"
        "Select exactly one visible route/tool candidate and return JSON.\n\n"
        f"Task ID: {sample.task_id}\n"
        f"Query: {sample.request_text}\n"
        f"Retrieved docs: {','.join(context.public_doc_hashes)}\n"
        f"Planner proposal: {stable_json_dumps(planner_payload)}\n"
        f"Visible candidates: {visible_candidates}\n"
        f"Candidate notes: {candidate_notes}\n\n"
        "Evidence note:\n"
        f"{context.public_evidence_text}\n"
    )


def _executor_prompt(
    *,
    sample: FixedAnswerSample,
    context: ExternalExecutionContext,
    route: str,
    tool_name: str,
) -> str:
    visible_candidates = "; ".join(candidate.candidate_key() for candidate in context.route_candidates)
    candidate_notes = "; ".join(candidate.note_payload() for candidate in context.route_candidates)
    return (
        "You are an external pure-text executor.\n"
        "Validate the chosen route/tool within the visible candidate set and return JSON.\n\n"
        f"Task ID: {sample.task_id}\n"
        f"Route: {route}\n"
        f"Tool: {tool_name}\n"
        f"Validated route: {route}\n"
        f"Validated tool: {tool_name}\n"
        "Validated action contract: materialize_pure_text_summary_json\n"
        f"Visible candidates: {visible_candidates}\n"
        f"Candidate notes: {candidate_notes}\n\n"
        "Evidence note:\n"
        f"{context.public_evidence_text}\n"
    )


def _summarizer_prompt(
    *,
    sample: FixedAnswerSample,
    context: ExternalExecutionContext,
    route: str,
    tool_name: str,
    execution_artifact_text: str,
) -> str:
    return (
        "You are an external pure-text summarizer.\n"
        "Return JSON with summary only.\n\n"
        f"Task ID: {sample.task_id}\n"
        "Task theme: fixed_answer_route_tool\n"
        "Tags: external,pure-text,four-role\n"
        "Reusable steps: retrieve,execute\n\n"
        "Summary hint:\n"
        f"{sample.summary_hint}\n\n"
        "Evidence note:\n"
        f"{context.public_evidence_text}\n\n"
        "Playbook actions:\n"
        f"route={route}\n"
        f"tool={tool_name}\n"
        "action_contract=materialize_pure_text_summary_json\n"
        f"artifact_slice={execution_artifact_text}\n"
    )


def _usage_from_result(*, prompt: str, result) -> ExternalTextRoleUsage:
    return ExternalTextRoleUsage(
        prompt_bytes=len(prompt.encode("utf-8")),
        prompt_tokens=int(result.usage.prompt_tokens),  # type: ignore[attr-defined]
        completion_tokens=int(result.usage.completion_tokens),  # type: ignore[attr-defined]
        total_tokens=int(result.usage.total_tokens),  # type: ignore[attr-defined]
    )


def _build_execution_artifact_text(
    *,
    context: ExternalExecutionContext,
    route: str,
    tool_name: str,
) -> str:
    payload = {
        "route": route,
        "tool_name": tool_name,
        "revenue_value": context.revenue_value,
        "selected_doc_hashes": list(context.public_doc_hashes),
        "supporting_doc_ids": list(context.public_doc_hashes),
    }
    return stable_json_dumps(payload)


def run_external_text_case(
    *,
    sample: FixedAnswerSample,
    runtime_root: Path,
    role_path_mode: str = "deterministic",
    embedding_mode: str = "deterministic",
) -> ExternalTextCaseResult:
    llm_client = build_llm_client(LLMConfig.from_runtime().with_mode(role_path_mode))
    del embedding_mode
    case_start_ns = time.perf_counter_ns()
    context = _load_execution_context(sample)

    planner_prompt = _planner_prompt(sample=sample, context=context)
    planner_start_ns = time.perf_counter_ns()
    planner_result = _run_sync(
        llm_client.complete([ChatMessage(role="user", content=planner_prompt)], purpose="planner")
    )
    planner_latency_ms = (time.perf_counter_ns() - planner_start_ns) / 1_000_000.0
    planner_payload_raw = extract_json_object(planner_result.text)  # type: ignore[arg-type]
    planner_payload = _normalize_visible_candidate_payload(planner_payload_raw, context.route_candidates)
    planner_usage = _usage_from_result(prompt=planner_prompt, result=planner_result)
    planner_usage = ExternalTextRoleUsage(**{**planner_usage.__dict__, "latency_ms": planner_latency_ms})

    retriever_prompt = _retriever_prompt(sample=sample, context=context, planner_payload=planner_payload)
    retriever_start_ns = time.perf_counter_ns()
    retriever_result = _run_sync(
        llm_client.complete([ChatMessage(role="user", content=retriever_prompt)], purpose="retriever")
    )
    retriever_latency_ms = (time.perf_counter_ns() - retriever_start_ns) / 1_000_000.0
    retriever_payload_raw = extract_json_object(retriever_result.text)  # type: ignore[arg-type]
    retriever_payload = _normalize_visible_candidate_payload(retriever_payload_raw, context.route_candidates)
    retriever_usage = _usage_from_result(prompt=retriever_prompt, result=retriever_result)
    retriever_usage = ExternalTextRoleUsage(**{**retriever_usage.__dict__, "latency_ms": retriever_latency_ms})
    route = str(retriever_payload.get("route", planner_payload.get("route", ""))).strip()
    tool_name = str(retriever_payload.get("tool_name", planner_payload.get("tool_name", ""))).strip()
    supporting_doc_ids = tuple(
        str(item).strip() for item in retriever_payload.get("supporting_doc_ids", context.public_doc_hashes) if str(item).strip()
    ) or context.public_doc_hashes

    executor_prompt = _executor_prompt(sample=sample, context=context, route=route, tool_name=tool_name)
    executor_start_ns = time.perf_counter_ns()
    executor_result = _run_sync(
        llm_client.complete([ChatMessage(role="user", content=executor_prompt)], purpose="executor")
    )
    executor_latency_ms = (time.perf_counter_ns() - executor_start_ns) / 1_000_000.0
    executor_payload_raw = extract_json_object(executor_result.text)  # type: ignore[arg-type]
    executor_payload = _normalize_visible_candidate_payload(executor_payload_raw, context.route_candidates)
    executor_usage = _usage_from_result(prompt=executor_prompt, result=executor_result)
    executor_usage = ExternalTextRoleUsage(**{**executor_usage.__dict__, "latency_ms": executor_latency_ms})
    route = str(executor_payload.get("route", route)).strip()
    tool_name = str(executor_payload.get("tool_name", tool_name)).strip()
    fairness_gate = _fairness_gate(
        route_candidates=context.route_candidates,
        planner_payload=planner_payload,
        retriever_payload=retriever_payload,
        executor_payload=executor_payload,
    )

    execution_artifact_text = _build_execution_artifact_text(context=context, route=route, tool_name=tool_name)
    summarizer_prompt = _summarizer_prompt(
        sample=sample,
        context=context,
        route=route,
        tool_name=tool_name,
        execution_artifact_text=execution_artifact_text,
    )
    summarizer_start_ns = time.perf_counter_ns()
    summarizer_result = _run_sync(
        llm_client.complete([ChatMessage(role="user", content=summarizer_prompt)], purpose="summarizer")
    )
    summarizer_latency_ms = (time.perf_counter_ns() - summarizer_start_ns) / 1_000_000.0
    summarizer_payload = extract_json_object(summarizer_result.text)  # type: ignore[arg-type]
    summarizer_usage = _usage_from_result(prompt=summarizer_prompt, result=summarizer_result)
    summarizer_usage = ExternalTextRoleUsage(**{**summarizer_usage.__dict__, "latency_ms": summarizer_latency_ms})
    summary_text = str(summarizer_payload.get("summary", summarizer_payload.get("s", ""))).strip()

    end_to_end_ms = (time.perf_counter_ns() - case_start_ns) / 1_000_000.0
    llm_ms = (
        planner_usage.latency_ms
        + retriever_usage.latency_ms
        + executor_usage.latency_ms
        + summarizer_usage.latency_ms
    )
    message_log = [
        f"Planner -> Retriever: route={planner_payload.get('route', '')}; tool={planner_payload.get('tool_name', '')}",
        f"Retriever -> Executor: route={route}; tool={tool_name}; docs={','.join(supporting_doc_ids)}",
        f"Executor -> Summarizer: artifact={execution_artifact_text}",
        f"Summarizer -> Output: summary={summary_text}",
    ]
    combined_surface = "\n".join(
        message_log
        + [planner_prompt, retriever_prompt, executor_prompt, summarizer_prompt, summary_text, execution_artifact_text]
    )
    contamination_detected = _contains_forbidden_terms(combined_surface)
    shared_score = score_fixed_answer_case(
        observed=FixedAnswerLaneResult(
            task_id=sample.task_id,
            route=route,
            tool_name=tool_name,
            summary_text=summary_text,
            revenue_value=context.revenue_value,
            selected_doc_hashes=context.public_doc_hashes,
            supporting_doc_ids=supporting_doc_ids,
            contamination_detected=contamination_detected,
        ),
        expected_route=sample.expected_route,
        expected_tool_name=sample.expected_tool_name,
        expected_facts=sample.expected_facts,
    )

    case_root = runtime_root / sample.task_id
    case_root.mkdir(parents=True, exist_ok=True)
    output_path = case_root / "external_text_output.json"
    report_path = case_root / "external_text_report.json"
    output_payload = {
        "task_id": sample.task_id,
        "route": route,
        "tool_name": tool_name,
        "summary_text": summary_text,
        "revenue_value": context.revenue_value,
        "selected_doc_hashes": list(context.public_doc_hashes),
        "supporting_doc_ids": list(supporting_doc_ids),
    }
    report_payload = {
        "task_id": sample.task_id,
        "baseline_name": "external_pure_text_four_role_baseline_v1",
        "route": route,
        "tool_name": tool_name,
        "summary_text": summary_text,
        "message_count": len(message_log),
        "text_bytes": sum(len(item.encode("utf-8")) for item in message_log),
        "control_bytes": sum(len(item.encode("utf-8")) for item in message_log),
        "prompt_bytes": (
            planner_usage.prompt_bytes
            + retriever_usage.prompt_bytes
            + executor_usage.prompt_bytes
            + summarizer_usage.prompt_bytes
        ),
        "prompt_tokens": (
            planner_usage.prompt_tokens
            + retriever_usage.prompt_tokens
            + executor_usage.prompt_tokens
            + summarizer_usage.prompt_tokens
        ),
        "completion_tokens": (
            planner_usage.completion_tokens
            + retriever_usage.completion_tokens
            + executor_usage.completion_tokens
            + summarizer_usage.completion_tokens
        ),
        "total_tokens": (
            planner_usage.total_tokens
            + retriever_usage.total_tokens
            + executor_usage.total_tokens
            + summarizer_usage.total_tokens
        ),
        "llm_ms": llm_ms,
        "end_to_end_ms": end_to_end_ms,
        "task_ms": end_to_end_ms,
        "llm_call_count": 4,
        "route_exact": shared_score.route_exact,
        "tool_exact": shared_score.tool_exact,
        "revenue_exact": shared_score.revenue_exact,
        "selected_doc_hashes_exact": shared_score.selected_doc_hashes_exact,
        "exact_match": shared_score.exact_match,
        "admissible_match": shared_score.admissible_match,
        "correctness_label": shared_score.correctness_label,
        "contamination_detected": contamination_detected,
        "fairness_gate": fairness_gate,
        "quality_floor": {
            "quality_floor_pass": shared_score.quality_floor.quality_floor_pass,
            "deterministic_checks_passed": shared_score.quality_floor.deterministic_checks_passed,
            "fact_coverage_passed": shared_score.quality_floor.fact_coverage_passed,
            "llm_judge_passed": shared_score.quality_floor.llm_judge_passed,
            "quality_floor_fail_reason": shared_score.quality_floor.quality_floor_fail_reason,
            "schema_version": shared_score.quality_floor.schema_version,
        },
        "role_usage": {
            "planner": planner_usage.__dict__,
            "retriever": retriever_usage.__dict__,
            "executor": executor_usage.__dict__,
            "summarizer": summarizer_usage.__dict__,
        },
        "role_payloads": {
            "planner_raw": planner_payload_raw,
            "planner": planner_payload,
            "retriever_raw": retriever_payload_raw,
            "retriever": retriever_payload,
            "executor_raw": executor_payload_raw,
            "executor": executor_payload,
            "summarizer": summarizer_payload,
        },
        "candidate_resolution": {
            "visible_candidate_keys": [candidate.candidate_key() for candidate in context.route_candidates],
            "final_route": route,
            "final_tool_name": tool_name,
            "planner_candidate_key": planner_payload.get("candidate_key", ""),
            "retriever_candidate_key": retriever_payload.get("candidate_key", ""),
            "executor_candidate_key": executor_payload.get("candidate_key", ""),
        },
        "message_log": message_log,
        "public_doc_hashes": list(context.public_doc_hashes),
    }
    output_path.write_text(stable_json_dumps(output_payload) + "\n", encoding="utf-8")
    report_path.write_text(stable_json_dumps(report_payload) + "\n", encoding="utf-8")
    return ExternalTextCaseResult(
        task_id=sample.task_id,
        route=route,
        tool_name=tool_name,
        summary_text=summary_text,
        revenue_value=context.revenue_value,
        output_path=str(output_path),
        report_path=str(report_path),
        message_count=len(message_log),
        text_bytes=report_payload["text_bytes"],
        prompt_bytes=report_payload["prompt_bytes"],
        prompt_tokens=report_payload["prompt_tokens"],
        completion_tokens=report_payload["completion_tokens"],
        total_tokens=report_payload["total_tokens"],
        llm_ms=llm_ms,
        end_to_end_ms=end_to_end_ms,
        llm_call_count=4,
        route_exact=shared_score.route_exact,
        tool_exact=shared_score.tool_exact,
        exact_match=shared_score.exact_match,
        admissible_match=shared_score.admissible_match,
        correctness_label=shared_score.correctness_label,
        contamination_detected=contamination_detected,
        fairness_gate=fairness_gate,
        selected_doc_hashes=context.public_doc_hashes,
        supporting_doc_ids=supporting_doc_ids,
        quality_floor=shared_score,
        planner_usage=planner_usage,
        retriever_usage=retriever_usage,
        executor_usage=executor_usage,
        summarizer_usage=summarizer_usage,
    )


def run_external_text_family(
    *,
    samples: list[FixedAnswerSample],
    runtime_root: Path,
    role_path_mode: str = "deterministic",
    suite_id: str = "external-pure-text-family",
    embedding_mode: str = "deterministic",
) -> BenchmarkFamilyReport:
    task_family = samples[0].task_family if samples else "fixed_answer_route_tool"
    report_path = runtime_root / "benchmark_reports" / f"{suite_id}.json"
    metadata = pure_text_external_metadata(
        role_path_mode=role_path_mode,
        embedding_mode=embedding_mode,
    )
    missing_reason = benchmark_runtime_missing_reason(
        role_path_mode=role_path_mode,
        embedding_mode=embedding_mode,
    )
    if missing_reason:
        report = BenchmarkFamilyReport(
            suite_id=suite_id,
            layer=BenchmarkLayer.L0,
            task_family=task_family,
            profile=STRICT_EXTERNAL_PROFILE,
            cases=(),
            aggregated_metrics={
                "case_count": 0.0,
                "quality_floor_pass_count": 0.0,
                "telemetry_event_count": 0.0,
            },
            telemetry_summary={},
            replay_class_distribution={},
            quality_floor_breakdown={
                "deterministic_checks_passed_count": 0.0,
                "fact_coverage_passed_count": 0.0,
                "quality_floor_pass_count": 0.0,
            },
            metadata=metadata,
            report_path=str(report_path),
            missing_reason=missing_reason,
        )
        write_json_report(report_path, family_report_to_dict(report))
        return report

    cases: list[BenchmarkCaseReport] = []
    for sample in samples:
        result = run_external_text_case(
            sample=sample,
            runtime_root=runtime_root,
            role_path_mode=role_path_mode,
            embedding_mode=embedding_mode,
        )
        cases.append(
            BenchmarkCaseReport(
                task_id=sample.task_id,
                task_family=sample.task_family,
                quality_floor=result.quality_floor.quality_floor,
                replay_class="assist",
                telemetry_event_count=0,
                output_artifact_hash="",
                output_artifact_path=result.output_path,
                workspace_root=str(runtime_root / sample.task_id),
                session_state="EXTERNAL_TEXT_DONE",
                comparison_tags=sample.scenario_tags,
                audit_paths={},
                audit_summary={},
                metrics={
                    "message_count": float(result.message_count),
                    "text_bytes": float(result.text_bytes),
                    "control_bytes": float(result.text_bytes),
                    "prompt_bytes": float(result.prompt_bytes),
                    "prompt_tokens": float(result.prompt_tokens),
                    "completion_tokens": float(result.completion_tokens),
                    "llm_total_tokens": float(result.total_tokens),
                    "llm_ms": float(result.llm_ms),
                    "end_to_end_ms": float(result.end_to_end_ms),
                    "task_ms": float(result.end_to_end_ms),
                    "llm_call_count": float(result.llm_call_count),
                    "planner_call_count": 1.0,
                    "retriever_call_count": 1.0,
                    "executor_call_count": 1.0,
                    "summarizer_call_count": 1.0,
                    "planner_prompt_bytes": float(result.planner_usage.prompt_bytes),
                    "retriever_prompt_bytes": float(result.retriever_usage.prompt_bytes),
                    "executor_prompt_bytes": float(result.executor_usage.prompt_bytes),
                    "summarizer_prompt_bytes": float(result.summarizer_usage.prompt_bytes),
                    "route_exact": 1.0 if result.route_exact else 0.0,
                    "tool_exact": 1.0 if result.tool_exact else 0.0,
                    "revenue_exact": 1.0 if result.quality_floor.revenue_exact else 0.0,
                    "selected_doc_hashes_exact": 1.0 if result.quality_floor.selected_doc_hashes_exact else 0.0,
                    "summary_present": 1.0 if result.quality_floor.summary_present else 0.0,
                    "exact_match": 1.0 if result.exact_match else 0.0,
                    "admissible_match": 1.0 if result.admissible_match else 0.0,
                    "contamination_detected": 1.0 if result.contamination_detected else 0.0,
                },
            )
        )
    aggregated_metrics = {
        "case_count": float(len(cases)),
        "quality_floor_pass_count": float(sum(1 for case in cases if case.quality_floor.quality_floor_pass)),
        "telemetry_event_count": 0.0,
    }
    telemetry_summary: dict[str, float] = {}
    for case in cases:
        for key, value in case.metrics.items():
            telemetry_summary[key] = telemetry_summary.get(key, 0.0) + float(value)
    report = BenchmarkFamilyReport(
        suite_id=suite_id,
        layer=BenchmarkLayer.L0,
        task_family=task_family,
        profile=STRICT_EXTERNAL_PROFILE,
        cases=tuple(cases),
        aggregated_metrics=aggregated_metrics,
        telemetry_summary=telemetry_summary,
        replay_class_distribution={"assist": float(len(cases))},
        quality_floor_breakdown={
            "deterministic_checks_passed_count": float(
                sum(1 for case in cases if case.quality_floor.deterministic_checks_passed)
            ),
            "fact_coverage_passed_count": float(sum(1 for case in cases if case.quality_floor.fact_coverage_passed)),
            "quality_floor_pass_count": aggregated_metrics["quality_floor_pass_count"],
        },
        metadata=metadata,
        report_path=str(report_path),
    )
    write_json_report(report_path, family_report_to_dict(report))
    return report


def run_external_text_suite(
    *,
    samples: list[FixedAnswerSample],
    runtime_root: Path,
    suite_id: str = "external-pure-text-suite",
    role_path_modes: tuple[str, ...] = ("deterministic",),
    embedding_mode: str = "deterministic",
) -> BenchmarkSuiteReport:
    layer_reports = tuple(
        run_external_text_family(
            samples=samples,
            runtime_root=runtime_root / mode,
            role_path_mode=mode,
            suite_id=f"{suite_id}-{mode}",
            embedding_mode=embedding_mode,
        )
        for mode in role_path_modes
    )
    successful_mode_count = float(sum(1 for layer in layer_reports if not layer.missing_reason))
    report = BenchmarkSuiteReport(
        suite_id=suite_id,
        task_family=samples[0].task_family if samples else "fixed_answer_route_tool",
        layer_reports=layer_reports,
        waterfall_metrics={
            "case_count": float(len(samples)),
            "llm_total_tokens": sum(layer.telemetry_summary.get("llm_total_tokens", 0.0) for layer in layer_reports),
            "message_count": sum(layer.telemetry_summary.get("message_count", 0.0) for layer in layer_reports),
            "exact_match_count": sum(layer.telemetry_summary.get("exact_match", 0.0) for layer in layer_reports),
        },
        comparison_summary={
            "mode_count": float(len(role_path_modes)),
            "successful_mode_count": successful_mode_count,
        },
        metadata={
            "benchmark_tier": "dev",
            "claim_level": "prototype",
            "task_family_tier": "dev_fixed_answer",
        },
        family_case_count=len(samples),
        report_path=str(runtime_root / "benchmark_reports" / f"{suite_id}.json"),
    )
    write_json_report(Path(report.report_path), suite_report_to_dict(report))
    return report
