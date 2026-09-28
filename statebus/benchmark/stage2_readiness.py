"""Offline readiness checks for the contest Stage 2 mechanism experiments.

This module deliberately does not start a model service or execute a live
mechanism campaign.  It verifies the deterministic Memory contract and the
public fixture/registry contracts that must be true before a formal Stage 2
runner can be admitted.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

from statebus.benchmark import stage2_pilot
from statebus.benchmark.memory_ablation import run_memory_ablation
from statebus.benchmark.semantic_holdout import load_semantic_holdout_cases
from statebus.benchmark.stage2_contract import LANES, validate_public_case
from statebus.utils import stable_json_dumps


SCHEMA_VERSION = "statebus.contest_stage2_readiness.v1"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")


def _prepare_output_root(output_root: Path) -> None:
    if output_root.exists():
        if not output_root.is_dir() or any(output_root.iterdir()):
            raise FileExistsError(f"stage2_readiness_output_root_not_empty:{output_root}")
        return
    output_root.mkdir(parents=True, exist_ok=False)


def _audit_semantic_fixture() -> dict[str, object]:
    try:
        cases = load_semantic_holdout_cases()
        shapes = Counter(str(case.sample.scenario_tags[0]) for case in cases)
        expected_shapes = {
            "narrative_only": 3,
            "table_only": 3,
            "mixed_narrative_table": 2,
        }
        errors: list[str] = []
        if len(cases) != 8:
            errors.append(f"case_count:{len(cases)}")
        if dict(shapes) != expected_shapes:
            errors.append(f"input_shapes:{dict(shapes)}")
        if len({case.task_id for case in cases}) != len(cases):
            errors.append("duplicate_task_ids")
        return {
            "status": "passed" if not errors else "failed",
            "case_count": len(cases),
            "input_shapes": dict(shapes),
            "errors": errors,
            "formal_task_selection": "not_frozen",
            "formal_required_executions": 6,
        }
    except Exception as exc:  # preserve an actionable readiness artifact
        return {
            "status": "failed",
            "case_count": 0,
            "input_shapes": {},
            "errors": [f"{type(exc).__name__}:{exc}"],
            "formal_task_selection": "not_frozen",
            "formal_required_executions": 6,
        }


def _audit_legacy_pilot_registry() -> dict[str, object]:
    """Validate the old bounded pilot without treating it as contest Stage 2."""

    try:
        registry = stage2_pilot._select_samples()
        family_counts: Counter[str] = Counter(
            family_key.split("::", 1)[0] for family_key, _minimal, _fixed in registry
        )
        projection_errors: list[str] = []
        for family_key, minimal, fixed in registry:
            minimal_case, minimal_sources = stage2_pilot._stage2_public_case(minimal)
            fixed_case, fixed_sources = stage2_pilot._stage2_public_case(fixed)
            if minimal_sources != fixed_sources:
                projection_errors.append(f"source_closure:{family_key}")
            if minimal_case != fixed_case:
                projection_errors.append(f"case_projection:{family_key}")
            projection_errors.extend(
                f"{family_key}:{error}"
                for error in validate_public_case(minimal_case)
            )
        return {
            "status": "passed" if not projection_errors else "failed",
            "registry_case_count": len(registry),
            "family_counts": dict(sorted(family_counts.items())),
            "lane_ids": list(LANES),
            "projection_error_count": len(projection_errors),
            "projection_errors": projection_errors[:20],
            "claim_scope": "legacy_bounded_stage2_pilot_contract_only",
            "contest_stage2_equivalent": False,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "registry_case_count": 0,
            "family_counts": {},
            "lane_ids": list(LANES),
            "projection_error_count": 1,
            "projection_errors": [f"{type(exc).__name__}:{exc}"],
            "claim_scope": "legacy_bounded_stage2_pilot_contract_only",
            "contest_stage2_equivalent": False,
        }


def run_stage2_readiness(
    *,
    output_root: Path,
    memory_rounds_per_family: int = 3,
) -> dict[str, object]:
    """Run no-model readiness checks and persist a truthful Stage 2 report."""

    if memory_rounds_per_family < 1:
        raise ValueError("memory_rounds_per_family_must_be_positive")
    _prepare_output_root(output_root)

    memory_root = output_root / "memory-contract"
    try:
        memory_result = run_memory_ablation(
            output_root=memory_root,
            rounds_per_family=memory_rounds_per_family,
        )
        memory_check = {
            "status": "passed" if memory_result.get("ok") else "failed",
            "result": memory_result,
            "claim_scope": "deterministic_runtime_contract_only",
            "formal_live_equivalent": False,
        }
    except Exception as exc:
        memory_check = {
            "status": "failed",
            "result": {},
            "errors": [f"{type(exc).__name__}:{exc}"],
            "claim_scope": "deterministic_runtime_contract_only",
            "formal_live_equivalent": False,
        }

    semantic_check = _audit_semantic_fixture()
    pilot_check = _audit_legacy_pilot_registry()
    checks = {
        "deterministic_memory_contract": memory_check["status"] == "passed",
        "semantic_fixture_contract": semantic_check["status"] == "passed",
        "legacy_pilot_registry_contract": pilot_check["status"] == "passed",
    }
    summary: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "ok": all(checks.values()),
        "formal_stage2_ready": False,
        "run_mode": "offline_readiness_smoke",
        "model_started": False,
        "llm_requests_started": False,
        "checks": checks,
        "components": {
            "memory": {
                "status": "deterministic_only",
                "formal_required_executions": 12,
                "formal_runner": "contest_stage2 --mechanism memory",
                "formal_campaign_executed": False,
                "deterministic_is_substitute": False,
                "smoke": memory_check,
            },
            "semantic_state": {
                "status": "implemented_not_run",
                "formal_required_executions": 6,
                "live_runner": "live_runner --suite semantic-state-ablation",
                "smoke": semantic_check,
            },
            "structured_communication": {
                "status": "carrier_only",
                "formal_required_executions": 4,
                "task_level_runner": "missing",
                "available_diagnostic": "live_runner --suite carrier-compare",
                "carrier_is_task_level_substitute": False,
            },
            "codeact_off": {
                "status": "not_applicable",
                "blocking": False,
                "reason": "no_validated_legal_common_route",
            },
            "legacy_stage2_pilot": pilot_check,
        },
        "blocking_reasons": [
            "formal_memory_campaign_not_executed_by_readiness",
            "structured_task_level_runner_missing",
            "live_state_campaign_not_executed_by_readiness",
            "live_cross_agent_caller_not_closed",
        ],
        "claim_scope": "offline_readiness_only_no_formal_stage2_result",
    }
    _write_json(output_root / "stage2-readiness.json", summary)
    return {**summary, "output_root": str(output_root)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run no-model readiness checks for contest Stage 2."
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--memory-rounds-per-family", type=int, default=3)
    args = parser.parse_args()
    summary = run_stage2_readiness(
        output_root=args.output_root,
        memory_rounds_per_family=args.memory_rounds_per_family,
    )
    print(stable_json_dumps(summary))
    if not summary["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
