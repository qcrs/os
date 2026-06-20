from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path

import yaml

from runtime.llm import ChatMessage, LLMClient, extract_json_object
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


@dataclass(frozen=True)
class IssueHypothesisRule:
    issue_id: str
    label: str
    keywords: tuple[str, ...]
    route_options: tuple[str, ...]


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

PLAYBOOK_BY_ROUTE = {item.route: item for item in PLAYBOOK_CATALOG}
PLAYBOOK_BY_TOOL = {item.tool_name: item for item in PLAYBOOK_CATALOG}
ISSUE_HYPOTHESIS_CATALOG = (
    IssueHypothesisRule(
        issue_id="auth_control_surface",
        label="Authentication control instability",
        keywords=("auth", "callback", "issuer", "rotation", "session", "tenant", "jwks"),
        route_options=("auth_session_drift", "auth_rate_limit"),
    ),
    IssueHypothesisRule(
        issue_id="traffic_shaping_surface",
        label="Traffic shaping or throttling pressure",
        keywords=("auth", "rate", "limit", "limiter", "backoff", "throttle", "login"),
        route_options=("auth_session_drift", "auth_rate_limit"),
    ),
    IssueHypothesisRule(
        issue_id="processing_capacity_surface",
        label="Processing capacity pressure",
        keywords=("billing", "queue", "backlog", "worker", "reload", "invoice", "drain"),
        route_options=("db_pool_saturation", "worker_queue_starvation"),
    ),
    IssueHypothesisRule(
        issue_id="data_plane_pressure_surface",
        label="Data-plane wait pressure",
        keywords=("database", "db", "pool", "sql", "query", "wait", "orders", "connection"),
        route_options=("db_pool_saturation", "worker_queue_starvation"),
    ),
    IssueHypothesisRule(
        issue_id="cache_consistency_surface",
        label="Cache consistency pressure",
        keywords=("cache", "stale", "sync", "aggregate", "hook", "freshness", "writer"),
        route_options=("cache_invalidation", "cache_replica_stale_read"),
    ),
    IssueHypothesisRule(
        issue_id="replica_read_surface",
        label="Replica lag or stale-read pressure",
        keywords=("replica", "lag", "stale", "read", "reads", "failover", "reporting"),
        route_options=("cache_replica_stale_read", "cache_invalidation"),
    ),
)
STRICT_EXTERNAL_TEXT_BASELINE_OBJECT = "external_pure_text_four_role_baseline_v1"
FORBIDDEN_TEXT_MARKERS = (
    "StateRef",
    "EXECUTOR_DECISION_PACKET",
    "DENSE_EVIDENCE",
    "FEATURE_BUNDLE",
    "MEMORY_ASSIST_HINT",
    "MEMORY_ASSIST",
    "<sb-",
    "</sb-",
)


