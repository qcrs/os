# StateBus KV 中间状态机制设计和实施计划

设计日期：2026-07-14  
基于调研：`01_kv_intermediate_state_research.md`  
状态：初稿完成

## 执行摘要

本文档提供 StateBus KV 中间状态机制的详细设计和实施计划。

**推荐架构：强化 vLLM Engine-Local Prefix 路线**

核心定义：StateBus KV 中间状态 = Engine-Local Prefix Identity + Scheduling Control

- 控制面：`NeuralPrefixIdentity`、`NeuralStateHandle`、`PrefixReuseScheduleHint`
- 数据面：vLLM native prefix caching（GPU memory KV blocks）
- Observability：vLLM counter delta、TTFT probe、prefix feedback loop

**相对当前实现的增量：**
1. 优化 evidence layout（role-agnostic prefix）
2. 增强 cache-friendly scheduling（动态 reorder、feedback 校准）
3. 完善 observability（持久化 feedback、counter audit）
4. 明确声明边界（控制面对象，不是 KV tensor export）

**Fallback 方案：**
- LMCache adapter 作为可选模块（第一版不实施，预留接口）

---

## 目录

[待补充]


## 1. 推荐架构

### 1.1 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                     StateBus Control Plane                       │
│                                                                   │
│  ┌────────────┐    ┌─────────────────┐    ┌─────────────────┐ │
│  │  Planner   │───▶│   Retriever     │───▶│    Executor     │ │
│  │            │    │   Fan-out       │    │                 │ │
│  └────────────┘    └─────────────────┘    └─────────────────┘ │
│                            │                        │           │
│                            ▼                        ▼           │
│                    ┌──────────────────────────────────┐         │
│                    │   Evidence + Prefix Identity    │         │
│                    │  - SemanticStateRef              │         │
│                    │  - NeuralPrefixIdentity          │         │
│                    │  - corpus_prefix_hash            │         │
│                    │  - evidence_prefix_hash          │         │
│                    └──────────────────────────────────┘         │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │            Cache-Friendly Scheduling                        │ │
│  │  - order_prefix_schedule_hints()                           │ │
│  │  - Corpus affinity grouping                                │ │
│  │  - Prefix feedback loop calibration                        │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │            EngineLocalPrefixRegistry                        │ │
│  │  - Session-scoped handle registry                          │ │
│  │  - Compatibility check                                     │ │
│  │  - Lifecycle management                                    │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
└───────────────────────────┬───────────────────────────────────────┘
                            │
                            │ Prompt with stable prefix
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     vLLM Serving Engine                          │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │         Automatic Prefix Caching (native)                   │ │
│  │  - Token sequence → KV blocks mapping                      │ │
│  │  - GPU memory KV cache                                     │ │
│  │  - Prefix match detection                                  │ │
│  │  - Block reuse (automatic)                                 │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │         Prometheus Metrics Exporter                         │ │
│  │  - gpu_prefix_cache_queries_total                          │ │
│  │  - gpu_prefix_cache_hits_total                             │ │
│  │  - Block counter delta                                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
└───────────────────────────┬───────────────────────────────────────┘
                            │
                            │ Counter delta
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Observability                               │
│                                                                   │
│  - Task-local counter delta sampling                            │
│  - TTFT probe (alternating order)                               │
│  - Prefix feedback loop (predicted vs observed)                 │
│  - Persistent feedback history                                  │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 组件职责

| 组件 | 职责 | 输入 | 输出 |
|------|------|------|------|
| **Planner** | 解析任务、生成 bounded semantic plan | Task spec、corpus | Retrieval objectives |
| **Retriever** | 检索证据、构造 stable prefix | Objectives、corpus | SemanticStateRef、NeuralPrefixIdentity |
| **EngineLocalPrefixRegistry** | 注册和管理 prefix handle | Prefix identity | NeuralStateHandle、cache hit flag |
| **Scheduler** | Cache-friendly task ordering | Schedule hints | Ordered task queue |
| **vLLM Engine** | LLM inference + automatic prefix caching | Prompt with stable prefix | Completion + KV blocks reuse |
| **Metrics Exporter** | Export vLLM block counters | - | Prometheus metrics |
| **Prefix Feedback** | 校准 predicted vs observed hit rate | Predicted、observed | Reorder signal |
| **Executor** | 执行工具、生成结果 | Evidence、execution plan | ExecutionArtifactRef、LogitStateRef |
| **Summarizer** | 总结结果、commit memory | Evidence、execution result | Summary、MemoryCommit |

### 1.3 当前架构到目标架构

