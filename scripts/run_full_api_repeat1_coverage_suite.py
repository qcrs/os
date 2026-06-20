from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_suite_common import (
    REPO_ROOT,
    commands_md,
    current_git_diff_stat,
    current_git_status,
    ensure_dir,
    load_benchmark_summary,
    load_open_summary,
    run_command,
    timestamp,
    worktree_baseline_md,
)


PLANNED_BRANCH = "feat/active-surface-and-external-text-baseline-20260619"

LOCAL_GATES: tuple[tuple[str, list[str]], ...] = (
    (
        "py_compile_changed_surfaces",
        [
            sys.executable,
            "-m",
            "py_compile",
            "scripts/audit_suite_common.py",
            "scripts/run_current_branch_support_refresh.py",
            "scripts/run_active_surface_repeat1_suite.py",
            "scripts/write_frozen_headline_slices.py",
            "scripts/run_full_api_repeat1_coverage_suite.py",
            "eval/open_runner.py",
            "eval/runner.py",
            "eval/text_open_baseline.py",
            "tasks/sample_tasks.py",
            "tests/test_smoke.py",
        ],
    ),
    ("runtime_smoke", [sys.executable, "-m", "runtime.smoke"]),
    (
        "targeted_surface_pytest",
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_smoke.py::test_typed_state_consumer_sensitivity_v3_alias_expands_to_5_families_and_reports_secondary_metrics",
            "tests/test_smoke.py::test_state_ref_consumer_sensitivity_audit_changes_executor_visibility_by_kind",
            "tests/test_smoke.py::test_pure_text_open_live_api_slice_v1_selects_frozen_headline_text_rows_only",
            "tests/test_smoke.py::test_route_corpus_stress_whole_lane_audit_v1_keeps_protocol_side_and_moves_text_side_to_whole_lane",
            "tests/test_smoke.py::test_pure_text_open_live_api_slice_v1_runs_text_only_pack_and_writes_manifest_fields",
            "tests/test_smoke.py::test_pure_text_open_live_api_slice_v1_does_not_send_oracle_fields_and_keeps_text_only_logs",
        ],
    ),
)

API_SURFACE_SPECS: tuple[dict[str, object], ...] = (
    {
        "label": "contest_honest_headline_v1_api_r1",
        "kind": "runner",
        "task_set": "contest_honest_headline_v1",
        "modes": "text,protocol",
    },
    {
        "label": "memory_policy_controlled_v3_api_r1",
        "kind": "runner",
        "task_set": "memory_policy_controlled_v3",
        "modes": "protocol",
    },
    {
        "label": "typed_state_consumer_sensitivity_v3_api_r1",
        "kind": "runner",
        "task_set": "typed_state_consumer_sensitivity_v3",
        "modes": "protocol",
    },
    {
        "label": "planner_support_v3_api_r1",
        "kind": "runner",
        "task_set": "planner_support_v3",
        "modes": "protocol",
    },
    {
        "label": "text_helper_ablation_audit_v1_api_r1",
        "kind": "runner",
        "task_set": "text_helper_ablation_audit_v1",
        "modes": "text,protocol",
    },
    {
        "label": "route_corpus_stress_audit_v1_api_r1",
        "kind": "runner",
        "task_set": "route_corpus_stress_audit_v1",
        "modes": "text,protocol",
    },
    {
        "label": "route_corpus_stress_whole_lane_audit_v1_api_r1",
        "kind": "runner",
        "task_set": "route_corpus_stress_whole_lane_audit_v1",
        "modes": "text,protocol",
    },
    {
        "label": "pure_text_open_baseline_v1_api_r1",
        "kind": "open_runner",
        "pack": "pure_text_open_baseline_v1",
        "task_set": "contest_honest_headline_v1",
        "llm_mode": "api",
    },
    {
        "label": "pure_text_open_live_api_slice_v1_api_r1",
        "kind": "open_runner",
        "pack": "pure_text_open_live_api_slice_v1",
        "task_set": "pure_text_open_live_api_slice_v1",
        "llm_mode": "api",
    },
    {
        "label": "langgraph_native_text_open_api_r1",
        "kind": "open_runner",
        "pack": "langgraph_native_text_open",
        "llm_mode": "api",
        "appendix": True,
    },
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the full StateBus API repeat=1 coverage suite with local gates first, "
            "then serialized API r1 benchmark surfaces."
        )
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory. Default: runs/full_api_repeat1_coverage_suite_<timestamp>",
    )
    parser.add_argument("--llm-config", default="deploy/statebus_llm.yaml.local")
    parser.add_argument("--skip-runtime-smoke", action="store_true")
    parser.add_argument("--skip-targeted-tests", action="store_true")
    parser.add_argument("--with-full-pytest", action="store_true")
    parser.add_argument("--allow-appendix-failure", action="store_true")
    parser.add_argument(
        "--refresh-summary-only",
        type=Path,
        default=None,
        help="Rewrite SUMMARY.md and suite_manifest.json from an existing suite output without rerunning gates or benchmarks.",
    )
    return parser


