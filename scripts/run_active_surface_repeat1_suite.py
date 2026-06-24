from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

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
PLANNER_FIXCHECK = Path(
    "/home/qcrs/statebus/runs/planner_open_secondary_v3_api_r1_fixcheck_20260619_2/benchmark_results.json"
)

SURFACE_SPECS = (
    {
        "label": "contest_honest_headline_v1_det_r1",
        "kind": "runner",
        "task_set": "contest_honest_headline_v1",
        "modes": "text,protocol",
        "llm_mode": "deterministic",
        "embedding_mode": "deterministic",
    },
    {
        "label": "contest_honest_headline_v1_api_r1",
        "kind": "runner",
        "task_set": "contest_honest_headline_v1",
        "modes": "text,protocol",
        "llm_mode": "api",
        "embedding_mode": None,
    },
    {
        "label": "memory_policy_controlled_v3_det_r1",
        "kind": "runner",
        "task_set": "memory_policy_controlled_v3",
        "modes": "protocol",
        "llm_mode": "deterministic",
        "embedding_mode": "deterministic",
    },
    {
        "label": "memory_policy_controlled_v3_api_r1",
        "kind": "runner",
        "task_set": "memory_policy_controlled_v3",
        "modes": "protocol",
        "llm_mode": "api",
        "embedding_mode": None,
    },
    {
        "label": "typed_state_consumer_sensitivity_v3_det_r1",
        "kind": "runner",
        "task_set": "typed_state_consumer_sensitivity_v3",
        "modes": "protocol",
        "llm_mode": "deterministic",
        "embedding_mode": "deterministic",
    },
    {
        "label": "typed_state_consumer_sensitivity_v3_api_r1",
        "kind": "runner",
        "task_set": "typed_state_consumer_sensitivity_v3",
        "modes": "protocol",
        "llm_mode": "api",
        "embedding_mode": None,
    },
    {
        "label": "planner_support_v3_det_r1",
        "kind": "runner",
        "task_set": "planner_support_v3",
        "modes": "protocol",
        "llm_mode": "deterministic",
        "embedding_mode": "deterministic",
    },
    {
        "label": "planner_support_v3_api_r1",
        "kind": "runner",
        "task_set": "planner_support_v3",
        "modes": "protocol",
        "llm_mode": "api",
        "embedding_mode": None,
    },
    {
        "label": "text_helper_ablation_audit_v1_det_r1",
        "kind": "runner",
        "task_set": "text_helper_ablation_audit_v1",
        "modes": "text,protocol",
        "llm_mode": "deterministic",
        "embedding_mode": "deterministic",
    },
    {
        "label": "text_helper_ablation_audit_v1_api_r1",
        "kind": "runner",
        "task_set": "text_helper_ablation_audit_v1",
        "modes": "text,protocol",
        "llm_mode": "api",
        "embedding_mode": None,
    },
    {
        "label": "route_corpus_stress_audit_v1_det_r1",
        "kind": "runner",
        "task_set": "route_corpus_stress_audit_v1",
        "modes": "text,protocol",
        "llm_mode": "deterministic",
        "embedding_mode": "deterministic",
    },
    {
        "label": "route_corpus_stress_audit_v1_api_r1",
        "kind": "runner",
        "task_set": "route_corpus_stress_audit_v1",
        "modes": "text,protocol",
        "llm_mode": "api",
        "embedding_mode": None,
    },
    {
        "label": "pure_text_open_baseline_v1_det_r1",
        "kind": "open_runner",
        "pack": "pure_text_open_baseline_v1",
        "task_set": "contest_honest_headline_v1",
    },
    {
        "label": "pure_text_open_baseline_v1_api_r1",
        "kind": "open_runner",
        "pack": "pure_text_open_baseline_v1",
        "task_set": "contest_honest_headline_v1",
    },
)

APPENDIX_SPEC = {
    "label": "langgraph_native_text_open_smoke_r1",
    "kind": "open_runner",
    "pack": "langgraph_native_text_open",
    "appendix": True,
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the active-surface repeat=1 suite.")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory. Default: runs/active_surface_repeat1_suite_<timestamp>",
    )
    parser.add_argument("--llm-config", default="deploy/statebus_llm.yaml.local")
    parser.add_argument("--include-appendix-open-smoke", action="store_true")
    return parser


