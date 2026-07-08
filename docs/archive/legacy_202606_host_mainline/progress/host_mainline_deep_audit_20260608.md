# StateBus Host-Mainline 深化审计报告

日期：`2026-06-08`

适用范围：这份报告只审计当前 `host-mainline` 以及它之前已经形成的实现与证据层，不把 Docker / openEuler / `nsjail` 当本轮主问题；它们只能作为后续阶段边界被轻提。

更新说明：

- `2026-06-08 08:48 CST` 之后，下面几处“问题”已经在当前 worktree 里被直接修正：
  - `runtime/smoke.py` 现在已有真实模块入口，新的
    `runs/host_goal_eval_20260608_084835_provenance_gate_refresh/runtime_smoke.txt`
    不再是空文件；
  - plan step 不再把 `expected_reuse_mode` 继续下发成运行时参数；
  - route 归档不再默认写成 `corpus_metadata`，而是开始记录
    `hint_consensus` / lexical provenance / route confidence。
- 因此，这份文档里关于上述三点的批评应理解为**修正前审计发现**，不是当前最新状态。
- `2026-06-08 10:00 CST` 之后，planner text-mode numeric `step_id` 导致的
  live API rerun 不稳定也已经被收口：
  - 新的 `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`
    已重新归档 `36 passed`、非空 `runtime_smoke.txt`、deterministic
    `repeat=10` 稳定，以及 serialized API `repeat=10` 的 `text/protocol`
    `10/10`
  - `runs/host_goal_eval_20260608_084835_provenance_gate_refresh/api_repeat10_serial/`
    应视为中途失败的诊断包，不再作为 formal live API 引用
- `2026-06-08 12:08 CST` 之后，executor candidate-tool 这一轮也已闭环：
  - 新的 `runs/host_goal_eval_20260608_120619_executor_candidate_tool_refresh/`
    归档了 deterministic `repeat=10`
  - `tool_candidates` 仍只保留在 `FEATURE_BUNDLE`
  - execute payload 不再回灌 `tool_candidates`
- `2026-06-08 12:31 CST` 之后，exact replay gate 也进一步去特化：
  - 新的 `runs/host_goal_eval_20260608_122921_exact_replay_drop_doc_preference_refresh/`
    归档了 deterministic `repeat=10`
  - `skip_retrieve_execute` 不再要求当前任务的 `preferred_corpus_doc_ids`
  - gate 现在主要依赖 memory 里已经归档的 query / route / evidence 一致性
- `2026-06-08 12:41 CST` 之后，doc ids 也退成任务级输入：
  - `preferred_corpus_doc_ids` 不再属于 `RuntimeTaskProfile`
  - 它现在由 `RunContext` 的 task-level corpus hint 持有
- `2026-06-08 12:49 CST` 之后，这条口径被最终收口成当前 deterministic refresh：
  - 新的 `runs/host_goal_eval_20260608_124900_runtime_profile_trim_refresh/`
    继续保持 `repeat=10` 稳定
  - `RuntimeTaskProfile` 当前只剩 `runtime_reuse_contract`
- `2026-06-08 13:08 CST` 之后，live memory lookup 也进一步去特化：
  - 新的 `runs/host_goal_eval_20260608_130836_runtime_drop_reuse_tags_refresh/`
    继续保持 deterministic `repeat=10` 稳定
  - `reuse_tags` 不再参与 live memory query 预过滤

---

## 1. 审计范围与证据源

### 1.1 范围

- 当前工作范围限定在 `/home/qcrs/statebus/project`
- 审计对象限定为：
  - 赛题 requirement 与当前实现是否对齐
  - 当前 host-mainline 到底是什么
  - 当前 replay / reuse / retriever / executor 主线是否合理
  - 当前 benchmark 与文档口径是否诚实
- 明确不把下面这些当成本轮主问题：
  - Docker 交付
  - openEuler VM 验证
  - `nsjail` / 强沙箱终态
  - hidden-state / KV 传递

### 1.2 核心证据源

- 题目与范围文档：
  - `docs/reference/题目.md`
  - `docs/constraints/current_host_and_migration.md`
  - `docs/constraints/current_feature_scope.md`
  - `docs/planning/implementation_plan.md`
  - `docs/planning/host_goal_mainline_dependency_20260607.md`
  - `docs/planning/host_goal_review_execution_plan_20260607.md`
  - `docs/planning/goal_prompt_host_mainline_execute_20260608.md`
