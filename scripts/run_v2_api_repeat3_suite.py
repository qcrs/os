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

from memory.store import DEFAULT_EMBEDDING_MODEL_PATH
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
        description="Archived v2 API repeat suite. It is not an active StateBus entrypoint.",
    )
    parser.add_argument(
        "--allow-archived-v2",
        action="store_true",
        help="Explicitly allow this archived v2 API suite to run.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory. Default: runs/v2_api_repeat3_suite_<timestamp>",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=3,
        help="Benchmark repeat count for each v2 pack. Default: 3.",
    )
    parser.add_argument(
        "--llm-config",
        default="deploy/statebus_llm.yaml.local",
        help="LLM config path for API mode.",
    )
    parser.add_argument(
        "--embedding-model",
        default=str(DEFAULT_EMBEDDING_MODEL_PATH),
        help="Local embedding model path.",
    )
    parser.add_argument("--planner-model", default=None)
    parser.add_argument("--summarizer-model", default=None)
    parser.add_argument("--executor-transport", choices=("local", "uds"), default="local")
    parser.add_argument("--executor-socket-path", default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--skip-regression-gates",
        action="store_true",
        help="Skip py_compile / pytest / runtime.smoke and run only the API repeat suite.",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    if not args.allow_archived_v2:
        raise SystemExit(
            "scripts/run_v2_api_repeat3_suite.py is archived and is not an active StateBus entrypoint. "
            "No API repeat suite is run in this remediation pass; pass --allow-archived-v2 for archaeology only."
        )
    out_dir = Path(args.out) if args.out else _default_out_dir(REPO_ROOT)
    out_dir.mkdir(parents=True, exist_ok=True)

    commands: list[list[str]] = []
    checks: list[dict[str, Any]] = []
    benchmark_summaries: list[dict[str, Any]] = []

    if not args.skip_regression_gates:
        gate_specs: list[tuple[str, list[str]]] = [
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
            ("runtime_smoke", [sys.executable, "-m", "runtime.smoke"]),
        ]
        for label, command in gate_specs:
            commands.append(command)
            log_path = out_dir / f"{label}.log"
            _print_progress(label=label, command=command, log_path=log_path)
            completed = _run_command(command, cwd=REPO_ROOT, log_path=log_path)
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
        completed = _run_command(command, cwd=REPO_ROOT, log_path=log_path)
        checks.append(
            {
                "label": f"benchmark_{pack_name}",
                "command": shlex.join(command),
                "log_path": str(log_path.relative_to(out_dir)),
                "returncode": completed.returncode,
            }
        )
        benchmark_summaries.append(_summarize_benchmark(out_dir=out_dir, pack_name=pack_name))

    (out_dir / "COMMANDS.md").write_text(_build_commands_md(commands), encoding="utf-8")
    (out_dir / "SUMMARY.md").write_text(
        _build_summary_md(out_dir=out_dir, args=args, checks=checks, summaries=benchmark_summaries),
        encoding="utf-8",
    )


def _default_out_dir(repo_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return repo_root / "runs" / f"v2_api_repeat3_suite_{stamp}"


def _print_progress(*, label: str, command: list[str], log_path: Path) -> None:
    print(f"[run_v2_api_repeat3_suite] start {label}", flush=True)
    print(f"[run_v2_api_repeat3_suite] log   {log_path}", flush=True)
    print(f"[run_v2_api_repeat3_suite] cmd   {shlex.join(command)}", flush=True)


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
        str(args.repeat),
        "--seed",
        str(args.seed),
        "--llm-mode",
        "api",
        "--llm-config",
        args.llm_config,
        "--embedding-model",
        args.embedding_model,
        "--executor-transport",
        args.executor_transport,
        "--out",
        str(out_dir),
        "--quiet-progress",
    ]
    if args.planner_model:
        command.extend(["--planner-model", args.planner_model])
    if args.summarizer_model:
        command.extend(["--summarizer-model", args.summarizer_model])
    if args.executor_socket_path:
        command.extend(["--executor-socket-path", args.executor_socket_path])
    return command


def _summarize_benchmark(*, out_dir: Path, pack_name: str) -> dict[str, Any]:
    pack_out = out_dir / "benchmarks" / pack_name
    report_path = pack_out / "benchmark_report.md"
    result_path = pack_out / "benchmark_results.json"
    report_text = report_path.read_text(encoding="utf-8")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    bundle = load_task_set_bundle(pack_name)
    manifest = result["manifest"]
    summary = result["summary"]

    checks: list[str] = []
    if pack_name == "planner_support_v2":
        _require("| exact_single_solution | 60 |" in report_text, pack_name, "expected repeat=3 case-type total missing")
        _require("| yaml |" in report_text and "| llm |" in report_text, pack_name, "missing yaml/llm rows")
        checks.extend(["repeat=3 case-type sum fixed", "yaml/llm rows present"])
    if pack_name == "semantic_retention_v2":
        for task in bundle.tasks:
            _require("pure-text" not in task.tags, pack_name, f"{task.task_id} still has pure-text tag")
            _require("typed-state" not in task.tags, pack_name, f"{task.task_id} still has typed-state tag")
        checks.append("retrieval tags cleaned")

    strategy_summary: dict[str, dict[str, float]] = {}
    for mode in ("text", "protocol"):
        for item in summary.get(mode, {}).get("transfer_strategies", []):
            strategy_summary[str(item.get("transfer_strategy", ""))] = {
                "task_count": float(item.get("task_count", 0.0)),
                "control_bytes": float(item.get("text_bytes" if mode == "text" else "protocol_bytes", 0.0)),
                "handoff_wire_bytes": float(item.get("handoff_wire_bytes", 0.0)),
                "handoff_payload_bytes": float(item.get("handoff_payload_bytes", 0.0)),
                "llm_total_tokens": float(item.get("llm_total_tokens", 0.0)),
                "task_ms": float(item.get("task_ms", 0.0)),
            }

    plan_sources: dict[str, list[str]] = {}
    for mode in ("text", "protocol"):
        runs = result["mode_runs"].get(mode, [])
        if not runs:
            continue
        tasks = runs[0].get("tasks", [])
        if any("plan_source" in task for task in tasks):
            plan_sources[mode] = sorted({str(task.get("plan_source", "")) for task in tasks})

    return {
        "pack_name": pack_name,
        "report_path": str(report_path.relative_to(out_dir)),
        "result_path": str(result_path.relative_to(out_dir)),
        "repeat": int(manifest.get("repeat", 0)),
        "task_mode_counts": dict(manifest.get("task_mode_counts", {})),
        "failure_counts": {
            mode: int(summary.get(mode, {}).get("failure_count", 0)) for mode in ("text", "protocol")
        },
        "checks": checks,
        "route_exact_rate": {
            mode: float(summary.get(mode, {}).get("misfire_audit", {}).get("case_contract", {}).get("route_exact_rate", 0.0))
            for mode in ("text", "protocol")
            if int(manifest.get("task_mode_counts", {}).get(mode, 0)) > 0
        },
        "admissible_match_rate": {
            mode: float(summary.get(mode, {}).get("misfire_audit", {}).get("case_contract", {}).get("admissible_match_rate", 0.0))
            for mode in ("text", "protocol")
            if int(manifest.get("task_mode_counts", {}).get(mode, 0)) > 0
        },
        "planner_plan_sources": plan_sources,
        "transfer_summary": strategy_summary,
    }


def _structured_unstructured_comparison(summaries: list[dict[str, Any]]) -> list[str]:
    lines = [
        "## Structured Vs Unstructured Focus",
        "",
        "| pack | unstructured side | structured side | control_bytes_delta | handoff_payload_delta | llm_total_tokens_delta | task_ms_delta | note |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for entry in summaries:
        pack = entry["pack_name"]
        transfer = entry["transfer_summary"]
        if pack == "carrier_controlled_v2":
            left = transfer.get("text_packet_minimal")
            right = transfer.get("state_packet_minimal")
            note = "matched carrier comparison under protocol-only minimal packet semantics"
            left_name = "text_packet_minimal"
            right_name = "state_packet_minimal"
        elif pack == "semantic_retention_v2":
            left = transfer.get("natural_handoff_text")
            right = transfer.get("channel_store_hashref")
            note = "natural free-text handoff versus typed state_ref under identical retrieval inputs"
            left_name = "natural_handoff_text"
            right_name = "channel_store_hashref"
        elif pack == "strict_pure_text_boundary_v2":
            left = transfer.get("inline_text_handoff")
            right = transfer.get("state_packet_minimal")
            note = "strict executor-facing pure text boundary versus typed minimal packet"
            left_name = "inline_text_handoff"
            right_name = "state_packet_minimal"
        else:
            continue
        if left is None or right is None:
            continue
        lines.append(
            f"| {pack} | {left_name} | {right_name} | "
            f"{right['control_bytes'] - left['control_bytes']:.2f} | "
            f"{right['handoff_payload_bytes'] - left['handoff_payload_bytes']:.2f} | "
            f"{right['llm_total_tokens'] - left['llm_total_tokens']:.2f} | "
            f"{right['task_ms'] - left['task_ms']:.2f} | {note} |"
        )
    lines.append("")
    return lines


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
    summaries: list[dict[str, Any]],
) -> str:
    lines = [
        "# V2 API Repeat-3 Suite Summary",
        "",
        "## Scope",
        "",
        "- Runs the full v2 benchmark suite in API mode with local embedding and repeat=3.",
        f"- LLM config: `{args.llm_config}`",
        f"- Embedding model: `{args.embedding_model}`",
        f"- Executor transport: `{args.executor_transport}`",
        "",
        "## Regression Gates",
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
            "| pack | repeat | task_mode_counts | failure_counts | admissible_match_rate | extra checks | report |",
            "| --- | ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for entry in summaries:
        lines.append(
            f"| {entry['pack_name']} | {entry['repeat']} | `{entry['task_mode_counts']}` | "
            f"`{entry['failure_counts']}` | `{entry['admissible_match_rate']}` | "
            f"{', '.join(entry['checks']) or '-'} | `{entry['report_path']}` |"
        )
        if entry["planner_plan_sources"]:
            lines.append(
                f"| {entry['pack_name']} plan_source | - | `{entry['planner_plan_sources']}` | - | - | - | `{entry['result_path']}` |"
            )
    lines.extend(["", * _structured_unstructured_comparison(summaries)])
    lines.extend(
        [
            "## Reading Boundary",
            "",
            "- This package is stronger than repeat=1 smoke, but it is still a host-side serialized API suite, not the final publication layer by itself.",
            "- `carrier_controlled_v2` answers carrier-only efficiency.",
            "- `semantic_retention_v2` answers semantic retention under matched retrieval input.",
            "- `strict_pure_text_boundary_v2` is formal-secondary boundary evidence, not the main headline.",
            "- `planner_support_v2` is support-only planner control evidence.",
            "",
            "## Paths",
            "",
            f"- Package root: `{out_dir}`",
            "- Commands: `COMMANDS.md`",
            "- Benchmark outputs: `benchmarks/<pack_name>/`",
            "- Logs: `logs/` plus top-level gate logs",
        ]
    )
    return "\n".join(lines) + "\n"


def _require(condition: bool, pack_name: str, message: str) -> None:
    if not condition:
        raise SystemExit(f"{pack_name}: {message}")


if __name__ == "__main__":
    main()
