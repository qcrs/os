from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from v2.contracts import (
    ARTIFACT_INVALIDATION_RECORD_SCHEMA_VERSION,
    ARTIFACT_SETTLEMENT_RECORD_SCHEMA_VERSION,
    INPUT_VALIDATOR_REPORT_SCHEMA_VERSION,
    RefStatus,
)
from v2.refs import ExecutionArtifactRef
from v2.utils import sha256_digest, stable_json_dumps


class ArtifactCommitState(StrEnum):
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    INVALIDATED = "invalidated"


@dataclass(frozen=True)
class StepWorkspaceLayout:
    task_id: str
    step_id: str
    root: Path
    inputs_dir: Path
    outputs_dir: Path
    logs_dir: Path
    tmp_dir: Path
    manifest_dir: Path


@dataclass(frozen=True)
class WorkspaceLayout:
    task_id: str
    root: Path
    inputs_dir: Path
    outputs_dir: Path
    logs_dir: Path
    tmp_dir: Path
    script_dir: Path
    manifest_dir: Path


@dataclass(frozen=True)
class ArtifactManifestItem:
    artifact_name: str
    artifact_type: str
    relpath: str
    size_bytes: int
    sha256: str

    def canonical_payload(self) -> dict[str, str | int]:
        return {
            "artifact_name": self.artifact_name,
            "artifact_type": self.artifact_type,
            "relpath": self.relpath,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class InputManifestItem:
    name: str
    artifact_type: str
    relpath: str
    blob_hash: str
    source_ref_id: str

    def canonical_payload(self) -> dict[str, str]:
        return {
            "name": self.name,
            "artifact_type": self.artifact_type,
            "relpath": self.relpath,
            "blob_hash": self.blob_hash,
            "source_ref_id": self.source_ref_id,
        }


@dataclass(frozen=True)
class InputManifest:
    task_id: str
    step_id: str
    workspace_root: str
    inputs: tuple[InputManifestItem, ...]

    def canonical_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "step_id": self.step_id,
            "workspace_root": self.workspace_root,
            "inputs": [item.canonical_payload() for item in self.inputs],
        }

    @property
    def manifest_hash(self) -> str:
        return sha256_digest(self.canonical_payload())

    def snapshot_payload(self) -> dict[str, object]:
        payload = self.canonical_payload()
        payload["manifest_hash"] = self.manifest_hash
        return payload


@dataclass(frozen=True)
class ArtifactOutputManifest:
    task_id: str
    step_id: str
    outputs: tuple[ArtifactManifestItem, ...]

    def canonical_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "step_id": self.step_id,
            "outputs": [item.canonical_payload() for item in self.outputs],
        }

    @property
    def manifest_hash(self) -> str:
        return sha256_digest(self.canonical_payload())

    def snapshot_payload(self) -> dict[str, object]:
        payload = self.canonical_payload()
        payload["manifest_hash"] = self.manifest_hash
        return payload


