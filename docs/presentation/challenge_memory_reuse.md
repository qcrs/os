# 技术难点三：记忆检索到了，什么时候可以真正复用

这一页讨论共享记忆从“候选记录”变成“当前任务输入”的过程。它要说明 StateBus 如何判断历史工作对当前任务有多大帮助，以及复用时怎样避免把上一轮的答案直接当成本轮结果。

## 这一页要回答的具体问题

建议把问题固定为：

> **记忆检索到了，什么时候可以真正复用？**

查询结果相似，只能说明历史记录值得看。当前任务的输入、目标时间范围、输出合同、来源数据、Runtime 版本和校验规则可能已经变化。Runtime 需要区分几种情况：历史记录可以提供参考，历史方法可以在新输入上重算，严格相同的任务才允许恢复旧结果，或者这条记录应该被拒绝。

这页要让评委清楚“候选命中”和“实际复用”是两个动作。

## 为什么值得作为技术难点

共享记忆如果只做成“把摘要写入向量库，再按相似度取回来”，很容易出现两个问题：

1. 相似的任务拿到不适用的历史结果；
2. 评测把检索到候选误认为记忆已经改变了执行路径。

StateBus 的难点在于把历史记录放回当前任务时，必须同时处理内容和条件：

- 记忆来自哪一次任务、哪个 Agent 和哪个 Artifact；
- 历史方法需要什么输入 schema 和 lineage；
- 本轮的任务意图、实体和时间范围是否兼容；
- 历史输出合同、Validator 和 Runtime 条件是否仍然匹配；
- 当前步骤到底会读取这条记忆，还是只在检索结果里出现。

这直接对应赛题中的“共享记忆保存、检索和跨任务复用”。保存和检索只是基础，复用判断才决定它能否对下一轮工作产生实际作用。

## Memory 在任务中怎样走

可以把一次跨任务过程拆成两段：上一轮怎样留下记录，下一轮怎样使用记录。

```text
上一轮任务
Executor 产生 Artifact
    ↓ 结果、来源和 recipe 通过验证
MemoryCommit 写入

下一轮任务
Retriever 形成当前查询
    ↓ 关键词 / 标签 / 语义检索
候选 Memory
    ↓ 兼容性和复用策略判断
目标步骤获得 ASSIST / VALIDATED_REPLAY
    ↓
当前输入上继续工作
```

## 上一轮保存什么

Memory 不是只保存一句最终答案。当前实现的记录至少需要让后续任务知道：

```text
memory_id
source_agent / source_task_id
created_at
task_theme / tags
summary
artifact_ref
recipe / recipe_hash
input lineage / schema
output contract
runtime / validator 条件
```

可以把写入规则说得简单一些：

> 结果已经通过验证，来源和处理方法也能说明白，这次工作才有资格进入后续记忆。

这句话是页面上的逻辑依据。页面不需要把所有 hash、receipt 和 admission 字段列出来，但讲解者要知道 Memory 记录必须能关联到验证过的 Artifact 和方法。

当前持久化实现包括 SQLite 元数据索引、JSON 记忆和向量记录，Artifact 文件仍保存在任务 workspace。不同任务要指向同一 `memory_store_root`，才能看到同一批历史记录。

## 下一轮怎样找到候选

Runtime 根据当前任务的查询、实体和语义向量，分别产生三路候选：

| 检索路 | 找什么 | 作用 |
| --- | --- | --- |
| 关键词 | 主题、摘要、来源任务和标签中的相关词 | 找描述中直接出现相关词的记录 |
| 标签 | 当前任务实体与历史标签的重合 | 找同一实体或相近任务主题 |
| 语义向量 | 当前查询与历史摘要/方法描述的语义相似度 | 找表述不同但意思接近的记录 |

三路结果的分数含义不同，不能直接相加。当前实现用 RRF 按名次合并：

```text
RRF(m) = 1 / (k + r_keyword(m))
        + 1 / (k + r_tag(m))
        + 1 / (k + r_vector(m))
```

这里的 RRF 只负责决定先检查哪些候选。它不是复用判断，也不应成为 PPT 的主要亮点。页面上最多用一个小公式说明“多路检索先合并候选”，然后把画面重点放到后面的兼容性判断和实际消费。

## 排名之后怎样决定能不能用

Runtime 需要将候选和当前执行步骤比较。重点条件包括：

- 任务主题和意图是否相容；
- 当前输入和历史 recipe 要求的 schema、字段和 lineage 是否相容；
- 历史 Artifact 是否已验证，来源是否仍然可追溯；
- 输出合同、Validator、Runtime signature 等条件是否允许复用；
- 当前步骤的记忆策略是否允许 assist、artifact 或 replay。

结果可以分为四类：

| 结果 | 当前步骤获得什么 | 当前步骤还要做什么 |
| --- | --- | --- |
| `ASSIST` | 摘要、历史策略或路线提示 | 仍用本轮输入完成计算 |
| `VALIDATED_REPLAY` | 已验证的 execution recipe 或程序 | 在本轮输入上重新执行，并生成、验证新的 Artifact |
| `EXACT_REPLAY` | 严格匹配的历史结果 | 只有任务合同、输入和版本等条件都一致时才有直接恢复基础 |
| `REJECT` / 不兼容 | 不把候选交给目标角色 | 回到当前任务自己的检索和执行路径 |

