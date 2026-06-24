from __future__ import annotations

from protocol.messages import Plan, PlanStep
from eval.fairness_gates import evaluate_execution_fairness_gate, evaluate_plan_fairness_gate
from eval.metrics import TaskMetrics
from eval.runner import _build_headline_gates


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


def test_execution_fairness_gate_fails_closed_on_text_typed_state_leakage() -> None:
    plan = Plan(
        task_id="task-3",
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
        role_context_slices={
            "planner": type("Slice", (), {"carrier": "text_whole_lane", "visible_state_ids": (), "projection_class": "planner_text_brief", "included_fields": ("goal",), "omitted_fields": ("typed_state_payloads",), "role_visible_contract": "planner_contract_v1", "helper_visibility": "declared_only", "model_visibility": "same_model_required", "tool_visibility": "catalog_visible", "corpus_visibility": "task_scope_only"})(),
            "retriever": type("Slice", (), {"carrier": "text_whole_lane", "visible_state_ids": (), "projection_class": "retriever_text_brief", "included_fields": ("query",), "omitted_fields": ("typed_state_payloads",), "role_visible_contract": "retriever_contract_v1", "helper_visibility": "declared_only", "model_visibility": "same_model_required", "tool_visibility": "catalog_visible", "corpus_visibility": "task_scope_only"})(),
            "executor": type("Slice", (), {"carrier": "text_whole_lane", "visible_state_ids": ("state-1",), "projection_class": "executor_text_handoff", "included_fields": ("retrieval_evidence",), "omitted_fields": ("full_feature_bundle_payload",), "role_visible_contract": "executor_contract_v1", "helper_visibility": "declared_only", "model_visibility": "same_model_required", "tool_visibility": "catalog_visible", "corpus_visibility": "retrieved_only"})(),
            "summarizer": type("Slice", (), {"carrier": "text_whole_lane", "visible_state_ids": (), "projection_class": "summarizer_text_handoff", "included_fields": ("summary_hint",), "omitted_fields": ("full_typed_packet_dump",), "role_visible_contract": "summarizer_contract_v1", "helper_visibility": "declared_only", "model_visibility": "same_model_required", "tool_visibility": "artifact_only", "corpus_visibility": "retrieved_only"})(),
        },
        role_trace=[
            {"role": "planner", "input_state_ids": []},
            {"role": "retriever", "input_state_ids": []},
            {"role": "executor", "input_state_ids": ["state-1"]},
            {"role": "summarizer", "input_state_ids": []},
        ],
        contract_errors=[],
    )

    assert gate.passed is False
    assert gate.text_typed_state_leak_roles == ("executor",)


def test_execution_fairness_gate_fails_closed_on_unbounded_protocol_projection_and_hidden_helper() -> None:
    plan = Plan(
        task_id="task-4",
        goal="goal",
        steps=[
            PlanStep("planner", "planner", "PLAN", [], {}, [], semantic_role="planner"),
            PlanStep("retrieve", "retriever", "RETRIEVE_EVIDENCE", [], {}, ["planner"], semantic_role="retrieve"),
            PlanStep("execute", "executor", "EXECUTE_PLAYBOOK", [], {}, ["retrieve"], semantic_role="execute"),
            PlanStep("summarize", "summarizer", "SUMMARIZE_AND_COMMIT", [], {}, ["execute"], semantic_role="summarize"),
        ],
    )

    bad_slice = type(
        "Slice",
        (),
        {
            "carrier": "protocol_full_rich_audit",
            "visible_state_ids": ("state-1",),
            "projection_class": "",
            "included_fields": (),
            "omitted_fields": (),
            "role_visible_contract": "",
            "helper_visibility": "hidden_helper",
            "model_visibility": "same_model_required",
            "tool_visibility": "catalog_visible",
            "corpus_visibility": "retrieved_only",
        },
    )()
    ok_slice = type(
        "Slice",
        (),
        {
            "carrier": "protocol_full_rich_audit",
            "visible_state_ids": (),
            "projection_class": "planner_statebus_brief",
            "included_fields": ("goal",),
            "omitted_fields": ("typed_state_payloads",),
            "role_visible_contract": "planner_contract_v1",
            "helper_visibility": "declared_only",
            "model_visibility": "same_model_required",
            "tool_visibility": "catalog_visible",
            "corpus_visibility": "task_scope_only",
        },
    )()

    gate = evaluate_execution_fairness_gate(
        plan=plan,
        role_context_slices={
            "planner": ok_slice,
            "retriever": ok_slice,
            "executor": bad_slice,
            "summarizer": ok_slice,
        },
        role_trace=[
            {"role": "planner", "input_state_ids": []},
            {"role": "retriever", "input_state_ids": []},
            {"role": "executor", "input_state_ids": ["state-1"]},
            {"role": "summarizer", "input_state_ids": []},
        ],
        contract_errors=[],
    )

    assert gate.passed is False
    assert gate.unbounded_projection_roles == ("executor",)
    assert gate.hidden_helper_roles == ("executor",)


