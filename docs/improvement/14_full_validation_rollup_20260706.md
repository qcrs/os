# StateBus v2 Full Validation Rollup

- Date: 2026-07-06
- Branch: `feat/statebus-v2-container-runtime`
- Commit: `f3dd0944eb5e6bbafc88d79eb2db24e0451b8a3e`
- Container: `statebus-dev-qcrs`
- Activation: `/usr/local/bin/activate_statebus_container.sh`
- Project root: `/workspace/statebus/project`
- Canonical full-audit result root: `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331`

## Scope

This report consolidates:

1. the original full audit run
2. the failed-stage rerun
3. the earlier strong-evidence ad hoc runs already used in `12_independent_codex_full_audit.md`
4. the final post-rerun status that should now be treated as the canonical validation snapshot

It supersedes the fragmented view across:

- `docs/improvement/12_independent_codex_full_audit.md`
- `docs/improvement/13_review_followup_and_full_test_script.md`
- `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/summary.latest.*`

## Final Status

- Final stage count: `16`
- Final failed stage count: `0`
- Failed-stage rerun count: `3`
- Canonical latest summary:
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/summary.latest.md`
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/summary.latest.json`
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/status.latest.tsv`
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/rerun_status.tsv`

## Executive Conclusions

1. The full validation bundle is now green end to end. The original failed stages were fixed and rerun successfully; there are no remaining failed stages in the canonical latest status.
2. The strongest replay claim is now materially stronger than in `12_independent_codex_full_audit.md`, because full `continuous-replay` collection evidence now exists in `api + local`, not only in `deterministic + local` or single-family reruns.
3. The original rerun failures were script/environment issues, not benchmark semantics issues:
   - `10_continuous_replay_collection_primary` and `14_continuous_replay_collection_det_local_fallback` failed due to overlong AF_UNIX socket paths.
   - `15_flagship_ablation_primary` failed due to timeout budget being too short for the actual workload.
4. Those failures were fixed by shortening socket paths and increasing flagship timeout in the audit scripts. The benchmark paths themselves then completed successfully.
5. The strongest currently defensible claims are:
   - typed control + semantic pruning reduce prompt/control exposure
   - semantic state transfer is real and benchmark-active
   - replay/reuse is real in `api + local` full collection, not only in deterministic fallback
6. The strongest claims that still require careful wording are unchanged:
   - formal suite breadth remains narrow
   - compare suite is still dev-only fairness/efficiency evidence, not broad superiority proof
   - flagship ablation still shows non-uniform family behavior, not universal state-transfer win

## Evidence Availability Matrix

| Path | Final status | Evidence tier | Role in conclusions |
| --- | --- | --- | --- |
| `api + local` preflight | pass | strong | environment confirmation |
| `api + local` formal | pass | strong | formal ladder evidence |
| `api + local` compare | pass | strong | external fairness/efficiency evidence |
| `api + local` continuous-replay collection | pass after rerun | strong | strongest replay collection evidence |
| `api + local` flagship ablation | pass after rerun | strong | non-text state stress evidence |
| `api + local` replay single-family reruns | pass | strong | family-level replay confirmation |
| `deterministic + local` continuous-replay collection | pass after rerun | medium | fallback consistency check |
| `api + deterministic` preflight | pass | medium | mode availability check |
| `deterministic + deterministic` preflight | pass | weak | lowest-tier fallback only |

## Test And Smoke Results

### Full Pytest

- Command class: full repo `pytest -q` inside container
- Result: `504 passed, 101 warnings in 981.50s (0:16:21)`
- Canonical log:
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/01_pytest_full/console.log`

### Runtime Smoke

- Result: pass
- Notable lines:
  - `statebus smoke ok: mode=text ... control_bytes=243456.0 task_ms=5935.02`
  - `statebus smoke ok: mode=protocol ... control_bytes=215901.0 task_ms=5353.99`
  - `statebus comparator artifact ok: external_claim_surface=formal_ready api_repeat1_ready=True`
- Canonical log:
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/02_runtime_smoke/console.log`

## Original Full Audit Run

### Successful On First Pass

The following stages passed before any rerun:

- `00_env_probe`
- `01_pytest_full`
- `02_runtime_smoke`
- `03_preflight_api_local`
- `04_preflight_api_deterministic`
- `05_preflight_deterministic_local`
- `06_preflight_deterministic_deterministic`
- `07_formal_primary`
- `08_compare_primary`
- `09_replay_negative_primary`
- `11_continuous_replay_cross_period_primary`
- `12_continuous_replay_csv_primary`
- `13_continuous_replay_long_doc_primary`

### Failed On First Pass

The following stages initially failed:

- `10_continuous_replay_collection_primary`
- `14_continuous_replay_collection_det_local_fallback`
- `15_flagship_ablation_primary`

## Failed-Stage Rerun

### Rerun Scope