**当前架构（2026-07-14）：**
- ✅ 控制面对象已存在（NeuralPrefixIdentity、NeuralStateHandle）
- ✅ shared_evidence_prefix layout 已实现
- ✅ Cache-friendly scheduling 已实现
- ✅ vLLM counter exporter 已实现
- ✅ Prefix feedback loop 已实现
- ✅ Task-local counter delta 已验证（78% hit rate）

**目标架构增强（第一版）：**
1. 📌 Evidence layout 优化：确保不同 role 共享完全相同 token prefix
2. 📌 Scheduling 增强：更激进的 cache-friendly order、动态 feedback-driven reorder
3. 📌 Observability 完善：持久化 prefix feedback history、counter delta audit trail
4. 📌 文档和声明边界：明确 "engine-local prefix control"，不是 KV tensor export
5. 📌 Benchmark 增强：prefix disabled baseline、identity perturbed ablation

**不做的（第一版）：**
- ❌ External KV cache service（LMCache adapter 预留接口，不实施）
- ❌ KV tensor export/serialization
- ❌ Cross-engine KV transfer
- ❌ Evidence-segment KV composition


## 2. Contract 和数据流设计

### 2.1 核心 Contract

#### 2.1.1 NeuralPrefixIdentity（已存在，需文档化）

```python
@dataclass(frozen=True)
class NeuralPrefixIdentity:
    """Stable identity for corpus-level and evidence-level prefix scheduling.
    
    This is a control-plane object for cache affinity and scheduling decisions.
    It does NOT represent a KV tensor or external KV reference.
    
    Claim boundary: prefix_identity_and_scheduling_control_plane_only
    """
    corpus_prefix_hash: str           # For scheduling (same corpus → same group)
    evidence_prefix_hash: str         # For exact prefix matching
    source_doc_hashes: tuple[str, ...] # Evidence source documents
    evidence_pack_hash: str           # Hydrated evidence content
    hydrate_manifest_hash: str        # Evidence locator and manifest
    system_prompt_version: str        # Must match for compatibility
    prefix_contract_version: str      # Schema version
    claim_boundary: str = "prefix_identity_and_scheduling_control_plane_only"
    schema_version: str = "statebus.neural_prefix_identity.v1"
```

**构造规则：**
- `corpus_prefix_hash`：基于 sorted source_doc_hashes + system_prompt_version
- `evidence_prefix_hash`：基于 corpus_hash + evidence_pack_hash + hydrate_manifest_hash
- 排除不稳定因素：query、Planner 措辞、score、lexical hint

#### 2.1.2 NeuralStateHandle（已存在，需文档化）

```python
@dataclass(frozen=True)
class NeuralStateHandle:
    """Engine-local handle for session-scoped prefix cache management.
    
    This is NOT a KV tensor reference. It tracks control-plane metadata
    for a prefix that MAY be cached inside the vLLM engine.
    
    Actual KV blocks are owned by vLLM and not directly accessible.
    """
    engine_id: str                    # vLLM engine instance ID
    session_id: str                   # StateBus session (for isolation)
    prefix_hash: str                  # Unique prefix identity
    model_id: str                     # Must match for compatibility
    tokenizer_id: str                 # Must match for compatibility
    corpus_prefix_hash: str           # For affinity grouping
    evidence_prefix_hash: str         # For exact matching
    lifetime_scope: str = "task_session"
    prefix_token_count: int = 0       # Estimated prefix length
    cache_hit_count: int = 0          # Control-plane counter (not vLLM raw)
    expires_at_ns: int = 0            # Lease expiration
    claim_boundary: str = "prefix_identity_and_scheduling_control_plane_only"
    schema_version: str = "statebus.neural_state_handle.v1"
    
    def is_compatible_with(self, *, engine_id: str, session_id: str,
                          prefix_hash: str, model_id: str, 
                          tokenizer_id: str) -> bool:
        """Strict compatibility check. Fail closed on mismatch."""
        return (self.engine_id == engine_id and 
                self.session_id == session_id and
                self.prefix_hash == prefix_hash and
                self.model_id == model_id and
                self.tokenizer_id == tokenizer_id)
```

#### 2.1.3 PrefixReuseScheduleHint（已存在，需增强）

```python
@dataclass(frozen=True)
class PrefixReuseScheduleHint:
    """Scheduling hint for cache-friendly task ordering.
    
    Used by scheduler to group tasks with same corpus_prefix_hash together.
    """
    task_id: str
    corpus_prefix_hash: str           # Affinity group key
    evidence_prefix_hash: str         # For exact matching (optional)
    estimated_prefix_tokens: int      # For priority ranking
    cache_affinity_group: str = ""    # Override affinity group
    schedule_priority: float = 0.0    # Higher = earlier
    metadata: dict[str, Any] = field(default_factory=dict)
    claim_boundary: str = "prefix_identity_and_scheduling_control_plane_only"
    schema_version: str = "statebus.neural_prefix_schedule_hint.v1"
```

