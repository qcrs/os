# StateBus 赛题对象、Benchmark 与机制设计计划

日期：`2026-06-10`

适用范围：这份文档服务当前 `/home/qcrs/statebus/project` 的后续方向判断。

它不是当前实现事实报告，也不是新的 benchmark 结果页。  
如果要按多轮方式推进当前 host-mainline 修改，请配合阅读：

- `docs/planning/host_mainline_authenticity_execution_plan_20260610.md`

它回答的是更上层的问题：

1. 赛题到底在要求什么对象
2. 这个对象更适合做受控系统还是开放系统
3. benchmark 应该如何设置才不误读
4. 结构化协议、非文本状态传递、共享记忆怎样做出亮点
5. 本地 `third_party/` 和 GitHub 上有哪些仓库值得借什么，不该借什么

首先对齐权威源：

- 赛题考的是
  - `低开销通信`
  - `非文本状态传递`
  - `共享记忆复用`
  - 以及相对纯文本协作的 `可复现实验验证`
- 赛题明确说自己
  - `区别于一般工作流编排类题目`
  - 重点在 `系统层机制`
  - 不是单纯做一个会调工具的 agent demo

本文件主要依据：

- `docs/reference/题目.md`
- `third_party/langgraph/README.md`
- `third_party/langgraph-bigtool/README.md`
- `third_party/semantic-router/README.md`
- `third_party/haystack/README.md`
- `third_party/memsearch/README.md`
- `third_party/AgentRx/README.md`
- `third_party/evals/README.md`
- GitHub 官方仓库：
  - `https://github.com/langchain-ai/langgraph`
  - `https://github.com/langchain-ai/langgraph-bigtool`
  - `https://github.com/aurelio-labs/semantic-router`
  - `https://github.com/deepset-ai/haystack`
  - `https://github.com/zilliztech/memsearch`
  - `https://github.com/microsoft/AgentRx`
  - `https://github.com/openai/evals`
  - `https://github.com/sierra-research/tau-bench`
  - `https://github.com/xlang-ai/OSWorld`
  - `https://github.com/web-arena-x/webarena`

---

## 1. 赛题对象到底是什么

### 1.1 不是开放域 agent 平台赛

题目并没有要求：

- 开放世界泛化
- 无边界工具生态
- 自由规划到任意任务
- computer-use 或 browser-use 终态
- hidden-state / KV 传递主路径

题目真正强制的是：

1. 至少 3 个 agent 和多角色协作
2. 结构化通信替代长文本透传
3. `text` / `protocol` 双模式对照
4. 一种真实可消费的非文本中间状态
5. 共享记忆的存储、检索、复用
6. 至少 2 组连续关联任务
7. 可复现实验与 10 轮稳定运行
8. 最终 openEuler 可运行交付

所以更准确的对象不是：

> “做一个尽量开放的多智能体平台”

而是：

> “做一个可复现实验的多智能体系统机制原型”

### 1.2 也不是纯脚本工作流赛

题目又明确排除了“只是编排工作流”。

这意味着系统不能退化成：

- 固定 DAG 的纯脚本流水线
- 每个 step 都没有实质决策
- 所有中间状态都只是预填字段
- memory 只是缓存一个最终答案

### 1.3 最合理的对象定义

最合理的对象是：

> 受控但不造假的多 agent 机制验证系统

这里的“受控”指：

- 任务域有边界
- 工具集有边界
- 证据库有边界
- benchmark pack 有边界

这里的“不造假”指：

- Retriever 真的要在候选中做选择
- Executor 真的要在候选动作中做选择
- Memory 真的要在后续任务中发挥作用
- 非文本状态真的被下游消费
- benchmark 对照只改被测机制，不偷改其他条件

### 1.4 我建议的任务对象

如果抛开当前代码重新定义，我最推荐的对象不是开放办公助手，而是：

> 证据驱动的技术调查/诊断任务族

例如：

- 日志/配置/文档联合排障
- 服务 incident triage 与 follow-up
- repo 内技术审计与修复建议
- 受限工具下的知识调查与执行建议

原因：

1. 天然适合 `Planner / Retriever / Executor / Summarizer`
2. 天然会产生证据候选、route 特征、工具候选
3. 天然适合非文本中间状态
4. 天然适合“连续关联任务”
5. 天然适合 memory 的 assist 和 replay 两条线
6. 比 computer-use 更可控，比纯 QA 更像系统协作

---

