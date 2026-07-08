# StateBus 赛题优先重构执行计划

日期：2026-06-17

适用范围：`/home/qcrs/statebus/project`

主合同优先级：

1. `docs/reference/题目.md`
2. `docs/review/statebus_contest_remaining_closure_plan_20260615.md`
3. `docs/review/statebus_full_restructure_execution_plan_20260616.md`
4. 当前代码、测试、`/home/qcrs/statebus/runs/host_full_api_repeat3_v3_20260616_221231/` 结果

本计划的定位：

- 这是下一轮实现时应直接执行的主计划。
- 它以赛题对象为最高约束，不为当前方法找补。
- 它回答上一轮 review 留下的开放问题，并把后续实现路线收敛成一条主线。
- 它只覆盖当前 host 本地 StateBus 主线；不扩展到 VM / openEuler / Docker / `nsjail`。

---

## 1. 结论先说

当前仓库不是“赛题方向错了”，也不是“只剩文案问题”。

当前真实状态是：

1. 系统主骨架已经够格：
   - 至少 3 个 agent 和多角色协作成立
   - 结构化协议成立
   - 非文本状态传递成立
   - 共享记忆与 replay 主线成立
   - planner / semantic-role / validate contract 已接通
2. 但当前正式 contest headline 仍然没有收硬：
   - `contest_honest_headline_v1` 已经接过 contest-facing formal headline
   - 它当前仍然只到 repeat=3，正式 stability gate 还是 `not_yet`
   - `contest_dual_mode_controlled_v3` 已降为 internal controlled surface，不再承担赛题 pure-text headline
3. 因此下一轮最该做的不是继续修 support surface，也不是先追更多指标，而是：
   - **保持 `contest_honest_headline_v1` 作为唯一正式 headline**
   - **同步清洗 reporting 语义**
   - **在收口后补 formal repeat=10 stability gate**

一句话收口：

> 当前 headline 对象已经收正；下一轮应先把报表语义和 formal stability gate 收硬，再谈更后面的任务厚化与 correctness 提升。

---

## 2. 赛题到底要什么

按 `docs/reference/题目.md`，赛题真正要的不是开放平台，也不是简单 workflow。

赛题硬要求的对象是：

1. 一个真实可运行的多 agent 协作系统
   - 至少 3 个 agent
   - 至少覆盖规划 / 检索 / 执行 / 总结中的 3 类
   - 能完成多步骤复杂任务
2. 一套结构化通信协议
   - 至少覆盖动作、参数、结果、能力描述
   - 有握手、能力发现或协议映射
   - 不能只靠自然语言长文本透传全部协作信息
3. 两种协作模式
   - 纯文本协作模式
   - 结构化协议协作模式
   - 必须在相同任务条件下可复现实验对比
4. 一种真实被生成、传递、接收、使用的非文本中间状态
5. 一套共享记忆
   - 可存储
   - 可检索
   - 可跨任务复用
6. 至少 2 组连续关联任务
   - 用来证明减少重复计算、降低开销、提升效率
7. 一套可信的实验
   - 消息次数
   - 文本 token/字符开销
   - 非文本状态次数与规模
   - 总耗时
   - 记忆命中率
   - 整体性能提升
8. 至少 10 轮稳定执行

这意味着：

- 赛题最关心的是“系统层机制是否真实成立，并在相同任务条件下比传统纯文本协作更合适”
- 赛题不要求开放世界 benchmark
- 赛题不要求 hidden-state / KV 作为主路线
- 赛题也不允许我们把 support surface、audit surface、工程中间层拿来冒充正式 headline

---

## 3. 开放问题的最终答案

### 3.1 当前 formal headline 里的 text object 应该定义成什么

答案：

> 如果它要承担赛题正式“纯文本协作模式”角色，就必须是传统 natural-language multi-agent handoff，而不是结构化决策字段的文本化载体。

因此：

