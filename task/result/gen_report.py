#!/usr/bin/env python3
"""Generate comparison report from Protocol A and Protocol B results."""

import json
from pathlib import Path

RESULT_DIR = Path(__file__).resolve().parent

a = json.loads((RESULT_DIR / "protocol_a_text.json").read_text())
b = json.loads((RESULT_DIR / "protocol_b_structured.json").read_text())

ma = a["metrics_summary"]
mb = b["metrics_summary"]

# Per-round timing comparison
rounds_a = {r["round"]: r["duration_s"] for r in a["rounds"]}
rounds_b = {r["round"]: r["duration_s"] for r in b["rounds"]}

report = {
    "experiment": {
        "name": "Group1: Protocol A (text) vs Protocol B (structured, compressed text only)",
        "container": "SynapseX-wang",
        "model": "Qwen3-8B (A100 80GB, bfloat16)",
        "tasks": "10 rounds, titanic.csv data analysis",
    },
    "protocol_a_text": {
        "llm_calls": ma["llm_calls"],
        "input_tokens": ma["input_tokens"],
        "output_tokens": ma["output_tokens"],
        "total_tokens": ma["total_tokens"],
        "total_node_time_s": round(ma["total_node_time"], 1),
        "context_compression": "N/A (text mode, full document passthrough)",
    },
    "protocol_b_structured_compressed_text": {
        "llm_calls": mb["llm_calls"],
        "input_tokens": mb["input_tokens"],
        "output_tokens": mb["output_tokens"],
        "total_tokens": mb["total_tokens"],
        "total_node_time_s": round(mb["total_node_time"], 1),
        "context_packets_enabled": mb["context_packets_enabled"],
        "context_original_chars": mb["context_original_chars"],
        "context_compressed_chars": mb["context_compressed_chars"],
        "context_saved_chars": mb["context_saved_chars"],
        "compression_ratio": f"{mb['context_saved_chars'] / max(mb['context_original_chars'], 1) * 100:.1f}%",
        "embedding_transfers": mb["embedding_transfers"],
        "hidden_state_transfers": mb["hidden_state_transfers"],
        "protocol_messages": mb["message_count"],
    },
    "comparison": {
        "input_token_diff": mb["input_tokens"] - ma["input_tokens"],
        "input_token_change_pct": round(
            (mb["input_tokens"] - ma["input_tokens"]) / max(ma["input_tokens"], 1) * 100, 1
        ),
        "total_token_diff": mb["total_tokens"] - ma["total_tokens"],
        "total_token_change_pct": round(
            (mb["total_tokens"] - ma["total_tokens"]) / max(ma["total_tokens"], 1) * 100, 1
        ),
        "time_diff_s": round(mb["total_node_time"] - ma["total_node_time"], 1),
        "time_change_pct": round(
            (mb["total_node_time"] - ma["total_node_time"]) / max(ma["total_node_time"], 1) * 100, 1
        ),
    },
    "per_round_timing": {
        f"round_{r}": {
            "protocol_a_s": rounds_a.get(r, 0),
            "protocol_b_s": rounds_b.get(r, 0),
            "diff_s": round(rounds_b.get(r, 0) - rounds_a.get(r, 0), 1),
        }
        for r in range(1, 11)
    },
}

out = RESULT_DIR / "group1_comparison.json"
out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