## 2. 受控还是开放

### 2.1 赛题没有要求开放

题面没有任何地方要求：

- open-ended web
- general desktop use
- open-world browsing
- 任意工具链

它要求的是“复杂任务”和“多 agent 协作”，但复杂不等于开放。

### 2.2 为什么 formal benchmark 应该受控

formal benchmark 的主要目标不是证明世界知识或环境泛化，
而是隔离三条机制 claim：

1. communication
2. state transfer
3. memory reuse

如果一开始就用开放环境：

- 环境噪声会压过协议收益
- 工具失败会掩盖 memory 效果
- 任务漂移会破坏可复现对照
- 10 轮稳定执行成本会暴涨

所以 formal 主线应该是：

> 受控任务族 + 真实机制不确定性 + 可重复实验

### 2.3 开放 benchmark 还有没有价值

有，但不应是 formal headline。

更合理的定位是：

- `support-only open validation`
- 证明系统不是只能在最窄脚手架里跑
- 暴露 failure mode
- 补充 trajectory 诊断材料

所以：

- `formal controlled pack` 用来支撑赛题主 claim
- `open validation pack` 用来说明边界，不用来抢 headline

---

## 3. benchmark 应该怎么设置

## 3.1 benchmark 总原则

### 原则 1：按 claim lane 拆，不看单一总分

至少拆成四层：

1. `communication lane`
2. `state_transfer lane`
3. `memory lane`
4. `support-only open validation`

如果只做一个 aggregate 总分表，评审很容易误读：

- 把协议收益读成 memory 收益
- 把 replay 收益读成一般 memory intelligence
- 把环境差异读成机制差异

### 原则 2：同任务、同模型、同工具、同证据，只改一个被测因素

每个 lane 的 baseline 必须只改一件事。

### 原则 3：成功率先守住，再谈效率

如果结构化协议省 token，但任务正确率掉了，就不能算有效收益。

### 原则 4：稳定性和正式性能证据要分开

- deterministic repeat run：
  - 用于控制平面稳定性
  - 用于解析/调度/复用路径验证
- serialized real API run：
  - 用于 token、bytes、latency 正式证据

deterministic 不能拿来冒充 token 证据。

## 3.2 推荐的 benchmark pack 结构

### A. Formal Controlled Pack

用途：

- 正式支撑赛题主 claim

要求：

- 任务域固定
- 工具集固定
- 证据库固定
- 连续任务关系固定
- 读者合同固定

建议包含：

1. `2-3` 个任务组
2. 每组 `4-6` 个连续任务
3. 总任务数 `12-18`
4. 每轮完整跑一次 pack
5. 正式串行 API `repeat >= 10`

推荐任务组形态：

1. `initial triage`
2. `near-duplicate follow-up`
3. `confounded variant`
4. `post-action summary`

这能同时覆盖：

- 检索
- 执行
- 总结
- 复用

### B. Open Validation Pack

用途：

- 暴露边界
- 做失效诊断
- 证明系统不是完全靠最窄脚手架

可以包含：

- 更弱 hint
- 更混杂证据集
- 更模糊任务表述
- 更高歧义工具选择

它不应用来：

- 直接产出 headline
- 替代 formal repeat-10

## 3.3 lane 级别的具体对照

### communication lane

目标：

- 证明结构化协议相对纯文本协作降低通信与解析开销

唯一变化：

- `mode = text` vs `mode = protocol`

必须固定：

- 同任务
- 同模型
- 同工具
- 同 memory policy
- 同 state transfer policy

推荐设置：

- baseline:
  - `text + text_brief_handoff + memory_off`
- compare:
  - `protocol + text_brief_handoff + memory_off`

为什么 state transfer 先固定成 `text_brief_handoff`：

- 否则会把非文本状态收益混进通信 lane

输出指标：

- task success rate
- control-plane bytes
- llm total tokens
- agent message count
- end-to-end latency
- parse / dispatch latency

### state_transfer lane

目标：

- 证明非文本状态传递本身有价值

唯一变化：

- `handoff = text_brief` vs `handoff = state_ref`

必须固定：

- 都走 `protocol`
- 同 memory policy
- 同任务
- 同工具

推荐设置：

- baseline:
  - `protocol + text_brief_handoff + memory_off`
- compare:
  - `protocol + state_ref_handoff + memory_off`

输出指标：

