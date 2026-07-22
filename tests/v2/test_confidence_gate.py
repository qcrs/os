from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from v2.contracts import CandidateSurfaceV2, GateAction, GateDecision, LogitPolicy
from v2.runtime.confidence_gate import FrozenGatePolicy, GateProcessResult
from v2.runtime.logit_controller import (
    LogitActionApplication,
    run_logit_state_lifecycle,
)
from v2.runtime.logit_state import extract_exact_choice_logit_state
from v2.state import LogitStatePublishContext, LogitStateStore
from v2.utils import sha256_digest, stable_json_dumps


def _surface() -> CandidateSurfaceV2:
    return CandidateSurfaceV2.from_candidate_ids(
        ("compare_metric::table_retriever", "summarize_risk::semantic_retriever")
    )


def _extraction(
    *,
    selected_probability: float = 0.7,
    competing_probability: float = 0.2,
):
    prefix = '{"choice_code":"'
    suffix = '"}'
    other_mass = 1.0 - selected_probability - competing_probability
    return extract_exact_choice_logit_state(
        completion_text='{"choice_code":"A"}',
        top_logprobs=[
            {"token": prefix, "bytes": list(prefix.encode("utf-8")), "logprob": 0.0},
            {
                "token": "A",
                "bytes": [65],
                "logprob": math.log(selected_probability),
                "top_logprobs": [
                    {"token": "A", "bytes": [65], "logprob": math.log(selected_probability)},
                    {"token": "B", "bytes": [66], "logprob": math.log(competing_probability)},
                    {"token": "X", "bytes": [88], "logprob": math.log(other_mass)},
                ],
            },
            {"token": suffix, "bytes": list(suffix.encode("utf-8")), "logprob": 0.0},
        ],
        candidate_surface=_surface(),
        request_id="request-1",
        attempt_id="attempt-1",
    )


def _policy() -> FrozenGatePolicy:
    return FrozenGatePolicy(
        temperature=1.0,
        accept_probability_min=0.8,
        verify_probability_min=0.55,
        selection_retry_margin_max=0.1,
    )


def _context(
    *,
    policy_mode: LogitPolicy = LogitPolicy.TELEMETRY_ONLY,
    policy: FrozenGatePolicy | None = None,
) -> LogitStatePublishContext:
    return LogitStatePublishContext(
        task_id="task-1",
        session_id="session-1",
        trace_id="trace-1",
        step_id="execute",
        request_id="request-1",
        attempt_id="attempt-1",
        prompt_sha256="prompt-digest",
        source_evidence_digest="evidence-digest",
        hydration_digest="hydration-digest",
        model_id="model-1",
        model_revision="revision-1",
        tokenizer_id="tokenizer-1",
        tokenizer_revision="tokenizer-revision-1",
        chat_template_sha256="template-digest",
        template_kwargs_sha256="template-kwargs-digest",
        response_schema_digest="response-schema-digest",
        owner_session_id="session-1",
        calibration_version=(
            policy.calibration_version if policy else "telemetry-calibration"
        ),
        threshold_policy_version=(
            policy.threshold_policy_version if policy else "telemetry-threshold"
        ),
        gate_budget_version=(
            policy.gate_budget_version if policy else "max-actions-1"
        ),
        policy=policy_mode,
        lease_ttl_ms=60_000,
    )


def _baseline_application(decision: GateDecision) -> LogitActionApplication:
    return LogitActionApplication(
        after_decision_surface_hash="surface-before",
        selection_changed=False,
        error_recovered=False,
        extra_llm_calls=0,
        extra_tool_calls=0,
        extra_tokens=0,
        extra_latency_ms=0.0,
        extra_evidence_bytes=0,
        outcome=(
            "fail_closed_baseline_preserved"
            if decision.action is GateAction.FAIL_CLOSED
            else "accepted_baseline_selection"
        ),
        fallback_reason=decision.reason if decision.action is GateAction.FAIL_CLOSED else "",
        downstream_ref_ids=("artifact-1",),
    )


def _event_types(result) -> tuple[str, ...]:
    return tuple(str(event["event_type"]) for event in result.events)


