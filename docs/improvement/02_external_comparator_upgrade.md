# P0-2：External Comparator 完整化

**优先级**：P0（赛题评分最重的"实验验证"和"通信效率"两项直接依赖此）
**目标**：从当前 dev fixed-answer（3 case）升级到 formal financial family 下的完整公平对比

---

## 一、当前问题根因

### 1.1 任务样本太少、太简单

当前 fixed-answer family 只有 3 个 case，任务模式高度同构：
- 选 route/tool（从有限候选中选一个）
- 提取一个数值（revenue_value）
- 生成一句话 summary

这种"确认型"任务即使两边都做对，也无法区分 StateBus 的系统价值与纯文本的差距。

### 1.2 fairness gate 前五项硬编码

`external_text_baseline.py:110` 的 `_fairness_gate()` 中：
```python
"no_statebus_imports": True,   # 硬编码，不是动态检测
"no_typed_state_used": True,   # 硬编码
"no_metadata_leakage": True,   # 硬编码
"no_lexical_fallback": True,   # 硬编码
"llm_only_decisions": True,    # 硬编码
```

这意味着 fairness gate 通过的"公平性"只靠代码结构保证，不是运行时验证，答辩时经不起追问。

### 1.3 LLM-as-a-Judge 层从未启用

`scoring.py` 中 `llm_judge_passed=None`，quality floor 的第三层实际上是 disabled 的。
这意味着当前 quality floor 只有两层（deterministic + fact coverage），不是完整的三层评分。

### 1.4 Wall time 更慢（+9263ms）但没有解释

external compare 的 `task_ms delta = +9263ms`，StateBus 更慢，但报告中没有细分 overhead 来源。
答辩时这是最容易被追问的点。

### 1.5 缺少 role-level token 对比

当前 aggregate token delta（-2002 tokens）是整体数字，无法回答"哪个角色节省了多少"。
赛题要求"统计 Agent 间消息次数、文本 token/字符开销"，需要 role-level 拆分。

---

## 二、解决方案

### 方案 A：扩充 formal financial family 任务样本

**目标**：从 3 个 case 扩充到 ≥8 个 case，覆盖更多场景

#### 任务设计原则（基于赛题要求）

| 原则 | 说明 |
|---|---|
| 四角色都有实质性工作 | Planner 需要做任务分解，Retriever 需要做 evidence selection（不是全文档），Executor 需要做真正的 route/tool 决策，Summarizer 需要做真正的综合 |
| 不能"单 prompt 吃完" | 任务必须有 role-local uncertainty，强模型直接看全局上下文也不能直接答出正确答案 |
| evidence 必须需要 selection | 文档中有多个竞争性 evidence，Retriever 需要从中选出真正相关的 |
| route/tool 决策有难度 | 候选集中存在"看起来合理但错误"的干扰项 |

#### 新增任务类型

**类型 1：跨季度对比任务（2个case）**
```
任务：分析 ACME 公司 2026Q1 vs 2025Q4 的营收变化，判断是增长还是下降，并给出变化幅度
难点：需要从两个季度的文档中各提取一个数值，然后计算差值
Route：multi_period_comparison
Tool：period_delta_calculator
期望事实：{ "direction": "growth", "delta_pct": "12.3%", "q1_revenue": "...", "q4_revenue": "..." }
```

**类型 2：多指标综合分析任务（2个case）**
```
任务：分析 ACME 公司 2026Q1 的毛利率健康状况（需要同时看营收和成本）
难点：需要从文档中提取两个不同指标，然后计算比率
Route：margin_health_analysis
Tool：ratio_calculator
期望事实：{ "gross_margin_pct": "...", "revenue": "...", "cost": "...", "assessment": "healthy|warning" }
```

**类型 3：异常检测任务（2个case）**
```
任务：判断 ACME 公司某季度的某指标是否异常（与历史均值对比）
难点：需要理解"历史均值"的概念，Planner 需要分解为"提取当前值 + 提取历史值 + 比较"
Route：anomaly_detection
Tool：threshold_comparator
期望事实：{ "is_anomaly": true/false, "current_value": "...", "threshold": "...", "severity": "low|medium|high" }
```

**类型 4：证据支持度评估任务（1个case）**
```
任务：评估某财报中关于"战略转型"的描述是否有具体数据支持
难点：需要 Retriever 不只是找数据，而是判断证据充分性
Route：evidence_sufficiency_check
Tool：support_coverage_analyzer
期望事实：{ "claim_supported": true/false, "supporting_facts_count": N, "evidence_quality": "strong|weak|absent" }
```

#### 新 corpus 文档需求

