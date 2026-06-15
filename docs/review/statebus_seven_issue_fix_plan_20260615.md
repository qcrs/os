# StateBus 七个问题修复方案与执行顺序

日期：2026-06-15

适用范围：当前 `main` / `feat/contest-audit-hardening-20260615` 一线代码、任务包、报告合同、审计口径。

前置阅读：

- [题目.md](/home/qcrs/statebus/project/docs/reference/题目.md:1)
- [statebus_remaining_issues_and_solutions_20260615.md](/home/qcrs/statebus/project/docs/review/statebus_remaining_issues_and_solutions_20260615.md:1)
- [full_system_audit_20260615.md](/home/qcrs/statebus/project/docs/analysis/full_system_audit_20260615.md:1)
- [experimental_anomalies_20260615.md](/home/qcrs/statebus/project/docs/analysis/experimental_anomalies_20260615.md:1)

---

## 一、最终决定

这次不做“小修小补”，直接按下面的结构收口：

1. `contest_dual_mode_controlled_v3`
   - 保留为唯一 formal headline。
   - 只承担 `低开销通信 + 非文本状态传递` 两条主线。
   - 不重新塞回 memory headline。
   - 但任务和 corpus 要重做，否则 headline 不成立。

2. `planner_support_v3`
   - 保留为 formal secondary planner surface。
   - 用来回答“系统确实覆盖了规划角色”，不把 planner 开放性混进 contest headline。

3. `memory_policy_controlled_v3`
   - 升格为唯一 formal secondary memory surface。
   - 用 contest-family 同源连续任务，固定 `mode=protocol` 和 `state_packet_minimal`，只改 `runtime_reuse_contract`。
   - memory 结论从这里出，不从 contest 包里偷带。

4. `typed_state_mechanism_v3`
   - 恢复为 formal secondary，但 claim 范围必须收窄。
   - 只回答：`minimal EXECUTOR_DECISION_PACKET` 是否真实生产、传递、消费。
   - 不回答效率，不回答 replay，不回答 external baseline。

5. `memory_dual_mode_fairness_v3`
   - 继续保留，但明确降为 `audit_only`。
   - 只做 object parity / restore compatibility 检查。
   - 不再承担 replay 效率结论。

6. `open surface`
   - 不修成“真实外部基线”。
   - 当前 `eval/open_runner.py` 永久定义为 `audit_only engineering simulation surface`。
   - 如果以后要做真实外部基线，必须新建 runner、新 artifact、新报告入口。

7. benchmark 主攻方向
   - 不是去追求更多 pack。
   - 是先把 `contest task/corpus` 重构到真的能让 protocol state 有正确率收益空间。

这套收口方式最稳，因为它和赛题三条评分主线是一一对应的：

- `通信效率 25分`：formal headline 里的 `text vs protocol`
- `状态传递创新 20分`：formal headline + typed-state formal secondary
- `记忆复用效果 20分`：memory formal secondary
- `实验验证 15分`：任务难度、变量控制、报告口径一起保证

对应赛题原文见 [题目.md](/home/qcrs/statebus/project/docs/reference/题目.md:2)、[题目.md](/home/qcrs/statebus/project/docs/reference/题目.md:35)。

---

## 二、七个问题的最终修法

### 问题 1：Contest 包 Planner 仍然被绕过

结论：

- 不把 `contest_dual_mode_controlled_v3` 改成 `plan_source_default: llm`。
- 保持 contest headline 上 `plan_source_default: yaml`，因为它当前就是复合对比面，不应再引入第三变量。
- Planner 证据单独放在 `planner_support_v3`。

原因：

- 当前 contest 包明确写死 `plan_source_default: yaml`，见 [contest_dual_mode_controlled_v3_benchmark.yaml](/home/qcrs/statebus/project/tasks/contest_dual_mode_controlled_v3_benchmark.yaml:18)。
- 编排层会直接短路到 `build_plan(task)`，见 [orchestrator.py](/home/qcrs/statebus/project/runtime/orchestrator.py:1235)。
- 赛题要求“覆盖规划角色”，但不要求 formal headline 一定把 planner openness 也揉进去；否则变量就失控了，和“相同任务条件下对比”冲突，见 [题目.md](/home/qcrs/statebus/project/docs/reference/题目.md:14)。

解决方案：

