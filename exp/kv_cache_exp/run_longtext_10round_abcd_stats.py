#!/usr/bin/env python3
"""Run 10-round LongText A/B/C/D communication-stat validation.

Extends run_longtext_10round_abc_stats.py by adding:
* D/latent_kv: latent steps with non-text KV state transfer via LangGraph.

Usage:
    # Run only D mode (A/B/C results from prior run):
    python3 run_longtext_10round_abcd_stats.py --modes latent_kv \
        --existing-abc-dir exp/kv_cache_exp/longtext_10round_abc_stats_wmw71_gpu0_20260701_114648

    # Run A/B/D modes together:
    CHAT_BASE_URL=http://localhost:8100/v1 CHAT_API_KEY=token-abc \
    CHAT_MODEL=/data/models/Qwen3-8B \
    python3 run_longtext_10round_abcd_stats.py --modes text structured latent_kv
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_TASKS_FILE = ROOT / "task" / "longtext" / "skyforge_cache_tasks.json"
DEFAULT_OUTPUT_ROOT = ROOT / "exp" / "kv_cache_exp"

MODES_ALL = ["text", "structured", "true_kv_transfer", "latent_kv"]
MODES_DEFAULT = ["latent_kv"]


# ---------------------------------------------------------------------------
# Shared dataclasses (mirror run_longtext_10round_abc_stats.py)
# ---------------------------------------------------------------------------

@dataclass
class LLMCall:
    round_id: int
    task_id: int
    agent: str
    prompt_tokens: int
    prompt_chars: int
    effective_prompt_tokens: int
    kv_reused_tokens: int
    output_tokens: int
    output_chars: int
    text_transfer_tokens: int
    text_transfer_chars: int
    wall_time_sec: float


@dataclass
class AgentMessageStat:
    round_id: int
    source: str
    target: str
    action: str
    text_chars: int
    text_tokens: int


@dataclass
class NonTextEvent:
    round_id: int
    event_type: str
    source: str
    target: str
    size_bytes: int
    note: str = ""


@dataclass
class RoundMetric:
    round_id: int
    task_id: int
    wall_time_sec: float
    llm_call_count: int
    inter_agent_message_count: int
    text_transfer_tokens: int
    text_transfer_chars: int
    effective_prompt_tokens: int
    logical_prompt_tokens: int
    output_tokens: int
    kv_reused_tokens: int
    non_text_state_events: int
    non_text_state_bytes: int


@dataclass
class ModeResult:
    mode: str
    mode_wall_time_sec: float = 0.0
    model_load_wall_time_sec: float = 0.0
    source_prefix_tokens: int = 0
    source_prefix_chars: int = 0
    producer_wall_time_sec: float = 0.0
    kv_storage: dict[str, Any] = field(default_factory=dict)
    calls: list[LLMCall] = field(default_factory=list)
    messages: list[AgentMessageStat] = field(default_factory=list)
    non_text_events: list[NonTextEvent] = field(default_factory=list)
    rounds: list[RoundMetric] = field(default_factory=list)
    # latent_kv extra
    latent_kv_stats: dict[str, Any] = field(default_factory=dict)

    def aggregate(self) -> dict[str, Any]:
        from collections import Counter
        logical_prompt_tokens = sum(c.prompt_tokens for c in self.calls)
        effective_prompt_tokens = sum(c.effective_prompt_tokens for c in self.calls)
        output_tokens = sum(c.output_tokens for c in self.calls)
        text_transfer_tokens = sum(c.text_transfer_tokens for c in self.calls)
        text_transfer_chars = sum(c.text_transfer_chars for c in self.calls)
        kv_reused_tokens = sum(c.kv_reused_tokens for c in self.calls)
        non_text_bytes = sum(e.size_bytes for e in self.non_text_events)
        edge_counts = Counter(f"{m.source}->{m.target}" for m in self.messages)
        round_times = [r.wall_time_sec for r in self.rounds]
        return {
            "mode": self.mode,
            "rounds_completed": len(self.rounds),
            "mode_wall_time_sec": round(self.mode_wall_time_sec, 4),
            "model_load_wall_time_sec": round(self.model_load_wall_time_sec, 4),
            "source_prefix_tokens": self.source_prefix_tokens,
            "source_prefix_chars": self.source_prefix_chars,
            "producer_wall_time_sec": round(self.producer_wall_time_sec, 4),
            "llm_call_count": len(self.calls),
            "logical_prompt_tokens": logical_prompt_tokens,
            "effective_prompt_tokens": effective_prompt_tokens,
            "output_tokens": output_tokens,
            "logical_total_tokens": logical_prompt_tokens + output_tokens,
            "effective_total_tokens": effective_prompt_tokens + output_tokens,
            "text_transfer_tokens": text_transfer_tokens,
            "text_transfer_chars": text_transfer_chars,
            "kv_reused_tokens": kv_reused_tokens,
            "non_text_state_transfer_count": len(self.non_text_events),
            "non_text_state_bytes": non_text_bytes,
            "inter_agent_message_count": len(self.messages),
            "message_edge_counts": dict(edge_counts),
            "sum_round_wall_time_sec": round(sum(round_times), 4),
            "avg_single_task_wall_time_sec": round(sum(round_times) / len(round_times), 4) if round_times else 0.0,
            "min_single_task_wall_time_sec": round(min(round_times), 4) if round_times else 0.0,
            "max_single_task_wall_time_sec": round(max(round_times), 4) if round_times else 0.0,
            "kv_storage": self.kv_storage,
            "latent_kv_stats": self.latent_kv_stats,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def count_tokens_approx(text: str) -> int:
    """Rough token count: ~4 chars per token."""
    return max(1, len(text) // 4)


def build_task_query(task: dict[str, Any], previous_outputs: list[dict[str, Any]]) -> str:
    """Build the query string for latent_kv graph from task and previous rounds."""
    question = task.get("question", "")
    constraints = task.get("constraints", "")
    answer_format = task.get("answer_format", "")
    round_id = task.get("round", 1)

    parts = [f"[Round {round_id}] {question}"]
    if constraints:
        parts.append(f"Constraints: {constraints}")
    if answer_format:
        parts.append(f"Expected answer format: {answer_format}")
    if previous_outputs:
        last = previous_outputs[-1]
        summary = last.get("summary", last.get("final_answer", ""))
        if summary:
            parts.append(f"[Previous round summary] {summary[:500]}")

    return "\n".join(parts)


def load_source_context(dataset: dict[str, Any]) -> str:
    """Load source context text from dataset reference."""
    src_file = dataset.get("source_context_file", "")
    if src_file:
        src_path = ROOT / src_file
        if src_path.exists():
            return src_path.read_text(encoding="utf-8")
    return ""


# ---------------------------------------------------------------------------
# Latent KV mode runner
# ---------------------------------------------------------------------------

def run_latent_kv_round(
    graph,
    task: dict[str, Any],
    previous_outputs: list[dict[str, Any]],
) -> tuple[dict[str, Any], RoundMetric, list[LLMCall], list[NonTextEvent]]:
    """Run one round of latent_kv mode.

    Uses the global `metrics` singleton from src/metrics.py to collect
    latent KV stats — it must be reset() before each round.
    """
    from metrics import metrics as global_metrics  # global singleton

    round_id = int(task.get("round", 0))
    task_id = int(task.get("id", 0))
    query = build_task_query(task, previous_outputs)

    global_metrics.reset()
    t0 = time.perf_counter()
    result = graph.invoke({"query": query})
    wall_time = time.perf_counter() - t0

    # Read metrics from global singleton after graph invocation
    # summary_dict() returns a flat dict — see src/metrics.py
    summary = global_metrics.summary_dict()
    latent_steps = summary.get("latent_steps_total", 0)
    kv_bytes_added = summary.get("latent_kv_bytes_added", 0)
    kv_bytes_copied = summary.get("latent_kv_bytes_copied", 0)
    avoided_prefill = summary.get("avoided_prefill_tokens", 0)
    llm_input_tokens = summary.get("input_tokens", 0)
    llm_output_tokens = summary.get("output_tokens", 0)

    # NonTextEvent: latent KV transfer
    non_text_events: list[NonTextEvent] = []
    if kv_bytes_added > 0:
        non_text_events.append(NonTextEvent(
            round_id=round_id,
            event_type="latent_kv_transfer",
            source="analyst_latent",
            target="summarizer_latent",
            size_bytes=kv_bytes_added,
            note=f"latent_steps={latent_steps}; avoided_prefill={avoided_prefill}; copied_bytes={kv_bytes_copied}",
        ))

    # Synthetic LLM calls
    llm_calls: list[LLMCall] = []
    query_chars = len(query)
    query_tokens = count_tokens_approx(query)
    if llm_input_tokens > 0 or llm_output_tokens > 0:
        llm_calls.append(LLMCall(
            round_id=round_id,
            task_id=task_id,
            agent="latent_kv_pipeline",
            prompt_tokens=llm_input_tokens,
            prompt_chars=query_chars,
            effective_prompt_tokens=max(0, llm_input_tokens - avoided_prefill),
            kv_reused_tokens=avoided_prefill,
            output_tokens=llm_output_tokens,
            output_chars=len(str(result.get("final_answer", ""))),
            text_transfer_tokens=query_tokens,
            text_transfer_chars=query_chars,
            wall_time_sec=round(wall_time, 4),
        ))

    round_metric = RoundMetric(
        round_id=round_id,
        task_id=task_id,
        wall_time_sec=round(wall_time, 4),
        llm_call_count=len(llm_calls),
        inter_agent_message_count=3,  # analyst→executor→summarizer
        text_transfer_tokens=query_tokens,
        text_transfer_chars=query_chars,
        effective_prompt_tokens=max(0, llm_input_tokens - avoided_prefill),
        logical_prompt_tokens=llm_input_tokens,
        output_tokens=llm_output_tokens,
        kv_reused_tokens=avoided_prefill,
        non_text_state_events=len(non_text_events),
        non_text_state_bytes=kv_bytes_added,
    )

    output = {
        "round_id": round_id,
        "task_id": task_id,
        "summary": result.get("summary", ""),
        "final_answer": result.get("final_answer", ""),
        "key_findings": result.get("key_findings", []),
        "latent_steps": latent_steps,
        "kv_bytes_added": kv_bytes_added,
    }
    return output, round_metric, llm_calls, non_text_events


def run_latent_kv_mode(
    output_dir: Path,
    dataset: dict[str, Any],
    max_rounds: int,
) -> ModeResult:
    """Run all rounds in latent_kv mode using the HTTP vLLM server."""
    from graph import build_latent_kv_graph

    result = ModeResult(mode="latent_kv")
    mode_started = time.perf_counter()

    print("[latent_kv] Building LangGraph latent_kv graph...", flush=True)
    graph, store = build_latent_kv_graph()
    print("[latent_kv] Graph built.", flush=True)

    output_mode_dir = output_dir / "round_outputs" / "latent_kv"
    output_mode_dir.mkdir(parents=True, exist_ok=True)

    previous_outputs: list[dict[str, Any]] = []
    tasks = dataset.get("tasks", [])[:max_rounds]

    total_latent_steps = 0
    total_kv_bytes_added = 0
    total_avoided_prefill = 0

    for task in tasks:
        print(f"[latent_kv] round={task.get('round')} task_id={task.get('id')}", flush=True)
        output, round_metric, llm_calls, non_text_events = run_latent_kv_round(
            graph, task, previous_outputs
        )
        previous_outputs.append(output)
        result.calls.extend(llm_calls)
        result.non_text_events.extend(non_text_events)
        result.rounds.append(round_metric)

        total_latent_steps += output.get("latent_steps", 0)
        total_kv_bytes_added += output.get("kv_bytes_added", 0)
        total_avoided_prefill += round_metric.kv_reused_tokens

        # Save round output
        (output_mode_dir / f"round_{round_metric.round_id:02d}.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({
            "mode": "latent_kv",
            "round_metric": asdict(round_metric),
        }, ensure_ascii=False), flush=True)

    result.mode_wall_time_sec = time.perf_counter() - mode_started
    result.latent_kv_stats = {
        "total_latent_steps": total_latent_steps,
        "total_kv_bytes_added": total_kv_bytes_added,
        "total_avoided_prefill_tokens": total_avoided_prefill,
        "avg_latent_steps_per_round": total_latent_steps / max(1, len(tasks)),
    }
    print(f"[latent_kv] Done. {len(result.rounds)} rounds in {result.mode_wall_time_sec:.1f}s", flush=True)
    return result


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def write_mode_files(output_dir: Path, result: ModeResult) -> None:
    mode_dir = output_dir / "metrics" / result.mode
    mode_dir.mkdir(parents=True, exist_ok=True)
    (mode_dir / "calls.json").write_text(
        json.dumps([asdict(c) for c in result.calls], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (mode_dir / "non_text_events.json").write_text(
        json.dumps([asdict(e) for e in result.non_text_events], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (mode_dir / "rounds.json").write_text(
        json.dumps([asdict(r) for r in result.rounds], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / f"{result.mode}.json").write_text(
        json.dumps({
            "mode": result.mode,
            "aggregate": result.aggregate(),
            "rounds": [asdict(r) for r in result.rounds],
            "kv_storage": result.kv_storage,
            "latent_kv_stats": result.latent_kv_stats,
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_abcd_report(output_dir: Path, summary: dict[str, Any]) -> None:
    metrics = summary.get("metrics", {})
    mode_labels = [("A", "text"), ("B", "structured"), ("C", "true_kv_transfer"), ("D", "latent_kv")]
    rows = []
    for label, mode in mode_labels:
        item = metrics.get(mode, {})
        if not item:
            continue
        lkv = item.get("latent_kv_stats", {})
        latent_note = f"latent_steps={lkv.get('total_latent_steps',0)}" if mode == "latent_kv" else ""
        rows.append(
            f"| {label} | `{mode}` | {item.get('rounds_completed',0)} | "
            f"{item.get('llm_call_count',0)} | {item.get('inter_agent_message_count',0)} | "
            f"{item.get('text_transfer_tokens',0)} | {item.get('non_text_state_transfer_count',0)} | "
            f"{item.get('non_text_state_bytes',0)} | {item.get('avg_single_task_wall_time_sec',0)}s | "
            f"{item.get('mode_wall_time_sec',0)}s | {latent_note} |"
        )

    report = f"""# ABCD Communication Mode Comparison Report

Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}
Experiment dir: `{output_dir}`

