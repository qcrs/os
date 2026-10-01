# 显式 KV：让下一个角色接着已有计算继续工作

这份文档用于准备显式 KV continuation 页面。页面关注一件事：长材料已经由 Executor 处理过，Summarizer 还要继续使用同一段上下文时，怎样减少第二次模型调用的 prefill 计算。

## 1. 页面主题

建议标题：

> **显式 KV：让下一个角色接着已有计算继续工作**

页面说明：

> **Executor 保存公共上下文的 KV，Summarizer 用 handle 加载它，只计算自己的后缀。**

评委看完这一页应当记住：

> **角色交接时，传递的可以是已经完成的模型计算状态。**

这页的重点是“交接以后少算了哪一部分”。`EngineLocalKVHandle`、capture、load、release 是支撑这件事的实现，不应盖过计算关系本身。

## 2. 它在系统中的位置

KV 发生在 Executor 和 Summarizer 之间：

```text
Planner → Retriever → Executor → Summarizer
                              └── explicit KV continuation
```

它接在证据已经准备好、Executor 开始处理长上下文之后。Executor 仍然生成普通的执行产物，Summarizer 仍然读取经过 Runtime 组织的输入；KV 只改变两个模型请求在引擎内部怎样完成 prefill。

显式 KV 有自己的模型服务接口和 Worker-local registry。它不是通用的 `SemanticStateRef` 或 `LogitStateRef`，也不在任意模型、任意 Worker 之间搬运 KV。当前实现要求 producer 和 consumer 使用同一 vLLM engine generation，并通过兼容性摘要和 token digest 对齐。

## 3. 场景：两个角色看同一份长材料

假设 Executor 和 Summarizer 都需要长报告、明细表或规则资料：

- Executor 根据材料完成一次计算，并生成 Artifact；
- Summarizer 需要基于同一份材料和 Artifact 组织带引用的结果；
- 两个请求的公共上下文很长，角色说明和最后的任务后缀不同。

普通的 full replay 会让两个请求分别重新计算公共上下文：

```text
Executor：   [parent context][executor suffix]  → 计算全部
Summarizer： [parent context][summarizer suffix] → 再计算全部
```

continuation 把这次交接改成：

```text
Executor：   [parent context] → capture parent KV
             [executor suffix]

Summarizer： [parent KV handle] + [summarizer suffix]
             → 只计算新增 suffix
```

这里复用的对象不是一段摘要文本，而是 vLLM 已经完成的 parent attention state。Summarizer 仍然有自己的后缀和输出过程。

## 4. 核心原理

把两个请求写成 parent 和 suffix：

```text
P = 共同的 parent token 序列
S_e = Executor 的后缀
S_s = Summarizer 的后缀
```

两种路径的主要计算可以写成：

```text
full replay：      prefill(P + S_e) + prefill(P + S_s)

continuation：     prefill(P + S_e)
                   + load(KV(P)) + prefill(S_s)
```

consumer 的 `computed_prefill_tokens` 从大约 `|P| + |S_s|` 变成接近 `|S_s|`。`inherited_kv_tokens` 记录从 parent 继承了多少 token 的状态。

这个公式是页面的技术中心。它说明 KV 的收益来自“跳过 parent 的重复 prefill”，而非简单地把两个模型请求合并成一个请求。

## 5. 具体实现

### 5.1 用真实 tokenizer 找 parent 边界

Executor 和 Summarizer 的逻辑消息经过同一 serving tokenizer 和 chat template 编码。Runtime 取两份请求的公共 token 前缀，并按 vLLM 的 block size 向下对齐。

```text
Executor request：   P | S_e
Summarizer request： P | S_s
                     ↑
              block-aligned parent
```

这一步避免把某个角色自己的 suffix 错当成公共 parent。若公共前缀太短、请求无法切出有效 parent，KV continuation 不进入可用状态。

### 5.2 Producer 捕获 parent KV

`EngineLocalKVRoleClient` 的 Executor 路径调用 vLLM 私有 loopback API：

```text
POST /statebus/kv/produce
```

请求包含 parent token IDs、Executor suffix、任务身份、模型兼容性摘要和是否捕获 KV。服务完成 producer 请求后，在 Worker-local registry 保存 parent KV，返回 `EngineLocalKVHandle` 和句柄元数据。

页面上可以把这一步写成：

```text
parent tokens → vLLM prefill → KV registry → handle
```

### 5.3 Consumer 使用 handle 继续生成

Summarizer 先确认自己的请求前缀与 parent token IDs 完全一致，再调用：

```text
POST /statebus/kv/continue
lane = kv_continuation
handle_id = EngineLocalKVHandle
suffix_token_ids = Summarizer suffix
```

Consumer 不重新提交 parent token IDs。Worker 根据 handle 加载 KV，再对 suffix 做 forward，返回普通的模型结果以及 `KVForwardProof`。上层 Runtime 继续按原来的 Artifact 和质量检查路径处理结果。

### 5.4 生命周期和使用边界

handle 的生命周期是一次 producer-consumer 交接：

```text
capture → ready → load/forward → release
```

句柄绑定 engine generation、model/tokenizer identity、parent token digest、任务和 attempt、TTL、KV bytes 等信息。consumer 使用结束后，角色适配器在 `finally` 中释放 handle，registry 需要回到清理状态。

