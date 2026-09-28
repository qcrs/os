#!/usr/bin/env python3
"""Collect bounded Contest Memory/State raw evidence into four compact reports."""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from statebus.benchmark.contest_mechanisms import MEMORY_TASKS, STATE_TASKS, VARIANTS, experiment_plan

CSV_COLUMNS = (
    "experiment", "task_id", "variant", "status", "quality", "e2e_ms",
    "provider_requests", "provider_tokens", "repair", "reason", "source_path",
)


def _load(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _memory_rows(raw_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for family, task_ids in MEMORY_TASKS.items():
        for variant in VARIANTS:
            chain_root = raw_root / "memory" / family / variant
            by_task = {str(item.get("task_id")): item for item in (_load(chain_root / "ledger.json", []) or [])}
            for task_id in task_ids:
                source = chain_root / "slots" / task_id
                item = dict(by_task.get(task_id, {}))
                metrics = item.get("metrics", {}) if isinstance(item.get("metrics"), dict) else {}
                status = str(item.get("status", "not_started"))
                reason = item.get("reason") or item.get("error") or item.get("blocked_reason")
                if reason is None and item.get("failure_codes"):
                    reason = ";".join(str(value) for value in item["failure_codes"])
                row = {
                    "experiment": "memory", "family": family, "task_id": task_id, "variant": variant,
                    "status": status, "quality": item.get("quality"),
                    "e2e_ms": _number(item.get("e2e_ms")),
                    "provider_requests": _number(metrics.get("provider_request_count")),
                    "provider_prompt_tokens": _number(metrics.get("provider_prompt_tokens")),
                    "provider_completion_tokens": _number(metrics.get("provider_completion_tokens")),
                    "provider_tokens": _number(metrics.get("provider_total_tokens")),
                    "repair": _number(item.get("repair", metrics.get("executor_repair_count"))),
                    "reason": reason, "source_path": str(source),
                }
                if item.get("memory") is not None:
                    row["memory"] = item["memory"]
                rows.append(row)
    return rows


def _host_source_path(raw_root: Path, value: Any, *, fallback: Path) -> str:
    if not value:
        return str(fallback.resolve())
    text = str(value)
    container_prefix = "/workspace/statebus/os/"
    if text.startswith(container_prefix):
        return str((PROJECT_ROOT / text[len(container_prefix):]).resolve())
    path = Path(text)
    return str(path.resolve()) if path.is_absolute() else str((raw_root / path).resolve())


def _state_rows(raw_root: Path) -> list[dict[str, Any]]:
    summary = _load(raw_root / "state" / "ablation" / "summary.json", {}) or {}
    observed = {(str(item.get("task_id")), str(item.get("variant"))): item
                for item in summary.get("rows", []) if isinstance(item, dict)}
    rows: list[dict[str, Any]] = []
    for task_id in STATE_TASKS:
        for variant in VARIANTS:
            item = dict(observed.get((task_id, variant), {}))
            fallback = raw_root / "state" / "ablation" / "cases" / task_id / variant / "summary.json"
            source_path = _host_source_path(
                raw_root, item.get("summary_path"), fallback=fallback,
            )
            case_summary = _load(Path(source_path), {}) or {}
            failure = item.get("failure") if isinstance(item.get("failure"), dict) else {}
            classification = (
                case_summary.get("failure_classification", {})
                if isinstance(case_summary.get("failure_classification"), dict) else {}
            )
            category = str(classification.get("category", failure.get("category", "")))
            error_code = classification.get("error_code") or failure.get("error_code")
            quality = item.get("quality_pass") if "quality_pass" in item else None
            started = bool(item or case_summary)
            if not started:
                status = "not_started"
            elif item.get("ok"):
                status = "success"
            elif quality is False and (category == "model_quality" or error_code == "output_validation_failed"):
                status = "quality_fail"
            elif item.get("terminal"):
                status = "quality_fail" if quality is False else "mechanism_fail"
            else:
                status = "runtime_fail"
            reason = None if status == "success" else (
                error_code
                or classification.get("error")
                or failure.get("error")
                or item.get("activation_reason")
                or None
            )
            state = None
            if item:
                state = {
                    "publish_count": _number(item.get("semantic_publish_count")),
                    "transfer_count": _number(item.get("semantic_transfer_count")),
                    "consume_count": _number(item.get("semantic_consume_count")),
                    "payload_bytes": _number(item.get("payload_bytes")),
                    "read_bytes": _number(item.get("read_bytes")),
                    "cross_process_consumption_observed": item.get("cross_process_consumption_observed"),
                    "release_observed": item.get("release_observed"),
                    "selected_ids": item.get("selected_ids"),
                    "selected_evidence_chars": _number(item.get("selected_evidence_chars")),
                    "selected_evidence_tokens": _number(item.get("selected_evidence_tokens")),
                    "behavioral_effect": item.get("behavioral_effect"),
                }
            row = {
                "experiment": "state", "task_id": task_id, "variant": variant,
                "status": status, "quality": quality,
                "e2e_ms": _number(item.get("e2e_ms")),
                "provider_requests": _number(item.get("provider_call_count")),
                "provider_prompt_tokens": _number(item.get("provider_prompt_tokens")),
                "provider_completion_tokens": _number(item.get("provider_completion_tokens")),
                "provider_tokens": _number(item.get("provider_total_tokens")),
                "repair": int(bool(item.get("repair"))) if item and item.get("repair") is not None else None,
                "reason": reason, "source_path": source_path,
            }
            if state is not None:
                row["state"] = state
            rows.append(row)
    return rows


def _sum_known(rows: list[dict[str, Any]], field: str) -> int | float | None:
    values = [row.get(field) for row in rows]
    return sum(values) if values and all(_number(value) is not None for value in values) else None


def _sum_started_known(rows: list[dict[str, Any]], field: str) -> int | float | None:
    started = [row for row in rows if row.get("status") != "not_started"]
    return _sum_known(started, field) if started else None


def _saving(off: Any, on: Any, *, comparable: bool) -> float | None:
    if not comparable or _number(off) is None or _number(on) is None or off == 0:
        return None
    return (off - on) / off


def _paired(rows: list[dict[str, Any]], experiment: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        if row["experiment"] == experiment:
            grouped[row["task_id"]][row["variant"]] = row
    pairs = []
    for task_id, variants in grouped.items():
        off, on = variants.get("off", {}), variants.get("on", {})
        comparable = bool(off.get("status") == on.get("status") == "success" and off.get("quality") is True and on.get("quality") is True)
        pairs.append({
            "task_id": task_id, "comparable": comparable, "off": off, "on": on,
            "e2e_saving_ratio": _saving(off.get("e2e_ms"), on.get("e2e_ms"), comparable=comparable),
            "provider_token_saving_ratio": _saving(off.get("provider_tokens"), on.get("provider_tokens"), comparable=comparable),
            "provider_request_saving_ratio": _saving(off.get("provider_requests"), on.get("provider_requests"), comparable=comparable),
        })
    return pairs


def _run_commands(batch_manifest: dict[str, Any], *, raw_root: Path) -> dict[str, str]:
    configuration = batch_manifest.get("configuration", {})
    if not isinstance(configuration, dict):
        configuration = {}
    mechanism = str(batch_manifest.get("mechanism", "all"))
    raw_root_text = str(batch_manifest.get("host_output") or raw_root)
    if raw_root_text.startswith("/workspace/statebus/os/"):
        raw_root_text = str((PROJECT_ROOT / raw_root_text.removeprefix("/workspace/statebus/os/")).resolve())
    base = [
        "bash scripts/run_contest_mechanisms.sh",
        f"  --mechanism {mechanism}",
        f"  --mode {batch_manifest.get('mode', configuration.get('mode', 'live'))}",
        f"  --output {raw_root_text}",
    ]
    if configuration.get("family") not in (None, "all"):
        base.append(f"  --family {configuration['family']}")
    for task_id in configuration.get("task_id", []) or []:
        base.append(f"  --task-id {task_id}")
    for case_id in configuration.get("case_id", []) or []:
        base.append(f"  --case-id {case_id}")
    return {
        "runner": " \\\n".join(base),
        "collector": f"bash scripts/run_contest_mechanisms.sh --collect-only --output {raw_root_text} --collect-output <new-report-root>",
    }


def _environment(batch_manifest: dict[str, Any]) -> dict[str, Any]:
    configured = batch_manifest.get("environment")
    if isinstance(configured, dict):
        return configured
    configuration = batch_manifest.get("configuration", {})
    return {
        "host_model": configuration.get("model", "qwen3-32b") if isinstance(configuration, dict) else "qwen3-32b",
        "vllm_physical_gpu": 2,
        "api_base_url": configuration.get("base_url", "http://127.0.0.1:53334/v1") if isinstance(configuration, dict) else "http://127.0.0.1:53334/v1",
        "context_tokens": configuration.get("max_context", 8192) if isinstance(configuration, dict) else 8192,
        "container": "statebus-runtime",
        "container_source": "/workspace/statebus/os",
        "runtime_python": "/home/qcrs/statebus/conda-envs/statebus_host/bin/python",
        "embedding_model": str(configuration.get("embedding_model", "/statebus/models/Qwen3-Embedding-0.6B")) if isinstance(configuration, dict) else "/statebus/models/Qwen3-Embedding-0.6B",
        "embedding_physical_gpu": 1,
        "embedding_container_device": configuration.get("embedding_device", "cuda:0") if isinstance(configuration, dict) else "cuda:0",
        "os": "openEuler 24.03 LTS-SP3",
    }


def build_summary(rows: list[dict[str, Any]], *, raw_root: Path) -> dict[str, Any]:
    planned = len(rows)
    started = sum(row["status"] != "not_started" for row in rows)
    passed = sum(row["status"] == "success" for row in rows)
    aggregates = {}
    for experiment in ("memory", "state"):
        exp_rows = [row for row in rows if row["experiment"] == experiment]
        by_variant = {}
        for variant in VARIANTS:
            variant_rows = [row for row in exp_rows if row["variant"] == variant]
            by_variant[variant] = {
                "planned": len(variant_rows),
                "started": sum(row["status"] != "not_started" for row in variant_rows),
                "passed": sum(row["status"] == "success" for row in variant_rows),
                "provider_requests": _sum_started_known(variant_rows, "provider_requests"),
                "provider_tokens": _sum_started_known(variant_rows, "provider_tokens"),
                "task_e2e_ms_sum": _sum_started_known(variant_rows, "e2e_ms"),
                "repairs": _sum_started_known(variant_rows, "repair"),
            }
        aggregates[experiment] = {"planned": len(exp_rows), "by_variant": by_variant, "pairs": _paired(rows, experiment)}
    memory_on = [row for row in rows if row["experiment"] == "memory" and row["variant"] == "on"]
    query_count = sum(int(row.get("memory", {}).get("query_count", 0) or 0) for row in memory_on)
    hit_count = sum(int(row.get("memory", {}).get("candidate_hit_count", 0) or 0) for row in memory_on)
    aggregates["memory"]["observed_mechanism"] = {
        "query_count": query_count,
        "candidate_hit_count": hit_count,
        "candidate_hit_rate": hit_count / query_count if query_count else None,
        "actual_consumed_tasks": sum(bool(row.get("memory", {}).get("actual_consumed")) for row in memory_on),
        "validated_replay_tasks": sum(bool(row.get("memory", {}).get("validated_replay")) for row in memory_on),
        "planned_on_tasks": len(memory_on),
    }
    aggregates["memory"]["chains"] = {
        family: {
            variant: {
                "planned": len(chain_rows := [
                    row for row in rows
                    if row["experiment"] == "memory"
                    and row.get("family") == family
                    and row["variant"] == variant
                ]),
                "started": sum(row["status"] != "not_started" for row in chain_rows),
                "passed": sum(row["status"] == "success" for row in chain_rows),
                "provider_requests": _sum_started_known(chain_rows, "provider_requests"),
                "provider_tokens": _sum_started_known(chain_rows, "provider_tokens"),
                "task_e2e_ms_sum": _sum_started_known(chain_rows, "e2e_ms"),
            }
            for variant in VARIANTS
        }
        for family in MEMORY_TASKS
    }
    batch_manifest = _load(raw_root / "manifest.json", {}) or {}
    return {
        "schema_version": "statebus.contest_mechanism_collection.v1",
        "raw_root": str(raw_root), "planned": planned, "started": started, "passed": passed,
        "status_counts": {status: sum(row["status"] == status for row in rows)
                          for status in sorted({row["status"] for row in rows})},
        "experiments": aggregates,
        "run_configuration": batch_manifest.get("configuration"),
        "run_plan": batch_manifest.get("plan"),
        "actual_commands": _run_commands(batch_manifest, raw_root=raw_root),
        "environment": _environment(batch_manifest),
        "boundaries": {
            "provider_tokens_are_not_agent_communication_tokens": True,
            "wire_bytes_not_inferred": True,
            "state_no_effect_is_not_business_benefit": True,
            "task_e2e_ms_sum_is_not_batch_wall_clock": True,
        },
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def write_markdown(summary: dict[str, Any], path: Path) -> None:
    environment = summary.get("environment", {})
    commands = summary.get("actual_commands", {})
    lines = [
        "# Contest Memory/State Mechanism Results", "",
        f"- Raw root: `{summary['raw_root']}`",
        f"- Planned / started / passed: {summary['planned']} / {summary['started']} / {summary['passed']}",
        f"- Environment: `{environment.get('os', '-')}`, container `{environment.get('container', '-')}`, source `{environment.get('container_source', '-')}`.",
        f"- Model/API: `{environment.get('host_model', '-')}` on physical GPU {environment.get('vllm_physical_gpu', '-')} at `{environment.get('api_base_url', '-')}`, context {environment.get('context_tokens', '-')}.",
        f"- Embedding: `{environment.get('embedding_model', '-')}` on physical GPU {environment.get('embedding_physical_gpu', '-')} (container `{environment.get('embedding_container_device', '-')}`).",
        f"- Runtime Python: `{environment.get('runtime_python', '-')}`",
        "- Provider tokens are provider usage, not Agent communication tokens; no wire-byte estimate is made.",
        "", "## Actual runner command", "", "```bash",
        str(commands.get("runner", "not recorded")), "```",
        "", "## Memory matched tasks", "",
        "| Task | Off status | On status | Off quality | On quality | Off ms | On ms | Off tokens | On tokens | Consumed | Replay | Source | Reason |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
    ]
    for pair in summary["experiments"]["memory"]["pairs"]:
        off, on = pair["off"], pair["on"]
        mem = on.get("memory", {})
        lines.append("| " + " | ".join(map(_fmt, [
            pair["task_id"], off.get("status"), on.get("status"),
            off.get("quality"), on.get("quality"), off.get("e2e_ms"), on.get("e2e_ms"),
            off.get("provider_tokens"), on.get("provider_tokens"), mem.get("actual_consumed"),
            mem.get("validated_replay"), mem.get("method_source_task"),
            mem.get("compatibility_or_nonreuse_reason"),
        ])) + " |")
    lines += ["", "### Memory four-round totals", "",
              "| Family | Variant | Started | Passed | Requests | Tokens | Task ms sum |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for family, variants in summary["experiments"]["memory"]["chains"].items():
        for variant, totals in variants.items():
            lines.append("| " + " | ".join(map(_fmt, [
                family, variant, totals["started"], totals["passed"],
                totals["provider_requests"], totals["provider_tokens"], totals["task_e2e_ms_sum"],
            ])) + " |")
    lines += ["", "## State matched tasks", "",
        "| Task | Off status | On status | Off quality | On quality | Off chars | On chars | Off tokens | On tokens | Consume | Cross-PID | Effect | On reason |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |"]
    for pair in summary["experiments"]["state"]["pairs"]:
        off, on = pair["off"], pair["on"]
        off_state, on_state = off.get("state", {}), on.get("state", {})
        lines.append("| " + " | ".join(map(_fmt, [
            pair["task_id"], off.get("status"), on.get("status"), off.get("quality"), on.get("quality"),
            off_state.get("selected_evidence_chars"), on_state.get("selected_evidence_chars"),
            off.get("provider_tokens"), on.get("provider_tokens"), on_state.get("consume_count"),
            on_state.get("cross_process_consumption_observed"), on_state.get("behavioral_effect"), on.get("reason"),
        ])) + " |")
    lines += ["", "### State variant totals", "",
              "| Variant | Started | Passed | Requests | Tokens | Task ms sum |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for variant, totals in summary["experiments"]["state"]["by_variant"].items():
        lines.append("| " + " | ".join(map(_fmt, [
            variant, totals["started"], totals["passed"], totals["provider_requests"],
            totals["provider_tokens"], totals["task_e2e_ms_sum"],
        ])) + " |")
    lines += ["", "## Observed and not proven", "",
              "- The bounded smoke observed real Memory replay on current input when recorded; unstarted formal slots prove nothing.",
              "- State publication/transfer/consumption can be observed even when `behavioral_effect=no_effect` or business quality fails.",
              "- Savings ratios are computed only for complete, quality-passing, non-zero matched pairs.",
              "- Candidate hit, actual consumption, and validated replay are separate observations.",
              "- `no_effect` is not a benefit claim, and provider tokens are not inter-agent communication tokens.",
              "- This report describes the recorded raw batch; later implementation fixes are not retroactively claimed as live evidence.",
              "", "## Collector command", "", "```bash",
              str(commands.get("collector", "not recorded")), "```"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def collect(raw_root: Path, report_root: Path) -> dict[str, Any]:
    raw_root, report_root = raw_root.resolve(), report_root.resolve()
    report_root.mkdir(parents=True, exist_ok=False)
    batch_manifest = _load(raw_root / "manifest.json", {}) or {}
    manifest_plan = batch_manifest.get("plan")
    if isinstance(manifest_plan, list) and manifest_plan:
        expected = [
            item for item in manifest_plan
            if isinstance(item, dict)
            and item.get("experiment") in {"memory", "state"}
            and item.get("task_id")
            and item.get("variant") in VARIANTS
        ]
        if len(expected) != len(manifest_plan):
            raise ValueError("contest_mechanism_collection_manifest_plan_invalid")
    else:
        # Preserve the historical fixed-matrix behavior for raw directories
        # created before batch manifests recorded their bounded plan.
        expected = experiment_plan()
    expected_keys = [
        (str(row["experiment"]), str(row["task_id"]), str(row["variant"]))
        for row in expected
    ]
    expected_key_set = set(expected_keys)
    rows = [
        row for row in [*_memory_rows(raw_root), *_state_rows(raw_root)]
        if (str(row["experiment"]), str(row["task_id"]), str(row["variant"]))
        in expected_key_set
    ]
    row_by_key = {
        (str(row["experiment"]), str(row["task_id"]), str(row["variant"])): row
        for row in rows
    }
    row_keys = [
        (str(row["experiment"]), str(row["task_id"]), str(row["variant"]))
        for row in rows
    ]
    if (
        not expected
        or len(rows) != len(expected)
        or len(expected_keys) != len(set(expected_keys))
        or set(row_keys) != set(expected_keys)
    ):
        raise ValueError("contest_mechanism_collection_plan_mismatch")
    rows = [row_by_key[key] for key in expected_keys]
    (report_root / "task_results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    with (report_root / "task_results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in CSV_COLUMNS} for row in rows)
    summary = build_summary(rows, raw_root=raw_root)
    (report_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(summary, report_root / "summary.md")
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="raw contest-mechanisms run root")
    parser.add_argument("--output", required=True, type=Path, help="new report directory")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    summary = collect(args.input, args.output)
    print(json.dumps({key: summary[key] for key in ("planned", "started", "passed", "raw_root")}, ensure_ascii=False, indent=2))
    # Collection succeeds when the fixed 24-slot report is reconstructed.
    # Incomplete or failed experiment slots remain explicit in the summary
    # rather than turning report generation itself into a failed command.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
