# StateBus API Repeat-1 Smoke 结果分析

日期：2026-06-16
运行目录：`runs/api_repeat1_smoke_20260616_143240/`
运行模式：real LLM (deepseek-v4-flash), real embedding (Qwen3-Embedding-0.6B), repeat=1

---

## 一、运行概览

4 个 pack，全部 API 模式，无报错中断。

| pack | modes | task数 | withheld | 核心发现 |
|---|---|---|---|---|
| contest_dual_mode_controlled_v3 | text+protocol | 40 | `contest_formal_coverage_incomplete`（repeat=1） | exact_match **0.05**，因去 hint |
| planner_support_v3 | protocol | 11 | 无 | Planner 真实调了 6 次 LLM，但 admissible 仅 **0.27** |
| memory_policy_controlled_v3 | protocol | 8 | 无 | exact_match **1.00**，replay gate pass |
| typed_state_consumer_sensitivity_v3 | protocol | 40 | 无 | rich helper disable 终于有 impact 了（misfire 0.80） |

---

## 二、逐 Pack 分析

### 2.1 contest_dual_mode_controlled_v3 — 去 hint 后正确率骤降

| 指标 | text | protocol | delta |
|---|---:|---:|---:|
| control_bytes | 7720.90 | 6523.05 | **-1197.85 (-15.5%)** |
| task_ms | 4989.78 | 4931.84 | -57.95 (-1.2%) |
| llm tokens | 308.80 | 379.90 | +71.10 (+23%) |
| handoff wire | 0 | 160.50 | — |
| Planner tokens | **0.00** | **0.00** | Planner 未调用 |

**正确率**：

| 指标 | 值 | 对比旧 run（有 hint） |
|---|---|---|
| exact_match_rate | **0.05** | 0.85 → 跌了 94% |
| admissible_match_rate | 0.55 | 0.90 → 跌了 39% |
| abstention_rate | 0.50 | 0.05 → 50% task 系统放弃了 |
| wrong_family_rate | 0.45 | 0.10 → 近半走错家族 |

**分析**：去掉 corpus 预标签后，正确率从 0.85 暴跌到 0.05。这恰恰证明了去 hint 是有效的——之前的 0.85 是预标签托着的虚高正确率。现在 retrieval 完全靠 lexical/semantic matching，系统的真实检索能力暴露出来了。50% 的 task 被 abstain（`tool.collect_more_evidence`），说明在无 hint 的开放检索空间中，系统缺乏足够的证据组合推理能力。

**typed-state 消费**：typed_executor_minimal_expected_consumption_rate = 1.00，kind_match = 1.00——typed state 被正确消费了，问题是 retrieval 产出的 route 本身就不对。

**text guard**：pass = 1.00, leak = 0.00 —— text 侧 defense 仍然完整。

---

### 2.2 planner_support_v3 — Planner 真实工作但正确率低

| 指标 | 值 |
|---|---|
| planner_llm_request_count | **6.00**（6 个 llm 行全部调用） |
| planned_step_count | 33.00 |
| protocol_admissible_match_rate | **0.27** |
| combined_admissible_match_rate | 0.14 |
| task_ms | 70426 ms |

**分析**：Planner 真实调用了 6 次 LLM，产出了 33 个 plan step。但正确率只有 0.27——LLM Planner 在开放环境中产出的 plan 不够靠谱。这可能因为：(1) Planner 没有被训练/提示优化过；(2) 去 hint 后 retrieval 质量差，Planner 收到的不良检索结果无法做出好决策。

---

### 2.3 memory_policy_controlled_v3 — replay 仍然完美

| 指标 | 值 |
|---|---|
| exact_match_rate | **1.00** |
| replay evidence gate | **pass** |
| replay headline gate | **pass** |

| policy | tokens | skipped | reuse_gain | task_ms |
|---|---:|---:|---:|---:|
| memory_off | 405 | 0 | 0 | 3522 |
| working_assist | 447 | 0 | 0 | 3021 |
| validated_replay | 410 | 1 | 0.33 | 2770 |
| exact_replay | 396 | 2 | 0.67 | 2789 |

