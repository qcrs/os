from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

import v2.studio.app as studio_app
import v2.studio.jobs as studio_jobs
from scripts.v2_diagnostics import run_adaptive_agent_smoke as adaptive_smoke
from v2.studio.catalog import load_catalog, load_evidence_snapshot
from v2.studio.jobs import JobManager
from v2.studio.task_flow import build_task_flow_index


def test_fixed_evidence_snapshot_matches_presentation_contract() -> None:
    snapshot = load_evidence_snapshot()

    metrics = {row["id"]: row for row in snapshot["headline_metrics"]}
    assert snapshot["git_sha"].startswith("bda1774")
    assert snapshot["quality"]["formal_passed"] == 95
    assert metrics["total_tokens"]["delta_pct"] == -47.40
    assert metrics["wire_bytes"]["delta_pct"] == -64.85
    assert metrics["task_time"]["delta_pct"] == -6.32
    assert snapshot["memory"]["actual_use_rate_pct"] == 35.0
    assert snapshot["capability"]["fallback"] == 0


def test_catalog_exposes_registered_tasks_without_external_paths() -> None:
    catalog = load_catalog()

    assert len(catalog["datasets"]) == 4
    assert sum(dataset["task_count"] for dataset in catalog["datasets"]) == 49
    assert all(not source["path"].startswith("/") for dataset in catalog["datasets"] for source in dataset["sources"])
    assert all(source["sha256"] for dataset in catalog["datasets"] for source in dataset["sources"])


def test_api_serves_snapshot_catalog_and_controlled_run(tmp_path, monkeypatch) -> None:
    manager = JobManager(tmp_path / "studio-runs")
    embedding_model = tmp_path / "embedding-model"
    embedding_model.mkdir()
    monkeypatch.setenv("STATEBUS_EMBED_MODEL_PATH", str(embedding_model))
    monkeypatch.setattr(studio_app, "manager", manager)
    monkeypatch.setattr(
        studio_app,
        "_probe_url",
        lambda url: {"ok": True, "status": 200, "url": url},
    )
    monkeypatch.setattr(
        studio_app,
        "_probe_role_worker_import",
        lambda: {"ok": True, "detail": "", "project_root_in_pythonpath": True},
    )
    monkeypatch.setattr(
        studio_app,
        "_probe_embedding_runtime",
        lambda device: {"ok": True, "device": device, "detail": "ready"},
    )
    monkeypatch.setattr(
        studio_jobs,
        "build_command",
        lambda recipe_id, run_dir, run_id: [
            sys.executable,
            "-c",
            "import json; print(json.dumps({'stage': 'studio_test', 'quality_passed': True}))",
        ],
    )

    with TestClient(studio_app.app) as client:
        evidence = client.get("/api/v1/evidence/current")
        assert evidence.status_code == 200
        assert evidence.json()["snapshot_id"] == "statebus-v2-20260726"

        catalog = client.get("/api/v1/catalog")
        assert catalog.status_code == 200
        assert {recipe["mode"] for recipe in catalog.json()["recipes"]} == {"quick", "scenario", "experiment"}

        rejected = client.post("/api/v1/runs", json={"recipe_id": "shell-anything"})
        assert rejected.status_code == 422

        created = client.post("/api/v1/runs", json={"recipe_id": "quick-operating-codeact"})
        assert created.status_code == 202
        run_id = created.json()["run_id"]

        deadline = time.monotonic() + 5
        status = "queued"
        while time.monotonic() < deadline:
            payload = client.get(f"/api/v1/runs/{run_id}").json()
            status = payload["status"]
            if status in {"completed", "failed"}:
                break
            time.sleep(0.02)

        assert status == "completed"
        result = client.get(f"/api/v1/runs/{run_id}/result")
        assert result.status_code == 200
        assert result.json()["result"]["stdout"]["stage"] == "studio_test"

        events = client.get(f"/api/v1/runs/{run_id}/events")
        assert events.status_code == 200
        assert "RUN_QUEUED" in events.text
        assert "RUN_COMPLETED" in events.text

        artifacts = client.get(f"/api/v1/runs/{run_id}/artifacts")
        assert artifacts.status_code == 200
        paths = {row["path"] for row in artifacts.json()["artifacts"]}
        assert {"command.json", "console.log", "studio_job.json"}.issubset(paths)

        flow = client.get(f"/api/v1/runs/{run_id}/task-flow")
        assert flow.status_code == 200
        assert flow.json()["available"] is False

        invalid_task = client.get(f"/api/v1/runs/{run_id}/task-flow?task_id=../../etc/passwd")
        assert invalid_task.status_code == 422


