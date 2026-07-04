# StateBus v2 Update Validation Readout 2026-07-04

## Scope

This note consolidates the 2026-07-04 update-validation runs into one analysis document for later judgment and issue triage.

Authoritative artifact roots:

- full validation base: `/home/qcrs/statebus/runs/v2-update-validation-20260704_145038`
- failed-stage rerun: `/home/qcrs/statebus/runs/v2-update-rerun-20260704_160710`
- flagship-only rerun: `/home/qcrs/statebus/runs/v2-update-rerun-20260704_170948`

Final all-stage status should be read from:

- `/home/qcrs/statebus/runs/v2-update-rerun-20260704_170948/status.tsv`

Headline metrics should primarily be read from:

- `/home/qcrs/statebus/runs/v2-update-rerun-20260704_160710/summary.md`

The flagship ablation final result should be read from:

- `/home/qcrs/statebus/runs/v2-update-rerun-20260704_170948/json/16_flagship_ablation.json`

## Final Status

After rerunning only failed stages, all 17 stages ended with `exit=0`.

Stage provenance:

| Stage group | Final source run | Status |
| --- | --- | --- |
| `00`-`08` | `v2-update-validation-20260704_145038` | pass |
| `09`, `10`, `14` | `v2-update-rerun-20260704_160710` | pass |
| `11`, `12`, `13`, `15` | `v2-update-validation-20260704_145038` | pass |
| `16` | `v2-update-rerun-20260704_170948` | pass |

Regression gate:

- `pytest`: `194 passed`
- replay negative audit: `7/7 pass`

## Key Metrics

### Formal Compare

Source:

- `/home/qcrs/statebus/runs/v2-update-validation-20260704_145038/json/04_formal_compare.json`

Observed metrics:

| Metric | Value |
| --- | --- |
| `formal_superiority_claim_allowed` | `True` |
| `formal_efficiency_claim_allowed` | `True` |
| StateBus quality floor pass count | `8` |
| External quality floor pass count | `6` |
| `quality_delta` | `+2` |
| `tokens_delta` | `-825` |
| `bytes_delta` | `-11054` |
| `net_llm_ms_delta` | `+15160.707293 ms` |
| `system_overhead_ms_delta` | `+12878.87071 ms` |
| `task_ms_delta` | `+28039.578003 ms` |

Important gate state:

- `mode_reports[0].comparison_valid = false`
- `invalid_reason = "quality_floor_gate_failed"`
- `formal_headline_eligible = false`
- `fixed_answer_external_comparison_valid = false`
- `claim_restriction = "external_compare_debug_only_until_four_role_fairness_gate_passes"`

Interpretation:

- The current artifact supports an efficiency-style debug readout and shows StateBus quality ahead of the external comparator.
- It does **not** support a clean formal external-headline claim yet, because the fairness/comparison gate is still not fully satisfied.

### Dev Compare

Source:

- `/home/qcrs/statebus/runs/v2-update-validation-20260704_145038/json/06_dev_compare_coldstart.json`

Observed metrics:

| Metric | Value |
| --- | --- |
| `mode_comparison_valid` | `true` |
| `quality_delta` | `0` |
| `tokens_delta` | `-1134` |
| `bytes_delta` | `-5056` |
| `net_llm_ms_delta` | `+301.178936 ms` |
| `system_overhead_ms_delta` | `+7212.383164 ms` |
| `task_ms_delta` | `+7513.5621 ms` |
| `codeact_execution_stage_ms_delta` | `null` |

Interpretation:

- Dev compare passes and still shows token and byte savings.
- The intended `codeact_execution_stage_ms` delta is not present in this artifact, so the claimed `>=30%` CodeAct execution-stage reduction is not proven by the current report set.

### Replay / Memory

Dev replay-ready source:

- `/home/qcrs/statebus/runs/v2-update-validation-20260704_145038/json/08_statebus_dev_replay_ready.json`

Observed metrics:

| Metric | Value |
| --- | --- |
| `L3_quality_floor_pass_count` | `3` |
| `L3_reuse_gain` | `3` |
| `L2_semantic_state_transfer_count` | `3` |
| `L3_skipped_step_count` | `null` |

