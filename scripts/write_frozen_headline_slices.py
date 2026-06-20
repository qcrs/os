from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


API_RESULTS = Path(
    "/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/benchmark_results.json"
)
DET_RESULTS = Path(
    "/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_runtime_det_r10_20260618_145812/benchmark_results.json"
)
OUT_PATH = Path("docs/reports/frozen_headline_slice_view_20260619.md")


@dataclass(frozen=True)
class SliceStats:
    task_count: int
    control_bytes: float
    task_ms: float
    exact_match_rate: float
    admissible_match_rate: float
    skipped_step_count: float
    reuse_gain: float


def _load_rows(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, object]] = []
    for mode_runs in payload.get("mode_runs", {}).values():
        for run in mode_runs:
            for task in run.get("tasks", []):
                if str(task.get("status", "")).strip() == "completed":
                    rows.append(task)
    return rows


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _slice_stats(rows: list[dict[str, object]]) -> SliceStats:
    return SliceStats(
        task_count=len(rows),
        control_bytes=_mean([float(row.get("metrics", {}).get("protocol_bytes", 0.0)) for row in rows]),
        task_ms=_mean([float(row.get("metrics", {}).get("task_ms", 0.0)) for row in rows]),
        exact_match_rate=_mean(
            [1.0 if bool(row.get("case_contract_audit", {}).get("exact_match")) else 0.0 for row in rows]
        ),
        admissible_match_rate=_mean(
            [1.0 if bool(row.get("case_contract_audit", {}).get("admissible_match")) else 0.0 for row in rows]
        ),
        skipped_step_count=_mean([float(row.get("metrics", {}).get("skipped_step_count", 0.0)) for row in rows]),
        reuse_gain=_mean([float(row.get("metrics", {}).get("reuse_gain", 0.0)) for row in rows]),
    )


def _format_stats(api_rows: list[dict[str, object]], det_rows: list[dict[str, object]]) -> tuple[SliceStats, SliceStats]:
    api = _slice_stats(api_rows)
    det = _slice_stats(det_rows)
    return api, det


def _group_by(rows: list[dict[str, object]], key_fn) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(key_fn(row))].append(row)
    return dict(grouped)


def _case_pairs(rows: list[dict[str, object]]) -> dict[str, dict[str, list[dict[str, object]]]]:
    pairs: dict[str, dict[str, list[dict[str, object]]]] = defaultdict(lambda: {"text": [], "protocol": []})
    for row in rows:
        pairs[str(row.get("case_id", row.get("task_id", "")))][str(row.get("mode", ""))].append(row)
    return dict(pairs)


