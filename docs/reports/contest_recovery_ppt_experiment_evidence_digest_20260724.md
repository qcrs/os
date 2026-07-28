# StateBus 答辩实验与证据总账（2026-07-24）

## 0. 文档目的

本文不是新的实验计划，也不是对单次成功结果的宣传稿。它把固定基线 E0-E6、历史 E1 时延观察、2026-07-24 的 P0-lite/P1-lite 复测、赛题要求和两版主 PPT 的叙事需求汇聚成一份可审计的实验依据，供以下工作直接使用：

1. 修改答辩 PPT 的实验页和结论页；
2. 让未参与开发的人快速判断“实现了什么、证据有多强、还不能声称什么”；
3. 避免把不同实验的候选数、命中率、Token、时延和省工指标混为一谈；
4. 保留历史结果与新复测之间的冲突，并给出统一解释，而不是选择性展示。

本文不引入新数据集，不把 Prefix/APC 或 LogitState 纳入主线，也不把未做的 T2 载体性能实验包装成现有结果。

## 1. 一页结论

### 1.1 固定叙事

```text
typed control
  -> cross-process SemanticStateRef
  -> verified ExecutionArtifactRef
  -> compatibility-gated MemoryRef
```

三个赛题支柱是：

| 支柱 | 要解决的问题 | StateBus 的做法 | 最强现有证据 |
| --- | --- | --- | --- |
| 结构化通信 | Agent 之间只传自然语言，接口不可验证、通信冗余 | UDS + typed Protobuf，显式 action/input/result/capability | E1：控制面字节下降 83.05%，质量保持 |
| 非文本状态 | 数值中间状态若转写为文本会膨胀、失真且缺少生命周期 | shared-memory `SemanticStateRef`，跨 PID 打开、消费、回执、释放 | E4：3 个语义任务、9 条数值选择回执、跨 PID、生命周期闭环 |
| 共享记忆复用 | 相似历史不能无条件注入，也不能只统计“检索到候选” | `MemoryRef` + 兼容门 + consumption/effect receipt + 不兼容重算 | E2：自然链真实使用率 35%；E3：负例拒绝、跨角色消费、一次真实跳过 LLM call |

统一亮点不是“用了 Protobuf、共享内存和向量库”三个组件的堆叠，而是 **receipt-backed state promotion（回执支撑的状态提升）**：状态只有在类型明确、来源可追踪、消费者真实打开或使用、产物验证通过、运行时兼容时，才从临时结果提升为可复用资产。

### 1.2 当前最可信的综合结论

| 维度 | 当前结论 | 证据等级 |
| --- | --- | --- |
| 正确性 | 固定基线 E1 40/40、E2 20/20、E3 6/6、E4 4/4、E5 25/25；新复测 80/80 | 强 |
| Token | 新 P0 AB/BA 中 L3 相对 L0 总 Token `-46.48%`，prompt Token `-53.28%` | 强、已平衡顺序复现 |
| 通信 | 新 P0 中 wire bytes `-64.77%`，control bytes `-78.74%` | 强、已平衡顺序复现 |
| 端到端时延 | 新 P0 中 L3 `+5.44%`，平均增加约 `1.414 s/任务` | 强；结果是受控代价，不是加速 |
| 非文本状态 | shared-memory float32 状态确实由不同 PID 的 Executor 消费，并改变证据选择 | 强机制证据；无载体速度结论 |
| 自然连续任务记忆 | E2 实际使用/行为效果率 `7/20 = 35%`，严格跳步率 `2/20 = 10%` | 强真实性证据 |
| 短窗口记忆净收益 | 新 P1-lite 实际使用率 `4/20 = 20%`，有 4 次跳步，但时延 `+3.82%`，0 次跳过 LLM | 强边界证据；未形成净加速 |
| 记忆安全性 | E2 拒绝 39/48 候选；E3 故意不兼容 fixture 被拒绝并重算 | 强 |
| CodeAct | E5 25/25，18 个受限 Python CodeAct、7 个 DSL、0 fallback | 强能力覆盖证据 |
| Prefix/LogitState | 不是当前固定基线已验证亮点 | 不进入 PPT 主结论 |

### 1.3 PPT 推荐主句

> StateBus 在 100% 保持本轮任务质量的前提下，将多 Agent 协作的总 Token 降低 46.48%、wire bytes 降低 64.77%、控制面字节降低 78.74%；完整的状态发布、消费回执、产物验证和记忆兼容门带来约 5.44%（1.41 秒/任务）的端到端时延代价。系统的价值是把不可控文本传递升级为低通信负担、可验证、可追溯、可安全复用的状态协作，而不是宣称所有任务都更快。

## 2. 证据层级与阅读规则

### 2.1 证据优先级

