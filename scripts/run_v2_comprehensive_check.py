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
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tasks.sample_tasks import load_task_set_bundle


BENCHMARK_PACKS = (
    "carrier_controlled_v2",
    "semantic_retention_v2",
    "strict_pure_text_boundary_v2",
    "memory_reuse_v2",
    "planner_support_v2",
    "langgraph_native_text_support_v2",
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Archived v2 benchmark checker. Use scripts/run_v3_comprehensive_check.py for the active surface.",
    )
    parser.add_argument(
        "--allow-archived-v2",
        action="store_true",
        help="Explicitly allow this archived v2 checker to run.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory. Default: runs/v2_comprehensive_check_<timestamp>",
    )
    parser.add_argument(
        "--skip-full-pytest",
        action="store_true",
        help="Skip the full `python -m pytest -q` step.",
    )
    parser.add_argument(
        "--llm-mode",
        choices=("deterministic", "api"),
        default="deterministic",
    )
    parser.add_argument("--llm-config", default=None)
    parser.add_argument("--embedding-model", default=None)
    parser.add_argument("--planner-model", default=None)
    parser.add_argument("--summarizer-model", default=None)
    parser.add_argument("--executor-transport", choices=("local", "uds"), default="local")
    parser.add_argument("--executor-socket-path", default=None)
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    if not args.allow_archived_v2:
        raise SystemExit(
            "scripts/run_v2_comprehensive_check.py is archived and is not an active StateBus entrypoint. "
            "Use scripts/run_v3_comprehensive_check.py, or pass --allow-archived-v2 for archaeology only."
        )
    repo_root = REPO_ROOT
    out_dir = Path(args.out) if args.out else _default_out_dir(repo_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    commands: list[list[str]] = []
    checks: list[dict[str, Any]] = []
    benchmark_summaries: list[dict[str, Any]] = []

    command_specs: list[tuple[str, list[str]]] = [
        (
            "py_compile",
            [sys.executable, "-m", "py_compile", "eval/runner.py", "tests/test_smoke.py"],
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
                (
                    "planner_support_v2 or semantic_retention_v2 or "
                    "carrier_controlled_v2 or strict_pure_text_boundary_v2 or "
                    "memory_reuse_v2 or langgraph_native_text_support_v2 or "
                    "case_contract or bounded_alternative or report"
                ),
            ],
        ),
    ]
    if not args.skip_full_pytest:
        command_specs.append(("full_pytest", [sys.executable, "-m", "pytest", "-q"]))
    command_specs.append(("runtime_smoke", [sys.executable, "-m", "runtime.smoke"]))

    for label, command in command_specs:
        commands.append(command)
        log_path = out_dir / f"{label}.log"
        _print_progress(label=label, command=command, log_path=log_path)
        completed = _run_command(command, cwd=repo_root, log_path=log_path)
        checks.append(
            {
                "label": label,
                "command": shlex.join(command),
                "log_path": str(log_path.relative_to(out_dir)),
                "returncode": completed.returncode,
            }
        )

    for pack_name in BENCHMARK_PACKS:
        pack_out = out_dir / "benchmarks" / pack_name
        command = _build_benchmark_command(args=args, out_dir=pack_out, pack_name=pack_name)
        commands.append(command)
        log_path = out_dir / "logs" / f"{pack_name}.log"
        _print_progress(label=f"benchmark_{pack_name}", command=command, log_path=log_path)
        completed = _run_command(command, cwd=repo_root, log_path=log_path)
        checks.append(
            {
                "label": f"benchmark_{pack_name}",
                "command": shlex.join(command),
                "log_path": str(log_path.relative_to(out_dir)),
                "returncode": completed.returncode,
            }
        )
        benchmark_summaries.append(_validate_benchmark_output(repo_root, out_dir, pack_name))

    (out_dir / "COMMANDS.md").write_text(_build_commands_md(commands), encoding="utf-8")
    (out_dir / "SUMMARY.md").write_text(
        _build_summary_md(
            out_dir=out_dir,
            args=args,
            checks=checks,
            benchmark_summaries=benchmark_summaries,
        ),
        encoding="utf-8",
    )


def _print_progress(*, label: str, command: list[str], log_path: Path) -> None:
    print(f"[run_v2_comprehensive_check] start {label}", flush=True)
    print(f"[run_v2_comprehensive_check] log   {log_path}", flush=True)
    print(f"[run_v2_comprehensive_check] cmd   {shlex.join(command)}", flush=True)


