# Logit 状态：用候选概率决定是否展开证据

这份文档用于准备“非文本状态”部分的 Logit 页面。这里要讲清楚一个具体问题：候选已经很少，但完整证据很长时，系统怎样判断当前信息够不够，什么时候需要补充材料。

## 1. 这一页要讲什么

建议的页标题：

> **Logit 状态：用候选概率决定是否展开证据**

页面上的一句说明：

> **选择输出留下分布，Runtime 决定继续、复查或停止。**

评委看完这一页，应当记住：

> **StateBus 把 choice token 的候选概率变成证据展开决策。**

这里有三个具体动作：

1. Executor 先在少量候选中做选择；
2. StateBus 从选择位置的 `top-logprobs` 提取候选概率；
3. Runtime 根据概率结果继续执行、请求一次更完整的证据，或者结束这次选择。

Logit 为调度提供依据。证据本身、业务计算和结果校验仍由原有流程负责。

## 2. 核心原理：把一次选择变成一个可计算的判别

这里的“Logit”沿用项目中的状态命名。实际传递的内容是选择位置的候选 token 概率，不是完整词表的 logits，也不是模型的隐状态。

Executor 被要求只返回一个固定格式的 choice code，例如 `A`、`B` 或 `C`。StateBus 在这个 choice token 所在的位置读取 provider 返回的 `top-logprobs`，把每个候选 alias 的 log probability 转成概率：

```text
p_i = exp(logprob_i)
p_other = max(0, 1 - Σ p_i)
state = [p(A), p(B), ..., p(N), p_other]
```

`p_other` 表示候选集合之外的剩余概率。只有所有候选 alias 都能在同一个选择位置找到，并且 token 字节与 completion 对齐时，StateBus 才发布这份状态。

只保存 `choice_code`，Runtime 只能知道模型选了谁，无法知道第一名和第二名是否接近，也无法知道候选集合之外是否还有明显的概率质量。把完整 `top-logprobs` 当作文本交给下游，又会把模型接口的原始输出重新交给接收方解析。固定宽度的概率向量保留了调度真正需要的两类信息，并且可以由独立 Worker 直接消费。

Decision Worker 读取状态后，先找出候选中的最高概率和第二高概率：

```text
top1 = argmax_i p_i
margin = p_top1 - p_second
```

基础 gate 的判定可以写成：

```text
accept  ⇔ selected == top1 and margin >= 0.10
retry   ⇔ otherwise
```

model-assist utility 在此基础上还要求 exact probability 可用，并要求 `p_other <= 0.20`。这些条件让 Runtime 能区分“当前选择足够明确”和“需要再看一次完整材料”。

举一个示意例子：

```text
明确：  [A=.72, B=.18, C=.05, other=.05]
       top1=A，margin=.54  → accept

含糊：  [A=.46, B=.39, C=.08, other=.07]
       top1=A，margin=.07  → retry
```

如果模型返回 `B`，但 `A` 的概率最高，即使 margin 达到阈值，也会进入 `retry`。Runtime 不替换模型选择，只根据选择和分布的关系决定是否追加证据。

这套计算是本页的技术中心。后面的 shared memory、UDS 和 receipt 解决的是状态怎样送到 Worker、怎样把判定结果带回 Runtime。

## 3. 什么时候需要它

### 3.1 场景：候选很少，材料很长

这里使用一个通用的“候选确认”场景，不绑定财务、运营或某个行业：

- Runtime 已经把资料范围缩小到少数候选；
- 每个候选都有一份短说明和一份完整材料；
- Executor 需要从候选中选出一个，或者明确表示证据不足；
- 大部分样本用短说明就能判断，少数样本必须回看完整材料。

可以把一次选择画成：

```text
候选 A     compact evidence / full evidence
候选 B     compact evidence / full evidence
证据不足   insufficient_evidence
```