- 现有审计与正式证据：
  - `docs/progress/contest_requirement_host_audit_20260607.md`
  - `runs/comprehensive_eval_20260607_131113/`
  - `runs/host_goal_eval_20260607_233858/`
  - `runs/host_goal_eval_20260608_032333_runtime_reuse_contract_refresh/`
  - `runs/host_goal_eval_20260608_084835_provenance_gate_refresh/`
  - `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`
  - `runs/host_goal_eval_20260608_120619_executor_candidate_tool_refresh/`
  - `runs/host_goal_eval_20260608_122921_exact_replay_drop_doc_preference_refresh/`
  - `runs/host_goal_eval_20260608_124900_runtime_profile_trim_refresh/`
- 关键实现锚点：
  - `runtime/smoke.py`
  - `runtime/orchestrator.py`
  - `runtime/reuse_contract.py`
  - `runtime/executor_runtime.py`
  - `agents/sample_agents.py`
  - `eval/runner.py`
  - `tasks/sample_benchmark.yaml`
  - `tasks/sample_tasks.py`
  - `tasks/local_corpus.py`
  - `tests/test_smoke.py`

### 1.3 本轮特别补看的证据

- `runtime/smoke.py:21-34`
  - 只定义了 `main()`，没有模块入口
- `runs/comprehensive_eval_20260607_131113/runtime_smoke.txt`
- `runs/host_goal_eval_20260608_032333_runtime_reuse_contract_refresh/runtime_smoke.txt`
  - 两个文件都是 `0` 字节
- `runtime/orchestrator.py:434-627`
  - exact replay 的真实匹配条件
- `tasks/local_corpus.py:97-127`
  - `route_hint` / `tool_name` 如何进入 route 决策
- `runtime/executor_runtime.py:130-340`
  - `Executor` 的真实运行形态
- `eval/runner.py:94-112`, `252-257`
  - benchmark 切片与 expectation 校验逻辑

---

## 2. 赛题要求逐项核对

| 赛题要求 | 当前状态 | 直接证据 | 真实边界 |
| --- | --- | --- | --- |
| 至少 3 个 Agent | 已实现 | `agents/sample_agents.py:367-414` | 当前是 `Planner/Retriever/Executor/Summarizer` 四角色，但仍是单仓库内 staged pipeline |
| `text` / `protocol` 双模式 | 已实现 | `eval/runner.py`, `tests/test_smoke.py:50-105` | 对比轴成立，但两边底层还是同一运行时 |
| 结构化通信与握手 | 已实现 | `runtime/orchestrator.py:532-548` | 已经不是长文本透传，但外部 transport 只覆盖 executor 样机 |
| 非文本状态传递 | 已实现 | `runtime/orchestrator.py:156-240` | 已实现的是 `DENSE_EVIDENCE / FEATURE_BUNDLE / EMBEDDING / StateRef`，不是 hidden-state / KV |
| 共享记忆与语义检索 | 已实现 | `runtime/orchestrator.py:242-317`, `agents/sample_agents.py:316-364` | SQLite + FAISS 主线是真实的，但复用泛化边界受任务合同和 incident family 约束 |
| 关联连续任务 | 已实现 | `tasks/sample_benchmark.yaml` | 当前是 3 组 x 6 任务，共 18 任务；不是开放任务流 |
| 统计通信、状态、时间、复用收益 | 已实现 | `eval/runner.py:31-239` | 指标齐全，但部分指标切片仍依赖 benchmark expectation |
| 10 轮稳定运行 | 宿主机已实现 | `runs/comprehensive_eval_20260607_131113/`, `runs/host_goal_eval_20260608_032333_runtime_reuse_contract_refresh/` | 这是 host-side 证据，不是最终 openEuler 交付证据 |
| 最终 openEuler 交付 | 后续阶段未验证 | 仅有文档边界 | 本轮不能当已完成项 |

硬结论：

- 当前仓库不是 design-only。
- 当前仓库也不是通用多 Agent runtime 完成态。
- 它已经是一个真实可运行的 host-side 赛题样机，但还有明显赛题特化。

---

## 3. 优化前后对照

### 3.1 真正发生了的实现深化

相对更早的 design-first 状态，当前仓库确实新增了这些真实能力：

