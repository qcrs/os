# 答辩共享记忆：历史处理方法如何用于后续任务

这份文档用于梳理共享记忆部分的叙事和展示重点。Memory 这一页要回答一个具体问题：同一类工作再次出现时，StateBus 怎样找到过去的处理记录，判断它对当前任务有多大帮助，并把合适的内容交给后续执行步骤。

## 1. 这一页要讲的中心

建议把主题定为：

> **共享记忆：从历史任务找到可用方法，让下一轮少做重复工作。**

上一轮任务留下的内容不只有答案，还包括结果来源、处理方法和适用条件。下一轮任务的数据可能已经变化，所以系统需要先找历史记录，再判断当前能参考什么、能复用什么，以及哪些内容不该使用。

评委看完这一页，应当理解四件事：

1. Memory 保存什么，为什么一轮任务结束后会留下这些内容；
2. 下一轮的查询从哪里来，历史候选如何排序；
3. 排序之后为什么还要检查任务条件，以及结果有哪些；
4. 选中的记忆实际交给哪个角色，怎样改变本轮工作。

这一页的重点是**跨任务复用过程**。Memory 的文件格式、所有兼容字段和索引实现属于支撑说明，不应和复用过程争夺画面。

## 2. Memory 在任务中什么时候发生

当前实现中，Retriever 和 Memory Store 各有分工：Retriever 处理本轮资料并形成查询线索；Runtime 使用这些线索查询历史 Memory；之后 Runtime 决定哪些 Memory 能进入哪个执行步骤。

流程可以这样读：

```text
任务 N
Executor 生成结果
  -> Runtime 验证 Artifact 和质量报告
  -> 记录来源、任务条件和 execution recipe
  -> MemoryCommit 写入索引

任务 N+1
Retriever 形成当前查询、实体标签和 query embedding
  -> Runtime 创建 MemoryQuery 并查询历史记录
  -> 多路排序和兼容性判断
  -> Runtime 按后续步骤选择 MemoryRef，写入对应 CapabilityGrant
  -> Dispatcher 为目标角色整理 Memory 输入
  -> Executor 使用 recipe，或其他获准角色读取摘要和来源
```

Memory 查询发生在 Retriever 已形成当前检索结果之后。当前代码从 Retriever 请求中取查询文本和目标实体，并使用 query embedding；Runtime 随后调用 `lookup_hybrid()`。Retriever Agent 负责本轮资料检索，历史 Memory 由 Runtime 查找，再交给后续获准的角色步骤使用。

Runtime 会在每个执行 attempt 上选择可用的 Memory ID，并把这些 ID 放入该步骤的 `CapabilityGrant`。Dispatcher 根据 Grant 加载 Memory 内容。当前最清楚、也有机制实验支持的消费位置是 Executor：Executor 读取历史 execution recipe，在本轮输入上执行。Summarizer 等角色也可以取得获准的摘要或来源信息，但本页不应把所有角色都说成已经发生同一种复用。

相关位置：[`adaptive_dispatcher.py`](../../src/statebus/runtime/adaptive_dispatcher.py) 中的 Retriever 结果处理、`MemoryQuery` 和 Memory 输入加载；[`adaptive_runtime.py`](../../src/statebus/runtime/adaptive_runtime.py) 中的逐步骤 Memory 选择；[`adaptive_mainline.py`](../../src/statebus/runtime/adaptive_mainline.py) 中的 Memory 写入。

## 3. 上一轮保存什么，保存在哪里

### 3.1 保存规则

Memory 按写入条件从任务结果中构造。当前主线使用已完成任务的 Executor Artifact。Runtime 要求任务完成、提供 `CanonicalTaskSpec` 和查询 embedding，确认产物已验证、质量报告对应同一个 Artifact，并且输入来源和 execution recipe 齐备，之后才形成并提交 `MemoryCommit`。

答辩时可以把规则简化为：

> **结果通过验证，来源和处理方法也能说明白，这次工作才进入后续记忆。**

这一规则值得用一小步表示，因为它解释了后续候选从哪里来，也回应赛题要求的记忆保存。页面不需要列出所有 hash、receipt 和 admission 字段。

### 3.2 Memory 记录的内容

`MemoryRef` 保存评委容易理解的描述信息：

```text
memory_id
source_agent / source_task_id
created_at
task_theme / tags
summary
```

主线记录还会关联：

- 已验证 Executor Artifact 的 ID 和内容 hash；
- execution recipe 及 recipe hash；
- 输入 lineage 和 schema；
- task spec、输出合同、Runtime signature 和 Validator digest；
- embedding 的引用，以及相关 manifest 信息。

