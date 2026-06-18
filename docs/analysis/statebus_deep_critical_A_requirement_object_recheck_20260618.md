# 文档 A：赛题要求与当前 Object 重新对照

日期：2026-06-18

范围：`/home/qcrs/statebus/project`

## 1. 赛题硬约束重述

`docs/reference/题目.md` 对 StateBus 这类系统的硬约束可以拆成三条机制主轴和三条工程交付约束。

机制主轴：

1. 低开销结构化通信：
   - Agent 间不应只传自然语言长文本；
   - 通信内容应包含动作、参数、结果、能力描述；
   - 需要可复现实验比较 pure text 与 structured protocol。
2. 非文本中间状态传递：
   - 可以是 embedding、语义向量、hidden-state-like feature 或其他中间表示；
   - 必须说明生成、传递、接收、使用方式。
3. 共享记忆复用：
   - 存储、检索、复用；
   - 至少包含 memory ID、来源 agent、创建时间、主题、摘要等元数据；
   - 通过连续关联任务证明减少重复计算、降低开销或提升效率。

工程交付约束：

- 至少 3 个 Agent，覆盖规划、检索、执行、总结等角色；
- 至少 2 组关联连续任务；
- 展示消息数、token/字符、状态传递次数和规模、耗时、记忆命中率、性能提升；
- 稳定执行不少于 10 轮；
- 最终 openEuler 交付属于后验验证，不是当前 host 主线已经完成的事实。

## 2. 当前对象到底是什么

当前最真实的 StateBus object 不是“开放世界多 Agent 平台”，也不是“LangGraph 应用示例”，而是：

> 一个 host-side, repo-local, release-regression 题材的受控多 Agent benchmark prototype，用 `text_whole_lane` 与 `state_packet_minimal` 比较同一任务条件下的自然语言 whole-lane handoff 与 typed-state protocol handoff。

当前 formal headline：

- task set: `contest_honest_headline_v1`
- public surface: `formal_headline`
- variable axis: `mode`
- text object: `text_whole_lane`
- protocol object: `state_packet_minimal`
- engine: LangGraph-backed runner
- plan source: YAML by default
- task shape: `retrieve -> validate -> execute -> summarize`
- families: 5 release-regression chains
- rows: 20 text + 20 protocol
- complexity buckets: simple / distractor / ambiguous / reusable

这不是 external pure-text benchmark；它是 StateBus 内部 fair comparator。

## 3. 当前满足了什么

### 3.1 多 Agent 与角色覆盖

当前满足。

代码与 runtime 里有：

- `PlannerAgent`
- `RetrieverAgent`
- `ExecutorAgent`
- `SummarizerAgent`

但要谨慎措辞：

- headline 的 Planner 主要是 YAML task contract compiler；
- LLM-open planner 不是 headline 默认路径；
- Planner openness 只能读 `planner_support_v3` 或后续 secondary。

### 3.2 结构化通信

当前满足，而且是主线最强对象。

证据：

- protocol control frames、StateRef、schema/capability hardening 在 runtime 中真实存在；
- latest repeat=10 中 protocol state-transfer count 非零；
- API repeat=10 formal stability 通过；
- protocol control bytes mean `192935.2`，text control bytes mean `223741.2`。

当前可说：

> 在 current controlled contest headline 中，protocol side 相比 `text_whole_lane` 有稳定 control-byte compactness。

当前不应说：

> StateBus 在所有 token/latency/correctness 维度全面优于任意 text multi-agent system。

### 3.3 非文本中间状态传递

当前满足。

protocol side 的核心 state packet 是：

- `DENSE_EVIDENCE`
- `EXECUTOR_DECISION_PACKET`
- validation 时还会出现 `VALIDATION_GATE_PACKET`

repeat=10 中 protocol aggregate：

- state refs mean: `100`
- handoff nontext ref count mean: `50`
- handoff nontext bytes mean: API `58661.0`，deterministic `58652.0`

这说明非文本状态不是文档摆设。

边界：

- 不是 hidden-state/KV cache；
- 不是神经网络 activation；
- 不是跨模型 latent 继续推理；
- 当前是 feature/packet/state-ref 级别的中间态。

