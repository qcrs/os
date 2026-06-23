# 结果详解与口径边界

本文档只讲结果，不讲完整架构。它回答：

1. 当前主要结果具体是什么。
2. 应该如何解释这些数字。
3. 哪些口径不能上读。

---

## 1. 结果先导读

当前正式结果应分三层阅读：

1. **communication headline**：`superiority_comm_v1` 在线，communication gate = `pass`。`protocol llm_total_tokens < text` 稳定成立；`repeat=3` 下已出现 planner-led latency positive signal；但 formal stability gate 仍是 `not_yet`。
2. **memory secondary**：exact-replay-backed `skip_execute` effect 成立。30/30 reusable rows 达标。但 latency superiority 未闭合。
3. **typed-state secondary**：非文本状态传递机制成立。minimal typed packet 被真实消费，缺失/错误包触发预期降级。但不在 active headline 里。

**不要试图把所有结果揉成一句总 headline**。

---

## 2. Communication 结果详解

### 2.1 关键 headline 指标

以 `superiority_comm_v1` 的 authoritative repeat=3 数据（数据源：`runs/superiority_comm_v1_api_repeat3_post_gate_semantics_split/benchmark_report.md`）：

| 指标 | text | protocol | delta (protocol - text) |
|---|---|---|---|
| `llm_total_tokens`（LLM 总 token） | 1363.33 | 1193.83 | **-169.50** |
| `planner_total_tokens`（规划器 token） | 951.11 | 886.67 | -64.44 |
| `summarizer_total_tokens`（总结器 token） | 412.22 | 307.17 | **-105.06** |
| `task_ms`（任务耗时 ms） | 4429.63 | 3968.14 | **-461.49** |
| `planner_ms`（规划耗时 ms） | 2939.50 | 2325.48 | **-614.02** |
| `retrieve_ms`（检索耗时 ms） | 46.56 | 55.98 | +9.42 |
| `summarize_ms`（总结耗时 ms） | 1213.56 | 1363.43 | +149.86 |

**逐行解读**：
- `llm_total_tokens -169.50`：token 节省是稳定事实
- 但这里必须加一条边界：`llm_total_tokens` 包含当前四角色的 LLM 调用；报告只单独拆出了 `planner_total_tokens` 与 `summarizer_total_tokens`，并没有单独给出 `Retriever` / `Executor` 的 token 子项
- `planner_ms -614.02`：当前主收益首先来自 planner——protocol prompt 更紧凑
- `summarize_ms +149.86`：当前主残差来自 summarizer——处理结构化字段需要重建关系，schema-native consumption 仍不完整
- `retrieve_ms +9.42`：Retriever 在两种模式下行为几乎相同，不是主拖累项

### 2.2 quality floor（质量底线）

在看这些指标之前，必须先知道当前系统怎么判“对”与“错”：

- 当前 scorer 的 primary correctness surface 不是 aggregate 指标本身，而是 case-level contract
- 每个 task 都显式声明 `primary_expected_route`、`primary_expected_tool`、`acceptable_routes`、`acceptable_tools`、`disallowed_families`、`abstention_allowed`
- `admissible_match_rate` 的含义不是“宽松地看着差不多就算对”，而是“结果落在 case contract 允许的 route/tool/abstention 边界内”
- `wrong_family_rate` 则专门用来检查是否落入明确禁止的 family

也就是说，当前 report 里的这些比率，是 case contract 审计结果的聚合读数，不是替代合同本身的启发式分数

| 指标 | 值 | 含义 |
|---|---|---|
| `wrong_family_rate`（错误族选择率） | 0.00 | 没有选到 disallowed family |
| `route_exact_rate`（路由精确率） | 1.00 | 所有 task 的 route 选择正确 |
| `exact_match_rate`（完全匹配率） | 0.75 | route+tool 同时完全匹配的比例 |
| `admissible_match_rate`（可接受匹配率） | 1.00 | 所有结果在 acceptable set 内 |

