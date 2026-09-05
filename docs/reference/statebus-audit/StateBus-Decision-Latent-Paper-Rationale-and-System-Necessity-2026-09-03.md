# StateBus DecisionState 与 Latent Hidden 的论文依据、必要性与系统设计论证
## 从 Uncertainty Quantification、Latent Communication、Activation Communication 与 KV Semantic Relay 出发

> **项目**：StateBus / `qcrs/os`  
> **日期**：2026-09-03  
> **目标**：回答两个核心问题：
>
> 1. **为什么 StateBus 需要 DecisionState？它不是“又多传一种 Logit”吗？**
> 2. **为什么 StateBus 应该优先实现 Hidden/Latent，而不是继续把 KV 扩成 Agent 语义通信？**
>
> 本文不把论文简单列成 Related Work，而是逐篇回答：
>
> - 论文解决了什么问题；
> - 它证明了什么；
> - 其公开源码用了什么机制；
> - 哪一部分适合 StateBus；
> - 哪一部分不适合直接照搬；
> - 最终怎样形成 StateBus 自己的系统设计。
>
> **核心结论**：
>
> ```text
> Embedding
>     = Selection State
>       “让模型看什么”
>
> Latent Hidden
>     = Representation Handoff State
>       “上游 Agent 新形成的内部表示如何直接传给下游”
>
> Decision Logit
>     = Runtime Decision State
>       “下游模型现在是否足够确信，Runtime 应该怎么走”
>
> APC / KV
>     = Compute Reuse State
>       “哪些 Transformer Prefill 已经算过，不需要再算”
> ```
>
> 对 StateBus 来说，真正推荐的非文本主线是：
>
> # `Embedding Selection → Latent Handoff → Decision → Feedback`
>
> KV/APC 则独立作为：
>
> # `Compute Memory / Inference Reuse`
>
> 这样语义通信与计算复用不会混在一起。

---

# 1. 先回答“必要性”：比赛要求、系统需求、研究创新不是一回事

讨论 Decision / Hidden 是否“有必要”，必须分三层。

---

## 1.1 赛题硬要求层

赛题要求：

```text
至少实现一种非文本中间状态传递机制
```

并明确列举：

```text
embedding
语义向量
隐藏状态特征
其他中间表示
```

因此严格从“能否满足题面”看：

```text
当前 Embedding
```

已经足以满足最低要求。

所以：

```text
DecisionState
不是赛题硬要求

Latent Hidden
也不是赛题硬要求

KV
更不是赛题硬要求
```

这点必须诚实。

---

## 1.2 为什么还要做 Hidden？

因为赛题的“状态传递创新”单独占分，而且题目原始动机非常明确：

> Agent 在协作中反复经历“内部状态 → 文本 → 内部状态”，存在额外 token、时延和潜在语义损失。

当前 Embedding 做到的是：

```text
vector
→ 选 Evidence
→ hydrate Evidence
→ 仍然把文本交给 LLM
```

它证明：

```text
非文本状态真正被传输和消费
```

但并没有直接解决：

```text
Agent A 已经形成的新内部 representation
为什么还必须先生成成文本
再让 Agent B tokenize + prefill？
```

Hidden/Latent 才直接打到这个问题。

所以：

> **Embedding 已经满足“有非文本状态”，Hidden 用来提升“非文本状态本身的技术含量和与题目动机的贴合度”。**

---

## 1.3 为什么还要做 Decision？

Decision 的必要性不是：

```text
赛题要求 Logit
```

题目没有要求。

它的必要性来自 StateBus 自己的架构目标：

```text
Agent proposes
Runtime authorizes
```

如果模型给出：

```text
USE_CODEACT
```

或者：

```text
FINALIZE
```

仅凭采样出的一个 token/JSON 字段立刻执行，会丢掉一个关键事实：

> **模型可能只是“勉强选择 A”，并不是真的确信 A。**

尤其 CodeAct/tool execution 可能产生：

```text
文件修改
外部操作
执行代码
不可逆副作用
```

所以：

```text
Model Choice
≠
Runtime Authorization
```

DecisionState 的意义是：

> **把模型的 bounded belief/uncertainty 转换成 Runtime Policy 的显式输入。**

这使 StateBus 不只是：

```text
LLM 输出一个 action
Runtime照着执行
```

而变成：

```text
LLM proposes action + confidence structure
Runtime依据 authority / risk / uncertainty
决定 ACCEPT / RETRY / EXPAND / REPLAN
```

这与 StateBus 的核心理念高度一致。

---

# 2. 论文地图：我们真正借鉴哪几条研究线

建议把相关工作分成三组。

---

## 2.1 Decision / Uncertainty 线

### A. Uncertainty Quantification for LLM Function-Calling — 2026

Paper：

https://arxiv.org/abs/2604.22985

核心问题：

```text
LLM 要调用 function/tool
但怎样知道这次调用是否可靠？
```

关键发现：

- Function-Calling 是高风险场景，错误调用可能产生不可逆后果；
- 多采样的 Semantic Entropy 在 function-calling 场景并没有显示出相对简单 single-sample UQ 的稳定优势；
- single-sample logit-based UQ 如果只观察真正有语义意义的 token，效果会更好；
- meaningful tokens 包括 function name、argument names、argument values 等。

这对 StateBus 的直接意义：

```text
不要拿整个自然语言输出做 entropy

而是：
Runtime先定义有限合法动作
→ 用单 token alias / bounded structured choice
→ 只读取这些决策 token 的概率
```

当前 StateBus 的：

```text
A/B/C alias
CandidateSurface
candidate probabilities
other_mass
```

