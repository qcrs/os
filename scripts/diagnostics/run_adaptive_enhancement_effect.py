from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
import json
from math import isclose
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from typing import Any

from scripts.diagnostics.run_llm_codeact_smoke import _task_definition
from statebus.runtime.capability_validators import (
    CapabilityQualityContext,
    default_capability_validator_registry,
)
from statebus.runtime.codeact_sandbox import CodeActSandboxConfig, CodeActSandboxRunner
from statebus.utils import sha256_digest, stable_json_dumps


_PROBE_TASK_NAME = "anomaly"
_SCHEMA_VERSION = "statebus.adaptive_enhancement_effect.v1"


@dataclass(frozen=True)
class EffectGate:
    name: str
    passed: bool
    evidence: object


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_rows(payload: object, *, label: str) -> tuple[dict[str, object], ...]:
    if isinstance(payload, dict):
        return (dict(payload),)
    if isinstance(payload, list) and all(isinstance(row, dict) for row in payload):
        return tuple(dict(row) for row in payload)
    raise ValueError(f"{label}_must_be_json_object_or_object_array")


def _single_path(root: Path, pattern: str) -> Path:
    paths = tuple(root.glob(pattern))
    if len(paths) != 1:
        raise ValueError(f"expected_one_path:{pattern}:found={len(paths)}")
    return paths[0]


def _source_profile(source: str) -> dict[str, object]:
    tree = ast.parse(source)
    profile = {
        "function_count": sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree)),
        "loop_count": sum(isinstance(node, (ast.For, ast.While, ast.comprehension)) for node in ast.walk(tree)),
        "arithmetic_count": sum(isinstance(node, ast.BinOp) for node in ast.walk(tree)),
        "comparison_count": sum(isinstance(node, ast.Compare) for node in ast.walk(tree)),
        "reads_authorized_input": "inputs/task.json" in source,
        "writes_authorized_output": "outputs/result.json" in source,
    }
    profile["computational"] = bool(
        profile["loop_count"]
        and profile["arithmetic_count"]
        and profile["comparison_count"]
        and profile["reads_authorized_input"]
        and profile["writes_authorized_output"]
    )
    return profile


def _counterfactual_rows(
    rows: tuple[dict[str, object], ...],
    *,
    value_field: str,
) -> tuple[dict[str, object], ...]:
    if not rows:
        raise ValueError("counterfactual_input_empty")
    changed = [dict(row) for row in rows]
    value = changed[-1].get(value_field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"counterfactual_value_not_numeric:{value_field}")
    delta = max(7.0, abs(float(value)) * 0.13)
    changed[-1][value_field] = round(float(value) + delta, 6)
    return tuple(changed)


def _quality_report(
    *,
    task: Any,
    input_rows: tuple[dict[str, object], ...],
    output_rows: tuple[dict[str, object], ...],
    output_hash: str,
) -> object:
    context = CapabilityQualityContext(
        capability_id=task.analysis_python_capability,
        validator_id="anomaly",
        input_rows=(input_rows,),
        output_rows=output_rows,
        input_artifact_hashes=(sha256_digest(stable_json_dumps(input_rows).encode("utf-8")),),
        output_artifact_hash=output_hash,
        required_fields=tuple(task.analysis_schema),
        completion_criteria={"min_rows": 1},
        operation_semantics=dict(task.analysis_semantics),
        provenance_item_ids=("counterfactual-probe",),
    )
    return default_capability_validator_registry().validate(context)


def _claim_row_coverage(
    claim_sets: object,
    output_rows: tuple[dict[str, object], ...],
    *,
    value_field: str,
) -> dict[str, object]:
    sets = claim_sets if isinstance(claim_sets, list) else []
    claims = [
        claim
        for claim_set in sets
        if isinstance(claim_set, dict)
        for claim in claim_set.get("claims", [])
        if isinstance(claim, dict)
    ]
    claim_ids = [str(claim.get("claim_id", "")) for claim in claims]
    matches_by_row: list[int] = []
    for row in output_rows:
        expected = row.get(value_field)
        matches = 0
        for claim in claims:
            numeric_fields = claim.get("numeric_fields", {})
            observed = numeric_fields.get(value_field) if isinstance(numeric_fields, dict) else None
            if (
                isinstance(expected, (int, float))
                and not isinstance(expected, bool)
                and isinstance(observed, (int, float))
                and not isinstance(observed, bool)
                and isclose(float(expected), float(observed), rel_tol=1e-9, abs_tol=1e-9)
            ):
                matches += 1
        matches_by_row.append(matches)
    support_complete = all(
        claim.get("status") == "ready"
        and bool(claim.get("supporting_artifact_ref_ids"))
        and bool(claim.get("supporting_evidence_item_ids"))
        and bool(claim.get("citation_locators"))
        for claim in claims
    )
    return {
        "passed": bool(
            len(claims) == len(output_rows)
            and len(set(claim_ids)) == len(claim_ids)
            and all(count == 1 for count in matches_by_row)
            and support_complete
        ),
        "claim_count": len(claims),
        "row_count": len(output_rows),
        "unique_claim_id_count": len(set(claim_ids)),
        "matches_by_row": matches_by_row,
        "support_complete": support_complete,
    }