- `StateRef + mmap/shared_memory` 已经进入真实代码路径，不是空概念
- `SQLite + FAISS` 共享记忆已经能查询、命中、写回
- `FEATURE_BUNDLE` 已经成为真实非文本中间态，而不只是“给个 embedding”
- `protocol` 相比 `text` 的控制面压缩与 API 时延收益已有正式包
- replay-aware `18` 任务链现在已有 repeat-10 的 deterministic 和 serialized API 证据

### 3.2 仍然只是“收口口径”，不是能力跃迁的地方

下面这些地方更多是口径升级，不应被误写成系统能力已本质升级：

- `assist-only` 到 `skip_execute / skip_retrieve_execute` 的提升是真的
  - 但主要成立于受控任务合同、固定 incident family、固定 doc-set、固定 route 面
- “runtime-evidence exact replay” 的表述比旧版本更诚实
  - 但它仍不是开放任务上的通用 replay
- `text` / `protocol` 的比较更完整了
  - 但这不是两套独立运行时的正面对抗

### 3.3 有一处证据层曾经需要降级，但现在已经被修正

- 历史 `python -m runtime.smoke` 不能被当成强 smoke 证据
  - 当时 `runtime/smoke.py` 没有 `if __name__ == "__main__": main()`
  - 历史归档的 `runtime_smoke.txt` 也是空文件
  - 这说明旧包里的“smoke 完成”说法证据强度不足
- 但当前状态已经不同：
  - `runtime/smoke.py` 已补上模块入口
  - `runs/host_goal_eval_20260608_084835_provenance_gate_refresh/runtime_smoke.txt`
    已真实归档 stdout

### 3.4 executor 候选工具集也已落地

- `runs/host_goal_eval_20260608_120619_executor_candidate_tool_refresh/deterministic_repeat10/benchmark_report.md`
  证明 executor 现在不只是固定 route -> playbook，还会先收敛出小的 ranked `tool_candidates`
- 这一步没有把候选集合塞回 execute payload，说明它现在是观察态，不是控制面膨胀

### 3.5 exact replay gate 继续去特化

- `runs/host_goal_eval_20260608_122921_exact_replay_drop_doc_preference_refresh/deterministic_repeat10/benchmark_report.md`
  证明 exact replay 现在不再依赖当前任务的 `preferred_corpus_doc_ids`
- 这一步保留了 `skip_retrieve_execute`，但把决定条件收紧到已归档的 query / route / evidence 一致性

### 3.6 runtime profile 已收窄到运行时合同

- `runs/host_goal_eval_20260608_124900_runtime_profile_trim_refresh/deterministic_repeat10/benchmark_report.md`
  证明把 `corpus_doc_ids` 退成 task-level corpus hint、并从 `RuntimeTaskProfile` 里删掉之后，当前 repeat-10 头没有塌
- 当前 `RuntimeTaskProfile` 只剩 `runtime_reuse_contract`

### 3.7 runtime memory lookup 已不再吃 benchmark tag bucket

- `runs/host_goal_eval_20260608_130836_runtime_drop_reuse_tags_refresh/deterministic_repeat10/benchmark_report.md`
  证明把 `reuse_tags` 从 live memory query 预过滤里拿掉之后，当前 repeat-10 头也没有塌
- 当前 deterministic headline 继续保持：
  - `failure_count = 0`
  - `expectation_match_rate = 1.00`
  - `skipped_step_count = 9`
  - `reuse_gain = 0.17`
  - `memory_hit_rate = 0.83`
  - control bytes：`132735 -> 119008`

---

## 4. 当前主线到底是什么

当前真实主线不是“通用多 Agent 系统基础设施”，而是下面这条 host-side contest pipeline：

1. `Planner` 现在只产出语义 plan skeleton；`runtime_reuse_contract`、`corpus_doc_ids`、
   `reuse_signature` 不再进入 live plan params，而是退到 side-band runtime profile
   - 见 `agents/sample_agents.py:71-89`
   - 见 `tasks/sample_tasks.py:116-167`
2. `Retriever` 先从 repo-local corpus 取证，再构造：
   - `DENSE_EVIDENCE`
   - `FEATURE_BUNDLE`
   - `EMBEDDING`
   - 见 `agents/sample_agents.py:97-227`
