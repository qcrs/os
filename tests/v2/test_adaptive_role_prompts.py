from __future__ import annotations

import json

import pytest

from runtime.llm import LLMResult, LLMUsage, parse_tagged_json
from v2.contracts import AdaptiveTaskEnvelope, Claim, ClaimSet, RiskClass, WorkflowMode
from v2.runtime.role_path import RolePathRunner


class RecordingLLMClient:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        messages,
        *,
        purpose: str,
        temperature: float | None = None,
        response_schema: dict[str, object] | None = None,
    ) -> LLMResult:
        self.calls.append({
            "messages": messages,
            "purpose": purpose,
            "temperature": temperature,
            "response_schema": response_schema,
        })
        return LLMResult(
            text=json.dumps(self.response),
            model="test-model",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    def describe(self) -> dict[str, object]:
        return {"backend": "recording"}


def _single_call(client: RecordingLLMClient) -> tuple[str, dict[str, object]]:
    assert len(client.calls) == 1
    call = client.calls[0]
    messages = call["messages"]
    assert isinstance(messages, list) and len(messages) == 1
    prompt = messages[0].content
    schema = call["response_schema"]
    assert isinstance(prompt, str)
    assert isinstance(schema, dict)
    return prompt, schema


def _assert_vllm_073_xgrammar_compatible(schema: object) -> None:
    if isinstance(schema, dict):
        assert "pattern" not in schema
        assert "enum" not in schema
        if schema.get("type") in {"integer", "number"}:
            assert not {
                "minimum",
                "maximum",
                "exclusiveMinimum",
                "exclusiveMaximum",
                "multipleOf",
            } & schema.keys()
        if schema.get("type") == "array":
            assert not {
                "uniqueItems",
                "contains",
                "minContains",
                "maxContains",
                "minItems",
                "maxItems",
            } & schema.keys()
        for value in schema.values():
            _assert_vllm_073_xgrammar_compatible(value)
    elif isinstance(schema, list):
        for value in schema:
            _assert_vllm_073_xgrammar_compatible(value)


def test_adaptive_planner_prompt_and_schema_expose_only_authorized_capabilities() -> None:
    response_steps = [
        {
            "step_id": "retrieve",
            "role": "retriever",
            "capability_id": "retrieve_semantic_evidence_v1",
            "goal": "retrieve cited evidence",
            "depends_on": ["[]"],
            "input_ref_ids": ["null"],
            "input_ref_kinds": ["n/a"],
            "required_input_fields": [],
            "output_contract_version": "statebus.evidence_pack.v2",
            "completion_criteria": {"min_locator_count": 1},
            "on_failure": "request_replan",
        },
        {
            "step_id": "extract",
            "role": "executor",
            "capability_id": "extract_metric_series_v1",
            "goal": "extract the revenue series",
            "depends_on": ["retrieve"],
            "input_ref_ids": [],
            "input_ref_kinds": [],
            "required_input_fields": [],
            "output_contract_version": "statebus.metric_series.v1",
            "completion_criteria": {"min_rows": 1},
            "on_failure": "request_replan",
        },
        {
            "step_id": "report",
            "role": "summarizer",
            "capability_id": "compose_cited_report_v1",
            "goal": "compose a cited report",
            "depends_on": ["extract"],
            "input_ref_ids": [],
            "input_ref_kinds": [],
            "required_input_fields": [],
            "output_contract_version": "statebus.cited_report.v1",
            "completion_criteria": {"min_locator_count": 1},
            "on_failure": "request_replan",
        },
    ]
    response = {
        "proposal_id": "proposal-1",
        "retriever_step": response_steps[0],
        "primary_executor_step": response_steps[1],
        "additional_executor_steps": [],
        "summarizer_step": response_steps[2],
        "final_output_contract_version": "statebus.cited_report.v1",
        "requested_memory_policy": "none",
        "planner_notes": "bounded three-step plan",
    }
    client = RecordingLLMClient(response)
    runner = RolePathRunner(llm_client=client)
    surface = (
        {
            "id": "retrieve_semantic_evidence_v1",
            "role": "retriever",
            "accepts": [],
            "produces": ["canonical_evidence_pack"],
            "output_contract": "statebus.evidence_pack.v2",
            "completion_criteria": {"min_locator_count": {"type": "integer", "minimum": 1, "maximum": 3}},
        },
        {
            "id": "extract_metric_series_v1",
            "role": "executor",
            "accepts": ["canonical_evidence_pack"],
            "produces": ["execution_artifact"],
            "output_contract": "statebus.metric_series.v1",
            "completion_criteria": {"min_rows": {"type": "integer", "minimum": 1, "maximum": 2}},
        },
        {
            "id": "compose_cited_report_v1",
            "role": "summarizer",
            "accepts": ["canonical_evidence_pack", "execution_artifact"],
            "produces": ["execution_artifact"],
            "output_contract": "statebus.cited_report.v1",
            "completion_criteria": {"min_locator_count": {"type": "integer", "minimum": 1, "maximum": 3}},
        },
    )
    envelope = AdaptiveTaskEnvelope(
        task_id="task-1",
        canonical_task_spec_hash="spec-1",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="long_doc_analysis_v1",
        allowed_capability_ids=tuple(str(item["id"]) for item in surface),
        allowed_output_contracts=(
            "statebus.evidence_pack.v2",
            "statebus.metric_series.v1",
            "statebus.cited_report.v1",
        ),
        risk_class=RiskClass.WORKSPACE_WRITE,
        max_plan_steps=4,
    )

    proposal = runner.propose_plan(
        envelope=envelope,
        task_goal="derive and report a cited revenue series",
        allowed_inputs=(),
        capability_surface=surface,
        required_roles=("retriever", "executor", "summarizer"),
        replan_context={
            "reason": "single_policy_repair",
            "invalid_proposal": {"steps": []},
            "policy_report": {"issues": ["role_cardinality_violation"]},
        },
        role_slot_layout=True,
    )

    assert len(proposal.steps) == 3
    assert proposal.steps[0].depends_on == ()
    assert proposal.steps[0].input_ref_ids == ()
    assert proposal.steps[0].input_ref_kinds == ()
    assert [step.on_failure for step in proposal.steps] == [
        "request_replan",
        "fallback_deterministic",
        "fail",
    ]
    prompt, schema = _single_call(client)
    assert "derive and report a cited revenue series" in prompt
    assert "phase_one_llm_python_enabled" not in prompt
    assert '"allow_llm_python": false' in prompt
    assert '"required_roles": ["retriever", "executor", "summarizer"]' in prompt
    assert "bounded_metric_python_v1" not in prompt
    assert "Do not emit on_failure" in prompt
    assert "Return a complete replacement plan" in prompt
    assert "Do not emit a top-level steps field" in prompt
    assert "Use the fewest Executor stages" in prompt
    assert "retains every field the downstream stage needs" in prompt
    assert "cannot split one input into branches and recombine them" in prompt
    assert "choose bounded Python when any of those operations is required" in prompt
    assert "fallback_capability_id" in prompt
    assert "Omit additional_executor_steps" in prompt
    assert "completion_criteria" in prompt
    payload = parse_tagged_json(prompt, "sb-adaptive-plan-v1")
    assert payload["authority"]["role_cardinality"] == {
        "executor": {"minimum": 1, "maximum": 2},
        "retriever": {"minimum": 1, "maximum": 1},
        "summarizer": {"minimum": 1, "maximum": 1},
    }
    assert payload["authority"]["capability_ids_by_role"] == {
        "executor": ["extract_metric_series_v1"],
        "retriever": ["retrieve_semantic_evidence_v1"],
        "summarizer": ["compose_cited_report_v1"],
    }
    assert "authority.capability_ids_by_role[role]" in prompt
    assert [item["id"] for item in payload["capability_surface"]] == [
        "retrieve_semantic_evidence_v1",
        "extract_metric_series_v1",
        "compose_cited_report_v1",
    ]
    assert payload["authority"]["allowed_memory_policies"] == ["none", "assist", "artifact", "strategy"]
    assert payload["authority"]["controller_owned_failure_actions"]["retriever"] == "request_replan for at most one eligible step"
    assert "steps" not in schema["properties"]
    assert {
        "retriever_step",
        "primary_executor_step",
        "summarizer_step",
    } <= set(schema["required"])
    assert "additional_executor_steps" not in schema["required"]
    assert "additional_executor_steps" in schema["properties"]
    step_properties = schema["properties"]["primary_executor_step"]["properties"]
    assert step_properties["capability_id"] == {"type": "string"}
    assert step_properties["role"] == {"type": "string"}
    assert step_properties["completion_criteria"]["additionalProperties"] is False
    assert step_properties["required_input_fields"]["type"] == "array"
    assert "required_input_fields" not in schema["properties"]["primary_executor_step"]["required"]
    assert "on_failure" not in step_properties
    _assert_vllm_073_xgrammar_compatible(schema)


def test_adaptive_retriever_schema_closes_corpus_and_evidence_types() -> None:
    client = RecordingLLMClient({
        "queries": ["ACME revenue by quarter"],
        "evidence_types": ["semantic_context", "table"],
        "target_entities": ["ACME"],
        "time_scope": "2025Q4 to 2026Q1",
        "corpus_scope_ids": ["local-long-doc"],
        "max_candidates": 8,
    })
    request = RolePathRunner(llm_client=client).build_evidence_request(
        task_id="task-1",
        step_id="retrieve",
        step_goal="find the cited revenue values",
        corpus_scope_ids=("local-long-doc",),
        evidence_types=("semantic_context", "table"),
        target_entities=("ACME",),
        time_scope="2025Q4 to 2026Q1",
        task_goal="Compare ACME revenue across the two reported quarters.",
    )

    assert request.queries == ("ACME revenue by quarter",)
    prompt, schema = _single_call(client)
    assert "find the cited revenue values" in prompt
    assert "Compare ACME revenue across the two reported quarters." in prompt
    payload = parse_tagged_json(prompt, "sb-evidence-request-v1")
    assert payload["corpus_scope"] == ["local-long-doc"]
    assert payload["evidence_types"] == ["semantic_context", "table"]
    assert payload["authority"]["target_entities"] == ["ACME"]
    assert payload["authority"]["time_scope"] == "2025Q4 to 2026Q1"
    properties = schema["properties"]
    assert properties["corpus_scope_ids"]["items"] == {"type": "string"}
    assert properties["evidence_types"]["items"] == {"type": "string"}
    assert "target_entities" not in properties
    assert "time_scope" not in properties
    _assert_vllm_073_xgrammar_compatible(schema)


def test_adaptive_executor_receives_goal_operation_contract_and_input_preview() -> None:
    client = RecordingLLMClient({
        "input_artifact_refs": ["evidence-ref"],
        "operations": [
            {"op": "select", "arguments": {"columns": ["quarter", "revenue_musd"]}},
            {"op": "sort", "arguments": {"columns": ["quarter"]}},
        ],
        "output_contract_version": "statebus.metric_series.v1",
    })
    program = RolePathRunner(llm_client=client).build_transform_program(
        program_id="program-1",
        authorized_input_refs=("evidence-ref",),
        input_schema={"evidence-ref": ("quarter", "revenue_musd")},
        output_contract_version="statebus.metric_series.v1",
        operation_catalog=("select", "rename", "sort"),
        step_goal="extract the two-quarter revenue series",
        desired_output_fields=("quarter", "revenue_musd"),
        input_preview=(
            {"quarter": "2025Q4", "revenue_musd": 100.0},
            {"quarter": "2026Q1", "revenue_musd": 120.0},
        ),
    )

    assert [step.op for step in program.operations] == ["select", "sort"]
    prompt, schema = _single_call(client)
    assert "extract the two-quarter revenue series" in prompt
    payload = parse_tagged_json(prompt, "sb-transform-program-v1")
    assert payload["operation_contracts"]["select"]["required"] == ["columns"]
    assert payload["operation_contracts"]["rename"]["required"] == ["source", "target"]
    assert "never use derive_safe to copy or rename" in prompt
    assert payload["input_preview"][1] == {"quarter": "2026Q1", "revenue_musd": 120.0}
    properties = schema["properties"]
    assert properties["input_artifact_refs"]["items"] == {"type": "string"}
    assert properties["operations"]["items"]["properties"]["op"] == {"type": "string"}
    assert properties["output_contract_version"]["const"] == "statebus.metric_series.v1"
    _assert_vllm_073_xgrammar_compatible(schema)


def test_adaptive_executor_receives_bounded_grouped_aggregation_contract() -> None:
    client = RecordingLLMClient({
        "input_artifact_refs": ["metrics-ref"],
        "operations": [{
            "op": "aggregate_grouped",
            "arguments": {"group_field": "segment", "value_field": "revenue_musd"},
        }],
        "output_contract_version": "statebus.aggregation.v1",
    })
    program = RolePathRunner(llm_client=client).build_transform_program(
        program_id="aggregate-1",
        authorized_input_refs=("metrics-ref",),
        input_schema={"metrics-ref": ("quarter", "segment", "revenue_musd")},
        output_contract_version="statebus.aggregation.v1",
        operation_catalog=("aggregate_grouped",),
        step_goal="aggregate each segment with sum, mean, minimum, maximum, and count",
        desired_output_fields=("segment", "sum", "mean", "min", "max", "count"),
    )

    assert program.operations[0].arguments == {"group_field": "segment", "value_field": "revenue_musd"}
    prompt, _ = _single_call(client)
    payload = parse_tagged_json(prompt, "sb-transform-program-v1")
    contract = payload["operation_contracts"]["aggregate_grouped"]
    assert contract["required"] == ["group_field", "value_field"]
    assert contract["fields"]["value_field"] == "authorized numeric column"


def test_adaptive_summarizer_receives_evidence_text_and_verified_artifact_rows() -> None:
    client = RecordingLLMClient({
        "claims": [{
            "claim_id": "revenue-series",
            "claim_text": "ACME revenue increased from 100 to 120 million USD.",
            "claim_type": "fact",
            "supporting_evidence_item_ids": ["evidence-1"],
            "supporting_artifact_ref_ids": ["artifact-1"],
            "citation_locators": ["section-1:0-77"],
            "numeric_fields": {"revenue_musd": 120.0},
            "uncertainty_note": "",
            "status": "ready",
        }],
        "status": "ready",
    })
    claim_set = RolePathRunner(llm_client=client).build_claim_set(
        task_id="task-1",
        claim_set_id="claims-1",
        verified_artifact_refs=("artifact-1",),
        task_goal="report the verified revenue change",
        evidence_items=({
            "id": "evidence-1",
            "locator": "section-1:0-77",
            "text": "ACME revenue was 100 in 2025Q4 and 120 in 2026Q1.",
        },),
        artifact_summaries=({
            "artifact_ref_id": "artifact-1",
            "status": "verified",
            "rows": [
                {"quarter": "2025Q4", "revenue_musd": 100.0},
                {"quarter": "2026Q1", "revenue_musd": 120.0},
            ],
        },),
    )

    assert claim_set.claims[0].numeric_fields["revenue_musd"] == 120.0
    prompt, schema = _single_call(client)
    assert "report the verified revenue change" in prompt
    assert "ACME revenue was 100 in 2025Q4 and 120 in 2026Q1." in prompt
    assert "supporting artifact's verified_rows" in prompt
    payload = parse_tagged_json(prompt, "sb-claim-set-v1")
    assert payload["reference_catalog"]["artifacts"][0]["artifact_ref_id"] == "artifact-1"
    assert payload["reference_catalog"]["artifacts"][0]["verified_rows"][1] == {
        "quarter": "2026Q1",
        "revenue_musd": 120.0,
    }
    assert payload["reference_catalog"]["artifacts"][0]["numeric_field_names"] == ["revenue_musd"]
    assert "Do not encode or convert period/date/string labels as numbers" in prompt
    assert "Create one compact claim per verified output row" in prompt
    assert payload["reference_catalog"]["evidence"][0]["evidence_id"] == "evidence-1"
    claim_properties = schema["properties"]["claims"]["items"]["properties"]
    assert claim_properties["supporting_evidence_item_ids"]["items"] == {"type": "string"}
    assert claim_properties["supporting_artifact_ref_ids"]["items"] == {"type": "string"}
    assert claim_properties["citation_locators"]["items"] == {"type": "string"}
    assert claim_properties["numeric_fields"] == {
        "type": "object",
        "additionalProperties": False,
        "properties": {"revenue_musd": {"type": "number"}},
    }
    _assert_vllm_073_xgrammar_compatible(schema)


def test_adaptive_summarizer_enforces_controller_claim_count() -> None:
    client = RecordingLLMClient({"claims": [], "status": "ready"})

    with pytest.raises(ValueError, match="adaptive_claim_count_mismatch:0:1"):
        RolePathRunner(llm_client=client).build_claim_set(
            task_id="task-1",
            claim_set_id="claims-1",
            verified_artifact_refs=("artifact-1",),
            evidence_items=({"id": "evidence-1", "locator": "section-1", "text": "revenue 120"},),
            artifact_summaries=({
                "artifact_ref_id": "artifact-1",
                "status": "verified",
                "rows": [{"revenue_musd": 120.0}],
            },),
            expected_claim_count=1,
        )

    prompt, _ = _single_call(client)
    payload = parse_tagged_json(prompt, "sb-claim-set-v1")
    assert payload["claim_contract"] == {
        "expected_claim_count": 1,
        "evidence_is_support_only": True,
        "one_claim_per_verified_row": True,
    }


def test_adaptive_summarizer_rejects_numeric_encoding_of_string_fields() -> None:
    client = RecordingLLMClient({
        "claims": [{
            "claim_id": "claim-1",
            "claim_text": "Revenue was 120 in 2026Q1.",
            "claim_type": "fact",
            "supporting_evidence_item_ids": ["evidence-1"],
            "supporting_artifact_ref_ids": ["artifact-1"],
            "citation_locators": ["section-1"],
            "numeric_fields": {"revenue_musd": 120.0, "quarter": 2026},
            "uncertainty_note": "",
            "status": "ready",
        }],
        "status": "ready",
    })

    with pytest.raises(ValueError, match="adaptive_claim_numeric_field_outside_contract"):
        RolePathRunner(llm_client=client).build_claim_set(
            task_id="task-1",
            claim_set_id="claims-1",
            verified_artifact_refs=("artifact-1",),
            evidence_items=({"id": "evidence-1", "locator": "section-1", "text": "revenue 120"},),
            artifact_summaries=({
                "artifact_ref_id": "artifact-1",
                "status": "verified",
                "rows": [{"quarter": "2026Q1", "revenue_musd": 120.0}],
            },),
            expected_claim_count=1,
        )


def test_adaptive_summarizer_citation_repair_can_only_change_typed_references() -> None:
    client = RecordingLLMClient({
        "repairs": [{
            "claim_id": "revenue-series",
            "supporting_evidence_item_ids": ["evidence-1"],
            "supporting_artifact_ref_ids": ["artifact-1"],
            "citation_locators": ["section-1:0-77"],
        }],
    })
    original = ClaimSet(
        claim_set_id="claims-1",
        task_id="task-1",
        claims=(Claim(
            claim_id="revenue-series",
            claim_text="ACME revenue increased from 100 to 120 million USD.",
            claim_type="fact",
            supporting_evidence_item_ids=("artifact-1",),
            supporting_artifact_ref_ids=(),
            citation_locators=("artifact_ref_id: artifact-1",),
            numeric_fields={"revenue_musd": 120.0},
        ),),
    )

    repaired = RolePathRunner(llm_client=client).repair_claim_citations(
        claim_set=original,
        verified_artifact_refs=("artifact-1",),
        evidence_items=({
            "id": "evidence-1",
            "locator": "section-1:0-77",
            "text": "ACME revenue was 120 in 2026Q1.",
        },),
        validation_errors=("invalid_evidence_reference:revenue-series:artifact-1",),
    )

    claim = repaired.claims[0]
    assert claim.claim_text == original.claims[0].claim_text
    assert claim.numeric_fields == {"revenue_musd": 120.0}
    assert claim.supporting_evidence_item_ids == ("evidence-1",)
    assert claim.supporting_artifact_ref_ids == ("artifact-1",)
    assert claim.citation_locators == ("section-1:0-77",)
    prompt, schema = _single_call(client)
    assert "citation-only repair" in prompt
    assert original.claims[0].claim_text not in prompt
    repair_properties = schema["properties"]["repairs"]["items"]["properties"]
    assert set(repair_properties) == {
        "claim_id",
        "supporting_evidence_item_ids",
        "supporting_artifact_ref_ids",
        "citation_locators",
    }
    _assert_vllm_073_xgrammar_compatible(schema)


def test_adaptive_retriever_rejects_values_outside_prompt_authority() -> None:
    client = RecordingLLMClient({
        "queries": ["ACME revenue"],
        "evidence_types": ["external_web"],
        "target_entities": [],
        "time_scope": "",
        "corpus_scope_ids": ["unapproved-corpus"],
        "max_candidates": 100,
    })
    with pytest.raises(ValueError, match="adaptive_evidence_type_outside_authority"):
        RolePathRunner(llm_client=client).build_evidence_request(
            task_id="task-1",
            step_id="retrieve",
            step_goal="find evidence",
            corpus_scope_ids=("local-long-doc",),
            evidence_types=("semantic_context", "table"),
        )


def test_adaptive_retriever_controller_injects_entity_and_time_scope() -> None:
    client = RecordingLLMClient({
        "queries": ["ACME revenue"],
        "evidence_types": ["semantic_context"],
        "target_entities": ["ACME", "unapproved entity"],
        "time_scope": "2024Q1 to 2026Q1",
        "corpus_scope_ids": ["local-long-doc"],
        "max_candidates": 8,
    })
    request = RolePathRunner(llm_client=client).build_evidence_request(
        task_id="task-1",
        step_id="retrieve",
        step_goal="find evidence",
        task_goal="find ACME revenue in the approved document",
        corpus_scope_ids=("local-long-doc",),
        evidence_types=("semantic_context", "table"),
        target_entities=("ACME",),
        time_scope="2025Q4 to 2026Q1",
    )

    assert request.target_entities == ("ACME",)
    assert request.time_scope == "2025Q4 to 2026Q1"
    prompt, schema = _single_call(client)
    assert "do not emit either field" in prompt
    assert "target_entities" not in schema["properties"]
    assert "time_scope" not in schema["properties"]


def test_adaptive_executor_rejects_model_output_contract_change() -> None:
    client = RecordingLLMClient({
        "input_artifact_refs": ["evidence-ref"],
        "operations": [{"op": "select", "arguments": {"columns": ["quarter"]}}],
        "output_contract_version": "statebus.unapproved.v1",
    })
    with pytest.raises(ValueError, match="adaptive_transform_output_contract_mismatch"):
        RolePathRunner(llm_client=client).build_transform_program(
            program_id="program-1",
            authorized_input_refs=("evidence-ref",),
            input_schema={"evidence-ref": ("quarter",)},
            output_contract_version="statebus.metric_series.v1",
            operation_catalog=("select",),
        )


def test_adaptive_summarizer_rejects_unknown_claim_type() -> None:
    client = RecordingLLMClient({
        "claims": [{
            "claim_id": "claim-1",
            "claim_text": "unsupported claim",
            "claim_type": "opinion",
            "supporting_evidence_item_ids": [],
            "supporting_artifact_ref_ids": [],
            "citation_locators": [],
            "numeric_fields": {},
            "uncertainty_note": "",
            "status": "ready",
        }],
        "status": "ready",
    })
    with pytest.raises(ValueError, match="adaptive_claim_type_outside_contract"):
        RolePathRunner(llm_client=client).build_claim_set(
            task_id="task-1",
            claim_set_id="claims-1",
            verified_artifact_refs=("artifact-1",),
            evidence_items=({"id": "evidence-1", "locator": "section-1", "text": "evidence"},),
        )
