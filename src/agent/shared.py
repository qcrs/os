"""Shared helpers for the research agents."""

import json
import os
import re
import ast

def _get_mode(state: dict) -> str:
    """Get communication mode from state."""
    return state.get("mode", "text")


def _researcher_fanout() -> int:
    """Return the configured number of researcher branches."""
    try:
        value = int(os.getenv("RESEARCHER_FANOUT", "3"))
    except ValueError:
        value = 3
    return max(1, min(value, 16))


def _normalize_sub_queries(query: str, sub_queries: list) -> list[str]:
    """Ensure fan-out has focused, non-duplicate research candidates."""
    fanout = _researcher_fanout()
    seen = set()
    normalized: list[str] = []
    for item in sub_queries or []:
        text = str(item).strip()
        if not text or len(text) < 8 or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
        if len(normalized) >= fanout:
            return normalized

    fallbacks = [
        f"{query} 的核心证据、约束和最终决策依据",
        f"{query} 需要的计算、枚举或验证步骤",
        f"{query} 的边界条件、例外情况和替代解释",
    ]
    if fanout > len(fallbacks):
        fallbacks.extend(
            f"{query} 的补充分支 {index}：从独立角度复核关键结论"
            for index in range(len(fallbacks) + 1, fanout + 1)
        )
    for text in fallbacks:
        if text in seen:
            continue
        normalized.append(text)
        seen.add(text)
        if len(normalized) >= fanout:
            break

    return normalized


def _extract_json_final_contract_fields(query: str) -> list[str]:
    """Extract required fields from a JSON final answer contract in a prompt."""
    marker = "Return only JSON with exactly these fields:"
    if marker not in query:
        return []

    tail = query.split(marker, 1)[1]
    start = tail.find("{")
    if start < 0:
        return []

    try:
        obj, _ = json.JSONDecoder().raw_decode(tail[start:])
    except json.JSONDecodeError:
        return []
    if not isinstance(obj, dict):
        return []
    return [str(key) for key in obj.keys() if str(key).strip()]


def _find_json_objects(text: str) -> list[dict]:
    """Best-effort extraction of JSON objects from model text."""
    if not text:
        return []
    objects: list[dict] = []
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            objects.append(obj)
    return objects


def _clean_json_contract_answer(value: object, required_fields: list[str]) -> dict[str, object]:
    """Normalize a direct/nested JSON answer to the required contract fields."""
    required = [str(field) for field in required_fields]
    if not required:
        return {}

    candidates: list[dict] = []
    if isinstance(value, dict):
        candidates.append(value)
        for nested_key in ("summary", "final_answer", "answer"):
            nested = value.get(nested_key)
            if isinstance(nested, str):
                candidates.extend(_find_json_objects(nested))
            elif isinstance(nested, dict):
                candidates.append(nested)
    elif isinstance(value, str):
        candidates.extend(_find_json_objects(value))
        if not candidates:
            try:
                literal = ast.literal_eval(value)
            except Exception:
                literal = None
            if isinstance(literal, dict):
                candidates.append(literal)

    best_partial: dict[str, object] = {}
    for candidate in candidates:
        if all(field in candidate for field in required):
            normalized = {
                field: _normalize_contract_value(candidate.get(field))
                for field in required
            }
            cleaned = {
                field: value
                for field, value in normalized.items()
                if not _is_placeholder_contract_value(value)
            }
            if all(field in cleaned for field in required):
                return cleaned
            if len(cleaned) > len(best_partial):
                best_partial = cleaned

    if best_partial:
        return best_partial

    merged: dict[str, object] = {}
    for candidate in candidates:
        for field in required:
            if field in candidate and field not in merged:
                value = _normalize_contract_value(candidate.get(field))
                if not _is_placeholder_contract_value(value):
                    merged[field] = value
    return merged


def _json_contract_answer_to_text(answer: dict[str, object], required_fields: list[str]) -> str:
    """Serialize a JSON contract answer with stable field order."""
    ordered = {field: answer.get(field, "") for field in required_fields}
    return json.dumps(ordered, ensure_ascii=False, separators=(",", ":"))


def _normalize_contract_value(value: object) -> object:
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"-?\d+", text):
            try:
                return int(text)
            except Exception:
                return text
        return text
    return value


def _is_placeholder_contract_value(value: object) -> bool:
    """Return True for template/unknown values that must not count as answers."""
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip()
        lower = text.lower()
        if lower in {
            "",
            "...",
            "unknown",
            "unk",
            "n/a",
            "na",
            "none",
            "null",
            "未识别",
            "未知",
        }:
            return True
        if re.fullmatch(r"<[^<>]+>", text):
            return True
        return False
    if isinstance(value, list):
        return not value or any(_is_placeholder_contract_value(item) for item in value)
    if isinstance(value, dict):
        return not value or all(_is_placeholder_contract_value(item) for item in value.values())
    return False
