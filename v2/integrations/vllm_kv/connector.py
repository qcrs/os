from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Mapping, Optional

from v2.contracts import KVForwardProof
from v2.integrations.vllm_kv.paged_cache import (
    PagedKVLayoutError,
    extract_kv_slots,
    inject_kv_slots,
    layer_tensor_nbytes,
    make_slot_mapping,
)
from v2.integrations.vllm_kv.registry import KVRegistryError, get_worker_registry
from v2.utils import sha256_digest

try:
    from vllm.distributed.kv_transfer.kv_connector.v1.base import (
        KVConnectorBase_V1,
        KVConnectorMetadata,
        KVConnectorRole,
    )
except ImportError:  # Keep scheduler/metadata tests runnable in the CPU container.
    class KVConnectorMetadata:
        pass

    class KVConnectorBase_V1:
        def __init__(self, vllm_config: Any, role: Any) -> None:
            self._vllm_config = vllm_config
            self._role = role
            self._connector_metadata = KVConnectorMetadata()

        def _get_connector_metadata(self) -> Any:
            return self._connector_metadata

    class KVConnectorRole:
        SCHEDULER = "scheduler"
        WORKER = "worker"


if TYPE_CHECKING:
    from vllm.attention.backends.abstract import AttentionMetadata
    from vllm.config import VllmConfig
    from vllm.forward_context import ForwardContext
    from vllm.v1.core.kv_cache_manager import KVCacheBlocks
    from vllm.v1.core.sched.output import SchedulerOutput
    from vllm.v1.request import Request
else:
    VllmConfig = Any
    ForwardContext = Any
    AttentionMetadata = Any
    KVCacheBlocks = Any
    SchedulerOutput = Any
    Request = Any


logger = logging.getLogger(__name__)
CONNECTOR_VERSION = "statebus.vllm_kv.connector.v1"
STORE_ACTION = "store"
LOAD_ACTION = "load"


class KVConnectorProtocolError(RuntimeError):
    def __init__(self, error_code: str, detail: str = "") -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class KVRequestMetadata:
    request_id: str
    action: str
    handle_id: str
    task_id: str
    token_digest: str
    prefix_len: int
    logical_prompt_tokens: int
    suffix_tokens: int
    block_size: int
    block_ids: tuple[int, ...]

    @property
    def slot_mapping(self) -> tuple[int, ...]:
        return make_slot_mapping(
            self.block_ids,
            seq_len=self.prefix_len,
            block_size=self.block_size,
        )


@dataclass
class StateBusLocalKVConnectorMetadata(KVConnectorMetadata):
    requests: list[KVRequestMetadata] = field(default_factory=list)


@dataclass
class _WorkerTransfer:
    metadata: KVRequestMetadata
    elapsed_ms: float = 0.0
    layer_count: int = 0
    byte_count: int = 0


