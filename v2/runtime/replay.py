from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path

from v2.contracts import (
    CanonicalTaskSpec,
    CompatibilityVerdict,
    CompilerStatus,
    PlannerHandoff,
    RefKind,
    ReplayClass,
    RuntimeCompatibilitySignature,
    TaskCompilerResult,
)
from v2.memory import MemoryCommit, MemoryIndexStore
from v2.refs import CanonicalEvidencePack, ExecutionArtifactRef, HydrateManifest
from v2.runtime.ledger import ReplayLedgerEntry
from v2.utils import sha256_digest, stable_json_dumps


_BENCHMARK_ONLY_ARGUMENT_KEYS = {"quality_checks", "reuse_contract", "depends_on_rounds"}
@dataclass(frozen=True)
class ReplayPolicy:
    allow_assist: bool = True
    allow_validated_replay: bool = False
    allow_exact_replay: bool = False


@dataclass(frozen=True)
class ReplayCandidate:
    candidate_id: str
    canonical_task_spec: CanonicalTaskSpec
    input_artifact_hashes: tuple[str, ...]
    runtime_signature: RuntimeCompatibilitySignature
    output_contract_version: str
    verified_output: bool
    code_template_version: str = ""
    extractor_version: str = ""

    @property
    def exact_key(self) -> str:
        return replay_exact_key(
            canonical_task_spec=self.canonical_task_spec,
            input_artifact_hashes=self.input_artifact_hashes,
            runtime_signature=self.runtime_signature,
            code_template_version=self.code_template_version,
            extractor_version=self.extractor_version,
            output_contract_version=self.output_contract_version,
        )


@dataclass(frozen=True)
class ReplayDecision:
    replay_class: ReplayClass
    reason: str
    candidate_id: str = ""
    compatibility_verdict: CompatibilityVerdict = CompatibilityVerdict.INCOMPATIBLE
    skipped_step_count: int = 0
    degraded: bool = False


@dataclass(frozen=True)
class HistoryReplayRecord:
    memory_commit: MemoryCommit
    artifact_ref: ExecutionArtifactRef
    replay_ledger_entry: ReplayLedgerEntry
    output_path: Path
    runtime_root: Path


@dataclass(frozen=True)
class ReplayCandidateSelection:
    candidate: ReplayCandidate
    record: HistoryReplayRecord
    selection_reason: str
    compatibility_verdict: CompatibilityVerdict


@dataclass
class ReplayAdmissibilityGate:
    def decide(
        self,
        *,
        compiler_result: TaskCompilerResult,
        policy: ReplayPolicy,
        candidate: ReplayCandidate | None,
        runtime_signature: RuntimeCompatibilitySignature,
        input_artifact_hashes: tuple[str, ...],
        output_contract_version: str,
    ) -> ReplayDecision:
        if candidate is None:
            return ReplayDecision(
                replay_class=ReplayClass.DISALLOWED,
                reason="no_replay_candidate",
            )
        compatibility = runtime_signature.compare(candidate.runtime_signature)
        exact_key = ""
        if compiler_result.canonical_task_spec is not None:
            exact_key = replay_exact_key(
                canonical_task_spec=compiler_result.canonical_task_spec,
                input_artifact_hashes=input_artifact_hashes,
                runtime_signature=runtime_signature,
                code_template_version=candidate.code_template_version,
                extractor_version=candidate.extractor_version,
                output_contract_version=output_contract_version,
            )
        if (
            policy.allow_exact_replay
            and compiler_result.status == CompilerStatus.COMPILED
            and compiler_result.canonical_task_spec is not None
            and candidate.verified_output
            and compatibility == CompatibilityVerdict.COMPATIBLE
            and output_contract_version == candidate.output_contract_version
            and exact_key == candidate.exact_key
        ):
            return ReplayDecision(
                replay_class=ReplayClass.EXACT_REPLAY,
                reason="exact_replay_key_match",
                candidate_id=candidate.candidate_id,
                compatibility_verdict=compatibility,
                skipped_step_count=2,
            )
        if (
            policy.allow_validated_replay
            and compiler_result.status == CompilerStatus.COMPILED
            and compiler_result.canonical_task_spec is not None
            and candidate.verified_output
            and validated_replay_contract_compatible(
                current_spec=compiler_result.canonical_task_spec,
                candidate_spec=candidate.canonical_task_spec,
            )
            and output_contract_version == candidate.output_contract_version
            and compatibility != CompatibilityVerdict.INCOMPATIBLE
        ):
            reason = "task_family_and_intent_match"
            if compatibility == CompatibilityVerdict.DEGRADED:
                reason = "runtime_signature_degraded_validated_replay"
            elif exact_key and exact_key != candidate.exact_key:
                reason = "exact_key_mismatch_validated_replay"
            return ReplayDecision(
                replay_class=ReplayClass.VALIDATED_REPLAY,
                reason=reason,
                candidate_id=candidate.candidate_id,
                compatibility_verdict=compatibility,
                skipped_step_count=1,
                degraded=compatibility == CompatibilityVerdict.DEGRADED,
            )
        if policy.allow_assist:
            reason = "memory_assist_only"
            if compatibility == CompatibilityVerdict.INCOMPATIBLE:
                reason = "runtime_signature_incompatible_assist_only"
            elif output_contract_version != candidate.output_contract_version:
                reason = "output_contract_mismatch_assist_only"
            return ReplayDecision(
                replay_class=ReplayClass.ASSIST,
                reason=reason,
                candidate_id=candidate.candidate_id,
                compatibility_verdict=compatibility,
            )
        return ReplayDecision(
            replay_class=ReplayClass.DISALLOWED,
            reason="policy_disallows_reuse",
            candidate_id=candidate.candidate_id,
            compatibility_verdict=compatibility,
        )


