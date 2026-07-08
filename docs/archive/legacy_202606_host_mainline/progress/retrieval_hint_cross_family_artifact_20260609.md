# Retrieval Hint Cross-Family Artifact 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前
`/home/qcrs/statebus/project`
为 `P1 retrieval` 补上的一层
cross-family weak-hint matched evidence。
它不是新的 formal benchmark，
也不改写当前
`communication` / `state_transfer` / `memory`
三条正式 claim 的边界。

## 1. 这轮为什么值得补

上一轮的
`runs/host_goal_eval_20260609_201200_retrieval_hint_diag_det_r1/`
已经证明：

1. 在 `cache` family 里，
   out-of-hint retrieval 胜出不再依赖当前任务 tags
2. misleading tags 也不足以把 retrieval
   硬拉回 hinted route
3. negative control 仍然成立

但那一层证据仍然停在单一 incident family。
如果只停在这里，
最诚实的说法仍然只能是：

> 当前 weak-hint retrieval 反例主要成立在 `cache` family。

所以这轮最值得补的不是继续改 runtime，
而是把同一组弱 hint 边界扩到多个 repo-local incident family，
先判断它是不是单家族偶然现象。

## 2. 新增 artifact

新包：

- `runs/host_goal_eval_20260609_203500_retrieval_hint_cross_family_det_r1/`

运行形态：

- `task_set = tasks/retrieval_hint_diagnostic_tasks.yaml`
- `repeat = 1`
- `modes = text,protocol`
- `llm_mode = deterministic`

这次的 task set 现在覆盖三个 family：

1. `cache_chain`
2. `latency_chain`
3. `session_chain`

总任务数：

1. `9` 个 task
2. 每个 family 各 `3` 个 task：
   - weak hint without tags
   - weak hint with misleading tags
   - negative control

## 3. 这包现在直接证明什么

### 3.1 这条弱 hint 边界不再只停在 `cache` family

在 `text/protocol` 两侧都成立：

1. `diag-retrieval-no-tags-001`
   - top doc = `cache-replica-false`
   - route = `cache_replica_stale_read`
2. `diag-retrieval-latency-no-tags-001`
   - top doc = `latency-worker-false`
   - route = `worker_queue_starvation`
3. `diag-retrieval-session-no-tags-001`
   - top doc = `session-rate-limit-false`
   - route = `auth_rate_limit`

这说明：

> 当前 out-of-hint retrieval 胜出，
> 已经不只是 `cache` family 的单点样例；
> 在 `latency` 和 `session` family 里，
> 同类弱 hint 边界也能成立。

### 3.2 misleading tags 也不再只在 `cache` family 里被压下去

在 `text/protocol` 两侧都成立：

1. `diag-retrieval-misleading-tags-001`
   仍回 `cache_replica_stale_read`
2. `diag-retrieval-latency-misleading-tags-001`
   仍回 `worker_queue_starvation`
3. `diag-retrieval-session-misleading-tags-001`
   仍回 `auth_rate_limit`

这说明：

> 当前 retrieval refresh 的“query evidence 胜过 misleading tags”
> 也不再只是一条 `cache` family 里的局部现象。

### 3.3 三个 family 的 negative control 都还活着

在 `text/protocol` 两侧都成立：

1. `diag-retrieval-invalidation-control-001`
   仍回 `cache_invalidation`
2. `diag-retrieval-latency-db-control-001`
   仍回 `db_pool_saturation`
3. `diag-retrieval-session-drift-control-001`
   仍回 `auth_session_drift`

这说明：

> 当前 retrieval refresh 还没有塌成
> 某个单一路线的 generic bias；
> 三个 family 的正常负对照都还保留着。

## 4. 当前最诚实的结论

这轮新增价值应记成：

> repo-local cross-family weak-hint matched diagnostic artifact

它现在支持的说法是：

1. weak-hint out-of-hint retrieval 胜出
   不再只停在 `cache` family
2. misleading tags 被更强 query evidence 压下去
   也不再只停在单一 family
3. 三个 family 都保留了自己的 negative control

它仍然不支持的说法包括：

1. retrieval 已经开放域泛化
2. 任意更弱 hint 或任意更弱 doc-set 下都会同样成立
3. deterministic diagnostic artifact
   已足够替代新的 formal matched benchmark

## 5. 这轮之后 `P1 retrieval` 的位置

这轮之后，
`P1 retrieval` 的 honest wording
比上一轮又前进了一格：

1. 当前不再只是
   “`corpus_doc_ids` 和当前 tags 不是硬依赖”的
   单家族最小反例
2. 而是已经有了
   `cache / latency / session`
   三个 repo-local incident family 的 matched diagnostics

但它仍然还没有前进到：

1. 更广义的 route/theme 泛化
2. formal benchmark headline
3. contest 主 claim 级别的新增结论
