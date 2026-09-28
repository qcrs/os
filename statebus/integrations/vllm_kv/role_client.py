from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Any

from statebus.integrations.llm import (
    ChatMessage,
    LLMClient,
    LLMResult,
    LLMUsage,
    normalize_comparator_role_name,
)
from statebus.integrations.vllm_kv.client import VllmKVClient
from statebus.integrations.vllm_kv.tokenizer_client import VllmTokenCodec
from statebus.runtime.model_assist import (
    ModelAssistHandoff,
    make_apc_observation,
    make_logit_observation,
)
from statebus.runtime.prefix_identity import shared_prefix_envelope
from statebus.utils import sha256_digest


AUDIT_SCHEMA_VERSION = "statebus.engine_local_kv_mainline_audit.v1"
VALID_MODES = {"off", "full_replay", "continuation", "auto"}


class KVPreflightError(ValueError):
    """The request was not sent; an auto profile may use ordinary LLM."""


@dataclass(frozen=True)
class EngineLocalKVRoleClientConfig:
    mode: str
    task_id: str
    audit_path: Path
    model: str = "qwen3-32b"
    parent_tokens: int = 0
    ttl_s: int = 300
    seed: int = 7
    executor_max_tokens: int = 96
    summarizer_max_tokens: int = 128
    executor_response_schema: dict[str, Any] | None = None
    summarizer_response_schema: dict[str, Any] | None = None
    logprobs: bool = False
    top_logprobs: int = 0
    profile: str = "kv_continuation"
    shared_prefix_text: str = ""
    kv_base_url: str = ""
    kv_timeout_s: float = 180.0
    tokenizer_timeout_s: float = 60.0
    chat_template_kwargs: dict[str, Any] | None = None

    @classmethod
    def from_env(cls, *, task_id: str, runtime_root: Path) -> "EngineLocalKVRoleClientConfig":
        mode = os.getenv("STATEBUS_ENGINE_LOCAL_KV_MODE", "off").strip().lower()
        if mode not in VALID_MODES:
            raise ValueError(f"unsupported engine-local KV mode: {mode}")
        return cls(
            mode=mode,
            task_id=task_id,
            audit_path=runtime_root / "engine_local_kv_mainline.json",
            model=os.getenv("STATEBUS_ENGINE_LOCAL_KV_MODEL", "qwen3-32b").strip(),
            parent_tokens=max(0, int(os.getenv("STATEBUS_ENGINE_LOCAL_KV_PARENT_TOKENS", "0"))),
            ttl_s=int(os.getenv("STATEBUS_ENGINE_LOCAL_KV_TTL_S", "300")),
            seed=int(os.getenv("STATEBUS_ENGINE_LOCAL_KV_SEED", "7")),
            executor_max_tokens=int(
                os.getenv("STATEBUS_ENGINE_LOCAL_KV_EXECUTOR_MAX_TOKENS", "96")
            ),
            summarizer_max_tokens=int(
                os.getenv("STATEBUS_ENGINE_LOCAL_KV_SUMMARIZER_MAX_TOKENS", "128")
            ),
            kv_base_url=os.getenv("STATEBUS_KV_API_BASE_URL", "").strip(),
            kv_timeout_s=float(os.getenv("STATEBUS_KV_API_TIMEOUT_S", "180")),
            tokenizer_timeout_s=float(os.getenv("STATEBUS_KV_TOKENIZER_TIMEOUT_S", "60")),
            chat_template_kwargs={"enable_thinking": False},
        )


