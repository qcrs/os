# Executor Claim-Boundary API Spot-Check 2026-06-09

日期：`2026-06-09`

适用范围：这份短 note 只记录当前
`/home/qcrs/statebus/project`
围绕 executor claim-boundary hardening 做的一次 live API spot-check。
它不是新的 contest headline，也不等于“executor 已经泛化”。

## 1. 这轮为什么要补

当前 executor 主线已经做过的小步包括：

1. `metadata_only_abstain`
2. `low_confidence_abstain`
3. `lexical_thin_support`
4. `corpus_metadata_conflict + thin override`
5. `ambiguous_candidates_abstain`

此前这些边界已经有 deterministic diagnostic artifact，
但按 `goal.md`，当前阶段还缺一轮 live API spot-check，
来决定这些边界是否值得保留。

## 2. 这轮 spot-check 是什么

本轮 live API 包：

- `runs/host_goal_eval_20260609_174155_executor_diag_api_r1/`

任务集：

- `tasks/executor_diagnostic_tasks.yaml`

完成状态：

1. `text`：`failure_count = 0`
2. `protocol`：`failure_count = 0`
3. 两侧都保持：
   - `expectation_match_rate = 1.00`

## 3. 这轮直接证明了什么

task-level 结果在 text / protocol 两侧一致保持：

1. `exec-low-confidence-001`
   - `route_source = low_confidence_abstain`
   - `route_provenance = ["lexical_below_threshold"]`
   - `tool_name = tool.collect_more_evidence`
2. `exec-metadata-only-001`
   - `route_source = metadata_only_abstain`
   - `route_provenance = ["corpus_metadata_unverified"]`
3. `exec-thin-support-001`
   - `route_source = low_confidence_abstain`
   - `route_provenance = ["lexical_thin_support"]`
4. `exec-conflict-thin-override-001`
   - `route_source = low_confidence_abstain`
   - `route_provenance = ["lexical_thin_support", "corpus_metadata_conflict"]`
5. `exec-ambiguous-001`
   - `route_source = ambiguous_candidates_abstain`
   - `route_provenance = ["lexical_ambiguous"]`
6. `exec-clear-worker-001`
   - `route_source = hint_consensus`
   - `route_provenance = ["corpus_metadata", "lexical"]`
   - `tool_name = tool.worker_queue_triage`

这说明：

1. claim-boundary 分支不再只是 deterministic 单测或本地 artifact
2. 它们已经在真实 retrieval -> feature_bundle -> execute -> summarize
   的 live API 路径下稳定命中
3. clear positive route 也没有被过度 abstain 打坏

## 4. 对主线 headline 的影响

这轮没有改写：

1. `communication`
2. `state_transfer`
3. `memory`

它新增的价值仍然只是：

> executor guardrail
> 在 live API 路径下也成立

不是：

1. 新的 formal contest headline
2. executor gain headline
3. 更大规模 mechanism hardening 的授权

## 5. retain / stop decision

当前决策是：

> retain the current boundary, then stop

更具体地说：

1. 保留现有 claim-boundary hardening
2. 保留现有 observability closure
3. 暂停继续往 executor 主线叠新规则

原因：

1. 当前 guardrail 已有 deterministic + live API 双层证据
2. 当前主 `26` 任务 mainline 没有出现需要继续主线 hardening 的新强证据
3. 再继续叠规则，最容易重新引入：
   - 不必要 abstain
   - fairness 扰动
   - 为了去特化而去特化

## 6. 当前最诚实的结论

这轮应记成：

> executor claim-boundary hardening retained after live API spot-check,
> but not promoted into a new mainline mechanism push

而不是：

1. executor headline gain
2. executor 已经需要继续主线扩张
3. 下一步默认还是 executor mechanism hardening
