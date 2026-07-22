"""Shared helpers for the research agents."""

import re


def _get_mode(state: dict) -> str:
    """Get communication mode from state."""
    return state.get("mode", "text")


def _memory_lookup_query(query: str, max_chars: int = 360) -> str:
    """Extract the task question for memory retrieval.

    Memory search should not include long constraints, answer formats, sample
    data, or source documents because they pollute BM25 keyword matching.
    """
    text = str(query or "").strip()
    if not text:
        return ""

    question_match = re.search(
        r"(?:^|\n)Question:\s*(.*?)(?:\nConstraints:|\nExpected answer format:|\nDepends on prior rounds:|\nConcepts:|\n\n|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if question_match:
        return _compact_line(question_match.group(1), max_chars)

    for marker in (
        "\nConstraints:",
        "\nExpected answer format:",
        "\nSample data",
        "\nDepends on prior rounds:",
        "\nConcepts:",
        "\nSkyforge source rules:",
    ):
        if marker in text:
            text = text.split(marker, 1)[0].strip()
            break

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().lower().startswith("round:")
    ]
    return _compact_line(lines[0] if lines else text, max_chars)


def _compact_line(value: object, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()



def _normalize_sub_queries(query: str, sub_queries: list) -> list[str]:
    """Ensure fan-out has three distinct research candidates."""
    normalized = []
    seen = set()
    for item in sub_queries or []:
        text = str(item).strip()
        if not text or len(text) < 8 or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
        if len(normalized) == 3:
            return normalized

    fallback_aspects = [
        f"{query} 的核心概念和机制",
        f"{query} 的实现方式和关键组件",
        f"{query} 的性能、可靠性和应用场景",
    ]
    for text in fallback_aspects:
        if text in seen:
            continue
        normalized.append(text)
        if len(normalized) == 3:
            break
    return normalized
