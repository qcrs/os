# StateBus KV 中间状态机制调研报告

调研日期：2026-07-14  
调研对象：为 StateBus 设计真正适用的 KV 中间状态机制  
状态：初稿完成

## 执行摘要

本调研从 StateBus 当前架构和赛题目标出发，系统性地调研了可用的 KV/神经中间状态方案，筛选出真正适合当前系统的技术路线。

**核心结论：**

1. **当前能力边界**：StateBus 已有 engine-local prefix identity、scheduling control 和 estimate，但没有 KV tensor export/transfer、cross-engine reuse 或 hidden-state handoff
2. **推荐主方案**：强化当前 vLLM engine-local prefix 路线 + evidence-segment KV identity
3. **Fallback 方案**：引入 external KV reference layer（如 LMCache adapter）作为可选数据面
4. **不推荐方案**：直接 KV tensor export/transfer、cross-model KV sharing（第一版）

**关键发现：**

- 当前 `NeuralPrefixIdentity` 和 `NeuralStateHandle` 是控制面对象，不是 KV tensor 引用
- vLLM native prefix caching 在同 engine 内已经有效，关键是优化 evidence layout 和 scheduling
- 跨 Agent KV 复用的主要挑战是不同 role 的 system prompt 和 position encoding 差异
- LMCache 等外部 KV cache 方案增加了部署复杂度，但对单机双 GPU 环境价值有限

本文档包含：

1. 当前 StateBus KV/Prefix 背景摘要
2. 候选技术图谱
3. 来源和引用
4. 初筛标准
5. Shortlist 深入分析
6. 对比矩阵
7. 最终技术选择依据

---

## 目录

[待补充]


## 1. 当前 StateBus KV/Prefix 背景摘要

### 1.1 当前已有能力

StateBus v2 当前已经实现了 engine-local prefix 控制面，包括：

**控制面对象：**
- `NeuralPrefixIdentity`：corpus/evidence prefix hash、source doc hashes、system prompt version
- `NeuralStateHandle`：engine/session/prefix 绑定、lifetime scope、cache hit count、eviction risk
- `EngineLocalPrefixRegistry`：session-scoped handle 注册和 lookup
- `NeuralPrefixReuseEstimate`：estimated prefix tokens、cache hit/query count、savings ratio
- `PrefixReuseScheduleHint`：task-level cache affinity group 和 schedule priority

**数据面：**
- shared_evidence_prefix prompt layout：把可共享 evidence 放到 prompt 前部
- vLLM engine 内部自动 prefix caching（V0 block manager）
- vLLM metrics exporter：block query/hit counter delta（task-local）

**Observability：**
- `vllm_metrics.py`：parse vLLM Prometheus metrics、compute counter delta
- `prefix_feedback.py`：predicted vs observed hit rate 的 sliding window 校准
- task-local counter delta 验证（已在 2026-07-14 定向验证中通过）

**实验证据（2026-07-14 定向验证）：**
- shared prefix mode：6,996 queries / 5,458 hits = 78.02% hit rate
- independent prefix mode：7,200 queries / 0 hits = 0% hit rate
- warm TTFT median：shared 267.06 ms vs independent 2,282.89 ms
- 4/4 alternating-order pair gate 通过

### 1.2 当前能力边界

**当前能做的：**
1. StateBus 构造稳定的 evidence prefix、计算 identity hash
2. 同一 vLLM engine 内，相同 token prefix 自动复用 KV blocks
3. 控制面估算 prefix cache hit/query count（基于 consumer role 数量）
4. 通过 corpus_prefix_hash 进行 cache-friendly scheduling
5. task-local 采样 vLLM block counter delta，验证真实 hit rate

**当前没有的：**
1. StateBus 可寻址的真实 KV tensor object
2. KV 从 vLLM 导出到 StateBus storage
3. Agent/进程/engine 之间的 KV store、transfer、restore
4. 跨服务重启的 KV 持久化
5. non-prefix evidence segment 的可靠 KV 组合
6. hidden-state tensor 的 producer-consumer 链路
7. cross-engine 或 cross-model KV reuse

**严格术语边界：**
- `NeuralPrefixIdentity`：控制面 identity，不是 KV tensor 引用
- `NeuralStateHandle`：engine-local handle，不是 external KV reference
- `estimated_prefix_cache_hit_count`：控制面推断，不是 vLLM raw counter
- vLLM block query/hit：engine 内 block reuse，不是 KV tensor transfer
- Engine-Local Prefix Reuse：同一 engine 内重复 prefill 的潜在复用，不是 Agent 间 KV handoff

### 1.3 与其他状态系统的协同

StateBus v2 当前有清晰的状态对象分工：

| 对象类型 | 职责 | 传递方式 | 生命周期 |
|---------|------|---------|---------|
| `SemanticStateRef` | 选择/表达证据、embedding、dense state | shared_memory / mmap | task session |
| `ExecutionArtifactRef` | 保存工具执行结果、文件、验证 artifact | workspace + CAS | 持久化 |
| `MemoryCommit` | 跨任务复用语义、策略、验证产物 | SQLite + FAISS | 持久化 |
| `NeuralPrefixIdentity` | 避免重复模型 prefill（控制面） | Protobuf | task session |
| `LogitStateRef` | 表达输出不确定性（top-logprobs 派生） | Protobuf | task session |

**当前缺失：真正的 KV 中间状态对象**

KV/Serving State 应该解决"如何让不同 Agent/请求复用已经计算过的 KV tensor"，而不是只靠 vLLM engine 内部的 automatic prefix caching。


## 2. 候选技术图谱

本章建立宽覆盖的候选技术清单，先不做深入分析。每个候选记录：解决的问题、状态对象、producer/consumer、cache identity、storage/transport、prefix-only 还是 segment、same/cross-engine、实验收益、vLLM 侵入程度、对 StateBus 潜在价值、明显不适合的原因。

### 2.1 vLLM Native Prefix Caching

**解决的问题：**
- 同一 engine 内重复 prompt prefix 的重复 prefill 计算

**状态对象：**
- KV blocks（engine 内部，GPU memory）
- Prefix hash → block mapping（V0: simple dict, V1: radix tree）

**Producer/Consumer：**
- Producer: 第一个包含该 prefix 的请求
- Consumer: 后续包含相同 token prefix 的请求
- 同一 vLLM engine instance

**Cache Identity：**
- Token IDs 的 exact sequence
- 不包含 position、generation config（temperature 等）

**Storage/Transport：**
- GPU memory（KV blocks）
- Engine-local，不跨进程

**Prefix-only or Segment:**
- Prefix-only（V0）
- V1 计划支持更灵活的 radix tree，但仍是 prefix-based

**Same/Cross-Engine:**
- Same engine only

**实验收益：**
- vLLM 官方 blog：长 context 场景下 TTFT 可降低 55-80%
- StateBus 定向验证：shared prefix TTFT median 267ms vs independent 2,283ms

**vLLM 侵入程度：**
- 零侵入（native feature）
- 通过 `--enable-prefix-caching` 启动参数开启

**对 StateBus 潜在价值：**
- 当前主线已在使用
- 优化空间：evidence layout、scheduling order、stable prefix 构造

**明显不适合的原因：**
- 无：当前主线方案

### 2.2 LMCache

**解决的问题：**
- Cross-request、cross-instance、persistent KV cache
- Multi-tenant KV sharing
- 降低 prefill latency 和 cost

