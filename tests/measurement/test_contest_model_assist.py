from __future__ import annotations

import asyncio
import json
from pathlib import Path

from statebus.benchmark.contest_dsl_fixtures import offline_program
from statebus.benchmark.contest_dsl_taskpack import (
    bind_inputs,
    generate_sealed,
    release_task,
    task_contract,
)
from statebus.benchmark.contest_model_assist import (
    ContestModelAssistSettings,
    ContestModelAssistClient,
    build_contest_model_assist_client,
)
from statebus.benchmark.request_journal import JournalClient
from statebus.benchmark import contest_dsl_mainline as runner
from statebus.integrations.llm import ChatMessage, LLMResult, LLMUsage
from statebus.integrations.vllm_kv.client import KVStreamResult
from statebus.integrations.vllm_kv.role_client import (
    EngineLocalKVRoleClient,
    EngineLocalKVRoleClientConfig,
)
from statebus.runtime.prefix_identity import shared_prefix_envelope
from statebus.utils import sha256_digest


_TOP_LOGPROBS = [
    {
        "token": "{",
        "logprob": -0.1,
        "top_logprobs": [
            {"token": "{", "logprob": -0.1},
            {"token": "[", "logprob": -1.2},
        ],
    }
]


class _FakeProvider:
    def __init__(self, task_id: str):
        self.task = task_contract(task_id, profile="mechanism_simple_v2")
        self.calls: list[tuple[str, list[ChatMessage]]] = []
        self.request_events: list[dict[str, object]] = []
        self.closed = False
        self._executor_calls = 0

    async def complete(self, messages, *, purpose, temperature=None, response_schema=None):
        del temperature
        messages = list(messages)
        self.calls.append((purpose, messages))
        try:
            payload = json.loads(messages[-1].content)
        except json.JSONDecodeError:
            return LLMResult(text="{}", model="fake", usage=LLMUsage(1, 1, 2))
        self.request_events.append({
            "event": "provider_request",
            "role": purpose,
            "response_prompt_tokens": 10,
            "response_completion_tokens": 5,
            "response_total_tokens": 15,
        })
        if purpose == "executor":
            self._executor_calls += 1
            refs = {name: name for name in payload["authorized_input_refs"]}
            raw = offline_program(self.task, refs).canonical_payload()
        else:
            raw = {"claims": []}
            for row in payload["rows"]:
                entity = row.get("unit_id", row.get("site_id"))
                evidence = next(item for item in payload["evidence"] if item["text"].startswith(entity + " "))
                text = " ".join(
                    f"{key}={str(value).lower() if isinstance(value, bool) else value}"
                    for key, value in row.items()
                ) + ". " + evidence["text"]
                if isinstance(response_schema, dict) and response_schema.get("title") == "statebus_simple_fact_report_v1":
                    raw["claims"].append({
                        "row": row,
                        "evidence_id": evidence["id"],
                        "context_text": evidence["text"],
                    })
                else:
                    raw["claims"].append({
                        "text": text,
                        "evidence_id": evidence["id"],
                        "numeric_fields": {
                            key: float(value) for key, value in row.items()
                            if type(value) in (int, float)
                        },
                    })
        return LLMResult(
            text=json.dumps(raw),
            model="fake",
            usage=LLMUsage(10, 5, 15),
            top_logprobs=_TOP_LOGPROBS,
        )

    def describe(self):
        return {"backend": "fake", "model": "fake"}

    def close(self):
        self.closed = True


def test_fake_live_run_slot_records_same_call_logit_and_closes_client(tmp_path, monkeypatch):
    sealed, public, slot = tmp_path / "sealed", tmp_path / "public", tmp_path / "slot"
    generate_sealed(sealed, profile="mechanism_simple_v2")
    release_task(sealed, public, "F01", profile="mechanism_simple_v2")
    provider = _FakeProvider("F01")

    def fake_live(path, model, base_url, max_context, provider_timeout_s, **kwargs):
        settings = ContestModelAssistSettings(
            profile=kwargs["model_assist_profile"],
            task_id=kwargs["task_id"],
            run_id=kwargs["run_id"],
            root=kwargs["runtime_root"],
            model=model,
            base_url=base_url,
            max_context=max_context,
            provider_timeout_s=provider_timeout_s,
        )
        return build_contest_model_assist_client(provider, journal_path=path, settings=settings)

    monkeypatch.setattr(runner, "_live_client", fake_live)
    result = runner.run_slot(
        slot,
        public,
        "F01",
        history={},
        variant="P-TEXT",
        mode="live",
        profile="mechanism_simple_v2",
        model_assist_profile="logit",
    )

    assert result["status"] == "success"
    assert len(provider.calls) == 2
    assert [purpose for purpose, _ in provider.calls] == ["executor", "summarizer"]
    assert all(len(messages) == 2 for _, messages in provider.calls)
    observations = [json.loads(line) for line in (slot / "model-assist.jsonl").read_text().splitlines()]
    assert [item["role"] for item in observations] == ["executor", "summarizer"]
    assert all(item["observations"]["logit"]["status"] == "available" for item in observations)
    assert observations[0]["stage"] == "generate"
    assert observations[1]["stage"] == "report"
    assert observations[0]["attempt"]
    assert observations[1]["batch_index"] == 0
    assert provider.closed is True


