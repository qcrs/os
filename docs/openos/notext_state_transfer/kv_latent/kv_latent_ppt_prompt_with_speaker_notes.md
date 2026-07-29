# KV Latent 机制 PPT 生成提示词与演讲稿

生成时间：2026-07-08

本文档用于生成一份介绍 `kv_latent` / `latent_kv` 机制的技术 PPT。目标是突出它相对普通 `structured` 模式的优势，同时讲清楚机制细节、适用边界和实验口径。可直接把下面的“PPT 生成提示词”复制给 PPT 生成工具或大模型。

相关材料：

| 文件 | 用途 |
|---|---|
| 现有 latent KV 设计文档 | latent_kv 模式架构、拓扑、control plane / data plane 设计 |
| `kv_latent_detailed_design.md` | KV latent 详细设计说明 |
| `kv_latent_usage_guide.md` | 适用任务、运行环境、启动与实验说明 |
| `exp/ppt_doc_2kv_latent_exp.md` | structured/latent_kv 十轮实验统计材料 |

## 一、PPT 生成提示词

请生成一份中文技术汇报 PPT，主题是：

```text
KV Latent：面向多 Agent 的非文本状态传递机制
```

### 1. 汇报目标

这份 PPT 用于向技术评审或导师说明 `kv_latent` 机制为什么存在、怎么工作、相比普通 `structured` 模式有什么优势，以及当前实现的限制。

核心观点：

```text
structured 解决了“证据可追踪、通信结构化”的问题；
latent_kv 在保留前半段结构化证据链的基础上，进一步解决 analyst、executor、summarizer 之间长中间推理反复文本搬运的问题。
```

请不要把 `kv_latent` 描述成完全替代 structured 模式。正确表达是：

```text
latent_kv = 前半段 structured evidence chain + 后半段 server-side KV continuation
```

### 2. 受众

- 熟悉 LLM / 多 Agent / LangGraph 的技术人员；
- 不一定了解 KV cache 细节；
- 需要看懂机制设计、实验收益、风险边界。

### 3. 视觉风格

- 技术报告风格，清晰、克制、结构化；
- 使用流程图、对比表、分层图；
- 不要做营销风格；
- 不要使用夸张结论；
- 每页控制在 3-5 个核心点；
- 每页都要包含演讲者备注。

### 4. 必须覆盖的概念

请在 PPT 中解释清楚以下概念：

| 概念 | 必须说明 |
|---|---|
| `structured` | 普通结构化模式，使用 `AgentMessage`、`ContextPacket`、`evidence refs`、`embedding ranking` 和 `verify/rehydrate` |
| `latent_kv` | 混合模式，planner/researcher 显式结构化，analyst 之后用 KV handle 传递状态 |
| `ContextPacket` | 压缩证据包，含 summary、evidence_spans、doc_key、full_doc_ref、offset/hash |
| `full_doc_ref` | 指向 Store 中完整原文，用于校验和回填 |
| `verify` | 用 offset 和 hash 检查 evidence 是否能对应回原文 |
| `rehydrate` | 校验失败时根据 doc_key 从 Store 回填兜底证据 |
| `KV handle` | 指向 server-side KV cache 的轻量引用 ID，不是 KV tensor 本体 |
| `prefill` | 把显式 analyst material 读进模型，创建初始 KV handle |
| `latent steps` | 不解码成文本的内部推理步，更新 KV cache |
| `decode` | 从当前 KV 状态生成必要的可见文本，如代码、JSON、最终答案 |
| `inject` | 把角色标记、执行结果等少量文本追加进 KV 链 |
| control plane / data plane | Agent state 只传 handle-id，真实 `past_key_values` 留在模型服务 GPU 内存 |

### 5. 必须突出 structured 与 latent_kv 的差异

请使用一页对比表说明：

| 维度 | structured | latent_kv |
|---|---|---|
| 前半段 planner/researcher | 显式结构化 | 显式结构化，保持一致 |
| 证据链 | ContextPacket + evidence refs + Store | 继续保留 |
| analyst/executor/summarizer 状态传递 | 显式文本、结构化 JSON、摘要字段 | 主要传 `latent_kv_handle_id` |
| 中间推理 | 通常需要解码成文本再交给下游 | 通过 latent steps 保留在 KV 链中 |
| 通信成本 | 仍有长中间文本搬运 | 显式文本减少，但 server-side KV 增长 |
| 审计性 | 强 | 证据链强；latent 中间状态不可直接阅读 |
| 适用场景 | 证据追踪、结构化协作 | 长链路、多阶段、长中间推理、短最终答案 |
| 风险 | 文本膨胀、重复 prefill | GPU 显存占用、handle 生命周期、latent drift |

