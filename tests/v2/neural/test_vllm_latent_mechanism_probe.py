from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts.run_vllm_latent_mechanism_probe import (
    _claimset_schema,
    _parser,
    run_probe,
)
from v2.integrations.vllm_latent.client import VllmLatentClientError


class _FakeClient:
    def __init__(
        self,
        *,
        bad_consumer_digest: bool = False,
        invalid_claimset: bool = False,
        ready: bool = True,
    ) -> None:
        self.bad_consumer_digest = bad_consumer_digest
        self.invalid_claimset = invalid_claimset
        self.ready = ready
        self.calls: list[tuple[str, object]] = []
        self.consumed: set[str] = set()

    def health(self) -> dict[str, object]:
        self.calls.append(("health", None))
        return {
            "status": "ready" if self.ready else "not_ready",
            "plugin_version": "statebus.vllm_latent.v1",
            "vllm_version": "0.9.2",
            "engine_generation": "V0",
            "model": "qwen3-32b",
            "hidden_size": 5120,
            "prompt_embeds_enabled": True,
            "worker_extension_ready": True,
            "max_num_seqs": 1,
            "compatibility_digest": "compatibility-digest",
            "compatibility_signature": {
                "architecture": "Qwen3ForCausalLM",
                "hidden_size": 5120,
                "dtype": "torch.bfloat16",
                "tensor_parallel_size": 1,
                "pipeline_parallel_size": 1,
            },
            "registry_entries": 0,
            "registry_bytes": 0,
            "errors": [],
        }

    def produce(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("produce", payload))
        steps = int(payload["latent_steps"])
        ref_id = f"latent-{steps}"
        return {
            "ref_id": ref_id,
            "status": "committed",
            "shape": [steps, 5120],
            "dtype": "bfloat16",
            "tensor_bytes": steps * 5120 * 2,
            "tensor_digest": f"tensor-digest-{steps}",
            "captured_step_count": steps,
            "recurrence_injection_count": steps - 1,
            "internal_scheduler_sample_count": steps,
            "producer_pid": 42,
            "engine_id": "vllm-v0",
            "compatibility_digest": "compatibility-digest",
            "telemetry": {"latent_steps_requested": steps},
        }

    def complete(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("complete", payload))
        ref_id = str(payload["latent_ref_id"])
        if ref_id in self.consumed:
            raise VllmLatentClientError(
                "latent_ref_already_consumed", status_code=409
            )
        self.consumed.add(ref_id)
        request_id = str(payload["request_id"])
        digest = "prompt-digest"
        telemetry_digest = "wrong-digest" if self.bad_consumer_digest else digest
        claim_set = {
            "claims": [
                {
                    "claim_id": "revenue",
                    "claim_text": "ACME revenue was 120 million USD in 2026Q1.",
                    "claim_type": "fact",
                    "supporting_evidence_item_ids": ["acme-revenue-2026q1"],
                    "supporting_artifact_ref_ids": [],
                    "citation_locators": [],
                    "numeric_fields": {"revenue_musd": 120},
                    "uncertainty_note": "",
                    "status": "ready",
                }
            ],
            "status": "ready",
            "schema_version": "statebus.claim_set.v1",
        }
        proof = {
            "ref_id": ref_id,
            "request_id": request_id,
            "worker_pid": 42,
            "engine_id": "vllm-v0",
            "inputs_embeds_shape": [17, 5120],
            "inputs_embeds_dtype": "bfloat16",
            "inputs_embeds_digest": digest,
            "event_id": "forward-event",
            "proof_kind": "worker_forward",
        }
        return {
            "text": '{"claims": [' if self.invalid_claimset else json.dumps(claim_set),
            "consumed_ref_id": ref_id,
            "consumer_forward_observed": True,
            "consumer_forward_event_id": "forward-event",
            "forward_proof": proof,
            "prompt_embed_shape": [17, 5120],
            "usage": {"prompt_tokens_equivalent": 17, "completion_tokens": 20},
            "telemetry": {
                "consumer_forward_inputs_embeds_shape": [17, 5120],
                "consumer_forward_inputs_embeds_dtype": "bfloat16",
                "consumer_forward_inputs_embeds_digest": telemetry_digest,
            },
        }

    def release(self, ref_id: str) -> dict[str, object]:
        self.calls.append(("release", ref_id))
        return {"ref_id": ref_id, "status": "released"}


