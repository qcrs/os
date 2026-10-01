# 技术难点一：同一份资料怎样交给不同角色继续使用

这一页讨论当前任务中的输入组织问题。它要让评委理解：多 Agent 协作里，资料交接最难的地方不在于把文件再发一次，而在于同一份资料进入不同角色后，需要变成不同的输入，同时还要保留来源和后续引用关系。

## 这一页要回答的具体问题

建议把问题写成一句评委能直接理解的话：

> **同一份资料怎样交给不同角色继续使用？**

这里的“继续使用”有两个含义：

1. 角色能拿到完成当前步骤所需要的内容；
2. 后续角色还能知道这些内容来自哪份证据、哪一行数据或哪段原文。

如果每个角色都收到完整资料，输入会重复，角色还要自己找字段和范围。如果只把上游的摘要交给下游，Executor 可能缺少计算所需的列，Summarizer 也可能无法回到原文。Runtime 需要在两种要求之间作出具体的输入组织。

## 为什么值得作为技术难点

这件事看起来像“把数据传过去”，实际涉及三个互相牵制的要求：

- **不同角色的工作不同**。Retriever 关心检索范围和候选资料，Executor 关心可计算字段和数据行，Summarizer 关心结果、来源和引用关系。
- **输入不能只剩一段摘要**。表格字段、数值口径、文本定位和冲突记录，可能决定后续计算是否成立。
- **输入缩小后仍然要能追溯**。Executor 产出的数值要能关联到证据项，Summarizer 的 Claim 要能回到原始 locator。

这不是简单的格式转换。Runtime 既要减少无关内容，又要保留后续步骤需要的结构和来源。这里的取舍会直接影响通信开销、下游执行是否成功，以及最终结果能否引用。

这也是评委看完结构化协议和 Embedding 之后仍会追问的地方：协议里有了 `input_refs`，引用指向的对象怎样变成某个角色真正能用的输入？向量选出候选以后，Executor 看到的是向量，还是可计算的证据？

## StateBus 怎样处理

StateBus 将“对象在哪里”和“角色这次需要看到什么”分开处理。

```text
EvidencePack / StateRef / ArtifactRef
              ↓
Runtime 根据角色、步骤和输入合同组织视图
              ↓
角色输入 + 来源关系
```

这里有两层实现，需要在讲解中区分：

- `RoleHydratedSlice` 表示某个角色实际可见的内容切片，重点是可见内容、来源 locator 和证据关系；
- `EvidenceProjectionAdapter` 将经过检查的 `EvidencePack` 转成 Executor 可以处理的 typed input artifact，重点是字段、行和计算输入。

它们都参与输入投影，但不是同一个通用接口。这样表述可以准确说明当前实现，也避免把所有角色都说成使用同一种输入对象。

### Retriever 看到什么

Retriever 需要知道本次任务允许检索的范围、查询目标、证据类型和候选预算。它形成 `EvidencePack`，其中可以包括：

- 必须保留的硬事实；
- 表格或其他结构化记录；
- 语义相关上下文；
- 关键词线索；
- 冲突证据。

Retriever 的任务是准备证据和候选状态。它不需要收到 Executor 才能计算的完整 typed rows。

### Executor 看到什么

Executor 需要的是可计算输入，而不是 Retriever 的原始检索过程。Runtime 根据能力合同和步骤要求整理：

- 本次计算所需的字段；
- 对应的数据行或结构化记录；
- 必要的证据项 ID；
- 每一行的来源 locator；
- 能够回到原始文档的 document hash 或 lineage 信息。

Executor 生成 DSL 或 Python 时，使用这份受控输入。它不需要把整个候选资料集重新放进模型上下文。

### Summarizer 看到什么

Summarizer 需要把已验证的执行结果和证据来源组织成结论。Runtime 可以给它：

- 已验证的 `ExecutionArtifactRef`；
- 对应的证据定位；
- 当前任务允许使用的记忆或摘要输入；
- 结果与证据之间的关系。

Summarizer 生成的 Claim 需要带有证据定位、产物来源和任务上下文，之后再通过 Claim 校验。这样，前面为了执行而裁剪过的输入，仍然能在总结阶段回到来源。

## 这页的核心展示逻辑

页面只需要讲清楚一条链路：同一份资料经过 Runtime 的角色投影，变成三种不同的输入。

