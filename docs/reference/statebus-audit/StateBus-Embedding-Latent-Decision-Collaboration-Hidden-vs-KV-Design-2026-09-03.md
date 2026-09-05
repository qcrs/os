# StateBus Embedding / Latent / Decision 协同机制与 Hidden vs KV 实现设计

> **项目**：StateBus / `qcrs/os`  
> **日期**：2026-09-03  
> **定位**：概念澄清 + 端到端协同设计 + Hidden/KV 边界 + Latent 实施方案  
> **关联文档**：
> - `StateBus-Decision-Latent-KV-Unified-Architecture-Design-2026-09-03-Revised-v2.md`
> - `StateBus-NonText-State-Embedding-LatentState-StateBridge-Source-Audit-2026-09-03-Revised-v2.md`
>
> 本文不再分别介绍 Embedding、Latent、Decision 三个 feature，而是回答一个更关键的问题：
>
> # **它们在一次真实 Multi-Agent 推理中到底如何前后衔接？**
>
> 同时回答：
>
> # **Hidden 与 KV 到底有什么本质区别，为什么 StateBus 要传 Hidden，而 KV/APC 应放在 Compute Reuse Plane？**

---

# 0. 最终结论先行

StateBus 中建议形成四个明确概念：

```text
Semantic / Retrieval Embedding
    ↓
“应该看什么？”

Latent Hidden State
    ↓
“上游 Agent 已形成什么内部 representation，
如何直接交给下游 Agent？”

Decision State
    ↓
“下游 Agent 当前是否足够确信，
Runtime 下一步应该怎么走？”

APC / KV
    ↓
“哪些 Transformer 计算已经完成，
不需要重复 Prefill？”
```

其中前三者不是完全并列运行。

真实协同链是：

# `Selection → Representation Handoff → Decision → Feedback`

完整：

```text
Task
  ↓
Retrieval Embedding
  ↓
Selected Evidence / Memory
  ↓
Agent A
  ↓
Transformer A
  ↓
Hidden H_A
  ↓
StateBridge Alignment
  ↓
LatentState Z_A→B
  ↓
Agent B
  ↓
Transformer B
  ↓
Hidden H_B
  ↓
LM Head
  ↓
Decision Logits
  ↓
DecisionState
  ↓
Runtime Policy
  ├─ ACCEPT
  ├─ RETRY
  ├─ EXPAND_EVIDENCE ───→ 回到 Embedding
  └─ REPLAN
```

APC/KV 则平行存在于每个 vLLM request 的 compute path：

```text
Shared textual prefix
    ↓
APC KV lookup
    ├─ HIT → 少算 Prefill
    └─ MISS → 正常 Prefill
```

所以：

```text
Embedding / Latent / Decision
= Agent semantic/control flow

APC / KV
= Transformer compute reuse flow
```

---

# 1. 最大的概念陷阱：系统里其实有两种 “Embedding”

这是理解整个架构的第一步。

## 1.1 Retrieval / Semantic Embedding

这是 StateBus 当前已有的：

```text
Query
Candidate Evidence / Memory
    ↓
Embedding Encoder
    ↓
vector similarity
    ↓
top-k
```

例如：

```text
Qwen3-Embedding
SentenceTransformers
```

或 CI 中 deterministic encoder。

它回答：

> **当前任务真正需要哪些外部信息？**

形式上：

\[
q = f_{embed}(query)
\]

\[
e_i = f_{embed}(evidence_i)
\]

\[
score_i = q^\top e_i
\]

得到：

```text
Evidence 7
Evidence 18
Evidence 31
...
```

然后 Runtime：

```text
hydrate Evidence IDs
→ 原始 evidence / artifact
→ 送给 LLM
```

这就是：

# Semantic Selection State

---

# 2. Transformer Input Embedding 是另一回事

LLM 自己内部还有：

```text
token_id
    ↓
embedding table
    ↓
input embedding
```

例如 token：

```text
"database"
```

经过：

\[
x_t = W_E[token_t]
\]

得到：

```text
hidden_dim 维向量
```

再进入：

```text
Transformer Layer 1
```

这与前面的：

```text
Qwen3-Embedding-0.6B 做 Retrieval
```

没有直接关系。

因此一定要坚持术语：

```text
SemanticEmbedding
    = retrieval vector

InputEmbedding
    = LLM token input representation
```

不要都简称：

```text
Embedding
```

。

---

# 3. Hidden State 位于哪里？

一个简化 Decoder-only Transformer：

```text
Token IDs
   ↓
Input Embedding
   ↓
Layer 1
   ↓
Layer 2
   ↓
...
   ↓
Layer N
   ↓
Deep / Final Hidden Representation
   ↓
LM Head
   ↓
Vocabulary Logits
   ↓
Sampling / Structured Choice
```

数学上：

\[
H^{(0)} = Embedding(tokens)
\]

\[
H^{(l+1)} = TransformerLayer_l(H^{(l)})
\]

最终：

\[
H^{(L)}
\]

然后：

