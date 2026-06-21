# Contest Superiority Headline V2 Design

日期：`2026-06-21`

适用范围：

- 当前仓库 `/home/qcrs/statebus/project`
- 用于冻结 `contest_superiority_headline_v2` 的设计边界
- 这是设计合同，不是实现说明，也不是当前结果报告

状态：

- 基于 `docs/planning/statebus_superiority_headline_execution_plan_20260621.md`
- 基于 `docs/planning/statebus_contest_superiority_gate_contract_20260621.md`
- 基于 `docs/analysis/statebus_superiority_object_and_scoring_audit_20260621.md`

---

## 1. 目标

新对象只回答：

> 在公平、单变量、contest-facing 的同任务多 Agent 比较下，
> `StateBus carrier`
> 是否相对
> `pure-text carrier`
> 在 token / task_ms / memory reuse 上整体更优。

---

## 2. 主对象命名

当前临时命名固定为：

- `contest_superiority_headline_v2`

当前不使用以下命名作为主对象：

- `contest_honest_headline_v2`
- `4-LLM architecture upgrade`
- `open-world benchmark`

原因：

- 当前阶段目标是 superiority comparator repair
- 不是架构扩张或开放世界展示

---

## 3. 设计要求

新对象必须同时满足：

1. `single-variable`
2. `text vs protocol`
3. 同任务
4. 同语料
5. 同评分口径
6. `plan_source=llm`
7. 两边 planner 都必须真工作
8. 不直接注入 S2 replay override

---

## 4. 主对象拆分

新体系拆成：

- 一个唯一公开 headline
- 一个 formal-secondary memory object

### 4.1 唯一公开 Headline: overall superiority

对象：

- `text_natural_open_planning`
- vs
- `state_packet_minimal_open_planning`

主读法：

- `llm_total_tokens`
- `task_ms`
- `quality floor`

通过标准：

- token 优势出现
- `task_ms` 不明显恶化
- `wrong_family_rate = 0`
- `exact_match_rate` 不明显塌陷

### 4.2 Formal-secondary object: memory reuse

对象：

- 同一 superiority family 下的连续关联任务

主读法：

- `reuse_gain`
- `skipped_step_count`
- `task_ms`

通过标准：

- 非零 reuse 证据
- 且与真实执行成本下降绑定

读法边界：

- 它属于 superiority program 的正式次级对象
- 不与唯一公开 headline 混读
- 不单独升级为公开总 headline

---

## 5. 与当前 mechanism object 的边界

### 5.1 `contest_honest_headline_v1`

保留为：

- `formal_secondary_mechanism`

职责：

- carrier isolation
- typed-state minimal packet consumption
- frozen purity / parity / mechanism stability

不再承担：

- 整体 superiority headline

### 5.2 support / audit surfaces

以下对象继续存在，但不并入 superiority 主裁决：

- `typed_state_mechanism_v3`
- `typed_state_consumer_sensitivity_v3`
- `memory_policy_controlled_v3`
- external baseline audit surfaces

---

## 6. 新 pack contract 草案

### 6.1 必须保留

1. 同 family
2. 同 query
3. 同 corpus evidence universe
4. 同 summary contract
5. 同 role graph
6. 同 scoring contract

### 6.2 必须变化

只允许变化：

1. carrier 表达方式
2. typed-state 是否存在
3. protocol lane 的 state consumption contract

### 6.3 必须移除

新对象中必须移除：

1. `plan_source=yaml` 作为默认 headline planner 方案
2. `runtime_reuse_contract_override` 直接塑造 S2 结果
3. 从 controlled pack 直接变形继承 superiority 语义

---

## 7. Metric Reading Contract

### 7.1 主指标

主指标固定为：

1. `llm_total_tokens`
2. `task_ms`
3. `exact_match_rate`
4. `wrong_family_rate`
5. `reuse_gain`
6. `skipped_step_count`

### 7.2 次指标

次指标固定为：

1. `admissible_match_rate`
2. `control_bytes`
3. `handoff_wire_bytes`
4. `handoff_payload_bytes`

### 7.3 读法

- 主指标决定 superiority 是否成立
- 次指标只负责解释机制、通信、边界和代价

---

## 8. Stopline

新对象必须自带 stopline：

1. 不把 support / audit / mechanism surface 混进 headline
2. 不把 `admissible` 单独读成成功
3. 不把 payload bytes 读成 token 节省
4. 不把 memory hit 读成 memory gain
5. 不在 `repeat=3` 没出现稳定 token 优势或明确失败信号前进入 `repeat=10`

---

## 9. 最小实现范围

只有在本设计冻结后，才允许进入最小实现修改。

允许优先修改：

1. `tasks/contest_family_spec.py`
2. `tasks/sample_tasks.py`
3. `runtime/orchestrator.py`
4. `eval/runner.py`

当前不授权修改：

1. external baseline 主线
2. `contest_honest_headline_v1` frozen 读法
3. open-world / CodeAct / openEuler 终态
4. 大规模任务扩张

---

## 10. 当前阶段结论

截至本设计冻结为止，当前结论固定为：

1. superiority 路线已经完成合同、审计和对象设计冻结
2. 当前尚未授权进入 benchmark 主实现修改
3. 下一步若继续，应只进入最小实现范围
