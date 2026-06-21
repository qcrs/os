# StateBus Contest Superiority Gate Contract

日期：`2026-06-21`

适用范围：

- 当前仓库 `/home/qcrs/statebus/project`
- 用于冻结 superiority 主对象的赛题过关合同
- 这是 gate contract，不是实现说明，也不是结果报告

状态：

- 基于 `docs/planning/statebus_superiority_headline_execution_plan_20260621.md` 落地
- 当前不授权修改 benchmark 主实现
- 当前不恢复 `contest_honest_headline_v1` 作为整体 superiority headline

---

## 1. 目标

本合同只回答一个问题：

> 新的赛题主对象要满足什么条件，
> 才允许被读成
> “相比 pure-text，StateBus 在整体上更优”。

当前不回答：

- 旧 headline 是否还能抢救
- external pure-text baseline 是否已经闭环
- open-world / CodeAct / openEuler 终态是否该并入

---

## 2. 对象分层

### 2.1 机制对象

机制对象只回答：

- structured carrier 是否成立
- typed-state handoff 是否成立
- replay / reuse mechanism 是否成立
- purity / parity / stability gate 是否成立

当前对象：

- `contest_honest_headline_v1`
- `contest_dual_mode_controlled_v3`
- `typed_state_mechanism_v3`
- `typed_state_consumer_sensitivity_v3`
- `memory_policy_controlled_v3`

这些对象不能直接升格为整体 superiority headline。

### 2.2 赛题主对象

赛题主对象只回答：

- `llm_total_tokens` 是否下降
- `task_ms` 是否下降或至少不明显恶化
- `memory reuse` 是否带来真实收益
- `quality floor` 是否守住

当前临时命名固定为：

- `contest_superiority_headline_v2`

---

## 3. 四行判题表

赛题过关只看以下四行。

### 3.1 `llm_total_tokens`

含义：

- LLM 真正消费的文本 token 成本

通过条件：

- `protocol < text`

失败读法：

- 不能把共享内存 payload 或 state payload 假装读成 token 节省

### 3.2 `task_ms`

含义：

- 端到端单任务耗时

通过条件：

- `protocol` 不能明显更差
- 最好更低

失败读法：

- 不能只看 control bytes 更低，就忽略明显变慢

### 3.3 `quality floor`

含义：

- 结果质量底线

通过条件：

- `wrong_family_rate = 0`
- `admissible_match_rate` 不掉
- `exact_match_rate` 不允许明显塌陷

读法边界：

- `admissible_match_rate` 只保留为 safety floor
- 不能单独承担 superiority 结论

### 3.4 `memory reuse`

含义：

- 跨任务复用的真实收益

通过条件：

- 非零 `reuse_gain` 或 `skipped_step_count`
- 且必须对应真实的 `task_ms` 或执行成本下降

失败读法：

- 不接受“命中了记忆但没省任何东西”

---

## 4. 指标记账边界

### 4.1 `llm_total_tokens`

- 只算 LLM 真正消费的文本 token
- 不把 state payload bytes 并入 token 节省

### 4.2 `control_bytes` / `handoff_wire_bytes`

- 只算线上控制面和结构化引用开销
- 它们属于通信成本
- 可以支持 mechanism / communication compactness 结论
- 不能单独支持整体 superiority

### 4.3 `handoff_payload_bytes` / `state payload bytes`

- 只算非文本状态数据规模
- 它们不是 token
- 它们的真实代价必须体现在 `task_ms`

### 4.4 `admissible_match_rate`

- 保留
- 但严格降读为 safety metric
- 不能替代 `exact_match_rate`
- 不能替代整体 superiority judgment

---

## 5. 通过标准

只有同时满足以下条件，才允许说“赛题主对象已形成”：

1. 出现稳定 token 优势
2. `task_ms` 未明显恶化
3. `quality floor` 守住
4. `memory reuse` 有真实收益

---

## 6. 失败标准

以下情况都不允许被读成“已经整体过关”：

1. 只有 `control_bytes` 更低
2. 只有 mechanism gate 通过
3. 只有 `admissible_match_rate = 1.00`
4. 只有 replay hit，但没有节省时间或步骤
5. 只有 support / audit surface 成立

---

## 7. 当前 frozen headline 的重新定位

`contest_honest_headline_v1` 当前重新定位为：

- `carrier-isolation / mechanism object`

它当前可以支持：

- `text_whole_lane` vs `state_packet_minimal` 的机制隔离
- typed-state minimal packet 被真实消费
- frozen purity / parity / stability 边界

它当前不能直接支持：

- “相比 pure-text 整体 superiority 已成立”

原因固定为四点：

1. `plan_source=yaml` 排除了 planner 开放协商成本
2. 它由 controlled pack 变形而来
3. S2 memory 行带有显式 replay override
4. `admissible_match_rate` 过宽，读法只能是 safety floor

---

## 8. 当前证据边界

当前仓库内可直接定位的 headline benchmark artifact 里，
最直接的有两类：

- `runs/full_api_repeat1_coverage_suite_20260619_095302/api_repeat1/contest_honest_headline_v1_api_r1/benchmark_report.md`
- `runs/formal_comparator_api_repeat10_20260621_125934/api_repeat10_frozen_headline/benchmark_report.md`

其中 repeat=1 artifact 直接显示：

- `Observed planner sources: yaml`
- `Formal stability gate: not_yet`
- `exact_match_rate = 0.25`
- `admissible_match_rate = 1.00`

其中 repeat=10 artifact 直接显示：

- `Repeat: 10`
- `Observed planner sources: yaml`
- `Formal stability gate: pass`
- `exact_match_rate = 0.25`
- `admissible_match_rate = 1.00`
- `llm_total_tokens_delta = 0.05`
- `task_ms_delta = 92.80`

当前仓库 surface 内已经存在可直接定位的
`contest_honest_headline_v1` repeat=10 frozen-headline artifact。

因此：

- repeat=10 frozen headline 结论并非缺失
- 当前问题不在于“没有 artifact”
- 而在于 headline 证据的 source-of-truth 仍分散在 repeat=1 / repeat=10 / freeze-analysis 三个 surface
- 这可以支撑当前历史定位
- 但不应被误写成“当前 superiority v2 审计已经拥有完全单路径的 headline source-of-truth”

---

## 9. Stopline

当前阶段必须遵守：

1. 不把 mechanism surface 混读成 superiority headline
2. 不把 `control_bytes` 紧凑性混读成整体优势
3. 不把 memory override 混读成自然复用收益
4. 不在合同冻结前进入 benchmark 主实现修改
