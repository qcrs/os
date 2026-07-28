from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
from multiprocessing.shared_memory import SharedMemory
import os
from pathlib import Path
import struct
import time
from typing import Any

from v2.contracts import (
    CandidateSurfaceV2,
    LOGIT_BYTE_ORDER,
    LOGIT_DTYPE,
    LOGIT_GATE_MARGIN_THRESHOLD,
    LOGIT_PROBABILITY_SEMANTICS,
    LOGIT_STATE_SCHEMA_VERSION,
    LogitGateAction,
    LogitGateReceipt,
    StorageKind,
)
from v2.refs import LogitStateRef
from v2.runtime.logit_state import ExactChoiceLogitResult
from v2.state.store import LayeredStateStore, MaterializedStateHandle
from v2.utils import sha256_digest, stable_json_dumps


class LogitStateValidationError(ValueError):
    pass


@dataclass(frozen=True)
class LogitStateContract:
    state_id: str
    task_id: str
    trace_id: str
    request_id: str
    attempt_id: str
    candidate_surface: CandidateSurfaceV2
    selected_alias: str
    selected_candidate_id: str
    selected_candidate_ordinal: int
    producer_pid: int
    lease_created_at_ns: int
    lease_expires_at_ns: int
    blob_hash: str
    size_bytes: int
    storage_kind: str = ""
    dtype: str = LOGIT_DTYPE
    byte_order: str = LOGIT_BYTE_ORDER
    probability_semantics: str = LOGIT_PROBABILITY_SEMANTICS
    schema_version: str = LOGIT_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        required = (
            self.state_id,
            self.task_id,
            self.trace_id,
            self.request_id,
            self.attempt_id,
            self.selected_alias,
            self.selected_candidate_id,
            self.blob_hash,
        )
        if any(not value for value in required):
            raise ValueError("logit state contract requires complete identity")
        if self.selected_alias not in self.candidate_surface.aliases:
            raise ValueError("selected alias outside candidate surface")
        if self.candidate_surface.candidate_id_for_alias(self.selected_alias) != self.selected_candidate_id:
            raise ValueError("selected candidate binding mismatch")
        if self.selected_candidate_ordinal != self.candidate_surface.aliases.index(self.selected_alias):
            raise ValueError("selected candidate ordinal mismatch")
        if self.producer_pid <= 0:
            raise ValueError("logit state producer PID must be positive")
        if self.lease_created_at_ns <= 0 or self.lease_expires_at_ns <= self.lease_created_at_ns:
            raise ValueError("invalid logit state lease")
        if self.dtype != LOGIT_DTYPE or self.byte_order != LOGIT_BYTE_ORDER:
            raise ValueError("logit state must use little-endian float32")
        if self.probability_semantics != LOGIT_PROBABILITY_SEMANTICS:
            raise ValueError("unsupported logit probability semantics")
        if self.size_bytes != 4 * (self.candidate_surface.candidate_count + 1):
            raise ValueError("logit state payload size mismatch")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state_id": self.state_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "attempt_id": self.attempt_id,
            "candidate_surface": self.candidate_surface.canonical_payload(),
            "candidate_surface_digest": self.candidate_surface.candidate_surface_digest,
            "alias_mapping_digest": self.candidate_surface.alias_mapping_digest,
            "selected_alias": self.selected_alias,
            "selected_candidate_id": self.selected_candidate_id,
            "selected_candidate_ordinal": self.selected_candidate_ordinal,
            "producer_pid": self.producer_pid,
            "lease_created_at_ns": self.lease_created_at_ns,
            "lease_expires_at_ns": self.lease_expires_at_ns,
            "blob_hash": self.blob_hash,
            "size_bytes": self.size_bytes,
            "storage_kind": self.storage_kind,
            "dtype": self.dtype,
            "byte_order": self.byte_order,
            "probability_semantics": self.probability_semantics,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "LogitStateContract":
        if not isinstance(payload, dict):
            raise LogitStateValidationError("logit_state_contract_missing")
        try:
            return cls(
                state_id=str(payload.get("state_id", "")),
                task_id=str(payload.get("task_id", "")),
                trace_id=str(payload.get("trace_id", "")),
                request_id=str(payload.get("request_id", "")),
                attempt_id=str(payload.get("attempt_id", "")),
                candidate_surface=CandidateSurfaceV2.from_payload(
                    payload.get("candidate_surface")
                ),
                selected_alias=str(payload.get("selected_alias", "")),
                selected_candidate_id=str(payload.get("selected_candidate_id", "")),
                selected_candidate_ordinal=int(payload.get("selected_candidate_ordinal", -1)),
                producer_pid=int(payload.get("producer_pid", 0)),
                lease_created_at_ns=int(payload.get("lease_created_at_ns", 0)),
                lease_expires_at_ns=int(payload.get("lease_expires_at_ns", 0)),
                blob_hash=str(payload.get("blob_hash", "")),
                size_bytes=int(payload.get("size_bytes", 0)),
                storage_kind=str(payload.get("storage_kind", "")),
                dtype=str(payload.get("dtype", "")),
                byte_order=str(payload.get("byte_order", "")),
                probability_semantics=str(payload.get("probability_semantics", "")),
                schema_version=str(payload.get("schema_version", "")),
            )
        except (TypeError, ValueError) as exc:
            raise LogitStateValidationError(str(exc) or "logit_state_contract_invalid") from exc


