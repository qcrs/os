"""Real Latent KV Model Server for D-mode multi-agent collaboration.

This FastAPI server runs INSIDE the Docker container (SynapseX-wmw71) and
provides real latent-forward KV state management using Qwen3-8B via
HuggingFace Transformers.

Key design:
  - Loads Qwen3-8B once on startup (bfloat16, GPU1 by default)
  - Stores past_key_values tensors in memory, indexed by handle_id
  - Supports real latent steps via inputs_embeds (bypasses LM head)
  - Supports token injection and greedy decode from any KV state

Usage (inside container):
    LATENT_KV_SERVER_GPU=1 python3 src/latent_kv_model_server.py

Endpoints:
    GET  /health
    POST /prefill          { text, task_group, created_by }
    POST /latent_steps     { handle_id, n_steps, agent_name }
    POST /inject_tokens    { handle_id, text }
    POST /decode           { handle_id, prompt, max_new_tokens, temperature }
    DELETE /handle/{id}
"""

from __future__ import annotations

import gc
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer

# ---------------------------------------------------------------------------
# Config from env
# ---------------------------------------------------------------------------
MODEL_PATH = os.getenv("VLLM_MODEL_PATH", "/data/models/Qwen3-8B")
SERVER_PORT = int(os.getenv("LATENT_KV_SERVER_PORT", "8101"))
SERVER_HOST = os.getenv("LATENT_KV_SERVER_HOST", "0.0.0.0")
GPU_ID = int(os.getenv("LATENT_KV_SERVER_GPU", "1"))
DTYPE = os.getenv("LATENT_KV_DTYPE", "bfloat16")
# Max handles kept in memory (LRU eviction when exceeded)
MAX_HANDLES = int(os.getenv("LATENT_KV_MAX_HANDLES", "64"))
CHAT_DISABLE_THINKING = os.getenv("CHAT_DISABLE_THINKING", "0").lower() in {"1", "true", "yes"}

# ---------------------------------------------------------------------------
# Global model state
# ---------------------------------------------------------------------------
_model: AutoModelForCausalLM | None = None
_tokenizer: AutoTokenizer | None = None
_device: str = f"cuda:{GPU_ID}"
_embed_scale: float = 1.0  # Typical embedding norm for latent aligner

# KV store: handle_id → { past_key_values, last_hidden, seq_len, meta }
# past_key_values is a list of (k, v) tuples, stored on GPU
_kv_store: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Lifespan: load model once
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model, _tokenizer, _embed_scale, _device

    dtype = torch.bfloat16 if DTYPE == "bfloat16" else torch.float16
    device = f"cuda:{GPU_ID}"
    _device = device

    print(f"[latent-kv-server] Loading {MODEL_PATH} on {device} ({DTYPE}) ...")
    t0 = time.time()

    _tokenizer = AutoTokenizer.from_pretrained(
        MODEL_PATH, trust_remote_code=True, padding_side="left"
    )
    _model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        torch_dtype=dtype,
        device_map=device,
        trust_remote_code=True,
    )
    _model.eval()

    # Compute typical embedding norm for latent aligner scaling
    with torch.no_grad():
        embed_weight = _model.get_input_embeddings().weight  # [vocab, hidden]
        _embed_scale = float(embed_weight.norm(dim=-1).mean().item())

    elapsed = time.time() - t0
    free_gb = torch.cuda.mem_get_info(GPU_ID)[0] / 1024**3
    print(
        f"[latent-kv-server] Model loaded in {elapsed:.1f}s  "
        f"| embed_scale={_embed_scale:.2f}  "
        f"| GPU{GPU_ID} free={free_gb:.1f}GB"
    )

    yield

    # Cleanup on shutdown
    _kv_store.clear()
    del _model
    del _tokenizer
    gc.collect()
    torch.cuda.empty_cache()


