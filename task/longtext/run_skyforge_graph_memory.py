#!/usr/bin/env python3
"""Run Skyforge long-text tasks through the main LangGraph pipeline.

This runner is for testing the project's Qdrant-backed analysis/summary memory.
It intentionally uses src/graph.py instead of the independent trueKV script in
exp/kv_cache_exp.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage


TASK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TASK_DIR.parents[1]
RESULT_ROOT = TASK_DIR / "result"
TASKS_FILE = TASK_DIR / "skyforge_cache_tasks.json"

for path in (
    PROJECT_ROOT,
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "third_party" / "langgraph" / "libs" / "langgraph",
    PROJECT_ROOT / "third_party" / "langgraph" / "libs" / "checkpoint",
):
    sys.path.insert(0, str(path))

from graph import build_graph  # noqa: E402
from memory import qdrant_add  # noqa: E402
from metrics import metrics  # noqa: E402
from models import get_model  # noqa: E402


ANSWER_RE = re.compile(r"@(\w+)\[([^\]]*)\]")
FILE_BLOCK_RE = re.compile(
    r"^###\s*`?(skyforge_courier_game\.py|GAMEPLAY\.md)`?\s*"
    r"\r?\n```(?:python|py|markdown|md)?\s*\r?\n(.*?)\r?\n```",
    re.MULTILINE | re.DOTALL,
)
GENERIC_FENCE_RE = re.compile(
    r"```(python|py|markdown|md)\s*\r?\n(.*?)\r?\n```",
    re.MULTILINE | re.DOTALL,
)
REQUIRED_GAME_FUNCTIONS = {
    "update_turn",
    "resolve_tile_effect",
    "deliver_orders",
    "calculate_summary",
    "render_map",
    "main",
}
TASK_GROUP = "skyforge_memory_graph"
TASK_TOPIC = "Skyforge Courier game"
DESIGN_DATA_MODELS = {
    "GameConfig": [
        "width",
        "height",
        "max_time",
        "max_stamina",
        "max_shield",
        "base_cargo_slots",
        "weather_script",
        "score_weights",
        "upgrade_costs",
    ],
    "LevelState": [
        "grid",
        "workshop",
        "customers",
        "orders",
        "current_weather",
        "weather_index",
        "blocked_tiles",
        "turn",
        "messages",
    ],
    "PlayerState": [
        "x",
        "y",
        "time_left",
        "stamina",
        "shield",
        "cargo",
        "items",
        "coins",
        "reputation",
        "upgrades",
        "steps_taken",
    ],
    "OrderState": [
        "order_id",
        "customer_id",
        "priority",
        "deadline",
        "reward_coins",
        "reward_rep",
        "fragility",
        "weight",
        "status",
        "damaged",
        "late",
    ],
    "RunSummary": [
        "delivered_count",
        "core_delivered",
        "late_count",
        "damaged_count",
        "score",
        "grade",
        "grade_reason",
        "coin_delta",
        "rep_delta",
        "upgrade_suggestion",
    ],
}
DESIGN_FUNCTIONS = {
    "render_map": "render_map(config: GameConfig, level: LevelState, player: PlayerState) -> None",
    "update_turn": "update_turn(config: GameConfig, level: LevelState, player: PlayerState, command: str) -> bool",
    "resolve_tile_effect": "resolve_tile_effect(config: GameConfig, level: LevelState, player: PlayerState, orders: list[OrderState]) -> None",
    "deliver_orders": "deliver_orders(level: LevelState, player: PlayerState, orders: list[OrderState]) -> list[OrderState]",
    "calculate_summary": "calculate_summary(config: GameConfig, level: LevelState, player: PlayerState, orders: list[OrderState]) -> RunSummary",
    "main": "main() -> None",
}
DESIGN_INVARIANTS = [
    "GameConfig owns static rule/config values, not mutable runtime weather or player stats.",
    "LevelState owns grid, customers, orders, current_weather, weather_index, blocked_tiles, turn, and messages.",
    "PlayerState owns x, y, time_left, stamina, shield, cargo, items, coins, reputation, upgrades, and steps_taken.",
    "OrderState owns order_id, customer_id, priority, deadline, status, damaged, late, rewards, fragility, and weight.",
    "All attribute reads in functions must target the class that declares that field.",
    "The first q input at the main prompt must exit cleanly without raising an exception.",
]


def clip_text(text: object, max_chars: int) -> str:
    """Keep fallback prompts under local model context limits."""
    value = str(text or "").strip()
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    head_chars = max_chars // 2
    tail_chars = max_chars - head_chars
    return (
        value[:head_chars].rstrip()
        + "\n[... clipped by runner ...]\n"
        + value[-tail_chars:].lstrip()
    )


def load_dataset() -> dict:
    return json.loads(TASKS_FILE.read_text(encoding="utf-8"))


def load_source_context(dataset: dict) -> str:
    return (PROJECT_ROOT / dataset["source_context_file"]).read_text(encoding="utf-8")


def compact_source_context(source_context: str, max_chars: int) -> str:
    if max_chars <= 0 or len(source_context) <= max_chars:
        return source_context
    head = source_context[: max_chars // 2].rstrip()
    tail = source_context[-max_chars // 2 :].lstrip()
    return f"{head}\n\n[... source context truncated by runner ...]\n\n{tail}"


def build_query(task: dict, source_context: str, *, source_policy: str) -> str:
    source_block = ""
    if source_policy == "full":
        source_block = f"\n\nSkyforge source rules:\n{source_context}"
    elif source_policy == "first_round":
        if task["round"] == 1:
            source_block = f"\n\nSkyforge source rules:\n{source_context}"
        else:
            source_block = (
                "\n\nSkyforge source rules: rely on prior long-term memory and "
                "the task constraints below; do not restart the design."
            )

    dependencies = task.get("memory", {}).get("reuses_from_rounds", [])
    concepts = ", ".join(task.get("concepts", []) or [])
    return "\n".join([
        f"Round: {task['round']}",
        f"Question: {task['question']}",
        f"Constraints: {task['constraints']}",
        f"Expected answer format: {task['answer_format']}",
        f"Depends on prior rounds: {dependencies or 'none'}",
        f"Concepts: {concepts or 'N/A'}",
        source_block,
        "\nReturn a useful result for this round and keep the expected answer "
        "format available for the executor.",
    ])


def extract_answers(text: str) -> dict[str, str]:
    return dict(ANSWER_RE.findall(text or ""))


def build_design_state(task: dict, round_record: dict) -> dict:
    """Build a structured design contract memory for one Skyforge round."""
    extracted = dict(round_record.get("extracted_answers") or {})
    new_systems = [
        item.strip()
        for item in str(extracted.get("new_systems", "")).split(",")
        if item.strip()
    ]
    if not new_systems:
        new_systems = [str(item) for item in task.get("concepts", []) or []]

    return {
        "round": task.get("round"),
        "task_id": task.get("id"),
        "question": task.get("question", ""),
        "constraints": task.get("constraints", ""),
        "answer_format": task.get("answer_format", ""),
        "depends_on": extracted.get("depends_on")
        or task.get("memory", {}).get("reuses_from_rounds", []),
        "feature_scope": extracted.get("feature_scope", ""),
        "new_systems": new_systems,
        "deliverable": extracted.get("deliverable", ""),
        "data_models": DESIGN_DATA_MODELS,
        "functions": DESIGN_FUNCTIONS,
        "invariants": DESIGN_INVARIANTS,
        "round_outputs": {
            "plan": clip_text(round_record.get("plan", ""), 700),
            "analysis_digest": clip_text(round_record.get("analysis_digest", ""), 900),
            "summary": clip_text(round_record.get("summary", ""), 900),
            "final_answer": clip_text(round_record.get("final_answer", ""), 300),
        },
    }


def store_design_state(design_state: dict, *, mode: str) -> None:
    """Persist a runner-owned design contract memory to Qdrant."""
    round_id = design_state.get("round")
    content = json.dumps(design_state, ensure_ascii=False, sort_keys=True)
    keywords = [
        "design_state",
        "skyforge",
        "runner",
        mode,
        f"round_{round_id}",
        *design_state.get("new_systems", []),
        *DESIGN_DATA_MODELS.keys(),
        *DESIGN_FUNCTIONS.keys(),
    ]
    qdrant_add(
        source_task_id=f"design_state_{TASK_GROUP}_{mode}_round_{round_id}",
        content=content,
        memory_type="design_state",
        source_agent="runner",
        task_topic=f"Skyforge Courier design state round {round_id}",
        keywords=keywords,
    )


def format_design_contract(design_states: list[dict]) -> str:
    """Render design states as a compact final-code source-of-truth."""
    if not design_states:
        return "No runner design_state contract is available."

    lines = [
        "Runner design_state contract. Treat this as the source of truth for code generation.",
        "Do not invent fields outside this contract. Keep attribute ownership consistent.",
        "",
        "Canonical data model fields:",
    ]
    for model_name, fields in DESIGN_DATA_MODELS.items():
        lines.append(f"- {model_name}: {', '.join(fields)}")

    lines.extend(["", "Canonical function signatures:"])
    for function_name, signature in DESIGN_FUNCTIONS.items():
        lines.append(f"- {function_name}: {signature}")

    lines.extend(["", "Invariants:"])
    for invariant in DESIGN_INVARIANTS:
        lines.append(f"- {invariant}")

    lines.extend(["", "Round-by-round design states:"])
    for state in sorted(design_states, key=lambda item: item.get("round") or 0):
        outputs = state.get("round_outputs", {})
        systems = ", ".join(state.get("new_systems", []) or [])
        lines.extend([
            f"Round {state.get('round')} systems: {systems or 'N/A'}",
            f"Summary: {clip_text(outputs.get('summary', ''), 220)}",
            "",
        ])
    return "\n".join(lines)


def extract_artifact_blocks(text: str) -> dict[str, str]:
    """Extract final deliverable files from markdown fenced blocks."""
    artifacts: dict[str, str] = {}
    for filename, content in FILE_BLOCK_RE.findall(text or ""):
        artifacts[filename] = content.strip() + "\n"

    if {"skyforge_courier_game.py", "GAMEPLAY.md"} <= set(artifacts):
        return artifacts

    # Some models return the two fences in order but omit filename headings.
    for language, content in GENERIC_FENCE_RE.findall(text or ""):
        language = language.lower()
        if language in {"python", "py"} and "skyforge_courier_game.py" not in artifacts:
            artifacts["skyforge_courier_game.py"] = content.strip() + "\n"
        elif language in {"markdown", "md"} and "GAMEPLAY.md" not in artifacts:
            artifacts["GAMEPLAY.md"] = content.strip() + "\n"
    return artifacts


def extract_markdown_artifact(text: str) -> str:
    """Extract GAMEPLAY.md while tolerating nested markdown fences."""
    raw = str(text or "")
    match = re.search(
        r"^###\s*`?GAMEPLAY\.md`?\s*\r?\n```(?:markdown|md)?\s*\r?\n",
        raw,
        flags=re.MULTILINE,
    )
    if not match:
        return ""
    end = raw.rfind("```")
    if end <= match.end():
        return ""
    return raw[match.end():end].strip() + "\n"


def collect_final_context(rounds: list[dict], source_context: str) -> str:
    """Build very compact context for final artifact generation.

    The detailed round-by-round contract is supplied separately via
    design_contract, so this should stay small to avoid model context overflow.
    """
    final_round = next((item for item in rounds if item.get("round") == 10), {})
    parts = [
        "Compact Skyforge source rules:",
        clip_text(source_context, 1200),
        "\nFinal round intent:",
        clip_text(final_round.get("question", ""), 320),
        clip_text(final_round.get("summary", ""), 320),
    ]
    return "\n\n".join(parts)


def extract_single_artifact(text: str, filename: str) -> str:
    """Extract one target artifact from a model response."""
    if filename == "GAMEPLAY.md":
        markdown = extract_markdown_artifact(text)
        if markdown:
            return markdown

    artifacts = extract_artifact_blocks(text)
    if artifacts.get(filename):
        return artifacts[filename]

    raw = str(text or "").strip()
    if not raw:
        return ""
    if "```" not in raw:
        if filename == "skyforge_courier_game.py" and "def main" in raw:
            return raw + "\n"
        if filename == "GAMEPLAY.md" and "python3 skyforge_courier_game.py" in raw:
            return raw + "\n"
    return ""


def generate_single_artifact_response(
    *,
    rounds: list[dict],
    source_context: str,
    design_contract: str,
    final_task: dict,
    filename: str,
    game_code: str = "",
) -> str:
    """Ask the configured model to produce one final artifact file."""
    model = get_model(temperature=0.2)
    context = collect_final_context(rounds, source_context)
    final_task_prompt = {
        "question": final_task.get("question", ""),
        "constraints": final_task.get("constraints", ""),
        "answer_format": final_task.get("answer_format", ""),
    }
    if filename == "skyforge_courier_game.py":
        language = "python"
        requirements = """Generate only skyforge_courier_game.py.
