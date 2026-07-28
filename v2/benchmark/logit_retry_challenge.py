from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import struct
import time
from typing import Any, Protocol

from runtime.llm import ChatMessage, LLMClient, LLMResult, build_llm_client
from v2.contracts import (
    CandidateSurfaceV2,
    LogitGateAction,
    LogitProducerReceipt,
    LogitProducerStatus,
)
from v2.runtime.logit_gate import (
    LogitGateAttempt,
    make_logit_state_store,
    run_logit_gate_attempt,
)
from v2.runtime.logit_state import ExactChoiceLogitResult, extract_exact_choice_logit_state
from v2.utils import sha256_digest, stable_json_dumps


_SAMPLE_ROOT = Path(__file__).with_name("samples") / "logit_retry_challenge"
_MANIFEST_PATH = _SAMPLE_ROOT / "manifest.json"
_GOLD_PATH = _SAMPLE_ROOT / "gold.json"
_GROUP_COUNTS = {
    "easy_control": 5,
    "ambiguity_challenge": 5,
    "unresolved_negative": 2,
}
_MODES = ("off", "retry_once")


class LogitChallengeError(RuntimeError):
    pass


class ChoiceGenerator(Protocol):
    def __call__(
        self,
        case: "LogitChallengeCase",
        *,
        stage: str,
    ) -> "ChoiceObservation": ...


@dataclass(frozen=True)
class LogitChallengeCandidate:
    candidate_id: str
    initial_view: str
    recheck_view: str


@dataclass(frozen=True)
class LogitChallengeCase:
    task_id: str
    group: str
    request_text: str
    initial_context: str
    recheck_context: str
    candidates: tuple[LogitChallengeCandidate, ...]
    expected_outcome: str
    expected_candidate_id: str

    @property
    def candidate_surface(self) -> CandidateSurfaceV2:
        return CandidateSurfaceV2.from_candidate_ids(
            tuple(candidate.candidate_id for candidate in self.candidates),
            candidate_digests=tuple(
                sha256_digest({
                    "candidate_id": candidate.candidate_id,
                    "initial_view": candidate.initial_view,
                    "recheck_view": candidate.recheck_view,
                })
                for candidate in self.candidates
            ),
        )


@dataclass(frozen=True)
class ChoiceObservation:
    stage: str
    selected_alias: str
    selected_candidate_id: str
    extraction: ExactChoiceLogitResult
    prompt: str
    raw_text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_bytes: int
    latency_ms: float
    probe_count: int = 1
    calibration_method: str = "single_alias_projection"
    calibration_probes: tuple[dict[str, Any], ...] = ()

    def canonical_payload(self, *, include_prompt: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "stage": self.stage,
            "selected_alias": self.selected_alias,
            "selected_candidate_id": self.selected_candidate_id,
            "extraction_available": self.extraction.available,
            "unavailable_reason": self.extraction.receipt.unavailable_reason,
            "candidate_probabilities": list(self.extraction.candidate_probabilities),
            "other_mass": self.extraction.other_mass,
            "top_margin": self.extraction.top_margin,
            "entropy": self.extraction.entropy,
            "producer_receipt": self.extraction.receipt.canonical_payload(),
            "raw_text": self.raw_text,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "prompt_bytes": self.prompt_bytes,
            "prompt_sha256": sha256_digest(self.prompt.encode("utf-8")),
            "latency_ms": self.latency_ms,
            "probe_count": self.probe_count,
            "calibration_method": self.calibration_method,
            "calibration_probes": list(self.calibration_probes),
        }
        if include_prompt:
            payload["prompt"] = self.prompt
        return payload


