from __future__ import annotations

from dataclasses import dataclass, replace
from types import SimpleNamespace
import hashlib

import pytest
import torch

from v2.contracts import (
    LatentAnchor,
    LatentLifecycleState,
    NeuralCompatibilitySignature,
)
from v2.integrations.vllm_latent.worker_extension import (
    LatentWorkerError,
    LatentWorkerExtension,
    _clear_temporary_sampled_embeds,
)
from v2.integrations.vllm_latent.alignment import (
    RIDGE_REALIGN_V1,
    resolve_alignment_configuration,
    write_ridge_realign_artifact,
)


@dataclass(frozen=True)
class _Input:
    input_tokens: torch.Tensor
    inputs_embeds: torch.Tensor | None
    request_ids_to_seq_ids: dict[str, list[int]]
    sampling_metadata: object | None = None
    is_prompt: bool = True


class _Model:
    def __init__(self, hidden_size: int = 8, vocab_size: int = 16) -> None:
        torch.manual_seed(7)
        self.config = SimpleNamespace(vocab_size=vocab_size)
        self.weight = torch.randn(vocab_size, hidden_size, dtype=torch.bfloat16)
        self.device = torch.device("cpu")

    def get_input_embeddings(self, token_ids: torch.Tensor) -> torch.Tensor:
        return self.weight[token_ids]

    def compute_logits(self, hidden: torch.Tensor, _sampling_metadata: object) -> torch.Tensor:
        return hidden.float() @ self.weight.float().transpose(0, 1)


class _PaddedLogitModel(_Model):
    def __init__(self) -> None:
        super().__init__()
        self.config.vocab_size = 20
        self.model = SimpleNamespace(
            config=SimpleNamespace(vocab_size=20),
            embed_tokens=SimpleNamespace(num_embeddings=16, org_vocab_size=16),
        )

    def compute_logits(self, hidden: torch.Tensor, sampling_metadata: object) -> torch.Tensor:
        assert sampling_metadata is None
        logits = super().compute_logits(hidden, sampling_metadata)
        padded = torch.full(
            (*logits.shape[:-1], 4),
            1e6,
            dtype=logits.dtype,
            device=logits.device,
        )
        return torch.cat((logits, padded), dim=-1)


class _Runner:
    def __init__(self) -> None:
        self.model = _Model()
        self.model_config = SimpleNamespace(vocab_size=16)
        self.device = torch.device("cpu")
        self.return_hidden_states = False
        self.calls: list[_Input] = []
        self.mutate_inputs_embeds = False

    def execute_model(self, model_input: _Input, *args, **kwargs):
        del args, kwargs
        self.calls.append(model_input)
        if model_input.inputs_embeds is not None:
            hidden = model_input.inputs_embeds + torch.tensor(0.1, dtype=torch.bfloat16)
            if self.mutate_inputs_embeds:
                model_input.inputs_embeds.add_(1)
        else:
            hidden = self.model.get_input_embeddings(model_input.input_tokens)
        return [SimpleNamespace(hidden_states=hidden)]


class _Host(LatentWorkerExtension):
    def __init__(self, signature: NeuralCompatibilitySignature) -> None:
        self.model_runner = _Runner()
        self._statebus_signature_override = signature


def _small_signature(
    signature: NeuralCompatibilitySignature,
) -> NeuralCompatibilitySignature:
    return replace(
        signature,
        hidden_size=8,
        num_attention_heads=1,
        num_kv_heads=1,
        head_dim=8,
    )


def _capture_spec(signature: NeuralCompatibilitySignature, *, steps: int = 3) -> dict[str, object]:
    return {
        "capture_id": "capture-1",
        "request_id": "producer-1",
        "task_id": "task-1",
        "source_step_id": "retrieve",
        "producer_role": "retriever",
        "consumer_role": "summarizer",
        "latent_steps": steps,
        "ttl_s": 60,
        "alignment_method": signature.alignment_method,
        "expected_compatibility_digest": signature.compatibility_digest,
        "anchor": {
            "evidence_pack_hash": "evidence-hash",
            "item_ids": ["ev-1"],
            "locator_digest": "locator-hash",
        },
    }


