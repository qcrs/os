# StateBus Native Latent 历史审计、LatentMAS 对齐与后续验证路线

> 记录日期：2026-09-03  
> 项目：StateBus  
> 主题：Qwen3-32B Native Latent / Hidden-State Handoff / Ridge Realignment / LatentMAS / Explicit KV  
> 文档性质：历史审计 + 架构判断 + 下一阶段实验冻结记录  
> 当前状态：**历史审计基本完成；禁止继续无目的历史考古；下一步进入 `RIDGE-FEASIBILITY-01`**

---

# 0. 为什么需要这份记录

StateBus 的非文本中间状态路线经历过多次迭代：

```text
Semantic Embedding
    ↓
Logit / Decision State
    ↓
Native Hidden-State Handoff
    ↓
APC / Explicit KV
    ↓
重新审视 Latent Communication
```

近期重新分析 StateBridge、LatentMAS、RecursiveMAS、CIPHER 等工作时，一个核心问题重新出现：

> **StateBus 过去的 Native Latent 到底做到了什么？为什么失败？失败的是 vLLM 集成、Hidden-State representation，还是 alignment？**

如果这个问题不先厘清，很容易出现两个错误：

1. 把旧实验的失败错误归因成“Hidden State 这条路线不成立”；
2. 重复实现过去已经做过的 vLLM Hidden-State / prompt-embeds / lifecycle 机制。

本轮通过：

- `os1` 历史 Git commit；
- `feat/native-latent-alignment` 分支；
- Qwen3-32B Native Latent Worker 实现；
- Ridge artifact builder；
- 历史启动脚本；
- 本地日志与 artifact 搜索；
- LatentMAS 官方源码；

重新完成了源码级审计。

最终结论是：

> **过去正式失败的不是 LatentMAS-style Ridge Native Latent，而是 `soft_token_topk_v1` alignment。**
>
> `ridge_realign_v1` 后来已经被实现并接入 runtime，但当前没有找到任何正式物理实验 / quality run 的 surviving evidence。

因此，StateBus Hidden-State 路线当前不应该被判定为失败，而应该被重新定义为：

```text
Native vLLM mechanism        已证明可行
Soft-token representation    已证明质量不足
Ridge representation         已实现，但未完成实证
Cross-agent KV working mem   尚未完成
```

这为后续是否采用 LatentMAS 提供了非常明确的判别路径。

---

# 1. 历史 Source Identity

## 1.1 旧仓库

历史仓库：

```text
qcrs/os1
```

本地旧工作区：

```text
/home/qcrs/statebus/project
```

本地当前工作区当时处于：

```text
contest/recovery-core
```

并存在大量未提交修改，因此本轮历史审计**没有 checkout / reset / switch**，而是通过：

```bash
git show <commit>:<path>
git ls-tree
git diff
git log --all
```

直接读取 Git object。

这保证了：

```text
current dirty worktree
≠
historical source truth
```

---

## 1.2 Native Latent 历史分支

关键历史分支：

```text
feat/native-latent-alignment
```

旧 Native Latent commit：

```text
4bc78120d984f06136152413f11b079ababb43a3
2026-07-22 08:13:24 +0800
v2: checkpoint remediation and native latent handoff
```

后续加入 Ridge 的 commit：

```text
a173cf048894d561b273d366dd40bc6e7c8fc1db
2026-07-22 14:55:17 +0800
chore: checkpoint contest rebuild preparation
```

两者时间关系极其重要：

```text
08:13 Native Latent / soft-token implementation
        ↓
14:55 Ridge implementation added
```

因此旧 L1 失败实验不能被直接解释为 Ridge 失败。

---

# 2. 旧 Native Latent 实际实现了什么

StateBus 旧 Native Latent 不是“保存一个 hidden tensor 的 toy demo”。

它已经实现了一个相对完整的 vLLM-native latent handoff lane。

核心环境：

```text
Model             Qwen3-32B
vLLM              0.9.2
Engine generation V0
Tensor Parallel   1
max_num_seqs      1
prompt_embeds     enabled
```

核心路径：

```text
Retriever / Producer
        ↓
Qwen3-32B vLLM forward
        ↓
capture last hidden
        ↓
alignment
        ↓
continuous latent embedding
        ↓
下一次 execute_model
        ↓
直接替换 inputs_embeds
        ↓
latent recurrence
        ↓
重复 K 次
        ↓
[K, 5120] BF16
        ↓
LatentStateRef
        ↓
Registry / lifecycle
        ↓
Consumer
        ↓
left token embeddings
+
latent vectors
+
right token embeddings
        ↓
prompt_embeds
        ↓
Qwen3-32B consumer forward
```

