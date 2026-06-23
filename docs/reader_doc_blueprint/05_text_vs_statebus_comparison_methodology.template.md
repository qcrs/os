# 模板 05：`text` 与 `StateBus` 对比方法说明

建议目标文件：

- `docs/reader_guide/05_text_vs_statebus_comparison_methodology.md`

## 一、文档目标

这份文档是实验可信性的核心文档。它必须回答：

1. `text` 到底是什么。
2. `StateBus` 到底是什么。
3. 它们如何被严格比较。
4. 为什么这不是换题比较。

## 二、必须使用的输入

1. `eval/runner.py`
2. `agents/sample_agents.py`
3. 相关 task pack 定义
4. 相关 benchmark artifact

## 三、建议章节结构

### 1. 比较对象先定义清楚

要求：

1. 明确当前 communication headline 比较的是谁和谁。
2. 解释为什么要先定义 lane / mode / transfer surface。

### 2. `text` 路径是什么

要求：

1. 解释 `text` 路径上传递的是什么。
2. 解释下游怎么解释这些文本。
3. 解释它和“完全外部传统多 Agent baseline”是否相同。

### 3. `StateBus` 路径是什么

要求：

1. 解释结构化 packet、`StateRef`、中间状态和记忆在其中的作用。
2. 解释它不只是“少写一点文本”。

### 4. 固定变量与变化变量

必须有表格，至少包括：

- 固定了什么
- 改变了什么
- 为什么这样公平

### 5. handoff 差异

要求：

1. 分角色说明 `text` 和 `StateBus` 的 handoff 差异。
2. 不允许一句话糊成“文本 vs 结构化”。

### 6. prompt 与输入差异

要求：

1. 说明 prompt 设计对比较的影响。
2. 说明哪些差异来自 carrier，哪些差异不是 carrier。

### 7. 并列流程图

至少要有：

1. `text` 路径图
2. `StateBus` 路径图

### 8. 这套比较在回答什么，不回答什么

要求：

1. 说明当前比较能证明的范围。
2. 说明它不等于整体 superiority 的所有问题都解决了。

## 四、必须解释的术语

至少解释：

- `text_whole_lane`
- `text_strict_pure_lane`
- `natural_handoff_text`
- `state_packet_minimal`
- `handoff_profile`
- `transfer_strategy`

## 五、验收清单

1. 读者看完知道上游到底传了什么。
2. 读者看完知道下游到底消费了什么。
3. 读者能理解为什么这不是换题。
4. 文档里有明确的固定变量/变化变量表。
