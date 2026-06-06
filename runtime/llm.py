from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

import yaml
from openai import AsyncOpenAI

DEFAULT_LLM_BASE_URL = "https://api.deepseek.com"
DEFAULT_LLM_MODEL = "deepseek-v4-flash"
DEFAULT_LLM_CONFIG_FILE = Path("deploy/statebus_llm.yaml.local")


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    usage: LLMUsage = field(default_factory=LLMUsage)


@dataclass(frozen=True)
class ProviderConfig:
    kind: str = "openai_compatible"
    base_url: str | None = DEFAULT_LLM_BASE_URL
    api_key: str | None = None
    api_key_env: str | None = "STATEBUS_LLM_API_KEY"
    timeout_s: float = 60.0
    default_headers: dict[str, str] = field(default_factory=dict)

    @property
    def resolved_api_key(self) -> str | None:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.getenv(self.api_key_env)
        return None


@dataclass(frozen=True)
class RoleLLMConfig:
    provider: str = "default"
    model: str = DEFAULT_LLM_MODEL
    json_output: bool = True
    temperature: float | None = 0.0
    max_tokens: int | None = None
    reasoning_effort: str | None = None
    extra_body: dict[str, Any] = field(default_factory=dict)
    request_kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMConfig:
    mode: str = "deterministic"
    source: str = "env"
    providers: dict[str, ProviderConfig] = field(
        default_factory=lambda: {"default": ProviderConfig()}
    )
    roles: dict[str, RoleLLMConfig] = field(
        default_factory=lambda: {
            "planner": RoleLLMConfig(),
            "summarizer": RoleLLMConfig(),
        }
    )

    @classmethod
    def from_env(cls) -> "LLMConfig":
        default_model = (
            os.getenv("STATEBUS_LLM_DEFAULT_MODEL")
            or os.getenv("STATEBUS_LLM_MODEL")
            or DEFAULT_LLM_MODEL
        )
        provider = ProviderConfig(
            kind=os.getenv("STATEBUS_LLM_PROVIDER_KIND", "openai_compatible"),
            base_url=(
                os.getenv("STATEBUS_LLM_BASE_URL")
                or os.getenv("OPENAI_BASE_URL")
                or DEFAULT_LLM_BASE_URL
            ),
            api_key=os.getenv("OPENAI_API_KEY") if os.getenv("STATEBUS_LLM_API_KEY") is None else None,
            api_key_env=(
                "STATEBUS_LLM_API_KEY"
                if os.getenv("STATEBUS_LLM_API_KEY") is not None
                else "OPENAI_API_KEY"
            ),
            timeout_s=float(os.getenv("STATEBUS_LLM_TIMEOUT_S", "60")),
        )
        planner = RoleLLMConfig(
            provider=os.getenv("STATEBUS_LLM_PLANNER_PROVIDER", "default"),
            model=os.getenv("STATEBUS_LLM_PLANNER_MODEL") or default_model,
            json_output=_env_bool("STATEBUS_LLM_PLANNER_JSON_MODE", True),
            temperature=_env_optional_float("STATEBUS_LLM_PLANNER_TEMPERATURE", 0.0),
            max_tokens=_env_optional_int("STATEBUS_LLM_PLANNER_MAX_TOKENS"),
            reasoning_effort=os.getenv("STATEBUS_LLM_PLANNER_REASONING_EFFORT"),
            extra_body=_env_json("STATEBUS_LLM_PLANNER_EXTRA_BODY"),
            request_kwargs=_env_json("STATEBUS_LLM_PLANNER_REQUEST_KWARGS"),
        )
        summarizer = RoleLLMConfig(
            provider=os.getenv("STATEBUS_LLM_SUMMARIZER_PROVIDER", "default"),
            model=os.getenv("STATEBUS_LLM_SUMMARIZER_MODEL") or default_model,
            json_output=_env_bool("STATEBUS_LLM_SUMMARIZER_JSON_MODE", True),
            temperature=_env_optional_float("STATEBUS_LLM_SUMMARIZER_TEMPERATURE", 0.0),
            max_tokens=_env_optional_int("STATEBUS_LLM_SUMMARIZER_MAX_TOKENS"),
            reasoning_effort=os.getenv("STATEBUS_LLM_SUMMARIZER_REASONING_EFFORT"),
            extra_body=_env_json("STATEBUS_LLM_SUMMARIZER_EXTRA_BODY"),
            request_kwargs=_env_json("STATEBUS_LLM_SUMMARIZER_REQUEST_KWARGS"),
        )
        return cls(
            mode=os.getenv("STATEBUS_LLM_MODE", "deterministic").strip().lower(),
            source="env",
            providers={"default": provider},
            roles={"planner": planner, "summarizer": summarizer},
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "LLMConfig":
        config_path = Path(path)
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError(f"llm config file must be a mapping: {config_path}")
        providers_payload = payload.get("providers") or {}
        roles_payload = payload.get("roles") or {}
        if not providers_payload:
            providers_payload = {"default": {}}
        providers = {
            str(name): _provider_from_mapping(name=str(name), payload=dict(item or {}))
            for name, item in providers_payload.items()
        }
        roles = {
            "planner": _role_from_mapping(
                role_name="planner",
                payload=dict(roles_payload.get("planner") or {}),
            ),
            "summarizer": _role_from_mapping(
                role_name="summarizer",
                payload=dict(roles_payload.get("summarizer") or {}),
            ),
        }
        return cls(
            mode=str(payload.get("mode", "deterministic")).strip().lower(),
            source=str(config_path),
            providers=providers,
            roles=roles,
        )

    @classmethod
    def from_runtime(cls, config_file: str | Path | None = None) -> "LLMConfig":
        config_path = Path(
            config_file
            or os.getenv("STATEBUS_LLM_CONFIG_FILE")
            or DEFAULT_LLM_CONFIG_FILE
        )
        if config_path.exists():
            config = cls.from_file(config_path)
        else:
            config = cls.from_env()
        if os.getenv("STATEBUS_LLM_MODE"):
            config = config.with_mode(os.getenv("STATEBUS_LLM_MODE", config.mode))
        return config

    @property
    def use_api(self) -> bool:
        return self.mode == "api"

    def provider_config(self, name: str) -> ProviderConfig:
        if name not in self.providers:
            raise KeyError(f"unknown llm provider {name}")
        return self.providers[name]

    def role_config(self, purpose: str) -> RoleLLMConfig:
        if purpose not in self.roles:
            raise KeyError(f"unknown llm role {purpose}")
        return self.roles[purpose]

    def with_mode(self, mode: str) -> "LLMConfig":
        return replace(self, mode=mode.strip().lower())

    def with_provider_override(self, provider_name: str, **kwargs: object) -> "LLMConfig":
        provider = self.provider_config(provider_name)
        updated = replace(provider, **kwargs)
        providers = dict(self.providers)
        providers[provider_name] = updated
        return replace(self, providers=providers)

    def with_role_override(self, role_name: str, **kwargs: object) -> "LLMConfig":
        role = self.role_config(role_name)
        updated = replace(role, **kwargs)
        roles = dict(self.roles)
        roles[role_name] = updated
        return replace(self, roles=roles)

    def require_api_ready(self) -> None:
        if not self.use_api:
            return
        for provider_name, provider in self.providers.items():
            if provider.kind != "openai_compatible":
                raise ValueError(f"unsupported llm provider kind: {provider.kind}")
            if not provider.resolved_api_key:
                raise ValueError(
                    f"provider {provider_name} missing api key; set {provider.api_key_env or 'api_key'}"
                )


class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        purpose: str,
        temperature: float | None = None,
    ) -> LLMResult: ...

    def describe(self) -> dict[str, object]: ...


