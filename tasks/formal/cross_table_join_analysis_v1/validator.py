from __future__ import annotations


def validate_output(output: dict[str, object], expected_facts: dict[str, object]) -> bool:
    return all(str(output.get(key, "")) == str(value) for key, value in expected_facts.items())