class ExternalTextOpenRuntime:
    node_order = ("planner", "retriever", "executor", "summarizer")

    def __init__(
        self,
        replay_store: object,
        *,
        llm_client: LLMClient | None = None,
        data_source: str = "lexical_stub",
        runtime_contract: str = STRICT_EXTERNAL_TEXT_BASELINE_OBJECT,
        live_mode: str = "deterministic",
    ) -> None:
        self.replay_store = replay_store
        self.llm_client = llm_client
        self.data_source = data_source
        self.runtime_contract = runtime_contract
        self.live_mode = live_mode

    async def run_task(
        self,
        *,
        task: SampleTask,
        policy: str,
        run_index: int,
    ) -> dict[str, object]:
        if self.data_source in {"strict_pure_text_four_role", "strict_pure_text_four_role_api"}:
            return await self._run_strict_text_task(task=task, policy=policy, run_index=run_index)
        if self.data_source == "live_api_text_only":
            return await self._run_live_text_task(task=task, policy=policy, run_index=run_index)
        return self._run_lexical_stub_task(task=task, policy=policy, run_index=run_index)

    async def _run_strict_text_task(
        self,
        *,
        task: SampleTask,
        policy: str,
        run_index: int,
    ) -> dict[str, object]:
        if self.llm_client is None:
            raise ValueError("strict pure-text external runtime requires llm_client")
        normalized_query = normalize_query(task.query)
        retrieved_docs = retrieve_corpus_docs(task)
        retrieved_doc_ids = tuple(doc.doc_id for doc in retrieved_docs)
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        role_trace: list[dict[str, object]] = []

        planner_payload, planner_usage, planner_model = await self._planner_outline(task=task)
        usage = _merge_usage(usage, planner_usage)
        planner_steps = _planner_steps(planner_payload)
        role_trace.append(
            {
                "role": "planner",
                "model": planner_model,
                "decision_source": "role_llm",
                "plan_step_count": len(planner_steps),
                "visible_inputs": ["goal", "query", "summary_hint", "evidence_text"],
            }
        )

        issue_hypotheses = build_issue_hypotheses(task=task, retrieved_docs=retrieved_docs)
        visible_candidates = build_visible_tool_candidates(
            task=task,
            retrieved_docs=retrieved_docs,
            issue_hypotheses=issue_hypotheses,
        )
        retriever_payload, retriever_usage, retriever_model = await self._retriever_selection(
            task=task,
            retrieved_docs=retrieved_docs,
            issue_hypotheses=issue_hypotheses,
            visible_candidates=visible_candidates,
        )
        usage = _merge_usage(usage, retriever_usage)
        route, tool_name = _strict_visible_selection(
            retriever_payload=retriever_payload,
            visible_candidates=visible_candidates,
        )
        helper_top1 = projected_helper_candidate(issue_hypotheses=issue_hypotheses)
        helper_top1_route = str(helper_top1.get("route", "")).strip()
        helper_top1_tool_name = str(helper_top1.get("tool_name", "")).strip()
        helper_selected_matches_top1 = (
            route == helper_top1_route and tool_name == helper_top1_tool_name
        )
        helper_single_candidate = len(visible_candidates) == 1
        role_trace.append(
            {
                "role": "retriever",
                "model": retriever_model,
                "decision_source": "role_llm",
                "visible_inputs": ["query", "retrieved_docs", "visible_candidates"],
                "selected_route": route,
                "selected_tool_name": tool_name,
                "candidate_count": len(visible_candidates),
                "helper_source": "declared_candidate_generation",
                "issue_hypothesis_count": len(issue_hypotheses),
                "helper_top1_route": helper_top1_route,
                "helper_top1_tool_name": helper_top1_tool_name,
                "selected_matches_helper_top1": helper_selected_matches_top1,
                "helper_single_candidate": helper_single_candidate,
            }
        )

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

        if replay_hit:
            summary_text = str(replay_record.summary_text)
            strongest_competing_route = ""
            validation_check = "retrieval set matched a prior strict pure-text decision"
            role_trace.append(
                {
                    "role": "executor",
                    "model": "",
                    "decision_source": "native_replay_store",
                    "visible_inputs": ["retriever_handoff", "replay_key"],
                    "selected_route": route,
                    "selected_tool_name": tool_name,
                    "helper_source": "none",
                }
            )
            role_trace.append(
                {
                    "role": "summarizer",
                    "model": "",
                    "decision_source": "native_replay_store",
                    "visible_inputs": ["replay_summary_text"],
                    "helper_source": "none",
                }
            )
            decision_source = "external_text_four_role_replay"
            skipped_step_count = 2
        else:
            executor_payload, executor_usage, executor_model = await self._executor_validation(
                task=task,
                retrieved_docs=retrieved_docs,
                visible_candidates=visible_candidates,
                route=route,
                tool_name=tool_name,
            )
            usage = _merge_usage(usage, executor_usage)
            strongest_competing_route = str(retriever_payload.get("reason", "")).strip()
            validation_check = _strict_action_contract(executor_payload)
            route, tool_name = _strict_executor_selection(
                executor_payload=executor_payload,
                visible_candidates=visible_candidates,
                fallback_route=route,
                fallback_tool_name=tool_name,
            )
            helper_selected_matches_top1 = (
                route == helper_top1_route and tool_name == helper_top1_tool_name
            )
            role_trace.append(
                {
                    "role": "executor",
                    "model": executor_model,
                    "decision_source": "role_llm",
                    "visible_inputs": ["retriever_handoff", "retrieved_docs", "visible_candidates"],
                    "selected_route": route,
                    "selected_tool_name": tool_name,
                    "action_contract": validation_check,
                    "helper_source": "none",
                    "helper_top1_route": helper_top1_route,
                    "helper_top1_tool_name": helper_top1_tool_name,
                    "selected_matches_helper_top1": helper_selected_matches_top1,
                    "helper_single_candidate": helper_single_candidate,
                }
            )
            summary_text, summarizer_usage, summarizer_model = await self._summary_text(
                task=task,
                retrieved_docs=retrieved_docs,
                route=route,
                tool_name=tool_name,
                strongest_competing_route=strongest_competing_route,
                validation_check=validation_check,
            )
            usage = _merge_usage(usage, summarizer_usage)
            role_trace.append(
                {
                    "role": "summarizer",
                    "model": summarizer_model,
                    "decision_source": "role_llm",
                    "visible_inputs": ["summary_hint", "retrieved_docs", "executor_handoff"],
                    "helper_source": "none",
                }
            )
            if policy == "native_reuse_on":
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
            decision_source = "external_text_four_role_llm"
            skipped_step_count = 0

        purity_audit = {
            "passed": True,
            "no_statebus_contract_used": True,
            "no_metadata_oracle_used": True,
            "no_lexical_fallback": True,
            "no_silent_correction": True,
            "no_hidden_helper_advantage": True,
            "helper_mode": "declared_candidate_generation_only",
            "structured_packet_markers_present": False,
            "role_count": 4,
        }
        message_log = build_strict_message_log(
            task=task,
            planner_steps=planner_steps,
            retrieved_docs=retrieved_docs,
            visible_candidates=visible_candidates,
            route=route,
            tool_name=tool_name,
            validation_check=validation_check,
            replay_hit=replay_hit,
        )
        if any(any(marker in message for marker in FORBIDDEN_TEXT_MARKERS) for message in message_log):
            purity_audit["passed"] = False
            purity_audit["structured_packet_markers_present"] = True
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
            "skipped_step_count": skipped_step_count,
            "message_log": message_log,
            "decision_source": decision_source,
            "metadata_oracle_used": False,
            "statebus_contract_used": False,
            "data_source": self.data_source,
            "runtime_contract": self.runtime_contract,
            "llm_usage": usage,
            "role_trace": role_trace,
            "purity_audit": purity_audit,
            "lexical_fallback_used": False,
            "helper_dominance": False,
            "visible_candidate_count": len(visible_candidates),
            "visible_candidates": [dict(item) for item in visible_candidates],
            "issue_hypotheses": [dict(item) for item in issue_hypotheses],
            "helper_top1_route": helper_top1_route,
            "helper_top1_tool_name": helper_top1_tool_name,
            "helper_selected_matches_top1": helper_selected_matches_top1,
            "helper_single_candidate": helper_single_candidate,
        }

    def _run_lexical_stub_task(
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
            "data_source": self.data_source,
            "runtime_contract": self.runtime_contract,
            "llm_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    async def _run_live_text_task(
        self,
        *,
        task: SampleTask,
        policy: str,
        run_index: int,
    ) -> dict[str, object]:
        normalized_query = normalize_query(task.query)
        retrieved_docs = retrieve_corpus_docs(task)
        retrieved_doc_ids = tuple(doc.doc_id for doc in retrieved_docs)
        replay_record = None
        if policy == "native_reuse_on":
            lexical_route, lexical_tool = choose_playbook(task=task, retrieved_docs=retrieved_docs)
            replay_record = self.replay_store.lookup(
                task_theme=task.task_theme,
                normalized_query=normalized_query,
                retrieved_doc_ids=retrieved_doc_ids,
                route=lexical_route,
                tool_name=lexical_tool,
            )
        replay_hit = replay_record is not None
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if replay_hit:
            route = str(replay_record.route)
            tool_name = str(replay_record.tool_name)
            summary_text = str(replay_record.summary_text)
            strongest_competing_route = ""
            validation_check = "retrieval set matched a prior validated text-only decision"
            decision_source = "pure_text_message_log_replay"
        else:
            route, tool_name = choose_playbook(task=task, retrieved_docs=retrieved_docs)
            strongest_competing_route = ""
            validation_check = ""
            decision_source = "dry_run_text_contract"
            if self.live_mode == "api":
                if self.llm_client is None:
                    raise ValueError("live API text runtime requires llm_client")
                planner_payload, planner_usage = await self._planner_decision(task=task, retrieved_docs=retrieved_docs)
                usage = _merge_usage(usage, planner_usage)
                route, tool_name = _sanitize_route_tool(
                    route=str(planner_payload.get("route", "")),
                    tool_name=str(planner_payload.get("tool_name", "")),
                    fallback_route=route,
                    fallback_tool_name=tool_name,
                )
                strongest_competing_route = str(planner_payload.get("strongest_competing_route", "")).strip()
                validation_check = str(planner_payload.get("validation_check", "")).strip()
                decision_source = "live_api_text_only"
                summary_text, summary_usage, _summary_model = await self._summary_text(
                    task=task,
                    retrieved_docs=retrieved_docs,
                    route=route,
                    tool_name=tool_name,
                    strongest_competing_route=strongest_competing_route,
                    validation_check=validation_check,
                )
                usage = _merge_usage(usage, summary_usage)
            else:
                summary_text = summarize(task, retrieved_docs, route, tool_name)
                strongest_competing_route = _best_competing_route(route=route, retrieved_docs=retrieved_docs)
                validation_check = "dry-run contract only"
            if policy == "native_reuse_on":
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
            "message_log": build_live_message_log(
                task=task,
                retrieved_docs=retrieved_docs,
                route=route,
                tool_name=tool_name,
                strongest_competing_route=strongest_competing_route,
                validation_check=validation_check,
                replay_hit=replay_hit,
            ),
            "decision_source": decision_source,
            "metadata_oracle_used": False,
            "statebus_contract_used": False,
            "data_source": self.data_source,
            "runtime_contract": self.runtime_contract,
            "llm_usage": usage,
        }

    async def _planner_decision(
        self,
        *,
        task: SampleTask,
        retrieved_docs: list[CorpusDoc],
    ) -> tuple[dict[str, object], dict[str, int]]:
        assert self.llm_client is not None
        prompt = build_planner_prompt(task=task, retrieved_docs=retrieved_docs)
        result = await self.llm_client.complete(
            [
                ChatMessage(
                    role="system",
                    content=(
                        "You are a text-only incident triage planner. Pick one route and one tool from the listed options. "
                        "Return JSON only."
                    ),
                ),
                ChatMessage(role="user", content=prompt),
            ],
            purpose="planner",
        )
        payload = extract_json_object(result.text)
        return payload, _usage_dict(result)

    async def _planner_outline(self, *, task: SampleTask) -> tuple[dict[str, object], dict[str, int], str]:
        assert self.llm_client is not None
        prompt = "\n".join(
            [
                f"Task ID: {task.task_id}",
                f"Task group: {task.task_group}",
                f"Task theme: {task.task_theme}",
                "Goal:",
                task.goal,
                "",
                "Search query:",
                task.query,
                "",
                "Required semantic roles:",
                "retrieve, execute, summarize",
                "",
                "Summary hint:",
                task.summary_hint,
                "",
                "Evidence note:",
                task.evidence_text,
                "",
                f"Tags: {', '.join(task.tags)}",
            ]
        )
        result = await self.llm_client.complete(
            [
                ChatMessage(
                    role="system",
                    content="You are the planner in a strict external pure-text four-role workflow. Return JSON only.",
                ),
                ChatMessage(role="user", content=prompt),
            ],
            purpose="planner",
        )
        payload = extract_json_object(result.text)
        return payload, _usage_dict(result), str(result.model)

    async def _retriever_selection(
        self,
        *,
        task: SampleTask,
        retrieved_docs: list[CorpusDoc],
        issue_hypotheses: list[dict[str, object]],
        visible_candidates: list[dict[str, object]],
    ) -> tuple[dict[str, object], dict[str, int], str]:
        assert self.llm_client is not None
        prompt = "\n".join(
            [
                f"Task theme: {task.task_theme}",
                f"Query: {task.query}",
                f"Retrieved docs: {', '.join(doc.doc_id for doc in retrieved_docs[:4])}",
                "Issue hypotheses: " + "; ".join(
                    (
                        f"{str(item['issue_id'])}::{str(item['label'])}"
                        f"|support_terms={','.join(str(term) for term in item.get('support_terms', []))}"
                        f"|support_docs={','.join(str(doc_id) for doc_id in item.get('supporting_doc_ids', []))}"
                        f"|route_options={','.join(str(route_id) for route_id in item.get('route_options', []))}"
                    )
                    for item in issue_hypotheses
                ),
                "Visible candidates: " + "; ".join(
                    f"{str(item['route'])}::{str(item['tool_name'])}"
                    for item in visible_candidates
                ),
                "Candidate notes: " + "; ".join(
                    (
                        f"{str(item['route'])}::{str(item['tool_name'])}"
                        f"|matched_issue_ids={','.join(str(issue_id) for issue_id in item.get('matched_issue_ids', []))}"
                        f"|support_terms={','.join(str(term) for term in item.get('support_terms', []))}"
                        f"|support_doc_count={int(item.get('support_doc_count', 0) or 0)}"
                        f"|support_docs={','.join(str(doc_id) for doc_id in item.get('supporting_doc_ids', []))}"
                    )
                    for item in visible_candidates
                ),
                "Candidate order is alphabetical only. Treat the notes as evidence-backed provenance, not as a ranking.",
                "Use the issue hypotheses only as coarse competing interpretations, then choose the route/tool pair best supported by the retrieved evidence and support terms.",
            ]
        )
        result = await self.llm_client.complete(
            [
                ChatMessage(
                    role="system",
                    content=(
                        "You are the retriever in a strict external pure-text workflow. "
                        "Use the visible candidate cards as a bounded comparison set. "
                        "Do not assume any candidate is pre-approved. "
                        "Return JSON."
                    ),
                ),
                ChatMessage(role="user", content=prompt),
            ],
            purpose="retriever",
        )
        payload = extract_json_object(result.text)
        return payload, _usage_dict(result), str(result.model)

    async def _executor_validation(
        self,
        *,
        task: SampleTask,
        retrieved_docs: list[CorpusDoc],
        visible_candidates: list[dict[str, object]],
        route: str,
        tool_name: str,
    ) -> tuple[dict[str, object], dict[str, int], str]:
        assert self.llm_client is not None
        prompt = "\n".join(
            [
                f"Task theme: {task.task_theme}",
                f"Route: {route}",
                f"Tool: {tool_name}",
                f"Validated route: {route}",
                f"Validated tool: {tool_name}",
                f"Evidence docs: {', '.join(doc.doc_id for doc in retrieved_docs[:4])}",
                "Visible candidates: " + "; ".join(
                    f"{str(item['route'])}::{str(item['tool_name'])}"
                    for item in visible_candidates
                ),
                "Candidate notes: " + "; ".join(
                    (
                        f"{str(item['route'])}::{str(item['tool_name'])}"
                        f"|matched_issue_ids={','.join(str(issue_id) for issue_id in item.get('matched_issue_ids', []))}"
                        f"|support_terms={','.join(str(term) for term in item.get('support_terms', []))}"
                        f"|support_doc_count={int(item.get('support_doc_count', 0) or 0)}"
                        f"|support_docs={','.join(str(doc_id) for doc_id in item.get('supporting_doc_ids', []))}"
                    )
                    for item in visible_candidates
                ),
                "Candidate order is alphabetical only. Re-check the proposed pair against the evidence-backed candidate notes.",
                "You may keep or revise the proposed pair, but you must stay inside the visible candidate set.",
                "Validated action contract: execute_validated_tool",
            ]
        )
        result = await self.llm_client.complete(
            [
                ChatMessage(
                    role="system",
                    content=(
                        "You are the executor in a strict external pure-text workflow. "
                        "Independently validate the proposed route/tool pair against the visible evidence and return JSON."
                    ),
                ),
                ChatMessage(role="user", content=prompt),
            ],
            purpose="executor",
        )
        payload = extract_json_object(result.text)
        return payload, _usage_dict(result), str(result.model)

    async def _summary_text(
        self,
        *,
        task: SampleTask,
        retrieved_docs: list[CorpusDoc],
        route: str,
        tool_name: str,
        strongest_competing_route: str,
        validation_check: str,
    ) -> tuple[str, dict[str, int]]:
        assert self.llm_client is not None
        prompt = build_summary_prompt(
            task=task,
            retrieved_docs=retrieved_docs,
            route=route,
            tool_name=tool_name,
            strongest_competing_route=strongest_competing_route,
            validation_check=validation_check,
        )
        result = await self.llm_client.complete(
            [
                ChatMessage(
                    role="system",
                    content=(
                        "Write a compact plain-text triage summary. "
                        "Do not emit JSON, code fences, packet markers, or structured protocol names."
                    ),
                ),
                ChatMessage(role="user", content=prompt),
            ],
            purpose="summarizer",
        )
        summary_text = sanitize_message_text(_extract_summary_text(result.text))
        return summary_text, _usage_dict(result), str(result.model)


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


