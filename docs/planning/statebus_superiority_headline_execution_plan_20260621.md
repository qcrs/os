# StateBus Superiority Headline 执行计划

日期：`2026-06-21`

适用范围：

- 当前仓库 `/home/qcrs/statebus/project`
- 用于指导下一阶段 benchmark 设计、审计、最小实现修改与验证顺序
- 这是执行计划，不是当前结果报告，也不是实现完成说明

状态：

- 当前 `contest_honest_headline_v1` 不再继续按“整体优势 headline”抢救
- 当前阶段先冻结对象分层、判题合同与执行顺序
- 未经显式修订，不应边实现边改变本文件主判断

---

## 1. 结论先说

下一阶段的主线不是继续在 `contest_honest_headline_v1` 上补丁式修补。

下一阶段只做一件事：

> 把 benchmark 体系拆成
> `机制对象`
> 和
> `赛题主对象`
> 两条线，
> 然后只让新的赛题主对象回答
> “相比 pure-text，StateBus 是否在 token / task_ms / memory reuse 上整体更优”。

当前主要判断如下：

1. `contest_honest_headline_v1` 当前应降读为 `carrier-isolation / mechanism object`
2. 当前 formal headline 最大问题不是某个局部 bug，而是对象目标错位
3. 当前最需要冻结的是赛题过关合同，而不是继续先改代码
4. 只有在合同、审计和新对象设计都冻结后，才进入最小代码修改

---

## 2. 当前问题定义

### 2.1 现有 headline 的真实定位

当前 `contest_honest_headline_v1` 具备这些优点：

- contest-facing
- single-variable
- text / protocol 对照干净
- parity / repeat gate 已经闭合

但它当前更适合回答：

- `structured carrier / typed-state / replay mechanism 是否成立`

不适合直接回答：

- `相比传统 pure-text，多 Agent 协作整体是否更省 token、更快、更能复用记忆`

### 2.2 为什么不适合直接承担赛题主结论

主要原因有四个：

1. `plan_source=yaml` 将 planner 的开放文本协商成本排除在 headline 之外
2. `contest_honest_headline_v1` 由 controlled pack 变形而来，不是自然长出的 superiority object
3. S2 replay 在 headline 构造中带有显式 override，不适合直接承担自然 memory 收益主结论
4. `admissible_match_rate` 当前更像 safety floor，不像 superiority metric

### 2.3 当前阶段不再争论的事情

本计划不再在开头争论以下问题：

- 要不要继续先修 external baseline
- 要不要继续先救当前 headline
- 要不要先上 repeat=10
- 要不要先做开放世界 / CodeAct / openEuler 终态

这些都降到次序靠后的位置。

---

## 3. 新的对象分层

下一阶段对象只分两类。

### 3.1 机制对象

用途：

- 证明 `structured carrier`
- 证明 `typed-state handoff`
- 证明 `replay / reuse mechanism`
- 证明 parity / purity / stability

当前承接对象：

- `contest_honest_headline_v1`
- `contest_dual_mode_controlled_v3`
- `typed_state_mechanism_v3`
- `typed_state_consumer_sensitivity_v3`
- `memory_policy_controlled_v3`

读法要求：

- 这些对象可以支撑“机制成立”
- 不直接支撑“整体 superiority”

### 3.2 赛题主对象

用途：

- 正式回答赛题主问题：
  - `llm_total_tokens` 是否下降
  - `task_ms` 是否下降或至少不恶化
  - `memory reuse` 是否带来真实收益
  - `quality floor` 是否守住

下一阶段新建对象：

- 临时命名：`contest_superiority_headline_v2`

读法要求：

- 只要新对象还没形成，就不要把现有机制对象偷读成 superiority headline

---

## 4. 赛题过关合同

这一步必须先冻结，不写实现逻辑。

### 4.1 赛题主对象的四行判题表

赛题过关只看四行：

1. `llm_total_tokens`
   - 含义：LLM 真正吃掉的文本成本
   - 要求：`protocol < text`

2. `task_ms`
   - 含义：端到端单任务耗时
   - 要求：`protocol` 不能明显更差，最好更低

3. `quality floor`
   - 含义：结果质量底线
   - 要求：
     - `wrong_family_rate = 0`
     - `admissible_match_rate` 不掉
     - `exact_match_rate` 不能明显塌陷

4. `memory reuse`
   - 含义：跨任务复用的真实收益
   - 要求：
     - 非零 `reuse_gain` 或 `skipped_step_count`
     - 对应 `task_ms` 或执行成本真实下降
     - 不接受“命中了记忆但没省任何东西”

### 4.2 指标记账边界

