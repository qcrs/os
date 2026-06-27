from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from v2.contracts.constants import (
    CANONICAL_TASK_SPEC_SCHEMA_VERSION,
    REF_REGISTRY_SCHEMA_VERSION,
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
    HYDRATE_MANIFEST = "hydrate_manifest"
    CANONICAL_EVIDENCE_PACK = "canonical_evidence_pack"


class StorageKind(StrEnum):
    SHARED_MEMORY = "shared_memory"
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
class TaskCompilerInput:
    request_text: str
    task_mode: TaskMode
    corpus_family: str = ""
    requested_outputs: tuple[str, ...] = ()


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