\[
logits = H^{(L)}W_{LM}
\]

所以：

# Hidden 是 Input Embedding 之后、LM Head 之前形成的内部 representation。

---

# 4. Hidden 不是“模型输出文本”

这一点非常重要。

模型真正输出文本必须经过：

```text
Hidden
↓
LM Head
↓
Vocabulary Logits
↓
token selection
↓
decode
↓
text
```

所以：

```text
Hidden
```

比：

```text
Visible Text
```

更靠近模型内部。

它保留的是：

```text
contextual representation
```

而不是：

```text
已经离散化后的 token sequence
```

。

---

# 5. StateBus 要传的 Hidden 到底是什么？

第一版不传：

```text
所有 layer
所有 prompt token
所有 hidden states
```

。

推荐只传：

```text
Producer Agent
最后若干 generated positions
对应的 deep/final hidden states
```

例如：

```text
K = 32 / 64
hidden_dim = 4096
```

得到：

\[
H_A \in R^{K\times H}
\]

例如：

```text
[64, 4096]
```

。

每个 position：

```text
h_i ∈ R^4096
```

不是：

```text
一个普通 token embedding
```

而是经过 Producer 整个 Transformer contextualized 后的 representation。

---

# 6. 一个精度要求：不要只写“final hidden”

实际实现必须记录：

```text
source_layer
hook_point
pre_norm / post_norm
model revision
```

因为：

```text
最后一个 transformer block 输出
```

与：

```text
最终 RMSNorm 后送 LM Head 的 hidden
```

在具体模型里可能不是完全同一个 tensor。

所以 Contract 应写：

```text
source_layer
source_hook_semantics
normalization_semantics
```

而不是只有：

```text
last_hidden=true
```

。

---

# 7. 为什么 Raw Hidden 不能直接给 Agent B？

这是 Latent 实现最关键的数学问题。

Producer：

```text
H_A
```

来自：

```text
深层 Transformer representation space
```

Consumer 正常输入：

```text
E_B
```

来自：

```text
input embedding space
```

即使：

```text
dim(H_A) = dim(E_B)
```

通常都是：

```text
hidden_size
```

，也不意味着：

```text
distribution(H_A)
==
distribution(E_B)
```

。

直接：

```python
receiver.generate(inputs_embeds=H_A)
```

很可能导致 OOD。

---

# 8. StateBridge 解决的是“Representation Space Mismatch”

StateBridge 做：

```text
Raw Hidden H_A
      ↓
Center
      ↓
Whitening
      ↓
Orthogonal Procrustes
      ↓
Receiver embedding statistics reconstruction
      ↓
Norm calibration
      ↓
Vocabulary anchoring
      ↓
Aligned Latent Z_A→B
```

最终：

\[
Z_{A\rightarrow B}\in R^{K\times H}
\]

虽然 shape 与 Hidden 一样，但语义已经变成：

> **Consumer 可以当作 continuous input prefix 使用的 representation。**

因此 StateBus 真正 publish：

```text
LatentStateRef
```

对应的是：

# `AlignedLatentPrefix`

而不是 provider-local 的 raw hidden。

---

# 9. Latent 如何进入下一个 Agent？

这是之前文档最容易让人误解的地方。

不是：

```text
Agent A Layer N
    ↓
Agent B Layer N+1
```

。

正确：

```text
Agent A
Input Embedding
→ Layer 1
→ ...
→ Layer N
→ Hidden H_A

H_A
→ Alignment
→ Latent Z_A→B

Agent B
Input Boundary:
[Text Embeddings | Latent Z_A→B | Text Embeddings]
    ↓
Layer 1
    ↓
...
    ↓
Layer N
```

也就是说：

# Agent B 仍然从自己的 Transformer Layer 1 开始正常计算。

Latent 只是：

```text
continuous pseudo-prefix / continuous neural prompt
```

。

---

# 10. 与 Communicating Activations 的区别

另一类方法可能做：

```text
Agent B
Layer 1
→ ...
→ Layer k
→ 插入 Agent A activation
→ Layer k+1
→ ...
```

这是：

```text
mid-layer activation communication
```

。

它需要：

```text
暂停 forward
中层 injection
修改 serving hot path
```

。

StateBus v1 不做。

当前选择：

```text
StateBridge-style
input-boundary latent communication
```

原因：

```text
实现干净
更容易适配 vLLM prompt embeds
更容易定义 Ref/Contract
更容易 fallback
```

。

---

# 11. Embedding 和 Latent 如何真正协同？

举一个完整任务。

用户：

```text
分析一份 100k-token 企业运营资料，
找出收入下降的主要原因。
```

数据库有：

```text
1000 Evidence Chunks
```

首先：

```text
Semantic Retrieval Embedding
```

决定：

```text
1000
↓
20
```

。

这 20 个 Evidence 构成：

```text
Agent A / Executor
```

输入。

所以：

# Embedding 决定 Hidden 形成时的输入条件。

如果 Embedding 选错：

```text
Agent A 看不到关键事实
```

那后面：

```text
Hidden 再强
```

