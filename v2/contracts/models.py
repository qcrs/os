from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from v2.contracts.constants import (
    CANONICAL_TASK_SPEC_SCHEMA_VERSION,
    HYDRATION_ACCOUNTING_AUDIT_SCHEMA_VERSION,
    PLANNER_HANDOFF_SCHEMA_VERSION,
    REF_REGISTRY_SCHEMA_VERSION,
    ROLE_PROMPT_SLICE_SCHEMA_VERSION,
    RUNTIME_SIGNATURE_MANIFEST_BUNDLE_SCHEMA_VERSION,
    RUNTIME_COMPATIBILITY_SCHEMA_VERSION,
)
from v2.utils import sha256_digest


class TaskMode(StrEnum):
    BENCHMARK_STRICT = "benchmark_strict"
    INTERACTIVE = "interactive"


class CompilerStatus(StrEnum):
    COMPILED = "compiled"
    OPAQUE_FREEFORM = "opaque_freeform"
    REJECTED = "rejected"


class StepLifecycleState(StrEnum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    ACKED = "ACKED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TRAPPED = "TRAPPED"
    CANCELLED = "CANCELLED"
    GC_PENDING = "GC_PENDING"
    GC_DONE = "GC_DONE"


class ReplayClass(StrEnum):
    DISALLOWED = "disallowed"
    ASSIST = "assist"
    VALIDATED_REPLAY = "validated_replay"
    EXACT_REPLAY = "exact_replay"


class CompatibilityVerdict(StrEnum):
    COMPATIBLE = "compatible"
    DEGRADED = "degraded"
    INCOMPATIBLE = "incompatible"


class RefKind(StrEnum):
    SEMANTIC_STATE = "semantic_state"
    EXECUTION_ARTIFACT = "execution_artifact"
    MEMORY = "memory"
    HYDRATE_MANIFEST = "hydrate_manifest"
    CANONICAL_EVIDENCE_PACK = "canonical_evidence_pack"
    LOGIT_STATE = "logit_state"


class StorageKind(StrEnum):
    SHARED_MEMORY = "shared_memory"
    MEMFD = "memfd"
    MMAP_FILE = "mmap_file"
    CAS_SIDECAR = "cas_sidecar"
    WORKSPACE_ROOT = "workspace_root"
    INLINE = "inline"


class RefStatus(StrEnum):
    ACTIVE = "active"
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    INVALIDATED = "invalidated"


@dataclass(frozen=True)
class HydrationRoleAccounting:
    role: str
    selected_stable_keys: tuple[str, ...] = ()
    external_text_bytes: int = 0
    external_text_item_count: int = 0
    table_bytes: int = 0
    table_item_count: int = 0
    artifact_bytes: int = 0
    artifact_item_count: int = 0
    memory_bytes: int = 0
    memory_item_count: int = 0
    external_evidence_bytes: int = 0
    total_prompt_visible_bytes: int = 0
    non_external_prompt_visible_bytes: int = 0
    total_prompt_visible_item_count: int = 0
    prompt_scaffolding_bytes: int = 0
    prompt_bytes: int = 0
    prompt_slice_ref_id: str = ""
    prompt_slice_root_id: str = ""
    prompt_slice_relpath: str = ""
    prompt_slice_blob_hash: str = ""
    prompt_slice_size_bytes: int = 0
    prompt_slice_schema_version: str = ROLE_PROMPT_SLICE_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "role": self.role,
            "selected_stable_keys": list(self.selected_stable_keys),
            "external_text_bytes": self.external_text_bytes,
            "external_text_item_count": self.external_text_item_count,
            "table_bytes": self.table_bytes,
            "table_item_count": self.table_item_count,
            "artifact_bytes": self.artifact_bytes,
            "artifact_item_count": self.artifact_item_count,
            "memory_bytes": self.memory_bytes,
            "memory_item_count": self.memory_item_count,
            "external_evidence_bytes": self.external_evidence_bytes,
            "total_prompt_visible_bytes": self.total_prompt_visible_bytes,
            "non_external_prompt_visible_bytes": self.non_external_prompt_visible_bytes,
            "total_prompt_visible_item_count": self.total_prompt_visible_item_count,
            "prompt_scaffolding_bytes": self.prompt_scaffolding_bytes,
            "prompt_bytes": self.prompt_bytes,
            "prompt_slice_ref_id": self.prompt_slice_ref_id,
            "prompt_slice_root_id": self.prompt_slice_root_id,
            "prompt_slice_relpath": self.prompt_slice_relpath,
            "prompt_slice_blob_hash": self.prompt_slice_blob_hash,
            "prompt_slice_size_bytes": self.prompt_slice_size_bytes,
            "prompt_slice_schema_version": self.prompt_slice_schema_version,
        }


@dataclass(frozen=True)
class HydrationAccountingAudit:
    task_id: str
    evidence_pack_id: str
    evidence_pack_hash: str
    hydrate_manifest_id: str
    hydrate_manifest_hash: str
    evidence_locator_count: int
    counting_scope: str
    raw_evidence_bytes_seen_by_llm: int
    prompt_visible_total_bytes: int
    non_external_prompt_visible_bytes: int
    prompt_scaffolding_bytes_total: int
    semantic_pruning_enabled: bool
    roles: tuple[HydrationRoleAccounting, ...] = ()
    schema_version: str = HYDRATION_ACCOUNTING_AUDIT_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "evidence_pack_id": self.evidence_pack_id,
            "evidence_pack_hash": self.evidence_pack_hash,
            "hydrate_manifest_id": self.hydrate_manifest_id,
            "hydrate_manifest_hash": self.hydrate_manifest_hash,
            "evidence_locator_count": self.evidence_locator_count,
            "counting_scope": self.counting_scope,
            "raw_evidence_bytes_seen_by_llm": self.raw_evidence_bytes_seen_by_llm,
            "prompt_visible_total_bytes": self.prompt_visible_total_bytes,
            "non_external_prompt_visible_bytes": self.non_external_prompt_visible_bytes,
            "prompt_scaffolding_bytes_total": self.prompt_scaffolding_bytes_total,
            "semantic_pruning_enabled": self.semantic_pruning_enabled,
            "roles": [role.canonical_payload() for role in self.roles],
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class TaskCompilerInput:
    request_text: str
    task_mode: TaskMode
    corpus_family: str = ""
    requested_outputs: tuple[str, ...] = ()
    precompiled_canonical_task_spec: "CanonicalTaskSpec | None" = None


