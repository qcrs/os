# 第一部分：当前 KV 实现审查与问题诊断

## 1. 代码实现质量评估

### 1.1 已实现功能清单

#### 估算层 (Estimation Layer)

**文件**: `v2/runtime/neural_state.py`

| 功能 | 状态 | 质量评估 |
|------|------|---------|
| `build_corpus_prefix_hash` | ✅ 已实现 | 优秀 - 正确分离 corpus identity 和 evidence details |
| `build_evidence_prefix_hash` | ✅ 已实现 | 优秀 - 提供严格的 token-level 相等性检查 |
| `build_neural_prefix_identity` | ✅ 已实现 | 优秀 - 统一的 identity 构造接口 |
| `NeuralPrefixIdentity` | ✅ 已实现 | 优秀 - 包含完整的 claim boundary 声明 |
| `NeuralStateHandle` | ✅ 已实现 | 优秀 - 支持 control-plane 字段（cache_hit_count, eviction_risk, schedule_priority） |
| `EngineLocalPrefixRegistry` | ✅ 已实现 | 优秀 - 正确实现 ensure_handle/lookup，不持有 KV tensor |

**代码质量**: 9/10
- ✅ Claim boundary 清晰标注
- ✅ Schema version 追踪
- ✅ 分离 corpus_prefix_hash (调度用) 和 evidence_prefix_hash (机制验证用)
- ⚠️ 缺少单元测试覆盖

#### 策略层 (Strategy Layer)

**文件**: `v2/runtime/role_path.py`

| 功能 | 状态 | 质量评估 |
|------|------|---------|
| `PrefixLayoutPlan` | ✅ 已实现 | 优秀 - 记录 shared_prefix 去重审计信息 |
| `compile_prefix_layout` | ✅ 已实现 | 良好 - 默认关闭，需要显式 `STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix` |
| Shared prefix 去重逻辑 | ✅ 已实现 | 优秀 - 避免 prefix 和 suffix 双写同一段 evidence |
| Role suffix 编译 | ✅ 已实现 | 良好 - 支持 compact refs 替代完整 evidence payload |

**代码质量**: 8.5/10
- ✅ 默认关闭避免混入 non-KV baseline
- ✅ Prefix/suffix 审计字段完整
- ⚠️ 环境变量控制，缺少配置文件集成
- ⚠️ 去重逻辑分散在 `_render_prompt`，可读性待优化

**文件**: `v2/retrieval/models.py`, `v2/retrieval/pipeline.py`

| 功能 | 状态 | 质量评估 |
|------|------|---------|
| `EvidencePruningHint` | ✅ 已实现 | 良好 - 支持 importance_score 和 keep_in_budget |
| Input-level KV 等价压缩 | ✅ 已实现 | 良好 - 估算 KV/prefill token savings |
| Pruning profile | ✅ 已实现 | 良好 - 记录 pruned chunk count 和 saved tokens |

**代码质量**: 7.5/10
- ✅ 概念清晰：input-level pruning，不是模型内部 KV 剪枝
- ⚠️ 未接入正式 benchmark 链路
- ⚠️ Importance threshold 硬编码，缺少动态调整

#### 观测层 (Observability Layer)

**文件**: `v2/benchmark/kv_analysis.py`

| 功能 | 状态 | 质量评估 |
|------|------|---------|
| `summarize_case_kv_reuse` | ✅ 已实现 | 优秀 - 聚合 corpus/evidence prefix 复用统计 |
| ReplayClass × KV 分层 | ✅ 已实现 | 优秀 - 统一 replay 和 KV 成本模型 |
| Engine-local estimate 聚合 | ✅ 已实现 | 优秀 - 计算 hit rate, saved tokens |

**代码质量**: 9/10
- ✅ Claim boundary 明确标注为 "theoretical estimate"
- ✅ 正确区分 corpus-level 和 engine-local 估算
- ✅ 与 continuous benchmark 集成良好

**文件**: `v2/benchmark/kv_prefix_experiment.py`

| 功能 | 状态 | 质量评估 |
|------|------|---------|
| vLLM metrics probe | ✅ 已实现 | 优秀 - 读取 `/metrics` prefix cache delta |
| Streaming TTFT 采集 | ✅ 已实现 | 优秀 - 正确实现 first-token 时间戳 |
| Shared-prefix vs chain strategy | ✅ 已实现 | 优秀 - 支持两种 prompt 构造对比 |

**代码质量**: 9/10
- ✅ 独立脚本，不污染主 benchmark 链路
- ✅ OpenAI-compatible client，易于本地 vLLM 接入
- ⚠️ 缺少错误重试和 timeout 保护

**文件**: `v2/benchmark/kv_prefix_schedule.py`

