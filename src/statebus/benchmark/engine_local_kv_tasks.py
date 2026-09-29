from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Protocol

from statebus.utils import sha256_digest


CASE_SCHEMA_VERSION = "statebus.engine_local_kv_cases.v1"
COMPILED_CASE_SCHEMA_VERSION = "statebus.engine_local_kv_compiled_case.v1"
DEFAULT_CASE_DIR = (
    Path(__file__).resolve().parent
    / "samples"
    / "engine_local_kv_continuation"
)


class TokenCodec(Protocol):
    def encode(self, text: str) -> tuple[int, ...]: ...

    def decode(self, token_ids: tuple[int, ...]) -> str: ...


@dataclass(frozen=True)
class KVCaseDefinition:
    case_id: str
    target_parent_tokens: int
    source_documents: tuple[str, ...]
    task_instruction: str
    required_keys: tuple[str, ...]
    expected_json: Mapping[str, Any]
    keyword_expectations: Mapping[str, tuple[str, ...]]
    producer_max_tokens: int | None = None
    consumer_max_tokens: int | None = None


@dataclass(frozen=True)
class CompiledKVCase:
    definition: KVCaseDefinition
    parent_token_ids: tuple[int, ...]
    producer_suffix_token_ids: tuple[int, ...]
    parent_text: str
    source_digest: str
    parent_token_digest: str
    producer_suffix_digest: str
    block_size: int
    max_model_len: int
    max_logical_sequence_tokens: int
    producer_max_tokens: int
    consumer_max_tokens: int

    def consumer_suffix_text(self, executor_output: str) -> str:
        return (
            "\n\n# Upstream Executor Draft\n"
            f"{executor_output.strip()}\n\n"
            "# Final Summarizer Task\n"
            f"{self.definition.task_instruction}\n"
            "Use the authoritative evidence table when the draft conflicts with it. "
            "Return JSON only."
            "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        )

    def consumer_suffix_token_ids(
        self,
        codec: TokenCodec,
        executor_output: str,
    ) -> tuple[int, ...]:
        token_ids = codec.encode(self.consumer_suffix_text(executor_output))
        if not token_ids:
            raise ValueError("consumer suffix cannot be empty")
        logical_budget = (
            len(self.parent_token_ids) + len(token_ids) + self.consumer_max_tokens
        )
        if logical_budget > self.max_logical_sequence_tokens:
            raise ValueError(
                f"{self.definition.case_id} exceeds logical token budget: "
                f"{logical_budget}>{self.max_logical_sequence_tokens}"
            )
        return token_ids

    def canonical_payload(self, *, include_token_ids: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": COMPILED_CASE_SCHEMA_VERSION,
            "case_id": self.definition.case_id,
            "target_parent_tokens": self.definition.target_parent_tokens,
            "source_documents": list(self.definition.source_documents),
            "task_instruction": self.definition.task_instruction,
            "required_keys": list(self.definition.required_keys),
            "expected_json": dict(self.definition.expected_json),
            "keyword_expectations": {
                key: list(values)
                for key, values in self.definition.keyword_expectations.items()
            },
            "source_digest": self.source_digest,
            "parent_token_digest": self.parent_token_digest,
            "producer_suffix_digest": self.producer_suffix_digest,
            "parent_tokens": len(self.parent_token_ids),
            "producer_suffix_tokens": len(self.producer_suffix_token_ids),
            "block_size": self.block_size,
            "max_model_len": self.max_model_len,
            "max_logical_sequence_tokens": self.max_logical_sequence_tokens,
            "producer_max_tokens": self.producer_max_tokens,
            "consumer_max_tokens": self.consumer_max_tokens,
        }
        if include_token_ids:
            payload["parent_token_ids"] = list(self.parent_token_ids)
            payload["producer_suffix_token_ids"] = list(
                self.producer_suffix_token_ids
            )
        return payload


@dataclass(frozen=True)
class QualityResult:
    passed: bool
    parsed: Mapping[str, Any] | None
    errors: tuple[str, ...]

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "parsed": None if self.parsed is None else dict(self.parsed),
            "errors": list(self.errors),
        }


