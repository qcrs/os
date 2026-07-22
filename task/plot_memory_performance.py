#!/usr/bin/env python3
"""Plot memory vs no-memory performance averaged across tasks."""

from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
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


DATA_SOURCES = [
    {
        "task": "data_anas",
        "mode": "text",
        "memory": "No Memory",
        "path": ROOT / "task/data_anas/result/group1_comparison_no_memory.json",
        "protocol": "protocol_a",
    },
    {
        "task": "data_anas",
        "mode": "structured",
        "memory": "No Memory",
        "path": ROOT / "task/data_anas/result/group1_comparison_no_memory.json",
        "protocol": "protocol_b",
    },
    {
        "task": "data_anas",
        "mode": "text",
        "memory": "Memory",
        "path": ROOT / "task/data_anas/result/group1_comparison_memory.json",
        "protocol": "protocol_a",
    },
    {
        "task": "data_anas",
        "mode": "structured",
        "memory": "Memory",
        "path": ROOT / "task/data_anas/result/group1_comparison_memory.json",
        "protocol": "protocol_b",
    },
    {
        "task": "company_com",
        "mode": "text",
        "memory": "No Memory",
        "path": ROOT / "task/company_com/result/cdns10_perf_no_memory_text.json",
    },
    {
        "task": "company_com",
        "mode": "text",
        "memory": "Memory",
        "path": ROOT / "task/company_com/result/cdns10_perf_memory_text.json",
    },
    {
        "task": "company_com",
        "mode": "structured",
        "memory": "No Memory",
        "path": ROOT / "task/company_com/result/cdns10_perf_no_memory_structured.json",
    },
    {
        "task": "company_com",
        "mode": "structured",
        "memory": "Memory",
        "path": ROOT / "task/company_com/result/cdns10_perf_memory_structured.json",
    },
]


def load_record(source: dict) -> dict:
    data = json.loads(source["path"].read_text(encoding="utf-8"))
    if "protocol" in source:
        protocol = data[source["protocol"]]
        elapsed_s = protocol["stats"]["total_duration_s"]
        metrics = protocol["metrics"]
    else:
        elapsed_s = data["summary"]["elapsed_s"]
        metrics = data["summary"]["metrics"]

    return {
        "task": source["task"],
        "mode": source["mode"],
        "memory": source["memory"],
        "elapsed_s": float(elapsed_s),
        "total_tokens": int(metrics["total_tokens"]),
        "llm_calls": int(metrics.get("llm_calls", 0)),
    }


def mean(values: list[float]) -> float:
    return sum(values) / max(len(values), 1)


def plot_metric(
    *,
    rows: list[dict],
    metric: str,
    title: str,
    ylabel: str,
    value_formatter,
    output_name: str,
) -> Path:
    by_group = {row["group"]: row for row in rows}
    labels = ["Text", "Struct"]
    no_memory_values = [
        by_group["Text / No Memory"][metric],
        by_group["Structured / No Memory"][metric],
    ]
    memory_values = [
        by_group["Text / Memory"][metric],
        by_group["Structured / Memory"][metric],
    ]
    x = list(range(len(labels)))

    fig, ax = plt.subplots(figsize=(7.2, 4.8), constrained_layout=True)
    fig.patch.set_facecolor(BACKGROUND_COLOR)
    ax.set_facecolor("white")

    ax.set_title(title, fontsize=15, pad=14)
    ax.set_ylabel(ylabel)
    ax.set_xticks(x, labels)
    ax.set_xlim(-0.25, 1.25)
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.plot(
        x,
        no_memory_values,
        marker="o",
        markersize=9,
        linewidth=2.4,
        color=NO_MEMORY_COLOR,
        label="No Memory",
    )
    ax.plot(
        x,
        memory_values,
        marker="o",
        markersize=9,
        linewidth=2.4,
        color=MEMORY_COLOR,
        label="Memory",
    )

    all_values = no_memory_values + memory_values
    data_min = min(all_values)
    data_max = max(all_values)
    span = max(data_max - data_min, data_max * 0.1)
    ax.set_ylim(data_min - span * 0.55, data_max + span * 0.55)
    for point_x, no_memory, memory in zip(x, no_memory_values, memory_values):
        reduction = (no_memory - memory) / no_memory * 100
        ax.text(
            point_x,
            no_memory + span * 0.06,
            value_formatter(no_memory),
            ha="center",
            va="bottom",
            fontsize=9,
            color=NO_MEMORY_COLOR,
        )
        ax.text(
            point_x,
            memory - span * 0.11,
            value_formatter(memory),
            ha="center",
            va="bottom",
            fontsize=9,
            color=MEMORY_COLOR,
        )
        marker = "↓" if reduction >= 0 else "↑"
        ax.text(
            point_x,
            max(no_memory, memory) + span * 0.25,
            f"{marker} {abs(reduction):.1f}%",
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
            color=REDUCTION_COLOR,
        )

    ax.legend(frameon=False, ncols=2, loc="upper center")

    output_path = OUT_DIR / output_name
    fig.savefig(output_path, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    return output_path


def main() -> None:
    records = [load_record(source) for source in DATA_SOURCES if source["path"].exists()]

    grouped = defaultdict(list)
    for record in records:
        label = f"{record['mode'].title()} / {record['memory']}"
        grouped[label].append(record)

    preferred_order = [
        "Text / No Memory",
        "Text / Memory",
        "Structured / No Memory",
        "Structured / Memory",
    ]
    rows = []
    for label in preferred_order:
        items = grouped.get(label, [])
        if not items:
            continue
        rows.append({
            "group": label,
            "avg_elapsed_s": mean([item["elapsed_s"] for item in items]),
            "avg_total_tokens": mean([item["total_tokens"] for item in items]),
            "avg_llm_calls": mean([item["llm_calls"] for item in items]),
            "tasks": ",".join(sorted({item["task"] for item in items})),
        })

    csv_path = OUT_DIR / "memory_performance_avg.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["group", "avg_elapsed_s", "avg_total_tokens", "avg_llm_calls", "tasks"],
        )
        writer.writeheader()
        writer.writerows(rows)

    time_path = plot_metric(
        rows=rows,
        metric="avg_elapsed_s",
        title="Average Execution Time",
        ylabel="Seconds",
        value_formatter=lambda value: f"{value:.1f}s",
        output_name="memory_performance_time.png",
    )
    token_path = plot_metric(
        rows=rows,
        metric="avg_total_tokens",
        title="Average Total Tokens",
        ylabel="Tokens",
        value_formatter=lambda value: f"{value / 1000:.1f}k",
        output_name="memory_performance_tokens.png",
    )

    print(f"Wrote {time_path}")
    print(f"Wrote {token_path}")
    print(f"Wrote {csv_path}")
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
