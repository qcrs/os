"""company_com task adapter for graph inputs.

The adapter keeps dataset-specific formatting out of generic agents. It splits
the task question/rules from the source material so only the researcher needs
to read the financial table and surrounding text.
"""

from __future__ import annotations

import re
from typing import Any


def clip_text(value: object, max_chars: int, *, normalize_whitespace: bool = True) -> str:
    text = str(value or "").strip()
    if normalize_whitespace:
        text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head
    return text[:head].rstrip() + "\n[... clipped ...]\n" + text[-tail:].lstrip()


def table_to_markdown(table: list[list[Any]], max_rows: int = 60) -> str:
    rows = table or []
    if not rows:
        return "(no table)"
    clipped = rows[:max_rows]
    lines = [" | ".join(str(cell) for cell in row) for row in clipped]
    if len(rows) > max_rows:
        lines.append(f"... {len(rows) - max_rows} more rows omitted")
    return "\n".join(lines)


def build_task_topic(company: str, session: dict[str, Any]) -> str:
    return (
        f"company_com financial QA | company={company} | "
        f"year={session.get('year')} | session={session.get('session_order')} | "
        f"source={session.get('id')}"
    )


COMPANY_COM_ANALYST_INSTRUCTIONS = """
Company_com answer rules:
- candidate_answers must contain final scalar numeric values only, one value for each @turn_N field.
- Never put formulas, expressions, source phrases, units, commas, dollar signs, or percent signs in candidate_answers.
- Do not copy a source table value into candidate_answers when the turn asks for a change, difference, less, over, divided by, percent change, rate of return, product, or sum. Compute the final value first.
- Preserve negative signs. For "change from A to B", compute value_B - value_A. If value_B is lower, the answer is negative.
- "less 100" means value - 100, not value. "over 100" or "divided by 100" means divide the computed value by 100.
- For later turns that refer to "that", "this", "previous", or "prior", use the final scalar answer from the earlier turn, not the original source table value.
- For percentage/rate questions, output the decimal ratio, rounded to 5 decimal places when needed.
- Before returning JSON, check every candidate_answers value can be placed directly inside @turn_N[value].
""".strip()


def build_company_graph_input(
    session: dict[str, Any],
    company: str,
    *,
    mode: str,
    max_context_chars: int,
) -> dict[str, Any]:
    turns = session.get("turns", []) or []
    order = int(session.get("session_order", 0))
    answer_format = " ".join(f"@turn_{idx}[number]" for idx in range(1, len(turns) + 1))
    turn_lines = []
    for idx, turn in enumerate(turns, start=1):
        ref_note = " Depends on prior turns." if turn.get("has_internal_ref") else ""
        turn_lines.append(f"Turn {idx}: {turn.get('question')}{ref_note}")

    query = "\n".join([
        "You are solving one financial QA session.",
        "Question:",
        "\n".join(turn_lines),
        "",
        "Constraints:",
        "Answer all turns in order. Later turns may refer to earlier answers with words like that, this, or previous value.",
        "Use only the source context that will be provided to the researcher.",
        "Return numeric scalar answers only.",
        "",
        "FinQA numeric conventions for this dataset:",
        "- Use the numeric value as written in the source; do not expand million/billion into absolute dollars.",
        "- Example: if the source says '$1.2 billion', use 1.2. If it says '$411.0 million', use 411.0.",
        "- If the question says 'times 1000', multiply the source number by 1000 after keeping the source number's scale.",
        "- If a question asks for a percentage, percent of, as a percent, relation, or over another value, return the decimal ratio, not percent points.",
        "- Example: 73 divided by 128 is 0.57031, not 57.031 or 57.031%.",
        "- For table lookup questions, match the requested row/label and year/column exactly before calculating.",
        "- For every later turn that says that/this/previous/prior product/same years, reuse the earlier turn answers in this session.",
        "- Round ratios to 5 decimal places when needed. Do not include units, commas, dollar signs, or percent signs.",
        f"Expected answer format: {answer_format}",
        "",
        "Important: populate every required @turn_1, @turn_2, ... field exactly once and do not invent any extra @turn_N field.",
    ])

    source_context = "\n".join([
        f"Company: {company}",
        f"Year: {session.get('year')}",
        f"Source session: {session.get('id')}",
        "",
        "Shared table:",
        table_to_markdown(session.get("table", [])),
        "",
        "Pre text:",
        " ".join(session.get("pre_text", []) or []),
        "",
        "Post text:",
        " ".join(session.get("post_text", []) or []),
    ])

    return {
        "query": query,
        "source_context": clip_text(
            source_context,
            max_context_chars,
            normalize_whitespace=False,
        ),
        "task_group": f"company_com_{company}_session_{order}",
        "task_topic": build_task_topic(company, session),
        "analyst_instructions": COMPANY_COM_ANALYST_INSTRUCTIONS,
        "mode": mode,
        "metadata": {
            "company": company,
            "year": session.get("year"),
            "session_order": order,
            "source_id": session.get("id"),
            "turn_count": len(turns),
        },
    }
