# Retrieval Replay Override Theme Drift Artifact 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前
`/home/qcrs/statebus/project`
为 `P1 replay` 再补的一层
cross-family theme-drift negative control。
它不是新的 formal benchmark，
也不改写当前
`communication` / `state_transfer` / `memory`
三条正式 claim 的边界。

## 1. 这轮为什么值得补

上一轮 cross-family override artifact
已经证明：

1. auth / cache
   两个 family 里，
   `lexical_override`
   provenance 仍然可以触发 replay

但那还只是一组正例。
主线里剩下的更关键问题是：

> 这条 lexical-led provenance gain
> 一旦脱离当前 task theme，
> 会不会像 earlier replay contract drift 一样立刻塌掉？

这轮最值得补的不是再加第三个正例 family，
而是补一组更像 matched benchmark 的
cross-family negative control。

## 2. 新增 artifact

新包：

- `runs/host_goal_eval_20260609_230600_retrieval_replay_override_theme_drift_det_r1/`

运行形态：

- `task_set = tasks/retrieval_replay_override_theme_drift_tasks.yaml`
- `repeat = 1`
- `modes = text,protocol`
- `llm_mode = deterministic`

family 结构：

1. auth family:
   - lexical-override anchor
   - theme-drift exact-replay control
2. cache family:
   - lexical-override anchor
   - theme-drift exact-replay control

## 3. 这包现在直接证明什么

### 3.1 fresh route 继续是 lexical-override，但 replay 仍被 task-theme drift 挡住

两个 drift 任务在 `text/protocol` 两侧都显示：

1. `feature_route_source = lexical_override`
2. `feature_route_provenance = ["lexical", "corpus_metadata_conflict"]`
3. `reuse_mode = none`

并且：

1. auth drift task:
   - `task_theme = executor_override_rate_limit_variant`
2. cache drift task:
   - `task_theme = cache_override_replica_variant`

这说明：

> 当前 replay gate
> 即使面对仍然 lexical-led 的 fresh route，
> 也仍然会在 task-theme drift 下
> 拒绝 exact replay。

### 3.2 lexical-led provenance gain 当前仍是 theme-scoped

把这包和上一轮 cross-family 正例放在一起，
现在能更完整地说明：

1. lexical-led provenance
   当前已经跨到 auth / cache
   两个 family
2. 但它仍然不是 broad replay freedom
3. task-theme drift
   依旧是一个硬 gate

## 4. 当前最诚实的结论

这轮新增价值应记成：

> replay lexical-led provenance matched negative control

它现在支持的说法是：

1. lexical-led provenance
   的 replay gain
   当前仍然是 theme-scoped
2. 这条 theme gate
   当前至少在 auth / cache
   两个 family 上都能复现
3. 当前 replay gain
   更像 cross-family but task-theme scoped reuse，
   不是自然泛化

它仍然不支持的说法包括：

1. task_theme 已经不重要
2. 这已经等价于更广 theme / provenance 的 formal matched benchmark
3. replay 已经自然泛化到更宽任务分布
