from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from statebus.contracts import ClaimSet, ClaimSetStatus
from statebus.refs import CanonicalEvidencePack, ExecutionArtifactRef, FragmentLocator, TableCellLocator, TextSpanLocator


@dataclass(frozen=True)
class ClaimValidationReport:
    ok: bool
    status: ClaimSetStatus
    errors: tuple[str, ...] = ()


class ClaimSetValidator:
    def validate(
        self,
        claim_set: ClaimSet,
        *,
        evidence_pack: CanonicalEvidencePack,
        verified_artifacts: dict[str, Any],
        current_task_id: str = "",
        current_session_id: str = "",
        evidence_session_id: str = "",
        artifact_context: dict[str, tuple[str, str]] | None = None,
    ) -> ClaimValidationReport:
        effective_task_id = current_task_id or claim_set.task_id
        if claim_set.schema_version != "statebus.claim_set.v1":
            return ClaimValidationReport(False, ClaimSetStatus.MISSING_CITATION, ("invalid_schema_version",))
        if not claim_set.task_id or claim_set.task_id != effective_task_id or evidence_pack.task_id != effective_task_id:
            return ClaimValidationReport(False, ClaimSetStatus.MISSING_CITATION, ("task_provenance_mismatch",))
        if current_session_id and evidence_session_id != current_session_id:
            return ClaimValidationReport(False, ClaimSetStatus.MISSING_CITATION, ("evidence_session_provenance_mismatch",))
        if claim_set.status == ClaimSetStatus.INSUFFICIENT_EVIDENCE:
            if claim_set.claims:
                return ClaimValidationReport(False, ClaimSetStatus.INSUFFICIENT_EVIDENCE, ("insufficient_evidence_must_not_assert_claims",))
            return ClaimValidationReport(False, ClaimSetStatus.INSUFFICIENT_EVIDENCE, ("insufficient_evidence",))
        if claim_set.status != ClaimSetStatus.READY:
            return ClaimValidationReport(False, claim_set.status, ("claim_set_not_ready",))
        if not claim_set.claims:
            return ClaimValidationReport(False, ClaimSetStatus.INSUFFICIENT_EVIDENCE, ("empty_claim_set",))
        evidence = {
            item.item_id: item
            for bucket in (
                evidence_pack.hard_facts, evidence_pack.structured_evidence, evidence_pack.semantic_contexts,
                evidence_pack.lexical_hints, evidence_pack.conflicts,
            )
            for item in bucket
        }
        locator_index = {
            locator
            for item in evidence.values()
            for locator in self._locator_values(item.locator)
        }
        artifact_context = artifact_context or {}
        artifact_payloads = {
            artifact_id: self._artifact_payload(value)
            for artifact_id, value in verified_artifacts.items()
        }
        errors: list[str] = []
        for claim in claim_set.claims:
            factual = claim.claim_type in {"fact", "inference", "risk"}
            if factual and not (claim.supporting_evidence_item_ids or claim.supporting_artifact_ref_ids):
                errors.append(f"missing_support:{claim.claim_id}")
            for item_id in claim.supporting_evidence_item_ids:
                item = evidence.get(item_id)
                if item is None or item.locator is None:
                    errors.append(f"invalid_evidence_reference:{claim.claim_id}:{item_id}")
            for locator in claim.citation_locators:
                if locator not in locator_index:
                    errors.append(f"invalid_locator:{claim.claim_id}:{locator}")
            for artifact_id in claim.supporting_artifact_ref_ids:
                if artifact_id not in verified_artifacts:
                    errors.append(f"unverified_artifact:{claim.claim_id}:{artifact_id}")
                    continue
                artifact_ref = self._artifact_ref(verified_artifacts[artifact_id])
                if artifact_ref is not None and artifact_ref.verification_state.value != "verified":
                    errors.append(f"unverified_artifact:{claim.claim_id}:{artifact_id}")
                    continue
                artifact_task_id, artifact_session_id = self._artifact_provenance(
                    verified_artifacts[artifact_id], artifact_context.get(artifact_id, ("", "")),
                )
                if artifact_task_id and artifact_task_id != effective_task_id:
                    errors.append(f"artifact_task_provenance_mismatch:{claim.claim_id}:{artifact_id}")
                if current_session_id and artifact_session_id != current_session_id:
                    errors.append(f"artifact_session_provenance_mismatch:{claim.claim_id}:{artifact_id}")
            scalar_values = {
                value
                for artifact_id in claim.supporting_artifact_ref_ids
                for value in self._scalars(artifact_payloads.get(artifact_id, {}))
            }
            for name, value in claim.numeric_fields.items():
                if float(value) not in scalar_values:
                    errors.append(f"numeric_mismatch:{claim.claim_id}:{name}")
        if errors:
            status = ClaimSetStatus.MISSING_CITATION if any("reference" in error or "support" in error or "locator" in error for error in errors) else ClaimSetStatus.FACT_CONFLICT
            return ClaimValidationReport(False, status, tuple(errors))
        return ClaimValidationReport(True, ClaimSetStatus.READY)

    @staticmethod
    def _artifact_payload(value: Any) -> Any:
        if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], ExecutionArtifactRef):
            return value[1]
        if isinstance(value, dict) and "payload" in value:
            return value["payload"]
        return value

    @staticmethod
    def _artifact_ref(value: Any) -> ExecutionArtifactRef | None:
        if isinstance(value, ExecutionArtifactRef):
            return value
        if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], ExecutionArtifactRef):
            return value[0]
        return None

    @staticmethod
    def _artifact_provenance(value: Any, fallback: tuple[str, str]) -> tuple[str, str]:
        if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], ExecutionArtifactRef):
            return value[0].task_id, str(value[0].metadata.get("session_id", ""))
        if isinstance(value, dict):
            return str(value.get("task_id", fallback[0])), str(value.get("session_id", fallback[1]))
        return fallback

    @staticmethod
    def _locator_values(locator: Any) -> set[str]:
        if locator is None:
            return set()
        values: set[str] = set()
        if isinstance(locator, FragmentLocator):
            values.add(locator.fragment_id)
        elif isinstance(locator, TextSpanLocator):
            values.add(f"{locator.canonical_text_id}:{locator.start_char}-{locator.end_char}")
        elif isinstance(locator, TableCellLocator):
            values.add(f"{locator.table_id}:{locator.row_idx}:{locator.col_idx}")
        values.add(repr(locator))
        return values

    @staticmethod
    def _scalars(payload: Any) -> set[float]:
        if isinstance(payload, dict):
            return set().union(*(ClaimSetValidator._scalars(value) for value in payload.values()))
        if isinstance(payload, (tuple, list)):
            return set().union(*(ClaimSetValidator._scalars(value) for value in payload))
        if isinstance(payload, (int, float)) and not isinstance(payload, bool):
            return {float(payload)}
        return set()