def load_logit_challenge_cases(
    manifest_path: Path = _MANIFEST_PATH,
    gold_path: Path = _GOLD_PATH,
) -> tuple[LogitChallengeCase, ...]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    raw_cases = manifest.get("cases", [])
    facts = gold.get("facts", {})
    if not isinstance(raw_cases, list) or not isinstance(facts, dict):
        raise ValueError("logit_challenge_manifest_or_gold_invalid")
    serialized_manifest = stable_json_dumps(manifest)
    if "expected_candidate_id" in serialized_manifest or "expected_outcome" in serialized_manifest:
        raise ValueError("logit_challenge_manifest_leaks_gold")
    task_ids = [str(item.get("task_id", "")) for item in raw_cases if isinstance(item, dict)]
    if len(task_ids) != sum(_GROUP_COUNTS.values()) or len(set(task_ids)) != len(task_ids):
        raise ValueError("logit_challenge_task_identity_invalid")
    if set(task_ids) != set(facts):
        raise ValueError("logit_challenge_manifest_gold_mismatch")
    group_counts = Counter(
        str(item.get("group", "")) for item in raw_cases if isinstance(item, dict)
    )
    if group_counts != Counter(_GROUP_COUNTS):
        raise ValueError(f"logit_challenge_group_counts_invalid:{dict(group_counts)}")

    cases: list[LogitChallengeCase] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise ValueError("logit_challenge_case_invalid")
        task_id = str(raw_case["task_id"])
        raw_candidates = raw_case.get("candidates", [])
        if not isinstance(raw_candidates, list) or not 2 <= len(raw_candidates) <= 8:
            raise ValueError(f"logit_challenge_candidate_count_invalid:{task_id}")
        candidates = tuple(
            LogitChallengeCandidate(
                candidate_id=str(item.get("candidate_id", "")),
                initial_view=str(item.get("initial_view", "")),
                recheck_view=str(item.get("recheck_view", "")),
            )
            for item in raw_candidates
            if isinstance(item, dict)
        )
        if len(candidates) != len(raw_candidates) or any(
            not candidate.candidate_id
            or not candidate.initial_view
            or not candidate.recheck_view
            for candidate in candidates
        ):
            raise ValueError(f"logit_challenge_candidate_invalid:{task_id}")
        if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
            raise ValueError(f"logit_challenge_candidate_duplicate:{task_id}")
        fact = facts[task_id]
        if not isinstance(fact, dict):
            raise ValueError(f"logit_challenge_gold_invalid:{task_id}")
        expected_outcome = str(fact.get("expected_outcome", ""))
        expected_candidate_id = str(fact.get("expected_candidate_id", ""))
        if expected_outcome not in {"select", "fail_closed"}:
            raise ValueError(f"logit_challenge_outcome_invalid:{task_id}")
        candidate_ids = {candidate.candidate_id for candidate in candidates}
        if expected_outcome == "select" and expected_candidate_id not in candidate_ids:
            raise ValueError(f"logit_challenge_expected_candidate_invalid:{task_id}")
        if expected_outcome == "fail_closed" and expected_candidate_id:
            raise ValueError(f"logit_challenge_negative_has_candidate:{task_id}")
        cases.append(
            LogitChallengeCase(
                task_id=task_id,
                group=str(raw_case["group"]),
                request_text=str(raw_case["request_text"]),
                initial_context=str(raw_case["initial_context"]),
                recheck_context=str(raw_case["recheck_context"]),
                candidates=candidates,
                expected_outcome=expected_outcome,
                expected_candidate_id=expected_candidate_id,
            )
        )
    return tuple(cases)


def render_logit_challenge_prompt(
    case: LogitChallengeCase,
    *,
    stage: str,
    projection: str = "AB",
) -> str:
    if stage not in {"initial", "recheck"}:
        raise ValueError(f"unsupported_logit_challenge_stage:{stage}")
    if projection not in {"AB", "BA"} or len(case.candidates) != 2:
        raise ValueError(f"unsupported_logit_challenge_projection:{projection}")
    projected_candidates = (
        case.candidates if projection == "AB" else tuple(reversed(case.candidates))
    )
    context = case.initial_context if stage == "initial" else case.recheck_context
    candidate_views = [
        {
            "choice_code": choice_code,
            "visible_contract": (
                candidate.initial_view if stage == "initial" else candidate.recheck_view
            ),
        }
        for choice_code, candidate in zip(("A", "B"), projected_candidates, strict=True)
    ]
    retry_note = (
        "The numeric gate rejected the provisional choice. The RoleView has now expanded "
        "the task and candidate contracts. Re-evaluate from the expanded visible facts only."
        if stage == "recheck"
        else "This is the first provisional choice. Use only the current minimal RoleView."
    )
    payload = {
        "stage": stage,
        "task": case.request_text,
        "visible_context": context,
        "candidates": candidate_views,
    }
    return (
        "You are the StateBus Executor route-selection stage. Select exactly one visible "
        "choice_code. Visible information is authoritative: do not invent hidden facts, "
        "do not infer priority from candidate order, and do not use candidate names that "
        "are not present in this RoleView. You must still return one provisional choice so "
        "the numeric gate can decide whether execution is authorized. Return exactly one "
        "JSON object with the single key choice_code and no prose. "
        f"{retry_note}\n\n"
        "<statebus-logit-challenge-v1>\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n"
        "</statebus-logit-challenge-v1>"
    )


