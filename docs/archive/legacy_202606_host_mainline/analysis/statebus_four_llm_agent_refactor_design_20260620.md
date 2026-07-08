# StateBus 四个 LLM Agent 重构路线设计

日期：2026-06-20

适用范围：
- 当前仓库 `/home/qcrs/statebus/project`
- 当前主目标是路线设计，不做实现
- 暂不涉及 CodeAct 主线、真实 VM/openEuler、生产级远程执行

---

## 1. 结论先说

推荐路线不是“直接把系统改成完全自由的 swarm”，也不是“照搬 CrewAI/AutoGen/LangGraph Supervisor”。

**推荐路线**：

> 保留 StateBus 的三平面方法设计（控制面 / 状态面 / 记忆面）和 LangGraph 固定执行骨架，  
> 但把 `Planner / Retriever / Executor / Summarizer` 四个角色都升级成真实的 LLM 语义主体。  
> 同时新建一个**同角色、同任务、同模型、同评测**的 external pure-text 4-agent baseline，  
> 让比较对象从“内部 runtime 内两种 handoff 风格”升级成“4 LLM agents 下 text carrier vs StateBus carrier”。

这条路线的核心价值不是“更炫”，而是三件事：

1. 解决当前中间两层过于非 LLM、语义压缩过早的问题。
2. 让 comparator 更自然、更接近评审直觉里的多 Agent 协作。
3. 仍然保住 StateBus 的方法身份：结构化 carrier、typed state、shared memory、可观测执行图。

我不建议现在直接转向：

- `CrewAI` 式层级 manager 主导方案
- `AutoGen Swarm` 式完全自由 speaker-selection
- `LangChain Subagents` 式中央 supervisor + stateless subagents 作为 formal benchmark 主线

这些模式都能借鉴，但**不应直接成为 StateBus 的 formal benchmark runtime**。

---

## 2. 当前本地系统到底卡在哪

先基于当前仓库代码，而不是抽象讨论。

### 2.1 当前已经是四角色系统，但不是四个 LLM agent

当前角色名义上已经完整：

- `Planner`
- `Retriever`
- `Executor`
- `Summarizer`

实现见：

- `agents/sample_agents.py`
- `runtime/langgraph_adapter.py`
- `runtime/orchestrator.py`

但当前真正调用 LLM 的角色主要只有两端：

- `PlannerAgent.plan_task()` 在 headline 主路径上通常不跑 LLM，因为 `plan_source=yaml`
  - 见 `agents/sample_agents.py:547-553`
- `SummarizerAgent.execute_step()` 是 headline 中最稳定、最主要的 LLM 使用点
  - 见 `agents/sample_agents.py:1592-1643`

中间两层现在主要不是“语义 agent”，而是 runtime 逻辑：

- `RetrieverAgent` 负责 corpus 检索、memory assist、`feature_bundle` / `tool_candidate_set` / `replay_eligibility_bundle` 生成
  - 见 `agents/sample_agents.py:592-733`
- `ExecutorAgent` 主要消费 `feature_bundle` 或从 text handoff 中恢复出 route/tool，然后执行 playbook
  - 见 `runtime/executor_runtime.py:1236-1297`

所以当前系统更准确的说法是：

> “四角色编排 + 两端 LLM + 中间 deterministic runtime 决策”

而不是：

> “四个对等的 LLM 协作 agent”

### 2.2 当前 text comparator 不是外部传统 pure-text 协作

`contest_honest_headline_v1` 的 text 侧是 `text_whole_lane`，并不是外部 pure-text baseline。

任务变换逻辑见：

- `tasks/sample_tasks.py:529-573`

它把 headline text 行转换成：

- `transfer_strategy="text_whole_lane"`
- `handoff_profile="text_whole_lane"`

但这条 lane 仍在 StateBus runtime 内运行，并且当前 `Executor` 仍可从 handoff 文本恢复 route/tool：

- `runtime/executor_runtime.py:1236-1287`

这意味着当前 formal headline 比的是：

> StateBus 内部 natural-language whole-lane carrier  
> vs  
> StateBus 内部 minimal typed-state carrier

不是评审直觉里的：

> 传统文本多 Agent  
> vs  
> StateBus 协议化多 Agent

### 2.3 当前 token 不降的代码级根因

