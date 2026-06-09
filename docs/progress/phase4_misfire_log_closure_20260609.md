# Phase 4 Misfire Log Closure 2026-06-09

日期：`2026-06-09`

适用范围：这份短 note 只记录当前
`/home/qcrs/statebus/project`
按 `goal.md` 执行到阶段 4
`Failure / Misfire Log`
之后的收口判断。
它不代表整个 `goal.md` 已完成，也不把阶段 4 扩成新的主线机制改造。

## 1. 这轮阶段 4 实际补了什么

这轮补的不是新的 replay / executor mechanism，
而是最小的 artifact-only misfire 审计层：

1. task YAML 现在可以声明：
   - `expected_route`
   - `expected_route_source`
   - `expected_tool_name`
   - `expected_top_doc_id`
2. `eval/runner.py`
   现在会把 archived route / tool / top-doc 输出重建成
   `artifact_misfire`
3. benchmark report 现在会显式写出：
   - `Misfire Audit`
   - route / route-source / tool-choice / top-doc misfire summary
   - reuse misfire summary

这一步的价值是：

> 给 replay / executor 诊断再补一层
> 可保留、可复查、可引用的证据层，
> 而不是继续靠手工读 task artifact。

## 2. 这轮 live evidence 说明了什么

阶段 4 现在已经有两类 live API 证据可直接复用：

1. replay / misfire 包
   - `runs/host_goal_eval_20260609_181732_phase4_replay_misfire_api_r1/`
2. executor claim-boundary 包
   - `runs/host_goal_eval_20260609_174155_executor_diag_api_r1/`

从这两包合起来读，当前最清楚的结论是：

1. replay misfire report surface 已经能稳定渲染
2. replay 包里声明过的 route / tool / top-doc expectation 都匹配
3. 真正留下来的负信号仍然是 reuse 侧：
   - `diag-replay-no-doc-pref-001`
   - `expected_reuse_mode = assist`
   - `actual_reuse_mode = none`
4. executor claim-boundary 侧已经另有 live API 包证明：
   - `route_source`
   - `tool_name`
   这些 artifact expectation 可以稳定命中

所以阶段 4 现在最诚实的读法是：

> misfire layer retained,
> and the retained stop-line is still assist miss / reuse miss,
> not route/tool artifact instability.

## 3. retain / stop decision

当前决策是：

> retain the misfire log layer, then stop

更具体地说：

1. 保留当前 artifact-only misfire 审计面
2. 保留 replay 包里的 `assist -> none` stop-line
3. 不再为了阶段 4 继续补新的 replay / executor mechanism
4. 不再额外追一包 executor API rerun
   - 因为现有
     `runs/host_goal_eval_20260609_174155_executor_diag_api_r1/`
     已经给了 route-source / tool-choice 的 live coverage

## 4. 这轮顺手修掉的 report 口径问题

阶段 4 在收口时还顺手修掉了一个 report 误导点：

1. 以前 misfire 表里如果某字段根本没有声明 expectation，
   也会显示成 `0.00`
2. 这会把
   “未覆盖”
   伪装成
   “全失配”

现在 benchmark report 会对这类字段显示：

- `n/a`

所以 misfire audit 的表意已经更接近当前阶段 4 的真实用途：

> 只审计 YAML 里明确声明过的 artifact expectation，
> 不把没声明的字段伪装成失败。

## 5. 当前最诚实的阶段 4 结论

当前阶段 4 应记成：

> Phase 4 misfire evidence layer retained after live API validation,
> with assist-only reuse miss preserved as the main stop-line

而不是：

1. replay / executor misfire 已经全部清零
2. `assist_only` 已经可以升级成 headline
3. 阶段 4 还应该继续默认做 mechanism expansion