- 当前 `text_strict_pure_lane` 不应继续按赛题 formal headline 的 pure-text baseline 使用
- 它可以保留，但只能作为
  - internal controlled composite surface
  - 或者 support / audit surface

原因：

- 当前 `text_strict_pure_lane` 明写 `Route / Tool / Route source / Route confidence / Retrieved docs`
- 这不是传统 pure-text 协作
- 这本质上是“结构化决策经文本串行化后的显式 handoff”

### 3.2 赛题正式 headline 是否必须留在当前 `contest_dual_mode_controlled_v3` 里

答案：

> 不必须。更合理的做法是二选一，但推荐第二种。

方案 A：

- 彻底重做 `contest_dual_mode_controlled_v3`
- 让它变成真正 honest 的 pure-text vs structured dual-mode headline

方案 B，推荐：

- 把当前 `contest_dual_mode_controlled_v3` 降格为
  - `internal_controlled_composite`
  - 或 formal-secondary controlled surface
- 新建一个真正 contest-facing 的 formal headline pack
  - `text_natural_contest_headline_v1`
  - vs `state_packet_minimal_contest_headline_v1`

推荐方案 B 的原因：

1. 当前 pack 的任务对象、handoff object、report wording 已经深度耦合
2. 强行在原 pack 上改，容易一边修对象一边污染旧比较
3. 分 pack 后可以更清楚地区分：
   - internal controlled composite
   - contest-facing pure-text headline
   - protocol-only mechanism surfaces

### 3.3 下一轮是不是只做口径和报告，不动对象

答案：

> 不是。下一轮必须动对象，而且主要动任务对象与 headline contract。

只修报告不够，因为：

- 当前最大问题不是“别人没理解我们”
- 而是“我们自己 formal headline 的比较对象就不够诚实”

### 3.4 是否要继续保留当前 release-regression 题材

答案：

> 保留题材，但要重做 benchmark object。

release-regression / incident triage 这个题材本身是合理的，因为它：

- 适合 Planner / Retriever / Executor / Summarizer
- 适合 structured evidence
- 适合 non-text handoff
- 适合 continuous tasks 和 memory reuse

要改的不是题材，而是：

- pure-text 对照对象
- family topology
- reusable dependency
- benchmark surface split

### 3.5 task 集、benchmark 设计是否允许继续大改

答案：

> 允许，而且这正是下一轮最值得改的对象。

理由：

- 当前 task/benchmark 正是赛题 headline 不诚实的主要来源
- 这类修改不会破坏已经成立的 runtime / protocol / statepool / memory 主链路
- 这是“按赛题要求重构对象”，不是“为了指标好看去改数据”

---

## 4. 当前真实问题分层

下面只保留值得进入执行计划的真实问题。

### P0-1：formal contest headline 的 pure-text 对象不成立

当前事实：

- `text_strict_pure_lane` 的 retrieve handoff 明写 route/tool/confidence 等结构化决策字段
- runner 也因此把 whole-lane text guard 标成 `hidden_field_leak`
- current pack 自己已经声明它是 composite comparison，不是 external pure-text baseline

为什么这是 P0：

- 它直接影响赛题主问题“纯文本 vs 结构化协议”
- 不修它，后续 repeat=10 也不能诚实拿去答辩

相关文件：

- `agents/sample_agents.py`
- `runtime/executor_runtime.py`
- `eval/runner.py`
- `tasks/contest_dual_mode_controlled_v3_benchmark.yaml`

### P0-2：contest formal surface 和内部 controlled surface 仍然混在一个 pack 里

当前事实：

- 当前 `contest_dual_mode_controlled_v3` 同时承担：
  - contest formal headline
  - internal controlled runtime comparison
- 但它的 variable axes 是 `mode + handoff_object`
- 自身 reading contract 也承认它不是 single-variable pure-text baseline

为什么这是 P0：

- 同一个 pack 既想当正式对照，又想当内部受控 composite，会导致口径永远摇摆

