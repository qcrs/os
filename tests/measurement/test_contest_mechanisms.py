from __future__ import annotations

import json
from pathlib import Path

from statebus.benchmark import contest_mechanisms
from statebus.benchmark.contest_dsl_taskpack import (
    SIMPLE_PROFILE,
    generate_sealed,
    publish_required_files,
    task_contract,
)
from statebus.benchmark import semantic_holdout
from tools.measurement import collect_contest_mechanism_results as collector


def test_fixed_plan_and_bounded_smoke_selection() -> None:
    plan = contest_mechanisms.experiment_plan()
    keys = [(row["experiment"], row["task_id"], row["variant"]) for row in plan]
    assert len(plan) == len(set(keys)) == 24
    assert sum(row["experiment"] == "memory" for row in plan) == 16
    assert sum(row["experiment"] == "state" for row in plan) == 8

    memory = contest_mechanisms.experiment_plan(
        mechanism="memory", family="finance", task_ids=("F01", "F02"),
    )
    assert [(row["task_id"], row["variant"]) for row in memory] == [
        ("F01", "off"), ("F02", "off"), ("F01", "on"), ("F02", "on"),
    ]
    state = contest_mechanisms.experiment_plan(
        mechanism="state", case_ids=("semantic-holdout-s1",),
    )
    assert [(row["task_id"], row["variant"]) for row in state] == [
        ("semantic-holdout-s1", "off"), ("semantic-holdout-s1", "on"),
    ]
    smoke_candidate = contest_mechanisms.experiment_plan(
        mechanism="state", case_ids=("semantic-holdout-s2",),
    )
    assert [(row["task_id"], row["variant"]) for row in smoke_candidate] == [
        ("semantic-holdout-s2", "off"), ("semantic-holdout-s2", "on"),
    ]
    assert contest_mechanisms.STATE_TASKS == (
        "semantic-holdout-s1", "semantic-holdout-s5", "semantic-holdout-s4", "semantic-holdout-s8",
    )


def test_required_file_publisher_does_not_release_future_inputs(tmp_path: Path) -> None:
    sealed = tmp_path / "sealed"
    generate_sealed(sealed, profile=SIMPLE_PROFILE)
    for task_id in ("F01", "F02", "F06", "F07", "O01", "O02", "O06", "O07"):
        public = tmp_path / "public" / task_id
        published = publish_required_files(sealed, public, task_id, profile=SIMPLE_PROFILE)
        contract = task_contract(task_id, profile=SIMPLE_PROFILE)
        assert contract.required_history == ()
        assert {path.name for path in published} == set(contract.required_files)
        assert {
            path.name for path in (public / contract.family).iterdir() if path.is_file()
        } == set(contract.required_files)


def test_offline_validation_is_wiring_only(tmp_path: Path) -> None:
    plan = contest_mechanisms.experiment_plan(
        mechanism="all",
        family="finance",
        task_ids=("F01", "F02"),
        case_ids=("semantic-holdout-s1",),
    )
    result = contest_mechanisms.run_offline_validation(tmp_path, plan=plan)
    assert result["ok"] is True
    assert result["provider_requests_made"] is False
    assert result["embedding_loaded"] is False
    assert result["live_results_produced"] is False
    assert result["state"]["modes"] == ["off", "on"]
    assert result["memory"]["mechanism_configuration"] == [
        {"variant": "off", "transport": "typed", "semantic_state": "on", "memory": "off"},
        {"variant": "on", "transport": "typed", "semantic_state": "on", "memory": "on"},
    ]


def test_memory_runner_only_switches_memory(monkeypatch, tmp_path: Path) -> None:
    observed: list[dict[str, object]] = []

    def fake_run_slot(root, public, task_id, **kwargs):
        del public, task_id
        observed.append(kwargs)
        root.mkdir(parents=True, exist_ok=False)
        (root / "rows.json").write_text("[]\n", encoding="utf-8")
        (root / "input-lineage.json").write_text("{}\n", encoding="utf-8")
        return {
            "status": "success", "quality": True, "returncode": 0, "repair": 0,
            "metrics": {"provider_request_count": 0, "provider_total_tokens": None,
                        "executor_request_count": 0},
            "failure_codes": [], "rows": [],
        }

    monkeypatch.setattr(contest_mechanisms, "run_slot", fake_run_slot)
    for variant in ("off", "on"):
        summary = contest_mechanisms.run_memory_chain(
            tmp_path / variant,
            family="finance",
            variant=variant,
            mode="offline",
            task_ids=("F01",),
        )
        assert summary["passed"] == 1
    assert [(item["memory_enabled"], item["semantic_state_mode"], item["variant"])
            for item in observed] == [
        (False, "on", "SB-FULL"),
        (True, "on", "SB-FULL"),
    ]


