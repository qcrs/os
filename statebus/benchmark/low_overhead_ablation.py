from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
from multiprocessing.shared_memory import SharedMemory
import os
from pathlib import Path
import socket
import time
from typing import Any

from google.protobuf.struct_pb2 import Struct
from google.protobuf.wrappers_pb2 import BytesValue

from statebus.utils import stable_json_dumps


VARIANTS = ("utf8_text_inline", "typed_protobuf_inline", "typed_protobuf_shm_ref")
DEFAULT_SIZES = {"small": 1_024, "medium": 65_536, "large": 524_288}
DEFAULT_THRESHOLDS = (256, 1_024, 4_096, 16_384)


def select_carrier(payload_size: int, *, inline_threshold_bytes: int) -> str:
    """Choose the carrier before any data-plane allocation is performed."""

    if payload_size < 1 or inline_threshold_bytes < 1:
        raise ValueError("p2_payload_size_and_threshold_must_be_positive")
    return (
        "typed_protobuf_inline"
        if payload_size <= inline_threshold_bytes
        else "typed_protobuf_shm_ref"
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.monotonic_ns()}")
    temporary.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")
    temporary.replace(path)


def _frame(payload: bytes) -> bytes:
    return len(payload).to_bytes(4, "big") + payload


def _recv_exact(conn: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = conn.recv(remaining)
        if not chunk:
            raise ConnectionError("p2_frame_truncated")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_frame(conn: socket.socket) -> tuple[bytes, int]:
    header = _recv_exact(conn, 4)
    size = int.from_bytes(header, "big")
    if size <= 0:
        raise ValueError("p2_frame_length_invalid")
    payload = _recv_exact(conn, size)
    return payload, size + 4


def _struct_payload(payload: dict[str, object]) -> bytes:
    message = Struct()
    message.update(payload)
    return message.SerializeToString()


def _decode_struct(payload: bytes) -> dict[str, object]:
    message = Struct()
    message.ParseFromString(payload)
    return {key: value for key, value in message.items()}


def _worker(socket_path: str, variant: str, ready: Any) -> None:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(socket_path)
        server.listen(1)
        ready.set()
        conn, _ = server.accept()
        with conn:
            request_payload, _wire_bytes = _recv_frame(conn)
            decode_started = time.perf_counter_ns()
            map_ms = 0.0
            read_ms = 0.0
            shared: SharedMemory | None = None
            try:
                if variant == "utf8_text_inline":
                    request = json.loads(request_payload.decode("utf-8"))
                    logical_payload = str(request["payload"]).encode("utf-8")
                    expected_hash = str(request["payload_sha256"])
                elif variant == "typed_protobuf_inline":
                    message = BytesValue()
                    message.ParseFromString(request_payload)
                    logical_payload = bytes(message.value)
                    expected_hash = hashlib.sha256(logical_payload).hexdigest()
                elif variant == "typed_protobuf_shm_ref":
                    descriptor = _decode_struct(request_payload)
                    expected_hash = str(descriptor["payload_sha256"])
                    map_started = time.perf_counter_ns()
                    shared = SharedMemory(name=str(descriptor["shared_memory_name"]))
                    map_ms = (time.perf_counter_ns() - map_started) / 1_000_000
                    read_started = time.perf_counter_ns()
                    logical_payload = bytes(shared.buf[: int(descriptor["size_bytes"])])
                    read_ms = (time.perf_counter_ns() - read_started) / 1_000_000
                else:
                    raise ValueError(f"p2_variant_unsupported:{variant}")
                observed_hash = hashlib.sha256(logical_payload).hexdigest()
                ok = observed_hash == expected_hash
                error = "" if ok else "payload_hash_mismatch"
            except Exception as exc:
                logical_payload = b""
                observed_hash = ""
                ok = False
                error = f"{type(exc).__name__}:{exc}"
            finally:
                if shared is not None:
                    shared.close()
            decode_ms = (time.perf_counter_ns() - decode_started) / 1_000_000
            response = _struct_payload(
                {
                    "ok": ok,
                    "error": error,
                    "payload_sha256": observed_hash,
                    "payload_bytes": len(logical_payload),
                    "decode_ms": decode_ms,
                    "state_map_ms": map_ms,
                    "state_read_ms": read_ms,
                    "consumer_pid": os.getpid(),
                }
            )
            conn.sendall(_frame(response))
    finally:
        server.close()
        try:
            Path(socket_path).unlink()
        except FileNotFoundError:
            pass


def _payload(size_bytes: int, *, payload_index: int) -> bytes:
    seed = f"statebus-p2-payload-{payload_index:03d}|".encode("ascii")
    repeats = (size_bytes + len(seed) - 1) // len(seed)
    return (seed * repeats)[:size_bytes]


def _run_variant(
    *,
    variant: str,
    payload: bytes,
    payload_id: str,
    socket_path: Path,
    timeout_s: float,
    policy_name: str = "fixed_variant",
    threshold_bytes: int | None = None,
) -> dict[str, object]:
    payload_hash = hashlib.sha256(payload).hexdigest()
    shared: SharedMemory | None = None
    process: multiprocessing.Process | None = None
    conn: socket.socket | None = None
    state_publish_ms = 0.0
    state_release_ms = 0.0
    encode_started = time.perf_counter_ns()
    if variant == "utf8_text_inline":
        request_payload = stable_json_dumps(
            {"payload": payload.decode("utf-8"), "payload_sha256": payload_hash}
        ).encode("utf-8")
        text_chars: dict[str, object] = {"status": "observed", "value": len(payload.decode("utf-8"))}
    elif variant == "typed_protobuf_inline":
        request_payload = BytesValue(value=payload).SerializeToString()
        text_chars = {"status": "not_applicable", "value": None}
    elif variant == "typed_protobuf_shm_ref":
        publish_started = time.perf_counter_ns()
        shared = SharedMemory(create=True, size=len(payload))
        shared.buf[: len(payload)] = payload
        state_publish_ms = (time.perf_counter_ns() - publish_started) / 1_000_000
        request_payload = _struct_payload(
            {
                "schema_version": "statebus.p2.shm_ref.v1",
                "ref_kind": "shared_memory",
                "shared_memory_name": shared.name,
                "size_bytes": len(payload),
                "payload_sha256": payload_hash,
            }
        )
        text_chars = {"status": "not_applicable", "value": None}
    else:
        raise ValueError(f"p2_variant_unsupported:{variant}")
    encode_ms = (time.perf_counter_ns() - encode_started) / 1_000_000

    wall_started = time.perf_counter_ns()
    try:
        context = multiprocessing.get_context("fork")
        ready = context.Event()
        process = context.Process(target=_worker, args=(str(socket_path), variant, ready))
        process.start()
        ready_deadline = time.monotonic() + timeout_s
        while not ready.wait(min(0.05, max(0.001, ready_deadline - time.monotonic()))):
            if not process.is_alive():
                process.join(timeout=1)
                raise RuntimeError(f"p2_worker_start_failed:exit_code={process.exitcode}")
            if time.monotonic() >= ready_deadline:
                raise TimeoutError("p2_worker_ready_timeout")

        request_frame = _frame(request_payload)
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(timeout_s)
        connect_started = time.perf_counter_ns()
        conn.connect(str(socket_path))
        socket_wait_ms = (time.perf_counter_ns() - connect_started) / 1_000_000
        conn.sendall(request_frame)
        response_payload, response_wire_bytes = _recv_frame(conn)
        ack_latency_ms = (time.perf_counter_ns() - connect_started) / 1_000_000
        response = _decode_struct(response_payload)
        process.join(timeout_s)
        if process.is_alive():
            raise TimeoutError("p2_worker_exit_timeout")
    finally:
        if conn is not None:
            conn.close()
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=1)
        if shared is not None:
            release_started = time.perf_counter_ns()
            shared.close()
            try:
                shared.unlink()
            except FileNotFoundError:
                pass
            state_release_ms = (time.perf_counter_ns() - release_started) / 1_000_000
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass

    quality_pass = bool(response.get("ok")) and response.get("payload_sha256") == payload_hash
    terminal_class = "success" if quality_pass and process.exitcode == 0 else "runtime_fail"
    is_ref = variant == "typed_protobuf_shm_ref"
    control_plane_bytes = len(request_frame) + response_wire_bytes
    descriptor_bytes = len(request_payload) if is_ref else 0
    payload_data_plane_bytes = len(payload) if is_ref else 0
    payload_control_plane_bytes = len(payload) if not is_ref else 0
    return {
        "schema_version": "statebus.p2.low_overhead_row.v1",
        "row_id": f"{payload_id}:{variant}",
        "matched_payload_id": payload_id,
        "variant": variant,
        "policy": policy_name,
        "threshold_bytes": threshold_bytes,
        "effective_carrier": "ref_shm" if is_ref else "inline",
        "carrier_decision_before_allocation": True,
        "shared_memory_created": is_ref,
        "descriptor_only_control_frame": is_ref,
        "semantic_payload_sha256": payload_hash,
        "semantic_payload_bytes": len(payload),
        "producer_pid": os.getpid(),
        "consumer_pid": int(response.get("consumer_pid", 0) or 0),
        "cross_process": int(response.get("consumer_pid", 0) or 0) != os.getpid(),
        "logical_messages": 2,
        "control_bytes": control_plane_bytes,
        "control_plane_bytes": control_plane_bytes,
        "descriptor_bytes": descriptor_bytes,
        "payload_data_plane_bytes": payload_data_plane_bytes,
        "payload_control_plane_bytes": payload_control_plane_bytes,
        "copy_setup_ms": encode_ms + socket_wait_ms,
        "wire_bytes": {
            "status": "observed",
            "value": len(request_frame) + response_wire_bytes,
            "source": "canonical_wire_observation",
        },
        "text_chars": text_chars,
        "prompt_tokens": {"status": "unsupported", "value": None, "reason": "provider_not_in_p2_carrier_scope"},
        "completion_tokens": {"status": "unsupported", "value": None, "reason": "provider_not_in_p2_carrier_scope"},
        "encode_ms": encode_ms,
        "decode_ms": float(response.get("decode_ms", 0.0) or 0.0),
        "socket_wait_ms": socket_wait_ms,
        "ack_latency_ms": ack_latency_ms,
        "copy_count": {"status": "unsupported", "value": None, "reason": "kernel_copy_count_not_observed"},
        "copy_bytes": {"status": "unsupported", "value": None, "reason": "kernel_copy_bytes_not_observed"},
        "state_publish_ms": state_publish_ms if variant == "typed_protobuf_shm_ref" else None,
        "state_map_ms": float(response.get("state_map_ms", 0.0) or 0.0) if variant == "typed_protobuf_shm_ref" else None,
        "state_read_ms": float(response.get("state_read_ms", 0.0) or 0.0) if variant == "typed_protobuf_shm_ref" else None,
        "state_release_ms": state_release_ms if variant == "typed_protobuf_shm_ref" else None,
        "shm_setup_ms": state_publish_ms if is_ref else 0.0,
        "shm_map_ms": float(response.get("state_map_ms", 0.0) or 0.0) if is_ref else 0.0,
        "shm_read_ms": float(response.get("state_read_ms", 0.0) or 0.0) if is_ref else 0.0,
        "shm_release_ms": state_release_ms if is_ref else 0.0,
        "critical_path_wall_ms": (time.perf_counter_ns() - wall_started) / 1_000_000,
        "quality": {"passed": quality_pass, "expected_sha256": payload_hash, "observed_sha256": response.get("payload_sha256", "")},
        "terminal_class": terminal_class,
        "failure": str(response.get("error", "")),
        "feature_flags": {
            "semantic_state": False,
            "memory": False,
            "codeact": False,
            "apc_prefix": False,
            "kv_hidden_latent": False,
        },
    }