## Summary Table

| Mode | Name | Rounds | LLM Calls | Messages | Text Tokens | NonText Events | NonText Bytes | Avg Round Time | Total Time | Notes |
|------|------|--------|-----------|----------|------------|---------------|---------------|----------------|-----------|-------|
{chr(10).join(rows)}

## Mode Descriptions

- **A/text**: Full source prefix + textual state transfer each round
- **B/structured**: Compact structured packets + typed state messages
- **C/true_kv_transfer**: Source prefix prefetched as vLLM KV tensors; per-agent suffix counted as text
- **D/latent_kv**: Non-text latent steps; KV state transferred as handle IDs (zero-copy)

## Latent KV (D mode) Stats
"""
    d_stats = metrics.get("latent_kv", {}).get("latent_kv_stats", {})
    if d_stats:
        report += f"""
- Total latent steps: {d_stats.get('total_latent_steps', 0)}
- Total KV bytes added: {d_stats.get('total_kv_bytes_added', 0):,}
- Total avoided prefill tokens: {d_stats.get('total_avoided_prefill_tokens', 0):,}
- Avg latent steps/round: {d_stats.get('avg_latent_steps_per_round', 0):.1f}
"""
    (output_dir / "abcd_communication_report.md").write_text(report, encoding="utf-8")
    print(f"[report] Written: {output_dir}/abcd_communication_report.md", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run 10-round LongText ABCD mode comparison")
    parser.add_argument("--tasks-file", type=Path, default=DEFAULT_TASKS_FILE)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--modes", nargs="+", choices=MODES_ALL, default=MODES_DEFAULT)
    parser.add_argument("--max-rounds", type=int, default=10)
    parser.add_argument(
        "--existing-abc-dir", type=Path, default=None,
        help="Path to existing A/B/C results dir. Merges with D results for combined report."
    )
    args = parser.parse_args()

    # Configure environment for local Qwen3-8B vLLM server
    os.environ.setdefault("CHAT_BASE_URL", "http://localhost:8100/v1")
    os.environ.setdefault("CHAT_API_KEY", "token-abc")
    os.environ.setdefault("CHAT_MODEL", "/data/models/Qwen3-8B")
    os.environ.setdefault("CHAT_DISABLE_THINKING", "1")
    os.environ.setdefault("COMM_MODE", "latent_kv")
    os.environ.setdefault("ANALYST_LATENT_STEPS", "64")
    os.environ.setdefault("EXECUTOR_LATENT_STEPS", "32")
    os.environ.setdefault("POST_EXEC_LATENT_STEPS", "16")

    ts = time.strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / f"longtext_10round_abcd_stats_{ts}")
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset = read_json(args.tasks_file)

    results: dict[str, ModeResult] = {}
    for mode in args.modes:
        print(f"\n{'='*60}", flush=True)
        print(f"[abcd] Running mode={mode}", flush=True)
        print(f"{'='*60}", flush=True)
        if mode == "latent_kv":
            result = run_latent_kv_mode(output_dir, dataset, args.max_rounds)
        else:
            print(f"[abcd] Mode {mode} not implemented in this script. Use run_longtext_10round_abc_stats.py.", flush=True)
            continue
        results[mode] = result
        write_mode_files(output_dir, result)
        agg = result.aggregate()
        print(json.dumps({"mode": mode, "aggregate": agg}, ensure_ascii=False, indent=2), flush=True)

    # Combine with existing A/B/C results if provided
    combined_metrics: dict[str, Any] = {}
    combined_rounds: dict[str, Any] = {}

    if args.existing_abc_dir and args.existing_abc_dir.exists():
        for mode in ["text", "structured", "true_kv_transfer"]:
            existing = args.existing_abc_dir / f"{mode}.json"
            if existing.exists():
                payload = read_json(existing)
                combined_metrics[mode] = payload.get("aggregate", {})
                combined_rounds[mode] = payload.get("rounds", [])
                print(f"[abcd] Loaded existing {mode} results from {existing}", flush=True)

    for mode, result in results.items():
        combined_metrics[mode] = result.aggregate()
        combined_rounds[mode] = [asdict(r) for r in result.rounds]

    summary = {
        "experiment_dir": str(output_dir),
        "existing_abc_dir": str(args.existing_abc_dir) if args.existing_abc_dir else None,
        "task_file": str(args.tasks_file),
        "total_rounds": min(int(dataset.get("total_rounds", len(dataset.get("tasks", [])))), args.max_rounds),
        "topology": "planner -> 3*researcher -> analyst_latent -> executor_latent -> summarizer_latent",
        "settings": {
            "chat_base_url": os.environ.get("CHAT_BASE_URL"),
            "chat_model": os.environ.get("CHAT_MODEL"),
            "analyst_latent_steps": os.environ.get("ANALYST_LATENT_STEPS"),
            "executor_latent_steps": os.environ.get("EXECUTOR_LATENT_STEPS"),
        },
        "metrics": combined_metrics,
        "rounds": combined_rounds,
    }

    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[abcd] Summary written: {summary_path}", flush=True)

    write_abcd_report(output_dir, summary)

    print(f"\n{'='*60}", flush=True)
    print("ABCD mode comparison complete!", flush=True)
    for mode, agg in combined_metrics.items():
        lkv = agg.get("latent_kv_stats", {})
        latent_note = f"  [latent_steps={lkv.get('total_latent_steps',0)}]" if mode == "latent_kv" else ""
        print(f"  {mode:20s}: {agg.get('rounds_completed',0)} rounds, "
              f"avg {agg.get('avg_single_task_wall_time_sec',0):.1f}s/round, "
              f"{agg.get('text_transfer_tokens',0)} text_tokens{latent_note}", flush=True)
    print(f"{'='*60}", flush=True)


if __name__ == "__main__":
    main()
