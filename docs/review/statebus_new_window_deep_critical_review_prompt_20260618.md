# StateBus 新窗口 Prompt：深度质疑式 Review / 重建判断

日期：`2026-06-18`

适用范围：

- 仓库：`/home/qcrs/statebus/project`
- 环境：`/home/qcrs/statebus/conda-envs/statebus_host`
- 用途：给新窗口 / 新会话 / 新协作者直接使用

定位：

- 这不是继续沿 Goal1/Goal3 收口执行的 prompt。
- 这不是默认当前 `contest_honest_headline_v1` 已经足够，只差补交付的 prompt。
- 这不是让你继续小修小补 benchmark 的 prompt。

这是一个**被明确授权去质疑、去拆、去重建判断框架**的 prompt。

你被授权做的不是“回答问题”，而是：

1. 基于赛题要求，重新分析当前 StateBus 项目的真实 object；
2. 基于当前代码、docs、artifact、历史优化，重建当前项目真正的问题地图；
3. 明确指出哪些问题已经闭合，不要沿用过时结论；
4. 明确指出哪些问题仍然严重，而且不能因为“为了赛题收口”就被掩饰；
5. 允许直接质疑题目 object、benchmark object、text 定义、planner 角色、LangGraph 作用、创新点定义，甚至赛题本身的耦合方式；
6. 如果问题够大，允许直接得出：
   - 应分包；
   - 应降级 claim；
   - 应部分重构；
   - 或者赛题 object 本身就不合理。

硬边界：

- 不做真实部署
- 不做 openEuler VM
- 不做 Docker
- 不做 nsjail / 强沙箱终态
- 不做 hidden-state / KV 传递
- 不做真实交付打包
- 不直接进入“优化实现”
- 不在没有完成问题重建前就建议具体改代码
- 不把当前主线当成神圣不可动

---

