from __future__ import annotations

from dataclasses import dataclass, replace
import os
import threading
import time
from typing import Any, Callable

from statebus.contracts import EngineLocalKVHandle, KVForwardProof, KVHandleStatus


class KVRegistryError(RuntimeError):
    def __init__(self, error_code: str, detail: str = "") -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class KVRegistryConfig:
    max_entries: int = 2
    max_bytes: int = 2 * 1024 * 1024 * 1024
    default_ttl_s: int = 120
    one_shot: bool = True
    pin_memory: bool = True

    def __post_init__(self) -> None:
        if self.max_entries <= 0 or self.max_bytes <= 0 or self.default_ttl_s <= 0:
            raise ValueError("KV registry limits must be positive")

    @classmethod
    def from_env(cls) -> "KVRegistryConfig":
        return cls(
            max_entries=int(os.environ.get("STATEBUS_KV_REGISTRY_MAX_ENTRIES", "2")),
            max_bytes=int(
                os.environ.get(
                    "STATEBUS_KV_REGISTRY_MAX_BYTES", str(2 * 1024 * 1024 * 1024)
                )
            ),
            default_ttl_s=int(os.environ.get("STATEBUS_KV_TTL_S", "120")),
            one_shot=os.environ.get("STATEBUS_KV_ONE_SHOT", "true").lower()
            in {"1", "true", "yes", "on"},
            pin_memory=os.environ.get("STATEBUS_KV_PIN_MEMORY", "true").lower()
            in {"1", "true", "yes", "on"},
        )


@dataclass
class _KVEntry:
    handle: EngineLocalKVHandle
    token_ids: tuple[int, ...]
    expected_layer_count: int
    layer_tensors: dict[str, tuple[Any, ...]]
    layer_bytes: dict[str, int]
    last_access_ns: int
    consume_request_id: str = ""
    forward_proof: KVForwardProof | None = None
    store_ms: float = 0.0
    rejection_reason: str = ""

    @property
    def byte_count(self) -> int:
        return sum(self.layer_bytes.values())


