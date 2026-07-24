from __future__ import annotations

import ast
import builtins
import json
from dataclasses import dataclass, field, replace
from math import isfinite
from pathlib import Path
import re
import symtable
import time
from typing import Any, Callable

from v2.contracts import (
    CapabilityGrant,
    CapabilityQualityReport,
    CodeExecutionRecord,
    CodeGenerationPolicy,
    CodeGenerationRequest,
    CodePolicyReport,
    CodeRepairRecord,
    ExecutionKind,
    GeneratedCodeCandidate,
    RefStatus,
)
from v2.refs import ExecutionArtifactRef
from v2.runtime.capability_registry import CapabilityRegistry
from v2.runtime.capability_validators import (
    CapabilityQualityContext,
    CapabilityValidatorRegistry,
    default_capability_validator_registry,
)
from v2.runtime.codeact_sandbox import CodeActSandboxReadiness, CodeActSandboxResult, CodeActSandboxRunner
from v2.runtime.workspace import ArtifactLifecycleManager
from v2.utils import sha256_digest, stable_json_dumps


_FENCE_RE = re.compile(r"^\s*```(?:python|py)?\s*\n(?P<source>[\s\S]*?)\n?```\s*$", re.IGNORECASE)
_JSON_FENCE_RE = re.compile(r"^\s*```json\s*\n(?P<payload>[\s\S]*?)\n?```\s*$", re.IGNORECASE)
_NAME_ERROR_RE = re.compile(r"NameError:\s+name ['\"](?P<name>[A-Za-z_][A-Za-z0-9_]*)['\"] is not defined")
_FORBIDDEN_CALLS = {"eval", "exec", "compile", "open", "input", "__import__", "getattr", "setattr", "delattr", "globals", "locals", "vars", "help", "dir"}
_FORBIDDEN_NAMES = {"os", "sys", "subprocess", "socket", "requests", "urllib", "http", "shutil", "builtins", "ctypes", "pickle", "marshal", "__file__", "__loader__", "__spec__"}
_FORBIDDEN_ATTRIBUTES = {
    "cwd", "home", "resolve", "absolute", "glob", "rglob", "iterdir", "walk", "environ",
    "system", "popen", "fork", "spawn", "run", "call", "Popen", "unlink", "rename",
    "symlink_to", "hardlink_to", "chmod", "chown", "touch", "mkdir", "rmdir", "unlink",
}
_FORBIDDEN_AST_NODES = (
    ast.ClassDef, ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith,
    ast.Await, ast.Yield, ast.YieldFrom,
)


class CodePolicyError(ValueError):
    pass


def extract_python_source(raw_response: str) -> str:
    """Accept one raw source payload, one fenced block, or a strict {"code": string} wrapper."""
    text = raw_response.strip()
    if not text:
        return ""
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, dict) and set(decoded) == {"code"} and isinstance(decoded["code"], str):
        return decoded["code"].strip() + "\n"
    json_fence = _JSON_FENCE_RE.match(text)
    if json_fence is not None:
        try:
            decoded = json.loads(json_fence.group("payload"))
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict) and set(decoded) == {"code"} and isinstance(decoded["code"], str):
            return decoded["code"].strip() + "\n"
    fence = _FENCE_RE.match(text)
    if fence is not None:
        return fence.group("source").strip() + "\n"
    return text + ("" if text.endswith("\n") else "\n")


