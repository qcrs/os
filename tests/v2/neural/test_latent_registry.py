from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest
import torch

from v2.contracts import (
    LatentAnchor,
    LatentForwardProof,
    LatentLifecycleState,
    LatentProofKind,
    NeuralCompatibilitySignature,
)
from v2.integrations.vllm_latent.registry import (
    LatentRegistryConfig,
    LatentRegistryError,
    LatentRegistryMetadata,
    LatentTensorRegistry,
)


def _signature(neural_signature: NeuralCompatibilitySignature) -> NeuralCompatibilitySignature:
    return replace(
        neural_signature,
        hidden_size=8,
        num_attention_heads=1,
        num_kv_heads=1,
        head_dim=8,
    )


def _metadata(signature: NeuralCompatibilitySignature, *, task: str = "task") -> LatentRegistryMetadata:
    return LatentRegistryMetadata(
        producer_role="retriever",
        consumer_role="summarizer",
        source_task_id=task,
        source_step_id="retrieve",
        anchor=LatentAnchor(
            evidence_pack_hash="evidence-hash",
            item_ids=("ev-1",),
            locator_digest="locator-hash",
        ),
        compatibility_signature=signature,
        source_layer_index=-1,
        engine_id="engine-1",
        producer_pid=123,
    )


def _tensor_digest(tensor: torch.Tensor) -> str:
    normalized = tensor.to(device="cpu", dtype=torch.bfloat16).contiguous()
    return hashlib.sha256(normalized.view(torch.uint8).numpy().tobytes()).hexdigest()


def _committed_registry(
    neural_signature: NeuralCompatibilitySignature,
    *,
    clock=None,
    config: LatentRegistryConfig | None = None,
):
    signature = _signature(neural_signature)
    registry = LatentTensorRegistry(
        config or LatentRegistryConfig(max_bytes=4096, max_entries=4, default_ttl_s=60),
        clock_ns=clock or (lambda: 1_000_000_000),
    )
    ref_id = registry.prepare(metadata=_metadata(signature), latent_step_count=2)
    tensor = torch.arange(16, dtype=torch.float32).reshape(2, 8)
    ref = registry.commit(
        ref_id,
        tensor,
        captured_step_count=2,
        recurrence_injection_count=1,
    )
    return registry, signature, ref, tensor


def test_registry_default_supports_the_preregistered_40_step_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STATEBUS_LATENT_MAX_STEPS", raising=False)

    assert LatentRegistryConfig.from_env().max_steps == 80