因此，历史代码已经真实解决：

```text
hidden capture               ✓
latent recurrence            ✓
vLLM request-local KV reuse  ✓
prompt_embeds consumer       ✓
LatentStateRef               ✓
compatibility signature      ✓
one-shot consume             ✓
release                      ✓
forward proof                ✓
```

这点必须和普通：

```text
HF hook → numpy → another HF model
```

区分开。

---

# 3. Producer 端：真正的 Continuous Latent Recurrence

旧 Worker Extension 会在 capture 开始时：

```text
runner.return_hidden_states = True
```

随后 wrapper 每轮执行：

```text
execute_model(...)
    ↓
extract hidden state
    ↓
align hidden
    ↓
active["aligned"].append(...)
    ↓
active["pending"] = aligned
```

下一轮 execute_model 开始前：

```text
model_input.inputs_embeds = pending
```

即：

```text
h_t
 ↓
alignment(h_t)
 ↓
z_t
 ↓
next Transformer step
 ↓
h_t+1
```

这一点非常关键：

> **旧 StateBus 已经实现真正的 continuous latent autoregression，而不是单次 hidden export。**

并且在同一个 producer request 内：

```text
vLLM KV Cache
```

会继续存在。

因此 producer 内部本质上已经是：

```text
prefill once
    ↓
latent decode-like step
    ↓
latent decode-like step
    ↓
...
```

这一机制与今天重新分析的：

- LatentMAS continuous reasoning；
- RecursiveMAS inner latent loop；
- latent-link-vllm in-engine latent rollout；

在 runtime primitive 上是同一类问题。

---

# 4. Consumer 端：真正使用了 `prompt_embeds`

旧 StateBus consumer 并不是：

```text
latent → decode text → tokenize → receiver
```

而是：

```text
left_token_ids
    ↓ embedding()

latent tensor [K,D]

right_token_ids
    ↓ embedding()

concat(left, latent, right)
    ↓
prompt_embeds
    ↓
consumer vLLM request
```

因此它完成了：

```text
continuous representation handoff
```

没有中间 token verbalization。

这也是为什么过去的机制验证可以成立：

```text
capture
recurrence
publish
resolve
consume
forward
release
```

即使最后 quality 很差，**mechanism 本身是成功的**。

---

# 5. 旧正式失败实验到底失败了什么

过去记录中的核心质量结果：

```text
Text / full evidence baseline
C0 ≈ 22 / 24 facts

Native Latent
16 latent steps ≈ 4 / 24 facts

Native Latent
40 latent steps ≈ 8 / 24 facts
```

过去容易把这个结果总结成：

> Hidden State communication 不工作。

这个总结现在需要正式废弃。

因为源码与本地审计已经确认：

# 那两批实验使用的是 `soft_token_topk_v1`

不是 Ridge。

---

# 6. `soft_token_topk_v1` 到底是什么

失败阶段的启动脚本明确：

```bash
STATEBUS_LATENT_ALIGNMENT=soft_token_topk_v1
STATEBUS_LATENT_ALIGNMENT_TOP_K=32
STATEBUS_LATENT_ALIGNMENT_TEMPERATURE=1.0
```

Worker runtime 的实际逻辑：

```python
logits = lm_head(hidden)

values, indices = torch.topk(
    logits,
    k=top_k,
)

weights = torch.softmax(
    values / temperature,
    dim=-1,
)

token_embeds = input_embedding(indices)

aligned = (
    weights.unsqueeze(-1)
    * token_embeds
).sum(dim=1)

aligned *= target_norm / ||aligned||
```

其本质是：

```text
Hidden State
    ↓
LM Head
    ↓
Vocabulary Logits
    ↓
Top-K
    ↓
Softmax
    ↓
Top-K Token Embeddings Weighted Sum
    ↓
Continuous Embedding
```

也就是一种：

```text
soft-token / belief embedding
```

而不是：

```text
direct hidden-space → input-embedding-space realignment
```

从今天的 taxonomy 看，它更接近：

```text
CIPHER / Soft Thinking
```

这一族方法，而不是 LatentMAS Ridge。

---

# 7. 为什么旧 soft-token 方法可能丢信息

路径：

