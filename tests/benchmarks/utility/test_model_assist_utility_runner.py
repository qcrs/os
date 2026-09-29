from __future__ import annotations

import json
import math
import os
from types import SimpleNamespace

import pytest

from statebus.benchmark.model_assist_utility import runner
from statebus.benchmark.model_assist_utility.taskpack import CASE_IDS, LOGIT_CASE_IDS


def test_dry_run_is_read_only_and_reports_contract_counts(tmp_path, monkeypatch) -> None:
    def fail_capture(*args, **kwargs):
        raise AssertionError("dry-run must not contact a service")

    monkeypatch.setattr(runner, "_run_capture", fail_capture)
    payload = runner.run_dry_run(phase="all")
    assert payload["positions"] == 28
    assert payload["standard_positions"] == 20
    assert payload["kv_positions"] == 8
    assert payload["warmups"] == {"business": 4, "choice": 2}
    assert not list(tmp_path.iterdir())


def test_smoke_dry_run_is_the_seven_position_gate() -> None:
    payload = runner.run_dry_run(phase="all", mode="smoke")
    assert payload["positions"] == 7
    assert payload["standard_positions"] == 5
    assert payload["kv_positions"] == 2
    assert payload["warmups"] == {"business": 0, "choice": 0}


def test_targeted_apc_dry_run_selects_one_position_and_expanded_budget(monkeypatch) -> None:
    taskpack = SimpleNamespace(
        manifest={"suite_revision": "longtext-demo-v3"},
        plan=runner.PLAN_POSITIONS,
    )
    monkeypatch.setattr(runner, "load_local_codec", lambda _path: object())
    monkeypatch.setattr(runner, "compile_taskpack", lambda *_args, **_kwargs: taskpack)

    payload = runner.run_dry_run(
        phase="apc",
        target_slot_id=f"{CASE_IDS[1]}:apc_on_independent",
        wall_budget_s=14400,
    )

    assert payload["positions"] == 1
    assert payload["standard_positions"] == 1
    assert payload["kv_positions"] == 0
    assert payload["wall_budget_s"] == 14400
    assert payload["target_slot_id"] == f"{CASE_IDS[1]}:apc_on_independent"
    assert payload["plan"][0]["condition"] == "apc_on_independent"
    assert payload["warmups"] == {"business": 0, "choice": 0}


def test_logit_dry_run_reports_only_choice_warmups() -> None:
    payload = runner.run_dry_run(phase="logit")

    assert payload["positions"] == 12
    assert payload["standard_positions"] == 12
    assert payload["kv_positions"] == 0
    assert payload["warmups"] == {"business": 0, "choice": 2}


def test_resume_phase_must_be_a_subset_of_frozen_phase() -> None:
    assert runner._resume_phase_is_subset("all", "logit")
    assert runner._resume_phase_is_subset("standard", "logit")
    assert runner._resume_phase_is_subset("all", "all")
    assert not runner._resume_phase_is_subset("logit", "all")
    assert not runner._resume_phase_is_subset("kv", "standard")


def test_tokenizer_codec_uses_unversioned_vllm_endpoint() -> None:
    class Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"tokens": [11, 12], "count": 2}

    class HttpClient:
        urls: list[str] = []

        def post(self, url: str, **_kwargs: object) -> Response:
            self.urls.append(url)
            return Response()

    client = HttpClient()
    codec = runner._tokenizer_codec(timeout_s=1.0, http_client=client)
    try:
        assert codec.encode_messages([{"role": "user", "content": "probe"}]) == (11, 12)
    finally:
        codec.close()
    assert client.urls == ["http://127.0.0.1:53334/tokenize"]


def test_executor_source_locators_are_bounded_for_the_512_token_contract() -> None:
    assert runner._executor_schema()["properties"]["source_locators"]["maxItems"] == 4
    request = SimpleNamespace(
        role_context=SimpleNamespace(verified_input_payloads=(
            {"kind": "canonical_evidence_pack", "ref_id": "evidence", "payload": {}},
        )),
        bound_grant=SimpleNamespace(grant=SimpleNamespace(attempt_id="attempt-1")),
        step=SimpleNamespace(output_contract_version="artifact.v1"),
    )
    candidate = runner._parse_transform_program(
        request=request,
        raw_text=json.dumps({"operations": [{"op": "select"}], "source_locators": ["row"] * 5}),
    )
    assert not candidate.success
    assert candidate.error_code == "executor_candidate_invalid:ValueError"


def test_executor_transform_program_requires_nested_dsl_arguments() -> None:
    operation_schema = runner._executor_schema()["properties"]["operations"]["items"]
    assert operation_schema["required"] == ["op", "arguments"]
    assert operation_schema["additionalProperties"] is False

    request = SimpleNamespace(
        role_context=SimpleNamespace(verified_input_payloads=(
            {
                "kind": "canonical_evidence_pack",
                "ref_id": "retrieve-output",
                "payload": {
                    "structured_evidence": [{
                        "item_id": "row-1",
                        "metadata": {"structured_row": {"source_locator": "ledger/sample.json#row-1"}},
                    }],
                },
            },
        )),
        bound_grant=SimpleNamespace(grant=SimpleNamespace(attempt_id="attempt-1")),
        step=SimpleNamespace(output_contract_version="statebus.model_assist_utility.artifact.v1"),
    )
    nested = runner._parse_transform_program(
        request=request,
        raw_text=json.dumps({
            "operations": [{"op": "filter_eq", "arguments": {"column": "status", "value": "APPROVED"}}],
            "source_locators": ["ledger/sample.json#row-1"],
        }),
    )
    flat = runner._parse_transform_program(
        request=request,
        raw_text=json.dumps({
            "operations": [{"op": "filter_eq", "field": "status", "value": "APPROVED"}],
            "source_locators": ["ledger/sample.json#row-1"],
        }),
    )

    assert nested.success is True
    assert nested.payload.operations[0].arguments == {"column": "status", "value": "APPROVED"}
    assert flat.success is False
    assert flat.error_code == "executor_candidate_invalid:ValueError"