当前 utility 对照中的 `full_replay` 与 `continuation` 使用相同 task、model、sampling、质量检查和 APC 关闭条件。这样测到的是显式 KV 路径本身的差异。标准任务默认保持 `STATEBUS_ENGINE_LOCAL_KV_MODE=off`。

## 6. 一页 PPT 的展示设计

### 6.1 这一页要证明什么

主标题只承担一个判断：

> **长上下文交给下一个角色时，公共计算可以沿着 KV handle 继续使用。**

页面要让评委按这个顺序理解：

1. Executor 和 Summarizer 为什么会重复处理同一份 parent；
2. `EngineLocalKVHandle` 在两者之间交接了什么；
3. consumer 的 prefill 哪一部分被省掉；
4. 实验怎样证明局部和端到端收益。

### 6.2 主图：full replay 与 continuation

页面中间用左右对照，左边是基线，右边是 continuation：

```text
FULL REPLAY                         KV CONTINUATION

Executor                            Executor
[P][S_e]                            [P][S_e]
  └─ prefill P + S_e                  └─ capture KV(P)

Summarizer                          EngineLocalKVHandle
[P][S_s]                                      ↓
  └─ prefill P + S_s                Summarizer
                                    [handle(P)] + [S_s]
                                      └─ prefill S_s
```

右侧的 `handle(P)` 用一张小对象卡片表示，卡片只列：

```text
parent token digest
engine generation
parent tokens
kv bytes
TTL / one-shot
```

图中央或底部放公式：

```text
full replay：prefill(P + S_s)
continuation：load(KV(P)) + prefill(S_s)
```

这张对照图是主视觉。它同时展示了问题、状态、交接位置和计算变化。

### 6.3 页面顶部标出系统位置

在标题下方放一条很窄的角色链：

```text
Planner → Retriever → Executor ── KV handle ──→ Summarizer
```

只高亮 Executor 到 Summarizer 的区段。这样评委知道 KV 是 Agent 协作链中的一条模型侧交接路径，不会把它理解成全局共享内存或所有角色都要使用的公共机制。

### 6.4 底部放实现链和证据

底部用一条细链说明实际调用：

```text
tokenize / block align
    → /statebus/kv/produce
    → capture handle
    → /statebus/kv/continue
    → forward proof
    → release
```

右下角放三项结果，并标明测量范围：

```text
consumer computed prefill  ↓ 90.37%
consumer TTFT              ↓ 60.88%
完整 task wall             ↓ 3.58%
```

`computed prefill` 证明重复计算减少，`consumer TTFT` 证明模型服务局部变快，`task wall` 说明 capture、store、load 等成本仍然存在。

## 7. 页面上放什么，讲解时补什么

### 页面主视觉必须有

- Executor → Summarizer 的链路位置；
- full replay / continuation 对照；
- parent KV 到 suffix continuation 的关系；
- `EngineLocalKVHandle` 的简化字段；
- `computed prefill` 的变化；
- capture → load → release 的实现链。

### 讲解时补充

- parent 来自真实 tokenizer 的公共 token 前缀；
- parent 按 block size 对齐；
- consumer 使用同一 engine generation；
- Worker forward proof 和 registry cleanup 怎样证明 handle 真被使用；
- private KV API 的请求只携带 handle 和 suffix。

### 不放在主画面

- 每个兼容性字段和错误码；
- KV registry 的全部容量限制；
- 把 KV 说成跨模型、跨机器的通用状态交换；
- 把显式 KV 和 APC 画成前后必经的两步；
- 只展示 90.37%，省略端到端 3.58%。

## 8. 与 APC 的关系

两者都减少长上下文的重复 prefill，但使用方式不同：

```text
KV：一个 producer 把 parent KV 显式交给一个 consumer
APC：多个独立请求共享相同 token prefix，由 vLLM 自动命中缓存
```

KV 页只需在页脚留这一行作为区分。APC 的动态调度和 prefix feedback 放在下一页讲。

## 9. 讲解稿

> Executor 和 Summarizer 都要处理同一份长材料。普通路径会让 Summarizer 再次计算 parent。我们先用真实 tokenizer 找到两份请求的公共 parent，并按 block 对齐；Executor 完成 parent prefill 后，把 KV 保存在同一 vLLM Worker 的 registry 中，返回一个短生命周期 handle。Summarizer 只提交这个 handle 和自己的 suffix，Worker 加载 parent KV 后继续计算。实验中 consumer 的 computed prefill 下降了 90.37%，TTFT 下降了 60.88%，完整任务下降 3.58%，后一个数字也把保存和加载成本算进去了。

这页最后让评委留下一个具体印象：

> **后一个角色接着前一个角色算过的上下文继续工作。**

## 10. 事实依据

- [Engine-Local KV Continuation](../implementation/runtime.md#engine-local-kv-continuation)
- [KV contracts](../../src/statebus/contracts/engine_local_kv.py)
- [KV role client](../../src/statebus/integrations/vllm_kv/role_client.py)
- [KV client and private API](../../src/statebus/integrations/vllm_kv/client.py)
- [KV 结果](../experiments/results.md#显式-kv继续使用已计算状态)
- [精选结果摘要](../../tests/evidence/model-assist/summary.md)