class EngineLocalKVRoleClient:
    """Task-local Executor-to-Summarizer KV acceleration sideband.

    The normal role client remains authoritative for Planner and Retriever. The
    private token API is used only for the two adjacent roles under test.
    """

    def __init__(
        self,
        delegate: LLMClient,
        config: EngineLocalKVRoleClientConfig,
        *,
        kv_client: Any | None = None,
        token_codec: Any | None = None,
        handoff: ModelAssistHandoff | None = None,
    ) -> None:
        if config.mode not in VALID_MODES or config.mode == "off":
            raise ValueError("EngineLocalKVRoleClient requires an enabled mode")
        if config.parent_tokens < 0 or config.ttl_s <= 0:
            raise ValueError("parent_tokens must be non-negative and ttl_s positive")
        self.delegate = delegate
        self.config = config
        self.kv_client = kv_client or VllmKVClient(
            base_url=config.kv_base_url or os.getenv("STATEBUS_KV_API_BASE_URL", "http://127.0.0.1:53334"),
            timeout_s=config.kv_timeout_s,
        )
        self.token_codec = token_codec or VllmTokenCodec(
            base_url=config.kv_base_url or os.getenv("STATEBUS_KV_API_BASE_URL", "http://127.0.0.1:53334"),
            model=config.model,
            timeout_s=config.tokenizer_timeout_s,
        )
        self.handoff = handoff or ModelAssistHandoff(task_id=config.task_id)
        if self.handoff.task_id and self.handoff.task_id != config.task_id:
            raise ValueError("model assist handoff task mismatch")
        self.handoff.task_id = config.task_id
        self._health: dict[str, Any] | None = None
        self._request_index = 0
        self._request_events: list[dict[str, object]] = []
        self._last_observation: dict[str, Any] | None = None
        self._pair_active = True
        self._audit: dict[str, Any] = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "task_id": config.task_id,
            "mode": config.mode,
            "model": config.model,
            "target_parent_tokens": config.parent_tokens,
            "producer_calls": [],
            "consumer_calls": [],
            "release_calls": [],
            "capture_count": 0,
            "load_count": 0,
            "fallback_count": 0,
            "status": "initialized",
        }
        self._write_audit()

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        purpose: str,
        temperature: float | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        role = normalize_comparator_role_name(purpose)
        if role not in {"executor", "summarizer"}:
            return await self.delegate.complete(
                messages,
                purpose=role,
                temperature=temperature,
                response_schema=response_schema,
            )
        messages = list(messages)
        if role == "executor":
            if not self._pair_active:
                return await self.delegate.complete(
                    messages,
                    purpose=role,
                    temperature=temperature,
                    response_schema=response_schema,
                )
            try:
                return self._produce(messages, temperature=temperature, response_schema=response_schema)
            except KVPreflightError:
                if self.config.mode != "auto":
                    raise
                self._last_observation = {
                    "profile": self.config.profile,
                    "requested_mode": self.config.profile,
                    "preflight_checked": True,
                    "effective_mode": "ordinary",
                    "route_reason": "auto_kv_preflight_ineligible",
                    "observations": {
                        "kv": {"status": "unavailable", "reason": "preflight_ineligible"},
                        "logit": make_logit_observation(None),
                        "apc": make_apc_observation(service_enabled=False),
                    },
                }
                return await self.delegate.complete(
                    messages,
                    purpose=role,
                    temperature=temperature,
                    response_schema=response_schema,
                )
        if not self._pair_active:
            return await self.delegate.complete(
                messages,
                purpose=role,
                temperature=temperature,
                response_schema=response_schema,
            )
        if not self.producer_ready:
            self._last_observation = {
                "profile": self.config.profile,
                "requested_mode": self.config.profile,
                "preflight_checked": False,
                "effective_mode": "ordinary",
                "route_reason": "auto_no_reusable_handle",
                "observations": {
                    "kv": {"status": "unavailable", "reason": "handle_missing"},
                    "logit": make_logit_observation(None),
                    "apc": make_apc_observation(service_enabled=False),
                },
            }
            if self.config.mode == "auto":
                return await self.delegate.complete(
                    messages,
                    purpose=role,
                    temperature=temperature,
                    response_schema=response_schema,
                )
            raise KVPreflightError("summarizer called before KV producer")
        try:
            return self._consume(messages, temperature=temperature, response_schema=response_schema)
        except KVPreflightError:
            if self.config.mode != "auto":
                raise
            self._last_observation = {
                "profile": self.config.profile,
                "requested_mode": self.config.profile,
                "preflight_checked": True,
                "effective_mode": "ordinary",
                "route_reason": "auto_consumer_preflight_ineligible",
                "observations": {
                    "kv": {"status": "unavailable", "reason": "consumer_preflight_ineligible"},
                    "logit": make_logit_observation(None),
                    "apc": make_apc_observation(service_enabled=False),
                },
            }
            return await self.delegate.complete(
                messages,
                purpose=role,
                temperature=temperature,
                response_schema=response_schema,
            )

    @property
    def producer_ready(self) -> bool:
        return bool(self.handoff.parent_token_ids) and bool(self.handoff.producer_attempt)

    @property
    def pair_active(self) -> bool:
        return self._pair_active

    def preflight_ready(self) -> bool:
        """Return whether the private service passed its cached identity check.

        ``auto`` uses this before selecting the private client.  A failed
        health or identity check is an ordinary-route fact, not a generation
        failure; explicit KV modes still call the normal path and fail
        clearly when the same check is not satisfied.
        """

        try:
            self._ready_health()
        except (KVPreflightError, KeyError, TypeError, ValueError, OSError):
            return False
        return True

    def disable_pair(self) -> None:
        self._pair_active = False
        self._release("pair_disabled")

    def describe_role(self, role: str) -> dict[str, object]:
        describe_role = getattr(self.delegate, "describe_role", None)
        if callable(describe_role):
            payload = dict(describe_role(role))
        else:
            payload = dict(self.delegate.describe())
        payload["engine_local_kv_mode"] = self.config.mode
        payload["model_assist_profile"] = self.config.profile
        payload["engine_local_kv_role"] = normalize_comparator_role_name(role)
        return payload

    def describe(self) -> dict[str, object]:
        return {
            **dict(self.delegate.describe()),
            "engine_local_kv_mode": self.config.mode,
            "model_assist_profile": self.config.profile,
            "engine_local_kv_parent_tokens": self.config.parent_tokens,
        }

    def close(self) -> None:
        self._release("client_close")
        for client in (self.kv_client, self.token_codec):
            close = getattr(client, "close", None)
            if callable(close):
                close()

    @property
    def audit_payload(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._audit))

    @property
    def request_events(self) -> list[dict[str, object]]:
        events = getattr(self.delegate, "request_events", ())
        combined = [
            *[dict(item) for item in events if isinstance(item, dict)],
            *[dict(item) for item in self._request_events],
        ]
        return sorted(combined, key=lambda item: int(item.get("start_ns", 0) or 0))

    @property
    def local_request_events(self) -> list[dict[str, object]]:
        """Private KV events, excluding the ordinary delegate history."""
        return [dict(item) for item in self._request_events]

    def take_model_assist_observation(self) -> dict[str, Any] | None:
        observation = self._last_observation
        self._last_observation = None
        return None if observation is None else json.loads(json.dumps(observation))

    def _produce(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        self._release("producer_replaced")
        health = self._ready_health()
        prompt_ids = self._encode_messages(messages)
        self._validate_shared_prefix(messages)
        block_size = int(health["block_size"])
        # The configured parent is only an upper bound.  When the serving
        # tokenizer supports exact message encoding, derive the boundary from
        # the actual executor/summarizer requests so role-specific suffixes
        # cannot be included in the shared parent.  Lightweight test codecs
        # without message encoding retain the explicit-token fallback.
        if callable(getattr(self.token_codec, "encode_messages", None)):
            common_prefix_tokens = self._common_prefix_token_count(prompt_ids)
        else:
            common_prefix_tokens = self.config.parent_tokens
        parent_cap = self.config.parent_tokens or common_prefix_tokens
        parent_count = min(parent_cap, common_prefix_tokens)
        parent_count -= parent_count % block_size
        if parent_count <= 0 or len(prompt_ids) <= parent_count:
            raise KVPreflightError(
                f"executor prompt has {len(prompt_ids)} tokens; cannot split a {block_size}-aligned "
                f"parent from {common_prefix_tokens} shared tokens"
            )
        if parent_count > 8192:
            raise KVPreflightError("executor parent exceeds private API limit")
        parent_ids = prompt_ids[:parent_count]
        suffix_ids = prompt_ids[parent_count:]
        if len(suffix_ids) > 4096:
            raise KVPreflightError(f"executor suffix exceeds private API limit: {len(suffix_ids)}")
        self._validate_context_budget(
            prompt_ids,
            health=health,
            max_tokens=self.config.executor_max_tokens,
        )
        self.handoff.parent_token_ids = parent_ids
        self.handoff.parent_token_digest = sha256_digest(list(parent_ids))
        capture = self.config.mode in {"continuation", "auto"}
        request_id = self._request_id("producer")
        self.handoff.producer_attempt = request_id
        self.handoff.consumer_role = "summarizer"
        started_ns = time.perf_counter_ns()
        try:
            payload = self.kv_client.produce(
                {
                    "model": self.config.model,
                    "request_id": request_id,
                    "task_id": self.config.task_id,
                    "parent_token_ids": list(parent_ids),
                    "producer_suffix_token_ids": list(suffix_ids),
                    "capture_kv": capture,
                    "ttl_s": self.config.ttl_s,
                    "sampling": self._sampling(
                        temperature=temperature,
                        max_tokens=self.config.executor_max_tokens,
                    ),
                    "expected_compatibility_digest": health["compatibility_digest"],
                    "response_schema": response_schema or self.config.executor_response_schema,
                    "logprobs": bool(self.config.logprobs),
                    "top_logprobs": int(self.config.top_logprobs),
                }
            )
            handle_id = str(payload.get("handle_id", ""))
            if handle_id:
                # Keep the returned id visible to cleanup while the receipt is
                # still being validated.
                self.handoff.handle_id = handle_id
            if capture and not handle_id:
                raise RuntimeError("KV producer did not return a handle")
            if capture and str(payload.get("engine_generation", "")) != str(health.get("engine_generation", "")):
                raise RuntimeError("KV producer generation mismatch")
            handle_metadata = dict(payload.get("handle") or {})
            if capture:
                self._validate_handle_metadata(
                    handle_metadata,
                    health=health,
                    task_id=self.config.task_id,
                    token_digest=self.handoff.parent_token_digest,
                    seq_len=len(parent_ids),
                    producer_request_id=request_id,
                    handle_id=handle_id,
                )
            self.handoff.handle_metadata = handle_metadata
            self.handoff.generation = str(health.get("engine_generation", ""))
            telemetry = dict(payload.get("telemetry") or {})
            output_ids = tuple(int(value) for value in payload.get("output_token_ids", ()))
            record = {
                "request_id": request_id,
                "success": True,
                "capture_kv": capture,
                "handle_id": handle_id,
                "logical_prompt_tokens": len(prompt_ids),
                "parent_tokens": len(parent_ids),
                "suffix_tokens": len(suffix_ids),
                "logical_token_digest": sha256_digest(list(prompt_ids)),
                "parent_token_digest": sha256_digest(list(parent_ids)),
                "output_token_digest": sha256_digest(list(output_ids)),
                "output_text_digest": sha256_digest(str(payload.get("output_text", ""))),
                "client_wall_ms": self._elapsed_ms(started_ns),
                "telemetry": telemetry,
            }
            self._audit["producer_calls"].append(record)
            self._audit["capture_count"] += int(capture)
            self._audit["status"] = "producer_complete"
            self._record_request_event(
                request_id,
                stage="producer",
                status="success",
                started_ns=started_ns,
                finish_reason=str(payload.get("finish_reason")) if payload.get("finish_reason") else None,
                logical_prompt_tokens=len(prompt_ids),
                logical_completion_tokens=len(output_ids),
            )
            self._last_observation = {
                "profile": self.config.profile,
                "requested_mode": self.config.profile,
                "preflight_checked": True,
                "effective_mode": "kv_continuation" if capture else "full_replay",
                "route_reason": "kv_capture_ready" if capture else "explicit_full_replay",
                "observations": {
                    "kv": {
                        "status": "available",
                        "lane": "capture" if capture else "full_replay",
                        "parent_tokens": len(parent_ids),
                        "engine_generation": str(health.get("engine_generation", "")),
                    },
                    "logit": make_logit_observation(payload.get("top_logprobs")),
                    "apc": {
                        "status": "unavailable",
                        "available": False,
                        "service_enabled": False,
                        "metrics_available": False,
                        "delta_valid": False,
                        "reason": "explicit_kv_requires_apc_disabled",
                    },
                },
            }
            self._write_audit()
            return self._llm_result(payload, prompt_tokens=len(prompt_ids), output_ids=output_ids)
        except Exception as exc:
            self._record_error("producer", request_id, exc)
            self._record_request_event(
                request_id,
                stage="producer",
                status="error",
                started_ns=started_ns,
                error=exc,
            )
            self._release("producer_error")
            raise

    def _consume(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        health = self._ready_health()
        prompt_ids = self._encode_messages(messages)
        self._validate_shared_prefix(messages)
        parent_ids = self.handoff.parent_token_ids
        parent_count = len(parent_ids)
        if not parent_count:
            raise KVPreflightError("summarizer called before KV producer")
        if len(prompt_ids) <= parent_count or prompt_ids[:parent_count] != parent_ids:
            self._record_error("consumer", "prefix", ValueError("shared parent token IDs do not match"))
            self._release("consumer_prefix_mismatch")
            raise KVPreflightError("executor and summarizer shared parent token IDs do not match")
        if str(self.handoff.generation) != str(health.get("engine_generation", "")):
            self._record_error("consumer", "generation", ValueError("engine generation mismatch"))
            self._release("consumer_generation_mismatch")
            raise KVPreflightError("engine generation mismatch")
        handle_metadata = self.handoff.handle_metadata
        if self.handoff.handle_id:
            try:
                self._validate_handle_metadata(
                    handle_metadata,
                    health=health,
                    task_id=self.config.task_id,
                    token_digest=self.handoff.parent_token_digest,
                    seq_len=parent_count,
                    producer_request_id=self.handoff.producer_attempt,
                    handle_id=self.handoff.handle_id,
                )
            except KVPreflightError:
                self._release("consumer_handle_metadata_mismatch")
                raise
        suffix_ids = prompt_ids[parent_count:]
        if len(suffix_ids) > 4096:
            self._release("consumer_suffix_limit")
            raise KVPreflightError(f"summarizer suffix exceeds private API limit: {len(suffix_ids)}")
        self._validate_context_budget(
            prompt_ids,
            health=health,
            max_tokens=self.config.summarizer_max_tokens,
        )
        use_kv = self.config.mode in {"continuation", "auto"} and bool(self.handoff.handle_id)
        lane = "kv_continuation" if use_kv else "full_replay"
        if self.config.mode == "continuation" and not use_kv:
            self._audit["status"] = "failed"
            self._write_audit()
            raise RuntimeError("explicit KV continuation handle is unavailable")
        request: dict[str, Any] = {
            "model": self.config.model,
            "request_id": self._request_id("consumer"),
            "task_id": self.config.task_id,
            "lane": lane,
            "suffix_token_ids": list(suffix_ids),
            "sampling": self._sampling(
                temperature=temperature,
                max_tokens=self.config.summarizer_max_tokens,
            ),
            "expected_compatibility_digest": health["compatibility_digest"],
            "response_schema": response_schema or self.config.summarizer_response_schema,
            "logprobs": bool(self.config.logprobs),
            "top_logprobs": int(self.config.top_logprobs),
        }
        if use_kv:
            request["handle_id"] = self.handoff.handle_id
        else:
            request["parent_token_ids"] = list(parent_ids)
        started_ns = time.perf_counter_ns()
        try:
            stream = self.kv_client.continue_stream(request)
            payload = dict(stream.payload)
            expected_digest = sha256_digest(list(prompt_ids))
            if str(payload.get("logical_token_digest", "")) != expected_digest:
                raise RuntimeError("consumer logical token digest mismatch")
            if use_kv and str(payload.get("engine_generation", "")) != str(health.get("engine_generation", "")):
                raise RuntimeError("consumer generation receipt mismatch")
            telemetry = dict(payload.get("telemetry") or {})
            output_ids = tuple(int(value) for value in payload.get("output_token_ids", ()))
            record = {
                "request_id": request["request_id"],
                "success": True,
                "lane": lane,
                "handle_id": self.handoff.handle_id if use_kv else "",
                "logical_prompt_tokens": len(prompt_ids),
                "parent_tokens": parent_count,
                "suffix_tokens": len(suffix_ids),
                "logical_token_digest": expected_digest,
                "output_token_digest": sha256_digest(list(output_ids)),
                "output_text_digest": sha256_digest(str(payload.get("output_text", ""))),
                "client_ttft_ms": float(stream.client_ttft_ms),
                "client_wall_ms": float(stream.client_wall_ms),
                "measured_call_wall_ms": self._elapsed_ms(started_ns),
                "api_request_bytes": int(stream.api_request_bytes),
                "token_event_count": int(stream.token_event_count),
                "telemetry": telemetry,
            }
            self._audit["consumer_calls"].append(record)
            self._audit["load_count"] += int(telemetry.get("connector_load_count", 0))
            self._audit["status"] = "consumer_complete"
            self._record_request_event(
                str(request["request_id"]),
                stage="consumer",
                status="success",
                started_ns=started_ns,
                finish_reason=str(payload.get("finish_reason")) if payload.get("finish_reason") else None,
                logical_prompt_tokens=len(prompt_ids),
                logical_completion_tokens=len(output_ids),
            )
            self._last_observation = {
                "profile": self.config.profile,
                "requested_mode": self.config.profile,
                "preflight_checked": True,
                "effective_mode": lane,
                "route_reason": "same_worker_handle" if use_kv else "full_replay",
                "observations": {
                    "kv": {
                        "status": "available",
                        "lane": lane,
                        "inherited_kv_tokens": int(telemetry.get("inherited_kv_tokens", 0)),
                        "computed_prefill_tokens": int(telemetry.get("computed_prefill_tokens", len(prompt_ids))),
                    },
                    "logit": make_logit_observation(payload.get("top_logprobs")),
                    "apc": {
                        "status": "unavailable",
                        "available": False,
                        "service_enabled": False,
                        "metrics_available": False,
                        "delta_valid": False,
                        "reason": "explicit_kv_requires_apc_disabled",
                    },
                },
            }
            return self._llm_result(payload, prompt_tokens=len(prompt_ids), output_ids=output_ids)
        except Exception as exc:
            self._record_error("consumer", str(request["request_id"]), exc)
            self._record_request_event(
                str(request["request_id"]),
                stage="consumer",
                status="error",
                started_ns=started_ns,
                error=exc,
            )
            raise
        finally:
            if use_kv or self.config.mode in {"continuation", "auto"}:
                self._release("consumer_complete")
            self._write_audit()

    def _ready_health(self) -> dict[str, Any]:
        if self._health is None:
            try:
                health = dict(self.kv_client.health())
            except Exception as exc:
                raise KVPreflightError("engine-local KV health unavailable") from exc
            if health.get("status") != "ready":
                raise KVPreflightError("engine-local KV service is not ready")
            required_identity = (
                "engine_id",
                "engine_generation",
                "model",
                "model_revision",
                "tokenizer_digest",
                "dtype",
                "compatibility_digest",
            )
            missing = [name for name in required_identity if not str(health.get(name, ""))]
            signature = health.get("compatibility_signature")
            if not isinstance(signature, dict):
                missing.append("compatibility_signature")
            if missing:
                raise KVPreflightError(
                    f"engine-local KV health identity incomplete: {','.join(missing)}"
                )
            if str(health["model"]) != self.config.model:
                raise KVPreflightError("engine-local KV model mismatch")
            if int(health.get("block_size", 0)) <= 0:
                raise KVPreflightError("engine-local KV block size is invalid")
            if bool(health.get("automatic_prefix_caching", True)):
                raise KVPreflightError("automatic prefix caching must be disabled for explicit KV")
            self._health = health
            self._audit["health"] = health
            self._write_audit()
        return self._health

    def _encode_prompt(self, prompt: str) -> tuple[int, ...]:
        try:
            return tuple(int(value) for value in self.token_codec.encode(prompt))
        except Exception as exc:
            raise KVPreflightError("tokenizer preflight unavailable") from exc

    def _encode_messages(self, messages: list[ChatMessage]) -> tuple[int, ...]:
        encode_messages = getattr(self.token_codec, "encode_messages", None)
        if callable(encode_messages):
            try:
                return tuple(
                    int(value)
                    for value in encode_messages(
                        [{"role": item.role, "content": item.content} for item in messages],
                        add_generation_prompt=True,
                        chat_template_kwargs=self.config.chat_template_kwargs or {"enable_thinking": False},
                    )
                )
            except Exception as exc:
                raise KVPreflightError("exact messages tokenizer unavailable") from exc
        if len(messages) == 1 and messages[0].role == "user" and messages[0].content:
            return self._encode_prompt(messages[0].content)
        raise KVPreflightError("exact messages tokenizer unavailable")

    def _validate_shared_prefix(self, messages: list[ChatMessage]) -> None:
        if not self.config.shared_prefix_text.strip():
            return
        envelope = shared_prefix_envelope(self.config.shared_prefix_text)
        if not messages or not str(messages[0].content).startswith(envelope):
            raise KVPreflightError("shared prefix is not an exact model input prefix")

    @staticmethod
    def _validate_context_budget(
        prompt_ids: tuple[int, ...],
        *,
        health: dict[str, Any],
        max_tokens: int,
    ) -> None:
        max_model_len = int(health.get("max_model_len", 0) or 0)
        if max_model_len and len(prompt_ids) + int(max_tokens) > max_model_len:
            raise KVPreflightError("private API context budget exceeded")

    def _common_prefix_token_count(self, prompt_ids: tuple[int, ...]) -> int:
        """Find the real token boundary before role-specific content.

        The provider messages are the authority for tokenization.  A short
        role probe lets us locate the first differing token without assuming
        that separately encoded text can be concatenated safely.
        """
        if not self.config.shared_prefix_text.strip():
            raise KVPreflightError("shared prefix is unavailable")
        prefix = shared_prefix_envelope(self.config.shared_prefix_text)
        probe = [
            {
                "role": "system",
                "content": prefix + '<statebus-role-suffix-v2 role="summarizer">\n',
            }
        ]
        encode_messages = getattr(self.token_codec, "encode_messages", None)
        if not callable(encode_messages):
            raise KVPreflightError("exact messages tokenizer unavailable")
        try:
            probe_ids = tuple(
                int(value)
                for value in encode_messages(
                    probe,
                    add_generation_prompt=True,
                    chat_template_kwargs=self.config.chat_template_kwargs or {"enable_thinking": False},
                )
            )
        except Exception as exc:
            raise KVPreflightError("shared prefix token boundary unavailable") from exc
        common = 0
        for actual, candidate in zip(prompt_ids, probe_ids):
            if actual != candidate:
                break
            common += 1
        if common <= 0:
            raise KVPreflightError("shared prefix token boundary unavailable")
        return common

    def _release(self, reason: str) -> None:
        handle_id = self.handoff.handle_id
        if not handle_id:
            self.handoff.clear()
            return
        self.handoff.clear()
        try:
            payload = dict(self.kv_client.release(handle_id))
            self._audit["release_calls"].append(
                {"handle_id": handle_id, "reason": reason, **payload}
            )
        except Exception as exc:
            self._audit["release_calls"].append(
                {
                    "handle_id": handle_id,
                    "reason": reason,
                    "status": "error",
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )
        finally:
            self._write_audit()

    @staticmethod
    def _validate_handle_metadata(
        metadata: dict[str, Any],
        *,
        health: dict[str, Any],
        task_id: str,
        token_digest: str,
        seq_len: int,
        producer_request_id: str,
        handle_id: str,
    ) -> None:
        required = (
            "handle_id",
            "engine_id",
            "engine_generation",
            "model_id",
            "model_revision",
            "tokenizer_digest",
            "task_id",
            "producer_request_id",
            "seq_len",
            "block_size",
            "token_digest",
            "dtype",
            "status",
        )
        missing = [
            name
            for name in required
            if name not in metadata or metadata[name] in (None, "")
        ]
        if missing:
            raise KVPreflightError(
                f"KV handle metadata incomplete: {','.join(missing)}"
            )
        expected = {
            "handle_id": str(handle_id),
            "engine_id": str(health["engine_id"]),
            "engine_generation": str(health["engine_generation"]),
            "model_id": str(health["model"]),
            "model_revision": str(health["model_revision"]),
            "tokenizer_digest": str(health["tokenizer_digest"]),
            "task_id": str(task_id),
            "producer_request_id": str(producer_request_id),
            "seq_len": int(seq_len),
            "block_size": int(health["block_size"]),
            "token_digest": str(token_digest),
            "dtype": str(health["dtype"]),
            "status": "ready",
        }
        mismatches = [
            name
            for name, expected_value in expected.items()
            if str(metadata.get(name)) != str(expected_value)
        ]
        if mismatches:
            raise KVPreflightError(
                f"KV handle metadata mismatch: {','.join(mismatches)}"
            )

    def _record_request_event(
        self,
        request_id: str,
        *,
        stage: str,
        status: str,
        started_ns: int,
        error: Exception | None = None,
        finish_reason: str | None = None,
        logical_prompt_tokens: int | None = None,
        logical_completion_tokens: int | None = None,
    ) -> None:
        event: dict[str, object] = {
            "request_id": request_id,
            "stage": stage,
            "status": status,
            "start_ns": started_ns,
            "end_ns": time.perf_counter_ns(),
            "role": "executor" if stage == "producer" else "summarizer",
            "endpoint": str(getattr(self.kv_client, "base_url", "")),
            "model": self.config.model,
            "finish_reason": finish_reason,
            # The private API currently returns token IDs, not server usage.
            # Keep provider usage null and expose derived logical counts under
            # an explicit source label instead.
            "response_prompt_tokens": None,
            "response_completion_tokens": None,
            "response_total_tokens": None,
            "logical_usage_source": "token_ids",
        }
        if logical_prompt_tokens is not None:
            event["logical_prompt_tokens"] = int(logical_prompt_tokens)
        if logical_completion_tokens is not None:
            event["logical_completion_tokens"] = int(logical_completion_tokens)
            if logical_prompt_tokens is not None:
                event["logical_total_tokens"] = int(logical_prompt_tokens) + int(logical_completion_tokens)
        if error is not None:
            event.update({"error_type": type(error).__name__, "error": str(error)})
        self._request_events.append(event)

    def _record_error(self, stage: str, request_id: str, exc: Exception) -> None:
        self._audit["status"] = "failed"
        self._audit["error"] = {
            "stage": stage,
            "request_id": request_id,
            "type": type(exc).__name__,
            "detail": str(exc),
        }
        self._write_audit()

    def _request_id(self, stage: str) -> str:
        self._request_index += 1
        safe_task = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in self.config.task_id
        )
        return f"mainline-{safe_task}-{self.config.mode}-{stage}-{self._request_index}"[-240:]

    def _sampling(self, *, temperature: float | None, max_tokens: int) -> dict[str, Any]:
        return {
            "temperature": 0.0 if temperature is None else float(temperature),
            "max_tokens": max_tokens,
            "seed": self.config.seed,
        }

    def _llm_result(
        self,
        payload: dict[str, Any],
        *,
        prompt_tokens: int,
        output_ids: tuple[int, ...],
    ) -> LLMResult:
        return LLMResult(
            # CodeAct consumes raw source; JSON roles already validate their
            # object after this adapter returns, so do not alter source bytes.
            text=str(payload.get("output_text", "")),
            model=self.config.model,
            usage=LLMUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=len(output_ids),
                total_tokens=prompt_tokens + len(output_ids),
            ),
            top_logprobs=payload.get("top_logprobs") if isinstance(payload.get("top_logprobs"), list) else None,
            finish_reason=(str(payload.get("finish_reason")) if payload.get("finish_reason") else None),
        )

    @staticmethod
    def _elapsed_ms(started_ns: int) -> float:
        return (time.perf_counter_ns() - started_ns) / 1_000_000.0

    def _write_audit(self) -> None:
        self.config.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.audit_path.write_text(
            json.dumps(self._audit, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def maybe_wrap_engine_local_kv_role_client(
    delegate: LLMClient,
    *,
    task_id: str,
    runtime_root: Path,
) -> LLMClient:
    config = EngineLocalKVRoleClientConfig.from_env(
        task_id=task_id,
        runtime_root=runtime_root,
    )
    if config.mode == "off":
        return delegate
    return EngineLocalKVRoleClient(delegate, config)


__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "EngineLocalKVRoleClient",
    "EngineLocalKVRoleClientConfig",
    "maybe_wrap_engine_local_kv_role_client",
]
