# StateBus Benchmark Boundary、External Evaluation 与 Dataset Generalization 深度设计 v2

> 项目：`qcrs/os`（当前主展示仓库，`master`）  
> 历史参考：`qcrs/os1`  
> 日期：2026-09-02  
> 文档版本：v2  
> 定位：Controlled Evaluation 保持兼容 + External Native Benchmark Selection + Minimal Integration + Contract Refactor Trigger Baseline  
> 本版核心修订：**不再以“先泛化所有 contract、再接 benchmark”为实施顺序；先冻结现有内部测试，再选择高认可且与 StateBus 有真实增益空间的公开 benchmark，以原生接口最小接入，根据真实 blocker 再抽象公共 contract。**

---

# 0. 本版结论先行

这份文档对上一版最重要的修正有六点。

第一，**当前 StateBus 已有内部任务、45-case controlled suite、E5 formal 25 cases 以及 Embedding / Memory / Logit / CodeAct / Prefix / KV 专项实验默认全部冻结，不因外部 benchmark 接入而改格式、改语义或改 evaluator。**

第二，重新审计 `qcrs/os:master` 后，当前没有发现“Gold answer 直接喂给 Agent”这类严重 benchmark correctness bug。当前主要问题是：

```text
Controlled formal input / adapter
具有较强 benchmark-specific semantic scaffolding
```

它影响的是：

```text
external validity / generality claim
```

而不是：

```text
现有 controlled A/B 是否无效
Runtime 是否存在严重 correctness bug
```

第三，当前 `adaptive_formal` 本质应该正式定位为：

```text
Controlled Formal Evaluation Lane
```

它允许：

```text
fixed CanonicalTaskSpec
operation semantics
input normalization
deterministic reference recomputation
fixed role topology
```

因为它的职责就是机制与受控执行验证。**不应为了外部 benchmark 把这条链改坏。**

第四，External benchmark 的第一目标不是“设计一套万能 `ExternalTaskEnvelope`”，而是：

```text
使用 benchmark 原生 harness / evaluator
+
写最薄 StateBus adapter
+
尽量不修改 StateBus core
```

只有接入至少两个真实 benchmark 后出现重复 blocker，才把重复机制抽成：

```text
InputAssetRef
ExternalTaskEnvelope
TaskContractIdentity
BenchmarkVisibilityAudit
```

第五，外部 benchmark 选择重新排序。上一版把 TeamBench / IDA-Bench 权重放得过高，主要考虑“研究问题贴合度”，但忽略了社区认可度与简历可信度。2026-09-02 当前应优先：

```text
P0  BFCL V4
P0/P1 τ³-bench
P1  AgentBench FC（OS / DB）
P2  AppWorld
P3  SWE-bench / Terminal-Bench / MLE-bench
```

专项补充：

```text
LongMemEval-V2
TeamBench
IDA-Bench
```

第六，**公开 benchmark 的目标不是保证 StateBus 所有 task 都赢。**

真正应该验证的是：

```text
Direct Baseline
vs
Fixed StateBus
vs
Adaptive StateBus
```

理想现象是：

```text
简单 task:
Adaptive bypass StateBus 重路径
≈ Direct baseline

复杂 / missing / stateful task:
Adaptive 启用 StateBus 机制
> Direct baseline

因此：
Adaptive 比 Fixed 更接近 quality-cost frontier
```

这才和前面的 Routing 架构形成闭环。

---

# 1. 先冻结一个最重要的工程约束：旧测试不能被 External Evaluation 破坏

现有 StateBus README 已经报告：

```text
正式任务：
20 个连续任务
+
五类 25 个独立 case

专项：
Embedding
Logit
Memory
Prefix
Explicit KV
```

现有主要 evidence：

```text
Full StateBus:
Token 33,974 -> 17,870
wire 36,069 -> 12,677 B

Embedding:
raw evidence -84.04%
Token -49.16%

Logit Gate:
Validator 8/12 -> 12/12

Memory:
paired latency -18.49%
Token -23.75%

CodeAct:
14/25 -> 25/25

Explicit KV:
computed prefill -85.22%
TTFT -61.62%

Prefix:
block hit 0 -> 78.02%
TTFT -68.7%
```

这些实验已经承担非常明确的机制验证职责。

因此 External integration 的第一 compatibility rule 是：

```text
DO NOT:
修改 internal case 的输入格式
修改 expected_facts
修改现有 CanonicalTaskSpec
修改 formal operation_semantics
修改 reference validator
修改现有 L0/L1/L2/L3 分母
修改 Prefix/KV 专项任务
```

外部 benchmark 是新增 lane，不是替代旧 lane。

---

# 2. 推荐最终 Evaluation Topology

目标应该是三条而不是一条：

```text
                         StateBus
                            │
          ┌─────────────────┼──────────────────┐
          │                 │                  │
          ▼                 ▼                  ▼
 Controlled Mechanism   Controlled Formal    External Native
 Evaluation             Evaluation           Evaluation
          │                 │                  │
          ▼                 ▼                  ▼
 L0/L1/L2/L3          E5 25 cases       BFCL / τ³ / AgentBench
 Embedding            DSL/CodeAct       AppWorld / ...
 Memory               deterministic
 Logit                validation
 Prefix/KV
```

其中：

## 2.1 Controlled Mechanism Lane

回答：

```text
机制真的工作吗？
减少了多少 token / bytes / prefill？
状态真的跨 PID 被消费了吗？
```

## 2.2 Controlled Formal Lane

回答：

```text
registered task contract 下
DSL / CodeAct / Planner / Validator
能否稳定完成已定义任务？
```

## 2.3 External Native Lane

回答：

```text
面对没有为 StateBus 预编译 intent/tool/operation 的真实公开 task，
Runtime 能否自己选择 workflow/capability/provider，
并在 benchmark 原生 evaluator 下保持或提升质量？
```

三者不能互相替代。

---

# 3. 当前源码问题重新定性：不是严重 bug，而是入口边界过于 controlled

当前 `os/master` 的主要主链已经是：

```text
CanonicalTaskSpec
  ↓
PlanProposal
  ↓
PlanPolicy
  ↓
ApprovedPlan
  ↓
CapabilityGrant
  ↓
Dispatcher
```

generic adaptive pack 也已经收敛到：

```text
retrieve_semantic_evidence_v1
retrieve_table_evidence_v1
execute_analysis_dsl_v2
execute_bounded_python_v2
compose_claim_set_v2
compose_risk_memo_v1
```

所以：

> “Runtime 里仍然一个 benchmark operation 对应一个 capability”

已经不是当前主事实。

真正 closed-world 的位置主要是：

```text
MinimalBenchmarkSample
    ↓
CanonicalTaskSpec
    ↓
adapt_formal_sample()
    ↓
FormalAdaptiveCase
```

这里仍然根据：

```text
task_family
intent_op
arguments
```

构造：

```text
operation
source schema
output schema
operation semantics
expected output shape
```

这意味着：

```text
当前 E5 =
Generic Runtime
+
Controlled Formal Semantic Adapter
```

而不是：

```text
Generic Runtime
+
Unknown External Task
```

这是 evaluation-boundary 问题，不是核心 Runtime correctness bug。

---

# 4. Gold Leakage 与 Semantic Scaffolding 必须继续分开

## 4.1 没有发现直接 Gold Leakage

当前 `expected_facts`：

```json
{
  "trend_direction": "increasing"
}
```

在现有 formal lane 中是 post-runtime evaluator Gold。

当前代码和运行记录明确隔离：

```text
benchmark_oracle_visible_to_roles = False
```

