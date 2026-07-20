from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from typing import Iterable

from runtime.llm import LLMConfig
from v2.runtime.capability_registry import CapabilityRegistry
from v2.runtime.domain_packs import register_generic_adaptive_analysis_capabilities
from v2.runtime.runtime_signature import capture_runtime_signature, runtime_signature_payload
from v2.utils import sha256_digest, stable_json_dumps


_STAGE_IDS = {
    "focused": "E0",
    "causal": "E1",
    "stress": "E2",
    "adaptive-memory": "E3",
    "semantic-holdout": "E4",
    "adaptive": "E5",
    "full": "E6",
}
_LIVE_STAGES = {"causal", "stress", "adaptive-memory", "semantic-holdout", "adaptive"}
_AUDIT_DIRS = (
    "case_reports",
    "role_requests",
    "state_consumption",
    "memory_queries",
    "memory_consumption",
    "replay_decisions",
    "artifact_lineage",
)
_FOCUSED_TESTS = (
    "tests/v2/test_adaptive_formal_compare.py",
    "tests/v2/test_adaptive_role_prompts.py",
    "tests/v2/test_continuous_runner.py",
    "tests/v2/test_continuous_suite_schedule.py",
    "tests/v2/test_hybrid_memory_query.py",
    "tests/v2/test_replay.py",
    "tests/v2/test_adaptive_dispatcher.py",
    "tests/v2/test_adaptive_mainline_integration.py",
    "tests/v2/test_continuous_task_family_loader.py",
    "tests/v2/test_continuous_task_family_design.py",
    "tests/v2/test_retrieval_capability_routing.py",
    "tests/v2/test_adaptive_structured_markdown_retrieval.py",
    "tests/v2/test_embedding_state_consumer.py",
    "tests/v2/test_contest_fairness.py",
    "tests/v2/test_subprocess_executor.py",
)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")