也无法凭空恢复没有看到的信息。

---

# 12. Agent A 如何产生 Latent？

Executor：

```text
Selected Evidence
+
Task
+
Role Instruction
```

进入：

```text
Transformer A
```

。

得到：

```text
H_A
```

。

同时它正常输出：

```text
ExecutionArtifact
```

例如：

```text
Revenue ↓12%
Enterprise churn is dominant cause
APAC slowdown secondary
```

。

然后 Hidden Capture：

```text
last K generated hidden positions
```

经过 Alignment：

```text
Latent Z_A→B
```

发布：

```text
LatentStateRef
```

。

---

# 13. Agent B 如何同时消费 Artifact 与 Latent？

推荐：

```text
Artifact
= Authoritative

Latent
= Advisory
```

Consumer Prompt：

```text
[Shared Evidence]
[Execution Artifact]
[Latent Prefix]
[Summarizer Role]
```

从 embedding-level 看：

```text
E(shared evidence)
+
E(artifact text/structured serialization)
+
Z_A→B
+
E(role suffix)
```

一起进入：

```text
Transformer B
```

。

---

# 14. 为什么不能让 Latent 取代 Artifact？

因为 Latent：

```text
不可人工直接解释
```

。

它无法承担：

```text
source provenance
evidence locator
verified fact
```

。

所以：

```text
Artifact
决定什么事实可以写

Latent
帮助 Consumer 理解重点、关系、推理倾向
```

。

这个 trust boundary 必须保留。

---

# 15. Latent 被消费后，会发生什么？

Agent B 接收到：

```text
Text + Latent
```

后：

```text
Layer 1
↓
...
↓
Layer N
```

形成：

\[
H_B
\]

注意：

```text
H_B
```

已经是：

```text
Agent B 自己的新内部 representation
```

它融合了：

```text
shared evidence
artifact
latent
role instruction
```

。

---

# 16. Decision State 在哪里产生？

Decision 并不直接：

```text
读取 LatentStateRef
```

。

而是 Agent B 在某个 bounded decision position：

```text
Hidden h_B
```

经过：

\[
logits = h_B W_{LM}
\]

然后 Runtime 只关心合法候选：

```text
A = FINALIZE
B = RETRIEVE_MORE
C = REPLAN
```

抽出：

```text
p(A)
p(B)
p(C)
other_mass
```

形成：

```text
DecisionState
```

。

---

# 17. 所以 Decision 是 Latent 的“下游投影”

这句话非常重要：

```text
LatentState
= Rich neural representation

DecisionState
= Current model state
  projected into a bounded Runtime action space
```

例如：

```text
Latent 可能包含：
对多个证据关系的连续表示

Decision 最终只保留：
FINALIZE 0.72
RETRIEVE_MORE 0.18
REPLAN 0.06
other 0.04
```

Decision 比 Latent 信息量小得多。

但它：

```text
可解释
可校准
可直接驱动 Runtime
```

。

---

# 18. Decision 如何反向驱动 Embedding？

这是三者真正形成系统闭环的地方。

假设：

```text
FINALIZE        0.41
RETRIEVE_MORE   0.39
REPLAN          0.08
other           0.12
```

Runtime 发现：

```text
margin low
absolute confidence low
```

DecisionPolicy：

```text
EXPAND_EVIDENCE
```

。

随后：

```text
当前 uncertainty / missing aspect
↓
形成新的 retrieval query
↓
Semantic Embedding
↓
检索新的 Evidence
↓
再次 Agent reasoning
```

因此：

```text
Decision
→ Embedding
```

形成 feedback。

---

# 19. 三者最终形成状态机，而不是 Pipeline Feature List

正式抽象：

```text
                    ┌───────────────────────┐
                    │                       │
                    ▼                       │
          Semantic Selection               │
             Embedding                     │
                    │                       │
                    ▼                       │
               Agent A                     │
                    │                       │
                    ▼                       │
             Latent Handoff                │
                    │                       │
                    ▼                       │
               Agent B                     │
                    │                       │
                    ▼                       │
             Decision State                │
                    │                       │
        ┌───────────┼───────────┐           │
        │           │           │           │
        ▼           ▼           ▼           │
     ACCEPT       RETRY       EXPAND────────┘
                                │
                              REPLAN
```

所以真正 headline：

# `Selection → Representation → Decision → Feedback`

---

# 20. Decision State 应该放在哪些场景？

第一版不应该到处使用。

推荐三个 bounded decision point。

## D1 Capability Dispatch

合法候选：

```text
DSL
CodeAct
Retrieve More
```

DecisionState 判断：

```text
模型选择是否足够可信
```

。

## D2 Evidence Sufficiency

合法候选：

```text
ANSWER_NOW
RETRIEVE_MORE
```

可以自然形成：

```text
Decision → Embedding feedback
```

。

## D3 Finalize / Replan

合法候选：

```text
FINALIZE
REPLAN
```

但要等 Adaptive Router 稳定后。

---

# 21. DecisionState 不拥有 Authority

即使：