class WorkerKVRegistry:
    """Bounded worker-local storage for explicit, one-shot KV handles."""

    def __init__(
        self,
        config: KVRegistryConfig | None = None,
        *,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.config = config or KVRegistryConfig.from_env()
        self.clock_ns = clock_ns
        self._entries: dict[str, _KVEntry] = {}
        self._lock = threading.RLock()
        self._peak_entries = 0
        self._peak_bytes = 0
        self._store_count = 0
        self._load_count = 0

    def prepare(
        self,
        handle: EngineLocalKVHandle,
        *,
        token_ids: tuple[int, ...] | list[int],
        expected_layer_count: int,
    ) -> EngineLocalKVHandle:
        resolved_tokens = tuple(int(value) for value in token_ids)
        if len(resolved_tokens) != handle.seq_len:
            raise KVRegistryError("kv_request_invalid", "token_count")
        if expected_layer_count <= 0:
            raise KVRegistryError("kv_request_invalid", "expected_layer_count")
        with self._lock:
            self._sweep_expired_locked()
            if handle.handle_id in self._entries:
                existing = self._entries[handle.handle_id]
                if (
                    existing.handle.token_digest == handle.token_digest
                    and existing.handle.producer_request_id == handle.producer_request_id
                ):
                    return existing.handle
                raise KVRegistryError("kv_request_invalid", "duplicate_handle")
            self._make_entry_capacity_locked()
            now = self.clock_ns()
            prepared = replace(
                handle,
                status=KVHandleStatus.PREPARING,
                kv_bytes_actual=0,
                layer_count=0,
            )
            self._entries[handle.handle_id] = _KVEntry(
                handle=prepared,
                token_ids=resolved_tokens,
                expected_layer_count=expected_layer_count,
                layer_tensors={},
                layer_bytes={},
                last_access_ns=now,
            )
            self._update_peaks_locked()
            return prepared

    def put_layer(
        self,
        handle_id: str,
        layer_name: str,
        tensors: tuple[Any, ...] | list[Any],
        *,
        byte_count: int | None = None,
    ) -> None:
        values = tuple(tensors)
        if not layer_name or not values:
            raise KVRegistryError("kv_request_invalid", "layer_payload")
        resolved_bytes = (
            int(byte_count)
            if byte_count is not None
            else sum(_tensor_nbytes(value) for value in values)
        )
        if resolved_bytes <= 0:
            raise KVRegistryError("kv_capture_incomplete", "layer_bytes")
        with self._lock:
            entry = self._live_entry_locked(handle_id)
            if entry.handle.status != KVHandleStatus.PREPARING:
                raise KVRegistryError("kv_request_invalid", "handle_not_preparing")
            old_bytes = entry.layer_bytes.get(layer_name, 0)
            additional_bytes = resolved_bytes - old_bytes
            if additional_bytes > 0:
                self._make_byte_capacity_locked(additional_bytes, exclude=handle_id)
            entry.layer_tensors[layer_name] = values
            entry.layer_bytes[layer_name] = resolved_bytes
            entry.last_access_ns = self.clock_ns()
            self._update_peaks_locked()

    def commit(self, handle_id: str, *, store_ms: float) -> EngineLocalKVHandle:
        with self._lock:
            entry = self._live_entry_locked(handle_id)
            if entry.handle.status == KVHandleStatus.READY:
                return entry.handle
            if entry.handle.status != KVHandleStatus.PREPARING:
                raise KVRegistryError("kv_request_invalid", "handle_not_preparing")
            if len(entry.layer_tensors) != entry.expected_layer_count:
                self._invalidate_locked(entry, "layer_count")
                raise KVRegistryError("kv_capture_incomplete", "layer_count")
            if entry.byte_count <= 0:
                self._invalidate_locked(entry, "empty_kv")
                raise KVRegistryError("kv_capture_incomplete", "empty_kv")
            entry.handle = replace(
                entry.handle,
                status=KVHandleStatus.READY,
                kv_bytes_actual=entry.byte_count,
                layer_count=len(entry.layer_tensors),
            )
            entry.store_ms = max(0.0, float(store_ms))
            entry.last_access_ns = self.clock_ns()
            self._store_count += 1
            self._update_peaks_locked()
            return entry.handle

    def begin_consume(
        self,
        handle_id: str,
        *,
        request_id: str,
        task_id: str,
        token_digest: str,
        engine_generation: str,
    ) -> EngineLocalKVHandle:
        if not request_id:
            raise KVRegistryError("kv_request_invalid", "request_id")
        with self._lock:
            entry = self._live_entry_locked(handle_id)
            if entry.handle.status == KVHandleStatus.CONSUMED:
                raise KVRegistryError("kv_ref_already_consumed")
            if entry.handle.status != KVHandleStatus.READY:
                raise KVRegistryError("kv_request_invalid", "handle_not_ready")
            if entry.handle.task_id != task_id:
                raise KVRegistryError("kv_task_mismatch")
            if entry.handle.token_digest != token_digest:
                raise KVRegistryError("kv_token_mismatch")
            if entry.handle.engine_generation != engine_generation:
                raise KVRegistryError("kv_model_incompatible", "engine_generation")
            entry.handle = replace(entry.handle, status=KVHandleStatus.CONSUMING)
            entry.consume_request_id = request_id
            entry.last_access_ns = self.clock_ns()
            return entry.handle

    def layer_tensors(
        self,
        handle_id: str,
        layer_name: str,
        *,
        request_id: str,
    ) -> tuple[Any, ...]:
        with self._lock:
            entry = self._live_entry_locked(handle_id)
            if (
                entry.handle.status != KVHandleStatus.CONSUMING
                or entry.consume_request_id != request_id
            ):
                raise KVRegistryError("kv_request_invalid", "consume_binding")
            try:
                values = entry.layer_tensors[layer_name]
            except KeyError as exc:
                raise KVRegistryError("kv_capture_incomplete", "layer_missing") from exc
            entry.last_access_ns = self.clock_ns()
            return values

    def finish_consume(self, proof: KVForwardProof) -> EngineLocalKVHandle:
        with self._lock:
            entry = self._live_entry_locked(proof.handle_id)
            if (
                entry.handle.status != KVHandleStatus.CONSUMING
                or entry.consume_request_id != proof.request_id
                or entry.handle.task_id != proof.task_id
                or entry.handle.token_digest != proof.token_digest
                or proof.inherited_kv_tokens != entry.handle.seq_len
                or proof.layer_count != entry.handle.layer_count
                or proof.kv_bytes_actual != entry.handle.kv_bytes_actual
                or proof.connector_load_count != 1
            ):
                self._invalidate_locked(entry, "forward_proof")
                raise KVRegistryError("kv_consumer_forward_not_observed")
            entry.forward_proof = proof
            entry.handle = replace(entry.handle, status=KVHandleStatus.CONSUMED)
            entry.last_access_ns = self.clock_ns()
            self._load_count += 1
            return entry.handle

    def abort_consume(self, handle_id: str, reason: str) -> None:
        with self._lock:
            entry = self._entries.get(handle_id)
            if entry is not None:
                self._invalidate_locked(entry, reason or "consume_aborted")

    def describe(self, handle_id: str) -> EngineLocalKVHandle:
        with self._lock:
            entry = self._live_entry_locked(handle_id)
            entry.last_access_ns = self.clock_ns()
            return entry.handle

    def token_ids(self, handle_id: str) -> tuple[int, ...]:
        with self._lock:
            entry = self._live_entry_locked(handle_id)
            return entry.token_ids

    def forward_proof(self, handle_id: str) -> KVForwardProof | None:
        with self._lock:
            entry = self._live_entry_locked(handle_id)
            return entry.forward_proof

    def store_ms(self, handle_id: str) -> float:
        with self._lock:
            return self._live_entry_locked(handle_id).store_ms

    def release(self, handle_id: str) -> EngineLocalKVHandle:
        with self._lock:
            entry = self._entries.get(handle_id)
            if entry is None:
                raise KVRegistryError("kv_ref_not_found")
            if entry.handle.status == KVHandleStatus.RELEASED:
                return entry.handle
            entry.layer_tensors.clear()
            entry.layer_bytes.clear()
            entry.token_ids = ()
            entry.consume_request_id = ""
            entry.handle = replace(entry.handle, status=KVHandleStatus.RELEASED)
            entry.last_access_ns = self.clock_ns()
            return entry.handle

    def sweep_expired(self) -> int:
        with self._lock:
            return self._sweep_expired_locked()

    def stats(self) -> dict[str, int]:
        with self._lock:
            self._sweep_expired_locked()
            live = [
                entry for entry in self._entries.values() if _occupies_registry(entry)
            ]
            return {
                "registry_entries": len(live),
                "registry_bytes": sum(entry.byte_count for entry in live),
                "registry_peak_entries": self._peak_entries,
                "registry_peak_bytes": self._peak_bytes,
                "store_count": self._store_count,
                "load_count": self._load_count,
            }

    def _live_entry_locked(self, handle_id: str) -> _KVEntry:
        entry = self._entries.get(handle_id)
        if entry is None:
            raise KVRegistryError("kv_ref_not_found")
        if (
            entry.handle.status
            not in {
                KVHandleStatus.RELEASED,
                KVHandleStatus.EXPIRED,
                KVHandleStatus.INVALIDATED,
            }
            and self.clock_ns() >= entry.handle.expires_at_ns
        ):
            entry.layer_tensors.clear()
            entry.layer_bytes.clear()
            entry.token_ids = ()
            entry.handle = replace(entry.handle, status=KVHandleStatus.EXPIRED)
        if entry.handle.status == KVHandleStatus.EXPIRED:
            raise KVRegistryError("kv_ref_expired")
        if entry.handle.status in {KVHandleStatus.RELEASED, KVHandleStatus.INVALIDATED}:
            raise KVRegistryError("kv_ref_not_found")
        return entry

    def _sweep_expired_locked(self) -> int:
        now = self.clock_ns()
        count = 0
        for entry in self._entries.values():
            if (
                entry.handle.status
                not in {
                    KVHandleStatus.RELEASED,
                    KVHandleStatus.EXPIRED,
                    KVHandleStatus.INVALIDATED,
                }
                and now >= entry.handle.expires_at_ns
            ):
                entry.layer_tensors.clear()
                entry.layer_bytes.clear()
                entry.token_ids = ()
                entry.handle = replace(entry.handle, status=KVHandleStatus.EXPIRED)
                count += 1
        return count

    def _make_entry_capacity_locked(self) -> None:
        live = [entry for entry in self._entries.values() if _occupies_registry(entry)]
        if len(live) < self.config.max_entries:
            return
        self._evict_one_locked(exclude="")

    def _make_byte_capacity_locked(self, required: int, *, exclude: str) -> None:
        if required > self.config.max_bytes:
            raise KVRegistryError("kv_registry_capacity_exceeded")
        while self._live_bytes_locked() + required > self.config.max_bytes:
            self._evict_one_locked(exclude=exclude)

    def _evict_one_locked(self, *, exclude: str) -> None:
        candidates = sorted(
            (
                entry
                for handle_id, entry in self._entries.items()
                if handle_id != exclude
                and entry.handle.status
                in {KVHandleStatus.READY, KVHandleStatus.CONSUMED}
            ),
            key=lambda entry: (entry.last_access_ns, entry.handle.created_at_ns),
        )
        if not candidates:
            raise KVRegistryError("kv_registry_capacity_exceeded")
        self._invalidate_locked(candidates[0], "capacity_evicted")

    def _invalidate_locked(self, entry: _KVEntry, reason: str) -> None:
        entry.layer_tensors.clear()
        entry.layer_bytes.clear()
        entry.token_ids = ()
        entry.consume_request_id = ""
        entry.rejection_reason = reason
        entry.handle = replace(entry.handle, status=KVHandleStatus.INVALIDATED)
        entry.last_access_ns = self.clock_ns()

    def _live_bytes_locked(self) -> int:
        return sum(entry.byte_count for entry in self._entries.values())

    def _update_peaks_locked(self) -> None:
        live = [entry for entry in self._entries.values() if _occupies_registry(entry)]
        self._peak_entries = max(self._peak_entries, len(live))
        self._peak_bytes = max(
            self._peak_bytes,
            sum(entry.byte_count for entry in live),
        )


def _tensor_nbytes(value: Any) -> int:
    element_size = getattr(value, "element_size", None)
    numel = getattr(value, "numel", None)
    if callable(element_size) and callable(numel):
        return int(element_size()) * int(numel())
    nbytes = getattr(value, "nbytes", None)
    if nbytes is not None:
        return int(nbytes)
    raise KVRegistryError("kv_request_invalid", "tensor_nbytes_unavailable")


def _occupies_registry(entry: _KVEntry) -> bool:
    return entry.handle.status in {
        KVHandleStatus.PREPARING,
        KVHandleStatus.READY,
        KVHandleStatus.CONSUMING,
        KVHandleStatus.CONSUMED,
    }


_WORKER_REGISTRY: WorkerKVRegistry | None = None
_WORKER_REGISTRY_LOCK = threading.Lock()


def get_worker_registry() -> WorkerKVRegistry:
    """Return the process-local registry shared by the worker extension and connector."""

    global _WORKER_REGISTRY
    if _WORKER_REGISTRY is None:
        with _WORKER_REGISTRY_LOCK:
            if _WORKER_REGISTRY is None:
                _WORKER_REGISTRY = WorkerKVRegistry()
    return _WORKER_REGISTRY


def reset_worker_registry_for_tests(
    config: KVRegistryConfig | None = None,
    *,
    clock_ns: Callable[[], int] = time.time_ns,
) -> WorkerKVRegistry:
    global _WORKER_REGISTRY
    with _WORKER_REGISTRY_LOCK:
        _WORKER_REGISTRY = WorkerKVRegistry(config, clock_ns=clock_ns)
        return _WORKER_REGISTRY