def load_case_definitions(
    case_dir: Path = DEFAULT_CASE_DIR,
) -> tuple[dict[str, Any], tuple[KVCaseDefinition, ...]]:
    manifest = json.loads((case_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != CASE_SCHEMA_VERSION:
        raise ValueError("engine-local KV case manifest schema mismatch")
    definitions: list[KVCaseDefinition] = []
    for value in manifest.get("cases", ()):
        keyword_values = value.get("keyword_expectations", {})
        definitions.append(
            KVCaseDefinition(
                case_id=str(value["case_id"]),
                target_parent_tokens=int(value["target_parent_tokens"]),
                source_documents=tuple(str(item) for item in value["source_documents"]),
                task_instruction=str(value["task_instruction"]),
                required_keys=tuple(str(item) for item in value["required_keys"]),
                expected_json=dict(value["expected_json"]),
                keyword_expectations={
                    str(key): tuple(str(item) for item in items)
                    for key, items in keyword_values.items()
                },
                producer_max_tokens=(
                    int(value["producer_max_tokens"])
                    if "producer_max_tokens" in value
                    else None
                ),
                consumer_max_tokens=(
                    int(value["consumer_max_tokens"])
                    if "consumer_max_tokens" in value
                    else None
                ),
            )
        )
    if not definitions or len({item.case_id for item in definitions}) != len(
        definitions
    ):
        raise ValueError("engine-local KV cases must be non-empty and unique")
    return manifest, tuple(definitions)


def compile_cases(
    codec: TokenCodec,
    case_dir: Path = DEFAULT_CASE_DIR,
) -> tuple[CompiledKVCase, ...]:
    manifest, definitions = load_case_definitions(case_dir)
    block_size = int(manifest["block_size"])
    max_model_len = int(manifest["max_model_len"])
    max_logical = int(manifest["max_logical_sequence_tokens"])
    default_producer_max_tokens = int(manifest["producer_max_tokens"])
    default_consumer_max_tokens = int(manifest["consumer_max_tokens"])
    compiled: list[CompiledKVCase] = []
    for definition in definitions:
        producer_max_tokens = (
            definition.producer_max_tokens or default_producer_max_tokens
        )
        consumer_max_tokens = (
            definition.consumer_max_tokens or default_consumer_max_tokens
        )
        if producer_max_tokens <= 0 or consumer_max_tokens <= 0:
            raise ValueError(f"{definition.case_id} generation budget must be positive")
        if definition.target_parent_tokens % block_size:
            raise ValueError(f"{definition.case_id} is not block aligned")
        sources = [
            (case_dir / filename).read_text(encoding="utf-8")
            for filename in definition.source_documents
        ]
        preferred_company = (
            "Nova"
            if definition.source_documents == ("nova_retail_ops_report_2026.md",)
            else "Orion"
            if definition.source_documents == ("orion_factory_ops_report_2026.md",)
            else None
        )
        evidence = "\n\n".join(
            sources + [render_operating_appendix(preferred_company)]
        )
        parent_source = _shared_parent_source(definition.case_id, evidence)
        source_ids = codec.encode(parent_source)
        if len(source_ids) < definition.target_parent_tokens:
            raise ValueError(
                f"{definition.case_id} only has {len(source_ids)} source tokens"
            )
        parent_ids = source_ids[: definition.target_parent_tokens]
        parent_text = codec.decode(parent_ids)
        if codec.encode(parent_text) != parent_ids:
            raise ValueError(f"{definition.case_id} tokenizer roundtrip mismatch")
        producer_suffix = codec.encode(_producer_suffix(definition))
        producer_budget = (
            len(parent_ids) + len(producer_suffix) + producer_max_tokens
        )
        if producer_budget > max_logical:
            raise ValueError(
                f"{definition.case_id} producer budget exceeds {max_logical}"
            )
        compiled.append(
            CompiledKVCase(
                definition=definition,
                parent_token_ids=parent_ids,
                producer_suffix_token_ids=producer_suffix,
                parent_text=parent_text,
                source_digest=sha256_digest(parent_source),
                parent_token_digest=sha256_digest(list(parent_ids)),
                producer_suffix_digest=sha256_digest(list(producer_suffix)),
                block_size=block_size,
                max_model_len=max_model_len,
                max_logical_sequence_tokens=max_logical,
                producer_max_tokens=producer_max_tokens,
                consumer_max_tokens=consumer_max_tokens,
            )
        )
    return tuple(compiled)


def load_compiled_cases(path: Path) -> tuple[CompiledKVCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != COMPILED_CASE_SCHEMA_VERSION:
        raise ValueError("compiled engine-local KV case schema mismatch")
    parent_dir = path.parent / "compiled_parents"
    cases: list[CompiledKVCase] = []
    for value in payload.get("cases", ()):
        if value.get("schema_version") != COMPILED_CASE_SCHEMA_VERSION:
            raise ValueError("compiled case entry schema mismatch")
        keyword_values = value.get("keyword_expectations", {})
        definition = KVCaseDefinition(
            case_id=str(value["case_id"]),
            target_parent_tokens=int(value["target_parent_tokens"]),
            source_documents=tuple(str(item) for item in value["source_documents"]),
            task_instruction=str(value["task_instruction"]),
            required_keys=tuple(str(item) for item in value["required_keys"]),
            expected_json=dict(value["expected_json"]),
            keyword_expectations={
                str(key): tuple(str(item) for item in items)
                for key, items in keyword_values.items()
            },
            producer_max_tokens=int(value["producer_max_tokens"]),
            consumer_max_tokens=int(value["consumer_max_tokens"]),
        )
        parent_ids = tuple(int(item) for item in value["parent_token_ids"])
        producer_suffix = tuple(
            int(item) for item in value["producer_suffix_token_ids"]
        )
        case = CompiledKVCase(
            definition=definition,
            parent_token_ids=parent_ids,
            producer_suffix_token_ids=producer_suffix,
            parent_text=(parent_dir / f"{definition.case_id}.txt").read_text(
                encoding="utf-8"
            ),
            source_digest=str(value["source_digest"]),
            parent_token_digest=str(value["parent_token_digest"]),
            producer_suffix_digest=str(value["producer_suffix_digest"]),
            block_size=int(value["block_size"]),
            max_model_len=int(value["max_model_len"]),
            max_logical_sequence_tokens=int(value["max_logical_sequence_tokens"]),
            producer_max_tokens=int(value["producer_max_tokens"]),
            consumer_max_tokens=int(value["consumer_max_tokens"]),
        )
        if (
            len(parent_ids) != definition.target_parent_tokens
            or len(parent_ids) % case.block_size
            or sha256_digest(list(parent_ids)) != case.parent_token_digest
            or sha256_digest(list(producer_suffix)) != case.producer_suffix_digest
        ):
            raise ValueError(f"compiled case integrity failed: {definition.case_id}")
        cases.append(case)
    if not cases or len({case.definition.case_id for case in cases}) != len(cases):
        raise ValueError("compiled cases must be non-empty and unique")
    return tuple(cases)


def validate_case_output(case: CompiledKVCase, output_text: str) -> QualityResult:
    parsed = _extract_json_object(output_text)
    if parsed is None:
        return QualityResult(False, None, ("json_parse_failed",))
    errors: list[str] = []
    expected_keys = set(case.definition.required_keys)
    observed_keys = set(parsed)
    if observed_keys != expected_keys:
        errors.append(
            "key_mismatch:"
            f"missing={sorted(expected_keys - observed_keys)},"
            f"extra={sorted(observed_keys - expected_keys)}"
        )
    keyword_fields = case.definition.keyword_expectations
    for key, expected in case.definition.expected_json.items():
        if key not in parsed:
            continue
        actual = parsed[key]
        if key in keyword_fields:
            normalized = str(actual).casefold()
            missing = [
                keyword for keyword in keyword_fields[key] if keyword.casefold() not in normalized
            ]
            if missing:
                errors.append(f"{key}_keywords_missing:{','.join(missing)}")
        elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
            try:
                delta = abs(float(actual) - float(expected))
            except (TypeError, ValueError):
                errors.append(f"{key}_not_numeric")
            else:
                if delta > 0.11:
                    errors.append(f"{key}_mismatch:{actual}!={expected}")
        elif str(actual).strip().casefold() != str(expected).strip().casefold():
            errors.append(f"{key}_mismatch:{actual}!={expected}")
    return QualityResult(not errors, parsed, tuple(errors))


def render_operating_appendix(preferred_company: str | None = None) -> str:
    """Build deterministic, unique operating rows used to reach long contexts."""

    companies = (
        ("Orion", 118, 96.4, 142, 380),
        ("Nova", 96, 95.7, 119, 310),
    )
    if preferred_company:
        companies = tuple(
            sorted(companies, key=lambda value: value[0] != preferred_company)
        )
    regions = (
        "Central",
        "Northeast",
        "Southeast",
        "Great Lakes",
        "Mountain",
        "Pacific",
        "Southwest",
        "Mid-Atlantic",
    )
    quarters = ("2026Q1", "2026Q2", "2026Q3")
    interventions = (
        "reserve carrier capacity",
        "qualify a secondary supplier",
        "advance deployment-window confirmation",
        "add a supervised night shift",
        "tighten exception review",
        "rebalance weekend lanes",
        "increase reliability sampling",
        "publish daily backlog aging",
    )
    rows = [
        "# Supplemental Regional Operating Ledger",
        "",
        "The following deterministic ledger adds realistic regional and control detail. "
        "It does not override either company's authoritative quarterly metric table.",
        "",
        "| company | quarter | region | backlog_units | supplier_otif_pct | "
        "expedite_cost_kusd | training_hours | exception_count | control_action |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for company_index, (company, backlog, otif, freight, training) in enumerate(
        companies
    ):
        for quarter_index, quarter in enumerate(quarters):
            for region_index, region in enumerate(regions):
                pressure = quarter_index * 9 + region_index * 2 + company_index * 3
                rows.append(
                    f"| {company} | {quarter} | {region} | {backlog + pressure} | "
                    f"{otif - quarter_index * 1.1 - region_index * 0.13:.2f} | "
                    f"{freight + pressure * 4} | {training + quarter_index * 35 + region_index * 7} | "
                    f"{3 + quarter_index * 2 + region_index} | "
                    f"{interventions[(region_index + quarter_index + company_index) % len(interventions)]} |"
                )

    rows.extend(
        [
            "",
            "# Supplier And Carrier Qualification Register",
            "",
            "Each line is a distinct review item with an owner, observed control signal, "
            "and next verification step.",
            "",
            "| item_id | company | dependency | control_signal | owner | next_check | disposition |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    dependencies = (
        "encoder lot A",
        "encoder lot B",
        "motor-driver board",
        "firmware validation queue",
        "enterprise deployment window",
        "reserved freight lane",
        "weekend carrier north",
        "weekend carrier south",
        "cross-dock overflow",
        "temporary labor pool",
        "slotting exception queue",
        "route-density forecast",
    )
    dispositions = (
        "monitor weekly",
        "complete second-source audit",
        "hold capacity buffer",
        "escalate missed threshold",
        "verify recovery evidence",
        "close after two stable periods",
    )
    for company_index, (company, *_rest) in enumerate(companies):
        for dependency_index, dependency in enumerate(dependencies):
            score = 72 + company_index * 5 + dependency_index * 2
            rows.append(
                f"| REG-{company[0]}-{dependency_index + 1:02d} | {company} | {dependency} | "
                f"control score {score}; variance band {2 + dependency_index % 5} | "
                f"owner-{(dependency_index % 6) + 1} | 2026-{10 + dependency_index // 4:02d}-"
                f"{5 + dependency_index % 19:02d} | "
                f"{dispositions[(dependency_index + company_index) % len(dispositions)]} |"
            )

    rows.extend(
        [
            "",
            "# Monthly Exception Commentary",
            "",
        ]
    )
    exception_types = (
        "supplier confirmation lag",
        "maintenance-window reschedule",
        "expedited freight approval",
        "weekend coverage shortfall",
        "quality inspection extension",
        "route-density threshold miss",
    )
    for company_index, (company, *_rest) in enumerate(companies):
        for month in range(1, 10):
            exception = exception_types[(month + company_index) % len(exception_types)]
            rows.append(
                f"- 2026-{month:02d} {company}: review {month + company_index + 2} recorded "
                f"{exception}; the control owner retained evidence packet "
                f"EP-{company[0]}-{month:02d}, checked {11 + month * 3} sampled orders, "
                f"and scheduled follow-up after {2 + month % 4} operating weeks."
            )
    return "\n".join(rows)


def _shared_parent_source(case_id: str, evidence: str) -> str:
    return (
        "<|im_start|>system\n"
        "You are a financial operations analyst. Use only the supplied offline "
        "evidence. Treat each report's Metric Table as authoritative, preserve "
        "units, and do not invent values. The supplemental ledger provides "
        "context but never overrides a Metric Table."
        "<|im_end|>\n<|im_start|>user\n"
        f"# StateBus Engine-Local KV Case: {case_id}\n\n"
        "# Offline Evidence Dossier\n\n"
        f"{evidence}"
    )


def _producer_suffix(definition: KVCaseDefinition) -> str:
    return (
        "\n\n# Executor Task\n"
        f"{definition.task_instruction}\n"
        "Prepare a compact evidence-grounded draft for a downstream summarizer. "
        "Return JSON only."
        "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    candidates = [stripped]
    opening = stripped.find("{")
    if opening >= 0:
        candidates.append(stripped[opening:])
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            value, _end = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


__all__ = [
    "CompiledKVCase",
    "DEFAULT_CASE_DIR",
    "KVCaseDefinition",
    "QualityResult",
    "TokenCodec",
    "compile_cases",
    "load_case_definitions",
    "load_compiled_cases",
    "render_operating_appendix",
    "validate_case_output",
]
