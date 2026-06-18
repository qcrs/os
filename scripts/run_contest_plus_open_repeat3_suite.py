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

STATEBUS_PACKS = (
    "contest_honest_headline_v1",
    "contest_dual_mode_controlled_v3",
    "memory_dual_mode_fairness_v3",
    "typed_state_mechanism_v3",
    "external_text_baseline_audit_v3",
    "text_definition_audit_v3",
    "typed_state_authenticity_v3",
    "typed_state_full_rich_audit_v3",
    "carrier_microbench_v3",
    "memory_reuse_v3",
    "memory_policy_controlled_v3",
    "planner_support_v3",
    "typed_state_consumer_sensitivity_v3",
)

OPEN_PACKS = (
    "open_system_comparison_v1",
    "pure_text_open_baseline_v1",
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a contest-first repeat suite that combines current StateBus formal/support packs, "
            "contest_honest_headline_v1, open comparison surfaces, and LangGraph native open smoke."
        )
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--llm-mode", choices=("api", "deterministic"), default="api")
    parser.add_argument("--llm-config", default="deploy/statebus_llm.yaml.local")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--statebus-packs", default=",".join(STATEBUS_PACKS))
    parser.add_argument("--skip-regression-gates", action="store_true")
    parser.add_argument("--skip-statebus-packs", action="store_true")
    parser.add_argument("--skip-open-surfaces", action="store_true")
    parser.add_argument("--skip-langgraph-open-smoke", action="store_true")
    parser.add_argument("--open-task-set", default="contest_honest_headline_v1")
    parser.add_argument("--langgraph-open-repeat", type=int, default=1)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    out_dir = args.out or _default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "logs").mkdir(parents=True, exist_ok=True)

    commands: list[list[str]] = []
    checks: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []

    if not args.skip_regression_gates:
        for label, command in _gate_commands():
            commands.append(command)
            checks.append(_run_labeled(label=label, command=command, out_dir=out_dir))

    if not args.skip_statebus_packs:
        for pack in _parse_requested(args.statebus_packs, allowed=STATEBUS_PACKS):
            pack_out = out_dir / "benchmarks" / pack
            command = _statebus_pack_command(args=args, pack=pack, out_dir=pack_out)
            commands.append(command)
            checks.append(_run_labeled(label=f"benchmark_{pack}", command=command, out_dir=out_dir))
            summaries.append(_summarize_statebus_pack(out_dir=out_dir, pack=pack))

    if not args.skip_open_surfaces:
        for pack in OPEN_PACKS:
            pack_out = out_dir / "open_surfaces" / pack
            command = [
                sys.executable,
                "-m",
                "eval.open_runner",
                "--pack",
                pack,
                "--repeat",
                str(args.repeat),
                "--task-set",
                args.open_task_set,
                "--out",
                str(pack_out),
            ]
            commands.append(command)
            checks.append(_run_labeled(label=f"open_{pack}", command=command, out_dir=out_dir))
            summaries.append(_summarize_open_pack(out_dir=pack_out, surface=pack))

    if not args.skip_langgraph_open_smoke:
        smoke_out = out_dir / "open_surfaces" / "langgraph_native_text_open"
        command = [
            sys.executable,
            "-m",
            "eval.open_runner",
            "--pack",
            "langgraph_native_text_open",
            "--repeat",
            str(args.langgraph_open_repeat),
            "--task-set",
            args.open_task_set,
            "--out",
            str(smoke_out),
        ]
        commands.append(command)
        checks.append(_run_labeled(label="open_langgraph_native_text_open", command=command, out_dir=out_dir))
        summaries.append(_summarize_open_pack(out_dir=smoke_out, surface="langgraph_native_text_open"))

    (out_dir / "COMMANDS.md").write_text(_commands_md(commands), encoding="utf-8")
    (out_dir / "SUMMARY.md").write_text(
        _summary_md(args=args, checks=checks, summaries=summaries),
        encoding="utf-8",
    )


def _default_out_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return REPO_ROOT / "runs" / f"contest_plus_open_repeat3_suite_{stamp}"


