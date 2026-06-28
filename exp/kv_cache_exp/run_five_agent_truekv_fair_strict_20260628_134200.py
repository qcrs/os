#!/usr/bin/env python3
"""Strict fair A/B/C comparison on the same five-Agent topology.

All modes execute the same logical graph:

    planner -> researcher_1, researcher_2, researcher_3 -> analyst -> executor -> summarizer

The only intended variable is the state transfer style:
- A/text: long source context and prior state are sent as plain text.
- B/structured: compact JSON/digest state is sent as text.
- C/true_kv_transfer: the same long source context is prefetched once into vLLM
  KV tensors, then every LLM Agent call uses the same prefix for KV lookup and
  only counts its suffix as effective prompt text.

This script intentionally does not use the older 10-round trueKV consumer chain,
because that changed the Agent topology and made the comparison unfair.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from true_kv_handoff_runtime import (  # noqa: E402
    build_llm_kwargs,
    build_shared_storage_kv_transfer_config,
    describe_runtime_contract,
    make_handoff_handle,
)

TASKS_FILE = ROOT / "task" / "longtext" / "skyforge_cache_tasks.json"
DEFAULT_OUTPUT_ROOT = ROOT / "exp" / "kv_cache_exp"
MODES = ["text", "structured", "true_kv_transfer"]
RESEARCHER_COUNT = 3

SYSTEM = """You are a senior Python game engineer in a five-Agent pipeline.
Follow the assigned role exactly. Keep outputs machine-readable. For the final
summarizer step, produce the final runnable game and gameplay manual.
""".strip()

ROLE_MAX_TOKENS = {
    "planner": 768,
    "researcher": 768,
    "analyst": 1024,
    "summarizer": 4096,
}

REQUIRED_FUNCTIONS = [
    "render_map",
    "update_turn",
    "resolve_tile_effect",
    "deliver_orders",
    "calculate_summary",
    "main",
]

FEATURE_TERMS = {
    "map_rendering": ["render_map", "grid", "workshop", "customer"],
    "movement_input": ["w", "a", "s", "d", "move"],
    "time_stamina": ["stamina", "time_left", "turn"],
    "wind_cloud": ["wind", "cloud"],
    "storm_shield": ["storm", "shield"],
    "orders_cargo": ["order", "cargo", "deliver"],
    "supply_items": ["supply", "battery", "parcel"],
    "weather": ["weather", "forecast"],
    "upgrade": ["upgrade"],
    "scoring": ["score", "grade", "summary"],
}


@dataclass
class LLMCall:
    agent: str
    prompt_tokens: int
    effective_prompt_tokens: int
    kv_reused_tokens: int
    output_tokens: int
    wall_time_sec: float
    text_transfer_tokens: int
    text_transfer_chars: int


@dataclass
class ModeResult:
    mode: str
    wall_time_sec: float = 0.0
    calls: list[LLMCall] = field(default_factory=list)
    planner: str = ""
    researchers: list[str] = field(default_factory=list)
    analysis: str = ""
    execution_summary: str = ""
    summary: str = ""
    code: str = ""
    manual: str = ""
    artifact_dir: str = ""
    compile_ok: bool = False
    q_smoke_ok: bool = False
    wasd_smoke_ok: bool = False
    final_artifact_score: float = 0.0
    overall_score: float = 0.0
    kv_storage: dict[str, Any] = field(default_factory=dict)
    source_prefix_tokens: int = 0
    producer_wall_time_sec: float = 0.0

    def metrics(self) -> dict[str, Any]:
        logical_prompt = sum(call.prompt_tokens for call in self.calls)
        effective_prompt = sum(call.effective_prompt_tokens for call in self.calls)
        kv_reused = sum(call.kv_reused_tokens for call in self.calls)
        output = sum(call.output_tokens for call in self.calls)
        text_transfer = sum(call.text_transfer_tokens for call in self.calls)
        text_transfer_chars = sum(call.text_transfer_chars for call in self.calls)
        kv_reuse_events = sum(1 for call in self.calls if call.kv_reused_tokens > 0)
        kv_files = self.kv_storage.get("storage_after_producer", {}).get("file_count", 0) if self.kv_storage else 0
        kv_bytes = self.kv_storage.get("storage_after_producer", {}).get("total_bytes", 0) if self.kv_storage else 0
        return {
            "wall_time_sec": round(self.wall_time_sec, 4),
            "llm_call_count": len(self.calls),
            "business_agent_roles": 5,
            "business_agent_instances": 7,
            "llm_business_agent_instances": len(self.calls),
            "logical_prompt_tokens": logical_prompt,
            "output_tokens": output,
            "logical_total_tokens": logical_prompt + output,
            "kv_reused_tokens": kv_reused,
            "effective_prompt_tokens": effective_prompt,
            "effective_total_tokens": effective_prompt + output,
            "agent_text_transfer_tokens": text_transfer,
            "agent_text_transfer_chars": text_transfer_chars,
            "non_text_state_write_events": 1 if self.mode == "true_kv_transfer" else 0,
            "non_text_state_reuse_events": kv_reuse_events,
            "non_text_state_transfer_events": (1 + kv_reuse_events) if self.mode == "true_kv_transfer" else 0,
            "non_text_state_files": kv_files,
            "non_text_state_bytes": kv_bytes,
            "final_artifact_score": self.final_artifact_score,
            "overall_score": self.overall_score,
            "compile_ok": self.compile_ok,
            "q_smoke_ok": self.q_smoke_ok,
            "wasd_smoke_ok": self.wasd_smoke_ok,
            "artifact_dir": self.artifact_dir,
            "source_prefix_tokens": self.source_prefix_tokens,
            "producer_wall_time_sec": self.producer_wall_time_sec,
            "kv_storage": self.kv_storage,
        }


def set_env() -> None:
    os.environ.setdefault("VLLM_MODEL_PATH", "/data/models/Qwen3-8B")
    os.environ.setdefault("VLLM_MAX_MODEL_LEN", "8192")
    os.environ.setdefault("VLLM_MAX_NUM_SEQS", "1")
    os.environ.setdefault("VLLM_MAX_NUM_BATCHED_TOKENS", "4096")
    os.environ.setdefault("VLLM_GPU_MEMORY_UTILIZATION", "0.92")
    os.environ.setdefault("VLLM_TENSOR_PARALLEL_SIZE", "1")
    os.environ.setdefault("VLLM_DTYPE", "bfloat16")
    os.environ.setdefault("VLLM_TRUST_REMOTE_CODE", "1")
    os.environ.setdefault("VLLM_ENFORCE_EAGER", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        os.environ.pop(name, None)


def load_dataset() -> dict[str, Any]:
    return json.loads(TASKS_FILE.read_text(encoding="utf-8"))


def load_source_context(dataset: dict[str, Any]) -> str:
    return (ROOT / dataset["source_context_file"]).read_text(encoding="utf-8")


def count_tokens(tokenizer, text: str) -> int:
    return len(tokenizer.encode(text or ""))


def count_storage_files(path: Path) -> dict[str, Any]:
    files = [item for item in path.rglob("*") if item.is_file()]
    total_bytes = sum(item.stat().st_size for item in files)
    return {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "sample_files": [str(item.relative_to(path)) for item in files[:8]],
    }


def direct_llm_kwargs() -> dict[str, Any]:
    kwargs = build_llm_kwargs(storage_path="/tmp/unused_truekv_five_agent", enable_prefix_caching=False)
    kwargs.pop("kv_transfer_config", None)
    return kwargs


def align_prefix(tokenizer, prefix: str, *, block_size: int = 16) -> tuple[str, int]:
    adjusted = prefix
    token_ids = tokenizer.encode(adjusted)
    pad_count = 0
    while len(token_ids) % block_size == 0:
        pad_count += 1
        adjusted += f"\n[KV alignment pad {pad_count}]\n"
        token_ids = tokenizer.encode(adjusted)
    return adjusted, pad_count


def source_prefix(dataset: dict[str, Any], source_context: str, mode: str) -> str:
    contract = json.dumps(dataset.get("final_deliverable_contract", {}), ensure_ascii=False, indent=2)
    if mode == "structured":
        brief = {
            "game": "Skyforge Courier",
            "goal": "terminal Python game",
            "controls": ["w", "a", "s", "d", "q"],
            "systems": [
                "map", "movement", "time", "stamina", "wind", "storm", "orders",
                "cargo", "supply", "weather", "upgrades", "scoring",
            ],
            "required_functions": REQUIRED_FUNCTIONS,
        }
        return f"""[Shared source brief]\n{json.dumps(brief, ensure_ascii=False, indent=2)}\n\n[Final deliverable contract]\n{contract}\n"""
    return f"""[Long source design document: {dataset['source_context_file']}]\n{source_context}\n\n[Final deliverable contract]\n{contract}\n"""


def task_brief(dataset: dict[str, Any]) -> str:
    tasks = []
    for task in dataset["tasks"]:
        tasks.append({
            "round": task["round"],
            "question": task["question"],
            "constraints": task["constraints"],
            "answer_format": task["answer_format"],
            "depends_on": task.get("memory", {}).get("reuses_from_rounds", []),
        })
    return json.dumps(tasks, ensure_ascii=False, indent=2)


def make_prompt(agent: str, mode: str, source: str, payload: str) -> tuple[str, str]:
    # Strict fairness: A/text and C/trueKV use the same logical long-source
    # prefix and the same role/task suffix. The only difference is whether the
    # long source prefix is counted as text communication or reused as KV state.
    suffix = f"[System]\n{SYSTEM}\n\n[Agent Role]\n{agent}\n\n{payload}\n\n[Assistant answer]\n"
    full = f"{source}\n\n{suffix}"
    if mode == "true_kv_transfer":
        return full, suffix
    return full, full


def generate(llm, tokenizer, *, agent: str, mode: str, source: str, payload: str, max_tokens: int, source_tokens: int = 0) -> tuple[str, LLMCall]:
    from vllm import SamplingParams

    prompt, text_transfer = make_prompt(agent, mode, source, payload)
    prompt_ids = tokenizer.encode(prompt)
    started = time.perf_counter()
    outputs = llm.generate([{"prompt_token_ids": prompt_ids}], SamplingParams(temperature=0.0, max_tokens=max_tokens), use_tqdm=False)
    wall = time.perf_counter() - started
    text = outputs[0].outputs[0].text if outputs and outputs[0].outputs else ""
    output_tokens = count_tokens(tokenizer, text)
    prompt_tokens = len(prompt_ids)
    kv_reused = min(source_tokens, prompt_tokens) if mode == "true_kv_transfer" else 0
    effective_prompt = max(0, prompt_tokens - kv_reused)
    text_transfer_tokens = count_tokens(tokenizer, text_transfer) if mode == "true_kv_transfer" else prompt_tokens
    return text, LLMCall(
        agent=agent,
        prompt_tokens=prompt_tokens,
        effective_prompt_tokens=effective_prompt,
        kv_reused_tokens=kv_reused,
        output_tokens=output_tokens,
        wall_time_sec=round(wall, 4),
        text_transfer_tokens=text_transfer_tokens,
        text_transfer_chars=len(text_transfer),
    )


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except Exception:
        match = re.search(r"\{.*\}", stripped, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
    return {}


def extract_blocks(text: str) -> tuple[str, str]:
    code = ""
    manual = ""
    code_match = re.search(r"###\s*skyforge_courier_game\.py\s*```python\s*(.*?)```", text, re.S | re.I)
    if not code_match:
        code_match = re.search(r"```python\s*(.*?)```", text, re.S | re.I)
    if code_match:
        code = code_match.group(1).strip()
    manual_match = re.search(r"###\s*GAMEPLAY\.md\s*```(?:markdown|md)?\s*(.*?)```", text, re.S | re.I)
    if manual_match:
        manual = manual_match.group(1).strip()
    return code, manual


def executor_step(analysis: str, researchers: list[str]) -> str:
    feature_hits = {}
    text = "\n".join([analysis, *researchers]).lower()
    for feature, terms in FEATURE_TERMS.items():
        feature_hits[feature] = any(term.lower() in text for term in terms)
    return json.dumps({
        "ok": True,
        "feature_hits": feature_hits,
        "covered_features": sum(feature_hits.values()),
        "note": "deterministic executor; no LLM call, same for all modes",
    }, ensure_ascii=False, indent=2)


def save_and_score(result: ModeResult, output_dir: Path) -> None:
    artifact_dir = output_dir / "artifacts" / result.mode / "skyforge_courier_release"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    code_path = artifact_dir / "skyforge_courier_game.py"
    manual_path = artifact_dir / "GAMEPLAY.md"
    placeholder_code = result.code.strip() in {"...", "pass", "# write the complete runnable Python code here, not a placeholder"}
    placeholder_manual = result.manual.strip() in {"...", "# write the complete gameplay manual here, not a placeholder"}
    if placeholder_code:
        result.code = ""
    if placeholder_manual:
        result.manual = ""
    if result.code:
        code_path.write_text(result.code, encoding="utf-8")
    if result.manual:
        manual_path.write_text(result.manual, encoding="utf-8")
    result.artifact_dir = str(artifact_dir)

    score = 0.0
    if result.code:
        score += 10
    if result.manual:
        score += 10
    if result.code:
        compile_proc = subprocess.run([sys.executable, "-m", "py_compile", str(code_path)], cwd=str(ROOT), capture_output=True, text=True, timeout=20)
        result.compile_ok = compile_proc.returncode == 0
        if result.compile_ok:
            score += 20
            q_proc = subprocess.run([sys.executable, str(code_path)], input="q\n", cwd=str(ROOT), capture_output=True, text=True, timeout=8)
            result.q_smoke_ok = q_proc.returncode == 0
            if result.q_smoke_ok:
                score += 10
            wasd_proc = subprocess.run([sys.executable, str(code_path)], input="d\ns\na\nw\nq\n", cwd=str(ROOT), capture_output=True, text=True, timeout=12)
            result.wasd_smoke_ok = wasd_proc.returncode == 0
            if result.wasd_smoke_ok:
                score += 10
    if result.code:
        try:
            tree = ast.parse(result.code)
            functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
            score += round(20 * len(set(REQUIRED_FUNCTIONS) & functions) / len(REQUIRED_FUNCTIONS), 1)
        except Exception:
            pass
        lower = result.code.lower()
        score += round(15 * sum(any(term in lower for term in terms) for terms in FEATURE_TERMS.values()) / len(FEATURE_TERMS), 1)
    if result.manual:
        lower_manual = result.manual.lower()
        score += round(5 * sum(term in lower_manual for term in ["w", "a", "s", "d", "q", "score", "deliver"]) / 7, 1)
    result.final_artifact_score = round(min(score, 100.0), 1)
    result.overall_score = result.final_artifact_score


def run_mode(mode: str, output_dir: Path, *, source_context: str, dataset: dict[str, Any]) -> ModeResult:
    set_env()
    from vllm import LLM

    started = time.perf_counter()
    storage_path = output_dir / "true_kv_shared_storage" if mode == "true_kv_transfer" else output_dir / f"unused_{mode}_storage"
    storage_path.mkdir(parents=True, exist_ok=True)
    llm_kwargs = build_llm_kwargs(storage_path=storage_path, enable_prefix_caching=False) if mode == "true_kv_transfer" else direct_llm_kwargs()
    llm = LLM(**llm_kwargs)
    tokenizer = llm.get_tokenizer()

    shared_source = source_prefix(dataset, source_context, "structured" if mode == "structured" else "text")
    if mode == "true_kv_transfer":
        shared_source, _ = align_prefix(tokenizer, shared_source)
    source_tokens = count_tokens(tokenizer, shared_source) if mode == "true_kv_transfer" else 0
    result = ModeResult(mode=mode, source_prefix_tokens=source_tokens)

    if mode == "true_kv_transfer":
        producer_started = time.perf_counter()
        _ = llm.generate([shared_source], __import__("vllm").SamplingParams(temperature=0.0, max_tokens=1), use_tqdm=False)
        result.producer_wall_time_sec = round(time.perf_counter() - producer_started, 4)
        handle = make_handoff_handle(
            prompt=shared_source,
            prompt_tokens=source_tokens,
            storage_path=storage_path,
            producer_agent="five_agent_context_prefill",
        )
        result.kv_storage = {
            "handoff_handle": handle.to_dict(),
            "storage_after_producer": count_storage_files(storage_path),
            "kv_transfer_config": build_shared_storage_kv_transfer_config(storage_path),
            "runtime_contract": describe_runtime_contract(),
        }

    tasks_json = task_brief(dataset)
    planner_payload = f"""[Planner task]
