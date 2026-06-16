# StateBus 全量代码 Review（第二轮）

日期：2026-06-15
Commit：`44f7af8 add ceshi`
Branch：`feat/contest-audit-hardening-20260615`

---

## 一、致命 Bug

### BUG-1 [致命]：plan_source 校验被嵌套在错误的 if 块内

**文件**：`tasks/sample_tasks.py:893-909`

```python
893:     if task.summary_contract == "actions_plus_evidence" and task.handoff_profile == "protocol_full_rich_audit":
894:         raise ValueError(...)
896:         )
897:         if (                                              # ← 缩进在 893 的 if 块内部
898:             task_set_metadata.pack_type in V3_FORMAL_TASK_PACK_TYPES
899:             and task_set_metadata.public_surface == "formal_headline"
900:             and not task_set_metadata.plan_source_default
901:             and not explicit_plan_source
902:         ):
903:             raise ValueError(f"{task.task_id}: formal packs must resolve plan_source explicitly")
904:         if (
905:             task_set_metadata.pack_type in V3_FORMAL_TASK_PACK_TYPES
906:             and task_set_metadata.public_surface == "formal_headline"
907:             and task.plan_source not in PLAN_SOURCES
908:         ):
909:             raise ValueError(f"{task.task_id}: formal packs require explicit plan_source")
```

**原因**：第 893 行的 if 条件 `summary_contract == "actions_plus_evidence" AND handoff_profile == "protocol_full_rich_audit"` 对 contest 包所有 40 个 task **永远为 False**——contest 的 handoff_profile 是 `text_strict_pure_lane` 或 `protocol_minimal_state_packet`。因此第 897-909 行的 plan_source 校验**永远不会执行**。

**后果**：如果有人删除 contest YAML 的 `plan_source_default: yaml`，系统不会报错，所有 task 的 plan_source 会静默退化为默认 `"yaml"`。plan_source 校验形同虚设。

---

### BUG-2 [致命]：`typed_state_full_rich_audit_v3` 加载失败

**现象**：
```
FAIL: typed_state_full_rich_audit_v3: v3 pack metadata requires public_surface
```

**原因**：该 YAML 的 `evidence_tier: support_only`，没有 `public_surface`。`sample_tasks.py:660-668` 的 auto-inference 只覆盖 `audit_only` 和 `formal_secondary` 两种情况，不覆盖 `support_only`。

```yaml
# typed_state_full_rich_audit_v3_benchmark.yaml:7
evidence_tier: support_only
# 缺少 public_surface
```

`_validate_task_set_metadata_contract()` at line 934-935 要求 v3 pack 必须有 `public_surface`，而 `support_only` 没有对应的 auto-inference 规则。

**后果**：这个 pack 无法被 benchmark runner 加载。12 个 v3 pack 中有 1 个坏了。

---

## 二、中等问题

### BUG-3 [中]：`_resolve_runtime_corpus_hints` 不检查 `formal_structure_clean_retrieval`

**文件**：`agents/sample_agents.py:1881-1888`

```python
def _resolve_runtime_corpus_hints(*, ctx, corpus_docs):
    task_metadata = getattr(getattr(ctx, "task", None), "task_set_metadata", None)
    runtime_hint_allowed = True
    if isinstance(task_metadata, TaskSetMetadata):
        runtime_hint_allowed = task_metadata.runtime_hint_allowed
    if not runtime_hint_allowed:
        return []
    return extract_corpus_feature_hints(corpus_docs)
```

这个函数只检查 `runtime_hint_allowed`，不检查 `formal_structure_clean_retrieval`。当前不会导致实际 bug——因为 `runtime_hint_allowed` 在 formal headline 包上已经是 `False`（`public_surface != "audit_only"`），所以始终返回 `[]`。但如果以后有人修改了 `runtime_hint_allowed` 的逻辑（例如让某些 formal 包也可以通过此检查），这里就可能泄漏 hint。

**当前影响**：无实际 bug，但代码意图不完整——两个独立的 clean 机制（`runtime_hint_allowed` 和 `formal_structure_clean_retrieval`）应该在 hint 决议上同时生效。

---

### CONFIG-1 [中]：`memory_policy_controlled_v3` 缺少 `formal_structure_clean_retrieval`

**文件**：`tasks/memory_policy_controlled_v3_benchmark.yaml:1-15`

该 pack 的 metadata 中没有 `formal_structure_clean_retrieval: true`。这意味着当这个 pack 运行时：
- `_formal_structure_clean_retrieval(ctx)` 返回 `False`
- `retrieve_corpus_docs()` 的 formal_structure_clean_retrieval 参数为 `False`
- **theme/group bonus 仍然是 0.12/0.06**（不是 0）
- `preferred_doc_ids` 仍然进入 `candidate_ids`（虽然 `allow_preferred_doc_bias` 已通过 `_runtime_preferred_doc_bias_allowed` 关掉）

