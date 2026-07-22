from __future__ import annotations

import json
import math
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path

import pytest

from v2.contracts import CandidateSurfaceV2, GateAction, LogitPolicy, StorageKind
from v2.runtime.confidence_gate import (
    ConfidenceGateError,
    FrozenGatePolicy,
    evaluate_logit_gate_in_subprocess,
)
from v2.runtime.logit_state import extract_exact_choice_logit_state
from v2.state import LogitStatePublishContext, LogitStateStore


def _choice_tokens(
    *,
    selected_probability: float,
    competing_probability: float,
) -> list[dict[str, object]]:
    prefix = '{"choice_code":"'
    suffix = '"}'
    tail_probability = 1.0 - selected_probability - competing_probability
    assert tail_probability > 0.0
    return [
        {"token": prefix, "bytes": list(prefix.encode("utf-8")), "logprob": 0.0},
        {
            "token": "A",
            "bytes": [65],
            "logprob": math.log(selected_probability),
            "top_logprobs": [
                {"token": "A", "bytes": [65], "logprob": math.log(selected_probability)},
                {"token": "B", "bytes": [66], "logprob": math.log(competing_probability)},
                {"token": "X", "bytes": [88], "logprob": math.log(tail_probability)},
            ],
        },
        {"token": suffix, "bytes": list(suffix.encode("utf-8")), "logprob": 0.0},
    ]


def _surface() -> CandidateSurfaceV2:
    return CandidateSurfaceV2.from_candidate_ids(
        ("compare_metric::table_retriever", "summarize_risk::semantic_retriever")
    )


def _extraction(
    *,
    selected_probability: float = 0.7,
    competing_probability: float = 0.2,
):
    return extract_exact_choice_logit_state(
        completion_text='{"choice_code":"A"}',
        top_logprobs=_choice_tokens(
            selected_probability=selected_probability,
            competing_probability=competing_probability,
        ),
        candidate_surface=_surface(),
        request_id="request-1",
        attempt_id="attempt-1",
    )


def _context(
    *,
    policy_mode: LogitPolicy = LogitPolicy.TELEMETRY_ONLY,
    policy: FrozenGatePolicy | None = None,
    lease_ttl_ms: int = 60_000,
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
        calibration_version=policy.calibration_version if policy else "telemetry-unfrozen",
        threshold_policy_version=(
            policy.threshold_policy_version if policy else "telemetry-no-threshold"
        ),
        gate_budget_version=policy.gate_budget_version if policy else "max-actions-1",
        policy=policy_mode,
        lease_ttl_ms=lease_ttl_ms,
    )


def test_logit_state_shared_memory_cross_pid_consume_release_and_tombstone(tmp_path: Path) -> None:
    store = LogitStateStore(tmp_path / "state", state_pool_mode="shared_memory")
    publication = store.publish(
        extraction=_extraction(),
        candidate_surface=_surface(),
        context=_context(),
    )
    shared_name = publication.ref.shared_memory_name

    result = evaluate_logit_gate_in_subprocess(
        state_root=store.root,
        ref=publication.ref,
    )

    assert publication.ref.storage_kind is StorageKind.SHARED_MEMORY
    assert result.worker_pid != publication.ref.contract.producer_pid
    assert result.decision.consumer_pid == result.worker_pid
    assert result.decision.action is GateAction.ACCEPT
    assert result.decision.selected_candidate_probability == pytest.approx(0.7)
    tombstone = store.release(
        publication.ref.state_id,
        reason="consumed",
        consumer_pid=result.worker_pid,
    )
    assert tombstone["lifecycle_status"] == "released"
    assert not publication.active_sidecar_path.exists()
    assert not (store.root / "metadata" / f"{publication.ref.state_id}.json").exists()
    assert "shared_memory_name" not in tombstone
    assert "probabilities" not in tombstone
    with pytest.raises(FileNotFoundError):
        SharedMemory(name=shared_name)


def test_logit_gate_duplicate_call_returns_original_action_decision(tmp_path: Path) -> None:
    store = LogitStateStore(tmp_path / "state", state_pool_mode="shared_memory")
    publication = store.publish(
        extraction=_extraction(),
        candidate_surface=_surface(),
        context=_context(),
    )
    first = evaluate_logit_gate_in_subprocess(state_root=store.root, ref=publication.ref)
    second = evaluate_logit_gate_in_subprocess(state_root=store.root, ref=publication.ref)
    try:
        assert not first.reused_action_decision
        assert second.reused_action_decision
        assert second.worker_pid != first.worker_pid
        assert second.decision == first.decision
    finally:
        store.release(publication.ref.state_id, reason="consumed")


def test_logit_state_mmap_fallback_is_cross_pid_resolvable_and_unlinked(tmp_path: Path) -> None:
    store = LogitStateStore(tmp_path / "state", state_pool_mode="mmap")
    publication = store.publish(
        extraction=_extraction(),
        candidate_surface=_surface(),
        context=_context(),
    )
    payload_path = store.root / publication.ref.mmap_relpath

    result = evaluate_logit_gate_in_subprocess(state_root=store.root, ref=publication.ref)
    assert publication.ref.storage_kind is StorageKind.MMAP_FILE
    assert result.decision.selected_candidate_probability == pytest.approx(0.7)
    store.release(publication.ref.state_id, reason="consumed", consumer_pid=result.worker_pid)
    assert not payload_path.exists()