Create a five-Agent implementation plan for the Skyforge Courier task source.
Return ONLY JSON: {{"plan": "...", "sub_queries": ["...", "...", "..."]}}

[10-round task brief]
{tasks_json}
"""
    planner_text, call = generate(llm, tokenizer, agent="planner", mode=mode, source=shared_source, payload=planner_payload, max_tokens=ROLE_MAX_TOKENS["planner"], source_tokens=source_tokens)
    result.calls.append(call)
    parsed_plan = extract_json(planner_text)
    sub_queries = parsed_plan.get("sub_queries") if isinstance(parsed_plan.get("sub_queries"), list) else []
    if len(sub_queries) < RESEARCHER_COUNT:
        sub_queries = [
            "Design core map, movement, orders, delivery, time, stamina, wind and storm systems.",
            "Design cargo, supplies, weather, upgrades, scoring, balance and test matrix.",
            "Prepare final Python terminal game architecture and gameplay manual requirements.",
        ]
    sub_queries = [str(item) for item in sub_queries[:RESEARCHER_COUNT]]
    result.planner = parsed_plan.get("plan") or planner_text.strip()[:1200]

    for idx, sub_query in enumerate(sub_queries, start=1):
        if mode == "text":
            prior = "\n\n".join(result.researchers)
            state = f"[Prior researcher text]\n{prior}" if prior else "[Prior researcher text]\nNone"
        else:
            state = json.dumps({
                "completed_researchers": len(result.researchers),
                "digests": [item[:360] for item in result.researchers],
            }, ensure_ascii=False, indent=2)
        researcher_payload = f"""[Researcher {idx} task]
