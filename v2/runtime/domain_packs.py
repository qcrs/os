from __future__ import annotations

from dataclasses import dataclass

from v2.contracts import (
    AdaptiveTaskEnvelope,
    CapabilityDescriptor,
    ExecutionKind,
    PlanProposal,
    PlanStepProposal,
    RiskClass,
)
from v2.runtime.capability_registry import CapabilityRegistry


@dataclass(frozen=True)
class DomainPack:
    pack_id: str
    capability_ids: tuple[str, ...]
    final_output_contract: str

    def fallback_proposal(self, envelope: AdaptiveTaskEnvelope) -> PlanProposal:
        if self.pack_id == "generic_adaptive_analysis_v2":
            raise ValueError("generic_adaptive_analysis_has_no_hidden_fixed_fallback")
        steps = (
            PlanStepProposal(
                step_id="retrieve-evidence",
                role="retriever",
                capability_id="retrieve_semantic_evidence_v1",
                goal="retrieve registered evidence",
                output_contract_version="statebus.evidence_pack.v2",
                completion_criteria={"min_locator_count": 1},
                on_failure="request_replan",
            ),
            PlanStepProposal(
                step_id="extract-metrics",
                role="executor",
                capability_id="extract_metric_series_v1",
                goal="extract a metric series from verified evidence",
                depends_on=("retrieve-evidence",),
                output_contract_version="statebus.metric_series.v1",
                completion_criteria={"min_rows": 1},
                on_failure="fallback_deterministic",
            ),
            PlanStepProposal(
                step_id="compose-report",
                role="summarizer",
                capability_id="compose_cited_report_v1",
                goal="compose cited report from verified results",
                depends_on=("retrieve-evidence", "extract-metrics"),
                output_contract_version=self.final_output_contract,
                completion_criteria={"min_locator_count": 1},
            ),
        )
        return PlanProposal(
            proposal_id=f"fallback-{envelope.task_id}",
            task_id=envelope.task_id,
            steps=steps,
            final_output_contract_version=self.final_output_contract,
            planner_notes="deterministic domain-pack fallback",
            model_id="runtime-fallback",
        )


def long_doc_analysis_pack() -> DomainPack:
    return DomainPack(
        pack_id="long_doc_analysis_v1",
        capability_ids=(
            "retrieve_semantic_evidence_v1",
            "retrieve_table_evidence_v1",
            # The typed adaptive memory dispatcher is not implemented yet.
            # Keep its descriptor registered for compatibility audits, but do
            # not advertise authority that the dispatcher cannot honor.
            "extract_metric_series_v1",
            "compare_periods_v1",
            "aggregate_metrics_v1",
            "join_metric_tables_v1",
            "detect_anomaly_v1",
            "detect_conflict_v1",
            "compose_cited_report_v1",
            "compose_comparison_report_v1",
            "compose_risk_memo_v1",
            "bounded_metric_python_v1",
            "compare_periods_python_v1",
            "aggregate_metrics_python_v1",
            "detect_anomaly_python_v1",
        ),
        final_output_contract="statebus.cited_report.v1",
    )


