from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import time

from v2.contracts import (
    AdaptiveTaskEnvelope,
    CapabilityDescriptor,
    Claim,
    ClaimSet,
    EvidenceRequest,
    ExecutionKind,
    HandoffIntent,
    LatentForwardProof,
    LatentHandoffMode,
    LatentLifecycleState,
    LatentProofKind,
    NeuralCompatibilitySignature,
    PlanProposal,
    PlanStepProposal,
    RefStatus,
    RiskClass,
    WorkflowMode,
)
from v2.integrations.vllm_latent.middleware import LATENT_MARKER
from v2.refs import (
    CanonicalEvidencePack,
    EvidenceItem,
    ExecutionArtifactRef,
    LatentStateRef,
    TextSpanLocator,
)
from v2.runtime.adaptive_dispatcher import StoredAdaptiveArtifact
from v2.runtime.adaptive_mainline import (
    AdaptiveMainlineBindings,
    AdaptiveMainlineRequest,
    AdaptiveMainlineResult,
    AdaptiveMainlineRunner,
)
from v2.runtime.adaptive_runtime import AdaptiveStepResult
from v2.runtime.capability_registry import CapabilityRegistry
from v2.runtime.latent_handoff import (
    LatentHandoffController,
    LatentHandoffPolicyConfig,
)
from v2.runtime.retrieval_adapter import AdaptiveRetrievalAdapter
from v2.runtime.role_model_backend import (
    LatentBackendHealth,
    LatentCompleteRequest,
    LatentCompleteResult,
    LatentProduceRequest,
    LatentProduceResult,
)
from v2.utils import sha256_digest, stable_json_dumps


EVIDENCE_SECRET = "EVIDENCE_BODY_MUST_NOT_PERSIST_" + ("long narrative context " * 32)
PROMPT_SECRET = "CONSUMER_PROMPT_MUST_NOT_PERSIST"
TOKEN_SECRET = "TOKEN_MUST_NOT_PERSIST"
TENSOR_SECRET = "RAW_TENSOR_MUST_NOT_PERSIST"