class OpenAICompatibleLLMClient:
    def __init__(self, config: LLMConfig) -> None:
        config.require_api_ready()
        self.config = config
        self._clients: dict[str, AsyncOpenAI] = {}
        for provider_name, provider in self.config.providers.items():
            self._clients[provider_name] = AsyncOpenAI(
                api_key=provider.resolved_api_key,
                base_url=provider.base_url,
                timeout=provider.timeout_s,
                default_headers=provider.default_headers or None,
            )

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        purpose: str,
        temperature: float | None = None,
    ) -> LLMResult:
        role_config = self.config.role_config(purpose)
        provider_name = role_config.provider
        if provider_name not in self._clients:
            raise KeyError(f"provider {provider_name} is not initialized")
        request = _build_openai_request(role_config, messages, temperature=temperature)
        response = await self._clients[provider_name].chat.completions.create(**request)
        choice = response.choices[0]
        content = _coerce_content_to_text(choice.message.content)
        usage = getattr(response, "usage", None)
        return LLMResult(
            text=content.strip(),
            model=getattr(response, "model", None) or role_config.model,
            usage=LLMUsage(
                prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
            ),
        )

    def describe(self) -> dict[str, object]:
        planner = self.config.role_config("planner")
        summarizer = self.config.role_config("summarizer")
        return {
            "backend": "openai_compatible",
            "mode": self.config.mode,
            "source": self.config.source,
            "planner_provider": planner.provider,
            "planner_model": planner.model,
            "summarizer_provider": summarizer.provider,
            "summarizer_model": summarizer.model,
            "providers": {
                name: {
                    "kind": provider.kind,
                    "base_url": provider.base_url,
                }
                for name, provider in self.config.providers.items()
            },
        }