def build_code_generation_prompt(request: CodeGenerationRequest) -> str:
    policy = request.policy
    ordered_output_by = request.quality_constraints.get("ordered_output_by")
    output_order_requirement = ""
    if request.expected_output_shape == "array" and isinstance(ordered_output_by, str) and ordered_output_by:
        output_order_requirement = (
            f"For an array output, sort every output object in ascending lexical order by `{ordered_output_by}` before writing JSON. "
            "Do not preserve arbitrary input order.\n"
        )
    input_schema_text = (
        stable_json_dumps(request.authorized_input_schemas)
        if request.authorized_input_schemas
        else stable_json_dumps(request.authorized_input_schema)
    )
    input_paths = tuple(request.policy.allowed_input_relpaths)
    primary_path = input_paths[-1] if input_paths else "inputs/task.json"
    input_instructions = (
        f"The JSON files at {', '.join(input_paths)} are exactly top-level arrays of authorized row objects. "
        "Each file is a distinct verified data artifact. Never concatenate ancestor and derived artifacts by default. "
        f"The authoritative artifact for this stage is {primary_path}; combine another file only when the task goal "
        "explicitly requires a join or union across independent inputs. "
        if len(input_paths) > 1
        else f"The JSON at {primary_path} is exactly a top-level array of authorized row objects. "
    )
    return (
        "You generate one complete pure-Python data transformation file for a sandbox.\n"
        "Return only a Python file or a JSON object with exactly one `code` field.\n"
        f"Allowed imports: {', '.join(policy.allowed_module_roots)}.\n"
        f"Allowed input paths: {', '.join(policy.allowed_input_relpaths)}.\n"
        f"Numeric text mode: {policy.numeric_text_mode}.\n"
        f"The only output path is: {policy.output_relpath}.\n"
        f"Required output fields: {', '.join(policy.output_required_fields)}.\n"
        f"Output schema: {stable_json_dumps(request.output_schema)}.\n"
        f"Output JSON shape: {request.expected_output_shape}.\n"
        f"Task goal: {request.task_goal}.\n"
        f"Operation semantics: {stable_json_dumps(request.operation_semantics)}.\n"
        f"Completion criteria: {stable_json_dumps(request.completion_criteria)}.\n"
        f"Output contract version: {request.output_contract_version}.\n"
        f"Validator ID: {request.validator_id}.\n"
        f"Quality constraints: {stable_json_dumps(request.quality_constraints)}.\n"
        f"Authorized input schema: {input_schema_text}.\n"
        f"Retrieved semantic context: {stable_json_dumps(request.retrieval_context)}.\n"
        f"Compatible memory inputs: {stable_json_dumps(request.memory_inputs)}.\n"
        "Follow the task goal and every operation-semantics requirement exactly, including exact source field names, "
        "the stated statistical method, rounding precision, row ordering, and output field meanings. Do not replace a "
        "named source column with a similar column. Before returning code, audit it against every explicit task constraint: "
        "input selection, missing-value handling, operation order, statistical definition, rounding, and output shape must "
        "each be implemented rather than merely mentioned in comments.\n"
        "Treat every input field whose source profile reports missing_count greater than zero as nullable. At each "
        "arithmetic, ordering, quantile, or reducer expression, either exclude missing/non-numeric values at that exact "
        "expression or impute them only when the task semantics explicitly requires imputation. Preserving a row with "
        "None does not authorize passing None to statistics.mean, sum, min, max, sorted, or arithmetic.\n"
        "Every referenced name must be a Python builtin, explicitly imported, or defined in this file before use. "
        "In particular, using a module namespace such as re, statistics, or collections requires its explicit allowed import.\n"
        f"{input_instructions}Their keys match the authorized schema(s). They are not objects containing task_parameters or source_profile, and they are not "
        "a CSV file. The original dataset path, dataset ID, and CSV path are metadata only and must never be opened. "
        "Use task parameters and the natural-language task goal from this prompt to choose literal filters, while "
        "reading all data values only from that JSON row array.\n"
        "String replacement is allowed only for in-memory text parsing such as removing thousands separators. "
        "Path.replace and every filesystem rename/replace operation remain forbidden.\n"
        "When a numeric cell contains a leading/base value followed by a bracketed range such as "
        "`630308[495000-801000]`, parse only the leading/base numeric token; never concatenate the range bounds "
        "into the value. Remove thousands separators without treating bracket contents as additional digits.\n"
        "Retrieved semantic context is read-only grounding for terminology, locators, and method selection. Compute every "
        "output value from the verified JSON data artifacts; retrieved text never widens file or value authority.\n"
        "When more than one input path is listed, load every listed path with its exact literal, but combine rows only "
        "under an explicit task join/union requirement. Policy rejects code that omits a listed authorized path.\n"
        "Write exactly the required output shape using exactly the schema fields on every output object. "
        "For identifier-like output fields whose names end in `_name`, `_id`, or `_key`, copy the exact canonical "
        "token from the task parameters or authorized input when one exists; do not expand it into a prose label "
        "or concatenate entity and time context. For example, `metric_name` should use the task's canonical "
        "`metric` token. "
        "Derive every numeric value from the authorized input and preserve its row-level provenance through the authorized input.\n"
        f"{output_order_requirement}"
        "Use pathlib.Path only with an exact listed literal path. Read JSON only with Path(...).read_text(encoding='utf-8') "
        "and write the fixed output only with Path(...).write_text(..., encoding='utf-8'). Do not use open or Path.open.\n"
        "Do not use network, subprocesses, environment variables, directory discovery, dynamic imports, "
        "eval/exec, arbitrary paths, shell commands, or any file outside the listed paths.\n"
        "Do not explain the code or emit execution commands.\n"
    )


def code_generation_prompt_bundle_digest(
    request: CodeGenerationRequest,
    *,
    rendered_prompt: str | None = None,
) -> str:
    """Bind CodeAct cache identity to the full prompt, contract, and tool rules."""
    prompt = rendered_prompt if rendered_prompt is not None else build_code_generation_prompt(request)
    return sha256_digest({
        "schema_version": "statebus.code_generation_prompt_bundle.v1",
        "role": "executor",
        "rendered_prompt": prompt,
        "output_contract_template": {
            "output_schema": dict(sorted(request.output_schema.items())),
            "expected_output_shape": request.expected_output_shape,
            "output_contract_version": request.output_contract_version,
            "validator_id": request.validator_id,
            "completion_criteria": request.completion_criteria,
            "quality_constraints": request.quality_constraints,
        },
        "tool_rules": {
            "policy": request.policy.canonical_payload(),
            "forbidden_calls": sorted(_FORBIDDEN_CALLS),
            "forbidden_names": sorted(_FORBIDDEN_NAMES),
            "forbidden_attributes": sorted(_FORBIDDEN_ATTRIBUTES),
            "forbidden_ast_nodes": sorted(node.__name__ for node in _FORBIDDEN_AST_NODES),
        },
    })