def test_registry_commits_real_bf16_bytes_and_exposes_no_tensor(
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    registry, _signature_value, ref, tensor = _committed_registry(neural_signature)

    assert ref.status == LatentLifecycleState.COMMITTED
    assert ref.dtype == "bfloat16"
    assert ref.tensor_bytes == 2 * 8 * 2
    assert ref.tensor_digest == _tensor_digest(tensor)
    payload = ref.canonical_payload()
    assert "tensor" not in payload
    assert "tensor_bytes" in payload
    assert registry.stats()["registry_bytes"] == ref.tensor_bytes


def test_registry_lifecycle_requires_worker_forward_proof(
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    registry, signature, ref, _tensor = _committed_registry(neural_signature)
    anchor_digest = _metadata(signature).anchor.anchor_digest
    leased = registry.lease(
        ref.ref_id,
        request_id="consumer-1",
        expected_compatibility_digest=signature.compatibility_digest,
        expected_anchor_digest=anchor_digest,
    )
    # The anchor digest is deliberately taken from the source metadata rather
    # than from a client-supplied arbitrary value.
    assert leased.status == LatentLifecycleState.LEASED
    prompt = torch.ones((3, 8), dtype=torch.bfloat16)
    prompt_digest = _tensor_digest(prompt)
    registry.begin_consume(
        ref.ref_id,
        request_id="consumer-1",
        prompt_embed_digest=prompt_digest,
        prompt_embed_shape=(3, 8),
        prompt_embed_dtype="bfloat16",
    )
    fake = LatentForwardProof(
        ref_id=ref.ref_id,
        request_id="consumer-1",
        worker_pid=1,
        engine_id="engine-1",
        inputs_embeds_shape=(3, 8),
        inputs_embeds_dtype="bfloat16",
        inputs_embeds_digest=prompt_digest,
        observed_at_ns=2,
        event_id="fake-event",
        proof_kind=LatentProofKind.FAKE,
    )
    with pytest.raises(LatentRegistryError, match="forward_not_observed"):
        registry.finish_consume(fake)
    real = replace(fake, proof_kind=LatentProofKind.WORKER_FORWARD)
    consumed = registry.finish_consume(real)
    assert consumed.status == LatentLifecycleState.CONSUMED
    assert registry.forward_proof(ref.ref_id) == real
    with pytest.raises(LatentRegistryError, match="already_consumed"):
        registry.lease(
            ref.ref_id,
            request_id="consumer-2",
            expected_compatibility_digest=signature.compatibility_digest,
            expected_anchor_digest=anchor_digest,
        )


def test_registry_rejects_anchor_mismatch_before_materialization(
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    registry, signature, ref, _tensor = _committed_registry(neural_signature)

    with pytest.raises(LatentRegistryError, match="latent_anchor_mismatch"):
        registry.lease(
            ref.ref_id,
            request_id="consumer-wrong-anchor",
            expected_compatibility_digest=signature.compatibility_digest,
            expected_anchor_digest="sha256:wrong-anchor",
        )

    assert registry.describe(ref.ref_id).status == LatentLifecycleState.COMMITTED
    with pytest.raises(LatentRegistryError) as exc_info:
        registry.materialize_tensor(ref.ref_id)
    assert exc_info.value.error_code == "latent_request_invalid"
    assert exc_info.value.detail == "ref_not_leased"


@pytest.mark.parametrize(
    ("proof_field", "replacement_value"),
    (
        ("request_id", "consumer-other"),
        ("inputs_embeds_shape", (2, 8)),
        ("inputs_embeds_digest", "sha256:wrong-prompt-embeds"),
    ),
)
def test_registry_rejects_each_forward_proof_binding_mismatch(
    neural_signature: NeuralCompatibilitySignature,
    proof_field: str,
    replacement_value: object,
) -> None:
    registry, signature, ref, _tensor = _committed_registry(neural_signature)
    anchor_digest = _metadata(signature).anchor.anchor_digest
    registry.lease(
        ref.ref_id,
        request_id="consumer-1",
        expected_compatibility_digest=signature.compatibility_digest,
        expected_anchor_digest=anchor_digest,
    )
    prompt = torch.ones((3, 8), dtype=torch.bfloat16)
    prompt_digest = _tensor_digest(prompt)
    registry.begin_consume(
        ref.ref_id,
        request_id="consumer-1",
        prompt_embed_digest=prompt_digest,
        prompt_embed_shape=(3, 8),
        prompt_embed_dtype="bfloat16",
    )
    proof = LatentForwardProof(
        ref_id=ref.ref_id,
        request_id="consumer-1",
        worker_pid=1,
        engine_id="engine-1",
        inputs_embeds_shape=(3, 8),
        inputs_embeds_dtype="bfloat16",
        inputs_embeds_digest=prompt_digest,
        observed_at_ns=2,
        event_id=f"mismatch-{proof_field}",
    )

    with pytest.raises(LatentRegistryError, match="forward_not_observed"):
        registry.finish_consume(replace(proof, **{proof_field: replacement_value}))

    assert registry.describe(ref.ref_id).status == LatentLifecycleState.CONSUMING
    assert registry.forward_proof(ref.ref_id) is None


def test_registry_expiry_capacity_and_idempotent_release(
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    now = [1_000_000_000]
    registry, signature, ref, _tensor = _committed_registry(
        neural_signature,
        clock=lambda: now[0],
    )
    now[0] += 61_000_000_000
    with pytest.raises(LatentRegistryError, match="expired"):
        registry.describe(ref.ref_id)
    with pytest.raises(LatentRegistryError, match="expired"):
        registry.release(ref.ref_id)
    with pytest.raises(LatentRegistryError, match="not_found"):
        registry.describe("unknown-ref")

    registry, signature, ref, _tensor = _committed_registry(
        neural_signature,
        config=LatentRegistryConfig(max_bytes=64, max_entries=1, default_ttl_s=60),
    )
    second_id = registry.prepare(metadata=_metadata(signature, task="task-2"), latent_step_count=2)
    second = registry.commit(
        second_id,
        torch.ones((2, 8), dtype=torch.bfloat16),
        captured_step_count=2,
        recurrence_injection_count=1,
    )
    assert second.status == LatentLifecycleState.COMMITTED
    with pytest.raises(LatentRegistryError, match="not_found"):
        registry.describe(ref.ref_id)
    released = registry.release(second.ref_id)
    assert released.status == LatentLifecycleState.RELEASED
    assert registry.release(second.ref_id).status == LatentLifecycleState.RELEASED


def test_registry_capacity_does_not_evict_a_leased_entry(
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    registry, signature, first, _tensor = _committed_registry(
        neural_signature,
        config=LatentRegistryConfig(max_bytes=64, max_entries=1, default_ttl_s=60),
    )
    registry.lease(
        first.ref_id,
        request_id="consumer-1",
        expected_compatibility_digest=signature.compatibility_digest,
        expected_anchor_digest=_metadata(signature).anchor.anchor_digest,
    )
    second_id = registry.prepare(
        metadata=_metadata(signature, task="task-2"),
        latent_step_count=2,
    )

    with pytest.raises(LatentRegistryError, match="capacity_exceeded"):
        registry.commit(
            second_id,
            torch.ones((2, 8), dtype=torch.bfloat16),
            captured_step_count=2,
            recurrence_injection_count=1,
        )

    assert registry.describe(first.ref_id).status == LatentLifecycleState.LEASED
    assert registry.stats()["registry_entries"] == 1
