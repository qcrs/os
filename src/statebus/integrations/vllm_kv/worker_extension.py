from __future__ import annotations

import importlib.metadata
import os
import time
from typing import Any, Mapping
from uuid import uuid4

from statebus.contracts import EngineLocalKVHandle
from statebus.integrations.vllm_kv.connector import CONNECTOR_VERSION
from statebus.integrations.vllm_kv.registry import KVRegistryError, get_worker_registry
from statebus.utils import sha256_digest


WORKER_EXTENSION_VERSION = "statebus.vllm_kv.worker_extension.v1"


class KVWorkerError(RuntimeError):
    def __init__(self, error_code: str, detail: str = "") -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.detail = detail


class StateBusKVWorkerExtension:
    """Control-plane methods injected into the vLLM worker for local KV handles."""

    def statebus_kv_capabilities(self) -> dict[str, object]:
        signature = self._statebus_kv_signature()
        registry = get_worker_registry()
        stats = registry.stats()
        errors = self._statebus_kv_configuration_errors(signature)
        return {
            "status": "ready" if not errors else "not_ready",
            "plugin_version": WORKER_EXTENSION_VERSION,
            "connector_version": CONNECTOR_VERSION,
            "vllm_version": _vllm_version(),
            "engine_id": signature["engine_id"],
            "engine_generation": signature["engine_generation"],
            "model": signature["model_id"],
            "model_revision": signature["model_revision"],
            "tokenizer_digest": signature["tokenizer_digest"],
            "dtype": signature["dtype"],
            "block_size": signature["block_size"],
            "layer_count": signature["layer_count"],
            "max_num_seqs": signature["max_num_seqs"],
            "max_model_len": signature["max_model_len"],
            "tensor_parallel_size": signature["tensor_parallel_size"],
            "pipeline_parallel_size": signature["pipeline_parallel_size"],
            "automatic_prefix_caching": signature["automatic_prefix_caching"],
            "kv_connector": signature["kv_connector"],
            "kv_role": signature["kv_role"],
            "compatibility_signature": signature,
            "compatibility_digest": sha256_digest(signature),
            "registry_entries": stats["registry_entries"],
            "registry_bytes": stats["registry_bytes"],
            "registry_peak_entries": stats["registry_peak_entries"],
            "registry_peak_bytes": stats["registry_peak_bytes"],
            "registry_max_entries": registry.config.max_entries,
            "registry_max_bytes": registry.config.max_bytes,
            "registry_ttl_s": registry.config.default_ttl_s,
            "registry_one_shot": registry.config.one_shot,
            "registry_pin_memory": registry.config.pin_memory,
            "store_count": stats["store_count"],
            "load_count": stats["load_count"],
            "worker_pid": os.getpid(),
            "errors": errors,
        }

    def statebus_kv_prepare(self, capture_spec: dict[str, object]) -> dict[str, object]:
        if not isinstance(capture_spec, Mapping):
            raise KVWorkerError("kv_request_invalid", "capture_spec")
        health = self.statebus_kv_capabilities()
        if health["status"] != "ready":
            raise KVWorkerError("kv_plugin_not_ready", "worker_configuration")
        expected_digest = str(capture_spec.get("expected_compatibility_digest", ""))
        if expected_digest != str(health["compatibility_digest"]):
            raise KVWorkerError("kv_model_incompatible", "compatibility_digest")
        token_ids = _token_ids(capture_spec.get("token_ids"))
        token_digest = sha256_digest(list(token_ids))
        supplied_digest = str(capture_spec.get("token_digest", ""))
        if supplied_digest and supplied_digest != token_digest:
            raise KVWorkerError("kv_token_mismatch")
        signature = health["compatibility_signature"]
        assert isinstance(signature, Mapping)
        block_size = int(signature["block_size"])
        if not token_ids or len(token_ids) % block_size:
            raise KVWorkerError("kv_request_invalid", "block_alignment")
        task_id = str(capture_spec.get("task_id", ""))
        request_id = str(capture_spec.get("request_id", ""))
        if not task_id or not request_id:
            raise KVWorkerError("kv_request_invalid", "request_binding")
        registry = get_worker_registry()
        ttl_s = int(capture_spec.get("ttl_s", registry.config.default_ttl_s))
        if ttl_s <= 0 or ttl_s > 3600:
            raise KVWorkerError("kv_request_invalid", "ttl_s")
        now = time.time_ns()
        handle = EngineLocalKVHandle(
            handle_id=str(capture_spec.get("handle_id", "")) or f"kv-{uuid4().hex}",
            engine_id=str(signature["engine_id"]),
            engine_generation=str(signature["engine_generation"]),
            model_id=str(signature["model_id"]),
            model_revision=str(signature["model_revision"]),
            tokenizer_digest=str(signature["tokenizer_digest"]),
            task_id=task_id,
            producer_request_id=request_id,
            seq_len=len(token_ids),
            block_size=block_size,
            token_digest=token_digest,
            kv_bytes_actual=0,
            layer_count=0,
            dtype=str(signature["dtype"]),
            storage_tier=(
                "worker_pinned_host"
                if registry.config.pin_memory
                else "worker_pageable_host"
            ),
            created_at_ns=now,
            expires_at_ns=now + ttl_s * 1_000_000_000,
        )
        try:
            prepared = registry.prepare(
                handle,
                token_ids=token_ids,
                expected_layer_count=int(signature["layer_count"]),
            )
        except KVRegistryError as exc:
            raise KVWorkerError(exc.error_code, exc.detail) from exc
        return {
            "handle": prepared.canonical_payload(),
            "handle_id": prepared.handle_id,
            "status": prepared.status.value,
            "token_digest": prepared.token_digest,
            "compatibility_digest": prepared.compatibility_digest,
            "worker_compatibility_digest": health["compatibility_digest"],
            "worker_pid": os.getpid(),
        }

    def statebus_kv_prepare_consume(
        self,
        handle_id: str,
        request_id: str,
        task_id: str,
        expected_compatibility_digest: str,
    ) -> dict[str, object]:
        health = self.statebus_kv_capabilities()
        if health["status"] != "ready":
            raise KVWorkerError("kv_plugin_not_ready", "worker_configuration")
        if expected_compatibility_digest != str(health["compatibility_digest"]):
            raise KVWorkerError("kv_model_incompatible", "compatibility_digest")
        registry = get_worker_registry()
        try:
            handle = registry.describe(str(handle_id))
            if handle.compatibility_digest != _handle_compatibility_digest(health):
                raise KVWorkerError("kv_model_incompatible", "handle_signature")
            consumed = registry.begin_consume(
                str(handle_id),
                request_id=str(request_id),
                task_id=str(task_id),
                token_digest=handle.token_digest,
                engine_generation=str(health["engine_generation"]),
            )
            token_ids = registry.token_ids(str(handle_id))
        except KVRegistryError as exc:
            raise KVWorkerError(exc.error_code, exc.detail) from exc
        return {
            "handle": consumed.canonical_payload(),
            "handle_id": consumed.handle_id,
            "status": consumed.status.value,
            "token_ids": list(token_ids),
            "token_digest": consumed.token_digest,
            "compatibility_digest": consumed.compatibility_digest,
            "worker_compatibility_digest": health["compatibility_digest"],
        }

    def statebus_kv_describe(self, handle_id: str) -> dict[str, object]:
        registry = get_worker_registry()
        try:
            handle = registry.describe(str(handle_id))
            proof = registry.forward_proof(str(handle_id))
            store_ms = registry.store_ms(str(handle_id))
        except KVRegistryError as exc:
            raise KVWorkerError(exc.error_code, exc.detail) from exc
        return {
            "handle": handle.canonical_payload(),
            "handle_id": handle.handle_id,
            "status": handle.status.value,
            "store_ms": store_ms,
            "forward_proof": None if proof is None else proof.canonical_payload(),
            "forward_proof_hash": "" if proof is None else proof.proof_hash,
        }

    def statebus_kv_release(self, handle_id: str) -> dict[str, object]:
        try:
            handle = get_worker_registry().release(str(handle_id))
        except KVRegistryError as exc:
            raise KVWorkerError(exc.error_code, exc.detail) from exc
        return {"handle_id": handle.handle_id, "status": handle.status.value}

    def statebus_kv_abort(self, handle_id: str, reason: str) -> dict[str, object]:
        get_worker_registry().abort_consume(str(handle_id), str(reason) or "aborted")
        return {
            "handle_id": str(handle_id),
            "status": "invalidated",
            "reason": str(reason) or "aborted",
        }

    def statebus_kv_sweep_expired(self) -> dict[str, object]:
        registry = get_worker_registry()
        return {"expired_count": registry.sweep_expired(), **registry.stats()}

    def _statebus_kv_signature(self) -> dict[str, object]:
        config = getattr(self, "vllm_config", None)
        model_config = getattr(config, "model_config", None)
        hf_config = getattr(model_config, "hf_config", None)
        cache_config = getattr(config, "cache_config", None)
        scheduler_config = getattr(config, "scheduler_config", None)
        parallel_config = getattr(config, "parallel_config", None)
        transfer_config = getattr(config, "kv_transfer_config", None)
        layer_count = int(
            getattr(hf_config, "num_hidden_layers", getattr(hf_config, "num_layers", 0))
            or 0
        )
        return {
            "engine_id": str(getattr(transfer_config, "engine_id", "")),
            "engine_generation": os.environ.get("STATEBUS_KV_ENGINE_GENERATION", ""),
            "model_id": os.environ.get("STATEBUS_KV_MODEL_ID", "qwen3-32b"),
            "model_revision": os.environ.get("STATEBUS_KV_MODEL_REVISION_DIGEST", ""),
            "tokenizer_digest": os.environ.get("STATEBUS_KV_TOKENIZER_DIGEST", ""),
            "dtype": str(getattr(model_config, "dtype", "")).replace("torch.", ""),
            "block_size": int(getattr(cache_config, "block_size", 0) or 0),
            "layer_count": layer_count,
            "max_num_seqs": int(getattr(scheduler_config, "max_num_seqs", 0) or 0),
            "max_model_len": int(getattr(model_config, "max_model_len", 0) or 0),
            "tensor_parallel_size": int(
                getattr(parallel_config, "tensor_parallel_size", 0) or 0
            ),
            "pipeline_parallel_size": int(
                getattr(parallel_config, "pipeline_parallel_size", 0) or 0
            ),
            "automatic_prefix_caching": bool(
                getattr(cache_config, "enable_prefix_caching", False)
            ),
            "kv_connector": str(getattr(transfer_config, "kv_connector", "")),
            "kv_role": str(getattr(transfer_config, "kv_role", "")),
            "schema_version": "statebus.engine_local_kv.compatibility.v1",
        }

    def _statebus_kv_configuration_errors(
        self,
        signature: Mapping[str, object],
    ) -> list[str]:
        errors: list[str] = []
        required = (
            "engine_id",
            "engine_generation",
            "model_id",
            "model_revision",
            "tokenizer_digest",
            "dtype",
        )
        errors.extend(f"{name}_missing" for name in required if not signature.get(name))
        if os.environ.get("VLLM_USE_V1", "0") != "1":
            errors.append("vllm_v1_required")
        if signature.get("kv_connector") != "StateBusLocalKVConnector":
            errors.append("kv_connector_mismatch")
        if signature.get("kv_role") != "kv_both":
            errors.append("kv_role_mismatch")
        if bool(signature.get("automatic_prefix_caching")):
            errors.append("automatic_prefix_caching_must_be_disabled")
        if int(signature.get("block_size", 0)) <= 0:
            errors.append("block_size_invalid")
        if int(signature.get("layer_count", 0)) <= 0:
            errors.append("layer_count_invalid")
        if int(signature.get("max_num_seqs", 0)) != 1:
            errors.append("max_num_seqs_must_be_one")
        if int(signature.get("tensor_parallel_size", 0)) != 1:
            errors.append("tensor_parallel_size_must_be_one")
        if int(signature.get("pipeline_parallel_size", 0)) != 1:
            errors.append("pipeline_parallel_size_must_be_one")
        return sorted(set(errors))


