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
        description="Snapshot the existing service before the KV maintenance window."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:53334")
    parser.add_argument("--container", default="statebus-dev-qcrs")
    parser.add_argument(
        "--model-path",
        type=Path,
        default=Path("/data/models/Qwen3-32B"),
    )
    parser.add_argument(
        "--service-pattern",
        default="vllm serve /data/models/Qwen3-32B",
    )
    parser.add_argument("--service-command", default="")
    parser.add_argument("--gpu-line", action="append", default=[])
    parser.add_argument("--physical-gpu", type=int, default=1)
    parser.add_argument(
        "--git-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
    )
    parser.add_argument(
        "--rollback-command",
        default="",
        help="Exact command used to restore the pre-maintenance service.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=args.update)
    service_command = args.service_command or _command(
        "pgrep",
        "-af",
        args.service_pattern,
    )
    metrics = _url_text(f"{args.base_url}/metrics")
    payload: dict[str, Any] = {
        "schema_version": "statebus.engine_local_kv_service_snapshot.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "service_endpoint": args.base_url,
        "service_command": service_command.splitlines(),
        "health_body": _url_text(f"{args.base_url}/health"),
        "models": _json_or_text(_url_text(f"{args.base_url}/v1/models")),
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
            args.container,
            "--format",
            "{{.Image}} {{.Config.Image}} {{.HostConfig.NetworkMode}}",
        ),
        "model_identity": _command(
            "sha256sum",
            str(args.model_path / "config.json"),
            str(args.model_path / "model.safetensors.index.json"),
            str(args.model_path / "tokenizer_config.json"),
            str(args.model_path / "tokenizer.json"),
        ).splitlines(),
        "git_root": str(args.git_root.resolve()),
        "git_branch": _command(
            "git", "-C", str(args.git_root), "branch", "--show-current"
        ),
        "git_commit": _command("git", "-C", str(args.git_root), "rev-parse", "HEAD"),
        "git_status": _command(
            "git", "-C", str(args.git_root), "status", "--short"
        ).splitlines(),
        "rollback": {
            "repo": str(args.git_root.resolve()),
            "command": args.rollback_command,
            "command_recorded": bool(args.rollback_command),
            "physical_gpu": args.physical_gpu,
        },
    }
    _write_json(args.output_dir / "service_snapshot.json", payload)
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