其实非常符合这个研究结论。

---

### B. Semantic Entropy — Nature 2024

Paper：

https://www.nature.com/articles/s41586-024-07421-0

核心问题：

```text
自由文本答案的 token entropy
不能代表“意义上的不确定性”
```

因为：

```text
Paris
The answer is Paris
France's capital is Paris
```

token 不同但意义相同。

论文通过：

```text
多次生成
→ 语义聚类
→ meaning-level entropy
```

检测 confabulation。

对 StateBus 的启发：

```text
Free-form answer uncertainty
可以未来考虑 Semantic Entropy
```

但是对当前：

```text
A = DSL
B = CodeAct
C = Retrieve More
```

这种 bounded decision，没有必要第一版就多采样聚类。

所以 StateBus 选择：

```text
Decision:
single-sample exact candidate probability

Free-form answer reliability:
future semantic entropy
```

更经济。

---

### C. CIPHER — ICLR 2024

Paper：

https://proceedings.iclr.cc/paper_files/paper/2024/hash/e444859b2a22df6b56af9381ad1e9480-Abstract-Conference.html

核心观点：

```text
从 vocabulary distribution
采样成一个 token
会丢掉模型本来具有的 belief information
```

CIPHER 不直接采样 token，而是：

```text
vocabulary probabilities
×
token embeddings
→ expected embedding
```

让 Agent 通过连续 embedding 交流。

论文报告相较自然语言 debate 在其五类任务上提升约：

```text
0.5% ~ 5.0%
```

对 StateBus 的启发不是照搬 CIPHER，而是：

> **一个 sampled action token 并不能完整表示模型对动作的 belief。**

所以：

```text
DecisionState
```

保留：

```text
完整 bounded candidate distribution
+
other_mass
```

比只保留：

```text
selected_action
```

更有信息。

---

# 3. Latent / Hidden Communication 研究线

---

## 3.1 StateBridge — 2026：最适合 StateBus v1 的方法

Paper：

https://arxiv.org/abs/2608.13317

Repo：

https://github.com/YanwenPneg/StateBridge

StateBridge 的问题定义非常直接：

```text
Text communication
需要把 continuous hidden state
离散成 token

可能导致：
信息丢失
token generation latency
```

它希望：

```text
Sender hidden
→ Receiver continuous input
```

但有一个关键困难：

```text
Sender final hidden space
≠
Receiver input embedding space
```

所以它提出 training-free alignment。

---

## 3.2 StateBridge 的核心算法

源码 `methods/state_bridge.py` 中真正实现：

```text
HiddenStateCapture
      ↓
last transformer layer forward hook
      ↓
每次 generation forward
只保存最后 position hidden
      ↓
[batch, generated_steps, hidden_dim]
```

然后 `_align_hidden_sequence()`：

```text
1. Center H / E

2. Regularized covariance

3. Whitening

4. Orthogonal Procrustes
   U Σ V^T

5. Map back to receiver embedding statistics

6. Norm calibration

7. Vocabulary anchoring / snapping
```

最后 `_generate_with_prefix()`：

```text
normal prompt embeddings
+
aligned hidden prefix
+
attention mask
```

调用：

```python
generate(inputs_embeds=...)
```

。

这就是 StateBus 最值得借的完整三段：

```text
Capture
→ Align
→ Inject
```

---

## 3.3 为什么 StateBridge 特别适合 StateBus

StateBus 当前部署假设：

```text
一个 Qwen3 vLLM
多个逻辑 Agent
```

也就是说：

```text
Planner
Executor
Summarizer
Verifier
```

本质共享同一模型权重。

因此：

```text
Producer Model
==
Consumer Model
```

StateBridge 最难的异构模型空间对齐问题被大幅简化。

同时它：

```text
training-free
```

不需要：

```text
专门训练 projector
重新训练模型
收集额外 dataset
```

这对比赛型工程项目非常重要。

---

## 3.4 StateBridge 的局限也必须写清楚

StateBridge 并不是：

```text
Sender 完全不生成 token
```

官方源码仍运行：

```python
model.generate(...)
```

再从 generation forward 中捕获 hidden。

所以真正节省的是：

```text
Agent A → Agent B
必须依赖自然语言文本作为唯一 handoff 介质
```

而不是：

```text
Producer autoregressive generation 完全消失
```

因此 StateBus 不应夸大成：

> “Latent eliminates all intermediate generation.”

准确 claim：

> **Latent reduces the need to serialize the sender's internal representation exclusively through natural-language handoff.**

---

# 4. LatentMAS — ICML 2026 Spotlight：证明方向价值，但不适合作为 StateBus v1

Paper：

https://arxiv.org/abs/2511.20639

Repo：

https://github.com/Gen-Verse/LatentMAS

截至 2026-09-03，官方 GitHub 当前约：

```text
1105 stars
169 forks
```

其论文报告：

```text
最高 +14.6% accuracy
输出 token 减少约 70.8%~83.7%
E2E 约 4×~4.3× speedup
```

覆盖 9 个数学、科学、代码等 benchmark。

这对 StateBus 很重要，因为它给出了一个更强的总体信号：

> **Continuous latent collaboration 不只是一个小众 embedding trick，而是一条已经出现较强 benchmark 和社区验证的 MAS 路线。**

---

# 5. LatentMAS 与 StateBridge 有什么不同

LatentMAS 更激进。

其公开代码中 `generate_latent_batch()` 会使用：

```text
inputs_embeds
+
past_key_values
```

做 autoregressive latent rollout。

因此它的系统更像：

```text
Agent A
→ latent step
→ past KV working memory
→ Agent B
→ latent step
→ shared past KV
→ ...
```