当前 headline 中基本只有 `Summarizer` 在稳定调用 LLM，而 protocol 侧传来的 typed state 最终又被重新文本化后放进 summarizer prompt：

- `agents/sample_agents.py:1610-1632`

也就是说，当前架构下的 token 根因不是“协议没省字节”，而是：

1. 上游决策没有让更多 LLM 直接参与。
2. 下游真正吃 token 的只有 `Summarizer`。
3. `Summarizer` 最终看到的仍是文本化内容。

因此在当前主线上，“StateBus protocol 降低 LLM token”本来就很难成立。

### 2.4 当前 external pure-text baseline 仍不够强

当前 external text runtime 在 `eval/text_open_baseline.py` 中。

虽然已经有 live API slice，但它还不是正式 comparator：

- live path 仍带 lexical fallback 起点
  - `eval/text_open_baseline.py:237-251`
- 当前 pack 只是小切片，不是 formal headline 对照面
  - `tasks/sample_tasks.py:522-523`
  - `tasks/sample_tasks.py:529-590`

所以现在如果继续只修补中间 deterministic 层，问题会变成：

> 你可能把内部 route/tool 选择修得更平滑了，  
> 但 formal comparator 仍然没对到赛题最关键的问题。

---

## 3. 为什么“四个角色都接入 LLM”是值得试的

用户提出的核心判断是：

> 当前中间两层不是 LLM，导致信息传递断裂、定义不自然、比较对象也不自然。

这个判断我认为**方向成立**，但要改成一个受控的工程结论：

### 3.1 这条路线解决的是真问题

如果把 `Retriever` 和 `Executor` 也改成 LLM 语义主体，会有三个直接变化：

1. route/tool 决策不再主要由 lexical/metadata helper 决定，而是由 role prompt + 局部上下文决定。
2. agent 之间的 handoff 语义会更自然，因为每一跳都真的是“上一位 agent 决定下一位 agent 该知道什么”。
3. external pure-text baseline 更容易做成“同构系统，只改 carrier”的公平比较。

### 3.2 但不能简单理解成“LLM 越多越好”

四个都接 LLM 后：

- token 大概率上升
- latency 大概率上升
- 调试复杂度上升
- 错误来源会从 deterministic helper 迁移到 prompt/context/handoff 设计

所以这条路线不是为了“优化当前 headline 数字”，而是为了：

> 重新建立一个更自然、更公平、更可解释的 benchmark object。

这是路线级重构，不是局部修 bug。

---

## 4. 外部参考里，哪些模式值得借，哪些不该照搬

下面只看与当前问题直接相关的官方文档/参考仓库。

### 4.1 LangChain / LangGraph：最有用的是 context engineering，不是 supervisor 包装

参考：

- LangChain multi-agent overview  
  https://docs.langchain.com/oss/python/langchain/multi-agent
- LangChain handoffs  
  https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs
- LangChain subagents  
  https://docs.langchain.com/oss/python/langchain/multi-agent/subagents
- LangGraph workflows and agents  
  https://docs.langchain.com/oss/python/langgraph/workflows-agents
- LangChain context overview  
  https://docs.langchain.com/oss/python/concepts/context
- LangChain memory overview  
  https://docs.langchain.com/oss/python/concepts/memory
- `langgraph-supervisor-py` README  
  https://github.com/langchain-ai/langgraph-supervisor-py

对 StateBus 最有价值的点：

1. **明确区分 workflow 和 agent**
   - LangGraph 文档强调：workflow 是预定代码路径，agent 是动态决策。
   - 这正适合 StateBus：**外层仍然是固定图，内层每个节点变成 LLM agent。**

2. **handoff 的重点不是“切换节点”，而是“控制传什么上下文过去”**
   - LangChain handoffs 文档反复强调 context engineering。
   - 这非常贴合 StateBus，因为 StateBus 的真正独特处本来就不是 DAG，而是 carrier / state / memory contract。

3. **subagents 模式说明了 stateless worker 的代价**
   - LangChain subagents 文档明确指出 subagents 是 stateless，context isolation 强，但重复调用成本高。
   - 这说明“中央 supervisor + 全部 subagents 作为工具”的模式不适合直接当 StateBus 的 formal comparator 主线。

