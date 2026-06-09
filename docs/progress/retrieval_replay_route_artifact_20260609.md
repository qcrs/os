# Retrieval Replay Route Artifact 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前
`/home/qcrs/statebus/project`
为 `P1 replay` 再补的一层
route-eligibility diagnostic evidence。
它不是新的 formal benchmark，
也不改写当前
`communication` / `state_transfer` / `memory`
三条正式 claim 的边界。

## 1. 这轮为什么值得补

前面的 replay artifact 已经证明：

1. query/theme/doc-set/candidate ordering
   仍然会影响 replay gain
2. replay 继续更像 tight runtime evidence gate

但 problem map 里还剩一层没有单独钉死：

> 当前 replay gate 对“更弱 route / route provenance”
> 到底敏感到什么程度？

这轮最值得补的不是再改 runtime，
而是先把 `generic_triage / low_confidence_abstain`
 和 clear route 的对照补成独立 artifact。

## 2. 新增 artifact

新包：

- `runs/host_goal_eval_20260609_131600_retrieval_replay_route_det_r1/`

运行形态：

- `task_set = tasks/retrieval_replay_route_diagnostic_tasks.yaml`
- `repeat = 1`
- `modes = text,protocol`
- `llm_mode = deterministic`

任务结构：

1. `diag-replay-route-weak-anchor-001`
2. `diag-replay-route-weak-exact-001`
3. `diag-replay-route-clear-anchor-001`
4. `diag-replay-route-clear-exact-001`

## 3. 这包现在直接证明什么

### 3.1 weak route 仍然不是 exact replay eligible

`diag-replay-route-weak-exact-001`
在 `text/protocol` 两侧都显示：

1. `reuse_mode = none`
2. `feature_route = generic_triage`
3. `feature_route_source = low_confidence_abstain`
4. `reused_from_memory_id = None`

而它前一个 anchor
`diag-replay-route-weak-anchor-001`
也保持同样的弱 route 状态。

这说明：

> 即使 query 和 task theme 继续对齐，
> 只要 archived replay route 本身仍停在
> `generic_triage / low_confidence_abstain`，
> exact replay 现在仍然不会误跳。

### 3.2 clear route 仍然保持 exact replay eligible

`diag-replay-route-clear-exact-001`
在 `text/protocol` 两侧都显示：

1. `reuse_mode = skip_retrieve_execute`
2. `feature_route = worker_queue_starvation`
3. `feature_route_source = hint_consensus`
4. `reused_from_memory_id = mem-diag-replay-route-clear-anchor-001-replay`

这说明：

> 当前 replay gate 不只是“exact replay 普遍关得很死”；
> 在 clear-route、route-eligible 的情况下，
> exact replay 仍然会正常触发。

## 4. 当前最诚实的结论

这轮新增价值应记成：

> replay route-eligibility boundary closure

它现在支持的说法是：

1. current replay gate 对弱 route / abstained route
   仍然敏感
2. `generic_triage / low_confidence_abstain`
   replay memory 现在不会被 exact replay 误用
3. clear route replay memory
   仍然保持 exact replay eligible

它仍然不支持的说法包括：

1. replay 已经自然泛化
2. route provenance 已经完全无关紧要
3. deterministic diagnostic artifact
   已足够替代新的 formal matched benchmark