这实际上把：

```text
Hidden Communication
+
Latent Reasoning
+
KV Working Memory
```

绑在一起。

---

## 5.1 为什么 StateBus 不直接复制 LatentMAS

因为当前我们首先需要回答的是：

```text
Agent-to-Agent Hidden Handoff
到底是否有真实价值？
```

如果第一版同时加入：

```text
past KV continuation
latent autoregressive rollout
multi-agent latent chain
```

一旦结果变好，无法判断收益来自：

```text
Hidden
KV reuse
更长 internal compute
还是其他因素
```

而且对 vLLM 的：

```text
position
KV layout
scheduler
cache lifetime
```

耦合更深。

所以：

```text
StateBridge
= v1 isolated semantic handoff

LatentMAS
= Future v2 latent working memory
```

是更适合工程验证的顺序。

---

# 6. Communicating Activations — ICML 2025：证明 Hidden/Activation 可以真的替代文本通信

Paper：

https://proceedings.mlr.press/v267/ramesh25a.html

这项工作比 StateBridge 更底层：

```text
Agent B forward 到中间 Layer k
     ↓
暂停
     ↓
把 Agent A activation
和 B activation 融合
     ↓
继续 Layer k+1...
```

论文报告在其任务上最高：

```text
约 +27% performance
并使用不到 1/4 的 compute
```

它给 StateBus 的价值主要是理论/实证支撑：

> **LLM 内部 activation 本身可以成为 Agent communication medium，不必天然先变成文本。**

---

## 6.1 为什么我们不直接做 Communicating Activations

因为它要求：

```text
mid-forward pause
指定 layer injection
activation fusion
继续后半段 forward
```

这对 vLLM serving hot path 入侵很深。

相比之下：

```text
StateBridge
→ input boundary injection
```

可以利用：

```text
prompt embeddings
```

走更干净的 serving interface。

所以：

```text
Communicating Activations
= 证明方向

StateBridge
= 当前实现方法
```

。

---

# 7. KV Semantic Communication 研究线

讨论 Hidden 时必须认真对比 KV，因为 KV 也能携带上下文和深层信息。

但：

> **KV 能做 semantic communication，不代表 StateBus 当前应该优先使用 KV 做 semantic communication。**

---

# 8. C2C — ICLR 2026：KV 确实可以成为语义通信介质

Paper：

https://proceedings.iclr.cc/paper_files/paper/2026/hash/474ada926b331d78f06d95e8913111cc-Abstract-Conference.html

Repo：

https://github.com/thu-nics/C2C

截至 2026-09-03，官方 Repo 当前约：

```text
435 stars
57 forks
```

C2C 的核心：

```text
Source Model KV
      ↓
learned projector
      ↓
semantic transformation
      ↓
fusion
      ↓
Target Model KV
```

并使用 learnable gating 决定哪些 target layers 应消费 source cache。

论文报告相较 text communication：

```text
约 +3.1%~5.4% accuracy
平均约 2.5× latency speedup
```

。

---

# 9. C2C 为什么没有成为 StateBus v1

它真正解决的是非常难的：

```text
不同模型
不同 KV space
之间 semantic transfer
```

所以需要：

```text
trained projector
fusion
layer gating
```

。

而 StateBus 当前：

```text
一个模型
多个逻辑 Agent
```

并不需要为 heterogeneous model communication 付这个成本。

更重要：

```text
C2C 的 semantic message
和 serving KV cache
强耦合
```

。

而我们已经希望：

```text
APC/KV
负责 compute reuse

LatentState
负责 semantic handoff
```

如果现在再用 KV 做 semantic message：

```text
职责重新混在一起
```

。

---

# 10. KVCOMM — 2025：它主要解决的是 Cross-Context Prefill Reuse

Paper：

https://arxiv.org/abs/2510.12872

KVCOMM 的场景：

```text
Agent A:
Prefix A + Shared X

Agent B:
Prefix B + Shared X
```

虽然：

```text
Shared X 文本相同
```

但：

```text
KV(X | Prefix A)
≠
KV(X | Prefix B)
```

普通 prefix cache 无法直接复用。

KVCOMM：

```text
维护 anchor pool
↓
估计 context-induced KV offset
↓
修正 reused KV
```

论文报告：

```text
>70% KV reuse
特定 5-agent workload
TTFT ~430 ms → ~55 ms
```

。

---

## 10.1 KVCOMM 对 StateBus 的意义

它说明：

> **Agent-specific prefix divergence 是 KV reuse 的真实问题。**

但是 StateBus 当前已经有一个更便宜的方法：

```text
Canonical Shared Prefix
→ Role-specific suffix 后置
```

即主动把：

```text
Shared X
```

移动到 exact prefix。

因此在当前系统：

```text
先做 Prompt Layout
+
APC exact reuse
```

比：

```text
anchor correction
cross-context KV transform
```

更稳。

KVCOMM 应该是：

```text
Prompt layout 无法解决时的 Future
```

。

---

# 11. 一篇非常关键的反面/审计论文：When Does Latent Communication Pay?

Paper：

https://arxiv.org/abs/2608.04893

这篇 2026 工作非常重要，因为它没有只看：

```text
KV relay 后 accuracy 提升多少
```

而是问：

> **模型是真的在使用“当前样本 Sender 的 latent information”，还是只要有一块 latent/KV tensor 就会改变行为？**

它使用：

```text
matched relay

mismatched-example relay

zero relay

moment-matched random relay
```

进行 causal audit。

其中一个重要观察：

```text
某些场景 zero relay 会明显损害结果
但 mismatched relay 与 matched 差距却很小
```

