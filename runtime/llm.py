from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

import yaml
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

DEFAULT_LLM_BASE_URL = "https://api.deepseek.com"
DEFAULT_LLM_MODEL = "deepseek-v4-flash"
DEFAULT_LLM_CONFIG_FILE = Path("deploy/statebus_llm.yaml.local")
FOUR_ROLE_COMPARATOR_ORDER = ("planner", "retriever", "executor", "summarizer")
FOUR_ROLE_ROLE_ALIASES = {
    "plan": "planner",
    "planner": "planner",
    "retrieve": "retriever",
    "retriever": "retriever",
    "execute": "executor",
    "executor": "executor",
    "summarize": "summarizer",
    "summarizer": "summarizer",
}


def normalize_comparator_role_name(role: str) -> str:
    normalized = str(role).strip().lower()
    if normalized not in FOUR_ROLE_ROLE_ALIASES:
        raise ValueError(f"unsupported comparator role: {role}")
    return FOUR_ROLE_ROLE_ALIASES[normalized]


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
    top_logprobs: list | None = None


@dataclass(frozen=True)
class ProviderConfig:
    kind: str = "openai_compatible"
    base_url: str | None = DEFAULT_LLM_BASE_URL
    api_key: str | None = None
    api_key_env: str | None = "STATEBUS_LLM_API_KEY"
    timeout_s: float = 60.0
    request_max_attempts: int = 3
    retry_initial_delay_s: float = 1.0
    retry_max_delay_s: float = 8.0
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
    max_context_tokens: int | None = None
    max_context_safety_margin_tokens: int = 64
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
            "retriever": RoleLLMConfig(),
            "executor": RoleLLMConfig(),
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
            request_max_attempts=max(1, int(os.getenv("STATEBUS_LLM_REQUEST_MAX_ATTEMPTS") or "3")),
            retry_initial_delay_s=max(
                0.0,
                float(os.getenv("STATEBUS_LLM_RETRY_INITIAL_DELAY_S") or "1"),
            ),
            retry_max_delay_s=max(
                0.0,
                float(os.getenv("STATEBUS_LLM_RETRY_MAX_DELAY_S") or "8"),
            ),
        )
        roles = {
            role: _role_from_env(default_model=default_model, role_name=role)
            for role in FOUR_ROLE_COMPARATOR_ORDER
        }
        return cls(
            mode=os.getenv("STATEBUS_LLM_MODE", "deterministic").strip().lower(),
            source="env",
            providers={"default": provider},
            roles=roles,
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
            role: _role_from_mapping(
                role_name=role,
                payload=dict(roles_payload.get(role) or {}),
            )
            for role in FOUR_ROLE_COMPARATOR_ORDER
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
        return self.mode in {"api", "local_vllm"}

    def provider_config(self, name: str) -> ProviderConfig:
        if name not in self.providers:
            raise KeyError(f"unknown llm provider {name}")
        return self.providers[name]

    def role_config(self, purpose: str) -> RoleLLMConfig:
        role_name = normalize_comparator_role_name(purpose)
        if role_name not in self.roles:
            raise KeyError(f"unknown llm role {purpose}")
        return self.roles[role_name]

    def with_mode(self, mode: str) -> "LLMConfig":
        return replace(self, mode=mode.strip().lower())

    def with_provider_override(self, provider_name: str, **kwargs: object) -> "LLMConfig":
        provider = self.provider_config(provider_name)
        updated = replace(provider, **kwargs)
        providers = dict(self.providers)
        providers[provider_name] = updated
        return replace(self, providers=providers)

    def with_role_override(self, role_name: str, **kwargs: object) -> "LLMConfig":
        normalized_role_name = normalize_comparator_role_name(role_name)
        role = self.role_config(normalized_role_name)
        updated = replace(role, **kwargs)
        roles = dict(self.roles)
        roles[normalized_role_name] = updated
        return replace(self, roles=roles)

    def require_api_ready(self) -> None:
        if not self.use_api:
            return
        for provider_name, provider in self.providers.items():
            if provider.kind != "openai_compatible":
                raise ValueError(f"unsupported llm provider kind: {provider.kind}")
            if not provider.base_url:
                raise ValueError(f"provider {provider_name} missing base_url")
            if self.mode != "local_vllm" and not provider.resolved_api_key:
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
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResult: ...

    def describe(self) -> dict[str, object]: ...


@dataclass(frozen=True)
class RoleDispatchLLMClient:
    """Dispatch role calls to independently configured LLM clients."""

    clients: dict[str, LLMClient]
    execution_modes: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized = {
            normalize_comparator_role_name(role): client
            for role, client in self.clients.items()
        }
        missing = [role for role in FOUR_ROLE_COMPARATOR_ORDER if role not in normalized]
        if missing:
            raise ValueError(f"missing role llm clients: {','.join(missing)}")
        object.__setattr__(self, "clients", normalized)
        object.__setattr__(
            self,
            "execution_modes",
            {
                normalize_comparator_role_name(role): str(mode).strip().lower()
                for role, mode in self.execution_modes.items()
            },
        )

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        purpose: str,
        temperature: float | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        role = normalize_comparator_role_name(purpose)
        return await self.clients[role].complete(
            messages,
            purpose=role,
            temperature=temperature,
            response_schema=response_schema,
        )

    def describe_role(self, role: str) -> dict[str, object]:
        normalized = normalize_comparator_role_name(role)
        description = dict(self.clients[normalized].describe())
        description["role"] = normalized
        description["execution_mode"] = self.execution_modes.get(
            normalized,
            str(description.get("mode", "")),
        )
        role_description = dict(description.get("roles", {})).get(normalized, {})
        if isinstance(role_description, dict):
            description["role_config"] = dict(role_description)
        return description

    def describe(self) -> dict[str, object]:
        return {
            "backend": "role_dispatch",
            "execution_modes": {
                role: self.execution_modes.get(role, "")
                for role in FOUR_ROLE_COMPARATOR_ORDER
            },
            "roles": {
                role: self.describe_role(role)
                for role in FOUR_ROLE_COMPARATOR_ORDER
            },
        }


class OpenAICompatibleLLMClient:
    def __init__(self, config: LLMConfig) -> None:
        config.require_api_ready()
        self.config = config

    def _build_provider_client(self, provider_name: str) -> AsyncOpenAI:
        provider = self.config.provider_config(provider_name)
        return AsyncOpenAI(
            api_key=provider.resolved_api_key or ("EMPTY" if self.config.mode == "local_vllm" else None),
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
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        role_config = self.config.role_config(purpose)
        provider_name = role_config.provider
        request = _build_openai_request(role_config, messages, temperature=temperature)
        # local_vllm: the bare {"type":"json_object"} grammar accepts ANY valid
        # JSON, and a JSON array "[...]" is valid JSON. That lets Qwen3 pick "["
        # as a legal first token and degenerate into "[\n\n[\n\n[..." on long
        # prompts (observed with local-embedding hydration). Swapping to a
        # json_schema makes "{" the sole legal root token, so the array branch
        # is removed from the grammar entirely. When the caller supplies a
        # closed-set response_schema (enum-only fields, no free-text sink), the
        # copy-attractor degeneration on unbounded string/array values is also
        # structurally impossible. Only applied for local_vllm; the DeepSeek API
        # path keeps json_object untouched.
        if (
            self.config.mode == "local_vllm"
            and isinstance(request.get("response_format"), dict)
            and request["response_format"].get("type") == "json_object"
        ):
            schema = response_schema or {"type": "object", "additionalProperties": True}
            request = {
                **request,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "role_object",
                        "strict": True,
                        "schema": schema,
                    },
                },
            }
        # local_vllm: Qwen3 defaults to enable_thinking=True and emits a
        # "<think>..." block before the answer. Under object-only JSON grammar the
        # first token must be "{", so the model cannot emit "<think>" and ends up
        # fighting the grammar (a contributor to token degeneration). These roles
        # are structured routing/classification tasks where thinking adds latency
        # without accuracy gain, so disable it to align generation with the
        # grammar. Merged into any role-configured extra_body; vLLM-only knob.
        if self.config.mode == "local_vllm":
            existing_extra_body = dict(request.get("extra_body") or {})
            chat_template_kwargs = dict(existing_extra_body.get("chat_template_kwargs") or {})
            chat_template_kwargs.setdefault("enable_thinking", False)
            existing_extra_body["chat_template_kwargs"] = chat_template_kwargs
            existing_extra_body.setdefault(
                "guided_decoding_backend",
                "xgrammar:disable-any-whitespace",
            )
            request = {**request, "extra_body": existing_extra_body}
        # local_vllm executor probes request token-level output distributions.
        if self.config.mode == "local_vllm" and purpose == "executor":
            request = {
                **request,
                "logprobs": True,
                "top_logprobs": 20,
            }
        response = await self._create_completion_with_retry(
            provider_name=provider_name,
            provider=self.config.provider_config(provider_name),
            request=request,
        )
        choice = response.choices[0]
        content = _coerce_content_to_text(choice.message.content)
        usage = getattr(response, "usage", None)
        raw_logprobs = getattr(getattr(choice, "logprobs", None), "content", None)
        return LLMResult(
            text=content.strip(),
            model=getattr(response, "model", None) or role_config.model,
            usage=LLMUsage(
                prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
            ),
            top_logprobs=raw_logprobs,
        )

    async def _create_completion_with_retry(
        self,
        *,
        provider_name: str,
        provider: ProviderConfig,
        request: dict[str, Any],
    ) -> Any:
        max_attempts = max(1, int(provider.request_max_attempts))
        delay_s = max(0.0, provider.retry_initial_delay_s)
        max_delay_s = max(0.0, provider.retry_max_delay_s)
        last_error: BaseException | None = None
        for attempt_index in range(max_attempts):
            client = self._build_provider_client(provider_name)
            try:
                return await client.chat.completions.create(**request)
            except BaseException as exc:
                context_adjusted_request = _context_window_adjusted_request(request, exc)
                if context_adjusted_request is not None:
                    try:
                        return await client.chat.completions.create(**context_adjusted_request)
                    except BaseException as retry_exc:
                        exc = retry_exc
                if not _is_transient_openai_error(exc) or attempt_index + 1 >= max_attempts:
                    raise
                last_error = exc
            finally:
                await client.close()
            if delay_s > 0.0:
                await asyncio.sleep(delay_s)
                if max_delay_s > 0.0:
                    delay_s = min(max_delay_s, delay_s * 2)
        raise RuntimeError("unreachable OpenAI retry loop exit") from last_error

    def describe(self) -> dict[str, object]:
        return {
            "backend": "openai_compatible",
            "mode": self.config.mode,
            "source": self.config.source,
            "planner_provider": self.config.role_config("planner").provider,
            "planner_model": self.config.role_config("planner").model,
            "summarizer_provider": self.config.role_config("summarizer").provider,
            "summarizer_model": self.config.role_config("summarizer").model,
            "roles": {
                role: {
                    "provider": self.config.role_config(role).provider,
                    "model": self.config.role_config(role).model,
                    "json_output": self.config.role_config(role).json_output,
                }
                for role in FOUR_ROLE_COMPARATOR_ORDER
            },
            "providers": {
                name: {
                    "kind": provider.kind,
                    "base_url": provider.base_url,
                    "request_max_attempts": provider.request_max_attempts,
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
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        del temperature
        response_properties = (
            response_schema.get("properties", {})
            if isinstance(response_schema, dict)
            else {}
        )
        semantic_task_plan_requested = (
            isinstance(response_properties, dict)
            and "semantic_task_plan" in response_properties
        )
        if not messages:
            raise ValueError("deterministic llm requires at least one message")
        user_content = messages[-1].content
        if purpose == "planner":
            if "Visible route/tool candidates:" in user_content and "Return JSON with route and tool_name" in user_content:
                payload = parse_text_route_tool_planner_prompt(user_content)
                selected = _deterministic_retriever_choice(
                    query=str(payload.get("query", "")),
                    tool_candidates=[
                        dict(item)
                        for item in payload.get("tool_candidates", [])
                        if isinstance(item, dict)
                    ],
                )
                selected_rank = next(
                    (
                        index
                        for index, item in enumerate(payload.get("tool_candidates", []), start=1)
                        if str(item.get("route", "")).strip() == str(selected.get("route", "")).strip()
                        and str(item.get("tool_name", "")).strip() == str(selected.get("tool_name", "")).strip()
                    ),
                    0,
                )
                result_payload = {
                    "route": str(selected.get("route", "")).strip(),
                    "tool_name": str(selected.get("tool_name", "")).strip(),
                    "strongest_competing_route": str(payload.get("fallback_route", "")).strip(),
                    "validation_check": "planner selected one visible route/tool candidate without typed-state fallback",
                    "candidate_rank": selected_rank,
                }
                return LLMResult(
                    text=json.dumps(result_payload, ensure_ascii=False, sort_keys=True),
                    model=self.config.role_config("planner").model,
                )
            if "Task request:\n" in user_content and "Allowed required outputs:\n" in user_content:
                payload = parse_semantic_planner_brief(user_content)
                plan = _build_semantic_task_plan(payload)
            elif "<sb-plan-v1>" in user_content:
                payload = parse_compact_protocol_planner_brief(user_content)
                plan = (
                    _build_semantic_task_plan(payload)
                    if semantic_task_plan_requested
                    else _build_compact_protocol_plan(payload)
                )
            else:
                payload = (
                    parse_tagged_json(user_content, "statebus-planner-input")
                    if "<statebus-planner-input>" in user_content
                    else parse_text_planner_brief(user_content)
                )
                if "evidence_text" not in payload:
                    payload["evidence_text"] = extract_optional_tagged_text(
                        user_content,
                        "statebus-planner-evidence",
                    )
                plan_steps = [
                    {
                        "step_id": "retrieve",
                        "semantic_role": "retrieve",
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
                ]
                if _requires_validation_step(payload):
                    plan_steps.append(
                        {
                            "step_id": "validate",
                            "semantic_role": "validate",
                            "owner_agent": "executor",
                            "action": "VALIDATE_ROUTE",
                            "input_state_refs": [],
                            "params": {},
                            "depends_on": ["retrieve"],
                        }
                    )
                plan_steps.extend(
                    [
                        {
                            "step_id": "execute",
                            "semantic_role": "execute",
                            "owner_agent": "executor",
                            "action": "EXECUTE_PLAYBOOK",
                            "input_state_refs": [],
                            "params": {},
                            "depends_on": ["retrieve", "validate"] if _requires_validation_step(payload) else ["retrieve"],
                        },
                        {
                            "step_id": "summarize",
                            "semantic_role": "summarize",
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
                )
                plan = {"steps": plan_steps}
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
            if "evidence_text" not in payload:
                payload["evidence_text"] = extract_optional_tagged_text(
                    user_content,
                    "statebus-summary-evidence",
                )
            if "actions_text" not in payload:
                payload["actions_text"] = extract_optional_tagged_text(
                    user_content,
                    "statebus-summary-actions",
                )
            reusable_steps = list(payload.get("reusable_steps") or ["retrieve", "execute"])
            if compact_protocol:
                action_lines = [line.strip() for line in str(payload["actions_text"]).splitlines() if line.strip()]
                action_summary = "; ".join(action_lines[:3]) if action_lines else "no action emitted"
                summary = f"{payload['summary_hint']} Actions: {action_summary}"
            else:
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
        if purpose == "retriever":
            payload = (
                parse_compact_protocol_retriever_handoff(user_content)
                if "<sb-retriever-v1>" in user_content
                else parse_text_retriever_handoff(user_content)
            )
            tool_candidates = [
                dict(item)
                for item in payload.get("tool_candidates", [])
                if isinstance(item, dict)
            ]
            selected = _deterministic_retriever_choice(
                query=str(payload.get("query", "")),
                tool_candidates=tool_candidates,
            ) if tool_candidates else {
                "route": "generic_triage",
                "tool_name": "tool.collect_more_evidence",
            }
            selected_rank = next(
                (
                    index
                    for index, item in enumerate(tool_candidates, start=1)
                    if str(item.get("route", "")).strip() == str(selected.get("route", "")).strip()
                    and str(item.get("tool_name", "")).strip() == str(selected.get("tool_name", "")).strip()
                ),
                0,
            )
            retrieved_doc_ids = [str(item) for item in payload.get("retrieved_doc_ids", []) if str(item).strip()]
            result_payload = {
                "route": str(selected.get("route", "generic_triage")).strip() or "generic_triage",
                "tool_name": str(selected.get("tool_name", "tool.collect_more_evidence")).strip() or "tool.collect_more_evidence",
                "supporting_doc_ids": retrieved_doc_ids[:3],
                "reason": "selected a visible candidate from bounded retriever context using query-aware deterministic tie-breaking",
                "candidate_rank": selected_rank,
            }
            return LLMResult(
                text=json.dumps(result_payload, ensure_ascii=False, sort_keys=True),
                model=self.config.role_config("retriever").model,
            )
        if purpose == "executor":
            payload = (
                parse_compact_protocol_executor_handoff(user_content)
                if "<sb-executor-v1>" in user_content
                else parse_text_executor_handoff(user_content)
            )
            validated_tool = str(payload.get("validated_tool_name", "")).strip()
            validated_route = str(payload.get("validated_route", "")).strip()
            tool_name = validated_tool or str(payload.get("tool_name", "tool.collect_more_evidence")).strip() or "tool.collect_more_evidence"
            route = validated_route or str(payload.get("route", "generic_triage")).strip() or "generic_triage"
            tool_candidates = [
                dict(item)
                for item in payload.get("tool_candidates", [])
                if isinstance(item, dict)
            ]
            if tool_candidates:
                selected = _deterministic_executor_choice(
                    route=route,
                    tool_name=tool_name,
                    tool_candidates=tool_candidates,
                )
                route = str(selected.get("route", route)).strip() or route
                tool_name = str(selected.get("tool_name", tool_name)).strip() or tool_name
            action_contract = (
                str(payload.get("validated_action_contract", "")).strip()
                or str(payload.get("action_contract", "")).strip()
                or "execute_validated_tool"
            )
            result_payload = {
                "route": route,
                "tool_name": tool_name,
                "action_contract": action_contract,
                "reason": "executor selected visible validated tool from bounded candidate view",
            }
            return LLMResult(
                text=json.dumps(result_payload, ensure_ascii=False, sort_keys=True),
                model=self.config.role_config("executor").model,
            )
        raise ValueError(f"unsupported deterministic llm purpose: {purpose}")

    def describe(self) -> dict[str, object]:
        return {
            "backend": "deterministic",
            "mode": self.config.mode,
            "source": self.config.source,
            "planner_provider": self.config.role_config("planner").provider,
            "planner_model": self.config.role_config("planner").model,
            "summarizer_provider": self.config.role_config("summarizer").provider,
            "summarizer_model": self.config.role_config("summarizer").model,
            "roles": {
                role: {
                    "provider": self.config.role_config(role).provider,
                    "model": self.config.role_config(role).model,
                    "json_output": self.config.role_config(role).json_output,
                }
                for role in FOUR_ROLE_COMPARATOR_ORDER
            },
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


def extract_optional_tagged_text(text: str, tag: str) -> str:
    start_token = f"<{tag}>"
    end_token = f"</{tag}>"
    start = text.find(start_token)
    end = text.find(end_token)
    if start == -1 or end == -1 or end < start:
        return ""
    return text[start + len(start_token) : end].strip()


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = _strip_code_fence(stripped)
    start = stripped.find("{")
    if start == -1:
        raise ValueError(f"expected json object in llm output: {text!r}")
    # Walk backwards from the last } until json.loads succeeds.
    # This handles LLM appending trailing commentary after the closing brace.
    end = len(stripped) - 1
    while end >= start:
        end = stripped.rfind("}", start, end + 1)
        if end == -1:
            break
        candidate = stripped[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            end -= 1
    raise ValueError(f"expected json object in llm output: {text!r}")


def parse_text_planner_brief(text: str) -> dict[str, Any]:
    required_roles_block = _extract_optional_block(
        text,
        "Required semantic roles:\n",
        "\n\nSummary hint:\n",
    )
    query_end_marker = (
        "\n\nRequired semantic roles:\n" if required_roles_block else "\n\nSummary hint:\n"
    )
    summary_start_marker = (
        "Summary hint:\n" if not required_roles_block else "\n\nSummary hint:\n"
    )
    has_evidence_note = "\n\nEvidence note:\n" in text
    summary_end_marker = (
        "\n\nEvidence note:\n" if has_evidence_note else "\n\nVisible route/tool candidates:"
    )
    return {
        "task_id": _extract_line_value(text, "Task ID:"),
        "task_group": _extract_line_value(text, "Task group:"),
        "task_theme": _extract_line_value(text, "Task theme:"),
        "goal": _extract_block(text, "Goal:\n", "\n\nSearch query:\n"),
        "query": _extract_block(text, "Search query:\n", query_end_marker),
        "summary_hint": _extract_block(
            text,
            summary_start_marker,
            summary_end_marker,
        ),
        "evidence_text": (_extract_after(text, "Evidence note:\n") if has_evidence_note else ""),
        "tags": _split_csv(_extract_line_value(text, "Tags:")),
        "required_plan_semantic_roles": _split_csv(required_roles_block),
    }


def parse_compact_protocol_planner_brief(text: str) -> dict[str, Any]:
    payload = parse_tagged_json(text, "sb-plan-v1")
    return {
        "goal": str(payload.get("g", "")),
        "query": str(payload.get("q", "")),
        "evidence_text": str(payload.get("e", "")),
        "summary_hint": str(payload.get("h", "")),
        "tags": [str(tag) for tag in payload.get("t", [])],
        "required_plan_semantic_roles": [str(role) for role in payload.get("rr", [])],
        "allowed_required_outputs": [str(item) for item in payload.get("ao", [])],
        "entities": [str(item) for item in payload.get("en", [])],
        "time_scope": str(payload.get("ts", "")),
    }


def parse_semantic_planner_brief(text: str) -> dict[str, Any]:
    def section(title: str, following_titles: tuple[str, ...]) -> str:
        marker = f"{title}:\n"
        start = text.find(marker)
        if start == -1:
            return ""
        start += len(marker)
        ends = [
            position
            for next_title in following_titles
            if (position := text.find(f"\n\n{next_title}:\n", start)) != -1
        ]
        end = min(ends) if ends else len(text)
        return text[start:end].strip()

    return {
        "goal": section(
            "Goal",
            ("Task request", "Summary hint", "Allowed required outputs", "Entity hints", "Time scope hint"),
        ),
        "query": section(
            "Task request",
            ("Summary hint", "Allowed required outputs", "Entity hints", "Time scope hint"),
        ),
        "summary_hint": section(
            "Summary hint",
            ("Allowed required outputs", "Entity hints", "Time scope hint"),
        ),
        "allowed_required_outputs": _split_csv(
            section("Allowed required outputs", ("Entity hints", "Time scope hint"))
        ),
        "entities": _split_csv(
            section("Entity hints", ("Time scope hint",))
        ),
        "time_scope": section("Time scope hint", ()),
        "evidence_text": "",
        "tags": [],
        "required_plan_semantic_roles": [],
    }


def _decode_compact_tool_candidates(items: list[Any]) -> list[dict[str, Any]]:
    tool_candidates: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        candidate: dict[str, Any] = {
            "route": str(raw.get("r", raw.get("route", ""))).strip(),
            "tool_name": str(raw.get("t", raw.get("tool_name", ""))).strip(),
        }
        if not candidate["route"] or not candidate["tool_name"]:
            continue
        if "d" in raw:
            candidate["supporting_doc_ids"] = [str(item) for item in raw.get("d", []) if str(item).strip()]
            candidate["support_doc_count"] = len(candidate["supporting_doc_ids"])
        elif "supporting_doc_ids" in raw:
            candidate["supporting_doc_ids"] = [str(item) for item in raw.get("supporting_doc_ids", []) if str(item).strip()]
            candidate["support_doc_count"] = len(candidate["supporting_doc_ids"])
        else:
            candidate["support_doc_count"] = int(raw.get("n", raw.get("support_doc_count", 0)) or 0)
        if "s" in raw:
            candidate["support_terms"] = [str(item) for item in raw.get("s", []) if str(item).strip()]
        elif "support_terms" in raw:
            candidate["support_terms"] = [str(item) for item in raw.get("support_terms", []) if str(item).strip()]
        if "m" in raw:
            candidate["matched_issue_ids"] = [str(item) for item in raw.get("m", []) if str(item).strip()]
        elif "matched_issue_ids" in raw:
            candidate["matched_issue_ids"] = [str(item) for item in raw.get("matched_issue_ids", []) if str(item).strip()]
        if "h" in raw or "helper_rank" in raw:
            candidate["helper_rank"] = int(raw.get("h", raw.get("helper_rank", 0)) or 0)
        if "sc" in raw or "score" in raw:
            candidate["score"] = float(raw.get("sc", raw.get("score", 0.0)) or 0.0)
        if "x" in raw:
            candidate["rationale"] = str(raw.get("x", "")).strip()
        elif "rationale" in raw:
            candidate["rationale"] = str(raw.get("rationale", "")).strip()
        tool_candidates.append(candidate)
    return tool_candidates


def _requires_validation_step(payload: dict[str, Any]) -> bool:
    required_roles = {
        str(role).strip().lower()
        for role in payload.get("required_plan_semantic_roles", [])
        if str(role).strip()
    }
    if "validate" in required_roles:
        return True
    joined = " ".join(
        [
            str(payload.get("goal", "")),
            str(payload.get("query", "")),
            str(payload.get("summary_hint", "")),
            str(payload.get("evidence_text", "")),
            " ".join(str(tag) for tag in payload.get("tags", [])),
        ]
    ).lower()
    return "validate route" in joined or "four-step" in joined or "4-step" in joined


def _build_compact_protocol_plan(payload: dict[str, Any]) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "r": {
            "sid": "retrieve",
            "role": "retrieve",
            "owner": "retriever",
            "action": "RETRIEVE_EVIDENCE",
            "dep": [],
            "q": payload["query"],
            "e": payload["evidence_text"],
            "t": payload.get("tags", []),
        },
        "x": {
            "sid": "execute",
            "role": "execute",
            "owner": "executor",
            "action": "EXECUTE_PLAYBOOK",
            "dep": ["retrieve"],
        },
        "s": {
            "sid": "summarize",
            "role": "summarize",
            "owner": "summarizer",
            "action": "SUMMARIZE_AND_COMMIT",
            "dep": ["retrieve", "execute"],
            "h": payload["summary_hint"],
            "t": payload.get("tags", []),
        },
    }
    if _requires_validation_step(payload):
        plan["x"].update(
            {
                "dep": ["retrieve", "validate"],
                "vsid": "validate",
                "vrole": "validate",
                "vowner": "executor",
                "vaction": "VALIDATE_ROUTE",
                "vdep": ["retrieve"],
            }
        )
    return plan


def _build_semantic_task_plan(payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query", "")).strip()
    goal = str(payload.get("goal", "")).strip() or query
    entities = [str(item).strip() for item in payload.get("entities", []) if str(item).strip()]
    time_scope = str(payload.get("time_scope", "")).strip()
    lexical_query = " ".join(part for part in (" ".join(entities), time_scope) if part).strip() or query
    table_query = " ".join(part for part in (query, "table cells schema") if part).strip()
    return {
        "semantic_task_plan": {
            "task_semantics": {
                "goal": goal,
                "entities": entities,
                "time_scope": time_scope,
            },
            "retrieval_objectives": {
                "lexical_metadata": {
                    "query_text": lexical_query,
                    "objective": "locate the relevant corpus metadata and document scope",
                    "evidence_types": ["lexical_metadata"],
                },
                "semantic_chunk": {
                    "query_text": query,
                    "objective": "retrieve explanatory context and citations for the request",
                    "evidence_types": ["semantic_context", "citation"],
                },
                "table_structure": {
                    "query_text": table_query,
                    "objective": "retrieve table cells and schema needed for the computation",
                    "evidence_types": ["table_cell", "table_schema"],
                },
                "memory": {
                    "query_text": query,
                    "objective": "find compatible prior artifacts or strategies without bypassing validation",
                    "evidence_types": ["memory_artifact", "memory_strategy"],
                    "reuse_intent": "assist",
                },
            },
            "required_evidence": ["table_cell", "semantic_context", "citation"],
            "required_outputs": [
                str(item).strip()
                for item in payload.get("allowed_required_outputs", [])
                if str(item).strip()
            ],
        }
    }


def _extract_optional_block(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    if start == -1:
        return ""
    start += len(start_marker)
    end = text.find(end_marker, start)
    if end == -1:
        return ""
    return text[start:end].strip()


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


def parse_compact_protocol_retriever_handoff(text: str) -> dict[str, Any]:
    payload = parse_tagged_json(text, "sb-retriever-v1")
    return {
        "query": str(payload.get("q", payload.get("query", ""))).strip(),
        "evidence_text": str(payload.get("e", payload.get("evidence_text", ""))).strip(),
        "retrieved_doc_ids": [
            str(item)
            for item in payload.get("rd", payload.get("retrieved_doc_ids", []))
            if str(item).strip()
        ],
        "tool_candidates": _decode_compact_tool_candidates(
            list(payload.get("tc", payload.get("tool_candidates", [])))
        ),
    }


def parse_text_retriever_handoff(text: str) -> dict[str, Any]:
    visible_candidates = _extract_line_value(text, "Visible candidates:")
    tool_candidates = _parse_text_candidates_line(visible_candidates)
    candidate_notes = _extract_optional_line_value(text, "Candidate notes:")
    note_candidates = _parse_text_candidate_notes(candidate_notes)
    if note_candidates:
        note_by_identity = {
            _candidate_identity(item): item
            for item in note_candidates
        }
        merged_candidates: list[dict[str, Any]] = []
        for item in tool_candidates:
            merged = dict(item)
            merged.update(note_by_identity.get(_candidate_identity(item), {}))
            merged_candidates.append(merged)
        tool_candidates = merged_candidates
    return {
        "query": _extract_line_value(text, "Query:"),
        "retrieved_doc_ids": _split_csv(_extract_line_value(text, "Retrieved docs:")),
        "tool_candidates": tool_candidates,
    }


def parse_text_route_tool_planner_prompt(text: str) -> dict[str, Any]:
    visible_candidates = _extract_line_value(text, "Visible route/tool candidates:")
    tool_candidates = _parse_text_candidates_line(visible_candidates)
    candidate_notes = _extract_optional_line_value(text, "Candidate notes:")
    note_candidates = _parse_text_candidate_notes(candidate_notes)
    if note_candidates:
        note_by_identity = {_candidate_identity(item): item for item in note_candidates}
        merged_candidates: list[dict[str, Any]] = []
        for item in tool_candidates:
            merged = dict(item)
            merged.update(note_by_identity.get(_candidate_identity(item), {}))
            merged_candidates.append(merged)
        tool_candidates = merged_candidates
    return {
        "task_id": _extract_line_value(text, "Task ID:"),
        "query": _extract_block(text, "Task query:\n", "\n\nVisible route/tool candidates:"),
        "tool_candidates": tool_candidates,
        "fallback_route": _extract_optional_line_value(text, "Competing route:"),
    }


def parse_text_executor_handoff(text: str) -> dict[str, Any]:
    visible_candidates = _extract_optional_line_value(text, "Visible candidates:")
    tool_candidates = _parse_text_candidates_line(visible_candidates)
    candidate_notes = _extract_optional_line_value(text, "Candidate notes:")
    note_candidates = _parse_text_candidate_notes(candidate_notes)
    if note_candidates:
        note_by_identity = {
            _candidate_identity(item): item
            for item in note_candidates
        }
        merged_candidates: list[dict[str, Any]] = []
        for item in tool_candidates:
            merged = dict(item)
            merged.update(note_by_identity.get(_candidate_identity(item), {}))
            merged_candidates.append(merged)
        tool_candidates = merged_candidates
    return {
        "route": _extract_line_value(text, "Route:"),
        "tool_name": _extract_line_value(text, "Tool:"),
        "validated_route": _extract_line_value(text, "Validated route:"),
        "validated_tool_name": _extract_line_value(text, "Validated tool:"),
        "validated_action_contract": _extract_line_value(text, "Validated action contract:"),
        "tool_candidates": tool_candidates,
    }


def parse_compact_protocol_executor_handoff(text: str) -> dict[str, Any]:
    payload = parse_tagged_json(text, "sb-executor-v1")
    return {
        "route": str(payload.get("r", payload.get("route", ""))).strip(),
        "tool_name": str(payload.get("t", payload.get("tool_name", ""))).strip(),
        "validated_route": str(
            payload.get("vr", payload.get("validated_route", ""))
        ).strip(),
        "validated_tool_name": str(
            payload.get("vt", payload.get("validated_tool_name", ""))
        ).strip(),
        "validated_action_contract": str(
            payload.get("va", payload.get("validated_action_contract", ""))
        ).strip(),
        "action_contract": str(payload.get("a", payload.get("action_contract", ""))).strip(),
        "evidence_text": str(payload.get("e", payload.get("evidence_text", ""))).strip(),
        "tool_candidates": _decode_compact_tool_candidates(
            list(payload.get("tc", payload.get("tool_candidates", [])))
        ),
    }


def _parse_text_candidates_line(value: str) -> list[dict[str, Any]]:
    tool_candidates: list[dict[str, Any]] = []
    for token in value.split(";"):
        item = str(token).strip()
        if not item or "::" not in item:
            continue
        route, tool_name = item.split("::", 1)
        route = route.strip()
        tool_name = tool_name.strip()
        if route and tool_name:
            tool_candidates.append({"route": route, "tool_name": tool_name})
    return tool_candidates


def _parse_text_candidate_notes(value: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for token in value.split(";"):
        item = str(token).strip()
        if not item or "::" not in item:
            continue
        head, *segments = item.split("|")
        if "::" not in head:
            continue
        route, tool_name = head.split("::", 1)
        payload: dict[str, Any] = {
            "route": route.strip(),
            "tool_name": tool_name.strip(),
        }
        for segment in segments:
            key, _, raw_value = segment.partition("=")
            key = key.strip()
            raw_value = raw_value.strip()
            if key == "helper_rank":
                payload[key] = int(raw_value or 0)
            elif key == "score":
                payload[key] = int(raw_value or 0)
            elif key == "support_doc_count":
                payload[key] = int(raw_value or 0)
            elif key == "support_terms":
                payload["support_terms"] = [item for item in raw_value.split(",") if item]
            elif key == "matched_issue_ids":
                payload["matched_issue_ids"] = [item for item in raw_value.split(",") if item]
            elif key == "support_docs":
                payload["supporting_doc_ids"] = [item for item in raw_value.split(",") if item]
        candidates.append(payload)
    return candidates


def _deterministic_retriever_choice(*, query: str, tool_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not tool_candidates:
        return {"route": "generic_triage", "tool_name": "tool.collect_more_evidence"}
    first_identity = _candidate_identity(tool_candidates[0])
    if first_identity == ("generic_triage", "tool.collect_more_evidence"):
        return tool_candidates[0]
    scored = [
        (index, item)
        for index, item in enumerate(tool_candidates)
        if item.get("score") is not None
    ]
    if scored:
        scored.sort(
            key=lambda pair: (
                -int(pair[1].get("score", 0) or 0),
                int(pair[1].get("helper_rank", 0) or 0) if int(pair[1].get("helper_rank", 0) or 0) > 0 else 10**9,
                pair[0],
            )
        )
        return scored[0][1]
    query_tokens = set(query.lower().replace("::", " ").replace(".", " ").replace("_", " ").split())
    affinity_ranked = [
        (index, item, _candidate_query_affinity(query_tokens, item))
        for index, item in enumerate(tool_candidates)
    ]
    affinity_ranked = [item for item in affinity_ranked if item[2] > 0]
    if affinity_ranked:
        affinity_ranked.sort(
            key=lambda pair: (
                -pair[2],
                int(pair[1].get("helper_rank", 0) or 0) if int(pair[1].get("helper_rank", 0) or 0) > 0 else 10**9,
                pair[0],
            )
        )
        return affinity_ranked[0][1]
    ranked = [
        (index, item)
        for index, item in enumerate(tool_candidates)
        if int(item.get("helper_rank", 0) or 0) > 0
    ]
    if ranked:
        ranked.sort(
            key=lambda pair: (
                int(pair[1].get("helper_rank", 0) or 0),
                pair[0],
            )
        )
        return ranked[0][1]
    # The bounded retriever prompt already carries an ordered visible-candidate view.
    # Deterministic mode should preserve that ordering instead of re-ranking by query terms.
    return tool_candidates[0]


def _deterministic_executor_choice(
    *,
    route: str,
    tool_name: str,
    tool_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    proposed_identity = (route.strip(), tool_name.strip())
    for item in tool_candidates:
        if _candidate_identity(item) == proposed_identity:
            return item
    return tool_candidates[0]


_ROUTE_AFFINITY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "by",
        "for",
        "in",
        "of",
        "or",
        "the",
        "to",
        "using",
        "with",
    }
)


def _candidate_query_affinity(query_tokens: set[str], item: dict[str, Any]) -> int:
    support_terms = [str(term) for term in item.get("support_terms", []) if str(term).strip()]
    if not support_terms:
        support_terms = list(_candidate_catalog_issue_terms(item))
    surface = " ".join(
        [
            str(item.get("route", "")),
            str(item.get("tool_name", "")),
            " ".join(str(issue_id) for issue_id in item.get("matched_issue_ids", []) if str(issue_id).strip()),
            " ".join(support_terms),
            " ".join(str(doc_id) for doc_id in item.get("supporting_doc_ids", []) if str(doc_id).strip()),
        ]
    ).lower()
    candidate_tokens = set(surface.replace("::", " ").replace(".", " ").replace("_", " ").split())
    return len((query_tokens - _ROUTE_AFFINITY_STOPWORDS) & (candidate_tokens - _ROUTE_AFFINITY_STOPWORDS))


def _candidate_identity(item: dict[str, Any]) -> tuple[str, str]:
    return (str(item.get("route", "")).strip(), str(item.get("tool_name", "")).strip())


def _candidate_catalog_issue_terms(item: dict[str, Any]) -> tuple[str, ...]:
    route = str(item.get("route", "")).strip()
    tool_name = str(item.get("tool_name", "")).strip()
    if not route or not tool_name:
        return ()
    try:
        from v2.route_tool_catalog import stable_tool_registry_profiles
    except Exception:
        return ()
    for profile in stable_tool_registry_profiles():
        if profile.route == route and profile.tool_name == tool_name:
            return tuple(str(term).strip() for term in profile.issue_terms if str(term).strip())
    return ()


def _provider_from_mapping(name: str, payload: dict[str, Any]) -> ProviderConfig:
    del name
    return ProviderConfig(
        kind=str(payload.get("kind", "openai_compatible")),
        base_url=payload.get("base_url", DEFAULT_LLM_BASE_URL),
        api_key=payload.get("api_key"),
        api_key_env=payload.get("api_key_env", "STATEBUS_LLM_API_KEY"),
        timeout_s=float(payload.get("timeout_s", 60.0)),
        request_max_attempts=max(1, int(payload.get("request_max_attempts") or 3)),
        retry_initial_delay_s=max(0.0, float(payload.get("retry_initial_delay_s") or 1.0)),
        retry_max_delay_s=max(0.0, float(payload.get("retry_max_delay_s") or 8.0)),
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
        max_context_tokens=_coerce_optional_int(payload.get("max_context_tokens")),
        max_context_safety_margin_tokens=int(
            payload.get("max_context_safety_margin_tokens", 64)
        ),
        reasoning_effort=_coerce_optional_str(payload.get("reasoning_effort")),
        extra_body=dict(payload.get("extra_body") or {}),
        request_kwargs=dict(payload.get("request_kwargs") or {}),
    )


def _role_from_env(*, default_model: str, role_name: str) -> RoleLLMConfig:
    env_prefix = f"STATEBUS_LLM_{normalize_comparator_role_name(role_name).upper()}"
    return RoleLLMConfig(
        provider=os.getenv(f"{env_prefix}_PROVIDER", "default"),
        model=os.getenv(f"{env_prefix}_MODEL") or default_model,
        json_output=_env_bool(f"{env_prefix}_JSON_MODE", True),
        temperature=_env_optional_float(f"{env_prefix}_TEMPERATURE", 0.0),
        max_tokens=_env_optional_int(f"{env_prefix}_MAX_TOKENS"),
        max_context_tokens=_env_optional_int(f"{env_prefix}_MAX_CONTEXT_TOKENS"),
        max_context_safety_margin_tokens=int(
            os.getenv(f"{env_prefix}_MAX_CONTEXT_SAFETY_MARGIN_TOKENS", "64")
        ),
        reasoning_effort=os.getenv(f"{env_prefix}_REASONING_EFFORT"),
        extra_body=_env_json(f"{env_prefix}_EXTRA_BODY"),
        request_kwargs=_env_json(f"{env_prefix}_REQUEST_KWARGS"),
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
        request["max_tokens"] = _cap_max_tokens_for_context(role_config, messages)
    if role_config.json_output:
        request["response_format"] = {"type": "json_object"}
    if role_config.reasoning_effort is not None:
        request["reasoning_effort"] = role_config.reasoning_effort
    if role_config.extra_body:
        request["extra_body"] = role_config.extra_body
    if role_config.request_kwargs:
        request.update(role_config.request_kwargs)
    return request


def _cap_max_tokens_for_context(
    role_config: RoleLLMConfig,
    messages: list[ChatMessage],
) -> int:
    max_tokens = int(role_config.max_tokens or 0)
    if role_config.max_context_tokens is None:
        return max_tokens
    available_tokens = (
        int(role_config.max_context_tokens)
        - _estimate_chat_prompt_tokens(messages)
        - max(0, int(role_config.max_context_safety_margin_tokens))
    )
    return max(1, min(max_tokens, available_tokens))


def _estimate_chat_prompt_tokens(messages: list[ChatMessage]) -> int:
    total = 3
    for item in messages:
        content = str(item.content or "")
        byte_len = len(content.encode("utf-8"))
        total += 4
        total += max(len(content.split()), (byte_len + 2) // 3)
    return max(1, total)


_CONTEXT_WINDOW_ERROR_RE = re.compile(
    r"maximum context length is (?P<context>\d+) tokens.*?"
    r"\((?P<prompt>\d+) in the messages,\s*(?P<completion>\d+) in the completion\)",
    re.IGNORECASE | re.DOTALL,
)


def _context_window_adjusted_request(
    request: dict[str, Any],
    exc: BaseException,
) -> dict[str, Any] | None:
    if not isinstance(exc, APIStatusError):
        return None
    if int(getattr(exc, "status_code", 0) or 0) != 400:
        return None
    message = str(exc)
    if "maximum context length" not in message:
        return None
    match = _CONTEXT_WINDOW_ERROR_RE.search(message)
    if not match:
        return None
    context_tokens = int(match.group("context"))
    prompt_tokens = int(match.group("prompt"))
    completion_tokens = int(match.group("completion"))
    current_max_tokens = int(request.get("max_tokens") or completion_tokens)
    adjusted_max_tokens = max(1, context_tokens - prompt_tokens - 16)
    if adjusted_max_tokens >= current_max_tokens:
        return None
    adjusted_request = dict(request)
    adjusted_request["max_tokens"] = adjusted_max_tokens
    return adjusted_request


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


def _is_transient_openai_error(exc: BaseException) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        return int(getattr(exc, "status_code", 0) or 0) in {408, 409, 429, 500, 502, 503, 504}
    return False


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


def _coerce_bool(value: object, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"cannot coerce to bool: {value!r}")


def _extract_line_value(text: str, label: str) -> str:
    marker = text.find(label)
    if marker == -1:
        raise ValueError(f"missing line label {label!r}")
    line = text[marker + len(label) :].splitlines()[0]
    return line.strip()


def _extract_optional_line_value(text: str, label: str) -> str:
    marker = text.find(label)
    if marker == -1:
        return ""
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
