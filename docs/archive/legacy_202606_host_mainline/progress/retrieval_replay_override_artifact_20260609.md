# Retrieval Replay Override Artifact 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前
`/home/qcrs/statebus/project`
为 `P1 replay` 再补的一层
lexical-override route-provenance diagnostic evidence。
它不是新的 formal benchmark，
也不改写当前
`communication` / `state_transfer` / `memory`
三条正式 claim 的边界。

## 1. 这轮为什么值得补

上一轮 route artifact 和 provenance contract
已经分别证明：

1. `generic_triage / low_confidence_abstain`
   仍然不会触发 replay
2. metadata-only route
   也不是 replay eligible

但 replay 主线里还剩一个没单独钉死的问题：

> route provenance 的要求
> 只是把 replay gate 收得更死，
> 还是在更宽的
> `lexical + corpus_metadata_conflict`
> 条件下也仍然允许 replay？

这轮最值得补的不是再做 synthetic seeding，
而是用自然任务把
`lexical_override`
这层 provenance 单独变成 preserved artifact。

## 2. 新增 artifact

新包：

- `runs/host_goal_eval_20260609_215400_retrieval_replay_override_det_r1/`

运行形态：

- `task_set = tasks/retrieval_replay_override_tasks.yaml`
- `repeat = 1`
- `modes = text,protocol`
- `llm_mode = deterministic`

任务结构：

1. `diag-replay-override-anchor-001`
2. `diag-replay-override-validated-001`
3. `diag-replay-override-exact-001`

## 3. 这包现在直接证明什么

### 3.1 lexical-override provenance 仍然是 replay eligible

三个任务在 `text/protocol` 两侧都显示：

1. `feature_route = auth_rate_limit`
2. `feature_route_source = lexical_override`
3. `feature_route_provenance = ["lexical", "corpus_metadata_conflict"]`

同时：

1. `diag-replay-override-validated-001`
   达到 `reuse_mode = skip_execute`
2. `diag-replay-override-exact-001`
   达到 `reuse_mode = skip_retrieve_execute`

这说明：

> 当前 replay gate
> 不是只允许
> `hint_consensus`
> 这类最干净的 provenance；
> 只要 route 仍然是 lexical-led，
> 即使 metadata hint 冲突，
> replay 也仍然可以成立。

### 3.2 exact replay 仍沿最近 eligible anchor 复用

`diag-replay-override-exact-001`
在 `text/protocol` 两侧都显示：

1. `reused_from_memory_id = mem-diag-replay-override-validated-001-replay`

而不是最早的 cold anchor：

1. `mem-diag-replay-override-anchor-001-replay`

这说明：

> 在 lexical-override provenance 下，
> exact replay 仍然沿最近 eligible replay memory
> 做 candidate ordering，
> 而不是无视当前 candidate surface。

## 4. 当前最诚实的结论

这轮新增价值应记成：

> replay wider route-provenance closure

它现在支持的说法是：

1. replay gate 当前真正要求的是
   lexical-led route evidence，
   不是必须 `hint_consensus`
2. `lexical_override`
   provenance 现在也能自然触发
   validated / exact replay
3. replay 仍然继续受 recent eligible anchor
   ordering 影响

它仍然不支持的说法包括：

1. replay 已经摆脱 route-evidence alignment
2. 当前 deterministic artifact
   已足够替代更广 theme / provenance 的 matched benchmark
3. replay 已经自然泛化到更宽任务分布
