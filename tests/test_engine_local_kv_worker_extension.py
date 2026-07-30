from __future__ import annotations

from types import SimpleNamespace

import pytest
import torch

from statebus.integrations.vllm_kv.registry import (
    KVRegistryConfig,
    get_worker_registry,
    reset_worker_registry_for_tests,
)
from statebus.integrations.vllm_kv.worker_extension import (
    KVWorkerError,
    StateBusKVWorkerExtension,
)
from statebus.utils import sha256_digest


def _worker() -> StateBusKVWorkerExtension:
    worker = StateBusKVWorkerExtension()
    worker.vllm_config = SimpleNamespace(
        model_config=SimpleNamespace(
            hf_config=SimpleNamespace(num_hidden_layers=2),
            dtype="bfloat16",
            max_model_len=8192,
        ),
        cache_config=SimpleNamespace(
            block_size=2,
            enable_prefix_caching=False,
        ),
        scheduler_config=SimpleNamespace(max_num_seqs=1),
        parallel_config=SimpleNamespace(
            tensor_parallel_size=1,
            pipeline_parallel_size=1,
        ),
        kv_transfer_config=SimpleNamespace(
            engine_id="engine-1",
            kv_connector="StateBusLocalKVConnector",
            kv_role="kv_both",
        ),
    )
    return worker


def _ready_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "VLLM_USE_V1": "1",
        "STATEBUS_KV_ENGINE_GENERATION": "generation-1",
        "STATEBUS_KV_MODEL_ID": "qwen3-32b",
        "STATEBUS_KV_MODEL_REVISION_DIGEST": "model-revision",
        "STATEBUS_KV_TOKENIZER_DIGEST": "tokenizer-digest",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def _prepare_ready_handle(
    worker: StateBusKVWorkerExtension,
    *,
    handle_id: str = "kv-worker-test",
) -> tuple[tuple[int, ...], dict[str, object]]:
    tokens = (10, 11, 12, 13)
    health = worker.statebus_kv_capabilities()
    prepared = worker.statebus_kv_prepare(
        {
            "handle_id": handle_id,
            "request_id": f"produce-{handle_id}",
            "task_id": "task-1",
            "token_ids": list(tokens),
            "token_digest": sha256_digest(list(tokens)),
            "ttl_s": 60,
            "expected_compatibility_digest": health["compatibility_digest"],
        }
    )
    registry = get_worker_registry()
    registry.put_layer(handle_id, "layer-0", (torch.ones((2, 4, 1)),))
    registry.put_layer(handle_id, "layer-1", (torch.ones((2, 4, 1)),))
    registry.commit(handle_id, store_ms=0.5)
    return tokens, prepared


def test_worker_health_fails_closed_when_runtime_configuration_is_unsafe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_worker_registry_for_tests(KVRegistryConfig(pin_memory=False))
    monkeypatch.delenv("VLLM_USE_V1", raising=False)
    monkeypatch.delenv("STATEBUS_KV_ENGINE_GENERATION", raising=False)
    monkeypatch.delenv("STATEBUS_KV_MODEL_REVISION_DIGEST", raising=False)
    monkeypatch.delenv("STATEBUS_KV_TOKENIZER_DIGEST", raising=False)
    worker = _worker()
    worker.vllm_config.cache_config.enable_prefix_caching = True
    worker.vllm_config.scheduler_config.max_num_seqs = 2

    health = worker.statebus_kv_capabilities()

    assert health["status"] == "not_ready"
    assert set(health["errors"]) >= {
        "engine_generation_missing",
        "model_revision_missing",
        "tokenizer_digest_missing",
        "vllm_v1_required",
        "automatic_prefix_caching_must_be_disabled",
        "max_num_seqs_must_be_one",
    }
    with pytest.raises(KVWorkerError, match="kv_plugin_not_ready"):
        worker.statebus_kv_prepare({})


def test_worker_prepare_and_consume_enforce_compatibility_task_and_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_worker_registry_for_tests(
        KVRegistryConfig(max_entries=4, max_bytes=4096, pin_memory=False)
    )
    _ready_environment(monkeypatch)
    worker = _worker()
    health = worker.statebus_kv_capabilities()
    assert health["status"] == "ready"

    tokens = (10, 11, 12, 13)
    with pytest.raises(KVWorkerError, match="kv_token_mismatch"):
        worker.statebus_kv_prepare(
            {
                "request_id": "produce-bad-digest",
                "task_id": "task-1",
                "token_ids": list(tokens),
                "token_digest": "wrong",
                "expected_compatibility_digest": health["compatibility_digest"],
            }
        )

    stored_tokens, prepared = _prepare_ready_handle(worker)
    assert prepared["status"] == "preparing"
    assert prepared["handle"]["storage_tier"] == "worker_pageable_host"
    with pytest.raises(KVWorkerError, match="kv_task_mismatch"):
        worker.statebus_kv_prepare_consume(
            "kv-worker-test",
            "consume-wrong-task",
            "other-task",
            str(health["compatibility_digest"]),
        )

    consumed = worker.statebus_kv_prepare_consume(
        "kv-worker-test",
        "consume-1",
        "task-1",
        str(health["compatibility_digest"]),
    )
    assert consumed["status"] == "consuming"
    assert tuple(consumed["token_ids"]) == stored_tokens
    assert consumed["token_digest"] == sha256_digest(list(stored_tokens))


def test_worker_rejects_handle_after_engine_generation_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_worker_registry_for_tests(
        KVRegistryConfig(max_entries=4, max_bytes=4096, pin_memory=False)
    )
    _ready_environment(monkeypatch)
    worker = _worker()
    _prepare_ready_handle(worker, handle_id="kv-old-generation")

    monkeypatch.setenv("STATEBUS_KV_ENGINE_GENERATION", "generation-2")
    new_health = worker.statebus_kv_capabilities()
    with pytest.raises(KVWorkerError, match="kv_model_incompatible"):
        worker.statebus_kv_prepare_consume(
            "kv-old-generation",
            "consume-new-generation",
            "task-1",
            str(new_health["compatibility_digest"]),
        )