Memory 记录同时包含可搜索的描述、语义向量、执行方法和适用条件。搜索使用摘要、主题、标签和向量发现候选；Executor 复用时读取 recipe；兼容性判断使用任务合同、输入和 Runtime 信息。

### 3.3 磁盘位置和格式

`AdaptiveMainlineRequest` 可以显式指定 `memory_store_root`。未指定时，当前实现使用：

```text
<runtime_root>/memory_index/
```

后续任务要检索上一轮的记录，必须使用相同的 `memory_store_root`，或使用能解析到同一目录的 `runtime_root`。Runtime 启动时会从这些持久化文件重新加载 Memory；若每轮任务指向不同目录，记忆就不会跨这些运行共享。

持久化目录包含：

| 文件 | 保存内容 | 用途 |
|:--|:--|:--|
| `memory_index.sqlite3` | Memory ID、主题、摘要、来源 Agent、创建时间、类型、状态和标签；SQLite 支持 FTS5 时另建全文索引 | 关键词和标签查询 |
| `commit_registry.json` | 按 Memory ID 保存 `MemoryCommit` 的规范化 JSON，包括 `MemoryRef`、任务合同、recipe、Artifact 引用和质量/来源元数据 | Memory 记录的持久内容 |
| `embedding_registry.json` | 按 embedding ID 保存维度、编码信息、来源文本 hash 和 float 向量 | 语义相似度排序 |
| `admission_receipt_registry.json` | Memory 写入决定及其关联 hash | 恢复已提交记录时确认提交状态 |

实际 Artifact 文件保存在任务 workspace。Memory 记录保存 Artifact ID、路径和内容 hash，不把 Artifact 文件复制进 `memory_index`。向量索引的持久内容是 JSON registry；如运行环境装有 FAISS，代码会从已加载的向量构造进程内索引，FAISS 索引不是持久化真源。

这部分是讲述人用来准确回答“Memory 存在哪、是什么格式”的实现说明。PPT 主画面不必放四个文件名；用一个 `Memory Store` 方框，旁边写“SQLite 元数据索引 + JSON 记忆/向量记录，Artifact 保存在 workspace”即可。

## 4. 下一轮怎样找到候选

Runtime 根据当前任务组装 `MemoryQuery`。在当前 Retriever 路径中，查询信号来自：

- **关键词**：Retriever 请求中的 query 文本；
- **标签**：目标实体；
- **语义向量**：当前查询对应的 query embedding。

Memory Store 分别产生三份候选排名：

| 检索路 | 当前实现 | 它回答的问题 |
|:--|:--|:--|
| 关键词 | SQLite FTS5 搜索主题、摘要、来源任务、来源 Agent 和标签文本 | 记忆描述中是否出现了相关词 |
| 标签 | 当前任务实体与 Memory 标签重合度 | 这条记录是否关联同一实体或任务主题 |
| 向量 | query embedding 与历史 Memory embedding 的 cosine similarity | 查询和历史描述的语义是否接近 |

三路分数的含义和数值范围不同，不能直接相加。StateBus 保留各路排名，再用 Reciprocal Rank Fusion 合并：

```text
RRF(m) = 1 / (k + r_keyword(m))
      + 1 / (k + r_tag(m))
      + 1 / (k + r_vector(m))
```

`r_keyword`、`r_tag` 和 `r_vector` 分别是候选在对应检索路中的名次；候选没有出现在某一路时，不计该项。当前默认 `k=60`，名次从 1 开始。候选在多个检索路都靠前时，RRF 分数会增加。PPT 不必解释 `k` 的取值，公式旁只需说：

> **关键词、标签和向量分别排序，RRF 按名次合并候选。**

RRF 解决的是“先看哪些历史记录”。它不判断历史记录能不能复用，也不代表复用成功。

## 5. 排名之后为什么有三种复用结果

任务表述相近时，当前输入、执行合同和输出要求仍可能不同。Memory 因此按可提供的帮助程度分为 `ASSIST`、`VALIDATED_REPLAY` 和 `EXACT_REPLAY`：有些记录适合参考，有些允许复用处理方法，有些要求条件完全一致才有恢复旧结果的基础。不符合使用条件的候选会被拒绝，当前任务继续自己的处理流程。