def test_api_rejects_run_when_isolated_role_worker_is_unavailable(tmp_path, monkeypatch) -> None:
    manager = JobManager(tmp_path / "studio-runs")
    monkeypatch.setattr(studio_app, "manager", manager)
    monkeypatch.setattr(
        studio_app,
        "_probe_role_worker_import",
        lambda: {
            "ok": False,
            "detail": "ModuleNotFoundError: No module named 'runtime'",
            "project_root_in_pythonpath": False,
        },
    )

    with TestClient(studio_app.app) as client:
        response = client.post("/api/v1/runs", json={"recipe_id": "quick-operating-codeact"})

    assert response.status_code == 503
    assert "Agent Worker" in response.json()["detail"]
    assert manager.list() == []


def test_api_rejects_run_when_embedding_device_is_unavailable(tmp_path, monkeypatch) -> None:
    manager = JobManager(tmp_path / "studio-runs")
    embedding_model = tmp_path / "embedding-model"
    embedding_model.mkdir()
    monkeypatch.setenv("STATEBUS_EMBED_MODEL_PATH", str(embedding_model))
    monkeypatch.setattr(studio_app, "manager", manager)
    monkeypatch.setattr(
        studio_app,
        "_probe_role_worker_import",
        lambda: {"ok": True, "detail": "", "project_root_in_pythonpath": True},
    )
    monkeypatch.setattr(
        studio_app,
        "_probe_embedding_runtime",
        lambda device: {"ok": False, "device": device, "detail": "PyTorch cannot access a CUDA device"},
    )
    monkeypatch.setattr(
        studio_app,
        "_probe_url",
        lambda url: {"ok": True, "status": 200, "url": url},
    )

    with TestClient(studio_app.app) as client:
        response = client.post("/api/v1/runs", json={"recipe_id": "quick-operating-codeact"})

    assert response.status_code == 503
    assert "Embedding 运行环境未就绪" in response.json()["detail"]
    assert manager.list() == []


def test_isolated_role_worker_builds_its_own_pythonpath(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.delenv("PYTHONPATH", raising=False)

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"candidate": {}, "attempts": [], "request_audit": {}, "error": ""}),
            stderr="",
        )

    monkeypatch.setattr(adaptive_smoke.subprocess, "run", fake_run)

    result = adaptive_smoke._isolated_role_completion("planner", {})
    project_root = Path(adaptive_smoke.__file__).resolve().parents[2]
    child_environment = captured["env"]

    assert result.error == ""
    assert captured["cwd"] == project_root
    assert isinstance(child_environment, dict)
    assert str(project_root) in str(child_environment["PYTHONPATH"]).split(os.pathsep)


def test_runner_failure_is_translated_to_actionable_chinese(tmp_path) -> None:
    console = tmp_path / "console.log"
    console.write_text("ModuleNotFoundError: No module named 'runtime'\n", encoding="utf-8")

    stage, detail = studio_jobs._diagnose_runner_failure(console, 1)

    assert stage == "Planner 启动失败"
    assert "无法导入 StateBus Runtime" in detail

    console.write_text("RuntimeError: No CUDA GPUs are available\n", encoding="utf-8")
    stage, detail = studio_jobs._diagnose_runner_failure(console, 1)
    assert stage == "Embedding GPU 不可用"
    assert "CUDA" in detail


def test_queued_run_can_be_canceled_without_starting_runner(tmp_path) -> None:
    import asyncio

    async def exercise() -> None:
        manager = JobManager(tmp_path / "cancel-runs")
        run = await manager.create("quick-operating-codeact")
        canceled = await manager.cancel(run.run_id)
        assert canceled.status == "canceled"
        assert canceled.current_stage == "排队任务已取消"

        restored = JobManager(tmp_path / "cancel-runs")
        restored_run = restored.get(run.run_id)
        assert restored_run.status == "canceled"
        assert restored_run.latest_events[-1].event_type == "RUN_CANCELED"

    asyncio.run(exercise())


