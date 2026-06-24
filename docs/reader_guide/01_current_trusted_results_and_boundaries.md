# 当前可信结论总览

本文档是所有读者的最短入口。它先回答三个问题：

1. 现在到底已经正式成立了什么。
2. 现在还没有正式成立什么。
3. 哪些是 headline、哪些是 support、哪些是 audit。

---

## 1. 先给读者的结论（5-10 句话）

1. StateBus 当前是一套**四角色（Agent 角色）、三平面（控制面/状态面/记忆面）、五层架构**的多 Agent 协作运行时原型。
2. 在受控 paired contest task object 上，`protocol` 路径（`state_packet_minimal`，状态包最小路径）相比 `text` 路径（`text_whole_lane`，自然语言全通道）**稳定降低了控制面通信开销**：`protocol llm_total_tokens < text` 稳定成立（具体数字见 `superiority_comm_v1` authoritative artifact：`runs/superiority_comm_v1_api_repeat3_post_gate_semantics_split/benchmark_report.md`）。
3. 非文本状态传递（non-text state transfer）已真实成立：`protocol` 路径下 `DENSE_EVIDENCE`（稠密证据）与 `EXECUTOR_DECISION_PACKET`（执行器决策包）被 Executor（执行器）真实生产、传递、接收、消费，且缺失/错误包会触发预期降级。
4. 共享记忆复用（shared memory replay）在受控 reusable rows 上已产生真实的 `skip_execute`（跳过执行）效果：memory authoritative artifact（`runs/superiority_memory_v1_api_repeat3_post_replay_contract_hardening/`）下 30 个 reusable rows 全部命中，`skipped_step_count = 5.00`（mean），`reuse_gain = 0.12`（mean），`Memory replay gate = pass`。
5. **当前 active communication headline 是 `superiority_comm_v1`**；`communication gate = pass` 已释出，authoritative artifact 已落盘（`runs/superiority_comm_v1_api_repeat3_post_gate_semantics_split/`）。`contest_honest_headline_v1` 是历史 frozen formal headline / carrier-isolation object，不是当前 active headline。
6. **`formal stability gate`（正式稳定性门控）仍为 `not_yet`**：communication latency superiority（通信延迟优越性）尚未闭合，memory latency superiority 也未闭合。`communication gate = pass` 不等于 `formal stability gate = pass`。
7. 当前**不能**宣称 StateBus 已全面优于 external traditional pure-text multi-agent systems（外部传统纯文本多 Agent 系统）；`text_whole_lane` 是内部 comparator（对照物），不是 external pure-text baseline（外部纯文本基线）。
8. 当前**不能**宣称 openEuler / Docker / nsjail / hidden-state（隐藏状态）/ KV cache（键值缓存）传输已完成。
9. typed-state（类型化状态）、memory replay（记忆回放）都是 required secondary verdict（必需二级判定），不是 communication headline。
10. 下一阶段最缺的不是某个 hotfix，而是一套从 current split evidence 到 final delivery verdict 的 staged closure program（分阶段收束程序）。

---

## 2. 当前正式结论分层

必须有一张表明确区分 headline（主结论）、support/formal-secondary（支撑/正式二级）、audit（审计）。

| 对象名 | 当前角色 | 当前能正式说什么 | 当前不能说什么 | 主证据路径 |
|---|---|---|---|---|---|
| `superiority_comm_v1` | active communication headline（活跃通信主结论） | protocol llm_total_tokens < text 稳定；quality floor 稳定；communication gate = pass | latency superiority 仍未闭合；formal stability gate = not_yet | `runs/superiority_comm_v1_api_repeat3_post_gate_semantics_split/` |
| `contest_honest_headline_v1` | historical frozen formal headline / carrier-isolation object（历史冻结主结论） | protocol control_bytes < text；typed_state 被真实消费；S1/S2/replay runtime behavior 在 API repeat=10 下成立 | 不等于 external pure-text baseline；不等于 overall superiority closure；不再承担当前 active communication headline | `runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/` |
| `superiority_memory_v1` | formal-secondary memory effect object | exact-replay-backed skip_execute effect 成立；30/30 reusable rows 达标 | latency superiority 未闭合；overall superiority 未闭合 | `runs/superiority_memory_v1_api_repeat3_post_replay_contract_hardening/` |
| `typed_state_mechanism_v3` | formal-secondary 机制证据 | minimal typed packet 被真实生成、传递、消费 | 不能当 dual-mode headline；不能替代 communication headline | `runs/typed_state_mechanism_v3_api_repeat1_current_branch_refresh_20260623/` |
| `typed_state_consumer_sensitivity_v3` | formal-secondary 消费者敏感性 | missing_decision_failure_rate=1.00；wrong_decision_mistool_rate=1.00；负控按合同触发 | 不能升格为 typed-state 机制主 headline | `runs/typed_state_consumer_sensitivity_v3_api_repeat1_current_branch_refresh_20260623/` |
| `external_text_baseline_audit_v3` | audit-only | 独立 external text baseline 审计 surface | 不并入 contest headline 或 typed-state mechanism | `tasks/external_text_baseline_audit_v3_benchmark.yaml` |
| `memory_dual_mode_fairness_v3` | audit-only | dual-mode fairness/object-parity surface | 不承担 replay proof；text restore 兼容性受限 | `tasks/memory_dual_mode_fairness_v3_benchmark.yaml` |
| `planner_support_v3` | formal-secondary | yaml vs llm plan_source 独立 planner 支撑面 | 不与 communication/state claim 混读 | `tasks/planner_support_v3_benchmark.yaml` |

