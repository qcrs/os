from __future__ import annotations

import json
import math
from multiprocessing.shared_memory import SharedMemory
import os
from pathlib import Path
import struct

import pytest

from runtime.llm import LLMResult, LLMUsage
from v2.contracts import (
    CandidateSurfaceV2,
    LogitProducerReceipt,
    LogitProducerStatus,
)
from v2.control import (
    ControlHeader,
    EventType,
    SuccessResult,
    deframe_control_message,
    frame_control_message,
)
from v2.runtime.logit_gate import make_logit_state_store, run_logit_gate_attempt
from v2.runtime.logit_state import (
    ExactChoiceLogitResult,
    extract_exact_choice_logit_state,
)
from v2.runtime.role_path import (
    ExecutorRoleDecision,
    PlannerRoleResult,
    RetrieverRoleDecision,
    RolePathRunner,
    SummarizerRoleDecision,
    _merge_llm_results,
)
from v2.runtime.smoke import SmokeLayerConfig, run_smoke
from v2.state import (
    LogitStateValidationError,
    publish_logit_state,
    release_logit_state,
    resolve_logit_state,
)


def _surface() -> CandidateSurfaceV2:
    return CandidateSurfaceV2.from_candidate_ids(
        ("route-a::tool-a", "route-b::tool-b")
    )


def _exact_result(
    surface: CandidateSurfaceV2,
    *,
    probabilities: tuple[float, ...],
    other_mass: float,
    attempt_id: str,
    selected_alias: str = "A",
) -> ExactChoiceLogitResult:
    selected_ordinal = surface.aliases.index(selected_alias)
    return ExactChoiceLogitResult(
        payload_bytes=struct.pack(
            f"<{len(probabilities) + 1}f",
            *probabilities,
            other_mass,
        ),
        candidate_probabilities=probabilities,
        other_mass=other_mass,
        selected_alias=selected_alias,
        selected_candidate_id=surface.candidate_id_for_alias(selected_alias),
        selected_candidate_ordinal=selected_ordinal,
        receipt=LogitProducerReceipt(
            request_id=f"request-{attempt_id}",
            attempt_id=attempt_id,
            status=LogitProducerStatus.AVAILABLE,
            candidate_surface_digest=surface.candidate_surface_digest,
            alias_mapping_digest=surface.alias_mapping_digest,
            selected_alias=selected_alias,
            selected_candidate_id=surface.candidate_id_for_alias(selected_alias),
            decision_token_position=1,
            sequence_length=3,
            top_k=len(probabilities) + 1,
        ),
    )


def _choice_token_sequence(
    *,
    selected_alias: str,
    probabilities: dict[str, float],
    leading_text: str = "",
    trailing_text: str = "",
) -> list[dict[str, object]]:
    prefix = f'{leading_text}{{"choice_code":"'
    suffix = f'"}}{trailing_text}'
    return [
        {
            "token": prefix,
            "bytes": list(prefix.encode("utf-8")),
            "logprob": -0.01,
        },
        {
            "token": selected_alias,
            "bytes": list(selected_alias.encode("ascii")),
            "logprob": math.log(probabilities[selected_alias]),
            "top_logprobs": [
                {
                    "token": alias,
                    "bytes": list(alias.encode("ascii")),
                    "logprob": math.log(probability),
                }
                for alias, probability in probabilities.items()
            ],
        },
        {
            "token": suffix,
            "bytes": list(suffix.encode("utf-8")),
            "logprob": -0.01,
        },
    ]


def test_exact_choice_logit_extraction_uses_alias_distribution() -> None:
    surface = _surface()
    result = extract_exact_choice_logit_state(
        completion_text='{"choice_code":"B"}',
        top_logprobs=_choice_token_sequence(
            selected_alias="B",
            probabilities={"A": 0.20, "B": 0.70, "X": 0.05},
            leading_text="\n",
            trailing_text="\n",
        ),
        candidate_surface=surface,
        request_id="request-1",
        attempt_id="attempt-1",
    )

    assert result.available is True
    assert result.selected_candidate_id == "route-b::tool-b"
    assert result.candidate_probabilities == pytest.approx((0.20, 0.70))
    assert result.other_mass == pytest.approx(0.10)
    assert result.top_margin == pytest.approx(0.50)
    assert struct.unpack("<3f", result.payload_bytes) == pytest.approx(
        (0.20, 0.70, 0.10)
    )


