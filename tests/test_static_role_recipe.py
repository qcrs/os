from __future__ import annotations

from dataclasses import replace

import pytest

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    PlanProvenanceError,
    RiskClass,
    WorkflowMode,
    semantic_plan_hash,
)
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.domain_packs import register_c2a_four_role_capabilities
from statebus.runtime.static_role_recipe import (
    StaticRoleRecipe,
    StaticRoleRecipeCompiler,
    compile_static_role_recipe_plan,
    default_fixed_role_recipe,
)


def _context() -> tuple[CapabilityRegistry, AdaptiveTaskEnvelope]:
    registry = CapabilityRegistry()
    pack = register_c2a_four_role_capabilities(registry)
    output_contracts = tuple(
        sorted({registry.get(capability_id).output_contract_version for capability_id in pack.capability_ids})
    )
    envelope = AdaptiveTaskEnvelope(
        task_id="recipe-task",
        canonical_task_spec_hash="sha256:recipe-contract",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id=pack.pack_id,
        allowed_capability_ids=pack.capability_ids,
        allowed_output_contracts=output_contracts,
        role_cardinality={
            "planner": (1, 1),
            "retriever": (1, 1),
            "executor": (1, 1),
            "summarizer": (1, 1),
        },
        max_plan_steps=4,
        max_execution_runtime_ms=100_000,
    )
    return registry, envelope


def test_static_recipe_compiles_stable_plan_proposal() -> None:
    registry, envelope = _context()
    recipe = default_fixed_role_recipe(retriever_capability_id="retrieve_table_evidence_v1")
    compiler = StaticRoleRecipeCompiler()

    first = compiler.compile(envelope.task_id, envelope, recipe)
    second = compiler.compile(envelope.task_id, envelope, recipe)

    assert first.canonical_payload() == second.canonical_payload()
    assert first.proposal_hash == second.proposal_hash
    assert tuple(step.role for step in first.steps) == ("planner", "retriever", "executor", "summarizer")
    assert tuple(step.depends_on for step in first.steps) == tuple(
        step.depends_on for step in second.steps
    )
    assert first.steps[1].depends_on == ("plan",)
    assert first.steps[2].depends_on == ("retrieve",)
    assert first.steps[3].depends_on == ("execute",)
    assert registry.contains(first.steps[0].capability_id)


def test_static_recipe_contains_no_provider_identity_or_execution_kind() -> None:
    registry, envelope = _context()
    proposal = StaticRoleRecipeCompiler().compile(
        envelope.task_id,
        envelope,
        default_fixed_role_recipe(retriever_capability_id="retrieve_table_evidence_v1"),
    )
    payload_text = str(proposal.canonical_payload()).lower()
    recipe_text = str(default_fixed_role_recipe(retriever_capability_id="retrieve_table_evidence_v1").canonical_payload()).lower()

    assert "execution_kind" not in payload_text
    assert "provider" not in payload_text
    assert "execution_kind" not in recipe_text
    assert "provider" not in recipe_text
    assert all(not hasattr(step, "provider") for step in proposal.steps)
    assert registry.digest


def test_static_recipe_rejects_physical_fields() -> None:
    _, envelope = _context()
    recipe_payload = default_fixed_role_recipe(retriever_capability_id="retrieve_table_evidence_v1").canonical_payload()
    recipe_payload["provider_id"] = "physical-provider-1"

    with pytest.raises(PlanProvenanceError, match="physical_provider_field_forbidden"):
        StaticRoleRecipe.from_mapping(recipe_payload)

    step_payload = dict(recipe_payload)
    step_payload.pop("provider_id")
    step_payload["steps"] = [dict(item) for item in step_payload["steps"]]
    step_payload["steps"][0]["execution_kind"] = "runtime_builtin"
    with pytest.raises(PlanProvenanceError, match="physical_provider_field_forbidden"):
        StaticRoleRecipe.from_mapping(step_payload)

    # The recipe compiler remains a pure control-plane operation and does not
    # need input materialization to produce its untrusted proposal.
    proposal = StaticRoleRecipeCompiler().compile(
        envelope.task_id,
        envelope,
        default_fixed_role_recipe(retriever_capability_id="retrieve_table_evidence_v1"),
        available_input_refs={"ignored": "ignored"},
    )
    assert proposal.task_id == envelope.task_id


def test_same_recipe_and_contract_produce_stable_semantic_hash() -> None:
    registry, envelope = _context()
    recipe = default_fixed_role_recipe(retriever_capability_id="retrieve_table_evidence_v1")
    first = StaticRoleRecipeCompiler().compile(envelope.task_id, envelope, recipe)
    second = StaticRoleRecipeCompiler().compile(envelope.task_id, envelope, recipe)

    assert semantic_plan_hash(
        first,
        runtime_task_id=envelope.task_id,
        task_contract_hash=envelope.canonical_task_spec_hash,
    ) == semantic_plan_hash(
        second,
        runtime_task_id=envelope.task_id,
        task_contract_hash=envelope.canonical_task_spec_hash,
    )
    result = compile_static_role_recipe_plan(
        runtime_task_id=envelope.task_id,
        envelope=envelope,
        recipe=recipe,
        registry=registry,
    )
    assert result.approved_plan_bundle.verify_hash_links()


def test_planner_telemetry_is_not_part_of_semantic_plan_hash() -> None:
    _, envelope = _context()
    proposal = StaticRoleRecipeCompiler().compile(
        envelope.task_id,
        envelope,
        default_fixed_role_recipe(retriever_capability_id="retrieve_table_evidence_v1"),
    )
    telemetry_variant = replace(
        proposal,
        proposal_id="planner-retry-42",
        planner_notes="different sampled explanation",
        model_id="another-planner",
        prompt_tokens=123,
        completion_tokens=45,
        latency_ms=987.5,
        raw_output_hash="different-raw-output",
    )

    assert proposal.proposal_hash != telemetry_variant.proposal_hash
    assert semantic_plan_hash(
        proposal,
        runtime_task_id=envelope.task_id,
        task_contract_hash=envelope.canonical_task_spec_hash,
    ) == semantic_plan_hash(
        telemetry_variant,
        runtime_task_id=envelope.task_id,
        task_contract_hash=envelope.canonical_task_spec_hash,
    )


def test_static_recipe_matches_c2a_four_role_topology() -> None:
    registry, _ = _context()
    recipe_steps = default_fixed_role_recipe(retriever_capability_id="retrieve_table_evidence_v1").steps
    assert tuple(step.role for step in recipe_steps) == ("planner", "retriever", "executor", "summarizer")
    assert tuple(step.step_id for step in recipe_steps) == ("plan", "retrieve", "execute", "summarize")
    assert tuple(step.depends_on for step in recipe_steps) == ((), ("plan",), ("retrieve",), ("execute",))
    assert tuple(registry.get(step.capability_id).owner_role for step in recipe_steps) == tuple(step.role for step in recipe_steps)
    assert tuple(step.output_contract_version for step in recipe_steps) == (
        "statebus.planner_handoff.v2", "statebus.evidence_pack.v2", "statebus.metric_series.v1", "statebus.cited_report.v1",
    )


def test_static_recipe_final_contract_matches_summarizer_contract() -> None:
    recipe = default_fixed_role_recipe()
    recipe.validate_fixed_topology()
    assert recipe.final_output_contract_version == recipe.steps[-1].output_contract_version

    mismatched = replace(recipe, final_output_contract="statebus.metric_series.v1")
    with pytest.raises(PlanProvenanceError, match="fixed_recipe_final_output_contract_mismatch"):
        mismatched.validate_fixed_topology()
