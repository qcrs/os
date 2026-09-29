from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any, Protocol

from statebus.utils import sha256_digest, stable_json_dumps
from statebus.runtime.prefix_identity import shared_prefix_envelope


SAMPLE_ROOT = Path(__file__).resolve().parent.parent / "samples" / "model_assist_utility_v1"
CASE_IDS = (
    "MU-ORION-4K-COST",
    "MU-NOVA-4K-DELIVERY",
    "MU-ORION-6K-COST",
    "MU-NOVA-6K-DELIVERY",
)
LOGIT_CASE_IDS = (
    "MU-LOGIT-EASY-NOVA-OTD",
    "MU-LOGIT-AMBIGUITY-ORION-COST",
    "MU-LOGIT-AMBIGUITY-NOVA-DELIVERY",
    "MU-LOGIT-UNRESOLVED-ORION-EXCEPTIONS",
)
CALIBRATION_CASE_ID = "MU-NOVA-6K-CALIBRATION-DELIVERY"
LOGIT_CALIBRATION_CASE_ID = "MU-LOGIT-CALIBRATION-NOVA-OTD"
CASE_SCHEMA_VERSION = "statebus.model_assist_utility.taskpack.v1"
SUITE_REVISION = "longtext-demo-v3"
BLOCK_SIZE = 16
MAX_MODEL_LEN = 8192
SEED = 20260928
NAMESPACE_HEX_LENGTH = 32
CACHE_NAMESPACE_PLACEHOLDER = "mu-0123456789abcdef0123456789abcdef"
LOGIT_COMPACT_EVIDENCE_TOKEN_RANGE = (384, 768)
LOGIT_FULL_EVIDENCE_TOKEN_RANGE = (2048, 4096)


class TokenCodec(Protocol):
    def encode(self, text: str) -> list[int] | tuple[int, ...]: ...


@dataclass(frozen=True)
class CaseDefinition:
    case_id: str
    company: str
    business: str
    length_class: str
    target_min_tokens: int
    target_max_tokens: int
    question: str
    executor_contract: str
    summarizer_contract: str


@dataclass(frozen=True)
class CompiledCase:
    definition: CaseDefinition
    dossier: str
    source_rows: tuple[dict[str, Any], ...]
    rules: tuple[dict[str, Any], ...]
    gold: dict[str, Any]
    prefix_token_ids: tuple[int, ...]
    prefix_token_digest: str
    source_digest: str
    target_prefix_tokens: int

    @property
    def case_id(self) -> str:
        return self.definition.case_id

    @property
    def length_class(self) -> str:
        return self.definition.length_class

    @property
    def role_visibility(self) -> dict[str, str]:
        return {
            "executor": "shared dossier plus executor suffix; Gold and final answer hidden",
            "summarizer": "shared dossier plus verified artifact suffix; Gold hidden",
        }

    def shared_prefix_text(self, namespace: str) -> str:
        _validate_cache_namespace(namespace)
        return (
            f"Utility cache isolation namespace (not business evidence): {namespace}\n\n"
            "StateBus long-text utility dossier. Use only this authorized dossier. "
            "The ledger and effective rules below are controlled sample facts.\n\n"
            + self.dossier
        )

    def layout_text(self, layout: str, role: str, *, namespace: str, artifact: str = "") -> str:
        if layout not in {"independent", "shared"}:
            raise ValueError(f"unsupported_layout:{layout}")
        if role not in {"executor", "summarizer"}:
            raise ValueError(f"unsupported_role:{role}")
        _validate_cache_namespace(namespace)
        role_suffix = (
            "\n\nROLE SUFFIX: Executor\n"
            + self.definition.executor_contract
            if role == "executor"
            else "\n\nROLE SUFFIX: Summarizer\n"
            + self.definition.summarizer_contract
            + ("\nVerified Executor Artifact:\n" + artifact if artifact else "")
        )
        if layout == "shared":
            return shared_prefix_envelope(self.shared_prefix_text(namespace)) + role_suffix
        return (
            f"Utility cache isolation namespace (not business evidence): {namespace}\n\n"
            "StateBus long-text utility task.\n"
            + role_suffix
            + "\n\nAUTHORIZED DOSSIER:\n"
            + self.dossier
        )

    def canonical_payload(self, *, include_gold: bool = False) -> dict[str, Any]:
        payload = {
            "case_id": self.case_id,
            "company": self.definition.company,
            "business": self.definition.business,
            "length_class": self.length_class,
            "target_prefix_tokens": self.target_prefix_tokens,
            "namespace_placement": "before_authorized_dossier",
            "namespace_token_count_preserved": True,
            "kv_parent_cap_tokens": self.definition.target_min_tokens,
            "prefix_token_digest": self.prefix_token_digest,
            "source_digest": self.source_digest,
            "source_row_count": len(self.source_rows),
            "rule_count": len(self.rules),
            "role_visibility": self.role_visibility,
        }
        if include_gold:
            payload["gold"] = dict(self.gold)
        return payload


