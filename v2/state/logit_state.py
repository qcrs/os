from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from mmap import ACCESS_READ, mmap
from multiprocessing.shared_memory import SharedMemory
import os
from pathlib import Path
import secrets
import struct
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from v2.contracts import (
    CandidateAliasBinding,
    CandidateSurfaceV2,
    LogitPolicy,
    LogitProducerReceipt,
    LogitProducerStatus,
    LogitStateContractV2,
    RefStatus,
    StorageKind,
)
from v2.refs import LogitStateRefV2
from v2.state.store import LayeredStateStore, LayeredStoragePolicy, MaterializedStateHandle
from v2.utils import sha256_digest, stable_json_dumps

if TYPE_CHECKING:
    from v2.runtime.logit_state import ExactChoiceLogitResult


class LogitStateValidationError(ValueError):
    pass


@dataclass(frozen=True)
class LogitStatePublishContext:
    task_id: str
    session_id: str
    trace_id: str
    step_id: str
    request_id: str
    attempt_id: str
    prompt_sha256: str
    source_evidence_digest: str
    hydration_digest: str
    model_id: str
    model_revision: str
    tokenizer_id: str
    tokenizer_revision: str
    chat_template_sha256: str
    template_kwargs_sha256: str
    response_schema_digest: str
    owner_session_id: str
    calibration_version: str
    threshold_policy_version: str
    gate_budget_version: str
    policy: LogitPolicy
    producer_component: str = "choice_logprob_extractor"
    expected_consumer_pid: int = 0
    lease_ttl_ms: int = 60_000

    def __post_init__(self) -> None:
        if self.policy is LogitPolicy.OFF:
            raise ValueError("off policy cannot publish LogitState")
        if self.lease_ttl_ms <= 0:
            raise ValueError("LogitState lease TTL must be positive")


@dataclass(frozen=True)
class LogitStatePublication:
    ref: LogitStateRefV2
    handle: MaterializedStateHandle
    candidate_surface: CandidateSurfaceV2
    producer_receipt: LogitProducerReceipt
    active_sidecar_path: Path
    published_at_ns: int


