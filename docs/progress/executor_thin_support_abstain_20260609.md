# Executor Thin-Support Abstain 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前 `/home/qcrs/statebus/project` 在
executor tool selection 上做的又一小步 claim-boundary 收紧。它不是新的
benchmark headline，也不改写当前 `communication` / `state_transfer` /
`memory` 的正式结论。

## 1. 这轮补的是什么口

上一轮已经有：

1. `metadata_only_abstain`
2. `ambiguous_candidates_abstain`
3. `low_confidence_abstain`

但还留着一个更窄的问题：

> 在没有 retrieved hint 支撑时，
> 某些 query-only 或极薄 lexical support 的单一路径，
> 仍可能因为分数过线而直接落到具体 playbook。

这会让执行层仍然显得太像
`query/route cue -> direct playbook drop`。

## 2. 代码上具体怎么收紧

这轮只在 `runtime/executor_runtime.py` 的无 hint lexical path 上补了一个
更小的判定：

- direct lexical match 除了要过 `route_confidence` threshold，
  还要满足最小 evidence support
- 如果 route 主要还是靠 query cue 撑起来，而正文证据没有形成足够的
  route-level lexical support，就回退到 `tool.collect_more_evidence`
- 当前这条收紧只作用于无 hint lexical 直落，不扩到
  `hint_consensus` 路径

对应新增的判断结果仍归到：

- `route_source = low_confidence_abstain`

但 provenance 更明确成：

- `route_provenance = ["lexical_thin_support"]`

## 3. 这轮新增了什么诊断证据

新增了一个更窄的 executor 诊断样例：

- `exec-thin-support-001`

对应语料在：

- `tasks/executor_diagnostic_tasks.yaml`
- `tasks/executor_diagnostic_corpus.yaml`

它刻意构造成：

1. query / tags 会把检索拉向 auth-session family
2. retrieved docs 本身仍保持 vague，不提供足够 route-level evidence
3. 结果应该 abstain，而不是直接掉到 `tool.auth_session_repair`

这让当前 executor 诊断层可以多证明一件事：

> 现在被收紧掉的不只是“分数明显不够”的单一路径，
> 还包括“query cue 很强，但正文证据仍然太薄”的单一路径。

## 4. 这轮没有改写什么

这轮**没有**改写：

1. `26` 任务 formal fairness headline
2. `state_transfer` 的 scoped wording
3. `memory` 的当前诚实边界

它仍然只是：

- executor claim-boundary hardening
- abstain discipline tightening

不是：

- 新的性能 headline
- 新的 formal lane gain

## 5. 验证结果

这轮验证包括：

1. 定向 executor / transfer regression
2. `tests/test_smoke.py tests/test_llm_runtime.py`
3. 全量 `python -m pytest -q`
4. `python -m runtime.smoke`

结果：

- 定向回归通过
- `python -m pytest -q tests/test_smoke.py tests/test_llm_runtime.py`
  通过，`54 passed in 160.41s`
- `python -m pytest -q`
  通过，`62 passed in 160.25s`
- `python -m runtime.smoke`
  通过，当前
  - `text`: `memory_hits=48 messages=311 control_bytes=259083 task_ms=3775.63`
  - `protocol`: `memory_hits=48 messages=311 control_bytes=139290 task_ms=3788.31`

## 6. 当前最诚实的结论

这轮最合理的新增判断是：

> 当前 host-mainline 的 executor selection 比上一轮更少允许
> “query cue 撑起的薄支撑 lexical 直落”，
> 更接近一个带明确 abstain 纪律的小候选工具检索层。

但它仍然只是主线去特化的一小步，不足以单独更新 benchmark headline。