说明：

```text
“KV 有效果”
≠
“当前 Sender 的 example-specific 信息被成功传递”
```

。

---

## 11.1 这篇论文直接改变 StateBus 的实验设计

我们不能只做：

```text
Text vs Latent
```

然后看到：

```text
Latent +3%
```

就声称：

```text
Agent 内部语义成功传递
```

必须增加：

```text
MATCHED_LATENT

MISMATCHED_LATENT

ZERO_LATENT

MOMENT_MATCHED_RANDOM
```

。

只有：

```text
Matched
显著优于
Mismatched / Zero / Random
```

才能较强地证明：

> **Receiver 真正在使用当前 Producer 的 sample-specific neural representation。**

这应该成为 StateBus Latent 的强制 Go/No-Go Gate。

---

# 12. Hidden/KV 的安全研究：When Latent Agents Lie

Paper：

https://arxiv.org/abs/2606.28958

该工作研究：

```text
visible text 看起来正常
但传递的 KV latent payload 被篡改
```

的问题。

论文展示：

```text
只检查 visible commitment
无法发现 hidden payload corruption
```

并实现 HMAC-SHA256 manifest 绑定：

```text
specialist
session
model
visible commitment
tensor metadata
payload digest
```

其记录中：

```text
774 个 honest replay 全部接受
295 个 tampered payload 全部拒绝
```

。

---

## 12.1 为什么它对 StateBus 很重要

StateBus 本来就强调：

```text
Ref
identity
hash
lease
provenance
authorization
receipt
```

因此 Latent 不是：

```text
“模型内部 tensor，所以可以默认信任”
```

而应该是：

# Security-sensitive Runtime Object

所以 `LatentStateRef` 必须绑定：

```text
model fingerprint
producer step
consumer role
shape / dtype
blob hash
contract hash
visible commitment
lease
```

。

这反而是 StateBus 相较单纯复现 latent论文非常有系统差异化的地方。

---

# 13. 为什么 DecisionState 对 StateBus 特别必要

现在回到 Decision。

当前 `qcrs/os` 已经不是一个概念 Demo。

`statebus/state/logit_state.py` 已经有：

```text
LogitStateContract
CandidateSurfaceV2
selected alias
selected candidate
producer PID
lease
blob hash
float32 payload
SHM
```

Payload 大小严格：

```text
(candidate_count + 1) × 4 bytes
```

最后一项就是：

```text
other_mass
```

。

Consumer 会验证：

```text
lease
state_id
blob hash
payload size
probability range
sum == 1
```

再计算：

```text
selected_probability
top1
top_margin
entropy
other_mass
```

。

说明我们已经具有：

# 一个真实的数值 Decision-State transport substrate。

---

# 14. 当前 Decision 最大的问题不是“没有 Logit”，而是 Policy 太简单

当前：

```text
ACCEPT
if:
selected == top1
AND
margin >= threshold

else:
RETRY
```

Runtime mode 主要：

```text
OFF
TELEMETRY
RETRY_ONCE
```

。

这证明了：

```text
State 能被跨 PID 真正消费
并改变执行
```

但它仍然像：

```text
实验 Gate
```

，而不是：

```text
Adaptive Runtime Decision Policy
```

。

---

# 15. 为什么只用 top margin 不够

例如：

```text
DSL       0.25
CodeAct   0.10
other     0.65
```

：

```text
margin = 0.15
```

当前 margin-based Gate 可能认为：

```text
DSL 足够领先
```

但真正的问题是：

```text
合法候选总概率只有 0.35
```

这很可能表示：

```text
当前 candidate surface
并没有覆盖模型认为真正合理的下一步
```

此时：

```text
RETRY DSL/CodeAct
```

未必正确。

更合理：

```text
EXPAND_EVIDENCE
或者
REPLAN
```

。

---

# 16. DecisionState v2 应该显式保留四个指标

定义：

\[
p_s = P(selected)
\]

\[
margin = p_1-p_2
\]

\[
candidate\_mass = \sum_i p_i = 1-p_{other}
\]

\[
H = -\sum p_i\log p_i
\]

它们分别回答：

```text
selected_probability
→ 我有多相信“被选中的动作”？

margin
→ 它比第二候选领先多少？

candidate_mass
→ Runtime 给出的候选动作集合本身是否覆盖了模型 belief？

entropy
→ 整个 decision surface 是否分散？
```

。

---

# 17. DecisionState 为什么和 Semantic Entropy 不矛盾

因为场景不同。

StateBus：

```text
Runtime先定义：
A/B/C
```

本质是：

```text
finite action space
```

Function-Calling UQ 的结果支持：

```text
single-sample meaningful-token logits
```

作为高性价比第一方案。

Semantic Entropy：

```text
适合自由文本意义空间
```

所以可以未来用于：

```text
Final Answer Reliability
```

而不是替换：

```text
Tool/Action DecisionState
```

。

---

# 18. DecisionState 对整个三状态闭环的价值

最终：

```text
Embedding
→ 选 Evidence

Latent
→ Agent A 把内部 representation 给 Agent B

Decision
→ Agent B 是否认为当前信息足够？
```

如果：

```text
Decision = EXPAND_EVIDENCE
```

：

```text
Decision
→ RetrievalFeedback
→ Embedding
→ 新 Evidence
```

如果：

```text
Decision = REPLAN
```

：

```text
Decision
→ Runtime
→ Planner
```

所以 Decision 让：

```text
非文本状态
```

不只是：

```text
被传输然后结束
```

而成为：

# Runtime Feedback Loop

---

# 19. 为什么 Latent 对 StateBus 不是“为了跟论文”

