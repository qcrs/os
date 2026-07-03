from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.runtime.smoke import SmokeLayerConfig, run_smoke
from v2.utils import stable_json_dumps


def _default_output_root() -> Path:
    return Path(os.getenv("STATEBUS_RUNS_DIR", "/tmp")) / "v2-diagnostics"


def _timestamp_label() -> str:
    return time.strftime("%Y%m%d_%H%M%S", time.localtime())


def _bundle_dir(output_root: Path, suite_id: str) -> Path:
    return output_root / f"{suite_id}-{_timestamp_label()}"


def _short_socket_path(bundle_dir: Path) -> Path:
    digest = hashlib.sha256(str(bundle_dir).encode("utf-8")).hexdigest()[:16]
    return Path("/tmp") / f"statebus-v2-diag-{digest}.sock"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")


def _write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _file_kind(relpath: Path) -> tuple[str, str]:
    parts = relpath.parts
    if len(parts) >= 2 and parts[0] == "sidecars":
        return "sidecar", parts[1]
    if len(parts) >= 2 and parts[0] == "manifests":
        return "manifest", parts[1]
    if len(parts) >= 2 and parts[0] == "telemetry":
        return "telemetry", parts[1]
    return "other", parts[0] if parts else ""


def _collect_file_rows(runtime_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(runtime_root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in {".json", ".jsonl"}:
            continue
        relpath = path.relative_to(runtime_root)
        kind, group = _file_kind(relpath)
        rows.append(
            {
                "kind": kind,
                "group": group,
                "relpath": str(relpath),
                "size_bytes": path.stat().st_size,
            }
        )
    rows.sort(key=lambda row: int(row["size_bytes"]), reverse=True)
    return rows


def _group_totals(rows: list[dict[str, Any]], *, kind: str) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, int]] = defaultdict(lambda: {"file_count": 0, "total_size_bytes": 0})
    for row in rows:
        if row["kind"] != kind:
            continue
        bucket = totals[str(row["group"])]
        bucket["file_count"] += 1
        bucket["total_size_bytes"] += int(row["size_bytes"])
    payload = [
        {"group": group, **metrics}
        for group, metrics in totals.items()
    ]
    payload.sort(key=lambda item: int(item["total_size_bytes"]), reverse=True)
    return payload


def _profile_includes_row(profile: str, row: dict[str, Any]) -> bool:
    kind = str(row["kind"])
    group = str(row["group"])
    if profile == "audit_full":
        return True
    if profile == "benchmark_balanced":
        if kind in {"manifest", "telemetry"}:
            return True
        return group not in {
            "codeact_plan_audits",
            "codeact_record_audits",
            "role_prompt_slices",
        }
    if profile == "fast_runtime":
        return kind == "manifest" or group in {
            "artifact_manifests",
            "execution_steps",
            "memory_commits",
            "replay_ledgers",
            "runtime_sessions",
        }
    raise ValueError(f"unsupported persistence profile: {profile}")