---

## 3. Authoritative Artifact 清单

### 3.1 Communication Authoritative Artifact

- **路径**: `runs/superiority_comm_v1_api_repeat3_post_gate_semantics_split/`
- **角色**: active communication headline authoritative artifact
- **包含文件**: `benchmark_report.md`、`benchmark_results.json`、`benchmark_compare.csv`、`benchmark_message_breakdown.csv`
- **回答什么**: `superiority_comm_v1` 下 `protocol llm_total_tokens < text` 是否稳定、quality floor 是否稳定、communication gate 是否 pass
- **不回答什么**: latency superiority closure；formal stability gate；memory superiority

### 3.2 Communication Support Artifact

- **路径**: `runs/superiority_comm_v1_api_repeat1_post_summarizer_schema_native_contract_repair/`
- **角色**: repeat=1 support artifact（当前 communication support）
- **回答什么**: repeat=1 下是否与 authoritative repeat=3 同向正向（`llm_total_tokens_delta < 0` 且 `task_ms_delta <= 0`）

### 3.3 Historical Frozen Headline Artifact

- **路径**: `runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/`
- **角色**: historical frozen formal headline / carrier-isolation object（历史冻结主结论）
- **包含文件**: `benchmark_report.md`、`benchmark_results.json`、`benchmark_compare.csv`、`benchmark_message_breakdown.csv`
- **回答什么**: `text_whole_lane` vs `state_packet_minimal` 在 API repeat=10 下，control compactness、typed-state handoff、S1/S2/replay runtime behavior 是否成立
- **不回答什么**: external pure-text baseline superiority；LangGraph innovation；不再承担当前 active communication headline

### 3.4 Typed-State Support Artifacts

- **机制证据**: `runs/typed_state_mechanism_v3_api_repeat1_current_branch_refresh_20260623/`
- **消费者敏感性**: `runs/typed_state_consumer_sensitivity_v3_api_repeat1_current_branch_refresh_20260623/`
- **角色**: formal-secondary state-transfer verdict
- **回答什么**: minimal typed packet 是否被真实消费；缺包/错包是否触发预期降级
- **不回答什么**: 是否等于 communication headline

### 3.5 Memory Authoritative Artifact

- **路径**: `runs/superiority_memory_v1_api_repeat3_post_replay_contract_hardening/`
- **角色**: formal-secondary memory authoritative artifact
- **包含文件**: `benchmark_report.md`、`benchmark_results.json`、`benchmark_compare.csv`
- **回答什么**: exact-replay-backed skip_execute effect 是否成立；30/30 reusable rows 是否达标
- **不回答什么**: latency superiority; overall superiority

---

## 4. 当前已经成立的结果

### 4.1 Communication（通信）当前读法

- `protocol llm_total_tokens < text`：稳定成立（见 `superiority_comm_v1` authoritative artifact：`llm_total_tokens_delta = -169.50`，对应 `text 1363.33 → protocol 1193.83`）
- `quality floor` 稳定：`wrong_family_rate = 0.00`，`admissible_match_rate = 1.00`，`route_exact_rate = 1.00`，`exact_match_rate = 0.75`
- `control_bytes` 稳定下降（见 `superiority_comm_v1` authoritative artifact：`control_bytes_delta = -1438.97`，对应 `text 12439.64 → protocol 11000.67`）
- `communication gate = pass`：object-level closure gate 已释出
- `planner one-shot valid rate = 0.99`，`planner repair attempts = 1` total across 72 llm rows：Planner 稳定性已收平
- `repeat=3` 下已出现 planner-led latency positive signal

### 4.2 Typed-State（类型化状态）当前读法

- `typed_executor_minimal_expected_consumption_rate = 0.50`：`typed_state_mechanism_v3` 的两条 protocol lane 中，只有 `state_packet_minimal` 那一半携带 minimal typed packet；这个数值反映的是该机制包正在对照 `natural_handoff_text` 与 `state_packet_minimal`
- `DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET` 被真实生产、传递、消费
- `missing_decision_failure_rate = 1.00`：缺失 EXECUTOR_DECISION_PACKET 导致稳定 failure
- `wrong_decision_mistool_rate = 1.00`：错误 EXECUTOR_DECISION_PACKET 导致工具错选
- 非文本状态传递机制已成立（formal-secondary）

### 4.3 Memory（记忆）当前读法

数据源：`superiority_memory_v1` authoritative artifact（`runs/superiority_memory_v1_api_repeat3_post_replay_contract_hardening/benchmark_report.md`）

