from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import time
import traceback
from typing import Any, Iterable, Mapping, Sequence

import httpx

from statebus.benchmark.model_assist_utility.taskpack import (
    BLOCK_SIZE,
    CASE_IDS,
    LOGIT_CASE_IDS,
    MAX_MODEL_LEN,
    PLAN_POSITIONS,
    SAMPLE_ROOT,
    Taskpack,
    build_cache_namespace,
    compile_taskpack,
    load_local_codec,
    logit_policy_order,
    plan_artifact_payload,
    prepare_taskpack,
)
from statebus.contracts import (
    CandidateSurfaceV2,
    Claim,
    ClaimSet,
    TransformProgram,
    TransformStep,
)
from statebus.integrations.llm import (
    ChatMessage,
    LLMConfig,
    LLMUsage,
    LLMResult,
    OpenAICompatibleLLMClient,
    ProviderConfig,
    RoleLLMConfig,
    _build_openai_request,
    _coerce_content_to_text,
    extract_json_object,
)
from statebus.integrations.vllm_kv.client import VllmKVClient, VllmKVClientConfig
from statebus.integrations.vllm_kv.role_client import (
    EngineLocalKVRoleClient,
    EngineLocalKVRoleClientConfig,
)
from statebus.integrations.vllm_kv.tokenizer_client import VllmTokenCodec
from statebus.runtime.logit_state import extract_exact_choice_logit_state
from statebus.runtime.prefix_identity import shared_prefix_envelope
from statebus.runtime.role_providers import (
    ExecutorCandidateReviewBinding,
    ExecutorCandidateReviewDecision,
    ProviderCandidate,
)
from statebus.runtime.vllm_metrics import (
    compute_vllm_prefix_cache_counter_delta,
    parse_vllm_prefix_cache_metrics,
)
from statebus.utils import sha256_digest
from statebus.benchmark.model_assist_utility.runtime_path import (
    UTILITY_ARTIFACT_CONTRACT,
    UTILITY_EXECUTOR_CAPABILITY,
    UTILITY_SUITE_ID,
    run_utility_runtime,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_REPORT_ROOT = REPO_ROOT / "docs" / "reports" / "contest-model-assist-utility"
MANAGER = REPO_ROOT / "scripts" / "vllm" / "manage_qwen3_32b.sh"
STANDARD_ENV = REPO_ROOT / "deploy" / "vllm.env.local"
KV_ENV_TEMPLATE = REPO_ROOT / "deploy" / "vllm.env.kv.local"
HOST_PYTHON = Path("/home/qcrs/statebus/conda-envs/statebus_host/bin/python")
MODEL = "qwen3-32b"
BASE_URL = "http://127.0.0.1:53334/v1"
TOKENIZER_BASE_URL = BASE_URL.removesuffix("/v1")
KV_BASE_URL = "http://127.0.0.1:53334"
CONTAINER_NAME = "statebus-runtime"
CONTAINER_SOURCE = "/workspace/statebus/os"
CONTAINER_PYTHON = "/home/qcrs/statebus/conda-envs/statebus_host/bin/python"
KV_TOKEN = Path.home() / "statebus/work/vllm-qwen3-32b-kv-gpu2/kv_api.token"
MIN_UTILITY_FREE_GPU_MEMORY_MIB = 4096


class UtilitySuiteError(RuntimeError):
    pass


class UtilitySuiteInterrupted(UtilitySuiteError):
    pass


class UtilitySuiteBudgetExceeded(UtilitySuiteError):
    pass


def _target_slot_identity(slot_id: str) -> tuple[str, str, str]:
    for item in PLAN_POSITIONS:
        if item.get("module") not in {"apc", "logit"}:
            continue
        if f"{item.get('case_id')}:{item.get('condition')}" == slot_id:
            return str(item["module"]), str(item["case_id"]), str(item["condition"])
    raise UtilitySuiteError("targeted_recheck_requires_one_planned_apc_or_logit_slot")


def _apc_slot_identity(slot_id: str) -> tuple[str, str]:
    module, case_id, condition = _target_slot_identity(slot_id)
    if module != "apc":
        raise UtilitySuiteError("targeted_recheck_requires_one_planned_apc_slot")
    return case_id, condition.removeprefix("apc_on_")


def _validate_failed_apc_slot(run_root: Path, slot_id: str) -> None:
    try:
        module, _case_id, _condition = _target_slot_identity(slot_id)
    except UtilitySuiteError as exc:
        raise UtilitySuiteError("targeted_recheck_requires_one_planned_apc_slot") from exc
    if module != "apc":
        raise UtilitySuiteError("targeted_recheck_requires_one_planned_apc_slot")
    _validate_failed_target_slot(run_root, slot_id, expected_module="apc")


def _validate_failed_logit_slot(run_root: Path, slot_id: str) -> None:
    try:
        module, _case_id, _condition = _target_slot_identity(slot_id)
    except UtilitySuiteError as exc:
        raise UtilitySuiteError("targeted_recheck_requires_one_planned_logit_slot") from exc
    if module != "logit":
        raise UtilitySuiteError("targeted_recheck_requires_one_planned_logit_slot")
    _validate_failed_target_slot(run_root, slot_id, expected_module="logit")


def _validate_failed_target_slot(
    run_root: Path,
    slot_id: str,
    *,
    expected_module: str | None = None,
) -> None:
    module, _case_id, _condition = _target_slot_identity(slot_id)
    if expected_module is not None and module != expected_module:
        raise UtilitySuiteError(f"targeted_recheck_requires_{expected_module}_slot")
    records_path = run_root / "records.jsonl"
    if not records_path.is_file():
        raise UtilitySuiteError("targeted_recheck_records_unavailable")
    latest: dict[str, Any] | None = None
    for line_number, line in enumerate(records_path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise UtilitySuiteError(f"targeted_recheck_records_json_invalid:{line_number}") from exc
        if record.get("slot_id") == slot_id and bool(record.get("scored", True)):
            latest = record
    if latest is None or latest.get("module") != module or latest.get("status") != "failed":
        raise UtilitySuiteError("targeted_recheck_slot_must_be_latest_scored_failure")


def _tokenizer_codec(*, timeout_s: float, http_client: Any | None = None) -> VllmTokenCodec:
    return VllmTokenCodec(
        base_url=TOKENIZER_BASE_URL,
        model=MODEL,
        timeout_s=timeout_s,
        http_client=http_client,
    )


@dataclass(frozen=True)
class PreflightResult:
    passed: bool
    reasons: tuple[str, ...]
    evidence: dict[str, Any]


def _run_capture(command: list[str], *, timeout_s: float = 30.0) -> dict[str, Any]:
    started = time.monotonic_ns()
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_s,
            check=False,
        )
        return {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "elapsed_ms": (time.monotonic_ns() - started) / 1_000_000.0,
        }
    except Exception as exc:
        return {
            "command": command,
            "returncode": None,
            "stdout": "",
            "error": f"{type(exc).__name__}:{exc}",
            "elapsed_ms": (time.monotonic_ns() - started) / 1_000_000.0,
        }


def _parse_manager_pid(status: str) -> int | None:
    match = re.search(r"pid=(\d+)", status)
    return int(match.group(1)) if match else None


def _manager_mode(status: str) -> str:
    match = re.search(r"mode=([A-Za-z0-9_.-]+)", status)
    return match.group(1) if match else ""


def _manager_identity(env_file: Path) -> dict[str, Any]:
    result = _run_capture(["env", f"STATEBUS_VLLM_ENV_FILE={env_file}", str(MANAGER), "status"])
    stdout = str(result.get("stdout", ""))
    return {
        "env_file": str(env_file),
        "status": result,
        "pid": _parse_manager_pid(stdout),
        "mode": _manager_mode(stdout),
        "healthy": "端点=健康" in stdout,
    }


def _read_env_exports(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*export\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)\s*$", line)
        if match:
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            values[match.group(1)] = value
    return values


def _archive_service_log(service_dir: Path, env_file: Path, label: str) -> dict[str, Any]:
    config = _run_capture(["env", f"STATEBUS_VLLM_ENV_FILE={env_file}", str(MANAGER), "print-config"])
    match = re.search(r"^日志文件=(.+)$", str(config.get("stdout", "")), re.MULTILINE)
    if config.get("returncode") != 0 or match is None:
        raise UtilitySuiteError(f"{label}_service_log_path_unavailable")
    source = Path(match.group(1).strip())
    evidence: dict[str, Any] = {"source": str(source), "status": "missing"}
    if source.is_file():
        service_dir.mkdir(parents=True, exist_ok=True)
        target = service_dir / f"{label}-{time.time_ns()}.service.log"
        try:
            shutil.copy2(source, target)
        except OSError as exc:
            raise UtilitySuiteError(f"{label}_service_log_archive_failed:{type(exc).__name__}") from exc
        evidence.update({"status": "archived", "archive": str(target), "bytes": target.stat().st_size})
    return evidence


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str) + "\n")


def _descendant_pids(root_pid: int | None) -> set[int]:
    if not root_pid:
        return set()
    result = _run_capture(["ps", "-eo", "pid=,ppid="], timeout_s=5)
    children: dict[int, list[int]] = {}
    for line in str(result.get("stdout", "")).splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            pid, ppid = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        children.setdefault(ppid, []).append(pid)
    found = {root_pid}
    queue = [root_pid]
    while queue:
        parent = queue.pop()
        for child in children.get(parent, []):
            if child not in found:
                found.add(child)
                queue.append(child)
    return found


def _gpu_uuid_for_index(gpu_list: str, index: str) -> str:
    for line in gpu_list.splitlines():
        match = re.match(r"GPU\s+(\d+):.*UUID:\s+([^\)]+)", line.strip())
        if match and match.group(1) == str(index):
            return match.group(2).strip()
    return ""


def _external_gpu_pids(apps_output: str, gpu_uuid: str, owned: set[int]) -> list[dict[str, Any]]:
    external: list[dict[str, Any]] = []
    for line in apps_output.splitlines():
        if not line.strip() or line.lower().startswith("gpu_uuid"):
            continue
        fields = [item.strip() for item in line.split(",")]
        if len(fields) < 4 or gpu_uuid and fields[0] != gpu_uuid:
            continue
        try:
            pid = int(fields[1])
        except ValueError:
            continue
        if pid in owned:
            continue
        external.append({"gpu_uuid": fields[0], "pid": pid, "process_name": fields[2], "used_memory": fields[3]})
    return external


def _unapproved_external_gpu_processes(
    external: Sequence[Mapping[str, Any]],
    allowed_pids: Sequence[int],
) -> list[dict[str, Any]]:
    allowed = {int(pid) for pid in allowed_pids}
    return [dict(item) for item in external if int(item.get("pid", -1)) not in allowed]


def _gpu_free_memory_mib(gpu_memory_output: str, gpu_index: str) -> int | None:
    for line in gpu_memory_output.splitlines():
        fields = [item.strip() for item in line.split(",")]
        if len(fields) < 5 or fields[0].lower() == "index" or fields[0] != str(gpu_index):
            continue
        value = re.match(r"([0-9]+)", fields[4])
        if value:
            return int(value.group(1))
    return None


def _parse_container_inspect_snapshot(output: str) -> dict[str, Any]:
    fields = output.strip().split("|", 7)
    if len(fields) != 8:
        raise ValueError("container_inspect_snapshot_invalid")
    container_id, status, image, command, network_mode, mounts, device_requests, labels = fields
    return {
        "container_id": container_id,
        "status": status,
        "image": image,
        "command": json.loads(command),
        "network_mode": network_mode,
        "mounts": json.loads(mounts),
        "device_requests": json.loads(device_requests),
        "labels": json.loads(labels),
    }


