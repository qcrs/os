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

V3_PACKS = (
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
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the active v3 deterministic/local StateBus check surface.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory. Default: runs/v3_comprehensive_check_<timestamp>",
    )
    parser.add_argument(
        "--packs",
        default=",".join(V3_PACKS),
        help="Comma-separated v3 pack aliases to run.",
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--llm-mode", choices=("deterministic", "api"), default="deterministic")
    parser.add_argument("--llm-config", default=None)
    parser.add_argument("--embedding-model", default=None)
    parser.add_argument("--executor-transport", choices=("local", "uds"), default="local")
    parser.add_argument("--executor-socket-path", default=None)
    parser.add_argument("--skip-pytest", action="store_true")
    parser.add_argument("--skip-runtime-smoke", action="store_true")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    out_dir = Path(args.out) if args.out else _default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    commands: list[list[str]] = []
    checks: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []

    gate_specs: list[tuple[str, list[str]]] = [
        ("py_compile", [sys.executable, "-m", "py_compile", "eval/runner.py", "tests/test_smoke.py"]),
    ]
    if not args.skip_pytest:
        gate_specs.append(
            (
                "targeted_pytest",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "tests/test_smoke.py",
                    "-k",
                    "v3 or memory_policy_controlled or typed_state_mechanism or external_text_baseline or typed_state_authenticity or memory_dual_mode_fairness",
                ],
            )
        )
    if not args.skip_runtime_smoke:
        gate_specs.append(("runtime_smoke", [sys.executable, "-m", "runtime.smoke"]))

    for label, command in gate_specs:
        commands.append(command)
        checks.append(_run_labeled(label=label, command=command, out_dir=out_dir))

    for pack in _parse_packs(args.packs):
        pack_out = out_dir / "benchmarks" / pack
        command = _benchmark_command(args=args, pack=pack, out_dir=pack_out)
        commands.append(command)
        checks.append(_run_labeled(label=f"benchmark_{pack}", command=command, out_dir=out_dir))
        summaries.append(_summarize_pack(out_dir=out_dir, pack=pack))

    (out_dir / "COMMANDS.md").write_text(_commands_md(commands), encoding="utf-8")
    (out_dir / "SUMMARY.md").write_text(
        _summary_md(out_dir=out_dir, checks=checks, summaries=summaries),
        encoding="utf-8",
    )


def _default_out_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return REPO_ROOT / "runs" / f"v3_comprehensive_check_{stamp}"


def _parse_packs(raw: str) -> list[str]:
    packs = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = [pack for pack in packs if pack not in V3_PACKS]
    if unknown:
        raise SystemExit(f"unsupported v3 pack aliases: {', '.join(unknown)}")
    return packs


def _benchmark_command(*, args: argparse.Namespace, pack: str, out_dir: Path) -> list[str]:
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
        "--executor-transport",
        args.executor_transport,
        "--out",
        str(out_dir),
        "--quiet-progress",
    ]
    if args.llm_config:
        command.extend(["--llm-config", args.llm_config])
    if args.embedding_model:
        command.extend(["--embedding-model", args.embedding_model])
    if args.executor_socket_path:
        command.extend(["--executor-socket-path", args.executor_socket_path])
    return command


def _run_labeled(*, label: str, command: list[str], out_dir: Path) -> dict[str, Any]:
    log_path = out_dir / "logs" / f"{label}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[run_v3_comprehensive_check] start {label}", flush=True)
    print(f"[run_v3_comprehensive_check] cmd   {shlex.join(command)}", flush=True)
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
        raise SystemExit(
            f"{label} failed with exit code {completed.returncode}; see {log_path}"
        )
    return {
        "label": label,
        "command": shlex.join(command),
        "returncode": completed.returncode,
        "log_path": str(log_path.relative_to(out_dir)),
    }


def _summarize_pack(*, out_dir: Path, pack: str) -> dict[str, Any]:
    result_path = out_dir / "benchmarks" / pack / "benchmark_results.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    manifest = result["manifest"]
    summary = result["summary"]
    return {
        "pack": pack,
        "task_pack_type": manifest.get("task_pack_type", ""),
        "withheld": manifest.get("withheld_headline_reason", ""),
        "mode_counts": manifest.get("task_mode_counts", {}),
        "failure_counts": {
            mode: int(summary.get(mode, {}).get("failure_count", 0))
            for mode in ("text", "protocol")
        },
        "report": f"benchmarks/{pack}/benchmark_report.md",
    }


def _commands_md(commands: list[list[str]]) -> str:
    lines = ["# Commands", ""]
    for command in commands:
        lines.extend(["```bash", shlex.join(command), "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def _summary_md(*, out_dir: Path, checks: list[dict[str, Any]], summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# V3 Comprehensive Check Summary",
        "",
        "## Scope",
        "",
        "- Runs active v3 deterministic/local checks. This is not repeat=10 or API formal evidence.",
        "",
        "## Gates",
        "",
        "| step | returncode | log |",
        "| --- | ---: | --- |",
    ]
    for check in checks:
        if not str(check["label"]).startswith("benchmark_"):
            lines.append(f"| {check['label']} | {check['returncode']} | `{check['log_path']}` |")
    lines.extend(
        [
            "",
            "## Benchmark Packs",
            "",
            "| pack | type | mode_counts | failure_counts | withheld | report |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for summary in summaries:
        lines.append(
            f"| {summary['pack']} | {summary['task_pack_type']} | `{summary['mode_counts']}` | "
            f"`{summary['failure_counts']}` | `{summary['withheld']}` | `{summary['report']}` |"
        )
    lines.extend(["", "## Paths", "", f"- Package root: `{out_dir}`"])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
