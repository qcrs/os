"""Read-only acceptance audit of a Stage1 batch, independent of summary flags."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import yaml

from statebus.benchmark.contest_stage1 import write_json
from statebus.benchmark.contest_stage1_report import REPORT_CONTRACT_VERSION, report_errors, report_sources, text_statements
from statebus.benchmark.contest_stage1_scorer import score_rows
from statebus.benchmark.contest_stage1_taskpack import ENTITIES, FAMILIES, PERIODS, files_for
from statebus.benchmark.request_journal import summarize_journal
from statebus.utils import stable_json_dumps


VARIANTS = {"sb-no-memory": ("SB-FULL", "SB-NO-MEMORY", "none"),
            "sb-full": ("SB-FULL", "SB-FULL", "validated_replay"),
            "p-text": ("P-TEXT", "P-TEXT", "none")}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def check(condition, name):
    if not condition:
        raise ValueError(name)


def audit_memory(result, previous, task_id, policy):
    records = result["memory_consumption_records"]
    queries = result["memory_query_results"]
    commit = result["memory_commit_decision"]
    check(isinstance(records, list) and isinstance(queries, dict), "memory_evidence_type")
    if policy == "none":
        check(not records and not commit.get("committed"), "memory_used_while_disabled")
    if previous is not None:
        check(result["source_artifact_hash"] != previous["source_artifact_hash"], "current_input_not_changed")
        check(result["execution_output_artifact_hash"] != previous["execution_output_artifact_hash"], "current_output_not_changed")
        if policy != "none":
            check(bool(queries), "memory_query_evidence_missing")
    output_hash = result["execution_output_artifact_hash"]
    executions = [r for r in result["execution_records"] if r["output_hash"] == output_hash
                  and r["exit_code"] == 0 and r["output_quality_valid"] and r["output_schema_valid"]]
    check(bool(executions), "current_execution_missing")
    check(any(r["verified"] and r["recomputation_evaluated"] and r["recomputation_passed"]
              and r["provenance_passed"] and r["output_artifact_hash"] == output_hash
              for r in result["terminal_quality_reports"]), "current_recomputation_missing")
    if commit.get("committed"):
        check(commit["artifact_hash"] == output_hash and result["source_artifact_hash"] in commit["input_lineage_hashes"],
              "commit_lineage_mismatch")
        check(commit["benchmark_gold_used"] is False and bool(commit["memory_admission_receipt_hash"]), "commit_admission_missing")
    for record in records:
        check(previous is not None, "unexpected_cold_memory")
        prior = previous["memory_commit_decision"]
        check(prior["committed"] and record["memory_id"] == prior["memory_id"], "memory_not_from_own_producer")
        check(record["memory_admission_receipt_hash"] == prior["memory_admission_receipt_hash"], "memory_admission_mismatch")
        session = result["runtime_session"]
        check(record["consumer_runtime_task_id"] == task_id and record["consumer_session_id"] == session["session_id"],
              "memory_consumer_identity_mismatch")
        check(record["capability_grant_hash"] in session["capability_grant_hashes"], "memory_grant_mismatch")
        check(any(a["attempt_id"] == record["consumer_attempt_id"] and a["step_id"] == record["consumer_step_id"]
                  and a["owner_role"] == record["consumer_role"] and a["state"] == "COMPLETED"
                  for a in session["attempt_records"]), "memory_attempt_mismatch")
        check(all(record.get(k) for k in ("attempt_result_admission_receipt_hash", "memory_commit_hash",
                                         "replay_eligibility_receipt_hash", "query_hash")), "memory_receipt_missing")
        check(any(d["memory_id"] == record["memory_id"] and d["policy_approved"]
                  and d["replay_class"] == record["replay_class"]
                  for q in queries.values() for d in q["compatibility_decisions"]), "memory_compatibility_missing")
        if record["replay_class"] == "validated_replay":
            check(record["recipe_recomputed"] is True and record["recipe_step_status"] == "skipped_generation",
                  "memory_recipe_not_recomputed")
            check(any(e["verified_artifact_id"] in record["downstream_ref_ids"] for e in executions), "memory_output_mismatch")
            old_sources = {e["source_hash"] for e in previous["execution_records"]
                           if e["output_hash"] == previous["execution_output_artifact_hash"] and e["output_quality_valid"]}
            check(any(e["source_hash"] in old_sources for e in executions), "memory_recipe_source_mismatch")
    return {"status": "consumed" if records else "not_observed" if policy != "none" and previous else "disabled_or_cold",
            "consumption_count": len(records), "queries": {k: q.get("retrieval_decision") for k, q in queries.items()},
            "current_input_recomputed": True}


def audit_stage1(root: Path, variant: str, *, embedding_device: str = "cuda:0") -> dict:
    profile, label, policy = VARIANTS[variant]
    root = root.resolve()
    report = {"ok": False, "variant": variant, "report_contract_version": REPORT_CONTRACT_VERSION,
              "formal_headline_eligible": False, "semantic_review_required": True, "tasks": [], "errors": []}

    def inspect(section, operation, row_report=None):
        # A failed check never admits a batch, but must not hide other tasks or
        # their incurred costs. Only read paths derived from the expected plan.
        try:
            return operation()
        except (OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError) as exc:
            error = f"{section}:{type(exc).__name__}:{exc}"
            report["errors"].append(error)
            if row_report is not None:
                row_report["errors"].append(error)
            return None

    summary = inspect("summary", lambda: read_json(root / "summary.json"))
    ledger = []
    if isinstance(summary, dict):
        inspect("batch_count", lambda: check(summary["planned_count"] == summary["passed_count"] == 4,
                                               "batch_count_or_failure"))
        inspect("batch_contract", lambda: check(summary["report_contract_version"] == REPORT_CONTRACT_VERSION,
                                                  "batch_report_contract"))
        inspect("batch_scope", lambda: check(summary["formal_headline_eligible"] is False
                                               and summary["semantic_review_required"] is True, "batch_scope"))
        raw_ledger = summary.get("ledger")
        if isinstance(raw_ledger, list) and all(isinstance(e, dict) for e in raw_ledger):
            ledger = raw_ledger
        inspect("task_ids", lambda: check(len(ledger) == 4 and sorted(e["task_id"] for e in ledger) == sorted(PERIODS), "task_ids"))
    else:
        inspect("summary", lambda: check(False, "summary_not_object"))

    results, budgets, configurations = {}, [], []
    for task_id in PERIODS:
        row_report = {"task_id": task_id, "ok": False, "errors": []}
        report["tasks"].append(row_report)
        task = root / FAMILIES[task_id[0]] / label / task_id

        def task_inspect(section, operation):
            return inspect(task_id + ":" + section, operation, row_report)

        def load(name):
            path = task / name
            check(path.resolve().is_relative_to(root), "artifact_path_outside_batch:" + name)
            return read_json(path)

        def inspect_scorer(score):
            checks = score.get("checks", {})
            check(isinstance(checks, dict), "scorer_checks_type")
            row_report["scorer"] = {"passed": score.get("passed"), "business_report_errors": score.get("business_report_errors"),
                                    "failed_checks": [k for k, v in checks.items() if v is not True]}

        matches = [e for e in ledger if e.get("task_id") == task_id]
        task_inspect("ledger", lambda: check(len(matches) == 1, "ledger_entry_count"))
        entry = matches[0] if len(matches) == 1 else None
        if entry is not None:
            row_report.update(status=entry.get("status"), elapsed_ms=entry.get("elapsed_ms"), returncode=entry.get("returncode"))
            task_inspect("ledger_variant", lambda: check(
                (entry["profile"], entry["configuration_label"], entry["memory_policy"]) == (profile, label, policy), "ledger_variant"))
            task_inspect("ledger_status", lambda: check(entry["family"] == FAMILIES[task_id[0]]
                and entry["status"] == "success" and entry["ok"] is True, "ledger_status"))
            task_inspect("result_path", lambda: check(Path(entry["result_path"]).resolve() == task / "result.json", "result_path"))

        def inspect_provider():
            check((task / "provider.jsonl").resolve().is_relative_to(root), "provider_path_outside_batch")
            provider = summarize_journal(task / "provider.jsonl")
            missing = any(v is None for v in provider["usage"].values())
            row_report.update(provider=provider, usage_status="missing_explicit" if missing else "complete")
            check(not missing or bool(provider["usage_missing_reason"]), "usage_missing_reason")
            events = [json.loads(line) for line in (task / "provider.jsonl").read_text().splitlines()]
            row_report["executor_provider_requests"] = (None if provider["unresolved_call_ids"] else sum(
                len(e["provider_events"]) for e in events if e["event"] == "finished" and e["role"] == "executor"))
            check(entry is not None and provider == entry["provider"] and provider["call_count"] > 0, "provider_journal_mismatch")
        task_inspect("provider", inspect_provider)

        result = task_inspect("result", lambda: load("result.json"))
        failure_envelope = (isinstance(result, dict) and result.get("ok") is False
                            and "error" in result and "task_id" not in result)
        scorer_path = task / "scorer.json"
        if failure_envelope and not scorer_path.exists():
            row_report["scorer_status"] = "not_produced_after_worker_failure"
            # The scorer is a separate artifact.  Its absence is useful
            # secondary evidence, while success-only result checks remain
            # suppressed below for the failed worker envelope.
            score = task_inspect("scorer", lambda: load("scorer.json"))
        else:
            score = task_inspect("scorer", lambda: load("scorer.json"))
        if isinstance(result, dict):
            row_report["failure"] = {k: result[k] for k in ("failure_classification", "error", "failure") if k in result}
            # The runner writes a small failure envelope when a worker exits
            # before execute_worker can write its normal result contract.  It
            # is evidence of a failed task, not a partially valid result.  Do
            # not turn its missing success-only fields into a cascade of
            # unrelated KeyError diagnostics; preserve the single root cause
            # and continue auditing the other tasks and incurred costs.
            if failure_envelope:
                detail = result.get("failure")
                # Keep the stable lifecycle error as the acceptance diagnosis.
                # The nested exception and traceback remain in row_report["failure"]
                # for root-cause inspection without turning them into a second
                # success-path schema failure.
                cause = result.get("error")
                if not cause and isinstance(detail, dict):
                    cause = detail.get("error")
                task_inspect("worker_failure", lambda: check(False, str(cause)))
            else:
                task_inspect("result_status", lambda: check(result["ok"] is True and result["external_score_passed"] is True, "result_or_scorer"))
                task_inspect("result_identity", lambda: check(result["task_id"] == task_id and result["profile"] == profile, "result_identity"))
                task_inspect("result_variant", lambda: check(result["configuration_label"] == label and result["memory_policy"] == policy, "result_variant"))
                task_inspect("report_contract", lambda: check(result["report_contract_version"] == REPORT_CONTRACT_VERSION, "report_contract"))
                task_inspect("independent_score", lambda: check(score_rows(task / "public", task_id, result["output_rows"])["passed"], "independent_score"))

                def inspect_report():
                    notes = files_for(task / "public", task_id)[-1]
                    sources = report_sources(notes.read_text(), source_name=notes.name, period=PERIODS[task_id], entities=ENTITIES[task_id[0]])
                    statements = ([c for s in result["claim_sets"] for c in s["claims"]] if profile == "SB-FULL"
                                  else text_statements(result["summary_text"]))
                    errors = report_errors(result["output_rows"], statements, sources=sources,
                                           evidence_items=result["report_evidence_items"] if profile == "SB-FULL" else None)
                    row_report["report_recheck_errors"] = errors
                    check(not errors, "report_recheck:" + ",".join(errors))
                task_inspect("report", inspect_report)
                previous = results.get(task_id[0] + "01") if task_id.endswith("02") else None
                if profile == "SB-FULL":
                    memory = task_inspect("memory", lambda: audit_memory(result, previous, task_id, policy))
                    if memory is not None:
                        row_report["memory"] = memory
                elif previous is not None:
                    task_inspect("fresh_output", lambda: check(result["output_rows"] != previous["output_rows"], "text_stale_output"))
                results[task_id] = result
        else:
            task_inspect("result_type", lambda: check(False, "result_not_object"))
        if isinstance(score, dict):
            task_inspect("scorer_checks", lambda: inspect_scorer(score))
            task_inspect("scorer_status", lambda: check(score["passed"] is True, "result_or_scorer"))
            task_inspect("scorer_contract", lambda: check(score["report_contract_version"] == REPORT_CONTRACT_VERSION, "report_contract"))
            task_inspect("stored_report", lambda: check(score["business_report_errors"] == [], "stored_report_errors"))
        elif not failure_envelope:
            task_inspect("scorer_type", lambda: check(False, "scorer_not_object"))
        for name, key in (("execution/business-report-checks.json", "report_checks"), ("failure.json", "worker_failure")):
            if (task / name).exists():
                row_report[key] = task_inspect(key, lambda: load(name))

        def inspect_environment():
            env = load("execution-environment.json")
            check(env["profile"] == profile and env["embedding_device"] == embedding_device
                  and env["configuration_label"] == label and env["memory_policy"] == policy, "execution_environment")
        task_inspect("environment", inspect_environment)
        budget = task_inspect("budget", lambda: load("effective-budget.json"))
        if budget is not None:
            budgets.append(budget)
        configuration = task_inspect("configuration", lambda: hashlib.sha256(stable_json_dumps(
            yaml.safe_load((task / "effective-llm.yaml").read_text())).encode()).hexdigest())
        if configuration is not None:
            configurations.append(configuration)
        row_report["ok"] = not row_report["errors"]

    inspect("budgets", lambda: check(len(budgets) == 4 and all(b == budgets[0] for b in budgets), "effective_budget_changed_within_batch"))
    inspect("configurations", lambda: check(len(configurations) == 4 and len(set(configurations)) == 1, "effective_configuration_changed_within_batch"))
    if len(budgets) == 4 and all(b == budgets[0] for b in budgets):
        report["effective_budget"] = budgets[0]
    if len(configurations) == 4 and len(set(configurations)) == 1:
        report["effective_configuration_hash"] = configurations[0]

    def total(values):
        return sum(values) if all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values) else None
    def observed_total(values):
        known = [v for v in values if type(v) in (int, float) and math.isfinite(v) and v >= 0]
        return sum(known) if known else None
    providers = [row.get("provider", {}) for row in report["tasks"]]
    report["costs"] = {
        "task_elapsed_ms_sum": total([row.get("elapsed_ms") for row in report["tasks"]]),
        "provider_request_count": total([p.get("provider_request_count") for p in providers]),
        "observed_provider_request_count": observed_total([p.get("observed_provider_request_count") for p in providers]),
        "usage": {k: total([p.get("usage", {}).get(k) for p in providers]) for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
        "observed_usage_partial": {k: observed_total([p.get("observed_usage_partial", {}).get(k) for p in providers])
                                   for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
        "missing_provider_task_ids": [r["task_id"] for r in report["tasks"] if not r.get("provider", {}).get("call_count")],
        "scope": "all_planned_tasks_including_failures_and_repairs_not_success_only",
    }
    report["costs"]["usage_missing_reason"] = (
        "one_or_more_task_usage_missing_or_unsettled" if any(v is None for v in report["costs"]["usage"].values()) else ""
    )
    report["ok"] = not report["errors"] and all(row["ok"] for row in report["tasks"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--variant", choices=tuple(VARIANTS), required=True)
    parser.add_argument("--embedding-device", default="cuda:0")
    args = parser.parse_args()
    report = audit_stage1(args.root, args.variant, embedding_device=args.embedding_device)
    write_json(args.root / "acceptance.json", report)
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
