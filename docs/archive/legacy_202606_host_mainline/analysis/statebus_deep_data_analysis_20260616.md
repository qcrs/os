# StateBus 实验数据深度分析

日期：2026-06-16
运行目录：`runs/api_repeat1_smoke_20260616_165207/`

---

## 一、typed_state_mechanism_v3 — 核心问题定位

### 1.1 逐 task 数据

```
rr-checkout-clean-natural-handoff-001:
  retrieve: route=generic_triage, conf=0.0
  execute:  route=db_pool_saturation, tool=tool.db_pool_triage   ← 纠正了！
  exec_input_kinds=['TOOL_ARTIFACT']

rr-checkout-clean-state-packet-101:
  retrieve: route=generic_triage, conf=0.0
  execute:  route=generic_triage, tool=tool.collect_more_evidence ← 没纠正！
  exec_input_kinds=['DENSE_EVIDENCE', 'EXECUTOR_DECISION_PACKET']
```

同一个 task，natural_handoff_text 的 executor 从 generic_triage 纠正到 db_pool_saturation。state_packet_minimal 的 executor 保持 generic_triage。

### 1.2 代码根因 — 两条路径的不对称

**natural_handoff_text 路径** (`_feature_bundle_from_natural_handoff`，line 1728-1744)：

```python
bundle = build_feature_bundle(
    evidence_text=f"{evidence_text}\n{handoff_text}",   # 合并了 DENSE_EVIDENCE + handoff text
    registry=registry,    # ← 使用 registry 做独立词法匹配
)
```

`build_feature_bundle()` → `registry.retrieve_candidates()` → 在合并的 evidence 文本上做 lexical matching → **可以在 retriever 给出 generic_triage 时，executor 自己找到 db_pool_saturation。**

**state_packet_minimal 路径** (`_feature_bundle_from_executor_decision_packet`，line 1779-1787)：

```python
del registry   # ← 丢弃 registry！
_validate_executor_decision_packet(packet=decision_packet)
route = str(decision_packet.get("route", "")).strip()
# ... 完全从 decision_packet 字段重建 bundle，不使用 registry、不做词法匹配
```

executor 收到 `evidence_text` 参数但只用于计算 `evidence_sha256`（line 1843）——**不做任何词法匹配、不做任何 fallback**。如果 decision packet 说 generic_triage，executor 就出 generic_triage。

### 1.3 这是怎么产生的

旧版代码中 `_feature_bundle_from_executor_decision_packet` 调了 `build_feature_bundle()`：
```python
# 旧代码（已被替换）：
bundle = build_feature_bundle(query=..., evidence_text=..., registry=registry, ...)
for key in (...): bundle[key] = decision_packet[key]   # 再用 packet 字段覆盖
```

重构时删除了 `build_feature_bundle()` 调用（commit `fef9888` 或 `beb14fc`），理由是正确的：避免冗余的 tool candidate search + evidence hashing。但副作用是删除了 fallback 路径——当 decision packet 的 route 是 generic_triage 时，executor 失去了自我纠正的能力。

**之前有 corpus hint 时这不是问题**——retriever 总能产出正确的 route。去掉 hint 后 retriever 95% 产 generic_triage，protocol executor 完全暴露在这条弱路径上。

---

## 二、Contest Dual-Mode — protocol 正确率为什么远低于 text

### 2.1 Per-mode 对比

| 指标 | Text | Protocol |
|---|---|---|
| Retrieve 产出 generic_triage | 19/20 | 19/20 |
| Execute 产出 generic_triage | **9/20** | **19/20** |
| Execute 精确匹配 | **8/20** | **1/20** |
| Execute 容许匹配 | 11/20 | 1/20 |

Text executor 把 19 个 generic_triage 纠正了 10 个（+2 个容许）。Protocol executor 纠正了 0 个。

### 2.2 Text executor 的纠正路径详解

`_feature_bundle_from_strict_pure_text_handoff`（line 1747-1776）：

```python
lexical_match = registry.retrieve_candidates(
    query_text=query.lower(),
    primary_evidence_text=evidence_text.lower(),
    evidence_text=evidence_text.lower(),
    tags=[],
    limit=1,
)
selected = lexical_match[0] if lexical_match else registry.fallback_match()
route = selected.route or "generic_triage"
```

