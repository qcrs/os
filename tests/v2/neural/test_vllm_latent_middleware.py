from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from v2.contracts import LatentAnchor
from v2.integrations.vllm_latent.middleware import (
    LATENT_MARKER,
    LatentHandoffMiddleware,
    _render_messages,
    _reset_v0_prefix_cache_for_prompt_embeds,
    _rpc,
    _sampling_params,
)
from v2.utils import sha256_digest


class _Tokenizer:
    def apply_chat_template(self, messages, *, tokenize=False, add_generation_prompt=False):
        del tokenize, add_generation_prompt
        return "\n".join(f"{item['role']}: {item['content']}" for item in messages)

    def encode(self, text, *, add_special_tokens=False):
        del add_special_tokens
        return [ord(char) % 97 for char in text]


class _FakeEngine:
    def __init__(
        self,
        signature,
        *,
        observe_forward=True,
        reject_begin_consume=False,
        describe_error_code="",
        prefix_cache_reset_ok=True,
    ):
        self.signature = signature
        self.observe_forward = observe_forward
        self.reject_begin_consume = reject_begin_consume
        self.describe_error_code = describe_error_code
        self.prefix_cache_reset_ok = prefix_cache_reset_ok
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.prefix_cache_reset_count = 0
        self.consumer_generate_count = 0
        self.ref_id = "latent-test-ref"
        self.capture_id = "capture-test"
        self.status = "committed"
        self.prompt_digest = ""
        self.prompt_shape: tuple[int, ...] = ()
        self.prompt_dtype = "bfloat16"
        self.forward_proof: dict[str, Any] | None = None

    async def get_tokenizer(self):
        return _Tokenizer()

    def reset_prefix_cache(self):
        self.prefix_cache_reset_count += 1
        return self.prefix_cache_reset_ok

    async def collective_rpc(self, method, *, args=(), kwargs=None):
        del kwargs
        self.calls.append((method, tuple(args)))
        if method == "statebus_latent_capabilities":
            return [
                {
                    "status": "ready",
                    "plugin_version": "statebus.vllm_latent.worker_extension.v1",
                    "vllm_version": self.signature.vllm_version,
                    "engine_generation": self.signature.engine_generation,
                    "model": self.signature.model_id,
                    "hidden_size": self.signature.hidden_size,
                    "prompt_embeds_enabled": True,
                    "worker_extension_ready": True,
                    "max_num_seqs": 1,
                    "tensor_parallel_size": 1,
                    "pipeline_parallel_size": 1,
                    "compatibility_signature": self.signature.canonical_payload(),
                    "compatibility_digest": self.signature.compatibility_digest,
                    "registry_entries": 0,
                    "registry_bytes": 0,
                    "registry_max_entries": 64,
                    "registry_max_bytes": 67_108_864,
                    "registry_max_steps": 80,
                    "errors": [],
                }
            ]
        if method == "statebus_latent_begin":
            spec = args[0]
            return [
                {
                    "capture_id": self.capture_id,
                    "ref_id": self.ref_id,
                    "compatibility_digest": spec["expected_compatibility_digest"],
                    "worker_pid": 42,
                    "engine_id": "fake-engine",
                }
            ]
        if method == "statebus_latent_finish":
            steps = int(args[0] and 3)
            return [
                {
                    "ref_id": self.ref_id,
                    "status": "committed",
                    "dtype": "bfloat16",
                    "shape": [steps, self.signature.hidden_size],
                    "tensor_bytes": steps * self.signature.hidden_size * 2,
                    "tensor_digest": "hidden-digest",
                    "captured_step_count": steps,
                    "recurrence_injection_count": steps - 1,
                    "internal_scheduler_sample_count": steps,
                    "producer_pid": 42,
                    "engine_id": "fake-engine",
                    "created_at_ns": 1,
                    "expires_at_ns": 99,
                    "compatibility_digest": self.signature.compatibility_digest,
                }
            ]
        if method == "statebus_latent_abort":
            self.status = "rejected"
            return [{"ref_id": self.ref_id, "status": "rejected"}]
        if method == "statebus_latent_materialize_consumer_prompt":
            self.prompt_shape = (7, self.signature.hidden_size)
            self.prompt_digest = "prompt-digest"
            self.prompt_dtype = "bfloat16"
            return [
                {
                    "ref_id": self.ref_id,
                    "prompt_embeds": object(),
                    "prompt_embed_shape": list(self.prompt_shape),
                    "prompt_embed_dtype": self.prompt_dtype,
                    "prompt_embed_bytes": self.prompt_shape[0]
                    * self.prompt_shape[1]
                    * 2,
                    "prompt_embed_digest": self.prompt_digest,
                    "compatibility_digest": self.signature.compatibility_digest,
                }
            ]
        if method == "statebus_latent_begin_consume":
            if self.reject_begin_consume:
                raise RuntimeError("latent_consumer_forward_not_observed")
            self.status = "consuming"
            return [{"ref_id": self.ref_id, "status": "consuming"}]
        if method == "statebus_latent_describe":
            if self.describe_error_code:
                raise RuntimeError(self.describe_error_code)
            return [
                {
                    "ref_id": self.ref_id,
                    "status": self.status,
                    "forward_proof": self.forward_proof,
                }
            ]
        if method == "statebus_latent_release":
            self.status = "released"
            return [{"ref_id": self.ref_id, "status": "released"}]
        raise AssertionError(f"unexpected RPC method: {method}")

    async def generate(self, prompt, sampling_params, *, request_id):
        del prompt
        if getattr(sampling_params, "ignore_eos", False):
            yield {"text": "internal-bookkeeping", "token_ids": [1, 2, 3]}
            return
        self.consumer_generate_count += 1
        assert self.prefix_cache_reset_count == self.consumer_generate_count
        if self.observe_forward:
            self.status = "consumed"
            self.forward_proof = {
                "ref_id": self.ref_id,
                "request_id": request_id,
                "worker_pid": 42,
                "engine_id": "fake-engine",
                "inputs_embeds_shape": list(self.prompt_shape),
                "inputs_embeds_dtype": self.prompt_dtype,
                "inputs_embeds_digest": self.prompt_digest,
                "observed_at_ns": 2,
                "event_id": "forward-test",
                "proof_kind": "worker_forward",
            }
        yield {"outputs": [{"text": "{\"claim\": 1}", "token_ids": [5, 6]}]}