1. 保持 contest 包 YAML 不动这条主设定。
2. 重做 `planner_support_v3`，保证它是严格单变量：
   - 固定 `mode`
   - 固定 `handoff_profile`
   - 固定 task object
   - 只改 `plan_source=yaml|llm`
3. 至少保留一个 4-step 诊断 case，证明 planner 不是“永远三步模板”。

落地类型：

- `contest` 这里主要是口径决定，不是代码问题。
- `planner_support_v3` 需要改 YAML，少量 runner 报告文案可跟进。

---

### 问题 2：Corpus 预标签仍然影响运行时检索

结论：

- 这不是“小问题”，而是 formal benchmark 真实性的核心问题之一。
- 必须把 formal corpus 里的 `route_hint/tool_name` 从 runtime 可读面彻底拿掉。
- `eval label` 可以保留，但 runtime 不得再接触。

原因：

- `TaskSetMetadata.runtime_hint_allowed` 已经把 formal pack 挡在 audit-only 之外，见 [sample_tasks.py](/home/qcrs/statebus/project/tasks/sample_tasks.py:248)。
- `_resolve_runtime_corpus_hints()` 在 formal pack 下确实会返回空，见 [sample_agents.py](/home/qcrs/statebus/project/agents/sample_agents.py:1817)。
- 但 corpus object 仍然带 `route_hint/tool_name` 字段，见 [local_corpus.py](/home/qcrs/statebus/project/tasks/local_corpus.py:16)。
- 更重要的是 `retrieve_corpus_docs()` 仍然给 `corpus_doc_ids` 一个 `preference_bonus`，见 [local_corpus.py](/home/qcrs/statebus/project/tasks/local_corpus.py:103)。
- 这说明 formal 检索空间仍被任务设计强塑形，不是真正开放的 route disambiguation。

解决方案：

1. formal corpus 文件删除 runtime 可见的 `route_hint` / `tool_name` 字段。
2. 如果评测需要标签，新建 eval-only 字段：
   - `eval_route_label`
   - `eval_tool_label`
3. `CorpusDoc` 结构跟着改，formal runtime 对 hint 字段零暴露。
4. `extract_corpus_feature_hints()` 保留，但仅限 audit/training surface。
5. `retrieve_corpus_docs()` 去掉 formal path 的 `preference_bonus`。
6. contest / memory formal packs 不再用“预定 doc_id 集合 + bonus”把答案路径提前压窄。

落地类型：

- 这是代码 + corpus 双改，不是只改 YAML。

优先级：

- 与问题 3 并列最高。

---

### 问题 3：Task 难度不足

结论：

- 这是当前最急迫的问题。
- 不能直接换成外部 benchmark。
- 最终方案是：**自己设计 repo-local benchmark，但显式借鉴外部 benchmark 的构造原则。**

原因：

- 当前 query 明显泄漏 route 关键词，见 [contest_dual_mode_controlled_v3_benchmark.yaml](/home/qcrs/statebus/project/tasks/contest_dual_mode_controlled_v3_benchmark.yaml:31)。
- `acceptable_routes` 基本塌缩为单一路由，见 [contest_dual_mode_controlled_v3_benchmark.yaml](/home/qcrs/statebus/project/tasks/contest_dual_mode_controlled_v3_benchmark.yaml:58)。
- 赛题真正要的是“非文本状态传递是否能减少中间状态到文本再解析的损耗”，见 [题目.md](/home/qcrs/statebus/project/docs/reference/题目.md:3)。如果题目本身没有 route/tool 分歧压力，`EXECUTOR_DECISION_PACKET` 再干净也不会提高正确率。

最终设计原则：

1. `route ambiguity`
   - 每题至少 2-3 个 route family 都会被 query 词法命中。
   - 必须靠证据组合和 provenance 才能区分。

2. `tool ambiguity within route`
   - 同一路由下允许 2 个以上可接受工具分支。
   - protocol packet 里的 candidate ranking / route provenance 才会有价值。

3. `cross-task reuse dependency`
   - 第二题必须识别第一题产出的结论、策略或排除项。
   - 不是简单相似 query。

4. distractor 要跨 family，不是同 family 弱干扰。

5. `acceptable_routes` / `acceptable_tools` 可保留有限歧义，但必须显式声明。

对外部 benchmark 的决定：

