"""Candidate-memory policy and deterministic long-term commit helpers."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Sequence
from typing import Any

from memory import qdrant_add_from_payload
from metrics import metrics
from protocol import hash_text


_ANSWER_FIELD_RE = re.compile(r"@(\w+)\[")
_MISSING_ANSWER_VALUES = {
    "",
    "unknown",
    "unk",
    "n/a",
    "none",
    "null",
    "nan",
    "未识别",
    "未知",
}
_SUMMARY_PRIORITY = {"summary": 0, "analysis": 1, "task_state": 2}


def make_memory_candidate(
    *,
    memory_type: str,
    source_agent: str,
    task_group: str,
    task_topic: str,
    query: str,
    value: dict,
    summary: str,
    tags: Sequence[str] | None = None,
    evidence_refs: Sequence[dict] | None = None,
    context_verification: dict | None = None,
) -> dict:
    """Create one task-local candidate without writing it to long-term memory."""
    scope_seed = f"{task_group}\n{query}".strip()
    memory_scope_id = f"{task_group}_{hash_text(scope_seed)}"
    return {
        "memory_type": str(memory_type),
        "source_agent": str(source_agent),
        "source_task_id": f"{memory_type}_{memory_scope_id}",
        "memory_scope_id": memory_scope_id,
        "task_group": str(task_group),
        "task_topic": str(task_topic),
        "value": dict(value or {}),
        "summary": str(summary or "").strip(),
        "tags": [str(tag) for tag in (tags or []) if str(tag).strip()],
        "evidence_refs": [dict(item) for item in (evidence_refs or []) if isinstance(item, dict)],
        "context_verification": dict(context_verification or {}),
    }


def commit_memory_candidates(
    state: dict,
    candidates: Sequence[dict] | None = None,
    *,
    writer: Callable[..., Any] = qdrant_add_from_payload,
) -> dict:
    """Validate, deduplicate, and persist task candidates without any LLM call."""
    candidates = [dict(candidate) for candidate in (candidates or state.get("pending_memory_candidates", []))]
    task_kind = classify_task(state)
    accepted, rejected = evaluate_memory_candidates(state, candidates, task_kind=task_kind)
    accepted = _materialize_commit_candidates(state, accepted, task_kind=task_kind)
    deduplicated, duplicates = _deduplicate_candidates(accepted)
    rejected.extend({"candidate": candidate, "reason": "duplicate_task_content"} for candidate in duplicates)

    committed = []
    not_stored = []
    write_failures = []
    started_at = time.perf_counter()
    for candidate in deduplicated:
        try:
            result = writer(
                key=candidate["source_task_id"],
                value=candidate["value"],
                memory_type=candidate["memory_type"],
                source_agent=candidate["source_agent"],
                task_group=candidate["task_group"],
                task_topic=candidate["task_topic"],
                summary=candidate["summary"],
                tags=candidate["tags"],
            )
        except Exception as exc:
            write_failures.append({
                "candidate": candidate,
                "error": f"{type(exc).__name__}: {exc}",
            })
            metrics.increment("memory_commit_write_failures")
            continue
        record = {
            "source_task_id": candidate["source_task_id"],
            "memory_type": candidate["memory_type"],
            "memory_scope_id": candidate["memory_scope_id"],
            "stored": result is not None,
        }
        if result is None:
            record["reason"] = "long_term_memory_unavailable_or_write_skipped"
            not_stored.append(record)
            metrics.increment("memory_candidates_not_stored")
        else:
            committed.append(record)
            metrics.increment("memory_candidates_committed")

    metrics.increment("memory_candidates_seen", len(candidates))
    metrics.increment("memory_candidates_rejected", len(rejected))
    metrics.record_timing("memory_commit", time.perf_counter() - started_at)
    return {
        "task_kind": task_kind,
        "accepted_count": len(deduplicated),
        "rejected_count": len(rejected),
        "committed": committed,
        "not_stored": not_stored,
        "rejected": [_rejection_record(item) for item in rejected],
        "write_failures": [_failure_record(item) for item in write_failures],
    }


def evaluate_memory_candidates(
    state: dict,
    candidates: Sequence[dict],
    *,
    task_kind: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """Apply task-sensitive admission rules without touching Qdrant."""
    task_kind = task_kind or classify_task(state)
    accepted: list[dict] = []
    rejected: list[dict] = []
    csv_codeact_ok, csv_reason = _csv_codeact_is_acceptable(state)

    for raw_candidate in candidates:
        candidate = dict(raw_candidate or {})
        reason = _candidate_rejection_reason(
            candidate,
            task_kind=task_kind,
            csv_codeact_ok=csv_codeact_ok,
            csv_reason=csv_reason,
        )
        if reason:
            rejected.append({"candidate": candidate, "reason": reason})
        else:
            accepted.append(candidate)
    return accepted, rejected


def classify_task(state: dict) -> str:
    """Classify only the task types that require a stricter write policy."""
    for artifact in state.get("artifact_refs", []) or []:
        if not isinstance(artifact, dict):
            continue
        kind = str(artifact.get("kind", "")).lower()
        path = str(artifact.get("path", "")).lower()
        if kind in {"csv", "table_csv"} or path.endswith(".csv"):
            return "csv"
    return "research"


def _candidate_rejection_reason(
    candidate: dict,
    *,
    task_kind: str,
    csv_codeact_ok: bool,
    csv_reason: str,
) -> str:
    memory_type = str(candidate.get("memory_type", "")).strip()
    if memory_type not in {"analysis", "summary", "task_state"}:
        return "unsupported_memory_type"
    if not str(candidate.get("summary", "")).strip():
        return "empty_summary"
    if not isinstance(candidate.get("value"), dict):
        return "invalid_value"

    if task_kind == "csv":
        if not csv_codeact_ok:
            return csv_reason
        if memory_type == "task_state":
            return "csv_task_state_not_committed"
        return ""

    if memory_type == "task_state" and not _has_stable_task_state(candidate["value"].get("task_state")):
        return "empty_task_state"
    if not _has_supported_evidence(candidate):
        return "insufficient_evidence_or_context_verification"
    return ""


def _materialize_commit_candidates(
    state: dict,
    candidates: Sequence[dict],
    *,
    task_kind: str,
) -> list[dict]:
    """Remove LLM prose from CSV fact records after the CodeAct gate passes."""
    if task_kind != "csv":
        return [dict(candidate) for candidate in candidates]

    execution_result = state.get("execution_result", {}) or {}
    final_answer = str(state.get("final_answer") or execution_result.get("final_answer") or "").strip()
    extracted_answers = execution_result.get("extracted_answers", {}) or state.get("extracted_answers", {}) or {}
    if not final_answer and isinstance(extracted_answers, dict):
        final_answer = " ".join(
            f"@{field}[{value}]" for field, value in extracted_answers.items()
        )
    execution_summary = str(state.get("execution_summary", "") or "").strip()
    canonical_text = "\n".join([
        "CodeAct CSV result (execution completed).",
        f"Final answer: {final_answer}",
        "Extracted answers: " + json.dumps(extracted_answers, ensure_ascii=False, sort_keys=True),
        *( [f"Execution summary: {execution_summary}"] if execution_summary else [] ),
    ])

    materialized = []
    for raw_candidate in candidates:
        candidate = dict(raw_candidate)
        value = {
            "text": canonical_text,
            "final_answer": final_answer,
            "extracted_answers": dict(extracted_answers),
            "execution_summary": execution_summary,
            "task_topic": candidate["task_topic"],
            "query": state.get("query", ""),
            "verification": "codeact_completed",
        }
        candidate["value"] = value
        candidate["summary"] = canonical_text
        candidate["tags"] = list(dict.fromkeys([*candidate.get("tags", []), "csv", "codeact_completed"]))
        materialized.append(candidate)
    return materialized


def _csv_codeact_is_acceptable(state: dict) -> tuple[bool, str]:
    execution_result = state.get("execution_result", {}) or {}
    if not isinstance(execution_result, dict) or not execution_result.get("ok"):
        return False, "csv_codeact_failed"

    traces = state.get("execution_trace", []) or execution_result.get("trace", []) or []
    has_csv_codeact_route = any(
        isinstance(item, dict)
        and item.get("stage") == "codeact.route"
        and item.get("kind") == "table_csv"
        for item in traces
    )
    if not has_csv_codeact_route:
        return False, "csv_codeact_not_run"

    required_fields = _required_answer_fields(str(state.get("query", "")))
    if not required_fields:
        return False, "csv_answer_format_not_machine_checkable"
    extracted = execution_result.get("extracted_answers", {}) or state.get("extracted_answers", {}) or {}
    if not isinstance(extracted, dict):
        return False, "csv_answers_invalid"
    missing = [
        field for field in required_fields
        if _is_missing_answer(extracted.get(field, ""))
    ]
    if missing:
        return False, "csv_answers_incomplete_or_unknown"
    return True, ""


def _has_supported_evidence(candidate: dict) -> bool:
    evidence = candidate.get("evidence_refs", []) or []
    if any(
        isinstance(item, dict)
        and str(item.get("claim", "")).strip()
        and str(item.get("support", "")).strip()
        for item in evidence
    ):
        return True

    verification = candidate.get("context_verification", {}) or {}
    if not isinstance(verification, dict):
        return False
    checked = int(verification.get("checked", 0) or 0)
    trustworthy = int(verification.get("reliable", 0) or 0) + int(
        verification.get("rehydrated", 0) or 0
    )
    return checked > 0 and trustworthy > 0


def _has_stable_task_state(task_state: object) -> bool:
    if not isinstance(task_state, dict):
        return False
    for value in task_state.values():
        if isinstance(value, dict) and value:
            return True
        if isinstance(value, (list, tuple, set)) and value:
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False


def _required_answer_fields(query: str) -> list[str]:
    return list(dict.fromkeys(_ANSWER_FIELD_RE.findall(query or "")))


def _is_missing_answer(value: object) -> bool:
    return str(value or "").strip().lower() in _MISSING_ANSWER_VALUES


def _deduplicate_candidates(candidates: Sequence[dict]) -> tuple[list[dict], list[dict]]:
    ordered = sorted(
        candidates,
        key=lambda item: _SUMMARY_PRIORITY.get(str(item.get("memory_type", "")), 99),
    )
    deduplicated: list[dict] = []
    duplicates: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for candidate in ordered:
        content = _normalise_candidate_content(candidate)
        key = (str(candidate.get("memory_scope_id", "")), content)
        if not content or key in seen:
            duplicates.append(candidate)
            continue
        seen.add(key)
        deduplicated.append(candidate)
    return deduplicated, duplicates


def _normalise_candidate_content(candidate: dict) -> str:
    value = candidate.get("value", {}) or {}
    text = value.get("text") if isinstance(value, dict) else ""
    return " ".join(str(text or candidate.get("summary", "")).split()).lower()


def _rejection_record(item: dict) -> dict:
    candidate = item["candidate"]
    return {
        "memory_type": candidate.get("memory_type", ""),
        "source_task_id": candidate.get("source_task_id", ""),
        "reason": item["reason"],
    }


def _failure_record(item: dict) -> dict:
    candidate = item["candidate"]
    return {
        "memory_type": candidate.get("memory_type", ""),
        "source_task_id": candidate.get("source_task_id", ""),
        "error": item["error"],
    }
