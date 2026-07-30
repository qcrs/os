from __future__ import annotations

import argparse
import ast
import asyncio
import json
import re
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from statebus.integrations.llm import ChatMessage, LLMConfig, build_llm_client
from statebus.runtime.codeact_sandbox import CodeActSandboxConfig, CodeActSandboxRunner
from statebus.utils import sha256_digest, stable_json_dumps


SCHEMA_VERSION = "statebus.bounded_llm_codeact_demo.v1"
ALLOWED_IMPORT_ROOTS = {
    "collections",
    "csv",
    "datetime",
    "decimal",
    "itertools",
    "json",
    "math",
    "pathlib",
    "re",
    "statistics",
}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "open", "input", "__import__"}
FORBIDDEN_NAME_ROOTS = {"socket", "subprocess", "requests", "urllib", "http", "os", "sys", "shutil"}


def _timestamp_label() -> str:
    return time.strftime("%Y%m%d_%H%M%S", time.localtime())


def _default_output_root() -> Path:
    return Path("/tmp") / "statebus-bounded-codeact-demo"


def _demo_input_payload() -> dict[str, object]:
    return {
        "task_id": "bounded-codeact-demo-001",
        "task": "Compute quarterly revenue growth and write a bounded JSON artifact.",
        "metric": "revenue_musd",
        "quarters": [
            {"quarter": "2026Q1", "value": 120.0},
            {"quarter": "2026Q2", "value": 132.0},
            {"quarter": "2026Q3", "value": 145.0},
        ],
        "required_outputs": ["metric", "point_count", "delta_abs", "growth_pct", "summary_text"],
    }


def _deterministic_generated_source() -> str:
    return textwrap.dedent(
        """
        from pathlib import Path
        import json

        root = Path.cwd()
        payload = json.loads((root / "inputs" / "task.json").read_text(encoding="utf-8"))
        points = payload["quarters"]
        first = float(points[0]["value"])
        last = float(points[-1]["value"])
        delta_abs = round(last - first, 6)
        growth_pct = round((delta_abs / first) * 100.0, 6) if first else 0.0
        result = {
            "task_id": payload["task_id"],
            "metric": payload["metric"],
            "point_count": len(points),
            "delta_abs": delta_abs,
            "growth_pct": growth_pct,
            "summary_text": f"{payload['metric']} increased by {delta_abs} from {points[0]['quarter']} to {points[-1]['quarter']}.",
        }
        output_dir = root / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "bounded_codeact_result.json").write_text(
            json.dumps(result, ensure_ascii=True, sort_keys=True) + "\\n",
            encoding="utf-8",
        )
        print("bounded-codeact-demo-ok")
        """
    ).strip() + "\n"


def _allowed_imports_text() -> str:
    return ", ".join(sorted(ALLOWED_IMPORT_ROOTS))


def _required_input_line() -> str:
    return 'payload = json.loads(Path("inputs/task.json").read_text(encoding="utf-8"))'


def _required_output_block() -> str:
    return textwrap.dedent(
        """
        out = Path("outputs")
        out.mkdir(parents=True, exist_ok=True)
        (out / "bounded_codeact_result.json").write_text(
            json.dumps(result, ensure_ascii=True, sort_keys=True),
            encoding="utf-8",
        )
        """
    ).strip()


def _safe_result_template() -> str:
    return textwrap.dedent(
        f"""
        import json
        from pathlib import Path

        {_required_input_line()}
        points = payload["quarters"]
        first = float(points[0]["value"])
        last = float(points[-1]["value"])
        delta_abs = round(last - first, 6)
        growth_pct = round((delta_abs / first) * 100.0, 6) if first else 0.0
        result = {{
            "metric": payload["metric"],
            "point_count": len(points),
            "delta_abs": delta_abs,
            "growth_pct": growth_pct,
            "summary_text": f"{{payload['metric']}} changed by {{delta_abs}} from {{points[0]['quarter']}} to {{points[-1]['quarter']}}.",
        }}
        {_required_output_block()}
        """
    ).strip()