- 不直接使用外部数据集替换 StateBus benchmark。
- 只参考构造方法：
  - HotpotQA：多证据组合
  - MuSiQue：分解式多跳、避免单跳猜中
  - BRIGHT：高相似候选中的鉴别性检索

为什么不能直接换外部数据集：

- 它们没有 `route/tool/replay` 合同。
- 不能直接映射到 StateBus 的 Executor / Memory policy 面。
- 会把 benchmark 变成“问答数据集套壳”，反而偏离赛题“系统层机制”对象，见 [题目.md](/home/qcrs/statebus/project/docs/reference/题目.md:4)。

落地类型：

- 这是 corpus + task YAML 的重点重做。
- 不是外部网页查一堆数据就能替代的工作。

---

### 问题 4：Contest 包 memory/reuse 全部关闭

结论：

- 不把 memory 重新塞回 `contest_dual_mode_controlled_v3`。
- contest headline 继续只讲 `communication + state_transfer`。
- memory 结论全部由 `memory_policy_controlled_v3` 承担。

原因：

- 当前 contest 包所有行都写的是 `runtime_reuse_contract: reuse_disabled`，见 [contest_dual_mode_controlled_v3_benchmark.yaml](/home/qcrs/statebus/project/tasks/contest_dual_mode_controlled_v3_benchmark.yaml:49)。
- 这不是“忘了开”，而是为了避免 `mode + handoff_object + memory policy` 三重变量缠绕。
- 赛题确实要求验证共享记忆复用，见 [题目.md](/home/qcrs/statebus/project/docs/reference/题目.md:17) 和 [题目.md](/home/qcrs/statebus/project/docs/reference/题目.md:35)，但这个验证不一定必须放在 dual-mode headline 上。

解决方案：

1. contest headline 不动 memory 关闭策略。
2. `memory_policy_controlled_v3` 重做任务来源：
   - 与 contest family 同源
   - 明确连续任务依赖
   - 固定 `mode=protocol`
   - 固定 `transfer_strategy=state_packet_minimal`
   - 只改 `runtime_reuse_contract`
3. formal memory 表头只读：
   - `replay_apply_rate`
   - `skipped_step_count`
   - `reuse_gain`
4. assist 命中只做辅指标，不再冒充 headline。

落地类型：

- 这里的结构决定是文档/合同层。
- 真正工作量在 memory pack 重做，不在 contest pack。

---

### 问题 5：memory_dual_mode_fairness_v3 变量缠绕

结论：

- 这个包不再承担任何 formal memory claim。
- 明确固定为 `audit_only object-parity / restore-compatibility surface`。

原因：

- 它显式同时改变 `mode + runtime_reuse_contract + restore_object_class`，见 [memory_dual_mode_fairness_v3_benchmark.yaml](/home/qcrs/statebus/project/tasks/memory_dual_mode_fairness_v3_benchmark.yaml:12)。
- 审计报告已经指出三变量缠绕，无法归因，见 [full_system_audit_20260615.md](/home/qcrs/statebus/project/docs/analysis/full_system_audit_20260615.md:259)。

解决方案：

1. 保留这个包，但只回答：
   - text / protocol 是否各自 restore 了兼容对象
   - object parity 是否成立
   - restore boundary 是否被越界
2. 报告中明确写：
   - 不读成 replay efficiency
   - 不读成 text-vs-protocol fairness
   - 不读成 memory headline
3. 如果需要更清楚，可考虑把 pack 名字直接改成 `memory_restore_boundary_audit_v3`。

落地类型：

- 主要是 pack 命名、README、report wording。
- 不需要新增 runtime 机制。

---

### 问题 6：typed_state_mechanism_v3 formal 空位

结论：

- 恢复 formal secondary 身份。
- 但 claim 必须缩成一句话：
  - `minimal executor-facing non-text packet is produced, transferred, and consumed`

原因：

- 当前 pack 自己的合同仍然是严格单变量，`variable_axes = [handoff_object]`，见 [typed_state_mechanism_v3_benchmark.yaml](/home/qcrs/statebus/project/tasks/typed_state_mechanism_v3_benchmark.yaml:8)。
- runner 报告也已经把它写成 formal-secondary typed-state mechanism pack，见 [runner.py](/home/qcrs/statebus/project/eval/runner.py:4781)。
- 但 YAML 的 `public_surface` 现在却是 `audit_only`，见 [typed_state_mechanism_v3_benchmark.yaml](/home/qcrs/statebus/project/tasks/typed_state_mechanism_v3_benchmark.yaml:11)；这和报告口径已经不一致。

