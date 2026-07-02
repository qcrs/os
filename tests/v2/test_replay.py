from __future__ import annotations

from pathlib import Path

from v2.contracts import PlannerHandoff
from v2.refs import CanonicalEvidencePack, EvidenceItem, HydrateManifest, HydrateManifestEntry, TextSpanLocator
from v2.contracts import CanonicalTaskSpec
from v2.runtime.replay import (
    ReplayAdmissibilityGate,
    ReplayCandidate,
    ReplayPolicy,
    evidence_pack_replay_hash,
    hydrate_manifest_replay_hash,
    planner_handoff_replay_hash,
    replay_exact_key,
    validated_replay_contract_compatible,
)
from v2.benchmark.replay_negative_audit import run_replay_negative_audit
from v2.contracts import CompilerStatus, ReplayClass, RuntimeCompatibilitySignature, TaskCompilerResult


def _spec(*, intent_op: str, metric: str, required_outputs: tuple[str, ...]) -> CanonicalTaskSpec:
    return CanonicalTaskSpec(
        task_family="continuous_long_doc_table_analysis",
        intent_op=intent_op,
        required_outputs=required_outputs,
        required_tools=("table_retriever",),
        arguments={
            "dataset_id": "acme_ops_2026",
            "document_path": "v2/benchmark/samples/continuous_task_families/long_doc_table/acme_ops_report_2026.md",
            "metric": metric,
            "quarters": ["2026Q1", "2026Q2", "2026Q3"],
        },
    )


def test_validated_replay_contract_allows_same_intent_with_different_argument_values() -> None:
    current = _spec(
        intent_op="extract_metric_series_generic",
        metric="revenue_musd",
        required_outputs=("metric_series_ref", "metric_name", "value_q1", "value_q2", "value_q3"),
    )
    candidate = _spec(
        intent_op="extract_metric_series_generic",
        metric="gross_margin_pct",
        required_outputs=("metric_series_ref", "metric_name", "value_q1", "value_q2", "value_q3"),
    )
    assert validated_replay_contract_compatible(current_spec=current, candidate_spec=candidate) is True


def test_validated_replay_contract_rejects_different_intent_even_with_same_surface_shape() -> None:
    current = _spec(
        intent_op="extract_metric_series_generic",
        metric="revenue_musd",
        required_outputs=("metric_series_ref", "metric_name", "value_q1", "value_q2", "value_q3"),
    )
    candidate = _spec(
        intent_op="extract_metric_series",
        metric="revenue_musd",
        required_outputs=("metric_series_ref", "metric_name", "value_q1", "value_q2", "value_q3"),
    )
    assert validated_replay_contract_compatible(current_spec=current, candidate_spec=candidate) is False


def test_replay_normalized_hashes_ignore_round_specific_ids() -> None:
    planner_a = PlannerHandoff(
        task_id="replay-longdoc-002",
        canonical_task_spec_hash="spec-a",
        retrieval_objective={"goal": "extract metric triplet", "candidate_keys": ["extract_metric_series::table_retriever"]},
        planner_plan_payload={"steps": [{"step_id": "retrieve"}, {"step_id": "execute"}]},
        planner_scope_payload={"source_doc_hashes": ["sha256:doc-1"]},
        summary_hint="metric summary ready",
    )
    planner_b = PlannerHandoff(
        task_id="replay-longdoc-005",
        canonical_task_spec_hash="spec-b",
        retrieval_objective=planner_a.retrieval_objective,
        planner_plan_payload=planner_a.planner_plan_payload,
        planner_scope_payload=planner_a.planner_scope_payload,
        summary_hint=planner_a.summary_hint,
    )
    locator = TextSpanLocator(
        source_doc_hash="sha256:doc-1",
        canonical_text_id="section-3",
        start_char=10,
        end_char=24,
        extractor_version="markdown-section-v1",
    )
    evidence_a = CanonicalEvidencePack(
        pack_id="pack-round-2",
        task_id="replay-longdoc-002",
        source_doc_hashes=("sha256:doc-1",),
        semantic_contexts=(
            EvidenceItem(
                item_id="ctx-section-3",
                bucket="semantic_context",
                locator=locator,
                rendered_text="Metric Table | 2026Q1 | 120 |",
                source_name="semantic",
                rank=1,
                score=0.7,
                metadata={"score": 0.7},
            ),
        ),
    )
    evidence_b = CanonicalEvidencePack(
        pack_id="pack-round-5",
        task_id="replay-longdoc-005",
        source_doc_hashes=evidence_a.source_doc_hashes,
        semantic_contexts=evidence_a.semantic_contexts,
    )
    hydrate_a = HydrateManifest(
        manifest_id="manifest-round-2",
        source_doc_hashes=("sha256:doc-1",),
        entries=(HydrateManifestEntry(row_idx=0, locator=locator, stable_key="text:doc-1:section-3", byte_hint=32),),
        canonicalizer_version="canon-v1",
        extractor_version="retriever-fanout-v1",
        created_at_ns=0,
    )
    hydrate_b = HydrateManifest(
        manifest_id="manifest-round-5",
        source_doc_hashes=hydrate_a.source_doc_hashes,
        entries=hydrate_a.entries,
        canonicalizer_version=hydrate_a.canonicalizer_version,
        extractor_version=hydrate_a.extractor_version,
        created_at_ns=123456789,
    )

    assert planner_handoff_replay_hash(planner_a) == planner_handoff_replay_hash(planner_b)
    assert evidence_pack_replay_hash(evidence_a) == evidence_pack_replay_hash(evidence_b)
    assert hydrate_manifest_replay_hash(hydrate_a) == hydrate_manifest_replay_hash(hydrate_b)


