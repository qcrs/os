from __future__ import annotations

from statebus.provenance import (
    DeterministicFanInBuilder,
    EvidenceCandidate,
    HydrationRegistry,
    hydrate_manifest_entries,
    manifest_from_dict,
    manifest_to_dict,
)
from statebus.refs import HydrateManifest, HydrateManifestEntry, TableCellLocator, TextSpanLocator


def test_hydrate_manifest_round_trip_preserves_locator_types() -> None:
    manifest = HydrateManifest(
        manifest_id="manifest-1",
        source_doc_hashes=("sha256:doc1",),
        entries=(
            HydrateManifestEntry(
                row_idx=0,
                stable_key="text-span-1",
                byte_hint=32,
                locator=TextSpanLocator(
                    source_doc_hash="sha256:doc1",
                    canonical_text_id="chunk-1",
                    start_char=10,
                    end_char=40,
                    extractor_version="chunker-v1",
                ),
            ),
        ),
        canonicalizer_version="canon-v1",
        extractor_version="chunker-v1",
        created_at_ns=1234,
    )
    parsed = manifest_from_dict(manifest_to_dict(manifest))
    assert parsed.entries[0].locator.locator_type == "text_span"
    assert parsed.manifest_hash == manifest.manifest_hash


def test_hydration_registry_renders_selected_entries_only() -> None:
    locator = TextSpanLocator(
        source_doc_hash="sha256:doc1",
        canonical_text_id="chunk-1",
        start_char=10,
        end_char=40,
        extractor_version="chunker-v1",
    )
    registry = HydrationRegistry()
    registry.register(locator, "Revenue increased 12 percent year over year.")
    manifest = HydrateManifest(
        manifest_id="manifest-1",
        source_doc_hashes=("sha256:doc1",),
        entries=(
            HydrateManifestEntry(
                row_idx=0,
                stable_key="text-selected",
                locator=locator,
            ),
        ),
        canonicalizer_version="canon-v1",
        extractor_version="chunker-v1",
    )
    rendered = hydrate_manifest_entries(manifest, registry, selected_keys={"text-selected"})
    assert rendered == ["Revenue increased 12 percent year over year."]


def test_deterministic_fan_in_rrf_and_bucket_separation_are_stable() -> None:
    builder = DeterministicFanInBuilder(rrf_k=60)
    pack = builder.build(
        pack_id="pack-1",
        task_id="task-1",
        hard_facts=[
            EvidenceCandidate(
                item_id="fact-1",
                bucket="hard_fact",
                locator=TableCellLocator(
                    source_doc_hash="sha256:doc1",
                    table_id="tbl-1",
                    sheet_name="income",
                    row_idx=1,
                    col_idx=2,
                    extractor_version="table-v1",
                ),
                rendered_text="Revenue = 120",
                source_name="table",
                rank=1,
            )
        ],
        text_candidates=[
            EvidenceCandidate(
                item_id="ctx-1",
                bucket="semantic_context",
                locator=TextSpanLocator(
                    source_doc_hash="sha256:doc1",
                    canonical_text_id="chunk-1",
                    start_char=0,
                    end_char=20,
                    extractor_version="chunker-v1",
                ),
                rendered_text="Demand improved in APAC.",
                source_name="semantic",
                rank=1,
            ),
            EvidenceCandidate(
                item_id="ctx-1",
                bucket="semantic_context",
                locator=TextSpanLocator(
                    source_doc_hash="sha256:doc1",
                    canonical_text_id="chunk-1",
                    start_char=0,
                    end_char=20,
                    extractor_version="chunker-v1",
                ),
                rendered_text="Demand improved in APAC.",
                source_name="lexical",
                rank=2,
            ),
        ],
        hint_candidates=[
            EvidenceCandidate(
                item_id="hint-1",
                bucket="lexical_hint",
                locator=None,
                rendered_text="Use table_analysis route.",
                source_name="lexical",
                rank=1,
            )
        ],
    )
    assert pack.hard_facts[0].rendered_text == "Revenue = 120"
    assert pack.semantic_contexts[0].item_id == "ctx-1"
    assert pack.lexical_hints[0].item_id == "hint-1"
    assert pack.source_doc_hashes == ("sha256:doc1",)