def _git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _model_profiles(run_root: Path) -> dict[str, object]:
    config = LLMConfig.from_runtime()
    roles = {
        role: {
            "model": role_config.model,
            "temperature": role_config.temperature,
            "max_tokens": role_config.max_tokens,
            "max_context_tokens": role_config.max_context_tokens,
            "reasoning_effort": role_config.reasoning_effort,
            "json_output": role_config.json_output,
            "seed": role_config.request_kwargs.get(
                "seed", role_config.extra_body.get("seed")
            ),
        }
        for role, role_config in sorted(config.roles.items())
    }
    config_path = Path(config.source)
    vllm_models_path = run_root / "vllm_models.json"
    vllm_models: dict[str, object] = {}
    if vllm_models_path.is_file():
        try:
            payload = json.loads(vllm_models_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                vllm_models = payload
        except json.JSONDecodeError:
            pass
    embedding_root = Path(
        os.getenv("STATEBUS_EMBED_MODEL_PATH", "/statebus/models/Qwen3-Embedding-0.6B")
    )
    embedding_config_path = embedding_root / "config.json"
    embedding_config: dict[str, object] = {}
    if embedding_config_path.is_file():
        try:
            payload = json.loads(embedding_config_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                embedding_config = payload
        except json.JSONDecodeError:
            pass
    profile = {
        "llm_mode": config.mode,
        "llm_config_source": config.source,
        "llm_config_sha256": (
            hashlib.sha256(config_path.read_bytes()).hexdigest()
            if config_path.is_file()
            else ""
        ),
        "roles": roles,
        "role_seed_boundary": (
            "explicit_per-role value when present; otherwise the current profile does not set a server seed"
        ),
        "vllm_models_response_sha256": (
            hashlib.sha256(vllm_models_path.read_bytes()).hexdigest()
            if vllm_models_path.is_file()
            else ""
        ),
        "vllm_models": [
            {
                key: item.get(key)
                for key in ("id", "root", "parent", "owned_by", "max_model_len")
                if key in item
            }
            for item in vllm_models.get("data", [])
            if isinstance(item, dict)
        ],
        "embedding_model_path": str(embedding_root),
        "embedding_config_sha256": (
            hashlib.sha256(embedding_config_path.read_bytes()).hexdigest()
            if embedding_config_path.is_file()
            else ""
        ),
        "embedding_revision": embedding_config.get(
            "_commit_hash", embedding_config.get("transformers_version", "")
        ),
        "embedding_architectures": embedding_config.get("architectures", []),
    }
    profile["profile_digest"] = sha256_digest(profile)
    return profile


def _validator_digest() -> str:
    paths = (
        Path("v2/runtime/capability_validators.py"),
        Path("v2/benchmark/adaptive_formal.py"),
        Path("v2/benchmark/scoring.py"),
    )
    return sha256_digest([
        {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in paths
    ])


def _environment_payload(run_root: Path) -> dict[str, object]:
    os_release: dict[str, str] = {}
    path = Path("/etc/os-release")
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            os_release[key] = value.strip().strip('"')
    return {
        "schema_version": "statebus.contest_environment.v1",
        "container_name": os.getenv("STATEBUS_V2_CONTAINER_NAME", "statebus-dev-qcrs"),
        "container_image": os.getenv("STATEBUS_CONTEST_IMAGE", ""),
        "container_image_id": os.getenv("STATEBUS_CONTEST_IMAGE_ID", ""),
        "container_image_digest": os.getenv("STATEBUS_CONTEST_IMAGE_DIGEST", ""),
        "os_release": dict(sorted(os_release.items())),
        "platform": platform.platform(),
        "python": sys.version,
        "python_executable": sys.executable,
        "bwrap_status": os.getenv("STATEBUS_CONTEST_BWRAP_STATUS", "unknown"),
        "cuda_status": os.getenv("STATEBUS_CONTEST_CUDA_STATUS", "unknown"),
        "vllm_health_status": os.getenv("STATEBUS_CONTEST_VLLM_HEALTH_STATUS", "unknown"),
        "physical_gpu": os.getenv("CUDA_VISIBLE_DEVICES", ""),
        "embedding_device": os.getenv("STATEBUS_EMBED_DEVICE", ""),
        "role_model": os.getenv("STATEBUS_LOCAL_VLLM_MODEL", "qwen3-32b"),
        "role_model_base_url": os.getenv(
            "STATEBUS_LOCAL_VLLM_BASE_URL", "http://127.0.0.1:53334/v1"
        ),
        "embedding_model_path": os.getenv(
            "STATEBUS_EMBED_MODEL_PATH", "/statebus/models/Qwen3-Embedding-0.6B"
        ),
        "model_profiles": _model_profiles(run_root),
        "recorded_at": _now(),
    }


def _generic_capability_registry() -> dict[str, object]:
    registry = CapabilityRegistry()
    pack = register_generic_adaptive_analysis_capabilities(
        registry,
        analysis_validator_ids=("formal_analysis", "generic_analysis"),
    )
    return {
        "schema_version": "statebus.contest_capability_registry.v1",
        "pack_id": pack.pack_id,
        "registry_digest": registry.digest,
        "capability_ids": list(pack.capability_ids),
        "public_descriptors": list(registry.public_view(pack.capability_ids)),
        "contains_expected_answers": False,
        "scope_note": (
            "This is the six-capability adaptive surface. Continuous case reports retain their "
            "own capability-surface digests in fairness artifacts."
        ),
    }


def _manifest_hash(stage: str) -> str:
    roots: tuple[Path, ...]
    if stage in {"causal", "stress"}:
        roots = (
            Path("v2/benchmark/samples/continuous_task_families/formal_financial_reports/manifest.json"),
            Path("v2/benchmark/samples/continuous_task_families/formal_operating_metrics/manifest.json"),
        )
    elif stage == "semantic-holdout":
        roots = (Path("v2/benchmark/samples/semantic_holdout/manifest.json"),)
    else:
        roots = tuple(sorted(Path("tasks/formal").glob("*/task_manifest.yaml"))) + tuple(
            sorted(Path("v2/benchmark/samples/formal_financial_family").glob("*.json"))
        )
    return sha256_digest([
        {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in roots
        if path.is_file()
    ])


def _stage_command(stage: str, run_root: Path) -> tuple[str, list[str]]:
    python = sys.executable
    common_live = [
        python,
        "-m",
        "v2.benchmark.live_runner",
        "--benchmark-tier",
        "formal",
        "--role-path-mode",
        "local_vllm",
        "--embedding-mode",
        "local",
        "--state-pool-mode",
        "shared_memory",
        "--transport",
        "subprocess",
        "--workspace-root",
        str(run_root / "workspaces"),
        "--runtime-root",
        str(run_root / "runtime"),
        "--socket-path",
        str(run_root / "control.sock"),
        "--suite-id",
        f"contest-{_STAGE_IDS[stage].lower()}",
    ]
    if stage == "focused":
        return "pytest", [python, "-m", "pytest", "-q", *_FOCUSED_TESTS]
    if stage == "causal":
        return "continuous_causal", [
            *common_live,
            "--suite",
            "continuous",
            "--round-view",
            "causal_core",
            "--executor-mode",
            "deterministic_codeact",
        ]
    if stage == "stress":
        return "continuous_stress", [
            *common_live,
            "--suite",
            "continuous",
            "--round-view",
            "long_horizon",
            "--layer",
            "L3",
            "--executor-mode",
            "deterministic_codeact",
        ]
    if stage == "adaptive-memory":
        return "adaptive_memory", [*common_live, "--suite", "adaptive-memory"]
    if stage == "semantic-holdout":
        return "semantic_holdout", [*common_live, "--suite", "semantic-holdout"]
    if stage == "adaptive":
        return "adaptive_formal", [
            python,
            "-m",
            "v2.benchmark.adaptive_formal_mainline",
            "--output-root",
            str(run_root / "raw"),
            "--embedding-model-path",
            os.getenv("STATEBUS_EMBED_MODEL_PATH", "/statebus/models/Qwen3-Embedding-0.6B"),
            "--embedding-device",
            os.getenv("STATEBUS_EMBED_DEVICE", "cuda:0"),
            "--max-cases",
            "25",
            "--lane",
            "adaptive",
            "--exit-gate",
            "all-correct",
        ]
    if stage == "full":
        return "pytest", [python, "-m", "pytest", "-q", "tests/v2"]
    raise ValueError(f"unknown contest stage: {stage}")


def _run_child(
    *,
    name: str,
    command: list[str],
    log_path: Path,
    console_path: Path,
) -> tuple[int, float]:
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as child_log, console_path.open(
        "a", encoding="utf-8"
    ) as console:
        command_text = " ".join(command)
        console.write(f"[{_now()}] START {name}: {command_text}\n")
        console.flush()
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            child_log.write(line)
            child_log.flush()
        return_code = process.wait()
        elapsed = time.perf_counter() - started
        console.write(f"[{_now()}] END {name}: exit={return_code} elapsed_s={elapsed:.3f}\n")
    return return_code, elapsed


def _parse_last_json_line(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _latest_nested_summary(run_root: Path) -> dict[str, object]:
    candidates = sorted(
        path
        for path in run_root.rglob("summary.json")
        if path != run_root / "summary.json"
        and "case_reports" not in path.parts
    )
    ranked: list[tuple[int, Path, dict[str, object]]] = []
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        schema = str(payload.get("schema_version", ""))
        rank = 0 if schema == "statebus.adaptive_formal_case.v1" else 2
        if schema in {
            "statebus.adaptive_formal_compare.v3",
            "statebus.adaptive_memory_summary.v1",
            "statebus.semantic_holdout_summary.v1",
        }:
            rank = 3
        ranked.append((rank, path, payload))
    return max(ranked, key=lambda item: (item[0], str(item[1])))[2] if ranked else {}


def _case_payloads(payload: object, *, context: dict[str, object] | None = None) -> Iterable[dict[str, object]]:
    inherited = dict(context or {})
    if isinstance(payload, list):
        for item in payload:
            yield from _case_payloads(item, context=inherited)
        return
    if not isinstance(payload, dict):
        return
    for key in ("layer", "task_family", "suite_id"):
        if key in payload:
            inherited[key] = payload[key]
    if "task_id" in payload and any(
        key in payload
        for key in (
            "quality_floor",
            "selected_capability_ids",
            "expected_facts_report",
            "audit_summary",
            "telemetry",
        )
    ):
        yield {**inherited, **payload}
    for key in (
        "family_reports",
        "layers",
        "cases",
        "adaptive_cases",
        "adaptive_case_summaries",
        "case_summaries",
    ):
        if key in payload:
            yield from _case_payloads(payload[key], context=inherited)


def _load_full_adaptive_cases(run_root: Path) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for path in sorted(run_root.rglob("summary.json")):
        if path == run_root / "summary.json" or "case_reports" in path.parts:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("schema_version") == "statebus.adaptive_formal_case.v1":
            cases.append(payload)
    return cases


def _slug(value: object) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-")
    return normalized or "unknown"


def _audit_slice(case: dict[str, object], category: str) -> dict[str, object]:
    audit = case.get("audit_summary", {})
    audit = audit if isinstance(audit, dict) else {}
    contest_context = case.get("contest_evidence_context", {})
    if category == "role_requests":
        return {
            "contest_evidence_context": contest_context,
            "task_id": case.get("task_id"),
            "role_invocations": case.get("role_invocations", []),
            "model_roles_observed": case.get("model_roles_observed", []),
            "role_path_mode": audit.get("role_path_mode", ""),
            "gold_visibility_audit": audit.get("gold_visibility_audit", {}),
        }
    if category == "state_consumption":
        return {
            "contest_evidence_context": contest_context,
            "task_id": case.get("task_id"),
            "records": case.get("state_consumption_records", audit.get("state_consumption_records", [])),
            "selections": case.get("semantic_state_selections", {}),
            "semantic_state": {
                key: value for key, value in audit.items()
                if "semantic" in key or "hydration" in key or "state_consum" in key
            },
        }
    if category == "memory_queries":
        return {
            "contest_evidence_context": contest_context,
            "task_id": case.get("task_id"),
            "results": case.get("memory_query_results", {}),
            "metrics": {
                key: value for key, value in case.get("metrics", case.get("telemetry", {})).items()
                if "memory" in key and ("query" in key or "candidate" in key or "match" in key)
            },
        }
    if category == "memory_consumption":
        return {
            "contest_evidence_context": contest_context,
            "task_id": case.get("task_id"),
            "role_inputs": case.get("memory_role_inputs_by_step", {}),
            "records": case.get("memory_consumption_records", []),
            "metrics": {
                key: value for key, value in case.get("metrics", case.get("telemetry", {})).items()
                if "memory" in key or "replay" in key or "skipped" in key
            },
        }
    if category == "replay_decisions":
        return {
            "contest_evidence_context": contest_context,
            "task_id": case.get("task_id"),
            "replay_class": case.get("replay_class", ""),
            "memory_commit_decision": case.get("memory_commit_decision", {}),
            "replay_audit": {
                key: value for key, value in audit.items()
                if "replay" in key or "compatib" in key
            },
        }
    if category == "artifact_lineage":
        return {
            "contest_evidence_context": contest_context,
            "task_id": case.get("task_id"),
            "output_artifact_hash": case.get(
                "execution_output_artifact_hash", case.get("output_artifact_hash", "")
            ),
            "output_artifact_path": case.get("output_artifact_path", ""),
            "source_artifact_hash": case.get("source_artifact_hash", ""),
            "audit_paths": case.get("audit_paths", {}),
            "runtime_session": case.get("runtime_session", {}),
        }
    raise ValueError(category)


def _fairness_manifest(payload: dict[str, object], stage: str) -> dict[str, object]:
    family_manifests: list[dict[str, object]] = []
    for family in payload.get("family_reports", []):
        if not isinstance(family, dict):
            continue
        metadata = family.get("metadata", {})
        if isinstance(metadata, dict) and isinstance(metadata.get("fairness_manifest"), dict):
            family_manifests.append(metadata["fairness_manifest"])
    if family_manifests:
        return {
            "schema_version": "statebus.contest_fairness_collection.v1",
            "stage": stage,
            "family_manifests": family_manifests,
            "comparison_valid": all(
                manifest.get("comparison_valid") is True
                for manifest in family_manifests
            ) if stage == "causal" else True,
        }
    return {
        "schema_version": "statebus.contest_fairness_collection.v1",
        "stage": stage,
        "comparison_valid": stage not in {"causal"} or bool(payload.get("formal_headline_eligible")),
        "benchmark_oracle_visible_to_roles": payload.get(
            "benchmark_oracle_visible_to_roles", False
        ),
        "gates": payload.get("gates", {}),
        "scope": "non-comparative engineering gate" if stage not in {"causal"} else "causal matrix",
    }


def _case_quality_passed(case: dict[str, object]) -> bool:
    quality_floor = case.get("quality_floor", {})
    quality_floor = quality_floor if isinstance(quality_floor, dict) else {}
    return bool(case.get("ok") or quality_floor.get("quality_floor_pass"))


def _stage_acceptance(stage: str, payload: dict[str, object]) -> dict[str, bool]:
    cases = list(_case_payloads(payload))
    layer_counts = Counter(str(case.get("layer", "")) for case in cases)
    layer_pass_counts = Counter(
        str(case.get("layer", ""))
        for case in cases
        if _case_quality_passed(case)
    )
    family_counts = Counter(str(case.get("task_family", "")) for case in cases)
    collection = payload.get("collection_summary", {})
    collection = collection if isinstance(collection, dict) else {}
    metadata = payload.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}

    if stage == "causal":
        return {
            "formal_causal_scope": bool(
                payload.get("formal_headline_eligible")
                or metadata.get("formal_headline_eligible")
            ),
            "case_count_40": len(cases) == 40,
            "each_lane_10_of_10": all(
                layer_counts[layer] == 10 and layer_pass_counts[layer] == 10
                for layer in ("L0", "L1", "L2", "L3")
            ),
            "two_families": len(family_counts) == 2,
            "fairness_comparison_valid": bool(
                _fairness_manifest(payload, stage).get("comparison_valid")
            ),
            "semantic_state_observed": float(
                collection.get("L2_semantic_state_transfer_count", 0.0)
            ) > 0.0,
            "memory_consumed": float(
                collection.get("L3_memory_consumed_count", 0.0)
            ) > 0.0,
            "memory_behavioral_effect_observed": float(
                collection.get("L3_memory_behavioral_effect_count", 0.0)
            ) > 0.0,
            "validated_replay_targets_observed": float(
                collection.get("validated_replay_count", 0.0)
            ) >= 2.0,
        }
    if stage == "stress":
        return {
            "formal_stability_scope": bool(
                payload.get("stability_evidence_eligible")
                or metadata.get("stability_evidence_eligible")
            ),
            "case_count_20": len(cases) == 20,
            "l3_20_of_20": (
                layer_counts["L3"] == 20 and layer_pass_counts["L3"] == 20
            ),
            "two_families_10_each": (
                len(family_counts) == 2
                and all(count == 10 for count in family_counts.values())
            ),
            "memory_consumed": float(
                collection.get("L3_memory_consumed_count", 0.0)
            ) > 0.0,
            "memory_behavioral_effect_observed": float(
                collection.get("L3_memory_behavioral_effect_count", 0.0)
            ) > 0.0,
            "incompatible_candidates_rejected": float(
                collection.get("L3_memory_rejected_incompatible_count", 0.0)
            ) >= 2.0,
        }
    if stage == "adaptive-memory":
        gates = payload.get("gates", {})
        gates = gates if isinstance(gates, dict) else {}
        return {
            "suite_reported_ok": payload.get("ok") is True,
            "quality_6_of_6": (
                int(payload.get("case_count", 0)) == 6
                and int(payload.get("quality_pass_count", 0)) == 6
            ),
            "all_product_gates": bool(gates) and all(value is True for value in gates.values()),
        }
    if stage == "semantic-holdout":
        gates = payload.get("gates", {})
        gates = gates if isinstance(gates, dict) else {}
        capabilities = payload.get("capability_counts", {})
        capabilities = capabilities if isinstance(capabilities, dict) else {}
        return {
            "suite_reported_ok": payload.get("ok") is True,
            "quality_4_of_4": (
                int(payload.get("case_count", 0)) == 4
                and int(payload.get("quality_pass_count", 0)) == 4
            ),
            "semantic_route_at_least_2": int(
                capabilities.get("retrieve_semantic_evidence_v1", 0)
            ) >= 2,
            "table_route_at_least_1": int(
                capabilities.get("retrieve_table_evidence_v1", 0)
            ) >= 1,
            "all_product_gates": bool(gates) and all(value is True for value in gates.values()),
        }
    if stage == "adaptive":
        metrics = payload.get("adaptive_metrics", {})
        metrics = metrics if isinstance(metrics, dict) else {}
        return {
            "all_correct_exit_gate": payload.get("selected_exit_gate_passed") is True,
            "quality_25_of_25": (
                int(payload.get("selected_case_count", 0)) == 25
                and int(metrics.get("quality_pass_count", 0)) == 25
            ),
            "dsl_observed": float(metrics.get("dsl_verified_count", 0.0)) > 0.0,
            "bounded_python_observed": float(
                metrics.get("codeact_verified_count", 0.0)
            ) > 0.0,
            "fallback_zero": all(
                float(metrics.get(key, 0.0)) == 0.0
                for key in (
                    "fallback_count",
                    "model_fallback_count",
                    "codeact_sandbox_fallback_count",
                )
            ),
        }
    return {
        "engineering_gate_reported_ok": payload.get("ok") is True,
        "pytest_passed": payload.get("pytest_passed") is True,
        "preflight_ok": payload.get("preflight_ok") is True,
    }


def _materialize_artifact_contract(
    *,
    run_root: Path,
    stage: str,
    payload: dict[str, object],
    run_manifest: dict[str, object],
) -> None:
    for directory in _AUDIT_DIRS:
        (run_root / directory).mkdir(parents=True, exist_ok=True)
    cases = list(_case_payloads(payload))
    full_adaptive = _load_full_adaptive_cases(run_root)
    full_adaptive_task_ids = {
        str(case.get("task_id", ""))
        for case in full_adaptive
        if case.get("task_id")
    }
    if full_adaptive_task_ids:
        cases = [
            case
            for case in cases
            if str(case.get("task_id", "")) not in full_adaptive_task_ids
        ]
    by_case = {
        (
            str(case.get("task_id")),
            str(case.get("task_family", "")),
            str(case.get("layer", "")),
        ): case
        for case in cases
    }
    by_case.update({
        (
            str(case.get("task_id")),
            str(case.get("task_family", "")),
            str(case.get("layer", "")),
        ): case
        for case in full_adaptive
    })
    cases = list(by_case.values())
    filename_counts: Counter[str] = Counter()
    materialized_cases: list[dict[str, object]] = []
    for native_case in cases:
        effective_lane = str(
            native_case.get("layer") or run_manifest.get("lane") or stage
        )
        case = {
            **native_case,
            "contest_evidence_context": {
                "experiment_id": run_manifest.get("experiment_id", _STAGE_IDS[stage]),
                "stage": stage,
                "lane": effective_lane,
                "run_id": run_root.name,
                "serial_execution": run_manifest.get("serial_execution") is True,
            },
        }
        materialized_cases.append(case)
        base = "-".join(filter(None, (
            _slug(case.get("task_family", "")),
            _slug(effective_lane),
            _slug(case.get("task_id", "")),
        )))
        filename_counts[base] += 1
        suffix = f"-{filename_counts[base]}" if filename_counts[base] > 1 else ""
        filename = f"{base}{suffix}.json"
        _write_json(run_root / "case_reports" / filename, case)
        for directory in _AUDIT_DIRS[1:]:
            _write_json(run_root / directory / filename, _audit_slice(case, directory))
    cases = materialized_cases
    if not cases:
        for directory in _AUDIT_DIRS:
            _write_json(run_root / directory / "stage.json", {
                "schema_version": "statebus.contest_stage_audit_placeholder.v1",
                "stage": stage,
                "applicable": False,
                "reason": "engineering gate has no benchmark cases",
            })

    _write_json(run_root / "environment.json", _environment_payload(run_root))
    _write_json(run_root / "fairness_manifest.json", _fairness_manifest(payload, stage))
    _write_json(run_root / "capability_registry.json", _generic_capability_registry())
    _write_json(run_root / "run_manifest.json", run_manifest)
    _write_json(run_root / "summary.json", payload)
    if not (run_root / "console.log").exists():
        (run_root / "console.log").write_text(
            "artifact materialization completed without a child console stream\n",
            encoding="utf-8",
        )
    if not (run_root / "pytest.log").exists():
        (run_root / "pytest.log").write_text(
            "not_applicable: this formal stage is a live benchmark, not a pytest stage\n",
            encoding="utf-8",
        )
    quality_count = sum(
        bool(
            case.get("ok")
            or case.get("quality_floor", {}).get("quality_floor_pass")
        )
        for case in cases
    )
    lines = [
        f"# Contest Evidence Closure {_STAGE_IDS[stage]}",
        "",
        f"- Stage: `{stage}`",
        f"- Exit status: `{run_manifest['exit_status']}`",
        f"- Serial execution: `{str(run_manifest['serial_execution']).lower()}`",
        f"- Materialized case reports: `{len(cases)}`",
        f"- Passing case reports: `{quality_count}`",
        f"- Raw payload hash: `{sha256_digest(payload)}`",
        "",
        "Detailed suite-native results remain under `raw/` and `runtime/`; this summary only indexes them.",
    ]
    (run_root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_checksums(run_root)


def _write_checksums(run_root: Path) -> None:
    checksum_path = run_root / "checksums.sha256"
    paths = sorted(
        path for path in run_root.rglob("*")
        if path.is_file() and path != checksum_path
    )
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(run_root).as_posix()}"
        for path in paths
    ]
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _preflight_command(run_root: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "v2.benchmark.live_runner",
        "--suite",
        "preflight",
        "--role-path-mode",
        "deterministic",
        "--embedding-mode",
        "deterministic",
        "--runtime-root",
        str(run_root / "preflight-runtime"),
    ]


def run_stage(stage: str, run_root: Path) -> int:
    if stage not in _STAGE_IDS:
        raise ValueError(f"unsupported contest stage: {stage}")
    if (run_root / "run_manifest.json").exists():
        raise FileExistsError(f"contest run root already initialized: {run_root}")
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "raw").mkdir(exist_ok=True)
    console_path = run_root / "console.log"
    console_path.touch()
    start_time = _now()
    git_sha = os.getenv("STATEBUS_CONTEST_GIT_SHA", "") or _git_value("rev-parse", "HEAD")
    dirty_env = os.getenv("STATEBUS_CONTEST_GIT_DIRTY", "")
    dirty = dirty_env == "1" if dirty_env else bool(_git_value("status", "--porcelain"))
    model_profiles = _model_profiles(run_root)
    runtime_signature = runtime_signature_payload(capture_runtime_signature())
    run_manifest: dict[str, object] = {
        "schema_version": "statebus.contest_run_manifest.v1",
        "experiment_id": _STAGE_IDS[stage],
        "suite": "contest_evidence_closure",
        "stage": stage,
        "view": "causal_core" if stage == "causal" else "long_horizon" if stage == "stress" else "",
        "lane": "L0,L1,L2,L3" if stage == "causal" else "L3" if stage == "stress" else "adaptive" if stage in {"adaptive-memory", "semantic-holdout", "adaptive"} else "engineering_gate",
        "order": list(_STAGE_IDS).index(stage) + 1,
        "git_sha": git_sha,
        "git_dirty": dirty,
        "image_id": os.getenv("STATEBUS_CONTEST_IMAGE_ID", ""),
        "image_digest": os.getenv("STATEBUS_CONTEST_IMAGE_DIGEST", ""),
        "role_model": os.getenv("STATEBUS_LOCAL_VLLM_MODEL", "qwen3-32b"),
        "role_model_config_digest": model_profiles["profile_digest"],
        "role_model_profiles": model_profiles["roles"],
        "role_model_revision_evidence": model_profiles["vllm_models"],
        "embedding_model": os.getenv(
            "STATEBUS_EMBED_MODEL_PATH", "/statebus/models/Qwen3-Embedding-0.6B"
        ),
        "embedding_model_revision": model_profiles["embedding_revision"],
        "embedding_config_sha256": model_profiles["embedding_config_sha256"],
        "capability_registry_digest": _generic_capability_registry()["registry_digest"],
        "runtime_compatibility_signature": runtime_signature["combined_digest"],
        "runtime_compatibility_signature_payload": runtime_signature,
        "validator_digest": _validator_digest(),
        "source_task_manifest_hash": _manifest_hash(stage),
        "runtime_root": str(run_root / "runtime"),
        "workspace_root": str(run_root / "workspaces"),
        "memory_root": str(run_root / "runtime"),
        "serial_execution": True,
        "start_time": start_time,
        "end_time": "",
        "exit_status": "running",
        "child_exit_codes": {},
    }
    _write_json(run_root / "run_manifest.json", run_manifest)

    blocked_reasons = []
    if stage in _LIVE_STAGES:
        for name in ("vllm_health", "cuda", "bwrap"):
            value = os.getenv(f"STATEBUS_CONTEST_{name.upper()}_STATUS", "unknown")
            if value != "ok":
                blocked_reasons.append(f"{name}:{value}")
    if blocked_reasons:
        payload = {
            "schema_version": "statebus.contest_blocked_stage.v1",
            "stage": stage,
            "status": "blocked_by_environment",
            "blocked_reasons": blocked_reasons,
            "ok": False,
        }
        run_manifest.update(
            end_time=_now(),
            exit_status="blocked_by_environment",
            blocked_reasons=blocked_reasons,
        )
        _materialize_artifact_contract(
            run_root=run_root,
            stage=stage,
            payload=payload,
            run_manifest=run_manifest,
        )
        return 2

    name, command = _stage_command(stage, run_root)
    child_log = run_root / ("pytest.log" if name == "pytest" else f"raw/{name}.log")
    return_code, elapsed = _run_child(
        name=name,
        command=command,
        log_path=child_log,
        console_path=console_path,
    )
    child_exit_codes = {name: return_code}
    payload = _parse_last_json_line(child_log)
    if stage == "adaptive" or not payload:
        payload = _latest_nested_summary(run_root)

    if stage in {"focused", "full"}:
        preflight_log = run_root / "raw/deterministic_preflight.log"
        preflight_code, preflight_elapsed = _run_child(
            name="deterministic_preflight",
            command=_preflight_command(run_root),
            log_path=preflight_log,
            console_path=console_path,
        )
        child_exit_codes["deterministic_preflight"] = preflight_code
        return_code = return_code or preflight_code
        preflight_payload = _parse_last_json_line(preflight_log)
        payload = {
            "schema_version": "statebus.contest_engineering_gate.v1",
            "stage": stage,
            "pytest_passed": child_exit_codes[name] == 0,
            "preflight": preflight_payload,
            "preflight_ok": preflight_payload.get("ok") is True,
            "child_exit_codes": child_exit_codes,
            "ok": all(code == 0 for code in child_exit_codes.values())
            and preflight_payload.get("ok") is True,
        }
        elapsed += preflight_elapsed

    stage_gates = _stage_acceptance(stage, payload)
    stage_gate_ok = bool(stage_gates) and all(stage_gates.values())
    payload = {
        **payload,
        "contest_stage_gates": stage_gates,
        "contest_stage_ok": stage_gate_ok,
    }
    child_exit_codes["acceptance_gate"] = 0 if stage_gate_ok else 1
    if return_code == 0 and not stage_gate_ok:
        return_code = 1
    if isinstance(payload.get("run_dir"), str):
        run_manifest["suite_run_root"] = payload["run_dir"]
    if isinstance(payload.get("family_memory_root"), str):
        run_manifest["memory_root"] = payload["family_memory_root"]

    run_manifest.update(
        end_time=_now(),
        exit_status="passed" if return_code == 0 else "failed",
        elapsed_seconds=round(elapsed, 3),
        child_exit_codes=child_exit_codes,
    )
    _materialize_artifact_contract(
        run_root=run_root,
        stage=stage,
        payload=payload or {
            "schema_version": "statebus.contest_child_failure.v1",
            "stage": stage,
            "ok": False,
            "reason": "child produced no JSON summary",
        },
        run_manifest=run_manifest,
    )
    return return_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one serialized contest evidence-closure stage.")
    parser.add_argument("--stage", choices=tuple(_STAGE_IDS), required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run_stage(args.stage, args.run_root))


if __name__ == "__main__":
    main()
