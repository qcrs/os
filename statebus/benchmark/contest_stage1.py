"""Ordered contest chains: Stage 1 subsets and opt-in Stage 3/A (40 executions)."""
from __future__ import annotations

import argparse
from dataclasses import replace
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

from statebus.benchmark.contest_stage1_taskpack import SEED, FAMILIES, TASK_PERIODS, generate_sealed, files_for, make_case
from statebus.benchmark.contest_stage1_scorer import score_rows
from statebus.benchmark.request_journal import summarize_journal
from statebus.benchmark.contest_stage1_report import (
    REPORT_CONTRACT_VERSION, REPORT_INSTRUCTIONS, report_errors, report_feedback, report_sources, text_statements,
)
from statebus.benchmark.contest_metrics import record_handoff, handoff_measurement, unified_metrics, aggregate_metrics
from statebus.utils import stable_json_dumps

PROFILES = ("SB-FULL", "P-TEXT")
# Outer watchdog includes interpreter/model initialization, planner retries,
# sandbox repairs and report/citation retries, not just Runtime dispatch budget.
TASK_TIMEOUT_S = 1800
# Execution IDs only. Original task definitions/scorers are deliberately unchanged.
CHECKPOINT_SOURCES = {f"{prefix}{index}": f"{prefix}09" for prefix in FAMILIES for index in (11, 12)}
EXECUTION_TASKS = (*TASK_PERIODS, *CHECKPOINT_SOURCES)


def business_task_id(task_id):
    return CHECKPOINT_SOURCES.get(task_id, task_id)


def checkpoint_case(root, task_id, history):
    """Recheck an own-chain verified task, not an oracle or a result-cache shortcut."""
    source_id = business_task_id(task_id)
    producer = root.parent / source_id
    prior = next((item for item in history if item["task_id"] == source_id and item["ok"]), None)
    if prior is None:
        raise ValueError("checkpoint_requires_verified_producer:" + source_id)
    # Include every producer-visible raw file, dictionary and note. Comparing
    # bound numeric rows alone would miss edits to public prose or definitions.
    source_files = {str(path.relative_to(producer / "public")): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (producer / "public").rglob("*") if path.is_file()}
    if any(not (root / "public" / name).is_file()
           or hashlib.sha256((root / "public" / name).read_bytes()).hexdigest() != digest
           for name, digest in source_files.items()):
        raise ValueError("checkpoint_input_or_contract_changed")
    original = make_case(producer / "public", source_id)
    current = make_case(root / "public", source_id)
    if current.source_rows != original.source_rows or current.operation_semantics != original.operation_semantics:
        raise ValueError("checkpoint_input_or_contract_changed")
    if not score_rows(producer / "public", source_id, prior["output_rows"])["passed"]:
        raise ValueError("checkpoint_producer_failed_revalidation")
    # Keep canonical business identity and input bytes unchanged, while Runtime
    # receives a fresh execution ID. The normal Memory policy still decides reuse.
    case = replace(original, sample=replace(original.sample, task_id=task_id,
        request_text="Audit recheck of the same published business snapshot. " + original.sample.request_text))
    identity = {"checkpoint_of": source_id, "business_task_id": source_id,
                "canonical_task_spec_hash": original.spec.spec_hash,
                "source_files": source_files,
                "input_rows_sha256": hashlib.sha256(stable_json_dumps(original.source_rows).encode()).hexdigest(),
                "reuse_mode": "validated_program_replay_with_current_input_recomputation",
                "result_cache": False}
    return case, identity


def checkpoint_evidence(summary):
    """Observe Runtime receipts and actual requests; never infer success from a hit."""
    records = summary.get("memory_consumption_records", [])
    approved = {item["memory_id"] for query in summary.get("memory_query_results", [])
                for item in query.get("compatibility_decisions", []) if item.get("policy_approved")}
    replay = [item for item in records if item.get("memory_id") in approved
              and item.get("recipe_step_status") == "skipped_generation"
              and item.get("recipe_recomputed") and item.get("replay_eligibility_receipt_hash")]
    requests = summary.get("metrics", {}).get("executor_request_count")
    return {"quality_passed": bool(summary.get("ok")), "executor_request_count": requests,
            "policy_approved": bool(replay), "consumption_count": len(replay),
            "memory_ids": [item["memory_id"] for item in replay],
            "positive_replay_observed": bool(summary.get("ok") and requests == 0 and replay),
            "work_avoided": "executor_code_generation_only" if replay else "not_observed",
            "input_recomputed": bool(replay), "result_cache": False}



