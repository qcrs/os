# Telemetry Event Contract

日期：2026-06-26  
状态：`v2` 子合同草案  
作用：定义 `StateBus v2` 的实时事件、聚合指标、落盘格式与 Dashboard 数据来源，避免前后端和 benchmark 各自维护一套口径。

---

## 1. 目标

这份合同要解决：

1. `TelemetryEvent` 的正式字段
2. 实时事件与聚合指标如何分层
3. Dashboard 展示与 benchmark 落盘如何共用同一数据源
4. Waterfall Chart 与关键指标从哪里算
5. 哪些字段是 runtime 事实，哪些字段只是 UI 衍生

---

## 2. 基本原则

### 2.1 前后端不维护两套事件模型

Dashboard 看到的事件，应尽量是 runtime telemetry 落盘记录的无损子集。

不推荐：

1. 后端写一套 sqlite/jsonl schema
2. WebSocket 再临时拼一套前端专用结构

更合理的是：

1. runtime 先生成正式 `TelemetryEvent`
2. 同一对象既可落盘，也可序列化发给 WebSocket
3. 正式控制面事件名称应与 typed Protobuf control plane 的语义事件保持一一对应

### 2.2 区分事件与指标

事件是：

1. 某个时间点发生了什么

指标是：

1. 基于事件聚合出来的统计值

不要把：

1. `REQ_EXEC`
2. `ARTIFACT_COMMITTED`
3. `REPLAY_DECIDED`

这类事件和：

1. `control_bytes`
2. `raw_evidence_bytes_seen_by_llm`
3. `reuse_gain`

这类聚合值混成同一种对象。

### 2.3 benchmark 报告只认正式聚合，不认 UI 即席推导

所有正式对比表、瀑布图、主报告 headline，必须来自正式聚合逻辑，而不是前端页面临时求和。

---

## 3. 事件分层

建议分成 3 层：

### 3.1 Runtime Event

描述 step、状态机、资源与 replay 决策。

例如：

1. `STEP_DISPATCHED`
2. `STEP_ACKED`
3. `STEP_RUNNING`
4. `STEP_COMPLETED`
5. `STEP_FAILED`
6. `STEP_TRAPPED`
7. `STEP_CANCELLED`
8. `REPLAY_DECIDED`
9. `GC_ISSUED`

### 3.2 Data Plane Event

描述 state/artifact/evidence 的生产、传递、裁剪与恢复。

例如：

1. `STATE_PUBLISHED`
2. `STATE_HYDRATED`
3. `EVIDENCE_PACK_BUILT`
4. `ARTIFACT_MATERIALIZED`
5. `ARTIFACT_COMMITTED`

### 3.3 Metric Snapshot Event

描述某一时刻的关键计数快照。

例如：

1. `METRIC_SNAPSHOT`
2. `TASK_SUMMARY_METRICS`

---

## 4. 建议的正式对象

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class TelemetryEvent:
    event_id: str
    trace_id: str
    task_id: str
    step_id: str = ""
    attempt_id: str = ""
    span_id: str = ""
    parent_span_id: str = ""
    event_type: str = ""
    event_ts_ns: int = 0
    role: str = ""
    channel: str = ""
    severity: str = "info"
    payload: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float | int] = field(default_factory=dict)
    schema_version: str = "statebus.telemetry_event.v1"
