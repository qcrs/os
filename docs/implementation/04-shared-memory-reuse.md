# 共享记忆实现导航

这里的“共享记忆”是跨任务知识层，不是 Python `shared_memory` 物理载体。实现被拆成候选检索、兼容与消费、提交与重放三部分，因为三者的分母和安全条件不同。

| 文档 | 核心问题 |
|:--|:--|
| [混合召回与 RRF](memory/hybrid-retrieval.md) | keyword、tag、vector 三路候选如何合并 |
| [兼容门与真实消费](memory/compatibility-and-consumption.md) | 相似候选为什么可能被拒绝，什么才算 actual-use |
| [记忆提交与分级重放](memory/commit-and-replay.md) | verified 产物如何写回，assist、validated replay、exact replay 有何区别 |

```text
MemoryQuery
  -> keyword / tag / vector candidates
  -> RRF rank fusion
  -> CompatibilityDecision
  -> role-bounded MemoryRef input
  -> MemoryConsumptionRecord
  -> behavioral effect
```

文档始终区分 candidate、compatible、consumed 和 effect。候选数量或向量相似度不能直接称为复用率。