### 6. 必须包含实验结果

请包含一页实验数据，使用下面结果，注意口径说明：

#### 交易系统连续事故响应十轮实验

| 模式 | 平均耗时(s) | 字段命中 | 全字段正确 | Agent消息/轮 | 文本字符/轮 |
|---|---:|---:|---:|---:|---:|
| structured | 303.588 | 2/60 | 0/10 | 7.0 | 30627.1 |
| latent_kv | 275.548 | 40/60 | 0/10 | 4.0 | 25657.2 |

结论：

```text
latent_kv 相比 structured 平均耗时快 9.24%；
latent_kv 的字段命中更高；
通信补跑中，latent_kv 的 Agent 消息/轮减少 42.9%，文本字符/轮减少 16.2%；
但严格全字段正确仍为 0/10，不能宣传为已经达到生产级正确率。
```

#### 四城市巡检路线十轮实验

| 模式 | 平均耗时(s) | 路线正确 | 成本正确 | 完全正确 |
|---|---:|---:|---:|---:|
| structured | 115.153 | 0/10 | 0/10 | 0/10 |
| latent_kv | 109.779 | 7/10 | 5/10 | 3/10 |

结论：

```text
latent_kv 相比 structured 平均耗时快 4.67%；
latent_kv raw 输出可解析质量更好；
小规模组合推理场景也能看到一定收益，但仍需要进一步稳定化。
```

### 7. PPT 页数与结构

请生成 13 页 PPT，每页包含：

```text
标题
页面要点
建议图示
演讲者备注
```

页面结构如下：

1. 标题页：KV Latent 是什么
2. 问题背景：多 Agent 为什么会有长中间状态搬运
3. structured 已经解决了什么
4. structured 还没有解决什么
5. latent_kv 总体设计
6. 显式区：planner + 3 researchers + ContextPacket
7. Latent 区：analyst -> executor -> summarizer
8. KV handle、prefill、latent steps、decode、inject 的流程
9. Control plane / data plane 分离
10. structured vs latent_kv 对比
11. 实验结果：交易系统连续事故响应
12. 实验结果：四城市巡检路线
13. 适用边界、限制与总结

### 8. 关键表述要求

请使用以下准确表述：

```text
KV handle 是 server-side KV 状态的引用，不是 KV tensor 本身。
```

```text
latent steps 是不生成可见文本的内部推理步，会推进 KV cache 和 seq_len。
```

```text
latent_kv 没有放弃可审计证据链，planner 和 researcher 仍显式输出 plan、sub_queries、context packets、evidence refs 和 full_doc_ref。
```

```text
latent_kv 的收益来自：保留 structured 的证据可追踪性，同时减少 analyst、executor、summarizer 之间长自然语言中间状态的重复搬运。
```

请避免以下错误表述：

```text
KV handle 是持久化长期记忆。
```

```text
latent steps 等同于 CoT 文本。
```

```text
latent_kv 完全不传文本。
```

```text
latent_kv 一定比 structured 更快。
```

正确说法是：

```text
latent_kv 减少显式文本通信，但会增加 server-side KV 状态和 GPU 显存占用；具体速度收益取决于 latent steps、模型服务、任务长度和 decode 次数。
```

## 二、逐页内容与演讲稿

下面内容可作为 PPT 逐页草稿，也可以直接交给生成器扩写。

### 第 1 页：KV Latent 是什么

页面要点：

- `KV Latent` 是面向多 Agent 的非文本状态传递机制。
- 核心思想：Agent 间不反复搬运长中间推理文本，而是传递 `latent_kv_handle_id`。
- 当前 latent_kv 模式是混合设计：前半段 structured，后半段 latent KV。

建议图示：

```text
planner -> 3×researcher -> analyst_latent -> executor_latent -> summarizer_latent
                           ↑ latent starts here
```

演讲者备注：

```text
这一页先给一个总定义。KV Latent 不是把整个多 Agent 系统变成黑盒，也不是取消结构化通信。它真正做的是把 analyst 之后的长中间状态留在模型服务的 KV cache 中，下游只拿一个 handle 继续推理。前面的 planner 和 researcher 仍然显式产出计划、子查询和证据包，因此证据链还在。
```

### 第 2 页：问题背景：长中间状态反复搬运

