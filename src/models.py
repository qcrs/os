"""Chat model backends for the multi-agent demo."""

from functools import lru_cache
from threading import Lock
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import (
    CHAT_API_KEY,
    CHAT_BACKEND,
    CHAT_BASE_URL,
    CHAT_DISABLE_THINKING,
    CHAT_MODEL,
    LOCAL_HIDDEN_POOLING,
    LOCAL_HIDDEN_ROUND_DECIMALS,
    LOCAL_MODEL_DEVICE,
    LOCAL_MODEL_DTYPE,
    LOCAL_MODEL_PATH,
    LOCAL_TRANSFORMERS_MAX_NEW_TOKENS,
)

_TRANSFORMERS_LOCK = Lock()


class LocalTransformersChatModel:
    """Minimal local Transformers chat wrapper with optional hidden-state capture."""

    def __init__(self, temperature: float = 0.7, capture_hidden: bool = False):
        self.temperature = temperature
        self.capture_hidden = capture_hidden
        self.model_name = CHAT_MODEL

    def _make_hidden_state_payload(self, tokenizer, model, inputs: dict, input_tokens: int) -> dict | None:
        if not self.capture_hidden:
            return None
        return _capture_pre_generation_hidden_state(
            tokenizer=tokenizer,
            model=model,
            inputs=inputs,
            input_tokens=input_tokens,
        )

    def invoke(self, messages: list[BaseMessage]) -> AIMessage:
        with _TRANSFORMERS_LOCK:
            tokenizer, model = _load_local_transformers_model()
            prompt = _format_chat_prompt(tokenizer, messages)
            inputs = tokenizer(prompt, return_tensors="pt")
            device = model.device
            inputs = {key: value.to(device) for key, value in inputs.items()}
            input_tokens = int(inputs["input_ids"].shape[-1])

            generation_kwargs: dict[str, Any] = {
                "max_new_tokens": LOCAL_TRANSFORMERS_MAX_NEW_TOKENS,
                "return_dict_in_generate": True,
                "pad_token_id": tokenizer.eos_token_id,
            }
            if self.temperature > 0:
                generation_kwargs.update({"do_sample": True, "temperature": self.temperature})
            else:
                generation_kwargs.update({"do_sample": False})

            import torch

            hidden_state_payload = self._make_hidden_state_payload(
                tokenizer, model, inputs, input_tokens
            )

            with torch.inference_mode():
                generated = model.generate(**inputs, **generation_kwargs)
            sequences = generated.sequences
            output_ids = sequences[0, input_tokens:]
            content = tokenizer.decode(output_ids, skip_special_tokens=True).strip()
            content = _strip_thinking(content)
            output_tokens = int(output_ids.shape[-1])

        response_metadata = {
            "model_name": self.model_name,
            "backend": "transformers",
        }
        if hidden_state_payload is not None:
            response_metadata["hidden_state_payload"] = hidden_state_payload

        return AIMessage(
            content=content,
            usage_metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
            response_metadata=response_metadata,
        )


@lru_cache(maxsize=1)
def _load_local_transformers_model():
    """Load tokenizer/model once per process."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    dtype_by_name = {
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float16": torch.float16,
        "fp16": torch.float16,
        "float32": torch.float32,
        "fp32": torch.float32,
    }
    torch_dtype = dtype_by_name.get(LOCAL_MODEL_DTYPE.lower(), torch.bfloat16)
    tokenizer = AutoTokenizer.from_pretrained(LOCAL_MODEL_PATH, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        LOCAL_MODEL_PATH,
        torch_dtype=torch_dtype,
        trust_remote_code=True,
    )
    model.to(LOCAL_MODEL_DEVICE)
    model.eval()
    return tokenizer, model


def _format_chat_prompt(tokenizer, messages: list[BaseMessage]) -> str:
    chat_messages = []
    for message in messages:
        if isinstance(message, SystemMessage):
            role = "system"
        elif isinstance(message, HumanMessage):
            role = "user"
        elif isinstance(message, AIMessage):
            role = "assistant"
        else:
            role = getattr(message, "type", "user")
        chat_messages.append({"role": role, "content": str(message.content)})

    try:
        return tokenizer.apply_chat_template(
            chat_messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=not CHAT_DISABLE_THINKING,
        )
    except TypeError:
        return tokenizer.apply_chat_template(
            chat_messages,
            tokenize=False,
            add_generation_prompt=True,
        )


def _strip_thinking(content: str) -> str:
    if "</think>" not in content:
        return content
    return content.split("</think>", 1)[1].strip()


def _capture_pre_generation_hidden_state(
    *,
    tokenizer,
    model,
    inputs: dict,
    input_tokens: int,
) -> dict:
    """Capture the last-layer hidden state before the first generated token."""
    import hashlib
    import math
    import torch

    with torch.inference_mode():
        outputs = model(**inputs, output_hidden_states=True, use_cache=False)

    last_hidden = outputs.hidden_states[-1][0]
    attention_mask = inputs.get("attention_mask")
    if attention_mask is None:
        attention_mask = torch.ones_like(inputs["input_ids"])
    attention_mask = attention_mask[0].to(last_hidden.dtype)
    sequence_length = int(attention_mask.sum().item())
    hidden_sequence_length = int(last_hidden.shape[0])
    if sequence_length <= 0:
        sequence_length = hidden_sequence_length
    sequence_length = min(sequence_length, hidden_sequence_length)

    if LOCAL_HIDDEN_POOLING == "mean":
        hidden_slice = last_hidden[:sequence_length]
        pooled = hidden_slice.mean(dim=0)
        pooled_token_span = "prompt_tokens"
    else:
        pooled = last_hidden[sequence_length - 1]
        pooled_token_span = "prompt_last_token"

    pooled = pooled.detach().float().cpu()
    norm = math.sqrt(float(torch.dot(pooled, pooled)))
    vector = [round(float(value), LOCAL_HIDDEN_ROUND_DECIMALS) for value in pooled.tolist()]
    token_ids = inputs["input_ids"][0, :sequence_length].detach().cpu().tolist()
    token_fingerprint = ",".join(str(token_id) for token_id in token_ids)
    source_token_hash = hashlib.sha256(token_fingerprint.encode("utf-8")).hexdigest()[:16]
    return {
        "kind": "transformer_hidden_state",
        "capture_stage": "pre_generation",
        "source": "prompt",
        "prediction_target": "next_token",
        "model": CHAT_MODEL,
        "model_path": LOCAL_MODEL_PATH,
        "layer": -1,
        "pooling": LOCAL_HIDDEN_POOLING,
        "pooled_token_span": pooled_token_span,
        "dims": len(vector),
        "norm": round(norm, 6),
        "dtype": "float32_serialized",
        "vector": vector,
        "source_token_hash": source_token_hash,
        "source_text_hash": source_token_hash,
        "input_tokens": input_tokens,
        "output_tokens": 0,
        "next_token_index": sequence_length,
    }


def get_model(temperature: float = 0.7, capture_hidden: bool = False):
    """Get the configured chat model instance."""
    if CHAT_BACKEND == "transformers":
        return LocalTransformersChatModel(
            temperature=temperature,
            capture_hidden=capture_hidden,
        )

    extra_body = None
    if CHAT_DISABLE_THINKING:
        extra_body = {"chat_template_kwargs": {"enable_thinking": False}}

    return ChatOpenAI(
        base_url=CHAT_BASE_URL,
        api_key=CHAT_API_KEY,
        model=CHAT_MODEL,
        temperature=temperature,
        extra_body=extra_body,
    )