def test_off_profile_does_not_parse_ambient_model_assist_configuration(monkeypatch, tmp_path):
    import statebus.integrations.llm as llm

    provider = _FakeProvider("F01")
    monkeypatch.setenv("STATEBUS_MODEL_ASSIST_PROFILE", "kv_continuation")
    monkeypatch.setenv("STATEBUS_KV_API_BASE_URL", "http://not-used.invalid")
    monkeypatch.setattr(llm, "build_llm_client", lambda config: provider)
    client = runner._live_client(
        tmp_path / "provider.jsonl",
        "qwen3-32b",
        "http://127.0.0.1:53334/v1",
        8192,
        model_assist_profile="off",
    )
    assert isinstance(client, JournalClient)
    assert not isinstance(client, ContestModelAssistClient)


def test_kv_logit_keeps_same_call_logit_observation(tmp_path):
    provider = _FakeProvider("F01")
    prefix = shared_prefix_envelope("public")
    kv = _KV()
    role_client = EngineLocalKVRoleClient(
        provider,
        EngineLocalKVRoleClientConfig(
            mode="continuation", task_id="task", audit_path=tmp_path / "kv.json",
            parent_tokens=4, shared_prefix_text="public", profile="kv_logit",
            logprobs=True, top_logprobs=20,
        ),
        kv_client=kv,
        token_codec=_MessageCodec(prefix),
    )
    wrapper = ContestModelAssistClient(
        JournalClient(provider, tmp_path / "provider.jsonl"),
        ContestModelAssistSettings(
            profile="kv_logit", task_id="task", run_id="run", root=tmp_path,
            model="qwen3-32b", base_url="http://127.0.0.1:53334/v1", max_context=8192,
            provider_timeout_s=10, shared_prefix_text="public",
        ),
        kv_client=role_client,
        kv_journal=JournalClient(role_client, tmp_path / "provider.jsonl"),
    )
    result = asyncio.run(
        wrapper.complete(
            [ChatMessage("user", '{"authorized_input_refs":["source"]}')],
            purpose="executor",
        )
    )
    wrapper.observe_result(result, context={"role": "executor", "stage": "generate"})
    observation = json.loads((tmp_path / "model-assist.jsonl").read_text())
    assert observation["observations"]["logit"]["status"] == "available"
    wrapper.close()


def test_auto_without_shared_prefix_uses_ordinary_provider(tmp_path):
    delegate = _FakeProvider("F01")
    kv = _KV()
    codec = _MessageCodec(shared_prefix_envelope("public"))
    role_client = EngineLocalKVRoleClient(
        delegate,
        EngineLocalKVRoleClientConfig(
            mode="auto", task_id="task", audit_path=tmp_path / "kv.json",
            parent_tokens=4, profile="auto",
        ),
        kv_client=kv,
        token_codec=codec,
    )
    wrapper = ContestModelAssistClient(
        JournalClient(delegate, tmp_path / "provider.jsonl"),
        ContestModelAssistSettings(
            profile="auto", task_id="task", run_id="run", root=tmp_path,
            model="qwen3-32b", base_url="http://127.0.0.1:53334/v1", max_context=8192,
            provider_timeout_s=10,
        ),
        kv_client=role_client,
        kv_journal=JournalClient(role_client, tmp_path / "provider.jsonl"),
    )
    result = asyncio.run(
        wrapper.complete(
            [ChatMessage("user", '{"authorized_input_refs":["source"]}')],
            purpose="executor",
        )
    )
    wrapper.observe_result(result, context={"role": "executor", "stage": "generate"})
    assert kv.produced == []
    observation = json.loads((tmp_path / "model-assist.jsonl").read_text())
    assert observation["effective_mode"] == "ordinary"
    assert observation["route_reason"] == "auto_no_eligible_reuse"
    wrapper.close()


