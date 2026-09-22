"""Join completed contest-core smoke artifacts into one honest P11 gate.

This is an orchestration gate, not a new Runtime and not a performance
aggregate.  It verifies that the independently owned P1/P2/P3/P4/P5 stages
all produced their canonical success artifacts before a campaign is promoted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from statebus.benchmark.contest_core_campaign import (
    STAGE2_FAMILY_CASE_COUNTS,
    STAGE2_FAMILY_IDS,
    _feature_flags,
)
from statebus.utils import stable_json_dumps


SCHEMA_VERSION = "statebus.contest_core_integrated_gate.v1"
FULL_STAGE2_CASE_COUNT = sum(STAGE2_FAMILY_CASE_COUNTS.values())
FULL_STAGE2_LANE_COUNT = 4
FULL_STAGE2_PLANNED_ROWS = FULL_STAGE2_CASE_COUNT * FULL_STAGE2_LANE_COUNT


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"contest_core_gate_object_required:{path}")
    return payload


def _find_payload(
    root: Path,
    filename: str,
    predicate: Callable[[dict[str, Any]], bool],
) -> tuple[Path | None, dict[str, Any] | None]:
    if not root.is_dir():
        return None, None
    for path in sorted(root.rglob(filename), reverse=True):
        try:
            payload = _read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if predicate(payload):
            return path, payload
    return None, None


def _full_registry_contract(root: Path) -> dict[str, Any]:
    """Recompute the full P1 scope from the campaign manifest and receipt.

    P11 is the promotion gate for the requested full campaign.  A bounded
    pilot may be useful evidence, but it must never satisfy this gate merely
    because its rows are terminal and its status says ``pilot_ready``.
    """

    manifest_path = root / "campaign_manifest.json"
    if not manifest_path.is_file():
        return {
            "manifest_present": False,
            "scope_full_registry": False,
            "family_set_complete": False,
            "case_count_48": False,
            "lane_count_4": False,
            "planned_rows_192": False,
            "expected_planned_rows": FULL_STAGE2_PLANNED_ROWS,
            "manifest_path": str(manifest_path),
        }
    try:
        manifest = _read_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {
            "manifest_present": False,
            "scope_full_registry": False,
            "family_set_complete": False,
            "case_count_48": False,
            "lane_count_4": False,
            "planned_rows_192": False,
            "expected_planned_rows": FULL_STAGE2_PLANNED_ROWS,
            "manifest_path": str(manifest_path),
        }
    selection = manifest.get("p1_selection")
    selection = selection if isinstance(selection, dict) else {}
    family_ids = tuple(str(item) for item in selection.get("family_ids", ()))
    expected_rows = int(selection.get("planned_rows", 0) or 0)
    return {
        "manifest_present": True,
        "scope_full_registry": selection.get("scope") == "full_registry"
        and int(selection.get("max_cases_per_family", -1)) == 0,
        "family_set_complete": set(family_ids) == set(STAGE2_FAMILY_IDS),
        "case_count_48": int(selection.get("independent_case_count", 0) or 0)
        == FULL_STAGE2_CASE_COUNT,
        "lane_count_4": int(selection.get("lane_count", 0) or 0)
        == FULL_STAGE2_LANE_COUNT,
        "planned_rows_192": expected_rows == FULL_STAGE2_PLANNED_ROWS,
        "expected_planned_rows": FULL_STAGE2_PLANNED_ROWS,
        "manifest_path": str(manifest_path),
    }


def _p1_full_denominator_check(
    p1: dict[str, Any],
    *,
    expected_rows: int,
) -> dict[str, bool]:
    denominator = p1.get("denominator")
    denominator = denominator if isinstance(denominator, dict) else {}
    return {
        "status_live": p1.get("status") == "pilot_ready"
        and p1.get("run_mode") == "live_measurement",
        "planned_rows": int(p1.get("planned_slots", 0) or 0) == expected_rows
        and int(denominator.get("planned_count", 0) or 0) == expected_rows,
        "started_rows": int(denominator.get("started_count", 0) or 0) == expected_rows
        and int(denominator.get("provider_started_count", 0) or 0) == expected_rows,
        "settled_rows": int(denominator.get("settled_count", 0) or 0) == expected_rows,
        "observed_rows": int(p1.get("observed_rows", 0) or 0) == expected_rows
        and int(denominator.get("observed_row_count", 0) or 0) == expected_rows
        and int(denominator.get("observed_slot_id_count", 0) or 0) == expected_rows,
        "arithmetic_closed": denominator.get("arithmetic_closed") is True
        and int(denominator.get("not_started_count", 0) or 0) == 0
        and int(denominator.get("unknown_count", 0) or 0) == 0
        and int(denominator.get("unsupported_count", 0) or 0) == 0
        and not denominator.get("missing")
        and not denominator.get("extra")
        and not denominator.get("duplicate"),
    }


def evaluate_integrated_gate(
    *,
    campaign_root: Path,
    feature_variant: str = "full",
) -> dict[str, Any]:
    root = campaign_root.expanduser().resolve()
    flags = _feature_flags(feature_variant)
    if feature_variant != "full":
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unsupported",
            "exit_code": 3,
            "feature_variant": feature_variant,
            "feature_flags": flags,
            "reason": "p11_variant_execution_runner_not_implemented",
            "formal_campaign_executed": False,
            "benchmark_superiority": "NOT_ESTABLISHED",
            "statistical_superiority": "NOT_ESTABLISHED",
        }

    p1_path = root / "p1" / "acceptance.json"
    p2_path = root / "p2" / "acceptance.json"
    p4_path = root / "p4" / "acceptance.json"
    p1 = _read_json(p1_path) if p1_path.is_file() else {}
    p2 = _read_json(p2_path) if p2_path.is_file() else {}
    p4 = _read_json(p4_path) if p4_path.is_file() else {}

    p3_path, p3 = _find_payload(
        root / "p3",
        "summary.json",
        lambda item: item.get("schema_version")
        == "statebus.semantic_state_ablation_summary.v1",
    )
    p4_live_path, p4_live = _find_payload(
        root / "p4-live",
        "final_gate_status.json",
        lambda item: item.get("schema_version")
        == "statebus.g6b2.final_gate_status.v1",
    )
    p5_live_path, p5_live = _find_payload(
        root / "p5-live",
        "summary.json",
        lambda item: item.get("schema_version") == "statebus.adaptive_live_task.v1",
    )

    p3_denominator = dict((p3 or {}).get("denominator", {}))
    p4_metrics = dict(p4.get("metrics", {}))
    p5_telemetry = dict((p5_live or {}).get("telemetry", {}))
    p5_execution_identity = dict((p5_live or {}).get("execution_identity", {}))
    p5_container_identity = dict(p5_execution_identity.get("container", {}))
    p5_sandbox_children = [
        dict(item)
        for item in p5_execution_identity.get("sandbox_children", [])
        if isinstance(item, dict)
    ]
    full_registry = _full_registry_contract(root)
    p1_denominator_checks = _p1_full_denominator_check(
        p1,
        expected_rows=int(full_registry["expected_planned_rows"]),
    )
    checks = {
        "p1_full_registry_manifest": all(
            bool(full_registry[name])
            for name in (
                "manifest_present",
                "scope_full_registry",
                "family_set_complete",
                "case_count_48",
                "lane_count_4",
                "planned_rows_192",
            )
        ),
        "p1_four_lane_live_ready": p1_denominator_checks["status_live"],
        "p1_full_denominator_closed": all(p1_denominator_checks.values()),
        "p2_threshold_sweep_passed": p2.get("status") == "passed",
        "p3_activation_quality_passed": bool((p3 or {}).get("ok"))
        and int(p3_denominator.get("closed_pairs", 0)) >= 1
        and int(p3_denominator.get("inactive_negative_control_pairs", 0)) >= 1,
        "p4_accounting_and_recipe_passed": p4.get("status") == "passed"
        and dict(p4_metrics.get("verified_recipe_work_avoided", {})).get("status")
        == "observed",
        "p4_live_provider_chain_passed": (p4_live or {}).get("status")
        == "MINIMAL_PAIR_VERIFIED_FOR_USER_CAMPAIGN"
        and (p4_live or {}).get("service_stop_called") is False,
        "p5_live_codeact_bwrap_passed": bool((p5_live or {}).get("ok"))
        and float(p5_telemetry.get("llm_codeact_verified_count", 0.0)) >= 1.0
        and float(p5_telemetry.get("llm_codeact_sandbox_fallback_count", 0.0))
        == 0.0
        and isinstance(p5_container_identity.get("uid"), int)
        and isinstance(p5_container_identity.get("gid"), int)
        and bool(p5_sandbox_children)
        and all(
            child.get("backend") == "bwrap"
            and int(child.get("uid", 0)) == 65534
            and int(child.get("gid", 0)) == 65534
            and not child.get("fallback_reason")
            for child in p5_sandbox_children
        ),
        "deferred_routes_excluded": not any(
            flags[name]
            for name in (
                "cross_text_semantic_state",
                "engine_local_kv",
                "hidden_latent",
                "apc_prefix",
            )
        ),
    }
    passed = all(checks.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed" if passed else "failed",
        "exit_code": 0 if passed else 1,
        "campaign_root": str(root),
        "feature_variant": feature_variant,
        "feature_flags": flags,
        "checks": checks,
        "evidence": {
            "campaign_manifest": str(full_registry["manifest_path"]),
            "p1": str(p1_path) if p1_path.is_file() else "",
            "p2": str(p2_path) if p2_path.is_file() else "",
            "p3": "" if p3_path is None else str(p3_path),
            "p4": str(p4_path) if p4_path.is_file() else "",
            "p4_live": "" if p4_live_path is None else str(p4_live_path),
            "p5_live": "" if p5_live_path is None else str(p5_live_path),
        },
        "p1_scope": {
            **full_registry,
            "denominator_checks": p1_denominator_checks,
        },
        "claim_boundary": (
            "serial smoke artifact closure only; no joint latency aggregate, "
            "benchmark superiority, or statistical superiority claim"
        ),
        "formal_campaign_executed": False,
        "benchmark_superiority": "NOT_ESTABLISHED",
        "statistical_superiority": "NOT_ESTABLISHED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the P11 integrated smoke gate.")
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--feature-variant",
        default="full",
        choices=(
            "full",
            "without_semantic_state",
            "without_memory",
            "without_adaptive_routing",
            "without_codeact",
            "memory_off_semantic_state_off",
            "memory_off_semantic_state_on",
            "memory_on_semantic_state_off",
            "memory_on_semantic_state_on",
        ),
    )
    args = parser.parse_args()
    result = evaluate_integrated_gate(
        campaign_root=args.campaign_root,
        feature_variant=args.feature_variant,
    )
    args.output_root.mkdir(parents=True, exist_ok=False)
    (args.output_root / "acceptance.json").write_text(
        stable_json_dumps(result) + "\n", encoding="utf-8"
    )
    print(stable_json_dumps(result))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
