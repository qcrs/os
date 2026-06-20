from __future__ import annotations

from protocol.messages import Plan, PlanStep
from eval.fairness_gates import evaluate_execution_fairness_gate, evaluate_plan_fairness_gate
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


def test_plan_fairness_gate_fails_closed_when_four_roles_are_incomplete() -> None:
    plan = Plan(
        task_id="task-1",
        goal="goal",
        steps=[
            PlanStep(
                step_id="retrieve",
                owner_agent="retriever",
                action="RETRIEVE_EVIDENCE",
                input_state_refs=[],
                params={},
                depends_on=[],
                semantic_role="retrieve",
            ),
            PlanStep(
                step_id="summarize",
                owner_agent="summarizer",
                action="SUMMARIZE_AND_COMMIT",
                input_state_refs=[],
                params={},
                depends_on=["retrieve"],
                semantic_role="summarize",
            ),
        ],
    )

    gate = evaluate_plan_fairness_gate(plan)

    assert gate.passed is False
    assert gate.missing_plan_roles == ("executor",)


def test_execution_fairness_gate_requires_context_and_trace_for_all_roles() -> None:
    plan = Plan(
        task_id="task-2",
        goal="goal",
        steps=[
            PlanStep("planner", "planner", "PLAN", [], {}, [], semantic_role="planner"),
            PlanStep("retrieve", "retriever", "RETRIEVE_EVIDENCE", [], {}, ["planner"], semantic_role="retrieve"),
            PlanStep("execute", "executor", "EXECUTE_PLAYBOOK", [], {}, ["retrieve"], semantic_role="execute"),
            PlanStep("summarize", "summarizer", "SUMMARIZE_AND_COMMIT", [], {}, ["execute"], semantic_role="summarize"),
        ],
    )

    gate = evaluate_execution_fairness_gate(
        plan=plan,
        role_context_slices={"planner": {}, "retriever": {}, "executor": {}},
        role_trace=[
            {"role": "planner"},
            {"role": "retriever"},
            {"role": "executor"},
        ],
        contract_errors=[],
    )

    assert gate.passed is False
    assert gate.missing_context_roles == ("summarizer",)
    assert gate.missing_trace_roles == ("summarizer",)
