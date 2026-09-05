# StateBus Model-Internal State Architecture
## Decision Logit、Latent Hidden 与 KV Compute Reuse 的统一设计

> **项目**：StateBus / `qcrs/os`  
> **主要源码基线**：`qcrs/os:master`  
> **当前正式推理环境**：Qwen3-32B + vLLM 0.9.2 + PyTorch 2.7.0  
> **目标部署前提**：**一个 vLLM 服务承载多个逻辑 Agent**，不是每个 Agent 单独部署一个 vLLM  
> **日期**：2026-09-03  
> **文档性质**：架构设计 / 源码审计 / 论文与开源实现调研 / Implementation 前规格  
> **本阶段不做**：不直接修改 StateBus/vLLM，不把所有研究路线同时实现，不推翻已有 Embedding/APC/Explicit-KV 实验

---

# 0. Executive Summary

这一轮最重要的结论不是“再增加几种 tensor”，而是把 StateBus 的模型内部状态能力拆成两个互补平面：

```text
                    StateBus Runtime
                           │
                  Typed Control Plane
         Plan / Capability / Grant / Ref / Audit
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
Semantic Selection     Latent Handoff     Decision State
   Embedding              Hidden              Logit
    “看什么”              “传什么”            “怎么走”
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
                    Logical Agents
                           │
                           ▼
                     One vLLM Engine


════════════════════ Compute Reuse Plane ════════════════════

                    InferenceReusePolicy
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
           Recompute       APC       Optional Offload
                         GPU-local       CPU / LMCache
```

最终建议：

| 机制 | 正式定位 | 核心问题 | 当前决策 |
|---|---|---|---|
| Embedding | `SemanticSelectionState` | 应该看哪些 Evidence / Memory？ | 保留，少投入 |
| Logit | `DecisionState` | 当前动作是否值得执行？retry / expand / replan？ | **升级** |
| Hidden | `LatentState` | 上游 Agent 的连续内部表示如何直接交给下游 Agent？ | **核心新增** |
| APC | Engine-local Shared Compute Memory | 同一 vLLM 中相同 prefix 是否已经算过？ | **保留主线** |
| Explicit KV | Explicit Continuation Baseline | StateBus 能否显式继承已完成 prefix 计算？ | 保留并冻结 |
| vLLM Native KV Offload | APC 的容量扩展层 | GPU KV 不够时是否下沉 CPU/secondary tier？ | 条件式 |
| LMCache | 外部 KV data plane | 跨 engine、SSD/remote、持久化、non-prefix reuse | 后续按需 |
| Semantic KV Relay | LatentMAS/C2C/KVCOMM 风格 | KV 是否直接承担 semantic communication？ | 当前不做 |

一句话冻结：

> **Embedding 负责 input selection；Latent Hidden 负责 inter-agent representation handoff；Decision Logit 负责 bounded runtime control；APC/KV 负责重复 Transformer 计算的复用。**

---

# 1. 从赛题反推真正需求

赛题核心不是“实现越多内部 tensor 越好”，而是要求证明三个基础设施问题：

1. 低开销结构化通信；
2. 非文本中间状态直接交换；
3. 共享记忆跨任务复用。

赛题明确允许：

```text
embedding
语义向量
隐藏状态特征
其他中间表示
```

所以当前 Embedding 已经满足最低字面要求。

但是如果目标是争取“状态传递创新”分数，Embedding 的创新 ceiling 有限，因为当前它最终仍然：

```text
vector
→ top-k evidence IDs
→ hydrate text
→ LLM
```

它没有解决：

```text
Agent A internal representation
→ Agent B neural input
```

因此：

```text
Embedding
= 基础非文本选择状态

Hidden / Latent
= 非文本语义 handoff headline
```

更合理。

---

# 2. 当前 StateBus 四条模型状态路径

当前 `docs/implementation/runtime/model-state-paths.md` 已经把系统分成：

```text
Embedding
Logit Gate
Prefix Reuse
Explicit KV Continuation
```

其真实逻辑：

```text
Planner
  ↓
Retriever
  ↓
Embedding Matrix
  ↓
SemanticStateRef
  ↓
hydrate Evidence
  ↓
canonical shared prefix
  ↓
Executor
  ↓
candidate probabilities
  ↓
LogitStateRef
  ↓
Gate
  ↓
CodeAct / Worker
  ↓
ExecutionArtifactRef
  ↓
Summarizer
```

旁路：

```text
canonical shared prefix
→ vLLM APC

Executor parent prefix
→ Explicit KV handle
→ Summarizer continuation
```

因此当前项目并不是缺 feature，而是缺少清晰的 state semantics。

---

# 3. 一个必须先修正的命名：`runtime/neural_state.py`

仓库已经存在：

```text
statebus/runtime/neural_state.py
```

但它不是 Hidden State。

里面主要是：

```text
PrefixLineageIdentity
NeuralStateHandle
EngineLocalPrefixRegistry
NeuralPrefixReuseEstimate
```

源码甚至明确写：

```text
prefix_identity_and_scheduling_control_plane_only_no_kv_tensor_export
```

所以它实际上属于：

```text
APC / Prefix Reuse Control Plane
```

不是：

```text
Latent / Hidden Neural State
```

建议未来重命名语义为：

```text
runtime/prefix_reuse_state.py
PrefixReuseHandle
PrefixLineageIdentity
```

旧 `NeuralStateHandle` 可保留 compatibility alias。

否则后面会出现：

```text
NeuralStateHandle
LatentStateRef
HiddenStateCacheSpec
```

三个概念混淆。

---

# 4. 最终两大 Plane

## 4.1 Agent Semantic / Decision Plane

```text
SemanticSelectionState
DecisionState
LatentState
```

它们真正影响：

```text
Agent 看什么
Runtime 做什么
下游 Agent 如何推理
```

## 4.2 Compute Reuse Plane

```text
APC
Explicit KV
Native KV Offload
LMCache
```

它们主要影响：

```text
某段 Transformer 计算要不要重做
```

不应该再把 APC/KV 包装成与 Hidden 同级的“语义消息”。

---

# Part I — Decision Logit

# 5. 当前 Logit 到底传的是什么

当前 StateBus 并没有传完整 vocabulary logits。

实际传：

```text
2~8 个合法候选的 probability
+
other_mass
```

例如：

```text
A → DSL
B → CodeAct
C → Retrieve More
```

Executor 输出：

```json
{"choice_code":"B"}
```

Runtime 定位该 alias token，读取：

```text
p(A)
p(B)
p(C)
```

并构造：

```text
other_mass = 1 - Σ p(candidate)
```

最后以：

```text
little-endian float32
```

通过：

```text
SHM
→ LogitStateRef
→ UDS
→ independent Gate PID
```

消费。

这其实是一个很干净的 **bounded belief state**。

---

# 6. 当前 Gate 已经证明了什么

当前 controlled challenge：

```text
Gate off:
Validator 8 / 12

retry_once:
Validator 12 / 12
```

同时：

```text
不可判定错误放行:
2 → 0
```

但成本：

```text
vLLM calls:
24 → 38

Token:
6110 → 9952
```

因此它证明的是：

> 数值概率状态可以真实改变 Runtime dispatch，并降低错误执行。

它不是 token/latency optimization。

所以正式定位应该是：

# Decision State / Risk Control

---

# 7. 为什么不应该叫“语义 Logit Communication”

Logit 并不包含：

```text
Agent A 的丰富内部 reasoning
```

它表达的是：

```text
在 Runtime 已定义的合法选项上
模型当前更相信哪个动作
```

例如：

```text
DSL       0.71
CodeAct   0.17
Retrieve  0.08
Other     0.04
```

因此其核心问题：

> “这个动作应不应该被执行？”

