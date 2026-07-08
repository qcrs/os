# 2026-07-08 local+api 合并结果分析

本文合并读取两组最新证据：

- Base comprehensive run：`sb2-gpu1-20260708_084458`
  - host root：`/home/qcrs/statebus/runs/sb2-gpu1-20260708_084458`
  - docs copy：`docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260708_084458/`
- Supplement health run：`sb2-gpu1-health-20260708_110413`
  - host root：`/home/qcrs/statebus/runs/sb2-gpu1-health-20260708_110413`
  - docs copy：`docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260708_084458_supplement_20260708_110413/`

结论先行：

- 正式 full registry 证据已更新到 API+local+memfd：formal 25 cases / 5 families 25/25 通过。
- formal text/protocol carrier compare 已覆盖 25 cases / 5 families。
- formal external compare 已覆盖 25 cases / 5 families，并通过 fairness gate 25/25；可读为 `quality_superiority` 与 token reduction evidence。
- 不能 claim latency superiority；`serialized_latency_superiority_claim_allowed=false`。
- continuous 和 continuous-replay 证明 semantic state transfer、validated replay 与 reuse gain 真实发生。
- 补跑关闭了前一轮 optional flagship 失败：flagship stage 跑完，5 个 claimable non-text state families 通过；1 个 `diagnostic_only` family 给出边界。
- KV prefix demo 证明 engine-local prefix scheduling/identity 设计可运行，并产生 corpus-level prefix reuse estimate；不证明真实 vLLM prefix-cache hit，也不证明 KV tensor transfer。
- Supplement run 的最终 `exit=1` 不是实验失败，而是两个新加 base audit gate 的 false negative；脚本已修，但本次 artifact 保留原始误报以便追溯。

## 运行状态

### Base comprehensive run

`status.tsv` 读数：

| Stage | Required | Result | 解读 |
|---|---:|---:|---|
| `02_pytest_full_v2` | yes | pass | full v2 pytest 通过 |
| `03_runtime_smoke` | yes | pass | runtime smoke 通过 |
| `r01_04_preflight_api_local` | yes | pass | local embedding + API preflight 通过 |
| `r01_05_formal_api_local_memfd` | yes | pass | formal 25/5 通过 |
| `r01_06_formal_carrier_compare_api_local_memfd` | yes | pass | text/protocol carrier compare 25/5 通过 |
| `r01_07_formal_compare_api_local_memfd` | yes | pass | external compare 25/5 通过 |
| `r01_10_continuous_api_local` | no | pass | continuous 30 rounds 通过 |
| `r01_11_continuous_replay_api_local` | no | pass | continuous replay 30 rounds 通过 |
| `r01_12_replay_negative_api_local` | yes | pass | replay negative audit 通过 |
| `r01_13_flagship_ablation_api_local` | no | fail | optional old failure，已由 supplement rerun 关闭 |

Base summary：

```text
failed_stage_count=1
failed_required_stage_count=0
failed_stages=[r01_13_flagship_ablation_api_local]
```

因此 base run 的 required evidence 是 green；唯一失败是 optional flagship old stage。

### Supplement health run

Supplement 中所有实质补跑 stage 均通过：

| Stage | Required | Result | 解读 |
|---|---:|---:|---|
| `s01_01_container_root_gpu_probe` | yes | pass | Docker root + GPU 1 可见，容器内 `cuda:0` |
| `s01_02_py_compile_health` | yes | pass | 19 个关键文件 compile/check 通过 |
| `s01_03_targeted_pytest_health` | yes | pass | targeted pytest 49 passed |
| `s01_04_kv_prefix_static_health` | yes | pass | KV prefix family 静态契约通过 |
| `s01_05_import_probe` | yes | pass | `neural_state` dataclass/import 问题关闭 |
| `s01_06_codeact_bwrap_smoke` | yes | pass | bwrap sandbox smoke 通过 |
| `s01_07_codeact_acceptance_api` | yes | pass | CodeAct API acceptance 5/5 通过 |
| `s01_08_kv_prefix_demo_api_local` | yes | pass | KV prefix demo API+local 跑通 |
| `s01_09* vllm prefix probes` | no | skipped | 未打开本地 vLLM probe，不产生机制 claim |
| `s01_10_flagship_ablation_api_local` | yes | pass | flagship ablation rerun 通过 |

