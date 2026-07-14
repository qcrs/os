from __future__ import annotations

import os


if os.getenv("STATEBUS_VLLM_EXPORT_PREFIX_COUNTERS", "0").strip().lower() in {
    "1",
    "true",
    "yes",
}:
    from vllm_v0_prefix_counter_exporter import install

    install()
