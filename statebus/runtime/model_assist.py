"""Small task-local model assistance policy for the experimental mainline."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Mapping
from urllib.request import urlopen

from statebus.runtime.logit_state import ExactChoiceLogitResult, serialize_logit_state_v2
from statebus.runtime.vllm_metrics import (
    VllmPrefixCacheCounterDelta,
    VllmPrefixCacheMetrics,
    compute_vllm_prefix_cache_counter_delta,
    parse_vllm_prefix_cache_metrics,
)
from statebus.utils import sha256_digest


MODEL_ASSIST_PROFILES = frozenset(
    {"off", "logit", "kv_replay", "kv_continuation", "kv_logit", "apc", "auto"}
)


@dataclass(frozen=True)
class ModelAssistConfig:
    profile: str = "off"
    model: str = "qwen3-32b"
    parent_tokens: int = 0
    ttl_s: int = 300
    seed: int = 7
    # This flag records the requested application profile. Provider readiness
    # is established from the invocation, never inferred from this setting.
    apc_enabled: bool = False
    apc_service_ready: bool = False
    apc_metrics_url: str = ""
    apc_metrics_exclusive: bool = False

    @classmethod
    def from_env(cls) -> "ModelAssistConfig":
        profile = os.getenv("STATEBUS_MODEL_ASSIST_PROFILE", "off").strip().lower() or "off"
        if profile not in MODEL_ASSIST_PROFILES:
            raise ValueError(f"unsupported model assist profile: {profile}")
        return cls(
            profile=profile,
            model=os.getenv("STATEBUS_ENGINE_LOCAL_KV_MODEL", "qwen3-32b").strip(),
            parent_tokens=max(0, int(os.getenv("STATEBUS_ENGINE_LOCAL_KV_PARENT_TOKENS", "0"))),
            ttl_s=max(1, int(os.getenv("STATEBUS_ENGINE_LOCAL_KV_TTL_S", "300"))),
            seed=max(0, int(os.getenv("STATEBUS_ENGINE_LOCAL_KV_SEED", "7"))),
            apc_enabled=os.getenv("STATEBUS_APC_ENABLED", "0").strip().lower()
            in {"1", "true", "yes", "on"},
            apc_service_ready=os.getenv("STATEBUS_APC_SERVICE_READY", "0").strip().lower()
            in {"1", "true", "yes", "on"},
            apc_metrics_url=os.getenv("STATEBUS_APC_METRICS_URL", "").strip(),
            apc_metrics_exclusive=os.getenv("STATEBUS_APC_METRICS_EXCLUSIVE", "0").strip().lower()
            in {"1", "true", "yes", "on"},
        )

    @property
    def enabled(self) -> bool:
        return self.profile != "off"


@dataclass
class ModelAssistHandoff:
    """One task/session-local producer-to-consumer handoff slot."""

    producer_step: str = ""
    producer_attempt: str = ""
    consumer_role: str = "summarizer"
    parent_token_ids: tuple[int, ...] = ()
    parent_token_digest: str = ""
    generation: str = ""
    handle_metadata: dict[str, Any] = field(default_factory=dict)
    handle_id: str = ""
    task_id: str = ""

    def clear(self) -> None:
        self.producer_step = ""
        self.producer_attempt = ""
        self.parent_token_ids = ()
        self.parent_token_digest = ""
        self.generation = ""
        self.handle_metadata.clear()
        self.handle_id = ""


@dataclass(frozen=True)
class ModelAssistRoute:
    effective_mode: str
    route_reason: str
    preflight_checked: bool = False
    requested_mode: str = ""


def choose_model_assist_route(
    config: ModelAssistConfig,
    *,
    role: str,
    has_compatible_handle: bool = False,
    shared_prefix_eligible: bool = False,
    kv_ready: bool = False,
    apc_ready: bool = False,
) -> ModelAssistRoute:
    """Choose a physical prefill mode without changing Runtime execution kind."""

    role = str(role).strip().lower()
    if role not in {"executor", "summarizer"}:
        return ModelAssistRoute(
            "ordinary", "role_not_in_executor_summarizer_pair", True, config.profile
        )
    profile = config.profile
    if profile == "off":
        return ModelAssistRoute("ordinary", "profile_off", True, "ordinary")
    if profile == "logit":
        return ModelAssistRoute("ordinary", "logit_observation_only", True, "ordinary")
    if profile == "kv_replay":
        return ModelAssistRoute("full_replay", "explicit_full_replay", True, "full_replay")
    if profile in {"kv_continuation", "kv_logit"}:
        if role == "summarizer" and has_compatible_handle and kv_ready and shared_prefix_eligible:
            return ModelAssistRoute(
                "kv_continuation", "explicit_same_worker_handle", True, "kv_continuation"
            )
        if role == "executor" and kv_ready and shared_prefix_eligible:
            return ModelAssistRoute(
                "kv_continuation",
                "explicit_capture_for_summarizer",
                True,
                "kv_continuation",
            )
        return ModelAssistRoute(
            "mechanism_failure", "explicit_continuation_ineligible", True, "kv_continuation"
        )
    if profile == "apc":
        return (
            ModelAssistRoute(
                "apc_full_prompt", "apc_service_with_shared_prefix", True, "apc_full_prompt"
            )
            if apc_ready and shared_prefix_eligible
            else ModelAssistRoute(
                "ordinary",
                "apc_service_unavailable" if not apc_ready else "apc_prefix_ineligible",
                True,
                "apc_full_prompt",
            )
        )
    if has_compatible_handle and kv_ready and shared_prefix_eligible and role == "summarizer":
        return ModelAssistRoute("kv_continuation", "auto_same_worker_handle", True, "kv_continuation")
    if kv_ready and shared_prefix_eligible and role == "executor":
        return ModelAssistRoute("kv_continuation", "auto_capture_for_summarizer", True, "kv_continuation")
    if apc_ready and shared_prefix_eligible:
        return ModelAssistRoute("apc_full_prompt", "auto_apc_full_prompt", True, "apc_full_prompt")
    return ModelAssistRoute("ordinary", "auto_no_eligible_reuse", True, "ordinary")


def make_observation(
    config: ModelAssistConfig,
    *,
    step: str = "",
    attempt: str = "",
    route: ModelAssistRoute | None = None,
    kv: Mapping[str, Any] | None = None,
    logit: Mapping[str, Any] | None = None,
    apc: Mapping[str, Any] | None = None,
    prefix_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    selected = route or ModelAssistRoute("ordinary", "not_routed")
    observation = {
        "profile": config.profile,
        "step": str(step),
        "attempt": str(attempt),
        "requested_mode": selected.requested_mode or config.profile,
        "effective_mode": selected.effective_mode,
        "route_reason": selected.route_reason,
        "preflight_checked": selected.preflight_checked,
        "observations": {
            "kv": dict(kv or {"status": "unavailable", "reason": "not_observed"}),
            "logit": dict(logit or {
                "status": "unavailable",
                "available": False,
                "source": "same_call_top_logprobs",
                "semantics": "unknown",
                "reason": "not_observed",
            }),
            "apc": dict(apc or {
                "status": "unavailable",
                "available": False,
                "service_enabled": bool(config.apc_enabled),
                "service_ready_attested": bool(config.apc_service_ready),
                "metrics_available": False,
                "delta_valid": False,
                "reason": "not_observed",
            }),
        },
    }
    if prefix_identity:
        observation["prefix_identity"] = dict(prefix_identity)
    return observation


def make_logit_observation(
    top_logprobs: list[object] | None,
    *,
    candidate_tokens: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Summarize one generation's logprobs without turning proxy confidence into a claim."""

    if not top_logprobs:
        return {
            "status": "unavailable",
            "available": False,
            "source": "same_call_top_logprobs",
            "semantics": "unknown",
            "reason": "top_logprobs_missing",
        }
    result = serialize_logit_state_v2(top_logprobs, candidate_tokens=candidate_tokens or None)
    if result.peak_position < 0 or not result.payload_bytes:
        return {
            "status": "unavailable",
            "available": False,
            "source": "same_call_top_logprobs",
            "semantics": "token_proxy",
            "sequence_length": result.sequence_length,
            "reason": "top_logprobs_unparseable",
        }
    return {
        "status": "available",
        "available": True,
        "source": "same_call_top_logprobs",
        # Candidate strings only provide a heuristic grouping for the generic
        # sequence serializer. Exact candidate probabilities require the
        # closed-set extractor and its receipt below.
        "semantics": "token_proxy",
        "sequence_length": result.sequence_length,
        "peak_position": result.peak_position,
        "entropy": result.entropy,
        "aggregated_entropy": result.aggregated_entropy,
        "varentropy": result.varentropy,
        "top_gap": result.top_gap,
        "decision_entropy": result.decision_entropy,
        "confidence_proxy": result.confidence_proxy,
    }


