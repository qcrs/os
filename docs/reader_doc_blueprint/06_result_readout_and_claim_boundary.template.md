# 模板 06：结果详解与口径边界

建议目标文件：

- `docs/reader_guide/06_result_readout_and_claim_boundary.md`

## 一、文档目标

这份文档只讲结果，不讲完整架构。它要回答：

1. 当前主要结果具体是什么。
2. 应该如何解释这些数字。
3. 哪些口径不能上读。

## 二、必须使用的输入

1. communication authoritative artifact
2. communication support artifact
3. typed-state support artifact
4. memory artifact
5. 当前冻结 docs

## 三、建议章节结构

### 1. 结果先导读

要求：

1. 先给读者一个结果导读。
2. 不要直接堆表格。

### 2. communication 结果详解

至少解释：

1. 关键 headline 指标
2. quality floor
3. planner 当前角色
4. summarizer residual 当前角色
5. parity diagnostic 当前角色

### 3. typed-state 结果详解

要求：

1. 说明 typed-state 在当前报告里支持了什么。
2. 明确它为什么还是 secondary。

### 4. memory 结果详解

要求：

1. 说明 memory 当前能正式写什么。
2. 明确为什么还不能升级为 superiority claim。

### 5. claim boundary

必须明确写出：

1. 可以正式说什么
2. 不可以正式说什么
3. 哪些是 residual，不等于 failure

### 6. 当前 gate 怎么读

要求：

1. 明确 `communication gate`
2. 明确 `formal stability gate`
3. 解释它们为什么不是一回事

## 四、必须解释的术语

至少解释：

- `route_exact_rate`
- `exact_match_rate`
- `admissible_match_rate`
- `wrong_family_rate`
- `parity diagnostic`
- `residual`

## 五、验收清单

1. 结果解释不脱离 artifact。
2. 读者能分清结果、残差、失败、边界。
3. 不会把 typed-state 或 memory 升格成 headline。
4. 不会把 gate 与 stability 混成一个词。
