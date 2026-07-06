# Fix Plan

## This audit fixed

1. Answer restoration metric overclaim

Files:

- `v2/runtime/driver.py`
- `v2/benchmark/continuous_runner.py`
- `tests/v2/test_continuous_runner.py`

Change: exact replay no longer increments or backfills `answer_restoration_replay_count`.

Verification:

- `tests/v2/test_continuous_runner.py`: 11 passed.
- focused v2 command: 49 passed.

2. CodeAct historical report downgrade

File:

- `docs/reports/v2_experiment_summary_20260703.md`

Change: marked CodeAct LLM-generation numbers as historical diagnostics and blocked upgrade to current formal realtime code-generation proof.

Verification: documentation diff reviewed; no overclaim added.

3. Comprehensive audit record

Files:

- this directory and benchmark artifacts.

Change: created source map, code review, issue ledger, evidence record, fix plan, applied changes, and remaining risks.

## 1 day fixes

1. Container activation mismatch

Files:

- `deploy/activate_statebus_host.sh`
- Docker image/build docs or compose setup

Approach: either install the expected conda path inside the container or add a container-specific activation mode that aliases `/usr/bin/python3` and validates required packages.

Risk: changing activation can affect host workflow; keep host and container branches explicit.

Verification: prompt's exact activation command succeeds under Docker root.

2. Formal external compare evidence

Files:

- benchmark artifact directory
- `docs/improvement/19_claim_upgrade_completion_report_20260706.md` only after new evidence exists

Approach: run formal compare with real API key and local embedding, save JSON, extract fairness and quality gates.

Risk: API nondeterminism and cost.

Verification: same-tier JSON with `formal_superiority_claim_allowed` and fairness fields.

3. Validator integration decision

Files:

- `tasks/formal/*/validator.py`
- `v2/benchmark/task_registry.py`
- `v2/runtime/smoke.py`

Approach: either make family validators active in benchmark validation or rename/remove them as helper examples.

Risk: active validators may fail current outputs and force benchmark fixes.

Verification: a failing validator fixture must fail the benchmark.

## 3 day fixes

1. API role-path formal run

Approach: run formal internal and formal compare in `--role-path-mode api`, archive role telemetry, and update safe claims only if quality gates pass.

2. Memfd unavailable real fallback validation

Approach: run in a capability-masked environment or a container/kernel path where `memfd_create` is unavailable; prove fallback respects shared-memory budget.

3. Prompt-visible evidence regression tests

Approach: add tests asserting raw evidence bytes, prompt-visible bytes, and role hydration bytes for representative CSV/table/financial cases.

## Requires architecture work

1. Realtime open-ended CodeAct

Needed if the project wants to claim realtime LLM code generation. It requires an API generation stage, repair loop evidence, sandbox policy, and formal validation artifacts.

2. Pure typed nested protobuf payloads

Needed if the project wants to claim all nested control payloads are protobuf-native rather than JSON strings inside protobuf fields.

3. openEuler VM validation

Needed before openEuler compatibility claims.

## Do not fix by wording only

These claims must remain downgraded until evidence exists:

- formal external superiority.
- speed advantage.
- generic answer restoration.
- openEuler VM compatibility.
- realtime LLM code generation.