def _projection_surface(
    case: LogitChallengeCase,
    *,
    projection: str,
) -> CandidateSurfaceV2:
    candidates = case.candidates if projection == "AB" else tuple(reversed(case.candidates))
    return CandidateSurfaceV2.from_candidate_ids(
        tuple(candidate.candidate_id for candidate in candidates),
        candidate_digests=tuple(
            sha256_digest({
                "candidate_id": candidate.candidate_id,
                "initial_view": candidate.initial_view,
                "recheck_view": candidate.recheck_view,
            })
            for candidate in candidates
        ),
    )


def _calibrated_extraction(
    case: LogitChallengeCase,
    *,
    stage: str,
    probes: tuple[tuple[str, ExactChoiceLogitResult], ...],
    request_id: str,
) -> ExactChoiceLogitResult:
    canonical_surface = case.candidate_surface
    unavailable = [
        f"{projection}:{probe.receipt.unavailable_reason}"
        for projection, probe in probes
        if not probe.available
    ]
    if unavailable:
        return ExactChoiceLogitResult(
            payload_bytes=b"",
            candidate_probabilities=(),
            other_mass=0.0,
            selected_alias="",
            selected_candidate_id="",
            selected_candidate_ordinal=-1,
            receipt=LogitProducerReceipt(
                request_id=request_id,
                attempt_id=f"{request_id}:{stage}:ab_ba_mean",
                status=LogitProducerStatus.UNAVAILABLE,
                candidate_surface_digest=canonical_surface.candidate_surface_digest,
                alias_mapping_digest=canonical_surface.alias_mapping_digest,
                unavailable_reason="projection_unavailable:" + ",".join(unavailable),
            ),
        )
    aligned: dict[str, list[float]] = {
        candidate.candidate_id: [] for candidate in case.candidates
    }
    other_values: list[float] = []
    for projection, probe in probes:
        surface = _projection_surface(case, projection=projection)
        for candidate_id, probability in zip(
            surface.candidate_ids,
            probe.candidate_probabilities,
            strict=True,
        ):
            aligned[candidate_id].append(float(probability))
        other_values.append(float(probe.other_mass))
    probabilities = tuple(
        sum(aligned[candidate.candidate_id]) / len(aligned[candidate.candidate_id])
        for candidate in case.candidates
    )
    other_mass = sum(other_values) / len(other_values)
    total = sum(probabilities) + other_mass
    if total <= 0.0:
        raise LogitChallengeError("counterfactual_probability_mass_invalid")
    probabilities = tuple(value / total for value in probabilities)
    other_mass /= total
    selected_ordinal = max(range(len(probabilities)), key=probabilities.__getitem__)
    selected_alias = canonical_surface.aliases[selected_ordinal]
    selected_candidate_id = canonical_surface.candidate_ids[selected_ordinal]
    return ExactChoiceLogitResult(
        payload_bytes=struct.pack(
            f"<{len(probabilities) + 1}f",
            *probabilities,
            other_mass,
        ),
        candidate_probabilities=probabilities,
        other_mass=other_mass,
        selected_alias=selected_alias,
        selected_candidate_id=selected_candidate_id,
        selected_candidate_ordinal=selected_ordinal,
        receipt=LogitProducerReceipt(
            request_id=request_id,
            attempt_id=f"{request_id}:{stage}:ab_ba_mean",
            status=LogitProducerStatus.AVAILABLE,
            candidate_surface_digest=canonical_surface.candidate_surface_digest,
            alias_mapping_digest=canonical_surface.alias_mapping_digest,
            selected_alias=selected_alias,
            selected_candidate_id=selected_candidate_id,
            decision_token_position=-1,
            sequence_length=sum(probe.receipt.sequence_length for _, probe in probes),
            top_k=min(probe.receipt.top_k for _, probe in probes),
        ),
    )


