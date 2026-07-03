from __future__ import annotations

import json
from pathlib import Path

from scripts.v2_diagnostics.bounded_llm_codeact_demo import (
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
    assert (bundle_dir / "summary.md").exists()
