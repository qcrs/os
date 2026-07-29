#!/usr/bin/env python3
"""Run 10-round LongText A/B/C communication-stat validation.

This experiment is intentionally metric-oriented.  It runs the same logical
five-Agent topology for every round in ``task/longtext`` and compares only the
state-transfer style:

* A/text: full source prefix plus textual previous-round state.
* B/structured: compact source/state packets and typed structured messages.
* C/true_kv_transfer: full source prefix is prefetched into vLLM
  SharedStorageConnector KV tensors; per-Agent suffix/state is counted as text.

For each mode and each round, the script records:

* inter-Agent message counts and edge counts,
* text communication tokens/chars,
* non-text/structured state-transfer event counts and byte sizes,
* per-round wall time and aggregate wall time.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import shutil
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from true_kv_handoff_runtime import (  # noqa: E402
    build_llm_kwargs,
    build_shared_storage_kv_transfer_config,
    make_handoff_handle,
)


DEFAULT_TASKS_FILE = ROOT / "task" / "longtext" / "skyforge_cache_tasks.json"
DEFAULT_OUTPUT_ROOT = ROOT / "exp" / "kv_cache_exp"
MODES = ["text", "structured", "true_kv_transfer"]
RESEARCHER_COUNT = 3

ROLE_MAX_TOKENS = {
    "planner": 160,
    "researcher": 192,
    "analyst": 256,
    "summarizer": 384,
    "summarizer_final": 768,
}

INTER_AGENT_EDGES = [
    ("planner", "researcher_1"),
    ("planner", "researcher_2"),
    ("planner", "researcher_3"),
    ("researcher_1", "analyst"),
    ("researcher_2", "analyst"),
    ("researcher_3", "analyst"),
    ("analyst", "executor"),
    ("executor", "summarizer"),
]

SYSTEM_PROMPT = """You are a senior Python game engineer in a multi-Agent pipeline.
Follow the assigned role. Keep outputs concise, specific, and machine-readable.
The task source is the 10-round Skyforge Courier longtext benchmark.
""".strip()


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

    def aggregate(self) -> dict[str, Any]:
        logical_prompt_tokens = sum(call.prompt_tokens for call in self.calls)
        effective_prompt_tokens = sum(call.effective_prompt_tokens for call in self.calls)
        output_tokens = sum(call.output_tokens for call in self.calls)
        text_transfer_tokens = sum(call.text_transfer_tokens for call in self.calls)
        text_transfer_chars = sum(call.text_transfer_chars for call in self.calls)
        kv_reused_tokens = sum(call.kv_reused_tokens for call in self.calls)
        non_text_bytes = sum(event.size_bytes for event in self.non_text_events)
        edge_counts = Counter(f"{msg.source}->{msg.target}" for msg in self.messages)
        round_times = [round_metric.wall_time_sec for round_metric in self.rounds]
        return {
            "mode": self.mode,
            "rounds_completed": len(self.rounds),
            "mode_wall_time_sec": round(self.mode_wall_time_sec, 4),
            "model_load_wall_time_sec": round(self.model_load_wall_time_sec, 4),
            "sum_round_wall_time_sec": round(sum(round_times), 4),
            "avg_single_task_wall_time_sec": round(sum(round_times) / max(len(round_times), 1), 4),
            "min_single_task_wall_time_sec": round(min(round_times), 4) if round_times else 0.0,
            "max_single_task_wall_time_sec": round(max(round_times), 4) if round_times else 0.0,
            "llm_call_count": len(self.calls),
            "inter_agent_message_count": len(self.messages),
            "message_edge_counts": dict(sorted(edge_counts.items())),
            "logical_prompt_tokens": logical_prompt_tokens,
            "effective_prompt_tokens": effective_prompt_tokens,
            "output_tokens": output_tokens,
            "logical_total_tokens": logical_prompt_tokens + output_tokens,
            "effective_total_tokens": effective_prompt_tokens + output_tokens,
            "text_transfer_tokens": text_transfer_tokens,
            "text_transfer_chars": text_transfer_chars,
            "kv_reused_tokens": kv_reused_tokens,
            "source_prefix_tokens": self.source_prefix_tokens,
            "source_prefix_chars": self.source_prefix_chars,
            "producer_wall_time_sec": round(self.producer_wall_time_sec, 4),
            "non_text_state_transfer_count": len(self.non_text_events),
            "non_text_state_bytes": non_text_bytes,
            "kv_storage": self.kv_storage,
        }


def set_env() -> None:
    os.environ.setdefault("VLLM_MODEL_PATH", "/data/models/Qwen3-8B")
    os.environ.setdefault("VLLM_MAX_MODEL_LEN", "8192")
    os.environ.setdefault("VLLM_MAX_NUM_SEQS", "1")
    os.environ.setdefault("VLLM_MAX_NUM_BATCHED_TOKENS", "4096")
    os.environ.setdefault("VLLM_GPU_MEMORY_UTILIZATION", "0.55")
    os.environ.setdefault("VLLM_TENSOR_PARALLEL_SIZE", "1")
    os.environ.setdefault("VLLM_DTYPE", "bfloat16")
    os.environ.setdefault("VLLM_TRUST_REMOTE_CODE", "1")
    os.environ.setdefault("VLLM_ENFORCE_EAGER", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        os.environ.pop(name, None)


def direct_llm_kwargs() -> dict[str, Any]:
    kwargs = build_llm_kwargs(storage_path="/tmp/unused_longtext_abc_stats", enable_prefix_caching=False)
    kwargs.pop("kv_transfer_config", None)
    return kwargs


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_bytes(value: Any) -> int:
    return len(json_text(value).encode("utf-8"))


def trim(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 80:
        return text[:max_chars]
    keep_head = max_chars // 3
    keep_tail = max_chars - keep_head - 40
    return f"{text[:keep_head]}\n...[trimmed {len(text) - max_chars} chars]...\n{text[-keep_tail:]}"


def load_source_context(root: Path, dataset: dict[str, Any]) -> str:
    return (root / dataset["source_context_file"]).read_text(encoding="utf-8")


def source_prefix(dataset: dict[str, Any], source_context: str, mode: str) -> str:
    contract = dataset.get("final_deliverable_contract", {})
    if mode == "structured":
        packet = {
            "protocol": "structured-longtext-source-packet",
            "group": dataset.get("group"),
            "total_rounds": dataset.get("total_rounds"),
            "source_context_file": dataset.get("source_context_file"),
            "source_chars": len(source_context),
            "source_hash": sha16(source_context),
            "recommended_mode": dataset.get("recommended_mode"),
            "systems": [
                "map", "movement", "time_left", "stamina", "wind_lane", "cloud_wall",
                "storm", "shield", "fragile_package", "multi_order", "cargo_slots",
                "supply", "items", "weather_script", "upgrades", "score", "grade",
            ],
            "final_deliverable_contract": contract,
        }
        return "[Structured source context packet]\n" + json.dumps(packet, ensure_ascii=False, indent=2)
    return (
        f"[Long source design document: {dataset.get('source_context_file')}]\n"
        f"{source_context}\n\n"
        "[Final deliverable contract]\n"
        f"{json.dumps(contract, ensure_ascii=False, indent=2)}"
    )


def align_prefix(tokenizer, prefix: str, *, block_size: int = 16) -> tuple[str, int]:
    adjusted = prefix
    token_ids = tokenizer.encode(adjusted)
    pad_count = 0
    while len(token_ids) % block_size == 0:
        pad_count += 1
        adjusted += f"\n[KV alignment pad {pad_count}]\n"
        token_ids = tokenizer.encode(adjusted)
    return adjusted, pad_count


def count_storage_files(path: Path) -> dict[str, Any]:
    files = [item for item in path.rglob("*") if item.is_file()]
    total_bytes = sum(item.stat().st_size for item in files)
    return {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "sample_files": [str(item.relative_to(path)) for item in files[:8]],
    }


def count_tokens(tokenizer, text: str) -> int:
    return len(tokenizer.encode(text or ""))


def task_brief(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "round": task.get("round"),
        "id": task.get("id"),
        "question": task.get("question"),
        "constraints": task.get("constraints"),
        "answer_format": task.get("answer_format"),
        "depends_on": task.get("memory", {}).get("reuses_from_rounds", []),
        "final_artifacts": task.get("final_artifacts"),
    }


def text_history(previous_outputs: list[dict[str, Any]], max_chars: int = 6000) -> str:
    if not previous_outputs:
        return "No previous round state."
    chunks = []
    for item in previous_outputs:
        chunks.append(
            f"[Round {item['round']} / task {item['task_id']} full textual handoff]\n"
            f"Planner:\n{item.get('planner', '')}\n"
            f"Analyst:\n{item.get('analysis', '')}\n"
            f"Final:\n{item.get('summary', '')}\n"
        )
    return trim("\n---\n".join(chunks), max_chars)


def structured_history(previous_outputs: list[dict[str, Any]], max_items: int = 9) -> dict[str, Any]:
    rounds = []
    for item in previous_outputs[-max_items:]:
        rounds.append({
            "round": item["round"],
            "task_id": item["task_id"],
            "answer_tags": item.get("answer_tags", ""),
            "summary": trim(item.get("summary", ""), 520),
            "analysis_digest": trim(item.get("analysis", ""), 360),
            "output_hash": item.get("summary_hash", ""),
            "output_chars": len(item.get("summary", "")),
        })
    return {
        "protocol": "round-state-packet",
        "carried_rounds": rounds,
        "carried_count": len(rounds),
    }


def mode_state(mode: str, previous_outputs: list[dict[str, Any]]) -> str:
    if mode == "text":
        return text_history(previous_outputs)
    return json.dumps(structured_history(previous_outputs), ensure_ascii=False, indent=2)


def make_prompt(agent: str, mode: str, source: str, payload: str) -> tuple[str, str]:
    system = f"[System]\n{SYSTEM_PROMPT}\n\n[Mode]\n{mode}\n\n[Agent Role]\n{agent}\n"
    if mode in {"text", "structured"}:
        full = f"{system}\n{source}\n\n{payload}\n\n[Assistant answer]\n"
        return full, full
    suffix = f"\n{system}\n{payload}\n\n[Assistant answer]\n"
    return source + suffix, suffix


def fit_payload_to_context(
    tokenizer,
    *,
    agent: str,
    mode: str,
    source: str,
    payload: str,
    max_tokens: int,
) -> tuple[str, str, str, list[int]]:
    """Trim the variable suffix/payload if a late-round prompt exceeds vLLM limits."""

    max_model_len = int(os.environ.get("VLLM_MAX_MODEL_LEN", "8192"))
    prompt, text_transfer = make_prompt(agent, mode, source, payload)
    prompt_ids = tokenizer.encode(prompt)
    if len(prompt_ids) + max_tokens <= max_model_len:
        return payload, prompt, text_transfer, prompt_ids

    original_payload = payload
    payload_budget_chars = len(original_payload)
    for _ in range(14):
        prompt_limit = max_model_len - max_tokens
        ratio = max(prompt_limit, 1) / max(len(prompt_ids), 1)
        next_budget = int(payload_budget_chars * ratio * 0.82)
        if next_budget >= payload_budget_chars:
            next_budget = payload_budget_chars - max(160, (len(prompt_ids) + max_tokens - max_model_len) * 4)
        payload_budget_chars = max(600, next_budget)
        payload = trim(original_payload, payload_budget_chars)
        prompt, text_transfer = make_prompt(agent, mode, source, payload)
        prompt_ids = tokenizer.encode(prompt)
        if len(prompt_ids) + max_tokens <= max_model_len:
            return payload, prompt, text_transfer, prompt_ids

    raise RuntimeError(
        f"prompt too long after trimming for round payload agent={agent} mode={mode}: "
        f"prompt_tokens={len(prompt_ids)} max_tokens={max_tokens} max_model_len={max_model_len}"
    )


def generate_batch(
    llm,
    tokenizer,
    *,
    round_id: int,
    task_id: int,
    agent_names: list[str],
    mode: str,
    source: str,
    payloads: list[str],
    max_tokens: int,
    source_tokens: int,
) -> tuple[list[str], list[LLMCall]]:
    from vllm import SamplingParams

    prompts: list[str] = []
    text_transfers: list[str] = []
    prompt_ids_list: list[list[int]] = []
    for agent, payload in zip(agent_names, payloads):
        _, prompt, text_transfer, prompt_ids = fit_payload_to_context(
            tokenizer,
            agent=agent,
            mode=mode,
            source=source,
            payload=payload,
            max_tokens=max_tokens,
        )
        prompts.append(prompt)
        text_transfers.append(text_transfer)
        prompt_ids_list.append(prompt_ids)

    started = time.perf_counter()
    outputs = llm.generate(
        [{"prompt_token_ids": prompt_ids} for prompt_ids in prompt_ids_list],
        SamplingParams(temperature=0.0, max_tokens=max_tokens),
        use_tqdm=False,
    )
    wall = time.perf_counter() - started
    wall_each = wall / max(len(agent_names), 1)
    texts = [out.outputs[0].text if out.outputs else "" for out in outputs]
    calls: list[LLMCall] = []
    for agent, prompt, prompt_ids, text_transfer, text in zip(
        agent_names, prompts, prompt_ids_list, text_transfers, texts
    ):
        prompt_tokens = len(prompt_ids)
        kv_reused = min(source_tokens, prompt_tokens) if mode == "true_kv_transfer" else 0
        effective_prompt = max(0, prompt_tokens - kv_reused)
        calls.append(LLMCall(
            round_id=round_id,
            task_id=task_id,
            agent=agent,
            prompt_tokens=prompt_tokens,
            prompt_chars=len(prompt),
            effective_prompt_tokens=effective_prompt,
            kv_reused_tokens=kv_reused,
            output_tokens=count_tokens(tokenizer, text),
            output_chars=len(text),
            text_transfer_tokens=count_tokens(tokenizer, text_transfer) if mode == "true_kv_transfer" else prompt_tokens,
            text_transfer_chars=len(text_transfer) if mode == "true_kv_transfer" else len(prompt),
            wall_time_sec=round(wall_each, 4),
        ))
    return texts, calls


def generate_one(*args, **kwargs) -> tuple[str, LLMCall]:
    texts, calls = generate_batch(*args, **kwargs)
    return texts[0], calls[0]


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    try:
        return json.loads(stripped)
    except Exception:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start:end + 1])
            except Exception:
                return {}
    return {}


def answer_tags_from_task(task: dict[str, Any]) -> str:
    return str(task.get("answer_format", ""))


def make_message_stats(
    tokenizer,
    *,
    round_id: int,
    mode: str,
    task: dict[str, Any],
    planner_text: str,
    researchers: list[str],
    analysis: str,
    execution_summary: str,
) -> list[AgentMessageStat]:
    payload_by_edge: dict[tuple[str, str], str] = {}
    for idx in range(1, RESEARCHER_COUNT + 1):
        payload_by_edge[("planner", f"researcher_{idx}")] = planner_text
        payload_by_edge[(f"researcher_{idx}", "analyst")] = researchers[idx - 1]
    payload_by_edge[("analyst", "executor")] = analysis
    payload_by_edge[("executor", "summarizer")] = execution_summary
    stats = []
    for source, target in INTER_AGENT_EDGES:
        text = payload_by_edge[(source, target)]
        if mode != "text":
            packet = {
                "source": source,
                "target": target,
                "round": task.get("round"),
                "task_id": task.get("id"),
                "payload_hash": sha16(text),
                "payload_chars": len(text),
                "payload_digest": trim(text, 480),
            }
            text = json.dumps(packet, ensure_ascii=False, indent=2)
        stats.append(AgentMessageStat(
            round_id=round_id,
            source=source,
            target=target,
            action=edge_action(source, target),
            text_chars=len(text),
            text_tokens=count_tokens(tokenizer, text),
        ))
    return stats


def edge_action(source: str, target: str) -> str:
    if source == "planner":
        return "plan_to_research"
    if source.startswith("researcher"):
        return "research_to_analysis"
    if source == "analyst":
        return "analysis_to_execution"
    return "execution_to_summary"


def structured_non_text_events_for_round(
    *,
    round_id: int,
    messages: list[AgentMessageStat],
) -> list[NonTextEvent]:
    events = []
    for msg in messages:
        packet = {
            "protocol": "AgentMessage",
            "round": round_id,
            "source": msg.source,
            "target": msg.target,
            "action": msg.action,
            "payload_text_tokens": msg.text_tokens,
            "payload_text_chars": msg.text_chars,
        }
        events.append(NonTextEvent(
            round_id=round_id,
            event_type="structured_agent_message",
            source=msg.source,
            target=msg.target,
            size_bytes=json_bytes(packet),
            note="Typed protocol object serialized outside free-form text passthrough.",
        ))
    return events


def truekv_lookup_events_for_round(
    *,
    round_id: int,
    task_id: int,
    source_tokens: int,
    handle_bytes: int,
) -> list[NonTextEvent]:
    events = []
    for agent in ["planner", "researcher_1", "researcher_2", "researcher_3", "analyst", "summarizer"]:
        events.append(NonTextEvent(
            round_id=round_id,
            event_type="kv_handle_lookup",
            source="SharedStorageConnector",
            target=agent,
            size_bytes=handle_bytes,
            note=f"task_id={task_id}; source_prefix_tokens={source_tokens}",
        ))
    return events


def execution_step(task: dict[str, Any], analysis: str, researchers: list[str]) -> str:
    required = answer_tags_from_task(task)
    combined = "\n".join([analysis, *researchers])
    tag_hits = {
        tag: (tag in combined)
        for tag in ["@round", "@feature_scope", "@depends_on", "@new_systems", "@deliverable"]
    }
    return json.dumps({
        "ok": True,
        "round": task.get("round"),
        "task_id": task.get("id"),
        "required_answer_format": required,
        "tag_hits": tag_hits,
        "covered_tag_count": sum(tag_hits.values()),
        "note": "deterministic validation executor; no LLM call",
    }, ensure_ascii=False, indent=2)


def round_metric_from_delta(
    *,
    round_id: int,
    task_id: int,
    wall_time_sec: float,
    calls: list[LLMCall],
    messages: list[AgentMessageStat],
    non_text_events: list[NonTextEvent],
) -> RoundMetric:
    return RoundMetric(
        round_id=round_id,
        task_id=task_id,
        wall_time_sec=round(wall_time_sec, 4),
        llm_call_count=len(calls),
        inter_agent_message_count=len(messages),
        text_transfer_tokens=sum(call.text_transfer_tokens for call in calls),
        text_transfer_chars=sum(call.text_transfer_chars for call in calls),
        effective_prompt_tokens=sum(call.effective_prompt_tokens for call in calls),
        logical_prompt_tokens=sum(call.prompt_tokens for call in calls),
        output_tokens=sum(call.output_tokens for call in calls),
        kv_reused_tokens=sum(call.kv_reused_tokens for call in calls),
        non_text_state_events=len(non_text_events),
        non_text_state_bytes=sum(event.size_bytes for event in non_text_events),
    )


def run_round(
    llm,
    tokenizer,
    *,
    mode: str,
    source: str,
    source_tokens: int,
    task: dict[str, Any],
    previous_outputs: list[dict[str, Any]],
    truekv_handle_bytes: int,
    output_mode_dir: Path,
) -> tuple[dict[str, Any], list[LLMCall], list[AgentMessageStat], list[NonTextEvent], RoundMetric]:
    round_id = int(task.get("round", 0))
    task_id = int(task.get("id", 0))
    round_started = time.perf_counter()
    current_state = mode_state(mode, previous_outputs)
    task_payload = json.dumps(task_brief(task), ensure_ascii=False, indent=2)

    planner_payload = f"""[Current round task]
{task_payload}

