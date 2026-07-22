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
from uuid import uuid4

from pydantic import ValidationError

from v2.contracts import LatentAnchor
from v2.integrations.vllm_latent.alignment import sanitize_alignment_diagnostics
from v2.integrations.vllm_latent.api_models import (
    LatentCompleteRequestModel,
    LatentProduceRequestModel,
    LatentReleaseRequestModel,
    anchor_payload,
)
from v2.integrations.vllm_latent.telemetry import (
    LatentConsumerTelemetry,
    LatentProducerTelemetry,
)
from v2.utils import sha256_digest


logger = logging.getLogger(__name__)

LATENT_API_PREFIX = "/statebus/latent"
LATENT_MARKER = "<|statebus_latent_v1|>"
LATENT_PLUGIN_VERSION = "statebus.vllm_latent.v1"

LATENT_RPC_ALLOWLIST = frozenset(
    {
        "statebus_latent_capabilities",
        "statebus_latent_begin",
        "statebus_latent_finish",
        "statebus_latent_abort",
        "statebus_latent_describe",
        "statebus_latent_materialize_consumer_prompt",
        "statebus_latent_begin_consume",
        "statebus_latent_finish_consume",
        "statebus_latent_release",
        "statebus_latent_sweep_expired",
    }
)

LATENT_ERROR_CODES = frozenset(
    {
        "latent_plugin_not_ready",
        "latent_auth_failed",
        "latent_loopback_required",
        "latent_capture_busy",
        "latent_request_invalid",
        "latent_model_incompatible",
        "latent_alignment_incompatible",
        "latent_position_contract_incompatible",
        "latent_anchor_mismatch",
        "latent_capture_incomplete",
        "latent_ref_not_found",
        "latent_ref_expired",
        "latent_ref_already_consumed",
        "latent_registry_capacity_exceeded",
        "latent_consumer_forward_not_observed",
        "latent_output_validation_failed",
    }
)

_ERROR_STATUS = {
    "latent_auth_failed": 401,
    "latent_loopback_required": 403,
    "latent_ref_not_found": 404,
    "latent_ref_expired": 410,
    "latent_capture_busy": 409,
    "latent_ref_already_consumed": 409,
    "latent_registry_capacity_exceeded": 507,
    "latent_plugin_not_ready": 503,
}

ASGIScope = dict[str, Any]
ASGIMessage = dict[str, Any]
ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
ASGISend = Callable[[ASGIMessage], Awaitable[None]]
ASGIApp = Callable[[ASGIScope, ASGIReceive, ASGISend], Awaitable[None]]


class LatentApiError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str = "",
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(error_code)
        self.error_code = (
            error_code if error_code in LATENT_ERROR_CODES else "latent_request_invalid"
        )
        self.detail = detail
        self.status_code = status_code or _ERROR_STATUS.get(self.error_code, 400)


@dataclass(frozen=True)
class _GenerationReceipt:
    text: str = ""
    completion_tokens: int = 0
    scheduler_sample_count: int = 0


@dataclass(frozen=True)
class _SamplingParamsFallback:
    temperature: float
    max_tokens: int
    seed: int
    ignore_eos: bool = False
    guided_decoding: Any | None = None


