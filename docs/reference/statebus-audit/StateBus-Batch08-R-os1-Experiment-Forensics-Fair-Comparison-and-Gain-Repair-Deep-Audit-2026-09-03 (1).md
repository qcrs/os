# StateBus Batch 08-R（源码重审版）
## Current `qcrs/os` Mainline × `qcrs/os1` Evolution：Benchmark Object、Fairness、Metric Semantics 与收益归因深度审计

> **日期**：2026-09-03  
> **当前源码 Truth**：`qcrs/os:master`，commit `8bfc6464ec236c0e121911095fc283129b0e7696`  
> **历史演进 Truth**：`qcrs/os1`，重点追踪 host prototype → benchmark fairness audit → v2 truth audit → Qwen3 full matrix  
> **文档定位**：替换上一版 Batch 08-R。本文不是“实验建议合集”，而是围绕当前源码逐链路回答：
>
> 1. 当前所谓 L0/L1/L2/L3 到底各自改变了什么；
> 2. 为什么某些收益消失、反向或与 `os1` 历史结果不一致；
> 3. 是机制本身没有收益、Runtime 太厚、A/B 不公平，还是指标聚合有问题；
> 4. “纯文本 baseline”到底应该是什么；
> 5. 哪些现有数字还能保留，哪些必须降级或重跑；
> 6. 最小改动应该落在哪些源码文件、函数与实验合同上。

---

# 0. Executive Decision

这次源码重审后的判断比上一版更明确：

> **StateBus 当前最大的问题不是“某个功能没优化好”，而是 Benchmark Object 仍然不够薄。**

当前主线已经比 `os1` 早期健康很多：Gold 基本转向 post-runtime scoring、Memory 已有 candidate→compatible→consumed→effect 漏斗、Semantic State 有真实跨 PID 消费、Prefix rate 已从 numerator/denominator 重算。

但当前正式实验仍存在四类会直接影响收益解释的问题：

```text
A. Experimental object 过厚
   ├─ L0→L1 不只改 carrier
   ├─ L1→L2 同时改 semantic selection + StateRef transfer
   └─ Full system compare 同时改变 Runtime / CodeAct / State / Memory

B. Baseline 语义没有完全定义清楚
   ├─ internal L0 ≠ traditional pure-text MAS
   ├─ external "pure text" 仍是 JSON-oriented structured roles
   └─ contract-conditioned task ≠ raw-user-request task

C. Fairness / task-object 问题
   ├─ route/tool 已被 CanonicalTaskSpec 高度预结构化
   ├─ route hints 默认开启
   ├─ legacy external summarizer 有 answer-bearing summary_hint
   ├─ continuous L0/L1/L2 仍能看见 prior artifact summaries
   └─ expected performance effects 被混入 quality gate

D. Metric / aggregation 问题
   ├─ control_bytes 两侧 measurement point 不一致
   ├─ internal comparison 对部分负向 delta 做 max(..., 0)
   ├─ non-additive metric 仍靠手写 special-case 修正
   └─ numeric_tolerance 实际只检查“可转成 float”
```

所以现在不能简单问：

> “为什么 StateBus 没收益？”

更准确的问题是：

> **我们现在到底在比较什么？这个实验的 treatment 是否只有一个？measurement point 是否一致？quality 与 mechanism activation 是否被混在一起？**

在这些问题解决之前，继续调 prompt、调 memory threshold 或增加新数据集，很容易重新走回 `os1` 早期“数字变漂亮，但因果越来越混”的路径。

---

# 1. 本轮审计方法：先读当前源码，再用 os1 解释历史

这次没有从 README 的结果表反推实现，而是按以下路径审计：

```text
qcrs/os master
│
├─ benchmark object
│  ├─ fixed_answer_runner.py
│  ├─ continuous_runner.py
│  ├─ comparator_runner.py
│  ├─ external_text_baseline.py
│  ├─ contest_fairness.py
│  └─ metric_aggregation.py
│
├─ runtime execution
│  ├─ smoke.py
│  ├─ role_path.py
│  ├─ driver.py
│  ├─ route_tool_catalog.py
│  └─ control/subprocess_worker.py
│
├─ task / gold
│  ├─ formal_registry_adapter.py
│  ├─ tasks/formal/*
│  └─ continuous_task_families/*/manifest.json
│
└─ docs/experiments/README.md
       ↓
       与真实源码逐项核对

然后：

qcrs/os1
│
├─ optimization_journal
├─ benchmark_fairness_audit
├─ state_transfer_benchmark_audit
├─ experimental_anomalies
├─ deep_data_analysis
├─ external_pure_text_baseline_contract
└─ Qwen3 full matrix / failure root cause
```

目的不是复述历史，而是确认：

```text
当前问题是历史遗留？
已经修复？
还是以另一种形式重新出现？
```

---

# 2. 当前 Mainline 的真实 L0/L1/L2/L3 并没有 README 看起来那么“单变量”

当前 `statebus/benchmark/fixed_answer_runner.py` 定义：

```text
L0
structured_control = false
semantic_pruning = false
replay = false
handoff_mode = text_collaboration

L1
structured_control = true
semantic_pruning = false
replay = false
handoff_mode = structured_collaboration

L2
structured_control = true
semantic_pruning = true
semantic_state_transfer = true
replay = false

L3
structured_control = true
semantic_pruning = true
semantic_state_transfer = true
replay = true
```

乍看像：

```text
L0 → L1 = structured control
L1 → L2 = semantic state
L2 → L3 = memory
```

但沿 `SmokeLayerConfig → RolePathRunner → RuntimeDriver` 继续读后，实际不是这么薄。

---

# 3. Root Cause A1：L0→L1 同时改变了 Control Carrier 和 LLM-visible Handoff Representation

## 3.1 `handoff_mode` 直接改变每个 Role 的 Prompt 构造

`statebus/runtime/role_path.py` 中：

```text
text_collaboration
→ _text_collaboration_prompt(...)

structured_collaboration
→ _structured_collaboration_prompt(...)
```

两者不是“同一模型 prompt，只把外部通信 protobuf 化”。

Text path 会生成类似：

```text
Task
Goal
Evidence
Candidate choices
Output contract
...
```

Structured path 会生成 tagged JSON / canonical packet。

因此：

```text
L0 → L1
```

至少同时改变：

```text
1. Runtime control encoding
2. role-to-role model-visible representation
3. prompt scaffolding
4. parsing/contract surface
```

所以当前 L0→L1 最准确的名字不是：

> Protobuf A/B

而是：

> **StateBus Internal Text-Rendered Collaboration vs Structured Collaboration**

---

# 4. 为什么这点非常重要

因为：

```text
binary wire encoding
```

和：

```text
LLM-visible prompt representation
```

是两层完全不同的东西。

模型看不到：

```text
Protobuf bytes
```

模型只看到：

```text
rendered prompt
```

所以如果 L0→L1 Token 有变化：

```text
不能自动归因给 Protobuf。
```

同样，如果 wire bytes 有变化：

```text
也不能自动归因给 Prompt Compiler。
```

当前 layer 把两者绑在了一起。

---

# 5. os1 历史已经验证过这个问题

`os1` 最早的 Live API repeat=10：

```text
Text
control ≈ 30,233 B
tokens ≈ 10,365
task ≈ 42.4 s

Protocol
control ≈ 23,892 B
tokens ≈ 10,238
task ≈ 44.0 s
```

结果：

```text
Control 明显下降
Token 只下降约 1%
Latency 甚至更差
```

后来加入：

```text
sb-plan-v1
sb-summary-v1
compact planner input/output
compact summarizer input/output
```

以后才突然得到：

```text
Token -33% ~ -34%
Latency -24% 左右
```

所以历史已经说明：

```text
大 Token Gain
主要来自 Prompt / Semantic Representation Compiler
而不是 binary codec。
```

---

# 6. 当前主线其实再次复现了同一规律

当前官方 `docs/experiments/README.md`：

```text
L0:
total token = 33,974

L1:
total token = 34,891
```

也就是：

```text
+2.70%
```

但 control / wire 大幅下降。

随后：

```text
L1:
34,891

L2:
17,739
```

Token 才大幅下降。

这和 `os1` 2026-07-14 Qwen3 full matrix 几乎是同一种现象：

```text
L0  total token 97,242
L1  total token 98,492
L2  total token 54,867
```

因此当前现象不是一次随机失败，而是：

> **StateBus 的真实成本结构。**

---

# 7. Root Cause A2：当前 `control_bytes` 不是对等的物理 Carrier Measurement

这是本轮最重要的源码问题之一。

`statebus/runtime/driver.py::_exchange_control_messages()`：

```python
control_bytes = (
    len(frame_control_message(loopback_message))
    if structured_control_enabled
    else runtime_input.retrieval.full_corpus_bytes
)
```

即：

## Structured

```text
control_bytes
=
serialized ExecRequest protobuf frame size
```

## Text

```text
control_bytes
=
full corpus bytes
```

这两个量不是同一个 measurement point。

---

# 8. 为什么这个 `control_bytes` 不能继续直接叫“控制面字节”

Text side 的真正 executor handoff 是：

```text
_build_matched_text_handoff(...)
```

生成的 UTF-8 message。

但当前 synthetic `control_bytes` 没有测：

```text
len(text_handoff.encode("utf-8"))
```

而是直接：

```text
retrieval.full_corpus_bytes
```

这意味着：

```text
Text:
data/evidence volume

vs

Structured:
control envelope volume
```

被放进同一个 metric。

因此当前：

```text
25,196 → 4,270
-83.05%
```

**不能作为“同一控制消息从 text 编码成 protobuf 后降低 83%”的物理证据。**

---

# 9. 当前 `control_bytes` 应怎么处理

P0 建议：

```text
control_bytes
→ deprecated
```

或重命名：

```text
synthetic_control_accounting_bytes
```

正式指标改成：

```text
request_wire_bytes
response_wire_bytes
logical_control_payload_bytes
data_plane_payload_bytes
```

每个指标必须明确：

```text
measurement point
producer
consumer
carrier
```

---

# 10. Root Cause A3：当前 `wire -68.95%` 也不是纯 Protobuf Codec Gain

继续读：

```text
statebus/control/subprocess_worker.py
```

发现更关键的事实。

Text carrier worker：

```text
recv_text_message()
```

以后只验证：

```text
"StateBus matched pure-text executor handoff."
"Task:"
"Output contract:"
"Current evidence:"
"Verified prior context:"
```

以及禁止 typed fields。

验证通过后直接回：

```text
ACK RECEIVED
RUN START
HEARTBEAT
RESULT SUCCESS
```

它并没有真正：

```text
读取 evidence
执行业务逻辑
根据 handoff 做 CodeAct
```

