from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import subprocess
import time
from typing import Any, Mapping, Sequence

from v2.benchmark.experiment_design import summarize_distribution
from v2.contracts import (
    Claim,
    ClaimSet,
    ClaimSetStatus,
    LatentAnchor,
    LatentHandoffMode,
    NeuralCompatibilitySignature,
    RefStatus,
)
from v2.integrations.vllm_latent.client import (
    VllmLatentClient,
    VllmLatentClientError,
)
from v2.integrations.vllm_latent.middleware import LATENT_MARKER
from v2.integrations.vllm_latent.role_model_backend_adapter import (
    VllmLatentRoleModelBackend,
)
from v2.refs import (
    CanonicalEvidencePack,
    EvidenceItem,
    ExecutionArtifactRef,
    TextSpanLocator,
)
from v2.runtime.claims import ClaimSetValidator
from v2.runtime.latent_handoff import (
    LatentHandoffController,
    LatentHandoffPolicyConfig,
    latent_telemetry_audit_view,
)
from v2.runtime.role_model_backend import (
    LatentBackendError,
    LatentCompleteRequest,
    LatentCompleteResult,
    LatentProduceRequest,
    LatentProduceResult,
)
from v2.utils import sha256_digest, stable_json_dumps


LANES = ("C0", "T0", "A0", "L1", "N1")
V1_MANIFEST = Path(
    "v2/benchmark/samples/latent_narrative_holdout_v1/manifest.json"
)
V2_MANIFEST = Path(
    "v2/benchmark/samples/latent_narrative_holdout_v2/manifest.json"
)
V3_MANIFEST = Path(
    "v2/benchmark/samples/latent_narrative_holdout_v3/manifest.json"
)
V4_MANIFEST = Path(
    "v2/benchmark/samples/latent_narrative_holdout_v4/manifest.json"
)
V6_MANIFEST = Path(
    "v2/benchmark/samples/latent_narrative_holdout_v6/manifest.json"
)
DEFAULT_MANIFEST = Path(
    "v2/benchmark/samples/latent_narrative_holdout_v5/manifest.json"
)
_FROZEN_FIXED_PARAMETERS: dict[str, object] = {
    "model_family": "Qwen3-32B",
    "vllm_version": "0.9.2",
    "engine_generation": "V0",
    "temperature": 0,
    "seed": 7,
    "summarizer_max_tokens": 768,
    "retriever_text_max_tokens": 128,
    "latent_steps": 8,
    "memory_enabled": False,
    "codeact_enabled": False,
    "prefix_alignment_mode": "independent",
}
_FROZEN_V2_FIXED_PARAMETERS: dict[str, object] = {
    **_FROZEN_FIXED_PARAMETERS,
    "retriever_text_max_tokens": 192,
    "latent_steps": 16,
}
_FROZEN_V6_FIXED_PARAMETERS: dict[str, object] = {
    **_FROZEN_V2_FIXED_PARAMETERS,
    "latent_steps": 40,
    "chat_template_thinking": False,
    "consumer_prompt_mode": "structured_messages",
}
_FROZEN_QUALITY_THRESHOLDS: dict[str, int] = {
    "required_fact_count": 24,
    "c0_min_passed_facts": 22,
    "t0_min_passed_facts": 20,
    "l1_min_passed_facts": 22,
    "l1_max_fact_deficit_vs_c0": 1,
    "l1_min_fact_gain_vs_a0": 3,
    "l1_required_mechanism_cases": 6,
    "n1_required_pre_forward_rejections": 6,
}
_FROZEN_CATEGORIES = frozenset({
    "condition_and_exception_combination",
    "conflict_or_risk_judgment",
    "cross_paragraph_time_qualification",
})
_FROZEN_V2_CATEGORIES = frozenset({
    "long_document_causal_analysis",
    "cross_document_evidence_synthesis",
    "conditional_plan_switch",
})
_MANIFEST_CONTRACTS: dict[str, dict[str, object]] = {
    "statebus.latent_narrative_holdout.v1": {
        "family_id": "latent_narrative_holdout_v1",
        "fixed_parameters": _FROZEN_FIXED_PARAMETERS,
        "quality_thresholds": _FROZEN_QUALITY_THRESHOLDS,
        "categories": _FROZEN_CATEGORIES,
        "case_scoped_sources": False,
    },
    "statebus.latent_narrative_holdout.v2": {
        "family_id": "latent_narrative_holdout_v2",
        "fixed_parameters": _FROZEN_V2_FIXED_PARAMETERS,
        "quality_thresholds": _FROZEN_QUALITY_THRESHOLDS,
        "categories": _FROZEN_V2_CATEGORIES,
        "case_scoped_sources": True,
    },
    "statebus.latent_narrative_holdout.v3": {
        "family_id": "latent_narrative_holdout_v3",
        "fixed_parameters": _FROZEN_V2_FIXED_PARAMETERS,
        "quality_thresholds": _FROZEN_QUALITY_THRESHOLDS,
        "categories": _FROZEN_V2_CATEGORIES,
        "case_scoped_sources": True,
    },
    "statebus.latent_narrative_holdout.v4": {
        "family_id": "latent_narrative_holdout_v4",
        "fixed_parameters": _FROZEN_V2_FIXED_PARAMETERS,
        "quality_thresholds": _FROZEN_QUALITY_THRESHOLDS,
        "categories": _FROZEN_V2_CATEGORIES,
        "case_scoped_sources": True,
    },
    "statebus.latent_narrative_holdout.v5": {
        "family_id": "latent_narrative_holdout_v5",
        "fixed_parameters": _FROZEN_V2_FIXED_PARAMETERS,
        "quality_thresholds": _FROZEN_QUALITY_THRESHOLDS,
        "categories": _FROZEN_V2_CATEGORIES,
        "case_scoped_sources": True,
        "scoring_contract": "statebus.required_fact_phrase.v2",
    },
    "statebus.latent_narrative_holdout.v6": {
        "family_id": "latent_narrative_holdout_v6",
        "fixed_parameters": _FROZEN_V6_FIXED_PARAMETERS,
        "quality_thresholds": _FROZEN_QUALITY_THRESHOLDS,
        "categories": _FROZEN_V2_CATEGORIES,
        "case_scoped_sources": True,
        "scoring_contract": "statebus.required_fact_phrase.v2",
    },
}


class NativeLatentExperimentError(RuntimeError):
    pass


@dataclass(frozen=True)
class RequiredFact:
    fact_id: str
    term_groups: tuple[tuple[str, ...], ...]
    source_item_ids: tuple[str, ...]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "RequiredFact":
        return cls(
            fact_id=str(payload["fact_id"]),
            term_groups=tuple(
                tuple(str(term) for term in group)
                for group in payload["term_groups"]
            ),
            source_item_ids=tuple(
                str(item_id) for item_id in payload["source_item_ids"]
            ),
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "fact_id": self.fact_id,
            "term_groups": [list(group) for group in self.term_groups],
            "source_item_ids": list(self.source_item_ids),
        }


@dataclass(frozen=True)
class NarrativeCase:
    case_id: str
    category: str
    task: str
    lane_order: tuple[str, ...]
    required_facts: tuple[RequiredFact, ...]
    source_item_ids: tuple[str, ...] = ()
    task_mode: str = ""
    manifest_schema_version: str = "statebus.latent_narrative_holdout.v1"

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        manifest_schema_version: str = "statebus.latent_narrative_holdout.v1",
    ) -> "NarrativeCase":
        return cls(
            case_id=str(payload["case_id"]),
            category=str(payload["category"]),
            task=str(payload["task"]),
            lane_order=tuple(str(lane) for lane in payload["lane_order"]),
            required_facts=tuple(
                RequiredFact.from_payload(item)
                for item in payload["required_facts"]
            ),
            source_item_ids=tuple(
                str(item_id) for item_id in payload.get("source_item_ids", ())
            ),
            task_mode=str(payload.get("task_mode", "")),
            manifest_schema_version=manifest_schema_version,
        )

    def generation_payload(self) -> dict[str, str]:
        """The only case fields allowed to enter model-visible surfaces."""

        payload = {
            "case_id": self.case_id,
            "category": self.category,
            "task": self.task,
        }
        if self.task_mode:
            payload["task_mode"] = self.task_mode
        return payload

    def canonical_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            **self.generation_payload(),
            "lane_order": list(self.lane_order),
            "required_facts": [
                fact.canonical_payload() for fact in self.required_facts
            ],
        }
        if self.source_item_ids:
            payload["source_item_ids"] = list(self.source_item_ids)
        return payload