class LatentHandoffMiddleware:
    """Pure ASGI middleware for the engine-local latent handoff API.

    The module deliberately imports neither vLLM nor torch at import time. This
    keeps contract tests runnable in the StateBus container while the live host
    process supplies those packages when the plugin is loaded.
    """

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
            "STATEBUS_LATENT_API_TOKEN_FILE",
            os.environ.get("STATEBUS_LATENT_TOKEN_FILE", ""),
        )
        self.token_file = Path(configured_token_file) if configured_token_file else None
        self.max_body_bytes = max_body_bytes or int(
            os.environ.get("STATEBUS_LATENT_MAX_BODY_BYTES", str(8 * 1024 * 1024))
        )
        if self.max_body_bytes <= 0:
            raise ValueError("STATEBUS_LATENT_MAX_BODY_BYTES must be positive")
        self.request_lock = request_lock or asyncio.Lock()
        self.latent_produce_success_count = 0
        self.latent_consume_success_count = 0
        self.latent_success_count = 0
        self.latent_failure_count = 0
        logger.info("latent middleware initialized")

    async def __call__(
        self,
        scope: ASGIScope,
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        if scope.get("type") != "http":
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
            path = _request_path(scope)
            if path.startswith(LATENT_API_PREFIX):
                await self._dispatch_latent(scope, receive, locked_send)
            else:
                await self.app(scope, receive, locked_send)
        finally:
            # Standards-compliant streaming apps return only after the final
            # body. This fallback prevents a lock leak on app exceptions.
            release_lock()

    async def _dispatch_latent(
        self,
        scope: ASGIScope,
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        path = _request_path(scope)
        method = str(scope.get("method", "GET")).upper()
        routes = {
            ("GET", f"{LATENT_API_PREFIX}/health"): self._health,
            ("POST", f"{LATENT_API_PREFIX}/produce"): self._produce,
            ("POST", f"{LATENT_API_PREFIX}/complete"): self._complete,
            ("POST", f"{LATENT_API_PREFIX}/release"): self._release,
        }
        handler = routes.get((method, path))
        if handler is None:
            await _send_json(
                send,
                404,
                _error_payload("latent_request_invalid", "endpoint_not_found"),
            )
            return

        try:
            self._require_loopback(scope)
            self._require_auth(scope)
            engine = self._engine_client(scope)
            if path == f"{LATENT_API_PREFIX}/health":
                payload = await handler(engine)
            else:
                body = await self._read_json_body(scope, receive)
                payload = await handler(engine, body)
            await _send_json(send, 200, payload)
        except LatentApiError as exc:
            if path != f"{LATENT_API_PREFIX}/health":
                self.latent_failure_count += 1
            await _send_json(
                send,
                exc.status_code,
                _error_payload(exc.error_code, exc.detail),
            )
        except ValidationError:
            if path != f"{LATENT_API_PREFIX}/health":
                self.latent_failure_count += 1
            await _send_json(
                send,
                400,
                _error_payload("latent_request_invalid", "schema_validation_failed"),
            )
        except Exception as exc:  # fail closed at the plugin boundary
            if path != f"{LATENT_API_PREFIX}/health":
                self.latent_failure_count += 1
            mapped = _exception_to_api_error(exc)
            await _send_json(
                send,
                mapped.status_code,
                _error_payload(mapped.error_code, mapped.detail),
            )

    def _require_loopback(self, scope: ASGIScope) -> None:
        client = scope.get("client")
        host = str(client[0]) if isinstance(client, (tuple, list)) and client else ""
        if not _is_loopback(host):
            raise LatentApiError("latent_loopback_required")

    def _require_auth(self, scope: ASGIScope) -> None:
        expected = self._read_token()
        authorization = _header_value(scope, b"authorization")
        prefix = "Bearer "
        supplied = authorization[len(prefix) :] if authorization.startswith(prefix) else ""
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise LatentApiError("latent_auth_failed")

    def _read_token(self) -> str:
        token_file = self.token_file
        if token_file is None:
            raise LatentApiError("latent_auth_failed", "token_file_unavailable")
        try:
            metadata = token_file.stat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                raise LatentApiError("latent_auth_failed", "token_file_permissions")
            token = token_file.read_text(encoding="utf-8").strip()
        except LatentApiError:
            raise
        except OSError as exc:
            raise LatentApiError("latent_auth_failed", "token_file_unavailable") from exc
        if not token or any(character.isspace() for character in token):
            raise LatentApiError("latent_auth_failed", "token_file_invalid")
        return token

    def _engine_client(self, scope: ASGIScope) -> Any:
        application = scope.get("app")
        if application is None:
            application = self.app
        state = getattr(application, "state", None)
        engine = getattr(state, "engine_client", None)
        if engine is None and isinstance(state, Mapping):
            engine = state.get("engine_client")
        if engine is None:
            raise LatentApiError("latent_plugin_not_ready", "engine_client_unavailable")
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
                    raise LatentApiError(
                        "latent_request_invalid", "body_too_large", status_code=413
                    )
            except ValueError as exc:
                raise LatentApiError(
                    "latent_request_invalid", "invalid_content_length"
                ) from exc
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                raise LatentApiError("latent_request_invalid", "client_disconnected")
            if message.get("type") != "http.request":
                continue
            chunk = bytes(message.get("body", b""))
            size += len(chunk)
            if size > self.max_body_bytes:
                raise LatentApiError(
                    "latent_request_invalid", "body_too_large", status_code=413
                )
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        try:
            payload = json.loads(b"".join(chunks))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LatentApiError("latent_request_invalid", "invalid_json") from exc
        if not isinstance(payload, dict):
            raise LatentApiError("latent_request_invalid", "object_body_required")
        return payload

    async def _health(self, engine: Any) -> dict[str, Any]:
        try:
            capabilities = await _rpc(
                engine,
                "statebus_latent_capabilities",
            )
        except Exception as exc:
            mapped = _exception_to_api_error(exc)
            if mapped.error_code == "latent_request_invalid":
                mapped = LatentApiError(
                    "latent_plugin_not_ready", "capability_rpc_failed"
                )
            raise mapped from exc
        if not isinstance(capabilities, Mapping):
            raise LatentApiError(
                "latent_plugin_not_ready", "capability_response_invalid"
            )
        return _sanitize_health_payload(capabilities)

    async def _produce(
        self,
        engine: Any,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        request = LatentProduceRequestModel.model_validate(body)
        health = await self._require_ready(
            engine,
            model=request.model,
            expected_compatibility_digest=request.expected_compatibility_digest,
        )
        signature = _signature_payload(health)
        if request.alignment_method != str(signature.get("alignment_method", "")):
            raise LatentApiError("latent_alignment_incompatible")
        if request.producer_role != "retriever" or request.consumer_role != "summarizer":
            raise LatentApiError("latent_request_invalid", "role_edge_not_allowed")

        tokenizer = await _engine_tokenizer(engine)
        rendered_prompt = _render_messages(tokenizer, request.messages)
        capture_id = f"capture-{uuid4().hex}"
        capture_spec = {
            "capture_id": capture_id,
            "request_id": request.request_id,
            "task_id": request.task_id,
            "source_step_id": request.source_step_id,
            "producer_role": request.producer_role,
            "consumer_role": request.consumer_role,
            "latent_steps": request.latent_steps,
            "ttl_s": request.ttl_s,
            "alignment_method": request.alignment_method,
            "expected_compatibility_digest": request.expected_compatibility_digest,
            "anchor": anchor_payload(request.anchor),
            "engine_id": str(health.get("engine_id", "vllm-v0")),
        }
        begin_started = time.perf_counter()
        begun: Mapping[str, Any] | None = None
        try:
            begun_value = await _rpc(engine, "statebus_latent_begin", capture_spec)
            if not isinstance(begun_value, Mapping):
                raise LatentApiError("latent_capture_incomplete", "begin_response_invalid")
            begun = begun_value
            if str(begun.get("compatibility_digest", "")) != (
                request.expected_compatibility_digest
            ):
                raise LatentApiError("latent_model_incompatible")
            sampling = _sampling_params(
                temperature=0.0,
                max_tokens=request.latent_steps,
                seed=7,
                ignore_eos=True,
            )
            rollout_started = time.perf_counter()
            receipt = await _run_generation(
                engine,
                prompt=rendered_prompt,
                sampling_params=sampling,
                request_id=request.request_id,
                retain_text=False,
            )
            rollout_ms = (time.perf_counter() - rollout_started) * 1000.0
            finish_started = time.perf_counter()
            finished_value = await _rpc(
                engine,
                "statebus_latent_finish",
                str(begun.get("capture_id", capture_id)),
            )
            registry_commit_ms = (time.perf_counter() - finish_started) * 1000.0
            if not isinstance(finished_value, Mapping):
                raise LatentApiError("latent_capture_incomplete", "finish_response_invalid")
            finished = finished_value
        except Exception as exc:
            if begun is not None:
                await _safe_rpc(
                    engine,
                    "statebus_latent_abort",
                    str(begun.get("capture_id", capture_id)),
                    _exception_to_api_error(exc).error_code,
                )
            raise _exception_to_api_error(exc) from exc

        response = _sanitize_produce_result(finished)
        expected_shape = (request.latent_steps, int(signature.get("hidden_size", 0)))
        shape = tuple(int(value) for value in response.get("shape", ()))
        expected_bytes = expected_shape[0] * expected_shape[1] * 2
        if (
            response.get("status") != "committed"
            or shape != expected_shape
            or int(response.get("tensor_bytes", 0)) != expected_bytes
            or int(response.get("captured_step_count", 0)) != request.latent_steps
            or int(response.get("recurrence_injection_count", -1))
            != request.latent_steps - 1
            or not response.get("tensor_digest")
        ):
            await _safe_rpc(
                engine,
                "statebus_latent_release",
                str(response.get("ref_id", "")),
            )
            raise LatentApiError("latent_capture_incomplete")

        anchor = LatentAnchor(
            evidence_pack_hash=request.anchor.evidence_pack_hash,
            item_ids=tuple(request.anchor.item_ids),
            locator_digest=request.anchor.locator_digest,
        )
        telemetry = LatentProducerTelemetry(
            request_id=request.request_id,
            ref_id=str(response["ref_id"]),
            producer_role=request.producer_role,
            worker_pid=int(response.get("producer_pid", begun.get("worker_pid", 0))),
            engine_id=str(response.get("engine_id", begun.get("engine_id", "vllm-v0"))),
            model_revision=str(
                signature.get("model_revision_or_manifest_digest", "unknown")
            ),
            compatibility_digest=request.expected_compatibility_digest,
            source_evidence_pack_hash=request.anchor.evidence_pack_hash,
            anchor_digest=anchor.anchor_digest,
            latent_steps_requested=request.latent_steps,
            hidden_steps_captured=int(response["captured_step_count"]),
            latent_steps_committed=shape[0],
            recurrence_injection_count=int(response["recurrence_injection_count"]),
            alignment_method=request.alignment_method,
            alignment_config_digest=str(
                signature.get("alignment_config_digest", "")
            ),
            alignment_diagnostics=response.get("alignment_diagnostics", {}),
            raw_hidden_shape=shape,
            aligned_tensor_shape=shape,
            aligned_tensor_dtype=str(response["dtype"]),
            aligned_tensor_bytes=int(response["tensor_bytes"]),
            aligned_tensor_digest=str(response["tensor_digest"]),
            producer_prefill_ms=(rollout_started - begin_started) * 1000.0,
            latent_rollout_ms=rollout_ms,
            registry_commit_ms=registry_commit_ms,
            internal_scheduler_sample_count=int(
                response.get(
                    "internal_scheduler_sample_count", receipt.scheduler_sample_count
                )
            ),
        )
        response["telemetry"] = telemetry.canonical_payload()
        response["telemetry_hash"] = telemetry.telemetry_hash
        self.latent_produce_success_count += 1
        return response

    async def _complete(
        self,
        engine: Any,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        request = LatentCompleteRequestModel.model_validate(body)
        rendered_marker_count = request.rendered_prompt.count(LATENT_MARKER)
        message_marker_count = sum(
            message.content.count(LATENT_MARKER) for message in request.messages
        )
        if (
            rendered_marker_count != 1
            or (request.messages and message_marker_count != 1)
            or (
                request.messages
                and not any(
                    message.content == request.rendered_prompt
                    for message in request.messages
                )
            )
        ):
            raise LatentApiError("latent_position_contract_incompatible")
        health = await self._require_ready(
            engine,
            model=request.model,
            expected_compatibility_digest=request.expected_compatibility_digest,
        )
        tokenizer = await _engine_tokenizer(engine)
        rendered_prompt = (
            _render_messages(tokenizer, request.messages)
            if request.messages
            else request.rendered_prompt
        )
        if rendered_prompt.count(LATENT_MARKER) != 1:
            raise LatentApiError("latent_position_contract_incompatible")
        left_text, right_text = rendered_prompt.split(LATENT_MARKER)
        left_token_ids = _tokenize_without_specials(tokenizer, left_text)
        right_token_ids = _tokenize_without_specials(tokenizer, right_text)
        anchor = LatentAnchor(
            evidence_pack_hash=request.anchor.evidence_pack_hash,
            item_ids=tuple(request.anchor.item_ids),
            locator_digest=request.anchor.locator_digest,
        )

        lease_started = time.perf_counter()
        leased = False
        try:
            materialized_value = await _rpc(
                engine,
                "statebus_latent_materialize_consumer_prompt",
                request.latent_ref_id,
                left_token_ids,
                right_token_ids,
                request.request_id,
                request.expected_compatibility_digest,
                anchor.anchor_digest,
            )
            lease_ms = (time.perf_counter() - lease_started) * 1000.0
            if not isinstance(materialized_value, Mapping):
                raise LatentApiError(
                    "latent_consumer_forward_not_observed", "materialize_response_invalid"
                )
            materialized = materialized_value
            leased = True
            prompt_embeds = materialized.get("prompt_embeds")
            shape = tuple(
                int(value) for value in materialized.get("prompt_embed_shape", ())
            )
            digest = str(materialized.get("prompt_embed_digest", ""))
            dtype = str(materialized.get("prompt_embed_dtype", ""))
            if (
                prompt_embeds is None
                or len(shape) != 2
                or not digest
                or not dtype
                or str(materialized.get("ref_id", "")) != request.latent_ref_id
                or str(materialized.get("compatibility_digest", ""))
                != request.expected_compatibility_digest
            ):
                raise LatentApiError("latent_consumer_forward_not_observed")
            await _rpc(
                engine,
                "statebus_latent_begin_consume",
                request.latent_ref_id,
                request.request_id,
                digest,
                list(shape),
                dtype,
            )
            await _reset_v0_prefix_cache_for_prompt_embeds(engine)
            sampling = _sampling_params(
                temperature=request.sampling.temperature,
                max_tokens=request.sampling.max_tokens,
                seed=request.sampling.seed,
                response_schema=request.response_schema,
            )
            generation_started = time.perf_counter()
            receipt = await _run_generation(
                engine,
                prompt={"prompt_embeds": prompt_embeds},
                sampling_params=sampling,
                request_id=request.request_id,
                retain_text=True,
            )
            consumer_model_ms = (time.perf_counter() - generation_started) * 1000.0
            try:
                described_value = await _rpc(
                    engine,
                    "statebus_latent_describe",
                    request.latent_ref_id,
                )
            except Exception as exc:
                # A worker-side binding mismatch invalidates the ref and the
                # registry intentionally hides invalidated refs as not found.
                # Once generation has run, either condition means there is no
                # acceptable forward receipt; keep the public failure stable.
                mapped = _exception_to_api_error(exc)
                if mapped.error_code == "latent_ref_not_found":
                    raise LatentApiError(
                        "latent_consumer_forward_not_observed"
                    ) from exc
                raise
            if not isinstance(described_value, Mapping):
                raise LatentApiError("latent_consumer_forward_not_observed")
            proof = described_value.get("forward_proof")
            if not _valid_forward_proof(
                described_value,
                proof,
                ref_id=request.latent_ref_id,
                request_id=request.request_id,
                shape=shape,
                dtype=dtype,
                digest=digest,
            ):
                raise LatentApiError("latent_consumer_forward_not_observed")
        except Exception as exc:
            if leased:
                await _safe_rpc(
                    engine,
                    "statebus_latent_release",
                    request.latent_ref_id,
                )
            raise _exception_to_api_error(exc) from exc

        proof = dict(proof)
        latent_count = max(0, shape[0] - len(left_token_ids) - len(right_token_ids))
        telemetry = LatentConsumerTelemetry(
            request_id=request.request_id,
            ref_id=request.latent_ref_id,
            lease_ms=lease_ms,
            compatibility_gate_ms=0.0,
            registry_load_ms=lease_ms,
            h2d_ms=0.0,
            left_token_count=len(left_token_ids),
            right_token_count=len(right_token_ids),
            latent_vector_count=latent_count,
            combined_prompt_embed_shape=shape,
            combined_prompt_embed_bytes=int(
                materialized.get("prompt_embed_bytes", shape[0] * shape[1] * 2)
            ),
            consumer_forward_observed=True,
            consumer_forward_event_id=str(proof.get("event_id", "")),
            consumer_forward_inputs_embeds_shape=tuple(
                int(value) for value in proof.get("inputs_embeds_shape", ())
            ),
            consumer_forward_inputs_embeds_dtype=str(
                proof.get("inputs_embeds_dtype", "")
            ),
            consumer_forward_inputs_embeds_digest=str(
                proof.get("inputs_embeds_digest", "")
            ),
            consumer_model_ms=consumer_model_ms,
            completion_tokens=receipt.completion_tokens,
        )
        self.latent_consume_success_count += 1
        self.latent_success_count += 1
        return {
            "id": f"statebus-latent-completion-{uuid4().hex}",
            "model": request.model,
            "text": receipt.text,
            "consumed_ref_id": request.latent_ref_id,
            "consumer_forward_observed": True,
            "consumer_forward_event_id": str(proof.get("event_id", "")),
            "forward_proof": _sanitize_forward_proof(proof),
            "prompt_embed_shape": list(shape),
            "usage": {
                "prompt_tokens_equivalent": shape[0],
                "completion_tokens": receipt.completion_tokens,
            },
            "telemetry": telemetry.canonical_payload(),
            "telemetry_hash": telemetry.telemetry_hash,
        }

    async def _release(
        self,
        engine: Any,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        request = LatentReleaseRequestModel.model_validate(body)
        released = await _rpc(
            engine,
            "statebus_latent_release",
            request.ref_id,
        )
        if not isinstance(released, Mapping):
            raise LatentApiError("latent_request_invalid", "release_response_invalid")
        return {
            "ref_id": str(released.get("ref_id", request.ref_id)),
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
            raise LatentApiError("latent_plugin_not_ready")
        if str(health.get("model", "")) != model:
            raise LatentApiError("latent_model_incompatible")
        if str(health.get("compatibility_digest", "")) != (
            expected_compatibility_digest
        ):
            raise LatentApiError("latent_model_incompatible")
        return health


async def _rpc(engine: Any, method: str, *args: Any) -> Any:
    if method not in LATENT_RPC_ALLOWLIST:
        raise LatentApiError("latent_request_invalid", "rpc_method_not_allowed")
    collective_rpc = getattr(engine, "collective_rpc", None)
    nested_engine = getattr(engine, "engine", None)
    nested_collective_rpc = getattr(nested_engine, "collective_rpc", None)
    if not callable(collective_rpc) and not callable(nested_collective_rpc):
        raise LatentApiError("latent_plugin_not_ready", "collective_rpc_unavailable")
    try:
        if callable(collective_rpc):
            result = collective_rpc(method, args=tuple(args), kwargs=None)
            try:
                result = await _maybe_await(result)
            except NotImplementedError:
                # vLLM 0.9.2's V0 AsyncLLMEngine wrapper exposes this method
                # but delegates to an unimplemented async hook. Its nested
                # V0 engine retains the synchronous LLMEngine RPC path.
                if not callable(nested_collective_rpc):
                    raise
                result = nested_collective_rpc(method, args=tuple(args), kwargs=None)
        else:
            result = nested_collective_rpc(method, args=tuple(args), kwargs=None)
    except Exception as exc:
        raise _exception_to_api_error(exc) from exc
    if isinstance(result, (list, tuple)):
        if not result:
            raise LatentApiError("latent_plugin_not_ready", "empty_worker_response")
        result = result[0]
    if isinstance(result, BaseException):
        raise _exception_to_api_error(result)
    return result


async def _safe_rpc(engine: Any, method: str, *args: Any) -> None:
    if args and not str(args[0]):
        return
    try:
        await _rpc(engine, method, *args)
    except Exception:
        return


async def _engine_tokenizer(engine: Any) -> Any:
    getter = getattr(engine, "get_tokenizer", None)
    if not callable(getter):
        raise LatentApiError("latent_plugin_not_ready", "tokenizer_unavailable")
    try:
        tokenizer = await _maybe_await(getter())
    except Exception as exc:
        raise LatentApiError("latent_plugin_not_ready", "tokenizer_unavailable") from exc
    if tokenizer is None:
        raise LatentApiError("latent_plugin_not_ready", "tokenizer_unavailable")
    return tokenizer


async def _reset_v0_prefix_cache_for_prompt_embeds(engine: Any) -> None:
    """Prevent V0 from reusing all-zero placeholder keys across embed prompts."""
    nested_engine = getattr(engine, "engine", None)
    # The public AsyncLLMEngine method intentionally discards the V0 boolean
    # result. Prefer the nested engine so an in-use cache still fails closed.
    reset = getattr(nested_engine, "reset_prefix_cache", None)
    if not callable(reset):
        reset = getattr(engine, "reset_prefix_cache", None)
    if not callable(reset):
        raise LatentApiError(
            "latent_consumer_forward_not_observed",
            "prompt_embeds_prefix_cache_reset_unavailable",
        )
    try:
        reset_ok = await _maybe_await(reset())
    except Exception as exc:
        raise LatentApiError(
            "latent_consumer_forward_not_observed",
            "prompt_embeds_prefix_cache_reset_failed",
        ) from exc
    if reset_ok is False:
        raise LatentApiError(
            "latent_consumer_forward_not_observed",
            "prompt_embeds_prefix_cache_reset_failed",
        )


async def _run_generation(
    engine: Any,
    *,
    prompt: Any,
    sampling_params: Any,
    request_id: str,
    retain_text: bool,
) -> _GenerationReceipt:
    generate = getattr(engine, "generate", None)
    if not callable(generate):
        raise LatentApiError("latent_plugin_not_ready", "generate_unavailable")
    try:
        stream = generate(prompt, sampling_params, request_id=request_id)
        stream = await _maybe_await(stream)
        text = ""
        completion_tokens = 0
        scheduler_sample_count = 0
        if hasattr(stream, "__aiter__"):
            async for chunk in stream:
                scheduler_sample_count += 1
                chunk_text, chunk_token_count = _generation_chunk(chunk)
                if chunk_text is not None and retain_text:
                    text = chunk_text
                completion_tokens = max(completion_tokens, chunk_token_count)
        elif isinstance(stream, (str, bytes, Mapping)) or not hasattr(
            stream, "__iter__"
        ):
            scheduler_sample_count = 1
            chunk_text, chunk_token_count = _generation_chunk(stream)
            if chunk_text is not None and retain_text:
                text = chunk_text
            completion_tokens = max(completion_tokens, chunk_token_count)
        else:
            for chunk in stream:
                scheduler_sample_count += 1
                chunk_text, chunk_token_count = _generation_chunk(chunk)
                if chunk_text is not None and retain_text:
                    text = chunk_text
                completion_tokens = max(completion_tokens, chunk_token_count)
    except Exception as exc:
        raise _exception_to_api_error(exc) from exc

    return _GenerationReceipt(
        text=text if retain_text else "",
        completion_tokens=completion_tokens,
        scheduler_sample_count=scheduler_sample_count,
    )


def _generation_chunk(chunk: Any) -> tuple[str | None, int]:
    if chunk is None:
        return None, 0
    outputs = (
        chunk.get("outputs", ()) if isinstance(chunk, Mapping) else getattr(chunk, "outputs", ())
    )
    if outputs:
        candidate = outputs[0]
        text_value = (
            candidate.get("text")
            if isinstance(candidate, Mapping)
            else getattr(candidate, "text", None)
        )
        token_ids = (
            candidate.get("token_ids", ())
            if isinstance(candidate, Mapping)
            else getattr(candidate, "token_ids", ())
        )
        return None if text_value is None else str(text_value), len(token_ids or ())
    if isinstance(chunk, Mapping):
        text_value = chunk.get("text")
        token_ids = chunk.get("token_ids", ())
        return None if text_value is None else str(text_value), len(token_ids or ())
    if isinstance(chunk, str):
        return chunk, 0
    text_value = getattr(chunk, "text", None)
    token_ids = getattr(chunk, "token_ids", ())
    return None if text_value is None else str(text_value), len(token_ids or ())


def _sampling_params(
    *,
    temperature: float,
    max_tokens: int,
    seed: int,
    ignore_eos: bool = False,
    response_schema: Mapping[str, Any] | None = None,
) -> Any:
    guided: Any | None = None
    if response_schema:
        try:
            from vllm.sampling_params import GuidedDecodingParams

            guided = GuidedDecodingParams(
                json=dict(response_schema),
                backend="xgrammar",
                disable_any_whitespace=True,
            )
        except ImportError:
            guided = {
                "json": dict(response_schema),
                "backend": "xgrammar",
                "disable_any_whitespace": True,
            }
    try:
        from vllm import SamplingParams

        return SamplingParams(
            temperature=float(temperature),
            max_tokens=int(max_tokens),
            seed=int(seed),
            ignore_eos=bool(ignore_eos),
            guided_decoding=guided,
        )
    except ImportError:
        return _SamplingParamsFallback(
            temperature=float(temperature),
            max_tokens=int(max_tokens),
            seed=int(seed),
            ignore_eos=bool(ignore_eos),
            guided_decoding=guided,
        )


def _render_messages(tokenizer: Any, messages: list[Any]) -> str:
    payload = [
        {"role": str(message.role), "content": str(message.content)}
        for message in messages
    ]
    apply_template = getattr(tokenizer, "apply_chat_template", None)
    if callable(apply_template):
        try:
            rendered = apply_template(
                payload,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            if isinstance(rendered, str) and rendered:
                return rendered
        except TypeError:
            try:
                rendered = apply_template(
                    payload,
                    tokenize=False,
                    add_generation_prompt=True,
                )
                if isinstance(rendered, str) and rendered:
                    return rendered
            except TypeError:
                rendered = apply_template(payload, tokenize=False)
                if isinstance(rendered, str) and rendered:
                    return rendered
    return chr(10).join(
        f"{message['role']}: {message['content']}" for message in payload
    )


def _tokenize_without_specials(tokenizer: Any, text: str) -> list[int]:
    encode = getattr(tokenizer, "encode", None)
    if callable(encode):
        try:
            value = encode(text, add_special_tokens=False)
        except TypeError:
            value = encode(text)
    elif callable(tokenizer):
        value = tokenizer(text, add_special_tokens=False)
        if isinstance(value, Mapping):
            value = value.get("input_ids", ())
    else:
        raise LatentApiError("latent_plugin_not_ready", "tokenizer_unavailable")
    if hasattr(value, "tolist"):
        value = value.tolist()
    if value and isinstance(value[0], (list, tuple)):
        value = value[0]
    try:
        return [int(token_id) for token_id in value]
    except (TypeError, ValueError) as exc:
        raise LatentApiError("latent_request_invalid", "tokenization_failed") from exc


def _sanitize_health_payload(capabilities: Mapping[str, Any]) -> dict[str, Any]:
    errors = [str(value) for value in capabilities.get("errors", ())]
    ready = (
        str(capabilities.get("status", "")) == "ready"
        and bool(capabilities.get("worker_extension_ready", False))
        and bool(capabilities.get("prompt_embeds_enabled", False))
        and int(capabilities.get("max_num_seqs", 0)) == 1
        and not errors
    )
    signature = capabilities.get("compatibility_signature", {})
    if not isinstance(signature, Mapping):
        signature = {}
        ready = False
        errors.append("compatibility_signature_invalid")
    payload = {
        "status": "ready" if ready else "not_ready",
        "plugin_version": LATENT_PLUGIN_VERSION,
        "worker_plugin_version": str(capabilities.get("plugin_version", "")),
        "vllm_version": str(capabilities.get("vllm_version", "")),
        "engine_generation": str(capabilities.get("engine_generation", "")),
        "model": str(capabilities.get("model", "")),
        "hidden_size": int(capabilities.get("hidden_size", 0)),
        "prompt_embeds_enabled": bool(
            capabilities.get("prompt_embeds_enabled", False)
        ),
        "worker_extension_ready": bool(
            capabilities.get("worker_extension_ready", False)
        ),
        "max_num_seqs": int(capabilities.get("max_num_seqs", 0)),
        "tensor_parallel_size": int(
            capabilities.get("tensor_parallel_size", 0)
        ),
        "pipeline_parallel_size": int(
            capabilities.get("pipeline_parallel_size", 0)
        ),
        "compatibility_signature": dict(signature),
        "compatibility_digest": str(
            capabilities.get("compatibility_digest", "")
        ),
        "registry_entries": int(capabilities.get("registry_entries", 0)),
        "registry_bytes": int(capabilities.get("registry_bytes", 0)),
        "registry_max_entries": int(
            capabilities.get("registry_max_entries", 0)
        ),
        "registry_max_bytes": int(capabilities.get("registry_max_bytes", 0)),
        "registry_max_steps": int(capabilities.get("registry_max_steps", 0)),
        "errors": sorted(set(errors)),
    }
    payload["health_digest"] = sha256_digest(payload)
    return payload


def _signature_payload(health: Mapping[str, Any]) -> Mapping[str, Any]:
    signature = health.get("compatibility_signature", {})
    if not isinstance(signature, Mapping):
        raise LatentApiError("latent_plugin_not_ready", "signature_unavailable")
    return signature


def _sanitize_produce_result(value: Mapping[str, Any]) -> dict[str, Any]:
    nested = value.get("ref", {})
    ref = nested if isinstance(nested, Mapping) else {}

    def field(name: str, default: Any = "") -> Any:
        return value.get(name, ref.get(name, default))

    shape = field("shape", ())
    return {
        "ref_id": str(field("ref_id")),
        "status": str(field("status")),
        "dtype": str(field("dtype")),
        "shape": [int(item) for item in shape],
        "tensor_bytes": int(field("tensor_bytes", 0)),
        "tensor_digest": str(field("tensor_digest")),
        "captured_step_count": int(field("captured_step_count", 0)),
        "recurrence_injection_count": int(
            field("recurrence_injection_count", 0)
        ),
        "internal_scheduler_sample_count": int(
            field("internal_scheduler_sample_count", 0)
        ),
        "alignment_diagnostics": sanitize_alignment_diagnostics(
            field("alignment_diagnostics", {})
        ),
        "producer_pid": int(field("producer_pid", 0)),
        "engine_id": str(field("engine_id", "vllm-v0")),
        "created_at_ns": int(field("created_at_ns", 0)),
        "expires_at_ns": int(field("expires_at_ns", 0)),
        "source_layer_index": int(field("source_layer_index", -1)),
        "compatibility_digest": str(field("compatibility_digest")),
    }


def _valid_forward_proof(
    described: Mapping[str, Any],
    proof: Any,
    *,
    ref_id: str,
    request_id: str,
    shape: tuple[int, ...],
    dtype: str,
    digest: str,
) -> bool:
    if str(described.get("status", "")) != "consumed" or not isinstance(
        proof, Mapping
    ):
        return False
    return (
        str(proof.get("proof_kind", "")) == "worker_forward"
        and str(proof.get("ref_id", "")) == ref_id
        and str(proof.get("request_id", "")) == request_id
        and tuple(int(value) for value in proof.get("inputs_embeds_shape", ()))
        == shape
        and str(proof.get("inputs_embeds_dtype", "")) == dtype
        and str(proof.get("inputs_embeds_digest", "")) == digest
        and bool(proof.get("event_id"))
    )


def _sanitize_forward_proof(proof: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ref_id": str(proof.get("ref_id", "")),
        "request_id": str(proof.get("request_id", "")),
        "worker_pid": int(proof.get("worker_pid", 0)),
        "engine_id": str(proof.get("engine_id", "")),
        "inputs_embeds_shape": [
            int(value) for value in proof.get("inputs_embeds_shape", ())
        ],
        "inputs_embeds_dtype": str(proof.get("inputs_embeds_dtype", "")),
        "inputs_embeds_digest": str(proof.get("inputs_embeds_digest", "")),
        "observed_at_ns": int(proof.get("observed_at_ns", 0)),
        "event_id": str(proof.get("event_id", "")),
        "proof_kind": str(proof.get("proof_kind", "")),
    }


def _exception_to_api_error(exc: BaseException) -> LatentApiError:
    if isinstance(exc, LatentApiError):
        return exc
    error_code = str(getattr(exc, "error_code", ""))
    if error_code in LATENT_ERROR_CODES:
        return LatentApiError(error_code)
    message = str(exc)
    for candidate in sorted(LATENT_ERROR_CODES, key=len, reverse=True):
        if candidate in message:
            return LatentApiError(candidate)
    return LatentApiError("latent_request_invalid", "backend_operation_failed")


def _error_payload(error_code: str, detail: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": {"code": error_code},
        "error_code": error_code,
    }
    if detail:
        payload["error"]["detail"] = detail
    return payload


async def _send_json(send: ASGISend, status_code: int, payload: Any) -> None:
    body = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": int(status_code),
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


def _request_path(scope: ASGIScope) -> str:
    path = str(scope.get("path", ""))
    root_path = str(scope.get("root_path", ""))
    if root_path and path.startswith(root_path):
        path = path[len(root_path) :]
    return path or "/"


def _header_value(scope: ASGIScope, wanted: bytes) -> str:
    for raw_name, raw_value in scope.get("headers", ()):
        name = raw_name if isinstance(raw_name, bytes) else str(raw_name).encode()
        if name.lower() == wanted:
            if isinstance(raw_value, bytes):
                return raw_value.decode("latin-1")
            return str(raw_value)
    return ""


def _is_loopback(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    if normalized in {"127.0.0.1", "::1", "localhost"}:
        return True
    if normalized.startswith("::ffff:"):
        normalized = normalized.removeprefix("::ffff:")
    octets = normalized.split(".")
    return (
        len(octets) == 4
        and octets[0] == "127"
        and all(part.isdigit() and 0 <= int(part) <= 255 for part in octets)
    )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = [
    "LATENT_API_PREFIX",
    "LATENT_ERROR_CODES",
    "LATENT_MARKER",
    "LATENT_PLUGIN_VERSION",
    "LATENT_RPC_ALLOWLIST",
    "LatentApiError",
    "LatentHandoffMiddleware",
]