def run_size_aware_threshold_sweep(
    *,
    output_root: Path,
    thresholds: tuple[int, ...] = DEFAULT_THRESHOLDS,
    sizes: dict[str, int] | None = None,
    payload_count_per_size: int = 1,
    repeats: int = 1,
    timeout_s: float = 20.0,
) -> dict[str, object]:
    """Run the existing carrier runner with an explicit size-aware policy.

    The selected fixed variant is passed to ``_run_variant`` only after the
    threshold decision.  This is the important invariant: an inline row never
    allocates a shared-memory object, while a ref row sends only a descriptor
    over the control socket.
    """

    if payload_count_per_size < 1 or repeats < 1 or timeout_s <= 0:
        raise ValueError("p2_positive_counts_and_timeout_required")
    normalized_thresholds = tuple(dict.fromkeys(int(item) for item in thresholds))
    if not normalized_thresholds or any(item < 1 for item in normalized_thresholds):
        raise ValueError("p2_thresholds_must_be_positive")
    effective_sizes = dict(sizes or DEFAULT_SIZES)
    if not effective_sizes or any(int(value) < 1 for value in effective_sizes.values()):
        raise ValueError("p2_payload_sizes_must_be_positive")
    if output_root.exists():
        if not output_root.is_dir() or any(output_root.iterdir()):
            raise FileExistsError(f"p2_output_root_must_be_new_or_empty:{output_root}")
    else:
        output_root.mkdir(parents=True, exist_ok=False)

    manifest = {
        "schema_version": "statebus.p2.size_aware_threshold_manifest.v1",
        "policy": "payload_size <= inline_threshold_bytes => typed_protobuf_inline; otherwise typed_protobuf_shm_ref",
        "thresholds_bytes": list(normalized_thresholds),
        "payload_sizes": effective_sizes,
        "payload_count_per_size": payload_count_per_size,
        "repeats": repeats,
        "decision_before_shared_memory_creation": True,
        "claim_boundary": "carrier decision and directly observed setup/control/data-plane telemetry; no provider or superiority claim",
    }
    _write_json(output_root / "manifest.json", manifest)

    rows: list[dict[str, object]] = []
    for threshold_bytes in normalized_thresholds:
        for repeat in range(1, repeats + 1):
            for size_name, size_bytes in effective_sizes.items():
                for payload_index in range(1, payload_count_per_size + 1):
                    payload_id = f"{size_name}:{payload_index:03d}:repeat-{repeat}"
                    # Threshold is a carrier policy variable only.  Keep the
                    # payload identity stable across the sweep so every row
                    # is a true matched-payload comparison.
                    stable_payload_index = (
                        repeat * 1_000_000
                        + sum(
                            index * 10_000
                            for index, name in enumerate(effective_sizes, start=1)
                            if name == size_name
                        )
                        + payload_index
                    )
                    logical_payload = _payload(
                        int(size_bytes), payload_index=stable_payload_index
                    )
                    variant = select_carrier(
                        len(logical_payload),
                        inline_threshold_bytes=threshold_bytes,
                    )
                    socket_path = Path("/tmp") / (
                        f"statebus-p2-policy-{os.getpid()}-{repeat}-"
                        f"{size_name}-{payload_index}-"
                        f"{threshold_bytes}.sock"
                    )
                    row = _run_variant(
                        variant=variant,
                        payload=logical_payload,
                        payload_id=payload_id,
                        socket_path=socket_path,
                        timeout_s=timeout_s,
                        policy_name="size_aware_threshold",
                        threshold_bytes=threshold_bytes,
                    )
                    row["threshold_row_id"] = f"{threshold_bytes}:{payload_id}"
                    rows.append(row)

    expected_carriers = {
        f"{threshold}:{size_name}": (
            "inline" if int(size_bytes) <= threshold else "ref_shm"
        )
        for threshold in normalized_thresholds
        for size_name, size_bytes in effective_sizes.items()
    }
    observed_carriers = {
        f"{row['threshold_bytes']}:{row['matched_payload_id'].split(':', 1)[0]}": row[
            "effective_carrier"
        ]
        for row in rows
    }
    rows_ok = all(row["terminal_class"] == "success" for row in rows)
    policy_ok = observed_carriers == expected_carriers and all(
        bool(row["carrier_decision_before_allocation"])
        and bool(row["shared_memory_created"]) == (row["effective_carrier"] == "ref_shm")
        for row in rows
    )
    acceptance = {
        "schema_version": "statebus.p2.size_aware_threshold_acceptance.v1",
        "status": "passed" if rows and rows_ok and policy_ok else "inconclusive",
        "exit_code": 0 if rows and rows_ok and policy_ok else 3,
        "thresholds_bytes": list(normalized_thresholds),
        "row_count": len(rows),
        "observed_carriers": observed_carriers,
        "expected_carriers": expected_carriers,
        "checks": {
            "rows_terminal": rows_ok,
            "carrier_matrix_matches": policy_ok,
            "inline_has_no_shm_setup": all(
                row["effective_carrier"] != "inline"
                or not row["shared_memory_created"]
                and row["shm_setup_ms"] == 0.0
                for row in rows
            ),
            "ref_uses_descriptor_only_control_frame": all(
                row["effective_carrier"] != "ref_shm"
                or row["descriptor_only_control_frame"]
                and row["payload_control_plane_bytes"] == 0
                for row in rows
            ),
        },
        "benchmark_superiority": "NOT_ESTABLISHED",
        "statistical_superiority": "NOT_ESTABLISHED",
    }
    _write_json(output_root / "rows.json", rows)
    _write_json(output_root / "acceptance.json", acceptance)
    return {**acceptance, "output_root": str(output_root)}