因此目前不能说：

```text
25/25 是因为直接把答案给 Agent。
```

## 4.2 但是有 Semantic Scaffolding

例如 Adapter 会根据 intent 自动生成：

```text
compute_trend
detect_outliers
groupby_aggregate
```

以及精确 operation semantics。

这会降低：

```text
task interpretation
algorithm selection
workflow selection
```

难度。

所以准确说法是：

```text
没有 direct answer leakage

但 Controlled Formal Adapter
提前承担了一部分 task formalization
```

这对 controlled task 没问题，但 external benchmark 不应该这么接。

---

# 5. 为什么现有 45 tasks / E5 不应该动

因为现有测试的科学问题是：

```text
A/B attribution
```

例如：

```text
Text vs Typed
Embedding off vs on
Memory cold vs warm
Prefix off vs on
KV off vs continuation
```

要测这类问题，本来就应该固定：

```text
task
input
oracle
model
temperature
quality floor
```

如果为了“更 generic”把 task interpretation 也变成随机 Agent 行为，

反而会增加实验噪声。

因此：

```text
Internal Controlled Suite:
特化 = 可接受，甚至必要

External Benchmark:
特化 solution semantics = 不可接受
```

两者职责不同。

---

# 6. External Adapter 到底能不能 benchmark-specific

答案：

# 可以，而且必须。

任何 benchmark 都有自己的 protocol。

例如：

```text
BFCL:
question + function schema + multi-turn execution state

τ³:
user message + tools + domain policy + environment state

AgentBench:
history + interactive OS/DB environment

SWE-bench:
repo + issue + base commit + Docker evaluator

AppWorld:
instruction + app world + APIs + persistent state
```

因此一定会存在：

```text
BFCLStateBusAdapter
TauStateBusAgent
AgentBenchStateBusAgent
...
```

这叫：

```text
Protocol Adaptation
```

完全合理。

---

# 7. 真正不能做的是 Solution Adaptation

错误：

```text
External task
  ↓
Adapter 看 task
  ↓
判断：
这是 anomaly detection
  ↓
intent_op=detect_outliers
  ↓
required_tool=CodeAct
  ↓
Runtime
```

这实际上已经替 Router 做了决定。

正确：

```text
External task
  ↓
Thin Adapter
  ↓
只提供：
- benchmark 原生公开 instruction
- benchmark 原生公开 tools
- benchmark 原生公开 environment state
- benchmark 原生公开 policy
  ↓
StateBus
  ↓
自己决定：
Plan
Role
Capability
Provider
```

所以 external adapter 可以知道 benchmark API 长什么样，

但不能知道：

```text
这道题应该怎么解。
```

---

# 8. 本版 External Integration 原则：Native Harness First

上一版建议先实现：

```text
InputAssetRef
ExternalTaskEnvelope
TaskContractIdentity
BenchmarkVisibilityAudit
```

再接 benchmark。

现在调整为：

```text
Benchmark Native Harness
      ↓
Thin StateBus Integration
      ↓
遇到真实 core blocker
      ↓
最小 core change
      ↓
第二个 benchmark
      ↓
如果出现重复抽象
再形成通用 contract
```

理由：

1. 防止过度设计；
2. 不破坏现有 controlled lane；
3. benchmark 会告诉我们真正需要什么抽象；
4. 更容易证明“StateBus 没有为 benchmark 特制 Runtime”。

---

# 9. Benchmark 选择标准

本项目不是纯论文 benchmark exploration，而是：

```text
比赛项目
+
简历项目
+
系统设计证明
```

因此 benchmark 不能只看“和我们最贴”。

建议使用五个维度：

| 维度 | 说明 |
|---|---|
| Recognition | 社区 Star、论文/会议、公开 leaderboard、行业采用 |
| Relevance | 是否真实测 StateBus 已有机制 |
| Native Evaluation Quality | evaluator 是否可复现、是否 outcome based、是否有 hidden/private boundary |
| Integration Cost | 当前 StateBus 是否可以较小改动接入 |
| Improvement Headroom | 当前同模型是否还有明显失败空间，StateBus 是否有结构性机会改善 |

特别注意：

> GitHub Star 不是唯一标准，但对于简历项目确实是有价值的 public-recognition signal。

---

# 10. 2026-09-02 当前候选 Benchmark 认可度快照

以下 Star 为 2026-09-02 GitHub API 快照，后续会变化。

| Benchmark / Repo | Star 约数 | 额外认可信号 |
|---|---:|---|
| BFCL / Gorilla | 13,014 | Berkeley 长期 leaderboard、V1-V4 持续更新 |
| SWE-bench | 5,765 | ICLR 2024 Oral、OpenAI Verified、广泛 agent benchmark |
| AgentBench | 3,711 | ICLR 2024、8 environment、2025 FC update |
| τ³ / tau2-bench | 1,933 | Sierra、持续 leaderboard、2024→2026 连续演化 |
| MLE-bench | 1,729 | OpenAI、75 Kaggle competitions |
| WebArena | ~1.6k | 经典 Web Agent benchmark |
| Terminal-Bench（Harbor 当前仓库） | 595 | frontier terminal-agent benchmark |
| AppWorld | 502 | ACL 2024 Best Resource Paper、457 APIs |
| LongMemEval-V2 | 148 | 2026 memory 专项 |
| IDA-Bench | 11 | 新、数据分析专项 |
| TeamBench | 8 | 新、role-separated MAS 专项 |

因此上一版将 TeamBench/IDA 作为 headline external benchmark 不够合适。

---

# 11. 新的 Benchmark Priority

推荐：

```text
P0:
BFCL V4

P0 / P1:
τ³-bench

P1:
AgentBench FC -- OS / DB

P2:
AppWorld

P3:
SWE-bench
Terminal-Bench
MLE-bench
```

专项：

```text
LongMemEval-V2
TeamBench
IDA-Bench
```

---

# 12. 为什么 BFCL V4 现在是第一优先

BFCL 当前不是简单 function-call benchmark。

V4 full score 已覆盖：

```text
Agentic
  - Web Search 200
  - Memory 465

Multi-Turn 800
  - Base 200
  - Missing Function 200
  - Missing Parameter 200
  - Long Context 200

Non-Live
Live
Hallucination / Irrelevance
Parallel / Multiple
Format Sensitivity
```

官方整体 scoring entries 超过 5k。

其 handler 还原生记录：

```text
input token count
output token count
latency
inference log
state log
```

非常适合 StateBus。

---

# 13. BFCL 与当前 Qwen3-32B 还有真实 headroom

BFCL 当前公开 leaderboard 中：

```text
Qwen3-32B (FC)
Overall ≈ 48.71
```

这非常重要。

说明：

```text
不是一个 baseline 已经 95% 的 benchmark。
```

存在很大提升空间。

但仍然不能因此承诺：

```text
StateBus 一定把 48.71 提升到更高。
```

真正要判断的是：

```text
Qwen3-32B 的错误类别
是否恰好能被 StateBus 的机制修复。
```

---

# 14. BFCL 子类别与 StateBus 机制逐项映射

## 14.1 Simple Python

Benchmark：

```text
清晰 query
清晰 function schema
单次调用
```

StateBus 增益预期：

```text
低
```

甚至可能：

```text
更慢
更多 token
```

因此正确策略不是让完整 multi-agent StateBus 强行介入。

应该：

```text
PlanSelector
→ direct tool-call path
```

Simple category 是：

# Router bypass 的 negative control。

---

# 15. BFCL Irrelevance

任务：

```text
给出的 function 全部不应该调用
```

