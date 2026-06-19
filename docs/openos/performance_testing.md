# 性能测试模块设计与实现

## 一、概述

性能测试模块用于统计和展示多 Agent 系统的运行性能数据，满足赛题要求：

> 系统需统计并展示 Agent 间消息次数、文本通信 token 或字符开销、非文本状态传递次数及数据规模、单任务总耗时、共享记忆命中率及整体性能提升情况。

本模块通过 `MetricsCollector` 类采集所有运行时指标，支持双模式（text vs structured）对比，输出结构化性能报告。

## 二、核心数据结构

**文件**: `metrics.py:1-16`

```python
@dataclass
class MetricsCollector:
    timings: dict[str, list[float]]       # 节点执行时间 {node_name: [duration_sec]}
    counters: dict[str, int]              # 计数器 {"memory_reuse_hits": N}
    store_ops: list[dict]                 # Store 操作日志 [{op, namespace, key, ...}]
    message_log: list[dict]               # AgentMessage 通信日志
    _task_start: float | None = None      # 任务开始时间戳
    _task_end: float | None = None        # 任务结束时间戳
    _node_start: float | None = None      # 当前节点开始时间戳
```

4 个数据容器各司其职：
- `timings` — 记录每个 graph node 的执行耗时（可多次调用取均值）
- `counters` — 通用计数器，当前用于记忆命中统计
- `store_ops` — 所有 Store 操作的详细日志（put/get/search + 命中情况）
- `message_log` — Agent 间结构化消息的完整记录

## 三、指标采集方法

### 3.1 任务计时

**文件**: `metrics.py:18-23`

```python
def start_task(self):
    self._task_start = time.time()
    self._node_start = time.time()

def stop_task(self):
    self._task_end = time.time()
```

- 在 `run_task_group()` 开头调用 `start_task()`，结尾调用 `stop_task()`
- 任务总耗时 = `_task_end - _task_start`
- `_node_start` 同时初始化，用于第一个节点的耗时计算

**调用位置**: `run_demo.py:62`（text 模式）、`run_demo.py:91`（structured 模式）

### 3.2 节点执行计时

**文件**: `metrics.py:25-35`

```python
def record_node(self, node_name: str):
    now = time.time()
    if self._node_start:
        self.timings.setdefault(node_name, []).append(now - self._node_start)
    self._node_start = now
```

- 每个 Agent 执行完毕后调用，记录从上次节点结束到当前的时间差
- 同名节点（如 retriever 被 fan-out 多次）会追加到列表中
- 节点总耗时 = 所有节点耗时之和

**调用位置**: `run_demo.py:75`（在 `stream()` 循环中，每个 node 执行后调用）

### 3.3 Store 操作记录

**文件**: `metrics.py:37-48`

```python
def record_store_op(self, op: str, namespace: str, key: str, found: bool = False):
    entry = {"op": op, "namespace": namespace, "key": key, "found": found}
    self.store_ops.append(entry)
    if op == "search" and found:
        self.counters["memory_reuse_hits"] = self.counters.get("memory_reuse_hits", 0) + 1
```

- `op` 类型: `"put"`（写入）、`"search"`（检索）
- `found=True` 表示搜索命中已有记忆
- 每次 `search` 且 `found=True` 时，`memory_reuse_hits` 计数器 +1

**调用位置**: `memory.py` 中的 `store_put()`、`store_search()` 包装函数

### 3.4 Agent 间消息记录

**文件**: `metrics.py:50-63`

```python
def record_message(self, source, target, action, param_chars, result_chars,
                   has_embedding, embedding_dims=0):
    self.message_log.append({
        "source": source,
        "target": target,
        "action": action,
        "param_chars": param_chars,
        "result_chars": result_chars,
        "has_embedding": has_embedding,
        "embedding_dims": embedding_dims,
    })
```

- 仅在 structured 模式下调用（text 模式不记录）
- 记录每条 AgentMessage 的通信元数据
- `has_embedding=True` 表示该消息携带了 embedding 向量

**调用位置**: 每个 Agent 的 structured 模式分支（`agents.py` 中 planner/retriever/executor/summarizer 各一处）

### 3.5 指标重置

**文件**: `metrics.py:65-70`

```python
def reset(self):
    self.timings.clear()
    self.counters.clear()
    self.store_ops.clear()
    self.message_log.clear()
```

- 双模式对比时，在 text 模式跑完后调用，清空所有指标
- structured 模式从零开始采集，确保对比公平

**调用位置**: `run_demo.py:86`

## 四、指标输出

### 4.1 文本报告

**文件**: `metrics.py:72-112` — `report()` 方法

输出 4 个区块：

**① 概览**（`metrics.py:73-82`）
```
任务总耗时: 12.35 秒
节点总耗时: 10.21 秒
Store 操作数: 6
```

**② 节点耗时**（`metrics.py:84-90`）
```
  planner: 3.12 秒
  executor: 4.56 秒
  summarizer: 2.53 秒
```

**③ Store 操作统计**（`metrics.py:92-112`）
```
  搜索操作: 3 次（命中 1 次）
  写入操作: 3 次
  记忆命中率: 33.3%
  记忆命中详情:
    [TASK_A] key: bio_cr1 → ✗ 未命中
    [TASK_A] key: topic_cr1 → ✓ 命中
```

