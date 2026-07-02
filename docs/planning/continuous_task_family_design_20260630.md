# Continuous Task Family Design

日期：2026-06-30
状态：`v2` benchmark task design draft
作用：把赛题要求的 10 轮连续任务落成可审计任务族设计，避免把孤立小题包装成 memory/replay 收益。

---

## 1. 上位约束

本设计只解决任务构造，不声称 runner 已完成。

依据：

1. `docs/reference/题目.md`
   - 至少 3 个 Agent
   - 纯文本协作与结构化协议协作对比
   - 非文本中间状态传递
   - 共享记忆存储、检索、复用
   - 至少 2 组关联性连续任务
   - 稳定执行不少于 10 轮连续任务
2. `docs/planning/statebus_v2_clean_room_rebuild_plan_20260625.md`
   - 任务必须换成长文档、真实数据、可复用代码模板的连续任务
   - L0-L3 分层归因：控制面、语义剪枝、记忆回放
   - 至少一个连续任务家族最终要能出现非零 replay `skipped_step_count`
   - 在 replay-admissible family 还未落地前，formal family 至少要把 history-backed `reuse_gain` / `history_step_reduction_count` 做实
3. `docs/planning/benchmark_quality_floor_contract.md`
   - 成本对比只在质量通过后成立
4. `docs/planning/task_compiler_contract.md`
   - formal benchmark 必须使用稳定 `CanonicalTaskSpec`
5. `docs/planning/semantic_provenance_and_hydration_contract.md`
   - hydrate 是局部回填，不是全文重建

---

## 2. 对“连续任务”的定义

这里的连续不是简单的“同一个目录下有 10 道题”。一个任务族必须同时满足：

1. `session continuity`
   - 同一 group 的轮次在同一个 benchmark session 中执行。
   - memory lineage 和 artifact lineage 可以跨轮查询。
2. `data continuity`
   - 多轮围绕同一数据源或相关数据源。
3. `artifact continuity`
   - 前轮产出的 schema profile、统计摘要、清洗表、特征列、路径表、证据索引等对象，可以被后轮直接消费。
4. `execution continuity`
   - 后轮至少一部分步骤可以通过 memory / artifact / replay 减少重复工作。
   - 不能把 `memory_hit_count > 0` 直接当成收益，必须观察 `artifact_reuse_count`、replay `skipped_step_count`，或 history-backed `history_step_reduction_count` / `history_reuse_gain`。

---

## 3. 三条任务线

### 3.1 `csv_table_profile`

定位：formal primary。

目标：

1. 证明 CodeAct 真执行。
2. 证明 CSV/table artifact 可复用。
3. 证明 strategy memory 和 execution artifact memory 的差别。

数据源：

1. `task/csv/estimated_numbers.csv`
2. `task/csv/baro_2015.csv`

为什么选它：

1. `baro_2015.csv` 有 8736 行，比当前 fixed-answer family 更适合拉开 evidence / artifact 成本。
2. 现有 `task/group2_tasks.json` 已有 13 轮和跨 CSV 复用边。
3. 可自动判定数值、缺失值、相关系数、异常值。

### 3.2 `long_doc_table`

定位：formal secondary。

目标：

1. 专门证明 semantic pruning。
2. 让 `semantic_state_transfer_count > 0` 成为硬指标。
3. 让 `raw_evidence_bytes_seen_by_llm` 的下降来自局部 hydrate，而不是 prompt wording。

数据源：

1. repo-local synthetic financial / operations long document
2. accompanying metric table

为什么用合成数据：

1. 可固定 gold answer。
2. 可控制长文档噪音、表格事实和证据 locator。
3. 不依赖网络或第三方版权材料。

### 3.3 `gridops_world`

定位：demo / secondary benchmark。

目标：

1. 直观展示 typed state、动作协议和策略记忆。
2. 证明 10 轮连续运行时，地图状态、路线片段和规则 memory 可以复用。
3. 作为演示，不承担 formal headline。

为什么不放 formal primary：

1. 游戏环境容易被认为 toy。
2. 它能证明系统机制，但不能替代表格/长文档真实任务。

---

## 4. L0-L3 归因设计

每个任务族都应支持同一套层级。

### L0: Text Collaboration

要求：

1. 纯文本 role handoff。
2. 不使用 typed semantic state。
3. 不使用 replay。
4. 可以使用同样工具能力，避免弱化 baseline。

主要回答：

