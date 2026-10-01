# 答辩亮点：Embedding 状态传递

这份文档准备“非文本状态”部分的 Embedding 页面。页面只讲一条完整链路：候选资料怎样变成数值状态，怎样交给另一个进程选择，怎样根据选择结果找回原始证据，最后怎样进入 Executor。

## 1. 页面主题

页标题建议使用：

> **Embedding：从候选资料中选出需要的证据**

副标题：

> **传递向量状态，返回证据引用。**

这页要让评委记住的结论是：

> **向量负责选择，最终交给 Executor 的仍然是有来源的证据。**

这句话对应 StateBus 的完整实现：`SemanticStateRef` 传递向量矩阵，`HydrateManifest` 保留每一行和原始证据之间的关系，消费进程返回候选 ID 和行号，Runtime 再把选择结果整理成 Executor 能够使用的证据。

页面的中心不在 embedding 模型本身，也不在某个排序算法。中心是下面这条数据流：

```text
候选资料
    ↓ 编码
query/candidate 向量矩阵
    ↓ SemanticStateRef
下游消费进程读取并选择 top-k
    ↓ candidate ID / row index
Runtime 根据 HydrateManifest 找回原文
    ↓
Executor 使用证据
```

## 2. 什么时候需要这条路径

页面场景使用“长资料中的候选证据筛选”，不绑定财务、运营或其他具体行业。

它适用于下面的任务条件：

- 一个查询对应很多文档片段、表格记录或日志片段；
- 候选片段的写法可能不同，单纯依靠关键词不够稳定；
- 下游步骤只需要其中一小部分证据；
- 最终结论仍然需要回到原文、表格单元格或文本区间；
- 选择过程可以由独立进程完成，结果再交给执行角色。

可以把场景说成一句话：

> Retriever 已经找到了候选资料，但 Executor 不需要把所有候选资料都读一遍。StateBus 把候选选择依据交给下游进程，选出需要的几行，再恢复成可引用证据。

这里的 Embedding 负责语义相关性筛选。金额、日期、统计口径和最终事实仍由原始证据、结构化执行和后续校验负责。Embedding 不能替代事实判断，也不能单独成为最终答案。

## 3. 各组件在这条链路中的职责

### Planner：提出检索目标

Planner 负责说明这一步要找什么，例如查询目标、资料范围和所需证据类型。Planner 不生成原始证据，也不负责把文档切成向量。

如果 Planner 没有提供完整的查询文本，Runtime 可以根据任务合同和任务参数形成检索目标。Planner 的输出进入 Runtime 管理的任务计划和输入合同。

### Runtime：确定范围并管理交接

Runtime 负责：

- 确定本次检索允许使用的语料范围；
- 提供查询目标、候选预算、`top_k` 和证据字节预算；
- 调用 Retriever 生成候选和向量状态；
- 发布 `SemanticStateRef` 及其 manifest；
- 通过结构化请求把 Ref 交给下游消费进程；
- 接收候选 ID、分数、行号和消费回执；
- 根据 manifest 把选择结果重新接到 `EvidencePack` 和 Executor 输入。

Runtime 不凭空生成证据。它负责对象范围、状态交接和证据定位关系。

### Retriever：切出候选并生成向量

Retriever 从批准范围内的文档、表格或日志取得候选片段。每个候选片段都保留：

- `candidate_id`；
- 候选文本或结构化内容；
- 所属证据 bucket；
- 文档 hash；
- 文本区间、表格单元格或其他 source locator；
- 候选行的字节提示和排序信息。

随后 Retriever 生成一个 query embedding 和多个 candidate embeddings，并把它们组织成固定行布局的矩阵：

```text
row 0   query
row 1   candidate A
row 2   candidate B
row 3   candidate C
...
row N   candidate N
```

当前状态使用 little-endian `float32`、C-order，矩阵形状为：

```text
(candidate_count + 1, embedding_dims)
```

### 下游消费进程：读取状态并选择候选

下游消费进程收到的是 `SemanticStateRef`，以及 `semantic_top_k`、`evidence_budget_bytes`、`hydrate_manifest_id` 和 `expected_encoder_signature` 等请求参数。

它完成以下工作：

1. 根据 Ref 和 sidecar 找到状态对象；
2. 校验 shape、dtype、大小、blob hash、encoder signature 和 lease；
3. 读取 query 行和 candidate 行；
4. 计算候选相似度；
5. 按 `top_k` 和证据预算选择候选；
6. 返回 candidate ID、score、row index、选择后的证据字节数以及 producer/consumer PID。

当前实现的相似度计算可以概括为：

```text
score(candidate_i) = candidate_row_i · query_row
```