Supplement raw summary 显示：

```text
failed_required_stages=[
  s01_00b_base_artifact_integrity_audit,
  s01_00c_base_claim_boundary_audit
]
```

这两个是新加的轻量 base-audit gate，不是实验 stage。失败原因是脚本误报：

- `summary_failed_required_zero` 使用 `int(summary.get(...) or -1)`，把合法的 `0` 误转成 `-1`。
- `external_fairness_gate_coverage` 和 `no_external_fairness_gate_failures` 在 base `summary.json.key_metrics` 中存在，但不在 `r01_07` stage stdout 顶层，旧 audit 未回填读取。
- 部分 claim gate 顶层序列化为 `0.0/1.0`，旧 audit 对布尔值判断过严。

脚本已修复这些误报点。当前 run 的原始 artifact 不应被重写；后续引用时应按“实质补跑全部通过，两个 base audit false negative”读取。

## Formal internal evidence

`r01_05_formal_api_local_memfd`：

| Metric | Value |
|---|---:|
| role path | `api` |
| embedding mode | `local` |
| formal L3 cases | 25 |
| formal L3 quality pass | 25 |
| formal family count | 5 |
| state pool requested | `memfd` |
| state pool used | `memfd` |
| memfd transfer count | 25 |
| memfd publish count | 25 |
| memfd bytes transferred | 247076 |
| semantic state transfer count | 25 |
| API planner/retriever/executor/summarizer calls | 25 each |

支持的结论：

- formal benchmark 已不是单 family 或 dev subset，而是 25 cases / 5 families。
- API 四角色都真实调用。
- local embedding 与 memfd data plane 跑通。
- `StateRef`/semantic state transfer 发生，并有 memfd publish/transfer telemetry。

不能推出：

- external superiority。internal 25/25 只是系统自身质量和 data-plane 证据。
- openEuler VM compatibility。
- hidden-state/KV tensor transfer。

## Formal carrier compare

`r01_06_formal_carrier_compare_api_local_memfd`：

```text
formal_compare_scope_label=formal_registry_25case_5family_text_protocol_compare
formal_compare_case_count=25
formal_compare_family_count=5
formal_compare_full_registry_coverage=true
```

支持的结论：

- v2 formal text/protocol carrier compare 已覆盖 full registry。
- 可用于说明 typed protocol/control/data-plane carrier 不是只在 3-case dev slice 上成立。

注意边界：

- 这是 internal carrier compare，不是 external baseline superiority。
- 不能与 latency claim 混用。

## Formal external compare

`r01_07_formal_compare_api_local_memfd`：

| Metric | StateBus | External | Delta |
|---|---:|---:|---:|
| prompt tokens | 48754 | 115734 | -66980 |
| completion tokens | 13062 | 7237 | +5825 |
| total tokens | 61816 | 122971 | -61155 |

Derived ratios:

- prompt token reduction：57.9%
- total token reduction：49.7%
- completion token increase：80.5%

Gate fields：

```text
formal_compare_case_count=25
formal_compare_family_count=5
formal_compare_full_registry_coverage=true
external_fairness_gate_coverage=true
no_external_fairness_gate_failures=true
external_fairness_gate_pass_count=25
external_fairness_gate_failed_case_count=0
comparator_token_split_schema=statebus.comparator.token_split.v1
timing_execution_contract=serialized_statebus_then_external_within_each_mode_v1
strict_equal_quality_comparison_valid=false
quality_superiority_comparison_valid=true
formal_quality_superiority_claim_allowed=true
formal_efficiency_superiority_claim_allowed=false
formal_external_claim_kind=quality_superiority
serialized_latency_superiority_claim_allowed=false
```

支持的结论：

- external compare 已覆盖 full registry 25/5。
- external fairness gate 25/25 通过。
- StateBus 在 full formal external compare 上有 quality-superiority gate。
- token split schema 已补齐，可以分别读 prompt/completion/total token。
- 尽管 completion tokens 增加，prompt tokens 与 total tokens 均显著下降。

不能 claim：

- strict equal-quality efficiency superiority。`strict_equal_quality_comparison_valid=false`。
- latency/efficiency superiority。`formal_efficiency_superiority_claim_allowed=false`，`serialized_latency_superiority_claim_allowed=false`。
- “所有维度更优”。准确表述应为：full-registry external compare 支持 quality-superiority claim，并伴随 prompt/total token reduction；completion tokens 上升。