def test_frozen_gate_policy_artifact_is_hash_bound(tmp_path: Path) -> None:
    policy = _policy()
    raw = (stable_json_dumps(policy.canonical_payload()) + "\n").encode("utf-8")
    path = tmp_path / "gate-policy.json"
    path.write_bytes(raw)

    loaded = FrozenGatePolicy.load(path, expected_file_hash=sha256_digest(raw))

    assert loaded == policy
    with pytest.raises(ValueError, match="policy file hash mismatch"):
        FrozenGatePolicy.load(path, expected_file_hash="wrong-hash")


def test_logit_controller_completes_ordered_lifecycle_and_effect_receipt(
    tmp_path: Path,
) -> None:
    store = LogitStateStore(tmp_path / "state", state_pool_mode="mmap")
    applied: list[GateDecision] = []

    def _apply(decision: GateDecision) -> LogitActionApplication:
        applied.append(decision)
        return _baseline_application(decision)

    result = run_logit_state_lifecycle(
        store=store,
        extraction=_extraction(),
        candidate_surface=_surface(),
        context=_context(),
        before_decision_surface_hash="surface-before",
        apply_action=_apply,
        effect_root=tmp_path / "effects",
    )

    assert _event_types(result) == (
        "LOGIT_STATE_EXTRACTION_AVAILABLE",
        "LOGIT_STATE_PUBLISHED",
        "LOGIT_STATE_RESOLVED",
        "LOGIT_STATE_CONSUMED",
        "LOGIT_GATE_ACTION_DECIDED",
        "LOGIT_GATE_EFFECT_RECORDED",
        "LOGIT_STATE_RELEASED",
    )
    assert len(applied) == 1
    assert result.gate_decision is applied[0]
    assert result.effect_receipt is not None
    assert result.effect_receipt.action_token == result.gate_decision.action_token
    assert result.release_reason == "consumed"
    assert result.reject_reason == ""
    assert result.producer_pid != result.consumer_pid
    assert result.metrics["logit_state_publish_count"] == 1.0
    assert result.metrics["logit_state_resolve_count"] == 1.0
    assert result.metrics["logit_state_consume_count"] == 1.0
    assert result.metrics["logit_gate_action_count"] == 1.0
    assert result.metrics["logit_gate_effect_count"] == 1.0
    assert result.metrics["logit_state_release_count"] == 1.0
    assert not (store.active_dir / f"{result.state_id}.json").exists()
    assert (store.tombstone_dir / f"{result.state_id}.json").exists()
    assert Path(result.effect_receipt_path).exists()


def test_logit_controller_missing_frozen_policy_fails_closed_to_baseline(
    tmp_path: Path,
) -> None:
    policy = _policy()
    store = LogitStateStore(tmp_path / "state", state_pool_mode="mmap")
    applied: list[GateDecision] = []

    def _apply(decision: GateDecision) -> LogitActionApplication:
        applied.append(decision)
        return _baseline_application(decision)

    result = run_logit_state_lifecycle(
        store=store,
        extraction=_extraction(),
        candidate_surface=_surface(),
        context=_context(policy_mode=LogitPolicy.GATED, policy=policy),
        before_decision_surface_hash="surface-before",
        apply_action=_apply,
        effect_root=tmp_path / "effects",
        policy=None,
    )

    assert len(applied) == 1
    assert applied[0].action is GateAction.FAIL_CLOSED
    assert applied[0].reason == "frozen_calibration_or_policy_missing"
    assert result.effect_receipt is not None
    assert result.effect_receipt.selection_changed is False
    assert result.effect_receipt.outcome == "fail_closed_baseline_preserved"
    assert result.release_reason == "consumed"
    assert result.metrics["logit_state_reject_count"] == 0.0


def test_logit_controller_action_exception_preserves_baseline_and_releases(
    tmp_path: Path,
) -> None:
    store = LogitStateStore(tmp_path / "state", state_pool_mode="mmap")

    def _fail_action(decision: GateDecision) -> LogitActionApplication:
        del decision
        raise RuntimeError("registered_action_failed")

    result = run_logit_state_lifecycle(
        store=store,
        extraction=_extraction(),
        candidate_surface=_surface(),
        context=_context(),
        before_decision_surface_hash="surface-before",
        apply_action=_fail_action,
        effect_root=tmp_path / "effects",
    )

    assert result.reject_reason == "registered_action_failed"
    assert result.release_reason == "action_failed"
    assert result.effect_receipt is not None
    assert result.effect_receipt.after_decision_surface_hash == "surface-before"
    assert result.effect_receipt.selection_changed is False
    assert result.effect_receipt.outcome == "action_failed_baseline_preserved"
    assert result.metrics["logit_state_reject_count"] == 1.0
    assert result.metrics["logit_state_release_count"] == 1.0
    assert _event_types(result)[-3:] == (
        "LOGIT_STATE_REJECTED",
        "LOGIT_GATE_EFFECT_RECORDED",
        "LOGIT_STATE_RELEASED",
    )


