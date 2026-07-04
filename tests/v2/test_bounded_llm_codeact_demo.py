from __future__ import annotations

import asyncio
import json
from pathlib import Path

from scripts.v2_diagnostics.bounded_llm_codeact_demo import (
    _deterministic_generated_source,
    _extract_code,
    _extract_python_source,
    _generation_prompt,
    _llm_generated_source,
    _repair_prompt,
    audit_generated_source,
    build_bounded_llm_codeact_demo_bundle,
)


def test_bounded_codeact_ast_policy_rejects_forbidden_call() -> None:
    audit = audit_generated_source("import subprocess\nsubprocess.run(['echo', 'bad'])\n")
    assert audit["pass"] is False
    assert "forbidden_import:subprocess" in audit["violations"]


def test_bounded_codeact_ast_policy_rejects_path_open_call() -> None:
    audit = audit_generated_source(
        "from pathlib import Path\n"
        "import json\n"
        "payload = json.loads((Path('inputs') / 'task.json').open().read())\n"
        "(Path('outputs') / 'bounded_codeact_result.json').write_text(json.dumps(payload))\n"
    )
    assert audit["pass"] is False
    assert "forbidden_call:open" in audit["violations"]


def test_bounded_codeact_ast_policy_rejects_inert_json_wrapper() -> None:
    audit = audit_generated_source(json.dumps({"code": _deterministic_generated_source()}))
    assert audit["pass"] is False
    assert "missing_input_path:task.json" in audit["violations"]
    assert "missing_output_path:bounded_codeact_result.json" in audit["violations"]
    assert "missing_output_write_call" in audit["violations"]


def test_extract_python_source_unwraps_json_code_payload() -> None:
    wrapped = json.dumps({"code": _deterministic_generated_source()})
    assert _extract_python_source(wrapped) == _deterministic_generated_source()


def test_extract_code_unwraps_markdown_fence_with_leading_prose() -> None:
    wrapped = f"Here is the code:\n```python\n{_deterministic_generated_source()}```"
    assert _extract_code(wrapped) == _deterministic_generated_source()


def test_bounded_codeact_ast_policy_allows_extended_stdlib_imports() -> None:
    source = (
        "import csv\n"
        "import json\n"
        "import re\n"
        "from collections import Counter\n"
        "from datetime import datetime\n"
        "from decimal import Decimal\n"
        "from itertools import islice\n"
        "from pathlib import Path\n"
        "payload = json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
        "result = {'rows': len(list(islice(payload['quarters'], 0, 10))), 'stamp': str(datetime.utcnow()),"
        " 'ok': bool(re.match('revenue', payload['metric'])), 'kind': str(Decimal('1.0')),"
        " 'counts': Counter(['a']).most_common(1)[0][0], 'dialect': csv.excel.delimiter}\n"
        "out = Path('outputs')\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "(out / 'bounded_codeact_result.json').write_text(json.dumps(result), encoding='utf-8')\n"
    )
    audit = audit_generated_source(source)
    assert audit["pass"] is True


def test_generation_prompt_requires_single_literal_input_path() -> None:
    prompt = _generation_prompt(input_example=json.dumps({"quarters": []}))
    assert 'payload = json.loads(Path("inputs/task.json").read_text(encoding="utf-8"))' in prompt
    assert 'Do NOT split the input path into Path("inputs") / "task.json"' in prompt
    assert "Return a COMPLETE Python file, not a fragment." in prompt


def test_repair_prompt_includes_exact_input_fix_for_missing_task_json() -> None:
    prompt = _repair_prompt(source="result = {}\n", audit={"violations": ["missing_input_path:task.json"]})
    assert 'insert this exact line and do not rewrite it' in prompt
    assert 'payload = json.loads(Path("inputs/task.json").read_text(encoding="utf-8"))' in prompt


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
    seen: dict[str, object] = {}

    class StubClient:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, messages, *, purpose, temperature=None):
            del messages, purpose, temperature
            self.calls += 1
            if self.calls == 1:
                return type("Result", (), {"text": "[])\n"})()
            return type("Result", (), {"text": _deterministic_generated_source()})()

    def _build_stub_client(config):
        seen["executor_json"] = config.role_config("executor").json_output
        client = StubClient()
        seen["client"] = client
        return client

    monkeypatch.setattr(
        "scripts.v2_diagnostics.bounded_llm_codeact_demo.build_llm_client",
        _build_stub_client,
    )
    source, attempts = asyncio.run(_llm_generated_source(role_path_mode="api", max_repair_attempts=1))

    assert audit_generated_source(source)["pass"] is True
    assert seen["executor_json"] is False
    assert len(attempts) == 2
    assert attempts[0]["ast_policy_pass"] is False
    assert attempts[1]["ast_policy_pass"] is True
    assert attempts[1]["repair"] is True


def test_bounded_codeact_api_generation_unwraps_repaired_json_code(monkeypatch) -> None:
    class StubClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, purpose, temperature
            return type("Result", (), {"text": json.dumps({"code": _deterministic_generated_source()})})()

    monkeypatch.setattr(
        "scripts.v2_diagnostics.bounded_llm_codeact_demo.build_llm_client",
        lambda config: StubClient(),
    )
    source, attempts = asyncio.run(_llm_generated_source(role_path_mode="api", max_repair_attempts=0))

    assert source == _deterministic_generated_source()
    assert audit_generated_source(source)["pass"] is True
    assert len(attempts) == 1
    assert attempts[0]["ast_policy_pass"] is True


def test_bounded_codeact_api_generation_falls_back_after_policy_failures(monkeypatch) -> None:
    class StubClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, purpose, temperature
            return type("Result", (), {"text": "result = {}\n"})()

    monkeypatch.setattr(
        "scripts.v2_diagnostics.bounded_llm_codeact_demo.build_llm_client",
        lambda config: StubClient(),
    )
    source, attempts = asyncio.run(_llm_generated_source(role_path_mode="api", max_repair_attempts=1))

    assert source == _deterministic_generated_source()
    assert audit_generated_source(source)["pass"] is True
    assert len(attempts) == 3
    assert attempts[0]["ast_policy_pass"] is False
    assert attempts[1]["ast_policy_pass"] is False
    assert attempts[2]["fallback"] is True
    assert attempts[2]["ast_policy_pass"] is True
