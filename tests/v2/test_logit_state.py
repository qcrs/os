from __future__ import annotations

import math
import struct

from v2.runtime.logit_state import serialize_logit_state


class _FakeAlt:
    def __init__(self, logprob: float) -> None:
        self.logprob = logprob


class _FakeToken:
    def __init__(self, logprob: float, top_logprobs: list[_FakeAlt]) -> None:
        self.logprob = logprob
        self.top_logprobs = top_logprobs


def test_serialize_logit_state_uses_final_token_top_logprobs_from_json_shape() -> None:
    payload, entropy, confidence = serialize_logit_state(
        [
            {
                "token": "```",
                "logprob": -0.5,
                "top_logprobs": [
                    {"token": "```", "logprob": -0.5},
                    {"token": "{\"", "logprob": -0.9},
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
