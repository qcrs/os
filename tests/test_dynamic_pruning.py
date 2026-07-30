from __future__ import annotations

from statebus.contracts import CanonicalTaskSpec
from statebus.retrieval import RetrieverFanoutPipeline
from statebus.retrieval.pruning import DynamicPruningConfig, compute_dynamic_pruning_threshold


def test_dynamic_pruning_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv("STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED", "1")
    monkeypatch.setenv("STATEBUS_EVIDENCE_AVAILABLE_KV_CACHE_BYTES", "123456")
    monkeypatch.setenv("STATEBUS_EVIDENCE_KV_BYTES_PER_TOKEN", "512")
    monkeypatch.setenv("STATEBUS_EVIDENCE_BASE_IMPORTANCE_THRESHOLD", "0.7")
    monkeypatch.setenv("STATEBUS_EVIDENCE_CAPACITY_BUFFER", "0.15")
    monkeypatch.setenv("STATEBUS_EVIDENCE_MIN_KEEP_SEMANTIC_CONTEXTS", "2")
    monkeypatch.setenv("STATEBUS_EVIDENCE_MIN_KEEP_LEXICAL_HINTS", "1")

    config = DynamicPruningConfig.from_env()

    assert config.enabled is True
    assert config.available_kv_cache_bytes == 123456
    assert config.kv_bytes_per_token == 512
    assert config.base_threshold == 0.7
    assert config.capacity_buffer == 0.15
    assert config.min_keep_semantic_contexts == 2
    assert config.min_keep_lexical_hints == 1


def test_compute_dynamic_pruning_threshold_increases_under_tight_capacity() -> None:
    assert compute_dynamic_pruning_threshold(
        available_kv_cache_bytes=8 * 1024**3,
        target_sequence_len=2048,
        kv_bytes_per_token=256,
        base_threshold=0.6,
    ) == 0.6
    assert compute_dynamic_pruning_threshold(
        available_kv_cache_bytes=700_000,
        target_sequence_len=2048,
        kv_bytes_per_token=256,
        base_threshold=0.6,
    ) == 0.7
    assert compute_dynamic_pruning_threshold(
        available_kv_cache_bytes=470_000,
        target_sequence_len=2048,
        kv_bytes_per_token=256,
        base_threshold=0.6,
    ) == 0.8
    assert compute_dynamic_pruning_threshold(
        available_kv_cache_bytes=128_000,
        target_sequence_len=2048,
        kv_bytes_per_token=256,
        base_threshold=0.6,
    ) == 0.9


def test_retrieval_pipeline_dynamic_pruning_preserves_baseline_when_capacity_has_headroom() -> None:
    baseline = RetrieverFanoutPipeline.with_embedding_mode(
        "deterministic",
        top_k=3,
    )
    baseline_bundle = baseline.run(
        task_id="task-dynamic-pruning-baseline",
        spec=CanonicalTaskSpec(
            task_family="financial_report_analysis",
            intent_op="compare_metric",
            required_outputs=("summary_text",),
            arguments={"ticker": "ACME", "quarter": "2026Q1", "metric": "revenue"},
        ),
    )

    pipeline = RetrieverFanoutPipeline.with_embedding_mode(
        "deterministic",
        top_k=3,
    )
    pipeline.dynamic_pruning_config = DynamicPruningConfig(
        enabled=True,
        available_kv_cache_bytes=8 * 1024**3,
        kv_bytes_per_token=256,
        base_threshold=0.6,
        capacity_buffer=0.2,
        min_keep_semantic_contexts=1,
        min_keep_lexical_hints=0,
    )
    bundle = pipeline.run(
        task_id="task-dynamic-pruning",
        spec=CanonicalTaskSpec(
            task_family="financial_report_analysis",
            intent_op="compare_metric",
            required_outputs=("summary_text",),
            arguments={"ticker": "ACME", "quarter": "2026Q1", "metric": "revenue"},
        ),
    )

    assert bundle.pruning_profile.dynamic_pruning_enabled is True
    assert bundle.pruning_profile.importance_threshold == 0.6
    assert bundle.pruning_profile.budget_decision == "capacity_headroom"
    assert bundle.pruning_profile.selected_candidate_ids == baseline_bundle.pruning_profile.selected_candidate_ids
    assert [item.item_id for item in bundle.evidence_pack.hard_facts] == [
        item.item_id for item in baseline_bundle.evidence_pack.hard_facts
    ]
    assert [item.item_id for item in bundle.evidence_pack.semantic_contexts] == [
        item.item_id for item in baseline_bundle.evidence_pack.semantic_contexts
    ]
    assert [item.item_id for item in bundle.evidence_pack.lexical_hints] == [
        item.item_id for item in baseline_bundle.evidence_pack.lexical_hints
    ]
    assert not any(
        hint.pruning_class == "dynamic_budget_drop"
        for hint in bundle.pruning_profile.pruning_hints
    )


def test_retrieval_pipeline_dynamic_pruning_preserves_hard_facts_and_drops_low_value_context() -> None:
    pipeline = RetrieverFanoutPipeline.with_embedding_mode(
        "deterministic",
        top_k=3,
    )
    pipeline.dynamic_pruning_config = DynamicPruningConfig(
        enabled=True,
        available_kv_cache_bytes=20_000,
        kv_bytes_per_token=256,
        base_threshold=0.6,
        capacity_buffer=0.2,
        min_keep_semantic_contexts=1,
        min_keep_lexical_hints=0,
    )
    bundle = pipeline.run(
        task_id="task-dynamic-pruning",
        spec=CanonicalTaskSpec(
            task_family="financial_report_analysis",
            intent_op="compare_metric",
            required_outputs=("summary_text",),
            arguments={"ticker": "ACME", "quarter": "2026Q1", "metric": "revenue"},
        ),
    )

    assert bundle.pruning_profile.dynamic_pruning_enabled is True
    assert bundle.pruning_profile.importance_threshold == 0.9
    assert bundle.pruning_profile.base_importance_threshold == 0.6
    assert bundle.pruning_profile.budget_decision == "capacity_critical"
    assert bundle.evidence_pack.hard_facts
    assert len(bundle.evidence_pack.semantic_contexts) == 1
    assert len(bundle.evidence_pack.lexical_hints) == 0
    assert any(
        hint.pruning_class == "dynamic_budget_drop"
        for hint in bundle.pruning_profile.pruning_hints
    )
    assert any(
        hint.reason == "candidate_pruned_by_dynamic_budget"
        for hint in bundle.pruning_profile.pruning_hints
    )
