from __future__ import annotations

import argparse
from pathlib import Path
import time

from v2.benchmark.experiment_design import (
    LaneCallbackResult,
    LaneRunSpec,
    run_balanced_serialized_experiment,
)
from v2.control import (
    ControlHeader,
    EventType,
    ExecRequest,
    RefHandle,
    SubprocessExecutorTransport,
    SuccessResult,
)
from v2.utils import stable_json_dumps


def _request(spec: LaneRunSpec) -> ExecRequest:
    suffix = f"{spec.block_index}-{spec.sequence_index}-{spec.lane}"
    return ExecRequest(
        header=ControlHeader(
            trace_id=f"transport-experiment:{suffix}",
            task_id=f"transport-experiment-{suffix}",
            step_id="executor-carrier",
            attempt_id=f"attempt-{spec.global_index}",
            target_role="executor",
            timeout_ms=20_000,
            event_type=EventType.REQ_EXEC,
        ),
        artifact_refs=(RefHandle(ref_id=f"artifact-{suffix}", ref_kind="artifact"),),
        runtime_reuse_contract="no_semantic_state",
        output_contract_version="statebus.transport_probe.v1",
        workspace_root=f"/tmp/statebus-transport-{suffix}",
        input_manifest_hash=f"input-{suffix}",
    )


def run_control_transport_experiment(
    *,
    output_root: Path,
    repeat_count: int = 3,
) -> dict[str, object]:
    output_root.mkdir(parents=True, exist_ok=True)
    socket_root = output_root / "sockets"
    socket_root.mkdir(parents=True, exist_ok=True)
    audits: list[dict[str, object]] = []

    def callback(carrier: str):
        def run(spec: LaneRunSpec) -> LaneCallbackResult:
            request = _request(spec)
            transport = SubprocessExecutorTransport(
                socket_path=socket_root / f"{spec.global_index:03d}-{carrier}.sock",
                timeout_s=20.0,
            )
            started_ns = time.perf_counter_ns()
            result = transport.execute(
                request,
                carrier="protobuf" if carrier == "typed_protobuf" else "utf8_text",
            )
            transport_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
            audit = {} if transport.last_exchange_audit is None else {
                **transport.last_exchange_audit.canonical_payload(),
                "block_index": spec.block_index,
                "sequence_index": spec.sequence_index,
                "global_index": spec.global_index,
                "quality_passed": isinstance(result, SuccessResult),
            }
            audits.append(audit)
            return LaneCallbackResult(
                quality_passed=isinstance(result, SuccessResult),
                component_ms={"transport": transport_ms},
            )

        return run

    observations, statistical_summary = run_balanced_serialized_experiment(
        {
            "typed_protobuf": callback("typed_protobuf"),
            "utf8_text": callback("utf8_text"),
        },
        lane_a="typed_protobuf",
        lane_b="utf8_text",
        repeat_count=repeat_count,
    )
    summary = {
        "schema_version": "statebus.control_transport_experiment.v1",
        "run_root": str(output_root),
        "experiment_scope": "local_uds_subprocess_carrier_only",
        "observations": [observation.canonical_payload() for observation in observations],
        "transport_audits": sorted(audits, key=lambda item: int(item.get("global_index", 0))),
        "statistics": statistical_summary,
        "model_latency_included": False,
        "hydration_latency_included": False,
        "validation_latency_included": False,
        "carrier_latency_claim_allowed": bool(
            statistical_summary.get("latency_superiority_claim_allowed", False)
        ),
        "end_to_end_latency_superiority_claim_allowed": False,
    }
    (output_root / "summary.json").write_text(
        stable_json_dumps(summary) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a serialized ABBA/BAAB StateBus control-carrier experiment."
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--repeat-count", type=int, default=3)
    args = parser.parse_args()
    summary = run_control_transport_experiment(
        output_root=args.output_root,
        repeat_count=args.repeat_count,
    )
    print(stable_json_dumps({
        "summary_path": str(args.output_root / "summary.json"),
        "observation_count": summary["statistics"]["observation_count"],
        "carrier_latency_claim_allowed": summary["carrier_latency_claim_allowed"],
        "end_to_end_latency_superiority_claim_allowed": False,
    }))


if __name__ == "__main__":
    main()