def run_preflight(*, phase: str = "all", report_root: Path | None = None, allow_external_gpu_pids: Sequence[int] = ()) -> PreflightResult:
    evidence: dict[str, Any] = {}
    reasons: list[str] = []
    gpu_list = _run_capture(["nvidia-smi", "-L"])
    gpu_memory = _run_capture(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu", "--format=csv"])
    gpu_apps = _run_capture(["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,process_name,used_memory", "--format=csv"])
    evidence["gpu_list"] = gpu_list
    evidence["gpu_memory"] = gpu_memory
    evidence["gpu_apps"] = gpu_apps
    if gpu_list.get("returncode") != 0 or gpu_memory.get("returncode") != 0 or gpu_apps.get("returncode") != 0:
        reasons.append("gpu_driver_or_process_query_failed")

    print_config = _run_capture(["env", f"STATEBUS_VLLM_ENV_FILE={STANDARD_ENV}", str(MANAGER), "print-config"])
    manager_status = _run_capture(["env", f"STATEBUS_VLLM_ENV_FILE={STANDARD_ENV}", str(MANAGER), "status"])
    standard_env = _read_env_exports(STANDARD_ENV)
    evidence["standard_print_config"] = print_config
    evidence["standard_status"] = manager_status
    evidence["standard_profile"] = {
        key: standard_env.get(key)
        for key in (
            "STATEBUS_VLLM_SERVICE_MODE",
            "STATEBUS_VLLM_MODEL_PATH",
            "STATEBUS_VLLM_SERVED_MODEL_NAME",
            "STATEBUS_VLLM_PORT",
            "STATEBUS_VLLM_CUDA_VISIBLE_DEVICES",
            "STATEBUS_VLLM_MAX_MODEL_LEN",
            "STATEBUS_VLLM_MAX_NUM_SEQS",
            "STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS",
            "STATEBUS_VLLM_ENABLE_PREFIX_CACHING",
            "STATEBUS_VLLM_MAX_LOGPROBS",
        )
    }
    manager_pid = _parse_manager_pid(str(manager_status.get("stdout", "")))
    owned_pids = _descendant_pids(manager_pid)
    evidence["manager_pid"] = manager_pid
    evidence["manager_owned_pids"] = sorted(owned_pids)
    if manager_status.get("returncode") != 0 or "mode=standard" not in str(manager_status.get("stdout", "")) or "端点=健康" not in str(manager_status.get("stdout", "")):
        reasons.append("standard_manager_not_healthy_or_not_owned")
    standard_gpu = standard_env.get("STATEBUS_VLLM_CUDA_VISIBLE_DEVICES", "2")
    free_memory_mib = _gpu_free_memory_mib(str(gpu_memory.get("stdout", "")), standard_gpu)
    evidence["standard_gpu_free_memory_mib"] = free_memory_mib
    evidence["minimum_utility_free_memory_mib"] = MIN_UTILITY_FREE_GPU_MEMORY_MIB
    if free_memory_mib is None:
        reasons.append("standard_gpu_memory_query_unavailable")
    elif free_memory_mib < MIN_UTILITY_FREE_GPU_MEMORY_MIB:
        reasons.append("standard_gpu_free_memory_below_utility_reserve")
    manager_gpu = re.search(r"物理GPU=(\d+)", str(print_config.get("stdout", "")))
    manager_gpu_index = manager_gpu.group(1) if manager_gpu else ""
    expected_standard = {
        "STATEBUS_VLLM_SERVICE_MODE": "standard",
        "STATEBUS_VLLM_MODEL_PATH": "/data/models/Qwen3-32B",
        "STATEBUS_VLLM_SERVED_MODEL_NAME": "qwen3-32b",
        "STATEBUS_VLLM_PORT": "53334",
        "STATEBUS_VLLM_MAX_MODEL_LEN": "8192",
        "STATEBUS_VLLM_MAX_NUM_SEQS": "1",
        "STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS": "8192",
        "STATEBUS_VLLM_MAX_LOGPROBS": "20",
        "STATEBUS_VLLM_ENABLE_PREFIX_CACHING": "1",
    }
    if any(standard_env.get(key) != value for key, value in expected_standard.items()):
        reasons.append("standard_profile_contract_mismatch")
    if not standard_gpu.isdigit() or manager_gpu_index != standard_gpu:
        reasons.append("standard_gpu_config_mismatch")

    listeners = _run_capture(["ss", "-ltnp"], timeout_s=5)
    evidence["port_listeners"] = listeners
    listener_lines = [line for line in str(listeners.get("stdout", "")).splitlines() if ":53334" in line]
    listener_pids = sorted({int(pid) for line in listener_lines for pid in re.findall(r"pid=(\d+)", line)})
    evidence["standard_port_listener_lines"] = listener_lines
    evidence["standard_port_listener_pids"] = listener_pids
    if listeners.get("returncode") != 0:
        reasons.append("standard_port_owner_query_failed")
    elif listener_lines and (not listener_pids or not set(listener_pids) <= owned_pids):
        reasons.append("standard_port_has_unknown_owner")

    gpu_uuid = _gpu_uuid_for_index(str(gpu_list.get("stdout", "")), standard_gpu)
    external = _external_gpu_pids(str(gpu_apps.get("stdout", "")), gpu_uuid, owned_pids)
    evidence["standard_gpu_index"] = standard_gpu
    evidence["standard_gpu_uuid"] = gpu_uuid
    if not gpu_uuid:
        reasons.append("standard_gpu_index_not_visible")
    evidence["external_gpu_processes_on_standard_gpu"] = external
    authorized_external = [item for item in external if int(item["pid"]) in {int(pid) for pid in allow_external_gpu_pids}]
    unapproved_external = _unapproved_external_gpu_processes(external, allow_external_gpu_pids)
    evidence["shared_gpu_authorization"] = {
        "requested_pids": sorted({int(pid) for pid in allow_external_gpu_pids}),
        "matched_processes": authorized_external,
        "unapproved_processes": unapproved_external,
    }

    if phase in {"all", "kv"} and KV_ENV_TEMPLATE.is_file():
        kv_print_config = _run_capture(["env", f"STATEBUS_VLLM_ENV_FILE={KV_ENV_TEMPLATE}", str(MANAGER), "print-config"])
        kv_status = _manager_identity(KV_ENV_TEMPLATE)
        kv_env = _read_env_exports(KV_ENV_TEMPLATE)
        evidence["kv_print_config"] = kv_print_config
        evidence["kv_status"] = kv_status
        evidence["kv_profile"] = {
            key: kv_env.get(key)
            for key in (
                "STATEBUS_VLLM_SERVICE_MODE",
                "STATEBUS_VLLM_MODEL_PATH",
                "STATEBUS_VLLM_SERVED_MODEL_NAME",
                "STATEBUS_VLLM_PORT",
                "STATEBUS_VLLM_CUDA_VISIBLE_DEVICES",
                "STATEBUS_VLLM_MAX_MODEL_LEN",
                "STATEBUS_VLLM_MAX_NUM_SEQS",
                "STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS",
                "STATEBUS_VLLM_ENABLE_PREFIX_CACHING",
                "STATEBUS_VLLM_MAX_LOGPROBS",
                "STATEBUS_KV_API_TOKEN_FILE",
            )
        }
        if kv_print_config.get("returncode") != 0 or kv_status["status"].get("returncode") != 0:
            reasons.append("kv_manager_status_query_failed")
        elif kv_status.get("pid") or kv_status.get("healthy"):
            reasons.append("kv_service_or_registry_already_active")
        kv_gpu = kv_env.get("STATEBUS_VLLM_CUDA_VISIBLE_DEVICES", "2")
        kv_manager_gpu = re.search(r"物理GPU=(\d+)", str(kv_print_config.get("stdout", "")))
        kv_token_text = kv_env.get("STATEBUS_KV_API_TOKEN_FILE", "").replace("${HOME}", str(Path.home())).replace("$HOME", str(Path.home()))
        expected_kv = {
            "STATEBUS_VLLM_SERVICE_MODE": "kv",
            "STATEBUS_VLLM_MODEL_PATH": "/data/models/Qwen3-32B",
            "STATEBUS_VLLM_SERVED_MODEL_NAME": "qwen3-32b",
            "STATEBUS_VLLM_PORT": "53334",
            "STATEBUS_VLLM_MAX_MODEL_LEN": "8192",
            "STATEBUS_VLLM_MAX_NUM_SEQS": "1",
            "STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS": "8192",
            "STATEBUS_VLLM_MAX_LOGPROBS": "20",
            "STATEBUS_VLLM_ENABLE_PREFIX_CACHING": "0",
            "STATEBUS_VLLM_MAX_LOGPROBS": "20",
        }
        if any(kv_env.get(key) != value for key, value in expected_kv.items()) or kv_gpu != standard_gpu or not kv_gpu.isdigit() or not kv_manager_gpu or kv_manager_gpu.group(1) != kv_gpu:
            reasons.append("kv_profile_contract_mismatch")
        if not kv_token_text or str(Path(kv_token_text).expanduser()) != str(KV_TOKEN):
            reasons.append("kv_token_path_mismatch")

    inspect_format = "{{.Id}}|{{.State.Status}}|{{.Config.Image}}|{{json .Config.Cmd}}|{{.HostConfig.NetworkMode}}|{{json .Mounts}}|{{json .HostConfig.DeviceRequests}}|{{json .Config.Labels}}"
    inspect = _run_capture(["docker", "inspect", CONTAINER_NAME, "--format", inspect_format], timeout_s=20)
    evidence["container_inspect"] = inspect
    if inspect.get("returncode") != 0:
        reasons.append("statebus_runtime_inspect_failed")
    else:
        try:
            container = _parse_container_inspect_snapshot(str(inspect.get("stdout", "")))
            evidence["container"] = container
            mounts = container["mounts"]
            source_mount = next((item for item in mounts if item.get("Destination") == "/workspace/statebus"), None)
            evidence["container_source_mount"] = source_mount
            if not source_mount or source_mount.get("Source") != "/home/qcrs/statebus":
                reasons.append("container_source_mapping_mismatch")
            evidence["container_network_mode"] = container["network_mode"]
            if evidence["container_network_mode"] != "host":
                reasons.append("container_network_mode_mismatch")
            if container["status"] != "running":
                reasons.append("statebus_runtime_not_running")
        except (TypeError, ValueError, json.JSONDecodeError):
            reasons.append("container_inspect_json_invalid")

    import_probe = "import statebus; from statebus.benchmark import contest_model_assist; from statebus.benchmark.model_assist_utility import taskpack, runtime_path, runner; print(statebus.__file__); print(contest_model_assist.__file__); print(taskpack.__file__); print(runtime_path.__file__); print(runner.__file__)"
    host_import = _run_capture([str(HOST_PYTHON), "-c", import_probe], timeout_s=20)
    container_import = _run_capture(["docker", "exec", "-w", CONTAINER_SOURCE, "-e", f"PYTHONPATH={CONTAINER_SOURCE}/src", CONTAINER_NAME, CONTAINER_PYTHON, "-c", import_probe], timeout_s=20)
    evidence["host_import"] = host_import
    evidence["container_import"] = container_import
    expected_host = str(REPO_ROOT / "src" / "statebus")
    expected_host_runner = str(REPO_ROOT / "src" / "statebus" / "benchmark" / "model_assist_utility" / "runner.py")
    if host_import.get("returncode") != 0 or expected_host not in str(host_import.get("stdout", "")) or expected_host_runner not in str(host_import.get("stdout", "")):
        reasons.append("host_source_import_mismatch")
    expected_container_runner = f"{CONTAINER_SOURCE}/src/statebus/benchmark/model_assist_utility/runner.py"
    if container_import.get("returncode") != 0 or CONTAINER_SOURCE not in str(container_import.get("stdout", "")) or expected_container_runner not in str(container_import.get("stdout", "")):
        reasons.append("container_source_import_mismatch")

    models = _run_capture(["curl", "--noproxy", "*", "--fail", "--silent", "--show-error", "--max-time", "10", "http://127.0.0.1:53334/v1/models"], timeout_s=15)
    health = _run_capture(["curl", "--noproxy", "*", "--fail", "--silent", "--show-error", "--max-time", "10", "http://127.0.0.1:53334/health"], timeout_s=15)
    evidence["models"] = models
    evidence["health"] = health
    if models.get("returncode") != 0 or '"qwen3-32b"' not in str(models.get("stdout", "")):
        reasons.append("standard_models_endpoint_failed")
    if health.get("returncode") != 0:
        reasons.append("standard_health_endpoint_failed")

    if phase in {"all", "kv"}:
        if not KV_ENV_TEMPLATE.is_file():
            reasons.append("kv_env_template_missing")
        if not KV_TOKEN.is_file() or (KV_TOKEN.stat().st_mode & 0o077):
            reasons.append("kv_token_missing_or_permissions_invalid")
        evidence["kv_token_path"] = str(KV_TOKEN)
        evidence["kv_token_mode"] = oct(KV_TOKEN.stat().st_mode & 0o777) if KV_TOKEN.exists() else None
        container_token = "/workspace/statebus/" + str(KV_TOKEN).removeprefix("/home/qcrs/statebus/")
        container_token_mode = _run_capture(["docker", "exec", CONTAINER_NAME, "stat", "-c", "%a", container_token], timeout_s=10)
        evidence["container_kv_token_mode"] = container_token_mode
        if container_token_mode.get("returncode") != 0 or str(container_token_mode.get("stdout", "")).strip() != "600":
            reasons.append("container_kv_token_mapping_or_permissions_invalid")
    return PreflightResult(not reasons, tuple(dict.fromkeys(reasons)), evidence)


def _llm_client(
    *,
    timeout_s: float = 480.0,
    executor_max_tokens: int = 512,
    summarizer_max_tokens: int = 384,
) -> OpenAICompatibleLLMClient:
    roles = {
        "planner": RoleLLMConfig(provider="default", model=MODEL, json_output=True, temperature=0.0, max_tokens=64, request_kwargs={"seed": 7}),
        "retriever": RoleLLMConfig(provider="default", model=MODEL, json_output=True, temperature=0.0, max_tokens=64, request_kwargs={"seed": 7}),
        "executor": RoleLLMConfig(provider="default", model=MODEL, json_output=True, temperature=0.0, max_tokens=executor_max_tokens, max_context_tokens=MAX_MODEL_LEN, max_context_safety_margin_tokens=64, request_kwargs={"seed": 7}, extra_body={"chat_template_kwargs": {"enable_thinking": False}}),
        "summarizer": RoleLLMConfig(provider="default", model=MODEL, json_output=True, temperature=0.0, max_tokens=summarizer_max_tokens, max_context_tokens=MAX_MODEL_LEN, max_context_safety_margin_tokens=64, request_kwargs={"seed": 7}, extra_body={"chat_template_kwargs": {"enable_thinking": False}}),
    }
    config = LLMConfig(mode="local_vllm", source="model_assist_utility", providers={"default": ProviderConfig(base_url=BASE_URL, api_key="EMPTY", timeout_s=timeout_s, request_max_attempts=1)}, roles=roles)
    return OpenAICompatibleLLMClient(config)


def _complete(client: OpenAICompatibleLLMClient, messages: list[ChatMessage], *, purpose: str, schema: dict[str, Any]) -> tuple[LLMResult | None, dict[str, Any]]:
    started = time.perf_counter_ns()
    try:
        result = asyncio.run(client.complete(messages, purpose=purpose, temperature=0.0, response_schema=schema))
        return result, {"status": "response", "request_wall_ms": (time.perf_counter_ns() - started) / 1_000_000.0, "usage": {"prompt_tokens": result.usage.prompt_tokens, "completion_tokens": result.usage.completion_tokens, "total_tokens": result.usage.total_tokens}, "finish_reason": result.finish_reason, "text": result.text}
    except Exception as exc:
        return None, {"status": "error", "error_type": type(exc).__name__, "error": str(exc), "request_wall_ms": (time.perf_counter_ns() - started) / 1_000_000.0}


def _complete_streaming(
    client: OpenAICompatibleLLMClient,
    messages: list[ChatMessage],
    *,
    purpose: str,
    schema: dict[str, Any],
) -> tuple[LLMResult | None, dict[str, Any]]:
    async def invoke() -> tuple[LLMResult, float | None, int]:
        role_config = client.config.role_config(purpose)
        provider_name = role_config.provider
        request = _build_openai_request(role_config, messages, temperature=0.0)
        simple_fact_report = isinstance(schema, dict) and schema.get("title") == "statebus_simple_fact_report_v1"
        if (
            client.config.mode == "local_vllm"
            and isinstance(request.get("response_format"), dict)
            and request["response_format"].get("type") == "json_object"
            and (purpose != "summarizer" or simple_fact_report)
        ):
            request = {
                **request,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "role_object", "strict": True, "schema": schema},
                },
            }
        elif (
            client.config.mode == "local_vllm"
            and purpose == "summarizer"
            and isinstance(request.get("response_format"), dict)
            and request["response_format"].get("type") == "json_object"
            and not simple_fact_report
        ):
            request = {**request, "response_format": {"type": "json_object"}}
        if client.config.mode == "local_vllm":
            extra_body = dict(request.get("extra_body") or {})
            template_kwargs = dict(extra_body.get("chat_template_kwargs") or {})
            template_kwargs.setdefault("enable_thinking", False)
            extra_body["chat_template_kwargs"] = template_kwargs
            request = {**request, "extra_body": extra_body}
        if client.config.mode == "local_vllm" and purpose == "executor":
            request = {**request, "logprobs": True, "top_logprobs": 20}
        request = {**request, "stream": True, "stream_options": {"include_usage": True}}

        provider_client = client._build_provider_client(provider_name)
        started_ns = time.perf_counter_ns()
        ttft_ms: float | None = None
        content: list[str] = []
        top_logprobs: list[Any] = []
        usage: Any = None
        finish_reason: str | None = None
        token_events = 0
        try:
            stream = await provider_client.chat.completions.create(**request)
            async for chunk in stream:
                usage = getattr(chunk, "usage", None) or usage
                for choice in getattr(chunk, "choices", ()) or ():
                    delta = getattr(choice, "delta", None)
                    text = _coerce_content_to_text(getattr(delta, "content", None)) if delta is not None else ""
                    if text:
                        if ttft_ms is None:
                            ttft_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
                        token_events += 1
                        content.append(text)
                    logprob_content = getattr(getattr(delta, "logprobs", None), "content", None) if delta is not None else None
                    if logprob_content:
                        top_logprobs.extend(logprob_content)
                    if getattr(choice, "finish_reason", None):
                        finish_reason = str(choice.finish_reason)
        finally:
            await provider_client.close()
        result = LLMResult(
            text="".join(content).strip(),
            model=role_config.model,
            usage=LLMUsage(
                prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
            ),
            top_logprobs=top_logprobs or None,
            finish_reason=finish_reason,
        )
        return result, ttft_ms, token_events

    started = time.perf_counter_ns()
    try:
        result, ttft_ms, token_events = asyncio.run(invoke())
        return result, {
            "status": "response",
            "request_wall_ms": (time.perf_counter_ns() - started) / 1_000_000.0,
            "ttft_ms": ttft_ms,
            "token_event_count": token_events,
            "usage": {
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
                "total_tokens": result.usage.total_tokens,
            },
            "finish_reason": result.finish_reason,
            "text": result.text,
        }
    except Exception as exc:
        return None, {
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "request_wall_ms": (time.perf_counter_ns() - started) / 1_000_000.0,
            "ttft_ms": None,
            "token_event_count": 0,
        }


def _json_schema(properties: dict[str, Any], required: Iterable[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required or properties), "additionalProperties": False}


def _validate_report(case: Any, payload: Mapping[str, Any] | None) -> tuple[bool, list[str]]:
    if not isinstance(payload, Mapping):
        return False, ["report_not_object"]
    errors: list[str] = []
    for key, expected in case.gold.items():
        if key not in payload:
            errors.append(f"missing:{key}")
            continue
        actual = payload[key]
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            try:
                if abs(float(actual) - float(expected)) > 0.0051:
                    errors.append(f"mismatch:{key}")
            except (TypeError, ValueError):
                errors.append(f"non_numeric:{key}")
        elif key == "rule_id":
            if str(actual) != str(expected):
                errors.append(f"mismatch:{key}")
    citations = payload.get("citations")
    if not isinstance(citations, list) or not all(isinstance(item, str) for item in citations):
        errors.append("citations_missing")
        return False, errors
    if not 2 <= len(citations) <= 3 or len(set(citations)) != len(citations):
        errors.append("citations_count_or_uniqueness_invalid")
    allowed_locators = {
        str(row.get("source_locator", "")) for row in case.source_rows
    } | {
        str(rule.get("source_locator", "")) for rule in case.rules
    }
    if any(locator not in allowed_locators for locator in citations):
        errors.append("citation_not_in_authorized_dossier")
    if not any(locator.startswith("ledger/") for locator in citations):
        errors.append("ledger_citation_missing")
    if not any(locator.startswith("rules/") for locator in citations):
        errors.append("rule_citation_missing")
    return not errors, errors


def _report_schema(case: Any) -> dict[str, Any]:
    if "ORION" in case.case_id:
        props = {key: {"type": "number"} for key in ("q1_fee_usd", "q3_fee_usd", "fee_delta_usd", "q1_exception_count", "q3_exception_count", "q1_covered_record_count", "q3_covered_record_count", "covered_record_count")}
    else:
        props = {key: {"type": "number"} for key in ("q1_on_time", "q1_committed", "q1_rate_pct", "q3_on_time", "q3_committed", "q3_rate_pct", "delta_pp", "q1_covered_record_count", "q3_covered_record_count", "covered_record_count")}
    props.update({"rule_id": {"type": "string"}, "citations": {"type": "array", "items": {"type": "string"}}})
    return _json_schema(props)


def _executor_schema() -> dict[str, Any]:
    operation_schema = {
        "type": "object",
        "properties": {
            "op": {"type": "string"},
            "arguments": {"type": "object", "additionalProperties": True},
        },
        "required": ["op", "arguments"],
        "additionalProperties": False,
    }
    return _json_schema({
        "operations": {"type": "array", "items": operation_schema},
        "source_locators": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
    })