## Continuous evidence

`r01_10_continuous_api_local` collection summary：

```text
family_count=3
continuous_round_count=30
successful_family_count=3
L2_semantic_state_transfer_count=30
L3_reuse_gain=9
L3_artifact_reuse_count=50
L3_history_reuse_gain=11
L3_history_step_reduction_count=13
validated_replay_count=4
exact_replay_count=5
quality_headline_eligible_family_count=2
replay_headline_eligible_family_count=0
```

Family readout:

| Family | Scope | Quality headline | Replay headline | Key observation |
|---|---|---:|---:|---|
| `csv_table_profile_v1` | continuous | yes | no | history-backed only，artifact reuse 21 |
| `incident_diagnosis_v2` | continuous | no | no | quality/missing target replay rounds keep it non-headline |
| `long_doc_table_v1` | continuous | yes | no | history-backed only，artifact reuse 20 |

支持的结论：

- Continuous runner 不是 smoke-only；3 families / 30 rounds 已跑完。
- Semantic state transfer 每轮发生：30 transfers。
- L3 reuse gain 非零。
- History-backed artifact reuse 明显存在。

边界：

- 这组不是 replay-headline evidence；`replay_headline_eligible_family_count=0`。
- `incident_diagnosis_v2` 是重要负例/诊断 family，不能把 continuous 整体写成 all-family headline eligible。

## Continuous replay evidence

`r01_11_continuous_replay_api_local` collection summary：

```text
family_count=3
continuous_round_count=30
replay_target_round_count=20
replay_observed_round_count=19
replay_missing_target_round_count=1
validated_replay_count=18
validated_downgraded_reuse_count=18
exact_replay_count=2
answer_restoration_replay_count=0
L2_semantic_state_transfer_count=30
L3_reuse_gain=20
replay_headline_eligible_family_count=2
```

Family readout:

| Family | Replay headline | Validated replay | Exact replay | Gate reason |
|---|---:|---:|---:|---|
| `csv_correlation_replay_v1` | yes | 8 | 0 | clean |
| `cross_period_financial_v1` | yes | 4 | 0 | clean |
| `long_doc_metric_replay_v1` | no | 6 | 2 | missing round 7 / quality gate |

支持的结论：

- Replay path 有正式 3-family / 30-round evidence。
- 18 个 validated replay 与 2 个 exact replay 真实发生。
- `answer_restoration_replay_count=0`，说明系统没有把 exact replay 偷换成 answer restoration。
- 2/3 replay families 可进入 replay headline。

边界：

- 不是所有 replay families 都 headline eligible。
- `long_doc_metric_replay_v1` 仍需单独修 missing target round 7 / quality gate。

## Replay negative audit

`r01_12_replay_negative_api_local`：

```text
audit_pass=true
case_count=7
```

支持的结论：

- Replay gate 不是只会正向通过；负向 audit 覆盖了 7 个 case。
- 可作为 anti-leak / false replay control 证据。

## CodeAct supplement evidence

`s01_07_codeact_acceptance_api`：

```text
total_runs=5
success_count=5
target_success_count=3
target_met=true
sandbox_backend_required=bwrap
```

每个 run 都满足：

- `ok=true`
- `generated_by=llm_api`
- `generation_fallback_used=false`
- `ast_policy_pass=true`
- `sandbox_backend=bwrap`

支持的结论：

- Bounded CodeAct API generation 在这次环境下 5/5 稳定通过。
- 不是 deterministic fallback。
- bwrap sandbox 路径可用。

边界：

- 这是 bounded CodeAct demo，不是通用 open-ended CodeAct benchmark superiority。
- 不能把 CodeAct 结果扩展到未测试任务族。

## KV prefix supplement evidence

### Static contract

`s01_04_kv_prefix_static_health`：

```text
family_id=kv_prefix_reuse_v1
claim_tier=demo_secondary
round_count=10
dataset_count=2
not_default_formal_chain=true
claim_boundary=engine_local_prefix_reuse_probe_only_no_kv_tensor_export
cache_friendly_max_same_dataset_run=5
cache_hostile_max_same_dataset_run=1
```

两个 corpus prefix hash 不同：

