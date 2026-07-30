from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hmac
import inspect
import json
import logging
import os
from pathlib import Path
import stat
import time
from typing import Any, Awaitable, Callable, Mapping

from pydantic import ValidationError

from statebus.integrations.vllm_kv.api_models import (
    KVContinueRequestModel,
    KVProduceRequestModel,
    KVReleaseRequestModel,
    KVSamplingModel,
)
from statebus.integrations.vllm_kv.telemetry import (
    KVConsumerTelemetry,
    KVProducerTelemetry,
)
from statebus.utils import sha256_digest


logger = logging.getLogger(__name__)

KV_API_PREFIX = "/statebus/kv"
KV_PLUGIN_VERSION = "statebus.vllm_kv.middleware.v1"
KV_RPC_ALLOWLIST = frozenset(
    {
        "statebus_kv_capabilities",
        "statebus_kv_prepare",
        "statebus_kv_prepare_consume",
        "statebus_kv_describe",
        "statebus_kv_release",
        "statebus_kv_abort",
        "statebus_kv_sweep_expired",
    }
)
KV_ERROR_CODES = frozenset(
    {
        "kv_plugin_not_ready",
        "kv_auth_failed",
        "kv_loopback_required",
        "kv_request_invalid",
        "kv_model_incompatible",
        "kv_task_mismatch",
        "kv_token_mismatch",
        "kv_capture_incomplete",
        "kv_ref_not_found",
        "kv_ref_expired",
        "kv_ref_already_consumed",
        "kv_registry_capacity_exceeded",
        "kv_consumer_forward_not_observed",
    }
)

_ERROR_STATUS = {
    "kv_auth_failed": 401,
    "kv_loopback_required": 403,
    "kv_ref_not_found": 404,
    "kv_ref_expired": 410,
    "kv_ref_already_consumed": 409,
    "kv_registry_capacity_exceeded": 507,
    "kv_plugin_not_ready": 503,
}

ASGIScope = dict[str, Any]
ASGIMessage = dict[str, Any]
ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
ASGISend = Callable[[ASGIMessage], Awaitable[None]]
ASGIApp = Callable[[ASGIScope, ASGIReceive, ASGISend], Awaitable[None]]


class KVApiError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str = "",
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(error_code)
        self.error_code = (
            error_code if error_code in KV_ERROR_CODES else "kv_request_invalid"
        )
        self.detail = detail
        self.status_code = status_code or _ERROR_STATUS.get(self.error_code, 400)


@dataclass(frozen=True)
class _SamplingParamsFallback:
    temperature: float
    max_tokens: int
    seed: int
    extra_args: dict[str, Any] | None = None


@dataclass(frozen=True)
class _GenerationReceipt:
    text: str
    token_ids: tuple[int, ...]
    server_first_output_ms: float
    server_wall_ms: float
    scheduler_output_count: int
    num_cached_tokens: int
    kv_transfer_params: Mapping[str, Any]


@dataclass(frozen=True)
class _ConsumerContext:
    request: KVContinueRequestModel
    prompt_token_ids: tuple[int, ...]
    parent_token_ids: tuple[int, ...]
    parent_digest: str
    kv_transfer_params: dict[str, Any] | None


