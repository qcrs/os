from __future__ import annotations

from pathlib import Path

from scripts.v2_diagnostics.run_adaptive_agent_smoke import _envelope_from_payload
from scripts.v2_diagnostics.run_adaptive_formal_compare import (
    _case_gate_failure,
    _classify_failure,
    _compile_formal_controller_wiring,
    _evaluate_formal_gates,
    _model_plan_errors,
    _normalize_formal_planner_array_leakage,
    _partition_planner_repair_errors,
    _row_scoped_evidence_items,
)
from v2.benchmark.adaptive_formal_mainline import (
    _adaptive_metrics,
    _build_formal_analysis_context,
    _case_system_gate_checks,
    _terminal_quality_reports,
)
from v2.benchmark.adaptive_formal import (
    adapt_formal_sample,
    build_formal_quality_validator,
    build_non_answer_source_profile,
    execution_task_parameters,
    expected_facts_report,
)
from v2.benchmark.task_registry import load_registered_formal_samples
from v2.contracts import (
    AdaptiveTaskEnvelope,
    PlanProposal,
    PlanStepProposal,
    RiskClass,
    WorkflowMode,
)
from v2.runtime.capability_validators import CapabilityQualityContext
from v2.runtime.capability_validators import default_capability_validator_registry
from v2.runtime.domain_packs import register_generic_adaptive_analysis_capabilities
from v2.runtime.capability_registry import CapabilityRegistry
from v2.runtime.plan_policy import PlanPolicyValidator
from v2.utils import sha256_digest, stable_json_dumps


def _cases():
    return [adapt_formal_sample(sample) for sample in load_registered_formal_samples()]


def test_all_25_registered_formal_cases_have_real_adaptive_adapters() -> None:
    cases = _cases()

    assert len(cases) == 25
    assert len({case.sample.task_family for case in cases}) == 5
    assert {case.operation for case in cases} == {
        "lookup_metric",
        "compare_metric",
        "compute_delta",
        "compute_trend",
        "profile_table",
        "aggregate_and_extreme",
        "profile_and_mean",
        "groupby_aggregate",
        "detect_outliers",
        "materialize_clean_table",
    }
    assert all(case.source_rows for case in cases)
    assert all(case.output_schema for case in cases)
    assert {case.capability_id for case in cases} == {"execute_bounded_python_v2"}


def test_independent_recomputation_matches_every_formal_expected_fact() -> None:
    reports = {
        case.task_id: expected_facts_report(case, case.expected_rows)
        for case in _cases()
    }

    assert all(report["passed"] for report in reports.values()), reports


def test_groupby_codeact_contract_exposes_source_date_format_without_expected_rows() -> None:
    case = next(case for case in _cases() if case.operation == "groupby_aggregate")

    assert case.operation_semantics["date_column"] == "DATE TIME"
    assert case.operation_semantics["date_format"] == (
        "MM/DD/YYYY HH:MM; the month is the leading two-digit MM component, "
        "for example 01/31/2015 23:00 has month 1"
    )
    assert "monthly_avg_windspeed.month_1" not in stable_json_dumps(case.operation_semantics)


def test_executor_context_profile_contains_no_values_or_benchmark_oracle() -> None:
    case = next(case for case in _cases() if case.operation == "groupby_aggregate")
    profile = build_non_answer_source_profile(case.source_rows)
    parameters = execution_task_parameters(case)
    assert profile["contains_values"] is False
    assert profile["row_count"] == len(case.source_rows)
    assert "quality_checks" not in parameters
    assert "csv_path" not in parameters
    assert "dataset_id" not in parameters
    assert parameters["groupby"] == "month(DATE TIME)"


def test_executor_context_profile_describes_bracketed_numeric_encoding_without_values() -> None:
    case = next(case for case in _cases() if case.operation == "aggregate_and_extreme")

    profile = build_non_answer_source_profile(case.source_rows)

    assert profile["contains_values"] is False
    assert profile["columns"]["No. of cases"]["formats"] == [
        "leading numeric token with optional [lower-upper] range; parse only the leading token as the value"
    ]
    serialized = stable_json_dumps(profile)
    assert "630308" not in serialized
    assert "2081990" not in serialized


def test_aggregation_rounding_contract_is_executor_visible_without_expected_facts() -> None:
    case = next(case for case in _cases() if case.task_id == "formal-agg-002")
    parameters = execution_task_parameters(case)

    assert parameters["mean_rounding"] == "nearest_integer"
    assert "rounded to the nearest integer" in case.sample.request_text
    visible_contract = stable_json_dumps({
        "request_text": case.sample.request_text,
        "task_parameters": parameters,
    })
    assert all(str(value) not in visible_contract for value in case.sample.expected_facts.values())