def _parse_live_summary_path(stdout: str) -> Path:
    for line in reversed(stdout.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("run_dir"), str):
            candidate = Path(payload["run_dir"]) / "summary.json"
            if candidate.is_file():
                return candidate
    raise ValueError("live_probe_summary_not_found")


def _run_live_probe(run_dir: Path) -> Path:
    live_root = run_dir / "live"
    live_root.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env.setdefault("STATEBUS_ADAPTIVE_ROLE_WORKER_TIMEOUT_S", "300")
    env.setdefault("STATEBUS_ADAPTIVE_SUMMARIZER_MAX_TOKENS", "1400")
    command = [
        sys.executable,
        "scripts/diagnostics/run_llm_codeact_smoke.py",
        "--task",
        _PROBE_TASK_NAME,
        "--output-root",
        str(live_root),
    ]
    timeout_seconds = int(os.getenv("STATEBUS_ADAPTIVE_EFFECT_LIVE_TIMEOUT_S", "900"))
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=timeout_seconds,
    )
    (run_dir / "live_stdout.jsonl").write_text(completed.stdout, encoding="utf-8")
    (run_dir / "live_stderr.log").write_text(completed.stderr, encoding="utf-8")
    (run_dir / "live_command.json").write_text(
        stable_json_dumps({"command": command, "exit_code": completed.returncode}) + "\n",
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"live_enhancement_probe_failed:exit={completed.returncode}")
    return _parse_live_summary_path(completed.stdout)


def _run_counterfactual(
    *,
    run_dir: Path,
    source_path: Path,
    original_rows: tuple[dict[str, object], ...],
    task: Any,
) -> dict[str, object]:
    root = run_dir / "counterfactual"
    inputs_dir = root / "inputs"
    outputs_dir = root / "outputs"
    inputs_dir.mkdir(parents=True, exist_ok=False)
    outputs_dir.mkdir(parents=True, exist_ok=False)
    changed_rows = _counterfactual_rows(
        original_rows,
        value_field=str(task.analysis_semantics["value_field"]),
    )
    input_path = inputs_dir / "task.json"
    input_path.write_text(stable_json_dumps(changed_rows) + "\n", encoding="utf-8")
    input_path.chmod(0o444)
    inputs_dir.chmod(0o555)
    outputs_dir.chmod(0o777)
    sandbox = CodeActSandboxRunner(CodeActSandboxConfig(requested_backend="bwrap", timeout_seconds=30.0))
    sandbox_result = sandbox.run_llm_bwrap(
        source_path=source_path,
        inputs_dir=inputs_dir,
        outputs_dir=outputs_dir,
        policy_version="statebus.llm_bwrap.v1",
    )
    output_path = outputs_dir / "result.json"
    if sandbox_result.actual_backend != "bwrap" or sandbox_result.completed.returncode != 0:
        raise RuntimeError(
            "counterfactual_bwrap_failed:"
            f"backend={sandbox_result.actual_backend}:exit={sandbox_result.completed.returncode}:"
            f"reason={sandbox_result.fallback_reason}"
        )
    changed_output = _json_rows(_load_json(output_path), label="counterfactual_output")
    output_hash = sha256_digest(output_path.read_bytes())
    quality = _quality_report(
        task=task,
        input_rows=changed_rows,
        output_rows=changed_output,
        output_hash=output_hash,
    )
    tampered_rows = [dict(row) for row in changed_output]
    tampered_rows[0]["baseline_mean"] = float(tampered_rows[0]["baseline_mean"]) + 1.0
    tampered = _quality_report(
        task=task,
        input_rows=changed_rows,
        output_rows=tuple(tampered_rows),
        output_hash=sha256_digest(stable_json_dumps(tampered_rows).encode("utf-8")),
    )
    return {
        "source_path": str(source_path),
        "source_hash": sha256_digest(source_path.read_bytes()),
        "input_path": str(input_path),
        "output_path": str(output_path),
        "original_input_hash": sha256_digest(stable_json_dumps(original_rows).encode("utf-8")),
        "counterfactual_input_hash": sha256_digest(stable_json_dumps(changed_rows).encode("utf-8")),
        "counterfactual_output_hash": sha256_digest(stable_json_dumps(changed_output).encode("utf-8")),
        "counterfactual_output_artifact_hash": output_hash,
        "sandbox_actual_backend": sandbox_result.actual_backend,
        "sandbox_exit_code": sandbox_result.completed.returncode,
        "quality_verified": bool(quality.verified),
        "quality_report": quality.canonical_payload(),
        "tampered_output_rejected": not tampered.verified,
        "tampered_error_codes": list(tampered.error_codes),
    }


