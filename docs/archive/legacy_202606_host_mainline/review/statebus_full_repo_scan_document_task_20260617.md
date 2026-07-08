# StateBus 全量仓库扫描文档化任务说明

日期：`2026-06-17`

适用范围：`/home/qcrs/statebus/project`

目标：

- 这不是普通问答 prompt。
- 这是一份明确要求执行者先做全量扫描、再把扫描结果写成正式文档的任务说明。
- 目标不是继续局部修补，而是系统梳理当前仓库：
  - 赛题到底要什么
  - 仓库当前到底实现了什么
  - 历史上改了什么
  - 哪些创新点真的落地了
  - 哪些 benchmark / pack / surface 仍然有效
  - 哪些东西已经变成历史包袱、概念残留、报表修补或解释层堆叠

---

## 1. 这次任务真正要产出的不是“回答”，而是“文档”

如果你把这份任务交给另一个 AI 或审计者，要求必须是：

1. 先全量扫描仓库，而不是直接给结论
2. 产出至少 1 份正式分析文档，写入仓库 `docs/analysis/` 或 `docs/review/`
3. 文档必须详细，必须引用具体文件、代码位置、测试位置、run 结果位置
4. 不允许只给聊天回复式摘要
5. 不允许只复述已有文档口径
6. 必须交叉核对：
   - 赛题要求
   - 当前文档
   - 当前代码
   - 当前测试
   - 当前 benchmark 结果
7. 如果发现已有文档互相矛盾、过时、只剩历史价值，必须明确标注

建议要求对方最终至少写出以下文档之一：

- `docs/analysis/statebus_full_repo_scan_20260617.md`
- 或 `docs/review/statebus_full_repo_scan_20260617.md`

如果对方工作量足够大，也可以拆成多份文档，但必须至少有 1 份主文档承担“全局认知地图”作用。

---

## 2. 这次扫描要解决的根问题

这次不是为了回答某一个局部 bug。

这次要解决的是更上层的问题：

1. 当前项目是否已经失去清晰主线
2. 当前 benchmark 体系是否过于复杂，导致解释成本高于新增证据
3. 当前代码架构是否已经开始石山化
4. 当前反复修补的是不是主要是：
   - benchmark 对象定义
   - fairness 口径
   - report / metric 语义
   - support surface 与 headline 分离
   而不是系统核心能力
5. 之前提出的一些创新点是否真正落地：
   - git 风格管理
   - 增量 / 版本化 state 管理
   - typed state richer authenticity
   - memory replay / policy
   - planner openness
   - open / langgraph extension
   - whole-lane pure text vs inline boundary
6. 当前“StateBus vs text”的对比是否在赛题要求下本来就很难做成完全公平、有效区分
7. 当前“结果总是差不多”到底是因为：
   - 方法本身没有形成真实优势
   - 任务太薄、太短、太简单
   - benchmark 设计不对
   - 对比对象不纯
   - 报表语义在误导

---

## 3. 产出文档必须回答的核心问题

最终文档必须明确回答这些问题，不能含糊：

1. 赛题真正要求什么
2. 当前项目真正回答了什么
3. 当前项目没有回答什么
4. 当前主线是否清晰
5. 当前 benchmark 是否仍然能回答赛题主问题
6. 当前“公平性修补”是否已经开始取代真正的方法进展
7. 当前最该停止继续追的方向是什么
8. 当前最应该保留的主线是什么
9. 是否应该先暂停补丁式修修补补，转而进行一次系统性收口

---

## 4. 对执行者的硬要求

### 4.1 必须先扫描，再写文档

不允许先下结论再补证据。

必须先做：

1. 文档扫描
2. 代码扫描
3. 测试扫描
4. benchmark / run 扫描
5. 版本演化线索扫描
6. 创新点与未落地项扫描

然后再写主文档。

### 4.2 必须把结果写入仓库文档

要求对方最终把分析写到仓库文件里，而不是只在聊天里回答。

必须明确要求：

- 新建文档
- 文档落盘
- 内容详细
- 有证据链
- 有文件路径
- 有代码路径
- 有测试与 run 路径

### 4.3 必须允许得出负面结论

要明确要求对方：

- 不要为当前方法找补
- 不要默认已有文档 claim 成立
- 如果结论是“当前路线发散了”或“当前 benchmark 无法证明方法优越性”，必须明确写出来

---

## 5. 必读文档入口

### 5.1 赛题与主约束

必须优先阅读：

- `README.md`
- `docs/reference/题目.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/planning/implementation_plan.md`

