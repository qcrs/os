from __future__ import annotations

from scripts.analyze_vllm_prefix_alignment_pair import analyze_pair
from scripts.run_vllm_prefix_alignment_repeats import _aggregate, _repeat_salt


def _probe(mode: str, *, evidence_file: str, evidence_hash: str, contract_valid: bool = True) -> dict[str, object]:
    request_count = 5
    return {
        "model": "qwen3-32b",
        "mode": mode,
        "evidence_file": evidence_file,
        "evidence_sha256": evidence_hash,
        "evidence_repeat": 4,
        "evidence_bytes": 4096,
        "run_salt": _repeat_salt(1),
        "max_tokens": 64,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "roles": ["planner", "retriever", "executor", "summarizer", "verifier"],
        "summary": {
            "request_count": request_count,
            "ok_count": request_count,
            "completion_contract_valid_count": request_count if contract_valid else request_count - 1,
            "counter_delta_valid_request_count": 0,
            "counter_delta_queries": 0.0,
            "counter_delta_hits": 0.0,
            "warm_candidate_mean_ttft_ms": 100.0 if mode == "shared_evidence_prefix" else 110.0,
        },
    }


def test_pair_requires_equal_evidence_content_run_salt_and_completion_contracts() -> None:
    shared = _probe("shared_evidence_prefix", evidence_file="one.md", evidence_hash="sha256:a")
    independent = _probe("independent", evidence_file="one.md", evidence_hash="sha256:a")

    analysis = analyze_pair(shared, independent)

    assert analysis["ok"] is True
    assert analysis["compatibility"]["evidence_sha256_equal"] is True
    assert analysis["compatibility"]["run_salt_equal"] is True

    independent["summary"]["completion_contract_valid_count"] = 4
    invalid = analyze_pair(shared, independent)
    assert invalid["ok"] is False
    assert invalid["compatibility"]["all_completion_contracts_valid"] is False


def test_repeat_aggregate_keeps_counter_claim_optional_but_requires_clean_contract_parity() -> None:
    shared = _probe("shared_evidence_prefix", evidence_file="one.md", evidence_hash="sha256:a")
    independent = _probe("independent", evidence_file="one.md", evidence_hash="sha256:a")
    analysis = analyze_pair(shared, independent)
    clean_service = {
        "requested": True,
        "command_returncode": 0,
        "ready": True,
    }
    pairs = [
        {
            "repeat_index": 1,
            "order": "shared_first",
            "shared": shared,
            "independent": independent,
            "analysis": analysis,
            "analysis_path": "one.json",
            "evidence_file": "one.md",
            "clean_service": clean_service,
        },
        {
            "repeat_index": 2,
            "order": "independent_first",
            "shared": shared,
            "independent": independent,
            "analysis": analysis,
            "analysis_path": "two.json",
            "evidence_file": "two.md",
            "clean_service": clean_service,
        },
    ]

    summary = _aggregate(pairs)

    assert summary["ok"] is True
    assert summary["both_orders_present"] is True
    assert summary["all_completion_contracts_valid"] is True
    assert summary["counter_claim_allowed"] is False
    assert summary["clean_service_all_ready"] is True
    assert summary["evidence_file_count"] == 2
