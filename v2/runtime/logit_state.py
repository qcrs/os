from __future__ import annotations

import math
import struct


def _coerce_logprob(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _distribution_items(last_token_payload: object) -> list[object]:
    if isinstance(last_token_payload, dict):
        top_items = last_token_payload.get("top_logprobs")
        if isinstance(top_items, list) and top_items:
            return list(top_items)
        logprob = _coerce_logprob(last_token_payload.get("logprob"))
        if logprob is not None:
            return [last_token_payload]
        if all(_coerce_logprob(value) is not None for value in last_token_payload.values()):
            return [
                {"token": token, "logprob": value}
                for token, value in last_token_payload.items()
            ]
        return []
    top_items = getattr(last_token_payload, "top_logprobs", None)
    if isinstance(top_items, list) and top_items:
        return list(top_items)
    logprob = _coerce_logprob(getattr(last_token_payload, "logprob", None))
    if logprob is not None:
        return [last_token_payload]
    return []


def _extract_logprob_values(top_logprobs: list[object], top_k: int) -> list[float]:
    if not top_logprobs:
        return []
    distribution = _distribution_items(top_logprobs[-1])[:top_k]
    values: list[float] = []
    for item in distribution:
        logprob = None
        if isinstance(item, dict):
            logprob = _coerce_logprob(item.get("logprob"))
        else:
            logprob = _coerce_logprob(getattr(item, "logprob", None))
        if logprob is not None:
            values.append(logprob)
    return values


def serialize_logit_state(
    top_logprobs: list[object],
    top_k: int = 20,
) -> tuple[bytes, float, float]:
    """Serialize the final-step top-k token distribution to float32 binary.

    Returns ``(payload_bytes, entropy, confidence_proxy)``.
    ``top_logprobs`` is expected to be ``choices[0].logprobs.content`` from the
    OpenAI-compatible response. The final content item may arrive either as:
    - SDK objects with ``.logprob`` and ``.top_logprobs``
    - JSON dicts with ``logprob`` and ``top_logprobs``
    - a legacy ``{token: logprob}`` dict
    """
    logprob_values = _extract_logprob_values(top_logprobs, top_k=top_k)
    if not logprob_values:
        return b"", 0.0, 0.0
    probs = [math.exp(float(lp)) for lp in logprob_values]
    total = sum(probs) or 1.0
    probs = [p / total for p in probs]
    entropy = -sum(p * math.log(p + 1e-12) for p in probs)
    max_entropy = math.log(len(probs)) if len(probs) > 1 else 1.0
    confidence_proxy = 1.0 - (entropy / max_entropy) if max_entropy > 0 else 1.0
    payload = struct.pack(f"<{len(probs)}f", *probs)
    return payload, entropy, confidence_proxy
