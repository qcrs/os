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

TRANSFER_STRATEGIES = (
    "state_ref",
    "text_brief",
    "mode_split_text_brief_vs_state_ref",
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
        "state_ref": "state_ref",
        "structured_state": "state_ref",
        "text_brief": "text_brief",
        "mode_split": "mode_split_text_brief_vs_state_ref",
        "mode_split_text_brief_vs_state_ref": "mode_split_text_brief_vs_state_ref",
    }
    normalized = alias_map.get(text, text)
    if normalized not in TRANSFER_STRATEGIES:
        raise ValueError(f"unsupported transfer_strategy: {value!r}")
    return normalized


@dataclass(frozen=True)
class RuntimeTaskProfile:
    runtime_reuse_contract: str = ""
    benchmark_lane: str = ""
    transfer_strategy: str = ""

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None = None) -> RuntimeTaskProfile:
        values = payload or {}
        raw_contract = str(values.get("runtime_reuse_contract", "")).strip()
        raw_lane = str(values.get("benchmark_lane", "")).strip()
        raw_transfer_strategy = str(values.get("transfer_strategy", "")).strip()
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
        )

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.runtime_reuse_contract:
            payload["runtime_reuse_contract"] = self.runtime_reuse_contract
        if self.benchmark_lane:
            payload["benchmark_lane"] = self.benchmark_lane
        if self.transfer_strategy:
            payload["transfer_strategy"] = self.transfer_strategy
        return payload

    @property
    def is_empty(self) -> bool:
        return not self.runtime_reuse_contract and not self.benchmark_lane and not self.transfer_strategy

    @property
    def resolved_benchmark_lane(self) -> str:
        return normalize_benchmark_lane(self.benchmark_lane)

    @property
    def resolved_transfer_strategy(self) -> str:
        return normalize_transfer_strategy(self.transfer_strategy)

    def effective_transfer_strategy(self, mode: str) -> str:
        strategy = self.resolved_transfer_strategy
        if strategy == "mode_split_text_brief_vs_state_ref":
            return "text_brief" if str(mode).strip().lower() == "text" else "state_ref"
        return strategy


def build_reuse_signature(task_theme: str, tags: list[str] | tuple[str, ...]) -> str:
    normalized = [str(tag).strip() for tag in tags if str(tag).strip()]
    stable_tags = "|".join(sorted(set(normalized)))
    return f"{task_theme}:{stable_tags}" if stable_tags else task_theme
