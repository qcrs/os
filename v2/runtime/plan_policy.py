from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from v2.contracts import (
    AdaptiveTaskEnvelope,
    ApprovedPlan,
    ExecutionKind,
    PlanPolicyIssue,
    PlanPolicyReport,
    PlanPolicyStatus,
    PlanProposal,
    PlanStepProposal,
    RiskClass,
)
from v2.runtime.capability_registry import CapabilityRegistry
from v2.utils import sha256_digest


_ALLOWED_COMPLETION_KEYS = {
    "min_locator_count",
    "min_rows",
    "required_evidence_types",
    "required_fields",
    "max_conflicts",
}
_ALLOWED_FAILURE_ACTIONS = {"fail", "request_replan", "fallback_deterministic"}
_ALLOWED_MEMORY_POLICIES = {"none", "assist", "artifact", "strategy"}
_RISK_RANK = {RiskClass.READ_ONLY: 0, RiskClass.WORKSPACE_WRITE: 1, RiskClass.BOUNDED_CODE: 2}
_PROMPT_ESCAPE_MARKERS = (
    "ignore previous", "ignore all previous", "<system", "```", "subprocess", "os.system",
    "http://", "https://", "\\x00",
)


@dataclass(frozen=True)
class PlanPolicyOutcome:
    report: PlanPolicyReport
    approved_plan: ApprovedPlan | None
    repair_used: bool = False
    fallback_used: bool = False


