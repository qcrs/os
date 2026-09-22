from types import SimpleNamespace

import statebus.integrations.llm as llm_module
from statebus.integrations.llm import (
    LLMConfig,
    OpenAICompatibleLLMClient,
    ProviderConfig,
    RoleLLMConfig,
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
