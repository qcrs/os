from __future__ import annotations

import json
from pathlib import Path

from statebus.benchmark.model_assist_utility.taskpack import (
    CASE_IDS,
    CALIBRATION_CASE_ID,
    LOGIT_CASE_IDS,
    LOGIT_CALIBRATION_CASE_ID,
    PLAN_POSITIONS,
    SAMPLE_ROOT,
    build_cache_namespace,
    _necessity_checks,
    compile_taskpack,
    load_local_codec,
    logit_policy_order,
    plan_artifact_payload,
)


def test_longtext_plan_is_exactly_28_and_gate_positions_are_included() -> None:
    assert len(PLAN_POSITIONS) == 28
    plan = plan_artifact_payload(compile_taskpack(load_local_codec(), root=SAMPLE_ROOT))
    assert plan["expected_slot_counts"] == {"apc": 8, "logit": 12, "kv": 8}
    assert len(plan["gate_positions"]) == 7
    assert sum(item["module"] == "apc" for item in PLAN_POSITIONS) == 8
    assert sum(item["module"] == "logit" for item in PLAN_POSITIONS) == 12
    assert sum(item["module"] == "kv" for item in PLAN_POSITIONS) == 8
    assert sum(bool(item["gate"]) for item in PLAN_POSITIONS) == 7
    assert [item["case_id"] for item in PLAN_POSITIONS[:2]] == [CASE_IDS[0], CASE_IDS[0]]
    assert [item["case_id"] for item in PLAN_POSITIONS[2:5]] == [LOGIT_CASE_IDS[0]] * 3
    assert [item["module"] for item in PLAN_POSITIONS[:5]] == ["apc", "apc", "logit", "logit", "logit"]
    assert [PLAN_POSITIONS[index]["case_id"] for index in (5, 7, 9)] == [CASE_IDS[1], CASE_IDS[2], CASE_IDS[3]]
    assert [PLAN_POSITIONS[index]["case_id"] for index in (11, 14, 17)] == list(LOGIT_CASE_IDS[1:])


def test_logit_policy_rotation_matches_frozen_plan() -> None:
    for case_index, case_id in enumerate(LOGIT_CASE_IDS):
        observed = tuple(
            item["condition"]
            for item in PLAN_POSITIONS
            if item["module"] == "logit" and item["case_id"] == case_id
        )
        assert observed == logit_policy_order(case_index)


def test_gold_is_separate_from_public_case_definitions() -> None:
    cases = json.loads((SAMPLE_ROOT / "cases.json").read_text(encoding="utf-8"))
    logit_cases = json.loads((SAMPLE_ROOT / "logit_cases.json").read_text(encoding="utf-8"))
    public_text = json.dumps({"cases": cases, "logit_cases": logit_cases}, ensure_ascii=False)
    assert "gold" not in public_text.lower()
    assert not any("q1_fee_usd: " in json.dumps(item) for item in cases["cases"])


def test_compiled_prefixes_are_real_long_contexts_and_block_aligned() -> None:
    taskpack = compile_taskpack(load_local_codec(), root=SAMPLE_ROOT)
    assert tuple(case.case_id for case in taskpack.cases) == CASE_IDS
    assert all(4096 <= case.target_prefix_tokens <= 6400 for case in taskpack.cases)
    assert all(case.definition.target_min_tokens % 16 == 0 for case in taskpack.cases)
    assert all(case.target_prefix_tokens >= case.definition.target_min_tokens for case in taskpack.cases)
    assert taskpack.cases[0].target_prefix_tokens <= 4352
    assert taskpack.cases[2].target_prefix_tokens >= 6144
    assert all(case.source_digest and case.prefix_token_digest for case in taskpack.cases)
    assert taskpack.calibration_case.case_id == CALIBRATION_CASE_ID
    assert taskpack.calibration_case.source_digest != taskpack.cases[-1].source_digest
    assert taskpack.calibration_case.target_prefix_tokens >= 6144
    assert taskpack.calibration_case.definition.target_min_tokens % 16 == 0
    assert taskpack.logit_calibration_case.case_id == LOGIT_CALIBRATION_CASE_ID
    assert taskpack.logit_calibration_case.case_id not in LOGIT_CASE_IDS
    assert all(item["passed"] for item in _necessity_checks(taskpack))


def test_condition_namespaces_preserve_prefix_length_and_kv_pair_identity() -> None:
    codec = load_local_codec()
    case = compile_taskpack(codec, root=SAMPLE_ROOT).cases[0]
    independent = build_cache_namespace(
        case,
        codec,
        run_id="namespace-test-run",
        scope="apc-condition:independent",
    )
    shared = build_cache_namespace(
        case,
        codec,
        run_id="namespace-test-run",
        scope="apc-condition:shared",
        forbidden=(independent["namespace"],),
    )
    assert independent["namespace"] != shared["namespace"]
    assert independent["prefix_token_count"] == shared["prefix_token_count"] == case.target_prefix_tokens
    for layout, assignment in (("independent", independent), ("shared", shared)):
        text = case.layout_text(layout, "executor", namespace=assignment["namespace"])
        assert text.index(assignment["namespace"]) < text.index("# Controlled Long-Text Dossier")

    replay = build_cache_namespace(
        case,
        codec,
        run_id="namespace-test-run",
        scope=f"kv-pair:{case.case_id}",
    )
    continuation = build_cache_namespace(
        case,
        codec,
        run_id="namespace-test-run",
        scope=f"kv-pair:{case.case_id}",
    )
    assert replay == continuation


def test_logit_cases_keep_unresolved_as_explicit_abstention() -> None:
    taskpack = compile_taskpack(load_local_codec(), root=SAMPLE_ROOT)
    unresolved = taskpack.logit_cases[-1]
    assert unresolved.case_id == LOGIT_CASE_IDS[-1]
    assert unresolved.gold_candidate == "insufficient_evidence"
    assert unresolved.gold_outcome == "abstain"
    assert len(unresolved.candidates) == 2


def test_logit_evidence_bundles_meet_frozen_token_ranges() -> None:
    codec = load_local_codec()
    taskpack = compile_taskpack(codec, root=SAMPLE_ROOT)
    for case in taskpack.logit_cases:
        compact_tokens = len(codec.encode(case.evidence_text("compact_evidence")))
        full_tokens = len(codec.encode(case.evidence_text("full_evidence")))
        assert 384 <= compact_tokens <= 768, (case.case_id, compact_tokens)
        assert 2048 <= full_tokens <= 4096, (case.case_id, full_tokens)
