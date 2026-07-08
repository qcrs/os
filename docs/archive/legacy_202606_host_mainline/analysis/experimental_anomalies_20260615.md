# StateBus 实验数据异常详细清单

日期：2026-06-15
数据源：`/home/qcrs/statebus/runs/api_smoke_then_v3_20260615_104805/`

---

# 零、前置确认：本批次数据来源

## R0-1：SUMMARY 声明了 `reused-existing-results`

**文件**：`v3_api_repeat3_suite/SUMMARY.md:7-9`
```
LLM config: 'reused-existing-results'
Embedding model: 'reused-existing-results'
Executor transport: 'reused-existing-results'
```

## R0-2：所有 Benchmark log 为空运行

**证据**：`v3_api_repeat3_suite/logs/` 下 14 个日志文件：
- 12 个 `benchmark_*.log` — 每个仅 4 行（FutureWarning + LangChainPendingDeprecationWarning），无 task 时间戳、无 LLM 调用记录、无 error
- 2 个 open surface log — 0 字节空文件

**结论**：本批次的所有 latency/timing/token 数值不来自本次 real LLM 运行。以下异常分析关注数据结构层面的矛盾，不依赖实时性。

---

# 一、跨模式数据记账矛盾

## ANOM-1：Text 和 Protocol 的 handoff bytes 在 per-family CSV 中完全相同

**文件**：`v3_api_repeat3_suite/benchmarks/contest_dual_mode_controlled_v3/benchmark_compare.csv`

**数据**（handoff 列摘录）：

| task_group | text_handoff_ref_count | protocol_handoff_ref_count | text_handoff_bytes | protocol_handoff_bytes | text_handoff_wire_bytes | protocol_handoff_wire_bytes |
|---|---:|---:|---:|---:|---:|---:|
| auth_rotation_chain | 0.0 | 8.0 | 7694.00 | 7694.00 | 626.00 | 626.00 |
| billing_queue_chain | 0.0 | 8.0 | 6957.00 | 6957.00 | 650.00 | 650.00 |
| checkout_release_chain | 0.0 | 8.0 | 7824.00 | 7824.00 | 658.00 | 658.00 |
| deploy_config_chain | 0.0 | 8.0 | 6660.00 | 6660.00 | 642.00 | 642.00 |
| inventory_rollout_chain | 0.0 | 8.0 | 8165.00 | 8165.00 | 634.00 | 634.00 |

**矛盾**：text 侧 `handoff_ref_count=0.0`（`text_strict_pure_lane` 不产生 typed state ref），但 `handoff_bytes` 非零且**完全等于** protocol 侧的值（每个 family 都相等，精确到小数点后两位）。text 的 wire bytes 也同样等于 protocol 的 wire bytes。

**根因分析**：指标聚合层（`eval/runner.py` 的 `_average_metric_rows` 或 `_sum_metric_rows`）在处理跨 mode 对比时，可能将同一组 handoff metrics 分配到了两个 mode 各自的聚合行中。具体表现为：per-family CSV 的行是按 `task_group` 聚合而非按 `mode` 聚合，同一 family 的 text 和 protocol 两行的 handoff 字段被填入了同一个聚合值。

## ANOM-2：报告 Headline 把 text handoff bytes 清零了——与 per-family CSV 矛盾

**文件**：`v3_api_repeat3_suite/benchmarks/contest_dual_mode_controlled_v3/benchmark_report.md:66-70`

**报告 Headline 展示**：
```
text / text_strict_pure_lane:
  handoff_wire_bytes = 0.00
  handoff_payload_bytes = 0.00
  handoff_textual_bytes = 0.00
  handoff_nontext_bytes = 0.00

protocol / state_packet_minimal:
  handoff_wire_bytes = 160.50
  handoff_payload_bytes = 1865.00
  handoff_textual_bytes = 751.00
  handoff_nontext_bytes = 1114.00
```

**矛盾**：如果 text 侧 handoff 全为 0，那么 per-family CSV（ANOM-1）中 text 行的 handoff_bytes=7694 怎么来的？

