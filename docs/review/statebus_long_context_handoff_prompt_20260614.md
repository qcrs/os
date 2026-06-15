# StateBus 长上下文阅读 Prompt

下面这份 prompt 适合交给能读长上下文的新模型窗口。它的目标不是立刻下结论，而是先系统阅读本地材料，再回到今天的审计、质疑与修复计划。

```text
你现在在 `/home/qcrs/statebus/project` 工作。

你的任务不是“帮项目圆回来”，也不是先给泛泛建议。
你的任务是做一次严格、负责任、以赛题要求为硬约束的深度审计预热阅读，然后基于本地文件、代码、tests、benchmark 合同和已有报告，重新分析：

- 当前项目到底做到什么程度
- 离赛题 formal closure 还差什么
- benchmark 设计是否干净
- 当前方法是否存在不公平、不真实、归因不成立、baseline 被做强、claim 混读等风险
- 哪些说法可以保留，哪些必须 withheld
- 下一步应如何收口 benchmark、实验结果分析、实现机制分析和纯文本逻辑

重要边界：

1. 严格以 `docs/reference/题目.md` 为最高约束。
2. 暂时不处理 API repeat=10 测试。
3. 暂时不处理 openEuler VM、Docker、nsjail 的具体实现。
4. 本轮重点只落在：
   - benchmark 设计
   - 实验结果的分析与读法边界
   - 实现机制真实性
   - text / pure-text / external-text 的逻辑与合同
5. 不要把 object existence 当成 hot-path proof。
6. 不要把 audit pack 当 formal headline。
7. 不要把 support pack 当正式证据。
8. 不要把 LangGraph 说成创新主轴，除非代码和 benchmark 真能支撑。

先读目录，再读文件。不要跳过阅读阶段。

第一步：先理解当前 repo 的核心目录

- `docs/`
- `agents/`
- `runtime/`
- `eval/`
- `tasks/`
- `tests/`
- `protocol/`
- `statepool/`
- `memory/`
- `scripts/`
- `runs/`

第二步：先读这些“当前主线约束与赛题源文件”

- `README.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/planning/implementation_plan.md`
- `docs/reference/题目.md`

第三步：再读这些“当前 active review / report / benchmark contract 文件”

- `docs/review/statebus_v3_deep_review_memo_20260613.md`
- `docs/review/statebus_contest_aligned_review_20260614.md`
- `docs/reports/MASTER_PRESENTATION_GUIDE.md`
- `docs/reports/task_design_and_mode_comparison.md`
- `tasks/README.md`
- `tasks/sample_tasks.py`
- `tasks/contest_dual_mode_controlled_v3_benchmark.yaml`
- `tasks/memory_dual_mode_fairness_v3_benchmark.yaml`
- `tasks/typed_state_mechanism_v3_benchmark.yaml`
- `tasks/memory_policy_controlled_v3_benchmark.yaml`
- `tasks/external_text_baseline_audit_v3_benchmark.yaml`
- `tasks/text_definition_audit_v3_benchmark.yaml`

第四步：再读这些“真正定义 hot path 的实现文件”

- `eval/runner.py`
- `runtime/task_profile.py`
- `runtime/orchestrator.py`
- `runtime/executor_runtime.py`
- `runtime/langgraph_adapter.py`
- `agents/sample_agents.py`
- `tests/test_smoke.py`

第五步：如果你还要继续做深读，再按需读这些历史与分析材料，帮助理解为什么当前会变成这样

- `docs/analysis/benchmark_task_and_result_analysis.md`
- `docs/analysis/code_audit_competition_check_and_solution_roadmap.md`
- `docs/analysis/state_transfer_benchmark_audit_20260611.md`
- `docs/planning/state_transfer_benchmark_redesign_20260610.md`
- `docs/planning/state_transfer_dual_formal_design_20260611.md`
- `docs/progress/structured_vs_text_claim_surface_report_20260609.md`
- `docs/progress/state_transfer_authenticity_boundary_20260610.md`
- `docs/progress/text_brief_executor_fidelity_20260609.md`
- `docs/progress/text_brief_executor_fidelity_formal_20260609.md`

第六步：如果需要读历史结果目录，优先只读这些结果的 `SUMMARY.md` / `benchmark_report.md`，不要一开始把所有 runs 全扫完

建议优先看：

- `runs/validation_det_r1_formal_controlled_20260610/`
- `runs/validation_det_r1_state_transfer_authenticity_20260610/`
- `runs/validation_det_r1_memory_20260610/`
- `runs/host_goal_eval_20260609_085938_text_brief_fidelity_api_repeat10_serial/`
- `runs/v3_det10_gate_20260614_152144/`

在完成以上阅读后，再带着下面这些质疑问题去分析：

1. 当前 branch 不是 `main`，worktree 也 dirty，这是否意味着今天的 surface 仍然是活动重构树，而不是稳定交付面？
2. `contest_dual_mode_controlled_v3` 到底在比什么？是只比通信介质，还是 `mode + handoff_object` 一起变？
3. `text_strict_pure_lane` 到底代表什么？它是不是 StateBus runtime 内的 strict text lane，而不是外部传统纯文本多 Agent 系统？
4. `text_whole_lane` 到底代表什么？它和 `text_strict_pure_lane` 的差别是否已经被文档和代码清楚收口？
5. `external_text_baseline_audit_v3` 是否真的外部？它能不能进入 formal headline？
6. text 侧是否仍然借用了 StateBus 的 feature extraction、tool registry、memory/replay machinery？如果是，影响是什么？
7. `typed_state_mechanism_v3` 现在到底证明了什么？它是否只证明 minimal typed packet 被生产、传递、消费，而不是证明 rich typed-state 效率收益？
8. `typed_state_authenticity_v3` 和 `typed_state_mechanism_v3` 是否还有重复、遗留、口径混读？
9. `memory_dual_mode_fairness_v3` 为什么只能读 object parity / restore compatibility，而不能读 replay proof？
10. `memory_reuse_v3` / `memory_policy_controlled_v3` 的 replay evidence gate 是否才是共享记忆减少重复工作的正式证据？
11. 当前 consumer sensitivity 是否只证明“可见性变化”，而没有证明“状态缺失会导致 route/tool/correctness 下降”？
12. LangGraph 当前究竟是创新对象，还是固定四节点编排 substrate？
13. README / task docs / report docs / review docs 之间是否还存在 claim drift？
14. 当前 formal headline 是否真的可以放，还是仍必须 withheld？

你在分析时，可以直接采用以下已经得到的中间判断作为待验证假设，而不是最终结论：

- 当前最严重问题是 claim/evidence/benchmark closure，不是对象完全不存在。
- 当前 v3 surface 已比旧 review 时明显更干净，但还没有完成 formal closure。
- 当前 text baseline 仍不能被诚实地叫作“外部传统纯文本 baseline”。
- 当前 typed-state 机制存在，但 consumer proof 还不够硬。
- 当前 memory fairness 与 memory replay proof 必须严格分开读。
- 当前 LangGraph 是工程 substrate，不应被拔高成主创新。
- 当前不该优先纠缠 API repeat=10、Docker、openEuler VM；更应该先把 benchmark 合同、实验结果读法、实现机制和纯文本逻辑收口。

输出要求：

1. 先汇报你读了哪些目录和文件。
2. 再明确当前 branch / dirty tree / review 与代码是否一致。
3. 再给你的严格问题清单，优先级从高到低。
4. 再区分：
   - 已实现
   - 已有局部证据
   - formal 仍不能说
   - 文档口径是否收口
5. 再给下一步修复与分析计划。

写作要求：

- 用中文。
- 不要安慰式表达。
- 允许直接给出负面判断。
- 不要把 audit pack 说成 formal headline。
- 不要把 text 说得比实际更纯。
- 不要把 support pack 说成正式证据。
- 每个重要判断尽量落到具体文件、具体 pack、具体 gate、具体实现路径。
```
