from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from v2.benchmark.native_latent_experiment import (
    ChatCompletionReceipt,
    DEFAULT_MANIFEST,
    LANES,
    NativeLatentExperimentError,
    V2_MANIFEST,
    V1_MANIFEST,
    V3_MANIFEST,
    V4_MANIFEST,
    V6_MANIFEST,
    _build_evidence_pack,
    _claim_set_schema,
    _compact_locator,
    _complete_request,
    _consumer_receipt,
    _evaluate_claim_text,
    _mechanism_receipt,
    _parse_claim_set,
    _produce_request,
    _producer_receipt,
    _retriever_messages,
    _run_n1,
    _run_t0,
    _summarizer_messages,
    _term_matches,
    _verified_artifact,
    load_experiment_definition,
)
from v2.contracts import LatentHandoffMode, NeuralCompatibilitySignature
from v2.runtime.claims import ClaimSetValidator
from v2.runtime.latent_handoff import (
    LatentHandoffController,
    LatentHandoffPolicyConfig,
)
from v2.runtime.role_model_backend import (
    FakeRoleModelBackend,
    LatentBackendError,
)
from v2.utils import stable_json_dumps


PROJECT_ROOT = Path(__file__).resolve().parents[3]
FROZEN_MANIFEST_SHA256 = (
    "d53c26351732620f3aee6198efc1f6b03147d633a733db8edcf47ce526515c4e"
)
FROZEN_V2_MANIFEST_SHA256 = (
    "ec345fdbbdb02f1a49df58c8212b3af8ea6816c38961a88af90db73238ca7f7f"
)
FROZEN_V3_MANIFEST_SHA256 = (
    "b6599949c7821d6722d9de655db58790e389cd11d84e48fee9f084b0488a0232"
)
FROZEN_V4_MANIFEST_SHA256 = (
    "b46769f43386c8d199f699c7a405a0169f1c3e162be938e9505a38fa6ebdeccd"
)
FROZEN_V5_MANIFEST_SHA256 = (
    "293abef320c534480ba58358b1f1801e5b2ca86878a96ae84c1255ed9a4b118e"
)
FROZEN_V6_MANIFEST_SHA256 = (
    "6c08351e3b08672b494f6dec98f73194fb3d6754aee4c498266254089ecd9e9c"
)


def _definition():
    return load_experiment_definition(DEFAULT_MANIFEST, project_root=PROJECT_ROOT)


def _v1_definition():
    return load_experiment_definition(V1_MANIFEST, project_root=PROJECT_ROOT)


def _v2_definition():
    return load_experiment_definition(V2_MANIFEST, project_root=PROJECT_ROOT)


def _v3_definition():
    return load_experiment_definition(V3_MANIFEST, project_root=PROJECT_ROOT)


def _v4_definition():
    return load_experiment_definition(V4_MANIFEST, project_root=PROJECT_ROOT)


def _v6_definition():
    return load_experiment_definition(V6_MANIFEST, project_root=PROJECT_ROOT)


def _case_context():
    definition = _definition()
    case = definition.cases[0]
    pack = _build_evidence_pack(case, definition.sources)
    artifact, rows = _verified_artifact(case, pack)
    return definition, case, pack, artifact, rows


def _valid_claim_set_text(case: Any, pack: Any) -> str:
    evidence = {
        item.item_id: item
        for bucket in (
            pack.hard_facts,
            pack.structured_evidence,
            pack.semantic_contexts,
            pack.lexical_hints,
            pack.conflicts,
        )
        for item in bucket
    }
    claims = []
    for index, fact in enumerate(case.required_facts, start=1):
        source_item_ids = list(fact.source_item_ids)
        locators = [
            _compact_locator(evidence[source_item_id])
            for source_item_id in source_item_ids
        ]
        claims.append({
            "claim_id": f"claim-{index}",
            "claim_text": " ".join(group[0] for group in fact.term_groups),
            "claim_type": "fact",
            "supporting_evidence_item_ids": source_item_ids,
            "supporting_artifact_ref_ids": [],
            "citation_locators": locators,
            "numeric_fields": {},
            "uncertainty_note": "",
            "status": "ready",
        })
    return stable_json_dumps({
        "claim_set_id": f"claims-{case.case_id}",
        "task_id": case.case_id,
        "claims": claims,
        "status": "ready",
        "schema_version": "statebus.claim_set.v1",
    })


