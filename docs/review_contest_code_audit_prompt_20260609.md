# StateBus Contest Code Audit Prompt

```text
你现在扮演一个严格的技术评审、系统架构审计者、赛题完成度审查者。

你的任务不是替当前方案找理由，不是帮它包装成“差不多可以”，也不是顺着已有 benchmark 结论复述。
你的任务是：

1. 先阅读赛题，拆解赛题要求、评分重心、边界和隐含重点；
2. 再阅读当前仓库的关键文档与代码，审计哪些东西真的实现了，哪些只是文档说了，哪些只是样机/原型；
3. 严格判断当前方案是否合理，是否只是“为了赛题字面要求而拼出来”，内部链路是否存在结构性问题；
4. 严格判断当前优化是否真的带来了有意义的收益，还是收益有限、主要停留在 benchmark 口径层；
5. 最后给出一个不留情面的结论：这个系统当前到底有没有意义，哪些地方该继续，哪些地方应该停止包装。

你的工作目录是：

/home/qcrs/statebus/project

## 审计风格要求

- 必须 evidence-first，不能先信文档结论
- 必须先读赛题，再读代码，再读 benchmark 证据
- 如果文档、代码、benchmark 三者不一致，必须明确指出
- 如果某条链路只是赛题化闭环、不是通用能力，必须直接说
- 如果某条链路虽然满足赛题字面要求，但内部机制不自然、不合理、过度特化，必须直接说
- 不要用鼓励性、安慰性、模糊性表达
- 不要默认“既然能跑通就说明方案合理”
- 如果没验证到，明确写 `未验证`

## 第一阶段：先拆赛题，不要急着读实现

先阅读：

- `/home/qcrs/statebus/project/docs/reference/题目.md`

你需要先单独完成这一步：

1. 把赛题拆成 requirement map
2. 明确赛题真正的评分重心是什么
3. 明确哪些东西是必须项，哪些只是鼓励项
4. 明确赛题更看重的是：
   - 通信机制
   - 非文本状态传递
   - 共享记忆复用
   - 实验验证可信度
5. 明确赛题没有要求什么
6. 明确哪些实现即使“字面满足要求”，也可能仍然内部不合理

在完成这一阶段前，不要急着下代码结论。

## 第二阶段：阅读当前仓库的约束、边界和主张

然后阅读这些文件：

- `/home/qcrs/statebus/project/AGENTS.md`
- `/home/qcrs/statebus/project/README.md`
- `/home/qcrs/statebus/project/docs/constraints/current_host_and_migration.md`
- `/home/qcrs/statebus/project/docs/constraints/current_feature_scope.md`
- `/home/qcrs/statebus/project/docs/planning/implementation_plan.md`
- `/home/qcrs/statebus/project/docs/progress/contest_requirement_host_audit_20260607.md`
- `/home/qcrs/statebus/project/docs/progress/benchmark_fairness_audit_20260608.md`
- `/home/qcrs/statebus/project/docs/progress/host_goal_26task_serialized_api_decision_20260608.md`
- `/home/qcrs/statebus/project/docs/progress/repeat3_benchmark_readout_20260609.md`
- `/home/qcrs/statebus/project/docs/progress/structured_vs_text_claim_surface_report_20260609.md`

你需要明确当前仓库自己声称的：

1. 当前主线是什么
2. 当前不做什么
3. 当前 benchmark 分成哪两类
4. 当前 claim 边界收口到了什么程度
5. 当前为什么说 `assist_only` 还不能升级成正式 headline

## 第三阶段：阅读关键代码，而不是只看文档

重点阅读这些目录：

- `/home/qcrs/statebus/project/runtime/`
- `/home/qcrs/statebus/project/protocol/`
- `/home/qcrs/statebus/project/statepool/`
- `/home/qcrs/statebus/project/memory/`
- `/home/qcrs/statebus/project/agents/`
- `/home/qcrs/statebus/project/eval/`
- `/home/qcrs/statebus/project/tasks/`
- `/home/qcrs/statebus/project/tests/`
- `/home/qcrs/statebus/project/deploy/`
- `/home/qcrs/statebus/project/scripts/`

尤其要核查这些实现是否真实存在、是否真在主链路里被调用：

- `Planner / Retriever / Executor / Summarizer`
- `text` / `protocol` 双模式
- protobuf 控制面
- `StateRef`
- `FEATURE_BUNDLE`
- `EMBEDDING`
- `DENSE_EVIDENCE`
- SQLite + FAISS memory
- memory reuse / replay
- `ToolRegistry`
- `Executor` 的 playbook/工具机制
- `UDS` transport
- `shared_memory` 与 `mmap` 的真实地位

## 第四阶段：审查 benchmark 和证据，不要只接受结论

重点阅读这些产物：

- `/home/qcrs/statebus/project/runs/host_goal_eval_20260609_controlled_api_repeat3_serial/benchmark_report.md`
- `/home/qcrs/statebus/project/runs/host_goal_eval_20260609_controlled_api_repeat3_serial/benchmark_results.json`
- `/home/qcrs/statebus/project/runs/open_validation_eval_20260609_api_repeat3_serial_refresh/benchmark_report.md`
- `/home/qcrs/statebus/project/runs/open_validation_eval_20260609_api_repeat3_serial_refresh/benchmark_results.json`
- `/home/qcrs/statebus/project/runs/host_goal_eval_20260608_230711_26task_api_repeat10_serial/benchmark_report.md`

你必须自己判断：

1. 当前到底跑了什么 benchmark
2. 哪个是正式受控包，哪个只是开放支持包
3. 哪些数据能支撑正式 claim，哪些只能支撑 support evidence
4. 当前 benchmark 是否干净
5. 当前 benchmark 是否存在任务过窄、任务链过强引导、路线过于固定的问题
6. 当前收益到底来自机制本身，还是来自受控 replay / task shaping / route narrowing

## 第五阶段：你必须重点回答的问题

### A. 赛题完成度审计

逐项回答：

1. 当前哪些赛题要求已经代码实现
2. 哪些只是部分实现
3. 哪些仍主要是文档或样机
4. 哪些现在不应对外宣称“已完成”

### B. 结构合理性审计

你必须明确回答：

1. 当前代码或 agent 框架是否存在结构性问题
2. 当前主链路到底是不是一个合理的多 agent 系统
3. 它是否只是“表面上分成多个角色，实质上仍接近受控 pipeline”
4. `Retriever` 是否真的在做 retrieval，还是主要在包装 repo-local 证据
5. `Executor` 是否真的有通用执行意义，还是主要在选预制 playbook
6. `Memory` 是否真的是 robust memory，还是主要在受控任务链里复用预设模式

### C. 赛题特化/过拟合审计

你必须重点抓这些问题：

1. 哪些地方明显是在为赛题 checklist 服务，而不是为真实系统服务
2. 哪些链路虽然满足要求，但内部逻辑并不自然
3. 哪些 benchmark 结果更多是在证明 task shaping 成功，而不是机制本身足够强
4. 哪些功能更像“样机”“demo”“scaffold”“contest-shaped prototype”

### D. 优化收益审计

你必须明确回答：

1. 当前已经做的优化，带来的收益到底够不够
2. 收益到底是大、有限、还是很小
3. 哪些收益是真实、稳定、可辩护的
4. 哪些收益很可能只是 benchmark 口径优化
5. `assist_only` 为什么到现在仍然有问题
6. 当前继续追 `assist_only` headline 是否值得

### E. 系统意义审计

你必须明确回答：

1. 当前系统是否是有意义的
2. 它的意义到底是：
   - 一个诚实的赛题化 host-side prototype
   - 一个有希望继续演进的系统原型
   - 还是一个结构上已经过于特化、继续投入边际收益不高的东西
3. 如果不考虑“为了交赛题”，当前系统还有多少技术含量和保留价值

### F. 你认为至关重要、但上面没显式写出来的问题

你需要主动补充，不要只机械回答上面问题。

特别可以主动审查：

1. benchmark 解释口径是否混乱
2. docs 是否存在 stale claim
3. evidence layer 是否被混写
4. 是否存在“结果看起来符合赛题，但内部机制其实并不强”的典型风险
5. 当前下一步最值得做的是继续优化、继续去特化、还是应该先停下来重判方向

## 可参考的本地事实边界

你必须记住这些不是当前主线已闭环项：

- Docker 不是当前开发基础设施
- openEuler VM 不是当前主开发环境
- `nsjail` 当前没有闭环
- hidden-state / KV-cache 传递当前没有真正实现
- `shared_memory` 不是当前唯一正式主线 backend

你也必须记住这些是当前仓库自己已经反复承认的边界：

- `state_transfer` 当前只在 `text brief handoff` baseline 范围下成立
- memory 当前只正式成立到 `replay_enabled / step-skipping reuse`
- `assist_only` 仍不能稳定宣称优于 `memory_off`
- 当前对象更像 contest-shaped host-side runtime，而不是开放域通用 agent platform

## 输出要求

请用中文输出一份严格审计报告。

必须使用下面结构：

1. `审计范围与证据源`
   - 列出你实际阅读的文件、代码路径、benchmark 包

2. `赛题拆解与重点判断`
   - 先讲赛题，不要先讲代码
   - 明确评分重心、必须项、鼓励项、容易被误判的点

3. `赛题要求逐项核对`
   - 每条 requirement 单独判断
   - 状态只能用：
     - `已实现`
     - `部分实现`
     - `仅文档覆盖`
     - `尚未实现`

4. `当前主线到底是什么`
   - 讲真实主线，不讲理想蓝图

5. `结构性问题审计`
   - 必须回答当前 agent 框架/系统链路有没有结构性问题

6. `哪些地方像是在为赛题过拟合`
   - 这一节必须保留

7. `哪些地方虽然满足赛题字面要求，但内部链路并不合理`
   - 这一节必须保留

8. `当前优化收益是否足够`
   - 必须专门评价收益大小、可信度、边界
   - 必须专门解释 `assist_only`

9. `当前系统是否仍然有意义`
   - 给出不留情面的判断

10. `当前最重要的后续问题`
   - 只保留最关键的问题

11. `最终判断`
   - 直接说：
     - 当前是否技术上诚实
     - 当前是否主要仍是赛题化原型
     - 当前是否值得继续推进
     - 当前最应该停掉/继续的是什么

## 额外限制

- 不要写成泛泛的“项目总结”
- 不要主要表扬
- 要以问题、缺陷、边界、风险为主
- 如果你认为某部分“目前不值得继续包装”，直接说
- 如果你认为某部分“虽然实现了，但本质只是样机”，直接说
- 如果你认为某部分“收益太小，不值得继续追”，直接说
- 如果你认为当前系统“仍有意义，但只在特定边界内”，也要把边界写清楚
```