Only the failed stages were rerun. Successful stages were not rerun.

Rerun record:

- `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/rerun_status.tsv`

Rerun stage outcomes:

- `10_continuous_replay_collection_primary`: `0`
- `14_continuous_replay_collection_det_local_fallback`: `0`
- `15_flagship_ablation_primary`: `0`

### Root Causes And Fixes

#### 1. `continuous-replay` collection socket-path failure

Initial failure:

- `OSError: AF_UNIX path too long`

Why it happened:

- the audit script generated a long stage-level socket path
- `continuous_runner` then appended family / layer / round suffixes
- the derived AF_UNIX path crossed Linux path-length limits

Fix:

- use a short hash-based socket basename in the audit scripts

Impact:

- this was a runner/script isolation problem
- it did not demonstrate a semantic benchmark failure

#### 2. `flagship-ablation` timeout failure

Initial failure:

- stage exited `124`

Why it happened:

- the default timeout budget was too aggressive for the actual flagship workload

Fix:

- increase flagship timeout in the audit scripts

Impact:

- again, this was a harness-budget problem, not evidence of benchmark invalidity

## Canonical Final Stage Matrix

| Stage | Final status | Notes |
| --- | --- | --- |
| `00_env_probe` | pass | environment sanity |
| `01_pytest_full` | pass | full repo regression |
| `02_runtime_smoke` | pass | smoke + comparator artifact |
| `03_preflight_api_local` | pass | strong mode available |
| `04_preflight_api_deterministic` | pass | medium mode available |
| `05_preflight_deterministic_local` | pass | medium mode available |
| `06_preflight_deterministic_deterministic` | pass | weak fallback available |
| `07_formal_primary` | pass | strong formal evidence |
| `08_compare_primary` | pass | strong compare evidence |
| `09_replay_negative_primary` | pass | replay negative audit |
| `10_continuous_replay_collection_primary` | pass after rerun | strong replay collection evidence |
| `11_continuous_replay_cross_period_primary` | pass | strong single-family replay evidence |
| `12_continuous_replay_csv_primary` | pass | strong single-family replay evidence |
| `13_continuous_replay_long_doc_primary` | pass | strong single-family replay evidence |
| `14_continuous_replay_collection_det_local_fallback` | pass after rerun | medium replay fallback evidence |
| `15_flagship_ablation_primary` | pass after rerun | strong flagship evidence |

## Key Benchmark Results

### Strong Formal Evidence

Canonical full-audit report:

- `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/07_formal_primary/stdout.json`

Key metrics:

- `L0_case_count = 8`
- `L3_quality_floor_pass_count = 8`
- `control_bytes_delta_l0_to_l1 = 360`
- `pruning_bytes_saved_vs_l0 = 6255`
- `L2_semantic_state_transfer_count = 8`
- `L3_reuse_gain = 0`

Interpretation:

- formal quality still holds under the strongest mode
- prompt/control savings attribution remains mostly about pruning, not pure structured carrier overhead
- formal still proves precision anchor behavior better than broad reasoning breadth

Reference earlier strong report:

- `/statebus/runs/v2-live/runtime/benchmark_reports/codex-repair-20260705-formal-api-local-formal-suite.json`

### Strong Compare Evidence

Canonical full-audit report:

- `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/08_compare_primary/stdout.json`

Key metrics:

- `comparison_valid = true`
- `formal_efficiency_claim_allowed = 0`
- `api_llm_total_tokens_delta = -1048`
- `api_control_bytes_delta = -465`
- `api_prompt_bytes_delta = -5056`
- `api_task_ms_delta = +13277.776363`
- `api_system_overhead_ms_delta = +10202.148287`

Interpretation:

- StateBus still wins on token/control/prompt exposure
- StateBus still does not win on end-to-end time in this comparison path
- compare remains useful fairness evidence, not speed-superiority evidence

Reference earlier strong report:

- `/statebus/runs/v2-live/runtime/benchmark_reports/codex-repair-20260705-compare-api-local-cold-start-compare.json`

### Strong Replay Collection Evidence

Canonical full-audit report:

- `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/10_continuous_replay_collection_primary/stdout.json`

Mode:

- `role_path_mode = api`
- `embedding_mode = local`

Collection metrics:

- `family_count = 3`
- `continuous_round_count = 30`
- `replay_target_round_count = 20`
- `replay_observed_round_count = 20`
- `replay_missing_target_round_count = 0`
- `replay_unexpected_round_count = 0`
- `validated_replay_count = 17`
- `exact_replay_count = 3`
- `L2_semantic_state_transfer_count = 30`
- `L3_artifact_reuse_count = 39`
- `L3_reuse_gain = 20`

Interpretation:

- the strongest replay headline is now supported by full collection evidence in `api + local`
- replay is no longer limited to deterministic fallback evidence
- collection-level admissibility and target-round coverage are now fully exercised under the strongest practical mode

