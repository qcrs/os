from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.reuse_contract import normalize_runtime_reuse_contract

BENCHMARK_LANES = (
    "internal_regression",
    "communication",
    "state_transfer",
    "memory",
)

HANDOFF_PROFILES = (
    "text_strict_pure_lane",
    "text_whole_lane",
    "protocol_natural_handoff_text",
    "protocol_inline_text_handoff",
    "protocol_minimal_text_packet",
    "protocol_minimal_state_packet",
    "protocol_feature_only_typed_state",
    "protocol_full_rich_audit",
    "protocol_text_shadow_audit",
)

TRANSFER_STRATEGIES = (
    "text_strict_pure_lane",
    "text_whole_lane",
    "state_ref",
    "text_brief",
    "text_packet_minimal",
    "state_packet_minimal",
    "natural_handoff_text",
    "inline_text_handoff",
)


def normalize_benchmark_lane(value: object) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if not text:
        return "internal_regression"
    if text not in BENCHMARK_LANES:
        raise ValueError(f"unsupported benchmark_lane: {value!r}")
    return text


def normalize_transfer_strategy(value: object) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    alias_map = {
        "": "state_ref",
        "text_strict_pure_lane": "text_strict_pure_lane",
        "text_whole_lane": "text_whole_lane",
        "state_ref": "state_ref",
        "structured_state": "state_ref",
        "text_brief": "text_brief",
        "text_packet_minimal": "text_packet_minimal",
        "state_packet_minimal": "state_packet_minimal",
        "natural_handoff_text": "natural_handoff_text",
        "inline_text_handoff": "inline_text_handoff",
    }
    normalized = alias_map.get(text, text)
    if normalized not in TRANSFER_STRATEGIES:
        raise ValueError(f"unsupported transfer_strategy: {value!r}")
    return normalized


def normalize_handoff_profile(value: object) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    alias_map = {
        "": "protocol_feature_only_typed_state",
        "text_strict_pure_lane": "text_strict_pure_lane",
        "text_whole_lane": "text_whole_lane",
        "protocol_natural_handoff_text": "protocol_natural_handoff_text",
        "natural_handoff_text": "protocol_natural_handoff_text",
        "protocol_inline_text_handoff": "protocol_inline_text_handoff",
        "inline_text_handoff": "protocol_inline_text_handoff",
        "protocol_minimal_text_packet": "protocol_minimal_text_packet",
        "text_packet_minimal": "protocol_minimal_text_packet",
        "protocol_minimal_state_packet": "protocol_minimal_state_packet",
        "state_packet_minimal": "protocol_minimal_state_packet",
        "protocol_feature_only_typed_state": "protocol_feature_only_typed_state",
        "protocol_rich_typed_state": "protocol_feature_only_typed_state",
        "state_ref": "protocol_feature_only_typed_state",
        "protocol_full_rich_audit": "protocol_full_rich_audit",
        "full_rich_audit": "protocol_full_rich_audit",
        "protocol_text_shadow_audit": "protocol_text_shadow_audit",
        "text_brief": "protocol_text_shadow_audit",
    }
    normalized = alias_map.get(text, text)
    if normalized not in HANDOFF_PROFILES:
        raise ValueError(f"unsupported handoff_profile: {value!r}")
    return normalized


@dataclass(frozen=True)
class RuntimeTaskProfile:
    runtime_reuse_contract: str = ""
    benchmark_lane: str = ""
    transfer_strategy: str = ""
    handoff_profile: str = ""

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None = None) -> RuntimeTaskProfile:
        values = payload or {}
        raw_contract = str(values.get("runtime_reuse_contract", "")).strip()
        raw_lane = str(values.get("benchmark_lane", "")).strip()
        raw_transfer_strategy = str(values.get("transfer_strategy", "")).strip()
        raw_handoff_profile = str(values.get("handoff_profile", "")).strip()
        return cls(
            runtime_reuse_contract=(
                normalize_runtime_reuse_contract(raw_contract) if raw_contract else ""
            ),
            benchmark_lane=normalize_benchmark_lane(raw_lane) if raw_lane else "",
            transfer_strategy=(
                normalize_transfer_strategy(raw_transfer_strategy)
                if raw_transfer_strategy
                else ""
            ),
            handoff_profile=(
                normalize_handoff_profile(raw_handoff_profile)
                if raw_handoff_profile
                else ""
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.runtime_reuse_contract:
            payload["runtime_reuse_contract"] = self.runtime_reuse_contract
        if self.benchmark_lane:
            payload["benchmark_lane"] = self.benchmark_lane
        if self.transfer_strategy:
            payload["transfer_strategy"] = self.transfer_strategy
        if self.handoff_profile:
            payload["handoff_profile"] = self.handoff_profile
        return payload

    @property
    def is_empty(self) -> bool:
        return (
            not self.runtime_reuse_contract
            and not self.benchmark_lane
            and not self.transfer_strategy
            and not self.handoff_profile
        )

    @property
    def resolved_benchmark_lane(self) -> str:
        return normalize_benchmark_lane(self.benchmark_lane)

    @property
    def resolved_transfer_strategy(self) -> str:
        return normalize_transfer_strategy(self.transfer_strategy)

    @property
    def resolved_handoff_profile(self) -> str:
        if self.handoff_profile:
            return normalize_handoff_profile(self.handoff_profile)
        strategy = self.resolved_transfer_strategy
        if strategy == "state_ref":
            return "protocol_feature_only_typed_state"
        if strategy == "text_packet_minimal":
            return "protocol_minimal_text_packet"
        if strategy == "state_packet_minimal":
            return "protocol_minimal_state_packet"
        if strategy == "text_brief":
            return "protocol_text_shadow_audit"
        if strategy == "natural_handoff_text":
            return "protocol_natural_handoff_text"
        if strategy == "inline_text_handoff":
            return "protocol_inline_text_handoff"
        if strategy == "text_strict_pure_lane":
            return "text_strict_pure_lane"
        if strategy == "text_whole_lane":
            return "text_whole_lane"
        return normalize_handoff_profile(strategy)

    def effective_transfer_strategy(self, mode: str) -> str:
        profile = self.resolved_handoff_profile
        normalized_mode = str(mode).strip().lower()
        if profile == "text_strict_pure_lane":
            if normalized_mode != "text":
                raise ValueError("handoff_profile=text_strict_pure_lane is only valid in mode=text")
            return "text_strict_pure_lane"
        if profile == "text_whole_lane":
            if normalized_mode != "text":
                raise ValueError("handoff_profile=text_whole_lane is only valid in mode=text")
            return "text_whole_lane"
        if profile == "protocol_natural_handoff_text":
            return "natural_handoff_text"
        if profile == "protocol_inline_text_handoff":
            return "inline_text_handoff"
        if profile == "protocol_minimal_text_packet":
            return "text_packet_minimal"
        if profile == "protocol_minimal_state_packet":
            return "state_packet_minimal"
        if profile in {"protocol_feature_only_typed_state", "protocol_full_rich_audit"}:
            return "state_ref"
        if profile == "protocol_text_shadow_audit":
            return "text_brief"
        return self.resolved_transfer_strategy


def build_reuse_signature(task_theme: str, tags: list[str] | tuple[str, ...]) -> str:
    normalized = [str(tag).strip() for tag in tags if str(tag).strip()]
    stable_tags = "|".join(sorted(set(normalized)))
    return f"{task_theme}:{stable_tags}" if stable_tags else task_theme
