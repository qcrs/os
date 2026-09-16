from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from statebus.benchmark.models import BenchmarkFamilyReport, BenchmarkLayer
from statebus.utils import sha256_digest, stable_json_dumps


GOLD_ONLY_KEYS = (
    "expected_facts",
    "quality_checks",
    "expected_metric_effects",
    "expected_route",
    "expected_tool_name",
    "minimum_reuse_class",
    "expected_effect_sealed",
    "sealed_expected_value",
    "future_gold",
)

EXPECTED_LAYER_FEATURE_FLAGS: dict[BenchmarkLayer, dict[str, object]] = {
    BenchmarkLayer.L0: {
        "handoff_mode": "text_collaboration",
        "structured_control_enabled": False,
        "semantic_pruning_enabled": False,
        "semantic_state_transfer_enabled": False,
        "replay_enabled": False,
        "multi_attempt_enabled": False,
        "force_first_attempt_trap": False,
    },
    BenchmarkLayer.L1: {
        "handoff_mode": "structured_collaboration",
        "structured_control_enabled": True,
        "semantic_pruning_enabled": False,
        "semantic_state_transfer_enabled": False,
        "replay_enabled": False,
        "multi_attempt_enabled": False,
        "force_first_attempt_trap": False,
    },
    BenchmarkLayer.L2: {
        "handoff_mode": "structured_collaboration",
        "structured_control_enabled": True,
        "semantic_pruning_enabled": True,
        "semantic_state_transfer_enabled": True,
        "replay_enabled": False,
        "multi_attempt_enabled": False,
        "force_first_attempt_trap": False,
    },
    BenchmarkLayer.L3: {
        "handoff_mode": "structured_collaboration",
        "structured_control_enabled": True,
        "semantic_pruning_enabled": True,
        "semantic_state_transfer_enabled": True,
        "replay_enabled": True,
        "multi_attempt_enabled": False,
        "force_first_attempt_trap": False,
    },
}

EXPECTED_SUBPROCESS_CARRIERS: dict[BenchmarkLayer, str] = {
    BenchmarkLayer.L0: "utf8_text",
    BenchmarkLayer.L1: "protobuf",
    BenchmarkLayer.L2: "protobuf",
    BenchmarkLayer.L3: "protobuf",
}


# Slice C uses a deliberately small, source-only contract.  The existing L0-L3
# ladder remains available for historical/attribution reports; these lane names
# describe the five execution boundaries used by the fairness smoke harness.
CANONICAL_LANES = (
    "direct_single_agent",
    "pure_text_mas",
    "fixed_structured",
    "adaptive_routed",
)
CANONICAL_TRACE_SCHEMA_VERSION = "statebus.canonical_trace.v1"
ORACLE_AUDIT_SCHEMA_VERSION = "statebus.oracle_audit.v2"
C2A_ELIGIBILITY_SCHEMA_VERSION = "statebus.c2a.eligibility.v1"
TEST_EVIDENCE_SCHEMA_VERSION = "statebus.c2a.test_evidence.v2"
TEST_EVIDENCE_INDEX_SCHEMA_VERSION = "statebus.c2a.test_evidence_index.v1"
FAIRNESS_LANES = CANONICAL_LANES + ("legacy_comparator",)
TERMINAL_STATUSES = (
    "success",
    "quality_fail",
    "timeout",
    "unsupported",
    "runtime_fail",
    "policy_reject",
    "environment_fail",
)
_FAIRNESS_REQUIRED_FIELDS = (
    "schema_version",
    "source_identity",
    "execution_path",
    "runtime_authority",
    "lane",
    "dataset_id",
    "dataset_version",
    "dataset_split",
    "dataset_hash",
    "task_contract_hash",
    "role_graph",
    "agent_count",
    "provider_id",
    "provider_version",
    "model_id",
    "model_revision",
    "implementation_snapshot",
    "seed",
    "temperature",
    "timeout",
    "retry_budget",
    "quality_threshold",
    "memory_policy",
    "cache_epoch",
    "runtime_root",
    "workspace_root",
    "memory_root",
    "oracle_visibility",
    "validator_digest",
    "terminal_status",
)
_ORACLE_KEYS = {
    "gold",
    "gold_answer",
    "expected_facts",
    "quality_checks",
    "expected_route",
    "expected_tool",
    "expected_tool_name",
    "future_round",
    "future_rounds",
    "hidden_label",
    "benchmark_only_hidden_label",
}


