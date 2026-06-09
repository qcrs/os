# Phase 5 Benchmark Pack Borrow List 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只服务当前
`/home/qcrs/statebus/project`
执行 `goal.md` 的阶段 5
`Benchmark 双层拆分`。

它不是新的 formal benchmark，
也不授权把外部 eval framework 搬成当前主线 runtime。

## 1. 当前阶段 5 要解决什么

当前阶段 5 的问题不是 benchmark 完全不可用，
而是：

> `Formal Controlled Pack`
> 和
> `Open Validation Pack`
> 主要还停留在说明层，
> 缺少 repo 内可以直接调用、直接归档、直接防误读的对象层分离。

## 2. 看了什么

### 2.1 `third_party/evals`

看了：

- `third_party/evals/README.md`

这轮最值得借的不是它的 registry / dashboard / dataset 体系，
而是两条更小的组织思路：

1. eval object 应该有明确的 pack / dataset identity
2. report 顶部应该把阅读合同写出来，
   避免不同用途的 eval 被混成一个 headline

### 2.2 当前本地 fairness / lane notes

重点对照：

- `docs/progress/benchmark_fairness_audit_20260608.md`
- `docs/progress/benchmark_lane_handoff_refresh_20260608.md`
- `docs/progress/host_goal_phase0_headline_stopline_20260609.md`

这些 note 已经把：

1. 哪些 lane 服务正式 claim
2. 哪些对象只是 support evidence
3. 为什么 aggregate 不能乱读

说清楚了；
阶段 5 要做的是把这些口径下沉到 task-set / report object 本身。

## 3. 这轮只借什么

当前只借：

1. `evals` 的
   - eval-set identity
   - reading-contract / report-surface 分层
2. 本地 fairness notes 里已经固定的：
   - `communication`
   - `state_transfer`
   - `memory`
   formal lane 口径

## 4. 明确不借什么

当前不借：

1. `third_party/evals` 的运行框架本体
2. 外部 dataset registry
3. 新的 model-graded eval pipeline
4. 用外部 eval harness 替换当前 `eval.runner`

原因：

> 当前阶段 5 要解决的是
> “当前 StateBus benchmark object 如何不再被误读”，
> 不是把 benchmark runtime 换成别的框架。

## 5. defended next action

当前阶段 5 最合理的小步是：

> 在当前 task-set / manifest / report 顶部
> 直接编码
> `formal controlled`
> 和
> `support-only open validation`
> 的对象层边界，
> 再分别做最小 live API `r1` 复核。