**解释**：报告的 headline 使用了 transfer_strategy 维度的聚合（`text_strict_pure_lane` 这个 strategy 的 handoff 确实是 0），而 per-family CSV 使用了 task_group 维度的聚合（可能把 protocol 的 handoff 值错误地抄到了 text 列）。两种聚合口径在同一个问题上给出相反的数值——一个是"text 没 handoff"，一个是"text 和 protocol handoff 一样大"。外部读者无法判断哪个是正确的。

## ANOM-3：memory_dual_mode_fairness_v3 的 per-family CSV 同样出现相同的 handoff bytes 抄写

**文件**：`v3_api_repeat3_suite/benchmarks/memory_dual_mode_fairness_v3/benchmark_compare.csv`

**数据**：
| task_group | text_handoff_ref_count | protocol_handoff_ref_count | text_handoff_bytes | protocol_handoff_bytes |
|---|---:|---:|---:|---:|
| auth_rotation_chain | 0.0 | 3.0 | 3875.67 | 3875.67 |
| checkout_release_chain | 0.0 | 4.0 | 6868.00 | 6868.00 |
| deploy_config_chain | 0.0 | 4.0 | 3726.00 | 3726.00 |
| billing_queue_chain | 0.0 | 4.0 | 6724.00 | 6724.00 |
| inventory_rollout_chain | 0.0 | 3.0 | 4120.00 | 4120.00 |

同一个 bug 跨多个 pack 复现。**这是一个系统性的指标聚合层问题，不是单 pack 的偶然误差。**

---

# 二、协议效率反直觉数据

## ANOM-4：Protocol 在 3/4 的 protocol-only 内部对比中 control_bytes 更高

**数据汇总**（所有 protocol-only pack 的内部对比）：

| pack | baseline strategy | protocol strategy | baseline control_bytes | protocol control_bytes | delta |
|---|---:|---|---:|---:|---:|
| `typed_state_authenticity_v3` | natural_handoff_text | state_packet_minimal | 6767.35 | 7001.55 | **+234.20** |
| `typed_state_mechanism_v3` | natural_handoff_text | state_packet_minimal | 6959.25 | 7054.25 | **+95.00** |
| `carrier_microbench_v3` | text_packet_minimal | state_packet_minimal | 6525.55 | 6682.55 | **+157.00** |
| `text_definition_audit_v3` | inline_text_handoff | state_packet_minimal | 7078.40 | 6740.95 | **-337.45** |

**只有跨 mode 对比的** `contest_dual_mode_controlled_v3`（text_strict_pure_lane=7955 → state_packet_minimal=6483，−1472）也显示 protocol 更轻。但这个对比中 mode 和 handoff object 同时变化。

**在 protocol-only 内部对照（只改 handoff object 不改 mode）中，3/4 的 pack 显示 `state_packet_minimal` 的控制面比 `natural_handoff_text` 或 `text_packet_minimal` 更重。** 这说明 protocol 的通信格式本身在没有跨 mode 的 setup/teardown 差异时并不比纯文本格式轻。

## ANOM-5：Protocol summarizer 在所有 family 上 tokens 多 19-26%

**文件**：`v3_api_repeat3_suite/benchmarks/contest_dual_mode_controlled_v3/benchmark_compare.csv`

| task_group | text_llm_total_tokens | protocol_llm_total_tokens | delta | delta% |
|---|---:|---:|---:|---:|
| auth_rotation_chain | 1236.00 | 1522.33 | +286.33 | +23.2% |
| billing_queue_chain | 1286.00 | 1589.33 | +303.33 | +23.6% |
| checkout_release_chain | 1306.67 | 1644.00 | +337.33 | +25.8% |
| deploy_config_chain | 1251.33 | 1549.00 | +297.67 | +23.8% |
| inventory_rollout_chain | 1344.67 | 1595.00 | +250.33 | +18.6% |

**所有 5 个 family 无一例外，protocol llm tokens > text llm tokens。** 按赛题"相比纯文本协作的 token 节省效果"的评分标准，这个数据方向与期望相反。

