# StateBus Host Goal 26-Task Serialized API Decision

日期：`2026-06-08`

适用范围：这份结论文档只收口当前 `/home/qcrs/statebus/project` 的 host-mainline
终局判断，基于最新一次受控 `serialized real API repeat=10` benchmark，
不把 Docker、openEuler VM、`nsjail`、hidden-state/KV 传递重新拉回当前主线。

## 1. 直接判断

1. 当前实现对象已经是一个**真实可运行、保留四角色语义**的赛题化多 Agent 主线，
   不是“预制任务 + 预制结果回填”的纯脚手架。
2. 它同时也**不是**开放任务上的通用多 Agent runtime 完成态。
   更准确的定位仍然是：
   - host-side contest-shaped runtime
   - `Planner / Retriever / Executor / Summarizer` 四角色都在真实跑
   - `Planner` / `Summarizer` 仍是 live LLM 路径
   - `Retriever` / `Executor` 仍明显受 repo-local corpus 与 playbook family 约束
3. 本轮受控 real API formal evidence 已完成：
   - `runs/host_goal_eval_20260608_230711_26task_api_repeat10_serial/`
4. 基于这包正式结果，当前主线的诚实 claim 边界应收口为：
   - `communication`：成立
   - `state_transfer`：成立，但必须明确 baseline 是 `text brief handoff`
   - `memory`：只成立到 `replay_enabled / step-skipping reuse`
   - `assist_only`：仍不能宣称比 `memory_off` 更优
5. 路线判断：
   - **继续** 当前 host-mainline 总方向
   - **停止** 把 broad assist-style shared-memory gain 当成当前主线 headline
   - 下一轮最值得做的是执行层/tool selection 去特化，而不是继续包装 memory claim

## 2. 回归门与 formal run

当前宿主机回归门：

- `python -m pytest -q`
  - `56 passed`
- `python -m runtime.smoke`
  - 通过

当前 formal benchmark：

- `python -m eval.runner --repeat 10 --modes text,protocol --llm-mode api --out runs/host_goal_eval_20260608_230711_26task_api_repeat10_serial --quiet-progress`

formal run 完成状态：

- `text`：`run_count = 10`，`failure_count = 0`
- `protocol`：`run_count = 10`，`failure_count = 0`
- 两侧都保持 `expectation_match_rate = 1.00`

## 3. 当前对象是否真的符合赛题要求

### 3.1 可以成立的部分

- 至少 `3` 个 Agent：
  - 当前是 `Planner / Retriever / Executor / Summarizer`
- `text` / `protocol` 双模式：
  - 同一任务集、同一 runner、同一 benchmark 报表
- 结构化通信：
  - `protocol` 主线是真实 protobuf control frame，不是“文本外面包一层壳”
- 非文本中间态：
  - 当前主线是真实 `StateRef / FEATURE_BUNDLE / EMBEDDING / DENSE_EVIDENCE`
- 共享记忆：
  - SQLite + FAISS + assist/replay 分层都在实际运行
- 连续任务与 10 轮稳定性：
  - 当前 `26` 任务 formal serialized API `repeat=10` 已完成

### 3.2 必须保留的边界

- 当前对象是**赛题化可运行原型**，不是开放域通用 agent platform
- route / tool 选择仍明显受：
  - repo-local corpus
  - 固定 incident family
  - playbook registry
  约束
- 但这不等于“偏题”：
  - 它仍然在真实运行多角色、检索、执行、总结、共享记忆与状态传递主链
  - 只是 admissible claim surface 需要收窄

## 4. 最新 formal evidence

### 4.1 aggregate

注意：aggregate 混合 `internal_regression / communication / state_transfer / memory`
四条 lane，只能做总览，不应直接当 isolated contest claim。

aggregate `repeat=10`：

| mode | control_bytes | llm_total_tokens | task_ms | memory_hit_rate | skipped_step_count | reuse_gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| text | 150546.10 | 29697.80 | 114984.17 | 0.77 | 10.00 | 0.13 |
| protocol | 129451.30 | 19916.20 | 90001.72 | 0.77 | 10.00 | 0.13 |

