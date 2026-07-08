# StateBus 总览

日期：`2026-06-11`

> 当前定位：历史演讲提纲，不是当前 active source-of-truth。
> 本文保留历史 frozen headline 叙事，只能作为背景材料阅读。
> 2026-07-06 claim-upgrade 后，当前可声明内容请优先读取：
> `docs/README.md`、`docs/improvement/README.md`、
> `docs/improvement/20_v2_comprehensive_truth_audit_20260706/00_executive_summary.md`
> 和最新 local+api 深挖文档。
> 当前仓库和当前 communication 读法请优先看：
> `docs/reports/statebus_system_method_task_and_results_explainer.md`
> `docs/reports/current_task_results_overview_20260622.md`
> `docs/reader_guide/README.md`

> 当前 active communication headline 已切到 `superiority_comm_v1`。
> 如果你在准备对外说明，不要再把本文当成当前主说明入口。

**本文只保留历史演讲组织方式，不再承担当前主说明入口。**

---

## 一、文档定位

| 问题 | 文档 | 用途 |
|-----------|--------|------|
| 当前正式主线能说什么？ | `final_claim_matrix_and_freeze_20260618` | frozen headline + claim matrix + can/cannot say |
| 系统跑出什么结果？ | `benchmark_results_interpretation` | 完整数据 + 每指标含义 + 公平性边界 |
| 系统怎么设计的？测了什么？ | `task_design_and_mode_comparison` | v3 pack 设计 + 三层差异矩阵 + pack 分工 |
| 系统内部怎么工作的？ | `architecture_and_data_flow` | 代码架构 + 数据流图 + Agent职责：谁调LLM、谁不调 |

---

## 二、核心数据速查

```
主张              状态        最强证据                         关键数据
──────────────────────────────────────────────────────────────────────
通信效率           historical contest_honest_headline_v1         historical API repeat=10 headline artifact
                              goal3_repeat_api_r10              control bytes: text 223741.2 vs protocol 192935.2

状态传递机制        frozen     contest_honest_headline_v1         protocol state_transfer_count mean 50
                              state_packet_minimal              DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET

external text审计   audit      external_text_baseline_audit_v3   external text-only audit surface
                              不并入正式headline                不与 typed-state 机制混读

记忆公平性         audit      memory_dual_mode_fairness_v3     dual-mode fairness/object-parity surface
                              restore 兼容性显式受限            不承担 frozen headline 外的广义 replay proof

记忆复用           scoped     contest_honest_headline_v1         controlled S2 replay effect
                              goal3_repeat_api_r10              actual replay rows 100, skipped steps 100

记忆策略归因        scoped     memory_policy_controlled_v3      protocol carrier-fixed policy surface
                              单变量只改 policy                replay gate 只在这里读

系统完整性          scoped     planner_support_v3               planner support surface
                              多 Agent 主链路已运行，但正式结论需按 pack gate 独立解读
```

---

## 三、路线

### 第1步：定义

> StateBus 在受控 paired contest task object 中，用 structured control + typed-state handoff 替代 whole-lane text handoff，稳定降低控制面通信开销，并证明 S1/S2/replay runtime behavior。

历史 frozen dual-mode surface 比较的是 `text_whole_lane` vs `state_packet_minimal`。它不是 external traditional pure-text baseline，不是 open-world agent benchmark，不是 LangGraph 创新证明，也不是开放 Planner 能力证明。
换句话说，它是历史阶段下的受控 paired contest object，不是当前 active communication 主结论。

### 第2步：架构

1. **控制面 vs 状态面**（`architecture_and_data_flow` §一、§六）
   - 控制面传"谁干什么"（协议消息），线上传输
   - 状态面传"实际数据"（StateRef 指针→mmap），本地零拷贝
   - `handoff_wire_bytes`（线上字节）= 真通信量；`handoff_payload_bytes`（负载字节）= 不是

2. **历史 frozen headline 下的旧角色计量假设**（`architecture_and_data_flow` §四）
   - 这里描述的是历史 frozen object 的旧拆账读法，不代表当前实现
   - 当前实现里 Retriever / Executor 也会进入 role-specific LLM contract；只是旧 frozen 叙事当时主要把差异归到 Summarizer
   - 因此本段只能当历史演讲口径，不可回灌为当前 active communication 解释

3. **三层差异矩阵**（`task_design_and_mode_comparison` §四）
   - v3 pack 需要按各自合同读取；不要把不同 pack 的模式、carrier、memory policy 混成一个变量
   - typed-state mechanism 单独用 `natural_handoff_text` vs `state_packet_minimal` 读，不和 carrier microbench 或 external text baseline 混读

### 第3步：结果

1. **通信**→ 当前正式主线优先读 `contest_honest_headline_v1` 的 API repeat=10 frozen artifact；主结论是 control-byte compactness。
2. **状态传递**→ 当前正式主线可读 `contest_honest_headline_v1` 的 `state_packet_minimal`：`DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET` 被 executor 真实消费。
3. **记忆**→ 当前正式主线只 claim controlled S2 replay effect；更广义的 memory policy 归因仍读 `memory_reuse_v3` / `memory_policy_controlled_v3`。
4. **通信变量读法**→ `carrier_microbench_v3` 只回答单一通信载体变量对照，不把 mode / carrier / memory policy 混成一个 headline。

### 第5步：诚实边界（加分项）

"我们在报告里诚实标注了四件事：`text_whole_lane` 是内部 comparator 不是 external pure-text baseline，LangGraph 是 substrate 不是主创新，Planner 在 headline 中主要是 contract compiler，memory/replay 是 controlled S2 replay 不是广义长期记忆 agent。这种诚实性比宣称'全面胜利'更有说服力。"

---

## 四、概念不要混

| 概念 | 含义 | 在哪讲 |
|------|------|--------|
| `contest_honest_headline_v1` | historical frozen formal headline: `text_whole_lane` vs `state_packet_minimal` | historical frozen object |
| `text vs protocol` | 控制面消息格式+LLM prompt | communication主张 |
| `memory_dual_mode_fairness_v3` | `text_whole_lane` vs `state_packet_minimal` 的 dual-mode memory fairness | audit fairness |
| `typed_state_mechanism_v3` | 固定 `protocol + reuse_disabled` 后只改 `natural_handoff_text` vs `state_packet_minimal` | protocol-only typed-state mechanism |
| `external_text_baseline_audit_v3` | 独立 external text 侧 surface | audit only |
| `memory_policy_controlled_v3` | 固定 `protocol + state_packet_minimal` 后只改 memory policy | protocol-only policy attribution |
| `memory_reuse_v3` | secondary protocol replay proof | protocol-only reuse |

`contest_honest_headline_v1` 是历史 frozen object；`memory_dual_mode_fairness_v3` 不回答 typed-state mechanism，也不单独回答 replay proof；`typed_state_mechanism_v3` 不回答 external text baseline；`memory_reuse_v3` 和 `memory_policy_controlled_v3` 都不回答 text-vs-protocol。