- success rate
- handoff_nontext_count
- handoff_nontext_bytes
- downstream_redecode_count
- repeated_evidence_fetch_count
- tool_call_count
- end-to-end latency

关键解释：

- 如果只是多出一份二进制 blob，但下游仍回去读全文，那不算有效 state transfer

### memory lane

目标：

- 拆清 assist 和 replay

必须分成两条子线，不要混成一条：

1. `memory_assist lane`
2. `memory_replay lane`

#### memory_assist lane

唯一变化：

- `memory_off` vs `assist_only`

固定：

- `protocol + state_ref_handoff`
- 同任务组

输出指标：

- success rate
- retrieval_docs_examined
- tool_call_count
- repeated_fetch_reduction
- latency
- memory_hit_rate

claim 门槛：

- assist 如果不能减少重复检索、重复执行、或提升成功率，
  就不应被包装成主收益 headline

#### memory_replay lane

唯一变化：

- `assist_only` vs `replay_enabled`

固定：

- `protocol + state_ref_handoff`

输出指标：

- success rate
- skipped_step_count
- reuse_gain
- exact_replay_precision
- replay_misfire_count
- end-to-end latency

claim 边界：

- 这条线必须明确写成 `replay / validated step-skipping gain`
- 不能偷换成“广义 memory intelligence”

## 3.4 benchmark 运行矩阵

建议正式矩阵如下：

| Layer | Mode | Handoff | Memory | LLM mode | Repeat | 用途 |
|---|---|---|---|---|---:|---|
| Stability | text | text_brief | off | deterministic | 10 | 验证 text 路径稳定 |
| Stability | protocol | text_brief | off | deterministic | 10 | 验证 protocol 路径稳定 |
| Stability | protocol | state_ref | replay_enabled | deterministic | 10 | 验证完整主路径稳定 |
| Formal communication | text vs protocol | text_brief | off | api_serial | 10 | 正式通信 claim |
| Formal state transfer | protocol | text_brief vs state_ref | off | api_serial | 10 | 正式状态传递 claim |
| Formal memory assist | protocol | state_ref | off vs assist_only | api_serial | 10 | 正式 assist claim |
| Formal memory replay | protocol | state_ref | assist_only vs replay_enabled | api_serial | 10 | 正式 replay claim |
| Support open validation | mixed | mixed | mixed | api_serial | 1-3 | 边界诊断 |

## 3.5 benchmark 的读者合同

每个 report 顶部应显式写：

1. `task_set_name`
2. `task_pack_type`
3. `support_evidence_only`
4. `claim_lane`
5. `what changed`
6. `what was fixed`
7. `what must not be concluded`

这是从 `third_party/evals` 最值得借的点：

- eval object identity
- report-level reading contract

## 3.6 benchmark 中最容易出错的地方

1. 把 `text` baseline 写得过弱  
   只要 text baseline 退化成“又长又乱的自然语言对话”，通信优势就会被质疑。

2. 在 lane 对照时偷偷改任务条件  
   例如 protocol 模式少检索一次、或用不同证据 hint。

3. 把 replay gain 混成 memory gain  
   replay 是有效收益，但不是全部 memory 价值。

4. 用开放环境结果直接讲 formal claim  
   OSWorld / WebArena 这类环境适合 support，不适合当前赛题 formal 主线。

---

## 4. 结构化协议怎样做出亮点

## 4.1 只上 JSON 或 Protobuf 不够

很多框架都有 JSON、function calling、tool call schema。  
单靠“我们也有结构化字段”没有亮点。

真正的亮点不在编码格式，而在：

1. 控制面和数据面分离
2. 能力协商和协议映射
3. 重状态不内联，只传引用
4. 每个 step 都有可审计 provenance
5. 下游 agent 明确声明消费什么状态

## 4.2 推荐的协议分层

### 控制面

只传：

- action type
- step id
- input args
- output summary
- capability
- confidence
- provenance refs

推荐对象：

- `Hello`
- `Capability`
- `TaskEnvelope`
- `PlanFrame`
- `StepRequest`
- `StepResult`
- `StateRef`
- `MemoryQuery`
- `MemoryHit`
- `MemoryCommit`
- `Ack`
- `Error`

### 数据面

不直接走长文本，走：

- `mmap`
- `shared_memory`
- file-backed blob
- sidecar state store

### 记忆面

独立于当前 step response：

- memory write
- memory search
- replay candidate lookup

## 4.3 协议真正该展示的创新点

### 创新点 1：typed handoff contract