---

# 11. 真正的 CodeAct 在什么时候执行

当前 `run_smoke()` 中：

```text
RolePath Executor decision
    ↓
CodeActRunner.run(...)
    ↓
产生 candidate output
    ↓
artifact slice
    ↓
RuntimeDriver.run(...)
    ↓
control-plane exchange / worker lifecycle
```

所以当前普通主链中的 subprocess worker 更像：

```text
control/lifecycle validation worker
```

而不是：

```text
真正执行任务的 remote executor。
```

---

# 12. Structured branch 为什么 wire 小

Structured worker 收到：

```text
ExecRequest
```

里面主要是：

```text
workspace_root
manifest hash
artifact refs
state refs
output contract
runtime reuse contract
```

而不是把完整 evidence inline 进去。

所以当前：

```text
Text:
inline Current evidence + prior context

Structured:
reference / manifest / workspace identity
```

这是一种：

# **Inline Data vs Reference-Based Out-of-Band Data Plane**

对比。

不是：

# **同一 Payload：Text Encoding vs Protobuf Encoding**

---

# 13. 所以当前 `wire -68.95%` 应该怎么表述

可以保留为 scoped observation：

> 在当前 executor handoff 设计中，StateBus reference-based typed handoff 相比 inline UTF-8 evidence handoff 减少 UDS wire bytes。

不能写：

> Protobuf 比纯文本压缩 68.95%。

这两个 claim 完全不同。

---

# 14. 真正的 Codec Benchmark 应该怎么设计

新增：

```text
A0 — Control Codec Microbenchmark
```

固定同一个：

```python
CanonicalExecControl(
    trace_id,
    task_id,
    step_id,
    attempt_id,
    capability_id,
    input_refs,
    output_contract,
    deadline,
)
```

分别：

```text
TextStructCodec
ProtobufCodec
```

然后真正通过：

```text
UDS
```

测：

```text
request wire bytes
response wire bytes
encode µs
decode µs
schema validation µs
```

不允许：

```text
Text 带 full corpus
Protobuf 只带 refs。
```

---

# 15. Root Cause A4：L1→L2 同时改变 Semantic Selection 和 State Carrier

当前 L2：

```text
semantic_pruning = true
semantic_state_transfer = true
```

所以：

```text
L1 → L2
```

一次打开两个不同机制。

---

# 16. 这意味着当前 `Token -49.16%` 的归因有问题

官方结果：

```text
raw evidence
73,266 → 11,693 B

Prompt Token
30,737 → 13,599

Total Token
34,891 → 17,739
```

最明显的 causal source 是：

```text
进入 LLM 的 evidence 被选择/裁剪了。
```

而不是：

```text
embedding 本身从 shared memory 跨 PID 传了一次。
```

StateRef 提供：

```text
physical non-text transfer
schema/hash/lifecycle
consumer authorization
```

但：

```text
prompt token reduction
```

主要由：

```text
selection + hydration policy
```

决定。

---

# 17. 当前源码其实已经承认这一点

`continuous_runner.py` 已经存在：

```text
CONTINUOUS_TEXT_SEMANTIC_SELECTION_PROFILE
```

其配置：

```text
handoff_mode = text_collaboration
semantic_pruning = true
semantic_state_transfer = false
```

并明确标：

```text
diagnostic_claim_scope =
isolates_semantic_selection_from_non_text_state_transfer
```

Fixed-answer 也有同类 `T2`。

所以当前 repo 已经有正确方向，只是：

```text
它仍然被降为 diagnostic
```

而正式 headline 继续使用：

```text
L1 → L2
```

这个 bundled layer。

---

# 18. 正确的 Semantic State Factorial Design

应该正式提升为三条：

```text
S0
Full Evidence
Text Carrier

S1
Selected Evidence
Text Carrier

S2
Same Selected Evidence
StateRef Carrier
```

于是：

```text
S0 → S1
=
Semantic Selection Gain

S1 → S2
=
State Carrier Gain
```

---

# 19. S1→S2 应该测什么

不要要求：

```text
Token 再下降 50%
```

因为 evidence selection 已经相同。

应该测：

```text
producer re-serialization bytes
consumer reconstruction bytes
text handoff bytes
non-text data-plane bytes
materialize ms
resolve ms
schema/hash validation
consumer behavioral equivalence
information fidelity
```

这才是：

```text
StateRef mechanism
```

自己的 KPI。

---

# 20. Root Cause B1：Internal L0 不是赛题意义上的 “Pure Text MAS”

当前 L0 仍然：

```text
StateBus Runtime
StateBus TaskCompiler
StateBus RolePath
StateBus candidate surface
StateBus CodeAct
StateBus Artifact
StateBus Validator
StateBus persistence
StateBus telemetry
```

只是：

```text
handoff_mode = text_collaboration
structured_control = false
```

而且每个 LLM Role 仍返回：

```text
strict structured JSON
```

并接受 bounded route/tool candidate surface。

所以它更准确的名字：

# `StateBus Internal Text-Rendered Comparator`

而不是：

# `Traditional Pure-Text Multi-Agent Baseline`

---

# 21. Internal L0 仍然非常有价值

它适合回答：

> 同一个 StateBus runtime 中，把中间协作表示为 Text 还是 Typed Structured，增量有什么不同？

这是：

```text
mechanism causal attribution
```

非常有价值。

问题只是：

```text
不要把它命名成赛题 external pure-text baseline。
```

---

# 22. Root Cause B2：当前 External “Pure Text” 也还不是我们真正想要的 Pure Text

`statebus/benchmark/external_text_baseline.py` 已经比早期 `os1` 健康很多：

```text
不 import StateRef
不 import StatePool
不使用 StateBus memory/replay
有 contamination scan
有 visible-candidate gate
```

但读实际 prompt 后会发现：

## Planner

返回：

```json
{
  "candidate_key": "...",
  "route": "...",
  "tool_name": "...",
  "retrieval_objective": "..."
}
```

## Retriever

返回：

```json
{
  "candidate_key": "...",
  "route": "...",
  "tool_name": "...",
  "evidence_summary": "...",
  ...
}
```

## Executor

仍返回 route/tool JSON。

## Summarizer

返回：

```json
{"summary": "..."}
```

Agent 之间还会传：

```text
stable_json_dumps(planner_payload)
```

---

# 23. JSON 是文本，但问题不是“JSON 算不算文本”

这件事不能陷入词义争论。

赛题真正关心的是：

```text
传统文本协作
vs
结构化协议协作
```

所以应该用 operational definition。

当前 external baseline 是：

# **Textual Structured-Field MAS**

它没有 StateBus typed runtime，但仍有：

```text
machine-readable named slots
candidate_key
route/tool authority
deterministic JSON parse
```

这和真正的自然语言 Agent handoff 仍有距离。

---

# 24. 建议正式定义三种 Comparator

---

## 24.1 NL-MAS：赛题 Primary Pure-Text Baseline

Agent-to-Agent handoff：

```text
UTF-8 natural language
```

允许：

```text
短标题
bullet
source identifier
exact numeric values
```

不允许：

```text
JSON schema
candidate_key
StateRef
memory_ref
typed state id
machine-authoritative slot
out-of-band hidden state
```

推荐共同 instruction：

> Only communicate information needed by the next role. Do not reveal chain-of-thought. Preserve concrete evidence values, source identifiers, selected action intent and uncertainty.

关键：

```text
不故意让 Pure Text 很啰嗦。
```

---

## 24.2 TextStruct：内部 Codec Baseline

这不是 Pure Text MAS。

定义：

```text
同一个 Canonical Semantic Object
→ text/JSON serialization
→ deterministic parser
```

用途：

```text
只测 codec / carrier。
```

---

## 24.3 StateBusTyped

```text
Typed Protobuf Control
+
Ref / State Plane
+
Runtime policy
```

---

# 25. 最好再把 System-level Baseline 分成两种

这是解决“到底怎样才公平”的关键。

---

## 25.1 Contract-Conditioned NL-MAS

两边都从：

```text
同一个已 admission 的 public task contract
```

开始。

但 Pure Text side 把 contract 内容：

```text
自然语言渲染
```

而不是给 JSON/StateRef。

用途：

> 比较 task admission 之后的协作机制。

---

## 25.2 Raw-Request NL-MAS

两边都只拿：

```text
user request
public source
public tool descriptors
```

StateBus 自己：

```text
TaskCompiler
Planner
PlanPolicy
```

都属于系统方法。

用途：

> 比较完整 StateBus 相比传统 MAS 的 whole-system value。

---

# 26. 为什么必须同时保留这两个 System Comparator

如果只做 Contract-Conditioned：

```text
TaskCompiler 的价值被控制掉。
```

如果只做 Raw Request：

```text
TaskCompiler
PlanPolicy
State
Memory
Tool execution
```

全部同时变化，不能做组件归因。

所以：

```text
Contract-conditioned
=
更公平的协作机制比较

Raw-request
=
更真实的产品系统比较
```

---

# 27. Root Cause C1：当前任务已经把 route / tool 预结构化得过多

`CanonicalTaskSpec` 当前通常含：

```text
task_family
intent_op
required_outputs
required_tools
arguments
```

例如：

```text
intent_op = compute_trend
required_tools = table_retriever
```

这已经不是：

```text
“模型从自然语言里发现应该做什么”
```

而是：

```text
“Runtime 已经把任务编译成一个很强的执行合同。”
```

---

# 28. `route_tool_catalog.py` 又继续使用这些字段构造候选

Candidate surface 的 score 会使用：

```text
spec.task_family
spec.intent_op
metric
ticker
quarter
request_text
issue_terms
bucket preference
```

Formal adapter 又会优先使用：

```text
spec.intent_op
```

推导 expected route。

所以：

```text
route_exact
```

很大程度是在评估：

# **Contract Conformance**

不是：

# **Autonomous Routing Intelligence**

---

# 29. 更重要的是：Route Hint 默认开启

`run_smoke()`：

```python
STATEBUS_ROUTE_HINTS_ENABLED
default = 1
```

Retriever / Executor 会收到：

```text
canonical_task_spec.intent_op
top_candidate.route
```

作为：

```text
route_hints
```

RolePath 会把它转换成 preferred candidate / tie-break。

---

# 30. 这并不一定“不公平”

如果实验定义是：

> 已经经过 Task Admission / Contract Compiler 后，多个角色能否稳定执行已授权 workflow。

那么这是合理的。

因为：

```text
CanonicalTaskSpec 本来就是 Runtime authority。
```

但这时：

```text
route/tool exact
```

应该解释为：

```text
contract execution fidelity
```

不能解释成：

```text
Planner 自主路由能力。
```

---