def test_auto_uses_apc_only_after_kv_readiness_fails(tmp_path):
    class _UnavailableKV(_KV):
        def health(self):
            return {"status": "not_ready"}

    delegate = _FakeProvider("F01")
    kv = _UnavailableKV()
    role_client = EngineLocalKVRoleClient(
        delegate,
        EngineLocalKVRoleClientConfig(
            mode="auto", task_id="task", audit_path=tmp_path / "kv.json",
            parent_tokens=4, shared_prefix_text="public", profile="auto",
        ),
        kv_client=kv,
        token_codec=_MessageCodec(shared_prefix_envelope("public")),
    )
    wrapper = ContestModelAssistClient(
        JournalClient(delegate, tmp_path / "provider.jsonl"),
        ContestModelAssistSettings(
            profile="auto", task_id="task", run_id="run", root=tmp_path,
            model="qwen3-32b", base_url="http://127.0.0.1:53334/v1", max_context=8192,
            provider_timeout_s=10, shared_prefix_text="public",
            apc_enabled=True, apc_service_ready=True,
        ),
        kv_client=role_client,
        kv_journal=JournalClient(role_client, tmp_path / "provider.jsonl"),
    )
    asyncio.run(
        wrapper.complete(
            [ChatMessage("system", "instructions"), ChatMessage("user", "executor")],
            purpose="executor",
        )
    )
    assert kv.produced == []
    assert delegate.calls[0][1][0].content.startswith(shared_prefix_envelope("public"))
    wrapper.observe_result(
        LLMResult(text="{}", model="fake"),
        context={"role": "executor", "stage": "generate"},
    )
    observation = json.loads((tmp_path / "model-assist.jsonl").read_text())
    assert observation["effective_mode"] == "apc_full_prompt"
    assert observation["observations"]["apc"]["service_ready_attested"] is True
    assert isinstance(observation["observations"]["apc"]["prefix_identity"], str)
    wrapper.close()


def test_auto_ordinary_route_preserves_original_messages(tmp_path):
    class _UnavailableKV(_KV):
        def health(self):
            return {"status": "not_ready"}

    delegate = _FakeProvider("F01")
    role_client = EngineLocalKVRoleClient(
        delegate,
        EngineLocalKVRoleClientConfig(
            mode="auto", task_id="task", audit_path=tmp_path / "kv.json",
            parent_tokens=4, shared_prefix_text="public", profile="auto",
        ),
        kv_client=_UnavailableKV(),
        token_codec=_MessageCodec(shared_prefix_envelope("public")),
    )
    wrapper = ContestModelAssistClient(
        JournalClient(delegate, tmp_path / "provider.jsonl"),
        ContestModelAssistSettings(
            profile="auto", task_id="task", run_id="run", root=tmp_path,
            model="qwen3-32b", base_url="http://127.0.0.1:53334/v1", max_context=8192,
            provider_timeout_s=10, shared_prefix_text="public",
        ),
        kv_client=role_client,
        kv_journal=JournalClient(role_client, tmp_path / "provider.jsonl"),
    )
    original = [ChatMessage("system", "instructions"), ChatMessage("user", "executor")]
    asyncio.run(wrapper.complete(original, purpose="executor"))
    assert delegate.calls[0][1] == original
    wrapper.close()


class _MessageCodec:
    def __init__(self, prefix: str):
        self.prefix = prefix
        self.messages: list[list[dict[str, str]]] = []

    def encode_messages(self, messages, *, add_generation_prompt, chat_template_kwargs):
        del add_generation_prompt, chat_template_kwargs
        normalized = [dict(item) for item in messages]
        self.messages.append(normalized)
        if normalized[0]["content"].startswith(self.prefix):
            return (1, 2, 3, 4, 10 if normalized[-1]["content"] == "executor" else 20)
        raise AssertionError(normalized)

    def close(self):
        pass


