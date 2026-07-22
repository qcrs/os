"""Lightweight local CodeAct runtime for controlled Python execution."""

from __future__ import annotations

import ast
import csv
import io
import math
import re
import time
from contextlib import redirect_stdout
from pathlib import Path


SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "next": next,
    "print": print,
    "range": range,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "Exception": Exception,
    "IndexError": IndexError,
    "KeyError": KeyError,
    "TypeError": TypeError,
    "ValueError": ValueError,
    "zip": zip,
}

SAFE_AST_NODES = {
    ast.Module,
    ast.Assign,
    ast.AnnAssign,
    ast.AugAssign,
    ast.Expr,
    ast.Load,
    ast.Store,
    ast.Name,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Set,
    ast.Subscript,
    ast.Slice,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.If,
    ast.For,
    ast.While,
    ast.Try,
    ast.ExceptHandler,
    ast.Pass,
    ast.Break,
    ast.Continue,
    ast.comprehension,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
    ast.GeneratorExp,
    ast.Call,
    ast.keyword,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.Attribute,
    ast.Lambda,
    ast.Add,
    ast.BitAnd,
    ast.BitOr,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    ast.IfExp,
}

MISSING_TEXT_VALUES = {"", "na", "n/a", "nan", "null", "none"}
NUMERIC_REMAINDER_PREFIXES = ("[", "(", "%")
LEADING_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?")

FORBIDDEN_CALL_NAMES = {
    "__import__",
    "compile",
    "delattr",
    "eval",
    "exec",
    "getattr",
    "globals",
    "input",
    "locals",
    "open",
    "setattr",
    "vars",
}


def run_codeact_python(
    code: str,
    *,
    artifact_refs: list[dict] | None = None,
    max_stdout_chars: int = 4000,
) -> dict:
    """Execute a small Python program with CSV helpers and restricted builtins."""
    started_at = time.perf_counter()
    artifacts = _normalize_artifact_refs(artifact_refs or [])
    try:
        tree = ast.parse(code, mode="exec")
        _validate_ast(tree)
        env = _build_runtime_env(artifacts)
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exec(compile(tree, "<codeact_python>", "exec"), env, env)
        stdout_text = stdout.getvalue().strip()
        if len(stdout_text) > max_stdout_chars:
            stdout_text = stdout_text[:max_stdout_chars].rstrip()
        metrics = env.get("metrics", {})
        extracted_answers = _normalize_extracted_answers(env.get("extracted_answers", {}))
        final_answer = str(env.get("final_answer", "") or "").strip()
        return {
            "ok": True,
            "stdout": stdout_text,
            "metrics": metrics if isinstance(metrics, dict) else {},
            "error": "",
            "final_answer": final_answer,
            "extracted_answers": extracted_answers,
            "artifacts": artifacts,
            "duration_s": round(time.perf_counter() - started_at, 4),
        }
    except Exception as exc:
        return {
            "ok": False,
            "stdout": "",
            "metrics": {},
            "error": f"{type(exc).__name__}: {exc}",
            "final_answer": "",
            "extracted_answers": {},
            "artifacts": artifacts,
            "duration_s": round(time.perf_counter() - started_at, 4),
        }