class DeterministicLLMClient:
    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        purpose: str,
        temperature: float | None = None,
    ) -> LLMResult:
        del temperature
        if not messages:
            raise ValueError("deterministic llm requires at least one message")
        user_content = messages[-1].content
        if purpose == "planner":
            if "<sb-plan-v1>" in user_content:
                payload = parse_compact_protocol_planner_brief(user_content)
                plan = {
                    "r": {
                        "q": payload["query"],
                        "e": payload["evidence_text"],
                        "t": payload.get("tags", []),
                        "rt": payload.get("reuse_tags", payload.get("tags", [])),
                        "sig": payload.get("reuse_signature", ""),
                        "er": payload.get("expected_reuse", False),
                        "reuse": True,
                    },
                    "x": {},
                    "s": {
                        "h": payload["summary_hint"],
                        "t": payload.get("tags", []),
                        "rt": payload.get("reuse_tags", payload.get("tags", [])),
                        "sig": payload.get("reuse_signature", ""),
                        "er": payload.get("expected_reuse", False),
                    },
                }
            else:
                payload = (
                    parse_tagged_json(user_content, "statebus-planner-input")
                    if "<statebus-planner-input>" in user_content
                    else parse_text_planner_brief(user_content)
                )
                plan = {
                    "steps": [
                        {
                            "step_id": "retrieve",
                            "owner_agent": "retriever",
                            "action": "RETRIEVE_EVIDENCE",
                            "input_state_refs": [],
                            "params": {
                                "query": payload["query"],
                                "evidence_text": payload["evidence_text"],
                                "tags": payload.get("tags", []),
                                "allow_memory_reuse": True,
                            },
                            "depends_on": [],
                        },
                        {
                            "step_id": "execute",
                            "owner_agent": "executor",
                            "action": "EXECUTE_PLAYBOOK",
                            "input_state_refs": [],
                            "params": {},
                            "depends_on": ["retrieve"],
                        },
                        {
                            "step_id": "summarize",
                            "owner_agent": "summarizer",
                            "action": "SUMMARIZE_AND_COMMIT",
                            "input_state_refs": [],
                            "params": {
                                "summary_hint": payload["summary_hint"],
                                "tags": payload.get("tags", []),
                            },
                            "depends_on": ["retrieve", "execute"],
                        },
                    ]
                }
            return LLMResult(
                text=json.dumps(plan, ensure_ascii=False, sort_keys=True),
                model=self.config.role_config("planner").model,
            )
        if purpose == "summarizer":
            compact_protocol = "<sb-summary-v1>" in user_content
            if compact_protocol:
                payload = parse_compact_protocol_summarizer_handoff(user_content)
            else:
                payload = (
                    parse_tagged_json(user_content, "statebus-summary-input")
                    if "<statebus-summary-input>" in user_content
                    else parse_text_summarizer_handoff(user_content)
                )
            reusable_steps = list(payload.get("reusable_steps") or ["retrieve", "execute"])
            summary = (
                f"{payload['summary_hint']}\n"
                f"Evidence: {payload['evidence_text']}\n"
                f"Playbook:\n{payload['actions_text']}"
            )
            summary_payload = (
                {
                    "s": summary,
                    "c": 0.95,
                    "t": payload.get("tags", []),
                    "r": reusable_steps,
                }
                if compact_protocol
                else {
                    "summary": summary,
                    "confidence": 0.95,
                    "tags": payload.get("tags", []),
                    "reusable_steps": reusable_steps,
                }
            )
            return LLMResult(
                text=json.dumps(summary_payload, ensure_ascii=False, sort_keys=True),
                model=self.config.role_config("summarizer").model,
            )
        raise ValueError(f"unsupported deterministic llm purpose: {purpose}")

    def describe(self) -> dict[str, object]:
        planner = self.config.role_config("planner")
        summarizer = self.config.role_config("summarizer")
        return {
            "backend": "deterministic",
            "mode": self.config.mode,
            "source": self.config.source,
            "planner_provider": planner.provider,
            "planner_model": planner.model,
            "summarizer_provider": summarizer.provider,
            "summarizer_model": summarizer.model,
            "providers": {
                name: {
                    "kind": provider.kind,
                    "base_url": provider.base_url,
                }
                for name, provider in self.config.providers.items()
            },
        }


