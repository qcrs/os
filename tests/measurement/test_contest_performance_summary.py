import json

import pytest

from tools.measurement.summarize_contest_performance import (
    aggregate_request_dispositions,
    aggregate_request_sections,
    interval_union,
    summarize,
)


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def cohort(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    write_json(root / "stage2_manifest.json", {"lanes": ["pure_text_mas", "fixed_structured"]})
    write_json(root / "acceptance.json", {"passed": False})
    write_json(root / "denominator.json", {"planned": 2})
    write_json(root / "planned_slots.json", {"slots": [{"slot_id": "a"}, {"slot_id": "b"}]})
    rows = []
    for slot, lane, status in (("a", "pure_text_mas", "success"), ("b", "fixed_structured", "failed")):
        rows.append({
            "schema_version": "statebus.stage2_pilot_raw.v2", "slot_id": slot,
            "lane": lane, "task_id": "case", "task_family": "family", "status": status,
            "quality": {"passed": status == "success"}, "lifecycle_state": "completed",
            "e2e_latency_ms": 15, "provider_usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            "provider_request_events": [{"role": "planner", "request_id": slot, "start_ns": 0, "end_ns": 10_000_000,
                                         "response_prompt_tokens": 10, "response_completion_tokens": 2,
                                         "response_total_tokens": 12, "finish_reason": "stop"}],
        })
    write_json(root / "raw_rows.json", rows)
    write_json(root / "warmups.json", [])
    return root, rows


def test_denominator_keeps_failure_and_missing_metrics(tmp_path):
    root, _ = cohort(tmp_path)
    result = summarize([("test", root)], tmp_path / "result")
    denominator = result["denominators"][0]
    assert denominator["planned"] == denominator["recorded"] == denominator["attempted"] == 2
    assert denominator["success"] == denominator["non_success_recorded"] == 1
    assert denominator["arithmetic_closed"] is True
    assert not result["issues"]
    assert result["missing_fields"]["prompt_bytes"] == 2
    assert result["lane_comparisons"][0]["metrics"]["wire_bytes"]["fixed_over_pure"] is None
    assert len(json.loads((tmp_path / "result" / "failure_summary.json").read_text())["rows"]) == 1


def test_missing_duplicate_and_warmup_are_not_success_denominator(tmp_path):
    root, rows = cohort(tmp_path)
    write_json(root / "raw_rows.json", [rows[0], rows[0]])
    write_json(root / "warmups.json", [{**rows[1], "family_id": "family::case", "started_at_ns": 0, "ended_at_ns": 20_000_000}])
    result = summarize([("test", root)], tmp_path / "result")
    assert result["denominators"][0]["missing"] == ["b"]
    assert result["denominators"][0]["duplicate"] == ["a"]
    assert result["denominators"][0]["arithmetic_closed"] is False
    assert len([row for row in result["rows"] if row["phase"] == "warmup"]) == 1
    assert result["rows"][-1]["e2e_ms"] == 20


def test_schema_and_usage_errors_are_reported(tmp_path):
    root, rows = cohort(tmp_path)
    rows[0]["provider_usage"]["total_tokens"] = 99
    write_json(root / "raw_rows.json", rows + [None])
    write_json(root / "planned_slots.json", {"slots": "invalid"})
    result = summarize([("test", root)], tmp_path / "result")
    assert {issue["code"] for issue in result["issues"]} >= {"schema_error", "denominator_mismatch", "usage_mismatch"}


def test_output_protection_and_duplicate_inputs(tmp_path):
    root, _ = cohort(tmp_path)
    with pytest.raises(ValueError, match="outside_input"):
        summarize([("test", root)], root / "result")
    with pytest.raises(ValueError, match="duplicate_input"):
        summarize([("test", root), ("other", root)], tmp_path / "result")
    assert not (tmp_path / "result").exists()


def test_provider_union_does_not_double_count_overlap():
    assert interval_union([{"start_ns": 0, "end_ns": 2_000_000}, {"start_ns": 1_000_000, "end_ns": 3_000_000}]) == 3
    assert interval_union([]) is None
    assert interval_union([{"start_ns": 10, "end_ns": 0}]) is None


def test_request_section_and_disposition_aggregates_keep_units_separate():
    request = {
        "cohort": "c", "phase": "measured", "order": "AB", "lane": "fixed_structured",
        "task_id": "case", "role": "executor", "finish_reason": "stop", "retry_kind": "none",
        "prompt_tokens": 11, "completion_tokens": 3, "provider_ms": 9.0,
        "sections": [
            {"section": "instruction", "bytes": 12},
            {"section": "task", "json_value_bytes": 7},
        ],
    }
    sections = aggregate_request_sections([request])
    assert sections[0]["raw_bytes"]["sum"] == 12
    assert sections[0]["serialized_json_value_bytes"]["status"] == "unsupported"
    assert sections[1]["serialized_json_value_bytes"]["sum"] == 7
    assert sections[1]["raw_bytes"]["status"] == "unsupported"
    dispositions = aggregate_request_dispositions([request])
    assert dispositions[0]["requests"] == 1
    assert dispositions[0]["prompt_tokens"]["sum"] == 11
    assert dispositions[0]["completion_tokens"]["sum"] == 3


def test_preflight_failure_is_separate_from_measured_denominator(tmp_path):
    root, _ = cohort(tmp_path)
    preflight = tmp_path / "preflight"
    preflight.mkdir()
    write_json(preflight / "preflight_error.json", {"status": "preflight_invalid", "error": "timeout"})
    write_json(preflight / "preflight.json", {"status": "failed"})
    result = summarize([("test", root)], tmp_path / "result", preflight_roots=[preflight])
    assert result["denominators"][0]["planned"] == 2
    assert len(result["rows"]) == 2
    assert len(result["preflight_failures"]) == 1
    assert "Preflight Failures" in (tmp_path / "result" / "REPORT.md").read_text()
