# 给 1M 模型的超严格主 Prompt

下面这段 Prompt 供直接复制使用。

---

你现在要为仓库 `/home/qcrs/statebus/project` 产出一套“面向新人学习 + 可对外阅读”的系统文档。

你的任务不是零散 summarization，不是抽取几段报告，也不是只看 README 后写一个概览。

你必须：

1. 先完整热身阅读代码、文档、任务定义和关键实验结果。
2. 再建立系统地图、任务地图、证据地图和比较地图。
3. 最后按指定模板产出 8 份正式文档。

## 一、先读这组蓝图文件

在正式阅读仓库前，你必须先完整阅读下面这些文件：

1. `docs/reader_doc_blueprint/README.md`
2. `docs/reader_doc_blueprint/00_model_warmup_reading_protocol.md`
3. `docs/reader_doc_blueprint/01_current_trusted_results_and_boundaries.template.md`
4. `docs/reader_doc_blueprint/02_project_goal_and_method_overview.template.md`
5. `docs/reader_doc_blueprint/03_system_architecture_and_dataflow_explainer.template.md`
6. `docs/reader_doc_blueprint/04_task_and_benchmark_design_with_walkthrough.template.md`
7. `docs/reader_doc_blueprint/05_text_vs_statebus_comparison_methodology.template.md`
8. `docs/reader_doc_blueprint/06_result_readout_and_claim_boundary.template.md`
9. `docs/reader_doc_blueprint/07_glossary_for_new_readers.template.md`
10. `docs/reader_doc_blueprint/08_pack_and_artifact_index.template.md`

你必须把这些文件当成写作合同，而不是可选建议。

## 二、硬边界

1. 如果说的是 Agent 角色，当前仍然只有四个：
   - `Planner`
   - `Retriever`
   - `Executor`
   - `Summarizer`
2. `validate` 不是第五个 Agent。
3. 你必须显式区分：
   - 四角色
   - 三平面
   - 五层架构
4. `memory` 不得被拆成外挂平行主线。它属于整体方法的一部分。
5. 不得把 `headline`、`support`、`audit` 混写。
6. 不得把当前支持结果上读成比冻结口径更强的结论。
7. 不得把 `text` vs `StateBus` 简化成“文本 vs 结构化”一句话。

## 三、预热阅读要求

你必须先完成一轮全量热身阅读，然后才能写正式文档。

### A. 必读入口

1. `README.md`
2. `docs/constraints/current_host_and_migration.md`
3. `docs/constraints/current_feature_scope.md`
4. `docs/planning/implementation_plan.md`
5. `docs/reference/题目.md`

### B. 必读 docs

你必须完整阅读 `docs/` 下当前与实现、结果和边界相关的 markdown，而不是只挑几份 summary。

至少要覆盖：

1. `docs/planning/`
2. `docs/reports/`
3. `docs/progress/`
4. 当前 architecture / result / gate / claim boundary 直接相关的其他 docs

### C. 必读代码

至少要系统阅读这些目录：

1. `agents/`
2. `runtime/`
3. `protocol/`
4. `statepool/`
5. `memory/`
6. `eval/`
7. `tasks/`
8. `tests/`

要求：

1. 不允许只读类名和函数名。
2. 你必须搞清楚对象是如何流动的。
3. 你必须搞清楚 `text` 路径和 `StateBus` 路径的 handoff 差异。

### D. 必读任务与评测定义

1. `tasks/README.md`
2. `tasks/*.yaml`
3. `tasks/sample_tasks.py`
4. `eval/runner.py`

### E. 必读实验结果

你必须先从当前冻结 docs 中确定：

1. 当前 communication authoritative artifact
2. 当前 communication support artifact
3. 当前 typed-state support artifact
4. 当前 memory artifact

然后对每个 artifact 至少完整阅读：

1. `benchmark_report.md`
2. `benchmark_results.json`
3. `benchmark_compare.csv`

注意：

1. 不要只看路径名。
2. 不要从历史 run 名推断当前代码状态。
3. 当前 authoritative artifact 以冻结 docs 的最新口径为准。

## 四、正式写作前必须先完成的内部工作

在输出正式文档前，你必须先形成下面 7 个内部工作结果：

