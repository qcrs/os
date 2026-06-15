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

ACTIVE_V3_CORE_PACKS = (
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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the next-stage v3 repeat suite, including typed-consumer and open-system surfaces.",
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--llm-mode", choices=("api", "deterministic"), default="api")
    parser.add_argument("--llm-config", default="deploy/statebus_llm.yaml.local")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--packs", default=",".join(ACTIVE_V3_CORE_PACKS))
    parser.add_argument("--skip-regression-gates", action="store_true")
    parser.add_argument("--skip-statebus-packs", action="store_true")
    parser.add_argument("--skip-open-system", action="store_true")
    parser.add_argument("--skip-langgraph-smoke", action="store_true")
    parser.add_argument("--quiet-progress", action="store_true", default=True)
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

    for label, command, validator in _deterministic_gate_commands(out_dir=out_dir):
        commands.append(command)
        checks.append(_run_labeled(label=label, command=command, out_dir=out_dir))
        validator()

    if not args.skip_statebus_packs:
        for pack in _parse_packs(args.packs):
            pack_out = out_dir / "benchmarks" / pack
            command = _statebus_pack_command(args=args, pack=pack, out_dir=pack_out)
            commands.append(command)
            checks.append(_run_labeled(label=f"benchmark_{pack}", command=command, out_dir=out_dir))
            summaries.append(_summarize_statebus_pack(out_dir=out_dir, pack=pack))

    if not args.skip_open_system:
        open_out = out_dir / "open_system_comparison_v1"
        command = [
            sys.executable,
            "-m",
            "eval.open_runner",
            "--pack",
            "open_system_comparison_v1",
            "--repeat",
            str(args.repeat),
            "--out",
            str(open_out),
        ]
        commands.append(command)
        checks.append(_run_labeled(label="open_system_comparison_v1", command=command, out_dir=out_dir))
        summaries.append(_summarize_open_pack(out_dir=open_out, pack="open_system_comparison_v1"))

    if not args.skip_langgraph_smoke:
        smoke_out = out_dir / "langgraph_native_text_open"
        command = [
            sys.executable,
            "-m",
            "eval.open_runner",
            "--pack",
            "langgraph_native_text_open",
            "--repeat",
            "1",
            "--out",
            str(smoke_out),
        ]
        commands.append(command)
        checks.append(_run_labeled(label="langgraph_native_text_open", command=command, out_dir=out_dir))
        summaries.append(_summarize_open_pack(out_dir=smoke_out, pack="langgraph_native_text_open"))

    (out_dir / "COMMANDS.md").write_text(_commands_md(commands), encoding="utf-8")
    (out_dir / "SUMMARY.md").write_text(
        _summary_md(args=args, checks=checks, summaries=summaries),
        encoding="utf-8",
    )


def _default_out_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return REPO_ROOT / "runs" / f"v3_next_stage_repeat3_suite_{stamp}"


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
                "scripts/run_v3_next_stage_repeat3_suite.py",
            ],
        ),
        (
            "targeted_pytest",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_smoke.py",
                "-k",
                "memory_dual_mode_fairness_v3 or typed_state_consumer_sensitivity_v3 or open_system_comparison_v1 or langgraph_native_text_open",
            ],
        ),
    ]


def _deterministic_gate_commands(out_dir: Path) -> list[tuple[str, list[str], Any]]:
    fairness_out = out_dir / "gates" / "memory_dual_mode_fairness_v3"
    consumer_out = out_dir / "gates" / "typed_state_consumer_sensitivity_v3"
    return [
        (
            "gate_memory_dual_mode_fairness_v3_repeat1",
            [
                sys.executable,
                "-m",
                "eval.runner",
                "--task-set",
                "memory_dual_mode_fairness_v3",
                "--repeat",
                "1",
                "--llm-mode",
                "deterministic",
                "--embedding-mode",
                "deterministic",
                "--out",
                str(fairness_out),
                "--quiet-progress",
            ],
            lambda: _validate_fairness_gate(fairness_out),
        ),
        (
            "gate_typed_state_consumer_sensitivity_v3_repeat1",
            [
                sys.executable,
                "-m",
                "eval.runner",
                "--task-set",
                "typed_state_consumer_sensitivity_v3",
                "--repeat",
                "1",
                "--llm-mode",
                "deterministic",
                "--embedding-mode",
                "deterministic",
                "--out",
                str(consumer_out),
                "--quiet-progress",
            ],
            lambda: _validate_typed_consumer_gate(consumer_out),
        ),
    ]


