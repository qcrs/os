#!/usr/bin/env python3

"""Unit tests for delayed long-term-memory admission rules."""

import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from memory_writer import (
    commit_memory_candidates,
    evaluate_memory_candidates,
    make_memory_candidate,
)


QUERY = "Compute the mean.\nExpected answer format: @mean[number]"


def _csv_state(*, ok=True, answer="42.00", include_route=True):
    trace = [{"stage": "codeact.route", "kind": "table_csv"}] if include_route else []
    return {
        "query": QUERY,
        "task_group": "csv_group",
        "artifact_refs": [{"kind": "csv", "path": "/tmp/input.csv"}],
        "execution_result": {
            "ok": ok,
            "final_answer": f"@mean[{answer}]",
            "extracted_answers": {"mean": answer},
        },
        "execution_trace": trace,
    }


def _candidate(memory_type="summary", *, evidence=True):
    evidence_refs = [{"claim": "mean is 42", "support": "computed from input"}] if evidence else []
    return make_memory_candidate(
        memory_type=memory_type,
        source_agent="test",
        task_group="csv_group",
        task_topic="CSV analysis",
        query=QUERY,
        value={"text": "The computed mean is 42."},
        summary="The computed mean is 42.",
        evidence_refs=evidence_refs,
    )


def main() -> None:
    candidate = _candidate()

    accepted, rejected = evaluate_memory_candidates(_csv_state(), [candidate])
    assert accepted == [candidate], rejected
    assert not rejected

    _, rejected = evaluate_memory_candidates(_csv_state(answer="unknown"), [candidate])
    assert rejected[0]["reason"] == "csv_answers_incomplete_or_unknown", rejected

    _, rejected = evaluate_memory_candidates(_csv_state(include_route=False), [candidate])
    assert rejected[0]["reason"] == "csv_codeact_not_run", rejected

    _, rejected = evaluate_memory_candidates(_csv_state(), [_candidate("task_state")])
    assert rejected[0]["reason"] == "csv_task_state_not_committed", rejected

    research_state = {"query": "Explain the system design.", "artifact_refs": []}
    research_candidate = _candidate(evidence=False)
    _, rejected = evaluate_memory_candidates(research_state, [research_candidate])
    assert rejected[0]["reason"] == "insufficient_evidence_or_context_verification", rejected

    writes = []

    def writer(**kwargs):
        writes.append(kwargs)
        return {"id": "memory-1"}

    analysis_candidate = _candidate("analysis")
    result = commit_memory_candidates(_csv_state(), [analysis_candidate, candidate], writer=writer)
    assert result["accepted_count"] == 1, result
    assert len(result["committed"]) == 1, result
    assert len(writes) == 1, writes
    assert writes[0]["memory_type"] == "summary", writes
    assert "Final answer: @mean[42.00]" in writes[0]["value"]["text"], writes

    unavailable = commit_memory_candidates(_csv_state(), [candidate], writer=lambda **_: None)
    assert not unavailable["committed"], unavailable
    assert len(unavailable["not_stored"]) == 1, unavailable

    print("memory commit policy tests passed")


if __name__ == "__main__":
    main()