页面不需要展示 Retriever 的完整 RRF、词法检索或多路 fan-in。那些属于候选准备和检索质量。页面需要展示“消费进程读取矩阵并返回选择结果”，因为这一步证明了非文本状态真的被下游使用。

在答辩中，下游框可以写成：

```text
Semantic Consumer
（Executor 前置路径）
```

这样能说明它服务于 Executor，同时保留实现上的准确性：消费进程负责数值选择，Runtime 负责把选择结果接回证据和后续角色。

### Runtime：把选择结果恢复成证据

消费进程返回的是 candidate ID 和 row index。Runtime 根据 `HydrateManifest` 找到每一行对应的 locator，再生成当前步骤需要的证据视图。

例如：

```text
row 3
  ↓
candidate_id = ctx-17
  ↓ HydrateManifest
source document hash = ...
table cell / text span locator
  ↓
CanonicalEvidencePack
  ↓
Executor input
```

`HydrateManifest` 的作用是把数值矩阵的行号和业务证据绑定起来。它记录 candidate ID、row index、证据类型、字节提示和 source locator。缺少这份映射，消费者只能返回“第 3 行最相似”，无法说明这一行对应哪段资料。

Runtime 会根据角色和预算生成证据投影。Executor 可以获得裁剪后的结构化数据和来源定位；Summarizer 后续仍可以读取证据引用和已验证产物。

## 4. 一页 PPT 的主图

页面建议使用从左到右的五个区域：

```text
候选资料 → Retriever 编码 → SemanticStateRef → 下游选择 → Hydrate 回证据
```

### 左侧：候选资料

标题写成“候选资料”，不要写成“完整检索系统”。画三类小卡片即可：

```text
text span
table cell
document fragment
```

每张卡片带一个 `candidate_id` 和 locator。旁边放一句：

```text
同一个查询对应多个候选片段
```

### 中左：Retriever 生成矩阵

画出 query 和 candidate 的编码过程：

```text
query text ───────────────┐
candidate fragments ──────┼─> float32 matrix
                           └─> HydrateManifest
```

矩阵只标出几行：

```text
row 0: query
row 1: candidate A
row 2: candidate B
row 3: candidate C
```

这里需要让评委看到：向量行不是孤立的，每一行都能通过 manifest 找回候选资料。

### 中间：Ref 和载体分开

用一张 `SemanticStateRef` 卡片连接控制面和数据面：

```text
SemanticStateRef
────────────────────
state_id
storage_kind
shape / dtype
blob_hash
manifest_id
encoder_signature
lease
```

从这张卡片分出两条线：

```text
控制面：Ref + top_k + manifest_id
        └── Protobuf / UDS

数据面：float32 matrix
        └── shared memory / mmap
```

这两条线一定要分开画。UDS 传的是控制请求和结果，shared memory 或 mmap 保存的是被 Ref 指向的矩阵。

### 中右：下游选择

下游框中展示四个动作：

```text
resolve Ref
validate state contract
score query × candidates
select top-k under evidence budget
```

框的输出写成：

```text
candidate IDs
scores
row indices
selected evidence bytes
```

可以在框的边上加一行：

```text
producer PID → consumer PID
```

它能说明这是跨进程消费，不是 Runtime 在同一段文本上重新计算。

### 右侧和底部：证据恢复

右侧不要直接接“最终答案”，要先画回证据：

```text
selected row
    ↓
candidate_id
    ↓
HydrateManifest
    ↓
text span / table cell / document fragment
    ↓
Executor evidence input
```

页面底部再放一条生命周期：

```text
publish → transfer → consume → release
```

这条线用于回应赛题要求的生成、传递、接收和后续使用，不需要展开对象清理代码。

## 5. 页面应让评委看到什么

评委看完这一页，应该能回答下面五个问题：

| 评委的问题 | 页面上的答案 |
| --- | --- |
| 向量从哪里来 | Retriever 对查询和候选片段编码 |
| 向量怎样传 | `SemanticStateRef` 指向 shared memory/mmap，控制请求通过 Protobuf/UDS 传递 |
| 谁来用 | 下游消费进程读取矩阵并计算相似度 |
| 用完得到什么 | candidate ID、score、row index 和证据字节数 |
| 结果怎样进入任务 | Runtime 通过 `HydrateManifest` 恢复证据，交给 Executor |

页面最后要停在一个具体结论上：

> **Embedding 状态完成的是候选选择；Runtime 完成的是证据恢复和角色交接。**

## 6. 这一页为什么有价值

### 状态内容和控制消息分开

控制消息只携带 Ref、选择参数和合同信息，矩阵留在状态载体中。这样下游消费进程可以直接读取数值状态，控制面也能保持小而固定。