**④ 结构化通信指标**（`metrics.py:115-135`）
```
  消息总条数: 8
  参数字符总数: 1234
  结果字符总数: 5678
  embedding 传递: 2 次 (1024 维)
  按动作类型分布:
    plan: 2 条
    retrieve: 2 条
    analyze: 2 条
    summarize: 2 条
```

### 4.2 结构化摘要

**文件**: `metrics.py:137-148` — `summary_dict()` 方法

```python
def summary_dict(self) -> dict:
    return {
        "message_count": len(self.message_log),
        "param_chars": sum(m["param_chars"] for m in self.message_log),
        "result_chars": sum(m["result_chars"] for m in self.message_log),
        "embedding_transfers": sum(1 for m in self.message_log if m["has_embedding"]),
        "total_task_time": (self._task_end or 0) - (self._task_start or 0),
        "total_node_time": sum(sum(v) for v in self.timings.values()),
        "memory_reuse_hits": self.counters.get("memory_reuse_hits", 0),
    }
```

返回 dict 用于双模式对比，包含 7 个关键指标。

## 五、双模式对比机制

### 5.1 执行流程

**文件**: `run_demo.py:52-140`

```
Phase 1: text 模式
  ├─ build_graph(mode="text")
  ├─ run_task_group(..., mode="text")  → Task A
  ├─ run_task_group(..., mode="text")  → Task B
  └─ text_summary = metrics.summary_dict()

metrics.reset()  ← 清空所有指标

Phase 2: structured 模式
  ├─ build_graph(mode="structured")
  ├─ run_task_group(..., mode="structured")  → Task A
  ├─ run_task_group(..., mode="structured")  → Task B
  └─ struct_summary = metrics.summary_dict()

Phase 3: 对比输出
  └─ print_comparison(text_summary, struct_summary)
```

### 5.2 对比表实现

**文件**: `run_demo.py:118-140`

```python
def print_comparison(text_sum: dict, struct_sum: dict):
    metrics = [
        ("Agent 消息次数", "message_count"),
        ("参数字符数", "param_chars"),
        ("结果字符数", "result_chars"),
        ("embedding 传递次数", "embedding_transfers"),
        ("记忆复用命中", "memory_reuse_hits"),
        ("任务总耗时(秒)", "total_task_time"),
    ]
    # 打印对比表，计算差值和百分比
```

输出示例：
```
══════════════════════════════════════════════════
  Text vs Structured 模式对比
══════════════════════════════════════════════════
  指标                   Text        Structured
  ────────────────────────────────────────────────
  Agent 消息次数          0           8
  参数字符数              0           1234
  结果字符数              0           5678
  embedding 传递次数      0           2
  记忆复用命中            1           1
  任务总耗时(秒)          12.3        14.5
══════════════════════════════════════════════════
```

### 5.3 对比指标说明

| 指标 | text 模式 | structured 模式 | 对比意义 |
|------|----------|----------------|---------|
| Agent 消息次数 | 0（不经过 record_message） | 8（每条 AgentMessage 记录） | 量化通信可见性 |
| 参数字符数 | 0 | ~1234 | 结构化协议的参数开销 |
| 结果字符数 | 0 | ~5678 | 结构化协议的结果开销 |
| embedding 传递 | 0 | 2 | 非文本状态传递使用情况 |
| 记忆复用命中 | 1 | 1 | 共享记忆对两种模式均有效 |
| 任务总耗时 | ~12s | ~14s | 结构化协议的额外时间开销 |

## 六、性能指标采集架构

```
Agent 执行
  │
  ├─ metrics.start_task()          ← 任务开始
  │
  ├─ [每个 node 执行完毕]
  │   ├─ metrics.record_node()     ← 节点耗时
  │   └─ metrics.record_message()  ← 通信记录（structured 模式）
  │
  ├─ [Store 操作]
  │   ├─ store_put()  → metrics.record_store_op("put", ...)
  │   └─ store_search() → metrics.record_store_op("search", found=...)
  │
  ├─ metrics.stop_task()           ← 任务结束
  │
  └─ metrics.report()              ← 输出报告
     metrics.summary_dict()        ← 返回结构化数据
```

## 七、文件清单

| 文件 | 作用 | 关键行号 |
|------|------|---------|
| `metrics.py` | 指标采集、存储、输出 | 数据结构 `:1-16`，采集方法 `:18-70`，输出方法 `:72-148` |
| `run_demo.py` | 双模式执行、对比输出 | Phase 1 `:60-84`，reset `:86`，Phase 2 `:88-112`，对比 `:118-140` |
| `agents.py` | 调用 record_message() | 每个 Agent 的 structured 分支 |
| `memory.py` | 调用 record_store_op() | store_put/store_search 包装函数 |

## 八、赛题对应

| 赛题要求 | 实现 |
|---------|------|
| Agent 间消息次数 | `message_log` 长度 — `metrics.py:27` |
| 文本通信字符开销 | `param_chars` + `result_chars` — `metrics.py:38-42` |
| 非文本传递次数及规模 | `embedding_transfers` + `embedding_dims` — `metrics.py:43-44` |
| 单任务总耗时 | `_task_end - _task_start` — `metrics.py:74-80` |
| 共享记忆命中率 | `memory_reuse_hits` / 总查询 — `metrics.py:59` |
| 整体性能提升 | `print_comparison()` 差值计算 — `run_demo.py:118-140` |