class StateBusLocalKVConnector(KVConnectorBase_V1):
    """Explicit, one-shot KV continuation for a single local vLLM worker."""

    def __init__(self, vllm_config: VllmConfig, role: KVConnectorRole):
        super().__init__(vllm_config=vllm_config, role=role)
        self._block_size = int(vllm_config.cache_config.block_size)
        self._expected_layer_count = _configured_layer_count(vllm_config)
        self._scheduler_params: dict[str, dict[str, Any]] = {}
        self._scheduler_blocks: dict[str, list[int]] = {}
        self._requests_need_load: set[str] = set()
        self._active_stores: dict[str, _WorkerTransfer] = {}
        self._active_loads: dict[str, _WorkerTransfer] = {}
        self._pin_memory = get_worker_registry().config.pin_memory
        logger.info(
            "StateBus local KV connector initialized role=%s block_size=%d layers=%d",
            _role_name(role),
            self._block_size,
            self._expected_layer_count,
        )

    # Worker-side methods.
    def start_load_kv(self, forward_context: ForwardContext, **kwargs: Any) -> None:
        del kwargs
        metadata = self._get_connector_metadata()
        if not isinstance(metadata, StateBusLocalKVConnectorMetadata):
            raise KVConnectorProtocolError("kv_request_invalid", "connector_metadata")
        self._active_stores.clear()
        self._active_loads.clear()
        for request in metadata.requests:
            transfer = _WorkerTransfer(metadata=request)
            if request.action == STORE_ACTION:
                self._active_stores[request.handle_id] = transfer
                continue
            if request.action != LOAD_ACTION:
                raise KVConnectorProtocolError("kv_request_invalid", "action")
            self._load_request(forward_context, transfer)
            self._active_loads[request.handle_id] = transfer

    def wait_for_layer_load(self, layer_name: str) -> None:
        del layer_name
        return

    def save_kv_layer(
        self,
        layer_name: str,
        kv_layer: Any,
        attn_metadata: AttentionMetadata,
        **kwargs: Any,
    ) -> None:
        del attn_metadata, kwargs
        if not self._active_stores:
            return
        registry = get_worker_registry()
        for transfer in self._active_stores.values():
            started = time.perf_counter_ns()
            try:
                extracted = extract_kv_slots(
                    kv_layer,
                    transfer.metadata.slot_mapping,
                )
                host_tensors = tuple(
                    _copy_to_host(value, pin_memory=self._pin_memory)
                    for value in extracted
                )
                _synchronize_if_cuda(kv_layer)
                byte_count = layer_tensor_nbytes(host_tensors)
                registry.put_layer(
                    transfer.metadata.handle_id,
                    layer_name,
                    host_tensors,
                    byte_count=byte_count,
                )
            except (KVRegistryError, PagedKVLayoutError) as exc:
                raise KVConnectorProtocolError(
                    getattr(exc, "error_code", "kv_capture_incomplete"),
                    getattr(exc, "detail", str(exc)),
                ) from exc
            transfer.elapsed_ms += (time.perf_counter_ns() - started) / 1_000_000.0
            transfer.layer_count += 1
            transfer.byte_count += byte_count

    def wait_for_save(self) -> None:
        registry = get_worker_registry()
        for transfer in self._active_stores.values():
            try:
                registry.commit(
                    transfer.metadata.handle_id,
                    store_ms=transfer.elapsed_ms,
                )
            except KVRegistryError as exc:
                raise KVConnectorProtocolError(exc.error_code, exc.detail) from exc
        for transfer in self._active_loads.values():
            request = transfer.metadata
            try:
                handle = registry.describe(request.handle_id)
                proof = KVForwardProof(
                    handle_id=request.handle_id,
                    request_id=request.request_id,
                    task_id=request.task_id,
                    engine_id=handle.engine_id,
                    engine_generation=handle.engine_generation,
                    token_digest=request.token_digest,
                    inherited_kv_tokens=request.prefix_len,
                    computed_prefill_tokens=request.suffix_tokens,
                    logical_prompt_tokens=request.logical_prompt_tokens,
                    suffix_tokens=request.suffix_tokens,
                    layer_count=transfer.layer_count,
                    kv_bytes_actual=transfer.byte_count,
                    connector_load_count=1,
                    kv_load_ms=transfer.elapsed_ms,
                    worker_pid=os.getpid(),
                    observed_at_ns=time.time_ns(),
                )
                registry.finish_consume(proof)
            except KVRegistryError as exc:
                raise KVConnectorProtocolError(exc.error_code, exc.detail) from exc

    # Scheduler-side methods.
    def get_num_new_matched_tokens(
        self,
        request: Request,
        num_computed_tokens: int,
    ) -> tuple[int, bool]:
        params = _validated_request_params(request, block_size=self._block_size)
        if params is None:
            return 0, False
        request_id = str(request.request_id)
        self._scheduler_params[request_id] = params
        if params["action"] != LOAD_ACTION:
            return 0, False
        if num_computed_tokens != 0:
            raise KVConnectorProtocolError(
                "kv_request_invalid", "local_prefix_cache_must_be_disabled"
            )
        self._requests_need_load.add(request_id)
        return int(params["prefix_len"]), False

    def update_state_after_alloc(
        self,
        request: Request,
        blocks: KVCacheBlocks,
        num_external_tokens: int,
    ) -> None:
        params = self._scheduler_params.get(str(request.request_id))
        if params is None:
            return
        block_ids = _first_block_group(blocks.get_block_ids())
        self._scheduler_blocks[str(request.request_id)] = list(block_ids)
        if params["action"] == LOAD_ACTION and num_external_tokens != int(
            params["prefix_len"]
        ):
            raise KVConnectorProtocolError("kv_consumer_forward_not_observed")

    def build_connector_meta(
        self,
        scheduler_output: SchedulerOutput,
    ) -> KVConnectorMetadata:
        result = StateBusLocalKVConnectorMetadata()
        for new_request in scheduler_output.scheduled_new_reqs:
            request_id = str(new_request.req_id)
            params = self._scheduler_params.get(request_id)
            if params is None:
                params = _params_from_sampling(getattr(new_request, "sampling_params", None))
                if params is None:
                    continue
                params = _validate_params_against_tokens(
                    params,
                    tuple(int(value) for value in new_request.prompt_token_ids),
                    block_size=self._block_size,
                )
                self._scheduler_params[request_id] = params
            block_ids = _first_block_group(new_request.block_ids)
            self._scheduler_blocks[request_id] = list(block_ids)
            scheduled = int(scheduler_output.num_scheduled_tokens[request_id])
            end_computed = int(new_request.num_computed_tokens) + scheduled
            if params["action"] == LOAD_ACTION:
                if request_id not in self._requests_need_load:
                    raise KVConnectorProtocolError(
                        "kv_consumer_forward_not_observed", "load_not_matched"
                    )
                if (
                    int(new_request.num_computed_tokens) != int(params["prefix_len"])
                    or scheduled != int(params["suffix_tokens"])
                ):
                    raise KVConnectorProtocolError(
                        "kv_consumer_forward_not_observed",
                        "scheduler_token_accounting",
                    )
                result.requests.append(
                    _metadata_from_params(request_id, params, block_ids, self._block_size)
                )
                self._requests_need_load.discard(request_id)
            elif end_computed >= int(params["prefix_len"]):
                result.requests.append(
                    _metadata_from_params(request_id, params, block_ids, self._block_size)
                )
                self._scheduler_params.pop(request_id, None)
                self._scheduler_blocks.pop(request_id, None)

        cached = scheduler_output.scheduled_cached_reqs
        for index, request_id_value in enumerate(cached.req_ids):
            request_id = str(request_id_value)
            params = self._scheduler_params.get(request_id)
            if params is None or params["action"] != STORE_ACTION:
                continue
            current = self._scheduler_blocks.setdefault(request_id, [])
            new_groups = cached.new_block_ids[index]
            new_ids = list(_first_block_group(new_groups))
            if bool(cached.resumed_from_preemption[index]):
                current[:] = new_ids
            else:
                current.extend(value for value in new_ids if value not in current)
            start_computed = int(cached.num_computed_tokens[index])
            scheduled = int(scheduler_output.num_scheduled_tokens[request_id])
            if start_computed + scheduled >= int(params["prefix_len"]):
                result.requests.append(
                    _metadata_from_params(request_id, params, tuple(current), self._block_size)
                )
                self._scheduler_params.pop(request_id, None)
                self._scheduler_blocks.pop(request_id, None)
        return result

    def request_finished(
        self,
        request: Request,
        block_ids: list[int],
    ) -> tuple[bool, Optional[dict[str, Any]]]:
        del block_ids
        request_id = str(request.request_id)
        params = _params_from_request(request)
        self._scheduler_params.pop(request_id, None)
        self._scheduler_blocks.pop(request_id, None)
        self._requests_need_load.discard(request_id)
        if params is None:
            return False, None
        prefix_len = int(params.get("prefix_len", 0))
        logical = len(tuple(int(value) for value in request.prompt_token_ids))
        return False, {
            "statebus_kv": {
                "connector_version": CONNECTOR_VERSION,
                "action": str(params.get("action", "")),
                "handle_id": str(params.get("handle_id", "")),
                "logical_prompt_tokens": logical,
                "inherited_kv_tokens": prefix_len
                if params.get("action") == LOAD_ACTION
                else 0,
                "computed_prefill_tokens": logical - prefix_len
                if params.get("action") == LOAD_ACTION
                else logical,
            }
        }

    def _load_request(
        self,
        forward_context: ForwardContext,
        transfer: _WorkerTransfer,
    ) -> None:
        request = transfer.metadata
        registry = get_worker_registry()
        started = time.perf_counter_ns()
        try:
            layers = getattr(forward_context, "no_compile_layers", None)
            if not isinstance(layers, Mapping) or not layers:
                raise KVConnectorProtocolError(
                    "kv_consumer_forward_not_observed", "attention_layers_unavailable"
                )
            virtual_engine = int(getattr(forward_context, "virtual_engine", 0))
            for layer_name, attention_layer in layers.items():
                caches = getattr(attention_layer, "kv_cache", None)
                if not isinstance(caches, (list, tuple)) or virtual_engine >= len(caches):
                    raise KVConnectorProtocolError(
                        "kv_consumer_forward_not_observed", "paged_cache_unavailable"
                    )
                destination = caches[virtual_engine]
                source = registry.layer_tensors(
                    request.handle_id,
                    str(layer_name),
                    request_id=request.request_id,
                )
                inject_kv_slots(destination, request.slot_mapping, source)
                transfer.layer_count += 1
                transfer.byte_count += layer_tensor_nbytes(source)
            _synchronize_if_cuda(next(iter(layers.values())).kv_cache[virtual_engine])
        except (KVRegistryError, PagedKVLayoutError) as exc:
            raise KVConnectorProtocolError(
                getattr(exc, "error_code", "kv_consumer_forward_not_observed"),
                getattr(exc, "detail", str(exc)),
            ) from exc
        transfer.elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0