页面要点：

- 多 Agent 链路中，上游常把内部推理解码成长文本。
- 下游再把这些文本重新 tokenize / prefill。
- analyst、executor、summarizer 之间尤其容易出现长分析、长计算、长摘要草稿反复传递。

建议图示：

```text
analyst long analysis text
        ↓ decode to text
executor reads again / prefill again
        ↓ execution explanation text
summarizer reads again / prefill again
```

演讲者备注：

```text
普通多 Agent 系统的问题不是只有 token 多，而是状态传递方式比较低效。模型内部已经形成了 KV cache，但我们通常会把它解码成自然语言，再让下一个 Agent 重新读一遍。这在任务复杂、链路长、每一步都有大量中间推理时，会带来重复编码、重复 prefill 和文本膨胀。
```

### 第 3 页：structured 已经解决了什么

页面要点：

- 用 `AgentWorkflowState` 承载共享状态。
- 用 `AgentMessage` 记录 Agent 行为。
- 用 `ContextPacket` 传递压缩证据。
- 用 `doc_key`、offset、hash、`full_doc_ref` 保留可追溯性。
- 用 embedding / lexical ranking 选择相关证据包。

建议图示：

```text
Store full docs
   ↑ doc_key + full_doc_ref
ContextPacket
   ├─ summary
   ├─ evidence_spans
   ├─ source_ref offset/hash
   └─ verification
```

演讲者备注：

```text
structured 的价值非常明确：它把原来松散的自然语言通信变成结构化协议。证据不是只靠一句摘要，而是有 doc_key、offset、hash 和 full_doc_ref，可以回 Store 校验。所以下游 Agent 不需要反复读全文，同时又能保留证据出处。
```

### 第 4 页：structured 还没有解决什么

页面要点：

- structured 让证据更可控，但 analyst 之后仍可能产生长文本中间状态。
- executor 和 summarizer 仍需要读取上游输出。
- 结构化字段减少混乱，不等于消除重复文本传递。
- 对长链路、短最终答案任务，显式中间文本可能是主要开销。

建议图示：

```text
structured:
context_packets are compact
but
analysis / execution / summary drafts may still be text-heavy
```

演讲者备注：

```text
这里要强调 structured 模式不是不好，而是它解决的是证据结构化问题。它没有从根上改变 analyst 到 executor、executor 到 summarizer 的状态传递方式。只要这些阶段仍然把中间推理解码成文本，再交给下游读，就还会存在重复搬运。
```

### 第 5 页：latent_kv 总体设计

页面要点：

- latent_kv 模式保留 structured 的前半段结构化证据链。
- latent KV 从 analyst 开始，不在 researcher 并行阶段 fork/merge KV。
- Agent 间传递轻量 `latent_kv_handle_id`。
- 真实 KV cache 留在 `latent_kv_model_server`。

建议图示：

```text
Explicit structured zone:
planner -> researcher x3 -> context_packets

Latent KV zone:
analyst_latent -> executor_latent -> summarizer_latent
     handle              handle              final decode
```

演讲者备注：

```text
latent_kv 的关键设计是混合式。planner 和 researcher 阶段需要并行、需要证据可查，所以仍然显式结构化。等三个 researcher fan-in 后，analyst 把这些材料 prefill 成初始 KV handle。之后 executor 和 summarizer 不再接收长 analysis 文本，而是继承这个 handle 继续推理。
```

### 第 6 页：显式区：Plan、Sub Queries 与 ContextPacket

页面要点：

- planner 输出 `plan` 和 3 个互补 `sub_queries`。
- 3 个 researcher 并行产出 `context_packets`。
- 每个 packet 包含 `summary`、`evidence_spans`、`doc_key`、`full_doc_ref`。
- evidence 通过 offset/hash 校验，失败可 rehydrate。

建议图示：

```text
planner
  ├─ sub_query_1 -> researcher_1 -> packet_1
  ├─ sub_query_2 -> researcher_2 -> packet_2
  └─ sub_query_3 -> researcher_3 -> packet_3
packets fan-in -> analyst material
```

演讲者备注：

```text
这一页解释为什么 latent_kv 仍然有三个 researcher。它们不是为了增加复杂度，而是为了覆盖互补证据方向，并保持和 structured 模式一致的业务拓扑。每个 researcher 的输出仍是可审计的 context packet。这样做避免了完全 latent 化带来的黑盒证据问题，也避免了并行 KV 分支合并难题。
```

### 第 7 页：Latent 区：Analyst 到 Summarizer

