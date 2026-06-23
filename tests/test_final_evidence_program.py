from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "write_final_evidence_program.py"
SPEC = importlib.util.spec_from_file_location("write_final_evidence_program", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _communication_artifact(
    *,
    repeat: int,
    llm_total_tokens_text: float,
    llm_total_tokens_protocol: float,
    task_ms_text: float,
    task_ms_protocol: float,
    planner_one_shot_valid_rate: float = 1.0,
    planner_repair_attempts: int = 0,
    summarize_ms_text: float = 1000.0,
    summarize_ms_protocol: float = 1100.0,
    summarizer_total_tokens_text: float = 500.0,
    summarizer_total_tokens_protocol: float = 450.0,
    mismatch_task_ids: list[str] | None = None,
    cross_lane_actual_parity_headline_blocking: bool = False,
    communication_gate: str = "withheld",
) -> dict[str, object]:
    mismatch_task_ids = mismatch_task_ids or ["rr-billing-clean"]
    return {
        "report_path": "runs/fake/benchmark_report.md",
        "results_path": "runs/fake/benchmark_results.json",
        "compare_path": "runs/fake/benchmark_compare.csv",
        "report_metrics": {
            "planner_one_shot_valid_rate": planner_one_shot_valid_rate,
            "planner_repair_attempts": planner_repair_attempts,
            "communication_gate": communication_gate,
            "formal_stability_gate": "not_yet",
            "cross_lane_actual_parity": "fail",
        },
        "manifest": {
            "task_pack_type": "superiority_comm_v1",
            "cross_lane_actual_parity_headline_blocking": cross_lane_actual_parity_headline_blocking,
            "cross_lane_actual_parity": {
                "applicable": True,
                "passed": False,
                "mismatch_task_ids": mismatch_task_ids,
                "shared_task_count": 12,
                "missing_in_text": [],
                "missing_in_protocol": [],
            },
            "headline_gates": {
                "communication_gate": {
                    "allowed": communication_gate == "pass",
                    "withheld_reasons": ["contest_repeat_insufficient"]
                    if communication_gate != "pass"
                    else [],
                    "contest_formal_coverage_gate": {
                        "surface_complete": True,
                        "matched_pair_count": 12,
                        "repeat": repeat,
                        "repeat_sufficient": repeat >= 10,
                    },
                },
                "formal_stability_gate": {
                    "allowed": False,
                },
            },
        },
        "summary": {
            "text": {
                "aggregate": {
                    "llm_total_tokens": llm_total_tokens_text,
                    "task_ms": task_ms_text,
                    "planner_total_tokens": 1000.0,
                    "summarizer_total_tokens": summarizer_total_tokens_text,
                },
                "stability": {
                    "planner_ms": {"mean": 3000.0},
                    "summarize_ms": {"mean": summarize_ms_text},
                },
                "failure_count": 0,
                "unexpected_task_failure_count": 0,
                "run_failure_count": 0,
                "misfire_audit": {
                    "case_contract": {
                        "wrong_family_rate": 0.0,
                        "route_exact_rate": 1.0,
                        "exact_match_rate": 0.75,
                        "tool_exact_rate": 0.75,
                    }
                },
            },
            "protocol": {
                "aggregate": {
                    "llm_total_tokens": llm_total_tokens_protocol,
                    "task_ms": task_ms_protocol,
                    "planner_total_tokens": 900.0,
                    "summarizer_total_tokens": summarizer_total_tokens_protocol,
                },
                "stability": {
                    "planner_ms": {"mean": 2500.0},
                    "summarize_ms": {"mean": summarize_ms_protocol},
                },
                "failure_count": 0,
                "unexpected_task_failure_count": 0,
                "run_failure_count": 0,
                "misfire_audit": {
                    "case_contract": {
                        "wrong_family_rate": 0.0,
                        "route_exact_rate": 1.0,
                        "exact_match_rate": 0.75,
                        "tool_exact_rate": 0.75,
                    }
                },
            },
        },
    }


def _memory_artifact(effect_established: bool = True) -> dict[str, object]:
    return {
        "report_path": "runs/memory/benchmark_report.md",
        "results_path": "runs/memory/benchmark_results.json",
        "compare_path": "runs/memory/benchmark_compare.csv",
        "report_metrics": {
            "memory_replay_gate": "pass" if effect_established else "withheld",
        },
        "manifest": {},
        "summary": {},
    }


def _typed_state_mechanism_artifact() -> dict[str, object]:
    return {
        "report_path": "runs/typed_mech/benchmark_report.md",
        "results_path": "runs/typed_mech/benchmark_results.json",
        "compare_path": None,
        "report_metrics": {},
        "manifest": {},
        "summary": {
            "protocol": {
                "misfire_audit": {
                    "case_contract": {
                        "route_exact_rate": 1.0,
                        "tool_exact_rate": 1.0,
                        "wrong_family_rate": 0.0,
                    }
                },
                "mechanism_audit": {
                    "slimming_variants": {
                        "state_packet_minimal": {
                            "task_count": 4,
                        }
                    }
                },
            }
        },
    }


def _typed_state_consumer_artifact(
    *,
    minimal_rate: float = 0.25,
    missing_decision_failure_rate: float = 1.0,
    wrong_decision_mistool_rate: float = 1.0,
) -> dict[str, object]:
    return {
        "report_path": "runs/typed_consumer/benchmark_report.md",
        "results_path": "runs/typed_consumer/benchmark_results.json",
        "compare_path": None,
        "report_metrics": {},
        "manifest": {},
        "summary": {
            "protocol": {
                "transfer_truth": {
                    "typed_executor_minimal_expected_consumption_rate": minimal_rate,
                },
                "mechanism_audit": {
                    "typed_state_consumer_sensitivity_v3": {
                        "missing_decision_failure_rate": missing_decision_failure_rate,
                        "wrong_decision_mistool_rate": wrong_decision_mistool_rate,
                    }
                },
            }
        },
    }


def test_communication_ledger_marks_withheld_when_authoritative_gate_still_withheld() -> None:
    support = _communication_artifact(
        repeat=1,
        llm_total_tokens_text=1500.0,
        llm_total_tokens_protocol=1400.0,
        task_ms_text=5000.0,
        task_ms_protocol=4700.0,
    )
    authoritative = _communication_artifact(
        repeat=3,
        llm_total_tokens_text=1600.0,
        llm_total_tokens_protocol=1450.0,
        task_ms_text=5300.0,
        task_ms_protocol=4900.0,
    )

    verdict = MODULE.build_communication_closure_ledger(
        communication_authoritative=authoritative,
        communication_support=support,
    )

    assert verdict["release_ledger"]["repeat_consistency_ok"]["passed"] is True
    assert verdict["release_ledger"]["planner_stability_ok"]["passed"] is True
    assert verdict["release_ledger"]["parity_isolation_ok"]["passed"] is True
    assert verdict["release_ledger_all_passed"] is True
    assert verdict["communication_gate_status"] == "withheld"


def test_parity_isolation_accepts_single_diagnostic_rr_billing_clean() -> None:
    support = _communication_artifact(
        repeat=1,
        llm_total_tokens_text=1500.0,
        llm_total_tokens_protocol=1400.0,
        task_ms_text=5000.0,
        task_ms_protocol=4700.0,
    )
    authoritative = _communication_artifact(
        repeat=3,
        llm_total_tokens_text=1600.0,
        llm_total_tokens_protocol=1450.0,
        task_ms_text=5300.0,
        task_ms_protocol=4900.0,
        mismatch_task_ids=["rr-billing-clean"],
        cross_lane_actual_parity_headline_blocking=False,
    )

    verdict = MODULE.build_communication_closure_ledger(
        communication_authoritative=authoritative,
        communication_support=support,
    )

    assert verdict["release_ledger"]["parity_isolation_ok"]["passed"] is True


def test_repeat10_admission_requires_communication_gate_pass() -> None:
    support = _communication_artifact(
        repeat=1,
        llm_total_tokens_text=1500.0,
        llm_total_tokens_protocol=1400.0,
        task_ms_text=5000.0,
        task_ms_protocol=4700.0,
    )
    authoritative = _communication_artifact(
        repeat=3,
        llm_total_tokens_text=1600.0,
        llm_total_tokens_protocol=1450.0,
        task_ms_text=5300.0,
        task_ms_protocol=4900.0,
        communication_gate="withheld",
    )
    closure = MODULE.build_communication_closure_ledger(
        communication_authoritative=authoritative,
        communication_support=support,
    )

    repeat10 = MODULE.build_repeat10_admission_verdict(
        communication_closure=closure,
    )

    assert repeat10["admitted"] is False
    assert repeat10["communication_gate_already_passed"] is False


def test_memory_verdict_never_claims_superiority() -> None:
    verdict = MODULE.build_memory_final_role_verdict(
        memory_artifact=_memory_artifact(effect_established=True),
    )

    assert verdict["role"] == "required_secondary_verdict"
    assert verdict["effect_established"] is True
    assert verdict["superiority_established"] is False
    assert "memory superiority established" in verdict["forbidden_claims"]


def test_typed_state_verdict_stays_secondary() -> None:
    verdict = MODULE.build_typed_state_final_role_verdict(
        typed_state_mechanism_artifact=_typed_state_mechanism_artifact(),
        typed_state_consumer_artifact=_typed_state_consumer_artifact(),
    )

    assert verdict["role"] == "required_secondary_state_transfer_verdict"
    assert verdict["mechanism_established"] is True
    assert verdict["minimal_packet_consumed"] is True
    assert verdict["negative_control_triggered"] is True
    assert "typed-state is the active communication headline" in verdict["forbidden_claims"]


def test_markdown_render_contains_required_sections() -> None:
    payload = MODULE.build_final_evidence_program(
        communication_authoritative=_communication_artifact(
            repeat=3,
            llm_total_tokens_text=1600.0,
            llm_total_tokens_protocol=1450.0,
            task_ms_text=5300.0,
            task_ms_protocol=4900.0,
        ),
        communication_support=_communication_artifact(
            repeat=1,
            llm_total_tokens_text=1500.0,
            llm_total_tokens_protocol=1400.0,
            task_ms_text=5000.0,
            task_ms_protocol=4700.0,
        ),
        memory_artifact=_memory_artifact(),
        typed_state_consumer_artifact=_typed_state_consumer_artifact(),
        typed_state_mechanism_artifact=_typed_state_mechanism_artifact(),
        input_paths={"fake": {"report": "runs/fake/report.md"}},
    )

    text = MODULE.render_final_evidence_program_md(payload)

    assert "Communication Closure Ledger" in text
    assert "Repeat-10 Admission" in text
    assert "Memory Final Role" in text
    assert "Typed-State Final Role" in text
    assert "Delivery Status" in text