@dataclass(frozen=True)
class SourceDocument:
    item_id: str
    path: Path
    bucket: str
    text: str
    content_hash: str

    @classmethod
    def load(
        cls,
        payload: Mapping[str, Any],
        *,
        project_root: Path,
    ) -> "SourceDocument":
        relative_path = Path(str(payload["path"]))
        path = (project_root / relative_path).resolve()
        if not path.is_relative_to(project_root.resolve()) or not path.is_file():
            raise NativeLatentExperimentError("source_document_path_invalid")
        text = path.read_text(encoding="utf-8")
        return cls(
            item_id=str(payload["item_id"]),
            path=relative_path,
            bucket=str(payload["bucket"]),
            text=text,
            content_hash=sha256_digest(text),
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "path": self.path.as_posix(),
            "bucket": self.bucket,
            "content_hash": self.content_hash,
            "content_bytes": len(self.text.encode("utf-8")),
        }


@dataclass(frozen=True)
class ExperimentDefinition:
    manifest_path: Path
    manifest_hash: str
    payload: Mapping[str, Any]
    sources: tuple[SourceDocument, ...]
    cases: tuple[NarrativeCase, ...]

    @property
    def fixed_parameters(self) -> Mapping[str, Any]:
        return dict(self.payload["fixed_parameters"])

    @property
    def quality_thresholds(self) -> Mapping[str, Any]:
        return dict(self.payload["quality_thresholds"])

    def preregistered_payload(self) -> dict[str, object]:
        source_corpus_bytes = sum(
            len(source.text.encode("utf-8")) for source in self.sources
        )
        source_corpus_tokens = sum(
            (len(source.text.encode("utf-8")) + 3) // 4
            for source in self.sources
        )
        case_scoped = all(case.source_item_ids for case in self.cases)
        case_selections = tuple(
            {
                "case_id": case.case_id,
                "source_item_ids": list(case.source_item_ids),
                "selected_evidence_bytes": sum(
                    len(source.text.encode("utf-8"))
                    for source in _case_sources(case, self.sources)
                ),
                "selected_evidence_tokens_estimate": sum(
                    (len(source.text.encode("utf-8")) + 3) // 4
                    for source in _case_sources(case, self.sources)
                ),
            }
            for case in self.cases
        )
        payload: dict[str, object] = {
            "schema_version": "statebus.native_latent_preregistered_plan.v1",
            "manifest_path": self.manifest_path.as_posix(),
            "manifest_hash": self.manifest_hash,
            "family_id": str(self.payload["family_id"]),
            "frozen_at_utc": str(self.payload["frozen_at_utc"]),
            "schedule_seed": int(self.payload["schedule_seed"]),
            "schedule_policy": str(self.payload["schedule_policy"]),
            "fixed_parameters": dict(self.fixed_parameters),
            "quality_thresholds": dict(self.quality_thresholds),
            "sources": [source.canonical_payload() for source in self.sources],
            "selected_evidence_bytes": (
                sum(int(item["selected_evidence_bytes"]) for item in case_selections)
                if case_scoped
                else source_corpus_bytes
            ),
            "selected_evidence_tokens_estimate": (
                sum(
                    int(item["selected_evidence_tokens_estimate"])
                    for item in case_selections
                )
                if case_scoped
                else source_corpus_tokens
            ),
            "cases": [case.canonical_payload() for case in self.cases],
        }
        if "scoring_contract" in self.payload:
            payload["scoring_contract"] = str(self.payload["scoring_contract"])
        if case_scoped:
            payload["source_corpus_bytes"] = source_corpus_bytes
            payload["source_corpus_tokens_estimate"] = source_corpus_tokens
            payload["case_evidence_selection"] = list(case_selections)
        return payload


@dataclass(frozen=True)
class ExperimentConfig:
    project_root: Path
    output_root: Path
    manifest_path: Path = DEFAULT_MANIFEST
    base_url: str = "http://127.0.0.1:53334"
    token_file: Path | None = None
    timeout_s: float = 300.0
    run_id: str = ""
    lanes: tuple[str, ...] = LANES


@dataclass(frozen=True)
class ChatCompletionReceipt:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    elapsed_ms: float
    finish_reason: str = ""

    def canonical_payload(self) -> dict[str, object]:
        return {
            "text": self.text,
            "text_hash": sha256_digest(self.text),
            "text_bytes": len(self.text.encode("utf-8")),
            "model": self.model,
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
            },
            "elapsed_ms": self.elapsed_ms,
            "finish_reason": self.finish_reason,
        }


class LocalJsonChatClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_s: float,
    ) -> None:
        try:
            import httpx
        except ImportError as exc:
            raise NativeLatentExperimentError("http_client_unavailable") from exc
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self._client = httpx.Client(timeout=timeout_s, trust_env=False)

    def complete(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        response_schema: Mapping[str, Any],
        max_tokens: int,
        seed: int,
    ) -> ChatCompletionReceipt:
        started = time.perf_counter()
        response = self._client.post(
            f"{self.base_url}/v1/chat/completions",
            json={
                "model": self.model,
                "messages": [dict(message) for message in messages],
                "temperature": 0.0,
                "max_tokens": int(max_tokens),
                "seed": int(seed),
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "statebus_native_latent_output",
                        "strict": True,
                        "schema": dict(response_schema),
                    },
                },
                "chat_template_kwargs": {"enable_thinking": False},
                "guided_decoding_backend": "xgrammar:disable-any-whitespace",
            },
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if response.status_code >= 400:
            raise NativeLatentExperimentError(
                f"chat_completion_http_{response.status_code}"
            )
        try:
            payload = response.json()
            choice = payload["choices"][0]
            text = str(choice["message"]["content"] or "").strip()
            finish_reason = str(choice.get("finish_reason") or "")
            usage = dict(payload.get("usage", {}))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise NativeLatentExperimentError(
                "chat_completion_response_invalid"
            ) from exc
        return ChatCompletionReceipt(
            text=text,
            model=str(payload.get("model", self.model)),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
            elapsed_ms=elapsed_ms,
            finish_reason=finish_reason,
        )

    def close(self) -> None:
        self._client.close()


def load_experiment_definition(
    manifest_path: Path,
    *,
    project_root: Path,
) -> ExperimentDefinition:
    project_root = project_root.resolve()
    resolved_manifest = (
        manifest_path
        if manifest_path.is_absolute()
        else project_root / manifest_path
    ).resolve()
    if (
        not resolved_manifest.is_relative_to(project_root)
        or not resolved_manifest.is_file()
    ):
        raise NativeLatentExperimentError("experiment_manifest_path_invalid")
    raw = resolved_manifest.read_bytes()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NativeLatentExperimentError("experiment_manifest_json_invalid") from exc
    if not isinstance(payload, dict):
        raise NativeLatentExperimentError("experiment_manifest_shape_invalid")
    sources = tuple(
        SourceDocument.load(item, project_root=project_root)
        for item in payload.get("source_documents", ())
    )
    manifest_schema_version = str(payload.get("schema_version", ""))
    cases = tuple(
        NarrativeCase.from_payload(
            item,
            manifest_schema_version=manifest_schema_version,
        )
        for item in payload.get("cases", ())
    )
    _validate_definition(payload, sources=sources, cases=cases)
    return ExperimentDefinition(
        manifest_path=resolved_manifest.relative_to(project_root),
        manifest_hash=sha256_digest(raw),
        payload=payload,
        sources=sources,
        cases=cases,
    )


