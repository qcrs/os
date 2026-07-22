from __future__ import annotations

import pytest

from v2.contracts import NeuralCompatibilitySignature


@pytest.fixture
def neural_signature() -> NeuralCompatibilitySignature:
    return NeuralCompatibilitySignature(
        vllm_version="0.9.2",
        engine_generation="V0",
        model_id="qwen3-32b",
        model_revision_or_manifest_digest="sha256:model-revision",
        architecture="Qwen3ForCausalLM",
        tokenizer_id="qwen3-32b",
        tokenizer_revision="sha256:tokenizer-revision",
        chat_template_digest="sha256:chat-template",
        active_lora_or_adapter_digest="none",
        quantization_digest="none",
        dtype="bfloat16",
        hidden_size=5120,
        num_layers=64,
        num_attention_heads=64,
        num_kv_heads=8,
        head_dim=128,
        rope_config_digest="sha256:rope",
        attention_backend="flash_attention",
        tensor_parallel_size=1,
        pipeline_parallel_size=1,
        worker_extension_version="statebus.vllm_latent.v1",
        alignment_method="soft_token_topk_v1",
        alignment_config_digest="sha256:alignment",
        position_contract_digest="sha256:position",
    )