def _validate_fairness_gate(out_dir: Path) -> None:
    result = json.loads((out_dir / "benchmark_results.json").read_text(encoding="utf-8"))
    manifest = result["manifest"]
    gate = manifest.get("object_parity_gate", {})
    failures: list[str] = []
    if str(manifest.get("withheld_headline_reason", "")).strip():
        failures.append(f"withheld_headline_reason={manifest.get('withheld_headline_reason')}")
    for key in ("passed", "executor_mainline_object_ok", "text_hidden_field_leak_zero"):
        if not bool(gate.get(key)):
            failures.append(f"object_parity_gate.{key}=false")
    if failures:
        raise SystemExit("memory_dual_mode_fairness_v3 deterministic gate failed: " + ", ".join(failures))


def _validate_typed_consumer_gate(out_dir: Path) -> None:
    result = json.loads((out_dir / "benchmark_results.json").read_text(encoding="utf-8"))
    manifest = result["manifest"]
    summary = result["summary"]["protocol"]
    consumer = summary["mechanism_audit"]["typed_state_consumer_sensitivity_v3"]
    tasks = result["mode_runs"]["protocol"][0]["tasks"]
    failures: list[str] = []
    if len(tasks) != 40:
        failures.append(f"task_count={len(tasks)}")
    if len({str(task.get("task_theme", "")) for task in tasks}) != 5:
        failures.append("family_coverage!=5")
    if manifest.get("task_set_evidence_tier") != "formal_secondary":
        failures.append(f"task_set_evidence_tier={manifest.get('task_set_evidence_tier')}")
    if float(consumer.get("missing_decision_failure_rate", 0.0)) < 1.0:
        failures.append("missing_decision_failure_rate<1.0")
    if (
        float(consumer.get("wrong_decision_mistool_rate", 0.0)) <= 0.0
        and float(consumer.get("wrong_decision_misroute_rate", 0.0)) <= 0.0
    ):
        failures.append("wrong_decision_no_tool_or_route_misfire")
    if failures:
        raise SystemExit(
            "typed_state_consumer_sensitivity_v3 deterministic gate failed: " + ", ".join(failures)
        )


def _parse_packs(raw: str) -> list[str]:
    packs = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = [pack for pack in packs if pack not in ACTIVE_V3_CORE_PACKS]
    if unknown:
        raise SystemExit(f"unsupported next-stage v3 pack aliases: {', '.join(unknown)}")
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
    print(f"[v3_next_stage_repeat3] start {label}", flush=True)
    print(f"[v3_next_stage_repeat3] cmd   {shlex.join(command)}", flush=True)
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
        "repeat": manifest.get("repeat", 0),
        "task_pack_type": manifest.get("task_pack_type", ""),
        "failure_counts": {
            mode: int(summary.get(mode, {}).get("failure_count", 0))
            for mode in ("text", "protocol")
            if mode in summary
        },
        "report": str(report_path.relative_to(out_dir)),
    }


def _summarize_open_pack(*, out_dir: Path, pack: str) -> dict[str, Any]:
    result_path = out_dir / "open_results.json"
    report_path = out_dir / "open_report.md"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    return {
        "surface": pack,
        "kind": "open_system",
        "repeat": result["manifest"].get("repeat", 0),
        "task_pack_type": result["manifest"].get("task_pack", pack),
        "failure_counts": {},
        "report": str(report_path),
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
        "# V3 Next Stage Repeat Suite Summary",
        "",
        "## Scope",
        "",
        f"- Repeat: `{args.repeat}`",
        f"- LLM mode: `{args.llm_mode}`",
        "- Includes active v3 core packs, `typed_state_consumer_sensitivity_v3`, `open_system_comparison_v1`, and `langgraph_native_text_open` smoke unless skipped.",
        "- This is a post-gate launcher. It is smoke-capable but not formal repeat evidence until deterministic fairness and typed-consumer gates pass.",
        f"- StateBus packs skipped: `{args.skip_statebus_packs}`",
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
            "| surface | kind | repeat | failure_counts | report |",
            "| --- | --- | ---: | --- | --- |",
        ]
    )
    for summary in summaries:
        lines.append(
            f"| {summary['surface']} | {summary['kind']} | {summary['repeat']} | `{summary['failure_counts']}` | `{summary['report']}` |"
        )
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    main()
