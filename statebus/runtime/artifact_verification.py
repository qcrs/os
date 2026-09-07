from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from statebus.contracts import (
    ArtifactVerificationDecision,
    ArtifactVerificationReceipt,
    BoundCapabilityGrant,
    CapabilityQualityReport,
    RefStatus,
    RuntimeIdentity,
)
from statebus.refs import ExecutionArtifactRef
from statebus.runtime.session import AttemptResultAdmissionReceipt, RuntimeSessionManager
from statebus.utils import sha256_digest


class ArtifactVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeArtifactVerificationAuthority:
    session_manager: RuntimeSessionManager
    runtime_identity: RuntimeIdentity

    def verify_candidate(
        self,
        *,
        candidate: ExecutionArtifactRef,
        artifact_id: str,
        bound_grant: BoundCapabilityGrant,
        result_admission: AttemptResultAdmissionReceipt,
        attempt_workspace: Path,
        validator_report_hashes: tuple[str, ...],
        quality_reports: Mapping[str, CapabilityQualityReport],
        claim_validation_reports: Mapping[str, dict[str, object]],
    ) -> tuple[ExecutionArtifactRef, ArtifactVerificationReceipt]:
        grant = bound_grant.grant
        self._validate_admission(
            step_id=grant.step_id,
            attempt_id=grant.attempt_id,
            result_admission=result_admission,
        )
        self._validate_identity(
            candidate=candidate,
            artifact_id=artifact_id,
            bound_grant=bound_grant,
        )
        self._validate_content(candidate=candidate, attempt_workspace=attempt_workspace)
        validator_ids = self._validate_evidence(
            candidate=candidate,
            validator_report_hashes=validator_report_hashes,
            quality_reports=quality_reports,
            claim_validation_reports=claim_validation_reports,
        )
        receipt = ArtifactVerificationReceipt(
            artifact_id=candidate.artifact_id,
            runtime_task_id=self.runtime_identity.runtime_task_id,
            run_id=self.runtime_identity.run_id,
            session_id=self.runtime_identity.session_id,
            producer_step_id=grant.step_id,
            producer_attempt_id=grant.attempt_id,
            execution_binding_hash=bound_grant.execution_binding_hash,
            capability_grant_hash=grant.grant_hash,
            candidate_blob_hash=candidate.blob_hash,
            candidate_size_bytes=candidate.size_bytes,
            validator_ids=validator_ids,
            validator_report_hashes=validator_report_hashes,
            decision=ArtifactVerificationDecision.VERIFIED,
            reason="active_attempt_candidate_validated",
        )
        verified = replace(
            candidate,
            verification_state=RefStatus.VERIFIED,
            replay_ready=False,
            metadata={
                **candidate.metadata,
                "artifact_verification_receipt_hash": receipt.receipt_hash,
                "attempt_result_admission_receipt_hash": result_admission.receipt_hash,
            },
        )
        return verified, receipt

    def _validate_admission(
        self,
        *,
        step_id: str,
        attempt_id: str,
        result_admission: AttemptResultAdmissionReceipt,
    ) -> None:
        active_attempt_id = self.session_manager.active_attempt_id(
            self.runtime_identity.session_id,
            step_id,
        )
        if (
            not result_admission.commit_authorized
            or result_admission.step_id != step_id
            or result_admission.observed_attempt_id != attempt_id
            or result_admission.active_attempt_id != attempt_id
            or active_attempt_id != attempt_id
        ):
            raise ArtifactVerificationError("artifact_producer_attempt_not_active")

    def _validate_identity(
        self,
        *,
        candidate: ExecutionArtifactRef,
        artifact_id: str,
        bound_grant: BoundCapabilityGrant,
    ) -> None:
        grant = bound_grant.grant
        if candidate.artifact_id != artifact_id:
            raise ArtifactVerificationError("artifact_candidate_id_mismatch")
        if (
            candidate.task_id != self.runtime_identity.runtime_task_id
            or grant.task_id != self.runtime_identity.runtime_task_id
            or grant.session_id != self.runtime_identity.session_id
            or candidate.step_id != grant.step_id
            or candidate.metadata.get("session_id") != grant.session_id
            or candidate.metadata.get("attempt_id") != grant.attempt_id
            or candidate.metadata.get("grant_hash") != grant.grant_hash
        ):
            raise ArtifactVerificationError("artifact_candidate_provenance_mismatch")
        if candidate.verification_state != RefStatus.CANDIDATE or candidate.replay_ready:
            raise ArtifactVerificationError("artifact_candidate_state_invalid")
        if not candidate.artifact_type or not candidate.manifest_hash:
            raise ArtifactVerificationError("artifact_candidate_identity_incomplete")

    @staticmethod
    def _validate_content(
        *,
        candidate: ExecutionArtifactRef,
        attempt_workspace: Path,
    ) -> None:
        if not candidate.root_id or not candidate.relpath:
            raise ArtifactVerificationError("artifact_candidate_path_required")
        if candidate.workspace_relpath and candidate.workspace_relpath != candidate.relpath:
            raise ArtifactVerificationError("artifact_candidate_relpath_mismatch")
        try:
            resolved_workspace = attempt_workspace.resolve(strict=True)
            resolved_root = Path(candidate.root_id).resolve(strict=True)
            artifact_path = Path(candidate.root_id) / candidate.relpath
            resolved_path = artifact_path.resolve(strict=True)
            if (
                not resolved_root.is_relative_to(resolved_workspace)
                or not resolved_path.is_relative_to(resolved_root)
                or artifact_path.is_symlink()
                or not artifact_path.is_file()
            ):
                raise ArtifactVerificationError("artifact_candidate_path_outside_workspace")
            payload = artifact_path.read_bytes()
        except OSError as exc:
            raise ArtifactVerificationError("artifact_candidate_path_unreadable") from exc
        if len(payload) != candidate.size_bytes:
            raise ArtifactVerificationError("artifact_candidate_size_mismatch")
        if sha256_digest(payload) != candidate.blob_hash:
            raise ArtifactVerificationError("artifact_candidate_blob_hash_mismatch")

    @staticmethod
    def _validate_evidence(
        *,
        candidate: ExecutionArtifactRef,
        validator_report_hashes: tuple[str, ...],
        quality_reports: Mapping[str, CapabilityQualityReport],
        claim_validation_reports: Mapping[str, dict[str, object]],
    ) -> tuple[str, ...]:
        quality_report_hash = str(candidate.metadata.get("quality_report_hash", ""))
        claim_report_hash = str(candidate.metadata.get("claim_validation_audit_hash", ""))
        evidence_hash = quality_report_hash or claim_report_hash
        if not evidence_hash or evidence_hash not in validator_report_hashes:
            raise ArtifactVerificationError("artifact_candidate_validator_evidence_missing")

        if quality_report_hash:
            report = quality_reports.get(quality_report_hash)
            if (
                report is None
                or report.report_hash != quality_report_hash
                or not report.verified
                or report.output_artifact_hash != candidate.blob_hash
            ):
                raise ArtifactVerificationError("artifact_candidate_validator_evidence_mismatch")
            return (report.validator_id,)

        audit = next(
            (
                report
                for report in claim_validation_reports.values()
                if sha256_digest(report) == claim_report_hash
            ),
            None,
        )
        if (
            audit is None
            or audit.get("claim_set_hash") != candidate.blob_hash
            or not bool(dict(audit.get("claim_validation", {})).get("ok"))
        ):
            raise ArtifactVerificationError("artifact_candidate_validator_evidence_mismatch")
        return ("claim_set_validator",)