app = FastAPI(title="Latent KV Model Server", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_model():
    if _model is None or _tokenizer is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet")


def _get_handle(handle_id: str) -> dict[str, Any]:
    if handle_id not in _kv_store:
        raise HTTPException(status_code=404, detail=f"Handle '{handle_id}' not found")
    return _kv_store[handle_id]


def _compute_kv_bytes(seq_len: int) -> int:
    """Estimate KV bytes for current handle's sequence length."""
    cfg = _model.config
    n_layers = cfg.num_hidden_layers
    n_kv_heads = getattr(cfg, "num_key_value_heads", cfg.num_attention_heads)
    head_dim = cfg.hidden_size // cfg.num_attention_heads
    dtype_bytes = 2  # bfloat16 / float16
    return 2 * n_layers * n_kv_heads * head_dim * dtype_bytes * seq_len


def _apply_latent_aligner(last_hidden: torch.Tensor) -> torch.Tensor:
    """Convert last hidden state to next input embedding.

    Strategy: L2-normalize then scale to match typical embedding magnitude.
    This is the 'normalized_identity' aligner — no learnable parameters.
    Shape: [1, 1, hidden_dim]
    """
    norm = last_hidden.norm(dim=-1, keepdim=True).clamp_min(1e-8)
    return (last_hidden / norm) * _embed_scale


def _decode_clean(token_ids: list[int]) -> str:
    """Decode token ids and strip Qwen3 thinking blocks + special tokens.

    Qwen3-8B in default mode may start with <think>...</think> reasoning.
    We keep the content after </think> (the actual answer), or fall back to
    the full decoded text if no thinking block is present.
    """
    import re
    # Decode raw (keep special tokens so we can parse them)
    raw = _tokenizer.decode(token_ids, skip_special_tokens=False)
    # Strip <think>...</think> block (possibly incomplete at end)
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    # If no closing tag yet, drop everything from <think> onwards
    cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL)
    # Remove remaining special tokens like <|im_start|>, <|im_end|>, <|endoftext|>
    cleaned = re.sub(r"<\|[^|]+\|>", "", cleaned)
    return cleaned.strip()


def _evict_oldest_if_needed():
    """Simple FIFO eviction when handle count exceeds MAX_HANDLES."""
    if len(_kv_store) >= MAX_HANDLES:
        oldest = next(iter(_kv_store))
        entry = _kv_store.pop(oldest)
        # Free GPU tensors explicitly
        del entry["past_key_values"]
        del entry["last_hidden"]
        gc.collect()
        torch.cuda.empty_cache()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class PrefillRequest(BaseModel):
    text: str
    task_group: str = "default"
    created_by: str = "prefill"


class PrefillResponse(BaseModel):
    handle_id: str
    seq_len: int
    kv_bytes: int
    elapsed_ms: float


class LatentStepsRequest(BaseModel):
    handle_id: str
    n_steps: int
    agent_name: str = "latent"


class LatentStepsResponse(BaseModel):
    handle_id: str  # New handle_id (child)
    seq_len: int
    latent_steps_added: int
    kv_bytes: int
    elapsed_ms: float


class InjectTokensRequest(BaseModel):
    handle_id: str
    text: str


class InjectTokensResponse(BaseModel):
    handle_id: str
    tokens_added: int
    seq_len: int
    kv_bytes: int


class DecodeRequest(BaseModel):
    handle_id: str
    prompt: str
    max_new_tokens: int = 256
    temperature: float = 0.0
    # If True, also return the updated handle (with generated tokens in KV)
    keep_handle: bool = True


class DecodeResponse(BaseModel):
    handle_id: str | None  # New handle including generated tokens
    generated_text: str
    tokens_generated: int
    elapsed_ms: float


class HandleMetaResponse(BaseModel):
    handle_id: str
    seq_len: int
    latent_steps_added: int
    kv_bytes: int
    agent: str
    created_at: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    loaded = _model is not None
    free_gb = None
    if loaded and torch.cuda.is_available():
        free_gb = round(torch.cuda.mem_get_info(GPU_ID)[0] / 1024**3, 2)
    return {
        "status": "ok" if loaded else "loading",
        "model": MODEL_PATH if loaded else None,
        "device": _device,
        "handles": len(_kv_store),
        "gpu_free_gb": free_gb,
    }


@app.post("/prefill", response_model=PrefillResponse)
def prefill(req: PrefillRequest):
    _require_model()
    t0 = time.perf_counter()

    tokens = _tokenizer(req.text, return_tensors="pt", truncation=True, max_length=6000)
    input_ids = tokens["input_ids"].to(_device)
    seq_len = int(input_ids.shape[1])

    with torch.no_grad():
        out = _model(
            input_ids=input_ids,
            use_cache=True,
            output_hidden_states=False,
        )

    # Save last hidden state for first latent step (need hidden states)
    # We rerun with output_hidden_states=True to get the last hidden
    with torch.no_grad():
        out_h = _model(
            input_ids=input_ids,
            use_cache=False,  # Already have past_kv, just need hidden
            output_hidden_states=True,
        )
    last_hidden = out_h.hidden_states[-1][:, -1:, :].detach()  # [1, 1, hidden]

    handle_id = f"lkv_{req.task_group}_{uuid.uuid4().hex[:12]}"
    kv_bytes = _compute_kv_bytes(seq_len)

    _evict_oldest_if_needed()
    _kv_store[handle_id] = {
        "past_key_values": out.past_key_values,
        "last_hidden": last_hidden,
        "seq_len": seq_len,
        "latent_steps_added": 0,
        "kv_bytes": kv_bytes,
        "agent": req.created_by,
        "parent_handle_id": None,
        "created_at": time.time(),
        "mode": "prefill",
    }

    elapsed_ms = (time.perf_counter() - t0) * 1000
    return PrefillResponse(
        handle_id=handle_id,
        seq_len=seq_len,
        kv_bytes=kv_bytes,
        elapsed_ms=round(elapsed_ms, 2),
    )


