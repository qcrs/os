# Retrieval Candidate-Pool API Spot-Check 2026-06-09

日期：`2026-06-09`

适用范围：这份短 note 只记录当前
`/home/qcrs/statebus/project`
围绕 retrieval candidate-pool refresh 做的一次 live API spot-check。
它不是新的 formal benchmark，也不改写
`communication` / `state_transfer` / `memory`
三条正式 claim。

## 1. 这轮为什么要补

`tasks/local_corpus.py` 的 retrieval
已经从单层总分排序收紧成：

> multi-signal overfetch
> -> small candidate pool
> -> light rerank

此前已经有 deterministic diagnostic artifact：

- `runs/host_goal_eval_20260609_193900_retrieval_candidate_pool_det_r1/`

但按 `goal.md`，当前阶段还缺一轮 live API spot-check，
来回答这步在真实 API 路径下是否值得保留。

## 2. 这轮 spot-check 是什么

本轮 live API 包：

- `runs/host_goal_eval_20260609_174155_retrieval_hint_diag_api_r1/`

任务集：

- `tasks/retrieval_hint_diagnostic_tasks.yaml`

完成状态：

1. `text`：`failure_count = 0`
2. `protocol`：`failure_count = 0`
3. 两侧都保持：
   - `expectation_match_rate = 1.00`

## 3. 这轮直接证明了什么

task-level 结果在 text / protocol 两侧一致保持：

1. `diag-retrieval-no-tags-001`
   - `tool.replica_stale_read_triage`
   - `retrieved_doc_ids = [cache-replica-false, cache-invalid-anchor]`
2. `diag-retrieval-misleading-tags-001`
   - 仍是 `tool.replica_stale_read_triage`
3. `diag-retrieval-invalidation-control-001`
   - 保持 `tool.cache_invalidation_playbook`
4. `diag-retrieval-latency-no-tags-001`
   - 保持 `tool.worker_queue_triage`
5. `diag-retrieval-latency-db-control-001`
   - 保持 `tool.db_pool_triage`
6. `diag-retrieval-session-no-tags-001`
   - 保持 `tool.auth_rate_limit_triage`
7. `diag-retrieval-session-drift-control-001`
   - 保持 `tool.auth_session_repair`

这些结果说明：

1. out-of-hint retrieval 胜出样例在 live API 路径下仍成立
2. misleading tags 仍不足以把候选拉回 hinted doc set
3. 三个 family 的 negative control 也都还在

## 4. 对主线 headline 的影响

这轮没有改写：

1. `communication` headline
2. `state_transfer` scoped wording
3. `memory` 只到 `replay_enabled / step-skipping reuse` 的边界

它新增的价值仍然只是：

> retrieval candidate-generation honesty
> 在 live API 路径下也站得住

## 5. retain / revert decision

当前决策是：

> retain

原因：

1. retrieval refresh 已有 deterministic artifact
2. 现在又补上了 live API spot-check
3. 没有出现把 out-of-hint / negative-control 边界打坏的信号

当前不做的是：

1. 不继续扩大 retrieval 重构范围
2. 不引重型外部 retrieval 框架
3. 不把这步误写成新的 formal headline

## 6. 当前最诚实的结论

这轮应记成：

> retrieval small-candidate-pool refresh retained after live API spot-check

而不是：

1. retrieval 已经开放域泛化
2. retrieval headline 已经升级
3. 当前 formal contest claim 发生改写
