from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re
from typing import Any

from v2.contracts import (
    CapabilityGrant,
    EvidenceCoverageStatus,
    EvidenceProjectionReport,
    EvidenceProjectionRequest,
    RefStatus,
)
from v2.refs import CanonicalEvidencePack, ExecutionArtifactRef, TableCellLocator
from v2.runtime.workspace import ArtifactLifecycleManager
from v2.utils import sha256_digest, stable_json_dumps


class EvidenceProjectionError(ValueError):
    pass


class MetricEvidenceParser:
    """Parse the repository's canonical table rendering without ad hoc splitting."""

    _METRIC_ROW = re.compile(
        r"^(?P<metric>[A-Za-z_ ]+)\s*=\s*(?P<value>-?(?:\d+(?:\.\d*)?|\.\d+))"
        r"\s+for\s+(?:(?P<entity>[A-Za-z0-9_.-]+)\s+)?(?P<quarter>\d{4}Q[1-4])\.$"
    )

    @classmethod
    def parse(cls, rendered_text: str) -> dict[str, object] | None:
        match = cls._METRIC_ROW.fullmatch(rendered_text.strip())
        if match is None:
            return None
        metric = match.group("metric").strip().lower().replace(" ", "_")
        value_field = metric if metric.endswith(("_musd", "_pct")) else f"{metric}_musd"
        row: dict[str, object] = {
            "quarter": match.group("quarter"),
            value_field: float(match.group("value")),
        }
        if match.group("entity"):
            row["entity"] = match.group("entity")
        return row


