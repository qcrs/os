from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess


def test_formal_suite_rejects_overlong_container_socket_path_before_container(
    tmp_path: Path,
) -> None:
    run_id = "x" * 120
    env = os.environ.copy()
    env.update(
        {
            "STATEBUS_HOST_RUNS_ROOT": str(tmp_path / "runs"),
            "STATEBUS_CONTAINER_RUNS_ROOT": "/statebus/runs",
            "STATEBUS_LOCAL_VLLM_FORMAL_RUN_ID": run_id,
        }
    )

    result = subprocess.run(
        ["scripts/run_local_vllm_formal_suite.sh"],
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 2
    assert "AF_UNIX path too long" in result.stderr
    assert "shorten STATEBUS_LOCAL_VLLM_FORMAL_RUN_ID" in result.stderr
    assert "statebus-local-vllm-check" not in result.stdout
    assert "statebus-local-vllm-check" not in result.stderr


def test_real_embedding_recommended_uses_selected_8b_profile(tmp_path: Path) -> None:
    source_root = Path(__file__).resolve().parents[1]
    os_root = tmp_path / "os"
    scripts = os_root / "scripts"
    scripts.mkdir(parents=True)
    wrapper = scripts / "run_g6b2_real_embedding.sh"
    shutil.copy2(source_root / "scripts" / wrapper.name, wrapper)

    live_runner = scripts / "run_g6b2_live.sh"
    live_runner.write_text(
        """#!/usr/bin/env bash
printf 'live_args=%s\\n' "$*"
printf 'llm_config=%s\\n' "$STATEBUS_LLM_CONFIG_FILE"
printf 'container_llm_config=%s\\n' "$STATEBUS_CONTAINER_LLM_CONFIG_FILE"
""",
        encoding="utf-8",
    )
    container_runner = scripts / "run_g6b2_os_container.sh"
    container_runner.write_text(
        """#!/usr/bin/env bash
if [[ "$1" == "exec" ]]; then
  printf 'container_exec=%s\\n' "$*"
  printf 'container_llm_config=%s\\n' "$STATEBUS_CONTAINER_LLM_CONFIG_FILE"
fi
""",
        encoding="utf-8",
    )
    live_runner.chmod(0o755)
    container_runner.chmod(0o755)

    minimal_root = tmp_path / "minimal"
    minimal_root.mkdir()
    env = os.environ.copy()
    env["STATEBUS_LOCAL_VLLM_MODEL"] = "qwen3-8b"
    result = subprocess.run(
        [str(wrapper), "recommended", "--minimal-evidence-root", str(minimal_root)],
        cwd=os_root,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    assert "--service-runtime-dir /home/qcrs/statebus/work/vllm-qwen3-8b-gpu0-u050" in result.stdout
    expected_config = "/workspace/statebus/os/deploy/statebus_llm.g6b2-qwen3-8b.example"
    assert f"llm_config={expected_config}" in result.stdout
    assert f"container_llm_config={expected_config}" in result.stdout


def test_local_vllm_container_check_is_loopback_only_and_uses_os_root() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_local_vllm_container_check.sh"
    ).read_text(encoding="utf-8")

    assert 'CONTAINER_PROJECT_ROOT="${STATEBUS_CONTAINER_PROJECT_ROOT:-/workspace/statebus/os}"' in source
    assert '"$mapper" map-path "$HOST_RUNS_ROOT"' in source
    assert 'ProxyHandler({})' in source
    assert "-e HTTP_PROXY=" in source
    assert "-e HTTPS_PROXY=" in source
    assert "-e ALL_PROXY=" in source
    assert 'LOCAL_NO_PROXY="127.0.0.1,localhost,::1"' in source
