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
    if corpus_doc_ids:
        candidates = [docs_by_id[doc_id] for doc_id in corpus_doc_ids if doc_id in docs_by_id]
    else:
        candidates = [
            doc
            for doc in docs_by_id.values()
            if doc.task_group == task_group or doc.task_theme == task_theme
        ]
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
        score = semantic + (0.20 * lexical) + (0.25 * tag_overlap)
        scored.append((score, doc))
    scored.sort(key=lambda item: (-item[0], item[1].doc_id))
    return [doc for _score, doc in scored[:top_k]]


def render_corpus_evidence(docs: list[CorpusDoc]) -> str:
    lines: list[str] = []
    for doc in docs:
        lines.append(f"[{doc.doc_id}] {doc.title}")
        lines.append(doc.text)
    return "\n\n".join(lines).strip()


def _normalized_terms(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_/-]+", text.lower()) if len(token) >= 3}