不是“我传了一个状态引用”，而是：

- 这个状态的类型是什么
- 谁生成的
- 谁能消费
- 生命周期是什么
- 下游用它做什么

### 创新点 2：capability-aware dispatch

不是 runtime 一厢情愿调度，而是 agent 声明：

- 可接收哪些状态类型
- 可执行哪些 action
- 可复用哪些 memory 类型

### 创新点 3：compact semantic control plane

控制帧里只保留高密度语义单元：

- route
- intent
- candidate ids
- evidence refs
- confidence
- memory refs

不要把证据正文重新塞回控制帧。

### 创新点 4：failure surface 可审计

协议应让失败被明确分类：

- no_match
- low_confidence
- missing_evidence
- invalid_tool_args
- replay_rejected

这比“最后输出错了”更像系统层对象。

---

## 5. 非文本中间状态怎样做出亮点

## 5.1 什么算真的非文本状态

满足下面四条才算：

1. 上游 agent 真实生成
2. 经独立通道传递
3. 下游不必还原全文就能消费
4. 这个消费行为影响后续决策或执行

不算的例子：

- 文本内容 gzip 一下再传
- 把一段说明塞进 JSON blob
- 传一个 state id，但下游马上去读原文全文

## 5.2 最推荐的非文本状态对象

### A. RankedEvidenceBundle

由 Retriever 生成，供 Executor 消费。

内容建议：

- ranked `doc_ids`
- dense scores
- lexical scores
- tag overlaps
- top evidence spans offsets
- route candidates
- retrieval confidence

价值：

- Executor 不必重新读完整证据库
- state_transfer lane 容易单独测

### B. ToolCandidateSet

由 Retriever 或 pre-executor 生成，供 Executor 消费。

内容建议：

- candidate tool ids
- tool scores
- abstain threshold
- disambiguation flags

价值：

- 把“先缩小候选，再执行”做成显式对象
- 这是从 `langgraph-bigtool` 和 `semantic-router` 最值得借的结构

### C. ExecutionArtifactRef

由 Executor 生成，供 Summarizer 或 MemoryWriter 消费。

内容建议：

- normalized tool outputs
- affected entities
- action status
- machine-readable result table

价值：

- Summarizer 不必从原始日志重新抽取
- memory 可以直接写 structured outcome

### D. ReplayEligibilityBundle

由 Memory 检索层生成，供 Orchestrator/Executor 决策。

内容建议：

- memory candidate ids
- similarity
- route signature
- provenance signature
- validation status
- replayable step ids

价值：

- replay gain 被写成显式系统对象
- 不会和 assist 模糊混在一起

## 5.3 生成、传递、接收、使用的完整链条

这条链必须在文档和 report 中写清楚：

1. 谁生成  
   例如 Retriever 生成 `RankedEvidenceBundle`

2. 如何传递  
   例如 `StateRef` 指向 file-backed statepool object

3. 谁接收  
   例如 Executor 声明支持 `RankedEvidenceBundle`

4. 如何消费  
   例如 Executor 只读取 top-k docs 和 candidate tools，不再全文重解码

5. 如何统计  
   例如 handoff count、bytes、downstream reuse count

## 5.4 为什么这条线能有亮点

很多框架有 memory，有 tool call，有 graph。  
但真正把“可消费的中间表示”定义得足够清楚的不多。

亮点不在于说“我们也有 embedding”，而在于：

- embedding 只是一部分
- 真正交付的是一套带 provenance 的状态对象族
- 且每个对象都对应明确 consumer

---

## 6. 共享记忆怎样做出亮点

## 6.1 不要把 memory 只理解成“历史聊天记录”

赛题里真正值得做的 memory 至少分四类：

1. `evidence memory`
2. `outcome memory`
3. `strategy memory`
4. `validated replay memory`

### evidence memory

- 哪些证据组合曾经有用
- 哪些 route 特征支持过某类判断

### outcome memory

- 某类任务最终结论
- 某类工具执行后的结构化结果

### strategy memory

- 哪类任务适合先查什么再做什么
- 哪类歧义需要先补证据

### validated replay memory

- 在严格前提下允许复用的历史 step 输出

## 6.2 推荐的 memory unit 结构

基本字段：

- `memory_id`
- `memory_type`
- `source_agent`
- `created_at`
- `task_theme`
- `task_group`
- `summary`

增强字段：