def test_formal_analysis_context_preserves_controller_operation_contract_without_answers() -> None:
    case = next(case for case in _cases() if case.operation == "materialize_clean_table")
    context = _build_formal_analysis_context(
        case,
        build_non_answer_source_profile(case.source_rows),
    )

    assert context["operation"] == "materialize_clean_table"
    assert "(n-1)*p" in str(context["inclusive_quantile_definition"])
    assert "do not impute" in str(context["outlier_column_missing_policy"]).lower()
    assert "only missing impute_column" in str(context["impute_column_missing_policy"])
    assert context["expected_values_are_not_provided"] is True
    serialized = stable_json_dumps(context)
    assert all(str(value) not in serialized for value in case.sample.expected_facts.values())


def test_adaptive_metrics_exposes_planner_gate_counts() -> None:
    metrics = _adaptive_metrics(
        [
            {
                "runtime_completed": True,
                "ok": True,
                "usage": {},
                "telemetry": {
                    "planner_hard_rejection_count": 0,
                    "planner_schema_repair_count": 1,
                    "planner_final_approved_count": 1,
                    "llm_codeact_quality_repair_count": 1,
                    "llm_codeact_quality_rejected_count": 1,
                    "dsl_quality_repair_count": 2,
                    "dsl_quality_rejected_count": 2,
                },
                "planner_policy_repair_used": True,
                "planner_schema_normalization_used": True,
            }
        ],
        selected_case_count=1,
        attempted_case_count=1,
    )

    assert metrics["planner_hard_rejection_count"] == 0
    assert metrics["planner_runtime_schema_repair_count"] == 1
    assert metrics["planner_policy_repair_count"] == 1
    assert metrics["planner_schema_normalization_count"] == 1
    assert metrics["planner_final_approved_count"] == 1
    assert metrics["codeact_quality_repair_count"] == 1
    assert metrics["codeact_quality_rejected_count"] == 1
    assert metrics["dsl_quality_repair_count"] == 2
    assert metrics["dsl_quality_rejected_count"] == 2


def test_formal_numeric_parser_contract_allows_only_in_memory_string_replace() -> None:
    case = next(case for case in _cases() if case.operation == "aggregate_and_extreme")

    numeric_parser = str(case.operation_semantics["numeric_parser"])

    assert "str.replace(',', '') is allowed" in numeric_parser
    assert "Path.replace" in numeric_parser


def test_summarizer_evidence_scope_prefers_each_rows_strongest_support() -> None:
    rows = (
        {"ticker": "ACME", "quarter": "2025Q3", "metric_value": 98.0},
        {"ticker": "ACME", "quarter": "2025Q4", "metric_value": 109.0},
    )
    evidence = (
        {"id": "q3", "text": "ACME revenue was 98 in 2025Q3", "locator": "q3"},
        {"id": "q4", "text": "ACME revenue was 109 in 2025Q4", "locator": "q4"},
        {"id": "q1", "text": "ACME revenue was 120 in 2026Q1", "locator": "q1"},
    )

    selected = _row_scoped_evidence_items(rows, evidence)

    assert [item["id"] for item in selected] == ["q3", "q4"]


def test_formal_quality_validator_rejects_a_tampered_model_output() -> None:
    case = next(case for case in _cases() if case.operation == "compute_delta")
    expected = case.expected_rows
    tampered = [dict(row) for row in expected]
    tampered[0]["delta_value"] = float(tampered[0]["delta_value"]) + 1.0
    validator = build_formal_quality_validator(case)
    report = validator(CapabilityQualityContext(
        capability_id=case.capability_id,
        validator_id=f"formal_quality_{case.operation}_v1",
        input_rows=(case.source_rows,),
        output_rows=tuple(tampered),
        input_artifact_hashes=(sha256_digest(stable_json_dumps(case.source_rows)),),
        output_artifact_hash=sha256_digest(stable_json_dumps(tampered)),
        required_fields=tuple(case.output_schema),
        completion_criteria={"min_rows": 1},
        operation_semantics=case.operation_semantics,
        provenance_item_ids=("formal-source",),
    ))

    assert not report.verified
    assert "formal_recomputation_mismatch" in report.error_codes