@app.post("/latent_steps", response_model=LatentStepsResponse)
def latent_steps(req: LatentStepsRequest):
    _require_model()
    t0 = time.perf_counter()

    parent = _get_handle(req.handle_id)
    pkv = parent["past_key_values"]
    last_hidden = parent["last_hidden"]  # [1, 1, hidden_dim]

    for _ in range(req.n_steps):
        next_embed = _apply_latent_aligner(last_hidden)  # [1, 1, hidden_dim]
        with torch.no_grad():
            out = _model(
                inputs_embeds=next_embed,
                past_key_values=pkv,
                use_cache=True,
                output_hidden_states=True,
            )
        pkv = out.past_key_values
        last_hidden = out.hidden_states[-1][:, -1:, :].detach()

    new_seq_len = parent["seq_len"] + req.n_steps
    new_kv_bytes = _compute_kv_bytes(new_seq_len)
    new_handle_id = f"{req.handle_id}_{req.agent_name}_{uuid.uuid4().hex[:6]}"

    _evict_oldest_if_needed()
    _kv_store[new_handle_id] = {
        "past_key_values": pkv,
        "last_hidden": last_hidden,
        "seq_len": new_seq_len,
        "latent_steps_added": req.n_steps,
        "kv_bytes": new_kv_bytes,
        "agent": req.agent_name,
        "parent_handle_id": req.handle_id,
        "created_at": time.time(),
        "mode": "latent",
    }

    elapsed_ms = (time.perf_counter() - t0) * 1000
    return LatentStepsResponse(
        handle_id=new_handle_id,
        seq_len=new_seq_len,
        latent_steps_added=req.n_steps,
        kv_bytes=new_kv_bytes,
        elapsed_ms=round(elapsed_ms, 2),
    )


@app.post("/inject_tokens", response_model=InjectTokensResponse)
def inject_tokens(req: InjectTokensRequest):
    """Append tokenized text to a KV handle (role transitions, result text, etc.)."""
    _require_model()

    parent = _get_handle(req.handle_id)
    tokens = _tokenizer(req.text, return_tensors="pt", add_special_tokens=False)
    input_ids = tokens["input_ids"].to(_device)
    tokens_added = int(input_ids.shape[1])

    with torch.no_grad():
        out = _model(
            input_ids=input_ids,
            past_key_values=parent["past_key_values"],
            use_cache=True,
            output_hidden_states=True,
        )

    last_hidden = out.hidden_states[-1][:, -1:, :].detach()
    new_seq_len = parent["seq_len"] + tokens_added
    new_kv_bytes = _compute_kv_bytes(new_seq_len)
    new_handle_id = f"{req.handle_id}_inj_{uuid.uuid4().hex[:6]}"

    _evict_oldest_if_needed()
    _kv_store[new_handle_id] = {
        "past_key_values": out.past_key_values,
        "last_hidden": last_hidden,
        "seq_len": new_seq_len,
        "latent_steps_added": 0,
        "kv_bytes": new_kv_bytes,
        "agent": parent["agent"],
        "parent_handle_id": req.handle_id,
        "created_at": time.time(),
        "mode": "inject",
    }

    return InjectTokensResponse(
        handle_id=new_handle_id,
        tokens_added=tokens_added,
        seq_len=new_seq_len,
        kv_bytes=new_kv_bytes,
    )


