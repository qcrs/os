# 2026-07-09 local API non-KV follow-up deep analysis

本文分析 2026-07-08 晚到 2026-07-09 的 v2 local API non-KV 大规模实验与 follow-up。分析对象不是新实验，不包含 KV rerun，不包含 `local_vllm`，也不把 `exit=0` 直接等同于 claim 成立。

主要证据根：

- Core run: `/home/qcrs/statebus/runs/v2-local-api-non-kv-20260709_002546-core`
- Follow-up wrapper: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750`
- Follow-up lr01: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-lr01`
- Follow-up flagship: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-flagship`
- Follow-up failed-family diagnostics: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-flagship-families`
- Follow-up extras: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras`
- Follow-up audit artifact copy: `/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750`

辅助脚本：

- `/home/qcrs/statebus/project/scripts/analyze_v2_local_api_non_kv_followup_results.py`
- 机器汇总输出目录：`/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/deep_mining`
- 机器可读摘录：`/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/deep_mining/deep_mining_readout.md`

## 1. Executive Summary

这批实验总体完成了 non-KV local API follow-up 的主要取证目标：core 的 required lr01 硬失败被 follow-up lr01 单独重跑关闭，full flagship 跑通并暴露更严格的 family-level stress 结果，extras 基本跑完并补到了 shared_memory、memfd benchmark_balanced、subprocess、CodeAct、continuous collection/replay collection 等证据。

最重要的变化是：

- Core 里 `lr01_14_formal_compare_latency_rerun_api_local_memfd` 是 required failure，`stdout.json` 为空，`console.log` 是 external baseline retriever 空输出触发 `ValueError: expected json object in llm output: ''`。证据：`/home/qcrs/statebus/runs/v2-local-api-non-kv-20260709_002546-core/artifacts/stages/lr01_14_formal_compare_latency_rerun_api_local_memfd/console.log`。
- Follow-up lr01 同名 stage exit 0，旧的 external 空输出硬错误没有复现。证据：`/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-lr01/artifacts/stages/lr01_14_formal_compare_latency_rerun_api_local_memfd/stdout.json`。
- 但 follow-up lr01 仍不能支持 formal superiority 或 latency claim：`strict_equal_quality_comparison_valid=false`、`quality_superiority_comparison_valid=false`、`formal_superiority_claim_allowed=false`、`serialized_latency_superiority_claim_allowed=false/0`，`claim_restriction=external_compare_debug_only_until_strict_or_quality_gate_passes`。同一 JSON 里 StateBus quality 是 24/25，external 是 16/25，说明不是 strict equal quality，也没过 quality-superiority gate。
- Follow-up flagship exit 0，但 stress 只有 2/6 pass。能直接作为 StateRef prompt-saving 正例的是 `csv_table_profile_v1` 和 `csv_correlation_replay_v1`。`incident_diagnosis_v2` 有 StateRef prompt saving 但 quality headline 不 eligible；`cross_period_financial_v1` quality/replay eligible 但 T2 text same semantic selection 更省；`long_doc_metric_replay_v1` full flagship 失败但 isolated diagnostic 通过；`long_doc_table_v1` full flagship 新出现 `no_extra_state_ref_prompt_saving_vs_t2`，没有等价 isolated 诊断。
- Extras 的 `x17b_continuous_gridops_world_api_local` 是 optional failure，原因是 current continuous runner 不支持 `gridops_world_v1`，不是随机实验失败。证据：`/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x17b_continuous_gridops_world_api_local/console.log`。
- `No such exec instance` 没在扫描的 `console.log` 中命中；这次产物没有证据支持它影响 artifact 完整性。若终端末尾曾出现，只能先按收尾噪声处理。

可以保留进报告的证据：

- Core `r01_07_formal_compare_api_local_memfd` 支持 formal quality-superiority：StateBus 25/25，external 16/25，同时 prompt tokens delta -63268、LLM total tokens delta -67989。证据：`/home/qcrs/statebus/runs/v2-local-api-non-kv-20260709_002546-core/artifacts/stages/r01_07_formal_compare_api_local_memfd/stdout.json`。
- Formal internal non-KV 路径稳定：memfd loopback、memfd subprocess、shared_memory loopback、shared_memory subprocess 都有 25/25 L3 quality pass，且 semantic transfer/state transfer 生效。
- Continuous/replay 证明确有 memory/replay/reuse，不是只存在 StateRef：`x27` 有 history reuse/artifact reuse，`x28` 有 validated replay 18、exact replay 2、replay target 20 observed 19。
- CodeAct bwrap smoke 和 acceptance 通过：`x04c` bwrap ok，`x04d` 5/5 success。

不能保留为 claim 的内容：

- 不能把 lr01/follow-up latency rerun 写成 formal superiority；它只是 debug evidence。
- 不能 claim latency superiority。即使某些 serialized task delta 为负，claim gate 是 false，且 system overhead delta 仍为正。
- 不能 claim full flagship 6/6 或 universal StateRef prompt saving。
- 不能把 KV prefix/hidden-state 作为实际实验结果；本轮是 non-KV，KV 只能作为 future work 的 Engine-Local Prefix Reuse/estimate 口径。

## 2. Experiment Inventory

机器扫描覆盖 6 个 host run root，并把矩阵输出写回 audit artifact root。按 status 表统计，host run 阶段如下：

| Run | Stages | Required | Failed | Required failed | Optional failed | Duration s |
|---|---:|---:|---:|---:|---:|---:|
| core | 18 | 12 | 1 | 1 | 0 | 23553 |
| followup_lr01 | 1 | 1 | 0 | 0 | 0 | 1107 |
| followup_flagship | 1 | 1 | 0 | 0 | 0 | 7118 |
| followup_flagship_families | 1 | 1 | 0 | 0 | 0 | 3802 |
| followup_extras | 35 | 15 | 1 | 0 | 1 | 23882 |

Follow-up wrapper phase status:

| Phase | Exit | Meaning |
|---|---:|---|
| lr01 | 0 | Single serialized formal compare retry closed old hard failure |
| flagship | 0 | Full 6-family flagship rerun produced fresh stress evidence |
| flagship_family_diag | 1 | Stage process succeeded, but family diagnostic summary still had failed families |
| extras | 1 | Extras mostly succeeded; optional `x17b` unsupported family failed |

Important stage classes:

| Class | Stages | Interpretation |
|---|---|---|
| Required hard failure | core `lr01_14_formal_compare_latency_rerun_api_local_memfd` | External baseline empty output; fixed by follow-up rerun |
| Optional unsupported | extras `x17b_continuous_gridops_world_api_local` | Continuous runner does not support `gridops_world_v1` |
| Diagnostic nonzero phase | follow-up `flagship_family_diag` | Diagnostic found 2 failed families; not a process/log corruption |
| Required clean follow-up | lr01, flagship, flagship families stage body | These produced readable artifacts |

Machine scan counts from `deep_mining_summary.json`:

| File type | Count |
|---|---:|
| files scanned | 124157 |
| stage rows | 56 |
| phase rows | 4 |
| stage `stdout.json` | 48 |
| stage `console.log` | 56 |
| benchmark report JSON | 304 |
| benchmark evidence md | 78 |
| telemetry JSON | 2373 |
| prompt slice JSON | 9492 |
| artifact audit JSON | 2373 |
| hydration audit JSON | 2373 |
| artifact invalidation sidecars | 221 |
| memory commit sidecars | 2373 |
| hydration accounting audit JSON | 2373 |
| ref registry JSON | 2373 |
| JSON load errors | 2 |

The two JSON load errors are both empty stage `stdout.json` files: core lr01 and extras x17b. This matters because the rest of the benchmark reports, telemetry, audit sidecars, prompt slices, memory commits, and ref registries are readable; the failure is localized rather than broad artifact corruption.

The script also emitted these reusable matrices under the same `deep_mining` directory:

| Matrix | Rows |
|---|---:|
| `family_matrix.csv` | 66 |
| `prompt_token_byte_matrix.csv` | 46070 |
| `replay_reuse_matrix.csv` | 42329 |
| `state_transport_backend_matrix.csv` | 25101 |
| `runtime_overhead_matrix.csv` | 21765 |
| `quality_artifact_validation_matrix.csv` | 8398 |
| `failed_validator_cases.csv` | 277 |
| `claim_validity_matrix.csv` | 45 |
| `sidecar_artifact_matrix.csv` | 12086 |
| `error_taxonomy.csv` | 10 categories |

## 3. Data Mining Method

I first read the requested docs and scripts:

- `/home/qcrs/statebus/project/README.md`
- `/home/qcrs/statebus/project/docs/constraints/current_host_and_migration.md`
- `/home/qcrs/statebus/project/docs/constraints/current_feature_scope.md`
- `/home/qcrs/statebus/project/docs/planning/implementation_plan.md`
- `/home/qcrs/statebus/project/docs/reference/题目.md`
- `/home/qcrs/statebus/project/docs/improvement/README.md`
- `/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/13_artifact_mining_deep_analysis_20260708.md`
- `/home/qcrs/statebus/project/scripts/run_v2_local_api_non_kv_full_suite.sh`
- `/home/qcrs/statebus/project/scripts/run_v2_local_api_non_kv_followup_suite.sh`

Then I wrote `/home/qcrs/statebus/project/scripts/analyze_v2_local_api_non_kv_followup_results.py`. The script is read-only against experiment roots. It parses:

- `status.tsv`, `summary.json`, `summary.md`
- `artifacts/stages/*/stdout.json`
- `artifacts/stages/*/console.log`
- `runtime/**/benchmark_reports/*.json`
- `runtime/**/benchmark_reports/*.evidence.md`
- `work/**/benchmark_reports/*.json`
- `work/**/benchmark_reports/*.evidence.md`
- `workspaces/**/logs/telemetry.json`
- `workspaces/**/logs/artifact_audit.json`
- `workspaces/**/logs/hydration_audit.json`
- `workspaces/**/logs/prompt_slices/*.json`
- `runtime/**/sidecars/artifact_invalidations/*.json`
- `runtime/**/sidecars/memory_commits/*.json`
- `runtime/**/sidecars/hydration_accounting_audits/*.json`
- `runtime/**/registry/ref_registry.json`

The script extracts run/stage inventory, claim gates, family stress rows, replay/reuse rows, transport/backend rows, layer telemetry rows, prompt/hydration totals, artifact validation sidecars, error taxonomy, and runtime overhead buckets. It intentionally does not use a single hard-coded report schema: it recognizes `layers`, `waterfall_metrics`, `collection_summary`, `admissibility_summary`, `non_text_state_stress_summary`, `stress_summary`, `failed_family_summaries`, `mode_reports`, and nested compare reports.

Primary generated evidence files:

- `/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/deep_mining/deep_mining_summary.json`
- `/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/deep_mining/stage_inventory.csv`
- `/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/deep_mining/family_matrix.csv`
- `/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/deep_mining/claim_validity_matrix.csv`
- `/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/deep_mining/error_taxonomy.csv`
- `/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/deep_mining/state_transport_backend_summary.csv`

## 4. Failure Taxonomy

| Category | Count | Evidence | Meaning | Rerun value |
|---|---:|---|---|---|
| Required stage failure | 1 | `/home/qcrs/statebus/runs/v2-local-api-non-kv-20260709_002546-core/artifacts/stages/lr01_14_formal_compare_latency_rerun_api_local_memfd/console.log` | External retriever returned empty text; stdout empty | Already rerun successfully in follow-up |
| Optional stage failure | 1 | `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras/artifacts/stages/x17b_continuous_gridops_world_api_local/console.log` | Continuous runner unsupported family | Do not rerun until runner supports `gridops_world_v1` or stage is removed |
| JSON load error | 2 | core lr01 stdout, extras x17b stdout | Empty stdout, not broad artifact corruption | No blind rerun needed |
| Traceback / ValueError | 2 unique stages | core lr01 stage log; extras x17b stage log | Two unique failures: empty external JSON and unsupported family | Fix benchmark/runner paths first |
| Artifact invalidation | 221 sidecars | e.g. `/home/qcrs/statebus/runs/v2-local-api-non-kv-20260709_002546-core/work/r01_07_formal_compare_api_local_memfd/runtime/api/statebus/formal-trend-001/sidecars/artifact_invalidations/artifact-smoke.json` | Validator rejected candidate artifacts | Expected audit mechanism, not stage failure by itself |
| Docker cleanup noise | 0 matched logs | scanned `console.log` files | No evidence of artifact damage | Treat as external terminal cleanup noise unless reproduced |

Artifact validation sidecar totals:

| Metric | Count |
|---|---:|
| artifact audit records | 2373 |
| verified artifacts | 2152 |
| invalidated artifacts | 221 |
| invalidation reason | `validator_failed` = 221 |
| memory commits | 2373 |
| memory validation passed | 2152 |
| memory validation failed | 221 |
| answer adopted | 2152 |
| ref registry entries | 15353 |

This is important: `validator_failed` sidecars are not equivalent to failed benchmark stages. They show the validation/invalidation mechanism is active.

## 5. lr01 Deep Analysis

Core lr01:

- Stage: `lr01_14_formal_compare_latency_rerun_api_local_memfd`
- Exit: 1, required.
- `stdout.json`: 0 bytes.
- Console error: `ValueError: expected json object in llm output: ''`.
- Evidence: `/home/qcrs/statebus/runs/v2-local-api-non-kv-20260709_002546-core/artifacts/stages/lr01_14_formal_compare_latency_rerun_api_local_memfd/console.log`.

Follow-up lr01:

- Stage: same name.
- Exit: 0.
- Evidence: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-lr01/artifacts/stages/lr01_14_formal_compare_latency_rerun_api_local_memfd/stdout.json`.

