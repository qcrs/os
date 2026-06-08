from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np
import yaml

from memory.store import EmbeddingProvider


DEFAULT_TASK_CORPUS = Path(__file__).with_name("sample_corpus.yaml")


@dataclass(frozen=True)
class CorpusDoc:
    doc_id: str
    task_group: str
    task_theme: str
    title: str
    tags: tuple[str, ...]
    route_hint: str
    tool_name: str
    text: str

    @property
    def full_text(self) -> str:
        return f"{self.title}\n{self.text}".strip()


def load_corpus_docs(path: str | Path | None = None) -> dict[str, CorpusDoc]:
    corpus_path = Path(path) if path is not None else DEFAULT_TASK_CORPUS
    payload = yaml.safe_load(corpus_path.read_text(encoding="utf-8")) or {}
    docs = payload["docs"] if isinstance(payload, dict) else payload
    loaded: dict[str, CorpusDoc] = {}
    for item in docs:
        doc = CorpusDoc(
            doc_id=str(item["doc_id"]).strip(),
            task_group=str(item["task_group"]).strip(),
            task_theme=str(item["task_theme"]).strip(),
            title=str(item["title"]).strip(),
            tags=tuple(str(tag).strip() for tag in item.get("tags", [])),
            route_hint=str(item.get("route_hint", "")).strip(),
            tool_name=str(item.get("tool_name", "")).strip(),
            text=str(item["text"]).strip(),
        )
        loaded[doc.doc_id] = doc
    return loaded


def retrieve_corpus_docs(
    *,
    query: str,
    tags: list[str],
    task_group: str,
    task_theme: str,
    corpus_doc_ids: list[str] | tuple[str, ...] | None,
    embedder: EmbeddingProvider,
    corpus_path: str | Path | None = None,
    top_k: int = 2,
) -> list[CorpusDoc]:
    docs_by_id = load_corpus_docs(corpus_path)
    preferred_doc_ids = {
        str(doc_id).strip() for doc_id in (corpus_doc_ids or []) if str(doc_id).strip()
    }
    candidates = list(docs_by_id.values())
    if not candidates:
        return []
    query_vector = embedder.embed_text(query)
    query_terms = _normalized_terms(query)
    tag_terms = {tag.strip().lower() for tag in tags if tag.strip()}
    scored: list[tuple[float, CorpusDoc]] = []
    for doc in candidates:
        doc_vector = embedder.embed_text(doc.full_text)
        semantic = float(np.dot(query_vector, doc_vector))
        lexical = float(len(query_terms & _normalized_terms(doc.full_text)))
        tag_overlap = float(len(tag_terms & {tag.lower() for tag in doc.tags}))
        theme_bonus = 0.12 if doc.task_theme == task_theme else 0.0
        group_bonus = 0.06 if doc.task_group == task_group else 0.0
        # Keep corpus doc hints as a weak retrieval prior: strong enough to stabilize
        # close replay/control ties, but not strong enough to override clearly better
        # lexical/semantic evidence outside the hinted doc set.
        preference_bonus = 0.20 if doc.doc_id in preferred_doc_ids else 0.0
        score = (
            semantic
            + (0.20 * lexical)
            + (0.25 * tag_overlap)
            + preference_bonus
            + theme_bonus
            + group_bonus
        )
        scored.append((score, doc))
    scored.sort(key=lambda item: (-item[0], item[1].doc_id))
    return [doc for _score, doc in scored[:top_k]]


def render_corpus_evidence(docs: list[CorpusDoc]) -> str:
    lines: list[str] = []
    for doc in docs:
        lines.append(f"[{doc.doc_id}] {doc.title}")
        lines.append(doc.text)
    return "\n\n".join(lines).strip()


def extract_corpus_feature_hints(docs: list[CorpusDoc]) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []
    for doc in docs:
        if not doc.route_hint and not doc.tool_name:
            continue
        hints.append(
            {
                "doc_id": doc.doc_id,
                "route": doc.route_hint,
                "tool_name": doc.tool_name,
            }
        )
    return hints


def resolve_corpus_feature_hint(
    doc_ids: list[str] | tuple[str, ...],
    *,
    corpus_path: str | Path | None = None,
) -> dict[str, str] | None:
    docs_by_id = load_corpus_docs(corpus_path)
    distinct_hints = {
        (doc.route_hint, doc.tool_name)
        for doc_id in doc_ids
        for doc in [docs_by_id.get(doc_id)]
        if doc is not None and (doc.route_hint or doc.tool_name)
    }
    if len(distinct_hints) != 1:
        return None
    route, tool_name = next(iter(distinct_hints))
    return {"route": route, "tool_name": tool_name}


def _normalized_terms(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_/-]+", text.lower()) if len(token) >= 3}