def test_executor_contract_uses_plural_values_for_filter_in() -> None:
    active_rule = {
        "rule_id": "R-NOV-SAMPLE-2026",
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
        "eligible_scope": "approved_sample_cohort",
    }
    contract = runner._transform_contract(SimpleNamespace(case_id="MU-NOVA-TEST", rules=(active_rule,)))
    assert '"group_fields":["quarter"]' in contract
    assert '"column":"effective_rule_id","value":"R-NOV-SAMPLE-2026"' in contract
    assert '"rate_pct","ratio","on_time","committed",100,4' in contract
    assert '["quarter","on_time","committed","record_count","rate_pct"]' in contract

    orion_contract = runner._transform_contract(SimpleNamespace(
        case_id="MU-ORION-TEST",
        rules=({**active_rule, "rule_id": "R-ORI-SAMPLE-2026"},),
    ))
    assert '"fee_per_record","ratio","fee_usd","record_count",1,2' in orion_contract
    assert '["quarter","fee_usd","exception_count","record_count","fee_per_record"]' in orion_contract
    assert tuple(runner._runtime_output_schema(SimpleNamespace(case_id="MU-ORION-TEST"))) == (
        "quarter", "fee_usd", "exception_count", "record_count", "fee_per_record",
    )

    messages = runner._executor_messages(
        SimpleNamespace(
            case_id="MU-NOVA-TEST",
            rules=(active_rule,),
            layout_text=lambda *_args, **_kwargs: "authorized dossier",
            definition=SimpleNamespace(question="Calculate the weighted rate.", executor_contract="Filter and aggregate."),
        ),
        "independent",
        "attempt-1",
        namespace="test",
    )

    assert '"column":"quarter","values":["2026Q1","2026Q3"]' in messages[1].content
    assert "filter_in arguments column/values (plural array)" in messages[1].content
    assert "derive_safe" in messages[1].content
    assert "nested arguments key `calculations`" in messages[1].content
    assert "never use `expressions`" in messages[1].content


def test_executor_prompt_lists_exact_active_rule_and_ledger_locators() -> None:
    active_rule = {
        "rule_id": "R-NOV-SAMPLE-2026",
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
        "eligible_scope": "approved_sample_cohort",
        "source_locator": "rules/mu-nova-4k-delivery_active_scope_rules.json#R-2026-sample",
    }
    rows = tuple(
        {"source_locator": locator}
        for locator in (
            "ledger/mu-nova-4k-delivery_controlled_sample_ledger.json#row-0001",
            "ledger/mu-nova-4k-delivery_controlled_sample_ledger.json#row-0016",
            "ledger/mu-nova-4k-delivery_controlled_sample_ledger.json#row-0031",
        )
    )
    case = SimpleNamespace(
        case_id="MU-NOVA-4K-DELIVERY",
        rules=(active_rule,),
        source_rows=rows,
        layout_text=lambda *_args, **_kwargs: "authorized dossier",
        definition=SimpleNamespace(question="Calculate the weighted rate.", executor_contract="Use the authorized dossier."),
    )

    content = runner._executor_messages(case, "independent", "attempt-1", namespace="test")[1].content

    for row in (active_rule, *rows):
        assert row["source_locator"] in content
    assert "rules/active_scope_rules.json" in content
    assert "copy character-for-character" in content


def test_summarizer_prompt_names_required_rule_and_citation_fields() -> None:
    active_rule = {
        "rule_id": "R-NOV-SAMPLE-2026",
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
        "eligible_scope": "approved_sample_cohort",
        "source_locator": "rules/active.json#R-2026-sample",
    }
    case = SimpleNamespace(
        case_id="MU-NOVA-TEST",
        rules=(active_rule,),
        definition=SimpleNamespace(question="Calculate the approved cohort."),
        layout_text=lambda *_args, **_kwargs: "authorized dossier",
    )
    request = SimpleNamespace(
        role_context=SimpleNamespace(verified_input_payloads=(
            {
                "kind": "execution_artifact",
                "ref_id": "execute-artifact",
                "payload": {"rows": [{"quarter": "2026Q1"}]},
            },
        )),
        bound_grant=SimpleNamespace(grant=SimpleNamespace(attempt_id="attempt-1")),
    )

    messages = runner._summarizer_messages(case, "shared", request, namespace="test")
    content = messages[1].content

    assert "required field names" in content
    assert "rule_id" in content
    assert "citations" in content
    assert "source_citations" in content
    assert "active_scope_rule" in content
    assert "R-NOV-SAMPLE-2026" in content
    assert "rules/active.json#R-2026-sample" in content
    assert "at least one exact `ledger/` locator" in content


