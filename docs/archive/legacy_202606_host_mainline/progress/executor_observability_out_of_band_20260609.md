# Executor Observability Out Of Band 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前 `/home/qcrs/statebus/project` 对上一轮
executor observability 补丁做的一次重要纠偏。它不是新的 benchmark
headline，也不改写当前 `communication` / `state_transfer` / `memory` 的
正式口径。

## 1. 为什么要纠偏

上一轮把 `FEATURE_BUNDLE` 的更多诊断字段直接加回了 live
`StepResult.payload`，目的是让 runtime 审计更透明。

但这会带来一个更重要的问题：

> `StepResult` 会被 `ctx.emit(result)` 走进 live message path，
> 所以这些 observability 字段会真实抬高 protocol/text control bytes，
> 从而污染当前主 benchmark 的控制面比较。

这不是一个可接受的主线状态，因为：

1. 它会把“审计辅助信息”混进正式通信成本
2. 它会让 `runtime.smoke` / benchmark 的 control bytes 漂移
3. 它会破坏当前 host-mainline 对 fairness 的要求

## 2. 这轮怎么改正

这轮没有删除 observability 需求本身，而是把它从 live path 挪到了
out-of-band 结果导出层：

1. `agents/sample_agents.py`
   - 撤回上一轮加到 retrieve payload 里的：
     - `feature_matched_signals`
     - `feature_matched_tags`
     - `feature_match_score`
     - `feature_tool_candidates`
2. `runtime/orchestrator.py`
   - replay / skip path 也不再把这些字段塞回 live `StepResult.payload`
3. `eval/runner.py`
   - 新增 out-of-band `feature_observability`
   - 它在 benchmark 结果导出阶段，从 `FEATURE_BUNDLE` state 本身读取：
     - route / tool / provenance
     - matched_signals / matched_tags / match_score
     - tool_candidates

所以当前形态变成：

1. live payload 只保留主运行所需字段
2. 诊断字段留在 benchmark artifact 里可审计

## 3. 这轮新得到的判断

这轮最重要的判断不是新的 executor 机制结论，而是一个 fairness 结论：

> executor observability 是值得保留的，
> 但它必须放在 out-of-band artifact 层，
> 不能直接回灌到 live message path。

在这样纠偏之后，两个目标现在可以同时满足：

1. 主 benchmark 的 control bytes 不再被观测字段抬高
2. runtime 审计仍然能在 artifact 里直接看到真实 `FEATURE_BUNDLE` 支撑

## 4. 这轮验证了什么

这轮验证包括：

1. 定向 replay / executor / transfer regression
2. `python -m runtime.smoke`
3. `python -m pytest -q tests/test_smoke.py tests/test_llm_runtime.py`

结果：

- 定向回归通过
- `python -m runtime.smoke`
  再次回到此前量级：
  - `text`: `control_bytes=259083`
  - `protocol`: `control_bytes=139290`
- `python -m pytest -q tests/test_smoke.py tests/test_llm_runtime.py`
  通过，`55 passed in 156.34s`

同时新的 out-of-band audit 也已验证：

- live retrieve payload 不再带新增 observability 字段
- benchmark task result 里的 `feature_observability` 仍能看到
  archived / fresh `FEATURE_BUNDLE` 的完整支持证据

## 5. 当前最诚实的结论

这轮最合理的新增判断是：

> 当前 host-mainline 的 executor 审计透明度仍然比之前更强，
> 但这份透明度现在放回了正确的位置：
> benchmark artifact / result-export 层，而不是 live control plane。

这是一轮 fairness-preserving observability hardening，不是新的性能 headline，
也不是新的 executor 机制胜利。