def make_exact_logit_observation(
    result: ExactChoiceLogitResult | None,
) -> dict[str, Any]:
    """Adapt a closed-set extraction result without widening its claim."""

    if result is None:
        return {
            "status": "unavailable",
            "available": False,
            "source": "same_call_top_logprobs",
            "semantics": "exact_candidate_plus_other",
            "reason": "exact_candidate_not_attempted",
        }
    receipt = result.receipt.canonical_payload()
    observation: dict[str, Any] = {
        "status": "available" if result.available else "unavailable",
        "available": result.available,
        "source": "same_call_top_logprobs",
        "semantics": "exact_candidate_plus_other",
        "candidate_surface_digest": result.receipt.candidate_surface_digest,
        "alias_mapping_digest": result.receipt.alias_mapping_digest,
        "selected_alias": result.selected_alias,
        "selected_candidate_id": result.selected_candidate_id,
        "decision_token_position": result.receipt.decision_token_position,
        "sequence_length": result.receipt.sequence_length,
        "receipt": receipt,
    }
    if not result.available:
        observation["reason"] = result.receipt.unavailable_reason
        return observation
    candidate_mass = sum(result.candidate_probabilities)
    observation.update(
        {
            "candidate_mass": candidate_mass,
            "selected_probability": result.candidate_probabilities[result.selected_candidate_ordinal],
            "other_mass": result.other_mass,
            "top_margin": result.top_margin,
            "surface_entropy": result.entropy,
            "normalized_entropy": result.normalized_entropy,
        }
    )
    return observation