def register_long_doc_analysis_capabilities(registry: CapabilityRegistry) -> DomainPack:
    descriptors = (
        CapabilityDescriptor(
            capability_id="retrieve_semantic_evidence_v1",
            owner_role="retriever",
            description="Retrieve cited semantic evidence from the approved corpus.",
            input_ref_kinds=(),
            input_contract_version="statebus.evidence_request.v1",
            output_ref_kinds=("canonical_evidence_pack",),
            output_contract_version="statebus.evidence_pack.v2",
            execution_kind=ExecutionKind.RETRIEVAL_ADAPTER,
            side_effect_class=RiskClass.READ_ONLY,
            max_runtime_ms=8_000,
            supports_replay=True,
            validator_ids=("evidence_coverage",),
            completion_criteria_contract={
                "min_locator_count": {"type": "integer", "minimum": 1, "maximum": 3},
                "required_evidence_types": {
                    "type": "string_list",
                    "allowed_values": ["semantic_context", "table"],
                    "min_items": 1,
                    "max_items": 2,
                },
                "max_conflicts": {"type": "integer", "minimum": 0, "maximum": 0},
            },
        ),
        CapabilityDescriptor(
            capability_id="retrieve_table_evidence_v1",
            owner_role="retriever",
            description="Retrieve cited table evidence from the approved corpus.",
            input_ref_kinds=(),
            input_contract_version="statebus.evidence_request.v1",
            output_ref_kinds=("canonical_evidence_pack",),
            output_contract_version="statebus.evidence_pack.v2",
            execution_kind=ExecutionKind.RETRIEVAL_ADAPTER,
            side_effect_class=RiskClass.READ_ONLY,
            max_runtime_ms=8_000,
            supports_replay=True,
            validator_ids=("evidence_coverage",),
            completion_criteria_contract={
                "min_locator_count": {"type": "integer", "minimum": 1, "maximum": 3},
                "required_evidence_types": {
                    "type": "string_list",
                    "allowed_values": ["semantic_context", "table"],
                    "min_items": 1,
                    "max_items": 2,
                },
                "max_conflicts": {"type": "integer", "minimum": 0, "maximum": 0},
            },
        ),
        CapabilityDescriptor(
            capability_id="retrieve_memory_assist_v1",
            owner_role="retriever",
            description="Match compatible memory evidence without granting reuse automatically.",
            input_ref_kinds=("semantic_state",),
            input_contract_version="statebus.memory_match_request.v1",
            output_ref_kinds=("memory",),
            output_contract_version="statebus.memory_match_result.v1",
            execution_kind=ExecutionKind.RETRIEVAL_ADAPTER,
            side_effect_class=RiskClass.READ_ONLY,
            max_runtime_ms=4_000,
            supports_replay=False,
            validator_ids=("memory_compatibility",),
        ),
        CapabilityDescriptor(
            capability_id="extract_metric_series_v1",
            owner_role="executor",
            description="Extract a metric series from verified table evidence using the Transform DSL.",
            input_ref_kinds=("canonical_evidence_pack", "execution_artifact"),
            input_contract_version="statebus.transform_input.v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.metric_series.v1",
            execution_kind=ExecutionKind.TRANSFORM_DSL,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=30_000,
            supports_replay=True,
            validator_ids=("metric_series",),
            completion_criteria_contract={
                "min_rows": {"type": "integer", "minimum": 1, "maximum": 2},
                "required_fields": {
                    "type": "string_list",
                    "allowed_values": ["quarter", "revenue_musd"],
                    "min_items": 1,
                    "max_items": 2,
                },
            },
        ),
        CapabilityDescriptor(
            capability_id="compare_periods_v1",
            owner_role="executor",
            description="Compare verified metric periods using the Transform DSL.",
            input_ref_kinds=("execution_artifact", "canonical_evidence_pack"),
            input_contract_version="statebus.metric_series.v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.comparison.v1",
            execution_kind=ExecutionKind.TRANSFORM_DSL,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=30_000,
            supports_replay=True,
            validator_ids=("period_comparison",),
            fallback_capability_id="extract_metric_series_v1",
            completion_criteria_contract={
                "min_rows": {"type": "integer", "minimum": 1, "maximum": 2},
            },
        ),
        CapabilityDescriptor(
            capability_id="detect_conflict_v1",
            owner_role="executor",
            description="Detect deterministic conflicts across approved evidence.",
            input_ref_kinds=("canonical_evidence_pack", "execution_artifact"),
            input_contract_version="statebus.transform_input.v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.conflict_report.v1",
            execution_kind=ExecutionKind.RUNTIME_BUILTIN,
            side_effect_class=RiskClass.READ_ONLY,
            max_runtime_ms=4_000,
            supports_replay=True,
            validator_ids=("conflict_check",),
            completion_criteria_contract={
                "max_conflicts": {"type": "integer", "minimum": 0, "maximum": 0},
            },
        ),
        CapabilityDescriptor(
            capability_id="aggregate_metrics_v1",
            owner_role="executor",
            description="Aggregate a verified operating-metric table using the Transform DSL.",
            input_ref_kinds=("execution_artifact", "canonical_evidence_pack"),
            input_contract_version="statebus.transform_input.v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.aggregation.v1",
            execution_kind=ExecutionKind.TRANSFORM_DSL,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=30_000,
            supports_replay=True,
            validator_ids=("aggregation",),
            fallback_capability_id="extract_metric_series_v1",
            completion_criteria_contract={"min_rows": {"type": "integer", "minimum": 1, "maximum": 10_000}},
        ),
        CapabilityDescriptor(
            capability_id="join_metric_tables_v1",
            owner_role="executor",
            description="Join two verified metric tables on an approved key using the Transform DSL.",
            input_ref_kinds=("execution_artifact",),
            input_contract_version="statebus.transform_input.v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.joined_metrics.v1",
            execution_kind=ExecutionKind.TRANSFORM_DSL,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=30_000,
            supports_replay=True,
            validator_ids=("join",),
            fallback_capability_id="extract_metric_series_v1",
            completion_criteria_contract={"min_rows": {"type": "integer", "minimum": 1, "maximum": 10_000}},
        ),
        CapabilityDescriptor(
            capability_id="detect_anomaly_v1",
            owner_role="executor",
            description="Detect bounded statistical anomalies from a verified metric artifact using the Transform DSL.",
            input_ref_kinds=("execution_artifact",),
            input_contract_version="statebus.transform_input.v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.anomaly_report.v1",
            execution_kind=ExecutionKind.TRANSFORM_DSL,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=30_000,
            supports_replay=True,
            validator_ids=("anomaly",),
            fallback_capability_id="extract_metric_series_v1",
            completion_criteria_contract={"min_rows": {"type": "integer", "minimum": 1, "maximum": 10_000}},
        ),
        CapabilityDescriptor(
            capability_id="compose_cited_report_v1",
            owner_role="summarizer",
            description="Compose a cited ClaimSet from verified evidence and artifacts.",
            input_ref_kinds=("canonical_evidence_pack", "execution_artifact"),
            input_contract_version="statebus.claim_input.v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.cited_report.v1",
            execution_kind=ExecutionKind.RUNTIME_BUILTIN,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=30_000,
            supports_replay=True,
            required_input_ref_kinds=("canonical_evidence_pack", "execution_artifact"),
            validator_ids=("claim_citation", "claim_numeric"),
            completion_criteria_contract={
                "min_locator_count": {"type": "integer", "minimum": 1, "maximum": 3},
                "required_evidence_types": {
                    "type": "string_list",
                    "allowed_values": ["semantic_context", "table"],
                    "min_items": 1,
                    "max_items": 2,
                },
                "max_conflicts": {"type": "integer", "minimum": 0, "maximum": 0},
            },
        ),
        CapabilityDescriptor(
            capability_id="bounded_metric_python_v1",
            owner_role="executor",
            description="Generate bounded pure-Python metric transformation when explicitly enabled.",
            input_ref_kinds=("execution_artifact",),
            input_contract_version="statebus.code_generation_input.v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.metric_series.v1",
            execution_kind=ExecutionKind.LLM_BOUNDED_PYTHON,
            side_effect_class=RiskClass.BOUNDED_CODE,
            # Covers bounded model generation plus the bwrap execution timeout.
            # The Grant remains capability-scoped; this does not expand file,
            # network, validator, or sandbox authority.
            max_runtime_ms=30_000,
            supports_replay=True,
            validator_ids=("metric_series",),
            fallback_capability_id="extract_metric_series_v1",
            completion_criteria_contract={
                "min_rows": {"type": "integer", "minimum": 1, "maximum": 2},
            },
        ),
        CapabilityDescriptor(
            capability_id="compare_periods_python_v1",
            owner_role="executor",
            description="Generate bounded Python comparison output with independently recomputed difference, ratio, and growth.",
            input_ref_kinds=("execution_artifact",),
            input_contract_version="statebus.metric_series.v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.comparison.v1",
            execution_kind=ExecutionKind.LLM_BOUNDED_PYTHON,
            side_effect_class=RiskClass.BOUNDED_CODE,
            max_runtime_ms=30_000,
            supports_replay=True,
            validator_ids=("period_comparison",),
            fallback_capability_id="compare_periods_v1",
            completion_criteria_contract={"min_rows": {"type": "integer", "minimum": 1, "maximum": 1}},
        ),
        CapabilityDescriptor(
            capability_id="aggregate_metrics_python_v1",
            owner_role="executor",
            description="Generate bounded Python grouped aggregates with independently recomputed sum, mean, min, max, and count.",
            input_ref_kinds=("execution_artifact",),
            input_contract_version="statebus.transform_input.v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.aggregation.v1",
            execution_kind=ExecutionKind.LLM_BOUNDED_PYTHON,
            side_effect_class=RiskClass.BOUNDED_CODE,
            max_runtime_ms=30_000,
            supports_replay=True,
            validator_ids=("aggregation",),
            fallback_capability_id="aggregate_metrics_v1",
            completion_criteria_contract={"min_rows": {"type": "integer", "minimum": 1, "maximum": 10_000}},
        ),
        CapabilityDescriptor(
            capability_id="detect_anomaly_python_v1",
            owner_role="executor",
            description="Generate bounded Python anomaly annotations using controller-defined mean and z-threshold semantics.",
            input_ref_kinds=("execution_artifact",),
            input_contract_version="statebus.transform_input.v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.anomaly_report.v1",
            execution_kind=ExecutionKind.LLM_BOUNDED_PYTHON,
            side_effect_class=RiskClass.BOUNDED_CODE,
            max_runtime_ms=30_000,
            supports_replay=True,
            validator_ids=("anomaly",),
            fallback_capability_id="detect_anomaly_v1",
            completion_criteria_contract={"min_rows": {"type": "integer", "minimum": 1, "maximum": 10_000}},
        ),
        CapabilityDescriptor(
            capability_id="compose_comparison_report_v1",
            owner_role="summarizer",
            description="Compose a cited comparison report from verified evidence and metrics.",
            input_ref_kinds=("canonical_evidence_pack", "execution_artifact"),
            input_contract_version="statebus.claim_input.v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.cited_report.v1",
            execution_kind=ExecutionKind.RUNTIME_BUILTIN,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=30_000,
            supports_replay=True,
            required_input_ref_kinds=("canonical_evidence_pack", "execution_artifact"),
            validator_ids=("cited_report",),
            completion_criteria_contract={"min_locator_count": {"type": "integer", "minimum": 1, "maximum": 20}},
        ),
        CapabilityDescriptor(
            capability_id="compose_risk_memo_v1",
            owner_role="summarizer",
            description="Compose a cited risk memo from verified anomaly or conflict artifacts.",
            input_ref_kinds=("canonical_evidence_pack", "execution_artifact"),
            input_contract_version="statebus.claim_input.v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.cited_report.v1",
            execution_kind=ExecutionKind.RUNTIME_BUILTIN,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=30_000,
            supports_replay=True,
            required_input_ref_kinds=("canonical_evidence_pack", "execution_artifact"),
            validator_ids=("cited_report",),
            completion_criteria_contract={"min_locator_count": {"type": "integer", "minimum": 1, "maximum": 20}},
        ),
    )
    for descriptor in descriptors:
        registry.register(descriptor)
    return long_doc_analysis_pack()