### 2.2 数据流时序

#### 2.2.1 Cold Miss（首次请求，无 prefix cache）

```
1. Planner
   └─> 生成 retrieval objectives

2. Retriever
   ├─> 检索 evidence chunks
   ├─> 构造 stable evidence prefix
   ├─> 计算 corpus_prefix_hash、evidence_prefix_hash
   └─> 创建 NeuralPrefixIdentity

3. EngineLocalPrefixRegistry
   ├─> lookup(prefix_hash) → None (cache miss)
   └─> ensure_handle() → 创建 NeuralStateHandle (cache_hit=False)

4. Role Path (Executor)
   ├─> 构造 prompt with shared_evidence_prefix layout
   ├─> vLLM 采样前：fetch_vllm_prefix_cache_metrics() → before
   ├─> vLLM inference (cold prefill, 无 prefix hit)
   └─> vLLM 采样后：fetch_vllm_prefix_cache_metrics() → after

5. Observability
   ├─> compute_vllm_prefix_cache_counter_delta(before, after)
   ├─> 记录 task-local queries/hits (例如: 2 queries, 0 hits)
   └─> prefix_feedback.record_observation(predicted=0.0, observed_delta)

6. Role Path (Summarizer)
   ├─> 复用相同 evidence prefix
   ├─> vLLM 采样前后
   ├─> vLLM inference (warm prefill, prefix hit!)
   └─> Counter delta: 2 queries, 1 hit

7. Registry Update
   └─> NeuralStateHandle.cache_hit_count += 1
```

#### 2.2.2 Warm Hit（后续请求，相同 corpus）

```
1. Scheduler
   ├─> 接收 N 个 PrefixReuseScheduleHint
   ├─> order_prefix_schedule_hints(mode="cache_friendly")
   └─> 按 corpus_prefix_hash 分组，同组连续调度

2. Task N (same corpus as Task 1)
   ├─> Retriever 生成相同 corpus_prefix_hash
   ├─> Registry.lookup() → 找到 existing handle (cache_hit=True)
   ├─> vLLM inference → prefix hit (same evidence)
   └─> Counter delta: 更高 hit rate

3. Prefix Feedback
   ├─> predicted_hit_rate = 0.5 (基于 2 consumer roles)
   ├─> observed_hit_rate = 0.75 (从 counter delta)
   ├─> mean_error = -0.25 (under-predicted)
   └─> should_reorder() = False (error < threshold)
```

#### 2.2.3 Partial Hit（evidence 部分变化）

```
1. Task with similar but not identical evidence
   ├─> corpus_prefix_hash 相同（same source docs）
   ├─> evidence_prefix_hash 不同（different query/chunks）
   └─> Registry.lookup(evidence_prefix_hash) → None

2. vLLM Behavior
   ├─> Corpus-level token prefix 可能部分相同
   ├─> vLLM automatic prefix matching (longest common prefix)
   └─> 部分 block reuse（取决于 vLLM 内部实现）

3. StateBus Observation
   ├─> Counter delta 显示部分 hit
   ├─> 无法精确归因到具体 prefix（vLLM 内部细节）
   └─> 记录 observed hit rate，用于 feedback 校准
```

#### 2.2.4 Exact Replay（绕过 LLM）

```
1. Replay Gate
   ├─> 检查 evidence_execution_input_replay_hash
   ├─> 匹配历史 exact key → exact replay
   └─> 直接恢复历史 output (skip LLM call)

2. 不触发 vLLM Prefix Cache
   └─> 没有 LLM call，vLLM counter 不变

3. Replay vs Prefix Cache 是独立机制
   ├─> Replay: 完全跳过 LLM，恢复历史 output
   └─> Prefix Cache: LLM call 发生，但 prefill 更快
```

### 2.3 与现有状态系统协同

#### 2.3.1 一次完整请求的状态流

```
Phase 1: Planning
  Planner → bounded SemanticTaskPlan
  ├─> retrieval_objectives (4 types: lexical/semantic/table/memory)
  └─> required_evidence、required_outputs

Phase 2: Retrieval + Prefix Identity
  Retriever Fan-out
  ├─> Lexical retrieval → evidence chunks
  ├─> Semantic retrieval → evidence chunks
  ├─> Table retrieval → table cells
  └─> Memory lookup → historical artifacts/strategies

  Evidence Consolidation
  ├─> Hydrate evidence → SemanticStateRef
  ├─> Compute stable prefix → NeuralPrefixIdentity
  └─> Register to EngineLocalPrefixRegistry → NeuralStateHandle

Phase 3: Execution + KV Reuse
  Executor
  ├─> Consume SemanticStateRef (evidence)
  ├─> Consume NeuralPrefixIdentity (control plane)
  ├─> vLLM automatic prefix cache hit (data plane)
  ├─> Generate execution result → ExecutionArtifactRef
  └─> Extract logit state → LogitStateRef

Phase 4: Summarization + KV Reuse
  Summarizer
  ├─> Consume evidence + execution result
  ├─> vLLM prefix cache hit again (same evidence prefix)
  ├─> Generate summary
  └─> Commit to memory → MemoryCommit

Phase 5: Observability
  ├─> Sample vLLM counter delta
  ├─> Record prefix feedback
  ├─> Persist task metrics
  └─> Update registry statistics
```

