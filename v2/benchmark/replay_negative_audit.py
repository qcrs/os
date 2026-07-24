from __future__ import annotations

from pathlib import Path

from v2.benchmark.reporting import write_json_report, write_markdown_report
from v2.contracts import (
    CanonicalTaskSpec,
    CompilerStatus,
    CompatibilityVerdict,
    ReplayClass,
    RuntimeCompatibilitySignature,
    TaskCompilerResult,
)
from v2.runtime.replay import ReplayAdmissibilityGate, ReplayCandidate, ReplayPolicy, replay_exact_key


def _spec(*, intent_op: str = "extract_metric_series_generic") -> CanonicalTaskSpec:
    return CanonicalTaskSpec(
        task_family="continuous_long_doc_table_analysis",
        intent_op=intent_op,
        required_outputs=("metric_series_ref", "metric_name", "value_q1", "value_q2", "value_q3"),
        required_tools=("table_retriever",),
        arguments={
            "dataset_id": "acme_ops_2026",
            "document_path": "v2/benchmark/samples/continuous_task_families/long_doc_table/acme_ops_report_2026.md",
            "metric": "revenue_musd",
            "quarters": ["2026Q1", "2026Q2", "2026Q3"],
        },
    )


def _compiler_result(spec: CanonicalTaskSpec) -> TaskCompilerResult:
    return TaskCompilerResult(status=CompilerStatus.COMPILED, canonical_task_spec=spec)


def _signature(
    *,
    os_digest: str = "os:openeuler-24.03-lts-sp3",
    python_digest: str = "python:3.11.6",
    dependency_digest: str = "deps:v1",
    tool_registry_digest: str = "tools:v1",
    prompt_bundle_digest: str = "prompts:v1",
    extractor_bundle_digest: str = "extractors:v1",
) -> RuntimeCompatibilitySignature:
    return RuntimeCompatibilitySignature(
        os_digest=os_digest,
        python_digest=python_digest,
        dependency_digest=dependency_digest,
        tool_registry_digest=tool_registry_digest,
        prompt_bundle_digest=prompt_bundle_digest,
        extractor_bundle_digest=extractor_bundle_digest,
    )


def _candidate(
    *,
    spec: CanonicalTaskSpec,
    runtime_signature: RuntimeCompatibilitySignature,
    input_artifact_hashes: tuple[str, ...],
    output_contract_version: str,
    verified_output: bool = True,
) -> ReplayCandidate:
    return ReplayCandidate(
        candidate_id="memory:replay-longdoc-002",
        canonical_task_spec=spec,
        input_artifact_hashes=input_artifact_hashes,
        runtime_signature=runtime_signature,
        output_contract_version=output_contract_version,
        verified_output=verified_output,
        code_template_version="codeact-metric-series-v1",
        extractor_version="long-doc-table-v1",
    )


def _decision_payload(
    *,
    case_id: str,
    expected_outcome: str,
    decision,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "expected_outcome": expected_outcome,
        "observed_replay_class": decision.replay_class.value,
        "observed_reason": decision.reason,
        "compatibility_verdict": decision.compatibility_verdict.value,
        "skipped_step_count": decision.skipped_step_count,
        "degraded": decision.degraded,
    }


def _case_passed(payload: dict[str, object]) -> bool:
    case_id = str(payload["case_id"])
    replay_class = str(payload["observed_replay_class"])
    compatibility = str(payload["compatibility_verdict"])
    if case_id == "exact_control":
        return replay_class == ReplayClass.EXACT_REPLAY.value
    if case_id == "runtime_signature_degraded":
        return replay_class == ReplayClass.VALIDATED_REPLAY.value and compatibility == CompatibilityVerdict.DEGRADED.value
    if case_id == "input_hash_changed":
        return replay_class == ReplayClass.VALIDATED_REPLAY.value
    return replay_class in {ReplayClass.ASSIST.value, ReplayClass.DISALLOWED.value}