```text
p(CodeAct)=0.99
```

如果 Plan/CapabilityGrant：

```text
没有授权 CodeAct
```

也不能执行。

因此：

```text
DecisionState
= belief

PlanPolicy / CapabilityGrant
= authority
```

永远分开。

---

# 22. Hidden 与 KV 为什么总容易被混淆？

因为它们都是：

```text
Transformer 内部 Tensor
```

而且都与：

```text
过去 token / context
```

相关。

但二者的数据来源、结构、用途完全不同。

---

# 23. Hidden 与 KV 从 Attention 公式看

某一层输入 hidden：

\[
H^{(l)}
\]

Attention 会计算：

\[
Q^{(l)} = H^{(l)}W_Q
\]

\[
K^{(l)} = H^{(l)}W_K
\]

\[
V^{(l)} = H^{(l)}W_V
\]

然后：

\[
Attention(Q,K,V)
\]

所以：

```text
Hidden H
  │
  ├─ Wq → Q
  ├─ Wk → K
  └─ Wv → V
```

K/V 是 Hidden 的 layer-specific projection。

---

# 24. Hidden 的典型形态

我们传：

```text
K positions
×
hidden_dim
```

例如：

```text
[64, 4096]
FP16
```

大约：

```text
512 KiB
```

。

---

# 25. KV Cache 的典型形态

KV Cache 是：

```text
每一层
每个历史 token
K + V
```

概念：

```text
Layer 1:
K[1..T]
V[1..T]

Layer 2:
K[1..T]
V[1..T]

...

Layer L:
K[1..T]
V[1..T]
```

所以完整 KV 依赖：

```text
num_layers
num_kv_heads
head_dim
sequence length
dtype
```

。

---

# 26. Hidden 为什么不能等于 KV？

原因一：

```text
KV 是 projection
```

。

原因二：

```text
KV 分散在每层
```

而我们常说 final hidden：

```text
只是一层的 representation
```

。

原因三：

```text
GQA / MQA
```

可能让 KV 表达维度远小于完整 hidden。

所以：

```text
KV
不能一般性逆推出完整 Hidden
```

。

---

# 27. Final Hidden 也不能生成完整 KV Cache

拿到：

```text
Agent A final hidden
```

并不意味着你拥有：

```text
Layer1 KV
Layer2 KV
...
LayerN KV
```

这些必须在每层 forward 时计算。

所以：

```text
Hidden
≠
KV 的压缩包
```

。

---

# 28. 两者最准确的系统区别

可以记：

> **Hidden = Representation State**

回答：

```text
模型当前内部怎么表示这些信息？
```

。

> **KV = Computation State**

回答：

```text
过去 token 的 Attention K/V
是否已经算过？
```

。

---

# 29. 为什么 StateBus Semantic Handoff 应优先 Hidden？

假设 Agent A 看到了 private context：

```text
Evidence A
Tool Result B
Derived Relation C
```

并经过推理形成：

```text
H_A
```

Agent B 没有完整看到 A 的过程。

那么：

```text
Latent H_A→B
```

承担的是：

```text
new information representation handoff
```

。

而普通 KV(P)：

```text
如果 Agent B 本来就拥有 P
```

B 完全可以：

```text
重新 Prefill P
```

再得到相同/对应 KV。

所以 KV 的主要价值是：

```text
少算一次
```

而不是：

```text
传递新的语义内容
```

。

---

# 30. 因此 Hidden 与 KV 分属两个 Plane

```text
Semantic / Neural Plane

Embedding
Latent
Decision
```

和：

```text
Compute Reuse Plane

APC
Explicit KV
Offloaded KV
```

。

两边可以同时工作。

---

# 31. Hidden 与 APC 如何同时存在？

推荐 Prompt Layout：

```text
[Canonical Shared Text Prefix]
[Latent Prefix]
[Role-Specific Suffix]
```

原因：

```text
Canonical Shared Prefix
```

放最左：

```text
多个 Agent request
可以 APC hit
```

。

unique Latent 放后面：

```text
不会破坏前面 shared blocks
```

。

---

# 32. 一个具体例子

Executor：

```text
[Shared Evidence X]
[Executor Role]
```

第一次：

```text
Shared Evidence X
→ Prefill
→ APC KV cached
```

Summarizer：

```text
[Same Shared Evidence X]
[Executor Latent]
[Summarizer Role]
```

于是：

```text
Shared Evidence X
→ APC HIT

Executor Latent
→ 作为 continuous positions 正常计算

Summarizer Role
→ 正常计算
```

。

所以：

```text
APC
节省公共上下文重算

Latent
传递 Agent-specific internal representation
```

。

---

# 33. 为什么这比 Full KV Transfer 更适合当前系统？

当前是：

```text
One vLLM
Many Logical Agents
```

。

相同公共 prefix 的 KV 本来就留在同一个 vLLM block pool。

没必要：

```text
GPU
→ CPU
→ StateBus
→ GPU
```

搬一遍。

APC：

```text
直接 engine-local reuse
```

更自然。