def _build_gates(
    *,
    summary: dict[str, object],
    source_path: Path,
    original_input: tuple[dict[str, object], ...],
    original_output: tuple[dict[str, object], ...],
    counterfactual: dict[str, object],
) -> list[EffectGate]:
    telemetry = dict(summary.get("telemetry", {}))
    session = dict(summary.get("session", {}))
    workflow_steps = session.get("workflow_steps", [])
    role_invocations = summary.get("role_invocations", [])
    role_invocations = role_invocations if isinstance(role_invocations, list) else []
    role_names = {str(item.get("role", "")) for item in role_invocations if isinstance(item, dict)}
    modeled_roles = {
        str(item.get("role", ""))
        for item in role_invocations
        if isinstance(item, dict)
        and isinstance(item.get("attempts"), list)
        and bool(item["attempts"])
        and all(
            isinstance(attempt, dict)
            and bool(attempt.get("model"))
            and bool(attempt.get("raw_response_hash"))
            for attempt in item["attempts"]
        )
    }
    generations = summary.get("generation_attempts", [])
    generations = generations if isinstance(generations, list) else []
    records = summary.get("execution_records", [])
    records = records if isinstance(records, list) else []
    record = records[0] if len(records) == 1 and isinstance(records[0], dict) else {}
    quality_reports = summary.get("quality_reports", [])
    quality_reports = quality_reports if isinstance(quality_reports, list) else []
    codeact_quality = [
        report
        for report in quality_reports
        if isinstance(report, dict) and report.get("capability_id") == "detect_anomaly_python_v1"
    ]
    claim_reports = summary.get("claim_validation_reports", {})
    claim_reports = claim_reports if isinstance(claim_reports, dict) else {}
    claim_report_ok = bool(claim_reports) and all(
        isinstance(report, dict)
        and isinstance(report.get("claim_validation"), dict)
        and bool(report["claim_validation"].get("ok"))
        for report in claim_reports.values()
    )
    summarizer_calls = [
        item
        for item in role_invocations
        if isinstance(item, dict) and item.get("role") == "summarizer"
    ]
    source_profile = _source_profile(source_path.read_text(encoding="utf-8"))
    row_coverage = _claim_row_coverage(
        summary.get("claim_sets", []),
        original_output,
        value_field="on_time_delivery_pct",
    )
    original_quality = _quality_report(
        task=_task_definition(_PROBE_TASK_NAME),
        input_rows=original_input,
        output_rows=original_output,
        output_hash=sha256_digest(stable_json_dumps(original_output).encode("utf-8")),
    )
    source_hash = sha256_digest(source_path.read_bytes())
    original_input_hash = sha256_digest(stable_json_dumps(original_input).encode("utf-8"))
    original_output_artifact_hash = sha256_digest(
        (source_path.parent.parent / "outputs" / "result.json").read_bytes()
    )
    recorded_source_hashes = [str(value) for value in summary.get("codeact_source_hashes", [])]
    approved_capabilities = [str(value) for value in summary.get("approved_capability_ids", [])]
    codeact_step_completed = any(
        isinstance(step, dict)
        and step.get("capability") == "detect_anomaly_python_v1"
        and step.get("state") == "COMPLETED"
        for step in workflow_steps if isinstance(workflow_steps, list)
    )
    state_records = summary.get("state_consumption_records", [])
    state_records = state_records if isinstance(state_records, list) else []
    gates = [
        EffectGate(
            "live_runtime_completed",
            bool(summary.get("ok")) and bool(summary.get("runtime_completed")),
            {"workflow_mode": summary.get("workflow_mode"), "runtime_completed": summary.get("runtime_completed")},
        ),
        EffectGate(
            "planner_model_selected_executed_plan",
            bool(summary.get("planner_model_id"))
            and bool(summary.get("planner_raw_output_hash"))
            and telemetry.get("adaptive_plan_model_used") == 1
            and telemetry.get("proposal_valid") == 1
            and codeact_step_completed,
            {
                "planner_model_id": summary.get("planner_model_id"),
                "planner_raw_output_hash": summary.get("planner_raw_output_hash"),
                "approved_capabilities": approved_capabilities,
            },
        ),
        EffectGate(
            "retriever_model_changed_candidates",
            float(telemetry.get("retriever_model_query_count", 0)) > 0
            and float(telemetry.get("retriever_query_changed_candidate_set_count", 0)) > 0
            and any(isinstance(item, dict) and item.get("behavioral_effect") == "changed" for item in state_records),
            {
                "query_count": telemetry.get("retriever_model_query_count", 0),
                "changed_candidate_count": telemetry.get("retriever_query_changed_candidate_set_count", 0),
            },
        ),
        EffectGate(
            "four_model_roles_observed",
            {"planner", "retriever", "executor", "summarizer"} <= modeled_roles
            and bool(generations)
            and all(
                isinstance(item, dict)
                and bool(item.get("model_id"))
                and bool(item.get("raw_response_hash"))
                for item in generations
            ),
            {
                "role_names": sorted(role_names),
                "modeled_roles": sorted(modeled_roles),
                "code_generation_attempt_count": len(generations),
            },
        ),
        EffectGate(
            "generated_code_is_computational",
            bool(source_profile["computational"]),
            source_profile,
        ),
        EffectGate(
            "codeact_runtime_bwrap_verified",
            len(records) == 1
            and source_hash in recorded_source_hashes
            and record.get("source_hash") == source_hash
            and record.get("output_hash") == original_output_artifact_hash
            and summary.get("upstream_input_artifact_hash") == original_input_hash
            and record.get("sandbox_actual_backend") == "bwrap"
            and int(record.get("sandbox_uid", 0)) != 0
            and int(record.get("sandbox_gid", 0)) != 0
            and bool(record.get("output_schema_valid"))
            and bool(record.get("output_quality_valid"))
            and telemetry.get("llm_codeact_verified_count") == 1,
            {
                "execution_record": record,
                "source_hash": source_hash,
                "recorded_source_hashes": recorded_source_hashes,
                "original_input_hash": original_input_hash,
                "recorded_upstream_input_hash": summary.get("upstream_input_artifact_hash"),
                "original_output_artifact_hash": original_output_artifact_hash,
            },
        ),
        EffectGate(
            "independent_business_recomputation_passed",
            len(codeact_quality) == 1
            and bool(codeact_quality[0].get("verified"))
            and bool(codeact_quality[0].get("recomputation_passed"))
            and bool(original_quality.verified),
            codeact_quality[0] if codeact_quality else {},
        ),
        EffectGate(
            "no_runtime_or_sandbox_fallback",
            float(telemetry.get("fallback_used", 0)) == 0
            and float(telemetry.get("llm_codeact_sandbox_fallback_count", 0)) == 0
            and not bool(record.get("fallback_reason")),
            {
                "fallback_used": telemetry.get("fallback_used", 0),
                "sandbox_fallback": telemetry.get("llm_codeact_sandbox_fallback_count", 0),
                "record_fallback_reason": record.get("fallback_reason", ""),
            },
        ),
        EffectGate(
            "summarizer_batched_model_claims_validated",
            len(summarizer_calls) >= 2
            and sum(int(item.get("claim_batch_row_count", 0)) for item in summarizer_calls) == len(original_output)
            and all(1 <= int(item.get("claim_batch_row_count", 0)) <= 2 for item in summarizer_calls)
            and claim_report_ok
            and bool(row_coverage["passed"]),
            {
                "batch_sizes": [item.get("claim_batch_row_count") for item in summarizer_calls],
                "claim_validation_ok": claim_report_ok,
                "row_coverage": row_coverage,
            },
        ),
        EffectGate(
            "same_generated_code_reacts_to_counterfactual_input",
            counterfactual.get("source_hash") == source_hash
            and counterfactual.get("original_input_hash") != counterfactual.get("counterfactual_input_hash")
            and sha256_digest(stable_json_dumps(original_output).encode("utf-8"))
            != counterfactual.get("counterfactual_output_hash")
            and bool(counterfactual.get("quality_verified")),
            {
                "source_hash": source_hash,
                "original_input_hash": counterfactual.get("original_input_hash"),
                "counterfactual_input_hash": counterfactual.get("counterfactual_input_hash"),
                "counterfactual_output_hash": counterfactual.get("counterfactual_output_hash"),
            },
        ),
        EffectGate(
            "tampered_output_rejected",
            bool(counterfactual.get("tampered_output_rejected"))
            and "anomaly_recomputation_mismatch" in counterfactual.get("tampered_error_codes", []),
            {"error_codes": counterfactual.get("tampered_error_codes", [])},
        ),
        EffectGate(
            "audit_hash_chain_present",
            all(
                bool(summary.get(field))
                for field in (
                    "approved_plan_hash",
                    "proposal_hash",
                    "evidence_pack_hashes",
                    "projection_report_hashes",
                    "codeact_source_hashes",
                    "codeact_quality_report_hashes",
                    "claim_set_hashes",
                )
            ),
            {
                field: summary.get(field)
                for field in (
                    "approved_plan_hash",
                    "proposal_hash",
                    "evidence_pack_hashes",
                    "projection_report_hashes",
                    "codeact_source_hashes",
                    "codeact_quality_report_hashes",
                    "claim_set_hashes",
                )
            },
        ),
    ]
    return gates