def build_visible_tool_candidates(
    *,
    task: SampleTask,
    retrieved_docs: list[CorpusDoc],
    issue_hypotheses: list[dict[str, object]],
) -> list[dict[str, object]]:
    del task, retrieved_docs
    hypothesis_by_route: dict[str, list[dict[str, object]]] = {}
    for hypothesis in issue_hypotheses:
        for route_id in hypothesis.get("route_options", []):
            hypothesis_by_route.setdefault(str(route_id), []).append(hypothesis)

    visible: list[dict[str, object]] = []
    for rule in PLAYBOOK_CATALOG:
        matched_hypotheses = hypothesis_by_route.get(rule.route, [])
        support_terms: list[str] = []
        supporting_doc_ids: list[str] = []
        matched_issue_ids: list[str] = []
        for hypothesis in matched_hypotheses:
            matched_issue_ids.append(str(hypothesis.get("issue_id", "")).strip())
            for term in hypothesis.get("support_terms", []):
                if str(term).strip() and str(term) not in support_terms:
                    support_terms.append(str(term))
            for doc_id in hypothesis.get("supporting_doc_ids", []):
                if str(doc_id).strip() and str(doc_id) not in supporting_doc_ids:
                    supporting_doc_ids.append(str(doc_id))
        visible.append(
            {
                "route": rule.route,
                "tool_name": rule.tool_name,
                "matched_issue_ids": matched_issue_ids,
                "support_terms": support_terms[:4],
                "supporting_doc_ids": supporting_doc_ids[:3],
                "support_doc_count": len(supporting_doc_ids[:3]),
            }
        )
    return sorted(visible, key=lambda item: (str(item["route"]), str(item["tool_name"])))


