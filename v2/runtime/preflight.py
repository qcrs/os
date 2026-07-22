from __future__ import annotations

from dataclasses import dataclass, field
from email.parser import Parser
import importlib.util
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from runtime.llm import LLMConfig
from v2.memory import (
    default_embedding_model_path,
    resolve_embed_device,
    torch_cuda_available,
)


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


@dataclass(frozen=True)
class DeferredEnvironmentCheck:
    name: str
    action_gate: str
    detail: str


@dataclass(frozen=True)
class ContestEnvironmentPreflightReport:
    profile: str
    phase: str
    checks: tuple[PreflightCheck, ...]
    deferred_checks: tuple[DeferredEnvironmentCheck, ...]
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
            "profile": self.profile,
            "phase": self.phase,
            "offline_only": True,
            "checks": [
                {"name": check.name, "ok": check.ok, "detail": check.detail}
                for check in self.checks
            ],
            "deferred_checks": [
                {
                    "name": check.name,
                    "status": "deferred",
                    "action_gate": check.action_gate,
                    "detail": check.detail,
                }
                for check in self.deferred_checks
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
            checks.append(
                PreflightCheck(
                    "llm_api_ready", True, f"{normalized_role_mode} configuration ready"
                )
            )
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    "llm_api_ready",
                    False,
                    f"{normalized_role_mode} configuration not ready: {exc}",
                )
            )
    else:
        checks.append(
            PreflightCheck(
                "llm_api_ready", True, "deterministic mode does not require live api"
            )
        )

    model_path = Path(embedding_model_path or default_embedding_model_path())
    device = resolve_embed_device(embedding_device)
    if normalized_embedding_mode == "deterministic":
        checks.append(
            PreflightCheck(
                "embedding_mode",
                True,
                "deterministic embedding requires no local model",
            )
        )
    elif normalized_embedding_mode in {
        "local",
        "sentence-transformers",
        "sentence_transformer",
    }:
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
            checks.append(
                PreflightCheck(
                    "embedding_model_path",
                    True,
                    f"embedding model present: {model_path}",
                )
            )
        else:
            checks.append(
                PreflightCheck(
                    "embedding_model_path",
                    False,
                    f"embedding model missing: {model_path}",
                )
            )
        if device.startswith("cuda"):
            if torch_cuda_available():
                checks.append(
                    PreflightCheck(
                        "embedding_device", True, f"cuda available for {device}"
                    )
                )
            else:
                checks.append(
                    PreflightCheck(
                        "embedding_device",
                        False,
                        f"cuda requested but unavailable: {device}",
                    )
                )
        else:
            checks.append(
                PreflightCheck(
                    "embedding_device", True, f"embedding device ready: {device}"
                )
            )
    else:
        checks.append(
            PreflightCheck(
                "embedding_mode", False, f"unsupported embedding mode: {embedding_mode}"
            )
        )

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


_CONTEST_ACTION_GATES = (
    "STATEBUS_CONTEST_ALLOW_METRICS_CHECK",
    "STATEBUS_CONTEST_ALLOW_TOP_LOGPROBS_PROBE",
    "STATEBUS_CONTEST_ALLOW_FILING_DOWNLOAD",
    "STATEBUS_CONTEST_ALLOW_FORMAL_EXPERIMENTS",
    "STATEBUS_CONTEST_ALLOW_COLD_CACHE",
    "STATEBUS_CONTEST_ALLOW_SERVICE_RESTART",
    "STATEBUS_CONTEST_ALLOW_OPENEULER_VALIDATION",
)

_CONTEST_WRITABLE_ROOTS = (
    "STATEBUS_CACHES_DIR",
    "STATEBUS_RUNS_DIR",
    "STATEBUS_LOGS_DIR",
    "STATEBUS_WORKDIR",
    "STATEBUS_CONTEST_DATA_ROOT",
    "STATEBUS_CONTEST_RUN_ROOT",
    "STATEBUS_CONTEST_LOG_ROOT",
    "STATEBUS_FILING_DOWNLOAD_ROOT",
    "STATEBUS_FILING_CANONICAL_ROOT",
    "STATEBUS_FILING_PRIVATE_GOLD_ROOT",
    "STATEBUS_OPENEULER_VALIDATION_ROOT",
)


