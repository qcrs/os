from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent

TARGETED_TESTS = (
    "tests/test_smoke.py::test_s2_prior_dependency_changes_admissible_action_boundary",
    "tests/test_smoke.py::test_s2_negative_controls_do_not_upgrade_without_valid_prior",
    "tests/test_smoke.py::test_s2_replay_negative_controls_require_prior_contract_and_replay_artifact",
    "tests/test_smoke.py::test_text_whole_lane_executor_helper_disabled_does_not_recover_route_or_tool",
    "tests/test_smoke.py::test_text_helper_ablation_audit_pack_is_audit_only_and_keeps_helper_flag_single_variable",
    "tests/test_smoke.py::test_route_corpus_stress_audit_pack_is_audit_only_and_pair_matched",
    "tests/test_smoke.py::test_planner_support_v3_runs_llm_planner_in_protocol_mode",
    "tests/test_smoke.py::test_planner_support_v3_report_uses_row_level_one_shot_rate",
    "tests/test_smoke.py::test_pure_text_open_baseline_v1_runs_one_external_arm_and_writes_outputs",
    "tests/test_smoke.py::test_pure_text_open_baseline_v1_selects_text_rows_across_small_mixed_complexity_slice",
    "tests/test_smoke.py::test_pure_text_open_baseline_v1_rejects_too_narrow_task_surface",
    "tests/test_smoke.py::test_external_text_open_ignores_expected_metadata_oracle_fields",
    "tests/test_smoke.py::test_external_text_open_native_reuse_requires_same_retrieved_doc_set",
    "tests/test_smoke.py::test_external_text_open_message_log_stays_text_only_and_without_markers",
    "tests/test_smoke.py::test_external_text_open_source_stays_outside_statebus_runtime_and_structured_packets",
    "tests/test_smoke.py::test_langgraph_native_text_open_smoke_is_independent_from_statebus_replay_contract",
    "tests/test_llm_runtime.py::test_planner_agent_retries_until_planner_contract_is_valid",
    "tests/test_llm_runtime.py::test_plan_parser_rejects_unsupported_memory_reuse_action",
)

DET_BENCHMARKS: tuple[dict[str, Any], ...] = (
    {
        "label": "audit_b_text_helper_ablation_det_r1",
        "kind": "runner",
        "task_set": "text_helper_ablation_audit_v1",
        "repeat": 1,
        "modes": "text,protocol",
        "llm_mode": "deterministic",
        "embedding_mode": "deterministic",
    },
    {
        "label": "audit_d_route_corpus_stress_det_r1",
        "kind": "runner",
        "task_set": "route_corpus_stress_audit_v1",
        "repeat": 1,
        "modes": "text,protocol",
        "llm_mode": "deterministic",
        "embedding_mode": "deterministic",
    },
    {
        "label": "audit_e_planner_support_det_r1",
        "kind": "runner",
        "task_set": "planner_support_v3",
        "repeat": 1,
        "modes": "protocol",
        "llm_mode": "deterministic",
        "embedding_mode": "deterministic",
    },
    {
        "label": "audit_c_pure_text_open_det_r1",
        "kind": "open_runner",
        "pack": "pure_text_open_baseline_v1",
        "task_set": "contest_dual_mode_controlled_v3",
        "repeat": 1,
    },
    {
        "label": "audit_f_langgraph_native_open_det_r1",
        "kind": "open_runner",
        "pack": "langgraph_native_text_open",
        "repeat": 1,
    },
)

