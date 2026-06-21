# StateBus Superiority Object And Scoring Audit

日期：`2026-06-21`

适用范围：

- 当前仓库 `/home/qcrs/statebus/project`
- 用于执行 superiority 路线的只读审计
- 这是审计清单，不是实现说明，也不是结果包装

状态：

- 严格基于 `docs/planning/statebus_superiority_headline_execution_plan_20260621.md`
- 当前未修改 benchmark 主实现

---

## 1. 审计目标

本轮只回答四个问题：

1. 当前哪些设计是公平 comparator 必须保留的
2. 当前哪些设计只适合 mechanism object，必须迁出 superiority headline
3. 当前哪些设计已直接妨碍赛题主结论
4. 当前指标读法哪里仍然有混读风险

---

## 2. 审计范围

本轮只审计以下位置：

1. `runtime/orchestrator.py:1427`
2. `tasks/sample_tasks.py:529-566`
3. `tasks/sample_tasks.py:735-780`
4. `eval/runner.py:896-966`

补充 contract：

- `tasks/contest_family_spec.py`
- `tasks/contest_family_spec.yaml`

补充 artifact：

- `runs/full_api_repeat1_coverage_suite_20260619_095302/api_repeat1/contest_honest_headline_v1_api_r1/benchmark_report.md`
- `runs/formal_comparator_api_repeat10_20260621_125934/api_repeat10_frozen_headline/benchmark_report.md`

说明：

- 当前 repo surface 中存在一个可直接定位的 repeat=10 frozen headline artifact
- 但当前 frozen headline 的 source-of-truth 仍分散在：
  - formal comparator repeat=10 run artifact
  - 更早的 freeze / analysis docs
  - repeat=1 coverage suite
- 因此本轮审计可以引用 repeat=10 artifact，但不能假装当前 headline 证据已经完全收敛为单一路径 source-of-truth

---

## 3. 证据摘录

### 3.1 planner source

`runtime/orchestrator.py:1429-1436`：

- `plan_source == "yaml"` 时直接 `build_plan(task)`
- 只有 `plan_source == "llm"` 才会调用 `planner.plan_task`

结论：

- 当前 headline 若默认 `yaml`，planner 的开放规划 token 成本并未进入 headline 主比较

### 3.2 S2 replay override

`tasks/sample_tasks.py:552-560`：

- `contest_honest_headline_v1` 的 `S2` 行会注入：
  - `expected_reuse_mode = "skip_execute"`
  - `runtime_reuse_contract_override = "validated_replay"`

结论：

- 当前 headline 的 memory 行不是自然长出的 replay outcome
- 而是 pack 变形时显式写入的结果合同

### 3.3 固定 DAG 形状

`tasks/sample_tasks.py:735-780`：

- `build_plan(task)` 固定生成 `retrieve -> validate? -> execute -> summarize`
- 角色形状由 `required_plan_semantic_roles` 静态约束

`tasks/contest_family_spec.py:314-319` 与 `tasks/sample_tasks.py:1166-1173`：

- formal contest rows 强制 `required_plan_semantic_roles = retrieve/validate/execute/summarize`

结论：

- 这保证了角色图和厚度 admission floor
- 但它不是 planner 真开放工作的证据

### 3.4 admissible 宽合同

`eval/runner.py:896-966`：

- case contract 同时读取 `acceptable_routes` 与 `acceptable_tools`
- 对 `bounded_alternative` / `abstention_allowed` 允许 `alternate_pair_admissible`

`tasks/contest_family_spec.yaml`：

- 大量 contest cases 的 `case_type` 是 `bounded_alternative`
- 且存在显式 `acceptable_routes` / `acceptable_tools`

结论：

- `admissible_match_rate` 在当前设计中天然宽于 exact correctness
- 它更适合 safety floor，不适合单独撑 superiority

### 3.5 当前 headline artifact 的直接暴露

`runs/full_api_repeat1_coverage_suite_20260619_095302/api_repeat1/contest_honest_headline_v1_api_r1/benchmark_report.md` 直接显示：

- `Plan source default: yaml`
- `Observed planner sources: yaml`
- `Formal stability gate: not_yet`
- `exact_match_rate = 0.25`
- `admissible_match_rate = 1.00`
- `state_transfer` lane 上 `llm_total_tokens_delta = 2.05`
- `state_transfer` lane 上 `task_ms_delta = 43.28`

结论：

- 当前 headline artifact 更强地支撑机制隔离
- 不支撑“整体 superiority 已成立”

`runs/formal_comparator_api_repeat10_20260621_125934/api_repeat10_frozen_headline/benchmark_report.md` 直接显示：

