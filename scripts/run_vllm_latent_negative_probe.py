#!/usr/bin/env python3
"""Run the non-destructive native latent HTTP negative matrix.

The probe records only stable error codes and sanitized receipts. It never
stores the bearer token, request messages, rendered prompts, or tensor data.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
from typing import Any, Callable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_vllm_latent_mechanism_probe import (  # noqa: E402
    _sanitize_health,
    _sanitize_producer,
    _validate_health,
)
from v2.integrations.vllm_latent.client import (  # noqa: E402
    VllmLatentClient,
    VllmLatentClientError,
)
from v2.integrations.vllm_latent.middleware import LATENT_MARKER  # noqa: E402
from v2.utils import stable_json_dumps  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run safe authenticated vLLM latent negative probes serially."
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:53334")
    parser.add_argument("--token-file", type=Path, default=None)
    parser.add_argument("--model", default="qwen3-32b")
    parser.add_argument("--timeout-s", type=float, default=240.0)
    parser.add_argument("--ttl-wait-s", type=float, default=1.25)
    parser.add_argument("--run-id", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_probe(args)
    print(result["artifact_path"])
    return 0 if bool(result.get("ok")) else 1


def run_probe(
    args: argparse.Namespace,
    *,
    client: Any | None = None,
    invalid_auth_probe: Callable[[str, float], Mapping[str, Any]] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    run_id = str(args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": "statebus.v2.native_latent_negative_probe.v1",
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": str(args.base_url),
        "model_requested": str(args.model),
        "scope": (
            "safe HTTP negatives only; injected tests own incomplete capture, capacity, "
            "concurrent capture, forward binding, mode-off, loopback, and fallback"
        ),
        "health": {},
        "cases": [],
        "final_registry": {},
        "ok": False,
    }
    owns_client = client is None
    if client is None:
        client = VllmLatentClient(
            base_url=str(args.base_url),
            token_file=args.token_file,
            timeout_s=float(args.timeout_s),
        )
    try:
        try:
            health = client.health()
        except Exception as exc:  # noqa: BLE001
            payload["health_error"] = _safe_error(exc)
            return _write_result(payload, output_root, run_id)
        payload["health"] = _sanitize_health(health)
        health_validation = _validate_health(health, expected_model=str(args.model))
        payload["health_validation"] = health_validation
        if not health_validation["ok"]:
            payload["health_error"] = "latent_plugin_not_ready"
            return _write_result(payload, output_root, run_id)

        model = str(health["model"])
        compatibility_digest = str(health["compatibility_digest"])
        signature = health.get("compatibility_signature", {})
        alignment_method = (
            str(signature.get("alignment_method", "soft_token_topk_v1"))
            if isinstance(signature, Mapping)
            else "soft_token_topk_v1"
        )
        anchor = {
            "evidence_pack_hash": "sha256:negative-probe-evidence",
            "item_ids": ["negative-probe-item"],
            "locator_digest": "sha256:negative-probe-locator",
        }

        payload["cases"].extend(
            (
                _expect_error(
                    "wrong_model",
                    "latent_model_incompatible",
                    lambda: client.produce(
                        _produce_payload(
                            run_id,
                            model="statebus-wrong-model",
                            compatibility_digest=compatibility_digest,
                            alignment_method=alignment_method,
                            anchor=anchor,
                        )
                    ),
                    "health_gate_before_capture",
                ),
                _expect_error(
                    "wrong_compatibility_digest",
                    "latent_model_incompatible",
                    lambda: client.produce(
                        _produce_payload(
                            run_id,
                            model=model,
                            compatibility_digest="sha256:wrong-compatibility",
                            alignment_method=alignment_method,
                            anchor=anchor,
                        )
                    ),
                    "health_gate_before_capture",
                ),
                _expect_error(
                    "wrong_alignment_method",
                    "latent_alignment_incompatible",
                    lambda: client.produce(
                        _produce_payload(
                            run_id,
                            model=model,
                            compatibility_digest=compatibility_digest,
                            alignment_method="identity_norm_v1",
                            anchor=anchor,
                        )
                    ),
                    "alignment_gate_before_capture",
                ),
                _expect_error(
                    "missing_marker",
                    "latent_position_contract_incompatible",
                    lambda: client.complete(
                        _complete_payload(
                            run_id,
                            model=model,
                            compatibility_digest=compatibility_digest,
                            anchor=anchor,
                            ref_id="latent-unknown-negative-probe",
                            rendered_prompt="no latent marker in this bounded prompt",
                        )
                    ),
                    "position_gate_before_registry_lookup",
                ),
                _expect_error(
                    "duplicate_marker",
                    "latent_position_contract_incompatible",
                    lambda: client.complete(
                        _complete_payload(
                            run_id,
                            model=model,
                            compatibility_digest=compatibility_digest,
                            anchor=anchor,
                            ref_id="latent-unknown-negative-probe",
                            rendered_prompt=LATENT_MARKER + LATENT_MARKER,
                        )
                    ),
                    "position_gate_before_registry_lookup",
                ),
                _expect_error(
                    "unknown_ref",
                    "latent_ref_not_found",
                    lambda: client.complete(
                        _complete_payload(
                            run_id,
                            model=model,
                            compatibility_digest=compatibility_digest,
                            anchor=anchor,
                            ref_id="latent-unknown-negative-probe",
                        )
                    ),
                    "registry_lookup_before_materialize",
                ),
            )
        )

        auth_probe = invalid_auth_probe or _probe_invalid_auth
        auth_result = dict(auth_probe(str(args.base_url), float(args.timeout_s)))
        payload["cases"].append({
            "name": "invalid_bearer_token",
            "expected_error_code": "latent_auth_failed",
            "observed_error_code": str(auth_result.get("error_code", "")),
            "status_code": int(auth_result.get("status_code", 0)),
            "rejection_stage": "middleware_auth_before_engine_access",
            "ok": str(auth_result.get("error_code", "")) == "latent_auth_failed"
            and int(auth_result.get("status_code", 0)) == 401,
        })

        payload["cases"].append(
            _wrong_anchor_case(
                client,
                run_id=run_id,
                model=model,
                compatibility_digest=compatibility_digest,
                alignment_method=alignment_method,
                anchor=anchor,
            )
        )
        payload["cases"].append(
            _expired_ref_case(
                client,
                run_id=run_id,
                model=model,
                compatibility_digest=compatibility_digest,
                alignment_method=alignment_method,
                anchor=anchor,
                wait_s=float(args.ttl_wait_s),
                sleep_fn=sleep_fn,
            )
        )

        try:
            final_health = client.health()
            payload["final_registry"] = {
                "registry_entries": int(final_health.get("registry_entries", -1)),
                "registry_bytes": int(final_health.get("registry_bytes", -1)),
            }
        except Exception as exc:  # noqa: BLE001
            payload["final_registry"] = {"error_code": _safe_error(exc)}
        payload["final_registry"]["ok"] = (
            payload["final_registry"].get("registry_entries") == 0
            and payload["final_registry"].get("registry_bytes") == 0
        )
        payload["ok"] = bool(payload["cases"]) and all(
            bool(case.get("ok")) for case in payload["cases"]
        ) and bool(payload["final_registry"].get("ok"))
        return _write_result(payload, output_root, run_id)
    finally:
        if owns_client:
            client.close()


def _produce_payload(
    run_id: str,
    *,
    model: str,
    compatibility_digest: str,
    alignment_method: str,
    anchor: Mapping[str, Any],
    suffix: str = "base",
    ttl_s: int = 60,
) -> dict[str, Any]:
    return {
        "model": model,
        "request_id": f"{run_id}-producer-{suffix}",
        "task_id": f"{run_id}-task-{suffix}",
        "source_step_id": "retrieve",
        "producer_role": "retriever",
        "consumer_role": "summarizer",
        "messages": [
            {
                "role": "user",
                "content": "Assimilate this bounded negative-probe evidence for validation.",
            }
        ],
        "latent_steps": 2,
        "alignment_method": alignment_method,
        "anchor": dict(anchor),
        "ttl_s": ttl_s,
        "expected_compatibility_digest": compatibility_digest,
    }


def _complete_payload(
    run_id: str,
    *,
    model: str,
    compatibility_digest: str,
    anchor: Mapping[str, Any],
    ref_id: str,
    suffix: str = "base",
    rendered_prompt: str | None = None,
) -> dict[str, Any]:
    return {
        "model": model,
        "request_id": f"{run_id}-consumer-{suffix}",
        "latent_ref_id": ref_id,
        "rendered_prompt": rendered_prompt or f"anchors {LATENT_MARKER} output",
        "response_schema": {},
        "sampling": {"temperature": 0.0, "max_tokens": 1, "seed": 7},
        "expected_compatibility_digest": compatibility_digest,
        "anchor": dict(anchor),
    }


def _wrong_anchor_case(
    client: Any,
    *,
    run_id: str,
    model: str,
    compatibility_digest: str,
    alignment_method: str,
    anchor: Mapping[str, Any],
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "name": "wrong_anchor",
        "expected_error_code": "latent_anchor_mismatch",
        "rejection_stage": "registry_lease_before_materialize",
        "ok": False,
    }
    ref_id = ""
    try:
        produced = client.produce(
            _produce_payload(
                run_id,
                model=model,
                compatibility_digest=compatibility_digest,
                alignment_method=alignment_method,
                anchor=anchor,
                suffix="wrong-anchor",
            )
        )
        ref_id = str(produced.get("ref_id", ""))
        record["producer"] = _sanitize_producer(produced)
        wrong_anchor = {**dict(anchor), "evidence_pack_hash": "sha256:wrong-anchor"}
        rejection = _expect_error(
            "wrong_anchor",
            "latent_anchor_mismatch",
            lambda: client.complete(
                _complete_payload(
                    run_id,
                    model=model,
                    compatibility_digest=compatibility_digest,
                    anchor=wrong_anchor,
                    ref_id=ref_id,
                    suffix="wrong-anchor",
                )
            ),
            "registry_lease_before_materialize",
        )
        record.update(rejection)
    except Exception as exc:  # noqa: BLE001
        record["observed_error_code"] = _safe_error(exc)
    finally:
        record["cleanup"] = _safe_release(client, ref_id)
    record["ok"] = bool(record.get("ok")) and bool(record["cleanup"].get("ok"))
    return record


def _expired_ref_case(
    client: Any,
    *,
    run_id: str,
    model: str,
    compatibility_digest: str,
    alignment_method: str,
    anchor: Mapping[str, Any],
    wait_s: float,
    sleep_fn: Callable[[float], None],
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "name": "ttl_expired",
        "expected_error_code": "latent_ref_expired",
        "rejection_stage": "registry_ttl_before_materialize",
        "ttl_s": 1,
        "wait_s": wait_s,
        "ok": False,
    }
    ref_id = ""
    try:
        produced = client.produce(
            _produce_payload(
                run_id,
                model=model,
                compatibility_digest=compatibility_digest,
                alignment_method=alignment_method,
                anchor=anchor,
                suffix="ttl",
                ttl_s=1,
            )
        )
        ref_id = str(produced.get("ref_id", ""))
        record["producer"] = _sanitize_producer(produced)
        sleep_fn(wait_s)
        rejection = _expect_error(
            "ttl_expired",
            "latent_ref_expired",
            lambda: client.complete(
                _complete_payload(
                    run_id,
                    model=model,
                    compatibility_digest=compatibility_digest,
                    anchor=anchor,
                    ref_id=ref_id,
                    suffix="ttl",
                )
            ),
            "registry_ttl_before_materialize",
        )
        record.update(rejection)
    except Exception as exc:  # noqa: BLE001
        record["observed_error_code"] = _safe_error(exc)
    finally:
        record["cleanup"] = _safe_release(
            client,
            ref_id,
            acceptable_errors={"latent_ref_expired"},
        )
    record["ok"] = bool(record.get("ok")) and bool(record["cleanup"].get("ok"))
    return record


def _expect_error(
    name: str,
    expected_error_code: str,
    operation: Callable[[], Any],
    rejection_stage: str,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "name": name,
        "expected_error_code": expected_error_code,
        "rejection_stage": rejection_stage,
        "ok": False,
    }
    try:
        operation()
    except VllmLatentClientError as exc:
        record["observed_error_code"] = exc.error_code
        record["status_code"] = exc.status_code
        record["ok"] = exc.error_code == expected_error_code
    except Exception as exc:  # noqa: BLE001
        record["observed_error_code"] = type(exc).__name__
    else:
        record["observed_error_code"] = ""
    return record


def _safe_release(
    client: Any,
    ref_id: str,
    *,
    acceptable_errors: set[str] | None = None,
) -> dict[str, Any]:
    if not ref_id:
        return {"attempted": False, "ok": False}
    try:
        released = client.release(ref_id)
        return {
            "attempted": True,
            "status": str(released.get("status", "")),
            "ok": str(released.get("status", "")) == "released",
        }
    except VllmLatentClientError as exc:
        return {
            "attempted": True,
            "error_code": exc.error_code,
            "ok": exc.error_code in (acceptable_errors or set()),
        }
    except Exception as exc:  # noqa: BLE001
        return {"attempted": True, "error_code": type(exc).__name__, "ok": False}


def _probe_invalid_auth(base_url: str, timeout_s: float) -> dict[str, Any]:
    import httpx

    response = httpx.get(
        f"{base_url.rstrip('/')}/statebus/latent/health",
        headers={"authorization": "Bearer statebus-invalid-negative-probe"},
        timeout=timeout_s,
        trust_env=False,
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    return {
        "status_code": int(response.status_code),
        "error_code": str(body.get("error_code", "")) if isinstance(body, dict) else "",
    }


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, VllmLatentClientError):
        return exc.error_code
    return type(exc).__name__


def _write_result(
    payload: dict[str, Any], output_root: Path, run_id: str
) -> dict[str, Any]:
    path = output_root / f"negative_probe_{run_id}.json"
    payload["artifact_path"] = str(path)
    path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