这部分必须写死，不允许后续混读：

1. `llm_total_tokens`
   - 只算 LLM 真正消费的文本 token
   - 不把共享内存 payload 假装算成 token 节省

2. `control_bytes` / `handoff_wire_bytes`
   - 只算线上控制面和结构化引用开销
   - 属于通信成本

3. `handoff_payload_bytes` / `state payload bytes`
   - 只算非文本状态数据规模
   - 不算 token 节省
   - 但必须通过 `task_ms` 体现真实读写代价

### 4.3 通过标准

只有满足以下条件，才允许说“赛题主对象已形成”：

- token 优势出现
- task_ms 未明显恶化
- quality floor 守住
- memory reuse 有真实收益

### 4.4 失败标准

以下情况都不允许被误读成“已经整体过关”：

- 只有 `control_bytes` 更低
- 只有 mechanism gate 通过
- 只有 `admissible_match_rate = 1.00`
- 只有 replay hit 但没有节省时间或步骤

---

## 5. 对象与评分逻辑审计

这一阶段只做只读审计，不跑大实验。

目标：

- 找出当前哪些设计是公平所必需
- 哪些设计应该迁出 superiority headline
- 哪些设计已经直接妨碍赛题主结论

### 5.1 审计范围

只看这四组代码与相关 contract：

1. `runtime/orchestrator.py:1426`
   - 确认 `plan_source=yaml` 如何绕开 planner

2. `tasks/sample_tasks.py:735`
   - 确认固定 DAG 如何生成

3. `tasks/sample_tasks.py:529`
   - 确认 `contest_honest_headline_v1` 的 S2 replay override 如何注入

4. `eval/runner.py:888`
   - 确认 `admissible_match_rate` 的宽合同范围

补充必读：

- `tasks/contest_family_spec.py`
- `tasks/contest_family_spec.yaml`
- 当前 repeat=10 formal headline report

### 5.2 审计产物

必须形成一份问题清单，且只允许三类标签：

1. `保留`
   - 为单变量公平必须保留

2. `迁出 headline`
   - 适合机制对象
   - 不适合赛题主对象

3. `必须改`
   - 已直接妨碍赛题主结论形成

### 5.3 当前预判

当前预判如下：

- `yaml planner`
  - 标签：`迁出 headline`

- `S2 replay override`
  - 标签：`迁出 headline`

- `bounded_alternative / admissible` 宽合同
  - 标签：`必须改读法`
  - 说明：可以保留作为 safety metric，但不能单独撑 superiority

- `controlled -> headline` 的变形链
  - 标签：`必须改`
  - 说明：新 superiority object 不应直接复用当前 headline 的变形假设

### 5.4 审计通过标准

只有当以下条件都满足，才允许进入实现阶段：

- 上述四组代码都已明确归类
- 当前 headline 的机制定位已冻结
- superiority object 的边界已明确
- 没有未决的指标记账歧义

---

## 6. 新赛题主对象设计

这一阶段只设计，不先改主线实现。

### 6.1 临时命名

新对象临时命名：

- `contest_superiority_headline_v2`

### 6.2 设计要求

它必须满足：

1. `single-variable`
2. `text vs protocol`
3. 同任务
4. 同语料
5. 同评分口径
6. `plan_source=llm`
7. 两边都让 planner 真工作
8. 不把 S2 replay override 直接塞成 headline memory 结果

### 6.3 主对象拆分

新体系拆成两个正式对象。

#### headline-A：overall superiority

内容：

- `text_natural_open_planning`
- vs
- `state_packet_minimal_open_planning`

目标：

- `llm_total_tokens`
- `task_ms`
- `quality floor`

#### headline-B：memory reuse

内容：

- 连续关联任务下的真实复用

目标：

- `reuse_gain`
- `skipped_step_count`
- `task_ms`

### 6.4 当前对象的重新定位

`contest_honest_headline_v1` 调整为：

- `formal_secondary_mechanism`

它的职责变成：

- 证明 carrier / typed-state / replay mechanism 成立
- 不再承担“整体 superiority”结论

### 6.5 新对象设计产物

必须形成：

1. 新 pack contract 草案
2. 新 metric reading contract
3. 新 stopline
4. 与当前 mechanism object 的边界说明

---

## 7. 最小代码修改范围

只有第 4、5、6 节全部冻结后，才允许改代码。

### 7.1 允许修改的文件

下一阶段只允许优先动这四处：

1. `tasks/contest_family_spec.py`
   - 新增 superiority pack 生成逻辑
   - 不复用当前 headline 的变形假设