Key metrics:

| Metric | Follow-up lr01 |
|---|---:|
| StateBus quality floor pass | 24 |
| External quality floor pass | 16 |
| strict equal-quality valid | false |
| quality-superiority valid | false |
| formal superiority allowed | false |
| serialized latency superiority allowed | false |
| formal external claim kind | `debug_only` |
| claim restriction | `external_compare_debug_only_until_strict_or_quality_gate_passes` |
| prompt tokens delta | -63088 |
| total tokens delta | -81991 |
| task ms delta | -92795.8 |
| LLM ms delta | -124997.3 |
| system overhead ms delta | +32201.5 |

Interpretation:

- The external empty-output hard error is fixed.
- The rerun is faster in task/LLM wall terms, and prompt/total tokens are lower.
- But StateBus is 24/25, not 25/25; claim gates remain false.
- The positive latency-looking delta is not claimable because serialized latency claim requires valid strict/formal gates. This stage is debug evidence, not headline evidence.

Historical comparison:

- Core `r01_07_formal_compare_api_local_memfd` supports quality-superiority: StateBus 25/25 vs external 16/25, prompt tokens -63268, total tokens -67989, formal claim kind `quality_superiority`.
- Core `lr02` and `lr03`, plus follow-up `lr01`, are all latency rerun/debug-only with StateBus 24/25 and formal gates false.
- The conflict is not an exit-code issue. It comes from compare object/gate differences and live API variability around one StateBus case/route/exact path.