4. **`langgraph-supervisor-py` 自己也建议更多场景直接用 tools 方式，而不是强依赖 supervisor 包**
   - 这进一步说明：我们应借模式，不应把 StateBus 变成 supervisor wrapper showcase。

结论：

> LangGraph 最值得借的是  
> “固定状态图 + 明确 state/context/store 区分 + 精细 context filtering”，  
> 不是把 StateBus 改写成 supervisor 演示项目。

### 4.2 AutoGen / Swarm：handoff 语义很有启发，但 speaker-selection 不适合直接拿来做 formal benchmark

参考：

- AutoGen handoffs  
  https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/design-patterns/handoffs.html
- AutoGen swarm  
  https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/swarm.html
- OpenAI Swarm  
  https://github.com/openai/swarm
- OpenAI Agents SDK orchestration  
  https://openai.github.io/openai-agents-python/multi_agent/
- OpenAI Agents SDK handoffs  
  https://openai.github.io/openai-agents-python/handoffs/
- OpenAI Agents SDK tracing  
  https://openai.github.io/openai-agents-python/tracing/
- OpenAI realtime sequential handoff example  
  https://github.com/openai/openai-realtime-agents

对 StateBus 最有价值的点：

1. **handoff 应该被建模成第一等原语**
   - Swarm / OpenAI Agents SDK 都把 handoff 作为核心能力。
   - 这非常适合 StateBus：当前已有 `PlanStep`、`StateRef`、`StepResult`，但 handoff 还不是显式的 LLM-level decision primitive。

2. **handoff 可以携带小量结构化 metadata**
   - OpenAI Agents SDK 的 `input_type` / `on_handoff` / `input_filter` 很有参考价值。
   - StateBus 可以对应成：
     - typed packet metadata
     - next-agent visible context filter
     - handoff history policy

3. **Tracing 需要把 handoff、tool call、usage 一起记录**
   - OpenAI Agents SDK 把 tracing 视为内建能力。
   - StateBus 当前已有较强 telemetry，这点可以直接升级，而不是重做。

4. **Swarm 的“轻量、可控、可测试”哲学适合我们**
   - 但其“无状态 between calls”不适合直接替代 StateBus 的 memory/state identity。

不该直接照搬的点：

1. **完全自由的 speaker-selection**
   - AutoGen swarm 的活跃 speaker 由最新 handoff 决定。
   - 这对开放系统很自然，但对 benchmark 不利：
     - 可重复性下降
     - metrics 归因更难
     - “到底比较了什么”更容易漂移

2. **把用户会话 ownership 交给随机活跃 agent**
   - 对客服/对话产品自然；
   - 对 StateBus 当前 contest object 不自然，因为我们要比较的是四个固定角色的协作机制，而不是用户会话路由产品。

结论：

> 借 OpenAI/AutoGen 的 handoff 语义和 tracing 视角，  
> 不借它们的完全自由 speaker-selection 作为 formal benchmark 主干。

### 4.3 CrewAI：manager + delegation + validation 很像企业流程，但不适合直接成为 StateBus benchmark 主线

参考：

- CrewAI hierarchical process  
  https://docs.crewai.com/en/learn/hierarchical-process
- CrewAI concepts / crews / tasks  
  https://docs.crewai.com/en/concepts/crews  
  https://docs.crewai.com/en/concepts/tasks
- CrewAI GitHub README  
  https://github.com/crewAIInc/crewAI

对 StateBus 有用的点：

1. manager 负责 delegation 与 result validation，这和我们想把 validate 语义内收进 Executor 很接近。
2. 它强调 context window 管理、delegation control、max iterations，这些都适合 future runtime gates。

但不适合直接照搬的原因：

1. CrewAI 的层级流程天然会引入一个 manager 角色。
2. StateBus 当前 contest object 是四角色：`Planner / Retriever / Executor / Summarizer`。
3. 如果直接引入 manager，就会把主对象从“四角色协作机制”改成“五角色 manager-led system”。

结论：

> 可借其“delegation + validation + iteration budget”治理思想，  
> 但不要把 StateBus 主线改成 manager-crew 框架演示。

---

## 5. 推荐总架构：固定四节点图 + 四个 LLM 角色 + StateBus carrier

### 5.1 一句话定义

推荐的新主线是：

> **固定图的 4-LLM cooperative graph**

也就是：