# 31. 所以需要两套 Planner Benchmark

## P-Contract

输入：

```text
CanonicalTaskSpec
bounded capability surface
```

测：

```text
contract conformance
plan validity
downstream consumption
```

保留当前测试。

---

## P-Raw

输入：

```text
raw user request
public capability descriptors
```

关闭：

```text
route hints
expected route/tool
precompiled intent_op authority
```

测：

```text
task interpretation
capability selection
plan semantic correctness
```

这才是 Planner generalization。

---

# 32. Root Cause C2：Current External Baseline 有真实的 `summary_hint` 污染

这是本轮对 current master 的一个实际源码发现。

某些 legacy formal financial samples 直接写：

```json
"expected_facts": {
  "metric_value": "120"
},
"summary_hint": "Report the revenue value for ACME 2026Q1: 120."
```

也就是说：

```text
summary_hint
直接包含 Gold answer。
```

---

# 33. External Summarizer 会把它放进 Prompt

`external_text_baseline.py::_summarizer_prompt()`：

```text
Summary hint:
{sample.summary_hint}
```

因此对于这些 legacy fixed-answer cases：

```text
External Summarizer
直接看到答案式 hint。
```

---

# 34. 一个必须澄清的点：Current StateBus 主线没有同样把 `sample.summary_hint` 传进去

`fixed_answer_runner.py` 调用 `run_smoke()` 时传：

```text
request_text
canonical_task_spec
expected_facts
```

但没有传：

```text
sample.summary_hint
```

`run_smoke()` 内部的 `summary_hint` 是从：

```text
canonical_task_spec
```

重新生成的 generic summary objective。

所以：

```text
External side
```

和：

```text
StateBus side
```

这里实际上不是对称污染。

---

# 35. 这个问题会造成什么

至少两个影响：

## 1. Quality

External Summarizer 更容易生成正确 summary。

## 2. Token

External prompt 被额外塞入：

```text
answer-bearing summary hint
```

会增加 prompt token。

如果拿：

```text
StateBus token
vs
External token
```

做正式 headline，

可能会：

```text
夸大 StateBus 的 token advantage。
```

---

# 36. P0 修复

所有：

```text
summary_hint
expected_facts
expected_metric_effects
expected route/tool
```

只允许存在于：

```text
Evaluator / Benchmark Gold
```

除非该内容原本就是：

```text
用户真实输入。
```

Legacy fixed sample 中的 answer-bearing `summary_hint`：

```text
必须删除或改成 request_text。
```

然后 external comparator 全部重跑。

---

# 37. Root Cause C3：Current `expected_facts` 进入 `run_smoke()` API，但当前源码确实是在 Runtime settlement 后才评分

这一点要严谨，不能因为看到参数就误判泄露。

当前：

```text
fixed_answer_runner
→ run_smoke(expected_facts=...)
```

看起来危险。

但继续读 `run_smoke()`：

```text
RuntimeDriver.run(...)
完成
↓
memory / artifact settlement
↓
benchmark scoring
score_benchmark_output(expected_facts)
```

源码注释明确：

```text
benchmark scoring happens after Runtime settlement
never artifact verification
never memory commit
never replay selection
never role request
```

所以：

# **当前 StateBus role path 没有因为 `expected_facts` 参数本身就直接使用 Gold。**

---

# 38. 但这个 API 设计仍然不够安全

因为：

```text
Runtime function signature
```

仍然拿到了：

```text
Evaluator Gold
```

未来非常容易回归污染。

建议：

```text
run_smoke()
```

完全不接：

```text
expected_facts
quality gold
expected_metric_effects
```

改为：

```text
runtime_result = run_runtime(...)
score = evaluator.score(runtime_result)
```

甚至正式实验：

```text
Evaluator
独立进程
```

Runtime 根本：

```text
mount 不到 gold root。
```

---

# 39. Root Cause C4：Current Gold Visibility Audit 很好，但仍是“值碰巧出现”式 provenance

当前 `contest_fairness.py` 已经进步很多：

它会扫描：

```text
真实 persisted rendered requests
```

找：

```text
GOLD_ONLY_KEYS
quality_check literals
expected_metric_effects
unprovenanced expected values
```

这是值得保留的。

---

# 40. 但它有一个逻辑边界

当前判断 expected value 是否 authorized：

```text
if value in public_material
→ authorized
```

比如：

```text
120
```

只要 source corpus 里存在 `120`，

那么某个 role prompt 里出现 `120` 就可能被认为：

```text
有 public provenance。
```

但它无法证明：

```text
120 真的是通过 Retriever/EvidencePack 合法到达该 Role
```

还是：

```text
从 summary_hint 偷偷塞进去。
```

---

# 41. 正确的 Gold / Provenance Audit

不要：

```text
value substring provenance
```

改成：

```python
RoleVisibleDatum(
    value_digest,
    source_object_id,
    source_field,
    authorization_edge,
    producer_role,
    consumer_role,
)
```

Role-visible data 必须回答：

```text
“这个值是谁产生的？
从哪个 object 来？
沿哪个 authorized edge 到这里？”
```

而不是：

```text
“它是不是曾经在 public corpus 里出现过？”
```

---

# 42. Root Cause C5：Continuous L0/L1/L2 并不是真正 No-History

这是这轮另一个很重要的 current master 事实。

`continuous_runner.py` 对每个 layer 都做：

```python
history_runtime_roots = tuple(
    history_runtime_root_by_round[dep]
    for dep in sample.depends_on_rounds
)
```

然后：

```python
run_smoke(
    history_runtime_roots=history_runtime_roots
)
```

没有：

```text
if layer == L3
```

限制。

---

# 43. `run_smoke()` 会怎么使用这些 history roots

如果：

```text
history_runtime_roots
```

非空：

它会读取：

```text
_history_artifact_summaries(...)
```

然后放进：

```text
planner_scope_payload["artifact_context"]
```

最后进入：

```text
Planner Prompt Slice。
```

因此：

```text
L0
L1
L2
L3
```

只要 round 有 dependency，

Planner 都能看到：

```text
prior verified artifact summaries。
```

---

# 44. 这意味着什么

当前描述：

```text
L0 = pure text cold baseline
```

对 continuous chain 来说不准确。

更准确：

```text
L0
text collaboration
+ history artifact context
+ no replay

L1
structured collaboration
+ same history artifact context
+ no replay

L2
+ semantic selection/state
+ same history artifact context
+ no replay

L3
+ replay
```

---

# 45. 这件事有两面

## 好的一面

如果要隔离：

```text
Replay incremental effect
```

让 L2 和 L3 都看到相同 prior context，只有 L3 能 replay，反而有利于：

```text
增量归因。
```

## 坏的一面

不能继续把：

```text
L0
```

描述成：

```text
no-memory / cold / no-history。
```

也不能把：

```text
L0→L3
```

所有差异解释成：

```text
加入 memory。
```

---

# 46. Memory 应该显式分成四层

```text
H0
No History

H1
History Text Assist
prior verified summaries visible
no MemoryIndex reuse

M1
Memory Assist
candidate/compatible/consume
no skip

M2
Validated Replay

M3
Exact Replay
```

这样：

```text
H0 → H1
= ordinary context history value

H1 → M1
= indexed memory assist value

M1 → M2
= replay / work-skipping value

M2 → M3
= verified restoration value
```

---

# 47. Root Cause C6：Continuous Manifest 自己写了“希望看到什么收益”

当前 continuous manifest 有：

```text
expected_metric_effects
```

例如：

```text
L3_artifact_reuse_count_min
L3_skipped_step_count_min
L3_reuse_gain_min
```

以及 family-level：

```text
L1 control delta < 0
L2 raw evidence delta < 0
L3 reuse > 0
```

作为 mechanism test：

```text
可以存在。
```

问题是后面的 gate 怎么用了它。

---

# 48. `expected_metric_effects` 当前会进入 Quality Floor

`continuous_runner.py::_apply_case_metric_contracts()`：

如果实际 metric 没满足：

```text
expected min/max
```

它会构造：

```text
QualityFloorResult(
    quality_floor_pass=False,
    fact_coverage_passed=False,
    quality_floor_fail_reason="continuous_metric_contract_failed..."
)
```

也就是说：

```text
任务输出完全正确
```

但如果：

```text
expected reuse 没发生
```

仍可能显示：

```text
quality fail。
```

---

# 49. 这是实验设计上的 P0

因为它把三件事混在一起：

```text
Task Correctness
Mechanism Activation
Performance Direction
```

应该拆成：

```text
TaskQualityGate
MechanismActivationGate
PerformanceObservation
```

---

# 50. 正确规则

## TaskQualityGate

只看：

```text
output facts
artifact contract
citation/provenance
business correctness
```

## MechanismActivationGate

只看：

```text
state 是否真的 publish/consume
memory 是否真的 consumed
replay 是否真的 skip
APC 是否真的 hit
KV 是否真的 inherited
```

如果 mechanism 没启动：

```text
causal experiment invalid
```

但：

```text
task quality 不应该失败。
```

## PerformanceObservation

```text
bytes
tokens
latency
```

无论：

```text
正
负
零
```

都应该如实保存。

---

# 51. 绝对不应该做

```text
预期 token ↓
实际 token ↑
→ benchmark quality fail
→ 从 headline 排除
```

那会造成：

```text
survivorship bias。
```

---

# 52. Root Cause D1：Internal Comparison 会把负向结果 clamp 到 0

`fixed_answer_runner.py::run_fixed_answer_suite()` 中：

```python
handoff_bytes_delta_l0_to_l1 = max(L0 - L1, 0.0)

prompt_visible_bytes_delta_l0_to_l1 = max(L0 - L1, 0.0)

control_bytes_delta_l0_to_l1 = max(L0 - L1, 0.0)

raw_evidence_bytes_delta_l1_to_l2 = max(L1 - L2, 0.0)

reuse_gain_delta_l2_to_l3 = max(L3 - L2, 0.0)
```

这意味着：

如果 treatment 更差：

```text
真实：
-100
```

最终 summary：

```text
0
```

---

# 53. 这会直接隐藏 Regression Direction

这是 benchmark metric pipeline 的明确问题。

所有正式 delta 必须：

```text
signed
```

统一定义：

```text
treatment - baseline
```

或：

```text
baseline - treatment
```

但不能：

```text
max(..., 0)。
```

如果为了展示 reduction：

另算：

```text
reduction_if_positive
```

但 raw signed delta 必须保留。

---

# 54. Root Cause D2：Metric Aggregation 已经修过 Prefix Rate，但整体仍是 ad-hoc

当前：

```text
metric_aggregation.py
```

已经会重新计算：

```text
prefix hit rate
observed vLLM hit rate
savings ratio
```