class _KV:
    def __init__(self):
        self.releases: list[str] = []
        self.produced: list[dict] = []
        self.consumed: list[dict] = []

    def health(self):
        return {
            "status": "ready", "engine_id": "engine", "engine_generation": "gen",
            "model": "qwen3-32b", "model_revision": "rev", "tokenizer_digest": "tok",
            "dtype": "bfloat16", "compatibility_digest": "compat", "block_size": 2,
            "automatic_prefix_caching": False,
            "compatibility_signature": {"engine_id": "engine", "engine_generation": "gen",
                "model_id": "qwen3-32b", "model_revision": "rev", "tokenizer_digest": "tok",
                "dtype": "bfloat16", "block_size": 2},
        }

    def produce(self, payload):
        self.produced.append(dict(payload))
        return {
            "status": "success", "handle_id": "h", "engine_generation": "gen",
            "handle": {
                "handle_id": "h", "engine_id": "engine", "engine_generation": "gen",
                "model_id": "qwen3-32b", "model_revision": "rev", "tokenizer_digest": "tok",
                "task_id": payload["task_id"], "producer_request_id": payload["request_id"],
                "seq_len": 4, "block_size": 2, "token_digest": sha256_digest([1, 2, 3, 4]),
                "dtype": "bfloat16", "status": "ready",
            },
            "output_text": "{}", "output_token_ids": [1],
            "top_logprobs": _TOP_LOGPROBS,
        }

    def continue_stream(self, payload):
        self.consumed.append(dict(payload))
        suffix = tuple(payload["suffix_token_ids"])
        return KVStreamResult(
            payload={"status": "success", "engine_generation": "gen",
                "logical_token_digest": sha256_digest([1, 2, 3, 4, *suffix]),
                "output_text": "{}", "output_token_ids": [1]},
            client_ttft_ms=1, client_wall_ms=2, api_request_bytes=3, token_event_count=1,
        )

    def release(self, handle_id):
        self.releases.append(handle_id)
        return {"status": "released"}

    def close(self):
        pass


def test_kv_pair_preserves_messages_and_second_summarizer_is_ordinary(tmp_path):
    prefix = shared_prefix_envelope("public")
    delegate = _FakeProvider("F01")
    kv = _KV()
    codec = _MessageCodec(prefix)
    role_client = EngineLocalKVRoleClient(
        delegate,
        EngineLocalKVRoleClientConfig(
            mode="continuation", task_id="task", audit_path=tmp_path / "kv.json",
            parent_tokens=4, shared_prefix_text="public", profile="kv_continuation",
        ),
        kv_client=kv,
        token_codec=codec,
    )
    wrapper = ContestModelAssistClient(
        JournalClient(delegate, tmp_path / "provider.jsonl"),
        ContestModelAssistSettings(
            profile="kv_continuation", task_id="task", run_id="run", root=tmp_path,
            model="qwen3-32b", base_url="http://127.0.0.1:53334/v1", max_context=8192,
            provider_timeout_s=10, shared_prefix_text="public",
        ),
        kv_client=role_client,
        kv_journal=JournalClient(role_client, tmp_path / "provider.jsonl"),
    )
    messages = [ChatMessage("system", "instructions"), ChatMessage("user", "executor")]
    asyncio.run(wrapper.complete(messages, purpose="executor"))
    asyncio.run(wrapper.complete([ChatMessage("system", "instructions"), ChatMessage("user", "summarizer")], purpose="summarizer"))
    asyncio.run(wrapper.complete([ChatMessage("system", "instructions"), ChatMessage("user", "summarizer")], purpose="summarizer"))
    assert len(kv.produced) == 1
    assert len(kv.consumed) == 1
    assert kv.releases == ["h"]
    full_messages = [messages for messages in codec.messages if len(messages) == 2]
    assert [[item["role"] for item in messages] for messages in full_messages] == [
        ["system", "user"], ["system", "user"],
    ]
    assert all(len(item) == 2 for item in full_messages)
    assert [purpose for purpose, _ in delegate.calls][-1] == "summarizer"
    wrapper.close()


def test_kv_pair_derives_parent_from_real_shared_token_boundary(tmp_path):
    prefix = shared_prefix_envelope("public")
    delegate = _FakeProvider("F01")
    kv = _KV()
    codec = _MessageCodec(prefix)
    role_client = EngineLocalKVRoleClient(
        delegate,
        EngineLocalKVRoleClientConfig(
            mode="continuation", task_id="task", audit_path=tmp_path / "kv.json",
            parent_tokens=0, shared_prefix_text="public", profile="kv_continuation",
        ),
        kv_client=kv,
        token_codec=codec,
    )

    asyncio.run(role_client.complete(
        [
            ChatMessage("system", prefix + '<statebus-role-suffix-v2 role="executor">\ninstructions'),
            ChatMessage("user", "executor"),
        ],
        purpose="executor",
    ))

    assert kv.produced[0]["parent_token_ids"] == [1, 2, 3, 4]
    role_client.close()
