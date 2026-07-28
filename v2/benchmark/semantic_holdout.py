from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import time
import traceback

from v2.benchmark.adaptive_formal import FormalAdaptiveCase, adapt_formal_sample
from v2.benchmark.adaptive_formal_mainline import (
    LaneFailure,
    _SYSTEM_FAILURE_CLASSES,
    _classify_failure,
    _failure_stage,
    _run_adaptive_case,
)
from v2.benchmark.contest_fairness import GOLD_ONLY_KEYS
from v2.benchmark.minimal_runner import MinimalBenchmarkSample
from v2.contracts import CanonicalTaskSpec
from v2.utils import sha256_digest, stable_json_dumps


_SAMPLE_ROOT = Path(__file__).with_name("samples") / "semantic_holdout"
_MANIFEST_PATH = _SAMPLE_ROOT / "manifest.json"
_GOLD_PATH = _SAMPLE_ROOT / "gold.json"
_FREEZE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/improvement/25_contest_evidence_closure_20260720/runtime_freeze_snapshot.json"
)
_FREEZE_DIRS = ("v2/runtime", "v2/control", "v2/state", "v2/memory")


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
    if not isinstance(raw_cases, list) or len(raw_cases) != 4:
        raise ValueError("semantic_holdout_requires_exactly_four_cases")
    if not isinstance(facts, dict):
        raise ValueError("semantic_holdout_gold_invalid")
    task_ids = [str(item.get("task_id", "")) for item in raw_cases if isinstance(item, dict)]
    if len(task_ids) != 4 or len(set(task_ids)) != 4 or set(task_ids) != set(facts):
        raise ValueError("semantic_holdout_manifest_gold_task_mismatch")
    input_shapes = Counter(str(item.get("input_shape", "")) for item in raw_cases)
    if input_shapes != Counter({
        "narrative_only": 2,
        "table_only": 1,
        "mixed_narrative_table": 1,
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
        project_root = Path(__file__).resolve().parents[2]
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
        for relative_dir in _FREEZE_DIRS
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
    for relative_dir in _FREEZE_DIRS:
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
        if not any(path.startswith(f"{relative_dir}/") for relative_dir in _FREEZE_DIRS)
    )
    if unknown_paths:
        raise ValueError(f"runtime_freeze_file_ledger_scope_invalid:{unknown_paths}")
    combined = hashlib.sha256()
    for relative_dir in _FREEZE_DIRS:
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

    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
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
    project_root = Path(__file__).resolve().parents[2]
    observed = {
        relative_dir: _directory_content_hash(project_root, relative_dir)
        for relative_dir in _FREEZE_DIRS
    }
    combined = hashlib.sha256()
    for relative_dir in _FREEZE_DIRS:
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
            for relative_dir in _FREEZE_DIRS
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
            and all(expected.get(item) == observed.get(item) for item in _FREEZE_DIRS)
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


def run_semantic_holdout(
    *,
    output_root: Path,
    embedding_model_path: str,
    embedding_device: str,
) -> dict[str, object]:
    cases = load_semantic_holdout_cases()
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
        "case_count_complete": len(case_summaries) == 4 and not failures,
        "quality_4_of_4": len(case_rows) == 4 and all(row["ok"] for row in case_rows),
        "semantic_capability_at_least_2": capability_counts["retrieve_semantic_evidence_v1"] >= 2,
        "table_capability_at_least_1": capability_counts["retrieve_table_evidence_v1"] >= 1,
        "semantic_state_cross_process_consumed": bool(semantic_rows) and all(
            row["semantic_state_gate"] for row in semantic_rows
        ),
        "benchmark_gold_hidden_from_role_requests": len(case_rows) == 4 and all(
            row["gold_key_visibility_gate"] for row in case_rows
        ),
        "runtime_freeze_unchanged": bool(freeze_audit["ok"]),
    }
    summary = {
        "schema_version": "statebus.semantic_holdout_summary.v1",
        "suite_id": "semantic_holdout_v1",
        "run_dir": str(run_root),
        "serial_execution": True,
        "case_count": 4,
        "attempted_case_count": len(case_summaries) + len(failures),
        "quality_pass_count": sum(bool(row["ok"]) for row in case_rows),
        "manifest_hash": sha256_digest(_MANIFEST_PATH.read_bytes()),
        "external_gold_hash": sha256_digest(_GOLD_PATH.read_bytes()),
        "benchmark_oracle_visible_to_roles": False,
        "capability_counts": dict(sorted(capability_counts.items())),
        "cases": case_rows,
        "runtime_freeze_audit": freeze_audit,
        "gates": gates,
        "failures": failures,
        "ok": all(gates.values()),
    }
    (run_root / "summary.json").write_text(stable_json_dumps(summary) + "\n", encoding="utf-8")
    _write_markdown(summary, run_root / "summary.md")
    return summary