def generic_adaptive_analysis_pack() -> DomainPack:
    """Return the capability closure for model-directed formal analysis.

    The registry describes *authority* (what the runtime may execute), not the
    business question being evaluated.  Formal adapters must use this closure
    instead of registering one capability per benchmark operation.
    """
    return DomainPack(
        pack_id="generic_adaptive_analysis_v2",
        capability_ids=(
            "retrieve_semantic_evidence_v1",
            "retrieve_table_evidence_v1",
            "execute_analysis_dsl_v2",
            "execute_bounded_python_v2",
            "compose_claim_set_v2",
            "compose_risk_memo_v1",
        ),
        final_output_contract="statebus.cited_report.v1",
    )


def register_generic_adaptive_analysis_capabilities(registry: CapabilityRegistry) -> DomainPack:
    """Register generic execution authorities once for a domain pack.

    No task operation, expected answer, formula, or case-specific output shape
    is encoded here.  The task contract supplies the requested result schema;
    the model chooses an analysis recipe inside this authority closure.
    """
    descriptors = (
        CapabilityDescriptor(
            capability_id="retrieve_semantic_evidence_v1",
            owner_role="retriever",
            description="Retrieve cited semantic evidence from the approved corpus.",
            input_ref_kinds=(),
            input_contract_version="statebus.evidence_request.v1",
            output_ref_kinds=("canonical_evidence_pack",),
            output_contract_version="statebus.evidence_pack.v2",
            execution_kind=ExecutionKind.RETRIEVAL_ADAPTER,
            side_effect_class=RiskClass.READ_ONLY,
            max_runtime_ms=8_000,
            supports_replay=True,
            validator_ids=("evidence_coverage",),
            completion_criteria_contract={
                "min_locator_count": {"type": "integer", "minimum": 1, "maximum": 20},
                "required_evidence_types": {
                    "type": "string_list",
                    "allowed_values": ["semantic_context", "table"],
                    "min_items": 1,
                    "max_items": 2,
                },
                "max_conflicts": {"type": "integer", "minimum": 0, "maximum": 0},
            },
        ),
        CapabilityDescriptor(
            capability_id="retrieve_table_evidence_v1",
            owner_role="retriever",
            description="Retrieve cited table evidence from the approved corpus.",
            input_ref_kinds=(),
            input_contract_version="statebus.evidence_request.v1",
            output_ref_kinds=("canonical_evidence_pack",),
            output_contract_version="statebus.evidence_pack.v2",
            execution_kind=ExecutionKind.RETRIEVAL_ADAPTER,
            side_effect_class=RiskClass.READ_ONLY,
            max_runtime_ms=8_000,
            supports_replay=True,
            validator_ids=("evidence_coverage",),
            completion_criteria_contract={
                "min_locator_count": {"type": "integer", "minimum": 1, "maximum": 20},
                "required_evidence_types": {
                    "type": "string_list",
                    "allowed_values": ["semantic_context", "table"],
                    "min_items": 1,
                    "max_items": 2,
                },
                "max_conflicts": {"type": "integer", "minimum": 0, "maximum": 0},
            },
        ),
        CapabilityDescriptor(
            capability_id="execute_analysis_dsl_v2",
            owner_role="executor",
            description=(
                "Execute a model-authored declarative analysis program over verified artifacts. "
                "Use for select, rename, filter, sort, basic aggregate/group, safe difference/ratio/percentage derivation, "
                "or two-period comparison with baseline/current values, difference, ratio, and growth percentage. "
                "Its operations form one linear row pipeline: it cannot split one input into branches and recombine them, "
                "self-join or pivot category rows into columns, or compare values that remain on different rows. "
                "Do not use it for custom parsing, categorical labels, imputation, or a statistical definition not represented "
                "exactly by the registered DSL operations."
            ),
            input_ref_kinds=("execution_artifact", "canonical_evidence_pack"),
            input_contract_version="statebus.analysis_input.v2",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.analysis_result.v2",
            execution_kind=ExecutionKind.TRANSFORM_DSL,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=120_000,
            supports_replay=True,
            validator_ids=("generic_analysis",),
            fallback_capability_id="execute_bounded_python_v2",
            completion_criteria_contract={
                "min_rows": {"type": "integer", "minimum": 1, "maximum": 100_000},
                "required_fields": {
                    "type": "string_list",
                    "min_items": 1,
                    "max_items": 64,
                },
            },
        ),
        CapabilityDescriptor(
            capability_id="execute_bounded_python_v2",
            owner_role="executor",
            description=(
                "Generate and execute bounded Python for an approved analysis intent over verified artifacts. "
                "Use when the task needs custom parsing, multi-stage statistics, outlier handling, imputation, cross-row "
                "alignment, pivoting, branch-and-recombine processing, or another composition that the declarative analysis "
                "capability cannot express."
            ),
            input_ref_kinds=("execution_artifact", "canonical_evidence_pack"),
            input_contract_version="statebus.analysis_input.v2",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.analysis_result.v2",
            execution_kind=ExecutionKind.LLM_BOUNDED_PYTHON,
            side_effect_class=RiskClass.BOUNDED_CODE,
            max_runtime_ms=120_000,
            supports_replay=True,
            required_input_ref_kinds=("execution_artifact",),
            validator_ids=("generic_analysis",),
            fallback_capability_id="execute_analysis_dsl_v2",
            completion_criteria_contract={
                "min_rows": {"type": "integer", "minimum": 1, "maximum": 100_000},
                "required_fields": {
                    "type": "string_list",
                    "min_items": 1,
                    "max_items": 64,
                },
            },
        ),
        CapabilityDescriptor(
            capability_id="compose_claim_set_v2",
            owner_role="summarizer",
            description="Compose a cited ClaimSet from verified evidence and analysis artifacts.",
            input_ref_kinds=("canonical_evidence_pack", "execution_artifact"),
            input_contract_version="statebus.claim_input.v2",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.cited_report.v1",
            execution_kind=ExecutionKind.RUNTIME_BUILTIN,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=30_000,
            supports_replay=True,
            required_input_ref_kinds=("canonical_evidence_pack", "execution_artifact"),
            validator_ids=("claim_citation", "claim_numeric"),
            completion_criteria_contract={
                "min_locator_count": {"type": "integer", "minimum": 1, "maximum": 100},
                "max_conflicts": {"type": "integer", "minimum": 0, "maximum": 0},
            },
        ),
        CapabilityDescriptor(
            capability_id="compose_risk_memo_v1",
            owner_role="summarizer",
            description="Compose a cited risk memo from verified analysis artifacts.",
            input_ref_kinds=("canonical_evidence_pack", "execution_artifact"),
            input_contract_version="statebus.claim_input.v2",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="statebus.cited_report.v1",
            execution_kind=ExecutionKind.RUNTIME_BUILTIN,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=30_000,
            supports_replay=True,
            required_input_ref_kinds=("canonical_evidence_pack", "execution_artifact"),
            validator_ids=("claim_citation", "claim_numeric"),
            completion_criteria_contract={
                "min_locator_count": {"type": "integer", "minimum": 1, "maximum": 100},
                "max_conflicts": {"type": "integer", "minimum": 0, "maximum": 0},
            },
        ),
    )
    for descriptor in descriptors:
        if not registry.contains(descriptor.capability_id):
            registry.register(descriptor)
    return generic_adaptive_analysis_pack()
