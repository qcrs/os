## P1-3 Replay Target Round Verification

Date: 2026-07-08
Branch: `feat/local-hidden-kv-prototype`
Plan item: `P1-3`

Current branch status:

- No additional code change was required after the prior replay fixes already present on this branch.
- This note records the verification evidence needed for the standalone `P1-3` commit once `.git` becomes writable again.

Authoritative live artifact:

- `/home/qcrs/statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-continuous-replay.json`

Observed replay-headline evidence for `long_doc_metric_replay_v1`:

- `eligible_for_replay_headline = true`
- `replay_gate_reason = ""`
- `headline_scope = replay_admissible`
- `expected_target_rounds = [3, 4, 5, 6, 7, 8, 9, 10]`
- `missing_target_rounds = []`
- `unexpected_target_rounds = []`
- `validated_target_rounds = [3, 4, 6, 8, 9]`
- `exact_target_rounds = [5, 7, 10]`
- `L3_validated_replay_count = 5.0`
- `L3_exact_replay_count = 3.0`

Repo-local regression coverage already present on the branch:

- `tests/v2/test_continuous_runner.py`
- `test_continuous_runner_executes_replay_family`
- `test_continuous_runner_executes_replay_collection`

Verification intent:

- This plan item is treated as verification-only on the current branch.
- The future `P1-3` commit can therefore be a narrow evidence commit that records this verification without changing runtime code paths.
