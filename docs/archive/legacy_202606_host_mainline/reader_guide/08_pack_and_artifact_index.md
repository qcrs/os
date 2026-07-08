# Pack 与 Artifact 索引

本文档是导航地图，防止读者在 pack 名、run 名和 artifact 路径里迷路。

它回答：

1. 每个主要 pack 回答什么。
2. 每个 pack 不回答什么。
3. 对应的 artifact 在哪。

---

## 1. 如何使用这份索引

- 本文档不是结果解释本身——结果解释见 [`06_result_readout_and_claim_boundary.md`](./06_result_readout_and_claim_boundary.md)
- 本文档是"去哪找证据"的地图
- 若要理解每个 pack 在验证什么，先看 [`04_task_and_benchmark_design_with_walkthrough.md`](./04_task_and_benchmark_design_with_walkthrough.md)
- 若要理解系统为什么会这样设计，先看 [`03_system_architecture_and_dataflow_explainer.md`](./03_system_architecture_and_dataflow_explainer.md)

---

## 2. headline / support / audit 总表

| 对象 / pack 名 | 当前角色 | 回答什么 | 不回答什么 | authoritative artifact | support artifact |
|---|---|---|---|---|---|
| `superiority_comm_v1` | active communication headline | protocol `llm_total_tokens < text`、quality floor、communication gate | latency superiority closure、formal stability gate | `runs/superiority_comm_v1_api_repeat3_post_gate_semantics_split/` | `runs/superiority_comm_v1_api_repeat1_post_summarizer_schema_native_contract_repair/` |
| `contest_honest_headline_v1` | historical frozen formal headline / carrier-isolation object | API repeat=10 下 `text_whole_lane` vs `state_packet_minimal` 的 control compactness、typed-state handoff、S1/S2/replay runtime behavior | external pure-text baseline、LangGraph innovation、不再承担当前 active communication headline | `runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/` | `runs/contest_honest_headline_goal3_repeat_runtime_det_r10_20260618_145812/` |
| `superiority_memory_v1` | formal-secondary memory effect object | exact-replay-backed `skip_execute` effect | latency superiority、overall superiority | `runs/superiority_memory_v1_api_repeat3_post_replay_contract_hardening/` | — |
| `typed_state_mechanism_v3` | formal-secondary | protocol-only `natural_handoff_text` vs `state_packet_minimal` 机制真实性 | dual-mode headline、external text baseline、replay efficiency | `runs/typed_state_mechanism_v3_api_repeat1_current_branch_refresh_20260623/` | — |
| `typed_state_consumer_sensitivity_v3` | formal-secondary support | minimal `EXECUTOR_DECISION_PACKET` 消费敏感性 + 负控降级 | typed-state 机制主 headline | `runs/typed_state_consumer_sensitivity_v3_api_repeat1_current_branch_refresh_20260623/` | — |
| `planner_support_v3` | formal-secondary | yaml vs llm plan_source 的独立 planner 支撑面 | communication 或 state claim；赛题主 headline | `tasks/planner_support_v3_benchmark.yaml` | — |
| `memory_policy_controlled_v3` | formal-secondary | protocol carrier-fixed memory policy 单变量归因 | text vs protocol | `tasks/memory_policy_controlled_v3_benchmark.yaml` | — |
| `memory_reuse_v3` | formal-secondary | replay-aware memory reuse 是否真实减少重复工作 | text vs protocol | `tasks/memory_reuse_v3_benchmark.yaml` | — |
| `memory_dual_mode_fairness_v3` | audit-only | dual-mode fairness/object-parity surface | replay proof、typed-state authenticity | `tasks/memory_dual_mode_fairness_v3_benchmark.yaml` | — |
| `external_text_baseline_audit_v3` | audit-only | 独立 external text baseline audit surface | contest headline、typed-state mechanism | `tasks/external_text_baseline_audit_v3_benchmark.yaml` | — |
| `text_definition_audit_v3` | audit-only | inline boundary 与 whole-lane pure text 的定义分离 | formal dual-mode headline | `tasks/text_definition_audit_v3_benchmark.yaml` | — |
| `carrier_microbench_v3` | audit-only | minimal text/state packet 的 engineering 差异 | 纯文本 vs structured 正式 headline | `tasks/carrier_microbench_v3_benchmark.yaml` | — |
| `typed_state_authenticity_v3` | legacy-compat | 旧引用的自然文本 vs minimal state packet surface | 正式机制 claim（优先读 `typed_state_mechanism_v3`） | `tasks/typed_state_authenticity_v3_benchmark.yaml` | — |
| `typed_state_full_rich_audit_v3` | support-only | full-rich audit 对象是否仍可显式恢复 | formal headline | `tasks/typed_state_full_rich_audit_v3_benchmark.yaml` | — |
| `uncertainty_audit_v1` | audit-only | residual/uncertainty surface | headline | `tasks/contest_dual_mode_controlled_v3_benchmark.yaml` | — |

