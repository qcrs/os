from __future__ import annotations

from v2.contracts import CanonicalTaskSpec
from v2.retrieval import (
    RetrieverFanoutPipeline,
    RetrieverKind,
    apply_semantic_state_selection,
)


def test_retrieval_pipeline_builds_bundle_with_logs_manifest_and_embedding() -> None:
    bundle = RetrieverFanoutPipeline().run(
        task_id="task-1",
        spec=CanonicalTaskSpec(
            task_family="financial_report_analysis",
            intent_op="compare_metric",
            required_outputs=("summary_text",),
            arguments={"ticker": "ACME", "quarter": "2026Q1", "metric": "revenue"},
        ),
    )
    assert bundle.task_id == "task-1"
    assert len(bundle.outputs) == 3
    assert bundle.evidence_pack.pack_id == "pack-task-1"
    assert bundle.hydrate_manifest.manifest_id == "manifest-task-1"
    assert bundle.query_embedding.dims == 16
    assert bundle.memory_query_embedding is bundle.query_embedding
    assert bundle.semantic_state_manifest is not None
    semantic_output = next(
        output
        for output in bundle.outputs
        if output.retriever_kind == RetrieverKind.SEMANTIC_CHUNK
    )
    assert [entry.row_idx for entry in bundle.semantic_state_manifest.entries] == list(
        range(1, len(bundle.semantic_candidate_embeddings) + 1)
    )
    assert [entry.candidate_id for entry in bundle.semantic_state_manifest.entries] == [
        candidate_id for candidate_id, _embedding in bundle.semantic_candidate_embeddings
    ]
    assert len(bundle.semantic_candidate_embeddings) == semantic_output.log_entry.candidate_count
    assert len(bundle.semantic_candidate_embeddings) > len(bundle.evidence_pack.semantic_contexts)
    assert bundle.candidate_pool.pool_hash
    assert bundle.rerank_result.rerank_hash
    assert bundle.pruning_profile.profile_hash
    assert len(bundle.candidate_pool.candidates) >= len(bundle.rerank_result.selected_candidate_ids)
    assert any(item.selected for item in bundle.rerank_result.items)
    assert bundle.selected_evidence_bytes > 0
    assert bundle.full_corpus_bytes >= bundle.selected_evidence_bytes
    assert bundle.pruning_profile.pruning_gain_bytes >= 0
    assert any(bucket.selected_count >= 1 for bucket in bundle.pruning_profile.bucket_stats)
    assert bundle.log_payload()["candidate_pool_hash"] == bundle.candidate_pool.pool_hash
    assert bundle.log_payload()["rerank_result_hash"] == bundle.rerank_result.rerank_hash
    assert bundle.log_payload()["pruning_profile_hash"] == bundle.pruning_profile.profile_hash
    assert bundle.log_payload()["evidence_pack_hash"] == bundle.evidence_pack.pack_hash
    first_output_payload = bundle.outputs[0].log_payload()
    assert "log_entry" not in first_output_payload
    assert first_output_payload["candidate_ids_hash"]
    assert first_output_payload["candidate_id_sample_count"] == len(first_output_payload["candidate_id_sample"])
    assert first_output_payload["selected_count"] >= 0
    assert isinstance(first_output_payload["diagnostics"], dict)
    assert first_output_payload["selected_ids_hash"]
    assert "selected_id_sample_count" not in first_output_payload
    assert "selected_id_sample" not in first_output_payload
    assert first_output_payload["selected_candidate_audit_hash"]
    assert first_output_payload["selected_candidate_audit_sample_count"] == len(
        first_output_payload["selected_candidate_audit_sample"]
    )
    assert "candidate_ids" not in first_output_payload
    assert "selected_candidate_audit" not in first_output_payload


def test_semantic_consumer_selection_hydrates_a_candidate_outside_producer_top_k() -> None:
    bundle = RetrieverFanoutPipeline.with_embedding_mode(
        "deterministic",
        top_k=1,
    ).run(
        task_id="consumer-authoritative-selection",
        spec=CanonicalTaskSpec(
            task_family="financial_report_analysis",
            intent_op="compare_metric",
            required_outputs=("summary_text",),
            arguments={"ticker": "ACME", "quarter": "2026Q1", "metric": "revenue"},
        ),
    )
    producer_selected_id = bundle.evidence_pack.semantic_contexts[0].item_id
    consumer_selected_id = next(
        candidate_id
        for candidate_id, _embedding in bundle.semantic_candidate_embeddings
        if candidate_id != producer_selected_id
    )

    selected = apply_semantic_state_selection(
        bundle,
        selected_candidate_ids=(consumer_selected_id,),
        selected_scores=(0.999,),
        consumer_pid=43210,
    )

    assert [item.item_id for item in selected.evidence_pack.semantic_contexts] == [
        consumer_selected_id
    ]
    assert selected.evidence_pack.semantic_contexts[0].rendered_text
    assert producer_selected_id not in selected.rerank_result.selected_candidate_ids
    assert consumer_selected_id in selected.rerank_result.selected_candidate_ids
    assert selected.evidence_pack.budget_meta["semantic_selection_source"] == (
        "cross_process_dense_state"
    )
    assert selected.pruning_profile.raw_evidence_bytes_seen_by_llm == (
        selected.selected_evidence_bytes
    )