@dataclass(frozen=True)
class LogitStatePublication:
    ref: LogitStateRef
    handle: MaterializedStateHandle
    contract: LogitStateContract


@dataclass(frozen=True)
class ResolvedLogitState:
    ref: LogitStateRef
    contract: LogitStateContract
    values: tuple[float, ...]
    consumer_pid: int


def publish_logit_state(
    *,
    store: LayeredStateStore,
    extraction: ExactChoiceLogitResult,
    candidate_surface: CandidateSurfaceV2,
    task_id: str,
    trace_id: str,
    state_id: str,
    lease_ttl_ms: int = 60_000,
    now_ns: int | None = None,
) -> LogitStatePublication:
    if not extraction.available:
        raise LogitStateValidationError(
            extraction.receipt.unavailable_reason or "logit_unavailable"
        )
    if extraction.receipt.candidate_surface_digest != candidate_surface.candidate_surface_digest:
        raise LogitStateValidationError("logit_candidate_surface_digest_mismatch")
    if extraction.receipt.alias_mapping_digest != candidate_surface.alias_mapping_digest:
        raise LogitStateValidationError("logit_alias_mapping_digest_mismatch")
    created_at_ns = time.time_ns() if now_ns is None else now_ns
    contract = LogitStateContract(
        state_id=state_id,
        task_id=task_id,
        trace_id=trace_id,
        request_id=extraction.receipt.request_id,
        attempt_id=extraction.receipt.attempt_id,
        candidate_surface=candidate_surface,
        selected_alias=extraction.selected_alias,
        selected_candidate_id=extraction.selected_candidate_id,
        selected_candidate_ordinal=extraction.selected_candidate_ordinal,
        producer_pid=os.getpid(),
        lease_created_at_ns=created_at_ns,
        lease_expires_at_ns=created_at_ns + lease_ttl_ms * 1_000_000,
        blob_hash=sha256_digest(extraction.payload_bytes),
        size_bytes=len(extraction.payload_bytes),
    )
    handle = store.publish(
        ref_id=state_id,
        object_kind="LOGIT_STATE",
        payload=extraction.payload_bytes,
        contract_metadata={"logit_state": contract.canonical_payload()},
    )
    if handle.storage_kind is not StorageKind.SHARED_MEMORY:
        store.release(state_id)
        handle.metadata_path.unlink(missing_ok=True)
        raise LogitStateValidationError("logit_state_requires_shared_memory")
    if handle.blob_hash != contract.blob_hash or handle.size_bytes != contract.size_bytes:
        store.release(state_id)
        handle.metadata_path.unlink(missing_ok=True)
        raise LogitStateValidationError("logit_state_materialization_mismatch")
    contract = replace(contract, storage_kind=handle.storage_kind.value)
    ref = LogitStateRef(
        state_id=state_id,
        producer_role="executor",
        consumer_role="logit_gate",
        storage_kind=handle.storage_kind,
        length=handle.size_bytes,
        blob_hash=handle.blob_hash,
        top_k=extraction.receipt.top_k,
        entropy=extraction.entropy,
        confidence_proxy=extraction.candidate_probabilities[
            extraction.selected_candidate_ordinal
        ],
        metadata={
            **contract.canonical_payload(),
            "shared_memory_name": handle.shared_memory_name,
        },
    )
    return LogitStatePublication(ref=ref, handle=handle, contract=contract)