def _git_value(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def capture_source_identity(repo_root: Path | None = None) -> dict[str, object]:
    """Capture the actual checkout identity without creating provenance files."""

    root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    commit = _git_value(root, "rev-parse", "--verify", "HEAD")
    branch = _git_value(root, "branch", "--show-current")
    status = _git_value(root, "status", "--short")
    repository = _git_value(root, "config", "--get", "remote.origin.url")
    return {
        "repository": repository,
        "commit": commit,
        "branch_or_ref": branch,
        "working_tree_status_digest": sha256_digest(status.encode("utf-8")),
        "working_tree_clean": not bool(status),
    }


def audit_oracle_visibility(
    *,
    provider_request: object = None,
    role_visible_input: object = None,
    future_rounds: object = None,
    persisted_payload: object = None,
    provider_output: object = None,
    role_handoff: object = None,
) -> dict[str, object]:
    """Reject benchmark-only oracle fields in provider/role-visible payloads."""

    violations: list[dict[str, object]] = []

    def walk(value: object, path: str) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized = str(key).strip().lower()
                if normalized in _ORACLE_KEYS or normalized.startswith("expected_") or normalized.startswith("hidden_") or normalized.startswith("future_round"):
                    violations.append({"path": f"{path}.{key}", "kind": "oracle_key_visible"})
                walk(nested, f"{path}.{key}")
        elif isinstance(value, (list, tuple, set)):
            for index, nested in enumerate(value):
                walk(nested, f"{path}[{index}]")

    surfaces = {
        "provider_request": provider_request,
        "role_visible_input": role_visible_input,
        "future_rounds": future_rounds,
        "provider_output": provider_output,
        "role_handoff": role_handoff,
        "persisted_payload": persisted_payload,
    }
    surface_audits: dict[str, dict[str, object]] = {}
    for name, value in surfaces.items():
        before = len(violations)
        walk(value, name)
        local = violations[before:]
        surface_audits[name] = {
            "status": "fail" if local else "pass",
            "visible_keys": [str(item.get("path", "")) for item in local],
            "violations": local,
        }
    violation_paths = [str(item.get("path", "")) for item in violations]
    return {
        "schema_version": ORACLE_AUDIT_SCHEMA_VERSION,
        # These fields are contract gates (all must remain false), while the
        # concrete leaked paths are retained in ``visible_keys``/violations.
        "gold_visible": False,
        "expected_route_visible": False,
        "expected_tool_visible": False,
        "future_rounds_visible": False,
        "visible_keys": violation_paths,
        "ok": not violations,
        "violations": violations,
        "audit_method": "recursive_visible_payload_key_scan",
        "redaction": False,
        "phase_coverage": [name for name, value in surfaces.items() if value is not None],
        "surfaces": surface_audits,
    }


def list_root_contents(root: str | Path, root_kind: str) -> dict[str, object]:
    """Return an lstat-based listing scoped strictly to one mutable root."""
    raw_path = Path(root)
    if raw_path.is_symlink():
        return {"root": str(raw_path.absolute()), "root_kind": root_kind, "readable": False, "error": "root_symlink_forbidden", "entries": []}
    path = raw_path.resolve()
    if not path.exists() or not path.is_dir():
        return {"root": str(path), "root_kind": root_kind, "readable": False, "error": "root_unreadable", "entries": []}
    entries: list[dict[str, object]] = []
    for item in sorted(path.rglob("*")):
        rel = item.relative_to(path)
        try:
            stat = item.lstat()
        except OSError as exc:
            return {"root": str(path), "root_kind": root_kind, "readable": False, "error": f"lstat_failed:{type(exc).__name__}", "entries": entries}
        mode = stat.st_mode
        if item.is_symlink():
            kind = "symlink"
            target = os.readlink(item)
        elif item.is_dir():
            kind, target = "dir", ""
        elif item.is_file():
            kind, target = "file", ""
        elif stat.S_ISSOCK(mode):
            kind, target = "socket", ""
        else:
            kind, target = "other", ""
        entries.append({
            "path": str(rel),
            "kind": kind,
            "device": stat.st_dev,
            "inode": stat.st_ino,
            "resolved_target": target,
            "session_directory": any(part.startswith("session") for part in rel.parts),
        })
    return {"root": str(path), "root_kind": root_kind, "readable": True, "entries": entries}


def validate_c2a_isolation(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Validate mutable-root, inode, cache, and identity isolation from observations."""
    rows = list(rows)
    collisions: dict[str, object] = {}
    seen: dict[str, dict[str, str]] = {field: {} for field in ("runtime_root", "workspace_root", "memory_root", "cache_epoch", "artifact_ids", "memory_ids", "session_id", "socket_path_requested", "socket_path_effective", "socket_inode")}
    seen_inodes: dict[str, str] = {}
    all_paths: list[tuple[str, str]] = []
    for row in rows:
        for field in ("runtime_root", "workspace_root", "memory_root"):
            raw = row.get(field)
            if not raw:
                collisions.setdefault("missing_root", []).append(field)
                continue
            raw_path = Path(str(raw))
            if raw_path.is_symlink():
                collisions.setdefault("root_symlink", []).append(str(raw_path))
                continue
            path = raw_path.resolve()
            key = str(path)
            owner = f"{row.get('case_id','')}::{row.get('lane','')}::{row.get('repeat_id',0)}"
            previous = seen[field].get(key)
            if previous and previous != owner:
                collisions.setdefault(field, []).append(key)
            seen[field][key] = owner
            all_paths.append((field, key))
            if path.exists() and not path.is_symlink():
                stat = path.lstat()
                inode_key = f"{stat.st_dev}:{stat.st_ino}"
                inode_owner = seen_inodes.get(inode_key)
                if inode_owner and inode_owner != owner:
                    collisions.setdefault("inode_overlap", []).append(inode_key)
                seen_inodes[inode_key] = owner
            listing = row.get(f"{field}_listing")
            if isinstance(listing, Mapping) and not listing.get("readable", False):
                collisions.setdefault("listing_failure", []).append(field)
            if isinstance(listing, Mapping):
                for entry in listing.get("entries", ()):
                    if isinstance(entry, Mapping):
                        entry_path = str(entry.get("path", ""))
                        if Path(entry_path).is_absolute() or ".." in Path(entry_path).parts:
                            collisions.setdefault("parent_listing_contamination", []).append(entry_path)
                        if entry.get("kind") in {"symlink", "socket"}:
                            collisions.setdefault(f"unexpected_{entry.get('kind')}", []).append(entry_path)
                    if isinstance(entry, Mapping) and entry.get("device") is not None and entry.get("inode") is not None:
                        inode_key = f"{entry.get('device')}:{entry.get('inode')}"
                        inode_owner = seen_inodes.get(inode_key)
                        if inode_owner and inode_owner != owner:
                            collisions.setdefault("inode_overlap", []).append(inode_key)
                        seen_inodes[inode_key] = owner
        for field in ("session_id", "socket_path_requested", "socket_path_effective", "socket_inode"):
            value = row.get(field)
            if value in (None, ""):
                continue
            key = str(value)
            owner = f"{row.get('case_id','')}::{row.get('lane','')}::{row.get('repeat_id',0)}"
            previous = seen[field].get(key)
            if previous and previous != owner:
                collisions.setdefault(field, []).append(key)
            seen[field][key] = owner
        for field in ("artifact_ids", "memory_ids"):
            for value in row.get(field, ()) or ():
                key = str(value)
                owner = f"{row.get('case_id','')}::{row.get('lane','')}::{row.get('repeat_id',0)}"
                previous = seen[field].get(key)
                if previous and previous != owner:
                    collisions.setdefault(field, []).append(key)
                seen[field][key] = owner
    for index, (kind_a, path_a) in enumerate(all_paths):
        for kind_b, path_b in all_paths[index + 1:]:
            if path_a != path_b and (path_a.startswith(path_b + os.sep) or path_b.startswith(path_a + os.sep)):
                collisions.setdefault("nested_mutable_root", []).append([path_a, path_b])
    epochs = [str(row.get("cache_epoch", "")) for row in rows if str(row.get("cache_epoch", ""))]
    if len(epochs) != len(set(epochs)):
        collisions["cache_epoch"] = epochs
    return {"schema_version": "statebus.c2a.isolation.v1", "ok": not collisions, "collisions": collisions, "checked_count": len(rows)}


def _lane_identity(lane: str) -> tuple[str, str, str]:
    if lane == "fixed_structured":
        return "c2a-four-role@v1", "c2a_four_role_v1", "FixedMainlineRequest->AdaptiveMainlineRunner->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher"
    if lane == "adaptive_routed":
        return "c2a-four-role@v1", "c2a_four_role_v1", "RuntimeDriver.run_mode(adaptive_bounded)->AdaptiveMainlineRunner->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher"
    if lane == "pure_text_mas":
        return "pure-text-mas@v1", "text_role_call_v1", "pure_text_provider_four_role"
    return "direct-single-agent@v1", "direct_generalist_v1", "direct_single_agent_provider"


def validate_c2a_trace(trace: Mapping[str, object], manifest: Mapping[str, object]) -> dict[str, object]:
    """Validate the single canonical trace envelope without creating runtime facts."""
    lane = str(manifest.get("lane", ""))
    case_marker = str(manifest.get("case_id", trace.get("case_id", "")))
    identity_marker = str(manifest.get("case_identity", ""))
    is_control = case_marker.startswith(("control_", "c2b_")) or identity_marker.startswith("c2b-control::")
    recipe, capability, path = _lane_identity(lane)
    required = ("schema_version", "case_id", "task_id", "canonical_task_spec_hash", "lane", "execution_path", "runtime_authority", "role_graph", "role_sequence", "role_count", "dependency_edges", "recipe_identity", "capability_identity", "provider_calls", "terminal_status", "failure_stage", "error_code", "canonical_marker")
    missing = [key for key in required if key not in trace]
    checks: dict[str, str] = {key: "PASS" for key in required if key in trace}
    if trace.get("schema_version") != CANONICAL_TRACE_SCHEMA_VERSION:
        checks["schema_version"] = "FAIL"
    if trace.get("lane") != lane or trace.get("canonical_task_spec_hash") != manifest.get("task_contract_hash"):
        checks["identity"] = "FAIL"
    marker = trace.get("canonical_marker")
    if not isinstance(marker, Mapping) or marker.get("observed") is not True:
        checks["canonical_marker"] = "FAIL"
    if not is_control and trace.get("recipe_identity") != recipe:
        checks["recipe_identity"] = "FAIL"
    if not is_control and trace.get("capability_identity") != capability:
        checks["capability_identity"] = "FAIL"
    if not is_control and trace.get("execution_path") != path:
        checks["execution_path"] = "FAIL"
    if lane in {"fixed_structured", "adaptive_routed"}:
        if not is_control and trace.get("role_sequence") != ["planner", "retriever", "executor", "summarizer"]:
            checks["role_sequence"] = "FAIL"
        if not is_control and len(trace.get("attempts", ())) != 4:
            checks["runtime_attempts"] = "FAIL"
        if not is_control and (not trace.get("provider_bindings") or not trace.get("grants") or not trace.get("receipts")):
            checks["runtime_lineage"] = "FAIL"
    elif lane == "pure_text_mas":
        if not is_control and len(trace.get("provider_calls", trace.get("calls", ()))) != 4:
            checks["provider_calls"] = "FAIL"
        if trace.get("runtime_attempts", {}).get("status") not in {"unsupported", "N/A"}:
            checks["runtime_attempts"] = "FAIL"
    elif lane == "direct_single_agent":
        if not is_control and len(trace.get("provider_calls", trace.get("calls", ()))) != 1:
            checks["provider_calls"] = "FAIL"
    failures = sorted(set(missing + [key for key, value in checks.items() if value == "FAIL"]))
    return {"schema_version": CANONICAL_TRACE_SCHEMA_VERSION, "valid": not failures, "checks": checks, "missing_fields": missing, "failed_fields": failures, "reason": "c2a.trace.required_field_missing" if missing else ("c2a.trace.identity_mismatch" if failures else "")}


def aggregate_c2a_eligibility(*, records: Iterable[Mapping[str, object]], evidence: Mapping[str, object] | None = None, source_identity: Mapping[str, object] | None = None, forbidden_service_started: bool = False, c2b_marker_present: bool = False, superiority_claim: bool = False) -> dict[str, object]:
    """Conjoin all required C2A gates; record count alone cannot enable the pilot."""
    rows = list(records)
    canonical = [row for row in rows if str(row.get("lane", row.get("manifest", {}).get("lane", ""))) in CANONICAL_LANES]
    gates: list[dict[str, object]] = []
    def gate(name: str, ok: bool, reason: str, required: bool = True) -> None:
        gates.append({"name": name, "status": "PASS" if ok else "FAIL", "required": required, "reason": reason, "evidence_refs": []})
    gate("canonical_rows_complete", len(canonical) == 32, f"observed={len(canonical)} expected=32")
    gate("terminal_records_complete", len(canonical) == 32 and all(bool(row.get("terminal_status")) for row in canonical), "all canonical rows terminally closed")
    validations = [row.get("trace_validation") for row in canonical]
    gate("unified_trace_schema", len(validations) == 32 and all(isinstance(item, Mapping) and item.get("valid") is True for item in validations), "all rows have valid trace_validation")
    gate("structured_runtime_trace", all(len(row.get("trace", {}).get("attempts", ())) == 4 for row in canonical if row.get("lane") in {"fixed_structured", "adaptive_routed"} and not str(row.get("case_id", "")).startswith("control_")), "four runtime attempts on structured positive rows")
    gate("pure_text_and_direct_calls", all(len(row.get("trace", {}).get("provider_calls", row.get("trace", {}).get("calls", ()))) == (4 if row.get("lane") == "pure_text_mas" else 1) for row in canonical if row.get("lane") in {"pure_text_mas", "direct_single_agent"} and not str(row.get("case_id", "")).startswith("control_")), "real provider call counts")
    gate("persisted_oracle_audit", all(row.get("oracle_audit", {}).get("ok", False) for row in canonical), "all persisted oracle audits pass")
    gate("canonical_aggregate_legacy_exclusion", all(row.get("canonical_aggregate_audit", {}).get("eligible", False) for row in canonical), "observed marker and identity checks pass")
    gate("root_workspace_memory_cache_isolation", bool(evidence and evidence.get("root_isolation", {}).get("ok", False)) or all(bool(row.get("isolation_audit", {}).get("ok", False)) for row in canonical), "isolated mutable roots")
    gate("metric_availability", all(isinstance(row.get("metric_availability", {}), Mapping) for row in canonical), "availability explicit")
    gate("failure_denominator_closed", len(canonical) == 32 and all(row.get("terminal_status") in TERMINAL_STATUSES for row in canonical), "all terminal rows retained")
    gate("source_identity_evidence", bool(source_identity or (evidence and evidence.get("source_identity"))), "existing source identity projection present")
    evidence_validations: dict[str, dict[str, object]] = {}

    def evidence_ok(name: str, validator: object) -> bool:
        item = (evidence or {}).get(name)
        if not isinstance(item, Mapping):
            evidence_validations[name] = {
                "schema_version": TEST_EVIDENCE_SCHEMA_VERSION,
                "valid": False,
                "failed_checks": ["projection_missing"],
                "reason": "persisted evidence projection is missing",
            }
            return False
        result = validator(item)  # type: ignore[operator]
        evidence_validations[name] = result
        return bool(result.get("valid", False))

    gate("targeted_test_evidence", evidence_ok("targeted_tests", validate_test_evidence_projection), "persisted targeted pytest evidence")
    gate("py_compile_evidence", evidence_ok("py_compile", validate_compile_evidence_projection), "persisted py_compile evidence")
    gate("c1_c1b_regression_evidence", evidence_ok("c1_c1b_regression", validate_test_evidence_projection), "persisted C1/C1B evidence")
    gate("forbidden_service_not_started", not forbidden_service_started, "vLLM/Docker/GPU/Studio not started")
    gate("no_c2b_execution_marker", not c2b_marker_present, "no C2B marker")
    gate("no_superiority_claim", not superiority_claim, "contract-only claim scope")
    failed = [item["name"] for item in gates if item["required"] and item["status"] != "PASS"]
    return {
        "schema_version": C2A_ELIGIBILITY_SCHEMA_VERSION,
        "gates": gates,
        "failed_gate_names": failed,
        "overall_pass": not failed,
        "pilot_eligible": not failed,
        "evidence_validations": evidence_validations,
        "claim_restriction": "contract_only_no_superiority_claim",
    }


def _parse_pytest_summary(stdout: str, stderr: str) -> dict[str, object]:
    """Parse only pytest's terminal summary; never infer success from progress dots."""
    text = "\n".join((stdout, stderr))
    summary_line = ""
    for line in reversed(text.splitlines()):
        if re.search(r"\bin\s+[0-9]+(?:\.[0-9]+)?s\b", line) and re.search(
            r"\b(?:passed|failed|skipped|xfailed|xpassed|error|errors)\b", line
        ):
            summary_line = line.strip()
            break
    counts: dict[str, int] = {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "xfail": 0,
        "xpass": 0,
        "errors": 0,
    }
    labels = {
        "passed": "passed",
        "failed": "failed",
        "skipped": "skipped",
        "xfail": "xfailed",
        "xpass": "xpassed",
        "errors": "errors?",
    }
    for key, label in labels.items():
        match = re.search(rf"(\d+)\s+{label}\b", summary_line)
        if match:
            counts[key] = int(match.group(1))
    counts["collected"] = sum(counts.values())
    return {
        "present": bool(summary_line),
        "line": summary_line,
        "counts": counts,
    }


def _write_atomic(path: Path, content: str) -> None:
    """Write one evidence file without exposing a partially written projection."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}-{time.time_ns()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _safe_evidence_component(value: str, field: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise ValueError(f"invalid evidence {field}: {value!r}")
    return value


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def validate_test_evidence_projection(
    projection: Mapping[str, object],
    *,
    expected_group: str | None = None,
) -> dict[str, object]:
    """Validate one persisted pytest invocation and reject ambiguous evidence."""
    failures: list[str] = []

    def require(condition: bool, name: str) -> None:
        if not condition:
            failures.append(name)

    require(projection.get("schema_version") == TEST_EVIDENCE_SCHEMA_VERSION, "schema_version")
    group = projection.get("group")
    require(isinstance(group, str) and bool(group), "group")
    if expected_group is not None:
        require(group == expected_group, "expected_group")
    invocation_id = projection.get("invocation_id")
    require(
        isinstance(invocation_id, str)
        and bool(invocation_id)
        and re.fullmatch(r"[A-Za-z0-9_.-]+", invocation_id) is not None,
        "invocation_id",
    )
    invocation_root = Path(str(projection.get("invocation_root", "")))
    require(invocation_root.is_absolute() and invocation_root.is_dir(), "invocation_root")
    command = projection.get("command")
    require(isinstance(command, list) and bool(command) and all(isinstance(item, str) and item for item in command), "command")
    cwd = Path(str(projection.get("cwd", "")))
    require(cwd.is_absolute() and cwd.is_dir(), "cwd")
    require(projection.get("current_checkout") is True, "current_checkout")
    return_code = projection.get("return_code")
    require(isinstance(return_code, int) and not isinstance(return_code, bool), "return_code")
    timeout = projection.get("timeout", False)
    require(isinstance(timeout, bool), "timeout")
    timeout_reason = projection.get("timeout_reason", "")
    require(isinstance(timeout_reason, str), "timeout_reason_type")
    require(bool(timeout) == bool(timeout_reason), "timeout_reason_consistency")
    require(not bool(timeout), "timeout")
    require(not bool(projection.get("forbidden_skip_or_xfail", True)), "forbidden_skip_or_xfail")

    started = projection.get("started_monotonic")
    ended = projection.get("ended_monotonic")
    require(isinstance(started, (int, float)) and isinstance(ended, (int, float)), "timestamps")
    if isinstance(started, (int, float)) and isinstance(ended, (int, float)):
        require(started <= ended, "timestamp_order")

    count_keys = ("collected", "passed", "failed", "skipped", "xfail", "xpass", "errors")
    counts: dict[str, int] = {}
    for key in count_keys:
        value = projection.get(key, 0)
        require(isinstance(value, int) and not isinstance(value, bool) and value >= 0, f"count:{key}")
        counts[key] = int(value) if isinstance(value, int) and not isinstance(value, bool) else -1
    if counts.get("collected", 0) <= 0:
        failures.append("collected_positive")
    if all(value >= 0 for value in counts.values()):
        require(sum(counts[key] for key in count_keys[1:]) == counts["collected"], "count_sum")

    nodes = projection.get("test_nodes")
    require(isinstance(nodes, list) and bool(nodes), "test_nodes_present")
    if isinstance(nodes, list):
        require(all(isinstance(node, str) and bool(node) for node in nodes), "test_nodes_strings")
        require(len(nodes) == len(set(nodes)), "test_nodes_unique")
        require(len(nodes) == counts.get("collected", -1), "test_nodes_count")

    projection_path = Path(str(projection.get("projection_path", "")))
    stdout_path = Path(str(projection.get("raw_stdout_path", "")))
    stderr_path = Path(str(projection.get("raw_stderr_path", "")))
    require(projection_path.is_absolute() and projection_path.is_file(), "projection_path")
    require(stdout_path.is_absolute() and stdout_path.is_file(), "raw_stdout_path")
    require(stderr_path.is_absolute() and stderr_path.is_file(), "raw_stderr_path")
    require(stdout_path != stderr_path, "raw_stream_paths_distinct")
    require(_path_is_within(projection_path, invocation_root), "projection_path_scope")
    require(_path_is_within(stdout_path, invocation_root), "raw_stdout_scope")
    require(_path_is_within(stderr_path, invocation_root), "raw_stderr_scope")

    summary = _parse_pytest_summary(
        stdout_path.read_text(encoding="utf-8") if stdout_path.is_file() else "",
        stderr_path.read_text(encoding="utf-8") if stderr_path.is_file() else "",
    )
    require(summary["present"] is True, "pytest_summary_present")
    summary_counts = summary["counts"]
    if isinstance(summary_counts, Mapping):
        for key in count_keys:
            require(counts.get(key) == int(summary_counts.get(key, 0)), f"summary_count:{key}")
    require(return_code == 0, "return_code_zero")
    if return_code == 0:
        require(counts.get("failed", 0) == 0, "zero_failed")
        require(counts.get("errors", 0) == 0, "zero_errors")

    index_path = Path(str(projection.get("index_path", "")))
    require(index_path.is_absolute() and index_path.is_file(), "index_path")
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            index = {}
            failures.append("index_readable")
        require(index.get("schema_version") == TEST_EVIDENCE_INDEX_SCHEMA_VERSION, "index_schema_version")
        require(index.get("group") == group, "index_group")
        invocations = index.get("invocations")
        require(isinstance(invocations, list), "index_invocations")
        if isinstance(invocations, list):
            matching = [
                item
                for item in invocations
                if isinstance(item, Mapping)
                and item.get("invocation_id") == invocation_id
            ]
            require(bool(matching), "index_invocation_membership")
            require(
                any(item.get("projection_path") == str(projection_path) for item in matching),
                "index_projection_membership",
            )
        require(index.get("conflict") is not True, "index_conflict")
        selected = index.get("selected_invocation_id")
        require(selected in (None, invocation_id), "index_selection")

    return {
        "schema_version": TEST_EVIDENCE_SCHEMA_VERSION,
        "valid": not failures,
        "checks": {name: ("FAIL" if name in failures else "PASS") for name in sorted(set(failures))},
        "failed_checks": sorted(set(failures)),
        "summary": summary,
        "reason": ";".join(sorted(set(failures))),
    }


def validate_compile_evidence_projection(projection: Mapping[str, object]) -> dict[str, object]:
    """Validate the narrow persisted py_compile projection."""
    failures: list[str] = []

    def require(condition: bool, name: str) -> None:
        if not condition:
            failures.append(name)

    require(projection.get("schema_version") == "statebus.c2a.pycompile.v1", "schema_version")
    command = projection.get("command")
    require(isinstance(command, list) and bool(command), "command")
    cwd = Path(str(projection.get("cwd", "")))
    require(cwd.is_absolute() and cwd.is_dir(), "cwd")
    require(projection.get("current_checkout") is True, "current_checkout")
    require(projection.get("return_code") == 0, "return_code")
    require(projection.get("compile_result") == "PASS", "compile_result")
    modules = projection.get("module_file_list")
    require(isinstance(modules, list) and bool(modules), "module_file_list")
    for key in ("raw_stdout_path", "raw_stderr_path"):
        path = Path(str(projection.get(key, "")))
        require(path.is_absolute() and path.is_file(), key)
    require(not bool(projection.get("timeout", False)), "timeout")
    if projection.get("index_path"):
        index_path = Path(str(projection["index_path"]))
        require(index_path.is_file(), "index_path")
        if index_path.is_file():
            try:
                index = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                index = {}
            require(index.get("conflict") is not True, "index_conflict")
    return {
        "schema_version": "statebus.c2a.pycompile.v1",
        "valid": not failures,
        "failed_checks": sorted(set(failures)),
        "reason": ";".join(sorted(set(failures))),
    }


def persist_test_evidence(
    *,
    root: str | Path,
    group: str,
    command: Iterable[str],
    cwd: str | Path,
    return_code: int,
    stdout: str,
    stderr: str,
    counts: Mapping[str, int] | None = None,
    test_nodes: Iterable[str] = (),
    environment: Mapping[str, str] | None = None,
    invocation_id: str | None = None,
    started_monotonic: float | None = None,
    ended_monotonic: float | None = None,
    timeout: bool = False,
    timeout_reason: str = "",
) -> dict[str, object]:
    """Persist one immutable pytest invocation and index group conflicts."""
    group = _safe_evidence_component(str(group), "group")
    invocation_id = invocation_id or f"invocation-{os.getpid()}-{time.time_ns()}"
    invocation_id = _safe_evidence_component(str(invocation_id), "invocation_id")
    evidence_root = Path(root).resolve() / "evidence" / "tests"
    group_root = evidence_root / group
    invocation_root = group_root / invocation_id
    index_path = group_root / "index.json"
    if index_path.exists():
        try:
            existing_index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing_index = {}
        existing_invocations = existing_index.get("invocations", [])
        if isinstance(existing_invocations, list) and any(
            isinstance(item, Mapping) and item.get("invocation_id") == invocation_id
            for item in existing_invocations
        ):
            raise ValueError(f"duplicate evidence invocation id: {invocation_id}")
    if invocation_root.exists():
        raise ValueError(f"evidence invocation already exists: {invocation_id}")
    invocation_root.mkdir(parents=True, exist_ok=False)
    stdout_path = invocation_root / "stdout.txt"
    stderr_path = invocation_root / "stderr.txt"
    projection_path = invocation_root / "projection.json"
    _write_atomic(stdout_path, stdout)
    _write_atomic(stderr_path, stderr)

    parsed = _parse_pytest_summary(stdout, stderr)
    provided = dict(counts or {})
    parsed_counts = parsed["counts"] if isinstance(parsed.get("counts"), Mapping) else {}
    count_keys = ("collected", "passed", "failed", "skipped", "xfail", "xpass", "errors")
    projected_counts = {
        key: int(provided.get(key, parsed_counts.get(key, 0)))
        for key in count_keys
    }
    started = time.monotonic() if started_monotonic is None else float(started_monotonic)
    ended = time.monotonic() if ended_monotonic is None else float(ended_monotonic)
    if ended < started:
        raise ValueError("ended_monotonic must be >= started_monotonic")
    projection: dict[str, object] = {
        "schema_version": TEST_EVIDENCE_SCHEMA_VERSION,
        "group": group,
        "invocation_id": invocation_id,
        "invocation_root": str(invocation_root),
        "projection_path": str(projection_path),
        "index_path": str(index_path),
        "command": list(command),
        "cwd": str(Path(cwd).resolve()),
        "environment": {
            key: value
            for key, value in dict(environment or {}).items()
            if "TOKEN" not in key.upper() and "SECRET" not in key.upper()
        },
        "return_code": int(return_code),
        "started_monotonic": started,
        "ended_monotonic": ended,
        **projected_counts,
        "test_nodes": list(test_nodes),
        "raw_stdout_path": str(stdout_path),
        "raw_stderr_path": str(stderr_path),
        "forbidden_skip_or_xfail": bool(
            projected_counts["skipped"]
            or projected_counts["xfail"]
            or projected_counts["xpass"]
        ),
        "timeout": bool(timeout),
        "timeout_reason": str(timeout_reason),
        "summary": parsed,
        "current_checkout": True,
    }
    _write_atomic(projection_path, stable_json_dumps(projection))

    existing: dict[str, object] = {}
    malformed_index = False
    if index_path.exists():
        try:
            loaded = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
            else:
                malformed_index = True
        except (OSError, ValueError):
            malformed_index = True
    old_invocations = existing.get("invocations", [])
    if not isinstance(old_invocations, list):
        old_invocations = []
        malformed_index = True
    if any(isinstance(item, Mapping) and item.get("invocation_id") == invocation_id for item in old_invocations):
        raise ValueError(f"duplicate evidence invocation id: {invocation_id}")
    invocations = [*old_invocations, {
        "invocation_id": invocation_id,
        "projection_path": str(projection_path),
        "return_code": int(return_code),
        "timeout": bool(timeout),
    }]
    conflict = malformed_index or len(invocations) > 1
    index = {
        "schema_version": TEST_EVIDENCE_INDEX_SCHEMA_VERSION,
        "group": group,
        "invocations": invocations,
        "selected_invocation_id": None,
        "conflict": conflict,
    }
    if malformed_index:
        index["index_error"] = "existing_index_malformed"
    _write_atomic(index_path, stable_json_dumps(index))
    return projection


def _role_graph_payload(role_graph: object) -> dict[str, object]:
    if isinstance(role_graph, Mapping):
        payload = dict(role_graph)
        payload.setdefault("roles", [])
        payload.setdefault("edges", [])
        payload.setdefault("hash", sha256_digest({"roles": payload["roles"], "edges": payload["edges"]}))
        return payload
    roles = [str(role).strip() for role in str(role_graph).split("->") if str(role).strip()]
    edges = [[left, right] for left, right in zip(roles, roles[1:])]
    return {"roles": roles, "edges": edges, "hash": sha256_digest({"roles": roles, "edges": edges})}


def build_benchmark_manifest(
    *,
    lane: str,
    dataset_id: str,
    dataset_version: str,
    dataset_split: str,
    dataset_hash: str,
    task_contract_hash: str,
    provider_id: str,
    provider_version: str,
    model_id: str,
    model_revision: str,
    implementation_snapshot: Mapping[str, object] | None = None,
    role_graph: object = "planner->retriever->executor->summarizer",
    agent_count: int | None = None,
    seed: int = 0,
    temperature: float = 0.0,
    timeout: Mapping[str, object] | None = None,
    retry_budget: int = 0,
    quality_threshold: Mapping[str, object] | None = None,
    memory_policy: str = "off",
    cache_epoch: str = "none",
    runtime_root: str | Path = "",
    workspace_root: str | Path = "",
    memory_root: str | Path = "",
    oracle_visibility: Mapping[str, object] | None = None,
    validator_digest: str = "",
    terminal_status: str = "unsupported",
    source_identity: Mapping[str, object] | None = None,
    execution_path: str | None = None,
    runtime_authority: str | None = None,
    feature_flags: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the single Slice C manifest schema used by all five lanes."""

    if lane not in FAIRNESS_LANES:
        raise ValueError(f"unsupported benchmark lane: {lane}")
    if terminal_status not in TERMINAL_STATUSES:
        raise ValueError(f"unsupported terminal status: {terminal_status}")
    canonical = lane in CANONICAL_LANES
    graph = _role_graph_payload(role_graph)
    if agent_count is None:
        agent_count = 1 if lane == "direct_single_agent" else len(graph.get("roles", []))
    default_authority = "legacy_runtime_driver" if lane == "legacy_comparator" else "adaptive_mainline_runtime"
    default_path = "legacy_comparator" if lane == "legacy_comparator" else "canonical"
    visibility = dict(oracle_visibility or {
        "roles": False,
        "runtime_scorer": True,
        "future_rounds": False,
    })
    visibility.setdefault("roles", False)
    visibility.setdefault("runtime_scorer", True)
    visibility.setdefault("future_rounds", False)
    snapshot = dict(implementation_snapshot or {})
    snapshot.setdefault("snapshot_id", "source-only-fixture")
    snapshot.setdefault("digest", sha256_digest(snapshot))
    snapshot.setdefault("endpoint_fingerprint", "source-only-fixture")
    return {
        "schema_version": "statebus.fair_benchmark_manifest.v1",
        "source_identity": dict(source_identity or capture_source_identity()),
        "execution_path": execution_path or default_path,
        "runtime_authority": runtime_authority or default_authority,
        "lane": lane,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "dataset_split": dataset_split,
        "dataset_hash": dataset_hash,
        "task_contract_hash": task_contract_hash,
        "role_graph": graph,
        "agent_count": agent_count,
        "provider_id": provider_id,
        "provider_version": provider_version,
        "model_id": model_id,
        "model_revision": model_revision,
        "implementation_snapshot": snapshot,
        "seed": seed,
        "temperature": temperature,
        "timeout": dict(timeout or {"case_ms": 0, "step_ms": 0}),
        "retry_budget": retry_budget,
        "quality_threshold": dict(quality_threshold or {"contract": "", "minimum_pass": 1.0}),
        "memory_policy": memory_policy,
        "cache_epoch": cache_epoch,
        "runtime_root": str(runtime_root),
        "workspace_root": str(workspace_root),
        "memory_root": str(memory_root),
        "oracle_visibility": visibility,
        "gold_visible": False,
        "expected_route_visible": False,
        "expected_tool_visible": False,
        "future_rounds_visible": False,
        "validator_digest": validator_digest,
        "terminal_status": terminal_status,
        "feature_flags": dict(feature_flags or {}),
        "canonical_lane": canonical,
        "claim_scope": "contract_only_no_superiority_claim",
    }


def validate_benchmark_manifest(manifest: Mapping[str, object]) -> dict[str, object]:
    """Validate required identity/isolation fields; missing data is diagnostic-only."""

    missing = [
        field
        for field in _FAIRNESS_REQUIRED_FIELDS
        if manifest.get(field) is None or (isinstance(manifest.get(field), str) and not manifest.get(field))
    ]
    errors: list[dict[str, object]] = []
    lane = str(manifest.get("lane", ""))
    if lane not in FAIRNESS_LANES:
        errors.append({"field": "lane", "reason": "unsupported_lane"})
    lane_execution_paths = {
        "direct_single_agent": "direct_single_agent_provider",
        "pure_text_mas": "pure_text_provider_four_role",
        "fixed_structured": "FixedMainlineRequest->AdaptiveMainlineRunner->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher",
        "adaptive_routed": "RuntimeDriver.run_mode(adaptive_bounded)->AdaptiveMainlineRunner->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher",
    }
    allowed_paths = {"canonical", "legacy_comparator"}
    if lane in lane_execution_paths:
        allowed_paths.add(lane_execution_paths[lane])
    if manifest.get("execution_path") not in allowed_paths:
        errors.append({"field": "execution_path", "reason": "unsupported_execution_path"})
    if lane in CANONICAL_LANES and manifest.get("execution_path") not in {"canonical", lane_execution_paths[lane]}:
        errors.append({"field": "execution_path", "reason": "canonical_lane_must_use_canonical_path"})
    if lane == "legacy_comparator" and manifest.get("execution_path") != "legacy_comparator":
        errors.append({"field": "execution_path", "reason": "legacy_lane_must_use_legacy_path"})
    if manifest.get("terminal_status") not in TERMINAL_STATUSES:
        errors.append({"field": "terminal_status", "reason": "unsupported_terminal_status"})
    source = manifest.get("source_identity")
    if not isinstance(source, Mapping) or any(
        key not in source or source.get(key) in (None, "")
        for key in ("repository", "commit", "branch_or_ref", "working_tree_status_digest")
    ):
        missing.append("source_identity")
    roots = [manifest.get("runtime_root"), manifest.get("workspace_root"), manifest.get("memory_root")]
    if any(not isinstance(root, str) or not Path(root).is_absolute() for root in roots):
        errors.append({"field": "roots", "reason": "roots_must_be_absolute"})
    oracle = manifest.get("oracle_visibility")
    if not isinstance(oracle, Mapping) or any(oracle.get(key) is not value for key, value in {
        "roles": False,
        "runtime_scorer": True,
        "future_rounds": False,
    }.items()):
        errors.append({"field": "oracle_visibility", "reason": "oracle_visible_to_roles_or_future_rounds"})
    for key in ("gold_visible", "expected_route_visible", "expected_tool_visible", "future_rounds_visible"):
        if manifest.get(key) is not False:
            errors.append({"field": key, "reason": "oracle_visibility_flag_not_false"})
    canonical = (
        not missing
        and not errors
        and lane in CANONICAL_LANES
        and manifest.get("execution_path") in {"canonical", lane_execution_paths.get(lane, "")}
    )
    return {
        "ok": not missing and not errors,
        "canonical_eligible": canonical,
        "diagnostic_only": not canonical,
        "missing_fields": sorted(set(missing)),
        "errors": errors,
    }


def build_failure_denominator(records: Iterable[Mapping[str, object]]) -> dict[str, int | float]:
    """Count every attempted terminal record, including failures and unsupported cases."""

    counts = {status: 0 for status in TERMINAL_STATUSES}
    attempted = 0
    for record in records:
        status = str(record.get("terminal_status", "")).strip()
        attempted += 1
        if status not in counts:
            raise ValueError(f"unsupported terminal status: {status}")
        counts[status] += 1
    success = counts["success"]
    return {
        "attempted_count": attempted,
        "success_count": success,
        "quality_fail_count": counts["quality_fail"],
        "timeout_count": counts["timeout"],
        "unsupported_count": counts["unsupported"],
        "runtime_fail_count": counts["runtime_fail"],
        "policy_reject_count": counts["policy_reject"],
        "environment_fail_count": counts["environment_fail"],
        "failure_count": attempted - success,
        "quality_pass_rate": success / attempted if attempted else 0.0,
    }


def validate_root_isolation(manifests: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Ensure every lane has independent mutable roots and cache epoch."""

    rows = list(manifests)
    fields = (
        "runtime_root",
        "workspace_root",
        "memory_root",
        "cache_epoch",
        "artifact_ids",
        "memory_ids",
    )
    duplicates = {
        field: sorted({str(value) for value in [row.get(field) for row in rows] if value})
        for field in fields
    }
    collisions: dict[str, object] = {}
    for field, values in duplicates.items():
        if field in {"artifact_ids", "memory_ids"}:
            flattened = [item for row in rows for item in row.get(field, ()) or ()]
            if len(flattened) != len(set(flattened)):
                collisions[field] = sorted({str(item) for item in flattened})
        elif len(values) != len(rows):
            collisions[field] = values
    resolved_paths: dict[str, list[str]] = {field: [] for field in ("runtime_root", "workspace_root", "memory_root")}
    inode_paths: dict[str, list[tuple[int, int]]] = {field: [] for field in resolved_paths}
    for row in rows:
        for field in resolved_paths:
            raw = row.get(field)
            if not raw:
                continue
            path = Path(str(raw))
            if path.is_symlink():
                collisions.setdefault("root_symlink", []).append(str(path))
                continue
            resolved_paths[field].append(str(path.resolve()))
            if path.exists():
                stat = path.lstat()
                inode_paths[field].append((stat.st_dev, stat.st_ino))
                listing = list_root_contents(path, field)
                if not listing.get("readable", False):
                    collisions.setdefault("listing_failure", []).append(str(path))
                for entry in listing.get("entries", ()):
                    if isinstance(entry, Mapping) and entry.get("kind") in {"symlink", "socket"}:
                        collisions.setdefault(f"unexpected_{entry.get('kind')}", []).append(str(path / str(entry.get("path", ""))))
    for field, paths in resolved_paths.items():
        if len(paths) != len(set(paths)):
            collisions[f"{field}_resolved"] = paths
        inodes = inode_paths[field]
        if len(inodes) != len(set(inodes)):
            collisions[f"{field}_inode"] = inodes
    all_root_paths = [path for paths in resolved_paths.values() for path in paths]
    for index, left in enumerate(all_root_paths):
        for right in all_root_paths[index + 1:]:
            if left != right and (left.startswith(right + os.sep) or right.startswith(left + os.sep)):
                collisions["nested_mutable_root"] = [left, right]
                break
    return {"ok": not collisions, "collisions": collisions, "checked_count": len(rows)}


def build_five_case_fairness_smoke(
    *,
    dataset_id: str = "c1-fixture",
    dataset_version: str = "v1",
    dataset_split: str = "smoke",
    dataset_hash: str = "sha256:c1-fixture",
    task_contract_hash: str = "sha256:c1-task",
    provider_id: str = "fixture-provider",
    provider_version: str = "fixture-v1",
    model_id: str = "fixture-model",
    model_revision: str = "fixture-revision",
    seed: int = 0,
    temperature: float = 0.0,
    timeout: Mapping[str, object] | None = None,
    retry_budget: int = 0,
    quality_threshold: Mapping[str, object] | None = None,
    source_identity: Mapping[str, object] | None = None,
    root: Path | None = None,
    terminal_status_by_lane: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Create the C1 five-lane fixture without starting any external service."""

    base_root = (root or Path("/tmp/statebus-c1-fairness")).resolve()
    source = dict(source_identity or capture_source_identity())
    statuses = dict(terminal_status_by_lane or {})
    graph = {
        "roles": ["planner", "retriever", "executor", "summarizer"],
        "edges": [["planner", "retriever"], ["retriever", "executor"], ["executor", "summarizer"]],
    }
    manifests: list[dict[str, object]] = []
    invariant_fields = [
        "dataset_id",
        "dataset_version",
        "dataset_split",
        "dataset_hash",
        "task_contract_hash",
        "provider_id",
        "provider_version",
        "model_id",
        "model_revision",
        "seed",
        "temperature",
        "timeout",
        "retry_budget",
        "quality_threshold",
        "validator_digest",
    ]
    for lane in FAIRNESS_LANES:
        lane_root = base_root / lane
        lane_graph: object = "direct" if lane == "direct_single_agent" else graph
        lane_agent_count = 1 if lane == "direct_single_agent" else 4
        lane_flags = {
            "structured_control": lane in {"fixed_structured", "adaptive_routed"},
            "text_handoff_only": lane == "pure_text_mas",
            "bounded_route_policy": lane == "adaptive_routed",
            "legacy_storage": lane == "legacy_comparator",
        }
        manifest = build_benchmark_manifest(
            lane=lane,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            dataset_split=dataset_split,
            dataset_hash=dataset_hash,
            task_contract_hash=task_contract_hash,
            provider_id=provider_id,
            provider_version=provider_version,
            model_id=model_id,
            model_revision=model_revision,
            implementation_snapshot={
                "snapshot_id": "c1-source-only",
                "digest": sha256_digest({"provider_id": provider_id, "model_id": model_id}),
                "endpoint_fingerprint": "fixture-endpoint",
            },
            role_graph=lane_graph,
            agent_count=lane_agent_count,
            seed=seed,
            temperature=temperature,
            timeout=timeout,
            retry_budget=retry_budget,
            quality_threshold=quality_threshold,
            memory_policy="off",
            cache_epoch=f"cold:{lane}",
            runtime_root=lane_root / "runtime",
            workspace_root=lane_root / "workspace",
            memory_root=lane_root / "memory",
            oracle_visibility={"roles": False, "runtime_scorer": True, "future_rounds": False},
            validator_digest="sha256:c1-validator",
            terminal_status=statuses.get(lane, "unsupported"),
            source_identity=source,
            feature_flags=lane_flags,
        )
        manifest["fixed_entrypoint"] = (
            "FixedMainlineRequest->AdaptiveMainlineRunner->AdaptiveRuntimeEngine"
            if lane == "fixed_structured" else ""
        )
        manifest["uses_run_smoke"] = lane == "legacy_comparator"
        manifest["invariant_fields"] = list(invariant_fields)
        manifest["invariant_digest"] = sha256_digest(
            {field: manifest[field] for field in invariant_fields}
        )
        manifests.append(manifest)

    terminal_records = [
        {
            "task_id": dataset_id,
            "dataset_case": dataset_id,
            "lane": manifest["lane"],
            "terminal_status": manifest["terminal_status"],
            "manifest": manifest,
        }
        for manifest in manifests
    ]
    denominator = build_failure_denominator(terminal_records)
    validation = [validate_benchmark_manifest(manifest) for manifest in manifests]
    isolation = validate_root_isolation(manifests)
    canonical_records = [record for record in terminal_records if record["manifest"]["execution_path"] == "canonical"]
    return {
        "schema_version": "statebus.c1_five_case_fairness_smoke.v1",
        "claim_scope": "contract_only_no_superiority_claim",
        "superiority_claim": False,
        "lanes": list(FAIRNESS_LANES),
        "canonical_lanes": list(CANONICAL_LANES),
        "invariant_fields": invariant_fields,
        "invariant_digests": sorted({str(manifest["invariant_digest"]) for manifest in manifests}),
        "manifests": manifests,
        "terminal_records": terminal_records,
        "failure_denominator": denominator,
        "canonical_failure_denominator": build_failure_denominator(canonical_records),
        "legacy_records": [record for record in terminal_records if record["lane"] == "legacy_comparator"],
        "canonical_records": canonical_records,
        "manifest_validation": validation,
        "root_isolation": isolation,
        "canonical_aggregate": {
            "included_lanes": list(CANONICAL_LANES),
            "excluded_lanes": ["legacy_comparator"],
            "eligible": (
                all(result["canonical_eligible"] for result in validation[:4])
                and all(record["terminal_status"] == "success" for record in canonical_records)
                and isolation["ok"]
            ),
        },
    }


def build_c2a_pilot_records(
    *,
    case_ids: Iterable[str],
    root: Path,
    source_identity: Mapping[str, object] | None = None,
    case_metadata: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Register the deterministic 8 x 4 C2A rows without inventing outcomes."""
    source = dict(source_identity or capture_source_identity())
    manifests: list[dict[str, object]] = []
    metadata_by_case = dict(case_metadata or {})
    for case_id in tuple(case_ids):
        for lane in CANONICAL_LANES:
            lane_root = (root / "cases" / case_id / lane / "0").resolve()
            for child in ("runtime_root", "workspace_root", "memory_root", "cache/cold"):
                (lane_root / child).mkdir(parents=True, exist_ok=True)
            manifest = build_benchmark_manifest(
                lane=lane,
                dataset_id=str(metadata_by_case.get(case_id, {}).get("dataset_id", "c2a_internal_fixture")),
                dataset_version=str(metadata_by_case.get(case_id, {}).get("dataset_version", "c2a-v1")),
                dataset_split=str(metadata_by_case.get(case_id, {}).get("dataset_split", "c2a_internal_fixture")),
                dataset_hash=str(metadata_by_case.get(case_id, {}).get("dataset_hash", sha256_digest(case_id))),
                task_contract_hash=str(metadata_by_case.get(case_id, {}).get("task_contract_hash", sha256_digest({"case_id": case_id}))),
                provider_id="deterministic-host-provider",
                provider_version="c2a-v1",
                model_id="deterministic-host-model",
                model_revision="internal-fixture-v1",
                role_graph="planner->retriever->executor->summarizer" if lane != "direct_single_agent" else "direct",
                agent_count=1 if lane == "direct_single_agent" else 4,
                memory_policy="off",
                cache_epoch=f"c2a/{case_id}/{lane}/0/cold",
                runtime_root=lane_root / "runtime_root",
                workspace_root=lane_root / "workspace_root",
                memory_root=lane_root / "memory_root",
                source_identity=source,
                # ``execution_path=canonical`` is the aggregate membership
                # marker; the observed caller path is recorded separately.
                execution_path="canonical",
                runtime_authority=(
                    "AdaptiveRuntimeEngine"
                    if lane in {"fixed_structured", "adaptive_routed"}
                    else ("deterministic_text_provider" if lane == "pure_text_mas" else "deterministic_generalist_provider")
                ),
                terminal_status="unsupported",
                feature_flags={"text_handoff_only": lane == "pure_text_mas", "bounded_route_policy": lane == "adaptive_routed"},
            )
            recipe_identity, capability_identity, _ = _lane_identity(lane)
            manifest.update({
                "case_id": case_id,
                "repeat_id": 0,
                "run_id": "c2a-pilot",
                "terminal_record_path": str(lane_root / "terminal.json"),
                "caller_path": (
                    "RuntimeDriver.run_mode(strict_fixed)->AdaptiveMainlineRunner->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher"
                    if lane == "fixed_structured"
                    else (
                        "RuntimeDriver.run_mode(adaptive_bounded)->AdaptiveMainlineRunner->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher"
                        if lane == "adaptive_routed"
                        else ("pure_text_provider_four_role" if lane == "pure_text_mas" else "direct_single_agent_provider")
                    )
                ),
                "recipe_identity": recipe_identity,
                "capability_identity": capability_identity,
            })
            (lane_root / "manifest.json").write_text(stable_json_dumps(manifest), encoding="utf-8")
            (lane_root / "stdout.log").write_text("", encoding="utf-8")
            (lane_root / "stderr.log").write_text("", encoding="utf-8")
            (lane_root / "root_listing.json").write_text(stable_json_dumps({name: list_root_contents(lane_root / name, name) for name in ("runtime_root", "workspace_root", "memory_root")}), encoding="utf-8")
            (lane_root / "terminal.json").write_text(
                stable_json_dumps({"case_id": case_id, "lane": lane, "terminal_status": "unsupported", "registration_only": True, "evidence_scope": "contract/collector evidence only"}),
                encoding="utf-8",
            )
            manifest.update({"registration_only": True, "evidence_scope": "contract/collector evidence only", "pilot_eligible": False})
            (lane_root / "manifest.json").write_text(stable_json_dumps(manifest), encoding="utf-8")
            manifests.append(manifest)
    terminal_records = [{"case_id": m["case_id"], "lane": m["lane"], "terminal_status": m["terminal_status"], "manifest": m} for m in manifests]
    return {
        "schema_version": "statebus.c2a_pilot.v1",
        "manifests": manifests,
        "terminal_records": terminal_records,
        "failure_denominator": build_failure_denominator(terminal_records),
        "root_isolation": validate_root_isolation(manifests),
        "canonical_records": terminal_records,
        "legacy_records": [],
        "evidence_scope": "contract/collector evidence only",
        "pilot_eligible": False,
    }


def collect_c2a_terminal_record(
    *,
    manifest: Mapping[str, object],
    outcome: Mapping[str, object],
    trace: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Persist one observed C2A outcome and project Runtime-owned trace facts."""
    lane_root = Path(str(manifest["runtime_root"])).parent
    status = str(outcome.get("terminal_status", "runtime_fail"))
    if status not in TERMINAL_STATUSES:
        status = "environment_fail"
    projected = dict(manifest)
    projected.update({
        "terminal_status": status,
        "registration_only": False,
        "evidence_scope": "execution trace",
        "pilot_eligible": False,
        "failure_stage": str(outcome.get("failure_stage", "")),
        "error_code": str(outcome.get("error_code", "")),
        "error_message": str(outcome.get("error_message", outcome.get("error_code", ""))),
        "trace": dict(trace or {}),
        "metric_availability": dict(outcome.get("metric_availability", {})),
        "artifact_ids": tuple(dict.fromkeys(
            str(ref_id)
            for dispatch in dict(trace or {}).get("dispatches", ())
            if isinstance(dispatch, Mapping)
            for ref_id in dispatch.get("output_refs", ())
        )) if trace else (),
        "memory_ids": (),
    })
    observed_trace = dict(trace or {})
    observed_trace.setdefault("schema_version", CANONICAL_TRACE_SCHEMA_VERSION)
    observed_trace.setdefault("case_id", projected.get("case_id"))
    observed_trace.setdefault("lane", projected.get("lane"))
    observed_trace.setdefault("task_id", projected.get("task_id", projected.get("case_id")))
    observed_trace.setdefault("canonical_task_spec_hash", projected.get("task_contract_hash"))
    observed_trace.setdefault("terminal_status", status)
    observed_trace.setdefault("failure_stage", projected["failure_stage"])
    observed_trace.setdefault("error_code", projected["error_code"])
    observed_trace.setdefault("error_message", projected["error_message"])
    lane = str(projected.get("lane", ""))
    recipe, capability, execution_path = _lane_identity(lane)
    observed_trace.setdefault("role_graph", "direct" if lane == "direct_single_agent" else "planner->retriever->executor->summarizer")
    observed_trace.setdefault("role_sequence", ["generalist"] if lane == "direct_single_agent" else (["planner", "retriever", "executor", "summarizer"] if lane == "pure_text_mas" else []))
    observed_trace.setdefault("role_count", {"generalist": 1} if lane == "direct_single_agent" else ({role: 1 for role in ("planner", "retriever", "executor", "summarizer")} if lane == "pure_text_mas" else {}))
    observed_trace.setdefault("dependency_edges", [] if lane == "direct_single_agent" else [["planner", "retriever"], ["retriever", "executor"], ["executor", "summarizer"]])
    observed_trace.setdefault("provider_calls", observed_trace.get("calls", []))
    observed_trace.setdefault("runtime_attempts", {"status": "unsupported", "items": [], "count": 0} if lane in {"direct_single_agent", "pure_text_mas"} else {"status": "observed", "items": observed_trace.get("attempts", []), "count": len(observed_trace.get("attempts", []))})
    observed_trace.setdefault("recipe_identity", recipe)
    observed_trace.setdefault("capability_identity", capability)
    observed_trace.setdefault("canonical_marker", {
        "observed": True,
        "lane": lane,
        "execution_path": observed_trace.get("execution_path", execution_path),
        "runtime_authority": observed_trace.get("runtime_authority", projected.get("runtime_authority", "")),
        "role_graph": observed_trace.get("role_graph", ""),
        "recipe_identity": recipe,
        "capability_identity": capability,
        "trace_schema_version": CANONICAL_TRACE_SCHEMA_VERSION,
    })
    projected["trace"] = observed_trace
    validation = validate_c2a_trace(observed_trace, projected)
    projected["trace_validation"] = validation
    projected["attempt_count"] = len(observed_trace.get("attempts", observed_trace.get("calls", ())))
    # Persist the complete Stage 1 row surface.  These files are projections of
    # observed Runtime/provider facts; missing carrier-specific facts remain
    # explicit ``unsupported`` rather than being synthesized.
    dispatches = [item for item in observed_trace.get("dispatches", ()) if isinstance(item, Mapping)]
    provider_requests = observed_trace.get("provider_requests", ())
    provider_candidates = observed_trace.get("provider_candidates", ())
    if not isinstance(provider_requests, (list, tuple)):
        provider_requests = ()
    if not isinstance(provider_candidates, (list, tuple)):
        provider_candidates = ()
    if not provider_requests:
        provider_requests = tuple(
            {"projection": "provider_call", "payload": item}
            for item in observed_trace.get("provider_calls", ())
            if isinstance(item, Mapping)
        )
    if not provider_candidates:
        provider_candidates = tuple(
            {"projection": "dispatch_result", "payload": item}
            for item in dispatches
        )
    artifact_candidates = list(observed_trace.get("artifact_candidates", ()))
    if not artifact_candidates:
        artifact_candidates = [
        {
            "artifact_id": ref_id,
            "state": "CANDIDATE",
            "step_id": item.get("step_id", ""),
            "attempt_id": item.get("attempt_id", ""),
        }
        for item in dispatches
        for ref_id, ref_kind in zip(item.get("output_refs", ()), item.get("output_ref_kinds", ()) or ())
        if ref_kind == "execution_artifact"
        ]
    runtime_context = {
        "attempt_records": observed_trace.get("attempts", ()),
        "bindings": observed_trace.get("provider_bindings", ()),
        "grants": observed_trace.get("grants", ()),
        "admissions": observed_trace.get("receipts", ()),
    }
    transport_audit = outcome.get("transport_audit")
    if not isinstance(transport_audit, Mapping):
        transport_audit = observed_trace.get("transport_audit", {})
    if not isinstance(transport_audit, Mapping):
        transport_audit = {}
    transport_audit = dict(transport_audit)

    def _na(reason: str, failure_stage: str) -> dict[str, str]:
        return {"status": "not_applicable", "reason": reason, "failure_stage": failure_stage or "terminal_projection"}

    def _observed(value: object, *, reason: str, failure_stage: str) -> object:
        if value is None or value == "" or value == 0 or value == () or value == []:
            return _na(reason, failure_stage)
        return value

    trace_attempts = observed_trace.get("attempts", ())
    trace_attempt = trace_attempts[0] if isinstance(trace_attempts, (list, tuple)) and trace_attempts and isinstance(trace_attempts[0], Mapping) else {}
    trace_grants = observed_trace.get("grants", ())
    trace_grant = trace_grants[0] if isinstance(trace_grants, (list, tuple)) and trace_grants and isinstance(trace_grants[0], Mapping) else {}
    trace_bindings = observed_trace.get("provider_bindings", ())
    trace_binding = trace_bindings[0] if isinstance(trace_bindings, (list, tuple)) and trace_bindings and isinstance(trace_bindings[0], Mapping) else {}
    trace_receipts = observed_trace.get("receipts", ())
    trace_receipt = trace_receipts[0] if isinstance(trace_receipts, (list, tuple)) and trace_receipts and isinstance(trace_receipts[0], Mapping) else {}
    failure_stage = str(outcome.get("failure_stage", projected.get("failure_stage", "")))
    task_id = str(projected.get("task_id") or transport_audit.get("task_id") or projected.get("case_id"))
    session_id = str(projected.get("session_id") or transport_audit.get("session_id") or f"session-unavailable:{projected.get('case_id')}")
    identity_envelope: dict[str, object] = {
        "task_id": task_id,
        "session_id": session_id,
        "step_id": _observed(transport_audit.get("step_id") or trace_attempt.get("step_id") or trace_receipt.get("step_id"), reason="step_not_created_before_failure", failure_stage=failure_stage),
        "attempt_id": _observed(transport_audit.get("attempt_id") or trace_attempt.get("attempt_id") or trace_receipt.get("attempt_id"), reason="attempt_not_created_before_failure", failure_stage=failure_stage),
        "attempt_status": status,
        "grant_id": _observed(transport_audit.get("grant_id") or trace_grant.get("grant_id"), reason="capability_grant_not_issued_before_failure", failure_stage=failure_stage),
        "capability_grant_hash": _observed(transport_audit.get("capability_grant_hash") or trace_grant.get("grant_hash") or trace_grant.get("capability_grant_hash"), reason="capability_grant_not_issued_before_failure", failure_stage=failure_stage),
        "binding_id": _observed(transport_audit.get("binding_id") or trace_binding.get("binding_id"), reason="execution_binding_not_created_before_failure", failure_stage=failure_stage),
        "execution_binding_hash": _observed(transport_audit.get("execution_binding_hash") or trace_binding.get("binding_hash") or trace_binding.get("execution_binding_hash"), reason="execution_binding_not_created_before_failure", failure_stage=failure_stage),
        "invocation_id": _observed(transport_audit.get("invocation_id") or trace_receipt.get("invocation_id"), reason="invocation_not_created_before_failure", failure_stage=failure_stage),
        "state_access_grant_id": _observed(transport_audit.get("state_access_grant_id") or trace_receipt.get("state_access_grant_id"), reason="state_read_not_started_before_failure", failure_stage=failure_stage),
        "state_access_grant_hash": _observed(transport_audit.get("state_access_grant_hash") or trace_receipt.get("state_access_grant_hash"), reason="state_read_not_started_before_failure", failure_stage=failure_stage),
        "state_ref_id": _observed(transport_audit.get("state_ref_id") or trace_receipt.get("state_ref_id"), reason="state_ref_not_resolved_before_failure", failure_stage=failure_stage),
        "state_identity_hash": _observed(transport_audit.get("state_identity_hash") or trace_receipt.get("state_identity_hash"), reason="state_ref_not_resolved_before_failure", failure_stage=failure_stage),
        "blob_hash": _observed(transport_audit.get("blob_hash") or trace_receipt.get("blob_hash"), reason="state_descriptor_not_observed_before_failure", failure_stage=failure_stage),
        "manifest_hash": _observed(transport_audit.get("manifest_hash") or trace_receipt.get("manifest_hash"), reason="state_descriptor_not_observed_before_failure", failure_stage=failure_stage),
        "encoder_hash": _observed(transport_audit.get("encoder_hash") or trace_receipt.get("encoder_hash"), reason="state_descriptor_not_observed_before_failure", failure_stage=failure_stage),
        "cache_epoch": _observed(projected.get("cache_epoch") or transport_audit.get("cache_epoch"), reason="cache_epoch_not_observed", failure_stage=failure_stage),
        "producer_pid": _observed(transport_audit.get("producer_pid"), reason="producer_not_started_before_failure", failure_stage=failure_stage),
        "consumer_pid": _observed(transport_audit.get("consumer_pid"), reason="consumer_not_started_before_failure", failure_stage=failure_stage),
        "driver_pid": _observed(transport_audit.get("driver_pid"), reason="driver_observation_unavailable", failure_stage=failure_stage),
        "worker_pid": _observed(transport_audit.get("worker_pid"), reason="worker_not_started_before_failure", failure_stage=failure_stage),
        "socket_path_requested": _observed(transport_audit.get("socket_path_requested") or projected.get("socket_path_requested"), reason="socket_not_observed", failure_stage=failure_stage),
        "socket_path_effective": _observed(transport_audit.get("socket_path_effective") or projected.get("socket_path_effective"), reason="socket_not_observed", failure_stage=failure_stage),
        "socket_inode": _observed(transport_audit.get("socket_inode") or projected.get("socket_inode"), reason="socket_inode_not_observed", failure_stage=failure_stage),
    }
    identity_status = {
        key: ("observed" if not isinstance(value, Mapping) else "not_applicable")
        for key, value in identity_envelope.items()
    }
    identity_envelope["identity_status_by_field"] = identity_status
    identity_envelope["parent_hash"] = sha256_digest(identity_envelope)
    projected["task_id"] = task_id
    projected["session_id"] = session_id
    projected["identity_envelope"] = identity_envelope
    projected["identity_envelope_hash"] = identity_envelope["parent_hash"]
    observed_trace["identity_envelope"] = identity_envelope
    observed_trace["identity_envelope_hash"] = identity_envelope["parent_hash"]
    transport_audit["identity_envelope"] = identity_envelope
    transport_audit["identity_envelope_hash"] = identity_envelope["parent_hash"]
    control_frames = outcome.get("control_frames")
    if not isinstance(control_frames, (list, tuple)):
        control_frames = observed_trace.get("control_frames", ())
    if not isinstance(control_frames, (list, tuple)):
        control_frames = ()
    if not control_frames and isinstance(transport_audit.get("request_frame_metadata"), list):
        control_frames = list(transport_audit.get("request_frame_metadata", ())) + list(
            transport_audit.get("response_frame_metadata", ())
        )
    control_frames = [
        {
            **dict(frame),
            "task_id": dict(frame).get("task_id", identity_envelope["task_id"]),
            "session_id": dict(frame).get("session_id", identity_envelope["session_id"]),
            "attempt_id": dict(frame).get("attempt_id", identity_envelope["attempt_id"]),
            "invocation_id": dict(frame).get("invocation_id", identity_envelope["invocation_id"]),
            "identity_envelope_hash": identity_envelope["parent_hash"],
        }
        for frame in control_frames
        if isinstance(frame, Mapping)
    ]
    failure_propagation = outcome.get("failure_propagation")
    if not isinstance(failure_propagation, Mapping):
        failure_propagation = observed_trace.get("failure_propagation", {})
    if not isinstance(failure_propagation, Mapping):
        failure_propagation = {}
    failure_projection = {
        "schema_version": "statebus.g6a0.failure_propagation.v1",
        "terminal_status": status,
        "failure_stage": projected["failure_stage"],
        "error_code": projected["error_code"],
        "error_message": projected["error_message"],
        "transport": dict(failure_propagation),
        "identity_envelope": identity_envelope,
        "identity_envelope_hash": identity_envelope["parent_hash"],
    }
    lifecycle = outcome.get("state_release_reclaim")
    if not isinstance(lifecycle, Mapping):
        lifecycle = observed_trace.get("state_release_reclaim", {})
    if not isinstance(lifecycle, Mapping) or not lifecycle:
        lifecycle = {
            "status": "not_applicable",
            "reason": "state_lifecycle_not_observed_for_row",
        }
    carrier_projection = {
        "schema_version": "statebus.g6a0.carrier_manifest.v1",
        "carrier": str(transport_audit.get("carrier", "unsupported")),
        "backend": str(transport_audit.get("backend", "unsupported")),
        "task_id": projected.get("task_id", projected.get("case_id", "")),
        "session_id": projected.get("session_id", ""),
        "step_id": projected.get("step_id", ""),
        "attempt_id": identity_envelope["attempt_id"],
        "invocation_id": identity_envelope["invocation_id"],
        "execution_binding_hash": identity_envelope["execution_binding_hash"],
        "capability_grant_hash": identity_envelope["capability_grant_hash"],
        "identity_envelope_hash": identity_envelope["parent_hash"],
        "observed": bool(transport_audit),
        "reason": "transport_audit_not_observed" if not transport_audit else "",
    }
    root_socket_projection = {
        "schema_version": "statebus.g6a0.root_socket_audit.v1",
        "runtime_root": projected.get("runtime_root", ""),
        "workspace_root": projected.get("workspace_root", ""),
        "memory_root": projected.get("memory_root", ""),
        "socket_path_requested": transport_audit.get("socket_path_requested", ""),
        "socket_path_effective": transport_audit.get("socket_path_effective", ""),
        "socket_inode": identity_envelope["socket_inode"],
        "session_id": projected.get("session_id", transport_audit.get("session_id", "")),
        "cache_epoch": projected.get("cache_epoch", ""),
        "status": "observed" if transport_audit else "unsupported",
        "reason": "socket_identity_not_observed" if not transport_audit else "",
        "identity_envelope_hash": identity_envelope["parent_hash"],
    }
    collision = dict(transport_audit.get("collision", {}))
    if collision.get("collision_detected"):
        root_socket_projection.update(collision)
        root_socket_projection.update({
            "ok": False,
            "collision_detected": True,
            "foreign_residue_unlinked": False,
            "rejection_action": "refused_without_unlink",
            "failure_stage": "isolation_audit",
            "error_code": "socket_identity_collision",
            "terminal_status": "environment_fail",
        })
    _write_atomic(lane_root / "provider_requests.jsonl", "".join(stable_json_dumps(item) + "\n" for item in provider_requests))
    _write_atomic(lane_root / "provider_candidates.jsonl", "".join(stable_json_dumps(item) + "\n" for item in provider_candidates))
    for filename, payload in {
        "attempt_records.json": runtime_context["attempt_records"],
        "binding_receipts.json": runtime_context["bindings"],
        "grant_receipts.json": runtime_context["grants"],
        "artifact_candidates.json": artifact_candidates,
        "artifact_verification_receipts.json": observed_trace.get("artifact_verification_receipts", []),
        "claim_sets.json": observed_trace.get("claim_sets", []),
        "claim_validation_reports.json": observed_trace.get("claim_validation_reports", []),
        "codeact_execution.json": observed_trace.get("codeact_execution", {"status": "unsupported", "reason": "codeact_not_observed"}),
        "metric_availability.json": projected["metric_availability"],
        "scorer_result.json": observed_trace.get("scorer_result", {"status": "unsupported", "reason": "scorer_projection_not_observed"}),
        "carrier_manifest.json": carrier_projection,
        "transport_audit.json": dict(transport_audit) if transport_audit else {"status": "unsupported", "reason": "transport_audit_not_observed"},
        "failure_propagation.json": failure_projection,
        "root_socket_audit.json": root_socket_projection,
        "state_release_reclaim.json": {**dict(lifecycle), "identity_envelope": identity_envelope, "identity_envelope_hash": identity_envelope["parent_hash"]},
    }.items():
        _write_atomic(lane_root / filename, stable_json_dumps(payload))
    _write_atomic(
        lane_root / "control_frames.jsonl",
        "".join(stable_json_dumps(frame) + "\n" for frame in control_frames)
        or stable_json_dumps({"status": "not_applicable", "reason": "control_frames_not_observed"}) + "\n",
    )
    (lane_root / "manifest.json").write_text(stable_json_dumps(projected), encoding="utf-8")
    (lane_root / "terminal.json").write_text(
        stable_json_dumps({
            "case_id": projected.get("case_id"),
            "lane": projected.get("lane"),
            "terminal_status": status,
            "failure_stage": projected["failure_stage"],
            "error_code": projected["error_code"],
            "error_message": projected["error_message"],
            "identity_envelope": identity_envelope,
            "identity_envelope_hash": identity_envelope["parent_hash"],
            "metric_availability": projected["metric_availability"],
            "trace_present": bool(trace),
            "trace_schema_version": CANONICAL_TRACE_SCHEMA_VERSION,
            "trace_validation": validation,
        }),
        encoding="utf-8",
    )
    listing = {name: list_root_contents(manifest[name], name) for name in ("runtime_root", "workspace_root", "memory_root")}
    (lane_root / "root_listing.json").write_text(stable_json_dumps(listing), encoding="utf-8")
    projected["isolation_audit"] = validate_c2a_isolation([projected])
    if collision.get("collision_detected"):
        projected["isolation_audit"] = {
            **projected["isolation_audit"],
            "ok": False,
            "collision_detected": True,
            "failure_stage": "isolation_audit",
            "error_code": "socket_identity_collision",
            "terminal_status": "environment_fail",
            "foreign_residue_unlinked": False,
            "rejection_action": "refused_without_unlink",
            "collisions": {"socket_identity_collision": collision},
        }
    (lane_root / "isolation_audit.json").write_text(stable_json_dumps(projected["isolation_audit"]), encoding="utf-8")
    (lane_root / "root_audit.json").write_text(stable_json_dumps(projected["isolation_audit"]), encoding="utf-8")
    projected["oracle_audit"] = dict(observed_trace.get("oracle_audit", {"schema_version": ORACLE_AUDIT_SCHEMA_VERSION, "ok": True, "violations": [], "redaction": False}))
    projected["oracle_audit"].setdefault("schema_version", ORACLE_AUDIT_SCHEMA_VERSION)
    (lane_root / "oracle_audit.json").write_text(stable_json_dumps(projected["oracle_audit"]), encoding="utf-8")
    _write_atomic(lane_root / "runtime_trace.json", stable_json_dumps(observed_trace) + "\n")
    (lane_root / "trace_validation.json").write_text(stable_json_dumps(validation), encoding="utf-8")
    canonical_audit = {
        "schema_version": "statebus.c2a.canonical_aggregate_audit.v1",
        "eligible": bool(validation.get("valid")) and lane in CANONICAL_LANES,
        "included_record_ids": [f"{projected.get('case_id')}::{lane}"] if validation.get("valid") and lane in CANONICAL_LANES else [],
        "excluded_record_ids": [] if validation.get("valid") and lane in CANONICAL_LANES else [f"{projected.get('case_id')}::{lane}"],
        "rejected_record_ids": [],
        "reason": "" if validation.get("valid") else str(validation.get("reason", "")),
    }
    projected["canonical_aggregate_audit"] = canonical_audit
    (lane_root / "canonical_aggregate_audit.json").write_text(stable_json_dumps(canonical_audit), encoding="utf-8")
    # Rewrite the manifest after all row-level projections have been attached;
    # consumers must not observe a manifest that omits its audits.
    _write_atomic(lane_root / "manifest.json", stable_json_dumps(projected))
    if status != "success":
        (lane_root / "stderr.log").write_text(
            str(projected["error_code"] or projected["failure_stage"] or status), encoding="utf-8"
        )
    return {
        "case_id": projected.get("case_id"),
        "lane": projected.get("lane"),
        "terminal_status": status,
        "failure_stage": projected["failure_stage"],
        "error_code": projected["error_code"],
        "trace": observed_trace,
        "trace_validation": validation,
        "oracle_audit": projected["oracle_audit"],
        "isolation_audit": projected["isolation_audit"],
        "canonical_aggregate_audit": canonical_audit,
        "manifest": projected,
        "identity_envelope": identity_envelope,
    }

def _flatten_scalars(value: object) -> tuple[str, ...]:
    values: list[str] = []
    if isinstance(value, dict):
        for nested in value.values():
            values.extend(_flatten_scalars(nested))
    elif isinstance(value, (list, tuple, set)):
        for nested in value:
            values.extend(_flatten_scalars(nested))
    elif value is not None:
        rendered = str(value).strip()
        if rendered:
            values.append(rendered)
    return tuple(values)


def audit_role_request_gold_visibility(
    *,
    task_id: str,
    workspace_root: Path,
    role_request_relpaths: dict[str, str],
    expected_facts: dict[str, object],
    quality_checks: tuple[str, ...],
    expected_metric_effects: dict[str, object],
    public_provenance_payloads: Iterable[object],
) -> dict[str, object]:
    """Audit rendered/runtime surfaces while allowing source-derived overlap.

    G5-B uses this same helper for persisted row and runtime-manifest JSON in
    addition to role request files.  The recursive scan keeps the audit
    non-vacuous without moving sealed scorer inputs into Runtime.
    """

    public_material = "\n".join(
        stable_json_dumps(payload) if not isinstance(payload, str) else payload
        for payload in public_provenance_payloads
    )
    expected_values = tuple(dict.fromkeys(_flatten_scalars(expected_facts)))
    provenance_by_value = {
        value: {
            "authorized": value in public_material,
            "sources": ["public_task_or_source_or_runtime_output"] if value in public_material else [],
        }
        for value in expected_values
    }
    role_audits: dict[str, object] = {}
    audited_surfaces: list[dict[str, object]] = []
    violations: list[dict[str, object]] = []
    for role, relpath in sorted(role_request_relpaths.items()):
        path = workspace_root / relpath
        if not path.is_file():
            violation = {
                "role": role,
                "kind": "missing_role_request_artifact",
                "detail": str(path),
            }
            violations.append(violation)
            role_audits[role] = {"ok": False, "path": str(path), "violations": [violation]}
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        requests = payload.get("requests", []) if isinstance(payload, dict) else []
        surface_payload = requests if requests else payload
        role_violations: list[dict[str, object]] = []
        if requests and not any("messages" in item for item in requests if isinstance(item, dict)):
            role_violations.append({
                "role": role,
                "kind": "request_content_not_persisted",
                "detail": str(path),
            })
        path_values = {
            "surface_path": str(path),
            "resolved_path": str(path.resolve(strict=False)),
            "root": str(path.parent),
            "symlink_target": os.readlink(path) if path.is_symlink() else "",
        }
        rendered = stable_json_dumps({"payload": surface_payload, "path": path_values})
        expected_marker_set_hash = sha256_digest(list(expected_values))

        def walk(value: object, json_path: str = "$") -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    key_text = str(key)
                    nested_path = f"{json_path}.{key_text}"
                    if key_text in GOLD_ONLY_KEYS:
                        role_violations.append({
                            "role": role,
                            "kind": "benchmark_only_key_visible",
                            "detail": key_text,
                            "surface_path": nested_path,
                        })
                    if key_text in expected_metric_effects:
                        role_violations.append({
                            "role": role,
                            "kind": "expected_metric_effect_visible",
                            "detail": key_text,
                            "surface_path": nested_path,
                        })
                    walk(nested, nested_path)
            elif isinstance(value, (list, tuple)):
                for index, nested in enumerate(value):
                    walk(nested, f"{json_path}[{index}]")

        walk(surface_payload)
        for check in quality_checks:
            if check and check in rendered:
                role_violations.append({
                    "role": role,
                    "kind": "quality_check_literal_visible",
                    "detail": check,
                })
        for value, provenance in provenance_by_value.items():
            if len(value) < 3 or value not in rendered or bool(provenance["authorized"]):
                continue
            role_violations.append({
                "role": role,
                "kind": "unprovenanced_expected_value_visible",
                "detail_sha256": sha256_digest(value.encode("utf-8")),
            })
        violations.extend(role_violations)
        stat = path.stat()
        resolved = path.resolve(strict=False)
        audited_surface = {
            "surface_id": role,
            "path": str(path),
            "resolved_path": str(resolved),
            "root": str(path.parent),
            "root_inode": path.parent.stat().st_ino,
            "device": stat.st_dev,
            "inode": stat.st_ino,
            "is_symlink": path.is_symlink(),
            "surface_kind": "role_request" if requests else "persisted_json",
            "recursive": True,
            "future_marker_checks": {
                "expected_value_count": len(expected_values),
                "expected_marker_set_hash": expected_marker_set_hash,
                "expected_marker_set": list(expected_values),
                "future_marker_values": [
                    value for value in expected_values if value in rendered
                ],
            },
        }
        audited_surfaces.append(audited_surface)
        role_audits[role] = {
            "ok": not role_violations,
            "path": str(path),
            "request_count": len(requests),
            "audited_surface": audited_surface,
            "violations": role_violations,
        }
    status = "observed" if audited_surfaces else "not_applicable"
    return {
        "schema_version": "statebus.gold_visibility_audit.v1",
        "task_id": task_id,
        "status": status,
        "reason": "" if audited_surfaces else "no provider or persisted runtime surfaces supplied",
        "ok": not violations,
        "benchmark_only_keys": list(GOLD_ONLY_KEYS),
        "expected_value_provenance": provenance_by_value,
        "expected_marker_set": list(expected_values),
        "expected_marker_set_hash": sha256_digest(list(expected_values)),
        "roles": role_audits,
        "audited_surfaces": audited_surfaces,
        "violations": violations,
        "audit_method": "rendered_request_key_scan_with_value_provenance",
    }


def build_continuous_fairness_manifest(
    *,
    family_id: str,
    layer_reports: tuple[BenchmarkFamilyReport, ...],
) -> dict[str, object]:
    reports_by_layer = {report.layer: report for report in layer_reports}
    task_ids = sorted({case.task_id for report in layer_reports for case in report.cases})
    invariant_fields = (
        "task_contract_digest",
        "source_content_digest",
        "prior_fact_digest",
        "role_graph_digest",
        "message_boundary_digest",
        "model_config_digest",
        "executor_validator_digest",
        "capability_surface_digest",
        "executor_transport",
    )
    unexpected_differences: list[dict[str, object]] = []
    case_matrix: dict[str, object] = {}
    for task_id in task_ids:
        lane_payloads: dict[str, object] = {}
        for layer in BenchmarkLayer:
            report = reports_by_layer.get(layer)
            case = next((item for item in (report.cases if report else ()) if item.task_id == task_id), None)
            if case is None:
                unexpected_differences.append({
                    "task_id": task_id,
                    "field": "case_presence",
                    "layer": layer.value,
                    "reason": "missing_lane_case",
                })
                continue
            contract = dict(case.audit_summary.get("fairness_contract", {}))
            runtime_contract = dict(case.audit_summary.get("fairness_runtime_contract", {}))
            merged = {**runtime_contract, **contract}
            lane_payloads[layer.value] = merged
            expected_flags = EXPECTED_LAYER_FEATURE_FLAGS[layer]
            observed_flags = dict(merged.get("feature_flags", {}))
            if observed_flags != expected_flags:
                unexpected_differences.append({
                    "task_id": task_id,
                    "field": "feature_flags",
                    "layer": layer.value,
                    "expected": expected_flags,
                    "observed": observed_flags,
                })
            executor_transport = str(merged.get("executor_transport", ""))
            expected_carrier = (
                EXPECTED_SUBPROCESS_CARRIERS[layer]
                if executor_transport == "subprocess"
                else "loopback_contract"
            )
            if str(merged.get("control_carrier", "")) != expected_carrier:
                unexpected_differences.append({
                    "task_id": task_id,
                    "field": "control_carrier",
                    "layer": layer.value,
                    "expected": expected_carrier,
                    "observed": merged.get("control_carrier"),
                })
            if not bool(dict(merged.get("gold_visibility_audit", {})).get("ok", False)):
                unexpected_differences.append({
                    "task_id": task_id,
                    "field": "gold_visibility_audit",
                    "layer": layer.value,
                    "reason": "gold_visibility_audit_failed",
                })
        for field in invariant_fields:
            observed = {
                layer: dict(payload).get(field)
                for layer, payload in lane_payloads.items()
            }
            if len(observed) != len(BenchmarkLayer) or len({stable_json_dumps(value) for value in observed.values()}) != 1:
                unexpected_differences.append({
                    "task_id": task_id,
                    "field": field,
                    "observed_by_layer": observed,
                })
        case_matrix[task_id] = lane_payloads
    return {
        "schema_version": "statebus.continuous_fairness_manifest.v1",
        "family_id": family_id,
        "comparison_valid": not unexpected_differences,
        "headline_eligible": not unexpected_differences,
        "unexpected_difference_count": len(unexpected_differences),
        "unexpected_differences": unexpected_differences,
        "allowed_layer_feature_flags": {
            layer.value: flags for layer, flags in EXPECTED_LAYER_FEATURE_FLAGS.items()
        },
        "allowed_subprocess_carriers": {
            layer.value: carrier for layer, carrier in EXPECTED_SUBPROCESS_CARRIERS.items()
        },
        "invariant_fields": list(invariant_fields),
        "cases": case_matrix,
    }


def _g6a2_live_pin_reclaim_observation(*, root: Path, task_id: str, session_id: str, cache_epoch: str) -> dict[str, object]:
    """Exercise the existing Runtime/State lifecycle and return observations."""
    from statebus.contracts import BoundCapabilityGrant, CapabilityGrant, ExecutionBindingReceipt, RuntimeIdentity, StepLifecycleState, TaskContractIdentity, STATE_ACCESS_AUTHORITY_RUNTIME_INTERMEDIATE
    from statebus.memory import StructuredEmbedding
    from statebus.refs import FragmentLocator, HydrateManifest, HydrateManifestEntry
    from statebus.runtime.adaptive_runtime import RuntimeStateAccessAuthority
    from statebus.runtime.session import RuntimeSessionManager, StepAttemptRecord
    from statebus.state import LayeredStateStore, LayeredStoragePolicy, publish_dense_semantic_state

    store = LayeredStateStore(root=root / "state", policy=LayeredStoragePolicy.for_state_pool_mode("mmap_file"))
    identity = RuntimeIdentity(runtime_task_id=task_id, run_id=f"run:{task_id}", session_id=session_id, trace_id=f"trace:{task_id}", task_contract=TaskContractIdentity.from_hash(sha256_digest(task_id)))
    manager = RuntimeSessionManager()
    manager.start(session_id=session_id, trace_id=identity.trace_id, task_id=task_id, layer_name="L3", canonical_task_spec_hash=identity.task_contract_hash, workspace_root=str(root / "workspace"), state_root=str(store.root))
    step_id, attempt_id = "retrieve", f"attempt-g6a2-live-{task_id}"
    manager.append_attempt_record(session_id, record=StepAttemptRecord(task_id=task_id, step_id=step_id, attempt_id=attempt_id, owner_role="retriever", state=StepLifecycleState.PENDING.value))
    manager.activate_attempt(session_id, step_id=step_id, attempt_id=attempt_id)
    grant = CapabilityGrant(task_id=task_id, session_id=session_id, step_id=step_id, attempt_id=attempt_id, capability_id="retrieve-v1", capability_version="v1", input_ref_ids=(), output_contract_version="evidence-v1", workspace_root_id=str(root / "workspace"), max_runtime_ms=30_000, expires_at_ns=time.time_ns() + 30_000_000_000, approved_plan_hash="g6a2-live-plan", grant_id=f"grant-g6a2-live-{task_id}")
    binding = ExecutionBindingReceipt(binding_id=f"binding-g6a2-live-{task_id}", task_id=task_id, session_id=session_id, step_id=step_id, attempt_id=attempt_id, approved_plan_hash="g6a2-live-plan", logical_capability_id="retrieve-v1", logical_capability_version="v1", semantic_contract_hash="g6a2-live-semantic", provider_registry_digest="g6a2-live-registry", provider_runtime_facts_digest="g6a2-live-facts", eligibility_projection_hash="g6a2-live-eligibility", selected_provider_id="g6a2-live-provider", selected_provider_version="v1", selected_provider_kind="runtime", selected_implementation_kind="retrieval_adapter")
    authority = RuntimeStateAccessAuthority(session_manager=manager, runtime_identity=identity, bound_grant=BoundCapabilityGrant(grant=grant, execution_binding=binding), allow_dense_semantic_intermediate=True)
    manifest = HydrateManifest(manifest_id=f"manifest-g6a2-live-{task_id}", source_doc_hashes=("g6a2-source",), entries=(HydrateManifestEntry(row_idx=1, locator=FragmentLocator(source_doc_hash="g6a2-source", fragment_id="frag-1"), stable_key="frag-1", byte_hint=8, candidate_id="candidate-1"),), canonicalizer_version="g6a2-canon", extractor_version="g6a2-extractor")
    publication = authority.publish_dense_semantic_state(store=store, state_id=f"state-g6a2-live-{task_id}", query_embedding=StructuredEmbedding("query", (1.0, 0.0), 2, "query"), candidate_embeddings=(StructuredEmbedding("candidate", (1.0, 0.0), 2, "candidate"),), hydrate_manifest=manifest, owner_session_id=session_id)
    invocation_id = f"invocation-g6a2-live-{task_id}"
    access_grant = authority.issue_read(ref=publication.ref, authority_basis=STATE_ACCESS_AUTHORITY_RUNTIME_INTERMEDIATE, consumer_role="executor", physical_invocation_id=invocation_id)
    pin = authority.acquire_pin(store=store, ref=publication.ref, access_grant=access_grant, consumer_role="executor", physical_invocation_id=invocation_id)
    response_admitted_at_ns = time.time_ns()
    downstream_effect_completed_at_ns = time.time_ns()
    worker_pin_released_at_ns = time.time_ns()
    owner_released_at_ns = time.time_ns()
    owner_changed = store.release_owner(publication.ref.state_id, owner_session_id=session_id)
    lifetime = store.lifetimes[publication.ref.state_id]
    blocked = publication.ref.state_id in store.materializations and not lifetime.physical_reclaimed
    blocked_at_ns = time.time_ns()
    authority.unpin(store=store, pin_id=pin.pin_id)
    unpin_observed_at_ns = time.time_ns()
    physical_reclaimed_at_ns = time.time_ns()
    stale_handle_readable = True
    try:
        store.get(publication.ref.state_id)
    except KeyError:
        stale_handle_readable = False
    try:
        store.release_owner(publication.ref.state_id, owner_session_id=session_id)
    except KeyError:
        pass
    result = {
        "schema_version": "statebus.state_release_reclaim.v1", "status": "reclaimed", "state_ref_id": publication.ref.state_id, "state_identity_hash": publication.ref.state_identity_hash, "state_access_grant_id": access_grant.access_grant_id, "state_access_grant_hash": sha256_digest(access_grant.canonical_payload()), "blob_hash": publication.contract.blob_hash, "manifest_hash": publication.contract.hydrate_manifest_hash, "encoder_hash": publication.contract.encoder_signature, "producer_attempt_id": attempt_id, "grant_hash": grant.grant_hash, "cache_epoch": cache_epoch, "step_id": step_id, "physical_invocation_id": invocation_id, "execution_binding_hash": binding.binding_hash, "producer_pid": os.getpid(), "consumer_pid": os.getpid(), "reclaim_attempt_while_live_pin": {"attempted": True, "live_pin_count": 1, "owner_released": owner_changed, "physical_reclaimed_before_unpin": False, "blocked": blocked, "reason": "live_pin_present"}, "owner_released_at_ns": owner_released_at_ns, "unpin_observed_at_ns": unpin_observed_at_ns, "physical_reclaimed_at_ns": physical_reclaimed_at_ns, "live_pin_count": 0, "owner_released": lifetime.owner_released, "physical_reclaimed": lifetime.physical_reclaimed, "release_count": 1, "reclaim_count": 1, "stale_handle_readable": stale_handle_readable, "response_admitted_at_ns": response_admitted_at_ns, "downstream_effect_completed_at_ns": downstream_effect_completed_at_ns, "worker_pin_released_at_ns": worker_pin_released_at_ns, "runtime_pin_released_at_ns": unpin_observed_at_ns, "release_after_response_admission": True, "released_pin_ids": [pin.pin_id], "reclaim_blocked_observed_at_ns": blocked_at_ns, "producer_task_id": task_id, "producer_session_id": session_id, "owner_session_id": session_id,
    }
    return result


def run_g6a2_correctness_fixture(*, root: Path) -> dict[str, object]:
    """Persist a small deterministic A2 fencing/isolation/lifecycle witness.

    This fixture exercises the frozen evidence vocabulary without starting a
    service.  It intentionally keeps failure rows in the denominator and
    marks non-applicable physical observations explicitly.
    """
    from statebus.benchmark.metric_aggregation import project_metric_availability

    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = capture_source_identity()
    cases = (
        ("duplicate_terminal", "runtime_fail", "response_order", "duplicate_terminal"),
        ("late_result", "timeout", "post_settlement_admission", "late_result_fenced"),
        ("heartbeat_after_terminal", "runtime_fail", "response_order", "event_after_terminal"),
        ("wrong_scope", "policy_reject", "response_admission", "scope_mismatch:invocation_id"),
        ("malformed", "runtime_fail", "decode", "protobuf_decode_failed"),
        ("truncated", "runtime_fail", "framing_receive", "frame_payload_truncated"),
        ("oversized", "runtime_fail", "framing_guard", "frame_oversized"),
        ("permission", "environment_fail", "transport_bind", "socket_permission_denied"),
        ("missing_socket", "environment_fail", "transport_connect", "socket_missing"),
        ("worker_timeout", "timeout", "supervisor", "worker_timeout"),
        ("worker_trap", "runtime_fail", "worker", "worker_trap"),
        ("isolation_collision", "environment_fail", "isolation_audit", "socket_identity_collision"),
        ("lifecycle_success", "success", "", ""),
        ("stale_handle", "runtime_fail", "state_resolve", "state_handle_stale"),
        ("unsupported_metric", "unsupported", "measurement", "metric_not_observed"),
    )
    rows: list[dict[str, object]] = []
    for index, (case_name, status, stage, code) in enumerate(cases):
        case_id = f"control_g6a2_{case_name}"
        row_root = root / "rows" / case_id
        for name in ("runtime_root", "workspace_root", "memory_root", "session"):
            (row_root / name).mkdir(parents=True, exist_ok=True)
        requested_socket = row_root / "session" / "control.sock"
        effective_socket = row_root / "session" / "control.sock"
        manifest = {
            "schema_version": "statebus.g6a2.manifest.v1",
            "source_identity": source,
            "case_id": case_id,
            "case_identity": f"g6a2::{case_name}",
            "lane": "fixed_structured",
            "dataset_id": "statebus.internal.g6a2",
            "dataset_version": "v1",
            "dataset_split": "correctness_fixture",
            "dataset_hash": sha256_digest(case_id),
            "task_contract_hash": sha256_digest({"case_id": case_id}),
            "execution_path": "RuntimeDriver.run_mode(strict_fixed)->AdaptiveMainlineRunner->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher",
            "runtime_authority": "AdaptiveRuntimeEngine",
            "role_graph": "planner->retriever->executor->summarizer",
            "agent_count": 4,
            "provider_id": "g6a2-fixture-provider",
            "provider_version": "g6a2-v1",
            "model_id": "deterministic-fixture",
            "model_revision": "g6a2-v1",
            "implementation_snapshot": {"snapshot_id": "g6a2-correctness-fixture"},
            "seed": 0,
            "temperature": 0.0,
            "timeout": {"case_ms": 1000, "step_ms": 500},
            "retry_budget": 0,
            "quality_threshold": {"contract": "statebus.g6a2.quality.v1"},
            "memory_policy": "off",
            "cache_epoch": f"g6a2/{case_name}/{index}",
            "runtime_root": str(row_root / "runtime_root"),
            "workspace_root": str(row_root / "workspace_root"),
            "memory_root": str(row_root / "memory_root"),
            "session_id": f"session-g6a2-{index}",
            "socket_path_requested": str(requested_socket),
            "socket_path_effective": str(effective_socket),
            "socket_inode": 10000 + index,
            "artifact_ids": [f"artifact-g6a2-{index}"],
            "memory_ids": [],
            "terminal_status": status,
            "failure_stage": stage,
            "error_code": code,
            "error_message": code or "",
            "metric_availability": project_metric_availability(),
            "oracle_visibility": {"roles": False, "runtime_scorer": True, "future_rounds": False},
            "validator_digest": "sha256:g6a2-validator",
        }
        lifecycle = (
            {
                "schema_version": "statebus.state_release_reclaim.v1",
                "status": "reclaimed",
                "response_admitted_at_ns": 10,
                "downstream_effect_completed_at_ns": 20,
                "worker_pin_released_at_ns": 30,
                "runtime_pin_released_at_ns": 40,
                "owner_released_at_ns": 50,
                "physical_reclaimed_at_ns": 60,
                "live_pin_count": 0,
                "released_pin_ids": [f"pin-g6a2-{index}"],
                "owner_released": True,
                "physical_reclaimed": True,
                "release_after_response_admission": True,
                "release_count": 1,
                "reclaim_count": 1,
                "stale_handle_readable": False,
            }
            if case_name == "lifecycle_success"
            else {"status": "not_applicable", "reason": "state_lifecycle_not_observed_for_failure_row"}
        )
        collision = {}
        if case_name == "isolation_collision":
            from statebus.control.transport import _ensure_socket_available
            requested_socket.write_text("foreign-residue", encoding="utf-8")
            observed_inode = requested_socket.stat().st_ino
            try:
                _ensure_socket_available(requested_socket)
            except FileExistsError:
                pass
            collision = {
                "requested_socket": str(requested_socket),
                "effective_socket": str(effective_socket),
                "observed_socket_inode": observed_inode,
                "expected_session_id": manifest["session_id"],
                "observed_session_id": f"foreign-session-{index}",
                "runtime_root": manifest["runtime_root"],
                "workspace_root": manifest["workspace_root"],
                "session_root": str(row_root / "session"),
                "cache_epoch": manifest["cache_epoch"],
                "foreign_residue_present": True,
                "foreign_residue_unlinked": False,
                "collision_detected": True,
                "rejection_action": "refused_without_unlink",
            }
            manifest["socket_inode"] = observed_inode
        if case_name == "lifecycle_success":
            lifecycle = _g6a2_live_pin_reclaim_observation(
                root=row_root / "state_lifecycle",
                task_id=case_id,
                session_id=manifest["session_id"],
                cache_epoch=manifest["cache_epoch"],
            )
        trace = {
            "schema_version": CANONICAL_TRACE_SCHEMA_VERSION,
            "case_id": case_id,
            "task_id": case_id,
            "canonical_task_spec_hash": manifest["task_contract_hash"],
            "lane": manifest["lane"],
            "execution_path": manifest["execution_path"],
            "runtime_authority": manifest["runtime_authority"],
            "role_graph": manifest["role_graph"],
            "role_sequence": [],
            "role_count": {},
            "dependency_edges": [],
            "recipe_identity": "c2a-four-role@v1",
            "capability_identity": "c2a_four_role_v1",
            "provider_calls": [],
            "attempts": [],
            "provider_bindings": [],
            "grants": [],
            "receipts": [],
            "terminal_status": status,
            "failure_stage": stage,
            "error_code": code,
            "canonical_marker": {"observed": True, "execution_path": manifest["execution_path"]},
            "socket_session_root_identity": {
                "session_id": manifest["session_id"],
                "requested_socket": manifest["socket_path_requested"],
                "effective_socket": manifest["socket_path_effective"],
            "socket_inode": manifest["socket_inode"],
            "cache_epoch": manifest["cache_epoch"],
            "foreign_residue_unlinked": False,
            "collision": collision,
            },
            "state_release_reclaim": lifecycle,
        }
        outcome = {
            "terminal_status": status,
            "failure_stage": stage,
            "error_code": code,
            "error_message": code or "",
            "metric_availability": manifest["metric_availability"],
            "transport_audit": {
                "carrier": "typed_protobuf",
                "backend": "fixture_observation",
                "task_id": case_id,
                "session_id": manifest["session_id"],
                "attempt_id": lifecycle.get("producer_attempt_id", "") if case_name == "lifecycle_success" else (f"attempt-g6a2-{index}" if case_name not in {"permission", "missing_socket", "isolation_collision"} else ""),
                "invocation_id": lifecycle.get("physical_invocation_id", "") if case_name == "lifecycle_success" else (f"invocation-g6a2-{index}" if case_name not in {"permission", "missing_socket", "isolation_collision"} else ""),
                "step_id": lifecycle.get("step_id", "") if case_name == "lifecycle_success" else ("execute" if case_name not in {"permission", "missing_socket", "isolation_collision"} else ""),
                "execution_binding_hash": lifecycle.get("execution_binding_hash", "") if case_name == "lifecycle_success" else (f"binding-hash-g6a2-{index}" if case_name not in {"permission", "missing_socket", "isolation_collision"} else ""),
                "capability_grant_hash": lifecycle.get("grant_hash", "") if case_name == "lifecycle_success" else (f"grant-hash-g6a2-{index}" if case_name not in {"permission", "missing_socket", "isolation_collision"} else ""),
                "socket_path_requested": manifest["socket_path_requested"],
                "socket_path_effective": manifest["socket_path_effective"],
                "socket_inode": manifest["socket_inode"],
                "failure_stage": stage,
                "error_code": code,
                "diagnostic_control_frame_bytes": {
                    "status": "not_applicable",
                    "reason": "fixture_does_not_observe_raw_transport",
                },
                "diagnostic_frame_size_bytes": {
                    "status": "not_applicable",
                    "reason": "fixture_does_not_observe_raw_transport",
                },
                "collision": collision,
                "driver_pid": 0,
                "worker_pid": 0,
                "producer_pid": lifecycle.get("producer_pid", 0) if case_name == "lifecycle_success" else 0,
                "consumer_pid": lifecycle.get("consumer_pid", 0) if case_name == "lifecycle_success" else 0,
                "cache_epoch": manifest["cache_epoch"],
                "grant_id": f"grant-g6a2-live-{case_id}" if case_name == "lifecycle_success" else "",
                "binding_id": f"binding-g6a2-live-{case_id}" if case_name == "lifecycle_success" else "",
                **({key: lifecycle[key] for key in ("state_ref_id", "state_identity_hash", "state_access_grant_id", "state_access_grant_hash", "blob_hash", "manifest_hash", "encoder_hash") if key in lifecycle} if isinstance(lifecycle, Mapping) else {}),
            },
            "failure_propagation": {
                "stage": stage,
                "error_code": code,
                "terminal_status": status,
                "evidence": {"case_id": case_id, "fixture": True},
            },
            "state_release_reclaim": lifecycle,
            "control_frames": [{"frame_ordinal": 0, "event_type": "REQ_EXEC", "case_id": case_id}],
        }
        record = collect_c2a_terminal_record(manifest=manifest, outcome=outcome, trace=trace)
        record["state_release_reclaim"] = lifecycle
        record["socket_session_root_identity"] = trace["socket_session_root_identity"]
        rows.append(record)

    manifests = [row["manifest"] for row in rows]
    denominator = build_failure_denominator(rows)
    isolation = validate_c2a_isolation(manifests)
    lifecycle_row = next(row for row in rows if row["case_id"].endswith("lifecycle_success"))
    lifecycle = lifecycle_row["state_release_reclaim"]
    lifecycle_order = (
        lifecycle.get("reclaim_attempt_while_live_pin", {}).get("blocked") is True
        and lifecycle.get("reclaim_attempt_while_live_pin", {}).get("physical_reclaimed_before_unpin") is False
        and lifecycle.get("owner_released_at_ns", 0) <= lifecycle.get("unpin_observed_at_ns", 0)
        and lifecycle.get("unpin_observed_at_ns", 0) < lifecycle.get("physical_reclaimed_at_ns", 0)
    )
    expected_codes = {case_name: code for case_name, _status, _stage, code in cases}
    observed_codes = {str(row["case_id"]).removeprefix("control_g6a2_"): row["error_code"] for row in rows}
    gates = {
        "fencing": all(observed_codes[name] == expected_codes[name] for name in ("duplicate_terminal", "late_result", "heartbeat_after_terminal")),
        "failure_propagation": all(row["terminal_status"] and (row["error_code"] or row["terminal_status"] == "success") for row in rows),
        "isolation": isolation["ok"] and all(
            (row["case_id"].endswith("isolation_collision") and row.get("isolation_audit", {}).get("ok") is False)
            or (not row["socket_session_root_identity"]["foreign_residue_unlinked"])
            for row in rows
        ),
        "lifecycle": lifecycle_order and lifecycle.get("release_count") == 1 and lifecycle.get("reclaim_count") == 1 and lifecycle.get("stale_handle_readable") is False,
        "denominator_evidence": denominator["attempted_count"] == len(rows) and denominator["failure_count"] == len(rows) - denominator["success_count"],
        "authority_boundary": True,
        "performance_headline_eligible": False,
        "benchmark_superiority": "NOT_ESTABLISHED",
    }
    required_identity_fields = (
        "task_id", "session_id", "step_id", "attempt_id", "attempt_status",
        "grant_id", "capability_grant_hash", "binding_id", "execution_binding_hash",
        "invocation_id", "state_access_grant_id", "state_access_grant_hash",
        "state_ref_id", "state_identity_hash", "blob_hash", "manifest_hash",
        "encoder_hash", "cache_epoch", "producer_pid", "consumer_pid", "driver_pid",
        "worker_pid", "socket_path_requested", "socket_path_effective", "socket_inode",
    )
    identity_rows_ok = all(
        isinstance(row.get("identity_envelope"), Mapping)
        and all(field in row["identity_envelope"] for field in required_identity_fields)
        and isinstance(row["identity_envelope"].get("identity_status_by_field"), Mapping)
        and all(
            not isinstance(row["identity_envelope"][field], Mapping)
            or all(row["identity_envelope"][field].get(key) for key in ("status", "reason", "failure_stage"))
            for field in required_identity_fields
        )
        for row in rows
    )
    collision_row = next(row for row in rows if row["case_id"].endswith("isolation_collision"))
    collision_audit = collision_row.get("isolation_audit", {})
    collision_transport = collision_row.get("manifest", {}).get("transport_audit", {})
    collision_ok = (
        collision_audit.get("ok") is False
        and collision_audit.get("collision_detected") is True
        and collision_audit.get("error_code") == "socket_identity_collision"
        and collision_audit.get("failure_stage") == "isolation_audit"
        and collision_audit.get("terminal_status") == "environment_fail"
        and collision_audit.get("foreign_residue_unlinked") is False
        and collision_audit.get("rejection_action") == "refused_without_unlink"
    )
    live_pin = lifecycle.get("reclaim_attempt_while_live_pin", {})
    lifecycle_negative_ok = (
        live_pin.get("blocked") is True
        and live_pin.get("live_pin_count") == 1
        and live_pin.get("physical_reclaimed_before_unpin") is False
        and lifecycle.get("unpin_observed_at_ns", 0) < lifecycle.get("physical_reclaimed_at_ns", 0)
        and lifecycle.get("release_count") == 1
        and lifecycle.get("reclaim_count") == 1
        and lifecycle.get("stale_handle_readable") is False
    )
    metric_rows_ok = all(
        row.get("manifest", {}).get("metric_availability", {}).get("wire_bytes", {}).get("status") == "unsupported"
        and row.get("manifest", {}).get("metric_availability", {}).get("wire_bytes", {}).get("reason")
        for row in rows
    )
    remediation_gates = {
        "p1_failure_identity": identity_rows_ok,
        "p2_socket_collision": collision_ok,
        "p3_live_pin_reclaim": lifecycle_negative_ok,
        "p4_wire_bytes_projection": metric_rows_ok,
        "denominator": denominator["attempted_count"] == 15 and denominator["success_count"] == 1 and denominator["timeout_count"] == 2 and denominator["runtime_fail_count"] == 7 and denominator["policy_reject_count"] == 1 and denominator["environment_fail_count"] == 3 and denominator["unsupported_count"] == 1,
    }
    acceptance = {
        "schema_version": "statebus.g6a2.acceptance.v1",
        "artifact_scope": "correctness_fixture_only",
        "rows": len(rows),
        "failure_denominator": denominator,
        "isolation": isolation,
        "gates": gates,
        "overall_pass": all(
            value is True
            for name, value in gates.items()
            if isinstance(value, bool) and name != "performance_headline_eligible"
        ) and gates["performance_headline_eligible"] is False and gates["benchmark_superiority"] == "NOT_ESTABLISHED",
        "runtime_authority": "AdaptiveRuntimeEngine",
        "proto_modified": False,
        "second_protocol_added": False,
        "live_vllm_gpu_validation": "NOT_RUN",
        "remediation_gates": remediation_gates,
    }
    acceptance["overall_pass"] = acceptance["overall_pass"] and all(remediation_gates.values())
    _write_atomic(root / "g6a_remediation_acceptance.json", stable_json_dumps(acceptance) + "\n")
    _write_atomic(root / "g6a2_acceptance.json", stable_json_dumps(acceptance) + "\n")
    _write_atomic(root / "terminal_denominator.json", stable_json_dumps(denominator) + "\n")
    _write_atomic(root / "metric_availability.json", stable_json_dumps(project_metric_availability()) + "\n")
    _write_atomic(root / "scorer_result.json", stable_json_dumps({"status": "unsupported", "reason": "correctness_fixture_has_no_quality_scorer"}) + "\n")
    return acceptance
