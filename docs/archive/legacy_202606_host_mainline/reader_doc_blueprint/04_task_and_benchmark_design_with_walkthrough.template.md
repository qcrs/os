# 模板 04：任务与 Benchmark 设计 + 真实 Walkthrough

建议目标文件：

- `docs/reader_guide/04_task_and_benchmark_design_with_walkthrough.md`

## 一、文档目标

这份文档回答：

1. 任务是怎么设计的。
2. 为什么不是一堆散题。
3. 这些任务是在验证系统能力，还是只是在做局部优化测试。
4. 一个真实任务到底如何完整流过系统。

## 二、必须使用的输入

1. `tasks/README.md`
2. `tasks/*.yaml`
3. `tasks/sample_tasks.py`
4. `eval/runner.py`
5. 至少一个真实 run artifact

## 三、建议章节结构

### 1. 任务设计总原则

要求：

1. 先解释为什么要做连续任务链。
2. 说明这些任务不是普通问答集。

### 2. task / family / chain / case 的关系

必须有一张关系表，至少包括：

- 名称
- 含义
- 在代码/配置里怎么体现
- 为什么要这么分

### 3. 一个 pack 为什么不是散题

要求：

1. 解释 pack 内任务之间的连续性。
2. 解释 clean / distractor / ambiguous / reusable 这类分支设计的作用。

### 4. variable axes 字典

至少解释：

- `mode`
- `transfer_strategy`
- `handoff_profile`
- `runtime_reuse_contract`
- `plan_source`
- `benchmark_lane`
- `variable_axes`

要求：

1. 每个变量都要写它控制什么。
2. 每个变量都要写“改它会影响哪条结论”。

### 5. 评分与正确性判定

必须解释：

1. route / tool / exact match / admissible match 这类指标怎么用
2. scorer 在判断什么
3. negative control 为什么重要

### 6. 一个真实任务的完整 walkthrough

要求：

1. 选一个真实任务，优先选 checkout 类或当前主 headline 相关任务。
2. 从任务定义开始讲：
   - task 长什么样
   - Planner 接收什么、输出什么
   - Retriever 接收什么、输出什么
   - `text` 路径怎么传
   - `StateBus` 路径怎么传
   - Executor 怎么消费
   - Summarizer 怎么总结
   - 记忆如何写回
   - scorer 最后怎么判

### 7. 这个任务在证明什么，不在证明什么

要求：

1. 不要把单个 walkthrough 讲成总结论。
2. 说明它是帮助理解系统流，不是单独证明 superiority。

## 四、必须解释的术语

至少解释：

- `negative control`
- `single-variable contract`
- `public_surface`
- `evidence_tier`
- `claim_lanes`

## 五、验收清单

1. 读者读完能理解 pack 不是散题集合。
2. 读者知道任务如何连续、如何被评分。
3. 文档里至少有一个真实任务走完整流程。
4. walkthrough 里同时体现 `text` 和 `StateBus` 两种路径。
