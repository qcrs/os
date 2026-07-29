from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
import torch

from v2.contracts import EngineLocalKVHandle, KVForwardProof, KVHandleStatus
from v2.integrations.vllm_kv.connector import (
    KVConnectorRole,
    KVRequestMetadata,
    StateBusLocalKVConnector,
    StateBusLocalKVConnectorMetadata,
)
from v2.integrations.vllm_kv.paged_cache import (
    extract_kv_slots,
    inject_kv_slots,
    make_slot_mapping,
)
from v2.integrations.vllm_kv.registry import (
    KVRegistryConfig,
    KVRegistryError,
    WorkerKVRegistry,
    reset_worker_registry_for_tests,
)
from v2.utils import sha256_digest


def _handle(
    handle_id: str = "kv-test",
    *,
    task_id: str = "task-1",
    token_ids: tuple[int, ...] = (10, 11, 12, 13),
) -> EngineLocalKVHandle:
    return EngineLocalKVHandle(
        handle_id=handle_id,
        engine_id="engine-1",
        engine_generation="generation-1",
        model_id="qwen3-32b",
        model_revision="model-revision",
        tokenizer_digest="tokenizer-digest",
        task_id=task_id,
        producer_request_id=f"produce-{handle_id}",
        seq_len=len(token_ids),
        block_size=2,
        token_digest=sha256_digest(list(token_ids)),
        kv_bytes_actual=0,
        layer_count=0,
        dtype="bfloat16",
        storage_tier="worker_pinned_host",
        created_at_ns=1,
        expires_at_ns=1_000_000,
    )


def _proof(handle: EngineLocalKVHandle) -> KVForwardProof:
    return KVForwardProof(
        handle_id=handle.handle_id,
        request_id="consume-1",
        task_id=handle.task_id,
        engine_id=handle.engine_id,
        engine_generation=handle.engine_generation,
        token_digest=handle.token_digest,
        inherited_kv_tokens=handle.seq_len,
        computed_prefill_tokens=2,
        logical_prompt_tokens=handle.seq_len + 2,
        suffix_tokens=2,
        layer_count=handle.layer_count,
        kv_bytes_actual=handle.kv_bytes_actual,
        connector_load_count=1,
        kv_load_ms=0.5,
        worker_pid=123,
        observed_at_ns=2,
    )


def test_preparing_handle_occupies_registry_capacity() -> None:
    registry = WorkerKVRegistry(
        KVRegistryConfig(
            max_entries=1,
            max_bytes=1024,
            default_ttl_s=60,
            pin_memory=False,
        ),
        clock_ns=lambda: 10,
    )
    registry.prepare(_handle("first"), token_ids=(10, 11, 12, 13), expected_layer_count=1)

    assert registry.stats()["registry_entries"] == 1
    assert registry.stats()["registry_peak_entries"] == 1
    with pytest.raises(KVRegistryError, match="kv_registry_capacity_exceeded"):
        registry.prepare(
            _handle("second"),
            token_ids=(10, 11, 12, 13),
            expected_layer_count=1,
        )


