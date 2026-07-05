# StateBus v2 Review Follow-up And Full Test Script

- Date: 2026-07-05
- Branch: `feat/statebus-v2-container-runtime`
- Commit: `f3dd0944eb5e6bbafc88d79eb2db24e0451b8a3e`
- Container: `statebus-dev-qcrs`
- Activation: `/usr/local/bin/activate_statebus_container.sh`
- Scope: follow-up review after `12_independent_codex_full_audit.md`, targeted fixes, and full test-script delivery

## This Pass Changed

1. `v2/state/store.py`
   - Added `weakref.finalize` cleanup for orphaned shared-memory segments.
   - This hardens abnormal-exit cleanup instead of relying only on normal `release()`.
2. `v2/runtime/smoke.py`
   - Added explicit `state_store.teardown()` on successful smoke completion.
   - This reduces shared-memory leakage during long benchmark sequences and complements the finalizer path.
3. `tests/v2/test_state_materialization.py`
   - Added finalizer regression coverage.
   - Added `run_smoke()` teardown regression coverage.
4. `tests/v2/test_continuous_task_family_design.py`
   - Added `cross_period_financial_v1` manifest coverage.
   - Added a regression asserting the family is designed for strategy-style validated reuse, not answer restoration.
5. `scripts/run_v2_full_container_audit_suite.sh`
   - Added a host-side wrapper that runs the full audit suite only through container-root execution.
   - The script isolates every benchmark stage with its own `runtime_root`, `workspace_root`, and `socket_path`.
   - The script attempts strongest evidence first, records downgrade/fallback stages, and writes status/summary artifacts.

## What In `docs/improvement` Is Now Resolved

1. `11_competition_readiness_audit.md` P0-A is outdated.
   - External baseline no longer falls back to gold `revenue_value` for observed answers.
   - The remaining issue is naming clarity: `revenue_fallback_used` now means "LLM omitted value while context existed", not "answer was replaced by gold".
2. `11_competition_readiness_audit.md` P0-C is outdated.
   - `TableStructureRetriever` is no longer hardcoded to first-row-only behavior for the relevant benchmark paths.
   - Cross-period and multi-row retrieval logic is already in `v2/retrieval/pipeline.py`.
3. `11_competition_readiness_audit.md` missing-test items are partly outdated.
   - External empty-revenue regression exists in `tests/v2/test_fixed_answer_and_external_baseline.py`.
   - `SubprocessExecutorTransport` memfd end-to-end coverage exists in `tests/v2/test_control_plane.py`.
   - `continuous-replay --family` CLI regression coverage exists in `tests/v2/test_preflight_and_live_runner.py`.
4. `05_memory_and_replay_complete_design.md` FAISS note is outdated.
   - FAISS-backed retrieval exists in code and coverage.
5. `03_agent_role_and_task_redesign.md` cross-period family note is outdated.
   - `cross_period_financial_v1` is implemented and now has stronger design coverage.

## What Is Still Not "Solved By Code"

1. Formal family breadth is still narrow.
   - The formal suite remains a precision anchor, not a broad reasoning benchmark.
   - This is a benchmark/task-design issue, not a local correctness bug.
2. External compare is still dev-only evidence.
   - It is useful for fairness and efficiency contrast, but not a formal superiority proof.
3. `validated_replay` naming is still more aggressive than behavior.
   - The runtime behavior is strategy-backed downgraded reuse, not generic answer restoration.
4. `SubprocessExecutorTransport`, `memfd + SCM_RIGHTS`, and persistent `mmap` publish remain capability/test-level evidence.
   - They are not yet benchmark-mainline evidence.
5. Full `continuous-replay` collection in `api + local` is still heavier than the formal/compare path.
   - Strong replay evidence now exists for `cross_period_financial_v1`, but not yet for the entire replay collection in one uninterrupted run.

## New Issue Found In This Pass

1. Parallel `live_runner` invocations are not safe if they share the default `runtime_root`.
   - Two concurrent `continuous-replay` runs with the same default roots can race in `v2/benchmark/continuous_runner.py:_prepare_dir()`.
   - This is primarily a runner isolation issue, not a benchmark correctness issue under the repo's serialized evidence discipline.
   - The new full audit script avoids this by assigning stage-local roots and sockets.

## Evidence Run In This Pass

1. Targeted regressions:
   - `tests/v2/test_state_materialization.py`
   - `tests/v2/test_continuous_task_family_design.py`
   - Result: pass
2. Focused regression set:
   - `tests/v2/test_state_materialization.py tests/v2/test_smoke.py`
   - Result: `17 passed`
3. Full repo pytest:
   - Result: `504 passed, 101 warnings`
4. `runtime.smoke`:
   - Result: pass
5. Strong replay family evidence:
   - Command: `continuous-replay --family cross_period_financial_v1 --role-path-mode api --embedding-mode local`
   - Result: pass
   - Key metrics:
     - `validated_replay_count = 4`
     - `skipped_step_count = 4`
     - `shared_memory_publish_count = 10`
     - `semantic_state_transfer_count = 10`
   - Key report:
     - `/statebus/runs/codex-review-cross-period/runtime/benchmark_reports/codex-review-20260705-cross-period-api-local-continuous-replay.json`

## Full Test Script

- Path: [scripts/run_v2_full_container_audit_suite.sh](/home/qcrs/statebus/project/scripts/run_v2_full_container_audit_suite.sh)
- Purpose:
  - run full repo pytest inside the container
  - run `runtime.smoke`
  - run all four preflight combinations
  - pick the strongest available mode automatically
  - run formal + compare in the selected primary mode
  - run replay-negative audit
  - try full replay collection first, then fall back to single replay families and `deterministic + local` replay if needed
  - persist `status.tsv`, `summary.md`, `summary.json`, and per-stage console logs
- Key design choice:
  - every benchmark stage uses an isolated runtime/workspace/socket namespace to avoid cleanup races and cross-stage contamination

## Recommended Next Moves

1. Keep using the new audit script for full verification instead of ad hoc shared-root reruns.
2. Reword public-facing replay language from "validated replay" toward "validated downgraded reuse" or equivalent.
3. Expand the formal family beyond single-metric table retrieval if broader claim surface is required.
4. If benchmark-mainline systems claims are important, add a formal subprocess-transport or memfd-backed benchmark lane instead of relying on capability/tests alone.
