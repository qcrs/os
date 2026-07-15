from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
import shutil

from v2.contracts import (
    CanonicalTaskSpec,
    HydrationAccountingAudit,
    HydrationRoleAccounting,
    RefKind,
    RefRegistryEntry,
    RefStatus,
    ReplayClass,
    StorageKind,
)
from v2.provenance import (
    evidence_pack_from_dict,
    evidence_pack_to_dict,
    manifest_from_dict,
    manifest_to_dict,
)
from v2.memory import (
    MemoryCommit,
    MemoryCandidatePool,
    MemoryCommitStatus,
    MemoryMatch,
    MemoryMatchResult,
    MemoryRef,
    MemoryRerankItem,
    MemoryRerankResult,
    MemoryType,
    MemoryValidationStatus,
    StructuredEmbedding,
)
from v2.refs import CanonicalEvidencePack, HydrateManifest
from v2.retrieval import RetrievalBundle
from v2.retrieval.models import EvidencePruningHint, RetrievalPruningBucketStat, RetrievalPruningProfile
from v2.runtime.codeact import (
    CodeActAction,
    CodeActExecutionRecord,
    CodeActPlan,
    CodeActStage,
    CodeActStageResult,
    CodeActActionResult,
)
from v2.runtime.execution import ExecutionLogCapture, ExecutionStepRecord
from v2.runtime.fallback import FallbackAction, FallbackDag
from v2.runtime.ledger import ReplayLedgerEntry
from v2.runtime.session import (
    RuntimeLeaseConfig,
    RuntimeReplanRecord,
    RuntimeTaskSession,
    RuntimeWorkflowStep,
    StepAttemptRecord,
)
from v2.runtime.workspace import (
    ArtifactInvalidationRecord,
    ArtifactManifestItem,
    ArtifactOutputManifest,
    ArtifactSettlementRecord,
    ArtifactValidatorReport,
    InputManifest,
    InputManifestItem,
    InputValidatorReport,
    MaterializedFile,
)
from v2.utils import stable_json_dumps


class RefManifestMissingError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class PersistedContractPaths:
    registry_path: Path
    hydrate_manifest_path: Path | None = None
    evidence_pack_path: Path | None = None
    hydration_accounting_audit_path: Path | None = None
    input_manifest_path: Path | None = None
    artifact_manifest_path: Path | None = None
    embedding_path: Path | None = None
    memory_commit_path: Path | None = None
    memory_match_result_path: Path | None = None
    retrieval_log_path: Path | None = None
    retrieval_candidate_pool_path: Path | None = None
    retrieval_candidate_payload_path: Path | None = None
    retrieval_rerank_result_path: Path | None = None
    retrieval_pruning_profile_path: Path | None = None
    session_path: Path | None = None
    validator_report_paths: tuple[Path, ...] = ()
    replay_ledger_path: Path | None = None
    execution_step_path: Path | None = None
    codeact_plan_audit_path: Path | None = None
    codeact_record_audit_path: Path | None = None
    fallback_dag_path: Path | None = None
    input_validator_report_paths: tuple[Path, ...] = ()
    artifact_settlement_path: Path | None = None
    artifact_invalidation_path: Path | None = None


@dataclass(frozen=True)
class RefRegistryQuery:
    ref_kind: RefKind | None = None
    status: RefStatus | None = None
    storage_kind: StorageKind | None = None
    manifest_hash: str = ""
    root_id: str = ""
    relpath_prefix: str = ""


@dataclass
class _JsonWriteSpec:
    path: Path
    payload: object
    source_path: Path | None = None
    trusted_source: bool = False


