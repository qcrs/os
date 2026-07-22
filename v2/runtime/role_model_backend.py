from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Protocol, runtime_checkable
from uuid import uuid4

from v2.contracts import (
    LatentAnchor,
    LatentForwardProof,
    LatentLifecycleState,
    LatentProofKind,
    NeuralCompatibilitySignature,
)
from v2.refs import LatentStateRef
from v2.utils import sha256_digest


class LatentBackendError(RuntimeError):
    def __init__(self, error_code: str, detail: str = "") -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class LatentBackendHealth:
    status: str
    plugin_version: str
    compatibility_signature: NeuralCompatibilitySignature
    worker_extension_ready: bool
    prompt_embeds_enabled: bool
    max_num_seqs: int
    registry_entries: int = 0
    registry_bytes: int = 0
    registry_max_entries: int = 0
    registry_max_bytes: int = 0
    registry_max_steps: int = 0
    backend_kind: str = "vllm_native"
    errors: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return (
            self.status == "ready"
            and self.worker_extension_ready
            and self.prompt_embeds_enabled
            and self.max_num_seqs == 1
            and not self.errors
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "plugin_version": self.plugin_version,
            "compatibility_signature": self.compatibility_signature.canonical_payload(),
            "compatibility_digest": self.compatibility_signature.compatibility_digest,
            "worker_extension_ready": self.worker_extension_ready,
            "prompt_embeds_enabled": self.prompt_embeds_enabled,
            "max_num_seqs": self.max_num_seqs,
            "registry_entries": self.registry_entries,
            "registry_bytes": self.registry_bytes,
            "registry_max_entries": self.registry_max_entries,
            "registry_max_bytes": self.registry_max_bytes,
            "registry_max_steps": self.registry_max_steps,
            "backend_kind": self.backend_kind,
            "errors": list(self.errors),
        }

    @property
    def health_digest(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class LatentProduceRequest:
    request_id: str
    task_id: str
    source_step_id: str
    producer_role: str
    consumer_role: str
    messages: tuple[Mapping[str, str], ...]
    latent_steps: int
    alignment_method: str
    anchor: LatentAnchor
    ttl_s: int
    compatibility_signature: NeuralCompatibilitySignature

    def canonical_payload(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "source_step_id": self.source_step_id,
            "producer_role": self.producer_role,
            "consumer_role": self.consumer_role,
            "messages": [dict(message) for message in self.messages],
            "latent_steps": self.latent_steps,
            "alignment_method": self.alignment_method,
            "anchor": self.anchor.canonical_payload(),
            "ttl_s": self.ttl_s,
            "compatibility_digest": self.compatibility_signature.compatibility_digest,
        }


@dataclass(frozen=True)
class LatentProduceResult:
    ref: LatentStateRef
    captured_step_count: int
    recurrence_injection_count: int
    internal_scheduler_sample_count: int
    telemetry: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LatentCompleteRequest:
    request_id: str
    latent_ref_id: str
    rendered_prompt: str
    response_schema: Mapping[str, Any]
    temperature: float
    max_tokens: int
    seed: int
    expected_compatibility_digest: str
    expected_anchor: LatentAnchor
    messages: tuple[Mapping[str, str], ...] = ()


@dataclass(frozen=True)
class LatentCompleteResult:
    text: str
    consumed_ref_id: str
    consumer_forward_observed: bool
    forward_proof: LatentForwardProof | None
    prompt_embed_shape: tuple[int, ...]
    prompt_tokens_equivalent: int = 0
    completion_tokens: int = 0
    telemetry: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class RoleModelBackend(Protocol):
    def health(self) -> LatentBackendHealth: ...

    def produce(self, request: LatentProduceRequest) -> LatentProduceResult: ...

    def complete(self, request: LatentCompleteRequest) -> LatentCompleteResult: ...

    def release(self, ref_id: str) -> None: ...


class FakeRoleModelBackend:
    """Contract-only backend. Its receipts can never prove model forward use."""

    def __init__(
        self,
        *,
        signature: NeuralCompatibilitySignature,
        now_ns: int = 1_000_000_000,
    ) -> None:
        self.signature = signature
        self.now_ns = now_ns
        self.refs: dict[str, LatentStateRef] = {}
        self.released_ref_ids: set[str] = set()

    def health(self) -> LatentBackendHealth:
        active_refs = [
            ref
            for ref in self.refs.values()
            if ref.status not in {
                LatentLifecycleState.RELEASED,
                LatentLifecycleState.EXPIRED,
            }
        ]
        return LatentBackendHealth(
            status="ready",
            plugin_version="statebus.fake_latent.v1",
            compatibility_signature=self.signature,
            worker_extension_ready=True,
            prompt_embeds_enabled=True,
            max_num_seqs=1,
            registry_entries=len(active_refs),
            registry_bytes=sum(ref.tensor_bytes for ref in active_refs),
            registry_max_entries=64,
            registry_max_bytes=67_108_864,
            registry_max_steps=80,
            backend_kind="fake_contract_only",
        )

    def produce(self, request: LatentProduceRequest) -> LatentProduceResult:
        if request.compatibility_signature.compatibility_digest != self.signature.compatibility_digest:
            raise LatentBackendError("latent_model_incompatible")
        if request.latent_steps < 2:
            raise LatentBackendError("latent_capture_incomplete")
        ref_id = f"latent-fake-{uuid4().hex}"
        tensor_digest = sha256_digest({
            "fake_contract_only": True,
            "request": request.canonical_payload(),
        })
        ref = LatentStateRef(
            ref_id=ref_id,
            status=LatentLifecycleState.COMMITTED,
            backend_handle=f"fake-handle:{ref_id}",
            producer_role=request.producer_role,
            consumer_role=request.consumer_role,
            source_task_id=request.task_id,
            source_step_id=request.source_step_id,
            source_evidence_pack_hash=request.anchor.evidence_pack_hash,
            anchor_item_ids=request.anchor.item_ids,
            anchor_locator_digest=request.anchor.locator_digest,
            model_id=self.signature.model_id,
            model_revision=self.signature.model_revision_or_manifest_digest,
            tokenizer_revision=self.signature.tokenizer_revision,
            chat_template_digest=self.signature.chat_template_digest,
            hidden_size=self.signature.hidden_size,
            source_layer_index=-1,
            latent_step_count=request.latent_steps,
            alignment_method=request.alignment_method,
            alignment_config_digest=self.signature.alignment_config_digest,
            position_contract_digest=self.signature.position_contract_digest,
            dtype="bfloat16",
            shape=(request.latent_steps, self.signature.hidden_size),
            tensor_bytes=request.latent_steps * self.signature.hidden_size * 2,
            tensor_digest=tensor_digest,
            producer_pid=0,
            engine_id="fake-engine",
            created_at_ns=self.now_ns,
            expires_at_ns=self.now_ns + request.ttl_s * 1_000_000_000,
            compatibility_digest=self.signature.compatibility_digest,
            metadata={"proof_kind": LatentProofKind.FAKE.value},
        )
        self.refs[ref_id] = ref
        return LatentProduceResult(
            ref=ref,
            captured_step_count=request.latent_steps,
            recurrence_injection_count=request.latent_steps - 1,
            internal_scheduler_sample_count=request.latent_steps,
            telemetry={"mechanism_proof_kind": LatentProofKind.FAKE.value},
        )

    def complete(self, request: LatentCompleteRequest) -> LatentCompleteResult:
        try:
            ref = self.refs[request.latent_ref_id]
        except KeyError as exc:
            raise LatentBackendError("latent_ref_not_found") from exc
        if ref.ref_id in self.released_ref_ids:
            raise LatentBackendError("latent_ref_already_consumed")
        if request.expected_compatibility_digest != ref.compatibility_digest:
            raise LatentBackendError("latent_model_incompatible")
        if request.expected_anchor.evidence_pack_hash != ref.source_evidence_pack_hash:
            raise LatentBackendError("latent_anchor_mismatch")
        fake_proof = LatentForwardProof(
            ref_id=ref.ref_id,
            request_id=request.request_id,
            worker_pid=0,
            engine_id="fake-engine",
            inputs_embeds_shape=(ref.latent_step_count, ref.hidden_size),
            inputs_embeds_dtype="bfloat16",
            inputs_embeds_digest=ref.tensor_digest,
            observed_at_ns=self.now_ns,
            event_id=f"fake-forward-{uuid4().hex}",
            proof_kind=LatentProofKind.FAKE,
        )
        return LatentCompleteResult(
            text="{}",
            consumed_ref_id=ref.ref_id,
            consumer_forward_observed=False,
            forward_proof=fake_proof,
            prompt_embed_shape=(ref.latent_step_count, ref.hidden_size),
            telemetry={"mechanism_proof_kind": LatentProofKind.FAKE.value},
        )

    def release(self, ref_id: str) -> None:
        ref = self.refs.get(ref_id)
        if ref is None:
            return
        self.refs[ref_id] = replace(ref, status=LatentLifecycleState.RELEASED)
        self.released_ref_ids.add(ref_id)