def _persistence_profile_readout(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profile_boundaries = {
        "audit_full": "keeps every manifest, sidecar, telemetry log, and audit detail; highest replay/debuggability",
        "benchmark_balanced": "keeps benchmark/replay-critical manifests and compact sidecars; drops repeated deep audit details",
        "fast_runtime": "keeps minimum runtime/replay lineage candidates only; diagnostic detail must be regenerated separately",
    }
    readouts = []
    total_bytes = sum(int(row["size_bytes"]) for row in rows)
    total_count = len(rows)
    for profile in ("audit_full", "benchmark_balanced", "fast_runtime"):
        included = [row for row in rows if _profile_includes_row(profile, row)]
        included_bytes = sum(int(row["size_bytes"]) for row in included)
        included_groups = sorted({f"{row['kind']}:{row['group']}" for row in included})
        readouts.append(
            {
                "profile": profile,
                "included_file_count": len(included),
                "excluded_file_count": total_count - len(included),
                "included_size_bytes": included_bytes,
                "excluded_size_bytes": total_bytes - included_bytes,
                "included_size_ratio": round(0.0 if total_bytes == 0 else included_bytes / total_bytes, 6),
                "included_groups": included_groups,
                "claim_boundary": profile_boundaries[profile],
            }
        )
    return readouts


def _persist_metric_subset(task_metrics: dict[str, float]) -> dict[str, float]:
    keys = sorted(key for key in task_metrics if key.startswith("persist_"))
    return {key: float(task_metrics[key]) for key in keys}


def _recommend_next_target(sidecar_totals: list[dict[str, Any]]) -> str:
    if not sidecar_totals:
        return "no_sidecar_payloads_detected"
    largest_group = str(sidecar_totals[0]["group"])
    recommendations = {
        "retrieval_logs": "continue shrinking retrieval_log payloads before comparator work",
        "runtime_sessions": "continue compacting runtime_session audit payloads without losing lifecycle hashes",
        "execution_steps": "continue externalizing execution_step repeated audit blobs",
        "retrieval_candidate_pools": "continue deduplicating candidate surface and planner scope payloads",
        "memory_commits": "continue deduplicating memory commit metadata against manifest refs",
        "replay_ledgers": "continue reducing replay ledger repeated signature metadata",
    }
    return recommendations.get(largest_group, f"inspect {largest_group} as the current largest persistence bucket")


def _build_markdown_summary(summary: dict[str, Any]) -> str:
    smoke = summary["smoke"]
    persist = summary["persist"]
    top_sidecars = summary["top_sidecars"]
    sidecar_totals = summary["sidecar_totals"]
    lines = [
        "# Runtime Persistence Breakdown",
        "",
        f"- bundle dir: `{summary['bundle_dir']}`",
        f"- task id: `{smoke['task_id']}`",
        f"- layer: `{smoke['layer_name']}`",
        f"- role path mode: `{smoke['role_path_mode']}`",
        f"- embedding mode: `{smoke['embedding_mode']}`",
        f"- replay enabled: `{smoke['replay_enabled']}`",
        f"- persist bundle write stage ms: `{persist['persist_bundle_write_stage_ms']:.6f}`",
        f"- persist and reload stage ms: `{persist['persist_and_reload_stage_ms']:.6f}`",
        f"- next target: `{summary['next_target']}`",
        "",
        "## Largest Sidecars",
        "",
    ]
    if not top_sidecars:
        lines.append("- none")
    else:
        for row in top_sidecars[:10]:
            lines.append(
                f"- `{row['group']}` `{row['size_bytes']}` B `{row['relpath']}`"
            )
    lines.extend(
        [
            "",
            "## Sidecar Totals",
            "",
        ]
    )
    if not sidecar_totals:
        lines.append("- none")
    else:
        for row in sidecar_totals[:10]:
            lines.append(
                f"- `{row['group']}` total `{row['total_size_bytes']}` B across `{row['file_count']}` files"
            )
    lines.extend(["", "## Persistence Profiles", ""])
    for profile in summary.get("persistence_profiles", []):
        lines.append(
            f"- `{profile['profile']}` keeps `{profile['included_file_count']}` files, "
            f"`{profile['included_size_bytes']}` B, ratio `{profile['included_size_ratio']}`; "
            f"{profile['claim_boundary']}"
        )
    return "\n".join(lines)


def build_runtime_persistence_breakdown_bundle(
    *,
    output_root: Path,
    suite_id: str,
    task_id: str,
    layer_name: str,
    handoff_mode: str,
    structured_control_enabled: bool,
    semantic_pruning_enabled: bool,
    replay_enabled: bool,
    multi_attempt_enabled: bool,
    force_first_attempt_trap: bool,
    role_path_mode: str,
    embedding_mode: str,
    seed_replay_memory: bool,
    history_runtime_roots: tuple[Path, ...] = (),
) -> Path:
    bundle_dir = _bundle_dir(output_root, suite_id)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    workspace_root = bundle_dir / "workspaces"
    runtime_root = bundle_dir / "runtime"
    socket_path = _short_socket_path(bundle_dir)
    layer_config = SmokeLayerConfig(
        layer_name=layer_name,
        handoff_mode=handoff_mode,
        structured_control_enabled=structured_control_enabled,
        semantic_pruning_enabled=semantic_pruning_enabled,
        replay_enabled=replay_enabled,
        multi_attempt_enabled=multi_attempt_enabled,
        force_first_attempt_trap=force_first_attempt_trap,
        hermetic_runtime_root=True,
        role_path_mode=role_path_mode,
        embedding_mode=embedding_mode,
    )
    result = run_smoke(
        workspace_root=workspace_root,
        runtime_root=runtime_root,
        socket_path=socket_path,
        task_id=task_id,
        layer_config=layer_config,
        seed_replay_memory=seed_replay_memory,
        history_runtime_roots=history_runtime_roots,
    )

    file_rows = _collect_file_rows(runtime_root)
    sidecar_rows = [row for row in file_rows if row["kind"] == "sidecar"]
    manifest_rows = [row for row in file_rows if row["kind"] == "manifest"]
    telemetry_rows = [row for row in file_rows if row["kind"] == "telemetry"]
    sidecar_totals = _group_totals(file_rows, kind="sidecar")
    manifest_totals = _group_totals(file_rows, kind="manifest")

    summary = {
        "bundle_dir": str(bundle_dir),
        "runtime_root": str(runtime_root),
        "workspace_root": str(workspace_root),
        "summary_json": str(bundle_dir / "summary.json"),
        "summary_markdown": str(bundle_dir / "summary.md"),
        "smoke": {
            "task_id": result.task_id,
            "layer_name": layer_name,
            "handoff_mode": handoff_mode,
            "structured_control_enabled": structured_control_enabled,
            "semantic_pruning_enabled": semantic_pruning_enabled,
            "replay_enabled": replay_enabled,
            "multi_attempt_enabled": multi_attempt_enabled,
            "force_first_attempt_trap": force_first_attempt_trap,
            "role_path_mode": role_path_mode,
            "embedding_mode": embedding_mode,
            "seed_replay_memory": seed_replay_memory,
            "history_runtime_root_count": len(history_runtime_roots),
        },
        "persist": {
            "persist_bundle_write_stage_ms": float(result.task_metrics.get("persist_bundle_write_stage_ms", 0.0)),
            "persist_and_reload_stage_ms": float(result.runtime_stage_metrics.get("persist_and_reload_stage_ms", 0.0)),
            "persist_metric_subset": _persist_metric_subset(result.task_metrics),
        },
        "runtime_stage_metrics": dict(sorted((key, float(value)) for key, value in result.runtime_stage_metrics.items())),
        "top_sidecars": sidecar_rows[:20],
        "top_manifests": manifest_rows[:20],
        "top_telemetry": telemetry_rows[:20],
        "sidecar_totals": sidecar_totals,
        "manifest_totals": manifest_totals,
        "persistence_profiles": _persistence_profile_readout(file_rows),
        "next_target": _recommend_next_target(sidecar_totals),
    }

    _write_json(bundle_dir / "summary.json", summary)
    _write_markdown(bundle_dir / "summary.md", _build_markdown_summary(summary))
    _write_csv(bundle_dir / "file_sizes.csv", file_rows)
    _write_csv(bundle_dir / "sidecar_sizes.csv", sidecar_rows)
    _write_csv(bundle_dir / "manifest_sizes.csv", manifest_rows)
    return bundle_dir


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a StateBus v2 smoke lane and write a mounted runtime persistence breakdown bundle."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=_default_output_root(),
        help="mounted diagnostics output root",
    )
    parser.add_argument(
        "--suite-id",
        default="statebus-v2-runtime-persistence-breakdown",
        help="bundle prefix",
    )
    parser.add_argument(
        "--task-id",
        default="smoke-task",
        help="smoke task id",
    )
    parser.add_argument(
        "--layer-name",
        default="L3-cold-start",
        help="smoke layer name",
    )
    parser.add_argument(
        "--handoff-mode",
        choices=("structured_collaboration", "text_collaboration"),
        default="structured_collaboration",
        help="role handoff mode",
    )
    parser.add_argument(
        "--structured-control-enabled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="whether structured control plane is enabled",
    )
    parser.add_argument(
        "--semantic-pruning-enabled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="whether semantic pruning is enabled",
    )
    parser.add_argument(
        "--replay-enabled",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="whether replay is enabled for this smoke lane",
    )
    parser.add_argument(
        "--multi-attempt-enabled",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="whether multi-attempt executor recovery is enabled",
    )
    parser.add_argument(
        "--force-first-attempt-trap",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="whether the first attempt should trap to exercise fallback",
    )
    parser.add_argument(
        "--role-path-mode",
        choices=("deterministic", "api"),
        default="deterministic",
        help="role path mode",
    )
    parser.add_argument(
        "--embedding-mode",
        choices=("deterministic", "local"),
        default="deterministic",
        help="embedding mode",
    )
    parser.add_argument(
        "--seed-replay-memory",
        action="store_true",
        help="seed dev-only replay memory during smoke",
    )
    parser.add_argument(
        "--history-runtime-root",
        type=Path,
        action="append",
        default=[],
        help="prior runtime root to use as history input; can be repeated",
    )
    return parser