def _generation_prompt(*, input_example: str) -> str:
    return textwrap.dedent(
        f"""
        You are a Python code generator for a sandboxed execution environment.
        Return ONLY Python code. Do not wrap the answer in markdown, JSON, or prose.
        Return a COMPLETE Python file, not a fragment. The first line of the answer must be `import json`.

        === AST POLICY: ALLOWED IMPORT ROOTS ONLY ===
        {_allowed_imports_text()}

        === FORBIDDEN ===
        - Imports or names rooted at: os, sys, subprocess, socket, requests, urllib, http, shutil
        - Calls: open(), eval(), exec(), compile(), input(), __import__()
        - Dynamic workspace discovery such as Path.cwd(), __file__, os.path.join(), or shell access

        === REQUIRED FILE PATH LITERALS ===
        - The exact string literal "inputs/task.json" MUST appear in the code as ONE literal
        - The exact string literal "bounded_codeact_result.json" MUST appear in the code
        - Do NOT split the input path into Path("inputs") / "task.json"
        - Copy this input line EXACTLY:
        ```python
        {_required_input_line()}
        ```
        - Write output under outputs/ while keeping the literal filename EXACTLY:
        ```python
        {_required_output_block()}
        ```

        === SAFE STARTER TEMPLATE ===
        Copy this whole file and then adjust only the calculation or summary text if needed.
        Do not drop the import lines. Do not start from the middle of the file.
        ```python
        {_safe_result_template()}
        ```

        === TASK INPUT SCHEMA ===
        {input_example}

        === REQUIRED OUTPUT FIELDS ===
        metric, point_count, delta_abs, growth_pct, summary_text

        === IMPORTANT ===
        - The easiest valid answer is to copy SAFE STARTER TEMPLATE and adjust only the summary text if needed.
        - Keep the input line and output block unchanged.
        - If you compose the input path from multiple strings, the code will be rejected.
        - Do not start with a fragment such as `["quarters"]`, `points = ...`, or `result = ...`.

        Use the smallest valid import set. Prefer pathlib.Path for all file access.
        """
    ).strip()


async def _llm_generated_source(
    *,
    role_path_mode: str,
    max_repair_attempts: int = 2,
) -> tuple[str, list[dict[str, object]]]:
    if role_path_mode != "api":
        source = _deterministic_generated_source()
        audit = audit_generated_source(source)
        return source, [_generation_attempt_payload(source=source, audit=audit, attempt=0, repair=False)]
    input_example = stable_json_dumps(_demo_input_payload())
    prompt = _generation_prompt(input_example=input_example)
    # Code generation requires raw text output. The default executor role config
    # requests JSON objects, which truncates or reshapes Python source replies.
    client = build_llm_client(
        LLMConfig.from_runtime()
        .with_mode("api")
        .with_role_override("executor", json_output=False)
    )
    source = ""
    attempts: list[dict[str, object]] = []
    current_prompt = prompt
    for attempt in range(max_repair_attempts + 1):
        result = await client.complete([ChatMessage(role="user", content=current_prompt)], purpose="executor")
        source = _extract_code(result.text)
        audit = audit_generated_source(source)
        attempts.append(_generation_attempt_payload(source=source, audit=audit, attempt=attempt, repair=attempt > 0))
        if audit["pass"]:
            return source, attempts
        current_prompt = _repair_prompt(source=source, audit=audit)
    fallback_source = _deterministic_generated_source()
    fallback_audit = audit_generated_source(fallback_source)
    attempts.append(
        _generation_attempt_payload(
            source=fallback_source,
            audit=fallback_audit,
            attempt=len(attempts),
            repair=False,
            fallback=True,
        )
    )
    return fallback_source, attempts


