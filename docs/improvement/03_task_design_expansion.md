# P1-1：任务设计补充与扩展

**优先级**：P1
**目标**：让任务设计更贴合赛题"连续任务、共享记忆复用、非文本状态传递"的评分重点

---

## 一、当前任务问题分析

### 1.1 fixed_answer_family —— 太小太固定

| 问题 | 影响 |
|---|---|
| 只有 3 个 case | 统计无显著性，对比说服力弱 |
| 任务高度同构（全是"选 route/tool + 提取一个数值"） | 无法展示系统应对多样任务的能力 |
| Evidence corpus 只有单一文档 | Retriever 的 evidence selection 没有真正意义（无候选竞争） |
| 任务可以被单一强 prompt 直接解决 | 四角色分工的价值被淡化 |

### 1.2 formal_financial_family —— 需要扩充多样性

当前 formal financial family 的任务模式过于单一，都是"从财报中提取某指标的值"，与 fixed_answer_family 的区别不够明显。

### 1.3 continuous_task_families —— 相对最好，但缺少"记忆失效"和"冲突修复"场景

当前已有：
- `csv_correlation_replay_v1`：统计相关性分析，跨轮 replay
- `long_doc_metric_replay_v1`：长文档指标提取，跨轮 replay

**缺少的场景**：
- 记忆污染/失效场景（旧记忆在新任务中应被拒绝）
- 跨轮财报对比（需要 Planner 做真正的分解）
- CodeAct artifact 作为下一轮输入（体现数据面 replay）

---

## 二、新任务设计方案

### 2.1 扩充 formal_financial_family（优先级最高）

见 `02_external_comparator_upgrade.md` 第二节方案 A，总计需要新增 5 个 case（从 3→8）。

**新增 case 的 JSON 格式参考**：

```json
{
  "task_id": "formal-fin-004",
  "task_family": "formal_financial_analysis",
  "request_text": "Compare ACME's revenue between 2026Q1 and 2025Q4. Is the trend improving?",
  "canonical_task_spec": {
    "task_family": "formal_financial_analysis",
    "intent_op": "multi_period_comparison",
    "target_entities": ["ACME"],
    "time_scope": "2026Q1_vs_2025Q4",
    "required_outputs": ["delta_direction", "delta_pct", "q1_value", "q4_value"],
    "required_tools": ["period_delta_calculator"],
    "arguments": {"ticker": "ACME", "metric": "revenue", "periods": ["2026Q1", "2025Q4"]}
  },
  "expected_route": "multi_period_comparison",
  "expected_tool_name": "period_delta_calculator",
  "expected_facts": {
    "delta_direction": "growth",
    "q1_revenue": "2.4B",
    "q4_revenue": "2.1B",
    "delta_pct": "14.3%"
  },
  "summary_hint": "Compare revenues across two periods and calculate the growth rate",
  "scenario_tags": ["cross_period", "trend_analysis", "multi_value_extraction"]
}
```

---

### 2.2 新增 continuous family：cross_period_financial_v1

**目的**：体现"连续任务 + 跨轮财报记忆复用"，直接对应赛题"至少 2 组具有关联性的连续任务"

**任务链设计（5轮）**：

```
Round 1：提取 ACME 2026Q1 营收
  → Planner 分解：定位文档 → 提取数值 → 确认单位
  → 结果写入 memory（key: ACME_2026Q1_revenue）

Round 2：提取 ACME 2025Q4 营收
  → memory hit：相同 ticker，相同指标类型，可复用 Route/Tool
  → validated_replay：复用 Route（period_extract） + Tool（value_extractor）
  → 不需要重新 plan Route/Tool 选择

Round 3：计算 Q1 vs Q4 增长率
  → memory hit：2个数值都在 memory 中
  → exact_replay 场景：如果两个数值已确认，直接用缓存结果
  → 减少 Retriever 调用（数值已在 memory，不需要重新检索文档）

Round 4：同样的分析但换 ACME 2025Q3
  → memory hit：Route/Tool 复用（validated_replay）
  → Retriever 需要检索新文档（不同季度）

Round 5：对比 3 个季度（Q1/Q4/Q3）生成趋势报告
  → 3个数值全在 memory 中
  → Summarizer 直接消费 memory refs，不需要重新执行 Retriever+Executor
  → exact_replay 路径：summarization template 可复用
```

**manifest.json 结构**：

```json
{
  "family_id": "cross_period_financial_v1",
  "description": "Cross-period financial analysis with memory-backed replay",
  "corpus_type": "offline_financial_multi_period",
  "tickers": ["ACME"],
  "periods": ["2026Q1", "2025Q4", "2025Q3"],
  "rounds": [
    {
      "round_number": 1,
      "depends_on_rounds": [],
      "minimum_reuse_class": "cold_start",
      "expected_metric_effects": {"L2_transfer_expected": true}
    },
    {
      "round_number": 2,
      "depends_on_rounds": [1],
      "minimum_reuse_class": "validated_replay",
      "expected_metric_effects": {"skipped_step_expected": true, "L3_reuse_expected": true}
    },
    {
      "round_number": 3,
      "depends_on_rounds": [1, 2],
      "minimum_reuse_class": "exact_replay",
      "expected_metric_effects": {"llm_call_reduction_expected": true}
    }
  ]
}
```

---

### 2.3 新增 continuous family：memory_robustness_v1

**目的**：验证记忆系统的鲁棒性——旧的、已过时的记忆不应被错误复用

**任务链设计（4轮）**：