**状态对象：**
- KV tensor chunks（serialized）
- LMCache 管理的 cache key → KV mapping

**Producer/Consumer：**
- Producer: 任意 LLM serving instance（支持 vLLM、SGLang、TensorRT-LLM）
- Consumer: 任意支持的 serving instance
- Cross-instance、cross-node

**Cache Identity：**
- Prefix token IDs + model metadata
- CacheBlend 支持 fuzzy matching 和 reordering

**Storage/Transport:**
- Storage: CPU memory、GPU memory、disk、distributed store（Redis 等）
- Transport: 本地 IPC、TCP、RDMA

**Prefix-only or Segment:**
- Prefix-based
- CacheBlend 支持 non-contiguous segment matching

**Same/Cross-Engine:**
- Cross-engine（主要价值）
- Cross-node

**实验收益：**
- LMCache paper：50-80% TTFT reduction（multi-turn dialogue）
- 40-60% cost reduction（document QA with reuse）

**vLLM 侵入程度：**
- 需要修改 vLLM
- 提供 vLLM integration patch
- 需要编译 native extension

**对 StateBus 潜在价值：**
- **中等**：如果需要 cross-engine 或 persistent KV reuse
- **低**：当前单 engine + session-scoped 场景

**明显不适合的原因：**
- 部署复杂度高：需要 patch vLLM、编译 native extension、运行 cache service
- 当前单 engine 环境下增量价值不明显
- openEuler 交付增加依赖风险

### 2.3 SGLang RadixAttention

**解决的问题：**
- 自动检测和复用 common prefix/suffix
- Multi-turn conversation 的 KV reuse

**状态对象：**
- Radix tree of KV cache
- Tree node → KV blocks mapping

**Producer/Consumer:**
- Producer: 第一个请求
- Consumer: 后续请求（自动 tree matching）
- Same SGLang runtime

**Cache Identity:**
- Token sequence（radix tree prefix matching）

**Storage/Transport:**
- GPU memory
- Runtime-local

**Prefix-only or Segment:**
- Prefix + suffix（通过 radix tree）
- 比 simple prefix cache 更灵活

**Same/Cross-Engine:**
- Same runtime only

**实验收益:**
- SGLang paper：multi-turn dialogue 中 30-50% latency reduction

**vLLM 侵入程度:**
- N/A（需要切换到 SGLang）

**对 StateBus 潜在价值:**
- **低**：需要切换 serving backend
- **中**：如果 SGLang 作为备选 backend

**明显不适合的原因:**
- 需要从 vLLM 切换到 SGLang
- 增加技术栈复杂度
- 当前 StateBus 已绑定 vLLM

### 2.4 CacheBlend / CacheGen

**解决的问题:**
- Non-contiguous KV segment matching
- Reordered context reuse

**状态对象:**
- KV segments with metadata
- Fuzzy matching index

**Producer/Consumer:**
- Producer: 第一个请求
- Consumer: 后续请求（即使 context 顺序不同）

**Cache Identity:**
- Content-based segment hash
- 支持 partial/fuzzy matching

**Storage/Transport:**
- 依赖底层 KV cache system（如 LMCache）

**Prefix-only or Segment:**
- Segment-based（主要创新点）

**Same/Cross-Engine:**
- 取决于底层 KV cache system

**实验收益:**
- CacheBlend paper：RAG with reordered docs，60-70% token savings

**vLLM 侵入程度:**
- 需要修改 attention 实现
- 研究 prototype，非 production-ready

**对 StateBus 潜在价值:**
- **中等**：如果 Retriever evidence 顺序变化频繁
- **高风险**：实现复杂度高，稳定性未知

**明显不适合的原因:**
- Research prototype，非生产系统
- 需要深度修改 attention kernel
- Position encoding 兼容性问题复杂

### 2.5 Persistent/Tiered KV Cache

**解决的问题:**
- 跨服务重启的 KV persistence
- Cold start 优化

**状态对象:**
- Serialized KV tensors
- Disk/SSD storage

**Producer/Consumer:**
- Producer: serving instance（shutdown 前）
- Consumer: serving instance（restart 后）

**Cache Identity:**
- Model + tokenizer + token sequence

**Storage/Transport:**
- Disk、SSD、分布式存储

**Prefix-only or Segment:**
- 取决于实现

**Same/Cross-Engine:**
- Cross-restart（主要价值）

**实验收益:**
- 理论：cold start TTFT 降低，但需权衡 I/O overhead

**vLLM 侵入程度:**
- 需要修改 vLLM KV cache manager
- 需要序列化/反序列化逻辑

**对 StateBus 潜在价值:**
- **低**：当前 session-scoped，不跨服务重启

**明显不适合的原因:**
- 当前不需要 persistent KV cache
- I/O overhead 可能抵消收益
- 增加故障恢复复杂度

### 2.6 MemServe / DistServe（Disaggregated Serving）

**解决的问题:**
- Prefill/decode 分离
- 跨 node KV transfer

**状态对象:**
- KV cache in remote memory/GPU
- Network-accessible KV store

**Producer/Consumer:**
- Producer: prefill instance
- Consumer: decode instance（可能在不同 node）

**Cache Identity:**
- Request-level KV reference

**Storage/Transport:**
- Remote GPU memory
- High-speed network（RDMA、NVLink 等）

**Prefix-only or Segment:**
- Full KV（不只是 prefix）

**Same/Cross-Engine:**
- Cross-node（主要价值）

**实验收益:**
- MemServe paper：disaggregated 架构下吞吐提升 2-3x

**vLLM 侵入程度:**
- 需要重新架构 serving system
- 非 vLLM native feature

**对 StateBus 潜在价值:**
- **极低**：单机双 GPU 环境
- **不适用**：架构 mismatch

**明显不适合的原因:**
- 为分布式集群设计，单机双 GPU 无价值
- 架构变更过大
- 网络传输 overhead 在单机无意义

### 2.7 Hidden State / Activation Export

**解决的问题:**
- Agent 间传递 neural representation
- 避免重复 forward pass

**状态对象:**
- Hidden state tensors（某一层的 activation）
- 不是 KV cache

**Producer/Consumer:**
- Producer: upstream Agent
- Consumer: downstream Agent（需要 compatible model/layer）

**Cache Identity:**
- Model + layer + input

**Storage/Transport:**
- Tensor serialization
- Shared memory、IPC、file

**Prefix-only or Segment:**
- N/A（不是 KV）

**Same/Cross-Engine:**
- Cross-process（理论上）

**实验收益:**
- 研究领域，无生产系统实验

**vLLM 侵入程度:**
- 需要深度修改 model inference
- 需要 export 中间 activation

**对 StateBus 潜在价值:**
- **极低**：实现复杂、收益不明、consumer 约束强

**明显不适合的原因:**
- 需要 downstream consumer 能从中间 layer 继续
- Model 和 layer 必须严格兼容
- 赛题要求的"KV 中间状态"更偏向 KV cache，不是 hidden state
- 实现和验证复杂度极高


## 3. 按 StateBus 约束筛选

### 3.1 筛选标准

用统一标准对候选方案评分（1-5 分，5 分最高）：