- 外层：仍由 LangGraph / Orchestrator 控制固定执行顺序
- 内层：四个节点都是真正的 LLM 语义 agent
- carrier：text lane 与 protocol lane 保持可比
- state/memory：继续由 StateBus 提供

### 5.2 为什么不是完全自由 handoff graph

因为当前最重要的不是“做一个更像 demo 的多 agent 系统”，而是：

1. 保持 benchmark object 稳定
2. 保持 metrics 可归因
3. 保持 single-variable 对照面
4. 给 external baseline 一个对称结构

固定顺序仍然可以是真实 agent：

1. `Planner`
2. `Retriever`
3. `Executor`
4. `Summarizer`

区别只在于：

- 过去中间两层更多是 runtime helper
- 现在中间两层也变成真正基于 prompt/context 做语义决策的 agent

### 5.3 LangGraph 在新路线中的准确定位

LangGraph 在新路线里继续做：

- execution graph
- state propagation
- checkpoint / resume
- debugging / tracing hook
- branch / retry / failure propagation

它**不**成为主方法。

StateBus 的主方法仍是：

- structured control carrier
- typed state transfer
- shared memory / replay
- per-role context projection

---

## 6. 四个角色的新定位

下面是推荐的四角色重新定义。

### 6.1 Planner LLM

#### 新职责

- 理解任务目标
- 生成本次协作的局部计划
- 指定检索目标、约束、输出契约
- 产出给 `Retriever` 的 handoff

#### 不再只是

- YAML plan compiler 的前置包装

#### 输入

- 用户 query / goal
- task-level public contract
- summary contract
- 可选 memory summary
- capability registry 摘要

#### 输出

- `PLAN_PACKET_V2`
- 给 `Retriever` 的 next-step instruction

#### 关键要求

- 不得读取 oracle 字段
- 不直接决定最终 tool
- 可以提出检索 focus、ambiguity checklist、validation need

#### 本地改造含义

- `agents/sample_agents.py:547-553` 的 YAML shortcut 不能再是 headline 主路径默认
- YAML 仍可保留做 deterministic support surface

### 6.2 Retriever LLM

#### 新职责

- 读取 Planner handoff
- 审阅本地检索结果
- 生成 evidence synthesis，而不是直接由 runtime lexical helper 决出 route/tool
- 给出 route hypotheses、candidate tools、uncertainty、需要验证的点
- 产出给 `Executor` 的 handoff

#### 保留的非 LLM基础设施

- 本地 corpus retrieval
- embedding / ranking
- memory lookup
- ranked docs 生成

#### 核心变化

当前 `Retriever` 的 `feature_bundle` 是“系统直接决策”的主来源。

新路线里它应降级为：

- retrieval feature source
- candidate generator
- evidence normalizer

真正的 route/tool 候选解释应由 `Retriever LLM` 完成。

#### 输入

- `PLAN_PACKET_V2`
- top-k ranked docs
- memory hits
- corpus feature hints

#### 输出

- `RETRIEVAL_PACKET_V2`
- bounded evidence claims
- candidate tools with rationale

#### 推荐 packet 字段

- `query_digest`
- `retrieved_doc_ids`
- `evidence_claims`
- `route_hypotheses`
- `candidate_tools`
- `ambiguity_notes`
- `memory_relevance`
- `needs_validation`
- `confidence`

### 6.3 Executor LLM

#### 新职责

- 读取 `Retriever` handoff
- 在候选 route/tool 中做最终动作选择
- 判断是否应 abstain / ask for more evidence / proceed
- 触发真实 playbook 工具执行
- 对结果做第一轮 action-level validation
- 产出给 `Summarizer` 的 handoff

#### 这是整个重构最关键的一层

当前 `Executor` 主要是：

- 消费 `feature_bundle`
- 从 text/protocol 恢复 route/tool
- 执行 playbook

新路线里它必须变成：

> “由 LLM 决定执行什么，由 deterministic tool runtime 执行”

也就是：

- tool execution 仍 deterministic
- tool selection / abstention / validation 变成 LLM 决策

#### 输入

- `RETRIEVAL_PACKET_V2`
- raw evidence refs / bounded projections
- tool catalog
- public action contract

#### 输出

- `EXECUTION_PACKET_V2`
- chosen route/tool
- abstain or proceed
- executed artifact refs
- validation notes