**token 差异来源**：报告中 `planner_tokens=0.00`（Planner 被绕过），所以 token 全部来自 Summarizer。protocol 侧的 Summarizer 收到了展开的结构化 metadata（`_build_protocol_summary_handoff()` 的产物），prompt 更长，输出 token 也更多。

## ANOM-6：Exact replay 下 protocol state_bytes 是 text 的 1.96 倍

**文件**：`v3_api_repeat3_suite/benchmarks/memory_dual_mode_fairness_v3/benchmark_compare.csv`

| reuse_axis | text_state_bytes | protocol_state_bytes | ratio |
|---|---:|---:|---:|
| exact_replay | 1213.67 | 2373.20 | **1.96x** |
| validated_replay | 2514.87 | 2869.60 | 1.14x |
| working_assist | 3734.33 | 4660.00 | 1.25x |

Exact replay 是 protocol 侧本应最有优势的场景（跳过 retrieve+execute，零新 state 生产，完全依赖 restore）。但 restore 回来的 protocol state 比 text state 大 96%。

**根因**：protocol minimal exact replay 需要恢复 `DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET + TOOL_ARTIFACT`，而 text exact replay 只需要恢复 `TOOL_ARTIFACT`。这是 restore allowlist 的合理差异，但对外展示时会被解读为"protocol state 更重"。

---

# 三、Memory 指标逻辑矛盾

## ANOM-7：memory_hit_rate=0 但 skipped_step_count>0

**数据来源**：三个 memory pack 的报告

**memory_policy_controlled_v3**：
| policy | memory_hit_rate | skipped_step_count |
|---|---|---|
| memory_off | 0.00 | 0.00 |
| working_assist | 1.00 | 0.00 |
| validated_replay | 0.00 | 1.00 |
| exact_replay | 0.00 | 2.00 |

**memory_reuse_v3**：
| policy | memory_hit_rate | skipped_step_count |
|---|---|---|
| memory_off | 0.00 | 0.00 |
| working_assist | 1.00 | 0.00 |
| validated_replay | 0.00 | 1.00 |
| exact_replay | 0.00 | 2.00 |

**memory_dual_mode_fairness_v3 (text 侧)**：
| policy | memory_hit_rate | skipped_step_count |
|---|---|---|
| memory_off | 0.00 | 0.00 |
| working_assist | 0.60 | 0.00 |
| validated_replay | 0.00 | 0.60 |
| exact_replay | 0.00 | 1.20 |

**一致的规律**：`memory_hit_rate > 0` 只出现在 `working_assist`。所有 `validated_replay` 和 `exact_replay` 行都是 0.00——尽管这些行确实跳过了步骤（`skipped_step_count ≥ 0.60`）。

**`memory_hit_rate` 的实际含义**：它度量的是 assist 路径（用历史记忆结果辅助当前路由决策）的命中率，不是 replay 路径（直接跳过计算步骤）的命中率。名称 `memory_hit_rate` 暗示"记忆命中率"，但实际排除了在赛题语境下最重要的命中——replay skip。

## ANOM-8：memory_dual_mode_fairness_v3 中 protocol 侧的 reuse_gain 为负数

**文件**：`v3_api_repeat3_suite/benchmarks/memory_dual_mode_fairness_v3/benchmark_compare.csv`

| reuse_axis | text_reuse_gain | protocol_reuse_gain |
|---|---|---|
| validated_replay | +0.053 | **-0.152** |
| exact_replay | +0.326 | **-0.126** |

protocol validated_replay 的 reuse_gain 是负数——开启记忆复用后协议侧比 baseline（memory_off）更差。这与 `memory_policy_controlled_v3` 中 protocol exact_replay 的 `reuse_gain=+0.67` 形成矛盾。

**差异原因**：`memory_dual_mode_fairness_v3` 是跨 mode 对照，变量缠绕（mode + runtime_reuse_contract + restore_object_class）。`memory_policy_controlled_v3` 是 protocol-only 单变量。同一个 policy（validated_replay/exact_replay）在两个 pack 中的效益方向相反——这说明 cross-mode 的 memory fairness 实验中有未被控制的变量在主导结果。

