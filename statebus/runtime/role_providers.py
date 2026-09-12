"""Authority-limited role provider contracts for the MRR-10A seam.

The objects in this module are invocation contracts, not Runtime authority
objects.  Providers receive a detached request and return a typed candidate;
the dispatcher remains the owner of execution, refs and admission.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from time import time_ns
from typing import Any, Callable, Literal, Protocol

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    ApprovedPlan,
    ClaimSet,
    EvidenceRequest,
    GeneratedCodeCandidate,
    PlanStepProposal,
    RuntimeIdentity,
    TransformProgram,
    TransformStep,
    BoundCapabilityGrant,
    PlannerHandoff,
)


DiagnosticScalar = str | int | float | bool | None
ProviderCandidateKind = Literal[
    "planner_handoff",
    "retrieval_request",
    "executor_program",
    "summary_claim_set",
    "diagnostic",
    "failure",
]


class ProviderAuthorityError(ValueError):
    """Raised when a provider request or candidate violates its authority scope."""


@dataclass(frozen=True)
class ImmutableStateReadView:
    ref_id: str
    state_identity_hash: str
    channel: str
    dtype: str
    shape: tuple[int, ...]
    payload_digest: str
    values: tuple[float, ...]


class ProviderStateReadFacade(Protocol):
    def read(self, ref_id: str) -> ImmutableStateReadView: ...


@dataclass
class AttemptBoundProviderStateReadFacade:
    """A detached, attempt-bound read capability.

    ``read_fn`` is an injected Runtime-owned read operation.  The facade does
    not retain a store, pin, grant issuer or filesystem handle.
    """

    runtime_task_id: str
    session_id: str
    step_id: str
    attempt_id: str
    execution_binding_hash: str
    grant_hash: str
    provider_id: str
    allowed_ref_ids: tuple[str, ...]
    expires_at_ns: int
    read_fn: Callable[[str], ImmutableStateReadView]
    active_attempt_fn: Callable[[], bool] | None = None
    _closed: bool = False

    def read(self, ref_id: str) -> ImmutableStateReadView:
        if self._closed:
            raise ProviderAuthorityError("provider_state_reader_closed")
        if self.active_attempt_fn is not None and not self.active_attempt_fn():
            raise ProviderAuthorityError("provider_state_attempt_not_active")
        if time_ns() >= self.expires_at_ns:
            raise ProviderAuthorityError("provider_state_reader_expired")
        if ref_id not in self.allowed_ref_ids:
            raise ProviderAuthorityError("provider_state_ref_out_of_scope")
        view = self.read_fn(ref_id)
        if not isinstance(view, ImmutableStateReadView) or view.ref_id != ref_id:
            raise ProviderAuthorityError("provider_state_read_invalid")
        # Never let a store-backed sequence escape the invocation boundary.
        return ImmutableStateReadView(
            ref_id=view.ref_id,
            state_identity_hash=view.state_identity_hash,
            channel=view.channel,
            dtype=view.dtype,
            shape=tuple(view.shape),
            payload_digest=view.payload_digest,
            values=tuple(float(value) for value in view.values),
        )

    def close(self) -> None:
        self._closed = True


@dataclass(frozen=True)
class RoleProviderContext:
    role: Literal["planner", "retriever", "executor", "summarizer"]
    prompt_slice: Any = None
    visible_candidate_keys: tuple[str, ...] = ()
    allowed_tool_names: tuple[str, ...] = ()
    input_contract_version: str = ""
    output_contract_version: str = ""
    mechanism_kind: str = ""
    verified_input_refs: tuple[str, ...] = ()
    code_generation_request: Any = None
    planner_handoff: PlannerHandoff | None = None
    canonical_task_spec: Any = None
    verified_input_payloads: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class ProviderRequest:
    envelope: AdaptiveTaskEnvelope
    approved_plan: ApprovedPlan
    step: PlanStepProposal
    bound_grant: BoundCapabilityGrant
    runtime_identity: RuntimeIdentity
    attempt_workspace: Path
    provider_input_refs: tuple[str, ...]
    role_context: RoleProviderContext
    state_reader: ProviderStateReadFacade | None = None

    def __post_init__(self) -> None:
        # Runtime keeps its own witness; providers receive invocation-local
        # value snapshots rather than mutable plan/envelope dictionaries.
        object.__setattr__(self, "envelope", deepcopy(self.envelope))
        object.__setattr__(self, "approved_plan", deepcopy(self.approved_plan))
        object.__setattr__(self, "step", deepcopy(self.step))
        object.__setattr__(self, "role_context", deepcopy(self.role_context))
        grant = self.bound_grant.grant
        binding = self.bound_grant.execution_binding
        if self.step.step_id != grant.step_id or self.step.capability_id != grant.capability_id:
            raise ProviderAuthorityError("provider_request_step_scope_mismatch")
        if self.approved_plan.approved_plan_hash != grant.approved_plan_hash:
            raise ProviderAuthorityError("provider_request_plan_scope_mismatch")
        if self.runtime_identity.runtime_task_id != self.envelope.task_id != grant.task_id:
            raise ProviderAuthorityError("provider_request_task_scope_mismatch")
        if self.runtime_identity.session_id != grant.session_id:
            raise ProviderAuthorityError("provider_request_session_scope_mismatch")
        if binding.attempt_id != grant.attempt_id:
            raise ProviderAuthorityError("provider_request_binding_scope_mismatch")
        if not set(self.provider_input_refs) <= set(grant.input_ref_ids):
            raise ProviderAuthorityError("provider_request_input_scope_mismatch")
        if not set(self.role_context.verified_input_refs) <= set(self.provider_input_refs):
            raise ProviderAuthorityError("provider_request_verified_input_scope_mismatch")
        if self.role_context.role != self.step.role:
            raise ProviderAuthorityError("provider_request_role_mismatch")


@dataclass(frozen=True)
class ProviderDiagnostic:
    code: str
    attributes: tuple[tuple[str, DiagnosticScalar], ...] = ()

    def __post_init__(self) -> None:
        if not str(self.code).strip():
            raise ProviderAuthorityError("provider_diagnostic_code_required")
        for key, value in self.attributes:
            if not isinstance(key, str) or not isinstance(value, (str, int, float, bool, type(None))):
                raise ProviderAuthorityError("provider_diagnostic_scalar_required")

    def canonical_payload(self) -> dict[str, object]:
        return {"code": self.code, "attributes": [[key, value] for key, value in self.attributes]}


ProviderPayload = PlannerHandoff | EvidenceRequest | TransformProgram | GeneratedCodeCandidate | ClaimSet | ProviderDiagnostic


@dataclass(frozen=True)
class ProviderCandidate:
    success: bool
    candidate_kind: ProviderCandidateKind
    payload: ProviderPayload | None = None
    diagnostics: tuple[tuple[str, DiagnosticScalar], ...] = ()
    retryable: bool = False
    error_code: str = ""

    def __post_init__(self) -> None:
        if self.candidate_kind == "failure":
            if self.success or self.payload is not None or not self.error_code.strip():
                raise ProviderAuthorityError("provider_candidate_payload_type_mismatch")
            return
        if not self.success or self.retryable:
            raise ProviderAuthorityError("provider_candidate_payload_type_mismatch")
        expected: tuple[type[object], ...]
        if self.candidate_kind == "planner_handoff":
            expected = (PlannerHandoff,)
        elif self.candidate_kind == "retrieval_request":
            expected = (EvidenceRequest,)
        elif self.candidate_kind == "executor_program":
            expected = (TransformProgram, GeneratedCodeCandidate)
        elif self.candidate_kind == "summary_claim_set":
            expected = (ClaimSet,)
        elif self.candidate_kind == "diagnostic":
            expected = (ProviderDiagnostic,)
        else:  # pragma: no cover - Literal keeps this closed for callers.
            raise ProviderAuthorityError("provider_candidate_kind_invalid")
        if not isinstance(self.payload, expected):
            raise ProviderAuthorityError("provider_candidate_payload_type_mismatch")
        for key, value in self.diagnostics:
            if not isinstance(key, str) or not isinstance(value, (str, int, float, bool, type(None))):
                raise ProviderAuthorityError("provider_candidate_diagnostic_scalar_required")


class BoundProviderHandler(Protocol):
    def __call__(self, request: ProviderRequest) -> ProviderCandidate: ...


@dataclass(frozen=True)
class RolePathRetrieverProvider:
    build_candidate: Callable[[ProviderRequest], EvidenceRequest]

    def __call__(self, request: ProviderRequest) -> ProviderCandidate:
        return ProviderCandidate(True, "retrieval_request", self.build_candidate(request))


@dataclass(frozen=True)
class RolePathPlannerProvider:
    build_candidate: Callable[[ProviderRequest], PlannerHandoff]

    def __call__(self, request: ProviderRequest) -> ProviderCandidate:
        return ProviderCandidate(True, "planner_handoff", self.build_candidate(request))


@dataclass(frozen=True)
class RolePathExecutorProvider:
    build_candidate: Callable[[ProviderRequest], TransformProgram | GeneratedCodeCandidate]

    def __call__(self, request: ProviderRequest) -> ProviderCandidate:
        return ProviderCandidate(True, "executor_program", self.build_candidate(request))


@dataclass(frozen=True)
class RolePathSummarizerProvider:
    build_candidate: Callable[[ProviderRequest], ClaimSet]

    def __call__(self, request: ProviderRequest) -> ProviderCandidate:
        return ProviderCandidate(True, "summary_claim_set", self.build_candidate(request))


def detach_provider_candidate(candidate: ProviderCandidate) -> ProviderCandidate:
    """Copy nested carrier data before the dispatcher owns it."""
    payload = deepcopy(candidate.payload)
    if isinstance(payload, TransformProgram):
        payload = TransformProgram(
            program_id=payload.program_id,
            input_artifact_refs=tuple(payload.input_artifact_refs),
            operations=tuple(
                TransformStep(op=item.op, arguments=deepcopy(dict(item.arguments)))
                for item in payload.operations
            ),
            output_contract_version=payload.output_contract_version,
        )
    return ProviderCandidate(
        success=candidate.success,
        candidate_kind=candidate.candidate_kind,
        payload=payload,
        diagnostics=tuple((str(key), value) for key, value in candidate.diagnostics),
        retryable=candidate.retryable,
        error_code=candidate.error_code,
    )


__all__ = [
    "AttemptBoundProviderStateReadFacade",
    "BoundProviderHandler",
    "DiagnosticScalar",
    "ImmutableStateReadView",
    "ProviderAuthorityError",
    "ProviderCandidate",
    "ProviderDiagnostic",
    "ProviderRequest",
    "ProviderStateReadFacade",
    "RolePathExecutorProvider",
    "RolePathPlannerProvider",
    "RolePathRetrieverProvider",
    "RolePathSummarizerProvider",
    "RoleProviderContext",
    "detach_provider_candidate",
]