@dataclass(frozen=True)
class LogitCase:
    case_id: str
    group: str
    question: str
    compact_view: str
    full_view: str
    candidates: tuple[dict[str, str], ...]
    gold_candidate: str
    gold_outcome: str

    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(item["candidate_id"] for item in self.candidates)

    def evidence_text(self, field_name: str) -> str:
        if field_name not in {"compact_evidence", "full_evidence"}:
            raise ValueError(f"unsupported_logit_evidence_field:{field_name}")
        return "\n\n".join(
            f"{item['candidate_id']} ({item['label']})\n{item[field_name]}"
            for item in self.candidates
        )

    def canonical_payload(self, *, include_gold: bool = False) -> dict[str, Any]:
        payload = {
            "case_id": self.case_id,
            "group": self.group,
            "question": self.question,
            "compact_view": self.compact_view,
            "full_view": self.full_view,
            "candidates": [dict(item) for item in self.candidates],
        }
        if include_gold:
            payload.update(
                {"gold_candidate": self.gold_candidate, "gold_outcome": self.gold_outcome}
            )
        return payload


@dataclass(frozen=True)
class Taskpack:
    manifest: dict[str, Any]
    cases: tuple[CompiledCase, ...]
    logit_cases: tuple[LogitCase, ...]
    plan: tuple[dict[str, Any], ...]
    calibration_case: CompiledCase
    logit_calibration_case: LogitCase

    def canonical_payload(self, *, include_gold: bool = False) -> dict[str, Any]:
        return {
            "manifest": dict(self.manifest),
            "cases": [case.canonical_payload(include_gold=include_gold) for case in self.cases],
            "logit_cases": [
                case.canonical_payload(include_gold=include_gold) for case in self.logit_cases
            ],
            "calibration_case": self.calibration_case.canonical_payload(include_gold=include_gold),
            "logit_calibration_case": self.logit_calibration_case.canonical_payload(include_gold=include_gold),
            "plan": [dict(item) for item in self.plan],
        }


CASE_DEFINITIONS = (
    CaseDefinition(
        "MU-ORION-4K-COST",
        "Orion Factory Systems",
        "approved sample expedited cost and exception analysis",
        "4k",
        4096,
        4352,
        "For the approved sample cohort, compare 2026Q1 and 2026Q3 expedited fees and exception counts, report the delta and covered record counts, and cite the active scope rule.",
        "Return a JSON TransformProgram with filter, aggregate, and derive operations. Select the approved sample cohort and effective rule from the dossier; do not copy a precomputed answer.",
        "Return a compact JSON report with q1_fee_usd, q3_fee_usd, fee_delta_usd, q1_exception_count, q3_exception_count, q1_covered_record_count, q3_covered_record_count, covered_record_count, and 2-3 source citations.",
    ),
    CaseDefinition(
        "MU-NOVA-4K-DELIVERY",
        "Nova Retail Logistics",
        "approved sample weighted delivery rate analysis",
        "4k",
        4096,
        4352,
        "For the approved sample cohort, calculate weighted on-time delivery for 2026Q1 and 2026Q3, the percentage-point change, numerator and denominator, and the active scope rule.",
        "Return a JSON TransformProgram that filters the effective approved cohort and aggregates committed and on_time orders. Never average row percentages or use the company-wide rate.",
        "Return a compact JSON report with q1_on_time, q1_committed, q1_rate_pct, q3_on_time, q3_committed, q3_rate_pct, delta_pp, q1_covered_record_count, q3_covered_record_count, covered_record_count, and 2-3 source citations.",
    ),
    CaseDefinition(
        "MU-ORION-6K-COST",
        "Orion Factory Systems",
        "approved sample expedited cost and exception analysis",
        "6k",
        6144,
        6400,
        "For the approved sample cohort, compare 2026Q1 and 2026Q3 expedited fees and exception counts, report the delta and covered record counts, and cite the active scope rule.",
        "Return a JSON TransformProgram with filter, aggregate, and derive operations. Select the approved sample cohort and effective rule from the dossier; do not copy a precomputed answer.",
        "Return a compact JSON report with q1_fee_usd, q3_fee_usd, fee_delta_usd, q1_exception_count, q3_exception_count, q1_covered_record_count, q3_covered_record_count, covered_record_count, and 2-3 source citations.",
    ),
    CaseDefinition(
        "MU-NOVA-6K-DELIVERY",
        "Nova Retail Logistics",
        "approved sample weighted delivery rate analysis",
        "6k",
        6144,
        6400,
        "For the approved sample cohort, calculate weighted on-time delivery for 2026Q1 and 2026Q3, the percentage-point change, numerator and denominator, and the active scope rule.",
        "Return a JSON TransformProgram that filters the effective approved cohort and aggregates committed and on_time orders. Never average row percentages or use the company-wide rate.",
        "Return a compact JSON report with q1_on_time, q1_committed, q1_rate_pct, q3_on_time, q3_committed, q3_rate_pct, delta_pp, q1_covered_record_count, q3_covered_record_count, covered_record_count, and 2-3 source citations.",
    ),
)

CALIBRATION_DEFINITION = CaseDefinition(
    CALIBRATION_CASE_ID,
    "Nova Retail Logistics",
    "approved sample weighted delivery rate calibration",
    "6k-calibration",
    6144,
    6400,
    "For the approved sample cohort, calculate weighted on-time delivery for 2026Q1 and 2026Q3, the percentage-point change, numerator and denominator, and the active scope rule.",
    "Return a JSON TransformProgram that filters the effective approved cohort and aggregates committed and on_time orders. Never average row percentages or use the company-wide rate.",
    "Return a compact JSON report with q1_on_time, q1_committed, q1_rate_pct, q3_on_time, q3_committed, q3_rate_pct, delta_pp, q1_covered_record_count, q3_covered_record_count, covered_record_count, and 2-3 source citations.",
)


