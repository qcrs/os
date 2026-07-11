#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

try:
    import yaml
except ImportError:  # pragma: no cover - host env normally includes PyYAML.
    yaml = None  # type: ignore[assignment]


OUTPUT_PATH = Path(
    "docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/"
    "local_vllm_kv_audit_20260711.json"
)

RUN_ROOTS = (
    Path("/home/qcrs/statebus/runs/sb32bcompact"),
    Path("/home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-gpu0-mini5-20260710_2234"),
    Path("/home/qcrs/statebus/runs/sb32bformal900"),
    Path("/home/qcrs/statebus/runs/sb32bformal3k"),
    Path("/home/qcrs/statebus/runs/sb32bcap3k"),
    Path("/home/qcrs/statebus/runs/sb32bformalx4k"),
    Path("/home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-gpu0-formal-20260710_2250"),
    Path("/home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-gpu0-formal-timeout900-20260711_0015"),
)
LOGS_ROOT = Path("/home/qcrs/statebus/logs")

AF_UNIX_SOCKET_PATH_MAX_BYTES = 107
MAX_SCAN_FILE_BYTES = 2_000_000
MAX_SNIPPETS_PER_RUN = 40
MAX_SNIPPETS_PER_FILE = 8
MAX_LOG_FILES_LISTED = 200

FAILURE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("traceback", re.compile(r"Traceback \(most recent call last\)", re.IGNORECASE)),
    ("bad_request_error", re.compile(r"BadRequestError", re.IGNORECASE)),
    ("api_timeout_error", re.compile(r"APITimeoutError|ReadTimeout|timed out", re.IGNORECASE)),
    ("af_unix_path_too_long", re.compile(r"AF_UNIX path too long|path too long", re.IGNORECASE)),
    ("invalid_json", re.compile(r"invalid JSON|JSONDecodeError|Expecting value", re.IGNORECASE)),
    ("maximum_context_length", re.compile(r"maximum context length", re.IGNORECASE)),
    ("truncated_json", re.compile(r"truncated JSON|Unterminated string|unterminated", re.IGNORECASE)),
    ("error", re.compile(r"\b(?:Error|Exception)\b")),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit local vLLM / KV run artifacts.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--metrics-url", default="http://127.0.0.1:53334/metrics")
    parser.add_argument("--health-url", default="http://127.0.0.1:53334/health")
    parser.add_argument("--timeout-s", type=float, default=5.0)
    args = parser.parse_args()

    runs = [audit_run(path) for path in RUN_ROOTS]
    logs_audit = scan_logs_root(LOGS_ROOT)
    vllm_service = probe_vllm_service(
        health_url=args.health_url,
        metrics_url=args.metrics_url,
        timeout_s=args.timeout_s,
    )
    payload = {
        "schema_version": "statebus.local_vllm_kv_audit.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "run_roots": [str(path) for path in RUN_ROOTS],
            "logs_root": str(LOGS_ROOT),
            "health_url": args.health_url,
            "metrics_url": args.metrics_url,
        },
        "claim_boundary": (
            "audit_evidence_only_no_true_kv_tensor_transfer_claim; "
            "prefix/cache metrics are reported only when exposed by the current vLLM endpoint"
        ),
        "runs": runs,
        "global_logs": logs_audit,
        "vllm_service": vllm_service,
        "aggregate": aggregate_runs(runs),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0


def audit_run(run_root: Path) -> dict[str, Any]:
    summary_path = run_root / "formal_suite.summary.json"
    stdout_path = run_root / "formal_suite.stdout.json"
    config_path = run_root / "statebus_llm.local_vllm.yaml"

    summary = load_json_document(summary_path)
    stdout = load_json_document(stdout_path)
    config = load_yaml_document(config_path)
    reports = load_benchmark_reports(run_root)
    snippets = scan_failure_snippets(run_root)
    socket_audit = socket_path_audit(run_root.name)

    payload_source = choose_payload_source(summary, stdout)
    fields = extract_run_fields(payload_source["payload"], reports)
    attribution = attribute_failure(
        run_id=run_root.name,
        summary=summary,
        stdout=stdout,
        config=config,
        reports=reports,
        snippets=snippets,
        socket_audit=socket_audit,
        fields=fields,
    )

    return {
        "run_id": run_root.name,
        "run_root": str(run_root),
        "exists": run_root.exists(),
        "summary": document_status(summary),
        "stdout": document_status(stdout),
        "statebus_llm_config": config_summary(config_path, config),
        "payload_source": payload_source["source"],
        "selected_case_count": fields["selected_case_count"],
        "available_case_count": fields["available_case_count"],
        "layers": fields["layers"],
        "comparison_summary": fields["comparison_summary"],
        "metadata": fields["metadata"],
        "benchmark_reports": reports,
        "socket_path_audit": socket_audit,
        "failure_snippets": snippets,
        "failure_attribution": attribution,
    }


