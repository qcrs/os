"""Structured Communication Protocol — simplified A2A-inspired design.

Provides:
- ActionType: enumeration of inter-agent action types
- AgentMessage: structured message format replacing natural language passthrough
- AgentCard: agent capability description
- AgentRegistry: capability discovery and routing
"""

import time
import hashlib
from dataclasses import dataclass, asdict
from enum import Enum
import math
import re
from uuid import uuid4


CONTEXT_PROTOCOL_VERSION = "context-packet"
CONTEXT_SCHEMA_VERSION = 2
DEFAULT_CONTEXT_TOP_K = 3
DEFAULT_EVIDENCE_PER_DOC = 4
DEFAULT_SUMMARY_CHARS = 360
DEFAULT_EVIDENCE_CHARS = 180
DEFAULT_MIN_QUERY_COVERAGE = 0.35
DEFAULT_MIN_EVIDENCE_SCORE = 0.05


class ActionType(str, Enum):
    """Action types for inter-agent communication."""
    PLAN = "plan"
    RESEARCH = "research"
    RETRIEVE = "retrieve"
    ANALYZE = "analyze"
    EXECUTE = "execute"
    SUMMARIZE = "summarize"
    QUERY_MEMORY = "query_memory"
    STORE_MEMORY = "store_memory"


@dataclass
class AgentMessage:
    """Structured message passed between agents.

    Replaces natural language passthrough with typed fields:
    - action: what to do (ActionType)
    - params: structured input (dict)
    - result: structured output (dict)
    - embedding: non-text vector (optional)
    - metadata: traceability (msg_id, timestamp, source, target)
    """
    msg_id: str
    timestamp: float
    source: str
    target: str
    action: ActionType
    params: dict
    result: dict
    embedding: list | None
    task_group: str
    round_id: int
    status: str = "success"

    def to_dict(self) -> dict:
        """Serialize to dict for state passing."""
        d = asdict(self)
        d["action"] = self.action.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AgentMessage":
        """Deserialize from dict."""
        d = dict(d)
        d["action"] = ActionType(d["action"])
        return cls(**d)

    def char_count(self) -> int:
        """Count total characters in params + result (for overhead comparison)."""
        total = 0
        for v in self.params.values():
            total += len(str(v))
        for v in self.result.values():
            total += len(str(v))
        return total


def make_message(
    source: str,
    target: str,
    action: ActionType,
    params: dict,
    result: dict,
    task_group: str,
    round_id: int = 0,
    embedding: list | None = None,
    status: str = "success",
) -> AgentMessage:
    """Factory to create an AgentMessage with auto-generated id and timestamp."""
    return AgentMessage(
        msg_id=f"msg_{uuid4().hex[:8]}",
        timestamp=time.time(),
        source=source,
        target=target,
        action=action,
        params=params,
        result=result,
        embedding=embedding,
        task_group=task_group,
        round_id=round_id,
        status=status,
    )


def make_document_key(task_group: str, sub_query: str, doc_text: str) -> str:
    """Create a stable Store key for generated research material."""
    digest = hashlib.sha256()
    digest.update(_normalize_text(task_group).encode("utf-8"))
    digest.update(b"\0")
    digest.update(_normalize_text(sub_query).encode("utf-8"))
    digest.update(b"\0")
    digest.update(_normalize_text(doc_text).encode("utf-8"))
    return f"doc_{_safe_key_part(task_group)}_{digest.hexdigest()[:12]}"


def hash_text(text: str) -> str:
    """Stable compact hash for verifying source text snippets."""
    return _hash_text(text)