---

## 3. Communication 相关对象索引

### 3.1 Frozen Headline（冻结主结论）

- **对象**：`contest_honest_headline_v1`
- **roles**：frozen formal headline
- **answer**：`text_whole_lane` vs `state_packet_minimal` 在 API repeat=10 下是否成立 control compactness + typed-state handoff + S1/S2/replay behavior（历史 frozen formal headline 口径）
- **not answer**：external pure-text baseline superiority
- **authoritative**：`runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/`
- **support**：`runs/contest_honest_headline_goal3_repeat_runtime_det_r10_20260618_145812/`

### 3.2 Active Communication Headline（活跃通信主结论）

- **对象**：`superiority_comm_v1`
- **roles**：active communication headline object
- **answer**：`protocol llm_total_tokens < text` 是否稳定；quality floor 是否稳定；communication gate 是否 pass
- **not answer**：latency superiority closure；formal stability gate
- **current status**：正式 run artifact 已落盘（`runs/superiority_comm_v1_api_repeat3_post_gate_semantics_split/`）；`docs/reports/current_task_results_overview_20260622.md` 提供冻结口径补充

### 3.3 Historical Carrier-Isolation Object

- **对象**：`contest_dual_mode_controlled_v3`
- **roles**：internal controlled composite surface（已降读）
- **answer**：`text_strict_pure_lane` vs `state_packet_minimal` 的内部受控 mainline handoff 对照
- **not answer**：contest-facing pure-text headline
- **note**：不再承担 contest-facing headline；只保留内部 controlled composite 解释面

---

## 4. Typed-State 相关对象索引

### 4.1 机制包

- **对象**：`typed_state_mechanism_v3`
- **roles**：formal-secondary
- **answer**：protocol executor 真实消费 minimal typed packet；`route_exact_rate`、`tool_exact_rate`、`handoff_textual_bytes` 下降
- **not answer**：dual-mode headline；external text baseline；replay efficiency
- **authoritative**：`runs/typed_state_mechanism_v3_api_repeat1_current_branch_refresh_20260623/`

### 4.2 消费者敏感性包

- **对象**：`typed_state_consumer_sensitivity_v3`
- **roles**：formal-secondary support
- **answer**：`missing_decision_failure_rate = 1.00`；`wrong_decision_mistool_rate = 1.00`；负控按合同触发
- **not answer**：typed-state 机制主 headline
- **authoritative**：`runs/typed_state_consumer_sensitivity_v3_api_repeat1_current_branch_refresh_20260623/`

### 4.3 为什么它们是 required secondary support

typed-state 回答的是赛题的第二条轴：非文本状态传递。它们不替代 communication headline（第一条轴），但它们是赛题完整性所必需的证据。在最终报告中，typed-state 应作为 required secondary state-transfer verdict 出现。

---

## 5. Memory 相关对象索引

### 5.1 记忆主对象

- **对象**：`superiority_memory_v1`
- **roles**：formal-secondary memory effect object
- **answer**：exact-replay-backed `skip_execute` effect 是否成立；30/30 reusable rows 是否达标
- **not answer**：latency superiority；overall superiority
- **final role**：required secondary verdict（不承担 communication headline）
- **current status**：正式 run artifact 已落盘（`runs/superiority_memory_v1_api_repeat3_post_replay_contract_hardening/`）；`docs/reports/current_task_results_overview_20260622.md` 提供冻结口径补充

### 5.2 记忆策略归因

- **对象**：`memory_policy_controlled_v3`
- **roles**：formal-secondary
- **answer**：固定 `protocol + state_packet_minimal` 后只改 memory policy 的单变量归因
- **not answer**：text vs protocol