---

# 四、Negative Control 真实性异常

## ANOM-9：15 个标记为 negative control 的 task 中只有 3 个实际失败

**文件**：`v3_api_repeat3_suite/SUMMARY.md:36`

```
typed_state_consumer_sensitivity_v3:
  failures={'text': 0, 'protocol': 3}
  expected_negative_control_failures={'text': 0, 'protocol': 15}
```

**报告声称**（`benchmarks/typed_state_consumer_sensitivity_v3/benchmark_report.md:39-43`）：
```
missing_decision_failure_rate = 1.00
wrong_decision_mistool_rate = 1.00
wrong_decision_misroute_rate = 0.00
expected_negative_control_failure_count = 15
unexpected_task_failure_count = 0
```

**矛盾**：
- 报告声明 `expected_negative_control_failure_count=15`，但 SUMMARY 显示 `failures=3`
- 报告声明 `missing_decision_failure_rate=1.00`（缺失 EXECUTOR_DECISION_PACKET 的 task 100% 失败）
- 报告声明 `wrong_decision_mistool_rate=1.00`（错误 packet 的 task 100% 走错 tool）
- 如果这两个 rate 都是 1.00，那么 failures 至少应该是这 2 类 × 每个 family × 3 repeat 的总和，但只有 3

**12 个被标记为应失败的 task 通过了。** 这些 task 的 `audit_disable_state_kinds` 被设为包含 `EXECUTOR_DECISION_PACKET`，意味着它们应该在缺少 decision packet 的情况下执行，预期会失败——但它们没有失败。

## ANOM-10：Rich helper 全部 disable 后零 impact——但 visibility 数据显示 executor 应该"看到"它们

**文件**：`benchmarks/typed_state_consumer_sensitivity_v3/benchmark_report.md:47-52`

| disable variant | task_count | failure_rate | route_misfire_rate | tool_misfire_rate |
|---|---:|---:|---:|---:|
| disable_channel_snapshot | 15 | 0.00 | 0.00 | 0.00 |
| disable_ranked_evidence_bundle | 15 | 0.00 | 0.00 | 0.00 |
| disable_replay_eligibility_bundle | 15 | 0.00 | 0.00 | 0.00 |
| disable_tool_candidate_set | 15 | 0.00 | 0.00 | 0.00 |

**60 个 disable task，全部零 impact。**

然而同一份报告 (:61-75) 的 Transfer Truth Summary 显示：

| metric | value |
|---|---|
| feature_bundle_executor_visibility_rate | 0.62 |
| channel_snapshot_executor_visibility_rate | 0.50 |
| tool_candidate_executor_visibility_rate | 0.50 |
| ranked_evidence_executor_visibility_rate | 0.00 |

**visibility rate 度量的是 executor 的 input contract 中包含了该 state kind**——即"允许读取"。不代表 executor 真读了、真用了。0.50-0.62 的 visibility rate 与 0.00 的 disable impact 之间的差距说明：

> Executor 的 input contract 声明了需要这些 state kind，但实际执行路径不依赖它们。这些 rich object 是"形式上的可见性"，不是"功能上的依赖性"。

---

# 五、Open Surface 数据不可信

## ANOM-11：16ms/task 与 contest 包的 3500ms/task 相差 200 倍

**文件**：`v3_api_repeat3_suite/open_surfaces/open_system_comparison_v1/open_report.md`

| runtime_arm | memory_policy | task_ms |
|---|---|---|
| statebus_protocol_open | memory_off | 16.02 |
| statebus_text_open | memory_off | 16.01 |
| langgraph_native_text_open | memory_off | 18.33 |
| external_text_open | memory_off | 38.07 |

**对比**：`contest_dual_mode_controlled_v3` 中同类 LLM 调用的 task 耗时 3300-3500ms。
**16ms 没有容下一个 LLM HTTP round-trip 的时间。** 这些 open surface task 运行的代码路径不包含真实 LLM 调用。

## ANOM-12：四个不同的 runtime arm 产出完全相同的 reuse 指标