| 结果 | 当前任务拿到什么 | 当前任务还要做什么 |
|:--|:--|:--|
| `ASSIST` | 历史摘要、策略或路线提示 | 正常使用本轮输入完成计算；不把旧结果当成本轮答案 |
| `VALIDATED_REPLAY` | 先前验证过的 execution recipe 或程序内容 | Executor 在本轮输入上重新执行，生成新 Artifact，并走本轮质量验证 |
| `EXACT_REPLAY` | 与严格相同任务和输入绑定的历史结果 | 满足 exact key 和运行条件时才有直接恢复结果的基础 |
| 不兼容 / 不允许 | 不把候选交给消费角色 | 记录原因，按当前批准步骤处理本轮输入 |

### 5.1 `ASSIST`：参考历史做法

当前任务与历史记录相关，但输入或任务细节存在变化，或者策略不允许更强的 replay 时，Memory 可以只提供摘要、历史策略或路线提示。Executor 仍处理本轮输入。这一档适合帮助当前角色少重新整理背景，不表示跳过执行。

### 5.2 `VALIDATED_REPLAY`：沿用方法，在新输入上重算

这是 Memory 页面和现有机制实验最值得强调的一档。当前任务与历史处理方法兼容，但本轮数据仍可能不同。Runtime 把历史 recipe 交给 Executor；例如 DSL 路径会从 recipe 恢复操作列表，在当前输入表上执行，重新生成 Artifact 并做质量验证。

因此，本页应明确说：

> **复用的是已经验证过的处理方法；本轮数据仍然重新计算，本轮结果仍然重新验证。**

它减少的是重复生成程序或方法的工作，不应概括成“直接复用旧答案”。

### 5.3 `EXACT_REPLAY`：只用于严格相同的任务

Exact replay 要求任务合同、输入 Artifact hash、Runtime 和相关版本、输出合同等条件严格匹配。它描述的是比 validated replay 更严格的复用边界。

需要注意当前运行路径：`AdaptiveRuntimeEngine._select_memory_for_attempt()` 中，exact artifact restoration 被标为当前 09B 路径之外；该路径会把 legacy exact match 降为 `ASSIST`。所以答辩主图不应把直接恢复旧 Artifact 画成当前 Memory 实验已证明的主要流程。若要展示 exact replay，应单独引用确实执行了该路径的结果。

### 5.4 拒绝候选为什么也要画

Memory 的价值不仅是找相似记录，还要避免把不适用的记录交给下游。若任务意图、输入 schema/lineage、Runtime 或输出合同不兼容，Runtime 不使用该候选，当前任务仍沿正常路径处理。

拒绝分支不必包装成“安全亮点”。它是复用判断的一种正常结果，也能让评委看出系统会区分“搜到了”与“适合复用”。

## 6. 选中的记忆在哪里被使用

检索和消费不是同一动作：

```text
候选被找到
  -> 通过兼容性和当前策略判断
  -> Runtime 为目标 step 选择 Memory ID
  -> MemoryRef ID 进入 CapabilityGrant
  -> Dispatcher 为获准角色构造 Memory 输入
  -> 角色读取并产生消费记录
```

对 `VALIDATED_REPLAY`，消费重点在 Executor：

```text
历史 Memory 中的 recipe
  + 当前 Grant 允许的输入
  -> Executor 在当前输入上执行
  -> 本轮 Artifact
  -> 本轮质量验证
  -> 下游 Summarizer
```

本轮 `MemoryConsumptionRecord` 记录 consumer role/step、Memory ID、复用等级、兼容结论、是否跳过生成步骤或模型调用，以及下游 Artifact 引用。它用来区分候选命中、角色实际读取和执行路径实际改变。

不同 Agent 可以在后续步骤读取适合自己角色的记忆输入，但讲解和实验应具体到实际消费者。当前 Memory 机制实验最有力的例子是 Executor 复用 recipe；主实验另记录了跨角色消费事件，可以作为系统支持角色间复用的补充证据，不应代替 Executor 的主例子。

## 7. 一页 PPT 应该怎样展示

### 7.1 页面主题和评委应记住什么

建议标题：

> **共享记忆：先找到历史做法，再决定本轮怎么用**

页面中心句：

> **StateBus 根据当前任务检索历史记录；Executor 可以在新输入上重用验证过的方法，并生成本轮结果。**

核心视觉应落在“从候选到 Executor 实际复用”的过程。写入规则和落盘结构要出现，但作为较小的前置说明；RRF 公式用来解释排序，不能占据主画面。

### 7.2 主图草案

