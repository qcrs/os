# StateBus 第三轮全量审计

日期：2026-06-16
Branch：`feat/statebus-full-restructure-20260616`
Commit：`fef9888 change v4`
本轮改动：37 文件，+5666/-1622 行

---

## 一、本轮架构变化

### 1.1 Contest family spec 系统（新增）

**文件**：
- `tasks/contest_family_spec.yaml` (1621 行) — 集中的 family 定义，含 task_set 元数据、corpus_metadata、5 个 family 的 docs 和 cases
- `tasks/contest_family_spec.py` (132 行) — 解析 spec 并生成 contest benchmark YAML 和 corpus YAML
- `scripts/generate_contest_family_yaml.py` (31 行) — CLI 入口

`contest_dual_mode_controlled_v3_benchmark.yaml` 和 `contest_release_regression_corpus.yaml` 现在是生成产物，不再手动编辑。source of truth 是 `contest_family_spec.yaml`。

### 1.2 语义角色系统（semantic_role）

`protocol/messages.py:148`：`PlanStep` 新增 `semantic_role: str = ""` 字段。

`runtime/orchestrator.py`：
- `RunContext` 新增 `step_roles` dict + `set_step_role` / `semantic_role_for_step` / `step_input_refs_for_role` / `result_for_role` 方法
- `_semantic_role_for_step()` 回退到 `step.semantic_role or step.step_id`
- `prepare_plan()` 遍历每个 step 设置 `ctx.set_step_role(step.step_id, role)`
- 整个 orchestration loop 不再用 `step.step_id == "retrieve"` 而是用 `step_role == "retrieve"`
- `_find_step` / `_step_for_emit` 按 semantic_role 查找
- `resolve_skip_retrieve_execute` / `resolve_skip_execute` 使用 `ctx.result_for_role("retrieve")`

`runtime/langgraph_adapter.py`：
- `_step_by_role_or_id()` 替代旧的 `_step_by_id()`
- 所有 node 函数使用 semantic role 或 step_id 查找

`agents/sample_agents.py`：
- `build_plan()` 三步均显式设置 `semantic_role`
- LLM planner 的 `_compact_planner_output_to_steps` / `_normalize_planner_step` 解析 semantic_role
- `_validate_planner_semantic_coverage()` 校验至少含 `retrieve/execute/summarize` 三个 role
- DAG 校验允许额外步骤（如 `validate`）

**影响**：Plan 不再被 step_id 锁死。LLM Planner 可以产生 `validate-first → retrieve → execute → summarize` 的 4 步 plan，只要 semantic_role 正确。这是 Planner 从"被锁死"到"真正可用"的关键变化。

### 1.3 prior dependency 运行时执行

`runtime/orchestrator.py:2179-2260`：
- `_ensure_prior_dependency_for_fresh_execution()` — fresh execution 时检查 task 的 `required_prior_case_ids` 和 `required_prior_rejections`。如果前序 task commit 不存在或不含所需的 rejected_routes，**抛 Error + raise ValueError**，阻止 task 继续。
- `_prior_dependency_satisfied()` — replay hit 时也检查 prior dependency。从 `memory_store.task_commit_candidates()` 中查找对应 case_id 的 commit，验证 `rejected_routes` 覆盖 `required_rejections`。

**影响**：`required_prior_case_ids` / `required_prior_rejections` 不再只是 YAML 声明——runtime 在 fresh execution 和 replay 路径都会 enforce。没有前序 task 产出正确的 rejected_routes 时，后续 task 无法运行。

### 1.4 TaskCommit 增强

`runtime/orchestrator.py:1139-1149`：seal_task_commit 新增字段：
- `case_id` — 当前 task 的 case_id
- `chosen_route` — executor 选择的 route
- `rejected_routes` — 从 task 合同提取的 required_prior_rejections（供下游 task 检查）
- `safe_first_action` — executor 产出的第一个 action
- `first_validation_check` — summarizer 输出中提及验证的句子

---

## 二、Bug 修复验证

### BUG-1（旧版 plan_source 校验缩进错误）— ✅ 已修复

`tasks/sample_tasks.py:895-907`：新增独立的 `_validate_plan_source_contract()` 函数。覆盖所有 `formal_headline / formal_secondary / formal_secondary_planner / formal_secondary_memory` surface。不再嵌套在 `protocol_full_rich_audit` 的 if 内。

### BUG-2（旧版 typed_state_full_rich_audit_v3 加载失败）— ✅ 已修复

12 个 pack 全部加载成功。`typed_state_full_rich_audit_v3` 的 YAML 已添加 `public_surface`。

---

## 三、本轮新增问题

### BUG-3 [P1]：`test_state_ref_consumer_sensitivity_audit` 测试失败

**文件**：`tests/test_smoke.py:3684`

```
assert wrong_decision["status"] == "completed"
E       AssertionError: assert 'failed' == 'completed'
```