## 6. Flagship Ablation Deep Analysis

Full follow-up flagship evidence:

- `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-flagship/artifacts/stages/r01_13_flagship_ablation_api_local/stdout.json`
- Nested report: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-flagship/work/r01_13_flagship_ablation_api_local/runtime/flagship-ablation/benchmark_reports/v2-local-api-non-kv-followup-20260709_083750-flagship-r01_13_flagship_ablation_api_local-non-text-flagship-ablation.json`

Stress summary:

| Metric | Value |
|---|---:|
| families | 6 |
| stress pass | 2 |
| stress fail | 4 |
| claimable non-text-state families | 2 |
| diagnostic-only families | 4 |
| total LLM prompt saved by StateRef bytes | 17702 |
| total visible prompt saved by StateRef bytes | 8437 |
| fail reasons | `no_extra_state_ref_prompt_saving_vs_t2`: 3; `quality_headline_not_eligible`: 2; `replay_headline_not_eligible`: 1 |

Per-family:

| Family | Claim tier | Scope | Stress | LLM delta L2 vs T2 | Visible delta L2 vs T2 | Quality eligible | Replay eligible | Interpretation |
|---|---|---|---|---:|---:|---|---|---|
| `csv_table_profile_v1` | formal_primary | history-backed | pass | -7979 | -5295 | true | false | Strong StateRef prompt-saving evidence |
| `csv_correlation_replay_v1` | formal_primary | replay-admissible | pass | -7109 | -6 | true | true | Valid replay family, small visible saving but clear LLM prompt saving |
| `incident_diagnosis_v2` | formal_secondary | not eligible | fail | -2614 | -3136 | false | false | StateRef saves prompt, but quality/replay gates fail |
| `cross_period_financial_v1` | formal_secondary | replay-admissible | fail | +16390 | +16227 | true | true | T2 text same semantic selection dominates StateRef |
| `long_doc_metric_replay_v1` | formal_secondary | not eligible | fail | +31691 | +30955 | false | false | Full-run negative; isolated diag contradicts it |
| `long_doc_table_v1` | formal_secondary | history-backed | fail | +6321 | +5910 | true | false | New no-extra-saving negative, no isolated diag yet |

Family conclusions:

- `csv_table_profile_v1`: worth keeping as a clean StateRef prompt/visible saving case. It is not a replay headline family; read it as history-backed quality plus prompt saving.
- `csv_correlation_replay_v1`: worth keeping as replay-admissible StateRef evidence. Replay gate is clean and `x28` confirms 8/8 target replay observed.
- `incident_diagnosis_v2`: not claimable as quality headline. The mechanism saves prompt but hurts or fails quality gate. This points to benchmark/scoring or answer-stability work, not to more blind reruns.
- `cross_period_financial_v1`: quality and replay are good, but StateRef is not better than T2 text with same semantic selection. This is a controlled negative that should be kept as a boundary example.
- `long_doc_metric_replay_v1`: high-priority instability. Full flagship says no saving and gate failure; isolated diagnostic says pass with large saving. Needs reproducibility/debug, not broad repeat=3.
- `long_doc_table_v1`: current evidence says no extra StateRef prompt saving. Because it lacks isolated diagnostic, do not overgeneralize; keep as tentative negative.

## 7. Isolated Failed-Family Diagnostics

Evidence:

- Stage stdout: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-flagship-families/artifacts/stages/flagship_failed_family_diagnostics/stdout.json`
- Summary: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-flagship-families/artifacts/summary.json`
- Work summary: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-flagship-families/work/flagship_family_diagnostics/summary.md`