**quality floor 稳定**：protocol 路径不降低正确性。`exact_match_rate = 0.75` 不能被草率解读成 correctness regression。当前更保守、也更诚实的读法是：在 `admissible_match_rate = 1.00` 和 `wrong_family_rate = 0.00` 前提下，exact-name 层面的差距仍需结合 parity diagnostic 一起解释，但不能上读成 protocol 路径质量退化。

### 2.3 planner 当前角色

在 `superiority_comm_v1` 中（数据源：`runs/superiority_comm_v1_api_repeat3_post_gate_semantics_split/benchmark_report.md`）：
- `planner one-shot valid rate = 0.99`：72 个 llm task row 中仅 1 次 repair
- `planner repair attempts = 1` total across 72 llm task rows
- `planner_total_tokens_delta = -64.44`：protocol planner token 更低
- `planner_ms_delta = -614.02`：protocol planner 更快

**结论**：planner 已基本收平，但这里的“收平”只表示当前 artifact family 下它不再是主 residual，不等于“所有 role 的 LLM cost 已被完全拆账”。

### 2.4 summarizer residual 当前角色

- `summarizer_total_tokens_delta = -105.06`：token 侧 Summarizer 已经更省
- `summarize_ms_delta = +149.86`：但 wall-time 仍略高
- **根因**：protocol summarizer 虽然 token 更省，但处理结构化字段（route、docs、signals、mem 的紧凑表示）需要重建关系，schema-native consumption 仍不完整

**当前 residual 主读法**：schema-native consumption 不完整，而不是 token trimming 不够。因此不应继续沿 `field trim` / `summarizer micro-tune` 线推进。

### 2.5 parity diagnostic 当前角色

当前有两点 parity diagnostic（等价性诊断）：
- `rr-auth-distractor`：text 和 protocol 的 `exact_match_rate` 存在差异
- `rr-billing-clean`：类似差异

这两点已显著收敛但**仍只属 diagnostic parity**，不应被读成"protocol 路径调低了正确性"——`admissible_match_rate = 1.00` 说明正确性未见退化。

---

## 3. Typed-State 结果详解

### 3.1 typed-state 在当前报告里支持了什么

typed-state 回答的是赛题的第二条轴：**非文本状态传递**。

当前最重要的两个机制结论：

1. **`typed_state_mechanism_v3`**（协议专用的类型化状态机制包）：
   - protocol executor 真实消费最小 typed packet（`DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET`）
   - `route_exact_rate = 1.00`（在 protocol-only 受控条件下）
   - `tool_exact_rate = 1.00`
   - `handoff_textual_bytes` 相比 `natural_handoff_text` 明显下降

2. **`typed_state_consumer_sensitivity_v3`**（类型化状态消费者敏感性包）：
   - `minimal-baseline`：稳定完成
   - `minimal-missing-decision`：**按合同稳定 failure**（`missing_decision_failure_rate = 1.00`）
   - `minimal-wrong-decision`：**稳定 tool misfire**（`wrong_decision_mistool_rate = 1.00`）

配套 substrate 也是真实落地的：
- `protocol/channels.py` 中定义了 `DENSE_EVIDENCE`、`EXECUTOR_DECISION_PACKET`、`REPLAY_ELIGIBILITY_BUNDLE`、`EMBEDDING` 等 Channel
- `tests/test_state_channels_and_graph.py` 对 channel metadata 和 graph path 做了显式验证

### 3.2 为什么它还是 secondary

不是因为没做，而是因为 split 后主动降层：
- communication headline（`superiority_comm_v1`）只负责 cross-mode token / task_ms / quality floor
- typed-state 机制保留在 protocol-only formal-secondary surface

这个边界本身是对的——typed-state 不应替代 communication headline，二者回答不同问题。

---

## 4. Memory 结果详解

### 4.1 memory 当前能正式写什么