def _input(
    request_id: str,
    *,
    embeds: torch.Tensor | None = None,
    sampling_metadata: object | None = None,
) -> _Input:
    return _Input(
        input_tokens=torch.tensor([1], dtype=torch.long),
        inputs_embeds=embeds,
        request_ids_to_seq_ids={request_id: [0]},
        sampling_metadata=sampling_metadata,
        is_prompt=embeds is None,
    )


def _digest(tensor: torch.Tensor) -> str:
    value = tensor.to(dtype=torch.bfloat16, device="cpu").contiguous()
    return hashlib.sha256(value.view(torch.uint8).numpy().tobytes()).hexdigest()


def test_worker_normal_request_is_passthrough_before_capture(
    neural_signature,
) -> None:
    signature = _small_signature(neural_signature)
    host = _Host(signature)
    model_input = _input("ordinary-1")

    output = host.model_runner.execute_model(model_input)

    assert output
    assert host.model_runner.calls == [model_input]
    assert host.model_runner.return_hidden_states is False


def test_worker_captures_hidden_recurrence_and_commits_opaque_ref(
    neural_signature,
) -> None:
    signature = _small_signature(neural_signature)
    host = _Host(signature)
    started = host.statebus_latent_begin(_capture_spec(signature))

    for _ in range(3):
        host.model_runner.execute_model(_input("producer-1"))

    finished = host.statebus_latent_finish(str(started["capture_id"]))

    assert finished["status"] == "committed"
    assert finished["shape"] == [3, 8]
    assert finished["dtype"] == "bfloat16"
    assert finished["tensor_bytes"] == 3 * 8 * 2
    assert finished["captured_step_count"] == 3
    assert finished["recurrence_injection_count"] == 2
    assert finished["tensor_digest"]
    assert "prompt" not in finished
    assert host.model_runner.return_hidden_states is False
    assert host.model_runner._statebus_wrapper_depth == 1
    assert host._statebus_capture_active is None
    assert host.model_runner.calls[1].inputs_embeds is not None
    assert host.model_runner.calls[2].inputs_embeds is not None


def test_worker_clips_padded_logits_before_embedding_lookup(neural_signature) -> None:
    signature = _small_signature(neural_signature)
    host = _Host(signature)
    host.model_runner.model = _PaddedLogitModel()
    host.model_runner.model_config.vocab_size = 20
    started = host.statebus_latent_begin(_capture_spec(signature, steps=2))

    pruning_metadata = SimpleNamespace(
        selected_token_indices=torch.tensor([99], dtype=torch.long)
    )
    host.model_runner.execute_model(
        _input("producer-1", sampling_metadata=pruning_metadata)
    )
    host.model_runner.execute_model(
        _input("producer-1", sampling_metadata=pruning_metadata)
    )

    finished = host.statebus_latent_finish(str(started["capture_id"]))
    assert finished["status"] == "committed"
    assert finished["shape"] == [2, 8]


def test_worker_captures_ridge_realign_with_aggregate_diagnostics(
    neural_signature, tmp_path, monkeypatch
) -> None:
    matrix_path = tmp_path / "ridge.npy"
    metadata_path = tmp_path / "ridge.json"
    artifact = write_ridge_realign_artifact(
        matrix=torch.eye(8),
        matrix_path=matrix_path,
        metadata_path=metadata_path,
        model_revision_or_manifest_digest=neural_signature.model_revision_or_manifest_digest,
        input_embedding_digest="sha256:input",
        output_embedding_digest="sha256:output",
        target_norm=1.0,
        regularization=0.01,
        training_row_count=16,
        linear_system_relative_residual=1e-7,
        embedding_fit_relative_rmse=0.25,
        identity_relative_rmse=0.5,
        embedding_fit_mean_cosine=0.95,
    )
    monkeypatch.setenv("STATEBUS_LATENT_ALIGNMENT", RIDGE_REALIGN_V1)
    monkeypatch.setenv("STATEBUS_LATENT_ALIGNMENT_ARTIFACT", str(matrix_path))
    monkeypatch.setenv("STATEBUS_LATENT_ALIGNMENT_METADATA", str(metadata_path))
    monkeypatch.setenv("STATEBUS_LATENT_ALIGNMENT_DIAGNOSTICS", "true")
    configuration = resolve_alignment_configuration(
        model_revision=neural_signature.model_revision_or_manifest_digest,
        hidden_size=8,
    )
    signature = replace(
        _small_signature(neural_signature),
        alignment_method=RIDGE_REALIGN_V1,
        alignment_config_digest=configuration.config_digest,
    )
    host = _Host(signature)
    started = host.statebus_latent_begin(_capture_spec(signature, steps=2))

    host.model_runner.execute_model(_input("producer-1"))
    host.model_runner.execute_model(_input("producer-1"))
    finished = host.statebus_latent_finish(str(started["capture_id"]))

    diagnostics = finished["alignment_diagnostics"]
    assert finished["status"] == "committed"
    assert diagnostics["observation_count"] == 2
    assert "direct_lm_head_topk_overlap_mean" in diagnostics
    assert diagnostics["direct_lm_head_topk_kl_min"] >= 0.0
    assert not {"prompt", "token_ids", "hidden_states", "matrix"}.intersection(
        diagnostics
    )
    assert artifact.matrix_sha256


