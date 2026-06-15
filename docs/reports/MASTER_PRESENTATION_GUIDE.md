# StateBus 总览

日期：`2026-06-11`

**三份文档按"数据→设计→架构"递进。本文档是串联入口。**

---

## 一、文档定位

|-----------|--------|------|
| 系统跑出什么结果？ | `benchmark_results_interpretation` | 完整数据 + 每指标含义 + 公平性边界 |
| 系统怎么设计的？测了什么？ | `task_design_and_mode_comparison` | v3 pack 设计 + 三层差异矩阵 + pack 分工 |
| 系统内部怎么工作的？ | `architecture_and_data_flow` | 代码架构 + 数据流图 + Agent职责：谁调LLM、谁不调 |

---

## 二、核心数据速查

```
主张              状态        最强证据                         关键数据
──────────────────────────────────────────────────────────────────────
通信效率           ⚠️ scoped  contest_dual_mode_controlled_v3   当前 formal surface
                              communication 专用包              repeat/API 正式证据另跑

状态传递机制        ⚠️ scoped  typed_state_mechanism_v3          protocol-only mechanism surface
                              state_packet_minimal              DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET

external text审计   ⚠️ audit   external_text_baseline_audit_v3   external text-only audit surface
                              不并入正式headline                不与 typed-state 机制混读

记忆公平性         ⚠️ audit    memory_dual_mode_fairness_v3     dual-mode fairness/object-parity surface
                              restore 兼容性显式受限            不承担 replay proof

记忆复用           ⚠️ scoped  memory_reuse_v3                   protocol-only replay proof
                              memory_policy_controlled_v3       carrier-fixed policy attribution

记忆策略归因        ⚠️ scoped  memory_policy_controlled_v3      protocol carrier-fixed policy surface
                              单变量只改 policy                replay gate 只在这里读

系统完整性          ⚠️ scoped  planner_support_v3               planner support surface
                              多 Agent 主链路已运行，但正式结论需按 pack gate 独立解读
```

---

## 三、路线

### 第1步：定义

> StateBus 是四个 Agent（Planner/Retriever/Executor/Summarizer）通过两种模式协作的运行时。当前 formal dual-mode surface 比较的是 `text_strict_pure_lane` vs `state_packet_minimal` 这两个受控 mainline handoff object；它不是 external traditional pure-text baseline，也不是单一通信载体变量对照。

### 第2步：架构

1. **控制面 vs 状态面**（`architecture_and_data_flow` §一、§六）
   - 控制面传"谁干什么"（协议消息），线上传输
   - 状态面传"实际数据"（StateRef 指针→mmap），本地零拷贝
   - `handoff_wire_bytes`（线上字节）= 真通信量；`handoff_payload_bytes`（负载字节）= 不是

2. **三个不调LLM的Agent + 一个调的**（`architecture_and_data_flow` §四）
   - Retriever/Executor 不调 LLM：两种模式产出完全相同
   - Summarizer 调 LLM：text 下收到原材料（原始 evidence），proto 下收到加工品（上游提取的结构化结论）——token 差异的来源

3. **三层差异矩阵**（`task_design_and_mode_comparison` §四）
   - v3 pack 需要按各自合同读取；不要把不同 pack 的模式、carrier、memory policy 混成一个变量
   - typed-state mechanism 单独用 `natural_handoff_text` vs `state_packet_minimal` 读，不和 carrier microbench 或 external text baseline 混读

### 第3步：结果

1. **通信**→ 当前只读 v3 surface 和本地 deterministic gates；历史百分比不能直接替代当前 v3 formal rerun
2. **状态传递**→ 只读 `typed_state_mechanism_v3`：`DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET` 是否被 executor 真实消费
3. **记忆**→ 见 §四：replay 只按 `memory_reuse_v3` / `memory_policy_controlled_v3` 的 gate 读取；历史百分比不能替代当前 v3 正式 rerun

### 第5步：诚实边界（加分项）

"我们在报告里诚实标注了三件事：assist_only不work所以不claim、state_transfer的wire差异来自共享StatePool而非'纯文本通信'、受控包里Planner不工作是为了控制变量。这种诚实性比宣称'全面胜利'更有说服力。"

---

## 四、三个概念不要混

| 概念 | 含义 | 在哪讲 |
|------|------|--------|
| `text vs protocol` | 控制面消息格式+LLM prompt | communication主张 |
| `memory_dual_mode_fairness_v3` | `text_whole_lane` vs `state_packet_minimal` 的 dual-mode memory fairness | audit fairness |
| `typed_state_mechanism_v3` | 固定 `protocol + reuse_disabled` 后只改 `natural_handoff_text` vs `state_packet_minimal` | protocol-only typed-state mechanism |
| `external_text_baseline_audit_v3` | 独立 external text 侧 surface | audit only |
| `memory_policy_controlled_v3` | 固定 `protocol + state_packet_minimal` 后只改 memory policy | protocol-only policy attribution |
| `memory_reuse_v3` | protocol replay proof | protocol-only reuse |

`memory_dual_mode_fairness_v3` 不回答 typed-state mechanism，也不单独回答 replay proof；`typed_state_mechanism_v3` 不回答 external text baseline；`memory_reuse_v3` 和 `memory_policy_controlled_v3` 都不回答 text-vs-protocol。