def build_codeact_prompt_context(artifact_refs: list[dict] | None) -> str:
    """Describe runtime helpers and mounted artifacts for the executor prompt."""
    artifacts = _normalize_artifact_refs(artifact_refs or [])
    lines = [
        "Runtime helpers available in Python code:",
        "- load_csv_rows(index=0, label=None, nrows=None, limit=None, usecols=None) -> list[dict[str, str]] with stripped cell values and whitespace-normalized column aliases",
        "- artifact_path(index=0, label=None) -> absolute artifact path string",
        "- list_artifacts() -> list of artifact metadata dicts",
        "- column_names(rows_or_table) -> list[str]",
        "- column_values(rows_or_table, field) -> list[object]",
        "- unique_values(rows_or_table, field, drop_missing=False) -> list[object]",
        "- value_counts(rows_or_table, field, drop_missing=True, normalize=False) -> dict[str, float]",
        "- numeric_values(rows_or_table, field) -> list[float]",
        "- paired_numeric_values(rows_or_table, field_x, field_y) -> list[tuple[float, float]]",
        "- mean(values), std(values, ddof=0), median(values), quantile(values, q), pearson_corr(pairs_or_xs, ys=None), sample_skew(values)",
        "- normality_pvalue(values), zscore_outlier_count(values, threshold=3.0), to_float(value)",
        "- preloaded modules/objects: math",
        "",
        "Rules:",
        "- Do not write files.",
        "- Do not import modules.",
        "- Do not define functions or classes.",
        "- Set `final_answer` to the exact machine-graded string when possible.",
        "- Set `extracted_answers` to a dict[str, str].",
        "- Optionally set `metrics` to a dict with audit values.",
        "",
        "Mounted artifacts:",
    ]
    if not artifacts:
        lines.append("- (none)")
    else:
        for index, artifact in enumerate(artifacts):
            lines.append(
                f"- [{index}] kind={artifact.get('kind', 'file')} "
                f"label={artifact.get('label', '') or '-'} path={artifact['path']}"
            )
    return "\n".join(lines)


def _build_runtime_env(artifacts: list[dict]) -> dict:
    def _resolve_artifact(index: int = 0, label: str | None = None) -> dict:
        if label is not None:
            for artifact in artifacts:
                if artifact.get("label") == label:
                    return artifact
            raise ValueError(f"Artifact label not found: {label}")
        if not artifacts:
            raise ValueError("No artifacts available for CodeAct execution.")
        if index < 0 or index >= len(artifacts):
            raise IndexError(f"Artifact index out of range: {index}")
        return artifacts[index]

    def artifact_path(index: int = 0, label: str | None = None) -> str:
        return _resolve_artifact(index=index, label=label)["path"]

    def load_csv_rows(
        index: int = 0,
        label: str | None = None,
        nrows: int | None = None,
        limit: int | None = None,
        usecols: list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, str]]:
        artifact = _resolve_artifact(index=index, label=label)
        if artifact.get("kind") != "csv":
            raise ValueError(f"Artifact is not CSV: {artifact}")
        row_limit = nrows if nrows is not None else limit
        return _read_csv_rows(artifact["path"], nrows=row_limit, usecols=usecols)

    def list_artifacts() -> list[dict]:
        return [dict(artifact) for artifact in artifacts]

    return {
        "__builtins__": SAFE_BUILTINS,
        "artifact_path": artifact_path,
        "artifacts": list_artifacts(),
        "column_names": _column_names,
        "column_values": _column_values,
        "list_artifacts": list_artifacts,
        "load_csv_rows": load_csv_rows,
        "math": math,
        "mean": _mean,
        "median": _median,
        "extracted_answers": {},
        "final_answer": "",
        "metrics": {},
        "normality_pvalue": _normality_pvalue,
        "numeric_values": _runtime_numeric_values,
        "paired_numeric_values": _runtime_paired_numeric_values,
        "pearson_corr": _runtime_pearson_corr,
        "quantile": _quantile,
        "sample_skew": _sample_skew,
        "std": _runtime_std,
        "to_float": _to_float,
        "unique_values": _unique_values,
        "value_counts": _value_counts,
        "zscore_outlier_count": _zscore_outlier_count,
    }


def _normalize_artifact_refs(artifact_refs: list[dict]) -> list[dict]:
    normalized = []
    for index, artifact in enumerate(artifact_refs):
        if not isinstance(artifact, dict):
            continue
        path = str(artifact.get("path", "") or "").strip()
        if not path:
            continue
        resolved = Path(path).expanduser()
        if not resolved.is_absolute():
            resolved = (Path.cwd() / resolved).resolve()
        else:
            resolved = resolved.resolve()
        normalized.append({
            "id": str(artifact.get("id") or f"artifact_{index}"),
            "kind": str(artifact.get("kind") or "file"),
            "label": str(artifact.get("label") or ""),
            "path": str(resolved),
        })
    return normalized


