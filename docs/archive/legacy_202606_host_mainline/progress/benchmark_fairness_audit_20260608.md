# StateBus Benchmark Fairness Audit

日期：`2026-06-08`

适用范围：这份文档只审计当前 `/home/qcrs/statebus/project` 的 benchmark 设计、证据边界和 host-mainline 下三条赛题主张的可证明性，不把 Docker、openEuler VM、`nsjail`、hidden-state/KV 传递拉回当前主线。

更新说明：

- `2026-06-08 23:07 CST` 之后，新的受控 serialized real API `repeat=10`
  包已经完成：
  - `runs/host_goal_eval_20260608_230711_26task_api_repeat10_serial/`
- 这包把此前的 lane-level `api_r3` direction check 升级成了 formal
  live repeat-10 evidence，并确认：
  - `communication` claim 继续成立
  - `state_transfer` claim 继续成立，但仍必须带 `text brief handoff`
    的 baseline 范围
  - `assist_only` 仍然没有打赢 `memory_off`
- 因此这份审计的最终判断不变，但当前应以 `230711` 包作为最新的
  serialized API lane evidence，而不是只看 `api_r3`

## 1. 最终判断

1. 当前 lane benchmark 已经更新为 `26` 任务：
   - `18` 个 `internal_regression`
   - `2` 个 `communication`
   - `3` 个 `state_transfer`
   - `3` 个 `memory`
2. 旧的 host formal API `repeat=10` 包仍然主要覆盖旧 `18` 任务主链，不能直接替代当前 lane benchmark 的公平性证据；两层证据必须继续分开表述。
3. 当前 benchmark 已经足够公平、清晰，可以进入下一轮 host-mainline 优化；但三条主张的成立强度并不相同。
4. 结构化通信优势现在可以直接成立：
   - `communication` lane 在 serialized live API `repeat=10` 下，
     control bytes `5832.70 -> 4986.00`
   - total tokens `1138.80 -> 747.40`
   - task ms `4705.14 -> 3577.55`
5. 非文本状态传递优势现在也可以成立，但结论必须带范围：
   - 这里比较的是 `text brief handoff` 对 `state_ref` handoff
   - 不是“把所有中间态全文自然语言重述”的无限泛化 baseline
   - 在 serialized live API `repeat=10` 下，`state_transfer` lane 的 text side
     `handoff_nontext_bytes = 0.00`，protocol side `handoff_nontext_bytes = 1704.67`
   - 同时 control bytes `5151.70 -> 4603.43`，tokens `1117.20 -> 698.57`，
     task ms `4393.87 -> 3397.05`
6. 共享记忆复用当前只能成立到“受控 replay / step-skipping reuse”这一级：
   - `replay_enabled` 仍然稳定降低 task time
   - 但 `assist_only` 还没有在当前 live benchmark 上显示出比 `memory_off` 更好的端到端成本
   - 因此现在还不能把 memory claim 写成“开放自然任务上的通用 shared-memory gain”

## 2. 证据边界

代码锚点：

- `tasks/sample_benchmark.yaml`
- `tasks/sample_tasks.py`
- `tasks/local_corpus.py`
- `eval/runner.py`
- `eval/metrics.py`
- `runtime/orchestrator.py`
- `runtime/executor_runtime.py`
- `agents/sample_agents.py`
- `tests/test_smoke.py`

当前主证据包：

- 旧 formal headline：`runs/host_goal_eval_20260608_162206_role_phase_telemetry_refresh/api_repeat10_serial/`
- 新 deterministic lane audit：`runs/host_goal_eval_20260608_26task_lane_audit_det_r1/`
- 早期 live API lane audit：`runs/host_goal_eval_20260608_26task_lane_audit_api_r3/`
- 当前 serialized live API lane formal 包：`runs/host_goal_eval_20260608_230711_26task_api_repeat10_serial/`

当前回归门：

- `python -m pytest -q` -> `56 passed`
- `python -m runtime.smoke` -> 通过，当前 sanity path 已经是 `26` 任务，消息量 `311`

这里的边界必须明确：

1. 旧 `18` 任务 formal API `repeat=10`
   - 适合保留为旧主链 headline evidence
2. 新 `26` 任务 deterministic / API lane audit
   - 适合回答 benchmark fairness、lane 是否隔离、当前三条主张到底成立到什么强度

不能把这两层混写成同一包 formal evidence。

## 3. 这轮 benchmark 修正到底解决了什么

### 3.1 state-transfer baseline 不再偷偷背非文本 state

当前 `text_brief` 路径只保留：

- `DENSE_EVIDENCE`
- `TOOL_ARTIFACT` brief

不再额外生成：

- `FEATURE_BUNDLE`
- `EMBEDDING`

而 `state_ref` 路径继续保留：

- `DENSE_EVIDENCE`
- `FEATURE_BUNDLE`
- `EMBEDDING`

这一步修掉了原先“text baseline 平白创建不会被 executor 消费的 non-text state”的不公平点。

### 3.2 state-transfer 指标改成读 executor handoff

当前新增并正式使用的指标：

- `handoff_ref_count`
- `handoff_bytes`
- `handoff_textual_ref_count`
- `handoff_textual_bytes`
- `handoff_nontext_ref_count`
- `handoff_nontext_bytes`