不是：

> “Agent A 想了什么？”

---

# 8. DecisionState 的 Authority 边界

非常重要：

```text
Runtime 定义 candidate surface
LLM 只提供 belief
```

不能发生：

```text
LLM 对未授权 tool 概率高
→ Runtime 自动授权
```

也不能：

```text
confidence 高
→ 绕过 PlanPolicy / Artifact Validator
```

DecisionState 只是：

```text
Policy Input
```

不是：

```text
Authority Source
```

这和 StateBus 当前：

```text
Agent proposes
Runtime authorizes
```

完全一致。

---

# 9. 外部研究为什么支持这条路线

2026 的 Function-Calling uncertainty 工作研究了：

```text
模型调 function/tool 前
怎么判断这次调用是否可靠
```

一个重要结果是：

```text
单样本 logit-based UQ
在 function-calling 场景非常有竞争力
```

尤其应该聚焦：

```text
function name
argument names
argument values
```

等真正有语义意义的 token。

这和 StateBus 当前设计：

```text
把 semantic action 映射到 A/B/C 单 token
→ 精确读取候选概率
```

方向高度一致。

所以我们不需要为了“更高级”直接跳到多样本 Semantic Entropy。

---

# 10. Semantic Entropy 应该用在哪里

Semantic Entropy 解决：

```text
自由文本形式不同
但意义相同
```

的问题。

例如：

```text
Paris
The answer is Paris.
France's capital is Paris.
```

token sequence 不同但语义相同。

这种情况下：

```text
multi-sample
→ semantic clustering
→ entropy over meanings
```

有意义。

但是 StateBus 的 closed decision surface 已经是：

```text
A
B
C
```

每个 alias 对应一个离散 semantic action。

因此：

```text
DecisionState
→ exact single-sample candidate probabilities

Free-form answer uncertainty
→ future semantic entropy
```

应该分开。

---

# 11. Entropix 值得借什么

Entropix 根据：

```text
entropy
varentropy
```

将模型状态区分为不同不确定性模式，然后动态改变 sampling。

StateBus 值得借的不是 sampler 算法，而是：

> 不同 uncertainty pattern 应该触发不同 Runtime behavior。

我们要触发的是：

```text
ACCEPT
RETRY
EXPAND
REPLAN
FAIL
```

而不是只改：

```text
temperature / top_p
```

。

---

# 12. 当前 Decision Gate 的主要不足：只有 ACCEPT / RETRY

现实情况：

```text
DSL = 0.31
CodeAct = 0.29
Retrieve = 0.08
other_mass = 0.32
```

如果只执行：

```text
RETRY same question
```

不一定合理。

更准确可能是：

```text
candidate surface 不完整
```

应该：

```text
EXPAND_EVIDENCE
或
REPLAN
```

。

---

# 13. `other_mass` 当前使用不足

当前 `other_mass` 被用于 entropy，但 ACCEPT 判据只看：

```text
selected is top1
AND margin >= 0.10
```

例如：

```text
A = 0.25
B = 0.10
other_mass = 0.65
```

：

```text
margin = 0.15
```

看似够大。

但：

```text
candidate_mass = 0.35
```

说明模型大量概率质量在合法候选外。

这时 ACCEPT 很危险。

---

# 14. DecisionState v2 推荐指标

定义：

\[
p_s = P(selected)
\]

\[
m = p_1 - p_2
\]

\[
c = \sum_i p_i = 1-p_{other}
\]

\[
H = -\sum_i p_i\log p_i - p_{other}\log p_{other}
\]

解释：

```text
p_s
= selected absolute confidence

m
= legal candidates 之间的 discrimination

c
= candidate surface coverage

H
= overall uncertainty
```

---

# 15. DecisionPolicy v1

第一版只支持：

```text
ACCEPT

RETRY_SAME

EXPAND_EVIDENCE

REPLAN

FAIL_CLOSED
```

不要一开始支持几十种动作。

建议逻辑：

```text
selected != top1
        ↓
RETRY / REPLAN

selected == top1
        ↓
candidate_mass low?
        ├─ yes → EXPAND / REPLAN
        └─ no
             ↓
selected probability low?
        ├─ yes → RETRY
        └─ no
             ↓
margin low?
        ├─ yes → RETRY
        └─ no → ACCEPT
```

---

# 16. Threshold 不应该再是 global 0.10

当前：

```text
margin >= 0.10
```

适合 controlled challenge。

正式 Runtime 要考虑：

```text
model fingerprint
candidate count
decision type
risk class
```

例如：

```text
read-only retrieval
```

和：

```text
destructive filesystem action
```

所需 confidence 不应该一样。

建议：

```text
DecisionCalibrationProfile
├─ model_fingerprint
├─ decision_surface_kind
├─ candidate_count_bucket
├─ risk_class
├─ p_selected_threshold
├─ candidate_mass_threshold
├─ margin_threshold
└─ entropy_threshold
```

---

# 17. DecisionState 最适合三个实际场景

## D1 — Capability / Tool Dispatch

```text
DSL
CodeAct
Retrieve More
```

选择已经由 Planner/Runtime 限定，DecisionState 只决定当前 selected capability 是否值得真正执行。

这是当前 Gate 的直接升级。

## D2 — Evidence Sufficiency

Surface：

```text
ANSWER_NOW
RETRIEVE_MORE
```

candidate mass 或 answer confidence 不足：

```text
EXPAND_EVIDENCE
```

这个非常适合 StateBus Retriever。

## D3 — Replan / Escalation

后续：

```text
CONTINUE
REPLAN
```

或：

```text
CHEAP_PROVIDER
STRONG_PROVIDER
```

但这应等 Router 稳定后再接。

---

# 18. DecisionState Contract

建议兼容演进：

```python
DecisionStateRef:
    state_id

    task_id
    trace_id
    step_id
    attempt_id

    producer_role
    consumer_policy

    decision_surface_id
    decision_surface_hash

    selected_candidate_id

    probability_semantics
    candidate_count

    blob_hash
    contract_hash

    model_fingerprint

    created_at_ns
    expires_at_ns

    schema_version
```

Payload 仍然：

```text
candidate probabilities
+
other_mass
```

。

---

# 19. DecisionSurface

```python
DecisionSurface:
    surface_id

    candidates: tuple[
        DecisionCandidate(
            candidate_id,
            capability_id,
            action_class,
            risk_class,
            authority_hash,
        )
    ]

    schema_version
```

关键原则：

# DecisionSurface 由 Runtime 构造，不由 LLM 构造。

---

# 20. Decision Receipt

```python
DecisionReceipt:
    action

    selected_candidate_id

    selected_probability
    candidate_mass
    top_margin
    entropy

    policy_version
    reason

    fallback
    consumed_state_id
```

。

---

# 21. 12~36 B 是否还需要 SHM

生产角度：

```text
12 B ~ 36 B
```

使用：

```text
SHM + sidecar + UDS
```

显然过重。

但赛题审计角度它非常有价值：

```text
真实非文本
跨 PID
实际消费
改变 dispatch
```

建议双模式：

```text
STATEBUS_DECISION_TRANSPORT=shm_audit

STATEBUS_DECISION_TRANSPORT=inline_binary
```

生产默认：

```text
inline typed binary
```

专项演示：

```text
shm_audit
```

。

---

# Part II — Latent Hidden State

# 22. Hidden 到底解决什么

Embedding：

```text
从已有候选里选什么
```

Hidden：

```text
Agent A 处理自己的上下文后
形成了什么内部 contextual representation
如何直接给 Agent B
```

所以：

```text
Embedding = Input Selection

Hidden = Inter-Agent Representation Handoff
```

。

---

# 23. 真正要传的不是 Raw Hidden

