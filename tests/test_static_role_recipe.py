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
from statebus.runtime.domain_packs import register_long_doc_analysis_capabilities
from statebus.runtime.driver import build_default_workflow
from statebus.runtime.static_role_recipe import (
    StaticRoleRecipe,
    StaticRoleRecipeCompiler,
    compile_static_role_recipe_plan,
    default_fixed_role_recipe,
)


def _context() -> tuple[CapabilityRegistry, AdaptiveTaskEnvelope]:
    registry = CapabilityRegistry()
    pack = register_long_doc_analysis_capabilities(registry)
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
            "retriever": (1, 1),
            "executor": (1, 1),
            "summarizer": (1, 1),
        },
        max_plan_steps=3,
        max_execution_runtime_ms=100_000,
    )
    return registry, envelope


def test_static_recipe_compiles_stable_plan_proposal() -> None:
    registry, envelope = _context()
    recipe = default_fixed_role_recipe()
    compiler = StaticRoleRecipeCompiler()

    first = compiler.compile(envelope.task_id, envelope, recipe)
    second = compiler.compile(envelope.task_id, envelope, recipe)

    assert first.canonical_payload() == second.canonical_payload()
    assert first.proposal_hash == second.proposal_hash
    assert tuple(step.role for step in first.steps) == (
        "retriever",
        "executor",
        "summarizer",
    )
    assert tuple(step.depends_on for step in first.steps) == tuple(
        step.depends_on for step in second.steps
    )
    assert first.steps[2].depends_on == ("retrieve", "execute")
    assert registry.contains(first.steps[0].capability_id)


def test_static_recipe_contains_no_provider_identity_or_execution_kind() -> None:
    registry, envelope = _context()
    proposal = StaticRoleRecipeCompiler().compile(
        envelope.task_id,
        envelope,
        default_fixed_role_recipe(),
    )
    payload_text = str(proposal.canonical_payload()).lower()
    recipe_text = str(default_fixed_role_recipe().canonical_payload()).lower()

    assert "execution_kind" not in payload_text
    assert "provider" not in payload_text
    assert "execution_kind" not in recipe_text
    assert "provider" not in recipe_text
    assert all(not hasattr(step, "provider") for step in proposal.steps)
    assert registry.digest


def test_static_recipe_rejects_physical_fields() -> None:
    _, envelope = _context()
    recipe_payload = default_fixed_role_recipe().canonical_payload()
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
        default_fixed_role_recipe(),
        available_input_refs={"ignored": "ignored"},
    )
    assert proposal.task_id == envelope.task_id


def test_same_recipe_and_contract_produce_stable_semantic_hash() -> None:
    registry, envelope = _context()
    recipe = default_fixed_role_recipe()
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
        default_fixed_role_recipe(),
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


def test_static_recipe_matches_legacy_post_plan_role_topology() -> None:
    registry, _ = _context()
    legacy_steps = tuple(
        step
        for step in build_default_workflow(step_id="execute", artifact_id="artifact")
        if step.role != "planner"
    )
    recipe_steps = default_fixed_role_recipe().steps
    legacy_roles = tuple(step.role for step in legacy_steps)
    recipe_roles = tuple(step.role for step in recipe_steps)

    def transitive_role_dependencies(steps: tuple[object, ...]) -> dict[str, tuple[str, ...]]:
        by_id = {str(getattr(step, "step_id")): step for step in steps}

        def ancestors(step_id: str) -> set[str]:
            result: set[str] = set()
            step = by_id[step_id]
            for dependency in getattr(step, "depends_on"):
                if dependency not in by_id:
                    continue
                result.add(str(getattr(by_id[dependency], "role")))
                result.update(ancestors(dependency))
            return result

        return {
            str(getattr(step, "role")): tuple(sorted(ancestors(str(getattr(step, "step_id")))))
            for step in steps
        }

    assert legacy_roles == ("retriever", "executor", "summarizer")
    assert recipe_roles == legacy_roles
    assert transitive_role_dependencies(legacy_steps) == transitive_role_dependencies(recipe_steps)
    assert transitive_role_dependencies(recipe_steps) == {
        "retriever": (),
        "executor": ("retriever",),
        "summarizer": ("executor", "retriever"),
    }
    assert tuple(registry.get(step.capability_id).owner_role for step in recipe_steps) == recipe_roles
    assert tuple(step.output_contract_version for step in recipe_steps) == (
        "statebus.evidence_pack.v2",
        "statebus.metric_series.v1",
        "statebus.cited_report.v1",
    )