这些文件回答：

- 项目对象
- 当前开发边界
- 不该重开的范围
- 赛题约束
- 当前 host 主线

### 5.2 当前最重要的 review / analysis 文档

建议优先阅读并交叉比对：

- `docs/review/statebus_contest_first_refactor_execution_plan_20260617.md`
- `docs/review/statebus_full_restructure_execution_plan_20260616.md`
- `docs/review/statebus_contest_remaining_closure_plan_20260615.md`
- `docs/review/statebus_remaining_issues_and_solutions_20260615.md`
- `docs/analysis/honest_full_audit_20260617.md`
- `docs/analysis/mainline_repeat3_analysis_20260617.md`
- `docs/analysis/host_full_api_repeat3_deep_analysis_20260616.md`
- `docs/analysis/statebus_deep_data_analysis_20260616.md`
- `docs/analysis/statebus_deep_data_repair_plan_20260616.md`
- `docs/analysis/issue_discovery_smoke_analysis_20260616.md`
- `docs/analysis/planner_validate_closure_verification_20260616.md`
- `docs/reports/task_design_and_mode_comparison.md`
- `docs/reports/architecture_and_data_flow.md`

要求执行者做的不是机械全读，而是：

1. 识别哪些是当前仍有效的主文档
2. 识别哪些只是历史阶段文档
3. 识别哪些文档的结论已被后续代码或 run 推翻
4. 写出一份“关键文档地图”

### 5.3 历史与参考文档

如需理解设计意图，可继续检索：

- `docs/reference/statebus_architecture_and_implementation_plan.md`
- `docs/reference/statebus_dual_plane_deep_design.md`
- `docs/reference/statebus_architecture_evolution_feasibility_report.md`
- `docs/reference/multi-agent-system-design.md`
- `docs/reference/s_memory_agent_design.md`
- `docs/analysis/novel_design_content_addressed_state_fabric.md`

执行者必须判断：

- 这些文档描述的是当前实现，还是历史构想
- 哪些创新点只停留在文档层

---

## 6. 必扫代码位置

执行者不能只看 2-3 个文件，必须建立代码地图。

### 6.1 Agent / Runtime 主路径

必须重点扫描：

- `agents/sample_agents.py`
- `runtime/orchestrator.py`
- `runtime/executor_runtime.py`
- `runtime/langgraph_adapter.py`
- `runtime/contracts.py`
- `runtime/reuse_contract.py`
- `runtime/task_profile.py`
- `runtime/llm.py`

重点回答：

- 真正运行主路径是什么
- Planner / Retriever / Executor / Summarizer 的数据流是什么
- 哪些路径是主线热路径
- 哪些路径只是兼容或审计路径

### 6.2 Protocol / State / Memory

必须扫描：

- `protocol/channels.py`
- `protocol/messages.py`
- `protocol/statebus.proto`
- `statepool/store.py`
- `memory/store.py`

重点回答：

- typed state / StateRef / StatePool 是否真实进入主路径
- 是什么被真的存、真的传、真的读
- 哪些 richer object 只是 support surface

### 6.3 Eval / Benchmark / Report

必须重点扫描：

- `eval/runner.py`
- `eval/metrics.py`
- `eval/open_runner.py`
- `eval/text_open_baseline.py`

重点回答：

- 当前 benchmark 汇总逻辑是什么
- report 和 row-level 是否一致
- 有没有 metric 语义错误
- 哪些 pack 是 formal headline / formal secondary / audit only / support only

### 6.4 Tasks / Corpus / Benchmark YAML

必须扫描：

- `tasks/sample_tasks.py`
- `tasks/local_corpus.py`
- `tasks/contest_family_spec.py`
- `tasks/contest_family_spec.yaml`
- `tasks/contest_dual_mode_controlled_v3_benchmark.yaml`
- `tasks/memory_dual_mode_fairness_v3_benchmark.yaml`
- `tasks/planner_support_v3_benchmark.yaml`
- `tasks/text_definition_audit_v3_benchmark.yaml`
- `tasks/typed_state_mechanism_v3_benchmark.yaml`
- `tasks/typed_state_authenticity_v3_benchmark.yaml`
- `tasks/typed_state_full_rich_audit_v3_benchmark.yaml`
- `tasks/external_text_baseline_audit_v3_benchmark.yaml`
- `tasks/state_ref_consumer_sensitivity_audit_benchmark.yaml`

重点回答：

- 当前 task object 是否过薄
- 当前 benchmark 是否单变量
- 当前对比对象是否纯净
- 哪些 pack 的任务设计只是 support / audit，不应误升格

