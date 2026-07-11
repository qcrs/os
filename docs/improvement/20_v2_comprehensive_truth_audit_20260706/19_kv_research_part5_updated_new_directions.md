## 2. 新增优化方向建议 - 详细实现计划与决策

### 2.1 优化方向 1: Budget-Aware Dynamic Pruning

**决策**: ✅ **Phase 2 立即实施**

**技术可行性**: 高

**核心思路**:
结合 KV cache 容量上限，动态调整 evidence pruning threshold。

#### 详细实现计划

**Step 1: 扩展 EvidencePruningHint 数据结构**（30分钟）

文件：`v2/retrieval/models.py`

```python
@dataclass
class EvidencePruningHint:
    chunk_id: str
    importance_score: float
    keep_in_budget: bool
    estimated_tokens: int
    # 新增字段
    available_kv_cache_bytes: int = 0
    kv_bytes_per_token: int = 0
    dynamic_threshold: float = 0.6
```

**Step 2: 实现动态阈值计算函数**（1小时）

文件：`v2/retrieval/pruning.py`（新建）

```python
def compute_dynamic_pruning_threshold(
    *,
    available_kv_cache_bytes: int,
    target_sequence_len: int,
    kv_bytes_per_token: int,
    base_threshold: float = 0.6,
    capacity_buffer: float = 0.2,
) -> float:
    """
    根据 KV cache 容量动态调整 pruning threshold。
    
    Args:
        available_kv_cache_bytes: 可用 KV cache 容量（字节）
        target_sequence_len: 目标序列长度（token）
        kv_bytes_per_token: 每个 token 的 KV 字节数
        base_threshold: 基础阈值（容量充足时使用）
        capacity_buffer: 容量 buffer（预留 20%）
    
    Returns:
        动态计算的 pruning threshold
    """
    required_kv_bytes = target_sequence_len * kv_bytes_per_token
    safe_capacity = available_kv_cache_bytes * (1 - capacity_buffer)
    capacity_ratio = safe_capacity / required_kv_bytes if required_kv_bytes > 0 else 2.0
    
    # 容量充足：保守 pruning
    if capacity_ratio >= 1.5:
        return base_threshold
    # 容量刚好：适度 pruning
    elif capacity_ratio >= 1.0:
        return base_threshold + 0.1
    # 容量紧张：激进 pruning
    elif capacity_ratio >= 0.7:
        return base_threshold + 0.2
    # 容量严重不足：极限 pruning
    else:
        return 0.9

def apply_dynamic_pruning(
    chunks: list[EvidenceChunk],
    *,
    available_kv_cache_bytes: int,
    kv_bytes_per_token: int,
    base_threshold: float = 0.6,
) -> tuple[list[EvidenceChunk], dict]:
    """
    应用动态 pruning，返回保留的 chunks 和统计信息。
    """
    total_tokens = sum(chunk.estimated_tokens for chunk in chunks)
    dynamic_threshold = compute_dynamic_pruning_threshold(
        available_kv_cache_bytes=available_kv_cache_bytes,
        target_sequence_len=total_tokens,
        kv_bytes_per_token=kv_bytes_per_token,
        base_threshold=base_threshold,
    )
    
    kept_chunks = [
        chunk for chunk in chunks
        if chunk.importance_score >= dynamic_threshold
    ]
    pruned_chunks = [
        chunk for chunk in chunks
        if chunk.importance_score < dynamic_threshold
    ]
    
    stats = {
        "dynamic_threshold": dynamic_threshold,
        "base_threshold": base_threshold,
        "total_chunks": len(chunks),
        "kept_chunks": len(kept_chunks),
        "pruned_chunks": len(pruned_chunks),
        "kept_tokens": sum(c.estimated_tokens for c in kept_chunks),
        "pruned_tokens": sum(c.estimated_tokens for c in pruned_chunks),
        "capacity_ratio": available_kv_cache_bytes / (total_tokens * kv_bytes_per_token),
    }
    
    return kept_chunks, stats
```

**Step 3: 集成到 Retriever Pipeline**（1小时）

文件：`v2/retrieval/pipeline.py`