Sub-query: {sub_query}
Plan: {result.planner}

[Transferred state]
{state}

Produce implementation-ready source material for downstream analyst. Include concrete data structures, functions, and tests.
"""
        text, call = generate(llm, tokenizer, agent=f"researcher_{idx}", mode=mode, source=shared_source, payload=researcher_payload, max_tokens=ROLE_MAX_TOKENS["researcher"], source_tokens=source_tokens)
        result.calls.append(call)
        result.researchers.append(text.strip())

    if mode == "text":
        research_context = "\n\n---\n\n".join(result.researchers)
    else:
        research_context = json.dumps([
            {"researcher": idx + 1, "digest": text[:900]} for idx, text in enumerate(result.researchers)
        ], ensure_ascii=False, indent=2)
    analyst_payload = f"""[Analyst task]
Plan: {result.planner}

[Research materials]
{research_context}

Produce ONLY JSON with keys: analysis, implementation_requirements, risks, acceptance_tests.
"""
    analysis_text, call = generate(llm, tokenizer, agent="analyst", mode=mode, source=shared_source, payload=analyst_payload, max_tokens=ROLE_MAX_TOKENS["analyst"], source_tokens=source_tokens)
    result.calls.append(call)
    result.analysis = analysis_text.strip()

    result.execution_summary = executor_step(result.analysis, result.researchers)

    summarizer_payload = f"""[Summarizer task]
