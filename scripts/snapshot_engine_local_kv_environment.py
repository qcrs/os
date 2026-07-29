#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any
from urllib.request import urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Snapshot the existing 53334 service before the KV maintenance window."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--service-command", default="")
    parser.add_argument("--gpu-line", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=args.update)
    service_command = args.service_command or _command(
        "pgrep",
        "-af",
        "/home/qcrs/statebus/conda-envs/vllm-qwen-cu121/bin/vllm serve /data/models/Qwen3-32B",
    )
    metrics = _url_text("http://127.0.0.1:53334/metrics")
    payload: dict[str, Any] = {
        "schema_version": "statebus.engine_local_kv_service_snapshot.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "service_endpoint": "http://127.0.0.1:53334",
        "service_command": service_command.splitlines(),
        "health_body": _url_text("http://127.0.0.1:53334/health"),
        "models": _json_or_text(_url_text("http://127.0.0.1:53334/v1/models")),
        "selected_metrics": _selected_metrics(metrics),
        "gpu_snapshot": args.gpu_line
        or _command(
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ).splitlines(),
        "container": _command(
            "docker",
            "inspect",
            "statebus-dev-qcrs",
            "--format",
            "{{.Image}} {{.Config.Image}} {{.HostConfig.NetworkMode}}",
        ),
        "model_identity": _command(
            "sha256sum",
            "/data/models/Qwen3-32B/config.json",
            "/data/models/Qwen3-32B/model.safetensors.index.json",
            "/data/models/Qwen3-32B/tokenizer_config.json",
            "/data/models/Qwen3-32B/tokenizer.json",
        ).splitlines(),
        "git_branch": _command("git", "branch", "--show-current"),
        "git_commit": _command("git", "rev-parse", "HEAD"),
        "git_status": _command("git", "status", "--short").splitlines(),
        "rollback": {
            "repo": "/home/qcrs/statebus/work/statebus-v2-contest-rebuild",
            "profile": "deploy/activate_statebus_vllm_allcap.sh",
            "manager": "scripts/manage_vllm_qwen3_32b_allcap.sh",
            "command": "source deploy/activate_statebus_vllm_allcap.sh && bash scripts/manage_vllm_qwen3_32b_allcap.sh start",
            "physical_gpu": 1,
        },
    }
    _write_json(args.output_dir / "latent_service_snapshot.json", payload)
    (args.output_dir / "metrics_before.prom").write_text(metrics, encoding="utf-8")
    (args.output_dir / "rollback_command.txt").write_text(
        payload["rollback"]["command"] + "\n", encoding="utf-8"
    )
    print(args.output_dir)
    return 0


def _command(*command: str) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    output = completed.stdout.strip()
    if completed.returncode and not output:
        output = completed.stderr.strip()
    return output


def _url_text(url: str) -> str:
    with urlopen(url, timeout=10) as response:
        return response.read().decode("utf-8")


def _json_or_text(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _selected_metrics(metrics: str) -> dict[str, float]:
    wanted = {
        "vllm:num_requests_running",
        "vllm:num_requests_waiting",
        "vllm:gpu_cache_usage_perc",
        "vllm:prompt_tokens_total",
        "vllm:generation_tokens_total",
    }
    selected: dict[str, float] = {}
    for line in metrics.splitlines():
        if not line or line.startswith("#"):
            continue
        name = line.partition("{")[0].partition(" ")[0]
        if name not in wanted:
            continue
        try:
            selected[name] = float(line.rsplit(" ", 1)[1])
        except (IndexError, ValueError):
            continue
    return selected


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