Executor 先看到 compact evidence，输出一个闭集的选择码。若选择明显，任务继续；若两个候选接近、候选集合外的概率较高，或者模型明确选了 `insufficient_evidence`，Runtime 再组织 full evidence 做一次复查。

这个场景的矛盾很直观：每次都发送完整材料，输入成本固定偏高；每次只发送短说明，又没有处理信息不足的样本。Logit 状态给 Runtime 提供了中间路径。

### 3.2 三种处理方式

模型侧专项用三个条件做对照：

| 条件 | 输入方式 | 用来说明什么 |
| --- | --- | --- |
| `full_context_once` | 一开始就给完整证据 | 完整输入的质量和开销基线 |
| `compact_once` | 只给紧凑证据 | 只压缩输入时的结果 |
| `logit_selective` | 先给紧凑证据，按概率决定是否复查 | 证据展开是否可以按需发生 |

Logit 的价值落在第三种条件：明确的选择不再展开，含糊的选择才请求 full evidence；完整材料仍无法区分时，系统保留 `abstain` 结果。

发布一段概率状态本身不会自动减少 token。实际节省来自后续没有发生的 full evidence 调用。

## 4. 它和 Embedding 的关系

Embedding 和 Logit 都属于非文本状态，但处理的是不同阶段的问题：

| Embedding | Logit |
| --- | --- |
| 候选资料还很多，先找相关片段 | 候选已经很少，判断当前证据是否够用 |
| 状态是 query/candidate 向量矩阵 | 状态是候选 choice token 的概率 |
| 结果是 candidate ID、row index、score | 结果是 `accept` 或 `retry`，以及一份判别回执 |
| Runtime 把选中的行恢复成证据 | Runtime 根据回执决定是否展开证据 |

两者可以在同一个任务中先后出现，也可以单独启用。页面上不要把它们画成所有任务都必须经过的一条流水线。适合的连接句是：

> Embedding 负责缩小资料范围；Logit 负责判断缩小后的证据是否足够。

## 5. StateBus 具体怎样做

### 5.1 先把候选固定下来

Logit 需要一个已经确定的候选集合。StateBus 用 `CandidateSurfaceV2` 把模型返回的短 alias 和稳定的候选身份绑定起来：

```text
CandidateSurfaceV2
────────────────────────────
A → candidate_1
B → candidate_2
C → insufficient_evidence
```

当前合同支持 2 到 8 个候选。每个绑定包含：

- `ordinal`：候选在概率向量中的位置；
- `alias`：模型需要返回的 `A` 到 `H`；
- `candidate_id`：后续执行和结果引用使用的稳定 ID；
- `candidate_digest`：候选身份的摘要。

模型只需返回一个闭集的 `choice_code`。Runtime 根据 alias 找回 candidate ID，后面的概率、证据和产物都沿用这个 ID。`insufficient_evidence` 也是一个明确候选，系统可以把“材料不够”与“选中了错误候选”区分开。

### 5.2 从选择位置提取概率

模型返回 choice code 后，StateBus 在真实 provider response 的 `top-logprobs` 中找到对应的选择位置，并按 `CandidateSurfaceV2` 的顺序提取每个 alias 的概率。

状态载荷的形式是：

```text
[p(A), p(B), p(C), other_mass]
```

其中：

- 前几项分别对应候选 A、B、C；
- `other_mass` 是候选集合之外的概率质量；
- 数值按 little-endian `float32` 写入；
- 载荷长度为 `4 × (candidate_count + 1)` bytes。

实现还会记录 `LogitProducerReceipt`，包括 request ID、attempt ID、choice token 位置、序列长度、候选映射摘要和状态是否可用。

概率提取有明确的失败结果。候选 alias 缺失、choice token 的字节与 completion 对不上，或者候选概率加和超过允许范围时，producer receipt 会标为 `unavailable`。model-assist utility 还提供本地 tokenizer 对齐路径，用来处理 provider 返回的 token 字节无法直接对应的情况。页面不需要展示这段对齐代码，只要说明状态来自真实选择 token，并且提取失败会被记录。