这修复了 `os1` 历史出现过的：

```text
prefix hit rate = 17.18
甚至 aggregate 223.31
```

这种明显错误。

这是 current master 的进步。

---

# 55. 但当前架构仍然危险

Runner 仍然先：

```text
for every float metric:
    SUM
```

再：

```text
针对少数已知 rate 手工修正。
```

未来新增：

```text
cache hit ratio
success rate
mean entropy
p95
average TTFT
```

如果忘记 special-case，

就会再次出现：

```text
rate > 1。
```

---

# 56. 应该增加 `MetricSemanticsRegistry`

例如：

```python
MetricSpec(
    name="memory_candidate_count",
    kind="COUNTER",
    unit="count",
    aggregate="SUM",
)

MetricSpec(
    name="prefix_hit_rate",
    kind="RATE",
    numerator="prefix_hits",
    denominator="prefix_queries",
)

MetricSpec(
    name="ttft_ms",
    kind="SAMPLE",
    aggregate=("P50", "P95", "MEAN"),
)

MetricSpec(
    name="worker_ready",
    kind="GAUGE",
    aggregate="LATEST",
)
```

---

# 57. 自动 invariant

```text
RATE:
0 <= x <= 1

COUNT:
x >= 0

DURATION:
x >= 0

PERCENTILE:
must be derived from sample ledger
```

一旦：

```text
rate > 1
```

run：

```text
evidence invalid
```

而不是：

```text
等人工发现。
```

---

# 58. Root Cause D3：`numeric_tolerance` 当前不是 tolerance

`statebus/benchmark/scoring.py` 当前：

```text
numeric_tolerance:field:0.01
```

实际上只做：

```text
float(observed)
float(tolerance)
```

能 parse：

```text
就 pass。
```

并没有：

```text
abs(observed - expected) <= tolerance。
```

`run_smoke()` 内部同类 deterministic check 也有类似语义。

---

# 59. 这是否意味着当前所有数值 Quality 都无效

不是。

因为后续：

```text
expected_facts
```

post-runtime scoring 仍可能检查 exact expected values。

所以准确结论是：

> `numeric_tolerance` 这个 quality-check 名称与实现不一致；它当前相当于 `numeric_parseable`，不能单独作为数值容差证据。

---

# 60. 修复

正式 evaluator：

```python
NumericCheck(
    field,
    expected_value,
    abs_tol,
    rel_tol,
)
```

并且：

```text
expected_value
```

只存在 evaluator。

---

# 61. Root Cause D4：External Comparator 的 Latency 顺序重新出现了 os1 已经踩过的坑

`comparator_runner.py` 当前默认：

```text
statebus
then
external
```

metadata 明确：

```text
serialized_statebus_then_external_within_each_mode_v1
```

Latency headline gate 只要求：

```text
task_ms_delta favorable
serialized_repeat_count >= 3
```

没有要求：

```text
AB/BA
randomized pair order
paired CI
```

---

# 62. os1 早在 2026-06-07 就发现这个问题

早期：

```text
text 全跑完
再跑 protocol
```

导致：

```text
live API service-load/time drift。
```

后来改成：

```text
AB
BA
AB
BA
```

才修掉。

当前 comparator 又采用固定：

```text
StateBus → External
```

顺序。

这是一个历史回归。

---

# 63. 正式 Latency 必须改

每个 pair：

```text
pair1: A → B
pair2: B → A
pair3: A → B
pair4: B → A
```

或 seeded randomized blocks。

同时：

```text
warmup excluded
local vLLM
same GPU
same model instance state policy
same cache policy
same memory namespace
```

---

# 64. Explicit KV 实验也存在顺序风险

官方实验文档写得很清楚：

```text
先 10 个 full replay baseline
后 10 个 continuation
```

虽然有每阶段 warmup，

仍可能受：

```text
temperature drift
GPU clocks
allocator state
service residency
background load
```

影响 latency。

机制层：

```text
computed prefill token
```

不太受这个问题影响。

但：

```text
TTFT
wall
```

最好重跑 AB/BA。

---

# 65. Prefix 实验反而设计得更好

Prefix 当前：

```text
Shared-first
Independent-first
```

交替。

这就是应该推广到：

```text
KV
Memory
External System Compare
```

的 paired-order pattern。

---

# 66. Root Cause B3：External Baseline 与 Full StateBus 在 Executor 功能上也不是等价成本

External public tool 路径：

```text
external_public_tools.py
```

会直接用 Python：

```text
读 CSV
计算 mean
IQR
groupby
trend
delta
```

而 StateBus side：

```text
Planner
Retriever
CodeAct generation
AST/policy
sandbox execution
Artifact
Validator
persistence
telemetry
```

两侧工作量明显不同。

---

# 67. 这是不是“不公平”

取决于 claim。

如果 claim：

> Full StateBus 系统 vs 轻量 Pure-Text 系统的整体 trade-off

可以。

因为：

```text
可审计 CodeAct
artifact lifecycle
memory
```

本来就是产品能力。

如果 claim：

> Structured communication 让 latency 降低 X%

不可以。

因为：

```text
Executor subsystem 都不同。
```

---

# 68. 所以 Full External Compare 只能做 System-Level Claim

必须明确：

```text
B-System
```

不是：

```text
A-Mechanism。
```

---

# 69. os1 历史：早期 benchmark 为什么看起来特别漂亮

回看最早任务：

```text
expected_reuse
reuse_tags
summary_hint
task_theme
```

Task 文本还直接写：

```text
Reuse previous...
Replay previous...
```

Planner 也会看到：

```text
expected_reuse
reuse_signature
```

所以早期：

```text
80% memory hit
```

本质更像：

```text
compatibility-keyed controlled replay。
```

---

# 70. 历史 Memory Store 也不是纯 Semantic NN

旧 `memory/store.py`：

```text
task_theme exact
encoder exact
tags
tags_any
tags_all
required_metadata reuse_signature
```

全部过完，

才 FAISS。

所以：

```text
semantic similarity
```

只是最后一级。

---

# 71. 这其实不是坏事

Replay 本来就应该：

```text
严格 compatibility
fail closed
```

真正的问题是：

```text
不能把它叫成“开放 Semantic Memory 80% hit”。
```

---

# 72. Current Master 在这里已经明显更健康

当前官方结果：

```text
20 queries
18 queries with candidates
48 candidates
9 compatible
7 actual-use
39 rejected
2 skipped steps
```

这反而比：

```text
8/10 expected → 8/10 hit
```

可信得多。

因为真实 memory system 应该：

```text
candidate 多
compatible 少
actual use 更少。
```

---

# 73. 但 Current Continuous Task 仍然是强 contract-driven reuse

当前 operating manifest 明确写：

```text
reuse_contract.produces
reuse_contract.consumes
minimum_reuse_class
depends_on_rounds
```

甚至 request text 有：

```text
"reusing the CSV profiling..."
```

所以它非常适合：

# **Memory Mechanism Activation / Compatibility Test**

但不能独自证明：

# **Blind Memory Discovery / General Memory Intelligence**

---

# 74. Memory 最终需要两套 Suite

## M-Contract

保留当前：

```text
显式 dependency
显式 reuse contract
known compatible/incompatible
```

用途：

```text
验证机制正确
```

---

## M-Blind

任务只描述当前目标：

```text
不写 expected_reuse
不写“reuse previous”
不告诉 memory id
```

Runtime 自己：

```text
retrieve candidates
compatibility
policy
consume
```

Evaluator 才知道：

```text
是否存在有价值的历史对象。
```

用途：

```text
验证 general reuse behavior。
```

---

# 75. Memory 最大的因果问题：必须 Same-Target Cold/Warm

历史 `os1` 曾把：

```text
group 第一个 task
```

作为所有 follow-up 的 cold baseline。

这是错误 counterfactual。

正确：

```text
same target X
```

---

# 76. 推荐 Memory Pair

先生成：

```text
VerifiedHistorySnapshot_r
```

clone 两份。

## Cold

```text
相同 history physical files
memory consumption denied
```

## Warm

```text
same history
memory consumption enabled
```

然后：

```text
X_cold
vs
X_warm
```

---

# 77. 为什么 Cold 也保留相同 history files

避免：

```text
page cache
filesystem layout
metadata load
directory count
```

差异。

只让：

```text
Memory Policy
```

成为 treatment。

---

# 78. Current `adaptive_memory.py` 更像 Mechanism/Funnel Suite，而不是完整 Cold/Warm Comparator

当前 Adaptive Memory：

```text
shared family memory root
6 serial cases
candidate/compatibility/consume/effect
negative incompatible fixture
```

它非常适合证明：

```text
memory funnel
negative compatibility
```

但代码自身没有同时构造：

```text
same-target no-memory paired branch。
```

所以当前文档中的：

```text
516.1s → 420.7s
28,379 → 21,638
```

需要在最终 evidence closure 中有一个明确：

```text
PairManifest
```

把：

```text
cold run path
warm run path
task digest
model digest
history snapshot digest
run order
```

一一闭合。

否则数字虽然可能来自真实运行，但 reviewer 很难从代码直接确认 counterfactual。

---

# 79. os1 历史还有一个非常重要的结论：Memory Assist 本来就不一定能赢

真实 repeat：

```text
memory_off
<
assist_only

但

replay_enabled
<
memory_off
```

原因：

```text
Assist:
多查一次 Memory
多输入一些 context
不跳 work

Replay:
直接减少 work
```

所以最终不要强行要求：

```text
Memory Assist latency 必须优化。
```

它可以主要提升：

```text
quality
consistency
decision stability
```

而：

```text
Replay
```

承担：

```text
compute reduction。
```

---

# 80. Runtime “机制太厚”到底体现在哪里

用户担心：

> 会不会不是 benchmark 问题，而是系统设计本身就太厚？

答案是：

# **两者都有。**

Current `run_smoke()` 是一个很厚的 production-like experimental harness：

```text
TaskCompiler
Planner
semantic plan resolution
retrieval
optional semantic subprocess
Memory lookup
Replay gate
RolePath
optional Logit
CodeAct
workspace
artifact
validators
RuntimeDriver
UDS lifecycle
memory commit
post-runtime scoring
telemetry
prefix accounting
```

这使得：

```text
Full E2E
```

当然很难把每个微机制节省完全转成 wall-time speedup。

---

# 81. “厚”本身不是错误

因为赛题也要求：

```text
完整 Runtime
协议
状态
记忆
评测
稳定运行
```

错误是：

```text
用 Full Runtime
去测一个 200B Control Codec
然后说这个 E2E delta 就是 codec 效果。
```

---

# 82. 正确架构应该区分