def test_role_worker_preserves_bounded_python_authority_from_envelope() -> None:
    envelope = AdaptiveTaskEnvelope(
        task_id="formal-case",
        canonical_task_spec_hash="spec-hash",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="formal",
        allowed_capability_ids=("execute_bounded_python_v2",),
        allowed_output_contracts=("statebus.analysis_result.v2",),
        risk_class=RiskClass.BOUNDED_CODE,
        allow_llm_python=True,
        max_plan_steps=3,
        max_replans=0,
    )

    restored = _envelope_from_payload(envelope.canonical_payload())

    assert restored == envelope
    assert restored.allow_llm_python
    assert restored.risk_class == RiskClass.BOUNDED_CODE


def test_formal_schema_normalizer_only_removes_known_field_leakage() -> None:
    case = _cases()[0]
    proposal = PlanProposal(
        proposal_id="proposal",
        task_id=case.task_id,
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                step_id="retrieve",
                role="retriever",
                capability_id="retrieve_semantic_evidence_v1",
                goal="retrieve",
                depends_on=("input_ref_ids", "unknown-semantic-dependency"),
                input_ref_ids=(case.source_ref_id,),
                input_ref_kinds=("execution_artifact",),
                output_contract_version="statebus.evidence_pack.v2",
            ),
        ),
    )

    normalized, fields = _normalize_formal_planner_array_leakage(case, proposal)

    assert normalized.steps[0].depends_on == ("input_ref_ids", "unknown-semantic-dependency")
    assert normalized.steps[0].input_ref_ids == (case.source_ref_id,)
    assert normalized.steps[0].input_ref_kinds == ("execution_artifact",)
    assert fields == ()


def test_formal_schema_normalizer_recovers_only_controller_bound_wiring() -> None:
    case = _cases()[0]
    proposal = PlanProposal(
        proposal_id="proposal",
        task_id=case.task_id,
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                step_id="retrieve",
                role="retriever",
                capability_id="retrieve_semantic_evidence_v1",
                goal="retrieve",
                depends_on=("input_ref_ids", "input_ref_kinds"),
                input_ref_ids=("input_ref_ids", "input_ref_kinds"),
                input_ref_kinds=("input_ref_ids", "input_ref_kinds"),
                output_contract_version="statebus.evidence_pack.v2",
            ),
            PlanStepProposal(
                step_id="analyze",
                role="executor",
                capability_id=case.capability_id,
                goal="analyze",
                depends_on=("input_ref_ids", "input_ref_kinds"),
                input_ref_ids=("input_ref_ids", "input_ref_kinds"),
                input_ref_kinds=("input_ref_ids", "input_ref_kinds"),
                output_contract_version=case.output_contract_version,
            ),
            PlanStepProposal(
                step_id="report",
                role="summarizer",
                capability_id="compose_cited_report_v1",
                goal="report",
                depends_on=("input_ref_ids", "input_ref_kinds"),
                input_ref_ids=("input_ref_ids", "input_ref_kinds"),
                input_ref_kinds=("input_ref_ids", "input_ref_kinds"),
                output_contract_version="statebus.cited_report.v1",
            ),
        ),
    )

    normalized, fields = _normalize_formal_planner_array_leakage(case, proposal)
    retriever, executor, summarizer = normalized.steps

    assert retriever.depends_on == ()
    assert retriever.input_ref_ids == ()
    assert retriever.input_ref_kinds == ()
    assert executor.depends_on == ()
    assert executor.input_ref_ids == (case.source_ref_id,)
    assert executor.input_ref_kinds == ("execution_artifact",)
    assert summarizer.depends_on == ("retrieve", "analyze")
    assert summarizer.input_ref_ids == ()
    assert summarizer.input_ref_kinds == ()
    assert fields


def test_formal_schema_normalizer_rejects_mixed_unknown_values() -> None:
    case = _cases()[0]
    proposal = PlanProposal(
        proposal_id="proposal",
        task_id=case.task_id,
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal("retrieve", "retriever", "retrieve_semantic_evidence_v1", "retrieve"),
            PlanStepProposal(
                "analyze",
                "executor",
                case.capability_id,
                "analyze",
                input_ref_ids=("input_ref_ids", "unknown-ref"),
                input_ref_kinds=("input_ref_ids", "input_ref_kinds"),
            ),
            PlanStepProposal("report", "summarizer", "compose_cited_report_v1", "report"),
        ),
    )

    normalized, _ = _normalize_formal_planner_array_leakage(case, proposal)

    assert normalized.steps[1].input_ref_ids == ("input_ref_ids", "unknown-ref")


