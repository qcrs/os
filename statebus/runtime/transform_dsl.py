from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import time
from typing import Any, Callable

from statebus.contracts import CapabilityGrant, CapabilityQualityReport, RefStatus, TransformProgram, TransformStep
from statebus.refs import ExecutionArtifactRef
from statebus.runtime.workspace import ArtifactLifecycleManager
from statebus.utils import sha256_digest, stable_json_dumps


class TransformProgramError(ValueError):
    pass


_ALLOWED_OPS = {
    "select", "rename", "filter_eq", "filter_contains", "filter_in", "filter_range", "sort", "limit",
    "group_by", "aggregate", "aggregate_grouped", "derive_safe", "compare_periods", "join_by_key",
    "anomaly_check", "anomaly_zscore", "project_claim_fields",
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
    ) -> None:
        self.max_operations = max_operations
        self.max_rows = max_rows
        self.max_join_rows = max_join_rows
        self.max_columns = max_columns
        self.max_output_bytes = max_output_bytes

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
        known_columns = set().union(*(set(available_columns.get(ref, ())) for ref in program.input_artifact_refs))
        if len(known_columns) > self.max_columns:
            return TransformValidationReport(False, "input_column_budget_exceeded")
        for index, step in enumerate(program.operations):
            if step.op not in _ALLOWED_OPS:
                return TransformValidationReport(False, "unknown_operation", index)
            invalid = self._validate_arguments(step, known_columns, program.input_artifact_refs)
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
            return {*known_columns, str(args.get("output", ""))}
        if step.op == "compare_periods":
            return {
                *(str(field) for field in args.get("carry_fields", ())),
                str(args.get("baseline_period_output", "baseline_period")),
                str(args.get("comparison_period_output", "comparison_period")),
                str(args.get("baseline_value_output", "baseline_value")),
                str(args.get("comparison_value_output", "comparison_value")),
                str(args.get("difference_output", "difference")),
                str(args.get("ratio_output", "ratio")),
                str(args.get("growth_pct_output", "growth_pct")),
            }
        if step.op == "join_by_key":
            right_ref = str(args.get("right_ref", ""))
            return {*known_columns, *available_columns.get(right_ref, ())}
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

    def _validate_arguments(self, step: TransformStep, known_columns: set[str], authorized_refs: tuple[str, ...]) -> str:
        for key, value in step.arguments.items():
            if "path" in key.lower() or "file" in key.lower() or "expr" in key.lower() or "python" in key.lower():
                return "unsafe_argument_key"
            if not self._safe_argument_value(value):
                return "unsafe_argument_value"
        columns: list[str] = []
        for key in (
            "column", "columns", "group_by", "group_field", "period_field", "value_field",
            "left_key", "right_key", "numerator", "denominator", "source", "carry_fields",
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
        if step.op == "aggregate_grouped" and not isinstance(step.arguments.get("group_field"), str):
            return "missing_group_field"
        if step.op == "compare_periods" and not {"period_field", "value_field"} <= set(step.arguments):
            return "missing_comparison_fields"
        if step.op == "compare_periods":
            carry_fields = step.arguments.get("carry_fields", ())
            if not isinstance(carry_fields, (tuple, list)):
                return "invalid_comparison_carry_fields"
            carry_names = tuple(str(field) for field in carry_fields)
            if len(carry_names) != len(set(carry_names)):
                return "duplicate_comparison_carry_field"
            output_names = {
                str(step.arguments.get("baseline_period_output", "baseline_period")),
                str(step.arguments.get("comparison_period_output", "comparison_period")),
                str(step.arguments.get("baseline_value_output", "baseline_value")),
                str(step.arguments.get("comparison_value_output", "comparison_value")),
                str(step.arguments.get("difference_output", "difference")),
                str(step.arguments.get("ratio_output", "ratio")),
                str(step.arguments.get("growth_pct_output", "growth_pct")),
            }
            if set(carry_names) & output_names:
                return "comparison_output_collision"
        if step.op == "anomaly_zscore" and not {"period_field", "value_field"} <= set(step.arguments):
            return "missing_anomaly_fields"
        if step.op == "derive_safe" and step.arguments.get("kind") not in {"difference", "ratio", "pct_change"}:
            return "invalid_derive_kind"
        if step.op == "join_by_key" and step.arguments.get("right_ref") not in authorized_refs:
            return "unauthorized_join_ref"
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
    def __init__(self, validator: TransformProgramValidator | None = None) -> None:
        self.validator = validator or TransformProgramValidator()

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
        """Materialize the only permitted DSL output and sign it after validation."""
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
        artifact = lifecycle.mark_verified(candidate.artifact_id)
        if artifact.verification_state != RefStatus.VERIFIED:
            raise TransformProgramError("artifact_not_verified")
        return TransformArtifactResult(rows=tuple(rows), artifact=artifact, output_hash=output_hash)

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
            group_field, value_field = str(args["group_field"]), str(args["value_field"])
            groups: dict[object, list[float]] = defaultdict(list)
            for row in rows:
                value = row.get(value_field)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise TransformProgramError("aggregate_value_not_numeric")
                groups[row.get(group_field)].append(float(value))
            return [
                {
                    str(args.get("group_output", group_field)): group,
                    str(args.get("sum_output", "sum")): sum(values),
                    str(args.get("mean_output", "mean")): sum(values) / len(values),
                    str(args.get("min_output", "min")): min(values),
                    str(args.get("max_output", "max")): max(values),
                    str(args.get("count_output", "count")): len(values),
                }
                for group, values in sorted(groups.items(), key=lambda item: str(item[0]))
            ]
        if step.op == "derive_safe":
            numerator = str(args["numerator"])
            denominator = str(args["denominator"])
            output = str(args["output"])
            kind = str(args["kind"])
            transformed: list[dict[str, Any]] = []
            for row in rows:
                left, right = row.get(numerator), row.get(denominator)
                value = None
                if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                    if kind == "difference": value = left - right
                    elif kind == "ratio" and right != 0: value = left / right
                    elif kind == "pct_change" and right != 0: value = ((left - right) / right) * 100.0
                if isinstance(value, float) and not isfinite(value):
                    raise TransformProgramError("non_finite_result")
                transformed.append({**row, output: value})
            return transformed
        if step.op == "compare_periods":
            period_field, value_field = str(args["period_field"]), str(args["value_field"])
            carry_fields = tuple(str(field) for field in args.get("carry_fields", ()))
            ordered = sorted(rows, key=lambda row: str(row.get(period_field, "")))
            if len(ordered) < 2:
                raise TransformProgramError("comparison_requires_two_rows")
            before, after = ordered[0], ordered[-1]
            base, current = before.get(value_field), after.get(value_field)
            if not isinstance(base, (int, float)) or isinstance(base, bool) or not isinstance(current, (int, float)) or isinstance(current, bool) or base == 0:
                raise TransformProgramError("comparison_values_invalid")
            carried: dict[str, Any] = {}
            for field in carry_fields:
                value = ordered[0].get(field)
                if any(row.get(field) != value for row in ordered[1:]):
                    raise TransformProgramError("comparison_carry_field_not_invariant")
                carried[field] = value
            return [{
                **carried,
                str(args.get("baseline_period_output", "baseline_period")): before.get(period_field),
                str(args.get("comparison_period_output", "comparison_period")): after.get(period_field),
                str(args.get("baseline_value_output", "baseline_value")): float(base),
                str(args.get("comparison_value_output", "comparison_value")): float(current),
                str(args.get("difference_output", "difference")): float(current) - float(base),
                str(args.get("ratio_output", "ratio")): float(current) / float(base),
                str(args.get("growth_pct_output", "growth_pct")): ((float(current) - float(base)) / float(base)) * 100.0,
            }]
        if step.op == "join_by_key":
            right_rows = inputs[str(args["right_ref"])]
            if len(rows) * len(right_rows) > self.validator.max_join_rows:
                raise TransformProgramError("join_budget_exceeded")
            left_key, right_key = str(args["left_key"]), str(args["right_key"])
            lookup: dict[Any, list[dict[str, Any]]] = defaultdict(list)
            for right in right_rows:
                lookup[right.get(right_key)].append(right)
            return [{**left, **right} for left in rows for right in lookup.get(left.get(left_key), ())]
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