[Previous round state]
{current_state}

Create a concise implementation plan for this round.
Return ONLY JSON: {{"plan":"...","sub_queries":["...","...","..."],"answer_tags":"{answer_tags_from_task(task)}"}}
"""
    planner_text, planner_call = generate_one(
        llm, tokenizer,
        round_id=round_id, task_id=task_id,
        agent_names=["planner"], mode=mode, source=source,
        payloads=[planner_payload], max_tokens=ROLE_MAX_TOKENS["planner"],
        source_tokens=source_tokens,
    )
    parsed_plan = extract_json(planner_text)
    sub_queries = parsed_plan.get("sub_queries") if isinstance(parsed_plan.get("sub_queries"), list) else []
    if len(sub_queries) < RESEARCHER_COUNT:
        sub_queries = [
            "state model and compatibility with previous rounds",
            "rule interactions, edge cases, and deterministic tests",
            "implementation checklist and final answer tags",
        ]
    sub_queries = [str(item) for item in sub_queries[:RESEARCHER_COUNT]]

    researcher_payloads = []
    for idx, sub_query in enumerate(sub_queries, start=1):
        researcher_payloads.append(f"""[Current round task]
{task_payload}

[Planner JSON/text]
{planner_text}

[Assigned sub-query for researcher_{idx}]
{sub_query}