def build_issue_hypotheses(
    *,
    task: SampleTask,
    retrieved_docs: list[CorpusDoc],
) -> list[dict[str, object]]:
    combined_text = "\n".join([task.goal, task.query, *(doc.text for doc in retrieved_docs)])
    combined_tokens = lexical_tokens(combined_text)
    doc_tokens = {doc.doc_id: lexical_tokens(f"{doc.title}\n{doc.text}") for doc in retrieved_docs}
    scored = sorted(
        (
            {
                "issue_id": rule.issue_id,
                "label": rule.label,
                "support_score": lexical_overlap(combined_tokens, set(rule.keywords)),
                "route_options": list(rule.route_options),
                "support_terms": [keyword for keyword in rule.keywords if keyword in combined_tokens][:4],
                "supporting_doc_ids": [
                    doc.doc_id
                    for doc in retrieved_docs
                    if lexical_overlap(doc_tokens.get(doc.doc_id, set()), set(rule.keywords)) > 0
                ][:3],
            }
            for rule in ISSUE_HYPOTHESIS_CATALOG
        ),
        key=lambda item: (-int(item["support_score"]), str(item["issue_id"])),
    )
    visible = [dict(item) for item in scored if int(item["support_score"]) > 0]
    minimum_visible = 3
    if len(visible) < minimum_visible:
        for item in scored:
            if any(str(existing["issue_id"]) == str(item["issue_id"]) for existing in visible):
                continue
            visible.append(dict(item))
            if len(visible) >= minimum_visible:
                break
    return visible


