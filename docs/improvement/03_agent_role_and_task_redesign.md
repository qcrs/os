# Agent 角色与任务重设计

**目标**：满足"3类任务"要求，展示角色真实分工，设计可以演示"越跑越快"的连续任务
**状态基准**：HEAD `6ece8a0`（2026-07-04）

---

## 问题一：incident_diagnosis_v2 任务族 — 已实现 ✅

### 实现状态

**corpus 已创建**，位于 `v2/benchmark/samples/incident_corpus/`（及相关目录）。

**实测数据（v2-update-validation-20260704_145038 / 13_incident_diagnosis_v2.json）**：

```
task_family:                incident_diagnosis_v2
family_case_count:          10
eligible_for_quality_headline:  True
eligible_for_replay_headline:   True
headline_scope:             replay_admissible

replay_admissibility_audit：
  exact_target_rounds:    [3,4,6,7,8,9,10]（7轮）
  validated_target_rounds: [2,5]（2轮）
  observed_exact_rounds:  [3,4,6,7,8,9,10]
  observed_validated_rounds: [2,3,4,5,6,7,8,9,10]
  missing_target_rounds:  []（全部命中）
  missing_validated_rounds: []

skipped_step_count:   16（从 full-experiment-20260704_111950 数据）
exact_replay:          7
validated_replay:      2
```

### 任务设计说明

三类任务现已完整：
1. `formal_financial_family`（8 cases）：financial report metric extraction
2. `continuous_csv_table` / `long_doc_table`：CSV 和长文档连续分析
3. `incident_diagnosis_v2`：服务诊断，日志语义检索 + CodeAct 探针 + 跨轮 replay

### 答辩展示要点

- Round 1：冷启动，全量日志检索
- Rounds 3,4,6,7,8,9,10：exact_replay（7轮），LLM 零调用
- Rounds 2,5：validated_replay，减少 LLM 调用
- eligible_for_replay_headline=True：满足赛题连续任务稳定性要求

---

## 问题二：Retriever 的定位 — 已澄清 ✅

### 当前状态

两种检索模式均已实现，在文档和 benchmark 报告中有明确说明：

**结构化路由检索（Structured Route Retrieval）**
- 适用：有 schema 约束的 corpus（financial report 等）
- 机制：route + tool_name → metric_name 精确匹配
- 证据：StateBus 8/8 vs external 6/8

**语义相似度检索（Semantic Similarity Retrieval）**
- 适用：非结构化文档（日志、长文档等）
- 机制：Qwen3-Embedding-0.6B → cosine similarity → top-k
- 证据：incident_diagnosis_v2 日志语义检索，exact_replay=7 轮

两种策略通过同一 StateRef 接口（DENSE_EVIDENCE + EMBEDDING）输出，Executor 无需感知检索方式差异。

---

## 问题三：10轮连续任务稳定展示 — 已满足 ✅

### 当前状态

以下连续任务 family 均完成10轮稳定运行（full-experiment-20260704_111950）：

| Family | 轮数 | validated_replay | exact_replay | eligible_for_replay_headline |
|---|---|---|---|---|
| csv_correlation_replay_v1 | 10 | 已包含在合计15中 | 已包含在合计10中 | True |
| long_doc_metric_replay_v1 | 10 | 已包含在合计15中 | 已包含在合计10中 | True |
| incident_diagnosis_v2 | 10 | 2 | 7 | True |

合计 continuous replay：validated_replay=15，exact_replay=10，missing_target_rounds=0。

---

## 问题四：cross_period_financial_v1 — 未实装，待做

### 问题描述

原设计的 cross_period_financial_v1（10轮，越跑越快的财务跨期分析）尚未实装。当前3类任务已满足赛题要求，但该 family 可进一步强化"记忆使得系统越跑越快"的展示效果。

### 设计目标

```
Round 1:  提取 ACME 2026Q1 revenue → cold_start，写入 memory
Round 2:  提取 ACME 2025Q4 revenue → validated_replay（复用 Route/Tool）
Round 3:  计算 Q1 vs Q4 delta → exact_replay（两值都在 memory）
Round 4:  提取 ACME 2025Q3 → validated_replay
Round 5:  计算三季度趋势 → exact_replay
Round 6:  提取 BETA 2026Q1 → validated_replay
Round 7:  ACME vs BETA 对比 → validated_replay
Round 8:  提取 BETA 2025Q4 → validated_replay
Round 9:  BETA 趋势 → exact_replay
Round 10: 完整对比报告 → exact_replay
```

### 实装路径

1. 创建 `v2/benchmark/samples/continuous_task_families/cross_period_financial/manifest.json`
2. 在 `v2/benchmark/live_runner.py` 的 `--suite statebus` 中注册
3. 在 `v2/benchmark/samples/financial_reports/` 补充 BETA 公司 2025Q3/Q4 数据

**验收命令**：

```bash
python -m v2.benchmark.live_runner \
  --suite statebus --benchmark-tier dev \
  --role-path-mode api --embedding-mode local \
  2>&1 | grep -E "cross_period|skipped_steps|exact_replay"
# 期望：Round 3/5/9/10 触发 exact_replay，tokens 整体递减
```

---

## 问题五：Executor 真实执行展示

### 当前状态

- formal financial：Executor 走 `codeact_data_tasks.py` deterministic 函数（8/8 成功）
- incident_diagnosis_v2：Executor 有 CodeAct 路径，skipped_step_count=16 证明 replay 在工作
- CodeAct LLM 生成路径：5/5 验证通过（v2-update-rerun 11_codeact_acceptance.json）

formal pipeline 稳定性优先，保持 deterministic 路径；答辩演示时可展示 LLM 生成路径的5/5验证结果。

### 答辩口径

> "formal pipeline 使用 deterministic CodeAct 保证评分稳定（8/8）；LLM CodeAct 生成路径在独立验证中5/5通过（generation_fallback_used=False），展示了完整的 LLM → AST check → bwrap sandbox 链路。codeact_execution_stage_ms 从 2455ms 降至 843ms（-65.7%），runner cache 已实现。"