def test_formal_schema_normalizer_does_not_clear_unknown_retriever_ref() -> None:
    case = _cases()[0]
    proposal = PlanProposal(
        proposal_id="proposal",
        task_id=case.task_id,
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                "retrieve",
                "retriever",
                "retrieve_semantic_evidence_v1",
                "retrieve",
                input_ref_ids=("unknown-ref",),
                input_ref_kinds=("input_ref_ids",),
            ),
            PlanStepProposal("analyze", "executor", case.capability_id, "analyze"),
            PlanStepProposal("report", "summarizer", "compose_cited_report_v1", "report"),
        ),
    )

    normalized, _ = _normalize_formal_planner_array_leakage(case, proposal)

    assert normalized.steps[0].input_ref_ids == ("unknown-ref",)
    assert normalized.steps[0].input_ref_kinds == ("input_ref_ids",)


def test_formal_compare_runner_is_new_adaptive_path_not_old_suite_wrapper() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "v2/benchmark/adaptive_formal_mainline.py").read_text(
        encoding="utf-8"
    )
    cli_source = (root / "scripts/v2_diagnostics/run_adaptive_formal_compare.py").read_text(
        encoding="utf-8"
    )
    wrapper = root / "scripts/v2_diagnostics/run_adaptive_formal_compare_gpu1.sh"

    assert 'RuntimeDriver().run_mode("adaptive_bounded"' in source
    assert "AdaptiveDispatchContext(" not in source
    assert "AdaptiveCapabilityDispatcher(" not in source
    assert "run_minimal_benchmark_family(" in source
    assert "run_v2_local_vllm_audit" not in source
    assert "run_adaptive_mode_matrix" not in source
    assert len(cli_source.splitlines()) < 40
    assert "AdaptiveMainlineRequest" not in cli_source
    assert wrapper.is_file()


def test_formal_runtime_uses_generic_authority_with_declared_operation_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "v2/benchmark/adaptive_formal_mainline.py").read_text(
        encoding="utf-8"
    )
    assert 'analysis_validator_ids=("formal_analysis", "generic_analysis")' in source
    assert 'validator_registry.register("formal_analysis", build_formal_quality_validator(case))' in source
    assert "_build_formal_analysis_context(case, source_profile)" in source
    assert 'case.capability_id: {' not in source
    assert 'execute_bounded_python_v2' in source
    assert source.count('"runtime_quality_scope": "formal_contract_recomputation_from_authorized_inputs"') == 2


def test_generic_analysis_validator_does_not_use_hidden_expected_rows() -> None:
    registry = CapabilityRegistry()
    pack = register_generic_adaptive_analysis_capabilities(registry)
    assert "execute_bounded_python_v2" in pack.capability_ids
    assert all("formal_" not in capability_id for capability_id in pack.capability_ids)
    validator = default_capability_validator_registry()
    report = validator.validate(CapabilityQualityContext(
        capability_id="execute_bounded_python_v2",
        validator_id="generic_analysis",
        input_rows=(({"value": 1},),),
        output_rows=({"answer": 2},),
        input_artifact_hashes=("source-hash",),
        output_artifact_hash="output-hash",
        required_fields=("answer",),
        completion_criteria={"min_rows": 1},
        expected_rows=(),
        provenance_item_ids=("source",),
    ))
    assert report.verified
    assert not report.recomputation_passed
    assert report.execution_verified
    assert not report.recomputation_evaluated


def test_generic_analysis_pack_declares_controller_selected_validator_order() -> None:
    registry = CapabilityRegistry()
    register_generic_adaptive_analysis_capabilities(
        registry,
        analysis_validator_ids=("formal_analysis", "generic_analysis"),
    )

    assert registry.get("execute_analysis_dsl_v2").validator_ids == (
        "formal_analysis", "generic_analysis",
    )
    assert registry.get("execute_bounded_python_v2").validator_ids == (
        "formal_analysis", "generic_analysis",
    )


def test_formal_validator_does_not_claim_recomputation_for_intermediate_schema() -> None:
    case = next(case for case in _cases() if case.operation == "compute_delta")
    validator = build_formal_quality_validator(case)
    report = validator(CapabilityQualityContext(
        capability_id=case.capability_id,
        validator_id="formal_analysis",
        input_rows=(case.source_rows,),
        output_rows=({"intermediate_value": 1.0},),
        input_artifact_hashes=("source-hash",),
        output_artifact_hash="output-hash",
        required_fields=("intermediate_value",),
        completion_criteria={"min_rows": 1},
        provenance_item_ids=("formal-source",),
    ))

    assert report.verified
    assert not report.recomputation_evaluated
    assert not report.recomputation_passed
    assert report.semantic_verification_status == "not_evaluated"