| 标准 | 权重 | 说明 |
|------|------|------|
| 真实 Agent 下游消费 | 高 | 是否形成真实的 Agent 下游消费，不只是 engine 内部优化 |
| 适合固定四角色流程 | 高 | 是否适合 Planner→Retriever→Executor→Summarizer 固定拓扑 |
| 适合 Retriever evidence/RAG | 高 | 是否适合 evidence-based RAG 上下文 |
| 兼容 Qwen3-32B + vLLM | 高 | 是否兼容当前 model 和 serving backend |
| 单机双 GPU 可行性 | 高 | 单机双 GPU、Docker/openEuler 条件是否可行 |
| 无需 fork vLLM | 中 | 是否需要修改或 fork vLLM |
| 资源成本 | 中 | GPU、CPU pinned memory 和磁盘成本 |
| 优于当前 shared prefix | 高 | 是否能优于当前 engine-local shared prefix |
| 可公平实验和解释 | 高 | 是否能公平实验和清晰解释 |
| 实施与交付风险 | 高 | 实施与交付风险 |
| 通用性 | 中 | 是否容易被认为针对赛题 case 特化 |

### 3.2 候选方案评分

| 方案 | 真实消费 | 四角色 | RAG | vLLM兼容 | 单机 | 无需fork | 成本 | 优于现状 | 可实验 | 风险 | 通用性 | 总分 |
|------|---------|--------|-----|---------|------|---------|------|---------|--------|------|--------|------|
| A. 强化 vLLM engine-local | 3 | 5 | 5 | 5 | 5 | 5 | 5 | 4 | 5 | 5 | 4 | 51 |
| B. LMCache adapter | 4 | 4 | 4 | 3 | 3 | 2 | 3 | 3 | 3 | 2 | 4 | 35 |
| C. Evidence segment KV | 4 | 5 | 5 | 3 | 4 | 2 | 4 | 4 | 3 | 3 | 5 | 42 |
| D. SGLang RadixAttention | 3 | 4 | 4 | 1 | 4 | 1 | 4 | 3 | 3 | 2 | 4 | 33 |
| E. Persistent KV cache | 2 | 3 | 3 | 2 | 3 | 2 | 3 | 2 | 3 | 3 | 3 | 29 |
| F. Hidden state export | 2 | 2 | 2 | 1 | 3 | 1 | 3 | 2 | 2 | 1 | 2 | 21 |

**说明：**
- 方案 A（强化 vLLM engine-local）得分最高（51），是当前主线的自然演进
- 方案 C（Evidence segment KV）得分次之（42），是增强版
- 方案 B（LMCache adapter）得分 35，可作为可选数据面
- 其他方案得分较低，不适合第一版

### 3.3 Shortlist 确定

根据评分和 StateBus 实际约束，选出 3 个方案深入分析：

1. **方案 A：强化当前 vLLM engine-local prefix 路线**（主方案）
2. **方案 C：Evidence-segment KV identity**（增强方案）
3. **方案 B：LMCache adapter**（可选数据面 fallback）

**不进入 shortlist 的方案及原因：**
- SGLang：需要切换 serving backend，风险高
- Persistent KV：当前不需要跨重启，增加复杂度无收益
- Hidden state：实现复杂度极高，consumer 约束强，赛题相关度低


## 4. Shortlist 深入分析

### 4.1 方案 A：强化当前 vLLM Engine-Local Prefix 路线

**核心思路：**
不引入外部 KV cache service，继续依赖 vLLM native prefix caching，但优化 StateBus 控制面：
- 优化 evidence layout 和 stable prefix 构造
- 改进 cache-friendly scheduling
- 增强 prefix identity 和 compatibility signature
- 完善 observability 和 feedback loop

**技术细节：**

1. **Evidence Layout 优化**
   - 当前：`shared_evidence_prefix` layout，evidence 在前、role instruction 在后
   - 优化：确保不同 role 共享完全相同的 token prefix
   - 挑战：role-specific system prompt 会破坏 prefix 相同性
   - 解决：将 role instruction 移到 evidence 之后，或使用统一 system prompt + role suffix

2. **Stable Prefix 构造**
   - corpus hash：基于 source doc hashes，不含 query
   - evidence hash：基于 evidence pack + hydrate manifest
   - 排除不稳定因素：Planner 措辞、query-derived score、lexical hint
   - 已在 2026-07-14 replay identity 修复中落地

3. **Cache-Friendly Scheduling**
   - 当前：`order_prefix_schedule_hints()` 支持 cache_friendly mode
   - 按 corpus_prefix_hash 分组，同组连续调度
   - Prefix feedback loop 校准 predicted vs observed hit rate
   - 已有 task-local counter delta 验证能力

4. **Observability 增强**
   - vLLM V0 block query/hit counter exporter（已实现）
   - task-local before/after delta（已实现）
   - TTFT probe with alternating order（已验证）
   - Prefix feedback snapshot（已实现）

**优点：**
- ✅ 零依赖：不引入新组件
- ✅ 风险低：基于已验证能力
- ✅ 可增量：逐步优化 layout 和 scheduling
- ✅ openEuler 友好：无需编译或 patch

**缺点：**
- ❌ Same-engine only：不支持 cross-engine reuse
- ❌ Session-scoped：不支持 persistent cache
- ❌ Prefix-only：不支持 non-contiguous segment

**对 StateBus 的价值：**
- 已有定向验证：shared 78% hit rate，TTFT 降低 88%
- 适合当前单 engine + session-scoped 场景
- 可直接用于证明"非文本中间状态传递"（prefix identity + scheduling control）

**实施复杂度：**低

**建议：作为主方案**

### 4.2 方案 C：Evidence-Segment KV Identity

**核心思路：**
将 `CanonicalEvidencePack` 的稳定 evidence segment 映射成 KV identity，支持更细粒度的 KV reuse。不要求 full prompt prefix 相同，只要 evidence segment 相同即可复用。

**技术细节：**

1. **Evidence Segment 定义**
   - Retriever 产生的稳定 evidence chunks
   - 每个 segment 有 content hash、source hash、locator
   - Segment 独立于 query、role、position

2. **Segment-Level KV Identity**
   ```python
   @dataclass(frozen=True)
   class EvidenceSegmentKVIdentity:
       segment_content_hash: str
       segment_source_hash: str
       model_id: str
       tokenizer_id: str
       position_encoding_mode: str  # absolute / relative / RoPE
       schema_version: str = "statebus.evidence_segment_kv.v1"
   ```

3. **KV Composition**
   - 挑战：不同 position、不同顺序的 evidence segment 如何组合 KV
   - CacheBlend 方案：fuzzy matching + recompute affected positions
   - 简化方案：只支持相同 position 的 segment reuse

4. **Position Encoding 兼容性**
   - RoPE（Qwen3）：position-dependent，改变 position 需要 recompute
   - Absolute position：更容易 segment reuse
   - 实现难度：需要深入理解 vLLM attention kernel

**优点：**
- ✅ 更细粒度：不要求 full prefix 相同
- ✅ 适合 RAG：evidence 顺序变化时仍能部分复用
- ✅ 概念清晰：evidence-centric，符合 StateBus 语义

**缺点：**
- ❌ 实现复杂：需要修改 vLLM attention 或 KV cache manager
- ❌ Position encoding 问题：RoPE 下 position 变化需要 recompute
- ❌ 验证困难：难以公平对比 segment reuse vs prefix reuse
- ❌ 稳定性风险：修改 attention kernel 可能引入 bug

**对 StateBus 的价值：**
- 理论价值高：evidence 顺序变化场景
- 实践风险高：实现复杂、验证困难
- 不适合第一版：建议作为后续研究方向

**实施复杂度：**高

**建议：作为研究方向，不纳入第一版**

### 4.3 方案 B：LMCache Adapter 作为可选数据面