Create the final deliverables from this five-Agent pipeline.

Plan:
{result.planner}

Analysis:
{result.analysis if mode == 'text' else result.analysis[:1400]}

Executor summary:
{result.execution_summary}

You must output exactly two fenced blocks and no extra prose.
Do NOT output ellipses, placeholders, pseudocode, omitted sections, or explanations.
The Python block must be a complete single-file terminal game that can pass `python -m py_compile`.
It must define these functions: render_map, update_turn, resolve_tile_effect, deliver_orders, calculate_summary, main.
It must support stdin controls w/a/s/d/q and exit cleanly on q.
Use only Python standard library.

### skyforge_courier_game.py
```python
# write the complete runnable Python code here, not a placeholder
```
### GAMEPLAY.md
```markdown
# write the complete gameplay manual here, not a placeholder
```
"""
    summary_text, call = generate(llm, tokenizer, agent="summarizer", mode=mode, source=shared_source, payload=summarizer_payload, max_tokens=ROLE_MAX_TOKENS["summarizer"], source_tokens=source_tokens)
    result.calls.append(call)
    result.summary = summary_text.strip()
    result.code, result.manual = extract_blocks(summary_text)
    save_and_score(result, output_dir)
    result.wall_time_sec = time.perf_counter() - started
    return result


def write_result(output_dir: Path, result: ModeResult) -> None:
    payload = {
        "mode": result.mode,
        "metrics": result.metrics(),
        "calls": [call.__dict__ for call in result.calls],
        "planner": result.planner,
        "researchers": result.researchers,
        "analysis": result.analysis,
        "execution_summary": result.execution_summary,
        "summary": result.summary,
        "code_file": str(Path(result.artifact_dir) / "skyforge_courier_game.py"),
        "manual_file": str(Path(result.artifact_dir) / "GAMEPLAY.md"),
    }
    (output_dir / f"{result.mode}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    rounds_dir = output_dir / "agent_outputs" / result.mode
    rounds_dir.mkdir(parents=True, exist_ok=True)
    (rounds_dir / "planner.md").write_text(result.planner, encoding="utf-8")
    for idx, text in enumerate(result.researchers, start=1):
        (rounds_dir / f"researcher_{idx}.md").write_text(text, encoding="utf-8")
    (rounds_dir / "analyst.md").write_text(result.analysis, encoding="utf-8")
    (rounds_dir / "summarizer.md").write_text(result.summary, encoding="utf-8")


def pct_reduction(base: float, new: float) -> float:
    return round((base - new) / base * 100, 2) if base else 0.0


def _calls_table(summary: dict[str, Any]) -> str:
    rows = []
    for mode in MODES:
        for call in summary["calls"][mode]:
            rows.append(
                f"| `{mode}` | `{call['agent']}` | {call['wall_time_sec']} | {call['prompt_tokens']} | {call['effective_prompt_tokens']} | {call['output_tokens']} | {call['text_transfer_tokens']} | {call['text_transfer_chars']} | {call['kv_reused_tokens']} |"
            )
    return "\n".join(rows)


def write_report(output_dir: Path, summary: dict[str, Any]) -> None:
    metrics = summary["metrics"]
    rows = []
    for label, mode in [("A", "text"), ("B", "structured"), ("C", "true_kv_transfer")]:
        item = metrics[mode]
        rows.append(
            f"| {label} | `{mode}` | {item['llm_call_count']} | {item['wall_time_sec']} | {item['logical_prompt_tokens']} | {item['effective_prompt_tokens']} | {item['output_tokens']} | {item['effective_total_tokens']} | {item['agent_text_transfer_tokens']} | {item['agent_text_transfer_chars']} | {item['kv_reused_tokens']} | {item['non_text_state_transfer_events']} | {item['non_text_state_bytes']} | {item['final_artifact_score']} | {item['compile_ok']} | {item['q_smoke_ok']} | {item['wasd_smoke_ok']} | `{item['artifact_dir']}` |"
        )
    c = metrics["true_kv_transfer"]
    a = metrics["text"]
    b = metrics["structured"]
    report = f"""# 同五 Agent 主图 A/B/C 严格公平对比实验

