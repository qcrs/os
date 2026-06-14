from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run matched StateBus benchmarks for mmap and shared_memory backends.",
    )
    parser.add_argument("--task-set", default="contest_dual_mode_controlled_v3")
    parser.add_argument("--modes", default="text,protocol")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--llm-mode", choices=("deterministic", "api"), default="deterministic")
    parser.add_argument("--llm-config", default=None)
    parser.add_argument("--embedding-model", default=None)
    parser.add_argument("--planner-model", default=None)
    parser.add_argument("--summarizer-model", default=None)
    parser.add_argument("--executor-transport", choices=("local", "uds"), default="local")
    parser.add_argument("--executor-socket-path", default=None)
    parser.add_argument("--out", default=None)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    out_dir = Path(args.out) if args.out else _default_out_dir(repo_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    commands: list[list[str]] = []
    results: dict[str, dict[str, Any]] = {}
    for backend in ("mmap", "shared_memory"):
        backend_out = out_dir / backend
        command = _build_backend_command(args=args, backend=backend, out_dir=backend_out)
        commands.append(command)
        log_path = out_dir / f"{backend}.log"
        completed = subprocess.run(
            command,
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        log_path.write_text(completed.stdout, encoding="utf-8")
        if completed.returncode != 0:
            raise SystemExit(
                f"{backend} benchmark failed with exit code {completed.returncode}; see {log_path}"
            )
        result_path = backend_out / "benchmark_results.json"
        results[backend] = json.loads(result_path.read_text(encoding="utf-8"))

    (out_dir / "COMMANDS.md").write_text(_build_commands_md(commands), encoding="utf-8")
    (out_dir / "SUMMARY.md").write_text(_build_summary_md(out_dir, results), encoding="utf-8")


def _default_out_dir(repo_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return repo_root / "runs" / f"statepool_backend_matrix_{stamp}"


def _build_backend_command(
    *,
    args: argparse.Namespace,
    backend: str,
    out_dir: Path,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "eval.runner",
        "--task-set",
        args.task_set,
        "--modes",
        args.modes,
        "--repeat",
        str(args.repeat),
        "--seed",
        str(args.seed),
        "--llm-mode",
        args.llm_mode,
        "--statepool-backend",
        backend,
        "--embed-state-backend",
        backend,
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


def _build_commands_md(commands: list[list[str]]) -> str:
    lines = ["# Commands", ""]
    for command in commands:
        lines.extend(["```bash", shlex.join(command), "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def _build_summary_md(out_dir: Path, results: dict[str, dict[str, Any]]) -> str:
    mmap_result = results["mmap"]
    shm_result = results["shared_memory"]
    manifest = mmap_result["manifest"]
    llm_mode = str(manifest["llm_mode"])
    lines = [
        "# StatePool Backend Matrix Summary",
        "",
        "## Scope",
        "",
        "- This package runs the same StateBus benchmark twice, changing only the state backend pair: `mmap` vs `shared_memory`.",
        "- It is a matched host-side comparison route for backend behavior, not a replacement for the replay-aware host-goal evidence packages.",
        f"- LLM mode: `{llm_mode}`",
        f"- Repeat: `{manifest['repeat']}`",
        f"- Modes: `{', '.join(manifest['modes'])}`",
        "",
        "## Where The Results Are",
        "",
        "- Command log: `COMMANDS.md`",
        "- Backend logs: `mmap.log`, `shared_memory.log`",
        "- MMAP package: `mmap/benchmark_report.md`",
        "- Shared-memory package: `shared_memory/benchmark_report.md`",
        "",
        "## Aggregate By Backend And Mode",
        "",
        "| backend | mode | control_bytes | state_bytes | mmap_state_bytes | shared_memory_state_bytes | llm_total_tokens | skipped_step_count | reuse_gain | task_ms |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for backend, result in (("mmap", mmap_result), ("shared_memory", shm_result)):
        for mode in result["manifest"]["modes"]:
            aggregate = result["summary"][mode]["aggregate"]
            lines.append(
                f"| {backend} | {mode} | {_control_bytes(aggregate, mode):.2f} | "
                f"{aggregate['state_bytes']:.2f} | {aggregate['mmap_state_bytes']:.2f} | "
                f"{aggregate['shared_memory_state_bytes']:.2f} | {aggregate['llm_total_tokens']:.2f} | "
                f"{aggregate['skipped_step_count']:.2f} | {aggregate['reuse_gain']:.2f} | "
                f"{aggregate['task_ms']:.2f} |"
            )
    lines.extend(
        [
            "",
            "## Shared-Memory Minus MMAP Delta",
            "",
            "| mode | control_bytes_delta | state_bytes_delta | mmap_state_bytes_delta | shared_memory_state_bytes_delta | llm_total_tokens_delta | skipped_step_count_delta | reuse_gain_delta | task_ms_delta |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in manifest["modes"]:
        mmap_aggregate = mmap_result["summary"][mode]["aggregate"]
        shm_aggregate = shm_result["summary"][mode]["aggregate"]
        lines.append(
            f"| {mode} | "
            f"{_control_bytes(shm_aggregate, mode) - _control_bytes(mmap_aggregate, mode):.2f} | "
            f"{shm_aggregate['state_bytes'] - mmap_aggregate['state_bytes']:.2f} | "
            f"{shm_aggregate['mmap_state_bytes'] - mmap_aggregate['mmap_state_bytes']:.2f} | "
            f"{shm_aggregate['shared_memory_state_bytes'] - mmap_aggregate['shared_memory_state_bytes']:.2f} | "
            f"{shm_aggregate['llm_total_tokens'] - mmap_aggregate['llm_total_tokens']:.2f} | "
            f"{shm_aggregate['skipped_step_count'] - mmap_aggregate['skipped_step_count']:.2f} | "
            f"{shm_aggregate['reuse_gain'] - mmap_aggregate['reuse_gain']:.2f} | "
            f"{shm_aggregate['task_ms'] - mmap_aggregate['task_ms']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "- This package is for matched backend comparison only.",
            "- It does not replace the replay-aware host-goal packages or their formal API timing claims.",
        ]
    )
    if llm_mode == "api":
        lines.append("- Because this run uses serialized API execution, the timing column is live API timing for this matched backend comparison.")
    else:
        lines.append("- Because this run uses deterministic execution, the timing column is not a formal live API latency claim.")
    lines.append(
        f"- Package root: `{out_dir}`"
    )
    return "\n".join(lines) + "\n"


def _control_bytes(aggregate: dict[str, Any], mode: str) -> float:
    return float(aggregate["text_bytes"] if mode == "text" else aggregate["protocol_bytes"])


if __name__ == "__main__":
    main()