3. `FEATURE_BUNDLE` 的 route 当前会先把 metadata hint 当候选，但已经开始记录
   lexical / metadata 的 provenance 与 confidence，并允许 lexical 证据覆盖冲突 hint
   - 见 `runtime/executor_runtime.py:270-323`
   - 见 `tasks/local_corpus.py:97-127`
4. `Executor` 本质上是 route -> small candidate-tool set -> tool/playbook 选择器
   - 见 `runtime/executor_runtime.py:130-267`
5. `Summarizer` 用 LLM 生成摘要，然后回写共享记忆
   - 见 `agents/sample_agents.py:275-364`
6. `Orchestrator` 在特定 reuse contract 下，允许：
   - assist
   - skip_execute
   - skip_retrieve_execute
   - 见 `runtime/orchestrator.py:378-783`
7. `eval.runner` 对同一任务链跑 `text` / `protocol` 对比，并按 expectation 切片出 replay 统计
   - 见 `eval/runner.py:94-112`, `252-257`

这条主线可以运行，也有实证。

但它的本质仍然是：

> 围绕 3 个固定 incident family、repo-local corpus、固定 playbook registry、固定 task contract 搭起来的 contest prototype。

---

## 5. 赛题特化 / 过拟合问题

### 5.1 任务合同不再直接污染 live plan，但仍保留 task-level corpus hint

- `tasks/sample_benchmark.yaml` 明写：
  - `expected_reuse_mode`
  - `runtime_reuse_contract`
  - `corpus_doc_ids`
  - `reuse_tags`
- `eval/runner.py` 现在把 `runtime_reuse_contract` 注入 `RuntimeTaskProfile`，并把 `corpus_doc_ids` 作为 task-level corpus hint 单独传给 `RunContext`

这意味着：

1. benchmark 已经不再通过 live plan params 直接泄漏这些字段；
2. `reuse_signature` 也已经不再是 runtime memory query 的主过滤条件；
3. 运行时合同现在主要剩 `runtime_reuse_contract`；
4. `corpus_doc_ids` 只作为 task-level corpus hint 存在，不再冒充 runtime profile 的一部分。

### 5.2 retriever 不是开放检索，更像 repo-local 证据打包器

- `tasks/local_corpus.py:52-86` 默认候选集就已经被 `task_group / task_theme / corpus_doc_ids` 缩小
- `agents/sample_agents.py:99-116` 再把这些 repo-local 文档转成固定证据块

所以当前 `Retriever` 更接近：

> 在一个小型受控语料里做 incident-family 定位，再把证据打包给后续步骤。

而不是：

> 对开放知识域做更一般化的跨任务检索。

### 5.3 route 决策曾经过强依赖 corpus metadata hint，但当前 worktree 已开始收紧

- `tasks/local_corpus.py:97-127` 会提取 `route_hint` / `tool_name`
- 历史版本里，`runtime/executor_runtime.py` 确实把 `corpus_metadata` 放在 lexical match 前面
- 历史测试也曾显式断言 exact replay 任务的 `feature_route_source == "corpus_metadata"`

这会导致当前最强 replay 路径严重依赖：

- 样本语料已经给过 route hint
- hint 与 tool registry 是一一适配的

但当前最新 `084835` 包已经开始把这条路径收紧成：

- `feature_route_source = hint_consensus`
- `feature_route_provenance = ["corpus_metadata", "lexical"]`
- exact replay 继续要求更强的 route confidence / provenance

### 5.4 executor 更像 playbook selector，不是通用执行层

- `runtime/executor_runtime.py:133-265` 注册的是固定 incident playbook
- 当前 route 基本就是：
  - `cache_invalidation`
  - `db_pool_saturation`
  - `auth_session_drift`
  - 以及少量 false-route control
- 当前 worktree 虽然已经增加了小候选工具集检索，但候选集合仍围绕这些固定 incident family 展开

这不是坏事。

但它意味着当前 `Executor` 的更准确定位应是：

> route-aware playbook executor

而不是：

> 通用 action runtime

---

## 6. 记忆分层与检索分层审计

### 6.1 记忆层本身是真实的

下面这些不是伪实现：

- `MemoryCommit` 的写回
- `MemoryQuery` 的查询
- SQLite 元数据
- 向量检索
- 复用命中 / 拒绝 / assist / skip 的统计

所以问题不在“有没有 memory module”，而在：