```python
class RetrievalPipeline:
    def __init__(self, kv_budget_config: dict | None = None):
        self.kv_budget_config = kv_budget_config or {}
        self.enable_dynamic_pruning = self.kv_budget_config.get("enable_dynamic_pruning", False)
    
    def retrieve_and_prune(
        self,
        query: str,
        corpus: list[Document],
        top_k: int = 20,
    ) -> tuple[list[EvidenceChunk], dict]:
        # 检索
        chunks = self._retrieve(query, corpus, top_k)
        
        # 动态 pruning（如果启用）
        if self.enable_dynamic_pruning:
            available_kv = self.kv_budget_config.get("available_kv_cache_bytes", 8 * 1024**3)  # 默认 8GB
            kv_per_token = self.kv_budget_config.get("kv_bytes_per_token", 256)
            base_threshold = self.kv_budget_config.get("base_threshold", 0.6)
            
            chunks, pruning_stats = apply_dynamic_pruning(
                chunks,
                available_kv_cache_bytes=available_kv,
                kv_bytes_per_token=kv_per_token,
                base_threshold=base_threshold,
            )
            return chunks, pruning_stats
        
        return chunks, {}
```

**Step 4: 配置文件支持**（30分钟）

文件：`deploy/statebus_llm.yaml.local`

```yaml
kv_optimization:
  evidence_pruning:
    enabled: false  # 默认关闭
    mode: dynamic   # static | dynamic
    base_threshold: 0.6
    available_kv_cache_bytes: 8589934592  # 8 GB
    kv_bytes_per_token: 256  # Qwen3-32B fp16
```

**Step 5: 单元测试**（1小时）

文件：`tests/v2/test_dynamic_pruning.py`

```python
def test_dynamic_threshold_sufficient_capacity():
    threshold = compute_dynamic_pruning_threshold(
        available_kv_cache_bytes=16 * 1024**3,  # 16 GB
        target_sequence_len=4096,
        kv_bytes_per_token=256,
        base_threshold=0.6,
    )
    assert threshold == 0.6  # 容量充足，使用 base

def test_dynamic_threshold_tight_capacity():
    threshold = compute_dynamic_pruning_threshold(
        available_kv_cache_bytes=2 * 1024**3,  # 2 GB
        target_sequence_len=8192,
        kv_bytes_per_token=256,
        base_threshold=0.6,
    )
    assert threshold > 0.6  # 容量紧张，提高阈值
```

#### 实验验证方案

**对比实验**:
- Baseline: 静态 threshold 0.6
- Treatment: 动态 threshold（容量 4GB / 8GB / 16GB）

**预期结果**:
- 4GB 容量: threshold 提升到 0.8，pruned tokens +30%，质量保持
- 8GB 容量: threshold 保持 0.6
- 16GB 容量: threshold 保持 0.6

**实施时间**: Phase 2 Day 3-4（4小时）

---

### 2.2 优化方向 2: Multi-Level Prefix Hierarchy

**决策**: ⚠️ **Phase 2 可选实施（如果时间允许）**

**技术可行性**: 中

**核心思路**:
分层 prefix：system (全局) + corpus (同文档) + task (同任务) + role (角色)。

#### 详细实现计划

**Step 1: 扩展 PrefixLayoutPlan 支持多层**（2小时）

文件：`v2/runtime/role_path.py`

```python
@dataclass(frozen=True)
class MultiLevelPrefixLayout:
    level0_system_prefix: str = ""
    level0_hash: str = ""
    level0_bytes: int = 0
    
    level1_corpus_prefix: str = ""
    level1_hash: str = ""
    level1_bytes: int = 0
    
    level2_task_prefix: str = ""
    level2_hash: str = ""
    level2_bytes: int = 0
    
    level3_role_suffix: str = ""
    level3_hash: str = ""
    level3_bytes: int = 0
    
    full_prompt: str = ""
    full_prompt_hash: str = ""
    full_prompt_bytes: int = 0

def compile_multi_level_prefix(
    *,
    system_prompt: str,
    corpus_context: str,
    task_objective: str,
    role_instruction: str,
) -> MultiLevelPrefixLayout:
    level0 = system_prompt
    level1 = f"{level0}\n\n{corpus_context}"
    level2 = f"{level1}\n\n{task_objective}"
    level3 = f"{level2}\n\n{role_instruction}"
    
    return MultiLevelPrefixLayout(
        level0_system_prefix=level0,
        level0_hash=sha256_digest(level0),
        level0_bytes=len(level0.encode("utf-8")),
        
        level1_corpus_prefix=corpus_context,
        level1_hash=sha256_digest(level1),
        level1_bytes=len(level1.encode("utf-8")),
        
        level2_task_prefix=task_objective,
        level2_hash=sha256_digest(level2),
        level2_bytes=len(level2.encode("utf-8")),
        
        level3_role_suffix=role_instruction,
        level3_hash=sha256_digest(level3),
        level3_bytes=len(level3.encode("utf-8")),
        
        full_prompt=level3,
        full_prompt_hash=sha256_digest(level3),
        full_prompt_bytes=len(level3.encode("utf-8")),
    )
```