def audit_generated_source(source: str, policy: CodeGenerationPolicy) -> CodePolicyReport:
    violations: list[str] = []
    imports: set[str] = set()
    if not source.strip():
        violations.append("empty_source")
    if len(source.encode("utf-8")) > policy.max_source_bytes:
        violations.append("source_too_large")
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        violations.append(f"syntax_error:{exc.lineno or 0}")
        return CodePolicyReport(
            source_hash=sha256_digest(source.encode("utf-8")), passed=False, violations=tuple(violations),
            policy_version=policy.policy_version,
        )
    nodes = list(ast.walk(tree))
    for name in _undefined_global_names(source):
        violations.append(f"undefined_name:{name}")
    path_constructors = _path_constructor_names(nodes)
    path_variables = _path_variable_names(nodes, path_constructors)
    if len(nodes) > policy.max_ast_nodes:
        violations.append("ast_node_budget_exceeded")
    if sum(isinstance(node, (ast.For, ast.While, ast.AsyncFor)) for node in nodes) > policy.max_loop_nodes:
        violations.append("loop_budget_exceeded")
    required_literals = set(policy.allowed_input_relpaths)
    literal_strings = {node.value for node in nodes if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for required in required_literals:
        if required not in literal_strings and required != Path(policy.output_relpath).name:
            violations.append(f"missing_required_path_literal:{required}")
    for node in nodes:
        if isinstance(node, _FORBIDDEN_AST_NODES):
            violations.append(f"forbidden_ast_node:{type(node).__name__}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                imports.add(root)
                if root not in policy.allowed_module_roots:
                    violations.append(f"forbidden_import:{root}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            imports.add(root)
            if not root or root not in policy.allowed_module_roots or node.level:
                violations.append(f"forbidden_import_from:{root or 'relative'}")
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            violations.append(f"forbidden_name:{node.id}")
        elif isinstance(node, ast.Attribute):
            if node.attr == "replace" and _is_path_expression(
                node.value,
                path_variables,
                path_constructors,
            ):
                violations.append("forbidden_path_attribute:replace")
            elif node.attr.startswith("__") or node.attr in _FORBIDDEN_ATTRIBUTES:
                violations.append(f"forbidden_attribute:{node.attr}")
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in _FORBIDDEN_CALLS or name.rsplit(".", 1)[-1] in _FORBIDDEN_CALLS:
                violations.append(f"forbidden_call:{name}")
            if name in path_constructors:
                if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                    violations.append("nonliteral_path")
                else:
                    path = node.args[0].value
                    if path.startswith("/") or ".." in Path(path).parts:
                        violations.append(f"unsafe_path:{path}")
                    elif path not in policy.allowed_input_relpaths and path not in {"outputs", policy.output_relpath}:
                        violations.append(f"unapproved_path:{path}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            # A bare slash is a data delimiter (for example MM/DD/YYYY), not
            # an absolute path. Path(...) calls are checked separately above.
            if (value.startswith("/") and value != "/") or ".." in Path(value).parts:
                violations.append("absolute_or_parent_path_literal")
    if policy.numeric_text_mode == "leading_token":
        for node in nodes:
            if not isinstance(node, ast.Call) or _call_name(node.func).rsplit(".", 1)[-1] != "join":
                continue
            if any(
                isinstance(child, ast.Call) and _call_name(child.func).rsplit(".", 1)[-1] == "isdigit"
                for argument in node.args
                for child in ast.walk(argument)
            ):
                violations.append("unsafe_full_string_digit_concatenation")
    # Require a strict output path literal or filename and protect against code that only reads input.
    if policy.output_relpath not in literal_strings and Path(policy.output_relpath).name not in literal_strings:
        violations.append("missing_output_path")
    if not any(isinstance(node, ast.Call) and _call_name(node.func).rsplit(".", 1)[-1] == "write_text" for node in nodes):
        violations.append("missing_output_write")
    return CodePolicyReport(
        source_hash=sha256_digest(source.encode("utf-8")),
        passed=not violations,
        violations=tuple(sorted(set(violations))),
        ast_node_count=len(nodes),
        import_roots=tuple(sorted(imports)),
        policy_version=policy.policy_version,
    )


def build_code_repair_guidance(
    violations: tuple[str, ...],
    policy: CodeGenerationPolicy,
) -> str:
    """Translate bounded policy/runtime diagnostics into generic repair actions."""
    undefined_names = {
        item.removeprefix("undefined_name:")
        for item in violations
        if item.startswith("undefined_name:")
    }
    runtime_errors = tuple(
        item.removeprefix("runtime_error:")
        for item in violations
        if item.startswith("runtime_error:")
    )
    quality_errors = tuple(
        item.removeprefix("quality_error:")
        for item in violations
        if item.startswith("quality_error:")
    )
    for diagnostic in runtime_errors:
        match = _NAME_ERROR_RE.search(diagnostic)
        if match is not None:
            undefined_names.add(match.group("name"))

    guidance: list[str] = []
    for name in sorted(undefined_names):
        if name in policy.allowed_module_roots:
            guidance.append(
                f"Add the explicit allowed statement `import {name}` before the first use of `{name}`."
            )
        else:
            guidance.append(
                f"Define `{name}` before its first use, correct it to an already-defined name, or import it explicitly "
                "from an allowed module; do not assume hidden globals or add an unauthorized import."
            )
    if runtime_errors:
        guidance.append(
            "The replacement must correct the exact bounded runtime diagnostic and must not repeat the failing source unchanged."
        )
    if quality_errors:
        guidance.append(
            "The prior program passed sandbox and schema checks but its output failed the registered Runtime validator. "
            "Re-derive the result from the authorized input rows and audit every operation against the supplied semantic "
            "contract. The validator intentionally does not disclose expected values."
        )
    return " ".join(guidance)


def _undefined_global_names(source: str) -> tuple[str, ...]:
    """Find unresolved Python globals without executing or importing user code."""
    table = symtable.symtable(source, "<statebus-codeact>", "exec")
    tables: list[symtable.SymbolTable] = []

    def collect(current: symtable.SymbolTable) -> None:
        tables.append(current)
        for child in current.get_children():
            collect(child)

    collect(table)
    globally_bound = {
        symbol.get_name()
        for current in tables
        for symbol in current.get_symbols()
        if (current is table or symbol.is_global())
        and (symbol.is_assigned() or symbol.is_imported() or symbol.is_parameter())
    }
    builtin_names = set(dir(builtins))
    unresolved = {
        symbol.get_name()
        for current in tables
        for symbol in current.get_symbols()
        if symbol.is_referenced()
        and symbol.is_global()
        and symbol.get_name() not in globally_bound
        and symbol.get_name() not in builtin_names
    }
    return tuple(sorted(unresolved))


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value) if isinstance(node.value, (ast.Name, ast.Attribute)) else ""
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _path_constructor_names(nodes: list[ast.AST]) -> set[str]:
    constructors = {"Path", "pathlib.Path"}
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pathlib":
                    constructors.add(f"{alias.asname or alias.name}.Path")
        elif isinstance(node, ast.ImportFrom) and node.module == "pathlib" and node.level == 0:
            for alias in node.names:
                if alias.name == "Path":
                    constructors.add(alias.asname or alias.name)
    return constructors


def _path_variable_names(
    nodes: list[ast.AST],
    path_constructors: set[str],
) -> set[str]:
    assignments: list[tuple[tuple[ast.expr, ...], ast.AST]] = []
    for node in nodes:
        if isinstance(node, ast.Assign):
            assignments.append((tuple(node.targets), node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            assignments.append(((node.target,), node.value))
        elif isinstance(node, ast.NamedExpr):
            assignments.append(((node.target,), node.value))
    path_variables: set[str] = set()
    changed = True
    while changed:
        changed = False
        for targets, value in assignments:
            if not _is_path_expression(value, path_variables, path_constructors):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in path_variables:
                    path_variables.add(target.id)
                    changed = True
    return path_variables


def _is_path_expression(
    node: ast.AST,
    path_variables: set[str],
    path_constructors: set[str],
) -> bool:
    if isinstance(node, ast.Name):
        return node.id in path_variables
    if isinstance(node, ast.Call):
        if _call_name(node.func) in path_constructors:
            return True
        return (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"joinpath", "with_name", "with_stem", "with_suffix"}
            and _is_path_expression(node.func.value, path_variables, path_constructors)
        )
    if isinstance(node, ast.Attribute):
        return _is_path_expression(node.value, path_variables, path_constructors)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _is_path_expression(node.left, path_variables, path_constructors)
    if isinstance(node, ast.IfExp):
        return _is_path_expression(
            node.body,
            path_variables,
            path_constructors,
        ) or _is_path_expression(
            node.orelse,
            path_variables,
            path_constructors,
        )
    return False


@dataclass(frozen=True)
class LlmCodeActOutcome:
    record: CodeExecutionRecord
    policy_report: CodePolicyReport
    repairs: tuple[CodeRepairRecord, ...]
    artifact: ExecutionArtifactRef | None = None
    output_payload: dict[str, Any] | list[dict[str, Any]] | None = None
    quality_report: "CapabilityQualityReport | None" = None
    quality_reports: tuple["CapabilityQualityReport", ...] = ()


@dataclass
class LlmCodeActCache:
    _verified: dict[str, tuple[LlmCodeActOutcome, str, str]] = field(default_factory=dict)

    @staticmethod
    def key(request: CodeGenerationRequest, candidate: GeneratedCodeCandidate) -> str:
        return sha256_digest({
            "task_id": request.task_id,
            "capability_id": request.capability_id,
            "semantic_input_digest": request.input_manifest_digest,
            "source_hash": candidate.source_hash,
            "model_signature": request.model_signature,
            "prompt_signature": request.prompt_signature,
            "runtime_signature": request.runtime_signature,
            "policy": request.policy.policy_digest,
            "output_schema": dict(sorted(request.output_schema.items())),
        })

    def put(self, key: str, outcome: LlmCodeActOutcome, *, task_id: str = "", session_id: str = "") -> None:
        if outcome.artifact is None or outcome.artifact.verification_state != RefStatus.VERIFIED:
            raise ValueError("only_verified_codeact_results_are_cacheable")
        self._verified[key] = (outcome, task_id or outcome.artifact.task_id, session_id)

    def get(
        self,
        key: str,
        *,
        task_id: str,
        session_id: str,
        grant_hash: str,
        authorize_grant: Callable[[str], bool],
        artifact_readable: Callable[[ExecutionArtifactRef], bool],
    ) -> LlmCodeActOutcome | None:
        cached = self._verified.get(key)
        if cached is None or not authorize_grant(grant_hash):
            return None
        outcome, cached_task_id, cached_session_id = cached
        if cached_task_id != task_id or cached_session_id != session_id or outcome.artifact is None:
            return None
        if not artifact_readable(outcome.artifact):
            return None
        return outcome


class LlmCodeActRunner:
    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        sandbox_runner: CodeActSandboxRunner | None = None,
        cache: LlmCodeActCache | None = None,
        validator_registry: CapabilityValidatorRegistry | None = None,
    ) -> None:
        self.registry = registry
        self.sandbox_runner = sandbox_runner or CodeActSandboxRunner()
        self.cache = cache or LlmCodeActCache()
        self.validator_registry = validator_registry or default_capability_validator_registry()
        self._consumed_grant_hashes: set[str] = set()

    def execute(
        self,
        *,
        request: CodeGenerationRequest,
        grant: CapabilityGrant,
        raw_response: str,
        attempt_workspace: Path,
        input_files: dict[str, bytes],
        repair_source: Callable[[str, tuple[str, ...]], str] | None = None,
        model_id: str = "",
    ) -> LlmCodeActOutcome:
        self._validate_request(request, grant)
        if grant.grant_hash in self._consumed_grant_hashes:
            raise CodePolicyError("capability_grant_already_consumed")
        self._consumed_grant_hashes.add(grant.grant_hash)
        source = extract_python_source(raw_response)
        candidate = GeneratedCodeCandidate(
            request_hash=sha256_digest(request.canonical_payload()), source=source,
            source_hash=sha256_digest(source.encode("utf-8")), raw_response_hash=sha256_digest(raw_response.encode("utf-8")),
            model_id=model_id,
        )
        report = audit_generated_source(candidate.source, request.policy)
        repairs: list[CodeRepairRecord] = []
        policy_repair_count = 0
        runtime_repair_count = 0
        quality_repair_count = 0
        while (
            not report.passed
            and repair_source is not None
            and policy_repair_count < request.policy.max_policy_repairs
        ):
            repaired = extract_python_source(repair_source(candidate.source, report.violations))
            policy_repair_count += 1
            repairs.append(CodeRepairRecord(
                attempt_index=len(repairs) + 1, previous_source_hash=candidate.source_hash,
                repaired_source_hash=sha256_digest(repaired.encode("utf-8")), policy_report_hash=report.report_hash,
                repair_kind="policy",
            ))
            candidate = GeneratedCodeCandidate(
                request_hash=candidate.request_hash, source=repaired,
                source_hash=sha256_digest(repaired.encode("utf-8")), raw_response_hash=candidate.raw_response_hash,
                model_id=model_id,
            )
            report = audit_generated_source(candidate.source, request.policy)
        if not report.passed:
            repairs.append(CodeRepairRecord(
                attempt_index=len(repairs) + 1,
                previous_source_hash=candidate.source_hash,
                policy_report_hash=report.report_hash,
                fallback_used=True,
                repair_kind="policy",
            ))
            return self._not_executed(request, grant, candidate, report, tuple(repairs), "code_policy_rejected")
        sandbox_runner = self._sandbox_for_policy(request.policy)
        readiness = sandbox_runner.check_llm_bwrap_readiness(policy_version=request.policy.sandbox_policy_version)
        if not readiness.ready:
            return self._not_executed(request, grant, candidate, report, tuple(repairs), f"bwrap_not_ready:{readiness.reason}", readiness)
        cache_key = self.cache.key(request, candidate)
        cached = self.cache.get(
            cache_key,
            task_id=request.task_id,
            session_id=grant.session_id,
            grant_hash=grant.grant_hash,
            authorize_grant=lambda grant_hash: grant_hash == grant.grant_hash and grant.expires_at_ns >= time.time_ns(),
            artifact_readable=self._artifact_readable,
        )
        if cached is not None:
            return replace(
                cached,
                record=replace(
                    cached.record,
                    request_hash=candidate.request_hash,
                    source_hash=candidate.source_hash,
                    raw_response_hash=candidate.raw_response_hash,
                    policy_report_hash=report.report_hash,
                    input_ref_ids=request.input_ref_ids,
                    fallback_reason="verified_cache_hit",
                ),
                policy_report=report,
                repairs=tuple(repairs),
            )
        execution_workspace = attempt_workspace
        source_path, inputs_dir, outputs_dir = self._materialize_attempt(
            attempt_workspace=execution_workspace, policy=request.policy, source=candidate.source, input_files=input_files,
        )
        runtime_error = ""
        quality_reports = []
        while True:
            while True:
                sandbox_result = sandbox_runner.run_llm_bwrap(
                    source_path=source_path, inputs_dir=inputs_dir, outputs_dir=outputs_dir,
                    policy_version=request.policy.sandbox_policy_version,
                )
                if sandbox_result.actual_backend == "bwrap" and sandbox_result.completed.returncode == 0:
                    break
                runtime_error = self._runtime_diagnostic(sandbox_result)
                # A non-zero Python exit after AST approval is a model-authored
                # program defect. Give the Executor one bounded repair opportunity
                # in a fresh workspace under the same Grant and input authority.
                if (
                    repair_source is None
                    or runtime_repair_count >= request.policy.max_runtime_repairs
                ):
                    failure = self._execution_failure(
                        request, grant, candidate, report, tuple(repairs), readiness,
                        sandbox_result.completed.returncode,
                        sandbox_result.fallback_reason or "bwrap_execution_failed",
                        runtime_error=runtime_error,
                    )
                    return replace(failure, quality_reports=tuple(quality_reports))
                repaired = extract_python_source(repair_source(
                    candidate.source,
                    (
                        f"runtime_error:{runtime_error}",
                        f"runtime_exit_code:{sandbox_result.completed.returncode}",
                    ),
                ))
                runtime_repair_count += 1
                repairs.append(CodeRepairRecord(
                    attempt_index=len(repairs) + 1,
                    previous_source_hash=candidate.source_hash,
                    repaired_source_hash=sha256_digest(repaired.encode("utf-8")),
                    policy_report_hash=report.report_hash,
                    repair_kind="runtime",
                    diagnostic=runtime_error,
                ))
                candidate = GeneratedCodeCandidate(
                    request_hash=candidate.request_hash,
                    source=repaired,
                    source_hash=sha256_digest(repaired.encode("utf-8")),
                    raw_response_hash=candidate.raw_response_hash,
                    model_id=candidate.model_id,
                )
                report = audit_generated_source(candidate.source, request.policy)
                if not report.passed:
                    failure = self._execution_failure(
                        request, grant, candidate, report, tuple(repairs), readiness,
                        sandbox_result.completed.returncode,
                        "runtime_repair_policy_rejected", validator_errors=report.violations,
                        runtime_error=runtime_error,
                    )
                    return replace(failure, quality_reports=tuple(quality_reports))
                execution_workspace = attempt_workspace.parent / f"{attempt_workspace.name}-runtime-repair-{len(repairs)}"
                source_path, inputs_dir, outputs_dir = self._materialize_attempt(
                    attempt_workspace=execution_workspace,
                    policy=request.policy,
                    source=candidate.source,
                    input_files=input_files,
                )

            payload, errors, output_hash = self._validate_output(outputs_dir, request)
            if errors:
                failure = self._execution_failure(
                    request, grant, candidate, report, tuple(repairs), readiness,
                    sandbox_result.completed.returncode,
                    "output_validation_failed", validator_errors=errors, output_hash=output_hash,
                )
                return replace(failure, quality_reports=tuple(quality_reports))
            quality_report = self._validate_capability_quality(
                request=request,
                payload=payload,
                input_files=input_files,
                output_hash=output_hash,
            )
            quality_reports.append(quality_report)
            if quality_report.verified:
                break
            if repair_source is None or quality_repair_count >= request.policy.max_quality_repairs:
                failure = self._execution_failure(
                    request,
                    grant,
                    candidate,
                    report,
                    tuple(repairs),
                    readiness,
                    sandbox_result.completed.returncode,
                    "capability_quality_rejected",
                    validator_errors=quality_report.error_codes,
                    output_hash=output_hash,
                    quality_report_hash=quality_report.report_hash,
                )
                return replace(
                    failure,
                    quality_report=quality_report,
                    quality_reports=tuple(quality_reports),
                )

            quality_diagnostics = tuple(
                f"quality_error:{error}" for error in quality_report.error_codes
            )
            repaired = extract_python_source(repair_source(candidate.source, quality_diagnostics))
            quality_repair_count += 1
            repairs.append(CodeRepairRecord(
                attempt_index=len(repairs) + 1,
                previous_source_hash=candidate.source_hash,
                repaired_source_hash=sha256_digest(repaired.encode("utf-8")),
                policy_report_hash=report.report_hash,
                repair_kind="quality",
                diagnostic=",".join(quality_report.error_codes),
            ))
            candidate = GeneratedCodeCandidate(
                request_hash=candidate.request_hash,
                source=repaired,
                source_hash=sha256_digest(repaired.encode("utf-8")),
                raw_response_hash=candidate.raw_response_hash,
                model_id=candidate.model_id,
            )
            report = audit_generated_source(candidate.source, request.policy)
            if not report.passed:
                failure = self._execution_failure(
                    request, grant, candidate, report, tuple(repairs), readiness,
                    sandbox_result.completed.returncode,
                    "quality_repair_policy_rejected", validator_errors=report.violations,
                )
                return replace(
                    failure,
                    quality_report=quality_report,
                    quality_reports=tuple(quality_reports),
                )
            execution_workspace = attempt_workspace.parent / f"{attempt_workspace.name}-quality-repair-{len(repairs)}"
            source_path, inputs_dir, outputs_dir = self._materialize_attempt(
                attempt_workspace=execution_workspace,
                policy=request.policy,
                source=candidate.source,
                input_files=input_files,
            )
        output_path = outputs_dir / Path(request.policy.output_relpath).name
        artifact_id = f"llm-codeact-{request.task_id}-{request.step_id}-{request.attempt_id}"
        lifecycle = ArtifactLifecycleManager()
        candidate_artifact = lifecycle.register_candidate(ExecutionArtifactRef(
            artifact_id=artifact_id, task_id=request.task_id, step_id=request.step_id,
            artifact_type="json", root_id=str(execution_workspace), relpath=str(output_path.relative_to(execution_workspace)),
            blob_hash=output_hash, size_bytes=output_path.stat().st_size, produced_by="executor",
            workspace_relpath=str(output_path.relative_to(execution_workspace)),
            manifest_hash=request.input_manifest_digest,
            metadata={
                "schema_version": "statebus.llm_codeact_artifact.v1",
                "source_hash": candidate.source_hash,
                "quality_report_hash": quality_report.report_hash,
                "session_id": grant.session_id,
                "attempt_id": grant.attempt_id,
            },
        ))
        artifact = lifecycle.mark_verified(candidate_artifact.artifact_id)
        record = CodeExecutionRecord(
            request_hash=candidate.request_hash, source_hash=candidate.source_hash, raw_response_hash=candidate.raw_response_hash, policy_report_hash=report.report_hash,
            sandbox_requested_backend="bwrap_required", sandbox_actual_backend="bwrap",
            sandbox_readiness_digest=readiness.readiness_digest, sandbox_policy_digest=request.policy.policy_digest,
            sandbox_uid=readiness.sandbox_uid, sandbox_gid=readiness.sandbox_gid,
            mount_policy_digest=self._mount_policy_digest(request.policy), input_ref_ids=request.input_ref_ids,
            output_hash=output_hash, output_schema_valid=True, output_quality_valid=True,
            exit_code=sandbox_result.completed.returncode,
            verified_artifact_id=artifact.artifact_id,
            quality_report_hash=quality_report.report_hash,
        )
        outcome = LlmCodeActOutcome(
            record=record,
            policy_report=report,
            repairs=tuple(repairs),
            artifact=artifact,
            output_payload=payload,
            quality_report=quality_report,
            quality_reports=tuple(quality_reports),
        )
        self.cache.put(self.cache.key(request, candidate), outcome, task_id=request.task_id, session_id=grant.session_id)
        return outcome

    def _validate_request(self, request: CodeGenerationRequest, grant: CapabilityGrant) -> None:
        descriptor = self.registry.get(request.capability_id)
        if request.schema_version != "statebus.code_generation_request.v1":
            raise CodePolicyError("invalid_code_generation_request_schema")
        if not request.policy.enabled:
            raise CodePolicyError("llm_codeact_disabled")
        if not request.policy.require_bwrap:
            raise CodePolicyError("llm_codeact_requires_bwrap")
        if request.policy.capability_id != request.capability_id:
            raise CodePolicyError("policy_capability_mismatch")
        if descriptor.execution_kind != ExecutionKind.LLM_BOUNDED_PYTHON:
            raise CodePolicyError("capability_not_llm_bounded_python")
        if grant.grant_hash != request.capability_grant_hash or grant.capability_id != request.capability_id:
            raise CodePolicyError("capability_grant_mismatch")
        if grant.task_id != request.task_id or grant.step_id != request.step_id or grant.attempt_id != request.attempt_id:
            raise CodePolicyError("grant_scope_mismatch")
        if request.session_id and grant.session_id != request.session_id:
            raise CodePolicyError("grant_session_scope_mismatch")
        if grant.approved_plan_hash != request.approved_plan_hash:
            raise CodePolicyError("approved_plan_hash_mismatch")
        if grant.expires_at_ns < time.time_ns():
            raise CodePolicyError("capability_grant_expired")
        if request.input_ref_ids != grant.input_ref_ids:
            raise CodePolicyError("grant_input_refs_mismatch")
        if not any(self.validator_registry.contains(validator_id) for validator_id in descriptor.validator_ids):
            raise CodePolicyError("capability_quality_validator_unregistered")
        self._validate_policy_paths(request.policy)

    def _validate_capability_quality(
        self,
        *,
        request: CodeGenerationRequest,
        payload: dict[str, Any] | list[dict[str, Any]] | None,
        input_files: dict[str, bytes],
        output_hash: str,
    ):
        if payload is None:
            raise CodePolicyError("missing_output_payload")
        descriptor = self.registry.get(request.capability_id)
        validator_id = request.validator_id or next(
            (item for item in descriptor.validator_ids if self.validator_registry.contains(item)),
            "",
        )
        if not validator_id or validator_id not in descriptor.validator_ids:
            raise CodePolicyError("capability_quality_validator_unregistered")
        input_rows: list[tuple[dict[str, object], ...]] = []
        input_hashes: list[str] = []
        for content in input_files.values():
            input_hashes.append(sha256_digest(content))
            try:
                decoded = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError):
                decoded = None
            if isinstance(decoded, dict):
                input_rows.append((dict(decoded),))
            elif isinstance(decoded, list) and all(isinstance(row, dict) for row in decoded):
                input_rows.append(tuple(dict(row) for row in decoded))
            else:
                input_rows.append(())
        return self.validator_registry.validate(
            CapabilityQualityContext(
                capability_id=request.capability_id,
                validator_id=validator_id,
                input_rows=tuple(input_rows),
                output_rows=(tuple(dict(row) for row in payload) if isinstance(payload, list) else (dict(payload),)),
                input_artifact_hashes=tuple(input_hashes),
                output_artifact_hash=output_hash,
                required_fields=tuple(request.output_schema),
                completion_criteria=request.completion_criteria,
                operation_semantics=request.operation_semantics,
                provenance_item_ids=request.provenance_item_ids or request.input_ref_ids,
            )
        )

    @staticmethod
    def _validate_policy_paths(policy: CodeGenerationPolicy) -> None:
        output = Path(policy.output_relpath)
        if output.is_absolute() or ".." in output.parts or output.parent != Path("outputs") or not output.name:
            raise CodePolicyError("unsafe_output_path_policy")
        if not policy.allowed_input_relpaths or len(set(policy.allowed_input_relpaths)) != len(policy.allowed_input_relpaths):
            raise CodePolicyError("invalid_input_path_policy")
        for relpath in policy.allowed_input_relpaths:
            path = Path(relpath)
            if path.is_absolute() or ".." in path.parts or path.parent != Path("inputs") or not path.name:
                raise CodePolicyError("unsafe_input_path_policy")
        if policy.max_output_bytes < 2 or policy.max_output_bytes > policy.file_size_bytes:
            raise CodePolicyError("invalid_output_byte_budget")
        if not 0 <= policy.max_policy_repairs <= 1:
            raise CodePolicyError("invalid_policy_repair_budget")
        if not 0 <= policy.max_runtime_repairs <= 1:
            raise CodePolicyError("invalid_runtime_repair_budget")
        if not 0 <= policy.max_quality_repairs <= 1:
            raise CodePolicyError("invalid_quality_repair_budget")
        if policy.numeric_text_mode not in {"unrestricted", "leading_token"}:
            raise CodePolicyError("invalid_numeric_text_mode")

    @staticmethod
    def _materialize_attempt(
        *, attempt_workspace: Path, policy: CodeGenerationPolicy, source: str, input_files: dict[str, bytes],
    ) -> tuple[Path, Path, Path]:
        expected = set(policy.allowed_input_relpaths)
        if set(input_files) != expected:
            raise CodePolicyError("input_file_manifest_mismatch")
        attempt_workspace.mkdir(parents=True, exist_ok=True)
        if any(attempt_workspace.iterdir()):
            raise CodePolicyError("attempt_workspace_not_empty")
        generated = attempt_workspace / "generated"
        inputs = attempt_workspace / "inputs"
        outputs = attempt_workspace / "outputs"
        generated.mkdir(parents=True, exist_ok=True)
        inputs.mkdir(parents=True, exist_ok=True)
        outputs.mkdir(parents=True, exist_ok=True)
        for relpath, content in input_files.items():
            target = attempt_workspace / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(0o444)
        inputs.chmod(0o555)
        outputs.chmod(0o777)
        source_path = generated / "llm_generated.py"
        source_path.write_text(source, encoding="utf-8")
        source_path.chmod(0o444)
        return source_path, inputs, outputs

    @staticmethod
    def _validate_output(
        outputs_dir: Path, request: CodeGenerationRequest,
    ) -> tuple[dict[str, Any] | list[dict[str, Any]] | None, tuple[str, ...], str]:
        expected = outputs_dir / Path(request.policy.output_relpath).name
        files = tuple(sorted(path for path in outputs_dir.rglob("*") if path.is_file() or path.is_symlink()))
        if expected not in files or expected.is_symlink():
            return None, ("missing_or_symlink_output",), ""
        if len(files) != 1:
            return None, ("unauthorized_extra_output",), ""
        try:
            raw = expected.read_bytes()
            payload = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None, ("invalid_json_output",), ""
        errors: list[str] = []
        if len(raw) > request.policy.max_output_bytes:
            errors.append("output_byte_budget_exceeded")
        if request.expected_output_shape not in {"object", "array"}:
            errors.append("unsupported_output_shape")
            rows: tuple[dict[str, Any], ...] = ()
        elif request.expected_output_shape == "object":
            if not isinstance(payload, dict):
                errors.append("output_not_object")
                rows = ()
            else:
                rows = (payload,)
        elif not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            errors.append("output_not_object_array")
            rows = ()
        else:
            rows = tuple(payload)
        if request.expected_output_shape == "array" and not rows:
            errors.append("output_array_empty")
        expected_fields = set(request.output_schema)
        for row in rows:
            if set(row) != expected_fields:
                errors.append("output_schema_fields_mismatch")
            for key, expected_type in request.output_schema.items():
                value = row.get(key)
                if expected_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(float(value))):
                    errors.append(f"output_type:{key}")
                elif expected_type == "string" and not isinstance(value, str):
                    errors.append(f"output_type:{key}")
                elif expected_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                    errors.append(f"output_type:{key}")
                elif expected_type == "boolean" and not isinstance(value, bool):
                    errors.append(f"output_type:{key}")
            if not set(request.policy.output_required_fields) <= set(row):
                errors.append("required_output_fields_missing")
        accepted = payload if isinstance(payload, dict) or (isinstance(payload, list) and all(isinstance(row, dict) for row in payload)) else None
        return accepted, tuple(sorted(set(errors))), sha256_digest(raw)

    @staticmethod
    def _artifact_readable(artifact: ExecutionArtifactRef) -> bool:
        if artifact.verification_state != RefStatus.VERIFIED:
            return False
        path = Path(artifact.root_id) / artifact.relpath
        try:
            return path.is_file() and not path.is_symlink() and sha256_digest(path.read_bytes()) == artifact.blob_hash
        except OSError:
            return False

    def _not_executed(
        self, request: CodeGenerationRequest, grant: CapabilityGrant, candidate: GeneratedCodeCandidate,
        report: CodePolicyReport, repairs: tuple[CodeRepairRecord, ...], reason: str,
        readiness: CodeActSandboxReadiness | None = None,
    ) -> LlmCodeActOutcome:
        readiness = readiness or self._sandbox_for_policy(request.policy).check_llm_bwrap_readiness(policy_version=request.policy.sandbox_policy_version)
        return LlmCodeActOutcome(
            record=CodeExecutionRecord(
                request_hash=candidate.request_hash, source_hash=candidate.source_hash, raw_response_hash=candidate.raw_response_hash, policy_report_hash=report.report_hash,
                sandbox_requested_backend="bwrap_required", sandbox_actual_backend=readiness.actual_backend,
                sandbox_readiness_digest=readiness.readiness_digest, sandbox_policy_digest=request.policy.policy_digest,
                sandbox_uid=readiness.sandbox_uid, sandbox_gid=readiness.sandbox_gid,
                mount_policy_digest=self._mount_policy_digest(request.policy), input_ref_ids=request.input_ref_ids,
                fallback_reason=reason, validator_errors=report.violations,
            ), policy_report=report, repairs=repairs,
        )

    def _execution_failure(
        self, request: CodeGenerationRequest, grant: CapabilityGrant, candidate: GeneratedCodeCandidate,
        report: CodePolicyReport, repairs: tuple[CodeRepairRecord, ...], readiness: CodeActSandboxReadiness,
        exit_code: int, reason: str, *, validator_errors: tuple[str, ...] = (), output_hash: str = "",
        quality_report_hash: str = "", runtime_error: str = "",
    ) -> LlmCodeActOutcome:
        del grant
        return LlmCodeActOutcome(
            record=CodeExecutionRecord(
                request_hash=candidate.request_hash, source_hash=candidate.source_hash, raw_response_hash=candidate.raw_response_hash, policy_report_hash=report.report_hash,
                sandbox_requested_backend="bwrap_required", sandbox_actual_backend="bwrap",
                sandbox_readiness_digest=readiness.readiness_digest, sandbox_policy_digest=request.policy.policy_digest,
                sandbox_uid=readiness.sandbox_uid, sandbox_gid=readiness.sandbox_gid,
                mount_policy_digest=self._mount_policy_digest(request.policy), input_ref_ids=request.input_ref_ids,
                output_hash=output_hash, exit_code=exit_code, timeout=exit_code == 124,
                fallback_reason=reason, validator_errors=validator_errors,
                quality_report_hash=quality_report_hash,
                runtime_error=runtime_error,
            ), policy_report=report, repairs=repairs,
        )

    @staticmethod
    def _runtime_diagnostic(sandbox_result: CodeActSandboxResult) -> str:
        completed = sandbox_result.completed
        raw = (completed.stderr or completed.stdout or sandbox_result.fallback_reason or "sandbox_execution_failed").strip()
        # Keep the model repair context and persisted audit bounded. The full
        # generated source and workspace remain available in the attempt tree.
        return raw[-4_000:]

    @staticmethod
    def _mount_policy_digest(policy: CodeGenerationPolicy) -> str:
        return sha256_digest({
            "source": "ro:/sandbox/generated.py", "inputs": list(policy.allowed_input_relpaths),
            "output": policy.output_relpath, "network": "unshared", "repo_mounted": False,
        })

    def _sandbox_for_policy(self, policy: CodeGenerationPolicy) -> CodeActSandboxRunner:
        if not hasattr(self.sandbox_runner, "config"):
            # Deterministic tests may provide a readiness-only fail-closed double.
            return self.sandbox_runner
        config = replace(
            self.sandbox_runner.config,
            timeout_seconds=policy.timeout_seconds,
            cpu_seconds=policy.cpu_seconds,
            address_space_bytes=policy.address_space_bytes,
            file_size_bytes=policy.file_size_bytes,
            nofile_limit=policy.nofile_limit,
            llm_nproc_limit=policy.nproc_limit,
        )
        return CodeActSandboxRunner(config)
