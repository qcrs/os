# Retrieval Replay Diagnostic Artifact 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前 `/home/qcrs/statebus/project`
把 retrieval / replay `P1` 诊断从测试级覆盖推进到一个保留的
benchmark artifact。它不是新的 formal token / latency 证据，
也不改写当前 `communication` / `state_transfer` / `memory`
三条正式 claim 的边界。

## 1. 这轮为什么继续做

上一轮已经把 retrieval / replay 的最小 diagnostic task set
补进了 repo，并用 `tests/test_smoke.py` 锁住了正向和负向边界。

但如果这些证据只停在测试里，它仍然不够像主线里的可复查 artifact。

所以这轮更进一步的动作不是再改 runtime 机制，
而是跑一个最小 deterministic benchmark 包，把这组 `P1`
边界正式落盘到 `runs/`。

## 2. 新增 artifact

新包：

- `runs/host_goal_eval_20260609_174900_retrieval_replay_diag_det_r1/`

运行形态：

- `task_set = tasks/retrieval_replay_diagnostic_tasks.yaml`
- `repeat = 1`
- `modes = text,protocol`
- `llm_mode = deterministic`

这包的定位必须写清楚：

1. 它是 retrieval / replay diagnostic artifact
2. 它不是 formal API repeat-10 证据
3. 它主要回答边界问题，不回答 live token / latency headline

## 3. 这包现在直接证明什么

### 3.1 stronger out-of-hint retrieval 可以真实胜出

`diag-retrieval-out-of-hint-001` 在 `text/protocol` 两侧都直接显示：

1. `retrieved_doc_ids[0] = cache-replica-false`
2. `feature_route = cache_replica_stale_read`
3. `execute tool = tool.replica_stale_read_triage`

这说明：

> 当前 `corpus_doc_ids` 确实只是弱先验，
> 更强的 hint 外证据已经可以真实改写 retrieval 与 execute 路径。

### 3.2 exact replay 不再依赖当前任务的 doc preference

`diag-replay-no-doc-pref-002` 在两侧都显示：

1. `reuse_mode = skip_retrieve_execute`
2. `retrieve_skipped = True`
3. `execute_skipped = True`
4. `retrieved_doc_ids` 仍然回到 archived replay doc set
5. payload 中没有：
   - `preferred_corpus_doc_ids`
   - `candidate_corpus_doc_ids`

这说明：

> 当前 exact replay 可以在没有当前任务 doc preference 的情况下成立。

### 3.3 exact replay 仍然是受控 replay，不会因 contract 自动误跳

`diag-replay-query-drift-001` 在两侧都显示：

1. `reuse_mode = none`
2. `retrieve_skipped = False`
3. `execute_skipped = False`
4. fresh path 回到 `cache_replica_stale_read`

这说明：

> 当前 exact replay 仍然受 runtime evidence gate 约束；
> 当 query 明显漂移时，它不会因为 contract 允许就自动 skip。

## 4. 这包也暴露了什么

这包还有一个同样重要的负结论：

- `diag-replay-no-doc-pref-001`
  在 `text/protocol` 两侧都出现：
  - `expected_reuse_mode = assist`
  - `actual_reuse_mode = none`
  - report 里因此有 `expectation_match_rate = 0.80`

这不是当前 artifact 的 bug，反而是一个值得保留的信号：

> 即使在这组 retrieval / replay diagnostic 里，
> assist-style reuse 也没有被硬凑成“应当成立”的主线亮点。

它继续支持当前 memory 边界：

> `assist_only` 仍然是诊断层对象，不是正式 headline。

## 5. 当前最诚实的结论

这轮新增价值应记成：

> preserved retrieval / replay diagnostic artifact

而不是：

1. replay 已经自然泛化
2. retrieval 已经脱离 benchmark-shaped 对象
3. deterministic artifact 已经足够替代新的 formal API 证据

它最有价值的地方是：

1. 把 `P1` retrieval/replay 去特化边界正式落到 `runs/`
2. 同时保留正向成立样例和负向 stop-line
3. 让后续如果继续做 weakened-hint matched evidence，
   有一个更稳的本地起点
