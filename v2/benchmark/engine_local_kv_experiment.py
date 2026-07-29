from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from typing import Any, Mapping, Protocol

from v2.benchmark.engine_local_kv_tasks import (
    CompiledKVCase,
    TokenCodec,
    validate_case_output,
)
from v2.integrations.vllm_kv.client import KVStreamResult
from v2.utils import sha256_digest


EXPERIMENT_SCHEMA_VERSION = "statebus.engine_local_kv_experiment.v1"
A_LANE = "A_full_replay"
B_LANE = "B_kv_continuation"
DEFAULT_LANE_ORDER = (A_LANE, B_LANE, B_LANE, A_LANE, A_LANE, B_LANE)


class KVExperimentClient(Protocol):
    def health(self) -> dict[str, Any]: ...

    def produce(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def continue_stream(self, payload: Mapping[str, Any]) -> KVStreamResult: ...

    def release(self, handle_id: str) -> dict[str, Any]: ...


class ExperimentInvariantError(RuntimeError):
    def __init__(self, error_code: str, detail: str = "") -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class KVExperimentConfig:
    run_id: str
    output_dir: Path
    model: str = "qwen3-32b"
    repeat_count: int = 3
    warmup_count_per_lane: int = 1
    lane_order: tuple[str, ...] = DEFAULT_LANE_ORDER
    temperature: float = 0.0
    seed: int = 7
    ttl_s: int = 300
    fail_fast: bool = False
    container_image_id: str = ""
    vllm_launch_manifest_digest: str = ""
    gpu_name: str = ""
    model_path: str = "/data/models/Qwen3-32B"
    git_branch: str = ""
    git_commit: str = ""
    git_status: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.run_id or self.repeat_count <= 0 or self.warmup_count_per_lane < 0:
            raise ValueError("run id and repeat counts must be valid")
        if set(self.lane_order) != {A_LANE, B_LANE}:
            raise ValueError("lane order must contain both A and B")
        if self.lane_order.count(A_LANE) != self.repeat_count or self.lane_order.count(
            B_LANE
        ) != self.repeat_count:
            raise ValueError("lane order counts must equal repeat_count")
        if self.temperature != 0.0 or self.seed < 0 or self.ttl_s <= 0:
            raise ValueError("formal KV experiment requires greedy deterministic sampling")


class EngineLocalKVExperiment:
    def __init__(
        self,
        *,
        client: KVExperimentClient,
        codec: TokenCodec,
        cases: tuple[CompiledKVCase, ...],
        config: KVExperimentConfig,
    ) -> None:
        if not cases:
            raise ValueError("at least one compiled KV case is required")
        self.client = client
        self.codec = codec
        self.cases = cases
        self.config = config
        self.output_dir = config.output_dir
        self.raw_output_dir = self.output_dir / "raw" / "outputs"
        self.raw_error_dir = self.output_dir / "raw" / "stderr"
        self.records_path = self.output_dir / "records.jsonl"
        self.warmup_records_path = self.output_dir / "warmup_records.jsonl"

    def run(self) -> dict[str, Any]:
        self._prepare_output_dir()
        health = self._require_ready_health(self.client.health())
        manifest = self._manifest(health, status="running")
        _write_json(self.output_dir / "manifest.json", manifest)
        _write_json(
            self.output_dir / "compiled_case_index.json",
            {
                "schema_version": EXPERIMENT_SCHEMA_VERSION,
                "cases": [
                    case.canonical_payload(include_token_ids=False)
                    for case in self.cases
                ],
            },
        )
        self._write_environment(health)

        warmup_records: list[dict[str, Any]] = []
        formal_records: list[dict[str, Any]] = []
        post_case_health: dict[str, Any] = {}
        try:
            sequence_index = 0
            for case in self.cases:
                for warmup_index in range(1, self.config.warmup_count_per_lane + 1):
                    for lane in (A_LANE, B_LANE):
                        sequence_index += 1
                        record = self._run_once(
                            case,
                            lane=lane,
                            repeat=warmup_index,
                            sequence_index=sequence_index,
                            warmup=True,
                            compatibility_digest=str(
                                health["compatibility_digest"]
                            ),
                        )
                        warmup_records.append(record)
                        _append_jsonl(self.warmup_records_path, record)
                        if not record["success"]:
                            raise ExperimentInvariantError(
                                "warmup_failed",
                                f"{case.definition.case_id}:{lane}:{record['error_code']}",
                            )

                lane_repeats = {A_LANE: 0, B_LANE: 0}
                for lane in self.config.lane_order:
                    sequence_index += 1
                    lane_repeats[lane] += 1
                    record = self._run_once(
                        case,
                        lane=lane,
                        repeat=lane_repeats[lane],
                        sequence_index=sequence_index,
                        warmup=False,
                        compatibility_digest=str(health["compatibility_digest"]),
                    )
                    formal_records.append(record)
                    _append_jsonl(self.records_path, record)
                    if self.config.fail_fast and not record["success"]:
                        raise ExperimentInvariantError(
                            str(record["error_code"]), str(record["error_detail"])
                        )
                case_health = self._require_ready_health(self.client.health())
                post_case_health[case.definition.case_id] = case_health
                if int(case_health.get("registry_entries", -1)) != 0 or int(
                    case_health.get("registry_bytes", -1)
                ) != 0:
                    raise ExperimentInvariantError(
                        "kv_registry_not_empty", case.definition.case_id
                    )

            summary = summarize_records(formal_records, post_case_health)
            _write_json(self.output_dir / "summary.json", summary)
            _write_text(self.output_dir / "report.md", render_report(summary, formal_records))
            manifest = {
                **manifest,
                "status": "complete",
                "completed_at": _utc_now(),
                "formal_record_count": len(formal_records),
                "warmup_record_count": len(warmup_records),
                "summary_digest": sha256_digest(summary),
            }
            _write_json(self.output_dir / "manifest.json", manifest)
            return summary
        except Exception as exc:
            error_code, error_detail = _error_parts(exc)
            failure = {
                "schema_version": EXPERIMENT_SCHEMA_VERSION,
                "status": "failed",
                "error_code": error_code,
                "error_detail": error_detail,
                "failed_at": _utc_now(),
                "formal_record_count": len(formal_records),
                "warmup_record_count": len(warmup_records),
            }
            _write_json(self.output_dir / "failure.json", failure)
            _write_json(
                self.output_dir / "manifest.json",
                {**manifest, **failure},
            )
            raise

    def _run_once(
        self,
        case: CompiledKVCase,
        *,
        lane: str,
        repeat: int,
        sequence_index: int,
        warmup: bool,
        compatibility_digest: str,
    ) -> dict[str, Any]:
        api_lane = "full_replay" if lane == A_LANE else "kv_continuation"
        capture_kv = lane == B_LANE
        request_prefix = (
            f"{self.config.run_id}-{case.definition.case_id}-"
            f"{'warmup' if warmup else 'formal'}-{lane[0]}{repeat}"
        )
        producer_request_id = f"{request_prefix}-producer"[-240:]
        consumer_request_id = f"{request_prefix}-consumer"[-240:]
        started_ns = time.perf_counter_ns()
        started_at = _utc_now()
        producer: dict[str, Any] = {}
        consumer: dict[str, Any] = {}
        release: dict[str, Any] = {}
        quality_payload: dict[str, Any] = {
            "passed": False,
            "parsed": None,
            "errors": ["consumer_not_completed"],
        }
        handle_id = ""
        suffix_ids: tuple[int, ...] = ()
        expected_logical_digest = ""
        error_code = ""
        error_detail = ""
        client_ttft_ms = 0.0
        client_wall_ms = 0.0
        api_request_bytes = 0
        token_event_count = 0
        try:
            producer = self.client.produce(
                {
                    "model": self.config.model,
                    "request_id": producer_request_id,
                    "task_id": case.definition.case_id,
                    "parent_token_ids": list(case.parent_token_ids),
                    "producer_suffix_token_ids": list(
                        case.producer_suffix_token_ids
                    ),
                    "capture_kv": capture_kv,
                    "ttl_s": self.config.ttl_s,
                    "sampling": {
                        "temperature": self.config.temperature,
                        "max_tokens": case.producer_max_tokens,
                        "seed": self.config.seed,
                    },
                    "expected_compatibility_digest": compatibility_digest,
                }
            )
            handle_id = self._validate_producer(case, lane, producer)
            executor_output = str(producer.get("output_text", ""))
            suffix_ids = case.consumer_suffix_token_ids(self.codec, executor_output)
            expected_logical_digest = sha256_digest(
                list(case.parent_token_ids + suffix_ids)
            )
            consumer_request: dict[str, Any] = {
                "model": self.config.model,
                "request_id": consumer_request_id,
                "task_id": case.definition.case_id,
                "lane": api_lane,
                "suffix_token_ids": list(suffix_ids),
                "sampling": {
                    "temperature": self.config.temperature,
                    "max_tokens": case.consumer_max_tokens,
                    "seed": self.config.seed,
                },
                "expected_compatibility_digest": compatibility_digest,
            }
            if lane == A_LANE:
                consumer_request["parent_token_ids"] = list(case.parent_token_ids)
            else:
                consumer_request["handle_id"] = handle_id
            stream_result = self.client.continue_stream(consumer_request)
            consumer = dict(stream_result.payload)
            client_ttft_ms = float(stream_result.client_ttft_ms)
            client_wall_ms = float(stream_result.client_wall_ms)
            api_request_bytes = int(stream_result.api_request_bytes)
            token_event_count = int(stream_result.token_event_count)
            self._validate_consumer(
                case,
                lane,
                suffix_ids,
                expected_logical_digest,
                producer,
                consumer,
                stream_result,
            )
            quality = validate_case_output(case, str(consumer.get("output_text", "")))
            quality_payload = quality.canonical_payload()
        except Exception as exc:
            error_code, error_detail = _error_parts(exc)
        finally:
            if handle_id:
                try:
                    release = self.client.release(handle_id)
                    if release.get("status") != "released":
                        raise ExperimentInvariantError(
                            "kv_release_failed", str(release.get("status", ""))
                        )
                except Exception as exc:
                    release_code, release_detail = _error_parts(exc)
                    if not error_code:
                        error_code, error_detail = release_code, release_detail
                    else:
                        error_detail = (
                            f"{error_detail};release={release_code}:{release_detail}"
                        )

        finished_ns = time.perf_counter_ns()
        producer_telemetry = _mapping(producer.get("telemetry"))
        consumer_telemetry = _mapping(consumer.get("telemetry"))
        executor_output = str(producer.get("output_text", ""))
        consumer_output = str(consumer.get("output_text", ""))
        producer_output_token_ids = _token_ids(producer.get("output_token_ids"))
        consumer_output_token_ids = _token_ids(consumer.get("output_token_ids"))
        record = {
            "schema_version": EXPERIMENT_SCHEMA_VERSION,
            "run_id": self.config.run_id,
            "case_id": case.definition.case_id,
            "lane": lane,
            "api_lane": api_lane,
            "repeat": repeat,
            "sequence_index": sequence_index,
            "warmup": warmup,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "success": not error_code,
            "error_code": error_code,
            "error_detail": error_detail,
            "producer_request_id": producer_request_id,
            "consumer_request_id": consumer_request_id,
            "handle_id": handle_id,
            "parent_tokens": len(case.parent_token_ids),
            "producer_suffix_tokens": len(case.producer_suffix_token_ids),
            "logical_input_tokens": len(case.parent_token_ids) + len(suffix_ids),
            "suffix_tokens": len(suffix_ids),
            "computed_prefill_tokens": int(
                consumer_telemetry.get("computed_prefill_tokens", 0)
            ),
            "inherited_kv_tokens": int(
                consumer_telemetry.get("inherited_kv_tokens", 0)
            ),
            "generated_tokens": int(consumer_telemetry.get("generated_tokens", 0)),
            "producer_generated_tokens": int(
                producer_telemetry.get("generated_tokens", 0)
            ),
            "consumer_ttft_ms": client_ttft_ms,
            "consumer_client_wall_ms": client_wall_ms,
            "consumer_server_first_output_ms": float(
                consumer_telemetry.get("server_first_output_ms", 0.0)
            ),
            "consumer_server_wall_ms": float(
                consumer_telemetry.get("server_wall_ms", 0.0)
            ),
            "producer_server_first_output_ms": float(
                producer_telemetry.get("server_first_output_ms", 0.0)
            ),
            "producer_server_wall_ms": float(
                producer_telemetry.get("server_wall_ms", 0.0)
            ),
            "chain_wall_time_ms": (finished_ns - started_ns) / 1_000_000.0,
            "kv_store_ms": float(producer_telemetry.get("kv_store_ms", 0.0)),
            "kv_load_ms": float(consumer_telemetry.get("kv_load_ms", 0.0)),
            "kv_bytes_actual": int(
                consumer_telemetry.get(
                    "kv_bytes_actual",
                    producer_telemetry.get("kv_bytes_actual", 0),
                )
            ),
            "layer_count": int(
                consumer_telemetry.get(
                    "layer_count", producer_telemetry.get("layer_count", 0)
                )
            ),
            "connector_load_count": int(
                consumer_telemetry.get("connector_load_count", 0)
            ),
            "num_cached_tokens_reported": int(
                consumer_telemetry.get("num_cached_tokens_reported", 0)
            ),
            "api_request_bytes": api_request_bytes,
            "token_event_count": token_event_count,
            "parent_token_digest": case.parent_token_digest,
            "expected_logical_token_digest": expected_logical_digest,
            "observed_logical_token_digest": str(
                consumer.get("logical_token_digest", "")
            ),
            "executor_output_digest": sha256_digest(executor_output),
            "consumer_output_digest": sha256_digest(consumer_output),
            "producer_first_token_id": _first_token_id(producer_output_token_ids),
            "consumer_first_token_id": _first_token_id(consumer_output_token_ids),
            "producer_output_token_digest": sha256_digest(
                list(producer_output_token_ids)
            ),
            "consumer_output_token_digest": sha256_digest(
                list(consumer_output_token_ids)
            ),
            "quality_pass": bool(quality_payload["passed"]),
            "quality_errors": list(quality_payload["errors"]),
            "forward_proof_hash": str(
                consumer_telemetry.get("forward_proof_hash", "")
            ),
            "release_status": str(release.get("status", "")),
        }
        raw_payload = {
            "record": record,
            "producer": producer,
            "consumer": consumer,
            "release": release,
            "quality": quality_payload,
        }
        raw_name = (
            f"{sequence_index:03d}_{case.definition.case_id}_{lane}_r{repeat}"
            f"{'_warmup' if warmup else ''}.json"
        )
        _write_json(self.raw_output_dir / raw_name, raw_payload)
        if error_code:
            _write_text(
                self.raw_error_dir / raw_name.replace(".json", ".txt"),
                f"{error_code}: {error_detail}\n",
            )
        return record

    def _validate_producer(
        self,
        case: CompiledKVCase,
        lane: str,
        payload: Mapping[str, Any],
    ) -> str:
        if payload.get("status") != "success":
            raise ExperimentInvariantError("producer_failed")
        telemetry = _mapping(payload.get("telemetry"))
        logical = len(case.parent_token_ids) + len(case.producer_suffix_token_ids)
        expected = {
            "logical_prompt_tokens": logical,
            "parent_tokens": len(case.parent_token_ids),
            "producer_suffix_tokens": len(case.producer_suffix_token_ids),
            "computed_prefill_tokens": logical,
        }
        if any(telemetry.get(key) != value for key, value in expected.items()):
            raise ExperimentInvariantError(
                "producer_token_accounting_invalid", case.definition.case_id
            )
        if int(telemetry.get("generated_tokens", 0)) <= 0 or not str(
            payload.get("output_text", "")
        ).strip():
            raise ExperimentInvariantError("producer_output_empty")
        output_token_ids = _token_ids(payload.get("output_token_ids"))
        if len(output_token_ids) != int(telemetry["generated_tokens"]):
            raise ExperimentInvariantError("producer_output_token_accounting_invalid")
        handle_id = str(payload.get("handle_id", ""))
        handle = payload.get("handle")
        if lane == B_LANE:
            handle_payload = _mapping(handle)
            if (
                not handle_id
                or handle_payload.get("status") != "ready"
                or int(handle_payload.get("seq_len", 0)) != len(case.parent_token_ids)
                or str(handle_payload.get("token_digest", ""))
                != case.parent_token_digest
                or int(handle_payload.get("kv_bytes_actual", 0)) <= 0
                or int(handle_payload.get("layer_count", 0)) <= 0
            ):
                raise ExperimentInvariantError("kv_capture_incomplete")
        elif handle_id or handle is not None or int(
            telemetry.get("kv_bytes_actual", 0)
        ):
            raise ExperimentInvariantError("full_replay_producer_contaminated")
        return handle_id

    def _validate_consumer(
        self,
        case: CompiledKVCase,
        lane: str,
        suffix_ids: tuple[int, ...],
        expected_digest: str,
        producer: Mapping[str, Any],
        consumer: Mapping[str, Any],
        stream_result: KVStreamResult,
    ) -> None:
        api_lane = "full_replay" if lane == A_LANE else "kv_continuation"
        if (
            consumer.get("status") != "success"
            or consumer.get("lane") != api_lane
            or consumer.get("logical_token_digest") != expected_digest
            or not str(consumer.get("output_text", "")).strip()
            or stream_result.token_event_count <= 0
        ):
            raise ExperimentInvariantError("consumer_response_invalid")
        telemetry = _mapping(consumer.get("telemetry"))
        output_token_ids = _token_ids(consumer.get("output_token_ids"))
        logical = len(case.parent_token_ids) + len(suffix_ids)
        if (
            int(telemetry.get("logical_prompt_tokens", 0)) != logical
            or int(telemetry.get("parent_tokens", 0))
            != len(case.parent_token_ids)
            or int(telemetry.get("suffix_tokens", 0)) != len(suffix_ids)
            or int(telemetry.get("generated_tokens", 0)) <= 0
            or len(output_token_ids) != int(telemetry.get("generated_tokens", 0))
        ):
            raise ExperimentInvariantError("consumer_token_accounting_invalid")
        if lane == A_LANE:
            if (
                int(telemetry.get("computed_prefill_tokens", 0)) != logical
                or int(telemetry.get("inherited_kv_tokens", -1)) != 0
                or int(telemetry.get("connector_load_count", -1)) != 0
                or consumer.get("forward_proof") is not None
            ):
                raise ExperimentInvariantError("full_replay_mechanism_invalid")
            return
        proof = _mapping(consumer.get("forward_proof"))
        producer_telemetry = _mapping(producer.get("telemetry"))
        if (
            int(telemetry.get("computed_prefill_tokens", 0)) != len(suffix_ids)
            or int(telemetry.get("inherited_kv_tokens", 0))
            != len(case.parent_token_ids)
            or int(telemetry.get("connector_load_count", 0)) != 1
            or not str(telemetry.get("forward_proof_hash", ""))
            or int(telemetry.get("kv_bytes_actual", 0))
            != int(producer_telemetry.get("kv_bytes_actual", -1))
            or int(proof.get("connector_load_count", 0)) != 1
            or int(proof.get("computed_prefill_tokens", 0)) != len(suffix_ids)
        ):
            raise ExperimentInvariantError("kv_consumer_forward_not_observed")

    def _prepare_output_dir(self) -> None:
        if self.output_dir.exists() and any(self.output_dir.iterdir()):
            raise ValueError(f"output directory is not empty: {self.output_dir}")
        self.raw_output_dir.mkdir(parents=True, exist_ok=True)
        self.raw_error_dir.mkdir(parents=True, exist_ok=True)

    def _require_ready_health(self, health: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(health)
        required = {
            "status": "ready",
            "model": self.config.model,
            "automatic_prefix_caching": False,
            "kv_connector": "StateBusLocalKVConnector",
            "kv_role": "kv_both",
            "max_num_seqs": 1,
            "tensor_parallel_size": 1,
            "pipeline_parallel_size": 1,
        }
        if any(value.get(key) != expected for key, expected in required.items()):
            raise ExperimentInvariantError("kv_plugin_not_ready", "health_gate")
        if not str(value.get("compatibility_digest", "")):
            raise ExperimentInvariantError(
                "kv_plugin_not_ready", "compatibility_digest"
            )
        return value

    def _manifest(self, health: Mapping[str, Any], *, status: str) -> dict[str, Any]:
        local_git_status = _git_output("status", "--short")
        git_status = (
            local_git_status.splitlines()
            if local_git_status
            else list(self.config.git_status)
        )
        return {
            "schema_version": EXPERIMENT_SCHEMA_VERSION,
            "run_id": self.config.run_id,
            "status": status,
            "started_at": _utc_now(),
            "git_branch": _git_output("branch", "--show-current")
            or self.config.git_branch,
            "git_commit": _git_output("rev-parse", "HEAD")
            or self.config.git_commit,
            "dirty_worktree": bool(git_status),
            "git_status": git_status,
            "model_path": self.config.model_path,
            "model": self.config.model,
            "model_config_digest": str(health.get("model_revision", "")),
            "tokenizer_digest": str(health.get("tokenizer_digest", "")),
            "vllm_version": str(health.get("vllm_version", "")),
            "torch_version": "recorded_by_service_launch_manifest",
            "cuda_version": "recorded_by_service_launch_manifest",
            "gpu_name": self.config.gpu_name,
            "container_image_id": self.config.container_image_id,
            "vllm_launch_manifest_digest": self.config.vllm_launch_manifest_digest,
            "vllm_engine_generation": str(health.get("engine_generation", "")),
            "kv_connector_name": str(health.get("kv_connector", "")),
            "automatic_prefix_caching": bool(
                health.get("automatic_prefix_caching", True)
            ),
            "storage_tier": (
                "worker_pinned_host"
                if health.get("registry_pin_memory")
                else "worker_pageable_host"
            ),
            "generation_config": {
                "temperature": self.config.temperature,
                "seed": self.config.seed,
                "producer_max_tokens": sorted(
                    {case.producer_max_tokens for case in self.cases}
                ),
                "consumer_max_tokens": sorted(
                    {case.consumer_max_tokens for case in self.cases}
                ),
            },
            "case_ids": [case.definition.case_id for case in self.cases],
            "case_parent_tokens": {
                case.definition.case_id: len(case.parent_token_ids)
                for case in self.cases
            },
            "case_parent_token_digests": {
                case.definition.case_id: case.parent_token_digest
                for case in self.cases
            },
            "lane_order": list(self.config.lane_order),
            "repeat_count": self.config.repeat_count,
            "warmup_count_per_lane": self.config.warmup_count_per_lane,
            "serialized_execution": True,
            "health_at_start": dict(health),
        }

    def _write_environment(self, health: Mapping[str, Any]) -> None:
        lines = [
            f"recorded_at={_utc_now()}",
            f"python={sys.version.replace(chr(10), ' ')}",
            f"platform={platform.platform()}",
            f"model={self.config.model}",
            f"model_path={self.config.model_path}",
            f"vllm_version={health.get('vllm_version', '')}",
            f"engine_id={health.get('engine_id', '')}",
            f"engine_generation={health.get('engine_generation', '')}",
            f"compatibility_digest={health.get('compatibility_digest', '')}",
            f"block_size={health.get('block_size', '')}",
            f"automatic_prefix_caching={health.get('automatic_prefix_caching', '')}",
            f"registry_pin_memory={health.get('registry_pin_memory', '')}",
        ]
        _write_text(self.output_dir / "environment.txt", "\n".join(lines) + "\n")


def summarize_records(
    records: list[dict[str, Any]],
    post_case_health: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    case_ids = list(dict.fromkeys(str(record["case_id"]) for record in records))
    by_case = {
        case_id: _summarize_group(
            [record for record in records if record["case_id"] == case_id]
        )
        for case_id in case_ids
    }
    total = _summarize_group(records)
    headline = _select_headline(by_case, total)
    return {
        "schema_version": EXPERIMENT_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "formal_record_count": len(records),
        "by_case": by_case,
        "total": total,
        "headline": headline,
        "post_case_health": dict(post_case_health or {}),
    }


def _summarize_group(records: list[dict[str, Any]]) -> dict[str, Any]:
    lanes: dict[str, dict[str, Any]] = {}
    for lane in (A_LANE, B_LANE):
        lane_records = [record for record in records if record["lane"] == lane]
        successful = [record for record in lane_records if record["success"]]
        lanes[lane] = {
            "count": len(lane_records),
            "success_count": len(successful),
            "quality_pass_count": sum(
                bool(record["quality_pass"]) for record in lane_records
            ),
            "p50_consumer_ttft_ms": _median(successful, "consumer_ttft_ms"),
            "p50_consumer_client_wall_ms": _median(
                successful, "consumer_client_wall_ms"
            ),
            "p50_consumer_server_first_output_ms": _median(
                successful, "consumer_server_first_output_ms"
            ),
            "p50_chain_wall_time_ms": _median(successful, "chain_wall_time_ms"),
            "p50_computed_prefill_tokens": _median(
                successful, "computed_prefill_tokens"
            ),
            "p50_inherited_kv_tokens": _median(
                successful, "inherited_kv_tokens"
            ),
            "p50_kv_store_ms": _median(successful, "kv_store_ms"),
            "p50_kv_load_ms": _median(successful, "kv_load_ms"),
            "p50_kv_bytes_actual": _median(successful, "kv_bytes_actual"),
            "max_kv_bytes_actual": max(
                (int(record["kv_bytes_actual"]) for record in successful),
                default=0,
            ),
            "p50_api_request_bytes": _median(successful, "api_request_bytes"),
        }
    a = lanes[A_LANE]
    b = lanes[B_LANE]
    pair_rows: list[dict[str, Any]] = []
    pair_keys = sorted(
        {
            (str(record["case_id"]), int(record["repeat"]))
            for record in records
        }
    )
    for case_id, repeat in pair_keys:
        a_record = next(
            (
                record
                for record in records
                if record["case_id"] == case_id
                and record["lane"] == A_LANE
                and int(record["repeat"]) == repeat
            ),
            None,
        )
        b_record = next(
            (
                record
                for record in records
                if record["case_id"] == case_id
                and record["lane"] == B_LANE
                and int(record["repeat"]) == repeat
            ),
            None,
        )
        if a_record is None or b_record is None:
            continue
        pair_rows.append(
            {
                "case_id": case_id,
                "repeat": repeat,
                "both_success": bool(a_record["success"] and b_record["success"]),
                "logical_token_digest_match": (
                    a_record["observed_logical_token_digest"]
                    == b_record["observed_logical_token_digest"]
                    and bool(a_record["observed_logical_token_digest"])
                ),
                "quality_parity": bool(
                    a_record["quality_pass"] == b_record["quality_pass"]
                ),
                "first_output_token_match": (
                    int(a_record["consumer_first_token_id"])
                    == int(b_record["consumer_first_token_id"])
                    and int(a_record["consumer_first_token_id"]) >= 0
                ),
                "output_token_digest_match": (
                    a_record["consumer_output_token_digest"]
                    == b_record["consumer_output_token_digest"]
                    and bool(a_record["consumer_output_token_digest"])
                ),
                "producer_output_token_digest_match": (
                    a_record["producer_output_token_digest"]
                    == b_record["producer_output_token_digest"]
                    and bool(a_record["producer_output_token_digest"])
                ),
            }
        )
    return {
        "lanes": lanes,
        "computed_prefill_reduction": _reduction(
            a["p50_computed_prefill_tokens"], b["p50_computed_prefill_tokens"]
        ),
        "consumer_ttft_reduction": _reduction(
            a["p50_consumer_ttft_ms"], b["p50_consumer_ttft_ms"]
        ),
        "chain_wall_time_reduction": _reduction(
            a["p50_chain_wall_time_ms"], b["p50_chain_wall_time_ms"]
        ),
        "api_request_bytes_reduction": _reduction(
            a["p50_api_request_bytes"], b["p50_api_request_bytes"]
        ),
        "pair_count": len(pair_rows),
        "pair_digest_match_count": sum(
            bool(row["logical_token_digest_match"]) for row in pair_rows
        ),
        "pair_quality_parity_count": sum(bool(row["quality_parity"]) for row in pair_rows),
        "pair_first_output_token_match_count": sum(
            bool(row["first_output_token_match"]) for row in pair_rows
        ),
        "pair_output_token_digest_match_count": sum(
            bool(row["output_token_digest_match"]) for row in pair_rows
        ),
        "pair_producer_output_token_digest_match_count": sum(
            bool(row["producer_output_token_digest_match"]) for row in pair_rows
        ),
        "pairs": pair_rows,
    }


def _select_headline(
    by_case: Mapping[str, Mapping[str, Any]],
    total: Mapping[str, Any],
) -> dict[str, Any]:
    eligible = [
        (case_id, summary)
        for case_id, summary in by_case.items()
        if summary["lanes"][A_LANE]["success_count"]
        == summary["lanes"][A_LANE]["count"]
        and summary["lanes"][B_LANE]["success_count"]
        == summary["lanes"][B_LANE]["count"]
        and summary["lanes"][B_LANE]["quality_pass_count"]
        >= summary["lanes"][A_LANE]["quality_pass_count"]
        and summary["pair_count"] > 0
        and summary["pair_digest_match_count"] == summary["pair_count"]
        and summary["pair_output_token_digest_match_count"]
        == summary["pair_count"]
        and summary["pair_producer_output_token_digest_match_count"]
        == summary["pair_count"]
    ]
    chain = [
        (case_id, float(summary["chain_wall_time_reduction"]))
        for case_id, summary in eligible
        if float(summary["chain_wall_time_reduction"]) >= 0.10
    ]
    if chain:
        case_id, value = max(chain, key=lambda item: item[1])
        return {
            "kind": "chain_wall_time",
            "case_id": case_id,
            "reduction": value,
            "text": f"{case_id} end-to-end chain wall time decreased by {value:.1%}.",
        }
    ttft = [
        (case_id, float(summary["consumer_ttft_reduction"]))
        for case_id, summary in eligible
        if float(summary["consumer_ttft_reduction"]) >= 0.20
    ]
    if ttft:
        case_id, value = max(ttft, key=lambda item: item[1])
        return {
            "kind": "consumer_ttft",
            "case_id": case_id,
            "reduction": value,
            "text": f"{case_id} consumer TTFT decreased by {value:.1%}.",
        }
    computed = [
        (case_id, float(summary["computed_prefill_reduction"]))
        for case_id, summary in eligible
        if float(summary["computed_prefill_reduction"]) >= 0.70
    ]
    if computed:
        case_id, value = max(computed, key=lambda item: item[1])
        return {
            "kind": "computed_prefill_tokens",
            "case_id": case_id,
            "reduction": value,
            "text": f"{case_id} repeated prefill computation decreased by {value:.1%}.",
        }
    return {
        "kind": "none",
        "case_id": "",
        "reduction": 0.0,
        "text": "No predefined positive headline threshold was met.",
        "total": dict(total),
    }


def render_report(
    summary: Mapping[str, Any],
    records: list[dict[str, Any]],
) -> str:
    lines = [
        "# StateBus Experimental Engine-Local KV Continuation Results",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        "This experiment compares full replay with explicit, one-shot KV continuation "
        "inside one Qwen3-32B vLLM engine. Automatic prefix caching is disabled.",
        "",
        f"Headline: {summary['headline']['text']}",
        "",
        "## Case Summary",
        "",
        "| case | A success | B success | A TTFT p50 ms | B TTFT p50 ms | "
        "TTFT reduction | A computed p50 | B computed p50 | computed reduction | "
        "A quality | B quality | logical digest pairs | output token pairs |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case_id, case_summary in summary["by_case"].items():
        a = case_summary["lanes"][A_LANE]
        b = case_summary["lanes"][B_LANE]
        lines.append(
            f"| {case_id} | {a['success_count']}/{a['count']} | "
            f"{b['success_count']}/{b['count']} | "
            f"{_format_number(a['p50_consumer_ttft_ms'])} | "
            f"{_format_number(b['p50_consumer_ttft_ms'])} | "
            f"{_format_percent(case_summary['consumer_ttft_reduction'])} | "
            f"{_format_number(a['p50_computed_prefill_tokens'])} | "
            f"{_format_number(b['p50_computed_prefill_tokens'])} | "
            f"{_format_percent(case_summary['computed_prefill_reduction'])} | "
            f"{a['quality_pass_count']}/{a['count']} | "
            f"{b['quality_pass_count']}/{b['count']} | "
            f"{case_summary['pair_digest_match_count']}/{case_summary['pair_count']} | "
            f"{case_summary['pair_output_token_digest_match_count']}/{case_summary['pair_count']} |"
        )
    lines.extend(
        [
            "",
            "## Raw Formal Runs",
            "",
            "| seq | case | lane | repeat | success | logical | computed | inherited | "
            "TTFT ms | chain ms | store ms | load ms | KV bytes | quality | error |",
            "| ---: | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for record in records:
        lines.append(
            f"| {record['sequence_index']} | {record['case_id']} | {record['lane']} | "
            f"{record['repeat']} | {record['success']} | {record['logical_input_tokens']} | "
            f"{record['computed_prefill_tokens']} | {record['inherited_kv_tokens']} | "
            f"{record['consumer_ttft_ms']:.3f} | {record['chain_wall_time_ms']:.3f} | "
            f"{record['kv_store_ms']:.3f} | {record['kv_load_ms']:.3f} | "
            f"{record['kv_bytes_actual']} | {record['quality_pass']} | "
            f"{record['error_code']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "`computed_prefill_tokens` measures model-side recomputation, not logical or "
            "billable prompt tokens. The mechanism is engine-local and does not claim "
            "cross-worker, cross-GPU, persistent, or automatic prefix-cache reuse.",
            "",
        ]
    )
    return "\n".join(lines)


def _median(records: list[dict[str, Any]], key: str) -> float:
    values = [float(record[key]) for record in records]
    return float(statistics.median(values)) if values else 0.0


def _reduction(baseline: Any, candidate: Any) -> float:
    baseline_value = float(baseline or 0.0)
    if baseline_value <= 0:
        return 0.0
    return 1.0 - float(candidate or 0.0) / baseline_value


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _token_ids(value: Any) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    try:
        token_ids = tuple(int(item) for item in value)
    except (TypeError, ValueError):
        return ()
    return token_ids if all(item >= 0 for item in token_ids) else ()


def _first_token_id(token_ids: tuple[int, ...]) -> int:
    return token_ids[0] if token_ids else -1


def _error_parts(exc: BaseException) -> tuple[str, str]:
    code = str(getattr(exc, "error_code", "")) or type(exc).__name__
    detail = str(getattr(exc, "detail", "")) or str(exc)
    return code, detail


def _git_output(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return completed.stdout.strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _write_text(path, json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n")


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _format_number(value: Any) -> str:
    return f"{float(value):.3f}"


def _format_percent(value: Any) -> str:
    return f"{float(value):.1%}"


__all__ = [
    "A_LANE",
    "B_LANE",
    "DEFAULT_LANE_ORDER",
    "EngineLocalKVExperiment",
    "ExperimentInvariantError",
    "KVExperimentConfig",
    "summarize_records",
    "render_report",
]