def test_executor_repair_uses_delegate_and_records_request_cost(monkeypatch) -> None:
    active_rule = {
        "rule_id": "R-ORI-SAMPLE-2026",
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
        "eligible_scope": "approved_sample_cohort",
        "source_locator": "rules/active.json#R-2026-sample",
    }
    case = SimpleNamespace(
        case_id="MU-ORION-TEST",
        rules=(active_rule,),
        source_rows=({"source_locator": "ledger/sample.json#row-1"},),
        definition=SimpleNamespace(question="Calculate the approved cohort.", executor_contract="Use the authorized dossier."),
        layout_text=lambda *_args, **_kwargs: "authorized dossier",
    )
    delegate = object()
    codec = SimpleNamespace(encode_messages=lambda *_args, **_kwargs: (11, 12, 13))
    observations: list[dict[str, object]] = []
    program_text = json.dumps({
        "operations": [{"op": "select", "arguments": {"columns": ["quarter", "fee_usd"]}}],
        "source_locators": ["rules/active.json#R-2026-sample", "ledger/sample.json#row-1"],
    })
    received_clients: list[object] = []

    def complete_streaming(client, _messages, **_kwargs):
        received_clients.append(client)
        return SimpleNamespace(text=program_text), {
            "status": "response",
            "request_wall_ms": 3.5,
            "ttft_ms": 1.25,
            "usage": {"prompt_tokens": 3, "completion_tokens": 12, "total_tokens": 15},
        }

    monkeypatch.setattr(runner, "_complete_streaming", complete_streaming)
    factory = runner._executor_repair_factory(
        case=case,
        layout="shared",
        namespace="mu-0123456789abcdef0123456789abcdef",
        client=delegate,
        codec=codec,
        observations=observations,
    )
    previous = runner.TransformProgram(
        program_id="rejected",
        input_artifact_refs=("evidence-ref",),
        operations=(runner.TransformStep("select", {"columns": ["missing"]}),),
        output_contract_version="artifact.v1",
    )
    repaired = factory(
        SimpleNamespace(output_contract_version="artifact.v1"),
        SimpleNamespace(attempt_id="attempt-1"),
        "evidence-ref",
        case.source_rows,
        ("missing_column:0",),
        previous_program=previous,
        repair_stage="execution_validation",
        input_tables={"evidence-ref": case.source_rows},
    )

    assert repaired.program_id == "utility-program-attempt-1-repair"
    assert received_clients == [delegate]
    assert observations[0]["role"] == "executor_repair"
    assert observations[0]["prompt_tokens_exact"] == 3
    assert observations[0]["usage"] == {"prompt_tokens": 3, "completion_tokens": 12, "total_tokens": 15}
    assert observations[0]["request_wall_ms"] == 3.5
    assert observations[0]["ttft_ms"] == 1.25


def test_apc_namespace_search_is_local_and_server_verified_once_per_condition(tmp_path) -> None:
    class CountingCodec:
        def __init__(self) -> None:
            self.calls: list[object] = []

        def encode_messages(self, messages, *, add_generation_prompt, chat_template_kwargs):
            self.calls.append((messages, add_generation_prompt, chat_template_kwargs))
            return (1, 2, 3)

    local_codec = CountingCodec()
    server_codec = CountingCodec()
    case = SimpleNamespace(
        case_id="MU-TEST-4K",
        target_prefix_tokens=3,
        shared_prefix_text=lambda namespace: f"authorized dossier namespace {namespace}",
    )
    utility_runner = runner.UtilitySuiteRunner(
        SimpleNamespace(manifest={}),
        tmp_path / "namespace-run",
        quiet=True,
        namespace_codec=local_codec,
    )

    assignments = utility_runner._apc_namespace_pair(case, ("independent", "shared"), server_codec)

    assert assignments["independent"]["namespace"] != assignments["shared"]["namespace"]
    assert len(local_codec.calls) == 2
    assert len(server_codec.calls) == 2


def test_apc_calibration_gate_requires_both_positions() -> None:
    assert runner._apc_calibration_gate_ready([{"gate_ready": True}, {"gate_ready": True}])
    assert not runner._apc_calibration_gate_ready([{"gate_ready": True}])
    assert not runner._apc_calibration_gate_ready([{"gate_ready": True}, {"gate_ready": False}])


def test_logit_extraction_payload_marks_probability_width_mismatch_unavailable() -> None:
    surface = runner.CandidateSurfaceV2.from_candidate_ids(("one", "two", "three"))
    extraction = SimpleNamespace(
        available=True,
        selected_alias=surface.aliases[-1],
        selected_candidate_id="three",
        candidate_probabilities=(0.8,),
        other_mass=0.2,
        top_margin=0.8,
        receipt=SimpleNamespace(
            unavailable_reason="",
            decision_token_position=0,
            sequence_length=1,
            top_k=3,
        ),
    )

    payload = runner._logit_extraction_payload(extraction, surface)

    assert payload["available"] is False
    assert payload["unavailable_reason"] == "candidate_probability_width_mismatch"


class _ByteLevelChoiceTokenizer:
    def __init__(self) -> None:
        visible = {
            "{": "{",
            "Ġ\"": " \"",
            "choice": "choice",
            "_c": "_c",
            "od": "od",
            "e": "e",
            "\":": "\":",
            "A": "A",
            "B": "B",
            "C": "C",
            "\"": "\"",
            "Ġ}": " }",
            "<|im_end|>": "<|im_end|>",
        }
        self.name_or_path = "qwen3-32b-test-tokenizer"
        self.eos_token_id = len(visible) - 1
        self._vocab = {token: index for index, token in enumerate(visible)}
        self._tokens = list(visible)
        self._visible = list(visible.values())

    def get_vocab(self) -> dict[str, int]:
        return self._vocab

    def convert_ids_to_tokens(self, token_id: int) -> str:
        return self._tokens[token_id]

    def decode(
        self,
        token_ids: list[int],
        *,
        clean_up_tokenization_spaces: bool,
        skip_special_tokens: bool,
    ) -> str:
        del clean_up_tokenization_spaces
        return "".join(
            "" if skip_special_tokens and token_id == self.eos_token_id else self._visible[token_id]
            for token_id in token_ids
        )


def _byte_level_choice_logprobs() -> list[dict[str, object]]:
    tokens = ["{", "Ġ\"", "choice", "_c", "od", "e", "\":", "Ġ\"", "A", "\"", "Ġ}", "<|im_end|>"]
    items = [
        {"token": token, "bytes": list(token.encode("utf-8")), "logprob": -0.1, "top_logprobs": []}
        for token in tokens
    ]
    items[8]["top_logprobs"] = [
        {"token": "A", "bytes": [65], "logprob": -0.1},
        {"token": "B", "bytes": [66], "logprob": -3.0},
        {"token": "C", "bytes": [67], "logprob": -4.0},
    ]
    return items