def projected_helper_candidate(*, issue_hypotheses: list[dict[str, object]]) -> dict[str, object]:
    if not issue_hypotheses:
        return {}
    route_options = [str(route_id).strip() for route_id in issue_hypotheses[0].get("route_options", []) if str(route_id).strip()]
    if not route_options:
        return {}
    route = route_options[0]
    rule = PLAYBOOK_BY_ROUTE.get(route)
    if rule is None:
        return {}
    return {"route": rule.route, "tool_name": rule.tool_name}


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
    return [sanitize_message_text(item) for item in messages]


def build_live_message_log(
    *,
    task: SampleTask,
    retrieved_docs: list[CorpusDoc],
    route: str,
    tool_name: str,
    strongest_competing_route: str,
    validation_check: str,
    replay_hit: bool,
) -> list[str]:
    doc_phrase = ", ".join(doc.doc_id for doc in retrieved_docs[:3])
    messages = [
        f"Planner: read the request and keep the collaboration text-only for {task.task_theme}.",
        f"Retriever: use local docs {doc_phrase} and quote only short snippets into the conversation.",
    ]
    if replay_hit:
        messages.append(
            f"Executor: retrieval matched a prior text-only decision for route {route} with tool {tool_name}."
        )
        messages.append("Summarizer: reuse the prior text summary because the evidence set matched exactly.")
        return [sanitize_message_text(item) for item in messages]
    messages.append(
        f"Executor: choose route {route} and tool {tool_name}; strongest competing route is {strongest_competing_route or 'none'}."
    )
    messages.append(
        f"Summarizer: return the first action and the validation check `{validation_check or 'confirm the top evidence path'}` in plain text."
    )
    return [sanitize_message_text(item) for item in messages]