| 优先级 | 证据 | 用途 |
| ---: | --- | --- |
| 1 | 新 P0-lite/P1-lite AB/BA 复测 | 当前 Token、通信、时延和短窗口记忆净收益结论 |
| 2 | 固定基线 E0-E6 正式实验 | 机制、长链稳定性、记忆真实性、CodeAct 和工程完整性 |
| 3 | 历史 E1 固定顺序统计 | 描述历史观察和工作负载差异，不能覆盖新时延结果 |
| 4 | 失败、重试和诊断产物 | 解释修复过程与回归边界，不进入 headline |
| 5 | 7 月 23-24 日 Prefix/LogitState 等开发产物 | 与本基线隔离，不倒推为已有能力 |

### 2.2 五个容易混淆的记忆概念

| 概念 | 分子 | 能说明什么 | 不能说明什么 |
| --- | --- | --- | --- |
| 有候选查询 | 返回至少一个候选的 query | 检索器找到了相似历史 | 记忆可用或已复用 |
| 兼容候选 | 通过 runtime/input/output/validator 门的候选 | 候选具备使用资格 | 已进入执行路径 |
| 真实消费 | 有 consumption receipt 的 query/候选 | 某角色确实使用了记忆 | 已节省时间或调用 |
| 行为效果 | 有 observable effect 的消费 | 记忆改变了执行行为 | 一定减少 LLM 调用 |
| 严格省工 | skipped step / skipped LLM call | 真实少做了一步或一次模型调用 | 整体一定更快 |

答辩只写“命中率”会失真。若必须给单一主数字，使用 E2 的 **实际使用率 `7/20 = 35%`**，并在图中保留完整漏斗。

### 2.3 指标公式

| 指标 | 公式 |
| --- | --- |
| query candidate rate | 有候选的 query 数 / 全部 query 数 |
| actual-use rate | 产生真实 consumption 的 query 数 / 全部 query 数 |
| effect rate | 产生 behavioral effect 的 query 数 / 全部 query 数 |
| candidate compatibility rate | 兼容候选数 / 候选总数 |
| candidate rejection rate | 不兼容候选数 / 候选总数 |
| strict skipped-step rate | 产生 skipped step 的 query 数 / 全部 query 数 |
| 指标变化率 | `(L3 - baseline) / baseline * 100%`；负数表示下降 |

## 3. 赛题要求覆盖矩阵

| 赛题要求 | 对应实现 | 实验证据 | 当前状态与边界 |
| --- | --- | --- | --- |
| 至少 3 个 Agent | Planner、Retriever、Executor、Summarizer 等角色 | E1-E5 的 role request、telemetry、receipt | 已覆盖 |
| 至少 3 类任务 | 财报、运营指标及 E5 扩展能力/任务族 | E1/E2/E5 | 已覆盖；正式 benchmark 仍以离线财报和运营分析为主 |
| 结构化 action/input/result/capability | typed Protobuf、typed plan、capability registry | E1、E5 | 已覆盖 |
| 文本与结构化同任务对比 | L0-L3 匹配矩阵 | E1；新 P0 L0/L3 AB/BA | 已覆盖 |
| 非文本状态生成、传递、使用 | StructuredEmbedding/DenseSemanticState -> shared-memory StateRef -> Executor selection | E4 | 已覆盖机制与生命周期；不声称载体更快 |
| 统一记忆单元及必要元数据 | MemoryRef/MemoryCommit，ID、来源、时间、主题、摘要 | E3 七个 registry entry | 已覆盖 |
| keyword/tag/semantic 检索 | `hybrid_rrf:vector` 语义检索，另有 tags | E3 memory query/registry | 已覆盖赛题“或”条件 |
| 后续任务由不同 Agent 复用 | Executor、Summarizer 的 consumption receipt | E2/E3 | 已覆盖 |
| 两组相关连续任务 | Financial、Operating 各 10 轮 | E2 | 已覆盖，20/20 通过 |
| 稳定运行不少于 10 轮 | 两条 10 轮链 | E2 | 已覆盖 |
| 消息、Token、状态大小、时间、命中率、整体表现 | E1/P0 的 bytes/token/time/quality，E2/E3 的 memory funnel，E4 state bytes | E1-E4、P0/P1 | 已覆盖；时延结论为小幅代价而非优势 |
| CodeAct | bounded Python 和 DSL | E5 | 已覆盖鼓励项，不作为第四支柱 |
| 源码、设计、部署、报告 | repo、设计文档、容器运行材料、证据报告 | E0/E6 及本文来源 | 基本覆盖 |
| openEuler 交付 | 单个 openEuler 24.03 容器内验证 | E6/运行记录 | 只能写单容器范围，不能扩展为 VM/跨机/通用 Linux |
| 演示视频 | 需独立交付 | 当前证据账本无视频产物 | 待交付检查 |

## 4. 实验资产总览

