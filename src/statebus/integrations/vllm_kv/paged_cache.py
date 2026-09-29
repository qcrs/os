from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class PagedKVLayoutError(ValueError):
    pass


def make_slot_mapping(
    block_ids: Sequence[int],
    *,
    seq_len: int,
    block_size: int,
) -> tuple[int, ...]:
    if seq_len <= 0 or block_size <= 0 or seq_len % block_size:
        raise PagedKVLayoutError("sequence length must be positive and block aligned")
    required_blocks = seq_len // block_size
    resolved_blocks = tuple(int(value) for value in block_ids)
    if len(resolved_blocks) < required_blocks or any(value < 0 for value in resolved_blocks):
        raise PagedKVLayoutError("insufficient or invalid block ids")
    return tuple(
        block_id * block_size + offset
        for block_id in resolved_blocks[:required_blocks]
        for offset in range(block_size)
    )


def extract_kv_slots(kv_layer: Any, slot_mapping: Sequence[int]) -> tuple[Any, ...]:
    """Extract logical token slots while preserving the backend's KV layout."""

    tensors, combined = _normalize_layer(kv_layer)
    slots = tuple(int(value) for value in slot_mapping)
    if not slots:
        raise PagedKVLayoutError("slot mapping cannot be empty")
    return tuple(_extract_tensor(tensor, slots, combined=combined) for tensor in tensors)


def inject_kv_slots(
    kv_layer: Any,
    slot_mapping: Sequence[int],
    source_tensors: Sequence[Any],
) -> None:
    """Inject logical token slots into newly allocated paged-cache blocks."""

    tensors, combined = _normalize_layer(kv_layer)
    sources = tuple(source_tensors)
    slots = tuple(int(value) for value in slot_mapping)
    if len(tensors) != len(sources) or not slots:
        raise PagedKVLayoutError("source tensors do not match the destination layout")
    for destination, source in zip(tensors, sources, strict=True):
        _inject_tensor(destination, source, slots, combined=combined)


def layer_tensor_nbytes(tensors: Sequence[Any]) -> int:
    total = 0
    for tensor in tensors:
        element_size = getattr(tensor, "element_size", None)
        numel = getattr(tensor, "numel", None)
        if not callable(element_size) or not callable(numel):
            raise PagedKVLayoutError("tensor byte size is unavailable")
        total += int(element_size()) * int(numel())
    return total


def _normalize_layer(kv_layer: Any) -> tuple[tuple[Any, ...], bool]:
    if _is_tensor(kv_layer):
        shape = tuple(int(value) for value in kv_layer.shape)
        if len(shape) < 2:
            raise PagedKVLayoutError("paged KV tensor rank is too small")
        combined = len(shape) >= 3 and shape[0] == 2
        return (kv_layer,), combined
    if isinstance(kv_layer, (tuple, list)) and kv_layer and all(
        _is_tensor(value) for value in kv_layer
    ):
        return tuple(kv_layer), False
    raise PagedKVLayoutError("unsupported paged KV layer representation")


def _extract_tensor(tensor: Any, slots: tuple[int, ...], *, combined: bool) -> Any:
    torch = _torch_module()
    index = torch.tensor(slots, dtype=torch.long, device=tensor.device)
    shape = tuple(int(value) for value in tensor.shape)
    if combined:
        if len(shape) < 3:
            raise PagedKVLayoutError("combined KV tensor rank is too small")
        flattened = tensor.reshape(shape[0], shape[1] * shape[2], *shape[3:])
        if max(slots) >= flattened.shape[1]:
            raise PagedKVLayoutError("slot mapping exceeds combined KV capacity")
        return flattened.index_select(1, index).contiguous()
    if len(shape) < 2:
        raise PagedKVLayoutError("split KV tensor rank is too small")
    flattened = tensor.reshape(shape[0] * shape[1], *shape[2:])
    if max(slots) >= flattened.shape[0]:
        raise PagedKVLayoutError("slot mapping exceeds KV capacity")
    return flattened.index_select(0, index).contiguous()


def _inject_tensor(
    destination: Any,
    source: Any,
    slots: tuple[int, ...],
    *,
    combined: bool,
) -> None:
    torch = _torch_module()
    index = torch.tensor(slots, dtype=torch.long, device=destination.device)
    shape = tuple(int(value) for value in destination.shape)
    source = source.to(device=destination.device, dtype=destination.dtype)
    if combined:
        flattened = destination.reshape(shape[0], shape[1] * shape[2], *shape[3:])
        expected = (shape[0], len(slots), *shape[3:])
        if tuple(int(value) for value in source.shape) != expected:
            raise PagedKVLayoutError("combined source tensor shape mismatch")
        flattened.index_copy_(1, index, source)
        return
    flattened = destination.reshape(shape[0] * shape[1], *shape[2:])
    expected = (len(slots), *shape[2:])
    if tuple(int(value) for value in source.shape) != expected:
        raise PagedKVLayoutError("source tensor shape mismatch")
    flattened.index_copy_(0, index, source)


def _is_tensor(value: Any) -> bool:
    return hasattr(value, "shape") and callable(getattr(value, "reshape", None))


def _torch_module() -> Any:
    try:
        import torch
    except ImportError as exc:
        raise PagedKVLayoutError("torch is required for paged KV operations") from exc
    return torch