def build_strict_message_log(
    *,
    task: SampleTask,
    planner_steps: list[str],
    retrieved_docs: list[CorpusDoc],
    visible_candidates: list[dict[str, object]],
    route: str,
    tool_name: str,
    validation_check: str,
    replay_hit: bool,
) -> list[str]:
    messages = [
        "Planner: "
        + (
            "; ".join(planner_steps[:3])
            if planner_steps
            else f"organize a four-role text-only triage for {task.task_theme}"
        ),
        f"Retriever: inspect docs {', '.join(doc.doc_id for doc in retrieved_docs[:3])} and compare visible candidates "
        + ", ".join(f"{item['route']}::{item['tool_name']}" for item in visible_candidates[:3]),
    ]
    if replay_hit:
        messages.append(
            f"Executor: retrieval matched a prior strict pure-text decision for route {route} and tool {tool_name}."
        )
        messages.append("Summarizer: reuse the prior plain-text summary because the evidence set matched exactly.")
    else:
        messages.append(
            f"Executor: validate route {route} with tool {tool_name} under contract {validation_check}."
        )
        messages.append("Summarizer: return the first action and supporting evidence in plain text.")
    return [sanitize_message_text(item) for item in messages]


def build_planner_prompt(*, task: SampleTask, retrieved_docs: list[CorpusDoc]) -> str:
    doc_lines = "\n".join(
        f"- {doc.doc_id}: {render_snippet(doc.text, limit=220)}" for doc in retrieved_docs[:4]
    )
    choices = "\n".join(f"- {rule.route} -> {rule.tool_name}" for rule in PLAYBOOK_CATALOG)
    return "\n".join(
        [
            f"Task theme: {task.task_theme}",
            f"Goal: {task.goal}",
            f"User request: {task.query}",
            "Allowed route and tool pairs:",
            choices,
            "Retrieved local evidence:",
            doc_lines,
            "Return JSON with keys route, tool_name, strongest_competing_route, and validation_check.",
        ]
    )


