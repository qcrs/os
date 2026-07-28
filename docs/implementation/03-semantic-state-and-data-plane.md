# 非文本状态与数据面导航

非文本状态按对象语义拆分。先明确各类 Ref 的边界，再分别查看检索 embedding 与执行候选概率怎样跨进程，随后理解数值选择如何重新回到可引用证据，最后阅读不同存储后端与释放规则。

| 文档 | 核心问题 |
|:--|:--|
| [Ref 类型边界](state/ref-boundaries.md) | SemanticStateRef、LogitStateRef、ExecutionArtifactRef、MemoryRef 为什么不能混成一种类型 |
| [稠密语义状态](state/dense-semantic-state.md) | query/candidate 矩阵如何编码、发布、解析和返回选择回执 |
| [LogitState](state/logit-state.md) | 闭集候选概率如何编码、由独立 PID 消费并留下 GateReceipt |
| [Hydration 与证据扇入](state/hydration-and-evidence.md) | row index 如何回到 locator，角色为何只看到自己的证据切片 |
| [分层存储与生命周期](state/storage-and-lifecycle.md) | shared memory、mmap、CAS、workspace 如何选择，lease 和 GC 如何清理 |

完整证据链不是只有 `STATE_PUBLISHED`：

```text
publish physical state
  -> resolve in another process
  -> select rows and recover candidate IDs
  -> record producer/consumer receipt
  -> record behavioral effect
  -> release physical object
```

当前主线传递 embedding 稠密矩阵与候选级概率状态。后者不是完整词表 logits；两者都不构成跨模型 KV cache 或 hidden state 传递。
