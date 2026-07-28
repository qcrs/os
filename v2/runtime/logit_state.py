from __future__ import annotations

import math
import json
import struct
from dataclasses import dataclass
from typing import Sequence

from v2.contracts import (
    CandidateSurfaceV2,
    LogitProducerReceipt,
    LogitProducerStatus,
)


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


@dataclass(frozen=True)
class ExactChoiceLogitResult:
    payload_bytes: bytes
    candidate_probabilities: tuple[float, ...]
    other_mass: float
    selected_alias: str
    selected_candidate_id: str
    selected_candidate_ordinal: int
    receipt: LogitProducerReceipt

    @property
    def available(self) -> bool:
        return self.receipt.status is LogitProducerStatus.AVAILABLE

    @property
    def entropy(self) -> float:
        values = (*self.candidate_probabilities, self.other_mass)
        return -sum(value * math.log(value) for value in values if value > 0.0)

    @property
    def normalized_entropy(self) -> float:
        width = len(self.candidate_probabilities) + 1
        return self.entropy / math.log(width) if width > 1 else 0.0

    @property
    def top_margin(self) -> float:
        ordered = sorted(self.candidate_probabilities, reverse=True)
        return ordered[0] - ordered[1] if len(ordered) > 1 else ordered[0]


def _field(item: object, name: str, default: object = None) -> object:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _exact_token_bytes(item: object) -> bytes | None:
    raw = _field(item, "bytes")
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    if isinstance(raw, (list, tuple)):
        try:
            return bytes(int(value) for value in raw)
        except (TypeError, ValueError, OverflowError):
            return None
    token = _field(item, "token")
    return token.encode("utf-8") if isinstance(token, str) else None


def _unavailable_exact_result(
    *,
    candidate_surface: CandidateSurfaceV2,
    request_id: str,
    attempt_id: str,
    reason: str,
    selected_alias: str = "",
    selected_candidate_id: str = "",
    decision_token_position: int = -1,
    sequence_length: int = 0,
    top_k: int = 0,
) -> ExactChoiceLogitResult:
    return ExactChoiceLogitResult(
        payload_bytes=b"",
        candidate_probabilities=(),
        other_mass=0.0,
        selected_alias=selected_alias,
        selected_candidate_id=selected_candidate_id,
        selected_candidate_ordinal=-1,
        receipt=LogitProducerReceipt(
            request_id=request_id,
            attempt_id=attempt_id,
            status=LogitProducerStatus.UNAVAILABLE,
            candidate_surface_digest=candidate_surface.candidate_surface_digest,
            alias_mapping_digest=candidate_surface.alias_mapping_digest,
            selected_alias=selected_alias,
            selected_candidate_id=selected_candidate_id,
            decision_token_position=decision_token_position,
            sequence_length=sequence_length,
            top_k=top_k,
            unavailable_reason=reason,
        ),
    )


