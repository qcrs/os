from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Sequence


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _coerce_logprob(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _token_str(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("token", ""))
    return str(getattr(item, "token", ""))


def _distribution_items(token_payload: object) -> list[object]:
    """Extract the top_logprobs list from a single per-position payload.

    Handles three shapes:
    - OpenAI SDK objects with ``.logprob`` and ``.top_logprobs``
    - JSON dicts with ``logprob`` and ``top_logprobs``
    - legacy ``{token: logprob}`` dicts
    """
    if isinstance(token_payload, dict):
        top = token_payload.get("top_logprobs")
        if isinstance(top, list) and top:
            return list(top)
        lp = _coerce_logprob(token_payload.get("logprob"))
        if lp is not None:
            return [token_payload]
        # legacy {token: logprob} mapping
        if all(_coerce_logprob(v) is not None for v in token_payload.values()):
            return [{"token": t, "logprob": v} for t, v in token_payload.items()]
        return []
    top = getattr(token_payload, "top_logprobs", None)
    if isinstance(top, list) and top:
        return list(top)
    lp = _coerce_logprob(getattr(token_payload, "logprob", None))
    if lp is not None:
        return [token_payload]
    return []


def _position_probs_tokens_entropy(
    items: list[object],
    top_k: int,
) -> tuple[list[float], list[str], float]:
    """Compute normalised probabilities, token strings, and Shannon entropy
    for a single token position, retaining at most ``top_k`` entries."""
    probs: list[float] = []
    tokens: list[str] = []
    for item in items[:top_k]:
        lp = _coerce_logprob(
            item.get("logprob") if isinstance(item, dict)
            else getattr(item, "logprob", None)
        )
        if lp is not None:
            probs.append(math.exp(lp))
            tokens.append(_token_str(item))
    if not probs:
        return [], [], 0.0
    total = sum(probs) or 1.0
    probs = [p / total for p in probs]
    h = -sum(p * math.log(p + 1e-12) for p in probs)
    return probs, tokens, h


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LogitStateResult:
    """Full output of :func:`serialize_logit_state_v2`.

    Attributes:
        payload_bytes: float32 little-endian packed normalised probabilities
            at the peak-entropy position.
        entropy: Shannon entropy (nats) at the peak-entropy position.
        confidence_proxy: ``1 - H / H_max`` at the peak-entropy position;
            higher means more certain.
        peak_position: index in ``top_logprobs`` of the highest-entropy
            position; ``-1`` when the input sequence is empty.
        sequence_length: total length of the ``top_logprobs`` sequence.
        aggregated_entropy: weighted-average entropy across the top-N
            highest-entropy positions (more robust than a single-point
            estimate against grammar-forced end tokens).
        varentropy: variance of per-position entropy across all valid
            positions in the sequence; high value indicates a specific
            decision point rather than uniform low-entropy output.
        top_gap: ``p1 - p2`` at the peak-entropy position; a near-zero gap
            means genuine token-level ambiguity, a large gap means
            confident selection.
        decision_entropy: entropy over semantic candidate clusters when
            ``candidate_tokens`` is supplied; ``-1.0`` when not computable.
    """

    payload_bytes: bytes
    entropy: float
    confidence_proxy: float
    peak_position: int
    sequence_length: int
    aggregated_entropy: float
    varentropy: float
    top_gap: float
    decision_entropy: float

    # ------------------------------------------------------------------
    # Back-compat properties for callers that unpack the old 3-tuple shim
    # ------------------------------------------------------------------

    @property
    def legacy_entropy(self) -> float:
        return self.entropy

    @property
    def legacy_confidence_proxy(self) -> float:
        return self.confidence_proxy


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

def serialize_logit_state_v2(
    top_logprobs: list[object],
    top_k: int = 20,
    top_n_positions: int = 3,
    candidate_tokens: Sequence[str] | None = None,
) -> LogitStateResult:
    """Extract decision-uncertainty signals from an output token logprob sequence.

    Unlike the v1 implementation which always samples the *last* token
    (a grammar-closing token whose entropy is structurally ~0), this function
    scans the entire output sequence and returns statistics anchored at the
    position of maximum Shannon entropy — typically the token position where
    the model genuinely chooses among competing candidates.

    Args:
        top_logprobs: ``choices[0].logprobs.content`` from an OpenAI-compatible
            response.  Each element may be an SDK object or a JSON dict.
        top_k: maximum number of top-logprob entries to consider per position.
        top_n_positions: number of highest-entropy positions to include in the
            weighted aggregated entropy.
        candidate_tokens: known candidate values (e.g. enum values) used to
            attempt candidate-level decision entropy computation.

    Returns:
        :class:`LogitStateResult` with payload bytes and all entropy metrics.
    """
    if not top_logprobs:
        return LogitStateResult(
            payload_bytes=b"",
            entropy=0.0,
            confidence_proxy=1.0,
            peak_position=-1,
            sequence_length=0,
            aggregated_entropy=0.0,
            varentropy=0.0,
            top_gap=0.0,
            decision_entropy=-1.0,
        )

    # ── Step 1: per-position entropy scan ────────────────────────────────────
    # Each tuple: (original_index, probs, tokens, entropy)
    position_data: list[tuple[int, list[float], list[str], float]] = []
    for i, token_payload in enumerate(top_logprobs):
        items = _distribution_items(token_payload)
        probs, tokens, h = _position_probs_tokens_entropy(items, top_k=top_k)
        if probs:
            position_data.append((i, probs, tokens, h))

    if not position_data:
        return LogitStateResult(
            payload_bytes=b"",
            entropy=0.0,
            confidence_proxy=1.0,
            peak_position=-1,
            sequence_length=len(top_logprobs),
            aggregated_entropy=0.0,
            varentropy=0.0,
            top_gap=0.0,
            decision_entropy=-1.0,
        )

    # ── Step 2: peak position ────────────────────────────────────────────────
    position_data_sorted = sorted(position_data, key=lambda x: x[3], reverse=True)
    peak_idx, peak_probs, _peak_tokens, peak_entropy = position_data_sorted[0]
    max_h = math.log(len(peak_probs)) if len(peak_probs) > 1 else 1.0
    confidence_proxy = 1.0 - (peak_entropy / max_h) if max_h > 0 else 1.0
    payload = struct.pack(f"<{len(peak_probs)}f", *peak_probs)

    # ── Step 3: top-N weighted aggregated entropy ────────────────────────────
    top_n = position_data_sorted[:top_n_positions]
    weights_raw = [d[3] for d in top_n]
    w_sum = sum(weights_raw) or 1.0
    aggregated_entropy = sum(w * d[3] for w, d in zip(weights_raw, top_n)) / w_sum

    # ── Step 4: varentropy ───────────────────────────────────────────────────
    # Variance of per-position entropy across the whole sequence.
    # High varentropy + moderate mean entropy → specific decision point.
    # Low varentropy → uniformly constrained output (grammar / greedy).
    all_entropies = [d[3] for d in position_data]
    mean_h = sum(all_entropies) / len(all_entropies)
    varentropy = sum((h - mean_h) ** 2 for h in all_entropies) / len(all_entropies)

    # ── Step 5: top-gap ──────────────────────────────────────────────────────
    peak_sorted = sorted(peak_probs, reverse=True)
    top_gap = peak_sorted[0] - (peak_sorted[1] if len(peak_sorted) > 1 else 0.0)

    # ── Step 6: candidate-level decision entropy ─────────────────────────────
    # Attempts a prefix-match between per-position top tokens and the supplied
    # candidate set.  Probabilities for tokens matching the same candidate are
    # pooled, then entropy is computed over the collapsed distribution.
    decision_entropy = -1.0
    if candidate_tokens:
        cand_set = {str(c).lower() for c in candidate_tokens}
        cand_probs: dict[str, float] = {}
        for _, pos_probs, pos_tokens, _ in top_n:
            for prob, token_str in zip(pos_probs, pos_tokens):
                normalized = token_str.strip('"').lower()
                for cand in cand_set:
                    if cand.startswith(normalized) or normalized.startswith(cand):
                        cand_probs[cand] = cand_probs.get(cand, 0.0) + prob
        if cand_probs:
            total = sum(cand_probs.values()) or 1.0
            ps = [v / total for v in cand_probs.values()]
            decision_entropy = -sum(p * math.log(p + 1e-12) for p in ps)

    return LogitStateResult(
        payload_bytes=payload,
        entropy=peak_entropy,
        confidence_proxy=confidence_proxy,
        peak_position=peak_idx,
        sequence_length=len(top_logprobs),
        aggregated_entropy=aggregated_entropy,
        varentropy=varentropy,
        top_gap=top_gap,
        decision_entropy=decision_entropy,
    )


# ---------------------------------------------------------------------------
# Back-compat shim — keeps existing callers (role_path.py, smoke.py) intact
# ---------------------------------------------------------------------------

def serialize_logit_state(
    top_logprobs: list[object],
    top_k: int = 20,
) -> tuple[bytes, float, float]:
    """Back-compatible wrapper returning ``(payload_bytes, entropy, confidence_proxy)``.

    Internally calls :func:`serialize_logit_state_v2` and returns the peak-
    entropy position metrics so that callers pinned to the v1 three-tuple
    interface receive meaningful values instead of the structurally-zero
    last-token entropy produced by the old implementation.

    ``top_logprobs`` is expected to be ``choices[0].logprobs.content`` from
    the OpenAI-compatible response.
    """
    result = serialize_logit_state_v2(top_logprobs, top_k=top_k)
    return result.payload_bytes, result.entropy, result.confidence_proxy
