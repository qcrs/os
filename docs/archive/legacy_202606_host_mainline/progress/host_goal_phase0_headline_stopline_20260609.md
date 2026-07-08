# StateBus Host Goal Phase-0 Headline And Stop-Line 2026-06-09

日期：`2026-06-09`

适用范围：这份短 note 只服务当前
`/home/qcrs/statebus/project`
执行 `goal.md` 的阶段 0。
它不新增 benchmark，不扩张 claim，只把当前
headline 与 stop-line 固定下来，作为后续 retrieval / executor /
replay / benchmark split 串行推进的入口。

## 1. 当前 headline

当前最应该固定的 headline 只有三条：

1. `communication`
   - 已成立
   - 当前正式包应读：
     - `runs/host_goal_eval_20260609_085938_text_brief_fidelity_api_repeat10_serial/`
2. `state_transfer`
   - 真实性成立
   - 当前只能正式写成：
     - `protocol text_brief handoff to executor`
       对
     - `protocol state_ref handoff`
   - 当前不能再直接写成：
     - `state_ref` 已证明更低开销
3. `memory`
   - 只成立到：
     - `replay_enabled / step-skipping reuse`
   - `assist_only` 仍不能写成当前 headline

这三条之外，当前不应再把 aggregate 或旧 `18` 任务 replay-aware formal 包
混写成统一结论。

## 2. 当前 stop-line

当前最需要明确停住的线也只有三条：

1. 不继续把 `assist_only` 当 headline 追
2. 不继续默认往 executor 主线叠 mechanism hardening
3. 不把 Docker / openEuler VM / `nsjail` / hidden-state/KV 传递拉回当前主线

## 3. 当前最直接的执行含义

对后续阶段，当前最直接的执行含义是：

1. retrieval 可以继续做更诚实的小候选生成与 rerank 收口
2. executor 只保留已经证明有价值的 claim-boundary / observability closure
3. 每一阶段都要补：
   - progress note
   - API spot-check
   - retain / revert decision

## 4. 当前引用基线

当前阶段 0 的控制性基线是：

1. `docs/progress/benchmark_fairness_audit_20260608.md`
2. `docs/progress/structured_vs_text_claim_surface_report_20260609.md`
3. `docs/progress/host_mainline_problem_map_20260609.md`
4. `docs/progress/host_mainline_next_step_decision_20260609.md`
5. `runs/host_goal_eval_20260609_085938_text_brief_fidelity_api_repeat10_serial/benchmark_report.md`

## 5. 当前最诚实的阶段 0 结论

当前阶段 0 应记成：

> headline / stop-line closure

而不是：

1. 新主张扩张
2. 新 benchmark headline
3. 新机制改造起点
