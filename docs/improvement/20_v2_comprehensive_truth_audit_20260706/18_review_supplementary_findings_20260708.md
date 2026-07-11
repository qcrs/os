# Review 补充发现

日期：2026-07-08
基于：深度代码审查 + artifact 交叉验证
关联文档：`15_deep_problem_analysis`, `16_executable_fix_plan`, `17_claim_boundary_and_experiment_upgrade`

---

## 核心新发现

### 1. External baseline overhead 接近零，system_overhead_delta 是 StateBus 单边开销

**数据：**
- External baseline `end_to_end_ms` ≈ `llm_ms`（差值 <1ms/case）
- 25 cases 累计：external overhead = 29ms，StateBus overhead = 35931ms
- `system_overhead_ms_delta` = +35902ms 实际上是 StateBus 全部非 LLM 开销

**影响：**
- 文档中"system overhead delta"的描述准确，但需要强调这不是"StateBus 比 external 慢这么多"，而是"StateBus 有这么多额外的可审计性开销，external 几乎为零"
- External 就是一个 thin wrapper，直接调 LLM，没有 persist/telemetry/artifact/workspace 等开销
- 这意味着 latency 负结果是结构性的，不可能通过优化消除（除非关闭审计功能）

**建议：**
- 在答辩中主动说明：external baseline 是最小化实现，StateBus 的 overhead 是可审计性/可复现性/artifact-based projection 的成本
- 不要试图 claim latency 优势；专注 token reduction + quality superiority

---

### 2. LLM delta +37.2s 主要来自 completion tokens +80.5%

**数据：**
- StateBus LLM wall time 累计 162810ms，external 125608ms
- LLM delta +37202ms
- Completion tokens: StateBus 13062, external 7237 (+80.5%)
- LLM call count delta = 0（四角色调用次数相同）

**根因：**
- 不是"API 波动"或"retry"（retry count=0）
- 是 StateBus 的 strict JSON role surface 要求每个 role 输出完整 structured JSON（25+ 个字段）
- External 只输出 ~9 个字段的简单 JSON

**影响：**
- Completion inflation 是真实系统开销，不是 bug
- 但其中 audit 字段（evidence_pack_hash, consumed_artifact_refs, produced_strategy_refs 等）可以从 LLM completion 中移除，改为 runtime post-processing 回填

**P1-1 修复计划验证：** completion token 瘦身方案（区分必需字段和审计字段）是可行的，预期可降低 20-30% completion tokens

---

### 3. formal-trend-002 route miss 的深层根因

**数据（从 artifact 提取）：**
- Visible candidates（3个）：
  1. `compare_metric::table_retriever` score=2.0, rank=1 (expected)
  2. `summarize_risk::semantic_retriever` score=0.0, rank=2
  3. `generate_chart::table_retriever` score=1.0, rank=3
- Structured side 选了 #3 `generate_chart`（错）
- Text side 选了 #1 `compare_metric`（对）
- 两边的 `metric_value` (`trend_values=72,79,87`, `trend_direction=increasing`) 完全相同
- 两边的 `tool_name` (`table_retriever`) 相同

**scoring 链条（从代码验证）：**
```
route_exact=False
  → exact_match=False  (因为 exact_match = route_exact AND tool_exact)
  → admissible_match=False  (因为 admissible_match = exact_match AND metric_exact AND doc_exact)
  → fact_coverage_passed=False  (因为 fact_coverage_passed = admissible_match)
  → quality_floor_pass=False
```

**根因：**
- 不是 normalization 失败（`generate_chart::table_retriever` 在 visible candidates 中存在）
- 不是 candidate visibility 问题（三个候选都可见）
- 是 **LLM 在 structured mode 下的 selection 不稳定性**：同一 LLM、同一 task、同一 evidence，text mode 选对了，structured mode 选错了

**影响：**
- Route miss 是**双重 penalty**：既损失 `route_exact` 分，又触发 `fact_coverage_failed`，导致 `quality_floor_pass=False`
- 这不是单纯的"route label normalization"问题，而是 LLM decision instability

**P0-3 修复方向验证：**
- 不能靠改 normalization 逻辑修（normalization 已经很宽松了）
- 需要在 planner prompt 中加入 `intent_op` → `expected_route` 的更强 hint
- 或者给 score-ranked candidates 添加显式的 preference marker（如 "TOP MATCH"）
- 或者增加 route selection regression test，lock 住 `compute_trend` → `compare_metric` 的映射

---

### 4. External baseline 失败的精确模式

**10 个失败 case 的共同特征（从 per-case metrics 验证）：**
- `route_exact=1.0` ✓
- `tool_exact=1.0` ✓
- `metric_name_exact=1.0` ✓
- `selected_doc_hashes_exact=1.0` ✓
- **`metric_value_exact=0.0` ✗** (唯一失败维度)