def build_context_packet(
    *,
    doc_key: str,
    sub_query: str,
    doc_text: str,
    task_group: str,
    embedding_ref: str | None = None,
    max_summary_chars: int = DEFAULT_SUMMARY_CHARS,
    max_evidence_chars: int = DEFAULT_EVIDENCE_CHARS,
    max_evidence_items: int = DEFAULT_EVIDENCE_PER_DOC,
) -> dict:
    """Build a retrievable compact protocol payload for downstream agents.

    The full document stays in Store. The packet carries query-focused evidence
    spans with exact offsets and hashes so downstream agents can verify and
    rehydrate the context before trusting it.
    """
    evidence_spans = retrieve_evidence_spans(
        text=doc_text,
        query=sub_query,
        max_items=max_evidence_items,
        max_chars=max_evidence_chars,
        doc_key=doc_key,
    )
    summary = summarize_evidence_spans(
        evidence_spans=evidence_spans,
        fallback_text=doc_text,
        max_chars=max_summary_chars,
    )
    tags = extract_tags(f"{sub_query} {summary}")
    covered_terms, missing_terms, query_coverage = _query_coverage(
        query=sub_query,
        evidence_spans=evidence_spans,
        summary=summary,
    )

    packet = {
        "protocol": CONTEXT_PROTOCOL_VERSION,
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "doc_key": doc_key,
        "task_group": task_group,
        "source_query": sub_query,
        "summary": summary,
        "evidence_spans": evidence_spans,
        "tags": tags,
        "embedding_ref": embedding_ref or doc_key,
        "original_chars": len(doc_text),
        "retrieval_diagnostics": {
            "method": "lexical_span_retrieval",
            "evidence_count": len(evidence_spans),
            "query_coverage": query_coverage,
            "covered_terms": covered_terms,
            "missing_terms": missing_terms,
            "requires_full_doc_lookup": query_coverage < DEFAULT_MIN_QUERY_COVERAGE,
        },
        "full_doc_ref": {
            "namespace": "docs",
            "key": doc_key,
            "text_hash": _hash_text(doc_text),
        },
        "score": 0.0,
    }
    packet["compressed_chars"] = estimate_prompt_context_chars(packet)
    packet["compression_ratio"] = round(
        packet["compressed_chars"] / max(len(doc_text), 1), 4
    )
    packet["verification"] = verify_context_packet(packet, doc_text, query_text=sub_query)
    packet["retrieval_diagnostics"]["requires_full_doc_lookup"] = packet["verification"][
        "requires_full_doc_lookup"
    ]
    packet["retrieval_diagnostics"]["coverage_warning"] = packet["verification"][
        "coverage_warning"
    ]
    return packet


def select_context_packets(
    *,
    packets: list[dict],
    query_text: str,
    query_embedding: list[float] | None = None,
    embedding_payloads: list[dict] | None = None,
    top_k: int = DEFAULT_CONTEXT_TOP_K,
) -> list[dict]:
    """Select the most relevant compact packets for an analyst prompt."""
    vector_by_key = {}
    for payload in embedding_payloads or []:
        if isinstance(payload, dict):
            key = payload.get("doc_key") or payload.get("embedding_ref")
            vector = payload.get("vector")
            if key and isinstance(vector, list):
                vector_by_key[key] = vector

    scored_packets = []
    for packet in packets:
        doc_key = packet.get("doc_key", "")
        lexical = lexical_relevance(query_text, packet)
        vector_score = None
        if query_embedding is not None:
            doc_vector = vector_by_key.get(doc_key) or vector_by_key.get(
                packet.get("embedding_ref", "")
            )
            if doc_vector:
                vector_score = cosine_similarity(query_embedding, doc_vector)

        diagnostics = packet.get("retrieval_diagnostics", {})
        coverage = float(diagnostics.get("query_coverage", 0.0) or 0.0)
        if vector_score is None:
            score = 0.8 * lexical + 0.2 * coverage
        else:
            score = 0.65 * vector_score + 0.25 * lexical + 0.1 * coverage

        enriched = dict(packet)
        enriched["score"] = round(float(score), 4)
        enriched["score_components"] = {
            "lexical": round(float(lexical), 4),
            "vector": round(float(vector_score), 4) if vector_score is not None else None,
            "coverage": round(float(coverage), 4),
        }
        scored_packets.append(enriched)

    scored_packets.sort(key=_score_sort_key, reverse=True)
    return scored_packets[:top_k]