[Previous round state]
{current_state}

Return ONLY JSON: {{"researcher":"researcher_{idx}","findings":["..."],"dependencies":["..."],"tests":["..."],"answer_tags":"{answer_tags_from_task(task)}"}}
""")
    researcher_texts, researcher_calls = generate_batch(
        llm, tokenizer,
        round_id=round_id, task_id=task_id,
        agent_names=[f"researcher_{idx}" for idx in range(1, RESEARCHER_COUNT + 1)],
        mode=mode, source=source, payloads=researcher_payloads,
        max_tokens=ROLE_MAX_TOKENS["researcher"], source_tokens=source_tokens,
    )

    analyst_payload = f"""[Current round task]
{task_payload}

[Planner]
{planner_text}

[Researcher outputs]
{json.dumps({f'researcher_{idx}': text for idx, text in enumerate(researcher_texts, start=1)}, ensure_ascii=False, indent=2)}

[Previous round state]
{current_state}

Consolidate the round specification and identify carried state for the next round.
Return ONLY JSON: {{"analysis":"...","round_summary":"...","carried_state":["..."],"answer_tags":"{answer_tags_from_task(task)}"}}
"""
    analysis_text, analyst_call = generate_one(
        llm, tokenizer,
        round_id=round_id, task_id=task_id,
        agent_names=["analyst"], mode=mode, source=source,
        payloads=[analyst_payload], max_tokens=ROLE_MAX_TOKENS["analyst"],
        source_tokens=source_tokens,
    )

    execution_summary = execution_step(task, analysis_text, researcher_texts)

    summarizer_payload = f"""[Current round task]
{task_payload}