Hidden：

```text
payload 几百 KiB
```

更适合 StateBus StateRef/SHM。

---

# 34. Explicit KV 还保留什么价值？

保留：

```text
Explicit Compute-State Lifecycle Proof
```

它证明：

```text
StateBus
真的可以治理：
producer
handle
compatibility
consumer
forward proof
release
```

。

但不作为：

```text
semantic handoff 主线
```

。

---

# 35. Latent 实现的总体链路

推荐：

```text
Producer vLLM
    ↓
Hidden Extraction
    ↓
RawHiddenCapture
    ↓
LatentExtractionPolicy
    ↓
StateBridgeAligner
    ↓
AlignedLatentPrefix
    ↓
StateBus publish
    ↓
LatentStateRef
    ↓
SHM / mmap
    ↓
Consumer resolve
    ↓
PromptEmbed Injector
    ↓
Consumer vLLM
    ↓
LatentConsumptionReceipt
    ↓
release
```

。

---

# 36. Producer Hidden Capture

推荐 modern vLLM：

```text
HiddenStateCacheSpec
+
ExampleHiddenStatesConnector 思路
```

而不是长期在 ModelRunner 随处 patch。

StateBus provider：

```text
StateBusHiddenStatesConnector
```

职责：

```text
只抓需要的 hidden
```

。

---

# 37. Capture 的第一版范围

强制：

```text
one selected deep/final layer
```

和：

```text
last K generated positions
```

。

不要抓：

```text
all prompt positions
all layers
```

。

第一版：

```text
K ∈ {16,32,64}
```

。

---

# 38. 为什么只抓 Generated Hidden？

因为我们真正想传的是：

```text
Producer 这一次 reasoning/generation
新形成的 representation
```

而不是：

```text
把全部 shared prompt 再传一遍神经表示
```

shared prompt 已经：

```text
APC
```

负责。

这会让：

```text
Latent
```

与：

```text
APC
```

职责更加干净。

---

# 39. `RawHiddenCapture`

Provider-local 对象建议：

```text
RawHiddenCapture
├─ hidden_tensor
├─ generated_token_ids
├─ source_layer
├─ source_hook_semantics
├─ model_fingerprint
├─ tokenizer_fingerprint
├─ generated_token_count
└─ capture_timestamp
```

不一定进入 StateStore。

---

# 40. `LatentExtractionPolicy`

第一版：

```text
LAST_K

POST_THINK_LAST_K
```

即可。

不要硬编码：

```text
</think>
```

到 StateStore。

这是 Provider policy。

---

# 41. `StateBridgeAligner`

输入：

```text
Raw hidden [K,H]
generated token ids
receiver embedding matrix / statistics
alignment config
```

输出：

```text
AlignedLatentTensor [K,H]
AlignmentReceipt
```

。

---

# 42. Alignment 的 Contract

必须绑定：

```text
alignment_method
alignment_version
regularization
snap_ratio
source model fp
receiver model fp
source token digest
```

。

因为：

```text
同一个 raw hidden
不同 alignment config
```

会产生不同 consumer input。

---

# 43. `LatentStateRef`

建议核心：

```text
state_id

task_id
trace_id

producer_step
producer_attempt
producer_role
allowed_consumers

representation_type
= aligned_hidden_prefix

producer_model_fp
receiver_model_fp
tokenizer_fp

source_layer
source_hook_semantics

prefix_length
hidden_dim
dtype

alignment_method
alignment_version
alignment_config_hash

blob_hash
contract_hash
commitment_hash

visible_commitment_hash

lease
```

。

---

# 44. 为什么需要 `visible_commitment_hash`

Latent 不可解释。

但 Producer 同时通常输出：

```text
ExecutionArtifact
```

所以可以：

```text
LatentState
绑定
ExecutionArtifact hash
```

。

它证明：

```text
这个 Latent
与这个可见 Producer 输出
属于同一次 committed production
```

。

不证明：

```text
Latent 语义一定正确
```

。

---

# 45. Transport

第一版：

```text
FP16
+
SHM
```

推荐。

例如：

```text
[64,4096]
```

约：

```text
512 KiB
```

完全可控。

不需要第一版：

```text
RDMA
CUDA IPC
LMCache
```

。

---

# 46. Consumer Validation

顺序推荐：

```text
Control Header

Grant

Ref commitment

Ref kind

Contract hash

Payload hash

Lease

Allowed consumer role

Producer/receiver model compatibility

Tokenizer compatibility

Shape

Dtype

Finite values

Injection policy
```

验证完才：

```text
map payload
→ device
→ inject
```

。

---

# 47. Consumer Injection

逻辑：

```text
Text Prompt
    ↓
Tokenization
    ↓
Text Input Embeddings

LatentStateRef
    ↓
Aligned Latent Tensor

Composition:
[Shared Text Embed]
[Latent]
[Role Text Embed]

    ↓
model.generate(inputs_embeds=...)
```

。

---

# 48. Latent 与 APC 的 Layout Contract

推荐：