class _App:
    def __init__(self, engine):
        self.state = SimpleNamespace(engine_client=engine)

    async def __call__(self, scope, receive, send):
        del scope, receive
        body = b"ordinary"
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})


@pytest.fixture
def token_file(tmp_path: Path) -> Path:
    path = tmp_path / "latent.token"
    path.write_text("test-token\n", encoding="utf-8")
    path.chmod(0o600)
    return path


async def _client(app, token_file: Path):
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 4123))
    return httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
        headers={"authorization": "Bearer test-token"},
    )


def _produce_payload(signature):
    return {
        "model": signature.model_id,
        "request_id": "producer-request",
        "task_id": "task-1",
        "source_step_id": "retrieve",
        "messages": [{"role": "user", "content": "narrative evidence"}],
        "latent_steps": 3,
        "anchor": {
            "evidence_pack_hash": "evidence-hash",
            "item_ids": ["ev-1"],
            "locator_digest": "locator-hash",
        },
        "expected_compatibility_digest": signature.compatibility_digest,
    }


def _complete_payload(signature):
    return {
        "model": signature.model_id,
        "request_id": "consumer-request",
        "latent_ref_id": "latent-test-ref",
        "rendered_prompt": f"anchors {LATENT_MARKER} claimset",
        "response_schema": {"type": "object"},
        "expected_compatibility_digest": signature.compatibility_digest,
        "anchor": {
            "evidence_pack_hash": "evidence-hash",
            "item_ids": ["ev-1"],
            "locator_digest": "locator-hash",
        },
    }