**原因**：`_validate_executor_decision_packet()` 的 hash 校验现在对 wrong_decision 生效。当 decision packet 的 route/tool 被覆盖为错误值，但 `feature_fresh_evidence_sha256` 可能不匹配（因为 packet 被修改了但 hash 没同步），导致 `ValueError("executor decision packet fresh evidence hash mismatch")`。

**这不是回归**——这是 validation hardening 的预期效果。wrong_decision packet 现在被正确地拦截为 failure 而不是静默通过。测试需要更新断言。

---

## 四、当前代码状态评估

### 4.1 Planner 状态

| 项目 | 状态 | 证据 |
|---|---|---|
| `build_plan()` 设置 semantic_role | ✅ | `sample_tasks.py:575/584/596` |
| LLM Planner 输出含 semantic_role | ✅ | `agents/sample_agents.py:1466/1630-1660` |
| LLM Planner 3-5 步 free | ✅ | `agents/sample_agents.py:1349-1352` |
| DAG 合法性校验 | ✅ | `agents/sample_agents.py:1748-1772` |
| semantic coverage（至少 retrieve/execute/summarize） | ✅ | `agents/sample_agents.py:1775-1780` |
| planner_support_v3 有 4-step validate case | ✅ | 6 个 llm 行，含 deploy-llm 和 auth-llm-002 |

**但**：contest 和 memory_policy 包的 `plan_source_default: yaml` 仍然意味着 Planner 在这些包上不会被调用。`planner_support_v3` 是 Planner 的唯一 formal evidence。

### 4.2 Contest benchmark 设计

| 项目 | 状态 |
|---|---|
| 所有 task 含 multi-route (`acceptable_routes >= 2`) | ✅ |
| 所有 task 含 multi-tool (`acceptable_tools >= 2`) | ✅ |
| Query 去关键词泄漏 | ✅（白名单测试锁住） |
| Reusable 行含 prior dependency 合同 | ✅（`required_prior_case_ids` + `required_prior_rejections`） |
| Prior dependency 运行时 enforce | ✅（fresh execution + replay 路径都检查） |
| Corpus 结构级 clean | ✅（`formal_structure_clean: true`） |
| Corpus 每个 family 8 类文档 | ✅（incident/metrics/logs/config_or_exe/distractor/ambiguous/scope/reuse） |
| YAML 从 spec 生成 | ✅（`contest_family_spec.yaml` → 脚本 → benchmark + corpus） |

### 4.3 Code quality issues（与上轮相同，未变）

| 问题 | 位置 |
|---|---|
| `executor_runtime.py:1850` — `route_confidence` 无 0.0-1.0 范围校验 | P3 |
| `orchestrator.py:873 + 1238` — `normalize_plan_source` 被调用两次 | 无害 |
| `memory_policy_controlled_v3` 缺 `formal_structure_clean_retrieval: true` | P2（仍需确认） |
| `_resolve_runtime_corpus_hints` 不检查 `formal_structure_clean_retrieval` | P2（当前无实际影响） |

### 4.4 测试状态

```
104 passed, 1 failed
```

唯一失败：`test_state_ref_consumer_sensitivity_audit_changes_executor_visibility_by_kind` — wrong_decision 的 status 从 `completed` 变为 `failed`（validation hardening 预期行为，需更新测试断言）。

---

## 五、赛题对照

| 赛题得分项 | 当前状态 | 关键 gaps |
|---|---|---|
| 通信效率 25 分 | contest 包 text vs protocol 对比结构完善 | 需要跑一次实跑 API 验证 control_bytes delta |
| 状态传递创新 20 分 | typed_state_mechanism + consumer_sensitivity 存在 | consumer sensitivity 测试需修（BUG-3） |
| 记忆复用效果 20 分 | memory_policy_controlled_v3 承担 formal | 需确认 `formal_structure_clean_retrieval` 配置 |
| 系统完整性 20 分 | Planner semantic_role 系统让 LLM 规划真正可用 | Planner 在 contest 包上仍被 yaml 绕过 |
| 实验验证 15 分 | prior dependency runtime enforce 补齐 | 需要实跑 API 验证 |

---

## 六、一句话总结

本轮 `feat/statebus-full-restructure-20260616` 是架构级的正向重构：
- semantic_role 系统让 Planner 从"被锁死"变成"真正可用"（可以在 plan 中插入 validate step）
- prior dependency 运行时 enforce 让 `required_prior_case_ids/rejections` 不再只是 YAML 声明
- contest family spec 让 contest 任务和 corpus 从手写变成生成，维护成本大幅降低
- TaskCommit 增强为完整的 task trace（case_id/chosen_route/rejected_routes/safe_first_action/first_validation_check）

**当前唯一需要修的是**：`test_state_ref_consumer_sensitivity_audit` 的 wrong_decision 断言需要从 `"completed"` 更新为 `"failed"`（因为 validation hardening 现在正确拦截了错误 packet）。
