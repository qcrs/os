# Phase 4 Misfire Borrow List 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只服务当前
`/home/qcrs/statebus/project`
执行 `goal.md` 的阶段 4
`Failure / Misfire Log`。

它不是新的 benchmark 结论，
也不要求把外部诊断框架搬进当前 host-mainline。

## 1. 当前阶段 4 要解决什么

当前阶段 4 的核心不是再改 replay / executor 机制，
而是：

> 把 route misfire / tool-choice misfire / false reuse / missed reuse
> 变成可保留、可复查、可引用的证据面。

## 2. 看了什么

### 2.1 `third_party/AgentRx`

看了：

- `third_party/AgentRx/README.md`

最值得借的不是它的整套 pipeline，
而是三条思路：

1. failure object 要能落成可审计轨迹
2. 误判不只看最终 answer，要看 route / step / evidence 对齐情况
3. validation log 应该能复查，而不是只存在人工阅读里

### 2.2 当前本地 diagnostic notes

重点对照：

- `docs/progress/retrieval_replay_diagnostic_surface_20260609.md`
- `docs/progress/executor_tool_selection_borrow_list_20260609.md`
- `docs/progress/executor_low_confidence_diagnostic_20260609.md`

这些本地 note 已经把：

1. retrieval / replay 的 stop-line
2. executor abstain boundary
3. 误判对象类型

说清楚了；
阶段 4 需要做的是把这些对象转成更正式的 artifact 面。

## 3. 这轮只借什么

当前只借：

1. `AgentRx` 的
   - trajectory / failure object
   - auditable validation log
   思路
2. 本地 diagnostic notes 里已经固定下来的：
   - route-source boundary
   - tool-choice boundary
   - assist miss / reuse miss stop-line

## 4. 明确不借什么

当前不借：

1. `AgentRx` 的全套 judge / invariant / pipeline infra
2. 新的外部诊断 runtime
3. 脱离当前 StateBus benchmark artifact 的独立审计平台

原因很直接：

> 当前阶段 4 只需要最小 artifact-only misfire layer，
> 不需要把 host-mainline 变成新的 diagnosis framework。

## 5. defended next action

当前阶段 4 最合理的小步是：

> 让 task YAML 能声明 expectation，
> 让 report 能回放 archived route / tool / doc / reuse mismatch，
> 但不把 live control plane 再扩成新的诊断协议。
