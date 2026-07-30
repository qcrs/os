from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from statebus.integrations.llm import ChatMessage, LLMResult
from statebus.integrations.vllm_kv.client import KVStreamResult
from statebus.integrations.vllm_kv.role_client import (
    EngineLocalKVRoleClient,
    EngineLocalKVRoleClientConfig,
)
from statebus.utils import sha256_digest


class _Delegate:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete(self, messages, *, purpose, temperature=None, response_schema=None):
        self.calls.append(purpose)
        return LLMResult(text='{"delegated":true}', model="delegate")

    def describe_role(self, role: str):
        return {"backend": "fake", "role": role}

    def describe(self):
        return {"backend": "fake"}


class _Codec:
    def encode(self, text: str):
        if text == "executor":
            return (1, 2, 3, 4, 10, 11)
        if text == "summarizer":
            return (1, 2, 3, 4, 20, 21, 22)
        raise AssertionError(text)

    def close(self) -> None:
        pass


class _KVClient:
    def __init__(self) -> None:
        self.produce_payloads: list[dict] = []
        self.consumer_payloads: list[dict] = []
        self.release_calls: list[str] = []

    def health(self):
        return {
            "status": "ready",
            "model": "qwen3-32b",
            "compatibility_digest": "compat",
            "block_size": 2,
            "automatic_prefix_caching": False,
        }

    def produce(self, payload):
        payload = dict(payload)
        self.produce_payloads.append(payload)
        capture = bool(payload["capture_kv"])
        return {
            "status": "success",
            "handle_id": "handle-1" if capture else "",
            "output_text": '{"candidate_key":"k","route":"r","tool_name":"t"}',
            "output_token_ids": [101, 102],
            "telemetry": {
                "computed_prefill_tokens": 6,
                "kv_store_ms": 1.25 if capture else 0.0,
            },
        }

    def continue_stream(self, payload):
        payload = dict(payload)
        self.consumer_payloads.append(payload)
        parent = (1, 2, 3, 4)
        suffix = tuple(payload["suffix_token_ids"])
        inherited = len(parent) if payload["lane"] == "kv_continuation" else 0
        return KVStreamResult(
            payload={
                "status": "success",
                "logical_token_digest": sha256_digest(list(parent + suffix)),
                "output_text": '{"summary":"done"}',
                "output_token_ids": [201, 202],
                "telemetry": {
                    "computed_prefill_tokens": len(suffix) if inherited else len(parent + suffix),
                    "inherited_kv_tokens": inherited,
                    "connector_load_count": 1 if inherited else 0,
                    "kv_load_ms": 0.75 if inherited else 0.0,
                },
            },
            client_ttft_ms=12.0 if inherited else 48.0,
            client_wall_ms=18.0 if inherited else 54.0,
            api_request_bytes=256 if inherited else 1024,
            token_event_count=1,
        )

    def release(self, handle_id: str):
        self.release_calls.append(handle_id)
        return {"status": "released", "handle_id": handle_id}

    def close(self) -> None:
        pass


@pytest.mark.parametrize(
    ("mode", "expected_lane", "capture"),
    (("full_replay", "full_replay", False), ("continuation", "kv_continuation", True)),
)
def test_role_client_runs_executor_summarizer_ab_and_writes_audit(
    tmp_path: Path,
    mode: str,
    expected_lane: str,
    capture: bool,
) -> None:
    delegate = _Delegate()
    kv_client = _KVClient()
    audit_path = tmp_path / mode / "audit.json"
    client = EngineLocalKVRoleClient(
        delegate,
        EngineLocalKVRoleClientConfig(
            mode=mode,
            task_id="task-1",
            audit_path=audit_path,
            parent_tokens=4,
        ),
        kv_client=kv_client,
        token_codec=_Codec(),
    )

    planner = asyncio.run(
        client.complete([ChatMessage(role="user", content="planner")], purpose="planner")
    )
    executor = asyncio.run(
        client.complete([ChatMessage(role="user", content="executor")], purpose="executor")
    )
    summarizer = asyncio.run(
        client.complete([ChatMessage(role="user", content="summarizer")], purpose="summarizer")
    )

    assert planner.model == "delegate"
    assert executor.usage.prompt_tokens == 6
    assert summarizer.usage.prompt_tokens == 7
    assert delegate.calls == ["planner"]
    assert kv_client.produce_payloads[0]["capture_kv"] is capture
    assert kv_client.consumer_payloads[0]["lane"] == expected_lane
    assert ("handle_id" in kv_client.consumer_payloads[0]) is capture
    assert kv_client.release_calls == (["handle-1"] if capture else [])
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["status"] == "consumer_complete"
    assert audit["producer_calls"][0]["parent_tokens"] == 4
    assert audit["consumer_calls"][0]["suffix_tokens"] == 3
    assert audit["consumer_calls"][0]["lane"] == expected_lane
    assert audit["capture_count"] == int(capture)
    assert audit["load_count"] == int(capture)


def test_role_client_fails_closed_when_role_prefixes_differ(tmp_path: Path) -> None:
    class _MismatchCodec(_Codec):
        def encode(self, text: str):
            if text == "summarizer":
                return (9, 2, 3, 4, 20)
            return super().encode(text)

    kv_client = _KVClient()
    client = EngineLocalKVRoleClient(
        _Delegate(),
        EngineLocalKVRoleClientConfig(
            mode="continuation",
            task_id="task-mismatch",
            audit_path=tmp_path / "audit.json",
            parent_tokens=4,
        ),
        kv_client=kv_client,
        token_codec=_MismatchCodec(),
    )
    asyncio.run(client.complete([ChatMessage(role="user", content="executor")], purpose="executor"))

    with pytest.raises(ValueError, match="shared parent"):
        asyncio.run(
            client.complete([ChatMessage(role="user", content="summarizer")], purpose="summarizer")
        )

    client.close()
    assert kv_client.release_calls == ["handle-1"]