- `orion_factory_ops_2026`
- `nova_retail_ops_2026`

支持的结论：

- KV prefix family 有明确的 corpus grouping 与 schedule contrast。
- Friendly schedule 的同 corpus 连续窗口大于 hostile schedule。
- 设计层面没有 claim KV tensor export。

### API+local demo

`s01_08_kv_prefix_demo_api_local`：

```text
task_family=kv_prefix_reuse_v1
family_case_count=10
L3_case_count=10
L3_quality_pass_count=10
L2_semantic_state_transfer_count=10
L3_reuse_gain=6
L3_validated_downgraded_reuse_count=6
L3_kv_corpus_prefix_hash_unique_count=2
L3_kv_corpus_prefix_hash_reuse_count=8
L3_kv_corpus_level_prefill_saved_tokens_estimate=2144
L3_kv_engine_local_prefill_saved_tokens_estimate=2680
```

Replay admissibility：

```text
headline_scope=history_backed_only
eligible_for_quality_headline=true
eligible_for_replay_headline=false
replay_gate_reason=missing_target_replay_rounds
missing_target_rounds=[3]
validated_target_rounds=[4,5,6,8,9,10]
```

支持的结论：

- KV prefix demo 不是只停留在 manifest；已用 API+local 跑完 10 rounds。
- corpus-level prefix reuse estimate 非零：8。
- corpus-level prefill saved estimate 非零：2144 tokens。
- engine-local prefill saved estimate 非零：2680 tokens。
- 质量 10/10，通过 demo family 的 deterministic/fact coverage floor。

边界：

- `STATEBUS_RUN_VLLM_PREFIX_PROBE=0`，vLLM metrics/alignment probe 被跳过。
- 因此不能 claim actual vLLM prefix-cache hits / TTFT improvement。
- 不能 claim KV tensor transfer；当前只能写 engine-local prefix identity / scheduling / estimate。
- 该 family 是 `demo_secondary`，不是 formal registry 25/5 的一部分。

## Flagship / non-text state evidence

`s01_10_flagship_ablation_api_local` stage exit 0。

Stress summary：

```text
stress_family_count=6
stress_pass_family_count=5
stress_fail_family_count=1
claimable_non_text_state_family_count=5
diagnostic_only_family_count=1
total_llm_prompt_saved_by_state_ref_bytes=21325
total_prompt_visible_saved_by_state_ref_bytes=7875
claim_boundary=isolates L2 StateRef/semantic-state transfer from T2 text handoff with same semantic selection; no KV or hidden-state transfer claim
```

Family-level readout:

| Family | Scope | Stress pass | LLM prompt saved | Visible saved | Interpretation |
|---|---|---:|---:|---:|---|
| `csv_correlation_replay_v1` | claimable | yes | 12980 | 7242 | extra StateRef prompt saving |
| `long_doc_metric_replay_v1` | claimable | yes | 3885 | 615 | extra StateRef prompt saving |
| `long_doc_table_v1` | claimable | yes | 941 | 18 | extra StateRef prompt saving |
| `cross_period_financial_v1` | claimable | yes | 1957 | 0 | scaffolding saving |
| `csv_table_profile_v1` | claimable | yes | 1562 | 0 | scaffolding saving |
| `incident_diagnosis_v2` | diagnostic only | no | 0 | 0 | semantic selection dominates |

支持的结论：

- 前一轮 optional flagship failure 已关闭：stage 跑完且 exit 0。
- 5 个 claimable non-text state families 都显示 StateRef / semantic-state 相对 T2 text semantic-selection 的 savings。
- `incident_diagnosis_v2` 作为 diagnostic-only 负例保留，说明方法不是所有 family 都自动获益。

边界：

- 不能写“6/6 all pass”。
- 不能写 hidden-state transfer 或 KV transfer。
- 准确 claim 是：在 5 个 claimable families 中，non-text StateRef/semantic-state transfer 相对 T2 text handoff 有 prompt/scaffolding savings；1 个 diagnostic-only family 不支持该 claim。

## 我们方法体现出的优势

当前最可辩护的优势有四类。

1. Formal full-registry quality + token reduction

   Full 25/5 external compare 已覆盖。StateBus 相比 external baseline：

   - quality superiority gate 通过；
   - fairness gate 25/25；
   - prompt tokens 下降 57.9%；
   - total tokens 下降 49.7%。

   但 completion tokens 上升 80.5%，strict equal-quality 不成立，所以不能写成 equal-quality efficiency superiority。