- `provenance_refs`
- `route_signature`
- `tool_signature`
- `state_fingerprint`
- `replay_scope`
- `validation_status`
- `reuse_count`

## 6.3 推荐的 memory 检索流程

### assist path

1. semantic retrieval
2. lexical retrieval
3. tag / metadata filter
4. candidate pool fusion
5. rerank
6. return compact assist set

这里最值得借 `memsearch` 的不是它的整套 infra，
而是：

> multi-signal retrieval -> candidate pool -> rerank

### replay path

1. retrieve replay candidates
2. validate provenance / route / tool compatibility
3. validate current task constraints
4. only then allow skip / prune

## 6.4 memory 的亮点不应只靠“向量库”

SQLite + FAISS、Milvus、Qdrant 都不是亮点本身。  
亮点应该在：

1. memory unit taxonomy
2. assist 和 replay 分流
3. provenance-aware retrieval
4. validated replay contract
5. replay misfire 可审计

## 6.5 memory 的 formal claim 应怎么说

最稳妥的说法应该分三层：

1. `memory retrieval works`
2. `assist may reduce repeated retrieval or improve robustness`
3. `validated replay reduces repeated execution via step-skipping`

不要直接跳成：

> memory 让系统更聪明

---

## 7. 怎样做出“很多框架都有，但我们仍然有亮点”

## 7.1 不要和成熟框架拼“大而全”

LangGraph、Haystack 这类框架已经很成熟。  
如果你试图在短期内做一个更大更通用的框架，几乎没有胜算。

### 正确方向

做出一个：

- object 清楚
- benchmark 清楚
- claim 边界清楚
- 协议/状态/memory 三面联动清楚

的系统机制原型。

## 7.2 推荐的亮点组合

### 亮点 A：三面分层

- control plane
- data plane
- memory plane

而不是把所有东西都塞进一个 agent graph。

### 亮点 B：state object family

不是一个笼统的 “embedding handoff”，而是多种 typed state：

- evidence bundle
- tool candidate set
- execution artifact
- replay eligibility bundle

### 亮点 C：abstain discipline

从 `semantic-router` 借阈值纪律：

- no_match
- low_confidence_abstain
- ambiguous_candidates_abstain

这会让系统更诚实。

### 亮点 D：tool retrieval before tool execution

从 `langgraph-bigtool` 借：

> first retrieve a small candidate set, then decide inside that set

这比“给 executor 暴露全部工具”更像系统机制。

### 亮点 E：memory assist vs replay split

很多系统把两者混在一起。  
如果这里能显式分离，并单独 benchmark，会更有说服力。

### 亮点 F：trajectory-level diagnosis

从 `AgentRx` 借：

- trajectory IR
- invariant-like checks
- failure localization

不一定要做全套 judge pipeline，  
但至少要让：

- replay misfire
- wrong tool choice
- low-confidence false execution

变得可定位。

### 亮点 G：report reading contract

从 `openai/evals` 和当前 benchmark split 思路借：

- 每个 benchmark object 都有身份
- 每个 report 都写清楚能说明什么
- formal 和 support 不混写

---

## 8. 本地 `third_party/` 仓库值得借什么

## 8.1 `third_party/langgraph`

仓库：

- `https://github.com/langchain-ai/langgraph`

最值得借：

1. durable execution
2. checkpoint / persistence 观念
3. short-term state 和 long-term memory 分离
4. 长流程可观测性

不该借：

1. 用 LangGraph 替换当前 runtime 主骨架
2. 把当前问题改写成“图框架选型问题”

适合 StateBus 的方式：

- 借状态图和 checkpoint 思路
- 不把 StateBus 退化成 LangGraph wrapper

## 8.2 `third_party/langgraph-bigtool`

仓库：

- `https://github.com/langchain-ai/langgraph-bigtool`

最值得借：

1. tool metadata indexing
2. retrieve small tool set first
3. 可自定义 tool retrieval logic

不该借：

1. 为了“很多工具”而先扩工具数量
2. 为了 bigtool 把 runtime 改写成 LangGraph agent

最适合借的具体结构：

> small candidate tool set -> executor decision

## 8.3 `third_party/semantic-router`

仓库：

- `https://github.com/aurelio-labs/semantic-router`

最值得借：

1. route layer
2. threshold optimization
3. no-match discipline
4. hybrid / local route 思路

不该借：

1. 把全部 routing 外包成新框架
2. 用 route 分数替代所有解释

最适合借的具体结构：