#### 2.3.2 对象生命周期

| 对象 | 生命周期 | 持久化 | GC 时机 |
|------|---------|--------|---------|
| `NeuralPrefixIdentity` | Task session | Task artifacts | Task completion |
| `NeuralStateHandle` | Session-scoped | Registry (in-memory) | Session end or explicit invalidation |
| `SemanticStateRef` | Task session | shared_memory / mmap | Task completion or lease expiration |
| `ExecutionArtifactRef` | Persistent | workspace + CAS | Manual cleanup or retention policy |
| `MemoryCommit` | Persistent | SQLite + FAISS | Manual cleanup or retention policy |
| vLLM KV blocks | Engine-managed | GPU memory | vLLM internal eviction policy |


## 3. 实施工作包

### 3.1 工作包 1：Evidence Layout 优化

**目标：** 确保不同 role 共享完全相同的 token prefix

**涉及文件：**
- `v2/runtime/role_path.py`：prompt 构造逻辑
- `v2/runtime/smoke.py`：role-specific prompt assembly

**当前问题：**
- 不同 role 的 system prompt 可能在 evidence 之前，破坏 prefix 相同性
- Role instruction 的位置和格式不统一

**实施内容：**

1. **统一 System Prompt Base**
   ```python
   # 当前（示例）
   prompt = f"{role_system_prompt}\n{evidence}\n{task_instruction}"
   
   # 目标
   prompt = f"{unified_base_prompt}\n{evidence}\n{role_suffix}"
   ```

2. **Evidence-First Layout**
   - Evidence 始终在最前（除了必要的 system base）
   - Role-specific instruction 在 evidence 之后
   - 验证不同 role 的 token prefix 完全相同（前 N tokens）

3. **Token-Level 验证**
   - 增加 unit test：验证 Executor 和 Summarizer 的 evidence prefix tokens 相同
   - 记录 prefix_token_count，用于 observability

**测试：**
- Unit test: 验证不同 role 的 tokenized prefix 相同
- Integration test: 验证 vLLM counter delta 显示 hit

**验收标准：**
- ✅ Executor 和 Summarizer 的 evidence prefix tokens 100% 相同
- ✅ Task-local counter delta 显示 hit rate > 0（warm path）

**风险：**
- 可能影响 role prompt 质量（需要验证 quality gate）
- 需要重新调整 prompt template

**回滚点：**
- 保留旧 prompt layout 作为 fallback
- Feature flag 控制新 layout

### 3.2 工作包 2：Cache-Friendly Scheduling 增强

**目标：** 更激进的 cache-friendly order、动态 feedback-driven reorder

**涉及文件：**
- `v2/runtime/neural_state.py`：`order_prefix_schedule_hints()`
- `v2/benchmark/live_runner.py`：benchmark scheduling logic
- `v2/runtime/prefix_feedback.py`：feedback loop

**实施内容：**

1. **更激进的 Affinity Grouping**
   ```python
   def order_prefix_schedule_hints_v2(
       hints: list[PrefixReuseScheduleHint],
       *,
       mode: str = "cache_friendly",
       feedback: PrefixCacheFeedbackLoop | None = None,
   ) -> list[PrefixReuseScheduleHint]:
       if mode == "cache_friendly":
           # 按 corpus_prefix_hash 严格分组
           # 同组内按 estimated_prefix_tokens 降序
           # 同组连续调度（不 interleave）
       elif mode == "feedback_driven":
           # 根据 feedback.mean_error() 动态调整
           # Under-predicted → 更激进分组
           # Over-predicted → 放松分组
   ```

2. **Dynamic Reorder**
   - 在 benchmark run 中，每 N 个 task 后检查 feedback
   - 如果 `feedback.should_reorder() == True`，对剩余 tasks reorder
   - 记录 reorder event 到 telemetry

3. **Affinity Group Visualization**
   - 在 benchmark report 中可视化 affinity group
   - 显示每个 group 的 task count、estimated hit rate、observed hit rate