页面要点：

- analyst 接收 `analyst material`，执行 prefill。
- analyst 运行 latent steps，形成内部分析状态。
- executor 继承 handle，只 decode 必要代码或动作。
- summarizer 继承执行后的 handle，只 decode 最终答案。

建议图示：

```text
analyst material
   ↓ prefill
handle_A
   ↓ latent steps
handle_A'
   ↓ executor decode/inject
handle_E
   ↓ summarizer final decode
answer
```

演讲者备注：

```text
Latent 区的目标是减少长中间文本。Analyst 可以进行内部分析，但不必把完整 analysis 文本输出给 executor。Executor 只在需要执行或生成代码时 decode 一小段，再把执行结果 inject 回 KV 链。Summarizer 最后基于整个 KV 链生成最终结果。
```

### 第 8 页：Prefill、Latent Steps、Decode、Inject

页面要点：

- `prefill`：把显式材料读入模型，创建初始 KV。
- `latent steps`：不输出文本，只追加隐式序列位置并更新 KV。
- `decode`：从当前 KV 状态生成必要可见文本。
- `inject`：把角色标记、执行结果等少量文本写回 KV 链。

建议图示：

```text
text material --prefill--> KV handle
KV handle --latent steps--> updated KV handle
KV handle --decode--> code / JSON / answer
external result --inject--> updated KV handle
```

演讲者备注：

```text
这几个词需要讲清楚。Prefill 是正常读文本，建立 KV cache。Latent steps 是让模型在不生成可见 token 文本的情况下继续 forward，更新内部状态。Decode 是必须输出时才生成文本，例如代码或最终 JSON。Inject 是把外部结果再接回 KV 链，让后续阶段知道执行发生了什么。
```

### 第 9 页：Control Plane / Data Plane 分离

页面要点：

- Control plane：LangGraph state 中的小字段，如 `latent_kv_handle_id`。
- Data plane：server-side `past_key_values` tensor。
- handle 是引用，不是数据本体。
- 好处是 Agent 通信轻量，GPU KV 不跨 Agent JSON 传输。

建议图示：

```text
LangGraph State:
{
  "latent_kv_handle_id": "lkv_xxx",
  "analysis_digest": "...",
  "execution_summary": "..."
}

Model Server:
lkv_xxx -> past_key_values + last_hidden + seq_len + kv_bytes
```

演讲者备注：

```text
这里是 latent_kv 模式最核心的系统设计。Agent 之间只传 handle-id，这是控制面。真实的 KV cache 作为数据面保留在模型服务中。这样既避免把巨大 tensor 放进 LangGraph state，也避免把上游长文本反复交给下游 prefill。
```

### 第 10 页：structured vs latent_kv

页面要点：

| 维度 | structured | latent_kv |
|---|---|---|
| 证据链 | 结构化可审计 | 继续保留 |
| 后半段状态 | 文本/JSON/摘要字段 | KV handle |
| 中间推理 | 解码后传递 | 留在 server-side KV |
| 通信 | 显式文本较多 | 显式文本减少 |
| 成本转移 | token/prefill | GPU KV/latent forward |
| 主要风险 | 文本膨胀 | 显存、handle 生命周期、latent drift |

建议图示：

```text
structured: structured text handoff
latent_kv: structured evidence + KV continuation
```

演讲者备注：

```text
这一页是核心对比。latent_kv 不是把 structured 推翻，而是在 structured 的基础上把后半段状态传递方式换掉。structured 的证据可追踪能力还在，latent_kv 额外减少了 analyst、executor、summarizer 之间的长文本 handoff。代价是 KV 会在 server 端增长，需要管理显存、handle 清理和 latent drift。
```

### 第 11 页：实验结果：交易系统连续事故响应

页面要点：

| 模式 | 平均耗时(s) | 字段命中 | 全字段正确 | Agent消息/轮 | 文本字符/轮 |
|---|---:|---:|---:|---:|---:|
| structured | 303.588 | 2/60 | 0/10 | 7.0 | 30627.1 |
| latent_kv | 275.548 | 40/60 | 0/10 | 4.0 | 25657.2 |

- latent_kv 平均耗时快 9.24%。
- Agent 消息/轮减少 42.9%。
- 文本字符/轮减少 16.2%。
- 严格全字段正确仍为 0/10。

建议图示：

```text
bar chart:
avg time: structured 303.588 vs latent_kv 275.548
text chars/round: structured 30627.1 vs latent_kv 25657.2
field hits: structured 2/60 vs latent_kv 40/60
```