def test_latent_launch_selects_direct_v0_engine_for_collective_rpc() -> None:
    script_path = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "start_vllm_qwen3_32b_latent.sh"
    )
    script = script_path.read_text(encoding="utf-8")

    assert "--disable-frontend-multiprocessing" in script
    assert "--enable-prefix-caching" in script
    assert "--worker-extension-cls" in script
    assert "--middleware" in script
    assert "STATEBUS_LATENT_MODEL_REVISION_DIGEST" in script
    assert "STATEBUS_LATENT_TOKENIZER_REVISION" in script
    assert "STATEBUS_LATENT_CHAT_TEMPLATE_DIGEST" in script


@pytest.mark.asyncio
async def test_rpc_falls_back_to_nested_v0_engine_when_async_hook_is_unimplemented():
    class _NestedV0Engine:
        def collective_rpc(self, method, *, args=(), kwargs=None):
            del kwargs
            return [{"method": method, "args": list(args)}]

    class _AsyncV0Wrapper:
        engine = _NestedV0Engine()

        async def collective_rpc(self, method, *, args=(), kwargs=None):
            del method, args, kwargs
            raise NotImplementedError

    result = await _rpc(
        _AsyncV0Wrapper(),
        "statebus_latent_capabilities",
        "probe",
    )
    assert result == {"method": "statebus_latent_capabilities", "args": ["probe"]}


@pytest.mark.asyncio
async def test_prompt_embeds_cache_isolation_prefers_nested_v0_result():
    class _NestedV0Engine:
        reset_count = 0

        def reset_prefix_cache(self):
            self.reset_count += 1
            return True

    class _AsyncV0Wrapper:
        engine = _NestedV0Engine()

        async def reset_prefix_cache(self):
            raise AssertionError("nested V0 reset must be authoritative")

    wrapper = _AsyncV0Wrapper()
    await _reset_v0_prefix_cache_for_prompt_embeds(wrapper)

    assert wrapper.engine.reset_count == 1


def test_latent_guided_decoding_disables_arbitrary_whitespace():
    sampling = _sampling_params(
        temperature=0.0,
        max_tokens=512,
        seed=7,
        response_schema={"type": "object"},
    )
    guided = sampling.guided_decoding

    if isinstance(guided, dict):
        assert guided["backend"] == "xgrammar"
        assert guided["disable_any_whitespace"] is True
    else:
        assert guided.backend == "xgrammar"
        assert guided.disable_any_whitespace is True


def test_chat_template_disables_qwen_thinking_and_keeps_generation_boundary():
    calls = []

    class ThinkingAwareTokenizer:
        def apply_chat_template(self, messages, **kwargs):
            calls.append((messages, kwargs))
            return "rendered"

    rendered = _render_messages(
        ThinkingAwareTokenizer(),
        [SimpleNamespace(role="user", content="evidence")],
    )

    assert rendered == "rendered"
    assert calls == [
        (
            [{"role": "user", "content": "evidence"}],
            {
                "tokenize": False,
                "add_generation_prompt": True,
                "enable_thinking": False,
            },
        )
    ]


