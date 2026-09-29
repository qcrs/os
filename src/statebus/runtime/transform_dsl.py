from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import ceil, isfinite
from pathlib import Path
import time
from typing import Any, Callable

from statebus.contracts import CapabilityGrant, CapabilityQualityReport, TransformProgram, TransformStep
from statebus.refs import ExecutionArtifactRef
from statebus.runtime.workspace import ArtifactLifecycleManager
from statebus.utils import sha256_digest, stable_json_dumps


class TransformProgramError(ValueError):
    pass


_ALLOWED_OPS = {
    "select", "rename", "filter_eq", "filter_contains", "filter_in", "filter_range", "sort", "limit",
    "group_by", "aggregate", "aggregate_grouped", "derive_safe", "compare_periods", "compare_metric", "join_by_key",
    "trend_series", "rank", "percentile_nearest_rank", "anomaly_check", "anomaly_zscore",
    "project_claim_fields", "deterministic_fixture",
}
_FORBIDDEN_FIELD_TOKENS = {"__", "/", "\\", ".."}
_FORBIDDEN_VALUE_TOKENS = _FORBIDDEN_FIELD_TOKENS | {"eval", "exec", "lambda", "import", "shell"}


@dataclass(frozen=True)
class TransformValidationReport:
    ok: bool
    error_code: str = ""
    operation_index: int = -1


@dataclass(frozen=True)
class TransformArtifactResult:
    rows: tuple[dict[str, Any], ...]
    artifact: ExecutionArtifactRef
    output_hash: str