def _is_missing(value: object) -> bool:
    return value is None or (
        isinstance(value, str) and value.strip().lower() in MISSING_TEXT_VALUES
    )


def _normalize_text_cell(value: object) -> str:
    return "" if value is None else str(value).strip()


def _canonicalize_column_name(name: object) -> str:
    return " ".join(str(name or "").strip().split())


def _resolve_mapping_key(mapping: dict[object, object], field: object) -> object | None:
    raw_keys = list(dict.keys(mapping)) if isinstance(mapping, dict) else list(mapping.keys())
    direct_key = str(field)
    if direct_key in raw_keys:
        return direct_key

    canonical_field = _canonicalize_column_name(field)
    if canonical_field in raw_keys:
        return canonical_field

    lowered_field = canonical_field.lower()
    for key in raw_keys:
        canonical_key = _canonicalize_column_name(key)
        if canonical_key == canonical_field or canonical_key.lower() == lowered_field:
            return key
    return None


def _to_float(value: object) -> float | None:
    if _is_missing(value):
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    lowered = text.lower()
    if lowered in MISSING_TEXT_VALUES:
        return None
    sanitized = text.replace(",", "")
    try:
        return float(sanitized)
    except (TypeError, ValueError):
        for prefix in NUMERIC_REMAINDER_PREFIXES:
            if prefix in sanitized:
                head = sanitized.split(prefix, 1)[0].strip()
                try:
                    return float(head)
                except (TypeError, ValueError):
                    break
        if sanitized.endswith("%"):
            try:
                return float(sanitized[:-1].strip())
            except (TypeError, ValueError):
                return None
        match = LEADING_NUMBER_RE.match(sanitized)
        if not match:
            return None
        remainder = sanitized[match.end():].strip()
        if remainder.startswith(("/", ":", "-")):
            return None
        try:
            return float(match.group(0))
        except (TypeError, ValueError):
            return None


def _read_csv_rows(
    path: str,
    *,
    nrows: int | None = None,
    usecols: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, str]]:
    selected = [str(column) for column in usecols] if usecols else None
    rows: list[dict[str, str]] = []
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            if nrows is not None and index >= nrows:
                break
            normalized = _AliasRow()
            for key, value in row.items():
                canonical_key = _canonicalize_column_name(key)
                normalized[canonical_key] = _normalize_text_cell(value)
            if selected is not None:
                filtered = _AliasRow()
                for column in selected:
                    canonical_column = _canonicalize_column_name(column)
                    filtered[canonical_column] = normalized.get(column, "")
                normalized = filtered
            rows.append(normalized)
    return rows


def _values_from_rows_or_table(rows_or_table: object, field: str) -> list[object]:
    if isinstance(rows_or_table, _MiniDataFrame):
        return list(rows_or_table[field].values)
    if isinstance(rows_or_table, _MiniSeries):
        return list(rows_or_table.values)
    if isinstance(rows_or_table, list):
        values = []
        for row in rows_or_table:
            if isinstance(row, dict):
                values.append(_lookup_mapping_value(row, field))
        return values
    raise TypeError(f"Unsupported runtime table type: {type(rows_or_table).__name__}")


def _column_names(rows_or_table: object) -> list[str]:
    if isinstance(rows_or_table, _MiniDataFrame):
        return _dedupe_column_names(rows_or_table.columns)
    if isinstance(rows_or_table, list):
        for row in rows_or_table:
            if isinstance(row, dict):
                return _dedupe_column_names(row.keys())
        return []
    raise TypeError(f"Unsupported runtime table type: {type(rows_or_table).__name__}")


def _column_values(rows_or_table: object, field: str) -> list[object]:
    return list(_values_from_rows_or_table(rows_or_table, field))


def _unique_values(rows_or_table: object, field: str, drop_missing: bool = False) -> list[object]:
    seen: set[str] = set()
    values: list[object] = []
    for value in _column_values(rows_or_table, field):
        if drop_missing and _is_missing(value):
            continue
        marker = repr(value)
        if marker in seen:
            continue
        seen.add(marker)
        values.append(value)
    return values