def contest_environment_preflight(
    environ: Mapping[str, str] | None = None,
) -> ContestEnvironmentPreflightReport:
    """Validate the contest environment without network or service access."""
    values = dict(os.environ if environ is None else environ)
    checks: list[PreflightCheck] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append(PreflightCheck(name=name, ok=ok, detail=detail))

    profile = values.get("STATEBUS_CONTEST_PROFILE", "").strip()
    phase = values.get("STATEBUS_CONTEST_PROFILE_PHASE", "").strip()
    record(
        "profile_identity",
        profile == "contest-rebuild-20260722"
        and values.get("STATEBUS_CONTEST_PROFILE_VERSION", "").strip() == "1",
        f"profile={profile or '<unset>'} version={values.get('STATEBUS_CONTEST_PROFILE_VERSION', '<unset>')}",
    )
    record(
        "preparation_phase",
        phase == "prepare",
        f"profile phase must be prepare for this offline preflight; found {phase or '<unset>'}",
    )

    latent_values = {
        "STATEBUS_LATENT_MODE": values.get("STATEBUS_LATENT_MODE", ""),
        "STATEBUS_LATENT_HANDOFF_MODE": values.get("STATEBUS_LATENT_HANDOFF_MODE", ""),
        "STATEBUS_LATENT_PROMPT_EMBEDS_ENABLED": values.get(
            "STATEBUS_LATENT_PROMPT_EMBEDS_ENABLED", ""
        ),
    }
    latent_off = (
        latent_values["STATEBUS_LATENT_MODE"].strip().lower() == "off"
        and latent_values["STATEBUS_LATENT_HANDOFF_MODE"].strip().lower() == "off"
        and latent_values["STATEBUS_LATENT_PROMPT_EMBEDS_ENABLED"].strip().lower()
        in {"0", "false", "off", "no"}
    )
    record("latent_disabled", latent_off, f"latent controls={latent_values}")

    prefix_policy = values.get("STATEBUS_PREFIX_POLICY", "").strip().lower()
    logit_policy = values.get("STATEBUS_LOGIT_POLICY", "").strip().lower()
    record(
        "treatments_disabled",
        prefix_policy == "off" and logit_policy == "off",
        f"prefix_policy={prefix_policy or '<unset>'} logit_policy={logit_policy or '<unset>'}",
    )
    record(
        "adaptive_prefix_feedback_disabled",
        _is_disabled(values.get("STATEBUS_PREFIX_FEEDBACK_ADAPTIVE", ""))
        and values.get("STATEBUS_PREFIX_ALIGNMENT_MODE", "").strip().lower()
        == "independent",
        "adaptive feedback must be disabled and legacy prefix alignment must be independent",
    )
    record(
        "prefix_preparation_guardrails",
        values.get("STATEBUS_PREFIX_REQUIRE_EXCLUSIVE_METRICS", "").strip().lower()
        in {"1", "true", "yes", "on"}
        and not values.get("STATEBUS_PREFIX_CACHE_NAMESPACE", "").strip()
        and not values.get("STATEBUS_PREFIX_CACHE_EPOCH", "").strip(),
        "exclusive metrics must be required and cache namespace/epoch must remain unassigned",
    )
    record(
        "logit_preparation_guardrails",
        values.get("STATEBUS_LOGIT_DECISION_TYPE", "").strip()
        == "executor_tool_recipe_choice_v1"
        and values.get("STATEBUS_LOGIT_MAX_ACTIONS", "").strip() == "1",
        "LogitState must use the closed executor choice and at most one action",
    )

    gate_values = {name: values.get(name, "") for name in _CONTEST_ACTION_GATES}
    record(
        "external_action_gates_disabled",
        all(_is_disabled(value) for value in gate_values.values()),
        f"action gates={gate_values}",
    )
    record(
        "serialized_formal_requests",
        values.get("STATEBUS_FORMAL_REQUEST_MODE", "").strip().lower() == "serialized"
        and values.get("STATEBUS_FORMAL_REQUEST_CONCURRENCY", "").strip() == "1",
        "formal requests must be serialized with concurrency=1",
    )

    base_url = values.get("STATEBUS_LOCAL_VLLM_BASE_URL", "").strip()
    health_url = values.get("STATEBUS_LOCAL_VLLM_HEALTH_URL", "").strip()
    metrics_url = values.get("STATEBUS_VLLM_METRICS_URL", "").strip()
    endpoint_ok, endpoint_detail = _validate_local_vllm_urls(
        base_url=base_url,
        health_url=health_url,
        metrics_url=metrics_url,
    )
    record("local_vllm_urls", endpoint_ok, endpoint_detail)

    query_names = _csv_values(values.get("STATEBUS_VLLM_METRIC_QUERY_NAMES", ""))
    hit_names = _csv_values(values.get("STATEBUS_VLLM_METRIC_HIT_NAMES", ""))
    record(
        "metrics_schema_candidates",
        any(name.endswith("_queries_total") for name in query_names)
        and any(name.endswith("_hits_total") for name in hit_names),
        f"query_candidates={query_names} hit_candidates={hit_names}",
    )
    metrics_status = values.get("STATEBUS_VLLM_METRICS_SCHEMA_STATUS", "").strip()
    logprobs_status = values.get("STATEBUS_TOP_LOGPROBS_CAPABILITY_STATUS", "").strip()
    record(
        "live_capability_statuses_unclaimed",
        metrics_status == "pending_live_check"
        and logprobs_status == "pending_live_check",
        f"metrics={metrics_status or '<unset>'} top_logprobs={logprobs_status or '<unset>'}",
    )
    try:
        top_logprobs_k = int(values.get("STATEBUS_TOP_LOGPROBS_PROBE_TOP_K", ""))
        top_logprobs_max_tokens = int(
            values.get("STATEBUS_TOP_LOGPROBS_PROBE_MAX_TOKENS", "")
        )
    except ValueError:
        top_logprobs_k = 0
        top_logprobs_max_tokens = 0
    record(
        "bounded_top_logprobs_probe",
        2 <= top_logprobs_k <= 20 and top_logprobs_max_tokens == 1,
        f"top_k={top_logprobs_k} max_tokens={top_logprobs_max_tokens}",
    )

    filing_url = urlparse(values.get("STATEBUS_FILING_SOURCE_BASE_URL", "").strip())
    try:
        filing_timeout_s = float(values.get("STATEBUS_FILING_HTTP_TIMEOUT_S", ""))
        filing_rate_limit_s = float(values.get("STATEBUS_FILING_RATE_LIMIT_S", ""))
        filing_max_bytes = int(values.get("STATEBUS_FILING_MAX_ARCHIVE_BYTES", ""))
    except ValueError:
        filing_timeout_s = 0.0
        filing_rate_limit_s = -1.0
        filing_max_bytes = 0
    record(
        "public_filing_source_config",
        values.get("STATEBUS_FILING_SOURCE_ID", "").strip()
        == "xbrl_international_filings"
        and filing_url.scheme == "https"
        and filing_url.hostname == "filings.xbrl.org"
        and filing_timeout_s > 0
        and filing_rate_limit_s >= 0
        and filing_max_bytes > 0,
        (
            f"source={filing_url.geturl()} timeout_s={filing_timeout_s} "
            f"rate_limit_s={filing_rate_limit_s} max_bytes={filing_max_bytes}"
        ),
    )

    config_path = Path(values.get("STATEBUS_LLM_CONFIG_FILE", ""))
    config_ok, config_detail = _validate_contest_llm_config(
        config_path=config_path,
        expected_base_url=base_url,
        expected_model=values.get("STATEBUS_LOCAL_VLLM_MODEL", "").strip(),
    )
    record("llm_config", config_ok, config_detail)

    model_path = Path(values.get("STATEBUS_VLLM_MODEL_PATH", ""))
    tokenizer_path = Path(values.get("STATEBUS_VLLM_TOKENIZER_PATH", ""))
    model_files = ("config.json", "model.safetensors.index.json")
    tokenizer_files = ("tokenizer.json", "tokenizer_config.json")
    missing_model_files = [
        name for name in model_files if not (model_path / name).is_file()
    ]
    missing_tokenizer_files = [
        name for name in tokenizer_files if not (tokenizer_path / name).is_file()
    ]
    record(
        "model_and_tokenizer_files",
        model_path.is_dir()
        and tokenizer_path.is_dir()
        and not missing_model_files
        and not missing_tokenizer_files,
        (
            f"model={model_path} tokenizer={tokenizer_path} "
            f"missing_model={missing_model_files} missing_tokenizer={missing_tokenizer_files}"
        ),
    )

    vllm_prefix = Path(values.get("STATEBUS_VLLM_ENV_PREFIX", ""))
    expected_vllm_version = values.get("STATEBUS_VLLM_EXPECTED_VERSION", "").strip()
    installed_vllm_version = _distribution_version(vllm_prefix, "vllm")
    vllm_tools_ok = all(
        path.is_file() and os.access(path, os.X_OK)
        for path in (vllm_prefix / "bin/python", vllm_prefix / "bin/vllm")
    )
    record(
        "vllm_environment",
        vllm_tools_ok
        and bool(expected_vllm_version)
        and installed_vllm_version == expected_vllm_version,
        (
            f"prefix={vllm_prefix} installed={installed_vllm_version or '<missing>'} "
            f"expected={expected_vllm_version or '<unset>'}"
        ),
    )
    record(
        "allcap_vllm_engine_profile",
        _is_enabled(values.get("STATEBUS_VLLM_EXPORT_PREFIX_COUNTERS", ""))
        and values.get("VLLM_USE_V1", "").strip() == "0"
        and values.get("STATEBUS_VLLM_MAX_LOGPROBS", "").strip() == "20"
        and _is_enabled(values.get("STATEBUS_VLLM_ENABLE_REQUEST_ID_HEADERS", "")),
        "all-cap vLLM 0.9.2 must use V0, exact prefix counters, max_logprobs=20, and request IDs",
    )
    record(
        "isolated_vllm_launch_values",
        values.get("CUDA_VISIBLE_DEVICES", "").strip()
        == values.get("STATEBUS_VLLM_CUDA_VISIBLE_DEVICES", "").strip()
        and values.get("STATEBUS_VLLM_NUM_GPU_BLOCKS_OVERRIDE", "").strip()
        == values.get("STATEBUS_CONTEST_VLLM_NUM_GPU_BLOCKS_OVERRIDE", "").strip()
        and values.get("STATEBUS_VLLM_CPU_OFFLOAD_GB", "").strip()
        == values.get("STATEBUS_CONTEST_VLLM_CPU_OFFLOAD_GB", "").strip()
        and values.get("STATEBUS_VLLM_KV_CACHE_DTYPE", "").strip()
        == values.get("STATEBUS_CONTEST_VLLM_KV_CACHE_DTYPE", "").strip(),
        (
            f"cuda={values.get('CUDA_VISIBLE_DEVICES', '<unset>')} "
            f"gpu_blocks={values.get('STATEBUS_VLLM_NUM_GPU_BLOCKS_OVERRIDE', '<unset>')} "
            f"cpu_offload={values.get('STATEBUS_VLLM_CPU_OFFLOAD_GB', '<unset>')} "
            f"kv_dtype={values.get('STATEBUS_VLLM_KV_CACHE_DTYPE', '<unset>')}"
        ),
    )

    token_path = Path(values.get("STATEBUS_LATENT_API_TOKEN_FILE", ""))
    try:
        token_mode = token_path.stat().st_mode & 0o777
        token_size = token_path.stat().st_size
    except OSError:
        token_mode = -1
        token_size = 0
    record(
        "latent_service_token",
        token_path.is_file() and token_size > 0 and token_mode == 0o600,
        f"token={token_path} size={token_size} mode={token_mode:04o}",
    )

    launcher_path = Path(values.get("STATEBUS_VLLM_START_SCRIPT", ""))
    launcher_ok, launcher_detail = _validate_allcap_launcher(launcher_path)
    record("allcap_vllm_launcher", launcher_ok, launcher_detail)

    host_prefix = Path(values.get("STATEBUS_ENV_PREFIX", ""))
    active_prefix = Path(values.get("CONDA_PREFIX", ""))
    record(
        "active_host_environment",
        (host_prefix / "bin/python").exists()
        and active_prefix.resolve(strict=False) == host_prefix.resolve(strict=False),
        f"active={active_prefix} expected={host_prefix}",
    )

    statebus_home = Path(values.get("STATEBUS_HOME", ""))
    home_dir = Path(values.get("HOME", ""))
    statebus_home_ok = (
        statebus_home.is_dir()
        and statebus_home.resolve(strict=False) != home_dir.resolve(strict=False)
        and _is_within(statebus_home, home_dir)
    )
    record(
        "user_owned_statebus_home",
        statebus_home_ok,
        f"STATEBUS_HOME={statebus_home} HOME={home_dir}",
    )

    missing_roots: list[str] = []
    unsafe_roots: list[str] = []
    for name in _CONTEST_WRITABLE_ROOTS:
        root = Path(values.get(name, ""))
        if not root.is_dir() or not os.access(root, os.W_OK | os.X_OK):
            missing_roots.append(f"{name}={root}")
        if root.resolve(strict=False) == statebus_home.resolve(
            strict=False
        ) or not _is_within(root, statebus_home):
            unsafe_roots.append(f"{name}={root}")
    record(
        "writable_user_roots",
        not missing_roots and not unsafe_roots,
        f"missing_or_readonly={missing_roots} outside_or_broad={unsafe_roots}",
    )

    compose_path = Path(values.get("STATEBUS_OPENEULER_COMPOSE_FILE", ""))
    openeuler_release = values.get("STATEBUS_OPENEULER_RELEASE", "").strip()
    openeuler_image = values.get("STATEBUS_OPENEULER_IMAGE", "").strip()
    container_uid = values.get("STATEBUS_UID", "").strip()
    container_gid = values.get("STATEBUS_GID", "").strip()
    record(
        "openeuler_descriptors",
        compose_path.is_file()
        and bool(openeuler_release)
        and bool(openeuler_image)
        and container_uid.isdigit()
        and container_gid.isdigit(),
        (
            f"compose={compose_path} release={openeuler_release} image={openeuler_image} "
            f"uid={container_uid or '<unset>'} gid={container_gid or '<unset>'}"
        ),
    )

    deferred_checks = (
        DeferredEnvironmentCheck(
            "live_metrics_schema",
            "STATEBUS_CONTEST_ALLOW_METRICS_CHECK",
            f"GET {metrics_url or '<unset>'} and validate labels/counter units",
        ),
        DeferredEnvironmentCheck(
            "top_logprobs_capability",
            "STATEBUS_CONTEST_ALLOW_TOP_LOGPROBS_PROBE",
            "send one fixed closed-set top_logprobs request",
        ),
        DeferredEnvironmentCheck(
            "public_filing_download",
            "STATEBUS_CONTEST_ALLOW_FILING_DOWNLOAD",
            "review source terms and freeze public filing hashes",
        ),
        DeferredEnvironmentCheck(
            "formal_plr_experiments",
            "STATEBUS_CONTEST_ALLOW_FORMAL_EXPERIMENTS",
            "run serialized preregistered P/L/R matrices",
        ),
        DeferredEnvironmentCheck(
            "cold_cache_and_restart",
            "STATEBUS_CONTEST_ALLOW_COLD_CACHE + STATEBUS_CONTEST_ALLOW_SERVICE_RESTART",
            "allocate a new engine epoch; no reset or restart is performed by preflight",
        ),
        DeferredEnvironmentCheck(
            "openeuler_final_validation",
            "STATEBUS_CONTEST_ALLOW_OPENEULER_VALIDATION",
            "build/run the final openEuler validation profile",
        ),
    )
    return ContestEnvironmentPreflightReport(
        profile=profile,
        phase=phase,
        checks=tuple(checks),
        deferred_checks=deferred_checks,
        metadata={
            "base_url": base_url,
            "health_url": health_url,
            "metrics_url": metrics_url,
            "model_path": str(model_path),
            "tokenizer_path": str(tokenizer_path),
            "vllm_env_prefix": str(vllm_prefix),
            "vllm_version": installed_vllm_version,
            "llm_config_file": str(config_path),
            "run_root": values.get("STATEBUS_CONTEST_RUN_ROOT", ""),
            "data_root": values.get("STATEBUS_CONTEST_DATA_ROOT", ""),
            "external_actions_performed": False,
        },
    )