演讲者备注：

```text
这个实验是更符合 latent_kv 模式优势的场景：十轮连续事故响应，每轮都有长证据、长因果分析、处置矩阵和短 JSON 输出。latent_kv 在平均耗时、字段命中和通信指标上都优于 structured。不过必须诚实说明，严格全字段正确仍然是 0/10，所以这个结果说明机制有潜力，但最终答案约束还需要继续加强。
```

### 第 12 页：实验结果：四城市巡检路线

页面要点：

| 模式 | 平均耗时(s) | 路线正确 | 成本正确 | 完全正确 |
|---|---:|---:|---:|---:|
| structured | 115.153 | 0/10 | 0/10 | 0/10 |
| latent_kv | 109.779 | 7/10 | 5/10 | 3/10 |

- latent_kv 平均耗时快 4.67%。
- latent_kv raw 输出可解析质量明显更好。
- 小规模组合推理也观察到收益，但收益小于长事故响应场景。

建议图示：

```text
bar chart:
route correct: structured 0 vs latent_kv 7
cost correct: structured 0 vs latent_kv 5
full correct: structured 0 vs latent_kv 3
```

演讲者备注：

```text
四城市任务规模比事故响应小，但仍有组合推理和结构化输出要求。这里 latent_kv 的速度提升没有事故响应那么大，但输出可解析质量更好。这个结果可以作为辅助证据：latent_kv 不只是在一个任务上有效，不过更适合长链路、长中间推理的场景。
```

### 第 13 页：适用边界、限制与总结

页面要点：

适合：

- 长链路多 Agent；
- analyst/executor/summarizer 有大量中间推理；
- 最终输出较短；
- 需要证据链可审计，但不要求每一步中间思考都显式展示。

限制：

- latent 中间状态不可直接阅读；
- KV 占用 GPU 显存；
- handle 生命周期需要清理；
- latent steps 太多可能变慢；
- 当前不支持多个 KV 分支无损 merge。

总结：

```text
KV Latent 的价值不是替代 structured，而是在 structured evidence chain 之后，用 server-side KV continuation 降低长中间状态 handoff 成本。
```

演讲者备注：

```text
最后要把边界说清楚。KV Latent 不是所有任务都适合。如果任务很短，或者每一步都必须给人完整阅读，那么 structured 可能更合适。latent_kv 模式的优势在于长链路、多阶段、最终答案短的任务。它把成本从显式文本通信转移到 server-side KV 管理，因此后续重点是 handle 生命周期、显存控制、latent steps 数量和最终答案约束。
```

## 三、一分钟版本讲稿

```text
KV Latent 解决的是多 Agent 后半段长中间推理反复搬运的问题。

普通 structured 模式已经把 planner 和 researcher 的输出结构化了：有 plan、sub_queries、ContextPacket、evidence refs、full_doc_ref、offset/hash 校验和 rehydrate，所以证据链是可审计的。但是到了 analyst、executor、summarizer，系统仍然容易把长分析、长计算过程和长摘要草稿解码成文本，再让下游重新读一遍。

latent_kv 的设计是混合式的：前半段继续使用 structured 证据链，保证可解释；从 analyst 开始，把显式材料 prefill 成 server-side KV cache，并返回一个 KV handle。后续 executor 和 summarizer 不再反复接收长文本，而是继承这个 handle，在同一条 KV 链上继续 latent steps，只在需要代码、执行结果或最终答案时 decode。

所以它的优势不是取消文本，而是减少不必要的中间文本 handoff。实验上，在交易系统连续事故响应十轮任务中，latent_kv 比 structured 平均耗时快 9.24%，Agent 消息/轮减少 42.9%，文本字符/轮减少 16.2%，字段命中也更高。但它仍有边界：latent 中间态不可直接阅读，KV 会占用 GPU 显存，handle 需要清理，最终 JSON 约束还需要进一步增强。
```

## 四、三分钟版本讲稿