def test_utility_logit_extraction_reconstructs_vllm_bytelevel_tokens_exactly() -> None:
    surface = runner.CandidateSurfaceV2.from_candidate_ids(("candidate-a", "candidate-b", "candidate-c"))
    raw = _byte_level_choice_logprobs()

    extraction, alignment = runner._extract_utility_choice_logit_state(
        completion_text='{ "choice_code": "A" }',
        top_logprobs=raw,
        candidate_surface=surface,
        request_id="request-1",
        attempt_id="attempt-1",
        tokenizer=_ByteLevelChoiceTokenizer(),
    )

    assert extraction.available is True
    assert extraction.selected_candidate_id == "candidate-a"
    assert extraction.receipt.decision_token_position == 8
    assert extraction.candidate_probabilities == pytest.approx((math.exp(-0.1), math.exp(-3.0), math.exp(-4.0)))
    assert alignment["status"] == "reconstructed_exactly"
    assert alignment["text_match"] is True
    assert raw[1]["bytes"] == [196, 160, 34]


def test_utility_logit_extraction_keeps_tokenizer_mismatch_unavailable() -> None:
    surface = runner.CandidateSurfaceV2.from_candidate_ids(("candidate-a", "candidate-b", "candidate-c"))

    extraction, alignment = runner._extract_utility_choice_logit_state(
        completion_text='{ "choice_code": "B" }',
        top_logprobs=_byte_level_choice_logprobs(),
        candidate_surface=surface,
        request_id="request-2",
        attempt_id="attempt-2",
        tokenizer=_ByteLevelChoiceTokenizer(),
    )

    assert extraction.available is False
    assert extraction.receipt.unavailable_reason == "completion_token_bytes_mismatch"
    assert alignment["status"] == "unavailable"
    assert alignment["reason"] == "local_tokenizer_completion_mismatch"


def test_logit_extraction_payload_handles_unavailable_exact_probabilities() -> None:
    surface = runner.CandidateSurfaceV2.from_candidate_ids(("one", "two"))
    extraction = runner.extract_exact_choice_logit_state(
        completion_text='{"choice_code":"A"}',
        top_logprobs=(),
        candidate_surface=surface,
        request_id="test-request",
        attempt_id="test-attempt",
    )

    payload = runner._logit_extraction_payload(extraction, surface)

    assert payload["available"] is False
    assert payload["unavailable_reason"] == "top_logprobs_missing"
    assert payload["top_margin"] is None


def test_runtime_abstention_uses_final_dispatch_error_after_evidence_recheck() -> None:
    runtime_payload = {
        "dispatches": [
            {"error_code": "model_assist_review_required"},
            {"error_code": "need_more_evidence"},
        ],
        "artifacts": [],
    }

    assert runner._runtime_abstained("abstain", runtime_payload) is True
    assert runner._runtime_abstained("abstain", runtime_payload | {"artifacts": [{"artifact_id": "claim"}]}) is False


def test_standard_endpoint_restore_accepts_returned_raw_logprobs_without_exact_choice(monkeypatch) -> None:
    class Codec:
        def encode_messages(self, *_args, **_kwargs):
            return (1, 2)

        def close(self):
            return None

    class Client:
        async def complete(self, *_args, **_kwargs):
            return SimpleNamespace(
                text='{"choice_code":"A"}',
                finish_reason="stop",
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=4, total_tokens=9),
                top_logprobs=(SimpleNamespace(
                    token="A",
                    bytes=b"A",
                    logprob=-0.1,
                    top_logprobs=(SimpleNamespace(token="A", bytes=b"A", logprob=-0.1),),
                ),),
            )

    monkeypatch.setattr(runner, "_manager_identity", lambda _path: {"mode": "standard", "pid": 123, "healthy": True})
    monkeypatch.setattr(
        runner,
        "_run_capture",
        lambda command, **_kwargs: {"returncode": 0, "stdout": '{"data":[{"id":"qwen3-32b"}]}' if command[-1].endswith("/v1/models") else ""},
    )
    monkeypatch.setattr(runner, "_tokenizer_codec", lambda **_kwargs: Codec())
    monkeypatch.setattr(runner, "_llm_client", lambda **_kwargs: Client())

    evidence = runner._verify_standard_endpoints()

    assert evidence["passed"] is True
    assert evidence["logprobs"]["status"] == "passed"
    assert evidence["logprobs"]["token_count"] == 1


def test_logit_warmup_preserves_raw_observation_before_index_failure(tmp_path, monkeypatch) -> None:
    def fail_extraction(**_kwargs):
        raise IndexError("captured extraction failure")

    class Codec:
        def encode_messages(self, *_args, **_kwargs):
            return (1, 2)

    result = SimpleNamespace(text='{"choice_code":"A"}', top_logprobs=())
    monkeypatch.setattr(runner, "_complete", lambda *_args, **_kwargs: (result, {"status": "response", "text": result.text}))
    monkeypatch.setattr(runner, "extract_exact_choice_logit_state", fail_extraction)
    utility_runner = runner.UtilitySuiteRunner(None, tmp_path / "logit-run", quiet=True)
    case = SimpleNamespace(
        case_id="MU-LOGIT-CALIBRATION",
        candidates=({"candidate_id": "one", "label": "One"}, {"candidate_id": "two", "label": "Two"}),
        question="Choose the authorized evidence.",
        compact_view="index",
        full_view="full evidence",
    )

    observations = utility_runner.run_logit_warmup(case, object(), Codec())
    raw_rows = [json.loads(line) for line in (utility_runner.run_root / "warmup-observations.jsonl").read_text().splitlines()]
    final_rows = [json.loads(line) for line in (utility_runner.run_root / "warmup.jsonl").read_text().splitlines()]

    assert len(observations) == len(raw_rows) == len(final_rows) == 2
    assert raw_rows[0]["observation"]["text"] == result.text
    assert final_rows[0]["extraction_error"] == {"type": "IndexError", "message": "captured extraction failure"}
    assert final_rows[0]["exact_available"] is False