当前 `OfflineFinancialReportCorpus` 只有单季度单文档。需要扩充：
- 至少 2 个 ticker（现有 ACME + 新增 BETA）
- 至少 2 个季度（2026Q1 + 2025Q4）
- 每个文档包含：text_fragments（叙述性文字）+ table_rows（数值表格）

**文件路径**：`v2/retrieval/corpus.py` 中的 `OfflineFinancialReportCorpus` + `v2/benchmark/samples/formal_financial_family/`

---

### 方案 B：fairness gate 动态化

#### 改动范围

`v2/benchmark/external_text_baseline.py` 的 `_fairness_gate()` 函数，将前五项从硬编码改为运行时检测：

**no_statebus_imports（检测方法）**：

在 `run_external_text_case()` 中，检查函数本身的 import（通过 `inspect.getfile()` + `importlib` 路径检查），确认没有从 StateBus typed state 包 import：

```python
STATEBUS_TYPED_MODULES = {
    "protocol", "statepool", "v2.runtime.compiler",
    "v2.retrieval.pipeline", "runtime.orchestrator"
}

def _check_no_statebus_imports() -> bool:
    """检查当前 external baseline 执行路径没有 import StateBus typed 模块"""
    import sys
    loaded_modules = set(sys.modules.keys())
    violations = [m for m in loaded_modules if any(
        m == blocked or m.startswith(blocked + ".")
        for blocked in STATEBUS_TYPED_MODULES
    )]
    return len(violations) == 0
```

**no_typed_state_used（检测方法）**：

在 `_contains_forbidden_terms()` 中已有字符串检测，但只检测了 prompt/output surface。
改为同时检测 `combined_surface`（已有）+ `execution_artifact_text`（已有）+ 所有 `role_payloads`。

**no_metadata_leakage（检测方法）**：

检查每个 role 的 payload 中是否出现了 `CanonicalTaskSpec.primary_expected_route`、`expected_tool_name`、`expected_facts` 等 oracle 字段：

```python
ORACLE_FIELD_NAMES = {
    "primary_expected_route", "expected_tool_name",
    "expected_facts", "expected_route",
    "oracle_answer", "correctness_hint"
}

def _check_no_oracle_leakage(payloads: list[dict]) -> bool:
    serialized = " ".join(json.dumps(p) for p in payloads)
    return not any(field in serialized for field in ORACLE_FIELD_NAMES)
```

注意：`expected_route` 和 `expected_tool_name` 是 `FixedAnswerSample` 的字段，必须确认它们不出现在任何传给 LLM 的 prompt 文本中。

**no_lexical_fallback（检测方法）**：

检查代码路径中没有调用 `select_route_profiles()` 或其他 StateBus 内部路由决策函数来"偷偷纠正" LLM 的选择。
当前代码已经走的是 `_normalize_visible_candidate_payload()` 路径，但这个函数本身做的是归一化（合法），不是偷偷修正。
将此项改为：验证最终 route/tool 确实来自 LLM 输出（非空），而不是从某个默认值填充。

**llm_only_decisions（检测方法）**：

验证 4 个角色都产生了非空的 LLM 输出，且没有任何一个 role 的 payload 被"静默覆盖"：

```python
def _check_llm_only_decisions(
    planner_raw: dict, retriever_raw: dict,
    executor_raw: dict, summarizer_raw: dict
) -> bool:
    return all(
        isinstance(p, dict) and len(p) > 0
        for p in [planner_raw, retriever_raw, executor_raw, summarizer_raw]
    )
```

---

### 方案 C：role-level token 对比补全

`external_text_baseline.py` 已经记录了 `role_usage`（4 个角色各自的 prompt/completion tokens），但 comparator 的 delta 计算只用了 aggregate 数字。

需要在 compare diagnostics 输出中加入 role-level delta 表格：

```
Role-level token delta (StateBus vs External):
┌───────────────┬──────────────┬──────────────┬──────────────┐
│ Role          │ prompt tokens│ completion   │ total tokens │
│               │ delta        │ delta        │ delta        │
├───────────────┼──────────────┼──────────────┼──────────────┤
│ planner       │ -XXX         │ +/-XXX       │ -XXX         │
│ retriever     │ -XXX         │ +/-XXX       │ -XXX         │
│ executor      │ -XXX         │ +/-XXX       │ -XXX         │
│ summarizer    │ -XXX         │ +/-XXX       │ -XXX         │
│ TOTAL         │ -2002        │ ...          │ ...          │
└───────────────┴──────────────┴──────────────┴──────────────┘
```

这个数据可以直接回答"StateBus 在哪个角色上节省最多 token"。

---

### 方案 D：wall time overhead 细分

在 external compare 的报告中加入 overhead 细分字段：