def _build_markdown(payload: dict[str, object]) -> str:
    lines = [
        f"# Replay Negative Audit: {payload['suite_id']}",
        "",
        f"- audit_pass: `{payload['audit_pass']}`",
        f"- case_count: `{payload['case_count']}`",
        "",
        "| case | expected | observed | reason | compatibility | skipped | pass |",
        "| --- | --- | --- | --- | --- | ---: | --- |",
    ]
    for case in payload["cases"]:
        case_payload = dict(case)
        lines.append(
            f"| {case_payload['case_id']} | {case_payload['expected_outcome']} | "
            f"{case_payload['observed_replay_class']} | {case_payload['observed_reason']} | "
            f"{case_payload['compatibility_verdict']} | {case_payload['skipped_step_count']} | "
            f"{case_payload['passed']} |"
        )
    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            "- Exact replay must fail closed when the exact key changes.",
            "- Validated replay may downgrade an exact miss only when the task contract, output contract, verified output, and non-incompatible runtime signature remain admissible.",
            "- Output contract mismatch, incompatible runtime/tool signature, incompatible intent, or unverified output must not produce exact or validated replay.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_replay_negative_audit(
    *,
    runtime_root: Path,
    suite_id: str = "statebus-v2-replay-negative-audit",
) -> dict[str, object]:
    report_root = runtime_root / "benchmark_reports"
    report_root.mkdir(parents=True, exist_ok=True)
    base_spec = _spec()
    base_signature = _signature()
    base_input_hashes = ("sha256:input-a",)
    base_output_contract = "statebus.output.metric_series.v1"
    candidate = _candidate(
        spec=base_spec,
        runtime_signature=base_signature,
        input_artifact_hashes=base_input_hashes,
        output_contract_version=base_output_contract,
    )
    assert candidate.exact_key == replay_exact_key(
        canonical_task_spec=base_spec,
        input_artifact_hashes=base_input_hashes,
        runtime_signature=base_signature,
        code_template_version=candidate.code_template_version,
        extractor_version=candidate.extractor_version,
        output_contract_version=base_output_contract,
    )
    gate = ReplayAdmissibilityGate()
    policy = ReplayPolicy(allow_assist=True, allow_validated_replay=True, allow_exact_replay=True)
    cases = [
        _decision_payload(
            case_id="exact_control",
            expected_outcome="exact replay allowed for identical key",
            decision=gate.decide(
                compiler_result=_compiler_result(base_spec),
                policy=policy,
                candidate=candidate,
                runtime_signature=base_signature,
                input_artifact_hashes=base_input_hashes,
                output_contract_version=base_output_contract,
            ),
        ),
        _decision_payload(
            case_id="input_hash_changed",
            expected_outcome="exact replay downgraded to validated replay",
            decision=gate.decide(
                compiler_result=_compiler_result(base_spec),
                policy=policy,
                candidate=candidate,
                runtime_signature=base_signature,
                input_artifact_hashes=("sha256:input-b",),
                output_contract_version=base_output_contract,
            ),
        ),
        _decision_payload(
            case_id="runtime_signature_degraded",
            expected_outcome="compatible-shape runtime drift downgraded to degraded validated replay",
            decision=gate.decide(
                compiler_result=_compiler_result(base_spec),
                policy=policy,
                candidate=candidate,
                runtime_signature=_signature(os_digest="os:openeuler-24.03-lts-sp3-patched"),
                input_artifact_hashes=base_input_hashes,
                output_contract_version=base_output_contract,
            ),
        ),
        _decision_payload(
            case_id="runtime_signature_incompatible_tool",
            expected_outcome="incompatible tool signature invalidates replay",
            decision=gate.decide(
                compiler_result=_compiler_result(base_spec),
                policy=policy,
                candidate=candidate,
                runtime_signature=_signature(tool_registry_digest="tools:v2"),
                input_artifact_hashes=base_input_hashes,
                output_contract_version=base_output_contract,
            ),
        ),
        _decision_payload(
            case_id="output_contract_changed",
            expected_outcome="output contract mismatch invalidates replay",
            decision=gate.decide(
                compiler_result=_compiler_result(base_spec),
                policy=policy,
                candidate=candidate,
                runtime_signature=base_signature,
                input_artifact_hashes=base_input_hashes,
                output_contract_version="statebus.output.metric_series.v2",
            ),
        ),
        _decision_payload(
            case_id="intent_changed",
            expected_outcome="intent mismatch invalidates replay",
            decision=gate.decide(
                compiler_result=_compiler_result(_spec(intent_op="extract_metric_series")),
                policy=policy,
                candidate=candidate,
                runtime_signature=base_signature,
                input_artifact_hashes=base_input_hashes,
                output_contract_version=base_output_contract,
            ),
        ),
        _decision_payload(
            case_id="unverified_output",
            expected_outcome="unverified output invalidates replay",
            decision=gate.decide(
                compiler_result=_compiler_result(base_spec),
                policy=policy,
                candidate=_candidate(
                    spec=base_spec,
                    runtime_signature=base_signature,
                    input_artifact_hashes=base_input_hashes,
                    output_contract_version=base_output_contract,
                    verified_output=False,
                ),
                runtime_signature=base_signature,
                input_artifact_hashes=base_input_hashes,
                output_contract_version=base_output_contract,
            ),
        ),
    ]
    enriched_cases = [{**case, "passed": _case_passed(case)} for case in cases]
    payload: dict[str, object] = {
        "schema_version": "statebus.replay_negative_audit.v1",
        "suite_id": suite_id,
        "case_count": len(enriched_cases),
        "audit_pass": all(bool(case["passed"]) for case in enriched_cases),
        "cases": enriched_cases,
        "claim_level_after_fix": [
            "Can claim replay exact-key mutations are audited and do not silently remain exact replay.",
            "Can claim validated replay requires verified output and contract-compatible task shape.",
            "Cannot claim mature audit-grade replay until these negative checks are also run against persisted live history artifacts.",
        ],
    }
    payload["report_path"] = str(report_root / f"{suite_id}.json")
    payload["markdown_report_path"] = str(report_root / f"{suite_id}.md")
    write_json_report(Path(str(payload["report_path"])), payload)
    write_markdown_report(Path(str(payload["markdown_report_path"])), _build_markdown(payload))
    return payload