def _value_counts(
    rows_or_table: object,
    field: str,
    drop_missing: bool = True,
    normalize: bool = False,
) -> dict[str, float]:
    counts: dict[str, float] = {}
    total = 0.0
    for value in _column_values(rows_or_table, field):
        if drop_missing and _is_missing(value):
            continue
        key = "" if value is None else str(value)
        counts[key] = counts.get(key, 0.0) + 1.0
        total += 1.0
    if normalize and total > 0.0:
        return {key: count / total for key, count in counts.items()}
    return counts


def _runtime_numeric_values(rows_or_table: object, field: str) -> list[float]:
    values = []
    for value in _values_from_rows_or_table(rows_or_table, field):
        parsed = _to_float(value)
        if parsed is not None:
            values.append(parsed)
    return values


def _runtime_paired_numeric_values(
    rows_or_table: object,
    field_x: object,
    field_y: object | None = None,
) -> list[tuple[float, float]]:
    if field_y is None:
        if isinstance(field_x, (list, tuple)) and len(field_x) == 2:
            left, right = field_x
            if isinstance(left, str) and isinstance(right, str):
                return _runtime_paired_numeric_values(rows_or_table, left, right)
            return _pair_numeric_sequences(left, right)
        return _pair_numeric_sequences(rows_or_table, field_x)

    if isinstance(rows_or_table, _MiniDataFrame):
        rows = rows_or_table.to_records()
    elif isinstance(rows_or_table, list):
        rows = rows_or_table
    else:
        raise TypeError(f"Unsupported runtime table type: {type(rows_or_table).__name__}")

    pairs = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        x_value = _to_float(_lookup_mapping_value(row, field_x))
        y_value = _to_float(_lookup_mapping_value(row, field_y))
        if x_value is None or y_value is None:
            continue
        pairs.append((x_value, y_value))
    return pairs


def _extract_numeric_values(values_or_table: object, field: str | None = None) -> list[float]:
    if field is not None:
        return _runtime_numeric_values(values_or_table, field)
    if isinstance(values_or_table, _MiniSeries):
        raw_values = list(values_or_table.values)
    elif isinstance(values_or_table, _MiniDataFrame):
        if len(values_or_table.columns) != 1:
            raise ValueError("Expected a single-column table for numeric reduction.")
        raw_values = list(values_or_table[values_or_table.columns[0]].values)
    elif isinstance(values_or_table, list):
        if values_or_table and isinstance(values_or_table[0], dict):
            first_row = values_or_table[0]
            if len(first_row) != 1:
                raise ValueError("Expected one field when reducing numeric row dictionaries.")
            field_name = next(iter(first_row.keys()))
            raw_values = [row.get(field_name) for row in values_or_table if isinstance(row, dict)]
        else:
            raw_values = list(values_or_table)
    else:
        raw_values = list(values_or_table)

    values = []
    for value in raw_values:
        parsed = _to_float(value)
        if parsed is not None:
            values.append(parsed)
    return values


def _mean(values_or_table: object, field: str | None = None) -> float:
    values = _extract_numeric_values(values_or_table, field)
    if not values:
        raise ValueError("Cannot compute mean of empty values.")
    return sum(values) / len(values)


def _median(values_or_table: object, field: str | None = None) -> float:
    values = sorted(_extract_numeric_values(values_or_table, field))
    if not values:
        raise ValueError("Cannot compute median of empty values.")
    size = len(values)
    middle = size // 2
    if size % 2 == 1:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2.0


def _quantile(values_or_table: object, q: float, field: str | None = None) -> float:
    values = sorted(_extract_numeric_values(values_or_table, field))
    if not values:
        raise ValueError("Cannot compute quantile of empty values.")
    q_value = float(q)
    if q_value < 0.0 or q_value > 1.0:
        raise ValueError("Quantile q must be between 0 and 1.")
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * q_value
    lower_index = int(math.floor(position))
    upper_index = int(math.ceil(position))
    if lower_index == upper_index:
        return values[lower_index]
    lower_value = values[lower_index]
    upper_value = values[upper_index]
    weight = position - lower_index
    return lower_value + (upper_value - lower_value) * weight