@app.post("/decode", response_model=DecodeResponse)
def decode(req: DecodeRequest):
    """Generate tokens from a stored KV state + a prompt continuation.

    Uses a manual token-by-token loop to avoid model.generate() cache_position
    incompatibilities when passing external past_key_values (transformers>=4.40).
    """
    _require_model()
    t0 = time.perf_counter()

    parent = _get_handle(req.handle_id)
    pkv = parent["past_key_values"]

    # Encode the new prompt (continuation only, no BOS re-added)
    prompt_tokens = _tokenizer(req.prompt, return_tensors="pt", add_special_tokens=False)
    prompt_ids = prompt_tokens["input_ids"].to(_device)  # [1, prompt_len]

    # Use <|endoftext|> as hard stop; <|im_end|> is chat-turn marker and will
    # be filtered by _decode_clean — stopping on it prematurely causes 0-token
    # output when the model predicts it as the first continuation token.
    endoftext_id = _tokenizer.convert_tokens_to_ids("<|endoftext|>")
    eos_id = endoftext_id if endoftext_id != _tokenizer.unk_token_id else _tokenizer.eos_token_id
    generated_ids: list[int] = []

    # ── First pass: digest the full prompt against stored KV ──────────────
    with torch.no_grad():
        out = _model(
            input_ids=prompt_ids,
            past_key_values=pkv,
            use_cache=True,
            output_hidden_states=False,
        )
    pkv = out.past_key_values
    next_logits = out.logits[:, -1, :]  # [1, vocab]

    # ── Token-by-token decoding loop ──────────────────────────────────────
    # min_new_tokens: after latent steps the model may lean toward EOS on the
    # very first token; force at least 8 tokens before honouring EOS.
    min_new_tokens = 8
    for step in range(req.max_new_tokens):
        if req.temperature == 0.0:
            next_id = int(next_logits.argmax(dim=-1).item())
        else:
            probs = torch.softmax(next_logits / req.temperature, dim=-1)
            next_id = int(torch.multinomial(probs, 1).item())

        if next_id == eos_id and step >= min_new_tokens:
            break
        if next_id == eos_id and step < min_new_tokens:
            # suppress EOS: pick the next-best token instead
            next_logits[0, next_id] = float("-inf")
            if req.temperature == 0.0:
                next_id = int(next_logits.argmax(dim=-1).item())
            else:
                probs = torch.softmax(next_logits / req.temperature, dim=-1)
                next_id = int(torch.multinomial(probs, 1).item())
        generated_ids.append(next_id)

        next_token = torch.tensor([[next_id]], device=_device)
        with torch.no_grad():
            out = _model(
                input_ids=next_token,
                past_key_values=pkv,
                use_cache=True,
                output_hidden_states=False,
            )
        pkv = out.past_key_values
        next_logits = out.logits[:, -1, :]

    generated_text = _decode_clean(generated_ids)
    tokens_generated = len(generated_ids)

    new_handle_id = None
    if req.keep_handle and generated_ids:
        # pkv already contains the full chain (prefix + prompt + generated tokens)
        # Get last hidden state for potential follow-up latent steps
        last_token = torch.tensor([[generated_ids[-1]]], device=_device)
        with torch.no_grad():
            final_out = _model(
                input_ids=last_token,
                past_key_values=pkv,
                use_cache=True,
                output_hidden_states=True,
            )
        tokens_total = len(prompt_tokens["input_ids"][0]) + tokens_generated
        new_seq_len = parent["seq_len"] + tokens_total
        new_kv_bytes = _compute_kv_bytes(new_seq_len)
        new_handle_id = f"{req.handle_id}_decode_{uuid.uuid4().hex[:6]}"

        _evict_oldest_if_needed()
        _kv_store[new_handle_id] = {
            "past_key_values": final_out.past_key_values,
            "last_hidden": final_out.hidden_states[-1][:, -1:, :].detach(),
            "seq_len": new_seq_len,
            "latent_steps_added": 0,
            "kv_bytes": new_kv_bytes,
            "agent": "decoder",
            "parent_handle_id": req.handle_id,
            "created_at": time.time(),
            "mode": "decode",
        }

    elapsed_ms = (time.perf_counter() - t0) * 1000
    return DecodeResponse(
        handle_id=new_handle_id,
        generated_text=generated_text,
        tokens_generated=tokens_generated,
        elapsed_ms=round(elapsed_ms, 2),
    )


@app.get("/handle/{handle_id}", response_model=HandleMetaResponse)
def get_handle_meta(handle_id: str):
    entry = _get_handle(handle_id)
    return HandleMetaResponse(
        handle_id=handle_id,
        seq_len=entry["seq_len"],
        latent_steps_added=entry["latent_steps_added"],
        kv_bytes=entry["kv_bytes"],
        agent=entry["agent"],
        created_at=entry["created_at"],
    )


@app.delete("/handle/{handle_id}")
def delete_handle(handle_id: str):
    if handle_id not in _kv_store:
        return {"status": "not_found"}
    entry = _kv_store.pop(handle_id)
    del entry["past_key_values"]
    del entry["last_hidden"]
    gc.collect()
    torch.cuda.empty_cache()
    return {"status": "deleted"}