def test_resume_reuses_saved_logit_warmup_responses_for_local_reanalysis(tmp_path) -> None:
    utility_runner = runner.UtilitySuiteRunner(None, tmp_path / "resume-run", quiet=True, resume=True)
    utility_runner.execution_id = "resume-run-resume-01"
    case = SimpleNamespace(
        case_id="MU-LOGIT-CALIBRATION",
        candidates=({"candidate_id": "one"}, {"candidate_id": "two"}),
    )
    raw_observation = {
        "status": "response",
        "text": '{"choice_code":"A"}',
        "raw_top_logprobs": [{
            "token": "A",
            "bytes": [65],
            "logprob": -0.1,
            "top_logprobs": [{"token": "A", "bytes": [65], "logprob": -0.1}],
        }],
    }
    source_path = utility_runner.run_root / "warmup-observations.jsonl"
    source_path.write_text(
        "".join(json.dumps({
            "module": "logit",
            "warmup": True,
            "stage": stage,
            "case_id": case.case_id,
            "observation": raw_observation,
        }) + "\n" for stage in ("compact", "full")),
        encoding="utf-8",
    )

    results = utility_runner._reuse_saved_logit_warmup(case)

    assert results is not None and len(results) == 2
    assert all(result["request_reused"] and not result["exact_available"] for result in results)
    assert all(result["source_observation_path"] == str(source_path) for result in results)
    assert source_path.read_text(encoding="utf-8").count('"stage"') == 2
    reanalysis_path = utility_runner.run_root / "warmup-reanalysis-resume-run-resume-01.jsonl"
    assert len(reanalysis_path.read_text(encoding="utf-8").splitlines()) == 2


def test_summary_counts_scored_slots_separately_from_warmups(tmp_path) -> None:
    records = [
        {"module": "apc", "slot_id": "warmup", "scored": False, "status": "completed", "business_quality": "passed"},
        {"module": "apc", "slot_id": f"{CASE_IDS[0]}:apc_on_independent", "scored": True, "status": "completed", "business_quality": "passed"},
        {"module": "kv", "slot_id": f"{CASE_IDS[0]}:full_replay", "scored": True, "status": "failed", "business_quality": "failed"},
    ]
    (tmp_path / "records.jsonl").write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")
    summary = runner.summarize_records(tmp_path)
    assert summary["slot_counts"] == {"apc": 1, "logit": 0, "kv": 1}
    assert summary["by_module"]["apc"]["completed"] == 1
    assert summary["warmup_counts"]["apc"] == 1
    assert summary["by_module"]["kv"]["failed"] == 1
    assert summary["demo_completed"] is False


def test_summary_counts_kv_quality_field_as_business_quality(tmp_path) -> None:
    records = [
        {
            "module": "kv",
            "slot_id": f"{CASE_IDS[0]}:full_replay",
            "scored": True,
            "status": "completed",
            "quality": True,
        }
    ]
    (tmp_path / "records.jsonl").write_text(
        "\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8"
    )

    summary = runner.summarize_records(tmp_path)

    assert summary["by_module"]["kv"]["passed"] == 1
    assert summary["by_module"]["kv"]["failed"] == 0


def test_quiet_log_persists_without_writing_to_stdout(tmp_path, capsys) -> None:
    utility_runner = runner.UtilitySuiteRunner(None, tmp_path / "run", quiet=True)
    utility_runner.log("slot=quiet-check status=completed")
    assert capsys.readouterr().out == ""
    assert utility_runner.run_log.read_text(encoding="utf-8") == "slot=quiet-check status=completed\n"


