from __future__ import annotations

import time
from dataclasses import dataclass, field

from v2.contracts import REPLAY_LEDGER_SCHEMA_VERSION, CompatibilityVerdict, ReplayClass
from v2.utils import sha256_digest


@dataclass(frozen=True)
class ReplayLedgerEntry:
    ledger_id: str
    session_id: str
    task_id: str
    candidate_id: str
    memory_id: str
    artifact_ref_id: str
    replay_class: ReplayClass
    decision_reason: str
    compatibility_verdict: CompatibilityVerdict
    runtime_signature_hash: str
    runtime_signature_manifest_bundle_hash: str
    canonical_task_spec_hash: str
    planner_handoff_hash: str
    input_artifact_hashes: tuple[str, ...]
    output_contract_version: str
    code_template_version: str = ""
    extractor_version: str = ""
    runtime_signature: dict[str, object] = field(default_factory=dict)
    exact_key: str = ""
    degraded: bool = False
    skipped_step_count: int = 0
    created_at_ns: int = field(default_factory=time.time_ns)
    schema_version: str = REPLAY_LEDGER_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "ledger_id": self.ledger_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "candidate_id": self.candidate_id,
            "memory_id": self.memory_id,
            "artifact_ref_id": self.artifact_ref_id,
            "replay_class": self.replay_class.value,
            "decision_reason": self.decision_reason,
            "compatibility_verdict": self.compatibility_verdict.value,
            "runtime_signature_hash": self.runtime_signature_hash,
            "runtime_signature_manifest_bundle_hash": self.runtime_signature_manifest_bundle_hash,
            "canonical_task_spec_hash": self.canonical_task_spec_hash,
            "planner_handoff_hash": self.planner_handoff_hash,
            "input_artifact_hashes": list(self.input_artifact_hashes),
            "output_contract_version": self.output_contract_version,
            "code_template_version": self.code_template_version,
            "extractor_version": self.extractor_version,
            "runtime_signature": dict(sorted(self.runtime_signature.items())),
            "exact_key": self.exact_key,
            "degraded": self.degraded,
            "skipped_step_count": self.skipped_step_count,
            "created_at_ns": self.created_at_ns,
            "schema_version": self.schema_version,
        }

    @property
    def ledger_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass
class ReplayLedger:
    entries: dict[str, ReplayLedgerEntry] = field(default_factory=dict)

    def append(self, entry: ReplayLedgerEntry) -> ReplayLedgerEntry:
        self.entries[entry.ledger_id] = entry
        return entry