def _source_case_prefix(case_id: str) -> str:
    return case_id.lower()


def _build_rules(company: str, case_id: str) -> tuple[dict[str, Any], ...]:
    source_path = f"rules/{_source_case_prefix(case_id)}_active_scope_rules.json"
    return (
        {
            "rule_id": f"R-{company[:3].upper()}-SAMPLE-2026",
            "effective_from": "2026-01-01",
            "effective_to": "2026-12-31",
            "eligible_scope": "approved_sample_cohort",
            "status_policy": "include approved; exclude cancelled and pending",
            "source_locator": f"{source_path}#R-2026-sample",
        },
        {
            "rule_id": f"R-{company[:3].upper()}-HISTORICAL-2025",
            "effective_from": "2025-01-01",
            "effective_to": "2025-12-31",
            "eligible_scope": "legacy_scope",
            "status_policy": "legacy records are not eligible",
            "source_locator": f"{source_path}#R-2025-legacy",
        },
    )


def _build_rows(company: str, row_count: int, case_id: str) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    source_path = f"ledger/{_source_case_prefix(case_id)}_sample_ledger.json"
    case_tag = {
        "MU-ORION-4K-COST": "O4C",
        "MU-NOVA-4K-DELIVERY": "N4D",
        "MU-ORION-6K-COST": "O6C",
        "MU-NOVA-6K-DELIVERY": "N6D",
        CALIBRATION_CASE_ID: "NCAL",
    }[case_id]
    offset = 37 if "CALIBRATION" in case_id else 0
    for index in range(row_count):
        value_index = index + offset
        quarter = "2026Q1" if value_index % 2 == 0 else "2026Q3"
        status = "CANCELLED" if value_index % 19 == 0 else "PENDING" if value_index % 23 == 0 else "APPROVED"
        region = ("Central", "Northeast", "Southeast", "Pacific", "Mountain")[value_index % 5]
        record: dict[str, Any] = {
            "record_id": f"{company[:3].upper()}-{case_tag}-{index + 1:04d}",
            "company": company,
            "quarter": quarter,
            "region": region,
            "scope": "approved_sample_cohort" if value_index % 11 else "legacy_scope",
            "status": status,
            "effective_rule_id": "R-ORI-SAMPLE-2026" if company.startswith("Orion") else "R-NOV-SAMPLE-2026",
            "source_locator": f"{source_path}#row-{index + 1:04d}",
        }
        if company.startswith("Orion"):
            record.update(
                {
                    "expedited_fee_usd": 1250 + value_index * 17 + (31 if quarter == "2026Q3" else 0),
                    "exception_count": (value_index % 4) + (1 if quarter == "2026Q3" else 0),
                }
            )
        else:
            committed = 80 + (value_index % 17) * 3
            on_time = committed - ((value_index % 7) + (2 if quarter == "2026Q3" else 0))
            record.update({"committed_orders": committed, "on_time_orders": on_time})
        rows.append(record)
    return tuple(rows)


def _gold_for(
    company: str,
    rows: tuple[dict[str, Any], ...],
    rules: tuple[dict[str, Any], ...] | None = None,
) -> dict[str, Any]:
    rules = rules or _build_rules(company, "gold-reference")
    active_rule = next(
        (rule for rule in rules if str(rule.get("effective_from", "")) == "2026-01-01"),
        {},
    )
    effective_rule_id = str(active_rule.get("rule_id", ""))
    eligible_scope = str(active_rule.get("eligible_scope", ""))
    included = [
        row
        for row in rows
        if row["status"] == "APPROVED"
        and row["scope"] == eligible_scope
        and row["effective_rule_id"] == effective_rule_id
    ]
    by_quarter = {quarter: [row for row in included if row["quarter"] == quarter] for quarter in ("2026Q1", "2026Q3")}
    if company.startswith("Orion"):
        q1_fee = sum(int(row["expedited_fee_usd"]) for row in by_quarter["2026Q1"])
        q3_fee = sum(int(row["expedited_fee_usd"]) for row in by_quarter["2026Q3"])
        return {
            "q1_fee_usd": q1_fee,
            "q3_fee_usd": q3_fee,
            "fee_delta_usd": q3_fee - q1_fee,
            "q1_exception_count": sum(int(row["exception_count"]) for row in by_quarter["2026Q1"]),
            "q3_exception_count": sum(int(row["exception_count"]) for row in by_quarter["2026Q3"]),
            "q1_covered_record_count": len(by_quarter["2026Q1"]),
            "q3_covered_record_count": len(by_quarter["2026Q3"]),
            "covered_record_count": len(included),
            "rule_id": effective_rule_id,
        }
    q1_committed = sum(int(row["committed_orders"]) for row in by_quarter["2026Q1"])
    q3_committed = sum(int(row["committed_orders"]) for row in by_quarter["2026Q3"])
    q1_on_time = sum(int(row["on_time_orders"]) for row in by_quarter["2026Q1"])
    q3_on_time = sum(int(row["on_time_orders"]) for row in by_quarter["2026Q3"])
    q1_rate = round(100.0 * q1_on_time / q1_committed, 4)
    q3_rate = round(100.0 * q3_on_time / q3_committed, 4)
    return {
        "q1_on_time": q1_on_time,
        "q1_committed": q1_committed,
        "q1_rate_pct": q1_rate,
        "q3_on_time": q3_on_time,
        "q3_committed": q3_committed,
        "q3_rate_pct": q3_rate,
        "delta_pp": round(q3_rate - q1_rate, 4),
        "q1_covered_record_count": len(by_quarter["2026Q1"]),
        "q3_covered_record_count": len(by_quarter["2026Q3"]),
        "covered_record_count": len(included),
        "rule_id": effective_rule_id,
    }


