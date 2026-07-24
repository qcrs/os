"""LangGraph node that commits only validated long-term memory candidates."""

import time

from langgraph.store.base import BaseStore

from memory_writer import commit_memory_candidates
from metrics import metrics


def memory_committer(state: dict, store: BaseStore) -> dict:
    """Persist task-local candidates after all executor and summary outputs exist."""
    del store
    started_at = time.perf_counter()
    commit_result = commit_memory_candidates(state)
    metrics.record_timing("node_memory_committer", time.perf_counter() - started_at)
    return {"memory_commit": commit_result}