**测试：**
- Unit test: 验证 cache_friendly mode 严格分组
- Integration test: 验证 feedback_driven mode 能触发 reorder

**验收标准：**
- ✅ Cache-friendly mode 下，同 corpus 的 tasks 100% 连续
- ✅ Feedback-driven mode 能在 prediction error > threshold 时 reorder

**风险：**
- 过度分组可能降低并发度（当前 serialized run，不影响）
- Dynamic reorder 增加调度复杂度

**回滚点：**
- 保留当前 scheduling 逻辑作为 fallback
- Feature flag 控制新 scheduling

### 3.3 工作包 3：Observability 完善

**目标：** 持久化 prefix feedback history、counter delta audit trail

**涉及文件：**
- `v2/runtime/vllm_metrics.py`：metrics parsing
- `v2/runtime/prefix_feedback.py`：feedback loop
- `v2/runtime/smoke.py`：task metrics injection

**实施内容：**

1. **Persistent Prefix Feedback History**
   ```python
   @dataclass
   class PrefixFeedbackHistory:
       task_id: str
       predicted_hit_rate: float
       observed_hit_rate: float
       observed_delta: VllmPrefixCacheCounterDelta
       feedback_snapshot: PrefixCacheFeedbackSnapshot
       timestamp_ns: int
       
   # 持久化到 workspace/logs/prefix_feedback_history.jsonl
   ```

2. **Counter Delta Audit Trail**
   - 每次 task-local counter delta 持久化到 audit log
   - 包含：before/after metrics、delta、validity flag、unavailable reason
   - 用于后续分析和 debug

3. **Prefix Cache Report Section**
   - 在 benchmark report 增加 "Prefix Cache Analysis" 章节
   - 包含：aggregate hit rate、per-affinity-group hit rate、feedback calibration
   - 可视化：predicted vs observed、reorder events

**测试：**
- Integration test: 验证 feedback history 正确持久化
- Integration test: 验证 counter delta audit trail 完整

**验收标准：**
- ✅ 每次 task run 的 prefix feedback 都持久化
- ✅ Counter delta audit trail 完整、可重现分析

**风险：**
- 增加 I/O overhead（较小）
- 日志文件增大（可接受）

**回滚点：**
- Feature flag 控制 persistent logging

### 3.4 工作包 4：文档和声明边界

**目标：** 明确 "engine-local prefix control"，不是 KV tensor export

**涉及文件：**
- `v2/runtime/neural_state.py`：增加 docstring 和 claim_boundary
- `docs/reports/`：更新实验报告 claim boundary
- `README.md`：更新能力描述

**实施内容：**

1. **Code Docstring**
   - 为所有 Neural* 类增加详细 docstring
   - 明确说明：控制面对象，不是 KV tensor reference
   - 明确 claim_boundary 字段含义

2. **Experiment Report Template**
   - 更新 benchmark report template
   - 增加 "Prefix Cache Claim Boundary" 章节
   - 明确可宣称和不可宣称的内容

3. **README 更新**
   - 更新 "非文本中间状态传递" 描述
   - 明确：prefix identity + scheduling control
   - 不宣称：KV tensor export/transfer

**测试：**
- Documentation review

**验收标准：**
- ✅ 所有 Neural* 类有完整 docstring
- ✅ Benchmark report 包含 claim boundary 章节
- ✅ README 准确描述能力边界

**风险：**
- 无

**回滚点：**
- N/A

### 3.5 工作包 5：Benchmark 增强

**目标：** 增加 prefix disabled baseline、identity perturbed ablation

**涉及文件：**
- `v2/benchmark/live_runner.py`：benchmark runner
- `scripts/run_v2_local_vllm_formal_suite.sh`：benchmark script

**实施内容：**

1. **Prefix Disabled Baseline**
   ```bash
   # 启动 vLLM without prefix caching
   vllm serve qwen3-32b --disable-prefix-caching
   
   # 运行 benchmark
   python -m v2.benchmark.live_runner \
     --suite formal \
     --prefix-cache-mode disabled
   ```

2. **Identity Perturbed Ablation**
   ```python
   # 在 benchmark run 中，故意扰动 prefix identity
   # 例如：增加 random salt 到 corpus_prefix_hash
   # 验证：perturbed identity 导致 cache miss
   ```

3. **Ablation Matrix**
   ```
   Baseline: prefix_cache=enabled, identity=stable
   Ablation 1: prefix_cache=disabled, identity=stable
   Ablation 2: prefix_cache=enabled, identity=perturbed
   Ablation 3: prefix_cache=enabled, scheduling=cache_hostile
   ```

**测试：**
- Integration test: 验证 disabled baseline 正确运行
- Integration test: 验证 perturbed ablation 显示 miss