### 6.5 Tests / Scripts

必须扫描：

- `tests/test_smoke.py`
- `tests/test_llm_runtime.py`
- `tests/test_state_channels_and_graph.py`
- `tests/test_memory_store.py`
- `tests/test_protocol_messages.py`
- `scripts/run_issue_discovery_smoke.py`
- `scripts/run_statebus_mainline_repeat3_suite.sh`
- `scripts/run_open_extension_repeat3_suite.sh`
- `scripts/run_contest_plus_open_repeat3_suite.py`

重点回答：

- 当前测试主要在保证什么
- 是 runtime correctness、contract correctness、还是 report surface correctness
- 当前脚本地图是否已经过多、过散、难以维护

---

## 7. 必扫 benchmark / run 结果位置

执行者必须以当前主 run 为重点，而不是只读 markdown 报告。

### 7.1 当前主 run

重点 run：

- `/home/qcrs/statebus/runs/statebus_mainline_repeat3_suite_20260617_141158/`

必须看：

- `SUMMARY.md`
- `logs/full_pytest.log`
- `benchmarks/contest_honest_headline_v1/benchmark_report.md`
- `benchmarks/contest_dual_mode_controlled_v3/benchmark_report.md`
- `benchmarks/memory_dual_mode_fairness_v3/benchmark_report.md`
- `benchmarks/planner_support_v3/benchmark_report.md`
- `benchmarks/text_definition_audit_v3/benchmark_report.md`
- `benchmarks/typed_state_mechanism_v3/benchmark_report.md`
- `benchmarks/typed_state_consumer_sensitivity_v3/benchmark_report.md`

必要时必须下钻：

- 对应 `benchmark_results.json`

### 7.2 之前的重要 run

如需理解前因后果，可对比：

- `/home/qcrs/statebus/runs/host_full_api_repeat3_v3_20260616_221231/`
- 各 `issue_discovery_smoke_*` run

要求执行者回答：

- 当前问题是新问题还是历史延续
- 哪些问题已经在 earlier run 中出现过
- 哪些问题只是新报表暴露得更清楚

---

## 8. 必须完成的几类分析

### 8.1 仓库地图分析

要求输出：

- 当前模块地图
- 当前文档地图
- 当前 benchmark surface 地图
- 当前脚本地图
- 当前主线热路径 vs 支线路径

### 8.2 版本演化分析

要求输出：

- 项目最初想解决什么
- 后来经历了哪些关键重构
- 哪几轮“修 fairness / 修 contract / 修 report / 修 headline”最关键
- 哪些历史包袱导致了现在的复杂度

### 8.3 创新点落地审计

要求输出每个重要创新点的状态：

- 已完整落地
- 已部分实现
- 仅停留在文档
- 有代码但不在热路径
- 有测试但无主线意义
- 应该放弃

特别需要关注：

- git 风格 / 增量管理
- richer typed-state
- replay / policy
- planner openness
- open / langgraph extension
- pure text 定义分离

### 8.4 架构审计

要求回答：

- 当前架构是否清晰
- 是否已经石山化
- 是否存在：
  - alias 堆积
  - pack / surface 膨胀
  - 边界不清
  - 概念重复包装
  - report 为了修解释又叠一层

### 8.5 Benchmark 审计

要求回答：

- 当前 benchmark 是否过度复杂
- 当前对比是否清晰
- 当前为何总是“效果差不多”
- 这是任务太薄、方法无优势、对象不公平，还是报表误导
- 当前是否仍然有值得继续保留的正式 surface

---

## 9. 文档输出结构要求

要求执行者最终落盘的主文档至少包含以下章节。

### 9.1 `Repository Map`

必须包括：

- 代码模块地图
- 文档分层地图
- benchmark pack 地图
- 主线 / 支线 / 历史残留分类

### 9.2 `Evolution Analysis`

必须包括：

- 版本迭代与主线变化
- 关键转向
- 哪些文档仍有效
- 哪些结论已过时

### 9.3 `Innovation Audit`

必须包括：

- 重要创新点清单
- 每个创新点的落地状态
- 是否进入主路径 / 测试 / benchmark / 结果解释

### 9.4 `Architecture Audit`

必须包括：

- 当前代码结构诊断
- 热路径图
- 复杂度来源
- 石山化风险

### 9.5 `Benchmark Audit`

必须包括：

- 当前 benchmark 地图
- formal / audit / support 分类
- 公平性与对象纯净性问题
- 为什么结果总是接近

### 9.6 `Main Diagnosis`