def _generation_attempt_payload(
    *,
    source: str,
    audit: dict[str, object],
    attempt: int,
    repair: bool,
    fallback: bool = False,
) -> dict[str, object]:
    return {
        "attempt": attempt,
        "repair": repair,
        "fallback": fallback,
        "source_hash": sha256_digest(source.encode("utf-8")),
        "ast_policy_pass": bool(audit["pass"]),
        "violations": list(audit.get("violations", [])),
    }


def _violation_explanation(violation: str) -> str:
    if violation.startswith("missing_input_path:"):
        fname = violation.split(":", 1)[1]
        return (
            f"missing_input_path:{fname} — "
            f"Your code MUST contain the string literal \"{fname}\" "
            f"(e.g. Path(\"inputs/{fname}\").read_text(...)). "
            f"Do NOT build the path with separate string parts or variables."
        )
    if violation.startswith("missing_output_path:"):
        fname = violation.split(":", 1)[1]
        return (
            f"missing_output_path:{fname} — "
            f"Your code MUST contain the string literal \"{fname}\" "
            f"(e.g. (out / \"{fname}\").write_text(...))."
        )
    if violation.startswith("forbidden_import:") or violation.startswith("forbidden_import_from:"):
        return f"{violation} — remove this import; allowed roots: {_allowed_imports_text()}."
    if violation.startswith("forbidden_call:") or violation.startswith("forbidden_call_root:"):
        return f"{violation} — remove or replace this call; use pathlib.Path for file I/O."
    return violation


def _numbered_source(source: str) -> str:
    lines = source.rstrip("\n").splitlines()
    if not lines:
        return "1: <empty>"
    return "\n".join(f"{index:>3}: {line}" for index, line in enumerate(lines, start=1))


def _repair_hint(violation: str) -> str:
    if violation.startswith("forbidden_import:") or violation.startswith("forbidden_import_from:"):
        return f"remove that import and keep only: {_allowed_imports_text()}"
    if violation == "missing_input_path:task.json":
        return f'insert this exact line and do not rewrite it: `{_required_input_line()}`'
    if violation == "missing_output_path:bounded_codeact_result.json":
        return 'write through `(Path("outputs") / "bounded_codeact_result.json").write_text(...)`'
    if violation == "missing_output_write_call":
        return "finish by writing the JSON result with Path.write_text(...)"
    if violation.startswith("forbidden_call:open"):
        return 'replace open() with `Path("...").read_text(...)` or `write_text(...)`'
    if violation.startswith("forbidden_call:"):
        return "remove the forbidden call and keep the logic in pure Python"
    if violation.startswith("forbidden_call_root:") or violation.startswith("forbidden_name:"):
        return "remove the forbidden module/root reference entirely"
    if violation.startswith("syntax_error:"):
        return "return syntactically valid Python with balanced brackets and indentation"
    return "repair this violation without changing the task logic"


def _repair_prompt(*, source: str, audit: dict[str, object]) -> str:
    violations = list(audit.get("violations", []))
    details = audit.get("violation_details", [])
    detail_by_code = {
        detail.get("violation"): detail
        for detail in details
        if isinstance(detail, dict) and isinstance(detail.get("violation"), str)
    }
    if violations:
        violation_lines = "\n".join(
            (
                f"  - line {detail_by_code[v].get('line')}: {v} -> {_repair_hint(v)}"
                if isinstance(v, str) and v in detail_by_code and detail_by_code[v].get("line") is not None
                else f"  - {v}: {_repair_hint(v)}"
            )
            for v in violations
        )
    else:
        violation_lines = "  - inspect the source and return valid code only"
    return textwrap.dedent(
        f"""
        Your previous Python script FAILED the AST policy. Repair it without changing the task logic.

        SOURCE WITH LINE NUMBERS:
        {_numbered_source(source)}

        REQUIRED FIXES:
        {violation_lines}

        REMINDERS:
        - Allowed import roots only: {_allowed_imports_text()}
        - Never use open(), eval(), exec(), compile(), input(), shell access, or network access
        - Keep the exact literals "inputs/task.json" and "bounded_codeact_result.json"
        - The input path must appear as ONE literal, not as Path("inputs") / "task.json"
        - Use pathlib.Path for all file I/O
        - Write the final JSON artifact under outputs/
        - Return a COMPLETE file from the first import line; do not return a mid-file fragment.
        - If needed, start from this safe skeleton and fill in the logic:
        ```python
          {_safe_result_template()}
        ```

        Return ONLY raw Python code — no markdown fences, no JSON wrapper.
        """
    ).strip()