class RecordingLatentBackend:
    def __init__(
        self,
        signature: NeuralCompatibilitySignature,
        *,
        completion_kind: str = "valid",
    ) -> None:
        self.signature = signature
        self.completion_kind = completion_kind
        self.health_calls = 0
        self.produce_calls = 0
        self.complete_calls = 0
        self.release_calls = 0
        self.produce_requests: list[LatentProduceRequest] = []
        self.complete_requests: list[LatentCompleteRequest] = []
        self.released_ref_ids: list[str] = []
        self.refs: dict[str, LatentStateRef] = {}

    def health(self) -> LatentBackendHealth:
        self.health_calls += 1
        return LatentBackendHealth(
            status="ready",
            plugin_version="statebus.test.worker-forward.v1",
            compatibility_signature=self.signature,
            worker_extension_ready=True,
            prompt_embeds_enabled=True,
            max_num_seqs=1,
            registry_entries=len(self.refs) - len(self.released_ref_ids),
            registry_bytes=sum(
                ref.tensor_bytes
                for ref_id, ref in self.refs.items()
                if ref_id not in self.released_ref_ids
            ),
            registry_max_entries=64,
            registry_max_bytes=67_108_864,
        )

    def produce(self, request: LatentProduceRequest) -> LatentProduceResult:
        self.produce_calls += 1
        self.produce_requests.append(request)
        now_ns = time.time_ns()
        ref_id = f"latent-mainline-{self.produce_calls}"
        tensor_digest = sha256_digest({
            "request_id": request.request_id,
            "anchor": request.anchor.anchor_digest,
        })
        ref = LatentStateRef(
            ref_id=ref_id,
            status=LatentLifecycleState.COMMITTED,
            backend_handle=f"engine-private:{TENSOR_SECRET}",
            producer_role=request.producer_role,
            consumer_role=request.consumer_role,
            source_task_id=request.task_id,
            source_step_id=request.source_step_id,
            source_evidence_pack_hash=request.anchor.evidence_pack_hash,
            anchor_item_ids=request.anchor.item_ids,
            anchor_locator_digest=request.anchor.locator_digest,
            model_id=self.signature.model_id,
            model_revision=self.signature.model_revision_or_manifest_digest,
            tokenizer_revision=self.signature.tokenizer_revision,
            chat_template_digest=self.signature.chat_template_digest,
            hidden_size=self.signature.hidden_size,
            source_layer_index=-1,
            latent_step_count=request.latent_steps,
            alignment_method=request.alignment_method,
            alignment_config_digest=self.signature.alignment_config_digest,
            position_contract_digest=self.signature.position_contract_digest,
            dtype="bfloat16",
            shape=(request.latent_steps, self.signature.hidden_size),
            tensor_bytes=request.latent_steps * self.signature.hidden_size * 2,
            tensor_digest=tensor_digest,
            producer_pid=4242,
            engine_id="test-vllm-engine",
            created_at_ns=now_ns,
            expires_at_ns=now_ns + request.ttl_s * 1_000_000_000,
            compatibility_digest=self.signature.compatibility_digest,
            metadata={"raw_tensor": TENSOR_SECRET},
        )
        self.refs[ref_id] = ref
        return LatentProduceResult(
            ref=ref,
            captured_step_count=request.latent_steps,
            recurrence_injection_count=request.latent_steps - 1,
            internal_scheduler_sample_count=request.latent_steps,
            telemetry={
                "request_id": request.request_id,
                "producer_prefill_ms": 1.0,
                "rendered_prompt": EVIDENCE_SECRET,
                "api_token": TOKEN_SECRET,
                "raw_tensor": TENSOR_SECRET,
            },
        )

    def complete(self, request: LatentCompleteRequest) -> LatentCompleteResult:
        self.complete_calls += 1
        self.complete_requests.append(request)
        ref = self.refs[request.latent_ref_id]
        prompt_shape = (ref.latent_step_count + 4, ref.hidden_size)
        if self.completion_kind == "missing_proof":
            return LatentCompleteResult(
                text="latent-valid",
                consumed_ref_id=ref.ref_id,
                consumer_forward_observed=False,
                forward_proof=None,
                prompt_embed_shape=prompt_shape,
                telemetry={"consumer_forward_observed": False},
            )
        prompt_digest = sha256_digest({
            "request_id": request.request_id,
            "ref_id": ref.ref_id,
            "shape": prompt_shape,
        })
        proof = LatentForwardProof(
            ref_id=ref.ref_id,
            request_id=request.request_id,
            worker_pid=4343,
            engine_id=ref.engine_id,
            inputs_embeds_shape=prompt_shape,
            inputs_embeds_dtype="bfloat16",
            inputs_embeds_digest=prompt_digest,
            observed_at_ns=time.time_ns(),
            event_id=f"forward-{request.request_id}",
            proof_kind=LatentProofKind.WORKER_FORWARD,
        )
        return LatentCompleteResult(
            text=(
                "latent-invalid"
                if self.completion_kind == "invalid_claim"
                else "latent-valid"
            ),
            consumed_ref_id=ref.ref_id,
            consumer_forward_observed=True,
            forward_proof=proof,
            prompt_embed_shape=prompt_shape,
            prompt_tokens_equivalent=prompt_shape[0],
            completion_tokens=16,
            telemetry={
                "request_id": request.request_id,
                "ref_id": ref.ref_id,
                "consumer_forward_observed": True,
                "consumer_forward_event_id": proof.event_id,
                "consumer_forward_inputs_embeds_shape": list(prompt_shape),
                "consumer_forward_inputs_embeds_dtype": proof.inputs_embeds_dtype,
                "consumer_forward_inputs_embeds_digest": prompt_digest,
                "consumer_model_ms": 2.0,
                "rendered_prompt": request.rendered_prompt,
                "api_token": TOKEN_SECRET,
                "raw_tensor": TENSOR_SECRET,
            },
        )

    def release(self, ref_id: str) -> None:
        self.release_calls += 1
        self.released_ref_ids.append(ref_id)


@dataclass(frozen=True)
class MainlineHarnessResult:
    result: AdaptiveMainlineResult
    backend: RecordingLatentBackend
    text_call_count: int


def _claim_set(
    *,
    task_id: str,
    artifact_id: str,
    locator: TextSpanLocator,
    valid: bool,
) -> ClaimSet:
    return ClaimSet(
        claim_set_id="latent-mainline-claims",
        task_id=task_id,
        claims=(Claim(
            claim_id="metric-claim",
            claim_text="The verified metric is 7.",
            claim_type="fact",
            supporting_evidence_item_ids=(
                "narrative-1" if valid else "unknown-evidence",
            ),
            supporting_artifact_ref_ids=(artifact_id,),
            citation_locators=(repr(locator) if valid else "unknown-locator",),
            numeric_fields={"metric": 7.0},
        ),),
    )


