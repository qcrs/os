## 2. 新增优化方向建议

### 2.1 优化方向 1: Budget-Aware Dynamic Pruning

**技术可行性**: 高

**核心思路**:
结合 KV cache 容量上限，动态调整 evidence pruning threshold。

**当前问题**:
- Evidence pruning threshold 硬编码为 0.6
- 不考虑 KV cache 容量限制
- 可能导致 OOM 或 cache eviction

**优化方案**:
```python
def dynamic_pruning_threshold(
    *,
    available_kv_cache_bytes: int,
    target_sequence_len: int,
    kv_bytes_per_token: int,
    base_threshold: float = 0.6,
) -> float:
    """
    根据 KV cache 容量动态调整 pruning threshold。
    
    逻辑:
    1. 如果 available_kv_cache 足够容纳 target_sequence，使用 base_threshold
    2. 如果 available_kv_cache 不足，提高 threshold（更激进 pruning）
    """
    required_kv_bytes = target_sequence_len * kv_bytes_per_token
    capacity_ratio = available_kv_cache_bytes / required_kv_bytes
    
    if capacity_ratio >= 1.5:
        return base_threshold  # 容量充足，保守 pruning
    elif capacity_ratio >= 1.0:
        return base_threshold + 0.1  # 容量刚好，适度 pruning
    elif capacity_ratio >= 0.7:
        return base_threshold + 0.2  # 容量紧张，激进 pruning
    else:
        return 0.9  # 容量严重不足，极限 pruning
```

**预期收益**:
- Token reduction: +5-10% (在 KV cache 受限场景)
- Quality impact: 需要验证（可能轻微下降）
- Cache hit rate: 提升（避免 eviction）

**实现难度**: 低（2-3 小时）

**实验验证方法**:
1. 模拟不同 KV cache 容量（16GB / 32GB / 64GB）
2. 对比 static threshold vs dynamic threshold
3. 采集指标: pruned_token_count, quality_floor_pass, cache_eviction_count

**优先级**: P1

---

### 2.2 优化方向 2: Multi-Level Prefix Hierarchy

**技术可行性**: 中

**核心思路**:
分层 prefix：system prefix (全局) + corpus prefix (同文档) + task prefix (同任务)。

**当前问题**:
- 只有两层：shared evidence prefix + role suffix
- 不同粒度的复用机会未充分利用

**优化方案**:
```text
Level 0: System Prefix (所有任务共享)
  [SYSTEM_PROMPT + CAPABILITY_DESCRIPTION]
  
Level 1: Corpus Prefix (同文档任务共享)
  [Level 0] + [CORPUS_CONTEXT + EVIDENCE_POOL]
  
Level 2: Task Prefix (同任务不同角色共享)
  [Level 1] + [TASK_OBJECTIVE + CONSTRAINT]
  
Level 3: Role Suffix (角色特定)
  [Level 2] + [ROLE_INSTRUCTION + OUTPUT_SCHEMA]
```

**预期收益**:
- Cache hit rate: +10-20% (更细粒度匹配)
- Prefix reuse opportunities: 从 2 层扩展到 4 层
- TTFT: -15-25% (更高 hit rate)

**实现难度**: 中（1-2 天）
- 需要修改 `compile_prefix_layout` 支持多层
- 需要 registry 追踪每层 hash
- 需要 vLLM 验证多层 prefix 是否正确命中

**实验验证方法**:
1. 构造 3 corpus × 5 tasks × 4 roles = 60 prompts
2. 对比 2-level vs 4-level prefix hit rate
3. 采集指标: per_level_cache_hit_rate, ttft_by_level

**优先级**: P1

---

### 2.3 优化方向 3: Predictive Cache-Affinity Scheduling

**技术可行性**: 中

**核心思路**:
根据历史 cache hit pattern 预测最优任务顺序。

**当前问题**:
- Cache-friendly scheduling 是静态的（同 corpus 连续）
- 不考虑实际 cache eviction policy
- 不学习历史 hit pattern

**优化方案**:
```python
@dataclass
class CacheAffinityScore:
    task_id: str
    corpus_prefix_hash: str
    predicted_hit_probability: float
    predicted_ttft_ms: float
    schedule_priority: float

def predict_cache_affinity(
    *,
    pending_tasks: list[Task],
    cache_history: list[CacheHitRecord],
    current_cache_state: dict[str, float],  # prefix_hash -> residency_score
) -> list[CacheAffinityScore]:
    """
    基于历史 hit pattern 预测每个 task 的 cache affinity。
    
    特征:
    1. corpus_prefix_hash 是否在 current_cache_state
    2. 历史上该 corpus 的平均 hit rate
    3. 该 corpus 的平均 TTFT
    4. 距离上次访问该 corpus 的时间
    """
    scores = []
    for task in pending_tasks:
        corpus_hash = task.corpus_prefix_hash
        
        # 特征 1: 当前 cache 中是否存在
        in_cache = corpus_hash in current_cache_state
        
        # 特征 2: 历史 hit rate
        historical_hits = [
            record for record in cache_history
            if record.corpus_prefix_hash == corpus_hash
        ]
        hit_rate = sum(r.cache_hit for r in historical_hits) / len(historical_hits) if historical_hits else 0.0
        
        # 特征 3: 历史 TTFT
        avg_ttft = sum(r.ttft_ms for r in historical_hits) / len(historical_hits) if historical_hits else 1000.0
        
        # 特征 4: 距离上次访问的时间
        last_access = max((r.timestamp for r in historical_hits), default=0)
        time_since_last_access = time.time() - last_access
        
        # 综合评分（越高越优先）
        priority = (
            (1.0 if in_cache else 0.5) * 0.4 +
            hit_rate * 0.3 +
            (1.0 - avg_ttft / 2000.0) * 0.2 +
            (1.0 - min(time_since_last_access / 600.0, 1.0)) * 0.1
        )
        
        scores.append(CacheAffinityScore(
            task_id=task.task_id,
            corpus_prefix_hash=corpus_hash,
            predicted_hit_probability=hit_rate,
            predicted_ttft_ms=avg_ttft,
            schedule_priority=priority,
        ))
    
    return sorted(scores, key=lambda s: -s.schedule_priority)
```