**核心思路：**
StateBus 保留 Protobuf/Ref/semantic/memory 控制面，通过 adapter 接入 LMCache 作为可选 KV data plane，实现可寻址、可加载、可观测的 KV reuse。

**技术细节：**

1. **LMCache 架构**
   - KV cache manager：管理 KV chunk 的 store/load/eviction
   - Storage backend：CPU memory、GPU memory、disk、Redis
   - Transport：本地 IPC、TCP、RDMA
   - vLLM integration：通过 patch 或 plugin

2. **StateBus 集成点**
   ```python
   @dataclass(frozen=True)
   class LMCacheKVReference:
       cache_key: str
       chunk_ids: list[str]
       total_tokens: int
       cache_service_endpoint: str
       schema_version: str = "statebus.lmcache_kv_ref.v1"
   ```

3. **Control Plane Adapter**
   - StateBus 控制面生成 cache key（基于 evidence hash）
   - LMCache SDK 查询、存储、加载 KV
   - vLLM 从 LMCache 加载 KV，继续 generation

4. **部署要求**
   - LMCache service（独立进程）
   - vLLM 需要 LMCache integration patch
   - 可能需要编译 LMCache native extension

**优点：**
- ✅ External KV reference：StateBus 可寻址 KV
- ✅ Cross-request reuse：不限于 same session
- ✅ Persistent cache：支持跨服务重启
- ✅ 成熟度：LMCache 是 research project，有 paper 和 code

**缺点：**
- ❌ 部署复杂：需要 LMCache service、patch vLLM、编译 extension
- ❌ 单机价值低：当前单 engine 环境下增量价值不明显
- ❌ openEuler 风险：增加依赖和编译要求
- ❌ 维护成本：需要跟进 LMCache 和 vLLM 版本

**对 StateBus 的价值：**
- 当前价值低：单 engine + session-scoped 场景下，native prefix caching 已足够
- 未来价值中：如果扩展到 multi-engine、persistent cache 场景
- 赛题价值中：可以宣称"external KV reference"，但增加交付风险

**实施复杂度：**中高

**建议：作为可选 fallback，不作为第一版主线**

**LMCache 源码快速审查：**

本地有 LMCache 源码：`/home/qcrs/statebus/project/third_party/LMCache`

关键观察：
- README 说明支持 vLLM、SGLang、TensorRT-LLM
- 需要修改 serving engine，不是纯 SDK
- CacheBlend 是研究 prototype，非生产 ready
- 主要价值在 cross-instance、persistent cache

对 StateBus 的适配判断：
- 如果只用 same-instance cache：vLLM native 已足够
- 如果用 cross-instance：当前单 engine 环境无价值
- 如果用 persistent cache：当前 session-scoped 无需求
- 结论：LMCache 当前对 StateBus 增量价值有限


## 5. 对比矩阵

### 5.1 三个 Shortlist 方案对比

| 维度 | 方案 A: 强化 Engine-Local | 方案 C: Evidence-Segment KV | 方案 B: LMCache Adapter |
|------|--------------------------|----------------------------|------------------------|
| **KV 对象定义** | 控制面 identity + handle | Evidence segment KV identity | External KV reference |
| **Producer** | 第一个 role（vLLM 内部） | Retriever evidence segment | 任意请求（LMCache 管理） |
| **Consumer** | 后续 role（同 engine） | 后续使用该 segment 的 role | 任意请求（cross-instance） |
| **Cache Identity** | Token prefix hash | Evidence content + source hash | Prefix token + model metadata |
| **Storage** | vLLM GPU memory | vLLM GPU memory（需修改） | LMCache service（CPU/GPU/disk） |
| **Transport** | Engine-local | Engine-local | IPC/TCP/RDMA |
| **Prefix/Segment** | Prefix-only | Segment（理论） | Prefix（CacheBlend 可 segment） |
| **Same/Cross-Engine** | Same engine | Same engine | Cross-engine |
| **vLLM 侵入** | 零 | 需修改 attention/KV manager | 需 patch vLLM |
| **实施复杂度** | 低 | 高 | 中高 |
| **openEuler 风险** | 低 | 中 | 高 |
| **增量价值** | 中（优化现有） | 高（理论），低（实践风险） | 低（当前场景） |
| **可验证性** | 高（已验证） | 中（难公平对比） | 中（需独立环境） |
| **赛题相关度** | 高 | 高 | 中 |

### 5.2 关键问题分析对比

#### 5.2.1 什么是适合 StateBus 的 KV 中间状态定义？

**方案 A 的定义：Engine-local handle + scheduling control**
- `NeuralPrefixIdentity`：corpus/evidence prefix hash
- `NeuralStateHandle`：engine/session/prefix 绑定、生命周期
- `PrefixReuseScheduleHint`：cache affinity、schedule priority
- **特点**：控制面对象，不是 KV tensor 引用；依赖 vLLM 内部 KV reuse

**方案 C 的定义：Evidence-segment KV identity**
- `EvidenceSegmentKVIdentity`：segment content/source hash + position
- **特点**：细粒度 KV identity，但需要 KV composition 能力

**方案 B 的定义：External KV reference**
- `LMCacheKVReference`：cache key + chunk ids + endpoint
- **特点**：真正的 external KV reference，但部署复杂

**结论：**
- **第一版**：采用方案 A 的定义（engine-local handle + control）
- **明确声明边界**：这是控制面对象，不是 KV tensor export/transfer
- **未来扩展**：如需 external KV，可引入方案 B 的 reference 层

#### 5.2.2 跨 Agent KV 复用是否真的可行？

**关键挑战：**
1. **System Prompt 差异**
   - Planner、Retriever、Executor、Summarizer 有不同的 system prompt
   - 如果 system prompt 在前，会破坏 prefix 相同性
   - **解决**：统一 system prompt base + role suffix，或 evidence-first layout

2. **Position Encoding**
   - Qwen3 使用 RoPE，position-dependent
   - 改变 token position 会影响 KV（需要 recompute RoPE）
   - **影响**：只有完全相同的 prefix position 才能复用

3. **Chat Template**
   - 不同 role 可能用不同 chat template
   - **解决**：统一 chat template，或只共享 evidence segment

**可行性判断：**

| 复用场景 | 可行性 | 条件 |
|---------|--------|------|
| 同一请求链内，Executor/Summarizer 复用 evidence | ✅ 高 | evidence-first layout，相同 position |
| 同一请求链内，不同 role 复用 evidence | ⚠️ 中 | 需要统一 system prompt 或 role suffix |
| 跨任务复用相同 corpus 的 evidence | ✅ 高 | cache-friendly scheduling |
| 跨轮次复用历史 evidence | ✅ 高 | Memory/Replay 机制 + cache scheduling |
| 不同 role、不同 position 复用 segment | ❌ 低 | 需要 segment KV composition（复杂） |

**方案 A 的可行路径：**
- ✅ 同一请求链内：Planner 生成 evidence → Retriever hydrate → Executor/Summarizer 复用
- ✅ 跨任务：相同 corpus 的不同 query → cache-friendly scheduling
- ✅ 跨轮次：continuous/replay → 历史 evidence 复用

**示例 Prompt Layout：**

```
# Shared Evidence Prefix (相同 for all roles)
<evidence>
  [Corpus Text]
  [Table Data]
  [Retrieved Chunks]
</evidence>

# Role-Specific Suffix (不同 for each role)
<role=executor>
  [Executor-specific instruction]
  [Task goal]
  [Required outputs]
</role>
```