当前 aggregate 能支撑的是：

- `protocol` 仍整体更省控制面字节
- `protocol` 仍整体更省 live LLM tokens
- `protocol` 仍整体更快

但不能把这些 aggregate 数字直接写成：

> memory 也因此已经全面优于 text baseline

### 4.2 communication lane

`communication` lane `repeat=10`：

| mode | control_bytes | llm_total_tokens | task_ms |
| --- | ---: | ---: | ---: |
| text | 5832.70 | 1138.80 | 4705.14 |
| protocol | 4986.00 | 747.40 | 3577.55 |

判断：

> 当前 `communication` claim 已经可以直接成立。

### 4.3 state_transfer lane

当前 baseline 必须写清楚：

> 这条线比较的是 `text brief handoff to executor` 对 `state_ref` handoff。

`state_transfer` lane `repeat=10`：

| mode | control_bytes | handoff_textual_bytes | handoff_nontext_bytes | llm_total_tokens | task_ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| text | 5151.70 | 1315.27 | 0.00 | 1117.20 | 4393.87 |
| protocol | 4603.43 | 738.00 | 1704.67 | 698.57 | 3397.05 |

判断：

> 当前 `state_transfer` claim 也可以成立，但必须带 `text brief handoff` 这个范围，
> 不能泛化成“所有纯文本中间态 baseline 都已被全面击败”。

### 4.4 memory policies

`memory` lane / `memory_policy` 结果：

| memory_policy | text task_ms | protocol task_ms | 判断 |
| --- | ---: | ---: | --- |
| `memory_off` | 4513.23 | 3487.28 | 无共享记忆基线 |
| `assist_only` | 4583.21 | 3530.00 | 两侧都仍慢于 `memory_off` |
| `replay_enabled` | 4046.16 | 3312.57 | 两侧都稳定更好 |

判断：

1. `replay_enabled` / step-skipping reuse 是当前真实成立的 memory gain
2. `assist_only` 仍然**没有**在当前 formal live benchmark 上打赢 `memory_off`
3. 因此现在不能把 memory claim 写成：
   - “shared memory assist 已普遍更优”
   - “开放自然任务上的通用 shared-memory gain 已成立”

## 5. 这轮 benchmark 之后的路线判断

### 5.1 继续什么

继续 host-mainline 主线本身。

原因：

1. 当前对象没有偏成 role-elimination fastpath
2. `communication` 与 `state_transfer` 两条赛题主张在正式 live repeat=10 下都成立
3. `memory` 也不是完全失败，而是已经成立到 replay/step-skipping 这一层

### 5.2 停止什么

停止把下面这条写成当前主线 headline：

> assist-style shared memory 已经稳定降低端到端成本

当前正式证据不支持这句。

### 5.3 下一轮最值得做什么

当前最值得继续的是：

> 让执行层从 `route -> playbook` 继续往“小候选工具检索 + threshold / abstain + collect-more-evidence fallback` 方向深化。

原因：

1. 当前最明显的去特化缺口在执行层/tool selection，而不是 benchmark fairness
2. benchmark fairness 已经足够清楚，不值得继续在同一层反复重写
3. 再去硬做 `assist_only` memory headline，更容易落回“为了 claim 去调 benchmark”而不是实质性推进

## 6. 当前可 claim / 不可 claim

### 可以 claim

- 当前是保留 `Planner / Retriever / Executor / Summarizer` 四角色语义的 host-side contest mainline
- `protocol` 相比 `text` 在结构化通信上更省控制开销、更省 live tokens、更快
- `state_ref` handoff 相比当前 `text brief` baseline 更适合非文本 executor input
- shared memory / replay 已经能在受控 replay contract 下产生 step-skipping gain

### 不可以 claim

- 当前已经是开放域通用多 Agent runtime 完成态
- 当前 assist-style shared memory 已经普遍优于 `memory_off`
- 当前 benchmark 已经证明“所有纯文本中间态 baseline 都不如 state_ref”
- 当前 host-mainline 已经覆盖 Docker / openEuler / `nsjail` / hidden-state / KV 传递
