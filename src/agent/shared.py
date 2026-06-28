"""Shared helpers for the research agents."""

def _get_mode(state: dict) -> str:
    """Get communication mode from state."""
    return state.get("mode", "text")



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