```text
Production Runtime
        ↑
用于完整性 / final demo

Mechanism Harness
        ↑
用于 causal attribution
```

两者复用：

```text
真实 codec
真实 StateStore
真实 Memory policy
真实 Worker
```

但 mechanism harness 不需要：

```text
每次都跑完整 CodeAct + persist + all audit。
```

---

# 83. 这不是“为了 benchmark 关掉真实功能”

关键是：

```text
实验对象不同。
```

例如 Codec benchmark 的科学问题：

> 同一个 control semantic object，TextStruct 与 Protobuf 谁的 wire/encode/decode 成本低？

它根本不需要：

```text
CodeAct。
```

---

# 84. Production Full System Compare 仍然保留

但是它回答：

> 整个 StateBus 产品栈相比 NL-MAS 的 quality / cost frontier 是什么？

而不是：

> Protobuf 快多少。

---

# 85. 当前 Runtime 输出为什么仍然容易吃 Completion Token

`role_path.py` 的每个 role 都要求结构化 JSON。

即使 current 已经有 lean completion 等演进，

模型仍然需要输出：

```text
route
tool
artifact related semantic fields
candidate selection
summary schema
```

历史 `os1` Qwen3 truth audit 曾出现：

```text
StateBus completion
比 external +80.5%
```

其中很多字段其实是：

```text
Runtime already knows。
```

---

# 86. 这里最值得优化的不是重新用单字母 key

而是进一步拆：

```text
RoleSemanticOutput
vs
RuntimeAuditEnvelope
```

---

# 87. RoleSemanticOutput

模型真正需要决定：

```python
RoleSemanticOutput(
    selected_candidate_ids,
    operation,
    semantic_decision,
    user_visible_content,
    uncertainty,
)
```

---

# 88. RuntimeAuditEnvelope

Runtime 自动填：

```python
RuntimeAuditEnvelope(
    task_id,
    step_id,
    attempt_id,
    input_ref_hashes,
    output_ref_hashes,
    provider_binding_hash,
    validator_digest,
    evidence_pack_hash,
    timing,
    provenance,
)
```

不要让 LLM：

```text
重新念一遍 hash / ref / attempt metadata。
```

---

# 89. 这是比 `sb-plan-v1 {r,x,s}` 更好的优化

旧 short-key 的问题：

```text
模型需要学一个人为缩写协议。
```

更好的设计：

```text
LLM schema 保持语义可读
Runtime binary representation 自己 compact。
```

---

# 90. Current Fairness Manifest 还缺什么

当前 internal carrier fairness 会检查：

```text
same task family
same role graph
same scorer
same quality floor
same tier
same role mode
same embedding
same statebus mode
same semantic pruning
same replay
same four-role counts
```

不错。

但它没有锁：

```text
consumer implementation digest
fallback policy digest
route-hint config
executor transport
history artifact context digest
actual role-visible semantic content digest
cache namespace
```

因此：

```text
pass_hard_gate
```

仍不能证明：

```text
only carrier changed。
```

---

# 91. FairnessManifest v2 推荐

每一对 A/B：

```json
{
  "pair_id": "...",

  "fixed": {
    "task_source_digest": "...",
    "user_request_digest": "...",
    "public_source_digest": "...",
    "tool_surface_digest": "...",
    "role_graph_digest": "...",
    "model_config_digest": "...",
    "scorer_digest": "...",
    "history_snapshot_digest": "...",
    "consumer_code_digest": "...",
    "fallback_policy_digest": "...",
    "route_hint_policy_digest": "...",
    "cache_policy_digest": "..."
  },

  "varied_axes": [
    "control_codec"
  ]
}
```

---

# 92. 如果是 Internal Carrier A/B

额外要求：

```text
consumer_code_digest equal
producer_semantic_output_digest equal
fallback_policy_digest equal
tool_surface_digest equal
```

只有：

```text
carrier
```

允许不同。

---

# 93. 如果是 Full System Compare

则：

```text
varied_axes
```

可以是整个 system implementation。

但 metadata 必须标：

```text
claim_scope = system_level
causal_component_attribution = false
```

---

# 94. 赛题“纯文本”公平对比的最终合同

---

## Baseline：NL-MAS

### Agent 数量

```text
Planner
Retriever
Executor
Summarizer
```

### 相同

```text
user-visible task
public datasets
public source documents
public tool semantics
base model/revision
temperature/seed policy
max logical calls
max physical requests
total token ceiling
role responsibilities
final output contract
private scorer
history availability
```

### Baseline 独有

```text
Natural-language A2A messages
No StateRef
No typed memory ref
No out-of-band state
No deterministic structured packet recovery
```

### StateBus 独有

```text
typed control
state refs
policy gates
memory/replay
```

---

# 95. Pure Text 不应该故意变成“全文复述”

Baseline prompt：

> Communicate only the minimal information needed by the next role. Preserve exact numeric values, source identifiers, selected action intent, and uncertainty. Do not reveal chain-of-thought.

也就是说：

```text
Text 可以很 concise。
```

否则：

```text
人为把 baseline 做胖
```

也是不公平。

---

# 96. Final output 是否允许 JSON

可以。

因为：

```text
final evaluator serialization
```

不是：

```text
Agent-to-Agent coordination protocol。
```

要避免的是：

```text
A2A 每条消息都用 machine-authoritative JSON slot
然后还称“traditional pure text”。
```

---

# 97. 工具调用是否允许结构化参数

也可以。

工具 API 本身通常就是：

```text
structured call。
```

赛题比较的是：

```text
Agent collaboration communication
```

不是要求：

```text
所有工具都不能有 schema。
```

关键是两边：

```text
工具接口相同。
```

---

# 98. BenchAgent 与 Nature 2026 对这个问题的启发

BenchAgent 很适合我们：

```text
SI = Substrate-Internal
PAE = Protocol-Aligned External
```

对应：

```text
StateBus Internal Mechanism A/B
+
External NL-MAS System Comparator
```

Nature Machine Intelligence 2026 的 controlled MAS study 则明确强调：

```text
same task prompts
same tools
matched compute budget
vary coordination
```

并把：

```text
communication overhead
```

当成实际成本，而不是免费资源。

这个原则应该进入 StateBus 的正式 Fairness Contract。

---

# 99. 新实验架构：不要再用一个 L0-L3 回答所有问题

最终建议四套 Suite。

---

# 100. Suite A — Mechanism Attribution

目的：

```text
解释“为什么”
```

---

## A0 — Control Codec

```text
TextStruct
vs
Protobuf
```

只变：

```text
encoding
```

无 LLM。

指标：

```text
request wire
response wire
encode
decode
parse
```

---

## A1 — Role Representation / Protocol Compiler

```text
Natural concise text rendering
vs
Canonical structured rendering
```

固定：

```text
carrier
task
model
semantic information
consumer logic
```

测：

```text
prompt token
completion token
prompt scaffolding
quality
```

---

## A2 — Semantic Selection

```text
Full Evidence Text
vs
Selected Evidence Text
```

两边：

```text
Text carrier
```

只变：

```text
selection。
```

---

## A3 — State Carrier

```text
Selected Evidence Text
vs
Same Selection via StateRef
```

只变：

```text
carrier / materialization。
```

---

## A4 — Memory Assist

```text
same target
same history
policy denies memory
vs
memory assist
```

禁止 skip。

---

## A5 — Validated Replay

```text
same target cold
vs
validated replay
```

---

## A6 — Exact Replay

```text
same target cold
vs
exact restoration
```

---

## A7 — APC

按 Batch 06：

```text
independent exact prefix
vs
shared exact prefix
```

task-local counters。

---

## A8 — Explicit KV

```text
full replay
vs
engine-local continuation
```

APC off。

重新用：

```text
AB/BA
```

跑 TTFT/wall。

---

# 101. Suite B — Contest System Comparator

---

## B0 Contract-Conditioned

```text
NL-MAS
vs
Full StateBus
```

双方拿：

```text
same admitted public task semantics。
```

---

## B1 Raw Request

```text
NL-MAS
vs
Full StateBus
```

双方只拿：

```text
raw user request
public sources
public tool descriptions
```

StateBus TaskCompiler/PlanPolicy 算系统能力。

---

# 102. Suite C — External Generalization

不是当前 P0。

可以：

```text
BFCL
LongMemEval-V2
```

后续有时间：

```text
τ³
SILO-BENCH small-scale communication stress
```

用途：

```text
证明不是只对 repo-local family 有效。
```

---

# 103. Suite D — Reliability / Soak

和 Batch 07 衔接：

```text
20–50 continuous tasks
worker crash
timeout
retry
late result
state cleanup
memory persistence
restart
```

---

# 104. 新的 Metric Taxonomy

必须彻底停止：

```text
一个 control_bytes 包含所有东西。
```

---

## Communication

```text
logical_message_count
logical_payload_bytes

request_wire_bytes
response_wire_bytes

inline_text_bytes
ref_control_bytes

data_plane_state_bytes
```

---

## Model

```text
prompt_tokens
completion_tokens
total_tokens

logical_llm_call_count
physical_model_request_count
```

---

## State

```text
state_publish_count
state_resolve_count
state_release_count

state_payload_bytes
state_materialize_ms
state_resolve_ms

cross_pid_consume_count
behavior_effect_count
```

---

## Memory

```text
query_count
candidate_query_count
candidate_count

compatible_query_count
compatible_candidate_count

consumed_query_count
consumption_count

behavior_effect_query_count

validated_replay_count
exact_replay_count

skipped_step_count
skipped_llm_logical_call_count
```

---

## Latency

```text
role_TTFT
role_TPOT
role_ITL
role_E2E

mechanism_stage_ms
integrity_stage_ms
task_E2E
```

---

# 105. 不要把 State/Data Plane Bytes 和 Control Wire Bytes 混在一起

例如 StateRef：

```text
control:
ref metadata 150 B

data plane:
embedding 110 KB
```

如果只说：

```text
wire 150 B
```

会误导。

必须报告：

```text
Control plane
Data plane
Model-visible plane
```

三套账。

---

# 106. 为什么 StateRef 不一定更省总 Bytes

因为可能：

```text
Text selected summary = 800 B

StateRef embedding = 100 KB
```

但 StateRef 仍可能有价值：

```text
不丢信息
可数学消费
不需要 LLM 重编码
有 lifecycle
可复用
```

所以 State Innovation 不能简化为：

```text
bytes 越小越好。
```

---

# 107. Break-even 是更专业的指标

定义：

```text
B*
```

为：

```text
State mechanism 的 saved downstream cost
=
state materialization/transfer/resolve overhead
```

对应：

```text
payload/context > B*
→ State worthwhile

payload/context < B*
→ inline text may be better
```

---