```

字段纪律：

1. `payload`
   - 放事件事实
2. `metrics`
   - 放当前事件直接携带的数值
3. UI 样式字段不进入正式对象

---

## 5. 必填公共字段

所有事件建议至少包含：

1. `event_id`
2. `trace_id`
3. `task_id`
4. `event_type`
5. `event_ts_ns`
6. `schema_version`

涉及 step 的事件还应包含：

1. `step_id`
2. `attempt_id`
3. `role`

涉及 carrier/data plane 的事件还应包含：

1. `channel`
2. `payload.ref_id` 或等价引用

---

## 6. 推荐事件类型

### 6.1 Runtime Event Types

1. `STEP_DISPATCHED`
2. `STEP_ACKED`
3. `STEP_RUNNING`
4. `STEP_COMPLETED`
5. `STEP_FAILED`
6. `STEP_TRAPPED`
7. `STEP_CANCELLED`
8. `REPLAY_DECIDED`
9. `MEMORY_COMMIT_VERIFIED`
10. `GC_ISSUED`

### 6.2 Data Plane Event Types

1. `STATE_PUBLISHED`
2. `STATE_HYDRATED`
3. `EVIDENCE_PACK_BUILT`
4. `ARTIFACT_MATERIALIZED`
5. `ARTIFACT_PUBLISHED`
6. `ARTIFACT_RESTORED`

### 6.3 Metric Event Types

1. `METRIC_SNAPSHOT`
2. `TASK_SUMMARY_METRICS`

---

## 7. 推荐 payload / metrics 字段

### 7.1 `STEP_DISPATCHED`

`payload`

1. `target_role`
2. `runtime_reuse_contract`
3. `state_ref_count`
4. `artifact_ref_count`

`metrics`

1. `timeout_ms`

### 7.2 `EVIDENCE_PACK_BUILT`

`payload`

1. `pack_id`
2. `pack_hash`
3. `locator_count`
4. `hard_fact_count`
5. `semantic_context_count`

`metrics`

1. `semantic_context_bytes`
2. `rendered_evidence_bytes`

### 7.3 `STATE_HYDRATED`

`payload`

1. `manifest_id`
2. `evidence_pack_id`
3. `locator_count`

`metrics`

1. `raw_evidence_bytes_seen_by_llm`

### 7.4 `REPLAY_DECIDED`

`payload`

1. `replay_class`
2. `decision_source`
3. `canonical_task_spec_hash`
4. `runtime_compatibility_signature`

`metrics`

1. `skipped_step_count`
2. `reuse_gain`

### 7.5 `TASK_SUMMARY_METRICS`

`metrics`

1. `control_bytes`
2. `control_message_count`
3. `semantic_state_bytes`
4. `semantic_state_transfer_count`
5. `artifact_bytes`
6. `artifact_reuse_count`
7. `raw_evidence_bytes_seen_by_llm`
8. `llm_prompt_tokens`
9. `llm_completion_tokens`
10. `task_ms`
11. `memory_hit_rate`
12. `skipped_step_count`
13. `reuse_gain`

---

## 8. 落盘合同

推荐双落盘：

1. `jsonl`
   - 面向调试、审计、回放
2. `sqlite`
   - 面向查询、聚合、Dashboard API

### 8.1 `jsonl`

每行一个 `TelemetryEvent` 的 canonical JSON。

### 8.2 `sqlite`

建议至少两张表：

1. `telemetry_events`
2. `task_metric_rollups`

`telemetry_events`

核心字段：

1. `event_id`
2. `trace_id`
3. `task_id`
4. `step_id`
5. `attempt_id`
6. `event_type`
7. `event_ts_ns`
8. `role`
9. `channel`
10. `payload_json`
11. `metrics_json`

`task_metric_rollups`

核心字段：

1. `task_id`
2. `trace_id`
3. `mode`
4. `replay_class_distribution_json`
5. `summary_metrics_json`

---

## 9. Dashboard 数据来源合同

Dashboard 的核心看板建议直接来源于聚合指标，不靠前端临时计算：

1. `Raw Evidence seen by LLM`
   - 来自 `TASK_SUMMARY_METRICS.raw_evidence_bytes_seen_by_llm`
2. `Token Saved`
   - 来自 compare runner 对 `llm_prompt_tokens + llm_completion_tokens` 的正式差值
3. `Task Latency`
   - 来自 `task_ms`
4. `Replay Class`
   - 来自 `REPLAY_DECIDED`

正式 benchmark 的成本对比还必须同时满足 quality floor。  
更完整定义见：

1. [benchmark_quality_floor_contract.md](/home/qcrs/statebus/project/docs/planning/benchmark_quality_floor_contract.md)

---

## 10. Waterfall Chart 合同

瀑布图不直接从任意事件累加，而应来自 compare runner 的正式分层汇总：

1. `L0 baseline total cost`
2. `control_plane_savings`
3. `semantic_pruning_savings`
4. `replay_savings`
5. `final_total_cost`

建议统一由 `eval/comparators.py` 或等价聚合模块生成，再喂给 Dashboard。

---

## 11. 与当前仓库对象的关系

当前文档已经确定了很多要展示的指标，但还没有正式的统一事件对象。

这份合同的直接作用是把：

1. runtime state machine
2. semantic provenance
3. replay admissibility
4. execution artifact
5. benchmark dashboard

几条线绑到一份正式 telemetry schema 上。

---

## 12. MVP 实现建议

1. 先只做 `jsonl + sqlite`
2. 先支持最关键 8-10 个事件类型
3. Dashboard 先消费 sqlite 聚合结果和少量实时事件
4. benchmark 正式报告只认 rollup 表

---

## 13. 非目标与暂不承诺

当前不承诺：

1. 分布式 trace 全链路兼容 OpenTelemetry
2. eBPF 级自动探针
3. 高吞吐流式日志基础设施

---

## 14. 验收建议

建议最小验收：

1. 一个任务完整跑完后，存在 `telemetry_events.jsonl`
2. sqlite 中存在对应 `telemetry_events` 记录
3. 能从正式聚合结果生成：
   - `raw_evidence_bytes_seen_by_llm`
   - `task_ms`
   - `skipped_step_count`
   - `reuse_gain`
4. Dashboard 与 benchmark 报告读取同一份聚合事实
