from __future__ import annotations

import json
import time

import pytest

from v2.contracts import (
    CapabilityGrant,
    EvidenceCoverageStatus,
    EvidenceProjectionRequest,
)
from v2.refs import CanonicalEvidencePack, EvidenceItem, TableCellLocator
from v2.runtime.evidence_projection import EvidenceProjectionAdapter, EvidenceProjectionError


def _grant() -> CapabilityGrant:
    return CapabilityGrant(
        grant_id="grant",
        task_id="task",
        session_id="session",
        step_id="extract",
        attempt_id="attempt",
        capability_id="extract_metric_series_v1",
        capability_version="v1",
        input_ref_ids=("evidence-ref",),
        output_contract_version="statebus.metric_series.v1",
        workspace_root_id="workspace",
        max_runtime_ms=1_000,
        expires_at_ns=time.time_ns() + 1_000_000_000,
        approved_plan_hash="plan",
    )


def _pack(value: float = 120.0) -> CanonicalEvidencePack:
    return CanonicalEvidencePack(
        pack_id="pack",
        task_id="task",
        source_doc_hashes=("doc",),
        hard_facts=(
            EvidenceItem(
                item_id="revenue-q1",
                bucket="hard_fact",
                locator=TableCellLocator(source_doc_hash="doc", table_id="income", row_idx=1, col_idx=1),
                rendered_text="Revenue = 120 for ACME 2026Q1.",
                metadata={"structured_row": {"quarter": "2026Q1", "revenue_musd": value}},
            ),
        ),
    )


def _request(pack: CanonicalEvidencePack) -> EvidenceProjectionRequest:
    return EvidenceProjectionRequest(
        task_id="task",
        session_id="session",
        step_id="extract",
        evidence_pack_ref_id="evidence-ref",
        evidence_pack_hash=pack.pack_hash,
        requested_fields=("quarter", "revenue_musd"),
    )


def test_projection_materializes_rows_from_evidence_and_preserves_locator_lineage(tmp_path) -> None:
    pack = _pack()
    rows, artifact, report = EvidenceProjectionAdapter().project(
        request=_request(pack),
        evidence_pack=pack,
        coverage_status=EvidenceCoverageStatus.COMPLETE,
        grant=_grant(),
        attempt_workspace=tmp_path,
    )
    assert rows == ({"quarter": "2026Q1", "revenue_musd": 120.0},)
    assert artifact.verification_state.value == "verified"
    assert artifact.metadata["attempt_id"] == "attempt"
    assert report.consumed_evidence_item_ids == ("revenue-q1",)
    assert report.row_lineage[0]["evidence_item_id"] == "revenue-q1"
    assert report.row_lineage[0]["locator"]["table_id"] == "income"
    assert json.loads((tmp_path / artifact.relpath).read_text(encoding="utf-8")) == list(rows)


def test_projection_changes_with_evidence_and_rejects_missing_provenance_or_unverified_pack(tmp_path) -> None:
    first = _pack(120.0)
    second = _pack(121.0)
    first_rows, first_artifact, _ = EvidenceProjectionAdapter().project(
        request=_request(first), evidence_pack=first, coverage_status=EvidenceCoverageStatus.COMPLETE,
        grant=_grant(), attempt_workspace=tmp_path / "first",
    )
    second_rows, second_artifact, _ = EvidenceProjectionAdapter().project(
        request=_request(second), evidence_pack=second, coverage_status=EvidenceCoverageStatus.COMPLETE,
        grant=_grant(), attempt_workspace=tmp_path / "second",
    )
    assert first_rows != second_rows
    assert first_artifact.blob_hash != second_artifact.blob_hash
    with pytest.raises(EvidenceProjectionError, match="requires_verified"):
        EvidenceProjectionAdapter().project(
            request=_request(first), evidence_pack=first, coverage_status=EvidenceCoverageStatus.INSUFFICIENT_EVIDENCE,
            grant=_grant(), attempt_workspace=tmp_path / "rejected",
        )
    no_locator = CanonicalEvidencePack(
        pack_id="no-locator", task_id="task", source_doc_hashes=("doc",),
        hard_facts=(EvidenceItem(item_id="row", bucket="hard_fact", locator=None, metadata={"structured_row": {"quarter": "2026Q1", "revenue_musd": 1.0}}),),
    )
    with pytest.raises(EvidenceProjectionError, match="locator_required"):
        EvidenceProjectionAdapter().project(
            request=_request(no_locator), evidence_pack=no_locator, coverage_status=EvidenceCoverageStatus.COMPLETE,
            grant=_grant(), attempt_workspace=tmp_path / "missing-locator",
        )


