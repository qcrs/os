from __future__ import annotations

from pathlib import Path

import pytest

from statebus.benchmark.continuous_task_family import load_continuous_task_family
from statebus.benchmark.kv_prefix_schedule import build_kv_prefix_schedule_plan
from statebus.runtime import (
    EngineLocalPrefixRegistry,
    PrefixReuseScheduleHint,
    build_corpus_prefix_hash,
    build_evidence_prefix_hash,
    compile_prefix_layout,
    order_prefix_schedule_hints_by_task_ids,
)


def test_corpus_and_evidence_prefix_hashes_have_different_granularity() -> None:
    corpus_a = build_corpus_prefix_hash(
        source_doc_hashes=("sha256:doc-a",),
        evidence_pack_hash="pack-a",
        hydrate_manifest_hash="manifest-a",
    )
    corpus_b = build_corpus_prefix_hash(
        source_doc_hashes=("sha256:doc-a",),
        evidence_pack_hash="pack-b",
        hydrate_manifest_hash="manifest-b",
    )
    evidence_a = build_evidence_prefix_hash(
        corpus_prefix_hash=corpus_a,
        evidence_pack_hash="pack-a",
        hydrate_manifest_hash="manifest-a",
    )
    evidence_b = build_evidence_prefix_hash(
        corpus_prefix_hash=corpus_a,
        evidence_pack_hash="pack-b",
        hydrate_manifest_hash="manifest-b",
    )

    assert corpus_a == corpus_b
    assert evidence_a != evidence_b


def test_engine_local_prefix_registry_updates_lease_metadata_on_hit() -> None:
    registry = EngineLocalPrefixRegistry(
        engine_id="local-vllm",
        model_id="qwen3-8b",
        tokenizer_id="qwen3",
    )
    first = registry.ensure_handle(
        session_id="session-a",
        prefix_hash="prefix-a",
        prefix_token_count=16,
        observed_ns=100,
        metadata={"source": "first"},
    )
    second = registry.ensure_handle(
        session_id="session-a",
        prefix_hash="prefix-a",
        prefix_token_count=32,
        expires_at_ns=500,
        observed_ns=200,
        estimated_resident_until_ns=450,
        eviction_risk="low",
        schedule_priority=0.9,
        metadata={"probe": "hit"},
    )

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.handle.cache_hit_count == 1
    assert second.handle.prefix_token_count == 32
    assert second.handle.expires_at_ns == 500
    assert second.handle.last_observed_query_ns == 200
    assert second.handle.last_observed_hit_ns == 200
    assert second.handle.estimated_resident_until_ns == 450
    assert second.handle.eviction_risk == "low"
    assert second.handle.schedule_priority == 0.9
    assert second.handle.metadata == {"source": "first", "probe": "hit"}


def test_prefix_layout_compiler_deduplicates_shared_evidence_from_suffix() -> None:
    shared_prefix = "Metric row: revenue_musd 2026Q1=122.4\nMetric row: gross_margin_pct 2026Q1=41.2"
    compiled = compile_prefix_layout(
        role_label="retriever",
        instruction="Return JSON.",
        payload_tag="sb-retriever-v1",
        payload={"q": "revenue", "e": shared_prefix},
        text_sections=(("Hydrated Evidence", shared_prefix), ("Query", "revenue")),
        evidence_blocks=(shared_prefix,),
        handoff_mode="structured_collaboration",
        prefix_alignment_mode="shared_evidence_prefix",
        shared_prefix_text=shared_prefix,
    )

    assert compiled.prompt.count(shared_prefix) == 1
    assert "<statebus-shared-prefix-v1>" in compiled.prompt
    assert compiled.layout_plan.shared_prefix_enabled is True
    assert compiled.layout_plan.removed_payload_evidence is True
    assert compiled.layout_plan.removed_text_section_count == 1
    assert compiled.layout_plan.removed_evidence_block_count == 1
    assert "e" not in compiled.layout_plan.suffix_payload_keys
    assert "sp" in compiled.layout_plan.suffix_payload_keys
    assert compiled.layout_plan.shared_prefix_bytes == len(shared_prefix.encode("utf-8"))


def test_manifest_ordering_applies_to_prefix_schedule_hints() -> None:
    hints = (
        PrefixReuseScheduleHint(task_id="b", corpus_prefix_hash="corpus-b"),
        PrefixReuseScheduleHint(task_id="a", corpus_prefix_hash="corpus-a"),
    )

    ordered = order_prefix_schedule_hints_by_task_ids(hints, ("a", "b"))

    assert tuple(hint.task_id for hint in ordered) == ("a", "b")
    with pytest.raises(ValueError, match="omits task ids"):
        order_prefix_schedule_hints_by_task_ids(hints, ("a",))


def test_kv_prefix_reuse_family_builds_cache_friendly_and_hostile_schedule_plans() -> None:
    family = load_continuous_task_family(
        Path("statebus/benchmark/samples/continuous_task_families/kv_prefix_reuse")
    )

    friendly = build_kv_prefix_schedule_plan(family, mode="cache_friendly")
    hostile = build_kv_prefix_schedule_plan(family, mode="cache_hostile")

    assert friendly.task_ids == tuple(family.kv_prefix_probe["cache_friendly_order"])
    assert hostile.task_ids == tuple(family.kv_prefix_probe["cache_hostile_order"])
    assert friendly.max_contiguous_same_affinity_run == 5
    assert hostile.max_contiguous_same_affinity_run == 1
    assert friendly.adjacent_reuse_opportunity_count == 8
    assert hostile.adjacent_reuse_opportunity_count == 0
    assert friendly.affinity_switch_count == 1
    assert hostile.affinity_switch_count == 9
    assert friendly.claim_boundary.endswith("no_kv_tensor_export")
