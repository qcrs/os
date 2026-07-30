from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ROLE_GRAPH = "planner->retriever->executor->summarizer"
ROLE_CONTRACT_SCHEMA_VERSION = "statebus.role_contract_audit.v1"
ROLE_ORDER = ("planner", "retriever", "executor", "summarizer")


@dataclass(frozen=True)
class RoleContract:
    role: str
    responsibility: str
    required_metric_keys: tuple[str, ...]
    produced_artifacts: tuple[str, ...]
    forbidden_scope: tuple[str, ...]

    def canonical_payload(self) -> dict[str, object]:
        return {
            "role": self.role,
            "responsibility": self.responsibility,
            "required_metric_keys": list(self.required_metric_keys),
            "produced_artifacts": list(self.produced_artifacts),
            "forbidden_scope": list(self.forbidden_scope),
        }


ROLE_CONTRACTS: tuple[RoleContract, ...] = (
    RoleContract(
        role="planner",
        responsibility="compile task intent into workflow steps, retrieval objective, and required outputs",
        required_metric_keys=("planner_call_count", "planner_generated_retrieval_objective_count"),
        produced_artifacts=("planner_handoff", "workflow_steps", "retrieval_objective"),
        forbidden_scope=("execute tools", "materialize final artifact", "commit memory"),
    ),
    RoleContract(
        role="retriever",
        responsibility="select bounded evidence, route/tool candidates, semantic state, and retrieval logs",
        required_metric_keys=("retriever_call_count", "retrieval_log_count", "retrieval_candidate_pool_count"),
        produced_artifacts=("evidence_pack", "hydrate_manifest", "retrieval_log", "query_embedding"),
        forbidden_scope=("change required outputs", "write final answer", "settle execution artifact"),
    ),
    RoleContract(
        role="executor",
        responsibility="execute validated tool or bounded CodeAct action and publish execution artifact",
        required_metric_keys=("executor_call_count", "artifact_count", "verified_artifact_ref_count"),
        produced_artifacts=("execution_artifact_ref", "artifact_manifest", "execution_step_record"),
        forbidden_scope=("select hidden evidence outside retrieved set", "commit memory summary"),
    ),
    RoleContract(
        role="summarizer",
        responsibility="synthesize answer, quality-floor result, replay ledger, and memory commit",
        required_metric_keys=("summarizer_call_count", "memory_ref_count", "runtime_session_count"),
        produced_artifacts=("summary_artifact", "memory_commit", "replay_ledger"),
        forbidden_scope=("reroute tools", "mutate execution artifact payload"),
    ),
)


def role_contracts_payload() -> dict[str, object]:
    return {
        "schema_version": ROLE_CONTRACT_SCHEMA_VERSION,
        "role_graph": ROLE_GRAPH,
        "roles": [contract.canonical_payload() for contract in ROLE_CONTRACTS],
    }


def audit_role_contract_report(report_payload: dict[str, Any]) -> dict[str, object]:
    telemetry_summary = _extract_telemetry_summary(report_payload)
    observed_role_graphs = _extract_metadata_values(report_payload, "role_graph")
    role_results = []
    failed_checks: list[str] = []

    role_graph = observed_role_graphs[0] if observed_role_graphs else ""
    if not observed_role_graphs or any(graph != ROLE_GRAPH for graph in observed_role_graphs):
        failed_checks.append("role_graph")

    for contract in ROLE_CONTRACTS:
        missing_metric_keys = [
            key
            for key in contract.required_metric_keys
            if float(telemetry_summary.get(key, 0.0)) <= 0.0
        ]
        passed = not missing_metric_keys
        if not passed:
            failed_checks.append(f"{contract.role}_metrics")
        role_results.append(
            {
                "role": contract.role,
                "passed": passed,
                "missing_metric_keys": missing_metric_keys,
                "required_metric_values": {
                    key: float(telemetry_summary.get(key, 0.0))
                    for key in contract.required_metric_keys
                },
                "produced_artifacts": list(contract.produced_artifacts),
                "forbidden_scope": list(contract.forbidden_scope),
            }
        )

    return {
        "schema_version": ROLE_CONTRACT_SCHEMA_VERSION,
        "role_graph": role_graph,
        "observed_role_graphs": observed_role_graphs,
        "expected_role_graph": ROLE_GRAPH,
        "pass": not failed_checks,
        "failed_checks": failed_checks,
        "roles": role_results,
        "contract": role_contracts_payload(),
    }


def _extract_telemetry_summary(report_payload: dict[str, Any]) -> dict[str, float]:
    totals: dict[str, float] = {}

    def _visit(node: Any) -> None:
        if isinstance(node, dict):
            for section in ("telemetry_summary", "metrics"):
                metrics = node.get(section, {})
                if isinstance(metrics, dict):
                    for key, value in metrics.items():
                        totals[str(key)] = totals.get(str(key), 0.0) + _float_value(value)
            for child_key in ("layers", "layer_reports", "family_reports", "cases", "mode_reports"):
                children = node.get(child_key, [])
                if isinstance(children, list):
                    for child in children:
                        _visit(child)
            for child_key in ("statebus_report", "external_report"):
                child = node.get(child_key)
                if isinstance(child, dict):
                    _visit(child)
        elif isinstance(node, list):
            for child in node:
                _visit(child)

    _visit(report_payload)
    return totals


def _extract_metadata_values(report_payload: dict[str, Any], key: str) -> list[str]:
    values: list[str] = []

    def _visit(node: Any) -> None:
        if isinstance(node, dict):
            metadata = node.get("metadata", {})
            if isinstance(metadata, dict) and metadata.get(key):
                values.append(str(metadata[key]))
            for child_key in ("layers", "layer_reports", "family_reports", "cases", "mode_reports"):
                children = node.get(child_key, [])
                if isinstance(children, list):
                    for child in children:
                        _visit(child)
            for child_key in ("statebus_report", "external_report"):
                child = node.get(child_key)
                if isinstance(child, dict):
                    _visit(child)
        elif isinstance(node, list):
            for child in node:
                _visit(child)

    _visit(report_payload)
    return sorted(set(values))


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