| 实验 | 主要问题 | 规模 | 最适合证明 | 不应承担的结论 |
| --- | --- | ---: | --- | --- |
| E0 | 基线测试门是否通过 | 135 passed | 基础工程稳定 | 性能或赛题亮点 |
| E1 | L0-L3 在同任务上的差异 | 2 族 x 5 轮 x 4 层 = 40 case | 结构化通信、Token/wire、完整链质量 | 公平稳定的时延加速 |
| E2 | L3 连续任务和自然记忆复用 | 2 族 x 10 轮 = 20 case | 长链稳定性、自然 actual-use 率 | L0/L3 性能差异 |
| E3 | 记忆是否真实、安全、跨角色消费 | 6 case | 兼容门、负例拒绝、消费/效果、一次跳过 LLM | 普遍命中率或普遍加速 |
| E4 | 非文本状态是否真正跨进程消费 | 4 holdout | shared-memory 数值状态、PID、receipt/release | shared memory 比文本载体更快 |
| E5 | CodeAct/DSL 能力是否闭环 | 25 case | 18 Python + 7 DSL，零 fallback | CodeAct 性能领先 |
| E6 | 完整回归是否通过 | 558 passed, 100 warnings | 交付回归门 | benchmark 结论 |
| P0-lite | L0/L3 的公平序列化复测 | 2 顺序 x 10 配对 = 20 pairs | 当前 Token/wire/时延权衡 | 每种工作负载都同幅度变化 |
| P1-lite | L2 OFF 与 L3 actual-use 的短窗口对比 | 2 顺序 x 10 配对 = 20 pairs | 短窗口记忆漏斗与净收益边界 | 冻结快照、gate-only 的严格因果归因 |

## 5. 主线、难点、机制与实验的对应关系

| 为什么做 | 真正难点 | 实现亮点 | 应看指标 | 对应证据 |
| --- | --- | --- | --- | --- |
| 文本消息既冗余又无法形成稳定接口 | 结构化后仍要保证角色可恢复、质量不下降 | typed control、typed plan、ACK 和 capability contract | control bytes、wire bytes、质量、恢复事件 | E1、P0 |
| 数值中间态不适合转成自然语言 | 跨进程对象身份、数值语义、所有权、释放与下游效果必须同时成立 | SemanticStateRef + shared memory + consumption/release receipt | producer/consumer PID、state bytes、selected IDs、release | E4 |
| 执行结果不能未经验证直接变成记忆 | 区分临时 StateRef 与可复用 ExecutionArtifactRef | validator-backed artifact promotion、lineage | validator pass、artifact lineage、真实消费 | E1/E3 |
| 相似历史可能过期、不兼容或污染当前任务 | 检索命中不等于安全复用，必须 fail-closed | runtime compatibility signature、approved consumption、recompute | funnel、拒绝率、effect、skipped work | E2/E3/P1 |
| 多机制会引入运行时固定成本 | 需要同时展示收益和代价，避免只看 Token | AB/BA、质量门、LLM/非 LLM 分解 | task time、LLM wall、non-LLM、Token、bytes | P0 |

## 6. 结构化控制：L0 到 L1 的纯粹贡献

E1 中 L0/L1 保持相同 50 条消息，最适合回答“仅将文本控制改为 typed Protobuf 带来什么”。

| 指标 | L0 -> L1 | 结论 |
| --- | ---: | --- |
| control bytes | `25,196 -> 4,270`，`-83.05%` | 结构化控制显著压缩控制面 |
| total wire bytes | `36,069 -> 11,200`，`-68.95%` | 总线通信负担同步下降 |
| prompt tokens | `29,876 -> 30,737`，`+2.88%` | typed control 本身不减少 prompt Token |
| total tokens | `33,974 -> 34,891`，`+2.70%` | 不能把 Token 节省归因给 Protobuf |
| message count | `50 -> 50` | 收益不是少发消息造成的 |
| 质量 | 保持通过 | 压缩未牺牲任务正确性 |

正确归因是：

```text
L0 -> L1: 控制面结构化与 wire 压缩
L1 -> L2: 语义选择、hydration/pruning 带来主要 prompt/Token 缩减
L2 -> L3: 增加兼容门控记忆；当前省工有限，不是主要 Token 来源
```

## 7. 完整链 L0 到 L3：效率、质量与代价

### 7.1 新 P0-lite AB/BA 主表

| 指标 | L0（20 个配对汇总） | L3（20 个配对汇总） | L3 相对 L0 | PPT 含义 |
| --- | ---: | ---: | ---: | --- |
| 质量通过 | 20/20 | 20/20 | 持平 | 所有效率比较先通过质量门 |
| task time | 519.473 s | 547.751 s | `+5.44%` | 完整链存在小幅端到端代价 |
| 平均 task time | 25.974 s | 27.388 s | `+1.414 s/任务` | 应优先展示绝对代价 |
| operator wall | 527.173 s | 555.303 s | `+5.34%` | 外部观察与 task time 一致 |
| LLM wall | 466.819 s | 476.710 s | `+2.12%` | Token 下降未稳定转化为模型 wall time 下降 |
| non-LLM residual | 52.654 s | 71.041 s | `+34.92%` | 每任务约 `2.633 -> 3.552 s`，增加约 `0.919 s` |
| prompt tokens | 59,716 | 27,900 | `-53.28%` | 下游可见上下文显著减少 |
| total tokens | 67,937 | 36,357 | `-46.48%` | 当前最强效率 headline 之一 |
| wire bytes | 71,976 | 25,354 | `-64.77%` | 总线通信显著下降 |
| control bytes | 50,392 | 10,714 | `-78.74%` | typed control 优势稳定复现 |