@dataclass(frozen=True)
class LogitStateGrant:
    ref_id: str
    task_id: str
    session_id: str
    trace_id: str
    step_id: str
    request_id: str
    attempt_id: str
    consumer_component: str
    consumer_pid: int
    candidate_surface_digest: str
    alias_mapping_digest: str
    calibration_version: str
    threshold_policy_version: str
    gate_budget_version: str
    model_id: str
    tokenizer_id: str
    chat_template_sha256: str
    template_kwargs_sha256: str
    response_schema_digest: str
    expires_at_ns: int
    grant_token: str
    schema_version: str = "statebus.logit_state_grant.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "statebus.logit_state_grant.v1":
            raise ValueError(f"unsupported LogitState grant schema: {self.schema_version}")
        if self.consumer_component != "confidence_gate" or self.consumer_pid <= 0:
            raise ValueError("LogitState grant requires a confidence_gate consumer PID")
        if self.expires_at_ns <= 0 or not self.grant_token:
            raise ValueError("LogitState grant requires expiry and token")

    @classmethod
    def issue(
        cls,
        ref: LogitStateRefV2,
        *,
        consumer_pid: int,
        now_ns: int | None = None,
    ) -> "LogitStateGrant":
        contract = ref.contract
        issued_at_ns = time.time_ns() if now_ns is None else now_ns
        return cls(
            ref_id=ref.state_id,
            task_id=contract.task_id,
            session_id=contract.session_id,
            trace_id=contract.trace_id,
            step_id=contract.step_id,
            request_id=contract.request_id,
            attempt_id=contract.attempt_id,
            consumer_component=contract.consumer_component,
            consumer_pid=consumer_pid,
            candidate_surface_digest=contract.candidate_surface_digest,
            alias_mapping_digest=contract.alias_mapping_digest,
            calibration_version=contract.calibration_version,
            threshold_policy_version=contract.threshold_policy_version,
            gate_budget_version=contract.gate_budget_version,
            model_id=contract.model_id,
            tokenizer_id=contract.tokenizer_id,
            chat_template_sha256=contract.chat_template_sha256,
            template_kwargs_sha256=contract.template_kwargs_sha256,
            response_schema_digest=contract.response_schema_digest,
            expires_at_ns=min(contract.lease_expires_at_ns, issued_at_ns + 30_000_000_000),
            grant_token=secrets.token_hex(32),
        )

    @property
    def grant_hash(self) -> str:
        return sha256_digest(self.canonical_payload())

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ref_id": self.ref_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "step_id": self.step_id,
            "request_id": self.request_id,
            "attempt_id": self.attempt_id,
            "consumer_component": self.consumer_component,
            "consumer_pid": self.consumer_pid,
            "candidate_surface_digest": self.candidate_surface_digest,
            "alias_mapping_digest": self.alias_mapping_digest,
            "calibration_version": self.calibration_version,
            "threshold_policy_version": self.threshold_policy_version,
            "gate_budget_version": self.gate_budget_version,
            "model_id": self.model_id,
            "tokenizer_id": self.tokenizer_id,
            "chat_template_sha256": self.chat_template_sha256,
            "template_kwargs_sha256": self.template_kwargs_sha256,
            "response_schema_digest": self.response_schema_digest,
            "expires_at_ns": self.expires_at_ns,
            "grant_token": self.grant_token,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "LogitStateGrant":
        return cls(
            ref_id=str(payload.get("ref_id", "")),
            task_id=str(payload.get("task_id", "")),
            session_id=str(payload.get("session_id", "")),
            trace_id=str(payload.get("trace_id", "")),
            step_id=str(payload.get("step_id", "")),
            request_id=str(payload.get("request_id", "")),
            attempt_id=str(payload.get("attempt_id", "")),
            consumer_component=str(payload.get("consumer_component", "")),
            consumer_pid=int(payload.get("consumer_pid", 0)),
            candidate_surface_digest=str(payload.get("candidate_surface_digest", "")),
            alias_mapping_digest=str(payload.get("alias_mapping_digest", "")),
            calibration_version=str(payload.get("calibration_version", "")),
            threshold_policy_version=str(payload.get("threshold_policy_version", "")),
            gate_budget_version=str(payload.get("gate_budget_version", "")),
            model_id=str(payload.get("model_id", "")),
            tokenizer_id=str(payload.get("tokenizer_id", "")),
            chat_template_sha256=str(payload.get("chat_template_sha256", "")),
            template_kwargs_sha256=str(payload.get("template_kwargs_sha256", "")),
            response_schema_digest=str(payload.get("response_schema_digest", "")),
            expires_at_ns=int(payload.get("expires_at_ns", 0)),
            grant_token=str(payload.get("grant_token", "")),
            schema_version=str(payload.get("schema_version", "")),
        )


@dataclass(frozen=True)
class ResolvedLogitState:
    ref: LogitStateRefV2
    candidate_surface: CandidateSurfaceV2
    producer_receipt: LogitProducerReceipt
    values: tuple[float, ...]
    consumer_pid: int

    @property
    def candidate_probabilities(self) -> tuple[float, ...]:
        return self.values[:-1]

    @property
    def other_mass(self) -> float:
        return self.values[-1]

    @property
    def selected_candidate_ordinal(self) -> int:
        return self.candidate_surface.aliases.index(self.producer_receipt.selected_alias)

    @property
    def selected_candidate_probability(self) -> float:
        return self.candidate_probabilities[self.selected_candidate_ordinal]