```text
hidden h
   ↓
lm_head
   ↓
vocabulary logits
   ↓
只保留 top-k
   ↓
softmax
   ↓
weighted token embeddings
```

包含两个明显的信息瓶颈。

## 7.1 Hidden → Vocabulary 投影已经发生压缩

最后一层 hidden 可能包含：

```text
semantic state
reasoning state
evidence interaction
context information
```

而 LM Head 的训练目标是：

```text
next-token prediction
```

所以：

```text
LM Head projection
```

并不保证保留所有对 downstream agent 有用的 latent information。

---

## 7.2 Top-K 再次截断

旧实现默认：

```text
top_k = 32
```

这意味着：

```text
151K+ vocab logits
      ↓
仅保留 32 个方向
```

然后再混成：

```text
1 × hidden_size
```

所以它并不是：

```text
hidden-state handoff
```

的无损或近无损实现。

更准确是：

```text
next-token belief manifold
    ↓
soft embedding
```

这可以解释为什么：

```text
16 step → 4/24
40 step → 8/24
```

增加 latent steps 有一定改善，但事实保真度仍然不足。

---

# 8. Ridge 是什么时候出现的

关键事实：

```text
4bc78120...
```

失败实验对应 commit 中：

```text
NO RIDGE FILES
```

不存在：

```text
v2/integrations/vllm_latent/alignment.py

scripts/build_vllm_latent_ridge_adapter.py
```

后续：

```text
a173cf04...
```

才新增：

```text
A scripts/build_vllm_latent_ridge_adapter.py

A v2/integrations/vllm_latent/alignment.py
```

并修改：

```text
worker_extension.py
middleware.py
registry.py
telemetry.py
start_vllm_qwen3_32b_latent.sh
```

因此可以正式冻结：

```text
soft-token formal run        YES
ridge formal run             NO SURVIVING EVIDENCE
```

---

# 9. Ridge implementation 的数学形式

StateBus 后来的 builder 直接从 Qwen3-32B 权重读取：

```text
W_in  = model.embed_tokens.weight
W_out = lm_head.weight
```

计算：

\[
A = W_{out}^{T} W_{out} + \lambda I
\]

\[
B = W_{out}^{T} W_{in}
\]

\[
M = A^{-1} B
\]

即：

\[
M =
(W_{out}^{T} W_{out} + \lambda I)^{-1}
W_{out}^{T}W_{in}
\]

runtime：

\[
z = hM
\]

然后：

\[
z' =
z \cdot
\frac{\mathbb{E}\|E_{in}\|}
{\|z\|}
\]

最终输出：

```text
BF16 latent embedding
```

---

# 10. StateBus Ridge 与 LatentMAS 的关系

LatentMAS 官方源码同样：

```python
input_weight = input_embedding.weight
output_weight = output_embedding.weight

gram = output_weight.T @ output_weight
gram += reg * I

rhs = output_weight.T @ input_weight

realign_matrix = solve(
    gram,
    rhs,
)

aligned = hidden @ realign_matrix
aligned *= target_norm / aligned.norm(...)
```

因此：

```text
StateBus ridge_realign_v1
        ≈
LatentMAS latent_space_realign
```

从数学 family 上看，两者基本一致。

这意味着：

> **StateBus 并不缺 LatentMAS 的 core hidden→embedding realignment 思路。**

实际上它已经被实现过。

真正缺的是：

```text
formal physical quality validation
```

---

# 11. 但二者目前不能认为数值完全等价

存在一个非常关键的参数差异。

StateBus builder 默认：

```text
regularization = 0.01 = 1e-2
```

LatentMAS 官方：

```text
regularization = 1e-5
```

两者相差：

```text
1000×
```

所以不能简单写：

```text
StateBus Ridge = LatentMAS Ridge
```

更准确是：

```text
same formulation family
different regularization regime
```

对于：

```text
hidden_size = 5120
vocab_size ≈ 151K
```

这种高维问题，

\[
\lambda
\]

会直接影响：

```text
conditioning
fit bias
direction preservation
embedding reconstruction
```

因此后续必须把：

```text
λ = 1e-2
```

和：

```text
λ = 1e-5
```

至少做一次 controlled ablation。

---

# 12. Ridge runtime 后来已经相当完整

后来的 `alignment.py` 不只是一个 matrix multiply。

已经实现：

```text
matrix SHA256
metadata SHA256

model revision binding

input embedding digest
output embedding digest

hidden size check

matrix shape check
matrix dtype check

fit residual

embedding-fit RMSE
identity baseline RMSE

fit error ratio

embedding-fit mean cosine
```