最适合主线展示的是 `VALIDATED_REPLAY`：

```text
历史 recipe
      + 当前任务输入
          ↓
Executor 重新执行
          ↓
本轮 Artifact
          ↓
本轮质量验证
```

复用的是已经验证过的方法，当前数据仍然重新计算，当前结果仍然重新验证。这样既能减少重复生成程序或处理步骤，又不会把上一轮的数值直接当成这一轮的答案。

`EXACT_REPLAY` 可以作为严格边界的小字说明。当前主线实验中，直接恢复旧 Artifact 不是主要展示路径，因此页面不应把它画成 Memory 的默认行为。

## Memory 实际在哪里进入当前任务

检索到候选后，Runtime 会为具体的 step 选择允许使用的 Memory ID，并把它们放入该步骤的 `CapabilityGrant`。Dispatcher 再根据 Grant 为目标角色组织 Memory 输入。

可以这样描述实际路径：

```text
候选 Memory
    ↓ 兼容性和策略判断
MemoryRef ID 进入当前 step 的 Grant
    ↓
Dispatcher 构造目标角色的 Memory 输入
    ↓
Executor 读取 recipe，或角色读取摘要和来源
    ↓
MemoryConsumptionRecord 记录实际使用
```

这一步很重要，因为它把“检索”与“注入”区分开：Memory 不是搜索结果列表，也不是自动写进所有 Agent 的 prompt。它只能进入 Runtime 授权给它的步骤，并以该角色需要的形式出现。

当前机制实验最适合展示 Executor 使用历史 recipe，在新输入上生成新 Artifact。Summarizer 或其他角色可以读取获准的摘要和来源，但不要把所有角色都说成执行了同一种 replay。

## 一页 PPT 的展示重点

### 主图：从历史记录到当前执行

建议使用左右结构：左侧是上一轮留下的记忆，中间是检索和判断，右侧是本轮实际使用。

```text
上一轮
verified Artifact + recipe
        ↓
Memory Store
        ↑
当前查询：关键词 / 标签 / 向量
        ↓
候选排序
        ↓
兼容性判断
   ├── ASSIST → 角色参考
   ├── VALIDATED_REPLAY → Executor 用本轮数据重算
   └── REJECT → 当前任务重新处理
```

右侧的 `VALIDATED_REPLAY` 分支要画得最大，因为它最能说明“记忆复用”怎样产生实际作用：历史方法进入 Executor，但结果仍然由本轮数据产生。

### 小卡片：记忆记录包含什么

可以放一个简化卡片：

```text
MemoryRef
────────────────────
task_theme: compare_metric
summary: verified method
artifact_ref: artifact-17
recipe: compare_periods.v1
tags: [ACME, quarterly]
```

字段只是示意。页面不需要放完整元数据、文件路径和 hash 列表。

### 小公式：RRF 放在候选排序旁

RRF 只作为三路检索如何合并的解释：

```text
keyword + tag + vector
          ↓ RRF
      candidate order
```

公式和 `k=60` 等参数不能抢占主图。评委最需要看的是排序后如何判断和实际使用。

## 这页和前面亮点的区别

Memory 亮点页可以介绍保存、三路检索和复用等级。本页只保留这些内容中最能说明难点的关系：

```text
候选相似 ≠ 可以复用
可以参考 ≠ 可以跳过当前计算
方法复用 ≠ 旧答案直接搬过来
```

这不是为了制造口号，而是页面的判断顺序：先找到候选，再检查条件，最后决定它以什么形式进入当前步骤。

## 源码和实验依据

可以引用以下实现位置：

- `src/statebus/memory/`：记忆模型、索引和检索；
- `src/statebus/runtime/adaptive_dispatcher.py`：Memory 查询结果进入 step 输入和消费记录；
- `src/statebus/runtime/adaptive_runtime.py`：按 attempt 选择 Memory 并绑定 Grant；
- `src/statebus/runtime/adaptive_mainline.py`：任务结果验证后形成 MemoryCommit；
- `docs/implementation/memory.md`：写入、检索、兼容性和 replay 规则。

实验数字应严格区分：当前机制报告中，8 个 Memory-on 位置有 4 个观察到 `validated replay` consumption；candidate hit、actual consumption 和 validated replay 不是同一个指标。主线的 Memory-on/off 对照可以展示某些任务中 provider requests、tokens 和端到端时间下降，但要按逐任务记录说明，不把所有位置都概括成同一收益。

## 评委最后应该记住什么

建议讲解收束为：

> Memory 先帮当前任务找到过去做过的工作，再根据任务条件决定使用方式。最有价值的复用是沿用已经验证的方法，在新的输入上重新计算，并把本轮结果重新交给验证流程。

这句话回应了赛题的跨任务复用要求，也把 Memory 和前两页接起来：角色输入由 Runtime 整理，当前任务由 Runtime 推进，历史方法由 Runtime 判断后重新接入。