def _args(tmp_path: Path, *, steps: list[int]) -> SimpleNamespace:
    evidence = tmp_path / "evidence.md"
    evidence.write_text("| quarter | ticker | revenue_musd |\n| 2026Q1 | ACME | 120 |\n")
    return SimpleNamespace(
        output_root=tmp_path / "run",
        steps=steps,
        base_url="http://127.0.0.1:53334",
        token_file=None,
        model="qwen3-32b",
        evidence_file=evidence,
        ttl_s=300,
        timeout_s=30.0,
        max_tokens=128,
        run_id="fake-run",
    )


def test_serial_probe_validates_producer_consumer_one_shot_and_release(
    tmp_path: Path,
) -> None:
    client = _FakeClient()
    result = run_probe(_args(tmp_path, steps=[2, 4]), client=client)

    assert result["ok"] is True
    assert [item["latent_steps"] for item in result["steps"]] == [2, 4]
    assert all(item["producer"]["validation"]["ok"] for item in result["steps"])
    assert all(item["consumer"]["validation"]["ok"] for item in result["steps"])
    assert all(item["one_shot"]["ok"] for item in result["steps"])
    assert all(item["release"]["ok"] for item in result["steps"])
    assert [method for method, _ in client.calls] == [
        "health",
        "produce",
        "complete",
        "complete",
        "release",
        "produce",
        "complete",
        "complete",
        "release",
    ]
    artifact = Path(result["artifact_path"]).read_text(encoding="utf-8")
    assert "messages\"" not in artifact
    assert "rendered_prompt\"" not in artifact
    assert "prompt_embeds\": [" not in artifact
    assert "Bearer " not in artifact


def test_serial_probe_fails_closed_and_stops_after_bad_forward_receipt(
    tmp_path: Path,
) -> None:
    client = _FakeClient(bad_consumer_digest=True)
    result = run_probe(_args(tmp_path, steps=[2, 4]), client=client)

    assert result["ok"] is False
    assert len(result["steps"]) == 1
    step = result["steps"][0]
    assert step["failure"] == "latent_consumer_forward_not_observed"
    assert step["consumer"]["validation"]["checks"][
        "proof_digest_matches_telemetry"
    ] is False
    assert step["cleanup_release"]["ok"] is True
    assert [method for method, _ in client.calls].count("produce") == 1


def test_serial_probe_classifies_invalid_claimset_after_valid_forward_proof(
    tmp_path: Path,
) -> None:
    client = _FakeClient(invalid_claimset=True)
    result = run_probe(_args(tmp_path, steps=[2, 4]), client=client)

    assert result["ok"] is False
    assert len(result["steps"]) == 1
    step = result["steps"][0]
    assert step["failure"] == "latent_output_validation_failed"
    validation = step["consumer"]["validation"]
    assert validation["forward_proof_ok"] is True
    assert validation["output_validation_ok"] is False
    assert validation["checks"]["claimset_json"] is False
    assert step["cleanup_release"]["ok"] is True


def test_parser_defaults_to_sufficient_claimset_completion_budget(tmp_path: Path) -> None:
    args = _parser().parse_args(["--output-root", str(tmp_path)])

    assert args.max_tokens == 512


def test_claimset_schema_bounds_mechanism_probe_output() -> None:
    schema = _claimset_schema(["report", "revenue"], "locator-digest")
    claims = schema["properties"]["claims"]
    claim = claims["items"]

    assert claims["minItems"] == 1
    assert claims["maxItems"] == 1
    assert claim["properties"]["claim_type"]["enum"] == [
        "fact",
        "inference",
        "risk",
    ]
    assert claim["properties"]["supporting_artifact_ref_ids"]["maxItems"] == 0
    assert claim["properties"]["numeric_fields"]["additionalProperties"] is False
    assert claim["properties"]["status"]["const"] == "ready"
    assert schema["properties"]["status"]["const"] == "ready"
    assert schema["properties"]["schema_version"]["const"] == "statebus.claim_set.v1"


def test_serial_probe_rejects_unsupported_health_before_produce(tmp_path: Path) -> None:
    client = _FakeClient(ready=False)
    result = run_probe(_args(tmp_path, steps=[2]), client=client)

    assert result["ok"] is False
    assert result["health_error"] == "latent_plugin_not_ready"
    assert result["steps"] == []
    assert [method for method, _ in client.calls] == ["health"]
