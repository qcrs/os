from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import msgpack

from protocol.messages import PlanStep, StateRef, StepResult
from statepool.store import MMAP_FILE_STORAGE, PY_SHARED_MEMORY_STORAGE, StatePool


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    timeout_s: float = 5.0


@dataclass
class ToolExecutionResult:
    tool_name: str
    route: str
    actions: list[str]
    reusable_steps: list[str]
    diagnostics: dict[str, Any] = field(default_factory=dict)
    sandbox_mode: str = "subprocess"


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, tool_name: str) -> ToolSpec:
        try:
            return self._tools[tool_name]
        except KeyError as exc:
            raise KeyError(f"unknown executor tool: {tool_name}") from exc

    def names(self) -> list[str]:
        return sorted(self._tools)


def default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="tool.cache_invalidation_playbook",
            description="Repo-local playbook for cache invalidation and stale inventory incidents.",
        )
    )
    registry.register(
        ToolSpec(
            name="tool.db_pool_triage",
            description="Repo-local playbook for DB pool saturation and contention incidents.",
        )
    )
    registry.register(
        ToolSpec(
            name="tool.collect_more_evidence",
            description="Fallback playbook when the current evidence is still too weak.",
            timeout_s=3.0,
        )
    )
    return registry


def build_feature_bundle(
    *,
    query: str,
    evidence_text: str,
    tags: list[str],
    reuse_signature: str,
    reused_memory: bool,
) -> dict[str, Any]:
    normalized_query = query.strip()
    normalized_tags = sorted({str(tag).strip() for tag in tags if str(tag).strip()})
    lowered = evidence_text.lower()
    cache_signals = _match_signals(
        lowered,
        (
            "cache invalidation",
            "stale inventory",
            "inventory aggregate",
            "cache freshness",
            "batch sync",
        ),
    )
    db_signals = _match_signals(
        lowered,
        (
            "db pool saturation",
            "database pool contention",
            "connection pool",
            "orders_created_at",
            "sql wait",
        ),
    )
    route = "generic_triage"
    matched_signals = list(cache_signals)
    if db_signals:
        route = "db_pool_saturation"
        matched_signals = list(db_signals)
    elif cache_signals:
        route = "cache_invalidation"

    query_terms = [
        token.strip(".,:;!?()[]{}")
        for token in normalized_query.lower().split()
        if len(token.strip(".,:;!?()[]{}")) >= 4
    ]
    return {
        "schema": "statebus.feature_bundle.v1",
        "route": route,
        "query": normalized_query,
        "query_terms": sorted(dict.fromkeys(query_terms)),
        "tags": normalized_tags,
        "matched_signals": matched_signals,
        "reuse_signature": reuse_signature,
        "reused_memory": bool(reused_memory),
        "evidence_chars": len(evidence_text),
        "evidence_lines": len([line for line in evidence_text.splitlines() if line.strip()]),
        "evidence_preview": evidence_text[:240],
        "evidence_sha256": hashlib.sha256(evidence_text.encode("utf-8")).hexdigest(),
    }


def select_tool_name(
    feature_bundle: dict[str, Any],
    *,
    registry: ToolRegistry | None = None,
) -> str:
    active_registry = registry or default_tool_registry()
    route = str(feature_bundle.get("route", "generic_triage"))
    if route == "cache_invalidation":
        return active_registry.get("tool.cache_invalidation_playbook").name
    if route == "db_pool_saturation":
        return active_registry.get("tool.db_pool_triage").name
    return active_registry.get("tool.collect_more_evidence").name


class LightweightSubprocessRunner:
    """Best-effort subprocess isolation for host-side tool execution.

    This is intentionally a lightweight host-only fallback and is not a secure
    sandbox equivalent to nsjail or container isolation.
    """

    def __init__(
        self,
        *,
        repo_root: str | Path | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent.parent
        self.python_executable = python_executable or sys.executable

    def execute(
        self,
        *,
        tool_name: str,
        payload: dict[str, Any],
        timeout_s: float,
    ) -> ToolExecutionResult:
        with tempfile.TemporaryDirectory(prefix="statebus-tool-run-") as tmpdir:
            request_path = Path(tmpdir) / "request.json"
            response_path = Path(tmpdir) / "response.json"
            request_path.write_text(
                json.dumps(payload, ensure_ascii=True, sort_keys=True),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    self.python_executable,
                    "-m",
                    "runtime.tool_worker",
                    "--tool",
                    tool_name,
                    "--request",
                    str(request_path),
                    "--response",
                    str(response_path),
                ],
                cwd=self.repo_root,
                env=self._sandbox_env(),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
            if completed.returncode != 0:
                stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown tool failure"
                raise RuntimeError(f"{tool_name} failed in lightweight sandbox: {stderr}")
            if not response_path.exists():
                raise RuntimeError(f"{tool_name} did not write response payload")
            response = json.loads(response_path.read_text(encoding="utf-8"))
        return ToolExecutionResult(
            tool_name=str(response.get("tool_name", tool_name)),
            route=str(response.get("route", payload.get("feature_bundle", {}).get("route", "generic_triage"))),
            actions=[str(item) for item in response.get("actions", [])],
            reusable_steps=[str(item) for item in response.get("reusable_steps", [])],
            diagnostics=dict(response.get("diagnostics", {}) or {}),
            sandbox_mode=str(response.get("sandbox_mode", "subprocess")),
        )

    def _sandbox_env(self) -> dict[str, str]:
        env: dict[str, str] = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", str(self.repo_root)),
            "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
            "PYTHONNOUSERSITE": "1",
        }
        current_pythonpath = os.environ.get("PYTHONPATH", "").strip()
        repo_root = str(self.repo_root)
        env["PYTHONPATH"] = (
            repo_root if not current_pythonpath else f"{repo_root}{os.pathsep}{current_pythonpath}"
        )
        return env