**验收标准：**
- ✅ Prefix disabled baseline 可运行、质量不变、latency 更高
- ✅ Identity perturbed 显示 cache miss、latency 更高
- ✅ Ablation matrix 完整、可公平对比

**风险：**
- 需要重启 vLLM（disable prefix caching）
- 增加 benchmark run 时间

**回滚点：**
- N/A（增量 ablation，不影响主线）

### 3.6 工作包依赖关系

```
WP1 (Evidence Layout)
  └─> WP2 (Scheduling)  [Layout 优化后，scheduling 更有效]
      └─> WP3 (Observability)  [Scheduling 后，记录 feedback]
          └─> WP5 (Benchmark)  [完整 observability 后验证]

WP4 (Documentation)  [独立，可并行]
```

**建议实施顺序：**
1. WP4（文档）：低风险，可先行
2. WP1（Layout）：核心优化
3. WP3（Observability）：与 WP1 可部分并行
4. WP2（Scheduling）：依赖 WP1
5. WP5（Benchmark）：最后验证

**总估算：**
- WP1: 3-5 天（含测试和 quality 验证）
- WP2: 2-3 天
- WP3: 2-3 天
- WP4: 1-2 天
- WP5: 2-3 天
- **总计：10-16 天**


## 4. 风险、Fallback 和迁移

### 4.1 主要技术风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| Evidence layout 改变影响 prompt 质量 | 高 | 中 | Quality gate 验证；保留旧 layout fallback |
| vLLM prefix cache 行为不稳定 | 中 | 低 | Counter delta 监控；已有定向验证 |
| Scheduling 过度分组降低吞吐 | 中 | 低 | 当前 serialized run，不影响；未来可配置 |
| Counter delta 采样失败 | 低 | 中 | Graceful fallback；记录 unavailable |
| openEuler 环境兼容性 | 中 | 低 | 已在 Docker 容器验证；minimal 依赖 |

### 4.2 Fallback 策略

**Level 1: Feature Flag Fallback**
```python
# 每个新特性都有 feature flag
ENABLE_OPTIMIZED_EVIDENCE_LAYOUT = True
ENABLE_AGGRESSIVE_CACHE_SCHEDULING = True
ENABLE_PERSISTENT_PREFIX_FEEDBACK = True

# 可运行时或启动时配置
if not ENABLE_OPTIMIZED_EVIDENCE_LAYOUT:
    # 使用旧 layout
```

**Level 2: Graceful Degradation**
- Counter delta 采样失败 → 记录 unavailable，继续运行
- Prefix feedback 异常 → 跳过 reorder，使用默认 order
- Registry lookup 失败 → 记录 miss，继续 LLM call

**Level 3: Complete Rollback**
- 保留当前 git tag（v2-non-kv-baseline-20260710）
- 可随时回滚到 baseline
- 所有变更通过 feature flag 控制

### 4.3 迁移计划

**阶段 1：Baseline 确认**
1. 确认当前 baseline 可稳定复现
2. Tag baseline code
3. 记录 baseline metrics

**阶段 2：增量实施**
1. 逐个 WP 实施
2. 每个 WP 完成后运行 regression test
3. 对比 baseline，确保无回归

**阶段 3：完整验证**
1. 运行完整 benchmark matrix（含 ablation）
2. 生成 comprehensive report
3. Review claim boundary

**阶段 4：openEuler 交付**
1. 在 openEuler 容器内重新验证
2. 生成交付 artifact
3. 文档和演示准备

### 4.4 质量门

每个 WP 必须通过以下 gate：

1. **Code Quality**
   - ✅ pytest 全部通过
   - ✅ Type hints 完整
   - ✅ Docstring 完整

2. **Functionality**
   - ✅ Unit test 覆盖核心逻辑
   - ✅ Integration test 验证端到端
   - ✅ Smoke test 通过

3. **Performance**
   - ✅ 无明显性能回归（端到端 latency）
   - ✅ Counter delta 显示预期 hit rate

4. **Quality**
   - ✅ Quality gate 通过（expected facts matching）
   - ✅ 无 contamination detected

5. **Documentation**
   - ✅ Claim boundary 清晰
   - ✅ 可复现步骤完整

## 5. 验证实验设计

### 5.1 最小验证矩阵

**目标：** 证明因果关系，不只是相关性