### P0-3：`planner_support_v3` 的 report schema 仍然混对象

当前事实：

- pack 明明是 protocol-only、single-variable=`plan_source`
- report 却输出 `text_admissible_match_rate / protocol_admissible_match_rate / combined_admissible_match_rate`

为什么这是 P0：

- 它会直接误导答辩/论文口径
- 它不是小可读性问题，而是 metric label 已经和对象不对齐

### P1-1：contest family 的 reusable 依赖还不够强

当前应有的 reusable 题，不该只是“同 family follow-up”。

它应该要求：

- 明确消费 prior case 的 rejection / validated route / scope narrowing
- prior missing 时显式降级或失败

这是赛题“连续关联任务 + 共享记忆复用”的关键对象。

### P1-2：contest family 仍然偏 route/tool 选择题，缺少更厚的协作对象

当前 family 太容易被读成：

- retriever 选 route
- executor 选 tool
- summarizer 写结果

下一轮应增强：

- validation target
- action scope
- conflicting evidence handling
- follow-up narrowing

但这不是要把系统改成开放世界，而是把当前 release-regression family 从薄分类题拉厚。

### P1-3：consumer-sensitivity 和 support packs 仍有少量 reporting 误导

例如：

- `wrong_decision_misroute_rate`
- support pack boundary 文案仍有残余歧义

这些需要改，但排在 headline object 之后。

---

## 5. 不需要作为本轮主目标的项

以下内容本轮不应抢主线：

1. 不重开 VM / openEuler / Docker / `nsjail`
2. 不把 `typed_state_mechanism_v3` 升格成 contest headline
3. 不把 `memory_dual_mode_fairness_v3` 升格成 replay headline
4. 不因为 `repeat=3` 就放宽 formal stability gate
5. 不为了提指标恢复：
   - `runtime_route_hint`
   - `preferred_doc_ids`
   - `theme_bonus`
   - `group_bonus`
6. 不把 `inline_text_handoff` 冒充 whole-lane pure text
7. 不把 planner support 的开放性 claim 和 communication medium / typed-state authenticity 混成一个故事

---

## 6. 是否支持继续重构

答案：

> 支持，而且应该继续；但只支持沿着“contest headline object 重构”这条线继续，不支持再做大而散的多线并发。

支持继续重构的理由：

1. 当前基础设施主链路已经够稳
   - pytest / smoke / repeat3 pack 都能跑
   - planner / semantic-role / validate / memory replay 已真实接通
2. 当前最大风险在 benchmark object，而不在 runtime 基础设施
3. benchmark object 的重构不会污染：
   - protocol minimal mechanism
   - memory replay proof
   - planner openness support

不支持并发散改的理由：

1. 同时改 headline、support surface、memory、planner、executor 细节，最后很难知道是哪个对象在变化
2. 这轮需要先解决“比较对象是否诚实”，不是“哪个 pack 分数更高”

---

## 7. 唯一推荐的下一条主线

### 主线名称

**Contest Honest Headline Refactor**

### 主线目标

把当前赛题 formal 对照从“结构化决策文本化后的 composite 比较”重构为“诚实的 pure-text contest baseline vs structured protocol contest baseline”，并为此同步重做 task family contract、benchmark split 和 report semantics。

### 为什么只选这条

因为它同时解决：

1. 赛题对象不诚实
2. headline / support surface 混用
3. task object 偏薄
4. report schema 误导

而且它不要求推翻现有 runtime 主链路。

---

## 8. 详细执行顺序

下面的顺序按实现时应直接执行，不建议跳步。

### Phase 0：冻结口径和 surface 边界

目标：

- 先把“哪些 surface 讲什么”写死，避免一边实现一边换读法

具体动作：

1. 新增或更新一份 surface manifest 说明
   - formal contest headline
   - internal controlled composite
   - planner support
   - typed-state mechanism
   - text definition audit
   - memory fairness
   - replay proof