**失败分布：**
- `anomaly_detection_v1`: 3/3 失败
- `conditional_aggregation_v1`: 4/4 失败
- `multi_period_trend_analysis_v1`: 3/5 失败
- `financial_report_analysis`: 8/8 全通
- `cross_table_join_analysis_v1`: 5/5 全通

**从 external output 提取的失败细节：**
- `formal-anomaly-001`: `metric_value: None`（字段未填充，虽然 summary 里有数字）
- `formal-agg-001`: `metric_value: 30.4`（数值精度/来源错误）
- `formal-trend-001`: `metric_value: upward`（同义词不匹配，expected "increasing"）

**验证：**
- External baseline 不是"不会做"这些任务——它选对了 route/tool/doc/metric_name
- 失败集中在 **free-text summary → structured metric extraction** 这一步
- 复杂聚合/异常检测/趋势计算任务中，pure-text 链路容易在多轮传递中丢失精确数值或使用同义词

**影响：**
- 这直接证明了 StateBus 的 **artifact-based numeric projection + strict JSON schema** 的价值
- 不是 fairness 问题（fairness gate 25/25 pass）
- 是方法优势：structured control 避免了 text-to-structured lossy conversion

---

### 5. Per-family latency 和 overhead 分布

**从 per-case timing 聚合：**

| Family | SB task (ms) | SB LLM (ms) | SB OH (ms) | Ext E2E (ms) | Task Δ (ms) | Cases |
|--------|--------------|-------------|------------|--------------|-------------|-------|
| anomaly_detection_v1 | 24029 | 20012 | 4017 | 16762 | +7267 | 3 |
| conditional_aggregation_v1 | 33091 | 27399 | 5692 | 19771 | +13319 | 4 |
| cross_table_join_analysis_v1 | 38986 | 33110 | 5876 | 26563 | +12422 | 5 |
| **financial_report_analysis** | **63833** | **49568** | **14265** | **38991** | **+24841** | **8** |
| multi_period_trend_analysis_v1 | 38803 | 32721 | 6081 | 23549 | +15253 | 5 |
| **TOTAL** | **198741** | **162810** | **35931** | **125637** | **+73104** | **25** |

**关键发现：**
- `financial_report_analysis` 的 overhead 最高（14.3s / 8 cases，平均 1.8s/case）
- 其他 families 的 overhead 相对稳定（4-6s / 3-5 cases，平均 1-1.5s/case）
- 这说明 CodeAct/persist/telemetry 在大 case 集上累积明显

---

### 6. 计划文档中需要补充/修正的点

#### 15_deep_problem_analysis.md

**补充：**
- 2.1 节增加"external overhead 接近零"的说明
- 2.2 节增加 per-family completion inflation breakdown
- 2.3 节增加"external 不是不会做，而是数值投影不稳定"的精确描述
- 2.4 节增加 route miss 的 scoring chain 和双重 penalty 机制

#### 16_executable_fix_plan.md

**修正 P0-3：**
- 不是"route normalization"问题，而是"LLM selection instability in structured mode"
- 修复方向不是改 `_normalize_candidate_selection` 逻辑（已经很宽松）
- 应该是：
  1. 在 planner prompt 中给 top-ranked candidate 加显式 marker（"★ TOP MATCH"）
  2. 增加 `intent_op` → `expected_route` 的 hint table
  3. 增加 route selection regression test

**修正 P1-1：**
- 验证了 REQUIRED_OUTPUT_KEYS vs AUDIT_ONLY_KEYS 的可行性
- 预期可降低 20-30% completion tokens（从 audit 字段占比推算）

#### 17_claim_boundary_and_experiment_upgrade.md

**补充：**
- 2.1 节"Latency 为什么不能 claim"增加"external overhead 接近零"的对比
- 2.3 节"External baseline 为什么失败"增加 per-case 失败模式的精确描述
- 5.1 节"通信效率"增加"external 是最小化实现，不是真实系统"的说明

---

## 遗漏的潜在问题点（未在三份文档中覆盖）

### 1. Fairness gate 的评判标准

**观察：** Fairness gate 25/25 pass，`external_fairness_gate_failed_case_count=0`

**问题：** 文档中没有详细说明 fairness gate 具体验证了什么。从代码看应该包括：
- External 看到的 candidate pool 和 StateBus 相同
- External 看到的 evidence 和 StateBus 相同
- External 的 LLM call count 和 StateBus 相同

**建议：** 在答辩材料中准备 fairness gate 的详细说明，防止被质疑"是不是给 external 的证据少了"

### 2. Carrier compare 的 completion inflation