# 108. 这能解释当前不同 workload 的现象

Operating 长表格：

```text
semantic pruning 大赚
```

短 evidence：

```text
state overhead 可能大于 saving
```

这不是系统失败。

是：

```text
workload crossover。
```

---

# 109. 建议按 Input Size 分桶

```text
Tiny       < 1K token
Medium     1K–4K
Long       4K–16K
Very Long  > 16K
```

然后画：

```text
context size
vs
token saved
vs
state overhead
vs
E2E delta
```

比单一平均 speedup 更有价值。

---

# 110. Current Claim Matrix：哪些还能保留

| Claim | 当前判断 | 原因 |
|---|---|---|
| SemanticState 真实跨 PID publish/consume | **KEEP** | 有物理 worker consumption |
| SemanticState 会改变 selection | **KEEP** | holdout 有 behavioral effect |
| L1→L2 Token -49.16% 是 StateRef carrier gain | **WITHHOLD** | selection + carrier bundled |
| Structured `control_bytes -83.05%` 是 protobuf compression | **WITHHOLD** | measurement point 不一致 |
| Structured `wire -68.95%` | **RENAME / SCOPED** | inline text vs ref-based handoff，不是 codec-only |
| L0→L3 Token -47.40% | **KEEP AS COMBINED STACK OBSERVATION** | 不能归因给 protocol |
| L0→L3 wall -6.32% | **DIAGNOSTIC** | fixed-order / thick runtime / history semantics |
| Memory 48 candidate / 9 compatible / 7 actual-use | **KEEP** | 很好的真实 funnel |
| Memory latency/token paired gain | **KEEP AS REPORTED, RERUN FOR FINAL HEADLINE** | 需 PairManifest 与 same-target counterfactual闭合 |
| External Pure-Text formal superiority | **WITHHOLD UNTIL CLEAN RERUN** | baseline structured + summary_hint issue |
| `numeric_tolerance` | **DOWNGRADE** | 当前只是 parseable |
| Prefix task-local hit | **KEEP** | numerator/denominator已修正，且 AB order较好 |
| Explicit KV computed prefill | **KEEP** | 机制直接观测 |
| Explicit KV TTFT/wall | **RERUN** | baseline 10 后 continuation 10，顺序不理想 |

---

# 111. Current README 最需要改的一句话

现在写：

> L0 与 L1 保持 10 个任务、50 条逻辑消息和质量结果一致，只改变控制消息的表示方式。

源码层面不够准确。

应该改成：

> L0 与 L1 保持任务、角色图和下游功能合同一致，但同时切换文本协作表示与 typed structured collaboration；当前结果可用于内部协作表示比较，不能单独归因于 Protobuf codec。

在新 A0 完成后，再单独写：

> identical CanonicalExecControl TextStruct→Protobuf wire reduction。

---

# 112. Current README 的 Embedding 表述也应收紧

当前：

> Embedding 状态 raw evidence -84%，Token -49%。

建议拆：

> Semantic selection 将模型可见 evidence 从 X 降至 Y；同一 L2 lane 同时使用 SemanticStateRef 完成跨 PID 非文本 selection state 消费。现有 L1→L2 waterfall 尚不能把 Token reduction 单独归因于 StateRef carrier。

待 S1/S2 formal 后再写：

```text
Selection Gain
Carrier Gain
```

分别多少。

---

# 113. Current “Pure Text” 名字建议统一重命名

内部：

```text
L0
StateBus Internal Text Collaboration
```

外部当前实现：

```text
External Textual-Structured Four-Role Baseline
```

新增真正赛题 baseline：

```text
External NL-MAS v1
```

不要三个对象都叫：

```text
pure text。
```

---

# 114. os1 演进对当前最重要的六条教训

---

## Lesson 1

```text
Protobuf ≠ Token Reduction
```

历史和当前都验证。

---

## Lesson 2

```text
Prompt Compiler
必须单独成为 treatment。
```

---

## Lesson 3

```text
Text/State consumer semantics
必须完全相同。
```

历史 text executor 多一次 lexical fallback 曾直接把 quality 结果翻转。

---

## Lesson 4

```text
Memory assist
≠
replay。
```

只有真正 skip work 才有稳定 compute gain。

---

## Lesson 5

```text
Rate / freshness / mode aggregation
会制造完全错误的 headline。
```

历史出现过：

```text
rate > 1
handoff bytes cross-mode bleed
stale reused result
negative control false pass
```

---

## Lesson 6

```text
Benchmark gate 必须跟机制语义一起演进。
```

历史 Exact Replay 明明成功减少三个 downstream roles，却被旧 gate 要求“四角色都必须调用”判成失败。

---

# 115. Current Master 哪些地方确实比 os1 好很多

不要因为本轮发现问题就推翻现有主线。

已经明显修对：

```text
1. benchmark Gold scoring 放到 Runtime settlement 后

2. rendered role request Gold audit

3. Memory candidate / compatibility / consume / effect 分层

4. incompatible negative fixture

5. SemanticState 真跨 PID consume

6. Prefix observed rate 从 hits/queries 重算

7. Exact/validated replay 分开

8. State / Artifact / Memory 生命周期更明确

9. External baseline 有 import/typed-state contamination guard

10. T2 diagnostic 已经意识到 selection vs carrier confound
```

问题不是：

```text
重新写系统。
```

而是：

```text
把 Benchmark Contract 补到与当前架构成熟度匹配。
```

---

# 116. P0 源码修改计划

---

## P0-1 — 修 `control_bytes`

**文件**

```text
statebus/runtime/driver.py
```

**当前问题**

```text
Text = full_corpus_bytes
Structured = protobuf frame
```

**修改**

新增：

```text
control_logical_payload_bytes
request_wire_bytes
response_wire_bytes
data_plane_reference_bytes
inline_handoff_bytes
```

旧：

```text
control_bytes
```

deprecated。

---

## P0-2 — 建立真正 Codec Harness

**文件**

```text
statebus/control/*
statebus/benchmark/
```

新增：

```text
control_codec_benchmark.py
```

同一 Canonical object：

```text
TextStructCodec
ProtobufCodec
```

---

## P0-3 — 把 T2 提升为 Formal Factorial

**文件**

```text
statebus/benchmark/fixed_answer_runner.py
statebus/benchmark/continuous_runner.py
```

正式加入：

```text
S0 full-text
S1 selected-text
S2 selected-state
```

---

## P0-4 — 拆 Quality / Activation / Performance Gate

**文件**

```text
statebus/benchmark/continuous_runner.py
```

删除：

```text
expected_metric_effects
→ QualityFloor
```

改：

```text
task_quality
mechanism_activation
performance_observation
```

三层独立。

---

## P0-5 — 删除 Signed Delta Clamp

**文件**

```text
statebus/benchmark/fixed_answer_runner.py
```

删除：

```python
max(delta, 0)
```

保留真实 signed delta。

---

## P0-6 — Metric Semantics Registry

**文件**

```text
statebus/benchmark/metric_aggregation.py
```

从：

```text
special-case finalizer
```

升级：

```text
typed metric registry。
```

---

## P0-7 — 修 numeric_tolerance

**文件**

```text
statebus/benchmark/scoring.py
statebus/runtime/smoke.py
```

明确：

```text
expected
abs_tol
rel_tol。
```

---

## P0-8 — External Summary Hint 清理

**文件**

```text
statebus/benchmark/external_text_baseline.py
statebus/benchmark/formal_registry_adapter.py
statebus/benchmark/samples/formal_financial_family/*
```

禁止：

```text
answer-bearing summary_hint
```

进入 role prompt。

---

## P0-9 — 实现真正 NL-MAS baseline

**文件**

建议新建：

```text
statebus/benchmark/external_nl_mas.py
```

不要在现有 `external_text_baseline.py` 上继续 patch 到看不懂。

---

## P0-10 — FairnessManifest v2

**文件**

```text
statebus/benchmark/contest_fairness.py
```

加入：

```text
consumer digest
fallback digest
route-hint digest
history context digest
cache policy
visibility provenance edges
```

---

## P0-11 — Comparator AB/BA

**文件**

```text
statebus/benchmark/comparator_runner.py
```

新增：

```text
pair_id
run_order
AB/BA
paired_delta
paired CI
```

---

## P0-12 — Explicit History Modes

**文件**

```text
statebus/benchmark/continuous_runner.py
statebus/runtime/smoke.py
```

显式：

```text
NO_HISTORY
HISTORY_TEXT_ASSIST
MEMORY_ASSIST
VALIDATED_REPLAY
EXACT_REPLAY
```

不要再靠：

```text
replay_enabled bool
```

表达所有 history semantics。

---

# 117. P1 源码优化

---

## P1-1 — RoleSemanticOutput / RuntimeAuditEnvelope

减少：

```text
LLM completion audit tax。
```

---

## P1-2 — Route-hint-free Raw Planner Suite

默认正式 Generalization：

```text
STATEBUS_ROUTE_HINTS_ENABLED=0
```

Contract conformance suite 可单独开。

---

## P1-3 — Evaluator Process Isolation

正式 run：

```text
runtime process
无 gold mount

evaluator process
只读 outputs + gold
```

---

## P1-4 — Consumer Symmetry Gate

Internal A/B：

```text
producer digest
consumer digest
fallback digest
```

不一致：

```text
causal claim invalid。
```

---

# 118. P2

```text
BFCL
LongMemEval-V2
SILO-BENCH small-scale communication audit
τ³
```

这些不是当前 benchmark truth 修复的前置条件。

---

# 119. 推荐重跑顺序

不要一次重跑 Full Matrix。

---

## R0 — Static Benchmark Contract Audit

必须全部绿：

```text
no answer-bearing role hint
no expected metric in task quality
no signed delta clamp
metric semantics registered
fairness v2 manifest generated
```

---

## R1 — Control Codec

无 LLM。

先把：

```text
“Structured communication”
```

这个最基本 claim 重新钉死。

---

## R2 — NL-MAS External Baseline Preflight

5 cases：

```text
prompt/output inspect
contamination inspect
```

确认：

```text
真的没有 machine-authoritative A2A structured packet。
```

---

## R3 — Semantic Factorial

```text
S0
S1
S2
```

至少两类：

```text
long evidence
short evidence
```

找到 crossover。

---

## R4 — Memory Paired Counterfactual

两条 10-round chain。

只对：

```text
actual useful target
```

做 same-task cold/warm。

---

## R5 — Full Contest Compare

```text
NL-MAS
vs
StateBus
```

AB/BA。

---

## R6 — APC / KV

Prefix 保持现设计。

KV latency 改 AB/BA。

---

# 120. 每个正式 Pair 的 Exit Gate