#### 推荐 packet 字段

- `selected_route`
- `selected_tool`
- `selection_rationale`
- `competing_tool_rejected_because`
- `requires_more_evidence`
- `action_contract`
- `tool_artifact_refs`
- `execution_observations`
- `post_action_confidence`

### 6.4 Summarizer LLM

#### 新职责

- 读取 `Executor` handoff
- 结合 evidence / action result 生成最终 summary
- 生成 memory commit candidate
- 生成 replay-friendly compact abstraction

#### 这层保留最多

但要改一件关键事情：

> protocol lane 不能再简单把 typed packet `json.dumps()` 后喂给 summarizer，
> 否则 token 效率不会有结构性提升空间。

新路线里应改为：

- `Summarizer` 消费的是 **role-specific bounded projection**
- raw state 留在 StatePool
- prompt 只拿必要 facts、chosen action、关键 evidence claims、artifact digest

#### 输入

- `EXECUTION_PACKET_V2`
- limited evidence projection
- tool artifact summary
- optional replay/memory context

#### 输出

- `summary`
- `memory_commit`
- `reusable_steps`
- `confidence`

---

## 7. 两条 carrier lane 应该怎么重定义

四个角色都上 LLM 后，真正要公平比较的不是“是否用了 LLM”，而是：

> **LLM 之间如何传协作信息**

### 7.1 Text lane

定义：

- agent 间只传自然语言或轻量 JSON 文本
- 不传 `StateRef`
- 不传 typed packet
- 不传 hidden structured fields
- 接收方只能根据文本 handoff 再理解任务

允许：

- 每个 agent 在本地使用自己的工具与本地检索
- 但 agent 间协作媒介必须是 text-only

不允许：

- 从 runtime 偷看 route/tool oracle
- 从 structured packet 恢复 route/tool
- lexical fallback 代替 LLM decision

### 7.2 Protocol lane

定义：

- 控制面继续用 protobuf / structured step envelope
- 状态面传 `StateRef`
- 角色间显式传 typed packet
- raw evidence、ranked bundle、tool artifact 放 StatePool / store
- LLM prompt 由 runtime 对 typed packet 做 bounded projection

允许：

- receiver 根据 packet 中 machine-readable fields 直接消费 structured state
- receiver 用 state refs 精准取局部上下文

不允许：

- 为了“对比好看”把 protocol lane 的 prompt 也扩成整段冗长自然语言复制品

### 7.3 关键公平性原则

如果四个角色都接 LLM，公平性不再是“都用不用模型”，而是：

1. 同一组 task
2. 同一组工具
3. 同一组 corpus
4. 同一组 LLM 模型
5. 同一组 summary / scoring contract
6. 只有 carrier / state-consumption contract 不同

---

## 8. 为什么这条路线仍然保留 StateBus 的方法身份

这是最重要的边界。

如果只是把四个 agent 都换成 LLM，然后 agent 之间纯文本聊天，那就不是 StateBus 了。

新路线下，StateBus 的身份要靠下面四件事保住：

### 8.1 控制面依旧是结构化协议

即便四个角色都用 LLM：

- step ownership
- semantic role
- handoff target
- validation state
- retry / replay gate

仍由结构化 control plane 管。

### 8.2 数据面依旧是 typed state + StateRef

关键点不是“LLM 能不能直接看 raw text”，而是：

- raw evidence
- ranked docs
- selected candidates
- tool artifacts
- replay certificates

是否仍作为 typed state 被 producer 产出、consumer 选择性读取。

### 8.3 记忆面依旧是显式共享记忆

而不是仅靠长对话历史。

这条路线下 shared memory 更重要，因为：

- 四个 LLM agent 如果都只靠消息历史，会更贵
- protocol lane 的价值应体现在“显式 store + targeted recall”

### 8.4 telemetry / tracing 更强，而不是更弱

四个 LLM 后，更应该按 role 记录：

- planner tokens
- retriever tokens
- executor tokens
- summarizer tokens
- handoff count
- handoff bytes
- state fetch count
- memory read/write count
- route/tool disagreement

这正好强化 StateBus 作为“可观测系统机制”的身份。

---

## 9. 推荐的 packet / handoff 合同

这里给一个足够实现级的建议，不是最终 schema。

### 9.1 `PLAN_PACKET_V2`

用途：