```text
Layer 0
Broadest reusable text prefix

Layer 1
Corpus / shared evidence

Layer 2
Optional session text

Layer 3
Latent

Layer 4
Role / task-specific suffix
```

原则：

> **越稳定、越广泛共享的 token 内容越靠左。**

因为 APC 的 block hash 是 chained prefix identity。

---

# 49. Consumer Forward 后产生新 Hidden

Consumer：

```text
Text + Latent
```

一起进入 Transformer。

所以新：

```text
H_B
```

已经编码了 Latent 的影响。

这时候才有资格产生：

```text
DecisionState
```

。

---

# 50. Decision Extraction

第一版：

```text
Runtime defines legal action aliases
```

例如：

```text
A=FINALIZE
B=RETRIEVE_MORE
C=REPLAN
```

Model：

```text
输出 bounded structured decision
```

Runtime：

```text
读取 A/B/C token probability
```

形成：

```text
selected_probability
top_margin
candidate_mass
entropy
```

。

---

# 51. `DecisionSurface`

建议：

```text
DecisionSurface
├─ surface_id
├─ candidates
│   ├─ candidate_id
│   ├─ action
│   ├─ authority requirement
│   └─ risk class
└─ surface_hash
```

由 Runtime 构造。

---

# 52. DecisionPolicy

输入：

```text
DecisionState
+
Risk
+
Budget
+
Plan Authority
```

输出：

```text
ACCEPT
RETRY
EXPAND_EVIDENCE
REPLAN
FAIL_CLOSED
```

。

---

# 53. Decision → Embedding Feedback Contract

这是以后很值得明确化的一层。

如果：

```text
Decision = EXPAND_EVIDENCE
```

不要只：

```text
重新跑原 Query
```

。

应生成：

```text
RetrievalFeedback
```

包含：

```text
missing aspect
uncertain entity
required evidence kind
previous evidence IDs
do-not-repeat IDs
budget
```

再给 Retriever。

于是：

```text
Decision
→ RetrievalFeedback
→ Semantic Embedding
```

成为真正反馈闭环。

---

# 54. 一个未来很漂亮的状态关系

```text
SemanticSelectionReceipt
    ↓
selected evidence refs
    ↓
Producer LatentState
    ↓
Consumer DecisionState
    ↓
RetrievalFeedback
    ↓
next SemanticSelectionReceipt
```

可以形成：

```text
State lineage graph
```

。

这比：

```text
三个独立 feature
```

强很多。

---

# 55. 三类状态的生命周期

| State | 生命周期 | 是否持久 | 典型 payload |
|---|---|---:|---|
| Semantic Embedding | retrieval/session，可缓存 | 可 | vectors/index |
| LatentState | task-local / short TTL | 通常否 | `[K,H]` FP16 |
| DecisionState | 极短 | 否 | candidate probs |
| KV/APC | engine/cache 生命周期 | engine owned | per-layer K/V |

所以：

```text
Latent
```

不要一开始放长期 Memory。

---

# 56. 为什么 Latent 不应成为 Cross-Task Memory v1

Hidden 强绑定：

```text
model
weights
context
position
alignment
prompt layout
```

而且不可解释。

第一版：

```text
task-local
one-hop / short-hop handoff
```

最稳。

跨任务：

```text
Semantic Memory
```

继续负责。

---

# 57. Embedding 是否会阻碍 Hidden？

不会。

真正要避免的是：

```text
SemanticStateRef
```

变成万能 Contract。

正确：

```text
SemanticSelectionState
    Retrieval specific

LatentState
    Neural handoff specific
```

底层可以共享：

```text
StateStore
SHM
hash
lease
authorization
receipt
```

。

---

# 58. StateBus 应共享基础设施，不共享语义 Contract

共同：

```text
state_id
storage
blob_hash
contract_hash
lease
grant binding
consumer authorization
actual-use receipt
release
```

独立：

```text
Semantic:
encoder
source hashes
hydrate manifest
top-k semantics

Latent:
model fp
source layer
alignment
shape
injection boundary

Decision:
candidate surface
probability semantics
risk/calibration
```

。

---

# 59. Hidden 与 KV Contract 也不应该合并

即使它们都是 model-internal tensor：

```text
LatentStateRef
```

需要：

```text
alignment
receiver model
injection boundary
advisory trust
```

KV：

```text
KVCacheRef / handle
```

需要：

```text
layer layout
block identity
position
engine generation
cache compatibility
```

完全不同。

---

# 60. 推荐的第一条 Latent Mainline

最适合：

# Executor → Summarizer

原因：

```text
Executor
有较丰富 reasoning

Summarizer
天然需要综合上游 information

已有 Artifact
可保持 Authority

Latent failure
可安全 fallback

不会破坏 Planner/PlanPolicy
```

。

---

# 61. 不推荐 Planner → Runtime Latent

Planner 的 Plan：

```text
必须 typed
可读
可 validate
```

不能：

```text
只靠 hidden 表示计划
```

否则 Runtime authority 被破坏。

所以 Planner 输出仍保持：