def test_exact_choice_logit_extraction_fails_when_candidate_alias_is_absent() -> None:
    result = extract_exact_choice_logit_state(
        completion_text='{"choice_code":"A"}',
        top_logprobs=_choice_token_sequence(
            selected_alias="A",
            probabilities={"A": 0.70, "X": 0.20},
        ),
        candidate_surface=_surface(),
        request_id="request-2",
        attempt_id="attempt-2",
    )

    assert result.available is False
    assert result.receipt.unavailable_reason == "candidate_alias_missing:B"


def test_llm_retry_accounting_retains_only_final_attempt_logprobs() -> None:
    first = LLMResult(
        text="not-json",
        model="stub",
        usage=LLMUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4),
        top_logprobs=[{"token": "old"}],
    )
    final_logprobs = [{"token": "A"}]
    second = LLMResult(
        text='{"choice_code":"A"}',
        model="stub",
        usage=LLMUsage(prompt_tokens=5, completion_tokens=2, total_tokens=7),
        top_logprobs=final_logprobs,
    )

    merged = _merge_llm_results([first, second])

    assert merged.text == second.text
    assert merged.top_logprobs is final_logprobs
    assert merged.usage == LLMUsage(prompt_tokens=8, completion_tokens=3, total_tokens=11)


def test_logit_gate_success_result_protobuf_round_trip() -> None:
    message = SuccessResult(
        header=ControlHeader(
            trace_id="trace-gate",
            task_id="task-gate",
            step_id="logit.gate",
            attempt_id="attempt-1",
            target_role="logit_gate",
            timeout_ms=20_000,
            event_type=EventType.RES_SUCC,
        ),
        output_contract_version="statebus.logit_gate_receipt.v1",
        consumed_state_ref_id="logit-state-1",
        consumer_pid=222,
        producer_pid=111,
        gate_action="retry",
        gate_reason="top_margin_below_threshold",
        selected_alias="A",
        selected_candidate_id="route-a::tool-a",
        top1_alias="A",
        selected_probability=0.45,
        top_margin=0.05,
        normalized_entropy=0.81,
        other_mass=0.15,
        decision_id="decision-1",
        margin_threshold=0.10,
        gate_candidate_count=2,
    )

    parsed = deframe_control_message(frame_control_message(message))

    assert parsed == message


def test_logit_state_cross_pid_consume_and_release(tmp_path: Path) -> None:
    store = make_logit_state_store(tmp_path / "state")
    attempt = run_logit_gate_attempt(
        store=store,
        extraction=_exact_result(
            _surface(),
            probabilities=(0.70, 0.20),
            other_mass=0.10,
            attempt_id="attempt-cross-pid",
        ),
        candidate_surface=_surface(),
        task_id="task-cross-pid",
        trace_id="trace-cross-pid",
        attempt_index=1,
    )

    assert attempt.gate_receipt.action.value == "accept"
    assert attempt.gate_receipt.producer_pid == os.getpid()
    assert attempt.gate_receipt.consumer_pid != os.getpid()
    assert attempt.transport_audit["driver_pid"] == os.getpid()
    assert attempt.transport_audit["worker_pid"] == attempt.gate_receipt.consumer_pid
    assert not (store.metadata_dir / f"{attempt.state_id}.json").exists()
    tombstone = json.loads(Path(attempt.tombstone_path).read_text(encoding="utf-8"))
    assert tombstone["lifecycle_status"] == "released"
    assert tombstone["released_bytes"] == attempt.state_bytes
    assert tombstone["producer_pid"] != tombstone["consumer_pid"]
    assert store.materializations == {}
    assert store.shared_memory_bytes_used == 0
    store.teardown()


def test_logit_state_rejects_expired_lease(tmp_path: Path) -> None:
    store = make_logit_state_store(tmp_path / "state")
    publication = publish_logit_state(
        store=store,
        extraction=_exact_result(
            _surface(),
            probabilities=(0.70, 0.20),
            other_mass=0.10,
            attempt_id="attempt-expired",
        ),
        candidate_surface=_surface(),
        task_id="task-expired",
        trace_id="trace-expired",
        state_id="logit-expired",
        lease_ttl_ms=1,
        now_ns=1_000_000,
    )
    try:
        with pytest.raises(LogitStateValidationError, match="logit_state_expired"):
            resolve_logit_state(
                state_root=store.root,
                ref=publication.ref,
                now_ns=2_000_000,
            )
    finally:
        release_logit_state(
            store=store,
            publication=publication,
            reason="test_cleanup",
        )
        store.teardown()