### 7.2 顺序与配对分布

| 观察 | 结果 | 判断 |
| --- | ---: | --- |
| AB（L0 后 L3） | L3 task time `+5.33%` | L3 更慢 |
| BA（L3 后 L0） | L3 task time `+5.55%` | 反向顺序仍更慢 |
| L3 更快的 pair | 7/20 | 存在局部受益任务 |
| L3 更慢的 pair | 13/20 | 当前总体不支持加速 |
| Operating | 约 `+6.56%` | 本轮变慢 |
| Financial | 约 `+4.36%` | 本轮变慢 |

AB 与 BA 同方向意味着本轮 `+5.44%` 比历史固定顺序的时延数字更适合做当前结论。它不意味着系统设计失败，而是量出了完整安全机制的运行成本。

### 7.3 时延成本具体换来了什么

L3 相比 L0 每任务平均多约 1.414 秒，其中 non-LLM residual 平均增加约 0.919 秒。这一部分不是单独某个函数的精确耗时，而是以下机制的合计残差：

| 机制 | 新增工作 |
| --- | --- |
| typed control | 序列化、解析、合同检查、ACK |
| SemanticStateRef | 发布、打开、消费回执、释放 |
| runtime compatibility | 输入 lineage、runtime signature、输出合同和 validator 状态检查 |
| ExecutionArtifactRef | workspace/CAS 持久化、验证、lineage |
| MemoryRef | 检索、候选过滤、批准、消费和 effect 记录 |
| 可审计性 | telemetry、receipt 和 manifest 持久化 |

因此 PPT 可将其描述为 **receipt-backed state promotion 的可测安全成本**，但不能声称 0.919 秒已被逐项严格归因。

## 8. 历史时延与新复测冲突：完整保留与统一解释

### 8.1 两组结果并列

| 实验 | 设计 | L0 task time | L3 task time | 变化 | 质量 |
| --- | --- | ---: | ---: | ---: | --- |
| 历史 E1 | 固定顺序、10 个匹配任务 | 315.678 s | 295.728 s | `-6.32%` | 10/10 vs 10/10 |
| 新 P0-lite | warmup + AB/BA、20 个配对 | 519.473 s | 547.751 s | `+5.44%` | 20/20 vs 20/20 |

历史 E1 的任务族分化：

| 任务族 | 历史 L0 | 历史 L3 | 历史变化 |
| --- | ---: | ---: | ---: |
| Operating（5 个） | 159.896 s | 131.551 s | `-17.73%` |
| Financial（5 个） | 155.782 s | 164.178 s | `+5.39%` |

历史 E1 中 L3 6/10 更快、4/10 更慢，单任务变化范围 `-27.49%` 到 `+15.59%`。这说明早期结果本身就不是普遍加速，只是聚合后呈下降。

### 8.2 冲突如何解释

| 问题 | 统一判断 |
| --- | --- |
| 历史 `-6.32%` 是错误数据吗？ | 不是。它是固定顺序运行下的真实描述性观察，应保留。 |
| 能否继续作为时延 headline？ | 不能。新 AB/BA 两个方向都得到约 `+5.4%`，旧下降未复现。 |
| 是否可以只展示历史 Operating `-17.73%`？ | 不可以。那会忽略 Financial `+5.39%` 和新复测两个任务族都变慢。 |
| 为什么 Token 大降而 LLM wall 不降？ | wall time 受服务状态、排队/调度、生成阶段、固定请求开销影响，不与 prompt Token 线性等价；本实验复用共享 vLLM 服务，也没有独占服务器。 |
| 当前最终表述是什么？ | Token 和通信收益稳定；端到端时延存在约 5.44% 的受控代价。历史曾出现局部加速，说明存在工作负载与摊销条件，但尚未形成稳定结论。 |

建议在附录或问答页保留历史结果，在主实验页使用新 P0 表。这样既不隐藏冲突，也不让较弱设计覆盖较强复测。

## 9. 非文本 SemanticStateRef 证据

### 9.1 E4 机制闭环

| 检查点 | E4 结果 | 证明内容 |
| --- | --- | --- |
| holdout 质量 | 4/4 | 机制加入后任务完成 |
| 语义状态任务 | 3 个 | shared-memory float32 matrix 真实存在 |
| 非语义对照 | 1 个 table/DSL case | 不是每个任务强制制造 semantic state |
| producer/consumer | producer PID 与 Executor consumer PID 不同 | 真正跨进程，不是进程内对象传递 |
| 数值消费 | 9 条 numerical selection receipt | 消费者确实用矩阵计算 cosine top-k |
| 下游效果 | selected IDs 改变 downstream evidence | 不只是打开文件或计数 |
| 生命周期 | publish/open/consume/release，release bytes 匹配 | 对象所有权和释放闭环 |