直接 FC model 常见问题：

```text
hallucinated tool call
wrong tool call
```

StateBus 可用机制：

```text
Capability feasibility
PlanPolicy
no-eligible-provider
Decision Logit Gate
fallback / ask / no-call
```

潜在增益：

```text
中高
```

但前提：

> Router 必须允许 `NO_TOOL / DIRECT_RESPONSE` 成为合法路径。

如果 Planner 被强制必须选一个 capability，

反而会更差。

---

# 16. BFCL Multi-Turn Missing Parameter

这是和 StateBus 当前 contract 最贴的类别之一。

任务特点：

```text
正确 function 已经存在
但必要参数缺失
Agent 应主动识别缺失信息
并向用户追问
```

StateBus 已有：

```text
required_input_fields
typed dependency
input Ref validation
PlanPolicy
```

因此可以设计：

```text
Function schema
   ↓
External Capability Descriptor
   ↓
required_input_fields
   ↓
Binding / Policy
   ↓
missing field
   ↓
ASK_USER
```

潜在质量提升：

```text
高
```

这是第一批最值得跑的 category。

---

# 17. BFCL Multi-Turn Missing Function

任务特点：

```text
当前 turn 缺少真正需要的 function
后续可能增加新 function
```

BFCL BaseHandler 本身支持：

```text
holdout function
later turn extend function list
recompile tools
```

StateBus 可映射：

```text
dynamic CapabilityRegistry
   ↓
当前 no feasible provider
   ↓
不允许 hallucinate unavailable tool
   ↓
replan / wait / clarify
   ↓
下一 turn capability surface 更新
```

潜在增益：

```text
高
```

这会直接验证：

```text
CapabilityRegistry + feasibility routing
```

是否真正有价值。

---

# 18. BFCL Multi-Turn Long Context

任务特点：

```text
history 很长
需要跨 turn 保存状态
```

StateBus 已有：

```text
typed state
ArtifactRef
SemanticState
Memory
EvidencePack
Prefix / KV experimental path
```

注意：

BFCL external conversation history本身不能随便丢。

但 StateBus 内部可以避免：

```text
Planner
Retriever
Executor
Summarizer
```

每个角色重新 hydration 整段外部 history。

可以：

```text
external history
  ↓
controller-owned compact state
  ↓
内部角色只拿所需 Ref
```

潜在收益：

```text
Token / context cost:
高潜力

accuracy:
中等潜力

latency:
取决于额外 Agent 调用
```

所以要同时测：

```text
accuracy
input tokens
output tokens
latency
```

---

# 19. BFCL V4 Memory

官方 Memory 465 entries：

```text
KV Store 155
Vector Store 155
Recursive Summarization 155
```

并覆盖：

```text
student advising
customer support
personal todo
healthcare
finance
```

BFCL 通过 memory APIs 让 agent：

```text
add
remove
search
clear
```

StateBus 当前 Memory 有：

```text
SQLite/FTS
vector retrieval
compatibility
replay gate
actual-use accounting
```

结构上非常贴。

但这里不是“直接把 StateBus Memory 打开就能跑”。

需要：

```text
BFCL Memory API
       ↓
StateBus Memory Adapter
```

因此 Memory 是：

```text
BFCL Phase 2
```

不是第一个 integration slice。

潜在增益：

```text
高
```

尤其可以测：

```text
accuracy
memory operation count
query token
latency
```

---

# 20. BFCL Web Search

官方 200 entries：

```text
Snippet 100
No Snippet 100
```

模型需要：

```text
search
fetch
multi-hop integrate
```

StateBus 有：

```text
EvidencePack
SemanticEmbeddingRef
retrieval
provenance
```

潜在收益：

```text
evidence token / provenance:
高

final answer accuracy:
中

integration cost:
中高
```

建议等 Capability Routing 和 Memory 跑通后再做。

---

# 21. BFCL Parallel / Multiple

需要谨慎。

虽然 StateBus Planner 可以表达 DAG，

但当前 AdaptiveRuntime 的 physical parallel execution 是否足以得到 latency benefit需要单独审计。

因此：

```text
不要在尚未实现真实 parallel dispatch 时
把 BFCL parallel category 当成“并行加速证明”。
```

可以先作为：

```text
function selection correctness
```

测试，而不是 latency headline。

---

# 22. BFCL 第一阶段正式实验设计

推荐完整 category，不挑 individual case：

```text
simple_python            negative control
irrelevance              no-tool routing
multi_turn_miss_param    required-input routing
multi_turn_miss_func     dynamic capability routing
multi_turn_long_context  state/context routing
```

第二阶段：

```text
memory
web_search
```

---

# 23. BFCL Baselines

所有 baseline 固定：

```text
same Qwen3-32B
same vLLM
same BFCL commit/package
same temperature
same function surface
```

比较：

## B0 Direct

```text
BFCL native Qwen3-32B FC
```

## B1 Fixed StateBus

```text
每个 task 都走完整 StateBus path
```

## B2 Adaptive StateBus

```text
PlanSelector
+
Capability Router
+
必要时 State / Memory
```

预期：

```text
Simple:
B2 ≈ B0
B1 更贵

Missing / Irrelevance / Long:
B2 > B0 quality 或 cost-quality
```

这比只比较：

```text
Direct vs Full StateBus
```

更合理。

---

# 24. BFCL 接入方式：Native Handler，而不是改数据

BFCL 当前 `BaseHandler` 已经负责：

```text
test_entry
function schemas
multi-turn loop
native function execution
token/latency logging
evaluation output
```

正确做法：

```text
BFCL
  ↓
StateBusBFCLHandler
  ↓
StateBus internal runtime
  ↓
返回 BFCL-compatible function calls
  ↓
BFCL native executor
  ↓
BFCL native evaluator
```

不要：

```text
BFCL JSON
  ↓
转换成 statebus/tasks/formal/*.json
```

---

# 25. BFCL Adapter 第一版尽量不改 StateBus Core

第一版尝试：

```text
external function schema
  ↓
temporary capability surface
```

如果当前 CapabilityRegistry 无法动态表示 external function，

才新增最小：

```text
ExternalToolProvider
```

或者在前一份 Routing R0：

```text
LogicalCapability / ExecutionProvider split
```

完成后增加：

```text
provider = external_tool
```

但不能因为 BFCL 就：

```text
新增 BFCL task_family
新增 BFCL intent_op
新增 bfcl_* capabilities
```

---

# 26. 第二主 benchmark：τ³-bench

当前 repository：

```text
sierra-research/tau2-bench
```

虽然名字仍叫 tau2-bench，

2026 已正式升级为：

```text
τ³-bench
```

当前约：

```text
1,933 GitHub Stars
```

并持续更新 leaderboard。

---

# 27. τ³ 为什么特别贴 StateBus

它的 external Agent contract 非常干净。

Half-Duplex Agent：

```python
get_init_state(message_history)

generate_next_message(
    message,
    state
) -> (AssistantMessage, State)
```

构造时 benchmark 原生传：

```python
tools
domain_policy
```

也就是说：

```text
tools
policy
user message
tool results
```

都是公开给被测 Agent 的输入。

我们无需自己定义：

```text
intent_op
required_tools
task_family
```

。

---

# 28. τ³ Agent Adapter 很适合 StateBus

可以实现：

```text
StateBusTauAgent(HalfDuplexAgent)
```

内部：

```text
incoming user/tool message
       ↓
StateBus external state
       ↓
PlanSelector
       ↓
Planner / direct
       ↓
Capability binding
       ↓
tool call / assistant response
       ↓
τ³ orchestrator
```

