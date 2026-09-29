"""Measured same-receiver handoffs for the DSL experiment.

``HandoffTransport(path, mode="text" | "typed").invoke(sender, receiver,
step, payload, callback)`` returns the callback's result (or an awaitable when
that callback is asynchronous). Payloads are JSON-domain dictionaries. Text
receivers consume the UTF-8 encoded/decoded full JSON payload. Typed receivers
consume a private object copy. Neither path resolves a Ref or reads a store.
The typed boundary is in-process; its object size is NOT a wire-byte estimate.
"""
from __future__ import annotations

from copy import deepcopy
import inspect
import json
import math
from pathlib import Path
import time
from typing import Any, Callable, Literal
import uuid

from statebus.benchmark.request_journal import append_event


def _validate_payload(value: Any) -> None:
    """Reject values whose JSON roundtrip changes their type or meaning."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _validate_payload(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _validate_payload(item)
        return
    raise TypeError(f"handoff payload is outside the JSON domain: {type(value).__name__}")


class HandoffTransport:
    def __init__(self, path: Path, *, mode: Literal["text", "typed"],
                 token_counter: Callable[[str], int] | None = None,
                 tokenizer_name: str | None = None):
        if mode not in {"text", "typed"}:
            raise ValueError(f"unsupported handoff mode: {mode}")
        self.path = Path(path)
        self.mode = mode
        self.token_counter = token_counter
        self.tokenizer_name = tokenizer_name

    def invoke(self, sender: str, receiver: str, step: str, payload: dict,
               callback: Callable[[dict], Any]) -> Any:
        """Record send/receive before dispatch, and outcome after real use.

        Caller exceptions and cancellations are journalled and propagated.
        An asynchronous callback must be awaited by the caller, just as when
        invoking that callback directly.
        """
        message_id = str(uuid.uuid4())
        base = {"message_id": message_id, "sender": sender, "receiver": receiver,
                "step": step, "carrier": "utf8_json_text" if self.mode == "text" else "in_process_typed_object",
                "transport_scope": "in_process_same_receiver", "wire_bytes": None,
                "wire_missing_reason": "no_wire_in_process_handoff"}

        def emit(event: str, **fields: Any) -> None:
            append_event(self.path, {**base, "event": event,
                                     "timestamp_ns": time.monotonic_ns(), **fields})

        phase = "validate"
        try:
            if type(payload) is not dict:
                raise TypeError("handoff payload must be a dictionary")
            _validate_payload(payload)
            metrics = {"handoff_text_chars": 0, "handoff_text_tokens": 0,
                       "handoff_text_bytes": 0, "typed_bytes": None,
                       "control_bytes": None, "serialized_bytes": None,
                       "serialize_ms": None, "parse_ms": None, "decode_ms": None,
                       "hydrate_ms": None, "hydrate_bytes": None,
                       "object_copy_ms": None,
                       "typed_bytes_missing_reason": "in_process_object_has_no_binary_encoding",
                       "control_bytes_missing_reason": "no_separate_control_frame",
                       "hydrate_missing_reason": "transport_does_not_resolve_references"}
            if self.mode == "text":
                phase = "serialize"
                start = time.monotonic_ns()
                text = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                                  sort_keys=True, separators=(",", ":"))
                encoded = text.encode("utf-8")
                metrics.update(serialize_ms=(time.monotonic_ns() - start) / 1e6,
                               handoff_text_chars=len(text), handoff_text_bytes=len(encoded),
                               serialized_bytes=len(encoded), typed_bytes=0,
                               typed_bytes_missing_reason=None)
                phase = "tokenize"
                metrics["handoff_text_tokens"] = self.token_counter(text) if self.token_counter else None
                metrics["tokenization"] = self.tokenizer_name if self.token_counter else None
                metrics["handoff_tokens_missing_reason"] = None if self.token_counter else "tokenizer_not_configured"
                # This is the actual carrier, not a second projection of an
                # object that was secretly passed to the receiver.
                emit("send", text=text, **metrics)
                phase = "decode"
                start = time.monotonic_ns()
                received_text = encoded.decode("utf-8")
                metrics["decode_ms"] = (time.monotonic_ns() - start) / 1e6
                start = time.monotonic_ns()
                received_payload = json.loads(received_text)
                metrics["parse_ms"] = (time.monotonic_ns() - start) / 1e6
            else:
                phase = "copy"
                start = time.monotonic_ns()
                received_payload = deepcopy(payload)
                metrics["object_copy_ms"] = (time.monotonic_ns() - start) / 1e6
                metrics["serialized_bytes_missing_reason"] = "no_serialization_at_object_boundary"
                metrics["handoff_tokens_missing_reason"] = None
                # append_event serializes its journal record, but those bytes
                # never reach the receiver and are excluded from transport.
                emit("send", **metrics)
            emit("receive", **metrics)
            phase = "receiver"
            start = time.monotonic_ns()
            result = callback(received_payload)
        except BaseException as exc:
            emit("error", phase=phase, error_type=type(exc).__name__, error=str(exc))
            raise

        if inspect.isawaitable(result):
            async def finish():
                try:
                    value = await result
                except BaseException as exc:
                    emit("error", phase="receiver", error_type=type(exc).__name__, error=str(exc))
                    raise
                emit("consume", receiver_ms=(time.monotonic_ns() - start) / 1e6)
                return value
            return finish()
        emit("consume", receiver_ms=(time.monotonic_ns() - start) / 1e6)
        return result