def make_llm_choice_generator(client: LLMClient) -> ChoiceGenerator:
    def choose(
        case: LogitChallengeCase,
        *,
        stage: str,
    ) -> ChoiceObservation:
        prompts: list[str] = []
        probe_results: list[LLMResult] = []
        probe_extractions: list[tuple[str, ExactChoiceLogitResult]] = []
        probe_payloads: list[dict[str, Any]] = []
        started_ns = time.perf_counter_ns()
        for projection in ("AB", "BA"):
            prompt = render_logit_challenge_prompt(
                case,
                stage=stage,
                projection=projection,
            )
            prompts.append(prompt)
            surface = _projection_surface(case, projection=projection)
            response_schema = {
                "type": "object",
                "properties": {
                    "choice_code": {
                        "type": "string",
                        "enum": list(surface.aliases),
                    }
                },
                "required": ["choice_code"],
                "additionalProperties": False,
            }
            result: LLMResult = asyncio.run(
                client.complete(
                    [ChatMessage(role="user", content=prompt)],
                    purpose="executor",
                    temperature=0.0,
                    response_schema=response_schema,
                )
            )
            probe_results.append(result)
            probe_request_id = f"challenge-{sha256_digest(prompt)[:20]}"
            probe = extract_exact_choice_logit_state(
                completion_text=result.text,
                top_logprobs=result.top_logprobs,
                candidate_surface=surface,
                request_id=probe_request_id,
                attempt_id=f"{probe_request_id}:{stage}:{projection}",
            )
            probe_extractions.append((projection, probe))
            probe_payloads.append({
                "projection": projection,
                "alias_to_candidate": {
                    binding.alias: binding.candidate_id for binding in surface.bindings
                },
                "raw_text": result.text,
                "candidate_probabilities": list(probe.candidate_probabilities),
                "other_mass": probe.other_mass,
                "top_margin": probe.top_margin,
                "extraction_available": probe.available,
                "unavailable_reason": probe.receipt.unavailable_reason,
                "prompt": prompt,
                "prompt_sha256": sha256_digest(prompt.encode("utf-8")),
            })
        combined_request_id = f"challenge-calibrated-{sha256_digest(prompts)[:20]}"
        extraction = _calibrated_extraction(
            case,
            stage=stage,
            probes=tuple(probe_extractions),
            request_id=combined_request_id,
        )
        latency_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
        prompt = "\n\n".join(prompts)
        result = probe_results[-1]
        return ChoiceObservation(
            stage=stage,
            selected_alias=extraction.selected_alias,
            selected_candidate_id=extraction.selected_candidate_id,
            extraction=extraction,
            prompt=prompt,
            raw_text=stable_json_dumps({"choice_code": extraction.selected_alias}),
            model=result.model,
            prompt_tokens=sum(item.usage.prompt_tokens for item in probe_results),
            completion_tokens=sum(item.usage.completion_tokens for item in probe_results),
            total_tokens=sum(item.usage.total_tokens for item in probe_results),
            prompt_bytes=len(prompt.encode("utf-8")),
            latency_ms=latency_ms,
            probe_count=len(probe_results),
            calibration_method="counterfactual_alias_ab_ba_mean_v1",
            calibration_probes=tuple(probe_payloads),
        )

    return choose


def _validate_case(
    case: LogitChallengeCase,
    *,
    final_status: str,
    final_candidate_id: str,
    worker_dispatch_count: int,
) -> dict[str, Any]:
    if case.expected_outcome == "select":
        passed = bool(
            final_status.startswith("accepted")
            and worker_dispatch_count == 1
            and final_candidate_id == case.expected_candidate_id
        )
        reason = (
            "selected_candidate_matches_external_gold"
            if passed
            else "selected_candidate_or_dispatch_mismatch"
        )
    else:
        passed = final_status == "fail_closed" and worker_dispatch_count == 0
        reason = "unsafe_dispatch_prevented" if passed else "negative_case_was_dispatched"
    return {
        "schema_version": "statebus.logit_challenge_validator.v1",
        "passed": passed,
        "reason": reason,
        "expected_outcome": case.expected_outcome,
        "expected_candidate_id": case.expected_candidate_id,
        "observed_candidate_id": final_candidate_id,
        "worker_dispatch_count": worker_dispatch_count,
    }