[Planner]
{planner_text}

[Analysis]
{analysis_text}

[Deterministic executor result]
{execution_summary}

[Previous round state]
{current_state}

Produce the round deliverable. Keep it concise but include the required answer tags.
Return JSON unless the round explicitly requires file blocks.
"""
    final_max_tokens = ROLE_MAX_TOKENS["summarizer_final"] if round_id == 10 else ROLE_MAX_TOKENS["summarizer"]
    summary_text, summarizer_call = generate_one(
        llm, tokenizer,
        round_id=round_id, task_id=task_id,
        agent_names=["summarizer"], mode=mode, source=source,
        payloads=[summarizer_payload], max_tokens=final_max_tokens,
        source_tokens=source_tokens,
    )

    calls = [planner_call, *researcher_calls, analyst_call, summarizer_call]
    messages = make_message_stats(
        tokenizer,
        round_id=round_id,
        mode=mode,
        task=task,
        planner_text=planner_text,
        researchers=researcher_texts,
        analysis=analysis_text,
        execution_summary=execution_summary,
    )
    non_text_events: list[NonTextEvent] = []
    if mode == "structured":
        non_text_events.extend(structured_non_text_events_for_round(round_id=round_id, messages=messages))
    elif mode == "true_kv_transfer":
        non_text_events.extend(truekv_lookup_events_for_round(
            round_id=round_id,
            task_id=task_id,
            source_tokens=source_tokens,
            handle_bytes=truekv_handle_bytes,
        ))

    output = {
        "round": round_id,
        "task_id": task_id,
        "planner": planner_text,
        "researchers": researcher_texts,
        "analysis": analysis_text,
        "execution_summary": execution_summary,
        "summary": summary_text,
        "answer_tags": answer_tags_from_task(task),
        "summary_hash": sha16(summary_text),
    }
    round_dir = output_mode_dir / f"round_{round_id:02d}"
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / "round_output.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    (round_dir / "planner.md").write_text(planner_text, encoding="utf-8")
    for idx, text in enumerate(researcher_texts, start=1):
        (round_dir / f"researcher_{idx}.md").write_text(text, encoding="utf-8")
    (round_dir / "analyst.md").write_text(analysis_text, encoding="utf-8")
    (round_dir / "executor.json").write_text(execution_summary, encoding="utf-8")
    (round_dir / "summarizer.md").write_text(summary_text, encoding="utf-8")

    wall_time = time.perf_counter() - round_started
    round_metric = round_metric_from_delta(
        round_id=round_id,
        task_id=task_id,
        wall_time_sec=wall_time,
        calls=calls,
        messages=messages,
        non_text_events=non_text_events,
    )
    return output, calls, messages, non_text_events, round_metric


def run_mode(mode: str, output_dir: Path, dataset: dict[str, Any], source_context: str, max_rounds: int) -> ModeResult:
    set_env()
    from vllm import LLM, SamplingParams

    result = ModeResult(mode=mode)
    mode_started = time.perf_counter()
    storage_path = output_dir / "true_kv_shared_storage" if mode == "true_kv_transfer" else output_dir / f"unused_{mode}_storage"
    storage_path.mkdir(parents=True, exist_ok=True)
    llm_kwargs = build_llm_kwargs(storage_path=storage_path, enable_prefix_caching=False) if mode == "true_kv_transfer" else direct_llm_kwargs()

    load_started = time.perf_counter()
    llm = LLM(**llm_kwargs)
    tokenizer = llm.get_tokenizer()
    result.model_load_wall_time_sec = time.perf_counter() - load_started

    src = source_prefix(dataset, source_context, "structured" if mode == "structured" else "text")
    if mode == "true_kv_transfer":
        src, _ = align_prefix(tokenizer, src)
    result.source_prefix_tokens = count_tokens(tokenizer, src)
    result.source_prefix_chars = len(src)
    truekv_handle_bytes = 0

    if mode == "true_kv_transfer":
        producer_started = time.perf_counter()
        _ = llm.generate([src], SamplingParams(temperature=0.0, max_tokens=1), use_tqdm=False)
        result.producer_wall_time_sec = time.perf_counter() - producer_started
        handle = make_handoff_handle(
            prompt=src,
            prompt_tokens=result.source_prefix_tokens,
            storage_path=storage_path,
            producer_agent="longtext_10round_context_prefill",
        )
        handle_dict = handle.to_dict()
        truekv_handle_bytes = json_bytes(handle_dict)
        storage_after_producer = count_storage_files(storage_path)
        result.kv_storage = {
            "handoff_handle": handle_dict,
            "storage_after_producer": storage_after_producer,
            "kv_transfer_config": build_shared_storage_kv_transfer_config(storage_path),
        }
        result.non_text_events.append(NonTextEvent(
            round_id=0,
            event_type="kv_tensor_store_prefill",
            source="context_prefill",
            target="SharedStorageConnector",
            size_bytes=int(storage_after_producer.get("total_bytes", 0)),
            note=f"source_prefix_tokens={result.source_prefix_tokens}; file_count={storage_after_producer.get('file_count', 0)}",
        ))

    previous_outputs: list[dict[str, Any]] = []
    output_mode_dir = output_dir / "round_outputs" / mode
    tasks = dataset.get("tasks", [])[:max_rounds]
    for task in tasks:
        print(f"[longtext-abc] mode={mode} round={task.get('round')} task_id={task.get('id')}", flush=True)
        output, calls, messages, non_text_events, round_metric = run_round(
            llm,
            tokenizer,
            mode=mode,
            source=src,
            source_tokens=result.source_prefix_tokens if mode == "true_kv_transfer" else 0,
            task=task,
            previous_outputs=previous_outputs,
            truekv_handle_bytes=truekv_handle_bytes,
            output_mode_dir=output_mode_dir,
        )
        previous_outputs.append(output)
        result.calls.extend(calls)
        result.messages.extend(messages)
        result.non_text_events.extend(non_text_events)
        result.rounds.append(round_metric)
        print(json.dumps({"mode": mode, "round_metric": asdict(round_metric)}, ensure_ascii=False), flush=True)

    result.mode_wall_time_sec = time.perf_counter() - mode_started
    del llm
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass
    return result


def pct_reduction(base: float, new: float) -> float:
    return round((base - new) / base * 100, 2) if base else 0.0


def write_mode_files(output_dir: Path, result: ModeResult) -> None:
    mode_dir = output_dir / "metrics" / result.mode
    mode_dir.mkdir(parents=True, exist_ok=True)
    (mode_dir / "calls.json").write_text(json.dumps([asdict(call) for call in result.calls], ensure_ascii=False, indent=2), encoding="utf-8")
    (mode_dir / "messages.json").write_text(json.dumps([asdict(msg) for msg in result.messages], ensure_ascii=False, indent=2), encoding="utf-8")
    (mode_dir / "non_text_events.json").write_text(json.dumps([asdict(event) for event in result.non_text_events], ensure_ascii=False, indent=2), encoding="utf-8")
    (mode_dir / "rounds.json").write_text(json.dumps([asdict(item) for item in result.rounds], ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / f"{result.mode}.json").write_text(json.dumps({
        "mode": result.mode,
        "aggregate": result.aggregate(),
        "rounds": [asdict(item) for item in result.rounds],
        "kv_storage": result.kv_storage,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def write_report(output_dir: Path, summary: dict[str, Any]) -> None:
    metrics = summary["metrics"]
    rows = []
    for label, mode in [("A", "text"), ("B", "structured"), ("C", "true_kv_transfer")]:
        item = metrics[mode]
        rows.append(
            f"| {label} | `{mode}` | {item['rounds_completed']} | {item['llm_call_count']} | "
            f"{item['inter_agent_message_count']} | {item['text_transfer_tokens']} | {item['text_transfer_chars']} | "
            f"{item['non_text_state_transfer_count']} | {item['non_text_state_bytes']} | "
            f"{item['sum_round_wall_time_sec']} | {item['avg_single_task_wall_time_sec']} | {item['mode_wall_time_sec']} |"
        )

    round_rows = []
    modes = ["text", "structured", "true_kv_transfer"]
    round_count = max(len(summary["rounds"].get(mode, [])) for mode in modes)
    for idx in range(round_count):
        cells = []
        round_id = idx + 1
        task_id = ""
        for mode in modes:
            item = summary["rounds"].get(mode, [])[idx]
            round_id = item["round_id"]
            task_id = item["task_id"]
            cells.append(f"{item['wall_time_sec']}s / {item['text_transfer_tokens']}tok / {item['non_text_state_events']}evt")
        round_rows.append(f"| {round_id} | {task_id} | {cells[0]} | {cells[1]} | {cells[2]} |")

    edge_lines = []
    all_edges = sorted({
        edge
        for mode in modes
        for edge in metrics[mode].get("message_edge_counts", {})
    })
    for edge in all_edges:
        edge_lines.append(
            f"| `{edge}` | {metrics['text']['message_edge_counts'].get(edge, 0)} | "
            f"{metrics['structured']['message_edge_counts'].get(edge, 0)} | "
            f"{metrics['true_kv_transfer']['message_edge_counts'].get(edge, 0)} |"
        )

    c = metrics.get("true_kv_transfer", {})
    a = metrics.get("text", {})
    b = metrics.get("structured", {})
    kv_storage = c.get("kv_storage", {}).get("storage_after_producer", {})
    report = f"""# LongText 十轮 A/B/C 通信统计验证