代码层必须区分：

```text
CapturedHiddenState
    ↓
Alignment
    ↓
AlignedLatentPrefix
    ↓
LatentStateRef
```

Raw Final Hidden：

```text
provider-local
ephemeral
```

真正跨 Agent 发布：

# Aligned Latent Prefix

---

# 24. 为什么 Raw Final Hidden 不能直接塞给 Receiver

Input Embedding：

```text
Embedding Table 的输出
```

Final Hidden：

```text
经过几十层 Attention / MLP / Residual 后的 representation
```

虽然：

```text
hidden_dim 相同
```

但分布不同。

直接：

```python
generate(inputs_embeds=raw_final_hidden)
```

通常是 OOD。

StateBridge 的核心价值就是：

```text
Hidden Space
→ Receiver Input Embedding Space
```

对齐。

---

# 25. StateBridge 的具体算法

流程：

```text
Sender final hidden sequence
       ↓
Center
       ↓
Regularized Covariance
       ↓
Whitening
       ↓
Orthogonal Procrustes
       ↓
Reconstruct in embedding statistics
       ↓
Norm Calibration
       ↓
Vocabulary Anchoring
       ↓
Aligned continuous prefix
```

然后：

```text
Receiver normal prompt embeddings
+
Aligned latent prefix
```

进入：

```python
model.generate(inputs_embeds=...)
```

。

---

# 26. 为什么 StateBridge 非常贴 StateBus

它的公开版本主要针对：

```text
homogeneous MAS
same pretrained weights
```

而 StateBus 当前正是：

```text
一个 Qwen3
被 Planner / Executor / Summarizer 等逻辑 role 共用
```

所以：

```text
Producer Model == Consumer Model
```

天然成立。

不需要处理异构模型 projector。

---

# 27. StateBridge 源码最值得借的三块

## 27.1 `HiddenStateCapture`

它不是：

```text
output_hidden_states=True
保存所有 layer × all tokens
```

而是：

```text
last transformer layer
forward hook
每次 forward 只取最后 position
```

输出：

```text
[batch, generated_steps, hidden_dim]
```

这大幅降低内存。

## 27.2 `_align_hidden_sequence`

真实实现：

```text
center
covariance
eigh whitening
SVD Procrustes
norm calibration
vocab snapping
```

。

## 27.3 `_generate_with_prefix`

做：

```text
normal prompt embedding
+
latent prefix
+
attention mask
```

然后：

```python
model.generate(inputs_embeds=...)
```

。

---

# 28. StateBridge 选择哪些 Hidden

官方逻辑：

```text
优先找到 </think>
```

若存在：

```text
只保留 think 结束后的 generated hidden
```

再：

```text
最多取最后 K 个
```

通常：

```text
K <= 64
```

。

如果没有 `</think>`：

```text
最后 K 个 generated hidden
```

。

这个逻辑不能硬编码进 StateStore，应该成为：

```text
LatentExtractionPolicy
```

例如：

```text
post_think_last_k

last_k
```

。

---

# 29. 必须准确描述：StateBridge Sender 仍生成 token

StateBridge 仍然调用：

```python
model.generate(...)
```

然后 forward hook 捕获每个生成 step 的 hidden。

所以它没有消除：

```text
Sender autoregressive generation
```

它消除的是：

> Sender 必须把内部表示先压缩成自然语言，才能作为 Agent 间唯一 communication payload。

正式 claim 应该是：

```text
remove discrete text serialization bottleneck
```

而不是：

```text
sender no longer generates
```

。

---

# 30. LatentMAS 与 StateBridge 的根本区别

LatentMAS 更激进。

HF 路径：

```text
Agent 1 prompt
    ↓
last hidden
    ↓
realign
    ↓
inputs_embeds
    ↓
past_key_values
    ↓
latent step
    ↓
继续累积 KV
    ↓
Agent 2
    ↓
...
```

也就是：

```text
latent rollout
+
shared past KV working memory
```

而 StateBridge 更像：

```text
一段 Agent output hidden
→ alignment
→ next Agent continuous prefix
```

---

# 31. 为什么当前不做 LatentMAS 主线

LatentMAS 把：

```text
semantic communication
latent autoregressive rollout
KV continuation
```

同时绑在一起。

问题：

```text
实现复杂
实验 attribution 困难
与 vLLM cache/position 强耦合
```

StateBridge 可以先回答最重要的问题：

> Continuous Hidden Representation 能不能成为真正 Agent message？

因此：

```text
StateBridge = Latent v1

LatentMAS = Future v2 / research
```

。

---

# 32. Communicating Activations 为什么暂不做

ICML 2025 的 Communicating Activations 直接：

```text
Agent B forward 到中层
      ↓
暂停
      ↓
融合 Agent A intermediate activation
      ↓
继续后半段
```

这是很纯粹的 activation communication。

但它需要：

```text
layer-level interception
mid-forward injection
serving hot-path 修改
```

比 StateBridge 对 vLLM 的侵入强很多。

适合作为 future provider，不适合第一版本。

---

# 33. CIPHER 能借什么

CIPHER：

```text
raw vocabulary distribution
→ expected embedding
→ next Agent
```

它解决的是：

```text
采样一个 token 会丢掉 belief distribution
```

更像：

```text
Rich Decision / Belief State
```

不是 full Hidden reasoning。

可以作为 DecisionState 的 future representation，不是 Latent v1。

---

# 34. 现代 vLLM 已经改变 Hidden 的可实现性

当前 StateBus 正式环境还是：

```text
vLLM 0.9.2
```

不建议直接覆盖。

但是现代 vLLM 已经有：

```text
Prompt Embeddings
Hidden State Extraction
```

这使：

```text
vLLM-native StateBus Latent
```

成为可行工程方案。

建议：

```text
legacy-vllm-0.9.2
    保留旧 benchmark

modern-neural-state
    新增 Hidden/Latent capability
```

两套环境并存，成熟后再合并。

---

# 35. Modern vLLM Prompt Embeddings

现代 vLLM 支持：

```text
--enable-prompt-embeds
```

能够接：

```text
[sequence_length, hidden_size]
```

的 prompt embeddings。

Chat 路径也能够把：

```text
normal text
+
prompt embeddings
```

组合。

这正好对应：

```text
shared text prefix
+
LatentState
+
role text suffix
```

。

---

# 36. 一个极关键事实：Prompt Embeds 与 APC 可以共存

现代 vLLM block hash 已经把：

```text
prompt embeddings hash
```

纳入 prefix block identity。

所以 Hidden 并不必然要求关闭 APC。

但是 layout 必须设计正确。

错误：

```text
[unique latent]
[shared evidence]
[role suffix]
```

因为第一个 block 已不同，shared evidence 的 parent hash 也全部不同。

正确：

```text
[Canonical Shared Evidence Prefix]
[Latent Sideband]
[Role-Specific Suffix]
```

这样：

```text
shared prefix blocks
```

在不同 role request 间仍可 APC hit。

---

# 37. 这就是 Hidden 完美接入当前 StateBus 的位置

当前 StateBus 已有：

```text
<statebus-shared-prefix-v2>
canonical evidence
</...>

<statebus-role-suffix-v2 role="executor">
...
</...>
```

未来建议：

```text
<statebus-shared-prefix-v3>
canonical shared evidence
</...>

[LatentState continuous positions]

<statebus-role-suffix-v3 role="summarizer">
role instruction
dynamic inputs
</...>
```

于是：

```text
APC
负责公共上下文

Latent
负责 Agent-specific internal representation

Role suffix
负责角色差异
```

三者不冲突。

---

# 38. Modern vLLM Hidden State Extraction

现代 vLLM 已经出现：

```text
extract_hidden_states
```

和：

