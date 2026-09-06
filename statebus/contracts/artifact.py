from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from statebus.utils import sha256_digest


ARTIFACT_VERIFICATION_RECEIPT_SCHEMA_VERSION = "statebus.artifact_verification_receipt.v1"


class ArtifactVerificationDecision(StrEnum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class ArtifactVerificationReceipt:
    artifact_id: str
    runtime_task_id: str
    run_id: str
    session_id: str
    producer_step_id: str
    producer_attempt_id: str
    execution_binding_hash: str
    capability_grant_hash: str
    candidate_blob_hash: str
    candidate_size_bytes: int
    validator_ids: tuple[str, ...]
    validator_report_hashes: tuple[str, ...]
    decision: ArtifactVerificationDecision
    reason: str
    schema_version: str = ARTIFACT_VERIFICATION_RECEIPT_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "runtime_task_id": self.runtime_task_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "producer_step_id": self.producer_step_id,
            "producer_attempt_id": self.producer_attempt_id,
            "execution_binding_hash": self.execution_binding_hash,
            "capability_grant_hash": self.capability_grant_hash,
            "candidate_blob_hash": self.candidate_blob_hash,
            "candidate_size_bytes": self.candidate_size_bytes,
            "validator_ids": list(self.validator_ids),
            "validator_report_hashes": list(self.validator_report_hashes),
            "decision": self.decision.value,
            "reason": self.reason,
            "schema_version": self.schema_version,
        }

    @property
    def receipt_hash(self) -> str:
        return sha256_digest(self.canonical_payload())