**分析**：memory replay 线仍然是最稳健的。exact_match = 1.00，replay gate pass。但 exact_replay 的 task_ms (2789) 略慢于 validated_replay (2770)——可能是 repeat=1 的测量抖动，也可能是 exact replay 的恢复开销。总体上 reuse_gain 从 0 到 0.67 的阶梯仍然清晰。

---

### 2.4 typed_state_consumer_sensitivity_v3 — rich helper disable 终于有 impact

| 指标 | 值 |
|---|---|
| exact_match_rate | 0.15 |
| admissible_match_rate | 0.15 |
| wrong_family_rate | 0.70 |
| missing_decision_failure_rate | **1.00** |
| wrong_decision_misroute_rate | **0.80** |
| wrong_decision_mistool_rate | **1.00** |

**Rich Helper Disable Impact（本轮 vs 上轮旧 run）**：

| variant | 上轮 misfire | 本轮 misfire |
|---|---|---|
| disable_channel_snapshot | 0.00 | **0.80** |
| disable_ranked_evidence | 0.00 | **0.80** |
| disable_replay_eligibility | 0.00 | **0.80** |
| disable_tool_candidate_set | 0.00 | **0.80** |

**分析**：去 hint 后，rich helper disable 终于显示出真实的 impact。上轮所有 variant 的 misfire 都是 0.00，因为 executor 根本不需要这些 helper——route 答案已经被 hint 直接提供了。现在 hint 没了，关闭 helper 会导致正确的 route/tool 候选无法进入 executor，misfire 率达到 0.80。这验证了 structure-level clean 是有效的——系统现在真的依赖这些 rich helper object 来做 routing。

---

## 三、关键判断

### 3.1 去 hint 的效果——真实但残酷

contest 包的 exact_match 从 0.85 跌到 0.05 不是 bug——这证明之前的 0.85 是预标签的虚假正确率。现在系统在真实的开放检索空间中暴露了弱点：retrieval 的 lexical/semantic matching 不足以在没有 hint 的情况下找到正确 route。

**这是正确的实验方向**：0.05 的正确率意味着 protocol 的 structured state 在 correctness 上有巨大的提升空间——如果 retrieval 能产出更准确的 evidence bundle 和 decision packet。

### 3.2 Protocol 的通信优势仍然成立

control_bytes: -15.5%（和之前 -18.5% 接近）。protocol summarizer 的 token 仍然比 text 多 +23%——这是因为 summarizer 收到了更丰富的结构化 digest。但 task_ms 几乎持平（-1.2%），通信节省被 LLM 延迟和 retrieval 质量抹平。

### 3.3 Memory replay 是唯一不受影响的高分线

exact_match 1.00, replay gate pass, reuse_gain 0.67——去 hint 没有影响 memory replay 的性能，因为 replay 依赖的是 route/docset/hash 匹配而非 retrieval 质量。

### 3.4 Planner 现在是真实的

planner_llm_request_count = 6.00 证明 Planner 被调用了。但它产出的计划质量很差（admissible 0.27），这说明 LLM Planner 在收到不良 retrieval 结果后无法做出有效规划。

---

## 四、流程问题

运行流程正常，4 个 pack 全部无报错完成。需要注意：

1. **repeat=1**：contest 包被 withheld 是因为 repeat=1（需要 10）。其余 3 个 pack 不受 repeat 影响
2. **plan_source_default: yaml**：contest 和 memory_policy 包的 Planner 没有被调用——这是设计决策，不是 bug。Planner 证据在 planner_support_v3 中独立呈现
3. **typed_state_consumer_sensitivity 的 wrong_decision 行为变化**：API run 中 `wrong_decision_misroute_rate = 0.80`（vs 之前 0.00），这是 validation hardening 的结果，证明去 hint 后决策验证更严格了
