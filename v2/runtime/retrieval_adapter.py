from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing import Callable

from v2.contracts import EvidenceCoverageReport, EvidenceCoverageStatus, EvidenceRequest
from v2.refs import CanonicalEvidencePack, EvidenceItem
from v2.runtime.evidence_coverage import EvidenceCoverageVerifier, validate_evidence_request
from v2.utils import sha256_digest

if TYPE_CHECKING:
    from v2.retrieval.models import RetrievalBundle


@dataclass(frozen=True)
class AdaptiveRetrievalResult:
    request: EvidenceRequest
    evidence_pack: CanonicalEvidencePack
    query_hashes: tuple[str, ...]
    coverage_reports: tuple[EvidenceCoverageReport, ...] = ()
    coverage_decisions: tuple["RetrievalCoverageDecision", ...] = ()
    # Product Runtime keeps the typed retrieval bundles alongside the
    # projected EvidencePack so downstream state consumers can operate on the
    # producer-owned dense matrix without receiving Python tuples over UDS.
    retrieval_bundles: tuple["RetrievalBundle", ...] = ()


@dataclass(frozen=True)
class RetrievalCoverageDecision:
    decision: str
    expansion_index: int
    before_status: EvidenceCoverageStatus
    after_status: EvidenceCoverageStatus
    before_candidate_count: int
    after_candidate_count: int
    missing_evidence_types: tuple[str, ...]
    query_hashes: tuple[str, ...]

    def canonical_payload(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "expansion_index": self.expansion_index,
            "before_status": self.before_status.value,
            "after_status": self.after_status.value,
            "before_candidate_count": self.before_candidate_count,
            "after_candidate_count": self.after_candidate_count,
            "missing_evidence_types": list(self.missing_evidence_types),
            "query_hashes": list(self.query_hashes),
        }


def stable_fan_in_evidence_packs(
    *,
    task_id: str,
    packs: tuple[CanonicalEvidencePack, ...],
) -> CanonicalEvidencePack:
    seen: set[tuple[str, str]] = set()

    def merge(bucket_name: str) -> tuple[EvidenceItem, ...]:
        values: list[EvidenceItem] = []
        for pack in sorted(packs, key=lambda item: (item.pack_hash, item.pack_id)):
            for item in getattr(pack, bucket_name):
                key = (item.item_id, repr(item.locator))
                if key in seen:
                    continue
                seen.add(key)
                values.append(item)
        return tuple(sorted(values, key=lambda item: (item.rank, -item.score, item.item_id)))

    return CanonicalEvidencePack(
        pack_id=f"adaptive-fan-in-{task_id}",
        task_id=task_id,
        source_doc_hashes=tuple(sorted({doc_hash for pack in packs for doc_hash in pack.source_doc_hashes})),
        hard_facts=merge("hard_facts"),
        structured_evidence=merge("structured_evidence"),
        semantic_contexts=merge("semantic_contexts"),
        lexical_hints=merge("lexical_hints"),
        conflicts=merge("conflicts"),
        budget_meta={"fan_in_pack_count": len(packs)},
    )


