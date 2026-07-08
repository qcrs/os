# Phase 5 Benchmark Pack Split 2026-06-09

日期：`2026-06-09`

适用范围：这份短 note 只记录当前
`/home/qcrs/statebus/project`
按 `goal.md` 执行到阶段 5
`Benchmark 双层拆分`
之后，已经落下去的 repo object、
一轮 live API spot-check，
以及当前最诚实的 retain 判断。

它不代表整个 `goal.md` 已完成，
也不把 support-only pack 误写成新的 formal headline。

## 1. 这轮阶段 5 实际补了什么

这轮没有重做 benchmark 核心逻辑，
而是把原先主要停留在口头和 progress note 里的
`Formal Controlled Pack / Open Validation Pack`
拆分要求，落成了 repo 内可执行对象：

1. `tasks/sample_benchmark.yaml`
   - 现在显式带：
     - `task_set.name = formal_controlled_pack`
     - `task_set.pack_type = formal_controlled`
     - `claim_lanes = [communication, state_transfer, memory]`
2. `tasks/open_validation_benchmark.yaml`
   - 新增 support-only open pack
   - 收进了当前最该保留的：
     - retrieval candidate-pool 边界
     - executor abstain / boundary 边界
     - replay route eligibility 边界
3. `tasks/sample_tasks.py`
   - 现在能解析 task-set metadata
   - 支持 named pack alias：
     - `formal_controlled`
     - `open_validation`
4. `eval/runner.py`
   - manifest 和 report 现在会显式写出：
     - `task_set_name`
     - `task_pack_type`
     - `support_evidence_only`
     - `task_set_reading_contract`
   - report 顶部会把：
     - formal pack
     - support-only pack
     的阅读边界直接写出来

这一步新增的价值不是指标本身，
而是：

> benchmark object split
> 从“文档解释”变成了
> “repo 内可以直接调用、直接归档、直接防误读”的对象层约束。

## 2. 这轮 live API spot-check 是什么

这轮现在已有两层 live API 包：

- `runs/host_goal_eval_20260609_phase5_open_validation_api_r1/`
- `runs/host_goal_eval_20260610_phase5_formal_controlled_api_r1/`

命令形状：

- `python -m eval.runner --task-set open_validation --repeat 1 --llm-mode api ...`
- `python -m eval.runner --task-set formal_controlled --repeat 1 --llm-mode api ...`

直接结果：

1. `open_validation`
   - `text` / `protocol`
     - `failure_count = 0`
     - `expectation_match_rate = 1.00`
   - report 顶部显式写出：
     - `Task set name: open_validation_pack`
     - `Task pack type: open_validation`
     - `Pack boundary: support evidence only ...`
2. `formal_controlled`
   - `text` / `protocol`
     - `failure_count = 0`
     - `expectation_match_rate = 1.00`
   - report 顶部显式写出：
     - `Task set name: formal_controlled_pack`
     - `Task pack type: formal_controlled`
     - `Pack boundary: formal controlled pack ...`
   - 当前 `Contest Benchmark Lanes` 继续直接保留：
     - `communication`
     - `state_transfer`
     - `memory`

所以这轮现在已经不只是：

1. deterministic parser / report pass
2. 本地 doc 说法
3. support-only pack 路径没坏

而是：

> 新的 pack split
> 在 support-only 与 formal controlled
> 两条 live API 路径下都能稳定出 artifact，
> 且两边的阅读边界都已经写进 report surface。

## 3. 当前阶段 5 现在能诚实证明什么

当前能成立的是：

1. repo 内已经有了真正分开的两类 benchmark pack object
2. formal pack 和 support-only pack
   不再只靠外部说明来区分
3. support-only pack
   已经在 live API 路径下完成了 `r1 spot-check`
4. formal controlled pack
   也已经在当前 worktree 下完成了最小 live API `r1` 复核
5. 这会直接降低后续误用风险：
   - 把 retrieval / executor / replay diagnostic task
     混写成 contest headline evidence
   - 或把 formal claim lane 和 support-only note 混成同一层证据

当前仍然不应多说的是：

1. open pack 已经需要 `r3`
2. formal controlled `r1` 已经替代 `repeat=10`
3. phase 5 带来了新的 headline 升级

## 4. retain / next-step decision

当前决策是：

> retain the benchmark-pack split, and treat phase 5 as closed on the current worktree

原因：

1. 它已经落成 repo object，而不是只有 note
2. deterministic targeted tests 已通过
3. `open_validation` live API `r1 spot-check` 已通过
4. `formal_controlled` live API `r1` 也已通过
5. 这一步显著增强了 benchmark object 的诚实性和可审计性，
   即使当前没有任何 headline 指标提升，也值得保留

当前阶段 5 收口后的更自然下一步，
不再是继续改 pack 机制，
而是回到更上层的 host-mainline 总收口判断。

## 5. 当前最诚实的阶段 5 结论

当前阶段 5 应记成：

> benchmark-pack split retained after support-only and formal-controlled live API spot-checks

而不是：

1. 新 formal headline
2. benchmark 全部重做完成
3. 整个 `goal.md` 已完成
