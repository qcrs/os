from __future__ import annotations

import json
import math

import pytest

from runtime.llm import LLMResult, LLMUsage
from v2.contracts import LogitProducerStatus
from v2.runtime.role_path import RolePathRunner, RoleToolCandidate


def _choice_logprobs(selected: str) -> list[dict[str, object]]:
    prefix = '{"choice_code":"'
    suffix = '"}'
    selected_probability = 0.7 if selected == "A" else 0.2
    return [
        {"token": prefix, "bytes": list(prefix.encode("utf-8")), "logprob": 0.0},
        {
            "token": selected,
            "bytes": list(selected.encode("ascii")),
            "logprob": math.log(selected_probability),
            "top_logprobs": [
                {"token": "A", "bytes": [65], "logprob": math.log(0.7)},
                {"token": "B", "bytes": [66], "logprob": math.log(0.2)},
                {"token": "X", "bytes": [88], "logprob": math.log(0.05)},
            ],
        },
        {"token": suffix, "bytes": list(suffix.encode("utf-8")), "logprob": 0.0},
    ]


def _candidates() -> tuple[RoleToolCandidate, ...]:
    return (
        RoleToolCandidate(route="compare_metric", tool_name="table_retriever", helper_rank=1),
        RoleToolCandidate(route="summarize_risk", tool_name="semantic_retriever", helper_rank=2),
    )


class _ExactChoiceClient:
    def __init__(self, results: list[LLMResult]) -> None:
        self.results = list(results)
        self.schemas: list[dict[str, object] | None] = []

    async def complete(self, messages, *, purpose, response_schema=None, **kwargs):
        del messages, kwargs
        assert purpose == "executor"
        self.schemas.append(response_schema)
        return self.results.pop(0)

    def describe(self):
        return {"backend": "stub", "mode": "local_vllm"}


def test_role_path_uses_dedicated_alias_surface_for_logit_policy() -> None:
    client = _ExactChoiceClient(
        [
            LLMResult(
                text='{"choice_code":"A"}',
                model="stub-model",
                usage=LLMUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
                top_logprobs=_choice_logprobs("A"),
            )
        ]
    )
    runner = RolePathRunner(llm_client=client, logit_policy="telemetry_only")

    decision = runner.validate_execution_choice(
        route="compare_metric",
        tool_name="table_retriever",
        visible_candidates=_candidates(),
        action_contract="execute_validated_tool",
        allow_assisted_correction=False,
    )

    assert client.schemas == [
        {
            "type": "object",
            "properties": {"choice_code": {"type": "string", "enum": ["A", "B"]}},
            "required": ["choice_code"],
            "additionalProperties": False,
        }
    ]
    assert decision.route == "compare_metric"
    assert decision.tool_name == "table_retriever"
    assert decision.raw_text == ""
    assert decision.logit_state_bytes == 12
    assert decision.logit_state_payload
    assert decision.logit_candidate_surface is not None
    assert decision.logit_producer_receipt is not None
    assert decision.logit_producer_receipt.status is LogitProducerStatus.AVAILABLE
    assert decision.logit_unavailable_reason == ""


def test_role_path_preserves_only_final_accepted_attempt_logprobs() -> None:
    client = _ExactChoiceClient(
        [
            LLMResult(
                text="not-json",
                model="stub-model",
                top_logprobs=_choice_logprobs("A"),
            ),
            LLMResult(
                text='{"choice_code":"B"}',
                model="stub-model",
                top_logprobs=_choice_logprobs("B"),
            ),
        ]
    )
    runner = RolePathRunner(
        llm_client=client,
        logit_policy="telemetry_only",
        json_response_max_attempts=2,
    )

    decision = runner.validate_execution_choice(
        route="compare_metric",
        tool_name="table_retriever",
        visible_candidates=_candidates(),
        action_contract="execute_validated_tool",
        allow_assisted_correction=False,
    )

    assert decision.route == "summarize_risk"
    assert decision.logit_producer_receipt is not None
    assert decision.logit_producer_receipt.selected_alias == "B"
    assert decision.logit_confidence_proxy == pytest.approx(0.2)


def test_role_path_records_structured_unavailable_without_changing_selection() -> None:
    client = _ExactChoiceClient(
        [LLMResult(text='{"choice_code":"A"}', model="stub-model", top_logprobs=None)]
    )
    runner = RolePathRunner(llm_client=client, logit_policy="telemetry_only")

    decision = runner.validate_execution_choice(
        route="compare_metric",
        tool_name="table_retriever",
        visible_candidates=_candidates(),
        action_contract="execute_validated_tool",
        allow_assisted_correction=False,
    )

    assert decision.route == "compare_metric"
    assert decision.logit_state_bytes == 0
    assert decision.logit_producer_receipt is not None
    assert decision.logit_producer_receipt.status is LogitProducerStatus.UNAVAILABLE
    assert decision.logit_unavailable_reason == "top_logprobs_missing"


def test_logit_policy_off_keeps_legacy_choice_and_ignores_unsolicited_logprobs() -> None:
    client = _ExactChoiceClient(
        [
            LLMResult(
                text=json.dumps(
                    {
                        "candidate_key": "compare_metric::table_retriever",
                        "route": "compare_metric",
                        "tool_name": "table_retriever",
                    }
                ),
                model="stub-model",
                top_logprobs=_choice_logprobs("A"),
            )
        ]
    )
    runner = RolePathRunner(llm_client=client, logit_policy="off")

    decision = runner.validate_execution_choice(
        route="compare_metric",
        tool_name="table_retriever",
        visible_candidates=_candidates(),
        action_contract="execute_validated_tool",
        allow_assisted_correction=False,
    )

    assert set(client.schemas[0]["properties"]) == {"candidate_key", "route", "tool_name"}
    assert decision.logit_policy == "off"
    assert decision.logit_state_bytes == 0
    assert decision.logit_state_payload == b""
    assert decision.logit_producer_receipt is None
    assert decision.logit_unavailable_reason == "policy_off"