def _runtime_input_schema(rows: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    schema: dict[str, str] = {}
    for row in rows:
        for key, value in row.items():
            if isinstance(value, bool):
                kind = "boolean"
            elif isinstance(value, int):
                kind = "integer"
            elif isinstance(value, float):
                kind = "number"
            else:
                kind = "string"
            prior = schema.get(str(key))
            if prior is not None and prior != kind and {prior, kind} != {"integer", "number"}:
                raise ValueError(f"utility_input_schema_conflict:{key}")
            schema[str(key)] = "number" if {prior, kind} == {"integer", "number"} else kind
    return schema


def _runtime_output_schema(case: Any) -> dict[str, str]:
    if "ORION" in case.case_id:
        return {
            "quarter": "string",
            "fee_usd": "number",
            "exception_count": "number",
            "record_count": "number",
            "fee_per_record": "number",
        }
    return {
        "quarter": "string",
        "on_time": "number",
        "committed": "number",
        "record_count": "number",
        "rate_pct": "number",
    }


def _apc_calibration_gate_ready(results: Sequence[Mapping[str, Any]]) -> bool:
    return len(results) == 2 and all(bool(item.get("gate_ready")) for item in results)


def _chat_messages_for_codec(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": item.role, "content": item.content} for item in messages]


def _count_prompt_tokens(codec: Any, messages: Sequence[ChatMessage]) -> int:
    return len(_encode_prompt_tokens(codec, messages))


def _encode_prompt_tokens(codec: Any, messages: Sequence[ChatMessage]) -> tuple[int, ...]:
    return tuple(codec.encode_messages(
        _chat_messages_for_codec(messages),
        add_generation_prompt=True,
        chat_template_kwargs={"enable_thinking": False},
    ))


def _parse_transform_program_payload(
    *,
    raw_text: str,
    attempt_id: str,
    output_contract_version: str,
    evidence_ref: str,
    allowed_locators: Mapping[str, str],
    program_id: str,
) -> ProviderCandidate:
    try:
        payload = extract_json_object(raw_text)
        operations = payload.get("operations")
        source_locators = payload.get("source_locators")
        if not isinstance(operations, list) or not operations:
            raise ValueError("executor_operations_missing")
        if not isinstance(source_locators, list) or not source_locators or not all(isinstance(item, str) for item in source_locators):
            raise ValueError("executor_source_locators_missing")
        if len(source_locators) > 4:
            raise ValueError("executor_source_locator_limit_exceeded")
        if any(item not in allowed_locators for item in source_locators):
            raise ValueError("executor_source_locator_out_of_scope")
        steps: list[TransformStep] = []
        for item in operations:
            if not isinstance(item, Mapping) or not str(item.get("op", "")).strip():
                raise ValueError("executor_operation_invalid")
            arguments = item.get("arguments")
            if not isinstance(arguments, Mapping) or not arguments:
                raise ValueError("executor_operation_arguments_missing")
            steps.append(TransformStep(op=str(item["op"]), arguments=dict(arguments)))
        program = TransformProgram(
            program_id=program_id or f"utility-program-{attempt_id}",
            input_artifact_refs=(evidence_ref,),
            operations=tuple(steps),
            output_contract_version=output_contract_version,
        )
        return ProviderCandidate(
            True,
            "executor_program",
            program,
            diagnostics=(("candidate_source", "local_vllm_transform_program"),),
        )
    except (TypeError, ValueError, KeyError, StopIteration, json.JSONDecodeError) as exc:
        return ProviderCandidate(False, "failure", error_code=f"executor_candidate_invalid:{type(exc).__name__}")


def _parse_transform_program(*, request: Any, raw_text: str) -> ProviderCandidate:
    evidence_payload = next(
        item["payload"] for item in request.role_context.verified_input_payloads
        if item.get("kind") == "canonical_evidence_pack"
    )
    evidence_ref = next(
        str(item["ref_id"])
        for item in request.role_context.verified_input_payloads
        if item.get("kind") == "canonical_evidence_pack"
    )
    attempt_id = request.bound_grant.grant.attempt_id
    return _parse_transform_program_payload(
        raw_text=raw_text,
        attempt_id=attempt_id,
        output_contract_version=request.step.output_contract_version,
        evidence_ref=evidence_ref,
        allowed_locators=_evidence_locator_index(evidence_payload),
        program_id=f"utility-program-{attempt_id}",
    )


def _number_fields_from_artifact(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    values: dict[str, float] = {}
    for index, row in enumerate(rows):
        for key, value in row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.setdefault(f"artifact_{index}_{key}", float(value))
    return values


def _evidence_locator_index(evidence_payload: Mapping[str, Any]) -> dict[str, str]:
    locators: dict[str, str] = {}
    for bucket in ("hard_facts", "structured_evidence", "semantic_contexts", "lexical_hints", "conflicts"):
        for item in evidence_payload.get(bucket, ()):
            if not isinstance(item, Mapping):
                continue
            metadata = item.get("metadata", {})
            row = metadata.get("structured_row", {}) if isinstance(metadata, Mapping) else {}
            fact = metadata.get("utility_fact", {}) if isinstance(metadata, Mapping) else {}
            source = row or fact
            locator = str(source.get("source_locator", "")) if isinstance(source, Mapping) else ""
            if locator:
                locators[locator] = str(item.get("item_id", ""))
    return locators


def _claim_candidate_from_report(*, request: Any, raw_text: str) -> tuple[ProviderCandidate, dict[str, Any] | None]:
    try:
        report = extract_json_object(raw_text)
        citations = report.get("citations")
        if not isinstance(citations, list) or not all(isinstance(item, str) for item in citations):
            raise ValueError("summarizer_citations_invalid")
        evidence_payload = next(
            item["payload"] for item in request.role_context.verified_input_payloads
            if item.get("kind") == "canonical_evidence_pack"
        )
        artifact_input = next(
            item for item in request.role_context.verified_input_payloads
            if item.get("kind") == "execution_artifact"
        )
        locator_index = _evidence_locator_index(evidence_payload)
        evidence_ids = tuple(dict.fromkeys(
            locator_index[item] for item in citations if item in locator_index
        ))
        artifact_rows = artifact_input["payload"].get("rows", ())
        claim = Claim(
            claim_id=f"utility-claim-{request.bound_grant.grant.attempt_id}",
            claim_text=json.dumps(report, ensure_ascii=False, sort_keys=True),
            claim_type="fact",
            supporting_evidence_item_ids=evidence_ids,
            supporting_artifact_ref_ids=(str(artifact_input["ref_id"]),),
            citation_locators=tuple(dict.fromkeys(str(item) for item in citations)),
            numeric_fields=_number_fields_from_artifact(artifact_rows),
        )
        return ProviderCandidate(
            True,
            "summary_claim_set",
            ClaimSet(
                claim_set_id=f"utility-claim-set-{request.bound_grant.grant.attempt_id}",
                task_id=request.envelope.task_id,
                claims=(claim,),
            ),
        ), report
    except (TypeError, ValueError, KeyError, StopIteration, json.JSONDecodeError) as exc:
        return ProviderCandidate(False, "failure", error_code=f"summarizer_candidate_invalid:{type(exc).__name__}"), None


def _runtime_evidence(result: Any) -> dict[str, Any]:
    runtime = result.runtime
    context = result.context
    attempts = [
        item.canonical_payload() if callable(getattr(item, "canonical_payload", None)) else repr(item)
        for item in runtime.session.attempt_records
    ]
    artifacts = [
        {
            "artifact_id": stored.artifact.artifact_id,
            "step_id": stored.artifact.step_id,
            "blob_hash": stored.artifact.blob_hash,
            "verification_state": stored.artifact.verification_state.value,
            "row_count": len(stored.rows),
        }
        for stored in context.artifacts.values()
    ]
    return {
        "execution_path": "RuntimeDriver.run_mode(adaptive_bounded)->AdaptiveMainlineRunner->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher",
        "runtime_completed": runtime.completed,
        "plan_replaced": runtime.plan_replaced,
        "approved_plan_hash": runtime.approved_plan_hash,
        "attempts": attempts,
        "artifacts": artifacts,
        "artifact_verification_receipt_hashes": sorted(
            receipt.receipt_hash for receipt in context.artifact_verification_receipts.values()
        ),
        "claim_validation_reports": list(context.claim_validation_reports.values()),
        "candidate_review_records": list(context.executor_candidate_review_records),
        "dispatches": [
            {
                "step_id": item.step_id,
                "attempt_id": item.attempt_id,
                "state": item.state,
                "error_code": item.error_code,
            }
            for item in runtime.dispatches
        ],
    }


def _runtime_abstained(runtime_action: str, runtime_payload: Mapping[str, Any]) -> bool:
    dispatches = runtime_payload.get("dispatches", [])
    last_error = next(
        (str(item.get("error_code", "")) for item in reversed(dispatches) if item.get("error_code")),
        "",
    )
    return (
        runtime_action == "abstain"
        and last_error == "need_more_evidence"
        and not runtime_payload.get("artifacts")
    )


def _serialize_top_logprobs(items: Sequence[Any] | None) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for item in items or ():
        raw_bytes = getattr(item, "bytes", None)
        if isinstance(raw_bytes, bytes):
            token_bytes: list[int] | None = list(raw_bytes)
        elif isinstance(raw_bytes, Sequence) and not isinstance(raw_bytes, str):
            token_bytes = [int(value) for value in raw_bytes]
        else:
            token_bytes = None
        alternatives = []
        for choice in getattr(item, "top_logprobs", None) or ():
            choice_bytes = getattr(choice, "bytes", None)
            if isinstance(choice_bytes, bytes):
                choice_bytes = list(choice_bytes)
            elif isinstance(choice_bytes, Sequence) and not isinstance(choice_bytes, str):
                choice_bytes = [int(value) for value in choice_bytes]
            else:
                choice_bytes = None
            alternatives.append({
                "token": str(getattr(choice, "token", "")),
                "bytes": choice_bytes,
                "logprob": getattr(choice, "logprob", None),
            })
        serialized.append({
            "token": str(getattr(item, "token", "")),
            "bytes": token_bytes,
            "logprob": getattr(item, "logprob", None),
            "top_logprobs": alternatives,
        })
    return serialized


@lru_cache(maxsize=1)
def _local_choice_tokenizer() -> Any:
    return load_local_codec().tokenizer


def _decoded_choice_token_bytes(token: Any, tokenizer: Any) -> bytes:
    if not isinstance(token, str):
        raise ValueError("choice_token_text_missing")
    token_id = tokenizer.get_vocab().get(token)
    if token_id is None or tokenizer.convert_ids_to_tokens(token_id) != token:
        raise ValueError("choice_token_not_in_local_vocab")
    decoded = tokenizer.decode(
        [int(token_id)],
        clean_up_tokenization_spaces=False,
        skip_special_tokens=True,
    )
    if not isinstance(decoded, str):
        raise ValueError("choice_token_decode_invalid")
    return decoded.encode("utf-8")


def _normalize_choice_logprobs_with_tokenizer(
    top_logprobs: Sequence[object],
    *,
    completion_text: str,
    tokenizer: Any,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    decoded_parts: list[bytes] = []
    try:
        for item in top_logprobs:
            payload = dict(item) if isinstance(item, Mapping) else _serialize_top_logprobs([item])[0]
            token_text = payload.get("token")
            token_bytes = _decoded_choice_token_bytes(token_text, tokenizer)
            payload["bytes"] = list(token_bytes)
            decoded_parts.append(token_bytes)
            alternatives = payload.get("top_logprobs") or ()
            normalized_alternatives = []
            for alternative in alternatives:
                alternative_payload = (
                    dict(alternative)
                    if isinstance(alternative, Mapping)
                    else _serialize_top_logprobs([alternative])[0]
                )
                alternative_payload["bytes"] = list(
                    _decoded_choice_token_bytes(alternative_payload.get("token"), tokenizer)
                )
                normalized_alternatives.append(alternative_payload)
            payload["top_logprobs"] = normalized_alternatives
            normalized.append(payload)
        decoded_completion = b"".join(decoded_parts).decode("utf-8")
    except (UnicodeDecodeError, TypeError, ValueError, KeyError) as exc:
        return None, {
            "source": "local_tokenizer_token_decode",
            "status": "unavailable",
            "reason": f"token_decode_failed:{type(exc).__name__}:{exc}",
        }

    if decoded_completion != completion_text and decoded_completion.strip() != completion_text:
        return None, {
            "source": "local_tokenizer_token_decode",
            "status": "unavailable",
            "reason": "local_tokenizer_completion_mismatch",
            "decoded_completion_digest": sha256_digest(decoded_completion),
            "completion_digest": sha256_digest(completion_text),
        }
    return normalized, {
        "source": "local_tokenizer_token_decode",
        "status": "reconstructed_exactly",
        "tokenizer_class": type(tokenizer).__name__,
        "tokenizer_name_or_path": str(getattr(tokenizer, "name_or_path", "")),
        "token_count": len(normalized),
        "decoded_completion_digest": sha256_digest(decoded_completion),
        "completion_digest": sha256_digest(completion_text),
        "text_match": True,
    }


def _extract_utility_choice_logit_state(
    *,
    completion_text: str,
    top_logprobs: Sequence[object] | None,
    candidate_surface: CandidateSurfaceV2,
    request_id: str,
    attempt_id: str,
    tokenizer: Any | None = None,
) -> tuple[Any, dict[str, Any]]:
    extraction = extract_exact_choice_logit_state(
        completion_text=completion_text,
        top_logprobs=top_logprobs,
        candidate_surface=candidate_surface,
        request_id=request_id,
        attempt_id=attempt_id,
    )
    reason = str(extraction.receipt.unavailable_reason or "")
    if extraction.available or reason != "completion_token_bytes_mismatch":
        return extraction, {
            "source": "provider_bytes",
            "status": "exact" if extraction.available else "unavailable",
            "reason": reason,
        }

    try:
        local_tokenizer = tokenizer if tokenizer is not None else _local_choice_tokenizer()
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return extraction, {
            "source": "local_tokenizer_token_decode",
            "status": "unavailable",
            "reason": f"tokenizer_load_failed:{type(exc).__name__}:{exc}",
        }
    normalized, alignment = _normalize_choice_logprobs_with_tokenizer(
        top_logprobs or (),
        completion_text=completion_text,
        tokenizer=local_tokenizer,
    )
    if normalized is None:
        return extraction, alignment | {"provider_bytes_reason": reason}
    extraction = extract_exact_choice_logit_state(
        completion_text=completion_text,
        top_logprobs=normalized,
        candidate_surface=candidate_surface,
        request_id=request_id,
        attempt_id=attempt_id,
    )
    return extraction, alignment | {
        "provider_bytes_reason": reason,
        "extraction_available": bool(extraction.available),
        "extraction_reason": str(extraction.receipt.unavailable_reason or ""),
    }


def _logit_extraction_payload(extraction: Any, surface: CandidateSurfaceV2) -> dict[str, Any]:
    probabilities = tuple(extraction.candidate_probabilities)
    selected_index = next(
        (index for index, alias in enumerate(surface.aliases) if alias == extraction.selected_alias),
        None,
    )
    probability_width_ok = len(probabilities) == len(surface.aliases)
    available = bool(extraction.available and probability_width_ok and selected_index is not None)
    unavailable_reason = extraction.receipt.unavailable_reason
    if extraction.available and not probability_width_ok:
        unavailable_reason = "candidate_probability_width_mismatch"
    elif extraction.available and selected_index is None:
        unavailable_reason = "selected_alias_outside_surface"
    payload = {
        "available": available,
        "selected_alias": extraction.selected_alias,
        "selected_candidate_id": extraction.selected_candidate_id,
        "candidate_probabilities": {
            alias: probability
            for alias, probability in zip(surface.aliases, probabilities)
        },
        "candidate_probabilities_raw": list(probabilities),
        "other_mass": extraction.other_mass,
        "top_margin": extraction.top_margin if probabilities else None,
        "selected_is_top1": (
            available
            and bool(probabilities)
            and probabilities[selected_index] >= max(probabilities)
        ),
        "unavailable_reason": unavailable_reason,
        "decision_token_position": extraction.receipt.decision_token_position,
        "sequence_length": extraction.receipt.sequence_length,
        "top_k": extraction.receipt.top_k,
    }
    return payload


def _verify_standard_endpoints() -> dict[str, Any]:
    manager = _manager_identity(STANDARD_ENV)
    models = _run_capture(["curl", "--noproxy", "*", "--fail", "--silent", "--show-error", "--max-time", "10", "http://127.0.0.1:53334/v1/models"], timeout_s=15)
    health = _run_capture(["curl", "--noproxy", "*", "--fail", "--silent", "--show-error", "--max-time", "10", "http://127.0.0.1:53334/health"], timeout_s=15)
    evidence: dict[str, Any] = {"manager": manager, "models": models, "health": health}
    evidence["model_present"] = models.get("returncode") == 0 and '"qwen3-32b"' in str(models.get("stdout", ""))
    if manager.get("mode") != "standard" or not manager.get("pid") or not manager.get("healthy") or not evidence["model_present"] or health.get("returncode") != 0:
        evidence.update({"passed": False, "reason": "standard_manager_health_or_model_failed"})
        return evidence

    codec = _tokenizer_codec(timeout_s=30.0)
    messages = [ChatMessage("user", "Return one of the authorized restoration choices.")]
    try:
        tokens = _encode_prompt_tokens(codec, messages)
        evidence["tokenize"] = {"status": "passed" if tokens else "failed", "token_count": len(tokens), "token_digest": sha256_digest(list(tokens))}
    except Exception as exc:
        evidence["tokenize"] = {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)}
        evidence.update({"passed": False, "reason": "standard_tokenize_failed"})
        return evidence
    finally:
        codec.close()
    if not tokens:
        evidence.update({"passed": False, "reason": "standard_tokenize_empty"})
        return evidence

    surface = CandidateSurfaceV2.from_candidate_ids(("restore_choice_a", "restore_choice_b"))
    schema = _json_schema({"choice_code": {"type": "string", "enum": list(surface.aliases)}})
    client = _llm_client(timeout_s=60.0, executor_max_tokens=32, summarizer_max_tokens=32)
    try:
        result = asyncio.run(client.complete(
            messages,
            purpose="executor",
            temperature=0.0,
            response_schema=schema,
        ))
        raw_top_logprobs = _serialize_top_logprobs(result.top_logprobs)
        has_raw_logprobs = any(
            isinstance(item.get("logprob"), (int, float))
            and math.isfinite(float(item["logprob"]))
            and bool(item.get("top_logprobs"))
            for item in raw_top_logprobs
        )
        evidence["logprobs"] = {
            "status": "passed" if has_raw_logprobs else "failed",
            "finish_reason": result.finish_reason,
            "usage": {
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
                "total_tokens": result.usage.total_tokens,
            },
            "token_count": len(raw_top_logprobs),
            "raw_top_logprobs": raw_top_logprobs,
        }
    except Exception as exc:
        evidence["logprobs"] = {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)}
    evidence["passed"] = bool(evidence.get("logprobs", {}).get("status") == "passed")
    if not evidence["passed"]:
        evidence["reason"] = "standard_minimal_logprobs_failed"
    return evidence


def _validate_logit_report(
    payload: Mapping[str, Any] | None,
    *,
    selected_candidate: str,
    candidate_rows: Sequence[Mapping[str, Any]],
) -> tuple[bool, list[str]]:
    if not isinstance(payload, Mapping):
        return False, ["report_not_object"]
    errors: list[str] = []
    if payload.get("decision") != "select":
        errors.append("decision_not_select")
    if payload.get("evidence_id") != selected_candidate:
        errors.append("selected_evidence_mismatch")
    citations = payload.get("citations")
    if not isinstance(citations, list) or not all(isinstance(item, str) for item in citations):
        return False, [*errors, "citations_missing"]
    allowed = {str(row.get("source_locator", "")) for row in candidate_rows}
    selected_locator = next(
        (str(row.get("source_locator", "")) for row in candidate_rows if row.get("candidate_id") == selected_candidate),
        "",
    )
    if not 1 <= len(citations) <= 3 or len(set(citations)) != len(citations):
        errors.append("citations_count_or_uniqueness_invalid")
    if any(locator not in allowed for locator in citations):
        errors.append("citation_not_in_authorized_candidates")
    if not selected_locator or selected_locator not in citations:
        errors.append("selected_source_citation_missing")
    if not isinstance(payload.get("summary"), str) or not payload.get("summary", "").strip():
        errors.append("summary_missing")
    return not errors, errors


def _metrics_snapshot(run_root: Path, name: str) -> Any:
    path = run_root / "service" / f"{name}.prom"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        response = httpx.get("http://127.0.0.1:53334/metrics", timeout=10.0, trust_env=False)
        response.raise_for_status()
        path.write_text(response.text, encoding="utf-8")
        return parse_vllm_prefix_cache_metrics(response.text)
    except Exception as exc:
        (run_root / "service" / f"{name}.error").write_text(f"{type(exc).__name__}:{exc}\n", encoding="utf-8")
        return None


def _apc_delta(before: Any, after: Any, request_count: int) -> dict[str, Any]:
    if before is None or after is None:
        return {"status": "unavailable", "reason": "metrics_request_failed"}
    request_delta = None
    if before.request_success_total is not None and after.request_success_total is not None:
        request_delta = after.request_success_total - before.request_success_total
    pollution = request_delta is None or request_delta != request_count
    delta = compute_vllm_prefix_cache_counter_delta(
        before,
        after,
        exclusive_interval=not pollution,
        pollution_detected=pollution,
        request_count=request_count,
        expected_engine_instance_id=before.engine_instance_id,
        expected_cache_epoch=before.cache_epoch,
        window_scope="task",
    )
    return delta.canonical_payload()


def _active_rule_id(case: Any) -> str:
    applicable = [
        rule for rule in case.rules
        if str(rule.get("effective_from", "")) <= "2026-01-01"
        and str(rule.get("effective_to", "")) >= "2026-09-30"
        and rule.get("eligible_scope") == "approved_sample_cohort"
    ]
    if len(applicable) != 1 or not applicable[0].get("rule_id"):
        raise ValueError(f"utility_active_rule_ambiguous:{case.case_id}")
    return str(applicable[0]["rule_id"])


def _executor_source_locators(case: Any) -> tuple[str, ...]:
    """Return exact active-rule and early/middle/late ledger locators."""
    active_rule_id = _active_rule_id(case)
    source_rows = tuple(getattr(case, "source_rows", ()))
    active_rule_locator = next(
        (
            str(rule.get("source_locator", ""))
            for rule in case.rules
            if str(rule.get("rule_id", "")) == active_rule_id
            and str(rule.get("source_locator", ""))
        ),
        "",
    )
    ledger_locators: list[str] = []
    for index in (0, len(source_rows) // 2, len(source_rows) - 1):
        if not source_rows:
            break
        locator = str(source_rows[index].get("source_locator", ""))
        if locator and locator not in ledger_locators:
            ledger_locators.append(locator)
    return tuple(item for item in (active_rule_locator, *ledger_locators) if item)


def _transform_contract(case: Any) -> str:
    rule_id = _active_rule_id(case)
    filters = (
        "Filter status == APPROVED, scope == approved_sample_cohort, "
        f"effective_rule_id == {rule_id}, and quarter in 2026Q1/2026Q3. "
        "The effective_rule_id value must be the exact active rule ID above, not a historical rule. "
    )
    filter_examples = (
        '{"op":"filter_eq","arguments":{"column":"status","value":"APPROVED"}}, '
        '{"op":"filter_eq","arguments":{"column":"scope","value":"approved_sample_cohort"}}, '
        f'{{"op":"filter_eq","arguments":{{"column":"effective_rule_id","value":"{rule_id}"}}}}, '
        '{"op":"filter_in","arguments":{"column":"quarter","values":["2026Q1","2026Q3"]}}. '
    )
    if "ORION" in case.case_id:
        return (
            filters + filter_examples
            + "Then use aggregate_grouped with arguments group_fields, value_fields, functions, outputs: "
            '{"group_fields":["quarter"],"value_fields":["expedited_fee_usd","exception_count","expedited_fee_usd"],'
            '"functions":["sum","sum","count"],"outputs":["fee_usd","exception_count","record_count"]}. '
            'Then derive fee_per_record with derive_safe calculations [["fee_per_record","ratio","fee_usd","record_count",1,2]]. '
            'Finish with select columns ["quarter","fee_usd","exception_count","record_count","fee_per_record"].'
        )
    return (
        filters + filter_examples
        + "Then use aggregate_grouped with arguments group_fields, value_fields, functions, outputs: "
        '{"group_fields":["quarter"],"value_fields":["on_time_orders","committed_orders","on_time_orders"],'
        '"functions":["sum","sum","count"],"outputs":["on_time","committed","record_count"]}. '
        'Then derive rate_pct with derive_safe calculations [["rate_pct","ratio","on_time","committed",100,4]]. '
        'Finish with select columns ["quarter","on_time","committed","record_count","rate_pct"].'
    )


def _executor_repair_factory(
    *,
    case: Any,
    layout: str,
    namespace: str,
    client: OpenAICompatibleLLMClient,
    codec: VllmTokenCodec,
    observations: list[dict[str, Any]],
):
    """Build the Runtime's single bounded DSL repair callback.

    The ordinary delegate is intentional: a KV producer handle remains
    available for the Summarizer's one continuation after repair.
    """
    allowed_locators = {
        str(item.get("source_locator", ""))
        for item in (*case.source_rows, *case.rules)
        if item.get("source_locator")
    }

    def repair(
        step: Any,
        grant: Any,
        input_ref_id: str,
        _rows: tuple[dict[str, Any], ...],
        validation_errors: tuple[str, ...],
        *,
        previous_program: TransformProgram,
        repair_stage: str,
        input_tables: Mapping[str, Any] | None = None,
    ) -> TransformProgram:
        attempt_id = str(grant.attempt_id)
        messages = _executor_messages(case, layout, attempt_id, namespace=namespace)
        repair_context = {
            "runtime_stage": repair_stage,
            "runtime_validation_errors": list(validation_errors),
            "previous_program": previous_program.canonical_payload(),
            "authorized_input_ref": input_ref_id,
            "authorized_input_tables": sorted(input_tables or {}),
        }
        messages[-1] = ChatMessage(
            "user",
            messages[-1].content
            + "\nRepair the rejected TransformProgram using only the Runtime validation errors and this prior candidate. "
            "Return the complete corrected JSON object; keep the same authorized evidence and make the smallest valid change.\n"
            + json.dumps(repair_context, ensure_ascii=False, sort_keys=True),
        )
        token_ids = _encode_prompt_tokens(codec, messages)
        observation: dict[str, Any] = {
            "role": "executor_repair",
            "attempt_id": attempt_id,
            "repair_stage": repair_stage,
            "validation_errors": list(validation_errors),
            "previous_program_hash": previous_program.program_hash,
            "prompt_tokens_exact": len(token_ids),
            "prompt_token_digest": sha256_digest(list(token_ids)),
        }
        if len(token_ids) + 512 + 64 > MAX_MODEL_LEN:
            observation.update({"status": "blocked_context_budget", "request_wall_ms": 0.0})
            observations.append(observation)
            raise ValueError("executor_repair_context_budget_exceeded")

        result, provider_observation = _complete_streaming(
            client,
            messages,
            purpose="executor",
            schema=_executor_schema(),
        )
        observation.update(provider_observation)
        observation.update({
            "role": "executor_repair",
            "attempt_id": attempt_id,
            "repair_stage": repair_stage,
            "validation_errors": list(validation_errors),
            "previous_program_hash": previous_program.program_hash,
            "prompt_tokens_exact": len(token_ids),
            "prompt_token_digest": sha256_digest(list(token_ids)),
        })
        observations.append(observation)
        if result is None:
            raise RuntimeError("executor_repair_provider_failed")
        candidate = _parse_transform_program_payload(
            raw_text=result.text,
            attempt_id=attempt_id,
            output_contract_version=step.output_contract_version,
            evidence_ref=input_ref_id,
            allowed_locators={locator: locator for locator in allowed_locators},
            program_id=f"utility-program-{attempt_id}-repair",
        )
        if not candidate.success or not isinstance(candidate.payload, TransformProgram):
            raise ValueError(candidate.error_code or "executor_repair_candidate_invalid")
        return candidate.payload

    return repair


def _executor_messages(case: Any, layout: str, attempt_id: str, *, namespace: str) -> list[ChatMessage]:
    exact_locators = _executor_source_locators(case)
    locator_instruction = (
        " Exact authorized source_locator strings (copy character-for-character; do not abbreviate, "
        "rename, or substitute dossier section labels): "
        + json.dumps(list(exact_locators), ensure_ascii=False)
        + ". Never emit `rules/active_scope_rules.json` or another shortened path; use the full strings above."
    )
    return [
        ChatMessage("system", case.layout_text(layout, "executor", namespace=namespace)),
        ChatMessage(
            "user",
            case.definition.question
            + "\n"
            + case.definition.executor_contract
            + "\n"
            + _transform_contract(case)
            + " Return a JSON object whose every operations item contains only op and nested arguments, "
            "using filter_eq arguments column/value and filter_in arguments column/values (plural array), "
            "for example {\"op\":\"filter_in\",\"arguments\":{\"column\":\"quarter\",\"values\":[\"2026Q1\",\"2026Q3\"]}}; "
            "do not put DSL arguments beside op. "
            "For derive_safe, use the exact nested arguments key `calculations`; never use `expressions`. "
            "Include no more than four exact source_locators: "
            "the active rule and representative ledger rows spanning early, middle, and late evidence. "
            + locator_instruction
            + " Use filter_eq/filter_in and aggregate_grouped. Do not enumerate the dossier or include answer totals."
            + f"\nRuntime attempt ID: {attempt_id}",
        ),
    ]


def _summarizer_messages(case: Any, layout: str, request: Any, *, namespace: str) -> list[ChatMessage]:
    artifact_input = next(
        item for item in request.role_context.verified_input_payloads
        if item.get("kind") == "execution_artifact"
    )
    active_rule_id = _active_rule_id(case)
    active_rule_locator = next(
        str(rule["source_locator"])
        for rule in case.rules
        if str(rule.get("rule_id", "")) == active_rule_id
    )
    required_fields = ", ".join(str(item) for item in _report_schema(case)["required"])
    artifact_text = json.dumps(
        {"artifact_ref": artifact_input["ref_id"], "rows": artifact_input["payload"].get("rows", ())},
        ensure_ascii=False,
        sort_keys=True,
    )
    return [
        ChatMessage("system", case.layout_text(layout, "summarizer", namespace=namespace, artifact=artifact_text)),
        ChatMessage(
            "user",
            case.definition.question
            + " Return one JSON object using exactly these required field names: "
            + required_fields
            + f". Set `rule_id` to the exact active rule ID `{active_rule_id}`; do not substitute `active_scope_rule`."
            + " Use `citations` as an array of 2-3 exact dossier `source_locator` strings; do not use `source_citations`. "
            + f"Include this active-rule locator: `{active_rule_locator}`, and at least one exact `ledger/` locator."
            + f"\nRuntime attempt ID: {request.bound_grant.grant.attempt_id}",
        ),
    ]


def _kv_health_issues(health: Mapping[str, Any], *, require_empty: bool) -> list[str]:
    issues: list[str] = []
    expected = {
        "status": "ready",
        "model": MODEL,
        "automatic_prefix_caching": False,
        "kv_connector": "StateBusLocalKVConnector",
        "kv_role": "kv_both",
        "max_model_len": MAX_MODEL_LEN,
        "max_num_seqs": 1,
        "tensor_parallel_size": 1,
        "pipeline_parallel_size": 1,
        "registry_one_shot": True,
    }
    for key, value in expected.items():
        if health.get(key) != value:
            issues.append(f"{key}_mismatch")
    for key in ("engine_id", "engine_generation", "compatibility_digest", "tokenizer_digest"):
        if not str(health.get(key, "")):
            issues.append(f"{key}_missing")
    block_size = int(health.get("block_size", 0) or 0)
    if block_size <= 0:
        issues.append("block_size_invalid")
    if int(health.get("registry_max_entries", 0) or 0) < 1:
        issues.append("registry_entry_capacity_missing")
    if int(health.get("registry_max_bytes", 0) or 0) <= 0:
        issues.append("registry_byte_capacity_missing")
    if require_empty and (
        int(health.get("registry_entries", -1) or 0) != 0
        or int(health.get("registry_bytes", -1) or 0) != 0
    ):
        issues.append("registry_not_empty_at_task_boundary")
    return issues


def _policy_order_for_case(cases: Sequence[Any], case_id: str) -> tuple[str, str, str]:
    case_index = next(index for index, case in enumerate(cases) if case.case_id == case_id)
    return logit_policy_order(case_index)


class _KVRunObserver:
    """Capture run-local KV receipts without persisting bearer credentials."""

    def __init__(self, client: VllmKVClient) -> None:
        self.client = client
        self.events: list[dict[str, Any]] = []

    def health(self) -> dict[str, Any]:
        payload = self.client.health()
        self.events.append({"event": "health", "payload": payload})
        return payload

    def produce(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        result = self.client.produce(payload)
        self.events.append({
            "event": "produce",
            "request_id": payload.get("request_id"),
            "task_id": payload.get("task_id"),
            "capture_kv": payload.get("capture_kv"),
            "parent_token_count": len(payload.get("parent_token_ids", ())),
            "parent_token_digest": sha256_digest(list(payload.get("parent_token_ids", ()))),
            "producer_suffix_token_count": len(payload.get("producer_suffix_token_ids", ())),
            "producer_suffix_token_digest": sha256_digest(list(payload.get("producer_suffix_token_ids", ()))),
            "response": result,
        })
        return result

    def continue_stream(self, payload: Mapping[str, Any]) -> Any:
        result = self.client.continue_stream(payload)
        self.events.append({
            "event": "continue",
            "request_id": payload.get("request_id"),
            "task_id": payload.get("task_id"),
            "lane": payload.get("lane"),
            "handle_id": payload.get("handle_id", ""),
            "parent_token_count": len(payload.get("parent_token_ids", ())),
            "parent_token_digest": sha256_digest(list(payload.get("parent_token_ids", ()))) if payload.get("parent_token_ids") else "",
            "suffix_token_count": len(payload.get("suffix_token_ids", ())),
            "suffix_token_digest": sha256_digest(list(payload.get("suffix_token_ids", ()))),
            "response": result.payload,
            "client_ttft_ms": result.client_ttft_ms,
            "client_wall_ms": result.client_wall_ms,
            "api_request_bytes": result.api_request_bytes,
            "token_event_count": result.token_event_count,
        })
        return result

    def release(self, handle_id: str) -> dict[str, Any]:
        payload = self.client.release(handle_id)
        self.events.append({"event": "release", "handle_id": handle_id, "response": payload})
        return payload

    def close(self) -> None:
        self.client.close()


def _taskpack_artifact_payload(taskpack: Taskpack) -> dict[str, Any]:
    gold_payload = {
        "cases": {case.case_id: case.gold for case in taskpack.cases},
        "logit_cases": {
            case.case_id: {"candidate": case.gold_candidate, "outcome": case.gold_outcome}
            for case in taskpack.logit_cases
        },
        "calibration_case": taskpack.calibration_case.gold,
    }
    return {
        "manifest": taskpack.manifest,
        "plan": list(taskpack.plan),
        "cases": [case.canonical_payload() for case in taskpack.cases],
        "logit_cases": [case.canonical_payload() for case in taskpack.logit_cases],
        "calibration_case": taskpack.calibration_case.canonical_payload(),
        "logit_calibration_case": taskpack.logit_calibration_case.canonical_payload(),
        "gold_digest": sha256_digest(gold_payload),
    }


class UtilitySuiteRunner:
    def __init__(
        self,
        taskpack: Taskpack,
        run_root: Path,
        *,
        quiet: bool = False,
        wall_budget_s: float = 5400.0,
        poll_interval_s: float = 60.0,
        resume: bool = False,
        target_slot_id: str | None = None,
        mode: str = "formal",
        namespace_codec: Any | None = None,
    ) -> None:
        self.taskpack = taskpack
        self.namespace_codec = namespace_codec
        self.run_root = run_root
        self.quiet = quiet
        self.wall_budget_s = wall_budget_s
        self.poll_interval_s = poll_interval_s
        self.mode = mode
        self.started = time.monotonic()
        self.records_path = run_root / "records.jsonl"
        self.run_log = run_root / "run.log"
        self.service_dir = run_root / "service"
        self.service_dir.mkdir(parents=True, exist_ok=True)
        self._record_count = 0
        self.standard_restored = "not_checked"
        self.execution_id = run_root.name
        self._standard_identity: dict[str, Any] | None = None
        self._kv_identity: dict[str, Any] | None = None
        self._switch_started = False
        self._previous_signal_handlers: dict[int, Any] = {}
        self.resume_enabled = resume
        self.target_slot_id = target_slot_id
        self._resume_latest: dict[str, dict[str, Any]] = {}
        if resume and self.records_path.is_file():
            for line_number, line in enumerate(self.records_path.read_text(encoding="utf-8").splitlines(), start=1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise UtilitySuiteError(f"resume_records_json_invalid:{line_number}") from exc
                slot_id = str(record.get("slot_id", ""))
                if slot_id and bool(record.get("scored", True)):
                    self._resume_latest[slot_id] = record

    def log(self, message: str) -> None:
        with self.run_log.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
        if not self.quiet:
            print(message)

    def record(self, payload: dict[str, Any]) -> None:
        payload = {
            "schema_version": "statebus.model_assist_utility.record.v1",
            "suite_revision": self.taskpack.manifest.get("suite_revision"),
            "run_id": self.run_root.name,
            **payload,
        }
        if self.execution_id != self.run_root.name:
            payload.setdefault("execution_id", self.execution_id)
        with self.records_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        slot_id = payload.get("slot_id")
        if slot_id:
            safe_slot = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(slot_id))
            slot_path = self.run_root / "slots" / f"{safe_slot}.json"
            slot_path.parent.mkdir(parents=True, exist_ok=True)
            if slot_path.exists():
                archive_dir = self.run_root / "slots" / "archive"
                archive_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(slot_path, archive_dir / f"{safe_slot}-{time.time_ns()}.json")
            slot_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            if bool(payload.get("scored", True)):
                self._resume_latest[str(slot_id)] = payload
            self.log(
                f"slot={slot_id} module={payload.get('module', '')} status={payload.get('status', '')} "
                f"quality={payload.get('business_quality', payload.get('quality', 'unavailable'))}"
            )
        elif payload.get("event") == "smoke_gate":
            self.log(f"gate module={payload.get('module', '')} passed={payload.get('passed', False)}")
        self._record_count += 1

    @staticmethod
    def _record_is_reusable(record: Mapping[str, Any]) -> bool:
        if record.get("status") != "completed":
            return False
        module = record.get("module")
        if module == "apc":
            return bool(
                record.get("business_quality") == "passed"
                and record.get("runtime", {}).get("runtime_completed")
                and record.get("mechanism_available")
                and record.get("prefix_contract_ok")
            )
        if module == "logit":
            return bool(
                record.get("business_quality") in {"passed", "correct_abstention"}
                and record.get("exact_available")
            )
        if module == "kv":
            return bool(
                record.get("quality")
                and record.get("runtime", {}).get("runtime_completed")
                and record.get("mechanism_available")
                and record.get("release_clean")
                and record.get("registry_clean")
            )
        return False

    def _resume_group_records(
        self,
        module: str,
        case_id: str,
        conditions: Sequence[str],
    ) -> list[dict[str, Any]] | None:
        if not self.resume_enabled:
            return None
        if module == "apc":
            slot_ids = [f"{case_id}:apc_on_{condition}" for condition in conditions]
        else:
            slot_ids = [f"{case_id}:{condition}" for condition in conditions]
        records = [self._resume_latest.get(slot_id) for slot_id in slot_ids]
        if all(record is not None and self._record_is_reusable(record) for record in records):
            reused = [dict(record) for record in records if record is not None]
            decision = {"module": module, "case_id": case_id, "conditions": list(conditions), "action": "reuse_completed_group"}
            self.log(f"resume_action=reuse_completed_group module={module} case_id={case_id}")
            _append_jsonl(self.run_root / "resume-decisions.jsonl", decision)
            return reused
        decision = {
            "module": module,
            "case_id": case_id,
            "conditions": list(conditions),
            "action": "rerun_entire_group",
            "missing_or_invalid_slots": [slot_id for slot_id, record in zip(slot_ids, records) if record is None or not self._record_is_reusable(record)],
        }
        self.log(f"resume_action=rerun_entire_group module={module} case_id={case_id}")
        _append_jsonl(self.run_root / "resume-decisions.jsonl", decision)
        return None

    def recover_orphaned_logit_traces(self) -> tuple[str, ...]:
        if not self.resume_enabled:
            return ()
        trace_root = self.run_root / "decision-traces"
        if not trace_root.is_dir():
            return ()
        recovered: list[str] = []
        for trace_path in sorted(trace_root.glob("*/*.json")):
            try:
                trace = json.loads(trace_path.read_text(encoding="utf-8"))
                slot_id = str(trace.get("slot_id", ""))
                safe_slot = re.sub(r"[^A-Za-z0-9_.-]+", "_", slot_id)
                slot_path = self.run_root / "slots" / f"{safe_slot}.json"
                if slot_path.is_file() and trace_path.stat().st_mtime_ns <= slot_path.stat().st_mtime_ns:
                    continue
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            if trace.get("module") != "logit" or not trace.get("scored") or not slot_id:
                continue
            if not isinstance(trace.get("correct"), bool) or not isinstance(trace.get("runtime"), Mapping):
                continue
            if not isinstance(trace.get("provider_requests"), list) or not trace["provider_requests"]:
                continue
            choice_attempts = trace.get("choice_attempts")
            exact_available = bool(choice_attempts) and all(
                isinstance(item, Mapping)
                and isinstance(item.get("extraction_payload"), Mapping)
                and bool(item["extraction_payload"].get("available"))
                for item in choice_attempts
            )
            correct = bool(trace["correct"])
            business_quality = (
                "correct_abstention"
                if correct and trace.get("gold_outcome") == "abstain"
                else "passed" if correct else "failed"
            )
            recovered_record = trace | {
                "status": "completed" if correct else "failed",
                "business_quality": business_quality,
                "exact_available": exact_available,
                "orphan_trace_recovered": True,
                "orphan_trace_path": str(trace_path),
            }
            self.record(recovered_record)
            recovered.append(slot_id)
        return tuple(recovered)

    def _resume_logit_position(self, case_id: str, policy: str) -> dict[str, Any] | None:
        if not self.resume_enabled:
            return None
        slot_id = f"{case_id}:{policy}"
        record = self._resume_latest.get(slot_id)
        if record is None:
            return None
        status = str(record.get("status", ""))
        has_requests = bool(record.get("provider_requests"))
        if status not in {"completed", "failed", "refused"} and not has_requests:
            return None
        reused = self._reused_result(record)
        action = "reuse_completed_slot" if reused["gate_ready"] else "reuse_terminal_slot"
        decision = {
            "module": "logit",
            "case_id": case_id,
            "slot_id": slot_id,
            "action": action,
            "status": status,
        }
        self.log(f"resume_action={action} slot_id={slot_id}")
        _append_jsonl(self.run_root / "resume-decisions.jsonl", decision)
        return reused

    def _reused_result(self, record: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(record)
        result.update({"gate_ready": self._record_is_reusable(record), "resumed_skipped": True})
        return result

    def _run_apc_group(
        self,
        case: Any,
        layouts: Sequence[str],
        client: OpenAICompatibleLLMClient,
        codec: VllmTokenCodec,
    ) -> list[dict[str, Any]]:
        existing = self._resume_group_records("apc", case.case_id, layouts)
        if existing is not None:
            return [self._reused_result(record) for record in existing]
        namespace_pair = self._apc_namespace_pair(case, layouts, codec)
        return [
            self.run_apc(
                case,
                layout,
                client,
                codec,
                namespace=namespace_pair[layout]["namespace"],
                namespace_prefix_token_count=namespace_pair[layout]["prefix_token_count"],
                namespace_prefix_token_digest=namespace_pair[layout]["prefix_token_digest"],
                namespace_pair_contract={
                    "different_values": len({item["namespace"] for item in namespace_pair.values()}) == len(namespace_pair),
                    "equal_prefix_token_counts": len({item["prefix_token_count"] for item in namespace_pair.values()}) == 1,
                    "condition_scoped": True,
                },
                scored=True,
            ) | {"case_id": case.case_id, "condition": layout}
            for layout in layouts
        ]

    def _run_targeted_apc_slot(
        self,
        case: Any,
        layout: str,
        client: OpenAICompatibleLLMClient,
        codec: VllmTokenCodec,
    ) -> dict[str, Any]:
        namespace_pair = self._apc_namespace_pair(case, ("independent", "shared"), codec)
        namespace_info = namespace_pair[layout]
        result = self.run_apc(
            case,
            layout,
            client,
            codec,
            namespace=namespace_info["namespace"],
            namespace_prefix_token_count=namespace_info["prefix_token_count"],
            namespace_prefix_token_digest=namespace_info["prefix_token_digest"],
            namespace_pair_contract={
                "different_values": len({item["namespace"] for item in namespace_pair.values()}) == 2,
                "equal_prefix_token_counts": len({item["prefix_token_count"] for item in namespace_pair.values()}) == 1,
                "condition_scoped": True,
            },
            scored=True,
        )
        return result | {"case_id": case.case_id, "condition": f"apc_on_{layout}"}

    def _run_targeted_logit_slot(
        self,
        case: Any,
        policy: str,
        client: OpenAICompatibleLLMClient,
        codec: VllmTokenCodec,
    ) -> dict[str, Any]:
        result = self.run_logit(case, policy, client, codec, scored=True)
        return result | {"case_id": case.case_id, "condition": policy}

    def _apc_namespace_pair(
        self,
        case: Any,
        layouts: Sequence[str],
        codec: VllmTokenCodec,
    ) -> dict[str, dict[str, Any]]:
        assignments: dict[str, dict[str, Any]] = {}
        search_codec = self.namespace_codec or codec
        for layout in layouts:
            assignments[layout] = build_cache_namespace(
                case,
                search_codec,
                run_id=self.execution_id,
                scope=f"apc-condition:{layout}",
                forbidden=tuple(item["namespace"] for item in assignments.values()),
            )
            server_token_ids = tuple(codec.encode_messages(
                [{"role": "system", "content": shared_prefix_envelope(case.shared_prefix_text(assignments[layout]["namespace"]))}],
                add_generation_prompt=False,
                chat_template_kwargs={"enable_thinking": False},
            ))
            if (
                len(server_token_ids) != assignments[layout]["prefix_token_count"]
                or sha256_digest(list(server_token_ids)) != assignments[layout]["prefix_token_digest"]
            ):
                raise UtilitySuiteError(f"apc_namespace_tokenizer_mismatch:{case.case_id}:{layout}")
        if (
            len({item["namespace"] for item in assignments.values()}) != len(assignments)
            or len({item["prefix_token_count"] for item in assignments.values()}) != 1
            or any(item["prefix_token_count"] != case.target_prefix_tokens for item in assignments.values())
        ):
            raise UtilitySuiteError(f"apc_namespace_pair_contract_failed:{case.case_id}")
        return assignments

    def _run_logit_group(
        self,
        case: Any,
        policies: Sequence[str],
        client: OpenAICompatibleLLMClient,
        codec: VllmTokenCodec,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for policy in policies:
            resumed = self._resume_logit_position(case.case_id, policy)
            if resumed is not None:
                results.append(resumed)
                continue
            results.append(
                self.run_logit(case, policy, client, codec, scored=True)
                | {"case_id": case.case_id, "condition": policy}
            )
        return results

    def _run_kv_group(
        self,
        case: Any,
        conditions: Sequence[str],
        *,
        delegate: OpenAICompatibleLLMClient,
    ) -> list[dict[str, Any]]:
        existing = self._resume_group_records("kv", case.case_id, conditions)
        if existing is not None:
            return [self._reused_result(record) for record in existing]
        return [
            self._run_kv_position(case, condition, delegate=delegate, scored=True)
            | {
                "slot_id": f"{case.case_id}:{condition}",
                "case_id": case.case_id,
                "condition": condition,
            }
            for condition in conditions
        ]

    def all_positions_reusable(self) -> bool:
        if not self.resume_enabled:
            return False
        return all(
            (record := self._resume_latest.get(f"{item['case_id']}:{item['condition']}")) is not None
            and self._record_is_reusable(record)
            for item in PLAN_POSITIONS
        )

    def all_module_positions_reusable(self, module: str) -> bool:
        if not self.resume_enabled:
            return False
        positions = [item for item in PLAN_POSITIONS if item["module"] == module]
        return bool(positions) and all(
            (record := self._resume_latest.get(f"{item['case_id']}:{item['condition']}")) is not None
            and self._record_is_reusable(record)
            for item in positions
        )

    def write_initial_artifacts(self, preflight: PreflightResult) -> None:
        self.run_root.mkdir(parents=True, exist_ok=True)
        taskpack_payload = _taskpack_artifact_payload(self.taskpack)
        (self.run_root / "plan.json").write_text(json.dumps(plan_artifact_payload(self.taskpack), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (self.run_root / "taskpack.json").write_text(json.dumps(taskpack_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (self.run_root / "manifest.json").write_text(json.dumps(self.taskpack.manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (self.run_root / "compiled-prefixes.json").write_text(json.dumps({case.case_id: case.canonical_payload() | {"prefix_token_ids": list(case.prefix_token_ids)} for case in self.taskpack.cases}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (self.run_root / "preflight.json").write_text(json.dumps(preflight.evidence | {"passed": preflight.passed, "reasons": list(preflight.reasons)}, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        (self.run_root / "necessity-checks.json").write_text((SAMPLE_ROOT / "necessity-checks.json").read_text(encoding="utf-8") if (SAMPLE_ROOT / "necessity-checks.json").exists() else "{}\n", encoding="utf-8")
        (self.run_root / "slots").mkdir(exist_ok=True)
        (self.run_root / "decision-traces").mkdir(exist_ok=True)
        (self.run_root / "changes-and-reruns.md").write_text(
            "# Changes and reruns\n\n"
            "This run uses the frozen `longtext-demo-v3` taskpack. Any repair or rerun must use a new run ID; prior evidence is immutable.\n\n"
            "The runner records warmup separately, stops on a failed module gate, and restores the manager-owned standard service after KV.\n",
            encoding="utf-8",
        )
        (self.run_root / "commands.md").write_text(
            "# Utility suite commands\n\n"
            f"- prepare: `scripts/experiments/contest_model_assist/run_utility_suite.sh --mode prepare`\n"
            f"- dry-run: `scripts/experiments/contest_model_assist/run_utility_suite.sh --mode formal --phase all --dry-run`\n"
            f"- recover: `scripts/experiments/contest_model_assist/run_utility_suite.sh --mode formal --recover-only --run-id {self.run_root.name}`\n",
            encoding="utf-8",
        )
        (self.run_root / "run-config.json").write_text(
            json.dumps(
                {
                    "suite_revision": self.taskpack.manifest.get("suite_revision"),
                    "mode": self.mode,
                    "wall_budget_s": self.wall_budget_s,
                    "poll_interval_s": self.poll_interval_s,
                    "phase": self.taskpack.manifest.get("phase", "all"),
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    def _check_budget(self) -> None:
        if time.monotonic() - self.started >= self.wall_budget_s:
            raise UtilitySuiteBudgetExceeded("incomplete_budget")

    def _install_signal_handlers(self) -> None:
        def _handle(signum: int, _frame: Any) -> None:
            name = signal.Signals(signum).name
            self.log(f"received_signal={name}; recovery will run before exit")
            raise UtilitySuiteInterrupted(name)

        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                self._previous_signal_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, _handle)
            except (ValueError, OSError):
                # Signal installation is only available in the main thread;
                # tests and read-only callers may invoke the runner elsewhere.
                continue

    def _restore_signal_handlers(self) -> None:
        for signum, handler in self._previous_signal_handlers.items():
            try:
                signal.signal(signum, handler)
            except (ValueError, OSError):
                pass
        self._previous_signal_handlers.clear()

    def run_apc(
        self,
        case: Any,
        layout: str,
        client: OpenAICompatibleLLMClient,
        codec: VllmTokenCodec,
        *,
        namespace: str,
        namespace_prefix_token_count: int,
        namespace_prefix_token_digest: str,
        namespace_pair_contract: Mapping[str, Any],
        scored: bool = True,
    ) -> dict[str, Any]:
        slot_id = f"{case.case_id}:apc_on_{layout}"
        started = time.perf_counter_ns()
        metric_prefix = f"{self.execution_id}-{case.case_id}-{layout}"
        before = _metrics_snapshot(self.run_root, f"{metric_prefix}-before")
        observations: list[dict[str, Any]] = []
        prompt_token_ids: list[tuple[str, tuple[int, ...]]] = []
        runtime_error: dict[str, str] | None = None

        def executor_handler(request: Any) -> ProviderCandidate:
            attempt_id = request.bound_grant.grant.attempt_id
            messages = _executor_messages(case, layout, attempt_id, namespace=namespace)
            token_ids = _encode_prompt_tokens(codec, messages)
            prompt_token_ids.append((request.step.step_id, token_ids))
            if len(token_ids) + 512 + 64 > MAX_MODEL_LEN:
                observations.append({"role": "executor", "attempt_id": attempt_id, "status": "blocked_context_budget", "prompt_tokens_exact": len(token_ids)})
                return ProviderCandidate(False, "failure", error_code="provider_prompt_budget_exceeded")
            result, observation = _complete_streaming(client, messages, purpose="executor", schema=_executor_schema())
            observation.update({"role": "executor", "attempt_id": attempt_id, "prompt_tokens_exact": len(token_ids), "prompt_token_digest": sha256_digest(list(token_ids))})
            observations.append(observation)
            if result is None:
                return ProviderCandidate(False, "failure", error_code="executor_provider_error")
            return _parse_transform_program(request=request, raw_text=result.text)

        def summarizer_handler(request: Any) -> ProviderCandidate:
            messages = _summarizer_messages(case, layout, request, namespace=namespace)
            token_ids = _encode_prompt_tokens(codec, messages)
            prompt_token_ids.append((request.step.step_id, token_ids))
            if len(token_ids) + 384 + 64 > MAX_MODEL_LEN:
                observations.append({"role": "summarizer", "attempt_id": request.bound_grant.grant.attempt_id, "status": "blocked_context_budget", "prompt_tokens_exact": len(token_ids)})
                return ProviderCandidate(False, "failure", error_code="provider_prompt_budget_exceeded")
            result, observation = _complete_streaming(client, messages, purpose="summarizer", schema=_report_schema(case))
            observation.update({"role": "summarizer", "attempt_id": request.bound_grant.grant.attempt_id, "prompt_tokens_exact": len(token_ids), "prompt_token_digest": sha256_digest(list(token_ids))})
            observations.append(observation)
            if result is None:
                return ProviderCandidate(False, "failure", error_code="summarizer_provider_error")
            return _claim_candidate_from_report(request=request, raw_text=result.text)[0]

        repair_factory = _executor_repair_factory(
            case=case,
            layout=layout,
            namespace=namespace,
            client=client,
            codec=codec,
            observations=observations,
        )

        runtime_result: Any = None
        try:
            runtime_result = run_utility_runtime(
                slot_id=slot_id,
                run_id=self.run_root.name,
                runtime_root=self.run_root / "runtime" / self.execution_id / re.sub(r"[^A-Za-z0-9_.-]+", "_", slot_id),
                workspace_root=self.run_root / "workspaces" / self.execution_id,
                task_question=case.definition.question,
                task_family=case.definition.business,
                task_arguments={"case_id": case.case_id, "layout": layout, "source_digest": case.source_digest},
                source_hash=case.source_digest,
                rows=tuple(dict(row) for row in case.source_rows),
                additional_evidence=tuple({**rule, "text": json.dumps(rule, ensure_ascii=False, sort_keys=True)} for rule in case.rules),
                input_fields=_runtime_input_schema(case.source_rows),
                output_schema=_runtime_output_schema(case),
                executor_handler=executor_handler,
                summarizer_handler=summarizer_handler,
                transform_program_repair_factory=repair_factory,
            )
        except Exception as exc:
            runtime_error = {"type": type(exc).__name__, "message": str(exc)}
        runtime_payload = _runtime_evidence(runtime_result) if runtime_result is not None else {
            "runtime_completed": False,
            "execution_path": "RuntimeDriver.run_mode(adaptive_bounded)->AdaptiveMainlineRunner->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher",
            "dispatches": [],
            "attempts": [],
            "artifacts": [],
            "candidate_review_records": [],
        }
        parsed: dict[str, Any] | None = None
        claim_sets = list(runtime_result.context.claim_sets.values()) if runtime_result is not None else []
        for claim_set in claim_sets:
            for claim in claim_set.claims:
                try:
                    parsed = extract_json_object(claim.claim_text)
                except Exception:
                    parsed = None
                if parsed is not None:
                    break
        quality, quality_errors = _validate_report(case, parsed)
        after = _metrics_snapshot(self.run_root, f"{metric_prefix}-after")
        lcp_tokens = 0
        lcp_digest = ""
        if len(prompt_token_ids) >= 2:
            left, right = prompt_token_ids[0][1], prompt_token_ids[1][1]
            for left_token, right_token in zip(left, right):
                if left_token != right_token:
                    break
                lcp_tokens += 1
            lcp_digest = sha256_digest(list(left[:lcp_tokens]))
        input_tokens = sum(int(item.get("prompt_tokens_exact", 0)) for item in observations)
        prefix_contract_ok = (
            namespace_prefix_token_count == case.target_prefix_tokens
            and bool(namespace_pair_contract.get("different_values"))
            and bool(namespace_pair_contract.get("equal_prefix_token_counts"))
            and (
                layout != "shared"
                or case.definition.target_min_tokens <= lcp_tokens <= case.definition.target_max_tokens
            )
        )
        successful_requests = sum(item.get("status") == "response" for item in observations)
        metrics_payload = _apc_delta(before, after, successful_requests)
        mechanism_available = metrics_payload.get("status") != "unavailable" and bool(metrics_payload.get("valid", False))
        runtime_ok = bool(runtime_result is not None and runtime_result.runtime.completed)
        consumer_observation = next((item for item in observations if item.get("role") == "summarizer"), {})
        consumer_ttft_ms = consumer_observation.get("ttft_ms")
        status = "completed" if runtime_ok else "failed"
        self.record({
            "slot_id": slot_id,
            "module": "apc",
            "case_id": case.case_id,
            "condition": f"apc_on_{layout}",
            "scored": scored,
            "warmup_namespace": "scored" if scored else "calibration-only",
            "status": status,
            "business_quality": "passed" if quality else "failed",
            "quality_errors": quality_errors,
            "layout": layout,
            "token_identity": {"actual_role_lcp_tokens": lcp_tokens, "actual_role_lcp_digest": lcp_digest, "compiled_prefix_tokens": case.target_prefix_tokens, "compiled_prefix_digest": case.prefix_token_digest, "source_digest": case.source_digest, "input_tokens_exact": input_tokens},
            "cache_namespace": namespace,
            "namespace_prefix_token_count": namespace_prefix_token_count,
            "namespace_prefix_token_digest": namespace_prefix_token_digest,
            "namespace_pair_contract": dict(namespace_pair_contract),
            "shared_template_prefix_may_hit_across_conditions": True,
            "role_visibility": case.role_visibility,
            "provider_requests": observations,
            "repair_requests": [item for item in observations if item.get("role") == "executor_repair"],
            "runtime": runtime_payload,
            "runtime_error": runtime_error,
            "executor_artifact": next((item for item in runtime_payload["artifacts"] if item["step_id"] == "execute"), None),
            "summarizer_claim_sets": [item.canonical_payload() for item in claim_sets],
            "output": parsed,
            "metrics_delta": metrics_payload,
            "mechanism_available": mechanism_available,
            "prefix_contract_ok": prefix_contract_ok,
            "consumer_ttft_ms": consumer_ttft_ms,
            "ttft_status": "measured_streaming" if isinstance(consumer_ttft_ms, (int, float)) else "unavailable_no_nonempty_content",
            "task_wall_ms": (time.perf_counter_ns() - started) / 1_000_000.0,
        })
        return {"slot_id": slot_id, "quality": quality, "status": status, "mechanism_available": mechanism_available, "runtime_completed": runtime_ok, "prefix_contract_ok": prefix_contract_ok, "gate_ready": bool(quality and mechanism_available and runtime_ok and prefix_contract_ok)}

    def run_logit(
        self,
        case: Any,
        policy: str,
        client: OpenAICompatibleLLMClient,
        codec: VllmTokenCodec,
        *,
        scored: bool = True,
    ) -> dict[str, Any]:
        slot_id = f"{case.case_id}:{policy}"
        trace_dir = self.run_root / "decision-traces" / self.execution_id
        trace_dir.mkdir(parents=True, exist_ok=True)
        if policy not in {"compact_once", "full_context_once", "logit_selective"}:
            raise ValueError(f"unsupported_logit_policy:{policy}")
        candidate_rows = tuple(dict(item) for item in case.candidates)
        candidates = tuple(str(item["candidate_id"]) for item in candidate_rows) + ("insufficient_evidence",)
        surface = CandidateSurfaceV2.from_candidate_ids(candidates)
        choice_schema = _json_schema({"choice_code": {"type": "string", "enum": list(surface.aliases)}})
        choice_states: dict[str, dict[str, Any]] = {}
        provider_observations: list[dict[str, Any]] = []
        runtime_result: Any = None
        runtime_error: dict[str, str] | None = None
        report_payload: dict[str, Any] | None = None
        report_quality_errors: list[str] = []
        report_observation: dict[str, Any] = {"status": "not_requested"}
        runtime_payload: dict[str, Any] = {"runtime_completed": False, "dispatches": [], "candidate_review_records": []}
        candidate_ids = {str(item.get("candidate_id", "")) for item in candidate_rows}
        valid_refs = (
            len(candidate_rows) == 2
            and len(candidate_ids) == 2
            and all(str(item.get("source_locator", "")).count("#") == 1 for item in candidate_rows)
            and all(item.get("grant_scope") == "model_assist_utility_frozen_sources" for item in candidate_rows)
            and all("2026" in str(item.get("valid_period", "")) for item in candidate_rows)
            and all(str(item.get("compact_evidence", "")).strip() for item in candidate_rows)
            and all(str(item.get("full_evidence", "")).strip() for item in candidate_rows)
            and len({str(item.get("source_locator", "")) for item in candidate_rows}) == len(candidate_rows)
        )

        def executor_handler(request: Any) -> ProviderCandidate:
            attempt_id = request.bound_grant.grant.attempt_id
            if request.step.step_id == "execute_full":
                stage = "full_recheck"
            elif policy == "full_context_once":
                stage = "full"
            else:
                stage = "compact"
            evidence_pack = next(
                item["payload"] for item in request.role_context.verified_input_payloads
                if item.get("kind") == "canonical_evidence_pack"
            )
            authorized_rows = {
                str(row.get("candidate_id", "")): row
                for item in evidence_pack.get("structured_evidence", ())
                if isinstance(item, Mapping)
                and isinstance(item.get("metadata"), Mapping)
                and isinstance((row := item["metadata"].get("structured_row")), Mapping)
            }
            evidence_field = "full_evidence" if stage in {"full", "full_recheck"} else "compact_evidence"
            candidate_lines = []
            for alias, candidate in zip(surface.aliases, candidate_rows):
                authorized = authorized_rows.get(str(candidate["candidate_id"]))
                if authorized is None or authorized.get("source_locator") != candidate.get("source_locator"):
                    return ProviderCandidate(False, "failure", error_code="logit_candidate_not_in_runtime_evidence")
                candidate_lines.append(
                    f"{alias}: candidate_id={candidate['candidate_id']}; label={candidate['label']}; "
                    f"source={candidate['source_locator']}; scope={candidate['grant_scope']}; "
                    f"valid_period={candidate['valid_period']}\n{authorized[evidence_field]}"
                )
            insufficient_alias = surface.aliases[-1]
            candidate_lines.append(f"{insufficient_alias}: candidate_id=insufficient_evidence; no sufficient authorized source")
            messages = [
                ChatMessage("system", "Choose only among the authorized evidence candidates. Return the required JSON choice code; do not calculate the business result."),
                ChatMessage(
                    "user",
                    f"Question: {case.question}\nVisible evidence stage: {stage}\n\nCandidates:\n{chr(10).join(candidate_lines)}\n\nReturn exactly one choice_code.\nRuntime attempt ID: {attempt_id}",
                ),
            ]
            token_ids = _encode_prompt_tokens(codec, messages)
            if len(token_ids) + 32 + 64 > MAX_MODEL_LEN:
                provider_observations.append({"role": "executor", "stage": stage, "attempt_id": attempt_id, "status": "blocked_context_budget", "prompt_tokens_exact": len(token_ids)})
                return ProviderCandidate(False, "failure", error_code="provider_prompt_budget_exceeded")
            result, observation = _complete(client, messages, purpose="executor", schema=choice_schema)
            observation.update({
                "role": "executor",
                "stage": stage,
                "attempt_id": attempt_id,
                "request_id": f"{slot_id}-{stage}-{attempt_id}",
                "prompt_tokens_exact": len(token_ids),
                "prompt_token_digest": sha256_digest(list(token_ids)),
                "raw_top_logprobs": _serialize_top_logprobs(result.top_logprobs) if result else [],
            })
            if result:
                extraction, token_byte_alignment = _extract_utility_choice_logit_state(
                    completion_text=result.text,
                    top_logprobs=result.top_logprobs,
                    candidate_surface=surface,
                    request_id=str(observation["request_id"]),
                    attempt_id=attempt_id,
                )
            else:
                extraction = None
                token_byte_alignment = {"source": "provider_bytes", "status": "no_response"}
            observation["token_byte_alignment"] = token_byte_alignment
            extraction_payload = _logit_extraction_payload(extraction, surface) if extraction else None
            state = {
                "stage": stage,
                "attempt_id": attempt_id,
                "result_text": result.text if result else "",
                "extraction": extraction,
                "extraction_payload": extraction_payload,
                "candidate_id": extraction.selected_candidate_id if extraction else "",
                "observation": observation,
            }
            choice_states[attempt_id] = state
            provider_observations.append(observation)
            if result is None:
                return ProviderCandidate(False, "failure", error_code="executor_provider_error")
            if extraction is None or not extraction.selected_candidate_id:
                return ProviderCandidate(False, "failure", error_code="executor_choice_invalid")
            if extraction.selected_candidate_id == "insufficient_evidence":
                return ProviderCandidate(False, "failure", error_code="model_assist_insufficient_evidence")
            evidence_ref = next(
                str(item["ref_id"])
                for item in request.role_context.verified_input_payloads
                if item.get("kind") == "canonical_evidence_pack"
            )
            program = TransformProgram(
                program_id=f"utility-logit-{attempt_id}",
                input_artifact_refs=(evidence_ref,),
                operations=(
                    TransformStep("filter_eq", {"column": "candidate_id", "value": extraction.selected_candidate_id}),
                    TransformStep("select", {"columns": ["candidate_id", "label", "source_locator", "grant_scope", "valid_period"]}),
                ),
                output_contract_version=request.step.output_contract_version,
            )
            return ProviderCandidate(
                True,
                "executor_program",
                program,
                diagnostics=(
                    ("selected_candidate_id", extraction.selected_candidate_id),
                    ("exact_available", extraction.available),
                    ("selected_is_top1", extraction_payload["selected_is_top1"]),
                    ("other_mass", extraction.other_mass),
                    ("top_margin", extraction.top_margin),
                    ("stage", stage),
                ),
            )

        def review_candidate(request: Any, candidate: ProviderCandidate) -> ExecutorCandidateReviewDecision:
            state = choice_states.get(request.bound_grant.grant.attempt_id)
            if state is None:
                return ExecutorCandidateReviewDecision("abstain", "choice_trace_missing")
            extraction = state["extraction"]
            stage = str(state["stage"])
            selected = str(state["candidate_id"])
            if candidate.candidate_kind == "failure" and candidate.error_code == "model_assist_insufficient_evidence":
                if policy == "logit_selective" and stage == "compact":
                    return ExecutorCandidateReviewDecision("request_evidence_recheck", "compact_insufficient_evidence")
                return ExecutorCandidateReviewDecision("abstain", "insufficient_evidence")
            if extraction is None or not extraction.available:
                if policy == "logit_selective" and stage == "compact":
                    return ExecutorCandidateReviewDecision("request_evidence_recheck", "exact_unavailable")
                return ExecutorCandidateReviewDecision("abstain", "exact_unavailable")
            if selected == "insufficient_evidence":
                if policy == "logit_selective" and stage == "compact":
                    return ExecutorCandidateReviewDecision("request_evidence_recheck", "compact_insufficient_evidence")
                return ExecutorCandidateReviewDecision("abstain", "insufficient_evidence")
            probabilities = extraction.candidate_probabilities
            selected_probability = probabilities[surface.aliases.index(extraction.selected_alias)]
            selected_is_top1 = selected_probability >= max(probabilities)
            reasons = []
            if not selected_is_top1:
                reasons.append("selected_not_top1")
            if extraction.other_mass > 0.20:
                reasons.append("other_mass_over_limit")
            if extraction.top_margin < 0.10:
                reasons.append("top_margin_below_tau")
            if policy == "logit_selective" and stage == "compact" and reasons:
                return ExecutorCandidateReviewDecision(
                    "request_evidence_recheck",
                    ",".join(reasons),
                    (("selected_candidate_id", selected), ("other_mass", extraction.other_mass), ("top_margin", extraction.top_margin)),
                )
            if policy == "logit_selective" and stage == "full_recheck" and reasons:
                return ExecutorCandidateReviewDecision("abstain", f"full_view_still_uncertain:{','.join(reasons)}")
            return ExecutorCandidateReviewDecision(
                "continue",
                "choice_admitted",
                (("selected_candidate_id", selected), ("other_mass", extraction.other_mass), ("top_margin", extraction.top_margin)),
            )

        def summarizer_handler(request: Any) -> ProviderCandidate:
            artifact_input = next(
                item for item in request.role_context.verified_input_payloads
                if item.get("kind") == "execution_artifact"
            )
            rows = artifact_input["payload"].get("rows", ())
            if len(rows) != 1:
                return ProviderCandidate(False, "failure", error_code="logit_selected_artifact_cardinality_invalid")
            selected = str(rows[0].get("candidate_id", ""))
            locator = str(rows[0].get("source_locator", ""))
            messages = [
                ChatMessage("system", "Summarize the Runtime-verified selected evidence candidate. Cite its exact source locator; do not claim a business result that is not in the selected artifact."),
                ChatMessage(
                    "user",
                    f"Question: {case.question}\nVerified selected evidence: {json.dumps(rows[0], ensure_ascii=False, sort_keys=True)}\nReturn JSON with decision=select, evidence_id={selected}, a concise summary, and citations containing {locator}.",
                ),
            ]
            token_ids = _encode_prompt_tokens(codec, messages)
            if len(token_ids) + 256 + 64 > MAX_MODEL_LEN:
                provider_observations.append({"role": "summarizer", "status": "blocked_context_budget", "prompt_tokens_exact": len(token_ids)})
                return ProviderCandidate(False, "failure", error_code="summarizer_prompt_budget_exceeded")
            schema = _json_schema({
                "decision": {"type": "string", "enum": ["select"]},
                "evidence_id": {"type": "string", "enum": list(candidate_ids)},
                "summary": {"type": "string"},
                "citations": {"type": "array", "items": {"type": "string", "enum": [str(item["source_locator"]) for item in candidate_rows]}, "minItems": 1, "maxItems": 3},
            })
            result, observation = _complete(client, messages, purpose="summarizer", schema=schema)
            observation.update({"role": "summarizer", "attempt_id": request.bound_grant.grant.attempt_id, "selected_candidate_id": selected, "prompt_tokens_exact": len(token_ids), "prompt_token_digest": sha256_digest(list(token_ids))})
            provider_observations.append(observation)
            if result is None:
                return ProviderCandidate(False, "failure", error_code="summarizer_provider_error")
            return _claim_candidate_from_report(request=request, raw_text=result.text)[0]

        if not valid_refs:
            runtime_error = {"type": "ValueError", "message": "logit_candidate_source_or_scope_check_failed"}
        else:
            utility_enabled_before = os.environ.get("STATEBUS_MODEL_ASSIST_UTILITY_ENABLED")
            os.environ["STATEBUS_MODEL_ASSIST_UTILITY_ENABLED"] = "1"
            try:
                runtime_result = run_utility_runtime(
                    slot_id=slot_id,
                    run_id=self.run_root.name,
                    runtime_root=self.run_root / "runtime" / self.execution_id / re.sub(r"[^A-Za-z0-9_.-]+", "_", slot_id),
                    workspace_root=self.run_root / "workspaces" / self.execution_id,
                    task_question=case.question,
                    task_family=f"evidence-routing:{case.group}",
                    task_arguments={"case_id": case.case_id, "policy": policy},
                    source_hash=sha256_digest(case.canonical_payload()),
                    rows=candidate_rows,
                    input_fields=_runtime_input_schema(candidate_rows),
                    output_schema={"candidate_id": "string", "label": "string", "source_locator": "string", "grant_scope": "string", "valid_period": "string"},
                    executor_handler=executor_handler,
                    summarizer_handler=summarizer_handler,
                    executor_candidate_review=ExecutorCandidateReviewBinding(
                        suite_id=UTILITY_SUITE_ID,
                        capability_id=UTILITY_EXECUTOR_CAPABILITY,
                        review=review_candidate,
                    ),
                    allow_evidence_replan=policy == "logit_selective",
                )
            except Exception as exc:
                runtime_error = {"type": type(exc).__name__, "message": str(exc)}
            finally:
                if utility_enabled_before is None:
                    os.environ.pop("STATEBUS_MODEL_ASSIST_UTILITY_ENABLED", None)
                else:
                    os.environ["STATEBUS_MODEL_ASSIST_UTILITY_ENABLED"] = utility_enabled_before

        if runtime_result is not None:
            runtime_payload = _runtime_evidence(runtime_result)
            claim_sets = list(runtime_result.context.claim_sets.values())
            for claim_set in claim_sets:
                for claim in claim_set.claims:
                    try:
                        report_payload = extract_json_object(claim.claim_text)
                    except Exception:
                        report_payload = None
                    if report_payload is not None:
                        break
                if report_payload is not None:
                    break
        else:
            claim_sets = []

        ordered_states = list(choice_states.values())
        final_state = ordered_states[-1] if ordered_states else None
        selected = str(final_state["candidate_id"]) if final_state else ""
        exact_available = bool(ordered_states) and all(
            bool(item["extraction"] and item["extraction"].available)
            for item in ordered_states
        )
        review_records = runtime_payload.get("candidate_review_records", [])
        runtime_action = str(review_records[-1].get("action", "not_reached")) if review_records else "not_reached"
        expanded = any(item.get("action") == "request_evidence_recheck" for item in review_records)
        expansion_reason = next((str(item.get("reason", "")) for item in review_records if item.get("action") == "request_evidence_recheck"), "")
        if case.gold_outcome == "abstain":
            business_correct = _runtime_abstained(runtime_action, runtime_payload) and selected == "insufficient_evidence"
            report_quality_errors = [] if business_correct else ["expected_runtime_abstention"]
            business_quality = "correct_abstention" if business_correct else "failed"
        else:
            report_ok, report_quality_errors = _validate_logit_report(
                report_payload,
                selected_candidate=selected,
                candidate_rows=candidate_rows,
            )
            business_correct = bool(
                runtime_payload.get("runtime_completed")
                and selected == case.gold_candidate
                and report_ok
            )
            business_quality = "passed" if business_correct else "failed"
        status = "completed" if business_correct else "failed"
        trace = {
            "slot_id": slot_id,
            "module": "logit",
            "case_id": case.case_id,
            "condition": policy,
            "policy": policy,
            "scored": scored,
            "warmup_namespace": "scored" if scored else "calibration-only",
            "gold_outcome": case.gold_outcome,
            "gold_candidate": case.gold_candidate,
            "selected_candidate": selected,
            "correct": business_correct,
            "choice_attempts": [
                {
                    "stage": item["stage"],
                    "attempt_id": item["attempt_id"],
                    "result_text": item["result_text"],
                    "extraction": item["extraction_payload"],
                    "extraction_payload": item["extraction_payload"],
                    "candidate_id": item["candidate_id"],
                    "observation": item["observation"],
                }
                for item in ordered_states
            ],
            "provider_requests": provider_observations,
            "report": report_payload,
            "report_observation": report_observation,
            "report_quality_errors": report_quality_errors,
            "runtime_action": runtime_action,
            "runtime_action_trace": review_records,
            "runtime": runtime_payload,
            "runtime_error": runtime_error,
            "expansion_reason": expansion_reason,
            "expanded": expanded,
            "request_count": len(provider_observations),
            "logical_input_tokens": sum(int(item.get("prompt_tokens_exact", 0)) for item in provider_observations),
            "logical_output_tokens": sum(int(item.get("usage", {}).get("completion_tokens", 0)) for item in provider_observations),
            "decision_contract": {"tau": 0.10, "other_mass_limit": 0.20, "max_choice_attempts": 2, "max_replans": 1},
        }
        (trace_dir / f"{case.case_id}-{policy}.json").write_text(json.dumps(trace, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        self.record(trace | {
            "status": status,
            "business_quality": business_quality,
            "exact_available": exact_available,
        })
        return {
            "slot_id": slot_id,
            "quality": business_correct,
            "status": status,
            "exact_available": exact_available,
            "runtime_completed": bool(runtime_payload.get("runtime_completed")),
            "gate_ready": bool(business_correct and exact_available and runtime_result is not None),
            "expanded": expanded,
        }

    def run_logit_warmup(
        self,
        case: Any,
        client: OpenAICompatibleLLMClient,
        codec: VllmTokenCodec,
    ) -> list[dict[str, Any]]:
        """Issue exactly two non-scored choice requests on an isolated calibration case."""
        candidates = tuple(str(item["candidate_id"]) for item in case.candidates) + ("insufficient_evidence",)
        surface = CandidateSurfaceV2.from_candidate_ids(candidates)
        schema = _json_schema({"choice_code": {"type": "string", "enum": list(surface.aliases)}})
        observations: list[dict[str, Any]] = []
        for stage, view in (("compact", case.compact_view), ("full", case.full_view)):
            candidate_lines = "\n".join(
                f"{alias}: {candidate['candidate_id']} ({candidate['label']})"
                for alias, candidate in zip(surface.aliases, case.candidates + ({"candidate_id": "insufficient_evidence", "label": "insufficient evidence"},))
            )
            messages = [ChatMessage("user", f"Calibration choice only. Select one evidence candidate.\nQuestion: {case.question}\nView: {view}\nCandidates:\n{candidate_lines}")]
            token_ids = _encode_prompt_tokens(codec, messages)
            result, observation = _complete(client, messages, purpose="executor", schema=schema)
            raw_observation = observation | {
                "raw_top_logprobs": _serialize_top_logprobs(result.top_logprobs) if result else [],
                "prompt_tokens_exact": len(token_ids),
                "prompt_token_digest": sha256_digest(list(token_ids)),
            }
            _append_jsonl(self.run_root / "warmup-observations.jsonl", {
                "module": "logit",
                "warmup": True,
                "stage": stage,
                "case_id": case.case_id,
                "observation": raw_observation,
            })
            extraction = None
            extraction_payload = None
            extraction_error = None
            token_byte_alignment = {"source": "provider_bytes", "status": "no_response"}
            if result:
                try:
                    extraction, token_byte_alignment = _extract_utility_choice_logit_state(
                        completion_text=result.text,
                        top_logprobs=result.top_logprobs,
                        candidate_surface=surface,
                        request_id=f"warmup-{case.case_id}-{stage}",
                        attempt_id=f"warmup-{case.case_id}-{stage}",
                    )
                    extraction_payload = _logit_extraction_payload(extraction, surface)
                except IndexError as exc:
                    extraction_error = {"type": type(exc).__name__, "message": str(exc)}
                    token_byte_alignment = {"source": "extractor", "status": "error", "reason": str(exc)}
            payload = {
                "module": "logit",
                "warmup": True,
                "stage": stage,
                "case_id": case.case_id,
                "observation": raw_observation,
                "extraction": extraction_payload,
                "token_byte_alignment": token_byte_alignment,
                "extraction_error": extraction_error,
                "exact_available": bool(extraction_payload and extraction_payload.get("available")),
            }
            observations.append(payload)
            with (self.run_root / "warmup.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
            self.log(f"warmup module=logit stage={stage} exact_available={payload['exact_available']}")
        return observations

    def _reuse_saved_logit_warmup(self, case: Any) -> list[dict[str, Any]] | None:
        if not self.resume_enabled:
            return None
        source_path = self.run_root / "warmup-observations.jsonl"
        if not source_path.is_file():
            return None
        saved: dict[str, dict[str, Any]] = {}
        try:
            for line in source_path.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                if not isinstance(record, Mapping):
                    return None
                if record.get("module") != "logit" or record.get("case_id") != case.case_id:
                    continue
                stage = str(record.get("stage", ""))
                if stage not in {"compact", "full"} or stage in saved:
                    return None
                observation = record.get("observation")
                if not isinstance(observation, Mapping) or observation.get("status") != "response":
                    return None
                raw_logprobs = observation.get("raw_top_logprobs")
                if not isinstance(raw_logprobs, list) or not raw_logprobs:
                    return None
                saved[stage] = dict(record)
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        if set(saved) != {"compact", "full"}:
            return None

        candidates = tuple(str(item["candidate_id"]) for item in case.candidates) + ("insufficient_evidence",)
        surface = CandidateSurfaceV2.from_candidate_ids(candidates)
        reanalysis_path = self.run_root / f"warmup-reanalysis-{self.execution_id}.jsonl"
        results: list[dict[str, Any]] = []
        for stage in ("compact", "full"):
            observation = saved[stage]["observation"]
            extraction_payload = None
            extraction_error = None
            token_byte_alignment = {"source": "provider_bytes", "status": "unavailable"}
            try:
                extraction, token_byte_alignment = _extract_utility_choice_logit_state(
                    completion_text=str(observation.get("text", "")),
                    top_logprobs=observation["raw_top_logprobs"],
                    candidate_surface=surface,
                    request_id=f"resume-warmup-{case.case_id}-{stage}",
                    attempt_id=f"resume-warmup-{case.case_id}-{stage}",
                )
                extraction_payload = _logit_extraction_payload(extraction, surface)
            except Exception as exc:
                extraction_error = {"type": type(exc).__name__, "message": str(exc)}
                token_byte_alignment = {"source": "extractor", "status": "error", "reason": str(exc)}
            result = {
                "module": "logit",
                "warmup": True,
                "stage": stage,
                "case_id": case.case_id,
                "request_reused": True,
                "source_observation_path": str(source_path),
                "source_observation_digest": sha256_digest(observation),
                "extraction": extraction_payload,
                "token_byte_alignment": token_byte_alignment,
                "extraction_error": extraction_error,
                "exact_available": bool(extraction_payload and extraction_payload.get("available")),
            }
            _append_jsonl(reanalysis_path, result)
            results.append(result)
            self.log(f"warmup module=logit stage={stage} source=resume_local_reanalysis exact_available={result['exact_available']}")
        return results

    def run_kv(
        self,
        case: Any,
        condition: str,
        client: VllmKVClient,
        codec: VllmTokenCodec,
        *,
        delegate: OpenAICompatibleLLMClient,
        scored: bool = True,
    ) -> dict[str, Any]:
        slot_id = f"{case.case_id}:{condition}"
        started = time.perf_counter_ns()
        observer = _KVRunObserver(client)
        role_client: EngineLocalKVRoleClient | None = None
        runtime_result: Any = None
        runtime_error: dict[str, str] | None = None
        provider_errors: list[dict[str, str]] = []
        repair_observations: list[dict[str, Any]] = []
        quality_errors: list[str] = ["runtime_not_completed"]
        parsed: dict[str, Any] | None = None
        health_before: dict[str, Any] = {}
        health_after: dict[str, Any] = {}

        namespace_info = build_cache_namespace(
            case,
            codec,
            run_id=self.execution_id,
            scope=f"kv-pair:{case.case_id}",
        )
        namespace = str(namespace_info["namespace"])
        namespace_contract_ok = int(namespace_info["prefix_token_count"]) == case.target_prefix_tokens

        def executor_handler(request: Any) -> ProviderCandidate:
            messages = _executor_messages(
                case,
                "shared",
                request.bound_grant.grant.attempt_id,
                namespace=namespace,
            )
            token_ids = _encode_prompt_tokens(codec, messages)
            if len(token_ids) + 512 + 64 > MAX_MODEL_LEN:
                return ProviderCandidate(False, "failure", error_code="provider_prompt_budget_exceeded")
            try:
                result = asyncio.run(role_client.complete(
                    messages,
                    purpose="executor",
                    temperature=0.0,
                    response_schema=_executor_schema(),
                ))
            except Exception as exc:
                provider_errors.append({"role": "executor", "type": type(exc).__name__, "message": str(exc)})
                return ProviderCandidate(False, "failure", error_code="executor_provider_error")
            return _parse_transform_program(request=request, raw_text=result.text)

        def summarizer_handler(request: Any) -> ProviderCandidate:
            messages = _summarizer_messages(case, "shared", request, namespace=namespace)
            token_ids = _encode_prompt_tokens(codec, messages)
            if len(token_ids) + 384 + 64 > MAX_MODEL_LEN:
                return ProviderCandidate(False, "failure", error_code="summarizer_prompt_budget_exceeded")
            try:
                result = asyncio.run(role_client.complete(
                    messages,
                    purpose="summarizer",
                    temperature=0.0,
                    response_schema=_report_schema(case),
                ))
            except Exception as exc:
                provider_errors.append({"role": "summarizer", "type": type(exc).__name__, "message": str(exc)})
                return ProviderCandidate(False, "failure", error_code="summarizer_provider_error")
            return _claim_candidate_from_report(request=request, raw_text=result.text)[0]

        repair_factory = _executor_repair_factory(
            case=case,
            layout="shared",
            namespace=namespace,
            client=delegate,
            codec=codec,
            observations=repair_observations,
        )

        try:
            if condition not in {"full_replay", "continuation"}:
                raise UtilitySuiteError(f"unsupported_kv_condition:{condition}")
            if case.definition.target_min_tokens % BLOCK_SIZE:
                raise UtilitySuiteError("kv_parent_cap_not_block_aligned")
            health_before = client.health()
            health_issues = _kv_health_issues(health_before, require_empty=True)
            if int(health_before.get("block_size", 0) or 0) != BLOCK_SIZE:
                health_issues.append("block_size_contract_mismatch")
            if health_issues:
                raise UtilitySuiteError("kv_health_contract_failed:" + ",".join(health_issues))
            role_client = EngineLocalKVRoleClient(
                delegate=delegate,
                config=EngineLocalKVRoleClientConfig(
                    mode=condition,
                    task_id=slot_id,
                    audit_path=self.run_root / "kv-audits" / self.execution_id / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', slot_id)}.json",
                    model=MODEL,
                    parent_tokens=case.definition.target_min_tokens,
                    ttl_s=180,
                    seed=7,
                    executor_max_tokens=512,
                    summarizer_max_tokens=384,
                    executor_response_schema=_executor_schema(),
                    summarizer_response_schema=_report_schema(case),
                    profile="kv_continuation",
                    shared_prefix_text=case.shared_prefix_text(namespace),
                    kv_base_url=KV_BASE_URL,
                    kv_timeout_s=480.0,
                    tokenizer_timeout_s=120.0,
                    chat_template_kwargs={"enable_thinking": False},
                ),
                kv_client=observer,
                token_codec=codec,
            )
            runtime_result = run_utility_runtime(
                slot_id=slot_id,
                run_id=self.run_root.name,
                runtime_root=self.run_root / "runtime" / self.execution_id / re.sub(r"[^A-Za-z0-9_.-]+", "_", slot_id),
                workspace_root=self.run_root / "workspaces" / self.execution_id,
                task_question=case.definition.question,
                task_family=case.definition.business,
                task_arguments={"case_id": case.case_id, "condition": condition, "source_digest": case.source_digest},
                source_hash=case.source_digest,
                rows=tuple(dict(row) for row in case.source_rows),
                additional_evidence=tuple({**rule, "text": json.dumps(rule, ensure_ascii=False, sort_keys=True)} for rule in case.rules),
                input_fields=_runtime_input_schema(case.source_rows),
                output_schema=_runtime_output_schema(case),
                executor_handler=executor_handler,
                summarizer_handler=summarizer_handler,
                transform_program_repair_factory=repair_factory,
            )
            claim_sets = list(runtime_result.context.claim_sets.values())
            for claim_set in claim_sets:
                for claim in claim_set.claims:
                    try:
                        parsed = extract_json_object(claim.claim_text)
                    except Exception:
                        parsed = None
                    if parsed is not None:
                        break
                if parsed is not None:
                    break
            quality, quality_errors = _validate_report(case, parsed)
        except Exception as exc:
            runtime_error = {"type": type(exc).__name__, "message": str(exc)}
            quality = False
            quality_errors = ["runtime_or_kv_execution_failed"]
        finally:
            if role_client is not None:
                try:
                    role_client.close()
                except Exception as exc:
                    provider_errors.append({"role": "kv_cleanup", "type": type(exc).__name__, "message": str(exc)})
            try:
                health_after = client.health()
            except Exception as exc:
                health_after = {"status": "unavailable", "error_type": type(exc).__name__, "error": str(exc)}

        audit = role_client.audit_payload if role_client is not None else {}
        runtime_payload = _runtime_evidence(runtime_result) if runtime_result is not None else {
            "runtime_completed": False,
            "execution_path": "RuntimeDriver.run_mode(adaptive_bounded)->AdaptiveMainlineRunner->AdaptiveRuntimeEngine->AdaptiveCapabilityDispatcher",
            "dispatches": [],
            "attempts": [],
            "artifacts": [],
            "candidate_review_records": [],
        }
        produce_events = [item for item in observer.events if item.get("event") == "produce"]
        continue_events = [item for item in observer.events if item.get("event") == "continue"]
        release_events = [item for item in observer.events if item.get("event") == "release"]
        producer_event = produce_events[-1] if produce_events else {}
        consumer_event = continue_events[-1] if continue_events else {}
        producer_response = producer_event.get("response", {})
        consumer_response = consumer_event.get("response", {})
        producer_telemetry = producer_response.get("telemetry", {}) if isinstance(producer_response, Mapping) else {}
        consumer_telemetry = consumer_response.get("telemetry", {}) if isinstance(consumer_response, Mapping) else {}
        handle = producer_response.get("handle", {}) if isinstance(producer_response, Mapping) else {}
        forward_proof = consumer_response.get("forward_proof", {}) if isinstance(consumer_response, Mapping) else {}
        release_clean = all(
            isinstance(item.get("response"), Mapping)
            and item["response"].get("status") in {"released", "success"}
            for item in release_events
        )
        registry_clean = (
            health_after.get("status") == "ready"
            and int(health_after.get("registry_entries", -1) or 0) == 0
            and int(health_after.get("registry_bytes", -1) or 0) == 0
        )
        engine_stable = bool(
            health_before.get("engine_id")
            and health_before.get("engine_id") == health_after.get("engine_id")
            and health_before.get("engine_generation") == health_after.get("engine_generation")
        )
        if condition == "continuation":
            kv_mechanism = bool(
                len(produce_events) == 1
                and len(continue_events) == 1
                and len(release_events) == 1
                and audit.get("capture_count") == 1
                and audit.get("load_count") == 1
                and producer_response.get("status") == "success"
                and bool(producer_response.get("handle_id"))
                and isinstance(handle, Mapping)
                and handle.get("status") == "ready"
                and int(consumer_telemetry.get("connector_load_count", 0) or 0) == 1
                and int(consumer_telemetry.get("inherited_kv_tokens", 0) or 0) == case.definition.target_min_tokens
                and int(consumer_telemetry.get("computed_prefill_tokens", 0) or 0) > 0
                and int(forward_proof.get("connector_load_count", 0) or 0) == 1
                and int(forward_proof.get("computed_prefill_tokens", 0) or 0) == int(consumer_telemetry.get("computed_prefill_tokens", 0) or 0)
                and bool(consumer_telemetry.get("forward_proof_hash"))
                and engine_stable
                and release_clean
                and registry_clean
            )
        else:
            kv_mechanism = bool(
                len(produce_events) == 1
                and len(continue_events) == 1
                and not release_events
                and audit.get("capture_count") == 0
                and audit.get("load_count") == 0
                and not producer_response.get("handle_id")
                and int(consumer_telemetry.get("inherited_kv_tokens", -1) or 0) == 0
                and int(consumer_telemetry.get("connector_load_count", -1) or 0) == 0
                and not forward_proof
                and engine_stable
                and registry_clean
            )
        runtime_ok = bool(runtime_result is not None and runtime_result.runtime.completed)
        status = "completed" if runtime_ok else "failed"
        payload = {
            "status": status,
            "quality": quality,
            "quality_errors": quality_errors,
            "output": parsed,
            "runtime": runtime_payload,
            "runtime_error": runtime_error,
            "provider_errors": provider_errors,
            "repair_requests": repair_observations,
            "role_client_audit": audit,
            "provider_request_events": role_client.local_request_events if role_client is not None else [],
            "kv_receipts": observer.events,
            "health_before": health_before,
            "health_after": health_after,
            "producer_computed_tokens": producer_telemetry.get("computed_prefill_tokens"),
            "producer_logical_tokens": producer_telemetry.get("logical_prompt_tokens"),
            "producer_output_tokens": producer_telemetry.get("generated_tokens"),
            "capture_bytes": handle.get("kv_bytes_actual", producer_telemetry.get("kv_bytes_actual")) if isinstance(handle, Mapping) else producer_telemetry.get("kv_bytes_actual"),
            "store_ms": producer_telemetry.get("kv_store_ms"),
            "consumer_logical_tokens": consumer_telemetry.get("logical_prompt_tokens"),
            "consumer_computed_tokens": consumer_telemetry.get("computed_prefill_tokens"),
            "consumer_inherited_tokens": consumer_telemetry.get("inherited_kv_tokens"),
            "consumer_output_tokens": consumer_telemetry.get("generated_tokens"),
            "consumer_ttft_ms": consumer_event.get("client_ttft_ms"),
            "consumer_request_wall_ms": consumer_event.get("client_wall_ms"),
            "load_ms": consumer_telemetry.get("kv_load_ms"),
            "forward_proof": forward_proof,
            "engine_identity": {
                "engine_id": health_before.get("engine_id"),
                "engine_generation": health_before.get("engine_generation"),
                "compatibility_digest": health_before.get("compatibility_digest"),
                "tokenizer_digest": health_before.get("tokenizer_digest"),
            },
            "release_results": [item.get("response", {}) for item in release_events],
            "release_clean": release_clean,
            "registry_clean": registry_clean,
            "mechanism_available": bool(kv_mechanism and namespace_contract_ok),
            "cache_namespace": namespace,
            "namespace_prefix_token_count": namespace_info["prefix_token_count"],
            "namespace_prefix_token_digest": namespace_info["prefix_token_digest"],
            "namespace_contract_ok": namespace_contract_ok,
            "repair_prompt_tokens": sum(
                int(item.get("usage", {}).get("prompt_tokens", 0) or 0)
                for item in repair_observations
                if item.get("status") == "response" and isinstance(item.get("usage"), Mapping)
            ),
            "repair_output_tokens": sum(
                int(item.get("usage", {}).get("completion_tokens", 0) or 0)
                for item in repair_observations
                if item.get("status") == "response" and isinstance(item.get("usage"), Mapping)
            ),
            "repair_request_count": len(repair_observations),
            "total_computed_tokens": (
                sum(int(item.get("computed_prefill_tokens", 0) or 0) for item in audit.get("producer_calls", ()))
                + sum(int(item.get("telemetry", {}).get("computed_prefill_tokens", 0) or 0) for item in audit.get("consumer_calls", ()))
                + sum(
                    int(item.get("usage", {}).get("prompt_tokens", 0) or 0)
                    for item in repair_observations
                    if item.get("status") == "response" and isinstance(item.get("usage"), Mapping)
                )
            ),
            "task_wall_ms": (time.perf_counter_ns() - started) / 1_000_000.0,
        }
        payload["gate_ready"] = bool(runtime_ok and quality and kv_mechanism and namespace_contract_ok)
        self.record({"slot_id": slot_id, "module": "kv", "case_id": case.case_id, "condition": condition, "scored": scored, "warmup_namespace": "scored" if scored else "calibration-only", **payload})
        return payload

    def _stop_owned_service(self, env_file: Path, expected: dict[str, Any], label: str) -> dict[str, Any]:
        current = _manager_identity(env_file)
        if current.get("mode") != expected.get("mode") or current.get("pid") != expected.get("pid"):
            raise UtilitySuiteError(
                f"{label}_ownership_changed:expected={expected.get('mode')}:{expected.get('pid')}:"
                f"actual={current.get('mode')}:{current.get('pid')}"
            )
        stopped = _run_capture(["env", f"STATEBUS_VLLM_ENV_FILE={env_file}", str(MANAGER), "stop"], timeout_s=60)
        (self.service_dir / f"{label}-stop.json").write_text(json.dumps(stopped, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if stopped.get("returncode") != 0:
            raise UtilitySuiteError(f"{label}_stop_failed")
        return stopped

    def _restore_standard_service(self, kv_env: Path | None) -> None:
        """Stop only the run-owned KV service, then verify the original standard."""
        self.standard_restored = "false"
        evidence: dict[str, Any] = {}
        current_standard = _manager_identity(STANDARD_ENV)
        current_kv = _manager_identity(kv_env) if kv_env is not None and kv_env.exists() else None
        evidence["observed_before"] = {"standard": current_standard, "kv": current_kv}
        (self.service_dir / "restore-observed.json").write_text(
            json.dumps(evidence["observed_before"], indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        try:
            if current_kv is not None and current_kv.get("pid"):
                expected_kv = self._kv_identity
                if expected_kv is None or current_kv.get("mode") != "kv" or current_kv.get("pid") != expected_kv.get("pid"):
                    raise UtilitySuiteError("kv_restore_owner_unknown")
                try:
                    evidence["kv_log"] = _archive_service_log(self.service_dir, kv_env, "kv-before-standard-restore")
                except UtilitySuiteError as exc:
                    evidence["kv_log_archive_error"] = str(exc)
                self._stop_owned_service(kv_env, expected_kv, "kv")
            elif current_kv is not None and current_kv.get("healthy"):
                raise UtilitySuiteError("kv_restore_owner_unknown")

            current_standard = _manager_identity(STANDARD_ENV)
            standard_owned_pid = self._standard_identity.get("pid") if self._standard_identity else None
            if current_standard.get("pid") and (
                current_standard.get("mode") != "standard"
                or standard_owned_pid != current_standard.get("pid")
            ):
                raise UtilitySuiteError("standard_restore_owner_unknown")
            if not (current_standard.get("mode") == "standard" and current_standard.get("pid") and current_standard.get("healthy")):
                restored = _run_capture(["setsid", "--wait", "env", f"STATEBUS_VLLM_ENV_FILE={STANDARD_ENV}", str(MANAGER), "start"], timeout_s=960)
                evidence["standard_start"] = restored
                (self.service_dir / "standard-restore.json").write_text(json.dumps(restored, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                if restored.get("returncode") != 0:
                    raise UtilitySuiteError("standard_restore_failed")

            verification = _verify_standard_endpoints()
            evidence["verification"] = verification
            (self.service_dir / "standard-restore-verification.json").write_text(
                json.dumps(verification, indent=2, ensure_ascii=False, default=str) + "\n",
                encoding="utf-8",
            )
            if not verification.get("passed"):
                raise UtilitySuiteError(str(verification.get("reason", "standard_restore_verification_failed")))
            self.standard_restored = "true"
        except Exception as exc:
            evidence["error"] = f"{type(exc).__name__}:{exc}"
            self.standard_restored = "false"
            raise
        finally:
            evidence["standard_restored"] = self.standard_restored
            evidence["standard_after"] = _manager_identity(STANDARD_ENV)
            (self.service_dir / "restore-evidence.json").write_text(
                json.dumps(evidence, indent=2, ensure_ascii=False, default=str) + "\n",
                encoding="utf-8",
            )

    def _verify_standard_unchanged(self) -> None:
        original = self._standard_identity
        current = _manager_identity(STANDARD_ENV)
        unchanged = bool(
            original
            and original.get("mode") == "standard"
            and original.get("healthy")
            and current.get("mode") == "standard"
            and current.get("healthy")
            and original.get("pid") == current.get("pid")
        )
        self.standard_restored = "unchanged" if unchanged else "false"
        evidence = {"original": original, "current": current, "standard_restored": self.standard_restored}
        (self.service_dir / "standard-unchanged-verification.json").write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        if not unchanged:
            raise UtilitySuiteError("standard_service_changed_without_utility_switch")

    def run_live(self, *, phase: str = "all", smoke_only: bool = False) -> dict[str, Any]:
        client = _llm_client()
        standard_codec = _tokenizer_codec(timeout_s=120.0)
        summary: dict[str, Any] = {"standard": [], "kv": [], "logit": [], "warmup": [], "rechecks": [], "status": "live_completed"}
        run_apc_phase = phase in {"all", "standard", "apc"}
        run_logit_phase = phase in {"all", "standard", "logit"}
        run_kv_phase = phase in {"all", "kv"}
        kv_env: Path | None = None
        self._install_signal_handlers()
        apc_already_complete = self.all_module_positions_reusable("apc")
        logit_already_complete = self.all_module_positions_reusable("logit")
        kv_already_complete = self.all_module_positions_reusable("kv")

        def checkpoint() -> None:
            self._check_budget()

        try:
            self._standard_identity = _manager_identity(STANDARD_ENV)
            if self._standard_identity.get("mode") != "standard" or not self._standard_identity.get("healthy"):
                self.standard_restored = "false"
                raise UtilitySuiteError("standard_service_not_healthy_at_live_start")
            self.standard_restored = "unchanged"
            if self.target_slot_id:
                target_module, case_id, condition = _target_slot_identity(self.target_slot_id)
                if target_module == "apc":
                    case = next((item for item in self.taskpack.cases if item.case_id == case_id), None)
                else:
                    case = next((item for item in self.taskpack.logit_cases if item.case_id == case_id), None)
                if case is None:
                    raise UtilitySuiteError("targeted_recheck_case_unavailable")
                checkpoint()
                if target_module == "apc":
                    result = self._run_targeted_apc_slot(case, condition.removeprefix("apc_on_"), client, standard_codec)
                    result_bucket = "standard"
                else:
                    result = self._run_targeted_logit_slot(case, condition, client, standard_codec)
                    result_bucket = "logit"
                summary[result_bucket].append(result)
                summary["targeted_recheck"] = {
                    "slot_id": self.target_slot_id,
                    "gate_ready": bool(result.get("gate_ready")),
                    "status": result.get("status"),
                }
                self.record({
                    "event": "targeted_recheck",
                    "module": target_module,
                    "target_slot_id": self.target_slot_id,
                    "passed": bool(result.get("gate_ready")),
                })
                return summary
            try:
                apc_warmup_ready = True
                if run_apc_phase and not smoke_only and not apc_already_complete:
                    warmup_case = self.taskpack.calibration_case
                    apc_warmup_results: list[dict[str, Any]] = []
                    warmup_namespaces = self._apc_namespace_pair(
                        warmup_case,
                        ("independent", "shared"),
                        standard_codec,
                    )
                    for layout in ("independent", "shared"):
                        checkpoint()
                        namespace_info = warmup_namespaces[layout]
                        result = self.run_apc(
                            warmup_case,
                            layout,
                            client,
                            standard_codec,
                            namespace=namespace_info["namespace"],
                            namespace_prefix_token_count=namespace_info["prefix_token_count"],
                            namespace_prefix_token_digest=namespace_info["prefix_token_digest"],
                            namespace_pair_contract={
                                "different_values": len({item["namespace"] for item in warmup_namespaces.values()}) == 2,
                                "equal_prefix_token_counts": len({item["prefix_token_count"] for item in warmup_namespaces.values()}) == 1,
                                "condition_scoped": True,
                            },
                            scored=False,
                        )
                        apc_warmup_results.append(result)
                        summary["warmup"].append({"module": "apc", "case_id": warmup_case.case_id, "condition": layout, **result})
                    apc_warmup_ready = _apc_calibration_gate_ready(apc_warmup_results)
                    self.record({
                        "event": "calibration_gate",
                        "module": "apc",
                        "passed": apc_warmup_ready,
                        "positions": [item["slot_id"] for item in apc_warmup_results],
                    })
                if run_logit_phase and not smoke_only and not logit_already_complete:
                    logit_warmup = self._reuse_saved_logit_warmup(self.taskpack.logit_calibration_case)
                    if logit_warmup is None:
                        checkpoint()
                        logit_warmup = self.run_logit_warmup(
                            self.taskpack.logit_calibration_case,
                            client,
                            standard_codec,
                        )
                    summary["warmup"].extend(logit_warmup)
                    logit_warmup_ready = len(logit_warmup) == 2 and all(
                        item.get("exact_available") for item in logit_warmup
                    )
                else:
                    logit_warmup_ready = True
                apc_enabled = run_apc_phase and apc_warmup_ready
                logit_enabled = run_logit_phase and logit_warmup_ready
                if run_apc_phase and apc_warmup_ready:
                    checkpoint()
                    gate_results = self._run_apc_group(self.taskpack.cases[0], ("independent", "shared"), client, standard_codec)
                    summary["standard"].extend(gate_results)
                    apc_enabled = all(bool(item.get("gate_ready")) for item in gate_results)
                    self.record({"event": "smoke_gate", "module": "apc", "passed": apc_enabled, "positions": [item["slot_id"] for item in gate_results]})
                    if not apc_enabled:
                        summary.setdefault("blocked_modules", {})["apc"] = "standard_gate_failed"
                elif run_apc_phase:
                    summary.setdefault("blocked_modules", {})["apc"] = "calibration_warmup_failed"
                    self.record({"event": "smoke_gate", "module": "apc", "passed": False, "reason": "calibration_warmup_failed"})
                if run_logit_phase and not logit_warmup_ready:
                    summary.setdefault("blocked_modules", {})["logit"] = "exact_choice_logprobs_unavailable_in_calibration"
                    for case in self.taskpack.logit_cases:
                        policies = _policy_order_for_case(self.taskpack.logit_cases, case.case_id)
                        existing = self._resume_group_records("logit", case.case_id, policies)
                        if existing is not None:
                            summary["logit"].extend(self._reused_result(record) for record in existing)
                            continue
                        for policy in policies:
                            slot_id = f"{case.case_id}:{policy}"
                            blocked = {
                                "slot_id": slot_id,
                                "module": "logit",
                                "case_id": case.case_id,
                                "condition": policy,
                                "policy": policy,
                                "scored": True,
                                "status": "unavailable",
                                "business_quality": "unavailable_exact_logprobs",
                                "exact_available": False,
                                "provider_requests": [],
                            }
                            self.record(blocked)
                            summary["logit"].append(blocked)
                elif run_logit_phase:
                    checkpoint()
                    gate_results = self._run_logit_group(
                        self.taskpack.logit_cases[0],
                        _policy_order_for_case(self.taskpack.logit_cases, self.taskpack.logit_cases[0].case_id),
                        client,
                        standard_codec,
                    )
                    summary["logit"].extend(gate_results)
                    logit_enabled = all(bool(item.get("gate_ready")) for item in gate_results)
                    self.record({"event": "smoke_gate", "module": "logit", "passed": logit_enabled, "positions": [item["slot_id"] for item in gate_results]})
                    if not logit_enabled:
                        summary.setdefault("blocked_modules", {})["logit"] = "standard_gate_failed"
                if apc_enabled and not smoke_only:
                    for case_index, case in enumerate(self.taskpack.cases[1:], start=1):
                        layouts = ("independent", "shared") if case_index % 2 == 0 else ("shared", "independent")
                        checkpoint()
                        summary["standard"].extend(self._run_apc_group(case, layouts, client, standard_codec))
                if logit_enabled and not smoke_only:
                    for case_index, case in enumerate(self.taskpack.logit_cases[1:], start=1):
                        checkpoint()
                        summary["logit"].extend(self._run_logit_group(
                            case,
                            _policy_order_for_case(self.taskpack.logit_cases, case.case_id),
                            client,
                            standard_codec,
                        ))
                standard_codec.close()
                if not run_kv_phase or kv_already_complete:
                    self.standard_restored = "unchanged"
                    if summary.get("blocked_modules"):
                        summary["status"] = "incomplete_gate"
                    return summary

                checkpoint()
                kv_env = self.run_root / "service" / "vllm.env.kv.local"
                text = KV_ENV_TEMPLATE.read_text(encoding="utf-8")
                text += f'\nexport STATEBUS_KV_ENGINE_GENERATION="utility-{self.execution_id}"\nexport STATEBUS_VLLM_RUNTIME_DIR="{self.run_root / "service" / f"kv-runtime-{self.execution_id}"}"\n'
                kv_env.write_text(text, encoding="utf-8")
                standard_at_switch = _manager_identity(STANDARD_ENV)
                if (
                    standard_at_switch.get("mode") != "standard"
                    or not standard_at_switch.get("healthy")
                    or standard_at_switch.get("pid") != self._standard_identity.get("pid")
                ):
                    raise UtilitySuiteError("standard_service_changed_before_kv_switch")
                (self.service_dir / "standard-manager-identity.json").write_text(
                    json.dumps({"original": self._standard_identity, "at_switch": standard_at_switch}, indent=2, ensure_ascii=False, default=str) + "\n",
                    encoding="utf-8",
                )
                standard_log = _archive_service_log(self.service_dir, STANDARD_ENV, "standard-before-kv")
                _append_jsonl(self.service_dir / "service-log-archives.jsonl", {"mode": "standard", **standard_log})
                # Once this flag is set, every exit path enters the ownership
                # checked restore routine, including a failed KV start.
                self._switch_started = True
                self._stop_owned_service(STANDARD_ENV, self._standard_identity, "standard")
                started = _run_capture(["setsid", "--wait", "env", f"STATEBUS_VLLM_ENV_FILE={kv_env}", str(MANAGER), "start"], timeout_s=960)
                (self.service_dir / "kv-start.json").write_text(json.dumps(started, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                self._kv_identity = _manager_identity(kv_env)
                (self.service_dir / "kv-manager-identity.json").write_text(json.dumps(self._kv_identity, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
                if started.get("returncode") != 0 or self._kv_identity.get("mode") != "kv" or not self._kv_identity.get("healthy"):
                    raise UtilitySuiteError("kv_service_start_failed")
                for condition in ("full_replay", "continuation"):
                    checkpoint()
                    warmup = self._run_kv_position(self.taskpack.calibration_case, condition, delegate=client, scored=False)
                    summary["warmup"].append({"module": "kv", "case_id": self.taskpack.calibration_case.case_id, "condition": condition, **warmup})
                kv_warmup_ready = all(
                    item.get("status") == "completed" and item.get("quality") and item.get("mechanism_available")
                    for item in summary["warmup"] if item.get("module") == "kv"
                )
                if not kv_warmup_ready:
                    summary.setdefault("blocked_modules", {})["kv"] = "kv_calibration_warmup_failed"
                    summary["status"] = "incomplete_gate"
                    return summary
                checkpoint()
                gate_results = self._run_kv_group(self.taskpack.cases[0], ("full_replay", "continuation"), delegate=client)
                summary["kv"].extend(gate_results)
                kv_gate_passed = all(bool(item.get("gate_ready")) for item in gate_results)
                self.record({"event": "smoke_gate", "module": "kv", "passed": kv_gate_passed, "positions": [item["slot_id"] for item in gate_results]})
                if not kv_gate_passed:
                    summary.setdefault("blocked_modules", {})["kv"] = "kv_gate_failed"
                if kv_gate_passed and not smoke_only:
                    for case_index, case in enumerate(self.taskpack.cases[1:], start=1):
                        conditions = ("full_replay", "continuation") if case_index % 2 == 0 else ("continuation", "full_replay")
                        checkpoint()
                        summary["kv"].extend(self._run_kv_group(case, conditions, delegate=client))
            except UtilitySuiteBudgetExceeded as exc:
                summary.update({"status": "incomplete_budget", "budget_error": str(exc), "elapsed_s": time.monotonic() - self.started})
                return summary
        finally:
            try:
                if self._switch_started:
                    self._restore_standard_service(kv_env)
                else:
                    self._verify_standard_unchanged()
            finally:
                try:
                    standard_codec.close()
                finally:
                    self._restore_signal_handlers()
        if summary.get("blocked_modules") and summary.get("status") == "live_completed":
            summary["status"] = "incomplete_gate"
        return summary

    def _run_kv_position(
        self,
        case: Any,
        condition: str,
        *,
        delegate: OpenAICompatibleLLMClient,
        scored: bool,
    ) -> dict[str, Any]:
        client = VllmKVClient(
            VllmKVClientConfig(base_url=KV_BASE_URL, token_file=str(KV_TOKEN), timeout_s=480.0)
        )
        codec = _tokenizer_codec(timeout_s=120.0)
        try:
            return self.run_kv(case, condition, client, codec, delegate=delegate, scored=scored)
        finally:
            client.close()
            codec.close()


def summarize_records(run_root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    records_path = run_root / "records.jsonl"
    if records_path.exists():
        for line in records_path.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    expected_by_module: dict[str, set[str]] = {"apc": set(), "logit": set(), "kv": set()}
    for item in PLAN_POSITIONS:
        if item["module"] == "apc":
            slot_id = f"{item['case_id']}:{item['condition']}"
        else:
            slot_id = f"{item['case_id']}:{item['condition']}"
        expected_by_module[str(item["module"])].add(slot_id)
    terminal_statuses = {"completed", "failed", "refused", "unavailable"}

    def _record_business_quality_passed(record: Mapping[str, Any]) -> bool:
        """Accept the quality field used by KV records as the same gate.

        APC and Logit records expose the utility gate as ``business_quality``;
        the KV adapter records the equivalent result as a boolean ``quality``.
        Both are runtime-owned quality observations and must contribute to the
        same aggregate.
        """
        business_quality = record.get("business_quality")
        return business_quality in {"passed", "correct_abstention"} or (
            business_quality in (None, "") and record.get("quality") is True
        )

    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        slot_id = str(record.get("slot_id", ""))
        module = str(record.get("module", ""))
        if slot_id in expected_by_module.get(module, set()) and bool(record.get("scored", True)):
            latest[slot_id] = record
    by_module: dict[str, dict[str, int]] = {}
    slot_counts: dict[str, int] = {}
    position_counts: dict[str, dict[str, int]] = {}
    not_started: dict[str, int] = {}
    for module, expected_slots in expected_by_module.items():
        module_records = [latest[slot_id] for slot_id in expected_slots if slot_id in latest]
        terminal = [item for item in module_records if str(item.get("status", "")) in terminal_statuses]
        bucket = {key: 0 for key in ("completed", "failed", "refused", "unavailable", "passed", "correct_abstention")}
        for item in terminal:
            status = str(item.get("status", ""))
            quality = item.get("business_quality")
            bucket[status] += 1
            if quality == "passed" or (quality in (None, "") and item.get("quality") is True):
                bucket["passed"] += 1
            if quality == "correct_abstention":
                bucket["correct_abstention"] += 1
        by_module[module] = bucket
        slot_counts[module] = len(terminal)
        position_counts[module] = {
            "completed": bucket["completed"],
            "failed": bucket["failed"],
            "refused": bucket["refused"],
            "unavailable": bucket["unavailable"],
        }
        not_started[module] = len(expected_slots) - len(terminal)
    expected = {module: len(slots) for module, slots in expected_by_module.items()}
    warmup_counts = {
        module: sum(
            1 for record in records
            if record.get("module") == module
            and record.get("slot_id")
            and not bool(record.get("scored", True))
        )
        for module in expected_by_module
    }
    logit_warmup_path = run_root / "warmup.jsonl"
    warmup_counts["logit"] += len(logit_warmup_path.read_text(encoding="utf-8").splitlines()) if logit_warmup_path.exists() else 0
    demo_completed = all(not not_started[module] for module in expected)
    business_slots = [
        latest[slot_id]
        for slots in expected_by_module.values()
        for slot_id in slots
        if slot_id in latest and str(latest[slot_id].get("status", "")) in terminal_statuses
    ]
    business_quality_passed = bool(demo_completed) and all(
        _record_business_quality_passed(item)
        for item in business_slots
    )
    return {
        "schema_version": "statebus.model_assist_utility.summary.v1",
        "record_count": len(records),
        "slot_counts": slot_counts,
        "attempt_counts": {
            module: sum(1 for record in records if record.get("module") == module and record.get("slot_id") and bool(record.get("scored", True)))
            for module in expected_by_module
        },
        "warmup_counts": warmup_counts,
        "expected_slot_counts": expected,
        "not_started_positions": not_started,
        "position_outcomes": position_counts,
        "demo_completed": demo_completed,
        "business_quality_passed": business_quality_passed,
        "by_module": by_module,
    }


def finalize_run(run_root: Path, *, status: str, standard_restored: str, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    summary = summarize_records(run_root)
    summary.update({"status": status, "standard_restored": standard_restored, **dict(extra or {})})
    (run_root / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    lines = [
        "# Long-text model-assist utility demonstration",
        "",
        f"status: `{status}`",
        f"standard_restored: `{standard_restored}`",
        "",
        "The 28 positions are counted as APC 8, Logit 12, and KV 8. Warmup and recovery evidence are separate.",
        "",
        "## APC",
        "",
        f"observed={summary['slot_counts']['apc']} expected={summary['expected_slot_counts']['apc']}",
        "",
        "## KV",
        "",
        f"observed={summary['slot_counts']['kv']} expected={summary['expected_slot_counts']['kv']}",
        "",
        "## Logit",
        "",
        f"observed={summary['slot_counts']['logit']} expected={summary['expected_slot_counts']['logit']}",
        "",
        "```json",
        json.dumps(summary, indent=2, ensure_ascii=False),
        "```",
        "",
    ]
    (run_root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    (run_root / "summary.csv").write_text("module,expected,observed\n" + "\n".join(f"{module},{summary['expected_slot_counts'][module]},{summary['slot_counts'][module]}" for module in ("apc", "logit", "kv")) + "\n", encoding="utf-8")
    return summary


def run_prepare(*, report_root: Path = DEFAULT_REPORT_ROOT, output_root: Path | None = None) -> dict[str, Any]:
    if output_root is None:
        run_id = f"prepare-longtext-demo-v3-{time.strftime('%Y%m%d_%H%M%S')}-{os.getpid()}"
        output_root = report_root / run_id
    return prepare_taskpack(
        output_root=output_root,
        root=SAMPLE_ROOT,
        tokenizer_path="/data/models/Qwen3-32B",
    )


def run_dry_run(*, phase: str = "all", mode: str = "formal", target_slot_id: str | None = None, wall_budget_s: float = 5400.0) -> dict[str, Any]:
    taskpack = compile_taskpack(load_local_codec("/data/models/Qwen3-32B"), root=SAMPLE_ROOT)
    if phase not in {"all", "standard", "apc", "logit", "kv"}:
        raise ValueError(f"unsupported_phase:{phase}")
    if mode not in {"formal", "smoke"}:
        raise ValueError(f"unsupported_mode:{mode}")
    target_module = None
    if target_slot_id:
        target_module, _target_case_id, _target_condition = _target_slot_identity(target_slot_id)
        if phase != target_module:
            raise ValueError(f"targeted_recheck_requires_{target_module}_phase")
    selected = [item for item in taskpack.plan if phase == "all" or item["module"] == phase]
    if mode == "smoke":
        selected = [item for item in selected if item["gate"]]
    if target_slot_id:
        selected = [item for item in selected if f"{item['case_id']}:{item['condition']}" == target_slot_id]
        if len(selected) != 1:
            raise ValueError("targeted_recheck_slot_not_in_selected_plan")
    if target_slot_id or mode == "smoke" or phase == "logit":
        business_warmups = 0
    elif phase == "all":
        business_warmups = 4
    else:
        business_warmups = 2
    return {
        "suite_revision": taskpack.manifest["suite_revision"],
        "mode": mode,
        "phase": phase,
        "positions": len(selected),
        "standard_positions": sum(item["module"] in {"apc", "logit"} for item in selected),
        "kv_positions": sum(item["module"] == "kv" for item in selected),
        "warmups": {
            "business": business_warmups,
            "choice": 0 if target_slot_id or mode == "smoke" or phase not in {"all", "standard", "logit"} else 2,
        },
        "wall_budget_s": wall_budget_s,
        "plan": selected,
        "target_slot_id": target_slot_id,
        "switches": ["standard APC-on", "KV APC-off", "restore original standard"] if phase in {"all", "kv"} else ["standard APC-on"],
    }


def _resume_phase_is_subset(saved_phase: str, requested_phase: str) -> bool:
    phase_modules = {
        "all": frozenset({"apc", "logit", "kv"}),
        "standard": frozenset({"apc", "logit"}),
        "apc": frozenset({"apc"}),
        "logit": frozenset({"logit"}),
        "kv": frozenset({"kv"}),
    }
    saved_modules = phase_modules.get(saved_phase)
    requested_modules = phase_modules.get(requested_phase)
    return saved_modules is not None and requested_modules is not None and requested_modules <= saved_modules


def run_execute(*, mode: str = "formal", phase: str = "all", quiet: bool = False, poll_interval_s: float = 60.0, wall_budget_s: float = 5400.0, report_root: Path = DEFAULT_REPORT_ROOT, run_id: str | None = None, yes: bool = False, resume: bool = False, target_slot_id: str | None = None, allow_external_gpu_pids: Sequence[int] = ()) -> tuple[int, Path, dict[str, Any]]:
    if not yes:
        raise UtilitySuiteError("--execute requires --yes for service switching")
    target_module = None
    if target_slot_id:
        target_module, _target_case_id, _target_condition = _target_slot_identity(target_slot_id)
        if not resume or mode != "formal" or phase != target_module:
            raise UtilitySuiteError(f"targeted_recheck_requires_formal_{target_module}_resume")
    if allow_external_gpu_pids and (not resume or mode != "formal" or not target_slot_id or target_module not in {"apc", "logit"}):
        raise UtilitySuiteError("shared_gpu_authorization_requires_one_targeted_standard_resume")
    namespace_codec = load_local_codec("/data/models/Qwen3-32B")
    taskpack = compile_taskpack(namespace_codec, root=SAMPLE_ROOT)
    run_id = run_id or f"longtext-demo-v3-{time.strftime('%Y%m%d_%H%M%S')}-{os.getpid()}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", run_id):
        raise UtilitySuiteError("invalid_run_id")
    run_root = report_root / run_id
    if resume:
        if not run_root.is_dir():
            raise UtilitySuiteError(f"resume_run_not_found:{run_root}")
        frozen_path = run_root / "taskpack.json"
        config_path = run_root / "run-config.json"
        try:
            frozen_taskpack = json.loads(frozen_path.read_text(encoding="utf-8"))
            saved_config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UtilitySuiteError(f"resume_frozen_inputs_unavailable:{type(exc).__name__}") from exc
        if frozen_taskpack != _taskpack_artifact_payload(taskpack):
            raise UtilitySuiteError("resume_taskpack_revision_or_configuration_mismatch")
        if (
            saved_config.get("suite_revision") != taskpack.manifest.get("suite_revision")
            or saved_config.get("mode", "formal") != mode
            or not _resume_phase_is_subset(str(saved_config.get("phase", "")), phase)
        ):
            raise UtilitySuiteError("resume_run_configuration_mismatch")
        if target_slot_id:
            _validate_failed_target_slot(run_root, target_slot_id, expected_module=target_module)
        history_path = run_root / "resume-history.jsonl"
        prior_resumes = len(history_path.read_text(encoding="utf-8").splitlines()) if history_path.exists() else 0
        archive_root = run_root / "resume-archives"
        existing_archive_numbers = [
            int(match.group(1))
            for path in archive_root.glob("resume-*") if path.is_dir()
            for match in [re.fullmatch(r"resume-(\d+)", path.name)]
            if match is not None
        ]
        resume_number = max([prior_resumes + 1, *(number + 1 for number in existing_archive_numbers)])
    elif run_root.exists():
        raise UtilitySuiteError(f"run_directory_exists:{run_root}")
    else:
        run_root.mkdir(parents=True)
        resume_number = 0

    runner = UtilitySuiteRunner(
        taskpack,
        run_root,
        quiet=quiet,
        wall_budget_s=wall_budget_s,
        poll_interval_s=poll_interval_s,
        resume=resume,
        target_slot_id=target_slot_id,
        mode=mode,
        namespace_codec=namespace_codec,
    )
    if resume:
        runner.execution_id = f"{run_id}-resume-{resume_number:02d}"
        history_dir = run_root / "resume-archives" / f"resume-{resume_number:02d}"
        history_dir.mkdir(parents=True, exist_ok=False)
        for name in ("summary.json", "report.md", "run-status.env"):
            source = run_root / name
            if source.is_file():
                shutil.copy2(source, history_dir / name)
        recovered_orphan_slots = runner.recover_orphaned_logit_traces()
        if recovered_orphan_slots:
            runner.log(f"orphan_logit_traces_recovered={len(recovered_orphan_slots)}")
    runner.log(f"run_id={run_id}")
    runner.log(f"run_log={runner.run_log}")
    if resume:
        runner.log(f"resume_execution_id={runner.execution_id}")
    if quiet:
        print(f"run_id={run_id} run_log={runner.run_log}" + (f" execution_id={runner.execution_id}" if resume else ""), flush=True)
    preflight = run_preflight(phase=phase, report_root=run_root, allow_external_gpu_pids=allow_external_gpu_pids)
    if resume:
        preflight_path = runner.service_dir / f"resume-preflight-{resume_number:02d}.json"
        preflight_path.write_text(json.dumps(preflight.evidence | {"passed": preflight.passed, "reasons": list(preflight.reasons)}, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        prior_status = (run_root / "run-status.env").read_text(encoding="utf-8") if (run_root / "run-status.env").exists() else "missing"
        _append_jsonl(run_root / "resume-history.jsonl", {
            "resume_number": resume_number,
            "execution_id": runner.execution_id,
            "phase": phase,
            "mode": mode,
            "wall_budget_s": wall_budget_s,
            "poll_interval_s": poll_interval_s,
            "prior_status": prior_status,
            "preflight_path": str(preflight_path),
            "preflight_passed": preflight.passed,
            "target_slot_id": target_slot_id,
            "allow_external_gpu_pids": sorted({int(pid) for pid in allow_external_gpu_pids}),
        })
        _append_jsonl(run_root / "run-status-history.jsonl", {"event": "resume_started", "execution_id": runner.execution_id, "prior_status": prior_status})
    else:
        runner.write_initial_artifacts(preflight)
        (run_root / "run-config.json").write_text(
            json.dumps({
                "suite_revision": taskpack.manifest.get("suite_revision"),
                "mode": mode,
                "phase": phase,
                "wall_budget_s": wall_budget_s,
                "poll_interval_s": poll_interval_s,
            }, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if not preflight.passed:
        summary = finalize_run(run_root, status="blocked_preflight", standard_restored="not_changed", extra={"blocked_reasons": list(preflight.reasons), "phase": phase})
        (run_root / "run-status.env").write_text("status=blocked_preflight\nstandard_restored=not_changed\n" + "blocked_reasons=" + ",".join(preflight.reasons) + "\n", encoding="utf-8")
        _append_jsonl(run_root / "run-status-history.jsonl", {"event": "blocked_preflight", "reasons": list(preflight.reasons)})
        return 3, run_root, summary
    if resume and runner.all_positions_reusable():
        summary = finalize_run(run_root, status="demo_completed", standard_restored="true", extra={"phase": phase, "resume_noop": True})
        (run_root / "run-status.env").write_text("status=demo_completed\nstandard_restored=true\nresume_noop=true\n", encoding="utf-8")
        _append_jsonl(run_root / "run-status-history.jsonl", {"event": "resume_noop", "execution_id": runner.execution_id})
        return 0, run_root, summary
    restored = "not_checked"
    try:
        summary_payload = runner.run_live(phase=phase, smoke_only=mode == "smoke")
        restored = runner.standard_restored
        run_status = str(summary_payload.get("status", "live_completed"))
        summary_state = summarize_records(run_root)
        if restored not in {"true", "unchanged"}:
            final_status = "failed_restore"
        elif run_status == "incomplete_budget":
            final_status = "incomplete_budget"
        elif summary_state["demo_completed"]:
            final_status = "demo_completed"
        elif summary_payload.get("blocked_modules"):
            final_status = "incomplete_gate"
        else:
            final_status = "incomplete"
        code = 0 if final_status == "demo_completed" else 1
        summary = finalize_run(run_root, status=final_status, standard_restored=restored, extra={"phase": phase, "live_summary": summary_payload})
        (run_root / "run-status.env").write_text(f"status={final_status}\nstandard_restored={restored}\n", encoding="utf-8")
        _append_jsonl(run_root / "run-status-history.jsonl", {"event": "run_finished", "status": final_status, "standard_restored": restored, "execution_id": runner.execution_id})
        return code, run_root, summary
    except Exception as exc:
        restored = runner.standard_restored
        (run_root / "failure-traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        summary = finalize_run(run_root, status="failed", standard_restored=restored, extra={"phase": phase, "error_type": type(exc).__name__, "error": str(exc)})
        (run_root / "run-status.env").write_text(f"status=failed\nstandard_restored={restored}\nerror={type(exc).__name__}:{exc}\n", encoding="utf-8")
        _append_jsonl(run_root / "run-status-history.jsonl", {"event": "run_failed", "error_type": type(exc).__name__, "error": str(exc), "standard_restored": restored, "execution_id": runner.execution_id})
        return 1, run_root, summary


def recover_only(run_id: str, *, report_root: Path = DEFAULT_REPORT_ROOT) -> tuple[int, Path]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", run_id):
        raise UtilitySuiteError("invalid_run_id")
    run_root = report_root / run_id
    if not run_root.is_dir():
        raise UtilitySuiteError(f"run_not_found:{run_root}")
    kv_env = run_root / "service" / "vllm.env.kv.local"
    service_dir = run_root / "service"
    service_dir.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, Any] = {}
    current_standard = _manager_identity(STANDARD_ENV)
    current_kv = _manager_identity(kv_env) if kv_env.exists() else None
    evidence["standard_before"] = current_standard
    evidence["kv_before"] = current_kv
    ok = False
    error = ""
    try:
        if current_kv is not None and current_kv.get("pid"):
            if current_kv.get("mode") != "kv":
                raise UtilitySuiteError("recover_service_owner_unknown")
            recorded_path = service_dir / "kv-manager-identity.json"
            recorded = json.loads(recorded_path.read_text(encoding="utf-8")) if recorded_path.exists() else {}
            recorded_pid = recorded.get("pid")
            if not recorded_pid or int(recorded_pid) != int(current_kv["pid"]):
                raise UtilitySuiteError("recover_kv_owner_not_recorded")
            try:
                evidence["kv_log"] = _archive_service_log(service_dir, kv_env, "kv-recover")
            except UtilitySuiteError as exc:
                evidence["kv_log_archive_error"] = str(exc)
            stopped = _run_capture(["env", f"STATEBUS_VLLM_ENV_FILE={kv_env}", str(MANAGER), "stop"], timeout_s=60)
            evidence["kv_stop"] = stopped
            if stopped.get("returncode") != 0:
                raise UtilitySuiteError("recover_kv_stop_failed")
        elif current_kv is not None and current_kv.get("healthy"):
            raise UtilitySuiteError("recover_service_owner_unknown")

        current_standard = _manager_identity(STANDARD_ENV)
        if current_standard.get("pid") and not (
            current_standard.get("mode") == "standard" and current_standard.get("healthy")
        ):
            standard_identity_path = service_dir / "standard-manager-identity.json"
            standard_identity = json.loads(standard_identity_path.read_text(encoding="utf-8")) if standard_identity_path.exists() else {}
            if standard_identity.get("pid") != current_standard.get("pid") or current_standard.get("mode") != "standard":
                raise UtilitySuiteError("recover_standard_owner_unknown")
            try:
                evidence["standard_log"] = _archive_service_log(service_dir, STANDARD_ENV, "standard-recover-before-restart")
            except UtilitySuiteError as exc:
                evidence["standard_log_archive_error"] = str(exc)
            stopped = _run_capture(["env", f"STATEBUS_VLLM_ENV_FILE={STANDARD_ENV}", str(MANAGER), "stop"], timeout_s=60)
            evidence["standard_stop"] = stopped
            if stopped.get("returncode") != 0:
                raise UtilitySuiteError("recover_standard_stop_failed")
            current_standard = _manager_identity(STANDARD_ENV)
        if not (current_standard.get("mode") == "standard" and current_standard.get("pid") and current_standard.get("healthy")):
            if current_standard.get("pid"):
                raise UtilitySuiteError("recover_standard_owner_unknown")
            restored = _run_capture(["setsid", "--wait", "env", f"STATEBUS_VLLM_ENV_FILE={STANDARD_ENV}", str(MANAGER), "start"], timeout_s=960)
            evidence["standard_start"] = restored
            if restored.get("returncode") != 0:
                raise UtilitySuiteError("recover_standard_start_failed")
        verification = _verify_standard_endpoints()
        evidence["verification"] = verification
        ok = bool(verification.get("passed"))
        if not ok:
            raise UtilitySuiteError(str(verification.get("reason", "recover_standard_verification_failed")))
    except (OSError, ValueError, TypeError, json.JSONDecodeError, UtilitySuiteError) as exc:
        error = f"{type(exc).__name__}:{exc}"
        ok = False
    evidence["standard_after"] = _manager_identity(STANDARD_ENV)
    evidence["error"] = error
    (service_dir / "recover-standard.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    status_archive = run_root / "recovery-archives" / f"recover-{time.time_ns()}"
    status_archive.mkdir(parents=True, exist_ok=True)
    prior_status = run_root / "run-status.env"
    if prior_status.is_file():
        shutil.copy2(prior_status, status_archive / "run-status.env")
    (run_root / "run-status.env").write_text(f"status={'recovered' if ok else 'recovery_failed'}\nstandard_restored={'true' if ok else 'false'}\n" + (f"error={error}\n" if error else ""), encoding="utf-8")
    _append_jsonl(run_root / "run-status-history.jsonl", {"event": "recover_only", "status": "recovered" if ok else "recovery_failed", "standard_restored": ok, "error": error})
    return (0 if ok else 1), run_root
