# StateBus Demo

`demo/` is the reviewer-facing launch surface. It will contain a short fixed
demo, offline replay samples, and configuration templates. The Studio product
source remains under `src/studio-ui/`; it is not duplicated into this folder.

```bash
demo/run_demo.sh --offline
demo/run_demo.sh --local-vllm
demo/run_smoke.sh --dry-run
```

The long-running measurement suites belong under `tests/benchmarks/`, while
their curated output belongs under `tests/evidence/`.