def _default_out_dir() -> Path:
    return REPO_ROOT / "runs" / f"active_surface_repeat1_suite_{timestamp()}"


def _build_command(*, spec: dict[str, object], args: argparse.Namespace, surface_out: Path) -> list[str]:
    if spec["kind"] == "runner":
        command = [
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
    command = [
        sys.executable,
        "-m",
        "eval.open_runner",
        "--pack",
        str(spec["pack"]),
        "--repeat",
        "1",
        "--out",
        str(surface_out),
    ]
    if spec.get("task_set"):
        command.extend(["--task-set", str(spec["task_set"])])
    if spec["label"].endswith("_api_r1"):
        command.extend(["--llm-config", args.llm_config])
    return command


def _load_fixcheck_summary() -> dict[str, Any]:
    payload = json.loads(PLANNER_FIXCHECK.read_text(encoding="utf-8"))
    return dict(payload.get("summary", {}).get("protocol", {}))


def _runner_entry(*, spec: dict[str, object], surface_out: Path) -> dict[str, object]:
    payload = load_benchmark_summary(surface_out)
    if "protocol" in payload["summary"]:
        mode_summary = dict(payload["summary"]["protocol"])
    else:
        mode_summary = dict(payload["summary"]["text"])
    public_surface = ""
    headline_gates = dict(payload.get("headline_gates", {}))
    return {
        "label": str(spec["label"]),
        "relative_out": str(surface_out.relative_to(REPO_ROOT)),
        "task_pack": payload["task_pack_type"],
        "llm_backend": payload["llm_backend"],
        "exact_match_rate": float(mode_summary.get("exact_match_rate", 0.0)),
        "admissible_match_rate": float(mode_summary.get("admissible_match_rate", 0.0)),
        "task_ms": float(mode_summary.get("aggregate", {}).get("task_ms", 0.0)),
        "skipped_step_count": float(mode_summary.get("aggregate", {}).get("skipped_step_count", 0.0)),
        "reuse_gain": float(mode_summary.get("aggregate", {}).get("reuse_gain", 0.0)),
        "headline_allowed": bool(headline_gates.get("allowed")) if headline_gates else False,
        "public_surface": public_surface,
    }


def _open_entry(*, spec: dict[str, object], surface_out: Path) -> dict[str, object]:
    payload = load_open_summary(surface_out)
    row = dict(payload["summary"][0]) if payload["summary"] else {}
    return {
        "label": str(spec["label"]),
        "relative_out": str(surface_out.relative_to(REPO_ROOT)),
        "task_pack": payload["task_pack"],
        "llm_backend": "api" if spec["label"].endswith("_api_r1") else "deterministic",
        "exact_match_rate": float(row.get("exact_match_rate", 0.0)),
        "admissible_match_rate": float(row.get("admissible_match_rate", 0.0)),
        "task_ms": float(row.get("task_ms", 0.0)),
        "skipped_step_count": float(row.get("skipped_step_count", 0.0)),
        "reuse_gain": float(row.get("reuse_gain", 0.0)),
        "data_source": payload.get("data_source", ""),
        "runtime_contract": payload.get("runtime_contract", ""),
        "statebus_contract_used": bool(payload.get("statebus_contract_used", False)),
    }


def _classify(entry: dict[str, object], *, appendix: bool = False, fixcheck_summary: dict[str, Any] | None = None) -> tuple[str, str]:
    label = str(entry["label"])
    if appendix:
        return ("audit-only risks", f"`{label}` appendix open smoke only; non-blocking.")
    if label.startswith("pure_text_open_baseline_v1"):
        return (
            "reporting drift only",
            f"`{label}` still reports `data_source={entry.get('data_source', '')}`; this remains audit-only and not a live external baseline.",
        )
    if label.startswith("text_helper_ablation_audit_v1") or label.startswith("route_corpus_stress_audit_v1"):
        return (
            "audit-only risks",
            f"`{label}` is normal but stays on an audit-only layer; do not promote it into the frozen headline.",
        )
    if label == "planner_support_v3_api_r1" and fixcheck_summary is not None:
        current_rate = float(entry.get("admissible_match_rate", 0.0))
        fixcheck_rate = float(fixcheck_summary.get("admissible_match_rate", 0.0))
        if current_rate + 1e-9 < fixcheck_rate:
            return (
                "regression candidates",
                f"`{label}` is a new regression vs latest valid fixcheck: admissible `{current_rate:.2f}` vs `{fixcheck_rate:.2f}`.",
            )
    return (
        "alive surfaces",
        f"`{label}` completed: admissible `{float(entry.get('admissible_match_rate', 0.0)):.2f}`, exact `{float(entry.get('exact_match_rate', 0.0)):.2f}`.",
    )


def _summary_md(
    *,
    entries: list[dict[str, object]],
    appendix_entries: list[dict[str, object]],
    notes: dict[str, list[str]],
) -> str:
    lines = [
        "# Active Surface Repeat1 Suite",
        "",
        "## Surface Table",
        "",
        "| surface | task_pack | llm_backend | exact_match_rate | admissible_match_rate | skipped_step_count | reuse_gain | task_ms | out |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for entry in [*entries, *appendix_entries]:
        lines.append(
            f"| {entry['label']} | {entry['task_pack']} | {entry['llm_backend']} | "
            f"{float(entry.get('exact_match_rate', 0.0)):.2f} | "
            f"{float(entry.get('admissible_match_rate', 0.0)):.2f} | "
            f"{float(entry.get('skipped_step_count', 0.0)):.2f} | "
            f"{float(entry.get('reuse_gain', 0.0)):.2f} | "
            f"{float(entry.get('task_ms', 0.0)):.2f} | "
            f"`{entry['relative_out']}` |"
        )
    for section in ("alive surfaces", "regression candidates", "reporting drift only", "audit-only risks"):
        lines.extend(["", f"## {section.title()}", ""])
        section_notes = notes.get(section, [])
        if section_notes:
            for note in section_notes:
                lines.append(f"- {note}")
        else:
            lines.append("- none")
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- `contest_honest_headline_v1` here is current-branch repeat=1 state only; it does not replace the frozen repeat=10 headline.",
            "- `planner_support_v3` API state must read against `/home/qcrs/statebus/runs/planner_open_secondary_v3_api_r1_fixcheck_20260619_2/` when classifying regressions.",
            "- `pure_text_open_baseline_v1` remaining `lexical_stub` is reporting drift, not live external text evidence.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    args = build_arg_parser().parse_args()
    out_dir = ensure_dir(args.out or _default_out_dir())
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

    commands: list[list[str]] = []
    entries: list[dict[str, object]] = []
    appendix_entries: list[dict[str, object]] = []
    notes: dict[str, list[str]] = {
        "alive surfaces": [],
        "regression candidates": [],
        "reporting drift only": [],
        "audit-only risks": [],
    }
    hard_failures: list[str] = []
    fixcheck_summary = _load_fixcheck_summary() if PLANNER_FIXCHECK.exists() else None

    specs = list(SURFACE_SPECS)
    if args.include_appendix_open_smoke:
        specs.append(APPENDIX_SPEC)

    for spec in specs:
        surface_out = ensure_dir(out_dir / str(spec["label"]))
        command = _build_command(spec=spec, args=args, surface_out=surface_out)
        commands.append(command)
        appendix = bool(spec.get("appendix", False))
        try:
            run_command(label=str(spec["label"]), command=command, out_dir=out_dir)
            if spec["kind"] == "runner":
                entry = _runner_entry(spec=spec, surface_out=surface_out)
            else:
                entry = _open_entry(spec=spec, surface_out=surface_out)
            bucket, note = _classify(entry, appendix=appendix, fixcheck_summary=fixcheck_summary)
            notes[bucket].append(note)
            if appendix:
                appendix_entries.append(entry)
            else:
                entries.append(entry)
        except subprocess.CalledProcessError as exc:
            message = f"`{spec['label']}` failed with return code {exc.returncode}; see `{surface_out.relative_to(REPO_ROOT)}`."
            target_bucket = "audit-only risks" if appendix else "regression candidates"
            notes[target_bucket].append(message)
            if not appendix:
                hard_failures.append(str(spec["label"]))

    (out_dir / "COMMANDS.md").write_text(commands_md(commands), encoding="utf-8")
    (out_dir / "SUMMARY.md").write_text(
        _summary_md(entries=entries, appendix_entries=appendix_entries, notes=notes),
        encoding="utf-8",
    )
    if hard_failures:
        raise SystemExit(f"active-surface regressions: {', '.join(hard_failures)}")


if __name__ == "__main__":
    main()
