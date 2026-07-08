# StateBus Benchmark 立项表

日期：`2026-06-17`

定位：

- 这是一份“如何定义一个可信 benchmark”的立项表。
- 不是审计报告。
- 不是执行计划。
- 也不是某个 pack 的解释说明。

目标：

- 让后续所有 benchmark 设计、收口和改动，都先过同一套判断标准。
- 防止再次回到“对象混乱、结果差不多、结论难分辨”的状态。

---

## 1. 这轮主问题

当前这一轮只回答一个问题：

> 在一个可信、单变量、足够厚的赛题 benchmark 上，structured protocol 是否比 pure-text handoff 更有优势？

这意味着：

- 不先证明所有创新点
- 不先扩展所有支线
- 不把 support surface 伪装成 headline
- 不把局部修补当成主结论

---

## 2. 可信 Benchmark 的硬条件

### 2.1 赛题对齐

- 必须直接回答赛题允许的问题
- 不能把 audit-only / support-only / internal surface 包装成正式 headline

### 2.2 单变量

- 一次只改一个主变量
- 其他条件固定：
  - 任务集
  - 语料
  - 计划源
  - 评分口径
  - 运行配置

### 2.3 对象纯净

- text 对象必须是真正的 text
- protocol 对象必须是真正的 protocol
- 不能混入隐藏能力、显式结构字段、pack-specific override

### 2.4 任务足够厚

- 不能只是一跳 route/tool 选择
- 至少要有多跳协作空间，protocol 的通信节省才可能复利

### 2.5 可区分

benchmark 必须能区分三种情况：

1. 方法没优势
2. benchmark 对象不公平
3. 任务太薄

如果分不出来，这个 benchmark 就不合格。

### 2.6 可复现

- 固定 seed
- 固定 corpus
- 固定 pack 语义
- repeat 结果必须能稳定解释

### 2.7 结果可解释

- 每个关键指标都要能追到 row-level
- report 和底层 JSON 必须一致
- 不能靠 aggregate 造语义

---

## 3. 一票否决项

以下任意一项出现，都不算可信 benchmark：

- hidden fallback
- pack-specific override
- support surface 冒充 headline
- 让“更会讲”代替“更强”
- 报表与 row-level 不一致
- 任务太薄但硬说能代表正式结论

---

## 4. 成功标准

本轮允许的成功标准只有三档：

### 4.1 结论 A：benchmark 不合格

出现以下任一情况即可：

- 对象不纯
- 不是单变量
- 任务太薄
- 报表语义有错

### 4.2 结论 B：benchmark 合格，但方法没显出优势

含义：

- benchmark 本身可信
- 但当前方法在这个对象上没有形成足够优势

### 4.3 结论 C：benchmark 合格，方法有局部优势

例如：

- control bytes 更低
- 但 latency / correctness 没明显拉开

### 4.4 结论 D：benchmark 合格，方法有稳定 headline 优势

这才是最终想要的结论。

---

## 5. 失败标准

以下情况都不应该被误判成“方法失败”：

- benchmark 对象不纯
- 任务太短太薄
- report 聚合 bug
- row-level 与 headline 不一致
- support surface 被误读成正式 headline

---

## 6. 最小可行 headline 对象

当前最小可行 headline 对象应满足：

1. contest-facing
2. single-variable
3. text vs protocol
4. object parity
5. formal headline 清晰
6. 不依赖额外解释层才能成立

---

## 7. 本轮不进入裁决的东西

以下内容可以保留，但不进入这轮主裁决：

- open extension
- LangGraph extension
- 更丰富 typed-state
- git 风格管理
- 其他加分创新点

它们不是没价值，而是不能和主 headline 混在一起裁决。

---

## 8. 诊断顺序

如果结果不理想，按这个顺序查：

1. benchmark 对象是否合格
2. 报表语义是否一致
3. 任务是否太薄
4. 才查方法本身

不要倒过来。

---

## 9. 立项前必须先定的四件事

### 9.1 成功标准

“体现优势”到底是：

- control bytes 更低就够
- 还是 latency / correctness 也必须拉开

### 9.2 失败标准

什么结果出现时，要承认当前方法在这个 benchmark 上没有优势。

### 9.3 headline benchmark 最小对象

至少要有：

- 几跳协作
- 是否允许跨任务依赖
- text / protocol 各自可见范围

### 9.4 不进入本轮裁决的支线

要明确写死，避免再次发散。

---

## 10. 结论

当前最重要的，不是继续增加新东西。

当前最重要的是：

1. 先把 benchmark 的立项标准定死
2. 再用这个标准审视现有对象
3. 最后才决定方法到底有没有优势

当前已收束的可执行事实：

- `contest_honest_headline_v1` 是当前 contest-facing formal headline。
- `contest_dual_mode_controlled_v3` 只保留为内部 controlled surface。
- `planner_support_v3` 和 `memory_dual_mode_fairness_v3` 都必须按 row-level 语义读，不得让报表口径反客为主。

如果 benchmark 本身不合格，后面的所有结果都只能算辅助证据，不能算正式裁决。