def replay_exact_key(
    *,
    canonical_task_spec: CanonicalTaskSpec,
    input_artifact_hashes: tuple[str, ...],
    runtime_signature: RuntimeCompatibilitySignature,
    code_template_version: str,
    extractor_version: str,
    output_contract_version: str,
) -> str:
    return sha256_digest(
        {
            "canonical_task_spec": _replay_spec_payload(canonical_task_spec),
            "input_artifact_hashes": list(input_artifact_hashes),
            "runtime_compatibility_signature": runtime_signature.combined_digest,
            "code_template_version": code_template_version,
            "extractor_version": extractor_version,
            "output_contract_version": output_contract_version,
        }
    )


def planner_handoff_replay_hash(planner_handoff: PlannerHandoff) -> str:
    return sha256_digest(
        {
            "retrieval_objective": planner_handoff.retrieval_objective,
            "planner_plan_payload": planner_handoff.planner_plan_payload,
            "planner_scope_payload": planner_handoff.planner_scope_payload,
            "summary_hint": planner_handoff.summary_hint,
            "schema_version": planner_handoff.schema_version,
        }
    )


def evidence_pack_replay_hash(pack: CanonicalEvidencePack) -> str:
    return sha256_digest(
        {
            "source_doc_hashes": list(pack.source_doc_hashes),
            "hard_facts": [_evidence_item_replay_payload(item) for item in pack.hard_facts],
            "structured_evidence": [_evidence_item_replay_payload(item) for item in pack.structured_evidence],
            "semantic_contexts": [_evidence_item_replay_payload(item) for item in pack.semantic_contexts],
            "lexical_hints": [_evidence_item_replay_payload(item) for item in pack.lexical_hints],
            "conflicts": [_evidence_item_replay_payload(item) for item in pack.conflicts],
            "schema_version": pack.schema_version,
        }
    )


def evidence_execution_input_replay_hash(pack: CanonicalEvidencePack) -> str:
    """Hash evidence content while excluding query-derived ranking observations.

    Planner objectives, lexical routing hints, and retriever scores are useful
    selection/audit data, but they are not stable execution inputs. Exact replay
    remains bound to hydrated evidence content, locators, source document
    hashes, and schema.
    """
    return sha256_digest(
        {
            "source_doc_hashes": list(pack.source_doc_hashes),
            "hard_facts": [_evidence_item_execution_input_payload(item) for item in pack.hard_facts],
            "structured_evidence": [
                _evidence_item_execution_input_payload(item) for item in pack.structured_evidence
            ],
            "semantic_contexts": [
                _evidence_item_execution_input_payload(item) for item in pack.semantic_contexts
            ],
            "conflicts": [_evidence_item_execution_input_payload(item) for item in pack.conflicts],
            "schema_version": pack.schema_version,
        }
    )


