# Issue Discovery Smoke 深度分析

日期：2026-06-16 20:30
运行：`runs/issue_discovery_smoke_20260616_203016/`
5 个 block，deterministic, repeat=1

---

## 一、contest_correctness (3 tasks × 2 modes)

| 模式 | route_exact | admissible | wrong_family | 对称? |
|---|---|---|---|---|
| text | **1.00** | **1.00** | 0.00 | ✅ |
| protocol | **1.00** | **1.00** | 0.00 | ✅ |

Per-task：

| task | mode | route | tool | 正确性 |
|---|---|---|---|---|
| auth-distractor | text | auth_session_drift | tool.auth_session_repair | exact_match |
| auth-distractor | protocol | auth_session_drift | tool.auth_session_repair | exact_match |
| billing-clean | text | worker_queue_starvation | **tool.retry_storm_relief** | admissible (tool 错了) |
| billing-clean | protocol | worker_queue_starvation | **tool.retry_storm_relief** | admissible |
| deploy-clean | text | db_pool_saturation | tool.db_pool_triage | exact_match |
| deploy-clean | protocol | db_pool_saturation | tool.db_pool_triage | exact_match |

**Text 和 protocol 完全对称。** billing family 两端都选了 `tool.retry_storm_relief` 而不是预期的 `tool.worker_queue_triage`——route 正确，tool 匹配精度问题。

text side: `whole_lane_text_guard_pass_rate=0.00, hidden_field_leak_rate=1.00` — 预期行为，handoff 现在显式携带 "Route:" / "Tool:" 字段，guard 正确检测。

---

## 二、typed_state_fairness (4 tasks)

| 指标 | 值 |
|---|---|
| route_exact | 1.00 |
| admissible | 0.50 |
| wrong_family | 0.00 |

Per-task：

| task | handoff | route | tool | 正确性 |
|---|---|---|---|---|
| checkout-clean | **natural_handoff_text** | db_pool_saturation ✅ | **tool.collect_more_evidence** ❌ | mismatch |
| checkout-clean | **state_packet_minimal** | db_pool_saturation ✅ | **tool.db_pool_triage** ✅ | **exact_match** |
| checkout-distractor | **natural_handoff_text** | db_pool_saturation ✅ | **tool.collect_more_evidence** ❌ | mismatch |
| checkout-distractor | **state_packet_minimal** | db_pool_saturation ✅ | **tool.db_pool_triage** ✅ | **exact_match** |

**这是公平性修复后的关键反转。** 之前 natural_handoff_text 的 executor 能通过 `build_feature_bundle()` 的独立词法匹配纠正 retriever 的错误，state_packet_minimal 不能。去掉 text 侧的词法恢复后：

- natural_handoff_text：route 正确（handoff 文本携带），但 tool 信息在 handoff 文本中缺失或不完整 → executor 回退到 `tool.collect_more_evidence`
- state_packet_minimal：route 和 tool 都从 EXECUTOR_DECISION_PACKET 正确读取 → **精确匹配**

**typed state 的结构化精度优势现在能体现。** natural_handoff 的文本格式不能可靠传递 tool 选择，而 msgpack 格式的 decision packet 可以。

自然文本 handoff 中 "Tool:" 字段被正确写入 route 但 tool 似乎没有被正确填充。需要确认 retriever 在构建 handoff 文本时是否把所有必要字段都写入了。

---

## 三、planner_validate (3 tasks)

| 指标 | 值 |
|---|---|
| route_exact | **1.00** |
| admissible | **1.00** |
| wrong_family | 0.00 |
| planner_llm_request_count | 3.00 |
| planned_step_count | 12.00 (3×4=12) |

3 个 task 全部 `exact_match`。validate-first 合同生效：deterministic LLM 产出 4-step plan，validate 通过，executor 正确执行。

**但 `true_invariant_violation_count=3.00` 需要解释。** `expected_gate_block_count=0.00`。3 个 task 全部 completed + exact_match，却报告 3 个 invariant violation。这可能是：

- `true_invariant_violation_count` 计数了 validate step 的某个检查项但不是 gate block
- 或者是 planner repair 相关计数误归入了 invariant violation
- 或者是 deterministic LLM 产出 plan 时某条 contract 校验触发了计数

**3 个 task 实际执行结果全部 correct，violation 计数是正确的记录了某类非阻断性校验失败，但需要确认它不应该被解读为"系统不稳定"。**

---

## 四、memory_contract (3 tasks × 2 modes)

| 模式 | route_exact | wrong_family | 
|---|---|---|
| text | 0.00 | 0.00 |
| protocol | 0.00 | 0.00 |

Per-task：

| task | mode | route | tool | 标注 |
|---|---|---|---|---|
| cold_start | text | db_pool_saturation | tool.collect_more_evidence | **mismatch** |
| cold_start | protocol | db_pool_saturation | tool.db_pool_triage | **mismatch** |
| assist | text | db_pool_saturation | tool.collect_more_evidence | **mismatch** |
| assist | protocol | db_pool_saturation | tool.db_pool_triage | **mismatch** |

**Protocol 侧的 route 和 tool 看起来都是正确的（db_pool_saturation / tool.db_pool_triage），但被标为 mismatch。** 这是 custom task set（`memory-dual-01-*`）的 expected route/tool 可能定义的和 checkout family 默认值不一致。需要检查 `task_sets/memory_contract.yaml` 确认 expected 值。

Text 侧 tool=tool.collect_more_evidence（和 typed_state_fairness 同样的问题：自然文本 handoff 无法可靠传递 tool 选择）。

---

## 五、consumer_negative_controls (4 tasks)

| task | status | route | tool | 正确性 |
|---|---|---|---|---|
| rich-full-001 | completed | db_pool_saturation | tool.db_pool_triage | exact_match |
| minimal-baseline-001 | completed | db_pool_saturation | tool.db_pool_triage | exact_match |
| **missing-decision-001** | **failed** | — | — | — |
| wrong-decision-001 | completed | db_pool_saturation | tool.collect_more_evidence | mismatch |

**Negative control 全部按预期工作：**
- missing EXECUTOR_DECISION_PACKET → `SchemaValidationError: step execute missing required input kinds` → **正确失败**
- wrong EXECUTOR_DECISION_PACKET → executor 拒绝了错误 packet → 回退到 `tool.collect_more_evidence` → **正确的降级**

---

## 六、关键发现汇总

### 正向

| 发现 | 证据 |
|---|---|
| **公平性修复生效** — text/protocol 完全对称 | contest 6 个 task 两端结果完全相同 |
| **state_packet_minimal 现在优于 natural_handoff_text** | typed_state_fairness：state_packet 2/2 exact，natural 0/2 exact |
| **negative control 正确工作** | missing → fail, wrong → degrade |
| **Planner validate-first 3/3 exact_match** | 4-step plan 正确执行 |

### 需要进一步确认

| 发现 | 位置 |
|---|---|
| natural_handoff_text 不能可靠传递 tool 选择（4 个 task 全落 tool.collect_more_evidence） | typed_state_fairness + memory_contract |
| `true_invariant_violation_count=3.00` 但所有 task exact_match | planner_validate |
| protocol memory_contract 的 route/tool 值正确但被标 mismatch | memory_contract |
| billing family tool 精度（两端都选 retry_storm_relief 而非 worker_queue_triage） | contest_correctness |
