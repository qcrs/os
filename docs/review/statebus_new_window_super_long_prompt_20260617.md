# StateBus 新窗口超长版 Prompt

日期：`2026-06-17`

状态说明：

- 这份文档仍保留为 `2026-06-17` 的 benchmark-first 超长启动 prompt。
- 但它主要对应“先收 `benchmark correctness / object purity`”那一阶段。
- 如果你现在要新开窗口处理“`task thickness` 还没过，何时才允许评方法”这个阶段，优先使用：
  - `docs/review/statebus_new_window_benchmark_thickness_prompt_20260618.md`

用途：

- 给新窗口 / 新会话 / 新协作者的最终长版启动 prompt
- 目标是让对方先建立完整认知，再产出方案、流程和文档，而不是一上来进入局部实现

---

```text
你现在在 `/home/qcrs/statebus/project` 工作。

你必须只在本地 host 环境下思考和执行：
- 当前工作目录：`/home/qcrs/statebus/project`
- 本地 conda 环境：`/home/qcrs/statebus/conda-envs/statebus_host`
- 激活：`source deploy/activate_statebus_host.sh`
- 以 host 本地代码、文档、测试、benchmark 结果为准

明确边界：
- 不涉及真实 VM / openEuler
- 不涉及 Docker
- 不涉及 nsjail
- 不涉及系统外部署
- 不依赖外部环境来解释当前结果

你这次的任务不是直接改代码，也不是直接挑某个 bug 开修。
你要先理解当前项目为什么会混乱、当前真正的问题是什么、为什么现在第一阶段必须先建立 benchmark 方案和流程，而不是继续无边界修补。

====================
一、最高原则
====================

最高约束始终是赛题要求。

你必须始终先问：
1. 这是不是赛题允许的比较对象？
2. 这是不是公平比较？
3. 这是不是 support surface 被误包装成 headline？
4. 这是不是 benchmark 对象问题，而不是方法问题？
5. 这是不是任务太薄导致差异无法展开？

禁止：
- 为现有方法找补
- 因为能跑通就默认 claim 成立
- 因为某 pack 指标不好就直接判方法失败
- 把 audit-only / support-only / internal surface 升格为正式 headline
- 通过 hidden fallback、pack-specific override、support surface 包装 headline 来修指标
- 在 benchmark 没立住前就给方法下死刑

====================
二、你必须先理解的总背景
====================

当前项目里混了两种不同目标：

目标 A：证明“StateBus 这套机制真实成立”
- 多 Agent 真在协作
- protocol 真在传结构化信息
- typed state 真在生产 / 传递 / 消费
- replay 真在减少重复工作

目标 B：证明“StateBus 在 contest headline 上明显优于 text baseline”
- latency 更好
- token 更少
- correctness 更高
- 对比差异更明显

当前更接近事实的判断是：
- 目标 A 已经有不少真实进展
- 目标 B 还没有站稳
- 最近大量工作主要是在修 fairness、headline object、report 语义、support surface 分离、pack 读法边界
- 这些工作主要让系统更诚实、更可辩护，但不等于方法能力已经明显增强

所以你必须避免一上来就把“为什么还没有明显优势”直接归因到方法本身。

当前更合理的判断顺序是：
1. 先判断 benchmark 是否回答了对的问题
2. 再判断 benchmark 是否单变量、公平、对象纯净
3. 再判断 benchmark 是否足够厚，能放大差异
4. 最后才判断方法本身是否没有形成优势

====================
三、当前项目的真正混乱来源
====================

当前最重要的问题，不是单点 bug，而是：

**项目的认知地图已经落后于项目本身的复杂度。**

具体表现：

1. 太多 benchmark pack
2. 太多历史阶段文档
3. 太多“这个回答 A、不回答 B”的解释边界
4. 太多历史修补仍挂在当前主视野
5. 太多“值得保留”的创新点同时挤在当前主线里

因此：
- 每个局部看起来都合理
- 但整体越来越难回答“这个项目现在主线到底是什么”
- 每做一步都像在推进，但主线感越来越弱

你必须把这个项目理解成：

> 不是某个局部 bug 没修完，而是需要先重建认知地图和工作顺序。

====================
四、当前第一优先级
====================

当前第一优先级不是继续改 runtime，也不是继续扩 benchmark pack。

当前第一优先级是：

建立一套可信 benchmark 的方案和流程，并重新梳理当前主线 / 支线 / 延后项边界。

换句话说：
- 先收 benchmark
- 再看主线
- 再决定是否进入代码级重构

====================
五、必须优先阅读的文档
====================

请严格按顺序阅读。

第一组：新窗口理解当前混乱与工作顺序
1. `docs/review/statebus_new_window_guidance_20260617.md`
2. `docs/review/statebus_new_window_bootstrap_20260617.md`
3. `docs/analysis/statebus_current_thinking_reset_20260617.md`

第二组：benchmark 立项与主线边界
4. `docs/review/statebus_benchmark_charter_20260617.md`
5. `docs/review/statebus_reset_plan_from_full_scan_20260617.md`

第三组：当前全局扫描与最新审计
6. `docs/analysis/statebus_full_repo_scan_20260617.md`
7. `docs/analysis/honest_full_audit_20260617.md`
8. `docs/analysis/mainline_repeat3_analysis_20260617.md`

第四组：当前执行计划与赛题边界
9. `docs/review/statebus_contest_first_refactor_execution_plan_20260617.md`
10. `README.md`
11. `docs/reference/题目.md`
12. `docs/constraints/current_host_and_migration.md`
13. `docs/constraints/current_feature_scope.md`
14. `docs/planning/implementation_plan.md`

阅读时必须主动分层：
- Source of Truth
- Current Benchmark Spec
- Current Diagnosis
- Historical / Archive

不要把所有文档同权对待。

====================
六、必须重点参考的代码
====================

至少重点阅读：
- `agents/sample_agents.py`
- `runtime/orchestrator.py`
- `runtime/executor_runtime.py`
- `runtime/langgraph_adapter.py`
- `runtime/contracts.py`
- `runtime/reuse_contract.py`
- `eval/runner.py`
- `eval/metrics.py`
- `tasks/sample_tasks.py`
- `tasks/local_corpus.py`
- `tasks/contest_family_spec.py`
- `tasks/contest_family_spec.yaml`
- `tasks/contest_dual_mode_controlled_v3_benchmark.yaml`
- `tasks/memory_dual_mode_fairness_v3_benchmark.yaml`
- `tasks/planner_support_v3_benchmark.yaml`
- `tasks/text_definition_audit_v3_benchmark.yaml`
- `tasks/typed_state_mechanism_v3_benchmark.yaml`
- `tests/test_smoke.py`
- `tests/test_llm_runtime.py`
- `tests/test_state_channels_and_graph.py`

你必须重点回答：
1. 当前主路径到底是什么
2. 哪些模块是真热路径
3. 哪些模块只是支线、兼容层、audit 层
4. 哪些创新点有代码但不在主路径
5. benchmark / report 语义是否与代码和 row-level 一致

====================
七、必须重点参考的实验结果
====================

以当前最新主 run 为主：

- `/home/qcrs/statebus/runs/statebus_mainline_repeat3_suite_20260617_141158/`

必须至少阅读：
- `SUMMARY.md`
- `logs/full_pytest.log`
- `benchmarks/contest_honest_headline_v1/benchmark_report.md`
- `benchmarks/contest_dual_mode_controlled_v3/benchmark_report.md`
- `benchmarks/memory_dual_mode_fairness_v3/benchmark_report.md`
- `benchmarks/planner_support_v3/benchmark_report.md`
- `benchmarks/text_definition_audit_v3/benchmark_report.md`
- `benchmarks/typed_state_mechanism_v3/benchmark_report.md`
- `benchmarks/typed_state_consumer_sensitivity_v3/benchmark_report.md`

必要时必须继续下钻：
- 对应 `benchmark_results.json`

你必须对实验结果做这样的解读：
1. 哪些结果是在说明 benchmark 对象还不够好
2. 哪些结果是在说明任务太薄
3. 哪些结果是在说明 report 语义有错
4. 哪些结果才有资格被读成方法表现

不要只看 markdown 报告下结论。

====================
八、当前建议的唯一主问题
====================

你必须围绕下面这句作为当前唯一主问题来组织判断：

“在一个可信、单变量、足够厚的赛题 benchmark 上，structured protocol 是否比 pure-text handoff 更有优势？”

围绕这句主问题：

当前应进入主线裁决的资产：
- contest headline object
- typed-state minimal mechanism
- memory replay（仅当它确实在主路径、且确实属于主问题）

当前可以保留但不进入本轮裁决的东西：
- planner openness
- open extension
- LangGraph extension
- 更丰富 typed-state
- git 风格管理
- 其他赛题加分创新点

注意：
- “保留”不等于“当前主线化”
- 不要把所有创新点同时压进本轮主问题

====================
九、你必须先产出的内容
====================

第一阶段不要直接进入大规模实现。

你必须先产出以下内容，并尽量落成仓库文档：

1. 一份可信 benchmark 立项方案
   - 什么样的 benchmark 才算可信
   - 什么情况下 benchmark 直接判不合格
   - 什么情况下 benchmark 合格但方法无优势
   - 什么情况下 benchmark 合格且方法有局部优势
   - 什么情况下才允许说方法有稳定 headline 优势

2. 一份 headline benchmark 最小对象定义
   - 最少几跳协作
   - 是否必须有跨任务依赖
   - 是否必须有竞争性 route
   - text / protocol 两侧各自允许看到什么
   - 哪些能力双方都允许，哪些不允许

3. 一份本轮不进入裁决的支线清单
   - 把保留但延后的东西写死
   - 防止主线再次发散

4. 一份当前项目主线 / 支线 / 延后项 / 历史包袱的重分类建议
   - 哪些是真资产
   - 哪些只是值得保留
   - 哪些应归档
   - 哪些不应继续追

5. 一份“第一阶段工作流程”
   - 先读什么
   - 先判断什么
   - 先落哪类文档
   - 什么时候才允许进入代码实现

建议你把这些产出写成文档，而不是只回一句总结。

====================
十、建议的文档输出结构
====================

如果需要写文档，建议至少分成以下四类：

1. `Current Thinking / Diagnosis`
   - 讲当前项目为什么乱
   - 讲当前主线到底卡在哪里
   - 讲当前最重要的认知收口是什么

2. `Benchmark Charter`
   - 讲什么叫可信 benchmark
   - 讲成功标准 / 失败标准 / 对象纯净 / 任务厚度

3. `Mainline / Sideline Boundary`
   - 讲哪些东西进入本轮裁决
   - 哪些东西保留但延后
   - 哪些东西应归档

4. `First-Phase Working Plan`
   - 讲第一阶段的工作流程
   - 讲先 benchmark 再主线，再决定是否实现

====================
十一、输出要求
====================

请先做分析，不要一上来就改代码。

你的输出应包括：

1. `Overall Judgment`
   - 当前项目最核心的问题是什么
   - 当前第一阶段最应该做什么

2. `Findings`
   - 按严重性排序
   - 必须区分：
     - benchmark 对象问题
     - 任务厚度问题
     - report / metric 语义问题
     - 方法本身问题
     - 文档 / 叙事 / 主线边界问题

3. `Recommended First-Phase Deliverables`
   - benchmark 立项方案
   - headline 最小对象定义
   - 支线延后清单
   - 主线重分类建议
   - 第一阶段工作流程

4. `Recommended Working Order`
   - 明确先做什么、后做什么
   - 先 benchmark 再主线，再决定是否实现

5. `What Not To Do Now`
   - 当前不该先做什么
   - 当前不该继续扩什么

如有必要，请先把你的分析写入仓库文档，再回答。

====================
十二、明确边界
====================

当前明确不做：
- 真实 VM / openEuler 路线
- Docker / nsjail / 系统外部署
- 继续扩更多 benchmark pack
- 直接进行大规模 runtime 重构
- 在 benchmark 没立住前直接给方法下死刑

你必须把“先建立可信 benchmark 和主线边界，再判断方法”作为第一原则。
```