@pytest.mark.asyncio
async def test_health_auth_loopback_and_allowlist(neural_signature, token_file):
    engine = _FakeEngine(neural_signature)
    wrapped = LatentHandoffMiddleware(_App(engine), token_file=token_file)
    async with await _client(wrapped, token_file) as client:
        response = await client.get("/statebus/latent/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["plugin_version"] == "statebus.vllm_latent.v1"
    assert payload["registry_max_steps"] == 80
    assert "test-token" not in response.text
    assert set(method for method, _ in engine.calls) <= {
        "statebus_latent_capabilities"
    }


@pytest.mark.asyncio
async def test_produce_is_opaque_and_binds_request(neural_signature, token_file):
    engine = _FakeEngine(neural_signature)
    wrapped = LatentHandoffMiddleware(_App(engine), token_file=token_file)
    async with await _client(wrapped, token_file) as client:
        response = await client.post(
            "/statebus/latent/produce", json=_produce_payload(neural_signature)
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "committed"
    assert payload["shape"] == [3, neural_signature.hidden_size]
    assert payload["tensor_bytes"] == 3 * neural_signature.hidden_size * 2
    assert "internal-bookkeeping" not in response.text
    assert "prompt" not in response.text.lower()
    assert any(
        method == "statebus_latent_begin" and args[0]["request_id"] == "producer-request"
        for method, args in engine.calls
    )
    assert wrapped.latent_produce_success_count == 1
    assert wrapped.latent_consume_success_count == 0
    assert wrapped.latent_success_count == 0


@pytest.mark.asyncio
async def test_complete_requires_worker_forward_and_preserves_success_counter(
    neural_signature, token_file
):
    engine = _FakeEngine(neural_signature)
    wrapped = LatentHandoffMiddleware(_App(engine), token_file=token_file)
    async with await _client(wrapped, token_file) as client:
        success = await client.post(
            "/statebus/latent/complete", json=_complete_payload(neural_signature)
        )
    assert success.status_code == 200
    assert success.json()["consumer_forward_observed"] is True
    assert success.json()["consumed_ref_id"] == engine.ref_id
    assert wrapped.latent_success_count == 1
    assert wrapped.latent_consume_success_count == 1
    assert engine.prefix_cache_reset_count == 1
    assert engine.consumer_generate_count == 1

    engine = _FakeEngine(neural_signature, observe_forward=False)
    wrapped = LatentHandoffMiddleware(_App(engine), token_file=token_file)
    async with await _client(wrapped, token_file) as client:
        failed = await client.post(
            "/statebus/latent/complete", json=_complete_payload(neural_signature)
        )
    assert failed.status_code == 400
    assert failed.json()["error_code"] == "latent_consumer_forward_not_observed"
    assert wrapped.latent_success_count == 0
    assert any(method == "statebus_latent_release" for method, _ in engine.calls)


@pytest.mark.asyncio
async def test_complete_can_render_structured_messages_with_the_same_prompt_contract(
    neural_signature, token_file
):
    engine = _FakeEngine(neural_signature)
    wrapped = LatentHandoffMiddleware(_App(engine), token_file=token_file)
    payload = _complete_payload(neural_signature)
    payload["messages"] = [
        {"role": "system", "content": "summarize grounded evidence"},
        {"role": "user", "content": payload["rendered_prompt"]},
    ]

    async with await _client(wrapped, token_file) as client:
        response = await client.post("/statebus/latent/complete", json=payload)

    assert response.status_code == 200
    assert response.json()["consumer_forward_observed"] is True
    materialize = next(
        args
        for method, args in engine.calls
        if method == "statebus_latent_materialize_consumer_prompt"
    )
    assert materialize[1]
    assert materialize[2]


@pytest.mark.asyncio
async def test_complete_fails_closed_when_v0_prefix_cache_cannot_be_isolated(
    neural_signature, token_file
):
    engine = _FakeEngine(neural_signature, prefix_cache_reset_ok=False)
    wrapped = LatentHandoffMiddleware(_App(engine), token_file=token_file)
    async with await _client(wrapped, token_file) as client:
        response = await client.post(
            "/statebus/latent/complete", json=_complete_payload(neural_signature)
        )

    assert response.status_code == 400
    assert response.json()["error_code"] == "latent_consumer_forward_not_observed"
    assert engine.prefix_cache_reset_count == 1
    assert engine.consumer_generate_count == 0
    assert any(method == "statebus_latent_release" for method, _ in engine.calls)
    assert wrapped.latent_success_count == 0


@pytest.mark.asyncio
async def test_duplicate_marker_and_non_loopback_are_rejected(neural_signature, token_file):
    engine = _FakeEngine(neural_signature)
    wrapped = LatentHandoffMiddleware(_App(engine), token_file=token_file)
    async with await _client(wrapped, token_file) as client:
        payload = _complete_payload(neural_signature)
        payload["rendered_prompt"] = f"{LATENT_MARKER}{LATENT_MARKER}"
        duplicate = await client.post("/statebus/latent/complete", json=payload)
    assert duplicate.status_code == 400
    assert duplicate.json()["error_code"] == "latent_position_contract_incompatible"

    transport = httpx.ASGITransport(app=wrapped, client=("10.0.0.8", 4123))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://10.0.0.8",
        headers={"authorization": "Bearer test-token"},
    ) as client:
        rejected = await client.get("/statebus/latent/health")
    assert rejected.status_code == 403
    assert rejected.json()["error_code"] == "latent_loopback_required"


@pytest.mark.asyncio
async def test_materialized_ref_is_released_when_begin_consume_fails(
    neural_signature, token_file
):
    engine = _FakeEngine(neural_signature, reject_begin_consume=True)
    wrapped = LatentHandoffMiddleware(_App(engine), token_file=token_file)
    async with await _client(wrapped, token_file) as client:
        response = await client.post(
            "/statebus/latent/complete", json=_complete_payload(neural_signature)
        )
    assert response.status_code == 400
    assert response.json()["error_code"] == "latent_consumer_forward_not_observed"
    assert any(method == "statebus_latent_release" for method, _ in engine.calls)
    assert wrapped.latent_success_count == 0


@pytest.mark.asyncio
async def test_invalidated_ref_maps_missing_forward_to_stable_error(
    neural_signature, token_file
):
    engine = _FakeEngine(
        neural_signature,
        describe_error_code="latent_ref_not_found",
    )
    wrapped = LatentHandoffMiddleware(_App(engine), token_file=token_file)
    async with await _client(wrapped, token_file) as client:
        response = await client.post(
            "/statebus/latent/complete", json=_complete_payload(neural_signature)
        )
    assert response.status_code == 400
    assert response.json()["error_code"] == "latent_consumer_forward_not_observed"
    assert any(method == "statebus_latent_release" for method, _ in engine.calls)


@pytest.mark.asyncio
async def test_streaming_lock_is_held_through_the_final_body(neural_signature, token_file):
    first_body = asyncio.Event()
    allow_final_body = asyncio.Event()

    class StreamingApp(_App):
        def __init__(self, engine):
            super().__init__(engine)
            self.entered = 0

        async def __call__(self, scope, receive, send):
            del scope, receive
            self.entered += 1
            current = self.entered
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send(
                {
                    "type": "http.response.body",
                    "body": b"first",
                    "more_body": True,
                }
            )
            if current == 1:
                first_body.set()
                await allow_final_body.wait()
            await send(
                {
                    "type": "http.response.body",
                    "body": b"final",
                    "more_body": False,
                }
            )

    app = StreamingApp(_FakeEngine(neural_signature))
    wrapped = LatentHandoffMiddleware(app, token_file=token_file)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/chat/completions",
        "headers": [],
        "client": ("127.0.0.1", 4100),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    first = asyncio.create_task(wrapped(dict(scope), receive, send))
    await first_body.wait()
    second = asyncio.create_task(wrapped(dict(scope), receive, send))
    await asyncio.sleep(0)
    assert app.entered == 1
    allow_final_body.set()
    await asyncio.gather(first, second)
    assert app.entered == 2


@pytest.mark.asyncio
async def test_body_limit_and_bad_bearer_fail_closed(neural_signature, token_file):
    wrapped = LatentHandoffMiddleware(
        _App(_FakeEngine(neural_signature)),
        token_file=token_file,
        max_body_bytes=8,
    )
    transport = httpx.ASGITransport(app=wrapped, client=("127.0.0.1", 4123))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
        headers={"authorization": "Bearer wrong-token"},
    ) as client:
        unauthorized = await client.get("/statebus/latent/health")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error_code"] == "latent_auth_failed"

    async with await _client(wrapped, token_file) as client:
        oversized = await client.post(
            "/statebus/latent/release",
            content=b'{"ref_id":"too-large"}',
            headers={"content-type": "application/json"},
        )
    assert oversized.status_code == 413
    assert oversized.json()["error_code"] == "latent_request_invalid"