def test_logit_state_rejects_payload_hash_mismatch(tmp_path: Path) -> None:
    store = make_logit_state_store(tmp_path / "state")
    publication = publish_logit_state(
        store=store,
        extraction=_exact_result(
            _surface(),
            probabilities=(0.70, 0.20),
            other_mass=0.10,
            attempt_id="attempt-corrupt",
        ),
        candidate_surface=_surface(),
        task_id="task-corrupt",
        trace_id="trace-corrupt",
        state_id="logit-corrupt",
    )
    shared = SharedMemory(name=publication.handle.shared_memory_name)
    try:
        shared.buf[0] = (int(shared.buf[0]) + 1) % 256
    finally:
        shared.close()
    try:
        with pytest.raises(LogitStateValidationError, match="logit_state_blob_hash_mismatch"):
            resolve_logit_state(state_root=store.root, ref=publication.ref)
    finally:
        release_logit_state(
            store=store,
            publication=publication,
            reason="test_cleanup",
        )
        store.teardown()


def _install_smoke_role_runner(
    monkeypatch: pytest.MonkeyPatch,
    probability_series: tuple[tuple[float, float, float], ...],
):
    class StubRolePathRunner(RolePathRunner):
        instances: list["StubRolePathRunner"] = []

        def __init__(
            self,
            llm_client=None,
            handoff_mode: str = "structured_collaboration",
            logit_gate_mode: str = "off",
        ) -> None:
            del llm_client
            self.handoff_mode = handoff_mode
            self.logit_gate_mode = logit_gate_mode
            self.executor_calls = 0
            self.rendered_request_audit: dict[str, list[dict[str, object]]] = {}
            self.instances.append(self)

        def plan_workflow(self, **kwargs) -> PlannerRoleResult:
            del kwargs
            return PlannerRoleResult(
                workflow_payload={"steps": []},
                retrieval_objective={"query_text": "logit gate test"},
                raw_text='{"steps":[]}',
                model="stub-model",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                prompt_bytes=100,
            )

        def choose_retrieval_candidate(self, **kwargs) -> RetrieverRoleDecision:
            candidate = kwargs["visible_candidates"][0]
            return RetrieverRoleDecision(
                route=candidate.route,
                tool_name=candidate.tool_name,
                supporting_doc_ids=candidate.supporting_doc_ids,
                reason="stub-retriever",
                candidate_rank=candidate.helper_rank,
                raw_text='{"ok":true}',
                model="stub-model",
                prompt_tokens=11,
                completion_tokens=6,
                total_tokens=17,
                prompt_bytes=110,
            )

        def validate_execution_choice(self, **kwargs) -> ExecutorRoleDecision:
            self.executor_calls += 1
            candidates = kwargs["visible_candidates"]
            surface = CandidateSurfaceV2.from_candidate_ids(
                tuple(candidate.candidate_key() for candidate in candidates[:2])
            )
            p1, p2, other = probability_series[
                min(self.executor_calls - 1, len(probability_series) - 1)
            ]
            exact = _exact_result(
                surface,
                probabilities=(p1, p2),
                other_mass=other,
                attempt_id=f"attempt-{self.executor_calls}",
            )
            selected = candidates[0]
            return ExecutorRoleDecision(
                route=selected.route,
                tool_name=selected.tool_name,
                action_contract=kwargs["action_contract"],
                reason="stub-executor",
                raw_text='{"choice_code":"A"}',
                model="stub-model",
                prompt_tokens=12 + self.executor_calls,
                completion_tokens=7,
                total_tokens=19 + self.executor_calls,
                prompt_bytes=120,
                latency_ms=5.0,
                logit_entropy=exact.entropy,
                logit_confidence_proxy=p1,
                logit_state_bytes=len(exact.payload_bytes),
                logit_top_gap=exact.top_margin,
                logit_sequence_length=3,
                logit_decision_entropy=exact.entropy,
                logit_gate_mode=self.logit_gate_mode,
                logit_state_payload=exact.payload_bytes,
                logit_candidate_surface=surface,
                logit_producer_receipt=exact.receipt,
                logit_exact_result=exact,
                logit_unavailable_reason="",
            )

        def summarize(self, **kwargs) -> SummarizerRoleDecision:
            del kwargs
            return SummarizerRoleDecision(
                summary_text="stub summary ready",
                reusable_steps=("retrieve", "execute"),
                confidence=0.9,
                tags=("stub",),
                raw_text='{"summary":"stub summary ready"}',
                model="stub-model",
                prompt_tokens=13,
                completion_tokens=8,
                total_tokens=21,
                prompt_bytes=130,
            )

        def rendered_request_audit_payload(
            self,
            role: str,
            *,
            include_content: bool = True,
        ) -> dict[str, object]:
            return {
                "schema_version": "statebus.rendered_role_request.v1",
                "role": role,
                "content_persisted": include_content,
                "request_count": 0,
                "requests": [],
            }

    monkeypatch.setattr("v2.runtime.smoke.RolePathRunner", StubRolePathRunner)
    return StubRolePathRunner