def test_worker_rejects_capture_method_that_differs_from_signature(neural_signature) -> None:
    signature = _small_signature(neural_signature)
    host = _Host(signature)
    spec = _capture_spec(signature, steps=2)
    spec["alignment_method"] = "ridge_realign_v1"

    with pytest.raises(LatentWorkerError, match="latent_alignment_incompatible"):
        host.statebus_latent_begin(spec)


def test_worker_health_rejects_missing_ridge_artifact_before_capture(
    neural_signature, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("STATEBUS_LATENT_ALIGNMENT", RIDGE_REALIGN_V1)
    monkeypatch.setenv(
        "STATEBUS_LATENT_ALIGNMENT_ARTIFACT", str(tmp_path / "missing.npy")
    )
    monkeypatch.setenv(
        "STATEBUS_LATENT_ALIGNMENT_METADATA", str(tmp_path / "missing.json")
    )
    signature = replace(
        _small_signature(neural_signature),
        alignment_method=RIDGE_REALIGN_V1,
        alignment_config_digest="sha256:ridge-missing",
    )
    host = _Host(signature)

    health = host.statebus_latent_capabilities()

    assert health["status"] == "not_ready"
    assert "alignment_configuration:artifact_missing" in health["errors"]
    with pytest.raises(LatentWorkerError, match="latent_alignment_incompatible"):
        host.statebus_latent_begin(_capture_spec(signature, steps=2))


def test_temporary_recurrence_clears_sampled_embeds_but_retains_hidden() -> None:
    hidden = torch.ones((1, 8), dtype=torch.bfloat16)
    sample = SimpleNamespace(output_embed=torch.zeros(8))
    output = SimpleNamespace(
        outputs=[SimpleNamespace(samples=[sample])],
        sampled_token_embeds=torch.zeros((1, 8)),
        hidden_states=hidden,
    )

    _clear_temporary_sampled_embeds([output])

    assert output.sampled_token_embeds is None
    assert sample.output_embed is None
    assert output.hidden_states is hidden


def test_worker_incomplete_capture_is_rejected_and_restores_runner_state(
    neural_signature,
) -> None:
    signature = _small_signature(neural_signature)
    host = _Host(signature)
    started = host.statebus_latent_begin(_capture_spec(signature, steps=3))
    host.model_runner.execute_model(_input("producer-1"))

    with pytest.raises(LatentWorkerError, match="capture_incomplete"):
        host.statebus_latent_finish(str(started["capture_id"]))

    assert host._statebus_capture_active is None
    assert host.model_runner.return_hidden_states is False


def test_worker_rejects_second_active_capture(neural_signature) -> None:
    signature = _small_signature(neural_signature)
    host = _Host(signature)
    started = host.statebus_latent_begin(_capture_spec(signature, steps=2))

    with pytest.raises(LatentWorkerError, match="latent_capture_busy"):
        host.statebus_latent_begin(
            {
                **_capture_spec(signature, steps=2),
                "capture_id": "capture-2",
                "request_id": "producer-2",
            }
        )

    assert host._statebus_capture_active["capture_id"] == started["capture_id"]
    host.statebus_latent_abort(str(started["capture_id"]), "test_cleanup")
    assert host._statebus_capture_active is None
    assert host.model_runner.return_hidden_states is False


def test_worker_forward_hook_binds_consumer_transaction_to_real_inputs_embeds(
    neural_signature,
) -> None:
    signature = _small_signature(neural_signature)
    host = _Host(signature)
    started = host.statebus_latent_begin(_capture_spec(signature, steps=2))
    host.model_runner.execute_model(_input("producer-1"))
    host.model_runner.execute_model(_input("producer-1"))
    finished = host.statebus_latent_finish(str(started["capture_id"]))
    ref_id = str(finished["ref_id"])
    anchor = LatentAnchor(
        evidence_pack_hash="evidence-hash",
        item_ids=("ev-1",),
        locator_digest="locator-hash",
    )

    materialized = host.statebus_latent_materialize_consumer_prompt(
        ref_id,
        [1],
        [2],
        "consumer-1",
        signature.compatibility_digest,
        anchor.anchor_digest,
    )
    prompt = materialized["prompt_embeds"]
    assert tuple(materialized["prompt_embed_shape"]) == tuple(prompt.shape)
    assert materialized["prompt_embed_digest"] == _digest(prompt)
    host.statebus_latent_begin_consume(
        ref_id,
        "consumer-1",
        str(materialized["prompt_embed_digest"]),
        tuple(materialized["prompt_embed_shape"]),
        str(materialized["prompt_embed_dtype"]),
    )
    host.model_runner.mutate_inputs_embeds = True
    host.model_runner.execute_model(_input("consumer-1", embeds=prompt))

    described = host.statebus_latent_describe(ref_id)
    assert described["status"] == LatentLifecycleState.CONSUMED.value
    assert described["forward_proof"]["proof_kind"] == "worker_forward"
    assert described["forward_proof"]["request_id"] == "consumer-1"
    assert described["forward_proof"]["inputs_embeds_digest"] == str(
        materialized["prompt_embed_digest"]
    )

    host.statebus_latent_release(ref_id)
    assert host._statebus_consume_ref_id == ""
    assert ref_id not in host._statebus_observed_forward_proofs


def test_worker_forward_binding_mismatch_invalidates_ref_without_raising(
    neural_signature,
    caplog,
) -> None:
    signature = _small_signature(neural_signature)
    host = _Host(signature)
    started = host.statebus_latent_begin(_capture_spec(signature, steps=2))
    host.model_runner.execute_model(_input("producer-1"))
    host.model_runner.execute_model(_input("producer-1"))
    finished = host.statebus_latent_finish(str(started["capture_id"]))
    ref_id = str(finished["ref_id"])
    anchor = LatentAnchor(
        evidence_pack_hash="evidence-hash",
        item_ids=("ev-1",),
        locator_digest="locator-hash",
    )
    materialized = host.statebus_latent_materialize_consumer_prompt(
        ref_id,
        [1],
        [2],
        "consumer-1",
        signature.compatibility_digest,
        anchor.anchor_digest,
    )
    prompt = materialized["prompt_embeds"]
    host.statebus_latent_begin_consume(
        ref_id,
        "consumer-1",
        str(materialized["prompt_embed_digest"]),
        tuple(materialized["prompt_embed_shape"]),
        str(materialized["prompt_embed_dtype"]),
    )

    output = host.model_runner.execute_model(
        _input("consumer-1", embeds=prompt[:-1])
    )

    assert output
    registry = host._statebus_registry()
    described = registry.describe(ref_id, check_expiry=False)
    assert described.status == LatentLifecycleState.INVALIDATED
    assert registry.forward_proof(ref_id) is None
    assert host._statebus_consume_ref_id == ""
    assert ref_id not in getattr(host, "_statebus_observed_forward_proofs", {})
    assert "request_id_match=True" in caplog.text
    assert "digest_match=False" in caplog.text
    assert str(materialized["prompt_embed_digest"]) not in caplog.text