```text
HiddenStateCacheSpec
```

。

它不是简单在 Python wrapper 中：

```text
output_hidden_states=True
```

而是借已有 speculative/EAGLE hidden plumbing，把 hidden 放入 paged cache，然后通过 connector 导出。

这非常符合 StateBus 的：

```text
large payload out-of-band
small typed control in-band
```

思想。

---

# 39. vLLM `ExampleHiddenStatesConnector`

当前实现基于：

```text
KVConnectorBase_V1
SupportsHMA
HiddenStateCacheSpec
```

worker 侧：

```text
hidden cache
    ↓
slot mapping
    ↓
dedicated CUDA copy stream
    ↓
pinned host tensor
    ↓
async D2H
    ↓
thread pool
    ↓
safetensors
```

并且 request finished 时会：

```text
延迟释放 block
直到 hidden extraction 安全
```

。

这是一个非常好的正式借鉴点。

---

# 40. 推荐实现 `StateBusHiddenStatesConnector`

不要直接在 vLLM ModelRunner 各处打 hook。

优先基于：

```text
ExampleHiddenStatesConnector
```

做 out-of-tree：

```text
StateBusHiddenStatesConnector
```

目标：

```text
vLLM hidden cache
    ↓
只选择 final layer
    ↓
只取最后 K 个 output hidden positions
    ↓
async D2H pinned
    ↓
StateBus SHM / memfd
    ↓
RawHiddenCapture
```

不把完整 hidden 写 safetensors。

---

# 41. 为什么要 GPU 侧先 slice

如果 prompt：

```text
8k tokens
```

但真正 StateBridge 只需要：

```text
最后 K=32/64 output positions
```

那么不应该：

```text
8k hidden
→ CPU
→ 再 slice
```

。

应该：

```text
GPU hidden cache
→ last K slot gather
→ D2H
```

大幅减少传输。

---

# 42. Token lineage 也能拿到

vLLM connector 当前会保存：

```text
token_ids
```

并支持：

```text
include_output_tokens
```

这非常关键，因为 StateBridge Alignment 需要：

```text
generated hidden sequence
↔
generated token IDs
```

以取得：

```text
input embedding(token_ids)
```

做 Procrustes。

所以整个链路是技术闭合的。

---

# 43. vLLM Hidden Extraction 的限制

当前这条能力仍有明确限制，例如：

```text
chunked prefill compatibility
Model Runner V2 support
```

并非所有新执行路径都完全成熟。

所以 Modern Latent prototype 推荐：

```text
V1 Engine
Model Runner V1
disable chunked prefill
```

先把机制做通。

不要同时追 MRv2。

---

# 44. Modern vLLM compatibility lab

先用：

```text
Qwen3-4B
Qwen3-8B
```

验证：

```text
extract_hidden_states

include_output_tokens

prompt_embeds

mixed text + prompt embeds

APC + prompt embeds

Qwen chat template
```

通过后再考虑 Qwen3-32B。

这是因为 StateBridge alignment 包含：

```text
H×H covariance
eigh
SVD
vocab anchoring
```

大 hidden dim 成本更高。

---

# 45. Raw Hidden 与正式 LatentStateRef

推荐：

```text
RawHiddenCapture
    provider-local
    ↓
LatentExtractionPolicy
    ↓
StateBridgeAligner
    ↓
AlignedLatentPrefix
    ↓
LatentStateRef
```

StateBus 对外发布：

```text
AlignedLatentPrefix
```

而不是 raw final hidden。

---

# 46. 为什么发布 Aligned Latent

好处：

1. Consumer 不需要理解 StateBridge 算法；
2. producer/receiver compatibility 可明确声明；
3. alignment error 在 publish 前暴露；
4. payload 可直接用于 prompt embeds；
5. actual-use receipt 容易验证。

---

# 47. `LatentStateRef` 建议

```python
LatentStateRef:
    state_id

    task_id
    trace_id

    producer_step_id
    producer_attempt_id

    producer_role
    allowed_consumer_roles

    representation_type
        = "aligned_hidden_prefix"

    producer_model_fingerprint
    receiver_model_fingerprint
    tokenizer_fingerprint

    extraction_policy
    source_layer

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

    storage_kind

    lease_created_at_ns
    lease_expires_at_ns

    schema_version
```

。

---

# 48. Model Fingerprint 为什么是 P0

Hidden space 强依赖：

```text
architecture
weights
revision
tokenizer
hidden dimension
```

即使都是：

```text
Qwen3-8B
```

也不能仅凭 model name 判断兼容。

第一版强制：

```text
producer_model_fp
==
receiver_model_fp
```

。

单 vLLM 多 role 恰好天然满足。

---

# 49. Latent 必须 Advisory

推荐主链：

```text
Executor
     │
     ├──── ExecutionArtifactRef ─────┐
     │                               │
     └──── LatentStateRef ───────────┤
                                     ▼
                                Summarizer
```

语义：

```text
Artifact
= authoritative

Latent
= advisory
```

最终 claim 必须仍然能回溯：

```text
Evidence
Artifact
```

不能：

```text
Hidden says X
→ X 直接成为 verified fact
```

。

---

# 50. `visible_commitment_hash`

Latent 是不可人读状态。

建议绑定：

```text
同一次 Producer 的 visible/verified output
```

例如：

```text
ExecutionArtifactRef.blob_hash
```

形成：

```text
visible_commitment_hash
```

其含义不是“证明 hidden 正确”，而是：

> 证明这个 Latent payload 与该 Producer output 属于同一次 committed production。

---

# 51. Integrity 和 Semantic Truth 是两回事

Hash/HMAC 只能证明：

```text
payload 未被替换
```

不能证明：

```text
payload 语义正确
```

所以：

```text
Latent
始终 advisory
```

。

---

# 52. Latent Payload 传输

第一版：

```text
FP16
+
SHM
```

就足够。

例如：

```text
K = 64
H = 4096
```

：

```text
64 * 4096 * 2
≈ 512 KiB
```

相比完整 KV 小很多。

没必要第一版做：

```text
CUDA IPC
RDMA
LMCache
```

。

---

# 53. Consumer 输入路径

第一阶段可以：

```text
StateBus Consumer
    ↓
resolve LatentStateRef
    ↓
validate
    ↓
normal vLLM prompt_embeds API
```

即使 API 边界有额外编码，也先证明算法/系统正确。

第二阶段再做：

```text
local SHM handle
→ vLLM plugin
```

避免 base64 / serialization。

不要把性能优化和 Latent correctness 第一阶段绑死。

---

# 54. `LatentConsumptionReceipt`

```python
LatentConsumptionReceipt:
    state_id

    consumer_role
    consumer_step_id
    consumer_attempt_id

    receiver_model_fingerprint

    payload_hash
    contract_hash

    prefix_length
    hidden_dim

    insertion_position

    prompt_commitment_hash
    output_commitment_hash

    fallback_used
    fallback_reason

    consumed_at_ns
```

。

---

# 55. actual-use 证明

不能只证明：

```text
SHM opened
```

至少：

```text
payload resolve
hash match
prompt embeds injected
receiver forward executed
```

Receipt 可记录：

```text
prefix_injected_and_receiver_forward_observed
```

。

至于：

```text
质量有没有提升
```

只能靠 A/B benchmark。

---

# 56. Hidden 必须做因果对照

不能只：

```text
Text
vs
Latent
```

。

至少：

```text
TEXT

MATCHED_LATENT

MISMATCHED_LATENT

ZERO_LATENT

MOMENT_MATCHED_RANDOM
```

。

否则看到 Latent accuracy 提升，也不能证明：

```text
对应样本的 semantic state
```

真的被消费。

---

# 57. Hidden benchmark 必须有真正信息依赖