| 实验 | 变量 | 固定 | 预期结果 | 用途 |
|------|------|------|---------|------|
| E1: Baseline | prefix_cache=enabled, identity=stable, scheduling=cache_friendly | model, task, quality_gate | Hit rate > 0, TTFT < baseline | 当前能力 |
| E2: Prefix Disabled | prefix_cache=disabled | 同上 | Hit rate = 0, TTFT 更高 | 证明 prefix cache 价值 |
| E3: Identity Perturbed | identity=random_salt | 同上 | Hit rate = 0, TTFT 更高 | 证明 identity 必要性 |
| E4: Scheduling Hostile | scheduling=interleaved | 同上 | Hit rate < E1, TTFT > E1 | 证明 scheduling 价值 |
| E5: Optimized Layout | evidence_layout=optimized | 同上 | Hit rate >= E1, quality pass | 证明 layout 优化有效 |

**对比维度：**
- vLLM block query/hit counter delta（task-local）
- TTFT（task-level probe）
- 端到端 task latency（serialized run）
- Quality gate pass rate
- Prompt token count、completion token count

**实验控制：**
- 同一 model（Qwen3-32B）
- 同一 task set（formal 25 cases）
- 同一 quality gate（expected facts）
- Serialized run（避免并发干扰）
- Repeat 3-5 次，报告 median + p90/p95

### 5.2 完整验证矩阵

在最小矩阵基础上，增加：

| 实验 | 目的 |
|------|------|
| E6: Continuous 10-round | 验证跨轮次 cache reuse |
| E7: Different corpus | 验证 corpus affinity 必要性 |
| E8: Same corpus different query | 验证 evidence-level reuse |
| E9: Replay vs Cache | 区分 replay（skip LLM）和 cache（faster prefill） |
| E10: Feedback calibration | 验证 feedback loop 能校准 predicted vs observed |

### 5.3 Observability 清单

**必须记录：**
1. ✅ vLLM block query/hit counter delta（per task）
2. ✅ TTFT（per role call）
3. ✅ 端到端 task latency
4. ✅ Prompt token count、completion token count
5. ✅ Quality gate result
6. ✅ Prefix feedback snapshot
7. ✅ Cache affinity group assignment
8. ✅ Scheduling order
9. ✅ Evidence layout version
10. ✅ Claim boundary declaration

**禁止的 Metrics：**
- ❌ vLLM service-lifetime cumulative gauge（不是 task-local）
- ❌ Estimated hit count without actual counter（不可验证）
- ❌ 单次 TTFT 当作端到端加速（复合收益需分解）

### 5.4 质量和 Oracle 检查

**质量门：**
- Expected facts matching（当前已有）
- Scorer-only，不泄露到 role prompt

**污染检查：**
- Taint scan：expected_facts、oracle_answer、correctness_hint 不出现在 role-visible 文件
- Case-ID 分支检查：代码中不应有 if task_id == "xxx" 的特化逻辑

**Counterfactual Test（理想）：**
- 扰动 expected facts → 模型仍应完成任务（不依赖 oracle）
- 当前未实现，记录为局限

## 6. Fallback 方案：LMCache Adapter（预留接口）

### 6.1 为什么预留

- 当前单 engine 环境下，LMCache 增量价值有限
- 但未来可能需要：cross-engine、persistent cache、multi-tenant
- 预留接口，不影响主线，降低未来重构成本

### 6.2 预留接口设计

```python
# v2/runtime/kv_cache_adapter.py (新文件，第一版只有接口)

from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class ExternalKVReference:
    """External KV cache reference (for future LMCache integration)."""
    cache_service_type: str  # "lmcache" | "redis" | "custom"
    cache_key: str
    chunk_ids: list[str]
    total_tokens: int
    cache_service_endpoint: str
    schema_version: str = "statebus.external_kv_ref.v1"

class KVCacheAdapter(ABC):
    """Abstract adapter for external KV cache services."""
    
    @abstractmethod
    def store_kv(self, prefix_identity: NeuralPrefixIdentity, 
                 kv_data: bytes) -> ExternalKVReference:
        """Store KV to external cache, return reference."""
        pass
    
    @abstractmethod
    def load_kv(self, kv_ref: ExternalKVReference) -> bytes:
        """Load KV from external cache."""
        pass
    
    @abstractmethod
    def invalidate_kv(self, kv_ref: ExternalKVReference) -> bool:
        """Invalidate KV in external cache."""
        pass

class LMCacheAdapter(KVCacheAdapter):
    """LMCache integration adapter (placeholder for future)."""
    
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        raise NotImplementedError(
            "LMCache adapter is reserved for future use. "
            "Current implementation uses vLLM engine-local prefix caching only."
        )
```

### 6.3 集成点（未实施）

如果未来实施 LMCache adapter：

1. **Control Plane**
   - StateBus 继续生成 `NeuralPrefixIdentity`
   - 通过 adapter 存储到 LMCache
   - 返回 `ExternalKVReference`

