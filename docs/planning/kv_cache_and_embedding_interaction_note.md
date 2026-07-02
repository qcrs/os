# KV Cache 与 Embedding 协同说明

日期：2026-06-26  
状态：`v2` 说明文档  
作用：说明 `KV cache / prefix reuse / hidden state handoff` 在 `StateBus v2` 里的真实定位、使用方式、与 `Embedding + pruning` 的关系，以及为什么它不会抹平 agent 分工。

---

## 1. 先回答最核心的问题

### 1.1 当前仓库是不是已经实现了这条路径

不是。

当前主仓库可以诚实宣称的是：

1. `StateRef`
2. `mmap / shared_memory`
3. `Embedding`
4. `FEATURE_BUNDLE`
5. `assist / validated_replay / exact_replay`

当前主仓库**不能**宣称：

1. 已实现通用 `LLM hidden state` 直传
2. 已实现跨任务 `KV cache` 复用
3. 已实现异构模型之间的神经状态接力

这条边界必须继续保持。

### 1.2 那 `v2` 文档里的建议是不是“共享前缀”

是，但要说完整：

> `v2` 如果以后接入 `KV cache`，推荐路径不是“把完整神经状态当 memory 到处传”，而是“在同一引擎内复用共享证据前缀，再让不同 agent 在这个共享前缀后面追加各自的 role suffix”。

这就是本文采用的工作定性：

> `Engine-Local Prefix Reuse`

而不是：

1. cross-task memory
2. replay persistence
3. arbitrary hidden-state export/import

---

## 2. 为什么不能把它理解成“每个 agent 都直接挂同一份 KV cache”

这种说法听起来很猛，但工程上太粗，会直接造成三类误解。

### 2.1 它会抹平 agent 分工

如果每个 agent 都拿到同一整段 prompt 对应的完整神经状态，而且后面不再区分 suffix，那么：

1. `Planner`、`Executor`、`Summarizer` 会变成“同一个脑子换不同名字”
2. agent 的职责边界会从“各自消费不同 contract”退化成“都在接同一个上下文”
3. 评委会质疑你们只是做了一个共享会话，而不是多 agent runtime

### 2.2 它会混淆 memory / replay / neural reuse

`KV cache` 不是：

1. `MemoryStore`
2. `ReplayCache`
3. `ArtifactCache`

它不适合：

1. 落盘
2. 跨任务检索
3. 作为正式历史资产回放

### 2.3 它会制造错误的实现承诺

一旦把它写成“任意 agent 之间都能传 hidden state”，就等于默认你们已经解决了：

1. 同模型权重一致性
2. 同 tokenizer 一致性
3. 同推理引擎一致性
4. 同 session 生命周期一致性
5. 显存对象的安全释放

这些如果没真的做，就不能提前写成事实。

---

## 3. `StateBus v2` 里它的正确定位

## 3.1 它属于哪一层

它不属于：

1. `Control Channel`
2. `Semantic State Channel`
3. `Execution Artifact Channel`

它属于：

1. 本地推理引擎内部的计算加速层
2. `Semantic State Channel` 之后
3. `Executor / Summarizer` 真正把证据喂给本地模型时的引擎级增强

更直白地说：

1. `Embedding` 决定“哪些证据应该进模型”
2. `KV cache` 决定“同一批证据不要重复 prefill”

### 3.2 它解决什么问题

它主要解决：

1. 相同前缀的重复 `prefill`
2. 同一 task 内多次消费同一批证据时的首字延迟
3. 多角色基于同一证据前缀生成不同输出时的重复计算

它**不直接**解决：

1. corpus 太大装不下的问题
2. 证据筛选问题
3. 跨任务长期复用问题

---

## 4. 它和 Embedding 的分工

## 4.1 一句话分工

1. `Embedding + pruning`：负责把“10 万字里该读哪 5000 字”先挑出来
2. `KV cache / prefix reuse`：负责让“这 5000 字不要被两个下游 LLM 步骤重复读两遍”

### 4.2 先后顺序

在 `v2` 里，二者的合理顺序应当固定为：

1. `Retriever` 做切块、embedding、召回
2. `Fan-in / Evidence Fuser` 组装 `CanonicalEvidencePack`
3. `Hydrator` 把证据 pack 还原成共享前缀文本
4. 第一个 LLM consumer 对这个前缀做一次 prefill
5. 后续 LLM consumer 复用这个前缀的 cache，再追加自己的 role suffix

当前冻结语境下，这条路径优先服务财报 / 经营数据分析类 task family，而不是 incident demo 类任务。

所以：

1. `Embedding` 发生在模型外
2. `KV cache` 发生在模型内

### 4.3 为什么它们不是替代关系

如果只有 `KV cache`，没有 `Embedding`：

1. 你还是得先把很大的证据全文塞进模型
2. 只是重复读第二遍时更快
3. 首次大规模证据摄入的成本还在

如果只有 `Embedding`，没有 `KV cache`：