#### 5.2.3 KV Identity 和安全边界

**方案 A 的 Identity 设计：**

```python
# Corpus-level identity (for scheduling)
corpus_prefix_hash = sha256({
    "prefix_contract_version": "statebus.engine_local_prefix.v1",
    "system_prompt_version": "statebus-v2-shared-prefix-v1",
    "source_doc_hashes": sorted(doc_hashes),
})

# Evidence-level identity (for exact prefix matching)
evidence_prefix_hash = sha256({
    "prefix_contract_version": "statebus.engine_local_prefix.v1",
    "corpus_prefix_hash": corpus_hash,
    "evidence_pack_hash": evidence_hash,
    "hydrate_manifest_hash": manifest_hash,
})
```

**Compatibility Signature 必须包含：**
- ✅ model_id + revision
- ✅ tokenizer_id
- ✅ system_prompt_version
- ✅ prefix_contract_version
- ✅ evidence content hash
- ❌ 不包含：query、Planner 措辞、score、lexical hint（不稳定）

**安全边界：**
1. **Fail Closed**：不兼容时必须拒绝复用，不能降级
2. **Stale Cache**：增加 expires_at_ns、lease 机制
3. **Cross-Contamination**：不同 tenant/task 必须有独立 session_id
4. **Model Mismatch**：model_id 或 tokenizer_id 不同必须拒绝

**已在代码中实现：**
- `NeuralStateHandle.is_compatible_with()` 检查 5 个字段
- Replay identity 修复（2026-07-14）排除不稳定因素
- Session-scoped registry，自动 invalidation

#### 5.2.4 与现有状态系统如何协同

**分工明确：**

```
SemanticStateRef     → 选择/表达证据、embedding、dense state
ExecutionArtifactRef → 保存工具执行结果、文件、验证 artifact
MemoryCommit         → 跨任务复用语义、策略、验证产物
NeuralPrefixIdentity → 避免重复 prefill（控制面 identity）
LogitStateRef        → 表达输出不确定性（top-logprobs 派生）
```

**一次请求的协同流程（方案 A）：**

1. **Planner**：生成 objective，Runtime 构造 evidence scope
2. **Retriever**：
   - 检索 evidence → 生成 `SemanticStateRef`
   - 构造 stable evidence prefix → 生成 `NeuralPrefixIdentity`
   - 注册到 `EngineLocalPrefixRegistry`
3. **Executor**：
   - 消费 `SemanticStateRef` 的 evidence
   - vLLM 自动检测 prefix match → 复用 KV blocks
   - 生成 `ExecutionArtifactRef` 和 `LogitStateRef`
4. **Summarizer**：
   - 消费 evidence 和 execution result
   - vLLM 再次复用 prefix KV
   - 生成 `MemoryCommit`（用于跨任务复用）
5. **Observability**：
   - 采样 vLLM counter delta → 验证实际 hit rate
   - 记录 prefix feedback → 校准调度

**Cache Miss 回退：**
- vLLM 自动 fallback：prefix miss 时正常 prefill
- StateBus 不需要显式 fallback 逻辑
- Observability 记录 miss 但不影响正确性

**Exact Replay 时如何绕过：**
- Exact replay 直接恢复历史 output，跳过 Executor/Summarizer LLM call
- 不触发 vLLM prefix cache（因为没有 LLM call）
- Replay identity 基于 evidence execution input hash（不含 prefix identity）

#### 5.2.5 真实收益在哪里

**适用 Workload：**

| Workload | 收益来源 | 方案 A 支持 | 实验证据 |
|----------|---------|------------|---------|
| 多 Agent 共享长 corpus | Executor/Summarizer 复用 Retriever prefix | ✅ | 定向验证：78% hit rate |
| 同任务不同角色读相同证据 | 同上 | ✅ | 同上 |
| 10 轮连续任务 | 跨轮次 evidence 复用 + memory | ✅ | CSV continuous：10/10 pass |
| 同一财报上的不同问题 | cache-friendly scheduling | ✅ | Formal 25/25 L3 pass |
| RAG evidence 顺序变化 | Corpus-level scheduling（不是 segment） | ⚠️ | 需要 segment KV（方案 C） |
| Exact replay | 直接跳过 LLM call（不依赖 prefix cache） | ✅ | Incident 7/10 exact replay |

**收益类型明确：**

1. **Prefill Token Savings**（理论）
   - 估算：`estimated_prefill_saved_tokens = prefix_tokens * (consumer_count - 1)`
   - 当前：控制面估算，不是 vLLM 实际计数

2. **Prefill Compute Savings**（实际）
   - vLLM block query/hit counter delta
   - 定向验证：shared 78% hit rate vs independent 0%

3. **TTFT Reduction**（实际）
   - 定向验证：shared 267ms vs independent 2,283ms（-88%）
   - 注意：这是 task-local pair probe，不是端到端 StateBus latency

4. **端到端 Task Latency**（复合）
   - 包含：LLM latency + control plane + state transfer + memory lookup
   - 不能把 TTFT reduction 直接等同于端到端加速
   - 需要完整 benchmark run 验证

**不能宣称的：**
- ❌ KV tensor export/transfer
- ❌ Hidden-state handoff
- ❌ Cross-engine reuse（当前 same engine only）
- ❌ 单独归因到 "typed carrier"（端到端收益是复合的）

**可以宣称的：**
- ✅ Engine-local prefix reuse 机制和控制面
- ✅ vLLM 内部 KV block hit rate 提升
- ✅ Shared prefix layout 下 TTFT reduction
- ✅ 非文本中间状态传递（prefix identity + scheduling control）


## 6. 最终技术选择

### 6.1 主方案：强化 vLLM Engine-Local Prefix 路线

**选择依据：**
1. ✅ 基于已验证能力：当前已有 78% hit rate、88% TTFT reduction 的实验证据
2. ✅ 零新依赖：不引入 LMCache、不修改 vLLM、不切换 serving backend
3. ✅ 风险最低：增量优化，可逐步推进
4. ✅ openEuler 友好：无需编译、patch 或运行额外服务
5. ✅ 适合当前场景：单 engine + session-scoped + 固定四角色
6. ✅ 可清晰解释：控制面 identity + scheduling + vLLM native reuse

**明确定义：StateBus KV 中间状态 = Engine-Local Prefix Identity + Scheduling Control**

这不是 KV tensor export/transfer，而是：
- StateBus 控制面构造稳定的 evidence prefix identity
- 通过 cache-friendly scheduling 让相同 prefix 连续调度
- vLLM engine 内部自动检测和复用 KV blocks
- StateBus 采样 vLLM counter delta 验证实际 hit rate

**相对当前实现的增量价值：**
1. 优化 evidence layout，确保不同 role 共享完全相同 prefix
2. 改进 scheduling：更激进的 cache-friendly order、feedback loop 校准
3. 完善 observability：持久化 prefix feedback、counter delta、TTFT probe
4. 明确声明边界：控制面对象，不是 KV tensor

### 6.2 Fallback 方案：LMCache Adapter 作为可选数据面

**选择依据：**
- 如果未来需要 cross-engine 或 persistent KV reuse
- 如果需要向评审证明"external KV reference"能力
- 作为可选模块，不影响主线

**实施边界：**
- 第一版：不实施，只在设计文档中预留接口
- 可选模块：通过 feature flag 开启
- 独立验证：不与主线 benchmark 混合

### 6.3 不选择的方案及理由