- `exact-replay-backed skip_execute` effect 成立：30 个 reusable rows 全部命中
- `reuse.mode = skip_execute`：30/30（Reuse-mode matched rows = 30）
- `matched_expectation = true`：30/30（Effect-matched rows = 30）
- `skipped_step_count = 5.00`（mean），`reuse_gain = 0.12`（mean）
- `validated_reuse_task_count = 5.00`（mean）
- `Memory replay gate = pass`
- formal prior-contract replay accept path 已闭合

---

## 5. 当前不能误读成什么

1. **不能误读成 overall superiority（整体优越性）**：current headline 是受控 paired contest object 下的单一通信载体变量对照，不是 StateBus 在所有维度全面优于所有外部系统。

2. **不能误读成 memory superiority（记忆优越性）**：memory replay 只证明 runtime effect（跳过步骤），不证明 latency superiority（延迟优越性）。`eval/runner.py` 的 `memory_replay_evidence_gate` 只 gate `skipped_step_count > 0` 和 `reuse_gain > 0`，不 gate `task_ms` 下降。

3. **不能把 support 写成 headline**：typed-state 机制、memory replay effect 是 required secondary verdict，不是 communication headline。

4. **不能把 communication gate 和 formal stability gate 混为一谈**：communication gate 已 `pass`，但 formal stability gate 仍 `not_yet`。前者是 object-level closure，后者是 repeat-depth / stability gate。

5. **不能把 `text_whole_lane` 说成 external pure-text baseline**：它是一个内部 comparator，用于控制在同一 StateBus runtime 内的通信载体变量。它仍然复用同一套 lexical route/tool helper path 和 playbook executor。

6. **不能把 LangGraph 说成主创新**：LangGraph 是当前执行图引擎外壳，但核心业务语义仍然集中在 `Orchestrator`。当前的 graph 更像"固定 DAG + 条件路由 + 状态传播"适配层。

7. **不能把 `validate` 写成第五个 Agent**：`validate` 是 `semantic_role`（语义角色）/图节点/PlanStep 的 action 类型，不是独立的第五个 Agent 角色。系统只有四个 Agent 角色：Planner、Retriever、Executor、Summarizer。

8. **不能把 `memory` 写成脱离主方法的外挂模块**：memory 属于整体方法的一部分，需要和结构化传递、中间状态、任务编排一起理解，不应单独抽成独立系统或平行主线。

---

## 6. 当前边界与下一步边界

### 6.1 当前为什么还要保留 boundary

- communication headline 有正向 signal，communication gate 已 `pass`，但 formal stability 仍 `not_yet`
- summarizer residual（总结器残差）仍存在：`summarize_ms` 略高，schema-native consumption 仍不完整
- 两点 parity diagnostic（等价性诊断）：`rr-auth-distractor` 与 `rr-billing-clean` 的 `exact_match_rate` 差异

### 6.2 下一步允许做什么，不允许做什么

**允许**：
- 继续做 communication closure audit，审读现有 `repeat=1 / repeat=3` authoritative artifacts
- 在 communication closure criteria 已冻结并满足后，进入 `repeat=10` 作为 formal stability adjudication（正式稳定性裁定）
- 冻结三条 transition contract：communication→repeat=10、split evidence→final claim、benchmark closure→openEuler delivery validation

**不允许**：
- 不继续沿 `field trim` / `summarizer micro-tune` 线追加 patch
- 不把 repeat=1 的正向信号升级成 formal closure
- 不把 memory line 升级成 overall superiority
- 不把 `cross_lane_actual_parity` 或 `uncertainty_audit_v1` 混成 headline
- 不改 VM / openEuler / Docker / nsjail 路线
- 不在没有 final evidence program 的情况下直接拼接 final delivery claim

---

## 7. 术语解释

- **headline（主结论）**：当前可正式引用的主结论对象。headline 本身是一个 object（如 `superiority_comm_v1`），不等于"所有 gate 都过了"。headline object 可以已通过 communication gate 但仍未通过 formal stability gate。
- **active headline object（活跃主结论对象）**：当前唯一承担 communication 主结论的 benchmark 对象。当前是 `superiority_comm_v1`。
- **communication gate（通信门控）**：object-level closure gate。判断 communication 主对象是否已满足 object-level 释放条件（`withheld → pass`）。当前状态：`pass`。
- **formal stability gate（正式稳定性门控）**：repeat-depth / stability gate。判断对象是否在足够多的 repeat 轮次和时间上稳定。当前状态：`not_yet`。它不等于 communication gate，不能因为 communication gate = pass 就说"headline 已通过所有 gate"。
- **support / formal-secondary（支撑/正式二级）**：已成立但不应替代 headline 的机制证据。它在最终报告中是 required secondary verdict，不是 appendix-like optional support。
- **audit（审计）**：仅供消融分析、边界验证或历史对照的证据面。不能升格为 headline。
- **authoritative artifact（权威产物）**：当前冻结 docs 明确指向的、作为正式结论依据的 run artifact。