1. 你会把证据规模降下来
2. 但多个下游 agent 仍可能重复 prefill 同一份证据

因此更合理的主叙事是：

1. `Embedding` 解决 evidence ingress
2. `KV cache` 解决 repeated prefill
3. `Replay / artifact reuse` 解决 repeated planning/codegen/output regeneration

---

## 5. 推荐的使用方式：`shared prefix + role suffix`

这是最关键的一条。

`StateBus v2` 不应把 `KV cache` 设计成“agent A 的完整脑状态直接给 agent B”。  
应设计成：

1. 多个 agent 共享同一个 `evidence prefix`
2. 每个 agent 再追加自己的 `role suffix`
3. 共享的是证据阅读结果，不是完整角色人格

### 5.1 共享什么

共享的是：

1. system prompt 中稳定且公共的部分
2. 经 `Embedding + fan-in + hydration` 产出的 `CanonicalEvidencePack`
3. 可能还包括固定的输出 contract 说明

不建议共享的是：

1. agent 私有的 role 指令
2. 上一个 agent 的完整 chain-of-thought
3. 上一个 agent 的最终任务结论

### 5.2 每个 agent 保留什么

每个 agent 保留自己的 `role suffix`，例如：

1. `Executor`：  
   “基于以上证据，生成可执行的 Python 数据清洗与绘图代码。输出只允许写入 `/data/outputs/`。”
2. `Summarizer`：  
   “基于以上证据和图表结果，写一份两段式管理摘要，不要生成代码。”
3. `Verifier`：  
   “基于以上证据和上游结果，检查是否存在数据口径冲突并给出风险标记。”

这样做的效果是：

1. 证据阅读只做一次或尽量少做
2. 角色行为仍然保持分工
3. 评委可以清楚看到“共享的是前缀，不是职责”

---

## 6. 哪些 agent 应该使用它，哪些不应该

不是所有 agent 都该碰 `KV cache`。

### 6.1 通常不需要

1. `Planner`
   - 主要消费 `CanonicalTaskSpec`、历史 telemetry、memory hit
   - 通常不是长证据阅读大户
2. `Retriever`
   - 主要在 CPU 侧做 embedding、召回、排序
   - 不是 LLM prefill 的主要消费者
3. `DataPrep / EvidenceFuser`
   - 主要做 deterministic merge/fan-in
   - 不需要引擎级神经状态

### 6.2 可能需要

1. `Executor`
   - 尤其在“先读证据，再写代码”的步骤
2. `Summarizer`
   - 尤其在“基于同一批证据，再写自然语言摘要”的步骤
3. `Verifier / Critic`
   - 如果它基于同一份证据做第二视角审查

结论就是：

> `KV cache` 应该只服务于“多个 LLM consumer 基于同一证据前缀进行不同后缀生成”的场景，而不是让所有 agent 都无差别共享。

---

## 7. 推荐对象模型

不要在控制总线上传原始 GPU tensor。  
更合理的是在控制面上传一个引擎私有 handle。

建议最小对象如下：

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class NeuralStateHandle:
    engine_id: str
    session_id: str
    prefix_hash: str
    model_id: str
    tokenizer_id: str
    lifetime_scope: str = "task_session"
