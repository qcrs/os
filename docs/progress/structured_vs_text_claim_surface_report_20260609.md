# Structured vs Text Claim-Surface Report Surface 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前 `/home/qcrs/statebus/project`
把已有 benchmark telemetry 更直接整理进 `benchmark_report.md`
的这一小步。它不是新的 formal benchmark，也不改写当前
`communication` / `state_transfer` / `memory` 的正式 claim 边界。

## 1. 这轮为什么值得做

当前 host-mainline 的一个剩余问题不是“缺 telemetry 字段”，而是：

1. 现有 telemetry 已经比早期分析文档更完整
2. 但 report 里还没有把这些字段按 claim-surface 直接整理出来
3. 因此 `fresh_retrieval`、`step_skipping`、`assist_only`、`replay_enabled`
   这些边界仍然太依赖手工翻 CSV / JSON 才能复查

所以这轮最值得做的一步不是再加 runtime 指标，
而是把已有指标更直接地写成 benchmark report 的审计视图。

## 2. 这轮具体改了什么

这轮只动 report/export 层：

1. `eval/runner.py`
   - 新增 `Claim-Surface Audit Views`
   - 在 `benchmark_report.md` 里新增：
     - `Structured-vs-Text By Reuse Axis`
     - `Contest Claim Lane Deltas`
     - `Memory Policy Claim Surface`
2. `tests/test_smoke.py`
   - 补充新的 benchmark report 回归断言

这些表全部复用已有的：

- `reuse_axes`
- `benchmark_lanes`
- `memory_policies`
- role-level token / phase timing / handoff metrics

没有新增 live telemetry 字段，也没有修改 benchmark runtime 行为。

## 3. 这轮新增的直接价值

这轮最直接的新增是：

> 当前 benchmark report
> 已经能更直接地区分
> `fresh_retrieval` 下的 structured-vs-text 差异、
> `step_skipping` 带来的 replay 影响、
> 以及 `assist_only` 和 `replay_enabled` 的不同 claim 强度。

因此当前主线里的几个判断更容易直接复查：

1. `fresh_retrieval` 更接近结构化通信 / orchestration 本身的差异
2. `step_skipping` 仍然应该读成 communication + replay 的联合结果
3. `assist_only` 仍然只是诊断层，不该直接包装成正式 memory headline

## 4. 当前最诚实的结论

这轮变化应记成：

> structured-vs-text claim-surface reporting closure

而不是：

1. 新的 telemetry invention
2. 新的 performance headline
3. 新的 memory / state-transfer 形式化扩张

如果继续推进，这条线更适合继续做说明层和证据层收口，
而不是为了“再多一点提升”去重开 executor 主机制或 memory assist headline。