def _default_out_dir() -> Path:
    return REPO_ROOT / "runs" / f"full_api_repeat1_coverage_suite_{timestamp()}"


def _build_gate_specs(args: argparse.Namespace) -> list[tuple[str, list[str]]]:
    gate_specs = [LOCAL_GATES[0]]
    if not args.skip_runtime_smoke:
        gate_specs.append(LOCAL_GATES[1])
    if not args.skip_targeted_tests:
        gate_specs.append(LOCAL_GATES[2])
    if args.with_full_pytest:
        gate_specs.append(("full_pytest", [sys.executable, "-m", "pytest", "-q"]))
    return gate_specs


def _build_benchmark_command(
    *,
    spec: dict[str, object],
    args: argparse.Namespace,
    surface_out: Path,
) -> list[str]:
    if spec["kind"] == "runner":
        return [
            sys.executable,
            "-m",
            "eval.runner",
            "--task-set",
            str(spec["task_set"]),
            "--repeat",
            "1",
            "--modes",
            str(spec["modes"]),
            "--llm-mode",
            "api",
            "--llm-config",
            args.llm_config,
            "--out",
            str(surface_out),
            "--quiet-progress",
        ]
    command = [
        sys.executable,
        "-m",
        "eval.open_runner",
        "--pack",
        str(spec["pack"]),
        "--repeat",
        "1",
        "--llm-mode",
        str(spec.get("llm_mode", "api")),
        "--llm-config",
        args.llm_config,
        "--out",
        str(surface_out),
    ]
    if spec.get("task_set"):
        command.extend(["--task-set", str(spec["task_set"])])
    return command


def _load_completed_runner_rows(surface_out: Path) -> list[dict[str, object]]:
    payload = json.loads((surface_out / "benchmark_results.json").read_text(encoding="utf-8"))
    rows: list[dict[str, object]] = []
    for mode_runs in payload.get("mode_runs", {}).values():
        for run in mode_runs:
            for task in run.get("tasks", []):
                if str(task.get("status", "")).strip() == "completed":
                    rows.append(task)
    return rows


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _extract_runner_metric(mode_summary: dict[str, object], key: str) -> float:
    direct = mode_summary.get(key)
    if isinstance(direct, (int, float)):
        return float(direct)
    case_contract = dict(dict(mode_summary.get("misfire_audit", {})).get("case_contract", {}))
    nested = case_contract.get(key)
    if isinstance(nested, (int, float)):
        return float(nested)
    return 0.0