class LogitStateStore:
    def __init__(
        self,
        root: Path,
        *,
        state_pool_mode: str = "auto",
        layered_store: LayeredStateStore | None = None,
    ) -> None:
        self.root = Path(root)
        self.layered_store = layered_store or LayeredStateStore(
            root=self.root,
            policy=LayeredStoragePolicy.for_state_pool_mode(state_pool_mode),
        )
        self.active_dir.mkdir(parents=True, exist_ok=True)
        self.tombstone_dir.mkdir(parents=True, exist_ok=True)
        self._publications: dict[str, LogitStatePublication] = {}

    @property
    def active_dir(self) -> Path:
        return self.root / "logit_active"

    @property
    def tombstone_dir(self) -> Path:
        return self.root / "logit_tombstones"

    def publish(
        self,
        *,
        extraction: "ExactChoiceLogitResult",
        candidate_surface: CandidateSurfaceV2,
        context: LogitStatePublishContext,
        state_id: str = "",
        now_ns: int | None = None,
    ) -> LogitStatePublication:
        if not extraction.available or not extraction.payload_bytes:
            raise LogitStateValidationError("logit_state_exact_producer_unavailable")
        receipt = extraction.receipt
        if receipt.candidate_surface_digest != candidate_surface.candidate_surface_digest:
            raise LogitStateValidationError("logit_state_candidate_surface_mismatch")
        if receipt.alias_mapping_digest != candidate_surface.alias_mapping_digest:
            raise LogitStateValidationError("logit_state_alias_mapping_mismatch")
        if receipt.request_id != context.request_id or receipt.attempt_id != context.attempt_id:
            raise LogitStateValidationError("logit_state_request_attempt_mismatch")
        if extraction.selected_candidate_id != candidate_surface.candidate_id_for_alias(
            extraction.selected_alias
        ):
            raise LogitStateValidationError("logit_state_selected_candidate_mismatch")
        created_at_ns = time.time_ns() if now_ns is None else now_ns
        ref_id = state_id or f"logit-{uuid4().hex}"
        if not ref_id or self._active_path(ref_id).exists() or self._tombstone_path(ref_id).exists():
            raise LogitStateValidationError("logit_state_id_not_unique")
        payload = extraction.payload_bytes
        try:
            handle = self.layered_store.publish(
                ref_id=ref_id,
                object_kind="LOGIT_STATE",
                payload=payload,
                contract_metadata={
                    "schema_version": "statebus.logit_state.v2",
                    "candidate_surface_digest": candidate_surface.candidate_surface_digest,
                    "request_id": context.request_id,
                    "attempt_id": context.attempt_id,
                },
            )
        except Exception as exc:
            raise LogitStateValidationError("logit_state_materialization_failed") from exc
        if handle.storage_kind not in {StorageKind.SHARED_MEMORY, StorageKind.MMAP_FILE}:
            self.layered_store.release(ref_id)
            handle.metadata_path.unlink(missing_ok=True)
            raise LogitStateValidationError("logit_state_storage_not_cross_process_resolvable")
        if handle.blob_hash != sha256_digest(payload) or handle.size_bytes != len(payload):
            self.layered_store.release(ref_id)
            handle.metadata_path.unlink(missing_ok=True)
            raise LogitStateValidationError("logit_state_materialization_mismatch")
        contract = LogitStateContractV2(
            state_id=ref_id,
            task_id=context.task_id,
            session_id=context.session_id,
            trace_id=context.trace_id,
            step_id=context.step_id,
            request_id=context.request_id,
            attempt_id=context.attempt_id,
            producer_role="executor",
            producer_component=context.producer_component,
            producer_pid=os.getpid(),
            logical_target="executor_choice",
            consumer_component="confidence_gate",
            expected_consumer_pid=context.expected_consumer_pid,
            decision_type=candidate_surface.decision_type,
            candidate_surface_digest=candidate_surface.candidate_surface_digest,
            candidate_count=candidate_surface.candidate_count,
            alias_mapping_digest=candidate_surface.alias_mapping_digest,
            decision_token_position=receipt.decision_token_position,
            sequence_length=receipt.sequence_length,
            top_k=receipt.top_k,
            prompt_sha256=context.prompt_sha256,
            source_evidence_digest=context.source_evidence_digest,
            hydration_digest=context.hydration_digest,
            model_id=context.model_id,
            model_revision=context.model_revision,
            tokenizer_id=context.tokenizer_id,
            tokenizer_revision=context.tokenizer_revision,
            chat_template_sha256=context.chat_template_sha256,
            template_kwargs_sha256=context.template_kwargs_sha256,
            response_schema_digest=context.response_schema_digest,
            blob_hash=handle.blob_hash,
            size_bytes=handle.size_bytes,
            storage_kind=handle.storage_kind.value,
            owner_session_id=context.owner_session_id,
            lease_created_at_ns=created_at_ns,
            lease_expires_at_ns=created_at_ns + context.lease_ttl_ms * 1_000_000,
            calibration_version=context.calibration_version,
            threshold_policy_version=context.threshold_policy_version,
            gate_budget_version=context.gate_budget_version,
            policy=context.policy,
            shape=(candidate_surface.candidate_count + 1,),
        )
        mmap_relpath = ""
        if handle.mmap_path is not None:
            try:
                mmap_relpath = handle.mmap_path.relative_to(self.root).as_posix()
            except ValueError as exc:
                self.layered_store.release(ref_id)
                handle.metadata_path.unlink(missing_ok=True)
                raise LogitStateValidationError("logit_state_mmap_path_outside_state_root") from exc
        ref = LogitStateRefV2(
            contract=contract,
            storage_kind=handle.storage_kind,
            shared_memory_name=handle.shared_memory_name,
            mmap_relpath=mmap_relpath,
        )
        publication = LogitStatePublication(
            ref=ref,
            handle=handle,
            candidate_surface=candidate_surface,
            producer_receipt=receipt,
            active_sidecar_path=self._active_path(ref_id),
            published_at_ns=created_at_ns,
        )
        active_payload = {
            "lifecycle_status": "active",
            "published_at_ns": created_at_ns,
            "ref": ref.canonical_payload(),
            "candidate_surface": candidate_surface.canonical_payload(),
            "producer_receipt": receipt.canonical_payload(),
        }
        try:
            _write_json_atomic(publication.active_sidecar_path, active_payload)
        except Exception:
            self.layered_store.release(ref_id)
            handle.metadata_path.unlink(missing_ok=True)
            raise
        self._publications[ref_id] = publication
        return publication

    def release(
        self,
        ref_id: str,
        *,
        reason: str,
        consumer_pid: int = 0,
        now_ns: int | None = None,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("LogitState release requires a reason")
        tombstone_path = self._tombstone_path(ref_id)
        existing = _read_json_optional(tombstone_path)
        if isinstance(existing, dict) and existing.get("lifecycle_status") == "released":
            return existing
        active = _read_active_sidecar(self.root, ref_id)
        ref = _ref_from_payload(_require_dict(active.get("ref"), "logit_state_ref_missing"))
        released_at_ns = time.time_ns() if now_ns is None else now_ns
        tombstone = {
            "schema_version": "statebus.logit_state_tombstone.v1",
            "lifecycle_status": "releasing",
            "state_id": ref_id,
            "task_id": ref.contract.task_id,
            "request_id": ref.contract.request_id,
            "attempt_id": ref.contract.attempt_id,
            "producer_pid": ref.contract.producer_pid,
            "consumer_pid": consumer_pid,
            "candidate_surface_digest": ref.contract.candidate_surface_digest,
            "contract_digest": sha256_digest(ref.contract.canonical_payload()),
            "release_reason": reason,
            "released_at_ns": released_at_ns,
        }
        _write_json_atomic(tombstone_path, tombstone)
        self._unlink_payload(ref)
        tombstone["lifecycle_status"] = "released"
        _write_json_atomic(tombstone_path, tombstone)
        self._active_path(ref_id).unlink(missing_ok=True)
        (self.root / "metadata" / f"{ref_id}.json").unlink(missing_ok=True)
        self._publications.pop(ref_id, None)
        return tombstone

    def release_expired(self, *, now_ns: int | None = None) -> tuple[str, ...]:
        effective_now = time.time_ns() if now_ns is None else now_ns
        released: list[str] = []
        for path in sorted(self.active_dir.glob("*.json")):
            try:
                sidecar = json.loads(path.read_text(encoding="utf-8"))
                ref = _ref_from_payload(_require_dict(sidecar.get("ref"), "logit_state_ref_missing"))
            except (OSError, json.JSONDecodeError, ValueError, KeyError):
                continue
            if ref.contract.lease_expires_at_ns <= effective_now:
                self.release(ref.state_id, reason="expired", now_ns=effective_now)
                released.append(ref.state_id)
        return tuple(released)

    def teardown(self) -> None:
        for ref_id in tuple(self._publications):
            self.release(ref_id, reason="cancelled")
        self.layered_store.teardown()

    def _unlink_payload(self, ref: LogitStateRefV2) -> None:
        if ref.state_id in self.layered_store.materializations:
            self.layered_store.release(ref.state_id)
            return
        if ref.storage_kind is StorageKind.SHARED_MEMORY:
            try:
                shared = SharedMemory(name=ref.shared_memory_name)
            except FileNotFoundError:
                return
            try:
                shared.close()
            finally:
                try:
                    shared.unlink()
                except FileNotFoundError:
                    pass
            return
        path = _safe_mmap_path(self.root, ref.mmap_relpath)
        path.unlink(missing_ok=True)

    def _active_path(self, ref_id: str) -> Path:
        return self.active_dir / f"{ref_id}.json"

    def _tombstone_path(self, ref_id: str) -> Path:
        return self.tombstone_dir / f"{ref_id}.json"


def logit_ref_from_sidecar(state_root: Path, ref_id: str) -> LogitStateRefV2:
    sidecar = _read_active_sidecar(Path(state_root), ref_id)
    return _ref_from_payload(_require_dict(sidecar.get("ref"), "logit_state_ref_missing"))


def resolve_logit_state(
    *,
    state_root: Path,
    ref: LogitStateRefV2,
    grant: LogitStateGrant,
    now_ns: int | None = None,
    unregister_shared_memory_tracker: bool = False,
) -> ResolvedLogitState:
    root = Path(state_root)
    if grant.consumer_pid != os.getpid():
        raise LogitStateValidationError("logit_state_grant_not_bound_to_current_pid")
    if (root / "logit_tombstones" / f"{ref.state_id}.json").exists():
        raise LogitStateValidationError("logit_state_terminal")
    sidecar = _read_active_sidecar(root, ref.state_id)
    sidecar_ref = _ref_from_payload(_require_dict(sidecar.get("ref"), "logit_state_ref_missing"))
    if sidecar_ref.canonical_payload() != ref.canonical_payload():
        raise LogitStateValidationError("logit_state_ref_sidecar_mismatch")
    surface = _surface_from_payload(
        _require_dict(sidecar.get("candidate_surface"), "logit_state_candidate_surface_missing")
    )
    receipt = _receipt_from_payload(
        _require_dict(sidecar.get("producer_receipt"), "logit_state_producer_receipt_missing")
    )
    effective_now = time.time_ns() if now_ns is None else now_ns
    _validate_grant(ref, surface, receipt, grant, effective_now)

    payload: bytes
    if ref.storage_kind is StorageKind.SHARED_MEMORY:
        try:
            shared = SharedMemory(name=ref.shared_memory_name)
        except FileNotFoundError as exc:
            raise LogitStateValidationError("logit_state_payload_missing") from exc
        try:
            if unregister_shared_memory_tracker:
                from multiprocessing import resource_tracker

                resource_tracker.unregister(shared._name, "shared_memory")
            payload = bytes(shared.buf[: ref.length])
        finally:
            shared.close()
    elif ref.storage_kind is StorageKind.MMAP_FILE:
        path = _safe_mmap_path(root, ref.mmap_relpath)
        try:
            with path.open("rb") as payload_file:
                with mmap(payload_file.fileno(), 0, access=ACCESS_READ) as mapped:
                    payload = mapped[: ref.length]
        except FileNotFoundError as exc:
            raise LogitStateValidationError("logit_state_payload_missing") from exc
    else:
        raise LogitStateValidationError("logit_state_storage_not_cross_process_resolvable")
    if len(payload) != ref.length or sha256_digest(payload) != ref.blob_hash:
        raise LogitStateValidationError("logit_state_blob_hash_mismatch")
    try:
        values = tuple(struct.unpack(f"<{ref.contract.candidate_count + 1}f", payload))
    except struct.error as exc:
        raise LogitStateValidationError("logit_state_shape_or_dtype_mismatch") from exc
    if not all(math.isfinite(value) and value >= 0.0 for value in values):
        raise LogitStateValidationError("logit_state_probability_invalid")
    if not math.isclose(sum(values), 1.0, abs_tol=1e-5):
        raise LogitStateValidationError("logit_state_probability_sum_invalid")
    return ResolvedLogitState(
        ref=ref,
        candidate_surface=surface,
        producer_receipt=receipt,
        values=values,
        consumer_pid=grant.consumer_pid,
    )


def _validate_grant(
    ref: LogitStateRefV2,
    surface: CandidateSurfaceV2,
    receipt: LogitProducerReceipt,
    grant: LogitStateGrant,
    now_ns: int,
) -> None:
    contract = ref.contract
    if now_ns >= contract.lease_expires_at_ns:
        raise LogitStateValidationError("logit_state_lease_expired")
    if now_ns >= grant.expires_at_ns:
        raise LogitStateValidationError("logit_state_grant_expired")
    if grant.consumer_pid == contract.producer_pid:
        raise LogitStateValidationError("logit_state_consumer_pid_not_independent")
    if contract.expected_consumer_pid not in {0, grant.consumer_pid}:
        raise LogitStateValidationError("logit_state_consumer_pid_mismatch")
    bindings = {
        "ref_id": contract.state_id,
        "task_id": contract.task_id,
        "session_id": contract.session_id,
        "trace_id": contract.trace_id,
        "step_id": contract.step_id,
        "request_id": contract.request_id,
        "attempt_id": contract.attempt_id,
        "consumer_component": contract.consumer_component,
        "candidate_surface_digest": contract.candidate_surface_digest,
        "alias_mapping_digest": contract.alias_mapping_digest,
        "calibration_version": contract.calibration_version,
        "threshold_policy_version": contract.threshold_policy_version,
        "gate_budget_version": contract.gate_budget_version,
        "model_id": contract.model_id,
        "tokenizer_id": contract.tokenizer_id,
        "chat_template_sha256": contract.chat_template_sha256,
        "template_kwargs_sha256": contract.template_kwargs_sha256,
        "response_schema_digest": contract.response_schema_digest,
    }
    for field_name, expected in bindings.items():
        if getattr(grant, field_name) != expected:
            raise LogitStateValidationError(f"logit_state_grant_binding_mismatch:{field_name}")
    if surface.candidate_surface_digest != contract.candidate_surface_digest:
        raise LogitStateValidationError("logit_state_candidate_surface_digest_mismatch")
    if surface.alias_mapping_digest != contract.alias_mapping_digest:
        raise LogitStateValidationError("logit_state_alias_mapping_digest_mismatch")
    if receipt.status is not LogitProducerStatus.AVAILABLE:
        raise LogitStateValidationError("logit_state_producer_unavailable")
    if receipt.request_id != contract.request_id or receipt.attempt_id != contract.attempt_id:
        raise LogitStateValidationError("logit_state_producer_binding_mismatch")
    if receipt.candidate_surface_digest != contract.candidate_surface_digest:
        raise LogitStateValidationError("logit_state_producer_surface_mismatch")
    if receipt.alias_mapping_digest != contract.alias_mapping_digest:
        raise LogitStateValidationError("logit_state_producer_alias_mapping_mismatch")
    if receipt.decision_token_position != contract.decision_token_position:
        raise LogitStateValidationError("logit_state_decision_position_mismatch")


def _read_active_sidecar(root: Path, ref_id: str) -> dict[str, Any]:
    path = root / "logit_active" / f"{ref_id}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LogitStateValidationError("logit_state_active_sidecar_missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise LogitStateValidationError("logit_state_active_sidecar_corrupt") from exc
    if not isinstance(payload, dict) or payload.get("lifecycle_status") != "active":
        raise LogitStateValidationError("logit_state_not_active")
    return payload


def _read_json_optional(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise LogitStateValidationError("logit_state_tombstone_corrupt") from exc
    return payload if isinstance(payload, dict) else None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        temporary.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_mmap_path(root: Path, relpath: str) -> Path:
    if not relpath or Path(relpath).is_absolute() or ".." in Path(relpath).parts:
        raise LogitStateValidationError("logit_state_mmap_path_invalid")
    allowed_root = (root / "mmap").resolve()
    candidate = (root / relpath).resolve(strict=False)
    if candidate.parent != allowed_root:
        raise LogitStateValidationError("logit_state_mmap_path_outside_state_root")
    return candidate


def _require_dict(value: object, reason: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LogitStateValidationError(reason)
    return value


def _contract_from_payload(payload: dict[str, Any]) -> LogitStateContractV2:
    shape = payload.get("shape", ())
    if not isinstance(shape, (list, tuple)):
        raise LogitStateValidationError("logit_state_shape_invalid")
    try:
        policy = LogitPolicy(str(payload.get("policy", "")))
        return LogitStateContractV2(
            state_id=str(payload.get("state_id", "")),
            task_id=str(payload.get("task_id", "")),
            session_id=str(payload.get("session_id", "")),
            trace_id=str(payload.get("trace_id", "")),
            step_id=str(payload.get("step_id", "")),
            request_id=str(payload.get("request_id", "")),
            attempt_id=str(payload.get("attempt_id", "")),
            producer_role=str(payload.get("producer_role", "")),
            producer_component=str(payload.get("producer_component", "")),
            producer_pid=int(payload.get("producer_pid", 0)),
            logical_target=str(payload.get("logical_target", "")),
            consumer_component=str(payload.get("consumer_component", "")),
            expected_consumer_pid=int(payload.get("expected_consumer_pid", 0)),
            decision_type=str(payload.get("decision_type", "")),
            candidate_surface_digest=str(payload.get("candidate_surface_digest", "")),
            candidate_count=int(payload.get("candidate_count", 0)),
            alias_mapping_digest=str(payload.get("alias_mapping_digest", "")),
            decision_token_position=int(payload.get("decision_token_position", -1)),
            sequence_length=int(payload.get("sequence_length", 0)),
            top_k=int(payload.get("top_k", 0)),
            prompt_sha256=str(payload.get("prompt_sha256", "")),
            source_evidence_digest=str(payload.get("source_evidence_digest", "")),
            hydration_digest=str(payload.get("hydration_digest", "")),
            model_id=str(payload.get("model_id", "")),
            model_revision=str(payload.get("model_revision", "")),
            tokenizer_id=str(payload.get("tokenizer_id", "")),
            tokenizer_revision=str(payload.get("tokenizer_revision", "")),
            chat_template_sha256=str(payload.get("chat_template_sha256", "")),
            template_kwargs_sha256=str(payload.get("template_kwargs_sha256", "")),
            response_schema_digest=str(payload.get("response_schema_digest", "")),
            blob_hash=str(payload.get("blob_hash", "")),
            size_bytes=int(payload.get("size_bytes", 0)),
            storage_kind=str(payload.get("storage_kind", "")),
            owner_session_id=str(payload.get("owner_session_id", "")),
            lease_created_at_ns=int(payload.get("lease_created_at_ns", 0)),
            lease_expires_at_ns=int(payload.get("lease_expires_at_ns", 0)),
            calibration_version=str(payload.get("calibration_version", "")),
            threshold_policy_version=str(payload.get("threshold_policy_version", "")),
            gate_budget_version=str(payload.get("gate_budget_version", "")),
            policy=policy,
            dtype=str(payload.get("dtype", "")),
            byte_order=str(payload.get("byte_order", "")),
            shape=tuple(int(value) for value in shape),
            probability_semantics=str(payload.get("probability_semantics", "")),
            sensitivity_class=str(payload.get("sensitivity_class", "")),
            schema_version=str(payload.get("schema_version", "")),
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, LogitStateValidationError):
            raise
        raise LogitStateValidationError(str(exc) or "logit_state_contract_invalid") from exc


def _ref_from_payload(payload: dict[str, Any]) -> LogitStateRefV2:
    try:
        return LogitStateRefV2(
            contract=_contract_from_payload(
                _require_dict(payload.get("contract"), "logit_state_contract_missing")
            ),
            storage_kind=StorageKind(str(payload.get("storage_kind", ""))),
            shared_memory_name=str(payload.get("shared_memory_name", "")),
            mmap_relpath=str(payload.get("mmap_relpath", "")),
            status=RefStatus(str(payload.get("status", ""))),
            schema_version=str(payload.get("schema_version", "")),
        )
    except (TypeError, ValueError) as exc:
        raise LogitStateValidationError(str(exc) or "logit_state_ref_invalid") from exc


def _surface_from_payload(payload: dict[str, Any]) -> CandidateSurfaceV2:
    raw_bindings = payload.get("bindings", ())
    if not isinstance(raw_bindings, list):
        raise LogitStateValidationError("logit_state_candidate_bindings_invalid")
    try:
        surface = CandidateSurfaceV2(
            bindings=tuple(
                CandidateAliasBinding(
                    ordinal=int(binding.get("ordinal", -1)),
                    alias=str(binding.get("alias", "")),
                    candidate_id=str(binding.get("candidate_id", "")),
                    candidate_digest=str(binding.get("candidate_digest", "")),
                    token_bytes_hex=str(binding.get("token_bytes_hex", "")),
                    token_id=int(binding.get("token_id", -1)),
                )
                for binding in raw_bindings
                if isinstance(binding, dict)
            ),
            decision_type=str(payload.get("decision_type", "")),
            schema_version=str(payload.get("schema_version", "")),
        )
    except (TypeError, ValueError) as exc:
        raise LogitStateValidationError(str(exc) or "logit_state_candidate_surface_invalid") from exc
    if payload.get("alias_mapping_digest") != surface.alias_mapping_digest:
        raise LogitStateValidationError("logit_state_alias_mapping_sidecar_mismatch")
    return surface


def _receipt_from_payload(payload: dict[str, Any]) -> LogitProducerReceipt:
    try:
        return LogitProducerReceipt(
            request_id=str(payload.get("request_id", "")),
            attempt_id=str(payload.get("attempt_id", "")),
            status=LogitProducerStatus(str(payload.get("status", ""))),
            candidate_surface_digest=str(payload.get("candidate_surface_digest", "")),
            alias_mapping_digest=str(payload.get("alias_mapping_digest", "")),
            selected_alias=str(payload.get("selected_alias", "")),
            selected_candidate_id=str(payload.get("selected_candidate_id", "")),
            decision_token_position=int(payload.get("decision_token_position", -1)),
            sequence_length=int(payload.get("sequence_length", 0)),
            top_k=int(payload.get("top_k", 0)),
            unavailable_reason=str(payload.get("unavailable_reason", "")),
            schema_version=str(payload.get("schema_version", "")),
        )
    except (TypeError, ValueError) as exc:
        raise LogitStateValidationError(str(exc) or "logit_state_producer_receipt_invalid") from exc
