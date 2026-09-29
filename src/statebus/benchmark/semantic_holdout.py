from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import time
import traceback

from statebus.benchmark.adaptive_formal import FormalAdaptiveCase, adapt_formal_sample
from statebus.benchmark.adaptive_formal_mainline import (
    LaneFailure,
    _SYSTEM_FAILURE_CLASSES,
    _classify_failure,
    _failure_stage,
    _run_adaptive_case,
)
from statebus.benchmark.contest_fairness import GOLD_ONLY_KEYS
from statebus.benchmark.minimal_runner import MinimalBenchmarkSample
from statebus.contracts import CanonicalTaskSpec
from statebus.utils import sha256_digest, stable_json_dumps


_SAMPLE_ROOT = Path(__file__).with_name("samples") / "semantic_holdout"
_MANIFEST_PATH = _SAMPLE_ROOT / "manifest.json"
_GOLD_PATH = _SAMPLE_ROOT / "gold.json"
_FREEZE_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs/improvement/25_contest_evidence_closure_20260720/runtime_freeze_snapshot.json"
)
# These keys belong to the immutable pre-release evidence snapshot. They keep
# their historical paths intentionally and are not live import/package names.
_HISTORICAL_FREEZE_DIRS = ("v2/runtime", "v2/control", "v2/state", "v2/memory")


def _canonical_spec(payload: dict[str, object]) -> CanonicalTaskSpec:
    return CanonicalTaskSpec(
        task_family=str(payload["task_family"]),
        intent_op=str(payload["intent_op"]),
        target_entities=tuple(str(item) for item in payload.get("target_entities", [])),
        time_scope=str(payload.get("time_scope", "")),
        required_outputs=tuple(str(item) for item in payload.get("required_outputs", [])),
        required_tools=tuple(str(item) for item in payload.get("required_tools", [])),
        arguments=dict(payload.get("arguments", {})),
        schema_version=str(
            payload.get("schema_version", CanonicalTaskSpec(task_family="", intent_op="").schema_version)
        ),
    )


def load_semantic_holdout_cases(
    manifest_path: Path = _MANIFEST_PATH,
    gold_path: Path = _GOLD_PATH,
) -> tuple[FormalAdaptiveCase, ...]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    raw_cases = manifest.get("cases", [])
    facts = gold.get("facts", {})
    if not isinstance(raw_cases, list) or len(raw_cases) != 8:
        raise ValueError("semantic_holdout_requires_exactly_eight_cases")
    if not isinstance(facts, dict):
        raise ValueError("semantic_holdout_gold_invalid")
    task_ids = [str(item.get("task_id", "")) for item in raw_cases if isinstance(item, dict)]
    if len(task_ids) != 8 or len(set(task_ids)) != 8 or set(task_ids) != set(facts):
        raise ValueError("semantic_holdout_manifest_gold_task_mismatch")
    input_shapes = Counter(str(item.get("input_shape", "")) for item in raw_cases)
    if input_shapes != Counter({
        "narrative_only": 3,
        "table_only": 3,
        "mixed_narrative_table": 2,
    }):
        raise ValueError(f"semantic_holdout_input_shape_contract:{dict(input_shapes)}")
    serialized_manifest = stable_json_dumps(manifest)
    for key in (*GOLD_ONLY_KEYS, "expected_capability", "expected_evidence_type"):
        if f'"{key}":' in serialized_manifest:
            raise ValueError(f"semantic_holdout_manifest_contains_benchmark_only_key:{key}")

    cases: list[FormalAdaptiveCase] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise ValueError("semantic_holdout_case_invalid")
        task_id = str(raw_case["task_id"])
        request_text = str(raw_case["request_text"])
        lowered_request = request_text.lower()
        if any(token in lowered_request for token in ("semantic capability", "table capability", "expected route")):
            raise ValueError(f"semantic_holdout_request_leaks_route:{task_id}")
        spec_payload = raw_case.get("canonical_task_spec")
        if not isinstance(spec_payload, dict):
            raise ValueError(f"semantic_holdout_spec_missing:{task_id}")
        spec = _canonical_spec(spec_payload)
        source_path = Path(str(spec.arguments.get("source_path", "")))
        project_root = Path(__file__).resolve().parents[3]
        resolved_source = (project_root / source_path).resolve()
        if project_root.resolve() not in resolved_source.parents or not resolved_source.is_file():
            raise ValueError(f"semantic_holdout_source_not_repo_local:{task_id}")
        if raw_case.get("input_shape") == "narrative_only":
            source_text = resolved_source.read_text(encoding="utf-8")
            if any(line.strip().startswith("|") for line in source_text.splitlines()):
                raise ValueError(f"semantic_holdout_narrative_contains_table:{task_id}")
        sample = MinimalBenchmarkSample(
            task_id=task_id,
            request_text=request_text,
            canonical_task_spec=spec,
            expected_artifact_type="json",
            task_family="semantic_holdout",
            expected_facts=dict(facts[task_id]),
            scenario_tags=(str(raw_case["input_shape"]), "offline", "external_gold"),
        )
        cases.append(adapt_formal_sample(sample))
    return tuple(cases)


def _select_semantic_holdout_cases(
    cases: tuple[FormalAdaptiveCase, ...],
    *,
    case_ids: tuple[str, ...] = (),
    max_cases: int = 0,
) -> tuple[FormalAdaptiveCase, ...]:
    if max_cases < 0:
        raise ValueError("semantic_holdout_max_cases_negative")
    normalized_ids = tuple(dict.fromkeys(case_id.strip() for case_id in case_ids if case_id.strip()))
    selected = cases
    if normalized_ids:
        by_id = {case.task_id: case for case in cases}
        missing = [case_id for case_id in normalized_ids if case_id not in by_id]
        if missing:
            raise ValueError(f"semantic_holdout_unknown_case_ids:{','.join(missing)}")
        selected = tuple(by_id[case_id] for case_id in normalized_ids)
    if max_cases > 0:
        selected = selected[:max_cases]
    if not selected:
        raise ValueError("semantic_holdout_selection_empty")
    return selected