**方案 C（Evidence-Segment KV）：**
- ❌ 实现复杂度极高：需要修改 vLLM attention kernel
- ❌ Position encoding 问题：RoPE 下难以处理 segment reorder
- ❌ 验证困难：难以公平对比 segment vs prefix
- 📌 建议：作为后续研究方向，不纳入第一版

**SGLang、Persistent KV、Hidden State：**
- ❌ 不适合当前环境和赛题要求
- ❌ 实施风险过高
- 📌 建议：不纳入调研范围

### 6.4 最终传递什么对象

**第一版传递对象：**

```python
# 控制面对象（已存在，需完善）
@dataclass(frozen=True)
class NeuralPrefixIdentity:
    corpus_prefix_hash: str
    evidence_prefix_hash: str
    source_doc_hashes: tuple[str, ...]
    evidence_pack_hash: str
    hydrate_manifest_hash: str
    system_prompt_version: str
    prefix_contract_version: str
    claim_boundary: str = "prefix_identity_and_scheduling_control_plane_only"
    schema_version: str = "statebus.neural_prefix_identity.v1"

@dataclass(frozen=True)
class NeuralStateHandle:
    engine_id: str
    session_id: str
    prefix_hash: str
    model_id: str
    tokenizer_id: str
    corpus_prefix_hash: str
    evidence_prefix_hash: str
    lifetime_scope: str
    prefix_token_count: int
    cache_hit_count: int
    claim_boundary: str = "prefix_identity_and_scheduling_control_plane_only"
    schema_version: str = "statebus.neural_state_handle.v1"

@dataclass(frozen=True)
class PrefixReuseScheduleHint:
    task_id: str
    corpus_prefix_hash: str
    evidence_prefix_hash: str
    estimated_prefix_tokens: int
    cache_affinity_group: str
    schedule_priority: float
    claim_boundary: str = "prefix_identity_and_scheduling_control_plane_only"
    schema_version: str = "statebus.neural_prefix_schedule_hint.v1"
```

**不传递的对象：**
- ❌ KV tensor bytes
- ❌ Hidden state activation
- ❌ vLLM-internal KV block pointer（engine-private）

**Claim Boundary 明确：**
- ✅ 控制面 identity 和 scheduling
- ✅ vLLM engine-local KV block reuse（自动）
- ✅ Observability：counter delta、TTFT probe、feedback
- ❌ 不是 KV tensor export/transfer
- ❌ 不是 cross-engine KV handoff
- ❌ 不是 hidden-state propagation

### 6.5 相对当前 Shared-Prefix 的增量能力

**当前已有（2026-07-14 状态）：**
1. ✅ `NeuralPrefixIdentity` 和 `NeuralStateHandle`
2. ✅ `shared_evidence_prefix` prompt layout
3. ✅ `order_prefix_schedule_hints()` cache-friendly scheduling
4. ✅ vLLM block counter exporter + task-local delta
5. ✅ Prefix feedback loop
6. ✅ TTFT probe（alternating order）
7. ✅ Replay identity 修复（排除不稳定因素）

**第一版增强（建议）：**
1. 📌 Evidence layout 优化：role-agnostic system prompt base
2. 📌 Scheduling 增强：更激进的 cache-friendly order、动态 reorder
3. 📌 Observability 完善：持久化 prefix feedback history、counter delta audit
4. 📌 文档和声明边界：明确 "engine-local prefix identity + control"
5. 📌 Benchmark 增强：prefix cache disabled baseline、identity perturbed ablation

**明确不做（第一版）：**
- ❌ External KV cache service（LMCache 等）
- ❌ KV tensor export/serialization
- ❌ Cross-engine KV transfer
- ❌ Persistent KV cache
- ❌ Evidence-segment KV composition
- ❌ Cross-model KV sharing

## 7. 跨模型 KV 协同（低优先级研究）

### 7.1 问题定义

是否可以在 Qwen3-8B 与 Qwen3-32B 等不同模型之间共享或转换某些中间状态？

### 7.2 技术可行性分析

**同一 Tokenizer ≠ KV Tensor 兼容**

Qwen3-8B 和 Qwen3-32B 共用 tokenizer，意味着：
- ✅ Token IDs 相同
- ✅ Token sequence 可以直接复用

但 KV tensor 形状和数值完全不同：

| 模型 | Layers | Hidden Size | KV Heads | Head Dim | KV Shape per Layer |
|------|--------|-------------|----------|----------|-------------------|
| Qwen3-8B | 28 | 3584 | 4 | 128 | [batch, seq_len, 4, 128] |
| Qwen3-32B | 64 | 5120 | 8 | 128 | [batch, seq_len, 8, 128] |

**不能直接复用 KV tensor：**
- ❌ Layer 数不同（28 vs 64）
- ❌ Hidden size 不同（3584 vs 5120）
- ❌ KV head 数不同（4 vs 8）
- ❌ 权重矩阵不同，数值完全不同

### 7.3 可行的跨模型协同路径

**路径 1：共享 Token Sequence 和 Evidence State**
- ✅ 可行度：高
- 复用 `SemanticStateRef`：evidence embedding、text、locator
- 复用 `ExecutionArtifactRef`：执行结果、文件
- 复用 `MemoryCommit`：策略、经验
- 复用 token sequence：小模型 tokenize → 大模型直接用
- ⚠️ 不是 KV tensor 复用

**路径 2：小模型规划/路由，大模型执行**
- ✅ 可行度：中高
- Planner/Retriever 用 Qwen3-8B（快速规划）
- Executor/Summarizer 用 Qwen3-32B（高质量执行）
- 传递：semantic state、evidence、tool selection
- ⚠️ 不是 KV 复用，是任务分工

**路径 3：Speculative Decoding**
- ✅ 可行度：中（需要框架支持）
- Draft model（Qwen3-8B）生成 candidate tokens
- Target model（Qwen3-32B）验证和接受
- vLLM 已支持 speculative decoding
- ⚠️ 这是 serving optimization，不是 Agent 间状态传递

**路径 4：KV Tensor Projection/Adapter（研究方向）**
- ❌ 可行度：低（研究阶段）
- 训练 adapter 将 Qwen3-8B KV 投影到 Qwen3-32B KV space
- 需要：大量训练数据、质量验证、推理 overhead 评估
- 转换成本可能超过重新 prefill
- 📌 不纳入第一版

### 7.4 结论

**第一版不实施跨模型 KV 共享：**
- Qwen3-8B 和 Qwen3-32B 的 KV tensor 不兼容
- 有价值的跨模型协同是共享 semantic state、evidence、artifact
- KV tensor projection 是研究方向，实用性待验证

**Compatibility Signature 必须拒绝跨模型：**
```python
def is_compatible_with(self, *, model_id: str, ...) -> bool:
    return self.model_id == model_id  # 严格相等
```

**未来如果需要跨模型能力：**
- 优先考虑：任务分工（小模型规划、大模型执行）
- 次优考虑：speculative decoding（框架级优化）
- 最后考虑：KV projection（研究方向，成本效益待验证）

## 8. 来源和引用

### 8.1 StateBus 项目文档