1. text baseline 质量是否过底线。
2. 全量文本或文本化 evidence 的成本是多少。

### L1: Structured Control

要求：

1. structured handoff。
2. 不打开 semantic pruning。
3. 不打开 replay。

主要回答：

1. `control_bytes` 是否下降。
2. `role_handoff_bytes_total` 是否下降。

### L2: Semantic Pruning

要求：

1. 打开 semantic state。
2. 打开 local hydrate。
3. 不打开 replay。

主要回答：

1. `semantic_state_transfer_count > 0`
2. `raw_evidence_bytes_seen_by_llm` 是否下降。
3. `prompt_visible_total_bytes` 是否下降。

### L3: Memory / Replay

要求：

1. 打开 L2。
2. 打开 memory reuse。
3. 对 admissible steps 允许 validated / exact replay。

主要回答：

1. `memory_match_count > 0`
2. `artifact_reuse_count > 0`
3. replay-admissible family 才要求 `skipped_step_count > 0`
4. history-backed family 至少要求 `history_step_reduction_count > 0`
5. `reuse_gain` 与 `history_reuse_gain` 必须分开解释

---

## 5. Manifest 合同

新增样本位于：

```text
v2/benchmark/samples/continuous_task_families/
```

每个 family 使用一个 `manifest.json`，结构如下：

```json
{
  "schema_version": "statebus.continuous_task_family.v1",
  "family_id": "csv_table_profile_v1",
  "claim_tier": "formal_primary",
  "round_count": 10,
  "datasets": [],
  "quality_floor": {},
  "l0_l3_expectations": {},
  "rounds": []
}
```

每轮必须包含：

1. `round`
2. `task_id`
3. `request_text`
4. `canonical_task_spec`
5. `depends_on_rounds`
6. `reuse_contract`
7. `expected_facts`
8. `quality_checks`
9. `expected_metric_effects`

---

## 6. 任务族摘要

### `csv_table_profile_v1`

10 轮：

1. 建立 `estimated_numbers.csv` schema/profile。
2. 计算 cases/deaths 缺失率。
3. 计算 cases/deaths 相关性。
4. 检测 deaths outlier，复用 round1/2 profile。
5. 生成 cleaned disease table artifact。
6. 切到 `baro_2015.csv`，建立 schema/profile，复用 profile 代码模板。
7. 计算 monthly wind speed，复用 groupby strategy。
8. 检测 BARO outlier，复用 outlier strategy。
9. 生成 cleaned weather table artifact。
10. 综合 disease/weather 两条 lineage，输出 reuse report。

关键预期：

1. L2 降低 prompt-visible table evidence。
2. L3 复用 schema/profile、missingness、outlier、cleaned table artifact。

### `long_doc_table_v1`

10 轮：

1. ingest 长文档，建立 entity/metric index。
2. 查询 revenue。
3. 查询 gross margin。
4. 查询 operating expense。
5. 比较 Q1-Q3 revenue trend。
6. 提取 churn risk narrative。
7. 提取 supply-chain mitigation narrative。
8. 表格 + narrative 联合归因。
9. 复用前面指标和 narrative 生成 risk memo。
10. 生成 final report with cited evidence ids。

关键预期：

1. L2 必须出现 semantic state transfer。
2. `raw_evidence_bytes_seen_by_llm` 相比 L0 下降。
3. L3 复用 metric artifacts 和 evidence index。

### `gridops_world_v1`

10 轮：

1. 探索地图并保存 topology。
2. 找到 key 与 door rule。
3. 搬运 crate 到 zone A，复用 topology。
4. 绕过新增 blocked cell，更新 route memory。
5. 两 crate 调度。
6. energy budget 路径规划。
7. 记录 hazard zone。
8. 新目标复用 route segment。
9. 新地图复用策略模板。
10. 综合 key/door/crate/hazard/energy 任务。

关键预期：

1. typed world state 比 text map 更短。
2. route memory 能减少 planning work。
3. demo 中 action validity 和 path length 可自动判定。

---

## 7. Claim 边界

完成本设计后可以 claim：

1. 已有完整连续任务 family 设计。
2. 每个 family 明确了复用对象和指标。
3. 任务设计覆盖表格、长文档、状态游戏三种互补场景。

不能 claim：

1. 已完成 runner。
2. 已跑出 L0-L3 收益。
3. 已完成 formal continuous benchmark。
4. 已证明 exact replay 或 semantic pruning headline。
