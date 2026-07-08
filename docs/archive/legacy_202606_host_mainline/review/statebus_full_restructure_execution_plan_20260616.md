# StateBus 全量重构执行方案（详细版）

日期：2026-06-16

适用范围：`/home/qcrs/statebus/project`

主合同优先级：

1. `docs/reference/题目.md`
2. `docs/review/statebus_contest_remaining_closure_plan_20260615.md`
3. 当前仓库代码与 YAML

本文只写“怎么改”，不再讨论抽象方向。

## 1. 这次重构要解决什么

当前树不是“缺几个补丁”，而是三层合同没有完全闭合：

- 任务合同层还在依赖隐式推断，`plan_source` / `public_surface` / `evidence_tier` 的边界不够硬。
- 语料与检索层仍保留了 hint、偏置、preferred shortlist 这类结构性捷径。
- Planner / Runtime 仍以固定 `retrieve/execute/summarize` 步名驱动，语义角色没有真正抽象出来。

因此，这次修改按“可以面目全非”的标准做，不追求最小 diff。

## 2. 已确认必须修的点

### 2.1 `plan_source` 校验是死代码

`tasks/sample_tasks.py:893-909` 的 `plan_source` 检查写在 `raise` 之后，当前对 contest 包永远不会执行。

### 2.2 `typed_state_full_rich_audit_v3` 仍会因 metadata 失败

`tasks/typed_state_full_rich_audit_v3_benchmark.yaml:1-8` 没有 `public_surface`，而 `_load_task_set_metadata()` 只对 `audit_only` 和 `formal_secondary` 做 auto-inference，见 `tasks/sample_tasks.py:660-668`。

### 2.3 formal retrieval 仍然过宽

`tasks/local_corpus.py:121-123` 仍有 `theme_bonus/group_bonus/preference_bonus`，`tasks/local_corpus.py:160-161` 仍可把 `preferred_doc_ids` 并入候选集。

### 2.4 运行时 hint 仍是“返回空”，不是“结构级禁止”

`agents/sample_agents.py:1881-1888` 只检查 `runtime_hint_allowed`，没有直接把 `formal_structure_clean_retrieval` 作为独立合同门。

### 2.5 Planner / Runtime 仍依赖固定 step_id

`runtime/orchestrator.py:1125-1126`、`1186-1187`、`1218` 和 `1296-1300`，以及 `agents/sample_agents.py:895-899`、`969-971` 都直接按 `"retrieve" / "execute" / "summarize"` 取步骤。

### 2.6 测试已经弱化

`tests/test_smoke.py:4447-4467`、`4470-4511` 只验证“有输出”，没有锁定具体 route/tool correctness。

## 3. 重构总原则

1. 显式优先于推断。active v3 pack 不再靠 loader 猜 metadata。
2. 结构优先于 gate。formal pack 不能只是“运行时不消费 hint”，而要在数据结构层面去掉 hint 依赖。
3. 语义优先于字符串。Planner / Runtime 不再靠固定 step_id 驱动。
4. 生成优先于手写。contest/corpus 这类重复结构改成 spec 生成。
5. 评测优先于口径。只要代码变了，测试和报告口径必须同步变。

## 4. 逐层修改方案

### 4.1 任务合同层

目标：把 `tasks/sample_tasks.py` 从“兼容性加载器”改成“显式合同验证器”。

具体改法：

- 把 `_validate_task_profile_contract()` 拆成 4 个独立检查：
  - transfer strategy / handoff profile 对齐检查
  - `plan_source` 合同检查
  - reusable 合同检查
  - formal pack 结构检查
- 把 `plan_source` 检查移出 `summary_contract` 分支，变成顶层检查。
- active v3 pack 的 `public_surface` 不再 auto-infer。
- `evidence_tier: support_only` 的 pack 必须显式写 `public_surface`，不能再靠默认路径兜底。
- `PUBLIC_SURFACE_ALIASES` 只保留历史兼容，不参与 active v3 合同判断。

涉及文件：

- [tasks/sample_tasks.py](/home/qcrs/statebus/project/tasks/sample_tasks.py:639)
- [tasks/typed_state_full_rich_audit_v3_benchmark.yaml](/home/qcrs/statebus/project/tasks/typed_state_full_rich_audit_v3_benchmark.yaml:1)
- [tasks/memory_policy_controlled_v3_benchmark.yaml](/home/qcrs/statebus/project/tasks/memory_policy_controlled_v3_benchmark.yaml:1)

验收标准：

- 所有 active v3 pack 都能显式通过加载。
- 任意缺失 `public_surface` 的 active v3 pack 直接失败。
- 任意缺失 `plan_source` 的 formal pack 直接失败。

### 4.2 benchmark 与 corpus 层

目标：把 contest / corpus 从手写样例改成 family spec 驱动。

contest pack 需要重构成下面的稳定合同：