- `Repeat: 10`
- `Plan source default: yaml`
- `Observed planner sources: yaml`
- `Single-variable contract: yes`
- `Formal stability gate: pass`
- `llm_total_tokens_delta = 0.05`
- `task_ms_delta = 92.80`

结论：

- repeat=10 artifact 当前是可直接定位的
- 它进一步支撑“mechanism object 已稳定”
- 但它同样不支撑“整体 superiority 已成立”

---

## 4. 审计清单

以下清单只允许三类标签：

- `保留`
- `迁出 headline`
- `必须改`

### 4.1 `yaml planner`

标签：

- `迁出 headline`

原因：

- 当前 `yaml` 规划直接绕开 planner 开放协商成本
- 它适合 mechanism / parity / shape control
- 不适合整体 superiority 主对象

处理结论：

- 旧对象保留
- 新 superiority object 必须改为 `plan_source=llm`

### 4.2 固定四角色 DAG admission floor

标签：

- `保留`

原因：

- 当前静态角色图是 comparator 公平性的必要条件
- `retrieve/validate/execute/summarize` 作为主拓扑仍应保留
- 否则 text/protocol 可能走不同图，失去单变量基础

处理结论：

- 新对象保留四角色图冻结
- 但 planner 不再允许被 `yaml` 直接短路

### 4.3 `S2 replay override`

标签：

- `迁出 headline`

原因：

- 当前 `expected_reuse_mode=skip_execute` 与 `runtime_reuse_contract_override=validated_replay` 是 pack 注入
- 更适合 mechanism object 中证明 replay contract 存在
- 不适合作为 superiority 主对象的自然 memory 收益证据

处理结论：

- 旧对象保留该行为
- 新 superiority object 不得直接复用这套 override

### 4.4 `acceptable_routes / acceptable_tools / bounded_alternative`

标签：

- `必须改`

原因：

- 它们作为安全边界是合理的
- 但当前若将 `admissible_match_rate = 1.00` 读成主成功指标，会掩盖 `exact_match_rate = 0.25`
- 这会直接妨碍 superiority judgment

处理结论：

- `admissible` 保留
- 但只能降读为 quality floor / safety metric
- superiority pass criteria 不能由 `admissible` 单独支撑

### 4.5 `controlled -> headline` 变形链

标签：

- `必须改`

原因：

- `contest_honest_headline_v1` 是从 controlled pack 变形而来
- 该 lineage 对 mechanism object 有价值
- 对 superiority 主对象则会带来目标错位

处理结论：

- `contest_superiority_headline_v2` 不应直接沿用当前 headline 的变形假设

### 4.6 `formal headline repeat=10 evidence source`

标签：

- `必须改`

原因：

- 当前仓库中已经存在可直接定位的 repeat=10 frozen-headline artifact
- 但当前 headline 证据仍分散在多个 surface：
  - formal comparator repeat=10 artifact
  - freeze / analysis docs
  - repeat=1 coverage suite
- 这会妨碍 superiority 审计和交接时的证据 source-of-truth 清晰度

处理结论：

- 新 superiority 路线后续必须固定唯一 direct artifact 归档路径
- 当前阶段只记为证据 source-of-truth 尚未完全收敛，不伪装成已完成状态

---

## 5. 审计结论

### 5.1 保留项

必须保留：

1. 四角色固定主图
2. same task / same corpus / same scoring 的 parity 原则
3. current mechanism objects 的 frozen 读法

### 5.2 迁出 headline 项

必须迁出 superiority headline：

1. `plan_source=yaml`
2. `S2 replay override`
3. 当前 `contest_honest_headline_v1` 的 mechanism-first 读法

### 5.3 必须改项

进入 superiority 主对象前必须改：

1. `admissible_match_rate` 的主读法
2. `controlled -> headline` 的继承链
3. repeat=10 direct artifact 固定方式

---

## 6. 进入实现前的准入判断

当前审计后的准入判断如下：

1. mechanism object 的降读已经明确
2. superiority object 的边界已经明确
3. 当前不应继续修补旧 headline 来冒充整体优势
4. 可以进入 `contest_superiority_headline_v2` 设计冻结
5. 当前还不应进入 benchmark 主实现修改

---

## 7. Stopline

本轮审计后的 stopline 固定为：

1. 不把 `contest_honest_headline_v1` 再读成整体 superiority headline
2. 不把 `admissible_match_rate = 1.00` 当成整体成功
3. 不把 S2 override 当成自然 memory reuse 收益
4. 不在新对象设计冻结前修改主实现
