from __future__ import annotations

from dataclasses import replace
import os
import socket

import pytest

from v2.contracts import CapabilityGrant
from v2.runtime.capability_grants import (
    CapabilityGrantAuthenticationError,
    CapabilityGrantAuthenticator,
    require_peer_uid,
)


def _grant(*, now_ns: int = 1_000_000_000) -> CapabilityGrant:
    return CapabilityGrant(
        grant_id="grant-1",
        task_id="task-1",
        session_id="session-1",
        step_id="step-1",
        attempt_id="attempt-1",
        capability_id="semantic_select_v1",
        capability_version="v1",
        input_ref_ids=("state-1",),
        output_contract_version="selection-v1",
        workspace_root_id="workspace-1",
        max_runtime_ms=1_000,
        expires_at_ns=now_ns + 1_000_000,
        approved_plan_hash="plan-1",
        grant_nonce="grant-nonce-1",
        issued_at_ns=now_ns,
    )


def _verify(authenticator: CapabilityGrantAuthenticator, token: str, grant: CapabilityGrant):
    return authenticator.verify(
        token,
        expected_grant_hash=grant.grant_hash,
        expected_task_id=grant.task_id,
        expected_session_id=grant.session_id,
        expected_step_id=grant.step_id,
        expected_attempt_id=grant.attempt_id,
        expected_ref_ids=("state-1",),
        expected_output_contract="selection-v1",
    )


def test_authenticated_grant_is_exact_bound_and_single_use() -> None:
    grant = _grant()
    authenticator = CapabilityGrantAuthenticator(secret=b"s" * 32, clock_ns=lambda: 1_000_000_100)
    token = authenticator.issue(
        grant,
        bound_ref_ids=("state-1",),
        bound_output_contract="selection-v1",
    )

    decoded = _verify(authenticator, token, grant)
    assert decoded["grant_hash"] == grant.grant_hash
    with pytest.raises(CapabilityGrantAuthenticationError, match="grant_replay"):
        _verify(authenticator, token, grant)


@pytest.mark.parametrize(
    ("override", "error"),
    (
        ({"expected_task_id": "other-task"}, "grant_task_id_binding_mismatch"),
        ({"expected_step_id": "other-step"}, "grant_step_id_binding_mismatch"),
        ({"expected_attempt_id": "other-attempt"}, "grant_attempt_id_binding_mismatch"),
        ({"expected_ref_ids": ("state-1", "state-2")}, "grant_ref_binding_mismatch"),
        ({"expected_output_contract": "other-output"}, "grant_output_binding_mismatch"),
    ),
)
def test_authenticated_grant_rejects_cross_binding(override, error) -> None:
    grant = _grant()
    authenticator = CapabilityGrantAuthenticator(secret=b"b" * 32, clock_ns=lambda: 1_000_000_100)
    token = authenticator.issue(
        grant,
        bound_ref_ids=("state-1",),
        bound_output_contract="selection-v1",
    )
    kwargs = {
        "expected_grant_hash": grant.grant_hash,
        "expected_task_id": grant.task_id,
        "expected_session_id": grant.session_id,
        "expected_step_id": grant.step_id,
        "expected_attempt_id": grant.attempt_id,
        "expected_ref_ids": ("state-1",),
        "expected_output_contract": "selection-v1",
    }
    kwargs.update(override)

    with pytest.raises(CapabilityGrantAuthenticationError, match=error):
        authenticator.verify(token, **kwargs)


def test_authenticated_grant_rejects_random_tampered_and_expired_tokens() -> None:
    grant = _grant()
    authenticator = CapabilityGrantAuthenticator(secret=b"c" * 32, clock_ns=lambda: 1_000_000_100)
    token = authenticator.issue(grant, bound_ref_ids=("state-1",))

    with pytest.raises(CapabilityGrantAuthenticationError, match="grant_token_malformed"):
        authenticator.verify("nonempty-random-hash")
    with pytest.raises(CapabilityGrantAuthenticationError, match="grant_signature_invalid"):
        authenticator.verify(token[:-1] + ("0" if token[-1] != "0" else "1"))

    expired = replace(grant, grant_nonce="expired", expires_at_ns=999_999_999)
    expired_token = authenticator.issue(expired, bound_ref_ids=("state-1",))
    with pytest.raises(CapabilityGrantAuthenticationError, match="grant_expired"):
        authenticator.verify(expired_token)


def test_peer_credentials_match_current_unix_identity() -> None:
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        pid, uid, gid = require_peer_uid(left, os.getuid())
    finally:
        left.close()
        right.close()

    assert pid == os.getpid()
    assert uid == os.getuid()
    assert gid == os.getgid()