def build_llm_client(config: LLMConfig | None = None) -> LLMClient:
    active_config = config or LLMConfig.from_runtime()
    if active_config.use_api:
        return OpenAICompatibleLLMClient(active_config)
    return DeterministicLLMClient(active_config)


def tagged_json_block(tag: str, payload: dict[str, Any]) -> str:
    return f"<{tag}>\n{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n</{tag}>"


def parse_tagged_json(text: str, tag: str) -> dict[str, Any]:
    start_token = f"<{tag}>"
    end_token = f"</{tag}>"
    start = text.find(start_token)
    end = text.find(end_token)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"missing tagged json block {tag}")
    payload = text[start + len(start_token) : end].strip()
    return json.loads(payload)


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = _strip_code_fence(stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"expected json object in llm output: {text!r}")
    return json.loads(stripped[start : end + 1])


def parse_text_planner_brief(text: str) -> dict[str, Any]:
    return {
        "task_id": _extract_line_value(text, "Task ID:"),
        "task_group": _extract_line_value(text, "Task group:"),
        "task_theme": _extract_line_value(text, "Task theme:"),
        "goal": _extract_block(text, "Goal:\n", "\n\nSearch query:\n"),
        "query": _extract_block(text, "Search query:\n", "\n\nSummary hint:\n"),
        "summary_hint": _extract_block(text, "Summary hint:\n", "\n\nEvidence note:\n"),
        "evidence_text": _extract_after(text, "Evidence note:\n"),
        "tags": _split_csv(_extract_line_value(text, "Tags:")),
    }


def parse_compact_protocol_planner_brief(text: str) -> dict[str, Any]:
    payload = parse_tagged_json(text, "sb-plan-v1")
    return {
        "goal": str(payload.get("g", "")),
        "query": str(payload.get("q", "")),
        "evidence_text": str(payload.get("e", "")),
        "summary_hint": str(payload.get("h", "")),
        "tags": [str(tag) for tag in payload.get("t", [])],
        "reuse_tags": [str(tag) for tag in payload.get("rt", payload.get("t", []))],
        "reuse_signature": str(payload.get("sig", "")),
        "expected_reuse": bool(payload.get("er", False)),
    }


def parse_text_summarizer_handoff(text: str) -> dict[str, Any]:
    return {
        "task_id": _extract_line_value(text, "Task ID:"),
        "task_theme": _extract_line_value(text, "Task theme:"),
        "summary_hint": _extract_block(text, "Summary hint:\n", "\n\nEvidence note:\n"),
        "evidence_text": _extract_block(text, "Evidence note:\n", "\n\nPlaybook actions:\n"),
        "actions_text": _extract_after(text, "Playbook actions:\n"),
        "tags": _split_csv(_extract_line_value(text, "Tags:")),
        "reusable_steps": _split_csv(_extract_line_value(text, "Reusable steps:")),
    }