@app.get("/handles")
def list_handles():
    return {
        "count": len(_kv_store),
        "handles": [
            {
                "handle_id": hid,
                "seq_len": v["seq_len"],
                "latent_steps_added": v["latent_steps_added"],
                "agent": v["agent"],
                "mode": v["mode"],
            }
            for hid, v in _kv_store.items()
        ],
    }


# ---------------------------------------------------------------------------
# OpenAI-compatible /v1/chat/completions  (for A/B mode fairness)
# ---------------------------------------------------------------------------
# Minimal subset of the OpenAI Chat Completions API that LangChain needs.

class _ChatMessage(BaseModel):
    role: str
    content: str

class _ChatCompletionsRequest(BaseModel):
    model: str = ""
    messages: list[_ChatMessage]
    max_tokens: int = 512
    temperature: float = 0.0
    stream: bool = False

class _ChatChoice(BaseModel):
    index: int
    message: _ChatMessage
    finish_reason: str

class _ChatUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class _ChatCompletionsResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[_ChatChoice]
    usage: _ChatUsage


def _apply_chat_template(messages: list[_ChatMessage]) -> str:
    """Build Qwen3 chat-format string from message list."""
    chat_messages = [{"role": msg.role, "content": msg.content} for msg in messages]
    try:
        return _tokenizer.apply_chat_template(
            chat_messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=not CHAT_DISABLE_THINKING,
        )
    except TypeError:
        parts = []
        for msg in messages:
            parts.append(f"<|im_start|>{msg.role}\n{msg.content}<|im_end|>")
        parts.append("<|im_start|>assistant\n")
        return "\n".join(parts)


@app.post("/v1/chat/completions", response_model=_ChatCompletionsResponse)
def chat_completions(req: _ChatCompletionsRequest):
    """OpenAI-compatible chat completions — same Transformers engine as D mode.

    Used by A/B modes (via LangChain OpenAI client) so all three modes share
    the same inference backend and the comparison is fair.
    """
    _require_model()
    t0 = time.perf_counter()

    prompt_str = _apply_chat_template(req.messages)
    tokens = _tokenizer(prompt_str, return_tensors="pt", truncation=True, max_length=6000)
    input_ids = tokens["input_ids"].to(_device)
    prompt_len = int(input_ids.shape[1])

    # First forward pass
    with torch.no_grad():
        out = _model(input_ids=input_ids, use_cache=True, output_hidden_states=False)
    pkv = out.past_key_values
    next_logits = out.logits[:, -1, :]

    endoftext_id = _tokenizer.convert_tokens_to_ids("<|endoftext|>")
    eos_id = endoftext_id if endoftext_id != _tokenizer.unk_token_id else _tokenizer.eos_token_id
    im_end_id = _tokenizer.convert_tokens_to_ids("<|im_end|>")

    generated_ids: list[int] = []
    min_new = 4

    for step in range(req.max_tokens):
        if req.temperature == 0.0:
            next_id = int(next_logits.argmax(dim=-1).item())
        else:
            probs = torch.softmax(next_logits / req.temperature, dim=-1)
            next_id = int(torch.multinomial(probs, 1).item())

        # Stop on endoftext; stop on im_end only after min_new tokens
        if next_id == eos_id:
            break
        if next_id == im_end_id and step >= min_new:
            break
        if next_id in (eos_id, im_end_id) and step < min_new:
            next_logits[0, next_id] = float("-inf")
            next_id = int(next_logits.argmax(dim=-1).item())

        generated_ids.append(next_id)
        next_token = torch.tensor([[next_id]], device=_device)
        with torch.no_grad():
            out = _model(input_ids=next_token, past_key_values=pkv,
                         use_cache=True, output_hidden_states=False)
        pkv = out.past_key_values
        next_logits = out.logits[:, -1, :]

    text = _decode_clean(generated_ids)
    comp_len = len(generated_ids)

    return _ChatCompletionsResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
        created=int(time.time()),
        model=MODEL_PATH,
        choices=[_ChatChoice(
            index=0,
            message=_ChatMessage(role="assistant", content=text),
            finish_reason="stop",
        )],
        usage=_ChatUsage(
            prompt_tokens=prompt_len,
            completion_tokens=comp_len,
            total_tokens=prompt_len + comp_len,
        ),
    )


@app.get("/v1/models")
def list_models():
    """OpenAI-compatible model list endpoint."""
    return {
        "object": "list",
        "data": [{"id": MODEL_PATH, "object": "model", "owned_by": "local"}],
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT, log_level="info")