def _extract_code(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("code"), str):
            return _extract_code(payload["code"])
    fenced = re.search(r"```(?:python)?\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1).strip() + "\n"
    return stripped + "\n"


def _extract_python_source(text: str) -> str:
    return _extract_code(text)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip() + "\n"
    return stripped + "\n"


def audit_generated_source(source: str) -> dict[str, object]:
    violations: list[str] = []
    violation_details: list[dict[str, object]] = []

    def _record(violation: str, *, node: ast.AST | None = None) -> None:
        violations.append(violation)
        line = getattr(node, "lineno", None) if node is not None else None
        violation_details.append(
            {
                "violation": violation,
                "line": int(line) if isinstance(line, int) else None,
            }
        )

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "pass": False,
            "violations": [f"syntax_error:{exc.msg}"],
            "violation_details": [{"violation": f"syntax_error:{exc.msg}", "line": exc.lineno}],
            "node_count": 0,
        }
    node_count = 0
    string_literals: list[str] = []
    has_output_write_call = False
    for node in ast.walk(tree):
        node_count += 1
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            string_literals.append(node.value)
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root not in ALLOWED_IMPORT_ROOTS:
                    _record(f"forbidden_import:{alias.name}", node=node)
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root not in ALLOWED_IMPORT_ROOTS:
                _record(f"forbidden_import_from:{node.module}", node=node)
        elif isinstance(node, ast.Call):
            call_name = _call_name(node.func)
            if call_name == "write_text" or call_name.endswith(".write_text") or call_name == "json.dump":
                has_output_write_call = True
            if call_name in FORBIDDEN_CALLS or call_name.endswith(".open"):
                _record(f"forbidden_call:{call_name}", node=node)
            root_name = call_name.split(".", 1)[0]
            if root_name in FORBIDDEN_NAME_ROOTS:
                _record(f"forbidden_call_root:{call_name}", node=node)
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAME_ROOTS:
            _record(f"forbidden_name:{node.id}", node=node)
    if not _has_path_literal(string_literals, "task.json"):
        _record("missing_input_path:task.json")
    if not _has_path_literal(string_literals, "bounded_codeact_result.json"):
        _record("missing_output_path:bounded_codeact_result.json")
    if not has_output_write_call:
        _record("missing_output_write_call")
    return {
        "schema_version": SCHEMA_VERSION,
        "pass": not violations,
        "violations": sorted(set(violations)),
        "violation_details": sorted(
            (
                {"violation": detail["violation"], "line": detail["line"]}
                for detail in violation_details
            ),
            key=lambda detail: (detail["violation"], -1 if detail["line"] is None else int(detail["line"])),
        ),
        "node_count": node_count,
        "allowed_import_roots": sorted(ALLOWED_IMPORT_ROOTS),
        "forbidden_calls": sorted(FORBIDDEN_CALLS),
        "forbidden_name_roots": sorted(FORBIDDEN_NAME_ROOTS),
    }


