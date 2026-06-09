# Retrieval Replay Override Matched Artifact 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前
`/home/qcrs/statebus/project`
为 `P1 replay` 再补的一层
matched-style lexical-led provenance evidence。
它不是新的 formal benchmark，
也不改写当前
`communication` / `state_transfer` / `memory`
三条正式 claim 的边界。

## 1. 这轮为什么值得补

上一轮已经分两步补出了：

1. auth / cache
   两个 family 的
   `lexical_override`
   cross-family 正例
2. auth / cache
   两个 family 的
   theme-drift 负对照

但那两层证据还是分散在两个 preserved artifact 里。
主线里真正还缺的不是再多加一个 family，
而是先把：

1. same-theme exact replay 正例
2. same-route but theme-drift 负对照

收成一个更像 matched benchmark 的
单包 deterministic artifact。

## 2. 新增 artifact

新包：

- `runs/host_goal_eval_20260609_233900_retrieval_replay_override_matched_det_r1/`

运行形态：

- `task_set = tasks/retrieval_replay_override_matched_tasks.yaml`
- `repeat = 1`
- `modes = text,protocol`
- `llm_mode = deterministic`

family 结构：

1. auth family:
   - `diag-replay-override-anchor-001`
   - `diag-replay-override-exact-001`
   - `diag-replay-override-theme-auth-drift-001`
2. cache family:
   - `diag-replay-override-cache-anchor-001`
   - `diag-replay-override-cache-exact-001`
   - `diag-replay-override-theme-cache-drift-001`

稳定性摘要：

1. `text`:
   - `expectation_match_rate = 1.00`
   - `failure_count = 0`
2. `protocol`:
   - `expectation_match_rate = 1.00`
   - `failure_count = 0`

## 3. 这包现在直接证明什么

### 3.1 lexical-led provenance 的 same-theme replay 正例和 theme-drift 负对照，已经进了同一个 matched-style 包

artifact report 显示：

1. `route_source` 分布：
   - `text | lexical_override | 6 | 6`
   - `protocol | lexical_override | 6 | 6`
2. `Memory Reuse Decisions By Mode`：
   - auth exact:
     `diag-replay-override-exact-001 -> skip_retrieve_execute`
   - cache exact:
     `diag-replay-override-cache-exact-001 -> skip_retrieve_execute`
3. 另外两条 theme-drift task
   在 benchmark results 里
   都是 `reuse_mode = none`

这说明：

> 当前 lexical-led provenance replay gain
> 已经不只是“分散的正例 + 分散的负对照”，
> 而是至少在 auth / cache
> 两个 repo-local family 里，
> 形成了一组单包 matched-style deterministic evidence：
> same-theme 时 exact replay 成立，
> theme-drift 时 exact replay 掉回 `none`。

### 3.2 这条 gain 仍然是 theme-scoped，而不是 broader replay freedom

这包里四条关键 task
都继续保持：

1. `feature_route_source = lexical_override`
2. `feature_route_provenance = ["lexical", "corpus_metadata_conflict"]`
3. `matched_expectation = true`

但 exact replay 只在
same-theme task 上成立。
一旦 `task_theme` 漂移成 variant：

1. auth drift:
   - `reuse_mode = none`
2. cache drift:
   - `reuse_mode = none`

这说明：

> 当前 replay gate
> 对 lexical-led provenance 的支持
> 已经至少有了 auth / cache
> 两个 family 的 matched-style 单包证据，
> 但它仍然明显受 `task_theme`
> 这种 runtime contract gate 约束。

## 4. 当前最诚实的结论

这轮新增价值应记成：

> replay lexical-led provenance matched-style deterministic closure

它现在支持的说法是：

1. `lexical_override`
   / `["lexical", "corpus_metadata_conflict"]`
   这条 lexical-led provenance
   已经至少在 auth / cache
   两个 family 上形成了单包 matched-style evidence
2. same-theme exact replay 正例
   和 theme-drift 负对照
   现在已经在同一个 preserved artifact 里
3. 当前 replay gain
   仍然是 task-theme scoped reuse，
   不是 broad replay freedom

它仍然不支持的说法包括：

1. 更广 theme 下 replay 已经自然成立
2. 更宽 route-evidence provenance
   已经有 matched benchmark
3. 这已经等价于新的 formal memory headline