StateBus 当前已有：

```text
Structured Protocol
Embedding State
Memory
APC
Explicit KV
CodeAct
Adaptive Runtime
```

但其中非文本语义状态最强的一条仍然是：

```text
Embedding
→ semantic selection
```

这会产生一个项目叙事短板：

```text
Agent 内部新产生的 reasoning representation
仍然主要通过文本输出给下游
```

Hidden 正好补这个缺口。

---

# 20. StateBus 与普通 LatentMAS 的区别应该是什么

不能把项目写成：

```text
“我们复现 StateBridge”
```

真正应该写：

> **StateBridge 提供 Neural Alignment Provider；StateBus 提供 Latent State Runtime。**

区别：

StateBridge 主要解决：

```text
Hidden Space
→ Input Embedding Space
```

StateBus 解决：

```text
谁可以发布？

哪个 Agent 可以消费？

这个 Tensor 属于哪个 Step？

模型是否兼容？

Payload 是否被篡改？

生命周期多长？

Consumer 是否真的用了？

失败怎么 fallback？

它与 Artifact / Evidence 的 trust boundary 是什么？
```

这才是 StateBus 自己的系统工作。

---

# 21. StateBridge repo 很新，为什么仍然值得借？

截至 2026-09-03，StateBridge GitHub 只有约：

```text
4 stars
```

所以不能拿：

```text
“这个仓库很火”
```

作为可信度来源。

我们的理由应该是：

```text
论文方法本身
+
源码结构简单明确
+
和 homogeneous one-model StateBus 高度匹配
+
可以被 LatentMAS / activation communication 等独立研究方向交叉支撑
```

。

StateBridge 的价值是：

# 工程适配度

而不是：

# 社区规模。

---

# 22. LatentMAS 为什么是重要的第二支撑

LatentMAS GitHub 当前约：

```text
1105 stars
```

且是 ICML 2026 Spotlight。

它说明：

```text
latent multi-agent collaboration
```

已经不是只有一个新 paper 在做。

同时它的结果给出了：

```text
质量
token
E2E
```

多维收益。

因此我们可以：

```text
StateBridge
证明 v1 方法可落地

LatentMAS
证明更广的 latent collaboration 方向有强实证/社区信号
```

。

---

# 23. Hidden 相较 KV Semantic Relay 的第一优势：职责更清楚

当前 StateBus 已有：

```text
APC
```

负责：

```text
exact shared prefix compute reuse
```

如果再让 KV 做：

```text
semantic handoff
```

KV 会同时承担：

```text
Compute Cache
+
Semantic Message
```

导致：

```text
状态兼容
实验归因
lifecycle
prompt position
cache policy
```

全部混在一起。

Hidden 方案：

```text
LatentState
= semantic handoff

APC/KV
= compute reuse
```

两层职责非常清楚。

---

# 24. 第二优势：Hidden payload 更轻

例如第一版：

```text
K=64
H=4096
FP16
```

：

```text
64 × 4096 × 2 bytes
≈ 512 KiB
```

而完整 KV 包含：

```text
所有 Transformer layers
×
K + V
×
历史 positions
```

实际通常大一个甚至多个数量级。

当前 StateBus Explicit KV 的已有专项中：

```text
4k prefix handle
约 1 GiB
```

这正说明：

> 对“Agent message”而言，full KV 是非常重的介质。

---

# 25. 第三优势：Hidden 的 Consumer boundary 更干净

StateBridge：

```text
Aligned Latent
→ Consumer input-embedding boundary
→ Consumer Layer 1
```

Consumer 自己重新形成：

```text
自己的 per-layer K/V
```

。

而 semantic KV relay 直接进入：

```text
Consumer 每一层 Attention cache
```

必须处理：

```text
layer count
KV heads
head dimension
position / RoPE
cache layout
backend format
model compatibility
```

工程耦合明显更高。

---

# 26. 第四优势：One-vLLM topology 让 Hidden 更合适

当前：

```text
One Qwen3
Many Logical Agents
```

公共上下文：

```text
APC
```

已经可以直接共享 KV。

所以当前真正缺的不是：

```text
更多公共 prefix KV sharing
```

而是：

```text
Executor 新形成的 internal representation
怎么给 Summarizer
```

这正是 Hidden。

---

# 27. 第五优势：Hidden 更适合做独立 causal experiment

Latent：

```text
Matched
Mismatched
Zero
Random
```

可以直接替换 `[K,H]` tensor。

而 KV semantic relay 经常同时改变：

```text
semantic context
prefill compute
position state
cache state
```

导致实验 attribution 更困难。

对比赛实验来说，Hidden 更容易讲清：

```text
到底是信息有效
还是只是缓存有效
```

。

---

# 28. KV Semantic Communication 仍然不是错误方向

必须避免另一个极端：

```text
KV semantic communication 没价值
```

不对。

C2C 已证明：

```text
Source KV
可以经过学习变换
成为跨模型 semantic communication medium
```

LatentMAS 也展示：

```text
past KV
可以成为 latent working memory
```

KVCOMM 展示：

```text
cross-context KV reuse
```

可以显著降低 TTFT。

所以：

```text
KV semantic communication
是成立的研究方向
```

。

只是：

> **它不是当前 StateBus 最优的第一实现。**

---

# 29. 什么时候 StateBus 再考虑 Semantic KV？

出现：

```text
Latent Handoff 已验证成功
```

之后，如果进一步希望：

```text
连 Consumer 对 latent positions 的 Transformer Prefill
也不要重新计算
```

就可以问：

```text
Hidden Handoff
vs
KV Working Memory
```