Note:

- This artifact does not expose the full skipped-step headline directly in the summary fields used by the wrapper script.
- The stronger replay evidence comes from the continuous suites and `incident_diagnosis_v2`.

Continuous collection source:

- `/home/qcrs/statebus/runs/v2-update-rerun-20260704_160710/json/09_continuous_collection.json`

Observed metrics:

| Metric | Value |
| --- | --- |
| `L3_history_reuse_gain` | `11` |
| `validated_replay_count` | `3` |
| `exact_replay_count` | `6` |
| `eligible_for_replay_headline` | `false` |

Continuous replay collection source:

- `/home/qcrs/statebus/runs/v2-update-rerun-20260704_160710/json/10_continuous_replay_collection.json`

Observed metrics:

| Metric | Value |
| --- | --- |
| `L3_history_reuse_gain` | `7` |
| `validated_replay_count` | `16` |
| `exact_replay_count` | `9` |
| `replay_missing_target_round_count` | `1` |
| `eligible_for_replay_headline` | `false` |
| `eligible_for_quality_headline` | `false` |

Interpretation:

- Replay is working and strongly exercised.
- Collection-level replay headline eligibility is still blocked by at least one target-round miss.

### `incident_diagnosis_v2`

Source:

- `/home/qcrs/statebus/runs/v2-update-validation-20260704_145038/json/13_incident_diagnosis_v2.json`

Observed metrics:

| Metric | Value |
| --- | --- |
| `validated_replay_count` | `2` |
| `exact_replay_count` | `7` |
| `skipped_step_count` | `16` |
| `eligible_for_replay_headline` | `true` |
| `replay_gate_reason` | `""` |

Interpretation:

- The standalone `incident_diagnosis_v2` family behaves well and remains a good replay demonstration family.
- This is stronger than the collection-level replay admissibility readout for the same family.

### CodeAct Acceptance

Source artifact:

- `/home/qcrs/statebus/runs/v2-update-validation-20260704_145038/json/11_codeact_acceptance.json`

Artifact-reported values:

| Metric | Value |
| --- | --- |
| `reported_success_count` | `0` |
| `reported_total_runs` | `5` |

Derived actual values from the same artifact payload:

| Metric | Value |
| --- | --- |
| non-log run count | `5` |
| derived actual success count | `5` |
| target (`>=3/5`) | `met` |

Interpretation:

- Real acceptance outcome is `5/5`.
- The `0/5` headline in the original summary is a script/statistics bug, not a model regression.

### Flagship Non-Text Ablation

Source:

- `/home/qcrs/statebus/runs/v2-update-rerun-20260704_170948/json/16_flagship_ablation.json`

Observed summary:

| Metric | Value |
| --- | --- |
| `claim_level` | `first_pass_with_diagnostic_text_controls` |
| `role_path_mode` | `api` |
| `stress_family_count` | `6` |
| `stress_pass_family_count` | `4` |
| `total_llm_prompt_saved_by_state_ref_bytes` | `19247` |
| `total_prompt_visible_saved_by_state_ref_bytes` | `7050` |
| strongest prompt-visible-saving family | `csv_correlation_replay_v1` |
| strongest prompt-visible saving | `5658 bytes` |

Fixed-answer external debug comparator inside flagship:

| Metric | Value |
| --- | --- |
| `comparison_valid` | `true` |
| `formal_superiority_claim_allowed` | `false` |
| `tokens_delta` | `-1081` |
| `bytes_delta` | `-5024` |

Interpretation:

- Flagship now completes successfully.
- Non-text state transfer produces real prompt savings on several families.
- The strongest evidence is in the long/table replay families, not in every family.

## Diagnostics Bundles

- compare diagnostics bundle:
  `/statebus/runs/v2-update-rerun-20260704_160710/diagnostics/compare/v2-update-validation-20260704_145038-cold-start-compare-20260704_083810`
- runtime persistence bundle:
  `/statebus/runs/v2-update-validation-20260704_145038/diagnostics/runtime-persistence/statebus-v2-runtime-persistence-breakdown-20260704_071252`