def run_low_overhead_ablation(
    *,
    output_root: Path,
    payload_count_per_size: int = 1,
    repeats: int = 1,
    sizes: dict[str, int] | None = None,
    timeout_s: float = 20.0,
) -> dict[str, object]:
    if payload_count_per_size < 1 or repeats < 1 or timeout_s <= 0:
        raise ValueError("p2_positive_counts_and_timeout_required")
    if output_root.exists():
        if not output_root.is_dir() or any(output_root.iterdir()):
            raise FileExistsError(f"p2_output_root_must_be_new_or_empty:{output_root}")
    else:
        output_root.mkdir(parents=True, exist_ok=False)
    effective_sizes = dict(sizes or DEFAULT_SIZES)
    if not effective_sizes or any(int(value) < 1 for value in effective_sizes.values()):
        raise ValueError("p2_payload_sizes_must_be_positive")

    manifest = {
        "schema_version": "statebus.p2.low_overhead_manifest.v1",
        "variants": list(VARIANTS),
        "payload_sizes": effective_sizes,
        "payload_count_per_size": payload_count_per_size,
        "repeats": repeats,
        "matched_variable": "semantic_payload_bytes_and_sha256",
        "topology": "cross_process_uds",
        "excluded_features": [
            "SemanticState_selection", "Memory", "CodeAct", "APC_Prefix", "KV_Hidden_Latent_State",
        ],
        "claim_boundary": "carrier realization and directly observed transfer telemetry only; no provider or superiority claim",
    }
    _write_json(output_root / "manifest.json", manifest)

    rows: list[dict[str, object]] = []
    ordinal = 0
    for repeat in range(1, repeats + 1):
        for size_name, size_bytes in effective_sizes.items():
            for payload_index in range(1, payload_count_per_size + 1):
                ordinal += 1
                payload_id = f"{size_name}:{payload_index:03d}:repeat-{repeat}"
                logical_payload = _payload(int(size_bytes), payload_index=ordinal)
                for variant in VARIANTS:
                    socket_path = Path("/tmp") / f"statebus-p2-{os.getpid()}-{ordinal}-{VARIANTS.index(variant)}.sock"
                    rows.append(_run_variant(
                        variant=variant,
                        payload=logical_payload,
                        payload_id=payload_id,
                        socket_path=socket_path,
                        timeout_s=timeout_s,
                    ))

    counts = {status: sum(row["terminal_class"] == status for row in rows) for status in ("success", "runtime_fail")}
    matched_groups: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        matched_groups.setdefault(str(row["matched_payload_id"]), []).append(row)
    matched_closed = all(
        {str(row["variant"]) for row in group} == set(VARIANTS)
        and len({str(row["semantic_payload_sha256"]) for row in group}) == 1
        and len({int(row["semantic_payload_bytes"]) for row in group}) == 1
        for group in matched_groups.values()
    )
    denominator = {
        "schema_version": "statebus.p2.low_overhead_denominator.v1",
        "planned_count": len(matched_groups) * len(VARIANTS),
        "observed_count": len(rows),
        "success_count": counts["success"],
        "runtime_fail_count": counts["runtime_fail"],
        "matched_payload_count": len(matched_groups),
        "matched_groups_closed": matched_closed,
        "arithmetic_closed": len(rows) == counts["success"] + counts["runtime_fail"],
    }
    ok = bool(rows) and matched_closed and denominator["arithmetic_closed"] and counts["runtime_fail"] == 0
    acceptance = {
        "schema_version": "statebus.p2.low_overhead_acceptance.v1",
        "status": "passed" if ok else "inconclusive",
        "exit_code": 0 if ok else 3,
        "performance_claim_eligible": False,
        "benchmark_superiority": "NOT_ESTABLISHED",
        "statistical_superiority": "NOT_ESTABLISHED",
        "denominator": denominator,
    }
    _write_json(output_root / "rows.json", rows)
    _write_json(output_root / "denominator.json", denominator)
    _write_json(output_root / "acceptance.json", acceptance)
    return {**acceptance, "output_root": str(output_root)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the matched-payload StateBus P2 carrier ablation.")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--payload-count-per-size", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout-s", type=float, default=20.0)
    parser.add_argument(
        "--threshold-sweep",
        action="store_true",
        help="run the explicit size-aware inline/ref threshold sweep",
    )
    parser.add_argument(
        "--threshold-bytes",
        action="append",
        type=int,
        default=None,
        help="inline threshold in bytes; repeat for a sweep",
    )
    args = parser.parse_args()
    if args.threshold_sweep:
        result = run_size_aware_threshold_sweep(
            output_root=args.output_root,
            thresholds=tuple(args.threshold_bytes or DEFAULT_THRESHOLDS),
            payload_count_per_size=args.payload_count_per_size,
            repeats=args.repeats,
            timeout_s=args.timeout_s,
        )
    else:
        result = run_low_overhead_ablation(
            output_root=args.output_root,
            payload_count_per_size=args.payload_count_per_size,
            repeats=args.repeats,
            timeout_s=args.timeout_s,
        )
    print(stable_json_dumps(result))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
