from __future__ import annotations

import pytest

from statebus.contracts import CanonicalTaskSpec, EvidenceCoverageStatus, EvidenceRequest
from statebus.refs import CanonicalEvidencePack, EvidenceItem, FragmentLocator
from statebus.retrieval import RetrieverFanoutPipeline
from statebus.runtime.evidence_coverage import EvidenceCoverageVerifier, EvidenceRequestError, validate_evidence_request
from statebus.runtime.retrieval_adapter import AdaptiveRetrievalAdapter, stable_fan_in_evidence_packs


def _pack(pack_id: str, item_id: str) -> CanonicalEvidencePack:
    return CanonicalEvidencePack(
        pack_id=pack_id, task_id="task", source_doc_hashes=("doc",),
        semantic_contexts=(EvidenceItem(item_id=item_id, bucket="semantic_context", locator=FragmentLocator(fragment_id=item_id), metadata={"entity": "Acme", "time_scope": "2026Q1"}),),
    )


def test_multi_query_coverage_and_stable_fan_in() -> None:
    request = EvidenceRequest(
        request_id="request", task_id="task", step_id="retrieve", queries=("revenue", "margin"),
        evidence_types=("semantic_context",), target_entities=("Acme",), time_scope="2026Q1", corpus_scope_ids=("corpus",),
    )
    validate_evidence_request(request, allowed_corpus_scope_ids=("corpus",))
    merged = stable_fan_in_evidence_packs(task_id="task", packs=(_pack("two", "b"), _pack("one", "a")))
    assert [item.item_id for item in merged.semantic_contexts] == ["a", "b"]
    coverage = EvidenceCoverageVerifier().evaluate(merged, request)
    assert coverage.status == EvidenceCoverageStatus.COMPLETE
    assert coverage.requested_entities == ("Acme",)
    assert coverage.missing_entities == ()
    assert coverage.evidence_types_coverage
    assert coverage.entity_coverage_ok
    assert coverage.locator_coverage


def test_coverage_report_explains_each_failed_acceptance_predicate() -> None:
    request = EvidenceRequest(
        request_id="request",
        task_id="task",
        step_id="retrieve",
        queries=("revenue",),
        evidence_types=("table",),
        target_entities=("OtherCo",),
        time_scope="2025Q4",
        corpus_scope_ids=("corpus",),
    )
    coverage = EvidenceCoverageVerifier().evaluate(_pack("pack", "evidence"), request)

    assert coverage.status == EvidenceCoverageStatus.INSUFFICIENT_EVIDENCE
    assert not coverage.evidence_types_coverage
    assert coverage.requested_entities == ("OtherCo",)
    assert coverage.missing_entities == ("OtherCo",)
    assert not coverage.entity_coverage_ok
    assert coverage.locator_coverage
    assert coverage.requested_time_scope == "2025Q4"
    assert not coverage.time_scope_coverage


def test_retrieval_rejects_duplicate_query_and_unknown_corpus() -> None:
    request = EvidenceRequest(
        request_id="request", task_id="task", step_id="retrieve", queries=("revenue", "revenue"),
        evidence_types=("semantic_context",), corpus_scope_ids=("other",),
    )
    try:
        validate_evidence_request(request, allowed_corpus_scope_ids=("corpus",))
    except EvidenceRequestError as exc:
        assert str(exc) == "duplicate_query"
    else:
        raise AssertionError("duplicate query was accepted")


def test_coverage_controller_allows_one_deduplicated_expansion_and_records_outcome() -> None:
    request = EvidenceRequest(
        request_id="request", task_id="task", step_id="retrieve", queries=("base",),
        evidence_types=("semantic_context",), corpus_scope_ids=("corpus",),
    )
    calls: list[str] = []

    def retrieve(query: str, request: EvidenceRequest) -> CanonicalEvidencePack:
        calls.append(query)
        return _pack("follow-up", "evidence") if query == "extra" else CanonicalEvidencePack("empty", "task", ("doc",))

    decisions = []
    result = AdaptiveRetrievalAdapter(retrieve).run_with_single_expansion(
        request,
        allowed_corpus_scope_ids=("corpus",),
        propose_expansion=lambda report: EvidenceRequest(
            request_id="expanded", task_id="task", step_id="retrieve", queries=("extra",),
            evidence_types=("semantic_context",), corpus_scope_ids=("corpus",),
        ),
        decision_sink=decisions.append,
    )
    assert calls == ["base", "extra"]
    assert result.coverage_reports[-1].status == EvidenceCoverageStatus.COMPLETE
    assert result.coverage_decisions[-1].decision == "coverage_complete_after_single_expansion"
    assert decisions == list(result.coverage_decisions)


