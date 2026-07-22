"""Validated parameter bindings for reusable execution recipes."""

from __future__ import annotations

import ast
import math
from typing import Any

from v2.contracts import CanonicalTaskSpec


RECIPE_PARAMETER_RELPATH = "inputs/statebus_parameters.json"
RECIPE_PARAMETER_VARIABLE = "statebus_params"


def _scalar_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float) and math.isfinite(value):
        return "number"
    if isinstance(value, str):
        return "string"
    return ""


def recipe_parameter_contract(
    spec: CanonicalTaskSpec | None,
) -> tuple[dict[str, str], dict[str, object]]:
    if spec is None:
        return {}, {}
    schema: dict[str, str] = {}
    bindings: dict[str, object] = {}
    for raw_name, value in sorted(spec.arguments.items()):
        name = str(raw_name).strip()
        value_type = _scalar_type(value)
        if not name or not value_type:
            continue
        schema[name] = value_type
        bindings[name] = value
    return schema, bindings


def validate_recipe_parameter_bindings(
    *,
    schema: dict[str, object],
    bindings: dict[str, object],
    allowed_parameter_bindings: tuple[str, ...] | list[str] | None = None,
) -> tuple[str, ...]:
    errors: list[str] = []
    normalized_schema = {str(key): str(value) for key, value in schema.items()}
    allowed = set(normalized_schema)
    if allowed_parameter_bindings is not None:
        declared = {str(value) for value in allowed_parameter_bindings}
        if declared != allowed:
            errors.append("allowed_parameter_bindings_mismatch")
    for name, expected_type in normalized_schema.items():
        if name not in bindings:
            errors.append(f"parameter_binding_missing:{name}")
            continue
        observed_type = _scalar_type(bindings[name])
        if observed_type != expected_type:
            errors.append(f"parameter_binding_type_mismatch:{name}")
    for name in bindings:
        if str(name) not in allowed:
            errors.append(f"parameter_binding_not_declared:{name}")
    return tuple(sorted(set(errors)))


def changed_task_argument_keys(
    *,
    source_spec: CanonicalTaskSpec,
    current_spec: CanonicalTaskSpec,
) -> tuple[str, ...]:
    keys = set(source_spec.arguments) | set(current_spec.arguments)
    return tuple(sorted(
        str(key)
        for key in keys
        if source_spec.arguments.get(key) != current_spec.arguments.get(key)
    ))


def bound_recipe_parameters(
    *,
    recipe: dict[str, object],
    source_spec: CanonicalTaskSpec,
    current_spec: CanonicalTaskSpec,
) -> tuple[dict[str, object], tuple[str, ...]]:
    changed_keys = changed_task_argument_keys(
        source_spec=source_spec,
        current_spec=current_spec,
    )
    raw_schema = recipe.get("parameter_schema")
    if not isinstance(raw_schema, dict) or not raw_schema:
        if not changed_keys:
            return {}, ()
        return {}, ("parameter_schema_missing",)
    schema = {str(key): str(value) for key, value in raw_schema.items()}
    missing_changed = sorted(set(changed_keys) - set(schema))
    errors = [f"parameter_schema_does_not_cover:{key}" for key in missing_changed]
    bindings = {
        key: current_spec.arguments[key]
        for key in schema
        if key in current_spec.arguments
    }
    allowed = recipe.get("allowed_parameter_bindings")
    if not isinstance(allowed, (list, tuple)):
        errors.append("allowed_parameter_bindings_missing")
        allowed_values: tuple[str, ...] = ()
    else:
        allowed_values = tuple(str(value) for value in allowed)
    errors.extend(validate_recipe_parameter_bindings(
        schema=schema,
        bindings=bindings,
        allowed_parameter_bindings=allowed_values,
    ))
    source_bindings = recipe.get("source_parameter_bindings")
    if not isinstance(source_bindings, dict):
        errors.append("source_parameter_bindings_missing")
    else:
        expected_source_bindings = {
            key: source_spec.arguments[key]
            for key in schema
            if key in source_spec.arguments
        }
        if source_bindings != expected_source_bindings:
            errors.append("source_parameter_bindings_mismatch")
    if str(recipe.get("parameter_relpath", "")) != RECIPE_PARAMETER_RELPATH:
        errors.append("parameter_relpath_mismatch")
    return bindings, tuple(sorted(set(errors)))


def audit_parameterized_recipe_source(
    source: str,
    *,
    parameter_schema: dict[str, object],
    parameter_bindings: dict[str, object],
    parameter_relpath: str = RECIPE_PARAMETER_RELPATH,
) -> tuple[str, ...]:
    if not parameter_schema:
        return ()
    errors = list(validate_recipe_parameter_bindings(
        schema=parameter_schema,
        bindings=parameter_bindings,
        allowed_parameter_bindings=tuple(parameter_schema),
    ))
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError:
        return tuple(sorted(set((*errors, "parameterized_source_syntax_error"))))

    parameter_assignment_found = False
    used_keys: set[str] = set()
    literal_values: set[Any] = {
        node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = (
                tuple(node.targets)
                if isinstance(node, ast.Assign)
                else (node.target,)
            )
            value = node.value
            if any(
                isinstance(target, ast.Name)
                and target.id == RECIPE_PARAMETER_VARIABLE
                for target in targets
            ) and value is not None:
                subtree_literals = {
                    child.value
                    for child in ast.walk(value)
                    if isinstance(child, ast.Constant)
                }
                calls = {
                    _call_name(child.func)
                    for child in ast.walk(value)
                    if isinstance(child, ast.Call)
                }
                parameter_assignment_found = bool(
                    parameter_relpath in subtree_literals
                    and any(call.endswith("json.loads") or call == "json.loads" for call in calls)
                )
        if not isinstance(node, ast.Subscript):
            continue
        if not isinstance(node.value, ast.Name) or node.value.id != RECIPE_PARAMETER_VARIABLE:
            continue
        key_node = node.slice
        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
            used_keys.add(key_node.value)

    if not parameter_assignment_found:
        errors.append("parameter_file_not_loaded_into_statebus_params")
    if not used_keys:
        errors.append("parameter_bindings_not_used")
    for key in sorted(used_keys - set(parameter_schema)):
        errors.append(f"undeclared_parameter_access:{key}")
    for key, value in parameter_bindings.items():
        if isinstance(value, str) and value and value in literal_values:
            errors.append(f"parameter_value_embedded_as_literal:{key}")
    return tuple(sorted(set(errors)))


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value) if isinstance(node.value, (ast.Name, ast.Attribute)) else ""
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""