def build_summary_prompt(
    *,
    task: SampleTask,
    retrieved_docs: list[CorpusDoc],
    route: str,
    tool_name: str,
    strongest_competing_route: str,
    validation_check: str,
) -> str:
    evidence_text = "\n".join(
        [
            render_snippet(doc.text, limit=180)
            for doc in retrieved_docs[:3]
        ]
    )
    actions_text = "\n".join(
        [
            f"- chosen route: {route}",
            f"- chosen tool: {tool_name}",
            f"- strongest competing route: {strongest_competing_route or 'none'}",
            f"- validation check: {validation_check or 'confirm the top evidence path'}",
        ]
    )
    return "\n".join(
        [
            f"Task ID: {task.task_id}",
            f"Task theme: {task.task_theme}",
            "Summary hint:",
            task.summary_hint,
            "",
            "Evidence note:",
            evidence_text,
            "",
            "Playbook actions:",
            actions_text,
            "",
            f"Tags: {', '.join(task.tags)}",
            "Reusable steps: retrieve, execute",
        ]
    )


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


def canonical_identity_token(text: str) -> str:
    stripped = str(text).strip().strip("`'\"")
    return re.sub(r"[^a-z0-9]+", "", stripped.lower())


def sanitize_message_text(text: str) -> str:
    sanitized = text.replace("StateRef", "state reference")
    for marker in ("EXECUTOR_DECISION_PACKET", "DENSE_EVIDENCE", "FEATURE_BUNDLE", "MEMORY_ASSIST_HINT", "MEMORY_ASSIST"):
        sanitized = sanitized.replace(marker, marker.lower().replace("_", " "))
    sanitized = sanitized.replace("<", "").replace(">", "")
    return sanitized.strip()


def _planner_steps(payload: dict[str, object]) -> list[str]:
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return []
    rendered: list[str] = []
    for item in steps:
        if isinstance(item, dict):
            action = str(item.get("action", "")).strip()
            role = str(item.get("owner_agent", "")).strip() or str(item.get("semantic_role", "")).strip()
            if action or role:
                rendered.append(f"{role or 'role'}:{action or 'step'}")
    return rendered


def _strict_visible_selection(
    *,
    retriever_payload: dict[str, object],
    visible_candidates: list[dict[str, object]],
) -> tuple[str, str]:
    route = str(retriever_payload.get("route", "")).strip()
    tool_name = str(retriever_payload.get("tool_name", "")).strip()
    if resolved := _resolve_visible_candidate_selection(
        route=route,
        tool_name=tool_name,
        visible_candidates=visible_candidates,
    ):
        return resolved
    visible_preview = ", ".join(
        f"{str(item['route']).strip()}::{str(item['tool_name']).strip()}"
        for item in visible_candidates[:4]
    )
    raise ValueError(
        "strict external pure-text retriever selected route/tool outside visible candidate set: "
        f"route={route!r} tool={tool_name!r} visible_preview=[{visible_preview}]"
    )