def test_generic_capability_surface_accepts_controller_compiled_plan() -> None:
    registry = CapabilityRegistry()
    register_generic_adaptive_analysis_capabilities(registry)
    source_ref = "formal-source:test"
    envelope = AdaptiveTaskEnvelope(
        task_id="test",
        canonical_task_spec_hash="spec",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="generic_adaptive_analysis_v2",
        allowed_capability_ids=(
            "retrieve_semantic_evidence_v1",
            "retrieve_table_evidence_v1",
            "execute_bounded_python_v2",
            "compose_claim_set_v2",
            "compose_risk_memo_v1",
        ),
        allowed_output_contracts=(
            "statebus.evidence_pack.v2",
            "statebus.analysis_result.v2",
            "statebus.cited_report.v1",
        ),
        risk_class=RiskClass.BOUNDED_CODE,
        allow_llm_python=True,
        max_plan_steps=4,
        max_execution_runtime_ms=200_000,
    )
    proposal = PlanProposal(
        proposal_id="compiled",
        task_id="test",
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
                PlanStepProposal(
                    "retrieve-evidence", "retriever", "retrieve_table_evidence_v1", "find table",
                    output_contract_version="statebus.evidence_pack.v2",
                ),
            PlanStepProposal(
                "execute-analysis", "executor", "execute_bounded_python_v2", "answer the task",
                input_ref_ids=(source_ref,), input_ref_kinds=("execution_artifact",),
                output_contract_version="statebus.analysis_result.v2",
                    completion_criteria={"min_rows": 1},
            ),
            PlanStepProposal(
                "compose-report", "summarizer", "compose_claim_set_v2", "cite the answer",
                depends_on=("retrieve-evidence", "execute-analysis"),
                output_contract_version="statebus.cited_report.v1",
                completion_criteria={"min_locator_count": 1},
            ),
        ),
    )
    outcome = PlanPolicyValidator(registry, allow_llm_python=True).validate(
        proposal,
        envelope,
        available_input_refs={source_ref: "execution_artifact"},
    )
    assert outcome.approved_plan is not None, outcome.report.canonical_payload()


def test_generic_python_capability_requires_verified_execution_artifact() -> None:
    registry = CapabilityRegistry()
    register_generic_adaptive_analysis_capabilities(registry)

    descriptor = registry.get("execute_bounded_python_v2")

    assert descriptor.input_ref_kinds == ("execution_artifact", "canonical_evidence_pack")
    assert descriptor.required_input_ref_kinds == ("execution_artifact",)


def test_controller_compiler_preserves_model_execution_choice_without_case_operation() -> None:
    case = _cases()[0]
    raw = PlanProposal(
        proposal_id="model",
        task_id=case.task_id,
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                "model-retrieve", "retriever", "retrieve_table_evidence_v1", "prefer cited tables",
                depends_on=("model-retrieve",),
            ),
            PlanStepProposal(
                "model-execute", "executor", "execute_analysis_dsl_v2", "use a declarative analysis",
                depends_on=("model-execute",),
                completion_criteria={"min_rows": 2},
            ),
            PlanStepProposal(
                "model-report", "summarizer", "compose_claim_set_v2", "write cited claims",
            ),
        ),
    )
    compiled, fields = _compile_formal_controller_wiring(case, raw)
    retriever, executor, summarizer = compiled.steps
    assert executor.capability_id == "execute_analysis_dsl_v2"
    assert executor.goal.endswith("Analysis strategy: use a declarative analysis")
    assert executor.input_ref_ids == (case.source_ref_id,)
    assert tuple(executor.completion_criteria["required_fields"]) == tuple(case.output_schema)
    assert executor.completion_criteria["min_rows"] == 1
    assert any(field.endswith("completion_criteria.min_rows.controller_owned") for field in fields)
    assert retriever.depends_on == ()
    assert summarizer.depends_on == ("retrieve-evidence", "execute-analysis")
    assert fields


def test_formal_planner_reports_duplicate_summarizer_as_repairable_contract_error() -> None:
    case = _cases()[0]
    legal = PlanProposal(
        proposal_id="duplicate-summarizer",
        task_id=case.task_id,
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal("retrieve", "retriever", "retrieve_table_evidence_v1", "retrieve"),
            PlanStepProposal("execute", "executor", "execute_bounded_python_v2", "analyze"),
            PlanStepProposal(
                "report-a", "summarizer", "compose_claim_set_v2", "report",
                depends_on=("retrieve", "execute"),
            ),
            PlanStepProposal(
                "report-b", "summarizer", "compose_risk_memo_v1", "report again",
                depends_on=("retrieve", "execute"),
            ),
        ),
    )

    errors = _model_plan_errors(case, legal)

    assert "formal_planner_requires_one_summarizer" in errors