runtime configuration 也通过：

```text
alignment_config_digest
```

被冻结。

因此 alignment artifact 本身已经具备比较完整的：

```text
Artifact Truth
```

属性。

---

# 13. Alignment diagnostics 也已经做好

后来的实现准备了：

```text
hidden_norm

aligned_norm

norm_ratio

source_topk_probability_mass

source_topk_conditional_entropy

direct_lm_head_topk_overlap

direct_lm_head_topk_kl
```

这些指标非常适合用于：

```text
soft-token
vs
ridge
```

对比。

尤其：

```text
direct_lm_head_topk_overlap
direct_lm_head_topk_kl
```

可以观察：

> realigned vector 重新经过 LM Head 后，其 local token belief 是否仍接近 source hidden 的输出分布。

这并不能直接证明 downstream semantic fidelity，但至少能作为 representation-level diagnostic。

---

# 14. 本地 artifact 审计结论

本轮进一步扫描：

```text
/home/qcrs/statebus/work
/home/qcrs/statebus/caches
/home/qcrs/statebus/runs
/home/qcrs/statebus/logs
```

结果：

## 14.1 找到的 Ridge 文件

只有代码：

```text
scripts/build_vllm_latent_ridge_adapter.py
alignment.py
tests
planning docs
startup script
```

以及 Python bytecode：

```text
__pycache__/build_vllm_latent_ridge_adapter.cpython-311.pyc
```

---

## 14.2 没有找到

```text
ridge_realign_v1.npy

ridge_realign_v1.json

正式 Ridge run artifact

Ridge service log

ridge_realign_v1 runtime evidence
```

因此当前最严谨的结论是：

> **Ridge implementation existed, but no surviving physical execution evidence has been found.**

不能写：

```text
Ridge 从来没有运行过
```

因为历史 artifact 有可能被清理。

但在工程决策上，应该将其视作：

```text
UNVALIDATED
```

而不是：

```text
FAILED
```

---

# 15. 后续 commit 的启动脚本也证明 Ridge 不是默认路径

即使 Ridge 已经加入：

```text
a173cf04...
```

启动脚本仍默认：

```bash
STATEBUS_LATENT_ALIGNMENT=soft_token_topk_v1
```

要运行 Ridge 必须显式：

```bash
STATEBUS_LATENT_ALIGNMENT=ridge_realign_v1
```

并提供：

```bash
STATEBUS_LATENT_ALIGNMENT_ARTIFACT=<matrix.npy>

STATEBUS_LATENT_ALIGNMENT_METADATA=<metadata.json>
```

否则直接 fail-fast。

所以即使后续有人继续运行：

```text
start_vllm_qwen3_32b_latent.sh
```

只要没有显式环境变量，

仍然还是：

```text
soft_token_topk_v1
```

---

# 16. 设计文档当时也明确把 Ridge 定义为后续项

历史设计文档仍写：

```text
Ridge realignment，后续研究项
```

并要求：

- 离线构建；
- 固定 digest；
- 报告 build time；
- 报告峰值内存；
- 报告 numerical error；
- 与 `soft_token_topk_v1` 独立消融；
- 不允许在 formal case 上搜索参数。

这进一步说明：

> Ridge 代码是后来为了下一阶段验证准备的，而不是旧失败实验的实际方法。

---

# 17. 当前历史状态应如何重新冻结

建议将项目认知从：

```text
Native Latent
→ 做过
→ 效果差
→ 放弃
```

改成：

```text
Native Latent Runtime
→ Mechanism PASS

Soft-Token Alignment
→ Quality FAIL

Ridge Alignment
→ Implementation DONE
→ Formal Validation MISSING

KV Working Memory
→ Not Yet Integrated
```

正式状态表：

| Component | Status | Evidence |
|---|---|---|
| Qwen3-32B hidden capture | PASS | historical runtime |
| vLLM latent recurrence | PASS | historical runtime |
| LatentStateRef | PASS | source |
| prompt_embeds consumer | PASS | historical runtime |
| consume / release | PASS | source + mechanism experiment |
| soft-token alignment | IMPLEMENTED | source |
| soft-token quality | FAIL | 4/24, 8/24 |
| Ridge builder | IMPLEMENTED | source |
| Ridge runtime | IMPLEMENTED | source |
| Ridge physical artifact | NOT FOUND | filesystem audit |
| Ridge formal quality | UNVALIDATED | no surviving evidence |
| Cross-agent KV continuation | NOT IMPLEMENTED | architecture gap |

