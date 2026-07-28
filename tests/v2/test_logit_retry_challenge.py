from __future__ import annotations

from collections import Counter
import math
from pathlib import Path
import struct

import pytest

from runtime.llm import LLMResult, LLMUsage
from v2.benchmark.logit_retry_challenge import (
    ChoiceObservation,
    load_logit_challenge_cases,
    make_llm_choice_generator,
    render_logit_challenge_prompt,
    run_logit_challenge_case,
)
from v2.contracts import LogitProducerReceipt, LogitProducerStatus
from v2.runtime.logit_state import ExactChoiceLogitResult


def _exact_observation(
    case,
    *,
    stage: str,
    probabilities: tuple[float, ...],
    other_mass: float,
    selected_alias: str,
) -> ChoiceObservation:
    surface = case.candidate_surface
    selected_ordinal = surface.aliases.index(selected_alias)
    selected_candidate_id = surface.candidate_id_for_alias(selected_alias)
    extraction = ExactChoiceLogitResult(
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
            request_id=f"request-{case.task_id}-{stage}",
            attempt_id=f"attempt-{case.task_id}-{stage}",
            status=LogitProducerStatus.AVAILABLE,
            candidate_surface_digest=surface.candidate_surface_digest,
            alias_mapping_digest=surface.alias_mapping_digest,
            selected_alias=selected_alias,
            selected_candidate_id=selected_candidate_id,
            decision_token_position=1,
            sequence_length=3,
            top_k=len(probabilities) + 1,
        ),
    )
    prompt = render_logit_challenge_prompt(case, stage=stage)
    return ChoiceObservation(
        stage=stage,
        selected_alias=selected_alias,
        selected_candidate_id=selected_candidate_id,
        extraction=extraction,
        prompt=prompt,
        raw_text=f'{{"choice_code":"{selected_alias}"}}',
        model="stub-model",
        prompt_tokens=10,
        completion_tokens=2,
        total_tokens=12,
        prompt_bytes=len(prompt.encode("utf-8")),
        latency_ms=1.0,
    )


class _SequenceChooser:
    def __init__(self, observations: list[ChoiceObservation]) -> None:
        self.observations = observations

    def __call__(self, case, *, stage: str) -> ChoiceObservation:
        del case
        observation = self.observations.pop(0)
        assert observation.stage == stage
        return observation


def _choice_result(
    *,
    selected_alias: str,
    probabilities: dict[str, float],
) -> LLMResult:
    prefix = '{"choice_code":"'
    suffix = '"}'
    return LLMResult(
        text=f'{prefix}{selected_alias}{suffix}',
        model="stub-model",
        usage=LLMUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13),
        top_logprobs=[
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
        ],
    )


class _SequenceClient:
    def __init__(self, results: list[LLMResult]) -> None:
        self.results = results

    async def complete(self, *args, **kwargs) -> LLMResult:
        del args, kwargs
        return self.results.pop(0)

    def describe(self) -> dict[str, object]:
        return {"mode": "stub"}


def test_logit_challenge_manifest_has_three_bounded_groups_and_external_gold() -> None:
    cases = load_logit_challenge_cases()

    assert len(cases) == 12
    assert Counter(case.group for case in cases) == {
        "easy_control": 5,
        "ambiguity_challenge": 5,
        "unresolved_negative": 2,
    }
    assert all(len(case.candidates) == 2 for case in cases)
    assert sum(case.expected_outcome == "select" for case in cases) == 10
    assert sum(case.expected_outcome == "fail_closed" for case in cases) == 2


def test_ambiguity_prompt_expands_contract_only_after_numeric_retry() -> None:
    case = next(
        item
        for item in load_logit_challenge_cases()
        if item.task_id == "logit-ambiguous-01-anomaly"
    )

    initial = render_logit_challenge_prompt(case, stage="initial")
    initial_ba = render_logit_challenge_prompt(
        case,
        stage="initial",
        projection="BA",
    )
    recheck = render_logit_challenge_prompt(case, stage="recheck")
    recheck_ba = render_logit_challenge_prompt(
        case,
        stage="recheck",
        projection="BA",
    )

    assert "IQR 异常标记" not in initial
    assert "两个候选在可见合同下同等适用" in initial
    assert initial == initial_ba
    assert "IQR 异常标记" in recheck
    assert "numeric gate rejected" in recheck
    assert recheck != recheck_ba
    assert all(candidate.candidate_id not in initial for candidate in case.candidates)
    assert all(candidate.candidate_id not in recheck for candidate in case.candidates)