```text
Task parity
PASS

Public source parity
PASS

Tool semantics parity
PASS

Model/revision parity
PASS

Compute budget parity
PASS

Gold isolation
PASS

Consumer symmetry
PASS (mechanism A/B only)

Treatment axis
exactly declared

Fresh execution
PASS

Metric semantics
PASS

Quality result
reported independently

Mechanism activation
reported independently

Performance
reported whether positive or negative
```

---

# 121. 最终赛题结果表应该长什么样

不要一张表混所有机制。

---

## Table A — Communication

```text
Codec
Prompt representation
System wire
```

分别列。

---

## Table B — Non-Text State

```text
Selection
Carrier
Physical transfer
Behavior effect
```

分别列。

---

## Table C — Memory

```text
candidate
compatible
actual use
assist
validated replay
exact replay
work skipped
```

---

## Table D — Full System

```text
NL-MAS
vs
Full StateBus

quality
tokens
wall
communication
```

只做 system-level conclusion。

---

# 122. 最终项目故事应该怎么讲

可以非常专业地说：

> 我们最初把 structured protocol、prompt compression、semantic state 和 memory reuse 放在同一条 benchmark ladder 中，因此一些收益归因并不干净。沿着历史实验和源码回溯后发现：typed control 最稳定的收益是控制面/线路字节；模型 Token 的主要下降来自 evidence selection，而不是 Protobuf；StateRef 的核心价值是非文本状态的可验证跨进程消费，而不是保证每个小 payload 都更快；Memory Assist 也不必然减少成本，只有 validated/exact replay 真正跳过计算。最终我们将 benchmark 重构为 mechanism-level causal suite 与 external NL-MAS system comparator 两层，并让 quality、mechanism activation 和 performance 独立记账。

这比：

```text
“所有机制都有 30% 提升”
```

更可信，也更像真正做过系统实验的人。

---

# 123. 最终回答：我们的问题到底在哪

不是一个点。

优先级排序：

## P0：Benchmark Object 定义

最严重。

```text
L0/L1/L2 treatment 太厚
```

---

## P0：Metric Semantics

同样严重。

```text
control_bytes apples-to-oranges
signed delta clamp
quality/effect coupling
```

---

## P0：Pure Text Baseline

当前 internal 和 external 都不是我们最终希望提交的：

```text
NL-MAS。
```

---

## P1：Task Pre-structuring

```text
CanonicalTaskSpec
route hint
candidate surface
```

适合 contract execution，

不适合证明 planner autonomy。

---

## P1：Runtime Thickness

确实存在。

但解决方法不是删掉 Runtime，

而是：

```text
Production Runtime
+
Thin Mechanism Harness
```

并存。

---

## P1：Completion Overhead

进一步把：

```text
Runtime-known audit data
```

从：

```text
LLM output
```

移出去。

---

# 124. Source Truth Map — Current `qcrs/os`

| 问题 | 文件 / 函数 |
|---|---|
| L0/L1/L2/L3 开关 | `statebus/benchmark/fixed_answer_runner.py` |
| Text vs structured Role prompt | `statebus/runtime/role_path.py` |
| control_bytes 定义 | `statebus/runtime/driver.py::_exchange_control_messages()` |
| Text/Protobuf worker | `statebus/control/subprocess_worker.py` |
| Current runtime ordering | `statebus/runtime/smoke.py` |
| Semantic T2 diagnostic | `statebus/benchmark/continuous_runner.py` |
| history roots across layers | `statebus/benchmark/continuous_runner.py` |
| expected metric effect quality coupling | `statebus/benchmark/continuous_runner.py::_apply_case_metric_contracts()` |
| signed delta clamp | `statebus/benchmark/fixed_answer_runner.py::run_fixed_answer_suite()` |
| External baseline prompts | `statebus/benchmark/external_text_baseline.py` |
| External deterministic tools | `statebus/benchmark/external_public_tools.py` |
| Formal route projection | `statebus/benchmark/formal_registry_adapter.py` |
| route/tool candidate construction | `statebus/route_tool_catalog.py` |
| Gold visibility | `statebus/benchmark/contest_fairness.py` |
| numeric tolerance | `statebus/benchmark/scoring.py` |
| rate aggregation | `statebus/benchmark/metric_aggregation.py` |
| External comparator timing order | `statebus/benchmark/comparator_runner.py` |
| Current published results | `docs/experiments/README.md` |

---

# 125. Source Truth Map — `qcrs/os1`

重点历史文件：

```text
docs/progress/optimization_journal.md

docs/archive/legacy_202606_host_mainline/progress/
  benchmark_fairness_audit_20260608.md

docs/archive/legacy_202606_host_mainline/analysis/
  state_transfer_benchmark_audit_20260611.md
  experimental_anomalies_20260615.md
  statebus_deep_data_analysis_20260616.md
  statebus_deep_critical_B_benchmark_task_text_audit_20260618.md
  statebus_external_pure_text_baseline_contract_20260620.md

docs/improvement/20_v2_comprehensive_truth_audit_20260706/
  15_deep_problem_analysis_20260708.md
  46_full_qwen3_extended_matrix_audit_20260714.md
  47_failure_root_cause_and_optimization_plan_20260714.md
```

这些历史材料最有价值的不是旧数字，而是它们已经记录：

```text
benchmark 设计怎么一步一步出错
以及为什么要重新收紧 claim。
```

---

# 126. External Evaluation Design References

## BenchAgent — 2026

`Do More Agents Help? Controlled and Protocol-Aligned Evaluation of LLM Agent Workflows`

核心可借：

```text
Substrate-Internal (SI)
Protocol-Aligned External (PAE)

same benchmark loader
same tool access
same answer contract
same usage accounting
same trajectory logging
```

---

## Nature Machine Intelligence — 2026

`Capable language models can outgrow the benefits of collaboration`

核心可借：

```text
identical task prompts
identical tool interfaces
matched per-system compute ceiling
realized communication overhead
```

---

## SILO-BENCH — ACL 2026

核心提醒：

```text
Success Rate
Token Consumption
Communication Density
```

必须一起看。

因为：

```text
Communication happened
≠
Communication helped.
```

---

# 127. Final Freeze for Batch 08-R

本轮建议冻结以下设计决策：

1. **Internal L0 不再叫赛题 Pure Text baseline。**
2. **新增真正 `External NL-MAS`。**
3. **TextStruct 与 NL-MAS 分开。**
4. **L0→L1 不再直接等同 Protobuf codec。**
5. **当前 `control_bytes -83%` headline 暂停，等同 measurement-point 重跑。**
6. **当前 `wire -69%` 只能叫 inline-text vs reference-based typed handoff。**
7. **L1→L2 Token gain 拆成 Selection 与 Carrier。**
8. **T2 diagnostic 升格为 formal factorial lane。**
9. **Continuous 的 history assist 与 memory replay 显式拆层。**
10. **expected_metric_effects 不再进入 task quality。**
11. **所有 signed delta 不允许 clamp。**
12. **所有 non-additive metric 必须由 MetricSemanticsRegistry 聚合。**
13. **External answer-bearing summary_hint 移除并重跑。**
14. **Route hint benchmark 只保留 contract-conformance；另建 raw planner benchmark。**
15. **External / KV latency 全部 AB/BA paired。**
16. **Memory headline 必须 same-target cold/warm。**
17. **Full-system result 只做 combined-stack observation，不做组件归因。**
18. **Production Runtime 与 thin Mechanism Harness 并存。**

---

# 128. 一句话结论

> **当前 StateBus 不是“机制没有收益”，而是实验层仍把若干不同机制放在了同一个 treatment 中，同时部分 metric 的 measurement point 和 gate semantics 还没有完全对齐。`os1` 的历史已经证明：Protobuf 的稳定收益主要在 wire/control；大 Token 收益来自 prompt representation 与 semantic evidence selection；Memory Assist 不必然降低成本，Replay 才真正减少 work。当前 `os/master` 已修复很多历史问题，但仍需要重新定义 NL-MAS、拆 L1→L2 selection/carrier、修 `control_bytes`、删除 signed-delta clamp、拆 quality/activation/performance、以及把 continuous history assist 显式建模。只有完成这些后，赛题 A/B 才能同时做到“公平、可解释、能归因”。**
---

# 129. Batch 08 Benchmark-Rebuild Implementation DAG

这一阶段不再增加机制，只修 Benchmark Contract，并把现有机制放到它真正适合的工作负载上。

总体顺序：

```text
P0 Benchmark Truth Fix
        ↓
A. Mechanism-Level Fair A/B
        ↓
B. External NL-MAS System Compare
        ↓
C. APC / KV / Memory 专项重跑
        ↓
Final Headline Reconciliation
```

目标不是“让所有实验都变成正收益”，而是：

```text
机制有效时能够稳定表现出优势；
机制不适合时 Runtime 能自动 bypass；
最终系统平均结果因此优于固定全开。
```

---

# 130. P0：先修实验基础，不先调模型

只做以下几项。

| 修改点 | 主要文件 | 修改目的 |
|---|---|---|
| 修正 `control_bytes` | `runtime/driver.py::_exchange_control_messages()` | Text / Structured 使用同一 measurement point |
| 删除负向 delta clamp | `benchmark/fixed_answer_runner.py` | regression 必须真实保留 |
| Quality / Activation / Performance 分离 | `benchmark/continuous_runner.py` | “机制没触发”不能等同“任务答错” |
| 修 `numeric_tolerance` | `benchmark/scoring.py` | 真正比较 expected value ± tolerance |
| 清理 External `summary_hint` | `benchmark/external_text_baseline.py` | Gold 不进入 Agent-visible surface |
| Metric typed aggregation | `benchmark/metric_aggregation.py` | counter/rate/sample 不再混加 |
| Comparator AB/BA | `benchmark/comparator_runner.py` | 消除固定执行顺序偏差 |

这一步完成后，旧 headline 先冻结：

```text
control_bytes -83%
external pure-text superiority
L1→L2 Token gain = StateRef gain
KV wall/TTFT superiority
```

原始数据不删除，只降级成 historical / diagnostic evidence。

---

# 131. 实验一：Structured Communication 应该怎么公平测

这里拆成两个实验，避免再混。

## 131.1 Codec A/B

固定同一个逻辑控制对象：

```text
task / step / attempt
capability
input refs
output contract
deadline
```

只改变：

```text
UTF-8 TextStruct
vs
Protobuf
```

两边都真实走 UDS。

测：

```text
request_wire_bytes
response_wire_bytes
encode/decode_us
parse/validation_us
```

### 如何体现机制优势

不要塞 corpus。

直接做 payload-size sweep：

```text
Small metadata
Medium metadata
Large ref list / capability list
```

