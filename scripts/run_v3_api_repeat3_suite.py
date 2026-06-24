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
    "typed_state_consumer_sensitivity_v3",
)

OPEN_PACKS = (
    "open_system_comparison_v1",
    "pure_text_open_baseline_v1",
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the active v3 StateBus API repeat=3 suite with host-side regression gates.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory. Default: runs/v3_api_repeat3_suite_<timestamp>",
    )
    parser.add_argument(
        "--packs",
        default=",".join(V3_PACKS),
        help="Comma-separated v3 pack aliases to run.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=3,
        help="Serialized API repeat count for each pack. Default: 3.",
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
    parser.add_argument("--llm-base-url", default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--statepool-backend", default=None)
    parser.add_argument("--embed-state-backend", default=None)
    parser.add_argument("--executor-transport", choices=("local", "uds"), default="local")
    parser.add_argument("--executor-socket-path", default=None)
    parser.add_argument("--skip-regression-gates", action="store_true")
    parser.add_argument("--skip-open-surfaces", action="store_true")
    parser.add_argument(
        "--open-task-set",
        default="contest_dual_mode_controlled_v3",
        help="Task set for open surfaces. Default: contest_dual_mode_controlled_v3.",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    out_dir = Path(args.out) if args.out else _default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    commands: list[list[str]] = []
    checks: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []

    if not args.skip_regression_gates:
        gate_specs: list[tuple[str, list[str]]] = [
            (
                "py_compile",
                [sys.executable, "-m", "py_compile", "eval/runner.py", "tests/test_smoke.py"],
            ),
            ("full_pytest", [sys.executable, "-m", "pytest", "-q"]),
            ("runtime_smoke", [sys.executable, "-m", "runtime.smoke"]),
        ]
        for label, command in gate_specs:
            commands.append(command)
            checks.append(_run_labeled(label=label, command=command, out_dir=out_dir))

    for pack in _parse_packs(args.packs):
        pack_out = out_dir / "benchmarks" / pack
        command = _benchmark_command(args=args, pack=pack, out_dir=pack_out)
        commands.append(command)
        checks.append(_run_labeled(label=f"benchmark_{pack}", command=command, out_dir=out_dir))
        summaries.append(_summarize_pack(out_dir=out_dir, pack=pack))

    if not args.skip_open_surfaces:
        for pack in OPEN_PACKS:
            pack_out = out_dir / "open_surfaces" / pack
            command = _open_command(args=args, pack=pack, out_dir=pack_out)
            commands.append(command)
            checks.append(_run_labeled(label=f"open_{pack}", command=command, out_dir=out_dir))
            summaries.append(_summarize_open_pack(out_dir=pack_out, pack=pack))

    (out_dir / "COMMANDS.md").write_text(_commands_md(commands), encoding="utf-8")
    (out_dir / "SUMMARY.md").write_text(
        _summary_md(out_dir=out_dir, args=args, checks=checks, summaries=summaries),
        encoding="utf-8",
    )


def _default_out_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return REPO_ROOT / "runs" / f"v3_api_repeat3_suite_{stamp}"


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
    if args.llm_base_url:
        command.extend(["--llm-base-url", args.llm_base_url])
    if args.statepool_backend:
        command.extend(["--statepool-backend", args.statepool_backend])
    if args.embed_state_backend:
        command.extend(["--embed-state-backend", args.embed_state_backend])
    if args.executor_socket_path:
        command.extend(["--executor-socket-path", args.executor_socket_path])
    return command


def _open_command(*, args: argparse.Namespace, pack: str, out_dir: Path) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "eval.open_runner",
        "--pack",
        pack,
        "--task-set",
        args.open_task_set,
        "--repeat",
        str(args.repeat),
        "--out",
        str(out_dir),
    ]
    return command


def _run_labeled(*, label: str, command: list[str], out_dir: Path) -> dict[str, Any]:
    log_path = out_dir / "logs" / f"{label}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[run_v3_api_repeat3_suite] start {label}", flush=True)
    print(f"[run_v3_api_repeat3_suite] log   {log_path}", flush=True)
    print(f"[run_v3_api_repeat3_suite] cmd   {shlex.join(command)}", flush=True)
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
    report_path = out_dir / "benchmarks" / pack / "benchmark_report.md"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    manifest = result["manifest"]
    summary = result["summary"]
    bundle = load_task_set_bundle(pack)

    headline_gates = manifest.get("headline_gates", {})
    communication_gate = headline_gates.get("communication_gate", {})
    typed_state_gate = headline_gates.get("typed_state_gate", {})
    memory_replay_gate = headline_gates.get("memory_replay_gate", {})
    object_parity_gate = manifest.get("object_parity_gate", {})
    formal_stability_gate = manifest.get("formal_stability_gate", {})
    contest_coverage_gate = manifest.get("contest_formal_coverage_gate", {})
    replay_evidence_gate = manifest.get("memory_replay_evidence_gate", {})

    return {
        "surface_kind": "statebus_pack",
        "pack": pack,
        "report": str(report_path.relative_to(out_dir)),
        "result": str(result_path.relative_to(out_dir)),
        "repeat": int(manifest.get("repeat", 0)),
        "task_count": len(bundle.tasks),
        "task_pack_type": str(manifest.get("task_pack_type", "")),
        "modes": list(manifest.get("modes", [])),
        "task_mode_counts": dict(manifest.get("task_mode_counts", {})),
        "failure_counts": {
            mode: int(summary.get(mode, {}).get("failure_count", 0))
            for mode in ("text", "protocol")
            if mode in summary
        },
        "expected_negative_control_failure_counts": {
            mode: int(summary.get(mode, {}).get("expected_negative_control_failure_count", 0))
            for mode in ("text", "protocol")
            if mode in summary
        },
        "withheld": str(manifest.get("withheld_headline_reason", "")),
        "single_variable": bool(manifest.get("task_set_single_variable", False)),
        "reading_contract": str(manifest.get("task_set_reading_contract", "")),
        "communication_gate_applicable": bool(communication_gate.get("applicable", False)),
        "communication_gate_allowed": bool(communication_gate.get("allowed", False)),
        "typed_state_gate_applicable": bool(typed_state_gate.get("applicable", False)),
        "typed_state_gate_allowed": bool(typed_state_gate.get("allowed", False)),
        "memory_replay_gate_applicable": bool(memory_replay_gate.get("applicable", False)),
        "memory_replay_gate_allowed": bool(memory_replay_gate.get("allowed", False)),
        "formal_stability_passed": bool(formal_stability_gate.get("passed", False)),
        "object_parity_passed": bool(object_parity_gate.get("passed", False)),
        "contest_coverage_passed": bool(contest_coverage_gate.get("passed", False)),
        "memory_replay_evidence_applicable": bool(replay_evidence_gate.get("applicable", False)),
        "memory_replay_evidence_passed": bool(replay_evidence_gate.get("passed", False)),
        "expectation_match_rate": {
            mode: float(summary.get(mode, {}).get("expectation_match_rate", 0.0))
            for mode in ("text", "protocol")
            if mode in summary
        },
        "admissible_match_rate": {
            mode: float(
                summary.get(mode, {}).get("misfire_audit", {}).get("case_contract", {}).get(
                    "admissible_match_rate", 0.0
                )
            )
            for mode in ("text", "protocol")
            if mode in summary
        },
    }


def _summarize_open_pack(*, out_dir: Path, pack: str) -> dict[str, Any]:
    result_path = out_dir / "open_results.json"
    report_path = out_dir / "open_report.md"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    manifest = result["manifest"]
    summary = result["summary"]
    return {
        "surface_kind": "open_surface",
        "pack": pack,
        "report": str(report_path.relative_to(out_dir)),
        "result": str(result_path.relative_to(out_dir)),
        "repeat": int(manifest.get("repeat", 0)),
        "task_count": int(manifest.get("task_count", 0)),
        "runtime_arms": list(manifest.get("runtime_arms", [])),
        "open_memory_policies": list(manifest.get("open_memory_policies", [])),
        "contract": str(manifest.get("contract", "")),
        "summary_rows": len(summary),
    }


def _commands_md(commands: list[list[str]]) -> str:
    lines = ["# Commands", ""]
    for command in commands:
        lines.extend(["```bash", shlex.join(command), "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def _summary_md(
    *,
    out_dir: Path,
    args: argparse.Namespace,
    checks: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
) -> str:
    lines = [
        "# V3 API Repeat-3 Suite Summary",
        "",
        "## Scope",
        "",
        "- Runs active v3 packs in serialized API mode with repeat=3.",
        "- Includes host-side regression gates first unless `--skip-regression-gates` is passed.",
        f"- LLM config: `{args.llm_config}`",
        f"- Embedding model: `{args.embedding_model}`",
        f"- Executor transport: `{args.executor_transport}`",
        "",
        "## Regression Gates",
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
            "## Surfaces",
            "",
            "| kind | pack | repeat | details | report |",
            "| --- | --- | ---: | --- | --- |",
        ]
    )
    for summary in summaries:
        if summary["surface_kind"] == "open_surface":
            details = (
                f"runtime_arms={summary['runtime_arms']}; "
                f"memory_policies={summary['open_memory_policies']}; "
                f"task_count={summary['task_count']}"
            )
            lines.append(
                f"| open_surface | {summary['pack']} | {summary['repeat']} | `{details}` | `{summary['report']}` |"
            )
            continue
        gates = []
        if summary["communication_gate_applicable"] and summary["communication_gate_allowed"]:
            gates.append("communication")
        if summary["typed_state_gate_applicable"] and summary["typed_state_gate_allowed"]:
            gates.append("typed_state")
        if summary["memory_replay_gate_applicable"] and summary["memory_replay_gate_allowed"]:
            gates.append("memory_replay")
        if summary["object_parity_passed"]:
            gates.append("object_parity")
        if summary["formal_stability_passed"]:
            gates.append("formal_stability")
        if summary["contest_coverage_passed"]:
            gates.append("contest_coverage")
        if summary["memory_replay_evidence_applicable"] and summary["memory_replay_evidence_passed"]:
            gates.append("replay_evidence")
        details = (
            f"modes={summary['task_mode_counts']}; failures={summary['failure_counts']}; "
            f"expected_negative_control_failures={summary['expected_negative_control_failure_counts']}; "
            f"withheld={summary['withheld']}; gates={','.join(gates) or '-'}"
        )
        lines.append(
            f"| statebus_pack | {summary['pack']} | {summary['repeat']} | `{details}` | `{summary['report']}` |"
        )

    lines.extend(
        [
            "",
            "## Reading Boundary",
            "",
            "- `contest_dual_mode_controlled_v3` is still a composite controlled surface: `text_strict_pure_lane` vs `state_packet_minimal` inside StateBus runtime.",
            "- `memory_dual_mode_fairness_v3` is fairness/object-parity only, not replay proof.",
            "- `typed_state_mechanism_v3` is the active protocol-only mechanism surface.",
            "- `typed_state_authenticity_v3` remains legacy compatibility support.",
            "- `memory_reuse_v3` and `memory_policy_controlled_v3` are the replay proof / replay policy packs.",
            "- `open_system_comparison_v1` and `pure_text_open_baseline_v1` stay as open/audit surfaces, not formal v3 headline proof.",
            "",
            "## Paths",
            "",
            f"- Package root: `{out_dir}`",
            "- Commands: `COMMANDS.md`",
            "- Summary: `SUMMARY.md`",
            "- Benchmark outputs: `benchmarks/<pack>/`",
            "- Logs: `logs/`",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
