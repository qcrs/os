from __future__ import annotations

import subprocess

import pytest

from scripts.v2_diagnostics import run_adaptive_agent_smoke
from v2.contracts import EvidenceRequest


def test_isolated_role_timeout_returns_structured_failure(monkeypatch) -> None:
    monkeypatch.setenv("STATEBUS_ADAPTIVE_ROLE_WORKER_TIMEOUT_S", "7")

    def timeout(*args, **kwargs):
        del args, kwargs
        raise subprocess.TimeoutExpired(cmd=["python3", "--role-worker", "planner"], timeout=7)

    monkeypatch.setattr(run_adaptive_agent_smoke.subprocess, "run", timeout)
    result = run_adaptive_agent_smoke._isolated_role_completion("planner", {"task_id": "task-1"})

    assert result.candidate == {}
    assert result.error == "planner_worker_timeout:7.0s"
    assert result.attempts[0]["error"] == result.error
    assert result.request_audit["content_persisted"] is False
    assert result.request_audit["request_count"] == 0


def test_isolated_role_nonzero_exit_returns_structured_failure(monkeypatch) -> None:
    completed = subprocess.CompletedProcess(
        args=["python3", "--role-worker", "executor"],
        returncode=1,
        stdout="worker stdout",
        stderr="worker stderr",
    )
    monkeypatch.setattr(run_adaptive_agent_smoke.subprocess, "run", lambda *args, **kwargs: completed)

    result = run_adaptive_agent_smoke._isolated_role_completion("executor", {})

    assert result.candidate == {}
    assert "executor_worker_failed:exit=1" in result.error
    assert "worker stdout" in result.error
    assert "worker stderr" in result.error


def test_role_max_tokens_override_is_positive_integer(monkeypatch) -> None:
    assert run_adaptive_agent_smoke._role_max_tokens_override("summarizer") is None
    monkeypatch.setenv("STATEBUS_ADAPTIVE_SUMMARIZER_MAX_TOKENS", "1400")
    assert run_adaptive_agent_smoke._role_max_tokens_override("summarizer") == 1400
    monkeypatch.setenv("STATEBUS_ADAPTIVE_SUMMARIZER_MAX_TOKENS", "invalid")
    with pytest.raises(ValueError, match="adaptive_summarizer_max_tokens_not_integer"):
        run_adaptive_agent_smoke._role_max_tokens_override("summarizer")


def test_controller_expansion_preserves_retriever_authority_and_deduplicates_queries() -> None:
    request = EvidenceRequest(
        request_id="request",
        task_id="task",
        step_id="retrieve",
        queries=("base query",),
        evidence_types=("semantic_context", "table"),
        target_entities=("ACME",),
        time_scope="2025Q4 to 2026Q1",
        corpus_scope_ids=("local-long-doc",),
        memory_policy="assist",
        max_candidates=8,
    )
    expansion = run_adaptive_agent_smoke._controlled_expansion_request(
        request,
        task_goal="Find ACME revenue evidence.",
        existing_query_hashes=(run_adaptive_agent_smoke.sha256_digest("base query"),),
    )

    assert expansion is not None
    assert expansion.queries != request.queries
    assert expansion.corpus_scope_ids == request.corpus_scope_ids
    assert expansion.evidence_types == request.evidence_types
    assert expansion.target_entities == request.target_entities
    assert expansion.time_scope == request.time_scope
    assert expansion.memory_policy == request.memory_policy