- 每个 family 共享同一任务语义对象。
- text / protocol 只差 `mode + handoff_object`。
- clean / ambiguous / distractor / reusable 的候选 route 集都必须有竞争，不允许退化成单 route。
- query 里不能直接泄漏 route 答案词。

corpus 需要重构成下面的稳定合同：

- 每个 family 至少包含 8 类证据角色：
  - incident
  - metrics
  - logs
  - structural anchor
  - distractor
  - ambiguity
  - scope
  - reuse
- reusable 文档必须显式携带 prior dependency 语义。
- `formal_structure_clean: true` 的 corpus 不能再有 runtime hint 作为可消费信息。

具体改法：

- 以 family spec 生成 `tasks/contest_dual_mode_controlled_v3_benchmark.yaml`。
- 以 family spec 生成 `tasks/contest_release_regression_corpus.yaml`。
- 删除 query 中的直白 route token。
- 把 reusable 行改成“依赖前一个 case 的 rejected route / validation result”。
- 保持 `case_type`、`acceptable_routes`、`acceptable_tools` 与 evidence 拓扑一致。

涉及文件：

- [tasks/contest_dual_mode_controlled_v3_benchmark.yaml](/home/qcrs/statebus/project/tasks/contest_dual_mode_controlled_v3_benchmark.yaml:1)
- [tasks/contest_release_regression_corpus.yaml](/home/qcrs/statebus/project/tasks/contest_release_regression_corpus.yaml:1)

验收标准：

- clean / reusable 不再是单 route 题。
- protocol 的结构化信息在正确性上有展示空间。
- corpus 文档结构能支撑 cross-family distractor，而不是 family 内轻干扰。

### 4.3 formal retrieval 层

目标：把 retrieval 从“有 hint 但 gate 关掉”变成“结构上没有 hint 依赖”。

具体改法：

- `CorpusDoc` 拆成 formal 与 audit 两种语义。
- `formal_structure_clean` 为真时，loader 不再保留 runtime hint 字段，而不是只置空。
- `retrieve_corpus_docs()` 在 formal 模式下关闭以下项：
  - `theme_bonus`
  - `group_bonus`
  - `preferred_doc_ids` shortlist 合并
- `_resolve_runtime_corpus_hints()` 改成 formal pack 直接拒绝 hint，而不是继续走 `runtime_hint_allowed` 兼容逻辑。
- `_runtime_preferred_doc_bias_allowed()` 必须和 `formal_structure_clean_retrieval` 同步。

涉及文件：

- [tasks/local_corpus.py](/home/qcrs/statebus/project/tasks/local_corpus.py:16)
- [agents/sample_agents.py](/home/qcrs/statebus/project/agents/sample_agents.py:1881)

验收标准：

- formal pack 的候选集不再受 repo-private 先验塑形。
- hint 仅在 audit / legacy pack 中存在。
- preferred shortlist 不再影响正式 headline。

### 4.4 Planner / Runtime 层

目标：让 Planner 输出真正可执行的语义 DAG，而不是固定三步模板。

具体改法：

- 在 `PlanStep` 增加语义角色字段，例如 `semantic_role`。
- `step_id` 继续保留，但只做实例标识，不再承担语义分发。
- `runtime/orchestrator.py` 的 `_find_step()` 改成先按语义角色找，再按 id 回退。
- `resolve_skip_retrieve_execute()`、`resolve_skip_execute()`、`SummarizerAgent.execute_step()`、`ExecutorAgent._validate_route_step()` 全部改为按语义角色消费输入。
- `compile_task_plan()` 继续写 `ctx.planner_source`，但 `_plan_task()` 不能再假设 `"retrieve/execute/summarize"` 是唯一合法结构。
- `plan_source=llm` 的 DAG 校验保留 3-5 步、DAG 非环、语义覆盖，但 step id 不再要求固定词。

涉及文件：

- [runtime/orchestrator.py](/home/qcrs/statebus/project/runtime/orchestrator.py:865)
- [runtime/orchestrator.py](/home/qcrs/statebus/project/runtime/orchestrator.py:1118)
- [runtime/orchestrator.py](/home/qcrs/statebus/project/runtime/orchestrator.py:1235)
- [agents/sample_agents.py](/home/qcrs/statebus/project/agents/sample_agents.py:293)
- [agents/sample_agents.py](/home/qcrs/statebus/project/agents/sample_agents.py:857)
- [agents/sample_agents.py](/home/qcrs/statebus/project/agents/sample_agents.py:965)

验收标准：

- `plan_source=llm` 不再是半开放。
- 非固定 step_id 的 plan 可以完整执行。
- replay / summarizer 仍能找到正确语义输入。

### 4.5 共享记忆与 reusable 层

目标：让 reusable 真的消费 prior dependency，而不是只记录字段。

具体改法：

- `required_prior_case_ids`、`required_prior_rejections` 进入 runtime 校验。
- Summarizer commit 必须显式写出 reusable contract。
- replay / exact replay 的命中必须验证 prior rejection 已被承接。
- `memory_policy_controlled_v3` 改成与 contest 同一份 formal retrieval contract，不允许额外检索偏置。