### 5.3 状态和控制请求分开传

候选概率写入 shared memory，Runtime 得到一个 `LogitStateRef`。跨进程 Worker 收到的是引用和操作上下文：

```text
控制消息：LogitStateRef + operation + task/attempt context
            └── Protobuf over UDS

状态内容：candidate probabilities + other_mass
            └── shared memory
```

Worker 根据 Ref 打开状态对象，读取固定宽度的概率向量。`LogitStateRef` 绑定 state ID、blob hash、长度、候选映射和 lease；消费完成后 Runtime 释放对象并留下 release/tombstone 记录。

这一段在页面上只需要说明两件事：概率确实作为数值状态跨进程传递；控制面没有把概率数组重新拼进文本消息。Protobuf、UDS 和 shared memory 是这条路径的实现方式，页面的重点是概率如何进入后续调度。

### 5.4 Decision Worker 计算判别结果

Decision Worker 读取状态后，计算并回传一份 `LogitGateReceipt`。页面可以展示下面四个字段：

```text
selected alias       当前模型选择
top1 alias           概率最高的候选
top margin           第一名与第二名的差距
other_mass           候选集合之外的概率
```

回执还包含 `selected_probability`、`normalized_entropy`、`decision_id`、候选数量以及 producer/consumer PID。基础 gate 的判断是：模型选择必须是 top-1，且 `top_margin >= 0.10`，通过时返回 `accept`，否则返回 `retry`。

model-assist utility 的 Runtime review 还检查 `other_mass <= 0.20`、精确概率可用等条件。因此答辩时可以把它概括为“看选择是否足够明确”，但讲解者要清楚这些条件分别来自 Worker gate 和 utility policy。

### 5.5 Runtime 决定下一步

`accept`、`retry` 和 `abstain` 分属两个阶段：

```text
compact evidence
    ↓
Decision Worker：accept / retry
    ├─ accept → 继续执行选中的候选
    └─ retry  → Runtime 请求一次 full evidence 复查
                    ├─ 判断明确 → 继续执行
                    └─ 仍然含糊 → Runtime 返回 abstain
```

职责关系如下：

- Decision Worker 读取概率并返回 `accept` 或 `retry`；
- Runtime 重新组织 full evidence，并限制复查次数；
- `abstain` 是复查后仍无法完成选择时的最终业务结果。

Logit 不修改证据，不生成 Artifact，也不替代 Executor 的业务计算。它把模型侧的数值分布转换成 Runtime 可以执行的证据取舍动作。

## 6. 一页 PPT 的中心和画法

### 6.1 这一页要证明什么

这页的主题建议定为：

> **Logit 状态：用候选概率决定是否展开证据**

副标题可以写：

> **模型先做一次小输入选择，Runtime 再决定要不要付出完整取证的成本。**

这一页要证明的内容只有一件事：模型的选择结果带有一份可计算的分布，StateBus 把这份分布交给 Runtime，Runtime 据此决定继续执行还是追加证据。

单独画流程图，评委只能看到“先发布、再消费、再返回”；单独画概率柱状图，又看不出它怎样影响任务。页面需要把“概率分布”和“证据动作”放在同一个主图里，IPC 和对象生命周期收进底部的小字。

### 6.2 主图：从紧凑证据到证据动作

页面主体采用左、中、右三段布局。

左侧表示 Executor 的输入：

```text
compact evidence
────────────────────────
A → candidate_1
B → candidate_2
C → insufficient_evidence

model output: choice_code = A
```

这里让评委看到候选集合已经固定，模型只需要在集合内选择。`choice_code` 是模型输出，候选身份仍由 Runtime 的 `CandidateSurfaceV2` 管理。

中间表示 StateBus 保存和计算的内容。先画一个概率向量，再画成带颜色的条形：

