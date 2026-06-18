# 全量 API Repeat-3 深度逐任务分析

日期：2026-06-16 22:12
运行：`/home/qcrs/statebus/runs/host_full_api_repeat3_v3_20260616_221231/`

---

## 一、contest_dual_mode_controlled_v3 — 逐任务拆解

### 1.1 正确率面

20 个 case × 2 mode = 40 task run。6 个 text mismatch + 6 个 protocol mismatch。

**Text mismatches**：

| task | retrieve | execute | 问题类型 |
|---|---|---|---|
| billing-clean | worker_queue_starvation(0.95) | worker_queue_starvation/tool.retry_storm_relief | **tool 错** |
| billing-distractor | worker_queue_starvation(0.95) | worker_queue_starvation/tool.retry_storm_relief | **tool 错** |
| billing-ambiguous | worker_queue_starvation(0.75) | worker_queue_starvation/tool.retry_storm_relief | **tool 错** |
| billing-reusable | worker_queue_starvation(0.95) | worker_queue_starvation/tool.retry_storm_relief | **tool 错** |
| checkout-ambiguous | generic_triage(0.0) | generic_triage/collect_more_evidence | **route+tool 错** |
| deploy-ambiguous | generic_triage(0.0) | generic_triage/collect_more_evidence | **route+tool 错** |

**Protocol mismatches**：

| task | retrieve | execute | 问题类型 |
|---|---|---|---|
| billing-clean | **cache_invalidation**(0.95) | worker_queue_starvation/tool.retry_storm_relief | retriever 错, executor 纠正了 route |
| billing-distractor | worker_queue_starvation(0.95) | worker_queue_starvation/tool.retry_storm_relief | **tool 错** |
| billing-ambiguous | worker_queue_starvation(0.75) | worker_queue_starvation/tool.retry_storm_relief | **tool 错** |
| billing-reusable | worker_queue_starvation(0.95) | worker_queue_starvation/tool.retry_storm_relief | **tool 错** |
| checkout-ambiguous | worker_queue_starvation(0.0) | generic_triage/collect_more_evidence | **route+tool 错** |
| deploy-ambiguous | generic_triage(0.0) | generic_triage/collect_more_evidence | **route+tool 错** |

### 1.2 问题定位

**billing tool 错（两端都 4/4）**：

根因在 `ToolRegistry` 的 match pattern 设计。

```
tool.retry_storm_relief: patterns=('retry storm', 'retry scheduling', 'invoice queue backlog', 'rebalance invoice consumers')
tool.worker_queue_triage: patterns=('worker queue starvation', 'worker queue stall', 'tls certificate reload', 'tls reload')
```

billing 的 corpus 文档包含 `retry storm`、`invoice queue backlog` 等措辞——这些恰好匹配 `retry_storm_relief` 的 pattern，得分 18。`worker_queue_triage` 的 pattern (`worker queue starvation`, `tls reload`) 在证据中也存在，但得分只有 11。

**两个 tool 都在 `acceptable_tools` 里**（`tool.worker_queue_triage, tool.retry_storm_relief, tool.db_pool_triage`），所以结果是 `admissible_match`，不报告为 wrong_family。

这是 corpus 措辞和 tool pattern 之间的词汇偏差。不是代码 bug，是 corpus/tool 对齐问题。

**checkout-ambiguous 和 deploy-ambiguous（两端都 generic_triage）**：

retrieval 的 feature_route 在 ambiguous 场景下回退到 generic_triage(conf=0.0)。ambiguous 证据组合的信号强度不足以触发任何一个特定 route 的判断。这是证据拓扑设计问题——ambiguous 文档在去 hint 后的信号太弱。

**protocol billing-clean 的特殊情况**：

retrieve 给了 `cache_invalidation`（完全错误），但 executor 输出了 `worker_queue_starvation`（正确）。这是在 decision packet 被拒绝后，executor 从 evidence_text 重新做了匹配。这条路径说明 protocol executor 在 decision packet 失效时有某种恢复机制——虽然 tool 仍选了 `retry_storm_relief`。

### 1.3 text hidden_field_leak 的精准位置

text 侧 `whole_lane_text_guard_pass_rate=0.00, hidden_field_leak_rate=1.00`。handoff 文本现在包含：

```
Route: db_pool_saturation.
Tool: tool.db_pool_triage.
Route source: lexical_match.
Route confidence: 0.95
```

触发 `WHOLE_LANE_TEXT_HIDDEN_FIELD_MARKERS` 中的 `"Route source:"` 和 `"Route confidence:"`。这是公平性修复后的新 handoff 格式——text lane 显式传递 route/tool 信息（不再靠 executor 自己猜）。这些字段不是"泄漏"——它们是显式的结构化传递。但 marker 定义把它们归类为 hidden field leak。

`_whole_lane_text_guard_payload`(`eval/runner.py:546-547`) 用 `any(marker in text for marker in MARKERS)` 检测。需要区分"旧 handoff 无意泄漏了结构化信息"和"新 handoff 显式传递结构化信息"。

---

## 二、memory_dual_mode_fairness_v3 — 文本/协议承载能力差异

### 2.1 逐 task 结果

**Text 侧（whole_lane_text_carrier）**：全部 20 个 task 产出 `generic_triage / tool.collect_more_evidence`。零 replay benefit（reuse=none, skipped=0）。