2. `tasks/sample_tasks.py`
   - 去掉新对象中的 S2 强 override
   - 保留旧对象行为不动

3. `runtime/orchestrator.py`
   - 让新对象走 `plan_source=llm`
   - 不破坏旧对象的 `yaml` 行为

4. `eval/runner.py`
   - 保留 `admissible`
   - 但将其读取边界降为 safety metric
   - superiority pass criteria 不再由它单独支撑

### 7.2 不允许优先动的地方

当前阶段先不要碰：

- `contest_honest_headline_v1` 的 frozen 读法
- external baseline 主线修复
- open-world / CodeAct / openEuler 终态
- 大规模任务厚化
- 报告措辞以外的次级 docs 铺陈

### 7.3 修改原则

必须遵守：

- 不破坏当前 frozen mechanism object
- 不让新对象复用旧 headline 的目标错位
- 不用宽指标掩盖 superiority 不成立
- 不把 memory override 假装成自然收益

---

## 8. 验证顺序

禁止一上来 repeat=10。

### 8.1 第一步：静态/单测

目的：

- 验证新对象 contract 是否成立
- 验证 plan_source 是否真为 `llm`
- 验证 memory contract 是否未被 override 污染
- 验证 metric accounting 是否按新边界输出

要看：

- pack contract
- metadata
- row-level fields
- report field semantics

通过标准：

- 新对象静态 contract 通过
- 测试绿
- report 与 row-level 同义

### 8.2 第二步：API repeat=1

目的：

- 只看方向，不看 freeze

只看三件事：

1. planner token 是否非零
2. protocol 的 `llm_total_tokens` 是否开始低于 text
3. `task_ms` 是否没有明显恶化

通过标准：

- planner 真进入 cost accounting
- superiority headline 至少出现 token 方向性优势，或明确暴露失败信号

### 8.3 第三步：API repeat=3

目的：

- 看方向是否稳定

不做的事：

- 不急着写 formal freeze
- 不急着解释所有尾差

通过标准：

- token 方向稳定
- task_ms 方向可解释
- quality floor 守住

### 8.4 第四步：API repeat=10

前提：

- repeat=3 已经出现稳定 token 优势
  或
- repeat=3 已经暴露明确失败信号

目的：

- 正式确认 superiority object 能否成立

---

## 9. Stopline

这一步必须提前写死，防止项目继续打转。

如果新的 superiority object 已满足：

- planner 已放开
- token 记账没有歧义
- memory 不是 override 假收益
- 质量底线守住

但 `protocol` 仍然没有稳定 token / time 优势，

则结论不再读成“代码还没修好”，而只允许读成两种可能：

1. 当前任务对象仍然太薄
2. StateBus 在这个任务对象上没有整体 superiority

一旦进入这一步：

- 不再继续在同一个 benchmark 上补丁式微调
- 转入“任务厚化 / 对象重做”阶段

---

## 10. 执行顺序

下一阶段严格按这个顺序执行：

1. 写并冻结“赛题过关合同”
2. 做对象与评分逻辑审计清单
3. 设计 `contest_superiority_headline_v2`
4. 才做最小代码修改
5. 按 `repeat=1 -> repeat=3 -> repeat=10` 验证

禁止倒序：

- 不先上 repeat=10
- 不先修 external
- 不先救旧 headline
- 不先做开放世界扩展

---

## 11. 对应文件清单

### 11.1 合同与计划

- `docs/reference/题目.md`
- `docs/review/statebus_benchmark_charter_20260617.md`
- `docs/planning/statebus_4_role_comparator_contract_20260620.md`
- `docs/planning/statebus_superiority_headline_execution_plan_20260621.md`

### 11.2 代码与对象

- `runtime/orchestrator.py`
- `tasks/sample_tasks.py`
- `tasks/contest_family_spec.py`
- `tasks/contest_family_spec.yaml`
- `eval/runner.py`

### 11.3 当前机制对象证据

- `runs/formal_comparator_api_repeat10_20260621_125934/api_repeat10_frozen_headline/benchmark_report.md`
- `runs/formal_comparator_api_repeat10_20260621_125934/api_repeat10_internal_paired/benchmark_report.md`
- `runs/formal_comparator_api_repeat10_20260621_125934/api_repeat10_external_pure_text_baseline/open_report.md`

---

## 12. 本计划的边界

本文件不声称以下事情已经成立：

- superiority headline 已经做完
- planner-open object 已经可读
- external comparator 已经正式成立
- open-world benchmark 已经准备好
- openEuler 终态已闭环

本文件只定义：

- 下一阶段该做什么
- 先后顺序是什么
- 什么算通过
- 什么情况必须停止继续修同一对象