def _run_mainline(
    tmp_path: Path,
    *,
    signature: NeuralCompatibilitySignature,
    mode: LatentHandoffMode,
    completion_kind: str = "valid",
    min_evidence_tokens: int = 1,
    consumer_signature: NeuralCompatibilitySignature | None = None,
    executor_fails: bool = False,
) -> MainlineHarnessResult:
    task_id = tmp_path.name.replace("_", "-")
    registry = CapabilityRegistry()
    descriptors = (
        CapabilityDescriptor(
            capability_id="retrieve-latent-evidence",
            owner_role="retriever",
            description="retrieve bounded narrative evidence",
            input_ref_kinds=(),
            required_input_ref_kinds=(),
            input_contract_version="input-v1",
            output_ref_kinds=("canonical_evidence_pack",),
            output_contract_version="evidence-v1",
            execution_kind=ExecutionKind.RETRIEVAL_ADAPTER,
            side_effect_class=RiskClass.READ_ONLY,
            max_runtime_ms=10_000,
            supports_replay=False,
        ),
        CapabilityDescriptor(
            capability_id="execute-latent-analysis",
            owner_role="executor",
            description="materialize a verified analysis artifact",
            input_ref_kinds=("canonical_evidence_pack",),
            required_input_ref_kinds=("canonical_evidence_pack",),
            input_contract_version="evidence-v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="artifact-v1",
            execution_kind=ExecutionKind.RUNTIME_BUILTIN,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=10_000,
            supports_replay=False,
        ),
        CapabilityDescriptor(
            capability_id="summarize-latent-analysis",
            owner_role="summarizer",
            description="validate and materialize a cited ClaimSet",
            input_ref_kinds=("canonical_evidence_pack", "execution_artifact"),
            required_input_ref_kinds=(
                "canonical_evidence_pack",
                "execution_artifact",
            ),
            input_contract_version="artifact-v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="report-v1",
            execution_kind=ExecutionKind.RUNTIME_BUILTIN,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=10_000,
            supports_replay=False,
        ),
    )
    for descriptor in descriptors:
        registry.register(descriptor)

    envelope = AdaptiveTaskEnvelope(
        task_id=task_id,
        canonical_task_spec_hash="latent-mainline-spec",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="latent-mainline-test-pack",
        allowed_capability_ids=tuple(
            descriptor.capability_id for descriptor in descriptors
        ),
        allowed_output_contracts=("evidence-v1", "artifact-v1", "report-v1"),
        allowed_handoff_intents=(
            HandoffIntent.AUTO.value,
            HandoffIntent.TEXT.value,
            HandoffIntent.LATENT_ASSIST.value,
        ),
        role_cardinality={
            "retriever": (1, 1),
            "executor": (1, 1),
            "summarizer": (1, 1),
        },
        risk_class=RiskClass.WORKSPACE_WRITE,
        max_plan_steps=3,
        max_retrieval_steps=1,
        max_total_attempts=3,
    )
    proposal = PlanProposal(
        proposal_id=f"proposal-{task_id}",
        task_id=task_id,
        final_output_contract_version="report-v1",
        steps=(
            PlanStepProposal(
                step_id="retrieve",
                role="retriever",
                capability_id="retrieve-latent-evidence",
                goal="retrieve long narrative evidence",
                output_contract_version="evidence-v1",
                handoff_intent=HandoffIntent.LATENT_ASSIST,
            ),
            PlanStepProposal(
                step_id="execute",
                role="executor",
                capability_id="execute-latent-analysis",
                goal="materialize the verified metric",
                depends_on=("retrieve",),
                output_contract_version="artifact-v1",
            ),
            PlanStepProposal(
                step_id="summarize",
                role="summarizer",
                capability_id="summarize-latent-analysis",
                goal="produce a cited ClaimSet",
                depends_on=("retrieve", "execute"),
                output_contract_version="report-v1",
            ),
        ),
    )
    locator = TextSpanLocator(
        source_doc_hash="doc-hash",
        canonical_text_id="narrative-doc",
        start_char=0,
        end_char=len(EVIDENCE_SECRET),
        extractor_version="test-v1",
    )
    evidence_pack = CanonicalEvidencePack(
        pack_id="latent-mainline-evidence",
        task_id=task_id,
        source_doc_hashes=("doc-hash",),
        semantic_contexts=(EvidenceItem(
            item_id="narrative-1",
            bucket="semantic_context",
            locator=locator,
            rendered_text=EVIDENCE_SECRET,
            source_name="offline-fixture",
        ),),
    )
    artifacts: dict[str, StoredAdaptiveArtifact] = {}

    def executor_handler(_envelope, _plan, _step, grant, workspace):
        if executor_fails:
            return AdaptiveStepResult(
                grant_hash=grant.grant_hash,
                success=False,
                attempt_id=grant.attempt_id,
                error_code="forced_executor_failure",
            )
        rows = ({"metric": 7.0},)
        payload = stable_json_dumps(list(rows)).encode("utf-8")
        output_dir = workspace / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "analysis.json"
        output_path.write_bytes(payload)
        artifact_id = f"analysis-{grant.attempt_id}"
        artifact = ExecutionArtifactRef(
            artifact_id=artifact_id,
            task_id=grant.task_id,
            step_id=grant.step_id,
            artifact_type="json",
            root_id=str(workspace),
            relpath=str(output_path.relative_to(workspace)),
            blob_hash=sha256_digest(payload),
            size_bytes=len(payload),
            produced_by="executor",
            verification_state=RefStatus.VERIFIED,
            metadata={
                "session_id": grant.session_id,
                "attempt_id": grant.attempt_id,
            },
        )
        artifacts[artifact_id] = StoredAdaptiveArtifact(
            artifact=artifact,
            rows=rows,
            provenance_item_ids=("narrative-1",),
        )
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            attempt_id=grant.attempt_id,
            output_refs=(artifact_id,),
            output_ref_kinds=("execution_artifact",),
        )

    text_calls: list[str] = []
    current_artifact_id = {"value": ""}

    def text_claim_set_factory(_step, grant, artifact, _rows, _evidence_pack):
        text_calls.append(grant.attempt_id)
        return _claim_set(
            task_id=grant.task_id,
            artifact_id=artifact.artifact_id,
            locator=locator,
            valid=True,
        )

    def complete_request_factory(
        _step,
        grant,
        artifact,
        _rows,
        _evidence_pack,
        ref,
        anchor,
        expected_signature,
    ) -> LatentCompleteRequest:
        current_artifact_id["value"] = artifact.artifact_id
        return LatentCompleteRequest(
            request_id=f"latent-complete-{grant.attempt_id}",
            latent_ref_id=ref.ref_id,
            rendered_prompt=(
                f"{PROMPT_SECRET} anchor={anchor.anchor_digest} "
                f"artifact={artifact.artifact_id} {LATENT_MARKER} claimset"
            ),
            response_schema={"type": "object"},
            temperature=0.0,
            max_tokens=128,
            seed=7,
            expected_compatibility_digest=(
                expected_signature.compatibility_digest
            ),
            expected_anchor=anchor,
        )

    def parse_latent_claim_set(text: str) -> ClaimSet:
        return _claim_set(
            task_id=task_id,
            artifact_id=current_artifact_id["value"],
            locator=locator,
            valid=text == "latent-valid",
        )

    backend = RecordingLatentBackend(
        signature,
        completion_kind=completion_kind,
    )
    controller = LatentHandoffController(LatentHandoffPolicyConfig(
        mode=mode,
        min_evidence_tokens=min_evidence_tokens,
        max_evidence_tokens=10_000,
        latent_steps=2,
        ttl_s=60,
    ))
    request = AdaptiveMainlineRequest(
        trace_id=f"trace-{task_id}",
        task_id=task_id,
        canonical_task_spec_hash=envelope.canonical_task_spec_hash,
        envelope=envelope,
        registry=registry,
        runtime_root=tmp_path / "runtime",
        workspace_root=tmp_path / "workspaces",
        propose_plan=lambda: proposal,
        bindings=AdaptiveMainlineBindings(
            artifacts=artifacts,
            retrieval_adapter=AdaptiveRetrievalAdapter(
                lambda _query, _request: evidence_pack
            ),
            retrieval_request_factory=lambda step, grant: EvidenceRequest(
                request_id=f"evidence-{grant.attempt_id}",
                task_id=grant.task_id,
                step_id=step.step_id,
                queries=("offline narrative evidence",),
                evidence_types=("semantic_context",),
                corpus_scope_ids=("offline-fixture",),
            ),
            allowed_corpus_scope_ids=("offline-fixture",),
            claim_set_factory=text_claim_set_factory,
            latent_handoff_controller=controller,
            latent_role_backend=backend,
            latent_producer_signature=signature,
            latent_consumer_signature=consumer_signature or signature,
            latent_producer_message_factory=lambda _step, _grant, pack: (
                {"role": "system", "content": "bounded latent producer"},
                {
                    "role": "user",
                    "content": pack.semantic_contexts[0].rendered_text,
                },
            ),
            latent_complete_request_factory=complete_request_factory,
            latent_claim_set_parser=parse_latent_claim_set,
            builtin_handlers={"execute-latent-analysis": executor_handler},
        ),
        memory_commit_enabled=False,
        state_pool_mode="mmap",
    )
    result = AdaptiveMainlineRunner().run(request)
    return MainlineHarnessResult(
        result=result,
        backend=backend,
        text_call_count=len(text_calls),
    )


