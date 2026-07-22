from __future__ import annotations

from dataclasses import replace

import pytest

from v2.contracts import (
    HandoffIntent,
    LatentLifecycleState,
    NeuralCompatibilitySignature,
    RefKind,
    StorageKind,
)
from v2.refs import LatentStateRef


def _latent_ref(signature: NeuralCompatibilitySignature) -> LatentStateRef:
    return LatentStateRef(
        ref_id="latent-1",
        status=LatentLifecycleState.COMMITTED,
        backend_handle="opaque-handle",
        producer_role="retriever",
        consumer_role="summarizer",
        source_task_id="task-1",
        source_step_id="retrieve",
        source_evidence_pack_hash="sha256:evidence",
        anchor_item_ids=("ev-1", "ev-2"),
        anchor_locator_digest="sha256:locators",
        model_id=signature.model_id,
        model_revision=signature.model_revision_or_manifest_digest,
        tokenizer_revision=signature.tokenizer_revision,
        chat_template_digest=signature.chat_template_digest,
        hidden_size=signature.hidden_size,
        source_layer_index=-1,
        latent_step_count=8,
        alignment_method=signature.alignment_method,
        alignment_config_digest=signature.alignment_config_digest,
        position_contract_digest=signature.position_contract_digest,
        dtype="bfloat16",
        shape=(8, 5120),
        tensor_bytes=8 * 5120 * 2,
        tensor_digest="sha256:tensor",
        producer_pid=123,
        engine_id="engine-1",
        created_at_ns=1,
        expires_at_ns=2,
        compatibility_digest=signature.compatibility_digest,
    )


def test_latent_ref_is_distinct_opaque_engine_local_contract(
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    ref = _latent_ref(neural_signature)
    payload = ref.canonical_payload()

    assert RefKind.LATENT_STATE.value == "latent_state"
    assert StorageKind.ENGINE_LOCAL.value == "engine_local"
    assert payload["ref_kind"] == "latent_state"
    assert payload["storage_kind"] == "engine_local"
    assert payload["backend_handle"] == "opaque-handle"
    assert "tensor" not in payload
    assert "tensor_bytes" in payload
    assert ref.registry_entry().ref_kind == RefKind.LATENT_STATE
    assert ref.ref_hash == _latent_ref(neural_signature).ref_hash


def test_latent_ref_rejects_shape_and_byte_contract_mismatch(
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    with pytest.raises(ValueError, match="shape_contract_mismatch"):
        replace(_latent_ref(neural_signature), shape=(7, 5120))
    with pytest.raises(ValueError, match="byte_count_mismatch"):
        replace(_latent_ref(neural_signature), tensor_bytes=1)


def test_neural_signature_is_exact_and_support_matrix_is_fail_closed(
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    assert neural_signature.initial_support_matrix_errors() == ()
    assert neural_signature.is_exactly_compatible_with(neural_signature)
    assert len(neural_signature.compatibility_digest) == 64

    wrong_revision = replace(
        neural_signature,
        model_revision_or_manifest_digest="sha256:other-model",
    )
    assert neural_signature.mismatch_fields(wrong_revision) == (
        "model_revision_or_manifest_digest",
    )
    assert not neural_signature.is_exactly_compatible_with(wrong_revision)

    unsupported = replace(neural_signature, tensor_parallel_size=2)
    assert unsupported.initial_support_matrix_errors() == ("tensor_parallel_size",)

    ridge = replace(
        neural_signature,
        alignment_method="ridge_realign_v1",
        alignment_config_digest="sha256:ridge-alignment",
    )
    assert ridge.initial_support_matrix_errors() == ()


@pytest.mark.parametrize(
    ("field_name", "error_name"),
    (
        (
            "model_revision_or_manifest_digest",
            "model_revision_or_manifest_digest",
        ),
        ("tokenizer_revision", "tokenizer_revision"),
        ("chat_template_digest", "chat_template_digest"),
    ),
)
def test_neural_signature_rejects_unknown_identity_digests(
    neural_signature: NeuralCompatibilitySignature,
    field_name: str,
    error_name: str,
) -> None:
    unsupported = replace(neural_signature, **{field_name: "unknown"})

    assert error_name in unsupported.initial_support_matrix_errors()


@pytest.mark.parametrize(
    ("field_name", "replacement_value"),
    (
        ("alignment_config_digest", "sha256:other-alignment-config"),
        ("position_contract_digest", "sha256:other-position-contract"),
    ),
)
def test_neural_signature_rejects_alignment_and_position_digest_mismatch(
    neural_signature: NeuralCompatibilitySignature,
    field_name: str,
    replacement_value: str,
) -> None:
    incompatible = replace(
        neural_signature,
        **{field_name: replacement_value},
    )

    assert neural_signature.mismatch_fields(incompatible) == (field_name,)
    assert not neural_signature.is_exactly_compatible_with(incompatible)
    assert neural_signature.compatibility_digest != incompatible.compatibility_digest


def test_handoff_intent_values_are_bounded() -> None:
    assert {intent.value for intent in HandoffIntent} == {
        "auto",
        "text",
        "latent_assist",
        "exact_artifact_preferred",
    }
