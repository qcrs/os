from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
import time
from typing import Any, Callable
from uuid import uuid4

from v2.contracts import (
    LatentAnchor,
    LatentForwardProof,
    LatentLifecycleEvent,
    LatentLifecycleState,
    LatentProofKind,
    NeuralCompatibilitySignature,
)
from v2.refs import LatentStateRef


class LatentRegistryError(RuntimeError):
    def __init__(self, error_code: str, detail: str = "") -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class LatentRegistryConfig:
    max_bytes: int = 67_108_864
    max_entries: int = 64
    default_ttl_s: int = 60
    max_steps: int = 80
    max_hidden_size: int = 8192
    one_shot: bool = True

    @classmethod
    def from_env(cls) -> "LatentRegistryConfig":
        return cls(
            max_bytes=int(os.environ.get("STATEBUS_LATENT_REGISTRY_MAX_BYTES", "67108864")),
            max_entries=int(os.environ.get("STATEBUS_LATENT_REGISTRY_MAX_ENTRIES", "64")),
            default_ttl_s=int(os.environ.get("STATEBUS_LATENT_TTL_S", "60")),
            max_steps=int(os.environ.get("STATEBUS_LATENT_MAX_STEPS", "80")),
            max_hidden_size=int(
                os.environ.get("STATEBUS_LATENT_MAX_HIDDEN_SIZE", "8192")
            ),
            one_shot=os.environ.get("STATEBUS_LATENT_ONE_SHOT", "true").lower()
            in {"1", "true", "yes", "on"},
        )


@dataclass(frozen=True)
class LatentRegistryMetadata:
    producer_role: str
    consumer_role: str
    source_task_id: str
    source_step_id: str
    anchor: LatentAnchor
    compatibility_signature: NeuralCompatibilitySignature
    source_layer_index: int
    engine_id: str
    producer_pid: int


@dataclass
class _ConsumeTransaction:
    request_id: str
    prompt_embed_digest: str
    prompt_embed_shape: tuple[int, ...]
    prompt_embed_dtype: str


@dataclass
class _RegistryEntry:
    ref_id: str
    metadata: LatentRegistryMetadata
    latent_step_count: int
    ttl_s: int
    created_at_ns: int
    expires_at_ns: int
    state: LatentLifecycleState = LatentLifecycleState.PREPARED
    tensor: Any | None = None
    tensor_bytes: int = 0
    tensor_digest: str = ""
    captured_step_count: int = 0
    recurrence_injection_count: int = 0
    lease_request_id: str = ""
    consume_transaction: _ConsumeTransaction | None = None
    forward_proof: LatentForwardProof | None = None
    rejection_reason: str = ""
    last_access_ns: int = 0