def logit_ref_from_sidecar(state_root: Path, state_id: str) -> LogitStateRef:
    sidecar = _load_sidecar(state_root, state_id)
    contract_payload = dict(sidecar.get("contract_metadata", {})).get("logit_state")
    contract = LogitStateContract.from_payload(contract_payload)
    storage_kind = str(sidecar.get("storage_kind", ""))
    try:
        kind = StorageKind(storage_kind)
    except ValueError as exc:
        raise LogitStateValidationError("logit_state_storage_kind_invalid") from exc
    contract = replace(contract, storage_kind=kind.value)
    if contract.state_id != state_id:
        raise LogitStateValidationError("logit_state_id_mismatch")
    return LogitStateRef(
        state_id=state_id,
        producer_role="executor",
        consumer_role="logit_gate",
        storage_kind=kind,
        length=int(sidecar.get("size_bytes", 0)),
        blob_hash=str(sidecar.get("blob_hash", "")),
        top_k=0,
        metadata={
            **contract.canonical_payload(),
            "shared_memory_name": str(sidecar.get("shared_memory_name", "")),
        },
    )


def resolve_logit_state(
    *,
    state_root: Path,
    ref: LogitStateRef,
    now_ns: int | None = None,
    unregister_shared_memory_tracker: bool = False,
) -> ResolvedLogitState:
    sidecar = _load_sidecar(state_root, ref.state_id)
    contract_payload = dict(sidecar.get("contract_metadata", {})).get("logit_state")
    contract = replace(
        LogitStateContract.from_payload(contract_payload),
        storage_kind=str(sidecar.get("storage_kind", "")),
    )
    current_ns = time.time_ns() if now_ns is None else now_ns
    if current_ns >= contract.lease_expires_at_ns:
        raise LogitStateValidationError("logit_state_expired")
    if contract.state_id != ref.state_id or contract.blob_hash != ref.blob_hash:
        raise LogitStateValidationError("logit_state_ref_contract_mismatch")
    if contract.size_bytes != ref.length:
        raise LogitStateValidationError("logit_state_length_mismatch")
    if contract.storage_kind != StorageKind.SHARED_MEMORY.value:
        raise LogitStateValidationError("logit_state_requires_shared_memory")
    name = str(sidecar.get("shared_memory_name", ""))
    if not name:
        raise LogitStateValidationError("logit_state_shared_memory_name_missing")
    try:
        shared = SharedMemory(name=name)
    except FileNotFoundError as exc:
        raise LogitStateValidationError("logit_state_payload_missing") from exc
    try:
        if unregister_shared_memory_tracker:
            from multiprocessing import resource_tracker

            resource_tracker.unregister(shared._name, "shared_memory")
        payload = bytes(shared.buf[: contract.size_bytes])
    finally:
        shared.close()
    if len(payload) != contract.size_bytes or sha256_digest(payload) != contract.blob_hash:
        raise LogitStateValidationError("logit_state_blob_hash_mismatch")
    width = contract.candidate_surface.candidate_count + 1
    try:
        values = tuple(float(value) for value in struct.unpack(f"<{width}f", payload))
    except struct.error as exc:
        raise LogitStateValidationError("logit_state_payload_shape_invalid") from exc
    if any(not math.isfinite(value) or value < 0.0 or value > 1.0 for value in values):
        raise LogitStateValidationError("logit_state_probability_invalid")
    if abs(sum(values) - 1.0) > 1e-4:
        raise LogitStateValidationError("logit_state_probability_sum_invalid")
    return ResolvedLogitState(
        ref=ref,
        contract=contract,
        values=values,
        consumer_pid=os.getpid(),
    )


