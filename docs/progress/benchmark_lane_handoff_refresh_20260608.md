# StateBus Benchmark Lane Refresh

日期：`2026-06-08`

适用范围：记录这轮 benchmark fairness 修正到底改了什么、为什么改、现在应当怎样读取新的 lane evidence。

## 1. 这轮实际改了什么

本轮只改 host-mainline 内与 benchmark fairness 直接相关的部分：

- `agents/sample_agents.py`
- `runtime/orchestrator.py`
- `eval/metrics.py`
- `eval/runner.py`
- `tasks/sample_benchmark.yaml`
- `tests/test_smoke.py`

没有改：

- Docker / openEuler VM
- `nsjail`
- hidden-state / KV 传递
- tool registry 主骨架

## 2. 改动前的关键问题

### 2.1 text-brief baseline 不自然

原先 `transfer_strategy = text_brief` 时：

- executor 只消费 `DENSE_EVIDENCE + TOOL_ARTIFACT`
- 但 Retriever 仍会额外生成 `FEATURE_BUNDLE + EMBEDDING`

结果是：

1. text baseline 平白创建不会被 executor 消费的 non-text state
2. `state_bytes` 里混入了不该算进 handoff 的对象

### 2.2 state-transfer lane 太窄

原先只有：

- `transfer-cache-001`

这只能算最小 demo，不足以做更强的 live evidence。

### 2.3 report 口径会误导

原先更容易被误读成：

- 看总 `state_bytes` 就等于看 transfer 成本

但真正该看的是：

- executor 实际收到什么 handoff

## 3. 这轮具体修正

### 3.1 Retriever 输出按 transfer strategy 收紧

当前行为：

- `state_ref`
  - 输出 `DENSE_EVIDENCE + FEATURE_BUNDLE + EMBEDDING`
- `text_brief`
  - 输出 `DENSE_EVIDENCE + TOOL_ARTIFACT` brief
  - 不再输出 `FEATURE_BUNDLE + EMBEDDING`

### 3.2 新增 executor handoff telemetry

新增字段：

- `handoff_ref_count`
- `handoff_bytes`
- `handoff_textual_ref_count`
- `handoff_textual_bytes`
- `handoff_nontext_ref_count`
- `handoff_nontext_bytes`

采集位置是：

- executor 真正收到 input refs 时

不是：

- Retriever 创建 state 时

### 3.3 state_transfer lane 扩成三个主题

当前 lane 已扩成：

- `transfer-cache-001`
- `transfer-latency-001`
- `transfer-session-001`

因此当前 manifest 变成：

- `18` internal regression
- `2` communication
- `3` state transfer
- `3` memory

总计 `26` 任务。

### 3.4 report 解释边界被固化

当前 report 明确写出：

1. aggregate 混合多 lane，不应用作 isolated claim
2. state-transfer claim 应优先读 handoff metrics
3. text side baseline 是 `text brief handoff to the executor`

## 4. 这轮新增证据

新的 deterministic lane audit：

- `runs/host_goal_eval_20260608_26task_lane_audit_det_r1/`

新的 live API lane audit：

- `runs/host_goal_eval_20260608_26task_lane_audit_api_r3/`

当前回归门：

- `python -m pytest -q` -> `52 passed`
- `python -m runtime.smoke` -> 通过

## 5. 新 evidence 应该怎么读

### 5.1 结构化通信

优先读：

- `Contest Benchmark Lanes` 里的 `communication`
- role-level tokens
- phase timing

### 5.2 非文本状态传递

优先读：

- `Contest Benchmark Lanes` 里的 `state_transfer`
- `State Transfer Strategies`
- `handoff_textual_bytes`
- `handoff_nontext_bytes`

不要优先读：

- aggregate `state_bytes`

### 5.3 共享记忆复用

优先读：

- `Memory Policies`
- `Replay Contract Slice Summary`
- `skipped_step_count`
- `reuse_gain`

不要把：

- assist hit rate
- replay step skip

混成同一个结论。

## 6. 这轮更新后的核心结果

### 6.1 communication lane 现在有更强 live evidence

在 live API `repeat=3` 下：

- control bytes：`5801.50 -> 4848.00`
- total tokens：`1138.33 -> 745.00`
- task ms：`4466.74 -> 3656.13`

### 6.2 state_transfer lane 现在能更直接回答“传了什么”

在 live API `repeat=3` 下：

- text `state_transfer`
  - `handoff_textual_bytes = 1333.78`
  - `handoff_nontext_bytes = 0`
- protocol `state_transfer`
  - `handoff_textual_bytes = 738.00`
  - `handoff_nontext_bytes = 1684.67`

同时：

- control bytes：`5091.67 -> 4543.00`
- total tokens：`1124.78 -> 715.11`
- task ms：`4368.89 -> 3477.67`

这已经明显强于之前的：

- 单任务
- 单次 live repeat
- raw `state_bytes` 口径

### 6.3 memory lane 结果更清楚地显示“assist”和“replay”不是一回事

text side：

- `memory_off` task ms：`4401.01`
- `assist_only` task ms：`4562.10`
- `replay_enabled` task ms：`4020.10`

protocol side：

- `memory_off` task ms：`3543.84`
- `assist_only` task ms：`3591.56`
- `replay_enabled` task ms：`3311.17`

这说明：

- replay-enabled 的收益是稳定的
- assist-only 还没有显示出明确端到端 gain

## 7. 现在剩下的真正缺口

1. 旧 `18` 任务 formal repeat-10 与当前 `26` 任务 lane benchmark 仍然是两层证据，不能混写。
2. `state_transfer` 的当前 baseline 是 `text brief handoff`，不是“完整自然语言重述所有中间态”；对外表述必须带这个范围。
3. memory lane 还不能支撑“shared memory assist 已普遍更优”的更强 claim。

## 8. 当前建议

benchmark 本身现在已经足够清楚，可以暂停继续拆 lane，进入下一轮 host-mainline 优化。

只有在后续目标是增强 memory claim 时，才值得继续补 benchmark；那时最值得做的不是再补更多 replay 标签，而是：

> 设计更自然的跨任务 workload，让 `assist_only` 也能在不跳步的前提下显示真实增益。