---

# 18. LatentMAS：到底比旧 StateBus 多了什么

重新读 LatentMAS 后，需要区分三个部分。

## 18.1 Latent continuous reasoning

LatentMAS：

```text
prompt
 ↓
last hidden
 ↓
realignment
 ↓
latent embedding
 ↓
next forward
 ↓
new hidden
 ↓
...
```

这一部分旧 StateBus 已经实现。

---

## 18.2 Ridge realignment

LatentMAS：

```text
hidden
 ↓
ridge hidden→input-embedding
 ↓
latent
```

这一部分 StateBus 后来同样实现。

---

## 18.3 Working-memory continuity

LatentMAS HF 路径还会：

```text
past_key_values
```

从一个 Agent 阶段传到下一个 Agent 阶段。

这才是旧 StateBus 真正没有做的部分。

---

# 19. LatentMAS HF 路径的数据流

LatentMAS：

```text
Agent A prompt
    ↓
HF forward
    ↓
past_kv
+
last hidden
    ↓
K latent steps
    ↓
updated past_kv
    ↓
Agent B prompt
+
previous past_kv
    ↓
K latent steps
    ↓
updated past_kv
    ↓
...
Judge
```

因此：

```text
Agent state
```

不只是：

```text
[K,D] latent vectors
```

而包括：

```text
all-layer KV working memory
```

这使 LatentMAS 有更大的内部状态容量。

---

# 20. 旧 StateBus 跨 Agent 只传了 Representation

旧设计：

```text
Retriever
   ↓
latent recurrence
   ↓
[K,5120]
   ↓
LatentStateRef
   ↓
Summarizer prompt_embeds
```

但：

```text
Retriever vLLM KV
```

没有进入 consumer。

所以：

```text
Representation Handoff    YES

Working Memory Handoff    NO
```

这可能是历史事实丢失的重要原因之一。

---

# 21. 为什么 Working Memory 可能重要

假设 input evidence 有数千 token。

旧方案试图把：

```text
64-layer Transformer computation
+
long evidence context
```

压缩成：

```text
K × 5120
```

比如：

```text
K = 16
```

或：

```text
K = 40
```

即使每个 vector 都是 BF16，

信息容量也远低于：

```text
all-layer KV cache
```

旧实验：

```text
16 steps → 4/24

40 steps → 8/24
```

实际上有一个值得注意的趋势：

```text
更多 latent state
→ quality 提高
```

这说明：

> representation capacity 可能确实是限制因素之一。

但仅凭这个结果还不能证明：

```text
KV 一定能解决问题
```

因此必须先完成 Ridge-only ablation。

---

# 22. LatentMAS 官方 vLLM 路径并不是真正的 vLLM KV Relay

这是本轮另一个必须修正的认识。

LatentMAS 当前 vLLM path：

```text
Second HuggingFace Model
     ↓
latent reasoning
     ↓
HF past_key_values
     ↓
accumulate hidden/input embeddings
     ↓
final embedding sequence
     ↓
vLLM prompt_embeds
     ↓
Judge generation
```

即：

```text
HF
负责 latent working memory

vLLM
只负责最终生成
```

它并没有做到：

```text
vLLM request A KV
    ↓
State / Handle
    ↓
vLLM request B
```

所以如果未来 StateBus 做：

```text
vLLM-native cross-agent working-memory continuation
```

并不是简单照搬 LatentMAS runtime。

更准确是：

```text
LatentMAS semantics
×
StateBus runtime ownership
×
vLLM-native context continuation
```

---

# 23. Explicit KV 的重新定位

StateBus 当前主仓已经实现真实 Explicit KV：

```text
vLLM Paged KV
 ↓
extract
 ↓
EngineLocalKVHandle
 ↓
store
 ↓
consumer
 ↓
inject
 ↓
skip inherited prefill
```

这条路径已经证明：

```text
physical KV capture / restore
```

在 Qwen3-32B 上可行。

而且历史实验中：

```text
consumer computed prefill
```

有大幅下降。

但它当前的数据搬运：

```text
GPU
 ↓ D2H
Host
 ↓ H2D
GPU
```

对于 4K 级 Qwen3-32B KV 可以达到约 GiB 级 payload。

因此它不应该继续作为：