**预期收益**:
- TTFT: -20-30% (相比随机顺序)
- Cache hit rate: +15-25% (相比静态 corpus grouping)
- Throughput: +10-15% (减少 prefill 等待)

**实现难度**: 中（2-3 天）
- 需要收集 cache history
- 需要实现 affinity scoring 函数
- 需要集成到 runner scheduler

**实验验证方法**:
1. 跑 50+ 轮 continuous tasks
2. 对比 random / static-corpus / predictive scheduling
3. 采集指标: avg_ttft, cache_hit_rate, throughput

**优先级**: P2（需要先有 Phase 3 实验数据才能训练）

---

### 2.4 优化方向 4: Prefix Delta Compression

**技术可行性**: 低（需要 vLLM 定制）

**核心思路**:
不存储完整 prefix KV，只存储 delta（相对于 base prefix）。

**当前问题**:
- 类似任务的 prefix 有大量重复部分
- 全量存储浪费 KV cache 空间

**优化方案**:
```text
Base prefix (存一次):
[SYSTEM_PROMPT + CORPUS_DOC_1 + CORPUS_DOC_2]

Task A prefix (只存 delta):
[Base] + [TASK_A_OBJECTIVE]

Task B prefix (只存 delta):
[Base] + [TASK_B_OBJECTIVE]
```

**预期收益**:
- KV cache 容量: 2-3× (更多并发 sequences)
- Memory bandwidth: -30-40% (减少 KV 读写)

**实现难度**: 高（需要修改 vLLM 内部 KV block manager）

**实验验证方法**:
需要 vLLM fork 或等待官方支持

**优先级**: P3（Future Work，不建议当前实现）

---

### 2.5 优化方向 5: Evidence Deduplication Across Tasks

**技术可行性**: 高

**核心思路**:
识别跨任务重复出现的 evidence chunk，统一编码一次。

**当前问题**:
- 不同任务可能检索到相同 evidence chunk
- 每次都重新编码，浪费 prefill

**优化方案**:
```python
@dataclass
class EvidenceChunkFingerprint:
    chunk_id: str
    content_hash: str
    first_encoded_task_id: str
    reuse_count: int
    estimated_tokens: int

class EvidenceDeduplicationRegistry:
    def __init__(self):
        self.fingerprints: dict[str, EvidenceChunkFingerprint] = {}
    
    def register_chunk(self, chunk_id: str, content_hash: str, task_id: str, tokens: int):
        if content_hash in self.fingerprints:
            fp = self.fingerprints[content_hash]
            fp.reuse_count += 1
        else:
            self.fingerprints[content_hash] = EvidenceChunkFingerprint(
                chunk_id=chunk_id,
                content_hash=content_hash,
                first_encoded_task_id=task_id,
                reuse_count=1,
                estimated_tokens=tokens,
            )
    
    def get_deduplication_savings(self) -> int:
        return sum(
            fp.estimated_tokens * max(fp.reuse_count - 1, 0)
            for fp in self.fingerprints.values()
        )
```

**预期收益**:
- Prefill tokens: -10-20% (在 evidence 重复率高的场景)
- TTFT: -5-15%

**实现难度**: 低（1 天）

**实验验证方法**:
1. 跑 20+ 任务，统计 evidence content_hash 重复率
2. 对比 with/without deduplication 的 prefill token count
3. 采集指标: evidence_reuse_rate, prefill_tokens_saved

**优先级**: P2

---

### 2.6 推荐实施路线

| 优化方向 | 优先级 | 预期收益 | 实现难度 | 推荐时机 |
|---------|--------|---------|---------|---------|
| Budget-Aware Dynamic Pruning | P1 | 中 | 低 | Phase 2 代码增强 |
| Multi-Level Prefix Hierarchy | P1 | 高 | 中 | Phase 2 代码增强 |
| Evidence Deduplication | P2 | 中 | 低 | Phase 3 实验后（如果 evidence 重复率 >20%） |
| Predictive Scheduling | P2 | 高 | 中 | Phase 3 实验后（需要 cache history 数据） |
| Prefix Delta Compression | P3 | 高 | 高 | Future Work（需要 vLLM 定制） |

**Phase 2 立即实施**: P1 项（Budget-Aware Pruning + Multi-Level Prefix）

**Phase 3 根据实验数据决定**: P2 项（Evidence Dedup + Predictive Scheduling）

**不建议实施**: P3 项（Prefix Delta Compression，工程复杂度太高）