Native evaluator 完全不需要改。

---

# 29. τ³ 的 evaluator 对 Router 非常友好

Airline / Retail / Telecom 默认主要按：

```text
DB
+
COMMUNICATE
```

评分。

`evaluation_criteria.actions` 通常只是：

```text
一条 reference trajectory
```

不是唯一允许的路径。

任何不同 tool sequence 只要最终：

```text
DB state 等价
+
required information 正确沟通
```

也能 pass。

这非常重要。

因为它真正允许比较：

```text
不同 workflow / routing
```

而不是要求复制 benchmark 作者的路线。

---

# 30. τ³ 对 benchmark leakage 的边界也更清晰

正确接法：

```text
Agent:
tools + public policy + messages

Evaluator:
reference actions
gold DB target
assertions
```

StateBus adapter 不应该拿：

```text
evaluation_criteria.actions
```

生成 Plan。

尤其不能：

```text
reference action
→ capability plan
```

否则会重新制造 solution leakage。

---

# 31. τ³ Banking Knowledge 是 StateBus 最有潜力的 domain

2026 新增：

```text
banking_knowledge
```

大约：

```text
700-document knowledge base
```

可用 retrieval config：

```text
BM25
dense embedding
grep
shell
alltools
```

当前官方 leaderboard最好 Pass^1 也大约：

```text
55.2%
```

说明 headroom 非常明显。

StateBus 有：

```text
Embedding State
EvidencePack
retrieval
provenance
Memory
typed state
```

这是目前外部 benchmark 中和 StateBus semantic-state/memory 最贴的一条。

---

# 32. τ³ Banking 第一阶段如何公平比较

不能：

```text
Direct baseline 用 BM25
StateBus 用 alltools+dense+shell
```

然后说 StateBus 更强。

正确：

```text
固定 retrieval config
```

例如：

```text
bm25
```

或：

```text
alltools-qwen
```

Direct 和 StateBus 得到同样 tools。

StateBus 只改变：

```text
内部证据选择
角色协作
typed state
routing
```

这样改进才能归因于 Runtime。

---

# 33. τ³ Banking 可测的 StateBus 机制

```text
SemanticEmbeddingRef
    evidence candidate selection

EvidencePack
    provenance / hydration

Typed Ref
    internal handoff

Memory
    multi-turn reuse

PlanSelector
    direct vs retrieve vs analyze

Capability Router
    BM25 / dense / shell 选择
```

潜在提升：

```text
quality:
中高

token:
高

provenance / audit:
高

latency:
不确定
```

---

# 34. τ³ Retail / Airline / Telecom

这三个 domain 更偏：

```text
policy
conversation
tool calls
mutating action
```

StateBus 可能帮助：

```text
risk-aware routing
typed state
no-op / refuse routing
optional verifier path
```

但是必须承认：

当前 StateBus `PlanPolicyValidator` 主要验证：

```text
capability authority
risk class
dependency
input Ref
budget
```

它并不天然理解：

```text
τ³ domain policy 的自然语言业务规则。
```

所以：

> 当前版本不能直接宣称 StateBus PlanPolicy 会显著提升 τ³ policy adherence。

如果要提升这一块，

需要后续：

```text
Policy-check / Verifier role
```

或 generic rule extraction。

因此：

```text
Banking Knowledge:
P0/P1

Retail/Airline/Telecom:
P1/P2
```

---

# 35. τ³ 还有一个很重要的 lesson：不要把 reference action 当 Required Plan

τ³ 官方文档专门强调：

```text
evaluation_criteria.actions
只是一条 reference trajectory
```

大多数 domain 按最终 DB state 评分。

这和我们当前 Controlled E5：

```text
Runtime reference recomputation
```

完全不同。

因此 External lane 正确的 evaluator 应尽量：

```text
outcome based
```

而不是：

```text
要求 StateBus 按预设 Plan 执行。
```

---

# 36. 第三候选：AgentBench FC

当前：

```text
THUDM/AgentBench
≈ 3711 Stars
ICLR 2024
```

2025-10 当前主仓库已加入 Function Calling 版本，并 containerize：

```text
ALFWorld
DBBench
KnowledgeGraph
OS Interaction
WebShop
```

---

# 37. AgentBench 为什么值得保留

它能回答一个不同问题：

> StateBus 是否只能解决自己设计的数据分析 task，
> 还是能作为一般 interactive agent runtime 工作？

尤其推荐：

```text
OS
DB
```

因为资源要求低：

```text
OS worker < 500MB
DB worker < 500MB
```

且 evaluator 是：

```text
Success Rate
```

---

# 38. AgentBench 接口本身也很薄

旧/兼容 AgentClient 核心：

```python
inference(history: List[dict]) -> str
```

因此可以：

```text
AgentBench Client
    ↓
StateBusAgentClient
    ↓
StateBus
```

不需要转成 CanonicalTaskSpec。

---

# 39. AgentBench 上能否期待提升

## OS

可能利用：

```text
Plan
CodeAct
Artifact state
history compression
```

但当前 StateBus CodeAct 主要经过 bounded Python/Workspace 流程，

并不是一个成熟通用 terminal coding agent。

因此：

```text
质量提升信心：中
```

## DB

和当前 DSL/CodeAct 更接近：

```text
structured query
schema
multi-table
interactive result
```

因此：

```text
质量提升信心：中高于 OS
```

AgentBench 更适合：

```text
generalization sanity check
```

而不是第一 headline gain benchmark。

---

# 40. AppWorld：比 SWE-bench 更贴 API / CodeAct，但仍应后置

AppWorld：

```text
ACL 2024 Best Resource Paper
~502 Stars
9 apps
457 APIs
100+ database tables
stateful interactive coding
```

它原生强调：

```text
不要 hardcode API call
test set 不做手工 tuning
```

这和 StateBus external-boundary 思路高度一致。

---

# 41. AppWorld 与 StateBus 的映射

```text
ApiDocs
    → retrieval capability

457 APIs
    → large capability surface

interactive Python
    → CodeAct

persistent AppWorld state
    → Artifact / typed state

multi-step task
    → Planner / Router
```

理论匹配很好。

但实际 blocker：

```text
Current CodeAct
尚未被证明能稳定完成复杂 persistent interactive API coding。
```

所以 AppWorld 适合作为：

```text
P2
```

不是当前第一个 external benchmark。

---

# 42. SWE-bench：认可度最高，但当前版本不是最佳主线

SWE-bench：

```text
~5765 Stars
ICLR 2024 Oral
Full 2294
Lite 300
Verified 500
```

Native evaluator：

```text
repo
issue
patch
Docker
tests
```

公信力极高。

但当前 StateBus 的 CodeAct evidence 是：

```text
五类 25 个 controlled analysis tasks
```

还没有证明：

```text
repository exploration
multi-file edit
test-debug loop
patch refinement
```

所以当前直接上 SWE-bench：

```text
实现成本高
成功率风险高
很可能测成“coding agent 能力不足”
而不是 StateBus Runtime 能力
```

---

# 43. SWE-bench 什么时候值得做

等下面能力成熟：

```text
generic repo asset
persistent workspace
repo retrieval
multi-step test feedback
CodeAct edit loop
artifact patch
verifier/test loop
```

再跑：

```text
SWE-bench Lite
或 Verified
```

因此：

```text
认可度：
★★★★★

当前匹配度：
★★★

当前实施优先：
P3
```

---

# 44. MLE-bench 为什么不推荐现在做

OpenAI MLE-bench：

```text
~1729 Stars
75 Kaggle competitions
```

