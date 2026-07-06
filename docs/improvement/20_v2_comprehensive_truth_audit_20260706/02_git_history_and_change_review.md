# Git History And Change Review

Commands reviewed:

- `git status -sb`
- `git log --oneline --decorate -n 50`
- `git log --oneline --decorate -- docs/improvement docs/reports docs/contracts v2 tests/v2 scripts | sed -n '1,200p'`
- `git show --stat --oneline HEAD`
- `git show --stat --oneline HEAD~1`
- `git show --stat --oneline HEAD~2`
- `git show --stat --oneline HEAD~3`
- `git diff --stat`
- `git diff --check`

## Current branch and tag

`HEAD` at audit start:

```text
3738f34 (HEAD -> feat/statebus-v2-container-runtime, tag: v2-claim-upgrade-20260706) Fix state pool backend fallback observability
```

The tag `v2-claim-upgrade-20260706` points at the state-pool observability fix commit before this audit's new follow-up commit.

## Key recent commits

### `3738f34 Fix state pool backend fallback observability`

Type: real code fix plus tests.

Changed:

- `v2/state/store.py`
- `tests/v2/test_minimal_benchmark.py`
- `tests/v2/test_state_materialization.py`

Resolution: real fix. `LayeredStateStore.backend_name` now reports the last or prior actual storage backend after a handle is released. Fresh formal runs confirmed `state_pool_mode_used` is real for shared memory and memfd.

Limit: memfd unavailable fallback is still not proven on a real no-memfd host.

### `5a44fea Update v2 claim upgrade documentation`

Type: documentation and safe-claim update.

Changed:

- `docs/improvement/19_claim_upgrade_completion_report_20260706.md`
- `docs/improvement/artifacts/17_final_system_audit/17f_safe_claim_language.md`
- selected report guides.

Resolution: mostly appropriate. It explicitly avoids formal external superiority. This audit adds a CodeAct historical warning to `docs/reports/v2_experiment_summary_20260703.md`.

Limit: documentation cannot substitute for formal external compare evidence.

### `e20b8e9 Implement v2 claim upgrade benchmark support`

Type: real implementation plus tests plus sample assets.

Changed:

- `scripts/run_v2_full_container_audit_suite.sh`
- `tasks/formal/*`
- `v2/benchmark/task_registry.py`
- benchmark runners and state store
- tests

Resolution: real implementation of the 25-case, 5-family formal registry and `--state-pool-mode` plumbing.

Limit: `tasks/formal/*/validator.py` helper files are not the primary runner validation path; actual quality gating uses `expected_facts` in `v2/runtime/smoke.py`.

### `4692c93 Add execution prompt for claim upgrade plan`

Type: prompt/documentation only.

Resolution: useful as work instruction only. It does not prove implementation.

## Worktree at audit start

Pre-existing user changes:

- `M docs/improvement/PROMPT_FOR_CLAIM_UPGRADE_EXECUTION.md`
- `?? docs/improvement/PROMPT_FOR_V2_COMPREHENSIVE_TRUTH_AUDIT.md`

Audit-created changes:

- replay metric code and test fix.
- CodeAct historical-report wording fix.
- new comprehensive audit directory and benchmark artifacts.

## Over-interpretation guard

Do not infer from recent commits that:

- formal external API comparison was rerun.
- realtime LLM code generation is part of the current formal benchmark.
- deterministic formal results prove API mode behavior.
- container activation works.
- openEuler VM validation occurred.