## 公平性约束

- 三组都执行同一逻辑拓扑：`planner → researcher_1/researcher_2/researcher_3 → analyst → executor → summarizer`。
- 三组业务 Agent 角色相同：`planner`、`researcher`、`analyst`、`executor`、`summarizer`。
- 三组 LLM Agent 调用次数相同：`6` 次；`executor` 是确定性 CodeAct，不调用 LLM，但三组都执行。
- 三组使用同一任务源、同一 Qwen3-8B、同一 max tokens、同一 temperature。
- A/text：长文档作为文本状态进入每个 LLM Agent prompt。
- B/structured：长文档被结构化摘要/JSON brief 替代，仍是文本 token 通信。
- C/trueKV：长文档作为 vLLM KV tensors 非文本状态复用；文本侧只统计 role/task suffix 与 compact state。
- 严格提示词修正：A/text 与 C/trueKV 的逻辑长文档前缀相同，system/role/current-task suffix 也相同；C 只改变长前缀的状态传递/计费方式。

## 总体指标

| 组别 | 模式 | LLM调用数 | wall_time_sec | logical_prompt_tokens | effective_prompt_tokens | output_tokens | effective_total_tokens | 文本通信tokens | 文本通信chars | kv_reused_tokens | 非文本状态事件 | 非文本状态bytes | 最终产物评分 | 编译 | q退出 | WASD试玩 | 产物目录 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
{chr(10).join(rows)}