```text
上一轮任务                                      当前任务

Executor Artifact                              Retriever 查询线索
      ↓                                               ↓
结果验证通过                                   keyword / tags / vector
      ↓                                               ↓
保存 MemoryRef + recipe ──> Memory Store ──> RRF 候选排序
                               │                    ↓
                          SQLite + JSON        兼容性判断
                                                    ├─ ASSIST：摘要给目标角色参考
                                                    ├─ VALIDATED_REPLAY：Runtime Grant
                                                    │       ↓
                                                    │  Executor 读取 recipe
                                                    │       ↓
                                                    │  本轮输入 → 重算 → 新 Artifact
                                                    ├─ REJECT：不使用，按当前计划处理
                                                    └─ EXACT：严格匹配边界，小字说明
```

版面可以分成三块：

**左侧小块：上一轮留下什么**

画一张 Memory 卡片，显示赛题要求的基本信息和本项目的关键字段。以下内容是字段示意，不对应某条具体实验记录：

```text
memory_id: <memory-id>
source_agent: executor
task_theme: <task-family>
summary: <verified method summary>
tags: [revenue, quarterly]
recipe: compare_metric.v1
artifact_ref: <verified-artifact-ref>
```

旁边用一行说明写入条件：“产物验证通过，来源和 recipe 完整”。不展开质量门的内部字段。

**中间主块：检索和判断**

画三条小输入 `关键词 / 标签 / 向量` 汇入 `RRF`，再进入兼容性判断。公式只占一个小角标：

```text
RRF(m) = 1 / (k + r_keyword(m))
      + 1 / (k + r_tag(m))
      + 1 / (k + r_vector(m))
```

兼容性判断旁边只列几个容易懂的条件：任务用途、输入结构、输出要求和 Runtime 是否匹配。不要把完整字段清单塞进图里。

**右侧主块：复用落点和结果**

突出 `VALIDATED_REPLAY → Executor`：Executor 取 recipe，在本轮输入上计算，产出新的 Artifact 并通过本轮质量验证。`ASSIST` 和“拒绝后正常处理”作为较小分支。`EXACT_REPLAY` 放页脚或讲解备注，标明当前主实验没有把直接恢复作为主证据。

### 7.3 存储信息在页面上的深度

评委应知道记忆确实被持久保存，但不需要在主视觉中阅读文件名。建议页面脚注或存储卡写：

```text
SQLite：Memory 描述和关键词索引
JSON：MemoryCommit、向量和 admission receipt
workspace：执行 Artifact 文件
```

问答时再补充默认目录 `<runtime_root>/memory_index/` 和四个文件名。这样既回答“保存在哪里、是什么格式”，也不把一页变成存储实现说明。

### 7.4 赛题要求在这一页怎样出现

| 赛题要求 | 这一页的呈现 | 主要证据 |
|:--|:--|:--|
| 保存记忆及基本元数据 | 小型 Memory 卡显示 ID、来源 Agent、时间、主题和摘要 | `MemoryRef` 与 `MemoryCommit` |
| 按关键词、标签或语义查找 | 三路候选汇入 RRF；公式简要解释排名如何合并 | Memory 查询结果和 source ranks |
| 后续任务中的 Agent 能复用 | Runtime 按目标 step 选择 MemoryRef；突出 Executor 读取 recipe 的实测路径 | `MemoryConsumptionRecord`、validated replay 和 skipped Executor generation |
| 两组关联任务及连续运行 | 在测试部分展示两个任务组的连续轮次；本页只用相邻任务说明 Memory 的时间关系 | 连续任务 manifest 与实际运行记录 |
| 记忆命中和整体效果 | 页面下方区分候选、消费、replay，再列开销变化 | Memory off/on 对照 |

记忆页不需要独自证明系统连续运行不少于 10 轮。它要把跨任务关系说清楚；连续任务数量和稳定运行证据在测试部分集中展示。任务 manifest 能说明任务如何关联，轮数和运行通过情况仍要引用实际运行结果。

## 8. 实验结果分别证明什么

Memory 实验要分开报告检索和复用事件。当前机制对照有 8 个 Memory-on 位置，对应 8 个 off 位置：

| 观察 | 结果 | 能说明什么 |
|:--|--:|:--|
| candidate hit | 6/8 | 检索找到了历史候选 |
| actual consumption | 4/8 | 记忆进入角色输入并被读取 |
| validated replay | 4/8 | 复用路径实际发生 |
| skipped Executor boundary | 4/8 | Executor 的重复生成步骤确实被跳过 |
| 质量通过 | 8/8 | Memory-on 结果仍通过本组任务的质量检查 |

同一组 off/on 对照中：