**Step 2: 扩展 NeuralStateHandle 追踪多层**（1小时）

文件：`v2/runtime/neural_state.py`

```python
@dataclass(frozen=True)
class MultiLevelPrefixHandle:
    level0_hash: str
    level1_hash: str
    level2_hash: str
    level3_hash: str
    cache_hit_by_level: dict[int, int] = field(default_factory=dict)  # {0: 5, 1: 3, 2: 1}
```

**Step 3: vLLM 验证多层 prefix 是否正确命中**（实验阶段）

**问题**: vLLM APC 是否支持部分前缀匹配？

**验证实验**:
```python
# Prompt A: [L0] + [L1] + [L2a] + [R1]
# Prompt B: [L0] + [L1] + [L2b] + [R2]
# 
# 预期: L0 + L1 部分可以命中
# 需要验证: vLLM 是否真的只 prefill L2b + R2
```

**风险**: 如果 vLLM 不支持部分匹配，多层架构无效

#### 实施决策

**条件性实施**: 仅当以下条件满足时才实施
1. Phase 2 时间充足（预算内完成 P1 债务和优化方向1）
2. vLLM 验证实验证明部分前缀匹配有效

**否则**: 推迟到 Future Work

**实施时间**: Phase 2 Day 4-5（3-4小时，可选）

---

### 2.3 优化方向 3: Predictive Cache-Affinity Scheduling

**决策**: ❌ **Phase 3 之后才决定（需要先有实验数据）**

**技术可行性**: 中

**理由**:
- 需要收集 cache history 数据
- 需要 Phase 3 实验完成后才能训练预测模型
- 收益不确定（静态 corpus scheduling 可能已经足够）

#### 推迟实施的条件

仅当以下条件满足时才考虑实施：
1. Phase 3 实验证明静态 corpus scheduling 收益有限（<10% hit rate 提升）
2. Cache history 数据显示明显的 temporal pattern
3. 有额外时间预算（Phase 4 之后）

**否则**: 记录为 Future Work

---

### 2.4 优化方向 4: Prefix Delta Compression

**决策**: ❌ **不实施（需要 vLLM 定制，工程复杂度过高）**

**技术可行性**: 低（需要修改 vLLM 内部）

**理由**:
1. **工程复杂度高**: 需要 fork vLLM，修改 KV block manager
2. **维护成本高**: vLLM 升级时需要重新 merge
3. **收益不确定**: 需要先验证 delta compression 的实际压缩率
4. **时间不足**: 7-12 天预算无法完成

#### 推荐替代方案

**不修改 vLLM，改为优化输入侧**:
- Evidence Deduplication (方向5)
- Dynamic Pruning (方向1)

**Future Work**: 如果后续有长期投入，可以考虑与 vLLM 社区合作

---

### 2.5 优化方向 5: Evidence Deduplication Across Tasks

**决策**: ⚠️ **Phase 3 根据实验数据决定**

**技术可行性**: 高

**核心思路**:
识别跨任务重复出现的 evidence chunk，统一编码一次。

#### 详细实现计划

**Step 1: 实现 EvidenceDeduplicationRegistry**（1小时）

文件：`v2/retrieval/deduplication.py`（新建）