def _directory_content_hash(project_root: Path, relative_dir: str) -> str:
    directory = project_root / relative_dir
    paths = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
        and not any(part.startswith(".") for part in path.relative_to(directory).parts)
    )
    digest = hashlib.sha256()
    for path in paths:
        relative_path = path.relative_to(project_root).as_posix()
        file_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(f"{file_digest}  {relative_path}\n".encode("utf-8"))
    return digest.hexdigest()


def _current_freeze_file_hashes(project_root: Path) -> dict[str, str]:
    paths = sorted({
        path
        for relative_dir in _HISTORICAL_FREEZE_DIRS
        for path in (project_root / relative_dir).rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
        and not any(
            part.startswith(".")
            for part in path.relative_to(project_root / relative_dir).parts
        )
    })
    return {
        path.relative_to(project_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


def _load_freeze_file_hashes(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, separator, relative_path = line.partition("  ")
        if (
            not separator
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not relative_path
            or relative_path in entries
        ):
            raise ValueError(f"runtime_freeze_file_ledger_invalid:{line}")
        entries[relative_path] = digest
    return entries


def _freeze_hashes_from_ledger(
    entries: dict[str, str],
) -> tuple[dict[str, str], str]:
    directory_hashes: dict[str, str] = {}
    for relative_dir in _HISTORICAL_FREEZE_DIRS:
        digest = hashlib.sha256()
        directory_entries = [
            (path, file_digest)
            for path, file_digest in sorted(entries.items())
            if path.startswith(f"{relative_dir}/")
        ]
        if not directory_entries:
            raise ValueError(f"runtime_freeze_directory_ledger_empty:{relative_dir}")
        for path, file_digest in directory_entries:
            digest.update(f"{file_digest}  {path}\n".encode("utf-8"))
        directory_hashes[relative_dir] = digest.hexdigest()
    unknown_paths = sorted(
        path
        for path in entries
        if not any(path.startswith(f"{relative_dir}/") for relative_dir in _HISTORICAL_FREEZE_DIRS)
    )
    if unknown_paths:
        raise ValueError(f"runtime_freeze_file_ledger_scope_invalid:{unknown_paths}")
    combined = hashlib.sha256()
    for relative_dir in _HISTORICAL_FREEZE_DIRS:
        combined.update(
            f"{relative_dir} {directory_hashes[relative_dir]}\n".encode("utf-8")
        )
    return directory_hashes, combined.hexdigest()


def historical_runtime_freeze_audit(
    snapshot_path: Path = _FREEZE_PATH,
    *,
    project_root: Path | None = None,
) -> dict[str, object]:
    """Audit the stored baseline ledger without comparing it to today's tree."""

    root = (project_root or Path(__file__).resolve().parents[3]).resolve()
    resolved_snapshot = (
        snapshot_path if snapshot_path.is_absolute() else root / snapshot_path
    ).resolve()
    if root not in resolved_snapshot.parents or not resolved_snapshot.is_file():
        raise ValueError("runtime_freeze_snapshot_missing")
    snapshot = json.loads(resolved_snapshot.read_text(encoding="utf-8"))
    ledger_path = (root / str(snapshot.get("per_file_hashes_path", ""))).resolve()
    if root not in ledger_path.parents or not ledger_path.is_file():
        raise ValueError("runtime_freeze_file_ledger_missing")
    entries = _load_freeze_file_hashes(ledger_path)
    ledger_directory_hashes, ledger_freeze_sha = _freeze_hashes_from_ledger(entries)
    observed_ledger_hash = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    expected_directory_hashes = dict(snapshot.get("directory_hashes", {}))
    checks = {
        "snapshot_schema": snapshot.get("schema_version")
        == "statebus.runtime_freeze_snapshot.v1",
        "ledger_sha256": snapshot.get("per_file_hashes_sha256")
        == observed_ledger_hash,
        "per_file_count": snapshot.get("per_file_count") == len(entries),
        "directory_hashes": expected_directory_hashes == ledger_directory_hashes,
        "combined_freeze_sha256": snapshot.get("runtime_freeze_sha")
        == ledger_freeze_sha,
        "git_head_shape": bool(
            isinstance(snapshot.get("git_head"), str)
            and len(str(snapshot["git_head"])) == 40
            and all(
                character in "0123456789abcdef"
                for character in str(snapshot["git_head"])
            )
        ),
    }
    return {
        "schema_version": "statebus.historical_runtime_freeze_audit.v1",
        "audit_scope": "stored_snapshot_and_ledger_self_consistency",
        "snapshot_path": str(resolved_snapshot),
        "freeze_kind": snapshot.get("freeze_kind"),
        "git_head": snapshot.get("git_head"),
        "runtime_freeze_sha": snapshot.get("runtime_freeze_sha"),
        "ledger_runtime_freeze_sha": ledger_freeze_sha,
        "expected_directory_hashes": expected_directory_hashes,
        "ledger_directory_hashes": ledger_directory_hashes,
        "per_file_hashes_path": str(ledger_path),
        "expected_per_file_count": snapshot.get("per_file_count"),
        "observed_per_file_count": len(entries),
        "expected_per_file_ledger_hash": snapshot.get("per_file_hashes_sha256"),
        "observed_per_file_ledger_hash": observed_ledger_hash,
        "checks": checks,
        "ok": all(checks.values()),
        "claim_scope": snapshot.get("claim_scope"),
        "current_tree_compared": False,
    }


def runtime_freeze_audit() -> dict[str, object]:
    snapshot = json.loads(_FREEZE_PATH.read_text(encoding="utf-8"))
    project_root = Path(__file__).resolve().parents[3]
    observed = {
        relative_dir: _directory_content_hash(project_root, relative_dir)
        for relative_dir in _HISTORICAL_FREEZE_DIRS
    }
    combined = hashlib.sha256()
    for relative_dir in _HISTORICAL_FREEZE_DIRS:
        combined.update(f"{relative_dir} {observed[relative_dir]}\n".encode("utf-8"))
    observed_freeze_sha = combined.hexdigest()
    expected = dict(snapshot.get("directory_hashes", {}))
    ledger_path = (project_root / str(snapshot.get("per_file_hashes_path", ""))).resolve()
    if project_root.resolve() not in ledger_path.parents or not ledger_path.is_file():
        raise ValueError("runtime_freeze_file_ledger_missing")
    expected_files = _load_freeze_file_hashes(ledger_path)
    observed_files = _current_freeze_file_hashes(project_root)
    changed_files = sorted(
        path
        for path in expected_files.keys() & observed_files.keys()
        if expected_files[path] != observed_files[path]
    )
    added_files = sorted(observed_files.keys() - expected_files.keys())
    removed_files = sorted(expected_files.keys() - observed_files.keys())
    observed_ledger_hash = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    per_file_ok = bool(
        snapshot.get("per_file_count") == len(expected_files) == len(observed_files)
        and snapshot.get("per_file_hashes_sha256") == observed_ledger_hash
        and not changed_files
        and not added_files
        and not removed_files
    )
    return {
        "schema_version": "statebus.runtime_freeze_audit.v1",
        "freeze_kind": snapshot.get("freeze_kind"),
        "git_head": snapshot.get("git_head"),
        "expected_runtime_freeze_sha": snapshot.get("runtime_freeze_sha"),
        "observed_runtime_freeze_sha": observed_freeze_sha,
        "expected_directory_hashes": expected,
        "observed_directory_hashes": observed,
        "changed_directories": [
            relative_dir
            for relative_dir in _HISTORICAL_FREEZE_DIRS
            if expected.get(relative_dir) != observed.get(relative_dir)
        ],
        "per_file_hashes_path": str(ledger_path),
        "expected_per_file_count": snapshot.get("per_file_count"),
        "observed_per_file_count": len(observed_files),
        "expected_per_file_ledger_hash": snapshot.get("per_file_hashes_sha256"),
        "observed_per_file_ledger_hash": observed_ledger_hash,
        "changed_files": changed_files,
        "added_files": added_files,
        "removed_files": removed_files,
        "ok": (
            snapshot.get("runtime_freeze_sha") == observed_freeze_sha
            and all(expected.get(item) == observed.get(item) for item in _HISTORICAL_FREEZE_DIRS)
            and per_file_ok
        ),
        "claim_scope": snapshot.get("claim_scope"),
    }


def _semantic_state_case_gate(case: dict[str, object]) -> bool:
    telemetry = case.get("telemetry", {})
    telemetry = telemetry if isinstance(telemetry, dict) else {}
    selections = case.get("semantic_state_selections", {})
    selections = selections if isinstance(selections, dict) else {}
    records = [
        record
        for record in case.get("state_consumption_records", [])
        if isinstance(record, dict)
    ]
    return bool(
        selections
        and float(telemetry.get("semantic_state_publish_count", 0.0)) >= 1.0
        and float(telemetry.get("semantic_state_transfer_count", 0.0)) >= 1.0
        and float(telemetry.get("semantic_state_consume_count", 0.0)) >= 1.0
        and float(telemetry.get("semantic_state_selected_bytes", 0.0)) > 0.0
        and all(
            int(selection.get("producer_pid", 0)) > 0
            and int(selection.get("consumer_pid", 0)) > 0
            and int(selection.get("producer_pid", 0)) != int(selection.get("consumer_pid", 0))
            and bool(selection.get("selected_candidate_ids"))
            for selection in selections.values()
            if isinstance(selection, dict)
        )
        and any(
            record.get("operation") == "cosine_topk_budget_pruning"
            and record.get("behavioral_effect") in {"changed", "no_effect"}
            and bool(record.get("selected_ids"))
            and bool(record.get("downstream_ref_ids"))
            for record in records
        )
    )


def _role_request_gold_key_gate(case: dict[str, object]) -> bool:
    rendered = stable_json_dumps(case.get("role_invocations", []))
    return all(f'"{key}":' not in rendered for key in GOLD_ONLY_KEYS)


def _write_markdown(summary: dict[str, object], path: Path) -> None:
    counts = summary["capability_counts"]
    gates = summary["gates"]
    lines = [
        "# Semantic Holdout Summary",
        "",
        f"- Overall: {'PASS' if summary['ok'] else 'FAIL'}",
        f"- Quality: {summary['quality_pass_count']}/{summary['case_count']}",
        f"- Semantic retrieval selections: {counts.get('retrieve_semantic_evidence_v1', 0)}",
        f"- Table retrieval selections: {counts.get('retrieve_table_evidence_v1', 0)}",
        f"- Runtime freeze audit: {'PASS' if gates['runtime_freeze_unchanged'] else 'FAIL'}",
        "",
        "## Cases",
        "",
        "| Case | Input | Retriever | Executor | Quality | StateRef |",
        "| --- | --- | --- | --- | ---: | ---: |",
    ]
    for case in summary["cases"]:
        lines.append(
            "| {task_id} | {input_shape} | {retriever_capability} | {executor_capability} | {quality} | {state} |".format(
                task_id=case["task_id"],
                input_shape=case["input_shape"],
                retriever_capability=case["retriever_capability"],
                executor_capability=case["executor_capability"],
                quality="PASS" if case["ok"] else "FAIL",
                state="PASS" if case["semantic_state_gate"] else ("N/A" if not case["semantic_selected"] else "FAIL"),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_ablation_markdown(summary: dict[str, object], path: Path) -> None:
    lines = [
        "# Semantic State Ablation Summary",
        "",
        f"- Overall: {'PASS' if summary['ok'] else 'INCONCLUSIVE'}",
        f"- Pairs: {summary['denominator']['closed_pairs']}/{summary['denominator']['planned_pairs']} closed",
        "- Variants: " + ", ".join(summary["modes"]),
        "",
        "| Pair | " + " | ".join(summary["modes"]) + " | Denominator |",
        "| --- | " + " | ".join("---" for _ in summary["modes"]) + " | --- |",
    ]
    for report in summary["pairs"]:
        by_mode = {row["variant"]: row for row in report["variants"]}
        statuses = ["PASS" if by_mode.get(mode, {}).get("ok") else "FAIL" for mode in summary["modes"]]
        lines.append("| " + str(report["task_id"]) + " | " + " | ".join(statuses) + " | "
                     + ("CLOSED" if report["denominator_eligible"] else "OPEN") + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _semantic_selected_metrics(summary: dict[str, object]) -> dict[str, object]:
    selections = summary.get("semantic_state_selections", {})
    selections = selections if isinstance(selections, dict) else {}
    state_selected_ids: list[str] = []
    selected_bytes = 0
    cross_process = False
    for selection in selections.values():
        if not isinstance(selection, dict):
            continue
        state_selected_ids.extend(str(item) for item in selection.get("selected_candidate_ids", ()))
        selected_bytes += int(selection.get("selected_evidence_bytes", 0) or 0)
        producer_pid = int(selection.get("producer_pid", 0) or 0)
        consumer_pid = int(selection.get("consumer_pid", 0) or 0)
        cross_process = cross_process or bool(producer_pid and consumer_pid and producer_pid != consumer_pid)
    publication_receipts = summary.get("state_publication_receipts", {})
    publication_receipts = publication_receipts if isinstance(publication_receipts, dict) else {}
    consumer_receipts = summary.get("semantic_consumer_receipts", {})
    consumer_receipts = consumer_receipts if isinstance(consumer_receipts, dict) else {}
    release_receipts = summary.get("state_release_reclaim_receipts", {})
    release_receipts = release_receipts if isinstance(release_receipts, dict) else {}
    evidence = summary.get("report_evidence_items")
    evidence = evidence if isinstance(evidence, list) else None
    downstream_items = [item for item in (evidence or []) if isinstance(item, dict)]
    downstream_ids = [str(item.get("id", "")) for item in downstream_items if item.get("id")]
    return {
        "payload_bytes": sum(int(item.get("size_bytes", 0) or 0) for item in publication_receipts.values() if isinstance(item, dict)),
        "read_bytes": sum(int(item.get("observed_size_bytes", 0) or 0) for item in consumer_receipts.values() if isinstance(item, dict)),
        # report_evidence_items is the evidence actually materialized for the
        # downstream reporting path.  State selection receipts are a useful
        # lifecycle observation, but their byte count is not a character
        # count and does not describe the off control's normal evidence path.
        "selected_ids": list(dict.fromkeys(downstream_ids)) if evidence is not None else None,
        "selected_evidence_chars": (
            sum(len(str(item.get("text", ""))) for item in downstream_items)
            if evidence is not None else None
        ),
        "state_selected_ids": list(dict.fromkeys(state_selected_ids)),
        "state_selected_evidence_bytes": selected_bytes,
        "cross_process_consumption_observed": cross_process,
        "release_observed": bool(release_receipts) and all(
            bool(item.get("owner_released")) and bool(item.get("physical_reclaimed"))
            for item in release_receipts.values() if isinstance(item, dict)
        ),
    }


def _semantic_selected_tokens(summary: dict[str, object], selected_ids: list[str] | None, tokenizer_path: str | None) -> int | None:
    if selected_ids is None:
        return None
    if not tokenizer_path or not (Path(tokenizer_path) / "tokenizer.json").is_file():
        return None
    evidence = summary.get("report_evidence_items", ())
    evidence = evidence if isinstance(evidence, list) else []
    selected = set(selected_ids)
    texts = [str(item.get("text", "")) for item in evidence if isinstance(item, dict) and str(item.get("id", "")) in selected]
    if not texts:
        return 0 if not selected else None
    from statebus.benchmark.contest_metrics import _tokenizer
    tokenizer = _tokenizer(tokenizer_path)
    return sum(len(tokenizer.encode(text, add_special_tokens=False).ids) for text in texts)


def _provider_call_count(summary: dict[str, object]) -> int | None:
    """Count observed role attempts, with legacy event fallback."""

    invocations = summary.get("role_invocations")
    if isinstance(invocations, list):
        role_attempts = sum(
            len(attempts)
            for invocation in invocations
            if isinstance(invocation, dict)
            and isinstance((attempts := invocation.get("attempts")), list)
        )
        generations = summary.get("generation_attempts")
        generation_attempts = len(generations) if isinstance(generations, list) else 0
        return role_attempts + generation_attempts
    events = summary.get("provider_invocation_events")
    return len(events) if isinstance(events, list) else None


def _semantic_ablation_row(
    *,
    case: FormalAdaptiveCase,
    mode: str,
    case_summary: dict[str, object] | None = None,
    failure: dict[str, object] | None = None,
    tokenizer_path: str | None = None,
) -> dict[str, object]:
    """Project one matched semantic-state variant without inventing metrics."""

    summary = case_summary or {}
    telemetry = summary.get("telemetry", {})
    telemetry = telemetry if isinstance(telemetry, dict) else {}
    receipts = summary.get("component_activation_receipts", {})
    receipts = receipts if isinstance(receipts, dict) else {}
    activation = receipts.get("semantic_state", {})
    activation = activation if isinstance(activation, dict) else {}
    selections = summary.get("semantic_state_selections", {})
    selections = selections if isinstance(selections, dict) else {}
    effects = summary.get("downstream_effects", {})
    effects = effects if isinstance(effects, dict) else {}
    selected_metrics = _semantic_selected_metrics(summary)
    selected_tokens = _semantic_selected_tokens(summary, selected_metrics["selected_ids"], tokenizer_path)
    usage = summary.get("usage", {})
    usage = usage if isinstance(usage, dict) else {}
    terminal = bool(summary.get("runtime_completed"))
    quality = bool(summary.get("ok"))
    disable_reason = str(activation.get("disable_reason", ""))
    effective_mode = str(activation.get("effective_mode", ""))
    if failure is not None:
        activation_status = "environment_failure"
    elif mode == "off":
        activation_status = "disabled_control"
    elif effective_mode == "not_applicable" or disable_reason == "no_semantic_state_payload":
        activation_status = "inactive_no_semantic_state_payload"
    else:
        activation_status = "active"
    release_receipts = summary.get("state_release_reclaim_receipts", {})
    release_receipts = release_receipts if isinstance(release_receipts, dict) else {}
    semantic_refs = any(
        bool(summary.get(name))
        for name in (
            "semantic_state_selections",
            "state_publication_receipts",
            "state_access_grants",
            "state_pin_receipts",
            "state_release_reclaim_receipts",
        )
    )
    inactive_lifecycle_closed = (
        activation_status == "inactive_no_semantic_state_payload"
        and not semantic_refs
    )
    active_gate = mode != "on" or _semantic_state_case_gate(summary)
    inactive_gate = (
        activation_status == "inactive_no_semantic_state_payload"
        and not selections
        and float(telemetry.get("semantic_state_publish_count", 0.0)) == 0.0
        and float(telemetry.get("semantic_state_transfer_count", 0.0)) == 0.0
        and float(telemetry.get("semantic_state_consume_count", 0.0)) == 0.0
        and inactive_lifecycle_closed
    )
    receipt_matches = activation.get("requested_mode") == mode
    row = {
        "pair_id": f"{case.task_id}:semantic_state",
        "task_id": case.task_id,
        "task_contract_hash": case.spec.spec_hash,
        "variant": mode,
        "requested_feature_flags": {"semantic_state": mode},
        "executor_consumer_policy": dict(
            summary.get("semantic_state_executor_policy", {})
        ),
        "effective_feature_flags": {
            "semantic_state": effective_mode or "unknown"
        },
        "activation_receipt": dict(activation),
        "activation_status": activation_status,
        "activation_reason": disable_reason,
        "terminal": terminal,
        "quality_pass": quality,
        "ok": bool(terminal and quality and receipt_matches and (active_gate or inactive_gate)),
        "provider_call_count": _provider_call_count(summary),
        "provider_prompt_tokens": usage.get("prompt_tokens"),
        "provider_completion_tokens": usage.get("completion_tokens"),
        "provider_total_tokens": usage.get("total_tokens"),
        "e2e_ms": summary.get("elapsed_ms"),
        "repair": bool(summary.get("planner_policy_repair_used", False)) or bool(telemetry.get("repair_used", 0.0)),
        "payload_bytes": selected_metrics["payload_bytes"],
        "read_bytes": selected_metrics["read_bytes"],
        "cross_process_consumption_observed": selected_metrics["cross_process_consumption_observed"],
        "release_observed": selected_metrics["release_observed"],
        "selected_ids": selected_metrics["selected_ids"],
        "selected_evidence_chars": selected_metrics["selected_evidence_chars"],
        "selected_evidence_tokens": selected_tokens,
        "state_selected_ids": selected_metrics["state_selected_ids"],
        "state_selected_evidence_bytes": selected_metrics["state_selected_evidence_bytes"],
        "semantic_publish_count": float(telemetry.get("semantic_state_publish_count", 0.0)),
        "semantic_consume_count": float(telemetry.get("semantic_state_consume_count", 0.0)),
        "semantic_transfer_count": float(telemetry.get("semantic_state_transfer_count", 0.0)),
        "producer_active": bool(activation.get("producer_active", False)),
        "consumer_active": bool(activation.get("consumer_active", False)),
        "actual_use": bool(selections),
        "downstream_effect": any(
            isinstance(effect, dict)
            and effect.get("behavioral_effect") in {"changed", "no_effect"}
            for effect in effects.values()
        ),
        "behavioral_effect": next(
            (
                str(effect.get("behavioral_effect"))
                for effect in effects.values()
                if isinstance(effect, dict)
                and effect.get("behavioral_effect") in {"changed", "no_effect"}
            ),
            "not_applicable",
        ),
        "headline_effect": any(
            isinstance(effect, dict) and effect.get("behavioral_effect") == "changed"
            for effect in effects.values()
        ),
        "state_release_reclaim_closed": bool(
            release_receipts
            or mode == "off"
            or inactive_lifecycle_closed
        ),
        "summary_path": str(summary.get("run_dir", "")),
    }
    if failure is not None:
        row.update({
            "terminal": False,
            "quality_pass": False,
            "ok": False,
            "activation_status": "environment_failure",
            "failure": failure,
            "provider_call_count": None,
            "payload_bytes": None,
            "read_bytes": None,
            "cross_process_consumption_observed": None,
            "release_observed": None,
            "selected_ids": None,
            "selected_evidence_chars": None,
            "selected_evidence_tokens": None,
            "state_selected_ids": None,
            "state_selected_evidence_bytes": None,
            "semantic_publish_count": None,
            "semantic_consume_count": None,
            "semantic_transfer_count": None,
        })
    return row


def run_semantic_state_ablation(
    *,
    output_root: Path,
    embedding_model_path: str,
    embedding_device: str,
    case_ids: tuple[str, ...] = (),
    max_cases: int = 0,
    modes: tuple[str, ...] = ("off", "on", "consumer_off"),
    tokenizer_path: str | None = None,
    run_name: str | None = None,
    executor_top_k: int | None = None,
    executor_budget_bytes: int | None = None,
) -> dict[str, object]:
    """Run a small matched off/on/consumer-off SemanticState ablation.

    The runner deliberately keeps the public task, source, provider profile,
    and scorer fixed.  Only the Runtime-owned semantic-state mode changes.
    """

    available_cases = load_semantic_holdout_cases()
    cases = _select_semantic_holdout_cases(
        available_cases,
        case_ids=case_ids,
        max_cases=max_cases,
    )
    normalized_modes = tuple(dict.fromkeys(str(mode) for mode in modes))
    if not normalized_modes or any(mode not in {"off", "on", "consumer_off"} for mode in normalized_modes):
        raise ValueError(f"semantic_state_ablation_modes_invalid:{','.join(normalized_modes)}")
    run_root = output_root / (run_name or (
        f"semantic_state_ablation_{time.strftime('%Y%m%d_%H%M%S')}_"
        f"{time.time_ns() % 1_000_000_000:09d}"
    ))
    run_root.mkdir(parents=True, exist_ok=False)
    case_root = run_root / "cases"
    case_root.mkdir()
    modes = normalized_modes
    rows: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    pair_reports: list[dict[str, object]] = []
    for case in cases:
        pair_rows: list[dict[str, object]] = []
        for mode in modes:
            variant_root = case_root / case.task_id / mode
            print(stable_json_dumps({
                "stage": "semantic_state_ablation_variant_started",
                "task_id": case.task_id,
                "variant": mode,
            }), flush=True)
            try:
                case_summary = _run_adaptive_case(
                    case,
                    case_root=variant_root,
                    embedding_model_path=embedding_model_path,
                    embedding_device=embedding_device,
                    memory_policy="none",
                    semantic_state_mode=mode,
                    semantic_state_executor_top_k=(
                        executor_top_k if mode == "on" else None
                    ),
                    semantic_state_executor_budget_bytes=(
                        executor_budget_bytes if mode == "on" else None
                    ),
                )
                row = _semantic_ablation_row(
                    case=case,
                    mode=mode,
                    case_summary=case_summary,
                    tokenizer_path=tokenizer_path,
                )
                row["summary_path"] = str(variant_root / "summary.json")
            except Exception as exc:
                stage = _failure_stage(str(exc))
                category = _classify_failure(str(exc), stage=stage)
                failure = LaneFailure(
                    lane=f"semantic-state:{case.task_id}:{mode}",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    category=category,
                    stage=stage,
                    task_id=case.task_id,
                    error_code=str(exc).split(":", 1)[0] or type(exc).__name__,
                    system_gate_failed=category in _SYSTEM_FAILURE_CLASSES,
                ).canonical_payload()
                failures.append(failure)
                variant_root.mkdir(parents=True, exist_ok=True)
                (variant_root / "failure.json").write_text(
                    stable_json_dumps(failure) + "\n", encoding="utf-8"
                )
                row = _semantic_ablation_row(
                    case=case,
                    mode=mode,
                    failure=failure,
                    tokenizer_path=tokenizer_path,
                )
                traceback.print_exc()
            pair_rows.append(row)
            rows.append(row)
        expected_modes = set(modes)
        observed_modes = {str(row.get("variant")) for row in pair_rows}
        by_mode = {str(row["variant"]): row for row in pair_rows}
        on_row = by_mode.get("on", {})
        off_row = by_mode.get("off", {})
        consumer_off_row = by_mode.get("consumer_off", {})
        mode_contract = {
            "off_disabled": (
                "off" not in expected_modes
                or (not off_row.get("producer_active", False) and not off_row.get("consumer_active", False))
            ),
            "on_cross_process_consumer": (
                "on" not in expected_modes
                or bool(on_row.get("producer_active", False)
                        and on_row.get("consumer_active", False)
                        and on_row.get("actual_use", False)
                        and on_row.get("cross_process_consumption_observed", False))
            ),
        }
        if "consumer_off" in expected_modes:
            mode_contract["consumer_off_producer_only"] = bool(
                consumer_off_row.get("producer_active", False)
                and not consumer_off_row.get("consumer_active", False)
            )
        activation_statuses = {str(row.get("activation_status", "unknown")) for row in pair_rows}
        inactive_modes = tuple(mode for mode in modes if mode != "off")
        inactive_variant_statuses = {
            str(by_mode.get(mode, {}).get("activation_status", "unknown"))
            for mode in inactive_modes
        }
        inactive_negative_control = (
            bool(inactive_modes)
            and inactive_variant_statuses == {"inactive_no_semantic_state_payload"}
            and ("off" not in expected_modes or by_mode.get("off", {}).get("activation_status") == "disabled_control")
            and all(row.get("ok", False) for row in pair_rows)
            and all(not row.get("actual_use", False) for row in pair_rows)
        )
        active_pair = not inactive_negative_control and (
            "active" in activation_statuses or "disabled_control" in activation_statuses
        )
        environment_failure = "environment_failure" in activation_statuses
        pair_gate = {
            "exact_requested_variants": observed_modes == expected_modes,
            # Compatibility field for historical three-mode consumers.  The
            # new two-mode experiment is judged by exact_requested_variants,
            # rather than being failed for intentionally omitting consumer_off.
            "exactly_three_variants": (
                observed_modes == {"off", "on", "consumer_off"}
                if expected_modes == {"off", "on", "consumer_off"}
                else True
            ),
            "all_variants_terminal": len(pair_rows) == len(modes) and all(row["terminal"] for row in pair_rows),
            "all_variants_quality_pass": len(pair_rows) == len(modes) and all(row["quality_pass"] for row in pair_rows),
            "receipt_modes_match": len(pair_rows) == len(modes) and all(
                row.get("activation_receipt", {}).get("requested_mode") == row.get("variant")
                for row in pair_rows
            ),
            **mode_contract,
            "activation_status_explained": bool(activation_statuses) and not environment_failure,
        }
        pair_report = {
            "pair_id": f"{case.task_id}:semantic_state",
            "task_id": case.task_id,
            "task_contract_hash": case.spec.spec_hash,
            "variants": pair_rows,
            "gates": pair_gate,
            "activation_class": (
                "environment_failure" if environment_failure else
                "inactive_negative_control" if inactive_negative_control else
                "active" if active_pair else "unclassified"
            ),
            "denominator_eligible": bool(active_pair and all(pair_gate.values())),
            "negative_control_valid": bool(inactive_negative_control),
        }
        pair_reports.append(pair_report)

    denominator = {
        "schema_version": "statebus.semantic_state_ablation_denominator.v1",
        "planned_pairs": len(cases),
        "closed_pairs": sum(bool(report["denominator_eligible"]) for report in pair_reports),
        "active_planned_pairs": sum(report["activation_class"] == "active" for report in pair_reports),
        "inactive_negative_control_pairs": sum(
            report["activation_class"] == "inactive_negative_control" for report in pair_reports
        ),
        "environment_failure_pairs": sum(
            report["activation_class"] == "environment_failure" for report in pair_reports
        ),
        "incomplete_pairs": sum(
            report["activation_class"] == "active" and not bool(report["denominator_eligible"])
            for report in pair_reports
        ),
        "eligible_pair_ids": [
            str(report["pair_id"])
            for report in pair_reports
            if report["denominator_eligible"]
        ],
        "excluded_pair_ids": [
            str(report["pair_id"])
            for report in pair_reports
            if not report["denominator_eligible"]
        ],
        "arithmetic_closed": len(pair_reports) == len(cases),
    }
    gates = {
        "pair_count_complete": len(pair_reports) == len(cases),
        "all_pairs_closed": bool(pair_reports) and all(
            report["denominator_eligible"]
            or report["activation_class"] == "inactive_negative_control"
            for report in pair_reports
        ),
        "inactive_negative_controls_valid": all(
            report["negative_control_valid"]
            for report in pair_reports
            if report["activation_class"] == "inactive_negative_control"
        ),
        "no_system_failures": not any(
            failure.get("system_gate_failed") for failure in failures
        ),
        "denominator_arithmetic_closed": bool(denominator["arithmetic_closed"]),
    }
    summary = {
        "schema_version": "statebus.semantic_state_ablation_summary.v1",
        "suite_id": "semantic_state_ablation_v1",
        "run_dir": str(run_root),
        "serial_execution": True,
        "case_count": len(cases),
        "variant_count": len(rows),
        "modes": list(modes),
        "case_ids": [case.task_id for case in cases],
        "rows": rows,
        "pairs": pair_reports,
        "denominator": denominator,
        "gates": gates,
        "failures": failures,
        "ok": all(gates.values()),
        "formal_campaign_eligible": False,
        "benchmark_superiority": "NOT_ESTABLISHED",
        "statistical_superiority": "NOT_ESTABLISHED",
        "claim_scope": "matched_semantic_state_mechanism_ablation_only",
    }
    (run_root / "manifest.json").write_text(stable_json_dumps({
        "schema_version": "statebus.semantic_state_ablation_manifest.v1",
        "suite_id": summary["suite_id"],
        "modes": list(modes),
        "case_ids": summary["case_ids"],
        "embedding_model_path": embedding_model_path,
        "embedding_device": embedding_device,
        "executor_consumer_policy": {
            "top_k": executor_top_k,
            "budget_bytes": executor_budget_bytes,
            "scope": "on_variant_only",
        },
        "provider_profile": "inherited_from_adaptive_formal_case",
        "lane_order": list(modes),
        "requested_feature_flags": {"semantic_state": "matched_" + "_".join(modes)},
        "tokenizer_path": tokenizer_path,
    }) + "\n", encoding="utf-8")
    (run_root / "rows.json").write_text(stable_json_dumps(rows) + "\n", encoding="utf-8")
    (run_root / "denominator.json").write_text(stable_json_dumps(denominator) + "\n", encoding="utf-8")
    (run_root / "summary.json").write_text(stable_json_dumps(summary) + "\n", encoding="utf-8")
    _write_ablation_markdown(summary, run_root / "summary.md")
    return summary


def run_semantic_holdout(
    *,
    output_root: Path,
    embedding_model_path: str,
    embedding_device: str,
    case_ids: tuple[str, ...] = (),
    max_cases: int = 0,
) -> dict[str, object]:
    available_cases = load_semantic_holdout_cases()
    cases = _select_semantic_holdout_cases(
        available_cases,
        case_ids=case_ids,
        max_cases=max_cases,
    )
    bounded_selection = bool(case_ids or max_cases > 0)
    run_root = output_root / f"semantic_holdout_{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns() % 1_000_000_000:09d}"
    run_root.mkdir(parents=True, exist_ok=False)
    adaptive_root = run_root / "cases"
    adaptive_root.mkdir()
    case_summaries: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for index, case in enumerate(cases, start=1):
        print(stable_json_dumps({
            "stage": "semantic_holdout_case_started",
            "case_index": index,
            "case_count": len(cases),
            "task_id": case.task_id,
        }), flush=True)
        try:
            case_summaries.append(_run_adaptive_case(
                case,
                case_root=adaptive_root / case.task_id,
                embedding_model_path=embedding_model_path,
                embedding_device=embedding_device,
            ))
        except Exception as exc:
            stage = _failure_stage(str(exc))
            category = _classify_failure(str(exc), stage=stage)
            failure = LaneFailure(
                lane=f"semantic-holdout:{case.task_id}",
                error_type=type(exc).__name__,
                error=str(exc),
                category=category,
                stage=stage,
                task_id=case.task_id,
                error_code=str(exc).split(":", 1)[0] or type(exc).__name__,
                system_gate_failed=category in _SYSTEM_FAILURE_CLASSES,
            ).canonical_payload()
            failures.append(failure)
            failure_path = adaptive_root / case.task_id / "failure.json"
            failure_path.parent.mkdir(parents=True, exist_ok=True)
            failure_path.write_text(stable_json_dumps(failure) + "\n", encoding="utf-8")
            traceback.print_exc()

    shape_by_id = {
        case.task_id: case.sample.scenario_tags[0]
        for case in cases
    }
    capability_counts = Counter(
        str(capability_id)
        for case in case_summaries
        for capability_id in case.get("selected_capability_ids", [])
    )
    case_rows: list[dict[str, object]] = []
    for case in case_summaries:
        selected = [str(item) for item in case.get("selected_capability_ids", [])]
        retriever = next((item for item in selected if item.startswith("retrieve_")), "")
        executor = next((item for item in selected if item.startswith("execute_")), "")
        semantic_selected = retriever == "retrieve_semantic_evidence_v1"
        case_rows.append({
            "task_id": case.get("task_id"),
            "input_shape": shape_by_id.get(str(case.get("task_id")), ""),
            "retriever_capability": retriever,
            "executor_capability": executor,
            "semantic_selected": semantic_selected,
            "semantic_state_gate": _semantic_state_case_gate(case) if semantic_selected else False,
            "gold_key_visibility_gate": _role_request_gold_key_gate(case),
            "expected_facts_passed": case.get("expected_facts_report", {}).get("passed", False),
            "system_gate_passed": case.get("system_gate_passed", False),
            "ok": bool(case.get("ok")),
            "summary_path": str(adaptive_root / str(case.get("task_id")) / "summary.json"),
        })
    semantic_rows = [row for row in case_rows if row["semantic_selected"]]
    freeze_audit = runtime_freeze_audit()
    gates = {
        "case_count_complete": len(case_summaries) == len(cases) and not failures,
        "quality_selected_complete": len(case_rows) == len(cases) and all(row["ok"] for row in case_rows),
        "semantic_capability_at_least_2": capability_counts["retrieve_semantic_evidence_v1"] >= 2,
        "table_capability_at_least_1": capability_counts["retrieve_table_evidence_v1"] >= 1,
        "semantic_state_cross_process_consumed": bool(semantic_rows) and all(
            row["semantic_state_gate"] for row in semantic_rows
        ),
        "benchmark_gold_hidden_from_role_requests": len(case_rows) == len(cases) and all(
            row["gold_key_visibility_gate"] for row in case_rows
        ),
        "runtime_freeze_unchanged": bool(freeze_audit["ok"]),
    }
    required_gates = (
        (
            "case_count_complete",
            "quality_selected_complete",
            "semantic_state_cross_process_consumed",
            "benchmark_gold_hidden_from_role_requests",
        )
        if bounded_selection
        else tuple(gates)
    )
    summary = {
        "schema_version": "statebus.semantic_holdout_summary.v1",
        "suite_id": "semantic_holdout_v1",
        "run_dir": str(run_root),
        "serial_execution": True,
        "case_count": len(cases),
        "available_case_count": len(available_cases),
        "attempted_case_count": len(case_summaries) + len(failures),
        "quality_pass_count": sum(bool(row["ok"]) for row in case_rows),
        "manifest_hash": sha256_digest(_MANIFEST_PATH.read_bytes()),
        "external_gold_hash": sha256_digest(_GOLD_PATH.read_bytes()),
        "benchmark_oracle_visible_to_roles": False,
        "capability_counts": dict(sorted(capability_counts.items())),
        "cases": case_rows,
        "runtime_freeze_audit": freeze_audit,
        "selection": {
            "mode": "bounded_diagnostic" if bounded_selection else "formal_full",
            "requested_case_ids": list(case_ids),
            "max_cases": max_cases,
            "selected_case_ids": [case.task_id for case in cases],
        },
        "gates": gates,
        "required_gates": list(required_gates),
        "failures": failures,
        "ok": all(gates[name] for name in required_gates),
        "formal_acceptance_eligible": not bounded_selection,
        "performance_claim_eligible": False,
        "benchmark_superiority": "NOT_ESTABLISHED",
        "statistical_superiority": "NOT_ESTABLISHED",
        "claim_scope": (
            "bounded_semantic_state_lifecycle_validation_only"
            if bounded_selection
            else "formal_semantic_holdout_quality_and_lifecycle"
        ),
    }
    (run_root / "summary.json").write_text(stable_json_dumps(summary) + "\n", encoding="utf-8")
    _write_markdown(summary, run_root / "summary.md")
    return summary