def select_document_payloads(
    *,
    documents: list[str],
    document_payloads: list[dict] | None = None,
    query_text: str,
    query_embedding: list[float] | None = None,
    embedding_payloads: list[dict] | None = None,
    top_k: int = DEFAULT_CONTEXT_TOP_K,
) -> list[dict]:
    """Select raw documents with optional embedding signals when compression is disabled."""
    candidates = []
    seen_texts = set()
    for payload in document_payloads or []:
        candidate = dict(payload)
        candidates.append(candidate)
        seen_texts.add(candidate.get("text", ""))
    for index, document in enumerate(documents):
        if document in seen_texts:
            continue
        candidates.append({
            "doc_key": f"raw_doc_{index}",
            "sub_query": "",
            "text": document,
            "original_chars": len(document),
        })

    vector_by_key = {}
    for payload in embedding_payloads or []:
        if isinstance(payload, dict):
            key = payload.get("doc_key") or payload.get("embedding_ref")
            vector = payload.get("vector")
            if key and isinstance(vector, list):
                vector_by_key[key] = vector

    scored_documents = []
    for candidate in candidates:
        doc_key = candidate.get("doc_key", "")
        text = candidate.get("text", "")
        packet_like = {
            "source_query": candidate.get("sub_query", ""),
            "summary": text[:DEFAULT_SUMMARY_CHARS],
            "tags": [],
            "evidence_spans": [{"text": text}],
        }
        lexical = lexical_relevance(query_text, packet_like)

        vector_score = None
        if query_embedding is not None:
            doc_vector = vector_by_key.get(doc_key) or vector_by_key.get(
                candidate.get("embedding_ref", "")
            )
            if doc_vector:
                vector_score = cosine_similarity(query_embedding, doc_vector)

        if vector_score is not None:
            score = 0.75 * vector_score + 0.25 * lexical
        else:
            score = lexical

        enriched = dict(candidate)
        enriched["score"] = round(float(score), 4)
        enriched["score_components"] = {
            "lexical": round(float(lexical), 4),
            "vector": round(float(vector_score), 4) if vector_score is not None else None,
        }
        scored_documents.append(enriched)

    scored_documents.sort(key=_score_sort_key, reverse=True)
    return scored_documents[:top_k]


def format_context_for_prompt(
    packets: list[dict],
    *,
    evidence_per_doc: int = DEFAULT_EVIDENCE_PER_DOC,
    max_evidence_chars: int = DEFAULT_EVIDENCE_CHARS,
) -> str:
    """Render verified evidence as a minimal LLM context block.

    Verification metadata, offsets, hashes, diagnostics, and compression stats stay
    in Python. The model only sees source ids plus short extractive spans.
    """
    if not packets:
        return "No selected context packets available."

    blocks = []
    for packet in packets:
        doc_key = packet.get("doc_key", "")
        evidence_lines = []
        for evidence in packet.get("evidence_spans", [])[:evidence_per_doc]:
            text = _compact_evidence_text(evidence.get("text", ""), max_chars=max_evidence_chars)
            if not text:
                continue
            evidence_lines.append(
                f"[{doc_key}#{evidence.get('span_id', 'ev')}] {text}"
            )
        if not evidence_lines:
            summary = _compact_evidence_text(packet.get("summary", ""), max_chars=max_evidence_chars)
            if summary:
                evidence_lines.append(f"[{doc_key}#summary] {summary}")
        blocks.extend(evidence_lines)
    return "\n".join(blocks) if blocks else "No selected context packets available."


def verify_context_packet(
    packet: dict,
    doc_text: str,
    *,
    query_text: str | None = None,
    min_query_coverage: float = DEFAULT_MIN_QUERY_COVERAGE,
) -> dict:
    """Verify compact evidence against the full document text.

    Exact offsets and hashes must still line up with the stored document.
    Query overlap is treated as a soft diagnostic so short answer-style packets
    are not forced back into full-document fallback when the compression is
    otherwise structurally correct.
    """
    evidence_spans = packet.get("evidence_spans", []) or []
    invalid_refs = []
    valid_ref_count = 0
    full_text_hash = _hash_text(doc_text)
    full_doc_hash_matches = packet.get("full_doc_ref", {}).get("text_hash") == full_text_hash
    summary_text = _normalize_text(packet.get("summary", ""))

    for evidence in evidence_spans:
        source_ref = evidence.get("source_ref", {}) or {}
        char_start = _as_int(source_ref.get("char_start", evidence.get("char_start")))
        char_end = _as_int(source_ref.get("char_end", evidence.get("char_end")))
        span_id = evidence.get("span_id", "ev")

        if char_start is None or char_end is None or char_start < 0 or char_end <= char_start:
            invalid_refs.append({"span_id": span_id, "reason": "invalid_range"})
            continue
        if char_end > len(doc_text):
            invalid_refs.append({"span_id": span_id, "reason": "range_out_of_bounds"})
            continue

        source_text = _normalize_text(doc_text[char_start:char_end])
        evidence_text = _normalize_text(evidence.get("text", ""))
        expected_hash = source_ref.get("text_hash")
        actual_hash = _hash_text(source_text)
        text_matches = source_text == evidence_text
        hash_matches = expected_hash == actual_hash if expected_hash else True
        if not text_matches or not hash_matches:
            invalid_refs.append({
                "span_id": span_id,
                "reason": "text_or_hash_mismatch",
                "expected_hash": expected_hash,
                "actual_hash": actual_hash,
            })
            continue
        valid_ref_count += 1

    covered_terms, missing_terms, query_coverage = _query_coverage(
        query=query_text or packet.get("source_query", ""),
        evidence_spans=evidence_spans,
        summary=packet.get("summary", ""),
    )
    has_evidence = bool(evidence_spans)
    all_refs_valid = has_evidence and valid_ref_count == len(evidence_spans) and not invalid_refs
    summary_only_valid = not has_evidence and bool(summary_text) and full_doc_hash_matches
    structural_valid = all_refs_valid or summary_only_valid
    coverage_warning = query_coverage < min_query_coverage
    reliable = structural_valid

    return {
        "reliable": reliable,
        "full_doc_hash_matches": full_doc_hash_matches,
        "evidence_count": len(evidence_spans),
        "valid_ref_count": valid_ref_count,
        "invalid_refs": invalid_refs,
        "query_coverage": query_coverage,
        "coverage_warning": coverage_warning,
        "covered_terms": covered_terms,
        "missing_terms": missing_terms,
        "requires_full_doc_lookup": not reliable,
        "reliability_basis": "structural" if reliable else "fallback",
    }