def _render_dossier(definition: CaseDefinition, rows: tuple[dict[str, Any], ...], rules: tuple[dict[str, Any], ...]) -> str:
    lines = [
        f"# Controlled Long-Text Dossier: {definition.case_id}",
        f"company={definition.company}; business={definition.business}; seed={SEED}",
        "This is a controlled sample ledger. The original company review is a separate scope.",
        "Relevant facts occur in early, middle, and late sections; citations identify source rows.",
        "\n## Effective Scope Rules [rules/active_scope_rules.json]",
    ]
    for rule in rules:
        lines.append(stable_json_dumps(rule))
    lines.append("\n## Sample Ledger [ledger/controlled_sample_ledger.json]")
    for index, row in enumerate(rows):
        if index == len(rows) // 2:
            lines.append("\n## Middle Ledger Checkpoint: continue applying the effective scope rule")
        lines.append(stable_json_dumps(row))
    lines.extend(
        [
            "\n## Late Evidence and Citation Rule [rules/late_scope_note.md]",
            "The active 2026 rule applies only to approved_sample_cohort rows. "
            "Cancelled, pending, legacy_scope, and out-of-period rows must remain excluded. "
            "A final report must cite the active rule and concrete ledger rows.",
        ]
    )
    return "\n".join(lines)


def _validate_cache_namespace(namespace: str) -> None:
    if not re.fullmatch(r"mu-[0-9a-f]{32}", namespace):
        raise ValueError("cache_namespace_must_be_128_bit_hex")


def _shared_prefix_text(dossier: str, namespace: str) -> str:
    _validate_cache_namespace(namespace)
    return (
        f"Utility cache isolation namespace (not business evidence): {namespace}\n\n"
        "StateBus long-text utility dossier. Use only this authorized dossier. "
        "The ledger and effective rules below are controlled sample facts.\n\n"
        + dossier
    )


def _definitions_from_disk(root: Path) -> tuple[CaseDefinition, ...]:
    path = root / "cases.json"
    if not path.exists():
        return CASE_DEFINITIONS
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = raw.get("cases", [])
    return tuple(CaseDefinition(**item) for item in cases)


def _logit_cases_from_disk(root: Path) -> tuple[LogitCase, ...]:
    path = root / "logit_cases.json"
    if not path.exists():
        return _default_logit_cases()
    raw = json.loads(path.read_text(encoding="utf-8"))
    gold_path = root / "gold.json"
    gold = json.loads(gold_path.read_text(encoding="utf-8")) if gold_path.exists() else {}
    gold_cases = gold.get("logit", {})
    return tuple(_decode_logit_case(item, gold_cases, root=root) for item in raw.get("cases", []))


def _decode_logit_case(
    item: dict[str, Any],
    gold_cases: dict[str, Any] | None = None,
    *,
    root: Path = SAMPLE_ROOT,
) -> LogitCase:
    gold = (gold_cases or {}).get(str(item["case_id"]), {})
    candidates: list[dict[str, str]] = []
    for candidate_payload in item["candidates"]:
        candidate = {str(key): str(value) for key, value in candidate_payload.items()}
        evidence_path = candidate.get("full_evidence_path", "")
        if evidence_path:
            resolved = (root / evidence_path).resolve()
            if not resolved.is_file():
                raise FileNotFoundError(f"logit_evidence_source_missing:{resolved}")
            candidate["full_evidence"] = resolved.read_text(encoding="utf-8")
        required = ("candidate_id", "label", "source_locator", "grant_scope", "valid_period", "compact_evidence", "full_evidence")
        missing = [key for key in required if not candidate.get(key, "").strip()]
        if missing:
            raise ValueError(f"logit_candidate_fields_missing:{item['case_id']}:{','.join(missing)}")
        candidates.append(candidate)
    return LogitCase(
        case_id=str(item["case_id"]),
        group=str(item["group"]),
        question=str(item["question"]),
        compact_view=str(item["compact_view"]),
        full_view=str(item["full_view"]),
        candidates=tuple(candidates),
        gold_candidate=str(gold.get("candidate", "")),
        gold_outcome=str(gold.get("outcome", "select")),
    )


