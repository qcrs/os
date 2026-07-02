from __future__ import annotations

from v2.contracts import CanonicalTaskSpec
from v2.retrieval import RetrieverFanoutPipeline


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