```text
StateBus 又一个独立 feature
```

而应该被重新定位成：

# Engine Context Ownership Primitive

---

# 24. Explicit KV 中真正值得保留的部分

真正有长期价值的是：

```text
EngineLocalKVHandle

Compatibility Contract

model identity

tokenizer identity

engine generation

context digest

consumer binding

TTL

one-shot consume

release

KVForwardProof

vLLM KVConnector seam
```

而不是：

```text
Host-copy implementation
```

本身。

未来如果 LatentMAS working-memory hypothesis 成立，

正确演化是：

```text
EngineLocalKVHandle
    ↓
EngineResidentWorkingMemoryHandle
```

即：

```text
physical KV stays on GPU / BlockPool
StateBus moves authority + handle
```

而不是：

```text
copy 1GB KV between agents
```

---

# 25. 理想的未来 Latent State 分层

如果 Ridge + KV 最终都成立，应明确分成：

## Representation State

```text
LatentThoughtRef
=
[K, hidden_size]
```

作用：

```text
what internal representation is transferred
```

---

## Compute / Working-Memory State

```text
EngineResidentWorkingMemoryHandle
```

作用：

```text
what Transformer working memory is inherited
```

---

这样保持：

```text
Latent Representation
≠
Physical KV
```

而不是重新把两个概念混成：

```text
Hidden State = KV
```

---

# 26. 当前最重要的两个 competing hypotheses

现在问题已经收敛成两个假设。

## Hypothesis A — Alignment Hypothesis

旧实验失败主要因为：

```text
soft_token_topk_v1
```

过度压缩 hidden information。

如果换成 Ridge：

```text
quality 应明显恢复
```

---

## Hypothesis B — Working-Memory Hypothesis

即使 Ridge 正确：

```text
[K,D]
```

仍然不足以替代：

```text
all-layer KV working memory
```

因此：

```text
Ridge-only
```

仍然无法达到 text baseline。

如果 B 成立，才有必要继续：

```text
Ridge + KV continuity
```

---

# 27. 下一步实验：RIDGE-FEASIBILITY-01

## 27.1 目标

只回答：

> **在旧 Qwen3-32B vLLM Native Latent runtime 中，仅替换 Alignment Provider，Ridge 是否显著改善 representation fidelity / downstream quality？**

禁止同时修改：

```text
Agent topology
vLLM version
KV semantics
Prompt structure
StateBus runtime
benchmark definition
```

---

# 28. Frozen Environment

优先复现旧环境：

```text
Model:
Qwen3-32B

vLLM:
0.9.2

Engine:
V0

TP:
1

max_num_seqs:
1

prompt_embeds:
enabled

temperature:
0

seed:
7
```

旧 Native Latent runtime：

```text
feat/native-latent-alignment
```

或者基于：

```text
a173cf048894d561b273d366dd40bc6e7c8fc1db
```

单独建立 clean worktree。

禁止直接在当前：

```text
contest/recovery-core
```

dirty worktree 上做实验。

---

# 29. 第一轮 Variant

只做三个。

| Variant | Alignment | λ |
|---|---|---:|
| H0 | `soft_token_topk_v1` | N/A |
| H1 | `ridge_realign_v1` | `1e-2` |
| H2 | `ridge_realign_v1` | `1e-5` |

H0：

```text
复现历史方法
```

H1：

```text
StateBus old builder default
```

H2：

```text
LatentMAS official regularization regime
```

---

# 30. 为什么不一次扫描很多 λ

第一阶段不要做：

```text
1e-1
1e-2
1e-3
1e-4
1e-5
1e-6
```

因为项目目标不是做：

```text
alignment hyperparameter research
```

只需要回答：

```text
old StateBus setting
vs
LatentMAS setting
```

是否存在明显差异。

如果 H1/H2 差异巨大，再考虑后续。

---

# 31. Latent Steps

第一轮固定：

```text
latent_steps = 16
```

理由：

- 旧正式实验已有 16-step reference；
- 计算成本可控；
- 不把 `latent_steps` 变成第二个 independent variable。

只有 Ridge 明显改善后，

再补：

```text
40-step
```

作为 capacity study。

---

# 32. Case 数量

第一轮不需要 full benchmark。

建议：

```text
2–3 representative L1 cases
```

优先包含：

```text
long-document causal analysis

cross-document evidence synthesis

conditional plan switch
```

即旧 v2/v5/v6 holdout 中典型的复杂 evidence task。

实验数：