@dataclass(frozen=True)
class ArtifactValidatorReport:
    task_id: str
    step_id: str
    artifact_id: str
    validation_scope: str
    passed: bool
    fail_reason: str = ""
    consumed_by: tuple[str, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "statebus.artifact_validator_report.v1"
    audit_details_hash: str = ""

    def canonical_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "step_id": self.step_id,
            "artifact_id": self.artifact_id,
            "validation_scope": self.validation_scope,
            "passed": self.passed,
            "fail_reason": self.fail_reason,
            "consumed_by": list(self.consumed_by),
            "metrics": dict(self.metrics),
            "details": dict(self.details),
            "schema_version": self.schema_version,
        }

    @property
    def report_hash(self) -> str:
        if self.audit_details_hash:
            return self.audit_details_hash
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class InputValidatorReport:
    task_id: str
    step_id: str
    validation_scope: str
    passed: bool
    fail_reason: str = ""
    required_inputs: tuple[str, ...] = ()
    observed_inputs: tuple[str, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    schema_version: str = INPUT_VALIDATOR_REPORT_SCHEMA_VERSION
    audit_details_hash: str = ""

    def canonical_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "step_id": self.step_id,
            "validation_scope": self.validation_scope,
            "passed": self.passed,
            "fail_reason": self.fail_reason,
            "required_inputs": list(self.required_inputs),
            "observed_inputs": list(self.observed_inputs),
            "metrics": dict(self.metrics),
            "details": dict(self.details),
            "schema_version": self.schema_version,
        }

    @property
    def report_hash(self) -> str:
        if self.audit_details_hash:
            return self.audit_details_hash
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class ArtifactSettlementRecord:
    artifact_id: str
    task_id: str
    step_id: str
    from_state: str
    to_state: str
    commit_gate_reason: str
    quality_floor_pass: bool
    validator_report_hashes: tuple[str, ...] = ()
    input_validator_hashes: tuple[str, ...] = ()
    replay_ready: bool = False
    schema_version: str = ARTIFACT_SETTLEMENT_RECORD_SCHEMA_VERSION
    audit_settlement_hash: str = ""

    def canonical_payload(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "commit_gate_reason": self.commit_gate_reason,
            "quality_floor_pass": self.quality_floor_pass,
            "validator_report_hashes": list(self.validator_report_hashes),
            "input_validator_hashes": list(self.input_validator_hashes),
            "replay_ready": self.replay_ready,
            "schema_version": self.schema_version,
        }

    @property
    def settlement_hash(self) -> str:
        if self.audit_settlement_hash:
            return self.audit_settlement_hash
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class ArtifactInvalidationRecord:
    artifact_id: str
    task_id: str
    step_id: str
    invalidation_reason: str
    invalidated_from_state: str
    validator_report_hashes: tuple[str, ...] = ()
    input_validator_hashes: tuple[str, ...] = ()
    schema_version: str = ARTIFACT_INVALIDATION_RECORD_SCHEMA_VERSION
    audit_invalidation_hash: str = ""

    def canonical_payload(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "invalidation_reason": self.invalidation_reason,
            "invalidated_from_state": self.invalidated_from_state,
            "validator_report_hashes": list(self.validator_report_hashes),
            "input_validator_hashes": list(self.input_validator_hashes),
            "schema_version": self.schema_version,
        }

    @property
    def invalidation_hash(self) -> str:
        if self.audit_invalidation_hash:
            return self.audit_invalidation_hash
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class MaterializedFile:
    logical_name: str
    relpath: str
    path: Path
    sha256: str
    size_bytes: int
    write_performed: bool = True


@dataclass(frozen=True)
class MaterializedInputBundle:
    files: tuple[MaterializedFile, ...]
    manifest_file: MaterializedFile

    @property
    def manifest_path(self) -> Path:
        return self.manifest_file.path


@dataclass(frozen=True)
class MaterializedOutputBundle:
    files: tuple[MaterializedFile, ...]
    manifest_file: MaterializedFile

    @property
    def manifest_path(self) -> Path:
        return self.manifest_file.path


