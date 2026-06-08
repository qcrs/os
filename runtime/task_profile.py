from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.reuse_contract import normalize_runtime_reuse_contract


@dataclass(frozen=True)
class RuntimeTaskProfile:
    runtime_reuse_contract: str = ""

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None = None) -> RuntimeTaskProfile:
        values = payload or {}
        raw_contract = str(values.get("runtime_reuse_contract", "")).strip()
        return cls(
            runtime_reuse_contract=(
                normalize_runtime_reuse_contract(raw_contract) if raw_contract else ""
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "runtime_reuse_contract": self.runtime_reuse_contract,
        }

    @property
    def is_empty(self) -> bool:
        return not self.runtime_reuse_contract


def build_reuse_signature(task_theme: str, tags: list[str] | tuple[str, ...]) -> str:
    normalized = [str(tag).strip() for tag in tags if str(tag).strip()]
    stable_tags = "|".join(sorted(set(normalized)))
    return f"{task_theme}:{stable_tags}" if stable_tags else task_theme