```python
@dataclass
class EvidenceChunkFingerprint:
    chunk_id: str
    content_hash: str
    first_encoded_task_id: str
    reuse_count: int
    estimated_tokens: int
    first_seen_timestamp: float

class EvidenceDeduplicationRegistry:
    def __init__(self):
        self.fingerprints: dict[str, EvidenceChunkFingerprint] = {}
        self.total_saved_tokens: int = 0
    
    def register_chunk(
        self,
        chunk_id: str,
        content_hash: str,
        task_id: str,
        tokens: int,
        timestamp: float,
    ) -> tuple[bool, int]:
        """
        注册 evidence chunk。
        
        Returns:
            (is_duplicate, saved_tokens)
        """
        if content_hash in self.fingerprints:
            fp = self.fingerprints[content_hash]
            fp.reuse_count += 1
            self.total_saved_tokens += tokens
            return True, tokens
        else:
            self.fingerprints[content_hash] = EvidenceChunkFingerprint(
                chunk_id=chunk_id,
                content_hash=content_hash,
                first_encoded_task_id=task_id,
                reuse_count=1,
                estimated_tokens=tokens,
                first_seen_timestamp=timestamp,
            )
            return False, 0
    
    def get_deduplication_stats(self) -> dict:
        return {
            "unique_chunks": len(self.fingerprints),
            "total_reuse_count": sum(fp.reuse_count - 1 for fp in self.fingerprints.values()),
            "total_saved_tokens": self.total_saved_tokens,
            "deduplication_rate": self.total_saved_tokens / sum(fp.estimated_tokens for fp in self.fingerprints.values()) if self.fingerprints else 0.0,
        }
```

**Step 2: 集成到 continuous runner**（1小时）

文件：`v2/benchmark/continuous_runner.py`

```python
class ContinuousRunner:
    def __init__(self):
        self.evidence_dedup_registry = EvidenceDeduplicationRegistry()
    
    def run_round(self, task_spec: CanonicalTaskSpec):
        # 检索 evidence
        evidence_chunks = self.retriever.retrieve(task_spec.query)
        
        # 去重统计
        for chunk in evidence_chunks:
            is_dup, saved_tokens = self.evidence_dedup_registry.register_chunk(
                chunk_id=chunk.chunk_id,
                content_hash=chunk.content_hash,
                task_id=task_spec.task_id,
                tokens=chunk.estimated_tokens,
                timestamp=time.time(),
            )
            if is_dup:
                print(f"Evidence chunk {chunk.chunk_id} is duplicate, saved {saved_tokens} tokens")
```

**Step 3: 实验验证**（Phase 3 期间）

**数据收集**: 在 Phase 3 实验中收集 evidence 重复率统计

**判断标准**:
- 如果 evidence 重复率 > 20%，实施 deduplication
- 如果 evidence 重复率 < 10%，不实施（收益有限）

#### 实施决策

**条件性实施**: Phase 3 实验后根据数据决定
- ✅ 实施: evidence 重复率 > 20%
- ❌ 不实施: evidence 重复率 < 10%

**实施时间**: Phase 3 实验期间收集数据，Phase 4 根据数据决定是否实施（2小时）

---

### 2.6 最终实施优先级和时间分配

| 优化方向 | 决策 | 实施时机 | 预计工作量 | 条件 |
|---------|------|---------|-----------|------|
| 1. Budget-Aware Pruning | ✅ **立即实施** | Phase 2 Day 3-4 | 4 小时 | 无条件 |
| 2. Multi-Level Prefix | ⚠️ **可选** | Phase 2 Day 4-5 | 3-4 小时 | 时间允许 + vLLM 验证 |
| 3. Predictive Scheduling | ❌ **推迟** | Phase 3 之后 | - | 需要实验数据 |
| 4. Prefix Delta Compression | ❌ **不做** | - | - | 工程复杂度过高 |
| 5. Evidence Deduplication | ⚠️ **数据驱动** | Phase 4 | 2 小时 | 重复率 > 20% |

**Phase 2 必做**: 优化方向 1（4小时）

**Phase 2 可选**: 优化方向 2（如果时间充足且 vLLM 验证通过）

**Phase 3-4 数据驱动**: 优化方向 5（如果重复率高）

**不做**: 优化方向 3、4