**Protocol 侧**：5 个 family 中 4 个完全正确（checkout/auth/cache/deploy 的 route+tool 都命中），1 个 billing tool 偏差（同 contest 包）。

| family | protocol route | protocol tool | correct? |
|---|---|---|---|
| 01 (checkout) | db_pool_saturation | tool.db_pool_triage | ✅ |
| 02 (auth) | auth_session_drift | tool.auth_session_repair | ✅ |
| 03 (cache) | cache_invalidation | tool.cache_invalidation_playbook | ✅ |
| 04 (billing) | worker_queue_starvation | tool.retry_storm_relief | △ tool 偏 |
| 05 (deploy) | db_pool_saturation | tool.db_pool_triage | ✅ |

replay 行为正确：cold_start → assist (hit_rate=1.00) → skip_execute (skipped=1) → skip_retrieve_execute (skipped=2, reuse_gain=0.67)。

### 2.2 为什么 text 端全都 generic_triage

`text_whole_lane` 的 handoff 是纯自然语言文本，不携带结构化 route/tool。text executor 收到 handoff 后无法从中提取 route/tool 信息。在当前公平性合同下（text executor 不做独立 lexical recovery），只能回退到 `generic_triage / tool.collect_more_evidence`。

这是**格式能力决定的**，不是 bug。text_whole_lane 格式的固有局限：自然语言文本无法可靠携带高密度结构化决策信息。

---

## 三、typed_state_consumer_sensitivity_v3 — wrong_decision 的行为

### 3.1 逐 task

| task family | retrieve | execute | expected |
|---|---|---|---|
| auth-rotation | auth_session_drift(0.95) | **db_pool_saturation**/collect_more_evidence | auth_session_drift |
| billing-queue | worker_queue_starvation(0.95) | **db_pool_saturation**/collect_more_evidence | worker_queue_starvation |
| checkout | db_pool_saturation(0.95) | **auth_session_drift**/collect_more_evidence | db_pool_saturation |
| deploy | db_pool_saturation(0.95) | **auth_session_drift**/collect_more_evidence | db_pool_saturation |
| inventory | cache_invalidation(0.95) | **db_pool_saturation**/collect_more_evidence | cache_invalidation |

### 3.2 wrong_decision_misroute_rate=0.00 的含义

尽管所有 5 个 task 的 execute route 都和 expected route 不同（明显的 route 错误），报告显示 `misroute_rate=0.00`。这不是"没有 misroute"——是 misroute 的**定义**不是"和 expected 不同"，而是"decision packet 的 route 没有被正确拒绝/override"。

数据说明：wrong decision packet 的 route 被成功注入了 executor，改变了执行结果——route 确实错了。但 `misroute_rate` 度量的粒度不是"route 是否错"，而是别的含义。需要阅读 `_summarize_transfer_truth_rows` 中 `wrong_decision_misroute_rate` 的计算逻辑。

---

## 四、ToolRegistry match pattern 系统性问题

billing `retry_storm_relief` vs `worker_queue_triage` 的分值差异暴露了 tool match pattern 设计中的普遍问题：

1. **pattern 与 corpus 措辞存在词汇偏差**：`retry_storm_relief` 的 pattern `('retry storm', 'invoice queue backlog')` 恰好出现在 billing 证据文档中，得分高
2. **一个 route 下多个 tool 竞争**：`worker_queue_starvation` route 下有 2 个 tool（`retry_storm_relief` 和 `worker_queue_triage`），lexical matching 选高分者
3. **acceptable_tools 包含两者**：所以选错 tool 不报 wrong_family，只降为 admissible_match——掩盖了 tool 精度问题

同样的问题可能存在于其他 family（如 checkout 的 `db_pool_triage` vs `db_query_hotfix`），只是那些 family 的 evidence 措辞恰好不触发。

---

## 五、日志证据

`logs/runtime_smoke.log`:
```
statebus smoke ok: mode=text memory_hits=0.0 messages=252.0 control_bytes=166006.0 task_ms=5163.50
statebus smoke ok: mode=protocol memory_hits=0.0 messages=252.0 control_bytes=133163.0 task_ms=4907.72
```

text/protocol 都无 memory hits（retriever 在去 hint 后 memory 命中率低）。control_bytes 差异 20%——与 contest 报告一致。

`logs/full_pytest.log`：191 passed, 0 failed。无 regression。

---

## 六、当前真实问题（不是总结，是具体定位）

| 问题 | 位置 | 根因 | 赛题相关 |
|---|---|---|---|
| billing tool 系统偏 `retry_storm_relief` | `executor_runtime.py` ToolRegistry patterns | corpus 措辞匹配 pattern 偏差 | 实验正确率 |
| checkout/deploy ambiguous 回退 generic_triage | contest corpus topology | 去 hint 后 ambiguous 证据信号太弱 | 实验正确率 |
| text hidden_field_leak 标记为泄漏 | `eval/runner.py:546` `WHOLE_LANE_TEXT_HIDDEN_FIELD_MARKERS` | fairness 修复后 handoff 携带显式 route/tool 字段被 marker 当作 leak | contest headline gate |
| text_whole_lane 全 generic_triage | memory_dual_mode text 侧 | text_whole_lane 格式不能携带结构化决策——格式能力的真实上限 | 记忆公平性面 |
| wrong_decision_misroute_rate 定义 | `eval/runner.py` `_summarize_transfer_truth_rows` | 0.00 不是"没有 misroute"，是定义与直观不符 | consumer sensitivity 报告语义 |
