from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from statebus.studio.catalog import PROJECT_ROOT


COLLECTION_ID = "contest39-20260927"
BUNDLE_ROOT = Path(__file__).with_name("data") / "observatory" / COLLECTION_ID
TASK_ID = re.compile(r"^F(?:0[1-9]|1[0-2])$")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _manifest() -> dict[str, Any]:
    return _read_json(BUNDLE_ROOT / "manifest.json")


@lru_cache(maxsize=1)
def _evidence() -> dict[str, Any]:
    return _read_json(BUNDLE_ROOT / "evidence.json")


@lru_cache(maxsize=12)
def _task(task_id: str) -> dict[str, Any]:
    return _read_json(BUNDLE_ROOT / "tasks" / f"{task_id}.json")


def _task_summary(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task["task_id"],
        "round": task.get("round"),
        "status": task.get("status", "success"),
        "run_id": task.get("run_id", ""),
        "event_count": len(task.get("events", [])),
        "object_count": len(task.get("objects", [])),
        "memory_consumption_count": sum(1 for event in task.get("events", []) if event.get("kind") == "memory.consume"),
    }


def load_campaign() -> dict[str, Any]:
    manifest = _manifest()
    tasks = [_task_summary(_task(task_id)) for task_id in manifest["task_ids"]]
    evidence = _evidence()
    results = evidence.get("results", {})
    overall = results.get("overall", {})
    return {
        "schema": manifest["schema"],
        "collection": manifest["collection"],
        "collection_date": manifest["collection_date"],
        "generator_version": manifest["generator_version"],
        "run_ids": manifest["run_ids"],
        "families": manifest.get("families", []),
        "task_ids": manifest["task_ids"],
        "tasks": tasks,
        "evidence": {
            "quality_pass_rate": overall.get("quality_pass_rate"),
            "passed_count": overall.get("business_quality_passed_count"),
            "record_count": evidence.get("results", {}).get("record_count"),
            "provider": overall.get("provider", {}),
            "state": overall.get("state", {}),
            "memory": overall.get("memory", {}),
        },
        "source_file_count": len(manifest.get("source_files", [])),
        "constraints": manifest.get("constraints", {}),
    }


def load_task(task_id: str) -> dict[str, Any]:
    if not TASK_ID.fullmatch(task_id):
        raise KeyError(task_id)
    return _task(task_id)


def load_evidence() -> dict[str, Any]:
    return _evidence()


def bundle_path() -> Path:
    """Return the package path for diagnostics without exposing it over HTTP."""
    return BUNDLE_ROOT