def _logit_calibration_from_disk(root: Path) -> LogitCase:
    path = root / "logit_cases.json"
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        item = raw.get("calibration")
        if isinstance(item, dict):
            return _decode_logit_case(item, root=root)
    return LogitCase(
        LOGIT_CALIBRATION_CASE_ID,
        "calibration",
        "Select the evidence bundle with an approved cohort denominator.",
        "A contains authorized Q1/Q3 cohort rows; B contains a current company-wide percentage.",
        "A contains the cohort ledger and its denominator rule; B has no cohort-level denominator.",
        (
            {"candidate_id": "sample_ledger_calibration", "label": "approved cohort ledger", "source_locator": f"logit/{LOGIT_CALIBRATION_CASE_ID}.json#sample-ledger"},
            {"candidate_id": "operating_review_calibration", "label": "company-wide review", "source_locator": f"logit/{LOGIT_CALIBRATION_CASE_ID}.json#operating-review"},
        ),
    )


def _default_logit_cases() -> tuple[LogitCase, ...]:
    return (
        LogitCase(
            LOGIT_CASE_IDS[0], "easy", "Choose the evidence bundle that computes Nova cohort OTD.",
            "A is the approved sample ledger with committed/on_time rows; B is an overall company review percentage.",
            "The sample ledger contains Q1/Q3 cohort rows and the active denominator rule. The overall review has no cohort denominator.",
            ({"candidate_id": "sample_ledger", "label": "approved cohort ledger", "source_locator": "logit_cases.json#easy-sample-ledger"}, {"candidate_id": "operating_review", "label": "company overall review", "source_locator": "logit_cases.json#easy-operating-review"}),
            "sample_ledger", "select",
        ),
        LogitCase(
            LOGIT_CASE_IDS[1], "semantic_ambiguity", "Choose the evidence bundle for Orion approved sample expedited fees.",
            "A is current sample ledger; B is historical scope material. Both are authorized and use similar titles.",
            "The current bundle carries the 2026 effective rule, approval exceptions, and row locators; historical material is out of scope.",
            ({"candidate_id": "orion_current_ledger", "label": "current sample ledger", "source_locator": "logit_cases.json#orion-current-ledger"}, {"candidate_id": "orion_historical_scope", "label": "historical scope", "source_locator": "logit_cases.json#orion-historical-scope"}),
            "orion_current_ledger", "select",
        ),
        LogitCase(
            LOGIT_CASE_IDS[2], "semantic_ambiguity", "Choose the evidence bundle for Nova weighted delivery.",
            "A is a report overall rate; B is a cohort ledger with committed and on_time counts.",
            "Only the cohort ledger contains the valid denominator and effective scope needed for weighted delivery.",
            ({"candidate_id": "nova_overall_rate", "label": "overall rate", "source_locator": "logit_cases.json#nova-overall-rate"}, {"candidate_id": "nova_delivery_ledger", "label": "cohort delivery ledger", "source_locator": "logit_cases.json#nova-delivery-ledger"}),
            "nova_delivery_ledger", "select",
        ),
        LogitCase(
            LOGIT_CASE_IDS[3], "unresolved", "Decide whether the conflicting Orion Q3 exception is eligible.",
            "A and B are authorized records for the same exception, but the final approval signature is missing.",
            "The expanded view confirms the records conflict and no final sign-off exists; the correct result is insufficient evidence.",
            ({"candidate_id": "include_exception", "label": "include", "source_locator": "logit_cases.json#unresolved-include"}, {"candidate_id": "exclude_exception", "label": "exclude", "source_locator": "logit_cases.json#unresolved-exclude"}),
            "", "abstain",
        ),
    )


def _default_logit_calibration_case() -> LogitCase:
    return _logit_calibration_from_disk(Path("/nonexistent"))


def logit_policy_order(case_index: int) -> tuple[str, str, str]:
    policies = ("compact_once", "full_context_once", "logit_selective")
    offset = case_index % len(policies)
    return policies[offset:] + policies[:offset]


def _build_plan() -> tuple[dict[str, Any], ...]:
    positions: list[dict[str, Any]] = []
    ordinal = 0
    # The first five standard slots are the built-in gate: Orion 4k APC in
    # both layouts followed by all three easy Logit policies. The remaining
    # standard slots then stay grouped by mechanism and preserve the frozen
    # case-order alternation.
    for layout in ("independent", "shared"):
        positions.append({"ordinal": ordinal, "module": "apc", "case_id": CASE_IDS[0], "condition": f"apc_on_{layout}", "gate": True})
        ordinal += 1
    for policy in logit_policy_order(0):
        positions.append({"ordinal": ordinal, "module": "logit", "case_id": LOGIT_CASE_IDS[0], "condition": policy, "gate": True})
        ordinal += 1
    for case_index, case in enumerate(CASE_IDS[1:], start=1):
        layouts = ("independent", "shared") if case_index % 2 == 0 else ("shared", "independent")
        for layout in layouts:
            positions.append({"ordinal": ordinal, "module": "apc", "case_id": case, "condition": f"apc_on_{layout}", "gate": False})
            ordinal += 1
    for case_index, case in enumerate(LOGIT_CASE_IDS[1:], start=1):
        for policy in logit_policy_order(case_index):
            positions.append({"ordinal": ordinal, "module": "logit", "case_id": case, "condition": policy, "gate": False})
            ordinal += 1
    for case_index, case in enumerate(CASE_IDS):
        conditions = ("full_replay", "continuation") if case_index % 2 == 0 else ("continuation", "full_replay")
        for condition in conditions:
            positions.append({"ordinal": ordinal, "module": "kv", "case_id": case, "condition": condition, "gate": case == CASE_IDS[0]})
            ordinal += 1
    return tuple(positions)