def parse_compact_protocol_summarizer_handoff(text: str) -> dict[str, Any]:
    payload = parse_tagged_json(text, "sb-summary-v1")
    return {
        "summary_hint": str(payload.get("h", "")),
        "evidence_text": str(payload.get("e", "")),
        "actions_text": str(payload.get("a", "")),
        "tags": [str(tag) for tag in payload.get("t", [])],
        "reusable_steps": [str(step_id) for step_id in payload.get("r", [])],
    }


def _provider_from_mapping(name: str, payload: dict[str, Any]) -> ProviderConfig:
    del name
    return ProviderConfig(
        kind=str(payload.get("kind", "openai_compatible")),
        base_url=payload.get("base_url", DEFAULT_LLM_BASE_URL),
        api_key=payload.get("api_key"),
        api_key_env=payload.get("api_key_env", "STATEBUS_LLM_API_KEY"),
        timeout_s=float(payload.get("timeout_s", 60.0)),
        default_headers=dict(payload.get("default_headers") or {}),
    )


def _role_from_mapping(role_name: str, payload: dict[str, Any]) -> RoleLLMConfig:
    default_model = DEFAULT_LLM_MODEL
    return RoleLLMConfig(
        provider=str(payload.get("provider", "default")),
        model=str(payload.get("model", default_model)),
        json_output=bool(payload.get("json_output", True)),
        temperature=_coerce_optional_float(payload.get("temperature"), 0.0),
        max_tokens=_coerce_optional_int(payload.get("max_tokens")),
        reasoning_effort=_coerce_optional_str(payload.get("reasoning_effort")),
        extra_body=dict(payload.get("extra_body") or {}),
        request_kwargs=dict(payload.get("request_kwargs") or {}),
    )


def _build_openai_request(
    role_config: RoleLLMConfig,
    messages: list[ChatMessage],
    *,
    temperature: float | None = None,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "model": role_config.model,
        "messages": [{"role": item.role, "content": item.content} for item in messages],
    }
    effective_temperature = role_config.temperature if temperature is None else temperature
    if effective_temperature is not None:
        request["temperature"] = effective_temperature
    if role_config.max_tokens is not None:
        request["max_tokens"] = role_config.max_tokens
    if role_config.json_output:
        request["response_format"] = {"type": "json_object"}
    if role_config.reasoning_effort is not None:
        request["reasoning_effort"] = role_config.reasoning_effort
    if role_config.extra_body:
        request["extra_body"] = role_config.extra_body
    if role_config.request_kwargs:
        request.update(role_config.request_kwargs)
    return request


def _coerce_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text:
                chunks.append(str(text))
                continue
            if isinstance(item, dict) and item.get("text"):
                chunks.append(str(item["text"]))
        return "\n".join(chunks)
    return str(content or "")


def _strip_code_fence(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _coerce_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _coerce_optional_float(value: object, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    if isinstance(value, str) and value.strip().lower() == "null":
        return None
    return float(value)


def _extract_line_value(text: str, label: str) -> str:
    marker = text.find(label)
    if marker == -1:
        raise ValueError(f"missing line label {label!r}")
    line = text[marker + len(label) :].splitlines()[0]
    return line.strip()


def _extract_block(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    if start == -1:
        raise ValueError(f"missing block start {start_marker!r}")
    start += len(start_marker)
    end = text.find(end_marker, start)
    if end == -1:
        raise ValueError(f"missing block end {end_marker!r}")
    return text[start:end].strip()


def _extract_after(text: str, start_marker: str) -> str:
    start = text.find(start_marker)
    if start == -1:
        raise ValueError(f"missing trailing block start {start_marker!r}")
    return text[start + len(start_marker) :].strip()


def _split_csv(text: str) -> list[str]:
    if not text.strip():
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def _env_optional_int(name: str) -> int | None:
    return _coerce_optional_int(os.getenv(name))


def _env_optional_float(name: str, default: float | None = None) -> float | None:
    return _coerce_optional_float(os.getenv(name), default)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_json(name: str) -> dict[str, Any]:
    raw = os.getenv(name)
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must be a JSON object")
    return payload
