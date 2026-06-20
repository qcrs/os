from __future__ import annotations

import argparse
import sys
from pathlib import Path

from audit_suite_common import (
    REPO_ROOT,
    commands_md,
    current_git_diff_stat,
    current_git_status,
    ensure_dir,
    load_benchmark_summary,
    run_command,
    timestamp,
    worktree_baseline_md,
)


PLANNED_BRANCH = "feat/active-surface-and-external-text-baseline-20260619"

SPECS = (
    {
        "label": "memory_policy_controlled_v3_det_r1",
        "task_set": "memory_policy_controlled_v3",
        "llm_mode": "deterministic",
        "embedding_mode": "deterministic",
    },
    {
        "label": "memory_policy_controlled_v3_api_r1",
        "task_set": "memory_policy_controlled_v3",
        "llm_mode": "api",
        "embedding_mode": None,
    },
    {
        "label": "typed_state_consumer_sensitivity_v3_det_r1",
        "task_set": "typed_state_consumer_sensitivity_v3",
        "llm_mode": "deterministic",
        "embedding_mode": "deterministic",
    },
    {
        "label": "typed_state_consumer_sensitivity_v3_api_r1",
        "task_set": "typed_state_consumer_sensitivity_v3",
        "llm_mode": "api",
        "embedding_mode": None,
    },
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Refresh current-branch support evidence for memory policy and typed-state consumer sensitivity."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory. Default: runs/current_branch_support_refresh_<timestamp>",
    )
    parser.add_argument("--llm-config", default="deploy/statebus_llm.yaml.local")
    return parser


def _default_out_dir() -> Path:
    return REPO_ROOT / "runs" / f"current_branch_support_refresh_{timestamp()}"


def _build_command(*, spec: dict[str, object], args: argparse.Namespace, surface_out: Path) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "eval.runner",
        "--task-set",
        str(spec["task_set"]),
        "--repeat",
        "1",
        "--modes",
        "protocol",
        "--llm-mode",
        str(spec["llm_mode"]),
        "--out",
        str(surface_out),
        "--quiet-progress",
    ]
    if spec.get("embedding_mode"):
        command.extend(["--embedding-mode", str(spec["embedding_mode"])])
    if spec["llm_mode"] == "api":
        command.extend(["--llm-config", args.llm_config])
    return command


def _summary_md(*, out_dir: Path, surface_summaries: list[dict[str, object]]) -> str:
    lines = [
        "# Current-Branch Support Refresh",
        "",
        "- These artifacts are `current-branch support evidence`.",
        "- They are not the frozen headline.",
        "- They are not the historical June 16/17 support bundles.",
        "",
        "## Surfaces",
        "",
        "| surface | llm_backend | exact_match_rate | admissible_match_rate | skipped_step_count | reuse_gain | task_ms | replay_gate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in surface_summaries:
        summary = dict(item["mode_summary"])
        replay_gate = dict(item.get("replay_gate", {}))
        lines.append(
            f"| {item['label']} | {item['llm_backend']} | "
            f"{float(summary.get('exact_match_rate', 0.0)):.2f} | "
            f"{float(summary.get('admissible_match_rate', 0.0)):.2f} | "
            f"{float(summary.get('aggregate', {}).get('skipped_step_count', 0.0)):.2f} | "
            f"{float(summary.get('aggregate', {}).get('reuse_gain', 0.0)):.2f} | "
            f"{float(summary.get('aggregate', {}).get('task_ms', 0.0)):.2f} | "
            f"{'pass' if bool(replay_gate.get('passed')) else 'n/a'} |"
        )
        lines.append(f"| output |  |  |  |  |  |  | `{item['relative_out']}` |")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    args = build_arg_parser().parse_args()
    out_dir = ensure_dir(args.out or _default_out_dir())
    commands: list[list[str]] = []
    surface_summaries: list[dict[str, object]] = []
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

    for spec in SPECS:
        surface_out = ensure_dir(out_dir / str(spec["label"]))
        command = _build_command(spec=spec, args=args, surface_out=surface_out)
        commands.append(command)
        run_command(label=str(spec["label"]), command=command, out_dir=out_dir)
        payload = load_benchmark_summary(surface_out)
        mode_summary = dict(payload["summary"]["protocol"])
        replay_gate = {}
        headline_gates = dict(payload.get("headline_gates", {}))
        if "memory_replay_gate" in headline_gates:
            replay_gate = dict(
                headline_gates.get("memory_replay_gate", {}).get("memory_replay_evidence_gate", {})
            )
        surface_summaries.append(
            {
                "label": str(spec["label"]),
                "relative_out": str(surface_out.relative_to(REPO_ROOT)),
                "llm_backend": payload["llm_backend"],
                "mode_summary": mode_summary,
                "replay_gate": replay_gate,
            }
        )

    (out_dir / "COMMANDS.md").write_text(commands_md(commands), encoding="utf-8")
    (out_dir / "SUMMARY.md").write_text(
        _summary_md(out_dir=out_dir, surface_summaries=surface_summaries),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