### 9.2 可以和不能说的内容

| 可以说 | 不能说 |
| --- | --- |
| 非文本 dense state 通过 shared-memory StateRef 跨 PID 传递 | shared memory 已证明比文本/文件/mmap 更快 |
| Executor 对数值状态做真实 top-k 消费 | 所有中间状态都应使用 KV cache |
| receipt 和 release 使生命周期可审计 | 已实现 hidden-state/KV 跨进程传递 |
| 一例任务不使用 semantic state，说明按对象类型选择载体 | E4 是纯 transport benchmark |

P2/T2 不必重跑，除非 PPT 一定要提出“StateRef 载体本身带来性能优势”。当前主线只需要证明非文本机制、跨进程消费和生命周期，E4 已足够。

## 10. 共享记忆：存储、检索、真实复用与安全门

### 10.1 赛题所需记忆能力

| 能力 | 现有实现/证据 |
| --- | --- |
| 统一记忆单元 | MemoryRef + MemoryCommit + ExecutionArtifactRef |
| 必要字段 | E3 的 7/7 registry entry 均含 ID、来源 Agent、创建时间、任务主题、摘要 |
| 扩展字段 | tags、embedding ref、artifact ref、validator、输入 lineage |
| 索引与存储 | SQLite memory index + embedding registry + commit registry |
| 检索 | `hybrid_rrf:vector` 语义检索，满足 keyword/tag/semantic 中至少一种 |
| 跨角色使用 | Executor、Summarizer 均有 consumption receipt |
| 安全门 | runtime compatibility、输入 lineage、输出合同、validator 状态 |
| 不兼容处理 | fail-closed，拒绝后重算 |

### 10.2 E2：自然两条 10 轮链的主漏斗

```text
20 queries
  -> 18 queries with candidates       90%
  -> 7 compatible queries             35%
  -> 7 actual-use/effect queries      35%
  -> 2 skipped-step queries           10%
  -> 0 skipped-LLM-call queries        0%
```

| 口径 | 数值 | 答辩解释 |
| --- | ---: | --- |
| 连续任务质量 | 20/20 | 两组各 10 轮稳定通过 |
| 有候选 query 率 | 18/20 = 90% | 检索容易找到相似历史，但这不是命中主数字 |
| 实际使用率 | 7/20 = 35% | 推荐的主“记忆命中/使用率” |
| 行为效果率 | 7/20 = 35% | 每个真实使用都改变了行为 |
| 严格跳步率 | 2/20 = 10% | 有限但真实的省工 |
| skipped LLM call | 0/20 = 0% | E2 不证明模型调用节省 |
| 候选总数 | 48 | 候选级分母 |
| 兼容候选 | 9/48 = 18.75% | 通过安全门的候选 |
| 拒绝候选 | 39/48 = 81.25% | 防止历史被无条件注入 |
| receipt | 9 条，分布于 7 轮 | 一个 query 可消费多条记忆 |
| 使用类型 | assist 7、validated replay 2、exact replay 0 | 当前以辅助式复用为主 |

### 10.3 E3：真实性、安全性与跨角色证据

| 指标 | E3 结果 | 使用边界 |
| --- | ---: | --- |
| 质量 | 6/6 | warm suite 全通过 |
| queries | 6 | 小规模、有意构造的 warm suite |
| candidates | 16 | 候选级统计 |
| compatible/approved | 15 | 兼容率 93.75% |
| actual-use query | 5/6 = 83.33% | 不能当自然任务总体命中率 |
| consumption records | 23 | 多角色、多记忆消费 |
| behavioral effects | 23 | 消费均有可观察效果 |
| incompatible fixture | 1 个被拒绝并重算 | 负例验证 fail-closed |
| skipped step | 1 | 有真实省工 |
| skipped LLM call | 1 | 现有唯一明确的模型调用跳过证据 |

E3 的 83.33% 高使用率来自刻意 warm 的真实性套件，适合证明“能真实复用并安全拒绝”，不适合替代 E2 的自然链 35%。

## 11. 新 P1-lite：短窗口记忆净收益

### 11.1 P1-lite 主表

| 指标 | L3 相对 L2 | 判断 |
| --- | ---: | --- |
| task time | `+3.82%` | 未形成端到端加速 |
| LLM wall | `+3.58%` | 没有跳过 LLM call |
| non-LLM residual | `+5.41%` | 检索、门控、记录有成本 |
| total tokens | `+1.97%` | actual-use 上下文略增 |
| wire bytes | `+7.19%` | 记忆引用/消费路径增加通信 |
| LLM calls | 不变 | 不能声称模型调用节省 |
| skipped steps | +4 | 确定性步骤确实被跳过 |
| skipped LLM calls | 0 | 跳步未触及主要模型成本 |

### 11.2 短窗口漏斗

```text
20 queries
  -> 30 candidates
  -> 4 compatible/approved
  -> 4 consumed/effect
  -> 4 skipped steps
  -> 0 skipped LLM calls
```