这让 report 不再把“任务里总共创建了多少 state”误读成“真正交给 executor 的 transfer 成本”。

### 3.3 state-transfer lane 不再只有一个 cache 任务

当前 `state_transfer` lane 已扩成三个主题：

- `transfer-cache-001`
- `transfer-latency-001`
- `transfer-session-001`

因此这条线已经不再只是单任务 demo。

### 3.4 report 解释口径被收紧

当前 report 已经明确要求：

- aggregate 只能做总览，不能做 isolated claim
- `state_transfer` 应优先读 handoff 指标
- text side baseline 是 `text brief handoff to executor`

这满足了 goal 里对 baseline 定义不能混用的要求。

## 4. 当前 benchmark 的公平性与解释力

### 4.1 communication lane 现在是合理的

隔离变量做得对：

- `runtime_reuse_contract = reuse_disabled`
- `memory_query_count = 0`
- `skipped_step_count = 0`
- 两侧都不混 memory reuse

因此它现在确实在回答“结构化控制面是否更轻”。

在 serialized live API `repeat=10` 下：

- control bytes：`5832.70 -> 4986.00`
- total tokens：`1138.80 -> 747.40`
- task ms：`4705.14 -> 3577.55`

当前判断：

> `communication lane` 已经能直接支撑“低开销结构化通信”。

### 4.2 state_transfer lane 现在足够干净，但结论必须带范围

这条线现在回答的是：

> 如果 text side 通过 executor-targeted text brief 传递，而 protocol side 直接传 `state_ref`，谁更省、谁能更直接传非文本中间态。

在 serialized live API `repeat=10` 下：

- text side：
  - `handoff_textual_bytes = 1315.27`
  - `handoff_nontext_bytes = 0.00`
- protocol side：
  - `handoff_textual_bytes = 738.00`
  - `handoff_nontext_bytes = 1704.67`

同时：

- control bytes：`5151.70 -> 4603.43`
- total tokens：`1117.20 -> 698.57`
- task ms：`4393.87 -> 3397.05`

当前判断：

> `state_transfer lane` 现在已经能证明“相对于当前 text-brief baseline，protocol/state-ref handoff 更适合传非文本 executor input，并且总控制面与总时延更低”。

但必须同时保留这句限制：

> 这不是“所有纯文本中间态 baseline 都已经被全面击败”的证明。

### 4.3 memory lane 现在仍然是“受控 replay gain”，不是“开放 assist gain”

当前三档策略区分是成立的：

- `memory_off`
- `assist_only`
- `replay_enabled`

而且行为约束已经通过测试锁住：

- `memory_off` 不查 memory
- `assist_only` 不跳步
- `replay_enabled` 才允许 `skip_execute`

但 serialized live API `repeat=10` 下的端到端结果必须诚实读：

text side：

- `memory_off` task ms：`4513.23`
- `assist_only` task ms：`4583.21`
- `replay_enabled` task ms：`4046.16`

protocol side：

- `memory_off` task ms：`3487.28`
- `assist_only` task ms：`3530.00`
- `replay_enabled` task ms：`3312.57`

因此当前成立的是：

- replay contract 下，step-skipping reuse 有稳定收益

当前还不成立的是：

- assist-style shared memory 已经在自然任务上稳定降低总成本

### 4.4 internal_regression 仍然应该留在 regression 层

这 `18` 个任务仍然承担：

- 主链稳定性
- reject control
- assist
- validated replay
- exact replay

它们继续适合作为：

- host-mainline regression
- replay semantics regression

不应直接被当成单条赛题主张的 formal proof。

## 5. 当前还不能怎么说

1. 不能把 `aggregate` 当成三条主张的统一主证明，因为它仍然混合：
   - internal regression
   - communication
   - state transfer
   - memory
2. 不能把旧 `18` 任务 formal API `repeat=10` 写成当前 `26` 任务 lane benchmark 的完整 formal evidence。
3. 不能把 `state_transfer` 结果写成“完整纯文本中间态 baseline 已被全面替代”；当前更准确的说法是“`text brief handoff` 对 `state_ref` handoff”的 scoped comparison。
4. 不能把 memory 结果写成“shared memory assist 已经普遍更优”；当前更像“replay-enabled step skipping 已经显示稳定收益”。

## 6. 现在是否可以进入下一轮主线优化

可以。

理由不是“所有 claim 都已经完全成立”，而是：

1. 当前 benchmark 已经足够公平，能清楚区分：
   - 哪些 claim 已经成立
   - 哪些 claim 只成立到 scoped wording
   - 哪些 claim 仍然不能夸大
2. 当前 repo 已经留下了：
   - benchmark fairness audit
   - lane refresh doc
   - 新 deterministic evidence
   - 新 live API evidence
   - 回归测试与 smoke 验证
3. 因此下一轮优化可以围绕真正的剩余缺口展开，而不是继续停留在“benchmark 到底在证明什么”的混乱状态。

下一轮如果继续做 benchmark，最值得扩的对象只有一个：

> 让 memory lane 的 assist-style reuse 也能在更自然的跨任务 workload 上产生可辩护的端到端收益。
