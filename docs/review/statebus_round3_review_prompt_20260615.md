# StateBus 第三轮全量 Review Prompt

交给能读长上下文的新模型窗口。目标：基于前天到今天的三轮审计→修复→再审计链条，验证当前代码状态，确认 Bug 是否存在，排查遗漏问题。

```text
你现在在 `/home/qcrs/statebus/project` 工作。

## 背景

这是一个面向赛题的 StateBus 原型系统。前天做了全系统审计发现大量问题，昨天落地了大量代码修改（12 个 pack 的 benchmark 重构、corpus 去 hint、retrieval 结构级 clean、query 去关键词等），今天做了第二轮全面 review 发现 2 个致命 Bug 和若干遗留问题。你的任务是验证这些问题是否真实存在，并排查是否还有其他遗漏。

## 阅读顺序（必须按这个顺序读，理解前因后果）

### 第一层：赛题约束（最高权威）

- `docs/reference/题目.md`

### 第二层：前天的问题发现（全系统审计）

- `docs/analysis/full_system_audit_20260615.md` — 原始 20+ 个问题的全系统审计
- `docs/analysis/experimental_anomalies_20260615.md` — 实验数据中的 16 个异常

### 第三层：昨天的修复方案与决定

- `docs/review/statebus_seven_issue_fix_plan_20260615.md` — 七问题修复方案与执行计划
- `docs/review/statebus_remaining_issues_and_solutions_20260615.md` — 遗留问题与方案
- `docs/review/statebus_contest_remaining_closure_plan_20260615.md` — contest/corpus/retrieval 收口方案

### 第四层：今天的第二轮 Review（当前需要验证的）

- `docs/review/statebus_code_review_20260615.md` — 刚刚完成的第二轮全量代码 Review，列出了：
  - BUG-1：`sample_tasks.py:897-909` plan_source 校验嵌套在错误的 if 块内
  - BUG-2：`typed_state_full_rich_audit_v3` 加载失败
  - BUG-3：`_resolve_runtime_corpus_hints` 不检查 `formal_structure_clean_retrieval`
  - 多个测试弱化问题
  - 配置遗漏问题

## 你的任务

### 第一步：验证 Review 中列出的 Bug 是否真实存在

对 `statebus_code_review_20260615.md` 中列出的每个 Bug，**亲自读代码验证**：

1. **BUG-1**：读 `tasks/sample_tasks.py` 第 880-920 行，确认 `plan_source` 校验（897-909 行）是否真的被嵌套在 `summary_contract` 的 if 块内部。如果 contest 包的 40 个 task 的 `handoff_profile` 不是 `protocol_full_rich_audit`，确认这些校验确实永远不会执行。

2. **BUG-2**：读 `tasks/typed_state_full_rich_audit_v3_benchmark.yaml` 的前 10 行，确认是否缺少 `public_surface`。读 `tasks/sample_tasks.py` 的 `_load_task_set_metadata()` 函数（约 639-703 行），确认 `evidence_tier: support_only` 是否没有被 auto-inference 覆盖。然后实际运行加载测试确认。

3. **BUG-3**：读 `agents/sample_agents.py` 的 `_resolve_runtime_corpus_hints()` 函数（约 1881-1888 行），确认它只检查 `runtime_hint_allowed` 而不检查 `formal_structure_clean_retrieval`。在当前配置下是否有实际影响。

4. **TEST-WEAK-1/2**：读 `tests/test_smoke.py` 的 `test_retrieval_weak_route_diagnostic_task_set` 和 `test_retrieval_theme_variant_diagnostic_task_set`，确认这些测试是否被弱化为只检查"有输出"而不检查"输出正确"。

5. **CONFIG 问题**：读 `tasks/memory_policy_controlled_v3_benchmark.yaml` 的前 20 行，确认是否缺少 `formal_structure_clean_retrieval: true`。

对每个问题给出：
- "确认存在" / "不存在" / "存在但描述不准确"
- 如果描述不准确，给出准确的描述和代码位置

### 第二步：排查是否还有其他遗漏问题

在验证完已知 Bug 后，通读以下关键文件，查找 Review 文档可能遗漏的问题：

1. `tasks/sample_tasks.py` — 全文通读，关注：
   - `_validate_task_profile_contract()` 的所有校验逻辑是否有其他缩进/逻辑错误
   - `_validate_task_set_metadata_contract()` 的所有校验是否完整
   - `_load_task_set_metadata()` 的 auto-inference 是否覆盖了所有 `EVIDENCE_TIERS`
   - `PUBLIC_SURFACE_ALIASES` 是否覆盖了所有旧名字

2. `tasks/contest_dual_mode_controlled_v3_benchmark.yaml` — 抽样检查：
   - 每个 family 的 8 个 task 行是否都有 `acceptable_routes` 和 `acceptable_tools`
   - reusable 行是否都有 `required_prior_case_ids` 和 `required_prior_rejections`
   - YAML 锚点引用是否正确（`*checkout_clean_docs` 等是否指向存在的锚点）

3. `tasks/contest_release_regression_corpus.yaml` — 抽样检查：
   - 每个 family 是否有完整的 8 类文档
   - `eval_route_label` 和 `eval_tool_label` 是否存在于每个文档
   - `corpus_metadata.formal_structure_clean` 是否为 `true`

4. `agents/sample_agents.py` — 通读关键函数：
   - `RetrieverAgent.execute_step()` (约 293-854 行)：检索流程中是否有其他绕开 formal clean 的路径
   - `SummarizerAgent.execute_step()` (约 969-1270 行)：compact JSON 路径和旧 `protocol_handoff_audit` 路径的切换逻辑是否正确
   - `_plan_from_llm_output()` (约 1349-1372 行)：3-5 步校验 + DAG 合法性 + semantic coverage 是否正确

5. `runtime/executor_runtime.py` — 通读关键函数：
   - `execute_playbook_step()` (约 904-1137 行)：9 种 transfer strategy 的 dispatch 是否完整、是否正确
   - `_feature_bundle_from_executor_decision_packet()` (约 1775-1830 行)：是否真的不调用 `build_feature_bundle()`
   - `_validate_executor_decision_packet()` (约 1833-1856 行)：校验是否完整

6. `runtime/orchestrator.py` — 检查：
   - `_plan_task()` (约 1235-1246 行)：yaml vs llm 的分支是否正确
   - `compile_task_plan()` (约 865-879 行)：是否设置了 `ctx.planner_source`
   - `resolve_skip_retrieve_execute()` (约 1118-1177 行)：对多 step plan 的 summarize 输入解析是否正确

7. `eval/runner.py` — 检查：
   - `_aggregate_task_groups()`：确认按 (mode, task_group) 分组
   - `_build_headline_gates()`：gate 的 applicable 条件是否正确
   - `_contest_formal_coverage_gate()`：检查 family/bucket/repeat 要求是否合理

### 第三步：赛题要求对照

基于 `docs/reference/题目.md`，对照当前代码状态：

1. **多 Agent 规划**：Planner 仍然被 `plan_source_default: yaml` 绕过（contest 和 memory_policy 包）。`planner_support_v3` 有 6 个 llm 行作为独立证据。这个分工是否满足赛题"覆盖规划角色"的要求？

2. **结构化通信**：protocol 的控制面是否确实比 text 低？protocol summarizer 的 token 是否仍然高于 text？

3. **非文本状态传递**：`EXECUTOR_DECISION_PACKET` 的 consumer sensitivity 是否真的证明了"缺失会导致 failure"？

4. **共享记忆复用**：`memory_policy_controlled_v3` 是否真正承担了 formal memory surface？它的 `single_variable` 实验是否干净？

5. **两种协作模式的同任务对比**：contest 包的 text vs protocol 对比现在是否公平？两边除了 mode+handoff_object 之外还有没有其他不可控的差异？

6. **任务设计**：新的 contest task（去关键词、multi-route、prior dependency）是否真的能让 protocol 的结构化精度有展示空间？

### 第四步：判断

1. 当前 commit (`44f7af8`) 如果把 BUG-1 和 BUG-2 修了，能否跑通 `python -m pytest -q`？
2. 修完这两个 Bug 之后，当前树在赛题意义上的完成度？哪些扣分点已经覆盖、哪些仍然薄弱？
3. 如果要跑一次 API repeat=3 来验证当前 benchmark 设计是否有效，应该先修什么？

## 约束

- 用中文
- 每个判断落到文件:行号
- 不要给出修复建议——只分析问题
- 不要提 Docker/openEuler/nsjail/API repeat=10 执行
- 严格以 `题目.md` 为最高约束
- 不要凭印象回答，必须读代码验证
```