def summarize_evidence_spans(
    *,
    evidence_spans: list[dict],
    fallback_text: str,
    max_chars: int = DEFAULT_SUMMARY_CHARS,
) -> str:
    """Build a query-focused extractive summary from verified candidate spans."""
    if not evidence_spans:
        return summarize_text(fallback_text, max_chars)

    ordered_spans = sorted(
        evidence_spans,
        key=lambda evidence: (
            -float(evidence.get("score", 0.0) or 0.0),
            evidence.get("char_start", 0),
        ),
    )
    parts = []
    total_chars = 0
    for evidence in ordered_spans:
        text = evidence.get("text", "").strip()
        if not text:
            continue
        prefix = f"{evidence.get('span_id', 'ev')}: "
        remaining = max_chars - total_chars - len(prefix)
        if remaining <= 0:
            break
        snippet = text[:remaining].rstrip()
        parts.append(f"{prefix}{snippet}")
        total_chars += len(prefix) + len(snippet)
        if total_chars >= max_chars:
            break

    summary = " ".join(parts).strip()
    return summary or summarize_text(fallback_text, max_chars)


def summarize_text(text: str, max_chars: int = DEFAULT_SUMMARY_CHARS) -> str:
    """Deterministically compress text without an extra LLM call."""
    normalized = _normalize_text(text)
    if len(normalized) <= max_chars:
        return normalized

    sentences = _split_sentences(normalized)
    selected = []
    total = 0
    for sentence in sentences:
        if total + len(sentence) > max_chars and selected:
            break
        selected.append(sentence)
        total += len(sentence)
        if total >= max_chars:
            break

    summary = " ".join(selected).strip()
    if not summary:
        summary = normalized[:max_chars].strip()
    if len(summary) > max_chars:
        summary = summary[:max_chars].rstrip()
    return summary


def extract_evidence_spans(
    *,
    text: str,
    query: str,
    max_items: int = DEFAULT_EVIDENCE_PER_DOC,
    max_chars: int = DEFAULT_EVIDENCE_CHARS,
) -> list[dict]:
    """Backward-compatible wrapper for retrieval-style evidence extraction."""
    return retrieve_evidence_spans(
        text=text,
        query=query,
        max_items=max_items,
        max_chars=max_chars,
    )


