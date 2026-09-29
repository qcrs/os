from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from statebus.benchmark.models import QualityFloorResult
from statebus.utils import stable_json_dumps


C2B_EVALUATOR_ID = "statebus.benchmark.scoring.score_benchmark_output@c2b-evaluator-v1"


@dataclass(frozen=True)
class FixedAnswerLaneResult:
    task_id: str
    route: str
    tool_name: str
    summary_text: str
    revenue_value: str
    selected_doc_hashes: tuple[str, ...]
    supporting_doc_ids: tuple[str, ...] = ()
    contamination_detected: bool = False
    metric_name: str = ""
    metric_value: str = ""


@dataclass(frozen=True)
class FixedAnswerScore:
    route_exact: bool
    tool_exact: bool
    revenue_exact: bool
    selected_doc_hashes_exact: bool
    summary_present: bool
    exact_match: bool
    admissible_match: bool
    correctness_label: str
    quality_floor: QualityFloorResult
    metric_name_exact: bool = False
    metric_value_exact: bool = False


@dataclass(frozen=True)
class BenchmarkGoldScore:
    passed: bool
    expected_facts_passed: bool
    quality_checks_passed: bool
    failures: tuple[str, ...] = ()

    def canonical_payload(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "expected_facts_passed": self.expected_facts_passed,
            "quality_checks_passed": self.quality_checks_passed,
            "failures": list(self.failures),
            "evaluation_boundary": "post_runtime_benchmark_scoring",
            "runtime_decision_input": False,
        }


def _lookup_output_value(output_payload: dict[str, object], key: str) -> object:
    if key in output_payload:
        return output_payload.get(key)
    current: object = output_payload
    for segment in key.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _numeric_equal(observed: object, expected: object) -> bool:
    if str(observed) == str(expected):
        return True
    try:
        return float(str(observed)) == float(str(expected))
    except (TypeError, ValueError):
        return False


def _score_expected_facts(
    *,
    output_payload: dict[str, object],
    expected_facts: dict[str, object],
) -> tuple[bool, tuple[str, ...]]:
    failures: list[str] = []
    for key, expected_value in expected_facts.items():
        observed_value = _lookup_output_value(output_payload, key)
        if observed_value is not None:
            if not _numeric_equal(observed_value, expected_value):
                failures.append(f"expected_fact_mismatch:{key}")
            continue
        if key.endswith("_min"):
            field_name = key.removesuffix("_min")
            observed_value = _lookup_output_value(output_payload, field_name)
            try:
                passed = observed_value not in {None, ""} and float(str(observed_value)) >= float(
                    str(expected_value)
                )
            except (TypeError, ValueError):
                passed = False
            if not passed:
                failures.append(f"expected_minimum_failed:{field_name}")
            continue
        if key.endswith("_max"):
            field_name = key.removesuffix("_max")
            observed_value = _lookup_output_value(output_payload, field_name)
            try:
                passed = observed_value not in {None, ""} and float(str(observed_value)) <= float(
                    str(expected_value)
                )
            except (TypeError, ValueError):
                passed = False
            if not passed:
                failures.append(f"expected_maximum_failed:{field_name}")
            continue
        failures.append(f"expected_fact_missing:{key}")
    return not failures, tuple(failures)


def _score_quality_checks(
    *,
    output_payload: dict[str, object],
    output_path: Path,
    quality_checks: tuple[str, ...],
) -> tuple[bool, tuple[str, ...]]:
    failures: list[str] = []
    workspace_root = output_path.parents[1] if len(output_path.parents) > 1 else output_path.parent
    for check in quality_checks:
        parts = check.split(":")
        kind = parts[0] if parts else ""
        passed = False
        if kind == "artifact_exists" and len(parts) == 2:
            relpath = str(_lookup_output_value(output_payload, parts[1]) or "").strip()
            passed = bool(relpath) and (workspace_root / relpath).is_file()
        elif kind in {"field_present", "exact"} and len(parts) == 2:
            value = _lookup_output_value(output_payload, parts[1])
            passed = value is not None and value != ""
        elif kind == "numeric_tolerance" and len(parts) == 3:
            try:
                float(str(_lookup_output_value(output_payload, parts[1])))
                float(parts[2])
                passed = True
            except (TypeError, ValueError):
                passed = False
        elif kind == "contains" and len(parts) >= 3:
            observed = str(_lookup_output_value(output_payload, parts[1]) or "")
            passed = ":".join(parts[2:]).lower() in observed.lower()
        elif kind == "field_gte" and len(parts) == 3:
            observed = _lookup_output_value(output_payload, parts[1])
            try:
                passed = observed not in {None, ""} and float(str(observed)) >= float(parts[2])
            except (TypeError, ValueError):
                passed = False
        if not passed:
            failures.append(f"quality_check_failed:{check}")
    return not failures, tuple(failures)


def score_benchmark_output(
    *,
    output_payload: dict[str, object],
    output_path: Path,
    expected_facts: dict[str, object] | None = None,
    quality_checks: tuple[str, ...] = (),
) -> BenchmarkGoldScore:
    """Evaluate benchmark-only gold after the Runtime has completed."""

    facts_passed, fact_failures = _score_expected_facts(
        output_payload=output_payload,
        expected_facts=dict(expected_facts or {}),
    )
    checks_passed, check_failures = _score_quality_checks(
        output_payload=output_payload,
        output_path=output_path,
        quality_checks=tuple(quality_checks),
    )
    failures = (*fact_failures, *check_failures)
    return BenchmarkGoldScore(
        passed=facts_passed and checks_passed,
        expected_facts_passed=facts_passed,
        quality_checks_passed=checks_passed,
        failures=failures,
    )


