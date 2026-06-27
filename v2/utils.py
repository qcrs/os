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
        return {str(key): normalize_for_json(val) for key, val in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [normalize_for_json(item) for item in value]
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
