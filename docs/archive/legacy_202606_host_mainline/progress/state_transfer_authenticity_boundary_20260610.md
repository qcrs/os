# State Transfer Authenticity Boundary 2026-06-10

日期：`2026-06-10`

适用范围：

- 当前工作目录：`/home/qcrs/statebus/project`
- 当前 formal pack：`tasks/sample_benchmark.yaml`
- 当前最新 formal repeat 包：
  - `runs/host_goal_eval_20260610_113710_controlled_api_repeat3_serial/`

这份 note 只做一件事：

> 把当前 `state_transfer` 的正式可说边界重新钉死。

它不新增 benchmark，
不把 support-only 对照包升级成 formal，
也不为当前 `state_ref` 负结果做包装。

## 1. 硬结论

当前最新 formal repeat 暴露出来的主问题不是 benchmark 失真，
而是：

1. 当前 `state_transfer` lane 已经相对公平
2. 在这个前提下，当前 `rich state_ref` 没有打出低开销效率优势
3. 它真正打出来的是 `typed non-text handoff` 的机制真实性

因此当前最诚实的口径应改成：

- `communication`：成立
- `state_transfer`：真实性成立
- `state_transfer` 的低开销优越性：暂未成立
- `memory`：只成立到 `replay_enabled / step-skipping reuse`

## 2. 当前 formal lane 实际怎么比

当前 `state_transfer` 已不是早期那种 `text mode vs protocol mode`
坏对照。

它现在固定：

- `mode = protocol`
- `benchmark_lane = state_transfer`
- `memory_policy = memory_off`
- 同任务、同 query、同 doc set

lane 内只改：

- `transfer_strategy = text_brief`
- `transfer_strategy = state_ref`

对应位置：

- `tasks/sample_benchmark.yaml`
- `eval/runner.py`
- `runs/host_goal_eval_20260610_113710_controlled_api_repeat3_serial/benchmark_report.md`

所以它对下面这个问题是有效的：

> 在同一 protocol runtime 内，executor handoff 采用
> `text_brief` 还是 `state_ref`，会产生什么差异？

## 3. 为什么它不能再直接承担“低开销 state_transfer 已成立”

因为当前 `text_brief` 不是普通自然文本交接，
而是明显沿用了我们自己的结构化上游设计。

它更接近：

- `same structured upstream packet`
- rendered as compact text

而不是：

- 普通 agent 自由写的自然语言 handoff

所以当前 formal lane 更接近在比较：

- `rich typed object handoff`
- vs `structured packet textual shadow`

这让 benchmark 本身更受控，
但也让 `text_brief` 变成了一个很强的文本基线。

## 4. 最新 formal repeat 真正说明了什么

来自：

- `runs/host_goal_eval_20260610_113710_controlled_api_repeat3_serial/benchmark_report.md`

当前 protocol-only `state_transfer` 表：

- `text_brief`
  - `control_bytes = 4784.11`
  - `handoff_textual_bytes = 1803.33`
  - `handoff_nontext_bytes = 0.00`
  - `llm_total_tokens = 698.67`
  - `task_ms = 3578.97`
- `state_ref`
  - `control_bytes = 5753.44`
  - `handoff_textual_bytes = 751.00`
  - `handoff_nontext_bytes = 2992.33`
  - `llm_total_tokens = 751.00`
  - `task_ms = 3643.96`
- `delta(state_ref - text_brief)`
  - `control_bytes = +969.33`
  - `handoff_textual_bytes = -1052.33`
  - `handoff_nontext_bytes = +2992.33`
  - `llm_total_tokens = +52.33`
  - `task_ms = +64.99`

这说明：

1. `state_ref` 确实减少了 textual handoff
2. 但它同时引入了更大的 non-text payload 与 control 开销
3. 当前 rich payload 抵消了 textual handoff 的减少
4. 所以当前结果不能再写成“更省”

## 5. 当前到底还能正式 claim 什么

还能正式 claim 的：

1. `typed non-text handoff` 已真实进入 formal path
2. `state_ref` 不是只存在于文档概念里
3. 当前 `state_transfer` lane 已经是 protocol-only handoff compare

当前不能正式 claim 的：

1. `state_ref` 比 `text_brief` 更低 token
2. `state_ref` 比 `text_brief` 更低时延
3. `state_ref` 已代表“真实自然文本协作”的全面优越性

## 6. 后续写作与 benchmark 口径要求

从这份 note 起，后续文档应统一写成：

> 当前 `state_ref` 已证明 typed non-text handoff 的机制真实性，
> 但尚未证明它作为端到端低开销 transfer 方案优于当前强文本基线。

同时保留两个方向分拆：

1. `rich state_ref`
   - 用来证明真实性
2. `lean/minimal state packet`
   - 如果后续要继续争取低开销 headline，应另做更小 payload 的 carrier benchmark

## 7. 一句话收束

当前 formal benchmark 对 `typed handoff is real` 是有效的；
它暴露出的主问题不是 benchmark 不公平，
而是我们拿去承担 low-overhead claim 的 `state_ref` payload 还太重。
