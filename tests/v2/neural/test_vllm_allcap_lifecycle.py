from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_allcap_activation_ignores_stale_generic_vllm_values(tmp_path: Path) -> None:
    env = {
        "HOME": str(tmp_path),
        "PATH": os.environ["PATH"],
        "STATEBUS_VLLM_MODEL_PATH": "/stale/model",
        "STATEBUS_VLLM_PORT": "9999",
        "STATEBUS_VLLM_EXPORT_PREFIX_COUNTERS": "0",
        "VLLM_USE_V1": "1",
    }
    command = """
source deploy/activate_statebus_vllm_allcap.sh
printf '%s\n' \
  "$STATEBUS_VLLM_SERVICE_NAME" \
  "$STATEBUS_VLLM_CAPABILITY_PROFILE" \
  "$STATEBUS_VLLM_MODEL_PATH" \
  "$STATEBUS_VLLM_PORT" \
  "$CUDA_VISIBLE_DEVICES" \
  "$STATEBUS_VLLM_MAX_LOGPROBS" \
  "$STATEBUS_VLLM_EXPORT_PREFIX_COUNTERS/$VLLM_USE_V1" \
  "$VLLM_NO_USAGE_STATS" \
  "$STATEBUS_VLLM_ENABLE_REQUEST_ID_HEADERS" \
  "$STATEBUS_LATENT_ALIGNMENT_DIAGNOSTICS" \
  "$STATEBUS_VLLM_PID_FILE" \
  "$STATEBUS_VLLM_LOG_FILE"
"""
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )

    assert result.stdout.splitlines() == [
        "statebus-vllm-qwen3-32b-allcap",
        "qwen3-32b-allcap-v0",
        "/data/models/Qwen3-32B",
        "53334",
        "1",
        "20",
        "1/0",
        "1",
        "1",
        "true",
        str(tmp_path / "statebus/work/statebus-vllm-qwen3-32b-allcap.pid"),
        str(tmp_path / "statebus/logs/statebus-vllm-qwen3-32b-allcap.log"),
    ]


def test_allcap_manager_uses_bounded_identity_and_nohup() -> None:
    manager = (REPO_ROOT / "scripts/manage_vllm_qwen3_32b_allcap.sh").read_text(
        encoding="utf-8"
    )

    assert "nohup bash" in manager
    assert "process_matches_identity" in manager
    assert "STATEBUS_VLLM_MODEL_PATH" in manager
    assert "STATEBUS_VLLM_PORT" in manager
    assert "kill -TERM" in manager
    assert "kill -KILL" in manager
    assert "pkill" not in manager


def test_allcap_manager_rejects_unknown_command_without_live_action() -> None:
    result = subprocess.run(
        ["bash", "scripts/manage_vllm_qwen3_32b_allcap.sh", "unknown"],
        cwd=REPO_ROOT,
        env={"HOME": os.environ["HOME"], "PATH": os.environ["PATH"]},
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 2
    assert "{check|start|stop|restart|status}" in result.stderr


def test_allcap_manager_matches_the_exact_managed_process_identity() -> None:
    fake_env = os.environ.copy()
    fake_env.update(
        {
            "STATEBUS_VLLM_EXPORT_PREFIX_COUNTERS": "1",
            "VLLM_USE_V1": "0",
            "STATEBUS_VLLM_SERVICE_NAME": "statebus-vllm-qwen3-32b-allcap",
            "STATEBUS_LATENT_ALIGNMENT_DIAGNOSTICS": "true",
            "CUDA_VISIBLE_DEVICES": "1",
        }
    )
    fake_process = subprocess.Popen(
        [
            "bash",
            "-c",
            "while :; do sleep 1; done",
            "/home/qcrs/statebus/conda-envs/vllm-qwen-cu121/bin/vllm",
            "serve",
            "/data/models/Qwen3-32B",
            "--port",
            "53334",
            "--enable-prefix-caching",
            "--enable-prompt-embeds",
            "--disable-frontend-multiprocessing",
            "--worker-extension-cls",
            "v2.integrations.vllm_latent.worker_extension.LatentWorkerExtension",
            "--middleware",
            "v2.integrations.vllm_latent.middleware.LatentHandoffMiddleware",
            "--max-logprobs",
            "20",
            "--enable-request-id-headers",
        ],
        env=fake_env,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        checker_env = {
            "HOME": os.environ["HOME"],
            "PATH": os.environ["PATH"],
            "STATEBUS_TEST_PID": str(fake_process.pid),
        }
        result = subprocess.run(
            [
                "bash",
                "-c",
                "source scripts/manage_vllm_qwen3_32b_allcap.sh; "
                'process_matches_identity "$STATEBUS_TEST_PID"; '
                'process_is_allcap "$STATEBUS_TEST_PID"',
            ],
            cwd=REPO_ROOT,
            env=checker_env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert result.returncode == 0, result.stderr

        wrong_gpu_env = checker_env | {"STATEBUS_ALLCAP_VLLM_CUDA_VISIBLE_DEVICES": "0"}
        wrong_gpu_result = subprocess.run(
            [
                "bash",
                "-c",
                "source scripts/manage_vllm_qwen3_32b_allcap.sh; "
                'process_matches_identity "$STATEBUS_TEST_PID"; '
                'process_is_allcap "$STATEBUS_TEST_PID"',
            ],
            cwd=REPO_ROOT,
            env=wrong_gpu_env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert wrong_gpu_result.returncode != 0
    finally:
        os.killpg(fake_process.pid, signal.SIGKILL)
        fake_process.wait(timeout=5)