- `Planner -> Retriever`

建议字段：

- `task_id`
- `goal`
- `query`
- `required_output_contract`
- `retrieval_objective`
- `ambiguity_focus`
- `disallowed_oracle_fields`
- `memory_policy`
- `next_agent = retriever`

text lane 表达：

- natural language brief
- 可以带轻量 JSON block

protocol lane 表达：

- typed packet + brief textual projection

### 9.2 `RETRIEVAL_PACKET_V2`

用途：

- `Retriever -> Executor`

建议字段：

- `retrieved_doc_ids`
- `evidence_claims`
- `route_hypotheses`
- `candidate_tools`
- `competing_explanations`
- `missing_information`
- `memory_hint`
- `confidence`
- `next_agent = executor`

### 9.3 `EXECUTION_PACKET_V2`

用途：

- `Executor -> Summarizer`

建议字段：

- `selected_route`
- `selected_tool`
- `selection_rationale`
- `abstain_or_execute`
- `tool_artifact_refs`
- `validation_notes`
- `first_action`
- `confidence`
- `next_agent = summarizer`

### 9.4 `SUMMARY_PACKET_V2`

用途：

- `Summarizer -> final output + memory store`

建议字段：

- `summary`
- `confidence`
- `reusable_steps`
- `memory_commit_kind`
- `retrieval_digest`
- `execution_digest`

### 9.5 新增一个关键概念：`LLM_CONTEXT_SLICE`

这是新路线最值得加的状态种类。

它不是 raw evidence，也不是纯自然语言 message。

它是：

> 某个 producer 为下游某个特定 LLM 角色准备的、受 token 预算约束的局部上下文投影。

例如：

- `Retriever` 产出给 `Executor` 的 600-token bounded context
- `Executor` 产出给 `Summarizer` 的 400-token action digest

这样做的目的：

1. protocol lane 不需要把所有 raw state 重新文本化
2. token 控制有显式预算
3. carrier 的优势可以真正体现在“传 ref + 传 compact slice”

---

## 10. 基线与 benchmark 该怎么跟着升级

这条路线如果只改 StateBus 主线，不改 baseline，还是会失真。

### 10.1 必须同步新建 external pure-text 4-agent baseline

建议对象：

- `external_pure_text_four_llm_baseline_v1`

核心要求：

1. 同四角色：
   - Planner
   - Retriever
   - Executor
   - Summarizer
2. 同模型
3. 同 task
4. 同 corpus
5. 同工具
6. 只允许 text handoff
7. 不允许 StateRef / typed packet / StateBus hidden helper

### 10.2 formal headline 不要直接覆盖旧对象

不要立即替换 `contest_honest_headline_v1`。

建议顺序：

1. 保留旧 frozen headline 作为历史对象
2. 新建四 LLM dual-mode comparator surface
3. 在 repeat=1 / repeat=3 稳定后，再决定是否升格成新 formal headline

### 10.3 新主实验对象建议

建议新增两个 surface：

1. `contest_four_llm_carrier_comparison_v1`
   - StateBus 内部 dual-mode comparator
   - text lane vs protocol lane
   - 同四角色、同图、同任务

2. `external_pure_text_four_llm_baseline_v1`
   - external formal comparator
   - 用于回答“相比传统纯文本多 Agent 协作是否更优”

### 10.4 新指标必须按 role 拆开

当前只有 planner/summarizer token 拆分不够。

新路线建议最少加：

- `planner_total_tokens`
- `retriever_total_tokens`
- `executor_total_tokens`
- `summarizer_total_tokens`
- `llm_total_tokens`
- `handoff_message_count`
- `handoff_text_bytes`
- `state_fetch_count`
- `state_fetch_bytes`
- `memory_lookup_count`
- `memory_write_count`
- `route_exact_rate`
- `tool_exact_rate`
- `abstain_rate`
- `validation_change_rate`

---

## 11. 代码层怎么适配，不推翻现有仓库

下面不是实现承诺，而是推荐拆分方向。

### 11.1 `runtime/llm.py`

当前 roles 主要是：

- `planner`
- `summarizer`

需要扩成：

- `planner`
- `retriever`
- `executor`
- `summarizer`

并允许：

- role-specific model config
- role-specific token budget
- role-specific temperature / structured output setting

### 11.2 `agents/sample_agents.py`

