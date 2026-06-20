from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from eval.open_runner import (
    PURE_TEXT_OPEN_BASELINE_PACK,
    STRICT_EXTERNAL_TEXT_BASELINE_OBJECT,
    run_pure_text_open_baseline,
)
from eval.runner import run_benchmark
from memory.store import DeterministicEmbeddingProvider
from runtime.llm import DeterministicLLMClient


FORMAL_COMPARATOR_ARTIFACT_NAME = "deterministic_formal_comparator_artifact"


async def build_deterministic_formal_comparator_artifact(
    *,
    out_dir: Path,
    internal_task_set: str = "contest_dual_mode_controlled_v3",
    headline_task_set: str = "contest_honest_headline_v1",
    external_task_set: str = "contest_dual_mode_controlled_v3",
    repeat: int = 1,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    llm_client = DeterministicLLMClient()
    embedder = DeterministicEmbeddingProvider()
    internal_dir = out_dir / "internal_paired_comparator"
    headline_dir = out_dir / "frozen_headline"
    external_dir = out_dir / "external_pure_text_baseline"

    internal_result = await run_benchmark(
        task_set_path=internal_task_set,
        repeat=repeat,
        out_dir=internal_dir,
        embedder=embedder,
        llm_client=llm_client,
    )
    headline_result = await run_benchmark(
        task_set_path=headline_task_set,
        repeat=repeat,
        out_dir=headline_dir,
        embedder=embedder,
        llm_client=llm_client,
    )
    external_result = await asyncio.to_thread(
        run_pure_text_open_baseline,
        out_dir=external_dir,
        repeat=repeat,
        task_set=external_task_set,
    )
    artifact = _build_artifact_payload(
        out_dir=out_dir,
        repeat=repeat,
        internal_result=internal_result,
        headline_result=headline_result,
        external_result=external_result,
    )
    (out_dir / "formal_comparator_artifact.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (out_dir / "formal_comparator_artifact.md").write_text(
        _build_artifact_report(artifact),
        encoding="utf-8",
    )
    return artifact


def _build_artifact_payload(
    *,
    out_dir: Path,
    repeat: int,
    internal_result: dict[str, Any],
    headline_result: dict[str, Any],
    external_result: dict[str, Any],
) -> dict[str, Any]:
    internal_manifest = dict(internal_result.get("manifest", {}))
    headline_manifest = dict(headline_result.get("manifest", {}))
    external_manifest = dict(external_result.get("manifest", {}))
    internal_parity = dict(internal_manifest.get("cross_lane_actual_parity", {}))
    headline_gates = dict(headline_manifest.get("headline_gates", {}))
    external_purity = dict(external_manifest.get("purity_gate", {}))
    surfaces = {
        "internal_paired_comparator": {
            "object_name": "contest_four_role_carrier_comparison_v1",
            "runtime_contract": "statebus_internal_four_role_paired_comparator",
            "source_task_set": str(internal_manifest.get("task_set_name", "")),
            "public_surface": str(internal_manifest.get("task_set_public_surface", "")),
            "evidence_tier": str(internal_manifest.get("task_set_evidence_tier", "")),
            "claim_lanes": list(internal_manifest.get("task_set_claim_lanes", [])),
            "reading_contract": str(internal_manifest.get("task_set_reading_contract", "")),
            "fairness_gate_passed": bool(dict(internal_manifest.get("object_parity_gate", {})).get("passed", False)),
            "cross_lane_actual_parity_passed": bool(internal_parity.get("passed", False)),
            "cross_lane_actual_parity_summary": {
                "shared_task_count": int(internal_parity.get("shared_task_count", 0) or 0),
                "mismatch_task_ids": list(internal_parity.get("mismatch_task_ids", [])),
                "mismatch_counts": dict(internal_parity.get("mismatch_counts", {})),
            },
            "claim_can_say": [
                "same-task internal text vs protocol paired comparator exists",
                "four-role runtime contract is active under deterministic execution",
                "fairness/object-parity and actual cross-lane parity are separately visible",
            ],
            "claim_cannot_say": [
                "not an external traditional pure-text baseline",
                "deterministic artifact is not API token/latency proof",
            ],
            "artifact_paths": {
                "json": str((out_dir / "internal_paired_comparator" / "benchmark_results.json").resolve()),
                "report": str((out_dir / "internal_paired_comparator" / "benchmark_report.md").resolve()),
            },
        },
        "external_pure_text_baseline": {
            "object_name": STRICT_EXTERNAL_TEXT_BASELINE_OBJECT,
            "runtime_contract": str(external_manifest.get("runtime_contract", "")),
            "source_task_set": str(external_manifest.get("task_set", "")),
            "public_surface": str(external_manifest.get("public_surface", "")),
            "evidence_tier": "formal_comparator_baseline",
            "claim_lanes": ["external_pure_text_readiness"],
            "reading_contract": str(external_manifest.get("contract", "")),
            "purity_gate_passed": bool(external_purity.get("passed", False)),
            "claim_surface": str(external_purity.get("claim_surface", "")),
            "helper_shaping": {
                "helper_top1_match_rate": float(external_purity.get("helper_top1_match_rate", 0.0) or 0.0),
                "helper_single_candidate_rate": float(
                    external_purity.get("helper_single_candidate_rate", 0.0) or 0.0
                ),
                "avg_visible_candidate_count": float(
                    external_purity.get("avg_visible_candidate_count", 0.0) or 0.0
                ),
                "helper_dominant_task_ids": list(external_purity.get("helper_dominant_task_ids", [])),
            },
            "claim_can_say": [
                "strict external pure-text four-role baseline exists",
                "same purity/report/gate stack produces a formal-ready verdict",
                "helper shaping metrics are explicit rather than hidden",
            ],
            "claim_cannot_say": [
                "not a protocol carrier object",
                "deterministic artifact is not live API latency/token evidence",
            ],
            "artifact_paths": {
                "json": str((out_dir / "external_pure_text_baseline" / "open_results.json").resolve()),
                "report": str((out_dir / "external_pure_text_baseline" / "open_report.md").resolve()),
            },
        },
        "frozen_headline": {
            "object_name": "contest_honest_headline_v1",
            "runtime_contract": "frozen_dual_mode_formal_headline",
            "source_task_set": str(headline_manifest.get("task_set_name", "")),
            "public_surface": str(headline_manifest.get("task_set_public_surface", "")),
            "evidence_tier": str(headline_manifest.get("task_set_evidence_tier", "")),
            "claim_lanes": list(headline_manifest.get("task_set_claim_lanes", [])),
            "reading_contract": str(headline_manifest.get("task_set_reading_contract", "")),
            "headline_gate_summary": {
                "headline_gates_passed": bool(headline_gates.get("passed", False)),
                "formal_stability_gate_passed": bool(
                    dict(headline_manifest.get("formal_stability_gate", {})).get("passed", False)
                ),
                "object_parity_gate_passed": bool(
                    dict(headline_manifest.get("object_parity_gate", {})).get("passed", False)
                ),
            },
            "claim_can_say": [
                "current contest-facing deterministic headline surface remains frozen and readable",
                "headline/support/audit boundaries remain separate from external baseline work",
            ],
            "claim_cannot_say": [
                "not the external pure-text comparator itself",
                "deterministic headline does not replace serialized API headline evidence",
            ],
            "artifact_paths": {
                "json": str((out_dir / "frozen_headline" / "benchmark_results.json").resolve()),
                "report": str((out_dir / "frozen_headline" / "benchmark_report.md").resolve()),
            },
        },
        "support_and_audit": {
            "object_name": "support_audit_family",
            "runtime_contract": "non_headline_support_and_audit_surfaces",
            "public_surface": "support_only_or_audit_only",
            "evidence_tier": "support_only_plus_audit_only",
            "claim_can_say": [
                "support/audit packs remain available for mechanism checks and diagnostics",
            ],
            "claim_cannot_say": [
                "must not be merged into formal headline or external comparator claims",
            ],
        },
    }
    contest_mapping = {
        "communication_efficiency": {
            "current_formal_object": "contest_honest_headline_v1",
            "deterministic_scope": "stability/control-surface only; not live token/latency headline proof",
        },
        "non_text_state_transfer": {
            "current_formal_object": "contest_four_role_carrier_comparison_v1",
            "deterministic_scope": "internal paired comparator plus typed-state parity/fairness boundaries",
        },
        "shared_memory_reuse": {
            "current_formal_object": "contest_honest_headline_v1",
            "deterministic_scope": "memory gates remain lane-specific and should not be mixed with external baseline",
        },
        "multi_agent_integrity": {
            "current_formal_object": "contest_four_role_carrier_comparison_v1 and external_pure_text_four_role_baseline_v1",
            "deterministic_scope": "four-role graph, role traces, purity/fairness/parity are checkable",
        },
        "external_pure_text_comparator": {
            "current_formal_object": STRICT_EXTERNAL_TEXT_BASELINE_OBJECT,
            "deterministic_scope": "formal-ready under deterministic purity gate; next step is API repeat=1",
        },
    }
    api_repeat1_plan = {
        "ready": bool(external_purity.get("formal_ready", False)),
        "purpose": "serialized API repeat=1 comparator sanity pass before any larger API sweep",
        "script": "scripts/run_formal_comparator_api_repeat1.sh",
        "run_order": [
            {
                "object": "contest_four_role_carrier_comparison_v1",
                "why_first": "check internal paired comparator role-level API wiring before external comparison packaging",
                "gate_to_watch": [
                    "object_parity_gate",
                    "cross_lane_actual_parity",
                    "formal_stability_gate",
                ],
                "command": (
                    "source deploy/activate_statebus_host.sh\n"
                    "python -m eval.runner --task-set contest_dual_mode_controlled_v3 --repeat 1 "
                    "--modes text,protocol --llm-mode api --llm-config deploy/statebus_llm.yaml.local "
                    "--out runs/<stamp>/api_repeat1_internal_paired"
                ),
                "out_dir": "runs/<stamp>/api_repeat1_internal_paired",
            },
            {
                "object": STRICT_EXTERNAL_TEXT_BASELINE_OBJECT,
                "why_second": "check strict external pure-text comparator under the same model family after internal API wiring passes",
                "gate_to_watch": [
                    "purity_gate",
                    "helper_shaping",
                    "claim_surface",
                ],
                "command": (
                    "source deploy/activate_statebus_host.sh\n"
                    "python -m eval.open_runner --pack pure_text_open_baseline_v1 --repeat 1 "
                    "--task-set contest_dual_mode_controlled_v3 --llm-mode api "
                    "--llm-config deploy/statebus_llm.yaml.local "
                    "--out runs/<stamp>/api_repeat1_external_pure_text_baseline"
                ),
                "out_dir": "runs/<stamp>/api_repeat1_external_pure_text_baseline",
            },
            {
                "object": "contest_honest_headline_v1",
                "why_third": "only after comparator objects are clean; keep headline evidence separate from comparator preparation",
                "gate_to_watch": [
                    "headline_gates",
                    "formal_stability_gate",
                ],
                "command": (
                    "source deploy/activate_statebus_host.sh\n"
                    "python -m eval.runner --task-set contest_honest_headline_v1 --repeat 1 "
                    "--modes text,protocol --llm-mode api --llm-config deploy/statebus_llm.yaml.local "
                    "--out runs/<stamp>/api_repeat1_frozen_headline"
                ),
                "out_dir": "runs/<stamp>/api_repeat1_frozen_headline",
            },
        ],
        "do_not_mix_rule": (
            "keep internal comparator, external baseline, and frozen headline in separate out dirs; "
            "do not merge support/audit artifacts into comparator or headline reads"
        ),
    }
    return {
        "artifact_name": FORMAL_COMPARATOR_ARTIFACT_NAME,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "repeat": repeat,
        "deterministic_scope": (
            "This artifact organizes current deterministic formal comparator objects and boundaries. "
            "It is a control/fairness/purity/parity packaging artifact, not a live API token/latency proof."
        ),
        "surfaces": surfaces,
        "contest_mapping": contest_mapping,
        "current_deterministic_conclusion": {
            "formal_internal_comparator_exists": True,
            "formal_external_pure_text_baseline_ready": bool(external_purity.get("formal_ready", False)),
            "headline_remains_frozen": True,
            "api_repeat1_next_step_ready": bool(external_purity.get("formal_ready", False)),
        },
        "claim_boundaries": {
            "can_say": [
                "internal paired comparator and external pure-text baseline both exist as deterministic comparator objects",
                "external pure-text baseline is formal-ready under the current deterministic purity gate",
                "frozen headline remains a separate contest-facing object",
            ],
            "cannot_say": [
                "deterministic artifact alone is not live API token/latency proof",
                "support/audit objects must not be read as formal comparator headline evidence",
            ],
        },
        "api_repeat1_plan": api_repeat1_plan,
    }


def _build_artifact_report(artifact: dict[str, Any]) -> str:
    surfaces = dict(artifact.get("surfaces", {}))
    lines = [
        "# Deterministic Formal Comparator Artifact",
        "",
        artifact["deterministic_scope"],
        "",
        "## Comparator Surfaces",
        "",
    ]
    for key in (
        "internal_paired_comparator",
        "external_pure_text_baseline",
        "frozen_headline",
        "support_and_audit",
    ):
        surface = dict(surfaces.get(key, {}))
        lines.extend(
            [
                f"### {surface.get('object_name', key)}",
                "",
                f"- Public surface: `{surface.get('public_surface', '')}`",
                f"- Evidence tier: `{surface.get('evidence_tier', '')}`",
                f"- Runtime contract: `{surface.get('runtime_contract', '')}`",
            ]
        )
        claim_lanes = surface.get("claim_lanes")
        if isinstance(claim_lanes, list) and claim_lanes:
            lines.append(f"- Claim lanes: `{', '.join(str(item) for item in claim_lanes)}`")
        reading_contract = str(surface.get("reading_contract", "")).strip()
        if reading_contract:
            lines.append(f"- Reading contract: `{reading_contract}`")
        if key == "internal_paired_comparator":
            parity = dict(surface.get("cross_lane_actual_parity_summary", {}))
            lines.append(
                f"- Actual parity: `{'pass' if surface.get('cross_lane_actual_parity_passed') else 'mismatch present'}`"
            )
            lines.append(
                f"- Actual parity mismatches: `{parity.get('mismatch_counts', {})}` across {int(parity.get('shared_task_count', 0))} shared tasks"
            )
        if key == "external_pure_text_baseline":
            helper = dict(surface.get("helper_shaping", {}))
            lines.append(f"- Purity gate: `{'pass' if surface.get('purity_gate_passed') else 'fail'}`")
            lines.append(f"- Claim surface: `{surface.get('claim_surface', '')}`")
            lines.append(
                f"- Helper shaping: `top1={helper.get('helper_top1_match_rate', 0.0):.2f}, "
                f"single_candidate={helper.get('helper_single_candidate_rate', 0.0):.2f}, "
                f"avg_visible_candidates={helper.get('avg_visible_candidate_count', 0.0):.2f}`"
            )
        if key == "frozen_headline":
            gate_summary = dict(surface.get("headline_gate_summary", {}))
            lines.append(
                f"- Headline gates: `{'pass' if gate_summary.get('headline_gates_passed') else 'not_all_passed'}`"
            )
        for claim_key, label in (("claim_can_say", "Can say"), ("claim_cannot_say", "Cannot say")):
            values = surface.get(claim_key, [])
            if isinstance(values, list) and values:
                lines.append(f"- {label}: `{'; '.join(str(item) for item in values)}`")
        artifact_paths = surface.get("artifact_paths")
        if isinstance(artifact_paths, dict) and artifact_paths:
            for path_key, path_value in artifact_paths.items():
                lines.append(f"- Artifact {path_key}: `{path_value}`")
        lines.append("")
    lines.extend(
        [
            "## Contest Mapping",
            "",
            "| Requirement axis | Current object | Deterministic scope |",
            "| --- | --- | --- |",
        ]
    )
    for axis, payload in dict(artifact.get("contest_mapping", {})).items():
        item = dict(payload)
        lines.append(
            f"| {axis} | {item.get('current_formal_object', '')} | {item.get('deterministic_scope', '')} |"
        )
    lines.extend(
        [
            "",
            "## Deterministic Conclusion",
            "",
            f"- Internal paired comparator exists: `{'yes' if artifact['current_deterministic_conclusion']['formal_internal_comparator_exists'] else 'no'}`",
            f"- External pure-text baseline formal-ready: `{'yes' if artifact['current_deterministic_conclusion']['formal_external_pure_text_baseline_ready'] else 'no'}`",
            f"- Frozen headline remains separate: `{'yes' if artifact['current_deterministic_conclusion']['headline_remains_frozen'] else 'no'}`",
            "",
            "## API Repeat=1 Plan",
            "",
            artifact["api_repeat1_plan"]["purpose"],
            f"- Unified script: `{artifact['api_repeat1_plan']['script']}`",
            "",
        ]
    )
    for item in artifact["api_repeat1_plan"]["run_order"]:
        lines.extend(
            [
                f"### {item['object']}",
                "",
                f"- Why: `{item['why_first'] if 'why_first' in item else item['why_second'] if 'why_second' in item else item['why_third']}`",
                f"- Gates: `{', '.join(item['gate_to_watch'])}`",
                f"- Out dir: `{item['out_dir']}`",
                "```bash",
                item["command"],
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## Stopline",
            "",
            "- Do not merge support/audit outputs into formal comparator or frozen headline reads.",
            "- Do not read this deterministic artifact as live API token/latency superiority evidence.",
            f"- API repeat=1 ready: `{'yes' if artifact['api_repeat1_plan']['ready'] else 'no'}`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build the deterministic formal comparator artifact.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--internal-task-set", default="contest_dual_mode_controlled_v3")
    parser.add_argument("--headline-task-set", default="contest_honest_headline_v1")
    parser.add_argument("--external-task-set", default="contest_dual_mode_controlled_v3")
    args = parser.parse_args()
    asyncio.run(
        build_deterministic_formal_comparator_artifact(
            out_dir=args.out,
            repeat=args.repeat,
            internal_task_set=args.internal_task_set,
            headline_task_set=args.headline_task_set,
            external_task_set=args.external_task_set,
        )
    )


if __name__ == "__main__":
    main()