def _summarize_surface(*, spec: dict[str, object], surface_out: Path) -> dict[str, object]:
    if spec["kind"] == "runner":
        payload = load_benchmark_summary(surface_out)
        mode_summaries = {key: dict(value) for key, value in payload["summary"].items()}
        protocol_summary = mode_summaries.get("protocol", {})
        text_summary = mode_summaries.get("text", {})
        primary_summary = protocol_summary or text_summary
        aggregate = dict(primary_summary.get("aggregate", {}))
        rows = _load_completed_runner_rows(surface_out)
        task_ms_values = [float(row.get("metrics", {}).get("task_ms", 0.0)) for row in rows]
        skipped_values = [float(row.get("metrics", {}).get("skipped_step_count", 0.0)) for row in rows]
        reuse_values = [float(row.get("metrics", {}).get("reuse_gain", 0.0)) for row in rows]
        exact_values = [
            1.0 if bool(row.get("case_contract_audit", {}).get("exact_match")) else 0.0 for row in rows
        ]
        admissible_values = [
            1.0 if bool(row.get("case_contract_audit", {}).get("admissible_match")) else 0.0 for row in rows
        ]
        exact_rate = _mean(exact_values)
        admissible_rate = _mean(admissible_values)
        if not rows:
            exact_rate = _extract_runner_metric(primary_summary, "exact_match_rate")
            admissible_rate = _extract_runner_metric(primary_summary, "admissible_match_rate")
        return {
            "label": str(spec["label"]),
            "kind": "runner",
            "task_pack": payload["task_pack_type"],
            "llm_backend": payload["llm_backend"],
            "exact_match_rate": exact_rate,
            "admissible_match_rate": admissible_rate,
            "task_ms": _mean(task_ms_values) or float(aggregate.get("task_ms", 0.0)),
            "skipped_step_count": _mean(skipped_values) or float(aggregate.get("skipped_step_count", 0.0)),
            "reuse_gain": _mean(reuse_values) or float(aggregate.get("reuse_gain", 0.0)),
            "relative_out": str(surface_out.relative_to(REPO_ROOT)),
            "appendix": bool(spec.get("appendix", False)),
        }
    payload = load_open_summary(surface_out)
    row = dict(payload["summary"][0]) if payload["summary"] else {}
    return {
        "label": str(spec["label"]),
        "kind": "open_runner",
        "task_pack": payload["task_pack"],
        "llm_backend": "api",
        "exact_match_rate": float(row.get("exact_match_rate", 0.0)),
        "admissible_match_rate": float(row.get("admissible_match_rate", 0.0)),
        "task_ms": float(row.get("task_ms", 0.0)),
        "skipped_step_count": float(row.get("skipped_step_count", 0.0)),
        "reuse_gain": float(row.get("reuse_gain", 0.0)),
        "data_source": payload.get("data_source", ""),
        "runtime_contract": payload.get("runtime_contract", ""),
        "statebus_contract_used": bool(payload.get("statebus_contract_used", False)),
        "relative_out": str(surface_out.relative_to(REPO_ROOT)),
        "appendix": bool(spec.get("appendix", False)),
    }