def load_json_document(path: Path) -> dict[str, Any]:
    status: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": 0,
        "json_ok": False,
        "parse_error": "",
        "payload": None,
    }
    if not path.exists():
        status["parse_error"] = "missing"
        return status
    status["size_bytes"] = path.stat().st_size
    if status["size_bytes"] == 0:
        status["parse_error"] = "empty"
        return status
    try:
        status["payload"] = json.loads(path.read_text(encoding="utf-8"))
        status["json_ok"] = True
    except Exception as exc:  # noqa: BLE001 - audit records parse failures.
        status["parse_error"] = f"{type(exc).__name__}: {exc}"
    return status


def load_yaml_document(path: Path) -> dict[str, Any]:
    status: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": 0,
        "yaml_ok": False,
        "parse_error": "",
        "payload": {},
    }
    if not path.exists():
        status["parse_error"] = "missing"
        return status
    status["size_bytes"] = path.stat().st_size
    if yaml is None:
        status["parse_error"] = "PyYAML unavailable"
        return status
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        status["payload"] = parsed if isinstance(parsed, dict) else {}
        status["yaml_ok"] = True
    except Exception as exc:  # noqa: BLE001
        status["parse_error"] = f"{type(exc).__name__}: {exc}"
    return status


def document_status(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": document["path"],
        "exists": document["exists"],
        "size_bytes": document["size_bytes"],
        "json_ok": document["json_ok"],
        "complete_json": bool(document["json_ok"]),
        "parse_error": document["parse_error"],
    }


def choose_payload_source(summary: dict[str, Any], stdout: dict[str, Any]) -> dict[str, Any]:
    if summary["json_ok"]:
        return {"source": "summary", "payload": summary["payload"]}
    if stdout["json_ok"]:
        return {"source": "stdout", "payload": stdout["payload"]}
    return {"source": "none", "payload": {}}


