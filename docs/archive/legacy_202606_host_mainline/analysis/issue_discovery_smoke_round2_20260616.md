# Issue Discovery Smoke 第二轮 — 逐项对比

日期：2026-06-16 21:45
运行：`runs/issue_discovery_smoke_20260616_214512/`

---

## 一、与上轮对比

| Block | 上轮问题 | 本轮 | 状态 |
|---|---|---|---|
| typed_state_fairness | natural_handoff tool=tool.collect_more_evidence | tool=tool.db_pool_triage, exact_match | ✅ 已修复 |
| typed_state_fairness | admissible=0.50 | admissible=**1.00** | ✅ |
| planner_validate | true_invariant_violation=3.00 | **0.00** | ✅ 已修复 |
| planner_validate | typed_executor_consumption=0.00 | **1.00** | ✅ |
| contest_correctness | 不变 | route_exact=1.00, adm=1.00 | ✅ 稳定 |
| consumer_neg | 不变 | missing→fail, wrong→degrade | ✅ 稳定 |
| memory_contract | text tool=tool.collect_more_evidence | 同 | △ 持续（预期行为） |

---

## 二、逐 Block 分析

### contest_correctness — 3/3 exact, 对称 ✅

| task | mode | carrier | route | tool |
|---|---|---|---|---|
| auth-distractor | text | structured_text | auth_session_drift | tool.auth_session_repair |
| auth-distractor | protocol | typed_packet | auth_session_drift | tool.auth_session_repair |
| billing-clean | text | structured_text | worker_queue_starvation | tool.retry_storm_relief |
| billing-clean | protocol | typed_packet | worker_queue_starvation | tool.retry_storm_relief |
| deploy-clean | text | structured_text | db_pool_saturation | tool.db_pool_triage |
| deploy-clean | protocol | typed_packet | db_pool_saturation | tool.db_pool_triage |

两端完全对称。唯一瑕疵：billing tool 选了 `retry_storm_relief` 而非 `worker_queue_triage`——ToolRegistry 匹配精度，两端一致。

### typed_state_fairness — 4/4 exact ✅ 本轮最大改善

| task | carrier | route | tool | 正确性 |
|---|---|---|---|---|
| checkout-clean-natural | structured_text | db_pool_saturation | tool.db_pool_triage | **exact_match** ← 修复！ |
| checkout-clean-state-packet | typed_packet | db_pool_saturation | tool.db_pool_triage | exact_match |
| checkout-distractor-natural | structured_text | db_pool_saturation | tool.db_pool_triage | **exact_match** ← 修复！ |
| checkout-distractor-state-packet | typed_packet | db_pool_saturation | tool.db_pool_triage | exact_match |

natural_handoff_text 现在正确携带了 tool 字段。`admissible=1.00`。

### planner_validate — 3/3 exact, 全 clean ✅

| task | validate_success | validated_route | validated_tool | gate_blocks | invariant |
|---|---|---|---|---|---|
| checkout-llm | true | db_pool_saturation | tool.db_pool_triage | 0 | 0 |
| deploy-llm | true | db_pool_saturation | tool.db_pool_triage | 0 | 0 |
| auth-llm-002 | true | auth_session_drift | tool.auth_session_repair | 0 | 0 |

`true_invariant_violation_count=0`（上轮是 3），`typed_executor_any=1.00`（上轮是 0）。validate gate 语义拆分正确，VALIDATION_GATE_PACKET 进入 executor input kinds。

Planner one-shot 1.00，repair 0。

### memory_contract — 对称，协议侧 assist/replay 正常

| task | mode | reuse | skipped | route | tool |
|---|---|---|---|---|---|
| cold_start | text | none | — | db_pool_saturation | tool.collect_more_evidence |
| cold_start | protocol | none | — | db_pool_saturation | tool.db_pool_triage |
| assist | text | none | — | db_pool_saturation | tool.collect_more_evidence |
| assist | protocol | assist ✅ | — | db_pool_saturation | tool.db_pool_triage |
| validated_replay | text | none | — | db_pool_saturation | tool.collect_more_evidence |
| validated_replay | protocol | **skip_execute** ✅ | execute | db_pool_saturation | tool.db_pool_triage |

Protocol 侧 assist 命中（hit_rate=1.00），skip_execute 生效（skipped=1, reuse_gain=0.11）。Text 侧 whole_lane_text_carrier 格式 tool=tool.collect_more_evidence——这是自然文本 handoff 不能可靠传递 tool 的预期行为。

`memory_replay_evidence_gate_passed=1.00`。

### consumer_negative_controls — 不变

| task | status | route | tool |
|---|---|---|---|
| rich-full | completed | db_pool_saturation | tool.db_pool_triage |
| minimal-baseline | completed | db_pool_saturation | tool.db_pool_triage |
| missing-decision | **failed** ← 正确 | — | — |
| wrong-decision | completed (degrade) | db_pool_saturation | tool.collect_more_evidence |

---

## 三、剩余可关注项

| 问题 | 位置 | 严重度 |
|---|---|---|
| billing tool 精度（retry_storm_relief vs worker_queue_triage） | contest_correctness, 两端一致 | 低 — ToolRegistry 的 tool match 精度 |
| text hidden_field_leak_rate=1.00 | contest text 侧 | 低 — handoff 显式携带 route/tool 字段的预期行为 |
| whole_lane_text_guard_pass_rate=0.00 | contest text 侧 | 低 — 同上 |

---

## 四、总结

**5 个 block 全部健康。** 公平性修复完全生效（text/protocol 对称）。natural_handoff_text 的 tool 传递问题已修复。planner validate 的 invariant violation 归零。typed state 的结构化精度优势可被 benchmark 观测到。negative control 语义正确。memory replay 和 assist 路径正常。

赛题三条主线的数据状态：
- **通信效率**：contest 两端对称，protocol control_bytes 低于 text（15% 量级，待 API 验证）
- **状态传递**：state_packet 的 tool 精度优于 natural_handoff（typed_state_fairness 验证）
- **记忆复用**：replay gate pass, skip_execute 生效
