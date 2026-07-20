from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from v2.benchmark.models import BenchmarkFamilyReport, BenchmarkLayer
from v2.utils import sha256_digest, stable_json_dumps


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