def _strict_action_contract(payload: dict[str, object]) -> str:
    contract = str(payload.get("action_contract", "")).strip()
    if contract not in {"execute_validated_tool", "abstain_collect_more_evidence"}:
        raise ValueError(
            "strict external pure-text executor returned unsupported action_contract"
        )
    return contract


def _strict_executor_selection(
    *,
    executor_payload: dict[str, object],
    visible_candidates: list[dict[str, object]],
    fallback_route: str,
    fallback_tool_name: str,
) -> tuple[str, str]:
    route = str(executor_payload.get("route", "")).strip()
    tool_name = str(executor_payload.get("tool_name", "")).strip()
    if resolved := _resolve_visible_candidate_selection(
        route=route,
        tool_name=tool_name,
        visible_candidates=visible_candidates,
    ):
        return resolved
    return fallback_route, fallback_tool_name


def _resolve_visible_candidate_selection(
    *,
    route: str,
    tool_name: str,
    visible_candidates: list[dict[str, object]],
) -> tuple[str, str] | None:
    visible_pairs = [
        (str(item["route"]).strip(), str(item["tool_name"]).strip())
        for item in visible_candidates
    ]
    if (route, tool_name) in visible_pairs:
        return (route, tool_name)

    by_canonical_pair = {
        (canonical_identity_token(candidate_route), canonical_identity_token(candidate_tool)): (
            candidate_route,
            candidate_tool,
        )
        for candidate_route, candidate_tool in visible_pairs
    }
    canonical_route = canonical_identity_token(route)
    canonical_tool = canonical_identity_token(tool_name)
    if canonical_route and canonical_tool:
        if resolved := by_canonical_pair.get((canonical_route, canonical_tool)):
            return resolved

    route_matches = [
        pair for pair in visible_pairs if canonical_route and canonical_identity_token(pair[0]) == canonical_route
    ]
    tool_matches = [
        pair for pair in visible_pairs if canonical_tool and canonical_identity_token(pair[1]) == canonical_tool
    ]
    if route_matches and tool_matches:
        shared = [pair for pair in route_matches if pair in tool_matches]
        if len(shared) == 1:
            return shared[0]
    if len(route_matches) == 1 and not canonical_tool:
        return route_matches[0]
    if len(tool_matches) == 1 and not canonical_route:
        return tool_matches[0]
    if len(route_matches) == 1 and len(tool_matches) == 1 and route_matches[0] == tool_matches[0]:
        return route_matches[0]
    return None


def _extract_summary_text(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{"):
        payload = extract_json_object(stripped)
        summary = str(payload.get("summary", "") or payload.get("s", "")).strip()
        if summary:
            return summary
    return stripped


def _usage_dict(result) -> dict[str, int]:
    usage = getattr(result, "usage", None)
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }


def _merge_usage(base: dict[str, int], delta: dict[str, int]) -> dict[str, int]:
    return {
        "prompt_tokens": int(base.get("prompt_tokens", 0)) + int(delta.get("prompt_tokens", 0)),
        "completion_tokens": int(base.get("completion_tokens", 0)) + int(delta.get("completion_tokens", 0)),
        "total_tokens": int(base.get("total_tokens", 0)) + int(delta.get("total_tokens", 0)),
    }


def _sanitize_route_tool(
    *,
    route: str,
    tool_name: str,
    fallback_route: str,
    fallback_tool_name: str,
) -> tuple[str, str]:
    route = route.strip()
    tool_name = tool_name.strip()
    if route in PLAYBOOK_BY_ROUTE and PLAYBOOK_BY_ROUTE[route].tool_name == tool_name:
        return route, tool_name
    if tool_name in PLAYBOOK_BY_TOOL and PLAYBOOK_BY_TOOL[tool_name].route == route:
        return route, tool_name
    return fallback_route, fallback_tool_name


def _best_competing_route(*, route: str, retrieved_docs: list[CorpusDoc]) -> str:
    combined_tokens = lexical_tokens("\n".join(doc.text for doc in retrieved_docs))
    scored = sorted(
        (
            (lexical_overlap(combined_tokens, set(rule.keywords)), rule.route)
            for rule in PLAYBOOK_CATALOG
            if rule.route != route
        ),
        reverse=True,
    )
    return scored[0][1] if scored and scored[0][0] > 0 else ""
