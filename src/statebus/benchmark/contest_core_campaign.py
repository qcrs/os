"""Prepare contest-core manifests and safe-to-copy campaign commands.

This module is intentionally a planner.  It never starts vLLM, Docker, a
container, or a formal campaign.  The generated manifest preserves the seed,
case/family selection, lane order, feature flags, command roots, and expected
exit codes so a user can run the next stage in a fresh output directory.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shlex
from typing import Iterable

from statebus.utils import stable_json_dumps


LANES = (
    "direct_single_agent",
    "pure_text_mas",
    "fixed_structured",
    "adaptive_routed",
)
P11_FEATURE_VARIANTS = (
    "full",
    "without_semantic_state",
    "without_memory",
    "without_adaptive_routing",
    "without_codeact",
    "memory_off_semantic_state_off",
    "memory_off_semantic_state_on",
    "memory_on_semantic_state_off",
    "memory_on_semantic_state_on",
)
DEFAULT_CASE_IDS = ("benchmark-sample-1",)
# The default live P1 scope is the largest currently closed independent slice.
# Additional registry families remain opt-in until their baseline contracts are
# repaired; the planner never turns a stopped family into a success row.
DEFAULT_STAGE2_FAMILIES = (
    "financial_report_analysis_v1",
    "multi_period_trend_analysis_v1",
)
DEFAULT_FAMILIES = ("cross_period_financial", "incident_diagnosis")
# Stage 2 uses the formal C2B registry family ids below.  These are separate
# from the historical P4 continuous-family ids in ``DEFAULT_FAMILIES``.
STAGE2_FAMILY_IDS = (
    "financial_report_analysis_v1",
    "multi_period_trend_analysis_v1",
    "cross_table_join_analysis_v1",
    "conditional_aggregation_v1",
    "anomaly_detection_v1",
)
STAGE2_FAMILY_CASE_COUNTS = {
    "financial_report_analysis_v1": 12,
    "multi_period_trend_analysis_v1": 10,
    "cross_table_join_analysis_v1": 10,
    "conditional_aggregation_v1": 8,
    "anomaly_detection_v1": 8,
}
SEMANTIC_HOLDOUT_CASE_IDS = (
    "semantic-holdout-s1",
    "semantic-holdout-s2",
    "semantic-holdout-s3",
    "semantic-holdout-s4",
    "semantic-holdout-s5",
    "semantic-holdout-s6",
    "semantic-holdout-s7",
    "semantic-holdout-s8",
)
BOUNDED_SEMANTIC_HOLDOUT_CASE_IDS = (
    "semantic-holdout-s1",
    "semantic-holdout-s3",
)
DEFAULT_PROFILE = "qwen3-32b-gpu2-u050"
DEFAULT_CONTAINER_NAME = "statebus-runtime"
DEFAULT_EMBEDDING_PHYSICAL_GPU = 1
DEFAULT_STAGE2_REPEATS = 1
# Stage 2 runs the four provider roles sequentially.  The live provider
# profile allows 180 seconds per request plus Runtime settlement time, so the
# generated campaign command must leave room for the full bounded workflow.
DEFAULT_STAGE2_TIMEOUT_S = 900
SCHEMA_VERSION = "statebus.contest_core_campaign_manifest.v1"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")


def _prepare_output_root(output_root: Path) -> Path:
    root = output_root.expanduser().resolve()
    if root.exists():
        if not root.is_dir() or any(root.iterdir()):
            raise FileExistsError(f"contest_core_output_root_must_be_new_or_empty:{root}")
    else:
        root.mkdir(parents=True, exist_ok=False)
    return root


def _lane_order(seed: int, case_id: str) -> list[str]:
    return sorted(
        LANES,
        key=lambda lane: hashlib.sha256(
            f"{seed}:{case_id}:{lane}".encode("utf-8")
        ).hexdigest(),
    )


def _feature_flags(variant: str) -> dict[str, bool]:
    if variant not in P11_FEATURE_VARIANTS:
        raise ValueError(f"unknown_p11_feature_variant:{variant}")
    flags = {
        "semantic_state": True,
        "memory": True,
        "adaptive_routing": True,
        "codeact": True,
        "cross_text_semantic_state": False,
        "engine_local_kv": False,
        "hidden_latent": False,
        "apc_prefix": False,
    }
    if variant == "without_semantic_state":
        flags["semantic_state"] = False
    elif variant == "without_memory":
        flags["memory"] = False
    elif variant == "without_adaptive_routing":
        flags["adaptive_routing"] = False
    elif variant == "without_codeact":
        flags["codeact"] = False
    elif variant == "memory_off_semantic_state_off":
        flags.update(memory=False, semantic_state=False)
    elif variant == "memory_off_semantic_state_on":
        flags.update(memory=False, semantic_state=True)
    elif variant == "memory_on_semantic_state_off":
        flags.update(memory=True, semantic_state=False)
    elif variant == "memory_on_semantic_state_on":
        flags.update(memory=True, semantic_state=True)
    return flags


def _command(*parts: str) -> str:
    return shlex.join(tuple(str(part) for part in parts))


def _python_parts() -> tuple[str, ...]:
    return ("PYTHONDONTWRITEBYTECODE=1", "PYTHONPATH=src", "python")


def _profile_bootstrap(profile: str, *, root: Path) -> str:
    """Return the live profile bootstrap used by ``commands.sh``.

    ``start_statebus.sh`` normally exports into its own process.  A generated
    campaign must import those exact exports into the shell that runs P1/P3/
    P4-live/P5-live, otherwise Stage 2 correctly sees an unconfigured profile.
    The second invocation performs the service/container reuse and verification.
    """

    quoted_profile = shlex.quote(profile)
    preflight_root = shlex.quote(str(root / "preflight"))
    return "\n".join(
        (
            "# Import the selected profile into this shell, then reuse/verify the live chain.",
            f'eval "$(scripts/start_statebus.sh {quoted_profile} '
            f'--container-name {DEFAULT_CONTAINER_NAME} '
            f'--embedding-gpu {DEFAULT_EMBEDDING_PHYSICAL_GPU} --print-env)"',
            f"export STATEBUS_HOST_RUNS_ROOT={preflight_root}",
            "export STATEBUS_LOCAL_VLLM_CHECK_RUN_ID=local-vllm-container-check",
            f'scripts/start_statebus.sh {quoted_profile} '
            f'--container-name {DEFAULT_CONTAINER_NAME} '
            f'--embedding-gpu {DEFAULT_EMBEDDING_PHYSICAL_GPU}',
            "scripts/run_g6b2_os_container.sh verify",
            "scripts/run_g6b2_os_container.sh smoke",
            "scripts/run_local_vllm_container_check.sh",
        )
    )


def _stage_commands(
    *,
    root: Path,
    seed: int,
    profile: str,
    case_ids: tuple[str, ...],
    families: tuple[str, ...],
    stage2_family_ids: tuple[str, ...],
    max_cases_per_family: int,
    full_registry: bool,
    dry_run: bool,
    skip_live: bool,
) -> dict[str, dict[str, object]]:
    if case_ids and stage2_family_ids:
        raise ValueError("contest_core_p1_case_and_family_selection_are_mutually_exclusive")
    if not case_ids and not stage2_family_ids:
        raise ValueError("contest_core_p1_selection_required")
    python = _python_parts()
    p1_root = root / "p1"
    selection_args = " ".join(
        _command(option, value)
        for option, values in (("--case-id", case_ids), ("--family-id", stage2_family_ids))
        for value in values
    )
    if dry_run:
        p1_command = _command(
            *python,
            "-m",
            "statebus.benchmark.stage2_pilot",
            "--output-root",
            str(p1_root),
            "--repeats",
            str(DEFAULT_STAGE2_REPEATS),
            "--max-cases-per-family",
            str(max_cases_per_family),
            "--timeout-s",
            str(DEFAULT_STAGE2_TIMEOUT_S),
            *(item for option, values in (("--case-id", case_ids), ("--family-id", stage2_family_ids)) for value in values for item in (option, value)),
            "--dry-run",
        )
    else:
        p1_command = "\n".join(
            (
                f"HOST_P1_ROOT={shlex.quote(str(p1_root))}",
                'mkdir -p "$HOST_P1_ROOT"',
                'CONTAINER_P1_ROOT="$(scripts/run_g6b2_os_container.sh map-path "$HOST_P1_ROOT")"',
                "scripts/run_g6b2_os_container.sh exec python3 -m "
                "statebus.benchmark.stage2_pilot "
                "--output-root \"$CONTAINER_P1_ROOT\" "
                "--embedding-device cuda:0 "
                f"--timeout-s {DEFAULT_STAGE2_TIMEOUT_S} "
                f"--repeats {DEFAULT_STAGE2_REPEATS} "
                f"--max-cases-per-family {max_cases_per_family} "
                + selection_args,
            )
        )
    p2 = _command(
        *python,
        "-m",
        "statebus.benchmark.low_overhead_ablation",
        "--output-root",
        str(root / "p2"),
        "--threshold-sweep",
        "--threshold-bytes",
        "256",
        "--threshold-bytes",
        "4096",
        "--threshold-bytes",
        "16384",
        "--payload-count-per-size",
        "1",
        "--repeats",
        "1",
    )
    p3_root = root / "p3"
    p3_case_ids = (
        SEMANTIC_HOLDOUT_CASE_IDS
        if full_registry
        else BOUNDED_SEMANTIC_HOLDOUT_CASE_IDS
    )
    p3_case_args = " ".join(
        f"--case-id {shlex.quote(case_id)}" for case_id in p3_case_ids
    )
    p3 = "\n".join(
        (
            f"HOST_P3_ROOT={shlex.quote(str(p3_root))}",
            'mkdir -p "$HOST_P3_ROOT"',
            'CONTAINER_P3_ROOT="$(scripts/run_g6b2_os_container.sh map-path \"$HOST_P3_ROOT\")"',
            "scripts/run_g6b2_os_container.sh exec python3 -m "
            "statebus.benchmark.live_runner --suite semantic-state-ablation "
            "--role-path-mode local_vllm --embedding-mode local "
            "--state-pool-mode shared_memory --transport subprocess "
            "--runtime-root \"$CONTAINER_P3_ROOT/runtime\" "
            "--workspace-root \"$CONTAINER_P3_ROOT/workspaces\" "
            + p3_case_args,
        )
    )
    p4 = _command(
        *python,
        "-m",
        "statebus.benchmark.memory_ablation",
        "--output-root",
        str(root / "p4"),
        "--rounds-per-family",
        "3",
    )
    p4_live = _command(
        "STATEBUS_LOCAL_VLLM_MODEL=qwen3-32b",
        "scripts/run_g6b2_real_embedding.sh",
        "minimal",
        "--service-runtime-dir",
        "/home/qcrs/statebus/work/vllm-qwen3-32b-gpu2-u050",
        "--output-base",
        str(root / "p4-live"),
        "--max-duration-s",
        "600",
    )
    p5 = _command(
        *python,
        "-m",
        "pytest",
        "-q",
        "tests/test_execution_routing.py",
        "tests/test_adaptive_codeact_integration.py",
        "tests/test_transform_dsl.py",
    )
    p5_live_root = root / "p5-live"
    p5_live = "\n".join(
        (
            f"HOST_P5_ROOT={shlex.quote(str(p5_live_root))}",
            'mkdir -p "$HOST_P5_ROOT"',
            'CONTAINER_P5_ROOT="$(scripts/run_g6b2_os_container.sh map-path \"$HOST_P5_ROOT\")"',
            "scripts/run_g6b2_os_container.sh exec python3 "
            "scripts/diagnostics/check_codeact_bwrap_sandbox.py",
            "scripts/run_g6b2_os_container.sh exec python3 "
            "scripts/diagnostics/run_llm_codeact_smoke.py "
            "--output-root \"$CONTAINER_P5_ROOT\" --task comparison "
            "--embedding-model-path /statebus/models/Qwen3-Embedding-0.6B "
            "--embedding-device cuda:0",
        )
    )
    p0 = _command(
        *python,
        "-m",
        "pytest",
        "-q",
        "tests/test_mrr_06a_attempt_lifecycle.py",
        "tests/test_mrr_06b_late_result_fencing.py",
        "tests/test_mrr_07a_state_access_authority.py",
        "tests/test_mrr_07b_state_lifetime.py",
        "tests/test_mrr_08_artifact_truth.py",
        "tests/test_execution_routing.py",
    )
    p11 = _command(
        *python,
        "-m",
        "statebus.benchmark.contest_core_integrated_gate",
        "--campaign-root",
        str(root),
        "--output-root",
        str(root / "p11"),
        "--feature-variant",
        "full",
    )
    commands: dict[str, dict[str, object]] = {
        "P0": {"command": p0, "enabled": True, "expected_exit_code": 0},
        "P1": {
            "command": p1_command,
            "enabled": True,
            "expected_exit_code": 3 if dry_run else 0,
        },
        "P2": {"command": p2, "enabled": True, "expected_exit_code": 0},
        "P3": {"command": p3, "enabled": not skip_live, "expected_exit_code": 0},
        "P4": {"command": p4, "enabled": True, "expected_exit_code": 0},
        "P4_live": {"command": p4_live, "enabled": not skip_live, "expected_exit_code": 0},
        "P5": {"command": p5, "enabled": True, "expected_exit_code": 0},
        "P5_live": {"command": p5_live, "enabled": not skip_live, "expected_exit_code": 0},
        "P11": {"command": p11, "enabled": not skip_live, "expected_exit_code": 0},
    }
    return commands


def build_campaign_manifest(
    *,
    output_root: Path,
    seed: int = 20260920,
    profile: str = DEFAULT_PROFILE,
    case_ids: Iterable[str] = (),
    families: Iterable[str] = DEFAULT_FAMILIES,
    stage2_family_ids: Iterable[str] = (),
    dry_run: bool = True,
    skip_live: bool = True,
    feature_variant: str = "full",
    full_registry: bool = False,
) -> dict[str, object]:
    root = _prepare_output_root(Path(output_root))
    normalized_cases = tuple(dict.fromkeys(str(item) for item in case_ids if str(item).strip()))
    normalized_families = tuple(dict.fromkeys(str(item) for item in families if str(item).strip()))
    normalized_stage2_families = tuple(
        dict.fromkeys(str(item) for item in stage2_family_ids if str(item).strip())
    )
    if not normalized_cases and not normalized_stage2_families:
        normalized_stage2_families = (
            STAGE2_FAMILY_IDS if full_registry else DEFAULT_STAGE2_FAMILIES
        )
    unknown_stage2_families = tuple(
        item for item in normalized_stage2_families if item not in STAGE2_FAMILY_IDS
    )
    if unknown_stage2_families:
        raise ValueError(
            "contest_core_unknown_stage2_family:" + ",".join(unknown_stage2_families)
        )
    if bool(normalized_cases) == bool(normalized_stage2_families) or not normalized_families:
        raise ValueError("contest_core_p1_selection_and_families_required")
    if full_registry and (
        normalized_cases
        or normalized_stage2_families != STAGE2_FAMILY_IDS
    ):
        raise ValueError("contest_core_full_registry_requires_all_stage2_families")
    max_cases_per_family = 0 if full_registry else 1
    independent_case_count = (
        len(normalized_cases)
        if normalized_cases
        else sum(
            STAGE2_FAMILY_CASE_COUNTS[family_id]
            if full_registry
            else min(1, STAGE2_FAMILY_CASE_COUNTS[family_id])
            for family_id in normalized_stage2_families
        )
    )
    p1_planned_rows = (
        independent_case_count * len(LANES) * DEFAULT_STAGE2_REPEATS
    )
    flags = _feature_flags(feature_variant)
    lane_keys = normalized_cases or normalized_stage2_families
    lane_orders = {
        key: _lane_order(seed, key) for key in lane_keys
    }
    commands = _stage_commands(
        root=root,
        seed=seed,
        profile=profile,
        case_ids=normalized_cases,
        families=normalized_families,
        stage2_family_ids=normalized_stage2_families,
        max_cases_per_family=max_cases_per_family,
        full_registry=full_registry,
        dry_run=dry_run,
        skip_live=skip_live,
    )
    p11_matrix = [
        {
            "variant": variant,
            "feature_flags": _feature_flags(variant),
            "execution_status": (
                "full_chain_command_ready" if variant == "full" else "variant_runner_not_implemented"
            ),
            "command": str(commands["P11"]["command"]) if variant == "full" else "",
            "expected_exit_code": 0 if variant == "full" else None,
        }
        for variant in P11_FEATURE_VARIANTS
    ]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "planned",
        "generation_mode": "dry_run" if dry_run else "command_only",
        "formal_campaign_executed": False,
        "benchmark_superiority": "NOT_ESTABLISHED",
        "statistical_superiority": "NOT_ESTABLISHED",
        "output_root": str(root),
        "seed": seed,
        "profile": profile,
        "cases": list(normalized_cases),
        "families": list(normalized_families),
        "stage2_families": list(normalized_stage2_families),
        "p1_selection": {
            "mode": "case" if normalized_cases else "family",
            "scope": "full_registry" if full_registry else "bounded_pilot",
            "case_ids": list(normalized_cases),
            "family_ids": list(normalized_stage2_families),
            "family_case_counts": {
                family_id: STAGE2_FAMILY_CASE_COUNTS[family_id]
                for family_id in normalized_stage2_families
            },
            "max_cases_per_family": max_cases_per_family,
            "independent_case_count": independent_case_count,
            "repeat_count": DEFAULT_STAGE2_REPEATS,
            "timeout_s": DEFAULT_STAGE2_TIMEOUT_S,
            "lane_count": len(LANES),
            "planned_rows": p1_planned_rows,
            "denominator_fields": [
                "planned",
                "started",
                "settled",
                "observed",
                "success",
                "failed",
            ],
        },
        "lane_order": lane_orders,
        "lanes": list(LANES),
        "feature_variant": feature_variant,
        "feature_flags": flags,
        "live_commands_enabled": not skip_live,
        "expected_exit_codes": {name: int(item["expected_exit_code"]) for name, item in commands.items()},
        "claim_boundary": "manifest and command preparation only; no formal result or superiority claim",
        "stages": commands,
        "profile_bootstrap": {
            "enabled": not skip_live,
            "command": _profile_bootstrap(profile, root=root) if not skip_live else "",
        },
        "stage_scopes": {
            "P1": {
                "cases": independent_case_count,
                "lanes": len(LANES),
                "repeats": DEFAULT_STAGE2_REPEATS,
                "planned_rows": p1_planned_rows,
                "timeout_s_per_slot": DEFAULT_STAGE2_TIMEOUT_S,
            },
            "P2": {
                "threshold_bytes": [256, 4096, 16384],
                "payload_count_per_size": 1,
                "repeats": 1,
            },
            "P3": {
                "scope": "formal_full" if full_registry else "bounded_diagnostic",
                "available_case_count": len(SEMANTIC_HOLDOUT_CASE_IDS),
                "case_ids": list(
                    SEMANTIC_HOLDOUT_CASE_IDS
                    if full_registry
                    else BOUNDED_SEMANTIC_HOLDOUT_CASE_IDS
                ),
                "active_denominator_policy": "inactive_excluded",
            },
            "P4": {
                "families": list(normalized_families),
                "rounds_per_family": 3,
                "accounting_mode": "deterministic",
            },
            "P4_live": {
                "mode": "minimal",
                "matched_pairs": 1,
                "max_duration_s": 600,
                "embedding_physical_gpu": DEFAULT_EMBEDDING_PHYSICAL_GPU,
                "embedding_container_device": "cuda:0",
            },
            "P5": {
                "contracts": ["dsl", "bounded_python", "codeact_off", "wrong_route"],
            },
            "P5_live": {
                "tasks": ["comparison"],
                "sandbox_backend": "bwrap",
                "sandbox_uid": 65534,
                "sandbox_gid": 65534,
                "fallback_count": 0,
            },
            "P11": {
                "feature_variant": feature_variant,
                "implemented_variants": ["full"],
            },
        },
        "p11_feature_matrix": p11_matrix,
        "negative_controls": [
            "stale_grant",
            "late_result",
            "invalid_artifact",
            "incompatible_memory",
            "recipe_hash_mismatch",
            "wrong_route",
            "codeact_policy_trap",
        ],
    }
    _write_json(root / "campaign_manifest.json", manifest)
    for stage, payload in commands.items():
        _write_json(root / f"{stage.lower()}_manifest.json", {"stage": stage, **payload})
    _write_json(root / "p11_feature_matrix.json", {"variants": p11_matrix})
    command_blocks: list[str] = []
    for stage, payload in commands.items():
        header = (
            f"# {stage} expected_exit_code={payload['expected_exit_code']} "
            f"enabled={payload['enabled']}"
        )
        command = str(payload["command"])
        if not payload["enabled"]:
            command = "\n".join(f"# {line}" for line in command.splitlines())
        command_blocks.append(f"{header}\n{command}")
    bootstrap = ""
    if not skip_live:
        bootstrap = _profile_bootstrap(profile, root=root) + "\n\n"
    preamble = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "cd /home/qcrs/statebus/os\n"
        "source ./deploy/activate_statebus_host.sh\n\n"
    )
    commands_text = preamble + bootstrap + "\n".join(command_blocks)
    (root / "commands.sh").write_text(commands_text + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate safe contest-core campaign manifests and commands."
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260920)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--family-id", action="append", default=[])
    parser.add_argument(
        "--stage2-family-id",
        action="append",
        default=[],
        choices=STAGE2_FAMILY_IDS,
        help="Select Stage 2 formal family ids instead of exact case ids; repeat for multiple families.",
    )
    parser.add_argument("--feature-variant", choices=P11_FEATURE_VARIANTS, default="full")
    parser.add_argument(
        "--full-registry",
        action="store_true",
        help="Run all 48 cases from all five Stage 2 families (192 rows at one repeat).",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-live", action="store_true")
    args = parser.parse_args()
    requested_cases = tuple(args.case_id)
    requested_stage2_families = tuple(args.stage2_family_id)
    if not requested_cases and not requested_stage2_families:
        requested_stage2_families = (
            STAGE2_FAMILY_IDS if args.full_registry else DEFAULT_STAGE2_FAMILIES
        )
    manifest = build_campaign_manifest(
        output_root=args.output_root,
        seed=args.seed,
        profile=args.profile,
        case_ids=requested_cases,
        families=tuple(args.family_id) or DEFAULT_FAMILIES,
        stage2_family_ids=requested_stage2_families,
        dry_run=args.dry_run,
        skip_live=args.skip_live,
        feature_variant=args.feature_variant,
        full_registry=args.full_registry,
    )
    print(stable_json_dumps({
        "output_root": manifest["output_root"],
        "schema_version": manifest["schema_version"],
        "formal_campaign_executed": False,
        "live_commands_enabled": manifest["live_commands_enabled"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