def hydrate_manifest_replay_hash(manifest: HydrateManifest) -> str:
    # Dense-state row indices and importance scores describe the current
    # query's carrier layout.  Exact replay is instead bound to the stable
    # hydration surface: source hashes, locators, byte hints, and extractor
    # versions.  Canonical sorting prevents a query-specific candidate order
    # from turning an otherwise identical execution input into a cache miss.
    entries = [
        {
            "stable_key": entry.stable_key,
            "byte_hint": entry.byte_hint,
            "locator": asdict(entry.locator),
        }
        for entry in manifest.entries
    ]
    entries.sort(key=stable_json_dumps)
    return sha256_digest(
        {
            "source_doc_hashes": list(manifest.source_doc_hashes),
            "entries": entries,
            "canonicalizer_version": manifest.canonicalizer_version,
            "extractor_version": manifest.extractor_version,
            "schema_version": manifest.schema_version,
        }
    )


def load_history_replay_candidates(
    *,
    history_roots: tuple[Path, ...],
    target_memory_store: MemoryIndexStore,
) -> dict[str, HistoryReplayRecord]:
    records: dict[str, HistoryReplayRecord] = {}
    for history_root in history_roots:
        source_store = MemoryIndexStore(store_root=history_root / "memory_index")
        source_store.load_persisted_state()
        for record in _history_replay_records(history_root):
            embedding_id = record.memory_commit.memory_ref.embedding_ref_id
            if embedding_id:
                embedding = source_store.embeddings.get(embedding_id)
                if embedding is not None:
                    target_memory_store.put_embedding(embedding)
            target_memory_store.put_commit(record.memory_commit)
            records[record.memory_commit.memory_ref.memory_id] = record
    return records


