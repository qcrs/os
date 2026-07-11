# 第二部分：创新点深化方案

## 1. 当前创新点评估

### 1.1 创新点对比分析

#### 创新点 1: Prefix Layout Compiler

**核心思路**:
将多 Agent prompt 编译成稳定共享前缀和角色后缀两段：
```text
[SYSTEM + STATIC CORPUS/EVIDENCE PREFIX] + [ROLE-SPECIFIC SUFFIX]
```

**与学术/工业界方案对比**:

| 方案 | 相似点 | 差异点 | 新颖性评分 |
|------|--------|--------|-----------|
| vLLM APC | 都利用 prefix cache | StateBus **主动构造** token-level 相同前缀，vLLM 只是**被动命中** | 4/5 |
| Prompt compression (LongLLMLingua) | 都减少 token | Compression 损失语义，Prefix Layout 保持完整证据 | 3/5 |
| OpenAI batch API prefix | 都复用 system prompt | StateBus 扩展到 corpus evidence，不只是 system | 4/5 |

**技术难度**: 中（需要 prompt 构造合同和去重逻辑）

**实现完成度**: 85%
- ✅ Shared prefix 编译逻辑
- ✅ Role suffix 去重
- ⚠️ 默认关闭，需要显式启用

**新颖性评分**: 4/5
- **优势**: Multi-agent 场景下主动对齐 prefix，控制面清晰
- **局限**: 依赖 same evidence selection，如果 Retriever 给不同角色返回不同证据则失效

#### 创新点 2: Corpus-Aware KV Scheduling

**核心思路**:
基于 `corpus_prefix_hash` 把同 corpus 任务排在同一时间窗口：
```text
优: ACME-1 → ACME-2 → ACME-3 → BETA-1
弱: ACME-1 → BETA-1 → ACME-2
```

**与学术/工业界方案对比**:

| 方案 | 相似点 | 差异点 | 新颖性评分 |
|------|--------|--------|-----------|
| vLLM continuous batching | 都调度请求 | vLLM 按到达顺序，StateBus 按 corpus affinity | 4/5 |
| LLM serving scheduler (Orca) | 都优化 cache hit | Orca 优化 GPU 利用率，StateBus 优化 prefix reuse | 3/5 |
| RAG pipeline scheduling | 都处理文档相关性 | StateBus 在 agent runtime 层面调度，不只是 retrieval | 4/5 |

**技术难度**: 中（需要 corpus identity 追踪和 schedule plan 生成）

**实现完成度**: 80%
- ✅ Corpus prefix hash 计算
- ✅ Cache-friendly / cache-hostile schedule plan 生成
- ⚠️ 未接入 runner 自动调度

**新颖性评分**: 4/5
- **优势**: 把 multi-agent runtime 调度和 LLM engine cache 驻留关联起来
- **局限**: 需要任务提前已知，不适合在线实时请求

#### 创新点 3: Prefix-Preserving Evidence Pruning

**核心思路**:
`EvidencePruningHint` 不只做 relevance pruning，还要区分是否适合进入 shared prefix。

**与学术/工业界方案对比**:

| 方案 | 相似点 | 差异点 | 新颖性评分 |
|------|--------|--------|-----------|
| SnapKV | 都减少 KV | SnapKV 在**模型内部**剪枝，StateBus 在**输入层**压缩 | 3/5 |
| H2O (Heavy-Hitter Oracle) | 都选择重要 token | H2O 基于 attention score，StateBus 基于 embedding similarity | 3/5 |
| LongLLMLingua | 都压缩 context | LongLLMLingua 语义损失，StateBus 保持原文 | 3/5 |

**技术难度**: 低（主要是 importance scoring 和 threshold）

**实现完成度**: 70%
- ✅ EvidencePruningHint 数据结构
- ✅ Importance score 计算
- ⚠️ 未接入 benchmark
- ❌ Threshold 硬编码，无动态调整

