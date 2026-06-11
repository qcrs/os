# README 历史归档（2026-06-11）

这份文档保存较长版本 README 中仍然可能有参考价值的背景信息，避免主 README 继续承担过多历史说明。

## 仓库定位

This directory is the host-side development repo for the StateBus implementation.

Current strategy:

- Develop on the current Linux host.
- Use the isolated conda env under `$HOME/statebus/conda-envs/statebus_host`.
- Keep models, caches, logs, runs, and state artifacts under `$HOME/statebus`.
- Finish `Phase 0` to `Phase 4` here.
- Use openEuler VM only for posterior validation and final delivery checks.

## Branch Roles

Current branch roles after the realism/protocol hardening merge:

- `main`
  - active implementation mainline
  - this is the default branch for new work
  - currently includes both the host-side prototype baseline and the realism/protocol hardening work
- `feat/realism-protocol-hardening`
  - historical topic branch for the realism/protocol hardening push
  - currently points to the same head as `main`
  - keep it as a comparison/reference pointer unless the user explicitly wants to reopen that topic as a separate line
- `baseline/statebus-host-prototype-20260607`
  - historical snapshot of the contestized host-side prototype before realism hardening
  - use it for regression comparison, explanation, or archaeology
  - do not base new development on it unless the user explicitly asks

Short version:

- new work starts from `main`
- `feat/...` explains how the hardening happened
- `baseline/...` explains what existed before the hardening pass

## Current Scope

Current implementation focus:

- `runtime`
- `protocol`
- `statepool`
- `memory`
- `agents`
- `eval`

Deferred until later:

- `nsjail`
- privileged container workflows
- openEuler-only validation
- final sandbox isolation path

## Current Validation Snapshot

The repo keeps benchmark code, packs, and report-generation logic in git, but
does not commit local `runs/` artifacts. If you need the historical host-side
evidence trail, rebuild it locally or consult the summary/report documents under
`docs/reports/`, `docs/planning/`, and `docs/analysis/`.

Selected local evidence pointers from the current host-side work are listed
below for orientation only:

- `runs/comprehensive_eval_20260607_131113/`
- `runs/host_goal_eval_20260607_233858/`
- `runs/host_goal_eval_20260608_002101/`
- `runs/host_goal_eval_20260608_021820_runtime_exact_replay_det_repeat10/`
- `runs/host_goal_eval_20260608_022627_runtime_exact_replay_api_repeat10/`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`
- `runs/host_goal_eval_20260608_120619_executor_candidate_tool_refresh/`
- `runs/host_goal_eval_20260608_122921_exact_replay_drop_doc_preference_refresh/`
- `runs/host_goal_eval_20260608_124900_runtime_profile_trim_refresh/`
- `runs/host_goal_eval_20260609_085938_text_brief_fidelity_api_repeat10_serial/`
- `runs/host_goal_eval_20260610_113710_controlled_api_repeat3_serial/`

Current benchmark-pack split in the repo:

- `tasks/sample_benchmark.yaml`
  - unique frozen `formal_controlled` headline pack
- `tasks/contest_release_regression_carrier_benchmark.yaml`
  - `state_transfer_carrier`
- `tasks/state_transfer_authenticity_benchmark.yaml`
  - `state_transfer_authenticity`
- `tasks/state_transfer_pure_text_benchmark.yaml`
  - `state_transfer_pure_text`
- `tasks/state_transfer_natural_support_benchmark.yaml`
  - support-only natural free-text comparison
- `tasks/communication_benchmark.yaml`
  - `communication`
- `tasks/memory_benchmark.yaml`
  - `memory`
- `tasks/internal_regression_benchmark.yaml`
  - `internal_regression`
- `tasks/open_validation_benchmark.yaml`
  - support-only open validation pack

Headline status from the host-side evidence stack:

- host env is valid and `AF_UNIX` socket bind works
- `runtime.smoke` has a real module entry
- `nsjail` is still missing on the host
- Docker socket is not available to the current user
- current lane readout supports:
  - `communication`
  - `state_transfer` as typed-handoff authenticity
  - `memory` only at `replay_enabled / step-skipping`
