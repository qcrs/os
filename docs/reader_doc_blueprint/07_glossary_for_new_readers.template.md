# 模板 07：新人术语表

建议目标文件：

- `docs/reader_guide/07_glossary_for_new_readers.md`

## 一、文档目标

这份文档专门解决“看不懂英文字段和内部术语”的问题。

要求：

1. 不只写一个英文到中文的对照表。
2. 每个术语都要解释“在本项目里具体是什么意思、在哪里出现、为什么重要”。

## 二、建议章节结构

### 1. 阅读方式说明

要求：

1. 先告诉读者这不是完整方法文档。
2. 这是辅助阅读的工具文档。

### 2. 核心对象术语

至少覆盖：

- `SampleTask`
- `Plan`
- `PlanStep`
- `StepResult`
- `StateRef`
- `MemoryHit`
- `MemoryCommit`
- `RunContext`

### 3. 实验变量术语

至少覆盖：

- `mode`
- `transfer_strategy`
- `handoff_profile`
- `runtime_reuse_contract`
- `plan_source`
- `benchmark_lane`
- `variable_axes`

### 4. 结果解释术语

至少覆盖：

- `headline`
- `support`
- `audit`
- `authoritative artifact`
- `quality floor`
- `parity`
- `residual`

### 5. 角色与结构术语

至少覆盖：

- `Planner`
- `Retriever`
- `Executor`
- `Summarizer`
- `validate`
- `control plane`
- `state plane`
- `memory plane`

## 三、每个词条的固定写法

每个词条建议都包含：

1. 英文名
2. 中文解释
3. 在本项目里的具体含义
4. 常见误解
5. 首次建议去读哪份文档

## 四、验收清单

1. 新人能靠这份表独立过掉大部分英文障碍。
2. 没有把“中文翻译”当成“解释”。
3. 至少指出常见误解。