```text
3 alignments
×
2~3 cases
=
6~9 runs
```

足够判定方向。

---

# 33. 必须记录的指标

## Quality

```text
required facts passed
required facts total

deficit vs text baseline
```

---

## Representation diagnostics

```text
hidden_norm

aligned_norm

norm_ratio

source_topk_probability_mass

source_topk_conditional_entropy

direct_lm_head_topk_overlap

direct_lm_head_topk_kl
```

---

## Mechanism proof

```text
captured_step_count

recurrence_injection_count

LatentStateRef shape

tensor bytes

tensor digest

consumer request id

consume proof

release status
```

---

## Runtime

```text
producer latency

alignment latency

consumer TTFT

consumer E2E

latent bytes
```

---

# 34. Result Interpretation

## Case A

```text
soft         poor

ridge 1e-2   much better

ridge 1e-5   much better
```

结论：

```text
old failure was primarily alignment-related
```

下一步：

```text
Native Latent + Ridge
```

可以重新成为正式 candidate。

暂时不需要 KV working memory。

---

## Case B

```text
soft         poor

ridge 1e-2   medium

ridge 1e-5   strong
```

结论：

```text
Ridge family works,
but old regularization was over-strong
```

可以明确引用 LatentMAS：

```text
LatentMAS-style realignment parameterization
```

作为方法依据。

---

## Case C

```text
soft ≈ ridge 1e-2 ≈ ridge 1e-5
```

结论：

```text
alignment is not the primary blocker
```

停止调 alignment。

下一步验证：

```text
working-memory continuity hypothesis
```

---

## Case D

```text
ridge < soft
```

结论：

```text
current Retriever→Summarizer task
does not benefit from direct last-layer latent transfer
```

Hidden State lane 应降级。

不要继续投入。

---

# 35. 如果 Ridge 失败，才做下一阶段

下一阶段才是：

# LATENT-WORKING-MEMORY-01

目标：

```text
Agent A
 ↓
latent reasoning
 ↓
LatentThoughtRef
+
Engine-resident KV handle
 ↓
Agent B
```

此时可以复用：

```text
Explicit KV Handle semantics
```

但必须重新设计：

```text
physical KV ownership
```

以避免：

```text
GPU → Host → GPU
```

巨大搬运。

---

# 36. 可能的未来架构

```text
                         StateBus Authority Plane

Planner / Router
      │
      ▼
Approved Agent Edge
      │
      ▼

                    Representation Plane

Agent A Qwen3-32B
      │
      ▼
latent rollout
      │
      ▼
LatentThoughtRef [K,D]
      │
      └──────────────────────────┐
                                 │
                                 ▼
                             Agent B


                       Compute Plane

Agent A KV Blocks
      │
      ▼
EngineResidentWorkingMemoryHandle
      │
      ▼
same-engine continuation
      │
      ▼
Agent B
```

必须保持：

```text
Representation State
≠
Compute State
```

---

# 37. 和 StateBus 现有非文本 State 的关系

未来整体可以明确为：

```text
Non-Text State
│
├── Semantic Selection
│     └── Embedding State
│
├── Decision State
│     └── LogitState / confidence / gate
│
├── Representation Handoff
│     ├── Latent Hidden State
│     └── CIPHER-like Belief Embedding
│
└── Compute Reuse
      ├── APC
      └── Engine Context / KV
```

语义分别是：

```text
Embedding:
看什么

Logit / Decision:
怎么走

Latent:
把什么内部表示传给下游

KV:
哪些 Transformer working memory / computation 不重复
```

这能够解决过去 StateBus feature stacking 的问题。

---

# 38. CIPHER 的位置

旧：

```text
soft_token_topk_v1
```

实际上已经和：

```text
CIPHER
Soft Thinking
```

非常接近。

即：

```text
logits
 ↓
probability
 ↓
weighted input embeddings
```

因此 CIPHER 不适合作为：

```text
Hidden State primary method
```

但它可以成为：

```text
BeliefState / Logit Representation Handoff
```

的理论依据。

也就是说：

```text
same Producer:
logits

       ├── LogitState
       │      ↓
       │   Decision Gate
       │
       └── Belief Embedding
              ↓
           Receiver LLM
```

这是另一条路线，不与 Ridge Hidden-State 混用。

---

# 39. 当前最终技术判断

截至本轮审计，Hidden-State 路线不应该被删除。

但也不能直接宣称：

```text
LatentMAS 可以解决 StateBus
```