```text
你现在进入 goal 模式。

工作目录固定为：
`/home/qcrs/statebus/project`

环境固定为：
`/home/qcrs/statebus/conda-envs/statebus_host`

进入后先执行：
```bash
source deploy/activate_statebus_host.sh
cd /home/qcrs/statebus/project
```

你这次的任务，不是继续做 Goal1 / Goal3 的执行收口，也不是继续补 API repeat、补 report surface、补 submission 交付。

你这次的任务是：

> 基于赛题要求、当前代码、当前 artifact、历史优化和当前主线边界，做一次“深度质疑式 review / 重建判断”。
> 目标不是替当前主线找补，而是搞清楚：
> - 当前真正的问题在哪里；
> - 当前对象到底证明了什么、没证明什么；
> - 哪些问题已经闭合，不要再拿旧结论说事；
> - 哪些问题仍然真实存在，而且不该因为赛题收口就被掩饰；
> - 如果问题够大，是否应该分包、降级 claim、或者局部重构。

你必须额外接受这一条非常重要的工作方式约束：

> `docs/analysis/statebus_deep_critical_question_map_20260618.md`
> 不是让你逐条“回答问题”的问答清单。
> 它的主要作用是：
> - 先帮你建立多角度的问题地图；
> - 先逼你从不同视角怀疑当前 object；
> - 先防止你过早收敛到单一结论；
> - 然后再回到代码、artifact、赛题要求里判断哪些问题真实存在、哪些问题是受控 benchmark 的自然代价、哪些问题值得继续推进。
>
> 换句话说：
> 你这次首先要做的是“建立判断框架”，不是“快速回答这些问题”。

你必须接受下面这些当前背景事实：

1. 当前项目已经不是“benchmark 没整理好、object 不纯、repeat 不足”的旧状态。
2. `contest_honest_headline_v1` 的 current headline 已完成：
   - object purity 收口
   - S1 runtime behavior proof
   - S2 prior-dependent action proof
   - current-headline memory/replay effect proof
   - deterministic repeat=10 formal closure
   - API repeat=10 closure
3. 当前 repo 的主线已经从“修 fairness / 修 report / 修 object”推进到“一个受控但较公平的 contest task object 已经闭合”。
4. 但这不等于：
   - Planner 已经强成立；
   - LangGraph 已经被充分发挥；
   - 当前 text 已经是外部纯文本 baseline；
   - 当前 task 已经是开放世界 agent benchmark；
   - 当前创新点已经完全被解释清楚。

你必须先读，不允许一上来给结论，不允许一上来给优化建议，不允许一上来改代码。

先按这个顺序读：

1. `AGENTS.md`
2. `README.md`
3. `docs/reference/题目.md`
4. `docs/analysis/statebus_deep_critical_question_map_20260618.md`
5. `docs/constraints/current_host_and_migration.md`
6. `docs/constraints/current_feature_scope.md`
7. `docs/review/statebus_new_window_guidance_20260617.md`
8. `docs/review/statebus_contest_aligned_review_20260614.md`
9. `docs/review/statebus_contest_first_refactor_execution_plan_20260617.md`
10. `docs/analysis/statebus_review_requirement_map_20260618.md`
11. `docs/analysis/statebus_review_benchmark_and_task_audit_20260618.md`
12. `docs/analysis/statebus_review_runtime_and_authenticity_20260618.md`
13. `docs/analysis/statebus_review_external_alignment_and_rebuild_20260618.md`

读法要求：

- 先读 `题目.md`，建立赛题硬约束；
- 紧接着读 `statebus_deep_critical_question_map_20260618.md`，建立“多角度怀疑框架”；
- 然后再读其余 review / analysis / constraints 文档，用本地材料去验证、修正、收敛这个问题地图；
- 不允许一开始就把问题地图读成“最终结论”；
- 也不允许一开始就挑一个问题直接深入，把其他角度忽略掉。

然后重点读这些代码锚点：

- `tasks/sample_tasks.py`
- `tasks/contest_family_spec.py`
- `tasks/local_corpus.py`
- `agents/sample_agents.py`
- `runtime/langgraph_adapter.py`
- `runtime/orchestrator.py`
- `runtime/executor_runtime.py`
- `eval/runner.py`
- `tests/test_smoke.py`

然后重点读这些当前关键 artifact：

- `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/`
- `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_runtime_det_r10_20260618_145812/`
- `/home/qcrs/statebus/runs/contest_honest_headline_goal3_memory_runtime_det_r1_20260618_143231/`
- `/home/qcrs/statebus/runs/contest_honest_headline_goal3_s2_runtime_det_r1_20260618_134109/`
- `/home/qcrs/statebus/runs/contest_honest_headline_goal3_s1_runtime_det_r1_20260618_123323/`

如有必要，你可以继续读旧 run / 旧 doc，但只能在完成上述阅读后进行。

你必须把下面这个问题作为本轮最高约束：

> 当前 StateBus 项目现在最真实的 object 是什么？
> 它到底应该被讲成：
> - 一个已经足够扎实的赛题主提交对象，
> - 一个受控但局限明显的 prototype，
> - 一个应该拆成 mainline + secondary + audit 的系统，
> - 还是一个因为赛题 object 本身不合理而需要重构叙事的项目？

再次强调：

- 你不是要把上面的一级问题逐条回答成 FAQ；
- 你是要先用这些问题搭一个“多视角分析框架”；
- 然后再回到本地 docs / code / artifact / 外部校准里，判断哪些怀疑成立、哪些怀疑过度、哪些怀疑指向真实重构需求。

你这次必须围绕下面这些一级问题做判断，不允许跳过：

1. 当前 benchmark 到底在测什么？
   - 测机制优势，还是受控工程优势？
   - 测真实复杂性，还是 contract/gate 复杂性？
   - route/corpus shaping 还剩多少？

2. 当前 text 到底是什么？
   - 它是不是我们真正想比较的“文本协作模式”？
   - 它是不是内部 fair comparator，而不是外部 pure-text baseline？
   - 当前没有更真实外部 text baseline，是难以公平实现、工程没做、还是一旦做真结论会变化？

3. 当前 Planner 到底有没有真实价值？
   - 它是规划角色，还是 contract compiler？
   - 它的弱是设计选择、benchmark 需要，还是能力不足？
   - 这个问题是否必须进入后续重构/分包？

4. 当前 LangGraph 到底扮演什么角色？
   - 是真实用到了，还是只是 execution shell？
   - 不用 LangGraph，当前 object 会变化多少？
   - 它是不是该被降级为 substrate，而不是继续被包装成创新点？

5. 当前 memory / replay 到底算不算强？
   - 当前 current headline 的 memory effect 到底证明到了哪一层？
   - 它是通用记忆复用，还是受控 reusable object 的 replay proof？
   - 后续应不应该继续作为主创新深挖？

6. 当前创新点到底想讲什么？
   - communication / state transfer / memory / planner / LangGraph / benchmark methodology 里，最强的一条到底是哪条？
   - 哪些点只是存在，不该升格为创新主轴？

7. 当前缺失的消融或解释实验是什么？
   - 它们是否是当前 submission 必需，还是 secondary enhancement？

8. 赛题本身是否存在不合理耦合？
   - 当前是不是被赛题 object 逼成了“什么都有一点，但没有一条完全纯”的系统？
   - 最合理的 story 是否本来就该拆成：
     - 一个 formal headline
     - 一个 planner secondary
     - 一个 memory secondary
     - 一个 external/open audit baseline

你必须先输出“执行前诊断”，再允许做进一步动作。诊断里必须明确回答：

1. 当前最强的真实主创新对象到底是哪一条
2. 当前哪些旧问题已经闭合，不应再拿过时结论当 blocker
3. 当前最值得警惕的 3-5 个深层问题是什么
4. 当前哪些问题是受控 benchmark 的必然代价，而不是 bug
5. 当前哪些问题如果不处理，会导致后续叙事继续失真
6. 当前是否值得继续维护现有主线 object，还是应该考虑分包 / 降级 / 重构

这里的“执行前诊断”不是最终裁决。

它必须首先产出：

1. 一个多角度问题框架；
2. 一个“当前最值得追的怀疑点优先级”；
3. 一个“哪些问题只是为了测试收敛而出现，不应误判为缺陷”的过滤层；
4. 然后才进入更具体的文档化判断。

这次不要急着下单一结论。

你必须把输出拆成至少 3 个详细文档，允许 4 个文档：

文档 A：`赛题要求与当前 object 重新对照`
- 当前到底满足了什么
- 哪些是 submission-level 满足
- 哪些只是存在、还不构成强 claim
- 哪些本身可能是赛题 object 写得不合理

文档 B：`benchmark / task / text 定义深度审计`
- 当前 benchmark 真正在测什么
- text 到底是什么
- 是否仍有 route/corpus shaping
- task thickness 哪些是真厚度，哪些是 contract 厚度
- 当前 benchmark 是否还需要改，还是应冻结为受控主提交对象

文档 C：`planner / LangGraph / runtime 角色重估`
- Planner 到底有没有真实作用
- LangGraph 到底是 substrate 还是方法对象
- 多 agent 角色是否真实必要
- 当前 runtime 的强处与弱处分别是什么

文档 D（可选但推荐）：`下一阶段路线重构建议`
- 如果维持当前主线，应该怎么收口
- 如果分包，应该怎么拆 mainline / secondary / audit
- 如果重构，应该先重构哪个 object
- 哪些东西明确不值得继续投入

你这次允许上网，但必须遵守：

- 先完成本地问题重建，再上网
- 外部检索必须服务于明确问题
- 优先论文、官方文档、官方 repo
- 不要先看二手博客

优先允许检索的问题方向：

1. 多跳 / connected benchmark：
   - HotpotQA
   - MuSiQue
   - BRIGHT
   - tau-bench
   - AgentBench
   - GAIA

2. 记忆 / replay / 历史依赖 benchmark：
   - LongMemEval
   - LongMemEval-V2
   - Mem0
   - MemSearch
   - AgentRx

3. routing / planner / open graph：
   - semantic-router
   - LangGraph BigTool
   - Haystack
   - AutoGen
   - CAMEL
   - MetaGPT

但请注意：

- 外部对象不是拿来抄实现；
- 也不是为了证明“我们方向肯定对”；
- 而是用来校准：
  - 我们当前 object 的弱点在哪里；
  - 哪些问题是当前受控 object 的自然代价；
  - 哪些问题说明我们可能真的该重构或分包。

这次严禁：

- 直接改代码
- 直接做 benchmark rerun，除非为核对关键事实绝对必要
- 重新打开 Docker / openEuler / VM / 真实部署
- 为了“看起来有进展”继续补 report surface
- 先入为主地维护当前主线 object
- 把 Goal1/Goal3 的闭合直接读成“所有深层问题都已解决”

你最后必须交付的不是一个“答案”，而是一个“判断框架”：

1. 当前项目到底完成到了哪一层
2. 当前真正的问题地图是什么
3. 哪些问题必须承认存在
4. 哪些问题不必再装成主 blocker
5. 当前是否应该：
   - 继续维持现有主线；
   - 分包；
   - 降级 claim；
   - 局部重构；
   - 或批判赛题 object 本身
6. 如果后续继续做，最值得优先做的只有哪 1-2 件事
7. 哪些方向明确不值得继续在主线上投入

重点提醒：

你的任务不是继续保护当前设计，而是先判断当前设计到底值不值得继续被保护。
```

---

## 使用建议

这份 prompt 适合：

- 新开窗口做“高压审稿人 / 批判性作者”视角的 review；
- 在决定是否开新 benchmark pack、planner-open pack、LangGraph native pack 之前，先重建问题地图；
- 避免新窗口一上来被当前 mainline 收口逻辑绑住。

这份 prompt 不适合：

- 继续做 Goal1 / Goal3 的执行迭代；
- 继续补 deterministic / API repeat；
- 继续小修 report 或 artifact 展示层。