认可度足够。

但它需要：

```text
模型训练
大量数据
长时间 compute
GPU / storage
```

会把 StateBus 项目带向：

```text
ML engineering automation
```

而不是：

```text
multi-agent communication/state runtime
```

因此不适合作为当前主外部评测。

---

# 45. Terminal-Bench

当前 Harbor repo：

```text
~595 Stars
```

任务覆盖：

```text
compile
server setup
terminal ops
model training
system tasks
```

认可度正在增长。

但当前 StateBus 还没有成熟 general terminal agent。

因此和 SWE-bench 类似：

```text
后续 CodeAct expansion benchmark
```

不是当前 P0。

---

# 46. LongMemEval-V2 重新定位

当前约：

```text
148 Stars
```

Star 低于 BFCL / τ³ / AgentBench，

所以不作为“项目公开背书主 headline”。

但是它的 Memory interface 非常干净：

```python
insert(trajectory)
query(question)
```

并专门做 query privacy test。

所以 LongMemEval-V2 的定位变为：

```text
Memory subsystem 专项 external evidence
```

不是整体 StateBus headline。

---

# 47. TeamBench / IDA-Bench 重新定位

## TeamBench

当前：

```text
8 Stars
```

虽然：

```text
role-separated MAS
```

和 PlanSelector 极其贴，

但目前太新，社区认可度不足。

使用方式：

```text
research comparison / discussion reference
```

而不是：

```text
main external benchmark
```

## IDA-Bench

当前：

```text
11 Stars
```

虽然和：

```text
DSL vs CodeAct
```

很贴，

但同样不适合作为简历 headline。

可作为：

```text
Data-analysis specialized supplement
```

---

# 48. 最终 External Benchmark Scorecard

| Benchmark | Recognition | Current Fit | Native Boundary | Integration Cost | Gain Opportunity | Priority |
|---|---:|---:|---:|---:|---:|---:|
| BFCL V4 | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★ | ★★★★☆ | P0 |
| τ³-bench | ★★★★☆ | ★★★★★ | ★★★★★ | ★★★★ | ★★★★ | P0/P1 |
| AgentBench FC | ★★★★☆ | ★★★☆ | ★★★★ | ★★★★ | ★★★ | P1 |
| AppWorld | ★★★☆ | ★★★★☆ | ★★★★★ | ★★★ | ★★★☆ | P2 |
| SWE-bench | ★★★★★ | ★★★ | ★★★★★ | ★ | ★★ | P3 |
| MLE-bench | ★★★★ | ★★★ | ★★★★★ | ★ | ★★ | P3 |
| Terminal-Bench | ★★★☆ | ★★★ | ★★★★★ | ★★ | ★★☆ | P3 |
| LongMemEval-V2 | ★★☆ | ★★★★★(Memory) | ★★★★★ | ★★★★ | ★★★★ | Supplement |
| TeamBench | ★★ | ★★★★★(Role) | ★★★★ | ★★★ | ★★★ | Research |
| IDA-Bench | ★★ | ★★★★☆ | ★★★★ | ★★★ | ★★★ | Research |

---

# 49. “我们的实现能否带来提升”的客观回答

不能在实验前保证：

```text
StateBus > baseline
```

但是可以建立：

```text
Mechanism-to-Failure Hypothesis
```

只有 benchmark 的 failure mode 和 StateBus 机制真正对应，

才值得跑。

---

# 50. Improvement Confidence Matrix

| Benchmark Category | StateBus 当前机制 | 增益预期 |
|---|---|---:|
| BFCL simple | PlanSelector direct bypass | 质量≈；成本避免退化 |
| BFCL irrelevance | no-tool route / Logit Gate / Policy | 中高 |
| BFCL miss_param | required_input_fields / typed contract | **高** |
| BFCL miss_func | dynamic capability / feasibility / replan | **高** |
| BFCL long_context | typed state / memory / semantic pruning | 高（成本） |
| BFCL memory | StateBus Memory | 高，但需 adapter |
| BFCL web search | EvidencePack / Embedding | 中高 |
| τ³ banking knowledge | retrieval / embedding / state | **高** |
| τ³ retail/airline/telecom | role routing / risk / state | 中 |
| AgentBench DB | DSL / CodeAct / state | 中 |
| AgentBench OS | CodeAct / planning | 中低~中 |
| AppWorld | capability routing / CodeAct | 中，但需扩能力 |
| SWE-bench | current CodeAct | **低** |
| MLE-bench | current Runtime | 低~中 |
| LongMemEval | Memory | 高 |

这张表比单纯 Star 排名更重要。

---

# 51. External Evaluation 不能只看 Quality

StateBus 的项目核心包括：

```text
低开销通信
状态传递
共享记忆
Runtime policy
```

所以 external benchmark 也必须测：

```text
native benchmark score

input tokens
output tokens
wall latency
LLM calls

StateBus plan latency
role count
capability selection
state bytes
fallback
memory hit/actual-use
routing overhead
```

否则只看：

```text
Pass Rate
```

会丢掉项目最核心的系统价值。

---

# 52. External Benchmark 的正确三组 Baseline

任何主 benchmark 建议：

## Direct

```text
same model
benchmark native agent / FC path
```

## Fixed StateBus

```text
same model
固定完整 StateBus workflow
```

## Adaptive StateBus

```text
same model
PlanSelector + BindingResolver
必要机制才启用
```

真正 claim：

```text
Adaptive
减少 Fixed 的协作过度
并在复杂 task 上保留 StateBus 质量收益
```

---

# 53. 为什么 Fixed StateBus 即使更差也有价值

假设：

```text
BFCL simple:
Direct 95
Fixed 92
Adaptive 95

BFCL miss-param:
Direct 55
Fixed 70
Adaptive 70
```

这不是坏结果。

它恰好说明：

```text
multi-agent/runtime machinery
不是所有 task 都该启用

Router 是必要的
```

这是非常好的系统结论。

---

# 54. External Eval 第一阶段不要改 7 个核心 Dataclass

上一版提出：

```text
MinimalBenchmarkSample
CanonicalTaskSpec
AdaptiveTaskEnvelope
AdaptiveMainlineRequest
AdaptiveDispatchContext
MemoryQuery
MemoryCommit
```

全面 Before→After。

现在调整：

# 这些仍然是“潜在迁移热点”，但不再作为第一实施步骤。

---

# 55. 为什么先不改 `MinimalBenchmarkSample`

因为 external benchmark 根本不应该进入：

```text
MinimalBenchmarkSample
```

所以：

```text
现有 Controlled sample
保持原样
```

External adapter 使用 benchmark native object。

没有理由先改它。

---

# 56. 为什么先不改 `CanonicalTaskSpec`

同样：

```text
Controlled lane
继续使用 CanonicalTaskSpec
```

External lane：

```text
尽量绕过 TaskCompiler(BENCHMARK_STRICT)
```

只有当 AdaptiveMainline 真正强制需要它时，

才增加 minimal bridge。

不要提前把 CanonicalTaskSpec 设计成：

```text
万能外部 task schema
```

。

---

# 57. `AdaptiveTaskEnvelope` 仍是最可能的真实 Core Seam

External integration 需要 Runtime authority：

```text
allowed capabilities
risk
role cardinality
budget
```

所以 `AdaptiveTaskEnvelope` 很可能继续复用。

原则：

```text
External Adapter
不是把 benchmark semantics 写进 Envelope

而是：
根据 benchmark public tool surface
形成 Runtime authority
```

例如 BFCL：

```text
BFCL functions
→ allowed external capabilities
```

没有：