```json
{
  "task_ms_delta": 9263,
  "task_ms_delta_breakdown": {
    "statebus_audit_bundle_write_ms": "估算值（从 persistence_breakdown 获取）",
    "statebus_semantic_state_write_ms": "估算值",
    "statebus_memory_commit_ms": "估算值",
    "external_baseline_overhead_ms": 0,
    "net_llm_ms_delta": "LLM调用时间差，去除 overhead 后的纯 LLM 时间对比"
  }
}
```

说明：`net_llm_ms_delta` = StateBus 四角色 LLM 时间之和 - External 四角色 LLM 时间之和，这个数字才是"纯 LLM 调用"的公平对比，可能是正数也可能是负数。

---

## 三、完整对比实验的最终形态

### 对比维度

改进后的 external comparator 应该能回答以下 5 个问题：

| 问题 | 当前状态 | 改进后 |
|---|---|---|
| LLM token 开销是否更低 | ✅ aggregate（-2002 tokens） | ✅ role-level 细分 |
| 端到端耗时是否更低 | ❌（更慢 +9263ms） | ✅ 有 overhead 细分，net LLM ms 对比 |
| 质量是否不下降 | ✅ 3/3 dev case | ✅ ≥8 formal case |
| 非文本状态是否真的节省 prompt | ✅ flagship ablation 有（13834 bytes） | ✅ 与 external compare 联动 |
| 公平性是否可验证 | ❌ 5项硬编码 | ✅ 动态检测 |

### 升级后的 claim 边界

| claim | 升级前 | 升级后 |
|---|---|---|
| 通信 token 节省 | dev_fixed_answer_only | formal_financial_family，role-level |
| 质量不下降 | 3 case | ≥8 case |
| 公平性 | 代码结构保证 | 运行时动态验证 |
| formal superiority | ❌ 不允许 | 视 ≥8 case 结果而定 |

---

## 四、执行顺序（改代码阶段）

1. 扩充 `OfflineFinancialReportCorpus`（添加新 ticker 和季度）
2. 新建 formal_financial_family 任务样本（8+ cases）
3. 修改 `_fairness_gate()` 的5项动态检测
4. 在 compare 报告中加入 role-level token delta 和 overhead breakdown
5. 实现 LLM-as-a-Judge（可以用 deterministic judge：检查关键数值是否出现，不需要真正的 LLM judge）
6. 重跑 compare suite（`--benchmark-tier formal`）

---

## 五、容器测试命令

```bash
export STATEBUS_CONTAINER_VALIDATION_DIR=/statebus/runs/container-validation-formal-compare-$(date +%Y%m%d_%H%M%S)

docker exec \
  -e STATEBUS_CONTAINER_VALIDATION_DIR="$STATEBUS_CONTAINER_VALIDATION_DIR" \
  statebus-dev-qcrs bash -lc '
  source /usr/local/bin/activate_statebus_container.sh
  cd /workspace/statebus/project
  mkdir -p "$STATEBUS_CONTAINER_VALIDATION_DIR"

  # 1. 先跑 formal suite 确认 StateBus 在 formal family 上的基线
  python3 -m v2.benchmark.live_runner \
    --suite formal \
    --benchmark-tier formal \
    --role-path-mode api \
    --embedding-mode local \
    2>&1 | tee "$STATEBUS_CONTAINER_VALIDATION_DIR/formal-suite.log"

  # 2. 再跑 external compare（需要新 formal family 任务样本就绪）
  python3 -m v2.benchmark.live_runner \
    --suite compare \
    --benchmark-tier formal \
    --role-path-mode api \
    --embedding-mode local \
    2>&1 | tee "$STATEBUS_CONTAINER_VALIDATION_DIR/formal-compare.log"

  # 3. 跑 compare diagnostics
  python3 scripts/v2_diagnostics/compare_diagnostics.py \
    --statebus-report /statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-formal-suite.json \
    --output-root "$STATEBUS_CONTAINER_VALIDATION_DIR/diagnostics" \
    2>&1 | tee "$STATEBUS_CONTAINER_VALIDATION_DIR/compare-diag.log"

  echo "$STATEBUS_CONTAINER_VALIDATION_DIR"
'
```

---

## 六、验收标准

| 指标 | 最低标准 | 目标 |
|---|---|---|
| formal family case 数量 | ≥5 | ≥8 |
| quality_floor_pass_count | ≥4/5 | ≥7/8 |
| fairness gate | 全部动态检测通过 | 同左 |
| token delta | 负值（StateBus 更省） | 同左，且有 role-level 细分 |
| formal_superiority_claim_allowed | 可能 true（视结果） | 不强求，诚实标定 |