def _summary_md(
    *,
    gate_results: list[dict[str, object]],
    surface_results: list[dict[str, object]],
    failures: list[str],
) -> str:
    lines = [
        "# Full API Repeat1 Coverage Suite",
        "",
        "- Scope: run local verification gates first, then serialize every current API repeat=1 surface that is intentionally supported on this branch.",
        "- This suite does not replace the frozen `contest_honest_headline_v1` repeat=10 headline artifact.",
        "",
        "## Gate Results",
        "",
        "| gate | status | out |",
        "| --- | --- | --- |",
    ]
    for gate in gate_results:
        lines.append(f"| {gate['label']} | {gate['status']} | `{gate['relative_log']}` |")
    lines.extend(
        [
            "",
            "## API Surface Results",
            "",
            "| surface | kind | task_pack | exact_match_rate | admissible_match_rate | skipped_step_count | reuse_gain | task_ms | out |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for item in surface_results:
        lines.append(
            f"| {item['label']} | {item['kind']} | {item['task_pack']} | "
            f"{float(item.get('exact_match_rate', 0.0)):.2f} | "
            f"{float(item.get('admissible_match_rate', 0.0)):.2f} | "
            f"{float(item.get('skipped_step_count', 0.0)):.2f} | "
            f"{float(item.get('reuse_gain', 0.0)):.2f} | "
            f"{float(item.get('task_ms', 0.0)):.2f} | "
            f"`{item['relative_out']}` |"
        )
    lines.extend(["", "## Notes", ""])
    lines.append("- `pure_text_open_baseline_v1` remains the old lexical-stub audit surface by design.")
    lines.append("- `pure_text_open_live_api_slice_v1` is the real text-only live API slice and should be read separately from the lexical stub baseline.")
    lines.append("- `route_corpus_stress_whole_lane_audit_v1` is audit-only whole-lane stress evidence, not a headline replacement.")
    lines.append("- `langgraph_native_text_open_api_r1` is engineering appendix evidence.")
    lines.extend(["", "## Failures", ""])
    if failures:
        for failure in failures:
            lines.append(f"- {failure}")
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def _surface_out_dir(out_dir: Path, spec: dict[str, object]) -> Path:
    return out_dir / "api_repeat1" / str(spec["label"])


def _rewrite_existing_summary(out_dir: Path) -> None:
    gate_results: list[dict[str, object]] = []
    surface_results: list[dict[str, object]] = []
    failures: list[str] = []

    log_dir = out_dir / "logs"
    for label, _command in _build_gate_specs(
        argparse.Namespace(
            skip_runtime_smoke=False,
            skip_targeted_tests=False,
            with_full_pytest=True,
        )
    ):
        log_path = log_dir / f"{label}.log"
        if not log_path.exists():
            continue
        log_text = log_path.read_text(encoding="utf-8")
        passed = "[returncode] 0" in log_text
        gate_results.append(
            {
                "label": label,
                "status": "passed" if passed else "failed",
                "relative_log": str(log_path.relative_to(REPO_ROOT)),
            }
        )
        if not passed:
            failures.append(f"gate `{label}` failed")

    for spec in API_SURFACE_SPECS:
        surface_out = _surface_out_dir(out_dir, spec)
        try:
            surface_results.append(_summarize_surface(spec=spec, surface_out=surface_out))
        except FileNotFoundError:
            failures.append(f"surface `{spec['label']}` missing artifact under `{surface_out.relative_to(REPO_ROOT)}`")

    manifest = {
        "suite_name": "full_api_repeat1_coverage_suite",
        "generated_at": timestamp(),
        "surface_count": len(surface_results),
        "gate_count": len(gate_results),
        "failures": failures,
        "refresh_only": True,
    }
    (out_dir / "suite_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out_dir / "SUMMARY.md").write_text(
        _summary_md(gate_results=gate_results, surface_results=surface_results, failures=failures),
        encoding="utf-8",
    )


def main() -> None:
    args = build_arg_parser().parse_args()
    if args.refresh_summary_only is not None:
        _rewrite_existing_summary(args.refresh_summary_only.resolve())
        return
    out_dir = ensure_dir(args.out or _default_out_dir())
    commands: list[list[str]] = []
    gate_results: list[dict[str, object]] = []
    surface_results: list[dict[str, object]] = []
    failures: list[str] = []

    status_text = current_git_status()
    diff_stat_text = current_git_diff_stat()
    (out_dir / "WORKTREE_BASELINE.md").write_text(
        worktree_baseline_md(
            branch=status_text.splitlines()[0].replace("## ", "").strip(),
            planned_branch=PLANNED_BRANCH,
            status_text=status_text,
            diff_stat_text=diff_stat_text,
        ),
        encoding="utf-8",
    )

    for label, command in _build_gate_specs(args):
        commands.append(command)
        try:
            result = run_command(label=label, command=command, out_dir=out_dir)
            gate_results.append(
                {
                    "label": label,
                    "status": "passed",
                    "relative_log": str(result.log_path.relative_to(REPO_ROOT)),
                }
            )
        except subprocess.CalledProcessError:
            gate_results.append(
                {
                    "label": label,
                    "status": "failed",
                    "relative_log": str((out_dir / "logs" / f"{label}.log").relative_to(REPO_ROOT)),
                }
            )
            failures.append(f"gate `{label}` failed")
            (out_dir / "COMMANDS.md").write_text(commands_md(commands), encoding="utf-8")
            (out_dir / "SUMMARY.md").write_text(
                _summary_md(gate_results=gate_results, surface_results=surface_results, failures=failures),
                encoding="utf-8",
            )
            raise

    for spec in API_SURFACE_SPECS:
        surface_out = ensure_dir(_surface_out_dir(out_dir, spec))
        command = _build_benchmark_command(spec=spec, args=args, surface_out=surface_out)
        commands.append(command)
        try:
            run_command(label=str(spec["label"]), command=command, out_dir=out_dir)
            surface_results.append(_summarize_surface(spec=spec, surface_out=surface_out))
        except subprocess.CalledProcessError as exc:
            failures.append(
                f"surface `{spec['label']}` failed with return code {exc.returncode}; see `{surface_out.relative_to(REPO_ROOT)}`"
            )
            if not (bool(spec.get("appendix", False)) and args.allow_appendix_failure):
                (out_dir / "COMMANDS.md").write_text(commands_md(commands), encoding="utf-8")
                (out_dir / "SUMMARY.md").write_text(
                    _summary_md(gate_results=gate_results, surface_results=surface_results, failures=failures),
                    encoding="utf-8",
                )
                raise

    manifest = {
        "suite_name": "full_api_repeat1_coverage_suite",
        "generated_at": timestamp(),
        "surface_count": len(API_SURFACE_SPECS),
        "gate_count": len(gate_results),
        "failures": failures,
    }
    (out_dir / "suite_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out_dir / "COMMANDS.md").write_text(commands_md(commands), encoding="utf-8")
    (out_dir / "SUMMARY.md").write_text(
        _summary_md(gate_results=gate_results, surface_results=surface_results, failures=failures),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
