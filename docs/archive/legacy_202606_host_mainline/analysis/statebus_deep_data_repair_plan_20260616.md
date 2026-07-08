# StateBus 深度数据分析修复文档

日期：2026-06-16  
基于运行目录：`runs/api_repeat1_smoke_20260616_165207/`  
参考：`docs/analysis/statebus_deep_data_analysis_20260616.md`

## 1. 结论先行

这批 `repeat=1` API smoke 证明了三件事：

- 主链路是通的，`pytest` / `runtime.smoke` 都已通过。
- `planner_support_v3` 的 planner / LangGraph 编排已正常接通。
- `typed_state_consumer_sensitivity_v3` 的负控统计是干净的，错误 packet 会真实触发降级/失败。

但当前深度分析里还有两类问题需要修正：

- 真实能力下限被正确揭示了，但部分表述把“结构合法”说成了“任务成功”。
- 若干对比混入了 lane 不对称，导致 text / protocol 或 natural-handoff / state-packet 的比较不够纯净。

## 2. 哪些判断成立

### 2.1 planner_support_v3 的主判断成立

- `planner_llm_request_count=6`
- `planned_step_count=38`
- 4-step validate-first 行确实存在
- 4-step 行里 `execute_ms=0`、`summarize_ms=0`、`trajectory_step_count=2` 是真实现象

这说明：

- planner 合同已接通
- `semantic_role` 驱动的 LangGraph 编排是正常的
- validate 不再是假步骤

### 2.2 contest 的主判断成立

contest 去 hint 后的确出现大量 `generic_triage` / `collect_more_evidence` 坍塌，这说明：

- formal retrieval 去捷径后，route discrimination 仍弱
- evidence topology 还不够强
- runtime 的保守 abstain 逻辑在起作用

### 2.3 typed_state_mechanism 的主判断部分成立

typed-state 不是“完全没消费”，而是“消费了也不一定救回正确 route”。

这在结果里可以看到：

- `typed_executor_any_consumption_rate=0.5`
- `exact=0.00`
- `admissible=0.25`

## 3. 需要修正的地方

### 3.1 `planner_support_v3` 不能再被表述成“validate-first 已闭环成功”

当前 4-step 行多数是：

- validate 触发
- execute / summarize 被阻断

这说明的是：

- `validate` gate 生效

不是：

- planner 已经把任务成功率提升到稳定闭环

因此报告应拆成两层：

- `plan_valid`
- `validate_blocked_or_passed`

不要把 `planned_step_count=4` 直接等同于“更强能力”。

### 3.2 contest 的 text/protocol 比较不能只讲“protocol 更差”

当前 summary 级结果显示：

- text: `exact=0.05`, `admissible=0.30`, `abstain=0.25`, `tool_exact=0.40`
- protocol: `exact=0.05`, `admissible=0.55`, `abstain=0.50`, `tool_exact=0.05`

这说明：

- 两边最终 exact 一样低
- protocol 更保守
- text 的 tool exact 更高，说明 executor 侧存在额外纠正能力

所以更准确的表述应是：

- protocol 更严格、更容易 abstain
- text lane 带有 executor-side lexical recovery
- 两者不是完全等价比较对象

### 3.3 `typed_state_mechanism_v3` 的问题不只是 retrieval 弱

这里还有 lane 不对称：

- `natural_handoff_text` 路径会在 executor 侧做 lexical reconstruction
- `state_packet_minimal` 路径更像直接消费 packet，没有同级别 fallback

因此当前结果混入了：

- handoff object 差异
- executor fallback 差异

这会污染“纯文本 vs 结构化状态传递”的赛题读法。

### 3.4 `invariant_violation_count=1` 需要重命名或重解释

4-step validate-first 行里出现的 `invariant_violation_count=1`，很可能包含的是：

- 预期的 gate 阻断

如果不拆语义，会被误读成：

- runtime 本身不稳定