```text
同一份 EvidencePack
        │
        ├── Retriever
        │     候选范围、检索线索、向量生成
        │
        ├── Executor
        │     可计算字段、数据行、证据 ID、来源 locator
        │
        └── Summarizer
              已验证结果、证据定位、引用关系
```

图上最重要的是 Executor 这一支，因为它最容易让评委看到“资料怎样真正继续被使用”：

```text
EvidencePack
      ↓ Runtime projection
typed input rows
      ↓
Executor 产出 Artifact
      ↓
结果仍带 evidence_item_id / locator / source hash
```

建议在图旁边放一句解释：

> Runtime 负责按当前角色整理输入，来源信息跟着数据一起保留。

这句话比“统一状态投影”更明确。评委能直接理解输入发生了什么变化，也能理解为什么要保留来源。

## 页面应该展示的内容

### 主图：角色输入的差异

主图建议由一个 `EvidencePack` 和三个角色输入框组成。三个框中的文字要短，但要体现用途差异：

```text
EvidencePack
────────────────────────
facts / table rows / contexts / locators

Retriever              Executor                 Summarizer
候选范围               可计算字段               已验证结果
查询线索               数据行                   证据定位
候选 StateRef          source locator           Claim 来源
```

不要画三个角色都接收完整文本的线路。页面要让评委看出“同一个对象，角色视图不同”。

### 重点小框：Executor 的输入和来源

右下角可以放一个小例子：

```text
Executor input row
────────────────────────
metric: 120
period: 2026Q1
evidence_item_id: e17
locator: report.pdf#table[2].cell[4]
source_hash: sha256:...
```

旁边接一条细线回到原始证据。数值只是展示格式，不要在页面上虚构业务结果；如果使用样例，应标明是字段示意。

### 小字实现说明

页面底部可以写：

```text
RoleHydratedSlice：角色可见内容和来源切片
EvidenceProjectionAdapter：EvidencePack → Executor typed input
```

这两个名字用于证明实现位置，不应该成为页面标题。源码类名的作用是支撑讲解，不是让评委记忆 API。

## 页面重点和非重点

页面中心应放在“角色输入不同，来源仍然保留”。以下内容只在讲解时补充：

- 具体的 evidence bucket 如何组合；
- projection request 中的字段和预算；
- 证据冲突如何导致 projection 失败；
- ClaimSetValidator 如何检查引用关系。

页面不需要放：

- 完整 `EvidencePack` 字段表；
- 所有 Agent 的完整 prompt；
- Embedding 相似度和 top-k 算法；
- Protobuf、UDS 或 shared memory 的通道细节；
- 所有 validator 和授权字段。

这些内容已经有结构化协议、Embedding 和执行页面。投影页放得过多，会让评委看不出主问题。

## 它和前面亮点的区别

结构化协议页的重点是：

```text
请求怎样描述动作、输入引用和输出合同
```

Embedding 页的重点是：

```text
向量怎样跨进程被消费，并把候选行还原成证据
```

本页的重点是：

```text
角色拿到的实际输入怎样组织，来源关系怎样一路保留
```

因此本页不重复讲“Ref 怎么传”，而是讲 Ref 到角色输入之间发生了什么。

## 证据安排

源码可以从以下位置支撑本页：

- `src/statebus/provenance/hydration.py`：`RoleHydratedSlice`；
- `src/statebus/runtime/evidence_projection.py`：`EvidenceProjectionAdapter`；
- `src/statebus/contracts/adaptive.py`：`EvidenceProjectionRequest` 和 `EvidenceProjectionReport`；
- `src/statebus/runtime/claims.py`：Claim 与证据定位的校验；
- `docs/implementation/roles.md`：各角色的输入和输出职责。

实验部分可以展示一条真实记录中的输入 lineage、evidence locator 和最终 Artifact 引用。若当前实验只记录了投影和消费事件，就把它说成“观察到输入被组织并被消费”，不要额外推导出未测量的 token 节省。

## 评委最后应该记住什么

建议讲解收束为：

> 同一份资料不会原样复制给每个 Agent。Runtime 按角色整理出可用输入，同时保留证据 ID 和来源位置，所以 Executor 能计算，Summarizer 能引用，后面的步骤还能继续使用同一份工作。

这句话同时说明了问题、解决方式和价值，也为下一页“任务怎样继续跑下去”留下接口：投影解决角色拿到什么，Runtime 调度解决拿到以后怎样接着做。