## 实验设置

- 任务源：`{summary['task_file']}`，共 `{summary['total_rounds']}` 轮。
- 逻辑拓扑：`planner → researcher_1/2/3 → analyst → executor → summarizer`。
- 每轮 LLM Agent 调用：`6` 次；executor 是确定性验证步骤，不调用 LLM。
- A/text：传全文长文档和文本状态；B/structured：传压缩 source/state packet 和 typed message；C/trueKV：长源文档通过 `SharedStorageConnector` 预填充 KV，Agent prompt 只把 suffix/state 计为文本通信。
- Agent 间消息数按业务 Agent 边统计，不包含 `summarizer → output`。

## 总体对比

| 组别 | 模式 | 轮数 | LLM调用 | Agent间消息 | 文本通信tokens | 文本通信chars | 非文本状态次数 | 非文本状态bytes | 十轮任务耗时合计(s) | 单任务平均耗时(s) | 模式总耗时含加载(s) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

## 单任务逐轮耗时 / 文本tokens / 非文本事件

| round | task_id | A/text | B/structured | C/trueKV |
| ---: | ---: | --- | --- | --- |
{chr(10).join(round_rows)}

## Agent 间消息次数分布

| edge | A/text | B/structured | C/trueKV |
| --- | ---: | ---: | ---: |
{chr(10).join(edge_lines)}