### 选择动作可以跨进程完成

Retriever 和消费进程不需要共享同一段 Python 对象。消费进程根据 Ref 读取状态，Runtime 通过回执知道哪一个 producer 发布了状态、哪一个 consumer 读取了状态、选中了哪些候选。

### 选择结果保留证据来源

向量选择最终回到 candidate ID、文本区间和表格单元格。Executor 和 Summarizer 得到的仍然是可以阅读、引用和验证的证据。

这三点构成页面的亮点。shared memory、mmap、Protobuf 和 UDS 是实现方式，真正要讲的是“数值选择怎样回到证据并继续进入任务”。

## 7. 这页需要讲清楚的范围

### Embedding 能带来的收益

Embedding 矩阵也需要生成、写入和读取。它带来的收益来自后续裁剪：

```text
候选证据全集
        ↓
向量状态选择
        ↓
只把选中的证据交给 Executor
```

因此，答辩时可以说：

> Embedding 为减少下游证据输入提供了机制。

端到端 token 和时延是否下降，需要由对应实验决定。不能把向量状态本身直接说成“必然更省”。

### Retriever 排序的范围

页面保留“准备候选、生成矩阵”这两步，省略 RRF、词法匹配和多路 fan-in。下游的相似度计算和 top-k 选择必须保留，因为它们构成状态消费的核心动作。

### 证据正确性的范围

Embedding 负责相关性筛选。精确数值、日期、统计口径和最终事实仍需要原始证据、结构化执行和 Validator。页面不要暗示向量可以替代来源检查。

## 8. 建议讲解稿

可以按下面的顺序讲，约一分钟：

> 这一页展示 Embedding 状态怎样进入多 Agent 主链。任务先产生一个检索目标，Retriever 从允许的文档、表格或日志中整理候选片段，为查询和候选片段生成向量，并把矩阵的每一行和原始片段写入 manifest。
>
> Runtime 发布一个 `SemanticStateRef`。控制请求只携带这个 Ref、top-k、证据预算和 manifest ID，矩阵本身放在 shared memory 或 mmap 中。下游消费进程读取矩阵，计算 query 和 candidate 的相似度，返回选中的 candidate ID、分数和行号。
>
> Runtime 再根据 `HydrateManifest` 找回这些行对应的文本区间、表格单元格或文档片段，生成 Executor 需要的证据输入。这里传递的是向量选择依据，最后交付的仍然是有来源的证据。

最后一句可以落在：

> **向量负责选，证据负责说明。**

## 9. 实验与事实边界

这一页讲机制，实验页面再讲收益数字。当前证据适合证明状态路径确实运行并被消费：

- State holdout 包含 4 个任务的 `off/on` 对照；
- State-on 的 4 个位置都记录了 publish、transfer、consume 和 release；
- 精选 evidence 中总计记录 10 次 publish、10 次 transfer、10 次 consume；
- `semantic-holdout-s1` 记录到 `behavioral_effect=changed`，其余三个 holdout 为 `no_effect`；
- 逻辑 payload/read bytes 记录为 `221,184`；
- 这一组结果主要证明跨进程状态被发布、读取、选择并释放，不能据此声称所有任务都获得业务收益。

主实验的整体 token 和时延变化来自完整的 `SB-FULL` 与 `P-TEXT` 配置，不能拆成 Embedding 单项收益。Embedding 页面展示机制链路，测试页面再说明这条路径在对应 holdout 中产生了什么效果。

## 10. 与其他非文本页面的衔接

Embedding 页结束时可以接到后续页面：

> 这里传递的是“选哪些证据”的语义状态。接下来还有两类不同的中间状态：一种保存模型已经算过的长上下文计算，另一种保存模型对候选动作的概率判断。

后续页面分别讲：

- APC：vLLM 引擎怎样复用公共前缀；
- 显式 KV：同一 Worker 怎样继续使用 parent KV；
- Logit：候选概率怎样决定是否展开更多证据。

Embedding 页面不提前展开这三条路径，保持“候选资料 → 数值选择 → 证据恢复”这一条线完整。

## 11. 事实依据

- [Embedding 与 Hydration 实现](../implementation/state.md#稠密语义状态)
- [Retriever 候选和跨进程选择](../../src/statebus/retrieval/pipeline.py)
- [语义状态消费](../../src/statebus/control/subprocess_worker.py)
- [State 消费回执](../../src/statebus/runtime/state_consumption.py)
- [控制协议字段](../../src/statebus/control/statebus_control.proto)
- [State 实验结果](../experiments/results.md#state状态传递和下游选择)
- [机制实验精选结果](../../tests/evidence/mechanisms/results.md)
- [结构化通信协议页面设计](./structured_protocol.md)