def retrieve_evidence_spans(
    *,
    text: str,
    query: str,
    max_items: int = DEFAULT_EVIDENCE_PER_DOC,
    max_chars: int = DEFAULT_EVIDENCE_CHARS,
    doc_key: str | None = None,
    min_score: float = DEFAULT_MIN_EVIDENCE_SCORE,
) -> list[dict]:
    """Retrieve compact evidence spans with precise source references."""
    query_terms = set(_content_terms(query))
    candidates = _candidate_spans(text, max_chars=max_chars)

    scored = []
    fallback_scored = []
    for position, candidate in enumerate(candidates):
        terms = set(_content_terms(candidate["text"]))
        overlap = len(query_terms & terms)
        matched_terms = sorted(query_terms & terms)
        coverage = overlap / max(len(query_terms), 1) if query_terms else 0.0
        density = overlap / max(len(terms), 1)
        position_bonus = 0.05 * (1 - min(candidate["char_start"] / max(len(text), 1), 1))
        phrase_bonus = _phrase_bonus(query, candidate["text"])
        score = 0.72 * coverage + 0.18 * density + position_bonus + phrase_bonus
        item = (score, position, candidate, matched_terms, coverage, density)
        fallback_scored.append(item)
        if score >= min_score and (matched_terms or not query_terms):
            scored.append(item)

    if not scored:
        scored = fallback_scored[:1]

    scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    evidence = []
    used_ranges: list[tuple[int, int]] = []
    for score, position, candidate, matched_terms, coverage, density in scored:
        if _overlaps_existing(candidate["char_start"], candidate["char_end"], used_ranges):
            continue
        snippet = candidate["text"][:max_chars].strip()
        if not snippet:
            continue
        text_hash = _hash_text(snippet)
        evidence.append({
            "span_id": f"ev{len(evidence) + 1}",
            "text": snippet,
            "score": round(float(score), 4),
            "matched_terms": matched_terms,
            "coverage": round(float(coverage), 4),
            "density": round(float(density), 4),
            "char_start": candidate["char_start"],
            "char_end": candidate["char_end"],
            "source_ref": {
                "doc_key": doc_key,
                "char_start": candidate["char_start"],
                "char_end": candidate["char_end"],
                "text_hash": text_hash,
            },
            "retrieval_method": "lexical_span_retrieval",
        })
        used_ranges.append((candidate["char_start"], candidate["char_end"]))
        if len(evidence) >= max_items:
            break
    return evidence


def estimate_prompt_context_chars(packet: dict) -> int:
    """Estimate only the prompt-visible compressed context size."""
    return len(format_context_for_prompt([packet]))


def estimate_context_packet_chars(packet: dict) -> int:
    """Estimate full internal packet size, including verification metadata."""
    evidence_chars = 0
    for evidence in packet.get("evidence_spans", []) or []:
        evidence_chars += len(evidence.get("text", ""))
        evidence_chars += len(str(evidence.get("source_ref", {})))
        evidence_chars += len(" ".join(evidence.get("matched_terms", [])))

    return sum([
        len(packet.get("doc_key", "")),
        len(packet.get("source_query", "")),
        len(packet.get("summary", "")),
        len(" ".join(packet.get("tags", []))),
        evidence_chars,
        len(str(packet.get("retrieval_diagnostics", {}))),
        len(str(packet.get("verification", {}))),
    ])


def extract_tags(text: str, max_tags: int = 8) -> list[str]:
    """Extract short tags for protocol routing and filtering."""
    tags = []
    seen = set()
    for token in _tokenize(text):
        if token in seen:
            continue
        seen.add(token)
        tags.append(token)
        if len(tags) >= max_tags:
            break
    return tags


def lexical_relevance(query_text: str, packet: dict) -> float:
    """Compute a small deterministic relevance score for packet selection."""
    query_terms = set(_content_terms(query_text))
    packet_text = " ".join([
        packet.get("source_query", ""),
        packet.get("summary", ""),
        " ".join(packet.get("tags", [])),
        " ".join(e.get("text", "") for e in packet.get("evidence_spans", [])),
    ])
    packet_terms = set(_content_terms(packet_text))
    if not query_terms or not packet_terms:
        return 0.0
    return len(query_terms & packet_terms) / len(query_terms | packet_terms)


def _score_sort_key(item: dict) -> tuple:
    components = item.get("score_components", {}) or {}
    vector_score = components.get("vector")
    return (
        item.get("score", 0.0),
        vector_score is not None,
        float(vector_score) if vector_score is not None else -1.0,
    )


def cosine_similarity(left_vector: list[float], right_vector: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not left_vector or not right_vector:
        return 0.0
    limit = min(len(left_vector), len(right_vector))
    dot = sum(left_vector[index] * right_vector[index] for index in range(limit))
    norm_left = math.sqrt(sum(value * value for value in left_vector[:limit]))
    norm_right = math.sqrt(sum(value * value for value in right_vector[:limit]))
    if norm_left == 0 or norm_right == 0:
        return 0.0
    return dot / (norm_left * norm_right)



def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def _compact_evidence_text(text: str, max_chars: int = DEFAULT_EVIDENCE_CHARS) -> str:
    normalized = _normalize_text(text)
    if len(normalized) <= max_chars:
        return normalized
    sentences = _split_sentences(normalized)
    if sentences and len(sentences[0]) <= max_chars:
        return sentences[0]
    return normalized[:max_chars].rstrip() + "…"


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？.!?;；])\s*", text)
    return [part.strip() for part in parts if part.strip()]