The file must be standard-library only, playable in a terminal with input()
controls for w/a/s/d/q, and include update_turn, resolve_tile_effect,
deliver_orders, calculate_summary, render_map, main. It must contain
if __name__ == '__main__': main(). Keep the implementation compact enough to
finish in one response.
Use the design state contract as the source of truth for state ownership.
Before returning the code, check every attribute access against the declared
GameConfig, LevelState, PlayerState, OrderState, and RunSummary fields.
Do not use config.current_weather or player.current_weather; weather belongs
to LevelState.current_weather. Do not use player.shield unless PlayerState
declares shield, and keep stamina/shield on PlayerState."""
    else:
        language = "markdown"
        requirements = """Generate only GAMEPLAY.md.
The manual must include the run command python3 skyforge_courier_game.py,
controls, map symbols, orders/cargo, supplies, weather, upgrades, scoring,
win/loss rules, and one sample route tip. Do not include nested triple-backtick
fences inside the markdown."""
        if game_code:
            requirements += (
                "\n\nUse this generated game source as the implementation reference:\n"
                f"{clip_text(game_code, 3500)}"
            )

    messages = [
        SystemMessage(content=(
            "You generate one final deliverable file for a terminal game task. "
            "Return exactly one fenced block and no prose outside it. "
            "Do not return JSON."
        )),
        HumanMessage(content=f"""Final task:
{json.dumps(final_task_prompt, ensure_ascii=False, indent=2)}

