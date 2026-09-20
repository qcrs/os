from __future__ import annotations

import json
from pathlib import Path

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
    assert metrics["provider_work_avoided"]["status"] == "observed"
    assert metrics["provider_work_avoided"]["value"] == 6
    assert metrics["verified_recipe_work_avoided"] == {
        "status": "unsupported",
        "value": None,
        "reason": "recipe_step_skip_not_observed",
    }
    for name in (
        "hydration_bytes_avoided",
        "embedding_work_avoided",
        "rerank_work_avoided",
        "compatibility_work_avoided",
        "exact_replay",
    ):
        assert metrics[name]["status"] == "unsupported"
        assert metrics[name]["value"] is None


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
