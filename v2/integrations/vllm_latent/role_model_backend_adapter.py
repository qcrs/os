from __future__ import annotations

from dataclasses import fields
import time
from typing import Any, Mapping

from v2.contracts import (
    LatentForwardProof,
    LatentLifecycleState,
    LatentProofKind,
    NeuralCompatibilitySignature,
)
from v2.integrations.vllm_latent.client import VllmLatentClient
from v2.refs import LatentStateRef
from v2.runtime.role_model_backend import (
    LatentBackendHealth,
    LatentCompleteRequest,
    LatentCompleteResult,
    LatentProduceRequest,
    LatentProduceResult,
)


class VllmLatentRoleModelBackend:
    """RoleModelBackend adapter over the authenticated same-port API."""

    def __init__(self, client: VllmLatentClient | None = None) -> None:
        self.client = client or VllmLatentClient()

    def health(self) -> LatentBackendHealth:
        payload = self.client.health()
        signature = _signature_from_payload(payload.get("compatibility_signature", {}))
        return LatentBackendHealth(
            status=str(payload.get("status", "not_ready")),
            plugin_version=str(payload.get("plugin_version", "")),
            compatibility_signature=signature,
            worker_extension_ready=bool(payload.get("worker_extension_ready", False)),
            prompt_embeds_enabled=bool(payload.get("prompt_embeds_enabled", False)),
            max_num_seqs=int(payload.get("max_num_seqs", 0)),
            registry_entries=int(payload.get("registry_entries", 0)),
            registry_bytes=int(payload.get("registry_bytes", 0)),
            registry_max_entries=int(payload.get("registry_max_entries", 0)),
            registry_max_bytes=int(payload.get("registry_max_bytes", 0)),
            registry_max_steps=int(payload.get("registry_max_steps", 0)),
            backend_kind="vllm_native",
            errors=tuple(str(value) for value in payload.get("errors", ())),
        )

    def produce(self, request: LatentProduceRequest) -> LatentProduceResult:
        signature = request.compatibility_signature
        payload = self.client.produce(
            {
                "model": signature.model_id,
                "request_id": request.request_id,
                "task_id": request.task_id,
                "source_step_id": request.source_step_id,
                "producer_role": request.producer_role,
                "consumer_role": request.consumer_role,
                "messages": [dict(message) for message in request.messages],
                "latent_steps": request.latent_steps,
                "alignment_method": request.alignment_method,
                "anchor": request.anchor.canonical_payload(),
                "ttl_s": request.ttl_s,
                "expected_compatibility_digest": signature.compatibility_digest,
            }
        )
        now = time.time_ns()
        shape = tuple(int(value) for value in payload.get("shape", ()))
        ref = LatentStateRef(
            ref_id=str(payload["ref_id"]),
            status=LatentLifecycleState(str(payload["status"])),
            backend_handle=f"vllm-engine-local:{payload['ref_id']}",
            producer_role=request.producer_role,
            consumer_role=request.consumer_role,
            source_task_id=request.task_id,
            source_step_id=request.source_step_id,
            source_evidence_pack_hash=request.anchor.evidence_pack_hash,
            anchor_item_ids=request.anchor.item_ids,
            anchor_locator_digest=request.anchor.locator_digest,
            model_id=signature.model_id,
            model_revision=signature.model_revision_or_manifest_digest,
            tokenizer_revision=signature.tokenizer_revision,
            chat_template_digest=signature.chat_template_digest,
            hidden_size=signature.hidden_size,
            source_layer_index=int(payload.get("source_layer_index", -1)),
            latent_step_count=request.latent_steps,
            alignment_method=request.alignment_method,
            alignment_config_digest=signature.alignment_config_digest,
            position_contract_digest=signature.position_contract_digest,
            dtype=str(payload["dtype"]),
            shape=shape,
            tensor_bytes=int(payload["tensor_bytes"]),
            tensor_digest=str(payload["tensor_digest"]),
            producer_pid=int(payload.get("producer_pid", 0)),
            engine_id=str(payload.get("engine_id", "vllm-v0")),
            created_at_ns=int(payload.get("created_at_ns", 0)) or now,
            expires_at_ns=int(payload.get("expires_at_ns", 0))
            or now + request.ttl_s * 1_000_000_000,
            compatibility_digest=str(payload["compatibility_digest"]),
            metadata={"proof_kind": "worker_capture"},
        )
        return LatentProduceResult(
            ref=ref,
            captured_step_count=int(payload["captured_step_count"]),
            recurrence_injection_count=int(payload["recurrence_injection_count"]),
            internal_scheduler_sample_count=int(
                payload.get("internal_scheduler_sample_count", request.latent_steps)
            ),
            telemetry=dict(payload.get("telemetry", {})),
        )

    def complete(self, request: LatentCompleteRequest) -> LatentCompleteResult:
        health = self.health()
        request_payload: dict[str, object] = {
            "model": health.compatibility_signature.model_id,
            "request_id": request.request_id,
            "latent_ref_id": request.latent_ref_id,
            "rendered_prompt": request.rendered_prompt,
            "response_schema": dict(request.response_schema),
            "sampling": {
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
                "seed": request.seed,
            },
            "expected_compatibility_digest": request.expected_compatibility_digest,
            "anchor": request.expected_anchor.canonical_payload(),
        }
        if request.messages:
            request_payload["messages"] = [
                dict(message) for message in request.messages
            ]
        payload = self.client.complete(request_payload)
        proof_payload = payload.get("forward_proof")
        proof = (
            _forward_proof_from_payload(proof_payload)
            if isinstance(proof_payload, Mapping)
            else None
        )
        usage = payload.get("usage", {})
        if not isinstance(usage, Mapping):
            usage = {}
        return LatentCompleteResult(
            text=str(payload.get("text", "")),
            consumed_ref_id=str(payload.get("consumed_ref_id", "")),
            consumer_forward_observed=bool(
                payload.get("consumer_forward_observed", False)
            ),
            forward_proof=proof,
            prompt_embed_shape=tuple(
                int(value) for value in payload.get("prompt_embed_shape", ())
            ),
            prompt_tokens_equivalent=int(
                usage.get("prompt_tokens_equivalent", 0)
            ),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            telemetry=dict(payload.get("telemetry", {})),
        )

    def release(self, ref_id: str) -> None:
        self.client.release(ref_id)