> 现在这条 memory 链路到底证明了多强的跨任务复用能力。

### 6.2 当前其实存在 4 层不同含义

1. fresh retrieval
2. memory assist
3. validated replay
4. exact replay

代码上分别散落在：

- `agents/sample_agents.py:118-150`
- `runtime/orchestrator.py:434-520`
- `runtime/reuse_contract.py:6-40`
- `eval/runner.py:64-75`, `94-112`

### 6.3 “记忆层”与“检索层”并没有真正解耦

当前 exact replay 仍要求多重匹配同时成立：

- `task_theme`
- `reuse_signature`
- `stored_query == current_query`
- `feature_route == expected_route`

直接证据：

- `runtime/orchestrator.py:474-506`
- `runtime/orchestrator.py:625-657`

这说明当前 exact replay 更接近：

> 在已知 incident family 内，对同一路由、同一 query 形状做受控复放。

而不是：

> 从更宽的历史记忆中自然地推断“这个任务可以不再检索/执行”。

### 6.4 为什么 `text` / `protocol` 的 memory 指标看起来几乎一样

不是因为实现 bug。

更主要是因为：

- 两边跑的是同一任务链
- 两边共享同一种 memory policy
- reuse decision 不依赖文本叙事风格，而依赖相同的结构化 contract / metadata 条件

所以当前 memory 指标的“模式间一致”，更多说明：

> replay contract 主导了 reuse 结果。

而不是说明：

> memory 已经足够自然和模式无关。

---

## 7. 虽然满足赛题字面要求，但内部链路并不合理

### 7.1 `runtime.smoke` 被当作回归门，但它其实没有 CLI 入口

- `runtime/smoke.py:21-34` 有 `main()`
- 但没有模块入口
- 历史 `runtime_smoke.txt` 也是空文件

这意味着：

- `python -m runtime.smoke` 返回 `0`，最多证明导入没炸
- 不能证明完整 smoke 真跑完了

这是一个典型的：

> 字面上“跑了 smoke”，但内部证据链并不成立。

### 7.2 exact replay 说是 runtime-evidence，但证据仍高度依赖外部任务形状

- `expected_route` 来自 `corpus_doc_ids -> corpus metadata`
- `retrieved_doc_ids` 直接要求和候选 doc-set 一致
- `stored_query` 也要求和当前 query 归一化后相等

见：

- `runtime/orchestrator.py:457-480`
- `runtime/orchestrator.py:602-627`

这会让“跳过检索”成立的前提仍然很强。

更直白地说：

> 这条 exact replay 不是在更开放条件下自己长出来的，而是被当前任务和语料形状强支撑着。

### 7.3 benchmark expectation 与 runtime decision 仍然缠在一起

- `eval/runner.py:94-112` 用 `expected_reuse_mode` 做统计切片
- `eval/runner.py:252-257` 直接用它校验 `matched_expectation`
- `tasks/sample_tasks.py:50-84` 里，默认 gate 又会回落到 `expected_reuse_mode`

这并不等于现在的 runtime 还是假的。

但它说明：

> benchmark 合同、任务先验、runtime gate 三者还没有彻底切干净。

### 7.4 `text` / `protocol` 是有效对比，但不是两条独立运行时路线

两边共享：

- 同一个 orchestrator
- 同一个 statepool
- 同一个 memory store
- 同一个 executor
- 同一个 replay contract

真正差异主要在：

- 控制面载荷编码
- 文本叙事渲染
- 由此带来的 token / bytes / live API latency

所以当前能成立的说法是：

> 结构化协议降低了通信负担。

不宜拔高成：

> 当前已经证明了两类协作架构的系统级路线优劣。

---

## 8. 当前最主要的问题

这里明确不把 Docker / openEuler / `nsjail` 算进去。

### 8.1 第一问题：证据层有一个明显假强项

就是 `runtime.smoke`。

这不是功能主链路的大 bug，但它直接污染了“回归门真的跑过”的证据可信度。

### 8.2 第二问题：replay gain 仍主要成立于受控合同，而不是自然 runtime 判定

当前最核心的限制不是“没有 gain”，而是：

- gain 已经有
- 但 gain 的触发条件仍太像 benchmark scaffold

这会限制外部对“共享记忆真的减少重复计算”的信任强度。

### 8.3 第三问题：retriever / executor 仍然过度贴合样本 incident family