如果 Receiver 原本已经看到全部 Evidence：

```text
Matched
vs
Mismatched
```

可能差不多。

所以专项 benchmark 应设计：

```text
Specialist / Executor
有 private information

Receiver
看不到完整 Sender reasoning text
```

Latent 才承担真实信息 handoff。

---

# 58. Mainline 与 Causal Diagnostic 分开

## Mainline

```text
Executor
→ Artifact + Latent
→ Summarizer
```

证明：

```text
真实 Runtime 集成成功
```

## Causal Diagnostic

```text
Specialist private evidence
→ Latent
→ Coordinator
```

证明：

```text
example-specific information
真的通过 neural channel
```

。

---

# Part III — KV / APC / Shared Compute Memory

# 59. 先冻结最关键部署事实

当前项目不是：

```text
Planner vLLM
Executor vLLM
Summarizer vLLM
```

三套服务。

而是：

```text
Planner ───────┐
Executor ──────┼──→ One vLLM Qwen3
Summarizer ────┤
Verifier ──────┘
```

逻辑 Agent 只是不同：

```text
prompt
role
tool authority
state visibility
```

请求。

这会决定 KV 的正确架构。

---

# 60. 单 vLLM 下，APC 本身就是跨 Agent KV 共享

从 vLLM 视角：

```text
Executor request
Summarizer request
Verifier request
```

都只是 request。

APC 不关心 Agent 身份。

只关心：

```text
left prefix block hash
```

是否相同。

所以：

> 两个逻辑 Agent 只要拥有相同 token prefix，就天然共享同一个 engine-local KV block。

根本不需要：

```text
Agent A export KV
→ CPU
→ Agent B import KV
```

。

---

# 61. 当前 StateBus APC 做得非常对

它没有重新实现 KV Cache。

StateBus 负责：

```text
多 role 可见 Evidence 交集
    ↓
Canonical shared evidence
    ↓
stable serialization
    ↓
放到 token position 0
    ↓
role-specific suffix later
    ↓
exact tokenizer / chat template identity
    ↓
affinity scheduling
    ↓
vLLM metrics proof
```

vLLM 负责：

```text
KV block creation
hash table
GPU memory
eviction
```

职责非常健康。

---

# 62. 当前 APC 已经足够强

现有专项：

```text
block hit:
0%
→
78.016%
```

平均：

```text
TTFT:
2356.536
→
738.322 ms
```

E2E：

```text
4116.549
→
2345.346 ms
```

warm role：

```text
TTFT 约 -88.3%
```

这已经能作为 Compute Reuse 主要 evidence。

---

# 63. APC 也天然覆盖多轮长对话

例如：

```text
Round 1:
History H

Round 2:
H + User2

Round 3:
H + User2 + Assistant2 + User3
```

每轮都复用前面的 token prefix。

这是 APC 的标准 workload。

所以：

# 不需要额外实现“跨对话 KV transfer”。

只要同一个 vLLM engine cache 仍驻留即可。

---

# 64. 多 Agent 真正的问题是 Role Prompt 导致 Prefix Divergence

传统：

```text
Executor:
[System Executor][Evidence X]

Summarizer:
[System Summarizer][Evidence X]
```

第一 token 就不同。

即使 Evidence X 相同：

```text
也无法 APC hit
```

。

当前 StateBus 已经主动改成：

```text
[Shared Evidence X][Role Suffix]
```

这其实就是：

# Cross-Agent KV Sharing Optimization

并且已经用真实 TTFT 证明。

---

# 65. 因此 APC 正式定位升级

建议叫：

# Engine-Local Cross-Agent Shared Compute Memory

它不是赛题要求的 Semantic Shared Memory 替代品。

但它非常好地回答：

```text
多个 Agent 重复读取同一长上下文时
为什么要重复 Prefill？
```

。

---

# 66. Existing Explicit KV 是否还有必要

有。

当前：

```text
StateBusLocalKVConnector
```

是真实：

```text
KVConnectorBase_V1
```

Producer：

```text
paged KV
→ extract slots
→ pinned CPU registry
```

Consumer：

```text
CPU tensors
→ GPU
→ inject slots
```

所以不是 fake。

---

# 67. Explicit KV 证明 APC 没证明的能力

APC：

```text
引擎自动识别相同 prefix
```

Explicit KV：

```text
StateBus 明确：
state identity
producer
consumer
load
release
forward proof
```

因此它证明：

# Explicit Compute-State Lifecycle

这个证据值得保留。

---

# 68. 但 Explicit KV 不应成为 Production Default

已有结果：

```text
4k prefix handle
≈ 1 GiB

computed prefill:
4806.5
→
710.5

TTFT:
1618.138
→
620.980 ms
```

但完整 mainline wall：

```text
仅 -5.69%
```

Producer：

```text
+6.39% overhead
```

说明：

```text
节省重算
```

是真的。

但：

```text
GPU→CPU→GPU movement
```

太贵。

---

# 69. 当前 Explicit KV 与 APC 还有 accounting 互斥

当前 LOAD path 要求：

```text
num_computed_tokens == 0
```

否则：

```text
local_prefix_cache_must_be_disabled
```

因为：

```text
APC 已经声明一部分 token locally computed

Explicit KV 又声明这些 token inherited
```

会冲突。

所以当前专项分别关闭另一条路径是合理的。

---

# 70. Explicit KV 最终选择

```text
KEEP
FREEZE
```

正式定位：

```text
Legacy Explicit KV Continuation Baseline
```

不再扩：

```text
distributed storage
SSD
remote
复杂 eviction
multi-consumer
```

。

---

# 71. LMCache 在单 vLLM 下不是 P0

LMCache 很强，但当前只有：

```text
One vLLM Engine
```

如果：

```text
GPU APC 容量够
engine 不重启
不需要 remote/SSD
```

引入 LMCache 很可能只是增加系统复杂度。

所以：

# 当前不把 LMCache 设为必做。

---

# 72. APC 容量不够时，第一升级优先 Native vLLM Offload

现代 vLLM 已经有：

```text
OffloadingConnector
```

可以形成：

```text
GPU APC cache
    ↓
Pinned CPU tier
    ↓
optional secondary tier
```

并使用异步 transfer。

对单 vLLM 来说：

```text
Native CPU Offload
```

比先引入完整 LMCache daemon 更自然。

---

# 73. Compute Memory 推荐分层

```text
                 InferenceReusePolicy
                           │
       ┌───────────────────┼────────────────────┐
       ▼                   ▼                    ▼
    Recompute           APC GPU           Offload Tier
                         local                optional
                                              │
                                      ┌───────┴────────┐
                                      ▼                ▼
                                vLLM Native        LMCache
```

优先级：

```text
L0 = APC

L1 = Native CPU Offload
     if capacity pressure

L2 = LMCache
     if advanced sharing/storage
```

。

---

# 74. 什么时候才真的需要 LMCache

出现任一：

```text
多个 vLLM engine

跨 engine restart 持久

SSD

remote cache

shared cache service

CacheBlend non-prefix reuse

RDMA / remote transfer

复杂 Serde / compression
```

才进入 LMCache。

---

# 75. LMCache HiddenStateStore 给了一个重要架构启发

LMCache 已经把：

```text
KV Store
```

和：

```text
HiddenStateStore
```

分开。

原因很直接：

```text
KV
是 per-layer K/V

Hidden
是 [num_tokens, hidden_dim] activation
```

某些 downstream stage 需要 upstream hidden，而 KV 无法反推出 hidden。

它们可以：

```text
共享同一 token/chunk lineage key
```

但：

```text
独立 memory pool
独立 eviction
独立 payload semantics
```

这和 StateBus 应采用的设计完全一致。

---

