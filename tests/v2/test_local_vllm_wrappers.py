from __future__ import annotations

import os
from pathlib import Path
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
        ["scripts/run_v2_local_vllm_formal_suite.sh"],
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