def _c2c_validate_pair_claim(
    *,
    baseline: dict[str, object],
    c1: dict[str, object],
    denominator: dict[str, object] | None = None,
) -> dict[str, object]:
    """Validate, but never create, a C2-C provider-baseline claim."""
    failures: list[str] = []
    for key in (
        "task_contract_hash",
        "input_lineage_hashes",
        "quality_contract_hash",
        "deterministic_seed",
        "family_id",
        "round_number",
        "repeat_id",
    ):
        if baseline.get(key) != c1.get(key):
            failures.append(f"pair_equivalence_mismatch:{key}")
    if baseline.get("memory_policy") != "off":
        failures.append("baseline_memory_policy_not_off")
    if baseline.get("runtime_memory_policy") not in {"", "none"}:
        failures.append("baseline_runtime_memory_policy_not_none")
    for key in ("runtime_root", "workspace_root", "memory_root", "session_id", "attempt_id", "cache_epoch"):
        if not str(baseline.get(key, "")) or not str(c1.get(key, "")):
            failures.append(f"pair_identity_missing:{key}")
        elif baseline.get(key) == c1.get(key):
            failures.append(f"pair_identity_not_separate:{key}")

    provider_value = baseline.get("provider_invocation_evidence", {})
    provider = dict(provider_value) if isinstance(provider_value, Mapping) else {}
    if (
        provider.get("status") != "observed"
        or provider.get("invocation_status") not in {"started", "completed"}
        or not str(provider.get("provider_id", ""))
        or not str(provider.get("invocation_id", ""))
        or not str(provider.get("evidence_hash", ""))
    ):
        failures.append("baseline_provider_invocation_evidence_missing")

    observation_value = c1.get("provider_not_started_observation", {})
    observation = dict(observation_value) if isinstance(observation_value, Mapping) else {}
    if (
        c1.get("runtime_authority") != "AdaptiveRuntimeEngine"
        or observation.get("status") != "observed"
        or observation.get("provider_invocation_status") != "not_started"
        or not str(observation.get("observation_id", ""))
        or not str(observation.get("created_at_ns", ""))
        or not str(observation.get("execution_binding_hash", ""))
        or not str(observation.get("capability_grant_hash", ""))
    ):
        failures.append("runtime_provider_not_started_observation_missing")

    baseline_quality_value = baseline.get("quality_evidence", {})
    c1_quality_value = c1.get("quality_evidence", {})
    baseline_quality = dict(baseline_quality_value) if isinstance(baseline_quality_value, Mapping) else {}
    c1_quality = dict(c1_quality_value) if isinstance(c1_quality_value, Mapping) else {}
    if baseline_quality.get("status") != "observed" or not baseline_quality.get("passed"):
        failures.append("baseline_quality_evidence_missing_or_failed")
    if c1_quality.get("status") != "observed" or not c1_quality.get("passed"):
        failures.append("c1_quality_evidence_missing_or_failed")
    if not str(baseline_quality.get("report_hash", "")) or not str(c1_quality.get("report_hash", "")):
        failures.append("quality_report_hash_missing")
    if str(c1_quality.get("report_hash", "")) != str(observation.get("quality_report_hash", "")):
        failures.append("c1_observation_quality_join_missing")

    baseline_admission_value = baseline.get("result_admission", {})
    c1_admission_value = c1.get("result_admission", {})
    baseline_admission = dict(baseline_admission_value) if isinstance(baseline_admission_value, Mapping) else {}
    c1_admission = dict(c1_admission_value) if isinstance(c1_admission_value, Mapping) else {}
    for label, admission in (("baseline", baseline_admission), ("c1", c1_admission)):
        if admission.get("status") != "observed" or not str(admission.get("receipt_hash", "")):
            failures.append(f"{label}_result_admission_missing")
    c1_admission_hash = str(c1_admission.get("receipt_hash", ""))
    if str(observation.get("attempt_result_admission_receipt_hash", "")) != c1_admission_hash:
        failures.append("c1_skip_observation_result_admission_join_missing")
    for key in (
        "memory_admission_receipt_hash",
        "replay_eligibility_receipt_hash",
        "quality_report_hash",
    ):
        if not str(observation.get(key, "")):
            failures.append(f"c1_observation_{key}_missing")
    source_receipts = [
        str(item)
        for item in (
            provider.get("evidence_hash", ""),
            observation.get("observation_id", ""),
            observation.get("attempt_result_admission_receipt_hash", ""),
            observation.get("memory_admission_receipt_hash", ""),
            observation.get("replay_eligibility_receipt_hash", ""),
            observation.get("execution_binding_hash", ""),
            observation.get("capability_grant_hash", ""),
            baseline_admission.get("receipt_hash", ""),
            c1_admission.get("receipt_hash", ""),
            baseline_quality.get("report_hash", ""),
            c1_quality.get("report_hash", ""),
        )
        if str(item)
    ]
    denominator_ok = denominator is None or bool(denominator.get("arithmetic_closed"))
    if not denominator_ok:
        failures.append("denominator_not_closed")
    quality_non_regression = {
        "status": "observed" if not failures and baseline_quality.get("passed") and c1_quality.get("passed") else "unsupported",
        "passed": not failures and bool(baseline_quality.get("passed")) and bool(c1_quality.get("passed")),
        "reason": "" if not failures else "no_matched_baseline",
    }
    return {
        "status": "eligible" if not failures else "rejected",
        "reason": "" if not failures else failures[0],
        "failures": failures,
        "quality_non_regression": quality_non_regression,
        "source_receipt_hashes": sorted(set(source_receipts)),
    }