### 3.4 共享记忆与 replay

当前满足“实现存在”和“current headline S2 replay effect”两层，但不能过度泛化。

最新 current headline 已经有：

- expected reuse: `skip_execute = 10`
- memory policy: `validated_replay = 10`
- API repeat=10 `headline_memory_replay_effect_gate.memory_replay_effect_ready = true`
- API repeat=10 `actual_replay_row_count = 100`
- API repeat=10 `skipped_step_count = 100`

这比旧的 support-only replay 证据更强。

但它证明的是：

- current-headline S2 reusable rows 能使用 prior-dependent action / validated replay；
- replay 能省执行步骤；
- text/protocol 两侧都在受控对象里触发。

它没有证明：

- 开放式长期记忆；
- 任意相似任务迁移；
- agent 自主抽象经验；
- memory 是主创新中最强的一条。

### 3.5 10 轮稳定执行

当前满足 current headline 的 host-side repeat=10：

- API repeat=10 passed；
- deterministic repeat=10 passed；
- `withheld_headline_reason = ""`。

但这不是 openEuler final validation，也不是 Docker/nsjail 交付验证。

## 4. Submission-level 满足

当前可以作为 submission-level 主提交对象的内容：

1. Host-side StateBus runtime 已可运行。
2. `contest_honest_headline_v1` 已是 current formal headline。
3. text/protocol 双模式可复现比较成立。
4. protocol control compactness 已有 repeat=10 证据。
5. typed state packet 真实生产、传递、消费。
6. S1 validation 行为不再只是静态字段。
7. S2 prior-dependent action + validated replay 在 current headline 内成立。
8. 记忆模块真实存在，并可通过 current S2 replay 与 secondary packs 分层说明。

这些足以支撑一个诚实的 contest mainline prototype。

## 5. 只是存在、还不构成强 claim 的内容

### Planner

存在，不是 headline 主创新。它满足角色覆盖和可运行性，但 headline 中主要是 contract compiler。

### LangGraph

真实接入，不是创新主轴。它是 execution substrate，负责固定图和 state propagation。

### UDS / subprocess / tool registry

增强工程完整性，但不是 contest headline。

### shared_memory backend

是可验证后端，但 current headline 主线仍以 mmap 为主，不应把 shared_memory 讲成统一最优。

### CodeAct / sandbox

不是当前完成项。轻量 subprocess fallback 不等价于正式 CodeAct 安全沙箱。

### external text baseline

当前只有 audit/待审计意义，不能并入 headline。

## 6. 赛题 object 本身的问题

赛题把三条不同 claim 耦合到一个系统里：

1. communication efficiency；
2. non-text state transfer；
3. shared memory reuse。

这些本来应该分层评估。当前 StateBus 的多 pack 历史混乱并不全是实现者问题，部分来自赛题 object 的耦合：

- pure text baseline 没有明确定义；
- structured protocol、state transfer、memory reuse 容易互相借分；
- 角色覆盖容易被误读成 Planner 必须强创新；
- 系统完整性容易把 LangGraph、CodeAct、sandbox、openEuler 混到主 claim 里。

因此最合理的 submission story 不是一个单一“StateBus 全面胜利”，而是：

- formal headline：communication + typed-state controlled object；
- memory secondary：S2 replay / prior-dependent action；
- planner secondary：planner support；
- audit layer：external pure text / open baseline / LangGraph-native / route-corpus stress。

## 7. A 文档结论

当前 StateBus 已经足够作为一个受控但扎实的赛题主提交对象。它最强的 submission-level object 是：

> structured control + typed-state handoff under `contest_honest_headline_v1`

它不应被讲成：

- external pure-text baseline win；
- open-world agent benchmark；
- LangGraph innovation；
- adaptive LLM planner benchmark；
- hidden-state/KV state transfer；
- broad long-term memory agent。

最稳口径：

> StateBus 在一个受控、paired、repeat=10 的 contest headline 中证明了结构化控制和 typed-state handoff 的机制真实性与通信 compactness；S2 replay 已进入 current headline，但其泛化边界应作为 secondary/audit 层继续说明。
