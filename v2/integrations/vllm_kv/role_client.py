from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Any

from runtime.llm import (
    ChatMessage,
    LLMClient,
    LLMResult,
    LLMUsage,
    normalize_comparator_role_name,
)
from v2.integrations.vllm_kv.client import VllmKVClient
from v2.integrations.vllm_kv.tokenizer_client import VllmTokenCodec
from v2.utils import sha256_digest


AUDIT_SCHEMA_VERSION = "statebus.engine_local_kv_mainline_audit.v1"
VALID_MODES = {"off", "full_replay", "continuation"}


@dataclass(frozen=True)
class EngineLocalKVRoleClientConfig:
    mode: str
    task_id: str
    audit_path: Path
    model: str = "qwen3-32b"
    parent_tokens: int = 4096
    ttl_s: int = 300
    seed: int = 7
    executor_max_tokens: int = 96
    summarizer_max_tokens: int = 128

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
            parent_tokens=int(os.getenv("STATEBUS_ENGINE_LOCAL_KV_PARENT_TOKENS", "4096")),
            ttl_s=int(os.getenv("STATEBUS_ENGINE_LOCAL_KV_TTL_S", "300")),
            seed=int(os.getenv("STATEBUS_ENGINE_LOCAL_KV_SEED", "7")),
            executor_max_tokens=int(
                os.getenv("STATEBUS_ENGINE_LOCAL_KV_EXECUTOR_MAX_TOKENS", "96")
            ),
            summarizer_max_tokens=int(
                os.getenv("STATEBUS_ENGINE_LOCAL_KV_SUMMARIZER_MAX_TOKENS", "128")
            ),
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
    ) -> None:
        if config.mode not in VALID_MODES or config.mode == "off":
            raise ValueError("EngineLocalKVRoleClient requires an enabled mode")
        if config.parent_tokens <= 0 or config.ttl_s <= 0:
            raise ValueError("parent_tokens and ttl_s must be positive")
        self.delegate = delegate
        self.config = config
        self.kv_client = kv_client or VllmKVClient()
        self.token_codec = token_codec or VllmTokenCodec(
            base_url=os.getenv("STATEBUS_KV_API_BASE_URL", "http://127.0.0.1:53334"),
            model=config.model,
        )
        self._health: dict[str, Any] | None = None
        self._parent_token_ids: tuple[int, ...] = ()
        self._handle_id = ""
        self._request_index = 0
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
        prompt = self._single_user_prompt(messages)
        if role == "executor":
            return self._produce(prompt, temperature=temperature)
        return self._consume(prompt, temperature=temperature)

    def describe_role(self, role: str) -> dict[str, object]:
        describe_role = getattr(self.delegate, "describe_role", None)
        if callable(describe_role):
            payload = dict(describe_role(role))
        else:
            payload = dict(self.delegate.describe())
        payload["engine_local_kv_mode"] = self.config.mode
        payload["engine_local_kv_role"] = normalize_comparator_role_name(role)
        return payload

    def describe(self) -> dict[str, object]:
        return {
            **dict(self.delegate.describe()),
            "engine_local_kv_mode": self.config.mode,
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

    def _produce(self, prompt: str, *, temperature: float | None) -> LLMResult:
        self._release("producer_replaced")
        health = self._ready_health()
        prompt_ids = tuple(int(value) for value in self.token_codec.encode(prompt))
        block_size = int(health["block_size"])
        parent_count = self.config.parent_tokens - self.config.parent_tokens % block_size
        if parent_count <= 0 or len(prompt_ids) <= parent_count:
            raise ValueError(
                f"executor prompt has {len(prompt_ids)} tokens; cannot split {parent_count}-token parent"
            )
        parent_ids = prompt_ids[:parent_count]
        suffix_ids = prompt_ids[parent_count:]
        if len(suffix_ids) > 4096:
            raise ValueError(f"executor suffix exceeds private API limit: {len(suffix_ids)}")
        self._parent_token_ids = parent_ids
        capture = self.config.mode == "continuation"
        request_id = self._request_id("producer")
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
                }
            )
            self._handle_id = str(payload.get("handle_id", ""))
            if capture and not self._handle_id:
                raise RuntimeError("KV producer did not return a handle")
            telemetry = dict(payload.get("telemetry") or {})
            output_ids = tuple(int(value) for value in payload.get("output_token_ids", ()))
            record = {
                "request_id": request_id,
                "success": True,
                "capture_kv": capture,
                "handle_id": self._handle_id,
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
            self._write_audit()
            return self._llm_result(payload, prompt_tokens=len(prompt_ids), output_ids=output_ids)
        except Exception as exc:
            self._record_error("producer", request_id, exc)
            self._release("producer_error")
            raise

    def _consume(self, prompt: str, *, temperature: float | None) -> LLMResult:
        health = self._ready_health()
        prompt_ids = tuple(int(value) for value in self.token_codec.encode(prompt))
        parent_count = len(self._parent_token_ids)
        if not parent_count:
            raise RuntimeError("summarizer called before KV producer")
        if len(prompt_ids) <= parent_count or prompt_ids[:parent_count] != self._parent_token_ids:
            raise ValueError("executor and summarizer shared parent token IDs do not match")
        suffix_ids = prompt_ids[parent_count:]
        if len(suffix_ids) > 4096:
            raise ValueError(f"summarizer suffix exceeds private API limit: {len(suffix_ids)}")
        use_kv = self.config.mode == "continuation" and bool(self._handle_id)
        lane = "kv_continuation" if use_kv else "full_replay"
        if self.config.mode == "continuation" and not use_kv:
            self._audit["fallback_count"] += 1
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
        }
        if use_kv:
            request["handle_id"] = self._handle_id
        else:
            request["parent_token_ids"] = list(self._parent_token_ids)
        started_ns = time.perf_counter_ns()
        try:
            stream = self.kv_client.continue_stream(request)
            payload = dict(stream.payload)
            expected_digest = sha256_digest(list(prompt_ids))
            if str(payload.get("logical_token_digest", "")) != expected_digest:
                raise RuntimeError("consumer logical token digest mismatch")
            telemetry = dict(payload.get("telemetry") or {})
            output_ids = tuple(int(value) for value in payload.get("output_token_ids", ()))
            record = {
                "request_id": request["request_id"],
                "success": True,
                "lane": lane,
                "handle_id": self._handle_id if use_kv else "",
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
            return self._llm_result(payload, prompt_tokens=len(prompt_ids), output_ids=output_ids)
        except Exception as exc:
            self._record_error("consumer", str(request["request_id"]), exc)
            raise
        finally:
            if use_kv:
                self._release("consumer_complete")
            self._write_audit()

    def _ready_health(self) -> dict[str, Any]:
        if self._health is None:
            health = dict(self.kv_client.health())
            if health.get("status") != "ready":
                raise RuntimeError("engine-local KV service is not ready")
            if str(health.get("model", "")) != self.config.model:
                raise RuntimeError("engine-local KV model mismatch")
            if int(health.get("block_size", 0)) <= 0:
                raise RuntimeError("engine-local KV block size is invalid")
            self._health = health
            self._audit["health"] = health
            self._write_audit()
        return self._health

    def _release(self, reason: str) -> None:
        if not self._handle_id:
            return
        handle_id = self._handle_id
        self._handle_id = ""
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
            raise
        finally:
            self._write_audit()

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
            text=str(payload.get("output_text", "")).strip(),
            model=self.config.model,
            usage=LLMUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=len(output_ids),
                total_tokens=prompt_tokens + len(output_ids),
            ),
        )

    @staticmethod
    def _single_user_prompt(messages: list[ChatMessage]) -> str:
        if len(messages) != 1 or messages[0].role != "user" or not messages[0].content:
            raise ValueError("engine-local KV adapter requires one non-empty user message")
        return messages[0].content

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