def _default_out_dir(repo_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return repo_root / "runs" / f"v2_comprehensive_check_{stamp}"


def _run_command(command: list[str], *, cwd: Path, log_path: Path) -> subprocess.CompletedProcess[str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise SystemExit(
            f"command failed with exit code {completed.returncode}: {shlex.join(command)}; see {log_path}"
        )
    return completed


def _build_benchmark_command(
    *,
    args: argparse.Namespace,
    out_dir: Path,
    pack_name: str,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "eval.runner",
        "--task-set",
        pack_name,
        "--repeat",
        "1",
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
    if args.planner_model:
        command.extend(["--planner-model", args.planner_model])
    if args.summarizer_model:
        command.extend(["--summarizer-model", args.summarizer_model])
    if args.executor_socket_path:
        command.extend(["--executor-socket-path", args.executor_socket_path])
    return command


def _validate_benchmark_output(repo_root: Path, out_dir: Path, pack_name: str) -> dict[str, Any]:
    pack_out = out_dir / "benchmarks" / pack_name
    report_path = pack_out / "benchmark_report.md"
    result_path = pack_out / "benchmark_results.json"
    report_text = report_path.read_text(encoding="utf-8")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    bundle = load_task_set_bundle(pack_name)

    checks: list[str] = []
    if pack_name == "carrier_controlled_v2":
        _require("V2 Carrier-Controlled Headline" in report_text, pack_name, "missing carrier headline")
        _require("text_packet_minimal" in report_text, pack_name, "missing text packet row")
        _require("state_packet_minimal" in report_text, pack_name, "missing state packet row")
        checks.extend(["headline present", "text/state packet rows present"])
    elif pack_name == "semantic_retention_v2":
        _require("V2 Semantic-Retention Headline" in report_text, pack_name, "missing semantic headline")
        _require("natural_handoff_text" in report_text, pack_name, "missing natural handoff row")
        _require("channel_store_hashref" in report_text, pack_name, "missing state ref row")
        for task in bundle.tasks:
            _require("pure-text" not in task.tags, pack_name, f"{task.task_id} still has pure-text tag")
            _require("typed-state" not in task.tags, pack_name, f"{task.task_id} still has typed-state tag")
        checks.extend(["headline present", "retrieval tags cleaned"])
    elif pack_name == "strict_pure_text_boundary_v2":
        _require("V2 Strict Pure-Text Boundary" in report_text, pack_name, "missing strict pure-text headline")
        _require("inline_text_handoff" in report_text, pack_name, "missing inline text row")
        _require("state_packet_minimal" in report_text, pack_name, "missing state packet row")
        checks.extend(["headline present", "inline/state packet rows present"])
    elif pack_name == "memory_reuse_v2":
        _require("Memory Reuse V2" in report_text, pack_name, "missing memory reuse title")
        checks.append("headline present")
    elif pack_name == "planner_support_v2":
        _require("Planner Support V2 (text)" in report_text, pack_name, "missing planner text section")
        _require("Planner Support V2 (protocol)" in report_text, pack_name, "missing planner protocol section")
        _require("| yaml |" in report_text, pack_name, "missing yaml control row")
        _require("| llm |" in report_text, pack_name, "missing llm control row")
        _require(
            "| exact_single_solution | 20 |" in report_text,
            pack_name,
            "combined case-type count is not summed across modes",
        )
        checks.extend(["text/protocol sections present", "yaml/llm rows present", "case-type sum fixed"])
    elif pack_name == "langgraph_native_text_support_v2":
        _require("support evidence only" in report_text, pack_name, "missing support-only boundary")
        checks.append("support boundary present")

    manifest = result["manifest"]
    summary = result["summary"]
    mode_counts = dict(manifest.get("task_mode_counts", {}))
    planner_plan_sources: dict[str, list[str]] = {}
    for mode in ("text", "protocol"):
        runs = result["mode_runs"].get(mode, [])
        if not runs:
            continue
        tasks = runs[0].get("tasks", [])
        if any("plan_source" in task for task in tasks):
            planner_plan_sources[mode] = sorted({str(task.get("plan_source", "")) for task in tasks})

    return {
        "pack_name": pack_name,
        "report_path": str(report_path.relative_to(out_dir)),
        "result_path": str(result_path.relative_to(out_dir)),
        "task_mode_counts": mode_counts,
        "failure_counts": {
            mode: int(summary.get(mode, {}).get("failure_count", 0)) for mode in ("text", "protocol")
        },
        "planner_plan_sources": planner_plan_sources,
        "checks": checks,
    }


def _require(condition: bool, pack_name: str, message: str) -> None:
    if not condition:
        raise SystemExit(f"{pack_name}: {message}")


def _build_commands_md(commands: list[list[str]]) -> str:
    lines = ["# Commands", ""]
    for command in commands:
        lines.extend(["```bash", shlex.join(command), "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def _build_summary_md(
    *,
    out_dir: Path,
    args: argparse.Namespace,
    checks: list[dict[str, Any]],
    benchmark_summaries: list[dict[str, Any]],
) -> str:
    lines = [
        "# V2 Comprehensive Check Summary",
        "",
        "## Scope",
        "",
        "- Runs host-side compile, targeted smoke, full pytest, runtime smoke, and all 6 formal/support v2 packs with `repeat=1`.",
        f"- LLM mode: `{args.llm_mode}`",
        f"- Executor transport: `{args.executor_transport}`",
        "",
        "## Regression Steps",
        "",
        "| step | returncode | log |",
        "| --- | ---: | --- |",
    ]
    for entry in checks:
        if not str(entry["label"]).startswith("benchmark_"):
            lines.append(
                f"| {entry['label']} | {entry['returncode']} | `{entry['log_path']}` |"
            )
    lines.extend(
        [
            "",
            "## Benchmark Packages",
            "",
            "| pack | task_mode_counts | failure_counts | extra checks | report |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for entry in benchmark_summaries:
        extra = ", ".join(entry["checks"])
        lines.append(
            f"| {entry['pack_name']} | `{entry['task_mode_counts']}` | `{entry['failure_counts']}` | "
            f"{extra} | `{entry['report_path']}` |"
        )
        if entry["planner_plan_sources"]:
            lines.append(
                f"| {entry['pack_name']} plan_source | `{entry['planner_plan_sources']}` | - | - | `{entry['result_path']}` |"
            )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `planner_support_v2` explicitly checks that the report contains `| exact_single_solution | 20 |`.",
            "- `semantic_retention_v2` also checks that the task bundle no longer contains `pure-text` or `typed-state` retrieval tags.",
            "",
            "## Paths",
            "",
            f"- Package root: `{out_dir}`",
            "- Full command list: `COMMANDS.md`",
            "- Benchmark outputs: `benchmarks/<pack_name>/`",
            "- Logs: `logs/` plus top-level `*.log` files",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
