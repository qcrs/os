"""Cross-process CapabilityGrant authentication primitives.

The existing grant hash is an identity digest, not an authorization proof.  A
worker that runs in another process needs a signed, expiring envelope carrying
the exact task/step/attempt/ref/output binding.  This module keeps the secret
in memory (and, for the subprocess transport, an inherited environment entry)
without ever placing it in a command line, prompt, or artifact payload.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import time
from typing import Iterable

from v2.contracts import CapabilityGrant
from v2.utils import stable_json_dumps


class CapabilityGrantAuthenticationError(ValueError):
    """Stable fail-closed error code for a rejected grant token."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _canonical_token_payload(
    grant: CapabilityGrant,
    *,
    bound_ref_ids: Iterable[str] = (),
    bound_output_contract: str = "",
) -> dict[str, object]:
    return {
        "version": "statebus.capability_grant_token.v1",
        "grant_hash": grant.grant_hash,
        "grant": grant.canonical_payload(),
        "bound_ref_ids": list(dict.fromkeys(str(ref_id) for ref_id in bound_ref_ids)),
        "bound_output_contract": bound_output_contract or grant.output_contract_version,
    }


@dataclass
class CapabilityGrantAuthenticator:
    """Issue and verify HMAC-backed, single-use grant envelopes."""

    secret: bytes = field(repr=False)
    clock_ns: callable = time.time_ns
    nonce_registry_dir: Path | None = field(default=None, repr=False)
    _used_nonces: set[str] = field(default_factory=set, init=False, repr=False)

    @classmethod
    def generate(cls) -> "CapabilityGrantAuthenticator":
        return cls(secret=secrets.token_bytes(32))

    def issue(
        self,
        grant: CapabilityGrant,
        *,
        bound_ref_ids: Iterable[str] = (),
        bound_output_contract: str = "",
    ) -> str:
        if not self.secret:
            raise CapabilityGrantAuthenticationError("grant_secret_missing")
        if not grant.grant_nonce:
            raise CapabilityGrantAuthenticationError("grant_nonce_missing")
        payload = _canonical_token_payload(
            grant,
            bound_ref_ids=bound_ref_ids,
            bound_output_contract=bound_output_contract,
        )
        payload["token_nonce"] = secrets.token_urlsafe(18)
        encoded = _encode_payload(payload)
        signature = hmac.new(self.secret, encoded, hashlib.sha256).hexdigest()
        return f"{_b64encode(encoded)}.{signature}"

    def verify(
        self,
        token: str,
        *,
        expected_grant_hash: str = "",
        expected_task_id: str = "",
        expected_session_id: str = "",
        expected_step_id: str = "",
        expected_attempt_id: str = "",
        expected_ref_ids: Iterable[str] = (),
        expected_output_contract: str = "",
        consume: bool = True,
    ) -> dict[str, object]:
        if not self.secret:
            raise CapabilityGrantAuthenticationError("grant_secret_missing")
        try:
            encoded_text, signature = str(token).split(".", 1)
            encoded = _b64decode(encoded_text)
            decoded = json.loads(encoded.decode("utf-8"))
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
            raise CapabilityGrantAuthenticationError("grant_token_malformed") from None
        if not isinstance(decoded, dict) or not isinstance(signature, str):
            raise CapabilityGrantAuthenticationError("grant_token_malformed")
        expected_signature = hmac.new(self.secret, encoded, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise CapabilityGrantAuthenticationError("grant_signature_invalid")
        if decoded.get("version") != "statebus.capability_grant_token.v1":
            raise CapabilityGrantAuthenticationError("grant_token_version_unsupported")
        grant_payload = decoded.get("grant")
        if not isinstance(grant_payload, dict):
            raise CapabilityGrantAuthenticationError("grant_payload_missing")
        grant_hash = str(decoded.get("grant_hash", ""))
        if not grant_hash or grant_hash != str(sha256_payload(grant_payload)):
            raise CapabilityGrantAuthenticationError("grant_payload_hash_mismatch")
        if expected_grant_hash and grant_hash != expected_grant_hash:
            raise CapabilityGrantAuthenticationError("grant_binding_mismatch")
        _check_exact(grant_payload, "task_id", expected_task_id)
        _check_exact(grant_payload, "session_id", expected_session_id)
        _check_exact(grant_payload, "step_id", expected_step_id)
        _check_exact(grant_payload, "attempt_id", expected_attempt_id)
        expected_refs = tuple(dict.fromkeys(str(ref_id) for ref_id in expected_ref_ids))
        bound_refs = tuple(str(ref_id) for ref_id in decoded.get("bound_ref_ids", ()))
        if expected_refs and bound_refs != expected_refs:
            raise CapabilityGrantAuthenticationError("grant_ref_binding_mismatch")
        if expected_output_contract:
            bound_output = str(decoded.get("bound_output_contract", ""))
            if bound_output != expected_output_contract:
                raise CapabilityGrantAuthenticationError("grant_output_binding_mismatch")
        expires_at_ns = int(grant_payload.get("expires_at_ns", 0) or 0)
        if expires_at_ns <= 0 or expires_at_ns < int(self.clock_ns()):
            raise CapabilityGrantAuthenticationError("grant_expired")
        if not str(grant_payload.get("grant_nonce", "")):
            raise CapabilityGrantAuthenticationError("grant_nonce_missing")
        nonce = str(decoded.get("token_nonce", ""))
        if not nonce:
            raise CapabilityGrantAuthenticationError("grant_token_nonce_missing")
        if nonce in self._used_nonces:
            raise CapabilityGrantAuthenticationError("grant_replay")
        if consume:
            self._consume_registry_nonce(nonce)
            self._used_nonces.add(nonce)
        return decoded

    def _consume_registry_nonce(self, nonce: str) -> None:
        if self.nonce_registry_dir is None:
            return
        registry = Path(self.nonce_registry_dir)
        registry.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker = registry / hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        try:
            fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise CapabilityGrantAuthenticationError("grant_replay") from None
        else:
            os.close(fd)


def _check_exact(payload: dict[str, object], key: str, expected: str) -> None:
    if expected and str(payload.get(key, "")) != expected:
        raise CapabilityGrantAuthenticationError(f"grant_{key}_binding_mismatch")


def _encode_payload(payload: dict[str, object]) -> bytes:
    return stable_json_dumps(payload).encode("utf-8")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sha256_payload(payload: dict[str, object]) -> str:
    # Keep this independent of v2.utils so a worker can verify the hash without
    # reconstructing a CapabilityGrant object.  Grant hashes in this repo are
    # bare hexadecimal SHA-256 strings.
    return hashlib.sha256(_encode_payload(payload)).hexdigest()


def peer_credentials(sock: socket.socket) -> tuple[int, int, int]:
    """Return Linux SO_PEERCRED (pid, uid, gid), or a stable error."""

    try:
        raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        return struct.unpack("3i", raw)
    except (AttributeError, OSError, struct.error) as exc:
        raise CapabilityGrantAuthenticationError("peer_credentials_unavailable") from exc


def require_peer_uid(sock: socket.socket, expected_uid: int) -> tuple[int, int, int]:
    credentials = peer_credentials(sock)
    if credentials[1] != int(expected_uid):
        raise CapabilityGrantAuthenticationError("peer_uid_mismatch")
    return credentials
