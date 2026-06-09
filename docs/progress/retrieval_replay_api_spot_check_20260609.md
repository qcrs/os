# Retrieval Replay API Spot-Check 2026-06-09

日期：`2026-06-09`

适用范围：这份短 note 只记录当前
`/home/qcrs/statebus/project`
围绕 retrieval / replay diagnostic surface 做的一次 live API spot-check。
它不是新的 formal benchmark，也不改写当前
`communication` / `state_transfer` / `memory`
三条正式 claim 的边界。

## 1. 这轮为什么要补

当前 replay 线已经有多份 deterministic diagnostic artifact，
但按 `goal.md`，这一阶段还缺一轮 live API spot-check，
来决定：

1. 当前 replay gate 的正向边界是否仍成立
2. 当前 replay 线的 stop-line 是否也会在 live API 路径下继续出现

## 2. 这轮 spot-check 是什么

本轮 live API 包：

- `runs/host_goal_eval_20260609_174155_retrieval_replay_diag_api_r1/`

任务集：

- `tasks/retrieval_replay_diagnostic_tasks.yaml`

完成状态：

1. `text`：`failure_count = 0`
2. `protocol`：`failure_count = 0`
3. 但两侧 `expectation_match_rate = 0.88`

这说明：

1. 当前 replay diagnostic 任务集没有跑坏
2. 但它也没有在 live API 路径下变成“全部期待都成立”

## 3. 这轮直接证明了什么

在 text / protocol 两侧，下面这些边界继续成立：

1. `diag-retrieval-out-of-hint-001`
   - `reuse_mode = none`
   - `retrieved_doc_ids = [cache-replica-false, cache-invalid-anchor]`
   - `tool.replica_stale_read_triage`
2. `diag-replay-validated-001`
   - `reuse_mode = skip_execute`
3. `diag-replay-no-doc-pref-002`
   - `reuse_mode = skip_retrieve_execute`
4. `diag-replay-tag-drift-001`
   - 仍然 `skip_retrieve_execute`
5. `diag-replay-query-drift-001`
   - 回到 `none`
   - fresh path 再次落到 replica-lag route
6. `diag-replay-theme-drift-001`
   - 回到 `none`
   - 说明 `task_theme` 仍然是 replay 硬边界
7. `diag-replay-validated-docset-drift-001`
   - 回到 `none`
   - 说明 same-route 但 fresh doc-set drift
     仍然会挡住 validated replay

所以当前 live API 路径下仍然成立的是：

> replay gain 继续主要建立在
> validated replay / exact replay
> 的 tight runtime evidence gate 上。

## 4. 这轮暴露了什么 stop-line

这轮最重要的负信号是：

1. `diag-replay-no-doc-pref-001`
   - `expected_reuse_mode = assist`
   - `actual_reuse_mode = none`
   - 两侧都一致

而且从 task-level artifact 直接可见：

1. 它确实命中了 memory hit
2. 但当前 worktree 仍然把这次 assist 拒掉
3. fresh retrieval / execute 继续走正常 invalidation 路径

这不是 crash，也不是 benchmark artifact 写坏；
它更像当前 worktree 在 live API 路径下继续保留的 stop-line：

> `assist_only` 仍然不是当前 replay 线里应该默认期待成立的正向 headline。

## 5. retain / stop decision

当前决策是：

> retain replay gate, retain the stop-line

更具体地说：

1. 保留当前 exact replay / validated replay 的 gate
2. 保留 query drift / theme drift / doc-set drift 的拒绝边界
3. 不把 `diag-replay-no-doc-pref-001` 的 assist miss
   硬修成当前主线正向收益

原因：

1. live API 下的 exact / validated replay 边界仍然站得住
2. 当前唯一明显没达成的是 assist expectation
3. 这和当前 broader problem map 一致：
   - `assist_only` 继续只是诊断层对象
   - 不该为了 headline 再去硬推 assist 主线

## 6. 当前最诚实的结论

这轮应记成：

> replay diagnostic surface retained after live API spot-check,
> with the assist-only stop-line preserved

而不是：

1. replay 线已经全部 expectation clean
2. assist-style replay 已经可以升级为当前主线亮点
3. 当前 replay 阶段还应该继续默认做 mechanism expansion