def _gate_commands() -> list[tuple[str, list[str]]]:
    return [
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
                "tests/test_state_channels_and_graph.py",
                "scripts/run_contest_plus_open_repeat3_suite.py",
            ],
        ),
        ("full_pytest", [sys.executable, "-m", "pytest", "-q"]),
        ("runtime_smoke", [sys.executable, "-m", "runtime.smoke"]),
    ]


def _parse_requested(raw: str, *, allowed: tuple[str, ...]) -> list[str]:
    packs = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = [pack for pack in packs if pack not in allowed]
    if unknown:
        raise SystemExit(f"unsupported pack aliases: {', '.join(unknown)}")
    return packs


def _statebus_pack_command(*, args: argparse.Namespace, pack: str, out_dir: Path) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "eval.runner",
        "--task-set",
        pack,
        "--repeat",
        str(args.repeat),
        "--seed",
        str(args.seed),
        "--llm-mode",
        args.llm_mode,
        "--out",
        str(out_dir),
        "--quiet-progress",
    ]
    if args.llm_mode == "api":
        command.extend(["--llm-config", args.llm_config])
    return command


def _run_labeled(*, label: str, command: list[str], out_dir: Path) -> dict[str, Any]:
    log_path = out_dir / "logs" / f"{label}.log"
    print(f"[contest_plus_open_repeat3] start {label}", flush=True)
    print(f"[contest_plus_open_repeat3] cmd   {shlex.join(command)}", flush=True)
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


def _summarize_statebus_pack(*, out_dir: Path, pack: str) -> dict[str, Any]:
    result_path = out_dir / "benchmarks" / pack / "benchmark_results.json"
    report_path = out_dir / "benchmarks" / pack / "benchmark_report.md"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    manifest = result["manifest"]
    summary = result["summary"]
    return {
        "surface": pack,
        "kind": "statebus_v3",
        "repeat": int(manifest.get("repeat", 0)),
        "withheld": str(manifest.get("withheld_headline_reason", "")),
        "failure_counts": {
            mode: int(summary.get(mode, {}).get("failure_count", 0))
            for mode in ("text", "protocol")
            if mode in summary
        },
        "report": str(report_path.relative_to(out_dir)),
    }


def _summarize_open_pack(*, out_dir: Path, surface: str) -> dict[str, Any]:
    result_path = out_dir / "open_results.json"
    report_path = out_dir / "open_report.md"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    manifest = result.get("manifest", {})
    return {
        "surface": surface,
        "kind": "open_system",
        "repeat": int(manifest.get("repeat", 0)),
        "withheld": str(manifest.get("task_pack", surface)),
        "failure_counts": {},
        "report": str(report_path.relative_to(out_dir)),
    }


def _commands_md(commands: list[list[str]]) -> str:
    lines = ["# Commands", ""]
    for command in commands:
        lines.extend(["```bash", shlex.join(command), "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def _summary_md(
    *,
    args: argparse.Namespace,
    checks: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
) -> str:
    lines = [
        "# Contest Plus Open Repeat Suite Summary",
        "",
        "## Scope",
        "",
        f"- Repeat: `{args.repeat}`",
        f"- LLM mode: `{args.llm_mode}`",
        f"- Open task set: `{args.open_task_set}`",
        f"- LangGraph open repeat: `{args.langgraph_open_repeat}`",
        "- Includes current contest-facing honest headline, active StateBus v3 packs, open comparison surfaces, and LangGraph native open smoke unless skipped.",
        "- This is broader than issue-discovery smoke and suitable for repeat=3 comparative readout, but it is not a formal repeat=10 contest package.",
        "",
        "## Launcher Logs",
        "",
        "| step | returncode | log |",
        "| --- | ---: | --- |",
    ]
    for check in checks:
        lines.append(f"| {check['label']} | {check['returncode']} | `{check['log_path']}` |")
    lines.extend(
        [
            "",
            "## Surfaces",
            "",
            "| surface | kind | repeat | failure_counts | withheld_or_pack | report |",
            "| --- | --- | ---: | --- | --- | --- |",
        ]
    )
    for summary in summaries:
        lines.append(
            f"| {summary['surface']} | {summary['kind']} | {summary['repeat']} | `{summary['failure_counts']}` | "
            f"`{summary['withheld']}` | `{summary['report']}` |"
        )
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    main()