def main(argv: list[str] | None = None) -> Path:
    parser = _build_parser()
    args = parser.parse_args(argv)
    bundle_dir = build_runtime_persistence_breakdown_bundle(
        output_root=args.output_root,
        suite_id=args.suite_id,
        task_id=args.task_id,
        layer_name=args.layer_name,
        handoff_mode=args.handoff_mode,
        structured_control_enabled=bool(args.structured_control_enabled),
        semantic_pruning_enabled=bool(args.semantic_pruning_enabled),
        replay_enabled=bool(args.replay_enabled),
        multi_attempt_enabled=bool(args.multi_attempt_enabled),
        force_first_attempt_trap=bool(args.force_first_attempt_trap),
        role_path_mode=args.role_path_mode,
        embedding_mode=args.embedding_mode,
        seed_replay_memory=bool(args.seed_replay_memory),
        history_runtime_roots=tuple(args.history_runtime_root),
    )
    print(
        stable_json_dumps(
            {
                "bundle_dir": str(bundle_dir),
                "summary_json": str(bundle_dir / "summary.json"),
                "summary_markdown": str(bundle_dir / "summary.md"),
                "sidecar_sizes_csv": str(bundle_dir / "sidecar_sizes.csv"),
                "manifest_sizes_csv": str(bundle_dir / "manifest_sizes.csv"),
            }
        )
    )
    return bundle_dir


if __name__ == "__main__":
    main()
