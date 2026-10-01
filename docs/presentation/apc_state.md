# APC：根据命中反馈调整长文本请求

这份文档用于准备 APC 页面。APC 指 vLLM 的 Automatic Prefix Caching。页面要说明两件事：Runtime 怎样把当前任务整理成可复用的公共 token prefix，以及连续任务执行时怎样根据实际命中情况调整后续任务顺序。

## 1. 页面主题

建议标题：

> **APC：根据实际命中反馈调整长文本请求**

页面说明：

> **先把公共 evidence 排成相同的 token 前缀，再用 vLLM 的 query/hit 反馈调整后续调度。**

评委看完这一页应当记住：

> **StateBus 负责准备和校准复用条件，vLLM 负责实际缓存命中。**

APC 是模型服务侧的缓存加速路径。它不把 KV handle 交给下一个 Agent，也不把 prefix block 纳入通用 StateRef；Runtime 通过请求布局和调度反馈影响命中机会，缓存 block 由同一 vLLM engine 管理。

## 2. 为什么需要 APC

长文档任务经常产生多个独立的模型请求：Executor 处理资料，Summarizer 生成报告，或者连续任务反复访问同一批文档。每个请求都可能带上相同的长材料。

即使两份 prompt 使用了相同的 evidence，只要前缀中的系统说明、渲染顺序、空格或 token 边界不同，vLLM 看到的就是不同 token 序列，prefix cache 就无法稳定命中。

普通的任务队列还会把不同资料的请求交错执行：

```text
资料 A → 资料 B → 资料 A → 资料 B
```

这会让刚建立的公共前缀很快被其他请求打断。APC 页面要讲的问题因此有两层：

1. 当前两个角色的 prompt 是否真的拥有同一段 token prefix；
2. 运行一段时间后，命中率与调度侧的预估是否一致，后续任务顺序要不要调整。

## 3. APC 的核心原理

把两个请求编码成 token 序列 `T_A` 和 `T_B`。公共前缀长度是：

```text
L = longest_common_prefix(T_A, T_B)
```

只有公共部分达到 vLLM block size 的完整 block，才有稳定的 prefix reuse 机会：

```text
eligible ⇔ L >= min_full_blocks × block_size
```

StateBus 做的是让 `L` 尽可能稳定、可验证：

```text
共同可见 evidence
    → stable-key intersection
    → canonical rendering
    → real tokenizer / chat template
    → exact token LCP
    → block alignment
    → 两个完整 prompt 发往同一 vLLM engine
```

vLLM 根据相同的 token block 决定 query、hit 和淘汰。Runtime 不读取或转移这些 cache block。

## 4. StateBus 的两层动态适配

### 4.1 请求级：每次按当前角色编译公共前缀

不同角色能看到的 evidence 可能不同。Runtime 先取参与角色的共同可见项，只保留 stable key 和 entry digest 都一致的内容，再按固定顺序渲染成公共前缀。

```text
Executor 可见：  e1, e2, e3, e4
Summarizer 可见：e1, e2, e3
共同前缀：       e1, e2, e3
```

`build_canonical_shared_evidence_prefix()` 负责交集和稳定渲染；`compile_exact_token_prefix_identity()` 使用真实 tokenizer 和 chat template 计算两份请求的最长公共 token 前缀，并按 block size 对齐。

这一层解决“语义上相同的材料没有落成相同 token”的问题。页面上可以用一条小链表示，不需要展开全部 digest 字段。

### 4.2 任务级：用实际命中反馈调整待执行队列

连续任务运行时，Runtime 为每个任务保留 prefix affinity hint，包括：

- `corpus_prefix_hash`：同一资料来源的调度身份；
- `cache_affinity_group`：可以连续执行的缓存亲和组；
- `estimated_prefix_tokens`：调度侧的前缀长度估计；
- 任务依赖关系和原始优先级。

每个任务执行前后读取 vLLM `/metrics`，计算本任务窗口内的 counter delta。反馈环的计算可以写成：

```text
e_t = predicted_hit_rate_t - observed_hit_rate_t
E   = mean(e_t) over recent window
```