Medium fallback confirmation:

- `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/14_continuous_replay_collection_det_local_fallback/stdout.json`
- the deterministic+local fallback produced the same aggregate replay counts:
  - `validated_replay_count = 17`
  - `exact_replay_count = 3`
  - `replay_target_round_count = 20`
  - `replay_observed_round_count = 20`

### Strong Single-Family Replay Evidence

Canonical reports:

- `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/11_continuous_replay_cross_period_primary/stdout.json`
- `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/12_continuous_replay_csv_primary/stdout.json`
- `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/13_continuous_replay_long_doc_primary/stdout.json`

Headline facts:

- `cross_period_financial_v1`
  - `replay_target_round_count = 4`
  - `replay_missing_target_round_count = 0`
  - `replay_unexpected_round_count = 0`
- `csv_correlation_replay_v1`
  - `replay_target_round_count = 8`
  - `replay_missing_target_round_count = 0`
  - `replay_unexpected_round_count = 0`
- `long_doc_metric_replay_v1`
  - `replay_target_round_count = 8`
  - `replay_missing_target_round_count = 0`
  - `replay_unexpected_round_count = 0`

Interpretation:

- each supported replay family now has a clean strong-mode path
- this reduces the risk that collection success is hiding a weak individual family

### Strong Flagship Ablation Evidence

Canonical report:

- `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/15_flagship_ablation_primary/stdout.json`

Mode:

- `role_path_mode = api`
- `embedding_mode = local`

Core non-text-state stress metrics:

- `stress_family_count = 6`
- `stress_pass_family_count = 4`
- `total_llm_prompt_saved_by_state_ref_bytes = 22208`
- `total_prompt_visible_saved_by_state_ref_bytes = 8409`
- `top_prompt_visible_saving_family = csv_correlation_replay_v1`

Family-level interpretation:

- clear positive families:
  - `csv_correlation_replay_v1`
  - `csv_table_profile_v1`
  - `cross_period_financial_v1`
  - `long_doc_table_v1`
- still not uniformly positive:
  - `long_doc_metric_replay_v1`
  - `incident_diagnosis_v2`

Interpretation:

- the strongest fair wording is not "non-text state always wins"
- the strongest fair wording is "non-text state produces meaningful prompt savings on several important families, but gains are family-sensitive"

## What Changed Relative To `12_independent_codex_full_audit.md`

### Upgraded

1. Replay collection strongest evidence has been upgraded.
   - Old state: strong full collection missing; only medium collection or strong single-family evidence was available.
   - New state: strong full collection exists in `api + local`.
2. Full validation bundle is now fully green.
   - Old state: three audit stages still failed.
   - New state: no failed stages remain.

### Unchanged

1. Formal family narrowness remains true.
2. Compare suite still does not support "StateBus is faster".
3. `validated replay` naming remains more aggressive than the runtime semantics.
4. Capability-vs-benchmark-mainline distinction still matters for subprocess transport / memfd / persistent mmap narratives.

## Recommended Canonical Claim Set

### Safe Strong Claims

1. `api + local` formal and compare paths are validated in the container.
2. `api + local` continuous replay collection is validated end to end.
3. semantic state transfer is benchmark-active and visible in both replay and flagship evidence.
4. StateBus reduces prompt/control exposure versus text baselines in validated benchmark paths.

### Claims To Keep Qualified

1. "StateBus is faster than external baseline"
   - not supported
2. "non-text state helps all families"
   - not supported
3. "validated replay is generic safe answer restoration"
   - not supported by current semantics
4. "formal suite proves broad open-ended reasoning superiority"
   - not supported by current task design

## Canonical File Set

Use these as the final source bundle:

- Full audit latest summary:
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/summary.latest.md`
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/summary.latest.json`
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/status.latest.tsv`
- Failed-stage rerun record:
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/rerun_status.tsv`
- Strong formal:
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/07_formal_primary/stdout.json`
- Strong compare:
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/08_compare_primary/stdout.json`
- Strong replay collection:
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/10_continuous_replay_collection_primary/stdout.json`
- Strong replay single-family evidence:
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/11_continuous_replay_cross_period_primary/stdout.json`
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/12_continuous_replay_csv_primary/stdout.json`
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/13_continuous_replay_long_doc_primary/stdout.json`
- Medium replay fallback:
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/14_continuous_replay_collection_det_local_fallback/stdout.json`
- Strong flagship:
  - `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/15_flagship_ablation_primary/stdout.json`

## Bottom Line

The current state is materially better than the one described in `12_independent_codex_full_audit.md`.

The decisive improvement is not another test passing in isolation. It is that the full replay collection now passes in the strongest practical mode, the failed audit stages have been rerun cleanly, and the canonical validation bundle is now fully green. The remaining caveats are mostly about claim discipline and benchmark scope, not about the audit harness still being broken.
