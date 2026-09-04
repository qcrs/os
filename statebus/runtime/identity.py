from __future__ import annotations

import time
import uuid
from pathlib import PurePath
from typing import Any

from statebus.contracts.identity import (
    IdentityContractError,
    RuntimeIdentity,
    TaskContractIdentity,
)


class RuntimeIdentityResolutionError(IdentityContractError):
    """Raised when an identity does not agree with a legacy request projection."""


def validate_runtime_id_component(value: str, *, field_name: str = "runtime_id") -> str:
    """Validate a single identity component before it reaches a workspace path.

    Runtime task IDs remain the compatibility workspace component in Batch 1,
    so separators and parent components are rejected without imposing a new
    global naming scheme on existing IDs.
    """

    if not isinstance(value, str) or not value:
        raise RuntimeIdentityResolutionError(f"{field_name}_invalid_component")
    if value != value.strip():
        raise RuntimeIdentityResolutionError(f"{field_name}_invalid_component")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise RuntimeIdentityResolutionError(f"{field_name}_invalid_component")
    if "/" in value or "\\" in value:
        raise RuntimeIdentityResolutionError(f"{field_name}_path_separator_forbidden")
    if value in {".", ".."}:
        raise RuntimeIdentityResolutionError(f"{field_name}_invalid_component")
    path = PurePath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeIdentityResolutionError(f"{field_name}_invalid_component")
    return value


def _validate_trace_component(value: str) -> str:
    return validate_runtime_id_component(value, field_name="trace_id")


def new_run_id(runtime_task_id: str | None = None, *, prefix: str = "run") -> str:
    """Create a fresh physical run identity without deriving it from a task ID."""

    if runtime_task_id is not None:
        validate_runtime_id_component(runtime_task_id, field_name="runtime_task_id")
    validate_runtime_id_component(prefix, field_name="run_id_prefix")
    # UUID supplies uniqueness when tests freeze the clock; the timestamp keeps
    # the identifier useful in local runtime evidence.
    return f"{prefix}-{time.time_ns()}-{uuid.uuid4().hex[:12]}"


def compatibility_runtime_identity(
    task_id: str,
    trace_id: str,
    canonical_task_spec_hash: str,
    *,
    external_case_id: str | None = None,
    run_id: str | None = None,
    session_id: str | None = None,
    session_prefix: str = "adaptive-session",
    task_contract: TaskContractIdentity | None = None,
) -> RuntimeIdentity:
    """Project a legacy request into the additive RuntimeIdentity contract."""

    validate_runtime_id_component(task_id, field_name="runtime_task_id")
    _validate_trace_component(trace_id)
    if not isinstance(canonical_task_spec_hash, str) or not canonical_task_spec_hash:
        raise RuntimeIdentityResolutionError("task_contract_hash_required")
    validate_runtime_id_component(session_prefix, field_name="session_id_prefix")
    resolved_contract = task_contract or TaskContractIdentity.from_hash(canonical_task_spec_hash)
    if resolved_contract.contract_hash != canonical_task_spec_hash:
        raise RuntimeIdentityResolutionError("task_contract_hash_projection_mismatch")
    resolved_run_id = new_run_id(task_id) if run_id is None else run_id
    validate_runtime_id_component(resolved_run_id, field_name="run_id")
    resolved_session_id = f"{session_prefix}-{task_id}" if session_id is None else session_id
    validate_runtime_id_component(resolved_session_id, field_name="session_id")
    return RuntimeIdentity(
        external_case_id=external_case_id,
        runtime_task_id=task_id,
        run_id=resolved_run_id,
        session_id=resolved_session_id,
        trace_id=trace_id,
        task_contract=resolved_contract,
    )


# Explicit name for callers that want to emphasize the legacy projection.
legacy_runtime_identity = compatibility_runtime_identity


def resolve_runtime_identity(
    runtime_identity: RuntimeIdentity | None = None,
    *,
    task_id: str | None = None,
    trace_id: str | None = None,
    canonical_task_spec_hash: str | None = None,
    external_case_id: str | None = None,
    run_id: str | None = None,
    session_id: str | None = None,
    session_prefix: str = "adaptive-session",
    task_contract: TaskContractIdentity | None = None,
) -> RuntimeIdentity:
    """Resolve one identity at the product boundary and validate projections."""

    if runtime_identity is not None:
        if not isinstance(runtime_identity, RuntimeIdentity):
            raise RuntimeIdentityResolutionError("runtime_identity_type_required")
        try:
            runtime_identity.validate_legacy_projection(
                task_id=task_id,
                canonical_task_spec_hash=canonical_task_spec_hash,
                trace_id=trace_id,
            )
        except IdentityContractError as exc:
            raise RuntimeIdentityResolutionError(str(exc)) from exc
        if external_case_id is not None and external_case_id != runtime_identity.external_case_id:
            raise RuntimeIdentityResolutionError("external_case_id_projection_mismatch")
        if run_id is not None and run_id != runtime_identity.run_id:
            raise RuntimeIdentityResolutionError("run_id_projection_mismatch")
        if session_id is not None and session_id != runtime_identity.session_id:
            raise RuntimeIdentityResolutionError("session_id_projection_mismatch")
        if task_contract is not None and task_contract != runtime_identity.task_contract:
            raise RuntimeIdentityResolutionError("task_contract_projection_mismatch")
        return runtime_identity

    if task_id is None or trace_id is None or canonical_task_spec_hash is None:
        raise RuntimeIdentityResolutionError("legacy_identity_projection_requires_task_trace_and_contract")
    return compatibility_runtime_identity(
        task_id,
        trace_id,
        canonical_task_spec_hash,
        external_case_id=external_case_id,
        run_id=run_id,
        session_id=session_id,
        session_prefix=session_prefix,
        task_contract=task_contract,
    )


def validate_identity_projection(
    runtime_identity: RuntimeIdentity,
    *,
    task_id: str,
    canonical_task_spec_hash: str,
    trace_id: str | None = None,
) -> RuntimeIdentity:
    """Convenience assertion used by request-boundary code and tests."""

    return resolve_runtime_identity(
        runtime_identity,
        task_id=task_id,
        canonical_task_spec_hash=canonical_task_spec_hash,
        trace_id=trace_id,
    )


def identity_payload(identity: RuntimeIdentity) -> dict[str, Any]:
    """Return a JSON-ready payload for evidence without exposing secrets."""

    if not isinstance(identity, RuntimeIdentity):
        raise RuntimeIdentityResolutionError("runtime_identity_type_required")
    return identity.canonical_payload()
