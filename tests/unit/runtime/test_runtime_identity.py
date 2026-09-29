from __future__ import annotations

import pytest

from statebus.contracts import (
    CanonicalTaskSpec,
    IdentityContractError,
    RuntimeIdentity,
    TaskContractIdentity,
)
from statebus.runtime.identity import (
    RuntimeIdentityResolutionError,
    compatibility_runtime_identity,
    resolve_runtime_identity,
    validate_runtime_id_component,
)


def _identity(*, run_id: str = "run-1", session_id: str = "session-1") -> RuntimeIdentity:
    return RuntimeIdentity(
        external_case_id="case-42",
        runtime_task_id="runtime-task",
        run_id=run_id,
        session_id=session_id,
        trace_id=f"trace-{run_id}",
        task_contract=TaskContractIdentity.from_hash("sha256:task-contract"),
    )


def test_runtime_identity_hash_is_stable() -> None:
    identity = _identity()
    equivalent = RuntimeIdentity(
        external_case_id=identity.external_case_id,
        runtime_task_id=identity.runtime_task_id,
        run_id=identity.run_id,
        session_id=identity.session_id,
        trace_id=identity.trace_id,
        task_contract=TaskContractIdentity.from_hash(identity.task_contract.contract_hash),
        schema_version=identity.schema_version,
    )

    assert identity.identity_hash == identity.identity_hash
    assert identity.identity_hash == equivalent.identity_hash


def test_runtime_identity_distinguishes_reruns() -> None:
    first = _identity(run_id="run-1", session_id="session-1")
    second = _identity(run_id="run-2", session_id="session-2")

    assert first.runtime_task_id == second.runtime_task_id
    assert first.task_contract == second.task_contract
    assert first.identity_hash != second.identity_hash


def test_runtime_task_id_is_stable_across_reruns() -> None:
    assert _identity(run_id="run-a").runtime_task_id == _identity(run_id="run-b").runtime_task_id
    assert _identity(run_id="run-a").task_id == "runtime-task"


def test_task_contract_identity_projects_canonical_spec_hash() -> None:
    spec = CanonicalTaskSpec(
        task_family="report",
        intent_op="summarize",
        required_outputs=("summary",),
    )
    contract = TaskContractIdentity.from_canonical_task_spec(spec)

    assert contract.contract_hash == spec.spec_hash
    assert contract.legacy_canonical_task_spec_hash == spec.spec_hash
    assert contract.canonical_task_spec_hash == spec.spec_hash


def test_explicit_session_id_is_not_silently_rederived() -> None:
    identity = compatibility_runtime_identity(
        "task",
        "trace-task",
        "spec",
        run_id="run-explicit",
        session_id="session-explicit",
    )

    resolved = resolve_runtime_identity(
        identity,
        task_id="task",
        trace_id="trace-task",
        canonical_task_spec_hash="spec",
    )
    assert resolved.session_id == "session-explicit"
    assert resolved.run_id == "run-explicit"


def test_legacy_identity_projection_is_deterministic_except_run_id() -> None:
    first = compatibility_runtime_identity(
        "task",
        "trace-task",
        "spec",
        run_id="run-1",
    )
    second = compatibility_runtime_identity(
        "task",
        "trace-task",
        "spec",
        run_id="run-2",
    )

    first_payload = first.canonical_payload()
    second_payload = second.canonical_payload()
    first_payload["run_id"] = "<run>"
    second_payload["run_id"] = "<run>"
    assert first_payload == second_payload
    assert first.session_id == second.session_id == "adaptive-session-task"


@pytest.mark.parametrize("value", ("..", ".", "../task"))
def test_runtime_task_id_rejects_parent_traversal(value: str) -> None:
    with pytest.raises(RuntimeIdentityResolutionError):
        validate_runtime_id_component(value, field_name="runtime_task_id")


@pytest.mark.parametrize("value", ("task/child", "task\\child"))
def test_runtime_task_id_rejects_path_separator(value: str) -> None:
    with pytest.raises(RuntimeIdentityResolutionError):
        validate_runtime_id_component(value, field_name="runtime_task_id")


def test_run_id_rejects_empty_or_invalid_component() -> None:
    with pytest.raises(RuntimeIdentityResolutionError):
        compatibility_runtime_identity("task", "trace", "spec", run_id="")
    with pytest.raises(RuntimeIdentityResolutionError):
        compatibility_runtime_identity("task", "trace", "spec", run_id="run/child")


def test_runtime_identity_rejects_task_id_projection_mismatch() -> None:
    with pytest.raises(RuntimeIdentityResolutionError, match="runtime_task_id_projection_mismatch"):
        resolve_runtime_identity(
            _identity(),
            task_id="different-task",
            trace_id="trace-run-1",
            canonical_task_spec_hash="sha256:task-contract",
        )


def test_runtime_identity_rejects_task_contract_hash_mismatch() -> None:
    with pytest.raises(RuntimeIdentityResolutionError, match="task_contract_hash_projection_mismatch"):
        resolve_runtime_identity(
            _identity(),
            task_id="runtime-task",
            trace_id="trace-run-1",
            canonical_task_spec_hash="sha256:other-contract",
        )


def test_task_contract_identity_rejects_hash_mismatch() -> None:
    with pytest.raises(IdentityContractError, match="task_contract_hash_mismatch"):
        TaskContractIdentity(
            contract_hash="sha256:one",
            legacy_canonical_task_spec_hash="sha256:two",
        )
