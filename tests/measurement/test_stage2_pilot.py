from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os
import subprocess
import time

import pytest

import statebus.benchmark.stage2_pilot as pilot
from statebus.integrations.llm import LLMResult
from statebus.utils import sha256_digest


def _sample(case_id: str = "case-1") -> SimpleNamespace:
    spec = SimpleNamespace(
        task_family="financial_report_analysis",
        intent_op="extract_metric",
        arguments={"metric": "revenue", "public_sources": ["doc-1"]},
        required_outputs=("summary_text",),
    )
    return SimpleNamespace(
        task_id=case_id,
        task_family="financial_report_analysis",
        dataset_id="dataset",
        dataset_version="v1",
        dataset_split="test",
        request_text="find revenue",
        canonical_task_spec=spec,
        expected_facts={"summary_text": "ok"},
    )


def _success_runner(sample, root: Path, *, seed: int = 0, **kwargs):
    del sample, seed, kwargs
    output = root / "output.json"
    output.write_text('{"summary_text":"ok"}\n', encoding="utf-8")
    return {
        "payload": {"summary_text": "ok"},
        "output_path": str(output),
        "report_path": str(root / "report.json"),
        "provider_invocation_status": "completed",
        "provider_invocation_events": [{"event": "provider_invocation", "status": "completed"}],
        "provider_calls": 1,
    }


def test_warmup_failure_blocks_remaining_slots_without_runtime_failure_rows(monkeypatch, tmp_path: Path) -> None:
    sample = _sample()
    monkeypatch.setattr(pilot, "_select_samples", lambda: [("family", sample, sample)])
    monkeypatch.setattr(pilot, "_quality", lambda *args, **kwargs: {"passed": True, "failures": []})

    def fail_runner(sample, root: Path, **kwargs):
        del sample, root, kwargs
        raise RuntimeError("warmup boom")

    runners = {lane: _success_runner for lane in pilot.LANES}
    runners["direct_single_agent"] = fail_runner
    acceptance = pilot.run_stage2_pilot(
        output_root=tmp_path / "run",
        lane_runners=runners,
        timeout_s=1,
    )

    rows = pilot.json.loads((tmp_path / "run" / "raw_rows.json").read_text(encoding="utf-8"))
    assert acceptance["status"] == "pilot_inconclusive"
    assert acceptance["denominator"]["not_started_count"] == len(pilot.LANES) * len(pilot.SEEDS)
    assert all(row["status"] == "not_started" for row in rows)
    assert all(row["terminal_class"] == "not_started" for row in rows)
    manifest = pilot.json.loads((tmp_path / "run" / "stage2_manifest.json").read_text(encoding="utf-8"))
    assert {slot["regime"] for slot in manifest["planned_slots"]} == {"provider_cache_uncontrolled"}
    assert manifest["cache_control"]["cold_warm_claim"] == "not_supported"
    blocked_warmups = pilot.json.loads((tmp_path / "run" / "warmups.json").read_text(encoding="utf-8"))
    for warmup in blocked_warmups[1:]:
        assert warmup["started_at_ns"] is None
        assert not (tmp_path / "run" / "warmups" / warmup["family_id"] / warmup["lane"] / "call-start.json").exists()


def test_adaptive_policy_rejection_preserves_real_planner_requests(monkeypatch, tmp_path: Path) -> None:
    sample = _sample()
    monkeypatch.setattr(pilot, "_select_samples", lambda: [("family", sample, sample)])
    monkeypatch.setattr(pilot, "_quality", lambda *args, **kwargs: {"passed": True, "failures": []})

    def fail_adaptive(sample, root: Path, **kwargs):
        del sample, kwargs
        case_root = root / "adaptive_case"
        case_root.mkdir()
        pilot._json(case_root / "planner_trace.json", {
            "attempts": [{"attempt_index": 1, "raw_response_hash": "first", "model": "qwen3-32b"}],
            "request_audit": {"requests": [{"attempt_index": 1, "request_sha256": "request-first"}]},
        })
        pilot._json(case_root / "planner_repair_trace.json", {
            "attempts": [{"attempt_index": 1, "raw_response_hash": "second", "model": "qwen3-32b"}],
            "request_audit": {"requests": [{"attempt_index": 1, "request_sha256": "request-second"}]},
        })
        raise RuntimeError("formal_planner_policy_rejected:execution_runtime_budget_exceeded")

    runners = {lane: _success_runner for lane in pilot.LANES}
    runners["adaptive_routed"] = fail_adaptive
    acceptance = pilot.run_stage2_pilot(
        output_root=tmp_path / "run", lane_runners=runners, timeout_s=1,
    )

    warmups = pilot.json.loads((tmp_path / "run" / "warmups.json").read_text(encoding="utf-8"))
    adaptive = next(item for item in warmups if item["lane"] == "adaptive_routed")
    assert adaptive["status"] == "policy_reject"
    assert adaptive["failure_stage"] == "planner_policy"
    assert adaptive["provider_invocation_status"] == "response_received"
    assert [event["request_id"] for event in adaptive["provider_request_events"]] == ["request-first", "request-second"]
    assert [event["retry_kind"] for event in adaptive["provider_request_events"]] == ["none", "role_repair"]
    assert len(adaptive["provider_evidence_paths"]) == 2
    assert acceptance["denominator"]["not_started_count"] == len(pilot.SEEDS)