2. 明确以下结论进入文档和 report：
   - `text_strict_pure_lane` 不再承担赛题 pure-text formal headline
   - `contest_dual_mode_controlled_v3` 若保留原对象，则降格
   - `planner_support_v3` 是 `yaml vs llm`，不是 `text vs protocol`

涉及文件：

- `README.md`
- `tasks/README.md`
- `docs/reports/MASTER_PRESENTATION_GUIDE.md`
- `eval/runner.py`

验收：

- 不再有任何地方把 `text_strict_pure_lane` 直接写成 contest pure-text baseline
- 不再有任何地方把 planner support 写成 communication headline

### Phase 1：拆 contest formal headline pack 与 internal controlled pack

目标：

- 不再让一个 pack 同时承担两个对象

推荐做法：

1. 保留当前 `contest_dual_mode_controlled_v3`
   - 改名或改 metadata 为 internal controlled composite surface
2. 新建正式 contest headline pack
   - 建议名：
     - `contest_pure_text_vs_protocol_headline_v1`
     - 或 `contest_dual_mode_honest_headline_v1`
3. formal headline pack 的变量轴固定为：
   - `mode`
4. handoff object 规则：
   - text side：真实 natural-language multi-agent handoff
   - protocol side：`state_packet_minimal`

涉及文件：

- `tasks/sample_tasks.py`
- `tasks/contest_dual_mode_controlled_v3_benchmark.yaml`
- 新 headline YAML
- `eval/runner.py`

验收：

- formal headline pack 的 reading contract 不再写 composite comparison
- internal controlled pack 退出 formal headline 角色

### Phase 2：定义真正的 pure-text contest baseline

目标：

- 让 text side 成为诚实的 pure-text collaboration object

硬约束：

1. text handoff 允许自然语言描述判断
2. 不允许显式字段化写入：
   - `Route:`
   - `Tool:`
   - `Route source:`
   - `Route confidence:`
   - `Retrieved docs:`
3. 不允许把 protocol packet 的字段机械改写成固定模板文本
4. 允许自然语言里出现基于证据的分析，但不能出现机器可稳定反解析的结构化槽位

推荐实现：

1. 新增 text headline 专用 handoff builder
   - 只输出自然语言解释、证据摘要、待执行意图、下一步建议
2. executor text lane 改为消费自然语言 handoff
   - 允许自然语言理解
   - 但不允许显式协议字段文本反解析
3. whole-lane guard 改成区分：
   - illegal structural slot leak
   - legal natural-language reasoning

涉及文件：

- `agents/sample_agents.py`
- `runtime/executor_runtime.py`
- `eval/runner.py`
- `tests/test_llm_runtime.py`
- `tests/test_smoke.py`
- `tests/test_state_channels_and_graph.py`

验收：

- formal text headline rows 的 handoff 文本里不再出现固定结构化字段 marker
- 相关 guard 对 formal text headline 应能通过

### Phase 3：重做 contest family object，而不是只改 query 词

目标：

- 把 current family 从薄 route/tool 题改成更像真实多 agent 协作

保留题材：

- release regression / incident triage

重做原则：

1. 每个 family 仍保留：
   - clean
   - distractor
   - ambiguous
   - reusable
2. 但每个 case 不只看 route/tool
3. 必须增加更厚的协作对象：
   - strongest competing explanation
   - first action
   - first validation check
   - allowed scope
   - carried-forward rejection
4. reusable case 必须真正依赖 prior case

具体设计建议：

每个 family 固定八类证据角色：

- incident
- metrics
- logs
- structural anchor / runbook
- cross-family distractor
- ambiguity note
- scope note
- reuse dependency note

每个 family 的 reusable case 必须满足：

- `required_prior_case_ids` 非空
- `required_prior_rejections` 非空
- 缺 prior 时只能 `collect_more_evidence` 或失败

涉及文件：

- `tasks/contest_family_spec.yaml`
- `tasks/contest_release_regression_corpus.yaml`
- `tasks/contest_dual_mode_controlled_v3_benchmark.yaml`
- 新 headline YAML