def evaluate_logit_state(
    resolved: ResolvedLogitState,
    *,
    margin_threshold: float = LOGIT_GATE_MARGIN_THRESHOLD,
) -> LogitGateReceipt:
    contract = resolved.contract
    candidate_values = resolved.values[:-1]
    other_mass = resolved.values[-1]
    top1_ordinal = max(range(len(candidate_values)), key=candidate_values.__getitem__)
    ordered = sorted(candidate_values, reverse=True)
    top_margin = ordered[0] - ordered[1]
    selected_probability = candidate_values[contract.selected_candidate_ordinal]
    selected_is_top1 = contract.selected_candidate_ordinal == top1_ordinal
    margin_passed = top_margin >= margin_threshold
    action = (
        LogitGateAction.ACCEPT
        if selected_is_top1 and margin_passed
        else LogitGateAction.RETRY
    )
    if not selected_is_top1:
        reason = "selected_alias_not_top1"
    elif not margin_passed:
        reason = "top_margin_below_threshold"
    else:
        reason = "selected_alias_is_top1_and_margin_passed"
    entropy = -sum(value * math.log(value) for value in resolved.values if value > 0.0)
    normalized_entropy = entropy / math.log(len(resolved.values))
    top1_alias = contract.candidate_surface.aliases[top1_ordinal]
    decision_id = sha256_digest({
        "state_id": contract.state_id,
        "blob_hash": contract.blob_hash,
        "selected_alias": contract.selected_alias,
        "top1_alias": top1_alias,
        "top_margin": top_margin,
        "margin_threshold": margin_threshold,
        "consumer_pid": resolved.consumer_pid,
    })
    return LogitGateReceipt(
        state_id=contract.state_id,
        decision_id=decision_id,
        action=action,
        reason=reason,
        selected_alias=contract.selected_alias,
        selected_candidate_id=contract.selected_candidate_id,
        top1_alias=top1_alias,
        selected_probability=selected_probability,
        top_margin=top_margin,
        normalized_entropy=normalized_entropy,
        other_mass=other_mass,
        candidate_count=contract.candidate_surface.candidate_count,
        producer_pid=contract.producer_pid,
        consumer_pid=resolved.consumer_pid,
        margin_threshold=margin_threshold,
    )


def release_logit_state(
    *,
    store: LayeredStateStore,
    publication: LogitStatePublication,
    reason: str,
    consumer_pid: int = 0,
) -> Path:
    store.release(publication.ref.state_id)
    publication.handle.metadata_path.unlink(missing_ok=True)
    tombstone_dir = store.root / "tombstones"
    tombstone_dir.mkdir(parents=True, exist_ok=True)
    tombstone_path = tombstone_dir / f"{publication.ref.state_id}.json"
    tombstone_path.write_text(
        stable_json_dumps({
            "schema_version": "statebus.logit_state_tombstone.v1",
            "state_id": publication.ref.state_id,
            "lifecycle_status": "released",
            "release_reason": reason,
            "released_at_ns": time.time_ns(),
            "released_bytes": publication.ref.length,
            "producer_pid": publication.contract.producer_pid,
            "consumer_pid": consumer_pid,
            "blob_hash": publication.ref.blob_hash,
        }) + "\n",
        encoding="utf-8",
    )
    return tombstone_path


def _load_sidecar(state_root: Path, state_id: str) -> dict[str, Any]:
    path = Path(state_root) / "metadata" / f"{state_id}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LogitStateValidationError("logit_state_metadata_missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise LogitStateValidationError("logit_state_metadata_corrupt") from exc
    if not isinstance(payload, dict):
        raise LogitStateValidationError("logit_state_metadata_invalid")
    return payload