> route may fail; below threshold should abstain

## 8.4 `third_party/haystack`

仓库：

- `https://github.com/deepset-ai/haystack`

最值得借：

1. retrieval / routing / memory / generation 显式分节点
2. pipeline 透明性
3. 可插拔组件观念

不该借：

1. 以重生态替换当前 host-mainline
2. 为 contest prototype 引入过重部署复杂度

最适合借的具体结构：

> explicit and traceable pipeline stages

## 8.5 `third_party/memsearch`

仓库：

- `https://github.com/zilliztech/memsearch`

最值得借：

1. progressive retrieval
2. hybrid retrieval
3. source-of-truth 与 shadow index 分离
4. dedup / sync 思路

不该借：

1. 整套跨平台插件体系
2. Docker/Milvus 等额外复杂度作为当前主线

最适合借的具体结构：

> semantic + lexical + metadata -> candidate pool -> rerank

## 8.6 `third_party/AgentRx`

仓库：

- `https://github.com/microsoft/AgentRx`

最值得借：

1. trajectory IR
2. invariant-like failure checks
3. critical failure step localization
4. grounded error taxonomy

不该借：

1. 把当前主线变成重型诊断平台建设
2. 在主路径前面插入全套 judge pipeline

最适合借的具体结构：

> trajectory normalization + localized failure report

## 8.7 `third_party/evals`

仓库：

- `https://github.com/openai/evals`

最值得借：

1. eval object identity
2. custom eval packaging
3. report contract

不该借：

1. 直接替换当前 `eval.runner`
2. 引入外部 registry 作为当前主线依赖

---

## 9. GitHub 上值得额外参考的 benchmark 仓库

## 9.1 `tau-bench`

仓库：

- `https://github.com/sierra-research/tau-bench`

为什么值得看：

1. 它更接近“结构化 API + 对话式任务 + 工具调用”的 formal benchmark
2. 它有 pass@k 风格结果表
3. 它包含历史 trajectory
4. 它还提供 auto error identification 脚本

最适合借：

1. 结构化任务集的 formal benchmark 气质
2. 历史 trajectory 的保留方式
3. 失败分析不只看 final answer

不该直接照搬：

1. 用户模拟器形态
2. 具体业务域
3. 其完整 evaluation harness

## 9.2 `OSWorld`

仓库：

- `https://github.com/xlang-ai/OSWorld`

为什么值得看：

1. 它代表开放 computer-use benchmark
2. 有强环境依赖和并行评测基础设施
3. 很适合说明“开放环境为什么不是当前 formal 主线”

最适合借：

1. open validation 的定位
2. environment-heavy benchmark 的 artifact 组织方式
3. 任务结果与 trajectory 保留方式

不该照搬：

1. VM / Docker / KVM 复杂环境作为赛题当前主对象
2. multimodal desktop benchmark 作为 formal controlled pack

## 9.3 `WebArena`

仓库：

- `https://github.com/web-arena-x/webarena`

为什么值得看：

1. 它代表 self-hostable web agent benchmark
2. 强调环境重置、可重复实验、trajectory 保存
3. 能帮助理解开放 web benchmark 的成本和噪声

最适合借：

1. environment reset 和 reproducibility 观念
2. trajectory artifact 组织
3. open validation benchmark 的外层形式

不该照搬：

1. browser environment 作为当前赛题 formal 主对象
2. web benchmark 的环境噪声进入主 claim

---

## 10. 推荐实现路线

## 10.1 只推荐这一条主路线

> 自研 host-side runtime + selective borrowing

也就是：

- 自己定义 runtime/orchestrator
- 自己定义 protocol schema
- 自己定义 state object family
- 自己定义 memory taxonomy 和 replay contract
- 从第三方仓库只借机制，不借主框架

### 不推荐的路线

#### 不推荐路线 A：LangGraph/Haystack 直接当主框架

问题：

1. 会把核心问题变成框架迁移
2. 会稀释赛题自己的系统机制表达
3. benchmark 会更难解释“收益来自哪里”

#### 不推荐路线 B：先做开放 computer-use 或 web-use

问题：

1. 复杂度过高
2. formal claim 难以隔离
3. 不利于 repeat-10 稳定证明

#### 不推荐路线 C：先冲 hidden-state / KV / CodeAct 主路径

问题：

1. 赛题鼓励，但不强制
2. 风险大
3. 容易把主线从 requirement closure 拉偏