验收：

- reusable rows 真正消费 prior dependency
- clean/distractor/ambiguous/reusable 的差异来自证据拓扑和协作压力，不只是 query 写法

### Phase 4：用 family spec 生成 contest packs

目标：

- 让 task/corpus 不再手工漂移

具体动作：

1. 把 `contest_family_spec.yaml` 作为唯一来源
2. 由生成器产出：
   - internal controlled pack
   - contest honest headline pack
   - contest corpus
3. 对 family spec 加结构校验：
   - required roles complete
   - required buckets complete
   - reusable dependency complete
   - text/protocol pair complete

涉及文件：

- `tasks/contest_family_spec.yaml`
- `tasks/sample_tasks.py`
- 可能新增 generator script

验收：

- 不再手工维护两三套容易漂移的 contest YAML

### Phase 5：修 planner support report schema

目标：

- 只修语义，不改 planner 主行为

具体动作：

1. `planner_support_v3` report 改为以下三层：
   - `yaml_control_case_correctness`
   - `llm_plan_case_correctness`
   - `planner_contract_metrics`
2. 额外输出：
   - `planner_one_shot_valid_rate`
   - `planner_repair_attempt_rate`
   - `validate_gate_triggered_count`
   - `validate_gate_passed_count`
   - `plan_valid_but_validate_blocked_count`
3. 删除或禁用：
   - `text_admissible_match_rate`
   - `protocol_admissible_match_rate`
   - `combined_admissible_match_rate`

涉及文件：

- `eval/runner.py`
- `eval/metrics.py`
- `tests/test_smoke.py`

验收：

- planner support report 不再出现 text/protocol 混名
- planner / validate / correctness 三层分开

### Phase 6：修 support pack 的误导性 metric 命名

目标：

- 清掉会误导答辩的 support metric

具体动作：

1. 重命名或重释义：
   - `wrong_decision_misroute_rate`
2. 在 consumer-sensitivity 报告里加 definition note：
   - 度量的是“最终产物是否仍匹配 expected route”
   - 不是“错误 packet 是否注入过”
3. 检查其他 support pack 是否仍有类似命名偏差

涉及文件：

- `eval/runner.py`
- 相关 benchmark report writer
- `tests/test_smoke.py`

### Phase 7：重新跑 gate，再决定是否进 repeat=10

目标：

- 先确认对象修正后，formal gate 真正干净

先跑：

1. `python -m pytest -q`
2. `python -m runtime.smoke`
3. deterministic / repeat=1:
   - new contest headline pack
   - internal controlled pack
   - planner_support_v3
   - typed_state_mechanism_v3
   - memory_policy_controlled_v3
4. serialized API / repeat=1:
   - new contest headline pack
5. 只有在以下条件都满足时，才进 API repeat=10：
   - formal text guard pass
   - no hidden-field structural slot leak
   - no report-schema mismatch
   - reusable dependency 真生效

---

## 9. task 集与 benchmark 设计的具体修改建议

### 9.1 formal contest headline pack 的任务数量

建议：

- 5 families
- 每 family 4 cases
- text/protocol paired
- 共 40 task rows

这与当前规模兼容，不必盲目扩容。

### 9.2 每个 family 的 case contract

固定四类：

1. clean
2. distractor
3. ambiguous
4. reusable

每类的读法：

- clean：证据收敛，但仍需多 agent 协作完成 action/validation decision
- distractor：强竞争解释存在，必须排除
- ambiguous：允许保守 abstain 或 evidence-seeking
- reusable：必须消费 prior rejection / prior validation

### 9.3 query 设计原则

下一轮不把“去 query 泄漏”当成主标题单独追，而作为 family 重做的一部分一并处理。

原则：

1. query 不直接给 route 答案词
2. query 只给现象和约束
3. route discrimination 主要靠 evidence topology，不靠 query token

