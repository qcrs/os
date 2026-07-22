#!/usr/bin/env python3
"""Create a compact memory experiment summary for presentation slides."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "task" / "result"
os.environ.setdefault("MPLCONFIGDIR", str(OUT_DIR / ".matplotlib"))

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402


MEMORY_COLOR = "#2F6FED"
NO_MEMORY_COLOR = "#9AA1AA"
REDUCTION_COLOR = "#F28C28"
TRACK_COLOR = "#E5E7EB"
TEXT_COLOR = "#111827"
MUTED_COLOR = "#64748B"
BACKGROUND_COLOR = "#F1F5F9"


def load_hit_rates() -> list[dict]:
    path = OUT_DIR / "memory_reuse_rates.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [row for row in rows if row.get("has_planner_validation")]


def load_performance() -> dict[str, dict]:
    path = OUT_DIR / "memory_performance_avg.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["group"]: row for row in csv.DictReader(handle)}


def draw_hit_rates(ax, rows: list[dict]) -> None:
    labels = [f"{row['case']} {row['group'].replace('+Mem', '')}" for row in rows]
    values = [float(row["validated_hit_rate"]) for row in rows]
    positions = list(range(len(rows)))

    ax.set_title("Memory Hit Rate", loc="left", fontsize=15, fontweight="bold", pad=16)
    ax.barh(positions, [1.0] * len(rows), color=TRACK_COLOR, height=0.34)
    ax.barh(positions, values, color=MEMORY_COLOR, height=0.34)
    ax.set_yticks(positions, labels)
    ax.set_xlim(0, 1.62)
    ax.invert_yaxis()
    ax.xaxis.set_visible(False)
    ax.tick_params(axis="y", length=0, labelsize=10, pad=8)

    for index, row in enumerate(rows):
        value = float(row["validated_hit_rate"])
        ax.text(
            min(value + 0.03, 1.04),
            index,
            f"{value:.0%}",
            va="center",
            fontsize=10,
            fontweight="bold",
            color=TEXT_COLOR,
        )
        ax.text(
            1.2,
            index,
            f"saved {row['research_subqueries_saved']} queries",
            va="center",
            fontsize=9.5,
            fontweight="bold",
            color=REDUCTION_COLOR,
        )

    for spine in ax.spines.values():
        spine.set_visible(False)


def draw_metric_card(
    ax,
    *,
    title: str,
    pairs: list[tuple[str, float, float]],
    formatter,
) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    card = FancyBboxPatch(
        (0.01, 0.04),
        0.98,
        0.92,
        boxstyle="round,pad=0.012,rounding_size=0.025",
        linewidth=1,
        edgecolor="#E2E8F0",
        facecolor="white",
        transform=ax.transAxes,
    )
    ax.add_patch(card)
    ax.text(
        0.06,
        0.78,
        title,
        fontsize=15,
        fontweight="bold",
        color=TEXT_COLOR,
        transform=ax.transAxes,
    )

    for y, (label, base, memory) in zip((0.52, 0.27), pairs):
        reduction = (base - memory) / base * 100
        marker = "↓" if reduction >= 0 else "↑"
        ax.text(
            0.06,
            y,
            label,
            fontsize=11,
            fontweight="bold",
            color=MUTED_COLOR,
            va="center",
            transform=ax.transAxes,
        )
        ax.text(
            0.25,
            y,
            formatter(base),
            fontsize=12,
            color=NO_MEMORY_COLOR,
            va="center",
            transform=ax.transAxes,
        )
        ax.text(
            0.45,
            y,
            "→",
            fontsize=15,
            color=MUTED_COLOR,
            va="center",
            transform=ax.transAxes,
        )
        ax.text(
            0.53,
            y,
            formatter(memory),
            fontsize=12,
            fontweight="bold",
            color=MEMORY_COLOR,
            va="center",
            transform=ax.transAxes,
        )
        ax.text(
            0.78,
            y,
            f"{marker} {abs(reduction):.1f}%",
            fontsize=12,
            fontweight="bold",
            color=REDUCTION_COLOR,
            va="center",
            transform=ax.transAxes,
        )


def main() -> None:
    hit_rows = load_hit_rates()
    performance = load_performance()

    time_pairs = [
        (
            "Text",
            float(performance["Text / No Memory"]["avg_elapsed_s"]),
            float(performance["Text / Memory"]["avg_elapsed_s"]),
        ),
        (
            "Struct",
            float(performance["Structured / No Memory"]["avg_elapsed_s"]),
            float(performance["Structured / Memory"]["avg_elapsed_s"]),
        ),
    ]
    token_pairs = [
        (
            "Text",
            float(performance["Text / No Memory"]["avg_total_tokens"]),
            float(performance["Text / Memory"]["avg_total_tokens"]),
        ),
        (
            "Struct",
            float(performance["Structured / No Memory"]["avg_total_tokens"]),
            float(performance["Structured / Memory"]["avg_total_tokens"]),
        ),
    ]

    fig = plt.figure(figsize=(13.5, 5.4), facecolor=BACKGROUND_COLOR)
    grid = fig.add_gridspec(
        2,
        2,
        width_ratios=(2, 3),
        height_ratios=(1, 1),
        left=0.07,
        right=0.98,
        top=0.91,
        bottom=0.10,
        wspace=0.13,
        hspace=0.10,
    )

    hit_ax = fig.add_subplot(grid[:, 0])
    hit_ax.set_facecolor(BACKGROUND_COLOR)
    draw_hit_rates(hit_ax, hit_rows)

    time_ax = fig.add_subplot(grid[0, 1])
    draw_metric_card(
        time_ax,
        title="Execution Time",
        pairs=time_pairs,
        formatter=lambda value: f"{value:.1f}s",
    )

    token_ax = fig.add_subplot(grid[1, 1])
    draw_metric_card(
        token_ax,
        title="Total Tokens",
        pairs=token_pairs,
        formatter=lambda value: f"{value / 1000:.1f}k",
    )

    output = OUT_DIR / "memory_experiment_summary.png"
    fig.savefig(output, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
