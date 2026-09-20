from __future__ import annotations

from types import SimpleNamespace

from statebus.benchmark import semantic_holdout


def _case(task_id: str = "semantic-holdout-s1") -> SimpleNamespace:
    return SimpleNamespace(
        task_id=task_id,
        spec=SimpleNamespace(spec_hash="sha256:semantic-case"),
        sample=SimpleNamespace(scenario_tags=("narrative_only",)),
    )


def _summary_for_mode(mode: str) -> dict[str, object]:
    active = mode != "off"
    consumed = mode == "on"
    activation = {
        "component": "semantic_state",
        "requested_mode": mode,
        "effective_mode": mode,
        "producer_active": active,
        "consumer_active": consumed,
        "publish_count": 1 if active else 0,
        "consume_count": 1 if consumed else 0,
        "transfer_count": 1 if consumed else 0,
        "disable_reason": "" if mode == "on" else f"requested_{mode}",
    }
    selection = {
        "producer_pid": 10,
        "consumer_pid": 11,
        "selected_candidate_ids": ["candidate-1"],
    }
    return {
        "run_dir": f"/tmp/{mode}",
        "runtime_completed": True,
        "ok": True,
        "component_activation_receipts": {"semantic_state": activation},
        "telemetry": {
            "semantic_state_publish_count": 1.0 if active else 0.0,
            "semantic_state_consume_count": 1.0 if consumed else 0.0,
            "semantic_state_transfer_count": 1.0 if consumed else 0.0,
            "semantic_state_selected_bytes": 32.0 if consumed else 0.0,
        },
        "semantic_state_selections": {"state-1": selection} if consumed else {},
        "state_consumption_records": [{
            "operation": "cosine_topk_budget_pruning",
            "behavioral_effect": "changed",
            "selected_ids": ["candidate-1"],
            "downstream_ref_ids": ["evidence-1"],
        }] if consumed else [],
        "downstream_effects": {
            "state-1": {"behavioral_effect": "changed"}
        } if consumed else {},
        "state_release_reclaim_receipts": {"state-1": {"physical_reclaimed": True}}
        if active else {},
        "provider_invocation_events": [{"status": "observed"}],
    }


def test_semantic_state_ablation_closes_only_matched_three_variant_pairs(
    monkeypatch,
    tmp_path,
) -> None:
    case = _case()
    monkeypatch.setattr(semantic_holdout, "load_semantic_holdout_cases", lambda: (case,))

    def fake_run(case, *, case_root, semantic_state_mode, **kwargs):
        del case, case_root, kwargs
        return _summary_for_mode(semantic_state_mode)

    monkeypatch.setattr(semantic_holdout, "_run_adaptive_case", fake_run)
    summary = semantic_holdout.run_semantic_state_ablation(
        output_root=tmp_path,
        embedding_model_path="/models/embed",
        embedding_device="cpu",
        case_ids=(case.task_id,),
    )

    assert summary["ok"] is True
    assert summary["denominator"]["planned_pairs"] == 1
    assert summary["denominator"]["closed_pairs"] == 1
    rows = {row["variant"]: row for row in summary["rows"]}
    assert rows["off"]["semantic_consume_count"] == 0.0
    assert rows["on"]["semantic_consume_count"] == 1.0
    assert rows["consumer_off"]["semantic_publish_count"] == 1.0
    assert rows["consumer_off"]["semantic_consume_count"] == 0.0


def test_semantic_state_ablation_does_not_close_pair_after_variant_failure(
    monkeypatch,
    tmp_path,
) -> None:
    case = _case()
    monkeypatch.setattr(semantic_holdout, "load_semantic_holdout_cases", lambda: (case,))

    def fake_run(case, *, case_root, semantic_state_mode, **kwargs):
        del case, case_root, kwargs
        if semantic_state_mode == "consumer_off":
            raise RuntimeError("worker unavailable")
        return _summary_for_mode(semantic_state_mode)

    monkeypatch.setattr(semantic_holdout, "_run_adaptive_case", fake_run)
    summary = semantic_holdout.run_semantic_state_ablation(
        output_root=tmp_path,
        embedding_model_path="/models/embed",
        embedding_device="cpu",
        case_ids=(case.task_id,),
    )

    assert summary["ok"] is False
    assert summary["denominator"]["closed_pairs"] == 0
    assert summary["denominator"]["incomplete_pairs"] == 1
    assert summary["failures"][0]["error"] == "worker unavailable"

