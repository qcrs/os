# Test And Benchmark Evidence

All commands were attempted with Docker root in `statebus-dev-qcrs`.

Important environment limitation: the prompt's `source deploy/activate_statebus_host.sh` path failed in the container because conda is absent. Verification therefore used `/usr/bin/python3` in the container-root environment and is labeled as such.

## Environment checks

Container path:

```text
/workspace/statebus/project
```

Container Python:

```text
/usr/bin/python3
Python 3.11.6
pytest ok
```

Activation failure:

```text
[statebus] conda executable not found; set CONDA_EXE or add conda to PATH
/etc/profile.d/conda.sh missing
conda: command not found
CONDA_PREFIX: unbound variable
```

`jq` failure:

```text
bash: line 1: jq: command not found
```

Python extraction was used instead.

## Static verification

Command:

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m py_compile ...'
```

Result: pass.

Command:

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && bash -n scripts/run_v2_full_container_audit_suite.sh'
```

Result: pass.

## Test verification

First focused test attempt:

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m pytest -q tests/v2/test_continuous_runner.py tests/v2/test_state_materialization.py tests/v2/test_minimal_benchmark.py tests/v2/test_preflight_and_live_runner.py'
```

Result: failed once because `test_continuous_runner_executes_replay_collection` still asserted `answer_restoration_replay_count == exact_replay_count`.

Fix applied: updated replay metric implementation and stale assertions.

Post-fix impacted suite:

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m pytest -q tests/v2/test_continuous_runner.py'
```

Result:

```text
11 passed in 342.32s (0:05:42)
```

Post-fix focused command:

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m pytest -q tests/v2/test_state_materialization.py tests/v2/test_minimal_benchmark.py tests/v2/test_preflight_and_live_runner.py tests/v2/test_continuous_runner.py'
```

Result:

```text
49 passed in 371.18s (0:06:11)
```

Smoke:

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m runtime.smoke'
```

Result:

```text
statebus smoke ok: mode=text memory_hits=0.0 messages=292.0 control_bytes=243456.0 task_ms=5895.53
statebus smoke ok: mode=protocol memory_hits=0.0 messages=292.0 control_bytes=215901.0 task_ms=5469.95
statebus comparator artifact ok: external_claim_surface=formal_ready api_repeat1_ready=True
```

Preflight:

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m v2.benchmark.live_runner --suite preflight --role-path-mode deterministic --embedding-mode deterministic ...'
```

Result: command exited 0. Artifact: `artifacts/preflight_deterministic.stdout.json`.

## Formal benchmark artifacts

Artifacts are committed under:

- `artifacts/formal_auto.stdout.json`
- `artifacts/formal_shared_memory.stdout.json`
- `artifacts/formal_memfd_local.stdout.json`

Extracted fields:

| Artifact | Role path | Embedding | Cases | Quality pass | Families | Requested | Used | memfd transfers | memfd publishes | memfd bytes | shm publishes | mmap publishes | semantic transfers |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| `formal_auto.stdout.json` | deterministic | deterministic | 25 | 25 | 5 | auto | shared_memory | 0 | 0 | 0 | 25 | 0 | 25 |
| `formal_shared_memory.stdout.json` | deterministic | deterministic | 25 | 25 | 5 | shared_memory | shared_memory | 0 | 0 | 0 | 25 | 0 | 25 |
| `formal_memfd_local.stdout.json` | deterministic | local | 25 | 25 | 5 | memfd | memfd | 25 | 25 | 247076 | 0 | 0 | 25 |

## Evidence strength classification

Strong evidence:

- Fresh container-root formal internal deterministic benchmark JSON for 25/25 and state-pool backend reporting.
- Post-fix pytest green for affected replay metric behavior.
- Text and protocol smoke execution.

Medium evidence:

- API four-role code paths exist by source review, but not rerun in formal API mode here.
- CodeAct sandbox and artifact path exists by source/tests, but not fresh realtime LLM formal evidence.

Weak or bounded evidence:

- Memfd unavailable fallback.
- Family-specific `validator.py` files.

Unsupported:

- formal external superiority.
- speed advantage.
- openEuler VM validation.
- generic answer restoration.