必须用最关键的结论回答：

- 赛题要什么
- 我们缺什么
- 当前真正做到了什么
- 当前没有做到什么
- 当前最应停止什么
- 当前最应保留什么

### 9.7 `Recommended Reset Plan`

如果执行者认为应该先重整再继续，必须给出一条主线计划：

- 不是发散菜单
- 而是一条收口主线
- 分阶段写清：
  - 目标
  - 输入
  - 输出
  - 边界

---

## 10. 对证据的要求

最终文档不是观点清单，必须有证据链。

每个重要结论至少给出：

1. 文档依据
2. 代码路径
3. 测试或 benchmark 结果依据
4. 为什么它属于：
   - 真能力问题
   - benchmark 对象问题
   - 报表问题
   - 架构问题
   - 历史未落地问题

必要时必须引用：

- 具体文件路径
- 具体 benchmark report
- 具体 `benchmark_results.json`
- 具体测试文件

---

## 11. 一段可直接发给另一个 AI 的任务说明

下面这段可以直接发给另一个 AI，但重点不是让它“回复我”，而是让它“把分析写成文档并落盘”：

```text
你现在要对 `/home/qcrs/statebus/project` 做一次全量仓库扫描式审计。

注意：你的任务不是先给聊天回复，而是先完成扫描，再把分析结果写成仓库里的正式文档。

要求：
1. 先扫描文档、代码、测试、run 结果，再分析。
2. 必须把结果写入新文档，建议路径：
   - `docs/analysis/statebus_full_repo_scan_20260617.md`
   - 或 `docs/review/statebus_full_repo_scan_20260617.md`
3. 文档必须详细，必须引用具体路径，包括文档、代码、测试、benchmark report、benchmark_results.json。
4. 不要为现有实现找补，不要默认当前 claim 成立。
5. 要区分：
   - 赛题真正要求什么
   - 当前仓库声称在做什么
   - 代码实际上实现了什么
   - benchmark 实际测到了什么
   - 哪些创新点真正落地了
   - 哪些只是概念、半实现、support surface 或历史残留
6. 必须明确判断：
   - 当前项目是否失去主线
   - 当前 benchmark 是否过于复杂
   - 当前代码是否石山化
   - 当前“效果差不多”到底是方法问题、任务太薄、对象不公平，还是报表问题
7. 如果结论是否定的，必须直接写出来，不要回避。

必读入口：
- `README.md`
- `docs/reference/题目.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/planning/implementation_plan.md`
- `docs/review/statebus_contest_first_refactor_execution_plan_20260617.md`
- `docs/review/statebus_full_restructure_execution_plan_20260616.md`
- `docs/analysis/honest_full_audit_20260617.md`
- `docs/analysis/mainline_repeat3_analysis_20260617.md`
- `docs/reports/task_design_and_mode_comparison.md`

必须重点扫描的代码：
- `agents/sample_agents.py`
- `runtime/orchestrator.py`
- `runtime/executor_runtime.py`
- `runtime/langgraph_adapter.py`
- `eval/runner.py`
- `eval/metrics.py`
- `tasks/sample_tasks.py`
- `tasks/local_corpus.py`
- `tasks/contest_family_spec.yaml`
- `tasks/contest_dual_mode_controlled_v3_benchmark.yaml`
- `tests/test_smoke.py`
- `tests/test_llm_runtime.py`
- `tests/test_state_channels_and_graph.py`

必须重点扫描的 run：
- `/home/qcrs/statebus/runs/statebus_mainline_repeat3_suite_20260617_141158/`

必须看：
- `SUMMARY.md`
- 各 benchmark report
- 必要时下钻 `benchmark_results.json`

输出文档至少包含：
- Repository Map
- Evolution Analysis
- Innovation Audit
- Architecture Audit
- Benchmark Audit
- Main Diagnosis
- Recommended Reset Plan

不要只给摘要。必须把详细内容写入文档。
```

---

## 12. 当前最客观的建议

如果你现在问“最该做什么”，我的建议不是继续追某个局部 pack。

当前最合理的动作是：

1. 先做这次全量扫描并落盘
2. 先建立完整认知地图
3. 再决定到底是：
   - 继续沿当前主线收口
   - benchmark 重整
   - 架构收缩
   - 还是暂停某些路线

因为当前最危险的问题已经不是某个局部 bug，而是：

- 解释成本越来越高
- 主线越来越散
- 局部都合理，但全局越来越难说清

这时最需要的是一份真正详细、可落盘、可复查的全量扫描文档。