解决方案：

1. 把 `typed_state_mechanism_v3` 的 `public_surface` 改回 formal secondary 口径。
2. `PUBLIC_SURFACE_ALIASES` 不再把 `formal_secondary_typed_state_mechanism` 映射到 `audit_only`，见 [sample_tasks.py](/home/qcrs/statebus/project/tasks/sample_tasks.py:104)。
3. 同步更新 [tasks/README.md](/home/qcrs/statebus/project/tasks/README.md:63) 与报告模板，明确 stopline：
   - 不读成 dual-mode headline
   - 不读成 efficiency claim
   - 不读成 replay claim

落地类型：

- 主要是 YAML + metadata alias + 报告口径。
- 不需要新机制代码。

---

### 问题 7：Open surface 仍是 deterministic stub

结论：

- 当前 open surface 不修。
- 直接改定位。

准确含义：

- 它不是“真实外部系统对比”。
- 它是一个 deterministic engineering simulator。
- 代码直接用任务预期答案作为 route/tool，再用 `_token_estimate()` 估 token。

硬证据：

- manifest 明写 `data_source = deterministic_oracle`，见 [open_runner.py](/home/qcrs/statebus/project/eval/open_runner.py:295)。
- route/tool 直接取 `task.primary_expected_route / task.primary_expected_tool`，见 [open_runner.py](/home/qcrs/statebus/project/eval/open_runner.py:416)。
- token 不来自真实模型，而是 `_token_estimate()`，见 [open_runner.py](/home/qcrs/statebus/project/eval/open_runner.py:641)。

解决方案：

1. 当前所有 open surface 统一标成：
   - `audit_only`
   - `engineering simulation`
   - `not real-LLM headline evidence`
2. 不进入 formal v3 headline。
3. 不进入 external baseline 正式叙事。
4. 如果以后要做真实外部基线：
   - 新建 runner
   - 新建 artifact 目录
   - 新建 surface 名称
   - 使用真实 backend 与真实 token/latency 记录
   - 不复用当前 `open_runner.py`

落地类型：

- 当前阶段只改口径、README、report gating。
- 不做 open runner 功能重建。

---

## 三、实施顺序

顺序不能乱，按这个来：

### 阶段 1：先修合同和报告口径

目标：

- 先把“什么能说、什么不能说”锁死。

动作：

1. 修 `typed_state_mechanism_v3` 的 public surface 回 formal secondary。
2. 固化 `memory_dual_mode_fairness_v3 = audit_only`。
3. 固化 `open surface = audit_only engineering simulation`。
4. runner/report 强制输出：
   - `public_surface`
   - `single_variable`
   - `variable_axes`
   - `data_source`
   - `artifact_reuse`
5. 所有 formal/report 文档同步 stopline。

优先文件：

- [tasks/sample_tasks.py](/home/qcrs/statebus/project/tasks/sample_tasks.py:97)
- [eval/runner.py](/home/qcrs/statebus/project/eval/runner.py:4157)
- [tasks/typed_state_mechanism_v3_benchmark.yaml](/home/qcrs/statebus/project/tasks/typed_state_mechanism_v3_benchmark.yaml:1)
- [tasks/memory_dual_mode_fairness_v3_benchmark.yaml](/home/qcrs/statebus/project/tasks/memory_dual_mode_fairness_v3_benchmark.yaml:1)
- [tasks/README.md](/home/qcrs/statebus/project/tasks/README.md:1)

### 阶段 2：再修 runtime 主路径里的伪机制

目标：

- 让 protocol 主路径的 typed-state 使用是真正 hot path，不是口头存在。

动作：

1. formal corpus 去掉 runtime hint 暴露。
2. formal retrieval path 去掉 `preference_bonus`。
3. executor 继续只吃 packet，不回退重推 route/tool。
4. summarizer 继续只吃 compact structured digest，不回退“结构化转长文本”。

优先文件：

