# API Repeat-3 Readout 2026-06-15

适用范围：`/home/qcrs/statebus/runs/api_smoke_then_v3_20260615_104805/v3_api_repeat3_suite/`

这份 memo 只收口这次 serialized API `repeat=3` 结果里当前可以说什么、还不能说什么，以及一个容易误读的 failure 口径修正点。

## 1. 这次结果可以直接说什么

1. host-side regression gates 都通过了：
   - `py_compile`
   - `full_pytest`
   - `runtime_smoke`
   - `open_system_comparison_v1`
   - `pure_text_open_baseline_v1`

2. `contest_dual_mode_controlled_v3` 本轮没有运行失败：
   - `text failure_count = 0`
   - `protocol failure_count = 0`
   - `whole-lane text guard pass rate = 1.00`
   - `hidden field leak rate = 0.00`
   - `object parity gate = pass`

3. `contest_dual_mode_controlled_v3` 当前 `repeat=3` 结果下：
   - `protocol` 相比 `text` 控制面字节更低
   - `protocol` 相比 `text` 端到端 `task_ms` 略低
   - 但 `protocol` 的 `llm_total_tokens` 更高
   - 所以现在可以说“control bytes 降了、端到端略快”，不能说“所有成本都稳定下降”

4. `typed_state_mechanism_v3` 仍然支持当前最核心的机制说法：
   - minimal typed packet 被真实生产、传递、消费
   - executor 看到的是 `DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET`
   - 这条读法仍应独立于 dual-mode headline

5. `memory_reuse_v3` 和 `memory_policy_controlled_v3` 继续成立：
   - protocol-only replay proof 还在
   - `memory_policy_controlled_v3` 的 replay evidence gate / replay headline gate 都是 `pass`

6. 两个 open surfaces 都工作正常：
   - `open_system_comparison_v1`
   - `pure_text_open_baseline_v1`
   - 它们都应继续读成 open/audit surface，不进 formal v3 headline

## 2. 这次结果还不能说什么

1. 还不能把 `contest_dual_mode_controlled_v3` 说成最终 formal headline 已闭合。
   - 当前 manifest 仍然是 `withheld=contest_formal_coverage_incomplete`
   - `formal_stability_gate` 也还不是 pass

2. 还不能把 external pure-text baseline 提升成 formal dual-mode headline。
   - `pure_text_open_baseline_v1` 仍然只是 audit-only external surface

3. 还不能把 `typed_state_mechanism_v3` 读成：
   - text-vs-protocol fairness 结论
   - richer typed state visibility 结论
   - replay proof

4. 还不能把当前 `repeat=3` 结果读成“protocol 在所有指标上稳定优于 text”。
   - 当前只看到 control bytes 更低、task_ms 略低
   - 总 token 没有一起下降

## 3. failure 口径修正

这次最容易被误读的是 `typed_state_consumer_sensitivity_v3`。

表面现象：
- summary 里 `protocol failure_count = 3`

实际含义：
- 一共 3 个 repeat run
- 每个 run 都包含 5 个故意删掉 `EXECUTOR_DECISION_PACKET` 的 negative-control rows
- 这些 rows 预期就应该失败
- 典型错误是：
  - `SchemaValidationError: step execute missing required input kinds ... EXECUTOR_DECISION_PACKET`

因此正确读法应当是：
- 这是“expected negative-control failures”
- 它们说明 destructive control 生效
- 不应和真正的 unexpected runtime failure 混为一类

## 4. 当前最值得保留的简短口径

> 这次 serialized API `repeat=3` 已经证明当前 host-mainline 能稳定跑通 active v3 packs 和新增 open surfaces。formal dual-mode 面上，strict pure text guard 和 object parity 继续成立，protocol minimal packet 在控制面字节上更低，端到端耗时也略低，但总 token 没有同步下降，因此当前仍应把 headline 收口为“受控主面继续成立、coverage/stability 尚未最终闭合”，而不是“全面稳定胜出”。