def _write_analysis(path: Path, payload: dict[str, object]) -> None:
    gates = payload["gates"]
    lines = [
        "# Adaptive Enhancement Effect Audit",
        "",
        f"- Overall: `{'PASS' if payload['ok'] else 'FAIL'}`",
        "- Scope: one focused live adaptive/LLM-CodeAct causal probe; no legacy 5-case or 25-case suite.",
        "- This result proves mechanism participation for this probe, not benchmark generalization or latency superiority.",
        "",
        "## Gates",
        "",
    ]
    for gate in gates:
        lines.append(f"- `{'PASS' if gate['passed'] else 'FAIL'}` `{gate['name']}`")
    lines.extend([
        "",
        "## Artifacts",
        "",
        f"- Live summary: `{payload['live_summary_path']}`",
        f"- Generated source: `{payload['counterfactual']['source_path']}`",
        f"- Counterfactual output: `{payload['counterfactual']['output_path']}`",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one focused causal audit of the current adaptive LLM-CodeAct enhancement."
    )
    parser.add_argument("--output-root", type=Path, default=Path("/statebus/runs"))
    parser.add_argument(
        "--existing-summary",
        type=Path,
        help="Analyze an existing single-task live summary instead of making a new vLLM call.",
    )
    args = parser.parse_args()
    run_dir = args.output_root / f"adaptive_enhancement_effect_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=False)
    print(stable_json_dumps({"stage": "run_created", "run_dir": str(run_dir)}), flush=True)

    live_summary_path = args.existing_summary or _run_live_probe(run_dir)
    if not live_summary_path.is_file():
        raise FileNotFoundError(live_summary_path)
    summary_raw = _load_json(live_summary_path)
    if not isinstance(summary_raw, dict):
        raise ValueError("live_summary_must_be_object")
    summary = dict(summary_raw)
    live_run_dir = live_summary_path.parent
    source_path = _single_path(
        live_run_dir,
        "runtime/adaptive_attempts/*/codeact/generated/llm_generated.py",
    )
    codeact_root = source_path.parent.parent
    original_input = _json_rows(_load_json(codeact_root / "inputs" / "task.json"), label="original_input")
    original_output = _json_rows(_load_json(codeact_root / "outputs" / "result.json"), label="original_output")
    task = _task_definition(_PROBE_TASK_NAME)
    counterfactual = _run_counterfactual(
        run_dir=run_dir,
        source_path=source_path,
        original_rows=original_input,
        task=task,
    )
    gates = _build_gates(
        summary=summary,
        source_path=source_path,
        original_input=original_input,
        original_output=original_output,
        counterfactual=counterfactual,
    )
    ok = all(gate.passed for gate in gates)
    result = {
        "schema_version": _SCHEMA_VERSION,
        "ok": ok,
        "run_dir": str(run_dir),
        "scope": {
            "live_case_count": 1,
            "probe_task": _PROBE_TASK_NAME,
            "legacy_five_case_matrix_executed": False,
            "formal_25_case_executed": False,
            "latency_claim_allowed": False,
            "generalization_claim_allowed": False,
        },
        "live_summary_path": str(live_summary_path),
        "gates": [asdict(gate) for gate in gates],
        "counterfactual": counterfactual,
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_analysis(run_dir / "analysis.md", result)
    print(stable_json_dumps({"ok": ok, "run_dir": str(run_dir), "summary_path": str(summary_path)}), flush=True)
    if not ok:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            stable_json_dumps({"ok": False, "exception_type": type(exc).__name__, "exception": str(exc)}),
            flush=True,
        )
        traceback.print_exc()
        raise
