from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RUNTIME_REUSE_CONTRACTS = (
    "reuse_disabled",
    "assist_allowed",
    "validated_replay",
    "exact_replay",
)


def normalize_runtime_reuse_contract(value: object) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    alias_map = {
        "": "assist_allowed",
        "assist": "assist_allowed",
        "assist_allowed": "assist_allowed",
        "none": "assist_allowed",
        "reuse_disabled": "reuse_disabled",
        "disabled": "reuse_disabled",
        "skip_execute": "validated_replay",
        "validated_replay": "validated_replay",
        "skip_retrieve_execute": "exact_replay",
        "exact_replay": "exact_replay",
    }
    normalized = alias_map.get(text, text)
    if normalized not in RUNTIME_REUSE_CONTRACTS:
        raise ValueError(f"unsupported runtime_reuse_contract: {value!r}")
    return normalized


def runtime_reuse_contract_gates(contract: object) -> dict[str, bool]:
    normalized = normalize_runtime_reuse_contract(contract)
    return {
        "allow_memory_assist": normalized == "assist_allowed",
        "allow_execute_prune": normalized == "validated_replay",
        "allow_exact_replay": normalized == "exact_replay",
    }


def runtime_reuse_contract_from_legacy(
    *,
    expected_reuse_mode: object = "none",
    allow_memory_assist: object | None = None,
    allow_execute_prune: object | None = None,
    allow_exact_replay: object | None = None,
) -> str:
    exact = _coerce_optional_bool(allow_exact_replay)
    execute_prune = _coerce_optional_bool(allow_execute_prune)
    memory_assist = _coerce_optional_bool(allow_memory_assist)
    if exact is True:
        return "exact_replay"
    if execute_prune is True:
        return "validated_replay"
    if memory_assist is True:
        return "assist_allowed"
    if memory_assist is False and execute_prune is False and exact is False:
        return "reuse_disabled"
    return normalize_runtime_reuse_contract(expected_reuse_mode)


def resolve_runtime_reuse_contract(
    params: Mapping[str, Any] | None,
    *,
    default_expected_reuse_mode: str = "none",
) -> str:
    payload = params or {}
    explicit = str(payload.get("runtime_reuse_contract", "")).strip()
    if explicit:
        return normalize_runtime_reuse_contract(explicit)
    return runtime_reuse_contract_from_legacy(
        expected_reuse_mode=payload.get("expected_reuse_mode", default_expected_reuse_mode),
        allow_memory_assist=payload.get("allow_memory_assist"),
        allow_execute_prune=payload.get("allow_execute_prune"),
        allow_exact_replay=payload.get("allow_exact_replay"),
    )


def _coerce_optional_bool(value: object | None) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None