这时研究：

```text
LatentMAS
C2C
KV relay
```

才是自然升级。

---

# 30. StateBus 推荐的最终研究层级

```text
Level 1
Embedding
Semantic Selection

Level 2
DecisionState
Runtime Uncertainty Control

Level 3
LatentState
Hidden Representation Handoff

Level 4
APC
Shared Compute Reuse

Level 5 Future
Semantic KV / Latent Working Memory
```

但注意：

```text
Level
不代表必须按开发顺序全部实现
```

。

---

# 31. 论文 → StateBus 映射表

| 论文/项目 | 论文解决什么 | StateBus 借什么 | 当前优先级 |
|---|---|---|---:|
| Function-Calling UQ 2026 | tool call uncertainty | meaningful-token single-sample UQ | **P0 Decision** |
| Semantic Entropy 2024 | free-form meaning uncertainty | future answer-level confidence | P2 |
| CIPHER ICLR'24 | sampling loses vocabulary belief | retain bounded probability distribution | P1 |
| StateBridge 2026 | final hidden → input embedding alignment | **Capture/Align/Inject v1** | **P0 Latent** |
| LatentMAS ICML'26 | full latent MAS collaboration | direction validation + future KV memory | P1 reference |
| Communicating Activations ICML'25 | mid-layer activation communication | prove activation communication value | P2 reference |
| C2C ICLR'26 | semantic KV across models | future heterogeneous KV | P3 |
| KVCOMM 2025 | cross-context KV reuse | future non-prefix compute reuse | P3 |
| Causal Audit 2026 | test if latent pairing really matters | **Matched/Mismatched/Zero/Random** | **P0 experiment** |
| When Latent Agents Lie 2026 | latent/KV integrity | **commitment + model/session binding** | **P0 contract** |

---

# 32. StateBus DecisionState v2 推荐设计

当前保留：

```text
CandidateSurfaceV2

selected candidate

candidate probabilities

other_mass

SHM actual-use path
```

新增：

```text
DecisionSurface
DecisionCalibrationProfile
DecisionPolicy
DecisionReceipt
```

。

---

# 33. DecisionPolicy 第一版

动作：

```text
ACCEPT

RETRY_SAME

EXPAND_EVIDENCE

REPLAN

FAIL_CLOSED
```

。

输入：

```text
selected_probability

top_margin

candidate_mass

entropy

risk class

budget

authority
```

。

---

# 34. Decision 与 Authority 的硬边界

无论：

```text
p(Action)=0.99
```

如果：

```text
CapabilityGrant
不存在
```

：

```text
不能执行。
```

所以：

```text
DecisionState
= uncertainty/belief

CapabilityGrant
= authority
```

。

这正是 StateBus 与“模型自己决定所有事情”的 Agent framework 的重要差异。

---

# 35. StateBus Latent v1 推荐设计

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
StateBus StateStore
      ↓
LatentStateRef
      ↓
Consumer resolve
      ↓
prompt_embeds / input boundary
      ↓
Consumer vLLM
      ↓
LatentConsumptionReceipt
```

。

---

# 36. 为什么 StateBus 发布 Aligned Latent，而不是 Raw Hidden

因为：

```text
Raw Hidden
只是 Producer internal representation
```

。

Consumer 真正需要：

```text
Receiver-compatible representation
```

。

因此 alignment 应在：

```text
publish contract
```

之前完成。

这样：

```text
LatentStateRef
```

可以明确写：

```text
representation_type =
aligned_hidden_prefix
```

。

---

# 37. LatentState 必须绑定什么

至少：

```text
state_id

producer step / attempt

producer role

allowed consumer roles

producer model fingerprint

receiver model fingerprint

tokenizer fingerprint

source layer / hook semantics

prefix length

hidden dimension

dtype

alignment method/version

alignment config hash

blob hash

contract hash

visible commitment hash

lease
```

。

---

# 38. 为什么 Artifact 仍然要保留

推荐：

```text
Executor
  ├─ ExecutionArtifactRef
  └─ LatentStateRef
          ↓
      Summarizer
```

而不是：

```text
Executor
→ 只发 Latent
→ Summarizer
```

。

因为：

```text
Artifact
= authoritative / inspectable / provenance-bearing

Latent
= advisory / neural / opaque
```

。

这能避免为了“非文本”牺牲 StateBus 已经很强的：

```text
auditability
quality gate
evidence lineage
```

。

---

# 39. Hidden 的第一正式场景为什么选 Executor → Summarizer

因为：

```text
Executor
```

有大量：

```text
Evidence
Tool Result
Analysis
```

形成较丰富 internal representation。

Summarizer 又天然需要：

```text
理解上游结果
```

同时已经有：

```text
ExecutionArtifact
```

作为 fallback / truth channel。

所以：

```text
Latent failure
```

不会导致整个 correctness contract 崩掉。

这比：

```text
Planner → Runtime
```

或者：

```text
Latent-only Tool Arguments
```

安全得多。

---

# 40. Latent 的必须实验

最少：

```text
TEXT_HANDOFF

MATCHED_LATENT

MISMATCHED_LATENT

ZERO_LATENT

MOMENT_MATCHED_RANDOM
```

指标：

```text
accuracy / pass@1

visible inter-agent output tokens

latent positions

latent bytes

capture latency

alignment latency

publish / consume latency

receiver TTFT

E2E

GPU memory