def test_explicit_memory_control_changes_real_runtime_query_projection(tmp_path: Path) -> None:
    observed = {}
    for variant in ("off", "on"):
        summary = contest_mechanisms.run_memory_chain(
            tmp_path / variant,
            family="finance",
            variant=variant,
            mode="offline",
            task_ids=("F01",),
        )
        assert summary["passed"] == 1
        observed[variant] = summary["rows"][0]["memory"]

    assert observed["off"]["query_count"] == 0
    assert observed["off"]["candidate_hit_count"] == 0
    assert observed["off"]["actual_consumed"] is False
    assert observed["off"]["validated_replay"] is False
    assert observed["on"]["query_count"] == 1




def test_state_metrics_use_downstream_evidence_and_actual_attempts() -> None:
    summary = {
        "report_evidence_items": [
            {"id": "a", "text": "three"},
            {"id": "b", "text": "four"},
        ],
        "semantic_state_selections": {
            "state": {
                "selected_candidate_ids": ["a"],
                "selected_evidence_bytes": 999,
                "producer_pid": 10,
                "consumer_pid": 11,
            }
        },
        "role_invocations": [
            {"role": "planner", "attempts": [{}, {}]},
            {"role": "retriever", "attempts": [{}]},
        ],
        "generation_attempts": [{}, {}],
    }
    metrics = semantic_holdout._semantic_selected_metrics(summary)
    assert metrics["selected_ids"] == ["a", "b"]
    assert metrics["selected_evidence_chars"] == 9
    assert metrics["state_selected_ids"] == ["a"]
    assert metrics["state_selected_evidence_bytes"] == 999
    assert semantic_holdout._provider_call_count(summary) == 5


def test_collector_reconstructs_fixed_slots_and_preserves_nulls(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    report = tmp_path / "report"
    summary = collector.collect(raw, report)
    rows = [json.loads(line) for line in (report / "task_results.jsonl").read_text().splitlines()]
    assert len(rows) == summary["planned"] == 24
    assert summary["started"] == summary["passed"] == 0
    assert all(row["status"] == "not_started" for row in rows)
    assert all(row["quality"] is None and row["provider_requests"] is None for row in rows)
    assert collector._saving(0, 0, comparable=True) is None
    assert set(path.name for path in report.iterdir()) == {
        "task_results.jsonl", "task_results.csv", "summary.json", "summary.md",
    }


def test_collector_uses_bounded_manifest_plan(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "manifest.json").write_text(json.dumps({
        "schema_version": "statebus.contest_mechanism_batch.v1",
        "mechanism": "state",
        "plan": [
            {"experiment": "state", "task_id": "semantic-holdout-s1", "variant": "off"},
            {"experiment": "state", "task_id": "semantic-holdout-s1", "variant": "on"},
        ],
    }), encoding="utf-8")
    report = tmp_path / "report"
    summary = collector.collect(raw, report)
    rows = [json.loads(line) for line in (report / "task_results.jsonl").read_text().splitlines()]
    assert len(rows) == summary["planned"] == 2
    assert summary["started"] == summary["passed"] == 0
    assert {(row["experiment"], row["task_id"], row["variant"]) for row in rows} == {
        ("state", "semantic-holdout-s1", "off"),
        ("state", "semantic-holdout-s1", "on"),
    }


def test_collector_classifies_state_model_quality_failure(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    case_root = raw / "state" / "ablation" / "cases" / "semantic-holdout-s1" / "on"
    case_root.mkdir(parents=True)
    (case_root / "summary.json").write_text(json.dumps({
        "failure_classification": {
            "category": "model_quality",
            "error_code": "output_validation_failed",
            "error": "semantic-holdout-s1",
        }
    }), encoding="utf-8")
    state_summary = raw / "state" / "ablation" / "summary.json"
    state_summary.parent.mkdir(parents=True, exist_ok=True)
    state_summary.write_text(json.dumps({"rows": [{
        "task_id": "semantic-holdout-s1",
        "variant": "on",
        "ok": False,
        "quality_pass": False,
        "summary_path": str(case_root / "summary.json"),
    }]}), encoding="utf-8")

    report = tmp_path / "report"
    collector.collect(raw, report)
    rows = [json.loads(line) for line in (report / "task_results.jsonl").read_text().splitlines()]
    row = next(item for item in rows if item["experiment"] == "state"
               and item["task_id"] == "semantic-holdout-s1" and item["variant"] == "on")
    assert row["status"] == "quality_fail"
    assert row["reason"] == "output_validation_failed"
    assert Path(row["source_path"]).is_absolute()