class AdaptiveRetrievalAdapter:
    """Small adapter around a registered retrieval callable; it never accepts paths from an LLM."""

    def __init__(self, retrieve_query) -> None:
        self._retrieve_query = retrieve_query

    def run(
        self,
        request: EvidenceRequest,
        *,
        allowed_corpus_scope_ids: tuple[str, ...],
        previous_query_hashes: tuple[str, ...] = (),
    ) -> AdaptiveRetrievalResult:
        validate_evidence_request(
            request,
            allowed_corpus_scope_ids=allowed_corpus_scope_ids,
            previous_query_hashes=previous_query_hashes,
        )
        raw_results = tuple(self._retrieve_query(query, request) for query in request.queries)
        bundles = tuple(
            result for result in raw_results
            if hasattr(result, "semantic_candidate_embeddings") and hasattr(result, "evidence_pack")
        )
        packs = tuple(
            result.evidence_pack if hasattr(result, "evidence_pack") else result
            for result in raw_results
        )
        return AdaptiveRetrievalResult(
            request=request,
            evidence_pack=stable_fan_in_evidence_packs(task_id=request.task_id, packs=packs),
            query_hashes=tuple(sha256_digest(query.strip().lower()) for query in request.queries),
            retrieval_bundles=bundles,
        )

    def run_with_single_expansion(
        self,
        request: EvidenceRequest,
        *,
        allowed_corpus_scope_ids: tuple[str, ...],
        propose_expansion: Callable[[EvidenceCoverageReport], EvidenceRequest | None] | None = None,
        verifier: EvidenceCoverageVerifier | None = None,
        max_expansions: int = 1,
        decision_sink: Callable[[RetrievalCoverageDecision], None] | None = None,
    ) -> AdaptiveRetrievalResult:
        """Execute trusted fan-out, then let the controller approve at most one follow-up.

        `propose_expansion` supplies an untrusted candidate only. Coverage status is
        always calculated from the registered retrieval output, never from that
        candidate or an LLM assertion.
        """
        if max_expansions < 0 or max_expansions > 1:
            raise ValueError("max_expansions_must_be_zero_or_one")
        verifier = verifier or EvidenceCoverageVerifier()
        initial = self.run(request, allowed_corpus_scope_ids=allowed_corpus_scope_ids)
        initial_report = verifier.evaluate(initial.evidence_pack, request)
        reports = [initial_report]
        decisions: list[RetrievalCoverageDecision] = []
        if initial_report.status != EvidenceCoverageStatus.INSUFFICIENT_EVIDENCE:
            decision = RetrievalCoverageDecision(
                decision="coverage_complete_no_expansion",
                expansion_index=0,
                before_status=initial_report.status,
                after_status=initial_report.status,
                before_candidate_count=_evidence_item_count(initial.evidence_pack),
                after_candidate_count=_evidence_item_count(initial.evidence_pack),
                missing_evidence_types=initial_report.missing_evidence_types,
                query_hashes=initial.query_hashes,
            )
            decisions.append(decision)
            if decision_sink is not None:
                decision_sink(decision)
            return AdaptiveRetrievalResult(
                request=request, evidence_pack=initial.evidence_pack, query_hashes=initial.query_hashes,
                coverage_reports=tuple(reports), coverage_decisions=tuple(decisions),
                retrieval_bundles=initial.retrieval_bundles,
            )
        if max_expansions == 0 or propose_expansion is None:
            decision = RetrievalCoverageDecision(
                decision="coverage_insufficient_no_expansion_authorized",
                expansion_index=0,
                before_status=initial_report.status,
                after_status=initial_report.status,
                before_candidate_count=_evidence_item_count(initial.evidence_pack),
                after_candidate_count=_evidence_item_count(initial.evidence_pack),
                missing_evidence_types=initial_report.missing_evidence_types,
                query_hashes=initial.query_hashes,
            )
            decisions.append(decision)
            if decision_sink is not None:
                decision_sink(decision)
            return AdaptiveRetrievalResult(
                request=request, evidence_pack=initial.evidence_pack, query_hashes=initial.query_hashes,
                coverage_reports=tuple(reports), coverage_decisions=tuple(decisions),
                retrieval_bundles=initial.retrieval_bundles,
            )
        expansion = propose_expansion(initial_report)
        if expansion is None:
            decision = RetrievalCoverageDecision(
                decision="coverage_insufficient_expansion_not_proposed",
                expansion_index=0,
                before_status=initial_report.status,
                after_status=initial_report.status,
                before_candidate_count=_evidence_item_count(initial.evidence_pack),
                after_candidate_count=_evidence_item_count(initial.evidence_pack),
                missing_evidence_types=initial_report.missing_evidence_types,
                query_hashes=initial.query_hashes,
            )
            decisions.append(decision)
            if decision_sink is not None:
                decision_sink(decision)
            return AdaptiveRetrievalResult(
                request=request, evidence_pack=initial.evidence_pack, query_hashes=initial.query_hashes,
                coverage_reports=tuple(reports), coverage_decisions=tuple(decisions),
                retrieval_bundles=initial.retrieval_bundles,
            )
        if expansion.task_id != request.task_id or expansion.step_id != request.step_id:
            raise ValueError("expansion_request_scope_mismatch")
        follow_up = self.run(
            expansion,
            allowed_corpus_scope_ids=allowed_corpus_scope_ids,
            previous_query_hashes=initial.query_hashes,
        )
        merged = stable_fan_in_evidence_packs(
            task_id=request.task_id,
            packs=(initial.evidence_pack, follow_up.evidence_pack),
        )
        final_report = verifier.evaluate(merged, expansion)
        reports.append(final_report)
        query_hashes = initial.query_hashes + follow_up.query_hashes
        decision = RetrievalCoverageDecision(
            decision=("coverage_complete_after_single_expansion" if final_report.status == EvidenceCoverageStatus.COMPLETE else "coverage_insufficient_after_single_expansion"),
            expansion_index=1,
            before_status=initial_report.status,
            after_status=final_report.status,
            before_candidate_count=_evidence_item_count(initial.evidence_pack),
            after_candidate_count=_evidence_item_count(merged),
            missing_evidence_types=final_report.missing_evidence_types,
            query_hashes=query_hashes,
        )
        decisions.append(decision)
        if decision_sink is not None:
            decision_sink(decision)
        return AdaptiveRetrievalResult(
            request=request,
            evidence_pack=merged,
            query_hashes=query_hashes,
            coverage_reports=tuple(reports),
            coverage_decisions=tuple(decisions),
            retrieval_bundles=initial.retrieval_bundles + follow_up.retrieval_bundles,
        )


def _evidence_item_count(pack: CanonicalEvidencePack) -> int:
    return sum(
        len(getattr(pack, bucket))
        for bucket in ("hard_facts", "structured_evidence", "semantic_contexts", "lexical_hints", "conflicts")
    )