# 76. StateBus 应“统一 Lineage，不统一 Payload”

可以有：

```text
ContextLineageIdentity
├─ model_fp
├─ tokenizer_fp
├─ token_digest
├─ prompt_layout_version
└─ position_range
```

然后：

```text
Lineage X
├─ SemanticSelection metadata
├─ LatentState
└─ KV cache
```

它们不是同一种 tensor。

只是：

```text
对应同一上下文 lineage
```

。

---

# 77. Non-prefix KV Reuse 当前不要自研

未来如果：

```text
Agent A:
RoleA + Evidence X

Agent B:
RoleB + Evidence X
```

且无法通过 prompt layout 把 X 放到共享 prefix，

再研究：

```text
CacheBlend
KVCOMM
```

。

但当前已经能：

```text
通过 shared prefix compilation
制造 exact prefix
```

优先使用 exact reuse 最稳。

---

# 78. Semantic KV Relay 当前不做

LatentMAS/C2C 等证明：

```text
KV 可以承载 semantic communication
```

研究上成立。

但当前 StateBus 已经选择：

```text
LatentState
```

负责 semantic handoff。

再实现 Semantic KV 会：

```text
功能重叠
工程成本高
实验归因困难
```

所以：

```text
Future Research Only
```

。

---

# Part IV — 三类状态如何同时进入 One vLLM

# 79. 推荐完整主链

```text
Task
 ↓
Planner
 ↓
Retriever
 ↓
Embedding Selection
 ↓
Canonical Evidence
 ↓
Shared Prefix Compiler
 ↓
APC-Reusable Prefix
 ↓
Executor Request
 ↓
vLLM
 ├─ normal output / Artifact
 └─ optional final hidden capture
          ↓
     StateBridge Align
          ↓
      LatentStateRef
          ↓
Summarizer Request
 [Shared APC Prefix]
 [Latent Prefix]
 [Role Suffix]
          ↓
vLLM
          ↓
Bounded Decision Output
          ↓
DecisionState
          ↓
Runtime DecisionPolicy
          ↓
accept / retry / expand / replan
```

---

# 80. 三类 Semantic/Decision State 的时序

```text
Embedding
    LLM reasoning 前
    负责输入选择

Hidden
    Agent A reasoning 后
    负责 Agent→Agent representation handoff

Logit
    bounded decision 后
    负责 Runtime action uncertainty
```

一句话：

```text
Embedding = input selection

Hidden = inter-agent representation

Logit = output/action uncertainty
```

。

---

# 81. APC 是旁路

所有 vLLM request：

```text
Request
  ↓
Prefix cache lookup
  ├─ hit → reuse
  └─ miss → prefill
```

APC 不替代 Hidden。

它只负责：

```text
相同公共前缀不重算
```

。

---

# 82. Hidden + APC 的理想协同

Executor：

```text
[Shared Evidence]
[Executor Suffix]
```

第一次：

```text
Shared Evidence
→ prefill
→ APC KV resident
```

Summarizer：

```text
[Same Shared Evidence]
[Latent]
[Summarizer Suffix]
```

于是：

```text
Shared Evidence
→ APC hit

Latent
→ 只计算小量 K continuous positions

Role suffix
→ normal compute
```

这就是最适合单 vLLM 多 Agent 的组合。

---

# 83. 为什么这比 Full KV Export/Import 更合理

Explicit KV：

```text
可能数百 MiB / GiB
GPU→CPU→GPU
```

Latent：

```text
几十/几百 KiB
```

Shared Evidence：

```text
APC 本地直接命中
不搬数据
```

所以：

# APC + Latent

比：

# Full KV Transfer

更适合当前系统主线。

---

# 84. 状态 Ownership

```text
SemanticSelectionState
Owner:
StateBus StateStore

LatentState
Owner:
StateBus StateStore

DecisionState
Owner:
StateBus / inline control

APC KV
Owner:
vLLM

Explicit KV Baseline
Owner:
legacy WorkerKVRegistry

Offloaded KV
Owner:
vLLM OffloadingConnector / LMCache
```

---

# 85. StateBus 统一的是治理，不是物理存储

所有显式状态可共享：

```text
Identity

Compatibility

Authorization

Commitment

Lease

Actual-use Receipt

Fallback

Audit
```

但 payload 不必：

```text
全部存在 StateStore
```

。

这是未来设计的核心原则。

---

# Part V — Contract / Code Refactor

# 86. State Type 正式命名

建议最终：

```text
SemanticSelectionStateRef

DecisionStateRef

LatentStateRef
```

Compute：

```text
PrefixReuseIdentity

KVReuseObservation
```

未来需要时才加：

```text
KVCacheRef
```

。

---

# 87. `SemanticStateRef` 兼容

不要为 Hidden 改坏旧 Embedding。

短期：

```text
SemanticStateRef
```

保留。

文档/新代码逐步改称：

```text
SemanticSelectionState
```

。

---

# 88. `LogitStateRef` 兼容

第一阶段：

```text
LogitStateRef
```

保留。

新增：

```text
DecisionSurface
DecisionStateContract
DecisionPolicy
```

后续再正式迁成：

```text
DecisionStateRef
```

。

---

# 89. `LatentStateRef` 必须独立

不能复用 SemanticStateRef。

因为后者强绑定：

```text
query_then_candidates

HydrateManifest

source doc

normalized embedding
```

Latent 完全不同。

---

# 90. Ref Commitment

Hidden 前建议把控制面 Ref 从：

```text
ref_id
ref_kind
```

升级到：

```text
RefHandleV2
├─ ref_id
├─ ref_kind
├─ blob_hash
├─ contract_hash
├─ commitment_hash
└─ lease_expires_at
```

。

---

# 91. CapabilityGrant

当前主要绑定：

```text
input_ref_ids
```

建议加入：

```text
input_ref_set_commitment
```

确保：

```text
Controller 授权之后
payload 不能被透明替换
```

。

---

# 92. Prompt Layout Contract

新增：

```text
statebus.prompt_layout.v3
```

绑定：

```text
shared_prefix_hash

chat_template_hash

latent insertion identity

role suffix hash
```

结构：

```text
shared prefix
→ latent
→ role suffix
```

。

---

# 93. `neural_state.py` 重命名迁移

Before：

```text
NeuralStateHandle
```

实际上是：

```text
APC candidate / prefix metadata
```

After：

```text
PrefixCacheCandidateHandle
```

旧名：

```text
NeuralStateHandle = PrefixCacheCandidateHandle
```

保兼容。

---

# Part VI — Implementation Slices

# 94. 总原则

绝对不要同一阶段：

```text
升级 vLLM

改 Logit

实现 Latent

接 LMCache

重做 KV
```

全部一起。

---

# 95. N0 — Freeze Existing Evidence

冻结：

```text
Embedding

Logit 12-case

APC

Explicit KV

Memory

45-case controlled suite
```

记录：

```text
source commit
environment
results
```

。

---

# 96. N1 — Naming / State Foundation Hardening

只做：

```text
neural_state naming cleanup

manifest ID/hash fix

Ref commitment

model fingerprint

atomic metadata/lifecycle

idempotent release
```

Gate：

```text
旧实验全部 Regression PASS
```

。

---

# 97. D1 — DecisionState v2

复用：

```text
exact choice token extraction
```

新增：

```text
DecisionSurface

candidate_mass

selected_probability

DecisionPolicy
```

动作：

```text
ACCEPT

RETRY

EXPAND_EVIDENCE

REPLAN

FAIL_CLOSED
```

。

第一步只接：

```text
Executor → dispatch
```

。

---

# 98. D2 — Calibration

用：

```text
原 12-case
+
正常 cases
+
controlled ambiguity
+
negative cases
```

