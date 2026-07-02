from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from v2.contracts import (
    CanonicalTaskSpec,
    CompilerStatus,
    TaskCompilerInput,
    TaskCompilerResult,
    TaskMode,
)


@dataclass
class TaskCompiler:
    default_task_family: str = "financial_report_analysis"
    default_required_tools: tuple[str, ...] = ("table_retriever", "semantic_retriever")
    allowed_task_families: tuple[str, ...] = (
        "financial_report_analysis",
        "continuous_csv_table_analysis",
        "continuous_long_doc_table_analysis",
    )
    allowed_intent_ops: tuple[str, ...] = (
        "compare_metric",
        "summarize_risk",
        "generate_chart",
        "triage_route_tool",
        "profile_table",
        "aggregate_and_extreme",
        "correlate_columns",
        "detect_outliers",
        "materialize_clean_table",
        "profile_and_mean",
        "groupby_aggregate",
        "summarize_reuse_lineage",
        "build_semantic_index",
        "extract_metric_series",
        "extract_metric_series_generic",
        "extract_and_compute_metric_delta",
        "compare_metric_trends",
        "retrieve_narrative_evidence",
        "join_metrics_and_narrative",
        "draft_risk_memo",
        "final_cited_report",
    )
    allowed_required_outputs: tuple[str, ...] = (
        "summary_text",
        "metric_table",
        "plot_png",
        "summary_json",
        "schema_profile_ref",
        "missingness_summary",
        "stats_artifact_ref",
        "mean_cases",
        "max_deaths_country",
        "max_deaths_year",
        "correlation_artifact_ref",
        "correlation_coefficient",
        "outlier_artifact_ref",
        "mean_no_of_deaths_with_outliers",
        "mean_no_of_deaths_without_outliers",
        "cleaned_table_ref",
        "cleaned_row_count",
        "cleaning_policy_hash",
        "mean_windspeed",
        "monthly_avg_windspeed",
        "groupby_artifact_ref",
        "baro_outlier_count",
        "mean_wind_post",
        "mean_atmos_temp_post",
        "reuse_report_ref",
        "reused_artifact_count",
        "reused_strategy_count",
        "semantic_state_ref",
        "metric_table_ref",
        "entity_index_ref",
        "metric_row_count",
        "semantic_state_ref_present",
        "metric_series_ref",
        "metric_name",
        "value_q1",
        "value_q2",
        "value_q3",
        "revenue_q1",
        "revenue_q2",
        "revenue_q3",
        "gross_margin_q1",
        "gross_margin_q2",
        "gross_margin_q3",
        "operating_expense_q1",
        "operating_expense_q3",
        "expense_growth_q1_to_q3",
        "trend_artifact_ref",
        "revenue_delta_q1_to_q3",
        "gross_margin_delta_q1_to_q3",
        "evidence_pack_ref",
        "churn_driver",
        "churn_delta_note",
        "delivery_decline_q1_to_q3",
        "mitigation_action",
        "joined_evidence_ref",
        "primary_explanation",
        "required_citations",
        "risk_memo_ref",
        "risk_count",
        "action_count",
        "final_report_ref",
        "citation_count",
    )
    allowed_required_tools: tuple[str, ...] = (
        "table_retriever",
        "semantic_retriever",
        "table_extractor",
        "csv_profiler",
        "codeact_executor",
        "artifact_writer",
        "artifact_reader",
        "summarizer",
    )

    def compile(self, compiler_input: TaskCompilerInput) -> TaskCompilerResult:
        if compiler_input.task_mode == TaskMode.BENCHMARK_STRICT:
            if compiler_input.precompiled_canonical_task_spec is None:
                return TaskCompilerResult(
                    status=CompilerStatus.REJECTED,
                    canonical_task_spec=None,
                    compiler_errors=("benchmark_strict_requires_precompiled_canonical_spec",),
                )
            try:
                validated = self._validate_precompiled_spec(compiler_input.precompiled_canonical_task_spec)
            except ValueError as exc:
                return TaskCompilerResult(
                    status=CompilerStatus.REJECTED,
                    canonical_task_spec=None,
                    compiler_errors=(str(exc),),
                )
            return TaskCompilerResult(
                status=CompilerStatus.COMPILED,
                canonical_task_spec=validated,
            )

        parsed = self._try_parse_spec_json(compiler_input.request_text)
        if parsed is not None:
            try:
                return TaskCompilerResult(
                    status=CompilerStatus.COMPILED,
                    canonical_task_spec=self._canonical_from_mapping(
                        parsed,
                        strict=False,
                    ),
                )
            except ValueError as exc:
                return TaskCompilerResult(
                    status=CompilerStatus.OPAQUE_FREEFORM,
                    canonical_task_spec=None,
                    compiler_warnings=("interactive_fallback_to_opaque_freeform",),
                    compiler_errors=(str(exc),),
                )
        heuristic = self._heuristic_compile(compiler_input)
        if heuristic is None:
            return TaskCompilerResult(
                status=CompilerStatus.OPAQUE_FREEFORM,
                canonical_task_spec=None,
                compiler_warnings=("interactive_fallback_to_opaque_freeform",),
            )
        return TaskCompilerResult(
            status=CompilerStatus.COMPILED,
            canonical_task_spec=heuristic,
            compiler_warnings=("interactive_heuristic_compile",),
        )

    def _try_parse_spec_json(self, request_text: str) -> dict[str, Any] | None:
        request_text = request_text.strip()
        if not request_text.startswith("{"):
            return None
        try:
            parsed = json.loads(request_text)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        if "task_family" not in parsed or "intent_op" not in parsed:
            return None
        return parsed

    def _canonical_from_mapping(
        self,
        mapping: dict[str, Any],
        *,
        strict: bool = False,
    ) -> CanonicalTaskSpec:
        task_family = str(mapping.get("task_family", self.default_task_family)).strip()
        intent_op = str(mapping.get("intent_op", "opaque_intent")).strip()
        target_entities = tuple(str(item).strip() for item in mapping.get("target_entities", []) if str(item).strip())
        time_scope = str(mapping.get("time_scope", "")).strip()
        required_outputs = tuple(str(item).strip() for item in mapping.get("required_outputs", []) if str(item).strip())
        required_tools = tuple(
            str(item).strip() for item in mapping.get("required_tools", self.default_required_tools) if str(item).strip()
        )
        arguments = mapping.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("canonical_task_spec_arguments_must_be_mapping")
        if strict:
            self._validate_enum_members(
                field_name="task_family",
                values=(task_family,),
                allowed_values=self.allowed_task_families,
            )
            self._validate_enum_members(
                field_name="intent_op",
                values=(intent_op,),
                allowed_values=self.allowed_intent_ops,
            )
            self._validate_enum_members(
                field_name="required_outputs",
                values=required_outputs,
                allowed_values=self.allowed_required_outputs,
            )
            self._validate_enum_members(
                field_name="required_tools",
                values=required_tools,
                allowed_values=self.allowed_required_tools,
            )
            if not required_outputs:
                raise ValueError("canonical_task_spec_missing_required_outputs")
        return CanonicalTaskSpec(
            task_family=task_family,
            intent_op=intent_op,
            target_entities=target_entities,
            time_scope=time_scope,
            required_outputs=required_outputs,
            required_tools=required_tools,
            arguments=dict(arguments),
        )

    def _validate_precompiled_spec(self, spec: CanonicalTaskSpec) -> CanonicalTaskSpec:
        self._validate_enum_members(
            field_name="task_family",
            values=(spec.task_family,),
            allowed_values=self.allowed_task_families,
        )
        self._validate_enum_members(
            field_name="intent_op",
            values=(spec.intent_op,),
            allowed_values=self.allowed_intent_ops,
        )
        self._validate_enum_members(
            field_name="required_outputs",
            values=spec.required_outputs,
            allowed_values=self.allowed_required_outputs,
        )
        self._validate_enum_members(
            field_name="required_tools",
            values=spec.required_tools or self.default_required_tools,
            allowed_values=self.allowed_required_tools,
        )
        if not spec.required_outputs:
            raise ValueError("canonical_task_spec_missing_required_outputs")
        if not isinstance(spec.arguments, dict):
            raise ValueError("canonical_task_spec_arguments_must_be_mapping")
        return CanonicalTaskSpec(
            task_family=spec.task_family,
            intent_op=spec.intent_op,
            target_entities=tuple(spec.target_entities),
            time_scope=spec.time_scope,
            required_outputs=tuple(spec.required_outputs),
            required_tools=tuple(spec.required_tools),
            arguments=dict(spec.arguments),
            schema_version=spec.schema_version,
        )

    def _heuristic_compile(self, compiler_input: TaskCompilerInput) -> CanonicalTaskSpec | None:
        request_text = compiler_input.request_text.strip()
        if not request_text:
            return None
        lowered = request_text.lower()
        intent_op = "summarize_risk"
        if "compare" in lowered:
            intent_op = "compare_metric"
        elif "chart" in lowered or "plot" in lowered:
            intent_op = "generate_chart"
        target_entities = tuple(
            token.strip(",. ")
            for token in request_text.split()
            if token[:1].isupper() and len(token.strip(",. ")) > 1
        )[:3]
        required_outputs = (
            tuple(compiler_input.requested_outputs)
            if compiler_input.requested_outputs
            else ("summary_text",)
        )
        return CanonicalTaskSpec(
            task_family=compiler_input.corpus_family or self.default_task_family,
            intent_op=intent_op,
            target_entities=target_entities,
            required_outputs=required_outputs,
            required_tools=self.default_required_tools,
            arguments={"request_text": request_text},
        )

    @staticmethod
    def _validate_enum_members(
        *,
        field_name: str,
        values: tuple[str, ...],
        allowed_values: tuple[str, ...],
    ) -> None:
        invalid = [value for value in values if value not in allowed_values]
        if invalid:
            raise ValueError(
                f"canonical_task_spec_invalid_{field_name}:{','.join(sorted(dict.fromkeys(invalid)))}"
            )