这是主重构点。

建议把现在的逻辑拆成三层：

1. **context assembly**
   - 从 task/state/memory 构造输入
2. **role LLM decision**
   - 真实调用 role prompt
3. **side-effect/runtime adapter**
   - 写 state
   - 调工具
   - 记 telemetry

其中：

- `RetrieverAgent` 不再直接以 `build_feature_bundle()` 的结果作为最终 route/tool 主来源
- `ExecutorAgent` 不再主要依赖 `_feature_bundle_from_*` 恢复 route/tool
- `SummarizerAgent` 不再把 protocol lane 全量 `json.dumps()` 回 prompt

### 11.3 `runtime/executor_runtime.py`

建议降级为：

- tool catalog
- candidate generation helper
- deterministic execution backend
- validation utility

不再承担：

- headline 主路径中的最终 route/tool 决策权

更具体地说：

- `build_feature_bundle()` 继续保留，但定位改成 retrieval features
- `_feature_bundle_from_text_whole_lane_handoff()` 不再是新 formal mainline 的核心
- `select_tool_name()` 不再是 LLM-enabled mainline 的最终 action decider

### 11.4 `protocol/messages.py`

建议新增或扩展：

- `PLAN_PACKET_V2`
- `RETRIEVAL_PACKET_V2`
- `EXECUTION_PACKET_V2`
- `LLM_CONTEXT_SLICE`

不要急着把这些都升到 `.proto` 首层消息类型，也可以先作为 typed state kinds 托管在 StatePool 中。

### 11.5 `runtime/orchestrator.py` 与 `runtime/langgraph_adapter.py`

这里不建议大推翻。

建议保持：

- 外层固定执行顺序
- 可选 validate/repair gate
- tracing / checkpoint / memory side effects

只需要让：

- 每个 node 真正变成 LLM decision node
- step input refs 与 context projection 更细粒度

### 11.6 `tasks/` 与 `eval/`

建议新增而不是覆盖：

- 新 dual-mode 4-LLM surface
- 新 external 4-LLM baseline surface
- 新 role-level metrics

不要动：

- frozen headline 历史包
- 旧 support/audit surface 的语义边界

---

## 12. 迁移阶段建议

### Phase 0：先立对象，不改 headline

目标：

- 文档冻结新对象定义
- 明确新 surface 名称
- 明确 role token 指标

交付：

- 设计文档
- 新对象命名与 reading contract

### Phase 1：把中间两层改成 LLM-capable，但先不替换主 benchmark

目标：

- `Retriever` / `Executor` 支持 API LLM
- 旧 deterministic helper 保留为 fallback/support surface

验收：

- smoke 通
- role-level usage 记录完整

### Phase 2：建立 4-LLM internal dual-mode comparator

目标：

- `contest_four_llm_carrier_comparison_v1`

要求：

- 同图
- 同四角色
- 同任务
- 只改 carrier

### Phase 3：建立 external pure-text 4-agent baseline

目标：

- `external_pure_text_four_llm_baseline_v1`

要求：

- 去掉 lexical fallback
- 去掉 StateBus hidden helper
- text-only inter-agent handoff

### Phase 4：repeat=1 / repeat=3 / targeted repeat=10

目标：

- 先看 object 是否成立
- 再决定是否值得冲 repeat=10 formalization

### Phase 5：决定是否升格新 headline

只有在以下条件同时满足时才考虑升格：

1. comparator 真正 external
2. 四角色都是真 LLM semantic agents
3. text/protocol 都可稳定跑
4. 指标能解释清楚
5. 新对象确实比旧对象更贴近赛题问题

---

## 13. 预期会发生什么变化

### 13.1 很可能变好的

1. **比较对象更自然**
2. **tool disambiguation 可解释性更强**
3. **benchmark 说服力更强**
4. **external baseline 更容易 formal 化**
5. **记忆复用更有机会在多 LLM 体系里体现价值**

### 13.2 很可能先变差的

1. `llm_total_tokens` 上升
2. `task_ms` 上升
3. exact 不一定立刻上升
4. prompt/context bug 会变多

### 13.3 这不应该被看成失败

如果 token 上升但 comparator 终于公平了，那么这是：

> benchmark 真实性上升，
> 不是路线失败。

真正要看的不是“数值先好不好看”，而是：