def _runtime_std(values_or_table: object, ddof: int = 0, field: str | None = None) -> float:
    values = _extract_numeric_values(values_or_table, field)
    if not values or len(values) <= ddof:
        return 0.0
    center = _mean(values)
    return math.sqrt(sum((value - center) ** 2 for value in values) / (len(values) - ddof))


def _sample_skew(values_or_table: object, field: str | None = None) -> float:
    values = _extract_numeric_values(values_or_table, field)
    if len(values) < 3:
        return 0.0
    center = _mean(values)
    sample_std = _runtime_std(values, ddof=1)
    if sample_std == 0.0:
        return 0.0
    n = len(values)
    third_moment = sum((value - center) ** 3 for value in values)
    return (n * third_moment) / ((n - 1) * (n - 2) * (sample_std ** 3))


def _pearson_from_pairs(pairs: list[tuple[float, float]]) -> float:
    if len(pairs) < 2:
        return 0.0
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    mean_x = _mean(xs)
    mean_y = _mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    denom_x = sum((x - mean_x) ** 2 for x in xs)
    denom_y = sum((y - mean_y) ** 2 for y in ys)
    denominator = math.sqrt(denom_x * denom_y)
    if denominator == 0.0:
        return 0.0
    return numerator / denominator


def _runtime_pearson_corr(pairs_or_xs: object, ys: object | None = None) -> float:
    if ys is None:
        if isinstance(pairs_or_xs, _MiniDataFrame):
            if len(pairs_or_xs.columns) < 2:
                return 0.0
            pairs = _runtime_paired_numeric_values(
                pairs_or_xs,
                pairs_or_xs.columns[0],
                pairs_or_xs.columns[1],
            )
            return _pearson_from_pairs(pairs)
        if isinstance(pairs_or_xs, list) and pairs_or_xs and isinstance(pairs_or_xs[0], dict):
            keys = list(pairs_or_xs[0].keys())
            if len(keys) >= 2:
                return _pearson_from_pairs(_runtime_paired_numeric_values(pairs_or_xs, keys[0], keys[1]))
        return _pearson_from_pairs(list(pairs_or_xs))
    if isinstance(ys, (list, tuple)) and len(ys) == 2 and all(isinstance(item, str) for item in ys):
        return _pearson_from_pairs(_runtime_paired_numeric_values(pairs_or_xs, ys[0], ys[1]))
    pairs = list(zip(pairs_or_xs, ys))
    numeric_pairs = []
    for x_value, y_value in pairs:
        left = _to_float(x_value)
        right = _to_float(y_value)
        if left is None or right is None:
            continue
        numeric_pairs.append((left, right))
    return _pearson_from_pairs(numeric_pairs)


def _excess_kurtosis(values: list[float]) -> float:
    if len(values) < 4:
        return 0.0
    center = _mean(values)
    second_moment = sum((value - center) ** 2 for value in values) / len(values)
    if second_moment == 0.0:
        return 0.0
    fourth_moment = sum((value - center) ** 4 for value in values) / len(values)
    return (fourth_moment / (second_moment ** 2)) - 3.0


def _normality_pvalue(values_or_table: object, field: str | None = None) -> float:
    values = _extract_numeric_values(values_or_table, field)
    if len(values) < 3:
        return 1.0
    try:
        from scipy import stats as real_scipy_stats

        return float(real_scipy_stats.shapiro(values).pvalue)
    except Exception:
        pass
    skewness = _sample_skew(values)
    excess_kurtosis = _excess_kurtosis(values)
    jb_stat = (len(values) / 6.0) * ((skewness ** 2) + ((excess_kurtosis ** 2) / 4.0))
    return math.exp(-jb_stat / 2.0)


