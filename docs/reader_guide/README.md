# StateBus 新人学习文档

这组文档是新人和外部读者从零开始理解 StateBus 项目的配套阅读材料。

如果你现在只想先读一份，先读：

- [`../reports/statebus_system_method_task_and_results_explainer.md`](../reports/statebus_system_method_task_and_results_explainer.md)

这份总览先把四件最重要的事情讲清楚：

1. 当前最新可信结果是什么
2. 系统主流程怎么跑
3. 任务是怎么构造、怎么判对错的
4. `text` 和 StateBus 到底是怎么比较的

读完它，再按需要回到这里查模块化说明。

---

## 概念边界

在开始阅读前，请先接受这几条固定概念：

1. Agent 角色只有四个：`Planner`（规划器）、`Retriever`（检索器）、`Executor`（执行器）、`Summarizer`（总结器）。`validate` 是语义角色/图节点，不是第五个 Agent。
2. 文档必须显式区分三套视角：
   - **四角色**：谁在工作
   - **三平面**：控制面（传"谁做什么"）、状态面（传"实际数据"）、记忆面（传"历史经验"）
   - **五层架构**：任务合同层 → 编排语义层 → typed state 基座层 → replay/记忆门控层 → 报告与结论边界层
3. `memory`（记忆）不单独抽成外挂系统。它属于整体方法的一部分。
4. 所有结果都要区分：`headline`（主结论）、`support`（支撑）、`audit`（审计）。

---

## 目录

| 序号 | 文件 | 用途 |
|---|---|---|
| 01 | [当前可信结论总览](./01_current_trusted_results_and_boundaries.md) | 最快入口：现在成立了什么、还没成立什么、headline/support/audit 分别是什么 |
| 02 | [项目目标与整体方法总览](./02_project_goal_and_method_overview.md) | 项目解决什么系统问题、三大核心机制是什么、为什么 memory 必须一起理解 |
| 03 | [系统架构与数据流说明](./03_system_architecture_and_dataflow_explainer.md) | 四角色/三平面/五层架构的关系、核心模块分工、完整时序图 |
| 04 | [任务与 Benchmark 设计 + 真实 Walkthrough](./04_task_and_benchmark_design_with_walkthrough.md) | 任务为什么不是散题、pack / family / chain / case 的关系、完整真实任务流 |
| 05 | [`text` 与 `StateBus` 对比方法说明](./05_text_vs_statebus_comparison_methodology.md) | 固定了什么改变了什么、handoff 差异分角色说明、为什么不是换题比较 |
| 06 | [结果详解与口径边界](./06_result_readout_and_claim_boundary.md) | 具体数字和解读、能说什么不能说什么、residual 不等于 failure |
| 07 | [新人术语表](./07_glossary_for_new_readers.md) | 所有核心术语的英文+中文+项目含义+常见误解 |
| 08 | [Pack 与 Artifact 索引](./08_pack_and_artifact_index.md) | 每个 pack 回答什么不回答什么、证据路径在哪、历史对象边界 |

---

## 推荐阅读顺序

**最快入口**：

1. [`../reports/statebus_system_method_task_and_results_explainer.md`](../reports/statebus_system_method_task_and_results_explainer.md)
2. [01_current_trusted_results_and_boundaries.md](./01_current_trusted_results_and_boundaries.md)

**想把系统和实验读明白**：

1. [`../reports/statebus_system_method_task_and_results_explainer.md`](../reports/statebus_system_method_task_and_results_explainer.md)
2. [03_system_architecture_and_dataflow_explainer.md](./03_system_architecture_and_dataflow_explainer.md)
3. [04_task_and_benchmark_design_with_walkthrough.md](./04_task_and_benchmark_design_with_walkthrough.md)
4. [05_text_vs_statebus_comparison_methodology.md](./05_text_vs_statebus_comparison_methodology.md)
5. [06_result_readout_and_claim_boundary.md](./06_result_readout_and_claim_boundary.md)

**查漏补缺**：

- 不懂术语时看 [07_glossary_for_new_readers.md](./07_glossary_for_new_readers.md)
- 想找具体 artifact 路径时看 [08_pack_and_artifact_index.md](./08_pack_and_artifact_index.md)
- 想先理解赛题为什么这样拆，再看 [02_project_goal_and_method_overview.md](./02_project_goal_and_method_overview.md)

---

## 质量规约

1. 第一次出现的关键英文术语写成"英文 + 中文解释"
2. 架构解释不脱离真实任务流
3. 结果解释不脱离真实 artifact
4. `text` 和 `StateBus` 的比较必须说清楚"固定了什么、改变了什么"
5. 不把 `validate` 写成第五个 Agent
6. 不把 `memory` 写成脱离主方法的外挂模块
7. 不把 support surface 偷换成 headline closure

---

## 关联文档

- 蓝图文件：`docs/reader_doc_blueprint/`
- 仓库入口：`README.md`
- 当前约束：`docs/constraints/`
- 当前主说明：`docs/reports/statebus_system_method_task_and_results_explainer.md`
- 当前冻结口径：`docs/reports/current_task_results_overview_20260622.md`
- 历史背景报告：`docs/reports/` 中带有“历史/冻结对象”提示的旧文档
- 任务定义：`tasks/`
- 执行入口：`eval/runner.py`