def _history_replay_records(history_root: Path) -> tuple[HistoryReplayRecord, ...]:
    from v2.state import JsonContractStore

    store = JsonContractStore(history_root)
    memory_commit_dir = history_root / "sidecars" / "memory_commits"
    if not memory_commit_dir.exists():
        return ()
    records: list[HistoryReplayRecord] = []
    for commit_path in sorted(memory_commit_dir.glob("*.json")):
        try:
            payload = json.loads(commit_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        memory_id = str(payload.get("memory_ref", {}).get("memory_id", "")).strip()
        if not memory_id:
            continue
        memory_commit = store.read_memory_commit(memory_id)
        metadata = dict(memory_commit.memory_ref.metadata)
        if memory_commit.memory_ref.commit_status.value != "committed":
            continue
        if not _truthy(metadata.get("replay_ready", False)):
            continue
        if not memory_commit.quality_floor_pass:
            continue
        artifact_ref_id = memory_commit.memory_ref.artifact_ref_id
        if not artifact_ref_id:
            continue
        artifact_ref = _load_history_artifact_ref(store=store, artifact_ref_id=artifact_ref_id)
        if artifact_ref is None or not artifact_ref.replay_ready:
            continue
        ledger_entry = _load_history_ledger_for_memory(store=store, memory_id=memory_id)
        if ledger_entry is None:
            continue
        if not ledger_entry.runtime_signature or not ledger_entry.input_artifact_hashes:
            continue
        if not ledger_entry.output_contract_version:
            continue
        output_path = _matching_history_output_path(
            history_root=history_root,
            store=store,
            artifact_ref=artifact_ref,
            ledger_entry=ledger_entry,
        )
        if output_path is None:
            continue
        record = HistoryReplayRecord(
            memory_commit=memory_commit,
            artifact_ref=artifact_ref,
            replay_ledger_entry=ledger_entry,
            output_path=output_path,
            runtime_root=history_root,
        )
        candidate = history_replay_candidate(record)
        if candidate is None:
            continue
        records.append(record)
    return tuple(records)


def history_replay_candidate(record: HistoryReplayRecord) -> ReplayCandidate | None:
    ledger_entry = record.replay_ledger_entry
    runtime_signature = ledger_entry.runtime_signature
    input_artifact_hashes = ledger_entry.input_artifact_hashes
    if not isinstance(runtime_signature, dict):
        return None
    if not isinstance(input_artifact_hashes, tuple):
        return None
    try:
        signature = RuntimeCompatibilitySignature(
            os_digest=str(runtime_signature["os_digest"]),
            python_digest=str(runtime_signature["python_digest"]),
            dependency_digest=str(runtime_signature["dependency_digest"]),
            tool_registry_digest=str(runtime_signature["tool_registry_digest"]),
            prompt_bundle_digest=str(runtime_signature["prompt_bundle_digest"]),
            extractor_bundle_digest=str(runtime_signature["extractor_bundle_digest"]),
            combined_digest=str(runtime_signature.get("combined_digest", "")),
            schema_version=str(runtime_signature.get("schema_version", "")),
        )
    except KeyError:
        return None
    return ReplayCandidate(
        candidate_id=record.memory_commit.memory_ref.memory_id,
        canonical_task_spec=record.memory_commit.canonical_task_spec,
        input_artifact_hashes=tuple(str(item) for item in input_artifact_hashes),
        runtime_signature=signature,
        output_contract_version=ledger_entry.output_contract_version,
        verified_output=record.artifact_ref.replay_ready,
        code_template_version=ledger_entry.code_template_version,
        extractor_version=ledger_entry.extractor_version,
    )


def validated_replay_contract_compatible(
    *,
    current_spec: CanonicalTaskSpec,
    candidate_spec: CanonicalTaskSpec,
) -> bool:
    if current_spec.task_family != candidate_spec.task_family:
        return False
    if current_spec.intent_op != candidate_spec.intent_op:
        return False
    if tuple(current_spec.required_tools) != tuple(candidate_spec.required_tools):
        return False
    if tuple(current_spec.required_outputs) != tuple(candidate_spec.required_outputs):
        return False
    current_arguments = _schema_shape_arguments(current_spec.arguments)
    candidate_arguments = _schema_shape_arguments(candidate_spec.arguments)
    return current_arguments == candidate_arguments


def select_history_replay_candidate(
    *,
    compiler_result: TaskCompilerResult,
    runtime_signature: RuntimeCompatibilitySignature,
    input_artifact_hashes: tuple[str, ...],
    output_contract_version: str,
    history_records: dict[str, HistoryReplayRecord],
    memory_match_memory_ids: tuple[str, ...],
    allow_exact_replay_selection: bool = True,
    allow_validated_replay_selection: bool = True,
    preferred_candidate_id: str = "",
) -> ReplayCandidateSelection | None:
    current_spec = compiler_result.canonical_task_spec
    if compiler_result.status != CompilerStatus.COMPILED or current_spec is None:
        return None
    ranked_ids: list[str] = []
    if preferred_candidate_id:
        ranked_ids.append(preferred_candidate_id)
    ranked_ids.extend(memory_id for memory_id in memory_match_memory_ids if memory_id != preferred_candidate_id)
    seen_ids: set[str] = set()
    selections: list[ReplayCandidateSelection] = []
    for memory_id in ranked_ids:
        if memory_id in seen_ids:
            continue
        seen_ids.add(memory_id)
        record = history_records.get(memory_id)
        if record is None:
            continue
        candidate = history_replay_candidate(record)
        if candidate is None:
            continue
        compatibility = runtime_signature.compare(candidate.runtime_signature)
        if compatibility == CompatibilityVerdict.INCOMPATIBLE:
            continue
        if output_contract_version != candidate.output_contract_version:
            continue
        if allow_exact_replay_selection and candidate.exact_key == replay_exact_key(
            canonical_task_spec=current_spec,
            input_artifact_hashes=input_artifact_hashes,
            runtime_signature=runtime_signature,
            code_template_version=candidate.code_template_version,
            extractor_version=candidate.extractor_version,
            output_contract_version=output_contract_version,
        ):
            selections.append(
                ReplayCandidateSelection(
                    candidate=candidate,
                    record=record,
                    selection_reason="exact_replay_key_match",
                    compatibility_verdict=compatibility,
                )
            )
            continue
        if allow_validated_replay_selection and validated_replay_contract_compatible(
            current_spec=current_spec,
            candidate_spec=candidate.canonical_task_spec,
        ):
            selections.append(
                ReplayCandidateSelection(
                    candidate=candidate,
                    record=record,
                    selection_reason="validated_replay_contract_match",
                    compatibility_verdict=compatibility,
                )
            )
    if not selections:
        return None
    selections.sort(key=_candidate_selection_sort_key)
    return selections[0]


def count_exact_replay_candidates(
    *,
    compiler_result: TaskCompilerResult,
    runtime_signature: RuntimeCompatibilitySignature,
    input_artifact_hashes: tuple[str, ...],
    output_contract_version: str,
    history_records: dict[str, HistoryReplayRecord],
    memory_match_memory_ids: tuple[str, ...],
    replay_candidate: ReplayCandidate | None = None,
    allow_exact_replay: bool = True,
) -> int:
    if not allow_exact_replay:
        return 0
    current_spec = compiler_result.canonical_task_spec
    if compiler_result.status != CompilerStatus.COMPILED or current_spec is None:
        return 0
    candidate_ids: set[str] = set()
    for memory_id in memory_match_memory_ids:
        record = history_records.get(memory_id)
        if record is None:
            continue
        candidate = history_replay_candidate(record)
        if candidate is None:
            continue
        if runtime_signature.compare(candidate.runtime_signature) != CompatibilityVerdict.COMPATIBLE:
            continue
        if output_contract_version != candidate.output_contract_version:
            continue
        exact_key = replay_exact_key(
            canonical_task_spec=current_spec,
            input_artifact_hashes=input_artifact_hashes,
            runtime_signature=runtime_signature,
            code_template_version=candidate.code_template_version,
            extractor_version=candidate.extractor_version,
            output_contract_version=output_contract_version,
        )
        if exact_key == candidate.exact_key:
            candidate_ids.add(candidate.candidate_id)
    if replay_candidate is not None:
        exact_key = replay_exact_key(
            canonical_task_spec=current_spec,
            input_artifact_hashes=input_artifact_hashes,
            runtime_signature=runtime_signature,
            code_template_version=replay_candidate.code_template_version,
            extractor_version=replay_candidate.extractor_version,
            output_contract_version=output_contract_version,
        )
        if (
            replay_candidate.verified_output
            and runtime_signature.compare(replay_candidate.runtime_signature) == CompatibilityVerdict.COMPATIBLE
            and output_contract_version == replay_candidate.output_contract_version
            and exact_key == replay_candidate.exact_key
        ):
            candidate_ids.add(replay_candidate.candidate_id)
    return len(candidate_ids)


def _candidate_selection_sort_key(selection: ReplayCandidateSelection) -> tuple[int, int, int, str]:
    exact_rank = 0 if selection.selection_reason == "exact_replay_key_match" else 1
    compatibility_rank = {
        CompatibilityVerdict.COMPATIBLE: 0,
        CompatibilityVerdict.DEGRADED: 1,
        CompatibilityVerdict.INCOMPATIBLE: 2,
    }[selection.compatibility_verdict]
    same_intent_rank = 0
    return (
        exact_rank,
        compatibility_rank,
        same_intent_rank,
        selection.candidate.candidate_id,
    )


def _schema_shape_arguments(arguments: dict[str, object]) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (str(key), _argument_shape_tag(value))
            for key, value in arguments.items()
            if key
            not in {
                "dataset_id",
                "csv_path",
                "document_path",
                "topic",
                "expected_locator",
                "source_rounds",
                "required_lineage",
                *_BENCHMARK_ONLY_ARGUMENT_KEYS,
            }
        )
    )


