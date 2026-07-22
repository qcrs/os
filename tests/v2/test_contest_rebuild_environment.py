from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from v2.runtime.preflight import contest_environment_preflight


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_executable(
    path: Path, content: str = "#!/usr/bin/env bash\nexit 0\n"
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _prepared_environment(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    statebus_home = home / "statebus"
    host_prefix = statebus_home / "conda-envs/statebus_host"
    vllm_prefix = statebus_home / "conda-envs/vllm-qwen-cu121"
    model_path = tmp_path / "models/Qwen3-32B"

    _write_executable(host_prefix / "bin/python")
    _write_executable(vllm_prefix / "bin/python")
    _write_executable(vllm_prefix / "bin/vllm")
    metadata = (
        vllm_prefix / "lib/python3.11/site-packages/vllm-0.9.2.dist-info/METADATA"
    )
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text("Name: vllm\nVersion: 0.9.2\n", encoding="utf-8")
    model_path.mkdir(parents=True)
    for filename in (
        "config.json",
        "model.safetensors.index.json",
        "tokenizer.json",
        "tokenizer_config.json",
    ):
        (model_path / filename).write_text("{}\n", encoding="utf-8")
    token_path = statebus_home / "work/latent_api.token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("test-token\n", encoding="utf-8")
    token_path.chmod(0o600)

    roots = {
        "STATEBUS_CACHES_DIR": statebus_home / "caches",
        "STATEBUS_RUNS_DIR": statebus_home / "runs",
        "STATEBUS_LOGS_DIR": statebus_home / "logs",
        "STATEBUS_WORKDIR": statebus_home / "work",
        "STATEBUS_CONTEST_DATA_ROOT": statebus_home / "work/contest-rebuild/data",
        "STATEBUS_CONTEST_RUN_ROOT": statebus_home / "runs/contest-rebuild-v1",
        "STATEBUS_CONTEST_LOG_ROOT": statebus_home / "logs/contest-rebuild-v1",
        "STATEBUS_FILING_DOWNLOAD_ROOT": statebus_home
        / "caches/contest-rebuild/public-filings/raw",
        "STATEBUS_FILING_CANONICAL_ROOT": statebus_home
        / "work/contest-rebuild/data/public-filings/canonical",
        "STATEBUS_FILING_PRIVATE_GOLD_ROOT": statebus_home
        / "work/contest-rebuild/gold-private",
        "STATEBUS_OPENEULER_VALIDATION_ROOT": statebus_home
        / "runs/contest-rebuild-v1/openeuler-final",
    }
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)

    env = {
        "HOME": str(home),
        "STATEBUS_HOME": str(statebus_home),
        "STATEBUS_ENV_PREFIX": str(host_prefix),
        "CONDA_PREFIX": str(host_prefix),
        "STATEBUS_CONTEST_PROFILE": "contest-rebuild-20260722",
        "STATEBUS_CONTEST_PROFILE_VERSION": "1",
        "STATEBUS_CONTEST_PROFILE_PHASE": "prepare",
        "STATEBUS_LOCAL_VLLM_BASE_URL": "http://127.0.0.1:53334/v1",
        "STATEBUS_LOCAL_VLLM_HEALTH_URL": "http://127.0.0.1:53334/health",
        "STATEBUS_VLLM_METRICS_URL": "http://127.0.0.1:53334/metrics",
        "STATEBUS_VLLM_METRIC_QUERY_NAMES": (
            "vllm:prefix_cache_queries_total,vllm_prefix_cache_queries_total"
        ),
        "STATEBUS_VLLM_METRIC_HIT_NAMES": (
            "vllm:prefix_cache_hits_total,vllm_prefix_cache_hits_total"
        ),
        "STATEBUS_VLLM_METRICS_SCHEMA_STATUS": "pending_live_check",
        "STATEBUS_TOP_LOGPROBS_CAPABILITY_STATUS": "pending_live_check",
        "STATEBUS_TOP_LOGPROBS_PROBE_TOP_K": "5",
        "STATEBUS_TOP_LOGPROBS_PROBE_MAX_TOKENS": "1",
        "STATEBUS_LLM_CONFIG_FILE": str(
            REPO_ROOT / "deploy/statebus_llm.contest_rebuild.yaml"
        ),
        "STATEBUS_LOCAL_VLLM_MODEL": "qwen3-32b",
        "STATEBUS_VLLM_MODEL_PATH": str(model_path),
        "STATEBUS_VLLM_TOKENIZER_PATH": str(model_path),
        "STATEBUS_VLLM_ENV_PREFIX": str(vllm_prefix),
        "STATEBUS_VLLM_EXPECTED_VERSION": "0.9.2",
        "STATEBUS_VLLM_EXPORT_PREFIX_COUNTERS": "1",
        "STATEBUS_VLLM_MAX_LOGPROBS": "20",
        "STATEBUS_VLLM_ENABLE_REQUEST_ID_HEADERS": "1",
        "STATEBUS_VLLM_CUDA_VISIBLE_DEVICES": "1",
        "CUDA_VISIBLE_DEVICES": "1",
        "STATEBUS_VLLM_NUM_GPU_BLOCKS_OVERRIDE": "",
        "STATEBUS_VLLM_CPU_OFFLOAD_GB": "",
        "STATEBUS_VLLM_KV_CACHE_DTYPE": "",
        "STATEBUS_CONTEST_VLLM_NUM_GPU_BLOCKS_OVERRIDE": "",
        "STATEBUS_CONTEST_VLLM_CPU_OFFLOAD_GB": "",
        "STATEBUS_CONTEST_VLLM_KV_CACHE_DTYPE": "",
        "VLLM_USE_V1": "0",
        "STATEBUS_LATENT_API_TOKEN_FILE": str(token_path),
        "STATEBUS_VLLM_START_SCRIPT": str(
            REPO_ROOT / "scripts/start_vllm_qwen3_32b_latent.sh"
        ),
        "STATEBUS_PREFIX_POLICY": "off",
        "STATEBUS_PREFIX_LAYOUT_VERSION": "v2",
        "STATEBUS_PREFIX_REQUIRE_EXCLUSIVE_METRICS": "true",
        "STATEBUS_PREFIX_FEEDBACK_ADAPTIVE": "0",
        "STATEBUS_PREFIX_ALIGNMENT_MODE": "independent",
        "STATEBUS_PREFIX_CACHE_NAMESPACE": "",
        "STATEBUS_PREFIX_CACHE_EPOCH": "",
        "STATEBUS_LOGIT_POLICY": "off",
        "STATEBUS_LOGIT_DECISION_TYPE": "executor_tool_recipe_choice_v1",
        "STATEBUS_LOGIT_MAX_ACTIONS": "1",
        "STATEBUS_LATENT_MODE": "off",
        "STATEBUS_LATENT_HANDOFF_MODE": "off",
        "STATEBUS_LATENT_PROMPT_EMBEDS_ENABLED": "false",
        "STATEBUS_FORMAL_REQUEST_MODE": "serialized",
        "STATEBUS_FORMAL_REQUEST_CONCURRENCY": "1",
        "STATEBUS_FILING_SOURCE_ID": "xbrl_international_filings",
        "STATEBUS_FILING_SOURCE_BASE_URL": "https://filings.xbrl.org",
        "STATEBUS_FILING_HTTP_TIMEOUT_S": "30",
        "STATEBUS_FILING_RATE_LIMIT_S": "1.0",
        "STATEBUS_FILING_MAX_ARCHIVE_BYTES": "536870912",
        "STATEBUS_OPENEULER_COMPOSE_FILE": str(REPO_ROOT / "docker/compose.yaml"),
        "STATEBUS_OPENEULER_RELEASE": "24.03-lts-sp3",
        "STATEBUS_OPENEULER_IMAGE": "statebus-dev-openeuler:24.03-lts-sp3-core",
        "STATEBUS_UID": "1000",
        "STATEBUS_GID": "1000",
    }
    env.update({name: str(path) for name, path in roots.items()})
    for gate in (
        "STATEBUS_CONTEST_ALLOW_METRICS_CHECK",
        "STATEBUS_CONTEST_ALLOW_TOP_LOGPROBS_PROBE",
        "STATEBUS_CONTEST_ALLOW_FILING_DOWNLOAD",
        "STATEBUS_CONTEST_ALLOW_FORMAL_EXPERIMENTS",
        "STATEBUS_CONTEST_ALLOW_COLD_CACHE",
        "STATEBUS_CONTEST_ALLOW_SERVICE_RESTART",
        "STATEBUS_CONTEST_ALLOW_OPENEULER_VALIDATION",
    ):
        env[gate] = "0"
    return env


def test_contest_environment_preflight_passes_without_live_actions(
    tmp_path: Path,
) -> None:
    report = contest_environment_preflight(_prepared_environment(tmp_path))

    assert report.ok is True
    assert report.missing_reasons == ()
    assert report.canonical_payload()["offline_only"] is True
    assert report.metadata["external_actions_performed"] is False
    assert {item.name for item in report.deferred_checks} == {
        "live_metrics_schema",
        "top_logprobs_capability",
        "public_filing_download",
        "formal_plr_experiments",
        "cold_cache_and_restart",
        "openeuler_final_validation",
    }


@pytest.mark.parametrize(
    ("name", "value", "failed_check"),
    [
        ("STATEBUS_LATENT_HANDOFF_MODE", "native", "latent_disabled"),
        ("STATEBUS_PREFIX_POLICY", "on", "treatments_disabled"),
        ("STATEBUS_LOGIT_POLICY", "gated", "treatments_disabled"),
        (
            "STATEBUS_CONTEST_ALLOW_TOP_LOGPROBS_PROBE",
            "1",
            "external_action_gates_disabled",
        ),
        ("STATEBUS_PREFIX_CACHE_EPOCH", "stale-epoch", "prefix_preparation_guardrails"),
        ("STATEBUS_FORMAL_REQUEST_CONCURRENCY", "2", "serialized_formal_requests"),
    ],
)
def test_contest_environment_preflight_rejects_unsafe_preparation_values(
    name: str,
    value: str,
    failed_check: str,
    tmp_path: Path,
) -> None:
    env = _prepared_environment(tmp_path)
    env[name] = value

    report = contest_environment_preflight(env)

    assert report.ok is False
    assert any(check.name == failed_check and not check.ok for check in report.checks)


def test_contest_environment_preflight_rejects_cross_service_metrics_url(
    tmp_path: Path,
) -> None:
    env = _prepared_environment(tmp_path)
    env["STATEBUS_VLLM_METRICS_URL"] = "http://127.0.0.1:8000/metrics"

    report = contest_environment_preflight(env)

    assert report.ok is False
    assert any(
        check.name == "local_vllm_urls" and not check.ok for check in report.checks
    )


def test_contest_environment_preflight_rejects_thinking_enabled(
    tmp_path: Path,
) -> None:
    env = _prepared_environment(tmp_path)
    config_path = tmp_path / "thinking-enabled.yaml"
    config_text = (REPO_ROOT / "deploy/statebus_llm.contest_rebuild.yaml").read_text(
        encoding="utf-8"
    )
    config_path.write_text(
        config_text.replace("enable_thinking: false", "enable_thinking: true", 1),
        encoding="utf-8",
    )
    env["STATEBUS_LLM_CONFIG_FILE"] = str(config_path)

    report = contest_environment_preflight(env)

    assert report.ok is False
    assert any(check.name == "llm_config" and not check.ok for check in report.checks)


def test_contest_activation_resets_old_profile_values(tmp_path: Path) -> None:
    home = tmp_path / "home"
    conda_base = tmp_path / "conda-base"
    fake_conda = conda_base / "bin/conda"
    conda_sh = conda_base / "etc/profile.d/conda.sh"
    _write_executable(
        fake_conda,
        f"#!/usr/bin/env bash\nprintf '%s\\n' '{conda_base}'\n",
    )
    conda_sh.parent.mkdir(parents=True, exist_ok=True)
    conda_sh.write_text(
        "conda() {\n"
        '  if [[ "$1" == "activate" ]]; then\n'
        '    export CONDA_PREFIX="$2"\n'
        "    return 0\n"
        "  fi\n"
        "  return 1\n"
        "}\n",
        encoding="utf-8",
    )
    env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "CONDA_EXE": str(fake_conda),
        "STATEBUS_LLM_ENV_FILE": str(tmp_path / "missing-llm.env"),
        "STATEBUS_CONTEST_ENV_FILE": str(tmp_path / "missing-contest.env"),
        "STATEBUS_VLLM_MODEL_PATH": "/old/8b",
        "STATEBUS_VLLM_START_SCRIPT": "/old/latent-launcher.sh",
        "STATEBUS_PREFIX_POLICY": "on",
        "STATEBUS_LOGIT_POLICY": "gated",
        "STATEBUS_LATENT_MODE": "native",
        "STATEBUS_LATENT_HANDOFF_MODE": "native",
        "STATEBUS_LATENT_PROMPT_EMBEDS_ENABLED": "true",
        "VLLM_USE_V1": "0",
        "CUDA_VISIBLE_DEVICES": "9",
        "STATEBUS_VLLM_NUM_GPU_BLOCKS_OVERRIDE": "573",
        "STATEBUS_VLLM_CPU_OFFLOAD_GB": "8",
        "STATEBUS_VLLM_KV_CACHE_DTYPE": "fp8",
        "STATEBUS_PREFIX_ALIGNMENT_MODE": "shared_evidence_prefix",
    }
    command = """
set -euo pipefail
source deploy/activate_statebus_contest_rebuild.sh >/dev/null
printf '%s\n' \
  "$STATEBUS_CONTEST_PROFILE" \
  "$STATEBUS_VLLM_MODEL_PATH" \
  "$STATEBUS_LOCAL_VLLM_BASE_URL" \
  "$STATEBUS_VLLM_METRICS_URL" \
  "${STATEBUS_VLLM_START_SCRIPT##*/}" \
  "$CUDA_VISIBLE_DEVICES/$STATEBUS_VLLM_NUM_GPU_BLOCKS_OVERRIDE/$STATEBUS_VLLM_CPU_OFFLOAD_GB/$STATEBUS_VLLM_KV_CACHE_DTYPE" \
  "$STATEBUS_PREFIX_POLICY/$STATEBUS_LOGIT_POLICY/$STATEBUS_LATENT_MODE" \
  "$STATEBUS_PREFIX_ALIGNMENT_MODE" \
  "$STATEBUS_LATENT_HANDOFF_MODE/$STATEBUS_LATENT_PROMPT_EMBEDS_ENABLED" \
  "$STATEBUS_VLLM_EXPORT_PREFIX_COUNTERS/$VLLM_USE_V1" \
  "$STATEBUS_CONTEST_ALLOW_FORMAL_EXPERIMENTS"
"""

    result = subprocess.run(
        ["bash", "-c", command],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    lines = result.stdout.splitlines()
    assert lines == [
        "contest-rebuild-20260722",
        "/data/models/Qwen3-32B",
        "http://127.0.0.1:53334/v1",
        "http://127.0.0.1:53334/metrics",
        "start_vllm_qwen3_32b_latent.sh",
        "1///",
        "off/off/off",
        "independent",
        "off/false",
        "1/0",
        "0",
    ]
    assert (home / "statebus/runs/contest-rebuild-v1").is_dir()
    assert (home / "statebus/work/contest-rebuild/gold-private").is_dir()
