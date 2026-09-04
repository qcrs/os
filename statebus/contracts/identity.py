from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from statebus.utils import sha256_digest

if TYPE_CHECKING:
    from statebus.contracts.models import CanonicalTaskSpec


TASK_CONTRACT_IDENTITY_SCHEMA_VERSION = "statebus.task_contract_identity.v1"
RUNTIME_IDENTITY_SCHEMA_VERSION = "statebus.runtime_identity.v1"


class IdentityContractError(ValueError):
    """Raised when a runtime identity cannot satisfy its compatibility contract."""


@dataclass(frozen=True)
class TaskContractIdentity:
    """Stable identity for the task contract used by one runtime execution."""

    contract_kind: str = "canonical_task_spec"
    contract_hash: str = ""
    public_context_hash: str = ""
    input_asset_set_hash: str = ""
    legacy_canonical_task_spec_hash: str = ""
    schema_version: str = TASK_CONTRACT_IDENTITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.contract_kind, str) or not self.contract_kind.strip():
            raise IdentityContractError("task_contract_kind_required")
        if not isinstance(self.contract_hash, str) or not self.contract_hash:
            raise IdentityContractError("task_contract_hash_required")
        if not isinstance(self.schema_version, str) or not self.schema_version.strip():
            raise IdentityContractError("task_contract_schema_version_required")
        for field_name in ("public_context_hash", "input_asset_set_hash"):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise IdentityContractError(f"{field_name}_must_be_string")

        if not isinstance(self.legacy_canonical_task_spec_hash, str):
            raise IdentityContractError("legacy_canonical_task_spec_hash_must_be_string")
        legacy_hash = self.legacy_canonical_task_spec_hash or self.contract_hash
        if legacy_hash != self.contract_hash:
            raise IdentityContractError("task_contract_hash_mismatch")
        object.__setattr__(self, "legacy_canonical_task_spec_hash", legacy_hash)

    @classmethod
    def from_canonical_task_spec(
        cls,
        spec: "CanonicalTaskSpec",
        *,
        public_context_hash: str = "",
        input_asset_set_hash: str = "",
    ) -> "TaskContractIdentity":
        return cls(
            contract_kind="canonical_task_spec",
            contract_hash=spec.spec_hash,
            public_context_hash=public_context_hash,
            input_asset_set_hash=input_asset_set_hash,
            legacy_canonical_task_spec_hash=spec.spec_hash,
        )

    # Short alias for callers that use the contract's existing type name.
    from_canonical_spec = from_canonical_task_spec

    @classmethod
    def from_hash(
        cls,
        contract_hash: str,
        *,
        contract_kind: str = "canonical_task_spec",
        public_context_hash: str = "",
        input_asset_set_hash: str = "",
    ) -> "TaskContractIdentity":
        return cls(
            contract_kind=contract_kind,
            contract_hash=contract_hash,
            public_context_hash=public_context_hash,
            input_asset_set_hash=input_asset_set_hash,
            legacy_canonical_task_spec_hash=contract_hash,
        )

    @property
    def canonical_task_spec_hash(self) -> str:
        """Compatibility name retained for CanonicalTaskSpec-backed callers."""

        return self.contract_hash

    @property
    def identity_hash(self) -> str:
        return sha256_digest(self.canonical_payload())

    @property
    def contract_identity_hash(self) -> str:
        return self.identity_hash

    def canonical_payload(self) -> dict[str, object]:
        return {
            "contract_kind": self.contract_kind,
            "contract_hash": self.contract_hash,
            "public_context_hash": self.public_context_hash,
            "input_asset_set_hash": self.input_asset_set_hash,
            "legacy_canonical_task_spec_hash": self.legacy_canonical_task_spec_hash,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class RuntimeIdentity:
    """Identity aggregate separating logical task, run, session and telemetry."""

    # Defaults keep the schema's documented field order usable with keyword or
    # positional construction while __post_init__ enforces required values.
    external_case_id: str | None = None
    runtime_task_id: str = ""
    run_id: str = ""
    session_id: str = ""
    trace_id: str = ""
    task_contract: TaskContractIdentity | None = None
    schema_version: str = RUNTIME_IDENTITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        from statebus.runtime.identity import validate_runtime_id_component

        validate_runtime_id_component(self.runtime_task_id, field_name="runtime_task_id")
        validate_runtime_id_component(self.run_id, field_name="run_id")
        validate_runtime_id_component(self.session_id, field_name="session_id")
        validate_runtime_id_component(self.trace_id, field_name="trace_id")
        if self.external_case_id is not None:
            if not isinstance(self.external_case_id, str) or not self.external_case_id.strip():
                raise IdentityContractError("external_case_id_invalid")
            if any(ord(char) < 32 or ord(char) == 127 for char in self.external_case_id):
                raise IdentityContractError("external_case_id_invalid")
        if not isinstance(self.task_contract, TaskContractIdentity):
            raise IdentityContractError("task_contract_identity_required")
        if not isinstance(self.schema_version, str) or not self.schema_version.strip():
            raise IdentityContractError("runtime_identity_schema_version_required")

    @property
    def task_id(self) -> str:
        """Legacy task_id projection; it is never a second identity."""

        return self.runtime_task_id

    @property
    def canonical_task_spec_hash(self) -> str:
        return self.task_contract.contract_hash

    @property
    def task_contract_hash(self) -> str:
        return self.task_contract.contract_hash

    @property
    def identity_hash(self) -> str:
        return sha256_digest(self.canonical_payload())

    @property
    def runtime_identity_hash(self) -> str:
        return self.identity_hash

    def canonical_payload(self) -> dict[str, object]:
        return {
            "external_case_id": self.external_case_id,
            "runtime_task_id": self.runtime_task_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "task_contract": self.task_contract.canonical_payload(),
            "schema_version": self.schema_version,
        }

    def validate_legacy_projection(
        self,
        *,
        task_id: str | None = None,
        canonical_task_spec_hash: str | None = None,
        trace_id: str | None = None,
    ) -> "RuntimeIdentity":
        if task_id is not None and task_id != self.runtime_task_id:
            raise IdentityContractError("runtime_task_id_projection_mismatch")
        if (
            canonical_task_spec_hash is not None
            and canonical_task_spec_hash != self.task_contract.contract_hash
        ):
            raise IdentityContractError("task_contract_hash_projection_mismatch")
        if trace_id is not None and trace_id != self.trace_id:
            raise IdentityContractError("trace_id_projection_mismatch")
        return self

    # More explicit spelling for API/contract tests.
    assert_legacy_projection = validate_legacy_projection

    @classmethod
    def from_legacy(
        cls,
        task_id: str,
        trace_id: str,
        canonical_task_spec_hash: str,
        **kwargs: object,
    ) -> "RuntimeIdentity":
        from statebus.runtime.identity import compatibility_runtime_identity

        return compatibility_runtime_identity(
            task_id,
            trace_id,
            canonical_task_spec_hash,
            **kwargs,
        )