2. Typed protocol / carrier and memfd state transfer

   Formal 25/5 internal benchmark 和 carrier compare 都跑通；memfd transfer/publish 各 25，semantic state transfer 25。可以说明 v2 的 typed control/data-plane 不是文档设计，而是 benchmark path 中实际发生。

3. Continuous and replay reuse

   Continuous 30 rounds 有 `L3_reuse_gain=9`；continuous replay 30 rounds 有 `validated_replay_count=18`、`exact_replay_count=2`、`L3_reuse_gain=20`。这能体现 StateBus 在多轮任务中的状态复用优势，而不是单轮 prompt 压缩。

4. Non-text StateRef family-level savings

   Flagship supplement 证明 5 个 claimable families 中 StateRef/semantic-state transfer 相对 T2 text handoff产生 LLM prompt savings，总计 21325 bytes。这个证据比之前 3/6 更强，但仍要保留 `incident_diagnosis_v2` 负例边界。

## 不能 claim 的内容

以下内容仍不能写进正式优势结论：

- Latency superiority：gate 为 false，且没有 serialized repeat3 latency evidence。
- Actual vLLM prefix-cache hit / TTFT advantage：vLLM probes skipped。
- KV tensor transfer、hidden-state transfer、cross-process KV sharing。
- openEuler VM validation。
- Universal flagship all-pass。
- General-purpose CodeAct superiority。
- Strict equal-quality efficiency superiority over full formal registry。

## 当前剩余问题与建议

1. Posthoc correction

   Supplement run 的 `summary.json` 原样保留了两个 base audit false-negative failure。建议不要改原始 artifact；可另写 posthoc corrected summary，或在后续 run 用已修脚本重跑轻量 audit。

2. vLLM prefix mechanism probe

   如果要把 KV prefix 从 estimate 提升为 mechanism evidence，需要启动 local vLLM prefix-cache service，并打开：

   ```bash
   export STATEBUS_RUN_VLLM_PREFIX_PROBE=1
   export STATEBUS_VLLM_METRICS_URL=http://127.0.0.1:8000/metrics
   export STATEBUS_VLLM_BASE_URL=http://127.0.0.1:8000/v1
   ```

   必须同时记录 prefix-cache metrics delta 与 streaming TTFT。

3. Long-doc replay missing round

   `long_doc_metric_replay_v1` 在 base continuous-replay 中 missing target round 7；KV prefix demo missing target round 3。二者不阻塞当前 quality/reuse evidence，但阻塞 replay-headline。

4. Formal claim language

   报告建议写：

   ```text
   In a full-registry 25-case / 5-family local+API comparison, StateBus passes the quality-superiority gate and reduces prompt/total token use under a passing external fairness gate. Latency superiority and strict equal-quality efficiency superiority are not claimed.
   ```

   不建议写：

   ```text
   StateBus is faster.
   StateBus is universally more efficient.
   StateBus transfers KV/hidden state.
   ```

## 详细拆解与归因

这一节专门回答“结果为什么这样判、收益来自哪里、损耗来自哪里、后续应优先改哪里”。它比前面的 summary 更适合后续决策。

### External compare：为什么能 claim quality，却不能 claim latency / strict equal-quality efficiency

Formal external compare 不是单一 gate，而是三层 gate：

| Gate | 要求 | 本轮结果 | 结论 |
|---|---|---:|---|
| strict equal-quality | StateBus 和 external 都在 25/25 上过同一 quality floor | false | 不能读 equal-quality efficiency |
| formal efficiency | strict equal-quality 成立，且 total token / prompt bytes 都下降 | false | 不能读 strict efficiency superiority |
| quality superiority | external fairness gate 过，且 StateBus quality floor 更高 | true | 可以读 quality-superiority |

关键事实是：strict equal-quality 失败不是因为 StateBus 质量低，而是因为 external 只有 15/25 过 quality floor，StateBus 是 25/25。External fairness gate 是 25/25，说明 baseline 不是污染、少角色或用了 StateBus 内部 helper；它是四角色纯文本 baseline，同一 scorer、同一 quality floor、无 oracle leakage。失败集中在输出目标数值没打准。