- [tasks/local_corpus.py](/home/qcrs/statebus/project/tasks/local_corpus.py:16)
- [agents/sample_agents.py](/home/qcrs/statebus/project/agents/sample_agents.py:307)
- [runtime/executor_runtime.py](/home/qcrs/statebus/project/runtime/executor_runtime.py:21)

### 阶段 3：重做 contest task 和 corpus

目标：

- 让 protocol 的非文本状态在 correctness 上有展示空间。

动作：

1. 重写 `contest_release_regression_corpus.yaml`
2. 重写 `contest_dual_mode_controlled_v3_benchmark.yaml`
3. 为 `memory_policy_controlled_v3` 设计同源连续任务
4. 把 ambiguity / multi-evidence / reuse dependency 真做出来

优先文件：

- `tasks/contest_release_regression_corpus.yaml`
- [tasks/contest_dual_mode_controlled_v3_benchmark.yaml](/home/qcrs/statebus/project/tasks/contest_dual_mode_controlled_v3_benchmark.yaml:1)
- [tasks/memory_policy_controlled_v3_benchmark.yaml](/home/qcrs/statebus/project/tasks/memory_policy_controlled_v3_benchmark.yaml:1)

### 阶段 4：最后补测试和文档

目标：

- 防止以后回退到“有 packet 但没价值”“有 memory 但 headline 不清”的状态。

必须补的测试：

1. formal pack 禁止 runtime hint 消费
2. formal retrieval path 不再用 preference bonus
3. planner_support_v3 至少一个 4-step plan
4. memory_policy_controlled_v3 只改 `runtime_reuse_contract`
5. typed_state_mechanism_v3 formal metadata 合同
6. open surface manifest 必带 `data_source/artifact_reuse`

---

## 四、哪些必须查网页，哪些不用查

### 必须参考

只需要参考这 4 类，目的非常明确：

1. HotpotQA
   - 用途：参考“多证据组合”的任务构造方法。
   - 不是拿来替换数据集。
   - 链接：https://hotpotqa.github.io/

2. MuSiQue
   - 用途：参考“多跳拆分、避免单跳词法泄漏”的构造原则。
   - 链接：https://arxiv.org/abs/2108.00573

3. BRIGHT
   - 用途：参考“高相似候选之间的鉴别性检索”怎么设计。
   - 链接：https://brightbenchmark.github.io/

4. LangGraph 官方文档
   - 用途：只用来支持一个口径：
     - orchestration / graph structure 演示不等于真实 benchmark evidence
   - 不是为了抄 benchmark。
   - 链接：https://langchain-ai.github.io/langgraph/

### 可参考但不是必须

1. 任何 retrieval benchmark survey
   - 只在你需要补“为什么要高相似候选歧义”时再看。

2. Agent framework 文档
   - 只在写 open surface stopline 时做辅助说明。

### 明确不需要再花时间查

1. Docker / openEuler / nsjail 相关网页
   - 这轮不解决。

2. 大而全的外部多 agent benchmark 列表
   - 对当前 task/corpus 重构帮助不大。

3. “如何让 open runner 更像真实 LLM” 的资料
   - 当前决定是不修它，只改定位。

---

## 五、直接执行清单

按优先级，下一步就做这些：

1. 修 `typed_state_mechanism_v3` 的 formal secondary metadata 与 alias。
2. 把 `memory_dual_mode_fairness_v3` 和 open surfaces 的 stopline 写死到 report/docs。
3. 从 formal corpus 移除 runtime hint 字段，并去掉 formal retrieval 的 `preference_bonus`。
4. 重写 `contest_dual_mode_controlled_v3` 的 tasks：
   - 至少 2-3 个 route 可词法命中
   - 同 route 多工具
   - 第二题依赖第一题产出
5. 重写 `memory_policy_controlled_v3`，作为唯一正式 memory evidence。
6. 最后补测试，锁死 formal/audit surface 边界。

---

## 六、最后的判断

如果只修报告口径，不重做 task/corpus，这套 benchmark 仍然很难拿下赛题里的 `状态传递创新` 和 `实验验证` 两项高分。

如果只把题目“做难”，但不拆清 surface 和 memory 口径，最后又会回到“结果很多，但 claim 不可 defend”。

所以真正的主线只有一条：

**先锁口径，再清 runtime 伪机制，再重做 contest task/corpus，最后用独立 memory surface 讲 replay。**
