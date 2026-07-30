from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

from statebus.contracts import RuntimeCompatibilitySignature, RuntimeSignatureManifestBundle
from statebus.utils import sha256_digest, stable_json_dumps


@dataclass(frozen=True)
class SignatureManifestEntry:
    entry_id: str
    entry_version: str
    entry_kind: str
    payload: dict[str, object]

    def canonical_payload(self) -> dict[str, object]:
        return {
            "entry_id": self.entry_id,
            "entry_version": self.entry_version,
            "entry_kind": self.entry_kind,
            "payload": dict(sorted(self.payload.items())),
        }


def capture_runtime_signature(
    *,
    repo_root: Path | None = None,
    prompt_manifests: tuple[SignatureManifestEntry, ...] = (),
    extractor_manifests: tuple[SignatureManifestEntry, ...] = (),
    tool_registry_manifests: tuple[SignatureManifestEntry, ...] = (),
) -> RuntimeCompatibilitySignature:
    root = repo_root or Path(__file__).resolve().parents[2]
    return RuntimeCompatibilitySignature(
        os_digest=_os_digest(),
        python_digest=_python_digest(),
        dependency_digest=_dependency_digest(root),
        tool_registry_digest=_manifest_digest(tool_registry_manifests),
        prompt_bundle_digest=_manifest_digest(prompt_manifests),
        extractor_bundle_digest=_manifest_digest(extractor_manifests),
    )


def capture_runtime_signature_manifest_bundle(
    *,
    prompt_manifests: tuple[SignatureManifestEntry, ...] = (),
    extractor_manifests: tuple[SignatureManifestEntry, ...] = (),
    tool_registry_manifests: tuple[SignatureManifestEntry, ...] = (),
) -> RuntimeSignatureManifestBundle:
    return RuntimeSignatureManifestBundle(
        prompt_manifests=tuple(entry.canonical_payload() for entry in prompt_manifests),
        extractor_manifests=tuple(entry.canonical_payload() for entry in extractor_manifests),
        tool_registry_manifests=tuple(entry.canonical_payload() for entry in tool_registry_manifests),
    )


def _os_digest() -> str:
    os_release = Path("/etc/os-release")
    payload = os_release.read_text(encoding="utf-8") if os_release.exists() else platform.platform()
    return sha256_digest({"os_release": payload})


def _python_digest() -> str:
    return sha256_digest(
        {
            "version": sys.version,
            "implementation": platform.python_implementation(),
            "cache_tag": getattr(sys.implementation, "cache_tag", ""),
            "executable": sys.executable,
        }
    )


def _dependency_digest(repo_root: Path) -> str:
    lock_candidates = (
        repo_root / "pyproject.toml",
        repo_root / "requirements-container-core.txt",
        repo_root / "requirements-container-embed.txt",
        repo_root / "requirements-host.txt",
    )
    payload: dict[str, str] = {}
    for path in lock_candidates:
        if path.exists():
            payload[str(path.relative_to(repo_root))] = path.read_text(encoding="utf-8")
    if not payload:
        payload["pythonpath"] = os.environ.get("PYTHONPATH", "")
    return sha256_digest(payload)


def _manifest_digest(entries: tuple[SignatureManifestEntry, ...]) -> str:
    payload = [
        entry.canonical_payload()
        for entry in sorted(entries, key=lambda item: (item.entry_kind, item.entry_id, item.entry_version))
    ]
    return sha256_digest(payload)


def runtime_signature_payload(signature: RuntimeCompatibilitySignature) -> dict[str, str]:
    payload = signature.structured_payload()
    payload["combined_digest"] = signature.combined_digest
    return payload


def runtime_signature_json(signature: RuntimeCompatibilitySignature) -> str:
    return stable_json_dumps(runtime_signature_payload(signature))
