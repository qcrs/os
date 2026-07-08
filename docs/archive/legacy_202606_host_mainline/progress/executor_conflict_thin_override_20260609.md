# Executor Conflict Thin Override 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前 `/home/qcrs/statebus/project` 在
executor tool selection 上又补的一条更窄的 abstain 纪律。它不是新的
benchmark headline，也不改写 `communication` / `state_transfer` / `memory`
 的正式口径。

## 1. 这轮补的是哪一个剩余口子

上一轮已经把无 hint lexical path 的 `thin support` 直落收紧掉了。

但还有一个更窄的剩余口子：

> 当 retrieved hint 已存在、且和 lexical route 冲突时，
> `lexical_override` 仍可能因为 query cue 很强而直接覆盖 hint，
> 即使正文证据其实还不够支撑 route-level override。

这类路径的问题不在于：

1. 完全没有 hint
2. 完全没有 lexical cue
3. top-2 route 明显 close call

而在于：

1. hint 存在
2. lexical cue 也存在
3. 但 lexical side 主要还是 query cue / 薄正文支撑
4. 当前 override 仍可能过早发生

## 2. 代码上具体怎么收紧

这轮只在 `runtime/executor_runtime.py` 的
`lexical_supported + corpus_metadata_conflict` 分支里补了一条和上一轮一致的
`minimum evidence support` 纪律：

1. 如果 lexical route 与 hint 冲突
2. lexical match 虽然过了 score / confidence gate
3. 但 evidence-side support 仍太薄

则不再走：

- `route_source = lexical_override`

而是回退到：

- `route_source = low_confidence_abstain`
- `route_provenance = ["lexical_thin_support", "corpus_metadata_conflict"]`

这一步仍然不碰：

1. `hint_consensus`
2. 已有的 clear lexical path
3. 已有的 ambiguous-candidate abstain

## 3. 这轮新增了什么诊断证据

新增了一个更窄的 executor 诊断样例：

- `exec-conflict-thin-override-001`

对应语料在：

- `tasks/executor_diagnostic_tasks.yaml`
- `tasks/executor_diagnostic_corpus.yaml`

它刻意构造成：

1. retrieved hint 指向 `auth_session_drift`
2. query cue 更像 `auth_rate_limit`
3. retrieved docs 自身仍保持 vague，不提供足够 route-level override evidence

因此当前更诚实的结果应该是：

- abstain to `tool.collect_more_evidence`

而不是：

- 直接 lexical override 到 `tool.auth_rate_limit_triage`

## 4. 这轮没有改写什么

这轮**没有**改写：

1. `26` 任务 formal fairness headline
2. `state_transfer` 的 scoped formal wording
3. `memory` 的当前诚实边界

它仍然只是：

- executor claim-boundary hardening
- abstain discipline tightening

不是：

- 新的性能 headline
- 新的 formal lane gain

## 5. 验证结果

这轮验证包括：

1. 定向 executor regression
2. `text_brief` round-trip regression
3. `python -m pytest -q tests/test_smoke.py tests/test_llm_runtime.py`
4. `python -m runtime.smoke`

结果：

- 定向回归通过
- `python -m pytest -q tests/test_smoke.py tests/test_llm_runtime.py`
  通过，`55 passed in 154.46s`
- `python -m runtime.smoke`
  通过，当前
  - `text`: `memory_hits=48 messages=311 control_bytes=259083 task_ms=3696.90`
  - `protocol`: `memory_hits=48 messages=311 control_bytes=139290 task_ms=3740.57`

## 6. 当前最诚实的结论

这轮最合理的新增判断是：

> 当前 host-mainline 的 executor selection
> 不仅更少允许无 hint 的 query-driven thin lexical 直落，
> 也更少允许 metadata-conflict 场景下的薄支撑 lexical override。

这仍然只是主线去特化的一小步，不足以单独更新 benchmark headline。
