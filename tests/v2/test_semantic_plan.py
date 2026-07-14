from __future__ import annotations

from v2.contracts import CanonicalTaskSpec
from v2.retrieval import RetrieverFanoutPipeline
from v2.runtime.semantic_plan import (
    compare_semantic_task_plans,
    resolve_semantic_task_plan,
)
from v2.utils import sha256_digest


def _spec() -> CanonicalTaskSpec:
    return CanonicalTaskSpec(
        task_family="financial_report_analysis",
        intent_op="compute_trend",
        target_entities=("ACME",),
        time_scope="2026Q1-2026Q3",
        required_outputs=("summary_text", "delta"),
        required_tools=("table_retriever",),
        arguments={"ticker": "ACME", "quarter": "2026Q1", "metric": "revenue"},
    )


def _model_plan() -> dict[str, object]:
    return {
        "semantic_task_plan": {
            "task_semantics": {
                "goal": "Measure the revenue trend for ACME.",
                "entities": ["ACME", "revenue"],
                "time_scope": "2026Q1-2026Q3",
            },
            "retrieval_objectives": {
                "lexical_metadata": {
                    "query_text": "ACME 2026 quarterly report",
                    "objective": "locate the report scope",
                    "evidence_types": ["lexical_metadata"],
                },
                "semantic_chunk": {
                    "query_text": "ACME revenue trend explanation",
                    "objective": "find explanatory cited text",
                    "evidence_types": ["semantic_context", "citation"],
                },
                "table_structure": {
                    "query_text": "ACME revenue values 2026Q1 through 2026Q3",
                    "objective": "find the cells needed for the trend",
                    "evidence_types": ["table_cell", "table_schema"],
                },
                "memory": {
                    "query_text": "prior compatible ACME revenue trend artifacts",
                    "objective": "find reusable validated analysis context",
                    "evidence_types": ["memory_artifact", "memory_strategy"],
                    "reuse_intent": "assist",
                },
            },
            "required_evidence": ["table_cell", "semantic_context", "citation"],
            "required_outputs": ["summary_text", "delta"],
        }
    }


def test_semantic_plan_hybrid_is_valid_and_behavioral() -> None:
    resolution = resolve_semantic_task_plan(
        spec=_spec(),
        goal="Compute the requested trend.",
        fallback_query_text="ACME 2026Q1 revenue compute_trend",
        model_payload=_model_plan(),
    )

    assert resolution.semantic_plan_valid is True
    assert resolution.semantic_equivalence is True
    assert resolution.objective_source == "hybrid"
    assert resolution.model_generated_field_count > 0
    assert resolution.behavioral_effect is True
    objectives = resolution.effective_plan["retrieval_objectives"]
    assert len({objective["query_text"] for objective in objectives.values()}) == 4


def test_semantic_plan_forbidden_tool_field_falls_back() -> None:
    payload = _model_plan()
    payload["semantic_task_plan"]["tool_name"] = "table_retriever"

    resolution = resolve_semantic_task_plan(
        spec=_spec(),
        goal="Compute the requested trend.",
        fallback_query_text="ACME 2026Q1 revenue compute_trend",
        model_payload=payload,
    )

    assert resolution.semantic_plan_valid is False
    assert resolution.objective_source == "runtime_fallback"
    assert resolution.effective_plan_hash == resolution.fallback_plan_hash
    assert any(error.startswith("forbidden_field:") for error in resolution.validation_errors)


def test_semantic_plan_disabled_mode_preserves_model_audit_but_uses_fallback() -> None:
    resolution = resolve_semantic_task_plan(
        spec=_spec(),
        goal="Compute the requested trend.",
        fallback_query_text="ACME 2026Q1 revenue compute_trend",
        model_payload=_model_plan(),
        consumption_mode="disabled",
    )

    assert resolution.semantic_plan_valid is True
    assert resolution.model_plan_hash
    assert resolution.objective_source == "runtime_fallback"
    assert resolution.behavioral_effect is False
    assert resolution.effective_plan_hash == resolution.fallback_plan_hash


def test_retriever_consumes_all_bounded_objectives() -> None:
    resolution = resolve_semantic_task_plan(
        spec=_spec(),
        goal="Compute the requested trend.",
        fallback_query_text="ACME 2026Q1 revenue compute_trend",
        model_payload=_model_plan(),
    )
    bundle = RetrieverFanoutPipeline.with_embedding_mode("deterministic").run(
        task_id="semantic-plan-test",
        spec=_spec(),
        planner_scope_payload={
            "query_text": resolution.effective_plan["retrieval_objectives"]["semantic_chunk"]["query_text"],
            "semantic_task_plan": resolution.effective_plan,
        },
    )

    expected_hashes = {
        name: sha256_digest(objective)
        for name, objective in resolution.effective_plan["retrieval_objectives"].items()
    }
    assert bundle.consumed_objective_hashes == expected_hashes
    assert bundle.memory_query_embedding is not None
    assert bundle.memory_query_embedding.embedding_hash != bundle.query_embedding.embedding_hash


def test_semantic_plan_comparison_allows_bounded_paraphrase_drift() -> None:
    left = _model_plan()["semantic_task_plan"]
    right = _model_plan()["semantic_task_plan"]
    right["task_semantics"] = {
        "goal": "Determine how ACME revenue changed.",
        "entities": [],
        "time_scope": "",
    }
    right["retrieval_objectives"].pop("memory")
    right["required_evidence"] = ["table_cell", "semantic_context"]

    comparison = compare_semantic_task_plans(left, right)

    assert comparison.equivalent is True
    assert comparison.required_outputs_equal is True
    assert comparison.retrieval_objective_overlap == 0.75
    assert comparison.goal_token_overlap < 1.0


def test_semantic_plan_comparison_rejects_different_output_contract() -> None:
    left = _model_plan()["semantic_task_plan"]
    right = _model_plan()["semantic_task_plan"]
    right["required_outputs"] = ["unrelated_output"]

    comparison = compare_semantic_task_plans(left, right)

    assert comparison.equivalent is False
    assert comparison.required_outputs_equal is False