def test_resolved_raw_wiring_error_does_not_trigger_planner_repair() -> None:
    context, unresolved = _partition_planner_repair_errors(
        raw_structural_errors=("formal_planner_summarizer_dependencies_incomplete",),
        effective_structural_errors=(),
        controller_errors=(),
        policy_errors=(),
    )

    assert context == ("formal_planner_summarizer_dependencies_incomplete",)
    assert unresolved == ()

    _, unresolved = _partition_planner_repair_errors(
        raw_structural_errors=(),
        effective_structural_errors=("formal_planner_requires_one_retriever",),
        controller_errors=("controller_wiring_not_compilable_role_graph",),
        policy_errors=("role_cardinality_violation",),
    )
    assert unresolved == (
        "formal_planner_requires_one_retriever",
        "controller_wiring_not_compilable_role_graph",
        "role_cardinality_violation",
    )


def test_controller_compiler_does_not_treat_retriever_output_as_python_artifact() -> None:
    case = next(case for case in _cases() if case.operation == "compute_delta")
    raw = PlanProposal(
        proposal_id="model-retriever-input",
        task_id=case.task_id,
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                "retrieve", "retriever", "retrieve_table_evidence_v1", "retrieve cited table evidence",
            ),
            PlanStepProposal(
                "analyze", "executor", "execute_bounded_python_v2", "compute the requested delta",
                depends_on=("retrieve",), input_ref_ids=("retrieve",),
                input_ref_kinds=("canonical_evidence_pack",),
                completion_criteria={"min_rows": 1, "required_fields": tuple(case.output_schema)},
            ),
            PlanStepProposal(
                "report", "summarizer", "compose_risk_memo_v1", "write cited claims",
                depends_on=("retrieve", "analyze"),
            ),
        ),
    )

    compiled, errors = _compile_formal_controller_wiring(case, raw)

    assert not any(item.startswith("formal_planner_") for item in errors)
    executor = compiled.steps[1]
    assert executor.depends_on == ("retrieve-evidence",)
    assert executor.input_ref_ids == (case.source_ref_id,)
    assert executor.input_ref_kinds == ("execution_artifact",)

    registry = CapabilityRegistry()
    pack = register_generic_adaptive_analysis_capabilities(registry)
    envelope = AdaptiveTaskEnvelope(
        task_id=case.task_id,
        canonical_task_spec_hash=sha256_digest(case.spec.canonical_payload()),
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id=pack.pack_id,
        allowed_capability_ids=pack.capability_ids,
        allowed_output_contracts=(
            "statebus.evidence_pack.v2", "statebus.analysis_result.v2", "statebus.cited_report.v1",
        ),
        risk_class=RiskClass.BOUNDED_CODE,
        allow_llm_python=True,
        max_execution_runtime_ms=200_000,
    )
    outcome = PlanPolicyValidator(registry, allow_llm_python=True).validate(
        compiled,
        envelope,
        available_input_refs={case.source_ref_id: "execution_artifact"},
    )
    assert outcome.approved_plan is not None, outcome.report.canonical_payload()


def test_controller_compiler_preserves_multi_executor_source_and_upstream_edges() -> None:
    case = next(case for case in _cases() if case.operation == "detect_outliers")
    raw = PlanProposal(
        proposal_id="model-multi-stage",
        task_id=case.task_id,
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                "retrieve", "retriever", "retrieve_table_evidence_v1", "retrieve cited table evidence",
            ),
            PlanStepProposal(
                "detect", "executor", "execute_bounded_python_v2", "detect outliers",
                depends_on=("retrieve",), input_ref_ids=(case.source_ref_id,),
                input_ref_kinds=("execution_artifact",), completion_criteria={"min_rows": 1},
            ),
            PlanStepProposal(
                "compare", "executor", "execute_bounded_python_v2", "compare filtered and unfiltered means",
                depends_on=("detect",), input_ref_ids=(case.source_ref_id,),
                input_ref_kinds=("execution_artifact",), completion_criteria={"min_rows": 1},
            ),
            PlanStepProposal(
                "report", "summarizer", "compose_claim_set_v2", "write cited claims",
                depends_on=("retrieve", "compare"),
            ),
        ),
    )

    compiled, errors = _compile_formal_controller_wiring(case, raw)

    assert not any(item.startswith("formal_planner_") for item in errors)
    first, second = compiled.steps[1:3]
    assert first.input_ref_ids == (case.source_ref_id,)
    assert first.depends_on == ("retrieve-evidence",)
    assert second.input_ref_ids == ()
    assert second.depends_on == ("retrieve-evidence", "execute-analysis")
    assert compiled.steps[-1].depends_on == (
        "retrieve-evidence", "execute-analysis", "execute-analysis-2",
    )


