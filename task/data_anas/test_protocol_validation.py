#!/usr/bin/env python3

"""Smoke test for compact-context verification heuristics."""

import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from protocol import build_context_packet, hash_text, verify_context_packet


def main() -> None:
    doc_text = "alpha beta gamma delta"

    packet = build_context_packet(
        doc_key="doc_demo",
        sub_query="unrelated query terms",
        doc_text=doc_text,
        task_group="group1",
    )

    assert packet["verification"]["reliable"] is True, packet["verification"]
    assert packet["verification"]["requires_full_doc_lookup"] is False, packet["verification"]
    assert packet["verification"]["coverage_warning"] is True, packet["verification"]
    assert packet["retrieval_diagnostics"]["requires_full_doc_lookup"] is False, packet["retrieval_diagnostics"]
    assert packet["retrieval_diagnostics"]["coverage_warning"] is True, packet["retrieval_diagnostics"]

    invalid_packet = {
        "doc_key": "doc_demo",
        "source_query": "unrelated query terms",
        "summary": "alpha",
        "evidence_spans": [
            {
                "span_id": "ev1",
                "text": "alpha",
                "source_ref": {
                    "doc_key": "doc_demo",
                    "char_start": 0,
                    "char_end": 5,
                    "text_hash": hash_text("beta"),
                },
            }
        ],
        "full_doc_ref": {"text_hash": hash_text(doc_text)},
    }

    verification = verify_context_packet(invalid_packet, doc_text, query_text="unrelated query terms")
    assert verification["reliable"] is False, verification
    assert verification["requires_full_doc_lookup"] is True, verification

    print("protocol verification smoke test passed")


if __name__ == "__main__":
    main()