def execution_variant(profile, sb_memory_policy):
    return {"configuration_label": "SB-NO-MEMORY" if profile == "SB-FULL" and sb_memory_policy == "none" else profile,
            "memory_policy": sb_memory_policy if profile == "SB-FULL" else "none"}


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")
    temporary.replace(path)


def publish(sealed: Path, public: Path, task_id: str) -> list[dict]:
    records = []
    for source in files_for(sealed, business_task_id(task_id)):
        target = public / source.relative_to(sealed)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise ValueError("published_file_changed:" + str(target))
        if not target.exists():
            shutil.copyfile(source, target)
        records.append({"path": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    return records


def task_budget() -> dict:
    return {"outer_watchdog_s": TASK_TIMEOUT_S, "runtime_dispatch_budget_ms": 400000,
            "role_http_timeout_s": 90, "role_worker_timeout_s": 105, "provider_max_attempts": 1,
            "python_timeout_s": 30, "python_repairs": {"policy": 1, "runtime": 1, "quality": 1},
            "code_max_tokens": 2200,
            "note": "outer watchdog includes planner, initialization and bounded repairs; dispatch deadlines remain enforced"}


def effective_configuration(model_context_tokens=None):
    """Resolve the same role/provider settings for dry-run and actual workers."""
    import yaml
    configuration = yaml.safe_load(Path(os.environ["STATEBUS_LLM_CONFIG_FILE"]).read_text())
    for provider in configuration["providers"].values():
        provider.update(timeout_s=90, request_max_attempts=1)
    configuration["roles"]["executor"]["max_tokens"] = 2200
    if model_context_tokens is not None:
        context_tokens = int(model_context_tokens)
        if context_tokens <= 0:
            raise ValueError("model_context_tokens_must_be_positive")
        for values in configuration["roles"].values():
            values["max_context_tokens"] = context_tokens
            values["max_context_safety_margin_tokens"] = 128
    # The worker supports explicit role overrides; honor them in both paths.
    for role, values in configuration["roles"].items():
        override = os.getenv(f"STATEBUS_ADAPTIVE_{role.upper()}_MAX_TOKENS")
        if override:
            values["max_tokens"] = int(override)
    return configuration


def effective_budget(configuration):
    return {**task_budget(), "code_max_tokens": configuration["roles"]["executor"]["max_tokens"], "roles": {
        role: {"model": values["model"], "max_tokens": values["max_tokens"],
               **({"max_context_tokens": values["max_context_tokens"],
                   "max_context_safety_margin_tokens": values.get("max_context_safety_margin_tokens", 64)}
                  if values.get("max_context_tokens") is not None else {}),
               "timeout_s": configuration["providers"][values["provider"]]["timeout_s"]}
        for role, values in configuration["roles"].items()}}


def final_history_context(history, public, task_id):
    """Read this chain's verified outputs, never reference answers or other profiles."""
    if task_id not in {"F10", "O10"}:
        return "", ()
    expected_ids = [f"{task_id[0]}{index:02d}" for index in range(1, 10)]
    if [item["task_id"] for item in history] != expected_ids or not all(item["ok"] for item in history):
        raise ValueError("final_round_requires_nine_verified_predecessors")
    # Revalidate the stored outputs against published source before making them visible.
    for item in history:
        if not score_rows(public, item["task_id"], item["output_rows"])["passed"]:
            raise ValueError("history_failed_revalidation:" + item["task_id"])
    # Keep useful monthly/weekly and budget/P95 fields, not entire previous prompts.
    fields = {"unit_id", "site_id", "net_revenue_cny", "profit_cny", "margin_pct", "error_rate_pct",
              "attainment_pct", "under_budget", "p95_latency_ms", "exceeds_slo", "below_20_pct", "risk_change",
              "growth_pct", "decline_rank", "error_rate_delta_pp", "deterioration_rank",
              "note_locator", "event_locator"}
    records = tuple({"task_id": item["task_id"], "rows": [
        {key: value for key, value in row.items() if key in fields} for row in item["output_rows"]
    ]} for item in history)
    instructions = (
        " This is the closing report of the SAME continuous chain. The supplied own-profile historical_results "
        "are prior verified outputs, not answers for the current task. Cross-check them with the newly verified "
        "full-period table. In EACH entity's statement include history_sources=" + ",".join(expected_ids) +
        ". Historical context is evidence of prior rounds, not a Memory API consumption claim."
    )
    return instructions, records


def execute_worker(args):
    from statebus.benchmark.adaptive_formal_mainline import _run_adaptive_case
    from statebus.benchmark.contest_stage1_text import run_text
    from statebus.contracts import ReplayClass
    root = args.output_root.resolve()
    variant = execution_variant(args.profile, args.sb_memory_policy)
    public = root / "public"
    history = json.loads((root / "history-before.json").read_text())
    business_task = business_task_id(args.task)
    checkpoint = None
    if args.task in CHECKPOINT_SOURCES:
        case, checkpoint = checkpoint_case(root, args.task, history)
        write_json(root / "checkpoint-identity.json", checkpoint)
    else:
        case = make_case(public, args.task)
    # Both profiles receive exactly the same explicit business report contract.
    # Ordinary reviews recompute from the released raw periods. The closing
    # report additionally receives its own nine verified predecessor outputs
    # below; no reference answers or other profile's results enter the prompt.
    case = replace(case, sample=replace(case.sample, request_text=(
        case.sample.request_text + " " + REPORT_INSTRUCTIONS
    )))
    write_json(root / "public-task.json", {"task_id": args.task, "request": case.sample.request_text,
                                          "spec": case.spec.canonical_payload(), "history": history,
                                          "report_contract_version": REPORT_CONTRACT_VERSION,
                                          "source_schema": case.source_schema, "source_rows": len(case.source_rows)})
    os.environ["STATEBUS_PROVIDER_JOURNAL"] = str(root / "provider.jsonl")
    os.environ["STATEBUS_ADAPTIVE_ROLE_HTTP_TIMEOUT_S"] = "90"
    os.environ["STATEBUS_ADAPTIVE_ROLE_WORKER_TIMEOUT_S"] = "105"
    # Existing raw-CodeAct caller derives provider timeout from the file; use a
    # local per-task copy, never mutate the shared deployment configuration.
    import yaml
    configuration = effective_configuration(getattr(args, "model_context_tokens", None))
    os.environ["STATEBUS_ADAPTIVE_FORMAL_CODE_MAX_TOKENS"] = str(configuration["roles"]["executor"]["max_tokens"])
    effective = root / "effective-llm.yaml"
    effective.write_text(yaml.safe_dump(configuration))
    os.environ["STATEBUS_LLM_CONFIG_FILE"] = str(effective)
    write_json(root / "effective-budget.json", effective_budget(configuration))
    write_json(root / "execution-environment.json", {
        "python": sys.executable, "python_version": sys.version,
        "embedding_device": args.embedding_device, "embedding_model_path": args.embedding_model_path,
        "profile": args.profile, "embedding_used": args.profile == "SB-FULL",
        **variant,
        "declared_helper_device": os.getenv("STATEBUS_EMBED_DEVICE"),
    })
    current_notes = files_for(public, business_task)[-1]
    notes = current_notes.read_text()
    sources = report_sources(notes, source_name=current_notes.name, period=TASK_PERIODS[business_task],
                             entities=case.spec.target_entities)
    history_instructions, history_records = final_history_context(history, public, args.task)
    report_instructions = REPORT_INSTRUCTIONS + history_instructions
    base_validator = partial(report_errors, sources=sources)
    def validate_report(rows, statements, *, evidence_items=None):
        errors = base_validator(rows, statements, evidence_items=evidence_items)
        if history_records:
            import re
            required = "history_sources=" + ",".join(item["task_id"] for item in history_records)
            for row in rows:
                entity = row.get("unit_id", row.get("site_id"))
                bodies = [str(item.get("claim_text", "")) for item in statements
                          if re.search(r"(?<![\w-])" + re.escape(entity) + r"(?![\w-])", str(item.get("claim_text", "")))]
                if len(bodies) != 1 or required not in bodies[0]:
                    errors.append("report_history_sources:" + entity)
        return errors
    write_json(root / "history-input.json", {"scope": "own_profile_verified_outputs_not_memory_api", "records": history_records})
    # Existing Markdown retrieval supports real semantic state without changing
    # the business task family or using a preview of only the first CSV rows.
    retrieval_spec = replace(case.spec, task_family="continuous_long_doc_table_analysis",
                             arguments={"dataset_id": case.sample.dataset_id, "document_path": str(current_notes)},
                             target_entities=(), time_scope="")
    if args.profile == "SB-FULL":
        def handoff(sender, receiver, payload):
            record_handoff(root / "handoffs.jsonl", sender, receiver, payload=payload,
                           scope="actual_callback_input_projection_at_invocation_includes_controller_binding")
        summary = _run_adaptive_case(
            case, case_root=root / "execution", embedding_model_path=args.embedding_model_path,
            embedding_device=args.embedding_device, memory_store_root=root.parent / "memory",
            memory_policy=variant["memory_policy"], memory_commit_replay_class=ReplayClass.VALIDATED_REPLAY,
            memory_tags=(FAMILIES[args.task[0]], "stage1-development"),
            require_executor_model_role=variant["memory_policy"] == "none",
            result_scorer=lambda rows: score_rows(public, business_task, rows), retrieval_spec=retrieval_spec,
            retrieval_top_k=7, report_instructions=report_instructions, report_validator=validate_report,
            historical_results=history_records,
            report_feedback=report_feedback,
            handoff_observer=handoff,
        )
        summary["handoff_measurement"] = handoff_measurement(root)
    else:
        summary = run_text(case, root / "execution", notes=notes, source_name=current_notes.name, report_sources=sources,
                           historical_results=history_records, report_instructions=report_instructions,
                           report_validator=validate_report)
        summary["handoff_measurement"] = handoff_measurement(root)
    score = score_rows(public, business_task, summary.get("output_rows", []))
    rows = summary.get("output_rows", [])
    if args.profile == "SB-FULL":
        statements = [claim for claim_set in summary.get("claim_sets", []) for claim in claim_set["claims"]]
        errors = validate_report(rows, statements, evidence_items=summary.get("report_evidence_items", []))
        summary["summary_text"] = "\n".join(claim["claim_text"] for claim in statements)
    else:
        errors = validate_report(rows, text_statements(summary.get("summary_text", "")))
    score["business_report_errors"] = errors
    score["report_contract_version"] = REPORT_CONTRACT_VERSION
    score["report_quality_scope"] = "entity_risk_current_citation_and_verbatim_context_not_general_entailment"
    score["semantic_review_required"] = True
    score["passed"] = bool(score["passed"] and not errors)
    write_json(root / "scorer.json", score)
    summary["ok"] = bool(summary.get("ok") and score["passed"])
    summary["external_score_passed"] = score["passed"]
    summary.update(variant, task_id=args.task, profile=args.profile,
                   report_contract_version=REPORT_CONTRACT_VERSION, semantic_review_required=True)
    summary["control_wire_bytes"] = None
    summary["control_wire_missing_reason"] = "no ExecutorTransportAudit captured on this adaptive/text caller; global network bytes unsupported"
    summary["metrics"] = unified_metrics(summary, root)
    if checkpoint is not None:
        summary["checkpoint"] = {**checkpoint, **checkpoint_evidence(summary)}
    write_json(root / "result.json", summary)
    return 0 if summary["ok"] else 1


def run(args):
    requested_tasks = getattr(args, "chain_tasks", None)
    task_ids = tuple(requested_tasks) if requested_tasks else None
    main_chain = bool(getattr(args, "main_chain", False))
    checkpoint_rounds = int(getattr(args, "checkpoint_rounds", 0))
    if checkpoint_rounds not in (0, 1, 2):
        raise ValueError("checkpoint_rounds_must_be_0_1_or_2")
    if checkpoint_rounds and not main_chain:
        raise ValueError("checkpoint_rounds_requires_main_chain")
    scope = f"main_chain_{20 + 2 * checkpoint_rounds}_tasks" if main_chain else ("explicit_development_chain" if task_ids else "stage1_development_only")
    if main_chain and task_ids is not None:
        raise ValueError("main_chain_cannot_override_task_list")
    if main_chain and task_ids is None:
        task_ids = tuple(f"{prefix}{index:02d}" for prefix in FAMILIES for index in range(1, 11 + checkpoint_rounds))
    if task_ids:
        if len(set(task_ids)) != len(task_ids) or any(task not in EXECUTION_TASKS for task in task_ids):
            raise ValueError("invalid_or_duplicate_chain_tasks")
        for prefix in FAMILIES:
            chain_tasks = [task for task in task_ids if task.startswith(prefix)]
            if chain_tasks != sorted(chain_tasks) or (prefix + "02" in chain_tasks and prefix + "01" not in chain_tasks):
                raise ValueError("chain_tasks_require_ordered_prior_batch")
        for task in task_ids:
            if task in CHECKPOINT_SOURCES and business_task_id(task) not in task_ids:
                raise ValueError("checkpoint_requires_producer_in_chain:" + task)
    plan = [{"family": family, "profile": profile, "task_id": task,
             **execution_variant(profile, args.sb_memory_policy)}
            for prefix, family in FAMILIES.items() if args.family in {"all", family}
            for profile in PROFILES if args.profile in {"both", profile}
            for task in (task_ids or (f"{prefix}01", f"{prefix}02"))
            if task.startswith(prefix)]
    if args.dry_run:
        # Keep the historical no-argument configuration hook usable by
        # callers/tests that provide only the minimal runner namespace.  The
        # CLI parser always supplies ``model_context_tokens`` and therefore
        # still gets the context-aware budget in its plan output.
        model_context_tokens = getattr(args, "model_context_tokens", None)
        configuration = (
            effective_configuration(model_context_tokens)
            if model_context_tokens is not None
            else effective_configuration()
        )
        payload = {"scope": scope, "checkpoint_rounds": checkpoint_rounds, "seed": SEED, "plan": plan,
                                 "report_contract_version": REPORT_CONTRACT_VERSION,
                                 "planned_count": len(plan), "output_root": str(args.output_root.resolve()),
                                 "budget": effective_budget(configuration), "embedding_device": args.embedding_device,
                                 "embedding_model_path": args.embedding_model_path}
        if args.plan_output is not None:
            write_json(args.plan_output, payload)
        print(stable_json_dumps(payload))
        return 0
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    started = time.monotonic_ns()
    generate_sealed(root / "sealed")
    ledger = [{**item, "status": "not_started", "ok": False, "elapsed_ms": None, "provider": None} for item in plan]
    write_json(root / "ledger.json", ledger)
    histories = {}
    chain_starts = {}
    chain_ends = {}
    failed_chains = set()
    halted = False
    for index, item in enumerate(plan):
        key = item["family"] + "/" + item["configuration_label"]
        if key in failed_chains:
            ledger[index].update(status="blocked_by_prior_failure", reason="producer_or_prior_round_failed")
            continue
        if halted:
            continue
        chain = root / item["family"] / item["configuration_label"]
        task = chain / item["task_id"]
        before = time.monotonic_ns()
        chain_starts.setdefault(key, before)
        task.mkdir(parents=True)
        public = task / "public"
        previous = histories.setdefault(key, [])
        for prior_task in previous:
            publish(root / "sealed", public, prior_task["task_id"])
        releases = publish(root / "sealed", public, item["task_id"])
        write_json(task / "release.json", {"current_release": releases,
                                          "visible_files": sorted(str(p.relative_to(public)) for p in public.rglob("*") if p.is_file())})
        write_json(task / "history-before.json", previous)
        ledger[index].update(status="running", start_ns=before)
        write_json(root / "ledger.json", ledger)
        command = [sys.executable, "-m", __name__, "--worker", "--task", item["task_id"],
                   "--profile", item["profile"], "--output-root", str(task),
                   "--sb-memory-policy", args.sb_memory_policy,
                   "--embedding-model-path", args.embedding_model_path, "--embedding-device", args.embedding_device]
        model_context_tokens = getattr(args, "model_context_tokens", None)
        if model_context_tokens is not None:
            command.extend(("--model-context-tokens", str(model_context_tokens)))
        # __name__ is __main__ under -m; use the stable module entrypoint.
        command[2] = "statebus.benchmark.contest_stage1"
        print(stable_json_dumps({"stage": "starting", **item, "root": str(task)}), flush=True)
        with (task / "worker.log").open("w") as log:
            worker = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                returncode = worker.wait(timeout=TASK_TIMEOUT_S)
                status = "success" if returncode == 0 else "failed"
            except subprocess.TimeoutExpired:
                # Only terminate this runner-owned process group, never shared services.
                import signal
                os.killpg(worker.pid, signal.SIGTERM)
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(worker.pid, signal.SIGKILL); worker.wait()
                returncode, status = None, "timeout"
        end = time.monotonic_ns()
        result = json.loads((task / "result.json").read_text()) if (task / "result.json").exists() else {}
        failure = json.loads((task / "failure.json").read_text()) if (task / "failure.json").exists() else None
        if not result:
            # Every attempted task has a machine-readable terminal result,
            # including startup errors and watchdog termination.
            result = {"ok": False, "status": status, "failure": failure,
                      "error": "outer_watchdog_timeout" if status == "timeout" else "worker_failed_before_result",
                      "output_rows": [], "quality_observed": False}
            write_json(task / "result.json", result)
        provider = summarize_journal(task / "provider.jsonl")
        result["metrics"] = unified_metrics(result, task, status=status)
        result["handoff_measurement"] = handoff_measurement(task)
        write_json(task / "result.json", result)
        entry = ledger[index]
        entry.update(status=status, ok=status == "success" and result.get("ok", False),
                     elapsed_ms=(end-before)/1e6, returncode=returncode, provider=provider,
                     result_path=str(task / "result.json"), log_path=str(task / "worker.log"),
                     metrics=result.get("metrics", {}))
        if not entry["ok"]:
            entry.update(
                error=(failure or {}).get("error") or result.get("error") or "worker_task_failed",
                failure_path=str(task / "failure.json") if failure else None,
            )
        if "checkpoint" in result:
            entry["checkpoint"] = result["checkpoint"]
        previous.append({"task_id": item["task_id"], "ok": entry["ok"], "status": status,
                         "output_rows": result.get("output_rows", []) if entry["ok"] else [],
                         "summary": result.get("summary_text", "") if entry["ok"] else ""})
        write_json(root / "ledger.json", ledger)
        chain_ends[key] = end
        print(stable_json_dumps({"stage": "finished", **entry}), flush=True)
        if not entry["ok"]:
            if main_chain or getattr(args, "block_failed_chain", False):
                failed_chains.add(key)
            halted = bool(getattr(args, "stop_on_failure", False))
    write_json(root / "ledger.json", ledger)
    summary = {"scope": scope if main_chain or task_ids else "basic_subset_only_not_full_G0_G1", "checkpoint_rounds": checkpoint_rounds, "planned_count": len(plan),
               "passed_count": sum(e["ok"] for e in ledger), "ledger": ledger,
               "e2e_ms": (time.monotonic_ns()-started)/1e6,
               "chains_ms": {k: (chain_ends[k]-v)/1e6 for k, v in chain_starts.items()},
               "generation_seed": SEED, "formal_headline_eligible": False,
               "report_contract_version": REPORT_CONTRACT_VERSION, "semantic_review_required": True,
               "global_wire_bytes": None, "global_wire_bytes_reason": "not_instrumented",
               "inter_agent_token_count": aggregate_metrics(ledger)["handoff_tokens"],
               "inter_agent_token_reason": "logical callback payload tokenization; per-edge scope, not physical wire bytes"}
    summary["metric_totals"] = aggregate_metrics(ledger)
    summary["chain_results"] = [{"family": family, "profile": profile,
        "planned_count": len(entries), "attempted_count": sum(e["status"] in {"success", "failed", "timeout"} for e in entries),
        "passed_count": sum(e["ok"] for e in entries), "completed_ten_rounds": len([e for e in entries if e["task_id"] not in CHECKPOINT_SOURCES]) == 10 and all(e["ok"] for e in entries if e["task_id"] not in CHECKPOINT_SOURCES),
        "completed_all_rounds": all(e["ok"] for e in entries),
        "elapsed_ms": summary["chains_ms"].get(f"{family}/{profile}"), "metrics": aggregate_metrics(entries)}
        for family, profile in dict.fromkeys((e["family"], e["configuration_label"]) for e in ledger)
        for entries in [[e for e in ledger if (e["family"],e["configuration_label"]) == (family,profile)]]]
    summary["main_chain_completed"] = main_chain and len(plan) == 4 * (10 + checkpoint_rounds) and all(e["ok"] for e in ledger)
    summary["base_campaign"] = {"planned_count": sum(e["task_id"] not in CHECKPOINT_SOURCES for e in ledger),
                                "passed_count": sum(e["ok"] and e["task_id"] not in CHECKPOINT_SOURCES for e in ledger)}
    summary["checkpoint_results"] = [e for e in ledger if e["task_id"] in CHECKPOINT_SOURCES]
    summary["checkpoint_costs"] = []
    for chain_result in summary["chain_results"]:
        entries = [e for e in ledger if (e["family"], e["configuration_label"]) ==
                   (chain_result["family"], chain_result["profile"])]
        rechecks = [e for e in entries if e["task_id"] in CHECKPOINT_SOURCES]
        if rechecks:
            producer_ids = {business_task_id(e["task_id"]) for e in rechecks}
            producers = [e for e in entries if e["task_id"] in producer_ids]
            def costs(items):
                times = [e["elapsed_ms"] for e in items]
                return {"planned_count": len(items), "passed_count": sum(e["ok"] for e in items),
                        "elapsed_ms": sum(times) if all(t is not None for t in times) else None,
                        "metrics": aggregate_metrics(items)}
            summary["checkpoint_costs"].append({"family": chain_result["family"], "profile": chain_result["profile"],
                "producer": costs(producers), "rechecks": costs(rechecks), "combined": costs(producers + rechecks)})
    write_json(root / "summary.json", summary)
    return 0 if summary["passed_count"] == len(plan) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--plan-output", type=Path, help="write clean plan JSON during --dry-run")
    parser.add_argument("--profile", choices=("both", *PROFILES), default="both")
    parser.add_argument("--family", choices=("all", *FAMILIES.values()), default="all")
    parser.add_argument("--sb-memory-policy", choices=("none", "validated_replay"), default="validated_replay",
                        help="SB only: none runs the SB-NO-MEMORY mechanism variant; P-TEXT remains memory-free")
    parser.add_argument("--embedding-model-path", default=os.getenv("STATEBUS_EMBED_MODEL_PATH", "/statebus/models/Qwen3-Embedding-0.6B"))
    parser.add_argument("--embedding-device", default=os.getenv("STATEBUS_EMBED_DEVICE", "cuda:0"))
    parser.add_argument("--model-context-tokens", type=int,
                        default=(int(os.environ["STATEBUS_VLLM_MAX_MODEL_LEN"])
                                 if os.getenv("STATEBUS_VLLM_MAX_MODEL_LEN") else None),
                        help="Serving context limit; caps each role's completion budget against the current prompt")
    parser.add_argument("--chain-tasks", nargs="+", choices=EXECUTION_TASKS,
                        help="Ordered development tasks; F06/O06 use the v2 definitions")
    parser.add_argument("--main-chain", action="store_true", help="run the ordered F01-F10 and O01-O10 campaign")
    parser.add_argument("--checkpoint-rounds", type=int, choices=(0, 1, 2), default=0,
                        help="append 1 or 2 audit rechecks per main chain; original ten rounds unchanged")
    parser.add_argument("--block-failed-chain", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--task", choices=EXECUTION_TASKS, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.plan_output is not None and not args.dry_run:
        parser.error("--plan-output requires --dry-run")
    if args.worker:
        if args.profile not in PROFILES or args.task is None:
            parser.error("worker requires task and one profile")
        try:
            code = execute_worker(args)
        except Exception as exc:
            write_json(args.output_root / "failure.json", {"type": type(exc).__name__, "error": str(exc), "traceback": traceback.format_exc()})
            traceback.print_exc(); code = 1
    else:
        code = run(args)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