class EvidenceProjectionAdapter:
    """Turn a verified EvidencePack into a typed, lineage-preserving ArtifactRef."""

    _BUCKET_EVIDENCE_TYPES = {
        "hard_facts": "table",
        "structured_evidence": "table",
        "semantic_contexts": "semantic_context",
        "lexical_hints": "lexical_hint",
        "conflicts": "conflict",
    }

    def project(
        self,
        *,
        request: EvidenceProjectionRequest,
        evidence_pack: CanonicalEvidencePack,
        coverage_status: EvidenceCoverageStatus,
        grant: CapabilityGrant,
        attempt_workspace: Path,
    ) -> tuple[tuple[dict[str, object], ...], ExecutionArtifactRef, EvidenceProjectionReport]:
        self._validate_request(request, evidence_pack, coverage_status, grant)
        rows: list[dict[str, object]] = []
        row_lineage: list[dict[str, object]] = []
        consumed: list[str] = []
        conflicts: list[str] = []
        seen_by_key: dict[tuple[object, ...], dict[str, object]] = {}
        for bucket in self._BUCKET_EVIDENCE_TYPES:
            evidence_type = self._BUCKET_EVIDENCE_TYPES[bucket]
            if evidence_type not in request.allowed_evidence_types:
                continue
            for item in getattr(evidence_pack, bucket):
                if request.required_locator and item.locator is None:
                    raise EvidenceProjectionError("evidence_locator_required")
                row = self._extract_row(item.metadata, item.rendered_text)
                if row is None:
                    continue
                missing = tuple(field for field in request.requested_fields if field not in row)
                if missing:
                    continue
                typed = {field: self._typed_value(row[field]) for field in request.requested_fields}
                # A period alone does not identify a grouped operating-metric
                # row: both ``enterprise`` and ``consumer`` can legitimately
                # have a 2026Q1 value.  Use every string-valued requested
                # field as a stable dimension key.  This preserves conflict
                # detection for competing evidence about the same dimensions
                # while allowing a typed table to contain multiple groups.
                key = tuple(
                    (field, value)
                    for field, value in typed.items()
                    if isinstance(value, str)
                )
                if not key:
                    key = tuple(sorted(typed.items()))
                prior = seen_by_key.get(key)
                if prior is not None and prior != typed:
                    conflicts.append(item.item_id)
                    continue
                if prior is not None:
                    continue
                seen_by_key[key] = typed
                rows.append(typed)
                consumed.append(item.item_id)
                row_lineage.append(
                    {
                        "row_index": len(rows) - 1,
                        "evidence_item_id": item.item_id,
                        "locator": self._locator_payload(item.locator),
                        "source_doc_hash": getattr(item.locator, "source_doc_hash", ""),
                    }
                )
        missing_fields = tuple(
            field for field in request.requested_fields if not any(field in row for row in rows)
        )
        if conflicts:
            raise EvidenceProjectionError("projection_conflicting_values")
        if missing_fields or not rows:
            raise EvidenceProjectionError(
                "projection_missing_fields:" + ",".join(missing_fields or request.requested_fields)
            )
        projected_rows = sorted(
            zip(rows, row_lineage, strict=True),
            key=lambda item: (
                stable_json_dumps(item[0]),
                str(item[1]["evidence_item_id"]),
                stable_json_dumps(item[1]["locator"]),
            ),
        )
        rows = [row for row, _ in projected_rows]
        row_lineage = [
            {**lineage, "row_index": row_index}
            for row_index, (_, lineage) in enumerate(projected_rows)
        ]
        payload = stable_json_dumps(rows).encode("utf-8")
        projection_dir = attempt_workspace / "projection"
        projection_dir.mkdir(parents=True, exist_ok=True)
        output_path = projection_dir / "typed_rows.json"
        output_path.write_bytes(payload)
        artifact = self._verified_artifact(
            request=request,
            grant=grant,
            attempt_workspace=attempt_workspace,
            output_path=output_path,
            payload=payload,
            consumed=tuple(consumed),
        )
        report = EvidenceProjectionReport(
            request_hash=request.request_hash,
            input_evidence_pack_hash=evidence_pack.pack_hash,
            consumed_evidence_item_ids=tuple(consumed),
            row_lineage=tuple(row_lineage),
            output_fields=request.requested_fields,
            row_count=len(rows),
            output_artifact_ref_id=artifact.artifact_id,
            output_artifact_hash=artifact.blob_hash,
            conflict_item_ids=tuple(conflicts),
            projection_policy_version=request.projection_policy_version,
        )
        return tuple(rows), artifact, report

    @staticmethod
    def _validate_request(
        request: EvidenceProjectionRequest,
        evidence_pack: CanonicalEvidencePack,
        coverage_status: EvidenceCoverageStatus,
        grant: CapabilityGrant,
    ) -> None:
        if request.schema_version != "statebus.evidence_projection_request.v1":
            raise EvidenceProjectionError("invalid_projection_request_schema")
        if not request.requested_fields or len(set(request.requested_fields)) != len(request.requested_fields):
            raise EvidenceProjectionError("invalid_projection_fields")
        if request.task_id != grant.task_id or request.session_id != grant.session_id or request.step_id != grant.step_id:
            raise EvidenceProjectionError("projection_grant_scope_mismatch")
        if evidence_pack.task_id != request.task_id or evidence_pack.pack_hash != request.evidence_pack_hash:
            raise EvidenceProjectionError("projection_evidence_pack_mismatch")
        if coverage_status != EvidenceCoverageStatus.COMPLETE:
            raise EvidenceProjectionError("projection_requires_verified_evidence_pack")
        if grant.expires_at_ns <= __import__("time").time_ns():
            raise EvidenceProjectionError("capability_grant_expired")

    @staticmethod
    def _extract_row(metadata: dict[str, Any], rendered_text: str) -> dict[str, object] | None:
        for key in ("structured_row", "row", "row_payload"):
            value = metadata.get(key)
            if isinstance(value, dict):
                return {str(field): item for field, item in value.items()}
        try:
            parsed = json.loads(rendered_text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return {str(field): item for field, item in parsed.items()}
        return MetricEvidenceParser.parse(rendered_text)

    @staticmethod
    def _typed_value(value: object) -> object:
        if isinstance(value, bool) or value is None:
            raise EvidenceProjectionError("unsupported_projection_value")
        if isinstance(value, (int, float, str)):
            return value
        raise EvidenceProjectionError("unsupported_projection_value")

    @staticmethod
    def _locator_payload(locator: object) -> dict[str, object]:
        if locator is None:
            return {}
        if isinstance(locator, TableCellLocator):
            return asdict(locator)
        return {
            key: value
            for key, value in vars(locator).items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }

    @staticmethod
    def _verified_artifact(
        *,
        request: EvidenceProjectionRequest,
        grant: CapabilityGrant,
        attempt_workspace: Path,
        output_path: Path,
        payload: bytes,
        consumed: tuple[str, ...],
    ) -> ExecutionArtifactRef:
        lifecycle = ArtifactLifecycleManager()
        candidate = lifecycle.register_candidate(
            ExecutionArtifactRef(
                artifact_id=f"projection-{grant.task_id}-{grant.step_id}-{grant.attempt_id}",
                task_id=grant.task_id,
                step_id=grant.step_id,
                artifact_type="json",
                root_id=str(attempt_workspace),
                relpath=str(output_path.relative_to(attempt_workspace)),
                blob_hash=sha256_digest(payload),
                size_bytes=len(payload),
                produced_by="runtime_projection",
                workspace_relpath=str(output_path.relative_to(attempt_workspace)),
                manifest_hash=request.request_hash,
                metadata={
                    "schema_version": "statebus.evidence_projection_artifact.v1",
                    "grant_hash": grant.grant_hash,
                    "session_id": grant.session_id,
                    "attempt_id": grant.attempt_id,
                    "evidence_item_ids": list(consumed),
                },
            )
        )
        artifact = lifecycle.mark_verified(candidate.artifact_id)
        if artifact.verification_state != RefStatus.VERIFIED:
            raise EvidenceProjectionError("projection_artifact_not_verified")
        return artifact