def _has_path_literal(values: list[str], filename: str) -> bool:
    return any(value == filename or value.endswith(f"/{filename}") or value.endswith(f"\\{filename}") for value in values)


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def build_bounded_llm_codeact_demo_bundle(
    *,
    output_root: Path,
    role_path_mode: str = "deterministic",
    sandbox_backend: str = "resource",
    python_executable: str = sys.executable,
    suite_id: str = "bounded-llm-codeact-demo",
    max_repair_attempts: int = 2,
) -> Path:
    bundle_dir = output_root / f"{suite_id}-{_timestamp_label()}"
    workspace_root = bundle_dir / "workspace"
    inputs_dir = workspace_root / "inputs"
    generated_dir = workspace_root / "generated"
    outputs_dir = workspace_root / "outputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    input_payload = _demo_input_payload()
    (inputs_dir / "task.json").write_text(stable_json_dumps(input_payload) + "\n", encoding="utf-8")
    source, generation_attempts = asyncio.run(
        _llm_generated_source(
            role_path_mode=role_path_mode,
            max_repair_attempts=max_repair_attempts,
        )
    )
    generated_path = generated_dir / "llm_generated_action.py"
    generated_path.write_text(source, encoding="utf-8")
    ast_audit = audit_generated_source(source)
    ast_audit_path = bundle_dir / "ast_audit.json"
    ast_audit_path.write_text(stable_json_dumps(ast_audit) + "\n", encoding="utf-8")
    generation_attempts_path = bundle_dir / "generation_attempts.json"
    generation_attempts_path.write_text(
        stable_json_dumps({"attempts": generation_attempts}) + "\n",
        encoding="utf-8",
    )

    sandbox_payload: dict[str, object]
    if ast_audit["pass"]:
        runner = CodeActSandboxRunner(
            CodeActSandboxConfig(
                requested_backend=sandbox_backend,
                timeout_seconds=30.0,
            )
        )
        sandbox_result = runner.run(
            host_command=[python_executable, str(generated_path)],
            bwrap_command=[python_executable, "/sandbox/workspace/generated/llm_generated_action.py"],
            cwd=workspace_root,
            host_env={},
            bwrap_env={},
            workspace_root=workspace_root,
            project_root=REPO_ROOT,
        )
        completed = sandbox_result.completed
        sandbox_payload = {
            "requested_backend": sandbox_result.requested_backend,
            "actual_backend": sandbox_result.actual_backend,
            "fallback_reason": sandbox_result.fallback_reason,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    else:
        sandbox_payload = {
            "requested_backend": sandbox_backend,
            "actual_backend": "not_run",
            "fallback_reason": "ast_policy_failed",
            "returncode": -1,
            "stdout": "",
            "stderr": "",
        }
    sandbox_result_path = bundle_dir / "sandbox_result.json"
    sandbox_result_path.write_text(stable_json_dumps(sandbox_payload) + "\n", encoding="utf-8")

    output_path = outputs_dir / "bounded_codeact_result.json"
    output_payload: dict[str, object] = {}
    if output_path.exists():
        output_payload = json.loads(output_path.read_text(encoding="utf-8"))
    fallback_used = any(bool(attempt.get("fallback")) for attempt in generation_attempts)
    generated_by = "deterministic_template"
    if role_path_mode == "api":
        generated_by = "deterministic_policy_fallback_after_llm_api" if fallback_used else "llm_api"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "ok": bool(ast_audit["pass"]) and int(sandbox_payload["returncode"]) == 0 and bool(output_payload),
        "bundle_dir": str(bundle_dir),
        "workspace_root": str(workspace_root),
        "role_path_mode": role_path_mode,
        "generated_by": generated_by,
        "generated_source_path": str(generated_path),
        "generated_source_hash": sha256_digest(source.encode("utf-8")),
        "generation_attempt_count": len(generation_attempts),
        "generation_repair_attempt_count": sum(
            1 for attempt in generation_attempts if bool(attempt.get("repair")) and not bool(attempt.get("fallback"))
        ),
        "generation_fallback_used": fallback_used,
        "generation_attempts_path": str(generation_attempts_path),
        "ast_audit_path": str(ast_audit_path),
        "ast_policy_pass": bool(ast_audit["pass"]),
        "sandbox_result_path": str(sandbox_result_path),
        "sandbox_backend": sandbox_payload["actual_backend"],
        "sandbox_requested_backend": sandbox_payload["requested_backend"],
        "sandbox_fallback_reason": sandbox_payload["fallback_reason"],
        "output_path": str(output_path),
        "output_payload_hash": sha256_digest(output_payload) if output_payload else "",
        "claim_boundary": "bounded CodeAct demo only; not a general-purpose CodeAct benchmark superiority claim",
    }
    (bundle_dir / "summary.json").write_text(stable_json_dumps(summary) + "\n", encoding="utf-8")
    (bundle_dir / "summary.md").write_text(_summary_markdown(summary, ast_audit) + "\n", encoding="utf-8")
    return bundle_dir