def shared_prefix_identity(
    shared_prefix_text: str,
    *,
    layout: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = str(shared_prefix_text).strip()
    if not normalized:
        return {"eligible": False, "reason": "shared_prefix_missing"}
    encoded = normalized.encode("utf-8")
    layout_payload = dict(layout or {})
    eligible = bool(layout_payload.get("shared_prefix_enabled", False))
    identity = {
        "eligible": eligible,
        "token_verified": bool(layout_payload.get("token_verified", False)),
        "text_sha256": sha256_digest(encoded),
        "text_bytes": len(encoded),
        "layout_version": str(
            layout_payload.get("prefix_layout_version", "statebus.shared_evidence_prefix.v2")
        ),
    }
    if layout_payload:
        identity.update(
            {
                "prompt_sha256": str(layout_payload.get("prompt_hash", "")),
                "role_suffix_sha256": str(layout_payload.get("role_suffix_hash", "")),
                "role": str(layout_payload.get("role_label", "")),
            }
        )
    else:
        identity["reason"] = "layout_not_observed"
    if not eligible and "reason" not in identity:
        identity["reason"] = str(
            layout_payload.get("ineligible_reason", "prefix_layout_ineligible")
        )
    return identity


def sample_apc_metrics(
    config: ModelAssistConfig,
    *,
    raw_snapshot_path: Path | None = None,
) -> VllmPrefixCacheMetrics | None:
    """Read a configured APC metrics endpoint for one invocation window."""

    # A metrics endpoint is an observation hook, not a readiness proof. The
    # caller still needs a valid counter window before APC is attributed.
    if not config.apc_metrics_url:
        return None
    try:
        with urlopen(config.apc_metrics_url, timeout=2.0) as response:  # nosec B310 - caller owns endpoint policy
            raw_text = response.read().decode("utf-8", errors="replace")
        if raw_snapshot_path is not None:
            raw_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            raw_snapshot_path.write_text(raw_text, encoding="utf-8")
        return parse_vllm_prefix_cache_metrics(raw_text)
    except (OSError, ValueError):
        return None


def finish_apc_metrics_window(
    config: ModelAssistConfig,
    before: VllmPrefixCacheMetrics | None,
    after: VllmPrefixCacheMetrics | None,
    *,
    request_count: int,
    retry_count: int,
    pollution_detected: bool = False,
    expected_engine_instance_id: str = "",
    expected_cache_epoch: str = "",
    window_scope: str = "request",
) -> VllmPrefixCacheCounterDelta | None:
    if before is None or after is None:
        return None
    return compute_vllm_prefix_cache_counter_delta(
        before,
        after,
        exclusive_interval=config.apc_metrics_exclusive,
        pollution_detected=pollution_detected,
        request_count=max(0, int(request_count)),
        retry_count=max(0, int(retry_count)),
        expected_engine_instance_id=str(expected_engine_instance_id),
        expected_cache_epoch=str(expected_cache_epoch),
        window_scope=str(window_scope),
    )


def make_apc_observation(
    *,
    service_enabled: bool,
    service_ready_attested: bool | None = None,
    delta: Any | None = None,
    prefix_identity: str = "",
    requested: bool | None = None,
) -> dict[str, Any]:
    """Adapt a real vLLM counter delta without treating missing metrics as zero."""

    ready_attested = bool(
        service_enabled if service_ready_attested is None else service_ready_attested
    )
    observation: dict[str, Any] = {
        "status": "unavailable",
        "available": False,
        "requested": bool(service_enabled if requested is None else requested),
        "service_enabled": bool(service_enabled),
        "service_ready_attested": ready_attested,
        "metrics_available": False,
        "delta_valid": False,
    }
    if prefix_identity:
        observation["prefix_identity"] = prefix_identity
    if not service_enabled:
        observation["reason"] = "service_disabled"
        return observation
    if not service_ready_attested:
        observation["reason"] = "service_not_ready"
        return observation
    if delta is None:
        observation["reason"] = "metrics_not_observed"
        return observation
    payload = delta.canonical_payload() if hasattr(delta, "canonical_payload") else dict(delta)
    available = bool(payload.get("available", False))
    valid = bool(payload.get("valid", False))
    observation.update(
        {
            "status": "available" if available and valid else "unavailable",
            "available": available and valid,
            "metrics_available": available,
            "delta_valid": valid,
            "reason": "" if available and valid else str(payload.get("unavailable_reason", "delta_invalid")),
            "counter_unit": payload.get("counter_unit", "tokens"),
            "exclusive_interval": bool(payload.get("exclusive_interval", False)),
            "pollution_detected": bool(payload.get("pollution_detected", False)),
            "window_scope": payload.get("window_scope", "request"),
        }
    )
    if available and valid:
        observation.update(
            {
                "query_tokens": payload.get("observed_query_token_delta"),
                "hit_tokens": payload.get("observed_hit_token_delta"),
                "hit_rate": payload.get("observed_token_hit_rate"),
            }
        )
    return observation


def route_for_profile(
    config: ModelAssistConfig,
    *,
    role: str,
    shared_prefix_eligible: bool | None = None,
    kv_ready: bool = False,
    apc_ready: bool = False,
    has_compatible_handle: bool = False,
) -> ModelAssistRoute:
    """Resolve a route from provider facts; absent facts remain explicitly unchecked."""

    if shared_prefix_eligible is None:
        requested_mode = {
            "kv_replay": "full_replay",
            "kv_continuation": "kv_continuation",
            "kv_logit": "kv_continuation",
            "apc": "apc_full_prompt",
        }.get(config.profile, "ordinary")
        # A requested physical lane is not an effective lane until provider
        # facts have been checked. This prevents fallback telemetry from
        # claiming a KV/APC path that never ran.
        return ModelAssistRoute("ordinary", "profile_request_unchecked", False, requested_mode)

    return choose_model_assist_route(
        config,
        role=role,
        has_compatible_handle=has_compatible_handle,
        shared_prefix_eligible=shared_prefix_eligible,
        kv_ready=kv_ready,
        apc_ready=apc_ready,
    )


__all__ = [
    "MODEL_ASSIST_PROFILES",
    "ModelAssistConfig",
    "ModelAssistHandoff",
    "ModelAssistRoute",
    "choose_model_assist_route",
    "make_observation",
    "make_logit_observation",
    "make_exact_logit_observation",
    "make_apc_observation",
    "shared_prefix_identity",
    "sample_apc_metrics",
    "finish_apc_metrics_window",
    "route_for_profile",
]
