"""Contest-local model-assist routing for the DSL runner.

This module deliberately sits at the provider boundary.  It does not alter
Runtime grants, retry budgets, DSL validation, Memory admission, or CodeAct
planning.  The default ``off`` path never constructs any of the sideband
objects below.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from statebus.benchmark.request_journal import JournalClient, append_event
from statebus.integrations.llm import ChatMessage, LLMClient, LLMResult, normalize_comparator_role_name
from statebus.integrations.vllm_kv.role_client import (
    EngineLocalKVRoleClient,
    EngineLocalKVRoleClientConfig,
    KVPreflightError,
)
from statebus.runtime.model_assist import (
    MODEL_ASSIST_PROFILES,
    ModelAssistConfig,
    ModelAssistRoute,
    finish_apc_metrics_window,
    make_apc_observation,
    make_logit_observation,
    make_observation,
    route_for_profile,
    sample_apc_metrics,
    shared_prefix_identity,
)
from statebus.runtime.prefix_identity import SHARED_PREFIX_LAYOUT_VERSION, shared_prefix_envelope


@dataclass(frozen=True)
class ContestModelAssistSettings:
    profile: str
    task_id: str
    run_id: str
    root: Path
    model: str
    base_url: str
    max_context: int
    provider_timeout_s: float
    shared_prefix_text: str = ""
    parent_tokens: int = 0
    ttl_s: int = 300
    seed: int = 7
    kv_base_url: str = ""
    kv_timeout_s: float = 180.0
    tokenizer_timeout_s: float = 60.0
    apc_enabled: bool = False
    apc_service_ready: bool = False
    apc_metrics_url: str = ""
    apc_metrics_exclusive: bool = False

    @classmethod
    def from_enabled_inputs(
        cls,
        *,
        profile: str,
        task_id: str,
        run_id: str,
        root: Path,
        model: str,
        base_url: str,
        max_context: int,
        provider_timeout_s: float,
        shared_prefix_text: str,
    ) -> "ContestModelAssistSettings":
        profile = str(profile).strip().lower()
        if profile not in MODEL_ASSIST_PROFILES or profile == "off":
            raise ValueError(f"unsupported enabled model assist profile: {profile}")

        def positive_float(name: str, default: float) -> float:
            value = float(os.getenv(name, str(default)))
            if value <= 0:
                raise ValueError(f"{name}_must_be_positive")
            return value

        def non_negative_int(name: str, default: int) -> int:
            value = int(os.getenv(name, str(default)))
            if value < 0:
                raise ValueError(f"{name}_must_be_non_negative")
            return value

        def flag(name: str) -> bool:
            return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}

        kv_base_url = os.getenv("STATEBUS_KV_API_BASE_URL", "").strip()
        if not kv_base_url:
            parsed = urlsplit(base_url)
            kv_base_url = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        return cls(
            profile=profile,
            task_id=str(task_id),
            run_id=str(run_id),
            root=Path(root),
            model=str(model),
            base_url=str(base_url),
            max_context=int(max_context),
            provider_timeout_s=float(provider_timeout_s),
            shared_prefix_text=str(shared_prefix_text),
            parent_tokens=non_negative_int("STATEBUS_ENGINE_LOCAL_KV_PARENT_TOKENS", 0),
            ttl_s=max(1, int(os.getenv("STATEBUS_ENGINE_LOCAL_KV_TTL_S", "300"))),
            seed=non_negative_int("STATEBUS_ENGINE_LOCAL_KV_SEED", 7),
            kv_base_url=kv_base_url,
            kv_timeout_s=positive_float("STATEBUS_KV_API_TIMEOUT_S", 180.0),
            tokenizer_timeout_s=positive_float(
                "STATEBUS_KV_TOKENIZER_TIMEOUT_S", min(60.0, float(provider_timeout_s))
            ),
            apc_enabled=flag("STATEBUS_APC_ENABLED"),
            apc_service_ready=flag("STATEBUS_APC_SERVICE_READY"),
            apc_metrics_url=os.getenv("STATEBUS_APC_METRICS_URL", "").strip(),
            apc_metrics_exclusive=flag("STATEBUS_APC_METRICS_EXCLUSIVE"),
        )

    @property
    def model_assist_path(self) -> Path:
        return self.root / "model-assist.jsonl"

    @property
    def kv_mode(self) -> str | None:
        return {
            "kv_replay": "full_replay",
            "kv_continuation": "continuation",
            "kv_logit": "continuation",
            "auto": "auto",
        }.get(self.profile)

    @property
    def kv_logprobs(self) -> bool:
        return self.profile == "kv_logit"

    def model_assist_config(self) -> ModelAssistConfig:
        return ModelAssistConfig(
            profile=self.profile,
            model=self.model,
            parent_tokens=self.parent_tokens,
            ttl_s=self.ttl_s,
            seed=self.seed,
            apc_enabled=self.apc_enabled,
            apc_service_ready=self.apc_service_ready,
            apc_metrics_url=self.apc_metrics_url,
            apc_metrics_exclusive=self.apc_metrics_exclusive,
        )


def render_public_context(contract_view: Mapping[str, Any], *, task_id: str) -> str:
    """Render only public task semantics shared by Executor and Summarizer."""

    payload = {
        "context_version": "contest.dsl.model_assist_public.v1",
        "task_id": str(task_id),
        "task_family": str(contract_view.get("family", contract_view.get("task_family", ""))),
        "intent_op": str(contract_view.get("method", contract_view.get("intent_op", ""))),
        "output_contract_version": str(contract_view.get("output_contract_version", "")),
        "required_outputs": list(contract_view.get("output_schema", contract_view.get("required_outputs", {})) or {}),
        "visibility": "public task semantics only; no gold rows, raw tables, or unverified evidence",
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ContestModelAssistClient:
    """Provider-boundary client with a one-producer/one-consumer KV scope."""

    def __init__(
        self,
        ordinary: JournalClient,
        settings: ContestModelAssistSettings,
        *,
        kv_client: EngineLocalKVRoleClient | None = None,
        kv_journal: JournalClient | None = None,
    ) -> None:
        self.ordinary = ordinary
        self.settings = settings
        self.kv_client = kv_client
        self.kv_journal = kv_journal
        self._consumer_open = True
        self._call_index = 0
        self._last_route = ModelAssistRoute("ordinary", "profile_enabled_ordinary", True, settings.profile)
        self._apc_before = (
            sample_apc_metrics(
                settings.model_assist_config(),
                raw_snapshot_path=settings.root / "apc-metrics-before.prom",
            )
            if settings.profile in {"apc", "auto"}
            and settings.apc_enabled
            and settings.apc_service_ready
            else None
        )
        self._apc_request_count = 0
        self._apc_retry_count = 0
        self._generation_success_count = 0
        self._generation_error_count = 0

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        purpose: str,
        temperature: float | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        role = normalize_comparator_role_name(purpose)
        selected = self.ordinary
        kv_ready = self.kv_client is not None
        if self.settings.profile == "auto" and self.settings.shared_prefix_text.strip():
            probe = getattr(self.kv_client, "preflight_ready", None)
            kv_ready = bool(probe()) if callable(probe) else False
        route = route_for_profile(
            self.settings.model_assist_config(),
            role=role,
            shared_prefix_eligible=bool(self.settings.shared_prefix_text.strip()),
            kv_ready=kv_ready,
            apc_ready=self.settings.apc_enabled and self.settings.apc_service_ready,
            has_compatible_handle=bool(self.kv_client and self.kv_client.producer_ready),
        )
        if (
            self.settings.profile in {"kv_replay", "kv_continuation", "kv_logit"}
            and role in {"executor", "summarizer"}
            and self.kv_client is None
        ):
            raise KVPreflightError("explicit KV profile has no KV client")
        if self.kv_client is not None and self.kv_journal is not None and role in {"executor", "summarizer"}:
            explicit_kv = self.settings.profile in {"kv_replay", "kv_continuation", "kv_logit"}
            physical_kv_route = route.effective_mode in {"full_replay", "kv_continuation"}
            mechanism_failure = route.effective_mode == "mechanism_failure"
            if not self._consumer_open:
                route = ModelAssistRoute("ordinary", "outside_first_consumer_pair", True, self.settings.profile)
            elif role == "executor" and (physical_kv_route or (explicit_kv and mechanism_failure)):
                selected = self.kv_journal
            elif (
                role == "summarizer"
                and self.kv_client.producer_ready
                and (physical_kv_route or (explicit_kv and mechanism_failure))
            ):
                selected = self.kv_journal
            elif role == "summarizer" and route.effective_mode == "ordinary":
                route = ModelAssistRoute("ordinary", "no_producer_not_applicable", False, self.settings.profile)
        elif self.settings.profile == "logit":
            route = ModelAssistRoute("ordinary", "logit_observation_only", True, "ordinary")
        elif self.settings.profile == "apc":
            route = ModelAssistRoute(
                "apc_full_prompt"
                if self.settings.apc_enabled and self.settings.apc_service_ready
                else "ordinary",
                "apc_service_with_shared_prefix"
                if self.settings.apc_enabled and self.settings.apc_service_ready
                else "apc_service_unavailable",
                True,
                "apc_full_prompt",
            )

        request_messages = self._decorate_messages(messages, role, route)
        self._call_index += 1
        self._last_route = route
        if route.effective_mode == "apc_full_prompt":
            self._apc_request_count += 1
        try:
            try:
                result = await selected.complete(
                    request_messages,
                    purpose=role,
                    temperature=temperature,
                    response_schema=response_schema,
                )
            except BaseException:
                self._generation_error_count += 1
                raise
            self._generation_success_count += 1
        finally:
            if selected is self.kv_journal and role == "summarizer":
                self._consumer_open = False
                self.disable_pair()
        return result

    def disable_pair(self) -> None:
        """Stop private KV use and release any task-local producer handle."""

        self._consumer_open = False
        if self.kv_client is not None:
            self.kv_client.disable_pair()

    def observe_result(self, result: LLMResult, *, context: Mapping[str, Any]) -> None:
        if self.settings.profile == "off":
            return
        config = self.settings.model_assist_config()
        kv_observation = None
        if self.kv_client is not None:
            kv_observation = self.kv_client.take_model_assist_observation()
        route = self._last_route
        if isinstance(kv_observation, Mapping) and "effective_mode" in kv_observation:
            route = ModelAssistRoute(
                str(kv_observation.get("effective_mode", route.effective_mode)),
                str(kv_observation.get("route_reason", route.route_reason)),
                bool(kv_observation.get("preflight_checked", route.preflight_checked)),
                str(kv_observation.get("requested_mode", route.requested_mode)),
            )
        if (
            self.settings.profile == "auto"
            and isinstance(kv_observation, Mapping)
            and str(kv_observation.get("effective_mode", "")) == "ordinary"
        ):
            route = ModelAssistRoute(
                "ordinary",
                str(kv_observation.get("route_reason", "auto_ordinary_fallback")),
                True,
                self.settings.profile,
            )
        kv_details = (
            kv_observation.get("observations", {}).get("kv")
            if isinstance(kv_observation, Mapping)
            and isinstance(kv_observation.get("observations"), Mapping)
            and isinstance(kv_observation.get("observations", {}).get("kv"), Mapping)
            else kv_observation
        )
        prefix_identity = None
        if self.settings.shared_prefix_text and self.settings.profile != "logit":
            kv_token_verified = bool(
                isinstance(kv_details, Mapping)
                and str(kv_details.get("status", "")) == "available"
                and route.effective_mode in {"full_replay", "kv_continuation"}
            )
            prefix_identity = shared_prefix_identity(
                self.settings.shared_prefix_text,
                layout={
                    # APC/ordinary only have a textual layout identity.  KV
                    # sets this flag only after the private tokenizer (and,
                    # for consumers, the shared-prefix check) has succeeded.
                    "shared_prefix_enabled": True,
                    "token_verified": kv_token_verified,
                    "prefix_layout_version": SHARED_PREFIX_LAYOUT_VERSION,
                },
            )
        observation = make_observation(
            config,
            step=str(context.get("step", "")),
            attempt=str(context.get("attempt", "")),
            route=route,
            kv=(kv_details or {"status": "unavailable", "reason": route.route_reason}),
            logit=make_logit_observation(
                result.top_logprobs
                if self.settings.profile in {"logit", "kv_logit"}
                else None
            ),
            prefix_identity=prefix_identity,
        )
        if self.settings.profile in {"apc", "auto"}:
            observation["observations"]["apc"] = make_apc_observation(
                service_enabled=config.apc_enabled,
                service_ready_attested=config.apc_service_ready,
                delta=None,
                prefix_identity=(prefix_identity or {}).get("text_sha256", ""),
                requested=self.settings.profile in {"apc", "auto"},
            )
            observation["observations"]["apc"]["reason"] = "task_window_pending"
        observation.update(
            {
                "task_id": self.settings.task_id,
                "run_id": self.settings.run_id,
                "call_index": self._call_index,
                "role": str(context.get("role", "")),
                "stage": str(context.get("stage", "")),
                "repair_stage": str(context.get("repair_stage", "")),
                "batch_index": context.get("batch_index"),
                "model": self.settings.model,
                "endpoint": self.settings.base_url,
                "finish_reason": result.finish_reason,
                "request_max_attempts": 1,
                "prefix_layout_version": (
                    SHARED_PREFIX_LAYOUT_VERSION if prefix_identity is not None else None
                ),
            }
        )
        append_event(self.settings.model_assist_path, observation)

    def observe_error(self, exc: BaseException, *, context: Mapping[str, Any]) -> None:
        if self.settings.profile == "off":
            return
        append_event(
            self.settings.model_assist_path,
            {
                "event": "model_assist_error",
                "task_id": self.settings.task_id,
                "run_id": self.settings.run_id,
                "call_index": self._call_index,
                "role": str(context.get("role", "")),
                "stage": str(context.get("stage", "")),
                "repair_stage": str(context.get("repair_stage", "")),
                "batch_index": context.get("batch_index"),
                "requested_mode": self.settings.profile,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )

    def finalize(self) -> None:
        """Close the APC observation window after all task requests settle."""

        if self.settings.profile not in {"apc", "auto"}:
            return
        config = self.settings.model_assist_config()
        observation_started_ns = time.monotonic_ns()
        after = sample_apc_metrics(
            config,
            raw_snapshot_path=self.settings.root / "apc-metrics-after.prom",
        )
        if self._apc_before is not None and self._generation_error_count == 0:
            while time.monotonic_ns() - observation_started_ns < 30_000_000_000:
                query_delta = (
                    after.queries_total - self._apc_before.queries_total
                    if after is not None
                    else 0.0
                )
                request_delta = (
                    after.request_success_total - self._apc_before.request_success_total
                    if after is not None
                    and after.request_success_total is not None
                    and self._apc_before.request_success_total is not None
                    else None
                )
                settled = query_delta > 0 and (
                    request_delta is None
                    or request_delta == self._generation_success_count
                )
                if settled:
                    break
                time.sleep(1.0)
                after = sample_apc_metrics(
                    config,
                    raw_snapshot_path=self.settings.root / "apc-metrics-after.prom",
                )
        observation_wait_ms = (time.monotonic_ns() - observation_started_ns) / 1_000_000.0
        delta = finish_apc_metrics_window(
            config,
            self._apc_before,
            after,
            request_count=self._generation_success_count,
            retry_count=self._apc_retry_count,
            expected_engine_instance_id=(
                str(getattr(self._apc_before, "engine_instance_id", ""))
                if self._apc_before is not None
                else ""
            ),
            expected_cache_epoch=(
                str(getattr(self._apc_before, "cache_epoch", ""))
                if self._apc_before is not None
                else ""
            ),
            window_scope="task",
        )
        append_event(
            self.settings.model_assist_path,
            {
                "event": "apc_task_window",
                "scope": "task",
                "request_count": self._generation_success_count,
                "apc_request_count": self._apc_request_count,
                "retry_count": self._apc_retry_count,
                "observation_wait_ms": observation_wait_ms,
                "before": self._apc_before.canonical_payload() if self._apc_before else None,
                "after": after.canonical_payload() if after else None,
                "observation": make_apc_observation(
                    service_enabled=config.apc_enabled,
                    service_ready_attested=config.apc_service_ready,
                    delta=delta,
                    requested=self.settings.profile in {"apc", "auto"},
                ),
            },
        )

    def describe(self) -> dict[str, object]:
        return {
            **dict(self.ordinary.describe()),
            "model_assist_profile": self.settings.profile,
            "model_assist_endpoint": self.settings.base_url,
            "model_assist_kv_endpoint": self.settings.kv_base_url if self.settings.kv_mode else None,
            "model_assist_apc_metrics_url": self.settings.apc_metrics_url or None,
            "model_assist_sidecar": str(self.settings.model_assist_path),
            "model_assist_shared_prefix": bool(
                self.settings.shared_prefix_text and self.settings.profile != "logit"
            ),
        }

    @property
    def request_events(self) -> list[dict[str, object]]:
        events = [dict(item) for item in self.ordinary.request_events]
        if self.kv_client is not None:
            events.extend(dict(item) for item in self.kv_client.local_request_events)
        return sorted(events, key=lambda item: int(item.get("start_ns", 0) or 0))

    def close(self) -> None:
        if self.kv_client is not None:
            self.kv_client.close()
        close = getattr(self.ordinary, "close", None)
        if callable(close):
            close()

    def _decorate_messages(
        self,
        messages: list[ChatMessage],
        role: str,
        route: ModelAssistRoute,
    ) -> list[ChatMessage]:
        if role not in {"executor", "summarizer"}:
            return list(messages)
        if route.effective_mode not in {"apc_full_prompt", "full_replay", "kv_continuation"}:
            return list(messages)
        if not self.settings.shared_prefix_text.strip():
            return list(messages)
        prefix = shared_prefix_envelope(self.settings.shared_prefix_text)
        suffix = f'<statebus-role-suffix-v2 role="{role}">\n'
        if not messages:
            return messages
        first = messages[0]
        if first.role == "system":
            content = prefix + suffix + first.content
            return [ChatMessage(first.role, content), *messages[1:]]
        return [ChatMessage("system", prefix + suffix), *messages]


def build_contest_model_assist_client(
    raw: LLMClient,
    *,
    journal_path: Path,
    settings: ContestModelAssistSettings,
) -> ContestModelAssistClient:
    ordinary = JournalClient(raw, journal_path)
    kv_client = None
    kv_journal = None
    try:
        if settings.kv_mode is not None:
            kv_config = EngineLocalKVRoleClientConfig(
                mode=settings.kv_mode,
                task_id=settings.task_id,
                audit_path=settings.root / "engine-local-kv.json",
                model=settings.model,
                parent_tokens=settings.parent_tokens,
                ttl_s=settings.ttl_s,
                seed=settings.seed,
                executor_max_tokens=3072,
                summarizer_max_tokens=1536,
                logprobs=settings.kv_logprobs,
                top_logprobs=20 if settings.kv_logprobs else 0,
                profile=settings.profile,
                shared_prefix_text=settings.shared_prefix_text,
                kv_base_url=settings.kv_base_url,
                kv_timeout_s=settings.kv_timeout_s,
                tokenizer_timeout_s=settings.tokenizer_timeout_s,
                chat_template_kwargs={"enable_thinking": False},
            )
            kv_client = EngineLocalKVRoleClient(raw, kv_config)
            kv_journal = JournalClient(kv_client, journal_path)
    except BaseException:
        if kv_client is not None:
            try:
                kv_client.close()
            except Exception:
                pass
        raise
    return ContestModelAssistClient(
        ordinary,
        settings,
        kv_client=kv_client,
        kv_journal=kv_journal,
    )


__all__ = [
    "ContestModelAssistClient",
    "ContestModelAssistSettings",
    "build_contest_model_assist_client",
    "render_public_context",
]