当前 repo 不是空壳。

但从 generalization 角度看，它仍明显更像：

- repo-local incident route system
- playbook reuse scaffold

而不是更一般化的任务系统。

### 8.4 第四问题：文档层与实现层仍需要更严格分层

当前 `README.md`、`current_feature_scope.md`、`implementation_plan.md`、`runs/*` 已经比以前清楚，但仍然容易让后续 goal 把下面三层混掉：

1. 旧正式基线
2. 当前 replay-aware 验证层
3. dirty worktree 的推进层

### 8.5 第五问题：当前“新意”空间不能再靠堆功能获得

如果继续往前加：

- Docker
- VM
- 沙箱
- 更重 transport

这轮只会把主线再次冲散。

当前真正还有价值的新意，只能来自：

> 在 host-mainline 内，让 replay / retrieval / route selection 更少依赖赛题合同。

---

## 9. 当前阶段最值得做的修正顺序

### 9.1 第一优先级：修证据，不先扩功能

先做：

1. 修 `runtime/smoke.py` 模块入口
2. 让 smoke stdout 真正归档
3. 以后只有看到实际输出，才把它算作回归门通过

这是最低成本、最高收益的证据修复。

### 9.2 第二优先级：把 benchmark expectation 与 runtime decision 再切开一层

重点不是把 `expected_reuse_mode` 删除干净，而是：

- 不让它再被误读成 runtime 主决策面
- 让 report 明确哪些是 expectation，哪些是 actual gate

### 9.3 第三优先级：做一组去 hint / 弱 doc-set 约束的 matched benchmark

最值得补的不是更多 repeat 数，而是更有解释力的对照：

1. 去掉 `corpus_metadata` hint
2. 放松 `candidate_doc_ids` 的硬匹配
3. 保留同一 incident family 的 negative control

如果这样一做，gain 明显塌掉，也要直接承认。

### 9.4 第四优先级：降低 retriever / executor 的 route 锁定强度

最有价值的方向不是再加 tool，而是：

- 让 `route_hint` 从“强先验”降到“弱先验”
- 让 `Executor` 更多消费 feature evidence，而不是吃现成 route label

### 9.5 第五优先级：只有前四项成立后，才谈 host-only 的新意深化

如果还能继续深化，唯一值得优先押注的方向是：

> 把 replay 触发从“同 query + 同 route + 同 doc-set”推进到“带 provenance 和 confidence 的 runtime evidence gate”。

这条线有新意，而且不需要跨到 Docker / openEuler / `nsjail`。

---

## 10. 如可联网：GitHub 可借鉴参考

本节只保留方向性参考；本轮没有重新联网核验，不应把这些仓库的当前状态当作已确认事实。

- `langchain-ai/langgraph`
  - 可借鉴 graph state 和 replay / checkpoint 组织方式
- `temporalio/sdk-python`
  - 可借鉴 workflow / replay 语义与 history boundary
- `deepset-ai/haystack`
  - 可借鉴 retrieval 分层和 evaluator 思路
- `mem0ai/mem0`
  - 可借鉴 memory policy 与 commit / recall 分层
- `openai/openai-agents-python`
  - 可借鉴 agent handoff 与 tool orchestration 的简化接口

这里最值得参考的不是“照搬框架”，而是：

- 如何把 history / replay / memory 的边界说清楚
- 如何把 route / tool / retrieval 的职责拆开

---

## 11. 最终判断

当前仓库已经形成了一个真实可运行的 host-side 赛题样机，不是空架子，也不只是 benchmark 包装。它在 `protocol`、`StateRef`、`memory`、`eval` 这些主骨架上已经站住了。

但按严格审计口径，它的本质仍然是：

> 一个围绕固定 incident family、固定语料、固定 playbook、固定 replay 合同构建的赛题化原型，而不是通用多 Agent runtime。

当前最主要的问题也不是“还没做 Docker / openEuler / nsjail”，而是：

1. 证据层还有假强项，`runtime.smoke` 不能再被当成强证明
2. replay gain 仍然过度依赖任务合同和样本形状
3. retriever / executor 的去特化还不够

所以这一轮后续 goal 的正确方向，不是扩更多系统层名词，而是：

> 先把 host-mainline 里的赛题特化问题压下去，再看还能不能在 runtime-evidence replay 上做出真正有新意的深化。