当 `|E|` 超过配置阈值，且还有未执行任务时，Runtime 使用 `build_kv_prefix_schedule_plan(mode="cache_friendly")` 重排待执行队列，把相同 affinity group 的任务尽量放在一起，同时保留依赖约束：

```text
当前队列：A1 → B1 → A2 → B2
反馈显示命中低
调整后：  A1 → A2 → B1 → B2
```

这个例子只表示调度原则。实际调度由 `DependencyAwarePrefixScheduler` 选择 ready task，不会跨越未完成依赖。

`PrefixCacheFeedbackLoop` 负责记录预测值、观察值和是否应重排；`continuous_runner` 读取这个信号，并真正替换 `pending_rounds` 的顺序。反馈对象本身不修改 vLLM cache，也不导出 KV tensor。

## 5. 它在系统中的位置

APC 的位置可以画成一条模型服务侧支路：

```text
Runtime task queue
        ↓
RolePathRunner 编译请求
        ↓
同一 vLLM engine 的多个完整 prompt
        ↓
vLLM APC query / hit counters
        ↓
PrefixCacheFeedbackLoop
        ↓
调整后续 pending task 顺序
```

它和前面几类状态的关系如下：

```text
Embedding：传递候选选择依据
Logit：传递候选概率并影响证据展开
KV：显式交接 parent KV handle
APC：调整请求前缀和任务顺序，让引擎自动复用 cache block
```

APC 没有 `SemanticStateRef`、`LogitStateRef` 或 `EngineLocalKVHandle` 作为主交接对象。页面上不要画 shared memory、UDS 或通用 Ref 路径。

## 6. 一页 PPT 的展示设计

### 6.1 这一页要让评委先看到什么

主标题可以直接写：

> **同一份长材料，怎样让后续请求继续命中缓存？**

随后用一句话说明 StateBus 的工作：

> **请求级对齐公共 token 前缀，任务级根据真实命中反馈调整顺序。**

这页的主视觉应当是一个反馈闭环。单独展示 `same prefix → cache hit` 只能说明 APC 的基本机制，无法体现 StateBus 在运行时做了适配；只画调度重排又会让评委不清楚缓存为什么能命中。

### 6.2 主图：请求对齐和反馈调度放在同一个闭环

建议采用“中间请求面板 + 外围反馈环”的结构。

中间请求面板：

```text
Executor request：  [shared evidence prefix][suffix A]
Summarizer request：[shared evidence prefix][suffix B]
                         ↓
                 same vLLM token blocks
                         ↓
                   APC query / hit
```

面板左上角放一行 Runtime 的处理：

```text
共同 evidence → canonical render → exact tokenizer → block align
```

外围反馈环：

```text
pending task queue
        ↓ choose next
run request pair
        ↓
vLLM query/hit counter delta
        ↓
predicted vs observed hit rate
        ↓ |mean error| > threshold ?
     keep order / reorder pending tasks
```

“keep order” 和 “reorder pending tasks” 用两个小出口表示。这样评委能看到动态调整发生在任务执行过程中，而不是一开始写死一个 cache-friendly 列表。

### 6.3 页面右侧的小卡片：动态调整依据

放一张很小的反馈卡片：

```text
PrefixCacheFeedbackLoop
────────────────────────
predicted hit rate
observed hit rate
task-local query/hit delta
mean error over window
should_reorder
```

旁边补一句：

```text
反馈只使用当前任务窗口的 counter delta
```

这句话很重要。vLLM 的服务级累计 counter 不能直接代表某一个任务的命中情况，Runtime 需要使用任务前后的差值，并检查 engine instance、cache epoch、请求数量和窗口是否可用。

### 6.4 底部的小链：实现位置和职责

页面底部用三段小字交代职责：

```text
Runtime：共同 evidence、token identity、任务顺序
vLLM：prefix block 的驻留、命中、淘汰
Metrics：query/hit counter delta
```

可以再放一条很短的代码路径：

```text
prefix_identity.py → vLLM full prompt → prefix_feedback.py → continuous_runner.py
```

不需要在 APC 页展示 UDS、StateRef 或 KV bytes。它们不属于这条机制的核心实现。

## 7. 页面上放什么，讲解时补什么

### 页面主视觉必须有

