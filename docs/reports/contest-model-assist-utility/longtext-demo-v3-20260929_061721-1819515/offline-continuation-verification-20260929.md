# Offline Continuation Verification

This note supplements the live-run artifacts. It does not alter `summary.json`, archived slots, runtime traces, or service recovery records.

## Workspace state

The checkout is on branch `experiment/contest-model-assist-20260928`. The observed worktree contains modified runtime files and untracked utility implementation/report artifacts; they were left intact. No branch switch or worktree cleanup was performed.

## Offline checks

- The Executor prompt now states that `filter_in` uses `arguments.column` and plural-array `arguments.values`; the focused contract test checks the wording and example.
- Targeted tests passed: `31 passed` across `test_model_assist_utility.py`, `test_model_assist_utility_runner.py`, and `test_model_assist_utility_runtime.py`.
- `bash -n scripts/experiments/contest_model_assist/run_utility_suite.sh` and `git diff --check` passed.
- Prepare passed for all four cases with necessity checks. Its output is `prepare-longtext-demo-v3-20260929_070046-1935453`.
- Formal dry-run passed with 28 planned scored positions: 8 APC, 12 Logit, and 8 KV; the plan groups 20 positions on standard and 8 on KV.
- Host and `statebus-runtime` imports resolve the utility modules from the current `/home/qcrs/statebus/os` checkout and its `/workspace/statebus/os` bind mount.

## Live gate outcome

The preserved run remains `incomplete_gate` with `demo_completed=false`. Its 12 Logit positions are marked unavailable because exact extraction returned `completion_token_bytes_mismatch`; no proxy probability was substituted. APC and KV each have zero scored positions, and the remaining 16 APC/KV positions did not start after their calibration quality gates failed. The archived executor output used singular `filter_in.value`; the prompt fix above was made after the allowed four extra targeted retry positions had been consumed, so it has only offline test evidence and was not sent to the model.

The detailed counts and failures remain in `summary.json`, `resume-01-diagnosis.md`, `slots/archive/`, and the runtime artifacts. This note does not characterize the 28-position demonstration as complete or claim a utility benefit.

## Service recovery

The run-owned KV manager stop is recorded in `service/kv-stop.json`. `service/restore-evidence.json` records `standard_restored=true`; the restored standard manager was PID `1911578`, mode `standard`, and passed manager health, model presence, tokenize, and raw-logprobs checks. The current manager status also reports that PID and healthy `/health` endpoint.