External 失败 case 拆解：

| Failed family | Failed / total | 失败形态 | 判断 |
|---|---:|---|---|
| `anomaly_detection_v1` | 3/3 | `metric_value_exact=0` | route/tool/doc 基本可选对，但异常数值投影不稳定 |
| `conditional_aggregation_v1` | 4/4 | `metric_value_exact=0` | 条件聚合类任务最容易在纯文本 evidence summary 中损失目标数值 |
| `multi_period_trend_analysis_v1` | 3/5 | `metric_value_exact=0` | 跨期趋势部分失败，说明纯文本链路对多期指标投影不稳定 |

这说明 StateBus 的优势主要不是“少写 prompt”这么简单，而是结构化 retrieval / execution / artifact projection 把目标 metric value 固定下来。External baseline 的 retriever 读公开 evidence 后，将关键事实压缩成自然语言 `evidence_summary`，后续 executor / summarizer 再继续传递，数值计算和投影容易丢；StateBus 则通过 selected evidence、tool artifact、`summary_json` 和 scorer-facing metric projection 让关键字段可审计。

### Token split：为什么 total 降了，但 completion 涨了

全量 token split：

| Metric | StateBus | External | Delta | Ratio |
|---|---:|---:|---:|---:|
| prompt tokens | 48754 | 115734 | -66980 | -57.9% |
| completion tokens | 13062 | 7237 | +5825 | +80.5% |
| total tokens | 61816 | 122971 | -61155 | -49.7% |

Prompt 端收益来源：

- External pure-text retriever 需要读取公开 corpus/evidence 文本；在 `anomaly_detection_v1` 和 `conditional_aggregation_v1` 里 evidence 更长，所以 prompt 膨胀最明显。
- StateBus 通过 local embedding、semantic pruning、StateRef hydration 和 structured handoff，把下游角色看到的内容收敛成 selected evidence / table / artifact slice。
- 本轮 StateBus 和 external 都是四角色，不是少调用 LLM 取胜；主要差异是每个角色拿到的上下文载荷不同。

Completion 端损耗来源：

- StateBus role path 强制返回可解析 JSON。`planner/retriever/executor/summarizer` 输出中包含 `candidate_key`、`route`、`tool_name`、`action_contract`、summary/reusable/confidence/tags 等结构字段。
- Executor 最终落成 `summary_json`，这提高了 scorer、replay gate 和 artifact audit 的稳定性，但 completion token 更重。
- External summarizer 输出更短，executor artifact 也更轻，所以 completion token 低。

Family-level token 拆解：

| Family | SB pass | Ext pass | Prompt delta | Completion delta | Total delta | 读法 |
|---|---:|---:|---:|---:|---:|---|
| `anomaly_detection_v1` | 3/3 | 0/3 | -26045 (-74.6%) | +527 (+61.1%) | -25518 (-71.4%) | 最大收益；external 长 evidence + 数值失败 |
| `conditional_aggregation_v1` | 4/4 | 0/4 | -33048 (-73.6%) | +745 (+55.9%) | -32303 (-69.9%) | 最大收益；条件聚合依赖结构化执行 |
| `cross_table_join_analysis_v1` | 5/5 | 5/5 | -2436 (-21.0%) | +1194 (+74.7%) | -1242 (-9.4%) | 双方质量相等，但 JSON completion 抵消部分 prompt 节省 |
| `financial_report_analysis` | 8/8 | 8/8 | -3090 (-24.3%) | +1997 (+107.4%) | -1093 (-7.5%) | 单文档短表场景 external 已较强，StateBus 更像可审计 artifact 优势 |
| `multi_period_trend_analysis_v1` | 5/5 | 2/5 | -2361 (-20.3%) | +1362 (+86.0%) | -999 (-7.6%) | 有质量优势，但 token 优势不大 |

因此正式措辞应是：StateBus 在 full-registry external compare 中通过 quality-superiority gate，并伴随 prompt/total token reduction；不能写成所有 token 维度都更优，也不能写成 strict equal-quality efficiency superiority。

### Latency：为什么本轮不能 claim latency superiority

本轮 timing debug：

```text
task_ms_delta = +73103.695
llm_ms_delta = +37201.852
system_overhead_ms_delta = +35901.844
timing_delta_direction = statebus_minus_external
```