```text
这套机制的背景是，多 Agent 系统在复杂任务里经常产生很长的中间状态。比如 analyst 做因果分析，executor 做执行计算，summarizer 做最终总结。普通做法是上游把这些内容解码成自然语言，下游再把它们重新 tokenize 和 prefill。这样不仅通信文本变长，也会重复消耗模型上下文处理成本。

structured 模式已经解决了前半段的关键问题。Planner 显式输出 plan 和 sub_queries，多个 researcher 输出 ContextPacket。每个 ContextPacket 里有 summary、evidence_spans、doc_key、full_doc_ref，以及 offset/hash。下游可以 verify，失败时可以 rehydrate。这使证据链可追踪、可校验、可审计。

但是 structured 的后半段仍然主要依赖显式文本传递。Analyst 的长分析要传给 executor，executor 的结果和解释要传给 summarizer。结构化协议降低了混乱，但没有完全消除长中间推理的重复搬运。

latent_kv 的思路是保留 structured 的证据链，然后从 analyst 开始切换到 server-side KV continuation。Analyst 先把 task、plan 和多路 context packets 组织成 analyst material，调用 prefill 创建初始 KV handle。这个 handle 只是一个轻量 ID，真正的 past_key_values 留在模型服务的 GPU 内存中。之后 analyst 运行 latent steps，不输出长 analysis 文本，只更新 KV 状态。Executor 继承 handle，只在必要时 decode 代码或动作，把执行结果 inject 回 KV 链。Summarizer 再继承执行后的 handle，生成最终答案。

这种设计把 control plane 和 data plane 分开。LangGraph state 里只传 handle-id、少量 digest 和执行摘要；data plane 里的真实 KV tensor 留在 latent_kv_model_server。这样既保留了 structured 的可审计证据链，又减少了后半段长文本 handoff。

实验上，交易系统连续事故响应十轮任务中，latent_kv 相比 structured 平均耗时快 9.24%，字段命中从 2/60 到 40/60，通信补跑中 Agent 消息数从 7.0 次/轮降到 4.0 次/轮，文本字符从 30627.1 降到 25657.2。四城市巡检路线任务中，latent_kv 也有 4.67% 的平均耗时提升，并且 raw 输出可解析质量明显更好。

但这个机制不是无条件更优。它会增加 server-side KV 占用，需要管理 handle 生命周期；latent steps 太多会变慢；中间 latent 状态不可直接阅读；当前也不支持多个 KV 分支无损 merge。因此我们把 latent 边界放在 researcher fan-in 之后，而不是从 planner 开始全链路 latent 化。

总结来说，KV Latent 的价值是：不是替代 structured，而是在 structured evidence chain 之后，用 KV continuation 降低多 Agent 后半段的长中间状态传递成本。
```

## 五、答辩问答提示

### Q1：为什么不直接用一个 Agent？

答：

```text
一个 Agent 可以做短任务，但复杂任务需要职责边界。planner 负责拆解，researcher 负责证据，analyst 负责归因，executor 负责动作和计算，summarizer 负责最终输出。拆分后可以审计、回放、定位错误阶段。KV Latent 不是为了增加 Agent，而是为了让已有多阶段设计减少长文本 handoff 成本。
```

### Q2：为什么不从 planner 开始就用 KV？

答：

```text
planner/researcher 阶段需要显式 plan、sub_queries 和 evidence refs，而且 researcher 是并行 fan-out。多个 KV 分支如何无损 merge 到 analyst 是复杂问题。当前设计把 latent 边界放在 researcher fan-in 之后，可以保留证据链，同时避免 KV fork/merge。
```

### Q3：KV handle 是不是长期记忆？

答：

```text
不是。KV handle 是当前模型服务中某段 KV cache 的引用，生命周期受 server 管理。它不是长期知识库，也不是可审计文本。长期可追踪信息仍然靠 Store、doc_key、ContextPacket 和 evidence refs。
```

### Q4：latent steps 是不是 Chain-of-Thought？

答：

```text
不是。CoT 是可见文本推理；latent steps 是不解码成文本的模型 forward 步。它会更新 KV cache 和 seq_len，但中间内容不可直接阅读。因此系统仍需要显式证据链来保证可审计性。
```

### Q5：latent_kv 为什么还能审计？

答：

```text
因为审计重点放在前半段证据链和最终输出引用上。planner 和 researcher 仍显式输出 plan、sub_queries、ContextPacket、evidence refs 和 full_doc_ref。ContextPacket 可以通过 offset/hash verify，失败可以 rehydrate。latent 区只减少后半段长中间推理文本，并不删除证据来源。
```

### Q6：latent_kv 一定比 structured 快吗？

答：

```text
不一定。latent_kv 减少显式文本通信和重复 prefill，但会增加 latent forward 和 GPU KV 管理成本。任务越长、后半段中间推理越重、最终输出越短，越适合 latent_kv。短任务或 latent steps 设置过多时，latent_kv 可能不快。
```
