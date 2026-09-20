#!/usr/bin/env python3
"""Offline, read-only Stage 2 artifact analyzer.

Only JSON/JSONL/CSV and a small known JSON-lines log shape are parsed.  The
helper never imports or executes artifact code, opens SQLite, follows links
across roots, starts services, or changes an input root.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


KNOWN_SUFFIXES = {".json", ".jsonl", ".csv", ".log"}
SCHEMA_PROFILES = {"auto", "stage2_v1", "stage2_v2"}
TERMINAL_CLASSES = {"success", "quality_fail", "timeout", "unsupported", "runtime_fail", "policy_reject", "environment_fail"}
RECEIPT_COLLECTIONS = {
    "artifact_verification_receipts.json",
    "binding_receipts.json",
    "grant_receipts.json",
    "semantic_consumer_receipt.json",
    "state_pin_receipts.json",
}
RECEIPT_FIELDS = {
    "statebus.execution_binding_receipt.v1": ("binding_id", "attempt_id", "session_id", "step_id"),
    "statebus.capability_grant.v1": ("grant_id", "attempt_id", "session_id", "step_id"),
    "statebus.artifact_verification_receipt.v1": ("artifact_id", "run_id", "session_id", "decision"),
    "statebus.semantic_consumer_receipt.v1": ("state_ref_id", "invocation_id", "session_id", "receipt_status"),
    "statebus.state_pin_receipt.v1": ("pin_id", "state_ref_id", "session_id", "status"),
}


def _diag(diagnostics: list[dict[str, Any]], *, root: Path, path: Path, code: str, message: str, **extra: Any) -> None:
    diagnostics.append({"source_root": str(root), "source_path": str(path), "code": code, "message": message, **extra})


def _iter_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in KNOWN_SUFFIXES:
            yield path


def _read_file(path: Path, root: Path, diagnostics: list[dict[str, Any]]) -> list[tuple[Any, str, int | None]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                return [(dict(row), "csv", index) for index, row in enumerate(csv.DictReader(handle), start=2)]
        except (OSError, UnicodeError, csv.Error) as exc:
            _diag(diagnostics, root=root, path=path, code="malformed", message=f"csv:{type(exc).__name__}:{exc}")
            return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        _diag(diagnostics, root=root, path=path, code="malformed", message=f"read:{type(exc).__name__}:{exc}")
        return []
    if suffix in {".jsonl", ".log"}:
        rows: list[tuple[Any, str, int | None]] = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append((json.loads(line), "jsonl", number))
            except json.JSONDecodeError:
                # Known text logs are retained as diagnostics, not executed or guessed.
                _diag(diagnostics, root=root, path=path, code="malformed", message="line_is_not_json", row_number=number)
        return rows
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        _diag(diagnostics, root=root, path=path, code="malformed", message=f"json:{exc.msg}")
        return []
    return [(payload, "json", None)]


def _expand(payload: Any, pointer: str = "") -> Iterable[tuple[Any, str]]:
    if isinstance(payload, list):
        for index, value in enumerate(payload):
            yield from _expand(value, f"{pointer}/{index}")
        return
    yield payload, pointer or "/"


def _kind(payload: Mapping[str, Any], path: Path) -> str:
    schema = str(payload.get("schema_version", ""))
    name = path.name.lower()
    if "manifest" in name or "manifest" in schema or isinstance(payload.get("planned_slots"), (list, dict)):
        return "manifest"
    if "slot_plan" in name or "planned_slots" in name:
        return "manifest"
    if "warmup" in str(path).lower():
        return "derived_summaries"
    if "call-start" in name or "call-end" in name:
        return "provider_events"
    if "raw_row" in name or schema.startswith(("statebus.stage2_pilot_raw.", "statebus.stage2_raw.")):
        return "raw_rows"
    if all(key in payload for key in ("slot_id", "pair_id", "lane")):
        return "raw_rows"
    if name in RECEIPT_COLLECTIONS or "receipt" in name or schema in RECEIPT_FIELDS:
        return "receipts"
    if "output" in name or "artifact" in name:
        return "actual_outputs"
    if "provider" in name or "provider_invocation" in str(payload.get("event", "")) or "request_id" in payload:
        return "provider_events"
    if "receipt_id" in payload or "admission" in payload:
        return "receipts"
    if "quality" in name or "quality" in payload or "passed" in payload and "validator" in payload:
        return "quality"
    if "denominator" in name or "denominator" in payload:
        return "denominator"
    if "summary" in name or "acceptance" in name or "report" in name:
        return "derived_summaries"
    return "unknown"


def _receipt_is_empty(record: Mapping[str, Any]) -> bool:
    required = RECEIPT_FIELDS.get(str(record.get("schema_version", "")))
    if required is not None:
        return any(not str(record.get(key, "")).strip() for key in required)
    return not str(record.get("receipt_id", "")).strip() or not any(
        str(record.get(key, "")).strip()
        for key in ("owner", "provider_invocation_status", "terminal_status", "admission", "decision", "status")
    )


def _raw_record(root: Path, path: Path, kind: str, payload: Mapping[str, Any], pointer: str, row_number: int | None) -> dict[str, Any]:
    identity = payload.get("row_identity") or payload.get("slot_id") or payload.get("row_id") or payload.get("id")
    return {
        "source_root": str(root), "source_path": str(path), "source_format": "jsonl" if row_number is not None else path.suffix.lstrip("."), "json_pointer": pointer, "row_number": row_number,
        "row_identity": str(identity) if identity is not None and str(identity) else None,
        "pair_id": payload.get("pair_id"), "slot_id": payload.get("slot_id"), "lane": payload.get("lane"), "task_family": payload.get("task_family"), "task_id": payload.get("task_id"), "split": payload.get("split", payload.get("dataset_split")), "round": payload.get("round", payload.get("round_number")), "repeat": payload.get("repeat", payload.get("repeat_id")), "seed": payload.get("seed"), "profile_id": payload.get("profile_id"), "epoch": payload.get("epoch", payload.get("regime")), "planned": payload.get("planned"), "status": payload.get("status", payload.get("terminal_status")), "terminal_class": payload.get("terminal_class", payload.get("status")), "raw_payload": dict(payload),
    }


def _raw_fingerprint(row: Mapping[str, Any]) -> str:
    """Fingerprint the canonical raw payload, excluding source bookkeeping."""

    payload = row.get("raw_payload", {})
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _is_aggregate_raw_path(path: Path) -> bool:
    return path.name in {"raw_rows.json", "raw_rows.jsonl"}


def _is_slot_raw_path(path: Path) -> bool:
    return path.name in {"raw_row.json", "raw_row.jsonl"}


def _finite_metric(value: Any) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(float(value)) != float("inf")
    except (TypeError, ValueError):
        return False


def analyze_artifacts(*, artifact_roots: Iterable[Path | str], output_root: Path | str, schema_profile: str = "auto", path_maps: Iterable[tuple[str, str]] = ()) -> dict[str, Any]:
    roots = [Path(item).resolve() for item in artifact_roots]
    output = Path(output_root).resolve()
    if schema_profile not in SCHEMA_PROFILES:
        raise ValueError(f"unsupported_schema_profile:{schema_profile}")
    if not roots:
        raise ValueError("at_least_one_artifact_root_required")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"analysis_output_root_must_be_new:{output}")
    for root in roots:
        if output == root or root in output.parents:
            raise ValueError("analysis_output_root_must_not_be_inside_input_root")
    output.mkdir(parents=True, exist_ok=True)
    diagnostics: list[dict[str, Any]] = []
    by_root: dict[str, dict[str, list[dict[str, Any]]]] = {str(root): defaultdict(list) for root in roots}
    file_count = 0
    for root in roots:
        if not root.exists():
            _diag(diagnostics, root=root, path=root, code="missing_root", message="artifact_root_does_not_exist")
            continue
        for path in _iter_files(root):
            file_count += 1
            for payload, fmt, row_number in _read_file(path, root, diagnostics):
                if path.name.lower() in RECEIPT_COLLECTIONS and payload in ({}, []):
                    continue
                for expanded, pointer in _expand(payload):
                    if not isinstance(expanded, Mapping):
                        _diag(diagnostics, root=root, path=path, code="malformed", message="row_is_not_object", row_number=row_number, json_pointer=pointer)
                        continue
                    kind = _kind(expanded, path)
                    record = dict(expanded)
                    record.update({"source_root": str(root), "source_path": str(path), "source_format": fmt, "row_number": row_number, "json_pointer": pointer})
                    if kind == "raw_rows":
                        raw = _raw_record(root, path, kind, expanded, pointer, row_number)
                        by_root[str(root)][kind].append(raw)
                        if not raw["row_identity"]:
                            _diag(diagnostics, root=root, path=path, code="missing_field", message="raw_row_identity_missing", row_number=row_number, json_pointer=pointer)
                    else:
                        by_root[str(root)][kind].append(record)
                        if kind == "receipts":
                            if _receipt_is_empty(record):
                                _diag(diagnostics, root=root, path=path, code="empty_receipt", message="receipt_has_no_identity_or_status", row_number=row_number, json_pointer=pointer)
                            if str(record.get("owner", "unknown")) not in {"runtime", "memory", "provider", "unknown"}:
                                _diag(diagnostics, root=root, path=path, code="wrong_scope", message="unknown_receipt_owner", owner=record.get("owner"), row_number=row_number)
    root_summaries: list[dict[str, Any]] = []
    all_pairs: list[dict[str, Any]] = []
    for root in roots:
        groups = by_root[str(root)]
        raw_rows_read = groups["raw_rows"]
        rows_by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in raw_rows_read:
            if row.get("row_identity"):
                rows_by_identity[str(row["row_identity"])].append(row)
        for identity, identity_rows in sorted(rows_by_identity.items()):
            if len(identity_rows) <= 1:
                continue
            aggregate_rows = [row for row in identity_rows if _is_aggregate_raw_path(Path(str(row["source_path"])))]
            slot_rows = [row for row in identity_rows if _is_slot_raw_path(Path(str(row["source_path"])))]
            fingerprints = {_raw_fingerprint(row) for row in identity_rows}
            expected_mirror = len(identity_rows) == 2 and len(aggregate_rows) == len(slot_rows) == len(fingerprints) == 1
            if expected_mirror:
                _diag(
                    diagnostics,
                    root=root,
                    path=root,
                    code="expected_mirror",
                    message="aggregate_and_per_slot_raw_rows_match",
                    row_identity=identity,
                    source_paths=sorted(str(row["source_path"]) for row in identity_rows),
                )
            else:
                _diag(
                    diagnostics,
                    root=root,
                    path=root,
                    code="duplicate_identity",
                    message="duplicate_raw_row_identity",
                    row_identity=identity,
                    source_paths=sorted(str(row["source_path"]) for row in identity_rows),
                )
                if len(fingerprints) > 1:
                    _diag(
                        diagnostics,
                        root=root,
                        path=root,
                        code="duplicate_payload_conflict",
                        message="duplicate_raw_row_identity_has_conflicting_payloads",
                        row_identity=identity,
                    )
        # Aggregate rows and per-slot copies are both evidence locations, but
        # an identity is one measurement row.  Keep one canonical row for
        # denominator/pair calculations and report duplicates above.
        canonical_by_identity: dict[str, dict[str, Any]] = {}
        identityless: list[dict[str, Any]] = []
        for row in raw_rows_read:
            identity = str(row.get("row_identity", ""))
            if identity:
                canonical_by_identity.setdefault(identity, row)
            else:
                identityless.append(row)
        raw_rows = list(canonical_by_identity.values()) + identityless
        statuses: dict[str, set[str]] = defaultdict(set)
        for row in raw_rows_read:
            if row.get("row_identity"):
                statuses[str(row["row_identity"])].add(str(row.get("status")))
            terminal = row.get("terminal_class")
            if terminal not in TERMINAL_CLASSES and terminal not in {None, "", "not_started"}:
                _diag(diagnostics, root=root, path=Path(str(row["source_path"])), code="conflicting_status", message="unknown_terminal_class", row_identity=row.get("row_identity"), terminal_class=terminal)
        for identity, values in statuses.items():
            if len(values) > 1:
                _diag(diagnostics, root=root, path=root, code="conflicting_status", message="identity_has_multiple_statuses", row_identity=identity, statuses=sorted(values))
        planned = [slot for manifest in groups["manifest"] for slot in (manifest.get("planned_slots") or manifest.get("slots") or []) if isinstance(slot, Mapping)]
        planned_ids = list(dict.fromkeys(str(slot.get("slot_id", "")) for slot in planned if str(slot.get("slot_id", ""))))
        observed_ids = [str(row.get("slot_id", "")) for row in raw_rows if str(row.get("slot_id", ""))]
        missing = sorted(set(planned_ids) - set(observed_ids))
        extra = sorted(set(observed_ids) - set(planned_ids)) if planned_ids else []
        duplicate_slots = sorted({item for item in observed_ids if observed_ids.count(item) > 1})
        if missing:
            _diag(diagnostics, root=root, path=root, code="missing_field", message="planned_slot_missing_raw_row", slot_ids=missing)
        if extra:
            _diag(diagnostics, root=root, path=root, code="wrong_scope", message="raw_row_not_in_planned_slots", slot_ids=extra)
        if duplicate_slots:
            _diag(diagnostics, root=root, path=root, code="duplicate_identity", message="duplicate_slot_identity", slot_ids=duplicate_slots)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in raw_rows:
            if row.get("pair_id"):
                grouped[str(row["pair_id"])].append(row)
        for pair_id, pair_rows in sorted(grouped.items()):
            lanes = {str(row.get("lane", "")): row for row in pair_rows}
            all_pairs.append({"source_root": str(root), "pair_id": pair_id, "lanes": sorted(lanes), "join_status": "joined" if len(lanes) == 4 and len(pair_rows) == 4 else "partial"})
        terminal_counts = Counter(str(row.get("terminal_class")) for row in raw_rows)
        metrics: dict[str, Any] = {}
        for name in ("provider_latency_ms", "e2e_latency_ms", "evaluation_latency_ms", "embedding_latency_ms", "tool_latency_ms", "writer_latency_ms"):
            values = [row.get("raw_payload", {}).get(name) for row in raw_rows]
            observed = [value for value in values if _finite_metric(value)]
            metrics[name] = {"status": "observed" if observed else "missing", "count": len(observed), "value": None if not observed else observed}
        root_summaries.append({"source_root": str(root), "file_count": sum(1 for _ in _iter_files(root)), "record_counts": {key: len(value) for key, value in groups.items()}, "raw_rows_read": len(raw_rows_read), "canonical_raw_row_count": len(raw_rows), "planned_count": len(planned_ids), "observed_raw_count": len(raw_rows), "missing_slot_count": len(missing), "extra_slot_count": len(extra), "duplicate_slot_count": len(duplicate_slots), "terminal_class_counts": dict(terminal_counts), "metric_availability": metrics, "pairs": [pair for pair in all_pairs if pair["source_root"] == str(root)]})
    blocking_diagnostics = sum(item["code"] != "expected_mirror" for item in diagnostics)
    summary = {"schema_version": "statebus.artifact_analysis_summary.v2", "schema_profile": schema_profile, "source_roots": [str(root) for root in roots], "path_maps": [{"container_prefix": left, "host_prefix": right} for left, right in path_maps], "file_count": file_count, "record_counts": {key: sum(len(groups[key]) for groups in by_root.values()) for key in {kind for groups in by_root.values() for kind in groups}}, "root_summaries": root_summaries, "pair_count": len(all_pairs), "joined_pair_count": sum(pair["join_status"] == "joined" for pair in all_pairs), "diagnostic_count": len(diagnostics), "blocking_diagnostic_count": blocking_diagnostics, "diagnostic_counts": dict(Counter(item["code"] for item in diagnostics)), "recorded_status": "observed_artifacts_only", "audited_gate_status": "inconclusive" if blocking_diagnostics else "recomputed_without_blocking_diagnostics", "unsupported_formats": ["sqlite3"], "hashes_computed": False, "summary_to_raw_fallback": False}
    report_lines = ["# Artifact analysis", "", f"- schema profile: `{schema_profile}`", f"- roots: {len(roots)}", f"- files: {file_count}", f"- diagnostics: {len(diagnostics)}", f"- pairs: {len(all_pairs)}", "", "## Root isolation", ""]
    for item in root_summaries:
        report_lines.append(f"- `{item['source_root']}`: raw={item['observed_raw_count']} planned={item['planned_count']} missing={item['missing_slot_count']} extra={item['extra_slot_count']}")
    report_lines.extend(["", "## Diagnostics", ""])
    report_lines.extend(f"- `{item['code']}` `{item['source_path']}`: {item['message']}" for item in diagnostics)
    (output / "artifact_analysis_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "artifact_analysis_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    with (output / "diagnostics.jsonl").open("w", encoding="utf-8") as handle:
        for item in diagnostics:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze Stage 2 artifacts without executing them")
    parser.add_argument("--artifact-root", action="append", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--schema-profile", default="auto", choices=sorted(SCHEMA_PROFILES))
    parser.add_argument("--path-map", action="append", default=[], metavar="CONTAINER_PREFIX=HOST_PREFIX")
    args = parser.parse_args()
    maps: list[tuple[str, str]] = []
    for item in args.path_map:
        if "=" not in item:
            parser.error(f"invalid --path-map: {item}")
        maps.append(tuple(item.split("=", 1)))
    analyze_artifacts(artifact_roots=args.artifact_root, output_root=args.output_root, schema_profile=args.schema_profile, path_maps=maps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