Diagnostic stress:

| Metric | Value |
|---|---:|
| families | 3 |
| stress pass | 1 |
| stress fail | 2 |
| claimable non-text-state families | 1 |
| diagnostic-only families | 2 |
| total LLM prompt saved bytes | 12888 |
| total visible saved bytes | 11899 |
| failed families | `incident_diagnosis_v2`, `cross_period_financial_v1` |

Per-family diagnostic:

| Family | Stress | LLM delta L2 vs T2 | Visible delta L2 vs T2 | Quality eligible | Replay eligible | Replay/reuse |
|---|---|---:|---:|---|---|---|
| `long_doc_metric_replay_v1` | pass | -10957 | -9434 | true | true | isolated pass; StateRef saves prompt |
| `incident_diagnosis_v2` | fail | -1931 | -2465 | false | false | L3 quality 7/10, validated replay 5, exact 4, skipped 13; gate reason `quality_gate_failed;missing_target_replay_rounds;missing_exact_target_rounds` |
| `cross_period_financial_v1` | fail | +14912 | +17973 | true | true | L3 quality 10/10, validated replay 4, exact 0, skipped 4; T2 dominates |

The `long_doc_metric_replay_v1` reversal is the most interesting diagnostic point. Full flagship failure and isolated diagnostic pass cannot both be turned into a clean headline. The likely causes are runner collection differences, history/runtime-root differences, live API variability, or T2/StateBus report pairing differences. Before rerunning broad suites, inspect the full-run and isolated report pairs:

- Full flagship report: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-flagship/work/r01_13_flagship_ablation_api_local/runtime/flagship-ablation/benchmark_reports/v2-local-api-non-kv-followup-20260709_083750-flagship-r01_13_flagship_ablation_api_local-non-text-flagship-ablation.json`
- Isolated long_doc_metric report is embedded in the diagnostic stdout and nested under `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-flagship-families/work/flagship_family_diagnostics/continuous_replay/long_doc_metric_replay_v1/`.

### 7.1 `long_doc_metric_replay_v1` full-vs-isolated diff

Evidence:

- Core full flagship stdout: `/home/qcrs/statebus/runs/v2-local-api-non-kv-20260709_002546-core/artifacts/stages/r01_13_flagship_ablation_api_local/stdout.json`
- Follow-up full flagship stdout: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-flagship/artifacts/stages/r01_13_flagship_ablation_api_local/stdout.json`
- Follow-up isolated diagnostic stdout: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-flagship-families/artifacts/stages/flagship_failed_family_diagnostics/stdout.json`

Stress/gate diff:

| Run/stage | Stress | Fail reasons | Quality eligible | Replay eligible | L2 vs T2 LLM prompt bytes | L2 vs T2 visible bytes | StateRef saved bytes | Interpretation |
|---|---|---|---|---|---:|---:|---:|---|
| Core full flagship `r01_13` | fail | `quality_headline_not_eligible`; `replay_headline_not_eligible` | false | false | -7528 | -6153 | 7528 / 6153 | StateRef saves prompt, but L3 quality/replay gate blocks headline |
| Follow-up full flagship `r01_13` | fail | `quality_headline_not_eligible`; `replay_headline_not_eligible`; `no_extra_state_ref_prompt_saving_vs_t2` | false | false | +31691 | +30955 | 0 / 0 | T2 same semantic selection beats L2; this is a new negative mode |
| Follow-up isolated diagnostic | pass | none | true | true | -10957 | -9434 | 10957 / 9434 | Strong diagnostic positive, but not a full-run headline until the contradiction is explained |

Layer-level metric diff:

| Run/stage | L2 prompt / visible | L2 quality | L2 state transfer | T2 prompt / visible | T2 quality | L3 prompt / visible | L3 quality | L3 replay/reuse | Readout |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| Core full flagship `r01_13` | 87275 / 54367 | 10/10 | 10 semantic, 10 SHM | 94803 / 60520 | 10/10 | 83357 / 53398 | 8/10 | validated 7, exact 1, skipped 9, artifact reuse 12 | Prompt saving exists, but replay/quality gate fails |
| Follow-up full flagship `r01_13` | 125403 / 90337 | 10/10 | 10 semantic, 10 SHM | 93712 / 59382 | 10/10 | 81246 / 54052 | 9/10 | validated 6, exact 2, skipped 10, artifact reuse 11 | L2 is abnormally larger than T2; L3 improves prompt and replay but headline summary is L2-vs-T2 plus quality/replay gated |
| Follow-up isolated diagnostic | 85974 / 53167 | 10/10 | 10 semantic, 10 SHM | 96931 / 62601 | 10/10 | 72914 / 48325 | 10/10 | validated 5, exact 3, skipped 11, artifact reuse 10 | All three gates align: prompt saving, quality, and replay |

The important attribution is not "long_doc_metric is good" or "long_doc_metric is bad"; it is that the family is sensitive to runner context. The follow-up full run changed the L2/T2 prompt relationship by roughly 42.6k bytes relative to the isolated diagnostic (`+31691` versus `-10957`). Because L2 quality remains 10/10 in both follow-up cases and semantic transfer count remains 10, the failure is unlikely to be a basic StatePool transport failure. The sharper suspects are prompt assembly/scaffolding, T2 pairing, selected-evidence packaging, history/runtime-root carryover, or live API output differences that affect L3 replay gate eligibility.

This table also separates mechanism evidence from claim evidence. Mechanism evidence is positive in all three rows: L2 has 10 semantic transfers and 10 shared-memory publishes. Claim evidence is unstable: full flagship does not allow the family headline, while isolated diagnostic does. The right next action is a targeted diff of prompt slices, report pairing, replay target rounds, artifact invalidations, and runtime roots for this family, not another broad repeat sweep.

## 8. Extras Deep Analysis

Extras stage coverage:

- Required setup and probes passed: `x00` env, `x01` py_compile, `x02` full non-KV pytest, `x03` runtime smoke, `x04` preflight, `x04b` import probe, `x04c` CodeAct bwrap smoke, `x04d` CodeAct acceptance.
- Design stages passed for six non-KV families plus `gridops_world_v1` design: `x05` to `x10b`.
- Dev baseline stages passed: `x11` to `x14`.
- Continuous family stages passed for supported families: `x15`, `x16`, `x17`, `x18`, `x19`, `x20`.
- `x17b` failed optional because continuous runner does not support `gridops_world_v1`.
- Formal backend stages passed: `x21`, `x22`, `x23`, `x23b`, `x24`, `x25`, `x26`.
- Collection stages passed: `x27`, `x28`.

CodeAct:

| Stage | Result |
|---|---|
| `x04c_codeact_bwrap_smoke` | `ok=true`, `bwrap_ok=true`, `codeact_bwrap_ok=true` |
| `x04d_codeact_acceptance_api` | `success_count=5`, `total_runs=5`, `target_met=true`, backend `bwrap` |

Formal backend matrix, L3:

| Stage | Backend | Transport | Quality | Prompt tokens | Total tokens | Semantic transfer | memfd transfer | SHM publish | Runtime ms | Control ms |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| core `r01_05` | memfd | loopback | 25 | 52743 | 110360 | 25 | 25 | 0 | 1275.0 | 58.8 |
| core `r01_14` | memfd | subprocess | 25 | 52719 | 110524 | 25 | 25 | 0 | 4141.4 | 2778.9 |
| extras `x21` | shared_memory | loopback | 25 | 52732 | 113676 | 25 | 0 | 25 | 1170.8 | 58.2 |
| extras `x23b` | shared_memory | subprocess | 25 | 52685 | 115512 | 25 | 0 | 25 | 4066.8 | 2763.3 |
| extras `x24` | memfd | loopback | 25 | 52739 | 112731 | 25 | 25 | 0 | 1155.1 | 47.4 |

Interpretation:

- memfd and shared_memory both work for formal 25/25.
- Subprocess transport works but has much higher control/runtime overhead than loopback.
- Backend formal internal evidence is strong for mechanism coverage, not superiority by itself.

Formal compare extras:

| Stage | Backend | Gate | Quality | Tokens | Timing | Claim |
|---|---|---|---|---|---|---|
| `x23_formal_compare_api_local_shared_memory` | shared_memory | strict=false, quality=false | StateBus 24, external 16 | prompt -63163, total -46338 | task +96601 ms, overhead +34694 ms | debug-only |
| `x26_formal_compare_api_local_memfd_benchmark_balanced` | memfd | strict=false, quality=false | StateBus 24, external 16 | prompt -63331, total -77127 | task -70220 ms, overhead +32709 ms | debug-only |

These are useful diagnostics, but not formal claims. The output explicitly restricts them with `external_compare_debug_only_until_strict_or_quality_gate_passes`.

Continuous collection:

| Stage | Families | Rounds | Replay target | Replay observed | Validated replay | Exact replay | L3 reuse gain | History reuse gain |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `x27_continuous_collection_api_local_benchmark_balanced` | 3 | 30 | 9 | 6 | 5 | 4 | 9 | 11 |
| `x28_continuous_replay_collection_api_local_benchmark_balanced` | 3 | 30 | 20 | 19 | 18 | 2 | 20 | 8 |

Family replay highlights:

- `csv_correlation_replay_v1`: replay-admissible, 8/8 target rounds observed in x28.
- `cross_period_financial_v1`: replay-admissible, 4/4 target rounds observed in x28.
- `long_doc_metric_replay_v1`: still not replay headline in x28; 7/8 target rounds observed, missing round 10, gate reason includes `quality_gate_failed;missing_target_replay_rounds;missing_exact_target_rounds`.
- `csv_table_profile_v1` and `long_doc_table_v1`: history-backed, not replay-headline families.
- `incident_diagnosis_v2`: not eligible; quality gate failed and missing replay/exact target rounds.

## 9. Metrics Worth Keeping

Good report candidates:

| Evidence | Metric | Claim boundary |
|---|---|---|
| Core formal external compare `r01_07` | StateBus 25/25 vs external 16/25; prompt tokens -63268; total tokens -67989 | Formal quality-superiority and token reduction; not strict equal-quality or latency |
| Formal internal memfd/shared_memory | L3 25/25, semantic transfer 25, memfd transfer 25 or shared_memory publish 25 | Non-text semantic StateRef + data-plane mechanism; not KV/hidden-state |
| Flagship `csv_table_profile_v1` | StateRef saves 7979 LLM prompt bytes and 5295 visible bytes vs T2 | Family-level StateRef prompt saving |
| Flagship `csv_correlation_replay_v1` | StateRef saves 7109 LLM prompt bytes; replay eligible | Family-level replay + prompt saving |
| Isolated `long_doc_metric_replay_v1` | StateRef saves 10957 LLM prompt bytes and 9434 visible bytes | Diagnostic positive; not full-run headline until instability explained |
| x27/x28 continuous collection | validated replay 18, exact replay 2 in x28; history/artifact reuse in x27 | Memory/replay is real; family gates still matter |
| CodeAct x04d | 5/5 bwrap acceptance | System completeness; not latency superiority |
| Artifact/telemetry sidecars | 2373 artifact audits, 2373 telemetry files, 9492 prompt slices | Auditability and instrumentation evidence |

Do not use as headline:

- lr01/follow-up latency rerun formal superiority.
- shared_memory or memfd compare superiority from x23/x26.
- full flagship all-family pass.
- cross-period StateRef prompt saving.
- incident quality headline.
- gridops continuous result.
- KV prefix-cache actual mechanism.

## 10. Problems And Optimization Points

Priority 0:

- Fix or isolate the 24/25 StateBus regression in serialized latency reruns. It blocks quality/strict gates and makes lr01/lr02/lr03 debug-only despite good token/timing deltas.
- Explain `long_doc_metric_replay_v1` full-vs-isolated contradiction. This is the highest-value attribution issue because it determines whether the family is a strong positive or unstable.
- Keep claim gate code and report wording strict: no `exit=0` to claim conversion.

Priority 1:

- Either add continuous runner support for `gridops_world_v1` or remove x17b from extras until supported.
- Add isolated diagnostic for `long_doc_table_v1` before treating its full flagship no-saving result as stable.
- For `incident_diagnosis_v2`, debug quality/replay gate rather than StateRef transport; prompt saving exists but quality fails.
- For `cross_period_financial_v1`, preserve as a controlled negative where T2 semantic selection is enough or better.

Priority 2:

- Reduce structured completion/schema overhead before attempting latency claims.
- Break down CodeAct/bwrap, persist/reload, telemetry, workspace IO, and transport costs in a formal repeatable report.
- Subprocess control-plane overhead is clearly larger than loopback; optimize only after claim gates are clean.

Not worth blind rerun now:

- `repeat=3` for all stages.
- KV/local_vllm.
- x17b without runner support.
- formal compare reruns before fixing StateBus 24/25 gate cause.

## 11. Historical Comparison

Compared with `/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/13_artifact_mining_deep_analysis_20260708.md`:

- The earlier 2026-07-08 base/supplement conclusion was stronger for full-registry formal compare: StateBus 25/25 vs external 15/25, prompt/total token reduction, no latency claim.
- This 2026-07-09 core `r01_07` still supports quality-superiority, now StateBus 25/25 vs external 16/25.
- The serialized latency reruns are weaker: StateBus 24/25 and debug-only. This is not a contradiction of `r01_07`; it is a different claim object with stricter timing contract and live API variability.
- Earlier flagship supplement had 5 claimable families pass; this follow-up full flagship has only 2/6 pass. The gap is meaningful and mostly comes from the T2 same semantic selection control plus family collection/gate differences. Do not merge these as all-pass.
- The new isolated diagnostic partly reverses full flagship for `long_doc_metric_replay_v1`; this is a new instability signal, not a resolved claim.

Likely sources of difference:

- Live API variability and route/exact-match sensitivity.
- Different runner modes: normal compare vs serialized latency rerun, full flagship vs isolated family diagnostic.
- Family collection and T2 control being stricter than older StateRef-vs-L0 readings.
- Benchmark gate semantics becoming more explicit: quality headline, replay headline, prompt-saving-vs-T2 are separate gates.

Cross-run headline table:

| Evidence set | Stage / source | External quality | Claim gate | Token/prompt result | Flagship/stress result | `long_doc_metric_replay_v1` | Interpretation |
|---|---|---:|---|---|---|---|---|
| 2026-07-08 base/supplement | `13_artifact_mining_deep_analysis_20260708.md` | 25/25 vs 15/25 | `quality_superiority`, no latency claim | prompt -57.9%, total -49.7% | supplement table had 5 claimable positives and 1 diagnostic-only family | supplement positive, 3885 LLM bytes and 615 visible bytes saved | Stronger earlier headline; useful baseline, but less strict than current follow-up stress framing |
| 2026-07-09 core formal compare | `r01_07_formal_compare_api_local_memfd` | 25/25 vs 16/25 | `formal_superiority_claim_allowed=true`, kind `quality_superiority`; `serialized_latency_superiority_claim_allowed=0` | prompt tokens -63268, total tokens -67989 | not a flagship stage | not tested in this stage | Best current formal external claim; keep for report |
| 2026-07-09 core serialized latency reruns | `lr02` / `lr03` | 24/25 vs 15/25 | `debug_only`; strict=false, quality=false, formal=false, serialized latency=false | prompt -62960/-62456, total -80465/-75303 | not a flagship stage | not tested in this stage | Exit 0 does not rescue claim; quality gate regression blocks formal latency/superiority |
| 2026-07-09 follow-up lr01 | `lr01_14_formal_compare_latency_rerun_api_local_memfd` | 24/25 vs 16/25 | `debug_only`; strict=false, quality=false, formal=false, serialized latency=false | prompt -63088, total -81991 | not a flagship stage | not tested in this stage | Old empty-output hard error is closed, but claim is still blocked |
| 2026-07-09 core full flagship | core `r01_13_flagship_ablation_api_local` | n/a | family stress gates | total StateRef saved 33963 LLM bytes, 25608 visible bytes | 3/6 pass; fail reasons: quality 2, replay 1, no-extra-saving 1 | fails quality/replay gates despite -7528 LLM and -6153 visible bytes vs T2 | Mechanism positive, headline blocked by quality/replay |
| 2026-07-09 follow-up full flagship | follow-up `r01_13_flagship_ablation_api_local` | n/a | family stress gates | total StateRef saved 17702 LLM bytes, 8437 visible bytes | 2/6 pass; fail reasons: no-extra-saving 3, quality 2, replay 1 | fails quality/replay/no-extra-saving; L2 is +31691 LLM bytes vs T2 | Strongest evidence that StateRef saving is family- and runner-dependent |
| 2026-07-09 isolated failed-family diagnostics | `flagship_failed_family_diagnostics` | n/a | diagnostic family stress gates | total StateRef saved 12888 LLM bytes, 11899 visible bytes | 1/3 pass; `incident` quality fail, `cross_period` T2 dominates | passes: -10957 LLM bytes and -9434 visible bytes vs T2, quality/replay eligible | Reverses full-run long_doc_metric; diagnostic evidence only until diffed |
| 2026-07-09 extras backend compare | `x23` shared_memory, `x26` memfd benchmark_balanced | 24/25 vs 16/25 | `debug_only`; strict=false, quality=false, formal=false, latency=false | x23 prompt -63163 total -46338; x26 prompt -63331 total -77127 | not a flagship stage | not tested in this stage | Backend mechanism works, but external compare claim remains gate-blocked |

What changed from the previous document:

- The earlier "formal external compare is strong" conclusion is still supported, but now it should specifically cite core `r01_07`, not the serialized latency reruns.
- The earlier supplement flagship looked much more positive. The follow-up makes the boundary sharper: `csv_table_profile_v1` and `csv_correlation_replay_v1` are clean full-run positives; `long_doc_metric_replay_v1` is unstable; `cross_period_financial_v1` is a controlled negative against T2; `incident_diagnosis_v2` is quality-limited.
- The strongest new engineering finding is not a new speedup claim. It is a set of failure modes: quality gate regression to 24/25 in serialized/extras external compares, T2 same semantic selection dominance in multiple families, and `long_doc_metric_replay_v1` sensitivity to full-run versus isolated execution context.
- The old external empty-output hard error was real and localized: core lr01 failed with empty stdout/ValueError, while follow-up lr01 produced valid JSON. That is a fixed execution reliability issue, not a fixed claim gate issue.
- The new data argues against broad blind reruns. It points to targeted fixes: external compare quality regression, prompt assembly/T2 pairing for long_doc families, and continuous runner support boundaries.

## 12. Return To Contest Requirements

The contest asks for low-overhead communication, non-text state transfer, shared memory/reuse, multi-agent system completeness, and reproducible evidence.

Current supported capabilities:

- Multi-agent system: v2 runtime uses planner/retriever/executor/summarizer style role graph and passes preflight/smoke/formal suites.
- Structured communication: formal internal reports show protocol/control bytes reduced vs text in formal internal paths.
- Non-text state transfer: semantic StateRef transfers and memfd/shared_memory publications are present in formal and continuous reports.
- Shared memory/reuse: replay/reuse metrics show validated replay, exact replay, skipped steps, artifact reuse, memory commits, and history reuse gains.
- Evaluation: status tables, benchmark reports, telemetry, prompt slices, hydration audits, artifact audits, memory commits, and ref registries are rich enough to support forensic claims.
- CodeAct: bwrap smoke and 5/5 acceptance support system completeness.

Current unsupported or bounded capabilities:

- No actual KV cache or hidden-state transfer was tested in this non-KV run.
- KV-related fields in reports are estimates or analysis side data; do not write them as actual KV-cache hit results.
- Latency superiority is not supported because gates are false and system overhead is still structurally positive.
- openEuler final delivery validation is still separate from these local/container run artifacts.
- `gridops_world_v1` continuous execution is unsupported by current runner.

Suggested contest narrative:

StateBus v2 has credible evidence for structured control, semantic StateRef transfer over memfd/shared_memory, and replay/memory reuse with auditability. The strongest formal external claim remains quality-superiority plus token reduction, not latency. Non-text StateRef prompt-saving is family-dependent; two full flagship families are clean positives, one isolated diagnostic family is promising but unstable, and several families define honest boundaries.

## 13. Final Recommendations

Do not continue blind benchmark expansion right now. The next highest-value work is code/benchmark correction:

1. Debug serialized compare 24/25 StateBus quality in lr01/lr02/lr03. Without this, latency reruns remain debug-only.
2. Build a targeted `long_doc_metric_replay_v1` full-vs-isolated diff: compare runtime roots, T2 pairing, replay target rounds, prompt slices, artifact invalidations, and route/exact outputs.
3. Add isolated diagnostic for `long_doc_table_v1`.
4. Decide whether `gridops_world_v1` should be supported by continuous runner or only remain design/demo evidence.
5. Keep `cross_period_financial_v1` as a negative/control example for "semantic selection dominates; StateRef adds no prompt saving."
6. Optimize overhead only after claim gates are clean: CodeAct/bwrap, JSON role schema, persist/reload, telemetry, workspace IO, and subprocess transport.

Recommended wording:

- Safe: "StateBus v2 reduces prompt/total tokens and improves formal quality vs external pure-text on the core formal compare; it also demonstrates semantic StateRef transfer over memfd/shared_memory and memory/replay reuse in continuous tasks."
- Safe: "StateRef prompt-saving is family-dependent; full follow-up flagship has 2/6 clean family passes, with additional isolated positive evidence for long_doc_metric that needs reconciliation."
- Unsafe: "StateBus is faster end-to-end", "all flagship families pass", "KV/hidden-state transfer was measured", "shared_memory/memfd compare proves superiority", or "exit=0 means claim成立".
