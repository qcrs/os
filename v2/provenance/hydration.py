from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from v2.refs import (
    CanonicalEvidencePack,
    EvidenceItem,
    FragmentLocator,
    HydrateManifest,
    HydrateManifestEntry,
    SourceLocator,
    TableCellLocator,
    TextSpanLocator,
)


def locator_to_dict(locator: SourceLocator) -> dict[str, Any]:
    if isinstance(locator, TextSpanLocator):
        return {
            "locator_type": locator.locator_type,
            "source_doc_hash": locator.source_doc_hash,
            "canonical_text_id": locator.canonical_text_id,
            "start_char": locator.start_char,
            "end_char": locator.end_char,
            "extractor_version": locator.extractor_version,
        }
    if isinstance(locator, TableCellLocator):
        return {
            "locator_type": locator.locator_type,
            "source_doc_hash": locator.source_doc_hash,
            "table_id": locator.table_id,
            "sheet_name": locator.sheet_name,
            "row_idx": locator.row_idx,
            "col_idx": locator.col_idx,
            "extractor_version": locator.extractor_version,
        }
    if isinstance(locator, FragmentLocator):
        return {
            "locator_type": locator.locator_type,
            "source_doc_hash": locator.source_doc_hash,
            "fragment_id": locator.fragment_id,
            "extractor_version": locator.extractor_version,
            "page_no": locator.page_no,
        }
    raise TypeError(f"unsupported locator type: {type(locator)!r}")


def locator_from_dict(payload: dict[str, Any]) -> SourceLocator:
    locator_type = payload.get("locator_type")
    if locator_type == "text_span":
        return TextSpanLocator(
            source_doc_hash=str(payload.get("source_doc_hash", "")),
            canonical_text_id=str(payload.get("canonical_text_id", "")),
            start_char=int(payload.get("start_char", 0)),
            end_char=int(payload.get("end_char", 0)),
            extractor_version=str(payload.get("extractor_version", "")),
        )
    if locator_type == "table_cell":
        return TableCellLocator(
            source_doc_hash=str(payload.get("source_doc_hash", "")),
            table_id=str(payload.get("table_id", "")),
            sheet_name=str(payload.get("sheet_name", "")),
            row_idx=int(payload.get("row_idx", 0)),
            col_idx=int(payload.get("col_idx", 0)),
            extractor_version=str(payload.get("extractor_version", "")),
        )
    if locator_type == "fragment":
        page_no = payload.get("page_no")
        return FragmentLocator(
            source_doc_hash=str(payload.get("source_doc_hash", "")),
            fragment_id=str(payload.get("fragment_id", "")),
            extractor_version=str(payload.get("extractor_version", "")),
            page_no=None if page_no is None else int(page_no),
        )
    raise ValueError(f"unknown locator_type: {locator_type!r}")


def manifest_to_dict(manifest: HydrateManifest) -> dict[str, Any]:
    return {
        "manifest_id": manifest.manifest_id,
        "source_doc_hashes": list(manifest.source_doc_hashes),
        "entries": [
            {
                "row_idx": entry.row_idx,
                "stable_key": entry.stable_key,
                "byte_hint": entry.byte_hint,
                "candidate_id": entry.candidate_id,
                "bucket": entry.bucket,
                "importance_score": entry.importance_score,
                "locator": locator_to_dict(entry.locator),
            }
            for entry in manifest.entries
        ],
        "canonicalizer_version": manifest.canonicalizer_version,
        "extractor_version": manifest.extractor_version,
        "schema_version": manifest.schema_version,
        "created_at_ns": manifest.created_at_ns,
    }


def manifest_from_dict(payload: dict[str, Any]) -> HydrateManifest:
    return HydrateManifest(
        manifest_id=str(payload.get("manifest_id", "")),
        source_doc_hashes=tuple(payload.get("source_doc_hashes", [])),
        entries=tuple(
            HydrateManifestEntry(
                row_idx=int(entry.get("row_idx", 0)),
                stable_key=str(entry.get("stable_key", "")),
                byte_hint=int(entry.get("byte_hint", 0)),
                candidate_id=str(entry.get("candidate_id", "")),
                bucket=str(entry.get("bucket", "semantic_context")),
                importance_score=float(entry.get("importance_score", 0.0)),
                locator=locator_from_dict(dict(entry.get("locator", {}))),
            )
            for entry in payload.get("entries", [])
        ),
        canonicalizer_version=str(payload.get("canonicalizer_version", "")),
        extractor_version=str(payload.get("extractor_version", "")),
        schema_version=str(payload.get("schema_version", "")),
        created_at_ns=int(payload.get("created_at_ns", 0)),
    )


def evidence_item_to_dict(item: EvidenceItem) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "bucket": item.bucket,
        "locator": None if item.locator is None else locator_to_dict(item.locator),
        "rendered_text": item.rendered_text,
        "source_name": item.source_name,
        "rank": item.rank,
        "score": item.score,
        "metadata": dict(item.metadata),
    }