class _StaticChatClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def complete(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        response_schema: Mapping[str, Any],
        max_tokens: int,
        seed: int,
    ) -> ChatCompletionReceipt:
        del messages, response_schema, max_tokens, seed
        self.calls += 1
        return ChatCompletionReceipt(
            text=self.text,
            model="qwen3-32b",
            prompt_tokens=32,
            completion_tokens=64,
            total_tokens=96,
            elapsed_ms=1.0,
        )


class _ProduceFailureBackend:
    def __init__(self) -> None:
        self.release_calls = 0

    def produce(self, _request: Any) -> Any:
        raise LatentBackendError("latent_plugin_not_ready")

    def complete(self, _request: Any) -> Any:
        raise AssertionError("complete must not run after produce failure")

    def release(self, _ref_id: str) -> None:
        self.release_calls += 1


def test_frozen_v1_manifest_hash_and_contract_remain_unchanged() -> None:
    definition = _v1_definition()

    assert definition.manifest_hash == FROZEN_MANIFEST_SHA256
    assert len(definition.cases) == 6
    assert sum(len(case.required_facts) for case in definition.cases) == 24
    assert {case.category for case in definition.cases} == {
        "cross_paragraph_time_qualification",
        "conflict_or_risk_judgment",
        "condition_and_exception_combination",
    }
    for left, right in zip(
        definition.cases[::2], definition.cases[1::2], strict=True
    ):
        assert set(left.lane_order) == set(LANES)
        assert right.lane_order == tuple(reversed(left.lane_order))
        assert not left.source_item_ids
        assert not right.source_item_ids


def test_v2_manifest_hash_and_contract_are_frozen() -> None:
    definition = _v2_definition()

    assert definition.manifest_path == V2_MANIFEST
    assert definition.manifest_hash == FROZEN_V2_MANIFEST_SHA256
    assert len(definition.cases) == 6


def test_v3_manifest_hash_and_contract_are_frozen() -> None:
    definition = _v3_definition()

    assert definition.manifest_path == V3_MANIFEST
    assert definition.manifest_hash == FROZEN_V3_MANIFEST_SHA256


def test_v4_manifest_hash_and_contract_are_frozen() -> None:
    definition = _v4_definition()

    assert definition.manifest_path == V4_MANIFEST
    assert definition.manifest_hash == FROZEN_V4_MANIFEST_SHA256


def test_v5_manifest_balances_narrative_synthesis_and_plan_modes() -> None:
    definition = _definition()

    assert definition.manifest_path == DEFAULT_MANIFEST
    assert definition.manifest_hash == FROZEN_V5_MANIFEST_SHA256
    assert len(definition.cases) == 6
    assert sum(len(case.required_facts) for case in definition.cases) == 24
    assert {case.category for case in definition.cases} == {
        "long_document_causal_analysis",
        "cross_document_evidence_synthesis",
        "conditional_plan_switch",
    }
    assert all(case.task_mode == case.category for case in definition.cases)
    assert all(case.source_item_ids for case in definition.cases)
    for left, right in zip(
        definition.cases[::2], definition.cases[1::2], strict=True
    ):
        assert set(left.lane_order) == set(LANES)
        assert right.lane_order == tuple(reversed(left.lane_order))