**完全独立的词法匹配**——retriever 给了 generic_triage，executor 不理会，自己重新做 `retrieve_candidates()`。这就是为什么 text 能 8/20 正确：executor 的 lexical matching 比 retriever 的 feature extraction 效果好。

### 2.3 Protocol executor 的盲信路径详解

`_feature_bundle_from_executor_decision_packet`（line 1779-1843）：如 1.2 所述，直接从 decision packet 取值，无 fallback。

### 2.4 Auth family 为什么 text 能全对

```
text auth-clean:       retrieve=auth_session_drift(conf=0.95) → execute=auth_session_drift ✅
text auth-distractor:  retrieve=generic_triage(conf=0.0)      → execute=auth_session_drift ✅ (executor corrected!)
text auth-ambiguous:   retrieve=generic_triage(conf=0.0)      → execute=auth_session_drift ✅
text auth-reusable:    retrieve=generic_triage(conf=0.0)      → execute=auth_session_drift ✅
```

auth family 的 evidence 文本含有足够强的信号（`issuer mismatch`, `stale jwks`, `callback failures`），让 text executor 的 lexical matching 能可靠找到 `auth_session_drift`。同样的 evidence 在 protocol 下被喂给 retriever，retriever 产出 generic_triage，但 executor 没有 lexical fallback。

---

## 三、Planner — 正确的编排，受限的 retrieval

### 3.1 Planner 统计数据

| 指标 | 值 |
|---|---|
| planner_llm_request_count | 6.00 |
| planned_step_count | 38.00 |
| one_shot_valid | 1.00 |
| repair_attempts | 0 |
| admissible | 0.27 |

Planner 本身工作正常：所有 6 个 LLM 行一次通过，3 个 validate-first 行产出正确 4-step plan。admissible=0.27 是因为 retrieval 产出 generic_triage 导致 route 选择错误——这不是 planner 的错。

### 3.2 LangGraph 编排

`build_langgraph()`（line 185-197）：5 节点 DAG，带条件路由 `_next_after_retrieve`。plan 含 validate → 走 validate 节点，否则直通 executor。编排是正常的。

### 3.3 Planner 的受控状态

contest 和 memory_policy 包的 `plan_source_default: yaml` 意味着 Planner 在这些包上不被调用。这不是 bug——是设计选择（受控实验）。但答辩时需要说明。

---

## 四、Memory Replay — 唯一不受 retrieval 质量影响的线

| policy | task_ms | skipped | reuse_gain |
|---|---:|---:|---:|
| memory_off | 3332 | 0 | 0 |
| exact_replay | 1756 | 2 | 0.67 |

replay gate pass，exact_match=1.00。Memory replay 靠 route/docset/hash 匹配，不靠 retrieval 质量。去 hint 不影响。

---

## 五、发现汇总

### 结构性缺陷

| 缺陷 | 代码位置 | 影响 |
|---|---|---|
| state_packet_minimal executor 无 lexical fallback | `executor_runtime.py:1787` — `del registry` | 去 hint 后 protocol 正确率 1/20 vs text 8/20 |
| natural_handoff_text executor 有独立词法匹配 | `executor_runtime.py:1735` — `build_feature_bundle(...registry=registry)` | text 能在 retriever 失败时自救 |
| 两条路径不对称 | executor_runtime.py 两条路径的 registry 使用方式不同 | 无法公平比较两种 handoff |

### 赛题相关

| 赛题要求 | 当前状态 |
|---|---|
| 纯文本 vs 结构化对比 | 实验跑了，但不公平——text executor 有 lexical fallback，protocol 没有 |
| 非文本状态传递创新 | 机制存在（DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET），consumer sensitivity 证明缺了会失败。但 retrieval 质量差时 protocol 无 fallback |
| 通信效率 | control_bytes -15.6%（稳定），但 task_ms 持平（协议开销抵消） |

### 不是问题的地方

- Planner/LangGraph 编排正常——one_shot=1.00, repair=0
- Consumer sensitivity 统计口径干净
- Memory replay 稳健
- Object parity gate pass
