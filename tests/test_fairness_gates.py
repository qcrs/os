from __future__ import annotations

from eval.metrics import TaskMetrics


def test_role_usage_metrics_accumulate_by_role() -> None:
    metrics = TaskMetrics()

    metrics.record_role_llm_usage(
        role="planner",
        prompt_tokens=11,
        completion_tokens=7,
        total_tokens=18,
    )
    metrics.record_role_llm_usage(
        role="summarize",
        prompt_tokens=5,
        completion_tokens=3,
        total_tokens=8,
    )
    metrics.record_role_latency(role="execute", elapsed_ms=12.5)

    assert metrics.role_usage["planner"].llm_request_count == 1
    assert metrics.role_usage["planner"].total_tokens == 18
    assert metrics.role_usage["summarizer"].total_tokens == 8
    assert metrics.role_usage["executor"].latency_ms == 12.5


def test_role_usage_metrics_are_serialized_in_task_metrics_dict() -> None:
    metrics = TaskMetrics()
    metrics.record_role_llm_usage(role="retrieve", total_tokens=4)

    payload = metrics.to_dict()

    assert payload["role_usage"]["retriever"]["total_tokens"] == 4