2. **Data Plane**
   - vLLM 启动时加载 LMCache patch
   - vLLM 调用 LMCache SDK 查询/加载 KV
   - StateBus 只持有 reference，不直接操作 KV tensor

3. **Observability**
   - 增加 LMCache-specific metrics
   - 区分 engine-local hit 和 cross-instance hit

### 6.4 不实施的理由（第一版）

1. **当前价值有限**：单 engine + session-scoped 场景，vLLM native 已足够
2. **部署复杂度高**：需要 LMCache service、patch vLLM、编译 extension
3. **openEuler 风险**：增加依赖和编译要求
4. **维护成本**：需要跟进 LMCache 和 vLLM 版本

**建议：** 第一版只预留接口，不实施。未来如需 cross-engine 或 persistent cache，再评估。

## 7. 当前可宣称与完成后可宣称

### 7.1 当前可宣称（2026-07-14 状态）

**已验证能力：**
- ✅ Engine-local prefix identity 和 scheduling control plane
- ✅ vLLM native prefix caching（automatic）
- ✅ Task-local block counter delta（78% hit rate 验证）
- ✅ TTFT reduction（shared 267ms vs independent 2,283ms）
- ✅ Cache-friendly scheduling
- ✅ Prefix feedback loop

**声明边界：**
- ✅ 控制面 identity + scheduling
- ✅ vLLM engine-local KV block reuse
- ✅ 非文本中间状态传递（prefix identity）
- ❌ 不是 KV tensor export/transfer
- ❌ 不是 cross-engine KV handoff
- ❌ 不是 hidden-state propagation

### 7.2 完成第一版后可宣称

**增量能力：**
- ✅ 优化的 evidence layout（role-agnostic prefix）
- ✅ 增强的 cache-friendly scheduling（aggressive grouping、feedback-driven）
- ✅ 完善的 observability（persistent feedback、counter audit）
- ✅ 完整的 ablation matrix（disabled、perturbed、hostile）
- ✅ 明确的 claim boundary 文档

**仍然不能宣称：**
- ❌ KV tensor export/serialization
- ❌ Cross-engine KV transfer
- ❌ Persistent KV cache（跨重启）
- ❌ Evidence-segment KV composition
- ❌ Cross-model KV sharing

### 7.3 未来可能宣称（如果实施 LMCache adapter）

**条件：** 实施 LMCache integration，运行 cross-engine 实验

**可增加宣称：**
- ✅ External KV reference（LMCacheKVReference）
- ✅ Cross-instance KV reuse
- ✅ Persistent KV cache（可选）

**仍需明确：**
- 这是 optional module，不是主线
- 主线仍是 engine-local prefix control

## 8. 总结

### 8.1 推荐架构回顾

**主方案：强化 vLLM Engine-Local Prefix 路线**
- 核心定义：Engine-Local Prefix Identity + Scheduling Control
- 增量优化：evidence layout、scheduling、observability
- 零新依赖、低风险、openEuler 友好

**Fallback：LMCache Adapter（预留接口）**
- 第一版不实施
- 预留接口以降低未来重构成本

### 8.2 关键设计决策

1. **不引入外部 KV cache service**：当前场景价值有限，部署复杂度高
2. **不修改 vLLM**：依赖 native prefix caching，零侵入
3. **不实施 evidence-segment KV**：实现复杂度极高，第一版风险过大
4. **不支持 cross-model KV**：tensor 不兼容，有价值的是 semantic state 共享

### 8.3 实施优先级

**P0（必须）：**
1. Evidence layout 优化
2. Observability 完善
3. 文档和 claim boundary

**P1（强烈建议）：**
4. Cache-friendly scheduling 增强
5. Benchmark ablation matrix

**P2（可选）：**
6. LMCache adapter 接口预留（不实施）

### 8.4 开始实施前需确认

**技术确认：**
1. ✅ vLLM native prefix caching 已开启（`--enable-prefix-caching`）
2. ✅ vLLM metrics exporter 已部署
3. ✅ 当前 baseline 可稳定复现

**资源确认：**
1. ✅ 单机双 GPU 可用（GPU 0: Qwen3-32B，GPU 1: embedding）
2. ✅ Docker/openEuler 环境可用
3. ✅ 实施时间：10-16 天

**风险确认：**
1. ⚠️ Evidence layout 变更可能影响 prompt 质量 → 需要 quality gate 验证
2. ⚠️ Scheduling 变更可能影响吞吐 → 当前 serialized run，影响有限
3. ✅ 所有变更可通过 feature flag 回滚

**建议行动：**
1. 用户确认推荐架构和实施计划
2. 确认不实施 LMCache adapter（第一版）
3. 确认实施优先级（P0 必须，P1 强烈建议）
4. 开始 WP4（文档）和 WP1（Evidence Layout）

