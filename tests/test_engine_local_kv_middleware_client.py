from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from statebus.integrations.vllm_kv.client import VllmKVClient
from statebus.integrations.vllm_kv.middleware import KVHandoffMiddleware
from statebus.utils import sha256_digest


class _WorkerFailure(RuntimeError):
    def __init__(self, error_code: str, detail: str = "") -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.detail = detail


class _FakeEngine:
    def __init__(self) -> None:
        self.parent_ids: tuple[int, ...] = ()
        self.handle_id = "kv-asgi-test"
        self.handle_status = "missing"
        self.task_id = ""
        self.consume_request_id = ""
        self.forward_proof: dict[str, Any] | None = None
        self.generate_calls: list[dict[str, Any]] = []
        self.compatibility_digest = "compatibility-digest"

    async def collective_rpc(
        self,
        method: str,
        *,
        args: tuple[Any, ...],
        kwargs: Mapping[str, Any] | None,
    ) -> list[Any]:
        del kwargs
        if method == "statebus_kv_capabilities":
            return [self._capabilities()]
        if method == "statebus_kv_prepare":
            spec = args[0]
            self.parent_ids = tuple(int(value) for value in spec["token_ids"])
            self.task_id = str(spec["task_id"])
            self.handle_status = "preparing"
            self.forward_proof = None
            return [{"handle_id": self.handle_id, "status": "preparing"}]
        if method == "statebus_kv_prepare_consume":
            handle_id, request_id, task_id, compatibility_digest = args
            if handle_id != self.handle_id or self.handle_status != "ready":
                raise _WorkerFailure("kv_ref_not_found")
            if task_id != self.task_id:
                raise _WorkerFailure("kv_task_mismatch")
            if compatibility_digest != self.compatibility_digest:
                raise _WorkerFailure("kv_model_incompatible")
            self.handle_status = "consuming"
            self.consume_request_id = str(request_id)
            return [
                {
                    "handle_id": self.handle_id,
                    "status": "consuming",
                    "token_ids": list(self.parent_ids),
                    "handle": self._handle_payload(status="consuming"),
                }
            ]
        if method == "statebus_kv_describe":
            if args[0] != self.handle_id or self.handle_status == "missing":
                raise _WorkerFailure("kv_ref_not_found")
            return [
                {
                    "handle_id": self.handle_id,
                    "status": self.handle_status,
                    "handle": self._handle_payload(status=self.handle_status),
                    "store_ms": 0.25,
                    "forward_proof": self.forward_proof,
                    "forward_proof_hash": "proof-hash" if self.forward_proof else "",
                }
            ]
        if method == "statebus_kv_abort":
            if args[0] == self.handle_id and self.handle_status == "consuming":
                self.handle_status = "missing"
            return [{"status": "invalidated"}]
        if method == "statebus_kv_release":
            if args[0] != self.handle_id:
                raise _WorkerFailure("kv_ref_not_found")
            self.handle_status = "released"
            return [{"handle_id": self.handle_id, "status": "released"}]
        if method == "statebus_kv_sweep_expired":
            return [{"expired_count": 0}]
        raise AssertionError(method)

    def generate(
        self,
        prompt: Mapping[str, Any],
        sampling_params: Any,
        *,
        request_id: str,
    ) -> Any:
        prompt_ids = tuple(int(value) for value in prompt["prompt_token_ids"])
        extra_args = getattr(sampling_params, "extra_args", None) or {}
        transfer = extra_args.get("kv_transfer_params") or {}
        action = str(transfer.get("action", ""))
        self.generate_calls.append(
            {"request_id": request_id, "prompt_ids": prompt_ids, "action": action}
        )

        async def stream() -> Any:
            yield {"outputs": [{"text": "O", "token_ids": [901]}]}
            final_chunk: dict[str, Any] = {
                "outputs": [{"text": "OK", "token_ids": [901, 902]}]
            }
            if action == "load":
                prefix_len = len(self.parent_ids)
                final_chunk["kv_transfer_params"] = {
                    "statebus_kv": {
                        "connector_version": "connector-v1",
                        "action": "load",
                        "handle_id": self.handle_id,
                        "logical_prompt_tokens": len(prompt_ids),
                        "inherited_kv_tokens": prefix_len,
                        "computed_prefill_tokens": len(prompt_ids) - prefix_len,
                    }
                }
            yield final_chunk
            if action == "store":
                self.handle_status = "ready"
            elif action == "load":
                suffix_count = len(prompt_ids) - len(self.parent_ids)
                self.handle_status = "consumed"
                self.forward_proof = {
                    "handle_id": self.handle_id,
                    "request_id": request_id,
                    "task_id": self.task_id,
                    "engine_id": "engine-1",
                    "engine_generation": "generation-1",
                    "token_digest": sha256_digest(list(self.parent_ids)),
                    "inherited_kv_tokens": len(self.parent_ids),
                    "computed_prefill_tokens": suffix_count,
                    "logical_prompt_tokens": len(prompt_ids),
                    "suffix_tokens": suffix_count,
                    "layer_count": 2,
                    "kv_bytes_actual": 1024,
                    "connector_load_count": 1,
                    "kv_load_ms": 0.4,
                    "worker_pid": 123,
                    "observed_at_ns": 2,
                }

        return stream()

    def _capabilities(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "plugin_version": "worker-v1",
            "connector_version": "connector-v1",
            "vllm_version": "0.9.2",
            "engine_id": "engine-1",
            "engine_generation": "generation-1",
            "model": "qwen3-32b",
            "model_revision": "model-revision",
            "tokenizer_digest": "tokenizer-digest",
            "dtype": "bfloat16",
            "block_size": 2,
            "layer_count": 2,
            "max_num_seqs": 1,
            "max_model_len": 8192,
            "tensor_parallel_size": 1,
            "pipeline_parallel_size": 1,
            "automatic_prefix_caching": False,
            "kv_connector": "StateBusLocalKVConnector",
            "kv_role": "kv_both",
            "compatibility_signature": {"engine_id": "engine-1"},
            "compatibility_digest": self.compatibility_digest,
            "errors": [],
        }

    def _handle_payload(self, *, status: str) -> dict[str, Any]:
        return {
            "handle_id": self.handle_id,
            "status": status,
            "seq_len": len(self.parent_ids),
            "token_digest": sha256_digest(list(self.parent_ids)),
            "kv_bytes_actual": 1024,
            "layer_count": 2,
        }