fallback rate
```

。

---

# 41. 必须选择真正“需要 Sender 信息”的任务

如果 Summarizer：

```text
已经看到了所有 Evidence
```

那么即使：

```text
Latent 对错
```

它也可能完成任务。

这种 benchmark 不能证明 semantic handoff。

专项实验需要：

```text
Sender 有额外/private task information
Receiver 不能完全独立重建
```

但仍保留：

```text
visible commitment / artifact
```

避免 latent 成为不可审计 Gold channel。

---

# 42. 为什么 Decision 和 Latent 应该协同，而不是各自做 demo

最终：

```text
Latent
→ 改变 Consumer internal hidden

Consumer hidden
→ LM Head
→ Decision probability
```

Decision 反映：

```text
Consumer 在真正消费 Latent 后
是否已经足够确信
```

如果不确定：

```text
EXPAND_EVIDENCE
```

再回到：

```text
Embedding Retrieval
```

因此：

# `Embedding → Latent → Decision → Embedding Feedback`

形成真正 Runtime 闭环。

---

# 43. 这使 Decision 不只是“Logit Demo”

如果 Decision 只：

```text
显示 entropy
```

没有意义。

它必须改变：

```text
Runtime behavior
```

例如：

```text
low confidence
→ 不执行 CodeAct

candidate surface low coverage
→ Retrieve More

persistent ambiguity
→ Replan
```

这样它才是：

```text
Decision State
```

而不是：

```text
Telemetry
```

。

---

# 44. 为什么这条路线比“Embedding + KV”更完整

如果只有：

```text
Embedding
+
KV
```

能讲：

```text
Embedding
选 Evidence

KV
少算重复 Context
```

但缺失：

```text
Agent A 新形成的 neural representation
怎么给 Agent B
```

。

增加 Hidden：

```text
Embedding
→ select existing information

Hidden
→ transfer newly formed representation

Decision
→ evaluate action uncertainty

APC
→ reuse repeated compute
```

整个模型状态空间才完整。

---

# 45. 对赛题的最终映射

## 低开销通信 25

主线：

```text
Typed protocol
+
减少不必要的 text handoff
```

Latent 提供增强证据。

---

## 状态创新 20

主 headline：

```text
LatentStateRef
```

生成：

```text
vLLM/HF hidden capture
```

传输：

```text
SHM / typed Ref
```

接收：

```text
alignment-compatible prompt embedding
```

使用：

```text
Consumer forward actual-use
```

。

---

## 共享记忆 20

仍然：

```text
Semantic Memory
```

主证据。

APC/KV：

```text
Computational Memory
```

是增强，不替代题目记忆。

---

## 系统完整性 20

Decision 很有价值：

```text
Agent 不直接拥有执行 Authority
Runtime 根据 typed state 做 policy
```

使项目明显区别于：

```text
简单工作流串模型 API
```

。

---

## 实验 15

Hidden 的 causal controls：

```text
Matched/Mismatched/Zero/Random
```

会比单纯：

```text
Text vs Latent
```

更有说服力。

---

# 46. 最终建议：哪些论文作为“核心依据”，哪些只放 Related Work

## 核心依据

### Decision

```text
Uncertainty Quantification for LLM Function-Calling
```

理由：

```text
和 StateBus tool/action gate 场景最直接
```

。

### Hidden

```text
StateBridge
```

理由：

```text
v1 实现方法最适合
```

。

```text
LatentMAS
```

理由：

```text
更强社区和 benchmark 信号
支持 latent collaboration 方向
```

。

```text
Communicating Activations
```

理由：

```text
独立证明 activation communication 的价值
```

。

### Experiment

```text
When Does Latent Communication Pay?
```

理由：

```text
直接决定 causal audit
```

。

### Security

```text
When Latent Agents Lie
```

理由：

```text
直接决定 Ref integrity contract
```

。

---

## Related / Future

```text
CIPHER
C2C
KVCOMM
Semantic Entropy
```

。

这些非常值得介绍，但不要把它们都包装成：

```text
我们马上要实现
```

。

---

# 47. 对论文证据强度的一个批判性排序

不能只看“最新”。

建议：

### 方向可信度较强

```text
LatentMAS
ICML 2026 Spotlight
Repo ~1105 stars

Communicating Activations
ICML 2025

C2C
ICLR 2026
Repo ~435 stars

CIPHER
ICLR 2024

Semantic Entropy
Nature 2024
```

。

### 方法适配度最高但工程/社区仍很新

```text
StateBridge
2026-08
Repo ~4 stars
```

所以它应该：

```text
作为 Latent v1 provider/reference
```

而不是：

```text
整个 StateBus 创新性的唯一学术背书
```

。

---

# 48. 最终技术选择

## BUILD

```text
DecisionState v2

LatentState / StateBridge Provider
```

。

## KEEP

```text
Semantic Embedding

Semantic Memory

APC
```

。

## KEEP + FREEZE

```text
Explicit KV Continuation
```

。

## FUTURE

```text
LatentMAS-style KV Working Memory

C2C semantic KV

KVCOMM cross-context reuse

mid-layer activation injection
```

。

---

# 49. 推荐开发顺序

```text
D0
Current Logit source audit

D1
DecisionSurface + DecisionPolicy v2

D2
Calibration / risk-coverage

L0
Modern Hidden Extraction compatibility

L1
StateBusHiddenStatesConnector

L2
StateBridgeAligner

L3
LatentStateRef lifecycle

L4
Causal controls

L5
Executor → Summarizer