def run_registered_tool(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    feature_bundle = dict(payload.get("feature_bundle", {}) or {})
    route = str(feature_bundle.get("route", "generic_triage"))
    matched_signals = [str(item) for item in feature_bundle.get("matched_signals", [])]
    if tool_name == "tool.cache_invalidation_playbook":
        return {
            "tool_name": tool_name,
            "route": route,
            "actions": [
                "force inventory aggregate invalidation",
                "rerun post-sync invalidation hook",
                "verify cache freshness after batch sync",
            ],
            "reusable_steps": ["retrieve", "execute"],
            "diagnostics": {
                "matched_signals": matched_signals,
                "evidence_sha256": feature_bundle.get("evidence_sha256"),
            },
            "sandbox_mode": "subprocess",
        }
    if tool_name == "tool.db_pool_triage":
        return {
            "tool_name": tool_name,
            "route": route,
            "actions": [
                "rollback release-17",
                "create orders_created_at index",
                "check database pool sizing",
            ],
            "reusable_steps": ["retrieve", "execute"],
            "diagnostics": {
                "matched_signals": matched_signals,
                "evidence_sha256": feature_bundle.get("evidence_sha256"),
            },
            "sandbox_mode": "subprocess",
        }
    if tool_name == "tool.collect_more_evidence":
        return {
            "tool_name": tool_name,
            "route": route,
            "actions": ["collect more evidence"],
            "reusable_steps": ["retrieve"],
            "diagnostics": {
                "matched_signals": matched_signals,
                "evidence_sha256": feature_bundle.get("evidence_sha256"),
            },
            "sandbox_mode": "subprocess",
        }
    raise KeyError(f"unsupported tool name: {tool_name}")


def execute_playbook_step(
    *,
    task_id: str,
    task_theme: str,
    step: PlanStep,
    statepool: StatePool,
    input_state_refs: list[StateRef],
    runner: LightweightSubprocessRunner | None = None,
    registry: ToolRegistry | None = None,
    output_storage: str | None = None,
) -> StepResult:
    evidence_ref = next((ref for ref in input_state_refs if ref.kind == "DENSE_EVIDENCE"), None)
    feature_ref = next((ref for ref in input_state_refs if ref.kind == "FEATURE_BUNDLE"), None)
    if evidence_ref is None:
        raise ValueError(f"step {step.step_id} missing DENSE_EVIDENCE input")
    if feature_ref is None:
        raise ValueError(f"step {step.step_id} missing FEATURE_BUNDLE input")

    feature_bundle = _load_feature_bundle(statepool, feature_ref)
    active_registry = registry or default_tool_registry()
    tool_name = select_tool_name(feature_bundle, registry=active_registry)
    tool_spec = active_registry.get(tool_name)
    active_runner = runner or LightweightSubprocessRunner()
    execution = active_runner.execute(
        tool_name=tool_name,
        payload={
            "task_id": task_id,
            "task_theme": task_theme,
            "step_id": step.step_id,
            "feature_bundle": feature_bundle,
            "evidence_text": statepool.get_text(evidence_ref),
        },
        timeout_s=tool_spec.timeout_s,
    )
    artifact_text = "\n".join(execution.actions)
    preferred_storage = (
        output_storage
        or (
        evidence_ref.storage
        if evidence_ref.storage in {MMAP_FILE_STORAGE, PY_SHARED_MEMORY_STORAGE}
        else None
        )
    )
    artifact_ref = statepool.put_bytes(
        state_id=f"{task_id}-{step.step_id}-artifact",
        kind="TOOL_ARTIFACT",
        payload=artifact_text.encode("utf-8"),
        metadata={
            "source_evidence": evidence_ref.state_id,
            "source_features": feature_ref.state_id,
            "tool_name": execution.tool_name,
            "route": execution.route,
            "sandbox_mode": execution.sandbox_mode,
        },
        storage=preferred_storage,
    )
    return StepResult(
        step_id=step.step_id,
        success=True,
        output_state_refs=[artifact_ref],
        payload={
            "actions": execution.actions,
            "reusable_steps": execution.reusable_steps,
            "tool_name": execution.tool_name,
            "route": execution.route,
            "sandbox_mode": execution.sandbox_mode,
            "matched_signals": list(execution.diagnostics.get("matched_signals", [])),
            "feature_state_id": feature_ref.state_id,
        },
    )


def _load_feature_bundle(statepool: StatePool, ref: StateRef) -> dict[str, Any]:
    payload = statepool.get_bytes(ref)
    feature_bundle = msgpack.unpackb(payload, raw=False, strict_map_key=False)
    if not isinstance(feature_bundle, dict):
        raise ValueError(f"feature bundle {ref.state_id} is not a map")
    return dict(feature_bundle)


def _match_signals(text: str, patterns: tuple[str, ...]) -> list[str]:
    return [pattern for pattern in patterns if pattern in text]
