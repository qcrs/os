# 非文本状态的整体定位

这份文档用于统一理解 Embedding、Logit 和显式 KV。在制作页面之前，先把三种状态放回 StateBus 的整体逻辑中，明确它们各自解决什么问题、位于哪一步、怎样组合，以及实验结果分别能证明什么。

## 1. 先确定一个总判断

多 Agent 协作中，文本适合表达任务、说明和结果；有些中间过程需要保留成模型或程序可以直接使用的对象。

StateBus 里的非文本状态，主要处理三类重复工作：

```text
Embedding：从很多资料中选出少量候选
Logit：判断当前候选证据是否够用
显式 KV：让后一个角色继续使用已经完成的上下文计算
```

三者都把中间结果从模型输出或控制消息中单独保存出来，交给后续组件消费。它们的对象形态、使用位置和所有者不同，不能合并成一种状态，也不要求每个任务依次经过三步。

更完整地说：

> **Embedding 处理资料选择，Logit 处理证据取舍，KV 处理模型计算复用。**

这是非文本部分最适合向评委解释的总框架。

## 2. 为什么需要非文本状态

如果每一步都把中间结果重新写成文本，后续角色需要重新解析同一份内容。不同问题会随之出现：

- 候选资料和原文一起传递，下游要处理比实际需要更多的内容；
- 模型已经表现出的选择分布被压缩成一个答案，Runtime 看不到选择是否接近；
- 前一个模型调用已经完成的长上下文计算，后一个调用又从头开始。

Embedding、Logit 和 KV 分别保留了这三类中间信息：

| 中间信息 | 重新写成文本会丢掉什么 | StateBus 保留什么 |
| --- | --- | --- |
| 资料相关性 | 候选行与原文的位置关系 | 向量矩阵、行号和 `HydrateManifest` |
| 选择不确定性 | 第一名和第二名的差距、候选集外概率 | 候选概率向量和 `LogitGateReceipt` |
| 已完成的模型计算 | parent 上已经完成的 prefill | `EngineLocalKVHandle` 和 Worker 内的 KV |

这里的共同点是保留可继续使用的中间表示，具体的消费方式由对象类型决定。

## 3. 三种状态分别处在哪里

### 3.1 Embedding：资料层

Embedding 发生在 Retriever 准备证据时。它解决的问题是：候选资料很多，Executor 只需要其中一部分。

```text
Planner 的检索目标
        ↓
Retriever 生成 query/candidate embedding
        ↓
SemanticStateRef
        ↓
消费进程计算相似度并选择 top-k
        ↓
Runtime 根据 HydrateManifest 找回原文
        ↓
Executor evidence
```

向量矩阵是选择依据，不是最终证据。Runtime 通过 `candidate_id`、row index 和 locator 把选择结果接回文本片段、表格单元格或文档区间。

Embedding 的关键位置是“资料进入 Executor 之前”。它改变的是证据范围，不改变 Executor 的业务计算。

### 3.2 Logit：决策层

Logit 发生在候选已经缩小之后。它解决的问题是：短证据是否足以支持当前选择，还是需要展开完整材料。

```text
compact evidence
        ↓
Executor 返回闭集 choice code
        ↓
提取 choice token 的候选概率
        ↓
LogitStateRef → Decision Worker
        ↓
accept / retry
        ↓
继续执行 / full evidence recheck / abstain
```

StateBus 使用 `CandidateSurfaceV2` 把 `A..H` alias 绑定到稳定的 `candidate_id`。在 choice token 的 `top-logprobs` 中提取候选概率，并保存：

```text
[p(candidate_1), ..., p(candidate_n), other_mass]
```

Decision Worker 计算：

```text
top1   = argmax p(candidate_i)
margin = p_top1 - p_second
```

基础 gate 要求模型选中的候选是 top-1 且 `margin >= 0.10`；model-assist utility 还检查 exact probability 是否可用以及 `other_mass <= 0.20`。通过时继续，含糊时请求一次更完整的证据；复查后仍然无法区分，Runtime 返回 `abstain`。

Logit 的关键位置是“证据已经准备好、业务执行尚未最终确定”。它不替代证据和 Validator，作用是把模型的选择分布转成 Runtime 可以执行的调度动作。

### 3.3 显式 KV：计算层

显式 KV 发生在 Executor 和 Summarizer 的模型调用之间。它解决的问题是：两个角色要处理相同的长 parent，但后一个角色只增加一个自己的 suffix。

```text
Executor：   prefill(parent + executor suffix)
             capture parent KV

Summarizer： load parent KV handle
             prefill(summarizer suffix)
```

`EngineLocalKVHandle` 由同一 vLLM Worker 的 registry 管理。Consumer 只能在兼容的 engine generation、model/tokenizer identity 和 parent token digest 下加载它。

KV 的关键位置是“证据已经固定、一个角色已经完成 parent 计算、下一个角色准备继续计算”。它改变的是模型服务的 prefill 路径，不改变 Artifact、Summarizer 结果和 Runtime 的业务合同。

## 4. 三者如何组合

可以用一个长材料任务说明它们之间的关系：

```text
资料很多
    ↓
Embedding 选出候选证据
    ↓
Executor 先看 compact evidence
    ↓
Logit 判断是否需要 full evidence
    ↓
Executor 完成计算并产生 Artifact
    ↓
Summarizer 继续处理相同长上下文
    ↓
显式 KV 复用 parent 计算
```

这是一条可以成立的组合示例，不是固定流水线。不同任务可能只有其中一部分：

- 候选很少时可以不启用 Embedding；
- 选择结果不需要二次取证时可以不启用 Logit；
- 后续角色没有公共长上下文时可以不启用显式 KV。