def _zscore_outlier_count(
    values_or_table: object,
    threshold: float = 3.0,
    field: str | None = None,
) -> int:
    values = _extract_numeric_values(values_or_table, field)
    if not values:
        return 0
    center = _mean(values)
    spread = _runtime_std(values, ddof=0)
    if spread == 0.0:
        return 0
    return sum(1 for value in values if abs((value - center) / spread) > threshold)


def _pair_numeric_sequences(left_source: object, right_source: object) -> list[tuple[float, float]]:
    left_values = _extract_numeric_values(left_source)
    right_values = _extract_numeric_values(right_source)
    pairs = []
    for left, right in zip(left_values, right_values):
        pairs.append((left, right))
    return pairs


class _MiniMask:
    def __init__(self, values: list[object]):
        self.values = [bool(value) for value in values]

    def __len__(self) -> int:
        return len(self.values)

    def __iter__(self):
        return iter(self.values)

    def __and__(self, other: object):
        other_values = _coerce_mask_values(other)
        return _MiniMask([left and right for left, right in zip(self.values, other_values)])

    def __or__(self, other: object):
        other_values = _coerce_mask_values(other)
        return _MiniMask([left or right for left, right in zip(self.values, other_values)])

    def sum(self) -> int:
        return sum(1 for value in self.values if value)


class _MiniValueCounts(dict):
    def to_dict(self) -> dict[str, float]:
        return dict(self)


class _AliasRow(dict):
    def __contains__(self, key: object) -> bool:
        return _resolve_mapping_key(self, key) is not None

    def __getitem__(self, key: object):
        resolved_key = _resolve_mapping_key(self, key)
        if resolved_key is None:
            raise KeyError(key)
        return super().__getitem__(resolved_key)

    def get(self, key: object, default=None):
        resolved_key = _resolve_mapping_key(self, key)
        if resolved_key is None:
            return default
        return super().get(resolved_key, default)