def test_projection_accepts_grouped_rows_but_rejects_conflicting_same_dimensions(tmp_path) -> None:
    rows = (
        EvidenceItem(
            item_id="enterprise-q1",
            bucket="hard_fact",
            locator=TableCellLocator(source_doc_hash="doc", table_id="segments", row_idx=1, col_idx=3),
            metadata={"structured_row": {"quarter": "2026Q1", "segment": "enterprise", "revenue_musd": 82.0}},
        ),
        EvidenceItem(
            item_id="consumer-q1",
            bucket="hard_fact",
            locator=TableCellLocator(source_doc_hash="doc", table_id="segments", row_idx=2, col_idx=3),
            metadata={"structured_row": {"quarter": "2026Q1", "segment": "consumer", "revenue_musd": 43.0}},
        ),
    )
    pack = CanonicalEvidencePack(
        pack_id="grouped", task_id="task", source_doc_hashes=("doc",), hard_facts=rows,
    )
    request = EvidenceProjectionRequest(
        task_id="task", session_id="session", step_id="extract", evidence_pack_ref_id="evidence-ref",
        evidence_pack_hash=pack.pack_hash, requested_fields=("quarter", "segment", "revenue_musd"),
    )
    projected, _, report = EvidenceProjectionAdapter().project(
        request=request, evidence_pack=pack, coverage_status=EvidenceCoverageStatus.COMPLETE,
        grant=_grant(), attempt_workspace=tmp_path / "grouped",
    )
    assert projected == (
        {"quarter": "2026Q1", "segment": "consumer", "revenue_musd": 43.0},
        {"quarter": "2026Q1", "segment": "enterprise", "revenue_musd": 82.0},
    )
    assert tuple(
        (
            lineage["row_index"],
            lineage["evidence_item_id"],
            lineage["locator"]["table_id"],
            lineage["locator"]["row_idx"],
        )
        for lineage in report.row_lineage
    ) == (
        (0, "consumer-q1", "segments", 2),
        (1, "enterprise-q1", "segments", 1),
    )

    conflict = CanonicalEvidencePack(
        pack_id="conflict", task_id="task", source_doc_hashes=("doc",),
        hard_facts=rows + (
            EvidenceItem(
                item_id="enterprise-q1-conflict",
                bucket="hard_fact",
                locator=TableCellLocator(source_doc_hash="doc", table_id="segments", row_idx=3, col_idx=3),
                metadata={"structured_row": {"quarter": "2026Q1", "segment": "enterprise", "revenue_musd": 99.0}},
            ),
        ),
    )
    with pytest.raises(EvidenceProjectionError, match="projection_conflicting_values"):
        EvidenceProjectionAdapter().project(
            request=EvidenceProjectionRequest(
                task_id="task", session_id="session", step_id="extract", evidence_pack_ref_id="evidence-ref",
                evidence_pack_hash=conflict.pack_hash, requested_fields=("quarter", "segment", "revenue_musd"),
            ),
            evidence_pack=conflict,
            coverage_status=EvidenceCoverageStatus.COMPLETE,
            grant=_grant(),
            attempt_workspace=tmp_path / "conflict",
        )
