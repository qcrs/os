from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from tasks.sample_tasks import SampleTask


@dataclass(frozen=True)
class CorpusDoc:
    doc_id: str
    title: str
    text: str


@dataclass(frozen=True)
class PlaybookRule:
    route: str
    tool_name: str
    keywords: tuple[str, ...]


PLAYBOOK_CATALOG = (
    PlaybookRule(
        route="db_pool_saturation",
        tool_name="tool.db_pool_triage",
        keywords=(
            "database",
            "db",
            "pool",
            "sql",
            "query",
            "wait",
            "latency",
            "connection",
            "orders",
            "index",
            "deploy",
            "deployment",
        ),
    ),
    PlaybookRule(
        route="auth_session_drift",
        tool_name="tool.auth_session_repair",
        keywords=(
            "auth",
            "session",
            "jwks",
            "issuer",
            "callback",
            "cookie",
            "cookies",
            "sign",
            "verification",
            "rotation",
            "tenant",
        ),
    ),
    PlaybookRule(
        route="cache_invalidation",
        tool_name="tool.cache_invalidation_playbook",
        keywords=(
            "inventory",
            "cache",
            "invalidation",
            "sync",
            "stale",
            "aggregate",
            "hook",
            "region",
            "freshness",
            "writer",
        ),
    ),
    PlaybookRule(
        route="worker_queue_starvation",
        tool_name="tool.worker_queue_triage",
        keywords=(
            "worker",
            "queue",
            "backlog",
            "tls",
            "reload",
            "billing",
            "webhook",
            "stall",
            "starvation",
            "drain",
        ),
    ),
    PlaybookRule(
        route="auth_rate_limit",
        tool_name="tool.auth_rate_limit_triage",
        keywords=("auth", "rate", "limit", "limiter", "backoff", "throttle", "login"),
    ),
    PlaybookRule(
        route="cache_replica_stale_read",
        tool_name="tool.replica_stale_read_triage",
        keywords=("replica", "lag", "stale", "read", "reads", "failover", "reporting"),
    ),
)


class ExternalTextOpenRuntime:
    node_order = ("planner", "retriever", "executor", "summarizer")

    def __init__(self, replay_store: object) -> None:
        self.replay_store = replay_store

    def run_task(
        self,
        *,
        task: SampleTask,
        policy: str,
        run_index: int,
    ) -> dict[str, object]:
        normalized_query = normalize_query(task.query)
        retrieved_docs = retrieve_corpus_docs(task)
        retrieved_doc_ids = tuple(doc.doc_id for doc in retrieved_docs)
        route, tool_name = choose_playbook(task=task, retrieved_docs=retrieved_docs)
        replay_record = None
        if policy == "native_reuse_on":
            replay_record = self.replay_store.lookup(
                task_theme=task.task_theme,
                normalized_query=normalized_query,
                retrieved_doc_ids=retrieved_doc_ids,
                route=route,
                tool_name=tool_name,
            )
        replay_hit = replay_record is not None
        summary_text = (
            replay_record.summary_text if replay_record is not None else summarize(task, retrieved_docs, route, tool_name)
        )
        if policy == "native_reuse_on" and replay_record is None:
            self.replay_store.commit_payload(
                {
                    "task_theme": task.task_theme,
                    "normalized_query": normalized_query,
                    "retrieved_doc_ids": retrieved_doc_ids,
                    "route": route,
                    "tool_name": tool_name,
                    "summary_text": summary_text,
                    "evidence_digest": evidence_digest(retrieved_doc_ids),
                }
            )
        return {
            "task": task,
            "policy": policy,
            "run_index": run_index,
            "normalized_query": normalized_query,
            "retrieved_doc_ids": retrieved_doc_ids,
            "retrieved_snippets": [
                {"doc_id": doc.doc_id, "snippet": render_snippet(doc.text)} for doc in retrieved_docs
            ],
            "route": route,
            "tool_name": tool_name,
            "summary_text": summary_text,
            "evidence_digest": evidence_digest(retrieved_doc_ids),
            "replay_hit": replay_hit,
            "skipped_step_count": 2 if replay_hit else 0,
            "message_log": build_message_log(
                task=task,
                retrieved_docs=retrieved_docs,
                route=route,
                tool_name=tool_name,
                replay_hit=replay_hit,
            ),
            "decision_source": "text_only_lexical_playbook",
            "metadata_oracle_used": False,
            "statebus_contract_used": False,
        }


def retrieve_corpus_docs(task: SampleTask) -> list[CorpusDoc]:
    docs = load_corpus_docs(task.corpus_path)
    selected = [docs[doc_id] for doc_id in task.corpus_doc_ids if doc_id in docs]
    if not selected:
        selected = list(docs.values())
    task_tokens = lexical_tokens(f"{task.goal}\n{task.query}")
    ranked = sorted(
        selected,
        key=lambda doc: (-lexical_overlap(task_tokens, lexical_tokens(f"{doc.title}\n{doc.text}")), doc.doc_id),
    )
    return ranked


def choose_playbook(*, task: SampleTask, retrieved_docs: list[CorpusDoc]) -> tuple[str, str]:
    combined_text = "\n".join([task.goal, task.query, *(doc.text for doc in retrieved_docs)])
    combined_tokens = lexical_tokens(combined_text)
    scored = sorted(
        PLAYBOOK_CATALOG,
        key=lambda rule: (-lexical_overlap(combined_tokens, set(rule.keywords)), rule.route, rule.tool_name),
    )
    best = scored[0]
    return best.route, best.tool_name


def summarize(task: SampleTask, retrieved_docs: list[CorpusDoc], route: str, tool_name: str) -> str:
    evidence_list = ", ".join(doc.doc_id for doc in retrieved_docs[:3])
    return (
        f"For {task.task_theme}, the retrieved evidence supports route {route}. "
        f"Use {tool_name} first after checking docs {evidence_list}."
    )


def build_message_log(
    *,
    task: SampleTask,
    retrieved_docs: list[CorpusDoc],
    route: str,
    tool_name: str,
    replay_hit: bool,
) -> list[str]:
    messages = [
        f"Planner: restate the task as {task.goal}",
        "Retriever: re-read the local corpus and rank passages by lexical overlap.",
    ]
    if replay_hit:
        messages.append(
            f"Executor: the same query, evidence set, route {route}, and tool {tool_name} were already validated."
        )
        messages.append("Summarizer: reuse the prior validated summary after the retrieval check matched.")
        return messages
    doc_phrase = ", ".join(doc.doc_id for doc in retrieved_docs[:3])
    messages.append(
        f"Executor: based on docs {doc_phrase}, pick route {route} and run {tool_name}."
    )
    messages.append("Summarizer: explain the first action and the strongest competing explanation ruled out.")
    return messages


def load_corpus_docs(path_text: str) -> dict[str, CorpusDoc]:
    path = Path(path_text)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    docs: dict[str, CorpusDoc] = {}
    for item in payload.get("docs", []):
        doc_id = str(item.get("doc_id", "")).strip()
        if not doc_id:
            continue
        docs[doc_id] = CorpusDoc(
            doc_id=doc_id,
            title=str(item.get("title", "")).strip(),
            text=str(item.get("text", "")).strip(),
        )
    return docs


def evidence_digest(doc_ids: tuple[str, ...]) -> str:
    return "|".join(doc_ids)


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def render_snippet(text: str, limit: int = 160) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def lexical_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]+", text.lower()) if len(token) > 1}


def lexical_overlap(left: set[str], right: set[str]) -> int:
    return len(left & right)