def _is_disabled(value: str) -> bool:
    return str(value).strip().lower() in {"0", "false", "no", "off"}


def _is_enabled(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _csv_values(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value).split(",") if item.strip())


def _validate_local_vllm_urls(
    *,
    base_url: str,
    health_url: str,
    metrics_url: str,
) -> tuple[bool, str]:
    parsed = [urlparse(value) for value in (base_url, health_url, metrics_url)]
    paths = tuple(item.path.rstrip("/") for item in parsed)
    loopback_hosts = {"127.0.0.1", "localhost", "::1"}
    ok = (
        all(item.scheme == "http" for item in parsed)
        and all(item.hostname in loopback_hosts for item in parsed)
        and len({item.netloc for item in parsed}) == 1
        and paths == ("/v1", "/health", "/metrics")
        and all(not item.query and not item.fragment for item in parsed)
    )
    return ok, f"base={base_url} health={health_url} metrics={metrics_url}"


def _validate_contest_llm_config(
    *,
    config_path: Path,
    expected_base_url: str,
    expected_model: str,
) -> tuple[bool, str]:
    try:
        config = LLMConfig.from_file(config_path)
        provider_urls = {
            config.provider_config(role.provider).base_url
            for role in config.roles.values()
        }
        role_models = {role.model for role in config.roles.values()}
        role_request_contracts: dict[str, dict[str, object]] = {}
        for role_name, role in config.roles.items():
            chat_template_kwargs = role.extra_body.get("chat_template_kwargs")
            enable_thinking = (
                chat_template_kwargs.get("enable_thinking")
                if isinstance(chat_template_kwargs, dict)
                else None
            )
            has_reasoning_override = role.reasoning_effort is not None or any(
                key in role.request_kwargs for key in ("reasoning_effort", "extra_body")
            )
            role_request_contracts[role_name] = {
                "json_output": role.json_output,
                "temperature": role.temperature,
                "enable_thinking": enable_thinking,
                "has_reasoning_override": has_reasoning_override,
            }
        request_contract_ok = all(
            item["json_output"] is True
            and item["temperature"] == 0.0
            and item["enable_thinking"] is False
            and item["has_reasoning_override"] is False
            for item in role_request_contracts.values()
        )
        ok = (
            config.mode == "local_vllm"
            and provider_urls == {expected_base_url}
            and role_models == {expected_model}
            and request_contract_ok
            and all(
                provider.request_max_attempts == 1
                for provider in config.providers.values()
            )
        )
        return (
            ok,
            (
                f"path={config_path} mode={config.mode} urls={provider_urls} "
                f"models={role_models} role_request_contracts={role_request_contracts}"
            ),
        )
    except Exception as exc:
        return False, f"unable to load contest LLM config {config_path}: {exc}"


def _distribution_version(prefix: Path, distribution: str) -> str:
    pattern = f"{distribution.replace('-', '_')}-*.dist-info/METADATA"
    metadata_files = sorted(prefix.glob(f"lib/python*/site-packages/{pattern}"))
    for metadata_path in metadata_files:
        try:
            metadata = Parser().parsestr(metadata_path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if metadata.get("Name", "").strip().lower().replace(
            "-", "_"
        ) == distribution.lower().replace("-", "_"):
            return metadata.get("Version", "").strip()
    return ""


def _validate_allcap_launcher(launcher_path: Path) -> tuple[bool, str]:
    try:
        content = launcher_path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"unable to read launcher {launcher_path}: {exc}"
    required = (
        "--enable-prefix-caching",
        "--enable-prompt-embeds",
        "--disable-frontend-multiprocessing",
        "--worker-extension-cls",
        "--middleware",
        "--max-logprobs",
        "--enable-request-id-headers",
        "scripts/vllm_exporter",
    )
    missing = [item for item in required if item not in content]
    ok = launcher_path.is_file() and os.access(launcher_path, os.X_OK) and not missing
    return (
        ok,
        f"launcher={launcher_path} missing_required_flags={missing}",
    )


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True