```text
PlanProposal
```

。

---

# 62. 不推荐 Latent 替代 Evidence

Evidence：

```text
有来源
有 locator
可引用
可验证
```

Latent 不具备。

所以：

```text
Evidence / Artifact
= truth-bearing plane

Latent
= advisory representation plane
```

。

---

# 63. 不推荐 Latent v1 直接承担 Tool Arguments

Tool 参数要求：

```text
可解释
schema valid
可 audit
```

Latent 不适合直接作为：

```text
shell / python / DB operation parameters
```

。

Decision 可以选择：

```text
是否调用已经授权的 capability
```

但实际 arguments 仍然 typed。

---

# 64. Hidden Benchmark 必须证明“信息真的通过 Latent”

仅：

```text
Text vs Latent
```

不够。

必须：

```text
MATCHED_LATENT

MISMATCHED_LATENT

ZERO_LATENT

MOMENT_MATCHED_RANDOM
```

。

如果：

```text
Matched
≈
Mismatched
```

说明 Receiver 可能只依赖：

```text
有一个 prefix
```

而没有依赖：

```text
当前样本 latent semantics
```

。

---

# 65. Latent 任务必须存在 Private Information Dependency

Receiver 不能已经看到 Sender 的全部信息。

否则：

```text
Latent
```

没有必要。

但也不能：

```text
把唯一 Gold answer 偷藏在 latent
```

。

正确：

```text
Artifact
保留 authoritative facts

Latent
补充 reasoning context / emphasis / relationship representation
```

。

---

# 66. 推荐 Latent Experiment

第一阶段：

```text
Text Handoff

StateBridge Reference

StateBus Matched Latent

Mismatched

Zero

Random
```

指标：

```text
accuracy / pass@1

visible handoff tokens

latent positions

latent bytes

capture latency

alignment latency

publish/consume latency

receiver TTFT

E2E

GPU peak

fallback
```

。

---

# 67. Decision Experiment

比较：

```text
Gate OFF

Current Retry Gate

DecisionPolicy v2
```

报告：

```text
incorrect dispatch

abstention

retry

expand

replan

risk-coverage

extra tokens

latency
```

。

---

# 68. Embedding Experiment

需要明确：

```text
真实 semantic backend
```

而不是 deterministic test encoder。

至少记录：

```text
encoder id
revision
fingerprint
dims
normalization
device
dtype
```

。

---

# 69. 联合实验才真正证明“协同”

最终可以有：

```text
A
Text + no Decision feedback

B
Embedding only

C
Embedding + Latent

D
Embedding + Decision

E
Embedding + Latent + Decision
```

测：

```text
quality
retrieval rounds
text handoff tokens
wrong dispatch
latency
```

。

但这一组要等三条单独机制都稳定后再做。

---

# 70. 不应该一开始联合调所有机制

正确顺序：

```text
Embedding
已有机制 harden

Decision
独立升级验证

Latent
独立 reference + causal validation

最后：
联合 mainline
```

。

否则：

```text
质量变好/变坏
```

无法 attribution。

---

# 71. 推荐 Implementation Slices

## S0 — State Foundation

修：

```text
Ref commitment
Grant binding
immutable state ID
atomic metadata
idempotent release
model fingerprint
```

。

## S1 — Decision v2

```text
DecisionSurface
candidate_mass
absolute confidence
policy
calibration
```

。

## S2 — Modern Hidden Probe

```text
Qwen3-4B/8B
hidden extraction
prompt embeds
mixed text/latent
```

。

## S3 — StateBusHiddenStatesConnector

```text
last-K hidden
async D2H
FP16
SHM
```

。

## S4 — StateBridgeAligner

reference correctness。

## S5 — LatentState Lifecycle

```text
publish
Ref
consume
receipt
release
fallback
```

。

## S6 — Executor → Summarizer

正式 mainline。

## S7 — Decision Feedback

```text
EXPAND_EVIDENCE
→ RetrievalFeedback
→ Embedding selection
```

。

---

# 72. Hidden v1 Go / No-Go

必须证明：

```text
StateBus Latent
≈ StateBridge reference
```

并：

```text
Matched > Mismatched / Zero / Random
```

至少在一个强信息依赖任务成立。

否则：

```text
不接主线
```

。

---

# 73. APC 与 Hidden 的集成 Gate

必须验证：

```text
Shared Prefix
→ APC hit
```

在加入 Latent 后没有被破坏。

对比：

```text
shared prefix only

shared prefix + latent

latent placed before shared prefix
```

应观察：

```text
正确 layout:
前部 APC hit 保留

错误 layout:
shared prefix reuse 消失
```

。

---

# 74. Hidden vs KV 最终对照表

