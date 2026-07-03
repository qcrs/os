# StateBus v2 Persistence Profiles

Date: 2026-07-03

Scope: diagnostic readout for v2 runtime persistence overhead.

The current runtime still writes the full audit bundle needed for replay,
debuggability, and claim verification. The profiles below are analysis buckets,
not a claim that the runtime has switched to a cheaper persistence mode.

| Profile | Meaning | Claim Boundary |
| --- | --- | --- |
| `audit_full` | Keep every manifest, sidecar, telemetry log, role prompt slice, CodeAct audit, and replay detail. | Maximum auditability; highest write volume. |
| `benchmark_balanced` | Keep replay/benchmark-critical manifests and compact sidecars while dropping repeated deep audit details. | Proposed benchmark profile; must be validated before becoming default. |
| `fast_runtime` | Keep minimum runtime/replay lineage candidates only. | Future optimization target; not enough for final evidence claims by itself. |

Run the current readout:

```bash
python3 scripts/v2_diagnostics/runtime_persistence_breakdown.py \
  --output-root /statebus/runs/v2-diagnostics
```

The output bundle contains:

- `summary.json`
- `summary.md`
- `file_sizes.csv`
- `sidecar_sizes.csv`
- `manifest_sizes.csv`

Use this report to explain persistence overhead honestly. Do not claim the
runtime is low-overhead merely because a hypothetical profile excludes files.