def _smoke_layer() -> SmokeLayerConfig:
    return SmokeLayerConfig(
        layer_name="L3-logit-gate",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
    )


def test_smoke_retries_once_and_continues_after_gate_accepts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATEBUS_LOGIT_GATE_MODE", "retry_once")
    runner_type = _install_smoke_role_runner(
        monkeypatch,
        ((0.45, 0.40, 0.15), (0.75, 0.15, 0.10)),
    )

    result = run_smoke(
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        layer_config=_smoke_layer(),
    )

    assert runner_type.instances[-1].executor_calls == 2
    assert result.task_metrics["executor_call_count"] == 2.0
    assert result.task_metrics["logit_extraction_attempt_count"] == 2.0
    assert result.task_metrics["logit_extraction_available_count"] == 2.0
    assert result.task_metrics["logit_state_publish_count"] == 2.0
    assert result.task_metrics["logit_state_consume_count"] == 2.0
    assert result.task_metrics["logit_state_release_count"] == 2.0
    assert result.task_metrics["logit_state_transfer_count"] == 2.0
    assert result.task_metrics["logit_gate_retry_recommended_count"] == 1.0
    assert result.task_metrics["logit_gate_accept_count"] == 1.0
    assert result.task_metrics["logit_retry_trigger_count"] == 1.0
    audit = json.loads(
        (Path(result.workspace_root) / "logs/logit_gate.json").read_text(
            encoding="utf-8"
        )
    )
    assert audit["final_status"] == "accepted_after_retry"
    assert audit["retry_triggered"] is True
    assert [item["gate_receipt"]["action"] for item in audit["attempts"]] == [
        "retry",
        "accept",
    ]


def test_smoke_fails_closed_after_second_low_margin_and_cleans_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATEBUS_LOGIT_GATE_MODE", "retry_once")
    runner_type = _install_smoke_role_runner(
        monkeypatch,
        ((0.45, 0.40, 0.15), (0.44, 0.41, 0.15)),
    )
    runtime_root = tmp_path / "runtime"

    with pytest.raises(RuntimeError, match="low_confidence_after_retry"):
        run_smoke(
            workspace_root=tmp_path / "workspaces",
            runtime_root=runtime_root,
            socket_path=tmp_path / "control.sock",
            layer_config=_smoke_layer(),
        )

    assert runner_type.instances[-1].executor_calls == 2
    audit_path = next((tmp_path / "workspaces").rglob("logs/logit_gate.json"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["final_status"] == "fail_closed"
    assert audit["failure_reason"] == "low_confidence_after_retry"
    assert [item["gate_receipt"]["action"] for item in audit["attempts"]] == [
        "retry",
        "retry",
    ]
    assert len(tuple((runtime_root / "logit_state/tombstones").glob("*.json"))) == 2
    assert not tuple((runtime_root / "logit_state/metadata").glob("*.json"))

    for sidecar_path in (runtime_root / "state/metadata").glob("*.json"):
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        shared_memory_name = str(sidecar.get("shared_memory_name", ""))
        if shared_memory_name:
            with pytest.raises(FileNotFoundError):
                SharedMemory(name=shared_memory_name)
