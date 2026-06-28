"""vLLM-backed prefix-cache handoff runtime.

vLLM does not expose a stable public raw-KV cache object to application code.
This module therefore implements Agent-level non-text state transfer as a
cache handle over vLLM's internal prefix cache: agents pass a compact
`cache_id`/`prefix_hash` handle, while the runtime reuses the exact same token
prefix so vLLM can hit its internal KV cache.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, asdict
from functools import lru_cache
from typing import Any

from config import (
    CHAT_DISABLE_THINKING,
    CHAT_MODEL,
    VLLM_DTYPE,
    VLLM_ENABLE_PREFIX_CACHING,
    VLLM_ENFORCE_EAGER,
    VLLM_GPU_MEMORY_UTILIZATION,
    VLLM_MAX_MODEL_LEN,
    VLLM_MAX_NUM_BATCHED_TOKENS,
    VLLM_MAX_NUM_SEQS,
    VLLM_MAX_NEW_TOKENS,
    VLLM_MODEL_PATH,
    VLLM_TENSOR_PARALLEL_SIZE,
    VLLM_TRUST_REMOTE_CODE,
)
from metrics import metrics


@dataclass
class PrefixCacheEntry:
    """Metadata for one shared vLLM prefix-cache handle."""

    cache_id: str
    state_type: str
    backend: str
    reuse_mode: str
    model: str
    model_path: str
    prefix_hash: str
    prefix_chars: int
    prefix_tokens: int
    created_by: str
    created_at: float
    parent_cache_id: str | None = None

    def to_handle(self) -> dict:
        """Serialize the handle that can safely cross Agent boundaries."""
        return asdict(self)


class VLLMPrefixCacheRuntime:
    """Small wrapper around vLLM with explicit Agent-level cache handles."""

    def __init__(self):
        self._entries: dict[str, PrefixCacheEntry] = {}
        self._prefix_by_cache_id: dict[str, str] = {}
        self._llm = None
        self._sampling_params_cls = None
        self._tokenizer = None

    def prefill(self, *, query: str, source_context: str, task_group: str, created_by: str) -> dict:
        """Register the shared long prefix and warm vLLM's internal prefix cache."""
        shared_prefix = build_shared_prefix(query=query, source_context=source_context)
        entry = self._make_entry(
            prefix=shared_prefix,
            created_by=created_by,
            parent_cache_id=None,
        )
        self._entries[entry.cache_id] = entry
        self._prefix_by_cache_id[entry.cache_id] = shared_prefix

        warmup_prompt = shared_prefix + (
            "\n[ContextPrefillAgent]\n"
            "The shared source context above is now registered for downstream agents.\n"
            "Reply with JSON: {\"prefill\": true}\n"
        )
        t0 = time.perf_counter()
        self._generate_prompt(warmup_prompt, max_tokens=8, temperature=0.0)
        duration = time.perf_counter() - t0
        metrics.record_timing("vllm_cache_prefill_warmup", duration)
        metrics.increment("vllm_prefix_cache_created")
        metrics.increment("vllm_prefix_cache_prefill_tokens", entry.prefix_tokens)

        handle = entry.to_handle()
        handle["task_group"] = task_group
        return handle

    def prefill_source(self, *, query: str, source_context: str, task_group: str, created_by: str) -> dict:
        """Create a stable source-document cache anchor for token-saving mode.

        Unlike the V1 chain cache, this handle is not extended with every
        downstream output. Each round starts from this same source anchor and
        appends only a bounded state capsule plus the current instruction.
        """
        handle = self.prefill(
            query=query,
            source_context=source_context,
            task_group=task_group,
            created_by=created_by,
        )
        handle["reuse_mode"] = "source_anchor_cache"
        cache_id = handle.get("cache_id")
        if cache_id in self._entries:
            self._entries[cache_id].reuse_mode = "source_anchor_cache"
        metrics.increment("vllm_source_anchor_created")
        metrics.increment("vllm_source_anchor_tokens", int(handle.get("prefix_tokens") or 0))
        return handle

    def generate_with_source_cache(
        self,
        *,
        source_cache: dict,
        agent_name: str,
        state_capsule: dict | str | None,
        instruction: str,
        retrieved_snippets: list[str] | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> tuple[str, dict]:
        """Generate from a stable source cache plus bounded state.

        The generated output is not appended to the next round's source prefix.
        A temporary round cache is registered for traceability, while the caller
        should update a bounded state capsule for subsequent rounds.
        """
        source_cache_id = source_cache["cache_id"]
        source_prefix = self._prefix_by_cache_id[source_cache_id]
        state_text = _format_state_capsule(state_capsule)
        snippets_text = _format_retrieved_snippets(retrieved_snippets or [])
        instruction_text = instruction.strip()
        suffix_parts = []
        if state_text:
            suffix_parts.append("[Bounded state capsule]\n" + state_text)
        if snippets_text:
            suffix_parts.append("[Retrieved historical snippets]\n" + snippets_text)
        suffix_parts.append("[Current instruction]\n" + instruction_text)
        suffix_text = "\n\n".join(suffix_parts)
        prompt = source_prefix + "\n" + suffix_text + "\n"

        t0 = time.perf_counter()
        text = self._generate_prompt(
            prompt,
            max_tokens=max_tokens or VLLM_MAX_NEW_TOKENS,
            temperature=temperature,
        )
        duration = time.perf_counter() - t0

        source_entry = self._entries[source_cache_id]
        round_entry = self._make_entry(
            prefix=prompt,
            created_by=agent_name,
            parent_cache_id=source_cache_id,
            reuse_mode="bounded_round_cache",
        )
        self._entries[round_entry.cache_id] = round_entry
        self._prefix_by_cache_id[round_entry.cache_id] = prompt

        state_tokens = self.count_tokens(state_text)
        instruction_tokens = self.count_tokens(instruction_text)
        snippet_tokens = self.count_tokens(snippets_text)
        suffix_tokens = self.count_tokens(suffix_text)
        output_tokens = self.count_tokens(text)

        metrics.record_timing(f"vllm_cache_v2_generate_{agent_name}", duration)
        metrics.record_tokens(f"cache_v2_{agent_name}", suffix_tokens, output_tokens)
        metrics.increment("vllm_source_anchor_reuses")
        metrics.increment("vllm_source_anchor_reused_tokens", source_entry.prefix_tokens)
        metrics.increment("vllm_bounded_state_tokens", state_tokens)
        metrics.increment("vllm_bounded_instruction_tokens", instruction_tokens)
        metrics.increment("vllm_bounded_snippet_tokens", snippet_tokens)

        handle = round_entry.to_handle()
        handle["last_agent"] = agent_name
        handle["source_cache_id"] = source_cache_id
        handle["source_prefix_tokens"] = source_entry.prefix_tokens
        handle["state_capsule_tokens"] = state_tokens
        handle["instruction_tokens"] = instruction_tokens
        handle["retrieved_snippet_tokens"] = snippet_tokens
        handle["last_suffix_tokens"] = suffix_tokens
        handle["last_output_tokens"] = output_tokens
        handle["last_duration_sec"] = round(duration, 6)
        handle["logical_prompt_tokens"] = round_entry.prefix_tokens
        handle["app_new_input_tokens"] = suffix_tokens
        handle["reuse_mode"] = "bounded_round_cache"
        return text, handle

    def generate_from_cache(
        self,
        *,
        cache_handle: dict,
        agent_name: str,
        instruction: str,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> tuple[str, dict]:
        """Generate by extending and reusing the prefix behind a cache handle.

        The incoming handle points to the full cached token prefix produced by
        previous agents. This call appends the current agent instruction, lets
        vLLM generate the agent artifact, then registers ``prompt + output`` as
        the next handoff prefix. Downstream agents therefore inherit both the
        original source context and prior agents' model-produced state without
        re-sending that state through the LangGraph message payload.
        """
        cache_id = cache_handle["cache_id"]
        parent_prefix = self._prefix_by_cache_id[cache_id]
        instruction_text = instruction.strip()
        prompt = parent_prefix + "\n" + instruction_text + "\n"
        t0 = time.perf_counter()
        text = self._generate_prompt(
            prompt,
            max_tokens=max_tokens or VLLM_MAX_NEW_TOKENS,
            temperature=temperature,
        )
        duration = time.perf_counter() - t0

        parent = self._entries[cache_id]
        next_prefix = self._build_next_prefix(prompt=prompt, output=text)
        new_entry = self._make_entry(
            prefix=next_prefix,
            created_by=agent_name,
            parent_cache_id=cache_id,
        )
        self._entries[new_entry.cache_id] = new_entry
        self._prefix_by_cache_id[new_entry.cache_id] = next_prefix

        suffix_tokens = self.count_tokens(instruction_text)
        output_tokens = self.count_tokens(text)
        metrics.record_timing(f"vllm_cache_generate_{agent_name}", duration)
        metrics.record_tokens(f"cache_{agent_name}", suffix_tokens, output_tokens)
        metrics.increment("vllm_prefix_cache_transfers")
        metrics.increment("vllm_prefix_cache_hits")
        metrics.increment("vllm_prefix_cache_reused_tokens", parent.prefix_tokens)
        metrics.increment("vllm_prefix_cache_agent_suffix_tokens", suffix_tokens)

        handle = new_entry.to_handle()
        handle["last_agent"] = agent_name
        handle["last_suffix_tokens"] = suffix_tokens
        handle["last_output_tokens"] = output_tokens
        handle["last_duration_sec"] = round(duration, 6)
        handle["inherited_prefix_tokens"] = parent.prefix_tokens
        handle["state_delta_tokens"] = new_entry.prefix_tokens - parent.prefix_tokens
        return text, handle

    def count_tokens(self, text: str) -> int:
        """Count tokens with vLLM's tokenizer when available."""
        tokenizer = self._get_tokenizer()
        try:
            return len(tokenizer.encode(text))
        except Exception:
            return max(len(text) // 4, 1) if text else 0

    def _build_next_prefix(self, *, prompt: str, output: str) -> str:
        """Return the exact generated sequence used as the next cache prefix."""
        return prompt + output.strip() + "\n"

    def _make_entry(
        self,
        *,
        prefix: str,
        created_by: str,
        parent_cache_id: str | None,
        reuse_mode: str = "implicit_prefix_cache",
    ) -> PrefixCacheEntry:
        prefix_hash = hash_text(prefix)
        stamp = int(time.time() * 1000)
        seed = f"{prefix_hash}:{created_by}:{parent_cache_id or ''}:{stamp}"
        cache_id = "vllm_prefix_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        return PrefixCacheEntry(
            cache_id=cache_id,
            state_type="vllm_prefix_cache",
            backend="vllm",
            reuse_mode=reuse_mode,
            model=CHAT_MODEL,
            model_path=VLLM_MODEL_PATH,
            prefix_hash=prefix_hash,
            prefix_chars=len(prefix),
            prefix_tokens=self.count_tokens(prefix),
            created_by=created_by,
            created_at=time.time(),
            parent_cache_id=parent_cache_id,
        )

    def _generate_prompt(self, prompt: str, *, max_tokens: int, temperature: float) -> str:
        llm, sampling_params_cls = self._load_llm()
        sampling_params = sampling_params_cls(
            max_tokens=max_tokens,
            temperature=temperature,
        )
        outputs = llm.generate([prompt], sampling_params, use_tqdm=False)
        if not outputs or not outputs[0].outputs:
            return ""
        return _strip_thinking(outputs[0].outputs[0].text.strip())

    def _get_tokenizer(self):
        if self._tokenizer is None:
            llm, _ = self._load_llm()
            self._tokenizer = llm.get_tokenizer()
        return self._tokenizer

    def _load_llm(self):
        if self._llm is not None:
            return self._llm, self._sampling_params_cls

        from vllm import LLM, SamplingParams

        kwargs: dict[str, Any] = {
            "model": VLLM_MODEL_PATH,
            "dtype": VLLM_DTYPE,
            "max_model_len": VLLM_MAX_MODEL_LEN,
            "max_num_seqs": VLLM_MAX_NUM_SEQS,
            "max_num_batched_tokens": VLLM_MAX_NUM_BATCHED_TOKENS,
            "gpu_memory_utilization": VLLM_GPU_MEMORY_UTILIZATION,
            "tensor_parallel_size": VLLM_TENSOR_PARALLEL_SIZE,
            "trust_remote_code": VLLM_TRUST_REMOTE_CODE,
            "enable_prefix_caching": VLLM_ENABLE_PREFIX_CACHING,
        }
        if VLLM_ENFORCE_EAGER:
            kwargs["enforce_eager"] = True

        self._llm = LLM(**kwargs)
        self._sampling_params_cls = SamplingParams
        return self._llm, self._sampling_params_cls


@lru_cache(maxsize=1)
def get_vllm_cache_runtime() -> VLLMPrefixCacheRuntime:
    """Return a process-local vLLM prefix-cache runtime."""
    return VLLMPrefixCacheRuntime()


def build_shared_prefix(*, query: str, source_context: str) -> str:
    """Build the stable shared prefix that must remain byte-identical."""
    return (
        "You are Qwen3-8B running a multi-agent task in cache handoff mode.\n"
        "All downstream agents must solve the task by reusing this exact shared prefix.\n\n"
        f"Task:\n{query.strip()}\n\n"
        f"Shared source context:\n{source_context.strip()}\n\n"
        "Agent chain: ContextPrefillAgent -> PlannerAgent -> ResearcherAgent -> "
        "AnalystAgent -> ExecutorAgent -> SummarizerAgent.\n"
    )


def _format_state_capsule(state_capsule: dict | str | None) -> str:
    if not state_capsule:
        return ""
    if isinstance(state_capsule, str):
        return state_capsule.strip()
    try:
        return json.dumps(state_capsule, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(state_capsule)


def _format_retrieved_snippets(snippets: list[str]) -> str:
    return "\n---\n".join(str(item).strip() for item in snippets if str(item).strip())


def hash_text(text: str) -> str:
    """Stable short hash for cache prefixes and handles."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def parse_json_object(text: str) -> dict:
    """Best-effort JSON object parser for model outputs."""
    if not text:
        return {}
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        candidate = candidate[start:end + 1]
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _strip_thinking(content: str) -> str:
    if "</think>" not in content:
        return content
    return content.split("</think>", 1)[1].strip()