def _argument_shape_tag(value: object) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        if not value:
            return "list:empty"
        return f"list:{_argument_shape_tag(value[0])}"
    if isinstance(value, dict):
        return "dict:" + ",".join(sorted(str(key) for key in value.keys()))
    return type(value).__name__


def _evidence_item_replay_payload(item: object) -> dict[str, object]:
    locator = getattr(item, "locator", None)
    return {
        "item_id": str(getattr(item, "item_id", "")),
        "bucket": str(getattr(item, "bucket", "")),
        "locator": None if locator is None else asdict(locator),
        "rendered_text": str(getattr(item, "rendered_text", "")),
        "source_name": str(getattr(item, "source_name", "")),
        "rank": int(getattr(item, "rank", 0)),
        "score": float(getattr(item, "score", 0.0)),
        "metadata": dict(sorted(dict(getattr(item, "metadata", {})).items())),
    }


def _evidence_item_execution_input_payload(item: object) -> dict[str, object]:
    locator = getattr(item, "locator", None)
    metadata = {
        str(key): value
        for key, value in dict(getattr(item, "metadata", {})).items()
        if str(key) not in {"score", "semantic_score", "lexical_score", "rrf_score"}
    }
    return {
        "item_id": str(getattr(item, "item_id", "")),
        "bucket": str(getattr(item, "bucket", "")),
        "locator": None if locator is None else asdict(locator),
        "rendered_text": str(getattr(item, "rendered_text", "")),
        "source_name": str(getattr(item, "source_name", "")),
        "metadata": dict(sorted(metadata.items())),
    }