| 功能 | 状态 | 质量评估 |
|------|------|---------|
| Cache-friendly scheduling | ✅ 已实现 | 优秀 - 生成 contiguous same-corpus window |
| Cache-hostile scheduling | ✅ 已实现 | 优秀 - 生成 interleaved corpus 对照组 |
| Schedule plan 控制面指标 | ✅ 已实现 | 优秀 - affinity switch, adjacent reuse opportunity |

**代码质量**: 8.5/10
- ✅ 对照实验设计清晰
- ✅ 支持从 manifest 生成 schedule plan
- ⚠️ 未接入正式 runner，需要手动调用

**文件**: `v2/runtime/kv_budget.py`, `scripts/inspect_vllm_kv_budget.py`

| 功能 | 状态 | 质量评估 |
|------|------|---------|
| KV bytes/token 估算 | ✅ 已实现 | 优秀 - 从 HF config 读取 layer/head/dim |
| Quantization savings 估算 | ✅ 已实现 | 优秀 - 支持 bf16/fp16 → int8/int4 收益计算 |
| Concurrency 估算 | ✅ 已实现 | 优秀 - 根据 VRAM 估算 max sequences |

**代码质量**: 9/10
- ✅ 不启动模型即可估算，适合容量规划
- ✅ Claim boundary 明确为 "config-based sizing, not runtime measurement"
- ⚠️ 缺少对 hybrid config (Qwen3.5-27B) 的健壮处理

#### 数据集 (Datasets)

**文件**: `v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/manifest.json`

| 功能 | 状态 | 质量评估 |
|------|------|---------|
| `kv_prefix_reuse_v1` family | ✅ 已实现 | 良好 - 10 轮，2 corpus，明确机制验证目标 |
| Cache-friendly/hostile schedule | ✅ 已声明 | 良好 - manifest 中定义两种顺序 |
| 不进入默认 formal collection | ✅ 已隔离 | 优秀 - 避免混入 headline claim |

**代码质量**: 8/10
- ✅ Explicit family 可加载，不污染默认 suite
- ✅ Claim tier 设置为 `demo_secondary`
- ⚠️ Corpus 数据文件未在仓库中找到（需要确认路径）

### 1.2 发现的问题和技术债务

#### P0（必须修复才能跑 KV 实验）

**无**。当前实现没有阻断性问题。

#### P1（应该修复，显著提升可信度）

1. **缺少单元测试覆盖**
   - `neural_state.py` 的 hash 函数、registry 逻辑无单元测试
   - `kv_analysis.py` 的聚合逻辑无单元测试
   - **建议**: 补充 `tests/v2/test_neural_state.py` 和 `tests/v2/test_kv_analysis.py`

2. **EvidencePruningHint 未接入 benchmark**
   - 代码已实现，但未在正式 run 中启用
   - **建议**: 在 KV 实验中显式启用并采集 pruned_chunk_count 指标

3. **kv_prefix_reuse_v1 corpus 数据文件缺失**
   - Manifest 引用的 `orion_factory_ops_report_2026.md` 和 `nova_retail_ops_report_2026.md` 未找到
   - **建议**: 补充样本文件或更新 manifest 路径

#### P2（可选优化）

1. **环境变量控制改为配置文件**
   - `STATEBUS_PREFIX_ALIGNMENT_MODE` 应该写入 `statebus_llm.yaml.local`
   - **建议**: 在 `v2/runtime/role_path.py` 中支持从 config 读取

2. **kv_prefix_experiment.py 缺少错误处理**
   - 网络错误、vLLM 宕机、metrics 端点不可用时会硬失败
   - **建议**: 添加 try-except 和 fallback

3. **去重逻辑可读性待优化**
   - `_render_prompt` 中 shared-prefix 去重逻辑分散，难以审计
   - **建议**: 提取为独立函数 `_deduplicate_evidence_in_suffix`

### 1.3 需要修复的优先级排序

| 优先级 | 问题 | 预计工作量 | 阻断 KV 实验 |
|--------|------|-----------|-------------|
| P0 | 无 | - | - |
| P1.1 | 补充单元测试 | 2-4 小时 | 否 |
| P1.2 | EvidencePruningHint 接入 | 1-2 小时 | 否（可在 KV 实验中直接启用） |
| P1.3 | 补充 kv_prefix_reuse_v1 corpus 数据 | 1-2 小时 | 是（KV 实验需要这个 family） |
| P2.1 | 配置文件支持 | 1 小时 | 否 |
| P2.2 | 错误处理 | 1 小时 | 否（可在首次失败后修） |
| P2.3 | 去重逻辑重构 | 2 小时 | 否 |

**总预算**: 8-12 小时（1-1.5 天）

**关键路径**: P1.3（corpus 数据）必须在 Phase 3 实验执行前完成。

