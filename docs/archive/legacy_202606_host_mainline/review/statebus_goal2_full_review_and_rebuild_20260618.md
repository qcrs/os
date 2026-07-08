# StateBus Goal 2：全面 Review / 分析 / 允许重构的 Goal Prompt

日期：`2026-06-18`

适用范围：

- 仓库：`/home/qcrs/statebus/project`
- 环境：`/home/qcrs/statebus/conda-envs/statebus_host`
- 用途：新窗口以赛题要求为中心，对当前实现、benchmark、任务集、创新点和证据层做全面 review，并允许得出“应重构/应重设主线”的结论

---

## 1. 这份文档的定位

这份文档不是执行型 prompt 的备份版。

它的定位是：

- 先全面阅读
- 再从赛题要求反推当前实现
- 不被本地已有实现绑架
- 不默认当前主线就是对的
- 不把“小补丁”当默认答案
- 不只在对话里给结论，而是把分析过程和结论详细落成文档
- 细读、细分析，不允许速读后草率下判断

如果 review 之后你判断：

- benchmark 不干净
- task 太薄
- claim 混乱
- 赛题特化过重
- 当前创新点主线不够强

你必须直接说，并允许给出：

- benchmark reset
- task set 重构
- retrieval / executor / replay 结构重构
- 主线重新立项

而且这些判断不能只停留在最终回答里，必须详细写入仓库文档。

这次 review / 检索 的工作风格也必须明确：

- 不允许只看文档开头/结尾就下判断
- 不允许只抽样看几个 case 就给 task/benchmark 结论
- 不允许只挑支持自己预设判断的 run 或段落
- 不允许把“我大概知道这是什么意思”当成已经分析完
- 必须把重要材料细读到能复述其对象、边界、证据和问题

---

## 2. 当前 review 应该怎么理解项目状态

截至 `2026-06-18`，当前项目不能再简单理解成“还在修 correctness/object purity”。

当前更准确的状态是：

- host-side 原型已经可运行，不是 design-only
- correctness/object purity 这层主收口已经基本完成
- `contest_honest_headline_v1` 已经接过唯一 contest-facing headline
- 最近一轮厚化 / validate-first 兼容性问题已经收口到只剩 `contest_repeat_insufficient`
- 但这不等于项目已经清楚
- 当前更需要重新审的是：
  - benchmark 是否真的适合裁决方法
  - task thickness 是否足够
  - 当前创新点是否在赛题主问题上真正立得住
  - 当前 retrieval / executor / replay 是否过度 scaffold / contest-shaped

---

## 3. 当前 review 以哪些文件为入口

如果文件之间有冲突，review 先按下面顺序建立事实层。

### 3.1 当前事实与主问题入口

1. `docs/review/statebus_goal2_full_review_and_rebuild_20260618.md`
2. `docs/reference/题目.md`
3. `docs/progress/contest_requirement_host_audit_20260607.md`
4. `docs/review/statebus_benchmark_thickness_execution_contract_20260618.md`
5. `docs/review/statebus_contest_honest_headline_thickening_plan_20260618.md`

### 3.2 当前诊断与问题地图

6. `docs/review/statebus_benchmark_charter_20260617.md`
7. `docs/review/statebus_new_window_guidance_20260617.md`
8. `docs/analysis/statebus_current_thinking_reset_20260617.md`
9. `docs/review/statebus_reset_plan_from_full_scan_20260617.md`
10. `docs/analysis/statebus_full_repo_scan_20260617.md`
11. `docs/analysis/honest_full_audit_20260617.md`
12. `docs/analysis/mainline_repeat3_analysis_20260617.md`

### 3.3 背景约束与实现边界

13. `README.md`
14. `docs/constraints/current_host_and_migration.md`
15. `docs/constraints/current_feature_scope.md`
16. `docs/reports/MASTER_PRESENTATION_GUIDE.md`
17. `docs/reports/task_design_and_mode_comparison.md`

### 3.4 背景参考，不作为当前事实主合同

18. `docs/planning/host_goal_mainline_dependency_20260607.md`
19. `docs/planning/host_goal_review_execution_plan_20260607.md`
20. `docs/planning/goal_prompt_host_mainline_despecialize_then_deepen_20260608.md`
21. `goal.md`
22. `docs/planning/implementation_plan.md`

