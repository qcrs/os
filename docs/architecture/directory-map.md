# StateBus OS Directory Map

This map describes the target submission layout for this `os` checkout. The
first refactor phase adds indexes and stable entry points while keeping the
existing source, scripts, tests, and reports in place.

| Current path | Target path | Role | Phase-one status |
| --- | --- | --- | --- |
| `statebus/` | `src/statebus/` | Runtime, contracts, memory, benchmark, Studio backend | Moved; packaging and runtime imports use `src` |
| `studio-ui/` | `src/studio-ui/` | React/TypeScript Studio frontend | Moved; Studio serves `src/studio-ui/dist` |
| `scripts/` | `tests/benchmarks/` and `demo/` | Measurement and demonstration entry points | Add dispatcher; keep legacy scripts |
| `tests/` | `tests/unit`, `tests/integration`, `tests/benchmarks`, `tests/fixtures` | Tests and reproducibility material | Classify by index before moving files |
| `docs/mrr/` | `docs/design/mrr/` | MRR contracts and design | Preserve source; classify as design |
| KV/APC/Logit design and audit docs | `docs/design/kv-apc-logit/` | Mechanism contracts and implementation notes | Preserve historical audit material |
| `docs/reports/` | `docs/reports/` plus `tests/evidence/` | Reports and selected evidence | Keep raw reports; publish curated evidence |
| `studio-ui/` launchers and samples | `demo/` | Reviewer-facing demo | Add wrappers and offline sample index |

The compatibility rule is deliberate: no source or test is deleted during this
phase. A later source move must update packaging, imports, scripts, frontend
paths, and tests together.
