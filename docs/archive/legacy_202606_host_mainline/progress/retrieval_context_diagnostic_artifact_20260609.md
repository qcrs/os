# Retrieval Context Diagnostic Artifact 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前
`/home/qcrs/statebus/project`
为 `P1 retrieval` 再补的一层
wrong-family context matched evidence。
它不是新的 formal benchmark，
也不改写当前
`communication` / `state_transfer` / `memory`
三条正式 claim 的边界。

## 1. 这轮为什么值得补

上一轮的
`runs/host_goal_eval_20260609_203500_retrieval_hint_cross_family_det_r1/`
已经证明：

1. out-of-hint retrieval 胜出
   不再只停在单一 `cache` family
2. misleading tags 也不再只在单一 family 里被压下去
3. 三个 family 的 negative control 都还活着

但那一层证据仍然主要回答：

> 当前 retrieval 是否还依赖
> 当前任务 tags / hinted docs / 单一 family 的弱 hint？

它还没有直接回答另一层剩余缺口：

> 当前 retrieval 到底还在多大程度上依赖
> 同 family 的 `task_group / task_theme / preferred docs`
> 这组 task-context prior？

所以这轮最值得补的不是再改 runtime，
而是把这条边界补成独立 diagnostic artifact。

## 2. 新增 artifact

新包：

- `runs/host_goal_eval_20260609_123900_retrieval_context_diag_det_r1/`

运行形态：

- `task_set = tasks/retrieval_context_diagnostic_tasks.yaml`
- `repeat = 1`
- `modes = text,protocol`
- `llm_mode = deterministic`

这次的 task set 覆盖三组 wrong-family context：

1. `cache` context 里验证 `session` retrieval
2. `session` context 里验证 `latency` retrieval
3. `latency` context 里验证 `cache` retrieval

总任务数：

1. `6` 个 task
2. 每组各 `2` 个 task：
   - one positive route-selection case
   - one same-family control

## 3. 这包现在直接证明什么

### 3.1 wrong-family `task_group / task_theme / preferred docs` 不再是 retrieval 的硬边界

在 `text/protocol` 两侧都成立：

1. `diag-retrieval-session-context-rate-limit-001`
   - task context = `cache_chain` + `repo_local_cache_staleness`
   - preferred docs = `cache-invalid-*`
   - top doc = `session-rate-limit-false`
   - route = `auth_rate_limit`
2. `diag-retrieval-latency-context-worker-001`
   - task context = `session_chain` + `repo_local_auth_session_drift`
   - preferred docs = `session-auth-*`
   - top doc = `latency-worker-false`
   - route = `worker_queue_starvation`
3. `diag-retrieval-cache-context-replica-001`
   - task context = `latency_chain` + `repo_local_latency_triage`
   - preferred docs = `latency-db-*`
   - top doc = `cache-replica-false`
   - route = `cache_replica_stale_read`

这说明：

> 当前 retrieval 已经不再依赖
> 同 family 的 `task_group / task_theme / preferred docs`
> 才能把正确 family 的 route 顶出来。

### 3.2 same-query-family 的 control 仍然成立

在 `text/protocol` 两侧都成立：

1. `diag-retrieval-session-context-drift-control-001`
   仍回 `auth_session_drift`
2. `diag-retrieval-latency-context-db-control-001`
   仍回 `db_pool_saturation`
3. `diag-retrieval-cache-context-invalidation-control-001`
   仍回 `cache_invalidation`

这说明：

> 当前 retrieval 不是单纯“脱离 task context 之后随机漂移”；
> 在 wrong-family context 下，
> 它仍能让真正匹配 query evidence 的 family 内 route 留在顶上。

## 4. 当前最诚实的结论

这轮新增价值应记成：

> repo-local retrieval context-drift diagnostic artifact

它现在支持的说法是：

1. same-family `task_group / task_theme / preferred docs`
   不再是 retrieval 命中的硬依赖
2. wrong-family task context
   也不足以把 retrieval 拉回错误 family
3. 三组 wrong-family context
   都保留了各自的 same-query-family control

它仍然不支持的说法包括：

1. retrieval 已经开放域泛化
2. 任意 route/theme drift 下都会同样成立
3. deterministic diagnostic artifact
   已足够替代新的 formal matched benchmark

## 5. 这轮之后 `P1 retrieval` 的位置

这轮之后，
`P1 retrieval` 的 honest wording
又前进了一小格：

1. 不仅当前任务 tags 和 hinted docs
   不是硬依赖
2. 连同 family 的 `task_group / task_theme / preferred docs`
   也已经不是 retrieval 命中的硬边界

但它仍然还没有前进到：

1. 更广义的 route/theme 泛化
2. formal benchmark headline
3. contest 主 claim 级别的新增结论
