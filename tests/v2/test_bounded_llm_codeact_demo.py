from __future__ import annotations

import asyncio
import json
from pathlib import Path

from scripts.v2_diagnostics.bounded_llm_codeact_demo import (
    _deterministic_generated_source,
    _llm_generated_source,
    audit_generated_source,
    build_bounded_llm_codeact_demo_bundle,
)


def test_bounded_codeact_ast_policy_rejects_forbidden_call() -> None:
    audit = audit_generated_source("import subprocess\nsubprocess.run(['echo', 'bad'])\n")
    assert audit["pass"] is False
    assert "forbidden_import:subprocess" in audit["violations"]


def test_bounded_codeact_demo_writes_artifacts_with_resource_backend(tmp_path: Path) -> None:
    bundle_dir = build_bounded_llm_codeact_demo_bundle(
        output_root=tmp_path / "diagnostics",
        role_path_mode="deterministic",
        sandbox_backend="resource",
    )
    summary = json.loads((bundle_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["ok"] is True
    assert summary["ast_policy_pass"] is True
    assert summary["sandbox_backend"] == "resource"
    assert Path(summary["generated_source_path"]).exists()
    assert Path(summary["output_path"]).exists()
    assert summary["generation_attempt_count"] == 1
    assert (bundle_dir / "generation_attempts.json").exists()
    assert (bundle_dir / "summary.md").exists()


def test_bounded_codeact_api_generation_repairs_syntax_error(monkeypatch) -> None:
    class StubClient:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, messages, *, purpose, temperature=None):
            del messages, purpose, temperature
            self.calls += 1
            if self.calls == 1:
                return type("Result", (), {"text": "[])\n"})()
            return type("Result", (), {"text": _deterministic_generated_source()})()

    monkeypatch.setattr(
        "scripts.v2_diagnostics.bounded_llm_codeact_demo.build_llm_client",
        lambda config: StubClient(),
    )
    source, attempts = asyncio.run(_llm_generated_source(role_path_mode="api", max_repair_attempts=1))

    assert audit_generated_source(source)["pass"] is True
    assert len(attempts) == 2
    assert attempts[0]["ast_policy_pass"] is False
    assert attempts[1]["ast_policy_pass"] is True
    assert attempts[1]["repair"] is True