@dataclass
class WorkspaceManager:
    workspace_root: Path

    def layout_for_task(self, task_id: str) -> WorkspaceLayout:
        root = self.workspace_root / task_id
        return WorkspaceLayout(
            task_id=task_id,
            root=root,
            inputs_dir=root / "inputs",
            outputs_dir=root / "outputs",
            logs_dir=root / "logs",
            tmp_dir=root / "tmp",
            script_dir=root / "script",
            manifest_dir=root / "manifest",
        )

    def ensure_layout(self, task_id: str) -> WorkspaceLayout:
        layout = self.layout_for_task(task_id)
        for directory in (
            layout.root,
            layout.inputs_dir,
            layout.outputs_dir,
            layout.logs_dir,
            layout.tmp_dir,
            layout.script_dir,
            layout.manifest_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return layout

    def step_layout(self, layout: WorkspaceLayout, step_id: str) -> StepWorkspaceLayout:
        root = layout.root / "steps" / step_id
        return StepWorkspaceLayout(
            task_id=layout.task_id,
            step_id=step_id,
            root=root,
            inputs_dir=root / "inputs",
            outputs_dir=root / "outputs",
            logs_dir=root / "logs",
            tmp_dir=root / "tmp",
            manifest_dir=root / "manifest",
        )

    def ensure_step_layout(self, layout: WorkspaceLayout, step_id: str) -> StepWorkspaceLayout:
        step_layout = self.step_layout(layout, step_id)
        for directory in (
            step_layout.root,
            step_layout.inputs_dir,
            step_layout.outputs_dir,
            step_layout.logs_dir,
            step_layout.tmp_dir,
            step_layout.manifest_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return step_layout

    def materialize_input_bundle(
        self,
        layout: WorkspaceLayout,
        manifest: InputManifest,
        payload_by_name: dict[str, Any],
        *,
        materialized_by_name: dict[str, MaterializedFile] | None = None,
    ) -> MaterializedInputBundle:
        reused = materialized_by_name or {}
        files = []
        for item in manifest.inputs:
            reused_file = reused.get(item.name)
            if reused_file is not None:
                if reused_file.relpath != item.relpath:
                    raise ValueError(
                        f"materialized input relpath mismatch for {item.name}: {reused_file.relpath} != {item.relpath}"
                    )
                files.append(replace(reused_file, logical_name=item.name, write_performed=False))
                continue
            files.append(self.write_json(layout, item.relpath, payload_by_name[item.name], logical_name=item.name))
        manifest_file = self.write_json(
            layout,
            f"manifest/{manifest.step_id}.input_manifest.json",
            manifest.snapshot_payload(),
            logical_name="input_manifest",
        )
        return MaterializedInputBundle(files=tuple(files), manifest_file=manifest_file)

    def materialize_output_bundle(
        self,
        layout: WorkspaceLayout,
        manifest: ArtifactOutputManifest,
        payload_by_name: dict[str, Any],
        *,
        materialized_by_name: dict[str, MaterializedFile] | None = None,
    ) -> MaterializedOutputBundle:
        reused = materialized_by_name or {}
        files = []
        for item in manifest.outputs:
            reused_file = reused.get(item.artifact_name)
            if reused_file is not None:
                if reused_file.relpath != item.relpath:
                    raise ValueError(
                        "materialized output relpath mismatch for "
                        f"{item.artifact_name}: {reused_file.relpath} != {item.relpath}"
                    )
                files.append(replace(reused_file, logical_name=item.artifact_name, write_performed=False))
                continue
            files.append(
                self.write_json(
                    layout,
                    item.relpath,
                    payload_by_name[item.artifact_name],
                    logical_name=item.artifact_name,
                )
            )
        manifest_file = self.write_json(
            layout,
            f"manifest/{manifest.step_id}.artifact_output_manifest.json",
            manifest.snapshot_payload(),
            logical_name="artifact_output_manifest",
        )
        return MaterializedOutputBundle(files=tuple(files), manifest_file=manifest_file)

    def write_validator_report(
        self,
        layout: WorkspaceLayout,
        report: ArtifactValidatorReport,
    ) -> MaterializedFile:
        return self.write_json(
            layout,
            f"manifest/{report.step_id}.{report.artifact_id}.validator_report.json",
            report.canonical_payload(),
            logical_name="validator_report",
        )

    def write_json(
        self,
        layout: WorkspaceLayout,
        relpath: str,
        payload: Any,
        *,
        logical_name: str,
    ) -> MaterializedFile:
        rendered = (stable_json_dumps(payload) + "\n").encode("utf-8")
        path = layout.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        write_performed = True
        if path.exists() and path.read_bytes() == rendered:
            write_performed = False
        else:
            path.write_bytes(rendered)
        return MaterializedFile(
            logical_name=logical_name,
            relpath=relpath,
            path=path,
            sha256=sha256_digest(rendered),
            size_bytes=len(rendered),
            write_performed=write_performed,
        )


@dataclass
class ArtifactLifecycleManager:
    artifacts: dict[str, ExecutionArtifactRef] = field(default_factory=dict)
    settlement_records: dict[str, ArtifactSettlementRecord] = field(default_factory=dict)
    invalidation_records: dict[str, ArtifactInvalidationRecord] = field(default_factory=dict)

    def register_candidate(self, artifact: ExecutionArtifactRef) -> ExecutionArtifactRef:
        candidate = replace(
            artifact,
            verification_state=RefStatus.CANDIDATE,
        )
        self.artifacts[candidate.artifact_id] = candidate
        return candidate

    def mark_verified(self, artifact_id: str) -> ExecutionArtifactRef:
        artifact = self.artifacts[artifact_id]
        verified = replace(
            artifact,
            verification_state=RefStatus.VERIFIED,
            replay_ready=True,
        )
        self.artifacts[artifact_id] = verified
        return verified

    def mark_invalidated(self, artifact_id: str) -> ExecutionArtifactRef:
        artifact = self.artifacts[artifact_id]
        invalidated = replace(
            artifact,
            verification_state=RefStatus.INVALIDATED,
            replay_ready=False,
        )
        self.artifacts[artifact_id] = invalidated
        return invalidated

    def record_settlement(self, record: ArtifactSettlementRecord) -> ArtifactSettlementRecord:
        self.settlement_records[record.artifact_id] = record
        return record

    def record_invalidation(self, record: ArtifactInvalidationRecord) -> ArtifactInvalidationRecord:
        self.invalidation_records[record.artifact_id] = record
        return record