## 10.2 鼓励项的用途与接入优先级

题目鼓励的这些系统技术，不应被理解成“都要现在接入主线”，而应理解成：

> 它们是可选增强手段，用来提升实现质量、系统味道和后续答辩说服力。

最关键的判断是：

- `IPC / Socket / shared_memory`
  - 直接服务赛题三条主 claim
  - 应进入当前主线
- `向量数据库`
  - 是 retrieval / memory 基础设施
  - 应作为主线底座，但不必追重型方案
- `CodeAct / 轻量沙箱`
  - 是 executor 增强项
  - 适合后续接入，不应先抢主路径
- `eBPF`
  - 是系统观测增强项
  - 最后接最合理

### 10.2.1 逐项用途表

| 技术 | 一般用在什么地方 | 对应 StateBus 哪一层 | 当前是否建议进入主线 | 理由 |
|---|---|---|---|---|
| `IPC` | 本机多进程组件之间的消息交换 | runtime / protocol | 是 | 最贴近 `communication lane` |
| `Socket` | orchestrator 与 agent / executor 的控制面通信，尤其 `AF_UNIX/UDS` | runtime / protocol | 是 | 简洁、可测、宿主机友好 |
| `共享内存` | 大块中间状态传递，避免重复文本化 | state transfer / statepool | 是 | 最贴近 `state_transfer lane` |
| `向量数据库` | corpus 检索、memory 检索、候选召回 | retrieval / memory | 是，但轻量优先 | 是基础设施，不是 headline |
| `WASM` | 受限代码执行、小工具执行隔离 | executor / sandbox | 暂不优先 | 有价值，但当前集成成本偏高 |
| `容器沙箱` | 不可信代码执行隔离、环境封装 | executor / deploy | 暂不优先 | 当前 host-mainline 不该先转容器化 |
| `eBPF` | syscall / I/O / CPU / 网络 / 延迟观测 | observability / diagnostics | 后续再接 | 适合增强“系统味道”，不影响 requirement closure |
| `CodeAct` | 让 LLM 生成 Python 执行真实小任务 | executor | 后续接入 side path | 是鼓励项，不必先做主路径 |

### 10.2.2 每一项更具体该怎么理解

#### `IPC / Socket`

最常见用途：

1. orchestrator 和 remote executor 之间的控制帧传输
2. agent worker 之间的本机通信
3. 本机 capability handshake / step dispatch / result return

为什么适合先进主线：

1. 直接服务结构化通信
2. 能真实测 bytes / messages / latency
3. 不会把系统复杂度一下拉爆

建议：

- 正式主线优先 `AF_UNIX/UDS`
- 不必为了“看起来系统”而一开始上分布式网络栈

#### `共享内存`

最常见用途：

1. 传递大块检索候选
2. 传递特征包、向量、执行产物
3. 避免 `内部状态 -> 文本 -> 内部状态` 的重复往返

为什么最贴题：

- 它就是赛题里“非文本中间状态传递”的最自然系统实现之一

建议：

- 先做 `file-backed mmap`
- 再做 `shared_memory`
- 都通过 `StateRef` 暴露

#### `向量数据库`

最常见用途：

1. retrieval 召回
2. memory semantic search
3. replay candidate retrieval

为什么它要进主线，但不应被包装成亮点：

1. memory / retrieval 没有语义检索很难做扎实
2. 但“用了向量库”本身不是创新

建议：

- 当前优先轻量、可控、宿主机友好的方案
- 例如 `SQLite + FAISS`、本地 shadow index
- 不必为赛题主线先上重型独立服务

#### `WASM / 容器沙箱`

最常见用途：

1. 跑不可信代码
2. 做 CodeAct 隔离执行
3. 限制文件系统、网络和进程能力

为什么不建议现在先进主线：

1. 它们服务的是 executor 安全增强，不是当前三条主 claim 的最短路径
2. 接入成本高，容易把主线带去部署/隔离工程
3. 当前 formal benchmark 先不需要这么重的执行环境

建议：

- 把它们留给 `CodeAct side path`
- 先做轻量 subprocess / restricted runtime
- 需要更强隔离时再上容器或 WASM

#### `eBPF`

最常见用途：

1. 观测 syscall / 文件访问 / socket 行为
2. 定位 executor 或 retrieval 的延迟热点
3. 为答辩提供系统级观测证据

为什么值得做，但应该很后：

1. 它增强解释力
2. 但不直接决定赛题 requirement 是否闭环

