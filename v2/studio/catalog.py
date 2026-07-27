from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = Path(__file__).with_name("data") / "evidence_snapshot_20260726.json"


def load_evidence_snapshot() -> dict[str, Any]:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_source(raw_path: str) -> Path | None:
    value = raw_path.strip()
    if not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(PROJECT_ROOT.resolve())
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def _source_preview(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            rows = []
            for index, row in enumerate(reader):
                rows.append(row)
                if index >= 5:
                    break
        return {"kind": "table", "rows": rows}
    if suffix in {".md", ".txt"}:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return {"kind": "text", "lines": lines[:8]}
    return {"kind": "metadata", "lines": []}


def _source_payload(path: Path) -> dict[str, Any]:
    relative = path.relative_to(PROJECT_ROOT)
    return {
        "name": path.name,
        "path": str(relative),
        "format": path.suffix.lower().lstrip(".") or "file",
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "preview": _source_preview(path),
    }


def _continuous_family(dataset_id: str, label: str, manifest_relative: str, domain: str) -> dict[str, Any]:
    manifest_path = PROJECT_ROOT / manifest_relative
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tasks: list[dict[str, Any]] = []
    sources: dict[str, Path] = {}
    for row in manifest.get("rounds", []):
        spec = row.get("canonical_task_spec", {})
        arguments = spec.get("arguments", {})
        for key in ("csv_path", "document_path", "source_path"):
            source = _resolve_source(str(arguments.get(key, "")))
            if source is not None:
                sources[str(source)] = source
        tasks.append(
            {
                "task_id": row.get("task_id", ""),
                "round": row.get("round"),
                "request_text": row.get("request_text", ""),
                "intent_op": spec.get("intent_op", ""),
                "required_outputs": spec.get("required_outputs", []),
                "depends_on_rounds": row.get("depends_on_rounds", []),
                "reuse_class": row.get("reuse_contract", {}).get("minimum_reuse_class", "none"),
            }
        )
    return {
        "dataset_id": dataset_id,
        "label": label,
        "domain": domain,
        "description": "十轮注册任务链，包含显式依赖、输出合同与质量验证器。",
        "task_count": len(tasks),
        "tasks": tasks,
        "sources": [_source_payload(path) for path in sorted(sources.values())],
        "manifest": manifest_relative,
    }


def _semantic_holdout() -> dict[str, Any]:
    relative = "v2/benchmark/samples/semantic_holdout/manifest.json"
    manifest_path = PROJECT_ROOT / relative
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tasks = []
    sources: dict[str, Path] = {}
    for row in manifest.get("cases", []):
        spec = row.get("canonical_task_spec", {})
        arguments = spec.get("arguments", {})
        for key in ("csv_path", "document_path", "source_path"):
            source = _resolve_source(str(arguments.get(key, "")))
            if source is not None:
                sources[str(source)] = source
        tasks.append(
            {
                "task_id": row.get("task_id", ""),
                "input_shape": row.get("input_shape", ""),
                "request_text": row.get("request_text", ""),
                "intent_op": spec.get("intent_op", ""),
                "required_outputs": spec.get("required_outputs", []),
            }
        )
    return {
        "dataset_id": "semantic-holdout",
        "label": "语义状态留出集",
        "domain": "叙事文档与混合证据",
        "description": "四个独立留出用例，用于验证跨进程数值状态的真实消费。",
        "task_count": len(tasks),
        "tasks": tasks,
        "sources": [_source_payload(path) for path in sorted(sources.values())],
        "manifest": relative,
    }


def _formal_capability() -> dict[str, Any]:
    families = (
        ("financial_report_analysis_v1", "财务指标提取", 8),
        ("multi_period_trend_analysis_v1", "多期趋势分析", 5),
        ("cross_table_join_analysis_v1", "跨表关联分析", 5),
        ("conditional_aggregation_v1", "条件聚合", 4),
        ("anomaly_detection_v1", "异常检测", 3),
    )
    return {
        "dataset_id": "formal-capability",
        "label": "正式能力注册表",
        "domain": "财务与运营分析",
        "description": "25 个注册任务，覆盖五类分析能力与两条经过验证的执行路径。",
        "task_count": 25,
        "tasks": [
            {"family_id": family_id, "label": label, "case_count": count}
            for family_id, label, count in families
        ],
        "sources": [],
        "manifest": "v2/benchmark/task_registry.py",
    }


def load_catalog() -> dict[str, Any]:
    return {
        "datasets": [
            _continuous_family(
                "operating-metrics",
                "运营指标",
                "v2/benchmark/samples/continuous_task_families/formal_operating_metrics/manifest.json",
                "CSV 画像与运营分析",
            ),
            _continuous_family(
                "financial-reports",
                "财务报告",
                "v2/benchmark/samples/continuous_task_families/formal_financial_reports/manifest.json",
                "跨期财务分析",
            ),
            _semantic_holdout(),
            _formal_capability(),
        ]
    }
