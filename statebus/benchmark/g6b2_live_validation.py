"""Bounded G6-B2 live validation for the selected local vLLM profile."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


DEFAULT_PROFILE_ID = "g6b2-live-qwen3-8b-gpu0-u050-v1"
REAL_EMBEDDING_PROFILE_ID = (
    "g6b2-live-qwen3-8b-gpu0-u050-qwen3-embedding-gpu1-v1"
)
EMBEDDING_MODE = os.getenv(
    "STATEBUS_G6B2_EMBEDDING_MODE", "deterministic"
).strip().lower()
PROFILE_ID = os.getenv(
    "STATEBUS_G6B2_PROFILE_ID",
    REAL_EMBEDDING_PROFILE_ID if EMBEDDING_MODE == "local" else DEFAULT_PROFILE_ID,
).strip()
EMBEDDING_MODEL_PATH = os.getenv(
    "STATEBUS_G6B2_EMBEDDING_MODEL_PATH",
    os.getenv(
        "STATEBUS_EMBED_MODEL_PATH", "/statebus/models/Qwen3-Embedding-0.6B"
    ),
).strip()
EMBEDDING_DEVICE = os.getenv(
    "STATEBUS_G6B2_EMBEDDING_DEVICE",
    os.getenv("STATEBUS_EMBED_DEVICE", "cuda:0"),
).strip()
EMBEDDING_PHYSICAL_GPU = int(
    os.getenv("STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU", "1")
)
SERVICE_PHYSICAL_GPU = int(os.getenv("STATEBUS_G6B2_SERVICE_PHYSICAL_GPU", "0"))
GPU_UUID = os.getenv(
    "STATEBUS_G6B2_SERVICE_GPU_UUID",
    {
        0: "GPU-3ecfad62-035b-2626-e769-79c785e7665d",
        2: "GPU-25019de8-09aa-328a-be23-4bec986badad",
    }.get(SERVICE_PHYSICAL_GPU, ""),
).strip()
QWEN3_8B_U050_PROFILE: dict[str, object] = {
    "profile_id": PROFILE_ID,
    "model_path": "/data/models/Qwen3-8B",
    "served_model": "qwen3-8b",
    "physical_gpu": SERVICE_PHYSICAL_GPU,
    "gpu_uuid": GPU_UUID,
    "gpu_memory_utilization": 0.50,
    "max_model_len": 4096,
    "max_num_seqs": 1,
    "max_num_batched_tokens": 4096,
    "dtype": "bfloat16",
    "enforce_eager": True,
    "cpu_offload_gb": 0,
    "host": "127.0.0.1",
    "port": 53334,
    "base_url": "http://127.0.0.1:53334/v1",
    "health_url": "http://127.0.0.1:53334/health",
    "reuse_min_free_mib": 4096,
}
QWEN3_32B_U050_PROFILE: dict[str, object] = {
    "profile_id": PROFILE_ID,
    "model_path": "/data/models/Qwen3-32B",
    "served_model": "qwen3-32b",
    "physical_gpu": SERVICE_PHYSICAL_GPU,
    "gpu_uuid": GPU_UUID,
    "gpu_memory_utilization": 0.82,
    "max_model_len": 8192,
    "max_num_seqs": 1,
    "max_num_batched_tokens": 8192,
    "dtype": "bfloat16",
    "enforce_eager": True,
    "cpu_offload_gb": None,
    "host": "127.0.0.1",
    "port": 53334,
    "base_url": "http://127.0.0.1:53334/v1",
    "health_url": "http://127.0.0.1:53334/health",
    "reuse_min_free_mib": 4096,
}
DEFAULT_MODEL_PROFILE = (
    QWEN3_32B_U050_PROFILE
    if os.getenv("STATEBUS_LOCAL_VLLM_MODEL", "qwen3-8b").strip()
    == "qwen3-32b"
    else QWEN3_8B_U050_PROFILE
)
ALLOWED_SEQUENCE = (
    "B2-Preflight",
    "Docker-Verify",
    "B2-Live-Smoke",
    "B2-Minimal-Matched-Pair",
)
PAIR_KEY_FIELDS = (
    "task_contract_hash",
    "input_lineage_hashes",
    "quality_contract_hash",
    "deterministic_seed",
)
PAIR_KEY_EXCLUDED_FIELDS = (
    "lane",
    "family_id",
    "round_number",
    "repeat_id",
    "cache_epoch",
)
FIXED_METRICS = {
    "exact_replay": {
        "status": "unsupported",
        "value": None,
        "reason": "c2_exact_restore_not_implemented",
    },
    "recipe_step_skip": {
        "status": "deferred",
        "value": None,
        "reason": "recipe_step_skip_deferred_to_c2",
    },
    "verified_recipe_work_avoided": {
        "status": "unsupported",
        "value": None,
        "reason": "recipe_step_skip_deferred_to_c2",
    },
}
TERMINAL_STATUSES = (
    "success",
    "runtime_fail",
    "timeout",
    "environment_fail",
    "policy_reject",
    "unsupported",
    "quality_fail",
)


def _embedding_profile() -> dict[str, object]:
    return {
        "mode": EMBEDDING_MODE,
        "model_path": EMBEDDING_MODEL_PATH if EMBEDDING_MODE == "local" else None,
        "device": EMBEDDING_DEVICE if EMBEDDING_MODE == "local" else "cpu",
        "physical_gpu": EMBEDDING_PHYSICAL_GPU if EMBEDDING_MODE == "local" else None,
        "container_device": "cuda:0" if EMBEDDING_MODE == "local" else None,
        "workload_scope": "memory_query_and_commit_vector",
        "document_retrieval": "table_structure",
        "semantic_document_retrieval": False,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _profile(model_profile: Mapping[str, object] | None = None) -> dict[str, object]:
    profile = dict(DEFAULT_MODEL_PROFILE)
    if model_profile:
        profile.update(dict(model_profile))
    return profile


def _json_write(path: Path, payload: object, *, exclusive: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if exclusive else "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")


def _json_read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _run(command: list[str], *, timeout: float = 30.0) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return completed.returncode, completed.stdout, completed.stderr


def _parse_csv_noheader(text: str, fields: tuple[str, ...]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        values = [item.strip() for item in line.split(",")]
        rows.append(
            {
                name: values[index] if index < len(values) else ""
                for index, name in enumerate(fields)
            }
        )
    return rows


def _number(value: object) -> float:
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    if not match:
        raise ValueError(f"numeric_value_required:{value}")
    return float(match.group(0))


def _proc_snapshot(pid: int, *, include_start_time: bool = False) -> dict[str, object] | None:
    proc = Path("/proc") / str(pid)
    try:
        status: dict[str, str] = {}
        for line in (proc / "status").read_text(encoding="utf-8").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                status[key] = value.strip()
        cmdline = (
            (proc / "cmdline")
            .read_bytes()
            .replace(b"\0", b" ")
            .decode("utf-8")
            .strip()
        )
        stat = (proc / "stat").read_text(encoding="utf-8").split()
        start_time = ""
        if include_start_time:
            rc, start_time, _ = _run(["ps", "-o", "lstart=", "-p", str(pid)])
            if rc != 0:
                start_time = ""
        return {
            "pid": pid,
            "ppid": int(status.get("PPid", "0")),
            "uid": int(status.get("Uid", "0").split()[0]),
            "start_time": start_time.strip(),
            "proc_start_ticks": int(stat[21]),
            "argv": cmdline,
        }
    except (OSError, ValueError, IndexError):
        return None


def _descendant_pids(parent_pid: int) -> set[int]:
    parents: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        snapshot = _proc_snapshot(int(entry.name))
        if snapshot is not None:
            parents[int(snapshot["pid"])] = int(snapshot["ppid"])
    descendants = {parent_pid}
    changed = True
    while changed:
        changed = False
        for pid, ppid in parents.items():
            if ppid in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    return descendants


def _listener_pids(host: str, port: int) -> set[int]:
    rc, output, _ = _run(
        ["ss", "-H", "-ltnp", f"sport = :{int(port)}"]
    )
    if rc != 0:
        return set()
    pids: set[int] = set()
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        local_address = fields[3]
        if not re.search(rf":{int(port)}$", local_address):
            continue
        if host not in {"0.0.0.0", "::", "[::]"}:
            observed_host = local_address.rsplit(":", 1)[0].strip("[]")
            if observed_host not in {host, "0.0.0.0", "::", "*"}:
                continue
        pids.update(int(pid) for pid in re.findall(r"\bpid=(\d+)\b", line))
    return pids


def _argv_value(argv: str, option: str, *, positional_model: bool = False) -> str | None:
    tokens = argv.split()
    if positional_model:
        try:
            return tokens[tokens.index("serve") + 1]
        except (ValueError, IndexError):
            return None
    try:
        return tokens[tokens.index(option) + 1]
    except (ValueError, IndexError):
        return None


def _observed_config(argv: str) -> dict[str, object]:
    return {
        "model_path": _argv_value(argv, "", positional_model=True),
        "served_model": _argv_value(argv, "--served-model-name"),
        "host": _argv_value(argv, "--host"),
        "port": _argv_value(argv, "--port"),
        "dtype": _argv_value(argv, "--dtype"),
        "max_model_len": _argv_value(argv, "--max-model-len"),
        "max_num_seqs": _argv_value(argv, "--max-num-seqs"),
        "max_num_batched_tokens": _argv_value(argv, "--max-num-batched-tokens"),
        "gpu_memory_utilization": _argv_value(argv, "--gpu-memory-utilization"),
        "cpu_offload_gb": _argv_value(argv, "--cpu-offload-gb"),
        "enforce_eager": "--enforce-eager" in argv.split(),
    }


def _config_matches(
    observed: Mapping[str, object],
    profile: Mapping[str, object],
) -> bool:
    try:
        observed_cpu_offload = observed.get("cpu_offload_gb")
        expected_cpu_offload = profile["cpu_offload_gb"]
        if expected_cpu_offload is None:
            cpu_offload_ok = observed_cpu_offload is None or float(
                str(observed_cpu_offload)
            ) == 0.0
        else:
            cpu_offload_ok = float(str(observed_cpu_offload)) == float(
                expected_cpu_offload
            )
        return (
            observed.get("model_path") == profile["model_path"]
            and observed.get("served_model") == profile["served_model"]
            and observed.get("host") == profile["host"]
            and int(str(observed.get("port"))) == int(profile["port"])
            and observed.get("dtype") == profile["dtype"]
            and int(str(observed.get("max_model_len")))
            == int(profile["max_model_len"])
            and int(str(observed.get("max_num_seqs")))
            == int(profile["max_num_seqs"])
            and int(str(observed.get("max_num_batched_tokens")))
            == int(profile["max_num_batched_tokens"])
            and float(str(observed.get("gpu_memory_utilization")))
            == float(profile["gpu_memory_utilization"])
            and cpu_offload_ok
            and observed.get("enforce_eager") is True
        )
    except (TypeError, ValueError):
        return False


def _g6b2_gpu_preflight_projection(
    gpu_inventory: Iterable[Mapping[str, object]] = (),
    compute_processes: Iterable[Mapping[str, object]] = (),
    *,
    model_path_readable: bool,
    vllm_executable_available: bool,
    resolved_config: Mapping[str, object] | None = None,
    authorized_gpu_indices: Iterable[int] = (),
    model_profile: Mapping[str, object] | None = None,
    authorized_competing_processes: Iterable[Mapping[str, object]] = (),
    target_service_pids: Iterable[int] = (),
    target_gpu_identity_ok: bool | None = None,
    operator_managed_reuse: bool = False,
    config_observed: bool | None = None,
) -> dict[str, object]:
    profile = _profile(model_profile)
    inventory = [dict(item) for item in gpu_inventory]
    compute_rows = [dict(item) for item in compute_processes]
    del authorized_competing_processes
    allowed_indices = {int(item) for item in authorized_gpu_indices} or {
        int(profile["physical_gpu"])
    }
    target_pids = {str(int(item)) for item in target_service_pids}
    selected_gpu = next(
        (
            gpu
            for gpu in inventory
            if int(_number(gpu.get("index", -1))) == int(profile["physical_gpu"])
        ),
        None,
    )
    target_uuid = (
        ""
        if selected_gpu is None
        else str(selected_gpu.get("uuid", selected_gpu.get("gpu_uuid", "")))
    )
    free_mib = (
        0.0
        if selected_gpu is None
        else _number(
            selected_gpu.get("memory_free", selected_gpu.get("memory.free", 0))
        )
    )
    config = dict(resolved_config or {})
    config_ok = _config_matches(config, profile)
    config_was_observed = (
        bool(config) if config_observed is None else config_observed
    )
    gpu_process_ok = (
        bool(target_pids)
        if target_gpu_identity_ok is None
        else target_gpu_identity_ok
    )
    compute_processes_checked = target_gpu_identity_ok is not None
    executable_ok = vllm_executable_available or (
        operator_managed_reuse and not config_was_observed
    )
    config_gate_ok = config_ok or (
        operator_managed_reuse and not config_was_observed
    )
    passed = bool(
        selected_gpu
        and int(profile["physical_gpu"]) in allowed_indices
        and target_uuid == profile["gpu_uuid"]
        and gpu_process_ok
        and model_path_readable
        and executable_ok
        and config_gate_ok
    )
    reasons = []
    if selected_gpu is None or target_uuid != profile["gpu_uuid"]:
        reasons.append("target_gpu_identity_mismatch")
    if not gpu_process_ok:
        reasons.append("target_gpu_process_attribution_missing")
    if not model_path_readable:
        reasons.append("model_path_unreadable")
    if not executable_ok:
        reasons.append("vllm_executable_unavailable")
    if not config_gate_ok:
        reasons.append("service_config_mismatch")
    return {
        "schema_version": "statebus.g6b2.gpu_preflight.v2",
        "profile_id": profile["profile_id"],
        "status": "observed" if passed else "environment_fail",
        "source": "nvidia-smi and /proc read-only reuse inspection",
        "observed_at": _now(),
        "driver_visible": bool(inventory),
        "selected_physical_gpu": int(profile["physical_gpu"])
        if selected_gpu
        else None,
        "gpu_uuid": target_uuid,
        "gpu_inventory": inventory,
        "coexistence_policy": "operator_managed_not_checked",
        "compute_processes_checked": compute_processes_checked,
        "compute_processes": compute_rows if compute_processes_checked else [],
        "target_service_pids": sorted(int(item) for item in target_pids),
        "authorized_competing_processes": [],
        "unrecognized_processes": [],
        "reuse_min_free_mib": profile["reuse_min_free_mib"],
        "observed_free_mib": free_mib,
        "model_path_readable": model_path_readable,
        "vllm_executable_available": vllm_executable_available,
        "operator_managed_reuse": operator_managed_reuse,
        "resolved_config": config,
        "resolved_config_observed": config_was_observed,
        "resolved_config_match": config_ok,
        "target_gpu_identity_ok": gpu_process_ok,
        "failure_stage": "" if passed else "B2-Preflight",
        "reason": "" if passed else ",".join(reasons),
        "environment_limitation": "" if passed else ",".join(reasons),
        "source_receipt_references": ["service_identity.json", "nvidia-smi"],
    }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise HTTPError(req.full_url, code, "redirect_forbidden", headers, fp)


def _g6b2_http_request(
    method: str,
    url: str,
    *,
    payload: Mapping[str, object] | None = None,
    timeout: float = 120.0,
) -> dict[str, object]:
    data = (
        None
        if payload is None
        else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    # The local vLLM endpoint is loopback-only.  Do not let a host-wide
    # HTTP(S)_PROXY setting route this request through an unrelated proxy.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            return {
                "status": "observed",
                "http_status": response.status,
                "headers": dict(response.headers.items()),
                "body": response.read().decode("utf-8"),
                "error": "",
            }
    except HTTPError as exc:
        return {
            "status": "failed",
            "http_status": exc.code,
            "headers": dict(exc.headers.items()),
            "body": exc.read().decode("utf-8", errors="replace"),
            "error": str(exc),
        }
    except (URLError, OSError, TimeoutError) as exc:
        return {
            "status": "failed",
            "http_status": None,
            "headers": {},
            "body": "",
            "error": str(exc),
        }


def _g6b2_vllm_health_projection(
    *,
    status_code: int | None,
    endpoint: str | None = None,
    error: str = "",
    manager_owned: bool = False,
) -> dict[str, object]:
    endpoint = endpoint or str(DEFAULT_MODEL_PROFILE["health_url"])
    passed = status_code is not None and 200 <= status_code < 300
    return {
        "schema_version": "statebus.g6b2.vllm_health.v2",
        "profile_id": PROFILE_ID,
        "source": "vllm /health",
        "endpoint": endpoint,
        "observed_at": _now(),
        "http_status": status_code,
        "http_health_ok": passed,
        "status": "observed" if passed else "environment_fail",
        "manager_owned": manager_owned,
        "manager_owner_observed": manager_owned,
        "failure_stage": "" if passed else "B2-Preflight",
        "reason": "" if passed else (error or "http_health_failed"),
        "source_receipt_references": ["service_identity.json", endpoint]
        if passed
        else [],
    }


def _g6b2_vllm_model_identity_projection(
    observed_model_ids: Iterable[str] = (),
    *,
    service_mode: str = "standard",
    source: str = "vllm /v1/models",
    error: str = "",
    model_profile: Mapping[str, object] | None = None,
) -> dict[str, object]:
    profile = _profile(model_profile)
    model_ids = [str(item) for item in observed_model_ids]
    matched = model_ids == [str(profile["served_model"])]
    return {
        "schema_version": "statebus.g6b2.vllm_model_identity.v2",
        "profile_id": profile["profile_id"],
        "requested": {
            key: profile[key] for key in ("model_path", "served_model", "host", "port")
        },
        "observed": {"model_ids": model_ids, "service_mode": service_mode},
        "identity_status": "matched" if matched else "mismatch" if model_ids else "not_run",
        "source": source,
        "failure_stage": "" if matched else "B2-Preflight",
        "reason": "" if matched else (error or "served_model_identity_mismatch"),
        "source_receipt_references": ["service_identity.json", source]
        if matched
        else [],
    }


def _g6b2_service_identity(
    service_runtime_dir: Path,
    coexist_pids: Iterable[int],
    *,
    model_profile: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    profile = _profile(model_profile)
    ignored_coexist_pids = [int(item) for item in coexist_pids]
    try:
        manager_pid = int(
            (service_runtime_dir / "service.pid")
            .read_text(encoding="utf-8")
            .strip()
        )
    except (OSError, ValueError):
        manager_pid = 0
    manager_server = (
        _proc_snapshot(manager_pid, include_start_time=True) if manager_pid else None
    )
    listener_pids = _listener_pids(str(profile["host"]), int(profile["port"]))
    service_roots = set(listener_pids)
    manager_argv = "" if manager_server is None else str(manager_server["argv"])
    if not service_roots and "vllm serve" in manager_argv:
        service_roots.add(manager_pid)
    target_pids: set[int] = set()
    for service_root in service_roots:
        target_pids.update(_descendant_pids(service_root))
    target_snapshots = [
        snapshot
        for pid in sorted(target_pids)
        if (snapshot := _proc_snapshot(pid)) is not None
    ]
    config_snapshot = next(
        (
            snapshot
            for snapshot in target_snapshots
            if _config_matches(
                _observed_config(str(snapshot.get("argv", ""))), profile
            )
        ),
        None,
    )
    if config_snapshot is None:
        config_snapshot = next(
            (
                snapshot
                for snapshot in target_snapshots
                if "vllm serve" in str(snapshot.get("argv", ""))
            ),
            manager_server,
        )
    attributed_argv = (
        "" if config_snapshot is None else str(config_snapshot.get("argv", ""))
    )
    observed_config = _observed_config(attributed_argv)
    config_observed = bool(attributed_argv.strip())
    rc_gpu, gpu_text, gpu_error = _run(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader",
        ]
    )
    inventory = (
        _parse_csv_noheader(
            gpu_text,
            (
                "index",
                "uuid",
                "name",
                "memory_total",
                "memory_used",
                "memory_free",
                "utilization_gpu",
            ),
        )
        if rc_gpu == 0
        else []
    )
    rc_compute, compute_text, compute_error = _run(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory",
            "--format=csv,noheader,nounits",
        ]
    )
    compute_processes = (
        _parse_csv_noheader(
            compute_text,
            ("gpu_uuid", "pid", "process_name", "used_gpu_memory_mib"),
        )
        if rc_compute == 0
        else []
    )
    target_compute_processes = []
    for process in compute_processes:
        try:
            process_pid = int(str(process.get("pid", "")))
        except ValueError:
            continue
        if (
            process_pid in target_pids
            and str(process.get("gpu_uuid", "")) == str(profile["gpu_uuid"])
        ):
            target_compute_processes.append(process)
    inventory_gpu_ok = any(
        int(_number(gpu.get("index", -1))) == int(profile["physical_gpu"])
        and str(gpu.get("uuid", "")) == str(profile["gpu_uuid"])
        for gpu in inventory
    )
    target_gpu_identity_ok = bool(
        rc_gpu == 0
        and rc_compute == 0
        and inventory_gpu_ok
        and target_compute_processes
    )
    health_raw = _g6b2_http_request(
        "GET", str(profile["health_url"]), timeout=10
    )
    models_raw = _g6b2_http_request(
        "GET", f"{profile['base_url']}/models", timeout=10
    )
    try:
        model_payload = json.loads(str(models_raw["body"]))
        model_ids = [str(item.get("id", "")) for item in model_payload.get("data", [])]
        model_roots = [
            str(item.get("root", "")) for item in model_payload.get("data", [])
        ]
        model_max_lens = [
            item.get("max_model_len") for item in model_payload.get("data", [])
        ]
    except (json.JSONDecodeError, AttributeError, TypeError):
        model_ids, model_roots, model_max_lens = [], [], []
    http_health_ok = bool(
        health_raw.get("status") == "observed"
        and isinstance(health_raw.get("http_status"), int)
        and 200 <= int(health_raw["http_status"]) < 300
    )
    served_model_identity_ok = model_ids == [str(profile["served_model"])]
    model_root_ok = model_roots == [str(profile["model_path"])]
    max_model_len_ok = model_max_lens == [profile["max_model_len"]]
    manager_owner_observed = bool(
        manager_server
        and int(manager_server["uid"]) == os.getuid()
        and manager_pid in target_pids
        and "vllm serve" in manager_argv
    )
    service_process_attribution_observed = bool(
        target_pids
        and any(
            int(snapshot["pid"]) in listener_pids
            for snapshot in target_snapshots
        )
    )
    identity = {
        "schema_version": "statebus.g6b2.service_identity.v2",
        "profile_id": profile["profile_id"],
        "source": "service.pid + ss listener + /proc + nvidia-smi + HTTP",
        "observed_at": _now(),
        "service_runtime_dir": str(service_runtime_dir),
        "manager_pid": manager_pid or None,
        "server": manager_server,
        "listener_pids": sorted(listener_pids),
        "service_root_pids": sorted(service_roots),
        "target_service_processes": target_snapshots,
        "target_compute_processes": target_compute_processes,
        "authorized_coexisting_processes": [],
        "requested_coexist_pids": ignored_coexist_pids,
        "coexistence_policy": "operator_managed_not_checked",
        "coexistence_process_inspection": False,
        "observed_config": observed_config,
        "observed_config_status": "observed" if config_observed else "unobserved",
        "observed_config_match": _config_matches(observed_config, profile),
        "gpu_uuid": profile["gpu_uuid"],
        "health_response": health_raw,
        "models_response": models_raw,
        "model_roots": model_roots,
        "model_max_lens": model_max_lens,
        "http_health_ok": http_health_ok,
        "served_model_identity_ok": served_model_identity_ok,
        "model_root_ok": model_root_ok,
        "max_model_len_ok": max_model_len_ok,
        "target_gpu_identity_ok": target_gpu_identity_ok,
        "target_gpu_identity_status": (
            "matched"
            if target_gpu_identity_ok
            else "environment_limited"
            if rc_gpu != 0 or rc_compute != 0 or not service_process_attribution_observed
            else "mismatch"
        ),
        "manager_owner_observed": manager_owner_observed,
        "manager_owner_status": (
            "matched"
            if manager_owner_observed
            else "unobserved"
            if manager_server is None
            else "mismatch"
        ),
        "service_process_attribution_observed": service_process_attribution_observed,
        "service_process_attribution_status": (
            "observed"
            if service_process_attribution_observed
            else "environment_limited"
            if listener_pids
            else "unobserved"
        ),
        "container_runtime_profile_ok": None,
        "container_runtime_profile_status": "unobserved",
        "owner_match": manager_owner_observed,
        "service_lifecycle_owner": "operator",
        "reuse_existing": True,
        "stop_service_on_exit": False,
        "service_stop_called": False,
    }
    health = _g6b2_vllm_health_projection(
        status_code=(
            health_raw.get("http_status")
            if health_raw["status"] == "observed"
            else None
        ),
        error=str(health_raw.get("error", "")),
        manager_owned=manager_owner_observed,
    )
    model_identity = _g6b2_vllm_model_identity_projection(
        model_ids,
        error=str(models_raw.get("error", "")),
        model_profile=profile,
    )
    model_ok = model_root_ok and max_model_len_ok
    if not model_ok and model_identity["identity_status"] == "matched":
        model_identity.update(
            {
                "identity_status": "mismatch",
                "reason": "model_root_or_context_mismatch",
                "source_receipt_references": [],
            }
        )
    preflight = _g6b2_gpu_preflight_projection(
        inventory,
        compute_processes,
        model_path_readable=os.access(
            f"{profile['model_path']}/config.json", os.R_OK
        ),
        vllm_executable_available="vllm serve" in attributed_argv,
        resolved_config=observed_config,
        authorized_gpu_indices=(int(profile["physical_gpu"]),),
        model_profile=profile,
        authorized_competing_processes=(),
        target_service_pids=target_pids,
        target_gpu_identity_ok=target_gpu_identity_ok,
        operator_managed_reuse=True,
        config_observed=config_observed,
    )
    if not (
        preflight["status"] == "observed"
        and http_health_ok
        and served_model_identity_ok
        and model_root_ok
        and max_model_len_ok
        and target_gpu_identity_ok
    ):
        reasons = [
            str(preflight.get("reason", "")),
            gpu_error if rc_gpu else "",
            compute_error if rc_compute else "",
        ]
        if not http_health_ok:
            reasons.append("http_health_failed")
        if not served_model_identity_ok:
            reasons.append("served_model_identity_mismatch")
        if not model_root_ok:
            reasons.append("model_root_mismatch")
        if not max_model_len_ok:
            reasons.append("max_model_len_mismatch")
        if not target_gpu_identity_ok:
            reasons.append("target_gpu_identity_mismatch")
        preflight.update(
            {
                "status": "environment_fail",
                "failure_stage": "B2-Preflight",
                "reason": ",".join(item for item in reasons if item),
            }
        )
    return identity, preflight, {
        "health": health,
        "model_identity": model_identity,
    }


def _g6b2_live_manifest(
    *,
    live_status: str = "NOT_RUN",
    artifact_root: Path | str = "",
    model_profile: Mapping[str, object] | None = None,
    campaign_mode: str = "minimal",
    planned_slot_count: int = 1,
    max_duration_s: int = 600,
    execution_actor: str = "sol",
) -> dict[str, object]:
    profile = _profile(model_profile)
    return {
        "schema_version": "statebus.g6b2.live_manifest.v2",
        "stage": "G6-B2",
        "campaign_mode": campaign_mode,
        "authorization": "user_authorized",
        "allowed_sequence": list(ALLOWED_SEQUENCE),
        "b2_expansion_authorized": campaign_mode in {"campaign", "soak"},
        "execution_actor": execution_actor,
        "planned_slot_count": planned_slot_count,
        "max_duration_s": max_duration_s,
        "concurrency": 1,
        "workload_scope": "bounded_live_executor_fixture",
        "embedding_profile": _embedding_profile(),
        "pair_key_algorithm": "existing _c2c_pair_key",
        "pair_key_fields": list(PAIR_KEY_FIELDS),
        "pair_key_excluded_fields": list(PAIR_KEY_EXCLUDED_FIELDS),
        **{
            key: profile[key]
            for key in (
                "profile_id",
                "model_path",
                "served_model",
                "physical_gpu",
                "gpu_uuid",
                "host",
                "port",
                "dtype",
                "max_model_len",
                "max_num_seqs",
                "max_num_batched_tokens",
                "gpu_memory_utilization",
                "enforce_eager",
            )
        },
        "service_lifecycle_owner": "user",
        "reuse_existing": True,
        "stop_service_on_exit": False,
        "benchmark_superiority": "NOT_ESTABLISHED",
        "live_vllm_gpu_validation": live_status,
        "external_dataset": "NOT_AUTHORIZED",
        "memfd_limitation": "skipped: memfd unavailable; SHM actual-read retained",
        "artifact_root": str(artifact_root),
        **FIXED_METRICS,
    }


def _stage_row(
    row_id: str,
    stage: str,
    status: str,
    reason: str = "",
    refs: Iterable[str] = (),
) -> dict[str, object]:
    return {
        "schema_version": "statebus.g6b2.live_stage_row.v1",
        "profile_id": PROFILE_ID,
        "row_id": row_id,
        "slot_id": "run",
        "lane": "stage",
        "provenance_scope": "live_environment",
        "stage": stage,
        "terminal_status": status,
        "status": "observed" if status == "success" else "failed",
        "reason": reason,
        "failure_stage": "" if status == "success" else stage,
        "environment_limitation": reason if status == "environment_fail" else "",
        "source_receipt_references": list(refs),
    }


def _g6b2_live_row_projection(
    row: Mapping[str, object], *, lane: str
) -> dict[str, object]:
    projected = dict(row)
    projected.setdefault("schema_version", "statebus.g6b2.live_row.v2")
    projected["lane"] = lane
    projected.setdefault(
        "provenance_scope",
        "live_baseline_runtime"
        if lane == "live-baseline"
        else "live_replay_runtime",
    )
    projected.setdefault("source_receipt_references", [])
    projected.setdefault("failure_stage", "")
    projected.setdefault("reason", "")
    projected.setdefault("environment_limitation", "")
    return projected


class G6B2LiveProvider:
    """Single-attempt loopback adapter called only by Runtime dispatch."""

    def __init__(
        self,
        *,
        artifact_root: Path,
        invocation_id: str,
        input_value: float,
        timeout_s: float = 120.0,
        model_profile: Mapping[str, object] | None = None,
    ) -> None:
        self.artifact_root = artifact_root
        self.invocation_id = invocation_id
        self.input_value = input_value
        self.timeout_s = timeout_s
        self.profile = _profile(model_profile)
        self.boundary_rows: list[dict[str, object]] = []

    def __call__(self, provider_request):  # noqa: ANN001
        from statebus.contracts import TransformProgram, TransformStep
        from statebus.runtime.role_providers import ProviderCandidate
        from statebus.utils import sha256_digest

        grant = provider_request.bound_grant.grant
        request_payload = {
            "model": self.profile["served_model"],
            "temperature": 0,
            "max_tokens": 256,
            "stream": False,
            "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [
                {
                    "role": "system",
                    "content": "Return only strict JSON matching the requested transform schema. No markdown.",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "instruction": "Return exactly the value inside response_schema (the JSON object whose only key is operations). Do not include a response_schema wrapper key or repeat the task, columns, or rows.",
                            "task": "Select the value column from the authorized input table.",
                            "columns": ["value"],
                            "rows": [{"value": self.input_value}],
                            "response_schema": {
                                "operations": [
                                    {
                                        "op": "select",
                                        "params": {"columns": ["value"]},
                                    }
                                ]
                            },
                        },
                        separators=(",", ":"),
                    ),
                },
            ],
        }
        request_path = (
            self.artifact_root / "requests" / f"{self.invocation_id}.request.json"
        )
        response_path = (
            self.artifact_root / "requests" / f"{self.invocation_id}.response.json"
        )
        _json_write(
            request_path,
            {
                "profile_id": PROFILE_ID,
                "invocation_id": self.invocation_id,
                "request": request_payload,
            },
        )
        request_started = time.perf_counter()
        response = _g6b2_http_request(
            "POST",
            f"{self.profile['base_url']}/chat/completions",
            payload=request_payload,
            timeout=self.timeout_s,
        )
        request_elapsed_ms = round(
            (time.perf_counter() - request_started) * 1000.0, 3
        )
        _json_write(
            response_path,
            {
                "profile_id": PROFILE_ID,
                "invocation_id": self.invocation_id,
                "response": response,
            },
        )
        try:
            if response["status"] != "observed" or not (
                200 <= int(response["http_status"]) < 300
            ):
                raise ValueError("provider_http_failed")
            body = json.loads(str(response["body"]))
            if body.get("model") != self.profile["served_model"]:
                raise ValueError("provider_model_mismatch")
            choice = body["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ValueError("provider_finish_reason_length")
            parsed = json.loads(choice["message"]["content"])
            expected = [
                {"op": "select", "params": {"columns": ["value"]}}
            ]
            if set(parsed) != {"operations"} or parsed["operations"] != expected:
                raise ValueError("provider_operation_contract_mismatch")
            operation = parsed["operations"][0]
            program = TransformProgram(
                program_id=f"g6b2-live-program:{grant.attempt_id}",
                input_artifact_refs=(grant.input_ref_ids[0],),
                operations=(
                    TransformStep(operation["op"], operation["params"]),
                ),
                output_contract_version=grant.output_contract_version,
            )
            evidence = {
                "status": "observed",
                "invocation_status": "completed",
                "recorded_by": "benchmark_bound_provider_adapter",
                "provider_id": provider_request.bound_grant.provider_id,
                "served_model": body["model"],
                "request_id": str(body.get("id", "")),
                "invocation_id": self.invocation_id,
                "request_reference": str(
                    request_path.relative_to(self.artifact_root)
                ),
                "response_reference": str(
                    response_path.relative_to(self.artifact_root)
                ),
                "candidate_hash": sha256_digest(program.canonical_payload()),
                "source": "Runtime provider call boundary",
                "provider_elapsed_ms": request_elapsed_ms,
            }
            evidence["evidence_hash"] = sha256_digest(evidence)
            evidence["source_receipt_references"] = [
                evidence["request_reference"],
                evidence["response_reference"],
                evidence["evidence_hash"],
            ]
            self.boundary_rows.append(evidence)
            return ProviderCandidate(
                success=True,
                candidate_kind="executor_program",
                payload=program,
            )
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            evidence = {
                "status": "failed",
                "invocation_status": "failed",
                "invocation_id": self.invocation_id,
                "reason": str(exc),
                "request_reference": str(
                    request_path.relative_to(self.artifact_root)
                ),
                "response_reference": str(
                    response_path.relative_to(self.artifact_root)
                ),
                "source": "Runtime provider call boundary",
                "provider_elapsed_ms": request_elapsed_ms,
                "source_receipt_references": [
                    str(request_path.relative_to(self.artifact_root)),
                    str(response_path.relative_to(self.artifact_root)),
                ],
            }
            self.boundary_rows.append(evidence)
            return ProviderCandidate(
                success=False,
                candidate_kind="failure",
                error_code=f"g6b2_live_provider_failed:{exc}",
            )


def _g6b2_make_live_request(
    *,
    row_root: Path,
    artifact_root: Path,
    family_id: str,
    task_family: str,
    task_id: str,
    session_id: str,
    run_id: str,
    value: float,
    memory_root: Path,
    memory_policy: str,
    invocation_id: str,
    commit_replay_class: object | None = None,
    timeout_s: float = 120.0,
):
    from statebus.benchmark.continuous_runner import _g5b_make_request
    from statebus.retrieval import RetrieverFanoutPipeline
    from statebus.runtime.capability_registry import CapabilityRegistry
    from statebus.runtime.provider_registry import (
        ExecutionProviderRegistry,
        PhysicalProviderImplementation,
        project_legacy_provider,
    )
    from statebus.runtime.retrieval_adapter import AdaptiveRetrievalAdapter

    request = _g5b_make_request(
        row_root=row_root,
        family_id=family_id,
        task_family=task_family,
        task_id=task_id,
        session_id=session_id,
        run_id=run_id,
        value=value,
        memory_root=memory_root,
        memory_policy=memory_policy,
        commit_replay_class=commit_replay_class,
    )
    if EMBEDDING_MODE not in {"deterministic", "local"}:
        raise ValueError(f"unsupported_g6b2_embedding_mode:{EMBEDDING_MODE}")
    if EMBEDDING_MODE == "local":
        pipeline = RetrieverFanoutPipeline.with_embedding_mode(
            "local",
            model_path=EMBEDDING_MODEL_PATH,
            device=EMBEDDING_DEVICE,
            top_k=1,
        )
        spec = request.canonical_task_spec

        def retrieve_query(query: str, evidence_request):  # noqa: ANN001
            return pipeline.run(
                task_id=evidence_request.task_id,
                spec=spec,
                planner_scope_payload={"query_text": query},
                enabled_evidence_types=("table",),
            )

        request = replace(
            request,
            bindings=replace(
                request.bindings,
                retrieval_adapter=AdaptiveRetrievalAdapter(retrieve_query),
            ),
        )
    registry = CapabilityRegistry()
    for descriptor in request.registry.descriptors():
        registry.register(
            replace(descriptor, max_runtime_ms=180_000)
            if descriptor.capability_id == "g5b-execute-recipe"
            else descriptor
        )
    providers = ExecutionProviderRegistry()
    for capability_id in ("g5b-retrieve-memory", "g5b-execute-recipe"):
        descriptor = project_legacy_provider(
            registry.get(capability_id),
            provider_id=f"provider-{capability_id}",
        )
        providers.register(descriptor)
        providers.register_implementation(
            PhysicalProviderImplementation.from_descriptor(descriptor)
        )
    handler = G6B2LiveProvider(
        artifact_root=artifact_root,
        invocation_id=invocation_id,
        input_value=value,
        timeout_s=timeout_s,
    )
    request = replace(
        request,
        envelope=replace(request.envelope, max_execution_runtime_ms=200_000),
        registry=registry,
        provider_registry=providers,
        bindings=replace(
            request.bindings,
            bound_provider_handlers={"g5b-execute-recipe": handler},
        ),
    )
    return request, handler


def _memory_embedding_evidence(result) -> dict[str, object]:  # noqa: ANN001
    query = result.context.memory_queries_by_task.get(
        result.runtime_identity.runtime_task_id
    )
    embedding = None if query is None else query.query_embedding
    if embedding is None:
        return {
            "status": "unsupported",
            "reason": "memory_query_embedding_missing",
            "configured": _embedding_profile(),
        }
    return {
        "status": "observed",
        "embedding_id": embedding.embedding_id,
        "embedding_hash": embedding.embedding_hash,
        "dims": embedding.dims,
        "encoding": embedding.encoding,
        "source_text_hash": embedding.source_text_hash,
        "configured": _embedding_profile(),
    }


def _g6b2_runtime_row(
    *,
    result,
    request,
    slot: Mapping[str, object],
    lane: str,
    cache_epoch: str,
    row_id: str,
    provider: G6B2LiveProvider,
    input_value: float,
) -> dict[str, object]:  # noqa: ANN001
    from statebus.benchmark.continuous_runner import _g5b_terminal_status
    from statebus.utils import sha256_digest

    execute_grant = next(
        (
            item.grant
            for item in result.runtime.bound_grants
            if item.grant.step_id == "execute"
        ),
        None,
    )
    execute_admission = next(
        (
            item
            for item in result.runtime.attempt_result_admissions
            if item.step_id == "execute"
        ),
        None,
    )
    execute_dispatch = next(
        (
            item
            for item in result.runtime.dispatches
            if item.step_id == "execute"
        ),
        None,
    )
    output_ref_id = (
        ""
        if execute_dispatch is None or not execute_dispatch.output_refs
        else execute_dispatch.output_refs[0]
    )
    verification = result.context.artifact_verification_receipts.get(output_ref_id)
    quality_hash = (
        ""
        if verification is None or not verification.validator_report_hashes
        else verification.validator_report_hashes[0]
    )
    source_artifact = next(iter(request.bindings.artifacts.values())).artifact
    terminal_status, failure_stage, reason = _g5b_terminal_status(result)
    stored_output = result.context.artifacts.get(output_ref_id)
    output_rows = (
        []
        if stored_output is None
        else [dict(item) for item in stored_output.rows]
    )
    current_input_recomputed = output_rows == [{"value": input_value}]
    if terminal_status == "success" and not current_input_recomputed:
        terminal_status = "quality_fail"
        failure_stage = "execute"
        reason = "current_input_result_mismatch"
    row = {
        "schema_version": "statebus.g6b2.live_row.v2",
        "profile_id": PROFILE_ID,
        "row_id": row_id,
        "slot_id": slot["slot_id"],
        "lane": lane,
        "provenance_scope": (
            "live_baseline_runtime"
            if lane == "live-baseline"
            else "live_replay_runtime"
            if lane == "live-validated-replay"
            else "live_producer_runtime"
        ),
        "family_id": slot["family_id"],
        "round_number": slot["round_number"],
        "repeat_id": slot["repeat_id"],
        "deterministic_seed": slot["deterministic_seed"],
        "task_contract_hash": result.runtime_identity.task_contract.contract_hash,
        "input_lineage_hashes": [source_artifact.blob_hash],
        "quality_contract_hash": sha256_digest(
            {
                "validator_ids": []
                if verification is None
                else list(verification.validator_ids),
                "output_contract_version": ""
                if execute_grant is None
                else execute_grant.output_contract_version,
            }
        ),
        "runtime_root": str(request.runtime_root),
        "workspace_root": str(request.workspace_root),
        "memory_root": str(request.memory_store_root),
        "session_id": result.runtime_identity.session_id,
        "run_id": result.runtime_identity.run_id,
        "attempt_id": "" if execute_grant is None else execute_grant.attempt_id,
        "cache_epoch": cache_epoch,
        "memory_policy": "off"
        if lane == "live-baseline"
        else "validated_replay",
        "runtime_memory_policy": "none"
        if lane == "live-baseline"
        else "validated_replay",
        "terminal_status": terminal_status,
        "failure_stage": failure_stage,
        "reason": reason,
        "environment_limitation": "",
        "runtime_authority": "AdaptiveRuntimeEngine",
        "model_identity": DEFAULT_MODEL_PROFILE["served_model"],
        "service_profile_id": PROFILE_ID,
        "embedding_evidence": _memory_embedding_evidence(result),
        "quality_evidence": {
            "status": "observed" if quality_hash else "unsupported",
            "passed": bool(quality_hash)
            and terminal_status == "success"
            and current_input_recomputed,
            "report_hash": quality_hash,
            "current_input_recomputed": current_input_recomputed,
            "observed_output_rows": output_rows,
        },
        "result_admission": {
            "status": "observed"
            if execute_admission is not None
            else "unsupported",
            "receipt_hash": ""
            if execute_admission is None
            else execute_admission.receipt_hash,
            "step_id": "execute",
        },
    }
    if lane in {"live-baseline", "live-producer"}:
        row["provider_invocation_evidence"] = (
            dict(provider.boundary_rows[0])
            if len(provider.boundary_rows) == 1
            else {}
        )
    else:
        observation = (
            dict(result.context.replay_observations[0])
            if len(result.context.replay_observations) == 1
            else {}
        )
        record = (
            result.context.memory_consumption_records[0]
            if len(result.context.memory_consumption_records) == 1
            else None
        )
        binding = next(
            (
                item
                for item in result.runtime.execution_bindings
                if item.step_id == "execute"
            ),
            None,
        )
        eligibility = next(iter(result.runtime.replay_eligibility_receipts), None)
        row.update(
            {
                "provider_not_started_observation": observation,
                "recipe_recomputed": bool(record and record.recipe_recomputed),
                "consumer_provider_boundary_call_count": len(
                    provider.boundary_rows
                ),
                "memory_consumption_receipt": None
                if record is None
                else record.canonical_payload(),
                "capability_grant": None
                if execute_grant is None
                else execute_grant.canonical_payload(),
                "execution_binding": None
                if binding is None
                else binding.canonical_payload(),
                "replay_eligibility_receipt": None
                if eligibility is None
                else eligibility.canonical_payload(),
            }
        )
    refs = []
    provider_evidence = row.get("provider_invocation_evidence")
    if isinstance(provider_evidence, Mapping):
        refs.extend(provider_evidence.get("source_receipt_references", ()))
    observation = row.get("provider_not_started_observation")
    if isinstance(observation, Mapping):
        refs.extend(
            str(observation.get(name, ""))
            for name in (
                "observation_id",
                "execution_binding_hash",
                "capability_grant_hash",
                "memory_admission_receipt_hash",
                "replay_eligibility_receipt_hash",
                "quality_report_hash",
                "attempt_result_admission_receipt_hash",
            )
        )
    refs.extend(
        [
            quality_hash,
            "" if execute_admission is None else execute_admission.receipt_hash,
        ]
    )
    row["source_receipt_references"] = sorted(
        {str(item) for item in refs if str(item)}
    )
    return row


def _runtime_evidence(
    artifact_root: Path, slot_id: str, lane: str, result
) -> None:  # noqa: ANN001
    payload = {
        "profile_id": PROFILE_ID,
        "slot_id": slot_id,
        "lane": lane,
        "runtime_identity": result.runtime_identity.canonical_payload(),
        "completed": result.completed,
        "manifest_path": str(result.manifest_path),
        "dispatches": [item.__dict__ for item in result.runtime.dispatches],
        "bound_grants": [
            item.canonical_payload() for item in result.runtime.bound_grants
        ],
        "execution_bindings": [
            item.canonical_payload() for item in result.runtime.execution_bindings
        ],
        "attempt_result_admissions": [
            item.canonical_payload()
            for item in result.runtime.attempt_result_admissions
        ],
        "replay_observations": [
            dict(item) for item in result.context.replay_observations
        ],
        "memory_query_embeddings": {
            task_id: {
                "embedding_id": query.query_embedding.embedding_id,
                "embedding_hash": query.query_embedding.embedding_hash,
                "dims": query.query_embedding.dims,
                "encoding": query.query_embedding.encoding,
                "source_text_hash": query.query_embedding.source_text_hash,
            }
            for task_id, query in result.context.memory_queries_by_task.items()
            if query.query_embedding is not None
        },
        "memory_consumption_records": [
            item.canonical_payload()
            for item in result.context.memory_consumption_records
        ],
    }
    _json_write(
        artifact_root
        / "runtime_evidence"
        / slot_id
        / lane
        / "runtime.json",
        payload,
    )


def _g6b2_campaign_slots(mode: str, pairs: int) -> list[dict[str, object]]:
    if mode == "minimal":
        if pairs != 1:
            raise ValueError("minimal_pairs_must_equal_one")
        return [
            {
                "slot_id": "cross_period_financial-r1-p1",
                "family_id": "cross_period_financial",
                "round_number": 1,
                "repeat_id": 1,
                "deterministic_seed": 62101001,
                "execution_status": "planned",
            }
        ]
    maximum = 120 if mode == "campaign" else 480
    full_count = 120 if mode == "campaign" else 480
    if pairs < 1 or pairs > maximum:
        raise ValueError(f"pairs_out_of_range:{mode}:{pairs}:{maximum}")
    base = 63_000_000 if mode == "campaign" else 64_000_000
    families = ("cross_period_financial", "incident_diagnosis")
    repeats = 30 if mode == "campaign" else 120
    slots = []
    for repeat_id in range(1, repeats + 1):
        for round_number in (1, 2):
            for family_index, family_id in enumerate(families, start=1):
                slots.append(
                    {
                        "slot_id": f"{family_id}-r{round_number}-p{repeat_id}",
                        "family_id": family_id,
                        "round_number": round_number,
                        "repeat_id": repeat_id,
                        "deterministic_seed": base
                        + family_index * 100_000
                        + round_number * 1_000
                        + repeat_id,
                        "execution_status": "planned",
                    }
                )
    if len(slots) != full_count:
        raise AssertionError("campaign_slot_count_invalid")
    slots = slots[:pairs]
    if len({item["deterministic_seed"] for item in slots}) != len(slots):
        raise ValueError("slot_seed_collision")
    return slots


def _g6b2_live_pair_projection(
    baseline_rows: Iterable[Mapping[str, object]],
    replay_rows: Iterable[Mapping[str, object]],
    *,
    model_profile: Mapping[str, object] | None = None,
    mode: str = "minimal",
    planned_slots: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    from statebus.benchmark.scoring import _g6b2_validate_live_campaign

    return _g6b2_validate_live_campaign(
        list(baseline_rows),
        list(replay_rows),
        model_profile=_profile(model_profile),
        mode=mode,
        planned_slots=list(planned_slots),
    )


def _g6b2_live_failure_denominator(
    baseline_rows: Iterable[Mapping[str, object]],
    replay_rows: Iterable[Mapping[str, object]],
    pair_projection: Mapping[str, object],
    *,
    producer_rows: Iterable[Mapping[str, object]] = (),
    stage_rows: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    baseline = [dict(row) for row in baseline_rows]
    replay = [dict(row) for row in replay_rows]
    producer = [dict(row) for row in producer_rows]
    stages = [dict(row) for row in stage_rows]
    physical = [*baseline, *replay, *producer, *stages]
    pairs = [
        dict(row)
        for row in pair_projection.get("pairings", ())
        if isinstance(row, Mapping)
    ]
    failures = [
        dict(row)
        for row in pair_projection.get("failure_rows", ())
        if isinstance(row, Mapping)
    ]
    unmatched_ids = {
        str(row.get("row_id", ""))
        for row in failures
        if row.get("status") == "unmatched"
    }
    result: dict[str, object] = {
        "schema_version": "statebus.g6b2.live_failure_denominator.v2",
        "status": "observed",
        "attempted": len(physical),
        "measurement_attempted": len(baseline) + len(replay),
        "producer_row_count": len(producer),
        "stage_row_count": len(stages),
        "baseline_row_count": len(baseline),
        "replay_row_count": len(replay),
        "matched_pair_count": len(pairs),
        "eligible_matched_pair_count": sum(
            row.get("status") == "eligible" for row in pairs
        ),
        "rejected_matched_pair_count": sum(
            row.get("status") == "rejected" for row in pairs
        ),
        "unmatched_row_count": len(unmatched_ids),
        "row_ids": [str(row.get("row_id", "")) for row in physical],
        "denominator_linkage": [
            str(row.get("row_id", "")) for row in physical
        ],
        "negative_index_count": len(failures),
    }
    for status in TERMINAL_STATUSES:
        result[status] = sum(
            row.get("terminal_status") == status for row in physical
        )
    unique = (
        len(set(result["row_ids"])) == len(physical)
        and all(result["row_ids"])
    )
    result["arithmetic_closed"] = bool(
        unique
        and result["attempted"]
        == result["measurement_attempted"] + len(producer) + len(stages)
        and result["attempted"]
        == sum(int(result[name]) for name in TERMINAL_STATUSES)
    )
    result["row_arithmetic_closed"] = bool(
        result["measurement_attempted"]
        == 2 * result["matched_pair_count"] + result["unmatched_row_count"]
    )
    return result


def _negative_index(pair_projection: Mapping[str, object]) -> dict[str, object]:
    records = []
    for index, raw in enumerate(pair_projection.get("failure_rows", ())):
        row = dict(raw)
        records.append(
            {
                "index_id": f"negative:{index + 1}",
                "linkage_kind": "physical_row",
                "denominator_linkage": str(row.get("row_id", "")),
                "failure_stage": row.get("failure_stage", "pairing"),
                "reason": row.get("reason", ""),
            }
        )
    for index, raw in enumerate(pair_projection.get("pairings", ())):
        pair = dict(raw)
        if pair.get("status") != "rejected":
            continue
        records.append(
            {
                "index_id": f"rejected-pair:{index + 1}",
                "linkage_kind": "matched_pair",
                "denominator_linkage": str(pair.get("pair_key", "")),
                "baseline_row_id": pair.get("baseline_row_id", ""),
                "replay_row_id": pair.get("replay_row_id", ""),
                "failure_stage": "pair_validation",
                "reason": pair.get("reason", ""),
            }
        )
    return {
        "schema_version": "statebus.g6b2.live_negative_row_index.v1",
        "records": records,
    }


def _physical_rows(
    *groups: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [dict(row) for group in groups for row in group]


def _embedding_rows_valid(
    *groups: Iterable[Mapping[str, object]],
) -> bool:
    if EMBEDDING_MODE != "local":
        return True
    rows = _physical_rows(*groups)
    expected_encoding = f"sentence-transformers:{Path(EMBEDDING_MODEL_PATH).name}"
    evidence = [row.get("embedding_evidence") for row in rows]
    return bool(
        rows
        and all(isinstance(item, Mapping) for item in evidence)
        and all(item.get("status") == "observed" for item in evidence)
        and all(item.get("encoding") == expected_encoding for item in evidence)
        and all(int(item.get("dims", 0)) > 16 for item in evidence)
        and len({int(item.get("dims", 0)) for item in evidence}) == 1
    )


def _g6b2_write_artifacts(
    artifact_root: Path | str,
    *,
    gpu_preflight: Mapping[str, object],
    vllm_health: Mapping[str, object],
    vllm_model_identity: Mapping[str, object],
    baseline_rows: Iterable[Mapping[str, object]] = (),
    replay_rows: Iterable[Mapping[str, object]] = (),
    producer_rows: Iterable[Mapping[str, object]] = (),
    stage_rows: Iterable[Mapping[str, object]] = (),
    pair_projection: Mapping[str, object] | None = None,
    failure_denominator: Mapping[str, object] | None = None,
    metrics: Mapping[str, object] | None = None,
    status: str = "FAILED",
    model_profile: Mapping[str, object] | None = None,
    create_root: bool = True,
    mode: str = "minimal",
    planned_slots: Iterable[Mapping[str, object]] = (),
    max_duration_s: int = 600,
) -> Path:
    from statebus.benchmark.metric_aggregation import _g6b2_metric_availability

    root = Path(artifact_root)
    if create_root:
        root.mkdir(parents=True, exist_ok=False)
    elif not root.is_dir():
        raise FileNotFoundError(root)
    baseline = [
        _g6b2_live_row_projection(row, lane="live-baseline")
        for row in baseline_rows
    ]
    replay = [
        _g6b2_live_row_projection(row, lane="live-validated-replay")
        for row in replay_rows
    ]
    producer = [
        _g6b2_live_row_projection(row, lane="live-producer")
        for row in producer_rows
    ]
    stages = [dict(row) for row in stage_rows]
    slots = [dict(item) for item in planned_slots]
    pairs = dict(
        pair_projection
        or _g6b2_live_pair_projection(
            baseline,
            replay,
            model_profile=model_profile,
            mode=mode,
            planned_slots=slots,
        )
    )
    denominator = dict(
        failure_denominator
        or _g6b2_live_failure_denominator(
            baseline,
            replay,
            pairs,
            producer_rows=producer,
            stage_rows=stages,
        )
    )
    projected_metrics = dict(
        metrics
        or _g6b2_metric_availability(
            baseline,
            replay,
            pairs.get("pairings", ()),
            pairs.get("failure_rows", ()),
            denominator,
            vllm_health,
            producer_rows=producer,
            stage_rows=stages,
        )
    )
    successful_statuses = {
        "MINIMAL_PAIR_VERIFIED_FOR_USER_CAMPAIGN",
        "CAMPAIGN_VERIFIED",
        "SOAK_VERIFIED",
    }
    complete = status in successful_statuses
    live_status = (
        "OBSERVED_FOR_MINIMAL_PAIR_ONLY"
        if status == "MINIMAL_PAIR_VERIFIED_FOR_USER_CAMPAIGN"
        else "OBSERVED_FOR_PROFILE_CAMPAIGN_ONLY"
        if complete
        else "FAILED"
    )
    embedding_probe = (
        _json_read(root / "embedding_probe.json")
        if (root / "embedding_probe.json").is_file()
        else {}
    )
    embedding_device_evidence = embedding_probe.get("device_evidence", {})
    embedding_device_evidence = (
        embedding_device_evidence
        if isinstance(embedding_device_evidence, Mapping)
        else {}
    )
    service_identity = (
        _json_read(root / "service_identity.json")
        if (root / "service_identity.json").is_file()
        else {}
    )
    manifest = _g6b2_live_manifest(
        live_status=live_status,
        artifact_root=root,
        campaign_mode=mode,
        planned_slot_count=len(slots) or 1,
        max_duration_s=max_duration_s,
        execution_actor="sol" if mode == "minimal" else "user",
    )
    checks = {
        "preflight": gpu_preflight.get("status") == "observed",
        "health": vllm_health.get("status") == "observed",
        "model_identity": vllm_model_identity.get("identity_status")
        == "matched",
        "container_profile": (
            (root / "container_runtime_profile.json").is_file()
            and _json_read(root / "container_runtime_profile.json").get("status")
            == "observed"
        ),
        "stage_order": [row.get("stage") for row in stages]
        == list(ALLOWED_SEQUENCE[: len(stages)]),
        "pair_projection": pairs.get("status") == "accepted",
        "eligible_pair_count": denominator.get("eligible_matched_pair_count")
        == (1 if mode == "minimal" else len(slots)),
        "row_arithmetic": denominator.get("arithmetic_closed") is True
        and denominator.get("row_arithmetic_closed") is True,
        "embedding_evidence": _embedding_rows_valid(
            baseline, producer, replay
        )
        and (
            EMBEDDING_MODE != "local"
            or (
                embedding_probe.get("status") == "observed"
                and embedding_device_evidence.get("physical_gpu")
                == EMBEDDING_PHYSICAL_GPU
                and embedding_device_evidence.get("parameter_devices")
                == ["cuda:0"]
                and embedding_device_evidence.get("parameter_device_ok") is True
            )
        ),
        "service_not_stopped": service_identity.get("service_stop_called") is False,
    }
    final_status = (
        status
        if all(checks.values()) and complete
        else "INCOMPLETE"
        if status == "INCOMPLETE"
        else "FAILED"
    )
    failed_row = next(
        (
            row
            for row in _physical_rows(stages, baseline, producer, replay)
            if row.get("terminal_status") != "success"
        ),
        {},
    )
    acceptance = {
        "schema_version": "statebus.g6b2.acceptance.v2",
        "profile_id": PROFILE_ID,
        "status": final_status,
        "mode": mode,
        "checks": checks,
        "eligible_live_pair_count": denominator.get(
            "eligible_matched_pair_count", 0
        ),
        "benchmark_superiority": "NOT_ESTABLISHED",
        "service_lifecycle_owner": "operator",
        "service_stop_called": False,
        "live_vllm_gpu_validation": live_status
        if final_status != "FAILED"
        else "FAILED",
        "observed_metrics": projected_metrics,
        **FIXED_METRICS,
        "failure_stage": str(failed_row.get("failure_stage", "")),
        "reason": str(failed_row.get("reason", "")),
        "artifact_references": {
            "service_identity": "service_identity.json",
            "gpu_preflight": "gpu_preflight.json",
            "vllm_health": "vllm_health.json",
            "vllm_model_identity": "vllm_model_identity.json",
            "container_runtime_profile": "container_runtime_profile.json",
            "docker_smoke": "docker_smoke.json",
            "embedding_probe": "embedding_probe.json",
            "manifest": "live_manifest.json",
            "slots": "live_slots.json",
            "stage_rows": "live_stage_rows.json",
            "producer_rows": "live_producer_rows.json",
            "baseline_rows": "live_baseline_rows.json",
            "replay_rows": "live_replay_rows.json",
            "pair_projection": "live_pair_projection.json",
            "negative_index": "live_negative_row_index.json",
            "denominator": "live_failure_denominator.json",
            "metrics": "live_metric_availability.json",
        },
    }
    payloads = {
        "gpu_preflight.json": dict(gpu_preflight),
        "vllm_health.json": dict(vllm_health),
        "vllm_model_identity.json": dict(vllm_model_identity),
        "live_manifest.json": manifest,
        "live_slots.json": {
            "schema_version": "statebus.g6b2.live_slots.v1",
            "slots": slots,
        },
        "live_stage_rows.json": {
            "schema_version": "statebus.g6b2.live_stage_rows.v1",
            "rows": stages,
        },
        "live_producer_rows.json": {
            "schema_version": "statebus.g6b2.live_producer_rows.v1",
            "rows": producer,
        },
        "live_baseline_rows.json": {
            "schema_version": "statebus.g6b2.live_baseline_rows.v2",
            "rows": baseline,
        },
        "live_replay_rows.json": {
            "schema_version": "statebus.g6b2.live_replay_rows.v2",
            "rows": replay,
        },
        "live_pair_projection.json": pairs,
        "live_negative_row_index.json": _negative_index(pairs),
        "live_failure_denominator.json": denominator,
        "live_metric_availability.json": {
            "schema_version": "statebus.g6b2.live_metric_availability.v2",
            "metrics": projected_metrics,
        },
        "g6b2_acceptance.json": acceptance,
        "final_gate_status.json": {
            "schema_version": "statebus.g6b2.final_gate_status.v1",
            "profile_id": PROFILE_ID,
            "status": final_status,
            "checks": checks,
            "eligible_live_pair_count": denominator.get(
                "eligible_matched_pair_count", 0
            ),
            "service_stop_called": False,
        },
    }
    for name, payload in payloads.items():
        _json_write(root / name, payload, exclusive=not (root / name).exists())
    return root


def _default_artifact_root(base: Path, mode: str) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    embedding_label = "-real-embedding" if EMBEDDING_MODE == "local" else ""
    for suffix in range(1, 1000):
        root = base / (
            f"g6b2-live-validation-{stamp}-{str(DEFAULT_MODEL_PROFILE['served_model'])}-gpu{int(DEFAULT_MODEL_PROFILE['physical_gpu'])}-u050-"
            f"{mode}{embedding_label}-{os.getpid()}-{suffix}"
        )
        if not root.exists():
            return root.resolve()
    raise RuntimeError("artifact_root_exhausted")


def run_g6b2_embedding_probe(
    *,
    artifact_root: Path | str,
) -> dict[str, object]:
    from statebus.memory.embedding import SentenceTransformerEmbeddingEncoder
    from statebus.runtime.preflight import runtime_preflight
    from statebus.utils import sha256_digest

    root = Path(artifact_root)
    preflight = runtime_preflight(
        role_path_mode="local_vllm",
        embedding_mode="local",
        embedding_model_path=EMBEDDING_MODEL_PATH,
        embedding_device=EMBEDDING_DEVICE,
    )
    if not preflight.ok:
        payload = {
            "schema_version": "statebus.g6b2.embedding_probe.v2",
            "profile_id": PROFILE_ID,
            "status": "environment_fail",
            "embedding_profile": _embedding_profile(),
            "preflight": preflight.canonical_payload(),
            "reason": "embedding_preflight_failed",
        }
        _json_write(root / "embedding_probe.json", payload)
        return payload

    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("embedding_cuda_unavailable_after_preflight")
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    encoder = SentenceTransformerEmbeddingEncoder(
        model_path=EMBEDDING_MODEL_PATH,
        device=EMBEDDING_DEVICE,
    )
    cold_started = time.perf_counter()
    cold = encoder.encode(
        embedding_id="g6b2-embedding-probe-cold",
        text="cross period financial related metric",
    )
    torch.cuda.synchronize()
    cold_ms = round((time.perf_counter() - cold_started) * 1000.0, 3)
    warm_started = time.perf_counter()
    warm = encoder.encode(
        embedding_id="g6b2-embedding-probe-warm",
        text="incident diagnosis related metric",
    )
    torch.cuda.synchronize()
    warm_ms = round((time.perf_counter() - warm_started) * 1000.0, 3)
    model = encoder._ensure_model()
    parameter_devices = sorted(
        {str(parameter.device) for parameter in model.parameters()}
    )
    parameter_device_ok = parameter_devices == ["cuda:0"]
    cuda_properties = torch.cuda.get_device_properties(0)
    config_path = Path(EMBEDDING_MODEL_PATH) / "config.json"
    payload = {
        "schema_version": "statebus.g6b2.embedding_probe.v2",
        "profile_id": PROFILE_ID,
        "status": "observed" if parameter_device_ok else "environment_fail",
        "embedding_profile": _embedding_profile(),
        "preflight": preflight.canonical_payload(),
        "model_config_hash": (
            sha256_digest(config_path.read_bytes())
            if config_path.is_file()
            else ""
        ),
        "torch": {
            "version": torch.__version__,
            "cuda_available": True,
            "device_count": torch.cuda.device_count(),
            "device_name": torch.cuda.get_device_name(0),
            "device_uuid": str(getattr(cuda_properties, "uuid", "")),
        },
        "device_evidence": {
            "physical_gpu": EMBEDDING_PHYSICAL_GPU,
            "container_device": "cuda:0",
            "requested_device": EMBEDDING_DEVICE,
            "parameter_devices": parameter_devices,
            "parameter_device_ok": parameter_device_ok,
            "cuda_visible_devices": os.getenv("CUDA_VISIBLE_DEVICES", ""),
        },
        "embedding": {
            "encoding": cold.encoding,
            "dims": cold.dims,
            "cold_vector_hash": cold.embedding_hash,
            "warm_vector_hash": warm.embedding_hash,
            "cold_encode_ms": cold_ms,
            "warm_encode_ms": warm_ms,
        },
        "cuda_memory": {
            "allocated_bytes": torch.cuda.memory_allocated(),
            "reserved_bytes": torch.cuda.memory_reserved(),
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        },
        "claim_scope": (
            "local embedding load/encode observation only; shared-GPU "
            "performance superiority is not established"
        ),
        "reason": "" if parameter_device_ok else "embedding_parameter_device_mismatch",
    }
    _json_write(root / "embedding_probe.json", payload)
    return payload


def run_g6b2_container_profile(
    *,
    artifact_root: Path | str,
    container_name: str = "statebus-runtime",
) -> dict[str, object]:
    root = Path(artifact_root)
    rc, output, error = _run(["docker", "inspect", container_name])
    try:
        inspected = json.loads(output)[0] if rc == 0 else {}
    except (IndexError, json.JSONDecodeError, TypeError):
        inspected = {}
    mounts = {
        str(item.get("Destination", "")): str(item.get("Source", ""))
        for item in inspected.get("Mounts", [])
        if isinstance(item, Mapping)
    }
    host_config = inspected.get("HostConfig", {})
    host_config = host_config if isinstance(host_config, Mapping) else {}
    device_requests = host_config.get("DeviceRequests", [])
    device_requests = device_requests if isinstance(device_requests, list) else []
    workspace_root = str(Path.cwd().resolve().parent)
    os_root = str(Path.cwd().resolve())
    workspace_mount_ok = (
        mounts.get("/workspace/statebus") == workspace_root
        or mounts.get("/workspace/statebus/os") == os_root
    )
    embedding_gpu_ok = any(
        str(EMBEDDING_PHYSICAL_GPU)
        in [str(item) for item in request.get("DeviceIDs", [])]
        for request in device_requests
        if isinstance(request, Mapping)
    )
    checks = {
        "inspect_observed": rc == 0 and bool(inspected),
        "container_name": inspected.get("Name") == f"/{container_name}",
        "running": bool(dict(inspected.get("State", {})).get("Running")),
        "host_network": host_config.get("NetworkMode") == "host",
        "workspace_mount": workspace_mount_ok,
        "statebus_home_mount": "/statebus" in mounts,
        "model_mount": mounts.get("/data/models") == "/data/models",
        "host_python_mount": "/home/qcrs/statebus/conda-envs/statebus_host"
        in mounts,
        "embedding_model_mount": "/statebus/models" in mounts,
        "embedding_physical_gpu": embedding_gpu_ok,
    }
    passed = all(checks.values())
    config = inspected.get("Config", {})
    config = config if isinstance(config, Mapping) else {}
    payload = {
        "schema_version": "statebus.g6b2.container_runtime_profile.v1",
        "profile_id": PROFILE_ID,
        "status": "observed" if passed else "environment_fail",
        "container_name": container_name,
        "container_user": str(config.get("User", "")),
        "image": str(config.get("Image", "")),
        "network_mode": str(host_config.get("NetworkMode", "")),
        "mounts": mounts,
        "device_requests": device_requests,
        "embedding_physical_gpu": EMBEDDING_PHYSICAL_GPU,
        "embedding_container_device": "cuda:0",
        "checks": checks,
        "reason": "" if passed else (error or "container_runtime_profile_mismatch"),
        "source": "docker inspect after run_g6b2_os_container verify/smoke",
    }
    _json_write(root / "container_runtime_profile.json", payload)
    return payload


def _nontext_artifact_root(base: Path, mode: str) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for suffix in range(1, 1000):
        root = base / (
            f"g6b2-real-embedding-nontext-{stamp}-{mode}-"
            f"{os.getpid()}-{suffix}"
        )
        if not root.exists():
            return root.resolve()
    raise RuntimeError("nontext_artifact_root_exhausted")


def run_g6b2_nontext_validation(
    *,
    output_base: Path | str,
    full: bool,
) -> dict[str, object]:
    from statebus.benchmark.adaptive_formal_mainline import _run_adaptive_case
    from statebus.benchmark.semantic_holdout import (
        _role_request_gold_key_gate,
        _semantic_state_case_gate,
        load_semantic_holdout_cases,
    )

    mode = "full" if full else "targeted"
    root = _nontext_artifact_root(Path(output_base), mode)
    root.mkdir(parents=True, exist_ok=False)
    probe = run_g6b2_embedding_probe(artifact_root=root)
    selected_ids = None if full else {
        "semantic-holdout-s1",
        "semantic-holdout-s3",
        "semantic-holdout-s4",
    }
    cases = [
        case
        for case in load_semantic_holdout_cases()
        if selected_ids is None or case.task_id in selected_ids
    ]
    case_rows: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for case in cases:
        case_root = root / "cases" / case.task_id
        shape = str(case.sample.scenario_tags[0])
        try:
            summary = _run_adaptive_case(
                case,
                case_root=case_root,
                embedding_model_path=EMBEDDING_MODEL_PATH,
                embedding_device=EMBEDDING_DEVICE,
            )
            selected = [
                str(item) for item in summary.get("selected_capability_ids", ())
            ]
            retriever = next(
                (item for item in selected if item.startswith("retrieve_")), ""
            )
            semantic_selected = retriever == "retrieve_semantic_evidence_v1"
            release_path = case_root / "state_release_reclaim.json"
            release_receipts = (
                _json_read(release_path) if release_path.is_file() else {}
            )
            semantic_gate = (
                _semantic_state_case_gate(summary) if semantic_selected else False
            )
            route_gate = (
                retriever == "retrieve_table_evidence_v1"
                if shape == "table_only"
                else bool(retriever)
            )
            row_ok = bool(
                summary.get("ok")
                and summary.get("system_gate_passed")
                and _role_request_gold_key_gate(summary)
                and route_gate
                and (
                    not semantic_selected
                    or (semantic_gate and bool(release_receipts))
                )
            )
            case_rows.append(
                {
                    "task_id": case.task_id,
                    "input_shape": shape,
                    "retriever_capability": retriever,
                    "semantic_selected": semantic_selected,
                    "semantic_state_gate": semantic_gate,
                    "release_reclaim_receipts": len(release_receipts),
                    "quality_passed": bool(summary.get("ok")),
                    "system_gate_passed": bool(
                        summary.get("system_gate_passed")
                    ),
                    "ok": row_ok,
                    "summary_path": str(case_root / "summary.json"),
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "task_id": case.task_id,
                    "input_shape": shape,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            break
    expected_count = 8 if full else 3
    shapes = {str(row["input_shape"]) for row in case_rows}
    gates = {
        "embedding_probe": probe.get("status") == "observed",
        "case_count": len(case_rows) == expected_count and not failures,
        "quality_and_runtime": bool(case_rows)
        and all(bool(row["ok"]) for row in case_rows),
        "target_shapes": (
            shapes
            == {"narrative_only", "table_only", "mixed_narrative_table"}
            if not full
            else len(shapes) == 3
        ),
        "dense_semantic_state_observed": any(
            bool(row["semantic_selected"])
            and bool(row["semantic_state_gate"])
            and int(row["release_reclaim_receipts"]) > 0
            for row in case_rows
        ),
        "table_structure_observed": any(
            row["retriever_capability"] == "retrieve_table_evidence_v1"
            for row in case_rows
        ),
    }
    result = {
        "schema_version": "statebus.g6b2.nontext_real_embedding.v1",
        "profile_id": PROFILE_ID,
        "mode": mode,
        "artifact_root": str(root),
        "embedding_profile": _embedding_profile(),
        "case_count": expected_count,
        "cases": case_rows,
        "failures": failures,
        "gates": gates,
        "status": "passed" if all(gates.values()) else "failed",
        "coverage": {
            "structured_nontext": "table/json/csv",
            "dense_nontext_state": "SemanticStateRef embedding matrix",
            "multimodal_image_audio_video": "NOT_TESTED",
        },
        "benchmark_superiority": "NOT_ESTABLISHED",
    }
    _json_write(root / "summary.json", result)
    return result


def run_g6b2_preflight(
    *,
    artifact_root: Path | str | None = None,
    output_base: Path | str = "artifacts",
    service_runtime_dir: Path | str = "/home/qcrs/statebus/work/vllm-qwen3-32b-gpu2-u050",
    coexist_pids: Iterable[int] = (),
    mode: str = "minimal",
    planned_slots: int = 1,
    max_duration_s: int = 600,
    **_ignored,
) -> dict[str, object]:
    root = (
        Path(artifact_root)
        if artifact_root
        else _default_artifact_root(Path(output_base), mode)
    )
    root.mkdir(parents=True, exist_ok=False)
    identity, preflight, probes = _g6b2_service_identity(
        Path(service_runtime_dir), coexist_pids
    )
    _json_write(root / "service_identity.json", identity)
    _json_write(root / "gpu_preflight.json", preflight)
    _json_write(root / "vllm_health.json", probes["health"])
    _json_write(root / "vllm_model_identity.json", probes["model_identity"])
    stages = [
        _stage_row(
            "stage:preflight",
            "B2-Preflight",
            "success"
            if preflight["status"] == "observed"
            else "environment_fail",
            str(preflight.get("reason", "")),
            (
                "service_identity.json",
                "gpu_preflight.json",
                "vllm_health.json",
                "vllm_model_identity.json",
            ),
        )
    ]
    _json_write(root / "live_stage_rows.partial.json", {"rows": stages})
    _json_write(
        root / "run_config.json",
        {
            "profile_id": PROFILE_ID,
            "embedding_profile": _embedding_profile(),
            "mode": mode,
            "planned_slot_count": planned_slots,
            "max_duration_s": max_duration_s,
            "service_runtime_dir": str(service_runtime_dir),
            "coexist_pids": [int(item) for item in coexist_pids],
        },
    )
    if preflight["status"] != "observed":
        slots = _g6b2_campaign_slots(mode, planned_slots)
        _g6b2_write_artifacts(
            root,
            gpu_preflight=preflight,
            vllm_health=probes["health"],
            vllm_model_identity=probes["model_identity"],
            stage_rows=stages,
            status="FAILED",
            mode=mode,
            planned_slots=slots,
            max_duration_s=max_duration_s,
            create_root=False,
        )
    return {
        "status": "passed"
        if preflight["status"] == "observed"
        else "failed",
        "artifact_root": str(root),
        "gpu_preflight": preflight,
    }


def run_g6b2_live_smoke(
    preflight: Mapping[str, object],
    *,
    artifact_root: Path | str,
    timeout_s: float = 120.0,
    smoke_runner=None,
) -> dict[str, object]:
    root = Path(artifact_root)
    if preflight.get("status") != "observed":
        return {
            "status": "failed",
            "failure_stage": "B2-Preflight",
            "reason": "preflight_failed",
        }
    if smoke_runner is not None:
        smoke = dict(smoke_runner())
    else:
        payload = {
            "model": DEFAULT_MODEL_PROFILE["served_model"],
            "temperature": 0,
            "max_tokens": 256,
            "stream": False,
            "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Return only this JSON: "
                        '{"operations":[{"op":"select","params":{"columns":["value"]}}]}'
                    ),
                }
            ],
        }
        _json_write(root / "requests" / "smoke.request.json", payload)
        response = _g6b2_http_request(
            "POST",
            f"{DEFAULT_MODEL_PROFILE['base_url']}/chat/completions",
            payload=payload,
            timeout=timeout_s,
        )
        _json_write(root / "requests" / "smoke.response.json", response)
        try:
            body = json.loads(str(response["body"]))
            content = json.loads(body["choices"][0]["message"]["content"])
            valid = bool(
                response["status"] == "observed"
                and body.get("model") == DEFAULT_MODEL_PROFILE["served_model"]
                and body["choices"][0].get("finish_reason") != "length"
                and content
                == {
                    "operations": [
                        {"op": "select", "params": {"columns": ["value"]}}
                    ]
                }
            )
            reason = "" if valid else "smoke_contract_mismatch"
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            valid = False
            reason = "smoke_response_invalid"
        smoke = {
            "schema_version": "statebus.g6b2.live_smoke.v1",
            "profile_id": PROFILE_ID,
            "terminal_status": "success" if valid else "runtime_fail",
            "status": "observed" if valid else "failed",
            "reason": reason,
            "request_reference": "requests/smoke.request.json",
            "response_reference": "requests/smoke.response.json",
            "source_receipt_references": [
                "requests/smoke.request.json",
                "requests/smoke.response.json",
            ],
        }
    _json_write(root / "live_smoke.json", smoke)
    return {
        "status": "passed"
        if smoke.get("terminal_status") == "success"
        else "failed",
        "failure_stage": ""
        if smoke.get("terminal_status") == "success"
        else "B2-Live-Smoke",
        "smoke": smoke,
    }


def _execute_slot(
    artifact_root: Path,
    runtime_base: Path,
    slot: Mapping[str, object],
    *,
    timeout_s: float,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    from statebus.contracts import ReplayClass
    from statebus.runtime.driver import RuntimeDriver

    family = str(slot["family_id"])
    task_family = (
        "financial_report_analysis"
        if family == "cross_period_financial"
        else "incident_diagnosis"
    )
    slug = str(slot["slot_id"])
    slot_root = runtime_base / slug
    minimal = slot["deterministic_seed"] == 62101001
    current_value = (
        101.0
        if minimal
        else float(int(slot["round_number"]) * 1000 + int(slot["repeat_id"]))
    )
    producer_value = (
        100.0 if minimal else float(int(slot["round_number"]) * 1000)
    )
    baseline_request, baseline_provider = _g6b2_make_live_request(
        row_root=slot_root / "baseline",
        artifact_root=artifact_root,
        family_id=family,
        task_family=task_family,
        task_id=f"g6b2-{slug}-baseline",
        session_id=f"g6b2-baseline-session:{slug}",
        run_id=f"g6b2-baseline-run:{slug}",
        value=current_value,
        memory_root=slot_root / "baseline-memory",
        memory_policy="none",
        invocation_id=f"{slug}-baseline",
        timeout_s=timeout_s,
    )
    baseline_started = time.perf_counter()
    baseline_result = RuntimeDriver().run_mode(
        "adaptive_bounded", adaptive_request=baseline_request
    )
    baseline = _g6b2_runtime_row(
        result=baseline_result,
        request=baseline_request,
        slot=slot,
        lane="live-baseline",
        cache_epoch=f"baseline:{slug}",
        row_id=f"baseline:{slug}",
        provider=baseline_provider,
        input_value=current_value,
    )
    baseline["runtime_elapsed_ms"] = round(
        (time.perf_counter() - baseline_started) * 1000.0, 3
    )
    _runtime_evidence(artifact_root, slug, "baseline", baseline_result)
    if baseline["terminal_status"] != "success":
        raise RuntimeError(
            json.dumps({"stage": "baseline", "row": baseline}, default=str)
        )

    memory_root = slot_root / "replay-memory"
    producer_request, producer_provider = _g6b2_make_live_request(
        row_root=slot_root / "producer",
        artifact_root=artifact_root,
        family_id=family,
        task_family=task_family,
        task_id=f"g6b2-{slug}-producer",
        session_id=f"g6b2-producer-session:{slug}",
        run_id=f"g6b2-producer-run:{slug}",
        value=producer_value,
        memory_root=memory_root,
        memory_policy="validated_replay",
        invocation_id=f"{slug}-producer",
        commit_replay_class=ReplayClass.VALIDATED_REPLAY,
        timeout_s=timeout_s,
    )
    producer_started = time.perf_counter()
    producer_result = RuntimeDriver().run_mode(
        "adaptive_bounded", adaptive_request=producer_request
    )
    producer = _g6b2_runtime_row(
        result=producer_result,
        request=producer_request,
        slot=slot,
        lane="live-producer",
        cache_epoch=f"producer:{slug}",
        row_id=f"producer:{slug}",
        provider=producer_provider,
        input_value=producer_value,
    )
    producer["runtime_elapsed_ms"] = round(
        (time.perf_counter() - producer_started) * 1000.0, 3
    )
    _runtime_evidence(artifact_root, slug, "producer", producer_result)
    if (
        producer["terminal_status"] != "success"
        or not producer_result.memory_commit_decision.committed
    ):
        raise RuntimeError(
            json.dumps({"stage": "producer", "row": producer}, default=str)
        )

    replay_request, replay_provider = _g6b2_make_live_request(
        row_root=slot_root / "replay",
        artifact_root=artifact_root,
        family_id=family,
        task_family=task_family,
        task_id=f"g6b2-{slug}-replay",
        session_id=f"g6b2-replay-session:{slug}",
        run_id=f"g6b2-replay-run:{slug}",
        value=current_value,
        memory_root=memory_root,
        memory_policy="validated_replay",
        invocation_id=f"{slug}-replay-unexpected",
        commit_replay_class=ReplayClass.VALIDATED_REPLAY,
        timeout_s=timeout_s,
    )
    replay_started = time.perf_counter()
    replay_result = RuntimeDriver().run_mode(
        "adaptive_bounded", adaptive_request=replay_request
    )
    replay = _g6b2_runtime_row(
        result=replay_result,
        request=replay_request,
        slot=slot,
        lane="live-validated-replay",
        cache_epoch=f"replay:{slug}",
        row_id=f"replay:{slug}",
        provider=replay_provider,
        input_value=current_value,
    )
    replay["runtime_elapsed_ms"] = round(
        (time.perf_counter() - replay_started) * 1000.0, 3
    )
    _runtime_evidence(artifact_root, slug, "replay", replay_result)
    if replay_provider.boundary_rows:
        replay.update(
            {
                "terminal_status": "runtime_fail",
                "failure_stage": "replay",
                "reason": "replay_provider_was_started",
            }
        )
    return baseline, producer, replay


def run_g6b2_live_campaign(
    *,
    artifact_root: Path | str,
    mode: str,
    pairs: int,
    max_duration_s: int,
    min_slot_interval_s: int = 0,
) -> dict[str, object]:
    root = Path(artifact_root)
    preflight = _json_read(root / "gpu_preflight.json")
    health = _json_read(root / "vllm_health.json")
    identity = _json_read(root / "vllm_model_identity.json")
    stages = _json_read(root / "live_stage_rows.partial.json")["rows"]
    container_profile = (
        _json_read(root / "container_runtime_profile.json")
        if (root / "container_runtime_profile.json").is_file()
        else {"status": "environment_fail", "reason": "container_profile_missing"}
    )
    container_ok = container_profile.get("status") == "observed"
    stages.append(
        _stage_row(
            "stage:container",
            "Docker-Verify",
            "success" if container_ok else "environment_fail",
            str(container_profile.get("reason", "")),
            refs=("docker_smoke.json",),
        )
    )
    _json_write(
        root / "docker_smoke.json",
        {
            "schema_version": "statebus.g6b2.docker_verify.v1",
            "profile_id": PROFILE_ID,
            "status": "observed" if container_ok else "environment_fail",
            "checkout": str(Path.cwd()),
            "statebus_module": __file__,
            "uid": os.getuid(),
            "gid": os.getgid(),
            "container": os.getenv(
                "STATEBUS_CONTAINER_NAME",
                os.getenv("STATEBUS_B2_CONTAINER_NAME", "statebus-runtime"),
            ),
            "network": "host",
            "host_profile_receipt": "container_runtime_profile.json",
            "source_receipt_references": ["container_runtime_profile.json"],
        },
    )
    smoke = (
        {"status": "passed", "smoke": _json_read(root / "live_smoke.json")}
        if container_ok and (root / "live_smoke.json").is_file()
        else run_g6b2_live_smoke(preflight, artifact_root=root)
        if container_ok
        else {
            "status": "failed",
            "smoke": {"reason": "container_runtime_profile_failed"},
        }
    )
    stages.append(
        _stage_row(
            "stage:smoke",
            "B2-Live-Smoke",
            "success" if smoke["status"] == "passed" else "runtime_fail",
            str(smoke.get("smoke", {}).get("reason", "")),
            ("live_smoke.json",),
        )
    )
    slots = _g6b2_campaign_slots(mode, pairs)
    baseline_rows: list[dict[str, object]] = []
    producer_rows: list[dict[str, object]] = []
    replay_rows: list[dict[str, object]] = []
    start = time.monotonic()
    interrupted = False
    failure_reason = ""
    slot_started = start
    if smoke["status"] == "passed":
        for index, slot in enumerate(slots):
            try:
                elapsed = time.monotonic() - start
                if elapsed >= max_duration_s:
                    failure_reason = "max_duration_exhausted"
                    break
                if mode == "soak" and index and min_slot_interval_s:
                    remaining = min_slot_interval_s - (
                        time.monotonic() - slot_started
                    )
                    if remaining > 0:
                        time.sleep(
                            min(
                                remaining,
                                max(
                                    0.0,
                                    max_duration_s
                                    - (time.monotonic() - start),
                                ),
                            )
                        )
                slot_started = time.monotonic()
                baseline, producer, replay = _execute_slot(
                    root,
                    Path("/statebus/work/b2") / root.name[-40:],
                    slot,
                    timeout_s=min(
                        120.0,
                        max(
                            1.0,
                            max_duration_s - (time.monotonic() - start),
                        ),
                    ),
                )
                baseline_rows.append(baseline)
                producer_rows.append(producer)
                replay_rows.append(replay)
                slot["execution_status"] = (
                    "completed"
                    if replay["terminal_status"] == "success"
                    else "failed"
                )
                if replay["terminal_status"] != "success":
                    failure_reason = str(replay["reason"])
                    break
            except KeyboardInterrupt:
                interrupted = True
                failure_reason = "interrupted"
                break
            except Exception as exc:  # first failure stops new live requests
                failure_reason = str(exc)
                slot["execution_status"] = "failed"
                break
    for slot in slots:
        if slot["execution_status"] == "planned":
            slot["execution_status"] = "not_run"
    stages.append(
        _stage_row(
            "stage:pair",
            "B2-Minimal-Matched-Pair",
            "success"
            if len(replay_rows) == len(slots) and not failure_reason
            else "runtime_fail",
            failure_reason,
            ("runtime_evidence",),
        )
    )
    projection = _g6b2_live_pair_projection(
        baseline_rows, replay_rows, mode=mode, planned_slots=slots
    )
    denominator = _g6b2_live_failure_denominator(
        baseline_rows,
        replay_rows,
        projection,
        producer_rows=producer_rows,
        stage_rows=stages,
    )
    complete = bool(
        len(replay_rows) == len(slots)
        and projection.get("status") == "accepted"
        and denominator.get("arithmetic_closed") is True
        and denominator.get("row_arithmetic_closed") is True
    )
    status = (
        "MINIMAL_PAIR_VERIFIED_FOR_USER_CAMPAIGN"
        if complete and mode == "minimal"
        else "CAMPAIGN_VERIFIED"
        if complete and mode == "campaign"
        else "SOAK_VERIFIED"
        if complete
        else "INCOMPLETE"
        if interrupted or failure_reason == "max_duration_exhausted"
        else "FAILED"
    )
    _g6b2_write_artifacts(
        root,
        gpu_preflight=preflight,
        vllm_health=health,
        vllm_model_identity=identity,
        baseline_rows=baseline_rows,
        replay_rows=replay_rows,
        producer_rows=producer_rows,
        stage_rows=stages,
        pair_projection=projection,
        failure_denominator=denominator,
        status=status,
        create_root=False,
        mode=mode,
        planned_slots=slots,
        max_duration_s=max_duration_s,
    )
    final_status = str(_json_read(root / "g6b2_acceptance.json")["status"])
    if final_status != status:
        status = final_status
    return {
        "status": status,
        "artifact_root": str(root),
        "eligible_live_pair_count": denominator[
            "eligible_matched_pair_count"
        ],
        "interrupted": interrupted,
    }


def run_g6b2_minimal_matched_pair(
    *,
    artifact_root: Path | str,
    baseline_row: Mapping[str, object] | None = None,
    replay_row: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if baseline_row is not None or replay_row is not None:
        projection = _g6b2_live_pair_projection(
            [] if baseline_row is None else [baseline_row],
            [] if replay_row is None else [replay_row],
        )
        return {
            "status": "passed"
            if projection.get("status") == "accepted"
            else "failed",
            "projection": projection,
            "artifact_root": str(artifact_root),
        }
    return run_g6b2_live_campaign(
        artifact_root=artifact_root,
        mode="minimal",
        pairs=1,
        max_duration_s=600,
    )


def _g6b2_verify_artifacts(
    artifact_root: Path | str,
    *,
    require_mode: str | None = None,
) -> dict[str, object]:
    root = Path(artifact_root).resolve()
    required = [
        "service_identity.json",
        "gpu_preflight.json",
        "vllm_health.json",
        "vllm_model_identity.json",
        "container_runtime_profile.json",
        "docker_smoke.json",
        "live_manifest.json",
        "live_slots.json",
        "live_stage_rows.json",
        "live_producer_rows.json",
        "live_baseline_rows.json",
        "live_replay_rows.json",
        "live_pair_projection.json",
        "live_negative_row_index.json",
        "live_failure_denominator.json",
        "live_metric_availability.json",
        "g6b2_acceptance.json",
        "final_gate_status.json",
    ]
    if EMBEDDING_MODE == "local":
        required.append("embedding_probe.json")
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        return {
            "status": "failed",
            "reason": "missing_artifacts",
            "missing": missing,
            "artifact_root": str(root),
        }
    manifest = _json_read(root / "live_manifest.json")
    slots = _json_read(root / "live_slots.json")["slots"]
    stages = _json_read(root / "live_stage_rows.json")["rows"]
    producer = _json_read(root / "live_producer_rows.json")["rows"]
    baseline = _json_read(root / "live_baseline_rows.json")["rows"]
    replay = _json_read(root / "live_replay_rows.json")["rows"]
    mode = str(manifest.get("campaign_mode", ""))
    projection = _g6b2_live_pair_projection(
        baseline, replay, mode=mode, planned_slots=slots
    )
    denominator = _g6b2_live_failure_denominator(
        baseline,
        replay,
        projection,
        producer_rows=producer,
        stage_rows=stages,
    )
    stored_denominator = _json_read(root / "live_failure_denominator.json")
    request_refs = [
        ref
        for row in [*baseline, *producer]
        for ref in row.get("source_receipt_references", ())
        if str(ref).startswith("requests/")
    ]
    runtime_refs_ok = all(
        (
            root
            / "runtime_evidence"
            / str(row["slot_id"])
            / lane
            / "runtime.json"
        ).is_file()
        for lane, rows in (
            ("baseline", baseline),
            ("producer", producer),
            ("replay", replay),
        )
        for row in rows
    )
    embedding_probe = (
        _json_read(root / "embedding_probe.json")
        if (root / "embedding_probe.json").is_file()
        else {}
    )
    probe_embedding = embedding_probe.get("embedding", {})
    if not isinstance(probe_embedding, Mapping):
        probe_embedding = {}
    probe_device = embedding_probe.get("device_evidence", {})
    if not isinstance(probe_device, Mapping):
        probe_device = {}
    checks = {
        "profile": manifest.get("profile_id") == PROFILE_ID,
        "mode": require_mode is None or mode == require_mode,
        "preflight": _json_read(root / "gpu_preflight.json").get("status")
        == "observed",
        "health": _json_read(root / "vllm_health.json").get("status")
        == "observed",
        "model": _json_read(root / "vllm_model_identity.json").get(
            "identity_status"
        )
        == "matched",
        "container_profile": _json_read(
            root / "container_runtime_profile.json"
        ).get("status")
        == "observed",
        "stage_order": [row.get("stage") for row in stages]
        == list(ALLOWED_SEQUENCE),
        "pair_projection": projection.get("status") == "accepted",
        "denominator": denominator == stored_denominator,
        "request_response_refs": bool(request_refs)
        and all((root / str(ref)).is_file() for ref in request_refs),
        "runtime_refs": runtime_refs_ok,
        "embedding_evidence": _embedding_rows_valid(
            baseline, producer, replay
        )
        and (
            EMBEDDING_MODE != "local"
            or (
                embedding_probe.get("status") == "observed"
                and probe_embedding.get("encoding")
                == f"sentence-transformers:{Path(EMBEDDING_MODEL_PATH).name}"
                and int(probe_embedding.get("dims", 0)) > 16
                and probe_device.get("physical_gpu") == EMBEDDING_PHYSICAL_GPU
                and probe_device.get("container_device") == "cuda:0"
                and probe_device.get("parameter_devices") == ["cuda:0"]
                and probe_device.get("parameter_device_ok") is True
            )
        ),
        "all_slots_complete": all(
            slot.get("execution_status") == "completed" for slot in slots
        ),
        "service_stop_called": _json_read(root / "service_identity.json").get(
            "service_stop_called"
        )
        is False,
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "artifact_root": str(root),
        "profile_id": PROFILE_ID,
        "mode": mode,
        "eligible_live_pair_count": denominator[
            "eligible_matched_pair_count"
        ],
        "checks": checks,
        "benchmark_superiority": "NOT_ESTABLISHED",
    }


def _coexist(value: str) -> list[int]:
    return [int(item) for item in value.split(",") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m statebus.benchmark.g6b2_live_validation"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    host = subparsers.add_parser("host-preflight")
    host.add_argument(
        "--mode", choices=("minimal", "campaign", "soak"), required=True
    )
    host.add_argument("--output-base", default="artifacts")
    host.add_argument(
        "--service-runtime-dir",
        default="/home/qcrs/statebus/work/vllm-qwen3-32b-gpu2-u050",
    )
    host.add_argument("--coexist-pids", default="")
    host.add_argument("--pairs", type=int, required=True)
    host.add_argument("--max-duration-s", type=int, required=True)

    execute = subparsers.add_parser("execute")
    execute.add_argument(
        "--mode", choices=("minimal", "campaign", "soak"), required=True
    )
    execute.add_argument("--artifact-root", required=True)
    execute.add_argument("--pairs", type=int, required=True)
    execute.add_argument("--max-duration-s", type=int, required=True)
    execute.add_argument("--min-slot-interval-s", type=int, default=0)

    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--artifact-root", required=True)
    smoke.add_argument("--timeout-s", type=float, default=120.0)

    embedding_probe = subparsers.add_parser("embedding-probe")
    embedding_probe.add_argument("--artifact-root", required=True)

    container_profile = subparsers.add_parser("container-profile")
    container_profile.add_argument("--artifact-root", required=True)
    container_profile.add_argument("--container-name", default="statebus-runtime")

    nontext = subparsers.add_parser("nontext")
    nontext.add_argument("--output-base", default="artifacts")
    nontext.add_argument(
        "--scope", choices=("targeted", "full"), default="targeted"
    )

    verify = subparsers.add_parser("verify")
    verify.add_argument("--artifact-root", required=True)
    verify.add_argument(
        "--require-mode", choices=("minimal", "campaign", "soak")
    )
    args = parser.parse_args(argv)
    if args.command == "host-preflight":
        result = run_g6b2_preflight(
            output_base=args.output_base,
            service_runtime_dir=args.service_runtime_dir,
            coexist_pids=_coexist(args.coexist_pids),
            mode=args.mode,
            planned_slots=args.pairs,
            max_duration_s=args.max_duration_s,
        )
        print(result["artifact_root"])
        return 0 if result["status"] == "passed" else 1
    if args.command == "execute":
        result = run_g6b2_live_campaign(
            artifact_root=args.artifact_root,
            mode=args.mode,
            pairs=args.pairs,
            max_duration_s=args.max_duration_s,
            min_slot_interval_s=args.min_slot_interval_s,
        )
        print(json.dumps(result, sort_keys=True))
        if result["status"] in {
            "MINIMAL_PAIR_VERIFIED_FOR_USER_CAMPAIGN",
            "CAMPAIGN_VERIFIED",
            "SOAK_VERIFIED",
        }:
            return 0
        if result.get("interrupted"):
            return 130
        return 3 if result["status"] == "INCOMPLETE" else 1
    if args.command == "smoke":
        root = Path(args.artifact_root)
        result = run_g6b2_live_smoke(
            _json_read(root / "gpu_preflight.json"),
            artifact_root=root,
            timeout_s=args.timeout_s,
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "passed" else 1
    if args.command == "embedding-probe":
        result = run_g6b2_embedding_probe(artifact_root=args.artifact_root)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "observed" else 1
    if args.command == "container-profile":
        result = run_g6b2_container_profile(
            artifact_root=args.artifact_root,
            container_name=args.container_name,
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "observed" else 1
    if args.command == "nontext":
        result = run_g6b2_nontext_validation(
            output_base=args.output_base,
            full=args.scope == "full",
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "passed" else 1
    result = _g6b2_verify_artifacts(
        args.artifact_root, require_mode=args.require_mode
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
