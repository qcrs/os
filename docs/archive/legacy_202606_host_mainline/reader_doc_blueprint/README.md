# 新人学习文档蓝图

这组文件不是最终对外文档，而是给大上下文模型和后续作者使用的“写作蓝图 + 阅读协议 + 主 Prompt”。

目标只有一个：

1. 让新人能从零开始理解当前项目。
2. 让外部读者能看懂我们的方法、任务、对比方式和结果边界。
3. 避免把架构解释、任务设计、实验口径、术语解释混成一份巨型文档。

## 概念边界

在开始写作前，先固定这几条：

1. 如果说的是 Agent 角色，当前仍然是四个：
   - `Planner`
   - `Retriever`
   - `Executor`
   - `Summarizer`
2. `validate` 不是第五个 Agent。它如果存在，属于计划步骤、语义角色或图节点。
3. 文档必须显式区分三套视角：
   - 四角色：谁在工作
   - 三平面：信息在哪几类表面上传递
   - 五层架构：系统从哪几层理解
4. `memory` 不单独抽成外挂系统。它属于整体方法的一部分，需要和结构化传递、中间状态、任务编排一起解释。
5. 所有结果都要区分：
   - `headline`
   - `support`
   - `audit`

## 目录内容

- [00_model_warmup_reading_protocol.md](./00_model_warmup_reading_protocol.md)
  - 先读什么、怎么读、读完要产出什么中间地图
- [01_current_trusted_results_and_boundaries.template.md](./01_current_trusted_results_and_boundaries.template.md)
  - 当前可信结论总览模板
- [02_project_goal_and_method_overview.template.md](./02_project_goal_and_method_overview.template.md)
  - 项目目标与整体方法模板
- [03_system_architecture_and_dataflow_explainer.template.md](./03_system_architecture_and_dataflow_explainer.template.md)
  - 系统架构与数据流模板
- [04_task_and_benchmark_design_with_walkthrough.template.md](./04_task_and_benchmark_design_with_walkthrough.template.md)
  - 任务与 benchmark 设计 + 真实 walkthrough 模板
- [05_text_vs_statebus_comparison_methodology.template.md](./05_text_vs_statebus_comparison_methodology.template.md)
  - `text` 与 `StateBus` 对比方法模板
- [06_result_readout_and_claim_boundary.template.md](./06_result_readout_and_claim_boundary.template.md)
  - 结果详解与口径边界模板
- [07_glossary_for_new_readers.template.md](./07_glossary_for_new_readers.template.md)
  - 新人术语表模板
- [08_pack_and_artifact_index.template.md](./08_pack_and_artifact_index.template.md)
  - pack 与 artifact 索引模板
- [09_ultra_strict_1m_model_master_prompt.md](./09_ultra_strict_1m_model_master_prompt.md)
  - 给 1M 模型的超严格主 Prompt

## 建议输出目录

最终正式文档建议写入：

- [docs/reader_guide/README.md](/home/qcrs/statebus/project/docs/reader_guide/README.md)

建议产出这 8 份正式文档：

1. `docs/reader_guide/01_current_trusted_results_and_boundaries.md`
2. `docs/reader_guide/02_project_goal_and_method_overview.md`
3. `docs/reader_guide/03_system_architecture_and_dataflow_explainer.md`
4. `docs/reader_guide/04_task_and_benchmark_design_with_walkthrough.md`
5. `docs/reader_guide/05_text_vs_statebus_comparison_methodology.md`
6. `docs/reader_guide/06_result_readout_and_claim_boundary.md`
7. `docs/reader_guide/07_glossary_for_new_readers.md`
8. `docs/reader_guide/08_pack_and_artifact_index.md`

## 使用顺序

1. 先读 `00_model_warmup_reading_protocol.md`
2. 再读 8 份模板文件，明确每份文档回答什么
3. 最后使用 `09_ultra_strict_1m_model_master_prompt.md`
4. 让模型先完成热身阅读，再正式写入 `docs/reader_guide/`

## 质量要求

1. 第一次出现的关键英文术语，必须写成“英文 + 中文解释”。
2. 架构解释不能脱离真实任务流。
3. 结果解释不能脱离真实 artifact。
4. `text` 和 `StateBus` 的比较必须说清楚“固定了什么、改变了什么、怎么传、怎么消费”。
5. 不要把 `validate` 写成第五个 Agent。
