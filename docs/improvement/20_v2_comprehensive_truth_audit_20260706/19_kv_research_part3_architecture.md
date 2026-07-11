## 2. 架构合理性分析

### 2.1 三层架构设计评估

当前 KV 实现采用三层架构：

```text
┌─────────────────────────────────────────────────────────┐
│                    观测层 (Observability)                │
│  kv_analysis.py, kv_prefix_experiment.py, vllm_metrics │
│  职责：采集 vLLM metrics, 聚合估算, 生成报告           │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                    策略层 (Strategy)                     │
│  role_path.py, kv_prefix_schedule.py, retrieval/models │
│  职责：prefix layout, corpus scheduling, pruning hint  │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                    估算层 (Estimation)                   │
│  neural_state.py, kv_budget.py                         │
│  职责：corpus/evidence hash, registry, capacity sizing │
└─────────────────────────────────────────────────────────┘
```

**架构评价**: ✅ **合理且清晰**

#### 优点

1. **职责分离清晰**
   - 估算层：纯数据结构，无 LLM 依赖，可独立测试
   - 策略层：控制 prompt 构造和任务调度，依赖估算层
   - 观测层：读取外部 metrics，不修改 runtime 状态

2. **依赖方向正确**
   - 观测层 → 策略层 → 估算层（单向依赖）
   - 估算层可以完全独立于 vLLM 工作（适合 API 模式估算）

3. **扩展性好**
   - 新增 pruning 策略只需修改策略层
   - 新增 metrics 采集只需扩展观测层
   - 估算层的 registry 设计支持未来多 engine

4. **边界防护到位**
   - 每层都有明确的 claim_boundary 声明
   - NeuralStateHandle 不持有 KV tensor，只记录 control-plane 信息

#### 缺点

1. **策略层和运行时耦合**
   - `role_path.py` 既负责 prefix layout，又负责 LLM 调用
   - 建议：分离 `PrefixLayoutCompiler` 和 `RolePathExecutor`

2. **观测层数据流不统一**
   - `kv_prefix_experiment.py` 是独立脚本，输出 JSON
   - `kv_analysis.py` 是 library 函数，返回 dict
   - 建议：统一为 `KVObservabilityReport` 数据类

3. **配置管理分散**
   - 环境变量（`STATEBUS_PREFIX_ALIGNMENT_MODE`）
   - Manifest（`kv_prefix_reuse_v1`）
   - 硬编码（pruning threshold）
   - 建议：集中到 `kv_config.yaml`

### 2.2 模块边界评估

#### 估算层边界

**输入**: 
- Source doc hashes, evidence pack hash, hydrate manifest hash
- Engine/model/tokenizer identifiers

**输出**:
- `corpus_prefix_hash` (用于调度)
- `evidence_prefix_hash` (用于机制验证)
- `NeuralStateHandle` (control-plane metadata)

**边界评价**: ✅ **清晰**
- 不依赖 LLM runtime
- 不读取 vLLM metrics
- 不修改 prompt

#### 策略层边界

**输入**:
- Task spec, retrieval pool, role instruction
- Corpus prefix hash (from 估算层)

**输出**:
- `CompiledRolePrompt` (包含 shared prefix / role suffix)
- `PrefixLayoutPlan` (审计信息)
- Task schedule plan (cache-friendly / cache-hostile)

**边界评价**: ⚠️ **部分模糊**
- `role_path.py` 既编译 prompt，又调用 LLM
- `kv_prefix_schedule.py` 生成 schedule，但不执行
- 建议：明确"策略制定"和"策略执行"的分界线

#### 观测层边界

**输入**:
- Benchmark case reports (from runtime)
- vLLM `/metrics` endpoint (from external)

**输出**:
- KV reuse summary (corpus/evidence hash counts)
- vLLM prefix cache metrics delta
- TTFT measurements

**边界评价**: ✅ **清晰**
- 只读，不修改 runtime 状态
- 独立脚本和 library 函数明确分离

### 2.3 与主流程的集成点评估

#### 集成点 1: Continuous Benchmark

**路径**: `v2/benchmark/continuous_runner.py` → `kv_analysis.summarize_case_kv_reuse`

**集成方式**:
```python
kv_summary = summarize_case_kv_reuse(cases)
evidence_pack["kv_reuse_analysis"] = kv_summary
```

**评价**: ✅ **正确**
- 不修改主流程逻辑
- KV 字段作为 optional metadata 追加

#### 集成点 2: Role Prompt Compilation

**路径**: `v2/runtime/role_path.py` → `compile_prefix_layout`

**集成方式**:
```python
if os.getenv("STATEBUS_PREFIX_ALIGNMENT_MODE") == "shared_evidence_prefix":
    # Compile shared prefix + role suffix
else:
    # Default: full prompt per role
```

**评价**: ⚠️ **需要改进**
- 环境变量控制不够显式
- 建议：通过 `role_path_mode` 参数传递，而非全局环境变量

#### 集成点 3: Benchmark Family Loading

**路径**: `v2/benchmark/family_loader.py` → explicit family `kv_prefix_reuse_v1`

**集成方式**:
```bash
python -m v2.benchmark.live_runner --family kv_prefix_reuse_v1
```

**评价**: ✅ **正确**
- Explicit family 不进入默认 collection
- 避免混入 non-KV baseline

### 2.4 架构改进建议

#### 优先级 P1

1. **分离策略制定和策略执行**
   ```python
   # Before
   class RolePathExecutor:
       def execute_role(...):
           prompt = compile_prefix_layout(...)  # 策略
           result = llm_client.call(prompt)      # 执行
   
   # After
   class PrefixLayoutCompiler:
       def compile(...) -> CompiledRolePrompt: ...
   
   class RolePathExecutor:
       def execute_role(compiled_prompt: CompiledRolePrompt): ...
   ```

2. **统一观测层数据结构**
   ```python
   @dataclass
   class KVObservabilityReport:
       corpus_reuse_summary: dict
       vllm_metrics_delta: VllmPrefixCacheMetrics
       ttft_measurements: list[float]
       experiment_metadata: dict
   ```

#### 优先级 P2

3. **集中配置管理**
   ```yaml
   # kv_config.yaml
   prefix_alignment:
     enabled: false
     mode: shared_evidence_prefix
   
   evidence_pruning:
     enabled: false
     importance_threshold: 0.6
   
   scheduling:
     cache_affinity_window_size: 5
   ```

