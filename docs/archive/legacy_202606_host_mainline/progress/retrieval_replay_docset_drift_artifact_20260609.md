# Retrieval Replay Docset Drift Artifact 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前
`/home/qcrs/statebus/project`
为 `P1 replay` 再补的一层
validated-replay doc-set drift 边界。
它不是新的 formal benchmark，
也不改写当前
`communication` / `state_transfer` / `memory`
三条正式 claim 的边界。

## 1. 这轮为什么值得补

前面的 replay diagnostic artifact 已经证明：

1. exact replay 不再依赖当前任务 `corpus_doc_ids`
2. exact replay 也不再依赖当前任务 `tags / reuse_signature`
3. `task_theme` 与 query drift 仍然会挡住 exact replay

但 replay 主线里还剩下一条没被单独隔离的 gate：

> validated replay 的 `skip_execute`
> 到底是不是也仍然受 fresh retrieved doc set / evidence 约束，
> 还是只要 query/theme/route 对齐就会跳？

这轮最值得补的不是再改 runtime，
而是把这条边界落成可复查 artifact。

## 2. 新增 artifact

新包：

- `runs/host_goal_eval_20260609_125200_retrieval_replay_docset_drift_det_r1/`

运行形态：

- `task_set = tasks/retrieval_replay_diagnostic_tasks.yaml`
- `repeat = 1`
- `modes = text,protocol`
- `llm_mode = deterministic`

这轮新增任务：

1. `diag-replay-validated-docset-drift-001`

它的定位必须写清楚：

1. 它是 replay doc-set drift diagnostic artifact
2. 它不是 formal API repeat-10 证据
3. 它只回答 replay gate 边界问题，不回答 headline latency / token claim

## 3. 这包现在直接证明什么

### 3.1 validated replay 仍然受 fresh doc-set / evidence gate 约束

`diag-replay-validated-docset-drift-001`
在 `text/protocol` 两侧都显示：

1. `reuse_mode = none`
2. `retrieve_skipped = False`
3. `execute_skipped = False`
4. `retrieved_doc_ids = [cache-invalid-anchor, cache-invalid-followup]`

而对照的
`diag-replay-validated-001`
仍然显示：

1. `reuse_mode = skip_execute`
2. `retrieve_skipped = False`
3. `execute_skipped = True`

这说明：

> validated replay 不是只要 query/theme/route 继续对齐就会自动 prune execute；
> 只要 fresh retrieval 落到不同的 same-route evidence/doc-set slice，
> `skip_execute` 现在仍然会被挡住。

### 3.2 replay gain 仍然更像 tight runtime evidence gate

这条新边界和之前几轮拼起来，
现在更完整地说明了：

1. exact replay 已经摆脱了当前任务 `doc preference`
2. exact replay 也已摆脱当前任务 `tags / reuse_signature`
3. 但 validated/exact replay
   仍然受 query/theme/doc-set/evidence 这些 tight gate 约束

## 4. 当前最诚实的结论

这轮新增价值应记成：

> validated replay doc-set/evidence gate closure

它现在支持的说法是：

1. replay gate 不只是看 query/theme/route 名字是否对齐
2. fresh retrieved doc set / evidence slice
   仍然会影响 validated replay 是否可以 prune execute
3. 当前 replay gain 继续更像 tight runtime evidence gate，
   而不是自然泛化的 memory reuse

它仍然不支持的说法包括：

1. replay 已经自然泛化
2. same-route 的 doc-set/evidence 漂移已经无关紧要
3. deterministic diagnostic artifact
   已足够替代新的 formal matched benchmark