def _summary_markdown(summary: dict[str, object], ast_audit: dict[str, object]) -> str:
    return "\n".join(
        [
            "# Bounded LLM-CodeAct Demo",
            "",
            f"- ok: `{summary['ok']}`",
            f"- generated_by: `{summary['generated_by']}`",
            f"- generated_source_hash: `{summary['generated_source_hash']}`",
            f"- generation_attempt_count: `{summary['generation_attempt_count']}`",
            f"- generation_repair_attempt_count: `{summary['generation_repair_attempt_count']}`",
            f"- generation_fallback_used: `{summary['generation_fallback_used']}`",
            f"- ast_policy_pass: `{summary['ast_policy_pass']}`",
            f"- sandbox_backend: `{summary['sandbox_backend']}`",
            f"- output_path: `{summary['output_path']}`",
            f"- claim_boundary: `{summary['claim_boundary']}`",
            f"- ast_violations: `{','.join(ast_audit.get('violations', [])) or 'none'}`",
        ]
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and execute a bounded LLM-CodeAct demo artifact.")
    parser.add_argument("--output-root", type=Path, default=_default_output_root())
    parser.add_argument("--suite-id", default="bounded-llm-codeact-demo")
    parser.add_argument("--role-path-mode", choices=("deterministic", "api"), default="deterministic")
    parser.add_argument("--sandbox-backend", choices=("auto", "bwrap", "resource", "none"), default="resource")
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--max-repair-attempts", type=int, default=2)
    return parser


def main(argv: list[str] | None = None) -> Path:
    args = _build_parser().parse_args(argv)
    bundle_dir = build_bounded_llm_codeact_demo_bundle(
        output_root=args.output_root,
        role_path_mode=args.role_path_mode,
        sandbox_backend=args.sandbox_backend,
        python_executable=args.python_executable,
        suite_id=args.suite_id,
        max_repair_attempts=max(args.max_repair_attempts, 0),
    )
    summary = json.loads((bundle_dir / "summary.json").read_text(encoding="utf-8"))
    ast_audit = json.loads((bundle_dir / "ast_audit.json").read_text(encoding="utf-8"))
    violations = list(ast_audit.get("violations", []))
    print(
        " ".join(
            [
                f"ok={summary.get('ok')}",
                f"generation_fallback_used={summary.get('generation_fallback_used')}",
                f"attempt_count={summary.get('generation_attempt_count')}",
                f"repair_attempt_count={summary.get('generation_repair_attempt_count')}",
                f"violations={','.join(violations) if violations else 'none'}",
            ]
        )
    )
    print(
        stable_json_dumps(
            {
                "bundle_dir": str(bundle_dir),
                "summary_json": str(bundle_dir / "summary.json"),
                "summary_markdown": str(bundle_dir / "summary.md"),
                "generation_attempts_json": str(bundle_dir / "generation_attempts.json"),
                "ast_audit_json": str(bundle_dir / "ast_audit.json"),
                "sandbox_result_json": str(bundle_dir / "sandbox_result.json"),
            }
        )
    )
    return bundle_dir


if __name__ == "__main__":
    main()