因此，答辩时不要说“每个任务都会经过 Embedding、Logit、KV”。应该说明 Runtime 根据任务的输入形态和角色关系选择对应路径。

## 5. 三种状态的共同结构

虽然对象不同，但三条路径都可以用同一组问题来解释：

```text
谁生成？
状态放在哪里？
谁来消费？
消费结果怎样回到主链？
什么时候释放？
```

对应关系如下：

| 问题 | Embedding | Logit | 显式 KV |
| --- | --- | --- | --- |
| 生成者 | Retriever | Executor/provider response | Executor + vLLM Worker |
| 状态 | query/candidate float32 matrix | candidate probabilities + `other_mass` | parent KV tensors |
| 交接对象 | `SemanticStateRef` | `LogitStateRef` | `EngineLocalKVHandle` |
| 消费者 | Semantic Consumer | Decision Worker | Summarizer-side Worker path |
| 消费结果 | candidate IDs → evidence | gate receipt → next action | forward result → Artifact/Summary |
| 载体 | shared memory/mmap | shared memory | Worker-local KV registry |
| 生命周期 | publish → consume → release | publish → gate → release | capture → load → release |

这张表适合用于内部统一口径，不需要原样放进 PPT。它能防止把三种机制讲成相同的“共享内存传输”。

## 6. 非文本状态和前面的协议页怎样接上

结构化协议页先说明 Agent 如何交接对象：请求携带动作、输入引用和输出合同。非文本状态页再说明其中几类引用指向什么，以及消费后怎样影响任务。

可以这样衔接：

```text
结构化请求：operation + input_refs + output_contract
        ↓
Embedding：SemanticStateRef → candidate evidence
Logit：    LogitStateRef → gate receipt
KV：       EngineLocalKVHandle → suffix continuation
```

但要保留实现边界：Embedding 和 Logit 使用 StateBus 的 Ref、sidecar 和独立消费路径；显式 KV 使用模型服务的 Worker-local registry 和专用 API。KV handle 可以作为协作关系中的对象，但它不属于通用 StateStore 的四类正式 Ref。

## 7. 三种状态和 APC 的边界

APC 与显式 KV 都能减少长上下文的重复 prefill，但 APC 的对象和所有者不同：

```text
显式 KV：Producer → EngineLocalKVHandle → Consumer
APC：    Runtime 对齐请求前缀 → vLLM 自动命中 prefix cache
```

APC 不经过 `SemanticStateRef`、`LogitStateRef` 或 `EngineLocalKVHandle`。StateBus 负责公共 evidence 的稳定渲染、exact token identity 和调度反馈；prefix block 的驻留、命中和淘汰由 vLLM 管理。

所以非文本状态的主线可以只包含：

```text
Embedding / Logit / 显式 KV
```

APC 放在相邻的“模型侧长文本加速”专项中，单独解释请求对齐和动态调度。

## 8. 每种机制的实验应该证明什么

### Embedding

当前 State holdout 证明了：

- 数值矩阵能够 publish、transfer、consume 和 release；
- 消费进程能够根据 row index 选择候选；
- Runtime 能通过 manifest 把候选行接回 evidence。

4 个 holdout 的 on 位置都完成了这条路径，但只有 `semantic-holdout-s1` 记录到 `behavioral_effect=changed`。因此 Embedding 页应证明“非文本状态被真实消费并回到证据”，不要把 State holdout 直接说成普遍的业务收益。

### Logit

当前 model-assist utility 证明了：

- 选择位置的候选概率可以被提取、发布并由独立 Worker 消费；
- resolved case 可以减少 full evidence 展开；
- unresolved case 可以在复查后得到正确 `abstain`。

12 个计分位置中有 9 个 resolved case 通过、3 个 unresolved case 正确 abstain；resolved case 的 logical input 平均减少 `75.21%`，`logit_selective` provider request wall 平均下降 `18.51%`。这些是独立模型侧专项数字。

### 显式 KV

当前 utility 对照证明了：

- parent KV 被 capture、load、forward 使用并 release；
- consumer computed prefill 平均下降 `90.37%`；
- consumer TTFT 平均下降 `60.88%`；
- 完整 task wall 平均下降 `3.58%`。

后一个数字把 KV capture/load 等固定成本也算在内。页面需要同时展示局部模型服务指标和完整任务指标。

## 9. 向评委讲这部分时的顺序

先给总框架，不要一上来讲三种数据结构：

> 多 Agent 工作流里，重复的内容有三种。第一种是资料重复搬运，第二种是选择信息被压缩以后无法判断是否需要更多证据，第三种是不同角色反复计算同一段长上下文。StateBus 分别用 Embedding、Logit 和显式 KV 保存这三类中间状态。

接着按“资料 → 决策 → 计算”的顺序展开：

1. Embedding 把候选资料选出来，再通过 manifest 回到原文；
2. Logit 把候选概率交给 Runtime，决定继续、复查还是停止；
3. 显式 KV 让后一个角色接着前一个角色已经完成的 parent 计算继续工作。

最后说明三者不构成固定流水线，Runtime 按任务需要启用。APC 在旁边单独作为模型服务的公共前缀复用和动态调度专项。

## 10. 一句话区分三者

这三句话可以作为内部讲解时的固定口径：

```text
Embedding：选择哪些资料进入下一步。
Logit：判断当前资料是否足够支持选择。
显式 KV：复用前一个角色已经完成的长上下文计算。
```

## 11. 事实依据

- [Embedding 页面设计](./embedding_state.md)
- [Logit 页面设计](./logit_state.md)
- [显式 KV 页面设计](./kv_state.md)
- [State、Ref 与存储](../implementation/state.md)
- [模型侧运行路径](../implementation/runtime.md)
- [机制实验结果](../experiments/results.md)
- [模型侧精选结果](../../tests/evidence/model-assist/summary.md)
