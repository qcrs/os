from __future__ import annotations

import json
import os
import re
import subprocess
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
) -> dict[str, object]:
    """Reject benchmark-only oracle fields in provider/role-visible payloads."""

    violations: list[dict[str, object]] = []

    def walk(value: object, path: str) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized = str(key).strip().lower()
                if normalized in _ORACLE_KEYS or normalized.startswith("expected_"):
                    violations.append({"path": f"{path}.{key}", "kind": "oracle_key_visible"})
                walk(nested, f"{path}.{key}")
        elif isinstance(value, (list, tuple, set)):
            for index, nested in enumerate(value):
                walk(nested, f"{path}[{index}]")

    walk(provider_request, "provider_request")
    walk(role_visible_input, "role_visible_input")
    walk(future_rounds, "future_rounds")
    return {
        "gold_visible": False,
        "expected_route_visible": False,
        "expected_tool_visible": False,
        "future_rounds_visible": False,
        "ok": not violations,
        "violations": violations,
        "audit_method": "recursive_visible_payload_key_scan",
    }


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
    if manifest.get("execution_path") not in {"canonical", "legacy_comparator"}:
        errors.append({"field": "execution_path", "reason": "unsupported_execution_path"})
    if lane in CANONICAL_LANES and manifest.get("execution_path") != "canonical":
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
        and manifest.get("execution_path") == "canonical"
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
            resolved_paths[field].append(str(path.resolve()))
            if path.exists():
                stat = path.stat()
                inode_paths[field].append((stat.st_dev, stat.st_ino))
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
            })
            (lane_root / "manifest.json").write_text(stable_json_dumps(manifest), encoding="utf-8")
            (lane_root / "stdout.log").write_text("", encoding="utf-8")
            (lane_root / "stderr.log").write_text("", encoding="utf-8")
            (lane_root / "root_listing.json").write_text(
                stable_json_dumps({"runtime_root": str(lane_root / "runtime_root"), "workspace_root": str(lane_root / "workspace_root"), "memory_root": str(lane_root / "memory_root")}),
                encoding="utf-8",
            )
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
        "pilot_eligible": True,
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
    projected["attempt_count"] = len(observed_trace.get("attempts", observed_trace.get("calls", ())))
    (lane_root / "manifest.json").write_text(stable_json_dumps(projected), encoding="utf-8")
    (lane_root / "terminal.json").write_text(
        stable_json_dumps({
            "case_id": projected.get("case_id"),
            "lane": projected.get("lane"),
            "terminal_status": status,
            "failure_stage": projected["failure_stage"],
            "error_code": projected["error_code"],
            "error_message": projected["error_message"],
            "metric_availability": projected["metric_availability"],
            "trace_present": bool(trace),
        }),
        encoding="utf-8",
    )
    listing = {
        name: sorted(
            str(path.relative_to(Path(str(manifest["runtime_root"])).parent))
            for path in Path(str(manifest[name])).parent.glob("**/*")
            if path.is_file()
        )
        for name in ("runtime_root", "workspace_root", "memory_root")
    }
    (lane_root / "root_listing.json").write_text(stable_json_dumps(listing), encoding="utf-8")
    if trace:
        (lane_root / "runtime_trace.json").write_text(stable_json_dumps(trace), encoding="utf-8")
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
        "trace": dict(trace or {}),
        "manifest": projected,
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
    """Audit actual rendered requests while allowing source-derived value overlap."""

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
        role_violations: list[dict[str, object]] = []
        if requests and not any("messages" in item for item in requests if isinstance(item, dict)):
            role_violations.append({
                "role": role,
                "kind": "request_content_not_persisted",
                "detail": str(path),
            })
        rendered = stable_json_dumps(requests)
        for key in GOLD_ONLY_KEYS:
            if re.search(rf'["\']{re.escape(key)}["\']\s*:', rendered):
                role_violations.append({
                    "role": role,
                    "kind": "benchmark_only_key_visible",
                    "detail": key,
                })
        for check in quality_checks:
            if check and check in rendered:
                role_violations.append({
                    "role": role,
                    "kind": "quality_check_literal_visible",
                    "detail": check,
                })
        for metric_key in expected_metric_effects:
            if metric_key and metric_key in rendered:
                role_violations.append({
                    "role": role,
                    "kind": "expected_metric_effect_visible",
                    "detail": metric_key,
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
        role_audits[role] = {
            "ok": not role_violations,
            "path": str(path),
            "request_count": len(requests),
            "violations": role_violations,
        }
    return {
        "schema_version": "statebus.gold_visibility_audit.v1",
        "task_id": task_id,
        "ok": not violations,
        "benchmark_only_keys": list(GOLD_ONLY_KEYS),
        "expected_value_provenance": provenance_by_value,
        "roles": role_audits,
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