@dataclass(frozen=True)
class CanonicalTaskSpec:
    task_family: str
    intent_op: str
    target_entities: tuple[str, ...] = ()
    time_scope: str = ""
    required_outputs: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    arguments: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CANONICAL_TASK_SPEC_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "task_family": self.task_family,
            "intent_op": self.intent_op,
            "target_entities": list(self.target_entities),
            "time_scope": self.time_scope,
            "required_outputs": list(self.required_outputs),
            "required_tools": list(self.required_tools),
            "arguments": dict(sorted(self.arguments.items())),
            "schema_version": self.schema_version,
        }

    @property
    def spec_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class PlannerHandoff:
    task_id: str
    canonical_task_spec_hash: str
    retrieval_objective: dict[str, Any] = field(default_factory=dict)
    planner_plan_payload: dict[str, Any] = field(default_factory=dict)
    planner_scope_payload: dict[str, Any] = field(default_factory=dict)
    summary_hint: str = ""
    semantic_plan_audit: dict[str, Any] = field(default_factory=dict)
    retriever_consumed_objective_hashes: dict[str, str] = field(default_factory=dict)
    planner_raw_output_hash: str = ""
    schema_version: str = PLANNER_HANDOFF_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "canonical_task_spec_hash": self.canonical_task_spec_hash,
            "retrieval_objective": dict(sorted(self.retrieval_objective.items())),
            "planner_plan_payload": dict(sorted(self.planner_plan_payload.items())),
            "planner_scope_payload": dict(sorted(self.planner_scope_payload.items())),
            "summary_hint": self.summary_hint,
            "semantic_plan_audit": dict(self.semantic_plan_audit),
            "retriever_consumed_objective_hashes": dict(
                sorted(self.retriever_consumed_objective_hashes.items())
            ),
            "planner_raw_output_hash": self.planner_raw_output_hash,
            "schema_version": self.schema_version,
        }

    @property
    def handoff_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class TaskCompilerResult:
    status: CompilerStatus
    canonical_task_spec: CanonicalTaskSpec | None
    compiler_warnings: tuple[str, ...] = ()
    compiler_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeCompatibilitySignature:
    os_digest: str
    python_digest: str
    dependency_digest: str
    tool_registry_digest: str
    prompt_bundle_digest: str
    extractor_bundle_digest: str
    combined_digest: str = ""
    schema_version: str = RUNTIME_COMPATIBILITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.combined_digest:
            object.__setattr__(self, "combined_digest", sha256_digest(self.structured_payload()))

    def structured_payload(self) -> dict[str, str]:
        return {
            "os_digest": self.os_digest,
            "python_digest": self.python_digest,
            "dependency_digest": self.dependency_digest,
            "tool_registry_digest": self.tool_registry_digest,
            "prompt_bundle_digest": self.prompt_bundle_digest,
            "extractor_bundle_digest": self.extractor_bundle_digest,
            "schema_version": self.schema_version,
        }

    def compare(self, other: "RuntimeCompatibilitySignature") -> CompatibilityVerdict:
        if self.combined_digest == other.combined_digest:
            return CompatibilityVerdict.COMPATIBLE
        if (
            self.tool_registry_digest != other.tool_registry_digest
            or self.prompt_bundle_digest != other.prompt_bundle_digest
            or self.extractor_bundle_digest != other.extractor_bundle_digest
        ):
            return CompatibilityVerdict.INCOMPATIBLE
        return CompatibilityVerdict.DEGRADED


@dataclass(frozen=True)
class RuntimeSignatureManifestBundle:
    prompt_manifests: tuple[dict[str, Any], ...] = ()
    extractor_manifests: tuple[dict[str, Any], ...] = ()
    tool_registry_manifests: tuple[dict[str, Any], ...] = ()
    schema_version: str = RUNTIME_SIGNATURE_MANIFEST_BUNDLE_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "prompt_manifests": list(self.prompt_manifests),
            "extractor_manifests": list(self.extractor_manifests),
            "tool_registry_manifests": list(self.tool_registry_manifests),
            "schema_version": self.schema_version,
        }

    @property
    def manifest_bundle_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class RefRegistryEntry:
    ref_id: str
    ref_kind: RefKind
    storage_kind: StorageKind
    status: RefStatus
    blob_hash: str = ""
    manifest_hash: str = ""
    root_id: str = ""
    relpath: str = ""
    workspace_relpath: str = ""
    schema_version: str = REF_REGISTRY_SCHEMA_VERSION

    def small_index_payload(self) -> dict[str, str]:
        return {
            "ref_id": self.ref_id,
            "ref_kind": self.ref_kind.value,
            "storage_kind": self.storage_kind.value,
            "status": self.status.value,
            "blob_hash": self.blob_hash,
            "manifest_hash": self.manifest_hash,
            "root_id": self.root_id,
            "relpath": self.relpath,
            "workspace_relpath": self.workspace_relpath,
            "schema_version": self.schema_version,
        }