以 `superiority_memory_v1` 的 authoritative repeat=3 数据（数据源：`runs/superiority_memory_v1_api_repeat3_post_replay_contract_hardening/benchmark_results.json`，per-row 统计；另见 `docs/reports/current_task_results_overview_20260622.md` §3.3）：

| 指标 | 值 | 含义 |
|---|---|---|
| reusable rows | 30 | 全部 30 个 S2 rows |
| `replay_class`（回放分类） | `exact_replay = 30` / 30 | 全部命中 exact replay |
| `reuse.mode`（复用模式） | `skip_execute = 30` / 30 | 全部跳过执行步骤 |
| `matched_expectation`（期望匹配） | `true = 30` / 30 | 全部与预期合同一致 |
| `skipped_step_count`（跳过步骤数） | `> 0` 且 gate 满足 | 这条线正式证明的是 non-zero skip effect，而不是要求读者把 row-level 均值当主结论 |
| `reuse_gain`（复用收益） | `> 0` 且 gate 满足 | 这条线正式证明的是存在正复用收益，而不是把某个均值当 superiority 证据 |
| `memory_hits`（记忆命中） | 命中存在 | 说明记忆覆盖存在，但不能直接当复用收益 |
| `replay_probe_hits`（回放探测命中） | 命中存在 | 说明回放探测在工作，但不能替代 replay effect |

**因果链**：
1. `preclosure_check`（预收束检查）→ 检测到 reusable rows 有 `memory_hits` 但 `reuse.mode = none`，根因为 formal accept path 未接通
2. `post_replay_accept_fix`（回放接受修复）→ 修复后 reusable rows 正式落成 `skip_execute`，`Memory replay gate: pass`
3. `post_replay_contract_hardening`（回放合同加固）→ accept path 从 prior-side acceptance 收紧到 fresh-side fail-closed，repeat=1 和 repeat=3 都保持 closure

### 4.2 明确为什么还不能升级为 superiority claim

关键原因不在 aggregate 数字，而在 gate 合同：
- `eval/runner.py` 的 `memory_replay_evidence_gate` 只检查：
  - expected reuse mode
  - `skipped_step_count > 0`
  - `reuse_gain > 0`
- **它不 gate**：
  - `task_ms` 必须下降
  - `retrieve_ms` 必须下降
  - `summarize_ms` 必须下降

所以当前 memory line 只能诚实读成：
- replay effect 已真实发生
- step skipping 已稳定发生
- **latency superiority 仍未闭合**

### 4.3 `memory_hit_rate` 为什么不能直接当 superiority

`memory_hit_rate` 高表示"查询记忆时找到了结果"，但不等于"产生了收益"：
- `assist`（辅助）模式下有命中但无 skip（`skipped_step_count = 0`）
- 只有 `validated_replay` / `exact_replay` 模式下命中才转化为 skip

**因此**：`memory_hit_rate` 应理解为"记忆覆盖度"，不能直接当"复用收益"。

---

## 5. Claim Boundary（口径边界）

### 5.1 可以正式说什么

| 赛题轴 | 可以正式说 |
|---|---|
| **通信** | `protocol llm_total_tokens < text` 稳定成立；quality floor 稳定；communication gate = `pass`；`repeat=3` 下已有 planner-led latency positive signal |
| **状态传递** | 非文本状态传递机制已成立（formal-secondary）；`DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET` 被真实生产、传递、接收、消费；缺失/错误 packet 触发预期降级 |
| **记忆复用** | exact-replay-backed `skip_execute` effect 成立；30/30 reusable rows 达到 effect-required contract；memory final role = required secondary verdict |
| **系统完整性** | 四角色（Planner/Retriever/Executor/Summarizer）主链路已运行；`text/protocol` 双模式已运行；StateRef/mmap/SQLite/FAISS 已落地 |

### 5.2 不可以正式说什么