def test_v6_is_explicit_post_remediation_diagnostic_with_40_latent_steps() -> None:
    definition = _v6_definition()

    assert definition.manifest_path == V6_MANIFEST
    assert definition.manifest_hash == FROZEN_V6_MANIFEST_SHA256
    assert definition.fixed_parameters["latent_steps"] == 40
    assert definition.fixed_parameters["chat_template_thinking"] is False
    assert (
        definition.fixed_parameters["consumer_prompt_mode"]
        == "structured_messages"
    )
    assert "not a fresh quality holdout" in str(
        definition.payload["claim_boundary"]
    )


def test_case_scoped_evidence_pack_contains_only_authorized_sources() -> None:
    definition = _definition()
    corpus_ids = {source.item_id for source in definition.sources}

    for case in definition.cases:
        pack = _build_evidence_pack(case, definition.sources)
        selected_ids = {item.item_id for item in pack.semantic_contexts}
        assert selected_ids == set(case.source_item_ids)
        assert selected_ids < corpus_ids
        assert {
            source_id
            for fact in case.required_facts
            for source_id in fact.source_item_ids
        } == selected_ids


def test_evidence_pack_rejects_fact_source_outside_case_authorization() -> None:
    definition = _definition()
    case = definition.cases[0]
    unauthorized = replace(
        case,
        source_item_ids=(definition.cases[1].source_item_ids[0],),
    )

    with pytest.raises(
        NativeLatentExperimentError,
        match="experiment_fact_source_unauthorized",
    ):
        _build_evidence_pack(unauthorized, definition.sources)


def test_generation_payload_excludes_post_generation_scoring_contract() -> None:
    definition = _definition()

    for case in definition.cases:
        payload = case.generation_payload()
        serialized = stable_json_dumps(payload)
        assert set(payload) == {"case_id", "category", "task", "task_mode"}
        assert "required_facts" not in serialized
        assert "term_groups" not in serialized
        assert "source_item_ids" not in serialized
        assert all(fact.fact_id not in serialized for fact in case.required_facts)


def test_v1_generation_payload_remains_backward_compatible() -> None:
    for case in _v1_definition().cases:
        assert set(case.generation_payload()) == {"case_id", "category", "task"}


def test_phrase_matcher_handles_inflection_and_negative_auxiliaries() -> None:
    assert _term_matches("freeze low priority", "freezes low-priority builds")
    assert _term_matches("reserve emergency freight", "reserves emergency freight")
    assert _term_matches("continue plan copper", "continues Plan Copper")
    assert _term_matches("cannot authorize", "could not authorize")
    assert _term_matches("remained held", "remains held")


def test_plan_switch_tasks_do_not_disclose_selected_branch() -> None:
    expected_branches = {
        "latent-plan-atlas-continuity": "plan copper",
        "latent-plan-cobalt-network": "plan bridge",
    }

    for case in _definition().cases:
        if case.category != "conditional_plan_switch":
            continue
        visible = stable_json_dumps(case.generation_payload()).lower()
        assert expected_branches[case.case_id] not in visible