最重要的一条是：

> 当前 review 不应再把旧 host-goal prompt 或 `implementation_plan.md` 当作当前事实层；它们最多是历史设计背景。

---

## 4. 这次 review 的默认立场

这次 review 的默认立场固定为：

- 赛题要求第一，不是当前实现第一
- benchmark correctness 先于 method judgment
- mechanism 先于 narrative
- 证据层必须分开，不能混说
- 允许重构，不要求保守补丁
- 如果问题太大，优先提出重构和重立主线，而不是继续修补
- 必须先基于 `docs/reference/题目.md` 重建你自己的赛题理解
- 必须在本地问题重建后做一轮受控上网检索，用外部 benchmark / 论文 / 官方 repo 校准你的判断
- 必须把 review 结果系统化落成 3-4 份详细文档，而不是只在对话里总结
- 必须保留“阅读记录 + 检索记录 + 判断记录”，让后续窗口能看到你到底读了什么、为什么这样判断

---

## 5. Goal Prompt

把下面整段 prompt 交给新的 goal 窗口使用。

`````text
你现在进入 goal 模式。

工作目录固定为：
`/home/qcrs/statebus/project`

Python 环境固定为：
`/home/qcrs/statebus/conda-envs/statebus_host`

进入后先执行：
```bash
source /home/qcrs/statebus/conda-envs/statebus_host/bin/activate
cd /home/qcrs/statebus/project
source deploy/activate_statebus_host.sh
```

这次 goal 不是“继续补一点”，而是做一次真正的全面 review / 分析 / 定位。

你的任务是：

从赛题要求反推当前 StateBus 的实现、创新点、benchmark 设计、任务集设定、证据层、历史演化和当前问题。不要被本地已有实现绑架，不要默认当前主线就是对的，不要自动选择最小补丁。如果你判断当前实现偏离赛题主问题、benchmark 不干净、任务太薄、claim 混乱、方法收益不真实，必须直接指出，并允许得出“应该重构”“应该重设 benchmark/task contract”“应该停掉某条线”的结论。

这次 goal 必须显式完成两步，而不是只做本地阅读：

1. 先基于赛题要求重建“这道题到底在考什么、不在考什么”
2. 再基于这个赛题理解，做一轮受控上网检索，用外部对象校准你对当前主线的判断

并且这次 goal 不是“口头 review”。

你必须把分析过程和结论详细写进仓库文档，允许分成 3-4 份文档分别落盘，要求事无巨细，证据、判断、反例、问题分层、重构建议都要写进去。

这次 goal 明确禁止下面这些偷懒行为：

- 只扫一遍目录或 README 就开始下结构结论
- 只看 aggregate report，不回到 row-level / run-level / code-level
- 只摘几句外部论文摘要，就说“外部研究支持/反对我们”
- 外部检索只搜一个方向，忽略与赛题主问题更直接相关的对象
- 只写结论，不写你是怎么读到这个结论的

你必须接受下面这些当前上下文：

- 当前 repo 已经是 host-side 可运行原型，不是 design-only
- 当前唯一 contest-facing headline 是 `contest_honest_headline_v1`
- 最近一轮厚化 / validate-first 兼容性问题已经收口到：
  - deterministic `repeat=1` 不再卡 object/gate compatibility
  - API `repeat=1` 不再卡 object/gate compatibility
  - 当前 withheld 主因只剩 `contest_repeat_insufficient`
  - `object_parity_gate.passed == true`
  - `unexpected_task_failure_count == 0`
- 这说明当前 review 不要再把 recent gate compatibility bug 当核心主问题
- 当前更应该重新审视的是 benchmark、task thickness、赛题特化、retrieval / executor / replay 的真实性和泛化性

如果文件之间有冲突，当前 review 先按下面顺序建立事实层：

1. `docs/review/statebus_goal2_full_review_and_rebuild_20260618.md`
2. `docs/reference/题目.md`
3. `docs/progress/contest_requirement_host_audit_20260607.md`
4. `docs/review/statebus_benchmark_thickness_execution_contract_20260618.md`
5. `docs/review/statebus_contest_honest_headline_thickening_plan_20260618.md`
6. `docs/review/statebus_benchmark_charter_20260617.md`
7. `docs/review/statebus_new_window_guidance_20260617.md`
8. `docs/analysis/statebus_current_thinking_reset_20260617.md`
9. `docs/review/statebus_reset_plan_from_full_scan_20260617.md`
10. `docs/analysis/statebus_full_repo_scan_20260617.md`
11. `docs/analysis/honest_full_audit_20260617.md`
12. `docs/analysis/mainline_repeat3_analysis_20260617.md`

下面这些只作背景，不是当前事实主合同：

- `docs/planning/host_goal_mainline_dependency_20260607.md`
- `docs/planning/host_goal_review_execution_plan_20260607.md`
- `docs/planning/goal_prompt_host_mainline_despecialize_then_deepen_20260608.md`
- `goal.md`
- `docs/planning/implementation_plan.md`

硬边界：

- 不做 Docker
- 不做 openEuler VM
- 不做 `nsjail` / 强沙箱终态
- 不做 hidden-state / KV 传递
- 不做交付打包
- 不为了“显得有创新”就把加分项强拉进主线
- 不把 support surface 说成 headline
- 不先改代码再解释
- 不允许只读 README 和一份 report 就下结论
- 不允许把“已有实现”当成“合理实现”

你必须先做全面阅读。按这个顺序：

A. 赛题与主约束
1. `docs/review/statebus_goal2_full_review_and_rebuild_20260618.md`
2. `docs/reference/题目.md`
3. `README.md`
4. `docs/constraints/current_host_and_migration.md`
5. `docs/constraints/current_feature_scope.md`

B. 当前 review / diagnosis / benchmark charter
6. `docs/progress/contest_requirement_host_audit_20260607.md`
7. `docs/review/statebus_benchmark_thickness_execution_contract_20260618.md`
8. `docs/review/statebus_contest_honest_headline_thickening_plan_20260618.md`
9. `docs/review/statebus_benchmark_charter_20260617.md`
10. `docs/review/statebus_new_window_guidance_20260617.md`
11. `docs/analysis/statebus_current_thinking_reset_20260617.md`
12. `docs/review/statebus_reset_plan_from_full_scan_20260617.md`
13. `docs/analysis/statebus_full_repo_scan_20260617.md`
14. `docs/analysis/honest_full_audit_20260617.md`
15. `docs/analysis/mainline_repeat3_analysis_20260617.md`

C. 当前 benchmark / task / 报告
16. `docs/reports/MASTER_PRESENTATION_GUIDE.md`
17. `docs/reports/task_design_and_mode_comparison.md`
18. `tasks/sample_benchmark.yaml`
19. `tasks/sample_tasks.py`
20. `tasks/local_corpus.py`

D. 当前关键代码
21. `agents/sample_agents.py`
22. `runtime/orchestrator.py`
23. `runtime/executor_runtime.py`
24. `eval/runner.py`
25. `tests/test_smoke.py`

E. 当前与历史 evidence
26. `runs/comprehensive_eval_20260607_131113/`
27. `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`
28. `runs/contest_honest_headline_thickness_det_r1_fix4/`
29. `runs/contest_honest_headline_thickness_api_r1_fix1/`
30. 必要时顺着 `docs/` 和 `runs/` 里的历史记录回看之前的拆分、失败、重写痕迹

在完成上面的本地阅读后，你必须先输出一个“赛题理解小结”，至少回答：

1. 这道题的主评分对象到底是什么
2. 这道题的主变量应该是什么，哪些东西只能算 support / audit / 加分项
3. 这道题为什么不能被偷换成“只要做了多 agent + memory 就算完成”
4. 这道题为什么必须谨慎对待 pure-text baseline、structured protocol、non-text state transfer、shared memory reuse 这四个对象的边界

只有写完这份“赛题理解小结”，才允许进入外部检索。

在正式写结论前，你还必须保留一份“阅读与检索记录”，可以单独成文，也可以并入第 4 份外部对照文档。至少包含：

1. 本地阅读记录
- 读了哪些 docs / code / runs
- 每份材料主要回答什么问题
- 哪些材料改变了你的判断

2. 外部检索记录
- 搜了什么问题
- 看了哪些 primary sources
- 哪些 source 支持当前主线，哪些 source 暗示当前主线可能偏了

3. 判断修正记录
- 你最初的判断是什么
- 读完哪些材料后修正了判断
- 为什么修正

在进入最终结论前，你必须把分析结果写成详细文档，默认至少产出下面 4 份中的 3 份，优先全部产出：

1. `docs/analysis/statebus_review_requirement_map_<date>.md`
   - 逐条写赛题 requirement map
   - 写清每条 requirement 当前的实现状态、证据、争议点、不能宣称的部分

2. `docs/analysis/statebus_review_benchmark_and_task_audit_<date>.md`
   - 详细写 benchmark、task set、headline/support/audit 分层问题
   - 写清 task thickness、object purity、single-variable、row/report consistency、scenario 壳与机制主问题的关系

3. `docs/analysis/statebus_review_runtime_and_authenticity_<date>.md`
   - 详细写 Planner/Retriever/Executor/Summarizer、memory/replay、retrieval/executor 的真实性、过度 scaffold、contest-shaped 问题
   - 写清哪些是实现 bug，哪些是结构错位，哪些是主线偏移

4. `docs/analysis/statebus_review_external_alignment_and_rebuild_<date>.md`
   - 详细写外部 benchmark / repo / 论文调研
   - 写清 borrow list / contrast table
   - 写清是否需要 benchmark reset / task 重构 / 主线重立 / 创新点改写

写文档的要求：

- 不是简短 memo
- 不是一页摘要
- 要写详细证据、文件锚点、run 路径、正反判断、为何如此
- 可以大量分节
- 可以把问题拆得很细
- 必须让后续窗口只看文档也能复原你的完整 reasoning
- 关键判断必须尽量附本地文件锚点、run 路径或外部 source
- 如果某条判断还只是推测，必须明确写成“推测/待验证”，不能伪装成已证实

你的 review 必须覆盖下面 11 个部分，缺一不可：

1. 赛题 requirement map
- 逐条核对赛题要求
- 区分：已实现、部分实现、字面满足但内部不合理、未证明、当前不该宣称

2. 当前创新点实现图谱
- structured communication
- non-text state transfer
- shared memory / replay
- tool / executor 机制
- statepool / StateRef
- 这些创新点哪些是真创新，哪些只是工程实现，哪些只是 support surface

3. 当前 evidence layer 分层
- formal headline evidence
- support evidence
- audit-only evidence
- 历史包 / 当前包 / fresh handoff 的关系
- 明确哪些不能混说

4. benchmark 设计审查
- 当前 benchmark 是否 single-variable
- text 对象是否真 text
- protocol 对象是否真 protocol
- 当前 headline 是否 contest-facing
- current report/aggregate 是否和 row-level 一致
- 是否存在 support surface 冒充 headline 的风险

5. task set 审查
- 当前 task 是否太薄
- 是否过于 incident-family / corpus-shaped / route-shaped
- 是否足以体现多 agent 协作收益
- 是否足以体现通信压缩、非文本状态、共享记忆三条主 claim
- scenario 是否只是壳，而不是评分重心

6. runtime / agent authenticity 审查
- Planner / Retriever / Executor / Summarizer 是否真在承担对应职责
- 是否存在过多 benchmark hint / gold-field leakage
- Retriever 是否只是 repo-local evidence packager
- Executor 是否仍主要是 route-to-playbook selector
- replay / reuse 是否过度依赖 scaffold

7. benchmark 与实现的错位点
- benchmark 问题
- task 设计问题
- code path 问题
- report wording / aggregation 问题
- 方法收益本身不足
必须分开，不许混写成一句“效果一般”

8. 赛题特化与泛化性审查
- 哪些地方是 contest-shaped 但还能接受
- 哪些地方已经过度特化，影响 claim 诚实性
- 哪些地方如果不重构就很难进入更可信 benchmark
- 必须给出文件级锚点

9. 基于赛题理解的外部文献 / repo / benchmark 对照
这一步是必做项，不是可选项。

先回答：

- 基于你对赛题的理解，当前最需要外部校准的判断是什么
- 你是要校准 benchmark object、task thickness、memory/replay 设计，还是多 agent structured communication 机制
- 为什么这些判断不能只靠本地实现自证

然后才允许上网检索。优先看论文、官方基准、官方 repo、官方文档。至少覆盖：

- benchmark / task thickness：
  - HotpotQA
  - MuSiQue
  - BRIGHT
  - LongMemEval
- retrieval / routing / tool selection：
  - semantic-router
  - LangGraph BigTool
  - Haystack
- memory / replay / layered retrieval：
  - Mem0
  - MemSearch
  - AgentRx
- 多 agent structured communication / intermediate representation / memory reuse 相关一手资料

另外必须显式看一类“赛题理解校准”资料：

- 多 agent benchmark / agent evaluation / tool-using agent evaluation 的官方论文或官方 benchmark 说明
- 目的是校准：什么样的 benchmark 才算在评“机制”，什么样的 benchmark 只是环境 / 任务壳
- 如果你认为现有 StateBus headline 与这些 benchmark 的评测对象存在错位，必须直接指出

外部检索要求：
- 不能变成抄框架
- 不能只列名单
- 必须形成对照表：
  - 我们当前问题
  - 外部对象
  - 借的机制
  - 为什么适合
  - 为什么不照搬
- 对每个重要方向，至少看 2 个一手对象再下判断；不要只凭一个 source 就定结论
- 如果外部对象之间互相冲突，必须把冲突点写进文档，而不是只选对自己有利的那一边

10. 是否需要重构
你必须正面回答：
- 当前是否只需要 patch
- 是否需要 benchmark reset
- 是否需要 task set 重构
- 是否需要 retrieval / executor / replay 的结构重构
- 是否需要缩减某些 claim
- 是否需要提出新的创新主线
如果需要重构，不要犹豫，直接说，并说明重构边界、优先级、代价、收益

11. 最终结论与行动树
最终必须给出明确结论，不能模糊收尾。只允许落到下面四类之一：
- A. benchmark 合格，当前方法值得继续深化
- B. benchmark 不够合格，先重设 benchmark/task contract，再谈方法
- C. 主线局部偏了，需要部分重构
- D. 当前主线与赛题主问题错位较大，需要较大重构或重立创新点

然后给出后续行动树：
- 必做
- 可做
- 不该做
- 当前停止项

命令与 benchmark 纪律：

- 这次 review 优先是读和判断，不是跑很多 benchmark
- 允许的最小验证只有：
```bash
python -m pytest -q
python -m runtime.smoke
```
- 只有当你需要验证某个明确判断时，才允许额外跑 deterministic `repeat=1`
- 只有在你已经给出审查结论、且需要验证“你的诊断是否真的对应一个行为问题”时，才允许一次正式 API benchmark
- 不允许频繁 rerun
- 不允许没有假设就跑 benchmark
- 所有 run 必须保留新 `--out` 路径

文档纪律：

- 本次 goal 的主要产物是详细文档，不是短答复
- 每完成一个大块分析，就应及时把结论写回文档
- 不要等全部看完才一次性草草写总结
- 文档里必须保留：
  - 你看了哪些本地材料
  - 你做了哪些外部检索
  - 你依赖了哪些证据包
  - 你为什么支持或反对当前主线
- 如果某个结论证据还不够，不要硬写死；应在文档里明确标成“证据不足/需要进一步验证”

分类纪律：
你识别出的每个问题，都必须归到下面之一：
- `contest closure required`
- `benchmark artifact`
- `task design issue`
- `implementation bug`
- `structural design mismatch`
- `reporting / narrative issue`
- `later enhancement`
- `not worth doing`

如果你判断“当前不是补丁能解决”，你应该做的是：
- 直接写出重构方向
- 明确哪些现有实现不该再维护为 headline
- 给出新的主线候选
- 说明为什么它更贴近赛题主问题

最后交付物必须包括：

1. 一份完整 review 结论
2. 一份“赛题理解小结”
3. requirement-by-requirement 状态表
4. benchmark/task/code/evidence 四层问题清单
5. 是否需要重构的明确判断
6. 外部 borrow list / contrast table
7. 一个按优先级排序的下一步行动树
8. 如果你认为该停掉某条线，明确写出 stop-line
9. 至少 3 份详细分析文档的实际落盘路径；如果你只写了 3 份，必须解释为什么第四份被合并
```
