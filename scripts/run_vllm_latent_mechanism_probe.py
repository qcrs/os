#!/usr/bin/env python3
"""Run a serial, evidence-bounded native latent mechanism probe.

The script intentionally owns no model state.  It only drives the authenticated
loopback API and records sanitized receipts, so a failed probe cannot be
mistaken for a successful hidden-state handoff.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.integrations.vllm_latent.client import (  # noqa: E402
    VllmLatentClient,
    VllmLatentClientError,
)
from v2.integrations.vllm_latent.alignment import (  # noqa: E402
    SUPPORTED_LATENT_ALIGNMENT_METHODS,
    sanitize_alignment_diagnostics,
)
from v2.integrations.vllm_latent.middleware import LATENT_MARKER  # noqa: E402
from v2.utils import sha256_digest, stable_json_dumps  # noqa: E402


DEFAULT_EVIDENCE_FILE = REPO_ROOT / (
    "v2/benchmark/samples/continuous_task_families/cross_period_financial/"
    "cross_period_financial_report.md"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run serial authenticated Qwen3 native latent producer/consumer probes."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="fresh directory for sanitized machine-readable artifacts",
    )
    parser.add_argument(
        "--steps",
        type=int,
        action="append",
        default=None,
        help="latent step count; repeat for later serial probes (default: 2)",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:53334")
    parser.add_argument(
        "--token-file",
        type=Path,
        default=None,
        help="0600 token path; value is never printed or stored",
    )
    parser.add_argument("--model", default="qwen3-32b")
    parser.add_argument("--evidence-file", type=Path, default=DEFAULT_EVIDENCE_FILE)
    parser.add_argument("--ttl-s", type=int, default=300)
    parser.add_argument("--timeout-s", type=float, default=240.0)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--run-id", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_probe(args)
    print(result["artifact_path"])
    return 0 if bool(result.get("ok")) else 1


def run_probe(args: argparse.Namespace, *, client: Any | None = None) -> dict[str, Any]:
    steps = tuple(args.steps or (2,))
    run_id = str(args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    evidence_path = Path(args.evidence_file).resolve()
    evidence_text = evidence_path.read_text(encoding="utf-8")
    evidence_digest = sha256_digest(evidence_text)
    owns_client = client is None
    payload: dict[str, Any] = {
        "schema_version": "statebus.v2.native_latent_mechanism_probe.v1",
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": str(args.base_url),
        "model_requested": str(args.model),
        "evidence_file": str(evidence_path),
        "evidence_sha256": evidence_digest,
        "evidence_bytes": len(evidence_text.encode("utf-8")),
        "steps_requested": list(steps),
        "claim_boundary": (
            "real worker hidden capture, aligned recurrence, engine-local opaque ref, "
            "and consumer worker-forward proof only; no KV/layer-wise transfer or speed claim"
        ),
        "health": {},
        "steps": [],
        "ok": False,
    }
    if any(step < 2 or step > 32 for step in steps):
        payload["config_error"] = "latent_steps_out_of_range"
        return _write_result(payload, output_root, run_id)
    if int(args.ttl_s) <= 0:
        payload["config_error"] = "ttl_s_out_of_range"
        return _write_result(payload, output_root, run_id)
    if client is None:
        client = VllmLatentClient(
            base_url=str(args.base_url),
            token_file=args.token_file,
            timeout_s=float(args.timeout_s),
        )
    try:
        try:
            health = client.health()
            payload["health"] = _sanitize_health(health)
        except Exception as exc:  # noqa: BLE001 - probe records stable failure class.
            payload["health_error"] = _safe_error(exc)
            return _write_result(payload, output_root, run_id)

        health_validation = _validate_health(health, expected_model=str(args.model))
        payload["health_validation"] = health_validation
        if not health_validation["ok"]:
            payload["health_error"] = "latent_plugin_not_ready"
            return _write_result(payload, output_root, run_id)
        signature = health.get("compatibility_signature", {})
        alignment_method = str(signature.get("alignment_method", ""))
        if alignment_method not in SUPPORTED_LATENT_ALIGNMENT_METHODS:
            payload["health_error"] = "latent_alignment_incompatible"
            return _write_result(payload, output_root, run_id)
        hidden_size = int(health.get("hidden_size", signature.get("hidden_size", 0)))
        if hidden_size <= 0:
            payload["health_error"] = "hidden_size_missing"
            return _write_result(payload, output_root, run_id)

        for step_index, latent_steps in enumerate(steps, start=1):
            record = _run_step(
                client=client,
                model=str(health.get("model", args.model)),
                compatibility_digest=str(health["compatibility_digest"]),
                alignment_method=alignment_method,
                hidden_size=hidden_size,
                latent_steps=int(latent_steps),
                ttl_s=int(args.ttl_s),
                max_tokens=int(args.max_tokens),
                evidence_text=evidence_text,
                evidence_digest=evidence_digest,
                run_id=run_id,
                step_index=step_index,
            )
            payload["steps"].append(record)
            if not bool(record.get("ok")):
                # The frozen execution order is serial and fail-closed.  Do not
                # spend more requests after a failed mechanism gate.
                break
        payload["ok"] = bool(payload["steps"]) and len(payload["steps"]) == len(steps) and all(
            bool(item.get("ok")) for item in payload["steps"]
        )
        return _write_result(payload, output_root, run_id)
    finally:
        if owns_client:
            client.close()


def _run_step(
    *,
    client: Any,
    model: str,
    compatibility_digest: str,
    alignment_method: str,
    hidden_size: int,
    latent_steps: int,
    ttl_s: int,
    max_tokens: int,
    evidence_text: str,
    evidence_digest: str,
    run_id: str,
    step_index: int,
) -> dict[str, Any]:
    request_id = f"{run_id}-producer-{latent_steps}-{step_index}"
    task_id = f"{run_id}-task-{latent_steps}-{step_index}"
    item_ids = ["cross-period-financial-report", "acme-revenue-2026q1"]
    locator_digest = sha256_digest({"evidence": evidence_digest, "items": item_ids})
    anchor = {
        "evidence_pack_hash": evidence_digest,
        "item_ids": item_ids,
        "locator_digest": locator_digest,
    }
    # Keep prompt material out of artifacts while still binding it to the source
    # corpus used by the producer and consumer.
    messages = (
        {
            "role": "system",
            "content": "You are a retrieval worker. Return concise evidence-grounded notes.",
        },
        {
            "role": "user",
            "content": (
                "Use the supplied cross-period financial report to identify the requested "
                "revenue facts for the summarizer.\n\n" + evidence_text
            ),
        },
    )
    record: dict[str, Any] = {
        "latent_steps": latent_steps,
        "alignment_method": alignment_method,
        "request_id": request_id,
        "task_id": task_id,
        "source_step_id": "retrieve",
        "anchor": anchor,
        "messages_sha256": sha256_digest(messages),
        "messages_bytes": sum(len(str(item["content"]).encode("utf-8")) for item in messages),
        "producer": {},
        "consumer": {},
        "one_shot": {},
        "release": {},
        "ok": False,
    }
    ref_id = ""
    try:
        produced = client.produce(
            {
                "model": model,
                "request_id": request_id,
                "task_id": task_id,
                "source_step_id": "retrieve",
                "producer_role": "retriever",
                "consumer_role": "summarizer",
                "messages": list(messages),
                "latent_steps": latent_steps,
                "alignment_method": alignment_method,
                "anchor": anchor,
                "ttl_s": ttl_s,
                "expected_compatibility_digest": compatibility_digest,
            }
        )
        ref_id = str(produced.get("ref_id", ""))
        record["producer"] = _sanitize_producer(produced)
        producer_ok = _validate_producer(
            produced,
            latent_steps,
            hidden_size,
            compatibility_digest,
        )
        record["producer"]["validation"] = producer_ok
        if not producer_ok["ok"] or not ref_id:
            record["failure"] = "latent_capture_incomplete"
            return record

        complete_request_id = f"{run_id}-consumer-{latent_steps}-{step_index}"
        rendered_prompt = (
            "Use the anchored financial evidence to return exactly one compact "
            "ClaimSet fact with one short claim sentence. "
            + LATENT_MARKER
            + " Return status ready and do not add prose outside JSON."
        )
        completion_payload = {
            "model": model,
            "request_id": complete_request_id,
            "latent_ref_id": ref_id,
            "rendered_prompt": rendered_prompt,
            "response_schema": _claimset_schema(item_ids, locator_digest),
            "sampling": {"temperature": 0.0, "max_tokens": max_tokens, "seed": 7},
            "expected_compatibility_digest": compatibility_digest,
            "anchor": anchor,
        }
        record["rendered_prompt_sha256"] = sha256_digest(rendered_prompt)
        record["response_schema_sha256"] = sha256_digest(
            completion_payload["response_schema"]
        )
        completed = client.complete(completion_payload)
        record["consumer"] = _sanitize_consumer(completed)
        consumer_ok = _validate_consumer(
            completed,
            ref_id=ref_id,
            request_id=complete_request_id,
            hidden_size=hidden_size,
        )
        record["consumer"]["validation"] = consumer_ok
        if not consumer_ok["ok"]:
            record["failure"] = (
                "latent_output_validation_failed"
                if consumer_ok["forward_proof_ok"]
                else "latent_consumer_forward_not_observed"
            )
            return record

        try:
            client.complete({**completion_payload, "request_id": complete_request_id + "-second"})
        except VllmLatentClientError as exc:
            record["one_shot"] = {
                "error_code": exc.error_code,
                "status_code": exc.status_code,
                "expected_error_code": "latent_ref_already_consumed",
                "ok": exc.error_code == "latent_ref_already_consumed",
            }
        except Exception as exc:  # noqa: BLE001
            record["one_shot"] = {"error_code": type(exc).__name__, "ok": False}
        else:
            record["one_shot"] = {
                "error_code": "",
                "expected_error_code": "latent_ref_already_consumed",
                "ok": False,
            }

        released = client.release(ref_id)
        record["release"] = {
            "ref_id": str(released.get("ref_id", "")),
            "status": str(released.get("status", "")),
            "ok": str(released.get("ref_id", "")) == ref_id
            and str(released.get("status", "")) == "released",
        }
        record["ok"] = bool(
            consumer_ok["ok"] and record["one_shot"].get("ok") and record["release"].get("ok")
        )
        return record
    except VllmLatentClientError as exc:
        record["failure"] = exc.error_code
        record["failure_status_code"] = exc.status_code
        return record
    except Exception as exc:  # noqa: BLE001 - stable probe evidence only.
        record["failure"] = type(exc).__name__
        return record
    finally:
        if ref_id and not record.get("release", {}).get("ok"):
            try:
                cleanup = client.release(ref_id)
                record["cleanup_release"] = {
                    "attempted": True,
                    "status": str(cleanup.get("status", "")),
                    "ok": str(cleanup.get("status", "")) == "released",
                }
            except Exception as exc:  # noqa: BLE001 - cleanup stays fail-closed.
                record["cleanup_release"] = {
                    "attempted": True,
                    "error_code": _safe_error(exc),
                    "ok": False,
                }


def _validate_health(
    health: Mapping[str, Any], *, expected_model: str
) -> dict[str, Any]:
    signature = health.get("compatibility_signature", {})
    if not isinstance(signature, Mapping):
        signature = {}
    checks = {
        "status_ready": str(health.get("status", "")) == "ready",
        "vllm_0_9_2": str(health.get("vllm_version", "")) == "0.9.2",
        "engine_v0": str(health.get("engine_generation", "")) == "V0",
        "model": str(health.get("model", "")) == expected_model,
        "architecture": str(signature.get("architecture", ""))
        == "Qwen3ForCausalLM",
        "hidden_size": int(health.get("hidden_size", 0)) == 5120,
        "dtype_bfloat16": str(signature.get("dtype", ""))
        in {"bfloat16", "torch.bfloat16"},
        "tp_one": int(signature.get("tensor_parallel_size", 0)) == 1,
        "pp_one": int(signature.get("pipeline_parallel_size", 0)) == 1,
        "worker_extension_ready": bool(health.get("worker_extension_ready")),
        "prompt_embeds_enabled": bool(health.get("prompt_embeds_enabled")),
        "max_num_seqs_one": int(health.get("max_num_seqs", 0)) == 1,
        "compatibility_digest": bool(health.get("compatibility_digest")),
        "alignment_method": str(signature.get("alignment_method", ""))
        in SUPPORTED_LATENT_ALIGNMENT_METHODS,
        "no_errors": not health.get("errors"),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _validate_producer(
    body: Mapping[str, Any],
    steps: int,
    hidden_size: int,
    compatibility_digest: str,
) -> dict[str, Any]:
    shape = tuple(int(value) for value in body.get("shape", ()))
    expected = (steps, hidden_size)
    checks = {
        "status_committed": body.get("status") == "committed",
        "shape": shape == expected,
        "dtype_bfloat16": body.get("dtype") == "bfloat16",
        "captured_steps": int(body.get("captured_step_count", 0)) == steps,
        "recurrence": int(body.get("recurrence_injection_count", -1)) == steps - 1,
        "tensor_bytes": int(body.get("tensor_bytes", 0)) == steps * hidden_size * 2,
        "tensor_digest": bool(body.get("tensor_digest")),
        "compatibility_digest": body.get("compatibility_digest")
        == compatibility_digest,
        "opaque_response": not any(
            key in body for key in ("tensor", "tensor_base64", "prompt_embeds", "internal_text")
        ),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _validate_consumer(
    body: Mapping[str, Any], *, ref_id: str, request_id: str, hidden_size: int
) -> dict[str, Any]:
    proof = body.get("forward_proof")
    shape = tuple(int(value) for value in body.get("prompt_embed_shape", ()))
    proof_shape = (
        tuple(int(value) for value in proof.get("inputs_embeds_shape", ()))
        if isinstance(proof, Mapping)
        else ()
    )
    telemetry = body.get("telemetry", {})
    if not isinstance(telemetry, Mapping):
        telemetry = {}
    text = str(body.get("text", ""))
    claimset = _validate_claimset(text)
    forward_checks = {
        "ref_id": body.get("consumed_ref_id") == ref_id,
        "forward_observed": body.get("consumer_forward_observed") is True,
        "proof_kind": isinstance(proof, Mapping) and proof.get("proof_kind") == "worker_forward",
        "proof_ref_id": isinstance(proof, Mapping) and proof.get("ref_id") == ref_id,
        "proof_request_id": isinstance(proof, Mapping) and proof.get("request_id") == request_id,
        "prompt_hidden_size": len(shape) == 2 and shape[-1] == hidden_size,
        "proof_hidden_size": len(proof_shape) == 2 and proof_shape[-1] == hidden_size,
        "proof_shape_matches_prompt": proof_shape == shape,
        "proof_dtype": isinstance(proof, Mapping) and proof.get("inputs_embeds_dtype") == "bfloat16",
        "proof_digest": isinstance(proof, Mapping) and bool(proof.get("inputs_embeds_digest")),
        "proof_shape_matches_telemetry": proof_shape
        == tuple(
            int(value)
            for value in telemetry.get("consumer_forward_inputs_embeds_shape", ())
        ),
        "proof_dtype_matches_telemetry": isinstance(proof, Mapping)
        and proof.get("inputs_embeds_dtype")
        == telemetry.get("consumer_forward_inputs_embeds_dtype"),
        "proof_digest_matches_telemetry": isinstance(proof, Mapping)
        and proof.get("inputs_embeds_digest")
        == telemetry.get("consumer_forward_inputs_embeds_digest"),
    }
    output_checks = {"claimset_json": claimset["ok"]}
    checks = {**forward_checks, **output_checks}
    forward_proof_ok = all(forward_checks.values())
    output_validation_ok = all(output_checks.values())
    return {
        "ok": forward_proof_ok and output_validation_ok,
        "forward_proof_ok": forward_proof_ok,
        "output_validation_ok": output_validation_ok,
        "checks": checks,
        "claimset": claimset,
    }


def _validate_claimset(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return {"ok": False, "error": "invalid_json", "text_sha256": sha256_digest(text)}
    if not isinstance(value, dict) or value.get("status") != "ready" or not isinstance(value.get("claims"), list):
        return {"ok": False, "error": "claimset_shape", "text_sha256": sha256_digest(text)}
    required = {
        "claim_id",
        "claim_text",
        "claim_type",
        "supporting_evidence_item_ids",
        "supporting_artifact_ref_ids",
        "citation_locators",
        "numeric_fields",
        "uncertainty_note",
        "status",
    }
    claim_ok = bool(value["claims"]) and all(
        isinstance(item, dict) and required.issubset(item) for item in value["claims"]
    )
    return {
        "ok": claim_ok,
        "error": "" if claim_ok else "claim_fields_missing",
        "claim_count": len(value["claims"]),
        "text_sha256": sha256_digest(text),
        "text_bytes": len(text.encode("utf-8")),
    }


def _claimset_schema(item_ids: Sequence[str], locator_digest: str) -> dict[str, Any]:
    claim = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claim_id": {"type": "string"},
            "claim_text": {"type": "string"},
            "claim_type": {"type": "string", "enum": ["fact", "inference", "risk"]},
            "supporting_evidence_item_ids": {
                "type": "array",
                "items": {"type": "string", "enum": list(item_ids)},
                "minItems": 1,
                "maxItems": 2,
            },
            "supporting_artifact_ref_ids": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 0,
            },
            "citation_locators": {
                "type": "array",
                "items": {"type": "string", "enum": [locator_digest]},
                "maxItems": 1,
            },
            "numeric_fields": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"revenue_musd": {"type": "number"}},
            },
            "uncertainty_note": {"type": "string"},
            "status": {"type": "string", "const": "ready"},
        },
        "required": [
            "claim_id",
            "claim_text",
            "claim_type",
            "supporting_evidence_item_ids",
            "supporting_artifact_ref_ids",
            "citation_locators",
            "numeric_fields",
            "uncertainty_note",
            "status",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claims": {
                "type": "array",
                "items": claim,
                "minItems": 1,
                "maxItems": 1,
            },
            "status": {"type": "string", "const": "ready"},
            "schema_version": {
                "type": "string",
                "const": "statebus.claim_set.v1",
            },
        },
        "required": ["claims", "status", "schema_version"],
    }


def _sanitize_health(body: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: body.get(key)
        for key in (
            "status",
            "plugin_version",
            "vllm_version",
            "engine_generation",
            "model",
            "hidden_size",
            "prompt_embeds_enabled",
            "worker_extension_ready",
            "max_num_seqs",
            "compatibility_digest",
            "compatibility_signature",
            "registry_entries",
            "registry_bytes",
            "errors",
        )
        if key in body
    }


def _sanitize_producer(body: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "ref_id",
        "status",
        "shape",
        "dtype",
        "tensor_bytes",
        "tensor_digest",
        "captured_step_count",
        "recurrence_injection_count",
        "internal_scheduler_sample_count",
        "producer_pid",
        "engine_id",
        "compatibility_digest",
        "alignment_diagnostics",
        "telemetry",
        "telemetry_hash",
    )
    result = {key: body.get(key) for key in allowed if key in body}
    if "alignment_diagnostics" in result:
        result["alignment_diagnostics"] = sanitize_alignment_diagnostics(
            result["alignment_diagnostics"]
        )
    return result


def _sanitize_consumer(body: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "consumed_ref_id",
        "consumer_forward_observed",
        "consumer_forward_event_id",
        "forward_proof",
        "prompt_embed_shape",
        "usage",
        "telemetry",
        "telemetry_hash",
        "text",
    )
    return {key: body.get(key) for key in allowed if key in body}


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, VllmLatentClientError):
        return exc.error_code
    return type(exc).__name__


def _write_result(payload: dict[str, Any], output_root: Path, run_id: str) -> dict[str, Any]:
    path = output_root / f"mechanism_probe_{run_id}.json"
    payload["artifact_path"] = str(path)
    path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