def _validate_definition(
    payload: Mapping[str, Any],
    *,
    sources: tuple[SourceDocument, ...],
    cases: tuple[NarrativeCase, ...],
) -> None:
    schema_version = str(payload.get("schema_version", ""))
    contract = _MANIFEST_CONTRACTS.get(schema_version)
    if contract is None:
        raise NativeLatentExperimentError("experiment_manifest_schema_invalid")
    if payload.get("family_id") != contract["family_id"]:
        raise NativeLatentExperimentError("experiment_family_id_invalid")
    if payload.get("fixed_parameters") != contract["fixed_parameters"]:
        raise NativeLatentExperimentError("experiment_fixed_parameters_invalid")
    if payload.get("quality_thresholds") != contract["quality_thresholds"]:
        raise NativeLatentExperimentError("experiment_quality_thresholds_invalid")
    expected_scoring_contract = contract.get("scoring_contract")
    if (
        expected_scoring_contract is not None
        and payload.get("scoring_contract") != expected_scoring_contract
    ):
        raise NativeLatentExperimentError("experiment_scoring_contract_invalid")
    if len(sources) < 2 or len({source.item_id for source in sources}) != len(sources):
        raise NativeLatentExperimentError("experiment_sources_invalid")
    if any(
        not source.item_id
        or source.bucket not in {"semantic_context", "lexical_hint"}
        or not source.text.strip()
        for source in sources
    ):
        raise NativeLatentExperimentError("experiment_source_contract_invalid")
    if len(cases) != 6 or len({case.case_id for case in cases}) != 6:
        raise NativeLatentExperimentError("experiment_case_count_invalid")
    source_ids = {source.item_id for source in sources}
    case_scoped_sources = bool(contract["case_scoped_sources"])
    category_counts: dict[str, int] = {}
    fact_ids: set[str] = set()
    for case in cases:
        category_counts[case.category] = category_counts.get(case.category, 0) + 1
        if not case.case_id.strip() or not case.task.strip():
            raise NativeLatentExperimentError("experiment_case_contract_invalid")
        if tuple(sorted(case.lane_order)) != tuple(sorted(LANES)):
            raise NativeLatentExperimentError("experiment_lane_order_invalid")
        if len(case.required_facts) != 4:
            raise NativeLatentExperimentError("experiment_case_fact_count_invalid")
        if case_scoped_sources:
            if (
                case.task_mode != case.category
                or not case.source_item_ids
                or len(set(case.source_item_ids)) != len(case.source_item_ids)
                or not set(case.source_item_ids) <= source_ids
            ):
                raise NativeLatentExperimentError(
                    "experiment_case_source_contract_invalid"
                )
            authorized_source_ids = set(case.source_item_ids)
        else:
            if case.source_item_ids or case.task_mode:
                raise NativeLatentExperimentError(
                    "experiment_v1_case_contract_changed"
                )
            authorized_source_ids = source_ids
        required_source_ids: set[str] = set()
        for fact in case.required_facts:
            if (
                not fact.fact_id
                or not fact.term_groups
                or any(not group for group in fact.term_groups)
                or any(not term.strip() for group in fact.term_groups for term in group)
            ):
                raise NativeLatentExperimentError("experiment_fact_contract_invalid")
            if (
                not fact.source_item_ids
                or not set(fact.source_item_ids) <= authorized_source_ids
            ):
                raise NativeLatentExperimentError(
                    "experiment_fact_source_unauthorized"
                )
            if fact.fact_id in fact_ids:
                raise NativeLatentExperimentError("experiment_fact_id_duplicate")
            fact_ids.add(fact.fact_id)
            required_source_ids.update(fact.source_item_ids)
        if case_scoped_sources and required_source_ids != authorized_source_ids:
            raise NativeLatentExperimentError(
                "experiment_case_source_coverage_invalid"
            )
    if (
        set(category_counts) != set(contract["categories"])
        or set(category_counts.values()) != {2}
    ):
        raise NativeLatentExperimentError("experiment_category_balance_invalid")
    if sum(len(case.required_facts) for case in cases) != 24:
        raise NativeLatentExperimentError("experiment_fact_total_invalid")
    paired_orders = tuple(zip(cases[::2], cases[1::2], strict=True))
    if any(
        left.category != right.category
        or right.lane_order != tuple(reversed(left.lane_order))
        for left, right in paired_orders
    ):
        raise NativeLatentExperimentError("experiment_schedule_pairing_invalid")
    if len({left.lane_order for left, _right in paired_orders}) != 3:
        raise NativeLatentExperimentError("experiment_schedule_diversity_invalid")


def write_preregistered_plan(config: ExperimentConfig) -> Path:
    definition = load_experiment_definition(
        config.manifest_path,
        project_root=config.project_root,
    )
    output_root = config.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "preregistered_experiment_plan.json"
    if path.exists():
        raise NativeLatentExperimentError("preregistered_plan_already_exists")
    path.write_text(
        stable_json_dumps(definition.preregistered_payload()) + "\n",
        encoding="utf-8",
    )
    return path


def run_native_latent_experiment(config: ExperimentConfig) -> dict[str, Any]:
    definition = load_experiment_definition(
        config.manifest_path,
        project_root=config.project_root,
    )
    output_root = config.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    result_path = output_root / "native_latent_experiment.json"
    if result_path.exists():
        raise NativeLatentExperimentError("experiment_result_already_exists")
    requested_lanes = tuple(dict.fromkeys(config.lanes))
    if (
        not requested_lanes
        or any(lane not in LANES for lane in requested_lanes)
    ):
        raise NativeLatentExperimentError("experiment_requested_lanes_invalid")
    requested_lane_set = set(requested_lanes)
    preregistered_path = output_root / "preregistered_experiment_plan.json"
    if not preregistered_path.exists():
        preregistered_path.write_text(
            stable_json_dumps(definition.preregistered_payload()) + "\n",
            encoding="utf-8",
        )

    run_id = config.run_id or datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    token_file = config.token_file
    if token_file is None:
        raise NativeLatentExperimentError("latent_token_file_required")
    latent_client = VllmLatentClient(
        base_url=config.base_url,
        token_file=token_file,
        timeout_s=config.timeout_s,
    )
    backend = VllmLatentRoleModelBackend(latent_client)
    health = backend.health()
    if not health.ready:
        latent_client.close()
        raise NativeLatentExperimentError("latent_backend_not_ready")
    expected = definition.fixed_parameters
    signature = health.compatibility_signature
    if (
        signature.vllm_version != str(expected["vllm_version"])
        or signature.engine_generation.upper()
        != str(expected["engine_generation"]).upper()
        or signature.model_id.lower()
        != str(expected["model_family"]).lower()
    ):
        latent_client.close()
        raise NativeLatentExperimentError("experiment_model_signature_mismatch")
    chat_client = LocalJsonChatClient(
        base_url=config.base_url,
        model=signature.model_id,
        timeout_s=config.timeout_s,
    )
    controller = LatentHandoffController(LatentHandoffPolicyConfig(
        mode=LatentHandoffMode.FORCE,
        min_evidence_tokens=1,
        max_evidence_tokens=8_000,
        latent_steps=int(expected["latent_steps"]),
        ttl_s=300,
    ))
    payload: dict[str, Any] = {
        "schema_version": "statebus.native_latent_experiment.v1",
        "run_id": run_id,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "definition": definition.preregistered_payload(),
        "environment": _environment_payload(
            config=config,
            signature=signature,
            health=health.canonical_payload(),
        ),
        "requested_lanes": list(requested_lanes),
        "samples": [],
        "summary": {},
        "completed": False,
    }
    raw_root = output_root / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    try:
        for case in definition.cases:
            pack = _build_evidence_pack(case, definition.sources)
            artifact, artifact_rows = _verified_artifact(case, pack)
            for sequence_index, lane in enumerate(case.lane_order, start=1):
                if lane not in requested_lane_set:
                    continue
                try:
                    record = _run_lane(
                        lane=lane,
                        case=case,
                        sequence_index=sequence_index,
                        pack=pack,
                        artifact=artifact,
                        artifact_rows=artifact_rows,
                        chat_client=chat_client,
                        backend=backend,
                        controller=controller,
                        signature=signature,
                        fixed_parameters=expected,
                        run_id=run_id,
                    )
                except Exception as exc:  # noqa: BLE001 - retain failed raw sample.
                    record = {
                        "schema_version": "statebus.native_latent_sample.v1",
                        "case_id": case.case_id,
                        "category": case.category,
                        "lane": lane,
                        "sequence_index": sequence_index,
                        "ok": False,
                        "error_code": _safe_error(exc),
                        "latent_success": False,
                        "fallback_used": False,
                        "quality": _empty_quality(case),
                    }
                case_root = raw_root / case.case_id
                case_root.mkdir(parents=True, exist_ok=True)
                raw_path = case_root / f"{sequence_index:02d}_{lane}.json"
                raw_path.write_text(
                    stable_json_dumps(record) + "\n",
                    encoding="utf-8",
                )
                payload["samples"].append({
                    "case_id": case.case_id,
                    "lane": lane,
                    "sequence_index": sequence_index,
                    "artifact": raw_path.relative_to(output_root).as_posix(),
                    "record_hash": sha256_digest(record),
                    "ok": bool(record.get("ok")),
                    "latent_success": bool(record.get("latent_success")),
                    "fallback_used": bool(record.get("fallback_used")),
                    "quality": dict(record.get("quality", {})),
                    "elapsed_ms": float(record.get("elapsed_ms", 0.0)),
                    "mechanism": dict(record.get("mechanism", {})),
                })
                _write_progress(payload, output_root)
        payload["summary"] = _summarize_experiment(
            definition=definition,
            sample_index=tuple(payload["samples"]),
            output_root=output_root,
        )
        payload["completed"] = True
        payload["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        result_path.write_text(
            stable_json_dumps(payload) + "\n",
            encoding="utf-8",
        )
        _write_checksums(output_root)
        return {**payload, "artifact_path": str(result_path)}
    finally:
        chat_client.close()
        latent_client.close()