def test_logit_controller_does_not_reexecute_duplicate_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LogitStateStore(tmp_path / "state", state_pool_mode="mmap")

    def _duplicate_gate(*, state_root, ref, policy, timeout_s):
        del state_root, policy, timeout_s
        consumer_pid = ref.contract.producer_pid + 1
        return GateProcessResult(
            decision=GateDecision(
                decision_id=f"decision:{ref.state_id}",
                action_token=f"action:{ref.state_id}",
                ref_id=ref.state_id,
                task_id=ref.contract.task_id,
                request_id=ref.contract.request_id,
                consumer_pid=consumer_pid,
                producer_pid=ref.contract.producer_pid,
                action=GateAction.ACCEPT,
                selected_candidate_probability=0.7,
                entropy=0.8,
                normalized_entropy=0.7,
                top_margin=0.5,
                other_mass=0.1,
                candidate_count=ref.contract.candidate_count,
                calibration_version=ref.contract.calibration_version,
                threshold_policy_version=ref.contract.threshold_policy_version,
                gate_budget_version=ref.contract.gate_budget_version,
            ),
            worker_pid=consumer_pid,
            grant_hash="duplicate-grant-hash",
            reused_action_decision=True,
        )

    monkeypatch.setattr(
        "v2.runtime.logit_controller.evaluate_logit_gate_in_subprocess",
        _duplicate_gate,
    )

    def _unexpected_action(decision: GateDecision) -> LogitActionApplication:
        del decision
        raise AssertionError("duplicate action must not be re-executed")

    result = run_logit_state_lifecycle(
        store=store,
        extraction=_extraction(),
        candidate_surface=_surface(),
        context=_context(),
        before_decision_surface_hash="surface-before",
        apply_action=_unexpected_action,
        effect_root=tmp_path / "effects",
    )

    assert result.release_reason == "duplicate_action_not_reexecuted"
    assert result.effect_receipt is None
    assert result.metrics["logit_gate_action_count"] == 0.0
    assert result.metrics["logit_gate_effect_count"] == 0.0
    assert result.metrics["logit_state_consume_count"] == 1.0
    assert result.metrics["logit_state_release_count"] == 1.0


@pytest.mark.parametrize(
    "gate_error",
    (TimeoutError("confidence_gate_timeout"), RuntimeError("confidence_gate_worker_crashed")),
    ids=("timeout", "worker-crash"),
)
def test_logit_controller_gate_failure_always_cleans_up_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_error: BaseException,
) -> None:
    store = LogitStateStore(tmp_path / "state", state_pool_mode="mmap")

    def _fail_gate(**kwargs):
        del kwargs
        raise gate_error

    monkeypatch.setattr(
        "v2.runtime.logit_controller.evaluate_logit_gate_in_subprocess",
        _fail_gate,
    )
    result = run_logit_state_lifecycle(
        store=store,
        extraction=_extraction(),
        candidate_surface=_surface(),
        context=_context(),
        before_decision_surface_hash="surface-before",
        apply_action=_baseline_application,
        effect_root=tmp_path / "effects",
    )

    assert result.reject_reason == str(gate_error)
    assert result.release_reason == "rejected"
    assert result.metrics["logit_state_reject_count"] == 1.0
    assert result.metrics["logit_state_release_count"] == 1.0
    assert not (store.active_dir / f"{result.state_id}.json").exists()
    assert not (store.root / "mmap" / f"{result.state_id}.bin").exists()
    tombstone = json.loads(
        (store.tombstone_dir / f"{result.state_id}.json").read_text(encoding="utf-8")
    )
    assert tombstone["lifecycle_status"] == "released"
    assert tombstone["release_reason"] == "rejected"