标定：

```text
p_selected
candidate_mass
margin
entropy
```

报告：

```text
risk-coverage

incorrect dispatch

retry rate

replan rate

extra token

latency
```

而不是只报：

```text
12/12
```

。

---

# 99. L0 — Modern vLLM Compatibility Lab

独立环境：

```text
Qwen3-4B / 8B

V1 Engine

MRv1
```

验证：

```text
extract_hidden_states

include_output_tokens

prompt_embeds

mixed text / prompt embeds

APC + prompt embeds
```

。

---

# 100. L1 — `StateBusHiddenStatesConnector`

基于现代 vLLM：

```text
ExampleHiddenStatesConnector
```

做 out-of-tree provider。

第一版：

```text
final layer only

last K generated positions only

FP16

async D2H

pinned host

StateBus SHM
```

。

---

# 101. L2 — StateBridge Aligner

先复现：

```text
whitening
Procrustes
norm calibration
vocab anchoring
```

。

确保：

```text
HF reference
```

和：

```text
vLLM extracted hidden
```

含义一致。

---

# 102. L3 — Latent Lifecycle

完整：

```text
capture

align

publish

LatentStateRef

consume

prompt_embeds

receipt

release
```

测试：

```text
expired lease

wrong consumer

wrong model

tamper

alignment failure

text fallback
```

。

---

# 103. L4 — Causal Benchmark

必须：

```text
TEXT

MATCHED

MISMATCHED

ZERO

RANDOM
```

先：

```text
Qwen3-4B
```

再：

```text
8B
```

最后才考虑：

```text
32B
```

。

---

# 104. L5 — Mainline Executor → Summarizer

运行模式：

```text
off

telemetry

enabled
```

失败：

```text
fallback Artifact/Text
```

Latent 永远不是 correctness hard dependency。

---

# 105. K0 — APC Reframe

不重写 APC。

只把正式定位改为：

```text
Engine-Local Cross-Agent Shared Compute Memory
```

并完善连续任务实验证据。

---

# 106. K1 — Continuous Task Benchmark

至少两组：

```text
Group A:
同一长报告
不同问题/不同角色

Group B:
同一 corpus / codebase
连续相关任务
```

比较：

```text
Independent Layout

Shared Prefix + APC
```

记录：

```text
query tokens

hit tokens

hit rate

TTFT

E2E

quality
```

。

---

# 107. K2 — Explicit KV Freeze

不新增功能。

保留：

```text
full replay
vs
continuation
```

作为：

```text
explicit compute-state lifecycle proof
```

。

不再成为 README 主创新 headline。

---

# 108. K3 — Optional Native KV Offload

只有出现：

```text
APC eviction
GPU KV capacity pressure
```

才做。

优先现代 vLLM：

```text
OffloadingConnector
```

StateBus 只增加：

```text
tier observation

reuse policy

break-even
```

。

---

# 109. K4 — LMCache Go / No-Go

只有以下需求才 GO：

```text
multi-engine

persistent cache

SSD

remote

CacheBlend

remote transfer
```

否则：

```text
NO-GO
```

。

---

# Part VII — Experimental Design

# 110. Decision Experiment

对照：

```text
Gate Off

Current Retry Gate

DecisionPolicy v2
```

指标：

```text
validator pass

wrong dispatch

abstention

retry count

expand count

replan count

token

latency

coverage

risk
```

。

---

# 111. Latent Experiment

对照：

```text
Text Handoff

StateBridge Reference

StateBus Latent

Mismatched

Zero

Random
```

指标：

```text
accuracy / pass@1

inter-agent text tokens

latent positions

latent bytes

capture latency

alignment latency

publish/resolve latency

receiver TTFT

E2E

GPU peak

fallback
```

。

---

# 112. Latent Position 不应该叫 Token

如果：

```text
K = 64
```

报告：

```text
latent positions = 64
```

不要写：

```text
64 tokens
```

因为这些位置没有 token ID。

同时报告：

```text
latent payload bytes
```

。

---

# 113. APC Experiment

已有：

```text
APC off

shared-prefix APC
```

强结果。

下一步只需补：

```text
10+ round correlated continuous tasks
```

。

这直接满足赛题连续任务要求。

---

# 114. KV Offload Experiment

只有在容量压力下比较：

```text
APC GPU only

APC + CPU Offload
```

否则强行 offload 可能只会变慢。

---

# Part VIII — 与 Router 的统一

# 115. StateRepresentationPolicy

候选：

```text
TEXT

SEMANTIC_SELECTION

LATENT_ADVISORY
```

。

Embedding 是 Retriever policy。

Latent 是 Agent handoff policy。

---

# 116. DecisionPolicy

输入：

```text
DecisionState

risk

budget

Plan authority
```

输出：

```text
ACCEPT

RETRY

EXPAND

REPLAN

FAIL
```

。

---

# 117. InferenceReusePolicy

输入：

```text
same engine?

exact shared prefix?

prefix length?

cache observation?

expected prefill cost?

offload available?
```

输出：

```text
RECOMPUTE

APC

OFFLOADED_KV
```

Current Explicit KV：

```text
experiment-only explicit branch
```

。

---

# 118. 一个最终端到端例子

用户：

```text
分析一个 10k-token 报告，找出异常根因并给出风险结论
```

## Step 1 — Embedding

Retriever：

```text
100 candidate evidence
→ Qwen Embedding
→ select 10
```

回答：

```text
“看什么？”
```

。

## Step 2 — Shared Prefix

StateBus：

```text
多 role 共同可见 Evidence
→ canonical shared prefix
```

。

## Step 3 — Executor

请求：

```text
[Shared Evidence Prefix]
[Executor Suffix]
```

第一次：

```text
APC miss
→ prefill
→ KV remains engine-local
```

。

## Step 4 — Hidden Capture

Executor 产生：

```text
Verified Artifact
+
last-K final hidden
```

。

## Step 5 — Latent

```text
Raw hidden
→ StateBridge align
→ LatentStateRef
```

回答：

```text
“Agent A 已形成什么 representation？”
```

。

## Step 6 — Summarizer

请求：

```text
[Same Shared Evidence Prefix]
[LatentState]
[Summarizer Suffix]
```

：

```text
Shared Evidence
→ APC hit

Latent
→ small extra compute

Suffix
→ normal compute
```

。

## Step 7 — Decision

若有 bounded final action：

```text
Decision Surface
→ candidate probabilities
→ DecisionState
→ Runtime Policy
```

回答：

```text
“现在该怎么走？”
```

。

---

# 119. 四个概念一句话

```text
Embedding
= 看什么

Hidden / Latent
= 上游形成的 representation 传什么

Logit / Decision
= 当前动作值不值得执行

APC / KV
= 哪些 Transformer 计算不用重做
```

。

---

# Part IX — 赛题叙事

# 120. 不建议的讲法

不要：

> StateBus 实现了 Embedding、Logit、APC、Explicit KV、Hidden 五种非文本状态。

这像 feature stacking。

---

# 121. 推荐 Claim

> **StateBus 是一个面向多 Agent 协作的 typed model-state runtime。它通过 Semantic Selection State 选择高价值上下文，通过 Latent State 在逻辑 Agent 间直接传递连续神经表示，通过 Decision State 将模型不确定性转化为受 Runtime 权限约束的执行决策；同时利用同一 vLLM 引擎中的 APC/KV 作为 Shared Compute Memory，复用跨 Agent 与连续任务中已经完成的 Transformer Prefill。**

并强调：

```text
StateBus
统一的是治理：

identity
compatibility
authorization
lifecycle
audit

不是重新实现所有 tensor storage。
```

---

# 122. 与评分项的关系

## 通信效率

```text
Typed Protocol

Text → Latent handoff reduction
```