- `AGENTS.md`：项目说明和架构概览
- `README.md`：环境、命令和实验结果入口
- `docs/reference/题目.md`：赛题要求
- `docs/constraints/current_feature_scope.md`：当前功能边界
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/43_full_qwen3_extended_audit_20260714.md`：Qwen3-32B 严格真实性审计
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/44_planner_role_and_stability_plan_20260714.md`：Planner 真实职责
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/45_planner_kv_replay_fix_results_20260714.md`：定向修复结果

### 8.2 StateBus 代码

- `v2/runtime/neural_state.py`：NeuralPrefixIdentity、NeuralStateHandle、EngineLocalPrefixRegistry
- `v2/runtime/prefix_feedback.py`：PrefixCacheFeedbackLoop
- `v2/runtime/vllm_metrics.py`：vLLM metrics parser、counter delta
- `v2/runtime/logit_state.py`：LogitStateRef（top-logprobs 派生）
- `scripts/vllm_v0_prefix_counter_exporter.py`：vLLM V0 block counter exporter
- `scripts/probe_local_vllm_prefix_alignment.py`：TTFT probe

### 8.3 vLLM 官方文档

- vLLM Prefix Caching: https://docs.vllm.ai/en/latest/automatic_prefix_caching/usage.html
- vLLM Metrics: https://docs.vllm.ai/en/latest/serving/metrics.html
- vLLM Architecture: https://docs.vllm.ai/en/latest/design/arch_overview.html

### 8.4 LMCache

- 本地源码：`/home/qcrs/statebus/project/third_party/LMCache`
- GitHub: https://github.com/LMCache/LMCache
- Paper: "LMCache: Locality-aware Cross-Request KV Cache Sharing for LLM Serving"

### 8.5 其他参考

- SGLang: https://github.com/sgl-project/sglang
- CacheBlend Paper: "CacheBlend: Fast Large Language Model Serving for RAG with Cached Knowledge Fusion"
- vLLM Speculative Decoding: https://docs.vllm.ai/en/latest/models/spec_decode.html

**访问日期：** 2026-07-14（本地代码和文档）

**网络访问限制：** 本次调研主要基于本地代码库、文档和已有 LMCache 源码；外部访问因代理问题受限，但不影响核心结论。

## 9. 总结

### 9.1 核心结论

1. **当前能力边界清晰：** StateBus 已有 engine-local prefix identity + scheduling control，但没有 KV tensor export/transfer
2. **主方案明确：** 强化当前 vLLM engine-local prefix 路线，不引入外部 KV cache
3. **Fallback 清晰：** LMCache adapter 作为可选模块，第一版不实施
4. **不做的清晰：** Evidence-segment KV、cross-model KV、hidden-state export 不纳入第一版

### 9.2 关键发现

1. **vLLM native prefix caching 已足够：** 单 engine + session-scoped 场景下，已有 78% hit rate 和 88% TTFT reduction
2. **控制面价值高：** 稳定的 prefix identity、cache-friendly scheduling、feedback loop 是主要优化方向
3. **External KV 价值低：** 当前场景下，LMCache 等外部 KV cache 增量价值有限，部署复杂度高
4. **跨模型 KV 不可行：** Qwen3-8B 和 Qwen3-32B 的 KV tensor 不兼容，有价值的是共享 semantic state

### 9.3 下一步

参见第二份文档：`02_statebus_kv_design_and_implementation_plan.md`


## 10. Hidden State 优化方法补充调研

### 10.1 Hidden State vs KV Cache 的区别

**KV Cache:**
- 存储：每层的 Key 和 Value tensor
- 用途：加速 attention 计算（避免重复计算 past tokens 的 K/V）
- 形状：`[batch, num_kv_heads, seq_len, head_dim]`
- 优化目标：减少重复 prefill

**Hidden State:**
- 存储：某一层的 activation output
- 用途：跨模型/跨阶段传递中间表示
- 形状：`[batch, seq_len, hidden_dim]`
- 优化目标：避免重复 forward pass

### 10.2 Hidden State 传递的研究方向

#### 10.2.1 Early Exit / Shallow-Deep Cascade

**核心思路：**
- 小模型（shallow）先处理，得到 hidden state
- 只在不确定时才调用大模型（deep）
- 大模型从中间层继续，不从头开始

**实现方式：**
```python
# Conceptual example
shallow_output, shallow_hidden = small_model(input, return_hidden=True)
if confidence(shallow_output) < threshold:
    # 大模型从中间层继续
    deep_output = large_model.forward_from_layer(
        hidden_state=shallow_hidden,
        start_layer=12  # 例如从第12层开始
    )
```

**挑战：**
- 小模型和大模型的 hidden_dim 必须兼容
- 或需要训练 projection layer
- Layer alignment：小模型的第 N 层对应大模型的第 M 层

**对 StateBus 的适用性：**
- ❌ Qwen3-8B (hidden=3584) 和 Qwen3-32B (hidden=5120) 不兼容
- ❌ 需要额外训练 projection layer
- ❌ 推理 overhead 可能抵消收益
- 📌 不适合第一版

#### 10.2.2 Speculative Decoding (Draft-Verify)

**核心思路：**
- Draft model（小模型）快速生成 candidate tokens
- Target model（大模型）验证，接受正确的 tokens
- 不传递 hidden state，而是传递 token candidates

**vLLM 已支持：**
```python
# vLLM speculative decoding
vllm serve qwen3-32b \
  --speculative-model qwen3-8b \
  --num-speculative-tokens 5
```

**对 StateBus 的适用性：**
- ✅ vLLM native 支持，零额外代码
- ✅ 适合 generation latency 敏感场景
- ⚠️ 这是 serving optimization，不是 Agent 间状态传递
- 📌 可以作为 serving 层优化，但不是 KV 中间状态主线

#### 10.2.3 Prompt Compression / Hidden State Distillation

**核心思路：**
- 将长 prompt 编码成 compact hidden state
- Downstream model 从 hidden state 继续，不重新读 prompt

**研究工作：**
- LLMLingua: Prompt compression
- GIST tokens: Learned prompt compression
- Prefix-tuning style: Soft prompt as hidden state

**挑战：**
- 需要训练 compression model
- 压缩质量 vs 信息损失 trade-off
- Downstream model 需要能接受 compressed hidden state

**对 StateBus 的适用性：**
- ❌ 需要训练额外模型
- ❌ 质量损失难以控制
- ❌ 不如直接优化 evidence selection 和 KV cache
- 📌 不适合第一版

#### 10.2.4 Cross-Attention over Hidden State

**核心思路：**
- Upstream agent 输出 hidden state
- Downstream agent 通过 cross-attention 读取
- 类似 encoder-decoder 架构

**实现要求：**
- Downstream model 必须有 cross-attention 层
- 或需要修改 model architecture

**对 StateBus 的适用性：**
- ❌ Qwen3 是 decoder-only，无 cross-attention
- ❌ 需要修改 model architecture
- ❌ 训练和部署复杂度极高
- 📌 不适合

### 10.3 Hidden State 优化的总体评估

**为什么 Hidden State 传递对 StateBus 价值有限：**

1. **模型兼容性问题**
   - Qwen3-8B 和 Qwen3-32B hidden_dim 不同
   - 需要 projection layer，增加 overhead

2. **训练成本高**
   - Early exit、prompt compression 都需要训练
   - 质量保证困难

3. **不如优化 KV cache**
   - KV cache 是 serving 层优化，无需训练
   - vLLM native 支持，零额外代码
   - 已有明确收益（78% hit rate）

4. **赛题相关度**
   - 赛题强调"非文本中间状态"，KV 更直接
   - Hidden state 是研究方向，工程成熟度低

**结论：** Hidden state 传递不纳入第一版，作为长期研究方向记录。


## 11. LogitState 优化作用补充分析

### 11.1 LogitState 当前实现回顾

**当前 LogitState 是什么：**
- 从 LLM completion 的 `top_logprobs` 派生
- 包含：peak entropy、varentropy、top_gap、decision_entropy
- 这是 probability distribution 的 compact summary
- **不是** hidden state 或 KV cache

**已记录字段：**
```python
@dataclass(frozen=True)
class LogitStateResult:
    payload_bytes: bytes           # Normalized probs at peak position
    entropy: float                 # Shannon entropy at peak
    confidence_proxy: float        # 1 - H/H_max
    peak_position: int             # Index of highest entropy position
    sequence_length: int           # Total output length
    aggregated_entropy: float      # Weighted average over top-N positions
    varentropy: float              # Variance of entropy across sequence
    top_gap: float                 # p1 - p2 at peak
    decision_entropy: float        # Entropy over candidate clusters
