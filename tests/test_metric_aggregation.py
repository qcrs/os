from __future__ import annotations

from statebus.benchmark.metric_aggregation import finalize_case_telemetry_summary, bootstrap_mean_ci, holm_adjust, paired_deltas, project_metric_availability


def test_observed_prefix_hit_rate_uses_ratio_of_sums() -> None:
    summary = {
        "vllm_prefix_observed_hit_delta": 10.0,
        "vllm_prefix_observed_query_delta": 12.0,
        "vllm_prefix_observed_hit_rate": 1.4,
    }

    result = finalize_case_telemetry_summary(summary, ())

    assert result["vllm_prefix_observed_hit_rate"] == 10.0 / 12.0


def test_observed_prefix_hit_rate_is_zero_without_queries() -> None:
    summary = {
        "vllm_prefix_observed_hit_delta": 0.0,
        "vllm_prefix_observed_query_delta": 0.0,
        "vllm_prefix_observed_hit_rate": 2.0,
    }

    result = finalize_case_telemetry_summary(summary, ())

    assert result["vllm_prefix_observed_hit_rate"] == 0.0


def test_c2b_bootstrap_and_holm_are_frozen_and_deterministic() -> None:
    result = bootstrap_mean_ci([1.0, 2.0, 3.0], resamples=100, seed=2027)
    assert result["status"] == "observed"
    assert result["resamples"] == 100
    assert result["seed"] == 2027
    assert holm_adjust({"a": 0.01, "b": 0.02}) == {"a": 0.02, "b": 0.02}


def test_c2b_pairing_drops_unobserved_values_without_zero_estimation() -> None:
    left = [{"pair_key": "p1", "wall_time": 10}, {"pair_key": "p2", "wall_time": None}]
    right = [{"pair_key": "p1", "wall_time": 12}, {"pair_key": "p2", "wall_time": 9}]
    assert paired_deltas(left, right, key="wall_time") == [2.0]


def test_wire_bytes_diagnostic_is_not_promoted_to_metric() -> None:
    result = project_metric_availability(observed={
        "wire_bytes": {"status": "observed", "value": 1713, "source": "raw_send_or_recv_frame_observation"},
    })
    assert result["wire_bytes"] == {"status": "unsupported", "reason": "wire_bytes_not_observed"}


def test_wire_bytes_requires_canonical_observation_source() -> None:
    result = project_metric_availability(observed={
        "wire_bytes": {"status": "observed", "value": 1713, "source": "canonical_wire_observation"},
    })
    assert result["wire_bytes"]["status"] == "observed"


def test_c2c_matched_pair_projects_provider_work_avoided_and_deferred_metrics() -> None:
    pair = {
        "status": "eligible",
        "task_contract_hash": "task-contract",
        "input_lineage_hashes": ["input-lineage"],
        "quality_contract_hash": "quality-contract",
        "replay_memory_policy": "validated_replay",
        "quality_non_regression": {"passed": True},
        "source_receipt_hashes": ["provider", "skip", "admission"],
    }
    result = project_metric_availability(observed={
        "c2c_pairings": [pair],
        "c2c_denominator": {"arithmetic_closed": True},
    })
    assert result["provider_work_avoided"] == {
        "status": "observed",
        "value": 1,
        "eligible_matched_pair_count": 1,
        "source_receipt_hashes": ["admission", "provider", "skip"],
    }
    assert result["quality_non_regression"]["status"] == "observed"
    assert pair["task_contract_hash"] and pair["input_lineage_hashes"]
    assert pair["quality_contract_hash"] and pair["replay_memory_policy"]
    assert result["verified_recipe_work_avoided"]["status"] == "unsupported"
    assert result["verified_recipe_work_avoided"]["reason"] == "recipe_step_skip_deferred_to_c2"
    assert result["exact_replay"]["reason"] == "c2_exact_restore_not_implemented"


def test_c2c_missing_pair_or_receipt_remains_unsupported() -> None:
    result = project_metric_availability(observed={
        "c2c_pairings": [{"status": "rejected"}],
        "c2c_denominator": {"arithmetic_closed": True},
    })
    assert result["provider_work_avoided"]["status"] == "unsupported"
    assert result["provider_work_avoided"]["reason"] == "no_matched_baseline_or_runtime_skip_receipt"
    assert result["quality_non_regression"] == {
        "status": "unsupported",
        "reason": "no_matched_baseline",
    }
