from __future__ import annotations

import json
from pathlib import Path
import pytest

import statebus.benchmark.memory_ablation as p4


def _load(root: Path, name: str):
    return json.loads((root / name).read_text(encoding="utf-8"))


def test_memory_ablation_closes_six_runtime_owned_matched_pairs(
    tmp_path: Path,
) -> None:
    root = tmp_path / "p4"
    result = p4.run_memory_ablation(output_root=root)

    rows = _load(root, "rows.json")
    producers = _load(root, "producer_rows.json")
    denominator = _load(root, "denominator.json")
    metrics = _load(root, "metrics.json")
    acceptance = _load(root, "acceptance.json")

    assert result["ok"] is True
    assert acceptance["status"] == "passed"
    assert len(producers) == 2
    assert all(row["denominator_eligible"] is False for row in producers)
    assert all(row["provider_boundary_call_count"] == 1 for row in producers)
    assert len(list(root.glob("runtime/*/measured/*/*/g5c-c0/manifest.json"))) == 12
    assert len(list(root.glob("runtime/*/measured/*/*/g5c-c1/manifest.json"))) == 12
    assert len(rows) == 12
    assert denominator == {
        **denominator,
        "planned_pairs": 6,
        "closed_pairs": 6,
        "rejected_pairs": 0,
        "incomplete_pairs": 0,
        "planned_measured_rows": 12,
        "observed_measured_rows": 12,
        "failed_measured_rows": 0,
        "producer_rows": 2,
        "producer_rows_excluded": True,
        "arithmetic_closed": True,
        "provider_pairing_arithmetic_closed": True,
    }

    by_pair: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_pair.setdefault(row["pair_id"], []).append(row)
    assert len(by_pair) == 6
    for group in by_pair.values():
        assert {row["variant"] for row in group} == set(p4.VARIANTS)
        assert len({row["task_contract_hash"] for row in group}) == 1
        assert len({tuple(row["input_lineage_hashes"]) for row in group}) == 1
        assert len({row["quality_contract_hash"] for row in group}) == 1
        assert len({row["deterministic_seed"] for row in group}) == 1
        assert len({row["current_value"] for row in group}) == 1
        assert len({row["source_payload_sha256"] for row in group}) == 1

    baseline_rows = [row for row in rows if row["variant"] == "memory_off"]
    replay_rows = [row for row in rows if row["variant"] == "validated_replay"]
    assert all(row["provider_boundary_call_count"] == 1 for row in baseline_rows)
    assert all(row["provider_boundary_call_count"] == 0 for row in replay_rows)
    assert all(row["candidate"] for row in replay_rows)
    assert all(row["compatible"] for row in replay_rows)
    assert all(row["policy_approved"] for row in replay_rows)
    assert all(row["actual_use"] for row in replay_rows)
    assert all(row["validated_replay"] for row in replay_rows)
    assert all(row["current_input_recomputed"] for row in replay_rows)
    assert all(row["quality_evidence"]["passed"] for row in replay_rows)
    assert {row["behavioral_effect"] for row in replay_rows} == {
        "changed",
        "no_effect",
    }
    assert all(
        row["behavioral_effect"] == row["expected_behavioral_effect"]
        for row in replay_rows
    )

    assert metrics["provider_boundary_calls"] == {
        "status": "observed",
        "memory_off": 6,
        "validated_replay": 0,
    }
    assert metrics["provider_work_avoided"] == {
        "status": "unsupported",
        "value": None,
        "reason": "provider_work_units_not_observed",
    }
    negative_controls = json.loads(
        (root / "negative_controls.json").read_text(encoding="utf-8")
    )
    assert len(negative_controls) == 3
    assert all(
        item["terminal_status"] == "policy_reject"
        and item["fail_closed"] is True
        and item["headline_denominator"] is False
        for item in negative_controls
    )
    assert metrics["verified_recipe_work_avoided"]["status"] == "observed"
    assert metrics["verified_recipe_work_avoided"]["value"] == 6
    assert all(
        row["recipe_step_status"] == "skipped_generation"
        and row["skipped_generation_step_count"] == 1
        and row["skipped_provider_call_count"] == 1
        and row["skip_evidence"]["status"] == "observed"
        for row in replay_rows
    )
    for name in (
        "hydration_bytes_avoided",
        "embedding_work_avoided",
        "rerank_work_avoided",
        "compatibility_work_avoided",
        "exact_replay",
    ):
        assert metrics[name]["status"] == "unsupported"
        assert metrics[name]["value"] is None

    timing = metrics["timing_accounting"]
    assert timing["paired_comparison_status"] == "observed"
    assert timing["producer_inclusive_replay_cost_ms"] == pytest.approx(
        sum(row["runtime_elapsed_ms"] for row in producers + replay_rows)
    )
    for row in rows + producers:
        events = row["runtime_phase_events"]
        persisted = [
            json.loads(line) for line in
            (Path(row["runtime_root"]) / "telemetry/runtime_events.jsonl").read_text().splitlines()
        ]
        assert events == [event for event in persisted if event["event_type"] == "RUNTIME_PHASE_TIMING"]
        phases = {event["payload"]["phase"] for event in events}
        assert {
            "execution_input_hydration", "transform_execution", "transform_recompute",
            "quality_validation", "transform_verified_materialization", "attempt_result_admission", "memory_commit",
        } <= phases
        assert all(event["payload"]["status"] == "returned" for event in events)
        if row in replay_rows:
            assert {
                "memory_lookup_including_compatibility", "memory_authorization_and_hydration", "memory_read_verification",
            } <= phases
            executor_calls = [
                event for event in events if event["payload"]["phase"] == "provider_invocation"
                and event["step_id"] == row["memory_consumption_receipt"]["consumer_step_id"]
            ]
            assert not executor_calls