def evidence_item_from_dict(payload: dict[str, Any]) -> EvidenceItem:
    locator_payload = payload.get("locator")
    locator = None if locator_payload is None else locator_from_dict(dict(locator_payload))
    return EvidenceItem(
        item_id=str(payload.get("item_id", "")),
        bucket=str(payload.get("bucket", "")),
        locator=locator,
        rendered_text=str(payload.get("rendered_text", "")),
        source_name=str(payload.get("source_name", "")),
        rank=int(payload.get("rank", 0)),
        score=float(payload.get("score", 0.0)),
        metadata=dict(payload.get("metadata", {})),
    )


def evidence_pack_to_dict(pack: CanonicalEvidencePack) -> dict[str, Any]:
    return {
        "pack_id": pack.pack_id,
        "task_id": pack.task_id,
        "source_doc_hashes": list(pack.source_doc_hashes),
        "hard_facts": [evidence_item_to_dict(item) for item in pack.hard_facts],
        "structured_evidence": [evidence_item_to_dict(item) for item in pack.structured_evidence],
        "semantic_contexts": [evidence_item_to_dict(item) for item in pack.semantic_contexts],
        "lexical_hints": [evidence_item_to_dict(item) for item in pack.lexical_hints],
        "conflicts": [evidence_item_to_dict(item) for item in pack.conflicts],
        "budget_meta": dict(pack.budget_meta),
        "pack_hash": pack.pack_hash,
        "schema_version": pack.schema_version,
    }


def evidence_pack_from_dict(payload: dict[str, Any]) -> CanonicalEvidencePack:
    return CanonicalEvidencePack(
        pack_id=str(payload.get("pack_id", "")),
        task_id=str(payload.get("task_id", "")),
        source_doc_hashes=tuple(payload.get("source_doc_hashes", [])),
        hard_facts=tuple(evidence_item_from_dict(item) for item in payload.get("hard_facts", [])),
        structured_evidence=tuple(
            evidence_item_from_dict(item) for item in payload.get("structured_evidence", [])
        ),
        semantic_contexts=tuple(
            evidence_item_from_dict(item) for item in payload.get("semantic_contexts", [])
        ),
        lexical_hints=tuple(
            evidence_item_from_dict(item) for item in payload.get("lexical_hints", [])
        ),
        conflicts=tuple(evidence_item_from_dict(item) for item in payload.get("conflicts", [])),
        budget_meta=dict(payload.get("budget_meta", {})),
        pack_hash=str(payload.get("pack_hash", "")),
        schema_version=str(payload.get("schema_version", "")),
    )


@dataclass
class HydrationRegistry:
    text_spans: dict[str, str] = field(default_factory=dict)
    table_cells: dict[str, str] = field(default_factory=dict)
    fragments: dict[str, str] = field(default_factory=dict)

    def register(self, locator: SourceLocator, rendered_text: str) -> None:
        if isinstance(locator, TextSpanLocator):
            self.text_spans[self._stable_key(locator)] = rendered_text
        elif isinstance(locator, TableCellLocator):
            self.table_cells[self._stable_key(locator)] = rendered_text
        elif isinstance(locator, FragmentLocator):
            self.fragments[self._stable_key(locator)] = rendered_text
        else:
            raise TypeError(f"unsupported locator type: {type(locator)!r}")

    def hydrate_locator(self, locator: SourceLocator) -> str:
        key = self._stable_key(locator)
        if isinstance(locator, TextSpanLocator):
            return self.text_spans[key]
        if isinstance(locator, TableCellLocator):
            return self.table_cells[key]
        if isinstance(locator, FragmentLocator):
            return self.fragments[key]
        raise TypeError(f"unsupported locator type: {type(locator)!r}")

    @staticmethod
    def _stable_key(locator: SourceLocator) -> str:
        if isinstance(locator, TextSpanLocator):
            return (
                f"text_span:{locator.source_doc_hash}:{locator.canonical_text_id}:"
                f"{locator.start_char}:{locator.end_char}:{locator.extractor_version}"
            )
        if isinstance(locator, TableCellLocator):
            return (
                f"table_cell:{locator.source_doc_hash}:{locator.table_id}:{locator.sheet_name}:"
                f"{locator.row_idx}:{locator.col_idx}:{locator.extractor_version}"
            )
        if isinstance(locator, FragmentLocator):
            return (
                f"fragment:{locator.source_doc_hash}:{locator.fragment_id}:"
                f"{locator.extractor_version}:{locator.page_no}"
            )
        raise TypeError(f"unsupported locator type: {type(locator)!r}")


def hydrate_manifest_entries(
    manifest: HydrateManifest,
    registry: HydrationRegistry,
    *,
    selected_keys: set[str] | None = None,
) -> list[str]:
    rendered: list[str] = []
    for entry in manifest.entries:
        if selected_keys is not None and entry.stable_key not in selected_keys:
            continue
        rendered.append(registry.hydrate_locator(entry.locator))
    return rendered


@dataclass(frozen=True)
class RoleHydratedSlice:
    role: str
    selected_stable_keys: tuple[str, ...]
    hydrated_text: str
    hydrated_bytes: int
    item_count: int
    table_text: str = ""
    table_bytes: int = 0
    table_item_count: int = 0
    artifact_text: str = ""
    artifact_bytes: int = 0
    artifact_item_count: int = 0
    memory_text: str = ""
    memory_bytes: int = 0
    memory_item_count: int = 0


