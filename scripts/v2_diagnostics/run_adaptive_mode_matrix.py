from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

from v2.utils import stable_json_dumps


_LIVE_TASKS = ("comparison", "aggregation", "aggregation_by_quarter", "anomaly", "anomaly_acme_delivery")


def _run_case(
    *,
    case_id: str,
    command: list[str],
    run_dir: Path,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    case_dir = run_dir / case_id
    case_dir.mkdir(parents=True, exist_ok=False)
    started_ns = time.perf_counter_ns()
    completed = subprocess.run(command, text=True, capture_output=True, check=False, env=env)
    elapsed_ms = round((time.perf_counter_ns() - started_ns) / 1_000_000.0, 3)
    stdout_path = case_dir / "stdout.log"
    stderr_path = case_dir / "stderr.log"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    result = {
        "case_id": case_id,
        "command": command,
        "exit_code": completed.returncode,
        "elapsed_ms": elapsed_ms,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }
    (case_dir / "result.json").write_text(stable_json_dumps(result) + "\n", encoding="utf-8")
    return result


def _live_summary_path(stdout: str) -> Path | None:
    for line in stdout.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("stage") == "run_created" and isinstance(payload.get("run_dir"), str):
            return Path(payload["run_dir"]) / "summary.json"
    return None


def _attach_live_summary(case: dict[str, object], stdout: str) -> dict[str, object] | None:
    summary_path = _live_summary_path(stdout)
    if summary_path is None or not summary_path.is_file():
        case["task_summary_error"] = "live_task_summary_not_found"
        return None
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        case["task_summary_error"] = "live_task_summary_invalid_json"
        return None
    if not isinstance(summary, dict):
        case["task_summary_error"] = "live_task_summary_not_object"
        return None
    case.update({
        "task_summary_path": str(summary_path),
        "task_name": summary.get("task_name", ""),
        "approved_plan_hash": summary.get("approved_plan_hash", ""),
        "approved_capability_ids": summary.get("approved_capability_ids", []),
        "task_ok": bool(summary.get("ok")),
    })
    return summary


def _assert_live_matrix(summaries: list[dict[str, object]]) -> dict[str, object]:
    failures: list[str] = []
    if len(summaries) != len(_LIVE_TASKS):
        failures.append("live_task_summary_count_mismatch")

    expected_names = set(_LIVE_TASKS)
    observed_names = {str(summary.get("task_name", "")) for summary in summaries}
    if observed_names != expected_names:
        failures.append("live_task_names_mismatch")
    if not all(bool(summary.get("ok")) and bool(summary.get("runtime_completed")) for summary in summaries):
        failures.append("live_task_runtime_incomplete")

    plan_hashes = {str(summary.get("approved_plan_hash", "")) for summary in summaries if summary.get("approved_plan_hash")}
    capability_combinations = {
        tuple(str(capability) for capability in summary.get("approved_capability_ids", []))
        for summary in summaries
    }
    program_or_source_hashes = {
        str(value)
        for summary in summaries
        for value in (
            list(summary.get("codeact_source_hashes", []))
            + list(dict(summary.get("session", {})).get("transform_program_hashes", []))
        )
        if str(value)
    }
    if len(plan_hashes) < 2:
        failures.append("fewer_than_two_approved_plan_hashes")
    if len(capability_combinations) < 2:
        failures.append("fewer_than_two_capability_combinations")
    if len(program_or_source_hashes) < 2:
        failures.append("fewer_than_two_program_or_source_hashes")

    codeact_verified_count = 0.0
    codeact_execution_record_count = 0
    model_fallback_counts: dict[str, float] = {}
    for summary in summaries:
        task_name = str(summary.get("task_name", ""))
        telemetry = dict(summary.get("telemetry", {}))
        model_fallback_count = float(telemetry.get("model_fallback_count", 0.0))
        model_fallback_counts[task_name] = model_fallback_count
        if model_fallback_count != 0.0:
            failures.append(f"model_fallback_used:{task_name}")
        if float(telemetry.get("fallback_used", 0.0)) != 0.0:
            failures.append(f"runtime_fallback_used:{task_name}")
        if float(telemetry.get("llm_codeact_sandbox_fallback_count", 0.0)) != 0.0:
            failures.append(f"sandbox_fallback_used:{task_name}")
        codeact_verified_count += float(telemetry.get("llm_codeact_verified_count", 0.0))

        role_invocations = summary.get("role_invocations", [])
        if not isinstance(role_invocations, list) or not role_invocations:
            failures.append(f"role_model_invocations_missing:{task_name}")
        else:
            for invocation in role_invocations:
                if not isinstance(invocation, dict):
                    failures.append(f"role_model_invocation_invalid:{task_name}")
                    continue
                attempts = invocation.get("attempts", [])
                if not isinstance(attempts, list) or not attempts:
                    failures.append(f"role_model_invocation_missing_attempt:{task_name}")
                    continue
                for attempt in attempts:
                    if (
                        not isinstance(attempt, dict)
                        or attempt.get("error")
                        or not isinstance(attempt.get("model"), str)
                        or not attempt["model"]
                        or not isinstance(attempt.get("raw_response_hash"), str)
                        or not attempt["raw_response_hash"]
                    ):
                        failures.append(f"role_model_invocation_not_live:{task_name}")

        generation_attempts = summary.get("generation_attempts", [])
        codeact_generated = float(telemetry.get("llm_codeact_generation_count", 0.0))
        if codeact_generated > 0.0:
            if not isinstance(generation_attempts, list) or not generation_attempts:
                failures.append(f"codeact_model_generation_missing:{task_name}")
            elif not all(
                isinstance(attempt, dict)
                and isinstance(attempt.get("model_id"), str)
                and bool(attempt["model_id"])
                and isinstance(attempt.get("raw_response_hash"), str)
                and bool(attempt["raw_response_hash"])
                for attempt in generation_attempts
            ):
                failures.append(f"codeact_model_generation_not_live:{task_name}")

        execution_records = summary.get("execution_records", [])
        if not isinstance(execution_records, list):
            failures.append(f"codeact_execution_records_invalid:{task_name}")
            execution_records = []
        codeact_execution_record_count += len(execution_records)
        if codeact_generated > 0.0 and not execution_records:
            failures.append(f"codeact_execution_record_missing:{task_name}")
        for record in execution_records:
            if not isinstance(record, dict):
                failures.append(f"codeact_execution_record_invalid:{task_name}")
                continue
            if record.get("sandbox_actual_backend") != "bwrap":
                failures.append(f"codeact_not_bwrap:{task_name}")
            if record.get("sandbox_uid") != 65534 or record.get("sandbox_gid") != 65534:
                failures.append(f"codeact_sandbox_identity_invalid:{task_name}")
            if record.get("exit_code") != 0:
                failures.append(f"codeact_execution_failed:{task_name}")
            if not bool(record.get("output_schema_valid")):
                failures.append(f"codeact_schema_not_verified:{task_name}")
            if not bool(record.get("output_quality_valid")):
                failures.append(f"codeact_quality_not_verified:{task_name}")
            if not isinstance(record.get("verified_artifact_id"), str) or not record["verified_artifact_id"]:
                failures.append(f"codeact_verified_artifact_missing:{task_name}")

        quality_reports = summary.get("quality_reports", [])
        if (
            not isinstance(quality_reports, list)
            or not quality_reports
            or not all(isinstance(report, dict) and bool(report.get("verified")) for report in quality_reports)
        ):
            failures.append(f"quality_not_verified:{task_name}")
        claim_sets = summary.get("claim_sets", [])
        raw_validation_reports = summary.get("claim_validation_reports", {})
        validation_reports = raw_validation_reports if isinstance(raw_validation_reports, dict) else {}
        if (
            not isinstance(claim_sets, list)
            or not claim_sets
            or not validation_reports
            or not all(
                isinstance(report, dict)
                and isinstance(report.get("claim_validation"), dict)
                and bool(report["claim_validation"].get("ok"))
                for report in validation_reports.values()
            )
        ):
            failures.append(f"claim_set_not_verified:{task_name}")
        consumption = summary.get("state_consumption_records", [])
        if not isinstance(consumption, list) or not consumption or not all(
            isinstance(record, dict) and record.get("behavioral_effect") == "changed"
            for record in consumption
        ):
            failures.append(f"state_consumption_not_changed:{task_name}")
    if codeact_verified_count < 1.0:
        failures.append("no_verified_llm_codeact")

    return {
        "ok": not failures,
        "failures": sorted(set(failures)),
        "approved_plan_hashes": sorted(plan_hashes),
        "capability_combinations": [list(item) for item in sorted(capability_combinations)],
        "program_or_source_hashes": sorted(program_or_source_hashes),
        "verified_codeact_count": codeact_verified_count,
        "codeact_execution_record_count": codeact_execution_record_count,
        "model_fallback_counts": dict(sorted(model_fallback_counts.items())),
        "codeact_sandbox_required_backend": "bwrap",
        "codeact_sandbox_required_uid_gid": [65534, 65534],
        "quality_perturbation_gate": "tests/v2/test_capability_validators.py",
        "fresh_fallback_grant_gate": "tests/v2/test_adaptive_codeact_integration.py::test_python_failure_falls_back_only_with_a_fresh_dsl_grant",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the three repo-local bounded adaptive tasks without formal 25-case or repeat benchmarks."
    )
    parser.add_argument("--output-root", type=Path, default=Path("/statebus/runs"))
    parser.add_argument(
        "--require-live-model-path",
        action="store_true",
        help="Require all three tasks to complete through local-vLLM without model or sandbox fallback.",
    )
    parser.add_argument(
        "--deterministic-only",
        action="store_true",
        help="Run only the numeric perturbation and fresh-fallback-Grant regression gates.",
    )
    args = parser.parse_args()
    if args.require_live_model_path and args.deterministic_only:
        raise SystemExit("require_live_model_path_conflicts_with_deterministic_only")
    run_dir = args.output_root / f"adaptive_mode_matrix_20260717_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=False)
    print(stable_json_dumps({"stage": "run_created", "run_dir": str(run_dir)}), flush=True)

    python = sys.executable
    cases: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    if args.deterministic_only:
        cases.append(_run_case(
            case_id="quality-and-fallback-regressions",
            command=[
                python, "-m", "pytest", "-q",
                "tests/v2/test_capability_validators.py",
                "tests/v2/test_adaptive_codeact_integration.py::test_python_failure_falls_back_only_with_a_fresh_dsl_grant",
            ],
            run_dir=run_dir,
        ))
        assertions = {
            "ok": int(cases[0]["exit_code"]) == 0,
            "quality_perturbation_gate": "passed" if int(cases[0]["exit_code"]) == 0 else "failed",
            "fresh_fallback_grant_gate": "passed" if int(cases[0]["exit_code"]) == 0 else "failed",
        }
    else:
        live_root = run_dir / "live-artifacts"
        live_environment = dict(os.environ)
        # Multi-claim local-vLLM Summarizer calls can exceed the normal
        # single-smoke deadline. Keep this Controller-owned deadline above the
        # configured HTTP deadline and observed tail latency; errors still fail
        # closed and have no model or deterministic fallback.
        live_environment.setdefault("STATEBUS_ADAPTIVE_ROLE_WORKER_TIMEOUT_S", "300")
        # ClaimSet JSON is a bounded evidence report, not a free-form answer.
        # This Controller-owned budget keeps the three-row aggregation task
        # within the local-vLLM service deadline without changing its schema or
        # quality gate. A truncated or invalid response still fails closed.
        live_environment.setdefault("STATEBUS_ADAPTIVE_SUMMARIZER_MAX_TOKENS", "1400")
        for task_name in _LIVE_TASKS:
            case = _run_case(
                case_id=f"adaptive-{task_name}-live",
                command=[
                    python,
                    "scripts/v2_diagnostics/run_llm_codeact_smoke.py",
                    "--task",
                    task_name,
                    "--output-root",
                    str(live_root),
                ],
                run_dir=run_dir,
                env=live_environment,
            )
            stdout = Path(str(case["stdout_path"])).read_text(encoding="utf-8")
            summary = _attach_live_summary(case, stdout)
            if summary is not None:
                summaries.append(summary)
            cases.append(case)
        assertions = _assert_live_matrix(summaries)
        if args.require_live_model_path and not assertions["ok"]:
            assertions["required_live_model_path"] = "failed"

    ok = all(int(case["exit_code"]) == 0 for case in cases) and bool(assertions["ok"])
    summary = {
        "schema_version": "statebus.adaptive_three_task_matrix.v1",
        "run_dir": str(run_dir),
        "formal_benchmark_executed": False,
        "serialized_repeats_executed": False,
        "deterministic_only": args.deterministic_only,
        "cases": cases,
        "assertions": assertions,
        "ok": ok,
    }
    (run_dir / "summary.json").write_text(stable_json_dumps(summary) + "\n", encoding="utf-8")
    print(stable_json_dumps({"ok": ok, "run_dir": str(run_dir), "summary": summary}), flush=True)
    if not ok:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(stable_json_dumps({"ok": False, "exception_type": type(exc).__name__, "exception": str(exc)}), flush=True)
        traceback.print_exc()
        raise