def _validated_request_params(request: Request, *, block_size: int) -> dict[str, Any] | None:
    params = _params_from_request(request)
    if params is None:
        return None
    tokens = tuple(int(value) for value in request.prompt_token_ids)
    return _validate_params_against_tokens(params, tokens, block_size=block_size)


def _validate_params_against_tokens(
    params: Mapping[str, Any],
    token_ids: tuple[int, ...],
    *,
    block_size: int,
) -> dict[str, Any]:
    action = str(params.get("action", ""))
    handle_id = str(params.get("handle_id", ""))
    task_id = str(params.get("task_id", ""))
    token_digest = str(params.get("token_digest", ""))
    prefix_len = int(params.get("prefix_len", 0))
    if action not in {STORE_ACTION, LOAD_ACTION} or not handle_id or not task_id:
        raise KVConnectorProtocolError("kv_request_invalid", "transfer_params")
    if prefix_len <= 0 or prefix_len % block_size or prefix_len >= len(token_ids):
        raise KVConnectorProtocolError("kv_request_invalid", "prefix_len")
    observed_digest = sha256_digest(list(token_ids[:prefix_len]))
    if token_digest != observed_digest:
        raise KVConnectorProtocolError("kv_token_mismatch")
    return {
        "action": action,
        "handle_id": handle_id,
        "task_id": task_id,
        "token_digest": token_digest,
        "prefix_len": prefix_len,
        "logical_prompt_tokens": len(token_ids),
        "suffix_tokens": len(token_ids) - prefix_len,
    }


