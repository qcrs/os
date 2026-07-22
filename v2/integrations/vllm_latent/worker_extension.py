from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.metadata
import logging
import os
import time
from typing import Any
from uuid import uuid4

from v2.contracts import (
    LatentAnchor,
    LatentForwardProof,
    LatentLifecycleState,
    LatentProofKind,
    NeuralCompatibilitySignature,
)
from v2.integrations.vllm_latent.registry import (
    LatentRegistryConfig,
    LatentRegistryError,
    LatentRegistryMetadata,
    LatentTensorRegistry,
)
from v2.utils import sha256_digest


WORKER_EXTENSION_VERSION = "statebus.vllm_latent.worker_extension.v1"
logger = logging.getLogger(__name__)


class LatentWorkerError(RuntimeError):
    def __init__(self, error_code: str, detail: str = "") -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.detail = detail


class LatentWorkerExtension:
    """Lazy vLLM worker extension; importing this module does not import vLLM."""

    def statebus_latent_capabilities(self) -> dict[str, object]:
        registry = self._statebus_registry()
        signature = self._statebus_signature()
        errors = list(signature.initial_support_matrix_errors())
        runner = getattr(self, "model_runner", None)
        if runner is None:
            errors.append("model_runner_missing")
        else:
            try:
                self._statebus_install_wrapper()
            except Exception as exc:
                errors.append(f"worker_hook_install_failed:{type(exc).__name__}")
        if getattr(self, "_statebus_capture_active", None) is not None:
            errors.append("capture_active")
        if not getattr(self, "_statebus_wrapper_installed", False):
            errors.append("worker_hook_not_installed")
        max_num_seqs = self._statebus_max_num_seqs()
        if max_num_seqs != 1:
            errors.append("max_num_seqs_not_one")
        prompt_embeds_enabled = self._statebus_prompt_embeds_enabled()
        if not prompt_embeds_enabled:
            errors.append("prompt_embeds_disabled")
        stats = registry.stats()
        if not errors and not getattr(self, "_statebus_ready_logged", False):
            logger.info("latent worker extension ready")
            self._statebus_ready_logged = True
        return {
            "status": "ready" if not errors else "not_ready",
            "plugin_version": WORKER_EXTENSION_VERSION,
            "vllm_version": signature.vllm_version,
            "engine_generation": signature.engine_generation,
            "model": signature.model_id,
            "hidden_size": signature.hidden_size,
            "prompt_embeds_enabled": prompt_embeds_enabled,
            "worker_extension_ready": not any(
                error in {"model_runner_missing", "max_num_seqs_not_one"}
                for error in errors
            ),
            "max_num_seqs": max_num_seqs,
            "tensor_parallel_size": signature.tensor_parallel_size,
            "pipeline_parallel_size": signature.pipeline_parallel_size,
            "compatibility_signature": signature.canonical_payload(),
            "compatibility_digest": signature.compatibility_digest,
            "registry_entries": stats["registry_entries"],
            "registry_bytes": stats["registry_bytes"],
            "registry_max_entries": registry.config.max_entries,
            "registry_max_bytes": registry.config.max_bytes,
            "registry_max_steps": registry.config.max_steps,
            "errors": sorted(set(errors)),
            "wrapper_installed": bool(getattr(self, "_statebus_wrapper_installed", False)),
        }

    def statebus_latent_begin(self, capture_spec: dict[str, object]) -> dict[str, object]:
        if getattr(self, "_statebus_capture_active", None) is not None:
            raise LatentWorkerError("latent_capture_busy")
        request_id = str(capture_spec.get("request_id", ""))
        if not request_id:
            raise LatentWorkerError("latent_request_invalid", "request_id")
        latent_steps = int(capture_spec.get("latent_steps", 0))
        registry = self._statebus_registry()
        if not 2 <= latent_steps <= registry.config.max_steps:
            raise LatentWorkerError("latent_request_invalid", "latent_steps")
        signature = self._statebus_signature()
        expected_digest = str(capture_spec.get("expected_compatibility_digest", ""))
        if expected_digest and expected_digest != signature.compatibility_digest:
            raise LatentWorkerError("latent_model_incompatible")
        anchor_payload = capture_spec.get("anchor", {})
        if not isinstance(anchor_payload, dict):
            raise LatentWorkerError("latent_anchor_mismatch")
        anchor = LatentAnchor(
            evidence_pack_hash=str(anchor_payload.get("evidence_pack_hash", "")),
            item_ids=tuple(str(item) for item in anchor_payload.get("item_ids", ())),
            locator_digest=str(anchor_payload.get("locator_digest", "")),
        )
        if not anchor.evidence_pack_hash or not anchor.locator_digest or not anchor.item_ids:
            raise LatentWorkerError("latent_anchor_mismatch")
        metadata = LatentRegistryMetadata(
            producer_role=str(capture_spec.get("producer_role", "retriever")),
            consumer_role=str(capture_spec.get("consumer_role", "summarizer")),
            source_task_id=str(capture_spec.get("task_id", "")),
            source_step_id=str(capture_spec.get("source_step_id", "")),
            anchor=anchor,
            compatibility_signature=signature,
            source_layer_index=int(capture_spec.get("source_layer_index", -1)),
            engine_id=str(capture_spec.get("engine_id", "vllm-v0")),
            producer_pid=os.getpid(),
        )
        ref_id = registry.prepare(
            metadata=metadata,
            latent_step_count=latent_steps,
            ttl_s=int(capture_spec.get("ttl_s", registry.config.default_ttl_s)),
            ref_id=str(capture_spec.get("ref_id", "")),
        )
        self._statebus_install_wrapper()
        runner = self.model_runner
        original_return_hidden_states = bool(getattr(runner, "return_hidden_states", False))
        runner.return_hidden_states = True
        self._statebus_capture_active = {
            "capture_id": str(capture_spec.get("capture_id", f"capture-{uuid4().hex}")),
            "ref_id": ref_id,
            "request_id": request_id,
            "latent_steps": latent_steps,
            "aligned": [],
            "pending": None,
            "captured_step_count": 0,
            "recurrence_injection_count": 0,
            "original_return_hidden_states": original_return_hidden_states,
        }
        return {
            "capture_id": self._statebus_capture_active["capture_id"],
            "ref_id": ref_id,
            "compatibility_digest": signature.compatibility_digest,
            "worker_pid": os.getpid(),
            "engine_id": metadata.engine_id,
        }

    def statebus_latent_finish(self, capture_id: str) -> dict[str, object]:
        active = getattr(self, "_statebus_capture_active", None)
        if active is None or str(active.get("capture_id")) != str(capture_id):
            raise LatentWorkerError("latent_capture_not_found")
        ref_id = str(active["ref_id"])
        try:
            captured = int(active["captured_step_count"])
            injected = int(active["recurrence_injection_count"])
            if captured != int(active["latent_steps"]) or injected != captured - 1:
                try:
                    self._statebus_registry().reject(ref_id, "latent_capture_incomplete")
                except LatentRegistryError:
                    pass
                raise LatentWorkerError("latent_capture_incomplete")
            torch = _torch_module()
            aligned = active["aligned"]
            if not aligned:
                raise LatentWorkerError("latent_capture_incomplete")
            tensor = torch.cat(tuple(aligned), dim=0)
            ref = self._statebus_registry().commit(
                ref_id,
                tensor,
                captured_step_count=captured,
                recurrence_injection_count=injected,
            )
            return {
                "ref": ref.canonical_payload(),
                "ref_id": ref.ref_id,
                "status": ref.status.value,
                "shape": list(ref.shape),
                "dtype": ref.dtype,
                "tensor_bytes": ref.tensor_bytes,
                "tensor_digest": ref.tensor_digest,
                "captured_step_count": captured,
                "recurrence_injection_count": injected,
                "producer_pid": ref.producer_pid,
                "compatibility_digest": ref.compatibility_digest,
                "internal_scheduler_sample_count": captured,
            }
        except LatentRegistryError as exc:
            raise LatentWorkerError(exc.error_code, exc.detail) from exc
        finally:
            self._statebus_clear_capture()

    def statebus_latent_abort(self, capture_id: str, reason: str) -> dict[str, object]:
        active = getattr(self, "_statebus_capture_active", None)
        if active is None or str(active.get("capture_id")) != str(capture_id):
            raise LatentWorkerError("latent_capture_not_found")
        ref_id = str(active["ref_id"])
        try:
            self._statebus_registry().reject(ref_id, str(reason) or "aborted")
        finally:
            self._statebus_clear_capture()
        return {"ref_id": ref_id, "status": "rejected", "reason": str(reason)}

    def statebus_latent_describe(self, ref_id: str) -> dict[str, object]:
        try:
            ref = self._statebus_registry().describe(str(ref_id))
        except LatentRegistryError as exc:
            raise LatentWorkerError(exc.error_code, exc.detail) from exc
        proof = self._statebus_registry().forward_proof(str(ref_id))
        return {
            "ref": ref.canonical_payload(),
            "ref_id": ref.ref_id,
            "status": ref.status.value,
            "forward_proof": None if proof is None else proof.canonical_payload(),
        }

    def statebus_latent_materialize_consumer_prompt(
        self,
        ref_id: str,
        left_token_ids: list[int],
        right_token_ids: list[int],
        request_id: str,
        expected_compatibility_digest: str,
        expected_anchor_digest: str,
    ) -> dict[str, object]:
        registry = self._statebus_registry()
        try:
            ref = registry.lease(
                str(ref_id),
                request_id=str(request_id),
                expected_compatibility_digest=str(expected_compatibility_digest),
                expected_anchor_digest=str(expected_anchor_digest),
            )
            torch = _torch_module()
            runner = self.model_runner
            device = getattr(runner, "device", None)
            if device is None:
                device = getattr(getattr(runner, "model", None), "device", "cpu")
            embedding = runner.model.get_input_embeddings
            left = torch.tensor(left_token_ids, dtype=torch.long, device=device)
            right = torch.tensor(right_token_ids, dtype=torch.long, device=device)
            pieces = []
            if left.numel():
                pieces.append(embedding(left))
            latent = registry.materialize_tensor(ref.ref_id).to(device=device)
            pieces.append(latent)
            if right.numel():
                pieces.append(embedding(right))
            combined = torch.cat(tuple(pieces), dim=0)
            cpu_combined = combined.detach().to(device="cpu", dtype=torch.bfloat16).contiguous()
            digest = _tensor_digest(cpu_combined)
            shape = tuple(int(value) for value in cpu_combined.shape)
            return {
                "ref_id": ref.ref_id,
                "prompt_embeds": cpu_combined,
                "prompt_embed_shape": list(shape),
                "prompt_embed_dtype": _dtype_name(cpu_combined),
                "prompt_embed_bytes": _tensor_nbytes(cpu_combined),
                "prompt_embed_digest": digest,
                "compatibility_digest": ref.compatibility_digest,
            }
        except LatentRegistryError as exc:
            raise LatentWorkerError(exc.error_code, exc.detail) from exc

    def statebus_latent_begin_consume(
        self,
        ref_id: str,
        request_id: str,
        prompt_embed_digest: str,
        prompt_embed_shape: list[int] | tuple[int, ...],
        prompt_embed_dtype: str,
    ) -> dict[str, object]:
        try:
            ref = self._statebus_registry().begin_consume(
                str(ref_id),
                request_id=str(request_id),
                prompt_embed_digest=str(prompt_embed_digest),
                prompt_embed_shape=tuple(int(value) for value in prompt_embed_shape),
                prompt_embed_dtype=str(prompt_embed_dtype),
            )
        except LatentRegistryError as exc:
            raise LatentWorkerError(exc.error_code, exc.detail) from exc
        self._statebus_consume_ref_id = ref.ref_id
        self._statebus_consume_request_id = str(request_id)
        self._statebus_consume_engine_id = ref.engine_id
        self._statebus_consume_prompt_embed_digest = str(prompt_embed_digest)
        self._statebus_consume_prompt_embed_shape = tuple(
            int(value) for value in prompt_embed_shape
        )
        self._statebus_consume_prompt_embed_dtype = str(prompt_embed_dtype)
        return {"ref_id": ref.ref_id, "status": ref.status.value}

    def statebus_latent_finish_consume(
        self,
        ref_id: str,
        request_id: str,
        forward_proof: dict[str, object],
    ) -> dict[str, object]:
        del forward_proof
        observed = getattr(self, "_statebus_observed_forward_proofs", {}).get(str(ref_id))
        if observed is None or observed.request_id != str(request_id):
            raise LatentWorkerError("latent_consumer_forward_not_observed")
        return {
            "ref_id": observed.ref_id,
            "status": self._statebus_registry().describe(observed.ref_id).status.value,
            "proof": observed.canonical_payload(),
        }

    def statebus_latent_release(self, ref_id: str) -> dict[str, object]:
        try:
            ref = self._statebus_registry().release(str(ref_id))
        except LatentRegistryError as exc:
            raise LatentWorkerError(exc.error_code, exc.detail) from exc
        if str(getattr(self, "_statebus_consume_ref_id", "")) == ref.ref_id:
            self._statebus_clear_consume()
        observed = getattr(self, "_statebus_observed_forward_proofs", None)
        if isinstance(observed, dict):
            observed.pop(ref.ref_id, None)
        return {"ref_id": ref.ref_id, "status": ref.status.value}

    def statebus_latent_sweep_expired(self) -> dict[str, object]:
        return {"expired_count": self._statebus_registry().sweep_expired()}

    def _statebus_registry(self) -> LatentTensorRegistry:
        registry = getattr(self, "_statebus_latent_registry", None)
        if registry is None:
            registry = LatentTensorRegistry(LatentRegistryConfig.from_env())
            self._statebus_latent_registry = registry
        return registry

    def _statebus_install_wrapper(self) -> None:
        runner = self.model_runner
        if getattr(self, "_statebus_wrapper_installed", False):
            return
        original = runner.execute_model
        extension = self

        def wrapped(model_input, *args, **kwargs):
            active = getattr(extension, "_statebus_capture_active", None)
            consume_ref_id = getattr(extension, "_statebus_consume_ref_id", "")
            inputs_embeds = getattr(model_input, "inputs_embeds", None)
            request_ids = getattr(model_input, "request_ids_to_seq_ids", None) or {}
            if active is not None:
                if set(request_ids) != {str(active["request_id"])}:
                    raise LatentWorkerError("latent_capture_request_mismatch")
                pending = active.get("pending")
                recurrence_injected = pending is not None
                if pending is not None:
                    try:
                        model_input = replace(model_input, inputs_embeds=pending)
                    except TypeError as exc:
                        raise LatentWorkerError("latent_model_input_not_replaceable") from exc
                    active["recurrence_injection_count"] += 1
                    inputs_embeds = pending
            else:
                recurrence_injected = False
            consume_binding = None
            if consume_ref_id and inputs_embeds is not None:
                expected_request_id = str(
                    getattr(extension, "_statebus_consume_request_id", "")
                )
                expected_digest = str(
                    getattr(extension, "_statebus_consume_prompt_embed_digest", "")
                )
                expected_shape = tuple(
                    getattr(extension, "_statebus_consume_prompt_embed_shape", ())
                )
                expected_dtype = str(
                    getattr(extension, "_statebus_consume_prompt_embed_dtype", "")
                )
                actual_shape = tuple(int(value) for value in inputs_embeds.shape)
                actual_dtype = _dtype_name(inputs_embeds)
                actual_digest = _tensor_digest(inputs_embeds)
                consume_binding = {
                    "expected_request_id": expected_request_id,
                    "expected_digest": expected_digest,
                    "expected_shape": expected_shape,
                    "expected_dtype": expected_dtype,
                    "actual_shape": actual_shape,
                    "actual_dtype": actual_dtype,
                    "actual_digest": actual_digest,
                    "request_id_matches": set(request_ids) == {expected_request_id},
                }
            try:
                output = original(model_input, *args, **kwargs)
            except Exception:
                if consume_ref_id:
                    extension._statebus_abort_consume_safely(
                        consume_ref_id, "consumer_forward_failed"
                    )
                raise
            if consume_binding is not None and output is not None:
                expected_request_id = consume_binding["expected_request_id"]
                expected_digest = consume_binding["expected_digest"]
                expected_shape = consume_binding["expected_shape"]
                expected_dtype = consume_binding["expected_dtype"]
                actual_shape = consume_binding["actual_shape"]
                actual_dtype = consume_binding["actual_dtype"]
                actual_digest = consume_binding["actual_digest"]
                request_id_matches = consume_binding["request_id_matches"]
                digest_matches = actual_digest == expected_digest
                shape_matches = actual_shape == expected_shape
                dtype_matches = actual_dtype == expected_dtype
                if not all(
                    (request_id_matches, digest_matches, shape_matches, dtype_matches)
                ):
                    logger.warning(
                        "latent consumer forward binding mismatch: "
                        "request_id_match=%s digest_match=%s "
                        "expected_shape=%s actual_shape=%s "
                        "expected_dtype=%s actual_dtype=%s",
                        request_id_matches,
                        digest_matches,
                        expected_shape,
                        actual_shape,
                        expected_dtype,
                        actual_dtype,
                    )
                    extension._statebus_abort_consume_safely(
                        consume_ref_id, "consumer_forward_binding_mismatch"
                    )
                else:
                    proof = LatentForwardProof(
                        ref_id=consume_ref_id,
                        request_id=expected_request_id,
                        worker_pid=os.getpid(),
                        engine_id=str(
                            getattr(
                                extension, "_statebus_consume_engine_id", "vllm-v0"
                            )
                        ),
                        inputs_embeds_shape=actual_shape,
                        inputs_embeds_dtype=actual_dtype,
                        inputs_embeds_digest=actual_digest,
                        observed_at_ns=time.time_ns(),
                        event_id=f"forward-{uuid4().hex}",
                        proof_kind=LatentProofKind.WORKER_FORWARD,
                    )
                    try:
                        extension._statebus_registry().finish_consume(proof)
                    except LatentRegistryError as exc:
                        logger.warning(
                            "latent consumer forward proof rejected: detail=%s",
                            exc.detail or "unspecified",
                        )
                        extension._statebus_abort_consume_safely(
                            consume_ref_id, "consumer_forward_proof_rejected"
                        )
                    else:
                        extension._statebus_observed_forward_proofs = {
                            **getattr(extension, "_statebus_observed_forward_proofs", {}),
                            consume_ref_id: proof,
                        }
                    finally:
                        extension._statebus_clear_consume()
            if recurrence_injected:
                # V0 adds sampled token embeddings whenever inputs_embeds is
                # present. The producer's recurrence input is only a temporary
                # decode substitution, not a prompt-embedding sequence owned by
                # vLLM's SequenceData; clear those optional output fields while
                # retaining hidden_states for the capture below.
                _clear_temporary_sampled_embeds(output)
            if active is not None:
                hidden = _extract_hidden_states(output)
                if hidden is None:
                    raise LatentWorkerError("latent_capture_incomplete", "hidden_missing")
                aligned = extension._statebus_align_hidden(hidden, model_input)
                active["aligned"].append(
                    aligned.detach().to(device="cpu", dtype=_torch_module().bfloat16)
                )
                active["pending"] = aligned.detach()
                active["captured_step_count"] += 1
            return output

        runner.execute_model = wrapped
        runner._statebus_original_execute_model = original
        runner._statebus_wrapper_depth = int(getattr(runner, "_statebus_wrapper_depth", 0)) + 1
        self._statebus_wrapper_installed = True

    def _statebus_clear_capture(self) -> None:
        active = getattr(self, "_statebus_capture_active", None)
        if active is not None:
            self.model_runner.return_hidden_states = active["original_return_hidden_states"]
            self._statebus_capture_active = None

    def _statebus_clear_consume(self) -> None:
        self._statebus_consume_ref_id = ""
        self._statebus_consume_request_id = ""
        self._statebus_consume_engine_id = ""
        self._statebus_consume_prompt_embed_digest = ""
        self._statebus_consume_prompt_embed_shape = ()
        self._statebus_consume_prompt_embed_dtype = ""

    def _statebus_abort_consume_safely(self, ref_id: str, reason: str) -> None:
        try:
            self._statebus_registry().abort_consume(ref_id, reason)
        except LatentRegistryError as exc:
            # Cleanup must never turn a rejected receipt into an engine error.
            logger.warning(
                "latent consumer abort cleanup failed: error_code=%s",
                exc.error_code,
            )
        finally:
            self._statebus_clear_consume()

    def _statebus_align_hidden(self, hidden: Any, model_input: Any) -> Any:
        torch = _torch_module()
        runner = self.model_runner
        if hidden.ndim == 1:
            hidden = hidden.unsqueeze(0)
        hidden = hidden[-1:].to(device=getattr(runner, "device", hidden.device))
        model = runner.model
        compute_logits = getattr(model, "compute_logits", None)
        embedding = getattr(model, "get_input_embeddings", None)
        if compute_logits is None or embedding is None:
            raise LatentWorkerError("latent_alignment_incompatible", "model_hooks_missing")
        # The captured hidden is already reduced to one row. Reusing the
        # request SamplingMetadata would apply prompt-relative pruning indices
        # to that row and can trigger an out-of-bounds CUDA index-select.
        logits = compute_logits(hidden, None)
        vocab_size = _configured_vocab_size(model, runner)
        if not getattr(self, "_statebus_alignment_bounds_logged", False):
            logger.info(
                "latent alignment bounds logits_vocab=%s input_vocab=%s",
                int(logits.shape[-1]),
                vocab_size,
            )
            self._statebus_alignment_bounds_logged = True
        if vocab_size > 0 and int(logits.shape[-1]) > vocab_size:
            # ParallelLMHead may expose padded logits rows that have no
            # corresponding input-embedding IDs (notably Qwen3 on V0).
            logits = logits[..., :vocab_size]
        top_k = int(os.environ.get("STATEBUS_LATENT_ALIGNMENT_TOP_K", "32"))
        top_k = max(1, min(top_k, int(logits.shape[-1])))
        temperature = float(os.environ.get("STATEBUS_LATENT_ALIGNMENT_TEMPERATURE", "1.0"))
        if temperature <= 0:
            raise LatentWorkerError("latent_alignment_incompatible", "temperature")
        values, indices = torch.topk(logits, k=top_k, dim=-1)
        weights = torch.softmax(values / temperature, dim=-1)
        token_embeds = embedding(indices.reshape(-1)).reshape(
            indices.shape[0], indices.shape[1], -1
        )
        aligned = (weights.unsqueeze(-1) * token_embeds).sum(dim=1)
        target_norm = self._statebus_embedding_norm(token_embeds)
        current_norm = aligned.float().norm(dim=-1, keepdim=True).clamp_min(1e-6)
        aligned = aligned * (target_norm / current_norm)
        return aligned.to(dtype=torch.bfloat16)

    def _statebus_embedding_norm(self, sample_embeds: Any) -> Any:
        cached = getattr(self, "_statebus_embedding_mean_norm", None)
        if cached is not None:
            return cached.to(device=sample_embeds.device, dtype=sample_embeds.dtype)
        torch = _torch_module()
        model = self.model_runner.model
        vocab_size = _configured_vocab_size(model, self.model_runner)
        if not vocab_size:
            vocab_size = int(sample_embeds.shape[1])
        count = min(1024, vocab_size)
        ids = torch.linspace(
            0, max(vocab_size - 1, 0), count, dtype=torch.long,
            device=sample_embeds.device,
        )
        sampled = model.get_input_embeddings(ids)
        value = sampled.float().norm(dim=-1).mean().reshape(1, 1)
        self._statebus_embedding_mean_norm = value.detach().cpu()
        return value.to(device=sample_embeds.device, dtype=sample_embeds.dtype)

    def _statebus_signature(self) -> NeuralCompatibilitySignature:
        override = getattr(self, "_statebus_signature_override", None)
        if override is not None:
            return override
        config = getattr(self, "vllm_config", None)
        model_config = getattr(config, "model_config", None)
        hf_config = getattr(model_config, "hf_config", None)
        architecture = str(
            (getattr(hf_config, "architectures", None) or ["Qwen3ForCausalLM"])[0]
        )
        hidden_size = int(getattr(hf_config, "hidden_size", 0) or 0)
        num_layers = int(
            getattr(hf_config, "num_hidden_layers", getattr(hf_config, "num_layers", 0)) or 0
        )
        num_attention_heads = int(getattr(hf_config, "num_attention_heads", 0) or 0)
        num_kv_heads = int(
            getattr(hf_config, "num_key_value_heads", num_attention_heads) or 0
        )
        head_dim = int(
            getattr(hf_config, "head_dim", 0)
            or (hidden_size // num_attention_heads if num_attention_heads else 0)
        )
        model_id = os.environ.get("STATEBUS_LATENT_MODEL_ID", "qwen3-32b")
        revision = os.environ.get(
            "STATEBUS_LATENT_MODEL_REVISION_DIGEST",
            str(getattr(model_config, "revision", "unknown")),
        )
        tokenizer_revision = os.environ.get("STATEBUS_LATENT_TOKENIZER_REVISION", revision)
        chat_digest = os.environ.get("STATEBUS_LATENT_CHAT_TEMPLATE_DIGEST", "unknown")
        position_digest = os.environ.get(
            "STATEBUS_LATENT_POSITION_CONTRACT_DIGEST",
            sha256_digest({
                "marker": "<|statebus_latent_v1|>",
                "chat_template": chat_digest,
                "chat_template_kwargs": {"enable_thinking": False},
                "consumer_render_mode": "messages_or_pre_rendered_v1",
                "tokenization": "add_special_tokens_false_left_right",
                "concat": "left_latent_right",
            }),
        )
        alignment_digest = sha256_digest({
            "method": "soft_token_topk_v1",
            "top_k": int(os.environ.get("STATEBUS_LATENT_ALIGNMENT_TOP_K", "32")),
            "temperature": float(os.environ.get("STATEBUS_LATENT_ALIGNMENT_TEMPERATURE", "1.0")),
            "normalization": "fixed_stride_1024_input_embedding_mean_norm",
            "model_revision": revision,
        })
        try:
            vllm_version = importlib.metadata.version("vllm")
        except importlib.metadata.PackageNotFoundError:
            vllm_version = "unknown"
        return NeuralCompatibilitySignature(
            vllm_version=vllm_version,
            engine_generation="V0" if os.environ.get("VLLM_USE_V1", "0") == "0" else "V1",
            model_id=model_id,
            model_revision_or_manifest_digest=revision,
            architecture=architecture,
            tokenizer_id=model_id,
            tokenizer_revision=tokenizer_revision,
            chat_template_digest=chat_digest,
            active_lora_or_adapter_digest=os.environ.get("STATEBUS_LATENT_LORA_DIGEST", "none"),
            quantization_digest=os.environ.get("STATEBUS_LATENT_QUANTIZATION_DIGEST", "none"),
            dtype=str(getattr(model_config, "dtype", "bfloat16")),
            hidden_size=hidden_size,
            num_layers=num_layers,
            num_attention_heads=num_attention_heads,
            num_kv_heads=num_kv_heads,
            head_dim=head_dim,
            rope_config_digest=sha256_digest(str(getattr(hf_config, "rope_theta", "default"))),
            attention_backend=str(
                getattr(getattr(self, "model_runner", None), "attn_backend", "unknown")
            ),
            tensor_parallel_size=int(
                getattr(getattr(config, "parallel_config", None), "tensor_parallel_size", 1)
            ),
            pipeline_parallel_size=int(
                getattr(getattr(config, "parallel_config", None), "pipeline_parallel_size", 1)
            ),
            worker_extension_version=WORKER_EXTENSION_VERSION,
            alignment_method="soft_token_topk_v1",
            alignment_config_digest=alignment_digest,
            position_contract_digest=position_digest,
        )

    def _statebus_max_num_seqs(self) -> int:
        config = getattr(self, "vllm_config", None)
        scheduler = getattr(config, "scheduler_config", None)
        return int(getattr(scheduler, "max_num_seqs", 1) or 1)

    def _statebus_prompt_embeds_enabled(self) -> bool:
        config = getattr(self, "vllm_config", None)
        model_config = getattr(config, "model_config", None)
        value = getattr(model_config, "enable_prompt_embeds", None)
        if value is None:
            value = os.environ.get("STATEBUS_LATENT_PROMPT_EMBEDS_ENABLED", "true")
        return bool(value) if isinstance(value, bool) else str(value).lower() in {
            "1", "true", "yes", "on"
        }


def _configured_vocab_size(model: Any, runner: Any) -> int:
    """Return the vocab size accepted by the model's input embeddings."""

    nested_model = getattr(model, "model", None)
    embedding_layer = getattr(nested_model, "embed_tokens", None)
    candidates = (
        getattr(getattr(model, "config", None), "vocab_size", 0),
        getattr(getattr(nested_model, "config", None), "vocab_size", 0),
        getattr(embedding_layer, "num_embeddings", 0),
        getattr(embedding_layer, "org_vocab_size", 0),
        getattr(getattr(runner, "model_config", None), "vocab_size", 0),
    )
    values: list[int] = []
    for candidate in candidates:
        try:
            value = int(candidate or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            values.append(value)
    return min(values, default=0)


def _torch_module():
    import torch

    return torch


def _clear_temporary_sampled_embeds(output: Any) -> None:
    outputs = output if isinstance(output, (list, tuple)) else (output,)
    for item in outputs:
        if item is None:
            continue
        if hasattr(item, "sampled_token_embeds"):
            item.sampled_token_embeds = None
        for group in getattr(item, "outputs", ()) or ():
            for sample in getattr(group, "samples", ()) or ():
                if hasattr(sample, "output_embed"):
                    sample.output_embed = None


def _extract_hidden_states(output: Any) -> Any | None:
    if isinstance(output, (list, tuple)):
        if not output:
            return None
        output = output[0]
    return getattr(output, "hidden_states", None)


def _tensor_raw_bytes(tensor: Any) -> bytes:
    torch = _torch_module()
    cpu = tensor.detach().to(device="cpu", dtype=torch.bfloat16).contiguous()
    return cpu.view(torch.uint8).numpy().tobytes()


def _tensor_digest(tensor: Any) -> str:
    return hashlib.sha256(_tensor_raw_bytes(tensor)).hexdigest()


def _tensor_nbytes(tensor: Any) -> int:
    return len(_tensor_raw_bytes(tensor))


def _dtype_name(tensor: Any) -> str:
    name = str(getattr(tensor, "dtype", "")).replace("torch.", "")
    return {"bf16": "bfloat16", "bfloat16": "bfloat16"}.get(name, name)