def test_failed_replay_variant_is_accounted_but_never_closes_pair(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        p4,
        "FAMILY_CONFIGS",
        (
            {
                "family_id": "cross_period_financial",
                "task_family": "financial_report_analysis",
                "base_value": 1_000.0,
                "no_effect_rounds": (),
            },
        ),
    )
    real_run_runtime = p4._run_runtime

    def fail_replay(request):
        if request.task_id.endswith(":validated_replay"):
            raise RuntimeError("injected_replay_failure")
        return real_run_runtime(request)

    monkeypatch.setattr(p4, "_run_runtime", fail_replay)
    root = tmp_path / "failed-p4"
    result = p4.run_memory_ablation(output_root=root, rounds_per_family=1)
    denominator = _load(root, "denominator.json")
    failures = _load(root, "failures.json")

    assert result["ok"] is False
    assert denominator["planned_pairs"] == 1
    assert denominator["closed_pairs"] == 0
    assert denominator["incomplete_pairs"] == 1
    assert denominator["observed_measured_rows"] == 1
    assert denominator["failed_measured_rows"] == 1
    assert denominator["arithmetic_closed"] is True
    assert failures[-1]["variant"] == "validated_replay"
    assert failures[-1]["error"] == "RuntimeError:injected_replay_failure"
    timing = _load(root, "metrics.json")["timing_accounting"]
    assert failures[-1]["runtime_elapsed_ms"] > 0
    assert timing["replay_total_ms"] == failures[-1]["runtime_elapsed_ms"]
    assert timing["lanes"]["validated_replay"]["failed_observed_ms"] == timing["replay_total_ms"]
    assert timing["producer_inclusive_replay_cost_ms"] == timing["producer_setup_ms"] + timing["replay_total_ms"]
    assert timing["paired_comparison_status"] == "unsupported"
    assert timing["break_even_reuse_count"]["value"] is None


def test_failed_producer_cost_is_retained_without_inventing_unstarted_lane_times(monkeypatch, tmp_path: Path) -> None:
    def fail_producer(request):
        raise RuntimeError("injected_producer_failure")

    monkeypatch.setattr(p4, "_run_runtime", fail_producer)
    root = tmp_path / "failed-producers"
    result = p4.run_memory_ablation(output_root=root, rounds_per_family=1)
    failures = _load(root, "failures.json")
    timing = _load(root, "metrics.json")["timing_accounting"]
    assert not result["ok"]
    assert timing["producer_setup_ms"] == sum(
        row["runtime_elapsed_ms"] for row in failures if row["row_scope"] == "producer"
    )
    assert timing["producer_setup_ms"] > 0
    for lane in timing["lanes"].values():
        assert lane["attempted_count"] == 0
        assert lane["not_started_count"] == 2
        assert lane["total_ms"] is None
    assert timing["producer_inclusive_replay_cost_ms"] is None
    assert timing["break_even_reuse_count"]["value"] is None
    assert _load(root, "denominator.json")["arithmetic_closed"]


def test_row_write_failure_is_counted_once_and_keeps_completed_runtime_cost(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(p4, "FAMILY_CONFIGS", p4.FAMILY_CONFIGS[:1])
    write_json = p4._write_json

    def fail_baseline_row(path, payload):
        if path.name == "measurement_row.json" and path.parent.name == "memory_off":
            raise OSError("injected_row_write_failure")
        write_json(path, payload)

    monkeypatch.setattr(p4, "_write_json", fail_baseline_row)
    root = tmp_path / "failed-write"
    result = p4.run_memory_ablation(output_root=root, rounds_per_family=1)
    denominator = _load(root, "denominator.json")
    failures = _load(root, "failures.json")
    metrics = _load(root, "metrics.json")
    assert not result["ok"]
    assert denominator["observed_measured_rows"] == 1
    assert denominator["failed_measured_rows"] == 1
    assert denominator["arithmetic_closed"]
    assert failures[0]["error"] == "OSError:injected_row_write_failure"
    assert failures[0]["runtime_elapsed_ms"] > 0
    assert metrics["timing_accounting"]["baseline_total_ms"] == failures[0]["runtime_elapsed_ms"]
    assert metrics["provider_boundary_calls"]["memory_off"] == 1
    assert metrics["timing_accounting"]["break_even_reuse_count"]["value"] is None


@pytest.mark.parametrize("missing", [None, float("nan"), float("inf"), -1, False, "12"])
def test_missing_or_invalid_elapsed_is_not_zero_filled(missing) -> None:
    cost = p4._elapsed_accounting([
        {"runtime_elapsed_ms": 5.0, "terminal_status": "success"},
        {"runtime_elapsed_ms": missing, "terminal_status": "success"},
    ])
    assert cost["status"] == "unsupported"
    assert cost["observed_subtotal_ms"] == 5.0
    assert cost["missing_timing_count"] == 1
    assert cost["total_ms"] is None
    assert cost["mean_ms"] is None


def test_incomplete_pairs_cannot_produce_optimistic_break_even() -> None:
    metrics = p4._metrics(
        rows=[
            {"variant": "memory_off", "terminal_status": "success", "runtime_elapsed_ms": 100},
            {"variant": "validated_replay", "terminal_status": "success", "runtime_elapsed_ms": 10},
        ],
        producer_rows=[{"terminal_status": "success", "runtime_elapsed_ms": 20}],
        failures=[], pair_projection={}, denominator={"planned_pairs": 2, "closed_pairs": 1},
    )
    timing = metrics["timing_accounting"]
    assert timing["status"] == "observed"
    assert timing["paired_comparison_status"] == "unsupported"
    assert timing["break_even_reuse_count"]["value"] is None
