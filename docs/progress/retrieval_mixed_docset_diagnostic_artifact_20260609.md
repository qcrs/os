# Retrieval Mixed Docset Diagnostic Artifact 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前
`/home/qcrs/statebus/project`
为 `P1 retrieval` 再补的一层
widened mixed-doc-set matched evidence。
它不是新的 formal benchmark，
也不改写当前
`communication` / `state_transfer` / `memory`
三条正式 claim 的边界。

## 1. 这轮为什么值得补

上一轮已经补出了两层 retrieval 证据：

1. weak-hint cross-family diagnostics
2. wrong-family context diagnostics

但 problem map 里仍剩一层没被单独隔离的问题：

> 当前 retrieval 在 widened preferred doc set 下，
> 还会不会被更杂的 mixed family prior 拉歪？

也就是说，
之前已经知道：

1. 当前 tags 不是硬依赖
2. current hinted docs 不是硬依赖
3. wrong-family `task_group / task_theme`
   也不是硬依赖

但还没有一组单独 artifact
回答这一层更接近 matched benchmark 的问题：

1. wrong-family task context
2. mixed family preferred docs
3. same query family positive / control pair

合在一起时，
query evidence 还能不能把正确 route 顶出来。

## 2. 新增 artifact

新包：

- `runs/host_goal_eval_20260609_235900_retrieval_mixed_docset_diag_det_r1/`

运行形态：

- `task_set = tasks/retrieval_mixed_docset_diagnostic_tasks.yaml`
- `repeat = 1`
- `modes = text,protocol`
- `llm_mode = deterministic`

任务结构：

1. latency pair under cache-family context:
   - `diag-retrieval-mixed-latency-worker-001`
   - `diag-retrieval-mixed-latency-db-control-001`
2. cache pair under session-family context:
   - `diag-retrieval-mixed-cache-replica-001`
   - `diag-retrieval-mixed-cache-invalidation-control-001`
3. session pair under latency-family context:
   - `diag-retrieval-mixed-session-rate-limit-001`
   - `diag-retrieval-mixed-session-drift-control-001`

稳定性摘要：

1. `text`:
   - `expectation_match_rate = 1.00`
   - `failure_count = 0`
2. `protocol`:
   - `expectation_match_rate = 1.00`
   - `failure_count = 0`

## 3. 这包现在直接证明什么

### 3.1 widened mixed preferred docs 也不足以把 retrieval 拉回错误 family

在 `text/protocol` 两侧都成立：

1. `diag-retrieval-mixed-latency-worker-001`
   - top doc = `latency-worker-false`
   - route = `worker_queue_starvation`
2. `diag-retrieval-mixed-cache-replica-001`
   - top doc = `cache-replica-false`
   - route = `cache_replica_stale_read`
3. `diag-retrieval-mixed-session-rate-limit-001`
   - top doc = `session-rate-limit-false`
   - route = `auth_rate_limit`

这些任务都同时带着：

1. wrong-family `task_group / task_theme`
2. mixed family `corpus_doc_ids`
3. 至少一个 in-family but wrong-route preferred doc

这说明：

> 当前 retrieval
> 不只是在“单一 wrong-family context”
> 或“单一 misleading doc hint”下能保持正确 route；
> 即使把 preferred docs 扩成 mixed family widened doc set，
> query evidence 仍能把正确 family 的 route 顶出来。

### 3.2 三组 same-family control 也都还活着

在 `text/protocol` 两侧都成立：

1. `diag-retrieval-mixed-latency-db-control-001`
   - top doc = `latency-db-anchor`
   - route = `db_pool_saturation`
2. `diag-retrieval-mixed-cache-invalidation-control-001`
   - top doc = `cache-invalid-anchor`
   - route = `cache_invalidation`
3. `diag-retrieval-mixed-session-drift-control-001`
   - top doc = `session-auth-anchor`
   - route = `auth_session_drift`

这说明：

> widened mixed doc set
> 并没有把 retrieval 压扁成某个 family 内的 generic bias；
> 当 query 真正指向 control route 时，
> 各自 same-family control 仍然能留在顶上。

## 4. 当前最诚实的结论

这轮新增价值应记成：

> repo-local retrieval widened-doc-set matched diagnostic artifact

它现在支持的说法是：

1. current retrieval
   已经不只摆脱了当前 tags / 当前 hinted docs
   的硬依赖
2. 即使叠加 wrong-family task context
   和 mixed family preferred docs，
   query evidence 仍能把正确 family route 顶出来
3. widened mixed doc set 下的 same-family control
   也都还保留着

它仍然不支持的说法包括：

1. retrieval 已经开放域泛化
2. 更广义 route ambiguity
   或更广义 theme drift
   下都会同样成立
3. deterministic diagnostic artifact
   已足够替代新的 formal matched benchmark