建议：

- formal benchmark 跑稳以后再补
- 更适合做 observability artifact，而不是主路径依赖

#### `CodeAct`

最常见用途：

1. 动态生成小段 Python 进行计算
2. 做数据清洗、规则检查、格式转换
3. 当固定工具不够时作为受控兜底执行能力

为什么不该一开始就做默认主路径：

1. 题目鼓励，但不强制
2. 会明显增加不稳定性和调试成本
3. 会模糊“系统机制收益”和“生成代码碰巧做对了”之间的边界

建议：

- 先做固定工具优先
- 再补一个窄范围 `CodeAct side path`
- 只允许少数白名单库和受限文件系统

### 10.2.3 推荐接入顺序

如果只给一个明确优先级，我建议：

1. `UDS / IPC / structured protocol`
2. `mmap / shared_memory / StateRef`
3. `vector-backed retrieval and memory`
4. `CodeAct side path + lightweight sandbox`
5. `eBPF observability`
6. `WASM / container sandbox hardening`

这条顺序的核心逻辑是：

- 先完成赛题主对象
- 再补执行增强
- 最后补系统观测和更强隔离

### 10.2.4 对主线与加分项的最终划分

当前应视为主线的：

1. `IPC / Socket`
2. `shared_memory / mmap`
3. `vector retrieval / memory`

当前应视为后续增强的：

1. `CodeAct`
2. `lightweight sandbox`
3. `eBPF`
4. `WASM / container isolation`

一句话判断：

> 最贴题、最该先进主线的是 `Socket/IPC + shared_memory + retrieval/memory index`；最适合作为后续加分项的是 `CodeAct + sandbox + eBPF`。

## 10.3 分阶段实现计划

### Phase A：对象冻结

产出：

1. 正式任务对象定义
2. formal controlled pack 任务清单
3. open validation pack 任务清单
4. claim lane 定义

退出条件：

- benchmark 读者合同已写清

### Phase B：协议和运行时

产出：

1. text / protocol 双模式
2. capability handshake
3. step-level telemetry
4. compact control frames

退出条件：

- communication lane 可运行

### Phase C：非文本状态

产出：

1. `RankedEvidenceBundle`
2. `ToolCandidateSet`
3. `ExecutionArtifactRef`
4. typed state consumer contract

退出条件：

- state_transfer lane 可运行

### Phase D：memory

产出：

1. memory unit taxonomy
2. assist retrieval path
3. replay eligibility path
4. replay diagnostics

退出条件：

- memory lane 可运行

### Phase E：formal benchmark

产出：

1. deterministic repeat-10 stability packs
2. serialized API repeat-10 formal packs
3. report reading contract
4. compare CSV / markdown reports

退出条件：

- communication / state_transfer / memory 三条 formal lane 全部有独立证据

### Phase F：support-only deepening

可选：

1. open validation
2. stronger sandbox analysis
3. CodeAct side path
4. richer trajectory diagnosis

---

## 11. 最应该避免的几件事

1. 把赛题解释成开放 agent 平台赛
2. 把当前主线变成 LangGraph/Haystack 框架迁移
3. 把 JSON/Protobuf 本身包装成亮点
4. 把“有 embedding”包装成真实 state transfer
5. 把 replay gain 包装成广义 memory intelligence
6. 把 OSWorld/WebArena 这类开放 benchmark 拉进 formal headline
7. 在 benchmark 对照里偷偷改任务条件
8. 只做 aggregate 总表，不拆 claim lane

---

## 12. 最终建议

一句话结论：

> 这题最合理的做法不是追求开放，而是做一个受控但诚实的系统机制原型；不是把大框架搬进来，而是自己掌控 runtime/protocol/state/memory，再从成熟仓库借小而关键的机制；benchmark 必须按 `communication / state_transfer / memory` 三条 lane 分开，开放环境只做 support-only validation。

如果后续只保留一个实现方向，我建议固定为：

1. 对象：
   - 证据驱动的技术调查/诊断任务族
2. runtime：
   - 自研 host-side orchestrator
3. protocol：
   - typed control plane + sideband state refs
4. non-text state：
   - evidence/tool/replay 三类对象
5. memory：
   - assist 与 validated replay 分流
6. benchmark：
   - formal controlled + open validation 双 pack
   - 三条 formal claim lane 独立对照

这条路线最贴题，也最容易做出诚实而清楚的证据层。