涉及文件：

- [tasks/sample_tasks.py](/home/qcrs/statebus/project/tasks/sample_tasks.py:911)
- [tasks/contest_release_regression_corpus.yaml](/home/qcrs/statebus/project/tasks/contest_release_regression_corpus.yaml:90)
- [tasks/contest_release_regression_corpus.yaml](/home/qcrs/statebus/project/tasks/contest_release_regression_corpus.yaml:187)
- [tasks/contest_release_regression_corpus.yaml](/home/qcrs/statebus/project/tasks/contest_release_regression_corpus.yaml:282)
- [tasks/memory_policy_controlled_v3_benchmark.yaml](/home/qcrs/statebus/project/tasks/memory_policy_controlled_v3_benchmark.yaml:1)

验收标准：

- reusable 题在 prior dependency 缺失时会降级或失败。
- `memory_policy_controlled_v3` 不再比 contest 包拥有更宽的检索偏置。

### 4.6 typed-state 与 decision packet 层

目标：把 typed-state support surface 改成一致、可验证、可消费。

具体改法：

- `typed_state_full_rich_audit_v3` 只做 support / audit，不进入主 headline。
- `typed_state_consumer_sensitivity_v3` 的 bundle metadata 与 child task metadata 必须一致，不能出现手工拼装后的分裂口径。
- `runtime/executor_runtime.py` 的 decision packet 校验至少补：
  - `route_confidence` 范围
  - provenance / hash 一致性
  - 非空候选集约束
  - negative control 必填字段

涉及文件：

- [tasks/typed_state_full_rich_audit_v3_benchmark.yaml](/home/qcrs/statebus/project/tasks/typed_state_full_rich_audit_v3_benchmark.yaml:1)
- [runtime/executor_runtime.py](/home/qcrs/statebus/project/runtime/executor_runtime.py:1775)
- [runtime/executor_runtime.py](/home/qcrs/statebus/project/runtime/executor_runtime.py:1833)
- [tasks/sample_tasks.py](/home/qcrs/statebus/project/tasks/sample_tasks.py:480)

验收标准：

- typed-state support pack 全部能稳定 load。
- decision packet 的 consumer sensitivity 可以被稳定测出。
- 错误 packet 能真实导致降级，而不是仅仅“有输出”。

### 4.7 测试、gate 与报告层

目标：把当前已经弱化的验证重新拉回到 correctness。

具体改法：

- 恢复 route/tool exact assertion。
- 新增 active v3 pack 全量 load gate。
- 新增 formal retrieval clean gate：
  - no runtime hint
  - no preferred shortlist bias
  - no theme/group bonus
- 新增 planner semantic-role gate：
  - 非固定 step_id 也能完整执行
  - DAG 仍正确
- 新增 reusable dependency gate：
  - prior case 缺失时必须失败或降级
- 报告里显式写出 `public_surface / evidence_tier / formal_structure_clean_retrieval / plan_source`。

涉及文件：

- [tests/test_smoke.py](/home/qcrs/statebus/project/tests/test_smoke.py:4447)
- [eval/runner.py](/home/qcrs/statebus/project/eval/runner.py:2662)
- [README.md](/home/qcrs/statebus/project/README.md:1)

验收标准：

- 测试能抓住 route/tool 错误，而不是只看“有输出”。
- 报告和代码口径一致。

## 5. 推荐实施顺序

1. 先修任务合同层，清掉 `plan_source`、`public_surface`、`support_only` 这些加载死角。
2. 再重构 contest/corpus 生成，停止手改大 YAML。
3. 再收口 formal retrieval，去掉 runtime hint、preferred shortlist、theme/group bias。
4. 再做 Planner / Runtime 的语义角色化。
5. 再把 reusable prior dependency 真正接入 runtime 和记忆。
6. 最后恢复测试、gate 和报告。

## 6. 最终完成标准

只有同时满足下面几条，才算这轮重构完成：

- 所有 active v3 pack 都能 load。
- contest formal headline 真的有 `text vs protocol` 正确性差异。
- formal retrieval 不再依赖结构性 hint。
- reusable 真的消费 prior dependency。
- planner 可以不靠固定 step id 执行。
- 测试能抓住 route/tool correctness，不再只验证“有输出”。

## 7. 设计借鉴

只借设计原则，不照搬数据集。

- HotpotQA：多支持文档与可解释支持事实，适合用来约束多证据任务结构。https://arxiv.org/abs/1809.09600
- MuSiQue：强调由 connected single-hop 组合得到真正多跳问题，适合用来约束“不要靠 shortcut”。https://arxiv.org/abs/2108.00573
- BRIGHT：强调 reasoning-intensive retrieval，适合用来约束“query 不能只靠字面命中”。https://arxiv.org/abs/2407.12883
- LongMemEval：强调长期交互记忆的 indexing / retrieval / reading 设计，适合用来约束 reusable / memory 语义。https://arxiv.org/abs/2410.10813