```text
state = [p(A), p(B), p(C), p_other]

A      ████████████████  .46
B      █████████████     .39
C      ██                .08
other  █                   .07
```

条形图上标出两个量：

```text
margin = p_top1 - p_second
other_mass = 1 - Σ p(candidate_i)
```

`margin` 用括号标出最高条和第二高条之间的差距。它表达“候选第一名领先第二名多少”。`other_mass` 单独用灰色条表示，表达“当前登记的候选集合之外还剩多少概率”。它不是某个候选的分数，也不是质量评价；它反映这次闭集候选是否覆盖了模型在选择位置上的主要概率。

旁边放一个小的 gate 规则框：

```text
selected == top1
and margin >= τ       → accept
otherwise              → retry

utility policy: other_mass <= 0.20
```

`τ=0.10` 和 `other_mass=0.20` 作为实现策略写在规则框的小字里。页面不需要解释“0.10 代表多少确定性”，只需让评委看到系统使用明确的阈值和可复现的判定量。

右侧表示 Runtime 后续动作：

```text
accept
  → 继续执行选中的 candidate

retry
  → 组织 full evidence，再检查一次

full recheck 仍不满足
  → abstain
```

`accept` 和 `retry` 标为 Decision Worker 的回执，`abstain` 标为 Runtime 在复查后的结果。这样页面既有数值原理，也有它在主任务中产生的动作。

### 6.3 用两个小例子让公式有意义

在概率条形图下方并列两个很小的状态卡片，使用示意数据：

```text
明确选择
[A=.72, B=.18, C=.05, other=.05]
margin=.54，other_mass=.05
        → accept

需要复查
[A=.46, B=.39, C=.08, other=.07]
margin=.07，other_mass=.07
        → retry
```

两个例子分别说明：

- `margin` 小时，最高候选和第二候选接近，Runtime 会要求补充证据；
- `other_mass` 记录候选集合之外的概率，即使候选内部有第一名，也可以作为 utility policy 的复查条件；
- 如果模型返回 `B`，但 `A` 才是 top-1，Worker 也返回 `retry`，因为模型选中的候选没有得到自身分布的支持。

这两个小卡片比展示一长串原始 `top-logprobs` 更有用：评委能直接看见数值如何变成动作。

### 6.4 底部保留一条核心链路

主图下方用一条细线交代实现闭环：

```text
choice token + top-logprobs
          ↓
[p(A), p(B), ..., p_other]  →  LogitStateRef
          │                         │
          ├─ probability blob ── shared memory ──→ Decision Worker
          └─ Ref + gate request ─ Protobuf/UDS ──→ Decision Worker
                                                   ↓
                                            LogitGateReceipt
                                                   ↓
                                Runtime：continue / full recheck / abstain
```

其中 `Protobuf/UDS` 只标在控制线旁，`shared memory` 只标在概率状态旁。底部这条线负责回应赛题的“生成、传递、接收、后续使用”；它不抢占主图的视觉重点。

### 6.5 视觉重点的先后顺序

评委的阅读顺序应当是：

1. 左侧看见“为什么先给 compact evidence”；
2. 中间看见概率向量、`margin`、`other_mass` 的含义；
3. 右侧看见 Runtime 的三种后续动作；
4. 底部确认这份状态确实经过了跨进程传递和独立 Worker 消费。

因此，公式和概率条形图要比 UDS、PID、lease 等字段醒目。后者属于实现支撑，放在讲解或底部即可。

## 7. 这一页讲到什么深度

### 页面上必须出现

- compact evidence 与 full evidence 的两阶段关系；
- `CandidateSurfaceV2` 的 alias 到 candidate ID 映射；
- `p_i = exp(logprob_i)` 和 `margin = p_top1 - p_second` 两个核心计算；
- `[candidate probabilities, other_mass]` 这种状态载荷；
- `margin` 表示前两名候选的差距，`other_mass` 表示候选集合之外的概率；
- Decision Worker 的 `top1`、margin 和 action；
- Runtime 的 `accept / retry / abstain` 后续动作；
- shared memory 承载概率，Protobuf/UDS 承载控制请求和回执。