def test_coverage_controller_stops_after_one_unsuccessful_expansion() -> None:
    request = EvidenceRequest(
        request_id="request", task_id="task", step_id="retrieve", queries=("base",),
        evidence_types=("semantic_context",), corpus_scope_ids=("corpus",),
    )
    calls: list[str] = []
    adapter = AdaptiveRetrievalAdapter(lambda query, request: (calls.append(query), CanonicalEvidencePack("empty-" + query, "task", ("doc",)))[1])
    result = adapter.run_with_single_expansion(
        request,
        allowed_corpus_scope_ids=("corpus",),
        propose_expansion=lambda report: EvidenceRequest(
            request_id="expanded", task_id="task", step_id="retrieve", queries=("extra",),
            evidence_types=("semantic_context",), corpus_scope_ids=("corpus",),
        ),
    )
    assert calls == ["base", "extra"]
    assert result.coverage_decisions[-1].decision == "coverage_insufficient_after_single_expansion"


def test_existing_fanout_pipeline_owns_approved_expansion_and_scope_check() -> None:
    spec = CanonicalTaskSpec(
        task_family="continuous_long_doc_table_analysis", intent_op="analyze_document",
        arguments={"dataset_id": "long_doc_table"},
    )
    request = EvidenceRequest(
        request_id="pipeline", task_id="task", step_id="retrieve", queries=("Acme revenue",),
        evidence_types=("semantic_context",), corpus_scope_ids=("local-long-doc",),
    )
    decisions = []
    result = RetrieverFanoutPipeline().run_bounded_evidence_request(
        request=request,
        spec=spec,
        allowed_corpus_scope_ids=("local-long-doc",),
        decision_sink=decisions.append,
    )
    assert result.coverage_reports[-1].status == EvidenceCoverageStatus.COMPLETE
    assert result.decisions[-1].decision == "coverage_complete_no_expansion"
    assert decisions == list(result.decisions)

    insufficient = EvidenceRequest(
        request_id="pipeline-insufficient", task_id="task", step_id="retrieve", queries=("Acme revenue",),
        evidence_types=("conflict",), corpus_scope_ids=("local-long-doc",),
    )
    retried = RetrieverFanoutPipeline().run_bounded_evidence_request(
        request=insufficient,
        spec=spec,
        allowed_corpus_scope_ids=("local-long-doc",),
        propose_expansion=lambda report: EvidenceRequest(
            request_id="pipeline-expansion", task_id="task", step_id="retrieve", queries=("Acme conflict",),
            evidence_types=("conflict",), corpus_scope_ids=("local-long-doc",),
        ),
    )
    assert len(retried.query_hashes) == 2
    assert retried.decisions[-1].decision == "coverage_insufficient_after_single_expansion"
    with pytest.raises(ValueError, match="corpus_scope_escalation"):
        RetrieverFanoutPipeline().run_bounded_evidence_request(
            request=insufficient,
            spec=spec,
            allowed_corpus_scope_ids=("local-long-doc", "forbidden"),
            propose_expansion=lambda report: EvidenceRequest(
                request_id="bad-expansion", task_id="task", step_id="retrieve", queries=("new",),
                evidence_types=("conflict",), corpus_scope_ids=("forbidden",),
            ),
        )


def test_long_document_table_retrieval_retains_bounded_metric_series() -> None:
    spec = CanonicalTaskSpec(
        task_family="continuous_long_doc_table_analysis",
        intent_op="analyze_document",
        arguments={"dataset_id": "long_doc_table", "metric": "revenue"},
    )
    result = RetrieverFanoutPipeline().run_multi_query(
        task_id="bounded-table-series",
        spec=spec,
        query_texts=("ACME quarterly revenue table",),
        planner_scope_payload={"query_text": "ACME quarterly revenue table"},
    )

    assert [item.metadata["value"] for item in result.evidence_pack.hard_facts] == [
        "120",
        "132",
        "145",
    ]
