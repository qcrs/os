from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
from pathlib import Path

from statebus.integrations.llm import LLMConfig
from statebus.memory import default_embedding_model_path, resolve_embed_device, torch_cuda_available


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class RuntimePreflightReport:
    role_path_mode: str
    embedding_mode: str
    checks: tuple[PreflightCheck, ...]
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def missing_reasons(self) -> tuple[str, ...]:
        return tuple(check.detail for check in self.checks if not check.ok)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "role_path_mode": self.role_path_mode,
            "embedding_mode": self.embedding_mode,
            "checks": [
                {"name": check.name, "ok": check.ok, "detail": check.detail}
                for check in self.checks
            ],
            "metadata": dict(sorted(self.metadata.items())),
        }


def runtime_preflight(
    *,
    role_path_mode: str = "deterministic",
    embedding_mode: str = "deterministic",
    embedding_model_path: str | Path | None = None,
    embedding_device: str | None = None,
) -> RuntimePreflightReport:
    checks: list[PreflightCheck] = []
    normalized_role_mode = str(role_path_mode).strip().lower()
    normalized_embedding_mode = str(embedding_mode).strip().lower()
    llm_config = LLMConfig.from_runtime().with_mode(normalized_role_mode)

    if normalized_role_mode in {"api", "local_vllm"}:
        try:
            llm_config.require_api_ready()
            checks.append(PreflightCheck("llm_api_ready", True, f"{normalized_role_mode} configuration ready"))
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    "llm_api_ready",
                    False,
                    f"{normalized_role_mode} configuration not ready: {exc}",
                )
            )
    else:
        checks.append(PreflightCheck("llm_api_ready", True, "deterministic mode does not require live api"))

    model_path = Path(embedding_model_path or default_embedding_model_path())
    device = resolve_embed_device(embedding_device)
    if normalized_embedding_mode == "deterministic":
        checks.append(PreflightCheck("embedding_mode", True, "deterministic embedding requires no local model"))
    elif normalized_embedding_mode in {"local", "sentence-transformers", "sentence_transformer"}:
        if importlib.util.find_spec("sentence_transformers") is None:
            checks.append(
                PreflightCheck(
                    "embedding_python_dependency",
                    False,
                    "missing python dependency: sentence_transformers",
                )
            )
        else:
            checks.append(
                PreflightCheck(
                    "embedding_python_dependency",
                    True,
                    "python dependency present: sentence_transformers",
                )
            )
        if model_path.exists():
            checks.append(PreflightCheck("embedding_model_path", True, f"embedding model present: {model_path}"))
        else:
            checks.append(PreflightCheck("embedding_model_path", False, f"embedding model missing: {model_path}"))
        if device.startswith("cuda"):
            if torch_cuda_available():
                checks.append(PreflightCheck("embedding_device", True, f"cuda available for {device}"))
            else:
                checks.append(PreflightCheck("embedding_device", False, f"cuda requested but unavailable: {device}"))
        else:
            checks.append(PreflightCheck("embedding_device", True, f"embedding device ready: {device}"))
    else:
        checks.append(PreflightCheck("embedding_mode", False, f"unsupported embedding mode: {embedding_mode}"))

    return RuntimePreflightReport(
        role_path_mode=normalized_role_mode,
        embedding_mode=normalized_embedding_mode,
        checks=tuple(checks),
        metadata={
            "llm_config_source": llm_config.source,
            "embedding_model_path": str(model_path),
            "embedding_device": device,
            "cuda_available": torch_cuda_available(),
        },
    )