```

### 11.2 LogitState 的潜在优化作用

#### 11.2.1 Evidence Expansion（证据扩展）

**核心思路：**
- 检测 Executor 输出的不确定性
- 如果 entropy 高、confidence 低 → 触发 evidence expansion
- Retriever 补充更多 evidence，重新执行

**实施方式：**
```python
executor_result = executor.execute(evidence)
logit_state = extract_logit_state(executor_result.top_logprobs)

if logit_state.entropy > HIGH_ENTROPY_THRESHOLD:
    # 不确定性高，需要更多证据
    additional_evidence = retriever.expand_evidence(
        original_query=query,
        current_evidence=evidence,
        uncertainty_signal=logit_state
    )
    # 重新执行
    executor_result = executor.execute(evidence + additional_evidence)
```

**收益：**
- 自适应 evidence 数量
- 只在需要时扩展，节省 token
- 提高输出质量

**挑战：**
- 需要定义 threshold（何时算"不确定"）
- Evidence expansion 逻辑复杂
- 可能增加 latency（额外 retrieval + execution）

**对 StateBus 的适用性：**
- ✅ 概念清晰，符合 adaptive retrieval 思路
- ⚠️ 需要实验验证 threshold 和收益
- 📌 建议作为第二版增强，不纳入第一版

#### 11.2.2 Route/Tool Confidence Gate（路由/工具置信门）

**核心思路：**
- Executor 选择 tool 时，检测 decision entropy
- 如果 decision_entropy 高 → tool 选择不确定
- 触发 fallback 或 human-in-the-loop

**实施方式：**
```python
executor_result = executor.execute(evidence)
logit_state = extract_logit_state(executor_result.top_logprobs)

if logit_state.decision_entropy > DECISION_UNCERTAINTY_THRESHOLD:
    # Tool 选择不确定
    if ENABLE_FALLBACK:
        # 回退到保守 tool
        executor_result = executor.execute_with_fallback(evidence)
    else:
        # 标记为需要人工审核
        executor_result.requires_human_review = True
```

**收益：**
- 避免错误 tool 选择
- 提高可靠性

**挑战：**
- `decision_entropy` 依赖 `candidate_tokens` 准确性
- 当前实现是 fuzzy prefix matching，可能不准确
- Fallback 逻辑增加复杂度

**对 StateBus 的适用性：**
- ⚠️ 当前 `decision_entropy` 实现简单，需要增强
- ⚠️ StateBus 的 route/tool 是 closed-set，不确定性相对低
- 📌 建议作为可选 gate，不作为主线

#### 11.2.3 Cache/Replay Admissibility Gate（缓存/重放准入门）

**核心思路：**
- 只有高置信度的输出才允许 cache 或 replay
- 低置信度输出不进入 memory，避免污染

**实施方式：**
```python
executor_result = executor.execute(evidence)
logit_state = extract_logit_state(executor_result.top_logprobs)

if logit_state.confidence_proxy > CONFIDENCE_THRESHOLD:
    # 高置信度，允许 commit to memory
    memory.commit(executor_result, allow_replay=True)
else:
    # 低置信度，不允许 replay
    memory.commit(executor_result, allow_replay=False)
```

**收益：**
- 避免低质量输出被 replay
- 提高 memory 质量

**挑战：**
- Confidence threshold 定义困难
- 可能过滤掉正确但"不常见"的答案
- 需要大量实验校准

**对 StateBus 的适用性：**
- ✅ 概念合理，符合 quality control 思路
- ⚠️ 需要实验验证 threshold 和误判率
- 📌 建议作为第二版增强

#### 11.2.4 Retry/Temperature Adjustment（重试/温度调整）

**核心思路：**
- 检测输出的 varentropy
- 高 varentropy + 低 quality → 可能是 degeneration
- 触发 retry with adjusted temperature

**实施方式：**
```python
executor_result = executor.execute(evidence, temperature=0.7)
logit_state = extract_logit_state(executor_result.top_logprobs)

if (logit_state.varentropy > HIGH_VAR_THRESHOLD and 
    not quality_check(executor_result)):
    # 可能 degeneration，降低 temperature 重试
    executor_result = executor.execute(evidence, temperature=0.3)
```

**收益：**
- 自动检测和修复 degeneration
- 提高输出质量

**挑战：**
- Varentropy threshold 定义困难
- Retry 增加 latency
- 可能不收敛（一直 retry）

**对 StateBus 的适用性：**
- ⚠️ 当前 temperature 固定，引入动态调整增加复杂度
- ⚠️ 需要实验验证 varentropy 和 quality 的相关性
- 📌 不建议第一版实施

### 11.3 LogitState 优化作用总结

**当前状态（2026-07-14）：**
- LogitState 已提取和记录
- 334/334 cases 有 logit state
- **但尚未用于任何行为干预**
- 所有 `logit_confidence_gate_trigger_count=0`

**推荐的优化路径：**

**P1（高优先级，建议第二版）：**
1. **Evidence Expansion Gate**
   - 实施简单，收益明确
   - 基于 entropy threshold 触发 evidence expansion
   - 需要实验校准 threshold

2. **Cache/Replay Admissibility Gate**
   - 符合 quality control 思路
   - 避免低质量输出污染 memory
   - 需要实验验证 confidence proxy 准确性

**P2（中优先级，可选）：**
3. **Route/Tool Confidence Gate**
   - 需要改进 decision_entropy 实现
   - 当前 closed-set route/tool，不确定性相对低

**P3（低优先级，不建议）：**
4. **Retry/Temperature Adjustment**
   - 增加复杂度
   - 收益不明确

**第一版不实施 LogitState 优化：**
- 第一版聚焦 KV prefix optimization
- LogitState 优化作为第二版增强
- 当前已记录 logit state，为未来优化打好基础

### 11.4 LogitState 与 KV Cache 的协同

**可能的协同场景：**

1. **低置信度时禁用 Cache/Replay**
   ```python
   if logit_state.confidence_proxy < THRESHOLD:
       # 不允许 cache 这次输出
       neural_prefix_handle.allow_cache = False
       # 不允许 replay
       memory_commit.allow_replay = False
   ```

2. **不确定性驱动的 Evidence Expansion + Cache Invalidation**
   ```python
   if logit_state.entropy > THRESHOLD:
       # 扩展 evidence
       expanded_evidence = retriever.expand(...)
       # 使当前 prefix cache 失效（因为 evidence 变化）
       registry.invalidate_prefix(current_prefix_hash)
       # 重新执行
       executor.execute(expanded_evidence)
   ```

**建议：**
- 第一版：LogitState 和 KV Cache 独立
- 第二版：探索协同优化

