# Retrieval Replay Contract Drift Artifact 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前 `/home/qcrs/statebus/project`
把 retrieval / replay `P1` 诊断继续向前推进一小格，
专门补 `exact replay` 的 contract-drift 边界。
它不是新的 formal API 证据，也不改写当前
`communication` / `state_transfer` / `memory`
三条正式 claim 的边界。

## 1. 这轮为什么值得补

上一轮 preserved diagnostic artifact 已经证明：

1. stronger out-of-hint retrieval 可以胜出
2. exact replay 不再依赖当前任务 `corpus_doc_ids`
3. query drift 仍然会挡住 exact replay

但还剩一个没被单独隔离的问题：

> 当前 exact replay 到底还依赖哪些 contract 字段，
> 哪些已经不再是必需条件？

这轮最值得补的不是再改 runtime，
而是把 `tags / reuse_signature` 与 `task_theme`
这两条边界单独落成可复查 artifact。

## 2. 新增 artifact

新包：

- `runs/host_goal_eval_20260609_190500_retrieval_replay_contract_drift_det_r1/`

运行形态：

- `task_set = tasks/retrieval_replay_diagnostic_tasks.yaml`
- `repeat = 1`
- `modes = text,protocol`
- `llm_mode = deterministic`

新增任务：

1. `diag-replay-tag-drift-001`
2. `diag-replay-theme-drift-001`

这包的定位仍然必须写清楚：

1. 它是 retrieval / replay contract-drift diagnostic artifact
2. 它不是 formal API repeat-10 证据
3. 它只回答 replay 边界问题，不回答 headline latency / token claim

## 3. 这包现在直接证明什么

### 3.1 current tags / reuse signature 已不是 exact replay 必需条件

`diag-replay-tag-drift-001` 在 `text/protocol` 两侧都显示：

1. `reuse_mode = skip_retrieve_execute`
2. `retrieve_skipped = True`
3. `execute_skipped = True`
4. reused memory 来自前一个 replay memory，而不是当前任务标签补齐

这说明：

> 当前 exact replay 已经不再依赖当前任务的 `tags`
> 或 `reuse_signature` 才能成立。

### 3.2 task_theme 仍然是 replay 的硬边界

`diag-replay-theme-drift-001` 在两侧都显示：

1. `reuse_mode = none`
2. `retrieve_skipped = False`
3. `execute_skipped = False`
4. 当前 query 仍然保持 invalidation replay 语义，但 exact replay 仍未触发

这说明：

> 当前 replay 候选仍然是 task-theme scoped；
> `task_theme` 漂移仍然会挡住 exact replay。

### 3.3 assist-only 仍然没有被救成 headline

这包仍然保留：

- `diag-replay-no-doc-pref-001`
  - `expected_reuse_mode = assist`
  - `actual_reuse_mode = none`
  - `expectation_match_rate = 0.86`

这继续支持当前 memory 边界：

> `assist_only` 仍然是诊断层对象，不是正式 headline。

## 4. 当前最诚实的结论

这轮新增价值应记成：

> replay contract-drift boundary closure

更具体地说：

1. 当前 exact replay 已经摆脱了当前任务 `corpus_doc_ids`
2. 当前 exact replay 也已摆脱当前任务 `tags / reuse_signature`
3. 但它仍然受 `task_theme` 和 query/evidence gate 约束

它不能支持的说法仍然包括：

1. replay 已经自然泛化
2. task theme 已经不重要
3. deterministic diagnostic artifact 已足够替代新的 formal matched benchmark
