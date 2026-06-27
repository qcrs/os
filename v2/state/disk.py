from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from v2.contracts import RefKind, RefRegistryEntry, RefStatus, StorageKind
from v2.provenance import (
    evidence_pack_from_dict,
    evidence_pack_to_dict,
    manifest_from_dict,
    manifest_to_dict,
)
from v2.refs import CanonicalEvidencePack, HydrateManifest
from v2.runtime.workspace import ArtifactManifestItem, ArtifactOutputManifest
from v2.utils import stable_json_dumps


class RefManifestMissingError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class PersistedContractPaths:
    registry_path: Path
    hydrate_manifest_path: Path | None = None
    evidence_pack_path: Path | None = None
    artifact_manifest_path: Path | None = None


@dataclass
class JsonContractStore:
    root: Path

    def __post_init__(self) -> None:
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.sidecar_hydrate_dir.mkdir(parents=True, exist_ok=True)
        self.sidecar_evidence_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_manifest_dir.mkdir(parents=True, exist_ok=True)

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
    def artifact_manifest_dir(self) -> Path:
        return self.root / "manifests" / "artifacts"

    def put_ref_registry_entry(self, entry: RefRegistryEntry) -> Path:
        payload = self._read_registry_payload()
        payload[entry.ref_id] = entry.small_index_payload()
        self._write_json(self.registry_path, payload)
        return self.registry_path

    def get_ref_registry_entry(self, ref_id: str) -> RefRegistryEntry:
        payload = self._read_registry_payload()
        item = dict(payload[ref_id])
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

    def write_artifact_output_manifest(self, manifest: ArtifactOutputManifest) -> Path:
        path = self.artifact_manifest_dir / f"{manifest.manifest_hash}.json"
        self._write_json(path, self._artifact_manifest_to_dict(manifest))
        return path

    def read_artifact_output_manifest(self, manifest_hash: str) -> ArtifactOutputManifest:
        path = self.artifact_manifest_dir / f"{manifest_hash}.json"
        if not path.exists():
            raise RefManifestMissingError(f"artifact manifest missing: {manifest_hash}")
        return self._artifact_manifest_from_dict(self._read_json(path))

    def persist_contract_bundle(
        self,
        *,
        registry_entries: list[RefRegistryEntry],
        hydrate_manifest: HydrateManifest,
        evidence_pack: CanonicalEvidencePack,
        artifact_manifest: ArtifactOutputManifest,
    ) -> PersistedContractPaths:
        for entry in registry_entries:
            self.put_ref_registry_entry(entry)
        return PersistedContractPaths(
            registry_path=self.registry_path,
            hydrate_manifest_path=self.write_hydrate_manifest(hydrate_manifest),
            evidence_pack_path=self.write_evidence_pack(evidence_pack),
            artifact_manifest_path=self.write_artifact_output_manifest(artifact_manifest),
        )

    def load_contract_bundle(
        self,
        *,
        state_ref_id: str,
        artifact_ref_id: str,
        evidence_pack_hash: str,
    ) -> tuple[RefRegistryEntry, RefRegistryEntry, HydrateManifest, CanonicalEvidencePack, ArtifactOutputManifest]:
        state_entry = self.get_ref_registry_entry(state_ref_id)
        artifact_entry = self.get_ref_registry_entry(artifact_ref_id)
        if not artifact_entry.manifest_hash:
            raise RefManifestMissingError(f"artifact manifest hash missing for ref: {artifact_ref_id}")
        hydrate_manifest = self.read_hydrate_manifest(state_entry.manifest_hash)
        evidence_pack = self.read_evidence_pack(evidence_pack_hash)
        artifact_manifest = self.read_artifact_output_manifest(artifact_entry.manifest_hash)
        return state_entry, artifact_entry, hydrate_manifest, evidence_pack, artifact_manifest

    def _read_registry_payload(self) -> dict[str, dict[str, str]]:
        if not self.registry_path.exists():
            return {}
        return dict(self._read_json(self.registry_path))

    def _artifact_manifest_to_dict(self, manifest: ArtifactOutputManifest) -> dict[str, object]:
        return {
            "task_id": manifest.task_id,
            "step_id": manifest.step_id,
            "manifest_hash": manifest.manifest_hash,
            "outputs": [item.canonical_payload() for item in manifest.outputs],
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

    def _write_json(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")

    def _read_json(self, path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))