```

最重要的纪律：

1. 它是 handle，不是原始 KV bytes
2. 它只在同一个本地引擎里有意义
3. 它不落盘
4. 它不进入 replay key
5. 它不进入 `MemoryStore`

如果后续做 telemetry，可再补：

1. `created_step_id`
2. `expires_at_ns`
3. `prefix_token_count`
4. `cache_hit_count`

---

## 8. 生命周期约束

这是第二个必须讲死的边界。

### 8.1 有效范围

建议只允许：

1. 同一 `task`
2. 同一 `session`
3. 同一 local engine
4. 同一 model
5. 同一 tokenizer
6. 同一 shared prefix

### 8.2 失效条件

任意一项变化，都应直接失效并回退到普通文本 prefill：

1. 证据 pack 改变
2. `prefix_hash` 改变
3. model 改变
4. tokenizer 改变
5. 引擎重启
6. 显存回收
7. task teardown

### 8.3 不要跨任务承诺

不建议把它写成：

1. 昨天任务 A 的 KV cache，今天任务 B 还能直接复用
2. 一个 agent crash 后，另一个 agent 从数据库恢复 KV cache

这些都不应属于 `MVP` 或当前 `v2` 主叙事。

---

## 9. 在单容器 openEuler 里的可实现路线

由于 `v2` 的目标环境已经是：

1. 单容器
2. 同文件系统根
3. 同 IPC 命名空间
4. 容器内多进程

这意味着相较于旧的 host-first 文档，`KV cache` 相关实验路径确实更可做。

但这里仍应选择**保守且可实现**的路线：

### 9.1 推荐路线

1. 容器内单独部署一个本地推理引擎进程
2. 使用引擎自带的 prefix caching 能力
3. runtime 只记录和传递 `NeuralStateHandle` 或 `prefix_hash`
4. agent 通过统一推理服务访问，不手写 GPU KV tensor 迁移

### 9.2 不推荐路线

1. 自己导出底层 KV tensor 后跨 worker 手工搬运
2. 不区分 model/tokenizer/backend 就硬传
3. 把显存对象伪装成 memory artifact 写入 SQLite

这三条都会把系统拖进高风险区，而且答辩也很难讲清楚。

---

## 10. 一个最适合答辩展示的工作流例子

任务：

> “基于同一份新能源车企财报证据，先生成毛利率清洗与绘图代码，再生成一份管理层风险摘要。”

### 10.1 第一步：Retriever 侧

1. `Retriever` 对财报切块
2. 生成 embedding
3. 本地相似度剪枝
4. 产出 `CanonicalEvidencePack`

此时的核心收益是：

1. 大量无关页面没有进 LLM
2. `raw_evidence_bytes_seen_by_llm` 大幅下降

### 10.2 第二步：Executor 侧第一次消费

1. `Executor` 拿到 hydration 后的证据前缀
2. 本地引擎第一次对这段前缀做 prefill
3. 生成 Python 代码与图表
4. 引擎内部为这个前缀建立 `NeuralStateHandle`

此时的角色后缀是：

> “请输出可运行的 Python 代码，读取 `/data/inputs/`，输出到 `/data/outputs/`。”

### 10.3 第三步：Summarizer 侧第二次消费

1. `Summarizer` 不再重新 prefill 同一批证据
2. 它复用相同 `prefix_hash` 对应的 cache
3. 只追加自己的 role suffix
4. 生成自然语言风险摘要

此时的角色后缀是：

> “请基于以上证据和执行结果写一份管理摘要，不要输出代码。”

### 10.4 这个例子里 agent 分工有没有被抹平

没有。

因为共享的是：

1. 财报证据前缀

不同的是：

1. `Executor` 的目标是生成代码和图表
2. `Summarizer` 的目标是生成解释性文本

所以他们共享的是“读过同一份材料”的成本，不是“变成同一个 agent”。

---

## 11. 它和 Replay 的关系

二者必须分开。

### 11.1 `KV cache`

解决：

1. 同一 task/session 内
2. 相同前缀的重复 prefill
3. 首字延迟与重复算力

### 11.2 `Replay`

解决：

1. 跨步骤甚至跨任务的复用
2. 旧代码、旧证据 shaping、旧 artifact 的重用
3. planning / codegen / execution 的跳步

所以：

1. `KV cache` 更像引擎局部优化
2. `Replay` 才是系统级长期复用

不能把：

1. `prefix hit`
2. `prefill saved`

写成：

1. exact replay
2. memory gain

---

## 12. 指标应该怎么记

`KV cache` 最好不要主打 token 节省，而应主打 prefill 计算节省。

建议记录：

1. `prefix_cache_hit_rate`
2. `prefill_saved_ms`
3. `shared_prefix_bytes`
4. `shared_prefix_tokens`
5. `neural_reuse_scope`
   - `task_session`
6. `neural_reuse_mode`
   - `shared_prefix_role_suffix`

不建议把下面两件事混写：

1. `raw_evidence_bytes_seen_by_llm`
   - 这是 `Embedding + hydration` 指标
2. `prefill_saved_ms`
   - 这是引擎级 prefix reuse 指标

---

## 13. 对答辩和文档话术的建议

如果后续接入成功，推荐这样表述：

> 我们没有把 KV cache 当作跨任务记忆，也没有把所有 agent 融成一个共享脑。  
> 我们做的是同一引擎内的 shared prefix reuse：先用 embedding 把证据收缩到一个 canonical evidence pack，再让多个下游 agent 共享这段证据前缀的 prefill 结果，各自追加 role suffix 完成不同职责。

不要写成：

1. “我们已经实现任意 hidden state 跨 agent 传递”
2. “KV cache 本身就是 memory”
3. “有了 KV cache 就不需要 embedding”

---

## 14. 本文对 `v2` 的最终约束

基于当前文档体系，`KV cache / hidden state handoff` 在 `v2` 里应被锁定为：

1. 可研究增强路径
2. 本地模型专属路径
3. `Engine-Local Prefix Reuse`
4. `shared prefix + role suffix`
5. 不进入 replay key
6. 不进入跨任务 memory
7. 不替代 `Embedding + pruning`

当前最合理的推进顺序是：

1. 先把 `Embedding + pruning + canonical evidence pack + replay` 做扎实
2. 再在单容器 openEuler 的本地引擎路径上补 `prefix reuse`

---

## 15. 参考

1. vLLM 官方文档，Automatic Prefix Caching：<https://docs.vllm.ai/en/latest/features/automatic_prefix_caching.html>
2. Kwon et al., *Efficient Memory Management for Large Language Model Serving with PagedAttention*：<https://arxiv.org/abs/2309.06180>
