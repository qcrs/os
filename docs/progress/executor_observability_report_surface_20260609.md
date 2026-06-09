# Executor Observability Report Surface 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前 `/home/qcrs/statebus/project`
把 out-of-band `feature_observability` 进一步接到 benchmark report
里的这一小步。它不是新的 benchmark headline，也不改写当前
`communication` / `state_transfer` / `memory` 的正式 claim。

## 1. 这轮为什么要做

上一轮已经把 executor observability 放回了正确位置：

1. 不再污染 live control plane
2. 但仍然保留在 benchmark artifact 里可审计

不过如果这些信息只停在 `benchmark_results.json` 深层 task payload，
当前主线判断仍然太依赖手工翻结果文件。

所以这轮更合适的一步不是继续改 executor 机制，
而是把这组 artifact-only 审计信息直接抬到 `benchmark_report.md`
里，让主线 re-audit 结论可以被更直接地看到。

## 2. 这轮具体改了什么

这轮只改了 report/export 层：

1. `eval/runner.py`
   - 新增 benchmark artifact 级别的 executor observability 汇总
   - 在 `benchmark_report.md` 里新增：
     - `Executor Feature Observability`
     - `Route Source Distribution`
     - `Hint-Consensus Support`
2. `tests/test_smoke.py`
   - 补充 benchmark report 回归
   - 补充 `executor_diagnostic` 报告内容回归

这些统计全部从已有的 out-of-band `feature_observability`
重建，不向 live `StepResult.payload` 增加任何字段。

## 3. 这轮新增的直接价值

这轮最实际的新增不是“executor 更强了”，而是：

> 当前 benchmark artifact
> 已经能直接把 executor 主线的观测面写进 report，
> 不再需要靠手工翻 JSON 才能重建
> `hint_consensus` 的支撑强度和 route-source 分布。

因此当前主线的负判断也更容易被保留：

1. 诊断集里的 abstain boundary 仍可直接读出
2. 主 `26` 任务里的 `hint_consensus` 支撑强度也更容易被复查
3. 这份透明度仍然停留在 artifact/report 层，不影响 fairness

## 4. 当前最诚实的结论

这轮变化应记成：

> artifact-only observability reporting closure

而不是：

1. 新的 executor mechanism hardening
2. 新的 performance headline
3. 新的 formal claim 扩张

如果继续推进，这条线更像是说明层 / 审计层完善，
不是继续往 executor 主机制硬叠规则。