class _MiniSeries:
    def __init__(self, values: list[object]):
        self.values = list(values)

    def __len__(self) -> int:
        return len(self.values)

    def __iter__(self):
        return iter(self.values)

    def __array__(self, dtype=None):
        import numpy as _np

        array_values = []
        for value in self.values:
            parsed = _to_float(value)
            array_values.append(_np.nan if parsed is None else parsed)
        return _np.asarray(array_values, dtype=dtype)

    @property
    def dtype(self):
        return self.__array__().dtype

    @property
    def shape(self):
        return (len(self.values),)

    def __abs__(self):
        converted = []
        for value in self.values:
            parsed = _to_float(value)
            converted.append(None if parsed is None else abs(parsed))
        return _MiniSeries(converted)

    def abs(self) -> "_MiniSeries":
        return abs(self)

    def _binary_numeric_op(self, other: object, op) -> "_MiniSeries":
        other_values = _coerce_series_values(other, len(self.values))
        result = []
        for left, right in zip(self.values, other_values):
            left_value = _to_float(left)
            right_value = _to_float(right)
            if left_value is None or right_value is None:
                result.append(None)
            else:
                result.append(op(left_value, right_value))
        return _MiniSeries(result)

    def _compare(self, other: object, op) -> _MiniMask:
        other_values = _coerce_series_values(other, len(self.values))
        result = []
        for left, right in zip(self.values, other_values):
            if _is_missing(left) or _is_missing(right):
                result.append(False)
                continue
            right_number = _to_float(right)
            left_number = _to_float(left)
            if right_number is not None and left_number is not None:
                result.append(op(left_number, right_number))
            else:
                result.append(op(str(left).strip(), str(right).strip()))
        return _MiniMask(result)

    def dropna(self) -> "_MiniSeries":
        return _MiniSeries([value for value in self.values if not _is_missing(value)])

    def astype(self, dtype) -> "_MiniSeries":
        converted = []
        for value in self.values:
            if _is_missing(value):
                converted.append(None)
            else:
                converted.append(dtype(value))
        return _MiniSeries(converted)

    def fillna(self, value: object) -> "_MiniSeries":
        return _MiniSeries([value if _is_missing(item) else item for item in self.values])

    def mean(self) -> float:
        return _mean(self.values)

    def median(self) -> float:
        return _median(self.values)

    def quantile(self, q: float) -> float:
        return _quantile(self.values, q)

    def std(self, ddof: int = 1) -> float:
        return _runtime_std(self.values, ddof=ddof)

    def skew(self) -> float:
        return _sample_skew(self.values)

    def corr(self, other: object, method: str = "pearson") -> float:
        if method != "pearson":
            raise ValueError(f"Unsupported correlation method: {method}")
        return _runtime_pearson_corr(self.values, getattr(other, "values", other))

    def sum(self):
        values = []
        for item in self.values:
            if isinstance(item, bool):
                values.append(int(item))
                continue
            parsed = _to_float(item)
            if parsed is not None:
                values.append(parsed)
        return sum(values)

    def min(self):
        if not self.values:
            raise ValueError("Cannot compute min of empty values.")
        return min(self.values)

    def max(self):
        if not self.values:
            raise ValueError("Cannot compute max of empty values.")
        return max(self.values)

    def unique(self) -> list[object]:
        seen: set[str] = set()
        unique_values: list[object] = []
        for value in self.values:
            marker = repr(value)
            if marker in seen:
                continue
            seen.add(marker)
            unique_values.append(value)
        return unique_values

    def nunique(self, dropna: bool = True) -> int:
        return len([
            value for value in self.unique()
            if not dropna or not _is_missing(value)
        ])

    def value_counts(self, dropna: bool = True, normalize: bool = False) -> _MiniValueCounts:
        counts: dict[str, float] = {}
        total = 0.0
        for value in self.values:
            if dropna and _is_missing(value):
                continue
            key = "" if value is None else str(value)
            counts[key] = counts.get(key, 0.0) + 1.0
            total += 1.0
        if normalize and total > 0.0:
            counts = {key: count / total for key, count in counts.items()}
        return _MiniValueCounts(counts)

    def tolist(self) -> list[object]:
        return list(self.values)

    def values_as_rows(self) -> list[dict[str, object]]:
        return [{"value": value} for value in self.values]

    def __add__(self, other: object):
        return self._binary_numeric_op(other, lambda left, right: left + right)

    def __sub__(self, other: object):
        return self._binary_numeric_op(other, lambda left, right: left - right)

    def __mul__(self, other: object):
        return self._binary_numeric_op(other, lambda left, right: left * right)

    def __truediv__(self, other: object):
        return self._binary_numeric_op(other, lambda left, right: left / right)

    def __eq__(self, other: object):
        return self._compare(other, lambda left, right: left == right)

    def __gt__(self, other: object):
        return self._compare(other, lambda left, right: left > right)

    def __ge__(self, other: object):
        return self._compare(other, lambda left, right: left >= right)