API_BENCHMARKS: tuple[dict[str, Any], ...] = (
    {
        "label": "audit_b_text_helper_ablation_api_r1",
        "kind": "runner",
        "task_set": "text_helper_ablation_audit_v1",
        "repeat": 1,
        "modes": "text,protocol",
        "llm_mode": "api",
        "embedding_mode": "deterministic",
    },
    {
        "label": "audit_c_pure_text_open_api_r1",
        "kind": "open_runner",
        "pack": "pure_text_open_baseline_v1",
        "task_set": "contest_dual_mode_controlled_v3",
        "repeat": 1,
    },
    {
        "label": "audit_d_route_corpus_stress_api_r1",
        "kind": "runner",
        "task_set": "route_corpus_stress_audit_v1",
        "repeat": 1,
        "modes": "text,protocol",
        "llm_mode": "api",
        "embedding_mode": "deterministic",
    },
    {
        "label": "audit_e_planner_support_api_r1",
        "kind": "runner",
        "task_set": "planner_support_v3",
        "repeat": 1,
        "modes": "protocol",
        "llm_mode": "api",
        "embedding_mode": None,
    },
    {
        "label": "audit_f_langgraph_native_open_api_r1",
        "kind": "open_runner",
        "pack": "langgraph_native_text_open",
        "repeat": 1,
    },
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Batch 2 audit full suite: regression gates, A-F targeted tests, "
            "deterministic audit artifacts, and API repeat=1 on the audit surfaces that are worth probing."
        )
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory. Default: runs/batch2_audit_full_suite_<timestamp>",
    )
    parser.add_argument("--skip-full-pytest", action="store_true")
    parser.add_argument("--skip-runtime-smoke", action="store_true")
    parser.add_argument("--skip-targeted-tests", action="store_true")
    parser.add_argument("--skip-deterministic", action="store_true")
    parser.add_argument("--skip-api", action="store_true")
    parser.add_argument("--llm-config", default="deploy/statebus_llm.yaml.local")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    out_dir = args.out or _default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "logs").mkdir(parents=True, exist_ok=True)

    commands: list[list[str]] = []
    checks: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []

    gate_specs: list[tuple[str, list[str]]] = [
        (
            "py_compile",
            [
                sys.executable,
                "-m",
                "py_compile",
                "eval/runner.py",
                "eval/open_runner.py",
                "tests/test_smoke.py",
                "tests/test_llm_runtime.py",
                "scripts/run_batch2_audit_full_suite.py",
            ],
        )
    ]
    if not args.skip_full_pytest:
        gate_specs.append(("full_pytest", [sys.executable, "-m", "pytest", "-q"]))
    if not args.skip_runtime_smoke:
        gate_specs.append(("runtime_smoke", [sys.executable, "-m", "runtime.smoke"]))
    if not args.skip_targeted_tests:
        gate_specs.append(("targeted_audit_pytest", [sys.executable, "-m", "pytest", "-q", *TARGETED_TESTS]))

    for label, command in gate_specs:
        commands.append(command)
        checks.append(_run_labeled(label=label, command=command, out_dir=out_dir))

    if not args.skip_deterministic:
        for spec in DET_BENCHMARKS:
            command = _benchmark_command(spec=spec, args=args, out_dir=out_dir / "deterministic" / spec["label"])
            commands.append(command)
            checks.append(_run_labeled(label=spec["label"], command=command, out_dir=out_dir))
            summaries.append(_summarize_surface(label=spec["label"], spec=spec, surface_out=out_dir / "deterministic" / spec["label"]))

    if not args.skip_api:
        for spec in API_BENCHMARKS:
            command = _benchmark_command(spec=spec, args=args, out_dir=out_dir / "api_repeat1" / spec["label"])
            commands.append(command)
            checks.append(_run_labeled(label=spec["label"], command=command, out_dir=out_dir))
            summaries.append(_summarize_surface(label=spec["label"], spec=spec, surface_out=out_dir / "api_repeat1" / spec["label"]))

    (out_dir / "COMMANDS.md").write_text(_commands_md(commands), encoding="utf-8")
    (out_dir / "SUMMARY.md").write_text(
        _summary_md(args=args, out_dir=out_dir, checks=checks, summaries=summaries),
        encoding="utf-8",
    )


def _default_out_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return REPO_ROOT / "runs" / f"batch2_audit_full_suite_{stamp}"


def _benchmark_command(*, spec: dict[str, Any], args: argparse.Namespace, out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if spec["kind"] == "runner":
        command = [
            sys.executable,
            "-m",
            "eval.runner",
            "--task-set",
            str(spec["task_set"]),
            "--repeat",
            str(spec["repeat"]),
            "--modes",
            str(spec["modes"]),
            "--llm-mode",
            str(spec["llm_mode"]),
            "--out",
            str(out_dir),
            "--quiet-progress",
        ]
        embedding_mode = spec.get("embedding_mode")
        if embedding_mode:
            command.extend(["--embedding-mode", str(embedding_mode)])
        if spec["llm_mode"] == "api":
            command.extend(["--llm-config", args.llm_config])
        return command

    if spec["kind"] == "open_runner":
        command = [
            sys.executable,
            "-m",
            "eval.open_runner",
            "--pack",
            str(spec["pack"]),
            "--repeat",
            str(spec["repeat"]),
            "--out",
            str(out_dir),
        ]
        task_set = spec.get("task_set")
        if task_set:
            command.extend(["--task-set", str(task_set)])
        return command

    raise SystemExit(f"unsupported benchmark kind: {spec['kind']}")


def _run_labeled(*, label: str, command: list[str], out_dir: Path) -> dict[str, Any]:
    log_path = out_dir / "logs" / f"{label}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[run_batch2_audit_full_suite] start {label}", flush=True)
    print(f"[run_batch2_audit_full_suite] cmd   {shlex.join(command)}", flush=True)
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise SystemExit(f"{label} failed with exit code {completed.returncode}; see {log_path}")
    return {
        "label": label,
        "command": shlex.join(command),
        "returncode": completed.returncode,
        "log_path": str(log_path.relative_to(out_dir)),
    }


