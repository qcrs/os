# Lifecycle Matrix

日期：2026-06-26  
状态：`v2` 跨合同文档  
作用：把 `StateBus v2` 中不同对象的存储位置、拥有者、是否可 replay、以及 GC 触发条件统一成一张总表。

---

## 1. 目标

避免以下问题分散在不同合同里各说各话：

1. 谁拥有对象
2. 谁负责释放
3. 哪些对象可 replay
4. 哪些对象只允许短生命周期

---

## 2. 总表

| kind | 主要载体 | owner | replay_restorable | 默认 GC trigger |
| --- | --- | --- | --- | --- |
| `EMBEDDING_STATE` | `shared_memory` / `mmap` | producer worker | 否 | task teardown / shm budget pressure |
| `FEATURE_BUNDLE` | `mmap` / small inline metadata | producer worker | 否 | step consumed / task teardown |
| `HYDRATE_MANIFEST` | CAS sidecar + registry | producer worker / runtime | 是 | 与关联 state/artifact 一起清理 |
| `CANONICAL_EVIDENCE_PACK` | CAS sidecar + registry | evidence fuser | 是 | replay retention policy |
| `WORKSPACE_INPUT` | workspace file | runtime supervisor | 否 | step/task teardown |
| `EXECUTION_ARTIFACT_CANDIDATE` | workspace + artifact root | executor wrapper | 条件式 | end-of-DAG settlement |
| `EXECUTION_ARTIFACT_VERIFIED` | artifact root + CAS | runtime supervisor | 是 | retention policy / explicit invalidation |
| `REPLAY_LEDGER_ENTRY` | SQLite | runtime supervisor | 是 | explicit invalidation / retention policy |
| `NEURAL_STATE_HANDLE` | engine-local memory | local inference engine | 否 | session end / engine eviction / task teardown |

---

## 3. 解释

### 3.1 短生命周期对象

默认短生命周期：

1. `EMBEDDING_STATE`
2. `FEATURE_BUNDLE`
3. `WORKSPACE_INPUT`
4. `NEURAL_STATE_HANDLE`

### 3.2 replay-ready 对象

默认只有下面几类允许进入 replay-ready 层：

1. `HYDRATE_MANIFEST`
2. `CANONICAL_EVIDENCE_PACK`
3. `EXECUTION_ARTIFACT_VERIFIED`
4. `REPLAY_LEDGER_ENTRY`

### 3.3 候选态对象

`EXECUTION_ARTIFACT_CANDIDATE` 不应直接暴露给未来新任务。

它必须先经过：

1. validator/consumer 成功消费
2. task 成功终结
3. end-of-DAG settlement

---

## 4. GC 与降级

### 4.1 `shared_memory`

优先服务短生命周期 state。

预算压力下：

1. 先清理过期 task 的 state
2. 再降级新分配到 `mmap`

这条规则当前不是备选建议，而是冻结后的正式默认降级策略。

### 4.2 workspace

workspace 下的对象默认不长存。

只有被提升为：

1. verified artifact
2. replay-ready manifest

的对象才进入持久层。

---

## 5. `MVP` 实现建议

1. 先让每个 `ref_kind` 对应一条生命周期规则
2. 先让 runtime supervisor 持有 GC 决策权
3. 先把 `candidate -> verified` 与 `task teardown` 打通

---

## 6. 验收建议

建议最小验收：

1. `shared_memory` 对象在 task 结束后被清理
2. candidate artifact 不会被 replay lookup 看见
3. verified artifact 会保留并可恢复
4. engine-local handle 在 task/session 结束后失效
