from __future__ import annotations

import json

from v2.benchmark.engine_local_kv_tasks import (
    compile_cases,
    render_operating_appendix,
    validate_case_output,
)


class _CharacterCodec:
    def encode(self, text: str) -> tuple[int, ...]:
        return tuple(ord(character) for character in text)

    def decode(self, token_ids: tuple[int, ...]) -> str:
        return "".join(chr(value) for value in token_ids)


def test_case_sources_compile_to_exact_block_aligned_lengths() -> None:
    codec = _CharacterCodec()
    cases = compile_cases(codec)

    assert [len(case.parent_token_ids) for case in cases] == [2048, 4096, 6144]
    assert all(len(case.parent_token_ids) % case.block_size == 0 for case in cases)
    assert len({case.parent_token_digest for case in cases}) == 3
    assert [case.producer_max_tokens for case in cases] == [96, 96, 160]
    assert [case.consumer_max_tokens for case in cases] == [96, 96, 160]
    assert all(
        len(case.parent_token_ids)
        + len(case.producer_suffix_token_ids)
        + case.producer_max_tokens
        <= case.max_logical_sequence_tokens
        for case in cases
    )


def test_supplemental_ledger_is_unique_meaningful_context() -> None:
    appendix = render_operating_appendix()

    assert "Supplemental Regional Operating Ledger" in appendix
    assert "REG-O-01" in appendix
    assert "REG-N-12" in appendix
    assert "2026-09 Nova" in appendix
    assert len(set(appendix.splitlines())) >= 100


def test_fixed_validator_accepts_expected_json_and_rejects_wrong_value() -> None:
    case = compile_cases(_CharacterCodec())[1]
    accepted = validate_case_output(case, json.dumps(case.definition.expected_json))
    assert accepted.passed

    wrong = dict(case.definition.expected_json)
    wrong["q3_rev"] = 999
    rejected = validate_case_output(case, json.dumps(wrong))
    assert not rejected.passed
    assert any("q3_rev_mismatch" in value for value in rejected.errors)


def test_cross_company_validator_accepts_unambiguous_short_company_name() -> None:
    case = compile_cases(_CharacterCodec())[2]
    output = dict(case.definition.expected_json)
    output["higher_churn"] = "Orion"

    assert validate_case_output(case, json.dumps(output)).passed