def test_task_flow_index_exposes_structured_agent_io_and_bounded_program(tmp_path) -> None:
    case_root = tmp_path / "run" / "adaptive" / "formal-anomaly-001"
    case_root.mkdir(parents=True)
    summary = {
        "task_id": "formal-anomaly-001",
        "operation": "detect_outliers",
        "ok": True,
        "system_gate_passed": True,
        "source_ref_id": "formal-source:formal-anomaly-001",
        "approved_plan_hash": "a" * 64,
        "canonical_task_spec": {
            "intent_op": "detect_outliers",
            "arguments": {"column": "value", "threshold": 1.5},
        },
        "selected_capability_ids": [
            "retrieve_table_evidence_v1",
            "execute_bounded_python_v2",
            "compose_claim_set_v2",
        ],
        "approved_steps": [
            {
                "step_id": "retrieve-evidence",
                "role": "retriever",
                "capability_id": "retrieve_table_evidence_v1",
                "goal": "Detect outliers. Evidence strategy: retrieve approved evidence.",
                "input_ref_ids": [],
                "output_contract_version": "statebus.evidence_pack.v2",
            },
            {
                "step_id": "execute-analysis",
                "role": "executor",
                "capability_id": "execute_bounded_python_v2",
                "goal": "Detect outliers. Analysis strategy: execute bounded Python.",
                "input_ref_ids": ["formal-source:formal-anomaly-001"],
                "output_contract_version": "statebus.analysis_result.v2",
                "completion_criteria": {"required_fields": ["mean"]},
            },
            {
                "step_id": "compose-report",
                "role": "summarizer",
                "capability_id": "compose_claim_set_v2",
                "goal": "Detect outliers. Reporting strategy: compose cited claims.",
                "input_ref_ids": [],
                "output_contract_version": "statebus.cited_report.v1",
            },
        ],
        "runtime_session": {
            "workflow_steps": [
                {"step_id": "retrieve-evidence", "state": "COMPLETED", "output_ref_hash": "b" * 64},
                {"step_id": "execute-analysis", "state": "COMPLETED", "output_ref_hash": "c" * 64},
                {"step_id": "compose-report", "state": "COMPLETED", "output_ref_hash": "d" * 64},
            ]
        },
        "runtime_dispatches": [
            {"step_id": "retrieve-evidence", "output_refs": ["evidence:1"]},
            {"step_id": "execute-analysis", "output_refs": ["artifact:1"]},
            {"step_id": "compose-report", "output_refs": ["claimset:1"]},
        ],
        "execution_records": [{
            "input_ref_ids": ["formal-source:formal-anomaly-001", "evidence:1"],
            "policy_report_hash": "e" * 64,
            "source_hash": "f" * 64,
            "sandbox_requested_backend": "bwrap_required",
            "sandbox_actual_backend": "bwrap",
            "sandbox_uid": 65534,
            "sandbox_gid": 65534,
            "exit_code": 0,
            "timeout": False,
            "verified_artifact_id": "artifact:1",
            "output_hash": "1" * 64,
            "output_schema_valid": True,
            "output_quality_valid": True,
            "validator_errors": [],
        }],
        "terminal_quality_reports": [{
            "capability_id": "execute_bounded_python_v2",
            "validator_id": "formal_analysis",
            "verified": True,
            "schema_passed": True,
            "completion_criteria_passed": True,
            "execution_verified": True,
            "provenance_passed": True,
            "recomputation_passed": True,
            "output_artifact_hash": "1" * 64,
        }],
        "generation_attempts": [{"model_id": "qwen3-32b"}],
        "claim_sets": [{
            "claim_set_id": "claimset:1",
            "claims": [{"claim_text": "The verified mean is 12.5."}],
        }],
        "initial_plan_policy_report": {"status": "approved", "policy_version": "statebus.plan_policy.v1"},
        "role_invocations": [{
            "role": "planner",
            "model_id": "qwen3-32b",
            "attempts": [{
                "model": "qwen3-32b",
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "raw_response": json.dumps({"proposal_id": "plan-1"}),
            }],
            "request_audit": {"messages": ["must not be exposed"]},
        }],
        "usage": {"prompt_tokens": 200, "completion_tokens": 50, "total_tokens": 250},
    }
    (case_root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (case_root / "planner_trace.json").write_text(
        json.dumps({"effective_proposal": {"task_id": "formal-anomaly-001", "steps": summary["approved_steps"]}}),
        encoding="utf-8",
    )
    (case_root / "executor_initial_raw.txt").write_text(
        "```python\nfrom pathlib import Path\nPath('outputs/result.json').write_text('{\\\"mean\\\": 12.5}')\n```",
        encoding="utf-8",
    )

    payload = build_task_flow_index(tmp_path / "run", task_id="formal-anomaly-001")

    assert payload["available"] is True
    assert [step["role"] for step in payload["selected"]["steps"]] == [
        "planner", "retriever", "executor", "summarizer",
    ]
    assert payload["selected"]["generated_program"]["kind"] == "python"
    assert payload["selected"]["generated_program"]["sandbox"]["network"] == "unshared"
    assert payload["selected"]["final_answer"] == "The verified mean is 12.5."
    assert "request_audit" not in json.dumps(payload)
    assert "must not be exposed" not in json.dumps(payload)