## trueKV 与结构化收益

- C vs A 文本通信 tokens 降低：`{pct_reduction(a.get('text_transfer_tokens', 0), c.get('text_transfer_tokens', 0))}%`
- C vs A 文本通信 chars 降低：`{pct_reduction(a.get('text_transfer_chars', 0), c.get('text_transfer_chars', 0))}%`
- C vs A effective total tokens 降低：`{pct_reduction(a.get('effective_total_tokens', 0), c.get('effective_total_tokens', 0))}%`
- C vs B 文本通信 tokens 降低：`{pct_reduction(b.get('text_transfer_tokens', 0), c.get('text_transfer_tokens', 0))}%`
- B vs A 文本通信 tokens 降低：`{pct_reduction(a.get('text_transfer_tokens', 0), b.get('text_transfer_tokens', 0))}%`

## 非文本状态说明

- A/text：无非文本状态传递，统计为 `0`。
- B/structured：非文本状态事件是 typed `AgentMessage`/state packet 的结构化对象，bytes 为 JSON 序列化后的协议对象大小。
- C/trueKV：非文本状态事件包含 1 次 KV tensor store prefill，以及每个 LLM Agent 调用的 KV handle lookup；KV tensor bytes 按 shared storage 实际文件大小统计。
- C/trueKV source prefix tokens：`{c.get('source_prefix_tokens')}`；producer wall time：`{c.get('producer_wall_time_sec')}`；KV 文件数：`{kv_storage.get('file_count')}`；KV tensor bytes：`{kv_storage.get('total_bytes')}`。

