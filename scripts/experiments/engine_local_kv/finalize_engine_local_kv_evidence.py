#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from statebus.benchmark.engine_local_kv_experiment import A_LANE, B_LANE, DEFAULT_LANE_ORDER
from statebus.utils import sha256_digest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit and finalize an engine-local KV evidence bundle."
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--git-root", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--container", default="statebus-vllm-kv-probe")
    parser.add_argument("--base-url", default="http://127.0.0.1:53334")
    parser.add_argument("--gpu-line", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = args.run_dir / "manifest.json"
    manifest = _read_json(manifest_path)
    summary = _read_json(args.run_dir / "summary.json")
    records = _read_jsonl(args.run_dir / "records.jsonl")
    warmups = _read_jsonl(args.run_dir / "warmup_records.jsonl")
    git_status = _git(args.git_root, "status", "--short").splitlines()
    git_branch = _git(args.git_root, "branch", "--show-current")
    git_commit = _git(args.git_root, "rev-parse", "HEAD")
    token = _read_token(args.token_file)
    health = _request_json(
        f"{args.base_url}/statebus/kv/health",
        authorization=f"Bearer {token}",
    )
    metrics = _request_text(f"{args.base_url}/metrics")
    inspect_value = _command_json("docker", "inspect", args.container)
    inspect_payload = inspect_value[0] if isinstance(inspect_value, list) else {}
    device_requests = inspect_payload.get("HostConfig", {}).get("DeviceRequests") or []
    raw_outputs = sorted((args.run_dir / "raw" / "outputs").glob("*.json"))
    raw_errors = sorted((args.run_dir / "raw" / "stderr").glob("*.txt"))
    expected_formal = len(summary.get("by_case", {})) * len(DEFAULT_LANE_ORDER)
    expected_warmups = len(summary.get("by_case", {})) * 2
    checks = {
        "manifest_complete": manifest.get("status") == "complete",
        "formal_record_count": len(records) == expected_formal == 18,
        "warmup_record_count": len(warmups) == expected_warmups == 6,
        "raw_output_count": len(raw_outputs) == len(records) + len(warmups),
        "raw_error_count_zero": not raw_errors,
        "all_formal_success": all(bool(record.get("success")) for record in records),
        "all_warmup_success": all(bool(record.get("success")) for record in warmups),
        "fixed_lane_order": _fixed_lane_order(records),
        "all_b_released": all(
            record.get("release_status") == "released"
            for record in records
            if record.get("lane") == B_LANE
        ),
        "summary_digest": manifest.get("summary_digest") == sha256_digest(summary),
        "pair_count_nine": summary.get("total", {}).get("pair_count") == 9,
        "pair_logical_digest_match": _pair_count_matches(
            summary, "pair_digest_match_count"
        ),
        "pair_first_token_match": _pair_count_matches(
            summary, "pair_first_output_token_match_count"
        ),
        "pair_output_token_match": _pair_count_matches(
            summary, "pair_output_token_digest_match_count"
        ),
        "pair_producer_token_match": _pair_count_matches(
            summary, "pair_producer_output_token_digest_match_count"
        ),
        "health_ready": health.get("status") == "ready",
        "automatic_prefix_caching_disabled": health.get(
            "automatic_prefix_caching"
        )
        is False,
        "registry_empty": health.get("registry_entries") == 0
        and health.get("registry_bytes") == 0,
        "physical_gpu_one_only": _physical_gpu_one_only(device_requests),
    }
    finalized_at = datetime.now(timezone.utc).isoformat()
    original_git = {
        "git_branch": manifest.get("git_branch", ""),
        "git_commit": manifest.get("git_commit", ""),
        "dirty_worktree": manifest.get("dirty_worktree", False),
        "git_status": manifest.get("git_status", []),
    }
    manifest.update(
        {
            "git_branch": git_branch,
            "git_commit": git_commit,
            "dirty_worktree": bool(git_status),
            "git_status": git_status,
            "git_identity_source": str(args.git_root),
            "git_identity_repaired_at": finalized_at,
            "git_identity_before_repair": original_git,
            "evidence_audit_passed": all(checks.values()),
            "evidence_finalized_at": finalized_at,
        }
    )
    digest_payload = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    manifest["manifest_digest"] = sha256_digest(digest_payload)
    _write_json(manifest_path, manifest)
    audit = {
        "schema_version": "statebus.engine_local_kv_evidence_audit.v1",
        "run_id": manifest.get("run_id", ""),
        "finalized_at": finalized_at,
        "passed": all(checks.values()),
        "checks": checks,
        "formal_record_count": len(records),
        "warmup_record_count": len(warmups),
        "raw_output_count": len(raw_outputs),
        "raw_error_files": [str(path) for path in raw_errors],
        "git_branch": git_branch,
        "git_commit": git_commit,
        "dirty_worktree": bool(git_status),
        "post_run_health": health,
        "device_requests": device_requests,
        "gpu_line": args.gpu_line,
        "summary_digest": sha256_digest(summary),
        "manifest_digest": manifest["manifest_digest"],
        "token_value_recorded": False,
    }
    _write_json(args.run_dir / "evidence_audit.json", audit)
    _write_json(args.run_dir / "post_run_health.json", health)
    (args.run_dir / "post_run_metrics.prom").write_text(metrics, encoding="utf-8")
    (args.run_dir / "kv_service_full.log").write_text(
        _command_combined_text("docker", "logs", "--timestamps", args.container),
        encoding="utf-8",
    )
    _write_csv(args.run_dir / "records.csv", records)
    print(json.dumps({"passed": audit["passed"], "checks": checks}, sort_keys=True))
    return 0 if audit["passed"] else 2


def _fixed_lane_order(records: list[dict[str, Any]]) -> bool:
    case_ids = list(dict.fromkeys(str(record.get("case_id", "")) for record in records))
    return all(
        tuple(
            str(record.get("lane", ""))
            for record in records
            if record.get("case_id") == case_id
        )
        == DEFAULT_LANE_ORDER
        for case_id in case_ids
    )


def _pair_count_matches(summary: Mapping[str, Any], key: str) -> bool:
    total = summary.get("total", {})
    return isinstance(total, Mapping) and total.get(key) == total.get("pair_count") == 9


def _physical_gpu_one_only(device_requests: Any) -> bool:
    return (
        isinstance(device_requests, list)
        and len(device_requests) == 1
        and device_requests[0].get("DeviceIDs") == ["1"]
    )


def _git(root: Path, *args: str) -> str:
    return _command_text("git", "-C", str(root), *args).strip()


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
    return json.loads(_command_text(*command))


def _command_text(*command: str) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise SystemExit(completed.stderr.strip() or "command failed")
    return completed.stdout


def _command_combined_text(*command: str) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise SystemExit(completed.stderr.strip() or "command failed")
    return completed.stdout + completed.stderr


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"expected object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if not all(isinstance(value, dict) for value in values):
        raise SystemExit(f"expected JSON objects: {path}")
    return values


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fieldnames = list(dict.fromkeys(key for record in records for key in record))
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=True, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in record.items()
                }
            )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