1. object 是否终于对准赛题主问题
2. protocol 相比 text 是否在更自然的 4-agent 环境里显出优势
3. 如果没有优势，到底是方法问题还是对象问题

---

## 14. 我建议避免的三个误区

### 14.1 误区一：直接上完全自由 swarm

问题：

- benchmark 不稳定
- metrics 难归因
- formal headline 更难收口

### 14.2 误区二：保留现有中间 deterministic 决策，只在外面套 LLM 壳

问题：

- 看起来四个 agent 都是 LLM
- 实际 route/tool 仍由 helper 主导
- 说服力不会真的提升

### 14.3 误区三：四个 LLM 后仍让 protocol lane 全量文本回灌

问题：

- token 结构性优势不会出现
- protocol 只剩 control_bytes 优势
- 新路线白改

---

## 15. 最终建议

如果只选一条主方向，我的建议非常明确：

> **做“固定四节点 + 四个 LLM 角色 + StateBus carrier”的新对象，  
> 并同步做 external pure-text 4-agent baseline。**

更直白一点：

1. 不要继续把主要精力放在修当前“中间 deterministic helper 更聪明”这件事上。
2. 不要直接把系统改成完全自由的 CrewAI/Swarm 风格。
3. 要做的是：**让四个角色都成为真实 semantic agents，但保持 StateBus 的 carrier/state/memory 身份。**

这条路线最符合当前局势：

- 能回应“中间两层非 LLM”的核心担忧
- 能回应“external baseline 不自然”的核心缺口
- 不会把 StateBus 方法彻底冲掉
- 还能保留 LangGraph / Orchestrator / StatePool / MemoryStore 的已有资产

---

## 16. 下一步建议

下一步不应该立刻写大量代码。

建议顺序：

1. 先把新对象和新 fairness contract 写成实施计划
2. 明确新 surface 名称、packet 草案、metrics 草案
3. 先做一个最小 4-LLM det smoke
4. 再做 API repeat=1 internal comparator
5. 再做 API repeat=1 external comparator
6. 只有 object 成立后才考虑 repeat=10

建议测试环境仍使用：

```bash
source deploy/activate_statebus_host.sh
```

---

## 17. 本文引用的本地关键文件

- `agents/sample_agents.py`
- `runtime/executor_runtime.py`
- `runtime/langgraph_adapter.py`
- `runtime/orchestrator.py`
- `runtime/llm.py`
- `protocol/messages.py`
- `tasks/sample_tasks.py`
- `eval/text_open_baseline.py`
- `docs/reports/architecture_and_data_flow.md`
- `docs/constraints/current_feature_scope.md`
- `docs/planning/implementation_plan.md`
- `docs/analysis/statebus_external_pure_text_baseline_contract_20260620.md`
- `docs/analysis/statebus_independent_followup_deep_diagnosis_20260620.md`

---

## 18. 本文参考的外部资料

- LangChain multi-agent overview  
  https://docs.langchain.com/oss/python/langchain/multi-agent
- LangChain handoffs  
  https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs
- LangChain subagents  
  https://docs.langchain.com/oss/python/langchain/multi-agent/subagents
- LangGraph workflows and agents  
  https://docs.langchain.com/oss/python/langgraph/workflows-agents
- LangChain context overview  
  https://docs.langchain.com/oss/python/concepts/context
- LangChain memory overview  
  https://docs.langchain.com/oss/python/concepts/memory
- `langgraph-supervisor-py`  
  https://github.com/langchain-ai/langgraph-supervisor-py
- AutoGen handoffs  
  https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/design-patterns/handoffs.html
- AutoGen swarm  
  https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/swarm.html
- OpenAI Swarm  
  https://github.com/openai/swarm
- OpenAI Agents SDK orchestration  
  https://openai.github.io/openai-agents-python/multi_agent/
- OpenAI Agents SDK handoffs  
  https://openai.github.io/openai-agents-python/handoffs/
- OpenAI Agents SDK tracing  
  https://openai.github.io/openai-agents-python/tracing/
- OpenAI realtime sequential handoff example  
  https://github.com/openai/openai-realtime-agents
- CrewAI hierarchical process  
  https://docs.crewai.com/en/learn/hierarchical-process
- CrewAI README  
  https://github.com/crewAIInc/crewAI
