from __future__ import annotations

import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class CommandResult:
    label: str
    command: list[str]
    returncode: int
    log_path: Path


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_command(*, label: str, command: list[str], out_dir: Path) -> CommandResult:
    logs_dir = ensure_dir(out_dir / "logs")
    log_path = logs_dir / f"{label}.log"
    print(f"[{Path(sys.argv[0]).stem}] start {label}", flush=True)
    print(f"[{Path(sys.argv[0]).stem}] cmd   {shlex.join(command)}", flush=True)
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    log_path.write_text(
        "\n".join(
            [
                f"$ {shlex.join(command)}",
                "",
                completed.stdout.rstrip(),
                "",
                "[stderr]",
                completed.stderr.rstrip(),
                "",
                f"[returncode] {completed.returncode}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            command,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return CommandResult(
        label=label,
        command=command,
        returncode=completed.returncode,
        log_path=log_path,
    )


def commands_md(commands: list[list[str]]) -> str:
    lines = ["# Commands", ""]
    for command in commands:
        lines.append(f"- `{shlex.join(command)}`")
    return "\n".join(lines).rstrip() + "\n"


def worktree_baseline_md(*, branch: str, planned_branch: str, status_text: str, diff_stat_text: str) -> str:
    lines = [
        "# Worktree Baseline",
        "",
        f"- Recorded at: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Source branch before split: `{branch}`",
        f"- Planned working branch: `{planned_branch}`",
        "",
        "## git status --short --branch",
        "",
        "```text",
        status_text.rstrip(),
        "```",
        "",
        "## git diff --stat",
        "",
        "```text",
        diff_stat_text.rstrip(),
        "```",
    ]
    return "\n".join(lines).rstrip() + "\n"


def current_git_status() -> str:
    return subprocess.run(
        ["git", "status", "--short", "--branch"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def current_git_diff_stat() -> str:
    return subprocess.run(
        ["git", "diff", "--stat"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def load_benchmark_summary(surface_out: Path) -> dict[str, Any]:
    payload = json.loads((surface_out / "benchmark_results.json").read_text(encoding="utf-8"))
    manifest = dict(payload.get("manifest", {}))
    summary = dict(payload.get("summary", {}))
    return {
        "task_pack_type": manifest.get("task_pack_type", ""),
        "task_set_name": manifest.get("task_set_name", ""),
        "llm_backend": manifest.get("llm_backend", ""),
        "modes": list(manifest.get("modes", [])),
        "headline_gates": dict(manifest.get("headline_gates", {})),
        "summary": summary,
    }


def load_open_summary(surface_out: Path) -> dict[str, Any]:
    payload = json.loads((surface_out / "open_results.json").read_text(encoding="utf-8"))
    manifest = dict(payload.get("manifest", {}))
    summaries = list(payload.get("summary", []))
    return {
        "task_pack": manifest.get("task_pack", ""),
        "task_count": manifest.get("task_count", 0),
        "data_source": manifest.get("data_source", ""),
        "runtime_contract": manifest.get("runtime_contract", ""),
        "statebus_contract_used": bool(manifest.get("statebus_contract_used", False)),
        "summary": summaries,
    }