正确状态是：

```text
Native vLLM mechanism:
PROVEN

Soft-token representation:
FAILED

Ridge representation:
IMPLEMENTED / UNVALIDATED

Cross-agent KV working memory:
UNVALIDATED / NOT IMPLEMENTED

Production TP/batching:
OUT OF CURRENT SCOPE
```

因此当前风险已经从：

```text
“vLLM hidden state 能不能实现？”
```

下降为：

```text
“哪种 representation 能保留足够的信息？”
```

这是一个显著更好的工程状态。

---

# 40. 当前决策

## 冻结结论

### 允许继续

```text
RIDGE-FEASIBILITY-01
```

---

### 暂时禁止

```text
直接 port LatentMAS full repo

直接实现跨 Agent KV relay

训练 RecursiveLink

替换 Qwen3-32B

引入第二个 HF Qwen3-32B production model

大规模 alignment hyperparameter search

在 dirty contest/recovery-core 上直接实验
```

---

# 41. 下一阶段 Gate

`RIDGE-FEASIBILITY-01` 结束后只能出现两个主要方向：

## PASS

```text
Ridge clearly improves quality
```

则：

```text
Latent Representation Handoff
→ Active Experimental Feature
```

下一步：

```text
vLLM version modernization
StateBus current architecture integration
causal true/mismatch/zero control
```

---

## FAIL

```text
Ridge does not materially improve quality
```

则：

```text
Alignment investigation STOP
```

下一步只允许判断：

```text
KV working-memory continuation
```

是否值得做。

如果时间不足：

```text
Hidden State lane DEFER
```

也完全合理。

---

# 42. 最终一句话

本轮历史审计最重要的结论不是：

> “StateBus 以前已经做过 LatentMAS。”

而是：

> **StateBus 以前已经把 Qwen3-32B 的 vLLM-native latent recurrence、LatentStateRef、prompt-embeds consumer 和生命周期机制跑通；正式失败的是 soft-token projection。LatentMAS-style Ridge 后来实际上已经实现，但没有完成 surviving formal validation。因此当前最优下一步不是重新实现 LatentMAS，而是补做一次严格的 Ridge-only controlled feasibility experiment。**

如果 Ridge 成立，再考虑把现有 Explicit KV 的 handle / lifecycle / proof 能力演进成真正的 engine-resident working-memory continuation。

这条路线同时满足：

```text
理论依据
+
历史代码复用
+
vLLM 真实性
+
Qwen3-32B
+
training-free
+
低额外研究成本
+
StateBus 架构一致性
```

也是当前最值得保留的 Hidden-State 方向。

---

# Appendix A. 关键历史 Commit

```text
Native Latent / soft-token:
4bc78120d984f06136152413f11b079ababb43a3

Ridge implementation added:
a173cf048894d561b273d366dd40bc6e7c8fc1db
```

---

# Appendix B. 关键历史文件

```text
scripts/start_vllm_qwen3_32b_latent.sh

scripts/build_vllm_latent_ridge_adapter.py

v2/integrations/vllm_latent/alignment.py

v2/integrations/vllm_latent/worker_extension.py

v2/integrations/vllm_latent/middleware.py

v2/integrations/vllm_latent/registry.py

v2/runtime/latent_handoff.py

v2/benchmark/native_latent_experiment.py

docs/planning/vllm_native_latent_handoff_implementation_20260720.md
```

---

# Appendix C. 外部参考

## LatentMAS

Paper:

```text
Latent Collaboration in Multi-Agent Systems
arXiv: 2511.20639
ICML 2026 Spotlight
```

Repository:

```text
https://github.com/Gen-Verse/LatentMAS
```

关键参考：

```text
models.py
methods/latent_mas.py
```

---

## CIPHER

```text
Let Models Speak Ciphers:
Multiagent Debate through Embeddings

ICLR 2024
```

适合作为：

```text
Logit / Belief Representation
```

参考，而不是当前 Hidden-State Ridge 主线。

---

# Appendix D. 当前唯一 Next Allowed Action

```text
RIDGE-FEASIBILITY-01
```

内容：

```text
Qwen3-32B
vLLM Native Latent
same runtime
same cases
same steps

soft_token_topk_v1
vs
ridge_realign_v1 λ=1e-2
vs
ridge_realign_v1 λ=1e-5
```

在得到这个实验结果前：

```text
禁止进入 full LatentMAS / KV relay implementation。
```