class _FakeApp:
    def __init__(self, engine: _FakeEngine) -> None:
        self.state = SimpleNamespace(engine_client=engine)
        self.forwarded_paths: list[str] = []

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        del receive
        self.forwarded_paths.append(str(scope.get("path", "")))
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b"", "more_body": False})


def _token_file(tmp_path: Path) -> Path:
    path = tmp_path / "kv-api.token"
    path.write_text("test-secret", encoding="utf-8")
    path.chmod(0o600)
    return path


async def _asgi_request(
    middleware: KVHandoffMiddleware,
    app: _FakeApp,
    method: str,
    path: str,
    payload: Mapping[str, Any] | None = None,
) -> tuple[int, list[dict[str, Any]], bytes]:
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    messages: list[dict[str, Any]] = []
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "client": ("127.0.0.1", 12345),
        "app": app,
        "headers": [
            (b"authorization", b"Bearer test-secret"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ],
    }
    await middleware(scope, receive, send)
    status = next(
        int(message["status"])
        for message in messages
        if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        bytes(message.get("body", b""))
        for message in messages
        if message["type"] == "http.response.body"
    )
    return status, messages, response_body


@pytest.mark.asyncio
async def test_asgi_ab_paths_have_identical_logical_tokens_and_real_kv_proof(
    tmp_path: Path,
) -> None:
    engine = _FakeEngine()
    app = _FakeApp(engine)
    middleware = KVHandoffMiddleware(app, token_file=_token_file(tmp_path))
    parent_ids = [10, 11, 12, 13]
    suffix_ids = [20, 21]
    common = {
        "model": "qwen3-32b",
        "task_id": "task-1",
        "sampling": {"temperature": 0.0, "max_tokens": 2, "seed": 7},
        "expected_compatibility_digest": engine.compatibility_digest,
    }

    produce = {
        **common,
        "request_id": "produce-1",
        "parent_token_ids": parent_ids,
        "producer_suffix_token_ids": [30],
        "capture_kv": True,
    }
    status, _, raw = await _asgi_request(
        middleware, app, "POST", "/statebus/kv/produce", produce
    )
    assert status == 200
    produced = json.loads(raw)
    assert produced["handle_id"] == engine.handle_id
    assert "token_ids" not in produced["handle"]
    assert "block_ids" not in produced["handle"]
    assert "layer_tensors" not in produced["handle"]

    full_replay = {
        **common,
        "request_id": "consumer-a",
        "lane": "full_replay",
        "parent_token_ids": parent_ids,
        "suffix_token_ids": suffix_ids,
        "stream": True,
    }
    status_a, _, raw_a = await _asgi_request(
        middleware, app, "POST", "/statebus/kv/continue", full_replay
    )
    assert status_a == 200
    assert b"event: token" in raw_a
    payload_a = json.loads(
        next(
            line.removeprefix("data: ")
            for line in raw_a.decode().splitlines()
            if line.startswith("data: ") and '"lane":"full_replay"' in line
        )
    )

    kv_continuation = {
        **common,
        "request_id": "consumer-b",
        "lane": "kv_continuation",
        "handle_id": engine.handle_id,
        "suffix_token_ids": suffix_ids,
        "stream": True,
    }
    assert "parent_token_ids" not in kv_continuation
    status_b, _, raw_b = await _asgi_request(
        middleware, app, "POST", "/statebus/kv/continue", kv_continuation
    )
    assert status_b == 200
    assert b"event: token" in raw_b
    payload_b = json.loads(
        next(
            line.removeprefix("data: ")
            for line in raw_b.decode().splitlines()
            if line.startswith("data: ") and '"lane":"kv_continuation"' in line
        )
    )

    consumer_calls = {
        item["request_id"]: item for item in engine.generate_calls if "consumer" in item["request_id"]
    }
    assert consumer_calls["consumer-a"]["prompt_ids"] == tuple(parent_ids + suffix_ids)
    assert consumer_calls["consumer-b"]["prompt_ids"] == tuple(parent_ids + suffix_ids)
    assert payload_a["logical_token_digest"] == payload_b["logical_token_digest"]
    assert payload_a["telemetry"]["computed_prefill_tokens"] == 6
    assert payload_a["telemetry"]["inherited_kv_tokens"] == 0
    assert payload_b["telemetry"]["computed_prefill_tokens"] == 2
    assert payload_b["telemetry"]["inherited_kv_tokens"] == 4
    assert payload_b["telemetry"]["connector_load_count"] == 1
    assert payload_b["forward_proof"]["request_id"] == "consumer-b"