1. 当前概念边界清单
2. authoritative / support / audit artifact 清单
3. 四角色输入输出表
4. 核心对象字典
5. 任务 pack 地图
6. `text` vs `StateBus` 对比矩阵
7. 当前 claim boundary 清单

这 7 项可以作为内部草稿，不一定最终落盘，但必须先做完。

## 五、正式输出目录

你要把正式文档写入这个目录：

- `docs/reader_guide/`

必须产出以下 8 份文件：

1. `docs/reader_guide/01_current_trusted_results_and_boundaries.md`
2. `docs/reader_guide/02_project_goal_and_method_overview.md`
3. `docs/reader_guide/03_system_architecture_and_dataflow_explainer.md`
4. `docs/reader_guide/04_task_and_benchmark_design_with_walkthrough.md`
5. `docs/reader_guide/05_text_vs_statebus_comparison_methodology.md`
6. `docs/reader_guide/06_result_readout_and_claim_boundary.md`
7. `docs/reader_guide/07_glossary_for_new_readers.md`
8. `docs/reader_guide/08_pack_and_artifact_index.md`

## 六、每份文档必须遵守各自模板

你必须逐份遵守：

1. `docs/reader_doc_blueprint/01_current_trusted_results_and_boundaries.template.md`
2. `docs/reader_doc_blueprint/02_project_goal_and_method_overview.template.md`
3. `docs/reader_doc_blueprint/03_system_architecture_and_dataflow_explainer.template.md`
4. `docs/reader_doc_blueprint/04_task_and_benchmark_design_with_walkthrough.template.md`
5. `docs/reader_doc_blueprint/05_text_vs_statebus_comparison_methodology.template.md`
6. `docs/reader_doc_blueprint/06_result_readout_and_claim_boundary.template.md`
7. `docs/reader_doc_blueprint/07_glossary_for_new_readers.template.md`
8. `docs/reader_doc_blueprint/08_pack_and_artifact_index.template.md`

要求：

1. 不允许跳过模板中的章节目标。
2. 不允许把多个模板混成一份大文档。
3. 不允许省略真实任务 walkthrough。
4. 不允许省略术语表。
5. 不允许省略 artifact 索引。

## 七、写作要求

1. 默认读者不懂项目，不懂内部术语。
2. 中文优先，英文只作为精确标识。
3. 第一次出现的关键术语必须写成“英文 + 中文解释”，例如：
   - `Plan（执行计划）`
   - `PlanStep（计划步骤）`
   - `StateRef（状态引用）`
4. 多用真实例子，少用空泛抽象语句。
5. 结果解释必须带 artifact 锚点。
6. 架构解释必须带对象流和真实数据流。
7. 对比方法必须明确写出：
   - 固定了什么
   - 改变了什么
   - 为什么公平

## 八、强制内容要求

你必须明确写出：

1. 四角色仍然是四个，不是五个。
2. `validate` 是步骤语义或图节点，不是第五个 Agent。
3. 当前 active headline 是什么。
4. 当前 typed-state 和 memory 各自是什么角色。
5. `text` 和 `StateBus` 到底传了什么、怎么传、谁消费。
6. 任务 pack 为什么不是散题。
7. scorer 如何判断正确性。
8. 当前能说什么，不能说什么。

## 九、禁止事项

1. 不要把 `memory` 单独写成脱离主方法的外挂主线。
2. 不要把 `validate` 写成第五个 Agent。
3. 不要把 support surface 偷换成 headline closure。
4. 不要把历史 artifact 当成当前 authoritative source-of-truth。
5. 不要把 `text` vs `StateBus` 写成一句“文本 vs 结构化”。
6. 不要省略中文解释。
7. 不要只抄代码名词，不讲含义。
8. 不要只讲高层设计，不讲真实任务流。

## 十、执行顺序

你必须按这个顺序工作：

1. 读蓝图文件
2. 读仓库入口和边界文档
3. 读全部相关 docs
4. 读关键代码
5. 读任务定义与 runner
6. 读 authoritative / support artifacts
7. 建立内部地图
8. 再开始正式输出 8 份文档

## 十一、开始正式写作前，先输出这三样中间确认

在真正写文档前，你必须先输出：

1. 你确认的当前概念边界
2. 你确认的主要 authoritative / support artifacts
3. 你即将写出的 8 份文档清单

只有这三项确认完，才进入正式写作。

---