def test_registry_commit_consume_proof_and_release() -> None:
    registry = WorkerKVRegistry(
        KVRegistryConfig(
            max_entries=2,
            max_bytes=4096,
            default_ttl_s=60,
            pin_memory=False,
        ),
        clock_ns=lambda: 10,
    )
    handle = _handle()
    registry.prepare(handle, token_ids=(10, 11, 12, 13), expected_layer_count=2)
    registry.put_layer(handle.handle_id, "layer-0", (torch.ones((2, 4, 1)),))
    registry.put_layer(handle.handle_id, "layer-1", (torch.ones((2, 4, 1)),))
    committed = registry.commit(handle.handle_id, store_ms=1.25)

    assert committed.status == KVHandleStatus.READY
    assert committed.layer_count == 2
    assert committed.kv_bytes_actual == 64
    assert registry.store_ms(handle.handle_id) == pytest.approx(1.25)

    registry.begin_consume(
        handle.handle_id,
        request_id="consume-1",
        task_id=handle.task_id,
        token_digest=handle.token_digest,
        engine_generation=handle.engine_generation,
    )
    proof = _proof(committed)
    consumed = registry.finish_consume(proof)

    assert consumed.status == KVHandleStatus.CONSUMED
    assert registry.forward_proof(handle.handle_id) == proof
    with pytest.raises(KVRegistryError, match="kv_ref_already_consumed"):
        registry.begin_consume(
            handle.handle_id,
            request_id="consume-2",
            task_id=handle.task_id,
            token_digest=handle.token_digest,
            engine_generation=handle.engine_generation,
        )
    assert registry.release(handle.handle_id).status == KVHandleStatus.RELEASED
    assert registry.release(handle.handle_id).status == KVHandleStatus.RELEASED
    assert registry.stats()["registry_entries"] == 0
    assert registry.stats()["registry_bytes"] == 0


def test_forward_proof_rejects_decorative_or_inconsistent_accounting() -> None:
    committed = replace(_handle(), kv_bytes_actual=64, layer_count=2)
    valid = _proof(committed)

    with pytest.raises(ValueError, match="token accounting"):
        replace(valid, computed_prefill_tokens=6)
    with pytest.raises(ValueError, match="mechanism evidence"):
        replace(valid, connector_load_count=0)


def test_combined_and_split_paged_cache_slot_roundtrip() -> None:
    source = torch.arange(2 * 4 * 2 * 3, dtype=torch.float32).reshape(2, 4, 2, 3)
    source_slots = make_slot_mapping((2, 0), seq_len=4, block_size=2)
    destination_slots = make_slot_mapping((1, 3), seq_len=4, block_size=2)
    captured = extract_kv_slots(source, source_slots)
    destination = torch.zeros_like(source)

    inject_kv_slots(destination, destination_slots, captured)

    assert torch.equal(extract_kv_slots(destination, destination_slots)[0], captured[0])
    split_source = [source[0].clone(), source[1].clone()]
    split_destination = [torch.zeros_like(split_source[0]), torch.zeros_like(split_source[1])]
    split_captured = extract_kv_slots(split_source, source_slots)
    inject_kv_slots(split_destination, destination_slots, split_captured)
    observed = extract_kv_slots(split_destination, destination_slots)
    assert all(
        torch.equal(actual, expected)
        for actual, expected in zip(observed, split_captured, strict=True)
    )


def _connector_config() -> SimpleNamespace:
    return SimpleNamespace(
        cache_config=SimpleNamespace(block_size=2),
        model_config=SimpleNamespace(
            hf_config=SimpleNamespace(num_hidden_layers=2),
        ),
    )