def test_gated_policy_produces_distinguishable_bounded_actions(tmp_path: Path) -> None:
    policy = FrozenGatePolicy(
        temperature=1.0,
        accept_probability_min=0.8,
        verify_probability_min=0.55,
        selection_retry_margin_max=0.1,
    )
    store = LogitStateStore(tmp_path / "state", state_pool_mode="shared_memory")
    high = store.publish(
        extraction=_extraction(selected_probability=0.85, competing_probability=0.1),
        candidate_surface=_surface(),
        context=_context(policy_mode=LogitPolicy.GATED, policy=policy),
        state_id="logit-high",
    )
    low_extraction = extract_exact_choice_logit_state(
        completion_text='{"choice_code":"A"}',
        top_logprobs=_choice_tokens(selected_probability=0.45, competing_probability=0.4),
        candidate_surface=_surface(),
        request_id="request-2",
        attempt_id="attempt-2",
    )
    low_context = _context(policy_mode=LogitPolicy.GATED, policy=policy)
    low_context = type(low_context)(
        **{
            **low_context.__dict__,
            "request_id": "request-2",
            "attempt_id": "attempt-2",
        }
    )
    low = store.publish(
        extraction=low_extraction,
        candidate_surface=_surface(),
        context=low_context,
        state_id="logit-low",
    )
    try:
        high_result = evaluate_logit_gate_in_subprocess(
            state_root=store.root,
            ref=high.ref,
            policy=policy,
        )
        low_result = evaluate_logit_gate_in_subprocess(
            state_root=store.root,
            ref=low.ref,
            policy=policy,
        )
        assert high_result.decision.action is GateAction.ACCEPT
        assert low_result.decision.action is GateAction.SELECTION_RETRY_ONCE
        assert high_result.decision.selected_candidate_probability > (
            low_result.decision.selected_candidate_probability
        )
    finally:
        store.release(high.ref.state_id, reason="consumed")
        store.release(low.ref.state_id, reason="consumed")


def test_gated_policy_without_frozen_bundle_fails_closed(tmp_path: Path) -> None:
    policy = FrozenGatePolicy(
        temperature=1.0,
        accept_probability_min=0.8,
        verify_probability_min=0.55,
        selection_retry_margin_max=0.1,
    )
    store = LogitStateStore(tmp_path / "state", state_pool_mode="shared_memory")
    publication = store.publish(
        extraction=_extraction(),
        candidate_surface=_surface(),
        context=_context(policy_mode=LogitPolicy.GATED, policy=policy),
    )
    try:
        result = evaluate_logit_gate_in_subprocess(state_root=store.root, ref=publication.ref)
        assert result.decision.action is GateAction.FAIL_CLOSED
        assert result.decision.reason == "frozen_calibration_or_policy_missing"
    finally:
        store.release(publication.ref.state_id, reason="rejected")


def test_payload_hash_corruption_fails_closed_and_can_be_released(tmp_path: Path) -> None:
    store = LogitStateStore(tmp_path / "state", state_pool_mode="shared_memory")
    publication = store.publish(
        extraction=_extraction(),
        candidate_surface=_surface(),
        context=_context(),
    )
    shared = SharedMemory(name=publication.ref.shared_memory_name)
    try:
        shared.buf[0] = (int(shared.buf[0]) + 1) % 256
    finally:
        shared.close()
    try:
        with pytest.raises(ConfidenceGateError, match="logit_state_blob_hash_mismatch"):
            evaluate_logit_gate_in_subprocess(state_root=store.root, ref=publication.ref)
    finally:
        store.release(publication.ref.state_id, reason="rejected")


def test_cross_task_sidecar_tamper_is_rejected(tmp_path: Path) -> None:
    store = LogitStateStore(tmp_path / "state", state_pool_mode="mmap")
    publication = store.publish(
        extraction=_extraction(),
        candidate_surface=_surface(),
        context=_context(),
    )
    sidecar = json.loads(publication.active_sidecar_path.read_text(encoding="utf-8"))
    sidecar["ref"]["contract"]["task_id"] = "other-task"
    publication.active_sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    try:
        with pytest.raises(ConfidenceGateError, match="logit_gate_control_ref_mismatch"):
            evaluate_logit_gate_in_subprocess(state_root=store.root, ref=publication.ref)
    finally:
        store.release(publication.ref.state_id, reason="rejected")


def test_expired_state_reaper_unlinks_payload_and_writes_terminal_tombstone(tmp_path: Path) -> None:
    store = LogitStateStore(tmp_path / "state", state_pool_mode="mmap")
    publication = store.publish(
        extraction=_extraction(),
        candidate_surface=_surface(),
        context=_context(lease_ttl_ms=1),
        now_ns=1_000_000,
    )
    payload_path = store.root / publication.ref.mmap_relpath

    released = store.release_expired(now_ns=2_000_001)

    assert released == (publication.ref.state_id,)
    assert not payload_path.exists()
    tombstone_path = store.tombstone_dir / f"{publication.ref.state_id}.json"
    tombstone = json.loads(tombstone_path.read_text(encoding="utf-8"))
    assert tombstone["lifecycle_status"] == "released"
    assert tombstone["release_reason"] == "expired"