| 指标 | 数值 |
| --- | ---: |
| actual-use/effect rate | 4/20 = 20% |
| candidate compatibility | 4/30 = 13.33% |
| candidate rejection | 26/30 = 86.67% |
| 命中的唯一任务位置 | Financial R2/R4，在 AB/BA 中各出现一次 |
| 命中 pair 时延 | 平均仍慢约 0.989 s；3/4 更慢 |

### 11.3 P1-lite 的设计边界

P1-lite 是 L2 OFF 与 L3 actual-use 的一轮 AB/BA 对比，**不是**“冻结完全相同的记忆快照 + OFF/gate-only/actual-use/incompatible-negative”的严格四臂实验。因此它可以回答：

- 当前五轮窗口中是否出现真实消费和跳步；
- 打开完整记忆路径后整体 Token/wire/time 如何变化；
- 当前跳过的工作能否覆盖门控成本。

它不能精确分离：检索成本、兼容门成本、记忆上下文成本和 actual-use 收益各占多少。

## 12. 为什么 E2 的 35% 与 P1 的 20% 不冲突

| 实验 | 窗口和目的 | actual-use | skipped step | skipped LLM | 正确解读 |
| --- | --- | ---: | ---: | ---: | --- |
| E2 | 两条自然 10 轮 L3 链 | 7/20 = 35% | 2 query | 0 | 长链中复用机会逐步出现 |
| P1-lite | 五轮 causal-core，L2/L3 AB/BA | 4/20 = 20% | 4 | 0 | 短窗口中真实使用较少且未抵消成本 |
| E3 | 刻意 warm 的真实性套件 | 5/6 = 83.33% | 1 | 1 | 证明能力上限、负例拒绝和真实省工，不代表自然分布 |

三个数字的分母、任务构造和实验目的不同。PPT 主页面用 E2 的 35%，旁边用 E3 证明真实性和安全门；P1-lite 放在“净收益边界”或问答页，说明当前短窗口尚未形成加速。

可用但谨慎的观察是：五轮窗口 actual-use 为 20%，十轮自然链为 35%，说明随着相关历史积累复用机会可能增加。由于二者不是同一冻结快照和严格增长实验，不应写成确定的随轮次增长曲线或因果规律。

## 13. CodeAct 与其他机制的边界

| 场景 | 是否需要 LLM 临场写 Python | 说明 |
| --- | --- | --- |
| E5 adaptive CodeAct | 是 | Executor LLM 生成受限 Python；18 个 Python、7 个 DSL，25/25，零 fallback |
| P0/P1 `deterministic_codeact` | 否 | Executor 使用确定性执行路径；Planner、Retriever、Summarizer 仍调用 vLLM |
| typed Protobuf | 否 | 协议机制本身不依赖 LLM 写代码 |
| StateRef/embedding selection | 否 | 数值状态发布和选择是运行时机制 |
| memory retrieval/compatibility | 否 | 检索和兼容门不要求 LLM 生成代码 |

因此 CodeAct 用于证明复杂操作能力和实现完整性，不应被用来解释 P0/P1 的 Token 或时延变化，也不应被提升为与三个赛题核心支柱并列的第四主线。

## 14. 跨实验一致性与冲突总表

| 主题 | 历史/基线证据 | 新证据 | 最终判断 |
| --- | --- | --- | --- |
| 质量 | E1-E5 全通过 | P0/P1 80/80 | 一致：质量门稳定 |
| 控制面压缩 | E1 L0/L1 `-83.05%` | P0 L0/L3 `-78.74%` | 一致：强优势 |
| wire 压缩 | E1 L0/L3 `-64.85%` | P0 `-64.77%` | 高度一致：强优势 |
| total Token | E1 L0/L3 `-47.40%` | P0 `-46.48%` | 高度一致：强优势 |
| typed control 是否省 Token | E1 L0/L1 `+2.70%` | P0 是整链，不能用于纯归因 | Token 优势来自后续语义选择/hydration，不来自 Protobuf 本身 |
| 端到端时延 | 历史 E1 `-6.32%` | P0 `+5.44%`，AB/BA 同方向 | 冲突；采用新 P0 为 headline，历史降级为观察 |
| 自然记忆使用率 | E2 35% | P1 短窗口 20% | 不冲突；窗口和设计不同 |
| 记忆安全门 | E2 拒绝 81.25%；E3 有负例重算 | P1 拒绝 86.67% | 一致：fail-closed 是稳定特征 |
| 记忆省工 | E2 跳 2 步；E3 跳 1 步和 1 次 LLM | P1 跳 4 步、0 LLM | 一致：有真实但有限省工，尚非广泛加速 |
| 非文本机制 | E4 跨 PID 生命周期闭环 | 未重跑 T2 | 已足够证明机制，不增加载体性能声称 |
| Prefix/LogitState | 正式基线无有效结论 | 新实验未包含 | 继续后置 |

## 15. PPT 可直接使用的结论与禁用表述

### 15.1 推荐结论

