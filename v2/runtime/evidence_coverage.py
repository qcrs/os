from __future__ import annotations

from dataclasses import dataclass

from v2.contracts import (
    EvidenceCoverageReport,
    EvidenceCoverageStatus,
    EvidenceRequest,
)
from v2.refs import CanonicalEvidencePack, EvidenceItem
from v2.utils import sha256_digest


_BUCKET_TO_TYPES = {
    # The existing fan-in places table cells in hard_facts; expose both terms
    # so an adaptive request cannot mistake that legacy bucket for missing data.
    "hard_facts": ("fact", "table"),
    "structured_evidence": ("table",),
    "semantic_contexts": ("semantic_context",),
    "lexical_hints": ("lexical_hint",),
    "conflicts": ("conflict",),
}


class EvidenceRequestError(ValueError):
    pass


def validate_evidence_request(
    request: EvidenceRequest,
    *,
    allowed_corpus_scope_ids: tuple[str, ...],
    previous_query_hashes: tuple[str, ...] = (),
) -> None:
    if request.schema_version != "statebus.evidence_request.v1":
        raise EvidenceRequestError("invalid_schema_version")
    if not 1 <= len(request.queries) <= 3:
        raise EvidenceRequestError("query_count_out_of_bounds")
    if any(not query.strip() or len(query) > 512 for query in request.queries):
        raise EvidenceRequestError("invalid_query")
    if len(set(query.strip().lower() for query in request.queries)) != len(request.queries):
        raise EvidenceRequestError("duplicate_query")
    if any(scope not in allowed_corpus_scope_ids for scope in request.corpus_scope_ids):
        raise EvidenceRequestError("unknown_corpus_scope")
    if any(sha256_digest(query.strip().lower()) in previous_query_hashes for query in request.queries):
        raise EvidenceRequestError("repeated_query")
    if request.max_candidates < 1 or request.max_candidates > 64:
        raise EvidenceRequestError("invalid_candidate_budget")
    if request.max_prompt_visible_bytes < 256 or request.max_prompt_visible_bytes > 262_144:
        raise EvidenceRequestError("invalid_prompt_budget")
    if not request.evidence_types:
        raise EvidenceRequestError("missing_evidence_type")


@dataclass(frozen=True)
class EvidenceCoverageVerifier:
    policy_version: str = "statebus.evidence_coverage.v1"

    def evaluate(
        self,
        evidence_pack: CanonicalEvidencePack,
        request: EvidenceRequest,
        *,
        consumed_state_ref_ids: tuple[str, ...] = (),
    ) -> EvidenceCoverageReport:
        bucket_items = self._bucket_items(evidence_pack)
        covered: list[str] = []
        locator_count = 0
        entity_coverage: set[str] = set()
        for bucket, items in bucket_items.items():
            if items:
                covered.extend(_BUCKET_TO_TYPES[bucket])
            for item in items:
                if item.locator is not None:
                    locator_count += 1
                entity = str(item.metadata.get("entity", ""))
                if entity:
                    entity_coverage.add(entity)
        missing = tuple(sorted(set(request.evidence_types) - set(covered)))
        conflict_items = tuple(item.item_id for item in evidence_pack.conflicts)
        requested_entities = set(request.target_entities)
        entity_ok = not requested_entities or requested_entities <= entity_coverage
        missing_entities = tuple(sorted(requested_entities - entity_coverage))
        locator_ok = not request.required_locator or locator_count > 0
        time_scope_ok = bool(request.time_scope) is False or any(
            str(item.metadata.get("time_scope", "")) == request.time_scope
            for items in bucket_items.values()
            for item in items
        )
        evidence_types_ok = not missing
        if conflict_items:
            status = EvidenceCoverageStatus.CONFLICTING_EVIDENCE
        elif not evidence_types_ok or not locator_ok or not entity_ok or not time_scope_ok:
            status = EvidenceCoverageStatus.INSUFFICIENT_EVIDENCE
        else:
            status = EvidenceCoverageStatus.COMPLETE
        return EvidenceCoverageReport(
            status=status,
            covered_evidence_types=tuple(sorted(covered)),
            missing_evidence_types=missing,
            entity_coverage=tuple(sorted(entity_coverage)),
            requested_entities=tuple(sorted(requested_entities)),
            missing_entities=missing_entities,
            evidence_types_coverage=evidence_types_ok,
            entity_coverage_ok=entity_ok,
            locator_coverage=locator_ok,
            requested_time_scope=request.time_scope,
            time_scope_coverage=time_scope_ok,
            locator_count=locator_count,
            conflict_item_ids=conflict_items,
            consumed_state_ref_ids=tuple(sorted(consumed_state_ref_ids)),
            evidence_pack_hash=evidence_pack.pack_hash,
            coverage_policy_version=self.policy_version,
        )

    @staticmethod
    def _bucket_items(evidence_pack: CanonicalEvidencePack) -> dict[str, tuple[EvidenceItem, ...]]:
        return {
            "hard_facts": evidence_pack.hard_facts,
            "structured_evidence": evidence_pack.structured_evidence,
            "semantic_contexts": evidence_pack.semantic_contexts,
            "lexical_hints": evidence_pack.lexical_hints,
            "conflicts": evidence_pack.conflicts,
        }
