from __future__ import annotations

from dataclasses import dataclass, field

from v2.contracts.constants import (
    CODE_EXECUTION_RECORD_SCHEMA_VERSION,
    CODE_EXECUTION_REQUEST_SCHEMA_VERSION,
    CODE_GENERATION_POLICY_SCHEMA_VERSION,
    CODE_GENERATION_REQUEST_SCHEMA_VERSION,
    CODE_POLICY_REPORT_SCHEMA_VERSION,
    CODE_REPAIR_RECORD_SCHEMA_VERSION,
    GENERATED_CODE_CANDIDATE_SCHEMA_VERSION,
)
from v2.utils import sha256_digest


@dataclass(frozen=True)
class CodeGenerationPolicy:
    capability_id: str
    enabled: bool = False
    require_bwrap: bool = True
    allowed_module_roots: tuple[str, ...] = ("json", "math", "statistics", "pathlib", "collections")
    allowed_input_relpaths: tuple[str, ...] = ("inputs/task.json",)
    output_relpath: str = "outputs/result.json"
    output_required_fields: tuple[str, ...] = ()
    max_source_bytes: int = 24_000
    max_ast_nodes: int = 1_200
    max_loop_nodes: int = 8
    max_output_bytes: int = 1_048_576
    timeout_seconds: float = 15.0
    cpu_seconds: int = 15
    address_space_bytes: int = 2 * 1024 * 1024 * 1024
    file_size_bytes: int = 64 * 1024 * 1024
    nofile_limit: int = 128
    nproc_limit: int = 65_536
    max_policy_repairs: int = 1
    max_runtime_repairs: int = 1
    max_quality_repairs: int = 1
    numeric_text_mode: str = "unrestricted"
    policy_version: str = "statebus.llm_code_policy.v1"
    sandbox_policy_version: str = "statebus.llm_bwrap.v1"
    schema_version: str = CODE_GENERATION_POLICY_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "enabled": self.enabled,
            "require_bwrap": self.require_bwrap,
            "allowed_module_roots": list(self.allowed_module_roots),
            "allowed_input_relpaths": list(self.allowed_input_relpaths),
            "output_relpath": self.output_relpath,
            "output_required_fields": list(self.output_required_fields),
            "max_source_bytes": self.max_source_bytes,
            "max_ast_nodes": self.max_ast_nodes,
            "max_loop_nodes": self.max_loop_nodes,
            "max_output_bytes": self.max_output_bytes,
            "timeout_seconds": self.timeout_seconds,
            "cpu_seconds": self.cpu_seconds,
            "address_space_bytes": self.address_space_bytes,
            "file_size_bytes": self.file_size_bytes,
            "nofile_limit": self.nofile_limit,
            "nproc_limit": self.nproc_limit,
            "max_policy_repairs": self.max_policy_repairs,
            "max_runtime_repairs": self.max_runtime_repairs,
            "max_quality_repairs": self.max_quality_repairs,
            "numeric_text_mode": self.numeric_text_mode,
            "policy_version": self.policy_version,
            "sandbox_policy_version": self.sandbox_policy_version,
            "schema_version": self.schema_version,
        }

    @property
    def policy_digest(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class CodeGenerationRequest:
    task_id: str
    step_id: str
    attempt_id: str
    approved_plan_hash: str
    capability_grant_hash: str
    capability_id: str
    input_ref_ids: tuple[str, ...]
    input_manifest_digest: str
    output_schema: dict[str, str]
    model_signature: str
    prompt_signature: str
    runtime_signature: str
    policy: CodeGenerationPolicy
    session_id: str = ""
    # These fields are controller-produced execution semantics.  They give the
    # Executor enough information to write an analysis program without giving
    # it authority over inputs, validators, paths, or output acceptance.
    task_goal: str = ""
    operation_semantics: dict[str, object] = field(default_factory=dict)
    completion_criteria: dict[str, object] = field(default_factory=dict)
    output_contract_version: str = ""
    validator_id: str = ""
    quality_constraints: dict[str, object] = field(default_factory=dict)
    authorized_input_schema: dict[str, str] = field(default_factory=dict)
    # When a Planner selects a multi-stage analysis, each verified artifact is
    # exposed through one fixed input file.  Keep the per-file schema explicit
    # instead of merging columns from unrelated upstream artifacts.
    authorized_input_schemas: dict[str, dict[str, str]] = field(default_factory=dict)
    expected_output_shape: str = "object"
    provenance_item_ids: tuple[str, ...] = ()
    retrieval_context: tuple[dict[str, object], ...] = ()
    memory_inputs: tuple[dict[str, object], ...] = ()
    recipe_parameter_schema: dict[str, str] = field(default_factory=dict)
    recipe_parameter_bindings: dict[str, object] = field(default_factory=dict)
    recipe_parameter_relpath: str = ""
    schema_version: str = CODE_GENERATION_REQUEST_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "step_id": self.step_id,
            "attempt_id": self.attempt_id,
            "approved_plan_hash": self.approved_plan_hash,
            "capability_grant_hash": self.capability_grant_hash,
            "capability_id": self.capability_id,
            "input_ref_ids": list(self.input_ref_ids),
            "input_manifest_digest": self.input_manifest_digest,
            "output_schema": dict(sorted(self.output_schema.items())),
            "task_goal": self.task_goal,
            "operation_semantics": self.operation_semantics,
            "completion_criteria": self.completion_criteria,
            "output_contract_version": self.output_contract_version,
            "validator_id": self.validator_id,
            "quality_constraints": self.quality_constraints,
            "authorized_input_schema": dict(sorted(self.authorized_input_schema.items())),
            "authorized_input_schemas": {
                path: dict(sorted(schema.items()))
                for path, schema in sorted(self.authorized_input_schemas.items())
            },
            "expected_output_shape": self.expected_output_shape,
            "provenance_item_ids": list(self.provenance_item_ids),
            "retrieval_context": [dict(item) for item in self.retrieval_context],
            "memory_inputs": [dict(item) for item in self.memory_inputs],
            "recipe_parameter_schema": dict(sorted(self.recipe_parameter_schema.items())),
            "recipe_parameter_bindings": dict(sorted(self.recipe_parameter_bindings.items())),
            "recipe_parameter_relpath": self.recipe_parameter_relpath,
            "model_signature": self.model_signature,
            "prompt_signature": self.prompt_signature,
            "runtime_signature": self.runtime_signature,
            "policy": self.policy.canonical_payload(),
            "session_id": self.session_id,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class GeneratedCodeCandidate:
    request_hash: str
    source: str
    source_hash: str
    raw_response_hash: str
    model_id: str = ""
    schema_version: str = GENERATED_CODE_CANDIDATE_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "request_hash": self.request_hash,
            "source_hash": self.source_hash,
            "raw_response_hash": self.raw_response_hash,
            "model_id": self.model_id,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class CodePolicyReport:
    source_hash: str
    passed: bool
    violations: tuple[str, ...] = ()
    ast_node_count: int = 0
    import_roots: tuple[str, ...] = ()
    policy_version: str = "statebus.llm_code_policy.v1"
    schema_version: str = CODE_POLICY_REPORT_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "source_hash": self.source_hash,
            "passed": self.passed,
            "violations": list(self.violations),
            "ast_node_count": self.ast_node_count,
            "import_roots": list(self.import_roots),
            "policy_version": self.policy_version,
            "schema_version": self.schema_version,
        }

    @property
    def report_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class CodeRepairRecord:
    attempt_index: int
    previous_source_hash: str
    repaired_source_hash: str = ""
    policy_report_hash: str = ""
    fallback_used: bool = False
    repair_kind: str = "policy"
    diagnostic: str = ""
    schema_version: str = CODE_REPAIR_RECORD_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "attempt_index": self.attempt_index,
            "previous_source_hash": self.previous_source_hash,
            "repaired_source_hash": self.repaired_source_hash,
            "policy_report_hash": self.policy_report_hash,
            "fallback_used": self.fallback_used,
            "repair_kind": self.repair_kind,
            "diagnostic": self.diagnostic,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class CodeExecutionRequest:
    generation_request: CodeGenerationRequest
    candidate: GeneratedCodeCandidate
    attempt_workspace: str
    schema_version: str = CODE_EXECUTION_REQUEST_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "generation_request_hash": sha256_digest(self.generation_request.canonical_payload()),
            "candidate": self.candidate.canonical_payload(),
            "attempt_workspace": self.attempt_workspace,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class CodeExecutionRecord:
    request_hash: str
    source_hash: str
    raw_response_hash: str
    policy_report_hash: str
    sandbox_requested_backend: str
    sandbox_actual_backend: str
    sandbox_readiness_digest: str
    sandbox_policy_digest: str
    sandbox_uid: int
    sandbox_gid: int
    mount_policy_digest: str
    input_ref_ids: tuple[str, ...]
    output_hash: str = ""
    output_schema_valid: bool = False
    output_quality_valid: bool = False
    exit_code: int = -1
    timeout: bool = False
    fallback_reason: str = ""
    validator_errors: tuple[str, ...] = ()
    quality_report_hash: str = ""
    verified_artifact_id: str = ""
    runtime_error: str = ""
    schema_version: str = CODE_EXECUTION_RECORD_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "request_hash": self.request_hash,
            "source_hash": self.source_hash,
            "raw_response_hash": self.raw_response_hash,
            "policy_report_hash": self.policy_report_hash,
            "sandbox_requested_backend": self.sandbox_requested_backend,
            "sandbox_actual_backend": self.sandbox_actual_backend,
            "sandbox_readiness_digest": self.sandbox_readiness_digest,
            "sandbox_policy_digest": self.sandbox_policy_digest,
            "sandbox_uid": self.sandbox_uid,
            "sandbox_gid": self.sandbox_gid,
            "mount_policy_digest": self.mount_policy_digest,
            "input_ref_ids": list(self.input_ref_ids),
            "output_hash": self.output_hash,
            "output_schema_valid": self.output_schema_valid,
            "output_quality_valid": self.output_quality_valid,
            "exit_code": self.exit_code,
            "timeout": self.timeout,
            "fallback_reason": self.fallback_reason,
            "validator_errors": list(self.validator_errors),
            "quality_report_hash": self.quality_report_hash,
            "verified_artifact_id": self.verified_artifact_id,
            "runtime_error": self.runtime_error,
            "schema_version": self.schema_version,
        }
