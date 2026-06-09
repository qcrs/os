# Executor Feature Observability 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前 `/home/qcrs/statebus/project` 在
executor / feature-bundle 审计透明度上补的一步。它不是新的 benchmark
headline，也不改写当前 `communication` / `state_transfer` / `memory` 的
正式口径。

## 1. 这轮补的是哪类问题

这轮起点不是新的 executor 误判，而是一个更基础的观测问题：

> retrieve payload 对 `FEATURE_BUNDLE` 的导出不够完整，
> 导致 runtime 审计很难区分
> “真的 metadata-driven 弱共识”
> 和
> “只是 payload 没把 lexical support 带出来”。

具体表现是：

1. fresh retrieve 路径内部已经有
   - `matched_signals`
   - `matched_tags`
   - `match_score`
   - `tool_candidates`
2. 但 retrieve payload 没有显式导出这些字段
3. replay / skip 路径的审计面则更弱

这会让 executor claim-boundary 的判断证据变差。

## 2. 代码上具体补了什么

这轮只做透明度补全，不改 executor 机制本身：

1. `agents/sample_agents.py`
   - retrieve payload 现在显式导出：
     - `feature_matched_signals`
     - `feature_matched_tags`
     - `feature_match_score`
     - `feature_tool_candidates`
2. `runtime/orchestrator.py`
   - `skip_retrieve_execute` replay 回填路径现在会把 archived `FEATURE_BUNDLE`
     里的同一组字段重新带回 retrieve/execute payload
   - `skip_execute` 路径的 execute payload 也不再把 `matched_signals`
     固定写成空

因此当前 replay path 的观测面已经更接近 fresh retrieve path，而不是更弱。

## 3. 这轮新得到的判断

这轮最有价值的新信息其实是一个负判断：

> 当前主线里的 `hint_consensus`
> 并不是“payload 里看起来像 metadata-only，所以大概率真是 metadata-only”。

在把 retrieve payload 的 feature support 导出补齐之后，可以直接看到：

1. `hint_consensus` 主线任务普遍带有非空 `feature_matched_signals`
2. `feature_match_score` 也不是接近零
3. top candidate 与 archived / fresh feature-bundle 是一致的

所以当前最诚实的判断是：

> 先前那次“主线 `hint_consensus` 看起来全是零 lexical support”的审计，
> 主要是在撞到 payload observability 缺口，
> 而不是已经证明 `hint_consensus` 机制本身坏掉。

## 4. 这轮没有改写什么

这轮**没有**改写：

1. executor 的决策规则
2. `26` 任务 formal fairness headline
3. `state_transfer` 的 scoped formal wording
4. `memory` 的当前诚实边界

它属于：

- executor observability hardening
- replay-path evidence transparency hardening

不是：

- 新的性能 headline
- 新的 abstain 规则

## 5. 验证结果

这轮验证包括：

1. 定向 replay / executor / transfer regression
2. `python -m pytest -q tests/test_smoke.py tests/test_llm_runtime.py`

结果：

- 定向回归通过
- `python -m pytest -q tests/test_smoke.py tests/test_llm_runtime.py`
  通过，`55 passed in 159.89s`

## 6. 当前最诚实的结论

这轮最合理的新增判断是：

> 当前 host-mainline 的 executor 审计面比上一轮更完整了；
> fresh retrieve 和 replay 回填路径现在都能把
> `FEATURE_BUNDLE` 的关键支持证据显式导出，
> 所以后续再判断某条 route 是真弱共识还是只是观测面不透明，
> 证据会更硬。

这一步仍然只是主线去特化/审计透明度收紧的一部分，不足以单独更新
benchmark headline。