def _metadata_from_params(
    request_id: str,
    params: Mapping[str, Any],
    block_ids: tuple[int, ...] | list[int],
    block_size: int,
) -> KVRequestMetadata:
    return KVRequestMetadata(
        request_id=request_id,
        action=str(params["action"]),
        handle_id=str(params["handle_id"]),
        task_id=str(params["task_id"]),
        token_digest=str(params["token_digest"]),
        prefix_len=int(params["prefix_len"]),
        logical_prompt_tokens=int(params["logical_prompt_tokens"]),
        suffix_tokens=int(params["suffix_tokens"]),
        block_size=block_size,
        block_ids=tuple(int(value) for value in block_ids),
    )


def _params_from_request(request: Request) -> dict[str, Any] | None:
    value = getattr(request, "kv_transfer_params", None)
    return dict(value) if isinstance(value, Mapping) else None


def _params_from_sampling(sampling_params: Any) -> dict[str, Any] | None:
    extra = getattr(sampling_params, "extra_args", None)
    if not isinstance(extra, Mapping):
        return None
    value = extra.get("kv_transfer_params")
    return dict(value) if isinstance(value, Mapping) else None


def _first_block_group(value: Any) -> tuple[int, ...]:
    if not isinstance(value, (tuple, list)) or not value:
        raise KVConnectorProtocolError("kv_request_invalid", "block_ids")
    first = value[0]
    if not isinstance(first, (tuple, list)):
        raise KVConnectorProtocolError("kv_request_invalid", "block_ids")
    return tuple(int(item) for item in first)


def _configured_layer_count(vllm_config: Any) -> int:
    hf_config = getattr(getattr(vllm_config, "model_config", None), "hf_config", None)
    return int(
        getattr(hf_config, "num_hidden_layers", getattr(hf_config, "num_layers", 0))
        or 0
    )


def _copy_to_host(value: Any, *, pin_memory: bool) -> Any:
    torch = _torch_module()
    if str(getattr(value, "device", "cpu")).startswith("cpu"):
        result = value.detach().contiguous().clone()
        return result.pin_memory() if pin_memory and torch.cuda.is_available() else result
    host = torch.empty_like(value, device="cpu", pin_memory=pin_memory)
    host.copy_(value.detach(), non_blocking=pin_memory)
    return host


def _synchronize_if_cuda(value: Any) -> None:
    torch = _torch_module()
    tensors = value if isinstance(value, (tuple, list)) else (value,)
    if any(str(getattr(item, "device", "cpu")).startswith("cuda") for item in tensors):
        torch.cuda.synchronize()


def _torch_module() -> Any:
    import torch

    return torch


def _role_name(role: Any) -> str:
    return str(getattr(role, "name", getattr(role, "value", role))).lower()


__all__ = [
    "CONNECTOR_VERSION",
    "KVConnectorProtocolError",
    "KVRequestMetadata",
    "StateBusLocalKVConnector",
    "StateBusLocalKVConnectorMetadata",
]
