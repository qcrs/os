"""Static, provider-neutral Fixed plan source.

The recipe compiler is intentionally a control-plane component.  It creates a
``PlanProposal`` from declarative logical steps and never invokes a role,
provider, workspace, attempt, or capability grant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, Mapping

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    ApprovedPlan,
    ApprovedPlanBundle,
    PlanNormalizationReceipt,
    PlanPolicyReport,
    PlanProposal,
    PlanProvenanceError,
    PlanStepProposal,
    RuntimeIdentity,
    STATIC_ROLE_RECIPE_SCHEMA_VERSION,
)
from statebus.utils import sha256_digest


_PHYSICAL_KEYS = {
    "execution_kind",
    "provider",
    "provider_id",
    "provider_name",
    "execution_provider",
    "handler",
    "handler_id",
    "model_id",
}


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanProvenanceError(f"{field_name}_required")
    return value.strip()


def _safe_component(value: str, field_name: str) -> str:
    value = _required_text(value, field_name)
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise PlanProvenanceError(f"{field_name}_invalid_component")
    path = PurePath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PlanProvenanceError(f"{field_name}_invalid_component")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PlanProvenanceError(f"{field_name}_invalid_component")
    return value


def _reject_physical_keys(value: object, *, path: str = "recipe") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in _PHYSICAL_KEYS:
                raise PlanProvenanceError(f"physical_provider_field_forbidden:{path}.{key}")
            _reject_physical_keys(child, path=f"{path}.{key}")
    elif isinstance(value, (tuple, list)):
        for index, child in enumerate(value):
            _reject_physical_keys(child, path=f"{path}[{index}]")


@dataclass(frozen=True)
class StaticRoleRecipeStep:
    """One logical step in a static role recipe."""

    step_id: str
    role: str
    capability_id: str
    goal: str
    depends_on: tuple[str, ...] = ()
    input_ref_ids: tuple[str, ...] = ()
    input_ref_kinds: tuple[str, ...] = ()
    output_contract_version: str = ""
    completion_criteria: dict[str, object] = field(default_factory=dict)
    on_failure: str = "fail"
    required_input_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _required_text(self.step_id, "step_id"))
        object.__setattr__(self, "role", _required_text(self.role, "role").lower())
        object.__setattr__(self, "capability_id", _required_text(self.capability_id, "capability_id"))
        object.__setattr__(self, "goal", _required_text(self.goal, "goal"))
        object.__setattr__(
            self,
            "output_contract_version",
            _required_text(self.output_contract_version, "output_contract_version"),
        )
        object.__setattr__(self, "depends_on", tuple(str(item).strip() for item in self.depends_on))
        object.__setattr__(self, "input_ref_ids", tuple(str(item) for item in self.input_ref_ids))
        object.__setattr__(self, "input_ref_kinds", tuple(str(item) for item in self.input_ref_kinds))
        object.__setattr__(self, "required_input_fields", tuple(str(item) for item in self.required_input_fields))
        object.__setattr__(self, "completion_criteria", dict(self.completion_criteria))
        object.__setattr__(self, "on_failure", _required_text(self.on_failure, "on_failure"))
        _reject_physical_keys(self.completion_criteria, path=f"steps.{self.step_id}.completion_criteria")

    @classmethod
    def from_plan_step(cls, step: PlanStepProposal) -> "StaticRoleRecipeStep":
        if not isinstance(step, PlanStepProposal):
            raise PlanProvenanceError("plan_step_proposal_required")
        return cls(
            step_id=step.step_id,
            role=step.role,
            capability_id=step.capability_id,
            goal=step.goal,
            depends_on=step.depends_on,
            input_ref_ids=step.input_ref_ids,
            input_ref_kinds=step.input_ref_kinds,
            output_contract_version=step.output_contract_version,
            completion_criteria=step.completion_criteria,
            on_failure=step.on_failure,
            required_input_fields=step.required_input_fields,
        )

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "StaticRoleRecipeStep":
        if not isinstance(mapping, Mapping):
            raise PlanProvenanceError("recipe_step_mapping_required")
        _reject_physical_keys(mapping, path="step")
        return cls(
            step_id=str(mapping.get("step_id", mapping.get("id", ""))),
            role=str(mapping.get("role", "")),
            capability_id=str(mapping.get("capability_id", mapping.get("capability", ""))),
            goal=str(mapping.get("goal", "")),
            depends_on=tuple(mapping.get("depends_on", ())),
            input_ref_ids=tuple(mapping.get("input_ref_ids", ())),
            input_ref_kinds=tuple(mapping.get("input_ref_kinds", ())),
            output_contract_version=str(
                mapping.get("output_contract_version", mapping.get("output_contract", ""))
            ),
            completion_criteria=dict(mapping.get("completion_criteria", {})),
            on_failure=str(mapping.get("on_failure", "fail")),
            required_input_fields=tuple(mapping.get("required_input_fields", ())),
        )

    def to_plan_step(self) -> PlanStepProposal:
        return PlanStepProposal(
            step_id=self.step_id,
            role=self.role,
            capability_id=self.capability_id,
            goal=self.goal,
            depends_on=self.depends_on,
            input_ref_ids=self.input_ref_ids,
            input_ref_kinds=self.input_ref_kinds,
            output_contract_version=self.output_contract_version,
            completion_criteria=dict(self.completion_criteria),
            on_failure=self.on_failure,
            required_input_fields=self.required_input_fields,
        )

    @property
    def capability(self) -> str:
        return self.capability_id

    @property
    def output_contract(self) -> str:
        return self.output_contract_version

    def canonical_payload(self) -> dict[str, object]:
        # Deliberately no ExecutionKind/provider field: recipes describe only
        # logical capability and contract requirements.
        return {
            "step_id": self.step_id,
            "role": self.role,
            "capability_id": self.capability_id,
            "goal": self.goal,
            "depends_on": list(self.depends_on),
            "input_ref_ids": list(self.input_ref_ids),
            "input_ref_kinds": list(self.input_ref_kinds),
            "output_contract_version": self.output_contract_version,
            "completion_criteria": dict(sorted(self.completion_criteria.items())),
            "on_failure": self.on_failure,
            "required_input_fields": list(self.required_input_fields),
        }


@dataclass(frozen=True)
class StaticRoleRecipe:
    """Declarative fixed topology used by ``StaticRoleRecipeCompiler``."""

    recipe_id: str
    recipe_version: str
    steps: tuple[StaticRoleRecipeStep, ...]
    final_output_contract: str
    requested_memory_policy: str = "none"
    schema_version: str = STATIC_ROLE_RECIPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipe_id", _required_text(self.recipe_id, "recipe_id"))
        object.__setattr__(
            self,
            "recipe_version",
            _required_text(self.recipe_version, "recipe_version"),
        )
        object.__setattr__(
            self,
            "final_output_contract",
            _required_text(self.final_output_contract, "final_output_contract"),
        )
        object.__setattr__(
            self,
            "requested_memory_policy",
            _required_text(self.requested_memory_policy, "requested_memory_policy"),
        )
        object.__setattr__(
            self,
            "steps",
            tuple(
                item
                if isinstance(item, StaticRoleRecipeStep)
                else StaticRoleRecipeStep.from_mapping(item)
                for item in self.steps
            ),
        )
        object.__setattr__(self, "schema_version", _required_text(self.schema_version, "schema_version"))
        _reject_physical_keys(self.canonical_payload(), path="recipe")

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "StaticRoleRecipe":
        if not isinstance(mapping, Mapping):
            raise PlanProvenanceError("recipe_mapping_required")
        _reject_physical_keys(mapping)
        steps = mapping.get("steps", ())
        if not isinstance(steps, (tuple, list)):
            raise PlanProvenanceError("recipe_steps_must_be_sequence")
        return cls(
            recipe_id=str(mapping.get("recipe_id", mapping.get("id", ""))),
            recipe_version=str(mapping.get("recipe_version", mapping.get("version", ""))),
            steps=tuple(
                item if isinstance(item, StaticRoleRecipeStep) else StaticRoleRecipeStep.from_mapping(item)
                for item in steps
            ),
            final_output_contract=str(
                mapping.get("final_output_contract", mapping.get("final_output_contract_version", ""))
            ),
            requested_memory_policy=str(mapping.get("requested_memory_policy", "none")),
            schema_version=str(mapping.get("schema_version", STATIC_ROLE_RECIPE_SCHEMA_VERSION)),
        )

    @property
    def recipe_hash(self) -> str:
        return sha256_digest(self.canonical_payload())

    @property
    def final_output_contract_version(self) -> str:
        return self.final_output_contract

    def canonical_payload(self) -> dict[str, object]:
        return {
            "recipe_id": self.recipe_id,
            "recipe_version": self.recipe_version,
            "steps": [step.canonical_payload() for step in self.steps],
            "final_output_contract": self.final_output_contract,
            "requested_memory_policy": self.requested_memory_policy,
            "schema_version": self.schema_version,
        }

    def validate_fixed_topology(self) -> None:
        """Enforce the first MRR-02 fixed topology without approving it."""

        if len(self.steps) != 3:
            raise PlanProvenanceError("fixed_recipe_requires_three_steps")
        step_ids = tuple(step.step_id for step in self.steps)
        if len(set(step_ids)) != len(step_ids):
            raise PlanProvenanceError("fixed_recipe_duplicate_step_id")
        roles = tuple(step.role for step in self.steps)
        if roles != ("retriever", "executor", "summarizer"):
            raise PlanProvenanceError("fixed_recipe_role_topology_mismatch")
        if self.steps[0].depends_on:
            raise PlanProvenanceError("fixed_recipe_retriever_must_be_root")
        if self.steps[1].depends_on != (self.steps[0].step_id,):
            raise PlanProvenanceError("fixed_recipe_executor_dependency_mismatch")
        if set(self.steps[2].depends_on) != {self.steps[0].step_id, self.steps[1].step_id}:
            raise PlanProvenanceError("fixed_recipe_summarizer_dependency_mismatch")
        if self.steps[1].role != "executor" or self.steps[2].role != "summarizer":
            raise PlanProvenanceError("fixed_recipe_role_topology_mismatch")


def default_fixed_role_recipe(
    *,
    recipe_id: str = "fixed-retriever-executor-summarizer",
    recipe_version: str = "v1",
    retriever_capability_id: str = "retrieve_semantic_evidence_v1",
    executor_capability_id: str = "extract_metric_series_v1",
    summarizer_capability_id: str = "compose_cited_report_v1",
    evidence_contract: str = "statebus.evidence_pack.v2",
    executor_contract: str = "statebus.metric_series.v1",
    final_output_contract: str = "statebus.cited_report.v1",
    requested_memory_policy: str = "none",
) -> StaticRoleRecipe:
    """Build the representative deterministic three-role recipe."""

    return StaticRoleRecipe(
        recipe_id=recipe_id,
        recipe_version=recipe_version,
        steps=(
            StaticRoleRecipeStep(
                step_id="retrieve",
                role="retriever",
                capability_id=retriever_capability_id,
                goal="retrieve registered evidence",
                output_contract_version=evidence_contract,
                completion_criteria={"min_locator_count": 1},
                on_failure="request_replan",
            ),
            StaticRoleRecipeStep(
                step_id="execute",
                role="executor",
                capability_id=executor_capability_id,
                goal="execute the approved metric transformation",
                depends_on=("retrieve",),
                input_ref_ids=("retrieve-output",),
                input_ref_kinds=("canonical_evidence_pack",),
                output_contract_version=executor_contract,
                completion_criteria={"min_rows": 1},
                on_failure="fallback_deterministic",
            ),
            StaticRoleRecipeStep(
                step_id="summarize",
                role="summarizer",
                capability_id=summarizer_capability_id,
                goal="compose the final cited report",
                depends_on=("retrieve", "execute"),
                input_ref_ids=("retrieve-output", "execute-output"),
                input_ref_kinds=("canonical_evidence_pack", "execution_artifact"),
                output_contract_version=final_output_contract,
                completion_criteria={"min_locator_count": 1},
            ),
        ),
        final_output_contract=final_output_contract,
        requested_memory_policy=requested_memory_policy,
    )


# Friendly aliases for callers and tests that use the terminology from the
# design document.
representative_fixed_role_recipe = default_fixed_role_recipe
build_default_static_role_recipe = default_fixed_role_recipe


@dataclass(frozen=True)
class StaticRoleRecipeCompiler:
    """Compile a static recipe into an untrusted, deterministic plan proposal."""

    compiler_id: str = "statebus.runtime.static_role_recipe"
    compiler_version: str = "v1"
    require_fixed_topology: bool = True

    def compile(
        self,
        runtime_task_id: str,
        envelope: AdaptiveTaskEnvelope,
        recipe: StaticRoleRecipe | Mapping[str, Any],
        available_input_refs: Mapping[str, str] | None = None,
    ) -> PlanProposal:
        del available_input_refs  # Input availability is a policy concern.
        if not isinstance(envelope, AdaptiveTaskEnvelope):
            raise PlanProvenanceError("adaptive_task_envelope_required")
        runtime_task_id = _safe_component(runtime_task_id, "runtime_task_id")
        if envelope.task_id != runtime_task_id:
            raise PlanProvenanceError("runtime_task_id_envelope_mismatch")
        resolved_recipe = (
            recipe if isinstance(recipe, StaticRoleRecipe) else StaticRoleRecipe.from_mapping(recipe)
        )
        if self.require_fixed_topology:
            resolved_recipe.validate_fixed_topology()
        if resolved_recipe.schema_version != STATIC_ROLE_RECIPE_SCHEMA_VERSION:
            raise PlanProvenanceError("unsupported_static_role_recipe_schema")

        # Proposal identity is deterministic and contains no run/session or
        # provider data.  PlanPolicy remains the sole approval boundary.
        proposal_id = (
            f"static-{resolved_recipe.recipe_id}-{resolved_recipe.recipe_version}-{runtime_task_id}"
        )
        return PlanProposal(
            proposal_id=proposal_id,
            task_id=runtime_task_id,
            steps=tuple(step.to_plan_step() for step in resolved_recipe.steps),
            final_output_contract_version=resolved_recipe.final_output_contract,
            requested_memory_policy=resolved_recipe.requested_memory_policy,
            planner_notes=(
                f"static role recipe {resolved_recipe.recipe_id}@{resolved_recipe.recipe_version}"
            ),
            model_id=self.compiler_id,
            raw_output_hash=resolved_recipe.recipe_hash,
        )

    # Alternate spelling used by some control-plane callers.
    compile_plan = compile
    compile_proposal = compile


FixedRoleRecipeCompiler = StaticRoleRecipeCompiler
RoleRecipe = StaticRoleRecipe
FixedRoleRecipe = StaticRoleRecipe
RoleRecipeStep = StaticRoleRecipeStep


@dataclass(frozen=True)
class StaticPlanCompilationResult:
    """All control-plane products emitted by a static recipe compilation."""

    proposal: PlanProposal
    normalized_proposal: PlanProposal
    normalization_receipt: PlanNormalizationReceipt
    policy_report: PlanPolicyReport
    approved_plan: ApprovedPlan
    approved_plan_bundle: ApprovedPlanBundle

    @property
    def bundle(self) -> ApprovedPlanBundle:
        return self.approved_plan_bundle


def compile_static_role_recipe_plan(
    *,
    runtime_task_id: str,
    envelope: AdaptiveTaskEnvelope,
    recipe: StaticRoleRecipe | Mapping[str, Any],
    registry: Any,
    available_input_refs: Mapping[str, str] | None = None,
    runtime_identity: RuntimeIdentity | None = None,
) -> StaticPlanCompilationResult:
    """Compile, mechanically normalize, authorize, and bundle a static plan.

    This helper stops at ``ApprovedPlanBundle``.  It deliberately has no
    runtime/dispatcher argument and therefore cannot execute a role or issue a
    grant as an accidental side effect.
    """

    from statebus.runtime.adaptive_plan_compiler import compile_required_input_wiring
    from statebus.runtime.plan_policy import PlanPolicyValidator

    if runtime_identity is not None:
        if not isinstance(runtime_identity, RuntimeIdentity):
            raise PlanProvenanceError("runtime_identity_type_required")
        if runtime_identity.runtime_task_id != runtime_task_id:
            raise PlanProvenanceError("runtime_task_id_identity_mismatch")
        if runtime_identity.task_contract.contract_hash != envelope.canonical_task_spec_hash:
            raise PlanProvenanceError("task_contract_hash_identity_mismatch")

    proposal = StaticRoleRecipeCompiler().compile(
        runtime_task_id,
        envelope,
        recipe,
        available_input_refs,
    )
    normalized, fields = compile_required_input_wiring(proposal, registry)
    receipt = PlanNormalizationReceipt.from_proposals(
        proposal,
        normalized,
        changed_fields=fields,
        runtime_task_id=runtime_task_id,
        task_contract_hash=envelope.canonical_task_spec_hash,
        task_identity=runtime_identity,
        registry=registry,
    )
    outcome = PlanPolicyValidator(
        registry,
        allow_llm_python=envelope.allow_llm_python,
    ).validate(
        normalized,
        envelope,
        available_input_refs=dict(available_input_refs or {}),
    )
    if outcome.approved_plan is None:
        raise PlanProvenanceError(
            "static_recipe_policy_rejected:"
            + ",".join(issue.error_code for issue in outcome.report.issues)
        )
    resolved_recipe = (
        recipe
        if isinstance(recipe, StaticRoleRecipe)
        else StaticRoleRecipe.from_mapping(recipe)
    )
    bundle = ApprovedPlanBundle.from_parts(
        runtime_task_id=runtime_task_id,
        task_contract_hash=envelope.canonical_task_spec_hash,
        source_proposal=proposal,
        effective_proposal=normalized,
        normalization_receipt=receipt,
        plan_policy_report=outcome.report,
        approved_plan=outcome.approved_plan,
        logical_capability_registry_digest=registry.digest,
        recipe_id=resolved_recipe.recipe_id,
        recipe_version=resolved_recipe.recipe_version,
    )
    return StaticPlanCompilationResult(
        proposal=proposal,
        normalized_proposal=normalized,
        normalization_receipt=receipt,
        policy_report=outcome.report,
        approved_plan=outcome.approved_plan,
        approved_plan_bundle=bundle,
    )


compile_static_recipe_plan = compile_static_role_recipe_plan


def compile_static_role_recipe(
    runtime_task_id: str,
    envelope: AdaptiveTaskEnvelope,
    recipe: StaticRoleRecipe | Mapping[str, Any],
    available_input_refs: Mapping[str, str] | None = None,
) -> PlanProposal:
    return StaticRoleRecipeCompiler().compile(
        runtime_task_id,
        envelope,
        recipe,
        available_input_refs,
    )


__all__ = [
    "FixedRoleRecipeCompiler",
    "FixedRoleRecipe",
    "RoleRecipe",
    "RoleRecipeStep",
    "StaticRoleRecipe",
    "StaticRoleRecipeCompiler",
    "StaticRoleRecipeStep",
    "StaticPlanCompilationResult",
    "build_default_static_role_recipe",
    "compile_static_role_recipe",
    "compile_static_recipe_plan",
    "compile_static_role_recipe_plan",
    "default_fixed_role_recipe",
    "representative_fixed_role_recipe",
]