class KVHandoffMiddleware:
    """Authenticated loopback API for explicit engine-local KV continuation."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        token_file: str | os.PathLike[str] | None = None,
        max_body_bytes: int | None = None,
        request_lock: asyncio.Lock | None = None,
    ) -> None:
        self.app = app
        configured_token_file = token_file or os.environ.get(
            "STATEBUS_KV_API_TOKEN_FILE", ""
        )
        self.token_file = Path(configured_token_file) if configured_token_file else None
        self.max_body_bytes = max_body_bytes or int(
            os.environ.get("STATEBUS_KV_MAX_BODY_BYTES", str(8 * 1024 * 1024))
        )
        if self.max_body_bytes <= 0:
            raise ValueError("STATEBUS_KV_MAX_BODY_BYTES must be positive")
        self.request_lock = request_lock or asyncio.Lock()
        self.produce_success_count = 0
        self.full_replay_success_count = 0
        self.kv_continuation_success_count = 0
        self.failure_count = 0
        logger.info("StateBus KV handoff middleware initialized")

    async def __call__(
        self,
        scope: ASGIScope,
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        if not _request_path(scope).startswith(KV_API_PREFIX):
            await self.app(scope, receive, send)
            return

        await self.request_lock.acquire()
        released = False

        def release_lock() -> None:
            nonlocal released
            if not released:
                released = True
                self.request_lock.release()

        async def locked_send(message: ASGIMessage) -> None:
            await send(message)
            if (
                message.get("type") == "http.response.body"
                and not message.get("more_body", False)
            ):
                release_lock()

        try:
            await self._dispatch(scope, receive, locked_send)
        finally:
            release_lock()

    async def _dispatch(
        self,
        scope: ASGIScope,
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        path = _request_path(scope)
        method = str(scope.get("method", "GET")).upper()
        try:
            self._require_loopback(scope)
            self._require_auth(scope)
            engine = self._engine_client(scope)
            if (method, path) == ("GET", f"{KV_API_PREFIX}/health"):
                await _send_json(send, 200, await self._health(engine))
                return
            body = await self._read_json_body(scope, receive)
            if (method, path) == ("POST", f"{KV_API_PREFIX}/produce"):
                payload = await self._produce(engine, body)
                await _send_json(send, 200, payload)
                return
            if (method, path) == ("POST", f"{KV_API_PREFIX}/continue"):
                request = KVContinueRequestModel.model_validate(body)
                if request.stream:
                    await self._continue_stream(engine, request, send)
                else:
                    payload = await self._continue_collect(engine, request)
                    await _send_json(send, 200, payload)
                return
            if (method, path) == ("POST", f"{KV_API_PREFIX}/release"):
                payload = await self._release(engine, body)
                await _send_json(send, 200, payload)
                return
            await _send_json(
                send,
                404,
                _error_payload("kv_request_invalid", "endpoint_not_found"),
            )
        except ValidationError:
            self.failure_count += 1
            await _send_json(
                send,
                400,
                _error_payload("kv_request_invalid", "schema_validation_failed"),
            )
        except KVApiError as exc:
            self.failure_count += 1
            await _send_json(
                send,
                exc.status_code,
                _error_payload(exc.error_code, exc.detail),
            )
        except Exception as exc:
            self.failure_count += 1
            mapped = _exception_to_api_error(exc)
            await _send_json(
                send,
                mapped.status_code,
                _error_payload(mapped.error_code, mapped.detail),
            )

    async def _health(self, engine: Any) -> dict[str, Any]:
        try:
            capabilities = await _rpc(engine, "statebus_kv_capabilities")
        except Exception as exc:
            mapped = _exception_to_api_error(exc)
            if mapped.error_code == "kv_request_invalid":
                mapped = KVApiError("kv_plugin_not_ready", "capability_rpc_failed")
            raise mapped from exc
        if not isinstance(capabilities, Mapping):
            raise KVApiError("kv_plugin_not_ready", "capability_response_invalid")
        return _sanitize_health_payload(capabilities)

    async def _produce(self, engine: Any, body: dict[str, Any]) -> dict[str, Any]:
        request = KVProduceRequestModel.model_validate(body)
        health = await self._require_ready(
            engine,
            model=request.model,
            expected_compatibility_digest=request.expected_compatibility_digest,
        )
        parent_ids = _validated_token_ids(request.parent_token_ids)
        producer_suffix = _validated_token_ids(request.producer_suffix_token_ids)
        prompt_ids = parent_ids + producer_suffix
        _require_context_budget(prompt_ids, request.sampling, health)
        handle_id = ""
        kv_transfer_params: dict[str, Any] | None = None
        try:
            if request.capture_kv:
                token_digest = sha256_digest(list(parent_ids))
                prepared = await _rpc(
                    engine,
                    "statebus_kv_prepare",
                    {
                        "request_id": request.request_id,
                        "task_id": request.task_id,
                        "token_ids": list(parent_ids),
                        "token_digest": token_digest,
                        "ttl_s": request.ttl_s,
                        "expected_compatibility_digest": (
                            request.expected_compatibility_digest
                        ),
                    },
                )
                if not isinstance(prepared, Mapping):
                    raise KVApiError("kv_capture_incomplete", "prepare_response_invalid")
                handle_id = str(prepared.get("handle_id", ""))
                if not handle_id:
                    raise KVApiError("kv_capture_incomplete", "handle_id_missing")
                kv_transfer_params = {
                    "action": "store",
                    "handle_id": handle_id,
                    "task_id": request.task_id,
                    "token_digest": token_digest,
                    "prefix_len": len(parent_ids),
                }
            receipt = await _run_generation(
                engine,
                prompt_token_ids=prompt_ids,
                sampling=request.sampling,
                request_id=request.request_id,
                kv_transfer_params=kv_transfer_params,
            )
            handle: Mapping[str, Any] | None = None
            store_ms = 0.0
            if request.capture_kv:
                described = await _rpc(engine, "statebus_kv_describe", handle_id)
                if not isinstance(described, Mapping):
                    raise KVApiError("kv_capture_incomplete", "describe_response_invalid")
                handle_value = described.get("handle", {})
                if not isinstance(handle_value, Mapping):
                    raise KVApiError("kv_capture_incomplete", "handle_response_invalid")
                handle = dict(handle_value)
                if (
                    described.get("status") != "ready"
                    or int(handle.get("seq_len", 0)) != len(parent_ids)
                    or int(handle.get("kv_bytes_actual", 0)) <= 0
                    or int(handle.get("layer_count", 0)) <= 0
                ):
                    raise KVApiError("kv_capture_incomplete", "handle_not_ready")
                store_ms = float(described.get("store_ms", 0.0))
            telemetry = KVProducerTelemetry(
                request_id=request.request_id,
                task_id=request.task_id,
                capture_kv=request.capture_kv,
                logical_prompt_tokens=len(prompt_ids),
                parent_tokens=len(parent_ids),
                producer_suffix_tokens=len(producer_suffix),
                computed_prefill_tokens=len(prompt_ids),
                generated_tokens=len(receipt.token_ids),
                server_first_output_ms=receipt.server_first_output_ms,
                server_wall_ms=receipt.server_wall_ms,
                kv_store_ms=store_ms,
                kv_bytes_actual=0 if handle is None else int(handle["kv_bytes_actual"]),
                layer_count=0 if handle is None else int(handle["layer_count"]),
                extra={
                    "scheduler_output_count": receipt.scheduler_output_count,
                    "num_cached_tokens_reported": receipt.num_cached_tokens,
                },
            )
        except Exception as exc:
            if handle_id:
                await _safe_rpc(
                    engine,
                    "statebus_kv_abort",
                    handle_id,
                    _exception_to_api_error(exc).error_code,
                )
            raise _exception_to_api_error(exc) from exc

        self.produce_success_count += 1
        return {
            "status": "success",
            "request_id": request.request_id,
            "task_id": request.task_id,
            "output_text": receipt.text,
            "output_token_ids": list(receipt.token_ids),
            "handle": handle,
            "handle_id": handle_id,
            "telemetry": telemetry.canonical_payload(),
            "telemetry_hash": telemetry.telemetry_hash,
        }

    async def _continue_collect(
        self,
        engine: Any,
        request: KVContinueRequestModel,
    ) -> dict[str, Any]:
        context = await self._prepare_consumer(engine, request)
        try:
            receipt = await _run_generation(
                engine,
                prompt_token_ids=context.prompt_token_ids,
                sampling=request.sampling,
                request_id=request.request_id,
                kv_transfer_params=context.kv_transfer_params,
            )
            return await self._finish_consumer(engine, context, receipt)
        except Exception as exc:
            await self._abort_consumer(engine, context, exc)
            raise _exception_to_api_error(exc) from exc

    async def _continue_stream(
        self,
        engine: Any,
        request: KVContinueRequestModel,
        send: ASGISend,
    ) -> None:
        context = await self._prepare_consumer(engine, request)
        await _send_sse_start(send)

        async def emit_delta(text_delta: str, token_ids: tuple[int, ...]) -> None:
            await _send_sse_event(
                send,
                "token",
                {"text_delta": text_delta, "token_ids": list(token_ids)},
                more_body=True,
            )

        try:
            receipt = await _run_generation(
                engine,
                prompt_token_ids=context.prompt_token_ids,
                sampling=request.sampling,
                request_id=request.request_id,
                kv_transfer_params=context.kv_transfer_params,
                on_delta=emit_delta,
            )
            payload = await self._finish_consumer(engine, context, receipt)
            await _send_sse_event(send, "final", payload, more_body=True)
        except Exception as exc:
            await self._abort_consumer(engine, context, exc)
            self.failure_count += 1
            mapped = _exception_to_api_error(exc)
            await _send_sse_event(
                send,
                "error",
                _error_payload(mapped.error_code, mapped.detail),
                more_body=True,
            )
        finally:
            await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def _prepare_consumer(
        self,
        engine: Any,
        request: KVContinueRequestModel,
    ) -> _ConsumerContext:
        health = await self._require_ready(
            engine,
            model=request.model,
            expected_compatibility_digest=request.expected_compatibility_digest,
        )
        suffix_ids = _validated_token_ids(request.suffix_token_ids)
        if request.lane == "kv_continuation":
            try:
                prepared = await _rpc(
                    engine,
                    "statebus_kv_prepare_consume",
                    request.handle_id,
                    request.request_id,
                    request.task_id,
                    request.expected_compatibility_digest,
                )
                if not isinstance(prepared, Mapping):
                    raise KVApiError(
                        "kv_consumer_forward_not_observed", "consume_response_invalid"
                    )
                parent_ids = _validated_token_ids(prepared.get("token_ids", ()))
                handle = prepared.get("handle", {})
                if not isinstance(handle, Mapping):
                    raise KVApiError(
                        "kv_consumer_forward_not_observed", "handle_invalid"
                    )
                parent_digest = sha256_digest(list(parent_ids))
                if (
                    prepared.get("status") != "consuming"
                    or int(handle.get("seq_len", 0)) != len(parent_ids)
                    or str(handle.get("token_digest", "")) != parent_digest
                ):
                    raise KVApiError(
                        "kv_consumer_forward_not_observed", "consume_binding_invalid"
                    )
                kv_transfer_params = {
                    "action": "load",
                    "handle_id": request.handle_id,
                    "task_id": request.task_id,
                    "token_digest": parent_digest,
                    "prefix_len": len(parent_ids),
                }
                prompt_ids = parent_ids + suffix_ids
                _require_context_budget(prompt_ids, request.sampling, health)
            except Exception as exc:
                await _safe_rpc(
                    engine,
                    "statebus_kv_abort",
                    request.handle_id,
                    _exception_to_api_error(exc).error_code,
                )
                raise _exception_to_api_error(exc) from exc
        else:
            parent_ids = _validated_token_ids(request.parent_token_ids)
            parent_digest = sha256_digest(list(parent_ids))
            kv_transfer_params = None
            prompt_ids = parent_ids + suffix_ids
            _require_context_budget(prompt_ids, request.sampling, health)
        return _ConsumerContext(
            request=request,
            prompt_token_ids=prompt_ids,
            parent_token_ids=parent_ids,
            parent_digest=parent_digest,
            kv_transfer_params=kv_transfer_params,
        )

    async def _finish_consumer(
        self,
        engine: Any,
        context: _ConsumerContext,
        receipt: _GenerationReceipt,
    ) -> dict[str, Any]:
        request = context.request
        parent_count = len(context.parent_token_ids)
        suffix_count = len(request.suffix_token_ids)
        proof_payload: dict[str, Any] | None = None
        proof_hash = ""
        inherited = 0
        computed = len(context.prompt_token_ids)
        load_count = 0
        load_ms = 0.0
        kv_bytes = 0
        layer_count = 0
        if request.lane == "kv_continuation":
            scheduler_proof = receipt.kv_transfer_params.get("statebus_kv", {})
            if not isinstance(scheduler_proof, Mapping):
                raise KVApiError(
                    "kv_consumer_forward_not_observed", "scheduler_proof_missing"
                )
            expected_scheduler = {
                "action": "load",
                "handle_id": request.handle_id,
                "logical_prompt_tokens": len(context.prompt_token_ids),
                "inherited_kv_tokens": parent_count,
                "computed_prefill_tokens": suffix_count,
            }
            if any(
                scheduler_proof.get(key) != value
                for key, value in expected_scheduler.items()
            ):
                raise KVApiError(
                    "kv_consumer_forward_not_observed",
                    "scheduler_proof_binding_invalid",
                )
            described = await _rpc(engine, "statebus_kv_describe", request.handle_id)
            if not isinstance(described, Mapping):
                raise KVApiError(
                    "kv_consumer_forward_not_observed", "describe_response_invalid"
                )
            proof = described.get("forward_proof", {})
            if not isinstance(proof, Mapping):
                raise KVApiError("kv_consumer_forward_not_observed", "proof_missing")
            expected = {
                "handle_id": request.handle_id,
                "request_id": request.request_id,
                "task_id": request.task_id,
                "token_digest": context.parent_digest,
                "inherited_kv_tokens": parent_count,
                "computed_prefill_tokens": suffix_count,
                "logical_prompt_tokens": len(context.prompt_token_ids),
                "suffix_tokens": suffix_count,
                "connector_load_count": 1,
            }
            if described.get("status") != "consumed" or any(
                proof.get(key) != value for key, value in expected.items()
            ):
                raise KVApiError(
                    "kv_consumer_forward_not_observed", "proof_binding_invalid"
                )
            proof_payload = dict(proof)
            proof_hash = str(described.get("forward_proof_hash", ""))
            inherited = int(proof["inherited_kv_tokens"])
            computed = int(proof["computed_prefill_tokens"])
            load_count = int(proof["connector_load_count"])
            load_ms = float(proof["kv_load_ms"])
            kv_bytes = int(proof["kv_bytes_actual"])
            layer_count = int(proof["layer_count"])
            self.kv_continuation_success_count += 1
        else:
            self.full_replay_success_count += 1

        telemetry = KVConsumerTelemetry(
            request_id=request.request_id,
            task_id=request.task_id,
            lane=request.lane,
            logical_prompt_tokens=len(context.prompt_token_ids),
            parent_tokens=parent_count,
            suffix_tokens=suffix_count,
            inherited_kv_tokens=inherited,
            computed_prefill_tokens=computed,
            generated_tokens=len(receipt.token_ids),
            server_first_output_ms=receipt.server_first_output_ms,
            server_wall_ms=receipt.server_wall_ms,
            connector_load_count=load_count,
            kv_load_ms=load_ms,
            kv_bytes_actual=kv_bytes,
            layer_count=layer_count,
            num_cached_tokens_reported=receipt.num_cached_tokens,
            forward_proof_hash=proof_hash,
            extra={
                "scheduler_output_count": receipt.scheduler_output_count,
                "scheduler_kv_proof": dict(
                    receipt.kv_transfer_params.get("statebus_kv", {})
                ),
            },
        )
        return {
            "status": "success",
            "request_id": request.request_id,
            "task_id": request.task_id,
            "lane": request.lane,
            "handle_id": request.handle_id,
            "logical_token_digest": sha256_digest(list(context.prompt_token_ids)),
            "output_text": receipt.text,
            "output_token_ids": list(receipt.token_ids),
            "telemetry": telemetry.canonical_payload(),
            "telemetry_hash": telemetry.telemetry_hash,
            "forward_proof": proof_payload,
        }

    async def _abort_consumer(
        self,
        engine: Any,
        context: _ConsumerContext,
        exc: Exception,
    ) -> None:
        if context.request.lane == "kv_continuation":
            await _safe_rpc(
                engine,
                "statebus_kv_abort",
                context.request.handle_id,
                _exception_to_api_error(exc).error_code,
            )

    async def _release(self, engine: Any, body: dict[str, Any]) -> dict[str, Any]:
        request = KVReleaseRequestModel.model_validate(body)
        released = await _rpc(engine, "statebus_kv_release", request.handle_id)
        if not isinstance(released, Mapping):
            raise KVApiError("kv_request_invalid", "release_response_invalid")
        return {
            "handle_id": str(released.get("handle_id", request.handle_id)),
            "status": str(released.get("status", "released")),
        }

    async def _require_ready(
        self,
        engine: Any,
        *,
        model: str,
        expected_compatibility_digest: str,
    ) -> dict[str, Any]:
        health = await self._health(engine)
        if health.get("status") != "ready":
            raise KVApiError("kv_plugin_not_ready")
        if str(health.get("model", "")) != model:
            raise KVApiError("kv_model_incompatible", "model")
        if str(health.get("compatibility_digest", "")) != expected_compatibility_digest:
            raise KVApiError("kv_model_incompatible", "compatibility_digest")
        return health

    def _require_loopback(self, scope: ASGIScope) -> None:
        client = scope.get("client")
        host = str(client[0]) if isinstance(client, (tuple, list)) and client else ""
        if not _is_loopback(host):
            raise KVApiError("kv_loopback_required")

    def _require_auth(self, scope: ASGIScope) -> None:
        expected = self._read_token()
        authorization = _header_value(scope, b"authorization")
        supplied = (
            authorization[len("Bearer ") :]
            if authorization.startswith("Bearer ")
            else ""
        )
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise KVApiError("kv_auth_failed")

    def _read_token(self) -> str:
        if self.token_file is None:
            raise KVApiError("kv_auth_failed", "token_file_unavailable")
        try:
            metadata = self.token_file.stat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                raise KVApiError("kv_auth_failed", "token_file_permissions")
            token = self.token_file.read_text(encoding="utf-8").strip()
        except KVApiError:
            raise
        except OSError as exc:
            raise KVApiError("kv_auth_failed", "token_file_unavailable") from exc
        if not token or any(character.isspace() for character in token):
            raise KVApiError("kv_auth_failed", "token_file_invalid")
        return token

    def _engine_client(self, scope: ASGIScope) -> Any:
        application = scope.get("app") or self.app
        state = getattr(application, "state", None)
        engine = getattr(state, "engine_client", None)
        if engine is None and isinstance(state, Mapping):
            engine = state.get("engine_client")
        if engine is None:
            raise KVApiError("kv_plugin_not_ready", "engine_client_unavailable")
        return engine

    async def _read_json_body(
        self,
        scope: ASGIScope,
        receive: ASGIReceive,
    ) -> dict[str, Any]:
        content_length = _header_value(scope, b"content-length")
        if content_length:
            try:
                if int(content_length) > self.max_body_bytes:
                    raise KVApiError(
                        "kv_request_invalid", "body_too_large", status_code=413
                    )
            except ValueError as exc:
                raise KVApiError(
                    "kv_request_invalid", "invalid_content_length"
                ) from exc
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                raise KVApiError("kv_request_invalid", "client_disconnected")
            if message.get("type") != "http.request":
                continue
            chunk = bytes(message.get("body", b""))
            total += len(chunk)
            if total > self.max_body_bytes:
                raise KVApiError("kv_request_invalid", "body_too_large", status_code=413)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        try:
            payload = json.loads(b"".join(chunks))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KVApiError("kv_request_invalid", "invalid_json") from exc
        if not isinstance(payload, dict):
            raise KVApiError("kv_request_invalid", "object_body_required")
        return payload


async def _rpc(engine: Any, method: str, *args: Any) -> Any:
    if method not in KV_RPC_ALLOWLIST:
        raise KVApiError("kv_request_invalid", "rpc_method_not_allowed")
    collective_rpc = getattr(engine, "collective_rpc", None)
    if not callable(collective_rpc):
        raise KVApiError("kv_plugin_not_ready", "collective_rpc_unavailable")
    try:
        result = collective_rpc(method, args=tuple(args), kwargs=None)
        result = await _maybe_await(result)
    except Exception as exc:
        raise _exception_to_api_error(exc) from exc
    if isinstance(result, (list, tuple)):
        if not result:
            raise KVApiError("kv_plugin_not_ready", "empty_worker_response")
        result = result[0]
    if isinstance(result, BaseException):
        raise _exception_to_api_error(result)
    return result


async def _safe_rpc(engine: Any, method: str, *args: Any) -> None:
    try:
        await _rpc(engine, method, *args)
    except Exception:
        return


async def _run_generation(
    engine: Any,
    *,
    prompt_token_ids: tuple[int, ...],
    sampling: KVSamplingModel,
    request_id: str,
    kv_transfer_params: Mapping[str, Any] | None,
    on_delta: Callable[[str, tuple[int, ...]], Awaitable[None]] | None = None,
) -> _GenerationReceipt:
    generate = getattr(engine, "generate", None)
    if not callable(generate):
        raise KVApiError("kv_plugin_not_ready", "generate_unavailable")
    sampling_params = _sampling_params(sampling, kv_transfer_params)
    started = time.perf_counter_ns()
    first_output_ns = 0
    scheduler_outputs = 0
    final_text = ""
    final_tokens: tuple[int, ...] = ()
    num_cached_tokens = 0
    final_kv_params: Mapping[str, Any] = {}
    try:
        stream = generate(
            {"prompt_token_ids": list(prompt_token_ids)},
            sampling_params,
            request_id=request_id,
        )
        stream = await _maybe_await(stream)
        if not hasattr(stream, "__aiter__"):
            raise KVApiError("kv_plugin_not_ready", "async_generation_required")
        async for chunk in stream:
            scheduler_outputs += 1
            text_value, token_ids, cached_tokens, transfer_params = _generation_snapshot(
                chunk
            )
            text_delta = (
                text_value[len(final_text) :]
                if text_value.startswith(final_text)
                else text_value
            )
            token_delta = (
                token_ids[len(final_tokens) :]
                if token_ids[: len(final_tokens)] == final_tokens
                else token_ids
            )
            if (text_delta or token_delta) and first_output_ns == 0:
                first_output_ns = time.perf_counter_ns()
            if on_delta is not None and (text_delta or token_delta):
                await on_delta(text_delta, token_delta)
            final_text = text_value
            final_tokens = token_ids
            num_cached_tokens = max(num_cached_tokens, cached_tokens)
            if transfer_params:
                final_kv_params = transfer_params
    except Exception as exc:
        raise _exception_to_api_error(exc) from exc
    finished = time.perf_counter_ns()
    return _GenerationReceipt(
        text=final_text,
        token_ids=final_tokens,
        server_first_output_ms=(
            0.0 if first_output_ns == 0 else (first_output_ns - started) / 1_000_000.0
        ),
        server_wall_ms=(finished - started) / 1_000_000.0,
        scheduler_output_count=scheduler_outputs,
        num_cached_tokens=num_cached_tokens,
        kv_transfer_params=final_kv_params,
    )


def _generation_snapshot(
    chunk: Any,
) -> tuple[str, tuple[int, ...], int, Mapping[str, Any]]:
    outputs = chunk.get("outputs", ()) if isinstance(chunk, Mapping) else getattr(
        chunk, "outputs", ()
    )
    candidate = outputs[0] if outputs else chunk
    text_value = candidate.get("text", "") if isinstance(candidate, Mapping) else getattr(
        candidate, "text", ""
    )
    token_values = candidate.get("token_ids", ()) if isinstance(candidate, Mapping) else getattr(
        candidate, "token_ids", ()
    )
    cached_tokens = chunk.get("num_cached_tokens", 0) if isinstance(chunk, Mapping) else getattr(
        chunk, "num_cached_tokens", 0
    )
    transfer = chunk.get("kv_transfer_params", {}) if isinstance(chunk, Mapping) else getattr(
        chunk, "kv_transfer_params", {}
    )
    return (
        str(text_value or ""),
        tuple(int(value) for value in (token_values or ())),
        int(cached_tokens or 0),
        dict(transfer) if isinstance(transfer, Mapping) else {},
    )


def _sampling_params(
    sampling: KVSamplingModel,
    kv_transfer_params: Mapping[str, Any] | None,
) -> Any:
    extra_args = (
        None
        if kv_transfer_params is None
        else {"kv_transfer_params": dict(kv_transfer_params)}
    )
    try:
        from vllm import SamplingParams

        return SamplingParams(
            temperature=float(sampling.temperature),
            max_tokens=int(sampling.max_tokens),
            seed=int(sampling.seed),
            extra_args=extra_args,
        )
    except ImportError:
        return _SamplingParamsFallback(
            temperature=float(sampling.temperature),
            max_tokens=int(sampling.max_tokens),
            seed=int(sampling.seed),
            extra_args=extra_args,
        )


def _validated_token_ids(value: Any) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise KVApiError("kv_request_invalid", "token_ids")
    try:
        token_ids = tuple(int(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise KVApiError("kv_request_invalid", "token_ids") from exc
    if any(item < 0 for item in token_ids):
        raise KVApiError("kv_request_invalid", "token_ids")
    return token_ids


def _require_context_budget(
    prompt_token_ids: tuple[int, ...],
    sampling: KVSamplingModel,
    health: Mapping[str, Any],
) -> None:
    max_model_len = int(health.get("max_model_len", 0))
    if max_model_len <= 0 or len(prompt_token_ids) + sampling.max_tokens > max_model_len:
        raise KVApiError("kv_request_invalid", "context_budget")


def _sanitize_health_payload(capabilities: Mapping[str, Any]) -> dict[str, Any]:
    errors = [str(value) for value in capabilities.get("errors", ())]
    signature = capabilities.get("compatibility_signature", {})
    if not isinstance(signature, Mapping):
        signature = {}
        errors.append("compatibility_signature_invalid")
    ready = (
        capabilities.get("status") == "ready"
        and capabilities.get("kv_connector") == "StateBusLocalKVConnector"
        and capabilities.get("kv_role") == "kv_both"
        and not bool(capabilities.get("automatic_prefix_caching", True))
        and int(capabilities.get("max_num_seqs", 0)) == 1
        and not errors
    )
    return {
        "status": "ready" if ready else "not_ready",
        "plugin_version": KV_PLUGIN_VERSION,
        "worker_plugin_version": str(capabilities.get("plugin_version", "")),
        "connector_version": str(capabilities.get("connector_version", "")),
        "vllm_version": str(capabilities.get("vllm_version", "")),
        "engine_id": str(capabilities.get("engine_id", "")),
        "engine_generation": str(capabilities.get("engine_generation", "")),
        "model": str(capabilities.get("model", "")),
        "model_revision": str(capabilities.get("model_revision", "")),
        "tokenizer_digest": str(capabilities.get("tokenizer_digest", "")),
        "dtype": str(capabilities.get("dtype", "")),
        "block_size": int(capabilities.get("block_size", 0)),
        "layer_count": int(capabilities.get("layer_count", 0)),
        "max_num_seqs": int(capabilities.get("max_num_seqs", 0)),
        "max_model_len": int(capabilities.get("max_model_len", 0)),
        "tensor_parallel_size": int(capabilities.get("tensor_parallel_size", 0)),
        "pipeline_parallel_size": int(capabilities.get("pipeline_parallel_size", 0)),
        "automatic_prefix_caching": bool(
            capabilities.get("automatic_prefix_caching", False)
        ),
        "kv_connector": str(capabilities.get("kv_connector", "")),
        "kv_role": str(capabilities.get("kv_role", "")),
        "compatibility_signature": dict(signature),
        "compatibility_digest": str(capabilities.get("compatibility_digest", "")),
        "registry_entries": int(capabilities.get("registry_entries", 0)),
        "registry_bytes": int(capabilities.get("registry_bytes", 0)),
        "registry_peak_entries": int(capabilities.get("registry_peak_entries", 0)),
        "registry_peak_bytes": int(capabilities.get("registry_peak_bytes", 0)),
        "registry_max_entries": int(capabilities.get("registry_max_entries", 0)),
        "registry_max_bytes": int(capabilities.get("registry_max_bytes", 0)),
        "registry_ttl_s": int(capabilities.get("registry_ttl_s", 0)),
        "registry_one_shot": bool(capabilities.get("registry_one_shot", False)),
        "registry_pin_memory": bool(capabilities.get("registry_pin_memory", False)),
        "store_count": int(capabilities.get("store_count", 0)),
        "load_count": int(capabilities.get("load_count", 0)),
        "worker_pid": int(capabilities.get("worker_pid", 0)),
        "errors": sorted(set(errors)),
    }


def _exception_to_api_error(exc: BaseException) -> KVApiError:
    if isinstance(exc, KVApiError):
        return exc
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = str(getattr(current, "error_code", ""))
        if code in KV_ERROR_CODES:
            return KVApiError(code, str(getattr(current, "detail", "")))
        message = str(current)
        for candidate in KV_ERROR_CODES:
            if candidate in message:
                return KVApiError(candidate)
        current = current.__cause__ or current.__context__
    return KVApiError("kv_plugin_not_ready", type(exc).__name__)


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _send_json(send: ASGISend, status: int, payload: Mapping[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


async def _send_sse_start(send: ASGISend) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"text/event-stream"),
                (b"cache-control", b"no-store"),
                (b"x-accel-buffering", b"no"),
            ],
        }
    )


async def _send_sse_event(
    send: ASGISend,
    event: str,
    payload: Mapping[str, Any],
    *,
    more_body: bool,
) -> None:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    body = f"event: {event}\ndata: {encoded}\n\n".encode()
    await send({"type": "http.response.body", "body": body, "more_body": more_body})


def _error_payload(error_code: str, detail: str = "") -> dict[str, str]:
    return {"status": "error", "error_code": error_code, "detail": detail}


def _header_value(scope: ASGIScope, name: bytes) -> str:
    for key, value in scope.get("headers", ()):
        if bytes(key).lower() == name:
            return bytes(value).decode("latin-1")
    return ""


def _request_path(scope: ASGIScope) -> str:
    return str(scope.get("path", ""))


def _is_loopback(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"127.0.0.1", "::1", "localhost"} or normalized.startswith(
        "127."
    )


__all__ = [
    "KV_API_PREFIX",
    "KV_ERROR_CODES",
    "KVApiError",
    "KVHandoffMiddleware",
]