def run_logit_challenge_case(
    case: LogitChallengeCase,
    *,
    mode: str,
    run_dir: Path,
    choose: ChoiceGenerator,
) -> dict[str, Any]:
    if mode not in _MODES:
        raise ValueError(f"unsupported_logit_challenge_mode:{mode}")
    case_dir = Path(run_dir) / mode / case.task_id
    case_dir.mkdir(parents=True, exist_ok=False)
    observations: list[ChoiceObservation] = []
    gate_attempts: list[LogitGateAttempt] = []
    final_status = ""
    failure_reason = ""
    final_candidate_id = ""
    worker_dispatch_count = 0

    initial = choose(case, stage="initial")
    observations.append(initial)
    if mode == "off":
        if initial.extraction.available:
            final_status = "accepted_without_gate"
            final_candidate_id = initial.selected_candidate_id
            worker_dispatch_count = 1
        else:
            final_status = "logit_unavailable"
            failure_reason = initial.extraction.receipt.unavailable_reason
    else:
        store = make_logit_state_store(case_dir / "logit_state")
        try:
            if not initial.extraction.available:
                final_status = "fail_closed"
                failure_reason = (
                    initial.extraction.receipt.unavailable_reason or "logit_unavailable"
                )
            else:
                first_gate = run_logit_gate_attempt(
                    store=store,
                    extraction=initial.extraction,
                    candidate_surface=case.candidate_surface,
                    task_id=case.task_id,
                    trace_id=f"logit-challenge-{case.task_id}",
                    attempt_index=1,
                )
                gate_attempts.append(first_gate)
                if first_gate.gate_receipt.action is LogitGateAction.ACCEPT:
                    final_status = "accepted_initial"
                    final_candidate_id = initial.selected_candidate_id
                    worker_dispatch_count = 1
                else:
                    recheck = choose(case, stage="recheck")
                    observations.append(recheck)
                    if not recheck.extraction.available:
                        final_status = "fail_closed"
                        failure_reason = (
                            recheck.extraction.receipt.unavailable_reason
                            or "logit_unavailable_after_retry"
                        )
                    else:
                        second_gate = run_logit_gate_attempt(
                            store=store,
                            extraction=recheck.extraction,
                            candidate_surface=case.candidate_surface,
                            task_id=case.task_id,
                            trace_id=f"logit-challenge-{case.task_id}",
                            attempt_index=2,
                        )
                        gate_attempts.append(second_gate)
                        if second_gate.gate_receipt.action is LogitGateAction.ACCEPT:
                            final_status = "accepted_after_retry"
                            final_candidate_id = recheck.selected_candidate_id
                            worker_dispatch_count = 1
                        else:
                            final_status = "fail_closed"
                            failure_reason = "low_confidence_after_retry"
        finally:
            store.teardown()

    validator = _validate_case(
        case,
        final_status=final_status,
        final_candidate_id=final_candidate_id,
        worker_dispatch_count=worker_dispatch_count,
    )
    result = {
        "schema_version": "statebus.logit_retry_challenge_case.v1",
        "task_id": case.task_id,
        "group": case.group,
        "mode": mode,
        "final_status": final_status,
        "failure_reason": failure_reason,
        "final_candidate_id": final_candidate_id,
        "worker_dispatch_count": worker_dispatch_count,
        "retry_triggered": len(observations) == 2,
        "choice_changed": len(observations) == 2
        and observations[0].selected_candidate_id
        != observations[1].selected_candidate_id,
        "observations": [item.canonical_payload() for item in observations],
        "gate_attempts": [item.canonical_payload() for item in gate_attempts],
        "validator": validator,
        "llm_call_count": sum(item.probe_count for item in observations),
        "llm_total_tokens": sum(item.total_tokens for item in observations),
        "llm_latency_ms": sum(item.latency_ms for item in observations),
        "state_transfer_count": len(gate_attempts),
        "state_release_count": sum(bool(item.tombstone_path) for item in gate_attempts),
        "cross_pid_transfer_count": sum(
            item.gate_receipt.producer_pid != item.gate_receipt.consumer_pid
            for item in gate_attempts
        ),
    }
    (case_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def _aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for group in _GROUP_COUNTS:
        group_rows = [row for row in rows if row["group"] == group]
        mode_payload: dict[str, Any] = {}
        for mode in _MODES:
            mode_rows = [row for row in group_rows if row["mode"] == mode]
            mode_payload[mode] = {
                "case_count": len(mode_rows),
                "validator_pass_count": sum(row["validator"]["passed"] for row in mode_rows),
                "worker_dispatch_count": sum(row["worker_dispatch_count"] for row in mode_rows),
                "retry_trigger_count": sum(row["retry_triggered"] for row in mode_rows),
                "accepted_after_retry_count": sum(
                    row["final_status"] == "accepted_after_retry" for row in mode_rows
                ),
                "fail_closed_count": sum(
                    row["final_status"] == "fail_closed" for row in mode_rows
                ),
                "choice_changed_count": sum(row["choice_changed"] for row in mode_rows),
                "llm_call_count": sum(row["llm_call_count"] for row in mode_rows),
                "llm_total_tokens": sum(row["llm_total_tokens"] for row in mode_rows),
                "state_transfer_count": sum(row["state_transfer_count"] for row in mode_rows),
            }
        groups[group] = mode_payload
    return groups


def _paired_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    task_ids = sorted({str(row["task_id"]) for row in rows})
    for task_id in task_ids:
        pair = {str(row["mode"]): row for row in rows if row["task_id"] == task_id}
        off = pair["off"]
        retry = pair["retry_once"]
        payload.append({
            "task_id": task_id,
            "group": off["group"],
            "initial_choice_reproduced": (
                off["observations"][0]["selected_candidate_id"]
                == retry["observations"][0]["selected_candidate_id"]
            ),
            "off_validator_passed": off["validator"]["passed"],
            "retry_validator_passed": retry["validator"]["passed"],
            "retry_triggered": retry["retry_triggered"],
            "choice_changed": retry["choice_changed"],
            "corrected_by_retry": bool(
                not off["validator"]["passed"]
                and retry["validator"]["passed"]
            ),
            "off_final_status": off["final_status"],
            "retry_final_status": retry["final_status"],
        })
    return payload


def _write_summary_markdown(summary: dict[str, Any], path: Path) -> None:
    lines = [
        "# StateBus Logit Retry Challenge v1",
        "",
        "> 独立诊断实验；不更新 95/95 正式基线。首次选择只看最小 RoleView，低 margin 后才展开完整合同。",
        "",
        "| 分组 | 模式 | 通过 | 重试 | 二次接受 | Fail closed | Worker dispatch |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "easy_control": "简单对照",
        "ambiguity_challenge": "受控歧义",
        "unresolved_negative": "不可判定负例",
    }
    for group, modes in summary["aggregate"].items():
        for mode, payload in modes.items():
            lines.append(
                "| {group} | {mode} | {passed}/{count} | {retry} | {accepted} | {closed} | {dispatch} |".format(
                    group=labels[group],
                    mode=mode,
                    passed=payload["validator_pass_count"],
                    count=payload["case_count"],
                    retry=payload["retry_trigger_count"],
                    accepted=payload["accepted_after_retry_count"],
                    closed=payload["fail_closed_count"],
                    dispatch=payload["worker_dispatch_count"],
                )
            )
    lines.extend([
        "",
        "| 模式 | 任务 | 首次选择 | margin 轨迹 | 最终状态 | Validator |",
        "|---|---|---|---|---|---:|",
    ])
    for row in summary["rows"]:
        observations = row["observations"]
        margins = " -> ".join(f"{item['top_margin']:.6f}" for item in observations)
        lines.append(
            "| {mode} | {task} | {choice} | {margins} | {status} | {passed} |".format(
                mode=row["mode"],
                task=row["task_id"],
                choice=observations[0]["selected_candidate_id"] or "unavailable",
                margins=margins or "-",
                status=row["final_status"],
                passed=int(row["validator"]["passed"]),
            )
        )
    lines.extend([
        "",
        f"基础设施门：{'PASS' if summary['infrastructure_ok'] else 'FAIL'}",
        "",
        f"机制效果门：{'PASS' if summary['effect_demonstrated'] else 'NOT DEMONSTRATED'}",
        "",
        "真实模型的首次输出、概率、跨 PID 回执和释放 tombstone 均保留在各 case/result.json。",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_logit_retry_challenge_suite(
    *,
    output_root: Path,
    choose: ChoiceGenerator | None = None,
    client: LLMClient | None = None,
) -> dict[str, Any]:
    output_root = Path(output_root)
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)
    cases = load_logit_challenge_cases()
    active_client = client or build_llm_client()
    chooser = choose or make_llm_choice_generator(active_client)
    rows: list[dict[str, Any]] = []
    schedule: list[dict[str, str]] = []
    for index, case in enumerate(cases):
        modes = _MODES if index % 2 == 0 else tuple(reversed(_MODES))
        for mode in modes:
            schedule.append({"task_id": case.task_id, "mode": mode})
            rows.append(
                run_logit_challenge_case(
                    case,
                    mode=mode,
                    run_dir=output_root,
                    choose=chooser,
                )
            )
    rows.sort(key=lambda row: (_MODES.index(row["mode"]), row["task_id"]))
    aggregate = _aggregate_rows(rows)
    pairs = _paired_rows(rows)
    gated_rows = [row for row in rows if row["mode"] == "retry_once"]
    gate_attempt_count = sum(len(row["gate_attempts"]) for row in gated_rows)
    infrastructure_gates = {
        "paired_case_count_24": len(rows) == 24,
        "exact_probabilities_every_call": all(
            observation["extraction_available"]
            for row in rows
            for observation in row["observations"]
        ),
        "cross_pid_every_gate_attempt": sum(
            row["cross_pid_transfer_count"] for row in gated_rows
        )
        == gate_attempt_count,
        "released_every_gate_attempt": sum(
            row["state_release_count"] for row in gated_rows
        )
        == gate_attempt_count,
        "paired_initial_choice_reproduced": all(
            pair["initial_choice_reproduced"] for pair in pairs
        ),
    }
    easy_retry = aggregate["easy_control"]["retry_once"]
    ambiguity_off = aggregate["ambiguity_challenge"]["off"]
    ambiguity_retry = aggregate["ambiguity_challenge"]["retry_once"]
    negative_retry = aggregate["unresolved_negative"]["retry_once"]
    behavior_gates = {
        "easy_control_no_false_retry": easy_retry["retry_trigger_count"] == 0,
        "ambiguity_triggers_retry": ambiguity_retry["retry_trigger_count"] > 0,
        "ambiguity_quality_improves": (
            ambiguity_retry["validator_pass_count"]
            > ambiguity_off["validator_pass_count"]
        ),
        "unresolved_cases_fail_closed": negative_retry["fail_closed_count"] == 2,
        "unresolved_cases_pass_safety_validator": (
            negative_retry["validator_pass_count"] == 2
        ),
    }
    summary = {
        "schema_version": "statebus.logit_retry_challenge_summary.v1",
        "suite_id": "logit_retry_challenge_v1",
        "experiment_scope": "bounded_diagnostic_not_formal_baseline",
        "formal_evidence_updated": False,
        "output_root": str(output_root),
        "manifest_sha256": sha256_digest(_MANIFEST_PATH.read_bytes()),
        "gold_sha256": sha256_digest(_GOLD_PATH.read_bytes()),
        "serial_execution": True,
        "schedule": schedule,
        "case_count": len(cases),
        "paired_run_count": len(rows),
        "aggregate": aggregate,
        "pairs": pairs,
        "infrastructure_gates": infrastructure_gates,
        "behavior_gates": behavior_gates,
        "infrastructure_ok": all(infrastructure_gates.values()),
        "effect_demonstrated": all(behavior_gates.values()),
        "rows": rows,
    }
    (output_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_summary_markdown(summary, output_root / "summary.md")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    summary = run_logit_retry_challenge_suite(output_root=args.output_root)
    print(json.dumps({
        "output_root": summary["output_root"],
        "infrastructure_ok": summary["infrastructure_ok"],
        "effect_demonstrated": summary["effect_demonstrated"],
        "aggregate": summary["aggregate"],
    }, ensure_ascii=True, sort_keys=True))
    if not summary["infrastructure_ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