## 产物索引

| 文件 | 说明 |
| --- | --- |
| `{output_dir / 'summary.json'}` | 总体汇总指标 |
| `{output_dir / 'text.json'}` | A/text 指标 |
| `{output_dir / 'structured.json'}` | B/structured 指标 |
| `{output_dir / 'true_kv_transfer.json'}` | C/trueKV 指标 |
| `{output_dir / 'metrics'}` | calls/messages/non_text_events/rounds 明细 |
| `{output_dir / 'round_outputs'}` | 每轮各 Agent 原始输出 |
"""
    (output_dir / "communication_report.md").write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks-file", type=Path, default=DEFAULT_TASKS_FILE)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--modes", nargs="+", choices=MODES, default=MODES)
    parser.add_argument("--max-rounds", type=int, default=10)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    set_env()
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / f"longtext_10round_abc_stats_{time.strftime('%Y%m%d_%H%M%S')}")
    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset = read_json(args.tasks_file)
    source_context = load_source_context(ROOT, dataset)
    results: dict[str, ModeResult] = {}
    for mode in args.modes:
        print(f"[longtext-abc] running mode={mode}", flush=True)
        result = run_mode(mode, output_dir, dataset, source_context, args.max_rounds)
        results[mode] = result
        write_mode_files(output_dir, result)
        print(json.dumps({"mode": mode, "aggregate": result.aggregate()}, ensure_ascii=False, indent=2), flush=True)

    combined_metrics: dict[str, Any] = {}
    combined_rounds: dict[str, Any] = {}
    for mode in MODES:
        if mode in results:
            combined_metrics[mode] = results[mode].aggregate()
            combined_rounds[mode] = [asdict(item) for item in results[mode].rounds]
            continue
        existing = output_dir / f"{mode}.json"
        if existing.exists():
            payload = json.loads(existing.read_text(encoding="utf-8"))
            combined_metrics[mode] = payload.get("aggregate", {})
            combined_rounds[mode] = payload.get("rounds", [])

    summary = {
        "experiment_dir": str(output_dir),
        "task_file": str(args.tasks_file.relative_to(ROOT) if args.tasks_file.is_relative_to(ROOT) else args.tasks_file),
        "total_rounds": min(int(dataset.get("total_rounds", len(dataset.get("tasks", [])))), args.max_rounds),
        "source_context_file": dataset.get("source_context_file"),
        "topology": "planner -> 3*researcher -> analyst -> executor -> summarizer",
        "settings": {
            "model": os.environ.get("VLLM_MODEL_PATH"),
            "temperature": 0.0,
            "role_max_tokens": ROLE_MAX_TOKENS,
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "vllm_max_model_len": os.environ.get("VLLM_MAX_MODEL_LEN"),
            "vllm_gpu_memory_utilization": os.environ.get("VLLM_GPU_MEMORY_UTILIZATION"),
        },
        "metrics": combined_metrics,
        "rounds": combined_rounds,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if all(mode in combined_metrics for mode in MODES):
        write_report(output_dir, summary)
        print(json.dumps({
            "summary": str(output_dir / "summary.json"),
            "report": str(output_dir / "communication_report.md"),
        }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