def test_adaptive_incomplete_attempt_does_not_fabricate_response(tmp_path: Path) -> None:
    case_root = tmp_path / "adaptive_case"
    case_root.mkdir()
    pilot._json(case_root / "planner_trace.json", {
        "attempts": [{"attempt_index": 1}], "request_audit": {"request_count": 1},
    })
    result = pilot._adaptive_failure_evidence(tmp_path, {"provider_invocation_status": "unknown"}, seed=0)
    assert not result.get("provider_request_events")
    assert result["provider_invocation_status"] == "unknown"


@pytest.mark.parametrize("process", [False, True])
def test_lane_exception_preserves_runtime_failure_projection(process: bool) -> None:
    def fail() -> dict[str, object]:
        error = RuntimeError("fixed_runtime_failed:plan:planner_contract_invalid")
        error.failure_stage = "plan"
        error.error_code = "planner_contract_invalid"
        error.provider_invocation_events = [{"role": "planner", "status": "error"}]
        error.provider_request_events = [{"request_id": "planner-1", "retry_kind": "none"}]
        error.retry_events = []
        error.runtime_root = "/tmp/runtime"
        raise error

    result, error, _ = pilot._invoke_with_deadline(fail, 1, process=process)
    assert error == "RuntimeError: fixed_runtime_failed:plan:planner_contract_invalid"
    assert result is not None
    assert result["failure_stage"] == "plan"
    assert result["error_code"] == "planner_contract_invalid"
    assert result["provider_invocation_status"] == "failed"
    assert result["provider_calls"] == 1
    assert result["runtime_root"] == "/tmp/runtime"


def test_adaptive_plan_budget_is_independent_of_measurement_deadline(monkeypatch, tmp_path: Path) -> None:
    from statebus.benchmark import adaptive_formal_mainline as adaptive

    captured: dict[str, object] = {}

    def inspect_planner(role, payload):
        assert role == "planner"
        captured.update(payload["envelope"])
        return SimpleNamespace(error="budget_probe")

    monkeypatch.setattr(adaptive, "_isolated_role_completion", inspect_planner)
    case = pilot.adapt_formal_sample(pilot._select_samples()[0][1])
    with pytest.raises(RuntimeError, match="formal_planner_worker_failed:budget_probe"):
        adaptive._run_adaptive_case(
            case,
            case_root=tmp_path / "case",
            embedding_model_path="/statebus/models/Qwen3-Embedding-0.6B",
            embedding_device="cuda:0",
        )
    assert captured["max_execution_runtime_ms"] == 400_000
    assert captured["max_execution_runtime_ms"] >= 120_000 + 2 * 120_000 + 30_000