def _split_sentences_with_offsets(text: str) -> list[dict]:
    spans = []
    for match in re.finditer(r"[^。！？.!?;；\n]+[。！？.!?;；]?", str(text)):
        raw_text = match.group(0)
        stripped_text = raw_text.strip()
        if not stripped_text:
            continue
        leading_ws = len(raw_text) - len(raw_text.lstrip())
        trailing_ws = len(raw_text) - len(raw_text.rstrip())
        char_start = match.start() + leading_ws
        char_end = match.end() - trailing_ws
        spans.append({
            "text": _normalize_text(stripped_text),
            "char_start": char_start,
            "char_end": char_end,
        })
    return spans


def _candidate_spans(text: str, *, max_chars: int) -> list[dict]:
    sentence_spans = _split_sentences_with_offsets(text)
    candidates = []
    for sentence in sentence_spans:
        if len(sentence["text"]) <= max_chars:
            candidates.append(sentence)
            continue

        char_start = sentence["char_start"]
        char_end = sentence["char_end"]
        window_size = max(max_chars, 80)
        overlap = min(80, window_size // 4)
        cursor = char_start
        while cursor < char_end:
            window_end = min(cursor + window_size, char_end)
            window_text = _normalize_text(text[cursor:window_end])
            if window_text:
                candidates.append({
                    "text": window_text,
                    "char_start": cursor,
                    "char_end": window_end,
                })
            if window_end == char_end:
                break
            cursor = max(window_end - overlap, cursor + 1)

    if not candidates and text:
        snippet = str(text)[:max_chars]
        candidates.append({
            "text": _normalize_text(snippet),
            "char_start": 0,
            "char_end": len(snippet),
        })
    return candidates


def _tokenize(text: str) -> list[str]:
    lowered = str(text).lower()
    tokens = re.findall(r"[a-z0-9][a-z0-9_\-]{1,}", lowered)
    for chunk in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if len(chunk) >= 2:
            tokens.append(chunk)
        tokens.extend(chunk[index:index + 2] for index in range(0, len(chunk) - 1, 2))
        tokens.extend(chunk[index:index + 4] for index in range(0, len(chunk) - 3, 2))
        if len(chunk) % 2 == 1 and len(chunk) > 2:
            tokens.append(chunk[-2:])
    return tokens


def _content_terms(text: str) -> list[str]:
    terms = []
    seen = set()
    for token in _tokenize(text):
        if token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms[:120]


def _query_coverage(
    *,
    query: str,
    evidence_spans: list[dict],
    summary: str,
) -> tuple[list[str], list[str], float]:
    query_terms = set(_content_terms(query))
    if not query_terms:
        return [], [], 1.0 if evidence_spans or summary else 0.0

    context_text = " ".join(
        [summary] + [evidence.get("text", "") for evidence in evidence_spans]
    )
    context_terms = set(_content_terms(context_text))
    covered_terms = sorted(query_terms & context_terms)
    missing_terms = sorted(query_terms - context_terms)
    coverage = len(covered_terms) / max(len(query_terms), 1)
    return covered_terms, missing_terms, round(float(coverage), 4)


def _phrase_bonus(query: str, text: str) -> float:
    normalized_query = _normalize_text(query).lower()
    normalized_text = _normalize_text(text).lower()
    if not normalized_query or not normalized_text:
        return 0.0
    phrases = [phrase for phrase in re.split(r"[,，;；。.!?？、\s]+", normalized_query) if len(phrase) >= 3]
    hits = sum(1 for phrase in phrases if phrase in normalized_text)
    return min(hits * 0.08, 0.16)


def _overlaps_existing(
    char_start: int,
    char_end: int,
    used_ranges: list[tuple[int, int]],
) -> bool:
    for used_start, used_end in used_ranges:
        if char_start < used_end and used_start < char_end:
            return True
    return False


def _hash_text(text: str) -> str:
    return hashlib.sha256(_normalize_text(text).encode("utf-8")).hexdigest()[:16]


def _safe_key_part(value: str, limit: int = 24) -> str:
    tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", str(value).lower())
    key_part = "_".join(tokens)[:limit].strip("_")
    return key_part or "default"


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "what", "how", "are",
    "was", "were", "into", "their", "there", "about", "based", "given", "包括",
    "以及", "之前", "基于", "进行", "相关", "结果", "重点", "分析", "研究", "调研",
    "什么", "如何", "一个", "之前的", "所有", "生成", "完整", "具体",
}


