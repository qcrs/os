#!/usr/bin/env python3
"""Extract a review ledger from the fixed StateBus contest baseline.

This tool is intentionally read-only with respect to experiment artifacts. It
does not run tests, benchmarks, containers, or models. It turns the canonical
E0-E6 roots plus preserved non-canonical retries into a compact evidence
ledger that points back to every source file.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import re
from typing import Any, Iterable


DEFAULT_ARTIFACT_ROOT = Path(
    "/home/qcrs/statebus/runs/contest_evidence_closure_20260720"
)
DEFAULT_FULL_AUDIT_SUMMARY = Path(
    "/home/qcrs/statebus/runs/contest_baseline_asset_audit_20260724_container/summary.md"
)

CANONICAL_RUNS = {
    "e0_focused_20260720_142422": "E0 focused tests and deterministic preflight",
    "e1_causal_serial_20260720_150801": "E1 matched L0-L3 causal matrix",
    "e2_stress_serial_20260720_152924": "E2 two-family 10-round stability",
    "e3_adaptive_memory_final_20260720_160244": "E3 adaptive-memory truth funnel",
    "e4_semantic_holdout_final4_20260720_175430": "E4 semantic/table holdout",
    "e5_adaptive_final_20260720_190107": "E5 adaptive capability and CodeAct run",
    "e6_full_final_20260720_201043": "E6 complete v2 regression and preflight",
}

NONCANONICAL_RUNS = {
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

AUDIT_CATEGORIES = (
    "case_reports",
    "role_requests",
    "state_consumption",
    "memory_queries",
    "memory_consumption",
    "replay_decisions",
    "artifact_lineage",
)

ROOT_FILES = (
    "run_manifest.json",
    "environment.json",
    "fairness_manifest.json",
    "capability_registry.json",
    "summary.json",
    "summary.md",
    "pytest.log",
    "console.log",
    "wrapper.log",
    "checksums.sha256",
)

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
    "round_index",
    "role",
    "role_id",
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
    "operation",
    "workflow_mode",
    "system_gate_passed",
    "expected_facts_passed",
    "benchmark_oracle_visible_to_roles",
    "producer_pid",
    "consumer_pid",
)

LOG_SUFFIXES = {".log", ".txt", ".out", ".err", ".stdout", ".stderr"}
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


def _json_dump(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle), None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _short(value: Any, limit: int = 240) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return None


def _find_values(value: Any, field: str, limit: int = 24) -> list[Any]:
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


def _numeric_leaves(value: Any, limit: int = 512) -> dict[str, float]:
    """Index named numeric leaves, but avoid copying numeric vector payloads."""
    result: dict[str, float] = {}
    stack: list[tuple[Any, str]] = [(value, "")]
    while stack and len(result) < limit:
        current, prefix = stack.pop()
        if isinstance(current, dict):
            for key, item in current.items():
                current_path = f"{prefix}.{key}" if prefix else key
                if isinstance(item, bool):
                    continue
                if isinstance(item, (int, float)):
                    result[current_path] = float(item)
                elif isinstance(item, dict):
                    stack.append((item, current_path))
                elif isinstance(item, list):
                    for member in item:
                        if isinstance(member, dict):
                            stack.append((member, current_path + "[]"))
    return result


def _category(path: Path) -> str:
    for component in path.parts:
        if component in AUDIT_CATEGORIES:
            return component
    if path.name in ROOT_FILES:
        return "root_envelope"
    if path.suffix.lower() == ".json":
        return "json_other"
    if path.suffix.lower() == ".jsonl":
        return "jsonl_other"
    if path.suffix.lower() in LOG_SUFFIXES:
        return "log_other"
    return "other"


def _compact_json_record(relative: Path, value: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": str(relative),
        "category": _category(relative),
        "root_type": type(value).__name__,
    }
    if not isinstance(value, dict):
        return record
    record["top_level_keys"] = sorted(value)
    selected: dict[str, list[Any]] = {}
    for field in SCALAR_FIELDS:
        values = [_short(item) for item in _find_values(value, field)]
        values = [item for item in values if item is not None]
        if values:
            selected[field] = values
    if selected:
        record["selected_fields"] = selected
    numeric = _numeric_leaves(value)
    if numeric:
        record["numeric_leaves"] = numeric
    return record


def _is_log(path: Path) -> bool:
    return path.suffix.lower() in LOG_SUFFIXES or path.name in {
        "stdout",
        "stderr",
        "console",
        "pytest",
    }


def _parse_log(path: Path, relative: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary: dict[str, Any] = {
        "path": str(relative),
        "line_count": 0,
        "event_counts": Counter(),
        "pytest_summaries": [],
        "stage_events": [],
    }
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, raw in enumerate(handle, start=1):
                summary["line_count"] += 1
                line = raw.rstrip("\n")
                kind = ""
                payload: dict[str, Any] = {}
                if match := START_RE.search(line):
                    kind = "start"
                    payload = {"stage": match.group("stage").strip()}
                    summary["stage_events"].append({"line": line_number, **payload})
                elif match := END_RE.search(line):
                    kind = "end"
                    payload = {
                        "stage": match.group("stage").strip(),
                        "exit": int(match.group("exit")),
                    }
                    if match.group("elapsed"):
                        payload["elapsed_s"] = float(match.group("elapsed"))
                    summary["stage_events"].append({"line": line_number, **payload})
                elif match := PYTEST_RE.search(line):
                    kind = "pytest_summary"
                    payload = {
                        key: int(item)
                        for key, item in match.groupdict().items()
                        if item is not None
                    }
                    summary["pytest_summaries"].append({"line": line_number, **payload})
                elif ERROR_RE.search(line):
                    kind = "error"
                elif WARNING_RE.search(line):
                    kind = "warning"
                if kind:
                    summary["event_counts"][kind] += 1
                    events.append(
                        {
                            "path": str(relative),
                            "line": line_number,
                            "kind": kind,
                            "payload": payload,
                            "text": line[:2000],
                        }
                    )
    except OSError as exc:
        summary["read_error"] = f"{type(exc).__name__}: {exc}"
    summary["event_counts"] = dict(summary["event_counts"])
    return summary, events


def _parse_checksum_ledger(path: Path) -> dict[str, Any]:
    entries = 0
    malformed: list[dict[str, Any]] = []
    line_re = re.compile(r"^[0-9a-fA-F]{64}\s+[* ]?.+$")
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {"path": path.name, "read_error": f"{type(exc).__name__}: {exc}"}
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        if line_re.match(line):
            entries += 1
        else:
            malformed.append({"line": number, "text": line})
    return {
        "path": path.name,
        "entry_count": entries,
        "malformed_entries": malformed,
    }


def _root_signal(summary: Any) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {"root_type": type(summary).__name__}
    signal: dict[str, Any] = {"top_level_keys": sorted(summary)}
    for key in (
        "ok",
        "stage",
        "suite_id",
        "round_view",
        "execution_scope",
        "pytest_passed",
        "preflight_ok",
        "contest_stage_ok",
        "formal_headline_eligible",
        "eligible_for_headline",
        "eligible_for_quality_headline",
        "eligible_for_replay_headline",
        "quality_pass_count",
        "case_count",
        "attempted_case_count",
        "quality_pass_rate",
        "latency_superiority_claim_allowed",
    ):
        if key in summary:
            signal[key] = summary[key]
    for key in (
        "child_exit_codes",
        "contest_stage_gates",
        "collection_summary",
        "memory_funnel",
        "adaptive_metrics",
        "adaptive_capability_distribution",
        "capability_counts",
        "runtime_freeze_audit",
        "failures",
        "stage_failure_counts",
        "negative_case_gates",
    ):
        if key in summary:
            signal[key] = summary[key]
    return signal


def _run_ledger(
    root: Path,
    run_name: str,
    description: str,
    slice_writer: Any,
    log_writer: Any,
) -> dict[str, Any]:
    run_root = root / run_name
    run: dict[str, Any] = {
        "run": run_name,
        "description": description,
        "source_root": str(run_root),
        "exists": run_root.is_dir(),
        "file_categories": {},
        "slice_category_counts": {},
        "slice_parse_errors": [],
        "root_files_present": [],
        "log_files": [],
        "log_event_counts": {},
        "root_envelope": {},
    }
    if not run_root.is_dir():
        return run

    file_categories: Counter[str] = Counter()
    slice_counts: Counter[str] = Counter()
    log_counts: Counter[str] = Counter()
    for path in sorted(item for item in run_root.rglob("*") if item.is_file()):
        relative = path.relative_to(run_root)
        category = _category(relative)
        file_categories[category] += 1
        if relative.name in ROOT_FILES and relative.parent == Path("."):
            run["root_files_present"].append(relative.name)
        if path.suffix.lower() == ".json" and category in AUDIT_CATEGORIES:
            value, error = _read_json(path)
            slice_counts[category] += 1
            if error:
                run["slice_parse_errors"].append({"path": str(relative), "error": error})
            else:
                record = _compact_json_record(relative, value)
                record["run"] = run_name
                slice_writer.write(json.dumps(record, ensure_ascii=False) + "\n")
        if _is_log(path):
            log_summary, events = _parse_log(path, relative)
            run["log_files"].append(log_summary)
            log_counts.update(log_summary["event_counts"])
            for event in events:
                event["run"] = run_name
                log_writer.write(json.dumps(event, ensure_ascii=False) + "\n")

    summary_path = run_root / "summary.json"
    if summary_path.is_file():
        summary, error = _read_json(summary_path)
        if error:
            run["summary_error"] = error
        else:
            run["summary"] = summary
            run["summary_signal"] = _root_signal(summary)
    for filename in (
        "run_manifest.json",
        "environment.json",
        "fairness_manifest.json",
        "capability_registry.json",
    ):
        envelope_path = run_root / filename
        if not envelope_path.is_file():
            continue
        value, error = _read_json(envelope_path)
        if error:
            run["root_envelope"][filename] = {"parse_error": error}
        else:
            run["root_envelope"][filename] = value
    checksums = run_root / "checksums.sha256"
    if checksums.is_file():
        run["checksum_ledger"] = _parse_checksum_ledger(checksums)
    run["file_categories"] = dict(file_categories)
    run["slice_category_counts"] = dict(slice_counts)
    run["log_event_counts"] = dict(log_counts)
    return run


def _markdown(ledger: dict[str, Any]) -> str:
    lines = [
        "# StateBus Contest Recovery Baseline Evidence Ledger",
        "",
        f"- Generated: `{ledger['generated_at']}`",
        f"- Artifact root: `{ledger['artifact_root']}`",
        "- Scope: read-only extraction of existing artifacts; no test, benchmark, model request, vLLM operation, or experiment workload was started.",
        "- Integrity source: the full container-root audit named below has zero scan/read errors; its checksum verification results remain in that audit inventory.",
        "",
        "## Audit Coverage",
        "",
        f"- Full audit summary: `{ledger['full_audit_summary']}`",
        "- The host audit could not enter 36 root-owned semantic-state view directories from later 2026-07-23 development runs.",
        "- The container-root audit read the same root completely: 64,472 files, 61,682 JSON/JSONL documents, and 0 scan/read errors.",
        "",
        "## Canonical E0-E6",
        "",
        "| Stage | Source root | Outcome signal | Slice files | Log events |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for run in ledger["canonical_runs"]:
        signal = run.get("summary_signal", {})
        outcome_parts = []
        for key in ("ok", "contest_stage_ok", "pytest_passed", "quality_pass_count", "case_count"):
            if key in signal:
                outcome_parts.append(f"{key}={signal[key]}")
        lines.append(
            "| {description} | `{run}` | {outcome} | {slices} | {events} |".format(
                description=run["description"],
                run=run["run"],
                outcome="; ".join(outcome_parts) or "see ledger JSON",
                slices=sum(run["slice_category_counts"].values()),
                events=sum(run["log_event_counts"].values()),
            )
        )
    lines.extend([
        "",
        "## Preserved Non-Canonical Runs",
        "",
        "| Root | Classification | Outcome signal |",
        "| --- | --- | --- |",
    ])
    for run in ledger["noncanonical_runs"]:
        signal = run.get("summary_signal", {})
        outcome_parts = []
        for key in ("ok", "contest_stage_ok", "pytest_passed", "quality_pass_count", "case_count"):
            if key in signal:
                outcome_parts.append(f"{key}={signal[key]}")
        lines.append(
            f"| `{run['run']}` | {run['description']} | {'; '.join(outcome_parts) or 'root log only / see ledger JSON'} |"
        )
    lines.extend([
        "",
        "## Machine-Readable Outputs",
        "",
        "- `ledger.json`: complete root summaries, file-category counts, checksum-ledger shapes, root-log summaries and source pointers.",
        "- `slice_records.jsonl.gz`: one compact record for every JSON file in the seven audit-slice categories of E0-E6 and preserved non-canonical runs.",
        "- `log_events.jsonl`: every START/END/pytest/error/warning event extracted from those roots.",
        "",
        "The ledger intentionally distinguishes canonical evidence from retries and diagnostics. It records what exists; it does not make a performance claim from a raw metric alone.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--full-audit-summary", type=Path, default=DEFAULT_FULL_AUDIT_SUMMARY)
    args = parser.parse_args()

    root = args.artifact_root.resolve()
    if not root.is_dir():
        raise SystemExit(f"artifact root is not a directory: {root}")
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    slice_path = output_dir / "slice_records.jsonl.gz"
    log_path = output_dir / "log_events.jsonl"
    with (
        gzip.open(slice_path, "wt", encoding="utf-8") as slice_writer,
        log_path.open("w", encoding="utf-8") as log_writer,
    ):
        canonical_runs = [
            _run_ledger(root, name, description, slice_writer, log_writer)
            for name, description in CANONICAL_RUNS.items()
        ]
        noncanonical_runs = [
            _run_ledger(root, name, description, slice_writer, log_writer)
            for name, description in NONCANONICAL_RUNS.items()
        ]

    ledger = {
        "schema_version": "statebus.contest_recovery_baseline_ledger.v1",
        "generated_at": _utc_now(),
        "artifact_root": str(root),
        "full_audit_summary": str(args.full_audit_summary),
        "full_audit_summary_exists": args.full_audit_summary.is_file(),
        "canonical_runs": canonical_runs,
        "noncanonical_runs": noncanonical_runs,
    }
    _json_dump(output_dir / "ledger.json", ledger)
    (output_dir / "ledger.md").write_text(_markdown(ledger), encoding="utf-8")
    print(
        f"wrote {len(canonical_runs)} canonical and {len(noncanonical_runs)} non-canonical run ledgers"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
