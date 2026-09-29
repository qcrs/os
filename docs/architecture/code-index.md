# StateBus Code Index

## Runtime and contracts

| Area | Current entry points | Target ownership |
| --- | --- | --- |
| Contracts | `src/statebus/contracts/` | `src/statebus/contracts/` |
| Control plane | `src/statebus/control/` | `src/statebus/control/` |
| Runtime | `src/statebus/runtime/` | `src/statebus/runtime/` |
| State and references | `src/statebus/state/`, `src/statebus/refs/` | `src/statebus/state/`, `src/statebus/refs/` |
| Retrieval and memory | `src/statebus/retrieval/`, `src/statebus/memory/` | `src/statebus/retrieval/`, `src/statebus/memory/` |
| Benchmark runners | `src/statebus/benchmark/` | `src/statebus/benchmark/` |
| Studio backend | `src/statebus/studio/` | `src/statebus/studio/` |
| Studio frontend | `src/studio-ui/` | `src/studio-ui/` |

## Stable command owners

| Command | Current implementation | Stable dispatcher |
| --- | --- | --- |
| Smoke | `scripts/run_local_vllm_container_check.sh` | `tests/benchmarks/run_statebus.sh smoke` |
| 24-round mainline | `scripts/run_contest_dsl_mainchains.sh` | `tests/benchmarks/run_statebus.sh mainline-24` |
| Mainline mechanisms | `scripts/run_contest_mechanisms.sh` | `tests/benchmarks/run_statebus.sh mainline-mechanisms` |
| APC/KV/Logit utility | `scripts/experiments/contest_model_assist/run_utility_suite.sh` | `tests/benchmarks/run_statebus.sh apc`, `kv`, or `logit` |
| Long-text utility | `scripts/experiments/contest_model_assist/run_utility_suite.sh` | `tests/benchmarks/run_statebus.sh utility` |

The dispatcher is a routing layer. It does not change the runner contracts or
start services implicitly.