| 不可以说的内容 | 原因 |
|---|---|
| formal latency superiority closure | `summarize_ms` 仍有正残差，formal stability gate 仍是 `not_yet` |
| communication 在所有维度全面优于 text | 主 claim 是 control compactness，不是 end-to-end 全面胜利 |
| memory latency superiority / overall superiority | gate 不检查 `task_ms` 下降 |
| typed-state = headline | 当前是 formal-secondary，不替代 communication headline |
| `text_whole_lane` = external pure-text baseline | 它是 StateBus runtime 内部的 comparator |
| LangGraph = 核心创新 | 它只是执行图引擎外壳，核心语义在 Orchestrator |
| openEuler / Docker / nsjail 已完成 | 都属于后续阶段，当前未实现 |
| hidden-state / KV cache transfer 已实现 | 属于后续增强，当前未实现 |
| repeat=10 / openEuler delivery validation 已闭环 | 尚未进入执行面 |

### 5.3 哪些是 residual，不等于 failure

| residual（残差） | 不等于 | 真正含义 |
|---|---|---|
| `summarize_ms +149.86` | Summarizer 在 protocol 路径下失效 | 处理结构化字段需要重建关系，schema-native consumption 不完整。token 侧 summarizer 已更省（-105.06） |
| `exact_match_rate 0.75`（当前 communication authoritative artifact） | protocol 路径降低了正确性 | `admissible_match_rate = 1.00`，说明所有结果仍在可接受范围内。`exact_match_rate` 的差距需要结合 actual parity 和 exact-name pressure 一起读，不能直接上读为 correctness regression |
| `rr-auth-distractor` 与 `rr-billing-clean` 的 parity divergence | protocol 路径有 bug | 仍只属 diagnostic parity。当前 `route_exact_rate = 1.00`，正确性未见退化 |

---

## 6. 当前 gate 怎么读

### 6.1 communication gate（通信门控）

- **定义**：object-level closure gate。判断 communication 主对象是否已结束 `withheld → pass`
- **当前状态**：`pass`
- **满足条件**：object freeze 保持、`repeat=1` support 与 `repeat=3` 一致正向、quality floor 稳定、planner stability 已基本收平（0.99 one-shot valid rate，仅 1 次 repair）、unexpected failures 为 0、residual 已被约束为 bounded residual
- **读法**：communication 主对象已经结束 `withheld -> pass`；但不改变 formal stability gate 的状态

### 6.2 formal stability gate（正式稳定性门控）

- **定义**：repeat-depth / stability gate。判断 repeat=10 与纵向稳定性是否已闭合
- **当前状态**：`not_yet`
- **和 communication gate 的区别**：communication gate 判断的是"对象级证据是否充分"，formal stability gate 判断的是"是否在足够多的 repeat 轮次和足够长的时间上稳定"

### 6.3 它们为什么不是一回事

不能把 "communication gate = pass" 简化成 "全部 gate 都过了"。这两个 gate 回答不同层面的问题：

| gate | 回答什么问题 | 当前 |
|---|---|---|
| communication gate | 对象级证据是否足以正式释放 headline？ | pass |
| formal stability gate | repeat 深度和纵向稳定性是否已证明？ | not_yet |

---

## 7. 术语解释

- **`route_exact_rate`（路由精确率）**：Executor 选择的 route 与 primary expected route 完全一致的比例。
- **`exact_match_rate`（完全匹配率）**：route 和 tool 同时完全匹配的比例。
- **`admissible_match_rate`（可接受匹配率）**：结果在 acceptable set 内的比例。这个指标比 exact_match_rate 更宽松但更全面地反映"有无严重错误"。
- **`wrong_family_rate`（错误族选择率）**：选中 disallowed family 中的 route 的比例。这是最严重的错误类型，正常情况下应为 0。
- **`parity diagnostic`（等价性诊断）**：text/protocol 两侧在 exact_match_rate 等指标上的局部差异诊断。它是用来定位问题的辅助工具，不是"protocol 路径做错了"的证据。
- **`residual`（残差）**：已知但尚未闭合的结果偏差。它不等于 failure（失败），而是"还需要进一步解释和处理"的部分。
