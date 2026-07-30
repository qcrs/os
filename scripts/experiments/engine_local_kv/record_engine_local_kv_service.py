#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any
from urllib.request import Request, urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record the live engine-local KV service launch evidence."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--container", default="statebus-vllm-kv-probe")
    parser.add_argument("--base-url", default="http://127.0.0.1:53334")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    token = _read_token(args.token_file)
    inspect_payload = _command_json("docker", "inspect", args.container)
    if not isinstance(inspect_payload, list) or len(inspect_payload) != 1:
        raise SystemExit("KV service container inspect failed")
    health = _request_json(
        f"{args.base_url}/statebus/kv/health",
        authorization=f"Bearer {token}",
    )
    models = _request_json(f"{args.base_url}/v1/models")
    metrics = _request_text(f"{args.base_url}/metrics")
    manifest: dict[str, Any] = {
        "schema_version": "statebus.engine_local_kv_service_launch.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "container_name": args.container,
        "container_id": str(inspect_payload[0].get("Id", "")),
        "container_image": str(inspect_payload[0].get("Image", "")),
        "container_config_image": str(
            inspect_payload[0].get("Config", {}).get("Image", "")
        ),
        "container_path": str(inspect_payload[0].get("Path", "")),
        "container_args": list(inspect_payload[0].get("Args", [])),
        "device_requests": list(
            inspect_payload[0].get("HostConfig", {}).get("DeviceRequests") or []
        ),
        "network_mode": str(
            inspect_payload[0].get("HostConfig", {}).get("NetworkMode", "")
        ),
        "readonly_mounts": [
            {
                "source": value.get("Source", ""),
                "destination": value.get("Destination", ""),
                "rw": bool(value.get("RW", False)),
            }
            for value in inspect_payload[0].get("Mounts", [])
        ],
        "health": health,
        "models": models,
        "selected_metrics": _selected_metrics(metrics),
        "automatic_prefix_caching": health.get("automatic_prefix_caching"),
        "physical_gpu": 1,
        "container_visible_gpu_count": 1,
        "client_endpoint": args.base_url,
        "token_file_path": str(args.token_file),
        "token_value_recorded": False,
    }
    digest = hashlib.sha256(
        json.dumps(
            manifest,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    manifest["launch_manifest_digest"] = digest
    _write_json(args.output_dir / "kv_service_launch_manifest.json", manifest)
    (args.output_dir / "kv_service_metrics_before.prom").write_text(
        metrics, encoding="utf-8"
    )
    logs = _command_text("docker", "logs", args.container)
    (args.output_dir / "kv_service_startup.log").write_text(logs, encoding="utf-8")
    print(digest)
    return 0


def _read_token(path: Path) -> str:
    metadata = path.stat()
    if metadata.st_mode & 0o077:
        raise SystemExit("token file permissions are too broad")
    value = path.read_text(encoding="utf-8").strip()
    if not value or any(character.isspace() for character in value):
        raise SystemExit("token file is invalid")
    return value


def _request_text(url: str, *, authorization: str = "") -> str:
    headers = {"authorization": authorization} if authorization else {}
    with urlopen(Request(url, headers=headers), timeout=15) as response:
        return response.read().decode("utf-8")


def _request_json(url: str, *, authorization: str = "") -> dict[str, Any]:
    value = json.loads(_request_text(url, authorization=authorization))
    if not isinstance(value, dict):
        raise SystemExit(f"expected object response from {url}")
    return value


def _command_json(*command: str) -> Any:
    value = _command_text(*command)
    return json.loads(value)


def _command_text(*command: str) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise SystemExit(completed.stderr.strip() or "command failed")
    return completed.stdout


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