也就是说，StateBus 在这轮 formal external compare 中总体更慢。这不影响 quality/token 结论，但直接阻塞 latency superiority。

原因拆解：

- 这只是单轮 `serialized_statebus_then_external_within_each_mode_v1`，没有 repeat3、交替顺序或随机化顺序，不能抵消 API 端瞬时波动。
- StateBus formal path 开启 audit / persistence / telemetry / memfd / CodeAct / workspace materialization，系统层开销真实存在；它是可审计证据的成本，不应被包装成 latency 优势。
- Completion tokens 增加也会拉长 LLM wall time；结构化 JSON 输出换来稳定 scorer 和 replay/audit，但不是免费。
- `serialized_latency_superiority_claim_allowed=false` 是正确 gate。

如果后续要 claim latency，必须补一个独立 serialized timing rerun：至少 repeat3，最好交替顺序 `statebus->external` 与 `external->statebus`，并分别输出 LLM wall time、system overhead、audit_full 与轻量 delivery profile 的对照。

### Continuous：history-backed reuse 和 replay 不能混写

Continuous 组主要证明“连续任务里有真实历史复用”，但不是 replay headline：

| Family | Quality headline | Replay headline | 主要收益 | 主要边界 |
|---|---:|---:|---|---|
| `csv_table_profile_v1` | yes | no | `history_artifact_reuse_count=21`，history target 全覆盖 | history-backed only，不是 replay-admissible headline |
| `long_doc_table_v1` | yes | no | `history_artifact_reuse_count=20`，长文表格任务有持续复用 | history-backed only |
| `incident_diagnosis_v2` | no | no | 有 exact/validated replay 诊断信号 | quality gate 失败，且 missing target rounds 3/6 |

正向价值：

- `L2_semantic_state_transfer_count=30`，每轮都有 semantic state transfer。
- `L3_artifact_reuse_count=50`、`L3_history_reuse_gain=11`、`L3_history_step_reduction_count=13`，共享记忆和 artifact history 不是摆设。
- 两个 history-backed families 的 observed reuse rounds 超过 manifest target rounds，说明复用不是只在手工指定轮次触发。

负向价值：

- `incident_diagnosis_v2` 证明当前机制对语义诊断/多因素解释类任务不够稳定，不能当作 formal headline family。
- Continuous 组 `replay_headline_eligible_family_count=0`，所以 replay 结论必须引用 continuous-replay 组。

### Continuous replay：validated replay 是主收益，exact replay 是较小但更强的子集

Replay 组的核心不是“全部 exact replay”，而是安全地把可复用历史降级成 validated replay：

| Family | Target replay | Observed replay | Validated replay | Exact replay | Headline | 解释 |
|---|---:|---:|---:|---:|---:|---|
| `csv_correlation_replay_v1` | 8 | 8 | 8 | 0 | yes | 相关性任务稳定复用历史策略/结果，但仍做验证 |
| `cross_period_financial_v1` | 4 | 4 | 4 | 0 | yes | 跨期财务任务 replay gate 干净 |
| `long_doc_metric_replay_v1` | 8 | 7 | 6 | 2 | no | 有 exact replay 证据，但 round 7 missing，且 quality gate 不达标 |

正向结论：

- `validated_replay_count=18` 是主要收益，说明系统能识别可复用历史并复核后复用。
- `exact_replay_count=2` 是更强但较少的证据，只能写成子集。
- `answer_restoration_replay_count=0` 很重要，说明没有把 answer restoration 当成 replay 成功偷报。
- `L3_reuse_gain=20` 高于普通 continuous 的 `9`，说明 replay-admissible family 的收益更强。

问题定位：

- `long_doc_metric_replay_v1` 的 missing target round 7 是当前 replay headline 的主要缺口。
- 这个缺口不影响 2 个 replay headline families，但阻止“3/3 replay families pass”的表述。
- 下一步应优先看 round 7 的 route/doc/metric projection 是否被 strict quality gate 拦下，而不是泛泛调 prompt。

### Flagship non-text state：5/6 不是 all-pass，负例有诊断价值

Flagship ablation 比较的是 L2 StateRef / semantic-state transfer 和 T2 text handoff with same semantic selection。因为 semantic selection 相同，`raw_evidence_delta_l2_vs_t2=0`，所以这组更适合回答“非文本状态传递本身有没有收益”。