@pytest.mark.asyncio
async def test_unknown_handle_fails_closed_before_generation(tmp_path: Path) -> None:
    engine = _FakeEngine()
    app = _FakeApp(engine)
    middleware = KVHandoffMiddleware(app, token_file=_token_file(tmp_path))
    before = len(engine.generate_calls)
    status, _, raw = await _asgi_request(
        middleware,
        app,
        "POST",
        "/statebus/kv/continue",
        {
            "model": "qwen3-32b",
            "request_id": "consumer-missing",
            "task_id": "task-1",
            "lane": "kv_continuation",
            "handle_id": "missing-handle",
            "suffix_token_ids": [20],
            "stream": True,
            "sampling": {"temperature": 0.0, "max_tokens": 2, "seed": 7},
            "expected_compatibility_digest": engine.compatibility_digest,
        },
    )

    assert status == 404
    assert json.loads(raw)["error_code"] == "kv_ref_not_found"
    assert len(engine.generate_calls) == before


@pytest.mark.asyncio
async def test_non_kv_routes_bypass_private_request_lock(tmp_path: Path) -> None:
    engine = _FakeEngine()
    app = _FakeApp(engine)
    request_lock = asyncio.Lock()
    middleware = KVHandoffMiddleware(
        app,
        token_file=_token_file(tmp_path),
        request_lock=request_lock,
    )
    await request_lock.acquire()
    try:
        status, _, _ = await _asgi_request(
            middleware,
            app,
            "GET",
            "/v1/models",
        )
    finally:
        request_lock.release()

    assert status == 404
    assert app.forwarded_paths == ["/v1/models"]


class _StreamResponse:
    status_code = 200

    def __enter__(self) -> "_StreamResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def iter_lines(self) -> Any:
        yield "event: token"
        yield 'data: {"text_delta":"O","token_ids":[901]}'
        yield ""
        yield "event: final"
        yield 'data: {"status":"success","lane":"kv_continuation"}'
        yield ""


class _CapturingHttpClient:
    def __init__(self) -> None:
        self.serialized = b""

    def stream(self, _method: str, _url: str, **kwargs: Any) -> _StreamResponse:
        self.serialized = bytes(kwargs["content"])
        return _StreamResponse()


def test_sync_client_sends_handle_only_and_measures_sse_ttft(tmp_path: Path) -> None:
    token_file = _token_file(tmp_path)
    transport = _CapturingHttpClient()
    client = VllmKVClient(
        base_url="http://127.0.0.1:53334",
        token_file=token_file,
        http_client=transport,
    )

    result = client.continue_stream(
        {
            "model": "qwen3-32b",
            "request_id": "consumer-client",
            "task_id": "task-1",
            "lane": "kv_continuation",
            "handle_id": "kv-handle-only",
            "suffix_token_ids": [20, 21],
            "expected_compatibility_digest": "compatibility-digest",
        }
    )

    sent = json.loads(transport.serialized)
    assert sent["handle_id"] == "kv-handle-only"
    assert sent["suffix_token_ids"] == [20, 21]
    assert "parent_token_ids" not in sent
    assert result.token_event_count == 1
    assert result.client_ttft_ms >= 0.0
    assert result.client_wall_ms >= result.client_ttft_ms
    assert result.api_request_bytes == len(transport.serialized)
