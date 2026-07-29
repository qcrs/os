# KV 模式两页 PPT 生成提示词

生成时间：2026-07-08

本文档用于生成一份 **2 页中文技术 PPT**，只讲 `kv_latent` / KV handoff 模式的机制、优点和适用任务，不包含实验数据。

## PPT 生成提示词

请生成一份 2 页中文技术 PPT，主题是：

```text
KV Latent：多 Agent 中的非文本状态传递机制
```

整体要求：

- 不讲实验结果，不放耗时、准确率、字段命中等数据。
- 重点讲 KV 模式的机制、设计优势、适合什么任务。
- 技术报告风格，清晰、克制、结构化。
- 每页包含：标题、页面要点、图示说明、演讲者备注。
- 不使用 `B_`、`D_` 这类实验组前缀。
- 不把 KV 模式讲成万能方案，要说明适用边界。

## 第 1 页：KV Latent 的机制

### 页面标题

```text
KV Latent：把长中间状态留在模型服务中
```

### 页面要点

- 普通多 Agent 链路中，上游 Agent 往往把中间推理解码成长文本，下游再重新读取。
- KV 模式把模型已经形成的 `past_key_values` 保留在 server-side KV cache 中。
- Agent 之间不直接传 KV tensor，只传轻量 `KV handle`。
- 下游 Agent 根据 handle 继续推理，实现类似“接着前面的模型状态继续生成”。
- 显式文本只保留必要控制信息，例如任务、证据引用、角色切换、最终输出约束。

### 关键概念说明

| 概念 | 含义 |
|---|---|
| `prefill` | 把显式输入读进模型，创建初始 KV cache |
| `KV handle` | 指向 server-side KV cache 的引用 ID，不是 KV tensor 本体 |
| `latent steps` | 不解码成可见文本的内部推理步，只推进 KV 状态 |
| `decode` | 在必要时从当前 KV 状态生成代码、JSON 或最终答案 |
| `inject` | 把执行结果、角色标记等少量文本写回 KV 链 |

### 图示说明

请画一张“控制面 / 数据面分离”的流程图：

```text
显式材料
task + plan + context packets + evidence refs
        |
        v
     prefill
        |
        v
  KV handle: lkv_xxx
        |
        | control plane: Agent state only passes handle-id
        v
analyst -> executor -> summarizer
        |
        v
data plane: server-side KV cache
past_key_values + last_hidden + seq_len
```

图中需要突出：

- Agent state 里只传 `latent_kv_handle_id`。
- 真实 KV tensor 留在模型服务中。
- analyst、executor、summarizer 通过同一条 KV 链继续推进状态。

### 演讲者备注

```text
这一页讲 KV 模式到底是什么。普通多 Agent 系统会把上游内部推理变成文本，再让下游重新读一遍。KV Latent 改变的是状态传递方式：显式材料先通过 prefill 进入模型，模型服务保存生成的 KV cache，并返回一个 handle。后续 Agent 不需要拿到完整中间文本，也不需要拿到真实 tensor，只要拿 handle 就能在同一条 KV 链上继续推理。

这里要强调，KV handle 只是引用，不是长期记忆，也不是可审计文本。真实数据面是 server-side 的 past_key_values；控制面是 LangGraph 或 Agent state 里的 handle-id、少量摘要和执行约束。这样既能减少长文本搬运，又不会把巨大 GPU tensor 放进 Agent 消息里。
```

## 第 2 页：KV 模式的优点与适用任务

### 页面标题

```text
适合长链路、长中间推理、短最终输出的任务
```

### 页面要点

- 减少 analyst、executor、summarizer 之间长中间文本的重复传递。
- 降低下游重复 tokenize / prefill 上游长分析文本的成本。
- 保留多 Agent 的职责边界：分析、执行、总结仍可分阶段管理。
- 状态传递更接近模型原生 continuation：下游基于已有 KV 状态继续推进。
- 适合最终答案很短、但中间推理很长的任务。

### 适用任务

| 任务类型 | 为什么适合 KV 模式 |
|---|---|
| 连续事故响应 | 每轮需要继承大量诊断、处置和约束，中间状态长 |
| 复杂运维诊断 | 需要多阶段归因、验证、执行和总结 |
| 多步骤代码分析 / CodeAct | 分析很长，但最终只需要代码片段、执行结果或 JSON |
| 长文档综合问答 | 前面证据很多，后面只需逐步综合和生成短答案 |
| 多轮决策任务 | 需要保留历史判断、候选方案和约束排序 |

### 不优先适用的任务

| 任务类型 | 原因 |
|---|---|
| 单轮短问答 | 中间状态不长，KV handoff 收益小 |
| 每一步都必须人工阅读完整推理 | latent 中间状态不可直接审计 |
| 强并行分支后必须无损合并 | 多个 KV 分支 merge 成一条链较复杂 |
| GPU 资源紧张的环境 | server-side KV cache 会占用显存 |

### 图示说明

请画一张“适用任务判定图”：

```text
任务是否适合 KV 模式？

1. Agent 链路是否较长？
        |
        v
2. 中间分析/执行过程是否很长？
        |
        v
3. 最终输出是否较短？
        |
        v
4. 是否允许中间 latent 状态不完全展开？
        |
        v
适合使用 KV Latent
```

旁边放一个对比小图：

```text
文本 handoff:
long analysis text -> reread -> long execution text -> reread -> summary

KV handoff:
KV handle -> latent continuation -> decode only when needed
```

### 演讲者备注

```text
这一页讲 KV 模式为什么有价值，以及什么时候值得用。它的核心收益不是让系统完全不传文本，而是减少不必要的长中间文本传递。多 Agent 的职责边界仍然保留，analyst 负责分析，executor 负责动作或代码，summarizer 负责最终输出；变化在于这些阶段之间主要传递 KV handle，而不是反复传递长自然语言中间状态。

最适合的任务有几个特征：链路长，中间推理长，最终输出短，并且不要求每一步内部推理都完整展开给人看。例如连续事故响应、复杂运维诊断、多步骤 CodeAct、长文档综合和多轮决策。相反，如果任务本来很短，或者每一步都必须人工审计完整推理文本，KV 模式的收益就不明显，甚至会因为 GPU KV 管理和 latent steps 带来额外成本。
```