class TransformProgramValidator:
    def __init__(
        self,
        *,
        max_operations: int = 12,
        max_rows: int = 10_000,
        max_join_rows: int = 20_000,
        max_columns: int = 128,
        max_output_bytes: int = 1_048_576,
        allow_deterministic_fixture: bool = False,
    ) -> None:
        self.max_operations = max_operations
        self.max_rows = max_rows
        self.max_join_rows = max_join_rows
        self.max_columns = max_columns
        self.max_output_bytes = max_output_bytes
        self.allow_deterministic_fixture = allow_deterministic_fixture

    def validate(
        self,
        program: TransformProgram,
        *,
        authorized_input_refs: tuple[str, ...],
        available_columns: dict[str, tuple[str, ...]],
    ) -> TransformValidationReport:
        if program.schema_version != "statebus.transform_program.v1":
            return TransformValidationReport(False, "invalid_schema_version")
        if not program.input_artifact_refs or any(ref not in authorized_input_refs for ref in program.input_artifact_refs):
            return TransformValidationReport(False, "unauthorized_input_ref")
        if len(program.operations) == 0 or len(program.operations) > self.max_operations:
            return TransformValidationReport(False, "operation_budget_exceeded")
        if any(len(columns) > self.max_columns for columns in available_columns.values()):
            return TransformValidationReport(False, "input_column_budget_exceeded")
        known_columns = set(available_columns.get(program.input_artifact_refs[0], ()))
        if len(known_columns) > self.max_columns:
            return TransformValidationReport(False, "input_column_budget_exceeded")
        for index, step in enumerate(program.operations):
            if step.op not in _ALLOWED_OPS:
                return TransformValidationReport(False, "unknown_operation", index)
            if step.op == "deterministic_fixture":
                if not self.allow_deterministic_fixture:
                    return TransformValidationReport(False, "deterministic_fixture_not_allowed", index)
                fixture_id = step.arguments.get("fixture_id")
                if not isinstance(fixture_id, str) or not fixture_id:
                    return TransformValidationReport(False, "missing_fixture_id", index)
                if set(step.arguments) != {"fixture_id"}:
                    return TransformValidationReport(False, "invalid_fixture_arguments", index)
            invalid = self._validate_arguments(step, known_columns, program.input_artifact_refs, available_columns)
            if invalid:
                return TransformValidationReport(False, invalid, index)
            known_columns = self._output_columns(step, known_columns, available_columns)
            if len(known_columns) > self.max_columns:
                return TransformValidationReport(False, "output_column_budget_exceeded", index)
        return TransformValidationReport(True)

    @staticmethod
    def _output_columns(
        step: TransformStep,
        known_columns: set[str],
        available_columns: dict[str, tuple[str, ...]],
    ) -> set[str]:
        args = step.arguments
        if step.op in {"select", "project_claim_fields"}:
            return {str(column) for column in args.get("columns", ())}
        if step.op == "rename":
            source = str(args.get("source", ""))
            target = str(args.get("target", ""))
            return {*known_columns - {source}, target}
        if step.op == "aggregate":
            function = str(args.get("function", ""))
            column = str(args.get("column", ""))
            return {str(args.get("output", f"{function}_{column}"))}
        if step.op == "aggregate_grouped":
            if "group_fields" in args:
                return {*args["group_fields"], *args["outputs"]}
            group_field = str(args.get("group_field", ""))
            return {
                str(args.get("group_output", group_field)),
                str(args.get("sum_output", "sum")),
                str(args.get("mean_output", "mean")),
                str(args.get("min_output", "min")),
                str(args.get("max_output", "max")),
                str(args.get("count_output", "count")),
            }
        if step.op == "derive_safe":
            if "calculations" in args:
                return {*known_columns, *(item[0] for item in args["calculations"])}
            return {*known_columns, str(args.get("output", ""))}
        if step.op == "compare_periods":
            return {
                *(str(field) for field in args.get("group_fields", ())),
                *(str(field) for field in args.get("carry_fields", ())),
                str(args.get("baseline_period_output", "baseline_period")),
                str(args.get("comparison_period_output", "comparison_period")),
                str(args.get("baseline_value_output", "baseline_value")),
                str(args.get("comparison_value_output", "comparison_value")),
                str(args.get("difference_output", "difference")),
                str(args.get("ratio_output", "ratio")),
                str(args.get("growth_pct_output", "growth_pct")),
            }
        if step.op == "compare_metric":
            return {
                str(args.get("period_output", "quarter")),
                str(args.get("left_output", "acme_revenue_value")),
                str(args.get("right_output", "beta_revenue_value")),
                str(args.get("gap_output", "gap_value")),
            }
        if step.op == "trend_series":
            return {
                str(args.get("ticker_output", "ticker")),
                str(args.get("period_output", "period")),
                str(args.get("value_output", "metric_value")),
                str(args.get("direction_output", "trend_direction")),
            }
        if step.op == "rank":
            return {*known_columns, str(args.get("output", "rank"))}
        if step.op == "percentile_nearest_rank":
            outputs = {*args.get("group_fields", ()), args["output"]}
            if "sample_count_output" in args:
                outputs.add(args["sample_count_output"])
            return outputs
        if step.op == "join_by_key":
            right_ref = str(args.get("right_ref", ""))
            prefix = str(args.get("right_prefix", ""))
            return {*known_columns, *(prefix + field for field in available_columns.get(right_ref, ()))}
        if step.op == "anomaly_check":
            return {*known_columns, str(args.get("output", "is_anomaly"))}
        if step.op == "anomaly_zscore":
            return {
                str(args.get("period_field", "")),
                str(args.get("value_field", "")),
                str(args.get("baseline_output", "baseline_mean")),
                str(args.get("threshold_output", "threshold")),
                str(args.get("flag_output", "is_anomaly")),
            }
        return set(known_columns)

    def _validate_arguments(
        self,
        step: TransformStep,
        known_columns: set[str],
        authorized_refs: tuple[str, ...],
        available_columns: dict[str, tuple[str, ...]],
    ) -> str:
        for key, value in step.arguments.items():
            if "path" in key.lower() or "file" in key.lower() or "expr" in key.lower() or "python" in key.lower():
                return "unsafe_argument_key"
            if not self._safe_argument_value(value):
                return "unsafe_argument_value"
        columns: list[str] = []
        for key in (
            "column", "columns", "group_by", "group_field", "period_field", "value_field",
            "ticker_field", "metric_field", "left_key", "left_keys", "numerator", "denominator",
            "source", "carry_fields", "tie_break_columns", "group_fields", "value_fields",
        ):
            value = step.arguments.get(key)
            if isinstance(value, str):
                columns.append(value)
            elif isinstance(value, (tuple, list)):
                columns.extend(str(item) for item in value)
        if any(column not in known_columns for column in columns):
            return "unknown_column"
        if len(columns) > self.max_columns:
            return "column_budget_exceeded"
        if step.op in {"select", "project_claim_fields", "group_by"} and not isinstance(step.arguments.get("columns"), (tuple, list)):
            return "missing_columns"
        if step.op == "rename":
            source = step.arguments.get("source")
            target = step.arguments.get("target")
            if not isinstance(source, str) or not isinstance(target, str) or not source or not target:
                return "missing_rename_fields"
            if source == target:
                return "rename_source_target_same"
            if target in known_columns:
                return "rename_target_exists"
        if step.op in {"filter_eq", "filter_contains", "filter_in", "filter_range", "aggregate", "anomaly_check"} and not isinstance(step.arguments.get("column"), str):
            return "missing_column"
        if step.op == "sort" and not isinstance(step.arguments.get("columns", step.arguments.get("column")), (tuple, list, str)):
            return "missing_sort_column"
        if step.op == "limit" and not isinstance(step.arguments.get("count"), int):
            return "invalid_limit"
        if step.op == "limit" and not 0 <= int(step.arguments["count"]) <= self.max_rows:
            return "limit_exceeded"
        if step.op == "aggregate" and step.arguments.get("function") not in {"count", "sum", "mean", "min", "max"}:
            return "invalid_aggregate"
        if step.op == "aggregate_grouped":
            error = self._validate_grouped_aggregate(step.arguments)
            if error:
                return error
        if step.op == "compare_periods" and not {"period_field", "value_field"} <= set(step.arguments):
            return "missing_comparison_fields"
        if step.op == "compare_periods":
            carry_fields = step.arguments.get("carry_fields", ())
            if not isinstance(carry_fields, (tuple, list)):
                return "invalid_comparison_carry_fields"
            carry_names = tuple(str(field) for field in carry_fields)
            if len(carry_names) != len(set(carry_names)):
                return "duplicate_comparison_carry_field"
            groups = step.arguments.get("group_fields", ())
            if not self._field_list(groups):
                return "invalid_comparison_group_fields"
            output_names = (
                str(step.arguments.get("baseline_period_output", "baseline_period")),
                str(step.arguments.get("comparison_period_output", "comparison_period")),
                str(step.arguments.get("baseline_value_output", "baseline_value")),
                str(step.arguments.get("comparison_value_output", "comparison_value")),
                str(step.arguments.get("difference_output", "difference")),
                str(step.arguments.get("ratio_output", "ratio")),
                str(step.arguments.get("growth_pct_output", "growth_pct")),
            )
            if any(not name for name in output_names) or len(set(output_names)) != len(output_names):
                return "comparison_output_collision"
            if (set(carry_names) | set(groups)) & set(output_names):
                return "comparison_output_collision"
        if step.op == "compare_metric":
            required = {
                "ticker_field",
                "period_field",
                "metric_field",
                "value_field",
                "left_ticker",
                "right_ticker",
                "period",
                "metric",
                "period_output",
                "left_output",
                "right_output",
                "gap_output",
            }
            if not required <= set(step.arguments):
                return "missing_compare_metric_fields"
            if step.arguments.get("left_ticker") == step.arguments.get("right_ticker"):
                return "compare_metric_tickers_must_differ"
            if not all(
                isinstance(step.arguments.get(field), str)
                and bool(str(step.arguments.get(field)).strip())
                for field in (
                    "left_ticker",
                    "right_ticker",
                    "period",
                    "metric",
                    "period_output",
                    "left_output",
                    "right_output",
                    "gap_output",
                )
            ):
                return "invalid_compare_metric_fields"
            output_names = tuple(
                str(step.arguments[name])
                for name in ("period_output", "left_output", "right_output", "gap_output")
            )
            if len(output_names) != len(set(output_names)):
                return "invalid_compare_metric_outputs"
        if step.op == "trend_series":
            required = {
                "ticker_field",
                "period_field",
                "metric_field",
                "value_field",
                "tickers",
                "periods",
                "metric",
                "ticker_output",
                "period_output",
                "value_output",
                "direction_output",
            }
            if not required <= set(step.arguments):
                return "missing_trend_fields"
            tickers = step.arguments.get("tickers")
            periods = step.arguments.get("periods")
            if (
                not isinstance(tickers, (tuple, list))
                or not tickers
                or any(not isinstance(item, str) or not item for item in tickers)
            ):
                return "invalid_trend_tickers"
            if (
                not isinstance(periods, (tuple, list))
                or len(periods) < 2
                or any(not isinstance(item, str) or not item for item in periods)
            ):
                return "invalid_trend_periods"
            if not isinstance(step.arguments.get("metric"), str) or not step.arguments["metric"]:
                return "invalid_trend_metric"
            output_names = tuple(
                str(step.arguments[name])
                for name in (
                    "ticker_output",
                    "period_output",
                    "value_output",
                    "direction_output",
                )
            )
            if any(not name for name in output_names) or len(output_names) != len(set(output_names)):
                return "invalid_trend_outputs"
        if step.op == "rank":
            metric = step.arguments.get("metric")
            output = step.arguments.get("output")
            tie_break = step.arguments.get("tie_break_columns", ())
            if not isinstance(metric, str) or not metric or not isinstance(output, str) or not output:
                return "missing_rank_fields"
            if metric not in known_columns:
                return "unknown_column"
            if not isinstance(tie_break, (tuple, list)) or any(not isinstance(item, str) for item in tie_break):
                return "invalid_rank_tie_break"
            if output in known_columns:
                return "rank_output_exists"
            if not isinstance(step.arguments.get("descending", False), bool):
                return "invalid_rank_direction"
            if step.arguments.get("method", "ordinal") != "ordinal":
                return "invalid_rank_method"
        if step.op == "percentile_nearest_rank":
            value_field = step.arguments.get("value_field")
            output = step.arguments.get("output")
            group_fields = step.arguments.get("group_fields", ())
            percentile = step.arguments.get("percentile")
            if not isinstance(value_field, str) or not value_field or not isinstance(output, str) or not output:
                return "missing_percentile_fields"
            if not self._field_list(group_fields):
                return "invalid_percentile_group_fields"
            if output in known_columns or output in group_fields:
                return "percentile_output_exists"
            if not isinstance(percentile, (int, float)) or isinstance(percentile, bool) or not 0 < float(percentile) <= 100:
                return "invalid_percentile"
            sample_output = step.arguments.get("sample_count_output")
            if "sample_count_output" in step.arguments and (
                not isinstance(sample_output, str) or not sample_output
                or sample_output in known_columns or sample_output == output
            ):
                return "percentile_sample_count_output_invalid"
        if step.op == "anomaly_zscore" and not {"period_field", "value_field"} <= set(step.arguments):
            return "missing_anomaly_fields"
        if step.op == "derive_safe":
            error = self._validate_derivations(step.arguments, known_columns)
            if error:
                return error
        if step.op == "join_by_key":
            if step.arguments.get("right_ref") not in authorized_refs:
                return "unauthorized_join_ref"
            error = self._validate_join(step.arguments, known_columns, available_columns)
            if error:
                return error
        return ""

    @staticmethod
    def _field_list(value: object, *, nonempty: bool = False) -> bool:
        return (
            isinstance(value, (list, tuple))
            and (bool(value) or not nonempty)
            and all(isinstance(item, str) and bool(item) for item in value)
            and len(value) == len(set(value))
        )

    @classmethod
    def _validate_grouped_aggregate(cls, args: dict[str, Any]) -> str:
        batch_keys = {"group_fields", "value_fields", "functions", "outputs"}
        if batch_keys & set(args):
            if set(args) != batch_keys or not cls._field_list(args.get("group_fields")):
                return "invalid_grouped_aggregate_arguments"
            values, functions, outputs = args.get("value_fields"), args.get("functions"), args.get("outputs")
            if not isinstance(values, (list, tuple)) or not values or any(not isinstance(v, str) or not v for v in values):
                return "invalid_aggregate_value_fields"
            if not isinstance(functions, (list, tuple)) or len(functions) != len(values):
                return "invalid_aggregate_functions"
            if any(not isinstance(function, str) or function not in {"sum", "mean", "min", "max", "count"} for function in functions):
                return "invalid_aggregate_functions"
            if not cls._field_list(outputs, nonempty=True) or len(outputs) != len(values):
                return "invalid_aggregate_outputs"
            if set(outputs) & set(args["group_fields"]):
                return "aggregate_output_collision"
            return ""
        if not isinstance(args.get("group_field"), str) or not args["group_field"]:
            return "missing_group_field"
        if not isinstance(args.get("value_field"), str) or not args["value_field"]:
            return "missing_value_field"
        outputs = [args.get("group_output", args["group_field"])] + [
            args.get(f"{function}_output", function) for function in ("sum", "mean", "min", "max", "count")
        ]
        if not cls._field_list(outputs, nonempty=True):
            return "aggregate_output_collision"
        return ""

    @staticmethod
    def _validate_derivations(args: dict[str, Any], known_columns: set[str]) -> str:
        if "calculations" in args:
            calculations = args["calculations"]
            if set(args) != {"calculations"} or not isinstance(calculations, (list, tuple)) or not calculations:
                return "invalid_derive_calculations"
        else:
            if not {"numerator", "denominator", "output", "kind"} <= set(args):
                return "missing_derive_fields"
            calculations = [[args["output"], args["kind"], args["numerator"], args["denominator"]]]
        visible = set(known_columns)
        for calculation in calculations:
            if not isinstance(calculation, (tuple, list)) or not 4 <= len(calculation) <= 6:
                return "invalid_derive_calculation"
            output, kind, left, right = calculation[:4]
            if not isinstance(output, str) or not output or output in visible:
                return "derive_output_collision"
            if not isinstance(kind, str) or kind not in {"difference", "ratio", "pct_change", "less_than", "greater_than", "boolean_change"}:
                return "invalid_derive_kind"
            if not isinstance(left, str) or left not in visible:
                return "unknown_column"
            if isinstance(right, str):
                if right not in visible:
                    return "unknown_column"
            elif kind == "boolean_change":
                if right is not None and not isinstance(right, bool):
                    return "invalid_derive_operand"
            elif not isinstance(right, (int, float)) or isinstance(right, bool) or not isfinite(float(right)):
                return "invalid_derive_operand"
            if len(calculation) > 4:
                scale = calculation[4]
                if kind in {"less_than", "greater_than", "boolean_change"}:
                    return "invalid_derive_numeric_format"
                if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not isfinite(float(scale)):
                    return "invalid_derive_scale"
            if len(calculation) > 5:
                decimals = calculation[5]
                if decimals is not None and (not isinstance(decimals, int) or isinstance(decimals, bool) or not 0 <= decimals <= 12):
                    return "invalid_derive_decimals"
            visible.add(output)
        return ""

    @classmethod
    def _validate_join(cls, args: dict[str, Any], known_columns: set[str], available_columns: dict[str, tuple[str, ...]]) -> str:
        if "left_keys" in args or "right_keys" in args:
            if "left_key" in args or "right_key" in args:
                return "invalid_join_keys"
            left_keys, right_keys = args.get("left_keys"), args.get("right_keys")
        else:
            left_keys, right_keys = [args.get("left_key")], [args.get("right_key")]
        if not cls._field_list(left_keys, nonempty=True) or not cls._field_list(right_keys, nonempty=True) or len(left_keys) != len(right_keys):
            return "invalid_join_keys"
        right_columns = set(available_columns.get(str(args["right_ref"]), ()))
        if not set(left_keys) <= known_columns or not set(right_keys) <= right_columns:
            return "unknown_column"
        prefix = args.get("right_prefix", "")
        if not isinstance(prefix, str):
            return "invalid_join_prefix"
        common_keys = {left for left, right in zip(left_keys, right_keys) if left == right and not prefix}
        if ({prefix + field for field in right_columns} & known_columns) - common_keys:
            return "join_output_collision"
        return ""

    @staticmethod
    def _safe_argument_value(value: object) -> bool:
        if value is None or isinstance(value, (bool, int, float)):
            return True
        if isinstance(value, str):
            lowered = value.lower()
            return len(value) <= 512 and not any(token in lowered for token in _FORBIDDEN_VALUE_TOKENS)
        if isinstance(value, (tuple, list)):
            return len(value) <= 128 and all(TransformProgramValidator._safe_argument_value(item) for item in value)
        # Nested mappings and arbitrary objects could encode an evaluator or path
        # surface. The first DSL intentionally has no operation that needs them.
        return False


