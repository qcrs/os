from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.runner import (
    _aggregate_mode_runs,
    _build_report,
    _write_compare_csv,
    _write_message_breakdown_csv,
    _build_message_sizes_md,
)
from scripts.run_v3_api_repeat3_suite import (
    OPEN_PACKS,
    V3_PACKS,
    _summarize_open_pack,
    _summarize_pack,
    _summary_md,
)


def _rewrite_benchmark_dir(bench_dir: Path) -> None:
    result_path = bench_dir / "benchmark_results.json"
    if not result_path.exists():
        return
    result = json.loads(result_path.read_text(encoding="utf-8"))
    pack_type = str(result.get("manifest", {}).get("task_pack_type", "ad_hoc"))
    mode_runs = result.get("mode_runs", {})
    result["summary"] = {
        mode: _aggregate_mode_runs(runs, pack_type=pack_type) for mode, runs in mode_runs.items()
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    _write_compare_csv(bench_dir / "benchmark_compare.csv", result)
    _write_message_breakdown_csv(bench_dir / "benchmark_message_breakdown.csv", result)
    (bench_dir / "benchmark_message_sizes.md").write_text(_build_message_sizes_md(result), encoding="utf-8")
    (bench_dir / "benchmark_report.md").write_text(_build_report(result), encoding="utf-8")


def _rewrite_suite_summary(suite_dir: Path) -> None:
    summaries: list[dict[str, object]] = []
    for pack in V3_PACKS:
        bench_dir = suite_dir / "benchmarks" / pack
        if (bench_dir / "benchmark_results.json").exists():
            summaries.append(_summarize_pack(out_dir=suite_dir, pack=pack))
    for pack in OPEN_PACKS:
        open_dir = suite_dir / "open_surfaces" / pack
        if (open_dir / "open_results.json").exists():
            summaries.append(_summarize_open_pack(out_dir=open_dir, pack=pack))

    logs = sorted((suite_dir / "logs").glob("*.log"))
    checks = [
        {"label": path.stem, "returncode": 0, "log_path": str(path.relative_to(suite_dir))}
        for path in logs
    ]

    args = SimpleNamespace(
        llm_config="reused-existing-results",
        embedding_model="reused-existing-results",
        executor_transport="reused-existing-results",
    )
    (suite_dir / "SUMMARY.md").write_text(
        _summary_md(out_dir=suite_dir, args=args, checks=checks, summaries=summaries),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Rewrite benchmark reports/csvs from existing benchmark_results.json files.")
    parser.add_argument("path", type=Path, help="Benchmark directory or suite directory.")
    args = parser.parse_args()

    target = args.path.resolve()
    if (target / "benchmark_results.json").exists():
        _rewrite_benchmark_dir(target)
        return
    bench_root = target / "benchmarks"
    if bench_root.exists():
        for bench_dir in sorted(bench_root.iterdir()):
            if bench_dir.is_dir():
                _rewrite_benchmark_dir(bench_dir)
        _rewrite_suite_summary(target)
        return
    raise SystemExit(f"unsupported path: {target}")


if __name__ == "__main__":
    main()