**新颖性评分**: 3/5
- **优势**: Input-level 压缩，不修改 engine，KV 等价
- **局限**: 需要高质量 embedding，否则 pruning 损失质量

#### 创新点 4: Neural Prefix Lease

**核心思路**:
`NeuralStateHandle` 记录 prefix 在哪个 engine/model/tokenizer/session 下可复用。

**与学术/工业界方案对比**:

| 方案 | 相似点 | 差异点 | 新颖性评分 |
|------|--------|--------|-----------|
| Ray Plasma object store | 都追踪对象生命周期 | Plasma 持有对象本身，StateBus 只记录 control-plane metadata | 3/5 |
| Distributed cache (Redis) | 都记录 cache 状态 | Redis 是通用 KV store，StateBus 专门为 LLM prefix 设计 | 3/5 |
| vLLM 内部 KV block manager | 都管理 KV 生命周期 | vLLM 在 engine 内部，StateBus 在 runtime 外部提供控制面 | 4/5 |

**技术难度**: 中（需要 registry 逻辑和生命周期字段设计）

**实现完成度**: 90%
- ✅ NeuralStateHandle 数据结构
- ✅ EngineLocalPrefixRegistry ensure_handle / lookup
- ✅ Control-plane 字段（cache_hit_count, eviction_risk, schedule_priority）
- ⚠️ Eviction_risk 和 schedule_priority 未实际使用

**新颖性评分**: 4/5
- **优势**: 给调度器提供 cache 控制面视图，不暴露 KV tensor
- **局限**: 只记录 lease，不能强制 eviction

#### 创新点 5: ReplayClass × KV Reuse Pyramid

**核心思路**:
统一 StateBus replay 分层和 KV prefill 成本：
- `exact_replay`: 跳过 LLM，KV 成本 ≈ 0
- `validated_replay`: 复用 corpus prefix，只重算 task suffix
- `assist`: 复用 system prefix
- `cold_start`: 全量 prefill

**与学术/工业界方案对比**:

| 方案 | 相似点 | 差异点 | 新颖性评分 |
|------|--------|--------|-----------|
| Semantic cache (GPTCache) | 都复用历史结果 | GPTCache 是结果 cache，StateBus 结合 prefix reuse 和 memory replay | 4/5 |
| Function calling cache | 都跳过计算 | Function cache 是应用层，StateBus 统一到 KV prefill 层 | 3/5 |
| vLLM speculative decoding | 都复用前缀 | Speculative decoding 预测 token，StateBus 预测整个 task 可复用 | 3/5 |

**技术难度**: 低（主要是概念映射）

**实现完成度**: 95%
- ✅ ReplayClass 定义（exact, validated, assist, cold_start）
- ✅ KV 理论分层映射
- ✅ 写入 kv_analysis report

**新颖性评分**: 4/5
- **优势**: 统一记忆复用和 KV 成本，形成完整的优化金字塔
- **局限**: 理论模型，需要实测 vLLM 验证

### 1.2 创新点新颖性总结

| 创新点 | 新颖性 | 技术难度 | 完成度 | 优先级 |
|--------|--------|---------|--------|--------|
| Prefix Layout Compiler | 4/5 | 中 | 85% | P0（核心机制） |
| Corpus-Aware Scheduling | 4/5 | 中 | 80% | P1（增强调度） |
| Evidence Pruning | 3/5 | 低 | 70% | P2（可选优化） |
| Neural Prefix Lease | 4/5 | 中 | 90% | P1（控制面） |
| ReplayClass × KV Pyramid | 4/5 | 低 | 95% | P0（理论框架） |

**总体新颖性评估**: 3.8/5

**与 vLLM APC 的核心差异**:
- vLLM APC: Engine 内部被动命中
- StateBus KV: Runtime 外部主动规划（prefix alignment + corpus scheduling + lease tracking）

**与 SnapKV / ChunkKV 的核心差异**:
- SnapKV / ChunkKV: 模型内部 KV 剪枝（修改 attention）
- StateBus KV: Input-level 等价压缩（不修改 engine）