def _g6b_validate_pair_equivalence(
    *,
    baseline: Mapping[str, object],
    c1: Mapping[str, object],
) -> dict[str, object]:
    """Validate the frozen G6-B pair contract without creating Runtime facts."""
    baseline = dict(baseline)
    c1 = dict(c1)

    def nonempty_string(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip()) and value.strip() != "None"

    def positive_integer(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    def valid_lineage(value: object) -> bool:
        return (
            isinstance(value, (list, tuple))
            and bool(value)
            and all(nonempty_string(item) for item in value)
        )

    from statebus.utils import sha256_digest

    provider_value = baseline.get("provider_invocation_evidence", {})
    observation_value = c1.get("provider_not_started_observation", {})
    baseline_quality_value = baseline.get("quality_evidence", {})
    c1_quality_value = c1.get("quality_evidence", {})
    baseline_admission_value = baseline.get("result_admission", {})
    c1_admission_value = c1.get("result_admission", {})
    provider = dict(provider_value) if isinstance(provider_value, Mapping) else {}
    observation = dict(observation_value) if isinstance(observation_value, Mapping) else {}
    baseline_quality = dict(baseline_quality_value) if isinstance(baseline_quality_value, Mapping) else {}
    c1_quality = dict(c1_quality_value) if isinstance(c1_quality_value, Mapping) else {}
    baseline_admission = dict(baseline_admission_value) if isinstance(baseline_admission_value, Mapping) else {}
    c1_admission = dict(c1_admission_value) if isinstance(c1_admission_value, Mapping) else {}

    string_identity_fields = (
        "task_contract_hash",
        "quality_contract_hash",
        "family_id",
        "runtime_root",
        "workspace_root",
        "memory_root",
        "session_id",
        "attempt_id",
        "cache_epoch",
    )
    integer_identity_fields = ("deterministic_seed", "round_number", "repeat_id")
    checks: dict[str, bool] = {}
    for side, row in (("baseline", baseline), ("c1", c1)):
        for field in string_identity_fields:
            checks[f"{side}_required_{field}"] = field in row and nonempty_string(row[field])
        for field in integer_identity_fields:
            checks[f"{side}_required_{field}"] = field in row and positive_integer(row[field])
        checks[f"{side}_required_input_lineage_hashes"] = (
            "input_lineage_hashes" in row and valid_lineage(row["input_lineage_hashes"])
        )

    equality_fields = (
        "task_contract_hash",
        "input_lineage_hashes",
        "quality_contract_hash",
        "deterministic_seed",
        "family_id",
        "round_number",
        "repeat_id",
    )
    for field in equality_fields:
        checks[field] = (
            checks[f"baseline_required_{field}"]
            and checks[f"c1_required_{field}"]
            and baseline[field] == c1[field]
        )

    checks.update({
        "baseline_memory_policy": (
            baseline.get("lane") == "memory-off"
            and baseline.get("memory_policy") == "off"
            and baseline.get("runtime_memory_policy") == "none"
        ),
        "replay_memory_policy": (
            c1.get("lane") == "validated-replay"
            and c1.get("memory_policy") == "validated_replay"
            and c1.get("runtime_memory_policy") == "validated_replay"
        ),
        "terminal_status_gate": all(
            "terminal_status" not in row or row.get("terminal_status") == "success"
            for row in (baseline, c1)
        ),
    })

    separation_fields = (
        "runtime_root",
        "workspace_root",
        "memory_root",
        "session_id",
        "attempt_id",
        "cache_epoch",
    )
    checks["root_session_attempt_cache_separation"] = all(
        checks[f"baseline_required_{field}"]
        and checks[f"c1_required_{field}"]
        and baseline.get(field) != c1.get(field)
        for field in separation_fields
    )
    checks["baseline_provider_invocation"] = (
        isinstance(provider_value, Mapping)
        and provider.get("status") == "observed"
        and provider.get("invocation_status") in {"started", "completed"}
        and nonempty_string(provider.get("provider_id"))
        and nonempty_string(provider.get("invocation_id"))
        and nonempty_string(provider.get("evidence_hash"))
        and nonempty_string(provider.get("request_hash"))
        and nonempty_string(provider.get("candidate_hash"))
        and provider.get("source") == "Runtime provider call boundary"
    )
    checks["c1_provider_not_started"] = (
        isinstance(observation_value, Mapping)
        and c1.get("runtime_authority") == "AdaptiveRuntimeEngine"
        and observation.get("status") == "observed"
        and observation.get("provider_invocation_status") == "not_started"
        and nonempty_string(observation.get("observation_id"))
        and isinstance(observation.get("created_at_ns"), int)
        and not isinstance(observation.get("created_at_ns"), bool)
        and observation.get("created_at_ns", -1) >= 0
        and nonempty_string(observation.get("execution_binding_hash"))
        and nonempty_string(observation.get("capability_grant_hash"))
        and nonempty_string(observation.get("memory_admission_receipt_hash"))
        and nonempty_string(observation.get("replay_eligibility_receipt_hash"))
        and nonempty_string(observation.get("quality_report_hash"))
        and nonempty_string(observation.get("attempt_result_admission_receipt_hash"))
    )
    checks["quality"] = (
        isinstance(baseline_quality_value, Mapping)
        and isinstance(c1_quality_value, Mapping)
        and baseline_quality.get("status") == "observed"
        and baseline_quality.get("passed") is True
        and nonempty_string(baseline_quality.get("report_hash"))
        and c1_quality.get("status") == "observed"
        and c1_quality.get("passed") is True
        and nonempty_string(c1_quality.get("report_hash"))
        and c1_quality.get("report_hash") == observation.get("quality_report_hash")
    )
    checks["result_admission"] = (
        isinstance(baseline_admission_value, Mapping)
        and isinstance(c1_admission_value, Mapping)
        and baseline_admission.get("status") == "observed"
        and nonempty_string(baseline_admission.get("receipt_hash"))
        and c1_admission.get("status") == "observed"
        and nonempty_string(c1_admission.get("receipt_hash"))
        and c1_admission.get("receipt_hash")
        == observation.get("attempt_result_admission_receipt_hash")
    )
    checks["recipe_step_not_promoted"] = observation.get("recipe_step_status") != "not_executed"
    checks["recipe_recomputed"] = c1.get("recipe_recomputed") is True
    checks["artifact_restore_not_promoted"] = observation.get("artifact_restore_status") in {
        "",
        "not_applicable",
        None,
    }
    grant_value = c1.get("capability_grant", {})
    binding_value = c1.get("execution_binding", {})
    consumption_value = c1.get("memory_consumption_receipt", {})
    eligibility_value = c1.get("replay_eligibility_receipt", {})
    grant = dict(grant_value) if isinstance(grant_value, Mapping) else {}
    binding = dict(binding_value) if isinstance(binding_value, Mapping) else {}
    consumption = dict(consumption_value) if isinstance(consumption_value, Mapping) else {}
    eligibility = dict(eligibility_value) if isinstance(eligibility_value, Mapping) else {}
    checks["c1_receipt_binding_join"] = (
        bool(grant)
        and bool(binding)
        and bool(consumption)
        and bool(eligibility)
        and sha256_digest(grant) == observation.get("capability_grant_hash")
        and sha256_digest(binding) == observation.get("execution_binding_hash")
        and consumption.get("memory_admission_receipt_hash")
        == observation.get("memory_admission_receipt_hash")
        and consumption.get("replay_eligibility_receipt_hash")
        == observation.get("replay_eligibility_receipt_hash")
        and consumption.get("attempt_result_admission_receipt_hash")
        == observation.get("attempt_result_admission_receipt_hash")
        and sha256_digest(eligibility) == observation.get("replay_eligibility_receipt_hash")
    )

    failures = [f"pair_equivalence_failed:{name}" for name, passed in checks.items() if not passed]
    source_receipts = sorted({
        value
        for value in (
            provider.get("evidence_hash"),
            observation.get("observation_id"),
            observation.get("execution_binding_hash"),
            observation.get("capability_grant_hash"),
            observation.get("memory_admission_receipt_hash"),
            observation.get("replay_eligibility_receipt_hash"),
            observation.get("quality_report_hash"),
            observation.get("attempt_result_admission_receipt_hash"),
            baseline_quality.get("report_hash"),
            c1_quality.get("report_hash"),
            baseline_admission.get("receipt_hash"),
            c1_admission.get("receipt_hash"),
        )
        if nonempty_string(value)
    })
    return {
        "status": "eligible" if not failures else "rejected",
        "reason": "" if not failures else failures[0],
        "failures": failures,
        "equivalence_checks": checks,
        "baseline_terminal_status": baseline.get("terminal_status"),
        "replay_terminal_status": c1.get("terminal_status"),
        "quality_non_regression": {
            "status": "observed" if not failures else "unsupported",
            "passed": not failures,
            "reason": "" if not failures else "pair_quality_or_equivalence_failed",
        },
        "source_receipt_hashes": source_receipts,
    }


def _g6b_validate_campaign_claim(
    projection: Mapping[str, object],
    *,
    stage: str,
) -> dict[str, object]:
    """Recompute every load-bearing B0/B1 acceptance gate from raw projections."""
    projection = dict(projection)
    manifest_value = projection.get("campaign_manifest", {})
    denominator_value = projection.get("denominator", {})
    metrics_value = projection.get("metrics", {})
    manifest = dict(manifest_value) if isinstance(manifest_value, Mapping) else {}
    denominator = dict(denominator_value) if isinstance(denominator_value, Mapping) else {}
    metrics = dict(metrics_value) if isinstance(metrics_value, Mapping) else {}
    pair_rules_value = projection.get("pair_equivalence_rules", {})
    protected_value = projection.get("protected_diff_status", {})
    focused_value = projection.get("focused_test_status", {})
    artifact_refs_value = projection.get("artifact_references", {})
    pair_rules = dict(pair_rules_value) if isinstance(pair_rules_value, Mapping) else {}
    protected = dict(protected_value) if isinstance(protected_value, Mapping) else {}
    focused = dict(focused_value) if isinstance(focused_value, Mapping) else {}
    artifact_refs = dict(artifact_refs_value) if isinstance(artifact_refs_value, Mapping) else {}
    baseline_rows = [dict(row) for row in projection.get("baseline_rows", ()) if isinstance(row, Mapping)]
    c1_rows = [dict(row) for row in projection.get("c1_rows", ()) if isinstance(row, Mapping)]
    pairings = [dict(row) for row in projection.get("pairings", ()) if isinstance(row, Mapping)]
    failure_rows = [dict(row) for row in projection.get("failure_rows", ()) if isinstance(row, Mapping)]
    failures: list[str] = []
    checks: dict[str, dict[str, object]] = {}

    def record(name: str, passed: bool, artifact: str, reason: str) -> None:
        checks[name] = {
            "passed": passed,
            "artifact": artifact,
            "reason": "" if passed else reason,
        }
        if not passed:
            failures.append(reason)

    pair_key_fields = [
        "task_contract_hash",
        "input_lineage_hashes",
        "quality_contract_hash",
        "deterministic_seed",
    ]
    pair_key_excluded_fields = [
        "lane",
        "family_id",
        "round_number",
        "repeat_id",
        "cache_epoch",
    ]
    denominator_dimensions = ["lane", "family_id", "round_number", "repeat_id", "cache_epoch"]
    denominator_count_fields = [
        "baseline_row_count",
        "c1_row_count",
        "matched_pair_count",
        "eligible_matched_pair_count",
        "unmatched_row_count",
        "attempted",
        "success",
        "unsupported",
        "policy_reject",
        "runtime_fail",
        "timeout",
        "quality_fail",
        "environment_fail",
    ]
    required_pair_fields = [
        "task_contract_hash",
        "input_lineage_hashes",
        "quality_contract_hash",
        "deterministic_seed",
        "family_id",
        "round_number",
        "repeat_id",
        "runtime_root",
        "workspace_root",
        "memory_root",
        "session_id",
        "attempt_id",
        "cache_epoch",
        "provider_invocation_evidence",
        "provider_not_started_observation",
        "quality_evidence",
        "result_admission",
    ]
    rejection_conditions = [
        "missing_or_invalid_frozen_pair_identity",
        "duplicate_side_for_pair_key",
        "missing_opposite_lane",
        "family_round_or_repeat_mismatch",
        "baseline_or_replay_policy_mismatch",
        "root_session_attempt_or_cache_epoch_not_separate",
        "baseline_provider_call_boundary_evidence_missing",
        "runtime_owned_replay_not_started_observation_missing",
        "terminal_status_not_success",
        "quality_evidence_missing_or_failed",
        "result_admission_join_missing",
        "recipe_step_or_exact_restore_claim_promoted",
    ]

    record(
        "pair_identity_contract",
        manifest.get("pair_key_algorithm") == "existing _c2c_pair_key"
        and manifest.get("pair_key_fields") == pair_key_fields
        and manifest.get("pair_key_excluded_fields") == pair_key_excluded_fields,
        str(artifact_refs.get("pair_identity", "manifest.json")),
        "pair_identity_contract_incomplete",
    )
    record(
        "pair_equivalence_rules",
        pair_rules.get("status") == "frozen"
        and pair_rules.get("pair_key_fields") == pair_key_fields
        and pair_rules.get("pair_key_excluded_fields") == pair_key_excluded_fields
        and pair_rules.get("required_fields") == required_pair_fields
        and pair_rules.get("rejection_conditions") == rejection_conditions,
        str(artifact_refs.get("pair_equivalence", "pair_equivalence_rules.json")),
        "pair_equivalence_rules_incomplete",
    )
    record(
        "denominator_contract",
        manifest.get("denominator_dimensions") == denominator_dimensions
        and manifest.get("denominator_count_fields") == denominator_count_fields
        and all(field in denominator for field in denominator_count_fields),
        str(artifact_refs.get("denominator", "failure_denominator.json")),
        "denominator_dimensions_or_counts_incomplete",
    )

    all_rows = [*baseline_rows, *c1_rows]
    row_ids = [row.get("row_id") for row in all_rows]
    matched = [row for row in pairings if row.get("status") in {"eligible", "rejected"}]
    eligible = [row for row in matched if row.get("status") == "eligible"]
    rejected = [row for row in matched if row.get("status") == "rejected"]
    unmatched_ids = {
        row.get("row_id")
        for row in failure_rows
        if row.get("status") == "unmatched" and isinstance(row.get("row_id"), str) and row.get("row_id")
    }
    terminal_statuses = [row.get("terminal_status") for row in all_rows]
    expected_counts = {
        "baseline_row_count": len(baseline_rows),
        "c1_row_count": len(c1_rows),
        "matched_pair_count": len(matched),
        "eligible_matched_pair_count": len(eligible),
        "unmatched_row_count": len(unmatched_ids),
        "attempted": len(all_rows),
        "success": terminal_statuses.count("success"),
        "unsupported": terminal_statuses.count("unsupported"),
        "policy_reject": terminal_statuses.count("policy_reject"),
        "runtime_fail": terminal_statuses.count("runtime_fail"),
        "timeout": terminal_statuses.count("timeout"),
        "quality_fail": terminal_statuses.count("quality_fail"),
        "environment_fail": terminal_statuses.count("environment_fail"),
    }
    linked_row_ids = {
        row_id
        for pair in matched
        for row_id in (pair.get("baseline_row_id"), pair.get("replay_row_id"))
        if isinstance(row_id, str) and row_id
    } | unmatched_ids
    denominator_recomputed = (
        all(isinstance(row_id, str) and bool(row_id) for row_id in row_ids)
        and len(row_ids) == len(set(row_ids))
        and set(row_ids) == linked_row_ids
        and len(all_rows) == 2 * len(matched) + len(unmatched_ids)
        and len(matched) == len(eligible) + len(rejected)
        and all(denominator.get(name) == value for name, value in expected_counts.items())
        and denominator.get("row_ids") == row_ids
        and denominator.get("arithmetic_closed") is True
        and denominator.get("row_arithmetic_closed") is True
    )
    record(
        "denominator_raw_row_recomputation",
        denominator_recomputed,
        str(artifact_refs.get("denominator", "failure_denominator.json")),
        "denominator_not_recomputable_from_raw_rows",
    )

    from statebus.benchmark.metric_aggregation import _g6b_metric_availability

    recomputed_metrics = _g6b_metric_availability(pairings, denominator, stage=stage)
    metric_structure_valid = all(
        isinstance(metric, Mapping)
        and metric.get("status") in {"observed", "unsupported", "not_applicable", "rejected", "deferred"}
        and "value" in metric
        and isinstance(metric.get("reason"), str)
        and isinstance(metric.get("source_receipt_hashes"), list)
        and all(isinstance(item, str) and bool(item) for item in metric.get("source_receipt_hashes", ()))
        and (metric.get("status") != "observed" or bool(metric.get("source_receipt_hashes")))
        for metric in metrics.values()
    )
    record(
        "metric_availability_from_raw_evidence",
        metrics == recomputed_metrics and metric_structure_valid,
        str(artifact_refs.get("metrics", "metric_availability.json")),
        "metric_status_not_supported_by_raw_evidence",
    )

    fixed_metrics = {
        "exact_replay": ("unsupported", "c2_exact_restore_not_implemented"),
        "recipe_step_skip": ("deferred", "recipe_step_skip_deferred_to_c2"),
        "verified_recipe_work_avoided": ("unsupported", "recipe_step_skip_deferred_to_c2"),
    }
    fixed_boundaries_valid = True
    for name, (status, reason) in fixed_metrics.items():
        value = metrics.get(name, {})
        metric = dict(value) if isinstance(value, Mapping) else {}
        if metric.get("status") != status or metric.get("value") is not None or metric.get("reason") != reason:
            fixed_boundaries_valid = False
    fixed_manifest_payloads = all(
        isinstance(manifest.get(name), Mapping)
        and manifest[name].get("status") == status
        and manifest[name].get("value") is None
        and manifest[name].get("reason") == reason
        for name, (status, reason) in fixed_metrics.items()
    )
    record(
        "deferred_and_live_boundaries",
        fixed_boundaries_valid
        and fixed_manifest_payloads
        and manifest.get("live_vllm_gpu_validation") == "NOT_RUN"
        and manifest.get("benchmark_superiority") == "NOT_ESTABLISHED"
        and manifest.get("memfd_limitation") == "skipped: memfd unavailable; SHM actual-read retained",
        str(artifact_refs.get("metrics", "metric_availability.json")),
        "fixed_metric_or_live_boundary_changed",
    )

    protected_keys = (
        "runtime",
        "memory",
        "control",
        "state",
        "refs",
        "contracts",
        "protocol",
        "authority",
        "terminal_semantics",
    )
    unchanged_status = "UNCHANGED_BY_G6B0" if stage == "G6-B0" else "UNCHANGED_BY_G6B1"
    record(
        "protected_source_gates",
        all(protected.get(key) == unchanged_status for key in protected_keys),
        str(artifact_refs.get("protected_sources", "runtime_memory_contract_protocol_diff_status.json")),
        "protected_source_gate_incomplete_or_changed",
    )
    record(
        "focused_tests",
        focused.get("status") == "passed",
        str(artifact_refs.get("focused_tests", "focused_test_status.json")),
        "focused_tests_not_passed",
    )

    if stage == "G6-B0":
        record(
            "b0_contains_no_campaign_rows",
            not baseline_rows and not c1_rows and not pairings and not failure_rows,
            "baseline_rows.json+c1_rows.json+pair_validation.json+negative_unmatched_rows.json",
            "b1_campaign_data_present_in_b0",
        )
        provider_value = metrics.get("provider_work_avoided", {})
        provider = dict(provider_value) if isinstance(provider_value, Mapping) else {}
        record(
            "b0_provider_work_boundary",
            provider == {
            "status": "unsupported",
            "value": None,
            "reason": "no_matched_baseline_or_runtime_skip_receipt",
            "source_receipt_hashes": [],
            },
            str(artifact_refs.get("metrics", "metric_availability.json")),
            "b0_provider_work_boundary_changed",
        )
    elif stage == "G6-B1":
        coverage_value = projection.get("coverage", {})
        coverage = dict(coverage_value) if isinstance(coverage_value, Mapping) else {}
        slot_manifest_value = manifest.get("pair_slot_manifest", {})
        slot_manifest = dict(slot_manifest_value) if isinstance(slot_manifest_value, Mapping) else {}
        expected_slots = {
            (
                str(row.get("family_id", "")),
                row.get("round_number"),
                row.get("repeat_id"),
            )
            for row in slot_manifest.get("slots", ())
            if isinstance(row, Mapping)
        }
        eligible_slots = {
            (
                str(row.get("family_id", "")),
                row.get("round_number"),
                row.get("repeat_id"),
            )
            for row in eligible
        }
        record(
            "b1_coverage",
            denominator.get("eligible_matched_pair_count", 0) >= 12
            and coverage.get("families", 0) >= 2
            and coverage.get("rounds", 0) >= 2
            and coverage.get("repeats", 0) >= 3
            and len(expected_slots) == 12
            and eligible_slots == expected_slots
            and len(eligible) == len(eligible_slots),
            "failure_denominator.json+pair_validation.json",
            "b1_coverage_below_frozen_minimum",
        )
        evidence_names = (
            "eligible_matched_pair_count",
            "baseline_provider_invocation_count",
            "replay_provider_not_started_count",
        )
        record(
            "b1_runtime_evidence_complete",
            all(
                isinstance(metrics.get(name), Mapping)
                and metrics[name].get("status") == "observed"
                and metrics[name].get("value") == len(eligible)
                for name in evidence_names
            )
            and all(pair.get("status") == "eligible" for pair in eligible),
            "metric_availability.json+pair_validation.json",
            "b1_runtime_evidence_incomplete",
        )
        required_negative_reasons = {
            "required_unmatched_baseline",
            "missing_pair_identity",
            "duplicate_pair_key",
            "quality_failure",
            "result_admission_failure",
            "runtime_failure",
            "runtime_policy_failure",
            "rejected_pair",
        }
        retained_negative_reasons = {
            str(row.get("reason", "")) for row in failure_rows
        }
        unmatched_baseline_families = {
            str(row.get("family_id", ""))
            for row in failure_rows
            if row.get("side") == "baseline"
            and row.get("status") == "unmatched"
        }
        record(
            "b1_negative_rows_retained",
            required_negative_reasons <= retained_negative_reasons
            and {"cross_period_financial", "incident_diagnosis"}
            <= unmatched_baseline_families
            and bool(rejected),
            "negative_row_index.json+failure_denominator.json",
            "b1_negative_rows_incomplete",
        )
        quality_value = metrics.get("quality_non_regression", {})
        quality = dict(quality_value) if isinstance(quality_value, Mapping) else {}
        provider_value = metrics.get("provider_work_avoided", {})
        provider = dict(provider_value) if isinstance(provider_value, Mapping) else {}
        record(
            "b1_positive_numerator",
            quality.get("status") == "observed"
            and quality.get("value") is True
            and quality.get("passed_pair_count") == len(eligible)
            and provider.get("status") == "observed"
            and provider.get("value") == len(eligible),
            "quality_evidence.json+metric_availability.json",
            "b1_positive_numerator_not_receipt_backed",
        )
    else:
        record("supported_stage", False, "manifest.json", "unsupported_g6b_stage")

    return {
        "status": "accepted" if not failures else "rejected",
        "stage_status": f"{stage.removeprefix('G6-').replace('-', '')}_ACCEPTED" if not failures else "FAILED",
        "failures": failures,
        "checks": checks,
    }


def score_c2b_case(
    *,
    family_id: str,
    output_payload: dict[str, object],
    output_path: Path,
    expected_facts: dict[str, object],
    quality_checks: tuple[str, ...] = (),
) -> dict[str, object]:
    """Sealed post-runtime scorer projection for one C2B positive/holdout row."""
    score = score_benchmark_output(
        output_payload=output_payload,
        output_path=output_path,
        expected_facts=expected_facts,
        quality_checks=quality_checks,
    )
    return {
        "schema_version": "statebus.c2b.scorer_result.v1",
        "evaluator_identity": C2B_EVALUATOR_ID,
        "family_id": family_id,
        **score.canonical_payload(),
    }


def expected_facts_for_scoring(
    *,
    expected_facts: dict[str, object],
    metric_projection_key: str = "",
) -> dict[str, object]:
    projected = dict(expected_facts)
    if not metric_projection_key or projected.get("metric_name") or projected.get("metric_value"):
        return projected
    if metric_projection_key in projected:
        current: object = projected[metric_projection_key]
    else:
        current = projected
        for segment in metric_projection_key.split("."):
            if not isinstance(current, dict) or segment not in current:
                return projected
            current = current[segment]
    projected["metric_name"] = metric_projection_key
    projected["metric_value"] = (
        stable_json_dumps(current)
        if isinstance(current, (dict, list, tuple))
        else str(current)
    )
    return projected


def score_fixed_answer_case(
    *,
    observed: FixedAnswerLaneResult,
    expected_route: str,
    expected_tool_name: str,
    expected_facts: dict[str, object],
) -> FixedAnswerScore:
    expected_metric_name = str(expected_facts.get("metric_name", "")).strip()
    expected_metric_value = str(
        expected_facts.get("metric_value", expected_facts.get("revenue_value", ""))
    ).strip()
    expected_revenue = str(expected_facts.get("revenue_value", "")).strip()
    expected_doc_hashes = tuple(str(item).strip() for item in expected_facts.get("selected_doc_hashes", []) if str(item).strip())
    observed_metric_name = str(observed.metric_name or "").strip()
    observed_metric_value = str(observed.metric_value or observed.revenue_value or "").strip()
    route_exact = observed.route == expected_route
    tool_exact = observed.tool_name == expected_tool_name
    revenue_exact = observed.revenue_value == expected_revenue if expected_revenue else bool(observed.revenue_value)
    metric_name_exact = observed_metric_name == expected_metric_name if expected_metric_name else True
    metric_value_exact = (
        observed_metric_value == expected_metric_value
        if expected_metric_value
        else bool(observed_metric_value)
    )
    selected_doc_hashes_exact = (
        observed.selected_doc_hashes == expected_doc_hashes if expected_doc_hashes else bool(observed.selected_doc_hashes)
    )
    summary_present = bool(observed.summary_text.strip())
    exact_match = route_exact and tool_exact
    requested_metric_exact = metric_name_exact and metric_value_exact
    admissible_match = exact_match and requested_metric_exact and selected_doc_hashes_exact
    quality_floor = QualityFloorResult(
        quality_floor_pass=summary_present and admissible_match and not observed.contamination_detected,
        deterministic_checks_passed=summary_present and requested_metric_exact,
        fact_coverage_passed=admissible_match,
        llm_judge_passed=None,
        quality_floor_fail_reason=(
            ""
            if summary_present and admissible_match and not observed.contamination_detected
            else "contamination_detected"
            if observed.contamination_detected
            else "fact_coverage_failed"
            if summary_present and requested_metric_exact
            else "deterministic_checks_failed"
        ),
    )
    return FixedAnswerScore(
        route_exact=route_exact,
        tool_exact=tool_exact,
        revenue_exact=revenue_exact,
        selected_doc_hashes_exact=selected_doc_hashes_exact,
        summary_present=summary_present,
        exact_match=exact_match,
        admissible_match=admissible_match,
        correctness_label="exact_match" if admissible_match else "mismatch",
        quality_floor=quality_floor,
        metric_name_exact=metric_name_exact,
        metric_value_exact=metric_value_exact,
    )


def _g6b2_validate_live_pair(
    baseline: Mapping[str, object],
    replay: Mapping[str, object],
    *,
    model_profile: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Validate one receipt-backed live baseline/replay pair."""
    from statebus.benchmark.continuous_runner import _c2c_pair_key
    from statebus.utils import sha256_digest

    left, right = dict(baseline), dict(replay)
    failures: list[str] = []
    required_strings = (
        "row_id", "family_id", "task_contract_hash", "quality_contract_hash",
        "runtime_root", "workspace_root", "memory_root", "session_id",
        "attempt_id", "cache_epoch", "model_identity", "service_profile_id",
    )
    for side, row in (("baseline", left), ("replay", right)):
        for field in required_strings:
            if not isinstance(row.get(field), str) or not row[field].strip():
                failures.append(f"{side}_required_{field}")
        if not isinstance(row.get("input_lineage_hashes"), list) or not row["input_lineage_hashes"] or not all(
            isinstance(item, str) and item.strip() for item in row["input_lineage_hashes"]
        ):
            failures.append(f"{side}_required_input_lineage_hashes")
        for field in ("round_number", "repeat_id", "deterministic_seed"):
            if not isinstance(row.get(field), int) or isinstance(row.get(field), bool):
                failures.append(f"{side}_required_{field}")
    try:
        if failures:
            raise ValueError("required_pair_identity_missing")
        left_key, right_key = _c2c_pair_key(left), _c2c_pair_key(right)
    except (TypeError, ValueError) as exc:
        left_key = right_key = ""
        failures.append(f"pair_identity_invalid:{exc}")
    if left_key != right_key:
        failures.append("pair_key_mismatch")
    for field in ("task_contract_hash", "input_lineage_hashes", "quality_contract_hash", "deterministic_seed"):
        if left.get(field) != right.get(field):
            failures.append(f"pair_equivalence_mismatch:{field}")
    for field in ("family_id", "round_number", "repeat_id"):
        if left.get(field) != right.get(field):
            failures.append(f"pair_equivalence_mismatch:{field}")
    if left.get("lane") != "live-baseline" or left.get("memory_policy") != "off" or left.get("runtime_memory_policy") != "none":
        failures.append("baseline_policy_mismatch")
    if right.get("lane") != "live-validated-replay" or right.get("memory_policy") != "validated_replay" or right.get("runtime_memory_policy") != "validated_replay":
        failures.append("replay_policy_mismatch")
    for field in ("runtime_root", "workspace_root", "memory_root", "session_id", "attempt_id", "cache_epoch"):
        if left.get(field) == right.get(field):
            failures.append(f"pair_identity_not_separate:{field}")
    if left.get("terminal_status") != "success" or right.get("terminal_status") != "success":
        failures.append("terminal_status_not_success")
    provider = left.get("provider_invocation_evidence")
    provider = dict(provider) if isinstance(provider, Mapping) else {}
    if not (
        provider.get("status") == "observed"
        and provider.get("invocation_status") == "completed"
        and isinstance(provider.get("invocation_id"), str)
        and bool(provider["invocation_id"].strip())
        and isinstance(provider.get("evidence_hash"), str)
        and bool(provider["evidence_hash"].strip())
        and provider.get("source") == "Runtime provider call boundary"
        and provider.get("recorded_by") == "benchmark_bound_provider_adapter"
        and provider.get("served_model") == left.get("model_identity")
        and isinstance(provider.get("request_reference"), str)
        and isinstance(provider.get("response_reference"), str)
    ):
        failures.append("baseline_provider_invocation_missing")
    observation = right.get("provider_not_started_observation")
    observation = dict(observation) if isinstance(observation, Mapping) else {}
    required_observation = (
        observation.get("status") == "observed"
        and observation.get("provider_invocation_status") == "not_started"
        and right.get("runtime_authority") == "AdaptiveRuntimeEngine"
        and all(str(observation.get(name, "")) for name in (
            "observation_id", "execution_binding_hash", "capability_grant_hash",
            "memory_admission_receipt_hash", "replay_eligibility_receipt_hash",
            "quality_report_hash", "attempt_result_admission_receipt_hash",
        ))
    )
    if not required_observation:
        failures.append("replay_provider_not_started_missing")
    if right.get("consumer_provider_boundary_call_count") != 0:
        failures.append("replay_provider_boundary_called")
    if observation.get("recipe_step_status") == "not_executed":
        failures.append("recipe_step_skip_promoted")
    if observation.get("artifact_restore_status") not in {None, "", "not_applicable"}:
        failures.append("artifact_restore_promoted")
    left_quality = left.get("quality_evidence")
    right_quality = right.get("quality_evidence")
    left_quality = dict(left_quality) if isinstance(left_quality, Mapping) else {}
    right_quality = dict(right_quality) if isinstance(right_quality, Mapping) else {}
    if left_quality.get("status") != "observed" or left_quality.get("passed") is not True:
        failures.append("baseline_quality_missing_or_failed")
    if right_quality.get("status") != "observed" or right_quality.get("passed") is not True:
        failures.append("replay_quality_missing_or_failed")
    if not str(left_quality.get("report_reference", left_quality.get("report_hash", ""))) or not str(right_quality.get("report_reference", right_quality.get("report_hash", ""))):
        failures.append("quality_reference_missing")
    if observation.get("quality_report_hash") and observation.get("quality_report_hash") != right_quality.get("report_hash", right_quality.get("report_reference")):
        failures.append("replay_quality_join_missing")
    left_admission = left.get("result_admission")
    right_admission = right.get("result_admission")
    left_admission = dict(left_admission) if isinstance(left_admission, Mapping) else {}
    right_admission = dict(right_admission) if isinstance(right_admission, Mapping) else {}
    if left_admission.get("status") != "observed" or not str(left_admission.get("receipt_reference", left_admission.get("receipt_hash", ""))):
        failures.append("baseline_result_admission_missing")
    if right_admission.get("status") != "observed" or not str(right_admission.get("receipt_reference", right_admission.get("receipt_hash", ""))):
        failures.append("replay_result_admission_missing")
    replay_admission = str(right_admission.get("receipt_reference", right_admission.get("receipt_hash", "")))
    if observation.get("attempt_result_admission_receipt_hash") and observation.get("attempt_result_admission_receipt_hash") != replay_admission:
        failures.append("replay_result_admission_join_missing")
    grant = right.get("capability_grant")
    binding = right.get("execution_binding")
    eligibility = right.get("replay_eligibility_receipt")
    memory_consumption = right.get("memory_consumption_receipt")
    grant = dict(grant) if isinstance(grant, Mapping) else {}
    binding = dict(binding) if isinstance(binding, Mapping) else {}
    eligibility = dict(eligibility) if isinstance(eligibility, Mapping) else {}
    memory_consumption = dict(memory_consumption) if isinstance(memory_consumption, Mapping) else {}
    if not grant or observation.get("capability_grant_hash") != sha256_digest(grant):
        failures.append("replay_capability_grant_join_missing")
    if not binding or observation.get("execution_binding_hash") != sha256_digest(binding):
        failures.append("replay_execution_binding_join_missing")
    if not eligibility or observation.get("replay_eligibility_receipt_hash") != sha256_digest(eligibility):
        failures.append("replay_eligibility_join_missing")
    if not memory_consumption or observation.get("memory_admission_receipt_hash") != memory_consumption.get("memory_admission_receipt_hash"):
        failures.append("replay_memory_admission_join_missing")
    if memory_consumption.get("attempt_result_admission_receipt_hash") != replay_admission:
        failures.append("replay_memory_result_admission_join_missing")
    if right.get("recipe_recomputed") is not True or right_quality.get("current_input_recomputed") is not True:
        failures.append("current_input_recipe_recompute_missing")
    expected_model = (model_profile or {}).get("served_model")
    expected_profile = (model_profile or {}).get("profile_id")
    if not isinstance(expected_model, str) or not expected_model.strip() or not isinstance(expected_profile, str) or not expected_profile.strip():
        failures.append("expected_model_profile_missing")
    model_left = left.get("model_identity")
    model_right = right.get("model_identity")
    if model_left != model_right or model_left != expected_model:
        failures.append("model_service_identity_mismatch")
    if left.get("service_profile_id") != expected_profile or right.get("service_profile_id") != expected_profile:
        failures.append("service_profile_identity_mismatch")
    refs = sorted({
        str(value)
        for value in (
            provider.get("evidence_hash", ""),
            provider.get("request_reference", ""),
            provider.get("response_reference", ""),
            observation.get("observation_id", ""),
            observation.get("execution_binding_hash", ""),
            observation.get("capability_grant_hash", ""),
            observation.get("memory_admission_receipt_hash", ""),
            observation.get("replay_eligibility_receipt_hash", ""),
            observation.get("attempt_result_admission_receipt_hash", ""),
            left_quality.get("report_reference", left_quality.get("report_hash", "")),
            right_quality.get("report_reference", right_quality.get("report_hash", "")),
            left_admission.get("receipt_reference", left_admission.get("receipt_hash", "")),
            right_admission.get("receipt_reference", right_admission.get("receipt_hash", "")),
        ) if str(value)
    })
    checks = {
        "pair_key": bool(left_key and left_key == right_key),
        "baseline_provider_invocation": "baseline_provider_invocation_missing" not in failures,
        "replay_provider_not_started": "replay_provider_not_started_missing" not in failures,
        "quality": not any(item.endswith("quality_missing_or_failed") for item in failures),
        "result_admission": not any("result_admission" in item for item in failures),
        "model_service_identity": "model_service_identity_mismatch" not in failures,
        "service_profile_identity": "service_profile_identity_mismatch" not in failures,
        "receipt_joins": not any("join_missing" in item for item in failures),
        "current_input_recompute": "current_input_recipe_recompute_missing" not in failures,
        "root_session_attempt_cache_separation": not any("required_" in item or item.startswith("pair_identity_") for item in failures),
    }
    return {
        "schema_version": "statebus.g6b2.live_pair.v1",
        "status": "eligible" if not failures else "rejected",
        "pair_key": left_key,
        "baseline_row_id": left.get("row_id", ""),
        "replay_row_id": right.get("row_id", ""),
        "reason": "" if not failures else failures[0],
        "failures": failures,
        "equivalence_checks": checks,
        "quality_non_regression": {"status": "observed" if not failures else "unsupported", "passed": not failures, "reason": "" if not failures else "pair_quality_or_equivalence_failed"},
        "source_receipt_references": refs,
        "source_receipt_hashes": refs,
    }


def _g6b2_validate_live_campaign(
    baseline_rows: Iterable[Mapping[str, object]] = (),
    replay_rows: Iterable[Mapping[str, object]] = (),
    *,
    model_profile: Mapping[str, object] | None = None,
    mode: str = "minimal",
    planned_slots: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Validate a mode-bounded live campaign and retain all unmatched rows."""
    baseline = [dict(row) for row in baseline_rows]
    replay = [dict(row) for row in replay_rows]
    slots = [dict(row) for row in planned_slots]
    limits = {"minimal": 1, "campaign": 120, "soak": 480}
    if mode not in limits:
        return {"status": "rejected", "reason": "b2_mode_invalid", "pairings": [], "failure_rows": baseline + replay}
    expected_count = len(slots) if slots else (1 if mode == "minimal" else len(baseline))
    if expected_count > limits[mode] or (mode == "minimal" and expected_count != 1):
        return {"status": "rejected", "reason": "b2_mode_pair_limit_exceeded", "pairings": [], "failure_rows": baseline + replay}
    by_left: dict[str, list[dict[str, object]]] = {}
    by_right: dict[str, list[dict[str, object]]] = {}
    failures: list[dict[str, object]] = []
    from statebus.benchmark.continuous_runner import _c2c_pair_key
    for side, rows, target in (("baseline", baseline, by_left), ("replay", replay, by_right)):
        for row in rows:
            try:
                key = _c2c_pair_key(row)
            except (TypeError, ValueError) as exc:
                failures.append({**row, "status": "unmatched", "failure_stage": "pair_identity", "reason": str(exc), "source_receipt_references": []})
                continue
            row["pair_key"] = key
            target.setdefault(key, []).append(row)
    pairings: list[dict[str, object]] = []
    for key in sorted(set(by_left) | set(by_right)):
        left, right = by_left.get(key, []), by_right.get(key, [])
        if len(left) != 1 or len(right) != 1:
            failures.extend([{**row, "status": "unmatched", "failure_stage": "pairing", "reason": "duplicate_or_missing_matched_side", "pair_key": key, "source_receipt_references": []} for row in [*left, *right]])
            continue
        pairings.append(_g6b2_validate_live_pair(left[0], right[0], model_profile=model_profile))
    eligible = sum(pair.get("status") == "eligible" for pair in pairings)
    rejected = sum(pair.get("status") == "rejected" for pair in pairings)
    all_rows = [*baseline, *replay]
    terminal = [row.get("terminal_status") for row in all_rows]
    denominator = {
        "schema_version": "statebus.g6b2.live_failure_denominator.v1",
        "status": "observed",
        "attempted": len(all_rows),
        "success": terminal.count("success"),
        "baseline_row_count": len(baseline),
        "replay_row_count": len(replay),
        "matched_pair_count": len(pairings),
        "eligible_matched_pair_count": eligible,
        "rejected_matched_pair_count": rejected,
        "unmatched_row_count": len(failures),
        **{name: terminal.count(name) for name in ("runtime_fail", "timeout", "environment_fail", "policy_reject", "unsupported", "quality_fail")},
        "row_ids": [str(row.get("row_id", "")) for row in all_rows],
        "denominator_linkage": [str(row.get("row_id", "")) for row in [*all_rows, *failures] if str(row.get("row_id", ""))],
        "arithmetic_closed": len({row.get("row_id") for row in all_rows}) == len(all_rows),
    }
    denominator["row_arithmetic_closed"] = denominator["arithmetic_closed"] and len(all_rows) == 2 * len(pairings) + len(failures)
    planned_ids = {str(slot.get("slot_id", "")) for slot in slots}
    observed_ids = {str(row.get("slot_id", "")) for row in [*baseline, *replay]}
    slot_plan_ok = not slots or observed_ids == planned_ids
    accepted = eligible == expected_count and not failures and not rejected and slot_plan_ok
    return {"status": "accepted" if accepted else "rejected", "reason": "" if accepted else "live_campaign_validation_failed", "mode": mode, "planned_slot_count": expected_count, "slot_plan_match": slot_plan_ok, "pairings": pairings, "failure_rows": failures, "denominator": denominator, "baseline_rows": baseline, "replay_rows": replay}