| 场景 | 推荐文字 |
| --- | --- |
| 总结页 | 100% 保持本轮任务质量，以约 5.44% 的端到端时延代价换取 46.48% 的 Token、64.77% 的 wire bytes 和 78.74% 的控制面字节下降 |
| 结构化通信 | 同样 50 条消息下，typed control 将控制面字节降低 83.05%；它解决的是接口与通信问题，不直接减少 Token |
| 非文本状态 | float32 语义状态通过 shared-memory StateRef 跨 PID 被 Executor 数值消费，publish/open/consume/release 全程有回执 |
| 记忆主数字 | 两组 10 轮自然连续任务中，实际记忆使用率 35%，所有实际使用均产生可观察行为效果 |
| 记忆安全 | 81.25% 的候选因不兼容被拒绝，系统宁可重算，也不无条件注入历史 |
| 记忆省工边界 | 已观察到跳步和一次真实跳过 LLM call，但短窗口复测尚未形成净时延收益 |
| CodeAct | 25/25 能力覆盖，18 个 bounded Python、7 个 DSL、零 fallback；作为执行完整性支撑 |

### 15.2 禁止或必须降级的表述

| 不应写 | 原因 | 替代表述 |
| --- | --- | --- |
| “StateBus 时延下降 6.32%” | 新 AB/BA 未复现 | 历史曾有下降观察；当前公平复测为 +5.44% 代价 |
| “共享内存带来 6.32% 加速” | E1 混合多个机制，E4 无载体对照 | shared memory 证明跨 PID 非文本消费与生命周期 |
| “结构化协议节省 46.48% Token” | L0/L1 total Token 反而 +2.70% | 整链通过语义选择/hydration 降低 Token |
| “记忆命中率 90%” | 90% 只是有候选 query | 自然实际使用率 35%，候选 query 率 90% |
| “记忆复用普遍加速” | P1 +3.82%，E2 0 skipped LLM | 复用真实且安全，目前省工有限 |
| “E3 命中率 83.33% 代表总体” | E3 是刻意 warm suite | E3 用于真实性/负例；总体主数字用 E2 35% |
| “实现 KV/hidden-state 跨进程传递” | 当前未实现且指导文件限定为 Future Work | 当前实现为 dense semantic state；KV 仅 Engine-Local Prefix Reuse future work |
| “openEuler/跨机通用验证完成” | 证据仅覆盖单个 openEuler 24.03 容器 | 已在单 openEuler 容器范围验证 |

## 16. PPT 实验页建议

### 16.1 页面与证据映射

| PPT 区域 | 建议内容 | 图表形式 | 数据来源 |
| --- | --- | --- | --- |
| 1-6：问题与架构 | 文本传递为何无法形成可复用状态；四级状态提升链 | 一条因果链，不放性能数字 | 固定叙事、赛题要求 |
| 8-9：typed control | L0/L1 同 50 消息，control/wire bytes 大幅下降，Token 不降 | 4 指标对比表或双柱图 | E1 |
| 10-11：非文本状态 | producer -> StateRef -> Executor PID -> selected IDs -> release | 生命周期流程 + 3 个数字 | E4；消费者写 Executor，不写 Selector |
| 12-13：记忆 | query -> candidate -> compatible -> consumed/effect -> skipped | 漏斗图；主数字 35% actual-use | E2；E3 作负例旁证 |
| 14：CodeAct | 18 Python + 7 DSL，25/25，0 fallback | 简单堆叠条或表 | E5 |
| 17-18：安全机制 | artifact validation、compatibility、拒绝后重算 | 状态机/链路图 | E1/E3 |
| 20：评估契约 | 同任务、质量门、序列化 AB/BA、共享服务边界 | 实验设计表 | P0/P1 operator guide |
| 21：总矩阵 | C/N/M/CodeAct/工程门各自证明什么 | 覆盖矩阵 | E0-E6 |
| 22：效率 | Token/wire/control 下降 + task time 代价 | 一张收益/代价对照表 | 新 P0 |
| 23：真实性 | E4 生命周期 + E2 20 轮记忆 timeline | 两块证据，不做 T2 虚构梯子 | E2/E4 |
| 24：结论 | 三个支柱、统一创新、关键数字和边界 | 3 张支柱卡 + 1 条 tradeoff | 本文一页结论 |

### 16.2 最值得放入 PPT 的四张图

1. **整链收益/代价图**：Token `-46.48%`、wire `-64.77%`、control `-78.74%`、task time `+5.44%`、质量 100% 对 100%。下降与上升必须用不同语义颜色，不用同一根“越高越好”坐标轴。
2. **记忆真实性漏斗**：E2 的 `20 -> 18 -> 7 -> 7 -> 2 -> 0`，明确每级分母和含义。
3. **非文本生命周期图**：producer PID、shared-memory StateRef、Executor consumer PID、9 条 selection receipt、release bytes matched。
4. **证据-亮点矩阵**：结构化通信看 bytes，非文本看跨 PID receipt/lifecycle，记忆看 compatibility/use/effect，CodeAct 看覆盖率。不要让所有亮点都只落到 Token 一项。

