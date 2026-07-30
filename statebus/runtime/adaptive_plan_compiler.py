from __future__ import annotations

from dataclasses import replace

from statebus.contracts import PlanProposal, PlanStepProposal
from statebus.runtime.capability_registry import CapabilityRegistry


def compile_required_input_wiring(
    proposal: PlanProposal,
    registry: CapabilityRegistry,
) -> tuple[PlanProposal, tuple[str, ...]]:
    """Complete controller-owned edges needed by registered input contracts.

    The compiler does not choose capabilities, add semantic stages, or change
    goals. It only binds existing producers to consumers when a descriptor
    requires a typed input that the raw proposal omitted. Unresolved graphs
    remain unchanged for PlanPolicyValidator to reject.
    """
    original_steps = tuple(proposal.steps)
    index_by_id = {step.step_id: index for index, step in enumerate(original_steps)}
    step_by_id = {step.step_id: step for step in original_steps}
    normalized_fields: list[str] = []
    compiled_steps: list[PlanStepProposal] = []

    for consumer_index, step in enumerate(original_steps):
        step_normalized_fields: list[str] = []
        if not registry.contains(step.capability_id):
            compiled_steps.append(step)
            continue
        descriptor = registry.get(step.capability_id)
        dependencies = list(dict.fromkeys(step.depends_on))
        provided_kinds = set(step.input_ref_kinds)
        for dependency in dependencies:
            producer = step_by_id.get(dependency)
            if producer is not None and registry.contains(producer.capability_id):
                provided_kinds.update(registry.get(producer.capability_id).output_ref_kinds)

        for required_kind in descriptor.required_input_ref_kinds:
            if required_kind in provided_kinds:
                continue
            candidates = [
                producer
                for producer_index, producer in enumerate(original_steps)
                if producer_index < consumer_index
                and producer.step_id != step.step_id
                and registry.contains(producer.capability_id)
                and required_kind in registry.get(producer.capability_id).output_ref_kinds
            ]
            for producer in candidates:
                if producer.step_id not in dependencies:
                    dependencies.append(producer.step_id)
                    step_normalized_fields.append(
                        f"steps.{step.step_id}.depends_on.required_input_kind.{required_kind}"
                    )
            if candidates:
                provided_kinds.add(required_kind)

        known_dependencies = [item for item in dependencies if item in step_by_id]
        unknown_dependencies = [item for item in dependencies if item not in step_by_id]

        def dependency_order(dependency: str) -> tuple[int, int]:
            producer = step_by_id[dependency]
            producer_kinds = (
                set(registry.get(producer.capability_id).output_ref_kinds)
                if registry.contains(producer.capability_id)
                else set()
            )
            kind_rank = next(
                (
                    rank
                    for rank, required_kind in enumerate(descriptor.required_input_ref_kinds)
                    if required_kind in producer_kinds
                ),
                len(descriptor.required_input_ref_kinds),
            )
            return kind_rank, index_by_id[dependency]

        ordered_dependencies = sorted(known_dependencies, key=dependency_order) + unknown_dependencies
        if tuple(ordered_dependencies) != tuple(dependencies):
            step_normalized_fields.append(f"steps.{step.step_id}.depends_on.controller_order")
        normalized_fields.extend(step_normalized_fields)
        compiled_steps.append(replace(step, depends_on=tuple(ordered_dependencies)))

    if tuple(compiled_steps) == original_steps:
        return proposal, ()
    return replace(proposal, steps=tuple(compiled_steps)), tuple(dict.fromkeys(normalized_fields))
