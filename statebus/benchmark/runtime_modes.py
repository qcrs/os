from __future__ import annotations

from statebus.integrations.llm import LLMConfig
from statebus.runtime import runtime_preflight


def benchmark_role_path_mode_missing_reason(role_path_mode: str) -> str:
    normalized_mode = str(role_path_mode).strip().lower()
    try:
        LLMConfig.from_runtime().with_mode(normalized_mode).require_api_ready()
    except Exception as exc:
        return f"role_path_mode={normalized_mode} not ready: {exc}"
    return ""


def benchmark_role_path_mode_ready(role_path_mode: str) -> bool:
    return benchmark_role_path_mode_missing_reason(role_path_mode) == ""


def benchmark_runtime_missing_reason(
    *,
    role_path_mode: str,
    embedding_mode: str = "deterministic",
) -> str:
    report = runtime_preflight(
        role_path_mode=role_path_mode,
        embedding_mode=embedding_mode,
    )
    if report.ok:
        return ""
    return "; ".join(report.missing_reasons)