## 状态创新

主角：

```text
LatentStateRef
Hidden extraction
StateBridge alignment
actual-use receipt
```

DecisionState 辅助。

## 共享记忆

主证据：

```text
现有 Semantic Memory
```

增强：

```text
APC shared compute memory
```

## 系统完整性

```text
多个逻辑 Agent
一个 vLLM
统一 Runtime Policy
```

## 实验

```text
Text vs Structured

Text vs Matched Latent

Matched/Mismatched/Zero/Random

Decision risk/coverage

Continuous-task APC
```

。

---

# Part X — 论文与源码阅读优先级

# 123. P0 — 必须读

## StateBridge

Paper：

https://arxiv.org/abs/2608.13317

Repo：

https://github.com/YanwenPneg/StateBridge

重点函数：

```text
HiddenStateCapture

_align_hidden_sequence

_generate_with_prefix

think_end filtering
```

---

## Modern vLLM Hidden Extraction

Docs/source：

https://github.com/vllm-project/vllm/blob/main/docs/features/speculative_decoding/extract_hidden_states.md

https://github.com/vllm-project/vllm/blob/main/vllm/distributed/kv_transfer/kv_connector/v1/example_hidden_states_connector.py

重点：

```text
HiddenStateCacheSpec

CacheOnlyAttentionLayer

async D2H

block lifetime

include_output_tokens
```

。

---

## Modern vLLM Prompt Embeds

https://github.com/vllm-project/vllm/blob/main/docs/features/prompt_embeds.md

重点：

```text
mixed text/embeds

Chat path

APC prompt embed hash
```

。

---

# 124. P1 — 应该读

## Function-Calling Uncertainty

https://arxiv.org/abs/2604.22985

借：

```text
single-sample logit UQ

meaningful decision tokens

selective execution
```

。

---

## LatentMAS

Paper：

https://arxiv.org/abs/2511.20639

Repo：

https://github.com/Gen-Verse/LatentMAS

重点：

```text
generate_latent_batch

past_key_values

inputs_embeds

run_batch_vllm
```

主要用于理解：

```text
future semantic KV working memory
```

而不是当前 copy。

---

## LMCache Hidden State Store

https://github.com/LMCache/LMCache/blob/dev/lmcache/v1/hidden_state_store.py

借：

```text
Hidden / KV 共享 lineage

但：
独立 payload
独立 allocator
独立 eviction
```

。

---

# 125. P2 — Future Research

## Communicating Activations — ICML 2025

https://proceedings.mlr.press/v267/ramesh25a.html

未来：

```text
layer-level activation provider
```

。

## CIPHER — ICLR 2024

https://proceedings.iclr.cc/paper_files/paper/2024/hash/e444859b2a22df6b56af9381ad1e9480-Abstract-Conference.html

未来：

```text
rich Decision/Belief State
```

。

## KVCOMM

https://arxiv.org/abs/2510.12872

未来：

```text
cross-context / non-prefix compute reuse
```

。

## C2C

https://proceedings.iclr.cc/paper_files/paper/2026/hash/474ada926b331d78f06d95e8913111cc-Abstract-Conference.html

未来：

```text
learned semantic KV
```

。

---

# 126. Causal / Security 参考

## When Does Latent Communication Pay?

https://arxiv.org/abs/2608.04893

必须借：

```text
matched
mismatched
zero
random
```

。

## When Latent Agents Lie

https://arxiv.org/abs/2606.28958

借：

```text
payload commitment

model/session binding

tamper rejection
```

。

---

# 127. 最终去留表

| 当前/计划机制 | 结论 | 说明 |
|---|---|---|
| Embedding | KEEP | 负责 Semantic Selection |
| SemanticStateRef | KEEP + HARDEN | 不作为 Hidden 容器 |
| Logit Gate | UPGRADE | 变成 DecisionState |
| Hidden / Latent | BUILD | 非文本创新主线 |
| APC | KEEP | 单 vLLM 跨 Agent Shared Compute Memory |
| Explicit KV | KEEP + FREEZE | 真实 mechanism baseline |
| Native KV Offload | CONDITIONAL | GPU cache capacity 不足才做 |
| LMCache | DEFER | 多 engine/SSD/remote/non-prefix 时再做 |
| LatentMAS semantic KV | DEFER | Future Research |
| KVCOMM/C2C | DEFER | Future Research |

---

# 128. 最终推荐实施顺序

```text
N0
Freeze existing evidence

↓

N1
State foundation / naming hardening

↓

D1
DecisionState v2

↓

D2
Decision calibration

↓

L0
Modern vLLM compatibility lab

↓

L1
StateBusHiddenStatesConnector

↓

L2
StateBridgeAligner

↓

L3
LatentState lifecycle

↓

L4
Causal benchmark

↓

L5
Executor→Summarizer mainline

↓

K0
APC reframe + continuous tasks

↓

K1
Only if necessary:
Native KV Offload

↓

Future:
LMCache / CacheBlend / KVCOMM / C2C
```

---

# 129. Go / No-Go Gates

## DecisionState GO

必须：

```text
wrong dispatch rate ↓

risk-coverage curve better than simple retry

extra token/latency 可解释
```

。

否则：

```text
保留 current retry gate
```

。

## Latent GO

必须：

```text
Matched > Mismatched / Zero / Random
```

至少在一个强信息依赖 benchmark 上成立。

并且：

```text
StateBus wrapping
不显著低于 StateBridge reference
```

。

否则：

```text
不接 mainline
```

。

## KV Offload GO

只有：

```text
APC cache eviction
导致明显重复 Prefill
```

才继续。

否则：

```text
APC 已够
```

。

---

# 130. 最后冻结结论

1. Embedding 不删除，它负责“看什么”；
2. Hidden 是当前最值得新增的 Agent-to-Agent 非文本 semantic handoff；
3. 真正发布的是 `AlignedLatentPrefix`，不是 raw final hidden；
4. StateBridge 是 v1 最合适的 alignment reference；
5. modern vLLM Hidden Extraction + Prompt Embeds 让 vLLM-native Latent 成为现实；
6. 推荐做 `StateBusHiddenStatesConnector`，而不是直接侵入 ModelRunner；
7. Hidden mainline 优先 `Executor → Summarizer`；
8. Latent 必须 advisory，Artifact/Evidence 仍 authoritative；
9. Latent 必须做 matched/mismatched/zero/random causal controls；
10. Decision Logit 应升级为 `DecisionState`，而不是扩大成“更丰富语义消息”；
11. DecisionState 第一版考虑 `p_selected + margin + candidate_mass + entropy`；
12. DecisionState 只能在 Runtime 已批准的合法 candidate surface 内决策；
13. 当前单 vLLM 多 Agent 架构下，APC 本身就是跨逻辑 Agent 的 KV sharing；
14. 当前 shared-evidence-prefix 是正确且已被实验验证的跨 Agent APC 优化；
15. 多轮长对话同样天然适合 APC；
16. 当前 Explicit KV 是真实 vLLM Connector，值得保留；
17. Explicit KV 不再继续扩成 production distributed cache；
18. 当前不需要立即引入 LMCache；
19. APC 容量不足时优先 modern vLLM Native KV Offload；
20. 只有 multi-engine / SSD / remote / persistence / CacheBlend 才引入 LMCache；
21. Semantic KV relay 当前不做；
22. Hidden 与 APC/KV 可以同时接入，推荐 Prompt Layout：
   `Shared Prefix → Latent → Role Suffix`；
23. 最终 StateBus 的差异点不是“tensor 数量多”，而是：
   **Model-internal state 被转换成具有 identity、compatibility、authorization、lifecycle、actual-use audit 和 Runtime policy 的受治理对象。**

