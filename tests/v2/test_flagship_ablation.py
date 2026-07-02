from __future__ import annotations

from v2.benchmark.flagship_ablation import _non_text_state_stress_summary


def test_non_text_state_stress_summary_identifies_l2_state_ref_savings() -> None:
    summary = _non_text_state_stress_summary(
        continuous_evidence=[
            {
                "family_id": "long_doc_table_v1",
                "headline_scope": "history_backed_only",
                "quality_headline_eligible": True,
                "replay_headline_eligible": False,
                "l2_structured_semantic_state": {"semantic_state_transfer_count": 10.0},
                "t2_text_same_semantic_selection": {
                    "semantic_state_transfer_count": 0.0,
                    "non_text_transfer_delta_l2_vs_text_same_selection": {
                        "llm_prompt_bytes": -6536.0,
                        "prompt_visible_total_bytes": -5538.0,
                        "raw_evidence_bytes_seen_by_llm": 0.0,
                    },
                },
            }
        ],
        continuous_replay_evidence=[],
    )

    assert summary["stress_pass_family_count"] == 1
    assert summary["total_llm_prompt_saved_by_state_ref_bytes"] == 6536.0
    assert summary["total_prompt_visible_saved_by_state_ref_bytes"] == 5538.0
    top_family = summary["top_prompt_visible_saving_family"]
    assert top_family["family_id"] == "long_doc_table_v1"
    assert top_family["stress_pass"] is True
    assert top_family["interpretation"] == "non_text_state_transfer_has_extra_prompt_saving"