def _run_lane(
    *,
    lane: str,
    case: NarrativeCase,
    sequence_index: int,
    pack: CanonicalEvidencePack,
    artifact: ExecutionArtifactRef,
    artifact_rows: tuple[dict[str, object], ...],
    chat_client: LocalJsonChatClient,
    backend: VllmLatentRoleModelBackend,
    controller: LatentHandoffController,
    signature: NeuralCompatibilitySignature,
    fixed_parameters: Mapping[str, Any],
    run_id: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    if lane == "C0":
        record = _run_c0(
            case=case,
            pack=pack,
            artifact=artifact,
            artifact_rows=artifact_rows,
            chat_client=chat_client,
            fixed_parameters=fixed_parameters,
        )
    elif lane == "T0":
        record = _run_t0(
            case=case,
            pack=pack,
            artifact=artifact,
            artifact_rows=artifact_rows,
            chat_client=chat_client,
            fixed_parameters=fixed_parameters,
        )
    elif lane == "A0":
        record = _run_a0(
            case=case,
            pack=pack,
            artifact=artifact,
            artifact_rows=artifact_rows,
            chat_client=chat_client,
            fixed_parameters=fixed_parameters,
        )
    elif lane == "L1":
        record = _run_l1(
            case=case,
            pack=pack,
            artifact=artifact,
            artifact_rows=artifact_rows,
            chat_client=chat_client,
            backend=backend,
            controller=controller,
            signature=signature,
            fixed_parameters=fixed_parameters,
            run_id=run_id,
        )
    elif lane == "N1":
        record = _run_n1(
            case=case,
            pack=pack,
            artifact=artifact,
            artifact_rows=artifact_rows,
            chat_client=chat_client,
            backend=backend,
            controller=controller,
            signature=signature,
            fixed_parameters=fixed_parameters,
            run_id=run_id,
        )
    else:
        raise NativeLatentExperimentError("experiment_lane_unknown")
    return {
        "schema_version": "statebus.native_latent_sample.v1",
        "case_id": case.case_id,
        "category": case.category,
        "lane": lane,
        "sequence_index": sequence_index,
        "task_hash": sha256_digest(case.generation_payload()),
        "evidence_pack_hash": pack.pack_hash,
        "artifact_id": artifact.artifact_id,
        "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        **record,
    }


def _run_c0(
    *,
    case: NarrativeCase,
    pack: CanonicalEvidencePack,
    artifact: ExecutionArtifactRef,
    artifact_rows: tuple[dict[str, object], ...],
    chat_client: LocalJsonChatClient,
    fixed_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    evidence_text = _render_selected_evidence(pack)
    return _run_text_summary(
        lane="C0",
        case=case,
        pack=pack,
        artifact=artifact,
        artifact_rows=artifact_rows,
        chat_client=chat_client,
        fixed_parameters=fixed_parameters,
        handoff_kind="full_selected_evidence",
        handoff_text=evidence_text,
        visible_evidence_bytes=len(evidence_text.encode("utf-8")),
    )


def _run_t0(
    *,
    case: NarrativeCase,
    pack: CanonicalEvidencePack,
    artifact: ExecutionArtifactRef,
    artifact_rows: tuple[dict[str, object], ...],
    chat_client: LocalJsonChatClient,
    fixed_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    retriever_messages = _retriever_messages(case, pack)
    retriever_prompt_hash = sha256_digest(retriever_messages)
    retriever = chat_client.complete(
        messages=retriever_messages,
        response_schema=_retriever_schema(_evidence_items(pack)),
        max_tokens=int(fixed_parameters["retriever_text_max_tokens"]),
        seed=int(fixed_parameters["seed"]),
    )
    retriever_receipt = {
        **retriever.canonical_payload(),
        "prompt_hash": retriever_prompt_hash,
        "prompt_bytes": _messages_bytes(retriever_messages),
    }
    try:
        handoff_payload = json.loads(retriever.text)
        if not isinstance(handoff_payload, dict):
            raise TypeError("retriever payload must be an object")
        analysis_value = handoff_payload["analysis"]
        if not isinstance(analysis_value, str) or not analysis_value.strip():
            raise ValueError("retriever analysis must be non-empty text")
        analysis = analysis_value.strip()
        cited_values = handoff_payload.get("cited_item_ids", ())
        if not isinstance(cited_values, list):
            raise TypeError("retriever citations must be an array")
        cited_item_ids = tuple(
            str(value) for value in cited_values
        )
        evidence_item_ids = {item.item_id for item in _evidence_items(pack)}
        if (
            not cited_item_ids
            or not set(cited_item_ids) <= evidence_item_ids
        ):
            raise ValueError("retriever citations are outside selected evidence")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return {
            "ok": False,
            "error_code": "retriever_text_handoff_invalid",
            "latent_success": False,
            "fallback_used": False,
            "generation_path": "retriever_text_invalid",
            "model_call_count": 1,
            "retriever": retriever_receipt,
            "quality": _empty_quality(case),
            "visible_evidence_bytes": 0,
            "visible_evidence_tokens": 0,
            "text_handoff_bytes": 0,
            "text_handoff_completion_tokens": retriever.completion_tokens,
            "tensor_bytes": 0,
            "mechanism": {},
        }
    summary = _run_text_summary(
        lane="T0",
        case=case,
        pack=pack,
        artifact=artifact,
        artifact_rows=artifact_rows,
        chat_client=chat_client,
        fixed_parameters=fixed_parameters,
        handoff_kind="bounded_retriever_text",
        handoff_text=analysis,
        visible_evidence_bytes=0,
    )
    summary["retriever"] = {
        **retriever_receipt,
        "cited_item_ids": list(cited_item_ids),
    }
    summary["text_handoff_bytes"] = len(analysis.encode("utf-8"))
    summary["text_handoff_completion_tokens"] = retriever.completion_tokens
    summary["model_call_count"] = 2
    return summary


def _run_a0(
    *,
    case: NarrativeCase,
    pack: CanonicalEvidencePack,
    artifact: ExecutionArtifactRef,
    artifact_rows: tuple[dict[str, object], ...],
    chat_client: LocalJsonChatClient,
    fixed_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    return _run_text_summary(
        lane="A0",
        case=case,
        pack=pack,
        artifact=artifact,
        artifact_rows=artifact_rows,
        chat_client=chat_client,
        fixed_parameters=fixed_parameters,
        handoff_kind="anchor_only",
        handoff_text="",
        visible_evidence_bytes=0,
    )


def _run_text_summary(
    *,
    lane: str,
    case: NarrativeCase,
    pack: CanonicalEvidencePack,
    artifact: ExecutionArtifactRef,
    artifact_rows: tuple[dict[str, object], ...],
    chat_client: LocalJsonChatClient,
    fixed_parameters: Mapping[str, Any],
    handoff_kind: str,
    handoff_text: str,
    visible_evidence_bytes: int,
) -> dict[str, Any]:
    messages = _summarizer_messages(
        case=case,
        pack=pack,
        artifact=artifact,
        handoff_kind=handoff_kind,
        handoff_text=handoff_text,
    )
    completion = chat_client.complete(
        messages=messages,
        response_schema=_claim_set_schema(case, pack, artifact),
        max_tokens=int(fixed_parameters["summarizer_max_tokens"]),
        seed=int(fixed_parameters["seed"]),
    )
    quality = _evaluate_claim_text(
        completion.text,
        case=case,
        pack=pack,
        artifact=artifact,
        artifact_rows=artifact_rows,
    )
    return {
        "ok": bool(quality["parse_ok"] and quality["validator_ok"]),
        "latent_success": False,
        "fallback_used": False,
        "generation_path": "text",
        "model_call_count": 1,
        "summarizer": {
            **completion.canonical_payload(),
            "prompt_hash": sha256_digest(messages),
            "prompt_bytes": _messages_bytes(messages),
        },
        "quality": quality,
        "visible_evidence_bytes": visible_evidence_bytes,
        "visible_evidence_tokens": completion.prompt_tokens,
        "text_handoff_bytes": (
            len(handoff_text.encode("utf-8"))
            if handoff_kind == "bounded_retriever_text"
            else 0
        ),
        "text_handoff_completion_tokens": 0,
        "tensor_bytes": 0,
        "mechanism": {},
    }


def _run_l1(
    *,
    case: NarrativeCase,
    pack: CanonicalEvidencePack,
    artifact: ExecutionArtifactRef,
    artifact_rows: tuple[dict[str, object], ...],
    chat_client: LocalJsonChatClient,
    backend: VllmLatentRoleModelBackend,
    controller: LatentHandoffController,
    signature: NeuralCompatibilitySignature,
    fixed_parameters: Mapping[str, Any],
    run_id: str,
) -> dict[str, Any]:
    produce_request = _produce_request(
        case=case,
        pack=pack,
        signature=signature,
        latent_steps=int(fixed_parameters["latent_steps"]),
        run_id=run_id,
        suffix="l1",
    )
    produced: LatentProduceResult | None = None
    completion: LatentCompleteResult | None = None
    candidate_quality: dict[str, Any] | None = None
    released = False
    failure = ""
    try:
        produced = backend.produce(produce_request)
        controller.validate_produced_ref(produce_request, produced)
        complete_request = _complete_request(
            case=case,
            pack=pack,
            artifact=artifact,
            ref_id=produced.ref.ref_id,
            signature=signature,
            fixed_parameters=fixed_parameters,
            run_id=run_id,
            suffix="l1",
        )
        completion = backend.complete(complete_request)
        controller.validate_completion_forward(
            ref=produced.ref,
            request=complete_request,
            completion=completion,
        )
        candidate_quality = _evaluate_claim_text(
            completion.text,
            case=case,
            pack=pack,
            artifact=artifact,
            artifact_rows=artifact_rows,
        )
        if not candidate_quality["parse_ok"] or not candidate_quality["validator_ok"]:
            failure = "latent_output_validation_failed"
    except Exception as exc:  # noqa: BLE001 - deterministic C0 fallback.
        failure = _safe_error(exc)
    finally:
        if produced is not None:
            try:
                backend.release(produced.ref.ref_id)
                released = True
            except Exception:  # noqa: BLE001 - retained below as release failure.
                failure = failure or "latent_release_failed"

    if not failure and produced is not None and completion is not None:
        assert candidate_quality is not None
        return {
            "ok": True,
            "latent_success": True,
            "fallback_used": False,
            "generation_path": "latent",
            "model_call_count": 2,
            "producer": _producer_receipt(produce_request, produced),
            "consumer": _consumer_receipt(completion),
            "quality": candidate_quality,
            "visible_evidence_bytes": 0,
            "visible_evidence_tokens": completion.prompt_tokens_equivalent,
            "text_handoff_bytes": 0,
            "text_handoff_completion_tokens": 0,
            "tensor_bytes": produced.ref.tensor_bytes,
            "mechanism": _mechanism_receipt(
                produced=produced,
                completion=completion,
                released=released,
            ),
        }

    fallback = _run_c0(
        case=case,
        pack=pack,
        artifact=artifact,
        artifact_rows=artifact_rows,
        chat_client=chat_client,
        fixed_parameters=fixed_parameters,
    )
    return {
        **fallback,
        "latent_success": False,
        "fallback_used": True,
        "generation_path": "text_fallback",
        "fallback_reason": failure or "latent_consumer_failed",
        "model_call_count": (
            int(fallback["model_call_count"])
            + int(produced is not None)
            + int(completion is not None)
        ),
        "producer": (
            {} if produced is None else _producer_receipt(produce_request, produced)
        ),
        "consumer": (
            {} if completion is None else _consumer_receipt(completion)
        ),
        "tensor_bytes": 0 if produced is None else produced.ref.tensor_bytes,
        "mechanism": _mechanism_receipt(
            produced=produced,
            completion=completion,
            released=released,
        ),
    }


def _run_n1(
    *,
    case: NarrativeCase,
    pack: CanonicalEvidencePack,
    artifact: ExecutionArtifactRef,
    artifact_rows: tuple[dict[str, object], ...],
    chat_client: LocalJsonChatClient,
    backend: VllmLatentRoleModelBackend,
    controller: LatentHandoffController,
    signature: NeuralCompatibilitySignature,
    fixed_parameters: Mapping[str, Any],
    run_id: str,
) -> dict[str, Any]:
    produce_request = _produce_request(
        case=case,
        pack=pack,
        signature=signature,
        latent_steps=int(fixed_parameters["latent_steps"]),
        run_id=run_id,
        suffix="n1",
    )
    produced: LatentProduceResult | None = None
    unexpected_completion: LatentCompleteResult | None = None
    rejection_reason = ""
    released = False
    try:
        produced = backend.produce(produce_request)
        controller.validate_produced_ref(produce_request, produced)
        incompatible_digest = sha256_digest({
            "compatible": signature.compatibility_digest,
            "negative": "position_contract_changed",
        })
        request = _complete_request(
            case=case,
            pack=pack,
            artifact=artifact,
            ref_id=produced.ref.ref_id,
            signature=signature,
            fixed_parameters=fixed_parameters,
            run_id=run_id,
            suffix="n1",
            compatibility_digest=incompatible_digest,
        )
        try:
            unexpected_completion = backend.complete(request)
            rejection_reason = "negative_completion_unexpectedly_forwarded"
        except Exception as exc:  # noqa: BLE001 - expected negative response.
            rejection_reason = _safe_error(exc)
    except Exception as exc:  # noqa: BLE001 - deterministic C0 fallback.
        rejection_reason = _safe_error(exc)
    finally:
        if produced is not None:
            try:
                backend.release(produced.ref.ref_id)
                released = True
            except Exception:  # noqa: BLE001 - captured in mechanism verdict.
                rejection_reason = rejection_reason or "latent_release_failed"
    fallback = _run_c0(
        case=case,
        pack=pack,
        artifact=artifact,
        artifact_rows=artifact_rows,
        chat_client=chat_client,
        fixed_parameters=fixed_parameters,
    )
    pre_forward_rejected = bool(
        rejection_reason == "latent_model_incompatible"
        and unexpected_completion is None
    )
    return {
        **fallback,
        "latent_success": False,
        "fallback_used": True,
        "generation_path": "negative_gate_c0_fallback",
        "fallback_reason": rejection_reason,
        "model_call_count": int(fallback["model_call_count"]) + int(
            produced is not None
        ),
        "producer": (
            {} if produced is None else _producer_receipt(produce_request, produced)
        ),
        "consumer": (
            {}
            if unexpected_completion is None
            else _consumer_receipt(unexpected_completion)
        ),
        "tensor_bytes": 0 if produced is None else produced.ref.tensor_bytes,
        "mechanism": {
            **_mechanism_receipt(
                produced=produced,
                completion=unexpected_completion,
                released=released,
            ),
            "negative_signature_changed": produced is not None,
            "pre_forward_rejected": pre_forward_rejected,
            "rejection_reason": rejection_reason,
        },
    }


def _build_evidence_pack(
    case: NarrativeCase,
    sources: tuple[SourceDocument, ...],
) -> CanonicalEvidencePack:
    selected_sources = _case_sources(case, sources)
    selected_source_ids = {source.item_id for source in selected_sources}
    if any(
        not set(fact.source_item_ids) <= selected_source_ids
        for fact in case.required_facts
    ):
        raise NativeLatentExperimentError("experiment_fact_source_unauthorized")
    policy_version = case.manifest_schema_version.rsplit(".", 1)[-1]
    if policy_version not in {"v1", "v2", "v3", "v4", "v5", "v6"}:
        raise NativeLatentExperimentError("experiment_manifest_schema_invalid")
    semantic_contexts: list[EvidenceItem] = []
    lexical_hints: list[EvidenceItem] = []
    for index, source in enumerate(selected_sources):
        item = EvidenceItem(
            item_id=source.item_id,
            bucket=source.bucket,
            locator=TextSpanLocator(
                source_doc_hash=source.content_hash,
                canonical_text_id=source.item_id,
                start_char=0,
                end_char=len(source.text),
                extractor_version=f"latent-holdout-{policy_version}",
            ),
            rendered_text=source.text,
            source_name=source.path.as_posix(),
            rank=index,
            score=1.0 / (index + 1),
        )
        if source.bucket == "semantic_context":
            semantic_contexts.append(item)
        else:
            lexical_hints.append(item)
    return CanonicalEvidencePack(
        pack_id=f"pack-{case.case_id}",
        task_id=case.case_id,
        source_doc_hashes=tuple(
            source.content_hash for source in selected_sources
        ),
        semantic_contexts=tuple(semantic_contexts),
        lexical_hints=tuple(lexical_hints),
        budget_meta={
            "policy": f"latent_narrative_holdout_{policy_version}",
            "selected_evidence_bytes": sum(
                len(source.text.encode("utf-8"))
                for source in selected_sources
            ),
        },
    )


def _case_sources(
    case: NarrativeCase,
    sources: tuple[SourceDocument, ...],
) -> tuple[SourceDocument, ...]:
    if not case.source_item_ids:
        return sources
    source_by_id = {source.item_id: source for source in sources}
    if len(source_by_id) != len(sources):
        raise NativeLatentExperimentError("experiment_sources_invalid")
    try:
        return tuple(source_by_id[item_id] for item_id in case.source_item_ids)
    except KeyError as exc:
        raise NativeLatentExperimentError(
            "experiment_case_source_unknown"
        ) from exc


def _verified_artifact(
    case: NarrativeCase,
    pack: CanonicalEvidencePack,
) -> tuple[ExecutionArtifactRef, tuple[dict[str, object], ...]]:
    rows = ({
        "case_id": case.case_id,
        "evidence_pack_hash": pack.pack_hash,
        "source_item_ids": [item.item_id for item in _evidence_items(pack)],
        "analysis_status": "verified_scope_only",
    },)
    payload = stable_json_dumps(rows)
    artifact = ExecutionArtifactRef(
        artifact_id=f"artifact-{case.case_id}",
        task_id=case.case_id,
        step_id="execute",
        artifact_type="json",
        root_id="experiment-in-memory",
        relpath=f"{case.case_id}.json",
        blob_hash=sha256_digest(payload),
        size_bytes=len(payload.encode("utf-8")),
        produced_by="executor",
        verification_state=RefStatus.VERIFIED,
        metadata={
            "session_id": f"session-{case.case_id}",
            "attempt_id": f"attempt-{case.case_id}",
            "schema_version": "statebus.latent_holdout_artifact.v1",
        },
    )
    return artifact, rows


def _retriever_messages(
    case: NarrativeCase,
    pack: CanonicalEvidencePack,
) -> tuple[dict[str, str], ...]:
    return (
        {
            "role": "system",
            "content": (
                "You are the StateBus Retriever. Read only the selected offline "
                "evidence. Preserve causal chains, cross-source relationships, "
                "branch triggers, time qualifiers, exceptions, and risk ordering. "
                "Ground every observation in supplied evidence item IDs and put "
                "the task's decisive conclusion first. Keep analysis to one "
                "paragraph of no more than 55 words. Return only JSON with keys "
                "analysis and cited_item_ids."
            ),
        },
        {
            "role": "user",
            "content": (
                "Task contract:\n"
                + stable_json_dumps(case.generation_payload())
                + "\n\nSelected evidence:\n"
                + _render_selected_evidence(pack)
                + "\n\nReturn the concise JSON handoff now."
            ),
        },
    )


def _summarizer_messages(
    *,
    case: NarrativeCase,
    pack: CanonicalEvidencePack,
    artifact: ExecutionArtifactRef,
    handoff_kind: str,
    handoff_text: str,
) -> tuple[dict[str, str], ...]:
    return (
        {
            "role": "system",
            "content": _summarizer_system_prompt(),
        },
        {
            "role": "user",
            "content": _summary_prompt(
                case=case,
                pack=pack,
                artifact=artifact,
                handoff_kind=handoff_kind,
                handoff_text=handoff_text,
                marker=False,
            ),
        },
    )


def _summarizer_system_prompt() -> str:
    return (
        "You are the StateBus Summarizer. Return only the requested "
        "ClaimSet JSON. State factual conclusions compactly, preserve "
        "qualifiers and exceptions, cite only supplied evidence item IDs "
        "and compact locators, and never invent unavailable facts."
    )


def _summary_prompt(
    *,
    case: NarrativeCase,
    pack: CanonicalEvidencePack,
    artifact: ExecutionArtifactRef,
    handoff_kind: str,
    handoff_text: str,
    marker: bool,
) -> str:
    base = (
        "Task contract:\n"
        + stable_json_dumps(case.generation_payload())
        + "\n\nVerified artifact:\n"
        + stable_json_dumps({
            "artifact_id": artifact.artifact_id,
            "verification_state": artifact.verification_state.value,
            "artifact_type": artifact.artifact_type,
            "schema_version": artifact.metadata["schema_version"],
        })
        + "\n\nAnchors (identity and lineage only; no answer summaries):\n"
        + stable_json_dumps(_anchor_view(pack))
        + f"\n\nHandoff kind: {handoff_kind}\n"
        + _task_mode_guidance(case.task_mode)
    )
    if marker:
        return (
            base
            + "Engine-local latent handoff: "
            + LATENT_MARKER
            + "\nUse the opaque latent state with the anchors and verified artifact. "
            + _claim_output_instruction()
        )
    if handoff_text:
        base += "Handoff content:\n" + handoff_text + "\n"
    else:
        base += "No additional evidence or analysis is visible in this lane.\n"
    return base + _claim_output_instruction()


def _task_mode_guidance(task_mode: str) -> str:
    if task_mode == "long_document_causal_analysis":
        return (
            "Task-mode structure: follow the dimensions in the task's stated "
            "order, using exactly one claim per requested dimension. Keep causal "
            "factors, timed response, and later relief conditions distinct; do "
            "not substitute a different valid action.\n"
        )
    if task_mode == "cross_document_evidence_synthesis":
        return (
            "Task-mode structure: preserve source-specific qualifiers and make "
            "the cross-document relationship explicit. A requested combined "
            "conclusion must cite both contributing documents. Use exactly one "
            "claim per requested dimension.\n"
        )
    if task_mode == "conditional_plan_switch":
        return (
            "Task-mode structure: distinguish signed current observations from "
            "branch thresholds. State the selected branch, immediate action, "
            "positive transition, and fail-closed fallback separately when the "
            "task requests them, with exactly one claim per dimension.\n"
        )
    return ""


def _claim_output_instruction() -> str:
    return (
        "Return exactly 4 cited claims as ClaimSet JSON. Keep every claim_text "
        "to one sentence of at most 40 words. Cite only the evidence needed for "
        "each claim and include a matching compact locator for every cited item. "
        "A conclusion that combines sources must cite all of them. Preserve specific names, values, "
        "and month or quarter qualifiers instead of replacing them with generic "
        "labels. Set supporting_artifact_ref_ids to [], numeric_fields to {}, "
        "and uncertainty_note to an empty string."
    )


def _produce_request(
    *,
    case: NarrativeCase,
    pack: CanonicalEvidencePack,
    signature: NeuralCompatibilitySignature,
    latent_steps: int,
    run_id: str,
    suffix: str,
) -> LatentProduceRequest:
    return LatentProduceRequest(
        request_id=f"{run_id}-{case.case_id}-{suffix}-produce",
        task_id=case.case_id,
        source_step_id="retrieve",
        producer_role="retriever",
        consumer_role="summarizer",
        messages=_retriever_messages(case, pack),
        latent_steps=latent_steps,
        alignment_method=signature.alignment_method,
        anchor=_latent_anchor(pack),
        ttl_s=300,
        compatibility_signature=signature,
    )


def _complete_request(
    *,
    case: NarrativeCase,
    pack: CanonicalEvidencePack,
    artifact: ExecutionArtifactRef,
    ref_id: str,
    signature: NeuralCompatibilitySignature,
    fixed_parameters: Mapping[str, Any],
    run_id: str,
    suffix: str,
    compatibility_digest: str = "",
) -> LatentCompleteRequest:
    rendered_prompt = _summary_prompt(
        case=case,
        pack=pack,
        artifact=artifact,
        handoff_kind="engine_local_latent",
        handoff_text="",
        marker=True,
    )
    return LatentCompleteRequest(
        request_id=f"{run_id}-{case.case_id}-{suffix}-complete",
        latent_ref_id=ref_id,
        rendered_prompt=rendered_prompt,
        response_schema=_claim_set_schema(case, pack, artifact),
        temperature=0.0,
        max_tokens=int(fixed_parameters["summarizer_max_tokens"]),
        seed=int(fixed_parameters["seed"]),
        expected_compatibility_digest=(
            compatibility_digest or signature.compatibility_digest
        ),
        expected_anchor=_latent_anchor(pack),
        messages=(
            {"role": "system", "content": _summarizer_system_prompt()},
            {"role": "user", "content": rendered_prompt},
        ),
    )


def _claim_set_schema(
    case: NarrativeCase,
    pack: CanonicalEvidencePack,
    artifact: ExecutionArtifactRef,
) -> dict[str, Any]:
    item_ids = [item.item_id for item in _evidence_items(pack)]
    locators = sorted({_compact_locator(item) for item in _evidence_items(pack)})
    claim = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claim_id": {"type": "string"},
            "claim_text": {"type": "string"},
            "claim_type": {
                "type": "string",
                "enum": ["fact", "inference", "risk"],
            },
            "supporting_evidence_item_ids": {
                "type": "array",
                "items": {"type": "string", "enum": item_ids},
            },
            "supporting_artifact_ref_ids": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [artifact.artifact_id],
                },
            },
            "citation_locators": {
                "type": "array",
                "items": {"type": "string", "enum": locators},
            },
            "numeric_fields": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
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
            "claim_set_id": {"type": "string"},
            "task_id": {"type": "string", "const": case.case_id},
            "claims": {
                "type": "array",
                "items": claim,
            },
            "status": {"type": "string", "const": "ready"},
            "schema_version": {
                "type": "string",
                "const": "statebus.claim_set.v1",
            },
        },
        "required": [
            "claim_set_id",
            "task_id",
            "claims",
            "status",
            "schema_version",
        ],
    }