### 5.3 记忆复用证明

- **对象**：`memory_reuse_v3`
- **roles**：formal-secondary
- **answer**：固定 `state_packet_minimal` 后 replay-aware memory reuse 是否真实减少重复工作
- **not answer**：text vs protocol

### 5.4 记忆公平性审计

- **对象**：`memory_dual_mode_fairness_v3`
- **roles**：audit-only
- **answer**：dual-mode fairness/object-parity surface
- **not answer**：replay proof；typed-state authenticity

---

## 6. 当前 authoritative artifact 完整清单

### Communication mainline（已落盘）

```text
runs/superiority_comm_v1_api_repeat3_post_gate_semantics_split/
  ├── benchmark_report.md
  ├── benchmark_results.json
  ├── benchmark_compare.csv
  └── benchmark_message_breakdown.csv

runs/superiority_comm_v1_api_repeat1_post_summarizer_schema_native_contract_repair/
  ├── benchmark_report.md
  ├── benchmark_results.json
  └── benchmark_compare.csv
```

### Frozen headline（已落盘）

```text
runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/
  ├── benchmark_report.md
  ├── benchmark_results.json
  ├── benchmark_compare.csv
  ├── benchmark_message_breakdown.csv
  └── benchmark_message_sizes.md

runs/contest_honest_headline_goal3_repeat_runtime_det_r10_20260618_145812/
  ├── benchmark_report.md
  ├── benchmark_results.json
  └── benchmark_compare.csv
```

### Memory mainline（已落盘）

```text
runs/superiority_memory_v1_api_repeat3_post_replay_contract_hardening/
  ├── benchmark_report.md
  ├── benchmark_results.json
  └── benchmark_compare.csv
```

### Typed-state support（已落盘）

```text
runs/typed_state_mechanism_v3_api_repeat1_current_branch_refresh_20260623/
  ├── benchmark_report.md
  └── benchmark_results.json

runs/typed_state_consumer_sensitivity_v3_api_repeat1_current_branch_refresh_20260623/
  ├── benchmark_report.md
  └── benchmark_results.json
```

---

## 7. 历史对象与当前对象的边界

### 7.1 哪些路径只是历史背景

以下路径保留历史价值，但不能当作当前 source-of-truth：

- `runs/benchmark_suite_20260611_124126_api_repeat3/`：v1/v2 历史结果，保留旧 pack 名称和 `text_brief -> state_ref` 读法。**当前 v3 结论不应从此读取**。
- `runs/comprehensive_eval_20260607_131113/`：repeat-10 稳定性基线，但共享记忆是 assist-only。已被后续 replay-aware 主线 superseded。
- `runs/host_goal_eval_20260607_233858/` 到 `runs/host_goal_eval_20260608_113845_*`：replay-aware 18 任务链的演进序列，保留了 causal chain（因果链）但不应作为当前 formal artifact。
- `runs/host_goal_eval_20260609_085938_*`：26 任务 contest fairness surface，保留为 fairness/claim-surface hardening 证据。
- `docs/analysis/` 下的 deep critical review 文档（如 `statebus_review_*`）：反映的是更早阶段的审计状态，部分判断已被后续 frozen headline 或当前 `superiority_comm_v1` communication mainline superseded。

### 7.2 为什么不能把旧 artifact 当当前 source-of-truth

1. 旧 pack 使用了不同的 task definition、mode definition 和 reading contract
2. 旧 run 可能基于已被修复的 bug 或已被废弃的 code path
3. 旧 report 可能使用已不再作为正式 headline 指标的字段（如 `task_match_rate`）
4. 当前 formal headline 已冻结，后续如果修改 task contract、runtime gate、text/protocol object，必须视为新对象

### 7.3 当前仍然有效的历史贡献

以下知识点从历史阶段保留，仍然是正确的：
- 赛题要求要从 structured communication、non-text state transfer、memory reuse 三条线拆读
- support surface 不能冒充 headline
- text baseline、LangGraph、Planner、memory claim 不能混读
- benchmark 必须 single-variable、object-pure、artifact-visible
- openEuler / Docker / nsjail / hidden-state / KV 不属于当前 host-mainline 已完成项