def test_required_gate_failure_stops_new_slots_and_preserves_unknown_failure_state(monkeypatch, tmp_path: Path) -> None:
    sample = _sample()
    monkeypatch.setattr(pilot, "_select_samples", lambda: [("family", sample, sample)])
    monkeypatch.setattr(pilot, "_quality", lambda *args, **kwargs: {"passed": True, "failures": []})
    calls = {"count": 0}

    def fail_on_first_measured(sample, root: Path, **kwargs):
        del kwargs
        calls["count"] += 1
        if calls["count"] == 2:  # warm-up succeeded; first measured slot failed
            raise RuntimeError("provider parse failure")
        return _success_runner(sample, root)

    runners = {lane: _success_runner for lane in pilot.LANES}
    runners["direct_single_agent"] = fail_on_first_measured
    acceptance = pilot.run_stage2_pilot(
        output_root=tmp_path / "run",
        lane_runners=runners,
        timeout_s=1,
    )

    rows = pilot.json.loads((tmp_path / "run" / "raw_rows.json").read_text(encoding="utf-8"))
    failed = [row for row in rows if row["status"] == "runtime_fail"]
    blocked = [row for row in rows if row["status"] == "not_started"]
    assert acceptance["status"] == "pilot_inconclusive"
    assert len(failed) == 1
    assert failed[0]["lifecycle_state"] == "unknown"
    assert failed[0]["provider_invocation_status"] == "not_started"
    assert blocked
    assert all(row["terminal_class"] == "not_started" for row in blocked)


def test_fixed_warmup_failure_blocks_fixed_and_later_lanes(monkeypatch, tmp_path: Path) -> None:
    sample = _sample()
    monkeypatch.setattr(pilot, "_select_samples", lambda: [("family", sample, sample)])
    monkeypatch.setattr(pilot, "_quality", lambda *args, **kwargs: {"passed": True, "failures": []})

    def fail_runner(sample, root: Path, **kwargs):
        del sample, root, kwargs
        raise RuntimeError("fixed warmup failed")

    runners = {lane: _success_runner for lane in pilot.LANES}
    runners["fixed_structured"] = fail_runner
    acceptance = pilot.run_stage2_pilot(
        output_root=tmp_path / "run",
        lane_runners=runners,
        timeout_s=1,
    )

    rows = pilot.json.loads((tmp_path / "run" / "raw_rows.json").read_text(encoding="utf-8"))
    by_lane = {lane: [row for row in rows if row["lane"] == lane] for lane in pilot.LANES}
    assert all(row["status"] == "success" for row in by_lane["direct_single_agent"])
    assert all(row["status"] == "success" for row in by_lane["pure_text_mas"])
    assert all(row["status"] == "not_started" for row in by_lane["fixed_structured"])
    assert all(row["status"] == "not_started" for row in by_lane["adaptive_routed"])
    assert acceptance["no_go_reasons"] == ["terminal_or_evidence_failure"]


def test_offline_negative_quality_is_no_go_not_success(monkeypatch, tmp_path: Path) -> None:
    sample = _sample()
    monkeypatch.setattr(pilot, "_select_samples", lambda: [("family", sample, sample)])
    monkeypatch.setattr(
        pilot,
        "_quality",
        lambda *args, **kwargs: {"passed": False, "failures": ["negative_fixture"]},
    )

    acceptance = pilot.run_stage2_pilot(
        output_root=tmp_path / "run",
        dry_run=True,
        strict_gates=True,
        preflight=False,
        process_deadline=False,
        timeout_s=1,
    )

    warmups = pilot.json.loads((tmp_path / "run" / "warmups.json").read_text(encoding="utf-8"))
    assert warmups[0]["status"] == "quality_fail"
    assert acceptance["status"] == "offline_validation"
    assert acceptance["exit_code"] == pilot.EXIT_INCONCLUSIVE
    assert "terminal_or_evidence_failure" in acceptance["no_go_reasons"]


def test_offline_fixed_lane_preserves_canonical_aggregate_exclusion(monkeypatch, tmp_path: Path) -> None:
    sample = _sample()
    monkeypatch.setattr(pilot, "_select_samples", lambda: [("family", sample, sample)])
    monkeypatch.setattr(pilot, "_quality", lambda *args, **kwargs: {"passed": True, "failures": []})

    acceptance = pilot.run_stage2_pilot(
        output_root=tmp_path / "run",
        dry_run=True,
        strict_gates=True,
        preflight=False,
        process_deadline=False,
        timeout_s=1,
    )

    rows = pilot.json.loads((tmp_path / "run" / "raw_rows.json").read_text(encoding="utf-8"))
    fixed_rows = [row for row in rows if row["lane"] == "fixed_structured"]
    assert len(fixed_rows) == len(pilot.SEEDS)
    assert all(row["canonical_aggregate_eligible"] is False for row in fixed_rows)
    assert {row["exclusion_reason"] for row in fixed_rows} == {
        pilot.FIXED_AGGREGATE_EXCLUSION_REASON
    }
    assert acceptance["denominator"]["excluded_count"] == len(pilot.SEEDS)
    assert acceptance["denominator"]["arithmetic_closed"] is True
    assert acceptance["no_go_reasons"] == ["canonical_aggregate_exclusion"]


