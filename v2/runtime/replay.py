from __future__ import annotations

from dataclasses import dataclass, field

from v2.contracts import (
    CanonicalTaskSpec,
    CompatibilityVerdict,
    CompilerStatus,
    ReplayClass,
    RuntimeCompatibilitySignature,
    TaskCompilerResult,
)
from v2.utils import sha256_digest


@dataclass(frozen=True)
class ReplayPolicy:
    allow_assist: bool = True
    allow_validated_replay: bool = False
    allow_exact_replay: bool = False


@dataclass(frozen=True)
class ReplayCandidate:
    candidate_id: str
    canonical_task_spec: CanonicalTaskSpec
    input_artifact_hashes: tuple[str, ...]
    runtime_signature: RuntimeCompatibilitySignature
    output_contract_version: str
    verified_output: bool
    code_template_version: str = ""
    extractor_version: str = ""

    @property
    def exact_key(self) -> str:
        return sha256_digest(
            {
                "canonical_task_spec": self.canonical_task_spec.canonical_payload(),
                "input_artifact_hashes": list(self.input_artifact_hashes),
                "runtime_compatibility_signature": self.runtime_signature.combined_digest,
                "code_template_version": self.code_template_version,
                "extractor_version": self.extractor_version,
                "output_contract_version": self.output_contract_version,
            }
        )


@dataclass(frozen=True)
class ReplayDecision:
    replay_class: ReplayClass
    reason: str
    candidate_id: str = ""
    compatibility_verdict: CompatibilityVerdict = CompatibilityVerdict.INCOMPATIBLE
    skipped_step_count: int = 0
    degraded: bool = False


@dataclass
class ReplayAdmissibilityGate:
    def decide(
        self,
        *,
        compiler_result: TaskCompilerResult,
        policy: ReplayPolicy,
        candidate: ReplayCandidate | None,
        runtime_signature: RuntimeCompatibilitySignature,
        input_artifact_hashes: tuple[str, ...],
        output_contract_version: str,
    ) -> ReplayDecision:
        if candidate is None:
            return ReplayDecision(
                replay_class=ReplayClass.DISALLOWED,
                reason="no_replay_candidate",
            )
        compatibility = runtime_signature.compare(candidate.runtime_signature)
        exact_key = ""
        if compiler_result.canonical_task_spec is not None:
            exact_key = sha256_digest(
                {
                    "canonical_task_spec": compiler_result.canonical_task_spec.canonical_payload(),
                    "input_artifact_hashes": list(input_artifact_hashes),
                    "runtime_compatibility_signature": runtime_signature.combined_digest,
                    "code_template_version": candidate.code_template_version,
                    "extractor_version": candidate.extractor_version,
                    "output_contract_version": output_contract_version,
                }
            )
        if (
            policy.allow_exact_replay
            and compiler_result.status == CompilerStatus.COMPILED
            and compiler_result.canonical_task_spec is not None
            and candidate.verified_output
            and compatibility == CompatibilityVerdict.COMPATIBLE
            and output_contract_version == candidate.output_contract_version
            and exact_key == candidate.exact_key
        ):
            return ReplayDecision(
                replay_class=ReplayClass.EXACT_REPLAY,
                reason="exact_replay_key_match",
                candidate_id=candidate.candidate_id,
                compatibility_verdict=compatibility,
                skipped_step_count=2,
            )
        if (
            policy.allow_validated_replay
            and compiler_result.status == CompilerStatus.COMPILED
            and compiler_result.canonical_task_spec is not None
            and compiler_result.canonical_task_spec.task_family
            == candidate.canonical_task_spec.task_family
            and compiler_result.canonical_task_spec.intent_op
            == candidate.canonical_task_spec.intent_op
            and output_contract_version == candidate.output_contract_version
            and compatibility != CompatibilityVerdict.INCOMPATIBLE
        ):
            return ReplayDecision(
                replay_class=ReplayClass.VALIDATED_REPLAY,
                reason="task_family_and_intent_match",
                candidate_id=candidate.candidate_id,
                compatibility_verdict=compatibility,
                skipped_step_count=1,
                degraded=compatibility == CompatibilityVerdict.DEGRADED,
            )
        if policy.allow_assist:
            return ReplayDecision(
                replay_class=ReplayClass.ASSIST,
                reason="memory_assist_only",
                candidate_id=candidate.candidate_id,
                compatibility_verdict=compatibility,
            )
        return ReplayDecision(
            replay_class=ReplayClass.DISALLOWED,
            reason="policy_disallows_reuse",
            candidate_id=candidate.candidate_id,
            compatibility_verdict=compatibility,
        )