- 两个完整请求共享的 token prefix；
- `exact token identity + block alignment` 这一条件；
- vLLM `query/hit` 的反馈位置；
- `predicted → observed → error → reorder` 的动态闭环；
- `keep order / reorder pending tasks` 两个结果。

### 讲解时补充

- 共同前缀来自参与角色的 evidence 交集；
- stable key 和 entry digest 用来保证交集中的内容相同；
- `PrefixCacheFeedbackLoop` 计算反馈，`continuous_runner` 执行重排；
- 重排只作用于尚未执行的任务，并保留依赖关系；
- adaptive feedback 的开启受 local vLLM、任务族和调度模式配置控制。

### 不放在主画面

- vLLM cache block 的内部淘汰算法；
- 完整的 tokenizer 或 chat template 代码；
- 把 APC 说成显式传递 KV tensor；
- 把所有任务都声称会自动重排；
- 把 APC utility 的共享布局对照直接说成动态反馈实验结果。

## 8. 实验结果怎样使用

当前 long-text utility suite 的 APC 对照是：

```text
apc_on_independent vs apc_on_shared
```

这组实验主要证明请求布局对缓存命中的影响：

- observed hit tokens：`48 → 5168`；
- consumer TTFT 平均下降 `89.59%`；
- 完整 task wall 平均下降 `4.29%`；
- 质量通过 `4/4`。

这些数字证明“公共 token prefix 确实带来 vLLM cache reuse”。它们不单独证明连续任务反馈重排带来了多少额外收益。动态重排应当以实现路径和运行报告中的 `prefix_feedback`、`adaptive_reorder_count` 为证据；如果某次报告没有记录有效重排，就只讲“系统具备反馈调整路径”，不要把它写成已测得的性能增益。

页面上的结果区可以这样排：

```text
布局对齐：hit tokens 48 → 5168
模型服务：consumer TTFT ↓ 89.59%
完整任务：task wall ↓ 4.29%
动态层：observed hit rate → reorder pending queue
```

最后一行用结构表示能力，前三行用正式 utility 数字证明 APC 的局部和端到端效果。两类证据不要混成一个百分比。

## 9. 与 KV 页的区分

APC 与 KV 都减少长上下文重复 prefill，但页面应各自回答不同问题：

```text
APC：不同请求怎样拥有相同的 token prefix？
KV：后一个角色怎样直接使用前一个角色的 parent KV？
```

APC 的主对象是请求布局和 cache counter；KV 的主对象是 `EngineLocalKVHandle`。APC 让 vLLM 自己命中公共 block，KV 让 producer-consumer 通过 handle 显式继续计算。两页不要连成固定的前后流程。

## 10. 讲解稿

> 长文本任务里，多个请求经常反复带上同一份材料。APC 能否命中，取决于它们是否真的拥有相同的 token 前缀，所以 Runtime 先取角色共同可见的 evidence，稳定渲染后用真实 tokenizer 检查最长公共前缀，并按 block 对齐。两个完整 prompt 仍然发送给同一个 vLLM engine，由引擎处理 cache block 的命中。
>
> 我们还把它接入连续任务调度。每个任务完成后，Runtime 读取这一任务窗口内的 query/hit counter 增量，比较预测命中率和实际命中率。如果误差超过阈值，就按资料的 cache affinity 重新排列尚未执行的任务，同时保留任务依赖。也就是说，系统会根据实际运行情况调整后面的请求顺序。

最后让评委留下：

> **先把请求排成能复用的前缀，再根据真实命中调整后续顺序。**

## 11. 事实依据

- [Engine-Local Prefix Reuse](../implementation/runtime.md#engine-local-prefix-reuse)
- [Prefix identity](../../src/statebus/runtime/prefix_identity.py)
- [Prefix feedback](../../src/statebus/runtime/prefix_feedback.py)
- [Continuous runtime adaptive reorder](../../src/statebus/benchmark/continuous_runner.py)
- [Prefix schedule plan](../../src/statebus/benchmark/kv_prefix_schedule.py)
- [APC 结果](../experiments/results.md#apc公共前缀复用)
- [模型侧精选结果](../../tests/evidence/model-assist/summary.md)
