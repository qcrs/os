from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml
from eval.runner import run_benchmark
from memory.store import DeterministicEmbeddingProvider
from runtime.llm import LLMConfig
from tasks.sample_tasks import load_task_set_bundle

DEFAULT_LLM_CONFIG = "deploy/statebus_llm.yaml.local"
DEFAULT_PYTEST_EXPR = (
    "planner_support_v3 or validate_gate or typed_state_mechanism_v3 or "
    "wrong_family or contest_dual_mode_controlled_v3_repeat_one_does_not_pass_formal_stability_gate"
)


@dataclass(frozen=True)
class SmokeBlock:
    name: str
    source_task_set: str
    description: str
    task_ids: tuple[str, ...]
    modes: tuple[str, ...]


SMOKE_BLOCKS: tuple[SmokeBlock, ...] = (
    SmokeBlock(
        name="contest_headline_guard",
        source_task_set="contest_honest_headline_v1",
        description=(
            "Contest-facing honest headline probe. Mirrors the full formal headline family/bucket "
            "surface at repeat=1 so wrong-family collapse, headline guard drift, template-slot "
            "leakage, and reusable-case risks can be scanned before formal repeat evidence."
        ),
        task_ids=(
            "rr-auth-clean-text-001",
            "rr-auth-clean-protocol-001",
            "rr-auth-distractor-text-001",
            "rr-auth-distractor-protocol-001",
            "rr-auth-ambiguous-text-001",
            "rr-auth-ambiguous-protocol-001",
            "rr-auth-replay_reusable-text-001",
            "rr-auth-replay_reusable-protocol-001",
            "rr-billing-clean-text-001",
            "rr-billing-clean-protocol-001",
            "rr-billing-distractor-text-001",
            "rr-billing-distractor-protocol-001",
            "rr-billing-ambiguous-text-001",
            "rr-billing-ambiguous-protocol-001",
            "rr-checkout-clean-text-001",
            "rr-checkout-clean-protocol-001",
            "rr-checkout-distractor-text-001",
            "rr-checkout-distractor-protocol-001",
            "rr-checkout-ambiguous-text-001",
            "rr-checkout-ambiguous-protocol-001",
            "rr-checkout-replay_reusable-text-001",
            "rr-checkout-replay_reusable-protocol-001",
            "rr-deploy-clean-text-001",
            "rr-deploy-clean-protocol-001",
            "rr-deploy-distractor-text-001",
            "rr-deploy-distractor-protocol-001",
            "rr-deploy-ambiguous-text-001",
            "rr-deploy-ambiguous-protocol-001",
            "rr-deploy-replay_reusable-text-001",
            "rr-deploy-replay_reusable-protocol-001",
            "rr-cache-clean-text-001",
            "rr-cache-clean-protocol-001",
            "rr-cache-distractor-text-001",
            "rr-cache-distractor-protocol-001",
            "rr-cache-ambiguous-text-001",
            "rr-cache-ambiguous-protocol-001",
            "rr-cache-replay_reusable-text-001",
            "rr-cache-replay_reusable-protocol-001",
            "rr-billing-replay_reusable-text-001",
            "rr-billing-replay_reusable-protocol-001",
        ),
        modes=("text", "protocol"),
    ),
    SmokeBlock(
        name="contest_controlled_guard",
        source_task_set="contest_dual_mode_controlled_v3",
        description=(
            "Internal controlled composite probe. Keeps text_strict_pure_lane/state_packet_minimal "
            "rows available for contrast so report/gate drift can be spotted without rereading it as "
            "the contest-facing headline."
        ),
        task_ids=(
            "rr-auth-distractor-text-001",
            "rr-auth-distractor-protocol-001",
            "rr-cache-distractor-text-001",
            "rr-cache-distractor-protocol-001",
        ),
        modes=("text", "protocol"),
    ),
    SmokeBlock(
        name="typed_state_fairness",
        source_task_set="typed_state_mechanism_v3",
        description=(
            "Mechanism fairness probe. Holds task semantics fixed and compares "
            "natural_handoff_text vs state_packet_minimal on clean and distractor rows."
        ),
        task_ids=(
            "rr-checkout-clean-natural-handoff-001",
            "rr-checkout-clean-state-packet-101",
            "rr-checkout-distractor-natural-handoff-001",
            "rr-checkout-distractor-state-packet-101",
        ),
        modes=("protocol",),
    ),
    SmokeBlock(
        name="planner_validate",
        source_task_set="planner_support_v3",
        description=(
            "Planner/validate probe. Focuses on llm-generated plans that should either continue "
            "cleanly or gate-block before execute, exposing planner reporting and validate semantics."
        ),
        task_ids=(
            "planner-support-checkout-llm-001",
            "planner-support-deploy-llm-001",
            "planner-support-auth-llm-002",
        ),
        modes=("protocol",),
    ),
    SmokeBlock(
        name="memory_contract",
        source_task_set="memory_dual_mode_fairness_v3",
        description=(
            "Dual-mode memory contract probe. Covers cold-start, assist, and validated replay under "
            "matched text/protocol rows on the same family."
        ),
        task_ids=(
            "memory-dual-01-cold_start-text-001",
            "memory-dual-01-cold_start-protocol-001",
            "memory-dual-01-assist-text-001",
            "memory-dual-01-assist-protocol-001",
            "memory-dual-01-validated_replay-text-001",
            "memory-dual-01-validated_replay-protocol-001",
        ),
        modes=("text", "protocol"),
    ),
    SmokeBlock(
        name="consumer_negative_controls",
        source_task_set="tasks/state_ref_consumer_sensitivity_audit_benchmark.yaml",
        description=(
            "Destructive negative-control probe. Confirms wrong or missing EXECUTOR_DECISION_PACKET "
            "degrades mainline behavior instead of being silently healed."
        ),
        task_ids=(
            "audit-sensitivity-rich-full-001",
            "audit-sensitivity-minimal-baseline-001",
            "audit-sensitivity-minimal-missing-decision-001",
            "audit-sensitivity-minimal-wrong-decision-001",
        ),
        modes=("protocol",),
    ),
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a block-structured StateBus issue-discovery smoke suite.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory. Default: runs/issue_discovery_smoke_<timestamp>",
    )
    parser.add_argument(
        "--llm-config",
        default=DEFAULT_LLM_CONFIG,
        help="LLM config file for API mode.",
    )
    parser.add_argument(
        "--llm-mode",
        choices=("api", "deterministic"),
        default="api",
        help="LLM mode. Default: api.",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip targeted pytest and runtime.smoke gates.",
    )
    parser.add_argument(
        "--blocks",
        default="all",
        help="Comma-separated block names to run, or 'all'.",
    )
    parser.add_argument(
        "--pytest-expr",
        default=DEFAULT_PYTEST_EXPR,
        help="Pytest -k expression for the gate phase.",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    out_dir = Path(args.out) if args.out else _default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    selected_blocks = _select_blocks(args.blocks)

    if not args.skip_tests:
        _run_gate_checks(out_dir=out_dir, pytest_expr=args.pytest_expr)

    llm_config = LLMConfig.from_runtime(args.llm_config).with_mode(args.llm_mode)
    _write_suite_readme(out_dir=out_dir, blocks=selected_blocks, args=args)

    block_reports: list[dict[str, Any]] = []
    for block in selected_blocks:
        task_set_path = _write_block_task_set(block=block, out_dir=out_dir)
        block_out = out_dir / "benchmarks" / block.name
        block_out.mkdir(parents=True, exist_ok=True)
        print(f"[issue_discovery_smoke] start block={block.name}", flush=True)
        result = asyncio.run(
            run_benchmark(
                task_set_path=task_set_path,
                repeat=1,
                modes=block.modes,
                out_dir=block_out,
                embedder=DeterministicEmbeddingProvider(),
                llm_config=llm_config,
                progress_callback=None,
            )
        )
        block_report = _build_block_report(block=block, result=result, block_out=block_out)
        block_reports.append(block_report)
        (block_out / "issue_smoke_summary.json").write_text(
            json.dumps(block_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    suite_report = {
        "suite": "issue_discovery_smoke",
        "out_dir": str(out_dir),
        "blocks": block_reports,
    }
    (out_dir / "issue_smoke_summary.json").write_text(
        json.dumps(suite_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "ISSUE_SMOKE_SUMMARY.md").write_text(
        _render_suite_markdown(out_dir=out_dir, block_reports=block_reports),
        encoding="utf-8",
    )
    print(f"[issue_discovery_smoke] done out_dir={out_dir}", flush=True)


def _default_out_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return REPO_ROOT / "runs" / f"issue_discovery_smoke_{stamp}"


def _select_blocks(raw: str) -> list[SmokeBlock]:
    if raw.strip().lower() == "all":
        return list(SMOKE_BLOCKS)
    requested = [part.strip() for part in raw.split(",") if part.strip()]
    available = {block.name: block for block in SMOKE_BLOCKS}
    missing = [name for name in requested if name not in available]
    if missing:
        raise SystemExit(f"unsupported blocks: {', '.join(missing)}")
    return [available[name] for name in requested]


def _run_gate_checks(*, out_dir: Path, pytest_expr: str) -> None:
    log_dir = out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    commands = [
        (
            "targeted_pytest",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_llm_runtime.py",
                "tests/test_state_channels_and_graph.py",
                "tests/test_smoke.py",
                "-k",
                pytest_expr,
            ],
        ),
        (
            "runtime_smoke",
            [sys.executable, "-m", "runtime.smoke"],
        ),
    ]
    for label, command in commands:
        _run_logged_command(
            label=label,
            command=command,
            out_path=log_dir / f"{label}.log",
        )


def _run_logged_command(*, label: str, command: list[str], out_path: Path) -> None:
    print(f"[issue_discovery_smoke] gate={label}", flush=True)
    print(f"[issue_discovery_smoke] cmd={shlex.join(command)}", flush=True)
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    out_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise SystemExit(f"{label} failed with exit code {completed.returncode}; see {out_path}")


def _write_suite_readme(*, out_dir: Path, blocks: list[SmokeBlock], args: argparse.Namespace) -> None:
    lines = [
        "StateBus issue-discovery smoke",
        "",
        "Contract:",
        "- This suite is for fast issue discovery and flow/report correctness checks.",
        "- It intentionally uses small task samples to cover more failure modes per minute.",
        "- It is not formal repeat stability evidence and not a headline publication surface.",
        "- Blocks are chosen to isolate logic classes: contest headline guard, internal controlled contrast, typed-state fairness, planner/validate, memory contract, and destructive negative controls.",
        "",
        f"LLM mode: {args.llm_mode}",
        f"LLM config: {args.llm_config}",
        f"Selected blocks: {', '.join(block.name for block in blocks)}",
    ]
    (out_dir / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_block_task_set(*, block: SmokeBlock, out_dir: Path) -> Path:
    bundle = load_task_set_bundle(block.source_task_set)
    selected = [task for task in bundle.tasks if task.task_id in set(block.task_ids)]
    missing = [task_id for task_id in block.task_ids if task_id not in {task.task_id for task in selected}]
    if missing:
        raise SystemExit(f"{block.name}: missing task ids: {missing}")

    metadata = {
        "name": f"{bundle.metadata.name}__{block.name}",
        "pack_type": bundle.metadata.pack_type,
        "description": block.description,
        "reading_contract": bundle.metadata.description or "",
        "claim_lanes": list(bundle.metadata.claim_lanes),
        "single_variable": bundle.metadata.single_variable,
        "variable_axes": list(bundle.metadata.variable_axes),
        "public_surface": bundle.metadata.public_surface,
        "plan_source_default": bundle.metadata.plan_source_default,
        "evidence_tier": bundle.metadata.evidence_tier,
        "benchmark_version": bundle.metadata.benchmark_version,
        "formal_structure_clean_retrieval": bundle.metadata.formal_structure_clean_retrieval,
    }
    tasks_payload = [_task_to_yaml_payload(task) for task in selected]
    task_set_path = out_dir / "task_sets" / f"{block.name}.yaml"
    task_set_path.parent.mkdir(parents=True, exist_ok=True)
    task_set_path.write_text(
        yaml.safe_dump({"task_set": metadata, "tasks": tasks_payload}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return task_set_path


def _task_to_yaml_payload(task: Any) -> dict[str, Any]:
    payload = {
        "task_id": task.task_id,
        "task_group": task.task_group,
        "task_order": task.task_order,
        "task_theme": task.task_theme,
        "goal": task.goal,
        "query": task.query,
        "tags": list(task.tags),
        "reuse_tags": list(task.reuse_tags),
        "summary_hint": task.summary_hint,
        "corpus_doc_ids": list(task.corpus_doc_ids),
        "corpus_path": task.corpus_path,
        "expected_reuse_mode": task.expected_reuse_mode,
        "benchmark_lane": task.benchmark_lane,
        "transfer_strategy": task.transfer_strategy,
        "handoff_profile": task.handoff_profile,
        "runtime_reuse_contract": task.runtime_reuse_contract,
        "evidence_text": task.evidence_text,
        "expected_route": task.expected_route,
        "expected_route_source": task.expected_route_source,
        "expected_tool_name": task.expected_tool_name,
        "expected_top_doc_id": task.expected_top_doc_id,
        "case_id": task.case_id,
        "case_type": task.case_type,
        "eval_scope": task.eval_scope,
        "expected_family": task.expected_family,
        "primary_expected_route": task.primary_expected_route,
        "primary_expected_tool": task.primary_expected_tool,
        "acceptable_routes": list(task.acceptable_routes),
        "acceptable_tools": list(task.acceptable_tools),
        "disallowed_families": list(task.disallowed_families),
        "required_prior_case_ids": list(task.required_prior_case_ids),
        "required_prior_routes": list(task.required_prior_routes),
        "required_prior_rejections": list(task.required_prior_rejections),
        "abstention_allowed": task.abstention_allowed,
        "allowed_abstain_tool": task.allowed_abstain_tool,
        "abstain_only_when": task.abstain_only_when,
        "allowed_modes": list(task.allowed_modes),
        "plan_source": task.plan_source,
        "complexity_bucket": task.complexity_bucket,
        "summary_contract": task.summary_contract,
    }
    if task.required_plan_semantic_roles:
        payload["required_plan_semantic_roles"] = list(task.required_plan_semantic_roles)
    if task.audit_disable_state_kinds:
        payload["audit_disable_state_kinds"] = list(task.audit_disable_state_kinds)
    if task.audit_decision_packet_override_route:
        payload["audit_decision_packet_override_route"] = task.audit_decision_packet_override_route
    if task.audit_decision_packet_override_tool_name:
        payload["audit_decision_packet_override_tool_name"] = task.audit_decision_packet_override_tool_name
    return payload


def _build_block_report(*, block: SmokeBlock, result: dict[str, Any], block_out: Path) -> dict[str, Any]:
    manifest = result.get("manifest", {})
    summary = result.get("summary", {})
    mode_runs = result.get("mode_runs", {})
    mode_reports: dict[str, Any] = {}
    for mode in block.modes:
        runs = mode_runs.get(mode, [])
        task_rows = runs[0]["tasks"] if runs else []
        mode_summary = summary.get(mode, {})
        aggregate = mode_summary.get("aggregate", {})
        case_audit = mode_summary.get("misfire_audit", {}).get("case_contract", {})
        transfer_truth = mode_summary.get("transfer_truth", {})
        guard_audit = mode_summary.get("guard_audit", {})
        mechanism_audit = mode_summary.get("mechanism_audit", {})
        memory_replay_gate = manifest.get("memory_replay_evidence_gate", {})
        mode_reports[mode] = {
            "aggregate": {
                "message_count": aggregate.get("message_count", 0.0),
                "task_ms": aggregate.get("task_ms", 0.0),
                "planner_ms": aggregate.get("planner_ms", 0.0),
                "retrieve_ms": aggregate.get("retrieve_ms", 0.0),
                "execute_ms": aggregate.get("execute_ms", 0.0),
                "summarize_ms": aggregate.get("summarize_ms", 0.0),
                "llm_total_tokens": aggregate.get("llm_total_tokens", 0.0),
                "planner_llm_request_count": aggregate.get("planner_llm_request_count", 0.0),
                "planned_step_count": aggregate.get("planned_step_count", 0.0),
                "expected_gate_block_count": aggregate.get("expected_gate_block_count", 0.0),
                "true_invariant_violation_count": aggregate.get("true_invariant_violation_count", 0.0),
                "assist_memory_hit_rate": aggregate.get("assist_memory_hit_rate", 0.0),
                "skipped_step_count": aggregate.get("skipped_step_count", 0.0),
                "reuse_gain": aggregate.get("reuse_gain", 0.0),
            },
            "case_contract": {
                "route_exact_rate": case_audit.get("route_exact_rate", 0.0),
                "tool_exact_rate": case_audit.get("tool_exact_rate", 0.0),
                "exact_match_rate": case_audit.get("exact_match_rate", 0.0),
                "admissible_match_rate": case_audit.get("admissible_match_rate", 0.0),
                "abstention_rate": case_audit.get("abstention_rate", 0.0),
                "wrong_family_rate": case_audit.get("wrong_family_rate", 0.0),
            },
            "memory_contract": {
                "assist_memory_hit_rate": aggregate.get("assist_memory_hit_rate", 0.0),
                "skipped_step_count": aggregate.get("skipped_step_count", 0.0),
                "reuse_gain": aggregate.get("reuse_gain", 0.0),
                "memory_replay_evidence_gate_passed": bool(memory_replay_gate.get("passed", False)),
                "memory_replay_expected_rows": int(memory_replay_gate.get("expected_rows", 0)),
                "memory_replay_matched_rows": int(memory_replay_gate.get("matched_rows", 0)),
            },
            "transfer_truth": {
                "typed_executor_any_consumption_rate": transfer_truth.get(
                    "typed_executor_any_consumption_rate", 0.0
                ),
                "typed_executor_minimal_expected_consumption_rate": transfer_truth.get(
                    "typed_executor_minimal_expected_consumption_rate", 0.0
                ),
                "executor_unexpected_kind_seen_rate": transfer_truth.get(
                    "executor_unexpected_kind_seen_rate", 0.0
                ),
            },
            "guard_audit": {
                "whole_lane_text_guard_pass_rate": guard_audit.get(
                    "whole_lane_text_guard_pass_rate", 0.0
                ),
                "hidden_field_leak_rate": guard_audit.get("hidden_field_leak_rate", 0.0),
                "summarizer_typed_visibility_rate": guard_audit.get(
                    "summarizer_typed_visibility_rate", 0.0
                ),
            },
            "mechanism_audit_keys": sorted(mechanism_audit.keys()) if isinstance(mechanism_audit, dict) else [],
            "tasks": [_build_task_row_summary(row) for row in task_rows],
        }
    return {
        "block": block.name,
        "description": block.description,
        "task_set_path": str(block_out / "benchmark_results.json"),
        "manifest": {
            "task_pack_type": manifest.get("task_pack_type", ""),
            "withheld_headline_reason": manifest.get("withheld_headline_reason", ""),
            "headline_gates": manifest.get("headline_gates", {}),
            "object_parity_gate": manifest.get("object_parity_gate", {}),
            "memory_replay_evidence_gate": manifest.get("memory_replay_evidence_gate", {}),
            "formal_stability_gate": manifest.get("formal_stability_gate", {}),
        },
        "modes": mode_reports,
    }


def _build_task_row_summary(row: dict[str, Any]) -> dict[str, Any]:
    metrics = row.get("metrics", {})
    audit = row.get("case_contract_audit", {})
    retrieve_payload = row.get("results", {}).get("retrieve", {}).get("payload", {})
    validate_result = row.get("results", {}).get("validate", {})
    validate_payload = validate_result.get("payload", {})
    execute_payload = row.get("results", {}).get("execute", {}).get("payload", {})
    reuse = row.get("reuse", {})
    transfer_strategy = str(row.get("transfer_strategy", "")).strip()
    return {
        "task_id": row.get("task_id", ""),
        "mode": row.get("mode", ""),
        "transfer_strategy": row.get("transfer_strategy", ""),
        "carrier_kind": _carrier_kind_for_transfer(transfer_strategy),
        "status": row.get("status", ""),
        "correctness_label": audit.get("correctness_label", ""),
        "observed_route": audit.get("observed_route", ""),
        "observed_tool": audit.get("observed_tool", ""),
        "expected_family": audit.get("expected_family", ""),
        "observed_family": audit.get("observed_family", ""),
        "planner_contract_valid_final": row.get("planner_contract_valid_final"),
        "planner_one_shot_valid": row.get("planner_one_shot_valid"),
        "planner_repair_attempt_count": row.get("planner_repair_attempt_count"),
        "planned_step_count": metrics.get("planned_step_count", 0.0),
        "expected_gate_block_count": metrics.get("expected_gate_block_count", 0.0),
        "true_invariant_violation_count": metrics.get("true_invariant_violation_count", 0.0),
        "validation_success": validate_result.get("success"),
        "validated_route": validate_payload.get("validated_route", ""),
        "validated_tool_name": validate_payload.get("validated_tool_name", ""),
        "validation_failure_reason": validate_payload.get("validation_failure_reason", ""),
        "retrieved_doc_ids": retrieve_payload.get("retrieved_doc_ids", []),
        "route_source": retrieve_payload.get("feature_route_source", ""),
        "route_provenance": retrieve_payload.get("feature_route_provenance", []),
        "matched_signals": retrieve_payload.get("matched_signals", []),
        "execute_route": execute_payload.get("route", ""),
        "execute_tool_name": execute_payload.get("tool_name", ""),
        "reuse_mode": reuse.get("mode", ""),
        "reuse_applied": reuse.get("applied", False),
        "replay_candidate_count": reuse.get("replay_candidate_count", 0),
        "skipped_step_ids": reuse.get("skipped_step_ids", []),
        "assist_memory_hit_rate": metrics.get("assist_memory_hit_rate", 0.0),
        "skipped_step_count": metrics.get("skipped_step_count", 0.0),
        "reuse_gain": metrics.get("reuse_gain", 0.0),
        "error": row.get("error", ""),
        "executor_input_kinds": row.get("transfer_truth_audit", {}).get("executor_input_kinds", []),
        "whole_lane_text_guard": row.get("whole_lane_text_guard", {}),
        "pure_text_guard": row.get("pure_text_guard", {}),
    }


def _render_suite_markdown(*, out_dir: Path, block_reports: list[dict[str, Any]]) -> str:
    lines = [
        "# Issue Discovery Smoke",
        "",
        f"- Output root: `{out_dir}`",
        "- Scope: `fast issue discovery only; not formal repeat stability evidence`",
        "",
    ]
    for block in block_reports:
        lines.extend(
            [
                f"## {block['block']}",
                "",
                f"- Description: {block['description']}",
                f"- Sample count: `{sum(len(report['tasks']) for report in block['modes'].values())}`",
                f"- Pack type: `{block['manifest']['task_pack_type']}`",
                f"- Withheld headline reason: `{block['manifest']['withheld_headline_reason']}`",
                "",
            ]
        )
        for mode, report in block["modes"].items():
            aggregate = report["aggregate"]
            case_contract = report["case_contract"]
            memory_contract = report["memory_contract"]
            transfer_truth = report["transfer_truth"]
            guard_audit = report["guard_audit"]
            lines.extend(
                [
                    f"### {mode}",
                    "",
                    "| metric | value |",
                    "| --- | ---: |",
                    f"| message_count | {float(aggregate['message_count']):.2f} |",
                    f"| task_ms | {float(aggregate['task_ms']):.2f} |",
                    f"| planner_llm_request_count | {float(aggregate['planner_llm_request_count']):.2f} |",
                    f"| planned_step_count | {float(aggregate['planned_step_count']):.2f} |",
                    f"| expected_gate_block_count | {float(aggregate['expected_gate_block_count']):.2f} |",
                    f"| true_invariant_violation_count | {float(aggregate['true_invariant_violation_count']):.2f} |",
                    f"| assist_memory_hit_rate | {float(aggregate['assist_memory_hit_rate']):.2f} |",
                    f"| skipped_step_count | {float(aggregate['skipped_step_count']):.2f} |",
                    f"| route_exact_rate | {float(case_contract['route_exact_rate']):.2f} |",
                    f"| admissible_match_rate | {float(case_contract['admissible_match_rate']):.2f} |",
                    f"| abstention_rate | {float(case_contract['abstention_rate']):.2f} |",
                    f"| wrong_family_rate | {float(case_contract['wrong_family_rate']):.2f} |",
                    f"| typed_executor_any_consumption_rate | {float(transfer_truth['typed_executor_any_consumption_rate']):.2f} |",
                    f"| typed_executor_minimal_expected_consumption_rate | {float(transfer_truth['typed_executor_minimal_expected_consumption_rate']):.2f} |",
                    f"| executor_unexpected_kind_seen_rate | {float(transfer_truth['executor_unexpected_kind_seen_rate']):.2f} |",
                    f"| whole_lane_text_guard_pass_rate | {float(guard_audit['whole_lane_text_guard_pass_rate']):.2f} |",
                    f"| hidden_field_leak_rate | {float(guard_audit['hidden_field_leak_rate']):.2f} |",
                    "",
                ]
            )
            if block["block"] == "memory_contract":
                lines.extend(
                    [
                        "| memory_contract_metric | value |",
                        "| --- | ---: |",
                        f"| assist_memory_hit_rate | {float(memory_contract['assist_memory_hit_rate']):.2f} |",
                        f"| skipped_step_count | {float(memory_contract['skipped_step_count']):.2f} |",
                        f"| reuse_gain | {float(memory_contract['reuse_gain']):.2f} |",
                        f"| memory_replay_evidence_gate_passed | {1.0 if memory_contract['memory_replay_evidence_gate_passed'] else 0.0:.2f} |",
                        f"| memory_replay_expected_rows | {float(memory_contract['memory_replay_expected_rows']):.2f} |",
                        f"| memory_replay_matched_rows | {float(memory_contract['memory_replay_matched_rows']):.2f} |",
                        "",
                        "| task_id | status | reuse_mode | reuse_applied | assist_hit_rate | skipped_steps | reuse_gain | route | tool | notes |",
                        "| --- | --- | --- | --- | ---: | --- | ---: | --- | --- | --- |",
                    ]
                )
                for task in report["tasks"]:
                    notes = _task_notes(task)
                    lines.append(
                        f"| {task['task_id']} | {task['status']} | {task['reuse_mode'] or 'none'} | "
                        f"{'yes' if task['reuse_applied'] else 'no'} | "
                        f"{float(task['assist_memory_hit_rate']):.2f} | "
                        f"`{','.join(task['skipped_step_ids']) if task['skipped_step_ids'] else 'none'}` | "
                        f"{float(task['reuse_gain']):.2f} | "
                        f"{task['observed_route'] or task['execute_route'] or '<empty>'} | "
                        f"{task['observed_tool'] or task['execute_tool_name'] or '<empty>'} | "
                        f"{notes} |"
                    )
                lines.append("")
                continue
            if block["block"] == "planner_validate":
                lines.extend(
                    [
                        "| task_id | status | validate_success | validated_route | validated_tool | failure_reason | gate_blocks | invariant_violations | notes |",
                        "| --- | --- | --- | --- | --- | --- | ---: | ---: | --- |",
                    ]
                )
                for task in report["tasks"]:
                    notes = _task_notes(task)
                    lines.append(
                        f"| {task['task_id']} | {task['status']} | "
                        f"{_fmt_bool(task['validation_success'])} | "
                        f"{task['validated_route'] or '<empty>'} | "
                        f"{task['validated_tool_name'] or '<empty>'} | "
                        f"{task['validation_failure_reason'] or '<empty>'} | "
                        f"{float(task['expected_gate_block_count']):.0f} | "
                        f"{float(task['true_invariant_violation_count']):.0f} | "
                        f"{task['carrier_kind']}; {notes} |"
                    )
                lines.append("")
                continue
            lines.extend(
                [
                    "| task_id | status | carrier | correctness | route | tool | gate_blocks | retrieved_docs | notes |",
                    "| --- | --- | --- | --- | --- | --- | ---: | --- | --- |",
                ]
            )
            for task in report["tasks"]:
                notes = _task_notes(task)
                lines.append(
                    f"| {task['task_id']} | {task['status']} | {task['carrier_kind']} | {task['correctness_label']} | "
                    f"{task['observed_route'] or task['execute_route'] or '<empty>'} | "
                    f"{task['observed_tool'] or task['execute_tool_name'] or '<empty>'} | "
                    f"{float(task['expected_gate_block_count']):.0f} | "
                    f"`{','.join(task['retrieved_doc_ids']) if task['retrieved_doc_ids'] else 'none'}` | "
                    f"{notes} |"
                )
            lines.append("")
    return "\n".join(lines)


def _task_notes(task: dict[str, Any]) -> str:
    notes: list[str] = []
    if task.get("planner_contract_valid_final") is False:
        notes.append("planner_invalid_final")
    if task.get("validation_success") is False:
        notes.append("validate_failed")
    if task.get("transfer_strategy") == "text_whole_lane":
        notes.append("whole_lane_text_carrier")
    if float(task.get("expected_gate_block_count", 0.0)) > 0.0:
        notes.append("gate_blocked")
    if task.get("error"):
        notes.append(f"error={str(task['error'])[:80]}")
    if task.get("route_provenance"):
        notes.append("prov=" + ",".join(str(item) for item in task["route_provenance"]))
    if task.get("executor_input_kinds"):
        notes.append("kinds=" + ",".join(str(item) for item in task["executor_input_kinds"]))
    return "; ".join(notes) if notes else "ok"


def _carrier_kind_for_transfer(transfer_strategy: str) -> str:
    strategy = str(transfer_strategy).strip()
    if strategy == "text_whole_lane":
        return "whole_lane_text"
    if strategy in {"natural_handoff_text", "inline_text_handoff", "text_strict_pure_lane"}:
        return "structured_text"
    if strategy == "state_packet_minimal":
        return "typed_packet"
    if strategy == "state_ref":
        return "state_ref"
    return strategy or "unknown"


def _fmt_bool(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "<n/a>"


if __name__ == "__main__":
    main()