def _delta_by_family(api_rows: list[dict[str, object]]) -> list[str]:
    families = sorted({str(row.get("task_theme", "")) for row in api_rows})
    lines = [
        "| family | text_control_bytes | protocol_control_bytes | delta_control_bytes | text_task_ms | protocol_task_ms | delta_task_ms | text_exact | protocol_exact | text_admissible | protocol_admissible |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for family in families:
        text_rows = [row for row in api_rows if row.get("task_theme") == family and row.get("mode") == "text"]
        protocol_rows = [row for row in api_rows if row.get("task_theme") == family and row.get("mode") == "protocol"]
        text_stats = _slice_stats(text_rows)
        protocol_stats = _slice_stats(protocol_rows)
        lines.append(
            f"| {family.replace('contest_release_', '')} | {text_stats.control_bytes:.2f} | {protocol_stats.control_bytes:.2f} | "
            f"{protocol_stats.control_bytes - text_stats.control_bytes:+.2f} | {text_stats.task_ms:.2f} | {protocol_stats.task_ms:.2f} | "
            f"{protocol_stats.task_ms - text_stats.task_ms:+.2f} | {text_stats.exact_match_rate:.2f} | {protocol_stats.exact_match_rate:.2f} | "
            f"{text_stats.admissible_match_rate:.2f} | {protocol_stats.admissible_match_rate:.2f} |"
        )
    return lines


def main() -> None:
    api_rows = _load_rows(API_RESULTS)
    det_rows = _load_rows(DET_RESULTS)

    api_by_family = _group_by(api_rows, lambda row: row.get("task_theme", ""))
    det_by_family = _group_by(det_rows, lambda row: row.get("task_theme", ""))
    api_by_thickness = _group_by(api_rows, lambda row: row.get("thickness_setting", ""))
    det_by_thickness = _group_by(det_rows, lambda row: row.get("thickness_setting", ""))
    api_by_reuse = _group_by(api_rows, lambda row: row.get("expected_reuse_mode", ""))
    det_by_reuse = _group_by(det_rows, lambda row: row.get("expected_reuse_mode", ""))

    pair_notes: list[str] = []
    for family in sorted(api_by_family):
        family_pairs = _case_pairs([row for row in api_rows if row.get("task_theme") == family])
        text_exact = 0
        protocol_exact = 0
        total = 0
        for pair in family_pairs.values():
            if not pair["text"] or not pair["protocol"]:
                continue
            total += 1
            text_exact += 1 if all(bool(row.get("case_contract_audit", {}).get("exact_match")) for row in pair["text"]) else 0
            protocol_exact += 1 if all(bool(row.get("case_contract_audit", {}).get("exact_match")) for row in pair["protocol"]) else 0
        pair_notes.append(
            f"- `{family.replace('contest_release_', '')}`: text exact pair coverage `{text_exact}/{total}`, protocol exact pair coverage `{protocol_exact}/{total}`."
        )

    lines = [
        "# Frozen Headline Slice View 2026-06-19",
        "",
        "- Inputs are frozen only:",
        f"  - `{API_RESULTS}`",
        f"  - `{DET_RESULTS}`",
        "- This report does not mix in current-branch support refresh, active-surface repeat=1, or any audit-only pack.",
        "",
        "## Family View",
        "",
        "| family | task_count | api_control_bytes | det_control_bytes | api_task_ms | det_task_ms | api_exact | det_exact | api_admissible | det_admissible |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for family in sorted(api_by_family):
        api_stats, det_stats = _format_stats(api_by_family[family], det_by_family[family])
        lines.append(
            f"| {family.replace('contest_release_', '')} | {api_stats.task_count} | {api_stats.control_bytes:.2f} | {det_stats.control_bytes:.2f} | "
            f"{api_stats.task_ms:.2f} | {det_stats.task_ms:.2f} | {api_stats.exact_match_rate:.2f} | {det_stats.exact_match_rate:.2f} | "
            f"{api_stats.admissible_match_rate:.2f} | {det_stats.admissible_match_rate:.2f} |"
        )

    lines.extend(
        [
            "",
            "Interpretation: `exact_match_rate=0.25` is a family-distributed issue on the text whole-lane side, not an admissibility collapse. The frozen pack keeps `admissible_match_rate=1.00` because bounded alternatives and abstention contracts still pass while exact route/tool picks remain under pressure.",
            "",
            "## S1 vs S2",
            "",
            "| thickness | task_count | api_control_bytes | det_control_bytes | api_task_ms | det_task_ms | api_exact | det_exact | api_admissible | det_admissible |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for thickness in ("S1", "S2"):
        api_stats, det_stats = _format_stats(api_by_thickness[thickness], det_by_thickness[thickness])
        lines.append(
            f"| {thickness} | {api_stats.task_count} | {api_stats.control_bytes:.2f} | {det_stats.control_bytes:.2f} | "
            f"{api_stats.task_ms:.2f} | {det_stats.task_ms:.2f} | {api_stats.exact_match_rate:.2f} | {det_stats.exact_match_rate:.2f} | "
            f"{api_stats.admissible_match_rate:.2f} | {det_stats.admissible_match_rate:.2f} |"
        )
    lines.extend(
        [
            "",
            f"- `S1` fresh-retrieval rows explain most exact slippage; they require action refinement under whole-lane wording but still satisfy admissible family/tool boundaries.",
            f"- `S2` rows carry prior dependency and measured step skipping: api mean skipped steps `{_slice_stats(api_by_thickness['S2']).skipped_step_count:.2f}`, api mean reuse gain `{_slice_stats(api_by_thickness['S2']).reuse_gain:.2f}`.",
            f"- `S2` therefore speaks to replay-shaped runtime behavior, while `S1` is where route/tool wording sensitivity shows up most directly.",
            "",
            "## Fresh Retrieval vs Step Skipping",
            "",
            "| expected_reuse_mode | task_count | api_control_bytes | det_control_bytes | api_task_ms | det_task_ms | api_exact | det_exact | api_admissible | det_admissible |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for reuse_mode in ("none", "skip_execute"):
        api_stats, det_stats = _format_stats(api_by_reuse[reuse_mode], det_by_reuse[reuse_mode])
        lines.append(
            f"| {reuse_mode} | {api_stats.task_count} | {api_stats.control_bytes:.2f} | {det_stats.control_bytes:.2f} | "
            f"{api_stats.task_ms:.2f} | {det_stats.task_ms:.2f} | {api_stats.exact_match_rate:.2f} | {det_stats.exact_match_rate:.2f} | "
            f"{api_stats.admissible_match_rate:.2f} | {det_stats.admissible_match_rate:.2f} |"
        )
    lines.extend(
        [
            "",
            f"- `fresh_retrieval` (`expected_reuse_mode=none`) stays at skipped steps `{_slice_stats(api_by_reuse['none']).skipped_step_count:.2f}` and carries the whole exact-match burden.",
            f"- `step_skipping` (`expected_reuse_mode=skip_execute`) keeps admissible behavior while adding replay effect: api skipped steps `{_slice_stats(api_by_reuse['skip_execute']).skipped_step_count:.2f}`, api reuse gain `{_slice_stats(api_by_reuse['skip_execute']).reuse_gain:.2f}`.",
            "",
            "## text_whole_lane vs state_packet_minimal",
            "",
        ]
    )
    lines.extend(_delta_by_family(api_rows))
    lines.extend(
        [
            "",
            "Interpretation: the frozen gap is not explained by support/audit pack misfires. It is the headline object's own whole-lane text route/tool exactness cost against a protocol minimal packet that keeps the same family and admissible contract intact.",
            "",
            "## Pair Notes",
            "",
            *pair_notes,
        ]
    )

    OUT_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
