from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path

from v2.contracts import RefStatus
from v2.refs import ExecutionArtifactRef
from v2.utils import sha256_digest


class ArtifactCommitState(StrEnum):
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    INVALIDATED = "invalidated"


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


@dataclass
class ArtifactLifecycleManager:
    artifacts: dict[str, ExecutionArtifactRef] = field(default_factory=dict)

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
