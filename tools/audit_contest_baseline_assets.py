#!/usr/bin/env python3
"""Create a content-addressed inventory of StateBus contest experiment artifacts.

The audit deliberately separates artifact discovery from claim making.  It
indexes every reachable file, records unreadable paths, parses every JSON or
JSONL document that can be read, and extracts log events without silently
discarding failed or diagnostic runs.

It is intended for evidence review, not for running benchmarks. It only reads
the artifact root and writes a new audit directory chosen by the caller. With
``--hash-files``, every reachable source file is content-addressed; raw
artifacts remain in place rather than being silently copied or rewritten.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Iterator


DEFAULT_ARTIFACT_ROOT = Path(
    "/home/qcrs/statebus/runs/contest_evidence_closure_20260720"
)

CANONICAL_RUNS = {
    "e0_focused_20260720_142422": "E0 focused tests and preflight",
    "e1_causal_serial_20260720_150801": "E1 causal L0-L3 matrix",
    "e2_stress_serial_20260720_152924": "E2 two-family long horizon",
    "e3_adaptive_memory_final_20260720_160244": "E3 adaptive memory loop",
    "e4_semantic_holdout_final4_20260720_175430": "E4 semantic holdout",
    "e5_adaptive_final_20260720_190107": "E5 adaptive/CodeAct",
    "e6_full_final_20260720_201043": "E6 full regression",
}

KNOWN_NONCANONICAL = {
    "focused_20260720_140122": "failed focused baseline",
    "causal_20260720_142709": "overlapping passing causal run",
    "e1_causal_20260720_143554": "interrupted causal run",
    "stress_20260720_145740": "interrupted stress run",
    "e3_adaptive_memory_serial_20260720_154048": "memory negative-gate failure",
    "e4_semantic_holdout_serial_20260720_170818": "semantic holdout retry",
    "e4_semantic_holdout_final_20260720_172250": "semantic holdout retry",
    "e4_semantic_holdout_final2_20260720_173344": "semantic holdout retry",
    "e4_semantic_holdout_final3_20260720_174324": "semantic holdout retry",
    "e5_adaptive_serial_20260720_180846": "adaptive 24/25 retry",
    "e5_formal_agg_002_probe_20260720_185808": "single-case diagnostic",
    "e6_full_serial_20260720_195042": "full regression retry",
    "e6_memory_slice_probe_20260720_200735": "memory-input diagnostic",
    "phase5_focused_20260720_140910": "focused retry",
    "phase5_focused_20260720_142012": "focused follow-up",
}

KNOWN_PRECANONICAL = {
    "baseline_20260720_104220": "pre-closure baseline artifact",
    "focused_20260720_141403": "intermediate focused retry",
    "phase3_focused_20260720_134402": "pre-closure phase-3 focused run",
    "phase3_focused_20260720_134510": "pre-closure phase-3 focused retry",
    "phase3_long_horizon_20260720_130858": "pre-closure phase-3 long-horizon run",
    "phase4_focused_20260720_134913": "pre-closure phase-4 focused run",
    "e3_adaptive_memory_rerun_20260720_155247": "intermediate adaptive-memory retry",
}

AUDIT_CATEGORIES = (
    "case_reports",
    "role_requests",
    "state_consumption",
    "memory_queries",
    "memory_consumption",
    "replay_decisions",
    "artifact_lineage",
)

ROOT_FILE_CATEGORIES = {
    "summary.json": "summary",
    "summary.md": "summary_markdown",
    "run_manifest.json": "run_manifest",
    "fairness_manifest.json": "fairness_manifest",
    "environment.json": "environment",
    "checksums.sha256": "checksums",
    "pytest.log": "pytest_log",
    "console.log": "console_log",
    "wrapper.log": "wrapper_log",
}

SCALAR_FIELDS = (
    "schema_version",
    "ok",
    "exit_status",
    "exit_code",
    "stage",
    "suite",
    "suite_id",
    "experiment_id",
    "task_id",
    "task_family",
    "family_id",
    "lane",
    "layer",
    "round_view",
    "role_path_mode",
    "embedding_mode",
    "executor_transport",
    "state_pool_mode_requested",
    "storage_kind",
    "control_carrier",
    "replay_class",
    "consumption_mode",
    "compatibility_verdict",
    "decision_reason",
    "quality_pass_count",
    "case_count",
    "attempted_case_count",
    "serial_execution",
    "comparison_valid",
    "formal_headline_eligible",
    "stability_evidence_eligible",
    "headline_eligible",
    "benchmark_oracle_visible_to_roles",
    "producer_pid",
    "consumer_pid",
)

METRIC_CONTAINER_KEYS = {
    "metrics",
    "telemetry_summary",
    "waterfall_metrics",
    "task_metrics",
    "comparison_summary",
}

LOG_SUFFIXES = {".log", ".txt", ".out", ".err", ".stdout", ".stderr"}
JSON_SUFFIXES = {".json", ".jsonl"}

START_RE = re.compile(r"\bSTART\s+(?P<stage>[^:]+):")
END_RE = re.compile(
    r"\bEND\s+(?P<stage>[^:]+):\s+exit=(?P<exit>-?\d+)(?:\s+elapsed_s=(?P<elapsed>[0-9.]+))?"
)
PYTEST_RE = re.compile(
    r"(?P<passed>\d+)\s+passed(?:,\s*(?P<failed>\d+)\s+failed)?(?:,\s*(?P<skipped>\d+)\s+skipped)?"
)
ERROR_RE = re.compile(r"\b(?:ERROR|Error|FAILED|FAIL|Traceback|Exception|SIGTERM|exit=[1-9-])\b")
WARNING_RE = re.compile(r"\b(?:WARNING|Warning|DeprecationWarning|ResourceWarning)\b")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _safe_text(value: Any, limit: int = 240) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return None


def _scalar_key(value: Any) -> str | None:
    value = _safe_text(value)
    if value is None:
        return None
    return str(value)


def _classify_group(name: str) -> tuple[str, str]:
    if name == "__root__":
        return "root_metadata", "files directly under the artifact root"
    if name in CANONICAL_RUNS:
        return "canonical", CANONICAL_RUNS[name]
    if name in KNOWN_NONCANONICAL:
        return "known_noncanonical", KNOWN_NONCANONICAL[name]
    if name in KNOWN_PRECANONICAL:
        return "precanonical", KNOWN_PRECANONICAL[name]
    if name.startswith(
        (
            "fresh-",
            "development-",
            "targeted-",
            "full-adaptive-",
            "focused-m2-",
            "focused-memory-",
        )
    ):
        return "later_or_development", "not a canonical 2026-07-20 E0-E6 run"
    if re.match(r"^(phase\d+|focused|causal|stress|e\d+_)", name):
        return "unclassified_experiment", "experiment-like root absent from canonical index"
    return "unclassified", "no canonical classification inferred"


def _category(relative: Path) -> str:
    if relative.name in ROOT_FILE_CATEGORIES:
        return ROOT_FILE_CATEGORIES[relative.name]
    for component in relative.parts:
        if component in AUDIT_CATEGORIES:
            return component
    if relative.suffix == ".json":
        return "json_other"
    if relative.suffix == ".jsonl":
        return "jsonl_other"
    if relative.suffix in LOG_SUFFIXES:
        return "log_other"
    return "other"


def _find_values(value: Any, field: str, limit: int = 12) -> list[Any]:
    found: list[Any] = []
    stack: list[Any] = [value]
    while stack and len(found) < limit:
        current = stack.pop()
        if isinstance(current, dict):
            for key, item in current.items():
                if key == field and isinstance(item, (str, int, float, bool)):
                    found.append(item)
                    if len(found) >= limit:
                        break
                elif isinstance(item, (dict, list)):
                    stack.append(item)
        elif isinstance(current, list):
            stack.extend(item for item in current if isinstance(item, (dict, list)))
    return found


def _schema_paths(
    value: Any,
    prefix: str = "$",
    depth: int = 0,
    node_limit: int = 20_000,
) -> tuple[Counter[str], bool]:
    paths: Counter[str] = Counter()
    stack: list[tuple[Any, str, int]] = [(value, prefix, depth)]
    seen = 0
    truncated = False
    while stack:
        current, current_prefix, current_depth = stack.pop()
        seen += 1
        if seen > node_limit or current_depth > 18:
            truncated = True
            break
        if isinstance(current, dict):
            for key, item in current.items():
                next_prefix = f"{current_prefix}.{key}"
                paths[f"{next_prefix}::{type(item).__name__}"] += 1
                if isinstance(item, (dict, list)):
                    stack.append((item, next_prefix, current_depth + 1))
        elif isinstance(current, list):
            for item in current:
                next_prefix = f"{current_prefix}[]"
                paths[f"{next_prefix}::{type(item).__name__}"] += 1
                if isinstance(item, (dict, list)):
                    stack.append((item, next_prefix, current_depth + 1))
    return paths, truncated


def _numeric_metrics(value: Any) -> dict[str, float]:
    metrics: dict[str, float] = {}
    if not isinstance(value, dict):
        return metrics

    def visit(current: Any, prefix: str) -> None:
        if isinstance(current, dict):
            for key, item in current.items():
                next_prefix = f"{prefix}.{key}" if prefix else key
                if isinstance(item, bool):
                    continue
                if isinstance(item, (int, float)):
                    metrics[next_prefix] = float(item)
                elif isinstance(item, dict):
                    visit(item, next_prefix)
                elif isinstance(item, list):
                    # Lists often contain vector payloads. Descend only into
                    # object records, retaining named scalar metrics but not
                    # exploding arrays of numeric state values into the index.
                    for list_item in item:
                        if isinstance(list_item, dict):
                            visit(list_item, f"{next_prefix}[]")

    # Historical artifacts do not consistently nest numbers beneath a single
    # "metrics" key. Named numeric leaves are therefore indexed everywhere;
    # the inventory labels their aggregate as a discovery aid, not a claim.
    visit(value, "")
    return metrics


def _project_json(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"root_type": type(value).__name__}
    projection: dict[str, Any] = {
        "root_type": "dict",
        "top_level_keys": sorted(value),
    }
    fields: dict[str, list[Any]] = {}
    for field in SCALAR_FIELDS:
        found = [_safe_text(item) for item in _find_values(value, field)]
        found = [item for item in found if item is not None]
        if found:
            fields[field] = found
    if fields:
        projection["selected_fields"] = fields
    metrics = _numeric_metrics(value)
    if metrics:
        projection["numeric_metrics"] = metrics
    schema_paths, schema_truncated = _schema_paths(value)
    projection["schema_paths"] = dict(schema_paths)
    projection["schema_paths_truncated"] = schema_truncated
    return projection


def _register_schema(
    catalog: dict[str, dict[str, Any]],
    schema_paths: dict[str, int],
) -> str | None:
    """Store each distinct structural shape once and return its stable ID."""
    if not schema_paths:
        return None
    encoded = json.dumps(schema_paths, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    schema_id = f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"
    entry = catalog.setdefault(
        schema_id,
        {
            "schema_paths": schema_paths,
            "document_count": 0,
        },
    )
    entry["document_count"] += 1
    return schema_id


def _compact_document_projection(
    projection: dict[str, Any],
    schema_id: str | None,
) -> dict[str, Any]:
    """Keep document-specific facts while putting repeated shapes in a catalog."""
    compact = {
        key: value
        for key, value in projection.items()
        if key != "schema_paths"
    }
    if schema_id:
        compact["schema_id"] = schema_id
    return compact


def _read_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle), None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _read_jsonl(path: Path) -> tuple[dict[str, Any], str | None]:
    line_count = 0
    valid_count = 0
    errors: list[dict[str, Any]] = []
    schemas: Counter[str] = Counter()
    fields: Counter[str] = Counter()
    scalar_value_counts: dict[str, Counter[str]] = defaultdict(Counter)
    numeric_metric_stats: dict[str, dict[str, float]] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                line_count += 1
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    value = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    errors.append({"line": line_no, "error": str(exc)})
                    continue
                valid_count += 1
                projection = _project_json(value)
                for path_key, count in projection.get("schema_paths", {}).items():
                    fields[path_key] += count
                selected = projection.get("selected_fields", {})
                for schema in selected.get("schema_version", []):
                    schemas[str(schema)] += 1
                for field, values in selected.items():
                    for item in values:
                        key = _scalar_key(item)
                        if key is not None:
                            scalar_value_counts[field][key] += 1
                _increment_numeric_stats(
                    numeric_metric_stats,
                    projection.get("numeric_metrics", {}),
                )
    except (OSError, UnicodeDecodeError) as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    return {
        "line_count": line_count,
        "valid_json_count": valid_count,
        "invalid_json_count": len(errors),
        "parse_errors": errors,
        "schema_versions": dict(schemas),
        "schema_paths": dict(fields),
        "scalar_value_counts": {
            field: dict(counter)
            for field, counter in sorted(scalar_value_counts.items())
        },
        "numeric_metric_stats": numeric_metric_stats,
    }, None


def _is_log(path: Path) -> bool:
    return path.suffix.lower() in LOG_SUFFIXES or path.name in {
        "stdout",
        "stderr",
        "console",
        "pytest",
    }


def _scan_log(
    path: Path,
    group_name: str,
    relative: Path,
) -> tuple[dict[str, Any], Iterator[dict[str, Any]], str | None]:
    summary: dict[str, Any] = {
        "line_count": 0,
        "event_counts": Counter(),
        "stage_events": [],
        "pytest_summaries": [],
        "error_samples": [],
        "warning_samples": [],
    }
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, raw_line in enumerate(handle, start=1):
                summary["line_count"] += 1
                line = raw_line.rstrip("\n")
                event_kind = ""
                event_payload: dict[str, Any] = {}
                start_match = START_RE.search(line)
                end_match = END_RE.search(line)
                pytest_match = PYTEST_RE.search(line)
                if start_match:
                    event_kind = "start"
                    event_payload = {"stage": start_match.group("stage").strip()}
                    summary["stage_events"].append({"line": line_no, **event_payload})
                elif end_match:
                    event_kind = "end"
                    event_payload = {
                        "stage": end_match.group("stage").strip(),
                        "exit": int(end_match.group("exit")),
                    }
                    if end_match.group("elapsed"):
                        event_payload["elapsed_s"] = float(end_match.group("elapsed"))
                    summary["stage_events"].append({"line": line_no, **event_payload})
                elif pytest_match:
                    event_kind = "pytest_summary"
                    event_payload = {
                        key: int(value)
                        for key, value in pytest_match.groupdict().items()
                        if value is not None
                    }
                    summary["pytest_summaries"].append({"line": line_no, **event_payload})
                elif ERROR_RE.search(line):
                    event_kind = "error"
                    if len(summary["error_samples"]) < 100:
                        summary["error_samples"].append({"line": line_no, "text": line[:1000]})
                elif WARNING_RE.search(line):
                    event_kind = "warning"
                    if len(summary["warning_samples"]) < 100:
                        summary["warning_samples"].append({"line": line_no, "text": line[:1000]})
                if event_kind:
                    summary["event_counts"][event_kind] += 1
                    events.append({
                        "run_group": group_name,
                        "path": str(relative),
                        "line": line_no,
                        "kind": event_kind,
                        "payload": event_payload,
                        "text": line[:2000],
                    })
    except OSError as exc:
        return {}, iter(()), f"{type(exc).__name__}: {exc}"
    summary["event_counts"] = dict(summary["event_counts"])
    return summary, iter(events), None


def _parse_checksums(path: Path, run_root: Path, verify: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    entries: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {"read_error": f"{type(exc).__name__}: {exc}"}, entries
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        match = re.match(r"^([0-9a-fA-F]{64})\s+[* ]?(.*)$", line)
        if not match:
            parse_errors.append({"line": line_no, "text": line})
            continue
        expected, relative_name = match.groups()
        # Checksum ledgers are emitted from the individual run root, not from
        # the shared contest artifact root.
        candidate = run_root / relative_name
        entry: dict[str, Any] = {
            "line": line_no,
            "expected_sha256": expected.lower(),
            "path": relative_name,
        }
        try:
            entry["exists"] = candidate.is_file()
        except OSError as exc:
            entry["exists"] = False
            entry["stat_error"] = f"{type(exc).__name__}: {exc}"
        if verify and entry["exists"]:
            try:
                observed = _sha256(candidate)
                entry["observed_sha256"] = observed
                entry["verified"] = observed == entry["expected_sha256"]
            except OSError as exc:
                entry["verification_error"] = f"{type(exc).__name__}: {exc}"
        entries.append(entry)
    return {
        "entry_count": len(entries),
        "parse_error_count": len(parse_errors),
        "parse_error_samples": parse_errors[:50],
        "verification_requested": verify,
        "verification_success_count": sum(1 for entry in entries if entry.get("verified") is True),
        "verification_failure_count": sum(1 for entry in entries if entry.get("verified") is False),
        "unreadable_entry_count": sum(1 for entry in entries if "stat_error" in entry),
    }, entries


def _increment_numeric_stats(stats: dict[str, dict[str, float]], metrics: dict[str, float]) -> None:
    for key, value in metrics.items():
        bucket = stats.setdefault(key, {"count": 0.0, "sum": 0.0, "min": value, "max": value})
        bucket["count"] += 1.0
        bucket["sum"] += value
        bucket["min"] = min(bucket["min"], value)
        bucket["max"] = max(bucket["max"], value)


def _merge_numeric_stats(
    target: dict[str, dict[str, float]],
    source: dict[str, dict[str, float]],
) -> None:
    """Merge pre-aggregated numeric summaries without treating means as data."""
    for key, source_bucket in source.items():
        if not source_bucket.get("count"):
            continue
        bucket = target.setdefault(
            key,
            {
                "count": 0.0,
                "sum": 0.0,
                "min": source_bucket["min"],
                "max": source_bucket["max"],
            },
        )
        bucket["count"] += float(source_bucket["count"])
        bucket["sum"] += float(source_bucket["sum"])
        bucket["min"] = min(bucket["min"], float(source_bucket["min"]))
        bucket["max"] = max(bucket["max"], float(source_bucket["max"]))


def _accumulate_projection(
    group: dict[str, Any],
    projection: dict[str, Any],
    global_schema_versions: Counter[str],
    global_schema_paths: Counter[str],
    global_scalar_counts: dict[str, Counter[str]],
    global_numeric_stats: dict[str, dict[str, float]],
) -> None:
    """Accumulate the common projection form for JSON and JSONL documents."""
    selected_fields = projection.get("selected_fields", {})
    for schema in selected_fields.get("schema_version", []):
        group["schema_versions"][str(schema)] += 1
        global_schema_versions[str(schema)] += 1
    for schema, count in projection.get("schema_versions", {}).items():
        group["schema_versions"][schema] += count
        global_schema_versions[schema] += count
    for schema_path, count in projection.get("schema_paths", {}).items():
        group["schema_paths"][schema_path] += count
        global_schema_paths[schema_path] += count

    for field, values in selected_fields.items():
        for item in values:
            key = _scalar_key(item)
            if key is not None:
                group["scalar_value_counts"][field][key] += 1
                global_scalar_counts[field][key] += 1
    for field, values in projection.get("scalar_value_counts", {}).items():
        for key, count in values.items():
            group["scalar_value_counts"][field][key] += count
            global_scalar_counts[field][key] += count

    metrics = projection.get("numeric_metrics", {})
    if metrics:
        _increment_numeric_stats(group["numeric_metric_stats"], metrics)
        _increment_numeric_stats(global_numeric_stats, metrics)
    _merge_numeric_stats(
        group["numeric_metric_stats"],
        projection.get("numeric_metric_stats", {}),
    )
    _merge_numeric_stats(
        global_numeric_stats,
        projection.get("numeric_metric_stats", {}),
    )


def _group_for(relative: Path, *, is_directory: bool = False) -> str:
    if not relative.parts:
        return "__root__"
    if is_directory:
        return relative.parts[0]
    return relative.parts[0] if len(relative.parts) > 1 else "__root__"


def _new_group(name: str) -> dict[str, Any]:
    classification, reason = _classify_group(name)
    return {
        "name": name,
        "classification": classification,
        "classification_reason": reason,
        "directory_count": 0,
        "unreadable_directory_count": 0,
        "file_count": 0,
        "byte_count": 0,
        "category_counts": Counter(),
        "json_document_count": 0,
        "json_parse_error_count": 0,
        "document_index_count": 0,
        "root_summary": None,
        "log_files": [],
        "checksum_files": [],
        "schema_versions": Counter(),
        "schema_paths": Counter(),
        "scalar_value_counts": defaultdict(Counter),
        "numeric_metric_stats": {},
        "file_records": [],
        "directory_records": [],
        "scan_errors": [],
    }


def _normalise_group(group: dict[str, Any]) -> dict[str, Any]:
    group = dict(group)
    for key in ("category_counts", "schema_versions", "schema_paths"):
        group[key] = dict(group[key])
    group["scalar_value_counts"] = {
        field: dict(counter)
        for field, counter in sorted(group["scalar_value_counts"].items())
    }
    for metric in group["numeric_metric_stats"].values():
        if metric["count"]:
            metric["mean"] = metric["sum"] / metric["count"]
    return group


def _write_markdown(inventory: dict[str, Any], path: Path) -> None:
    scan = inventory["scan"]
    lines = [
        "# StateBus Contest Baseline Artifact Inventory",
        "",
        f"- Generated: `{inventory['generated_at']}`",
        f"- Artifact root: `{inventory['artifact_root']}`",
        f"- Indexed directories: `{scan['directory_count']}`; files: `{scan['file_count']}`; reachable bytes: `{scan['byte_count']}`",
        f"- JSON documents: `{scan['json_document_count']}`; JSON parse errors: `{scan['json_parse_error_count']}`",
        f"- Scan/read errors: `{len(scan['errors'])}`. They remain explicit in `inventory.json`.",
        "- This report inventories evidence. It does not convert a diagnostic artifact into a headline claim.",
        "",
        "## Run Groups",
        "",
        "| Group | Classification | Files | Bytes | JSON | Logs |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for group in inventory["run_groups"]:
        lines.append(
            "| {name} | {classification} | {files} | {bytes} | {json} | {logs} |".format(
                name=group["name"].replace("|", "\\|"),
                classification=group["classification"],
                files=group["file_count"],
                bytes=group["byte_count"],
                json=group["json_document_count"],
                logs=len(group["log_files"]),
            )
        )
    lines.extend([
        "",
        "## Canonical E0-E6",
        "",
        "| Stage | Root | Root summary fields | Categories present |",
        "| --- | --- | --- | --- |",
    ])
    for group in inventory["run_groups"]:
        if group["classification"] != "canonical":
            continue
        summary = group.get("root_summary") or {}
        fields = summary.get("projection", {}).get("selected_fields", {})
        compact = []
        for key in ("ok", "stage", "suite_id", "quality_pass_count", "case_count"):
            if key in fields:
                compact.append(f"{key}={fields[key][0]}")
        categories = ", ".join(sorted(group["category_counts"]))
        lines.append(
            f"| {group['classification_reason']} | `{group['name']}` | {'; '.join(compact) or 'see inventory'} | {categories} |"
        )
    lines.extend([
        "",
        "## Output Files",
        "",
        "- `inventory.json`: complete file/directory index, aggregate schema/field/metric inventory, checksum manifests and scan errors.",
        "- `document_index.jsonl.gz`: one compact parsed record per JSON/JSONL source, including source path, category, selected fields, numeric leaves and a schema catalog ID.",
        "- `schema_catalog.json`: de-duplicated schema paths referenced by `document_index.jsonl.gz`.",
        "- `log_events.jsonl`: every indexed START/END/pytest/error/warning event with source path and line number.",
        "- `summary.md`: this navigational summary.",
        "",
        "Raw artifacts remain at the source root; the inventory records their paths and sizes instead of copying prompts, task data or model outputs.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit(args: argparse.Namespace) -> dict[str, Any]:
    root = args.artifact_root.resolve()
    if not root.is_dir():
        raise SystemExit(f"artifact root does not exist or is not a directory: {root}")
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    groups: dict[str, dict[str, Any]] = {"__root__": _new_group("__root__")}
    errors: list[dict[str, Any]] = []
    global_category_counts: Counter[str] = Counter()
    global_schema_versions: Counter[str] = Counter()
    global_schema_paths: Counter[str] = Counter()
    global_scalar_counts: dict[str, Counter[str]] = defaultdict(Counter)
    global_numeric_stats: dict[str, dict[str, float]] = {}
    global_log_event_counts: Counter[str] = Counter()
    schema_catalog: dict[str, dict[str, Any]] = {}
    log_event_path = output_dir / "log_events.jsonl"
    document_index_path = output_dir / "document_index.jsonl.gz"

    def group_for_path(relative: Path, *, is_directory: bool = False) -> dict[str, Any]:
        name = _group_for(relative, is_directory=is_directory)
        if name not in groups:
            groups[name] = _new_group(name)
        return groups[name]

    def on_walk_error(exc: OSError) -> None:
        path = Path(exc.filename) if exc.filename else root
        try:
            relative = path.relative_to(root)
        except ValueError:
            relative = Path(str(path))
        entry = {
            "path": str(relative),
            "kind": "directory_walk",
            "error": f"{type(exc).__name__}: {exc}",
        }
        errors.append(entry)
        group = group_for_path(relative, is_directory=True)
        group["scan_errors"].append(entry)
        group["unreadable_directory_count"] += 1
        group["directory_records"].append({
            "path": str(relative),
            "access_error": entry["error"],
        })

    with (
        log_event_path.open("w", encoding="utf-8") as log_event_handle,
        gzip.open(document_index_path, "wt", encoding="utf-8") as document_index_handle,
    ):
        for directory, dirnames, filenames in os.walk(root, topdown=True, onerror=on_walk_error):
            directory_path = Path(directory)
            try:
                relative_directory = directory_path.relative_to(root)
            except ValueError:
                relative_directory = Path()
            directory_group = group_for_path(relative_directory, is_directory=True)
            directory_record: dict[str, Any] = {
                "path": str(relative_directory) if relative_directory.parts else ".",
            }
            try:
                directory_stat = directory_path.stat()
                directory_record["mtime_ns"] = directory_stat.st_mtime_ns
                directory_record["mode_octal"] = format(directory_stat.st_mode & 0o7777, "04o")
            except OSError as exc:
                directory_record["stat_error"] = f"{type(exc).__name__}: {exc}"
                entry = {
                    "path": directory_record["path"],
                    "kind": "directory_stat",
                    "error": directory_record["stat_error"],
                }
                errors.append(entry)
                directory_group["scan_errors"].append(entry)
            directory_group["directory_count"] += 1
            directory_group["directory_records"].append(directory_record)
            for filename in sorted(filenames):
                path = directory_path / filename
                relative = relative_directory / filename
                group = group_for_path(relative)
                category = _category(relative)
                record: dict[str, Any] = {
                    "path": str(relative),
                    "category": category,
                }
                try:
                    stat = path.stat()
                    record["size_bytes"] = stat.st_size
                    record["mtime_ns"] = stat.st_mtime_ns
                except OSError as exc:
                    record["stat_error"] = f"{type(exc).__name__}: {exc}"
                    entry = {
                        "path": str(relative),
                        "kind": "file_stat",
                        "error": record["stat_error"],
                    }
                    errors.append(entry)
                    group["scan_errors"].append(entry)
                    group["file_records"].append(record)
                    continue
                if args.hash_files:
                    try:
                        record["sha256"] = _sha256(path)
                    except OSError as exc:
                        record["hash_error"] = f"{type(exc).__name__}: {exc}"
                group["file_count"] += 1
                group["byte_count"] += int(record["size_bytes"])
                group["category_counts"][category] += 1
                global_category_counts[category] += 1

                if path.suffix.lower() == ".json":
                    group["json_document_count"] += 1
                    value, error = _read_json(path)
                    document_record: dict[str, Any] = {
                        "run_group": group["name"],
                        "path": str(relative),
                        "category": category,
                        "source_kind": "json",
                        "source_size_bytes": record["size_bytes"],
                    }
                    if "sha256" in record:
                        document_record["source_sha256"] = record["sha256"]
                    if error:
                        document_record["parse_error"] = error
                        group["json_parse_error_count"] += 1
                        entry = {"path": str(relative), "kind": "json_parse", "error": error}
                        errors.append(entry)
                        group["scan_errors"].append(entry)
                    else:
                        projection = _project_json(value)
                        _accumulate_projection(
                            group,
                            projection,
                            global_schema_versions,
                            global_schema_paths,
                            global_scalar_counts,
                            global_numeric_stats,
                        )
                        schema_id = _register_schema(
                            schema_catalog,
                            projection.get("schema_paths", {}),
                        )
                        document_record["projection"] = _compact_document_projection(
                            projection,
                            schema_id,
                        )
                        if (
                            relative.name == "summary.json"
                            and relative.parent == Path(group["name"])
                        ):
                            group["root_summary"] = {
                                "path": str(relative),
                                "projection": document_record["projection"],
                            }
                    document_index_handle.write(
                        json.dumps(document_record, ensure_ascii=False) + "\n"
                    )
                    group["document_index_count"] += 1
                elif path.suffix.lower() == ".jsonl":
                    group["json_document_count"] += 1
                    projection, error = _read_jsonl(path)
                    document_record = {
                        "run_group": group["name"],
                        "path": str(relative),
                        "category": category,
                        "source_kind": "jsonl",
                        "source_size_bytes": record["size_bytes"],
                    }
                    if "sha256" in record:
                        document_record["source_sha256"] = record["sha256"]
                    if error:
                        document_record["parse_error"] = error
                        group["json_parse_error_count"] += 1
                        entry = {"path": str(relative), "kind": "jsonl_read", "error": error}
                        errors.append(entry)
                        group["scan_errors"].append(entry)
                    else:
                        group["json_parse_error_count"] += int(projection["invalid_json_count"])
                        for parse_error in projection["parse_errors"]:
                            entry = {
                                "path": str(relative),
                                "kind": "jsonl_parse",
                                "line": parse_error["line"],
                                "error": parse_error["error"],
                            }
                            errors.append(entry)
                            group["scan_errors"].append(entry)
                        _accumulate_projection(
                            group,
                            projection,
                            global_schema_versions,
                            global_schema_paths,
                            global_scalar_counts,
                            global_numeric_stats,
                        )
                        schema_id = _register_schema(
                            schema_catalog,
                            projection.get("schema_paths", {}),
                        )
                        document_record["projection"] = _compact_document_projection(
                            projection,
                            schema_id,
                        )
                    document_index_handle.write(
                        json.dumps(document_record, ensure_ascii=False) + "\n"
                    )
                    group["document_index_count"] += 1

                if _is_log(path):
                    summary, events, error = _scan_log(path, group["name"], relative)
                    log_record: dict[str, Any] = {"path": str(relative), "category": category}
                    if error:
                        log_record["read_error"] = error
                        entry = {"path": str(relative), "kind": "log_read", "error": error}
                        errors.append(entry)
                        group["scan_errors"].append(entry)
                    else:
                        log_record["summary"] = summary
                        global_log_event_counts.update(summary["event_counts"])
                        for event in events:
                            log_event_handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                    group["log_files"].append(log_record)

                if path.name == "checksums.sha256":
                    checksum_summary, checksum_entries = _parse_checksums(
                        path,
                        path.parent,
                        args.verify_checksums,
                    )
                    group["checksum_files"].append({
                        "path": str(relative),
                        "summary": checksum_summary,
                        "entries": checksum_entries,
                    })
                group["file_records"].append(record)

    _json_dump(output_dir / "schema_catalog.json", schema_catalog)
    for metric in global_numeric_stats.values():
        if metric["count"]:
            metric["mean"] = metric["sum"] / metric["count"]
    normalised_groups = [_normalise_group(groups[name]) for name in sorted(groups)]
    inventory = {
        "schema_version": "statebus.contest_baseline_asset_inventory.v2",
        "generated_at": _utc_now(),
        "artifact_root": str(root),
        "audit_options": {
            "hash_files": args.hash_files,
            "verify_checksums": args.verify_checksums,
            "canonical_run_names": CANONICAL_RUNS,
        },
        "index_outputs": {
            "document_index": document_index_path.name,
            "document_index_encoding": "gzip JSON Lines",
            "schema_catalog": "schema_catalog.json",
            "log_events": log_event_path.name,
        },
        "scan": {
            "directory_count": sum(group["directory_count"] for group in normalised_groups),
            "unreadable_directory_count": sum(
                group["unreadable_directory_count"] for group in normalised_groups
            ),
            "file_count": sum(group["file_count"] for group in normalised_groups),
            "byte_count": sum(group["byte_count"] for group in normalised_groups),
            "json_document_count": sum(group["json_document_count"] for group in normalised_groups),
            "json_parse_error_count": sum(group["json_parse_error_count"] for group in normalised_groups),
            "category_counts": dict(global_category_counts),
            "schema_versions": dict(global_schema_versions),
            "schema_paths": dict(global_schema_paths),
            "scalar_value_counts": {
                field: dict(counter) for field, counter in sorted(global_scalar_counts.items())
            },
            "numeric_metric_stats": global_numeric_stats,
            "log_event_counts": dict(global_log_event_counts),
            "errors": errors,
        },
        "run_groups": normalised_groups,
    }
    _json_dump(output_dir / "inventory.json", inventory)
    _write_markdown(inventory, output_dir / "summary.md")
    return inventory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT,
        help=f"artifact root to inspect (default: {DEFAULT_ARTIFACT_ROOT})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="new directory for inventory.json, log_events.jsonl, and summary.md",
    )
    parser.add_argument(
        "--hash-files",
        action="store_true",
        help="compute SHA-256 for every reachable file; slower but fully content-addresses the index",
    )
    parser.add_argument(
        "--verify-checksums",
        action="store_true",
        help="recompute entries listed in every checksums.sha256 file",
    )
    args = parser.parse_args()
    inventory = audit(args)
    scan = inventory["scan"]
    print(
        "indexed "
        f"{scan['file_count']} files, {scan['json_document_count']} JSON/JSONL documents, "
        f"{len(inventory['run_groups'])} run groups; "
        f"scan errors={len(scan['errors'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
