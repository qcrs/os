# StateBus 当前遗留问题清单

日期：2026-06-15
Branch：`feat/contest-audit-hardening-20260615`
基准：`docs/review/statebus_seven_issue_fix_plan_20260615.md` 修复计划

---

## 已完成的背景（不需要再动）

以下 15 项修改已落地并验证通过，不需要重新讨论：

- `handoff_bytes` 移除、跨 mode 聚合按 `(mode, task_group)` 分组
- `memory_hit_rate` → `assist_memory_hit_rate` 全链路重命名
- `failure_count` → `run_failure_count`，新增 `negative_control_trigger_rate`
- `public_surface` 收敛为 `formal_headline / formal_secondary_planner / formal_secondary_memory / audit_only` 四类 + 8 个 alias
- Planner 审计字段（planner_source / planner_step_count / planner_contract_valid）挂到 RunContext + task payload
- `_plan_from_llm_output` 解除固定 3 步合同，改为 3-5 步 + DAG 合法性 + semantic coverage 校验
- executor 侧 `build_feature_bundle` 双重调用已移除，改为直接从 decision_packet 取值 + schema/hash 校验
- summarizer 非 audit 路径改用 compact JSON，不展开为长文本
- formal corpus 的 `route_hint→eval_route_label`、`tool_name→eval_tool_label` 字段重命名
- `retrieve_corpus_docs` 的 `preference_bonus` 对 formal 包关闭
- `_resolve_runtime_corpus_hints` 对 formal 包返回空
- `runtime_hint_allowed` 只对 audit_only 为 True
- typed_state_mechanism_v3 恢复为 formal secondary
- memory_policy_controlled_v3 重写为 contest-family checkout 连续任务
- open surface manifest 标 `audit_only` + `data_source: deterministic_oracle` + stopline 段

---

## 当前遗留问题

### 问题 1：Contest benchmark 的 query 仍然直接泄漏答案关键词

**文件**：`tasks/contest_dual_mode_controlled_v3_benchmark.yaml`

每个 family 的 query 仍然包含直接指向正确 route 的关键词。以下为所有 clean 行（text 侧）的 query：

| family | query 原文 | 泄漏的关键词 → 目标 route |
|---|---|---|
| checkout | `checkout release 17.4 canary shows connection pool waits and slow orders query after rollout` | `connection pool waits` → `db_pool_saturation` |
| auth | `auth metadata rotation canary shows issuer mismatch stale jwks and repeated callback verification failures` | `issuer mismatch stale jwks` → `auth_session_drift` |
| inventory | `inventory rollout region shows stale inventory after batch sync with dropped aggregate invalidation rate` | `dropped aggregate invalidation rate` → `cache_invalidation` |
| billing | `billing invoice workers show growing queue depth after release 9.2 with tls reload retries and delayed processing` | `growing queue depth` → `worker_queue_starvation` |
| deploy | `deployment canary shard shows pool cap mismatch after rollout alongside the checkout release` | `pool cap mismatch` → `db_pool_saturation` |

**影响**：`ToolRegistry.retrieve_candidates()` 默认对 query 做词法匹配。这意味着 text 侧的 executor 不需要读 corpus 文档，仅凭 query 词法就能猜对 route。protocol 侧传的 `EXECUTOR_DECISION_PACKET` 里的 route metadata 对于正确率是冗余的。

**修复计划要求**："每题至少 2-3 个 route family 都会被 query 词法命中"——当前所有 clean/simple 行的 `acceptable_routes` 只有 1 个。

---

### 问题 2：Clean/simple task 的 acceptable_routes 仍然只有 1 个

**文件**：`tasks/contest_dual_mode_controlled_v3_benchmark.yaml`

当前任务设计：

| 复杂度 | acceptable_routes 数量 | acceptable_tools 数量 |
|---|---|---|
| clean (simple) | 1 | 2 |
| distractor | 2 | 3 |
| ambiguous | 2 | 3 |
| replay_reusable | 1 | 2 |

clean 和 replay_reusable 行仍然只有 1 个 acceptable route。协议的结构化路由精度在这些 task 上没有展示空间——只有正确答案，没有候选竞争。

**修复计划要求**："每题至少 2-3 个 route family 都会被 query 词法命中，必须靠证据组合和 provenance 才能区分"——当前只对 distractor/ambiguous 实现了多 route，clean/replay_reusable 行没有。

---

### 问题 3：Corpus 文档内容未重写

**文件**：`tasks/contest_release_regression_corpus.yaml`

Diff 显示本轮的修改是**纯字段重命名**（`route_hint` → `eval_route_label`，`tool_name` → `eval_tool_label`），文档的 `text` 内容、数量、结构完全未变。