```text
intent_op
expected answer
```

。

---

# 58. `AdaptiveMainlineRequest` 只在真实 blocker 出现时改

如果现在可以：

```text
canonical_task_spec=None
+
available input refs
+
Envelope
```

跑通外部 adapter，

就不应提前增加：

```text
external_task_envelope
available_input_assets
visibility_audit
```

等字段。

如果 BFCL / τ³ 都出现同类公共输入问题，

再抽象。

---

# 59. `AdaptiveDispatchContext` 同样触发式修改

第一个真实 blocker 很可能不是：

```text
task contract
```

而是：

# External Tool Execution Provider

当前 Dispatcher 的 handler 主要是：

```text
retrieval
DSL
bounded Python
builtin
```

而 BFCL / τ³ 给的是：

```text
benchmark-native external tool
```

所以真正可能需要的是：

```text
ExternalToolProvider
```

而不是先重构所有 task identity。

---

# 60. MemoryQuery / MemoryCommit 明确后置

BFCL 第一阶段：

```text
memory category 不跑
```

τ³ 第一阶段也可以：

```text
StateBus memory off
```

先打通 capability / routing。

之后 Memory phase 再解决：

```text
CanonicalTaskSpec coupling
MemoryQuery compatibility
MemoryCommit identity
```

这样不影响旧 memory tests。

---

# 61. 七个 Contract 的新优先级

| Contract | 旧建议 | v2 建议 |
|---|---|---|
| MinimalBenchmarkSample | P3 改 lane | **不改** |
| CanonicalTaskSpec | bridge | **Controlled 保留，external 尽量绕过** |
| AdaptiveTaskEnvelope | P0 | **真实 external seam，必要时最小扩展** |
| AdaptiveMainlineRequest | P0 | **先尝试不改** |
| AdaptiveDispatchContext | P0 | **ExternalToolProvider blocker 出现再改** |
| MemoryQuery | P1 | **Memory external phase** |
| MemoryCommit | P1/P2 | **Memory external phase** |

---

# 62. 哪些前一版设计仍然保留为未来候选

以下设计不是删掉，

而是从：

```text
First implementation
```

降级成：

```text
Trigger-based abstraction
```

包括：

```text
InputAssetRef
ExternalTaskEnvelope
TaskContractIdentity
BenchmarkVisibilityAudit
```

---

# 63. 什么时候必须引入 `InputAssetRef`

当出现第二个 benchmark 都需要：

```text
raw FILE / DIRECTORY / REPOSITORY
```

且当前 `ExecutionArtifactRef` 无法准确表达：

```text
“这是外部输入，而不是 Runtime 产物”
```

时再引入。

最可能触发：

```text
AppWorld
SWE-bench
AgentBench OS
```

BFCL 不一定需要。

---

# 64. 什么时候必须引入 `TaskContractIdentity`

当至少两个 external benchmark 都因为：

```text
canonical_task_spec_hash
```

无法通过 Runtime / Memory compatibility 时，

再引入 generic identity。

第一版 BFCL 如果不用 StateBus Memory，

可能根本不需要。

---

# 65. 什么时候必须实现 `BenchmarkVisibilityAudit`

正式 external leaderboard 结果前建议实现。

但 adapter bring-up 阶段可先用：

```text
manual visibility inventory
unit test
process-level boundary
```

避免先引入复杂 contract。

一旦准备发布结果，

必须做到：

```text
Gold
grader
reference action
benchmark category
```

不会进入 Router / Planner。

---

# 66. 第一阶段外部目录建议

优先独立：

```text
statebus/integrations/external_eval/
    bfcl/
    tau3/
    agentbench/
```

或：

```text
external_eval/
```

具体目录以仓库现有风格为准。

关键原则：

```text
不要把 BFCL code 塞进
statebus/benchmark/adaptive_formal.py
```

。

---

# 67. E0：BFCL Adapter Spike

目标：

```text
证明 BFCL 原生 case
可以不转 CanonicalTaskSpec
进入 StateBus 并返回合法 function call。
```

Scope：

```text
1~5 dev/specified run IDs

只跑：
simple_python
irrelevance

不改 Memory
不改 KV
不改 Prefix
```

成功标准：

```text
BFCL native evaluator 能评分
StateBus core 改动最小
internal tests 全部通过
```

---

# 68. E1：BFCL Routing Formal

固定官方 category：

```text
simple_python

irrelevance

multi_turn_miss_param

multi_turn_miss_func

multi_turn_long_context
```

不是挑单题。

比较：

```text
Direct Qwen3-32B FC

Fixed StateBus

Adaptive StateBus
```

记录：

```text
BFCL category accuracy

tokens
latency

Planner invocation
no-tool decision
missing-field rejection
capability-unavailable event
fallback
```

---

# 69. E1 的 Success Criteria 不应该定义成“Overall 必须涨”

更合理：

```text
Simple:
Adaptive 不显著退化

Missing Param:
Adaptive accuracy 提升

Missing Function:
hallucinated unavailable tool 减少

Long Context:
相同或更高 quality 下 token 降低

Irrelevance:
false tool call 降低

Routing overhead:
相对 Fixed 明显降低
```

只要这些成立，

即使 BFCL Overall 未显著增加，

Router 仍然有非常强的证据。

---

# 70. E2：BFCL Memory

将 BFCL：

```text
memory_kv
memory_vector
memory_rec_sum
```

映射到：

```text
StateBus Memory Adapter
```

此时才进入：

```text
MemoryQuery / MemoryCommit genericization
```

。

也就是：

> Memory contract 改造由真实 BFCL use case 驱动。

---

# 71. E3：τ³ Banking Knowledge

实现：

```text
StateBusTauAgent
extends HalfDuplexAgent
```

第一阶段：

```text
same retrieval config
same Qwen model
same user simulator
same task split
```

比较：

```text
native LLMAgent

Fixed StateBus Agent

Adaptive StateBus Agent
```

---

# 72. τ³ Banking Experiment Variables

建议至少两组 retrieval config：

```text
bm25

alltools-qwen
```

注意：

不要因为 StateBus 自己支持 embedding 就更换 baseline retriever。

先保持同一 retrieval surface。

StateBus 的增益来自：

```text
哪个 tool 被选
哪些 evidence 被内部传递
是否重复 hydration
是否需要额外 role
```

---

# 73. E4：τ³ Retail / Airline / Telecom

等 Banking 和 Router 稳定后再做。

研究问题：

```text
简单事务：
direct

复杂 policy / mutation：
Planner + optional verifier
```

这是 Role Routing 非常好的 workload。

但如果没有实现：

```text
semantic policy verifier
```

就不要提前承诺质量提升。

---

# 74. E5：AgentBench FC OS / DB

定位：

```text
Generalization sanity check
```

优先：

```text
DB
OS
```

不必一开始跑 8 environment。

比较：

```text
AgentBench native FC agent

StateBus adapter
```

这里可以测试：

```text
StateBus 是否只适配 BFCL/τ³
```

。

---

# 75. 是否做 SWE-bench

决策 Gate：

只有以下条件同时满足再做：

```text
repo input provider READY
persistent CodeAct loop READY
multi-file write READY
test feedback loop READY
patch artifact READY
```

否则：

```text
NO-GO
```

。

这样避免为了“5k Star”把项目范围拖垮。

---

# 76. Routing 与 External Evaluation 的真正关系

前一份 Routing 设计：

```text
PlanSelector
ExecutionBindingPolicy
StatePlacementPolicy
DecisionGatePolicy
InferenceReusePolicy
```

External benchmark 不应该重新设计 Router。