### 9.4 benchmark surface 重新分层

正式保留以下 surfaces：

1. `contest_honest_headline_v1`
   - 赛题正式 pure-text vs protocol headline
2. `contest_controlled_composite_v1`
   - 内部 controlled comparison
3. `typed_state_mechanism_v3`
   - protocol-only mechanism surface
4. `memory_policy_controlled_v3`
   - protocol-only memory policy attribution
5. `planner_support_v3`
   - planner openness support surface
6. `text_definition_audit_v3`
   - executor-boundary audit
7. `memory_dual_mode_fairness_v3`
   - object parity / fairness audit

### 9.5 不建议新增的对象

本轮不建议再引入：

- 开放域 web / browser use family
- code repair family
- open-system comparison 并入 formal 主线

原因：

- 会把 headline object 改造和系统能力扩张绑在一起
- 当前最该修的是赛题 formal object 的诚实性

---

## 10. 文件级改动边界

### 必改

- `agents/sample_agents.py`
- `runtime/executor_runtime.py`
- `eval/runner.py`
- `eval/metrics.py`
- `tasks/sample_tasks.py`
- `tasks/contest_family_spec.yaml`
- `tasks/contest_dual_mode_controlled_v3_benchmark.yaml`
- `tasks/contest_release_regression_corpus.yaml`
- 新 contest headline YAML
- `tests/test_smoke.py`
- `tests/test_llm_runtime.py`
- `tests/test_state_channels_and_graph.py`
- `README.md`

### 可能需要改

- `runtime/orchestrator.py`
  - 仅在 text headline handoff contract 需要额外状态跟踪时
- `tasks/local_corpus.py`
  - 若 family 重做后需进一步收紧 formal retrieval inputs

### 本轮不改

- `runtime/langgraph_adapter.py`
  - 除非 planner support 报告调整需要少量字段透出
- `memory/store.py`
- `statepool/`
- `protocol/`

---

## 11. 验证标准

### 必须满足

1. 新 formal contest headline pack 的 text side 不再是结构化字段文本化载体
2. formal text guard 对新 headline pack 通过
3. planner support report 不再混 `text/protocol`
4. reusable rows 缺 prior dependency 时真实降级或失败
5. support surface 不再冒充 headline
6. 不恢复 formal retrieval hint / shortlist / bias

### 可以暂时不满足

1. API repeat=10 正式包
2. correctness 指标进一步上升
3. open-system external text baseline
4. 更开放的 planner DAG

---

## 12. 实施中的 stopline

执行时遇到以下情况应立即停下复核，而不是硬改：

1. 为了让 text headline 通过 guard，开始偷偷恢复结构化字段或隐藏 fallback
2. 为了让 protocol 赢，给 protocol pack 单独加 hint / override
3. support pack 指标好看后，开始把 support surface 升格成 headline
4. 为了过 repeat=10，放宽 formal stability gate
5. family 重做开始要求 runtime / memory / planner 同步大扩展

---

## 13. 推荐执行顺序总结

唯一推荐顺序：

1. 先收 surface 边界
2. 再拆 contest headline pack
3. 再定义真正的 pure-text headline object
4. 再重做 family spec 与 corpus topology
5. 再修 planner support report schema
6. 再修 support metric 命名
7. 最后才跑新的 API repeat 证据

不推荐顺序：

- 先追 correctness
- 先追 repeat=10
- 先修 tool pattern
- 先扩更多 task domain
- 先做开放 benchmark

---

## 14. 最终执行判断

这轮之后，StateBus 当前最合理的继续方向已经不是“再补几个小 patch”，也不是“直接大跑 repeat=10”。

最合理的方向是：

> 把赛题正式 headline 从当前 composite controlled surface 中拆出来，重建一个诚实的 pure-text vs structured protocol contest object，并围绕它重做 task family、benchmark contract 和 reporting 语义。

这是当前最值得做、也最不容易污染已有正确结论的一条主线。