class LatentTensorRegistry:
    """Worker-owned, bounded registry. Tensor values never enter public payloads."""

    def __init__(
        self,
        config: LatentRegistryConfig | None = None,
        *,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.config = config or LatentRegistryConfig.from_env()
        self.clock_ns = clock_ns
        self._entries: dict[str, _RegistryEntry] = {}
        self._events: list[LatentLifecycleEvent] = []

    def prepare(
        self,
        *,
        metadata: LatentRegistryMetadata,
        latent_step_count: int,
        ttl_s: int | None = None,
        ref_id: str = "",
    ) -> str:
        if not 2 <= latent_step_count <= self.config.max_steps:
            raise LatentRegistryError("latent_request_invalid", "latent_step_count")
        if not 1 <= metadata.compatibility_signature.hidden_size <= self.config.max_hidden_size:
            raise LatentRegistryError("latent_model_incompatible", "hidden_size")
        if metadata.compatibility_signature.alignment_method != "soft_token_topk_v1":
            raise LatentRegistryError("latent_alignment_incompatible")
        now = self.clock_ns()
        ttl = self.config.default_ttl_s if ttl_s is None else int(ttl_s)
        if ttl <= 0:
            raise LatentRegistryError("latent_request_invalid", "ttl_s")
        resolved_ref_id = ref_id or f"latent-{uuid4().hex}"
        if resolved_ref_id in self._entries:
            raise LatentRegistryError("latent_request_invalid", "duplicate_ref_id")
        entry = _RegistryEntry(
            ref_id=resolved_ref_id,
            metadata=metadata,
            latent_step_count=latent_step_count,
            ttl_s=ttl,
            created_at_ns=now,
            expires_at_ns=now + ttl * 1_000_000_000,
            last_access_ns=now,
        )
        self._entries[resolved_ref_id] = entry
        self._emit(entry, "LATENT_PREPARED", None, LatentLifecycleState.PREPARED)
        return resolved_ref_id

    def commit(
        self,
        ref_id: str,
        tensor: Any,
        *,
        captured_step_count: int,
        recurrence_injection_count: int,
    ) -> LatentStateRef:
        entry = self._entry(ref_id)
        self._require_state(entry, LatentLifecycleState.PREPARED)
        if (
            captured_step_count != entry.latent_step_count
            or recurrence_injection_count != entry.latent_step_count - 1
        ):
            self.reject(ref_id, "latent_capture_incomplete")
            raise LatentRegistryError("latent_capture_incomplete")
        normalized = _cpu_bf16_contiguous(tensor)
        expected_shape = (
            entry.latent_step_count,
            entry.metadata.compatibility_signature.hidden_size,
        )
        if tuple(int(value) for value in normalized.shape) != expected_shape:
            self.reject(ref_id, "latent_capture_incomplete")
            raise LatentRegistryError("latent_capture_incomplete", "shape")
        tensor_bytes = _tensor_nbytes(normalized)
        expected_bytes = expected_shape[0] * expected_shape[1] * 2
        if tensor_bytes != expected_bytes:
            self.reject(ref_id, "latent_capture_incomplete")
            raise LatentRegistryError("latent_capture_incomplete", "byte_count")
        self.sweep_expired()
        self._make_capacity(tensor_bytes, exclude_ref_id=ref_id)
        before = entry.state
        entry.tensor = normalized
        entry.tensor_bytes = tensor_bytes
        entry.tensor_digest = _tensor_digest(normalized)
        entry.captured_step_count = captured_step_count
        entry.recurrence_injection_count = recurrence_injection_count
        entry.state = LatentLifecycleState.COMMITTED
        entry.last_access_ns = self.clock_ns()
        self._emit(entry, "LATENT_COMMITTED", before, entry.state)
        return self.describe(ref_id)

    def lease(
        self,
        ref_id: str,
        *,
        request_id: str,
        expected_compatibility_digest: str,
        expected_anchor_digest: str,
    ) -> LatentStateRef:
        entry = self._live_entry(ref_id)
        if entry.state == LatentLifecycleState.CONSUMED:
            raise LatentRegistryError("latent_ref_already_consumed")
        self._require_state(entry, LatentLifecycleState.COMMITTED)
        if (
            expected_compatibility_digest
            != entry.metadata.compatibility_signature.compatibility_digest
        ):
            raise LatentRegistryError("latent_model_incompatible")
        if expected_anchor_digest != entry.metadata.anchor.anchor_digest:
            raise LatentRegistryError("latent_anchor_mismatch")
        before = entry.state
        entry.state = LatentLifecycleState.LEASED
        entry.lease_request_id = request_id
        entry.last_access_ns = self.clock_ns()
        self._emit(entry, "LATENT_LEASED", before, entry.state, request_id=request_id)
        return self.describe(ref_id)

    def materialize_tensor(self, ref_id: str) -> Any:
        entry = self._live_entry(ref_id)
        if entry.state not in {
            LatentLifecycleState.LEASED,
            LatentLifecycleState.CONSUMING,
        }:
            raise LatentRegistryError("latent_request_invalid", "ref_not_leased")
        if entry.tensor is None:
            raise LatentRegistryError("latent_ref_not_found", "tensor_released")
        entry.last_access_ns = self.clock_ns()
        return entry.tensor.clone()

    def begin_consume(
        self,
        ref_id: str,
        *,
        request_id: str,
        prompt_embed_digest: str,
        prompt_embed_shape: tuple[int, ...],
        prompt_embed_dtype: str,
    ) -> LatentStateRef:
        entry = self._live_entry(ref_id)
        self._require_state(entry, LatentLifecycleState.LEASED)
        if not request_id or not prompt_embed_digest or len(prompt_embed_shape) != 2:
            raise LatentRegistryError("latent_request_invalid", "consume_binding")
        before = entry.state
        entry.consume_transaction = _ConsumeTransaction(
            request_id=request_id,
            prompt_embed_digest=prompt_embed_digest,
            prompt_embed_shape=tuple(int(value) for value in prompt_embed_shape),
            prompt_embed_dtype=prompt_embed_dtype,
        )
        entry.state = LatentLifecycleState.CONSUMING
        entry.last_access_ns = self.clock_ns()
        self._emit(entry, "LATENT_CONSUME_BEGAN", before, entry.state, request_id=request_id)
        return self.describe(ref_id)

    def finish_consume(self, proof: LatentForwardProof) -> LatentStateRef:
        entry = self._live_entry(proof.ref_id)
        self._require_state(entry, LatentLifecycleState.CONSUMING)
        transaction = entry.consume_transaction
        if transaction is None:
            raise LatentRegistryError("latent_consumer_forward_not_observed")
        if proof.proof_kind != LatentProofKind.WORKER_FORWARD:
            raise LatentRegistryError("latent_consumer_forward_not_observed")
        if (
            proof.request_id != transaction.request_id
            or proof.inputs_embeds_digest != transaction.prompt_embed_digest
            or proof.inputs_embeds_shape != transaction.prompt_embed_shape
            or proof.inputs_embeds_dtype != transaction.prompt_embed_dtype
        ):
            raise LatentRegistryError("latent_consumer_forward_not_observed", "binding_mismatch")
        before = entry.state
        entry.forward_proof = proof
        entry.state = LatentLifecycleState.CONSUMED
        entry.last_access_ns = self.clock_ns()
        self._emit(
            entry,
            "LATENT_CONSUMED",
            before,
            entry.state,
            request_id=proof.request_id,
            attributes={"forward_proof_hash": proof.proof_hash},
        )
        return self.describe(proof.ref_id)

    def abort_consume(self, ref_id: str, reason: str) -> LatentStateRef:
        entry = self._entry(ref_id)
        if entry.state in {
            LatentLifecycleState.RELEASED,
            LatentLifecycleState.EXPIRED,
            LatentLifecycleState.INVALIDATED,
        }:
            return self.describe(ref_id, check_expiry=False)
        before = entry.state
        entry.state = LatentLifecycleState.INVALIDATED
        entry.rejection_reason = reason
        entry.tensor = None
        entry.consume_transaction = None
        self._emit(entry, "LATENT_CONSUME_ABORTED", before, entry.state, reason=reason)
        return self.describe(ref_id, check_expiry=False)

    def reject(self, ref_id: str, reason: str) -> None:
        entry = self._entry(ref_id)
        before = entry.state
        entry.state = LatentLifecycleState.REJECTED
        entry.rejection_reason = reason
        entry.tensor = None
        entry.consume_transaction = None
        self._emit(entry, "LATENT_REJECTED", before, entry.state, reason=reason)

    def release(self, ref_id: str) -> LatentStateRef:
        entry = self._entry(ref_id)
        if entry.state == LatentLifecycleState.EXPIRED:
            raise LatentRegistryError("latent_ref_expired")
        if entry.state == LatentLifecycleState.RELEASED:
            return self.describe(ref_id, check_expiry=False)
        before = entry.state
        entry.state = LatentLifecycleState.RELEASED
        entry.tensor = None
        entry.consume_transaction = None
        entry.last_access_ns = self.clock_ns()
        self._emit(entry, "LATENT_RELEASED", before, entry.state)
        return self.describe(ref_id, check_expiry=False)

    def sweep_expired(self) -> int:
        now = self.clock_ns()
        expired = 0
        for entry in self._entries.values():
            if (
                entry.state
                not in {
                    LatentLifecycleState.RELEASED,
                    LatentLifecycleState.EXPIRED,
                    LatentLifecycleState.REJECTED,
                    LatentLifecycleState.INVALIDATED,
                }
                and now >= entry.expires_at_ns
            ):
                before = entry.state
                entry.state = LatentLifecycleState.EXPIRED
                entry.tensor = None
                entry.consume_transaction = None
                self._emit(entry, "LATENT_EXPIRED", before, entry.state)
                expired += 1
        return expired

    def describe(self, ref_id: str, *, check_expiry: bool = True) -> LatentStateRef:
        entry = self._live_entry(ref_id) if check_expiry else self._entry(ref_id)
        if not entry.tensor_digest:
            raise LatentRegistryError("latent_capture_incomplete")
        signature = entry.metadata.compatibility_signature
        return LatentStateRef(
            ref_id=entry.ref_id,
            status=entry.state,
            backend_handle=f"engine-local:{entry.ref_id}",
            producer_role=entry.metadata.producer_role,
            consumer_role=entry.metadata.consumer_role,
            source_task_id=entry.metadata.source_task_id,
            source_step_id=entry.metadata.source_step_id,
            source_evidence_pack_hash=entry.metadata.anchor.evidence_pack_hash,
            anchor_item_ids=entry.metadata.anchor.item_ids,
            anchor_locator_digest=entry.metadata.anchor.locator_digest,
            model_id=signature.model_id,
            model_revision=signature.model_revision_or_manifest_digest,
            tokenizer_revision=signature.tokenizer_revision,
            chat_template_digest=signature.chat_template_digest,
            hidden_size=signature.hidden_size,
            source_layer_index=entry.metadata.source_layer_index,
            latent_step_count=entry.latent_step_count,
            alignment_method=signature.alignment_method,
            alignment_config_digest=signature.alignment_config_digest,
            position_contract_digest=signature.position_contract_digest,
            dtype="bfloat16",
            shape=(entry.latent_step_count, signature.hidden_size),
            tensor_bytes=entry.tensor_bytes,
            tensor_digest=entry.tensor_digest,
            producer_pid=entry.metadata.producer_pid,
            engine_id=entry.metadata.engine_id,
            created_at_ns=entry.created_at_ns,
            expires_at_ns=entry.expires_at_ns,
            compatibility_digest=signature.compatibility_digest,
            metadata={
                "captured_step_count": entry.captured_step_count,
                "recurrence_injection_count": entry.recurrence_injection_count,
                "forward_proof_hash": (
                    "" if entry.forward_proof is None else entry.forward_proof.proof_hash
                ),
                "rejection_reason": entry.rejection_reason,
            },
        )

    def forward_proof(self, ref_id: str) -> LatentForwardProof | None:
        return self._entry(ref_id).forward_proof

    def events(self) -> tuple[LatentLifecycleEvent, ...]:
        return tuple(self._events)

    def stats(self) -> dict[str, int]:
        live = [entry for entry in self._entries.values() if entry.tensor is not None]
        return {
            "registry_entries": len(live),
            "registry_bytes": sum(entry.tensor_bytes for entry in live),
            "registry_peak_entries": max(
                (int(event.attributes.get("registry_entries", 0)) for event in self._events),
                default=0,
            ),
            "registry_peak_bytes": max(
                (int(event.attributes.get("registry_bytes", 0)) for event in self._events),
                default=0,
            ),
        }

    def _make_capacity(self, required_bytes: int, *, exclude_ref_id: str) -> None:
        if required_bytes > self.config.max_bytes:
            raise LatentRegistryError("latent_registry_capacity_exceeded")
        while True:
            live = [
                entry
                for entry in self._entries.values()
                if entry.tensor is not None and entry.ref_id != exclude_ref_id
            ]
            live_bytes = sum(entry.tensor_bytes for entry in live)
            if (
                len(live) + 1 <= self.config.max_entries
                and live_bytes + required_bytes <= self.config.max_bytes
            ):
                return
            evictable = sorted(
                (
                    entry
                    for entry in live
                    if entry.state == LatentLifecycleState.COMMITTED
                ),
                key=lambda entry: (entry.last_access_ns, entry.created_at_ns, entry.ref_id),
            )
            if not evictable:
                raise LatentRegistryError("latent_registry_capacity_exceeded")
            victim = evictable[0]
            before = victim.state
            victim.state = LatentLifecycleState.INVALIDATED
            victim.rejection_reason = "capacity_evicted"
            victim.tensor = None
            self._emit(
                victim,
                "LATENT_CAPACITY_EVICTED",
                before,
                victim.state,
                reason="capacity_evicted",
            )

    def _live_entry(self, ref_id: str) -> _RegistryEntry:
        entry = self._entry(ref_id)
        if (
            entry.state
            not in {
                LatentLifecycleState.RELEASED,
                LatentLifecycleState.EXPIRED,
                LatentLifecycleState.REJECTED,
                LatentLifecycleState.INVALIDATED,
            }
            and self.clock_ns() >= entry.expires_at_ns
        ):
            before = entry.state
            entry.state = LatentLifecycleState.EXPIRED
            entry.tensor = None
            entry.consume_transaction = None
            self._emit(entry, "LATENT_EXPIRED", before, entry.state)
        if entry.state == LatentLifecycleState.EXPIRED:
            raise LatentRegistryError("latent_ref_expired")
        if entry.state in {
            LatentLifecycleState.REJECTED,
            LatentLifecycleState.INVALIDATED,
            LatentLifecycleState.RELEASED,
        }:
            raise LatentRegistryError("latent_ref_not_found")
        return entry

    def _entry(self, ref_id: str) -> _RegistryEntry:
        try:
            return self._entries[ref_id]
        except KeyError as exc:
            raise LatentRegistryError("latent_ref_not_found") from exc

    @staticmethod
    def _require_state(entry: _RegistryEntry, expected: LatentLifecycleState) -> None:
        if entry.state == LatentLifecycleState.CONSUMED:
            raise LatentRegistryError("latent_ref_already_consumed")
        if entry.state != expected:
            raise LatentRegistryError(
                "latent_request_invalid",
                f"expected_{expected.value}_got_{entry.state.value}",
            )

    def _emit(
        self,
        entry: _RegistryEntry,
        event_type: str,
        before: LatentLifecycleState | None,
        after: LatentLifecycleState,
        *,
        request_id: str = "",
        reason: str = "",
        attributes: dict[str, Any] | None = None,
    ) -> None:
        live = [candidate for candidate in self._entries.values() if candidate.tensor is not None]
        payload = {
            "registry_entries": len(live),
            "registry_bytes": sum(candidate.tensor_bytes for candidate in live),
            **dict(attributes or {}),
        }
        self._events.append(LatentLifecycleEvent(
            event_id=f"latent-event-{uuid4().hex}",
            ref_id=entry.ref_id,
            event_type=event_type,
            state_before=before,
            state_after=after,
            occurred_at_ns=self.clock_ns(),
            request_id=request_id,
            reason=reason,
            attributes=payload,
        ))


def _torch_module():
    import torch

    return torch


def _cpu_bf16_contiguous(tensor: Any) -> Any:
    torch = _torch_module()
    if not torch.is_tensor(tensor):
        raise LatentRegistryError("latent_request_invalid", "tensor_required")
    if tensor.ndim != 2:
        raise LatentRegistryError("latent_capture_incomplete", "rank")
    return tensor.detach().to(device="cpu", dtype=torch.bfloat16).contiguous().clone()


def _tensor_raw_bytes(tensor: Any) -> bytes:
    torch = _torch_module()
    return tensor.contiguous().view(torch.uint8).numpy().tobytes()


def _tensor_nbytes(tensor: Any) -> int:
    return len(_tensor_raw_bytes(tensor))


def _tensor_digest(tensor: Any) -> str:
    return hashlib.sha256(_tensor_raw_bytes(tensor)).hexdigest()