def extract_run_fields(payload: Any, reports: list[dict[str, Any]]) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    layers = extract_layers(data)
    if not layers:
        layers = extract_layers_from_reports(reports)
    comparison_summary = data.get("comparison_summary", {})
    metadata = data.get("metadata", {})
    return {
        "selected_case_count": data.get("selected_case_count"),
        "available_case_count": data.get("available_case_count"),
        "layers": layers,
        "comparison_summary": comparison_summary if isinstance(comparison_summary, dict) else {},
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


def extract_layers(data: dict[str, Any]) -> list[dict[str, Any]]:
    layers = data.get("layers", [])
    extracted: list[dict[str, Any]] = []
    if isinstance(layers, list):
        for item in layers:
            if not isinstance(item, dict):
                continue
            metrics = item.get("aggregated_metrics", item)
            metrics = metrics if isinstance(metrics, dict) else {}
            extracted.append(
                {
                    "layer": item.get("layer"),
                    "case_count": metrics.get("case_count"),
                    "quality_floor_pass_count": metrics.get("quality_floor_pass_count"),
                    "source": "payload.layers",
                }
            )
    return extracted


def extract_layers_from_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    layers: list[dict[str, Any]] = []
    for report in reports:
        metrics = report.get("aggregated_metrics", {})
        if not isinstance(metrics, dict):
            continue
        layer = report.get("layer") or infer_layer_from_name(str(report.get("path", "")))
        layers.append(
            {
                "layer": layer,
                "case_count": metrics.get("case_count"),
                "quality_floor_pass_count": metrics.get("quality_floor_pass_count"),
                "source": "benchmark_report",
                "path": report.get("path"),
            }
        )
    return sorted(layers, key=lambda item: str(item.get("layer", "")))


def load_benchmark_reports(run_root: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    if not run_root.exists():
        return reports
    for path in sorted(run_root.glob("runtime/**/benchmark_reports/*.json")):
        document = load_json_document(path)
        payload = document.get("payload") if document.get("json_ok") else {}
        payload = payload if isinstance(payload, dict) else {}
        cases = payload.get("cases", [])
        reports.append(
            {
                "path": str(path),
                "json_ok": bool(document["json_ok"]),
                "parse_error": document["parse_error"],
                "suite_id": payload.get("suite_id"),
                "layer": payload.get("layer") or infer_layer_from_name(path.name),
                "case_count": len(cases) if isinstance(cases, list) else None,
                "aggregated_metrics": payload.get("aggregated_metrics"),
                "metadata": payload.get("metadata"),
                "comparison_summary": payload.get("comparison_summary"),
            }
        )
    return reports


def infer_layer_from_name(name: str) -> str:
    match = re.search(r"(?:^|-)(L[0-3])(?:\.|-)", name)
    return match.group(1) if match else ""


def scan_failure_snippets(root: Path) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    if not root.exists():
        return snippets
    for path in iter_candidate_text_files(root):
        snippets.extend(scan_file_for_failure_snippets(path))
        if len(snippets) >= MAX_SNIPPETS_PER_RUN:
            return snippets[:MAX_SNIPPETS_PER_RUN]
    return snippets


def iter_candidate_text_files(root: Path) -> list[Path]:
    suffixes = {".json", ".jsonl", ".log", ".txt", ".out", ".err", ".stdout", ".stderr", ".yaml", ".yml"}
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in suffixes and "stdout" not in path.name and "stderr" not in path.name:
            continue
        if "memory_index" in path.parts:
            continue
        files.append(path)
    files.sort(key=lambda item: (0 if item.name.startswith("formal_suite") else 1, len(item.parts), str(item)))
    return files


def scan_file_for_failure_snippets(path: Path) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    try:
        raw = path.read_bytes()[:MAX_SCAN_FILE_BYTES]
    except OSError:
        return snippets
    if not raw:
        return snippets
    text = raw.decode("utf-8", errors="replace")
    for line_no, line in enumerate(text.splitlines(), start=1):
        matches = [name for name, pattern in FAILURE_PATTERNS if pattern.search(line)]
        if not matches:
            continue
        snippets.append(
            {
                "path": str(path),
                "line": line_no,
                "categories": matches,
                "text": line[:700],
            }
        )
        if len(snippets) >= MAX_SNIPPETS_PER_FILE:
            break
    return snippets


def socket_path_audit(run_id: str) -> dict[str, Any]:
    container_path = f"/statebus/runs/{run_id}/control.sock"
    host_path = f"/home/qcrs/statebus/runs/{run_id}/control.sock"
    return {
        "container_socket_path": container_path,
        "container_socket_path_bytes": len(container_path.encode("utf-8")),
        "host_socket_path": host_path,
        "host_socket_path_bytes": len(host_path.encode("utf-8")),
        "af_unix_limit_bytes": AF_UNIX_SOCKET_PATH_MAX_BYTES,
        "container_path_within_limit": len(container_path.encode("utf-8")) <= AF_UNIX_SOCKET_PATH_MAX_BYTES,
        "host_path_within_limit": len(host_path.encode("utf-8")) <= AF_UNIX_SOCKET_PATH_MAX_BYTES,
    }


def config_summary(path: Path, config: dict[str, Any]) -> dict[str, Any]:
    payload = config.get("payload", {})
    payload = payload if isinstance(payload, dict) else {}
    providers = payload.get("providers", {})
    default_provider = providers.get("default", {}) if isinstance(providers, dict) else {}
    roles_payload = payload.get("roles", {})
    roles = roles_payload if isinstance(roles_payload, dict) else {}
    role_summary = {}
    for role_name, role_config in roles.items():
        role_config = role_config if isinstance(role_config, dict) else {}
        role_summary[role_name] = {
            "model": role_config.get("model"),
            "max_tokens": role_config.get("max_tokens"),
            "max_context_tokens": role_config.get("max_context_tokens"),
            "max_context_safety_margin_tokens": role_config.get("max_context_safety_margin_tokens"),
            "json_output": role_config.get("json_output"),
        }
    return {
        "path": str(path),
        "exists": config["exists"],
        "yaml_ok": config["yaml_ok"],
        "parse_error": config["parse_error"],
        "mode": payload.get("mode"),
        "base_url": default_provider.get("base_url") if isinstance(default_provider, dict) else None,
        "timeout_s": default_provider.get("timeout_s") if isinstance(default_provider, dict) else None,
        "request_max_attempts": (
            default_provider.get("request_max_attempts") if isinstance(default_provider, dict) else None
        ),
        "roles": role_summary,
    }


def attribute_failure(
    *,
    run_id: str,
    summary: dict[str, Any],
    stdout: dict[str, Any],
    config: dict[str, Any],
    reports: list[dict[str, Any]],
    snippets: list[dict[str, Any]],
    socket_audit: dict[str, Any],
    fields: dict[str, Any],
) -> dict[str, Any]:
    categories = {category for snippet in snippets for category in snippet["categories"]}
    signals: list[str] = []
    types: list[str] = []
    final_pass = is_final_pass(fields)
    if final_pass:
        types.append("final pass")
        signals.append("all extracted L0-L3 layers have case_count=25 and quality_floor_pass_count=25")

    config_payload = config.get("payload", {}) if isinstance(config.get("payload"), dict) else {}
    timeout_s = extract_provider_timeout(config_payload)
    executor_config = extract_role_config(config_payload, "executor")
    summarizer_config = extract_role_config(config_payload, "summarizer")
    executor_max_tokens = safe_int(executor_config.get("max_tokens"))
    executor_context_cap = safe_int(executor_config.get("max_context_tokens"))
    summarizer_max_tokens = safe_int(summarizer_config.get("max_tokens"))
    summary_missing = not summary["json_ok"]
    stdout_empty = stdout["exists"] and int(stdout["size_bytes"] or 0) == 0
    partial_reports = bool(reports) and summary_missing

    if "api_timeout_error" in categories:
        types.append("wrapper timeout or API timeout")
        signals.append("timeout-related failure snippet found")
    if timeout_s == 120 and summary_missing and stdout_empty:
        types.append("wrapper timeout 120s")
        signals.append("config timeout_s=120 and wrapper stdout is empty with no summary JSON")
    if partial_reports and timeout_s and timeout_s > 120 and summary_missing:
        types.append("partial formal run without suite summary")
        signals.append(f"benchmark reports exist but top-level summary is missing; timeout_s={timeout_s}")

    if "af_unix_path_too_long" in categories or not socket_audit["container_path_within_limit"]:
        types.append("AF_UNIX path too long")
        signals.append("AF_UNIX/path-too-long snippet found or container socket path exceeds limit")

    if "bad_request_error" in categories or "maximum_context_length" in categories:
        types.append("vLLM context 400")
        signals.append("BadRequestError/maximum context length snippet found")
    elif executor_max_tokens and executor_max_tokens >= 4096 and not executor_context_cap and summary_missing:
        types.append("vLLM context 400 risk")
        signals.append("executor max_tokens >= 4096 without context cap and no suite summary was produced")

    if "truncated_json" in categories or "invalid_json" in categories:
        role_hint = infer_role_from_snippets(snippets)
        if role_hint == "executor":
            types.append("executor JSON truncation")
            signals.append("JSON failure snippet references executor context")
        elif role_hint == "summarizer":
            types.append("summarizer JSON truncation")
            signals.append("JSON failure snippet references summarizer context")
        else:
            types.append("JSON truncation or invalid JSON")
            signals.append("JSON failure snippet found without a clear role")
    elif summary_missing and executor_context_cap and executor_max_tokens and executor_max_tokens >= 3000:
        types.append("executor JSON truncation risk reduced by context cap")
        signals.append("context cap present with large executor max_tokens, but no direct JSON snippet found")
    if summary_missing and summarizer_max_tokens and summarizer_max_tokens <= 1024 and executor_context_cap:
        types.append("summarizer JSON truncation risk")
        signals.append("summarizer max_tokens <= 1024 after context-cap runs and no suite summary was produced")

    if summary_missing and stdout_empty and not types:
        types.append("unattributed empty wrapper stdout")
        signals.append("formal_suite.stdout.json is empty and no direct failure snippet was found")

    return {
        "types": dedupe(types),
        "signals": dedupe(signals),
        "direct_snippet_categories": sorted(categories),
        "evidence_strength": "direct" if categories else ("inferred" if types else "none"),
    }


def is_final_pass(fields: dict[str, Any]) -> bool:
    layers = fields.get("layers", [])
    if len(layers) < 4:
        return False
    by_layer = {item.get("layer"): item for item in layers if isinstance(item, dict)}
    for layer in ("L0", "L1", "L2", "L3"):
        item = by_layer.get(layer, {})
        if safe_int(item.get("case_count")) != 25:
            return False
        if safe_int(item.get("quality_floor_pass_count")) != 25:
            return False
    return True


def extract_provider_timeout(config_payload: dict[str, Any]) -> int | None:
    providers = config_payload.get("providers", {})
    if not isinstance(providers, dict):
        return None
    default_provider = providers.get("default", {})
    if not isinstance(default_provider, dict):
        return None
    return safe_int(default_provider.get("timeout_s"))


def extract_role_config(config_payload: dict[str, Any], role: str) -> dict[str, Any]:
    roles = config_payload.get("roles", {})
    if not isinstance(roles, dict):
        return {}
    role_config = roles.get(role, {})
    return role_config if isinstance(role_config, dict) else {}


def safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def infer_role_from_snippets(snippets: list[dict[str, Any]]) -> str:
    text = "\n".join(f"{snippet.get('path', '')} {snippet.get('text', '')}" for snippet in snippets).lower()
    if "executor" in text or "step-execute" in text:
        return "executor"
    if "summarizer" in text or "summary" in text:
        return "summarizer"
    return ""


def dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def scan_logs_root(logs_root: Path) -> dict[str, Any]:
    files = sorted(path for path in logs_root.rglob("*") if path.is_file()) if logs_root.exists() else []
    snippets: list[dict[str, Any]] = []
    for path in files[:MAX_LOG_FILES_LISTED]:
        snippets.extend(scan_file_for_failure_snippets(path))
        if len(snippets) >= MAX_SNIPPETS_PER_RUN:
            break
    return {
        "logs_root": str(logs_root),
        "exists": logs_root.exists(),
        "file_count": len(files),
        "files_sample": [str(path) for path in files[:MAX_LOG_FILES_LISTED]],
        "failure_snippets": snippets[:MAX_SNIPPETS_PER_RUN],
    }


def probe_vllm_service(*, health_url: str, metrics_url: str, timeout_s: float) -> dict[str, Any]:
    health = fetch_url(health_url, timeout_s=timeout_s)
    metrics = fetch_url(metrics_url, timeout_s=timeout_s)
    parsed_metrics = parse_prefix_cache_metrics(metrics.get("body", "") if metrics["ok"] else "")
    return {
        "health": {
            "url": health_url,
            "ok": health["ok"],
            "status_code": health["status_code"],
            "body_sample": health["body"][:500],
            "error": health["error"],
        },
        "metrics": {
            "url": metrics_url,
            "ok": metrics["ok"],
            "status_code": metrics["status_code"],
            "error": metrics["error"],
            "prefix_cache_metric_status": parsed_metrics["status"],
            "raw_metric_values": parsed_metrics["raw_metric_values"],
            "raw_metric_lines": parsed_metrics["raw_metric_lines"],
            "raw_metric_names": sorted(parsed_metrics["raw_metric_values"]),
            "claim_boundary": "raw_metrics_only_no_hit_miss_claim_without_explicit_exposed_counters",
        },
    }


def fetch_url(url: str, *, timeout_s: float) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=timeout_s) as response:  # nosec B310 - local audit endpoint.
            body = response.read().decode("utf-8", errors="replace")
            return {
                "ok": 200 <= int(response.status) < 400,
                "status_code": int(response.status),
                "body": body,
                "error": "",
            }
    except URLError as exc:
        return {"ok": False, "status_code": None, "body": "", "error": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status_code": None, "body": "", "error": f"{type(exc).__name__}: {exc}"}


def parse_prefix_cache_metrics(metrics_text: str) -> dict[str, Any]:
    values: dict[str, float] = {}
    lines: list[str] = []
    for raw_line in metrics_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        metric_name = line.split("{", 1)[0].split(" ", 1)[0]
        if not re.search(r"(prefix|cache|kv)", metric_name, re.IGNORECASE):
            continue
        lines.append(line)
        value_text = line.rsplit(" ", 1)[-1]
        try:
            values[metric_name] = float(value_text)
        except ValueError:
            continue
    if values:
        status = "prefix/cache/kv metrics exposed"
    elif metrics_text:
        status = "metrics available but no prefix-cache metric exposed"
    else:
        status = "metrics unavailable or no prefix-cache metric exposed"
    return {"status": status, "raw_metric_values": values, "raw_metric_lines": lines}


def aggregate_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    final_pass_runs = [
        run["run_id"]
        for run in runs
        if "final pass" in run.get("failure_attribution", {}).get("types", [])
    ]
    attribution_counts: dict[str, int] = {}
    for run in runs:
        for failure_type in run.get("failure_attribution", {}).get("types", []):
            attribution_counts[failure_type] = attribution_counts.get(failure_type, 0) + 1
    return {
        "run_count": len(runs),
        "final_pass_runs": final_pass_runs,
        "attribution_counts": attribution_counts,
    }


if __name__ == "__main__":
    raise SystemExit(main())