def _token_ids(value: object) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise KVWorkerError("kv_request_invalid", "token_ids")
    try:
        resolved = tuple(int(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise KVWorkerError("kv_request_invalid", "token_ids") from exc
    if any(item < 0 for item in resolved):
        raise KVWorkerError("kv_request_invalid", "token_ids")
    return resolved


def _handle_compatibility_digest(health: Mapping[str, object]) -> str:
    signature = health.get("compatibility_signature", {})
    if not isinstance(signature, Mapping):
        return ""
    probe = EngineLocalKVHandle(
        handle_id="compatibility-probe",
        engine_id=str(signature.get("engine_id", "")),
        engine_generation=str(signature.get("engine_generation", "")),
        model_id=str(signature.get("model_id", "")),
        model_revision=str(signature.get("model_revision", "")),
        tokenizer_digest=str(signature.get("tokenizer_digest", "")),
        task_id="compatibility-probe",
        producer_request_id="compatibility-probe",
        seq_len=int(signature.get("block_size", 1)),
        block_size=int(signature.get("block_size", 1)),
        token_digest="compatibility-probe",
        kv_bytes_actual=0,
        layer_count=0,
        dtype=str(signature.get("dtype", "")),
        storage_tier="worker_pinned_host",
        created_at_ns=1,
        expires_at_ns=2,
    )
    return probe.compatibility_digest


def _vllm_version() -> str:
    try:
        return importlib.metadata.version("vllm")
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


__all__ = ["KVWorkerError", "StateBusKVWorkerExtension", "WORKER_EXTENSION_VERSION"]