**文件**：`v3_api_repeat3_suite/open_surfaces/open_system_comparison_v1/open_report.md`

| metric | statebus_protocol | statebus_text | langgraph_native | external_text |
|---|---:|---:|---:|---:|
| replay_hit_rate | 0.83 | 0.83 | 0.83 | 0.83 |
| skipped_step_count | 1.67 | 1.67 | 1.67 | 1.67 |
| reuse_gain | 0.42 | 0.42 | 0.42 | 0.42 |

四个 runtime arm 有不同的 memory backend（StateBus SQLite+FAISS vs LangGraph checkpoint vs external text store），不同的 task 执行路径，不同的 replay 逻辑——但 reuse 指标完全相同到小数点后两位。

**这不是真实运行能产生的数据。** 这些值来自于一个共享的确定性 stub 或预计算的模板值。

## ANOM-13：Open surface task 的 llm_tokens=19-48——不可能

| runtime_arm | memory_policy | llm_total_tokens |
|---|---|---|
| statebus_protocol_open | memory_off | 30.75 |
| statebus_protocol_open | native_reuse_on | 19.22 |
| external_text_open | memory_off | 48.00 |

30 个 token 不足以容纳一个 Summarizer 的完整输出。contest 包的 Summarizer 消耗 300-400 tokens。

---

# 六、其他数据模式异常

## ANOM-14：Exact match == Admissible match（无容错空间）

多个 pack 的 `exact_match_rate == admissible_match_rate`：

| pack | exact_match | admissible_match |
|---|---|---|
| typed_state_mechanism_v3 | 0.75 | 0.75 |
| typed_state_consumer_sensitivity_v3 | 0.75 | 0.75 |
| external_text_baseline_audit_v3 | 0.75 | 0.75 |

admissible_match 本应比 exact_match 更大——它允许 bounded alternative（容许的替代 route/tool）。两者完全相等意味着所有非 exact 的 task 都直接到了 wrong_family（0.25），而不是落在 admissible 区间。

## ANOM-15：checkout_release_chain 在多个 pack 中完全相同的失败率

checkout family 在 `contest_dual_mode_controlled_v3`、`typed_state_mechanism_v3`、`external_text_baseline_audit_v3` 中都有 `wrong_family_rate=0.25`。同一个 family 在不同 mode、不同 pack、不同 transfer strategy 下产出完全相同的错误率——说明这个 family 的 25% 失败来自 task 设计或 corpus 问题，与通信方式无关。

## ANOM-16：memory_dual_mode_fairness_v3 的 text hidden field leak 已修复

上一轮（`v3_api_repeat3_suite_20260614_230949`）中该 pack 的 withheld 包含 `text_hidden_field_leak_detected`。本轮 SUMMARY 中该 pack 的 withheld 只有 `formal_stability_gate_failed`——leak 已被修复。Object parity gate 从 "not_yet" 变为 "pass"。这是本轮相对于上轮的正面变化。

---

# 七、异常影响矩阵

| 异常编号 | 类型 | 影响的结论 | 严重度 |
|---|---|---|---|
| ANOM-1,2,3 | 记账错误 | handoff bytes 在 text 和 protocol 之间被抄写，幅度数据不可信 | 高 |
| ANOM-4 | 反直觉 | 协议在内部对比中更重，对外 claim "协议更轻"缺少 protocol-only 支撑 | 高 |
| ANOM-5 | 反直觉 | token 消耗协议 > 文本（+23%），与赛题"token 节省"矛盾 | 高 |
| ANOM-6 | 反直觉 | exact replay 下协议 state 是文本的 2 倍 | 中 |
| ANOM-7 | 命名混淆 | memory_hit_rate 不度量 replay 命中，解读容易出错 | 中 |
| ANOM-8 | 矛盾数据 | 同一 policy 在不同 pack 中 reuse_gain 方向相反 | 中 |
| ANOM-9,10 | 失效验证 | Negative control 12/15 未触发，rich helper disable 零 impact | 高 |
| ANOM-11,12,13 | 不可信数据 | Open surface 的 timing/token/reuse 值不是真实运行产物 | 高 |