## Problems And Caveats

### 1. Formal compare output is internally mixed

Observed facts:

- `formal_superiority_claim_allowed=True`
- `formal_efficiency_claim_allowed=True`
- `mode_comparison_valid=false`
- `formal_headline_eligible=false`
- claim restriction still says external fairness gate is not fully passed

Why this matters:

- These fields can easily be misread as “formal external superiority fully established”.
- The safer reading is: debug evidence is strong, but the external-fairness headline gate is still not closed.

### 2. CodeAct acceptance source artifact is numerically wrong

Observed facts:

- original artifact reports `success_count=0`
- the same payload contains five successful non-log runs with `generation_fallback_used=false`
- rerun summary correctly reconstructs it as `5/5`

Why this matters:

- Any later automation reading only the original `11_codeact_acceptance.json` can draw the wrong conclusion.

### 3. Rerun merge summary is not recursive

Observed facts:

- `v2-update-rerun-20260704_170948/summary.md` shows many headline fields as `None`
- this happens because its base run is itself a rerun bundle, and the merge logic does not recursively resolve prior-stage metrics

Why this matters:

- Final all-green status is correct.
- Final merged headline metrics are incomplete unless you read `160710` as the main summary layer.

### 4. `flagship_ablation` is still flaky on planner JSON formatting

Observed facts:

- first rerun failed with `json.decoder.JSONDecodeError`
- failure path:
  - `v2/runtime/role_path.py:744`
  - `runtime/llm.py:617`
- second isolated rerun passed

Why this matters:

- The benchmark is now passable by rerun.
- The underlying planner-output robustness issue is not actually fixed in code.

### 5. Replay collection headline is still blocked at collection level

Observed facts:

- `10_continuous_replay_collection` shows `validated_replay_count=16`, `exact_replay_count=9`
- but collection-level `eligible_for_replay_headline=false`
- `replay_missing_target_round_count=1`

Why this matters:

- Replay is functioning well in practice.
- The collection-level headline is still not clean enough for the strongest formal replay claim.

### 6. `incident_diagnosis_v2` behaves differently standalone vs collection

Observed facts:

- standalone family run shows `eligible_for_replay_headline=true`, `exact_replay_count=7`, `skipped_step_count=16`
- in the continuous replay collection evidence, `incident_diagnosis_v2` is the family that contributes replay gate friction

Why this matters:

- This is a real evaluation-surface inconsistency.
- It may be due to suite composition, history ordering, or admissibility gating rather than model quality itself.

### 7. P2 CodeAct stage-speed improvement is not proven by current artifacts

Observed facts:

- `codeact_execution_stage_ms_delta` is `null` in dev compare

Why this matters:

- You cannot honestly claim the `>=30%` CodeAct execution-stage reduction from the present report set.
- The optimization may exist in code, but it is not currently evidenced in the benchmark outputs.

## What Is Safe To Claim Now

- The updated validation suite is now operational end-to-end and all stages can be made green with targeted reruns.
- StateBus still shows prompt/token savings against the current comparators.
- StateBus still preserves or improves quality on the current compare artifacts.
- Replay and memory reuse are real, especially on `incident_diagnosis_v2` and the replay families.
- Non-text state transfer has measurable savings on several task families.
- CodeAct generation success is strong under the current prompt hardening and acceptance path.

## What Is Not Yet Safe To Claim

- Clean formal external pure-text superiority without fairness-gate caveats.
- Fully stable flagship execution with no planner-output fragility.
- Proven `>=30%` CodeAct execution-stage speedup from benchmark evidence.
- Universal non-text-state prompt savings on every family.

## Recommended Next Actions

1. Fix the rerun summary merge logic so nested reruns do not lose headline fields.
2. Fix the original CodeAct acceptance serializer so `success_count` is correct at the source artifact.
3. Harden planner JSON extraction or planner response format so `16_flagship_ablation` is not rerun-dependent.
4. Investigate why `incident_diagnosis_v2` is replay-eligible standalone but drags collection-level replay admissibility.
5. Add or restore `codeact_execution_stage_ms_delta` in compare artifacts if P2 speed claims matter.