def test_controller_compiler_does_not_invent_replan_action() -> None:
    case = _cases()[0]
    raw = PlanProposal(
        proposal_id="model-no-replan",
        task_id=case.task_id,
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                "model-retrieve", "retriever", "retrieve_table_evidence_v1", "prefer cited tables",
            ),
            PlanStepProposal(
                "model-execute", "executor", "execute_analysis_dsl_v2", "use a declarative analysis",
            ),
            PlanStepProposal(
                "model-report", "summarizer", "compose_claim_set_v2", "write cited claims",
            ),
        ),
    )
    compiled, _ = _compile_formal_controller_wiring(case, raw, allow_replan=False)

    assert compiled.steps[0].on_failure == "fail"

    registry = CapabilityRegistry()
    pack = register_generic_adaptive_analysis_capabilities(registry)
    envelope = AdaptiveTaskEnvelope(
        task_id=case.task_id,
        canonical_task_spec_hash=sha256_digest(case.spec.canonical_payload()),
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="generic_adaptive_analysis_v2",
        allowed_capability_ids=pack.capability_ids,
        allowed_output_contracts=("statebus.evidence_pack.v2", "statebus.analysis_result.v2", "statebus.cited_report.v1"),
        risk_class=RiskClass.BOUNDED_CODE,
        allow_llm_python=True,
        max_replans=0,
        max_execution_runtime_ms=200_000,
    )
    outcome = PlanPolicyValidator(registry, allow_llm_python=True).validate(
        compiled,
        envelope,
        available_input_refs={case.source_ref_id: "execution_artifact"},
    )
    assert outcome.approved_plan is not None, outcome.report.canonical_payload()


def test_generic_required_fields_allow_unregistered_column_names() -> None:
    registry = CapabilityRegistry()
    register_generic_adaptive_analysis_capabilities(registry)
    descriptor = registry.get("execute_bounded_python_v2")
    contract = descriptor.completion_criteria_contract["required_fields"]
    assert contract == {
        "type": "string_list", "min_items": 1, "max_items": 64,
    }
    assert PlanPolicyValidator._criterion_matches_contract(
        ["quarter", "revenue"], contract
    )


def test_formal_failure_classification_separates_model_policy_sandbox_and_runtime() -> None:
    assert _classify_failure("external_expected_facts_quality_failed", stage="executor") == "model_quality"
    assert _classify_failure("formal_planner_policy_rejected:dependency_cycle", stage="planner") == "policy_rejection"
    assert _classify_failure("bwrap_not_ready:namespace_denied", stage="executor") == "sandbox_infrastructure"
    assert _classify_failure("artifact_blob_hash_mismatch", stage="executor") == "runtime_bug"


def test_case_gate_failure_attributes_external_quality_to_executor_model() -> None:
    failure = _case_gate_failure({
        "task_id": "formal-case",
        "runtime_completed": True,
        "runtime_dispatches": [],
        "approved_steps": [],
        "provenance_expected_facts": {"passed": True},
        "expected_facts_report": {"passed": False},
        "claim_sets": [{"status": "ready"}],
    })

    assert failure["category"] == "model_quality"
    assert failure["stage"] == "executor"
    assert failure["system_gate_failed"] is False


def test_terminal_quality_gate_accepts_verified_repair_and_retains_rejected_history() -> None:
    rejected = {
        "output_artifact_hash": "rejected-output",
        "verified": False,
        "error_codes": ["formal_recomputation_mismatch"],
    }
    repaired = {
        "output_artifact_hash": "accepted-output",
        "verified": True,
        "error_codes": [],
    }
    history = [rejected, repaired]

    terminal = _terminal_quality_reports(
        history,
        output_artifact_hash="accepted-output",
    )
    checks = _case_system_gate_checks({
        "ok": True,
        "runtime_completed": True,
        "claim_sets": [{"status": "ready"}],
        "quality_reports": history,
        "terminal_quality_reports": terminal,
        "execution_output_artifact_hash": "accepted-output",
        "telemetry": {},
        "execution_records": [],
        "runtime_dispatches": [],
        "benchmark_oracle_visible_to_roles": False,
    })

    assert history == [rejected, repaired]
    assert terminal == [repaired]
    assert checks["passing_case_refs_verified"] is True