@dataclass
class JsonContractStore:
    root: Path

    def __post_init__(self) -> None:
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.sidecar_hydrate_dir.mkdir(parents=True, exist_ok=True)
        self.sidecar_evidence_dir.mkdir(parents=True, exist_ok=True)
        self.sidecar_hydration_accounting_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_manifest_dir.mkdir(parents=True, exist_ok=True)
        self.input_manifest_dir.mkdir(parents=True, exist_ok=True)
        self.memory_commit_dir.mkdir(parents=True, exist_ok=True)
        self.memory_match_dir.mkdir(parents=True, exist_ok=True)
        self.embedding_dir.mkdir(parents=True, exist_ok=True)
        self.retrieval_log_dir.mkdir(parents=True, exist_ok=True)
        self.retrieval_candidate_pool_dir.mkdir(parents=True, exist_ok=True)
        self.retrieval_candidate_payload_dir.mkdir(parents=True, exist_ok=True)
        self.retrieval_rerank_dir.mkdir(parents=True, exist_ok=True)
        self.retrieval_pruning_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_session_dir.mkdir(parents=True, exist_ok=True)
        self.validator_report_dir.mkdir(parents=True, exist_ok=True)
        self.replay_ledger_dir.mkdir(parents=True, exist_ok=True)
        self.execution_step_dir.mkdir(parents=True, exist_ok=True)
        self.codeact_plan_audit_dir.mkdir(parents=True, exist_ok=True)
        self.codeact_record_audit_dir.mkdir(parents=True, exist_ok=True)
        self.fallback_dag_dir.mkdir(parents=True, exist_ok=True)
        self.input_validator_report_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_settlement_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_invalidation_dir.mkdir(parents=True, exist_ok=True)

    @property
    def registry_dir(self) -> Path:
        return self.root / "registry"

    @property
    def registry_path(self) -> Path:
        return self.registry_dir / "ref_registry.json"

    @property
    def sidecar_hydrate_dir(self) -> Path:
        return self.root / "sidecars" / "hydrate_manifests"

    @property
    def sidecar_evidence_dir(self) -> Path:
        return self.root / "sidecars" / "evidence_packs"

    @property
    def sidecar_hydration_accounting_dir(self) -> Path:
        return self.root / "sidecars" / "hydration_accounting_audits"

    @property
    def artifact_manifest_dir(self) -> Path:
        return self.root / "manifests" / "artifacts"

    @property
    def input_manifest_dir(self) -> Path:
        return self.root / "manifests" / "inputs"

    @property
    def memory_commit_dir(self) -> Path:
        return self.root / "sidecars" / "memory_commits"

    @property
    def memory_match_dir(self) -> Path:
        return self.root / "sidecars" / "memory_matches"

    @property
    def embedding_dir(self) -> Path:
        return self.root / "sidecars" / "embeddings"

    @property
    def retrieval_log_dir(self) -> Path:
        return self.root / "sidecars" / "retrieval_logs"

    @property
    def runtime_session_dir(self) -> Path:
        return self.root / "sidecars" / "runtime_sessions"

    @property
    def retrieval_candidate_pool_dir(self) -> Path:
        return self.root / "sidecars" / "retrieval_candidate_pools"

    @property
    def retrieval_candidate_payload_dir(self) -> Path:
        return self.root / "sidecars" / "retrieval_candidate_payloads"

    @property
    def retrieval_rerank_dir(self) -> Path:
        return self.root / "sidecars" / "retrieval_rerank_results"

    @property
    def retrieval_pruning_dir(self) -> Path:
        return self.root / "sidecars" / "retrieval_pruning_profiles"

    @property
    def validator_report_dir(self) -> Path:
        return self.root / "sidecars" / "validator_reports"

    @property
    def replay_ledger_dir(self) -> Path:
        return self.root / "sidecars" / "replay_ledgers"

    @property
    def execution_step_dir(self) -> Path:
        return self.root / "sidecars" / "execution_steps"

    @property
    def codeact_plan_audit_dir(self) -> Path:
        return self.root / "sidecars" / "codeact_plan_audits"

    @property
    def codeact_record_audit_dir(self) -> Path:
        return self.root / "sidecars" / "codeact_record_audits"

    @property
    def fallback_dag_dir(self) -> Path:
        return self.root / "sidecars" / "fallback_dags"

    @property
    def input_validator_report_dir(self) -> Path:
        return self.root / "sidecars" / "input_validator_reports"

    @property
    def artifact_settlement_dir(self) -> Path:
        return self.root / "sidecars" / "artifact_settlements"

    @property
    def artifact_invalidation_dir(self) -> Path:
        return self.root / "sidecars" / "artifact_invalidations"

    def put_ref_registry_entry(self, entry: RefRegistryEntry) -> Path:
        return self.put_ref_registry_entries([entry])

    def put_ref_registry_entries(self, entries: list[RefRegistryEntry]) -> Path:
        payload = self._read_registry_payload()
        modified = False
        for entry in entries:
            small_payload = entry.small_index_payload()
            if payload.get(entry.ref_id) == small_payload:
                continue
            payload[entry.ref_id] = small_payload
            modified = True
        if modified or not self.registry_path.exists():
            self._write_json(self.registry_path, payload)
        return self.registry_path

    def get_ref_registry_entry(self, ref_id: str) -> RefRegistryEntry:
        payload = self._read_registry_payload()
        item = dict(payload[ref_id])
        return self._registry_entry_from_payload(item)

    def query_ref_registry(self, query: RefRegistryQuery | None = None) -> list[RefRegistryEntry]:
        query = query or RefRegistryQuery()
        payload = self._read_registry_payload()
        matches: list[RefRegistryEntry] = []
        for item in payload.values():
            entry = self._registry_entry_from_payload(item)
            if query.ref_kind is not None and entry.ref_kind != query.ref_kind:
                continue
            if query.status is not None and entry.status != query.status:
                continue
            if query.storage_kind is not None and entry.storage_kind != query.storage_kind:
                continue
            if query.manifest_hash and entry.manifest_hash != query.manifest_hash:
                continue
            if query.root_id and entry.root_id != query.root_id:
                continue
            if query.relpath_prefix and not entry.relpath.startswith(query.relpath_prefix):
                continue
            matches.append(entry)
        return sorted(matches, key=lambda entry: entry.ref_id)

    def write_hydrate_manifest(self, manifest: HydrateManifest) -> Path:
        path = self.sidecar_hydrate_dir / f"{manifest.manifest_hash}.json"
        self._write_json(path, manifest_to_dict(manifest))
        return path

    def read_hydrate_manifest(self, manifest_hash: str) -> HydrateManifest:
        path = self.sidecar_hydrate_dir / f"{manifest_hash}.json"
        if not path.exists():
            raise RefManifestMissingError(f"hydrate manifest missing: {manifest_hash}")
        return manifest_from_dict(self._read_json(path))

    def write_evidence_pack(self, pack: CanonicalEvidencePack) -> Path:
        path = self.sidecar_evidence_dir / f"{pack.pack_hash}.json"
        self._write_json(path, evidence_pack_to_dict(pack))
        return path

    def read_evidence_pack(self, pack_hash: str) -> CanonicalEvidencePack:
        path = self.sidecar_evidence_dir / f"{pack_hash}.json"
        if not path.exists():
            raise RefManifestMissingError(f"evidence pack missing: {pack_hash}")
        return evidence_pack_from_dict(self._read_json(path))

    def write_hydration_accounting_audit(self, audit: HydrationAccountingAudit) -> Path:
        path = self.sidecar_hydration_accounting_dir / f"{audit.task_id}.json"
        self._write_json(path, audit.canonical_payload())
        return path

    def read_hydration_accounting_audit(self, task_id: str) -> HydrationAccountingAudit:
        path = self.sidecar_hydration_accounting_dir / f"{task_id}.json"
        if not path.exists():
            raise RefManifestMissingError(f"hydration accounting audit missing: {task_id}")
        payload = self._read_json(path)
        return HydrationAccountingAudit(
            task_id=str(payload.get("task_id", "")),
            evidence_pack_id=str(payload.get("evidence_pack_id", "")),
            evidence_pack_hash=str(payload.get("evidence_pack_hash", "")),
            hydrate_manifest_id=str(payload.get("hydrate_manifest_id", "")),
            hydrate_manifest_hash=str(payload.get("hydrate_manifest_hash", "")),
            evidence_locator_count=int(payload.get("evidence_locator_count", 0)),
            counting_scope=str(payload.get("counting_scope", "")),
            raw_evidence_bytes_seen_by_llm=int(payload.get("raw_evidence_bytes_seen_by_llm", 0)),
            prompt_visible_total_bytes=int(payload.get("prompt_visible_total_bytes", 0)),
            non_external_prompt_visible_bytes=int(payload.get("non_external_prompt_visible_bytes", 0)),
            prompt_scaffolding_bytes_total=int(payload.get("prompt_scaffolding_bytes_total", 0)),
            semantic_pruning_enabled=bool(payload.get("semantic_pruning_enabled", False)),
            roles=tuple(
                HydrationRoleAccounting(
                    role=str(item.get("role", "")),
                    selected_stable_keys=tuple(item.get("selected_stable_keys", [])),
                    external_text_bytes=int(item.get("external_text_bytes", 0)),
                    external_text_item_count=int(item.get("external_text_item_count", 0)),
                    table_bytes=int(item.get("table_bytes", 0)),
                    table_item_count=int(item.get("table_item_count", 0)),
                    artifact_bytes=int(item.get("artifact_bytes", 0)),
                    artifact_item_count=int(item.get("artifact_item_count", 0)),
                    memory_bytes=int(item.get("memory_bytes", 0)),
                    memory_item_count=int(item.get("memory_item_count", 0)),
                    external_evidence_bytes=int(item.get("external_evidence_bytes", 0)),
                    total_prompt_visible_bytes=int(item.get("total_prompt_visible_bytes", 0)),
                    non_external_prompt_visible_bytes=int(item.get("non_external_prompt_visible_bytes", 0)),
                    total_prompt_visible_item_count=int(item.get("total_prompt_visible_item_count", 0)),
                    prompt_scaffolding_bytes=int(item.get("prompt_scaffolding_bytes", 0)),
                    prompt_bytes=int(item.get("prompt_bytes", 0)),
                    prompt_slice_ref_id=str(item.get("prompt_slice_ref_id", "")),
                    prompt_slice_root_id=str(item.get("prompt_slice_root_id", "")),
                    prompt_slice_relpath=str(item.get("prompt_slice_relpath", "")),
                    prompt_slice_blob_hash=str(item.get("prompt_slice_blob_hash", "")),
                    prompt_slice_size_bytes=int(item.get("prompt_slice_size_bytes", 0)),
                    prompt_slice_schema_version=str(item.get("prompt_slice_schema_version", "")),
                )
                for item in payload.get("roles", [])
            ),
            schema_version=str(payload.get("schema_version", "")),
        )

    def write_artifact_output_manifest(self, manifest: ArtifactOutputManifest) -> Path:
        path = self.artifact_manifest_dir / f"{manifest.manifest_hash}.json"
        self._write_json(path, self._artifact_manifest_to_dict(manifest))
        return path

    def write_input_manifest(self, manifest: InputManifest) -> Path:
        path = self.input_manifest_dir / f"{manifest.manifest_hash}.json"
        self._write_json(path, self._input_manifest_to_dict(manifest))
        return path

    def read_artifact_output_manifest(self, manifest_hash: str) -> ArtifactOutputManifest:
        path = self.artifact_manifest_dir / f"{manifest_hash}.json"
        if not path.exists():
            raise RefManifestMissingError(f"artifact manifest missing: {manifest_hash}")
        return self._artifact_manifest_from_dict(self._read_json(path))

    def read_input_manifest(self, manifest_hash: str) -> InputManifest:
        path = self.input_manifest_dir / f"{manifest_hash}.json"
        if not path.exists():
            raise RefManifestMissingError(f"input manifest missing: {manifest_hash}")
        return self._input_manifest_from_dict(self._read_json(path))

    def write_embedding(self, embedding: StructuredEmbedding) -> Path:
        path = self.embedding_dir / f"{embedding.embedding_hash}.json"
        self._write_json(path, embedding.canonical_payload())
        return path

    def read_embedding(self, embedding_hash: str) -> StructuredEmbedding:
        path = self.embedding_dir / f"{embedding_hash}.json"
        if not path.exists():
            raise RefManifestMissingError(f"embedding missing: {embedding_hash}")
        payload = self._read_json(path)
        vector = tuple(float(value) for value in payload.get("vector", []))
        return StructuredEmbedding(
            embedding_id=str(payload["embedding_id"]),
            vector=vector,
            dims=int(payload["dims"]),
            source_text_hash=str(payload["source_text_hash"]),
            encoding=str(payload.get("encoding", "hashed-bow-v1")),
            schema_version=str(payload.get("schema_version", "")),
        )

    def write_memory_commit(self, commit: MemoryCommit) -> Path:
        path = self.memory_commit_dir / f"{commit.memory_ref.memory_id}.json"
        self._write_json(path, self._memory_commit_to_dict(commit))
        return path

    def read_memory_commit(self, memory_id: str) -> MemoryCommit:
        path = self.memory_commit_dir / f"{memory_id}.json"
        if not path.exists():
            raise RefManifestMissingError(f"memory commit missing: {memory_id}")
        return self._memory_commit_from_dict(self._read_json(path))

    def write_memory_match_result(self, result: MemoryMatchResult) -> Path:
        path = self.memory_match_dir / f"{result.result_hash}.json"
        self._write_json(path, self._memory_match_result_to_dict(result))
        return path

    def read_memory_match_result(self, result_hash: str) -> MemoryMatchResult:
        path = self.memory_match_dir / f"{result_hash}.json"
        if not path.exists():
            raise RefManifestMissingError(f"memory match result missing: {result_hash}")
        return self._memory_match_result_from_dict(self._read_json(path))

    def write_retrieval_log(self, bundle: RetrievalBundle) -> Path:
        path = self.retrieval_log_dir / f"{bundle.log_hash}.json"
        self._write_json(path, bundle.log_payload())
        return path

    def write_retrieval_candidate_pool(self, bundle: RetrievalBundle) -> Path:
        path = self.retrieval_candidate_pool_dir / f"{bundle.candidate_pool.pool_hash}.json"
        self._write_json(path, bundle.candidate_pool.audit_payload())
        candidate_payload_path = (
            self.retrieval_candidate_payload_dir / f"{bundle.candidate_pool.candidate_surface_hash}.json"
        )
        self._write_json(candidate_payload_path, bundle.candidate_pool.candidate_surface_payload())
        return path

    def read_retrieval_candidate_pool(self, pool_hash: str) -> dict[str, object]:
        path = self.retrieval_candidate_pool_dir / f"{pool_hash}.json"
        if not path.exists():
            raise RefManifestMissingError(f"retrieval candidate pool missing: {pool_hash}")
        return self._read_json(path)

    def write_retrieval_rerank_result(self, bundle: RetrievalBundle) -> Path:
        path = self.retrieval_rerank_dir / f"{bundle.rerank_result.rerank_hash}.json"
        self._write_json(path, bundle.rerank_result.canonical_payload())
        return path

    def write_retrieval_pruning_profile(self, bundle: RetrievalBundle) -> Path:
        path = self.retrieval_pruning_dir / f"{bundle.pruning_profile.profile_hash}.json"
        self._write_json(path, bundle.pruning_profile.canonical_payload())
        return path

    def read_retrieval_rerank_result(self, rerank_hash: str) -> dict[str, object]:
        path = self.retrieval_rerank_dir / f"{rerank_hash}.json"
        if not path.exists():
            raise RefManifestMissingError(f"retrieval rerank result missing: {rerank_hash}")
        return self._read_json(path)

    def read_retrieval_pruning_profile(self, profile_hash: str) -> RetrievalPruningProfile:
        path = self.retrieval_pruning_dir / f"{profile_hash}.json"
        if not path.exists():
            raise RefManifestMissingError(f"retrieval pruning profile missing: {profile_hash}")
        return self._retrieval_pruning_profile_from_dict(self._read_json(path))

    def read_retrieval_log(self, log_hash: str) -> dict[str, object]:
        path = self.retrieval_log_dir / f"{log_hash}.json"
        if not path.exists():
            raise RefManifestMissingError(f"retrieval log missing: {log_hash}")
        return self._read_json(path)

    def write_validator_report(self, report: ArtifactValidatorReport) -> Path:
        path = self.validator_report_dir / f"{report.report_hash}.json"
        self._write_json(path, report.canonical_payload())
        return path

    def read_validator_report(self, report_hash: str) -> dict[str, object]:
        path = self.validator_report_dir / f"{report_hash}.json"
        if not path.exists():
            raise RefManifestMissingError(f"validator report missing: {report_hash}")
        return self._read_json(path)

    def write_input_validator_report(self, report: InputValidatorReport) -> Path:
        path = self.input_validator_report_dir / f"{report.report_hash}.json"
        self._write_json(path, report.canonical_payload())
        return path

    def read_input_validator_report(self, report_hash: str) -> dict[str, object]:
        path = self.input_validator_report_dir / f"{report_hash}.json"
        if not path.exists():
            raise RefManifestMissingError(f"input validator report missing: {report_hash}")
        return self._read_json(path)

    def write_artifact_settlement_record(self, record: ArtifactSettlementRecord) -> Path:
        path = self.artifact_settlement_dir / f"{record.artifact_id}.json"
        self._write_json(path, record.canonical_payload())
        return path

    def read_artifact_settlement_record(self, artifact_id: str) -> dict[str, object]:
        path = self.artifact_settlement_dir / f"{artifact_id}.json"
        if not path.exists():
            raise RefManifestMissingError(f"artifact settlement missing: {artifact_id}")
        return self._read_json(path)

    def write_artifact_invalidation_record(self, record: ArtifactInvalidationRecord) -> Path:
        path = self.artifact_invalidation_dir / f"{record.artifact_id}.json"
        self._write_json(path, record.canonical_payload())
        return path

    def read_artifact_invalidation_record(self, artifact_id: str) -> dict[str, object]:
        path = self.artifact_invalidation_dir / f"{artifact_id}.json"
        if not path.exists():
            raise RefManifestMissingError(f"artifact invalidation missing: {artifact_id}")
        return self._read_json(path)

    def write_runtime_session(self, session: RuntimeTaskSession) -> Path:
        path = self.runtime_session_dir / f"{session.session_id}.json"
        self._write_json(path, self._runtime_session_to_dict(session))
        return path

    def write_execution_step_record(self, record: ExecutionStepRecord) -> Path:
        self.write_artifact_output_manifest(record.output_manifest)
        path = self.execution_step_dir / f"{record.task_id}.{record.step_id}.{record.attempt_id}.json"
        self._write_json(path, record.canonical_payload())
        return path

    def read_execution_step_record(
        self,
        *,
        task_id: str,
        step_id: str,
        attempt_id: str,
    ) -> ExecutionStepRecord:
        path = self.execution_step_dir / f"{task_id}.{step_id}.{attempt_id}.json"
        if not path.exists():
            raise RefManifestMissingError(
                f"execution step record missing: {task_id}.{step_id}.{attempt_id}"
            )
        return self._execution_step_record_from_dict(self._read_json(path))

    def write_fallback_dag(self, dag: FallbackDag) -> Path:
        path = self.fallback_dag_dir / f"{dag.dag_id}.json"
        self._write_json(path, dag.canonical_payload())
        return path

    def read_fallback_dag(self, dag_id: str) -> FallbackDag:
        path = self.fallback_dag_dir / f"{dag_id}.json"
        if not path.exists():
            raise RefManifestMissingError(f"fallback dag missing: {dag_id}")
        payload = self._read_json(path)
        return FallbackDag(
            dag_id=str(payload["dag_id"]),
            task_id=str(payload["task_id"]),
            source_step_id=str(payload["source_step_id"]),
            actions=tuple(
                FallbackAction(
                    action_name=str(item["action_name"]),
                    target_step_id=str(item["target_step_id"]),
                    reason=str(item["reason"]),
                    next_capability=str(item.get("next_capability", "")),
                    skip_downstream_step_ids=tuple(item.get("skip_downstream_step_ids", [])),
                    downgrade_outputs=tuple(item.get("downgrade_outputs", [])),
                )
                for item in payload.get("actions", [])
            ),
            schema_version=str(payload.get("schema_version", "")),
        )

    def read_runtime_session(self, session_id: str) -> RuntimeTaskSession:
        path = self.runtime_session_dir / f"{session_id}.json"
        if not path.exists():
            raise RefManifestMissingError(f"runtime session missing: {session_id}")
        payload = self._read_json(path)
        workspace_root_relpath = str(payload.get("workspace_root_relpath", "")).strip()
        state_root_relpath = str(payload.get("state_root_relpath", "")).strip()
        workspace_root = (
            str((self.root / workspace_root_relpath).resolve(strict=False))
            if workspace_root_relpath
            else str(payload.get("workspace_root", ""))
        )
        state_root = (
            str((self.root / state_root_relpath).resolve(strict=False))
            if state_root_relpath
            else str(payload.get("state_root", ""))
        )
        return RuntimeTaskSession(
            session_id=str(payload["session_id"]),
            trace_id=str(payload["trace_id"]),
            task_id=str(payload["task_id"]),
            layer_name=str(payload["layer_name"]),
            canonical_task_spec_hash=str(payload["canonical_task_spec_hash"]),
            workspace_root=workspace_root,
            state_root=state_root,
            retrieval_log_hash=str(payload.get("retrieval_log_hash", "")),
            input_manifest_hash=str(payload.get("input_manifest_hash", "")),
            artifact_manifest_hash=str(payload.get("artifact_manifest_hash", "")),
            planner_handoff_hash=str(payload.get("planner_handoff_hash", "")),
            runtime_signature_hash=str(payload.get("runtime_signature_hash", "")),
            runtime_signature_manifest_bundle_hash=str(
                payload.get("runtime_signature_manifest_bundle_hash", "")
            ),
            replay_input_artifact_hashes=tuple(payload.get("replay_input_artifact_hashes", [])),
            state_ref_ids=tuple(payload.get("state_ref_ids", [])),
            artifact_ref_ids=tuple(payload.get("artifact_ref_ids", [])),
            memory_ref_ids=tuple(payload.get("memory_ref_ids", [])),
            workflow_steps=tuple(
                RuntimeWorkflowStep(
                    step_id=str(item["step_id"]),
                    role=str(item["role"]),
                    capability=str(item["capability"]),
                    depends_on=tuple(item.get("depends_on", [])),
                    input_refs=tuple(item.get("input_refs", [])),
                    output_refs=tuple(item.get("output_refs", [])),
                    can_skip_if=str(item.get("can_skip_if", "")),
                    max_retries=int(item.get("max_retries", 0)),
                    state=str(item.get("state", "")),
                    attempt_id=str(item.get("attempt_id", "")),
                    last_error=str(item.get("last_error", "")),
                    started_at_ns=int(item.get("started_at_ns", 0)),
                    completed_at_ns=int(item.get("completed_at_ns", 0)),
                    updated_at_ns=int(item.get("updated_at_ns", 0)),
                    metrics={str(key): float(value) for key, value in dict(item.get("metrics", {})).items()},
                )
                for item in payload.get("workflow_steps", [])
            ),
            attempt_records=tuple(
                StepAttemptRecord(
                    task_id=str(item.get("task_id", payload.get("task_id", ""))),
                    step_id=str(item["step_id"]),
                    attempt_id=str(item["attempt_id"]),
                    owner_role=str(item["owner_role"]),
                    state=str(item["state"]),
                    attempt_index=int(item.get("attempt_index", 0)),
                    worker_id=str(item.get("worker_id", "")),
                    dispatched_at_ns=int(item.get("dispatched_at_ns", 0)),
                    acked_at_ns=int(item.get("acked_at_ns", 0)),
                    running_at_ns=int(item.get("running_at_ns", 0)),
                    heartbeat_at_ns=int(item.get("heartbeat_at_ns", 0)),
                    completed_at_ns=int(item.get("completed_at_ns", 0)),
                    cancel_reason=str(item.get("cancel_reason", "")),
                    trap_reason=str(item.get("trap_reason", "")),
                    fallback_action=str(item.get("fallback_action", "")),
                    resource_handles=tuple(item.get("resource_handles", [])),
                    workspace_dirs=tuple(item.get("workspace_dirs", [])),
                    validator_report_hashes=tuple(item.get("validator_report_hashes", [])),
                )
                for item in payload.get("attempt_records", [])
            ),
            replan_history=tuple(
                RuntimeReplanRecord(
                    replan_id=str(item["replan_id"]),
                    task_id=str(item["task_id"]),
                    source_step_id=str(item["source_step_id"]),
                    attempt_id=str(item["attempt_id"]),
                    trigger_state=str(item["trigger_state"]),
                    trigger_reason=str(item["trigger_reason"]),
                    fallback_action=str(item["fallback_action"]),
                    selected_capability=str(item.get("selected_capability", "")),
                    downgraded_execution_goal=bool(item.get("downgraded_execution_goal", False)),
                    fallback_dag_hash=str(item.get("fallback_dag_hash", "")),
                    created_at_ns=int(item.get("created_at_ns", 0)),
                    schema_version=str(item.get("schema_version", "")),
                )
                for item in payload.get("replan_history", [])
            ),
            replay_ledger_ids=tuple(payload.get("replay_ledger_ids", [])),
            current_step_id=str(payload.get("current_step_id", "")),
            runtime_fallback_count=int(
                payload.get("runtime_fallback_count", payload.get("planner_fallback_count", 0))
            ),
            runtime_replan_count=int(
                payload.get("runtime_replan_count", payload.get("planner_replan_count", 0))
            ),
            summary_artifact_ref_id=str(payload.get("summary_artifact_ref_id", "")),
            memory_match_result_hash=str(payload.get("memory_match_result_hash", "")),
            current_attempt_id=str(payload.get("current_attempt_id", "")),
            last_fallback_action=str(payload.get("last_fallback_action", "")),
            session_state=str(payload.get("session_state", "")),
            created_at_ns=int(payload.get("created_at_ns", 0)),
            updated_at_ns=int(payload.get("updated_at_ns", 0)),
            lease_config=RuntimeLeaseConfig(**dict(payload.get("lease_config", {}))),
            schema_version=str(payload.get("schema_version", "")),
        )

    def write_replay_ledger_entry(self, entry: ReplayLedgerEntry) -> Path:
        path = self.replay_ledger_dir / f"{entry.ledger_id}.json"
        self._write_json(path, entry.canonical_payload())
        return path

    def read_replay_ledger_entry(self, ledger_id: str) -> ReplayLedgerEntry:
        path = self.replay_ledger_dir / f"{ledger_id}.json"
        if not path.exists():
            raise RefManifestMissingError(f"replay ledger missing: {ledger_id}")
        payload = self._read_json(path)
        from v2.contracts import CompatibilityVerdict

        return ReplayLedgerEntry(
            ledger_id=str(payload["ledger_id"]),
            session_id=str(payload["session_id"]),
            task_id=str(payload["task_id"]),
            candidate_id=str(payload["candidate_id"]),
            memory_id=str(payload["memory_id"]),
            artifact_ref_id=str(payload["artifact_ref_id"]),
            replay_class=ReplayClass(str(payload["replay_class"])),
            decision_reason=str(payload["decision_reason"]),
            compatibility_verdict=CompatibilityVerdict(str(payload["compatibility_verdict"])),
            runtime_signature_hash=str(payload["runtime_signature_hash"]),
            runtime_signature_manifest_bundle_hash=str(payload.get("runtime_signature_manifest_bundle_hash", "")),
            canonical_task_spec_hash=str(payload["canonical_task_spec_hash"]),
            planner_handoff_hash=str(payload.get("planner_handoff_hash", "")),
            input_artifact_hashes=tuple(payload.get("input_artifact_hashes", [])),
            output_contract_version=str(payload["output_contract_version"]),
            code_template_version=str(payload.get("code_template_version", "")),
            extractor_version=str(payload.get("extractor_version", "")),
            runtime_signature=dict(payload.get("runtime_signature", {})),
            exact_key=str(payload.get("exact_key", "")),
            degraded=bool(payload.get("degraded", False)),
            skipped_step_count=int(payload.get("skipped_step_count", 0)),
            created_at_ns=int(payload.get("created_at_ns", 0)),
            schema_version=str(payload.get("schema_version", "")),
        )

    def persist_contract_bundle(
        self,
        *,
        registry_entries: list[RefRegistryEntry],
        hydrate_manifest: HydrateManifest,
        evidence_pack: CanonicalEvidencePack,
        hydration_accounting_audit: HydrationAccountingAudit | None = None,
        input_manifest: InputManifest,
        artifact_manifest: ArtifactOutputManifest,
        embedding: StructuredEmbedding | None = None,
        memory_commit: MemoryCommit | None = None,
        memory_match_result: MemoryMatchResult | None = None,
        retrieval_bundle: RetrievalBundle | None = None,
        runtime_session: RuntimeTaskSession | None = None,
        validator_reports: tuple[ArtifactValidatorReport, ...] = (),
        input_validator_reports: tuple[InputValidatorReport, ...] = (),
        replay_ledger_entry: ReplayLedgerEntry | None = None,
        execution_step_record: ExecutionStepRecord | None = None,
        fallback_dag: FallbackDag | None = None,
        artifact_settlement_record: ArtifactSettlementRecord | None = None,
        artifact_invalidation_record: ArtifactInvalidationRecord | None = None,
        materialized_json_by_hash: dict[str, Path] | None = None,
    ) -> PersistedContractPaths:
        self.put_ref_registry_entries(registry_entries)
        writes: list[_JsonWriteSpec] = []
        reused_json = materialized_json_by_hash or {}

        def _build_write(path: Path, payload: object, *, content_hash: str = "") -> _JsonWriteSpec:
            source_path = None if not content_hash else reused_json.get(content_hash)
            return _JsonWriteSpec(
                path=path,
                payload=payload,
                source_path=source_path,
                trusted_source=source_path is not None,
            )

        hydrate_manifest_path = self.sidecar_hydrate_dir / f"{hydrate_manifest.manifest_hash}.json"
        evidence_pack_path = self.sidecar_evidence_dir / f"{evidence_pack.pack_hash}.json"
        input_manifest_path = self.input_manifest_dir / f"{input_manifest.manifest_hash}.json"
        artifact_manifest_path = self.artifact_manifest_dir / f"{artifact_manifest.manifest_hash}.json"
        writes.extend(
            (
                _build_write(
                    hydrate_manifest_path,
                    manifest_to_dict(hydrate_manifest),
                    content_hash=hydrate_manifest.manifest_hash,
                ),
                _build_write(
                    evidence_pack_path,
                    evidence_pack_to_dict(evidence_pack),
                    content_hash=evidence_pack.pack_hash,
                ),
                _build_write(
                    input_manifest_path,
                    self._input_manifest_to_dict(input_manifest),
                    content_hash=input_manifest.manifest_hash,
                ),
                _build_write(
                    artifact_manifest_path,
                    self._artifact_manifest_to_dict(artifact_manifest),
                    content_hash=artifact_manifest.manifest_hash,
                ),
            )
        )
        hydration_accounting_audit_path = None
        if hydration_accounting_audit is not None:
            hydration_accounting_audit_path = self.sidecar_hydration_accounting_dir / f"{hydration_accounting_audit.task_id}.json"
            writes.append(_JsonWriteSpec(hydration_accounting_audit_path, hydration_accounting_audit.canonical_payload()))

        embedding_path = None
        if embedding is not None:
            embedding_path = self.embedding_dir / f"{embedding.embedding_hash}.json"
            writes.append(_JsonWriteSpec(embedding_path, embedding.canonical_payload()))

        memory_commit_path = None
        if memory_commit is not None:
            memory_commit_path = self.memory_commit_dir / f"{memory_commit.memory_ref.memory_id}.json"
            writes.append(_JsonWriteSpec(memory_commit_path, self._memory_commit_to_dict(memory_commit)))

        memory_match_result_path = None
        if memory_match_result is not None:
            memory_match_result_path = self.memory_match_dir / f"{memory_match_result.result_hash}.json"
            writes.append(_JsonWriteSpec(memory_match_result_path, self._memory_match_result_to_dict(memory_match_result)))

        retrieval_log_path = None
        retrieval_candidate_pool_path = None
        retrieval_candidate_payload_path = None
        retrieval_rerank_result_path = None
        retrieval_pruning_profile_path = None
        if retrieval_bundle is not None:
            retrieval_log_path = self.retrieval_log_dir / f"{retrieval_bundle.log_hash}.json"
            retrieval_candidate_pool_path = self.retrieval_candidate_pool_dir / f"{retrieval_bundle.candidate_pool.pool_hash}.json"
            retrieval_candidate_payload_path = (
                self.retrieval_candidate_payload_dir / f"{retrieval_bundle.candidate_pool.candidate_surface_hash}.json"
            )
            retrieval_rerank_result_path = self.retrieval_rerank_dir / f"{retrieval_bundle.rerank_result.rerank_hash}.json"
            retrieval_pruning_profile_path = self.retrieval_pruning_dir / f"{retrieval_bundle.pruning_profile.profile_hash}.json"
            writes.extend(
                (
                    _build_write(
                        retrieval_log_path,
                        retrieval_bundle.log_payload(),
                        content_hash=retrieval_bundle.log_hash,
                    ),
                    _JsonWriteSpec(retrieval_candidate_pool_path, retrieval_bundle.candidate_pool.audit_payload()),
                    _JsonWriteSpec(
                        retrieval_candidate_payload_path,
                        retrieval_bundle.candidate_pool.candidate_surface_payload(),
                    ),
                    _JsonWriteSpec(retrieval_rerank_result_path, retrieval_bundle.rerank_result.canonical_payload()),
                    _JsonWriteSpec(retrieval_pruning_profile_path, retrieval_bundle.pruning_profile.canonical_payload()),
                )
            )

        session_path = None
        if runtime_session is not None:
            session_path = self.runtime_session_dir / f"{runtime_session.session_id}.json"
            writes.append(_JsonWriteSpec(session_path, self._runtime_session_to_dict(runtime_session)))

        validator_report_paths = tuple(self.validator_report_dir / f"{report.report_hash}.json" for report in validator_reports)
        writes.extend(
            _JsonWriteSpec(path, report.canonical_payload()) for path, report in zip(validator_report_paths, validator_reports)
        )

        input_validator_report_paths = tuple(
            self.input_validator_report_dir / f"{report.report_hash}.json" for report in input_validator_reports
        )
        writes.extend(
            _JsonWriteSpec(path, report.canonical_payload())
            for path, report in zip(input_validator_report_paths, input_validator_reports)
        )

        replay_ledger_path = None
        if replay_ledger_entry is not None:
            replay_ledger_path = self.replay_ledger_dir / f"{replay_ledger_entry.ledger_id}.json"
            writes.append(_JsonWriteSpec(replay_ledger_path, replay_ledger_entry.canonical_payload()))

        execution_step_path = None
        codeact_plan_audit_path = None
        codeact_record_audit_path = None
        if execution_step_record is not None:
            execution_step_path = self.execution_step_dir / (
                f"{execution_step_record.task_id}.{execution_step_record.step_id}.{execution_step_record.attempt_id}.json"
            )
            writes.append(_JsonWriteSpec(execution_step_path, execution_step_record.canonical_payload()))
            codeact_plan_detail = execution_step_record.codeact_plan_audit_detail_payload()
            if codeact_plan_detail is not None:
                codeact_plan_audit_path = self.root / execution_step_record.codeact_plan_audit_relpath
                writes.append(_JsonWriteSpec(codeact_plan_audit_path, codeact_plan_detail))
            codeact_record_detail = execution_step_record.codeact_record_audit_detail_payload()
            if codeact_record_detail is not None:
                codeact_record_audit_path = self.root / execution_step_record.codeact_record_audit_relpath
                writes.append(_JsonWriteSpec(codeact_record_audit_path, codeact_record_detail))

        fallback_dag_path = None
        if fallback_dag is not None:
            fallback_dag_path = self.fallback_dag_dir / f"{fallback_dag.dag_id}.json"
            writes.append(_JsonWriteSpec(fallback_dag_path, fallback_dag.canonical_payload()))

        artifact_settlement_path = None
        if artifact_settlement_record is not None:
            artifact_settlement_path = self.artifact_settlement_dir / f"{artifact_settlement_record.artifact_id}.json"
            writes.append(_JsonWriteSpec(artifact_settlement_path, artifact_settlement_record.canonical_payload()))

        artifact_invalidation_path = None
        if artifact_invalidation_record is not None:
            artifact_invalidation_path = self.artifact_invalidation_dir / f"{artifact_invalidation_record.artifact_id}.json"
            writes.append(_JsonWriteSpec(artifact_invalidation_path, artifact_invalidation_record.canonical_payload()))

        self._write_json_batch(writes)
        return PersistedContractPaths(
            registry_path=self.registry_path,
            hydrate_manifest_path=hydrate_manifest_path,
            evidence_pack_path=evidence_pack_path,
            hydration_accounting_audit_path=hydration_accounting_audit_path,
            input_manifest_path=input_manifest_path,
            artifact_manifest_path=artifact_manifest_path,
            embedding_path=embedding_path,
            memory_commit_path=memory_commit_path,
            memory_match_result_path=memory_match_result_path,
            retrieval_log_path=retrieval_log_path,
            retrieval_candidate_pool_path=retrieval_candidate_pool_path,
            retrieval_candidate_payload_path=retrieval_candidate_payload_path,
            retrieval_rerank_result_path=retrieval_rerank_result_path,
            retrieval_pruning_profile_path=retrieval_pruning_profile_path,
            session_path=session_path,
            validator_report_paths=validator_report_paths,
            replay_ledger_path=replay_ledger_path,
            execution_step_path=execution_step_path,
            codeact_plan_audit_path=codeact_plan_audit_path,
            codeact_record_audit_path=codeact_record_audit_path,
            fallback_dag_path=fallback_dag_path,
            input_validator_report_paths=input_validator_report_paths,
            artifact_settlement_path=artifact_settlement_path,
            artifact_invalidation_path=artifact_invalidation_path,
        )

    def load_contract_bundle(
        self,
        *,
        state_ref_id: str,
        artifact_ref_id: str,
        evidence_pack_hash: str,
        input_manifest_hash: str,
    ) -> tuple[
        RefRegistryEntry,
        RefRegistryEntry,
        HydrateManifest,
        CanonicalEvidencePack,
        InputManifest,
        ArtifactOutputManifest,
    ]:
        state_entry = self.get_ref_registry_entry(state_ref_id)
        artifact_entry = self.get_ref_registry_entry(artifact_ref_id)
        if not artifact_entry.manifest_hash:
            raise RefManifestMissingError(f"artifact manifest hash missing for ref: {artifact_ref_id}")
        hydrate_manifest = self.read_hydrate_manifest(state_entry.manifest_hash)
        evidence_pack = self.read_evidence_pack(evidence_pack_hash)
        input_manifest = self.read_input_manifest(input_manifest_hash)
        artifact_manifest = self.read_artifact_output_manifest(artifact_entry.manifest_hash)
        return state_entry, artifact_entry, hydrate_manifest, evidence_pack, input_manifest, artifact_manifest

    def _read_registry_payload(self) -> dict[str, dict[str, str]]:
        if not self.registry_path.exists():
            return {}
        return dict(self._read_json(self.registry_path))

    def _registry_entry_from_payload(self, item: dict[str, object]) -> RefRegistryEntry:
        return RefRegistryEntry(
            ref_id=str(item["ref_id"]),
            ref_kind=RefKind(item["ref_kind"]),
            storage_kind=StorageKind(item["storage_kind"]),
            status=RefStatus(item["status"]),
            blob_hash=str(item.get("blob_hash", "")),
            manifest_hash=str(item.get("manifest_hash", "")),
            root_id=str(item.get("root_id", "")),
            relpath=str(item.get("relpath", "")),
            workspace_relpath=str(item.get("workspace_relpath", "")),
            schema_version=str(item.get("schema_version", "")),
        )

    def _artifact_manifest_to_dict(self, manifest: ArtifactOutputManifest) -> dict[str, object]:
        return {
            "task_id": manifest.task_id,
            "step_id": manifest.step_id,
            "manifest_hash": manifest.manifest_hash,
            "outputs": [item.canonical_payload() for item in manifest.outputs],
        }

    def _root_relpath_from_store(self, path_text: str) -> str:
        normalized_path = str(path_text).strip()
        if not normalized_path:
            return normalized_path
        try:
            return os.path.relpath(normalized_path, self.root)
        except ValueError:
            return normalized_path

    def _runtime_session_to_dict(self, session: RuntimeTaskSession) -> dict[str, object]:
        payload = dict(session.canonical_payload())
        payload.pop("workspace_root", None)
        payload.pop("state_root", None)
        payload["workspace_root_relpath"] = self._root_relpath_from_store(session.workspace_root)
        payload["state_root_relpath"] = self._root_relpath_from_store(session.state_root)
        return payload

    def _input_manifest_to_dict(self, manifest: InputManifest) -> dict[str, object]:
        return {
            "task_id": manifest.task_id,
            "step_id": manifest.step_id,
            "workspace_root": manifest.workspace_root,
            "manifest_hash": manifest.manifest_hash,
            "inputs": [item.canonical_payload() for item in manifest.inputs],
        }

    def _artifact_manifest_from_dict(self, payload: dict[str, object]) -> ArtifactOutputManifest:
        outputs = tuple(
            ArtifactManifestItem(
                artifact_name=str(item["artifact_name"]),
                artifact_type=str(item["artifact_type"]),
                relpath=str(item["relpath"]),
                size_bytes=int(item["size_bytes"]),
                sha256=str(item["sha256"]),
            )
            for item in payload.get("outputs", [])
        )
        return ArtifactOutputManifest(
            task_id=str(payload.get("task_id", "")),
            step_id=str(payload.get("step_id", "")),
            outputs=outputs,
        )

    def _input_manifest_from_dict(self, payload: dict[str, object]) -> InputManifest:
        inputs = tuple(
            InputManifestItem(
                name=str(item["name"]),
                artifact_type=str(item["artifact_type"]),
                relpath=str(item["relpath"]),
                blob_hash=str(item["blob_hash"]),
                source_ref_id=str(item["source_ref_id"]),
            )
            for item in payload.get("inputs", [])
        )
        return InputManifest(
            task_id=str(payload.get("task_id", "")),
            step_id=str(payload.get("step_id", "")),
            workspace_root=str(payload.get("workspace_root", "")),
            inputs=inputs,
        )

    def _memory_ref_from_dict(self, payload: dict[str, object]) -> MemoryRef:
        metadata = dict(payload.get("metadata", {}))
        return MemoryRef(
            memory_id=str(payload["memory_id"]),
            memory_type=MemoryType(str(payload["memory_type"])),
            replay_class=ReplayClass(str(payload["replay_class"])),
            score=float(payload["score"]),
            source_task_id=str(payload["source_task_id"]),
            summary=str(payload["summary"]),
            canonical_task_spec_hash=str(payload["canonical_task_spec_hash"]),
            source_agent=str(payload.get("source_agent", metadata.get("source_agent", ""))),
            created_at_ns=int(payload.get("created_at_ns", metadata.get("created_at_ns", 0))),
            task_theme=str(payload.get("task_theme", metadata.get("task_theme", ""))),
            tags=tuple(str(item) for item in payload.get("tags", metadata.get("tags", []))),
            source_role_path=tuple(
                str(item) for item in payload.get("source_role_path", metadata.get("source_role_path", []))
            ),
            producer_run_id=str(payload.get("producer_run_id", metadata.get("producer_run_id", ""))),
            artifact_ref_id=str(payload.get("artifact_ref_id", "")),
            semantic_state_ref_id=str(payload.get("semantic_state_ref_id", "")),
            embedding_ref_id=str(payload.get("embedding_ref_id", "")),
            manifest_hash=str(payload.get("manifest_hash", "")),
            commit_status=MemoryCommitStatus(str(payload.get("commit_status", MemoryCommitStatus.CANDIDATE.value))),
            validation_status=MemoryValidationStatus(
                str(payload.get("validation_status", MemoryValidationStatus.UNCHECKED.value))
            ),
            answer_adopted=bool(payload.get("answer_adopted", False)),
            schema_version=str(payload.get("schema_version", "")),
            metadata=metadata,
        )

    def _memory_commit_to_dict(self, commit: MemoryCommit) -> dict[str, object]:
        return commit.canonical_payload()

    def _memory_commit_from_dict(self, payload: dict[str, object]) -> MemoryCommit:
        memory_ref = self._memory_ref_from_dict(dict(payload["memory_ref"]))
        spec_payload = dict(payload["canonical_task_spec"])
        return MemoryCommit(
            memory_ref=memory_ref,
            canonical_task_spec=CanonicalTaskSpec(
                task_family=str(spec_payload["task_family"]),
                intent_op=str(spec_payload["intent_op"]),
                target_entities=tuple(spec_payload.get("target_entities", [])),
                time_scope=str(spec_payload.get("time_scope", "")),
                required_outputs=tuple(spec_payload.get("required_outputs", [])),
                required_tools=tuple(spec_payload.get("required_tools", [])),
                arguments=dict(spec_payload.get("arguments", {})),
                schema_version=str(spec_payload.get("schema_version", "")),
            ),
            required_outputs=tuple(payload.get("required_outputs", [])),
            quality_floor_pass=bool(payload.get("quality_floor_pass", False)),
            created_from_artifact_hash=str(payload.get("created_from_artifact_hash", "")),
            schema_version=str(payload.get("schema_version", "")),
        )

    def _memory_match_result_to_dict(self, result: MemoryMatchResult) -> dict[str, object]:
        return result.canonical_payload()

    def _memory_match_result_from_dict(self, payload: dict[str, object]) -> MemoryMatchResult:
        from v2.contracts import ReplayClass

        matches = tuple(
            MemoryMatch(
                memory_ref=self._memory_ref_from_dict(
                    {
                        "replay_class": str(item.get("replay_class", ReplayClass.ASSIST.value)),
                        "score": float(item.get("score", 0.0)),
                        **dict(item["memory_ref"]),
                    }
                ),
                matched_on=str(item["matched_on"]),
                score=float(item["score"]),
                replay_class=ReplayClass(str(item["replay_class"])),
            )
            for item in payload.get("matches", [])
        )
        candidate_pool_payload = payload.get("candidate_pool")
        candidate_pool = None
        if isinstance(candidate_pool_payload, dict):
            candidate_pool = MemoryCandidatePool(
                query_task_id=str(candidate_pool_payload["query_task_id"]),
                query_spec_hash=str(candidate_pool_payload["query_spec_hash"]),
                candidate_memory_ids=tuple(candidate_pool_payload.get("candidate_memory_ids", [])),
                candidate_types=tuple(candidate_pool_payload.get("candidate_types", [])),
                candidate_taxonomy={
                    str(key): int(value)
                    for key, value in dict(candidate_pool_payload.get("candidate_taxonomy", {})).items()
                },
                schema_version=str(candidate_pool_payload.get("schema_version", "")),
            )
        rerank_payload = payload.get("rerank_result")
        rerank_result = None
        if isinstance(rerank_payload, dict):
            rerank_result = MemoryRerankResult(
                query_task_id=str(rerank_payload["query_task_id"]),
                selected_memory_ids=tuple(rerank_payload.get("selected_memory_ids", [])),
                items=tuple(
                    MemoryRerankItem(
                        memory_id=str(item["memory_id"]),
                        rank=int(item["rank"]),
                        score=float(item["score"]),
                        replay_class=ReplayClass(str(item["replay_class"])),
                        selected=bool(item["selected"]),
                    )
                    for item in rerank_payload.get("items", [])
                ),
                selected_taxonomy={
                    str(key): int(value)
                    for key, value in dict(rerank_payload.get("selected_taxonomy", {})).items()
                },
                schema_version=str(rerank_payload.get("schema_version", "")),
            )
        return MemoryMatchResult(
            query_task_id=str(payload["query_task_id"]),
            query_spec_hash=str(payload["query_spec_hash"]),
            matches=matches,
            retrieval_decision=str(payload["retrieval_decision"]),
            candidate_pool=candidate_pool,
            rerank_result=rerank_result,
            candidate_pool_hash=str(payload.get("candidate_pool_hash", "")),
            rerank_result_hash=str(payload.get("rerank_result_hash", "")),
            schema_version=str(payload.get("schema_version", "")),
        )

    def _validator_report_from_dict(self, payload: dict[str, object]) -> ArtifactValidatorReport:
        return ArtifactValidatorReport(
            task_id=str(payload.get("task_id", "")),
            step_id=str(payload.get("step_id", "")),
            artifact_id=str(payload.get("artifact_id", "")),
            validation_scope=str(payload.get("validation_scope", "")),
            passed=bool(payload.get("passed", False)),
            fail_reason=str(payload.get("fail_reason", "")),
            consumed_by=tuple(payload.get("consumed_by", [])),
            metrics={str(key): float(value) for key, value in dict(payload.get("metrics", {})).items()},
            details=dict(payload.get("details", {})),
            schema_version=str(payload.get("schema_version", "")),
            audit_details_hash=str(payload.get("details_hash", "")),
        )

    def _input_validator_report_from_dict(self, payload: dict[str, object]) -> InputValidatorReport:
        return InputValidatorReport(
            task_id=str(payload.get("task_id", "")),
            step_id=str(payload.get("step_id", "")),
            validation_scope=str(payload.get("validation_scope", "")),
            passed=bool(payload.get("passed", False)),
            fail_reason=str(payload.get("fail_reason", "")),
            required_inputs=tuple(payload.get("required_inputs", [])),
            observed_inputs=tuple(payload.get("observed_inputs", [])),
            metrics={str(key): float(value) for key, value in dict(payload.get("metrics", {})).items()},
            details=dict(payload.get("details", {})),
            schema_version=str(payload.get("schema_version", "")),
            audit_details_hash=str(payload.get("details_hash", "")),
        )

    def _artifact_settlement_from_dict(self, payload: dict[str, object]) -> ArtifactSettlementRecord:
        return ArtifactSettlementRecord(
            artifact_id=str(payload.get("artifact_id", "")),
            task_id=str(payload.get("task_id", "")),
            step_id=str(payload.get("step_id", "")),
            from_state=str(payload.get("from_state", "")),
            to_state=str(payload.get("to_state", "")),
            commit_gate_reason=str(payload.get("commit_gate_reason", "")),
            quality_floor_pass=bool(payload.get("quality_floor_pass", False)),
            validator_report_hashes=tuple(payload.get("validator_report_hashes", [])),
            input_validator_hashes=tuple(payload.get("input_validator_hashes", [])),
            replay_ready=bool(payload.get("replay_ready", False)),
            schema_version=str(payload.get("schema_version", "")),
            audit_settlement_hash=str(payload.get("settlement_hash", "")),
        )

    def _artifact_invalidation_from_dict(self, payload: dict[str, object]) -> ArtifactInvalidationRecord:
        return ArtifactInvalidationRecord(
            artifact_id=str(payload.get("artifact_id", "")),
            task_id=str(payload.get("task_id", "")),
            step_id=str(payload.get("step_id", "")),
            invalidation_reason=str(payload.get("invalidation_reason", "")),
            invalidated_from_state=str(payload.get("invalidated_from_state", "")),
            validator_report_hashes=tuple(payload.get("validator_report_hashes", [])),
            input_validator_hashes=tuple(payload.get("input_validator_hashes", [])),
            schema_version=str(payload.get("schema_version", "")),
            audit_invalidation_hash=str(payload.get("invalidation_hash", "")),
        )

    def _materialized_file_from_payload(
        self,
        *,
        logical_name: str,
        relpath: str,
        sha256: str,
        size_bytes: int,
    ) -> MaterializedFile:
        return MaterializedFile(
            logical_name=logical_name,
            relpath=relpath,
            path=Path(relpath),
            sha256=sha256,
            size_bytes=size_bytes,
        )

    def _execution_step_record_from_dict(self, payload: dict[str, object]) -> ExecutionStepRecord:
        manifest_payload = payload.get("output_manifest")
        if isinstance(manifest_payload, dict) and manifest_payload:
            manifest = self._artifact_manifest_from_dict(dict(manifest_payload))
        else:
            manifest_hash = str(payload.get("output_manifest_hash", "")).strip()
            manifest_relpath = str(payload.get("output_manifest_relpath", "")).strip()
            if not manifest_hash:
                raise RefManifestMissingError("execution step record missing output manifest reference")
            if manifest_relpath:
                detail_path = self.root / manifest_relpath
                if not detail_path.exists():
                    raise RefManifestMissingError(
                        f"execution step record missing output manifest sidecar: {manifest_relpath}"
                    )
                manifest = self._artifact_manifest_from_dict(self._read_json(detail_path))
            else:
                manifest = self.read_artifact_output_manifest(manifest_hash)
        outputs_by_name = {item.artifact_name: item for item in manifest.outputs}
        stdout_item = outputs_by_name.get("stdout_log")
        stderr_item = outputs_by_name.get("stderr_log")
        if stdout_item is None or stderr_item is None:
            raise RefManifestMissingError(
                "execution step record missing stdout/stderr log artifacts in output manifest"
            )
        log_capture = ExecutionLogCapture(
            stdout_preview=str(payload.get("stdout_preview", "")),
            stderr_preview=str(payload.get("stderr_preview", "")),
            stdout_artifact=self._materialized_file_from_payload(
                logical_name="stdout_log",
                relpath=stdout_item.relpath,
                sha256=stdout_item.sha256,
                size_bytes=stdout_item.size_bytes,
            ),
            stderr_artifact=self._materialized_file_from_payload(
                logical_name="stderr_log",
                relpath=stderr_item.relpath,
                sha256=stderr_item.sha256,
                size_bytes=stderr_item.size_bytes,
            ),
            stdout_truncated=bool(payload.get("stdout_truncated", False)),
            stderr_truncated=bool(payload.get("stderr_truncated", False)),
        )
        return ExecutionStepRecord(
            task_id=str(payload.get("task_id", "")),
            step_id=str(payload.get("step_id", "")),
            attempt_id=str(payload.get("attempt_id", "")),
            workspace_root=str(payload.get("workspace_root", "")),
            execution_goal=str(payload.get("execution_goal", "")),
            exit_code=int(payload.get("exit_code", 0)),
            output_manifest=manifest,
            log_capture=log_capture,
            input_validator_reports=tuple(
                self._input_validator_report_from_dict(dict(item))
                for item in payload.get("input_validator_reports", [])
            ),
            validator_reports=tuple(
                self._validator_report_from_dict(dict(item))
                for item in payload.get("validator_reports", [])
            ),
            settlement_record=(
                None
                if payload.get("settlement_record") is None
                else self._artifact_settlement_from_dict(dict(payload["settlement_record"]))
            ),
            invalidation_record=(
                None
                if payload.get("invalidation_record") is None
                else self._artifact_invalidation_from_dict(dict(payload["invalidation_record"]))
            ),
            invalidation_reasons=tuple(payload.get("invalidation_reasons", [])),
            codeact_plan=(
                None
                if payload.get("codeact_plan") is None
                else self._load_codeact_plan_from_summary(
                    {
                        "task_id": str(payload.get("task_id", "")),
                        "step_id": str(payload.get("step_id", "")),
                        "execution_goal": str(payload.get("execution_goal", "")),
                        **dict(payload["codeact_plan"]),
                    }
                )
            ),
            codeact_record=(
                None
                if payload.get("codeact_record") is None
                else self._load_codeact_record_from_summary(
                    {
                        "task_id": str(payload.get("task_id", "")),
                        "step_id": str(payload.get("step_id", "")),
                        "attempt_id": str(payload.get("attempt_id", "")),
                        "execution_goal": str(payload.get("execution_goal", "")),
                        **dict(payload["codeact_record"]),
                    }
                )
            ),
            schema_version=str(payload.get("schema_version", "")),
        )

    def _load_codeact_plan_from_summary(self, payload: dict[str, object]) -> CodeActPlan:
        audit_relpath = str(payload.get("audit_relpath", "")).strip()
        merged = dict(payload)
        if audit_relpath:
            detail_path = self.root / audit_relpath
            if not detail_path.exists():
                raise RefManifestMissingError(f"codeact plan audit missing: {audit_relpath}")
            detail_payload = self._read_json(detail_path)
            if "stages" in detail_payload:
                merged["stages"] = detail_payload["stages"]
        return self._codeact_plan_from_dict(merged)

    def _load_codeact_record_from_summary(self, payload: dict[str, object]) -> CodeActExecutionRecord:
        audit_relpath = str(payload.get("audit_relpath", "")).strip()
        merged = dict(payload)
        if audit_relpath:
            detail_path = self.root / audit_relpath
            if not detail_path.exists():
                raise RefManifestMissingError(f"codeact record audit missing: {audit_relpath}")
            detail_payload = self._read_json(detail_path)
            if "stage_results" in detail_payload:
                merged["stage_results"] = detail_payload["stage_results"]
        return self._codeact_record_from_dict(merged)

    def _codeact_plan_from_dict(self, payload: dict[str, object]) -> CodeActPlan:
        def _parameters_from_action(action: dict[str, object]) -> dict[str, object]:
            parameters = action.get("parameters", {})
            if isinstance(parameters, dict) and parameters:
                return dict(parameters)
            parameter_keys = action.get("parameter_keys")
            if isinstance(parameter_keys, list):
                return {str(key): "<audit-elided>" for key in parameter_keys}
            return {}

        return CodeActPlan(
            plan_id=str(payload.get("plan_id", "")),
            task_id=str(payload.get("task_id", "")),
            step_id=str(payload.get("step_id", "")),
            execution_goal=str(payload.get("execution_goal", "")),
            stages=tuple(
                CodeActStage(
                    stage_id=str(stage.get("stage_id", "")),
                    title=str(stage.get("title", "")),
                    actions=tuple(
                        CodeActAction(
                            action_id=str(action.get("action_id", "")),
                            kind=str(action.get("kind", "")),
                            title=str(action.get("title", "")),
                            input_relpath=str(action.get("input_relpath", "")),
                            output_relpath=str(action.get("output_relpath", "")),
                            parameters=_parameters_from_action(dict(action)),
                        )
                        for action in stage.get("actions", [])
                    ),
                )
                for stage in payload.get("stages", [])
            ),
            schema_version=str(payload.get("schema_version", "")),
        )

    def _retrieval_pruning_profile_from_dict(self, payload: dict[str, object]) -> RetrievalPruningProfile:
        return RetrievalPruningProfile(
            task_id=str(payload.get("task_id", "")),
            full_corpus_bytes=int(payload.get("full_corpus_bytes", 0)),
            selected_evidence_bytes=int(payload.get("selected_evidence_bytes", 0)),
            raw_evidence_bytes_seen_by_llm=int(payload.get("raw_evidence_bytes_seen_by_llm", 0)),
            pruning_gain_bytes=int(payload.get("pruning_gain_bytes", 0)),
            selected_candidate_ids=tuple(payload.get("selected_candidate_ids", [])),
            bucket_stats=tuple(
                RetrievalPruningBucketStat(
                    bucket=str(item.get("bucket", "")),
                    candidate_count=int(item.get("candidate_count", 0)),
                    selected_count=int(item.get("selected_count", 0)),
                    selected_bytes=int(item.get("selected_bytes", 0)),
                    dropped_count=int(item.get("dropped_count", 0)),
                )
                for item in payload.get("bucket_stats", [])
            ),
            importance_threshold=float(payload.get("importance_threshold", 0.6)),
            base_importance_threshold=float(payload.get("base_importance_threshold", payload.get("importance_threshold", 0.6))),
            dynamic_pruning_enabled=bool(payload.get("dynamic_pruning_enabled", False)),
            pruning_hints=tuple(
                EvidencePruningHint(
                    candidate_id=str(item.get("candidate_id", "")),
                    bucket=str(item.get("bucket", "")),
                    importance_score=float(item.get("importance_score", 0.0)),
                    rendered_text_bytes=int(item.get("rendered_text_bytes", 0)),
                    keep_in_budget=bool(item.get("keep_in_budget", False)),
                    threshold=float(item.get("threshold", 0.6)),
                    estimated_tokens=int(item.get("estimated_tokens", 0)),
                    estimated_kv_tokens_saved_if_dropped=int(item.get("estimated_kv_tokens_saved_if_dropped", 0)),
                    available_kv_cache_bytes=int(item.get("available_kv_cache_bytes", 0)),
                    kv_bytes_per_token=int(item.get("kv_bytes_per_token", 0)),
                    dynamic_threshold=float(item.get("dynamic_threshold", 0.0)),
                    capacity_ratio=float(item.get("capacity_ratio", 0.0)),
                    budget_decision=str(item.get("budget_decision", "")),
                    pruning_class=str(item.get("pruning_class", "candidate")),
                    quality_guard=str(item.get("quality_guard", "")),
                    reason=str(item.get("reason", "")),
                    claim_boundary=str(item.get("claim_boundary", "")),
                    schema_version=str(item.get("schema_version", "")),
                )
                for item in payload.get("pruning_hints", [])
            ),
            full_corpus_tokens_estimate=int(payload.get("full_corpus_tokens_estimate", 0)),
            selected_evidence_tokens_estimate=int(payload.get("selected_evidence_tokens_estimate", 0)),
            dropped_candidate_bytes=int(payload.get("dropped_candidate_bytes", 0)),
            dropped_candidate_tokens_estimate=int(payload.get("dropped_candidate_tokens_estimate", 0)),
            estimated_kv_tokens_saved=int(payload.get("estimated_kv_tokens_saved", 0)),
            pruning_gain_ratio=float(payload.get("pruning_gain_ratio", 0.0)),
            available_kv_cache_bytes=int(payload.get("available_kv_cache_bytes", 0)),
            kv_bytes_per_token=int(payload.get("kv_bytes_per_token", 0)),
            target_sequence_tokens_estimate=int(payload.get("target_sequence_tokens_estimate", 0)),
            capacity_ratio=float(payload.get("capacity_ratio", 0.0)),
            budget_decision=str(payload.get("budget_decision", "")),
            policy_name=str(payload.get("policy_name", "statebus_input_level_evidence_pruning_v1")),
            claim_boundary=str(payload.get("claim_boundary", "")),
            schema_version=str(payload.get("schema_version", "")),
        )

    def _codeact_record_from_dict(self, payload: dict[str, object]) -> CodeActExecutionRecord:
        return CodeActExecutionRecord(
            task_id=str(payload.get("task_id", "")),
            step_id=str(payload.get("step_id", "")),
            attempt_id=str(payload.get("attempt_id", "")),
            execution_goal=str(payload.get("execution_goal", "")),
            script_relpath=str(payload.get("script_relpath", "")),
            request_relpath=str(payload.get("request_relpath", "")),
            output_relpath=str(payload.get("output_relpath", "")),
            plan_relpath=str(payload.get("plan_relpath", "")),
            exit_code=int(payload.get("exit_code", 0)),
            stdout_text=str(payload.get("stdout_text", "")),
            stderr_text=str(payload.get("stderr_text", "")),
            output_payload=dict(payload.get("output_payload", {})),
            generated_code_hash=str(payload.get("generated_code_hash", "")),
            request_hash=str(payload.get("request_hash", "")),
            plan_hash=str(payload.get("plan_hash", "")),
            stage_results=tuple(
                CodeActStageResult(
                    stage_id=str(stage.get("stage_id", "")),
                    ok=bool(stage.get("ok", False)),
                    action_results=tuple(
                        CodeActActionResult(
                            action_id=str(item.get("action_id", "")),
                            kind=str(item.get("kind", "")),
                            ok=bool(item.get("ok", False)),
                            output_relpath=str(item.get("output_relpath", "")),
                            output_hash=str(item.get("output_hash", "")),
                            metadata=dict(item.get("metadata", {})),
                        )
                        for item in stage.get("action_results", [])
                    ),
                )
                for stage in payload.get("stage_results", [])
            ),
            audit_stdout_bytes=int(payload.get("stdout_bytes", -1)),
            audit_stderr_bytes=int(payload.get("stderr_bytes", -1)),
            audit_output_payload_field_names=tuple(
                str(item) for item in payload.get("output_payload_field_names", [])
            ),
            sandbox_backend=str(payload.get("sandbox_backend", "legacy_subprocess")),
            sandbox_requested_backend=str(payload.get("sandbox_requested_backend", "legacy_subprocess")),
            sandbox_fallback_reason=str(payload.get("sandbox_fallback_reason", "")),
            schema_version=str(payload.get("schema_version", "")),
        )

    def _write_json_batch(self, writes: list[_JsonWriteSpec]) -> None:
        for write in writes:
            if write.trusted_source and write.source_path is not None:
                self._copy_json(write.path, write.source_path)
                continue
            self._write_json(write.path, write.payload, source_path=write.source_path)

    def _write_json(self, path: Path, payload: object, *, source_path: Path | None = None) -> None:
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        rendered = (stable_json_dumps(payload) + "\n").encode("utf-8")
        if path.exists() and path.read_bytes() == rendered:
            return
        if source_path is not None and source_path.exists() and source_path.read_bytes() == rendered:
            shutil.copyfile(source_path, path)
            return
        path.write_bytes(rendered)

    def _copy_json(self, path: Path, source_path: Path) -> None:
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        source_bytes = source_path.read_bytes()
        if path.exists() and path.read_bytes() == source_bytes:
            return
        shutil.copyfile(source_path, path)

    def _read_json(self, path: Path) -> dict[str, object]:
        return json.loads(path.read_bytes())