PLAN_POSITIONS = _build_plan()


def _compile_case(definition: CaseDefinition, codec: TokenCodec) -> CompiledCase:
    # Only complete, unique ledger rows may establish the long-text interval.
    if definition.target_min_tokens % BLOCK_SIZE:
        raise ValueError(f"kv_parent_cap_not_block_aligned:{definition.case_id}")
    selected_rows: tuple[dict[str, Any], ...] = ()
    selected_dossier = ""
    selected_ids: tuple[int, ...] = ()
    rules = _build_rules(definition.company, definition.case_id)
    for count in range(20, 260):
        rows = _build_rows(definition.company, count, definition.case_id)
        dossier = _render_dossier(definition, rows, rules)
        prefix_text = _shared_prefix_text(dossier, CACHE_NAMESPACE_PLACEHOLDER)
        token_ids = _encode_shared_prefix(codec, shared_prefix_envelope(prefix_text))
        if definition.target_min_tokens <= len(token_ids) <= definition.target_max_tokens:
            selected_rows, selected_dossier, selected_ids = rows, dossier, token_ids
            break
    if not selected_ids:
        raise ValueError(f"unable_to_compile_prefix_from_complete_rows:{definition.case_id}")
    gold = _gold_for(definition.company, selected_rows, rules)
    return CompiledCase(
        definition=definition,
        dossier=selected_dossier,
        source_rows=selected_rows,
        rules=rules,
        gold=gold,
        prefix_token_ids=selected_ids,
        prefix_token_digest=sha256_digest(list(selected_ids)),
        source_digest=sha256_digest({"rows": selected_rows, "rules": rules}),
        target_prefix_tokens=len(selected_ids),
    )