def _signature_from_payload(payload: Any) -> NeuralCompatibilitySignature:
    if not isinstance(payload, Mapping):
        raise ValueError("latent compatibility signature is missing")
    names = {field.name for field in fields(NeuralCompatibilitySignature)}
    values = {name: payload[name] for name in names if name in payload}
    return NeuralCompatibilitySignature(**values)


def _forward_proof_from_payload(payload: Mapping[str, Any]) -> LatentForwardProof:
    return LatentForwardProof(
        ref_id=str(payload.get("ref_id", "")),
        request_id=str(payload.get("request_id", "")),
        worker_pid=int(payload.get("worker_pid", 0)),
        engine_id=str(payload.get("engine_id", "")),
        inputs_embeds_shape=tuple(
            int(value) for value in payload.get("inputs_embeds_shape", ())
        ),
        inputs_embeds_dtype=str(payload.get("inputs_embeds_dtype", "")),
        inputs_embeds_digest=str(payload.get("inputs_embeds_digest", "")),
        observed_at_ns=int(payload.get("observed_at_ns", 0)),
        event_id=str(payload.get("event_id", "")),
        proof_kind=LatentProofKind(str(payload.get("proof_kind", "worker_forward"))),
    )


LatentRoleModelBackendAdapter = VllmLatentRoleModelBackend
VllmRoleModelBackend = VllmLatentRoleModelBackend


__all__ = [
    "LatentRoleModelBackendAdapter",
    "VllmLatentRoleModelBackend",
    "VllmRoleModelBackend",
]
