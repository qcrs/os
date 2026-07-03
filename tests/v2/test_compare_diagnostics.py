from __future__ import annotations

import json
from pathlib import Path

from scripts.v2_diagnostics.compare_diagnostics import build_compare_diagnostics_bundle, main as compare_diagnostics_main
from v2.benchmark.comparator_runner import compare_fixed_answer_with_external
from v2.benchmark.fixed_answer_runner import load_fixed_answer_family, run_fixed_answer_internal_carrier_compare_suite


def test_compare_diagnostics_bundle_reports_fairness_and_runtime(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    compare_report = compare_fixed_answer_with_external(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        role_path_modes=("deterministic",),
        statebus_mode="cold-start",
    )

    bundle_dir = build_compare_diagnostics_bundle(
        compare_suite_report_path=Path(compare_report.report_path),
        output_root=tmp_path / "diagnostics",
        family_dir=Path("v2/benchmark/samples/fixed_answer_family"),
    )

    summary = json.loads((bundle_dir / "summary.json").read_text(encoding="utf-8"))
    fairness = summary["fairness"]
    text_lane = summary["text_lane"]
    runtime = summary["runtime"]

    assert fairness["suite_verdict"] == "dev_fixed_answer_valid"
    assert fairness["mode_results"][0]["invalid_reason"] == ""
    assert fairness["mode_results"][0]["failed_gates"] == []
    assert text_lane["suite_verdict"] == "reasonable_for_debug_not_formal"
    assert runtime["suite_verdict"] == "runtime_non_llm_overhead_dominates"
    assert runtime["mode_results"][0]["suite_summary"]["dominant_gap"] == "runtime_non_llm_overhead"
    case_row = runtime["mode_results"][0]["case_rows"][0]
    assert "persist_and_reload_stage_ms" in case_row
    assert "codeact_execution_stage_ms" in case_row
    assert "runtime_driver_stage_ms" in case_row
    assert "executor_state_machine_stage_ms" in case_row
    assert "telemetry_emit_stage_ms" in case_row
    assert "estimated_unbucketed_non_llm_ms" in case_row
    assert "workspace_input_bundle_reused_count" in case_row
    assert runtime["mode_results"][0]["suite_summary"]["aggregate_bucket_totals"]["persist_and_reload_stage_ms_total"] >= 0.0
    assert runtime["mode_results"][0]["suite_summary"]["aggregate_bucket_totals"]["observed_bucket_sum_stage_ms_total"] >= 0.0
    assert (
        runtime["mode_results"][0]["suite_summary"]["cross_cutting_observation_totals"][
            "telemetry_event_write_count_total"
        ]
        >= 1
    )
    assert (bundle_dir / "summary.md").exists()
    assert (bundle_dir / "case_matrix.csv").exists()


def test_compare_diagnostics_cli_analyzes_existing_report(
    tmp_path: Path,
    capsys,
) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    compare_report = compare_fixed_answer_with_external(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        role_path_modes=("deterministic",),
        statebus_mode="cold-start",
    )

    bundle_dir = compare_diagnostics_main(
        [
            "--compare-suite-report",
            str(compare_report.report_path),
            "--output-root",
            str(tmp_path / "diagnostics"),
            "--family-dir",
            "v2/benchmark/samples/fixed_answer_family",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert Path(payload["bundle_dir"]) == bundle_dir
    assert Path(payload["summary_json"]).exists()
    assert Path(payload["summary_markdown"]).exists()


def test_compare_diagnostics_bundle_supports_internal_carrier_compare(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    compare_report = run_fixed_answer_internal_carrier_compare_suite(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
    )

    bundle_dir = build_compare_diagnostics_bundle(
        compare_suite_report_path=Path(compare_report.report_path),
        output_root=tmp_path / "diagnostics",
        family_dir=Path("v2/benchmark/samples/fixed_answer_family"),
    )
    summary = json.loads((bundle_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["fairness"]["suite_verdict"] == "internal_carrier_single_variable_valid"
    assert summary["text_lane"]["suite_verdict"] == "same_mainline_carrier_only"
    assert summary["runtime"]["suite_verdict"] == "carrier_runtime_delta_profiled"
