from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts.run_vllm_latent_negative_probe import run_probe
from v2.integrations.vllm_latent.client import VllmLatentClientError
from v2.integrations.vllm_latent.middleware import LATENT_MARKER


class _FakeNegativeClient:
    def __init__(self) -> None:
        self.refs: dict[str, dict[str, object]] = {}
        self.expired = False
        self.next_ref = 0

    def health(self) -> dict[str, object]:
        return {
            "status": "ready",
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
                "alignment_method": "soft_token_topk_v1",
            },
            "registry_entries": len(self.refs),
            "registry_bytes": len(self.refs) * 20_480,
            "errors": [],
        }

    def produce(self, payload: dict[str, object]) -> dict[str, object]:
        if payload["model"] != "qwen3-32b":
            raise VllmLatentClientError("latent_model_incompatible", status_code=409)
        if payload["expected_compatibility_digest"] != "compatibility-digest":
            raise VllmLatentClientError("latent_model_incompatible", status_code=409)
        if payload["alignment_method"] != "soft_token_topk_v1":
            raise VllmLatentClientError("latent_alignment_incompatible", status_code=409)
        self.next_ref += 1
        ref_id = f"latent-{self.next_ref}"
        self.refs[ref_id] = {
            "anchor": dict(payload["anchor"]),
            "ttl_s": int(payload["ttl_s"]),
        }
        return {
            "ref_id": ref_id,
            "status": "committed",
            "shape": [2, 5120],
            "dtype": "bfloat16",
            "tensor_bytes": 20_480,
            "tensor_digest": f"digest-{self.next_ref}",
            "captured_step_count": 2,
            "recurrence_injection_count": 1,
            "compatibility_digest": "compatibility-digest",
        }

    def complete(self, payload: dict[str, object]) -> dict[str, object]:
        if str(payload["rendered_prompt"]).count(LATENT_MARKER) != 1:
            raise VllmLatentClientError(
                "latent_position_contract_incompatible", status_code=409
            )
        ref_id = str(payload["latent_ref_id"])
        if ref_id not in self.refs:
            raise VllmLatentClientError("latent_ref_not_found", status_code=404)
        entry = self.refs[ref_id]
        if int(entry["ttl_s"]) == 1 and self.expired:
            self.refs.pop(ref_id)
            raise VllmLatentClientError("latent_ref_expired", status_code=410)
        if dict(payload["anchor"]) != entry["anchor"]:
            raise VllmLatentClientError("latent_anchor_mismatch", status_code=409)
        raise AssertionError("negative probe unexpectedly reached generation")

    def release(self, ref_id: str) -> dict[str, object]:
        if ref_id not in self.refs:
            raise VllmLatentClientError("latent_ref_expired", status_code=410)
        self.refs.pop(ref_id)
        return {"ref_id": ref_id, "status": "released"}


def test_negative_probe_covers_safe_http_matrix_and_leaves_registry_empty(
    tmp_path: Path,
) -> None:
    client = _FakeNegativeClient()
    args = SimpleNamespace(
        output_root=tmp_path / "negative",
        base_url="http://127.0.0.1:53334",
        token_file=None,
        model="qwen3-32b",
        timeout_s=30.0,
        ttl_wait_s=1.25,
        run_id="fake-negative",
    )

    result = run_probe(
        args,
        client=client,
        invalid_auth_probe=lambda _url, _timeout: {
            "status_code": 401,
            "error_code": "latent_auth_failed",
        },
        sleep_fn=lambda _seconds: setattr(client, "expired", True),
    )

    assert result["ok"] is True
    assert result["final_registry"] == {
        "registry_entries": 0,
        "registry_bytes": 0,
        "ok": True,
    }
    assert {
        case["name"]: case["observed_error_code"] for case in result["cases"]
    } == {
        "wrong_model": "latent_model_incompatible",
        "wrong_compatibility_digest": "latent_model_incompatible",
        "wrong_alignment_method": "latent_alignment_incompatible",
        "missing_marker": "latent_position_contract_incompatible",
        "duplicate_marker": "latent_position_contract_incompatible",
        "unknown_ref": "latent_ref_not_found",
        "invalid_bearer_token": "latent_auth_failed",
        "wrong_anchor": "latent_anchor_mismatch",
        "ttl_expired": "latent_ref_expired",
    }
    artifact = Path(result["artifact_path"]).read_text(encoding="utf-8")
    parsed = json.loads(artifact)
    assert parsed["ok"] is True
    assert "authorization" not in artifact.lower()
    assert "Bearer " not in artifact
    assert "rendered_prompt" not in artifact
    assert "messages" not in artifact
