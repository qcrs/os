from __future__ import annotations

import math
import struct

import pytest

from v2.runtime.logit_state import (
    LogitStateResult,
    serialize_logit_state,
    serialize_logit_state_v2,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _FakeAlt:
    def __init__(self, logprob: float) -> None:
        self.logprob = logprob


class _FakeToken:
    def __init__(self, logprob: float, top_logprobs: list[_FakeAlt]) -> None:
        self.logprob = logprob
        self.top_logprobs = top_logprobs


def _json_token(logprob: float, alts: list[float]) -> dict:
    return {
        "token": "t",
        "logprob": logprob,
        "top_logprobs": [{"token": f"t{i}", "logprob": lp} for i, lp in enumerate(alts)],
    }


# ---------------------------------------------------------------------------
# Back-compat shim: serialize_logit_state() — old callers must not break
# ---------------------------------------------------------------------------

def test_serialize_logit_state_uses_final_token_top_logprobs_from_json_shape() -> None:
    """Back-compat shim returns a valid 3-tuple with non-zero entropy."""
    payload, entropy, confidence = serialize_logit_state(
        [
            {
                "token": "```",
                "logprob": -0.5,
                "top_logprobs": [
                    {"token": "```", "logprob": -0.5},
                    {"token": '{"', "logprob": -0.9},
                    {"token": "{\n", "logprob": -10.6},
                ],
            }
        ],
        top_k=3,
    )
    probs = struct.unpack("<3f", payload)
    assert len(probs) == 3
    assert math.isclose(sum(probs), 1.0, rel_tol=1e-6)
    assert 0.0 < entropy < math.log(3.0)
    assert 0.0 < confidence < 1.0


def test_serialize_logit_state_uses_final_token_top_logprobs_from_sdk_shape() -> None:
    """Back-compat shim works with SDK-style objects."""
    payload, entropy, confidence = serialize_logit_state(
        [
            _FakeToken(
                logprob=-0.2,
                top_logprobs=[_FakeAlt(-0.2), _FakeAlt(-1.2), _FakeAlt(-2.2)],
            )
        ],
        top_k=3,
    )
    probs = struct.unpack("<3f", payload)
    assert len(probs) == 3
    assert math.isclose(sum(probs), 1.0, rel_tol=1e-6)
    assert 0.0 < entropy < math.log(3.0)
    assert 0.0 < confidence < 1.0


# ---------------------------------------------------------------------------
# serialize_logit_state_v2: empty / degenerate input
# ---------------------------------------------------------------------------

def test_v2_empty_sequence_returns_sentinel() -> None:
    result = serialize_logit_state_v2([])
    assert result.payload_bytes == b""
    assert result.peak_position == -1
    assert result.sequence_length == 0
    assert result.entropy == 0.0
    assert result.confidence_proxy == 1.0
    assert result.varentropy == 0.0
    assert result.top_gap == 0.0
    assert result.decision_entropy == -1.0


def test_v2_all_positions_empty_items() -> None:
    """Positions with no parseable logprob values degrade gracefully."""
    result = serialize_logit_state_v2([{"token": "x", "logprob": None}])
    assert result.peak_position == -1


# ---------------------------------------------------------------------------
# serialize_logit_state_v2: peak-entropy position selection
# ---------------------------------------------------------------------------

def test_v2_peak_position_not_last_token() -> None:
    """With a high-entropy early token and a low-entropy closing token,
    peak_position must NOT be the last index (i.e. not the grammar close token)."""
    # Position 0: nearly uniform 3-way split → high entropy
    # Position 1: one dominant token → near-zero entropy
    seq = [
        _json_token(-1.1, [-1.1, -1.2, -1.3]),   # ~uniform → high H
        _json_token(-0.01, [-0.01, -9.0, -9.0]),  # dominant → low H
    ]
    result = serialize_logit_state_v2(seq, top_k=3)
    assert result.peak_position == 0, (
        f"Expected peak at position 0 (high entropy), got {result.peak_position}"
    )
    assert result.entropy > 0.5, f"Expected meaningful entropy, got {result.entropy}"


def test_v2_single_position_sequence() -> None:
    result = serialize_logit_state_v2(
        [_json_token(-0.5, [-0.5, -0.9, -2.0])], top_k=3
    )
    assert result.peak_position == 0
    assert result.sequence_length == 1
    assert result.entropy > 0.0


# ---------------------------------------------------------------------------
# serialize_logit_state_v2: varentropy
# ---------------------------------------------------------------------------

def test_v2_varentropy_high_for_mixed_sequence() -> None:
    """Sequence with one high-entropy and one near-zero-entropy position
    should yield higher varentropy than a uniform sequence."""
    mixed_seq = [
        _json_token(-1.1, [-1.1, -1.15, -1.2]),   # ~uniform
        _json_token(-0.001, [-0.001, -10.0, -10.0]),  # dominant
    ]
    uniform_seq = [
        _json_token(-1.1, [-1.1, -1.15, -1.2]),
        _json_token(-1.1, [-1.1, -1.15, -1.2]),
    ]
    mixed_result = serialize_logit_state_v2(mixed_seq, top_k=3)
    uniform_result = serialize_logit_state_v2(uniform_seq, top_k=3)
    assert mixed_result.varentropy > uniform_result.varentropy, (
        f"mixed varentropy={mixed_result.varentropy} should exceed "
        f"uniform varentropy={uniform_result.varentropy}"
    )


def test_v2_varentropy_zero_for_single_position() -> None:
    result = serialize_logit_state_v2(
        [_json_token(-0.5, [-0.5, -1.0])], top_k=2
    )
    assert result.varentropy == 0.0


# ---------------------------------------------------------------------------
# serialize_logit_state_v2: top_gap
# ---------------------------------------------------------------------------

def test_v2_top_gap_near_zero_for_uniform_distribution() -> None:
    # Nearly equal logprobs → small gap
    result = serialize_logit_state_v2(
        [_json_token(-1.0, [-1.0, -1.01, -1.02])], top_k=3
    )
    assert result.top_gap < 0.1


def test_v2_top_gap_large_for_dominant_token() -> None:
    # One token hugely dominant → large gap
    result = serialize_logit_state_v2(
        [_json_token(-0.001, [-0.001, -10.0, -10.0])], top_k=3
    )
    assert result.top_gap > 0.8


# ---------------------------------------------------------------------------
# serialize_logit_state_v2: payload serialisation
# ---------------------------------------------------------------------------

def test_v2_payload_is_normalised_float32() -> None:
    result = serialize_logit_state_v2(
        [_json_token(-0.5, [-0.5, -1.0, -2.0])], top_k=3
    )
    assert len(result.payload_bytes) == 3 * 4  # 3 float32
    probs = struct.unpack("<3f", result.payload_bytes)
    assert math.isclose(sum(probs), 1.0, rel_tol=1e-5)


def test_v2_payload_empty_for_empty_sequence() -> None:
    result = serialize_logit_state_v2([])
    assert result.payload_bytes == b""


# ---------------------------------------------------------------------------
# serialize_logit_state_v2: decision_entropy
# ---------------------------------------------------------------------------

def test_v2_decision_entropy_minus_one_without_candidates() -> None:
    result = serialize_logit_state_v2(
        [_json_token(-0.5, [-0.5, -1.0])], top_k=2
    )
    assert result.decision_entropy == -1.0


def test_v2_decision_entropy_computed_with_candidates() -> None:
    # token "to" prefix-matches candidates "tool_a" and "tool_b"
    seq = [{
        "token": "to",
        "logprob": -0.5,
        "top_logprobs": [
            {"token": "tool_a", "logprob": -0.5},
            {"token": "tool_b", "logprob": -0.9},
        ],
    }]
    result = serialize_logit_state_v2(seq, candidate_tokens=["tool_a", "tool_b"])
    # Both candidates matched → entropy should be positive
    assert result.decision_entropy > 0.0


# ---------------------------------------------------------------------------
# LogitStateResult: back-compat properties
# ---------------------------------------------------------------------------

def test_logit_state_result_legacy_properties() -> None:
    result = serialize_logit_state_v2(
        [_json_token(-0.5, [-0.5, -1.0, -2.0])], top_k=3
    )
    assert isinstance(result, LogitStateResult)
    assert result.legacy_entropy == result.entropy
    assert result.legacy_confidence_proxy == result.confidence_proxy
