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
    runtime_route_hint: str
    runtime_tool_name: str
    eval_route_label: str
    eval_tool_label: str
    text: str

    @property
    def full_text(self) -> str:
        return f"{self.title}\n{self.text}".strip()


@dataclass(frozen=True)
class _CorpusDocScore:
    doc: CorpusDoc
    semantic: float
    lexical: float
    tag_overlap: float
    theme_bonus: float
    group_bonus: float
    preference_bonus: float

    @property
    def combined_score(self) -> float:
        return (
            self.semantic
            + (0.20 * self.lexical)
            + (0.25 * self.tag_overlap)
            + self.preference_bonus
            + self.theme_bonus
            + self.group_bonus
        )


def load_corpus_docs(path: str | Path | None = None) -> dict[str, CorpusDoc]:
    corpus_path = Path(path) if path else DEFAULT_TASK_CORPUS
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
            runtime_route_hint=str(item.get("route_hint", "")).strip(),
            runtime_tool_name=str(item.get("tool_name", "")).strip(),
            eval_route_label=str(item.get("eval_route_label", item.get("route_hint", ""))).strip(),
            eval_tool_label=str(item.get("eval_tool_label", item.get("tool_name", ""))).strip(),
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
    allow_preferred_doc_bias: bool = True,
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
    scored: list[_CorpusDocScore] = []
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
        preference_bonus = 0.20 if allow_preferred_doc_bias and doc.doc_id in preferred_doc_ids else 0.0
        scored.append(
            _CorpusDocScore(
                doc=doc,
                semantic=semantic,
                lexical=lexical,
                tag_overlap=tag_overlap,
                theme_bonus=theme_bonus,
                group_bonus=group_bonus,
                preference_bonus=preference_bonus,
            )
        )
    if not scored:
        return []

    # Borrow a small-candidate-first retrieval shape: overfetch a few candidates from
    # independent weak signals, then rerank only inside that pool.
    signal_window = min(len(scored), max(top_k, top_k * 2))
    semantic_ids = set(_top_doc_ids(scored, key=lambda item: item.semantic, limit=signal_window))
    lexical_ids = set(
        _top_doc_ids(
            scored,
            key=lambda item: item.lexical,
            limit=signal_window,
            positive_only=True,
        )
    )
    tag_ids = set(
        _top_doc_ids(
            scored,
            key=lambda item: item.tag_overlap,
            limit=signal_window,
            positive_only=True,
        )
    )
    baseline_ids = set(_top_doc_ids(scored, key=lambda item: item.combined_score, limit=top_k))
    candidate_ids = semantic_ids | lexical_ids | tag_ids | baseline_ids | preferred_doc_ids
    shortlisted = [item for item in scored if item.doc.doc_id in candidate_ids]
    shortlisted.sort(
        key=lambda item: (
            -_rerank_score(
                item,
                semantic_ids=semantic_ids,
                lexical_ids=lexical_ids,
                tag_ids=tag_ids,
            ),
            item.doc.doc_id,
        )
    )
    return [item.doc for item in shortlisted[:top_k]]


def render_corpus_evidence(docs: list[CorpusDoc]) -> str:
    lines: list[str] = []
    for doc in docs:
        lines.append(f"[{doc.doc_id}] {doc.title}")
        lines.append(doc.text)
    return "\n\n".join(lines).strip()


def extract_corpus_feature_hints(docs: list[CorpusDoc]) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []
    for doc in docs:
        if not doc.runtime_route_hint and not doc.runtime_tool_name:
            continue
        hints.append(
            {
                "doc_id": doc.doc_id,
                "route": doc.runtime_route_hint,
                "tool_name": doc.runtime_tool_name,
            }
        )
    return hints


def extract_corpus_eval_labels(docs: list[CorpusDoc]) -> list[dict[str, str]]:
    labels: list[dict[str, str]] = []
    for doc in docs:
        labels.append(
            {
                "doc_id": doc.doc_id,
                "eval_route_label": doc.eval_route_label,
                "eval_tool_label": doc.eval_tool_label,
            }
        )
    return labels


def resolve_corpus_feature_hint(
    doc_ids: list[str] | tuple[str, ...],
    *,
    corpus_path: str | Path | None = None,
) -> dict[str, str] | None:
    docs_by_id = load_corpus_docs(corpus_path)
    distinct_hints = {
        (doc.runtime_route_hint, doc.runtime_tool_name)
        for doc_id in doc_ids
        for doc in [docs_by_id.get(doc_id)]
        if doc is not None and (doc.runtime_route_hint or doc.runtime_tool_name)
    }
    if len(distinct_hints) != 1:
        return None
    route, tool_name = next(iter(distinct_hints))
    return {"route": route, "tool_name": tool_name}


def _normalized_terms(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_/-]+", text.lower()) if len(token) >= 3}


def _top_doc_ids(
    scored: list[_CorpusDocScore],
    *,
    key,
    limit: int,
    positive_only: bool = False,
) -> list[str]:
    ranked = sorted(scored, key=lambda item: (-float(key(item)), item.doc.doc_id))
    if positive_only:
        ranked = [item for item in ranked if float(key(item)) > 0.0]
    return [item.doc.doc_id for item in ranked[:limit]]


def _rerank_score(
    item: _CorpusDocScore,
    *,
    semantic_ids: set[str],
    lexical_ids: set[str],
    tag_ids: set[str],
) -> float:
    support_count = (
        int(item.doc.doc_id in semantic_ids)
        + int(item.doc.doc_id in lexical_ids)
        + int(item.doc.doc_id in tag_ids)
    )
    support_bonus = 0.03 * max(0, support_count - 1)
    return item.combined_score + support_bonus