def test_connector_copies_real_slots_and_commits_worker_forward_proof() -> None:
    registry = reset_worker_registry_for_tests(
        KVRegistryConfig(
            max_entries=2,
            max_bytes=4096,
            default_ttl_s=60,
            pin_memory=False,
        ),
        clock_ns=lambda: 10,
    )
    token_ids = (10, 11, 12, 13)
    handle = _handle(token_ids=token_ids)
    registry.prepare(handle, token_ids=token_ids, expected_layer_count=2)
    source_slots = make_slot_mapping((2, 0), seq_len=4, block_size=2)
    store_meta = KVRequestMetadata(
        request_id="produce-1",
        action="store",
        handle_id=handle.handle_id,
        task_id=handle.task_id,
        token_digest=handle.token_digest,
        prefix_len=4,
        logical_prompt_tokens=6,
        suffix_tokens=2,
        block_size=2,
        block_ids=(2, 0, 1),
    )
    connector = StateBusLocalKVConnector(_connector_config(), KVConnectorRole.WORKER)
    connector._connector_metadata = StateBusLocalKVConnectorMetadata([store_meta])
    connector.start_load_kv(SimpleNamespace())
    layer_0 = torch.arange(2 * 4 * 2, dtype=torch.float32).reshape(2, 4, 2, 1)
    layer_1 = layer_0 + 100
    connector.save_kv_layer("layer-0", layer_0, None)
    connector.save_kv_layer("layer-1", layer_1, None)
    connector.wait_for_save()

    committed = registry.describe(handle.handle_id)
    assert committed.status == KVHandleStatus.READY
    assert committed.layer_count == 2
    assert committed.kv_bytes_actual == 64
    registry.begin_consume(
        handle.handle_id,
        request_id="consume-1",
        task_id=handle.task_id,
        token_digest=handle.token_digest,
        engine_generation=handle.engine_generation,
    )

    destination_0 = torch.zeros_like(layer_0)
    destination_1 = torch.zeros_like(layer_1)
    load_meta = replace(
        store_meta,
        request_id="consume-1",
        action="load",
        block_ids=(1, 3, 0),
    )
    connector._connector_metadata = StateBusLocalKVConnectorMetadata([load_meta])
    forward_context = SimpleNamespace(
        virtual_engine=0,
        no_compile_layers={
            "layer-0": SimpleNamespace(kv_cache=[destination_0]),
            "layer-1": SimpleNamespace(kv_cache=[destination_1]),
        },
    )
    connector.start_load_kv(forward_context)
    connector.wait_for_save()

    destination_slots = load_meta.slot_mapping
    assert torch.equal(
        extract_kv_slots(destination_0, destination_slots)[0],
        extract_kv_slots(layer_0, source_slots)[0],
    )
    assert torch.equal(
        extract_kv_slots(destination_1, destination_slots)[0],
        extract_kv_slots(layer_1, source_slots)[0],
    )
    proof = registry.forward_proof(handle.handle_id)
    assert proof is not None
    assert proof.inherited_kv_tokens == 4
    assert proof.computed_prefill_tokens == 2
    assert proof.connector_load_count == 1
    assert registry.describe(handle.handle_id).status == KVHandleStatus.CONSUMED


def test_scheduler_marks_only_explicit_load_prefix_as_external() -> None:
    reset_worker_registry_for_tests(
        KVRegistryConfig(pin_memory=False),
    )
    connector = StateBusLocalKVConnector(_connector_config(), KVConnectorRole.SCHEDULER)
    parent = (10, 11, 12, 13)
    prompt = parent + (20, 21)
    params = {
        "action": "load",
        "handle_id": "kv-load",
        "task_id": "task-1",
        "token_digest": sha256_digest(list(parent)),
        "prefix_len": len(parent),
    }
    request = SimpleNamespace(
        request_id="consume-1",
        prompt_token_ids=list(prompt),
        kv_transfer_params=params,
    )
    matched, asynchronous = connector.get_num_new_matched_tokens(request, 0)
    connector.update_state_after_alloc(
        request,
        SimpleNamespace(get_block_ids=lambda: ([1, 2, 3],)),
        matched,
    )
    new_request = SimpleNamespace(
        req_id=request.request_id,
        prompt_token_ids=list(prompt),
        sampling_params=SimpleNamespace(
            extra_args={"kv_transfer_params": params}
        ),
        block_ids=([1, 2, 3],),
        num_computed_tokens=matched,
    )
    scheduler_output = SimpleNamespace(
        scheduled_new_reqs=[new_request],
        scheduled_cached_reqs=SimpleNamespace(
            req_ids=[],
            new_block_ids=[],
            resumed_from_preemption=[],
            num_computed_tokens=[],
        ),
        num_scheduled_tokens={request.request_id: 2},
    )
    metadata = connector.build_connector_meta(scheduler_output)

    assert matched == 4
    assert asynchronous is False
    assert len(metadata.requests) == 1
    assert metadata.requests[0].action == "load"
    assert metadata.requests[0].suffix_tokens == 2
    assert metadata.requests[0].slot_mapping == (2, 3, 4, 5)