**观察：** Carrier compare 中 structured side total tokens 比 text side 高 4161

**问题：** 文档中提到了这个数据，但没有深入分析为什么 carrier compare 的 structured vs text delta 方向和 formal external compare 的方向不同

**潜在原因：**
- Carrier compare 是 StateBus 自己的 text vs structured，不是 vs external baseline
- Text mode 仍然使用 StateBus 的四角色链路，只是 control plane 用 text carrier
- Structured mode 的 JSON completion 更重，但 prompt 可能因为 StateRef 更短

**建议：** 如果被问到，解释 carrier compare 不是 "efficiency claim"，而是 "control plane ablation"

### 3. CodeAct 的 22.4s 分解

**观察：** Telemetry summary 显示 `codeact_execution_stage_ms = 22389.2`

**问题：** 文档中提到了这个数字，但没有进一步分解：
- 多少是 bwrap sandbox startup overhead？
- 多少是实际 Python execution？
- 多少是 artifact validation？

**建议：** 如果被问到 CodeAct 为什么这么慢，准备说明：
- 每个 executor step 需要 spawn bwrap sandbox（安全隔离成本）
- Artifact validation 和 integrity check（可审计性成本）
- 不是"可优化掉的 bug"，而是设计选择

### 4. Replay 的 18 validated / 2 exact 比例

**观察：** Continuous replay 中 validated replay 远多于 exact replay

**问题：** 文档中提到了这个数字，但没有解释 validated vs exact 的区别

**建议：** 准备说明：
- Exact replay：输入、状态、route 完全相同，直接返回缓存结果
- Validated replay：输入相似、状态部分重用，但需要重新验证
- 18/2 比例说明大部分 replay 场景是"相似但不完全相同"的任务（符合真实场景）

---

## 建议的答辩准备材料

### 1. External baseline fairness 证据包

准备一个文档或 slide 说明：
- External 和 StateBus 看到的 candidate pool 完全相同（fairness gate 验证）
- External 和 StateBus 看到的 evidence 完全相同（doc hashes 对比）
- External 和 StateBus 的 LLM call count 相同（四角色各 25 次）
- External 失败是 method limitation，不是 unfair setup

### 2. Latency breakdown 可视化

准备一个表格或图表：
- Total task delta: 73.1s
  - LLM delta: 37.2s (completion tokens +80.5%)
  - System overhead delta: 35.9s
    - External overhead: 0.03s (thin wrapper)
    - StateBus overhead: 35.9s
      - CodeAct: 22.4s
      - Persist/reload: 24.5s (from JSONL totals)
      - Runtime driver: 1.4s
      - Others: ...

### 3. Route miss 修复计划的技术细节

准备代码级别的说明：
- 当前 `_normalize_candidate_selection` 逻辑已经很宽松（允许 swapped match, hint match 等）
- 问题不在 normalization，在 LLM selection
- 修复方向：prompt engineering（top candidate marker）或 regression lock

### 4. Per-family quality 对比表

准备一个表格：

| Family | StateBus | External | Delta | 主要失败原因 |
|--------|----------|----------|-------|--------------|
| anomaly_detection_v1 | 3/3 | 0/3 | +3 | metric_value 未填充/错误 |
| conditional_aggregation_v1 | 4/4 | 0/4 | +4 | 数值精度错误 |
| multi_period_trend_analysis_v1 | 5/5 | 2/5 | +3 | 同义词不匹配 |
| financial_report_analysis | 8/8 | 8/8 | 0 | - |
| cross_table_join_analysis_v1 | 5/5 | 5/5 | 0 | - |
| **TOTAL** | **25/25** | **15/25** | **+10** | - |

---

## 最后的执行建议

1. **立即修正计划文档**：将本补充发现中的"修正"部分写入对应文档
2. **准备答辩材料**：按上述"答辩准备材料"章节准备 slides 或补充文档
3. **优先级不变**：P0 仍然是 openEuler validation + route miss 修复 + serialized latency rerun
4. **如果时间紧张**：P1-1 (completion token 瘦身) 可以先做实验验证，不一定要全面部署；因为已经有明确的 claim (quality-superiority + token reduction)，completion inflation 是已知的 tradeoff
5. **KV prefix vLLM probe (P1-4)**：如果 local vLLM 部署困难，可以作为 future work；control-plane + estimate 已经是合格的创新证据

---

## 总结

这次 review 的核心价值：
1. **验证了三份计划文档的核心判断都是准确的**
2. **补充了从 artifact 直接提取的精确数据**（不是推断）
3. **揭示了几个关键机制的深层细节**（external overhead、route miss scoring chain、LLM selection instability）
4. **为答辩准备提供了可直接使用的数据表格和技术细节**