def test_repeats_scale_planned_slots_without_changing_pair_identity(monkeypatch, tmp_path: Path) -> None:
    sample = _sample()
    monkeypatch.setattr(pilot, "_select_samples", lambda: [("family", sample, sample)])
    monkeypatch.setattr(pilot, "_quality", lambda *args, **kwargs: {"passed": True, "failures": []})

    acceptance = pilot.run_stage2_pilot(
        output_root=tmp_path / "run", repeats=3, dry_run=True, timeout_s=1,
        strict_gates=True, preflight=False, process_deadline=False,
    )

    manifest = pilot.json.loads((tmp_path / "run" / "stage2_manifest.json").read_text(encoding="utf-8"))
    assert manifest["repeat_seeds"] == [0, 1, 0]
    assert manifest["repeat_count"] == 3
    assert acceptance["planned_slots"] == acceptance["observed_rows"] == 3 * len(pilot.LANES)
    assert acceptance["denominator"]["arithmetic_closed"] is True
    assert len({slot["slot_id"] for slot in manifest["planned_slots"]}) == 3 * len(pilot.LANES)
    for repeat in (1, 2, 3):
        slots = [slot for slot in manifest["planned_slots"] if slot["repeat"] == repeat]
        assert len({slot["pair_id"] for slot in slots}) == 1


def test_bounded_registry_selection_preserves_independent_family_cases() -> None:
    case_a1 = _sample("case-a1")
    case_a2 = _sample("case-a2")
    case_b1 = _sample("case-b1")
    selected = [
        ("family-a::case-a1", case_a1, case_a1),
        ("family-a::case-a2", case_a2, case_a2),
        ("family-b::case-b1", case_b1, case_b1),
    ]

    bounded = pilot._filter_selected_samples(
        selected,
        family_ids=("family-a", "family-b"),
        max_cases_per_family=1,
    )

    assert [(family, sample.task_id) for family, sample, _fixed in bounded] == [
        ("family-a::case-a1", "case-a1"),
        ("family-b::case-b1", "case-b1"),
    ]
    assert [row[1].task_id for row in pilot._filter_selected_samples(
        selected,
        case_ids=("case-a2", "case-b1"),
    )] == ["case-a2", "case-b1"]


def test_bounded_registry_selection_rejects_ambiguous_or_unknown_filters() -> None:
    sample = _sample("case-a1")
    selected = [("family-a::case-a1", sample, sample)]

    with pytest.raises(ValueError, match="mutually_exclusive"):
        pilot._filter_selected_samples(
            selected,
            case_ids=("case-a1",),
            family_ids=("family-a",),
        )
    with pytest.raises(ValueError, match="stage2_case_not_registered"):
        pilot._filter_selected_samples(selected, case_ids=("missing",))
    with pytest.raises(ValueError, match="stage2_family_not_registered"):
        pilot._filter_selected_samples(selected, family_ids=("missing",))


