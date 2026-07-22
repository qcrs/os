from __future__ import annotations

from v2.benchmark.experiment_design import (
    LaneCallbackResult,
    LaneObservation,
    balanced_lane_schedule,
    bootstrap_confidence_interval,
    run_balanced_serialized_experiment,
    summarize_balanced_lane_observations,
)
from v2.benchmark.control_transport_experiment import (
    run_control_transport_experiment,
)


def test_balanced_lane_schedule_alternates_abba_and_baab() -> None:
    schedule = balanced_lane_schedule(
        repeat_count=3,
        lane_a="statebus",
        lane_b="external",
    )

    assert [item.lane for item in schedule] == [
        "statebus", "external", "external", "statebus",
        "external", "statebus", "statebus", "external",
        "statebus", "external", "external", "statebus",
    ]
    assert [item.order_pattern for item in schedule] == [
        "ABBA", "ABBA", "ABBA", "ABBA",
        "BAAB", "BAAB", "BAAB", "BAAB",
        "ABBA", "ABBA", "ABBA", "ABBA",
    ]
    assert [item.global_index for item in schedule] == list(range(1, 13))


def test_balanced_summary_reports_intervals_and_allows_claim_only_after_three_blocks() -> None:
    schedule = balanced_lane_schedule(
        repeat_count=3,
        lane_a="statebus",
        lane_b="external",
    )
    observations = tuple(
        LaneObservation(
            spec=spec,
            elapsed_ms=(10.0 + spec.block_index if spec.lane == "statebus" else 30.0 + spec.block_index),
            quality_passed=True,
            component_ms=(("transport", 2.0 if spec.lane == "statebus" else 4.0),),
        )
        for spec in schedule
    )

    summary = summarize_balanced_lane_observations(
        observations,
        lane_a="statebus",
        lane_b="external",
        repeat_count=3,
    )

    assert summary["schedule_valid"] is True
    assert summary["serialized_execution"] is True
    assert summary["quality_gate_passed"] is True
    assert summary["lane_summaries"]["statebus"]["count"] == 6
    assert summary["lane_summaries"]["statebus"]["p90"] is not None
    assert summary["lane_summaries"]["external"]["p95"] is not None
    assert summary["component_summaries"]["statebus"]["transport"]["median"] == 2.0
    assert summary["paired_block_delta_a_minus_b_ms"]["median"] == -20.0
    assert summary["latency_superiority_claim_allowed"] is True


def test_balanced_summary_blocks_latency_claim_for_single_repeat_or_quality_failure() -> None:
    schedule = balanced_lane_schedule(repeat_count=1, lane_a="a", lane_b="b")
    observations = tuple(
        LaneObservation(
            spec=spec,
            elapsed_ms=1.0 if spec.lane == "a" else 10.0,
            quality_passed=spec.global_index != 1,
        )
        for spec in schedule
    )

    summary = summarize_balanced_lane_observations(
        observations,
        lane_a="a",
        lane_b="b",
        repeat_count=1,
    )

    assert summary["quality_gate_passed"] is False
    assert summary["latency_superiority_claim_allowed"] is False


def test_balanced_runner_invokes_exactly_one_callback_at_a_time_in_schedule_order() -> None:
    observed_order: list[tuple[int, str]] = []

    def callback(spec):
        observed_order.append((spec.global_index, spec.lane))
        return LaneCallbackResult(
            quality_passed=True,
            component_ms={"validation": float(spec.sequence_index)},
        )

    observations, summary = run_balanced_serialized_experiment(
        {"a": callback, "b": callback},
        lane_a="a",
        lane_b="b",
        repeat_count=2,
    )

    assert observed_order == [
        (spec.global_index, spec.lane)
        for spec in balanced_lane_schedule(repeat_count=2, lane_a="a", lane_b="b")
    ]
    assert len(observations) == 8
    assert summary["schedule_valid"] is True
    assert summary["latency_superiority_claim_allowed"] is False


def test_bootstrap_confidence_interval_is_deterministic() -> None:
    values = (1.0, 2.0, 3.0, 4.0, 5.0)

    first = bootstrap_confidence_interval(values, seed=17)
    second = bootstrap_confidence_interval(values, seed=17)

    assert first == second
    assert first[0] <= 3.0 <= first[1]


def test_control_transport_experiment_records_real_negotiation_and_text_frames(
    tmp_path,
) -> None:
    summary = run_control_transport_experiment(
        output_root=tmp_path / "transport-experiment",
        repeat_count=1,
    )

    assert summary["statistics"]["observation_count"] == 4
    assert summary["statistics"]["schedule_valid"] is True
    assert summary["carrier_latency_claim_allowed"] is False
    assert summary["end_to_end_latency_superiority_claim_allowed"] is False
    typed_audits = [
        audit
        for audit in summary["transport_audits"]
        if audit["carrier"] == "typed_protobuf"
    ]
    text_audits = [
        audit
        for audit in summary["transport_audits"]
        if audit["carrier"] == "utf8_text"
    ]
    assert len(typed_audits) == len(text_audits) == 2
    assert all(audit["negotiation_accepted"] is True for audit in typed_audits)
    assert all(audit["request_frame_count"] == 2 for audit in typed_audits)
    assert all(audit["response_frame_count"] == 5 for audit in typed_audits)
    assert all(audit["negotiation_performed"] is False for audit in text_audits)
    assert all(audit["request_frame_count"] == 1 for audit in text_audits)
    assert all(audit["response_frame_count"] == 4 for audit in text_audits)
    assert (tmp_path / "transport-experiment" / "summary.json").is_file()