它应该：

```text
提供真实 workload
```

验证 Router。

例如 BFCL：

```text
simple
→ direct

miss-param
→ clarification

miss-function
→ no feasible provider / wait

long-context
→ state-aware route
```

这是非常自然的 Router workload。

---

# 77. 这也是为什么当前 Formal E5 不需要改

当前 E5：

```text
固定 role cardinality
固定 operation contract
```

所以它继续测：

```text
provider correctness
controlled capability path
```

BFCL / τ³ 才测：

```text
开放 routing
```

两条 lane 互补。

---

# 78. 关于 External Gold / Grader Boundary，原则仍然不变

即使本版不马上实现完整：

```text
BenchmarkVisibilityAudit
```

仍必须遵守：

```text
Gold / hidden evaluator
永远不进入 StateBus
```

---

# 79. BFCL 的 Public / Private 边界

StateBus 可以看：

```text
question
function definitions
execution results
public multi-turn messages
```

不能看：

```text
expected function call
evaluation AST target
reference state
```

。

---

# 80. τ³ 的 Public / Private 边界

StateBus 可以看：

```text
tools
domain policy
user message
tool result
public knowledge tools
```

不能看：

```text
evaluation_criteria.actions
target DB hash
communicate_info gold
hidden assertions
```

。

特别：

```text
evaluation_criteria.actions
绝不能用来预编译 Plan。
```

---

# 81. AgentBench Public / Private 边界

StateBus 只能通过：

```text
Task Server / history
```

交互。

不能读取：

```text
task answer
success condition internals
```

来构造 Router hint。

---

# 82. 不应该把 Benchmark Name 放入 Router Feature

即使 Adapter 代码知道：

```text
这是 BFCL
这是 τ³
```

Router 也不应该：

```python
if benchmark == "bfcl":
    ...
```

。

正确 feature：

```text
tool count
required parameter state
conversation length
tool availability
input media
risk
memory state
```

。

---

# 83. Benchmark-specific Adapter 与 Runtime-specific Policy 的边界

```text
Adapter:
把外部 protocol 变成 Runtime 可以消费的公开对象

Router:
根据 Runtime facts 决策

Benchmark Evaluator:
根据 private oracle 打分
```

严格三段。

---

# 84. 旧 Contract Audit 仍然有价值，但用途变化

上一版对：

```text
MinimalBenchmarkSample
CanonicalTaskSpec
AdaptiveTaskEnvelope
AdaptiveMainlineRequest
AdaptiveDispatchContext
MemoryQuery
MemoryCommit
```

的字段分析仍然是：

```text
migration inventory
```

但现在不应该把它误解为：

```text
必须全部先改。
```

---

# 85. Contract Trigger Matrix

| 真实 blocker | 应改 Contract |
|---|---|
| BFCL tools 无法映射 Registry | Capability / Provider contract |
| External task 无法进入 Mainline | AdaptiveMainlineRequest / task identity |
| raw repo/file 无法授权 | InputAssetRef |
| Role policy 不能动态生成 | AdaptiveTaskEnvelope |
| external tool 无法执行 | AdaptiveDispatchContext / ExternalToolProvider |
| BFCL Memory 无法 reuse | MemoryQuery / MemoryCommit |
| 多 benchmark 重复 public/private boundary | BenchmarkVisibilityAudit |
| 多 benchmark 都不适合 CanonicalTaskSpec hash | TaskContractIdentity |

这比“一次改七个 dataclass”更可靠。

---

# 86. Internal Regression Gate

任何 external slice：

```text
E0 / E1 / E2 / ...
```

都必须先跑：

```text
existing pytest
existing controlled benchmark smoke
```

并记录：

```text
internal_baseline_compatibility = PASS
```

---

# 87. Hard Compatibility Rule

如果 External integration 为了方便需要：

```text
修改现有 MinimalBenchmarkSample
修改 existing task JSON
修改 CanonicalTaskSpec 的旧字段语义
修改 formal evaluator
```

默认判定：

```text
DESIGN WRONG
```

除非有非常明确的 Runtime bug 证据。

---

# 88. 推荐最终项目 Evidence Story

未来 README 可以分：

## Controlled Mechanism Evidence

```text
现有 45 case + 专项实验
```

证明：

```text
mechanism works
```

## External Routing Evidence

```text
BFCL V4
```

证明：

```text
capability / state-aware routing
```

## External Stateful Agent Evidence

```text
τ³
```

证明：

```text
multi-turn / knowledge / policy / tools
```

## Optional Generalization Evidence

```text
AgentBench OS/DB
```

证明：

```text
不是只为一个 benchmark 特制
```

这比：

```text
“我们自己 45 个 case 全赢”
```

强得多。

---

# 89. 不要追求“StateBus 在所有公开 benchmark 都赢”

这既不现实，也和 Router 的研究动机冲突。

真正项目 claim：

> StateBus 在 controlled mechanism benchmark 中提供可验证的通信/状态/记忆/推理复用收益；在公开 agent benchmark 中，通过 adaptive workflow/capability routing，避免在简单任务上强制多 Agent 开销，并在 missing information、dynamic tool availability、long-context、memory 和 knowledge-intensive workload 上改善 quality-cost tradeoff。

这是更可信的目标。

---

# 90. 当前对项目问题严重程度的最终判断

## 是否发现严重 Runtime correctness bug？

```text
NO
```

目前没有看到：

```text
Gold 直接进入 Agent
Runtime 结果伪造
evaluator 与 actual output 脱节
```

这类严重问题。

## 是否存在自建 benchmark 特化？

```text
YES
```

主要：

```text
CanonicalTaskSpec closed taxonomy
FormalAdapter operation mapping
input normalization
reference semantics
fixed role topology
```

## 这是否使原有消融无效？

```text
NO
```

因为原有消融本来是 controlled mechanism evaluation。

## 是否影响 general-purpose claim？

```text
YES
```

所以需要 External Native Benchmark。

## 正确修复方式？

```text
不是重写旧 benchmark

而是：
保留旧 lane
+
新增 native external lane
```

。

---

# 91. 当前推荐实施顺序

```text
R0
完成前一份 Routing 的 logical capability / provider split
（至少确保 external tool provider 有清晰 seam）

        ↓

E0
BFCL adapter spike
尽量 0 core change

        ↓

E1
BFCL：
simple / irrelevance /
miss-param / miss-function /
long-context

        ↓

根据真实 blocker
最小改 core

        ↓

E2
BFCL Memory

        ↓

E3
τ³ Banking Knowledge

        ↓

E4
τ³ Retail/Airline/Telecom

        ↓

E5
AgentBench DB / OS

        ↓

再决定：
AppWorld / SWE-bench
```

---

# 92. 与 Routing R0/R1 的协调

最值得注意：

```text
BFCL Function Schema
```

正好可以成为：

```text
External Logical Capability Surface
```

而真正执行方式：

```text
BFCL native function executor
```

是：

```text
Execution Provider
```

这和前一份：

```text
LogicalCapabilityDescriptor
ExecutionProviderDescriptor
BindingResolver
```

完全一致。

因此：

> BFCL 不只是 benchmark，也是 Routing R0/R1 最好的 external design pressure。

---

# 93. BFCL 可能暴露的第一个真实 Contract 问题

当前 StateBus CapabilityDescriptor 绑定：

```text
semantic capability
+
execution kind
```

BFCL 给你：

```text
hundreds of runtime function schemas
```

如果要给每个 function 定义：

```text
固定 internal capability_id
```

显然不可行。

所以 BFCL 很可能直接证明：