def test_case_system_gate_rederives_terminal_quality_from_the_output_hash() -> None:
    rejected = {
        "output_artifact_hash": "accepted-output",
        "verified": False,
    }
    checks = _case_system_gate_checks({
        "ok": True,
        "runtime_completed": True,
        "claim_sets": [{"status": "ready"}],
        "quality_reports": [rejected],
        "terminal_quality_reports": [{
            "output_artifact_hash": "forged-output",
            "verified": True,
        }],
        "execution_output_artifact_hash": "accepted-output",
        "telemetry": {},
        "execution_records": [],
        "runtime_dispatches": [],
        "benchmark_oracle_visible_to_roles": False,
    })

    assert checks["passing_case_refs_verified"] is False


def test_case_gate_failure_attributes_terminal_quality_rejection_to_executor_model() -> None:
    rejected = {
        "output_artifact_hash": "terminal-output",
        "verified": False,
        "error_codes": ["formal_recomputation_mismatch"],
    }
    failure = _case_gate_failure({
        "task_id": "formal-quality-rejected",
        "runtime_completed": True,
        "runtime_dispatches": [],
        "approved_steps": [],
        "provenance_expected_facts": {"passed": True},
        "expected_facts_report": {"passed": True},
        "claim_sets": [{"status": "ready"}],
        "quality_reports": [rejected],
        "terminal_quality_reports": [rejected],
        "execution_output_artifact_hash": "terminal-output",
    })

    assert failure["error_code"] == "terminal_capability_quality_rejected"
    assert failure["category"] == "model_quality"
    assert failure["stage"] == "executor"
    assert failure["system_gate_failed"] is False


def test_high_accuracy_gate_keeps_policy_failures_in_the_full_denominator() -> None:
    cases = [{"system_gate_passed": True} for _ in range(20)]
    metrics = {
        "attempted_case_count": 25.0,
        "quality_pass_count": 20.0,
        "verified_execution_count": 20.0,
        "codeact_verified_count": 16.0,
        "codeact_execution_record_count": 16.0,
        "fallback_count": 0.0,
        "model_fallback_count": 0.0,
        "codeact_sandbox_fallback_count": 0.0,
    }
    failures = [
        {
            "lane": f"adaptive:case-{index}",
            "category": "policy_rejection",
            "stage": "planner",
        }
        for index in range(5)
    ]

    gates = _evaluate_formal_gates(
        lane="both",
        selected_case_count=25,
        full_registry=True,
        strict_ok=True,
        adaptive_cases=cases,
        adaptive_metrics=metrics,
        failures=failures,
        quality_threshold=0.80,
    )

    assert gates["system_safety_gate"] is True
    assert gates["quality_pass_rate"] == 0.80
    assert gates["high_accuracy_development_gate"] is True
    assert gates["all_cases_quality_gate"] is False
    assert gates["formal_enhancement_gate"] is False


def test_partial_dsl_diagnostic_does_not_misclassify_missing_codeact_coverage_as_unsafe() -> None:
    gates = _evaluate_formal_gates(
        lane="adaptive",
        selected_case_count=1,
        full_registry=False,
        strict_ok=True,
        adaptive_cases=[{"system_gate_passed": True}],
        adaptive_metrics={
            "attempted_case_count": 1.0,
            "quality_pass_count": 1.0,
            "verified_execution_count": 1.0,
            "codeact_verified_count": 0.0,
            "codeact_execution_record_count": 0.0,
            "fallback_count": 0.0,
            "model_fallback_count": 0.0,
            "codeact_sandbox_fallback_count": 0.0,
        },
        failures=[],
        quality_threshold=0.80,
    )

    assert gates["codeact_proof_present"] is False
    assert gates["codeact_proof_required"] is False
    assert gates["system_safety_gate"] is True
    assert gates["high_accuracy_development_gate"] is True


def test_high_accuracy_gate_never_masks_a_sandbox_or_runtime_failure() -> None:
    metrics = {
        "attempted_case_count": 25.0,
        "quality_pass_count": 25.0,
        "verified_execution_count": 25.0,
        "codeact_verified_count": 25.0,
        "codeact_execution_record_count": 25.0,
        "fallback_count": 0.0,
        "model_fallback_count": 0.0,
        "codeact_sandbox_fallback_count": 0.0,
    }
    gates = _evaluate_formal_gates(
        lane="both",
        selected_case_count=25,
        full_registry=True,
        strict_ok=True,
        adaptive_cases=[{"system_gate_passed": True} for _ in range(25)],
        adaptive_metrics=metrics,
        failures=[{
            "lane": "adaptive:case-1",
            "category": "sandbox_infrastructure",
            "stage": "executor",
        }],
        quality_threshold=0.80,
    )

    assert gates["system_safety_gate"] is False
    assert gates["high_accuracy_development_gate"] is False
    assert gates["formal_enhancement_gate"] is False
