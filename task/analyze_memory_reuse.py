#!/usr/bin/env python3
"""Extract and plot memory reuse metrics from experiment outputs."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "task" / "result"
OUT_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(OUT_DIR / ".matplotlib"))

import matplotlib.pyplot as plt  # noqa: E402

NO_MEMORY_COLOR = "#9AA1AA"
MEMORY_COLOR = "#2F6FED"
REDUCTION_COLOR = "#F28C28"
BACKGROUND_COLOR = "#F8FAFC"


EXPERIMENTS = [
    {
        "dataset": "data_anas",
        "case": "Titanic",
        "group": "Text+Mem",
        "path": ROOT / "task/data_anas/result/group1_comparison_memory.json",
        "protocol": "protocol_a",
    },
    {
        "dataset": "data_anas",
        "case": "Titanic",
        "group": "Struct+Mem",
        "path": ROOT / "task/data_anas/result/group1_comparison_memory.json",
        "protocol": "protocol_b",
    },
    {
        "dataset": "company_com",
        "case": "CDNS",
        "group": "Text+Mem",
        "path": ROOT / "task/company_com/result/cdns10_perf_memory_text_reuse.json",
    },
    {
        "dataset": "company_com",
        "case": "CDNS",
        "group": "Struct+Mem",
        "path": ROOT / "task/company_com/result/cdns10_perf_memory_structured_reuse.json",
    },
    {
        "dataset": "company_com",
        "case": "ETR",
        "group": "Text+Mem",
        "path": ROOT / "task/company_com/result/etr_perf_memory_text_reuse.json",
    },
    {
        "dataset": "company_com",
        "case": "ETR",
        "group": "Struct+Mem",
        "path": ROOT / "task/company_com/result/etr_perf_memory_structured_reuse.json",
    },
]


def load_items(spec: dict) -> tuple[list[dict], dict]:
    data = json.loads(spec["path"].read_text(encoding="utf-8"))
    if "protocol" in spec:
        protocol = data[spec["protocol"]]
        return protocol.get("per_round", []), protocol.get("metrics", {})
    return data.get("sessions", []), data.get("summary", {}).get("metrics", {})


def summarize(spec: dict) -> dict:
    items, metrics = load_items(spec)
    total = len(items)
    candidate_tasks = sum(bool(item.get("reused_memory_ids")) for item in items)
    validated_tasks = sum(bool(item.get("validated_memory_ids")) for item in items)
    memory_hits = sum(bool(item.get("memory_hit")) for item in items)
    reductions = sum(bool(item.get("reduced_research")) for item in items)
    has_validation = any("memory_validation" in item for item in items)

    metric_reductions = int(metrics.get("research_fanout_reduced", 0) or 0)
    metric_hits = int(metrics.get("memory_reuse_hits", 0) or 0)
    if not has_validation:
        if reductions == 0 and metric_reductions:
            reductions = metric_reductions
        if memory_hits == 0 and metric_hits:
            memory_hits = min(metric_hits, total)
        if validated_tasks == 0:
            validated_tasks = memory_hits
        if candidate_tasks == 0:
            candidate_tasks = memory_hits

    return {
        "dataset": spec["dataset"],
        "case": spec["case"],
        "group": spec["group"],
        "source_file": str(spec["path"].relative_to(ROOT)),
        "has_planner_validation": has_validation,
        "rate_source": "planner_validation" if has_validation else "legacy_metrics_inferred",
        "total_tasks": total,
        "candidate_tasks": candidate_tasks,
        "validated_memory_tasks": validated_tasks,
        "memory_hit_tasks": memory_hits,
        "reduced_research_tasks": reductions,
        "candidate_rate": candidate_tasks / total if total else 0.0,
        "validated_hit_rate": validated_tasks / total if total else 0.0,
        "memory_hit_rate": memory_hits / total if total else 0.0,
        "reduction_rate": reductions / total if total else 0.0,
        "candidate_to_validated_rate": validated_tasks / candidate_tasks if candidate_tasks else 0.0,
        "hit_to_reduction_rate": reductions / memory_hits if memory_hits else 0.0,
        "memory_reuse_hits_metric": metric_hits,
        "research_subqueries_saved": int(metrics.get("research_subqueries_saved", 0) or 0),
        "llm_calls": int(metrics.get("llm_calls", 0) or 0),
        "total_tokens": int(metrics.get("total_tokens", 0) or 0),
    }


def pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def plot_hit_rates(rows: list[dict]) -> Path:
    labels = [f"{row['case']} {row['group'].replace('+Mem', '')}" for row in rows]
    values = [row["validated_hit_rate"] for row in rows]
    y = list(range(len(rows)))

    fig, ax = plt.subplots(figsize=(8.6, 4.2), constrained_layout=True)
    fig.patch.set_facecolor(BACKGROUND_COLOR)
    ax.set_facecolor("white")
    ax.barh(y, [1.0] * len(rows), color="#E5E7EB", height=0.42)
    ax.barh(y, values, color=MEMORY_COLOR, height=0.42)

    ax.set_title("Memory Hit Rate", fontsize=15, pad=14)
    ax.set_yticks(y, labels)
    ax.set_xlim(0, 1.32)
    ax.invert_yaxis()
    ax.tick_params(axis="y", length=0, pad=10)
    ax.xaxis.set_visible(False)
    ax.grid(False)
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    for index, row in enumerate(rows):
        value = row["validated_hit_rate"]
        ax.text(
            min(value + 0.025, 1.03),
            index,
            pct(value),
            ha="left",
            va="center",
            fontsize=10,
            fontweight="bold",
            color="#111827",
        )
        ax.text(
            1.12,
            index,
            f"saved {row['research_subqueries_saved']} queries",
            ha="left",
            va="center",
            fontsize=10,
            fontweight="bold",
            color=REDUCTION_COLOR,
        )

    output = OUT_DIR / "memory_hit_rate.png"
    fig.savefig(output, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    return output


def plot_reuse_funnel(rows: list[dict]) -> Path:
    labels = [f"{row['case']}\n{row['group'].replace('+Mem', '')}" for row in rows]
    x = list(range(len(rows)))
    width = 0.26
    candidate = [row["candidate_rate"] for row in rows]
    validated = [row["validated_hit_rate"] for row in rows]
    reduced = [row["reduction_rate"] for row in rows]

    fig, ax = plt.subplots(figsize=(9.2, 4.9), constrained_layout=True)
    fig.patch.set_facecolor(BACKGROUND_COLOR)
    ax.set_facecolor("white")
    ax.bar([i - width for i in x], candidate, width, label="Candidates", color=NO_MEMORY_COLOR)
    ax.bar(x, validated, width, label="Planner validated", color=MEMORY_COLOR)
    ax.bar([i + width for i in x], reduced, width, label="Research reduced", color=REDUCTION_COLOR)

    ax.set_title("Memory Reuse Funnel", fontsize=15, pad=14)
    ax.set_ylabel("Rate")
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.set_major_formatter(lambda value, _: pct(value))
    ax.legend(frameon=False, ncols=3, loc="upper center")

    for i, row in enumerate(rows):
        if row["candidate_tasks"]:
            ax.text(
                i,
                min(row["validated_hit_rate"] + 0.04, 1.0),
                f"{row['candidate_to_validated_rate'] * 100:.0f}% conv.",
                ha="center",
                va="bottom",
                fontsize=9,
                color="#111827",
            )

    output = OUT_DIR / "memory_reuse_funnel.png"
    fig.savefig(output, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    return output


def main() -> None:
    rows = [summarize(spec) for spec in EXPERIMENTS if spec["path"].exists()]

    csv_path = OUT_DIR / "memory_reuse_rates.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    json_path = OUT_DIR / "memory_reuse_rates.json"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    # The validation plot is meaningful only for files generated after planner validation was added.
    validation_rows = [row for row in rows if row["has_planner_validation"]]
    hit_path = plot_hit_rates(validation_rows) if validation_rows else None
    funnel_path = plot_reuse_funnel(validation_rows) if validation_rows else None

    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")
    if hit_path:
        print(f"Wrote {hit_path}")
    if funnel_path:
        print(f"Wrote {funnel_path}")
    for row in rows:
        print(
            f"{row['case']} {row['group']}: "
            f"candidate={row['candidate_rate']:.1%}, "
            f"validated={row['validated_hit_rate']:.1%}, "
            f"reduced={row['reduction_rate']:.1%}, "
            f"saved={row['research_subqueries_saved']}"
        )


if __name__ == "__main__":
    main()
