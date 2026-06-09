# Executor Low-Confidence Diagnostic 2026-06-09

日期：`2026-06-09`

适用范围：这份说明只记录当前 `/home/qcrs/statebus/project` 在
`low_confidence_abstain` 加入后，新增的 executor 诊断层证据。它不是新的
contest fairness headline，也不替代当前 `26` 任务 lane benchmark。

## 1. 这轮为什么要补这份诊断

前一轮已经完成了两件事：

1. 在 `runtime/executor_runtime.py` 里加入 `low_confidence_abstain`
2. 通过主线回归证明这步没有打坏 host-mainline

但还缺一个关键证据：

> 当前 `26` 任务 fairness 主线并不会自然命中这条新规则。

也就是说，之前的 deterministic `repeat=1` 包只能证明：

- 没有回归
- claim boundary 更收紧

但还不能证明：

- 这条规则在真实 runtime 的检索路径下真的可触发

## 2. 这轮新增了什么

### 2.1 隔离诊断语料与任务集

新增：

- `tasks/executor_diagnostic_corpus.yaml`
- `tasks/executor_diagnostic_tasks.yaml`

同时给 task 定义补了可选 `corpus_path`，让独立诊断语料不污染当前主
`sample_corpus.yaml` 和 `26` 任务 fairness 主线。

相关代码路径：

- `tasks/sample_tasks.py`
- `runtime/orchestrator.py`
- `agents/sample_agents.py`
- `eval/runner.py`
- `tasks/local_corpus.py`

### 2.2 真实 runtime 诊断包

新增证据包：

- `runs/host_goal_eval_20260609_081303_executor_diag_det_r1/`

这个包只回答 executor 边界问题，不回答 contest 三条主张。

## 3. 这包到底证明了什么

在 text / protocol 两侧都稳定得到同样的 runtime 行为：

1. `exec-low-confidence-001`
   - `feature_route_source = low_confidence_abstain`
   - `tool_name = tool.collect_more_evidence`
2. `exec-metadata-only-001`
   - `feature_route_source = metadata_only_abstain`
   - `tool_name = tool.collect_more_evidence`
3. `exec-ambiguous-001`
   - `feature_route_source = ambiguous_candidates_abstain`
   - `tool_name = tool.collect_more_evidence`
4. `exec-clear-worker-001`
   - `feature_route_source = hint_consensus`
   - `tool_name = tool.worker_queue_triage`

所以当前可以诚实增加的判断是：

> `low_confidence_abstain` 不再只是单测里的静态分支；
> 它已经在真实 retrieval -> feature_bundle -> execute 的 runtime 路径下有独立诊断证据。

## 4. 这包没有证明什么

这包**没有**证明：

1. 当前 `26` 任务 fairness 主线已经自然受益于 `low_confidence_abstain`
2. 当前 contest headline 有新的正式提升
3. 当前 aggregate / lane fairness 结论需要改写

更准确地说：

- 主 fairness 集当前没有自然命中这条分支
- 所以这轮新增的是 executor 边界诊断证据，不是新的主 headline

## 5. 和当前主线证据如何并存

当前证据应该拆成两层：

1. 主 contest / fairness 层
   - 继续看 `26` 任务 lane benchmark
2. executor 诊断层
   - 看这次独立 `executor_diag` 包

两层不要混写。

如果以后主 fairness 任务真的开始自然命中 `low_confidence_abstain`，
那时再把它提升到主线解释层。

## 6. 当前最诚实的结论

这轮 executor 小步现在已经具备两类证据：

1. 主线 no-regression 证据
2. 独立 runtime 诊断命中证据

但仍然还没有：

1. 主 fairness 主线里的自然命中
2. 新 headline gain

所以它当前最合适的定位是：

> 一个更收紧、更可诊断的 executor claim-boundary hardening，而不是新的 benchmark headline。