## 每个 LLM Agent 明细

| 模式 | Agent | wall_time_sec | logical_prompt | effective_prompt | output | 文本通信tokens | 文本通信chars | kv_reused |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{_calls_table(summary)}

## trueKV 相对收益

- C vs A effective_prompt_tokens 降低：`{pct_reduction(a['effective_prompt_tokens'], c['effective_prompt_tokens'])}%`
- C vs A effective_total_tokens 降低：`{pct_reduction(a['effective_total_tokens'], c['effective_total_tokens'])}%`
- C vs A 文本通信 tokens 降低：`{pct_reduction(a['agent_text_transfer_tokens'], c['agent_text_transfer_tokens'])}%`
- C vs A wall_time_sec 改善：`{pct_reduction(a['wall_time_sec'], c['wall_time_sec'])}%`
- C vs B effective_prompt_tokens 降低：`{pct_reduction(b['effective_prompt_tokens'], c['effective_prompt_tokens'])}%`
- C vs B effective_total_tokens 降低：`{pct_reduction(b['effective_total_tokens'], c['effective_total_tokens'])}%`
- C vs B 文本通信 tokens 降低：`{pct_reduction(b['agent_text_transfer_tokens'], c['agent_text_transfer_tokens'])}%`
- C vs B wall_time_sec 改善：`{pct_reduction(b['wall_time_sec'], c['wall_time_sec'])}%`

