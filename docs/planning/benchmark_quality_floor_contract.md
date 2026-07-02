# Benchmark Quality Floor Contract

日期：2026-06-26  
状态：`v2` 跨合同文档  
作用：定义 `L0-L3` 消融实验与正式 benchmark 中，什么叫“节省有效且质量未塌陷”。

---

## 1. 目标

这份合同要解决：

1. 低成本结果是否仍满足质量底线
2. 哪些 run 有资格进入成本对比
3. `LLM-as-a-Judge` 在体系里的位置

---

## 2. 基本原则

### 2.1 成本对比只在质量通过后成立

如果质量底线没过：

1. 允许保留 run
2. 允许进入失败分析
3. 不允许进入正式省钱/省时 headline

### 2.2 不让 `LLM-as-a-Judge` 做唯一裁判

默认采用三层判断：

1. deterministic validator
2. fact coverage validator
3. `LLM-as-a-Judge`

---

## 3. 三层质量底线

### 3.1 第一层：deterministic validator

至少检查：

1. JSON schema
2. CSV/PNG/输出文件存在且非空
3. 关键字段类型正确
4. 关键数值可解析

### 3.2 第二层：fact coverage validator

至少检查：

1. 必需事实是否出现
2. 关键数值是否一致
3. 必需输出类型是否齐全

### 3.3 第三层：`LLM-as-a-Judge`

只用于：

1. 语义等价
2. 解释是否缺关键信息
3. 图表与文本说明是否一致

不用于：

1. 取代 deterministic validator
2. 单独决定 benchmark pass/fail

---

## 4. 正式 gate

建议统一输出：

1. `quality_floor_pass`
2. `quality_floor_fail_reason`
3. `deterministic_checks_passed`
4. `fact_coverage_passed`
5. `llm_judge_passed`

只有 `quality_floor_pass == true` 的 run，才进入：

1. `L0-L3` 瀑布图
2. 正式 token/latency headline

当前冻结要求：

3. formal benchmark 至少输出 `L0`、`L1`、`L2`、`L3` 四层结果或明确缺失原因

---

## 5. 与 replay 的关系

如果一个 run 未通过质量底线：

1. 不得用于正式 replay gain claim
2. 不得把其产物升格为 `VERIFIED`

也就是说，quality floor 同时是：

1. benchmark gate
2. replay commit gate 的一部分

---

## 6. `LLM-as-a-Judge` 的使用纪律

建议：

1. 使用独立 judge 配置
2. 不与被评测模型共用提示模板
3. 输出结构化判定结果

不建议：

1. 只看一段自由文本好评
2. 用 judge 分数直接替代硬校验

---

## 7. `MVP` 实现建议

1. 先实现 deterministic validator
2. 再实现 fact coverage validator
3. `LLM-as-a-Judge` 先作为 optional comparator
4. 正式报告至少展示 `quality_floor_pass`

---

## 8. 验收建议

建议最小验收：

1. 一个低成本但错答案的 run 不会进入正式对比
2. 一个低成本且质量通过的 run 可以进入正式对比
3. 未过质量底线的 artifact 不会升级为 `VERIFIED`