L6
Decision EXPAND_EVIDENCE feedback
→ Embedding Retrieval
```

。

---

# 50. 最终项目叙事

不建议：

> “我们实现了 Embedding、Logit、Hidden、KV 多种非文本状态。”

建议：

> **StateBus 把模型内部信号按用途划分为 Selection State、Latent Representation State、Decision State 与 Compute Reuse State。Retrieval Embedding 用来选择高价值上下文；LatentState 将上游 Agent 的深层连续表示经过对齐后直接注入下游 Agent；DecisionState 将下游模型对有限合法动作的 belief 转化为 Runtime 的 accept/retry/retrieve/replan 决策；APC/KV 则独立负责已经完成的 Transformer Prefill 复用。StateBus 的核心贡献不是发明一种 tensor，而是让这些内部状态成为具有 identity、compatibility、authorization、lifecycle、integrity 和 actual-use audit 的 Runtime 对象。**

---

# 51. 一句话回答“为什么 Decision？”

> **因为 LLM 采样出的动作只是 Proposal，不应该天然等于 Runtime Authorization；DecisionState 保留模型在合法动作集合上的不确定性，使 StateBus 可以在执行有副作用的能力前进行可校准的 accept/retry/expand/replan。**

---

# 52. 一句话回答“为什么 Hidden？”

> **因为 Embedding 只能选择已有信息，不能表达 Agent 处理这些信息后新形成的内部 representation；Hidden/Latent 直接针对题目所说的“内部状态—文本—内部状态”离散化瓶颈。**

---

# 53. 一句话回答“为什么不直接用 KV？”

> **因为在当前 one-vLLM StateBus 中，公共上下文的 KV 计算复用已经由 APC 更自然地解决；用 final/deep Hidden 做 semantic handoff 能用更小、更干净、与 cache layout 更弱耦合的 payload 表达 Agent-specific representation，而不会把 semantic communication 与 serving cache lifecycle 混成同一个机制。**

---

# 54. 一句话回答“KV 以后还有没有价值？”

> **有：当我们未来需要 latent working memory、heterogeneous model semantic communication、cross-context reuse、跨 engine cache 或更长 KV 生命周期时，再研究 LatentMAS/C2C/KVCOMM/LMCache；但它们不是当前 Hidden v1 的前置条件。**

---

# 55. Reference Index

## Competition / StateBus

- StateBus repository  
  https://github.com/qcrs/os

- Competition specification  
  `docs/reference/题目.md`

- Current Logit State  
  `statebus/state/logit_state.py`

- Current Logit Gate  
  `statebus/runtime/logit_gate.py`

---

## Decision / Uncertainty

### Uncertainty Quantification for LLM Function-Calling

https://arxiv.org/abs/2604.22985

### Detecting hallucinations in large language models using semantic entropy

https://www.nature.com/articles/s41586-024-07421-0

### CIPHER — Let Models Speak Ciphers

https://proceedings.iclr.cc/paper_files/paper/2024/hash/e444859b2a22df6b56af9381ad1e9480-Abstract-Conference.html

---

## Hidden / Latent Communication

### StateBridge

Paper:

https://arxiv.org/abs/2608.13317

Repo:

https://github.com/YanwenPneg/StateBridge

Key implementation:

```text
methods/state_bridge.py
HiddenStateCapture
_align_hidden_sequence
_generate_with_prefix
```

### LatentMAS

Paper:

https://arxiv.org/abs/2511.20639

Repo:

https://github.com/Gen-Verse/LatentMAS

### Communicating Activations Between Language Model Agents

https://proceedings.mlr.press/v267/ramesh25a.html

### Beyond Tokens: A Unified Framework for Latent Communication in LLM-based MAS

https://arxiv.org/abs/2606.05711

---

## KV Semantic / Reuse

### C2C — Cache-to-Cache

Paper:

https://proceedings.iclr.cc/paper_files/paper/2026/hash/474ada926b331d78f06d95e8913111cc-Abstract-Conference.html

Repo:

https://github.com/thu-nics/C2C

### KVCOMM

https://arxiv.org/abs/2510.12872

---

## Causal / Security Audit

### When Does Latent Communication Pay?

https://arxiv.org/abs/2608.04893

### When Latent Agents Lie

https://arxiv.org/abs/2606.28958

---

# 56. Final Frozen Recommendation

当前 StateBus 最合理的 Model-Internal State 路线：

```text
Semantic Embedding
    KEEP
    ↓
Selection

Latent Hidden
    BUILD
    ↓
Semantic Representation Handoff

Decision Logit
    UPGRADE
    ↓
Runtime Uncertainty Control

APC
    KEEP
    ↓
Compute Reuse

Explicit KV
    FREEZE
    ↓
Mechanism Evidence

Semantic KV
    FUTURE
```

因此论文借鉴关系最终不是：

```text
我们选 StateBridge，
所以我们实现 Hidden。
```

而应该是：

```text
赛题指出 text serialization bottleneck
        ↓
CIPHER / Activation Communication / LatentMAS
共同说明 continuous communication 有价值
        ↓
StateBridge 给出当前最可落地的
training-free hidden→input alignment 方法
        ↓
Causal Audit 告诉我们如何证明它真的传了信息
        ↓
Latent Security 工作告诉我们怎样治理 opaque payload
        ↓
StateBus 把它做成
typed / authorized / lifecycle-managed LatentState
```

同时：

```text
Function-Calling UQ
        ↓
证明“模型选了某个动作”
并不等于“这个动作应该被立即执行”
        ↓
当前 LogitState 已有真实 probability transport
        ↓
升级成 DecisionState
        ↓
形成 ACCEPT / RETRY / EXPAND / REPLAN
        ↓
反馈回 Embedding / Planner
```

最终形成：

# `Selection → Latent Handoff → Decision → Feedback`

而 APC/KV 独立负责：

# `Shared Compute Reuse`

这就是当前最符合 StateBus、最贴赛题、同时工程风险可控的技术路线。