class TransformDslInterpreter:
    def __init__(
        self,
        validator: TransformProgramValidator | None = None,
        *,
        deterministic_fixture_runner: Callable[[TransformStep, list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.deterministic_fixture_runner = deterministic_fixture_runner
        self.validator = validator or TransformProgramValidator(
            allow_deterministic_fixture=deterministic_fixture_runner is not None,
        )

    def run(self, program: TransformProgram, *, inputs: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        available_columns = {
            ref: tuple(sorted({key for row in rows for key in row}))
            for ref, rows in inputs.items()
        }
        report = self.validator.validate(
            program,
            authorized_input_refs=tuple(inputs),
            available_columns=available_columns,
        )
        if not report.ok:
            raise TransformProgramError(f"{report.error_code}:{report.operation_index}")
        rows = [dict(row) for row in inputs[program.input_artifact_refs[0]]]
        if len(rows) > self.validator.max_rows:
            raise TransformProgramError("input_row_budget_exceeded")
        for step in program.operations:
            try:
                rows = self._apply(rows, step, inputs)
            except TransformProgramError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise TransformProgramError(f"operation_type_error:{step.op}") from exc
            if len(rows) > self.validator.max_rows:
                raise TransformProgramError("output_row_budget_exceeded")
            if any(len(row) > self.validator.max_columns for row in rows):
                raise TransformProgramError("output_column_budget_exceeded")
        stable_rows = self._stable_rows(rows)
        encoded = stable_json_dumps(stable_rows).encode("utf-8")
        if len(encoded) > self.validator.max_output_bytes:
            raise TransformProgramError("output_byte_budget_exceeded")
        return stable_rows

    def run_verified(
        self,
        program: TransformProgram,
        *,
        inputs: dict[str, list[dict[str, Any]]],
        grant: CapabilityGrant,
        attempt_workspace: Path,
        output_schema: dict[str, str],
        quality_validator: Callable[[list[dict[str, Any]]], bool] | None = None,
        quality_report: CapabilityQualityReport | None = None,
    ) -> TransformArtifactResult:
        """Materialize the only permitted DSL output as a validated candidate."""
        if grant.expires_at_ns < time.time_ns():
            raise TransformProgramError("capability_grant_expired")
        if program.output_contract_version != grant.output_contract_version:
            raise TransformProgramError("grant_output_contract_mismatch")
        if not set(program.input_artifact_refs) <= set(grant.input_ref_ids):
            raise TransformProgramError("grant_input_ref_mismatch")
        rows = self.run(program, inputs=inputs)
        self._validate_output_rows(rows, output_schema)
        if quality_validator is not None and not bool(quality_validator(rows)):
            raise TransformProgramError("artifact_quality_validation_failed")
        if quality_report is not None and not quality_report.verified:
            raise TransformProgramError("artifact_quality_validation_failed")
        attempt_workspace.mkdir(parents=True, exist_ok=True)
        output_dir = attempt_workspace / "outputs"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / "transform_result.json"
        payload = stable_json_dumps(rows).encode("utf-8")
        if len(payload) > self.validator.max_output_bytes:
            raise TransformProgramError("output_byte_budget_exceeded")
        output_path.write_bytes(payload)
        output_hash = sha256_digest(payload)
        lifecycle = ArtifactLifecycleManager()
        candidate = lifecycle.register_candidate(ExecutionArtifactRef(
            artifact_id=f"dsl-{grant.task_id}-{grant.step_id}-{grant.attempt_id}",
            task_id=grant.task_id,
            step_id=grant.step_id,
            artifact_type="json",
            root_id=str(attempt_workspace),
            relpath=str(output_path.relative_to(attempt_workspace)),
            blob_hash=output_hash,
            size_bytes=len(payload),
            produced_by="executor",
            workspace_relpath=str(output_path.relative_to(attempt_workspace)),
            manifest_hash=program.program_hash,
            metadata={
                "schema_version": "statebus.transform_dsl_artifact.v1",
                "grant_hash": grant.grant_hash,
                "session_id": grant.session_id,
                "attempt_id": grant.attempt_id,
                "quality_report_hash": "" if quality_report is None else quality_report.report_hash,
            },
        ))
        return TransformArtifactResult(rows=tuple(rows), artifact=candidate, output_hash=output_hash)

    @staticmethod
    def _validate_output_rows(rows: list[dict[str, Any]], output_schema: dict[str, str]) -> None:
        if not output_schema:
            raise TransformProgramError("missing_output_schema")
        expected = set(output_schema)
        for row in rows:
            if set(row) != expected:
                raise TransformProgramError("output_schema_fields_mismatch")
            for key, kind in output_schema.items():
                value = row[key]
                if kind == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(float(value))):
                    raise TransformProgramError(f"output_schema_type:{key}")
                if kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                    raise TransformProgramError(f"output_schema_type:{key}")
                if kind == "string" and not isinstance(value, str):
                    raise TransformProgramError(f"output_schema_type:{key}")
                if kind == "boolean" and not isinstance(value, bool):
                    raise TransformProgramError(f"output_schema_type:{key}")

    def _apply(self, rows: list[dict[str, Any]], step: TransformStep, inputs: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        args = step.arguments
        if step.op in {"select", "project_claim_fields"}:
            columns = tuple(args["columns"])
            return [{column: row.get(column) for column in columns} for row in rows]
        if step.op == "rename":
            source = str(args["source"])
            target = str(args["target"])
            renamed_rows: list[dict[str, Any]] = []
            for row in rows:
                renamed = dict(row)
                renamed[target] = renamed.pop(source, None)
                renamed_rows.append(renamed)
            return renamed_rows
        if step.op == "filter_eq":
            return [row for row in rows if row.get(args["column"]) == args.get("value")]
        if step.op == "filter_contains":
            needle = str(args.get("value", "")).lower()
            return [row for row in rows if needle in str(row.get(args["column"], "")).lower()]
        if step.op == "filter_in":
            values = set(args.get("values", ()))
            return [row for row in rows if row.get(args["column"]) in values]
        if step.op == "filter_range":
            lower = args.get("min")
            upper = args.get("max")
            return [row for row in rows if (lower is None or row.get(args["column"]) >= lower) and (upper is None or row.get(args["column"]) <= upper)]
        if step.op == "sort":
            columns = tuple(args.get("columns", (args.get("column"),)))
            return sorted(rows, key=lambda row: tuple((row.get(column) is None, row.get(column)) for column in columns))
        if step.op == "limit":
            return rows[:int(args["count"])]
        if step.op == "rank":
            metric = str(args["metric"])
            output = str(args["output"])
            descending = bool(args.get("descending", False))
            tie_break = tuple(str(field) for field in args.get("tie_break_columns", ()))
            if any(
                not isinstance(row.get(metric), (int, float))
                or isinstance(row.get(metric), bool)
                or not isfinite(float(row[metric]))
                for row in rows
            ):
                raise TransformProgramError("rank_metric_not_numeric")
            ranked = sorted(
                rows,
                key=lambda row: (
                    -row[metric] if descending else row[metric],
                    tuple(row.get(field) for field in tie_break),
                ),
            )
            positions = {id(row): index for index, row in enumerate(ranked, 1)}
            return [{**row, output: positions[id(row)]} for row in rows]
        if step.op == "percentile_nearest_rank":
            value_field = str(args["value_field"])
            output = str(args["output"])
            percentile = float(args["percentile"])
            group_fields = tuple(str(field) for field in args.get("group_fields", ()))
            groups: dict[tuple[Any, ...], list[int | float]] = defaultdict(list)
            for row in rows:
                value = row.get(value_field)
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(float(value)):
                    raise TransformProgramError("percentile_value_not_numeric")
                groups[tuple(row[field] for field in group_fields)].append(value)
            output_rows: list[dict[str, Any]] = []
            for key, values in sorted(groups.items(), key=lambda item: tuple(str(part) for part in item[0])):
                ordered = sorted(values)
                index = max(1, ceil(percentile * len(ordered) / 100.0)) - 1
                item = {**dict(zip(group_fields, key)), output: ordered[index]}
                if "sample_count_output" in args:
                    item[str(args["sample_count_output"])] = len(ordered)
                output_rows.append(item)
            return output_rows
        if step.op == "deterministic_fixture":
            if self.deterministic_fixture_runner is None:
                raise TransformProgramError("deterministic_fixture_not_allowed")
            try:
                fixture_rows = self.deterministic_fixture_runner(step, rows)
            except TransformProgramError:
                raise
            except (KeyError, TypeError, ValueError, OSError) as exc:
                raise TransformProgramError("deterministic_fixture_failed") from exc
            if not isinstance(fixture_rows, list) or any(not isinstance(row, dict) for row in fixture_rows):
                raise TransformProgramError("deterministic_fixture_result_invalid")
            return [dict(row) for row in fixture_rows]
        if step.op == "group_by":
            columns = tuple(args["columns"])
            return [dict(row) for row in sorted(rows, key=lambda row: tuple(row.get(column) for column in columns))]
        if step.op == "aggregate":
            column = str(args["column"])
            function = str(args["function"])
            output = str(args.get("output", f"{function}_{column}"))
            values = [row[column] for row in rows if row.get(column) is not None]
            if function == "count": value: Any = len(rows)
            elif not values: value = None
            elif function == "sum": value = sum(values)
            elif function == "mean": value = sum(values) / len(values)
            elif function == "min": value = min(values)
            else: value = max(values)
            return [{output: value}]
        if step.op == "aggregate_grouped":
            if "group_fields" in args:
                group_fields = tuple(args["group_fields"])
                group_outputs = group_fields
                aggregates = tuple(zip(args["value_fields"], args["functions"], args["outputs"], strict=True))
            else:
                group_fields = (str(args["group_field"]),)
                group_outputs = (str(args.get("group_output", group_fields[0])),)
                aggregates = tuple(
                    (str(args["value_field"]), function, str(args.get(f"{function}_output", function)))
                    for function in ("sum", "mean", "min", "max", "count")
                )
            groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                groups[tuple(row[field] for field in group_fields)].append(row)
            result: list[dict[str, Any]] = []
            for key, members in sorted(groups.items(), key=lambda item: tuple(str(part) for part in item[0])):
                record = dict(zip(group_outputs, key, strict=True))
                for field, function, output in aggregates:
                    values = [row[field] for row in members]
                    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(float(value)) for value in values):
                        raise TransformProgramError("aggregate_value_not_numeric")
                    if function == "count":
                        value = len(values)
                    elif function == "sum":
                        value = sum(values)
                    elif function == "mean":
                        value = sum(values) / len(values)
                    elif function == "min":
                        value = min(values)
                    else:
                        value = max(values)
                    if isinstance(value, float) and not isfinite(value):
                        raise TransformProgramError("non_finite_result")
                    record[output] = value
                result.append(record)
            return result
        if step.op == "derive_safe":
            calculations = args.get("calculations")
            if calculations is None:
                calculations = [[args["output"], args["kind"], args["numerator"], args["denominator"]]]
            transformed: list[dict[str, Any]] = []
            for row in rows:
                record = dict(row)
                for calculation in calculations:
                    output, kind, left_field, right_operand = calculation[:4]
                    left = record[left_field]
                    right = record[right_operand] if isinstance(right_operand, str) else right_operand
                    if kind == "boolean_change":
                        if not isinstance(left, bool) or (right is not None and not isinstance(right, bool)):
                            raise TransformProgramError("derive_boolean_operand_invalid")
                        if right is None:
                            value = "initial"
                        elif left:
                            value = "still_risk" if right else "new"
                        else:
                            value = "resolved" if right else "still_clear"
                    else:
                        if any(not isinstance(operand, (int, float)) or isinstance(operand, bool) or not isfinite(float(operand)) for operand in (left, right)):
                            raise TransformProgramError("derive_operand_not_numeric")
                        if kind in {"ratio", "pct_change"} and right == 0:
                            raise TransformProgramError("derive_zero_denominator")
                        if kind == "difference":
                            value = left - right
                        elif kind == "ratio":
                            value = left / right
                        elif kind == "pct_change":
                            value = ((left - right) / right) * 100.0
                        elif kind == "less_than":
                            value = left < right
                        else:
                            value = left > right
                        if len(calculation) > 4:
                            value *= calculation[4]
                        if len(calculation) > 5 and calculation[5] is not None:
                            value = round(value, calculation[5])
                        if isinstance(value, float) and not isfinite(value):
                            raise TransformProgramError("non_finite_result")
                    record[output] = value
                transformed.append(record)
            return transformed
        if step.op == "compare_periods":
            period_field, value_field = str(args["period_field"]), str(args["value_field"])
            carry_fields = tuple(str(field) for field in args.get("carry_fields", ()))
            group_fields = tuple(str(field) for field in args.get("group_fields", ()))
            groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                groups[tuple(row[field] for field in group_fields)].append(row)
            if not rows:
                raise TransformProgramError("comparison_requires_two_rows")
            result: list[dict[str, Any]] = []
            for key, members in sorted(groups.items(), key=lambda item: tuple(str(part) for part in item[0])):
                ordered = sorted(members, key=lambda row: str(row[period_field]))
                if len(ordered) < 2:
                    raise TransformProgramError("comparison_requires_two_rows")
                if "group_fields" in args and (len(ordered) != 2 or ordered[0][period_field] == ordered[1][period_field]):
                    raise TransformProgramError("comparison_period_rows_invalid")
                before, after = ordered[0], ordered[-1]
                base, current = before[value_field], after[value_field]
                if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(float(value)) for value in (base, current)) or base == 0:
                    raise TransformProgramError("comparison_values_invalid")
                carried = dict(zip(group_fields, key, strict=True))
                for field in carry_fields:
                    value = ordered[0][field]
                    if any(row[field] != value for row in ordered[1:]):
                        raise TransformProgramError("comparison_carry_field_not_invariant")
                    carried[field] = value
                result.append({
                    **carried,
                    str(args.get("baseline_period_output", "baseline_period")): before[period_field],
                    str(args.get("comparison_period_output", "comparison_period")): after[period_field],
                    str(args.get("baseline_value_output", "baseline_value")): base,
                    str(args.get("comparison_value_output", "comparison_value")): current,
                    str(args.get("difference_output", "difference")): current - base,
                    str(args.get("ratio_output", "ratio")): current / base,
                    str(args.get("growth_pct_output", "growth_pct")): ((current - base) / base) * 100.0,
                })
            return result
        if step.op == "compare_metric":
            ticker_field = str(args["ticker_field"])
            period_field = str(args["period_field"])
            metric_field = str(args["metric_field"])
            value_field = str(args["value_field"])
            left_ticker = str(args["left_ticker"]).upper()
            right_ticker = str(args["right_ticker"]).upper()
            period = str(args["period"])
            metric = str(args["metric"]).lower()

            def select_value(ticker: str) -> float:
                matches = [
                    row
                    for row in rows
                    if str(row.get(ticker_field, "")).upper() == ticker
                    and str(row.get(period_field, "")) == period
                    and str(row.get(metric_field, "")).lower() == metric
                ]
                if len(matches) != 1:
                    raise TransformProgramError("compare_metric_match_count_invalid")
                value = matches[0].get(value_field)
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not isfinite(float(value))
                ):
                    raise TransformProgramError("compare_metric_value_invalid")
                return float(value)

            left = select_value(left_ticker)
            right = select_value(right_ticker)
            return [{
                str(args["period_output"]): period,
                str(args["left_output"]): left,
                str(args["right_output"]): right,
                str(args["gap_output"]): left - right,
            }]
        if step.op == "trend_series":
            ticker_field = str(args["ticker_field"])
            period_field = str(args["period_field"])
            metric_field = str(args["metric_field"])
            value_field = str(args["value_field"])
            tickers = tuple(str(item) for item in args["tickers"])
            periods = tuple(str(item) for item in args["periods"])
            metric = str(args["metric"])
            ticker_output = str(args["ticker_output"])
            period_output = str(args["period_output"])
            value_output = str(args["value_output"])
            direction_output = str(args["direction_output"])
            output: list[dict[str, Any]] = []
            for ticker in tickers:
                values: list[float] = []
                for period in periods:
                    matches = [
                        row
                        for row in rows
                        if str(row.get(ticker_field, "")).upper() == ticker.upper()
                        and str(row.get(period_field, "")) == period
                        and str(row.get(metric_field, "")).lower() == metric.lower()
                    ]
                    if len(matches) != 1:
                        raise TransformProgramError("trend_series_match_count_invalid")
                    value = matches[0].get(value_field)
                    if not isinstance(value, (int, float)) or isinstance(value, bool):
                        raise TransformProgramError("trend_series_value_invalid")
                    values.append(float(value))
                deltas = [right - left for left, right in zip(values, values[1:], strict=False)]
                if all(delta > 0 for delta in deltas):
                    direction = "increasing"
                elif all(delta < 0 for delta in deltas):
                    direction = "decreasing"
                elif all(delta == 0 for delta in deltas):
                    direction = "flat"
                else:
                    direction = "mixed"
                output.extend(
                    {
                        ticker_output: ticker,
                        period_output: period,
                        value_output: value,
                        direction_output: direction,
                    }
                    for period, value in zip(periods, values, strict=True)
                )
            return output
        if step.op == "join_by_key":
            right_rows = inputs[str(args["right_ref"])]
            if len(rows) * len(right_rows) > self.validator.max_join_rows:
                raise TransformProgramError("join_budget_exceeded")
            left_keys = tuple(args["left_keys"]) if "left_keys" in args else (str(args["left_key"]),)
            right_keys = tuple(args["right_keys"]) if "right_keys" in args else (str(args["right_key"]),)
            prefix = str(args.get("right_prefix", ""))
            lookup: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
            for right in right_rows:
                lookup[tuple(right[key] for key in right_keys)].append(right)
            return [
                {**left, **{prefix + key: value for key, value in right.items()}}
                for left in rows
                for right in lookup.get(tuple(left[key] for key in left_keys), ())
            ]
        if step.op == "anomaly_check":
            column, output = str(args["column"]), str(args.get("output", "is_anomaly"))
            values = sorted(float(row[column]) for row in rows if isinstance(row.get(column), (int, float)))
            if not values:
                return [{**row, output: False} for row in rows]
            q1, q3 = values[len(values) // 4], values[(len(values) * 3) // 4]
            lower, upper = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
            return [{**row, output: isinstance(row.get(column), (int, float)) and not lower <= row[column] <= upper} for row in rows]
        if step.op == "anomaly_zscore":
            period_field, value_field = str(args["period_field"]), str(args["value_field"])
            ordered = sorted(rows, key=lambda row: str(row.get(period_field, "")))
            values = [row.get(value_field) for row in ordered]
            if not values or any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in values):
                raise TransformProgramError("anomaly_values_invalid")
            numeric = [float(value) for value in values]
            mean = sum(numeric) / len(numeric)
            threshold = float(args.get("z_threshold", 1.5)) * (sum((value - mean) ** 2 for value in numeric) / len(numeric)) ** 0.5
            return [{
                period_field: row.get(period_field), value_field: float(row[value_field]),
                str(args.get("baseline_output", "baseline_mean")): mean,
                str(args.get("threshold_output", "threshold")): threshold,
                str(args.get("flag_output", "is_anomaly")): abs(float(row[value_field]) - mean) > threshold,
            } for row in ordered]
        raise TransformProgramError("unknown_operation")

    @staticmethod
    def _stable_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{key: row[key] for key in sorted(row)} for row in rows]
