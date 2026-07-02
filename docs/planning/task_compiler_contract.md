# Task Compiler Contract

日期：2026-06-26  
状态：`v2` 跨合同文档  
作用：定义自然语言任务如何被规范化为 `CanonicalTaskSpec`，以及在 `formal benchmark` 与 `interactive runtime` 中的不同失败处理策略。

---

## 1. 目标

这份合同要定死：

1. `TaskCompiler` 的输入输出
2. `CanonicalTaskSpec` 的最小字段
3. 字段枚举由谁维护
4. 编译失败时如何回退
5. 哪些路径允许进入 replay，哪些不允许

---

## 2. 基本结论

### 2.1 `CanonicalTaskSpec` 必须存在于 replay 之前

`exact_replay` 不允许直接对原始自然语言做哈希。

系统必须先得到一个：

1. 稳定
2. 可排序序列化
3. 受枚举约束
4. 可校验

的任务规格对象。

### 2.2 区分两条运行路径

这份合同不建议把所有场景都强行收口成一种失败策略。

更合理的默认分流是：

1. `formal benchmark / strict`
   - 解析失败即拒绝执行
2. `interactive runtime`
   - 允许降级到 `opaque_freeform`
   - 但禁用 `validated_replay / exact_replay`

这样既保护 formal 评测的可重复性，也不把交互体验做死。

---

## 3. `TaskCompiler` 的位置

`TaskCompiler` 应位于：

1. 用户输入之后
2. `Planner` 正式编图之前
3. replay candidate lookup 之前

也就是：

```text
user request
  -> task compiler
  -> canonical task spec
  -> planner / replay gate / route gate
```

---

## 4. 输入输出合同

### 4.1 输入

最小输入建议：

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class TaskCompilerInput:
    request_text: str
    task_mode: str  # "benchmark_strict" | "interactive"
    corpus_family: str = ""
    requested_outputs: list[str] | None = None
```

### 4.2 输出

最小输出建议：

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class CanonicalTaskSpec:
    task_family: str
    intent_op: str
    target_entities: list[str] = field(default_factory=list)
    time_scope: str = ""
    required_outputs: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    arguments: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "statebus.canonical_task_spec.v1"
```

同时建议产出编译诊断：

```python
@dataclass(frozen=True)
class TaskCompilerResult:
    status: str  # "compiled" | "opaque_freeform" | "rejected"
    canonical_task_spec: CanonicalTaskSpec | None
    compiler_warnings: list[str]
    compiler_errors: list[str]
```

---

## 5. 字段枚举由谁维护

### 5.1 不交给模型自由发明

关键字段枚举必须由代码维护，而不是由模型随意输出字符串。

建议至少把下面这些做成硬编码 Enum：

1. `task_family`
2. `intent_op`
3. `required_outputs`
4. `required_tools`

例如：

```python
from enum import Enum

class IntentOp(str, Enum):
    COMPARE_METRIC = "compare_metric"
    SUMMARIZE_RISK = "summarize_risk"
    GENERATE_CHART = "generate_chart"
    UPDATE_CHART = "update_chart"
    VALIDATE_OUTPUT = "validate_output"
```

### 5.2 维护责任

默认由：

1. `protocol/schema registry`
2. `task family owner`

共同维护这些枚举与字段说明。

不建议：

1. 在 prompt 里临时列一套枚举
2. 在不同角色里维护多套不一致的枚举

---

## 6. 失败与回退策略

### 6.1 `formal benchmark / strict`

如果编译失败，默认：

1. `TRAP_REJECTED`
2. 不进入 Planner
3. 不进入 replay gate
4. 该 run 记为 compile failure

这条路径下，不允许回退到模糊 NLP。

### 6.2 `interactive runtime`

如果编译失败，但请求仍可尝试执行，默认回退到：

1. `opaque_freeform`
2. 允许 Planner 走通用流程
3. 允许工具执行
4. 禁用 `validated_replay / exact_replay`
5. telemetry 中显式记录 `compiler_status = opaque_freeform`

### 6.3 为什么不直接静默放过

因为静默放过会造成：

1. `spec_hash` 漂移
2. replay 误命中
3. formal benchmark 不可复现

---

## 7. `spec_hash` 计算纪律

建议只对 canonical JSON 做哈希：

```text
SHA256(canonical_task_spec_json)
```

必须保证：

1. key 排序稳定
2. 不包含原始 display text
3. 不包含模型生成解释
4. 不包含瞬时 telemetry

---

## 8. 与 replay 的关系

### 8.1 exact replay

必须要求：

1. `compiler_status == compiled`
2. `canonical_task_spec` 通过 schema 校验
3. `spec_hash` 稳定存在

### 8.2 validated replay

默认也要求：

1. 至少有 `task_family`
2. `intent_op` 明确
3. 输出 contract 可判定

### 8.3 opaque freeform

默认：

1. 不参与 `exact_replay`
2. 不参与 `validated_replay`
3. 最多允许 `assist`

---

## 9. `MVP` 实现建议

### 9.1 benchmark 优先使用预编译 spec

`formal benchmark` 下最稳的做法是：

1. 任务样本文件直接附带 `canonical_task_spec.json`
2. 运行时不依赖自然语言临场编译
3. `TaskCompiler` 主要用于 interactive/demo

这也是当前冻结方案：

1. 首版 formal benchmark 默认走 `benchmark_strict`
2. `interactive opaque_freeform` 存在，但不参与 `validated_replay / exact_replay`

这能显著降低 benchmark 漂移风险。

### 9.2 interactive 路径再引入编译器

对交互式输入，可先用：

1. 小模型
2. rule-based extractor
3. schema validator

组合实现首版编译器。

---

## 10. 验收建议

建议最小验收：

1. 相同任务文本经编译后得到相同 `spec_hash`
2. 文案表述不同、语义等价的请求能落到相同 `CanonicalTaskSpec`
3. 缺少关键字段的 strict benchmark 请求被 `TRAP_REJECTED`
4. 同样的失败请求在 interactive 模式进入 `opaque_freeform`

建议后续补测试：

1. `tests/task_compiler/test_canonical_task_spec_hash.py`
2. `tests/task_compiler/test_strict_reject_vs_interactive_fallback.py`
3. `tests/task_compiler/test_enum_guardrails.py`