def extract_exact_choice_logit_state(
    *,
    completion_text: str,
    top_logprobs: Sequence[object] | None,
    candidate_surface: CandidateSurfaceV2,
    request_id: str,
    attempt_id: str,
    sum_tolerance: float = 1e-5,
) -> ExactChoiceLogitResult:
    """Extract exact A..H choice probabilities from the chosen alias token."""
    sequence = tuple(top_logprobs or ())
    sequence_length = len(sequence)
    try:
        parsed = json.loads(completion_text)
    except (json.JSONDecodeError, TypeError):
        return _unavailable_exact_result(
            candidate_surface=candidate_surface,
            request_id=request_id,
            attempt_id=attempt_id,
            reason="choice_json_invalid",
            sequence_length=sequence_length,
        )
    if not isinstance(parsed, dict) or set(parsed) != {"choice_code"}:
        return _unavailable_exact_result(
            candidate_surface=candidate_surface,
            request_id=request_id,
            attempt_id=attempt_id,
            reason="choice_schema_mismatch",
            sequence_length=sequence_length,
        )
    selected_alias = parsed.get("choice_code")
    if not isinstance(selected_alias, str) or selected_alias not in candidate_surface.aliases:
        return _unavailable_exact_result(
            candidate_surface=candidate_surface,
            request_id=request_id,
            attempt_id=attempt_id,
            reason="choice_alias_outside_surface",
            selected_alias=str(selected_alias or ""),
            sequence_length=sequence_length,
        )
    selected_candidate_id = candidate_surface.candidate_id_for_alias(selected_alias)
    if not sequence:
        return _unavailable_exact_result(
            candidate_surface=candidate_surface,
            request_id=request_id,
            attempt_id=attempt_id,
            reason="top_logprobs_missing",
            selected_alias=selected_alias,
            selected_candidate_id=selected_candidate_id,
        )

    completion_bytes = completion_text.encode("utf-8")
    alias_literal = json.dumps(selected_alias, ensure_ascii=True).encode("ascii")
    literal_offset = completion_bytes.find(alias_literal)
    if literal_offset < 0 or completion_bytes.find(alias_literal, literal_offset + 1) >= 0:
        return _unavailable_exact_result(
            candidate_surface=candidate_surface,
            request_id=request_id,
            attempt_id=attempt_id,
            reason="choice_alias_span_not_unique",
            selected_alias=selected_alias,
            selected_candidate_id=selected_candidate_id,
            sequence_length=sequence_length,
        )
    alias_start = literal_offset + 1
    alias_end = alias_start + len(selected_alias.encode("ascii"))
    spans: list[tuple[int, int, bytes]] = []
    cursor = 0
    for token_payload in sequence:
        token_bytes = _exact_token_bytes(token_payload)
        if token_bytes is None:
            return _unavailable_exact_result(
                candidate_surface=candidate_surface,
                request_id=request_id,
                attempt_id=attempt_id,
                reason="chosen_token_bytes_unavailable",
                selected_alias=selected_alias,
                selected_candidate_id=selected_candidate_id,
                sequence_length=sequence_length,
            )
        spans.append((cursor, cursor + len(token_bytes), token_bytes))
        cursor += len(token_bytes)
    raw_completion_bytes = b"".join(item[2] for item in spans)
    completion_offset = 0
    if raw_completion_bytes != completion_bytes:
        if raw_completion_bytes.strip() != completion_bytes:
            return _unavailable_exact_result(
                candidate_surface=candidate_surface,
                request_id=request_id,
                attempt_id=attempt_id,
                reason="completion_token_bytes_mismatch",
                selected_alias=selected_alias,
                selected_candidate_id=selected_candidate_id,
                sequence_length=sequence_length,
            )
        completion_offset = len(raw_completion_bytes) - len(raw_completion_bytes.lstrip())
    alias_start += completion_offset
    alias_end += completion_offset
    if cursor != len(raw_completion_bytes):
        return _unavailable_exact_result(
            candidate_surface=candidate_surface,
            request_id=request_id,
            attempt_id=attempt_id,
            reason="completion_token_bytes_mismatch",
            selected_alias=selected_alias,
            selected_candidate_id=selected_candidate_id,
            sequence_length=sequence_length,
        )
    overlapping = [
        index
        for index, (start, end, _token) in enumerate(spans)
        if start < alias_end and end > alias_start
    ]
    if len(overlapping) != 1:
        return _unavailable_exact_result(
            candidate_surface=candidate_surface,
            request_id=request_id,
            attempt_id=attempt_id,
            reason="choice_alias_not_single_token",
            selected_alias=selected_alias,
            selected_candidate_id=selected_candidate_id,
            sequence_length=sequence_length,
        )
    decision_position = overlapping[0]
    start, end, chosen_bytes = spans[decision_position]
    if start != alias_start or end != alias_end or chosen_bytes != selected_alias.encode("ascii"):
        return _unavailable_exact_result(
            candidate_surface=candidate_surface,
            request_id=request_id,
            attempt_id=attempt_id,
            reason="choice_alias_not_exact_token_span",
            selected_alias=selected_alias,
            selected_candidate_id=selected_candidate_id,
            decision_token_position=decision_position,
            sequence_length=sequence_length,
        )

    alternatives = _distribution_items(sequence[decision_position])
    probabilities: dict[str, float] = {}
    aliases_by_bytes = {alias.encode("ascii"): alias for alias in candidate_surface.aliases}
    for alternative in alternatives:
        alias = aliases_by_bytes.get(_exact_token_bytes(alternative) or b"")
        if alias is None:
            continue
        if alias in probabilities:
            return _unavailable_exact_result(
                candidate_surface=candidate_surface,
                request_id=request_id,
                attempt_id=attempt_id,
                reason="duplicate_alias_alternative",
                selected_alias=selected_alias,
                selected_candidate_id=selected_candidate_id,
                decision_token_position=decision_position,
                sequence_length=sequence_length,
                top_k=len(alternatives),
            )
        logprob = _coerce_logprob(_field(alternative, "logprob"))
        if logprob is None or not math.isfinite(logprob) or logprob > sum_tolerance:
            return _unavailable_exact_result(
                candidate_surface=candidate_surface,
                request_id=request_id,
                attempt_id=attempt_id,
                reason="top_logprob_invalid",
                selected_alias=selected_alias,
                selected_candidate_id=selected_candidate_id,
                decision_token_position=decision_position,
                sequence_length=sequence_length,
                top_k=len(alternatives),
            )
        probabilities[alias] = math.exp(logprob)
    missing = tuple(alias for alias in candidate_surface.aliases if alias not in probabilities)
    if missing:
        return _unavailable_exact_result(
            candidate_surface=candidate_surface,
            request_id=request_id,
            attempt_id=attempt_id,
            reason=f"candidate_alias_missing:{','.join(missing)}",
            selected_alias=selected_alias,
            selected_candidate_id=selected_candidate_id,
            decision_token_position=decision_position,
            sequence_length=sequence_length,
            top_k=len(alternatives),
        )
    candidate_probabilities = tuple(probabilities[alias] for alias in candidate_surface.aliases)
    candidate_total = sum(candidate_probabilities)
    if candidate_total > 1.0 + sum_tolerance:
        return _unavailable_exact_result(
            candidate_surface=candidate_surface,
            request_id=request_id,
            attempt_id=attempt_id,
            reason="candidate_probability_sum_exceeds_one",
            selected_alias=selected_alias,
            selected_candidate_id=selected_candidate_id,
            decision_token_position=decision_position,
            sequence_length=sequence_length,
            top_k=len(alternatives),
        )
    other_mass = max(0.0, min(1.0, 1.0 - candidate_total))
    payload_values = (*candidate_probabilities, other_mass)
    if any(not math.isfinite(value) or value < 0.0 for value in payload_values):
        return _unavailable_exact_result(
            candidate_surface=candidate_surface,
            request_id=request_id,
            attempt_id=attempt_id,
            reason="candidate_probability_invalid",
            selected_alias=selected_alias,
            selected_candidate_id=selected_candidate_id,
            decision_token_position=decision_position,
            sequence_length=sequence_length,
            top_k=len(alternatives),
        )
    receipt = LogitProducerReceipt(
        request_id=request_id,
        attempt_id=attempt_id,
        status=LogitProducerStatus.AVAILABLE,
        candidate_surface_digest=candidate_surface.candidate_surface_digest,
        alias_mapping_digest=candidate_surface.alias_mapping_digest,
        selected_alias=selected_alias,
        selected_candidate_id=selected_candidate_id,
        decision_token_position=decision_position,
        sequence_length=sequence_length,
        top_k=len(alternatives),
    )
    return ExactChoiceLogitResult(
        payload_bytes=struct.pack(f"<{len(payload_values)}f", *payload_values),
        candidate_probabilities=candidate_probabilities,
        other_mass=other_mass,
        selected_alias=selected_alias,
        selected_candidate_id=selected_candidate_id,
        selected_candidate_ordinal=candidate_surface.aliases.index(selected_alias),
        receipt=receipt,
    )