```
Round 1：提取 ACME 2024Q1 营收（故意是旧数据）
  → 写入 memory（source: round1, timestamp: 旧）

Round 2：ACME 发布了更新的 2024Q1 修订数据
  → 新任务提示"数据已修订"
  → 正确行为：不应 exact_replay Round 1 的结果
  → 预期：系统识别出 "data revision" 信号，降级到 validated_replay 或 cold_start

Round 3：提取 ACME 2026Q1 营收（完全新任务）
  → 与 Round 1 是同一指标类型，memory 存在 Route/Tool hint
  → 正确行为：可以复用 Route/Tool（validated_replay），但不复用 2024Q1 的数值
  → 预期：skipped_step_count 对 Route/Tool 选择步骤有贡献，但 Retriever 仍要检索 2026Q1 文档

Round 4：验证 Round 1 的记忆是否已被标记为过时
  → audit：`MemoryRef` 的 status 是否为 INVALIDATED 或 superseded
  → 预期：replay negative audit 通过（不会错误 exact_replay 已过时数据）
```

**这个任务族直接对应 `replay_admissibility_contract.md` 中的"失效规则"**，是对当前 7-case replay negative audit 的直接扩充。

---

### 2.4 升级 incident_diagnosis family（对应 openEuler 服务诊断场景）

当前任务以财报分析为主，但 `implementation_plan.md` 中的"openEuler 服务启动慢诊断"场景对赛题中"非文本状态传递"更有演示价值（日志是典型的非文本状态）。

**新增 incident_continuous_v1 任务链（3轮）**：

```
Round 1：诊断 inference-gateway.service 启动慢
  → Retriever 检索日志片段（DENSE_EVIDENCE StateRef）
  → Executor 运行诊断探针脚本（TOOL_ARTIFACT StateRef）
  → 结果写入 memory（策略：high_io_wait_on_slow_storage）

Round 2：诊断 service-b.service 启动慢
  → memory hit：类似症状，相同策略
  → validated_replay：复用诊断策略，只需重新收集 service-b 的日志
  → 预期：Planner 步骤减少（不需要重新推断策略）

Round 3：验证修复效果（同一 service，不同时间点）
  → memory hit：same route
  → 如果旧结果仍有效 → exact_replay
  → 如果日志已变化 → validated_replay with new evidence
```

**注意**：这个场景用的是仓库内的样本日志文件（`tasks/` 目录下），不依赖真实系统日志。

---

## 三、corpus 扩充方案

### 3.1 OfflineFinancialReportCorpus 扩充

需要新增以下文档到 `v2/retrieval/corpus.py` 或对应的 sample data 目录：

| ticker | quarter | 主要指标 | 包含干扰项 |
|---|---|---|---|
| ACME | 2026Q1 | 已有 | 是 |
| ACME | 2025Q4 | 需新增 | 是 |
| ACME | 2025Q3 | 需新增 | 是 |
| BETA | 2026Q1 | 需新增 | 是 |

**每个文档的最小结构**：

```python
FinancialReportDocument(
    ticker="ACME",
    quarter="2025Q4",
    title="ACME Corp Q4 2025 Earnings Report",
    source_doc_hash="sha256_of_content",
    text_fragments=[
        TextFragment(text="Revenue for Q4 2025 was..."),
        TextFragment(text="Operating costs increased by..."),  # 干扰项
        TextFragment(text="Strategic investments in cloud..."),  # 干扰项
    ],
    table_rows=[
        TableRow(metric_name="revenue", value="2.1B", period="2025Q4"),
        TableRow(metric_name="operating_cost", value="1.4B", period="2025Q4"),
        TableRow(metric_name="net_income", value="0.7B", period="2025Q4"),
    ]
)
```

**干扰项设计原则**：每个文档至少包含 2 个与任务指标无关的数值（让 Retriever 的 evidence selection 有真正意义）。

### 3.2 incident log corpus 扩充

在 `tasks/` 或 `v2/benchmark/samples/` 下添加：

```
v2/benchmark/samples/incident_corpus/
  inference-gateway/
    boot_log.txt           # 启动日志样本
    systemd_journal.txt    # journal 日志样本
    probe_output.json      # 诊断探针输出样本
  service-b/
    boot_log.txt
    ...
```

---

## 四、任务质量检查清单

在实现新任务时，每个 case 必须通过以下检查：

- [ ] 四角色都有实质性工作（不能有角色是"空过"）
- [ ] Evidence 集合中有 ≥2 个竞争性文档片段（Retriever 需要真正选择）
- [ ] Route/Tool 候选集中有 ≥1 个干扰项（Executor 需要真正判断）
- [ ] 单个强 LLM 无法直接从 request_text 得出正确答案（必须依赖 evidence）
- [ ] Expected facts 包含 ≥2 个可以独立验证的字段
- [ ] 有 scenario_tags 标注任务类型

---

## 五、完成后新的任务覆盖矩阵

| family | case 数 | 主要验证点 | replay class |
|---|---|---|---|
| fixed_answer_family | 8 | external comparator 对比 | cold_start |
| formal_financial_family | 8 | formal superiority 对比 | cold_start + validated |
| cross_period_financial_v1 | 5 轮 | 跨轮财报记忆复用 | cold→validated→exact |
| memory_robustness_v1 | 4 轮 | 记忆失效/拒绝复用 | replay negative |
| incident_continuous_v1 | 3 轮 | 非文本日志状态传递 + 策略复用 | cold→validated→exact |
| csv_correlation_replay_v1 | 已有 | CSV 相关性跨轮 replay | validated |
| long_doc_metric_replay_v1 | 已有 | 长文档指标跨轮 replay | exact + validated |
