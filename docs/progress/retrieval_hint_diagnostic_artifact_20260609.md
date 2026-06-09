# Retrieval Hint Diagnostic Artifact 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前
`/home/qcrs/statebus/project`
为 `P1 retrieval` 补的一组更像 matched evidence 的
weak-hint diagnostic artifact。
它不是新的 formal benchmark，也不改写当前
`communication` / `state_transfer` / `memory`
三条正式 claim 的边界。

## 1. 这轮为什么值得补

在做完 retrieval candidate-pool refresh 之后，
我们已经知道：

1. retrieval 结构比以前更诚实
2. 现有 replay diagnostics 没被打坏

但还缺一层更直接的 retrieval matched evidence：

> 当前 out-of-hint retrieval 胜出，
> 到底在多弱的 hint 条件下还能成立？

这轮最值得补的不是再改 runtime，
而是把这条边界从终端 probe 升格成保留 artifact。

## 2. 新增 artifact

新包：

- `runs/host_goal_eval_20260609_201200_retrieval_hint_diag_det_r1/`

运行形态：

- `task_set = tasks/retrieval_hint_diagnostic_tasks.yaml`
- `repeat = 1`
- `modes = text,protocol`
- `llm_mode = deterministic`

新增任务：

1. `diag-retrieval-no-tags-001`
2. `diag-retrieval-misleading-tags-001`
3. `diag-retrieval-invalidation-control-001`

## 3. 这包现在直接证明什么

### 3.1 out-of-hint retrieval 胜出不再依赖当前任务 tags

`diag-retrieval-no-tags-001` 在 `text/protocol` 两侧都显示：

1. `retrieved_doc_ids[0] = cache-replica-false`
2. `feature_route = cache_replica_stale_read`
3. `execute tool = tool.replica_stale_read_triage`

这说明：

> 当前 out-of-hint retrieval 胜出，
> 已经不依赖当前任务 tags 才能成立。

### 3.2 misleading tags 也不会把 retrieval 硬拉回 hinted invalidation 路线

`diag-retrieval-misleading-tags-001` 在两侧都显示：

1. `retrieved_doc_ids[0] = cache-replica-false`
2. `feature_route = cache_replica_stale_read`
3. `execute tool = tool.replica_stale_read_triage`

这说明：

> 即使当前任务 tags 偏向 invalidation，
> 更强的 replica-lag query evidence 仍然能把 hinted 路线压下去。

### 3.3 retrieval refresh 没有塌成“无脑偏 replica”

`diag-retrieval-invalidation-control-001` 在两侧都显示：

1. `retrieved_doc_ids[0] = cache-invalid-anchor`
2. `feature_route = cache_invalidation`
3. `execute tool = tool.cache_invalidation_playbook`

这说明：

> 当前 retrieval refresh 不是 generic replica bias；
> 当 query 真正偏 invalidation 时，invalidation 路线仍然在顶上。

## 4. 当前最诚实的结论

这轮新增价值应记成：

> retrieval weak-hint matched diagnostic artifact

它现在支持的说法是：

1. out-of-hint retrieval 胜出不再依赖当前任务 tags
2. misleading tags 也不足以把 retrieval 拉回 hinted invalidation doc set
3. retrieval 仍保留正常的 invalidation negative control

它不支持的说法仍然包括：

1. retrieval 已经开放域泛化
2. 任意更弱 hint 条件下都会同样成立
3. deterministic diagnostic artifact 已足够替代新的 formal matched benchmark