def test_execute_records_blocked_preflight_without_live_calls(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_preflight(*, phase: str, report_root, **_kwargs):
        return runner.PreflightResult(
            passed=False,
            reasons=("standard_gpu_has_non_workflow_compute_owner",),
            evidence={"owner": "external"},
        )

    def fail_live(self):
        calls.append("live")
        raise AssertionError("blocked preflight must not run live")

    monkeypatch.setattr(runner, "run_preflight", fake_preflight)
    monkeypatch.setattr(runner.UtilitySuiteRunner, "run_live", fail_live)
    code, root, summary = runner.run_execute(
        phase="all",
        report_root=tmp_path,
        run_id="blocked-owner",
        yes=True,
    )
    assert code == 3
    assert calls == []
    assert summary["status"] == "blocked_preflight"
    assert summary["standard_restored"] == "not_changed"
    assert (root / "preflight.json").exists()
    assert "standard_gpu_has_non_workflow_compute_owner" in (root / "run-status.env").read_text()


def test_resume_reuses_only_a_complete_valid_apc_pair(tmp_path) -> None:
    taskpack = SimpleNamespace(manifest={"suite_revision": "longtext-demo-v3"})
    utility_runner = runner.UtilitySuiteRunner(taskpack, tmp_path / "run", quiet=True, resume=True)
    case_id = CASE_IDS[0]
    common = {
        "module": "apc",
        "case_id": case_id,
        "status": "completed",
        "business_quality": "passed",
        "runtime": {"runtime_completed": True},
        "mechanism_available": True,
        "prefix_contract_ok": True,
        "scored": True,
    }
    utility_runner._resume_latest = {
        f"{case_id}:apc_on_independent": common | {"slot_id": f"{case_id}:apc_on_independent"},
        f"{case_id}:apc_on_shared": common | {"slot_id": f"{case_id}:apc_on_shared"},
    }

    reused = utility_runner._resume_group_records("apc", case_id, ("independent", "shared"))
    assert reused is not None and len(reused) == 2
    utility_runner._resume_latest[f"{case_id}:apc_on_shared"] = common | {
        "slot_id": f"{case_id}:apc_on_shared",
        "status": "failed",
    }
    assert utility_runner._resume_group_records("apc", case_id, ("independent", "shared")) is None
    decisions = [json.loads(line) for line in (tmp_path / "run" / "resume-decisions.jsonl").read_text().splitlines()]
    assert [item["action"] for item in decisions] == ["reuse_completed_group", "rerun_entire_group"]
    assert decisions[-1]["missing_or_invalid_slots"] == [f"{case_id}:apc_on_shared"]


def test_targeted_apc_resume_requires_latest_failed_slot(tmp_path) -> None:
    slot_id = f"{CASE_IDS[1]}:apc_on_independent"
    records_path = tmp_path / "records.jsonl"
    records_path.write_text(
        "\n".join(
            json.dumps(item)
            for item in (
                {"slot_id": slot_id, "module": "apc", "status": "failed", "scored": True},
                {"slot_id": f"{CASE_IDS[1]}:apc_on_shared", "module": "apc", "status": "completed", "scored": True},
            )
        )
        + "\n",
        encoding="utf-8",
    )

    runner._validate_failed_apc_slot(tmp_path, slot_id)
    records_path.write_text(
        json.dumps({"slot_id": slot_id, "module": "apc", "status": "completed", "scored": True}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(runner.UtilitySuiteError, match="latest_scored_failure"):
        runner._validate_failed_apc_slot(tmp_path, slot_id)
    with pytest.raises(runner.UtilitySuiteError, match="one_planned_apc_slot"):
        runner._validate_failed_apc_slot(tmp_path, "not-a-planned-slot")


def test_preflight_records_external_gpu_pids_without_blocking_owner_check(monkeypatch) -> None:
    monkeypatch.setattr(
        runner,
        "_run_capture",
        lambda command, **_kwargs: {
            "command": command,
            "returncode": 0,
            "stdout": (
                "GPU 2: NVIDIA A100 (UUID: GPU-test)"
                if command == ["nvidia-smi", "-L"]
                else "index, name, memory.total, memory.used, memory.free, utilization.gpu [%]\n2, A100, 81920 MiB, 70000 MiB, 11920 MiB, 0 %"
                if any(arg.startswith("--query-gpu=index") for arg in command)
                else "gpu_uuid, pid, process_name, used_gpu_memory [MiB]\nGPU-test, 1234, python, 400 MiB\nGPU-test, 5678, python, 500 MiB"
                if any(arg.startswith("--query-compute-apps") for arg in command)
                else "模式=standard\n物理GPU=2\n"
                if command[-1] == "print-config"
                else "进程=运行中 pid=10 mode=standard\n端点=健康\n"
                if command[-1] == "status"
                else ""
            ),
        },
    )
    monkeypatch.setattr(runner, "_descendant_pids", lambda _pid: {10})
    monkeypatch.setattr(runner, "_gpu_uuid_for_index", lambda _output, _index: "GPU-test")
    monkeypatch.setattr(runner, "_manager_identity", lambda _env: {"status": {"returncode": 0}, "pid": None, "healthy": False, "mode": ""})
    result = runner.run_preflight(phase="apc")
    assert result.passed is False
    assert "standard_gpu_has_non_workflow_compute_owner" not in result.reasons
    assert [item["pid"] for item in result.evidence["external_gpu_processes_on_standard_gpu"]] == [1234, 5678]
    assert result.evidence["standard_gpu_free_memory_mib"] == 11920


def test_targeted_apc_resume_runs_only_selected_slot_without_calibration(tmp_path, monkeypatch) -> None:
    case_id = CASE_IDS[1]
    slot_id = f"{case_id}:apc_on_independent"
    case = SimpleNamespace(case_id=case_id, target_prefix_tokens=4096)
    utility_runner = runner.UtilitySuiteRunner(
        SimpleNamespace(manifest={"suite_revision": "longtext-demo-v3"}, cases=(case,)),
        tmp_path / "targeted-run",
        quiet=True,
        resume=True,
        target_slot_id=slot_id,
    )
    utility_runner.execution_id = "targeted-run-resume-07"

    class Codec:
        closed = False

        def close(self) -> None:
            self.closed = True

    codec = Codec()
    calls: list[tuple[str, str, bool]] = []
    namespace_pair = {
        layout: {
            "namespace": f"{layout}-namespace",
            "prefix_token_count": 4096,
            "prefix_token_digest": f"{layout}-digest",
        }
        for layout in ("independent", "shared")
    }

    monkeypatch.setattr(runner, "_llm_client", lambda: object())
    monkeypatch.setattr(runner, "_tokenizer_codec", lambda **_kwargs: codec)
    monkeypatch.setattr(
        runner,
        "_manager_identity",
        lambda _env: {"mode": "standard", "healthy": True, "pid": 10},
    )
    monkeypatch.setattr(utility_runner, "_install_signal_handlers", lambda: None)
    monkeypatch.setattr(utility_runner, "_restore_signal_handlers", lambda: None)
    monkeypatch.setattr(
        utility_runner,
        "_verify_standard_unchanged",
        lambda: setattr(utility_runner, "standard_restored", "unchanged"),
    )
    monkeypatch.setattr(utility_runner, "_apc_namespace_pair", lambda *_args: namespace_pair)

    def fake_run_apc(_case, layout, _client, _codec, *, scored, **_kwargs):
        calls.append((case_id, layout, scored))
        utility_runner.record({
            "slot_id": slot_id,
            "module": "apc",
            "case_id": case_id,
            "scored": scored,
            "status": "completed",
            "business_quality": "passed",
            "runtime": {"runtime_completed": True},
            "mechanism_available": True,
            "prefix_contract_ok": True,
        })
        return {"slot_id": slot_id, "status": "completed", "gate_ready": True}

    monkeypatch.setattr(utility_runner, "run_apc", fake_run_apc)
    summary = utility_runner.run_live(phase="apc")

    assert calls == [(case_id, "independent", True)]
    assert len(summary["standard"]) == 1
    assert summary["warmup"] == []
    assert summary["kv"] == []
    assert summary["targeted_recheck"] == {"slot_id": slot_id, "gate_ready": True, "status": "completed"}
    assert utility_runner.standard_restored == "unchanged"
    assert codec.closed
    records = [json.loads(line) for line in utility_runner.records_path.read_text(encoding="utf-8").splitlines()]
    scored = [record for record in records if record.get("scored")]
    assert len(scored) == 1
    assert scored[0]["execution_id"] == "targeted-run-resume-07"
    assert records[-1]["event"] == "targeted_recheck"
    assert records[-1]["target_slot_id"] == slot_id


def test_targeted_logit_resume_runs_only_selected_slot_without_warmup(tmp_path, monkeypatch) -> None:
    case_id = LOGIT_CASE_IDS[3]
    slot_id = f"{case_id}:logit_selective"
    case = SimpleNamespace(case_id=case_id)
    utility_runner = runner.UtilitySuiteRunner(
        SimpleNamespace(manifest={"suite_revision": "longtext-demo-v3"}, cases=(), logit_cases=(case,)),
        tmp_path / "targeted-logit-run",
        quiet=True,
        resume=True,
        target_slot_id=slot_id,
    )
    utility_runner.execution_id = "targeted-logit-run-resume-09"

    class Codec:
        closed = False

        def close(self) -> None:
            self.closed = True

    codec = Codec()
    calls: list[tuple[str, str, bool]] = []

    monkeypatch.setattr(runner, "_llm_client", lambda: object())
    monkeypatch.setattr(runner, "_tokenizer_codec", lambda **_kwargs: codec)
    monkeypatch.setattr(
        runner,
        "_manager_identity",
        lambda _env: {"mode": "standard", "healthy": True, "pid": 10},
    )
    monkeypatch.setattr(utility_runner, "_install_signal_handlers", lambda: None)
    monkeypatch.setattr(utility_runner, "_restore_signal_handlers", lambda: None)
    monkeypatch.setattr(
        utility_runner,
        "_verify_standard_unchanged",
        lambda: setattr(utility_runner, "standard_restored", "unchanged"),
    )

    def fake_run_logit(_case, policy, _client, _codec, *, scored):
        calls.append((case_id, policy, scored))
        utility_runner.record({
            "slot_id": slot_id,
            "module": "logit",
            "case_id": case_id,
            "condition": policy,
            "scored": scored,
            "status": "completed",
            "business_quality": "correct_abstention",
            "exact_available": True,
        })
        return {"slot_id": slot_id, "status": "completed", "gate_ready": True}

    monkeypatch.setattr(utility_runner, "run_logit", fake_run_logit)
    summary = utility_runner.run_live(phase="logit")

    assert calls == [(case_id, "logit_selective", True)]
    assert summary["standard"] == []
    assert len(summary["logit"]) == 1
    assert summary["warmup"] == []
    assert summary["kv"] == []
    assert summary["targeted_recheck"] == {"slot_id": slot_id, "gate_ready": True, "status": "completed"}
    assert utility_runner.standard_restored == "unchanged"
    assert codec.closed


def test_kv_group_returns_slot_ids_for_gate_reporting(tmp_path, monkeypatch) -> None:
    utility_runner = runner.UtilitySuiteRunner(
        SimpleNamespace(manifest={}),
        tmp_path / "kv-run",
        quiet=True,
    )
    monkeypatch.setattr(utility_runner, "_resume_group_records", lambda *_args: None)
    monkeypatch.setattr(
        utility_runner,
        "_run_kv_position",
        lambda _case, _condition, **_kwargs: {"gate_ready": True},
    )

    results = utility_runner._run_kv_group(
        SimpleNamespace(case_id=CASE_IDS[0]),
        ("full_replay", "continuation"),
        delegate=object(),
    )

    assert [item["slot_id"] for item in results] == [
        f"{CASE_IDS[0]}:full_replay",
        f"{CASE_IDS[0]}:continuation",
    ]


def test_logit_resume_skips_observed_positions_but_runs_unrequested_placeholders(tmp_path) -> None:
    utility_runner = runner.UtilitySuiteRunner(
        SimpleNamespace(manifest={"suite_revision": "longtext-demo-v3"}),
        tmp_path / "run",
        quiet=True,
        resume=True,
    )
    case_id = "MU-LOGIT-EASY-NOVA-OTD"
    completed = {
        "module": "logit",
        "slot_id": f"{case_id}:compact_once",
        "status": "completed",
        "business_quality": "passed",
        "exact_available": True,
        "provider_requests": [{"status": "response"}],
    }
    unrequested = {
        "module": "logit",
        "slot_id": f"{case_id}:full_context_once",
        "status": "unavailable",
        "business_quality": "unavailable_exact_logprobs",
        "exact_available": False,
        "provider_requests": [],
    }
    utility_runner._resume_latest = {
        completed["slot_id"]: completed,
        unrequested["slot_id"]: unrequested,
    }

    reused = utility_runner._resume_logit_position(case_id, "compact_once")

    assert reused is not None
    assert reused["resumed_skipped"] is True
    assert reused["gate_ready"] is True
    assert utility_runner._resume_logit_position(case_id, "full_context_once") is None


def test_resume_recovers_completed_logit_position_from_orphan_trace(tmp_path) -> None:
    run_root = tmp_path / "run"
    slot_id = "MU-LOGIT-EASY-NOVA-OTD:compact_once"
    prior_record = {
        "schema_version": "statebus.model_assist_utility.record.v1",
        "suite_revision": "longtext-demo-v3",
        "run_id": "run",
        "module": "logit",
        "case_id": "MU-LOGIT-EASY-NOVA-OTD",
        "condition": "compact_once",
        "slot_id": slot_id,
        "status": "unavailable",
        "business_quality": "unavailable_exact_logprobs",
        "exact_available": False,
        "provider_requests": [],
        "scored": True,
    }
    slots = run_root / "slots"
    slots.mkdir(parents=True)
    (run_root / "records.jsonl").write_text(json.dumps(prior_record) + "\n", encoding="utf-8")
    (slots / "MU-LOGIT-EASY-NOVA-OTD_compact_once.json").write_text(
        json.dumps(prior_record), encoding="utf-8"
    )
    trace = {
        "module": "logit",
        "case_id": "MU-LOGIT-EASY-NOVA-OTD",
        "condition": "compact_once",
        "slot_id": slot_id,
        "scored": True,
        "gold_outcome": "select",
        "correct": True,
        "provider_requests": [{"role": "executor", "status": "response"}],
        "choice_attempts": [{"extraction_payload": {"available": True}}],
        "runtime": {"runtime_completed": True},
    }
    trace_path = run_root / "decision-traces" / "resume-02" / "MU-LOGIT-EASY-NOVA-OTD-compact_once.json"
    trace_path.parent.mkdir(parents=True)
    trace_path.write_text(json.dumps(trace), encoding="utf-8")
    os.utime((slots / "MU-LOGIT-EASY-NOVA-OTD_compact_once.json"), ns=(1_700_000_000_000_000_000,) * 2)

    utility_runner = runner.UtilitySuiteRunner(
        SimpleNamespace(manifest={"suite_revision": "longtext-demo-v3"}),
        run_root,
        quiet=True,
        resume=True,
    )
    recovered = utility_runner.recover_orphaned_logit_traces()

    assert recovered == (slot_id,)
    record = utility_runner._resume_latest[slot_id]
    assert record["status"] == "completed"
    assert record["business_quality"] == "passed"
    assert record["exact_available"] is True
    assert record["orphan_trace_recovered"] is True


def test_repeated_slot_record_archives_previous_result(tmp_path) -> None:
    utility_runner = runner.UtilitySuiteRunner(
        SimpleNamespace(manifest={"suite_revision": "longtext-demo-v3"}),
        tmp_path / "run",
        quiet=True,
    )
    base = {
        "slot_id": "case:condition",
        "module": "logit",
        "case_id": "case",
        "condition": "condition",
        "scored": True,
    }
    utility_runner.record(base | {"status": "failed"})
    utility_runner.record(base | {"status": "completed"})
    archives = list((tmp_path / "run" / "slots" / "archive").glob("*.json"))
    assert len(archives) == 1
    assert json.loads(archives[0].read_text())["status"] == "failed"
    assert json.loads((tmp_path / "run" / "slots" / "case_condition.json").read_text())["status"] == "completed"


def test_standard_restore_records_failure_and_success(tmp_path, monkeypatch) -> None:
    utility_runner = runner.UtilitySuiteRunner(None, tmp_path / "restore", quiet=True)
    utility_runner._standard_identity = {"mode": "standard", "pid": 123, "healthy": True}
    monkeypatch.setattr(runner, "_manager_identity", lambda _path: {"mode": "standard", "pid": 123, "healthy": True})
    monkeypatch.setattr(runner, "_verify_standard_endpoints", lambda: {"passed": True})
    utility_runner._restore_standard_service(None)
    assert utility_runner.standard_restored == "true"
    assert json.loads((tmp_path / "restore" / "service" / "restore-evidence.json").read_text())["standard_restored"] == "true"

    failed_runner = runner.UtilitySuiteRunner(None, tmp_path / "restore-failed", quiet=True)
    failed_runner._standard_identity = {"mode": "standard", "pid": 123, "healthy": True}
    monkeypatch.setattr(runner, "_verify_standard_endpoints", lambda: {"passed": False, "reason": "test_logprobs_failed"})
    with pytest.raises(runner.UtilitySuiteError, match="test_logprobs_failed"):
        failed_runner._restore_standard_service(None)
    assert failed_runner.standard_restored == "false"
    assert json.loads((tmp_path / "restore-failed" / "service" / "restore-evidence.json").read_text())["standard_restored"] == "false"


def test_standard_unchanged_path_verifies_original_manager_identity(tmp_path, monkeypatch) -> None:
    utility_runner = runner.UtilitySuiteRunner(None, tmp_path / "unchanged", quiet=True)
    original = {"mode": "standard", "pid": 123, "healthy": True}
    utility_runner._standard_identity = original
    monkeypatch.setattr(runner, "_manager_identity", lambda _path: dict(original))
    utility_runner._verify_standard_unchanged()
    assert utility_runner.standard_restored == "unchanged"
    evidence = json.loads((tmp_path / "unchanged" / "service" / "standard-unchanged-verification.json").read_text())
    assert evidence["original"]["pid"] == evidence["current"]["pid"] == 123

    monkeypatch.setattr(runner, "_manager_identity", lambda _path: {"mode": "standard", "pid": 456, "healthy": True})
    with pytest.raises(runner.UtilitySuiteError, match="standard_service_changed_without_utility_switch"):
        utility_runner._verify_standard_unchanged()
    assert utility_runner.standard_restored == "false"


def test_streaming_observer_measures_first_content_without_changing_request_contract(monkeypatch) -> None:
    class FakeStream:
        def __aiter__(self):
            async def chunks():
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='{"choice_code":'), finish_reason=None)], usage=None)
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='"A"}'), finish_reason="stop")], usage=None)
                yield SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=12, completion_tokens=4, total_tokens=16))
            return chunks()

    class FakeCompletions:
        request: dict[str, object] = {}

        async def create(self, **request):
            self.request = request
            return FakeStream()

    completions = FakeCompletions()

    class FakeProviderClient:
        chat = SimpleNamespace(completions=completions)

        async def close(self):
            return None

    client = runner._llm_client(timeout_s=1.0, executor_max_tokens=32)
    monkeypatch.setattr(client, "_build_provider_client", lambda _provider: FakeProviderClient())
    schema = runner._json_schema({"choice_code": {"type": "string", "enum": ["A", "B"]}})
    result, observation = runner._complete_streaming(
        client,
        [runner.ChatMessage("user", "Choose A or B.")],
        purpose="executor",
        schema=schema,
    )

    assert result is not None and result.text == '{"choice_code":"A"}'
    assert observation["ttft_ms"] is not None and observation["token_event_count"] == 2
    assert observation["usage"]["total_tokens"] == 16
    assert completions.request["stream"] is True
    assert completions.request["seed"] == 7
    assert completions.request["logprobs"] is True
    assert completions.request["top_logprobs"] == 20
    assert completions.request["response_format"]["type"] == "json_schema"
    assert completions.request["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