| 维度 | Hidden / Latent | KV Cache |
|---|---|---|
| 来源 | Transformer internal representation | 每层 Attention 的 K/V projection |
| 典型 Shape | `[K,H]` | `[L,2,T,Hkv,D]` 概念结构 |
| 是否每层都有 | 通常选择一层 | 是 |
| 是否直接表达新的 Agent representation | **是，主要用途** | 通常不是 |
| Consumer 怎么用 | 对齐后进入 input-embedding boundary | 直接供每层 Attention 读取 |
| Consumer 是否重新跑 Transformer | **是** | 对 inherited positions 不需要重新 Prefill |
| 主要目标 | semantic representation handoff | compute reuse |
| Payload | 较小 | 很大 |
| StateBus v1 | BUILD | APC 主线，Explicit KV freeze |
| Trust | advisory | compute-state compatibility |

---

# 75. 一个一句话判断法

问：

> Consumer 如果拿到同样的 textual input，能不能通过重新 forward 得到这个状态？

如果：

```text
可以
```

例如：

```text
KV(shared prefix)
```

那么主要是：

# Compute Reuse State

。

如果：

```text
Consumer 没有 Producer 的完整 private reasoning/context，
无法仅靠自己的输入重建 Producer Hidden
```

那么：

# Semantic Representation State

。

---

# 76. 最终推荐的 StateBus 非文本架构

```text
                          StateBus
                             │
           ┌─────────────────┼───────────────────┐
           │                 │                   │
           ▼                 ▼                   ▼
 Semantic Selection      Latent State       Decision State
     Embedding              Hidden              Logit
       │                     │                   │
       │                     │                   │
 “看什么”             “传什么内部表示”      “下一步怎么走”
       │                     │                   │
       └─────────────────────┼───────────────────┘
                             │
                             ▼
                       Runtime Feedback


════════════════════ Compute Plane ════════════════════

                         One vLLM
                             │
                             ▼
                       APC / KV Cache
                             │
                  “哪些 Prefill 不要重算”
```

---

# 77. 端到端最终主链

```text
Task
 ↓
Retriever
 ↓
Semantic Embedding
 ↓
Selected Evidence
 ↓
Canonical Shared Prefix
 ↓
Executor Request
 ↓
vLLM
 ├─ APC lookup on shared text
 ├─ normal generation
 └─ hidden capture
        ↓
    RawHidden
        ↓
  StateBridgeAligner
        ↓
  LatentStateRef
        ↓
Summarizer Request
[Shared Prefix]
[Artifact]
[Latent]
[Role Suffix]
        ↓
vLLM
 ├─ shared text APC hit
 └─ consume latent
        ↓
Summarizer Hidden
        ↓
LM Head
        ↓
Decision candidate probabilities
        ↓
DecisionState
        ↓
Runtime
 ├─ ACCEPT
 ├─ RETRY
 ├─ EXPAND_EVIDENCE
 │       ↓
 │   RetrievalFeedback
 │       ↓
 │   Semantic Embedding
 │
 └─ REPLAN
```

这就是三类非文本状态与 APC/KV 最终的完整协同模型。

---

# 78. 最终冻结结论

1. StateBus 当前的 Embedding 是 `Retrieval/Semantic Embedding`，不能和 Transformer `Input Embedding` 混淆；
2. Embedding 决定 Agent 推理前“看到什么”；
3. Producer Hidden 是 Input Embedding 之后、LM Head 之前的深层 contextual representation；
4. 实现时必须记录精确 source layer/hook/norm semantics，不能笼统写“final hidden”；
5. Raw Hidden 不直接跨 Agent；
6. Raw Hidden 经 StateBridge-style alignment 后成为 `AlignedLatentPrefix`；
7. `LatentStateRef` 指向 Aligned Latent，而不是 Raw Hidden；
8. Consumer 将 Latent 作为 continuous input positions，在自己的 Layer 1 开始正常 forward；
9. 当前 Latent v1 不是 layer-to-layer continuation；
10. Consumer 消费 Latent 后形成新的 Hidden，再经 LM Head 得到 Decision Logits；
11. DecisionState 不直接读取 LatentState；
12. DecisionState 是当前模型内部状态在 Runtime 合法动作空间中的低维 belief projection；
13. Decision 的 `EXPAND_EVIDENCE` 可以反向触发新的 Retrieval Embedding，形成 feedback loop；
14. 三者真正的协同是 `Selection → Representation → Decision → Feedback`；
15. Hidden 与 KV 不是同一种状态；
16. Hidden 是 representation state，KV 是 attention computation state；
17. Hidden 用于 Agent semantic handoff；
18. KV/APC 用于相同 prefix 的 Prefill compute reuse；
19. 当前 one-vLLM topology 下 APC 是主要 KV 机制；
20. Hidden 与 APC 可以同时工作，Prompt Layout 推荐 `Shared Prefix → Latent → Role Suffix`；
21. Artifact/Evidence 保持 authoritative，Latent 只做 advisory sideband；
22. 第一主链接入点优先 `Executor → Summarizer`；
23. Latent failure 必须安全 fallback；
24. Latent benchmark 必须包含 matched/mismatched/zero/random causal controls；
25. 最终 StateBus 的核心不是“有三种 tensor”，而是把 selection state、neural handoff state、decision state 和 compute reuse 分别纳入统一 Runtime governance。