| Family | LLM prompt saved | Visible saved | Interpretation | 读法 |
|---|---:|---:|---|---|
| `csv_correlation_replay_v1` | 12980 | 7242 | extra prompt saving | 最强正例，StateRef 明显减少下游可见上下文 |
| `long_doc_metric_replay_v1` | 3885 | 615 | extra prompt saving | 正例，但还有 replay round 7 问题 |
| `long_doc_table_v1` | 941 | 18 | extra prompt saving | 弱正例，visible saving 很小 |
| `cross_period_financial_v1` | 1957 | 0 | scaffolding saving | 不是 evidence visible saving，主要省 role scaffolding / handoff overhead |
| `csv_table_profile_v1` | 1562 | 0 | scaffolding saving | 同上，可以 claim prompt saving，但不要夸成 evidence 大幅减少 |
| `incident_diagnosis_v2` | 0 | 0 | semantic selection dominates | 负例；L2 比 T2 反而多 1456 prompt bytes |

这说明 non-text StateRef/semantic-state transfer 是有效改动，但不是 universal。5 个 claimable families 通过，其中 3 个是可见 evidence/handoff 层 savings，2 个主要是 scaffolding savings。`incident_diagnosis_v2` 的失败说明：当 semantic selection 已经把 evidence 控得很紧时，StateRef 的 manifest/hydration/reference scaffolding 可能抵消收益，甚至更重。

### KV prefix：当前证明 schedule/identity/estimate，不证明 vLLM 机制命中

KV prefix demo 的正向结果：

- 10 rounds / 2 corpus，质量 10/10。
- Friendly schedule 最大同 corpus 连续窗口是 5；hostile schedule 最大窗口是 1。
- L3 `validated_downgraded_reuse_count=6`，`L3_reuse_gain=6`。
- corpus prefix hash unique count 为 2，reuse count 为 8。
- corpus-level prefill saved estimate 为 2144 tokens，engine-local estimate 为 2680 tokens。

边界：

- `evidence_prefix_hash_unique_count=10`、`evidence_prefix_hash_reuse_count=0`，说明每个任务的具体 evidence prefix 仍不同。
- 可复用的是 corpus-level / engine-local prefix identity，不是完整 per-task evidence prompt。
- vLLM metrics probe 和 TTFT alignment probe 都 skipped，所以这些数字是 prefix scheduling estimate，不是实际 `prefix_cache_hit` 计数。
- `missing_target_rounds=[3]`，所以它能做 demo quality / reuse evidence，不能做 replay-headline evidence。

要把 KV 从 demo 提到机制证据，需要启动 local vLLM prefix-cache service，同时记录 prefix-cache metrics delta 与 streaming TTFT，并继续保持 `no_kv_tensor_export` 的 claim boundary，除非真的实现跨进程 KV tensor handoff。

### CodeAct：健康证据，不是优势主证据

CodeAct supplement 的结论是 bounded acceptance 5/5：

- `generated_by=llm_api`，不是 deterministic fallback。
- `generation_fallback_used=false`。
- `ast_policy_pass=true`。
- `sandbox_backend=bwrap`。

这能支撑赛题“鼓励 CodeAct”的系统完整性加分，说明 bounded CodeAct 生成和 bwrap 执行链路可用。但它不是 broad CodeAct benchmark：没有覆盖复杂开放任务，也没有和 non-CodeAct baseline 做质量/latency/token 对照。因此只能作为执行链路健康证据，不能作为“CodeAct superiority”。

## Reference commands

Base summary：

```bash
jq '{run_id, failed_stage_count, failed_required_stage_count, key_metrics}' \
  /home/qcrs/statebus/runs/sb2-gpu1-20260708_084458/artifacts/summary.json
```

Supplement summary：

```bash
jq '{run_id, base_run_id, failed_stage_count, failed_required_stage_count, failed_stages, key_metrics}' \
  /home/qcrs/statebus/runs/sb2-gpu1-health-20260708_110413/artifacts/summary.json
```

Stage status：

```bash
sed -n '1,220p' /home/qcrs/statebus/runs/sb2-gpu1-20260708_084458/artifacts/status.tsv
sed -n '1,220p' /home/qcrs/statebus/runs/sb2-gpu1-health-20260708_110413/artifacts/status.tsv
```
