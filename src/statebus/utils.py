from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any


def normalize_for_json(value: Any) -> Any:
    if is_dataclass(value):
        return normalize_for_json(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        # json.dumps(sort_keys=True) already enforces stable key order.
        return {str(key): normalize_for_json(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_for_json(item) for item in value]
    return value


def _is_compactable_default(value: Any) -> bool:
    if value is None:
        return True
    if value == "":
        return True
    if value is False:
        return True
    if isinstance(value, (int, float)) and value == 0:
        return True
    if isinstance(value, (list, tuple, dict)) and not value:
        return True
    return False


def compact_json_payload(value: Any) -> Any:
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for key, item in value.items():
            child = compact_json_payload(item)
            if _is_compactable_default(child):
                continue
            compacted[str(key)] = child
        return compacted
    if isinstance(value, (list, tuple)):
        return [compact_json_payload(item) for item in value]
    return value


def stable_json_dumps(value: Any) -> str:
    return json.dumps(
        normalize_for_json(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_digest(value: Any) -> str:
    if isinstance(value, bytes):
        payload = value
    else:
        payload = stable_json_dumps(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
