from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from eval.formal_comparator_artifact import build_deterministic_formal_comparator_artifact
from eval.runner import run_benchmark
from memory.store import DeterministicEmbeddingProvider
from runtime.llm import DeterministicLLMClient


async def _run_all_modes(root: Path) -> dict[str, object]:
    return await run_benchmark(
        repeat=1,
        out_dir=root,
        embedder=DeterministicEmbeddingProvider(),
        llm_client=DeterministicLLMClient(),
    )


def main() -> None:
    print(
        "statebus smoke scope:"
        " deterministic repeat=1 host sanity check;"
        " verifies runnable benchmark path and formal comparator artifact generation only,"
        " not formal API timing evidence"
    )
    with tempfile.TemporaryDirectory(prefix="statebus-smoke-") as tmpdir:
        root = Path(tmpdir)
        result = asyncio.run(_run_all_modes(root))
        comparator_artifact = asyncio.run(
            build_deterministic_formal_comparator_artifact(
                out_dir=root / "formal_comparator",
                repeat=1,
            )
        )
        for mode in result["manifest"]["modes"]:
            aggregate = result["summary"][mode]["aggregate"]
            control_bytes = aggregate["text_bytes"] if mode == "text" else aggregate["protocol_bytes"]
            print(
                "statebus smoke ok:"
                f" mode={mode}"
                f" memory_hits={aggregate['memory_hits']}"
                f" messages={aggregate['message_count']}"
                f" control_bytes={control_bytes}"
                f" task_ms={aggregate['task_ms']:.2f}"
            )
        print(
            "statebus comparator artifact ok:"
            f" external_claim_surface={comparator_artifact['surfaces']['external_pure_text_baseline']['claim_surface']}"
            f" api_repeat1_ready={comparator_artifact['api_repeat1_plan']['ready']}"
        )


if __name__ == "__main__":
    main()
