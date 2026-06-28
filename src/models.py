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
    LOCAL_MODEL_DEVICE,
    LOCAL_MODEL_DTYPE,
    LOCAL_MODEL_PATH,
    LOCAL_TRANSFORMERS_MAX_NEW_TOKENS,
)

_TRANSFORMERS_LOCK = Lock()


class LocalTransformersChatModel:
    """Minimal local Transformers chat wrapper."""

    def __init__(self, temperature: float = 0.7):
        self.temperature = temperature
        self.model_name = CHAT_MODEL

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



def get_model(temperature: float = 0.7):
    """Get the configured chat model instance."""
    if CHAT_BACKEND == "transformers":
        return LocalTransformersChatModel(temperature=temperature)

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