### 16.3 时延页面的公平表达

时延不应隐藏，也不应把相对增长放大成失败。建议同时放：

| 展示项 | 数字 | 为什么展示 |
| --- | ---: | --- |
| 相对 task time | +5.44% | 完整、透明 |
| 绝对 task time | +1.414 s/任务 | 便于理解实际代价 |
| non-LLM residual | 2.633 -> 3.552 s/任务 | 指出安全/状态机制的成本区域 |
| Token | -46.48% | 与代价并列形成系统权衡 |
| 质量 | 100% -> 100% | 防止效率数字脱离正确性 |

不要将 non-LLM `+34.92%` 单独放大，因为其基数较小；如展示相对值，必须同时展示绝对值。也不要把 Token 减少直接换算成推理费用或吞吐收益，除非服务计费和吞吐实验另有证据。

## 17. 当前是否还缺实验

从赛题和当前 PPT 主线看，核心机制证据已经齐全：结构化通信、非文本状态、共享记忆、连续 10 轮、CodeAct、质量门、Token/bytes/time/hit 指标均有数据。当前不是“必须继续跑实验才能答辩”的状态。

| 潜在实验 | 是否必需 | 何时才值得做 |
| --- | --- | --- |
| 再跑 P0 | 否 | 当前 P0 有 AB/BA 和 80/80 总质量，除非运行环境发生变化 |
| 严格 P1 四臂冻结快照 | 可选 | 若要把 memory gate 成本与 actual-use 收益分别量化 |
| T2 同选择载体对比 | 默认否 | 只有要宣称 StateRef 载体更快时才需要 |
| 扩充数据集/更换任务 | 否 | 会造成特化嫌疑，且不关闭当前赛题缺口 |
| Prefix/APC | 否 | 不解决当前三支柱证据缺口 |
| LogitState | 否 | 当前没有稳定、可交付且赛题必需的结论 |
| 演示视频验收 | 是，交付层面 | 若赛题提交材料尚无视频，应优先完成 |

若不增加性能声称，最合理的下一步是用本文修改 PPT、统一口径并检查演示视频，而不是继续制造更多实验矩阵。

## 18. 数据来源与追溯路径

### 18.1 汇总与解释文档

| 来源 | 用途 |
| --- | --- |
| `docs/reports/contest_recovery_fixed_baseline_experiment_compendium_20260724.md` | E0-E6 固定基线总账、逐实验数据和边界 |
| `docs/reports/contest_recovery_baseline_asset_audit_20260724.md` | 容器 root 全量资产审计、正式/诊断/后续产物隔离 |
| `docs/reports/contest_recovery_ppt_evidence_reconciliation_20260724.md` | 两版主 PPT 的页级证据校正 |
| `docs/reports/contest_recovery_supplemental_experiment_operator_20260724.md` | P0/P1-lite 的运行设计、环境和边界 |
| `docs/reference/题目.md` | 赛题原始要求 |

### 18.2 新复测原始汇总

| 来源 | 用途 |
| --- | --- |
| `/home/qcrs/statebus/runs/contest_recovery_supplemental_all_20260724_210057/supplemental_summary.md` | P0/P1 人类可读汇总 |
| `/home/qcrs/statebus/runs/contest_recovery_supplemental_all_20260724_210057/supplemental_summary.json` | lane、pair、family、token、bytes、time、memory funnel 的机器可读来源 |

### 18.3 主 PPT

| 文件 | 用途 |
| --- | --- |
| `docs/reports/StateBus-v2-答辩终版-06-字体最终统一版.pptx` | 主答辩内容基线 |
| `docs/reports/StateBus-v2-答辩终版-07-演示化重构版.pptx` | 演示化页面结构与叙事参考 |

## 19. 最终判断

现有实验不是“只有 Token 节省”，而是分别从五个互补角度支撑主线：

| 角度 | 核心证据 |
| --- | --- |
| 通信效率 | control `-78.74%`、wire `-64.77%`，历史纯 L0/L1 control `-83.05%` |
| 上下文效率 | prompt Token `-53.28%`、total Token `-46.48%` |
| 非文本真实性 | shared-memory float32、跨 PID、9 条选择回执、生命周期闭环 |
| 记忆真实性与安全 | 自然 actual-use 35%、effect 35%、候选拒绝 81.25%、负例重算 |
| 工程与能力完整性 | E0 135 passed、E6 558 passed、E5 25/25 CodeAct/DSL |

同时，P0/P1 把不能回避的边界量化清楚：完整链当前带来 `+5.44%` 的 task time，短窗口记忆为 `+3.82%` 且没有跳过 LLM call。因此答辩的技术主张应收敛为：

> StateBus 的创新是让跨 Agent 状态经过类型约束、跨进程消费回执、产物验证和兼容门之后再提升为可复用资产。它已经稳定降低通信与上下文负担，并把安全、可追溯机制的运行代价量化在约 5.44%；记忆复用真实存在，但当前优先证明安全和可观察性，而不是夸大为普遍加速。
