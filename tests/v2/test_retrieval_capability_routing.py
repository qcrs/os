from __future__ import annotations

from v2.contracts import CanonicalTaskSpec, EvidenceRequest
from v2.retrieval import RetrieverFanoutPipeline, RetrieverKind


def _spec() -> CanonicalTaskSpec:
    return CanonicalTaskSpec(
        task_family="financial_report_analysis",
        intent_op="compare_metric",
        target_entities=("ACME",),
        time_scope="2026Q1",
        required_outputs=("summary_text",),
        required_tools=("finance",),
        arguments={"ticker": "ACME", "quarter": "2026Q1"},
    )


def test_table_only_request_skips_lexical_and_semantic_document_retrievers() -> None:
    pipeline = RetrieverFanoutPipeline.with_embedding_mode("deterministic")
    bundle = pipeline.run(
        task_id="table-only",
        spec=_spec(),
        enabled_evidence_types=("table",),
    )
    output_by_kind = {output.retriever_kind: output for output in bundle.outputs}

    assert output_by_kind[RetrieverKind.LEXICAL_METADATA].log_entry.diagnostics == {
        "dispatch": "disabled_by_evidence_types"
    }
    assert output_by_kind[RetrieverKind.SEMANTIC_CHUNK].log_entry.diagnostics == {
        "dispatch": "disabled_by_evidence_types"
    }
    assert output_by_kind[RetrieverKind.TABLE_STRUCTURE].log_entry.candidate_count > 0
    assert bundle.semantic_candidate_embeddings == ()
    assert bundle.semantic_state_manifest is None
    assert bundle.evidence_pack.budget_meta["enabled_retrievers"] == ["table"]


def test_evidence_request_routes_only_requested_semantic_retriever() -> None:
    pipeline = RetrieverFanoutPipeline.with_embedding_mode("deterministic")
    request = EvidenceRequest(
        request_id="request-semantic-only",
        task_id="semantic-only",
        step_id="retrieval",
        queries=("ACME revenue increased",),
        evidence_types=("semantic_context",),
        corpus_scope_ids=("local",),
        target_entities=("ACME",),
        time_scope="2026Q1",
        max_candidates=8,
    )
    result = pipeline.run_bounded_evidence_request(
        request=request,
        spec=_spec(),
        allowed_corpus_scope_ids=("local",),
        max_expansions=0,
    )
    output_by_kind = {
        output.retriever_kind: output for output in result.bundles[0].outputs
    }

    assert output_by_kind[RetrieverKind.SEMANTIC_CHUNK].log_entry.candidate_count > 0
    assert output_by_kind[RetrieverKind.LEXICAL_METADATA].log_entry.candidate_count == 0
    assert output_by_kind[RetrieverKind.TABLE_STRUCTURE].log_entry.candidate_count == 0