def test_model_visible_surfaces_never_include_expected_fact_metadata(
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    definition, case, pack, artifact, _rows = _case_context()
    producer = _produce_request(
        case=case,
        pack=pack,
        signature=neural_signature,
        latent_steps=8,
        run_id="test-run",
        suffix="l1",
    )
    consumer = _complete_request(
        case=case,
        pack=pack,
        artifact=artifact,
        ref_id="opaque-ref",
        signature=neural_signature,
        fixed_parameters=definition.fixed_parameters,
        run_id="test-run",
        suffix="l1",
    )
    response_schema = _claim_set_schema(case, pack, artifact)
    surfaces = (
        _retriever_messages(case, pack),
        _summarizer_messages(
            case=case,
            pack=pack,
            artifact=artifact,
            handoff_kind="full_selected_evidence",
            handoff_text="selected evidence",
        ),
        producer.messages,
        consumer.rendered_prompt,
        response_schema,
    )

    serialized = stable_json_dumps(surfaces)
    assert consumer.messages[0]["role"] == "system"
    assert consumer.messages[1] == {
        "role": "user",
        "content": consumer.rendered_prompt,
    }
    assert "required_facts" not in serialized
    assert "term_groups" not in serialized
    assert "source_item_ids" not in serialized
    assert all(fact.fact_id not in serialized for fact in case.required_facts)
    assert not ({
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
    } & _keys(response_schema))


def test_claim_parser_and_post_generation_scorer_cover_all_required_facts() -> None:
    _definition_value, case, pack, artifact, rows = _case_context()
    text = _valid_claim_set_text(case, pack)

    parsed = _parse_claim_set(text)
    quality = _evaluate_claim_text(
        text,
        case=case,
        pack=pack,
        artifact=artifact,
        artifact_rows=rows,
    )

    assert len(parsed.claims) == 4
    assert quality["parse_ok"] is True
    assert quality["validator_ok"] is True
    assert quality["fact_passed_count"] == 4
    assert quality["all_required_facts_passed"] is True


def test_cross_document_fact_requires_all_declared_source_citations() -> None:
    definition = _definition()
    case = next(
        item
        for item in definition.cases
        if item.case_id == "latent-synthesis-meridian-response"
    )
    pack = _build_evidence_pack(case, definition.sources)
    artifact, rows = _verified_artifact(case, pack)
    payload = json.loads(_valid_claim_set_text(case, pack))
    cross_source_fact = next(
        fact for fact in case.required_facts if len(fact.source_item_ids) == 2
    )
    target = next(
        claim
        for claim in payload["claims"]
        if all(
            group[0].lower() in claim["claim_text"].lower()
            for group in cross_source_fact.term_groups
        )
    )
    target["supporting_evidence_item_ids"] = [
        cross_source_fact.source_item_ids[0]
    ]
    target["citation_locators"] = target["citation_locators"][:1]

    quality = _evaluate_claim_text(
        stable_json_dumps(payload),
        case=case,
        pack=pack,
        artifact=artifact,
        artifact_rows=rows,
    )
    verdict = next(
        item
        for item in quality["fact_verdicts"]
        if item["fact_id"] == cross_source_fact.fact_id
    )

    assert verdict["terms_passed"] is True
    assert verdict["citation_passed"] is False
    assert verdict["passed"] is False


def test_t0_invalid_retriever_json_retains_completion_receipt() -> None:
    definition, case, pack, artifact, rows = _case_context()
    chat_client = _StaticChatClient('{"analysis":')

    record = _run_t0(
        case=case,
        pack=pack,
        artifact=artifact,
        artifact_rows=rows,
        chat_client=chat_client,  # type: ignore[arg-type]
        fixed_parameters=definition.fixed_parameters,
    )

    assert record["ok"] is False
    assert record["error_code"] == "retriever_text_handoff_invalid"
    assert record["model_call_count"] == 1
    assert record["retriever"]["text"] == '{"analysis":'
    assert record["retriever"]["usage"]["completion_tokens"] == 64
    assert record["quality"]["fact_passed_count"] == 0


def test_safe_receipts_drop_prompts_tokens_and_raw_tensor_payloads(
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    definition, case, pack, artifact, _rows = _case_context()
    prompt_secret = "PROMPT_MUST_NOT_PERSIST"
    token_secret = "TOKEN_MUST_NOT_PERSIST"
    tensor_secret = "RAW_TENSOR_MUST_NOT_PERSIST"
    request = _produce_request(
        case=case,
        pack=pack,
        signature=neural_signature,
        latent_steps=8,
        run_id="test-run",
        suffix="receipt",
    )
    request = replace(
        request,
        messages=({"role": "user", "content": prompt_secret},),
    )
    backend = FakeRoleModelBackend(signature=neural_signature)
    produced = backend.produce(request)
    produced = replace(
        produced,
        telemetry={
            "producer_prefill_ms": 1.0,
            "rendered_prompt": prompt_secret,
            "api_token": token_secret,
            "raw_tensor": tensor_secret,
        },
    )
    complete_request = _complete_request(
        case=case,
        pack=pack,
        artifact=artifact,
        ref_id=produced.ref.ref_id,
        signature=neural_signature,
        fixed_parameters=definition.fixed_parameters,
        run_id="test-run",
        suffix="receipt",
    )
    completion = backend.complete(complete_request)
    completion = replace(
        completion,
        telemetry={
            "consumer_model_ms": 2.0,
            "rendered_prompt": prompt_secret,
            "api_token": token_secret,
            "raw_tensor": tensor_secret,
        },
    )
    receipt = {
        "producer": _producer_receipt(request, produced),
        "consumer": _consumer_receipt(completion),
        "mechanism": _mechanism_receipt(
            produced=produced,
            completion=completion,
            released=True,
        ),
    }

    serialized = stable_json_dumps(receipt)
    assert prompt_secret not in serialized
    assert token_secret not in serialized
    assert tensor_secret not in serialized
    assert not ({"messages", "rendered_prompt", "api_token", "raw_tensor"} & _keys(receipt))


def test_n1_rejects_before_forward_releases_once_and_uses_c0_fallback(
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    definition, case, pack, artifact, rows = _case_context()
    chat_client = _StaticChatClient(_valid_claim_set_text(case, pack))
    backend = FakeRoleModelBackend(signature=neural_signature)
    controller = LatentHandoffController(LatentHandoffPolicyConfig(
        mode=LatentHandoffMode.FORCE,
        min_evidence_tokens=1,
        max_evidence_tokens=8_000,
        latent_steps=int(definition.fixed_parameters["latent_steps"]),
        ttl_s=300,
    ))

    record = _run_n1(
        case=case,
        pack=pack,
        artifact=artifact,
        artifact_rows=rows,
        chat_client=chat_client,  # type: ignore[arg-type]
        backend=backend,  # type: ignore[arg-type]
        controller=controller,
        signature=neural_signature,
        fixed_parameters=definition.fixed_parameters,
        run_id="test-run",
    )

    assert record["fallback_used"] is True
    assert record["latent_success"] is False
    assert record["quality"]["all_required_facts_passed"] is True
    assert record["mechanism"]["pre_forward_rejected"] is True
    assert record["mechanism"]["rejection_reason"] == "latent_model_incompatible"
    assert record["mechanism"]["released"] is True
    assert len(backend.released_ref_ids) == 1
    assert chat_client.calls == 1


def test_n1_producer_failure_still_uses_exactly_one_c0_fallback(
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    definition, case, pack, artifact, rows = _case_context()
    chat_client = _StaticChatClient(_valid_claim_set_text(case, pack))
    backend = _ProduceFailureBackend()
    controller = LatentHandoffController(LatentHandoffPolicyConfig(
        mode=LatentHandoffMode.FORCE,
        min_evidence_tokens=1,
        max_evidence_tokens=8_000,
        latent_steps=int(definition.fixed_parameters["latent_steps"]),
        ttl_s=300,
    ))

    record = _run_n1(
        case=case,
        pack=pack,
        artifact=artifact,
        artifact_rows=rows,
        chat_client=chat_client,  # type: ignore[arg-type]
        backend=backend,  # type: ignore[arg-type]
        controller=controller,
        signature=neural_signature,
        fixed_parameters=definition.fixed_parameters,
        run_id="test-run",
    )

    assert record["fallback_used"] is True
    assert record["fallback_reason"] == "latent_plugin_not_ready"
    assert record["latent_success"] is False
    assert record["mechanism"]["negative_signature_changed"] is False
    assert record["mechanism"]["pre_forward_rejected"] is False
    assert backend.release_calls == 0
    assert chat_client.calls == 1


def _keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return set(map(str, value)) | set().union(*(_keys(item) for item in value.values()))
    if isinstance(value, (tuple, list)):
        return set().union(*(_keys(item) for item in value))
    return set()