class _MiniDataFrame:
    def __init__(self, rows: list[dict[str, object]]):
        self._rows = [_AliasRow(row) for row in rows]
        self.columns = list(self._rows[0].keys()) if self._rows else []

    def __len__(self) -> int:
        return len(self._rows)

    @property
    def shape(self):
        return (len(self._rows), len(self.columns))

    def __getitem__(self, key: object):
        if isinstance(key, str):
            return _MiniSeries([row.get(key) for row in self._rows])
        if isinstance(key, _MiniMask):
            return _MiniDataFrame([
                _AliasRow(row) for row, keep in zip(self._rows, key.values) if keep
            ])
        if isinstance(key, list):
            if key and all(isinstance(item, str) for item in key):
                return _MiniDataFrame([
                    {column: row.get(column) for column in key}
                    for row in self._rows
                ])
            if key and all(isinstance(item, bool) for item in key):
                return _MiniDataFrame([
                    _AliasRow(row) for row, keep in zip(self._rows, key) if keep
                ])
        raise TypeError(f"Unsupported DataFrame key type: {type(key).__name__}")

    def __setitem__(self, key: str, value: object) -> None:
        if isinstance(value, _MiniSeries):
            values = list(value.values)
        elif isinstance(value, list):
            values = list(value)
        else:
            values = [value] * len(self._rows)
        if len(values) != len(self._rows):
            raise ValueError("Assigned column length does not match DataFrame rows.")
        for row, item in zip(self._rows, values):
            row[key] = item
        if key not in self.columns:
            self.columns.append(key)

    def copy(self) -> "_MiniDataFrame":
        return _MiniDataFrame(self._rows)

    def head(self, n: int = 5) -> "_MiniDataFrame":
        return _MiniDataFrame(self._rows[:max(int(n), 0)])

    def dropna(self) -> "_MiniDataFrame":
        return _MiniDataFrame([
            _AliasRow(row)
            for row in self._rows
            if all(not _is_missing(value) for value in row.values())
        ])

    def iterrows(self):
        for index, row in enumerate(self._rows):
            yield index, _AliasRow(row)

    def to_dict(self, orient: str = "dict"):
        if orient == "records":
            return self.to_records()
        if orient == "list":
            return {
                column: [row.get(column) for row in self._rows]
                for column in self.columns
            }
        return {
            column: {
                index: row.get(column)
                for index, row in enumerate(self._rows)
            }
            for column in self.columns
        }

    def to_records(self) -> list[dict[str, object]]:
        return [_AliasRow(row) for row in self._rows]


class _ShapiroResult:
    def __init__(self, pvalue: float):
        self.pvalue = float(pvalue)


class _ScipyStatsCompat:
    def shapiro(self, values: object) -> _ShapiroResult:
        series = values.values if isinstance(values, _MiniSeries) else values
        numeric_values = []
        for value in series:
            parsed = _to_float(value)
            if parsed is not None:
                numeric_values.append(parsed)
        return _ShapiroResult(_normality_pvalue(numeric_values))

    def zscore(self, values: object) -> _MiniSeries:
        series = values.values if isinstance(values, _MiniSeries) else list(values)
        numeric_values = []
        for value in series:
            parsed = _to_float(value)
            if parsed is not None:
                numeric_values.append(parsed)
        if not numeric_values:
            return _MiniSeries([])
        center = _mean(numeric_values)
        spread = _runtime_std(numeric_values, ddof=0)
        if spread == 0.0:
            return _MiniSeries([0.0 for _ in numeric_values])
        return _MiniSeries([(value - center) / spread for value in numeric_values])

    def pearsonr(self, xs: object, ys: object) -> tuple[float, float]:
        corr = _runtime_pearson_corr(xs, ys)
        return corr, 1.0


def _lookup_mapping_value(mapping: dict[object, object], field: object, default=None):
    resolved_key = _resolve_mapping_key(mapping, field)
    if resolved_key is None:
        return default
    if isinstance(mapping, dict):
        return dict.get(mapping, resolved_key, default)
    return mapping.get(resolved_key, default)


def _dedupe_column_names(columns: object) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for column in columns:
        canonical = _canonicalize_column_name(column)
        marker = canonical.lower()
        if marker in seen:
            continue
        seen.add(marker)
        names.append(canonical)
    return names


def _coerce_series_values(other: object, size: int) -> list[object]:
    if isinstance(other, _MiniSeries):
        return list(other.values)
    if isinstance(other, list):
        return list(other)
    return [other] * size


def _coerce_mask_values(other: object) -> list[bool]:
    if isinstance(other, _MiniMask):
        return list(other.values)
    if isinstance(other, list):
        return [bool(value) for value in other]
    raise TypeError(f"Unsupported mask type: {type(other).__name__}")


def _normalize_extracted_answers(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized = {}
    for key, raw in value.items():
        field = str(key).strip().lstrip("@")
        if not field:
            continue
        normalized[field] = str(raw).strip()
    return normalized


def _validate_ast(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if type(node) not in SAFE_AST_NODES:
            raise ValueError(f"Unsafe CodeAct node: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError("Dunder names are not allowed")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError("Dunder attribute access is not allowed")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALL_NAMES:
                raise ValueError(f"Forbidden call: {node.func.id}")
