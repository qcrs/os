# Retrieval Weak Route Diagnostic Artifact 2026-06-10

日期：`2026-06-10`

适用范围：这份短文档只记录当前
`/home/qcrs/statebus/project`
为 `P1 retrieval` 再补的一层
weak-route matched evidence。
它不是新的 formal benchmark，
也不改写当前
`communication` / `state_transfer` / `memory`
三条正式 claim 的边界。

## 1. 这轮为什么值得补

上一轮 widened mixed-doc-set artifact
已经证明：

1. wrong-family task context
2. mixed family preferred docs
3. clear enough query evidence

三者叠加时，
正确 family route 仍然能顶出来。

但 problem map 里仍然剩下一层没被单独隔离的问题：

> 一旦 query evidence 变薄，
> 当前 retrieval 到底还会不会重新受
> in-family preferred route
> 明显牵引？

这层边界如果不补，
最容易把当前 retrieval narrate 得过头：

1. 好像 wrong-family context 和 widened doc set
   彻底不重要
2. 但真实情况可能只是：
   clear query evidence 足够强时不重要，
   weak-route 时它们又会回来

所以这轮最值得补的不是再加更强正例，
而是把 weak-route sensitivity
固定成一组 matched diagnostics。

## 2. 新增 artifact

新包：

- `runs/host_goal_eval_20260610_001800_retrieval_weak_route_diag_det_r1/`

运行形态：

- `task_set = tasks/retrieval_weak_route_diagnostic_tasks.yaml`
- `repeat = 1`
- `modes = text,protocol`
- `llm_mode = deterministic`

任务结构：

1. cache family under session-family context:
   - `diag-retrieval-weak-route-cache-invalidation-001`
   - `diag-retrieval-weak-route-cache-replica-001`
2. latency family under cache-family context:
   - `diag-retrieval-weak-route-latency-db-001`
   - `diag-retrieval-weak-route-latency-worker-001`
3. session family under latency-family context:
   - `diag-retrieval-weak-route-session-drift-001`
   - `diag-retrieval-weak-route-session-rate-limit-001`

稳定性摘要：

1. `text`:
   - `expectation_match_rate = 1.00`
   - `failure_count = 0`
2. `protocol`:
   - `expectation_match_rate = 1.00`
   - `failure_count = 0`

## 3. 这包现在直接证明什么

### 3.1 weak route 下，当前 retrieval 的确会重新受 in-family preferred route 牵引

在 `text/protocol` 两侧都成立：

1. cache pair:
   - `diag-retrieval-weak-route-cache-invalidation-001`
     -> top doc = `cache-invalid-anchor`
     -> route = `cache_invalidation`
   - `diag-retrieval-weak-route-cache-replica-001`
     -> top doc = `cache-replica-false`
     -> route = `cache_replica_stale_read`
2. latency pair:
   - `diag-retrieval-weak-route-latency-db-001`
     -> top doc = `latency-db-anchor`
     -> route = `db_pool_saturation`
   - `diag-retrieval-weak-route-latency-worker-001`
     -> top doc = `latency-worker-false`
     -> route = `worker_queue_starvation`
3. session pair:
   - `diag-retrieval-weak-route-session-drift-001`
     -> top doc = `session-auth-anchor`
     -> route = `auth_session_drift`
   - `diag-retrieval-weak-route-session-rate-limit-001`
     -> top doc = `session-rate-limit-false`
     -> route = `auth_rate_limit`

这些成对任务都保持：

1. 同一个 thin family-level query
2. 同一个 wrong-family `task_group / task_theme`
3. 只切换 in-family preferred doc

这说明：

> 当前 retrieval
> 在 clear query evidence 下
> 已经能压过 wrong-family context 和 widened doc set；
> 但一旦 route evidence 变薄，
> route 选择仍然会重新受
> in-family preferred doc
> 明显牵引。

### 3.2 当前 retrieval 的更诚实表述是 “query-strong 时更稳，query-thin 时仍然 family-scoped”

把这包和前面的
wrong-family context / widened mixed-doc-set artifact
放在一起看，
现在能更清楚地区分两件事：

1. clear query evidence:
   - current tags
   - wrong-family context
   - widened mixed preferred docs
   都不再是硬边界
2. weak route evidence:
   - in-family preferred doc
   仍然能把 route 拉向对应 family path

这说明：

> 当前 retrieval
> 已经不是简单的 metadata hard-prune，
> 但它仍然明显是
> repo-local family-scoped evidence router，
> 而不是 broader route-general retriever。

## 4. 当前最诚实的结论

这轮新增价值应记成：

> repo-local retrieval weak-route matched diagnostic artifact

它现在支持的说法是：

1. current retrieval
   在 query evidence 足够清晰时，
   已经能压过 wrong-family context
   和 widened mixed preferred docs
2. 但在 weak-route 条件下，
   route 选择仍然明显受
   in-family preferred doc
   牵引
3. 因此当前 retrieval 的更诚实定位
   是 query-strong more robust，
   query-thin still family-scoped

它仍然不支持的说法包括：

1. retrieval 已经摆脱 repo-local family structure
2. 更广义 theme drift
   下也会同样成立
3. deterministic diagnostic artifact
   已足够替代新的 formal matched benchmark