### 讲解时可以补充

- 当前候选合同支持 2 到 8 个候选；
- 概率来自真实 choice token 的 `top-logprobs`；
- `LogitProducerReceipt` 和 `LogitGateReceipt` 如何把生产、消费、选择串起来；
- 基础 margin 阈值 `0.10`，utility 的 `other_mass` 阈值 `0.20`；
- 状态由独立 PID 的 Worker 消费，消费后释放。

### 不要占主画面

- 完整词表 logits；
- 所有 token 的原始 top-logprobs 列表；
- 概率提取函数的代码；
- 每一个校验字段和清理细节；
- 把 Logit 说成正确率证明、风险评分或安全保证；
- 把 Embedding、Logit、APC、显式 KV 画成一条固定链路。

## 8. 这一页怎样接实验

实验数据要回答“按需展开是否有效”，不需要列出所有模型字段。

当前 model-assist utility suite 的结果是：

- 4 个 case，每个 case 有 `full_context_once`、`compact_once`、`logit_selective` 三种条件，共 12 个计分位置；
- 9 个 resolved case 通过，3 个 unresolved case 正确 `abstain`；
- resolved case 中，`compact_once` 和 `logit_selective` 的 logical input 平均比 full context 少 `75.21%`；
- provider request wall 相比基线平均下降：`compact_once` 为 `17.18%`，`logit_selective` 为 `18.51%`。

这些数据来自独立的模型侧专项，用来证明选择性取证在这组候选任务中减少了输入和请求开销，并且保留了“证据不足”的结果。它们不能被表述成 48 个主任务的 Logit 单项收益。

页面最好把一个 resolved case 和一个 unresolved case 并列：

```text
resolved：compact → accept → 继续执行
unresolved：compact → retry → full recheck → abstain
```

这样比单独展示一个平均百分比更容易说明系统既能省一次展开，也能在材料不足时停下来。

## 9. 讲解顺序

可以按下面的顺序讲这页：

> 候选已经缩小以后，真正花钱的地方可能是把一整份材料再次交给 Executor。我们先给它一份紧凑证据，让模型只在固定候选中选择。StateBus 从这个选择位置的真实 top-logprobs 中提取候选概率，按候选顺序写成 LogitStateRef，并交给独立 Worker 消费。Worker 判断当前选择是不是 top-1、和第二名的差距是否够大，以及候选集合外的概率是否过高。通过就继续；不确定就请求一次完整证据复查；复查后仍然无法区分，就返回 abstain。

最后落到一句具体的话：

> **完整证据只在判断需要时展开。**

## 10. 和其他非文本机制的衔接

这页和前后的关系可以保持简单：

```text
Embedding：从很多资料中选出候选证据
Logit：判断候选证据是否够用
APC / 显式 KV：后续继续处理长上下文时复用已经做过的计算
```

APC 和显式 KV 是两条不同的长文本计算复用路径，当前专项中分别测试，页面上不要把它们接到 Logit 的流程末端。Logit 也不要求每个任务都开启，它适合有闭集候选和“必要时再补充证据”这个决策点的任务。

## 11. 事实依据

- [Logit 合同和候选绑定](../../src/statebus/contracts/logit.py)
- [choice token 提取与概率状态](../../src/statebus/runtime/logit_state.py)
- [Logit 状态发布、消费和释放](../../src/statebus/state/logit_state.py)
- [Decision Worker 调度](../../src/statebus/runtime/logit_gate.py)
- [模型侧运行路径](../implementation/runtime.md#logit-retry-decision)
- [Logit 实验结果](../experiments/results.md#logit按候选概率展开证据)
- [模型侧精选证据](../../tests/evidence/model-assist/summary.md)
- [Embedding 页面设计](./embedding_state.md)