def _summarize_surface(*, label: str, spec: dict[str, Any], surface_out: Path) -> dict[str, Any]:
    if spec["kind"] == "runner":
        result = json.loads((surface_out / "benchmark_results.json").read_text(encoding="utf-8"))
        manifest = result["manifest"]
        summary = result["summary"]
        modes = tuple(str(mode) for mode in manifest.get("modes", []))
        failure_counts = {
            mode: int(summary.get(mode, {}).get("failure_count", 0))
            for mode in modes
            if mode in summary
        }
        return {
            "label": label,
            "kind": "runner",
            "surface": str(manifest.get("task_pack_type", spec["task_set"])),
            "repeat": int(manifest.get("repeat", 0)),
            "llm_mode": str(manifest.get("llm_mode", spec["llm_mode"])),
            "public_surface": str(manifest.get("task_set_public_surface", "")),
            "failure_counts": failure_counts,
            "report": str((surface_out / "benchmark_report.md").relative_to(surface_out.parent.parent.parent)),
        }

    result = json.loads((surface_out / "open_results.json").read_text(encoding="utf-8"))
    manifest = result.get("manifest", {})
    return {
        "label": label,
        "kind": "open_runner",
        "surface": str(manifest.get("task_pack", spec["pack"])),
        "repeat": int(manifest.get("repeat", 0)),
        "llm_mode": "n/a",
        "public_surface": str(manifest.get("public_surface", "")),
        "failure_counts": {},
        "report": str((surface_out / "open_report.md").relative_to(surface_out.parent.parent.parent)),
    }


def _commands_md(commands: list[list[str]]) -> str:
    lines = ["# Commands", ""]
    for command in commands:
        lines.extend(["```bash", shlex.join(command), "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def _summary_md(
    *,
    args: argparse.Namespace,
    out_dir: Path,
    checks: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
) -> str:
    lines = [
        "# Batch 2 Audit Full Suite Summary",
        "",
        "## Scope",
        "",
        "- Regression gates: `py_compile`, full `pytest -q`, `runtime.smoke`.",
        "- Targeted audit tests: A-F focused `pytest` coverage.",
        "- Deterministic artifacts: Batch 2 audit surfaces that need runner/open-runner outputs.",
        "- API repeat=1: only the audit surfaces worth probing under live API.",
        "- Frozen headline rule: this suite must not mutate or requalify `contest_honest_headline_v1`.",
        "",
        "## Flags",
        "",
        f"- skip_full_pytest = `{args.skip_full_pytest}`",
        f"- skip_runtime_smoke = `{args.skip_runtime_smoke}`",
        f"- skip_targeted_tests = `{args.skip_targeted_tests}`",
        f"- skip_deterministic = `{args.skip_deterministic}`",
        f"- skip_api = `{args.skip_api}`",
        "",
        "## Checks",
        "",
        "| step | returncode | log |",
        "| --- | ---: | --- |",
    ]
    for check in checks:
        lines.append(f"| {check['label']} | {check['returncode']} | `{check['log_path']}` |")
    lines.extend(["", "## Surfaces", "", "| label | kind | surface | repeat | llm_mode | public_surface | failures | report |", "| --- | --- | --- | ---: | --- | --- | --- | --- |"])
    for summary in summaries:
        lines.append(
            f"| {summary['label']} | {summary['kind']} | {summary['surface']} | {summary['repeat']} | "
            f"{summary['llm_mode']} | {summary['public_surface']} | `{summary['failure_counts']}` | `{summary['report']}` |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Audit A stays targeted-test only: the current object is negative-control boundary verification, not a separate API runner pack.",
            "- Audit B/D/E are the current API repeat=1 runner surfaces in this suite.",
            "- Audit C/F stay in the suite, but their current `open_runner` surfaces are not live-API LLM paths; they remain lexical/native audit surfaces.",
            f"- Package root: `{out_dir}`",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