**影响**：memory_policy_controlled_v3 包的 retrieval 偏置比 contest 包更大。这个 pack 是 formal_secondary_memory，它的 retrieval 应该保持和 contest 包一致的结构级 clean。

---

### CONFIG-2 [中]：Contest 和 memory_policy 包的 Planner 仍然被绕过

**确认**：
- `contest_dual_mode_controlled_v3_benchmark.yaml:14` — `plan_source_default: yaml`
- `memory_policy_controlled_v3_benchmark.yaml:12` — `plan_source_default: yaml`

执行路径：`orchestrator.py:1238-1240` → `plan_source == "yaml" → build_plan(task)` → 硬编码 3 步 plan。

**这是刻意设计决策（修复计划 Phase 1 明确说了"不把 contest 包改成 llm"），但需要确认是否是最终决定。** `planner_support_v3` 的 6 个 llm 行承担了 Planner 证据。

---

## 三、一致性问题

### CONSISTENCY-1：`_validate_task_set_metadata_contract` 的 variable_axes 检查放宽

**文件**：`sample_tasks.py:938`

```python
# 旧代码：
if not variable_axes:
    raise ValueError(...)

# 新代码：
if not variable_axes and public_surface == "formal_headline":
    raise ValueError(...)
```

非 headline pack 现在可以不声明 `variable_axes`。当前所有 pack 的 YAML 都声明了 `variable_axes`，所以此改动尚未隐藏实际数据问题。但如果新增 pack 时漏写了 `variable_axes`，旧代码会拦截，新代码不会。

---

### CONSISTENCY-2：Contest 包的 clean 行 `case_type` 从 `exact_single_solution` 改为 `bounded_alternative`

**文件**：`contest_dual_mode_controlled_v3_benchmark.yaml` — 所有 clean/simple 行

```yaml
case_type: bounded_alternative  # 原来是 exact_single_solution
```

因为 clean 行现在有 2 个 `acceptable_routes`（如 `db_pool_saturation` 和 `worker_queue_starvation`），不再适用 `exact_single_solution`。这个改正是正确的——但需要确认 `case_type` 变更是否在 runner 的 misfire audit 中正确反映（`bounded_alternative` 的 matching 逻辑是否与 `exact_single_solution` 不同）。

---

## 四、被弱化的测试

### TEST-WEAK-1：`test_retrieval_weak_route_diagnostic_task_set` 不再验证具体 route/tool

**文件**：`tests/test_smoke.py:4447-4502`

旧断言验证了每个 task_id 的 `top_doc_id`、`route`、`tool_name`。新断言只检查 `feature_route` 非空、`tool_name.startswith("tool.")`。**测试不再能捕获错误路由。**

---

### TEST-WEAK-2：`test_retrieval_theme_variant_diagnostic_task_set` 同上

**文件**：`tests/test_smoke.py:4483-4515`

相同的弱化模式。

---

### TEST-WEAK-3：`test_executor_diagnostic_task_set` 删除了 4 个断言

**文件**：`tests/test_smoke.py:4046-4076`

删除的断言：
- `route_source["matched"] is True`
- 3 个 markdown 表格行的格式验证

---

### TEST-WEAK-4：`test_state_ref_minimal_slimming_audit` 放宽 admissible 断言

**文件**：`tests/test_smoke.py:3710-3715`

从 `== 1.0` 放宽为 `0.0 <= x <= 1.0`。去 hint 后正确率确实可能下降，但不再被约束到任何具体的正确率底线。

---

## 五、代码质量

### CODE-1：`executor_runtime.py:1039-1044` — feature_bundle 从空 dict 构建

```python
_merge_feature_bundle_with_tool_candidates(feature_bundle={}, ...)
```

当 `feature_ref is None` 且 `channel_snapshot_ref is None` 但 `tool_candidate_ref is not None` 时，从空 dict 开始 merge。这个 fallback 路径只在 `protocol_full_rich_audit` 的极端场景下出现。

### CODE-2：`executor_runtime.py:1850-1851` — route_confidence 无范围校验

`_validate_executor_decision_packet()` 检查 `route_confidence` 是否为数值类型，但不检查是否为 0.0-1.0 范围内的概率值。

### CODE-3：`orchestrator.py:873 + 1238` — plan_source 被归一化两次

`compile_task_plan()` 在 line 873 归一化一次，`_plan_task()` 在 line 1238 又归一化一次。无害但冗余。

---

## 六、从赛题要求对照当前状态

### 已解决（确认不再算问题）

