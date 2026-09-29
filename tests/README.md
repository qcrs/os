# Tests and Verification

This directory contains correctness tests, benchmark entry points, and curated
verification evidence.

```text
tests/
├── unit/          # Small offline contracts, runtime, memory, CodeAct, and mechanism tests
├── integration/   # Minimal runtime/mainline and Studio integration tests
├── benchmarks/    # Mainline, mechanism, and longtext utility validation
├── measurement/   # Reserved compatibility namespace; active tests are elsewhere
└── evidence/      # Curated mainline, mechanism, and APC/KV/Logit results
```

The refactoring branch keeps only the high-value offline regression set. The
historical MRR and contest-stage tests remain available on the backup branch;
they are not part of the default delivery tree.

Run the offline regression with:

```bash
source deploy/activate_statebus_host.sh
python -m pytest -q tests/unit tests/integration tests/benchmarks
```

Use `tests/benchmarks/run_statebus.sh --help` for the stable experiment
entry point. `tests/evidence/` distinguishes the 48-task mainline, mechanism
ablations, and the independent APC/KV/Logit utility chain. It intentionally
contains result aggregates only; service logs and failed runs remain in the
report archive.
