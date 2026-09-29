# Benchmark Entrypoints

Use `run_statebus.sh` as the stable keyword-based entry point. Existing runners
remain available for forensic reproduction and are not deleted in this phase.

```bash
tests/benchmarks/run_statebus.sh smoke --dry-run
tests/benchmarks/run_statebus.sh mainline-24 --dry-run
tests/benchmarks/run_statebus.sh mainline-mechanisms --dry-run
tests/benchmarks/run_statebus.sh apc --dry-run
tests/benchmarks/run_statebus.sh kv --dry-run
tests/benchmarks/run_statebus.sh logit --dry-run
tests/benchmarks/run_statebus.sh utility --dry-run
```

Live execution still requires the underlying runner's explicit options and
service maintenance authorization. The dispatcher never starts or stops a
model service implicitly.