def test_counterfactual_alias_calibration_cancels_first_alias_bias() -> None:
    case = next(
        item
        for item in load_logit_challenge_cases()
        if item.task_id == "logit-ambiguous-01-anomaly"
    )
    choose = make_llm_choice_generator(_SequenceClient([
        _choice_result(
            selected_alias="A",
            probabilities={"A": 0.999, "B": 0.0009, "X": 0.0001},
        ),
        _choice_result(
            selected_alias="A",
            probabilities={"A": 0.999, "B": 0.0009, "X": 0.0001},
        ),
    ]))

    observation = choose(case, stage="initial")

    assert observation.calibration_method == "counterfactual_alias_ab_ba_mean_v1"
    assert observation.probe_count == 2
    assert observation.extraction.candidate_probabilities == pytest.approx(
        (0.49995, 0.49995)
    )
    assert observation.extraction.other_mass == pytest.approx(0.0001)
    assert observation.extraction.top_margin == pytest.approx(0.0)


def test_counterfactual_alias_calibration_preserves_semantic_choice() -> None:
    case = next(
        item
        for item in load_logit_challenge_cases()
        if item.task_id == "logit-ambiguous-01-anomaly"
    )
    choose = make_llm_choice_generator(_SequenceClient([
        _choice_result(
            selected_alias="B",
            probabilities={"A": 0.009, "B": 0.99, "X": 0.001},
        ),
        _choice_result(
            selected_alias="A",
            probabilities={"A": 0.99, "B": 0.009, "X": 0.001},
        ),
    ]))

    observation = choose(case, stage="recheck")

    assert observation.selected_candidate_id == "detect_outliers"
    assert observation.extraction.candidate_probabilities == pytest.approx((0.009, 0.99))
    assert observation.extraction.other_mass == pytest.approx(0.001)
    assert observation.extraction.top_margin == pytest.approx(0.981)


def test_challenge_retry_expands_context_and_corrects_route(tmp_path: Path) -> None:
    case = next(
        item
        for item in load_logit_challenge_cases()
        if item.task_id == "logit-ambiguous-01-anomaly"
    )
    off = run_logit_challenge_case(
        case,
        mode="off",
        run_dir=tmp_path / "off-run",
        choose=_SequenceChooser([
            _exact_observation(
                case,
                stage="initial",
                probabilities=(0.45, 0.40),
                other_mass=0.15,
                selected_alias="A",
            )
        ]),
    )
    retry = run_logit_challenge_case(
        case,
        mode="retry_once",
        run_dir=tmp_path / "retry-run",
        choose=_SequenceChooser([
            _exact_observation(
                case,
                stage="initial",
                probabilities=(0.45, 0.40),
                other_mass=0.15,
                selected_alias="A",
            ),
            _exact_observation(
                case,
                stage="recheck",
                probabilities=(0.10, 0.80),
                other_mass=0.10,
                selected_alias="B",
            ),
        ]),
    )

    assert off["validator"]["passed"] is False
    assert off["worker_dispatch_count"] == 1
    assert retry["final_status"] == "accepted_after_retry"
    assert retry["final_candidate_id"] == "detect_outliers"
    assert retry["validator"]["passed"] is True
    assert retry["retry_triggered"] is True
    assert retry["choice_changed"] is True
    assert retry["state_transfer_count"] == 2
    assert retry["cross_pid_transfer_count"] == 2
    assert retry["state_release_count"] == 2


def test_unresolved_challenge_fails_closed_after_second_low_margin(
    tmp_path: Path,
) -> None:
    case = next(
        item
        for item in load_logit_challenge_cases()
        if item.task_id == "logit-unresolved-01-replica"
    )
    result = run_logit_challenge_case(
        case,
        mode="retry_once",
        run_dir=tmp_path / "negative-run",
        choose=_SequenceChooser([
            _exact_observation(
                case,
                stage="initial",
                probabilities=(0.45, 0.40),
                other_mass=0.15,
                selected_alias="A",
            ),
            _exact_observation(
                case,
                stage="recheck",
                probabilities=(0.44, 0.41),
                other_mass=0.15,
                selected_alias="A",
            ),
        ]),
    )

    assert result["final_status"] == "fail_closed"
    assert result["failure_reason"] == "low_confidence_after_retry"
    assert result["worker_dispatch_count"] == 0
    assert result["validator"]["passed"] is True
    assert result["state_transfer_count"] == 2
    assert result["state_release_count"] == 2
