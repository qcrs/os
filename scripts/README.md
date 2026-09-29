# Script Entrypoints

The repository keeps a small set of stable operational and experiment entrypoints.
The benchmark dispatcher is `tests/benchmarks/run_statebus.sh`; it selects the
mainline, mechanism, utility, and local-vLLM smoke flows without changing their
contracts.

## Stable paths

```text
tests/benchmarks/run_statebus.sh                 keyword dispatcher
scripts/run_contest_dsl_mainchains.sh            P-TEXT/SB-FULL 24-round chains
scripts/run_contest_mechanisms.sh                mainline mechanism ablation
scripts/experiments/contest_model_assist/        longtext utility suite
scripts/experiments/engine_local_kv/              explicit KV experiments
scripts/probe_local_vllm_prefix_alignment.py     APC/prefix observation probe
scripts/run_local_vllm_container_check.sh        local-vLLM container smoke
scripts/start_statebus.sh                        environment/container setup
scripts/run_statebus_studio.sh                   Studio backend/frontend
scripts/vllm/                                    managed vLLM service
```

`scripts/diagnostics/` contains reusable CodeAct, Runtime, contract, Logit,
and persistence diagnostics. `scripts/evidence/` contains report and evidence
post-processing tools. These directories are not part of the default benchmark
dispatcher.

Historical stage runners, old utility probes, supplemental GPU experiments, and
diagnostics that referenced removed top-level tests were removed from this
branch. Their original run evidence remains under `docs/reports/` and on the
backup branch.