如果 Protobuf 有优势，它应该自然出现在：

```text
wire size
parse stability
schema validation
```

而不是依赖 baseline 携带更多 evidence。

---

## 131.2 Inline Handoff vs Ref Handoff

这是 StateBus 更值得展示的通信优势。

两边传递**完全相同的信息内容**：

```text
Text:
inline selected evidence

StateBus:
Ref + out-of-band evidence/state
```

按 evidence size：

```text
1 KB
8 KB
32 KB
128 KB
```

分桶。

测：

```text
control wire
data-plane bytes
total physical bytes
serialization cost
consumer reconstruction cost
```

这里 StateBus 的优势应随着 payload 增大而明显。

因此最终 claim 可以是：

> 对大中间状态，StateBus 将 O(payload) 的 Agent control handoff 转为近似 O(metadata) 的 reference control，同时由独立 data plane 管理真实 payload。

这比“Protobuf 压缩 83%”更准确，也更强。

---

# 132. 实验二：Semantic State 不再用一个 L1→L2 解释全部收益

正式变成：

```text
S0  Full Evidence + Text
S1  Selected Evidence + Text
S2  Same Selected Evidence + StateRef
```

## S0 → S1

只回答：

```text
Semantic Selection 有没有减少模型上下文？
```

测：

```text
raw evidence
prompt tokens
quality
retrieval recall
```

## S1 → S2

只回答：

```text
非文本 StateRef 是否比重复文本序列化更适合作为中间状态 carrier？
```

测：

```text
handoff bytes
materialize / resolve ms
cross-PID consumption
state bytes
information fidelity
```

### 如何让优势自然体现

使用三类输入：

```text
Short evidence
Medium evidence
Long evidence
```

不要只报总体均值。

StateBus 应允许：

```text
payload < threshold
→ inline text

payload >= threshold
→ StateRef
```

也就是加入一个真正的：

```text
StatePlacementPolicy
```

这样小状态不为机制付额外开销，大状态才走 StateBus。

最终展示的不是：

> StateRef 永远更快。

而是：

> StateBus 可以根据 payload crossover 自动选择 inline 或 state plane，因此整体成本不劣于最优静态路径，并在大状态场景明显占优。

这个故事更合理。

---

# 133. 实验三：Memory 重点展示 Replay，不强迫 Assist 必须加速

Memory 拆成：

```text
H0  No History
H1  History Text Assist
M1  Indexed Memory Assist
M2  Validated Replay
M3  Exact Replay
```

正式性能 headline 重点看：

```text
M2 / M3
```

因为它们真正能够：

```text
skip step
skip LLM call
skip execution
```

`M1 Assist` 主要看：

```text
quality
consistency
candidate→compatible→consume→effect
```

不要求 latency 必须下降。

---

# 134. Memory 的公平 A/B

对同一个 target task：

```text
VerifiedHistorySnapshot
        ├─ Cold: memory consumption disabled
        └─ Warm: memory/replay enabled
```

必须固定：

```text
same target
same source
same history snapshot
same model
same tool
same output contract
```

再做：

```text
AB / BA
```

---

# 135. 如何让 Memory 真正体现优势

不是降低 baseline，而是增加 Runtime 的收益判断：

```text
ReuseAdmissionPolicy
```

只有满足：

```text
compatibility = PASS
expected_saved_work > lookup + validation overhead
```

才允许 replay。

例如：

```text
只能省一个很短的 prompt
→ recompute

能省 Executor + Summarizer / CodeAct
→ replay
```

因此最终比较：

```text
Always Recompute
vs
Adaptive Reuse Policy
```

这会比：

```text
Memory Always On
```

更容易得到稳定正收益，而且是合理系统设计。

---

# 136. 实验四：Planner / Routing 不再混用 Contract 与 Generalization

保留两条。

## Contract Lane

```text
CanonicalTaskSpec
+ bounded capability surface
```

测：

```text
contract conformance
route/tool execution fidelity
```

可以保留 route hint。

## Raw Lane

只给：

```text
raw user request
public capability descriptions
public sources
```

关闭：

```text
route hints
precompiled correct route authority
```

测：

```text
task interpretation
capability selection
plan correctness
```

这样当前 Runtime 的 TaskCompiler / PlanPolicy 价值才能真实展示，而不是让 reviewer 怀疑答案已经写在 `intent_op` 中。

---

# 137. 实验五：真正的 Pure-Text Comparator

新增：

```text
External NL-MAS
```

角色仍然：

```text
Planner
Retriever
Executor
Summarizer
```

两边保持：

```text
same task
same source
same tools
same model
same logical role graph
same final evaluator
same compute ceiling
```

Pure Text Agent 之间只传：

```text
concise natural-language handoff
```

允许：

```text
numbers
source IDs
short bullets
```

不允许：

```text
candidate_key
machine-authoritative JSON packet
StateRef
MemoryRef
hidden state
```

注意：

> Pure Text baseline 也必须允许“简洁表达”，不能故意让它全文复述 corpus。

---

# 138. Full System Compare 应该如何设置

最终赛题主结果：

```text
External NL-MAS
vs
Full StateBus
```

使用三类 workload：

```text
1. Short / low reuse
2. Medium / moderate reuse
3. Long-context / repeated-state
```

分别报告。

这样可以直接展示：

```text
Short:
StateBus 可能接近 baseline

Medium:
开始出现收益

Long / repeated:
StateBus 明显优于 baseline
```

这反而比只挑长任务更可信。

---

# 139. “展示机制优越性”最重要的修改：不要所有机制固定全开

StateBus 应该有统一 Runtime Policy：

```text
if state small:
    inline

if state large:
    StateRef

if no useful semantic pruning:
    full evidence

if memory expected saving small:
    recompute

if compatible replay can skip expensive work:
    replay

if exact prefix too short:
    no APC

if exact prefix long enough:
    APC

if explicit continuation store/load overhead > recompute:
    recompute
```

最终系统优势来自：

# **Adaptive Mechanism Selection**

而不是：

# **Every Mechanism Always On**

这和我们前面 Batch 05 / 06 的设计是一致的：

```text
ExecutionBindingPolicy
StatePlacementPolicy
InferenceReusePolicy
```

都应该根据运行时成本和能力做选择。

---

# 140. APC / Explicit KV 如何展示得更公平

## APC

保留当前 exact-prefix 思路。

工作负载：

```text
相同长 evidence prefix
不同 role / task suffix
```

同时增加：

```text
short-prefix negative bucket
```

让 Runtime 在 prefix 太短时不强制 APC。

主指标：

```text
task-local hit/query
computed prefill
TTFT
```

---

## Explicit KV

使用：

```text
same parent token IDs
same suffix contract
APC off
```

但顺序改：

```text
AB
BA
AB
BA
```

并同时报告：

```text
store
load
computed prefill
TTFT
full chain wall
```

最重要的是增加：

```text
parent length sweep
```

例如：

```text
512
2K
4K
8K
```

这样能直接找到：

```text
store/load overhead
vs
recompute saved cost
```

的 break-even。

显式 KV 的优势就会从“某个 4K case 正好快”变成：

> 当 parent 超过某个长度后 continuation 稳定优于 recompute。

这更像 AI Infra 项目结果。

---

# 141. 第一轮最小重跑顺序

不需要立刻重新跑所有 45+ case。

先跑：

```text
R0
Static fairness / metric unit tests

R1
Codec microbenchmark
20 repeats × 3 payload buckets

R2
Semantic S0/S1/S2
各选 3 个代表任务

R3
Memory
2 个 same-target cold/warm pair

R4
External NL-MAS vs StateBus
5 个代表 case，AB/BA

R5
Explicit KV
3 个 parent lengths，AB/BA
```

如果这些结果方向合理，再扩到完整 formal suite。

---

# 142. 第一轮成功标准

不是预先规定：

```text
必须提升 30%
```

而是：

| 机制 | 第一轮必须证明什么 |
|---|---|
| Protobuf | 同 semantic object 下真实 wire/parse 优势 |
| Ref Handoff | payload 越大，control plane 越不随 payload 增长 |
| Semantic Selection | 长 evidence 下显著降低模型可见上下文且质量不降 |
| StateRef | 同 selection 下真实跨 PID 非文本消费，存在明确 break-even |
| Memory | replay 真正减少 step / LLM / execution work |
| NL-MAS Compare | 相同公开信息和资源下 StateBus 的 quality-cost frontier 更好 |
| APC | exact long prefix 下减少 computed prefill / TTFT |
| Explicit KV | parent 足够长时 inherited compute 收益覆盖 store/load |

---

# 143. 最终 headline 的选择规则

只有满足：

```text
Fairness PASS
Task Quality PASS
Mechanism Activation PASS
Fresh Execution PASS
Metric Semantics PASS
```

才进入 headline。

然后：

```text
无论正负
都保留 signed result。
```

机制如果只在某个 workload bucket 有优势：

```text
报告适用区间和 break-even。
```

不要把负 bucket 删除。

---

# 144. Batch 08 接下来真正进入实现的 P0 DAG

```text
B08-P0-1
Metric truth fix
driver.py / metric_aggregation.py / scoring.py

        ↓

B08-P0-2
Fairness truth fix
summary_hint / route-hint metadata / signed delta / AB-BA

        ↓

B08-P0-3
Formal semantic factorial
S0 / S1 / S2

        ↓

B08-P0-4
External NL-MAS v1

        ↓

B08-P0-5
Memory same-target pair harness

        ↓

B08-P0-6
Small representative rerun

        ↓

B08-P0-7
Review results
决定哪些机制进入 full formal rerun
```

这里先不要：

```text
增加新数据集
接 BFCL
接 LongMemEval
继续扩 KV feature
继续扩 Scheduler feature
```

先把现有机制的因果证据做干净。

---

# 145. Batch 08 Rebuild Freeze

从这里开始，Benchmark 重构遵循四条规则：

1. **一个实验只有一个主要 treatment。**
2. **Pure Text baseline 不故意做弱，但也不给 StateBus 专属结构信息。**
3. **机制不是固定全开，而是由 Runtime 在适用区间启用。**
4. **最终展示优势优先使用 workload crossover / break-even，而不是挑最好看的单点。**

最终我们希望得到的不是：

```text
StateBus 每个机制都比 baseline 快。
```

而是：

```text
StateBus 能识别什么时候应该 text、什么时候应该 StateRef、
什么时候应该 recompute、什么时候应该 replay、
什么时候应该 APC / continuation。

因此在异构多 Agent workload 上，
它能够稳定接近每种静态策略的最优点，
并在大状态、长上下文、重复计算和连续任务场景中形成明确优势。
```

这才是目前这个项目最值得做出的系统结论。