def test_stage2_wrapper_rejects_existing_root_without_overwriting_logs(tmp_path: Path) -> None:
    run_root = tmp_path / "already-there"
    run_root.mkdir()
    existing_log = run_root / "stage2_pilot.stdout.log"
    existing_log.write_text("original output\n", encoding="utf-8")
    script = Path(__file__).resolve().parents[2] / "scripts" / "run_local_vllm_formal_suite.sh"

    result = subprocess.run(
        [str(script)],
        env={
            **os.environ,
            "STATEBUS_LOCAL_VLLM_FORMAL_SUITE": "stage2-pilot",
            "STATEBUS_LOCAL_VLLM_FORMAL_RUN_ID": "already-there",
            "STATEBUS_HOST_RUNS_ROOT": str(tmp_path),
            "STATEBUS_STAGE2_HOST_RUNS_ROOT": str(tmp_path),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "stage2 run root must be new" in result.stderr
    assert existing_log.read_text(encoding="utf-8") == "original output\n"
    assert not (run_root / "container_verify.log").exists()


def test_live_fixed_aggregate_exclusion_cannot_report_pilot_ready(monkeypatch, tmp_path: Path) -> None:
    sample = _sample()
    monkeypatch.setattr(pilot, "_select_samples", lambda: [("family", sample, sample)])
    monkeypatch.setattr(pilot, "_quality", lambda *args, **kwargs: {"passed": True, "failures": []})

    def fixed_runner(sample, root: Path, **kwargs):
        result = _success_runner(sample, root, **kwargs)
        result.update(
            {
                "canonical_aggregate_eligible": False,
                "exclusion_reason": pilot.FIXED_AGGREGATE_EXCLUSION_REASON,
            }
        )
        return result

    runners = {lane: _success_runner for lane in pilot.LANES}
    runners["fixed_structured"] = fixed_runner
    acceptance = pilot.run_stage2_pilot(
        output_root=tmp_path / "run",
        lane_runners=runners,
        timeout_s=1,
    )

    assert acceptance["status"] == "pilot_inconclusive"
    assert acceptance["exit_code"] == pilot.EXIT_INCONCLUSIVE
    assert acceptance["denominator"]["excluded_count"] == len(pilot.SEEDS)
    assert acceptance["denominator"]["arithmetic_closed"] is True
    assert acceptance["no_go_reasons"] == ["canonical_aggregate_exclusion"]


def test_quality_scores_canonical_provenance_without_legacy_revenue_alias(tmp_path: Path) -> None:
    sample = _sample()
    sample.expected_facts = {
        "metric_name": "gross_margin",
        "metric_value": "38",
        "revenue_value": "38",
        "selected_doc_hashes": ["doc-1"],
        "summary_text": "observed",
    }
    output_path = tmp_path / "output.json"
    output_path.write_text("{}\n", encoding="utf-8")
    payload = {
        "metric_name": "gross_margin",
        "metric_value": "38",
        "summary_text": "observed",
        "provenance": {"selected_doc_ids": ["doc-1"]},
    }

    quality = pilot._quality(sample, payload, output_path)

    assert quality["passed"] is True
    assert quality["failures"] == []


def test_gate_pass_accepts_hard_gate_contract() -> None:
    assert pilot._gate_pass({"pass_hard_gate": True, "status": "passed"}, strict=True)
    assert not pilot._gate_pass({"pass_hard_gate": False, "status": "failed"}, strict=True)


def _adaptive_trace_fixture() -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    steps = [
        {"step_id": "retrieve-evidence", "role": "retriever", "capability_id": "retrieve_table_evidence_v1"},
        {"step_id": "execute-analysis", "role": "executor", "capability_id": "execute_analysis_dsl_v2"},
        {"step_id": "compose-report", "role": "summarizer", "capability_id": "compose_claim_set_v2"},
    ]
    rows = []
    for index, step in enumerate(steps, start=1):
        attempt_id = f"attempt-{index}"
        rows.append((step, attempt_id))
    grant_receipts = [
        {
            "step_id": step["step_id"], "attempt_id": attempt_id,
            "approved_plan_hash": "plan-hash", "capability_id": step["capability_id"],
        }
        for step, attempt_id in rows
    ]
    trace = {
        "role_sequence": [step["role"] for step in steps],
        "role_count": {"planner": 0, "retriever": 1, "executor": 1, "summarizer": 1},
        "dispatches": [
            {"step_id": step["step_id"], "attempt_id": attempt_id, "state": "COMPLETED", "output_refs": [f"out-{attempt_id}"], "grant_hash": sha256_digest(grant)}
            for (step, attempt_id), grant in zip(rows, grant_receipts)
        ],
        "attempts": [
            {"step_id": step["step_id"], "attempt_id": attempt_id, "state": "COMPLETED", "owner_role": step["role"]}
            for step, attempt_id in rows
        ],
        "provider_bindings": [
            {"step_id": step["step_id"], "attempt_id": attempt_id, "approved_plan_hash": "plan-hash"}
            for step, attempt_id in rows
        ],
        "grants": [
            {
                "step_id": step["step_id"],
                "attempt_id": attempt_id,
                "approved_plan_hash": "plan-hash",
                "capability_id": step["capability_id"],
            }
            for step, attempt_id in rows
        ],
        "receipts": [
            {
                "step_id": step["step_id"],
                "observed_attempt_id": attempt_id,
                "active_attempt_id": attempt_id,
                "decision": "ACTIVE_ATTEMPT_COMMIT_ALLOWED",
            }
            for step, attempt_id in rows
        ],
    }
    summary = {
        "approved_plan_hash": "plan-hash",
        "approved_steps": steps,
        "role_invocations": [{"role": "planner", "attempts": [{"raw_response_hash": "planner-response"}]}],
        "runtime_completed": True,
        "system_gate_passed": True,
        "trace_validation": {"valid": False, "failed_fields": ["role_sequence", "runtime_attempts"]},
    }
    return trace, summary, grant_receipts


def test_adaptive_trace_gate_accepts_three_step_runtime_and_keeps_legacy_mismatch_diagnostic() -> None:
    trace, summary, grant_receipts = _adaptive_trace_fixture()

    gate = pilot._adaptive_trace_gate(trace, summary, grant_receipts)

    assert gate["valid"] is True
    assert gate["checks"]["persisted_grants_match_dispatch_hashes"] is True
    assert gate["legacy_topology"]["diagnostic"]["valid"] is False


def test_adaptive_trace_gate_rejects_missing_receipt_wrong_step_and_duplicate_attempt() -> None:
    trace, summary, grant_receipts = _adaptive_trace_fixture()

    missing_receipt = {**trace, "receipts": trace["receipts"][:-1]}
    assert pilot._adaptive_trace_gate(missing_receipt, summary, grant_receipts)["valid"] is False

    wrong_step = {**trace, "dispatches": [*trace["dispatches"][:-1], {**trace["dispatches"][-1], "step_id": "unexpected"}]}
    assert pilot._adaptive_trace_gate(wrong_step, summary, grant_receipts)["valid"] is False

    duplicate_attempt = {
        **trace,
        "attempts": [*trace["attempts"], dict(trace["attempts"][0])],
    }
    assert pilot._adaptive_trace_gate(duplicate_attempt, summary, grant_receipts)["valid"] is False

    changed_hash = {**trace, "dispatches": [{**trace["dispatches"][0], "grant_hash": "wrong"}, *trace["dispatches"][1:]]}
    assert pilot._adaptive_trace_gate(changed_hash, summary, grant_receipts)["checks"]["persisted_grants_match_dispatch_hashes"] is False
    assert pilot._adaptive_trace_gate(trace, summary, None)["valid"] is False

    wrong_plan = [{**grant_receipts[0], "approved_plan_hash": "wrong"}, *grant_receipts[1:]]
    assert pilot._adaptive_trace_gate(trace, summary, wrong_plan)["valid"] is False


def test_adaptive_claim_projection_uses_observed_claim_sets_only() -> None:
    assert pilot._claim_summary(
        {
            "claim_sets": [
                {
                    "status": "ready",
                    "claims": [{"claim_text": "Observed gross margin is 38.0."}],
                }
            ],
            "expected_facts": {"summary_text": "must not be used"},
        }
    ) == "Observed gross margin is 38.0."


def test_adaptive_terminal_gate_uses_persisted_terminal_artifacts(tmp_path: Path) -> None:
    (tmp_path / "terminal.json").write_text('{"terminal_status":"success"}\n', encoding="utf-8")
    (tmp_path / "runtime_trace.json").write_text('{"terminal_status":"success"}\n', encoding="utf-8")

    gate = pilot._adaptive_terminal_gate(
        {"terminal_status": None, "runtime_completed": True, "system_gate_passed": True},
        tmp_path,
    )

    assert gate["passed"] is True


def test_pure_financial_metric_uses_public_business_name_not_output_field() -> None:
    from statebus.benchmark.external_text_baseline import _requested_metric_name

    financial = pilot._select_samples()[0][2]
    trend = pilot._select_samples()[1][2]
    assert _requested_metric_name(financial) == "gross_margin"
    assert _requested_metric_name(trend) == "trend_direction"


def test_direct_trend_contract_requires_public_outputs_and_keeps_unknown_source_invalid(monkeypatch, tmp_path: Path) -> None:
    sample = pilot._select_samples()[1][2]
    public_case, source_ids = pilot._stage2_public_case(sample)
    captured: dict[str, object] = {}
    selected_doc_ids = list(source_ids)

    class FakeClient:
        request_events = [{"event": "provider_request", "request_id": "trend-1", "retry_kind": "none"}]

        async def complete(self, messages, *, purpose, response_schema):
            captured.update({"prompt": messages[0].content, "schema": response_schema, "role": purpose})
            return LLMResult(
                text=pilot.stable_json_dumps({
                    "trend_values": "98,109,120", "trend_direction": "increasing",
                    "summary_text": "ACME revenue increased across all three quarters.",
                    "selected_doc_ids": selected_doc_ids,
                }),
                model="qwen3-32b",
            )

    monkeypatch.setattr(pilot, "build_llm_client", lambda config: FakeClient())
    result = pilot._direct_case(sample, tmp_path, public_case=public_case)

    assert result["payload"]["projection_valid"] is True
    assert set(captured["schema"]["required"]) == set(sample.canonical_task_spec.required_outputs)
    assert captured["schema"]["properties"]["trend_direction"]["enum"] == ["increasing", "decreasing", "flat", "mixed"]
    assert source_ids[0] in captured["prompt"]
    assert "expected_facts" not in captured["prompt"]

    selected_doc_ids[:] = ["doc-cross-period-financial"]
    invalid = pilot._direct_case(sample, tmp_path / "invalid", public_case=public_case)
    assert invalid["payload"]["projection_valid"] is False
    assert "unknown_doc_id:doc-cross-period-financial" in invalid["payload"]["projection_errors"]


def test_direct_join_contract_uses_case_output_schema_without_gold(monkeypatch, tmp_path: Path) -> None:
    _family, _minimal, sample = next(
        row for row in pilot._select_samples() if row[1].task_id == "formal-join-001"
    )
    public_case, source_ids = pilot._stage2_public_case(sample)
    captured: dict[str, object] = {}

    class FakeClient:
        request_events = [{"event": "provider_request", "request_id": "join-1", "retry_kind": "none"}]

        async def complete(self, messages, *, purpose, response_schema):
            captured.update({"prompt": messages[0].content, "schema": response_schema, "role": purpose})
            return LLMResult(
                text=pilot.stable_json_dumps({
                    "acme_revenue_value": 120,
                    "beta_revenue_value": 87,
                    "gap_value": 33,
                    "summary_text": "ACME exceeds BETA by 33 in 2026Q1.",
                    "selected_doc_ids": list(source_ids),
                }),
                model="qwen3-32b",
            )

    monkeypatch.setattr(pilot, "build_llm_client", lambda config: FakeClient())
    result = pilot._direct_case(sample, tmp_path, public_case=public_case)

    assert result["payload"]["projection_valid"] is True
    assert result["payload"]["gap_value"] == 33
    schema = captured["schema"]
    assert set(schema["required"]) == set(sample.canonical_task_spec.required_outputs)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["acme_revenue_value"] == {"type": "number"}
    assert schema["properties"]["beta_revenue_value"] == {"type": "number"}
    assert schema["properties"]["gap_value"] == {"type": "number"}
    assert schema["properties"]["selected_doc_ids"]["items"]["enum"] == list(source_ids)
    assert "acme_revenue_value:number" in captured["prompt"]
    assert "expected_facts" not in captured["prompt"]
    assert "const" not in repr(schema)
    assert "default" not in repr(schema)


def test_preflight_checks_model_identity_path_and_context() -> None:
    profile = {"model": "qwen3-32b", "model_path": "/data/models/Qwen3-32B", "max_model_len": "8192"}
    data = {"data": [{"id": "qwen3-32b", "root": "/data/models/Qwen3-32B", "max_model_len": 8192}]}
    assert pilot._validate_served_model(data, profile) == (["qwen3-32b"], [])
    data["data"][0]["max_model_len"] = 4096
    assert any("served_max_model_len_mismatch" in error for error in pilot._validate_served_model(data, profile)[1])
    data["data"][0]["root"] = "/data/models/Qwen3-8B"
    assert any("served_model_path_mismatch" in error for error in pilot._validate_served_model(data, profile)[1])


def test_public_source_closure_is_stable_deduplicated(monkeypatch) -> None:
    sample = _sample()
    monkeypatch.setattr(
        pilot,
        "_load_execution_context",
        lambda sample: SimpleNamespace(public_doc_hashes=("doc-2", "doc-1", "doc-2")),
    )

    public_case, closure = pilot._stage2_public_case(sample)

    assert closure == ("doc-2", "doc-1")
    assert public_case["public_sources"] == ["doc-2", "doc-1"]


def test_direct_parse_failure_preserves_logical_and_physical_request_events(monkeypatch, tmp_path: Path) -> None:
    sample = _sample()
    context = SimpleNamespace(
        public_doc_hashes=("doc-1",),
        route_candidates=(),
        public_evidence_text="public evidence",
    )

    class FakeClient:
        def __init__(self) -> None:
            self.request_events = [
                {"event": "provider_request", "request_id": "r1", "attempt": 1, "retry_kind": "none", "status": "response_received"},
                {"event": "provider_request", "request_id": "r2", "attempt": 2, "retry_kind": "transient_retry", "status": "response_received"},
            ]

        async def complete(self, messages, *, purpose, response_schema):
            del messages, purpose, response_schema
            return LLMResult(text="not-json", model="qwen3-32b")

    monkeypatch.setattr(pilot, "_load_execution_context", lambda sample, public_case=None: context)
    monkeypatch.setattr(pilot, "build_llm_client", lambda config: FakeClient())

    with pytest.raises(ValueError) as raised:
        pilot._direct_case(
            sample,
            tmp_path,
            seed=7,
            public_case={"public_sources": ["doc-1"]},
        )

    logical = raised.value.provider_invocation_events
    physical = raised.value.provider_request_events
    retries = raised.value.retry_events
    assert len(logical) == 1
    assert logical[0]["status"] == "parse_error"
    assert [item["request_id"] for item in physical] == ["r1", "r2"]
    assert [item["request_id"] for item in retries] == ["r2"]


def test_requested_seed_is_propagated_but_effective_seed_remains_separate() -> None:
    config = pilot._seeded_local_config(19)
    assert config.provider_config("default").request_max_attempts == 1
    assert all(config.role_config(role).request_kwargs["seed"] == 19 for role in ("planner", "retriever", "executor", "summarizer"))


def test_deadline_records_late_result_diagnostics() -> None:
    def slow() -> dict[str, object]:
        time.sleep(0.1)
        return {}

    thread_result, thread_error, _ = pilot._invoke_with_deadline(slow, 0.01, process=False)
    assert thread_error == "deadline_exceeded"
    assert thread_result["worker_termination"] == "not_cancelled"
    assert thread_result["late_result"] == "possible_unobserved"

    process_result, process_error, _ = pilot._invoke_with_deadline(slow, 0.01, process=True)
    assert process_error == "deadline_exceeded"
    assert process_result["worker_termination"] == "terminated_after_deadline"
    assert process_result["late_result"] == "not_admitted"


def test_adaptive_request_projection_distinguishes_initial_and_retries() -> None:
    events = pilot._adaptive_provider_request_events(
        {
            "requested_seed": 3,
            "effective_seed": None,
            "role_invocations": [
                {
                    "role": "planner",
                    "attempts": [{"attempt_index": 1}, {"attempt_index": 2}],
                    "request_audit": {
                        "requests": [
                            {"attempt_index": 1, "request_sha256": "p1"},
                            {"attempt_index": 2, "request_sha256": "p2"},
                        ]
                    },
                }
            ],
            "generation_attempts": [
                {"kind": "initial", "raw_response_hash": "g1"},
                {"kind": "repair", "raw_response_hash": "g2"},
            ],
        }
    )
    by_id = {event["request_id"]: event for event in events}
    assert by_id["p1"]["retry_kind"] == "none"
    assert by_id["p2"]["retry_kind"] == "provider_retry"
    assert by_id["g1"]["retry_kind"] == "none"
    assert by_id["g2"]["retry_kind"] == "model_repair"
    assert all(event["requested_seed"] == 3 for event in events)
    assert all(event["effective_seed"] is None for event in events)


def test_interrupted_acceptance_recomputes_partial_slot_accounting(tmp_path: Path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    planned = [{"slot_id": "s1"}, {"slot_id": "s2"}, {"slot_id": "s3"}]
    pilot._json(root / "planned_slots.json", {"slots": planned})
    slot_one = root / "families" / "f" / "lane" / "one"
    slot_two = root / "families" / "f" / "lane" / "two"
    pilot._json(slot_one / "call-start.json", {"slot_id": "s1"})
    pilot._json(slot_one / "raw_row.json", {"slot_id": "s1", "status": "success"})
    pilot._json(slot_two / "call-start.json", {"slot_id": "s2"})

    acceptance = pilot._write_interrupted_acceptance(root, dry_run=False)

    assert acceptance["partial"] is True
    assert acceptance["planned_slots"] == 3
    assert acceptance["observed_rows"] == 1
    assert acceptance["missing"] == ["s2", "s3"]
    assert acceptance["unknown"] == ["s2"]
    assert acceptance["not_started"] == ["s3"]
    assert acceptance["denominator"]["arithmetic_closed"] is True