class PlanPolicyValidator:
    def __init__(self, registry: CapabilityRegistry, *, allow_llm_python: bool = False) -> None:
        self.registry = registry
        self.allow_llm_python = allow_llm_python

    def validate(
        self,
        proposal: PlanProposal,
        envelope: AdaptiveTaskEnvelope,
        *,
        available_input_refs: dict[str, str] | None = None,
    ) -> PlanPolicyOutcome:
        available_input_refs = available_input_refs or {}
        issues: list[PlanPolicyIssue] = []
        normalized_fields: list[str] = []
        if proposal.schema_version != "statebus.plan_proposal.v1":
            issues.append(self._issue("invalid_schema_version", field_path="schema_version", value=proposal.schema_version))
        if proposal.task_id != envelope.task_id:
            issues.append(self._issue("task_id_mismatch", field_path="task_id", value=proposal.task_id))
        if not 2 <= len(proposal.steps) <= envelope.max_plan_steps:
            issues.append(self._issue("step_budget_exceeded", field_path="steps", value=str(len(proposal.steps))))
        if proposal.final_output_contract_version not in envelope.allowed_output_contracts:
            issues.append(self._issue("output_contract_not_allowed", field_path="final_output_contract_version", value=proposal.final_output_contract_version))
        if (
            proposal.requested_memory_policy not in _ALLOWED_MEMORY_POLICIES
            or proposal.requested_memory_policy not in envelope.allowed_memory_policies
        ):
            issues.append(self._issue("memory_policy_not_allowed", field_path="requested_memory_policy", value=proposal.requested_memory_policy))
        if proposal.prompt_tokens > envelope.max_planner_prompt_tokens:
            issues.append(self._issue("planner_prompt_budget_exceeded", field_path="prompt_tokens", value=str(proposal.prompt_tokens)))
        if proposal.completion_tokens > envelope.max_planner_completion_tokens:
            issues.append(self._issue("planner_completion_budget_exceeded", field_path="completion_tokens", value=str(proposal.completion_tokens)))

        step_ids = [step.step_id for step in proposal.steps]
        if len(set(step_ids)) != len(step_ids) or any(not step_id for step_id in step_ids):
            issues.append(self._issue("duplicate_or_empty_step_id", field_path="steps"))
        step_by_id = {step.step_id: step for step in proposal.steps}
        role_counts = {
            role: sum(step.role == role for step in proposal.steps)
            for role in envelope.role_cardinality
        }
        for role, bounds in envelope.role_cardinality.items():
            minimum, maximum = bounds
            if minimum < 0 or maximum < minimum:
                issues.append(self._issue(
                    "invalid_role_cardinality_contract",
                    field_path=f"role_cardinality.{role}",
                    value=f"{minimum}:{maximum}",
                ))
            elif not minimum <= role_counts[role] <= maximum:
                issues.append(self._issue(
                    "role_cardinality_violation",
                    field_path=f"steps.role.{role}",
                    value=str(role_counts[role]),
                ))
        for step in proposal.steps:
            self._validate_step(step, envelope, available_input_refs, step_by_id, issues)
        if not issues and self._has_cycle(step_by_id):
            issues.append(self._issue("dependency_cycle", field_path="steps.depends_on"))
        if not issues and self._max_depth(step_by_id) > envelope.max_dependency_depth:
            issues.append(self._issue("dependency_depth_exceeded", field_path="steps.depends_on"))
        if not issues:
            self._validate_executor_stage_contracts(proposal, step_by_id, issues)
        if not issues:
            self._validate_plan_budgets_and_edges(proposal, envelope, step_by_id, issues)

        if issues:
            report = PlanPolicyReport(
                proposal_id=proposal.proposal_id,
                status=PlanPolicyStatus.REJECTED,
                issues=tuple(issues),
                policy_version=envelope.policy_version,
            )
            return PlanPolicyOutcome(report=report, approved_plan=None)
        normalized_steps = tuple(self._normalize_step(step, normalized_fields) for step in proposal.steps)
        status = PlanPolicyStatus.NORMALIZED if normalized_fields else PlanPolicyStatus.APPROVED
        report = PlanPolicyReport(
            proposal_id=proposal.proposal_id,
            status=status,
            normalized_fields=tuple(normalized_fields),
            policy_version=envelope.policy_version,
        )
        approved = ApprovedPlan(
            approved_plan_id=f"approved-{proposal.proposal_id}",
            task_id=proposal.task_id,
            source_proposal_id=proposal.proposal_id,
            steps=normalized_steps,
            final_output_contract_version=proposal.final_output_contract_version,
            plan_policy_report_hash=report.report_hash,
            capability_registry_digest=self.registry.digest,
            total_attempt_budget=envelope.max_total_attempts,
            requested_memory_policy=proposal.requested_memory_policy,
            normalized_fields=tuple(normalized_fields),
        )
        return PlanPolicyOutcome(report=report, approved_plan=approved)

    def validate_with_single_repair(
        self,
        proposal: PlanProposal,
        envelope: AdaptiveTaskEnvelope,
        *,
        repair: Callable[[PlanPolicyReport], PlanProposal | None] | None = None,
        fallback_proposal: PlanProposal | None = None,
        available_input_refs: dict[str, str] | None = None,
    ) -> PlanPolicyOutcome:
        """Allow one schema-only repair before a registered deterministic fallback.

        The repair result goes through the exact same policy gates, so it cannot
        expand capabilities, references, or budgets merely by being labelled a repair.
        """
        initial = self.validate(proposal, envelope, available_input_refs=available_input_refs)
        if initial.approved_plan is not None:
            return initial
        if repair is not None:
            repaired = repair(initial.report)
            if repaired is not None and self._is_schema_only_repair(proposal, repaired):
                repaired_outcome = self.validate(repaired, envelope, available_input_refs=available_input_refs)
                if repaired_outcome.approved_plan is not None:
                    repaired_report = replace(
                        repaired_outcome.report,
                        normalized_fields=tuple(sorted(set(repaired_outcome.report.normalized_fields + ("repair_used",)))),
                    )
                    repaired_plan = replace(
                        repaired_outcome.approved_plan,
                        plan_policy_report_hash=repaired_report.report_hash,
                    )
                    return PlanPolicyOutcome(
                        report=repaired_report,
                        approved_plan=repaired_plan,
                        repair_used=True,
                    )
        if fallback_proposal is not None:
            fallback = self.fallback(
                proposal,
                envelope,
                fallback_proposal,
                available_input_refs=available_input_refs,
            )
            return replace(fallback, fallback_used=fallback.approved_plan is not None)
        return initial

    @staticmethod
    def _is_schema_only_repair(original: PlanProposal, repaired: PlanProposal) -> bool:
        """Repairs may fix encoding/schema fields, never change approved authority.

        This deliberately treats the plan graph, its capability surface, and all
        budget-bearing values as semantic. A different graph must use the
        deterministic fallback or a separately authorized replan instead.
        """
        if (
            original.task_id != repaired.task_id
            or original.final_output_contract_version != repaired.final_output_contract_version
            or original.requested_memory_policy != repaired.requested_memory_policy
            or original.prompt_tokens != repaired.prompt_tokens
            or original.completion_tokens != repaired.completion_tokens
            or len(original.steps) != len(repaired.steps)
        ):
            return False
        original_steps = tuple(
            (
                step.step_id.strip(), step.role.strip().lower(), step.capability_id.strip(), step.goal.strip(),
                tuple(step.depends_on), tuple(step.input_ref_ids), tuple(step.input_ref_kinds),
                step.output_contract_version.strip(), dict(sorted(step.completion_criteria.items())), step.on_failure,
                tuple(step.required_input_fields),
            )
            for step in original.steps
        )
        repaired_steps = tuple(
            (
                step.step_id.strip(), step.role.strip().lower(), step.capability_id.strip(), step.goal.strip(),
                tuple(step.depends_on), tuple(step.input_ref_ids), tuple(step.input_ref_kinds),
                step.output_contract_version.strip(), dict(sorted(step.completion_criteria.items())), step.on_failure,
                tuple(step.required_input_fields),
            )
            for step in repaired.steps
        )
        return original_steps == repaired_steps

    def fallback(
        self,
        proposal: PlanProposal,
        envelope: AdaptiveTaskEnvelope,
        fallback_proposal: PlanProposal,
        *,
        available_input_refs: dict[str, str] | None = None,
    ) -> PlanPolicyOutcome:
        fallback = self.validate(fallback_proposal, envelope, available_input_refs=available_input_refs)
        if fallback.approved_plan is None:
            return fallback
        report = PlanPolicyReport(
            proposal_id=proposal.proposal_id,
            status=PlanPolicyStatus.FALLBACK_FIXED_PLAN,
            issues=(self._issue("fallback_after_rejection", value=proposal.proposal_hash),),
            policy_version=envelope.policy_version,
        )
        approved = ApprovedPlan(
            approved_plan_id=fallback.approved_plan.approved_plan_id,
            task_id=fallback.approved_plan.task_id,
            source_proposal_id=proposal.proposal_id,
            steps=fallback.approved_plan.steps,
            final_output_contract_version=fallback.approved_plan.final_output_contract_version,
            plan_policy_report_hash=report.report_hash,
            capability_registry_digest=fallback.approved_plan.capability_registry_digest,
            total_attempt_budget=fallback.approved_plan.total_attempt_budget,
            requested_memory_policy=fallback.approved_plan.requested_memory_policy,
            normalized_fields=fallback.approved_plan.normalized_fields,
        )
        return PlanPolicyOutcome(report=report, approved_plan=approved, fallback_used=True)

    def _validate_step(
        self,
        step: PlanStepProposal,
        envelope: AdaptiveTaskEnvelope,
        available_input_refs: dict[str, str],
        step_by_id: dict[str, PlanStepProposal],
        issues: list[PlanPolicyIssue],
    ) -> None:
        if not step.step_id:
            return
        if step.capability_id not in envelope.allowed_capability_ids or not self.registry.contains(step.capability_id):
            issues.append(self._issue("unknown_or_unauthorized_capability", step, "capability_id", step.capability_id))
            return
        descriptor = self.registry.get(step.capability_id)
        if descriptor.owner_role != step.role:
            issues.append(self._issue("capability_owner_mismatch", step, "role", step.role))
        if self._contains_prompt_escape(step.goal):
            issues.append(self._issue("unsafe_goal_or_prompt_injection", step, "goal", step.goal))
        if descriptor.execution_kind == ExecutionKind.LLM_BOUNDED_PYTHON and (
            not self.allow_llm_python or not envelope.allow_llm_python
        ):
            issues.append(self._issue("llm_python_not_enabled_in_phase_one", step, "capability_id", step.capability_id))
        if _RISK_RANK[descriptor.side_effect_class] > _RISK_RANK[envelope.risk_class]:
            issues.append(self._issue("risk_class_exceeded", step, "capability_id", step.capability_id))
        if step.output_contract_version != descriptor.output_contract_version:
            issues.append(self._issue("capability_output_contract_mismatch", step, "output_contract_version", step.output_contract_version))
        if step.output_contract_version not in envelope.allowed_output_contracts and step.output_contract_version != descriptor.output_contract_version:
            issues.append(self._issue("step_output_contract_not_allowed", step, "output_contract_version", step.output_contract_version))
        for dependency in step.depends_on:
            if dependency not in step_by_id:
                issues.append(self._issue("unknown_dependency", step, "depends_on", dependency))
        if step.input_ref_ids and not descriptor.input_ref_kinds:
            issues.append(self._issue(
                "capability_does_not_accept_input_refs",
                step,
                "input_ref_ids",
                ",".join(step.input_ref_ids),
            ))
        for ref_id, ref_kind in zip(step.input_ref_ids, step.input_ref_kinds, strict=False):
            upstream_source = self._upstream_ref_source(ref_id, step.depends_on)
            if ref_id in available_input_refs:
                if available_input_refs[ref_id] != ref_kind:
                    issues.append(self._issue("input_ref_kind_mismatch", step, "input_ref_kinds", ref_kind))
                continue
            if upstream_source is None or upstream_source not in step_by_id:
                issues.append(self._issue("unknown_input_ref", step, "input_ref_ids", ref_id))
            else:
                upstream_step = step_by_id[upstream_source]
                if not self.registry.contains(upstream_step.capability_id):
                    issues.append(self._issue("unknown_input_ref", step, "input_ref_ids", ref_id))
                    continue
                upstream_descriptor = self.registry.get(upstream_step.capability_id)
                if ref_kind not in upstream_descriptor.output_ref_kinds:
                    issues.append(self._issue("upstream_input_ref_kind_mismatch", step, "input_ref_kinds", ref_kind))
            if descriptor.input_ref_kinds and ref_kind not in descriptor.input_ref_kinds:
                issues.append(self._issue("capability_input_kind_mismatch", step, "input_ref_kinds", ref_kind))
        if len(step.input_ref_ids) != len(step.input_ref_kinds):
            issues.append(self._issue("input_ref_shape_mismatch", step, "input_ref_ids"))
        if step.on_failure not in _ALLOWED_FAILURE_ACTIONS:
            issues.append(self._issue("invalid_failure_action", step, "on_failure", step.on_failure))
        if step.role == "executor" and (
            len(step.required_input_fields) > 64
            or len(set(step.required_input_fields)) != len(step.required_input_fields)
            or any(
                not isinstance(field, str)
                or not field.strip()
                or len(field) > 128
                or "\n" in field
                for field in step.required_input_fields
            )
        ):
            issues.append(self._issue(
                "invalid_required_input_fields",
                step,
                "required_input_fields",
                ",".join(str(field) for field in step.required_input_fields),
            ))
        for key, value in step.completion_criteria.items():
            if key not in _ALLOWED_COMPLETION_KEYS or not self._safe_criterion(value):
                issues.append(self._issue("invalid_completion_criteria", step, f"completion_criteria.{key}", str(value)))
                continue
            criterion_contract = descriptor.completion_criteria_contract.get(key)
            if criterion_contract is None:
                issues.append(self._issue(
                    "completion_criteria_not_supported_by_capability",
                    step,
                    f"completion_criteria.{key}",
                    str(value),
                ))
                continue
            if not self._criterion_matches_contract(value, criterion_contract):
                issues.append(self._issue(
                    "completion_criteria_outside_capability_contract",
                    step,
                    f"completion_criteria.{key}",
                    str(value),
                ))

    def _validate_executor_stage_contracts(
        self,
        proposal: PlanProposal,
        step_by_id: dict[str, PlanStepProposal],
        issues: list[PlanPolicyIssue],
    ) -> None:
        """Keep recovery alternatives out of the DAG and verify field flow.

        Fallback capability IDs are controller-owned recovery choices, not
        additional semantic stages. Generic same-contract Executor pipelines
        remain legal when the downstream stage declares fields that an
        upstream Executor promised through its completion contract.
        """
        for step in proposal.steps:
            if step.role != "executor":
                continue
            descriptor = self.registry.get(step.capability_id)
            executor_dependencies = tuple(
                step_by_id[dependency]
                for dependency in step.depends_on
                if step_by_id[dependency].role == "executor"
            )
            if not executor_dependencies:
                continue

            field_contract_dependencies: list[PlanStepProposal] = []
            available_fields: set[str] = set()
            for producer in executor_dependencies:
                producer_descriptor = self.registry.get(producer.capability_id)
                fallback_pair = (
                    descriptor.fallback_capability_id == producer.capability_id
                    or producer_descriptor.fallback_capability_id == step.capability_id
                )
                if fallback_pair and producer.output_contract_version == step.output_contract_version:
                    issues.append(self._issue(
                        "fallback_capability_pipeline_forbidden",
                        step,
                        "depends_on",
                        producer.step_id,
                    ))

                if (
                    "required_fields" in descriptor.completion_criteria_contract
                    and "required_fields" in producer_descriptor.completion_criteria_contract
                    and producer.output_contract_version == step.output_contract_version
                ):
                    field_contract_dependencies.append(producer)
                    raw_fields = producer.completion_criteria.get("required_fields", ())
                    if isinstance(raw_fields, (list, tuple)):
                        available_fields.update(str(field) for field in raw_fields)

            if not field_contract_dependencies:
                continue
            if not step.required_input_fields:
                issues.append(self._issue(
                    "executor_input_fields_undeclared",
                    step,
                    "required_input_fields",
                ))
                continue
            missing_fields = sorted(set(step.required_input_fields) - available_fields)
            if missing_fields:
                issues.append(self._issue(
                    "executor_input_fields_not_produced",
                    step,
                    "required_input_fields",
                    ",".join(missing_fields),
                ))

    def _validate_plan_budgets_and_edges(
        self,
        proposal: PlanProposal,
        envelope: AdaptiveTaskEnvelope,
        step_by_id: dict[str, PlanStepProposal],
        issues: list[PlanPolicyIssue],
    ) -> None:
        retrieval_steps = 0
        replan_steps = 0
        execution_runtime_ms = 0
        for step in proposal.steps:
            descriptor = self.registry.get(step.capability_id)
            execution_runtime_ms += descriptor.max_runtime_ms
            retrieval_steps += int(descriptor.execution_kind == ExecutionKind.RETRIEVAL_ADAPTER)
            replan_steps += int(step.on_failure == "request_replan")
            for dependency in step.depends_on:
                producer = self.registry.get(step_by_id[dependency].capability_id)
                if (
                    producer.output_ref_kinds
                    and descriptor.input_ref_kinds
                    and not set(producer.output_ref_kinds).intersection(descriptor.input_ref_kinds)
                ):
                    issues.append(self._issue("dependency_output_not_consumable", step, "depends_on", dependency))
            provided_kinds = set(step.input_ref_kinds)
            for dependency in step.depends_on:
                provided_kinds.update(
                    self.registry.get(step_by_id[dependency].capability_id).output_ref_kinds
                )
            for required_kind in descriptor.required_input_ref_kinds:
                if required_kind not in provided_kinds:
                    issues.append(self._issue(
                        "required_input_kind_not_covered",
                        step,
                        "depends_on",
                        required_kind,
                    ))
        if retrieval_steps > envelope.max_retrieval_steps:
            issues.append(self._issue("retrieval_step_budget_exceeded", field_path="steps", value=str(retrieval_steps)))
        if replan_steps > envelope.max_replans:
            issues.append(self._issue("replan_budget_exceeded", field_path="steps", value=str(replan_steps)))
        if execution_runtime_ms > envelope.max_execution_runtime_ms:
            issues.append(self._issue("execution_runtime_budget_exceeded", field_path="steps", value=str(execution_runtime_ms)))
        leaf_contracts = {
            step.output_contract_version
            for step in proposal.steps
            if not any(step.step_id in candidate.depends_on for candidate in proposal.steps)
        }
        if proposal.final_output_contract_version not in leaf_contracts:
            issues.append(self._issue("final_output_not_produced", field_path="final_output_contract_version", value=proposal.final_output_contract_version))

    @staticmethod
    def _upstream_ref_source(ref_id: str, dependencies: tuple[str, ...]) -> str | None:
        for dependency in dependencies:
            if ref_id in {dependency, f"{dependency}-output"} or ref_id.startswith(f"{dependency}:"):
                return dependency
        return None

    @staticmethod
    def _contains_prompt_escape(value: str) -> bool:
        normalized = value.strip().lower()
        return bool(normalized) and any(marker in normalized for marker in _PROMPT_ESCAPE_MARKERS)

    @staticmethod
    def _safe_criterion(value: object) -> bool:
        if isinstance(value, (bool, int, float)):
            return True
        if isinstance(value, str):
            return len(value) <= 128 and "\n" not in value
        if isinstance(value, (tuple, list)):
            return len(value) <= 8 and all(isinstance(item, str) and len(item) <= 128 for item in value)
        return False

    @staticmethod
    def _criterion_matches_contract(value: object, contract: dict[str, object]) -> bool:
        """Validate a criterion against the registered capability, not model text.

        The response schema deliberately remains grammar-friendly for the local
        vLLM version.  Range, field, and cardinality checks therefore belong in
        this policy boundary where they are deterministic and auditable.
        """
        kind = str(contract.get("type", "")).strip()
        if kind == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                return False
            minimum = contract.get("minimum")
            maximum = contract.get("maximum")
            return (
                (not isinstance(minimum, int) or value >= minimum)
                and (not isinstance(maximum, int) or value <= maximum)
            )
        if kind == "string_list":
            if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
                return False
            minimum = contract.get("min_items")
            maximum = contract.get("max_items")
            if isinstance(minimum, int) and len(value) < minimum:
                return False
            if isinstance(maximum, int) and len(value) > maximum:
                return False
            # An omitted enum means arbitrary field names are valid.  Generic
            # analysis capabilities intentionally expose a bounded list shape
            # without pre-registering task-specific columns.
            allowed_values = contract.get("allowed_values")
            if allowed_values is None:
                return True
            if not isinstance(allowed_values, (list, tuple)):
                return False
            return set(value) <= {str(item) for item in allowed_values}
        return False

    @staticmethod
    def _normalize_step(step: PlanStepProposal, normalized_fields: list[str]) -> PlanStepProposal:
        normalized = PlanStepProposal(
            step_id=step.step_id.strip(),
            role=step.role.strip().lower(),
            capability_id=step.capability_id.strip(),
            goal=step.goal.strip(),
            depends_on=tuple(dict.fromkeys(step.depends_on)),
            input_ref_ids=tuple(step.input_ref_ids),
            input_ref_kinds=tuple(step.input_ref_kinds),
            output_contract_version=step.output_contract_version.strip(),
            completion_criteria=dict(sorted(step.completion_criteria.items())),
            on_failure=step.on_failure,
            required_input_fields=(
                tuple(dict.fromkeys(field.strip() for field in step.required_input_fields))
                if step.role.strip().lower() == "executor"
                else ()
            ),
        )
        if normalized.canonical_payload() != step.canonical_payload():
            normalized_fields.append(f"steps.{step.step_id}")
        return normalized

    @staticmethod
    def _has_cycle(steps: dict[str, PlanStepProposal]) -> bool:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> bool:
            if step_id in visiting:
                return True
            if step_id in visited:
                return False
            visiting.add(step_id)
            for dependency in steps[step_id].depends_on:
                if dependency in steps and visit(dependency):
                    return True
            visiting.remove(step_id)
            visited.add(step_id)
            return False

        return any(visit(step_id) for step_id in sorted(steps))

    @staticmethod
    def _max_depth(steps: dict[str, PlanStepProposal]) -> int:
        memo: dict[str, int] = {}

        def depth(step_id: str) -> int:
            if step_id in memo:
                return memo[step_id]
            memo[step_id] = 1 + max((depth(dep) for dep in steps[step_id].depends_on), default=0)
            return memo[step_id]

        return max((depth(step_id) for step_id in steps), default=0)

    @staticmethod
    def _issue(
        error_code: str,
        step: PlanStepProposal | None = None,
        field_path: str = "",
        value: str = "",
    ) -> PlanPolicyIssue:
        return PlanPolicyIssue(
            error_code=error_code,
            step_id="" if step is None else step.step_id,
            field_path=field_path,
            proposed_value_hash=sha256_digest(value) if value else "",
            resolution="rejected",
        )