建议拆成：

- `expected_gate_block_count`
- `true_invariant_violation_count`

## 4. 额外发现的问题

### 4.1 contest 也存在 lane 不对称，不止 typed-state

当前 text/protocol 对比里，text lane 也更像“可自救”，protocol lane 更像“冻结消费”。

如果不统一 executor policy，contest 和 typed-state 两条对比都会被同一种偏差污染。

### 4.2 planner task-level 报告不完整

当前 task-level 里：

- `planner_one_shot_valid` 可能为空
- `planner_repair_attempt_count` 可能为空
- `status` 也可能为空

这会影响审计，不利于答辩。

### 4.3 当前 analysis 不能把 abstention 直接写成“乱答”

contest 里的很多失败不是错猜，而是：

- 低置信度 abstain
- `generic_triage`
- `collect_more_evidence`

这是保守失败，不是随机胡说。

## 5. 修复原则

### 5.1 先保证比较对象干净，再追指标

赛题要求的是：

- 低开销通信
- 非文本状态传递
- 共享记忆复用

不是把某一 lane 做成更强的“二次推理器”。

### 5.2 不回退 formal clean

不能为了提升 exact 再把这些东西偷偷加回去：

- `runtime_route_hint`
- `preferred_doc_ids`
- `theme_bonus`
- `group_bonus`

### 5.3 support / headline 边界要保持清楚

- `contest_dual_mode_controlled_v3` 是 headline
- `planner_support_v3` 是 support surface
- `typed_state_mechanism_v3` 是 formal-secondary mechanism surface
- `typed_state_consumer_sensitivity_v3` 是 support surface

## 6. 修复方案

### 6.1 统一 lane policy，先修公平性

建议把 `typed_state_mechanism_v3` 和 contest text/protocol 的 executor policy 统一成一种：

- 要么两条 lane 都允许 executor-side lexical recovery
- 要么两条 lane 都不允许，executor 只消费标准化 decision packet / retrieval output

推荐方案：

- 禁止 executor 侧二次 lexical recovery
- 让差异只来自 handoff object 本身

原因：

- 更符合“比较状态传递机制”的赛题本意
- 不会把 text lane 做成额外自救器

### 6.2 修 contest 的 evidence topology

优先修这 9 个 `wrong_family`：

- auth 1
- billing 2
- checkout 2
- deploy 2
- cache 2

修法不是加 route token，而是补结构：

- route-specific structural anchor
- route-specific metrics / logs 联动
- 为竞争 route 提供明确反证

目标是：

- clean case 至少做到二证据收敛
- distractor case 变成“主因可排除次因”
- ambiguous case 保持真实 abstain，而不是假装可判

### 6.3 修 planner 报告粒度

补齐 task-level 字段：

- `planner_one_shot_valid`
- `planner_repair_attempt_count`
- `planner_contract_valid_final`
- `validate_gate_triggered`
- `validate_gate_passed`

并把 4-step 行拆成两类：

- `plan_valid_but_validate_blocked`
- `plan_valid_and_execute_continued`

### 6.4 修分析口径

报告里不要再混用这几种指标：

- step-level route/tool exact
- case-level exact/admissible
- lane-level executor recovery

它们不是一回事。

## 7. 建议执行顺序

1. 先统一 `typed_state_mechanism_v3` 的 lane policy
2. 再修 planner task-level reporting
3. 再修 validate gate 语义命名
4. 再重构 contest 的 9 个 wrong-family 样本及其 family topology
5. 最后再跑一次 `repeat=1` API smoke

## 8. 验证标准

修完后，至少满足：

- planner-support 的 4-step 行能被明确标成 gate-blocked 或 continue
- contest 的 wrong-family 仍然存在，但不再主要靠 `generic_triage` 折叠
- typed-state 的两条 lane 在 executor policy 上一致，比较对象纯净
- 报告里不再把预期阻断写成异常