| 指标 | `off` | `on` | 变化 |
|:--|--:|--:|--:|
| provider requests | 18 | 12 | 降低 33.33% |
| provider tokens | 31,466 | 17,581 | 降低 44.12% |
| 任务耗时总和 | 550.2 s | 401.0 s | 降低 27.12% |

页面上适合把漏斗和收益放在一起：

```text
8 个 Memory-on 任务
  -> 6 个找到候选
  -> 4 个实际消费并进入 validated replay
  -> 4 个跳过 Executor 生成

质量：8/8 通过
requests：18 → 12
provider tokens：31,466 → 17,581
E2E 总和：550.2 s → 401.0 s
```

不要把 6/8 的 candidate hit 叫作 6/8 成功复用。数字顺序本身要让评委看到从“找到”到“用上”之间的区别。

Memory 消融结果证明在这组任务里，开启 Memory 后请求、模型 token 和任务时间下降；主实验则观察到 24 次 Memory 查询中 22 次有候选、12 次实际消费和 12 次 validated replay。主实验同时启用了多项 StateBus 机制，整体收益不能全部归因于 Memory。更完整的对照、分母和逐任务结果见 [`docs/experiments/results.md`](../experiments/results.md) 与 [`tests/evidence/mechanisms/results.md`](../../tests/evidence/mechanisms/results.md)。

赛题还要求至少两组相关连续任务，并要求连续运行不少于 10 轮。这部分应由测试章节展示任务序列和运行证据；Memory 机制页的 8 组 off/on 消融适合证明复用收益，不能单独代替连续任务轮数的证明。当前仓库包含 `cross_period_financial` 和 `csv_correlation_replay` 两组 10 轮任务定义，可从对应 manifest 说明任务关系；正式展示轮数时还应引用实际运行记录。

## 9. 讲述顺序

可以这样讲：

> Memory 处理的是跨任务重复工作。上一轮任务完成后，Runtime 保存通过验证的结果、来源和执行方法。下一轮 Retriever 先形成当前查询，Runtime 用关键词、标签和向量找出候选，再用 RRF 合并三路排名。排名靠前只说明值得检查，Runtime 还要看当前任务、输入和输出要求是否匹配。普通相关记录可以作为参考；当处理方法兼容时，Executor 会拿到历史 recipe，在本轮输入上重新计算并生成新 Artifact；条件不合适的候选就不使用。实验里我们分别统计找到候选、实际消费、validated replay 和跳过 Executor 生成，避免把检索命中当成复用效果。

讲完后，评委应记住：**Memory 把已验证的处理方法带到下一轮；Runtime 根据当前任务判断用作参考、在新输入上重跑，还是不使用。**

## 10. 讲述边界

- Memory 的 query embedding 用来找历史任务记录；Embedding State 页面讲的是当前任务中怎样从候选证据选择内容。两者可以都用向量，但查询对象和后续用途不同。
- RRF 只合并候选排名。是否兼容、进入哪个角色、是否实际改变执行是后续阶段。
- 写入规则要简要说明，重点放在保存的内容和下一轮消费，不展开 receipt 和 hash 的完整结构。
- 当前最有力的 Memory 复用例子是 Executor 复用 recipe，并在当前输入上重算；不要说成无条件复制旧答案。
- 单独展示 Memory 的 off/on 结果；主实验的整体改善不能全部算作 Memory 带来的收益。
- `EXACT_REPLAY` 是严格复用边界，但当前 adaptive 主线的 Memory 消费证据不支持把它画成直接恢复旧 Artifact 的主路径。

## 相关实现和证据

- Memory 查询、RRF 和兼容性判断：[`src/statebus/memory/store.py`](../../src/statebus/memory/store.py)
- Memory 数据模型：[`src/statebus/memory/models.py`](../../src/statebus/memory/models.py)
- 查询时机、Executor 消费和 Memory 输入投影：[`src/statebus/runtime/adaptive_dispatcher.py`](../../src/statebus/runtime/adaptive_dispatcher.py)
- Runtime 按执行步骤选择 Memory：[`src/statebus/runtime/adaptive_runtime.py`](../../src/statebus/runtime/adaptive_runtime.py)
- Memory 提交和持久化入口：[`src/statebus/runtime/adaptive_mainline.py`](../../src/statebus/runtime/adaptive_mainline.py)
- Memory 搜索、消费和 replay 设计说明：[`docs/implementation/memory.md`](../implementation/memory.md)
- 连续任务示例：[`docs/implementation/walkthroughs.md`](../implementation/walkthroughs.md)
- 赛题要求：[`docs/reference/题目.md`](../reference/题目.md)