Context from the previous rounds:
{context}

Design state contract:
{design_contract}

Return exactly this shape:
### {filename}
```{language}
...
```

{requirements}"""),
    ]
    response = model.invoke(messages)
    return str(getattr(response, "content", response))


def repair_single_artifact_response(
    *,
    raw_response: str,
    final_task: dict,
    filename: str,
) -> str:
    """Ask the model to reformat a non-parseable single-file response."""
    model = get_model(temperature=0.0)
    final_task_prompt = {
        "question": final_task.get("question", ""),
        "constraints": final_task.get("constraints", ""),
    }
    language = "python" if filename == "skyforge_courier_game.py" else "markdown"
    messages = [
        SystemMessage(content=(
            "Reformat or regenerate one failed terminal-game deliverable file. "
            "Return exactly one fenced block and no prose outside it. "
            "Do not return JSON."
        )),
        HumanMessage(content=f"""The previous response did not parse into {filename}.

Final task:
{json.dumps(final_task_prompt, ensure_ascii=False, indent=2)}

Previous response:
{clip_text(raw_response, 5000)}

Return exactly:
### {filename}
```{language}
...
```

If this is the Python file, it must compile and include update_turn,
resolve_tile_effect, deliver_orders, calculate_summary, render_map, main,
input(), and if __name__ == '__main__': main().
If this is the Markdown file, do not include nested triple-backtick fences."""),
    ]
    response = model.invoke(messages)
    return str(getattr(response, "content", response))


def generate_final_artifacts(
    *,
    rounds: list[dict],
    source_context: str,
    design_contract: str,
    final_task: dict,
) -> tuple[dict[str, str], str]:
    artifacts: dict[str, str] = {}
    debug_parts: list[str] = []
    for filename in ("skyforge_courier_game.py", "GAMEPLAY.md"):
        print(
            f"[skyforge:artifact] generating {filename}",
            file=sys.stderr,
            flush=True,
        )
        raw_response = generate_single_artifact_response(
            rounds=rounds,
            source_context=source_context,
            design_contract=design_contract,
            final_task=final_task,
            filename=filename,
            game_code=artifacts.get("skyforge_courier_game.py", ""),
        )
        debug_parts.append(f"--- {filename} response ---\n\n{raw_response}")
        content = extract_single_artifact(raw_response, filename)
        if not content:
            repair_response = repair_single_artifact_response(
                raw_response=raw_response,
                final_task=final_task,
                filename=filename,
            )
            debug_parts.append(f"--- {filename} repair response ---\n\n{repair_response}")
            content = extract_single_artifact(repair_response, filename)
        if content:
            artifacts[filename] = content
        print(
            f"[skyforge:artifact] {filename} extracted={bool(content)} "
            f"chars={len(content)}",
            file=sys.stderr,
            flush=True,
        )

    raw_debug = "\n\n".join(debug_parts)
    return artifacts, raw_debug



def validate_game_file(path: Path) -> dict:
    """Compile and lightly validate the generated game source."""
    result = {
        "py_compile_ok": False,
        "required_functions_present": False,
        "has_main_guard": False,
        "has_input_controls": False,
        "smoke_run_ok": False,
        "smoke_stdout_tail": "",
        "smoke_stderr_tail": "",
        "missing_functions": sorted(REQUIRED_GAME_FUNCTIONS),
        "error": "",
    }
    code = path.read_text(encoding="utf-8")
    try:
        compile(code, str(path), "exec")
        result["py_compile_ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
        return result

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        result["error"] = str(exc)
        return result

    functions = {
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = sorted(REQUIRED_GAME_FUNCTIONS - functions)
    result["missing_functions"] = missing
    result["required_functions_present"] = not missing
    result["has_main_guard"] = "__name__" in code and "main()" in code
    result["has_input_controls"] = "input(" in code
    try:
        completed = subprocess.run(
            [sys.executable, "-B", str(path)],
            input="q\n",
            text=True,
            capture_output=True,
            timeout=8,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        result["smoke_run_ok"] = completed.returncode == 0
        result["smoke_stdout_tail"] = completed.stdout[-1200:]
        result["smoke_stderr_tail"] = completed.stderr[-1200:]
        if completed.returncode != 0 and not result["error"]:
            result["error"] = f"smoke run failed with exit code {completed.returncode}"
    except Exception as exc:
        result["error"] = f"smoke run failed: {exc}"
    return result


def validate_manual_content(content: str) -> dict:
    """Validate that GAMEPLAY.md is not a truncated shell of the manual."""
    text = str(content or "")
    checks = {
        "min_length": len(text) >= 400,
        "has_run_command": "python3 skyforge_courier_game.py" in text,
        "has_controls": "control" in text.lower() or "操作" in text,
        "has_map_symbols": "map" in text.lower() or "符号" in text,
        "has_scoring": "scor" in text.lower() or "评分" in text,
        "has_win_loss": (
            ("win" in text.lower() and "loss" in text.lower())
            or "胜负" in text
        ),
    }
    return {
        **checks,
        "ok": all(checks.values()),
        "length": len(text),
    }


def validate_manual_file(path: Path) -> dict:
    return validate_manual_content(path.read_text(encoding="utf-8", errors="replace"))


def package_final_artifacts(
    *,
    mode_result: dict,
    dataset: dict,
    source_context: str,
    output_dir: Path,
    mode: str,
    multi_mode: bool,
) -> dict:
    """Save round-10 game/manual artifacts and return packaging metadata."""
    final_task = next(
        (task for task in dataset.get("tasks", []) if task.get("round") == 10),
        None,
    )
    if not final_task:
        return {"status": "skipped", "reason": "no round-10 final task found"}

    rounds = mode_result.get("rounds", [])
    design_contract = format_design_contract(mode_result.get("design_states", []))
    final_round = next((item for item in rounds if item.get("round") == 10), None)
    if not final_round:
        return {"status": "skipped", "reason": "round 10 was not run"}

    artifacts: dict[str, str] = {}
    for field in ("final_answer", "summary", "analysis_digest", "execution_summary"):
        artifacts.update(extract_artifact_blocks(str(final_round.get(field, ""))))
    if artifacts.get("GAMEPLAY.md") and not validate_manual_content(artifacts["GAMEPLAY.md"])["ok"]:
        artifacts.pop("GAMEPLAY.md", None)

    generated_by_fallback = False
    fallback_debug_path = None
    if not {"skyforge_courier_game.py", "GAMEPLAY.md"} <= set(artifacts):
        try:
            generated_artifacts, raw_generation = generate_final_artifacts(
                rounds=rounds,
                source_context=source_context,
                design_contract=design_contract,
                final_task=final_task,
            )
            fallback_debug_path = output_dir / f"final_artifact_fallback_{mode}.md"
            fallback_debug_path.write_text(raw_generation, encoding="utf-8")
            artifacts.update(generated_artifacts)
            generated_by_fallback = True
        except Exception as exc:
            return {
                "status": "failed",
                "reason": f"could not extract or generate final artifacts: {exc}",
                "generated_by_fallback": generated_by_fallback,
                "fallback_debug_path": str(fallback_debug_path) if fallback_debug_path else "",
            }

    missing_files = sorted(
        {"skyforge_courier_game.py", "GAMEPLAY.md"} - set(artifacts)
    )
    if missing_files:
        return {
            "status": "failed",
            "reason": "missing final artifact blocks",
            "missing_files": missing_files,
            "generated_by_fallback": generated_by_fallback,
            "fallback_debug_path": str(fallback_debug_path) if fallback_debug_path else "",
        }

    release_dir_name = (
        f"{mode}_skyforge_courier_release"
        if multi_mode else
        "skyforge_courier_release"
    )
    release_dir = output_dir / release_dir_name
    release_dir.mkdir(parents=True, exist_ok=True)

    game_path = release_dir / "skyforge_courier_game.py"
    manual_path = release_dir / "GAMEPLAY.md"
    game_path.write_text(artifacts["skyforge_courier_game.py"], encoding="utf-8")
    manual_path.write_text(artifacts["GAMEPLAY.md"], encoding="utf-8")

    validation = validate_game_file(game_path)
    manual_validation = validate_manual_file(manual_path)
    validation_ok = (
        validation["py_compile_ok"]
        and validation["required_functions_present"]
        and validation["has_main_guard"]
        and validation["has_input_controls"]
        and validation["smoke_run_ok"]
        and manual_validation["ok"]
    )
    return {
        "status": "ok" if validation_ok else "failed",
        "release_dir": str(release_dir),
        "files": [str(game_path), str(manual_path)],
        "generated_by_fallback": generated_by_fallback,
        "fallback_debug_path": str(fallback_debug_path) if fallback_debug_path else "",
        "validation": validation,
        "manual_validation": manual_validation,
    }


def summarize_store_ops() -> dict:
    by_op: dict[str, int] = {}
    by_namespace: dict[str, int] = {}
    for item in metrics.store_ops:
        by_op[item.get("op", "")] = by_op.get(item.get("op", ""), 0) + 1
        namespace = "/".join(str(part) for part in item.get("namespace", ()))
        by_namespace[namespace] = by_namespace.get(namespace, 0) + 1
    return {
        "by_op": by_op,
        "by_namespace": by_namespace,
        "qdrant_ops": [
            item for item in metrics.store_ops
            if item.get("namespace", ("",))[0] == "qdrant"
        ],
    }


def sanitize_for_json(value):
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(value, list):
        return [sanitize_for_json(item) for item in value]
    if isinstance(value, dict):
        return {
            sanitize_for_json(key): sanitize_for_json(item)
            for key, item in value.items()
        }
    return value


def run_mode(
    *,
    mode: str,
    tasks: list[dict],
    source_context: str,
    source_policy: str,
) -> dict:
    metrics.reset()
    rounds = []
    design_states = []
    started = time.perf_counter()

    for task in tasks:
        graph, _store = build_graph(mode=mode)
        round_id = task["round"]
        print(
            f"[skyforge:{mode}] round {round_id}/{len(tasks)} start",
            file=sys.stderr,
            flush=True,
        )
        query = build_query(task, source_context, source_policy=source_policy)
        task_group = TASK_GROUP
        t0 = time.perf_counter()
        try:
            result = graph.invoke({
                "query": query,
                "task_group": task_group,
                "task_topic": TASK_TOPIC,
                "mode": mode,
            })
            error = ""
        except Exception as exc:
            result = {}
            error = str(exc)
            print(
                f"[skyforge:{mode}] round {round_id} error: {error}",
                file=sys.stderr,
                flush=True,
            )
        duration = time.perf_counter() - t0
        final_answer = result.get("final_answer", "")
        round_record = {
            "round": round_id,
            "task_id": task["id"],
            "question": task["question"],
            "expected_format": task["answer_format"],
            "duration_s": round(duration, 2),
            "error": error,
            "plan": result.get("plan", ""),
            "analysis_digest": result.get("analysis_digest", ""),
            "summary": result.get("summary", ""),
            "final_answer": final_answer,
            "extracted_answers": result.get("extracted_answers", {}) or extract_answers(final_answer),
            "key_findings": result.get("key_findings", []),
            "execution_summary": result.get("execution_summary", ""),
        }
        design_state = build_design_state(task, round_record)
        round_record["design_state"] = design_state
        design_states.append(design_state)
        store_design_state(design_state, mode=mode)
        rounds.append(round_record)
        metrics.record_timing(f"task_round_{round_id}", duration)
        print(
            f"[skyforge:{mode}] round {round_id} done {duration:.1f}s "
            f"error={bool(error)}",
            file=sys.stderr,
            flush=True,
        )

    total_duration = time.perf_counter() - started
    summary = metrics.summary_dict()
    return {
        "mode": mode,
        "source_policy": source_policy,
        "total_duration_s": round(total_duration, 2),
        "rounds": rounds,
        "design_states": design_states,
        "metrics_summary": summary,
        "store_summary": summarize_store_ops(),
        "metrics_report": metrics.report(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Skyforge long-text tasks through the main graph."
    )
    parser.add_argument(
        "--mode",
        choices=["text", "structured", "both"],
        default="both",
        help="Run one mode or both text and structured.",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=10,
        help="Number of sequential rounds to run.",
    )
    parser.add_argument(
        "--source-policy",
        choices=["full", "first_round", "none"],
        default="full",
        help=(
            "How to include skyforge_rules.md in each query. Use first_round "
            "to stress long-term memory after round 1."
        ),
    )
    parser.add_argument(
        "--max-source-chars",
        type=int,
        default=0,
        help="Optionally truncate source rules before building queries.",
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    dataset = load_dataset()
    source_context = load_source_context(dataset)
    source_context = compact_source_context(source_context, args.max_source_chars)
    tasks = dataset["tasks"][: args.rounds]
    modes = ["text", "structured"] if args.mode == "both" else [args.mode]

    output_dir = args.output_dir or (
        RESULT_ROOT / f"skyforge_graph_{time.strftime('%Y%m%d_%H%M%S')}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    for mode in modes:
        mode_result = run_mode(
            mode=mode,
            tasks=tasks,
            source_context=source_context,
            source_policy=args.source_policy,
        )
        mode_result["final_artifacts"] = package_final_artifacts(
            mode_result=mode_result,
            dataset=dataset,
            source_context=source_context,
            output_dir=output_dir,
            mode=mode,
            multi_mode=len(modes) > 1,
        )
        results[mode] = mode_result
        (output_dir / f"{mode}.json").write_text(
            json.dumps(sanitize_for_json(mode_result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    summary = {
        "experiment": {
            "name": "skyforge_graph_memory",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "task_file": str(TASKS_FILE.relative_to(PROJECT_ROOT)),
            "source_file": dataset["source_context_file"],
            "rounds": len(tasks),
            "modes": modes,
            "source_policy": args.source_policy,
            "chat_backend": os.getenv("CHAT_BACKEND"),
            "chat_base_url": os.getenv("CHAT_BASE_URL"),
            "chat_model": os.getenv("CHAT_MODEL"),
            "long_term_memory_enabled": os.getenv("LONG_TERM_MEMORY_ENABLED"),
            "long_term_memory_search_mode": os.getenv("LONG_TERM_MEMORY_SEARCH_MODE"),
            "enable_context_packets": os.getenv("ENABLE_CONTEXT_PACKETS"),
            "enable_embedding_transfer": os.getenv("ENABLE_EMBEDDING_TRANSFER"),
        },
        "results": {
            mode: {
                "total_duration_s": item["total_duration_s"],
                "design_state_count": len(item.get("design_states", [])),
                "design_contract_chars": len(format_design_contract(item.get("design_states", []))),
                "metrics_summary": item["metrics_summary"],
                "store_summary": {
                    "by_op": item["store_summary"]["by_op"],
                    "by_namespace": item["store_summary"]["by_namespace"],
                    "qdrant_op_count": len(item["store_summary"]["qdrant_ops"]),
                },
                "round_errors": [
                    r["error"] for r in item["rounds"] if r.get("error")
                ],
                "final_artifacts": item.get("final_artifacts", {}),
            }
            for mode, item in results.items()
        },
    }
    (output_dir / "summary.json").write_text(
        json.dumps(sanitize_for_json(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"output_dir": str(output_dir)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
