from types import SimpleNamespace

import statebus.integrations.llm as llm_module
from statebus.integrations.llm import (
    ChatMessage,
    LLMConfig,
    OpenAICompatibleLLMClient,
    ProviderConfig,
    RoleLLMConfig,
    _build_openai_request,
    _estimate_chat_prompt_tokens,
)


def _config(mode: str) -> LLMConfig:
    return LLMConfig(
        mode=mode,
        providers={
            "default": ProviderConfig(
                base_url="http://127.0.0.1:53334/v1",
                api_key="test-key" if mode == "api" else None,
                timeout_s=17.0,
            )
        },
        roles={"planner": RoleLLMConfig(model="test-model")},
    )


def test_local_vllm_client_does_not_inherit_host_proxy_environment(monkeypatch) -> None:
    captured: dict[str, object] = {}
    transport = SimpleNamespace(name="local-http-client")

    def fake_http_client(**kwargs: object) -> object:
        captured["http_client_kwargs"] = kwargs
        return transport

    def fake_openai(**kwargs: object) -> object:
        captured["openai_kwargs"] = kwargs
        return SimpleNamespace()

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", fake_http_client)
    monkeypatch.setattr(llm_module, "AsyncOpenAI", fake_openai)

    OpenAICompatibleLLMClient(_config("local_vllm"))._build_provider_client("default")

    assert captured["http_client_kwargs"] == {"timeout": 17.0, "trust_env": False}
    assert captured["openai_kwargs"]["http_client"] is transport


def test_remote_api_client_keeps_default_proxy_behavior(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fail_http_client(**kwargs: object) -> object:
        raise AssertionError(f"unexpected custom http client: {kwargs}")

    def fake_openai(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", fail_http_client)
    monkeypatch.setattr(llm_module, "AsyncOpenAI", fake_openai)

    OpenAICompatibleLLMClient(_config("api"))._build_provider_client("default")

    assert captured["http_client"] is None


def test_completion_budget_is_capped_by_estimated_prompt_and_context() -> None:
    messages = [ChatMessage(role="user", content=("Generate a complete Python report. " * 160))]
    context_tokens = 8192
    margin = 128
    role = RoleLLMConfig(
        model="test-model",
        max_tokens=2200,
        max_context_tokens=context_tokens,
        max_context_safety_margin_tokens=margin,
    )

    request = _build_openai_request(role, messages)

    assert request["max_tokens"] == min(
        2200,
        context_tokens - _estimate_chat_prompt_tokens(messages) - margin,
    )
    assert _estimate_chat_prompt_tokens(messages) + request["max_tokens"] + margin <= context_tokens


def test_completion_budget_fails_closed_when_prompt_exceeds_context() -> None:
    role = RoleLLMConfig(model="test-model", max_tokens=2200, max_context_tokens=128,
                         max_context_safety_margin_tokens=32)
    messages = [ChatMessage(role="user", content="large prompt " * 200)]

    try:
        _build_openai_request(role, messages)
    except ValueError as exc:
        assert "prompt_exceeds_model_context" in str(exc)
    else:
        raise AssertionError("request was built without room for a completion")


def test_completion_budget_does_not_overreserve_ascii_prompt_for_normal_code_output(monkeypatch) -> None:
    monkeypatch.delenv("STATEBUS_LLM_TOKENIZER_PATH", raising=False)
    monkeypatch.delenv("STATEBUS_VLLM_TOKENIZER_PATH", raising=False)
    llm_module._PROMPT_TOKENIZER_CACHE.clear()
    messages = [ChatMessage(role="user", content=("Compute each field from the authorized row and write the complete output. " * 260))]
    role = RoleLLMConfig(
        model="test-model",
        max_tokens=2200,
        max_context_tokens=8192,
        max_context_safety_margin_tokens=128,
    )
    request = _build_openai_request(role, messages)
    assert request["max_tokens"] == 2200
    assert _estimate_chat_prompt_tokens(messages) + request["max_tokens"] + 128 <= 8192
