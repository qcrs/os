from __future__ import annotations

from dataclasses import dataclass
import time

from statebus.utils import sha256_digest


STATE_ACCESS_GRANT_SCHEMA_VERSION = "statebus.state_access_grant.v1"
STATE_ACCESS_MODE_READ = "READ"
STATE_ACCESS_AUTHORITY_CAPABILITY_INPUT = "CAPABILITY_INPUT"
STATE_ACCESS_AUTHORITY_RUNTIME_INTERMEDIATE = "RUNTIME_INTERMEDIATE"


class StateAccessContractError(ValueError):
    pass


@dataclass(frozen=True)
class StateAccessGrant:
    """Runtime-derived READ witness for one immutable State publication."""

    access_grant_id: str
    runtime_task_id: str
    run_id: str
    session_id: str
    step_id: str
    attempt_id: str
    execution_binding_hash: str
    capability_grant_hash: str
    ref_id: str
    ref_kind: str
    state_identity_hash: str
    access_mode: str
    authority_basis: str
    consumer_provider_id: str
    consumer_role: str
    physical_invocation_id: str
    expires_at_ns: int
    schema_version: str = STATE_ACCESS_GRANT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        required = (
            self.access_grant_id,
            self.runtime_task_id,
            self.run_id,
            self.session_id,
            self.step_id,
            self.attempt_id,
            self.execution_binding_hash,
            self.capability_grant_hash,
            self.ref_id,
            self.ref_kind,
            self.state_identity_hash,
            self.consumer_provider_id,
            self.consumer_role,
            self.schema_version,
        )
        if any(not value.strip() for value in required):
            raise StateAccessContractError("state_access_identity_required")
        if self.access_mode != STATE_ACCESS_MODE_READ:
            raise StateAccessContractError("state_access_mode_not_read")
        if self.authority_basis not in {
            STATE_ACCESS_AUTHORITY_CAPABILITY_INPUT,
            STATE_ACCESS_AUTHORITY_RUNTIME_INTERMEDIATE,
        }:
            raise StateAccessContractError("state_access_authority_basis_invalid")
        if self.expires_at_ns <= 0:
            raise StateAccessContractError("state_access_expiry_invalid")

    def validate_read_scope(
        self,
        *,
        runtime_task_id: str,
        run_id: str,
        session_id: str,
        step_id: str,
        attempt_id: str,
        execution_binding_hash: str,
        capability_grant_hash: str,
        ref_id: str,
        ref_kind: str,
        consumer_provider_id: str,
        consumer_role: str,
        physical_invocation_id: str,
        now_ns: int | None = None,
    ) -> None:
        if self.access_mode != STATE_ACCESS_MODE_READ:
            raise StateAccessContractError("state_access_mode_not_read")
        if (
            self.runtime_task_id != runtime_task_id
            or self.run_id != run_id
            or self.session_id != session_id
            or self.step_id != step_id
            or self.attempt_id != attempt_id
        ):
            raise StateAccessContractError("state_access_execution_scope_mismatch")
        if self.execution_binding_hash != execution_binding_hash:
            raise StateAccessContractError("state_access_execution_binding_mismatch")
        if self.capability_grant_hash != capability_grant_hash:
            raise StateAccessContractError("state_access_capability_grant_mismatch")
        if self.ref_id != ref_id or self.ref_kind != ref_kind:
            raise StateAccessContractError("state_access_ref_mismatch")
        if (
            self.consumer_provider_id != consumer_provider_id
            or self.consumer_role != consumer_role
        ):
            raise StateAccessContractError("state_access_consumer_mismatch")
        if self.physical_invocation_id != physical_invocation_id:
            raise StateAccessContractError("state_access_invocation_mismatch")
        if self.expires_at_ns <= (time.time_ns() if now_ns is None else now_ns):
            raise StateAccessContractError("state_access_expired")

    def validate_state_identity(self, state_identity_hash: str) -> None:
        if self.state_identity_hash != state_identity_hash:
            raise StateAccessContractError("state_access_identity_mismatch")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "access_grant_id": self.access_grant_id,
            "runtime_task_id": self.runtime_task_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "step_id": self.step_id,
            "attempt_id": self.attempt_id,
            "execution_binding_hash": self.execution_binding_hash,
            "capability_grant_hash": self.capability_grant_hash,
            "ref_id": self.ref_id,
            "ref_kind": self.ref_kind,
            "state_identity_hash": self.state_identity_hash,
            "access_mode": self.access_mode,
            "authority_basis": self.authority_basis,
            "consumer_provider_id": self.consumer_provider_id,
            "consumer_role": self.consumer_role,
            "physical_invocation_id": self.physical_invocation_id,
            "expires_at_ns": self.expires_at_ns,
            "schema_version": self.schema_version,
        }

    @property
    def access_grant_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


__all__ = [
    "STATE_ACCESS_AUTHORITY_CAPABILITY_INPUT",
    "STATE_ACCESS_AUTHORITY_RUNTIME_INTERMEDIATE",
    "STATE_ACCESS_GRANT_SCHEMA_VERSION",
    "STATE_ACCESS_MODE_READ",
    "StateAccessContractError",
    "StateAccessGrant",
]
