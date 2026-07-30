from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from statebus.benchmark.engine_local_kv_experiment import (
    A_LANE,
    B_LANE,
    EngineLocalKVExperiment,
    KVExperimentConfig,
)
from statebus.benchmark.engine_local_kv_tasks import CompiledKVCase, KVCaseDefinition
from statebus.integrations.vllm_kv.client import KVStreamResult
from statebus.utils import sha256_digest


class _CharacterCodec:
    def encode(self, text: str) -> tuple[int, ...]:
        return tuple(ord(character) for character in text)

    def decode(self, token_ids: tuple[int, ...]) -> str:
        return "".join(chr(value) for value in token_ids)


class _FakeKVClient:
    compatibility_digest = "compatibility-digest"

    def __init__(self, cases: tuple[CompiledKVCase, ...], *, bad_proof: bool = False) -> None:
        self.expected_outputs = {
            case.definition.case_id: dict(case.definition.expected_json)
            for case in cases
        }
        self.handles: dict[str, tuple[int, ...]] = {}
        self.release_calls: list[str] = []
        self.bad_proof = bad_proof
        self.handle_counter = 0

    def health(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "model": "qwen3-32b",
            "model_revision": "model-revision",
            "tokenizer_digest": "tokenizer-digest",
            "vllm_version": "0.9.2",
            "engine_id": "engine-1",
            "engine_generation": "generation-1",
            "compatibility_digest": self.compatibility_digest,
            "block_size": 2,
            "automatic_prefix_caching": False,
            "registry_pin_memory": False,
            "registry_entries": len(self.handles),
            "registry_bytes": len(self.handles) * 1024,
            "kv_connector": "StateBusLocalKVConnector",
            "kv_role": "kv_both",
            "max_num_seqs": 1,
            "tensor_parallel_size": 1,
            "pipeline_parallel_size": 1,
        }

    def produce(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        parent_ids = tuple(int(value) for value in payload["parent_token_ids"])
        producer_suffix_ids = tuple(
            int(value) for value in payload["producer_suffix_token_ids"]
        )
        capture_kv = bool(payload["capture_kv"])
        handle_id = ""
        handle = None
        kv_bytes = 0
        layer_count = 0
        if capture_kv:
            self.handle_counter += 1
            handle_id = f"handle-{self.handle_counter}"
            self.handles[handle_id] = parent_ids
            kv_bytes = len(parent_ids) * 256
            layer_count = 2
            handle = {
                "handle_id": handle_id,
                "status": "ready",
                "seq_len": len(parent_ids),
                "token_digest": sha256_digest(list(parent_ids)),
                "kv_bytes_actual": kv_bytes,
                "layer_count": layer_count,
            }
        logical = len(parent_ids) + len(producer_suffix_ids)
        return {
            "status": "success",
            "handle_id": handle_id,
            "handle": handle,
            "output_text": '{"draft":"stable"}',
            "output_token_ids": [300, 301, 302, 303, 304],
            "telemetry": {
                "logical_prompt_tokens": logical,
                "parent_tokens": len(parent_ids),
                "producer_suffix_tokens": len(producer_suffix_ids),
                "computed_prefill_tokens": logical,
                "generated_tokens": 5,
                "server_first_output_ms": 11.0,
                "server_wall_ms": 14.0,
                "kv_store_ms": 1.5 if capture_kv else 0.0,
                "kv_bytes_actual": kv_bytes,
                "layer_count": layer_count,
            },
        }

    def continue_stream(self, payload: Mapping[str, Any]) -> KVStreamResult:
        suffix_ids = tuple(int(value) for value in payload["suffix_token_ids"])
        lane = str(payload["lane"])
        if lane == "full_replay":
            parent_ids = tuple(int(value) for value in payload["parent_token_ids"])
            inherited = 0
            computed = len(parent_ids) + len(suffix_ids)
            connector_load_count = 0
            kv_bytes = 0
            layer_count = 0
            forward_proof = None
            forward_proof_hash = ""
            ttft_ms = 100.0
            api_request_bytes = 4096
        else:
            parent_ids = self.handles[str(payload["handle_id"])]
            inherited = len(parent_ids)
            computed = len(suffix_ids)
            connector_load_count = 0 if self.bad_proof else 1
            kv_bytes = len(parent_ids) * 256
            layer_count = 2
            forward_proof = {
                "connector_load_count": connector_load_count,
                "computed_prefill_tokens": computed,
            }
            forward_proof_hash = "" if self.bad_proof else "proof-hash"
            ttft_ms = 25.0
            api_request_bytes = 512
        logical_ids = parent_ids + suffix_ids
        telemetry = {
            "logical_prompt_tokens": len(logical_ids),
            "parent_tokens": len(parent_ids),
            "suffix_tokens": len(suffix_ids),
            "computed_prefill_tokens": computed,
            "inherited_kv_tokens": inherited,
            "generated_tokens": 8,
            "connector_load_count": connector_load_count,
            "num_cached_tokens_reported": inherited,
            "forward_proof_hash": forward_proof_hash,
            "kv_bytes_actual": kv_bytes,
            "layer_count": layer_count,
            "kv_load_ms": 2.0 if inherited else 0.0,
            "server_first_output_ms": ttft_ms - 2.0,
            "server_wall_ms": ttft_ms + 5.0,
        }
        output_text = json.dumps(self.expected_outputs[str(payload["task_id"])])
        return KVStreamResult(
            payload={
                "status": "success",
                "lane": lane,
                "logical_token_digest": sha256_digest(list(logical_ids)),
                "output_text": output_text,
                "output_token_ids": list(range(400, 408)),
                "forward_proof": forward_proof,
                "telemetry": telemetry,
            },
            client_ttft_ms=ttft_ms,
            client_wall_ms=ttft_ms + 10.0,
            api_request_bytes=api_request_bytes,
            token_event_count=2,
        )

    def release(self, handle_id: str) -> dict[str, Any]:
        self.release_calls.append(handle_id)
        self.handles.pop(handle_id, None)
        return {"status": "released", "handle_id": handle_id}


def _cases(count: int = 3) -> tuple[CompiledKVCase, ...]:
    cases: list[CompiledKVCase] = []
    for index in range(count):
        parent_ids = tuple(range(10 + index * 4, 14 + index * 4))
        producer_suffix_ids = (100 + index, 200 + index)
        expected = {"answer": index + 1}
        definition = KVCaseDefinition(
            case_id=f"case-{index + 1}",
            target_parent_tokens=len(parent_ids),
            source_documents=(f"source-{index + 1}.md",),
            task_instruction="Return the answer.",
            required_keys=("answer",),
            expected_json=expected,
            keyword_expectations={},
        )
        cases.append(
            CompiledKVCase(
                definition=definition,
                parent_token_ids=parent_ids,
                producer_suffix_token_ids=producer_suffix_ids,
                parent_text="parent",
                source_digest=sha256_digest("parent"),
                parent_token_digest=sha256_digest(list(parent_ids)),
                producer_suffix_digest=sha256_digest(list(producer_suffix_ids)),
                block_size=2,
                max_model_len=8192,
                max_logical_sequence_tokens=8192,
                producer_max_tokens=16,
                consumer_max_tokens=16,
            )
        )
    return tuple(cases)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_runner_writes_complete_fixed_order_ab_evidence_bundle(tmp_path: Path) -> None:
    cases = _cases()
    client = _FakeKVClient(cases)
    output_dir = tmp_path / "run"
    experiment = EngineLocalKVExperiment(
        client=client,
        codec=_CharacterCodec(),
        cases=cases,
        config=KVExperimentConfig(run_id="fake-formal", output_dir=output_dir),
    )

    summary = experiment.run()

    formal = _read_jsonl(output_dir / "records.jsonl")
    warmups = _read_jsonl(output_dir / "warmup_records.jsonl")
    assert len(formal) == 18
    assert len(warmups) == 6
    assert len(list((output_dir / "raw" / "outputs").glob("*.json"))) == 24
    assert not list((output_dir / "raw" / "stderr").glob("*.txt"))
    assert all(record["success"] and record["quality_pass"] for record in formal)
    assert all(record["release_status"] == "released" for record in formal if record["lane"] == B_LANE)
    for case in cases:
        rows = [record for record in formal if record["case_id"] == case.definition.case_id]
        assert [record["lane"] for record in rows] == [
            A_LANE,
            B_LANE,
            B_LANE,
            A_LANE,
            A_LANE,
            B_LANE,
        ]
        case_summary = summary["by_case"][case.definition.case_id]
        assert case_summary["pair_digest_match_count"] == 3
        assert case_summary["pair_quality_parity_count"] == 3
        assert case_summary["pair_first_output_token_match_count"] == 3
        assert case_summary["pair_output_token_digest_match_count"] == 3
        assert case_summary["pair_producer_output_token_digest_match_count"] == 3
        assert case_summary["computed_prefill_reduction"] > 0
        assert case_summary["consumer_ttft_reduction"] == 0.75
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"
    assert manifest["formal_record_count"] == 18
    assert manifest["warmup_record_count"] == 6
    assert summary["formal_record_count"] == 18
    assert summary["total"]["pair_count"] == 9
    assert "Raw Formal Runs" in (output_dir / "report.md").read_text(encoding="utf-8")
    assert not client.handles


def test_runner_releases_handle_when_kv_forward_proof_is_invalid(tmp_path: Path) -> None:
    cases = _cases(1)
    client = _FakeKVClient(cases, bad_proof=True)
    output_dir = tmp_path / "failed-proof"
    experiment = EngineLocalKVExperiment(
        client=client,
        codec=_CharacterCodec(),
        cases=cases,
        config=KVExperimentConfig(
            run_id="fake-bad-proof",
            output_dir=output_dir,
            repeat_count=1,
            warmup_count_per_lane=0,
            lane_order=(A_LANE, B_LANE),
        ),
    )

    summary = experiment.run()

    records = _read_jsonl(output_dir / "records.jsonl")
    b_record = next(record for record in records if record["lane"] == B_LANE)
    assert not b_record["success"]
    assert b_record["error_code"] == "kv_consumer_forward_not_observed"
    assert b_record["release_status"] == "released"
    assert summary["by_case"]["case-1"]["lanes"][B_LANE]["success_count"] == 0
    assert len(client.release_calls) == 1
    assert not client.handles