def build_hydration_registry_from_evidence_pack(pack: CanonicalEvidencePack) -> HydrationRegistry:
    registry = HydrationRegistry()
    for item in (
        *pack.hard_facts,
        *pack.structured_evidence,
        *pack.semantic_contexts,
        *pack.lexical_hints,
        *pack.conflicts,
    ):
        if item.locator is None:
            continue
        registry.register(item.locator, item.rendered_text)
    return registry


def role_hydrated_slice(
    *,
    role: str,
    manifest: HydrateManifest,
    registry: HydrationRegistry,
    selected_keys: tuple[str, ...],
) -> RoleHydratedSlice:
    rendered = hydrate_manifest_entries(
        manifest,
        registry,
        selected_keys=set(selected_keys),
    )
    hydrated_text = "\n".join(item for item in rendered if item)
    return RoleHydratedSlice(
        role=role,
        selected_stable_keys=tuple(selected_keys),
        hydrated_text=hydrated_text,
        hydrated_bytes=len(hydrated_text.encode("utf-8")),
        item_count=len(rendered),
    )


@dataclass(frozen=True)
class EvidenceCandidate:
    item_id: str
    bucket: str
    locator: SourceLocator | None
    rendered_text: str
    source_name: str
    rank: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeterministicFanInBuilder:
    rrf_k: int = 60

    def build(
        self,
        *,
        pack_id: str,
        task_id: str,
        hard_facts: list[EvidenceCandidate] | None = None,
        structured_evidence: list[EvidenceCandidate] | None = None,
        text_candidates: list[EvidenceCandidate] | None = None,
        hint_candidates: list[EvidenceCandidate] | None = None,
        conflicts: list[EvidenceCandidate] | None = None,
        budget_meta: dict[str, Any] | None = None,
    ) -> CanonicalEvidencePack:
        hard_fact_items = self._dedupe_stable(hard_facts or [])
        structured_items = self._dedupe_stable(structured_evidence or [])
        semantic_items = self._rrf_rank(text_candidates or [])
        hint_items = self._rrf_rank(hint_candidates or [])
        conflict_items = self._dedupe_stable(conflicts or [])
        doc_hashes = {
            locator.source_doc_hash
            for group in [
                hard_fact_items,
                structured_items,
                semantic_items,
                hint_items,
                conflict_items,
            ]
            for item in group
            if item.locator is not None
            for locator in [item.locator]
        }
        return CanonicalEvidencePack(
            pack_id=pack_id,
            task_id=task_id,
            source_doc_hashes=tuple(sorted(doc_hashes)),
            hard_facts=tuple(hard_fact_items),
            structured_evidence=tuple(structured_items),
            semantic_contexts=tuple(semantic_items),
            lexical_hints=tuple(hint_items),
            conflicts=tuple(conflict_items),
            budget_meta=dict(sorted((budget_meta or {}).items())),
        )

    def _dedupe_stable(self, candidates: list[EvidenceCandidate]) -> list[EvidenceItem]:
        best: dict[str, EvidenceCandidate] = {}
        for candidate in sorted(candidates, key=lambda item: (item.item_id, item.rank, item.source_name)):
            best.setdefault(candidate.item_id, candidate)
        return [
            EvidenceItem(
                item_id=candidate.item_id,
                bucket=candidate.bucket,
                locator=candidate.locator,
                rendered_text=candidate.rendered_text,
                source_name=candidate.source_name,
                rank=candidate.rank,
                metadata=dict(sorted(candidate.metadata.items())),
            )
            for candidate in sorted(best.values(), key=lambda item: (item.item_id, item.rank, item.source_name))
        ]

    def _rrf_rank(self, candidates: list[EvidenceCandidate]) -> list[EvidenceItem]:
        aggregate: dict[str, tuple[float, EvidenceCandidate]] = {}
        for candidate in candidates:
            score = 1.0 / (self.rrf_k + max(candidate.rank, 1))
            if candidate.item_id not in aggregate:
                aggregate[candidate.item_id] = (score, candidate)
                continue
            current_score, current_candidate = aggregate[candidate.item_id]
            merged_score = current_score + score
            if (candidate.rank, candidate.source_name, candidate.item_id) < (
                current_candidate.rank,
                current_candidate.source_name,
                current_candidate.item_id,
            ):
                aggregate[candidate.item_id] = (merged_score, candidate)
            else:
                aggregate[candidate.item_id] = (merged_score, current_candidate)
        ranked = sorted(
            aggregate.items(),
            key=lambda item: (-item[1][0], item[1][1].item_id, item[1][1].source_name),
        )
        return [
            EvidenceItem(
                item_id=candidate.item_id,
                bucket=candidate.bucket,
                locator=candidate.locator,
                rendered_text=candidate.rendered_text,
                source_name=candidate.source_name,
                rank=candidate.rank,
                score=score,
                metadata=dict(sorted(candidate.metadata.items())),
            )
            for candidate_id, (score, candidate) in ranked
        ]
