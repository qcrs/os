from __future__ import annotations

import json
from pathlib import Path

from statebus.benchmark import contest_stage2
from statebus.benchmark.contest_stage2 import build_plan, run_live_components, run_stage2, source_digest


STAGE1 = Path(__file__).resolve().parents[2] / "runs" / "contest-stage1-history-fix-20260925b"


def test_formal_stage2_plan_counts_and_smoke_selection() -> None:
    plan = build_plan("all", smoke=False)
    assert len(plan) == 27
    assert {row["mechanism"] for row in plan} == {"memory", "state", "communication", "codeact", "cross-agent"}
    assert sum(row["mechanism"] == "memory" for row in plan) == 12
    assert sum(row["mechanism"] == "state" for row in plan) == 6
    assert sum(row["mechanism"] == "communication" for row in plan) == 4
    assert sum(row["mechanism"] == "codeact" for row in plan) == 4
    assert sum(row["mechanism"] == "cross-agent" for row in plan) == 1
    smoke = build_plan("all", smoke=True)
    assert len([row for row in smoke if row["smoke_selected"]]) == 12
    assert {row["mechanism"] for row in smoke if row["smoke_selected"]} == {"memory", "state", "communication", "codeact", "cross-agent"}


def test_offline_stage2_persists_contract_artifacts_and_boundaries(tmp_path: Path) -> None:
    acceptance = run_stage2(
        output_root=tmp_path / "stage2",
        stage1_root=STAGE1,
        mechanism="all",
        smoke=True,
        offline=True,
        stop_on_failure=True,
        profile="test-profile",
        embedding_model_path="/models/embed",
        embedding_device="cuda:0",
    )
    root = tmp_path / "stage2"
    assert acceptance["run_mode"] == "offline_contract"
    assert acceptance["formal_stage2_ready"] is False
    assert acceptance["components"]["memory"] == "passed"
    assert acceptance["components"]["state"] == "passed"
    assert acceptance["components"]["communication"] == "passed"
    assert acceptance["components"]["codeact"] == "not_applicable"
    assert acceptance["components"]["cross-agent"] == "blocked"
    for name in (
        "manifest.json", "effective-config.json", "preflight.json", "source-digest.txt",
        "task-plan.json", "raw_rows.json", "telemetry.json", "acceptance.json",
        "phase-summary.json", "failures.json",
    ):
        assert (root / name).is_file(), name
    projection = json.loads((root / "results.json").read_text(encoding="utf-8"))["components"]["public_projection"]
    assert projection["gold_fields_removed"] is True
    assert all("expected" not in json.dumps(row).lower() for row in json.loads((root / "raw_rows.json").read_text()))


def test_live_stop_on_failure_marks_unrun_selected_slots(monkeypatch) -> None:
    plan = build_plan("all", smoke=True)
    calls: list[str] = []

    def failed_memory(*args, **kwargs):
        calls.append("memory")
        return {"status": "failed", "error": "synthetic"}

    def unexpected_state(*args, **kwargs):
        calls.append("state")
        raise AssertionError("state must not run after memory failure")

    monkeypatch.setattr(contest_stage2, "_run_stage1_memory_smoke", failed_memory)
    monkeypatch.setattr(contest_stage2, "_run_state_smoke", unexpected_state)
    components = run_live_components(
        Path("/tmp/stage2"), Path("/tmp/stage1"), "all", plan,
        embedding_model_path="/models/embed", embedding_device="cuda:0",
        stop_on_failure=True,
    )

    assert calls == ["memory"]
    assert components == {"memory": {"status": "failed", "error": "synthetic"}}
    assert all(
        row["status"] == "not_started"
        for row in plan
        if row["mechanism"] != "memory" and row["smoke_selected"]
    )


def test_source_digest_ignores_generated_runs(tmp_path: Path) -> None:
    (tmp_path / "statebus").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "deploy").mkdir()
    (tmp_path / "runs").mkdir()
    (tmp_path / "statebus" / "module.py").write_text("source\n", encoding="utf-8")
    first = source_digest(tmp_path)
    (tmp_path / "runs" / "old-run.json").write_text("generated\n", encoding="utf-8")
    assert source_digest(tmp_path) == first


def test_live_component_details_preserve_offline_rows(monkeypatch, tmp_path: Path) -> None:
    def fake_live(*args, **kwargs):
        return {
            "communication": {
                "status": "diagnostic_only",
                "task_level_live_equivalent": False,
            },
        }

    monkeypatch.setattr(contest_stage2, "run_live_components", fake_live)
    acceptance = run_stage2(
        output_root=tmp_path / "stage2",
        stage1_root=STAGE1,
        mechanism="communication",
        smoke=True,
        offline=False,
        stop_on_failure=True,
        profile="test-profile",
        embedding_model_path="/models/embed",
        embedding_device="cuda:0",
    )

    assert acceptance["components"]["communication"] == "diagnostic_only"
    details = acceptance["component_details"]["communication"]
    assert details["offline_contract"]["status"] == "passed"
    rows = json.loads((tmp_path / "stage2" / "raw_rows.json").read_text(encoding="utf-8"))
    assert {row["evidence_scope"] for row in rows} == {"offline_contract"}
    assert len(rows) == 4