def _replay_spec_payload(spec: CanonicalTaskSpec) -> dict[str, object]:
    return {
        "task_family": spec.task_family,
        "intent_op": spec.intent_op,
        "target_entities": list(spec.target_entities),
        "time_scope": spec.time_scope,
        "required_outputs": list(spec.required_outputs),
        "required_tools": list(spec.required_tools),
        "arguments": {
            key: value
            for key, value in dict(spec.arguments).items()
            if key not in _BENCHMARK_ONLY_ARGUMENT_KEYS
        },
        "schema_version": spec.schema_version,
    }


def _load_history_artifact_ref(
    *,
    store: object,
    artifact_ref_id: str,
) -> ExecutionArtifactRef | None:
    try:
        entry = store.get_ref_registry_entry(artifact_ref_id)
    except Exception:
        return None
    if entry.ref_kind.value != "execution_artifact":
        return None
    try:
        settlement_payload = store.read_artifact_settlement_record(artifact_ref_id)
    except Exception:
        return None
    replay_ready = bool(settlement_payload.get("replay_ready", False))
    manifest_hash = entry.manifest_hash
    relpath = entry.relpath or entry.workspace_relpath
    if not manifest_hash or not relpath:
        return None
    manifest = store.read_artifact_output_manifest(manifest_hash)
    primary_output = next((item for item in manifest.outputs if item.relpath == relpath), None)
    if primary_output is None:
        primary_output = next((item for item in manifest.outputs if item.artifact_name == "summary_json"), None)
    if primary_output is None:
        return None
    return ExecutionArtifactRef(
        artifact_id=artifact_ref_id,
        task_id=manifest.task_id,
        step_id=manifest.step_id,
        artifact_type=primary_output.artifact_type,
        root_id=entry.root_id,
        relpath=primary_output.relpath,
        blob_hash=primary_output.sha256,
        size_bytes=primary_output.size_bytes,
        produced_by="executor",
        verification_state=entry.status,
        replay_ready=replay_ready,
        workspace_relpath=entry.workspace_relpath,
        manifest_hash=manifest_hash,
    )


def _load_history_ledger_for_memory(
    *,
    store: object,
    memory_id: str,
) -> ReplayLedgerEntry | None:
    ledger_dir = store.replay_ledger_dir
    if not ledger_dir.exists():
        return None
    for path in sorted(ledger_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if str(payload.get("memory_id", "")) != memory_id:
            continue
        return store.read_replay_ledger_entry(str(payload["ledger_id"]))
    return None


def _matching_history_output_path(
    *,
    history_root: Path,
    store: object,
    artifact_ref: ExecutionArtifactRef,
    ledger_entry: ReplayLedgerEntry,
) -> Path | None:
    try:
        session = store.read_runtime_session(ledger_entry.session_id)
    except Exception:
        return None
    workspace_root = str(session.workspace_root).strip()
    output_relpath = str(artifact_ref.relpath or artifact_ref.workspace_relpath).strip()
    expected_sha = str(artifact_ref.blob_hash).strip()
    if not workspace_root or not output_relpath or not expected_sha:
        return None
    path = Path(workspace_root) / output_relpath
    if not path.is_absolute():
        path = history_root / path
    if not path.exists():
        return None
    payload = path.read_bytes()
    if sha256_digest(payload) != expected_sha:
        return None
    return path


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)
