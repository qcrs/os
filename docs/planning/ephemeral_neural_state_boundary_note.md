# Ephemeral Neural State Boundary Note

日期：2026-06-26  
状态：边界说明  
作用：明确 `KV cache / prefix state / neural handoff` 在 `StateBus v2` 中的位置，防止主叙事失焦。

---

## 1. 结论先说

`Ephemeral Neural State` 是值得研究的增强方向，但当前必须严格放在：

1. `Future Work`
2. `experimental appendix`
3. `Tier-0 experimental path`

它不是：

1. `MVP`
2. formal benchmark 必需项
3. 当前仓库主实现承诺

---

## 2. 为什么要单独写这个边界说明

因为这块最容易造成两种误导：

1. 明明只实现了 embedding + pruning，却说成“已实现神经状态接力”
2. 评委把注意力全部放到“你们到底有没有做 KV cache 传递”

这都会伤害 `v2` 的主线。

`v2` 当前真正需要证明的是：

1. 结构化控制面
2. 非文本 semantic state
3. execution artifact 一等公民
4. replay 真跳步

这里的“结构化控制面”当前已经冻结为 typed Protobuf control plane，而不是 `MessagePack` 主线。

不是先去赌一条高风险的显存级暂态路径。

---

## 3. 定义

本文把 `Ephemeral Neural State` 定义为：

> 在同一 task/session 的短生命周期内，由本地模型推理系统产生、并可能被下游继续消费的神经级暂态表示。

典型例子：

1. `KV cache`
2. `prefix cache`
3. `prefill hidden state pages`

当前更推荐的定性是：

> `Engine-Local Prefix Reuse`

如果需要进一步说明它在 `v2` 中如何与 `Embedding + pruning` 协同、为什么不会抹平 agent 分工，以及推荐的 `shared prefix + role suffix` 用法，可结合阅读：

- [kv_cache_and_embedding_interaction_note.md](/home/qcrs/statebus/project/docs/planning/kv_cache_and_embedding_interaction_note.md)

也就是：

1. 它首先属于推理引擎内部对象
2. 不是共享记忆对象
3. 不是 replay-ready 持久化对象
4. 不是跨任务历史资产

---

## 4. 它和 Semantic State 的区别

### 4.1 Semantic State

解决：

1. 找哪些证据值得进入 LLM
2. route/tool/memory match
3. 如何减少原始证据进入 LLM 的规模

载体：

1. embedding matrix
2. feature bundle
3. canonical evidence pack

### 4.2 Ephemeral Neural State

解决：

1. 已经进入模型后的 prefill 代价
2. 同会话内前缀复用
3. TTFT / decode 前的重复计算

载体：

1. `KV pages`
2. `prefix cache`
3. 模型推理引擎内部状态

### 4.3 二者关系

它们互补，不替代。

一句话说：

1. semantic state 是“找书”
2. neural state 是“传脑电波”

---

## 5. 为什么它现在不能进主线

### 5.1 生命周期太短

这类状态天然短命：

1. 依赖具体 session
2. 依赖具体模型实例
3. 依赖具体显存布局

### 5.2 环境依赖太重

它通常依赖：

1. 本地模型部署
2. 推理引擎暴露相应接口
3. 显存/页管理策略

而当前主线即便转到单容器 `Docker + openEuler`，这部分仍然会额外引入本地模型引擎、显存可见性和进程生命周期问题。

### 5.3 测量口径不稳

如果连以下问题都没回答，主线就不该写它：

1. 省的是 prefill time 还是 token
2. 统计的是 cache hit 还是 prompt bytes saved
3. 跨进程/跨 worker 如何安全挂载

---

## 6. 允许的叙事边界

可以写：

1. `v2` 在架构上预留 `Ephemeral Neural State` 通道
2. 当底层是支持 prefix/KV reuse 的本地模型引擎时，这是一条可研究增强路径
3. 当前系统会优雅降级到 `Semantic State + Replay`

不能写：

1. 当前正式实现已经支持跨任务 KV cache 复用
2. 当前 benchmark 的 token 节省主要来自 KV cache
3. API 模型也能透明享受同等神经状态传递

---

## 7. 推荐的架构位置

在主架构图里，它应处于：

1. 最外层增强路径
2. 灰色虚线框
3. 标注 `Experimental / Local Model Only`

不要放在：

1. 三通道主路径中心
2. `MVP` 数据面主框

---

## 8. 如果以后要做，先回答什么

只有先回答下面问题，才有资格把它从 `Future Work` 往前提。

### 8.1 生命周期问题

1. 是同一 `task/session` 内复用，还是跨任务复用
2. worker 崩溃后是否还能恢复
3. 显存回收和 task teardown 如何协调

### 8.2 可移植性问题

1. 是否限定某个本地引擎
2. API 模式如何优雅退化
3. openEuler 最终交付环境是否具备相应栈

### 8.3 指标问题

1. 统计 `prefill_saved_ms`
2. 统计 `prefix_cache_hit_rate`
3. 统计 `neural_state_transfer_bytes`

而不是混写成普通 token 节省。

### 8.4 最小对象模型问题

如果以后真的要接，建议至少先定义一个最小 handle：

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class NeuralStateHandle:
    engine_id: str
    session_id: str
    prefix_hash: str
    lifetime_scope: str = "session"
```

它应明确：

1. 不落盘
2. 不跨任务
3. 只在兼容引擎内有效

---

## 9. 与当前仓库现实的关系

当前仓库已经具备：

1. `StateRef`
2. `mmap/shared_memory`
3. `FEATURE_BUNDLE`
4. replay-ready memory

这些足以支撑正式主线。

当前仓库还不具备：

1. 显式的 `KV page` object model
2. local model neural state export/import contract
3. prefix cache telemetry

因此，当前把它降级是工程纪律，不是能力不足的掩饰。

---

## 10. MVP 与 Future Work 的划线

### 10.1 MVP

只做：

1. `Control Channel`
2. `Semantic State Channel`
3. `Execution Artifact Channel`

### 10.2 Future Work

预留：

4. `Ephemeral Neural State`

但仅保留：

1. 文档位置
2. 接口想定
3. 风险说明

---

## 11. 外部参考

关于 prefix / KV cache，建议只引用官方或引擎主文档，不做二手猜测：

- vLLM automatic prefix caching 文档：<https://docs.vllm.ai/en/latest/features/automatic_prefix_caching.html>