def test_replay_normalized_hashes_change_when_core_inputs_change() -> None:
    planner_a = PlannerHandoff(
        task_id="task-a",
        canonical_task_spec_hash="spec-a",
        retrieval_objective={"goal": "extract revenue"},
        planner_plan_payload={"steps": [{"step_id": "retrieve"}]},
        planner_scope_payload={"source_doc_hashes": ["sha256:doc-1"]},
        summary_hint="metric summary ready",
    )
    planner_b = PlannerHandoff(
        task_id="task-b",
        canonical_task_spec_hash="spec-a",
        retrieval_objective={"goal": "extract gross margin"},
        planner_plan_payload=planner_a.planner_plan_payload,
        planner_scope_payload=planner_a.planner_scope_payload,
        summary_hint=planner_a.summary_hint,
    )

    assert planner_handoff_replay_hash(planner_a) != planner_handoff_replay_hash(planner_b)


def test_validated_replay_gate_rejects_unverified_candidate_output() -> None:
    spec = _spec(
        intent_op="extract_metric_series_generic",
        metric="revenue_musd",
        required_outputs=("metric_series_ref", "metric_name", "value_q1", "value_q2", "value_q3"),
    )
    runtime_signature = RuntimeCompatibilitySignature(
        os_digest="os:openeuler",
        python_digest="python:3.11",
        dependency_digest="deps:v1",
        tool_registry_digest="tools:v1",
        prompt_bundle_digest="prompts:v1",
        extractor_bundle_digest="extractors:v1",
    )
    output_contract_version = "statebus.output.metric_series.v1"
    input_artifact_hashes = ("sha256:input-a",)
    candidate = ReplayCandidate(
        candidate_id="memory:unverified",
        canonical_task_spec=spec,
        input_artifact_hashes=input_artifact_hashes,
        runtime_signature=runtime_signature,
        output_contract_version=output_contract_version,
        verified_output=False,
        code_template_version="codeact-metric-series-v1",
        extractor_version="long-doc-table-v1",
    )
    assert candidate.exact_key == replay_exact_key(
        canonical_task_spec=spec,
        input_artifact_hashes=input_artifact_hashes,
        runtime_signature=runtime_signature,
        code_template_version=candidate.code_template_version,
        extractor_version=candidate.extractor_version,
        output_contract_version=output_contract_version,
    )

    decision = ReplayAdmissibilityGate().decide(
        compiler_result=TaskCompilerResult(status=CompilerStatus.COMPILED, canonical_task_spec=spec),
        policy=ReplayPolicy(allow_assist=True, allow_validated_replay=True, allow_exact_replay=True),
        candidate=candidate,
        runtime_signature=runtime_signature,
        input_artifact_hashes=("sha256:input-b",),
        output_contract_version=output_contract_version,
    )

    assert decision.replay_class == ReplayClass.ASSIST
    assert decision.skipped_step_count == 0


def test_replay_negative_audit_report_covers_downgrade_and_invalidation_cases(tmp_path: Path) -> None:
    report = run_replay_negative_audit(runtime_root=tmp_path / "runtime")

    assert report["audit_pass"] is True
    assert report["case_count"] == 7
    cases = {str(case["case_id"]): case for case in report["cases"]}
    assert cases["exact_control"]["observed_replay_class"] == "exact_replay"
    assert cases["input_hash_changed"]["observed_replay_class"] == "validated_replay"
    assert cases["runtime_signature_degraded"]["compatibility_verdict"] == "degraded"
    assert cases["runtime_signature_incompatible_tool"]["observed_replay_class"] == "assist"
    assert cases["output_contract_changed"]["observed_replay_class"] == "assist"
    assert cases["intent_changed"]["observed_replay_class"] == "assist"
    assert cases["unverified_output"]["observed_replay_class"] == "assist"
    assert Path(str(report["report_path"])).exists()
    assert Path(str(report["markdown_report_path"])).exists()
