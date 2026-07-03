from __future__ import annotations

import argparse
import ast
import asyncio
import json
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.llm import ChatMessage, LLMConfig, build_llm_client
from v2.runtime.codeact_sandbox import CodeActSandboxConfig, CodeActSandboxRunner
from v2.utils import sha256_digest, stable_json_dumps


SCHEMA_VERSION = "statebus.bounded_llm_codeact_demo.v1"
ALLOWED_IMPORT_ROOTS = {"json", "pathlib", "statistics", "math"}
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
    prompt = textwrap.dedent(
        f"""
        Generate a single Python script for a bounded CodeAct demo.
        Requirements:
        - read inputs/task.json from the current working directory;
        - task.json has this schema/example: {input_example}
        - write outputs/bounded_codeact_result.json;
        - use only json and pathlib imports;
        - compute metric, point_count, delta_abs, growth_pct, summary_text;
        - do not use network, subprocess, open(), eval(), exec(), os, sys, or arbitrary paths.
        Return raw Python code only, no markdown, and do not wrap the code in JSON or a "code" field.
        """
    ).strip()
    client = build_llm_client(LLMConfig.from_runtime().with_mode("api"))
    source = ""
    attempts: list[dict[str, object]] = []
    current_prompt = prompt
    for attempt in range(max_repair_attempts + 1):
        result = await client.complete([ChatMessage(role="user", content=current_prompt)], purpose="executor")
        source = _extract_python_source(result.text)
        audit = audit_generated_source(source)
        attempts.append(_generation_attempt_payload(source=source, audit=audit, attempt=attempt, repair=attempt > 0))
        if audit["pass"]:
            return source, attempts
        current_prompt = _repair_prompt(source=source, audit=audit)
    return source, attempts


def _generation_attempt_payload(
    *,
    source: str,
    audit: dict[str, object],
    attempt: int,
    repair: bool,
) -> dict[str, object]:
    return {
        "attempt": attempt,
        "repair": repair,
        "source_hash": sha256_digest(source.encode("utf-8")),
        "ast_policy_pass": bool(audit["pass"]),
        "violations": list(audit.get("violations", [])),
    }


def _repair_prompt(*, source: str, audit: dict[str, object]) -> str:
    input_example = stable_json_dumps(_demo_input_payload())
    return textwrap.dedent(
        f"""
        Repair this bounded CodeAct Python script so it passes the AST policy.
        Return raw Python code only, no markdown, and do not wrap the code in JSON or a "code" field.

        Policy:
        - read inputs/task.json from the current working directory;
        - task.json has this schema/example: {input_example}
        - write outputs/bounded_codeact_result.json;
        - use only json and pathlib imports;
        - compute metric, point_count, delta_abs, growth_pct, summary_text;
        - do not use network, subprocess, open(), eval(), exec(), os, sys, or arbitrary paths.

        AST violations:
        {stable_json_dumps(audit)}

        Previous source:
        {source}
        """
    ).strip()


def _extract_python_source(text: str) -> str:
    stripped = _strip_code_fence(text).strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("code"), str):
            stripped = _strip_code_fence(payload["code"]).strip()
    return stripped + "\n"


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
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "pass": False,
            "violations": [f"syntax_error:{exc.msg}"],
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
                    violations.append(f"forbidden_import:{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root not in ALLOWED_IMPORT_ROOTS:
                violations.append(f"forbidden_import_from:{node.module}")
        elif isinstance(node, ast.Call):
            call_name = _call_name(node.func)
            if call_name.endswith(".write_text") or call_name == "json.dump":
                has_output_write_call = True
            if call_name in FORBIDDEN_CALLS:
                violations.append(f"forbidden_call:{call_name}")
            root_name = call_name.split(".", 1)[0]
            if root_name in FORBIDDEN_NAME_ROOTS:
                violations.append(f"forbidden_call_root:{call_name}")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAME_ROOTS:
            violations.append(f"forbidden_name:{node.id}")
    if not _has_path_literal(string_literals, "task.json"):
        violations.append("missing_input_path:task.json")
    if not _has_path_literal(string_literals, "bounded_codeact_result.json"):
        violations.append("missing_output_path:bounded_codeact_result.json")
    if not has_output_write_call:
        violations.append("missing_output_write_call")
    return {
        "schema_version": SCHEMA_VERSION,
        "pass": not violations,
        "violations": sorted(set(violations)),
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
    summary = {
        "schema_version": SCHEMA_VERSION,
        "ok": bool(ast_audit["pass"]) and int(sandbox_payload["returncode"]) == 0 and bool(output_payload),
        "bundle_dir": str(bundle_dir),
        "workspace_root": str(workspace_root),
        "role_path_mode": role_path_mode,
        "generated_by": "llm_api" if role_path_mode == "api" else "deterministic_template",
        "generated_source_path": str(generated_path),
        "generated_source_hash": sha256_digest(source.encode("utf-8")),
        "generation_attempt_count": len(generation_attempts),
        "generation_repair_attempt_count": max(len(generation_attempts) - 1, 0),
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