def build_cache_namespace(
    case: CompiledCase,
    codec: TokenCodec,
    *,
    run_id: str,
    scope: str,
    forbidden: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Choose an opaque per-scope ID without changing the compiled prefix length."""
    for attempt in range(4096):
        digest = sha256_digest({"run_id": run_id, "case_id": case.case_id, "scope": scope, "attempt": attempt})
        namespace = f"mu-{digest[:NAMESPACE_HEX_LENGTH]}"
        if namespace in forbidden or namespace == CACHE_NAMESPACE_PLACEHOLDER:
            continue
        token_ids = _encode_shared_prefix(
            codec,
            shared_prefix_envelope(case.shared_prefix_text(namespace)),
        )
        if len(token_ids) == case.target_prefix_tokens:
            return {
                "namespace": namespace,
                "prefix_token_count": len(token_ids),
                "prefix_token_digest": sha256_digest(list(token_ids)),
            }
    raise ValueError(f"unable_to_preserve_namespaced_prefix_length:{case.case_id}:{scope}")


def compile_taskpack(codec: TokenCodec, *, root: Path = SAMPLE_ROOT) -> Taskpack:
    definitions = _definitions_from_disk(root)
    if tuple(item.case_id for item in definitions) != CASE_IDS:
        raise ValueError("case_ids_must_match_frozen_contract")
    cases = tuple(_compile_case(definition, codec) for definition in definitions)
    logit_cases = _logit_cases_from_disk(root)
    if tuple(item.case_id for item in logit_cases) != LOGIT_CASE_IDS:
        raise ValueError("logit_case_ids_must_match_frozen_contract")
    for case in logit_cases:
        for field_name, bounds in (
            ("compact_evidence", LOGIT_COMPACT_EVIDENCE_TOKEN_RANGE),
            ("full_evidence", LOGIT_FULL_EVIDENCE_TOKEN_RANGE),
        ):
            token_count = len(codec.encode(case.evidence_text(field_name)))
            if not bounds[0] <= token_count <= bounds[1]:
                raise ValueError(
                    f"logit_evidence_token_budget_violation:{case.case_id}:{field_name}:{token_count}"
                )
    calibration_case = _compile_case(CALIBRATION_DEFINITION, codec)
    logit_calibration_case = _logit_calibration_from_disk(root)
    if logit_calibration_case.case_id != LOGIT_CALIBRATION_CASE_ID:
        raise ValueError("logit_calibration_case_id_must_match_frozen_contract")
    manifest = {
        "schema_version": CASE_SCHEMA_VERSION,
        "suite_revision": SUITE_REVISION,
        "seed": SEED,
        "block_size": BLOCK_SIZE,
        "max_model_len": MAX_MODEL_LEN,
        "logit_evidence_token_ranges": {
            "compact": list(LOGIT_COMPACT_EVIDENCE_TOKEN_RANGE),
            "full": list(LOGIT_FULL_EVIDENCE_TOKEN_RANGE),
        },
        "executor_max_tokens": 512,
        "summarizer_max_tokens": 384,
        "temperature": 0.0,
        "generation_seed": 7,
        "enable_thinking": False,
        "tokenization": "local Qwen3 chat template with enable_thinking=false",
        "cache_namespace": {
            "format": "mu-<32 lowercase hex characters>",
            "placement": "before_authorized_dossier",
            "apc": "unique per run/case/layout with equal shared-prefix token counts",
            "kv": "shared by replay and continuation within each run/case pair",
        },
        "case_ids": list(CASE_IDS),
        "logit_case_ids": list(LOGIT_CASE_IDS),
        "calibration_case_id": calibration_case.case_id,
        "logit_calibration_case_id": logit_calibration_case.case_id,
        "kv_parent_caps": {case.case_id: case.definition.target_min_tokens for case in (*cases, calibration_case)},
        "plan_count": len(PLAN_POSITIONS),
        "gold_path": "gold.json",
    }
    return Taskpack(manifest, cases, logit_cases, PLAN_POSITIONS, calibration_case, logit_calibration_case)


class LocalTokenizerCodec:
    def __init__(self, tokenizer: Any) -> None:
        self.tokenizer = tokenizer

    def encode(self, text: str) -> tuple[int, ...]:
        return tuple(int(item) for item in self.tokenizer.encode(text, add_special_tokens=False))

    def encode_messages(
        self,
        messages: list[dict[str, str]],
        *,
        add_generation_prompt: bool = False,
        chat_template_kwargs: dict[str, Any] | None = None,
    ) -> tuple[int, ...]:
        template_kwargs = {"enable_thinking": False, **dict(chat_template_kwargs or {})}
        return tuple(
            int(item)
            for item in self.tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=add_generation_prompt,
                chat_template_kwargs=template_kwargs,
            )
        )


def _encode_shared_prefix(codec: TokenCodec, text: str) -> tuple[int, ...]:
    encode_messages = getattr(codec, "encode_messages", None)
    if callable(encode_messages):
        return tuple(
            int(item)
            for item in encode_messages(
                [{"role": "system", "content": text}],
                add_generation_prompt=False,
                chat_template_kwargs={"enable_thinking": False},
            )
        )
    return tuple(int(item) for item in codec.encode(text))


def load_local_codec(tokenizer_path: str = "/data/models/Qwen3-32B") -> LocalTokenizerCodec:
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_path,
        local_files_only=True,
        trust_remote_code=True,
        use_fast=True,
    )
    return LocalTokenizerCodec(tokenizer)


def _necessity_checks(taskpack: Taskpack) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for case in (*taskpack.cases, taskpack.calibration_case):
        rows = list(case.source_rows)
        active_rule = next(
            rule for rule in case.rules
            if str(rule.get("effective_from", "")) == "2026-01-01"
        )
        relevant_indices = [
            index
            for index, row in enumerate(rows)
            if row["status"] == "APPROVED"
            and row["scope"] == active_rule["eligible_scope"]
            and row["effective_rule_id"] == active_rule["rule_id"]
        ]
        if len(relevant_indices) < 3:
            raise ValueError(f"necessity_requires_three_relevant_rows:{case.case_id}")
        for label, index in (
            ("early", relevant_indices[0]),
            ("middle", relevant_indices[len(relevant_indices) // 2]),
            ("late", relevant_indices[-1]),
        ):
            changed = rows[:index] + rows[index + 1 :]
            changed_gold = _gold_for(case.definition.company, tuple(changed), case.rules)
            checks.append({"case_id": case.case_id, "check": f"remove_{label}_relevant_row", "passed": changed_gold != case.gold})
        late_row = rows[relevant_indices[-1]]
        rows_without_late = rows[: relevant_indices[-1]] + rows[relevant_indices[-1] + 1 :]
        gold_without_late = _gold_for(case.definition.company, tuple(rows_without_late), case.rules)
        checks.append({
            "case_id": case.case_id,
            "check": "remove_late_row_changes_covered_record_count",
            "passed": gold_without_late.get("covered_record_count") != case.gold.get("covered_record_count"),
        })
        changed_rules = list(case.rules)
        changed_rules[0] = {**changed_rules[0], "eligible_scope": "wrong_scope"}
        valid_record_ids = {
            row["record_id"] for row in rows
            if row["status"] == "APPROVED"
            and row["scope"] == active_rule["eligible_scope"]
            and row["effective_rule_id"] == active_rule["rule_id"]
        }
        changed_record_ids = {
            row["record_id"] for row in rows
            if row["status"] == "APPROVED"
            and row["scope"] == changed_rules[0]["eligible_scope"]
            and row["effective_rule_id"] == changed_rules[0]["rule_id"]
        }
        checks.append({
            "case_id": case.case_id,
            "check": "active_rule_changes_program_semantics",
            "baseline_eligible_record_count": len(valid_record_ids),
            "changed_rule_eligible_record_count": len(changed_record_ids),
            "passed": valid_record_ids != changed_record_ids,
        })
        locators = [str(row.get("source_locator", "")) for row in rows]
        rule_locators = [str(rule.get("source_locator", "")) for rule in case.rules]
        checks.append({
            "case_id": case.case_id,
            "check": "executor_and_summarizer_citations_resolve",
            "passed": (
                all(locators)
                and len(set(locators)) == len(locators)
                and all(rule_locators)
                and len(set(rule_locators)) == len(rule_locators)
                and str(active_rule.get("source_locator", "")) in rule_locators
                and str(late_row.get("source_locator", "")) in locators
            ),
        })
    return checks


def prepare_taskpack(
    *,
    output_root: Path,
    root: Path = SAMPLE_ROOT,
    tokenizer_path: str = "/data/models/Qwen3-32B",
) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(f"prepare_output_exists:{output_root}")
    codec = load_local_codec(tokenizer_path)
    taskpack = compile_taskpack(codec, root=root)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    output_root.mkdir()
    (output_root / "sources").mkdir()
    (output_root / "ledger").mkdir()
    (output_root / "rules").mkdir()
    for case in (*taskpack.cases, taskpack.calibration_case):
        source_path = output_root / "sources" / f"{case.case_id}.json"
        source_path.write_text(
            json.dumps({"case_id": case.case_id, "rules": list(case.rules), "rows": list(case.source_rows)}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        ledger_path = output_root / str(case.source_rows[0]["source_locator"]).split("#", 1)[0]
        ledger_path.write_text(
            json.dumps({"case_id": case.case_id, "rows": list(case.source_rows)}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        rules_path = output_root / str(case.rules[0]["source_locator"]).split("#", 1)[0]
        rules_path.write_text(
            json.dumps({"case_id": case.case_id, "rules": list(case.rules)}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    logit_source = root / "logit_cases.json"
    if logit_source.exists():
        (output_root / "sources" / "logit_cases.json").write_text(logit_source.read_text(encoding="utf-8"), encoding="utf-8")
    referenced_logit_sources: set[Path] = set()
    for logit_case in (*taskpack.logit_cases, taskpack.logit_calibration_case):
        for candidate in logit_case.candidates:
            evidence_path = str(candidate.get("full_evidence_path", ""))
            if evidence_path:
                referenced_logit_sources.add((root / evidence_path).resolve())
    if referenced_logit_sources:
        referenced_root = output_root / "sources" / "referenced"
        referenced_root.mkdir(parents=True, exist_ok=True)
        for source_path in sorted(referenced_logit_sources):
            (referenced_root / source_path.name).write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
    gold_payload = {
        "schema_version": "statebus.model_assist_utility.gold.v1",
        "cases": {case.case_id: case.gold for case in taskpack.cases},
        "calibration_case": {"case_id": taskpack.calibration_case.case_id, "gold": taskpack.calibration_case.gold},
        "logit": {case.case_id: {"candidate": case.gold_candidate, "outcome": case.gold_outcome} for case in taskpack.logit_cases},
    }
    (output_root / "gold.json").write_text(json.dumps(gold_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_root / "compiled-prefixes.json").write_text(json.dumps({case.case_id: case.canonical_payload() | {"prefix_token_ids": list(case.prefix_token_ids)} for case in (*taskpack.cases, taskpack.calibration_case)}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    necessity = _necessity_checks(taskpack)
    (output_root / "necessity-checks.json").write_text(json.dumps({"schema_version": "statebus.model_assist_utility.necessity.v1", "checks": necessity}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest = dict(taskpack.manifest)
    manifest.update({
        "case_compiled_prefix_tokens": {case.case_id: case.target_prefix_tokens for case in (*taskpack.cases, taskpack.calibration_case)},
        "necessity_checks_passed": all(bool(item["passed"]) for item in necessity),
    })
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    taskpack_payload = taskpack.canonical_payload()
    taskpack_payload["manifest"] = manifest
    (output_root / "taskpack.json").write_text(json.dumps(taskpack_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_root / "plan.json").write_text(json.dumps(plan_artifact_payload(taskpack), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "output_root": str(output_root),
        "manifest": manifest,
        "cases": [case.canonical_payload() for case in taskpack.cases],
        "calibration_case": taskpack.calibration_case.canonical_payload(),
        "logit_cases": [case.canonical_payload() for case in taskpack.logit_cases],
        "logit_calibration_case": taskpack.logit_calibration_case.canonical_payload(),
        "necessity_checks": necessity,
    }


def plan_artifact_payload(taskpack: Taskpack) -> dict[str, Any]:
    return {
        "schema_version": "statebus.model_assist_utility.plan.v1",
        "suite_revision": taskpack.manifest["suite_revision"],
        "expected_slot_counts": {
            module: sum(item["module"] == module for item in taskpack.plan)
            for module in ("apc", "logit", "kv")
        },
        "gate_positions": [dict(item) for item in taskpack.plan if item["gate"]],
        "positions": [dict(item) for item in taskpack.plan],
        "warmups": {"business": 4, "choice": 2},
        "service_sequence": [
            "standard APC-on: calibration warmup, 8 APC and 12 Logit positions",
            "KV APC-off: calibration warmup, 8 KV positions, release and registry check",
            "restore original standard and verify health/models/tokenize/logprobs",
        ],
        "wall_budget_s": 5400,
    }


__all__ = [
    "CASE_IDS",
    "CALIBRATION_CASE_ID",
    "CACHE_NAMESPACE_PLACEHOLDER",
    "LOGIT_CASE_IDS",
    "LOGIT_CALIBRATION_CASE_ID",
    "PLAN_POSITIONS",
    "CompiledCase",
    "LogitCase",
    "Taskpack",
    "build_cache_namespace",
    "compile_taskpack",
    "load_local_codec",
    "logit_policy_order",
    "plan_artifact_payload",
    "prepare_taskpack",
]


def load_taskpack(*, tokenizer_path: str = "/data/models/Qwen3-32B", root: Path = SAMPLE_ROOT) -> Taskpack:
    return compile_taskpack(load_local_codec(tokenizer_path), root=root)
