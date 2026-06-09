# Text Brief Executor Fidelity Formal Refresh 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录 `text_brief executor fidelity` 收紧之后，
当前 `/home/qcrs/statebus/project` 的正式 `serialized API repeat=10`
lane evidence 更新。它回答的是：

> 在把 text-side brief 收紧成更完整的 executor handoff 之后，
> 当前 host-mainline 的 formal `state_transfer` claim 是否仍成立，
> 以及它应当怎样被更诚实地表述。

它不是新的 broad performance headline，也不改写 `memory` 的边界。

## 1. 这轮正式包是什么

新的 formal 包：

- `runs/host_goal_eval_20260609_085938_text_brief_fidelity_api_repeat10_serial/`

这包是在上一轮 `text_brief` fidelity 收紧之后，对当前 `26` 任务
host-mainline 重新做的 serialized live API `repeat=10`。

完成状态：

- `text`：`run_count = 10`，`failure_count = 0`
- `protocol`：`run_count = 10`，`failure_count = 0`
- 两侧继续保持 `expectation_match_rate = 1.00`

因此它现在可以作为当前 worktree 的正式 lane evidence，而不是 direction check。

## 2. 和旧 formal 包相比，真正变化了什么

对照旧 formal 包：

- `runs/host_goal_eval_20260608_230711_26task_api_repeat10_serial/`

最关键的变化在 `state_transfer` text-side baseline：

- 旧 formal：
  - `handoff_textual_bytes = 1315.27`
  - `llm_total_tokens = 1117.20`
  - `task_ms = 4393.87`
- 新 formal：
  - `handoff_textual_bytes = 1725.00`
  - `llm_total_tokens = 1116.07`
  - `task_ms = 4840.01`

这说明：

1. text-side brief 现在确实更完整了
2. 它的 textual handoff 成本明显上升
3. `state_transfer` 的 text baseline 因而更诚实，而不是更便宜

更重要的是，`protocol` side 并没有跟着失真：

- `handoff_textual_bytes = 738.00`
- `handoff_nontext_bytes = 1704.67`
- `llm_total_tokens = 698.53`
- `task_ms = 3804.30`

所以 `state_transfer` 的正式判断仍然成立：

> 相对于当前更完整的 `text brief handoff` baseline，
> `state_ref` handoff 仍然更适合非文本 executor input，
> 并且 protocol side 仍保持更低的 control bytes、LLM tokens 和 task time。

## 3. 哪些 headline 没有被改写

### 3.1 `communication`

仍然成立，没有出现需要回退的信号：

- 新 formal：
  - `control_bytes = 5838.25 -> 4944.60`
  - `llm_total_tokens = 1140.25 -> 727.70`
  - `task_ms = 5133.40 -> 3907.84`

### 3.2 `memory`

边界没有变强，甚至更该继续收紧：

- `assist_only`
  - text：`5032.21`，慢于 `memory_off = 4964.08`
  - protocol：`3916.17`，慢于 `memory_off = 3868.85`
- `replay_enabled`
  - text：`4567.17`
  - protocol：`3836.18`

因此现在仍只能写：

> `memory` 成立到 `replay_enabled / step-skipping reuse`，
> `assist_only` 仍不能写成已优于 `memory_off`。

## 4. 当前最诚实的 formal wording

当前 `state_transfer` 的正式口径应更新成：

> 当前 `state_transfer` claim 仍成立，但它比较的是
> `text brief handoff to executor` 对 `state_ref` handoff。
> 在把 text-side brief 收紧成更完整的 executor handoff 之后，
> 这条 claim 仍然成立，而且 text baseline 现在比旧 formal 包更诚实。

不该写成：

- “state_transfer headline 更强了”
- “protocol 优势因为这轮优化又扩大了”
- “所有纯文本中间态 baseline 已被全面替代”

## 5. 这轮之后的结论

这轮最有价值的新增点不是新的 headline gain，而是：

> 当前 host-mainline 的 `state_transfer` formal evidence
> 已经不再依赖一个偏轻的 text-side brief baseline；
> 即使把 text brief 收紧成更完整的 executor handoff，
> scoped `state_transfer` claim 仍然成立。

这属于：

- benchmark fairness closure
- claim-surface hardening

而不是：

- 新的性能 headline
- `memory` 边界扩张
- 更大范围的架构结论改写