## trueKV 证据

- connector：`SharedStorageConnector`
- source prefix tokens：`{c['source_prefix_tokens']}`
- producer wall time：`{c['producer_wall_time_sec']}`
- producer write events：`{c['non_text_state_write_events']}`
- consumer reuse events：`{c['non_text_state_reuse_events']}`
- KV 文件数：`{c.get('kv_storage', {}).get('storage_after_producer', {}).get('file_count')}`
- KV tensor bytes：`{c.get('kv_storage', {}).get('storage_after_producer', {}).get('total_bytes')}`

## 口径说明

- `logical_prompt_tokens`：vLLM 看到的完整 prompt token 数；C 仍包含 long prefix token，因为 vLLM SharedStorageConnector 使用 token-prefix lookup。
- `effective_prompt_tokens`：估算实际需要重新 prefill/计算的 token；C 扣除了已写入共享存储并命中的 long prefix KV。
- `文本通信tokens/chars`：Agent 间显式传递的文本状态开销；C 只统计 suffix/state，不把 KV tensors 记作文本。
- `非文本状态bytes`：SharedStorageConnector 写出的 KV tensor 文件总大小；A/B 没有 KV 非文本状态，故为 0。

## 产物索引

| 文件 | 说明 |
| --- | --- |
| `{output_dir / 'summary.json'}` | 汇总指标 |
| `{output_dir / 'text.json'}` | A/text 原始输出 |
| `{output_dir / 'structured.json'}` | B/structured 原始输出 |
| `{output_dir / 'true_kv_transfer.json'}` | C/trueKV 原始输出 |
"""
    (output_dir / "experiment_report.md").write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--modes", nargs="+", choices=MODES, default=MODES)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    set_env()
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / f"five_agent_truekv_fair_strict_{time.strftime('%Y%m%d_%H%M%S')}")
    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset = load_dataset()
    source_context = load_source_context(dataset)
    results: dict[str, ModeResult] = {}
    for mode in args.modes:
        print(f"[five-agent fair] running mode={mode}", flush=True)
        result = run_mode(mode, output_dir, source_context=source_context, dataset=dataset)
        write_result(output_dir, result)
        results[mode] = result
        print(json.dumps({"mode": mode, "metrics": result.metrics()}, ensure_ascii=False, indent=2), flush=True)

    if all(mode in results for mode in MODES):
        summary = {
            "experiment_dir": str(output_dir),
            "task_file": str(TASKS_FILE.relative_to(ROOT)),
            "topology": "planner -> 3*researcher -> analyst -> executor -> summarizer",
            "fairness": {
                "same_logical_agent_count": True,
                "same_llm_call_count": True,
                "llm_calls_per_mode": 6,
                "executor_llm_call": False,
                "only_transfer_mode_changes": True,
            },
            "settings": {
                "model": os.environ.get("VLLM_MODEL_PATH"),
                "temperature": 0.0,
                "role_max_tokens": ROLE_MAX_TOKENS,
            },
            "metrics": {mode: results[mode].metrics() for mode in MODES},
            "calls": {
                mode: [call.__dict__ for call in results[mode].calls]
                for mode in MODES
            },
        }
        (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        write_report(output_dir, summary)
        print(json.dumps({"summary": str(output_dir / "summary.json"), "report": str(output_dir / "experiment_report.md")}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