@dataclass
class AgentCard:
    """Capability description for an agent (A2A AgentCard inspired)."""
    name: str
    description: str
    actions: list[str]
    input_schema: dict
    output_schema: dict
    supports_embedding: bool = False


class AgentRegistry:
    """Global agent capability registry — supports capability discovery."""

    _ACTION_ALIASES = {
        ActionType.RETRIEVE.value: ActionType.RESEARCH.value,
    }
    _NAME_ALIASES = {"retriever": "researcher"}

    def __init__(self):
        self._cards: dict[str, AgentCard] = {}

    def register(self, card: AgentCard):
        """Register an agent's capability card."""
        self._cards[card.name] = card

    def discover(self, action: str) -> list[AgentCard]:
        """Discover agents that support a given action."""
        action = self._ACTION_ALIASES.get(action, action)
        return [c for c in self._cards.values() if action in c.actions]

    def get_card(self, name: str) -> AgentCard | None:
        """Get a specific agent's capability card."""
        name = self._NAME_ALIASES.get(name, name)
        return self._cards.get(name)

    def list_all(self) -> list[AgentCard]:
        """List all registered agents."""
        return list(self._cards.values())

    def summary(self) -> str:
        """Print registry contents."""
        lines = ["Agent Registry:"]
        for card in self._cards.values():
            emb = "✓" if card.supports_embedding else "✗"
            lines.append(f"  [{card.name}] actions={card.actions}, embedding={emb}")
            lines.append(f"    {card.description}")
        return "\n".join(lines)


# Default registry with 4 agents pre-registered
def create_default_registry() -> AgentRegistry:
    """Create registry with the 4 demo agents registered."""
    registry = AgentRegistry()

    registry.register(AgentCard(
        name="planner",
        description="Breaks down research queries into structured sub-queries",
        actions=[ActionType.PLAN.value],
        input_schema={"query": "str", "task_group": "str"},
        output_schema={
            "plan": "str",
            "sub_queries": "list[str]",
        },
        supports_embedding=False,
    ))

    registry.register(AgentCard(
        name="researcher",
        description="Generates source material and emits compact context packets",
        actions=[ActionType.RESEARCH.value],
        input_schema={"sub_query": "str", "task_group": "str"},
        output_schema={
            "doc_key": "str",
            "context_packet": "dict",
            "embedding_payload": "{doc_key: str, vector: list[float]}",
        },
        supports_embedding=True,
    ))

    registry.register(AgentCard(
        name="analyst",
        description="Selects compact context packets and produces structured analysis",
        actions=[ActionType.ANALYZE.value],
        input_schema={
            "plan": "str",
            "context_packets": "list[dict]",
            "embedding_payloads": "list[dict]",
        },
        output_schema={
            "analysis": "str",
            "analysis_digest": "str",
            "candidate_answers": "dict[str, str]",
            "evidence": "list[dict]",
        },
        supports_embedding=True,
    ))

    registry.register(AgentCard(
        name="executor",
        description="Runs a bounded CodeAct step and emits machine-evaluation answers",
        actions=[ActionType.EXECUTE.value],
        input_schema={
            "analysis": "str",
            "evidence": "list[dict]",
            "selected_context_packets": "list[dict]",
        },
        output_schema={
            "execution_code": "str",
            "execution_result": "dict",
            "execution_summary": "str",
            "final_answer": "str",
            "extracted_answers": "dict[str, str]",
        },
        supports_embedding=False,
    ))

    registry.register(AgentCard(
        name="summarizer",
        description="Produces final summary with key findings",
        actions=[ActionType.SUMMARIZE.value],
        input_schema={
            "analysis": "str",
            "evidence": "list[dict]",
            "execution_result": "dict",
            "execution_summary": "str",
        },
        output_schema={"summary": "str", "key_findings": "list[str]"},
        supports_embedding=False,
    ))

    return registry