def _event_types(result: AdaptiveMainlineResult) -> list[str]:
    return [event.event_type for event in result.runtime.telemetry.events]


def test_mode_off_makes_zero_backend_calls_and_preserves_text_path(
    tmp_path: Path,
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    harness = _run_mainline(
        tmp_path,
        signature=neural_signature,
        mode=LatentHandoffMode.OFF,
    )

    assert harness.result.completed
    assert harness.text_call_count == 1
    assert (
        harness.backend.health_calls,
        harness.backend.produce_calls,
        harness.backend.complete_calls,
        harness.backend.release_calls,
    ) == (0, 0, 0, 0)
    state = harness.result.context.latent_handoffs_by_consumer_step["summarize"]
    assert state.decision.rejection_reason == "mode_enabled"
    assert state.text_fallback_used is False


def test_gate_rejection_uses_exactly_one_text_call(
    tmp_path: Path,
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    harness = _run_mainline(
        tmp_path,
        signature=neural_signature,
        mode=LatentHandoffMode.PLANNER_ASSIST,
        min_evidence_tokens=4_096,
    )

    assert harness.result.completed
    assert harness.text_call_count == 1
    assert harness.backend.health_calls == 1
    assert harness.backend.produce_calls == 0
    assert harness.backend.complete_calls == 0
    state = harness.result.context.latent_handoffs_by_consumer_step["summarize"]
    assert state.decision.rejection_reason == "evidence_token_budget"
    assert state.fallback_call_count == 1
    assert _event_types(harness.result).count("LATENT_HANDOFF_FALLBACK") == 1


def test_worker_forward_and_valid_claim_set_complete_latent_mainline(
    tmp_path: Path,
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    harness = _run_mainline(
        tmp_path,
        signature=neural_signature,
        mode=LatentHandoffMode.PLANNER_ASSIST,
    )

    assert harness.result.completed
    assert harness.text_call_count == 0
    assert (
        harness.backend.health_calls,
        harness.backend.produce_calls,
        harness.backend.complete_calls,
        harness.backend.release_calls,
    ) == (1, 1, 1, 1)
    state = harness.result.context.latent_handoffs_by_consumer_step["summarize"]
    assert state.latent_consumed is True
    assert state.latent_quality_passed is True
    assert state.text_fallback_used is False
    assert state.released is True
    assert state.ref is not None
    assert state.ref.status == LatentLifecycleState.RELEASED
    assert _event_types(harness.result).count("LATENT_STATE_CONSUMED") == 1
    metrics = harness.result.runtime.telemetry.summarize_task(
        harness.result.runtime.session.task_id
    )
    assert metrics["latent_success_count"] == 1.0
    assert metrics.get("latent_text_fallback_count", 0.0) == 0.0


def test_signature_mismatch_rejects_before_produce_or_forward(
    tmp_path: Path,
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    harness = _run_mainline(
        tmp_path,
        signature=neural_signature,
        consumer_signature=replace(
            neural_signature,
            position_contract_digest="sha256:incompatible-position",
        ),
        mode=LatentHandoffMode.PLANNER_ASSIST,
    )

    assert harness.result.completed
    assert harness.text_call_count == 1
    assert harness.backend.health_calls == 1
    assert harness.backend.produce_calls == 0
    assert harness.backend.complete_calls == 0
    state = harness.result.context.latent_handoffs_by_consumer_step["summarize"]
    assert state.decision.rejection_reason == "signature_exact_match"
    assert state.latent_consumed is False


def test_missing_worker_forward_proof_never_counts_consumption(
    tmp_path: Path,
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    harness = _run_mainline(
        tmp_path,
        signature=neural_signature,
        mode=LatentHandoffMode.PLANNER_ASSIST,
        completion_kind="missing_proof",
    )

    assert harness.result.completed
    assert harness.text_call_count == 1
    assert harness.backend.complete_calls == 1
    assert harness.backend.release_calls == 1
    state = harness.result.context.latent_handoffs_by_consumer_step["summarize"]
    assert state.latent_consumed is False
    assert state.fallback_reason == "latent_consumer_forward_not_observed"
    assert state.fallback_call_count == 1
    assert "LATENT_STATE_CONSUMED" not in _event_types(harness.result)
    metrics = harness.result.runtime.telemetry.summarize_task(
        harness.result.runtime.session.task_id
    )
    assert metrics["latent_success_count"] == 0.0


def test_invalid_latent_claim_set_uses_only_one_text_fallback(
    tmp_path: Path,
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    harness = _run_mainline(
        tmp_path,
        signature=neural_signature,
        mode=LatentHandoffMode.PLANNER_ASSIST,
        completion_kind="invalid_claim",
    )

    assert harness.result.completed
    assert harness.text_call_count == 1
    assert harness.backend.complete_calls == 1
    assert harness.backend.release_calls == 1
    state = harness.result.context.latent_handoffs_by_consumer_step["summarize"]
    assert state.latent_consumed is True
    assert state.latent_quality_passed is False
    assert state.fallback_reason == "latent_output_validation_failed"
    assert state.fallback_call_count == 1
    assert _event_types(harness.result).count("LATENT_HANDOFF_FALLBACK") == 1
    assert "LATENT_OUTPUT_VALIDATED" not in _event_types(harness.result)
    metrics = harness.result.runtime.telemetry.summarize_task(
        harness.result.runtime.session.task_id
    )
    assert metrics["latent_success_count"] == 0.0
    assert metrics["latent_text_fallback_count"] == 1.0


def test_manifest_keeps_only_safe_latent_metadata(
    tmp_path: Path,
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    harness = _run_mainline(
        tmp_path,
        signature=neural_signature,
        mode=LatentHandoffMode.PLANNER_ASSIST,
    )

    manifest_text = harness.result.manifest_path.read_text(encoding="utf-8")
    for forbidden in (
        EVIDENCE_SECRET,
        PROMPT_SECRET,
        TOKEN_SECRET,
        TENSOR_SECRET,
        LATENT_MARKER,
    ):
        assert forbidden not in manifest_text
    manifest = json.loads(manifest_text)
    state = manifest["latent_handoffs"]["summarize"]
    assert state["latent_consumed"] is True
    assert state["latent_quality_passed"] is True
    assert state["released"] is True
    assert state["ref"]["status"] == "released"
    assert "backend_handle" not in state["ref"]
    assert "metadata" not in state["ref"]
    assert {event["event_type"] for event in manifest["latent_events"]} >= {
        "LATENT_HANDOFF_DECIDED",
        "LATENT_STATE_COMMITTED",
        "LATENT_STATE_CONSUMED",
        "LATENT_OUTPUT_VALIDATED",
        "LATENT_STATE_RELEASED",
    }


def test_runtime_failure_releases_active_latent_ref(
    tmp_path: Path,
    neural_signature: NeuralCompatibilitySignature,
) -> None:
    harness = _run_mainline(
        tmp_path,
        signature=neural_signature,
        mode=LatentHandoffMode.PLANNER_ASSIST,
        executor_fails=True,
    )

    assert harness.result.completed is False
    assert harness.text_call_count == 0
    assert harness.backend.produce_calls == 1
    assert harness.backend.complete_calls == 0
    assert harness.backend.release_calls == 1
    state = harness.result.context.latent_handoffs_by_consumer_step["summarize"]
    assert state.released is True
    assert state.release_reason == "runtime_incomplete"
    release_events = [
        event
        for event in harness.result.runtime.telemetry.events
        if event.event_type == "LATENT_STATE_RELEASED"
    ]
    assert len(release_events) == 1
    assert release_events[0].step_id == "runtime.latent_cleanup"
    manifest = json.loads(harness.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["latent_handoffs"]["summarize"]["released"] is True