```text
Logical Capability / External Provider split
```

确实需要。

这是“被真实 benchmark 逼出来的重构”，含金量高于提前想象。

---

# 94. τ³ 可能暴露的第一个真实 State 问题

HalfDuplexAgent 需要自己维护：

```text
state
```

StateBus 可以第一次真正测试：

```text
外部 conversation state
+
内部 typed state
```

的双层状态结构。

如果现有 Mainline 只能绑定：

```text
CanonicalTaskSpec
```

到 memory/trace，

这时再引入：

```text
TaskContractIdentity
```

就有真实理由。

---

# 95. 研究型专项仍然可以保留

等主 external 做完后：

```text
TeamBench
```

可以做：

```text
role-routing case study
```

```text
IDA-Bench
```

做：

```text
DSL/CodeAct case study
```

```text
LongMemEval-V2
```

做：

```text
memory privacy/reuse case study
```

但不再承担 headline public recognition。

---

# 96. 最终 Benchmark Portfolio

建议最终最多四层：

```text
Level 0:
Internal Controlled
必须有

Level 1:
BFCL V4
必须有

Level 2:
τ³-bench
强烈建议

Level 3:
AgentBench OS/DB
可选通用性证明

Level 4:
SWE/AppWorld/LongMemEval
按能力成熟度选择
```

不要一次做 8 个 benchmark。

---

# 97. 最终 Architecture

```text
                    EXISTING STATEBUS
                         │
             Controlled paths unchanged
                         │
                         ▼
                 Adaptive Runtime
                         │
       ┌─────────────────┼──────────────────┐
       │                 │                  │
       ▼                 ▼                  ▼
   Internal Tests     BFCL Handler       τ³ Agent
       │                 │                  │
       │          Public function           │
       │          schemas/messages          │
       │                 │             public tools/policy
       │                 ▼                  │
       │            StateBus Router         ▼
       │                 │             StateBus Router
       │                 ▼                  │
       │          BFCL function call        ▼
       │                 │            Assistant/tool call
       │                 ▼                  │
       │         Native BFCL executor       ▼
       │                 │             τ³ environment
       │                 ▼                  │
       │         Native BFCL evaluator      ▼
       │                              Native τ³ evaluator
       │
       ▼
Old evidence preserved
```

核心不是：

```text
所有 benchmark
→ StateBus 特制 TaskSpec
```

而是：

```text
StateBus
作为被测 runtime / agent
嵌入 benchmark 原生 harness
```

。

---

# 98. 当前文档的 Contract Audit 如何保留

原 v1 里对七个 dataclass 的详细字段分析仍可作为附录使用。

但执行优先级统一修改为：

```text
DEFERRED UNTIL TRIGGERED
```

除：

```text
AdaptiveTaskEnvelope
Capability/Provider contracts
```

以外，不提前全面迁移。

---

# 99. 第一条 Codex External Slice 的正确规格

不是：

```text
B0/B1:
先创建一堆 generic external contract
```

而是：

```text
EXTERNAL-E0-BFCL-ADAPTER-SPIKE
```

目标：

```text
使用 BFCL 原生 test entry
不转换 StateBus formal sample

Qwen3-32B
通过 StateBus
输出 BFCL-compatible tool call

BFCL native evaluator
能够成功评分

existing internal tests unchanged
```

不追求 performance improvement。

这是 adapter compatibility slice。

---

# 100. 第二条 Slice 才是 Routing Experiment

```text
EXTERNAL-E1-BFCL-ROUTING
```

支持：

```text
simple
irrelevance
miss-param
miss-function
long-context
```

并记录：

```text
route decision
planner call
state path
tool call
BFCL score
tokens
latency
```

---

# 101. 对 README / 简历的未来写法

不要写：

> “在自建 45-case benchmark 上达到 100%。”

单独这样很弱。

更强：

> “在 45-case controlled suite 上完成 typed communication / semantic state / memory / CodeAct / KV 机制 A/B；进一步接入 Berkeley BFCL V4 与 τ³-bench 原生 evaluator，在不暴露 Gold/参考轨迹的前提下验证 adaptive capability/workflow routing，并以同模型 Direct / Fixed / Adaptive 三路对照衡量质量、Token、延迟与 routing regret。”

这才会把系统项目讲完整。

---

# 102. 参考资料与固定版本建议

## StateBus

- https://github.com/qcrs/os
- https://github.com/qcrs/os1

## BFCL / Gorilla

- Repo: https://github.com/ShishirPatil/gorilla
- BFCL README:
  https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard
- Test categories:
  https://github.com/ShishirPatil/gorilla/blob/main/berkeley-function-call-leaderboard/TEST_CATEGORIES.md
- Leaderboard:
  https://gorilla.cs.berkeley.edu/leaderboard.html
- BFCL V3 multi-turn:
  https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html
- BFCL V4 memory:
  https://gorilla.cs.berkeley.edu/blogs/16_bfcl_v4_memory.html
- BFCL V4 web:
  https://gorilla.cs.berkeley.edu/blogs/15_bfcl_v4_web_search.html

正式对齐官方 leaderboard 时建议固定其公开标注的 evaluation commit / package 版本，而不是直接追随不断变化的 main。

## τ³-bench

- Repo:
  https://github.com/sierra-research/tau2-bench
- Website:
  https://taubench.com
- Agent Developer Guide:
  https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/agent/README.md
- Evaluation:
  https://github.com/sierra-research/tau2-bench/blob/main/docs/evaluation.md
- Knowledge:
  https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/knowledge/README.md

建议正式结果至少 pin：

```text
tau2-bench >= v1.0.1
```

因为 2026-07 banking grading 有不兼容修正。

## AgentBench

- https://github.com/THUDM/AgentBench
- ICLR 2024
- 当前 main 已加入 AgentBench FC

## AppWorld

- https://github.com/StonyBrookNLP/appworld
- ACL 2024 Best Resource Paper

## SWE-bench

- https://github.com/SWE-bench/SWE-bench
- https://www.swebench.com/
- ICLR 2024 Oral

## LongMemEval-V2

- https://github.com/xiaowu0162/LongMemEval-V2

## Specialized references

- TeamBench:
  https://github.com/ybkim95/TeamBench
- IDA-Bench:
  https://github.com/lhydave/IDA-Bench

---

# 103. 最终冻结结论

1. **现有内部任务和所有消融默认不改。**
2. 当前没有发现 direct Gold leakage 或需要推翻 Runtime 的严重 bug。
3. 当前 formal 入口确实高度适配自建 controlled dataset，但这是 evaluation scope 问题，不是 controlled experiment 本身错误。
4. 不再优先做“大一统 ExternalTaskEnvelope 重构”。
5. 外部 benchmark 必须走原生 harness/evaluator。
6. Adapter 允许 benchmark-specific protocol mapping，但禁止 solution mapping。
7. BFCL V4 作为第一主 external benchmark。
8. τ³-bench 作为第二主 external benchmark，优先 banking_knowledge。
9. AgentBench FC OS/DB 作为通用性补充。
10. SWE-bench 当前暂不做，除非 CodeAct / repo workflow 明显扩展。
11. TeamBench / IDA 作为研究型专项，不作为主要 public credibility。
12. Contract refactor 改为真实 blocker 驱动。
13. External integration 每一 Slice 必须以 existing internal regression PASS 为 Gate。
14. External benchmark 不要求所有 task 都赢；Adaptive bypass 简单任务、复杂任务选择重路径才是 Router 的核心价值。
15. 最终 external claim 应报告 native score + token + latency + routing/state metrics，而不是只报准确率。