| 原 Audit 问题 | 解决状态 | 证据 |
|---|---|---|
| Query 泄漏答案关键词 | ✅ 已解决 | 5 个 family 全部重写 query，`test_contest_dual_mode_controlled_v3_queries_avoid_direct_route_leak_tokens` 锁住白名单 |
| Clean task 单 route | ✅ 已解决 | 所有 complexity bucket 的 `acceptable_routes >= 2`，有测试锁住 |
| Corpus 预标签 | ✅ 已解决 | route_hint→eval_route_label，`formal_structure_clean: true`，runtime 字段为空，测试锁住 |
| Retrieval preference_bonus | ✅ 已解决 | `formal_structure_clean_retrieval` 关闭 theme/group bonus，排除 preferred_doc_ids |
| 双重 build_feature_bundle | ✅ 已解决 | `_feature_bundle_from_executor_decision_packet()` 不再调 `build_feature_bundle()` |
| Summarizer token 膨胀 | ✅ 已解决 | 非 audit 路径用 compact JSON，不展开为长文本 |
| memory_policy 单 family | ✅ 已解决 | 扩为 checkout + auth 两组 |
| planner_support 缺 4-step | ✅ 已解决 | deploy-llm 和 auth-llm-002 标记为 4-step plan |
| handoff_bytes 抄写 | ✅ 已解决 | `_aggregate_task_groups` 按 (mode, task_group) 分组 |
| memory_hit_rate 命名 | ✅ 已解决 | 全链路改为 `assist_memory_hit_rate` |
| public_surface 混乱 | ✅ 已解决 | 收敛为 4 类 + 8 个 alias |

### 仍未解决

| 问题 | 状态 | 位置 |
|---|---|---|
| Planner 在 contest/memory_policy 包上被绕过 | 设计决定（不是 bug） | `plan_source_default: yaml` |
| 跨任务依赖的运行时消费 | 合同已建立（`required_prior_*`），但 runtime 不读取这些字段 | YAML 有声明，代码不消费 |
| `test_retrieval_weak_route` 不验证具体 route | 测试弱化 | `test_smoke.py:4447` |
| memory_policy 缺 `formal_structure_clean_retrieval` | 配置遗漏 | `memory_policy_controlled_v3_benchmark.yaml` |

### 新增 Bug（本轮引入）

| Bug | 严重度 | 位置 |
|---|---|---|
| BUG-1: plan_source 校验嵌套在错误 if 块 | P0 | `sample_tasks.py:897-909` |
| BUG-2: typed_state_full_rich_audit_v3 加载失败 | P0 | 缺 `public_surface`，`support_only` 无 auto-inference |
| BUG-3: _resolve_runtime_corpus_hints 不检查 formal_structure_clean_retrieval | P1 | `sample_agents.py:1881-1888`（当前无实际影响） |
| TEST-WEAK-1/2: 弱化 route correctness 断言 | P2 | `test_smoke.py` |
| CODE-2: route_confidence 无范围校验 | P3 | `executor_runtime.py:1850` |

---

## 七、全 12 个 Pack 加载状态

| # | Pack | 状态 |
|---|---|---|
| 1 | contest_dual_mode_controlled_v3 | ✅ OK (40 tasks) |
| 2 | memory_dual_mode_fairness_v3 | ✅ OK (40 tasks) |
| 3 | typed_state_mechanism_v3 | ✅ OK (8 tasks) |
| 4 | external_text_baseline_audit_v3 | ✅ OK (4 tasks) |
| 5 | text_definition_audit_v3 | ✅ OK (40 tasks) |
| 6 | typed_state_authenticity_v3 | ✅ OK (40 tasks) |
| 7 | **typed_state_full_rich_audit_v3** | **❌ FAIL** — `requires public_surface` |
| 8 | carrier_microbench_v3 | ✅ OK (40 tasks) |
| 9 | memory_reuse_v3 | ✅ OK (4 tasks) |
| 10 | memory_policy_controlled_v3 | ✅ OK (8 tasks) |
| 11 | planner_support_v3 | ✅ OK (11 tasks) |
| 12 | typed_state_consumer_sensitivity_v3 | ✅ OK (40 tasks) |

---

## 八、Contest 任务设计验证

| 验证项 | 状态 |
|---|---|
| 所有 task 的 `acceptable_routes >= 2` | ✅ 全部 40 个 task，所有 4 个 complexity bucket |
| 所有 task 的 `acceptable_tools >= 2` | ✅ 全部 |
| clean/simple 的 query 无 route 关键词泄漏 | ✅ 有白名单测试锁住 |
| reusable 的 `required_prior_case_ids` 非空 | ✅ 全部 5 个 family |
| reusable 的 `required_prior_rejections` 非空 | ✅ 全部 5 个 family |
| 5 个 family × 4 complexity × 2 mode = 40 个 task | ✅ |
| Corpus 每个 family 有 8 类文档（incident/metrics/logs/config_or_runbook/distractor/ambiguous/scope/reuse） | ✅ 有测试锁住 |
