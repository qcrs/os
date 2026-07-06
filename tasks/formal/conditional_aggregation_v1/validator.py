from __future__ import annotations


def _lookup(output: dict[str, object], key: str) -> object:
    current: object = output
    for segment in key.split("."):
        if not isinstance(current, dict) or segment not in current:
            return ""
        current = current[segment]
    return current


def validate_output(output: dict[str, object], expected_facts: dict[str, object]) -> bool:
    return all(str(_lookup(output, key)) == str(value) for key, value in expected_facts.items())