**当前 corpus 特点**：
- 32 个文档，5 个 family，每个 family 约 5-6 个文档
- 每个 family 有一个主 evidence 文档（如 `rr-checkout-incident`）和 3-4 个支撑文档
- distractor 文档（如 `rr-checkout-worker-false`）在同 family 内提供替代假说，但其 `text` 内容质量与主文档不对等
- 所有证据链中的"答案"仍然明显——没有需要跨 family 消歧的模糊证据

**修复计划要求**："formal corpus 文件删除 runtime 可见的 `route_hint` / `tool_name` 字段"——✅ 已完成。"但 corpus 内容本身需要重构以支持多候选路由和跨 family 推理"——❌ 未做。

---

### 问题 4：没有跨 family 的 distractor

**文件**：`tasks/contest_dual_mode_controlled_v3_benchmark.yaml`

当前 distractor 文档（如 `rr-checkout-worker-false`）和主文档在同一个 family 内。例如 checkout family 的 distractor 是一个关于 `worker_queue_starvation` 的文档，但其 `text` 内容较弱——它不是真正和主 evidence 文档竞争的"对抗性证据"。

**修复计划要求**："distractor 要跨 family，不是同 family 弱干扰"——当前仍然是同 family 内的弱干扰。

---

### 问题 5：没有跨任务依赖（cross-task reuse dependency）

**文件**：`tasks/contest_dual_mode_controlled_v3_benchmark.yaml`

当前每个 family 的 4 个 task chain（clean→distractor→ambiguous→replay_reusable）之间没有真正的依赖关系。replay_reusable 行只是"同样的 query 换个说法"，不需要从上一个 task 的产出（排除的证据、确认的策略）中获取信息。

**修复计划要求**："第二题必须识别第一题产出的结论、策略或排除项"—当前无此设计。

---

### 问题 6：protocol 和 text 共享同一个 tool registry 的精确度天花板

**代码定位**：
- `executor_runtime.py:59` — `ToolRegistry` 定义
- `executor_runtime.py:95-148` — `retrieve_candidates()` + `infer_match()` 词法匹配逻辑
- `executor_runtime.py:1657-1686` — `_feature_bundle_from_strict_pure_text_handoff()` text 侧用同一个 registry

text 侧 executor 调用 `registry.retrieve_candidates(query_text)` 做词法匹配来选 route/tool。protocol 侧 executor 用 `EXECUTOR_DECISION_PACKET` 里的 route/tool 直接执行。但如果任务简单到 query 词法就能猜对（见问题 1），那两边的正确率天花板相同——0.85 是 task 难度的上限，不是通信格式的上限。

**这是一个设计矛盾**：为了让 text 侧有一个公平基线，它被允许使用同一个 tool registry 做词法匹配。但这也意味着只要 task 的 query 关键词够强，text 侧的"推理"就是查字典，protocol 侧的精确路由传输变得无用。

---

### 问题 7：缺乏 "formal hint 禁止消费" 的显式测试

**当前代码**：有纵深防御——`runtime_hint_allowed`（`sample_tasks.py:250`）+ `_resolve_runtime_corpus_hints`（`sample_agents.py:1884`）。但没有专门测试断言 "formal pack 运行时 hint 数组确实为空"。

---

### 问题 8：planner_support_v3 的 4-step plan 只有 YAML 声明、无测试验证

**文件**：`planner_support_v3_benchmark.yaml:522` — deploy-llm 行 goal 写 "four-step plan row that explicitly validates the route before execution"。但 `tests/test_smoke.py` 中没有测试验证 LLM 实际产出的 plan 确实是 4 步。

---

## 优先级排序

| 优先级 | 问题 | 影响面 | 赛题关联 |
|---|---|---|---|
| P0 | 问题 1：Query 泄漏答案关键词 | contest 包全部 40 行 | 通信效率 25 分、实验验证 15 分 |
| P0 | 问题 2：Clean task 单 route | contest 包 20 行（clean + replay） | 通信效率、状态传递创新 20 分 |
| P0 | 问题 3：Corpus 内容未重写 | 所有 11 个 v3 pack 的 corpus 依赖 | 状态传递创新、记忆复用效果 20 分 |
| P1 | 问题 4：无跨 family distractor | contest 包 distractor/ambiguous 行 | 实验验证 15 分 |
| P1 | 问题 5：无跨任务依赖 | contest 包 replay_reusable 行 | 记忆复用效果 20 分 |
| P2 | 问题 6：共享 tool registry 天花板 | executor_runtime.py | 实验验证（归因 clarity） |
| P2 | 问题 7：缺 formal hint 禁止测试 | test_smoke.py | 系统完整性（regression guard） |
| P2 | 问题 8：缺 4-step plan 测试 | test_smoke.py | 系统完整性（regression guard） |