def test_execution_fairness_gate_requires_actual_parity_evidence_and_non_dominant_helper() -> None:
    plan = Plan(
        task_id="task-5",
        goal="goal",
        steps=[
            PlanStep("planner", "planner", "PLAN", [], {}, [], semantic_role="planner"),
            PlanStep("retrieve", "retriever", "RETRIEVE_EVIDENCE", [], {}, ["planner"], semantic_role="retrieve"),
            PlanStep("execute", "executor", "EXECUTE_PLAYBOOK", [], {}, ["retrieve"], semantic_role="execute"),
            PlanStep("summarize", "summarizer", "SUMMARIZE_AND_COMMIT", [], {}, ["execute"], semantic_role="summarize"),
        ],
    )

    def _slice(role: str, *, decision_source: str = "role_llm") -> object:
        return type(
            "Slice",
            (),
            {
                "carrier": "state_packet_minimal",
                "visible_state_ids": (),
                "projection_class": "bounded",
                "included_fields": ("a",),
                "omitted_fields": ("b",),
                "role_visible_contract": f"{role}_contract_v1",
                "helper_visibility": "declared_only",
                "model_visibility": "same_model_required",
                "tool_visibility": "catalog_visible",
                "corpus_visibility": "retrieved_only",
                "metadata": {
                    "actual_llm_model": "det-model",
                    "actual_tool_catalog": ["tool.a"],
                    "actual_tool_candidates": ["r::tool.a"],
                    "actual_corpus_scope": ["doc-1"],
                    "decision_source": decision_source,
                },
            },
        )()

    gate = evaluate_execution_fairness_gate(
        plan=plan,
        role_context_slices={
            "planner": _slice("planner"),
            "retriever": _slice("retriever", decision_source="helper_selected_directly"),
            "executor": _slice("executor"),
            "summarizer": _slice("summarizer"),
        },
        role_trace=[
            {"role": "planner", "input_state_ids": [], "semantic_trace": {}},
            {"role": "retriever", "input_state_ids": [], "semantic_trace": {"helper_selected_directly": True}},
            {"role": "executor", "input_state_ids": [], "semantic_trace": {"helper_selected_directly": False}},
            {"role": "summarizer", "input_state_ids": [], "semantic_trace": {}},
        ],
        contract_errors=[],
    )

    assert gate.passed is False
    assert gate.helper_dominance_roles == ("retriever",)


def test_headline_gates_surface_cross_lane_actual_parity_failure() -> None:
    gates = _build_headline_gates(
        pack_type="memory_dual_mode_fairness_v3",
        withheld_reasons=["cross_lane_actual_parity_failed", "dual_mode_object_parity_failed"],
        formal_stability_gate={"passed": True},
        object_parity_gate={"passed": False, "cross_lane_actual_parity_ok": False},
        cross_lane_actual_parity={
            "passed": False,
            "applicable": True,
            "mismatch_counts": {
                "model": 1,
                "tool_catalog": 1,
                "tool_candidates": 0,
                "corpus_scope": 0,
            },
        },
        memory_replay_evidence_gate={"applicable": False, "passed": False},
        contest_formal_coverage_gate={"passed": False},
    )

    assert gates["object_parity_gate"]["applicable"] is True
    assert gates["object_parity_gate"]["allowed"] is False
    assert "cross_lane_actual_parity_failed" in gates["object_parity_gate"]["withheld_reasons"]
    assert gates["object_parity_gate"]["cross_lane_actual_parity"]["passed"] is False


def test_superiority_headline_gate_downgrades_actual_parity_to_diagnostic() -> None:
    gates = _build_headline_gates(
        pack_type="contest_superiority_headline_v2",
        withheld_reasons=["contest_repeat_insufficient", "cross_lane_actual_parity_failed"],
        formal_stability_gate={"passed": False},
        object_parity_gate={"passed": False, "cross_lane_actual_parity_ok": False},
        cross_lane_actual_parity={
            "passed": False,
            "applicable": True,
            "mismatch_counts": {
                "model": 0,
                "tool_catalog": 0,
                "tool_candidates": 2,
                "corpus_scope": 4,
            },
        },
        memory_replay_evidence_gate={"applicable": False, "passed": False},
        contest_formal_coverage_gate={"passed": False},
    )

    assert gates["primary_headline_gate"]["allowed"] is False
    assert gates["primary_headline_gate"]["withheld_reasons"] == ["contest_repeat_insufficient"]
    assert gates["superiority_scaffold_gate"]["withheld_reasons"] == ["contest_repeat_insufficient"]
    assert gates["superiority_scaffold_gate"]["diagnostic_reasons"] == ["cross_lane_actual_parity_failed"]