def _retriever_schema(items: tuple[EvidenceItem, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "analysis": {"type": "string"},
            "cited_item_ids": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [item.item_id for item in items],
                },
            },
        },
        "required": ["analysis", "cited_item_ids"],
    }


def _parse_claim_set(text: str) -> ClaimSet:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NativeLatentExperimentError("claim_set_json_invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("claims"), list):
        raise NativeLatentExperimentError("claim_set_shape_invalid")
    claims = tuple(
        Claim(
            claim_id=str(item["claim_id"]),
            claim_text=str(item["claim_text"]),
            claim_type=str(item["claim_type"]),
            supporting_evidence_item_ids=tuple(
                str(value)
                for value in item.get("supporting_evidence_item_ids", ())
            ),
            supporting_artifact_ref_ids=tuple(
                str(value)
                for value in item.get("supporting_artifact_ref_ids", ())
            ),
            citation_locators=tuple(
                str(value) for value in item.get("citation_locators", ())
            ),
            numeric_fields={
                str(key): float(value)
                for key, value in dict(item.get("numeric_fields", {})).items()
            },
            uncertainty_note=str(item.get("uncertainty_note", "")),
            status=str(item.get("status", "ready")),
        )
        for item in payload["claims"]
        if isinstance(item, dict)
    )
    return ClaimSet(
        claim_set_id=str(payload["claim_set_id"]),
        task_id=str(payload["task_id"]),
        claims=claims,
        status=ClaimSetStatus(str(payload["status"])),
        schema_version=str(payload["schema_version"]),
    )


def _evaluate_claim_text(
    text: str,
    *,
    case: NarrativeCase,
    pack: CanonicalEvidencePack,
    artifact: ExecutionArtifactRef,
    artifact_rows: tuple[dict[str, object], ...],
) -> dict[str, Any]:
    try:
        claim_set = _parse_claim_set(text)
    except Exception as exc:  # noqa: BLE001 - post-generation scoring.
        return {
            **_empty_quality(case),
            "parse_ok": False,
            "parse_error": _safe_error(exc),
            "output_hash": sha256_digest(text),
        }
    report = ClaimSetValidator().validate(
        claim_set,
        evidence_pack=pack,
        verified_artifacts={artifact.artifact_id: (artifact, list(artifact_rows))},
        current_task_id=case.case_id,
        current_session_id=f"session-{case.case_id}",
        evidence_session_id=f"session-{case.case_id}",
    )
    fact_verdicts = tuple(
        _score_required_fact(fact, claim_set)
        for fact in case.required_facts
    )
    passed_count = sum(
        bool(verdict["passed"] and report.ok) for verdict in fact_verdicts
    )
    return {
        "parse_ok": True,
        "validator_ok": report.ok,
        "validator_status": report.status.value,
        "validator_errors": list(report.errors),
        "claim_set_hash": claim_set.claim_set_hash,
        "claim_count": len(claim_set.claims),
        "fact_passed_count": passed_count,
        "fact_total_count": len(case.required_facts),
        "all_required_facts_passed": passed_count == len(case.required_facts),
        "fact_verdicts": list(fact_verdicts),
        "output_hash": sha256_digest(text),
    }


def _score_required_fact(
    fact: RequiredFact,
    claim_set: ClaimSet,
) -> dict[str, Any]:
    matching_claim_ids: list[str] = []
    cited = False
    for claim in claim_set.claims:
        term_groups_passed = all(
            any(_term_matches(term, claim.claim_text) for term in group)
            for group in fact.term_groups
        )
        if not term_groups_passed:
            continue
        matching_claim_ids.append(claim.claim_id)
        if set(fact.source_item_ids) <= set(
            claim.supporting_evidence_item_ids
        ):
            cited = True
    return {
        "fact_id": fact.fact_id,
        "terms_passed": bool(matching_claim_ids),
        "citation_passed": cited,
        "passed": bool(matching_claim_ids and cited),
        "matching_claim_ids": matching_claim_ids,
    }


def _empty_quality(case: NarrativeCase) -> dict[str, Any]:
    return {
        "parse_ok": False,
        "validator_ok": False,
        "fact_passed_count": 0,
        "fact_total_count": len(case.required_facts),
        "all_required_facts_passed": False,
        "fact_verdicts": [],
    }


def _producer_receipt(
    request: LatentProduceRequest,
    produced: LatentProduceResult,
) -> dict[str, object]:
    ref = produced.ref
    return {
        "request_id": request.request_id,
        "request_hash": sha256_digest(request.canonical_payload()),
        "messages_hash": sha256_digest(request.messages),
        "messages_bytes": _messages_bytes(request.messages),
        "ref_id": ref.ref_id,
        "status": ref.status.value,
        "producer_role": ref.producer_role,
        "consumer_role": ref.consumer_role,
        "source_evidence_pack_hash": ref.source_evidence_pack_hash,
        "anchor_item_ids": list(ref.anchor_item_ids),
        "anchor_locator_digest": ref.anchor_locator_digest,
        "model_revision": ref.model_revision,
        "compatibility_digest": ref.compatibility_digest,
        "shape": list(ref.shape),
        "dtype": ref.dtype,
        "tensor_bytes": ref.tensor_bytes,
        "tensor_digest": ref.tensor_digest,
        "producer_pid": ref.producer_pid,
        "engine_id": ref.engine_id,
        "created_at_ns": ref.created_at_ns,
        "expires_at_ns": ref.expires_at_ns,
        "captured_step_count": produced.captured_step_count,
        "recurrence_injection_count": produced.recurrence_injection_count,
        "internal_scheduler_sample_count": (
            produced.internal_scheduler_sample_count
        ),
        "telemetry": latent_telemetry_audit_view(produced.telemetry),
    }


def _consumer_receipt(completion: LatentCompleteResult) -> dict[str, object]:
    return {
        "text": completion.text,
        "text_hash": sha256_digest(completion.text),
        "text_bytes": len(completion.text.encode("utf-8")),
        "consumed_ref_id": completion.consumed_ref_id,
        "consumer_forward_observed": completion.consumer_forward_observed,
        "forward_proof": (
            None
            if completion.forward_proof is None
            else completion.forward_proof.canonical_payload()
        ),
        "prompt_embed_shape": list(completion.prompt_embed_shape),
        "prompt_tokens_equivalent": completion.prompt_tokens_equivalent,
        "completion_tokens": completion.completion_tokens,
        "telemetry": latent_telemetry_audit_view(completion.telemetry),
    }


def _mechanism_receipt(
    *,
    produced: LatentProduceResult | None,
    completion: LatentCompleteResult | None,
    released: bool,
) -> dict[str, object]:
    return {
        "latent_attempted": produced is not None,
        "latent_committed": bool(
            produced is not None and produced.ref.status.value == "committed"
        ),
        "hidden_capture_complete": bool(
            produced is not None
            and produced.captured_step_count == produced.ref.latent_step_count
        ),
        "recurrence_injection_count": (
            0 if produced is None else produced.recurrence_injection_count
        ),
        "tensor_shape": (
            [] if produced is None else list(produced.ref.shape)
        ),
        "tensor_bytes": 0 if produced is None else produced.ref.tensor_bytes,
        "tensor_digest": "" if produced is None else produced.ref.tensor_digest,
        "latent_consumed": bool(
            completion is not None
            and completion.consumer_forward_observed
            and completion.forward_proof is not None
        ),
        "consumer_forward_event_id": (
            ""
            if completion is None or completion.forward_proof is None
            else completion.forward_proof.event_id
        ),
        "consumer_worker_pid": (
            0
            if completion is None or completion.forward_proof is None
            else completion.forward_proof.worker_pid
        ),
        "released": released,
    }


def _summarize_experiment(
    *,
    definition: ExperimentDefinition,
    sample_index: tuple[Mapping[str, Any], ...],
    output_root: Path,
) -> dict[str, Any]:
    raw_records = {
        (str(sample["case_id"]), str(sample["lane"])): json.loads(
            (output_root / str(sample["artifact"])).read_text(encoding="utf-8")
        )
        for sample in sample_index
    }
    lanes: dict[str, dict[str, Any]] = {}
    for lane in LANES:
        records = tuple(
            record
            for (_case_id, record_lane), record in raw_records.items()
            if record_lane == lane
        )
        lanes[lane] = {
            "sample_count": len(records),
            "ok_count": sum(bool(record.get("ok")) for record in records),
            "fact_passed_count": sum(
                int(dict(record.get("quality", {})).get("fact_passed_count", 0))
                for record in records
            ),
            "fact_total_count": sum(
                int(dict(record.get("quality", {})).get("fact_total_count", 0))
                for record in records
            ),
            "validator_pass_count": sum(
                bool(dict(record.get("quality", {})).get("validator_ok"))
                for record in records
            ),
            "latent_success_count": sum(
                bool(record.get("latent_success")) for record in records
            ),
            "fallback_count": sum(
                bool(record.get("fallback_used")) for record in records
            ),
            "visible_evidence_bytes": sum(
                int(record.get("visible_evidence_bytes", 0)) for record in records
            ),
            "text_handoff_completion_tokens": sum(
                int(record.get("text_handoff_completion_tokens", 0))
                for record in records
            ),
            "tensor_bytes": sum(
                int(record.get("tensor_bytes", 0)) for record in records
            ),
            "latency_ms": summarize_distribution(tuple(
                float(record.get("elapsed_ms", 0.0)) for record in records
            )),
        }
    categories: dict[str, dict[str, dict[str, int]]] = {}
    for category in sorted({case.category for case in definition.cases}):
        category_case_ids = {
            case.case_id for case in definition.cases if case.category == category
        }
        category_lanes: dict[str, dict[str, int]] = {}
        for lane in LANES:
            records = tuple(
                record
                for (case_id, record_lane), record in raw_records.items()
                if record_lane == lane and case_id in category_case_ids
            )
            category_lanes[lane] = {
                "sample_count": len(records),
                "ok_count": sum(bool(record.get("ok")) for record in records),
                "fact_passed_count": sum(
                    int(dict(record.get("quality", {})).get(
                        "fact_passed_count", 0
                    ))
                    for record in records
                ),
                "fact_total_count": sum(
                    int(dict(record.get("quality", {})).get(
                        "fact_total_count", 0
                    ))
                    for record in records
                ),
            }
        categories[category] = category_lanes
    thresholds = definition.quality_thresholds
    c0 = lanes["C0"]["fact_passed_count"]
    t0 = lanes["T0"]["fact_passed_count"]
    a0 = lanes["A0"]["fact_passed_count"]
    l1 = lanes["L1"]["fact_passed_count"]
    l1_mechanism_count = sum(
        bool(record.get("latent_success"))
        and bool(dict(record.get("mechanism", {})).get("hidden_capture_complete"))
        and int(dict(record.get("mechanism", {})).get(
            "recurrence_injection_count", 0
        )) > 0
        and bool(dict(record.get("mechanism", {})).get("latent_consumed"))
        and bool(dict(record.get("mechanism", {})).get("released"))
        for (case_id, lane), record in raw_records.items()
        if lane == "L1" and case_id
    )
    n1_pre_forward_count = sum(
        bool(dict(record.get("mechanism", {})).get("pre_forward_rejected"))
        for (_case_id, lane), record in raw_records.items()
        if lane == "N1"
    )
    executed_lanes = tuple(
        lane for lane in LANES if lanes[lane]["sample_count"] > 0
    )
    complete_matrix = executed_lanes == LANES
    criteria = {
        "c0_task_solvable": c0 >= int(thresholds["c0_min_passed_facts"]),
        "t0_quality_floor": t0 >= int(thresholds["t0_min_passed_facts"]),
        "l1_quality_floor": l1 >= int(thresholds["l1_min_passed_facts"]),
        "l1_within_c0_deficit": (
            c0 - l1 <= int(thresholds["l1_max_fact_deficit_vs_c0"])
        ),
        "l1_not_below_t0": l1 >= t0,
        "l1_gain_over_a0": (
            l1 - a0 >= int(thresholds["l1_min_fact_gain_vs_a0"])
        ),
        "l1_mechanism_all_cases": (
            l1_mechanism_count
            >= int(thresholds["l1_required_mechanism_cases"])
        ),
        "n1_pre_forward_rejection_all_cases": (
            n1_pre_forward_count
            >= int(thresholds["n1_required_pre_forward_rejections"])
        ),
        "n1_never_latent_success": lanes["N1"]["latent_success_count"] == 0,
    }
    if complete_matrix:
        interpretation = _interpretation(criteria)
    elif executed_lanes == ("C0",):
        interpretation = (
            "c0_preflight_passed"
            if criteria["c0_task_solvable"]
            else "task_design_failed_c0_not_solvable"
        )
    else:
        interpretation = "partial_matrix_completed"
    return {
        "lanes": lanes,
        "categories": categories,
        "executed_lanes": list(executed_lanes),
        "complete_matrix": complete_matrix,
        "l1_mechanism_case_count": l1_mechanism_count,
        "n1_pre_forward_rejection_count": n1_pre_forward_count,
        "criteria": criteria,
        "quality_matrix_passed": complete_matrix and all(criteria.values()),
        "interpretation": interpretation,
    }


def _interpretation(criteria: Mapping[str, bool]) -> str:
    if not criteria["c0_task_solvable"]:
        return "task_design_failed_c0_not_solvable"
    if not criteria["l1_mechanism_all_cases"]:
        return "native_latent_mechanism_incomplete"
    if not criteria["l1_gain_over_a0"]:
        return "workload_has_no_demonstrated_latent_need"
    if not (
        criteria["l1_quality_floor"]
        and criteria["l1_within_c0_deficit"]
        and criteria["l1_not_below_t0"]
    ):
        return "native_latent_quality_regression"
    if not criteria["n1_pre_forward_rejection_all_cases"]:
        return "negative_gate_incomplete"
    return "native_latent_quality_and_mechanism_matrix_passed"


def _environment_payload(
    *,
    config: ExperimentConfig,
    signature: NeuralCompatibilitySignature,
    health: Mapping[str, Any],
) -> dict[str, object]:
    return {
        "git_sha": _git_sha(config.project_root),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {
            name: _package_version(name)
            for name in ("torch", "transformers", "vllm")
        },
        "base_url": config.base_url,
        "compatibility_signature": signature.canonical_payload(),
        "compatibility_digest": signature.compatibility_digest,
        "health": dict(health),
    }


def _write_progress(payload: Mapping[str, Any], output_root: Path) -> None:
    progress = {
        "schema_version": "statebus.native_latent_experiment_progress.v1",
        "run_id": payload["run_id"],
        "requested_lanes": list(payload.get("requested_lanes", ())),
        "completed_sample_count": len(payload["samples"]),
        "samples": list(payload["samples"]),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (output_root / "progress.json").write_text(
        stable_json_dumps(progress) + "\n",
        encoding="utf-8",
    )


def _write_checksums(output_root: Path) -> None:
    paths = sorted(
        path
        for path in output_root.rglob("*")
        if path.is_file() and path.name != "checksums.sha256"
    )
    lines = [
        f"{sha256_digest(path.read_bytes())}  {path.relative_to(output_root).as_posix()}"
        for path in paths
    ]
    (output_root / "checksums.sha256").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _render_selected_evidence(pack: CanonicalEvidencePack) -> str:
    sections = []
    for item in _evidence_items(pack):
        sections.append(
            "[evidence_item_id="
            + item.item_id
            + "; locator="
            + _compact_locator(item)
            + "; source="
            + item.source_name
            + "]\n"
            + item.rendered_text
        )
    return "\n\n".join(sections)


def _evidence_items(pack: CanonicalEvidencePack) -> tuple[EvidenceItem, ...]:
    return tuple(
        item
        for bucket in (
            pack.hard_facts,
            pack.structured_evidence,
            pack.semantic_contexts,
            pack.lexical_hints,
            pack.conflicts,
        )
        for item in bucket
    )


def _anchor_view(pack: CanonicalEvidencePack) -> list[dict[str, object]]:
    return [
        {
            "item_id": item.item_id,
            "bucket": item.bucket,
            "locator": _compact_locator(item),
            "source_name": item.source_name,
            "source_doc_hash": getattr(item.locator, "source_doc_hash", ""),
        }
        for item in _evidence_items(pack)
    ]


def _compact_locator(item: EvidenceItem) -> str:
    locator = item.locator
    if isinstance(locator, TextSpanLocator):
        return f"{locator.canonical_text_id}:{locator.start_char}-{locator.end_char}"
    values = sorted(ClaimSetValidator._locator_values(locator))
    if not values:
        raise NativeLatentExperimentError("experiment_evidence_locator_missing")
    return values[0]


def _latent_anchor(pack: CanonicalEvidencePack) -> LatentAnchor:
    items = _evidence_items(pack)
    return LatentAnchor(
        evidence_pack_hash=pack.pack_hash,
        item_ids=tuple(item.item_id for item in items),
        locator_digest=sha256_digest([
            {"item_id": item.item_id, "locator": item.locator}
            for item in items
        ]),
    )


def _messages_bytes(messages: Sequence[Mapping[str, str]]) -> int:
    return sum(
        len(str(message.get("content", "")).encode("utf-8"))
        for message in messages
    )


def _normalize_text(value: str) -> str:
    return " ".join(_canonical_tokens(value))


def _term_matches(term: str, text: str) -> bool:
    expected = _canonical_tokens(term)
    actual = _canonical_tokens(text)
    if not expected or len(expected) > len(actual):
        return False
    for offset in range(len(actual) - len(expected) + 1):
        window = actual[offset:offset + len(expected)]
        if all(
            _token_forms(left) & _token_forms(right)
            for left, right in zip(expected, window, strict=True)
        ):
            return True
    return False


def _canonical_tokens(value: str) -> tuple[str, ...]:
    tokens = tuple(
        stripped
        for token in re.findall(r"[a-z0-9.]+", value.lower())
        if (stripped := token.strip("."))
    )
    canonical: list[str] = []
    negative_auxiliaries = {
        "can",
        "could",
        "did",
        "do",
        "does",
        "should",
        "will",
        "would",
    }
    for index, token in enumerate(tokens):
        if token == "cannot":
            canonical.append("not")
            continue
        if (
            token in negative_auxiliaries
            and index + 1 < len(tokens)
            and tokens[index + 1] == "not"
        ):
            continue
        canonical.append(token)
    return tuple(canonical)


def _token_forms(token: str) -> frozenset[str]:
    forms = {token}
    if len(token) > 3 and token.endswith("s"):
        forms.add(token[:-1])
    if len(token) > 4 and token.endswith("ies"):
        forms.add(token[:-3] + "y")
    if len(token) > 4 and token.endswith("ed"):
        forms.add(token[:-1])
        forms.add(token[:-2])
    if len(token) > 5 and token.endswith("ing"):
        forms.add(token[:-3])
        forms.add(token[:-3] + "e")
    return frozenset(forms)


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, (LatentBackendError, VllmLatentClientError)):
        return exc.error_code
    if isinstance(exc, NativeLatentExperimentError):
        return str(exc)
    return type(exc).__name__


def _git_sha(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return ""
