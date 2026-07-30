from __future__ import annotations

from pathlib import Path

from scripts.experiments.engine_local_kv.run_engine_local_kv_mainline_suite import (
    DEFAULT_MANIFEST,
    load_suite_manifest,
    pair_records,
    render_report,
    summarize_suite,
)
from statebus.benchmark.engine_local_kv_tasks import load_compiled_cases


def test_ten_round_manifest_has_grouped_phase_order_and_metric_coverage() -> None:
    suite = load_suite_manifest(DEFAULT_MANIFEST)

    assert suite.phase_order == ("full_replay", "continuation")
    assert suite.parent_tokens == 4096
    assert suite.warmup_per_phase == 1
    assert [item.round_number for item in suite.tasks] == list(range(1, 11))
    assert [item.task.company for item in suite.tasks] == ["nova"] * 5 + ["orion"] * 5
    assert len({item.task.task_id for item in suite.tasks}) == 10
    assert all(item.task.document.is_file() for item in suite.tasks)


def test_dedicated_orion_parent_is_exactly_4096_tokens() -> None:
    compiled_path = DEFAULT_MANIFEST.parent / "compiled_cases.json"
    cases = load_compiled_cases(compiled_path)

    assert len(cases) == 1
    assert cases[0].definition.case_id == "kv-mainline-4k-orion"
    assert len(cases[0].parent_token_ids) == 4096
    assert len(cases[0].parent_token_ids) % cases[0].block_size == 0


def test_suite_aggregation_pairs_grouped_records_without_losing_order(
    tmp_path: Path,
) -> None:
    suite = load_suite_manifest(DEFAULT_MANIFEST)
    records = []
    for mode in suite.phase_order:
        for item in suite.tasks:
            records.append(
                _fake_record(
                    item.round_number,
                    item.task.task_id,
                    item.task.company,
                    item.task.metric,
                    mode,
                )
            )

    pairs = pair_records(records)
    summary = summarize_suite(
        run_id="fake-run",
        output_dir=tmp_path,
        suite=suite,
        records=records,
    )

    assert len(pairs) == 10
    assert [value["mode"] for value in records[:10]] == ["full_replay"] * 10
    assert [value["mode"] for value in records[10:]] == ["continuation"] * 10
    assert summary["aggregate"]["pair_count"] == 10
    assert summary["aggregate"]["quality_parity_count"] == 10
    assert summary["aggregate"]["consumer_output_token_parity_count"] == 10
    assert summary["aggregate"]["output_artifact_hash_parity_count"] == 10
    assert summary["aggregate"]["structured_artifact_core_parity_count"] == 10
    assert summary["aggregate"]["required_fact_parity_count"] == 10
    assert summary["aggregate"]["kv_proof_pass_count"] == 10
    assert summary["aggregate"]["fallback_count"] == 0
    assert (
        summary["aggregate"]["metrics"]["consumer_ttft_ms"]["positive_pair_count"] == 10
    )
    assert (
        summary["aggregate"]["metrics"]["computed_prefill_tokens"]["lane_p50_reduction"]
        > 0.8
    )
    report = render_report(summary)
    assert "先 10 个 `full_replay`，再 10 个 `continuation`" in report
    assert "显式 KV proof 通过：`10/10`" in report


def _fake_record(
    round_number: int,
    task_id: str,
    company: str,
    metric: str,
    mode: str,
) -> dict[str, object]:
    continuation = mode == "continuation"
    return {
        "round": round_number,
        "task_id": task_id,
        "company": company,
        "metric": metric,
        "mode": mode,
        "computed_prefill_tokens": 704 if continuation else 4800,
        "consumer_ttft_ms": 620.0 if continuation else 1600.0,
        "consumer_wall_ms": 6200.0 if continuation else 7100.0,
        "consumer_request_bytes": 3200 if continuation else 20000,
        "producer_client_wall_ms": 5000.0 if continuation else 4400.0,
        "producer_consumer_wall_ms": 11200.0 if continuation else 11700.0,
        "mainline_wall_ms": 30700.0 if continuation else 33800.0,
        "inherited_kv_tokens": 4096 if continuation else 0,
        "parent_tokens": 4096,
        "kv_store_ms": 2050.0 if continuation else 0.0,
        "kv_load_ms": 320.0 if continuation else 0.0,
        "kv_bytes_actual": 1073741824 if continuation else 0,
        "quality_floor_pass": True,
        "expected_facts": {
            "metric_name": metric,
            "value_q1": "1",
            "value_q2": "2",
            "value_q3": "3",
        },
        "output_payload": {
            "metric_name": metric,
            "value_q1": "1",
            "value_q2": "2",
            "value_q3": "3",
            "summary_text": "same",
        },
        "producer_logical_token_digest": f"producer-logical-{task_id}",
        "consumer_logical_token_digest": f"consumer-logical-{task_id}",
        "producer_output_token_digest": f"producer-output-{task_id}",
        "consumer_output_token_digest": f"consumer-output-{task_id}",
        "output_artifact_hash": f"artifact-{task_id}",
        "capture_count": int(continuation),
        "load_count": int(continuation),
        "connector_load_count": int(continuation),
        "fallback_count": 0,
        "release_calls": (
            [{"status": "released", "handle_id": f"handle-{task_id}"}]
            if continuation
            else []
        ),
    }
