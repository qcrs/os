# 第四部分：实验设计方案

## 1. 数据集选择

### 1.1 是否只用 kv_prefix_reuse_v1

**推荐**: 否，需要组合使用多个数据集

**理由**:
1. `kv_prefix_reuse_v1` 是专门的机制验证数据集，规模小（10 轮）
2. 只用它无法证明 KV 在真实 formal 场景的有效性
3. 需要在已有 formal 数据集上补充 KV 对比

### 1.2 推荐数据集组合

#### Tier 1: 机制验证（必须）

**数据集**: `kv_prefix_reuse_v1`

**规模**: 10 轮，2 corpus

**目标**: 证明 prefix alignment + corpus scheduling 机制有效

**对比组**:
- Cache-friendly scheduling
- Cache-hostile scheduling

**必须采集的指标**:
- `vllm_prefix_cache_hit_rate`
- `ttft_ms` (p50, p95)
- `quality_floor_pass_rate`

#### Tier 2: 真实场景验证（推荐）

**数据集**: `cross_period_financial_v1` 或 `long_doc_metric_replay_v1`

**规模**: 18-20 轮（已有 corpus prefix 复用信号）

**目标**: 证明 KV 在真实 formal 场景的增量收益

**对比组**:
- Local Non-KV baseline
- Local KV enabled

**必须采集的指标**:
- Quality (≥ Non-KV - 1)
- Prompt tokens delta
- TTFT delta
- Cache hit rate

#### Tier 3: 全量验证（可选）

**数据集**: Full formal 25 cases

**规模**: 25 轮

**目标**: 证明 KV 不损失质量，广泛适用

**对比组**:
- Local Non-KV baseline (25/25 目标)
- Local KV enabled (≥ 24/25 目标)

**采集指标**: 同 Tier 2

### 1.3 数据集规模权衡

| 方案 | 规模 | 预计时间 | 证明力度 | 推荐 |
|------|------|---------|---------|------|
| 只跑 Tier 1 | 10 轮 | 1-2 小时 | 弱（只是机制 demo） | ❌ |
| Tier 1 + Tier 2 | 30 轮 | 3-5 小时 | 中（机制 + 真实场景） | ✅ |
| Tier 1 + Tier 2 + Tier 3 | 55 轮 | 6-10 小时 | 强（全面验证） | ⚠️（时间允许再做） |

**推荐**: Tier 1 + Tier 2（必须），Tier 3（如果 Phase 3 时间充足）

---

## 2. 对照组设计

### 2.1 对照组定义

#### Baseline 1: API 模式（已完成，不重跑）

**配置**:
- `role_path_mode: api`
- `llm_provider: openai_compatible` (API endpoint)
- No prefix caching observability

**结果**: 25/25 quality pass, prompt token baseline

**用途**: 作为 headline quality baseline

#### Baseline 2: Local Non-KV

**配置**:
```yaml
role_path_mode: local_vllm
llm_base_url: http://localhost:8000/v1
llm_model: qwen3-32b
prefix_alignment_mode: disabled
enable_prefix_caching: true  # vLLM 自动 APC，但 StateBus 不主动对齐
```

**预期**:
- Quality: ≥ 24/25
- vLLM cache hit rate: 低（偶然命中）
- TTFT: baseline

**用途**: 本地环境公平对比基线

#### Treatment 1: Local KV (Prefix Alignment Only)

**配置**:
```yaml
role_path_mode: local_vllm
llm_base_url: http://localhost:8000/v1
llm_model: qwen3-32b
prefix_alignment_mode: shared_evidence_prefix  # 核心差异
enable_prefix_caching: true
```

**预期**:
- Quality: ≥ Baseline 2 - 1
- vLLM cache hit rate: 中（prefix alignment 提升）
- TTFT: -15% to -30%
- Prompt tokens: 可能略增（shared prefix overhead）

**用途**: 证明 prefix alignment 机制有效

#### Treatment 2: Local KV (Prefix Alignment + Corpus Scheduling)

**配置**:
```yaml
role_path_mode: local_vllm
prefix_alignment_mode: shared_evidence_prefix
enable_prefix_caching: true
task_schedule_plan: cache_friendly  # 核心差异
```

**预期**:
- Quality: = Treatment 1
- vLLM cache hit rate: 高（alignment + scheduling）
- TTFT: -25% to -40%

**用途**: 证明 corpus scheduling 增量收益

#### Treatment 3: Local KV (Full Stack)

**配置**:
```yaml
role_path_mode: local_vllm
prefix_alignment_mode: shared_evidence_prefix
enable_prefix_caching: true
task_schedule_plan: cache_friendly
evidence_pruning_enabled: true  # 核心差异
evidence_pruning_threshold: 0.6
```

**预期**:
- Quality: ≥ Treatment 2 - 1
- Prompt tokens: -5% to -15% (pruning 收益)
- TTFT: -30% to -50%

**用途**: 证明 evidence pruning 增量收益（如果质量不损失）

### 2.2 控制变量和自变量

| 变量 | Baseline 2 | Treatment 1 | Treatment 2 | Treatment 3 |
|------|-----------|-------------|-------------|-------------|
| **控制变量** |
| 模型 | Qwen3-32B | Qwen3-32B | Qwen3-32B | Qwen3-32B |
| 量化 | fp16 | fp16 | fp16 | fp16 |
| Temperature | 0.0 | 0.0 | 0.0 | 0.0 |
| vLLM APC | ✅ | ✅ | ✅ | ✅ |
| **自变量** |
| Prefix alignment | ❌ | ✅ | ✅ | ✅ |
| Corpus scheduling | ❌ | ❌ | ✅ | ✅ |
| Evidence pruning | ❌ | ❌ | ❌ | ✅ |

### 2.3 实验矩阵

**完整实验矩阵**:

| 实验编号 | 数据集 | 配置 | 预计时间 | 优先级 |
|---------|--------|------|---------|--------|
| E1 | kv_prefix_reuse_v1 | Baseline 2 | 30 min | P0 |
| E2 | kv_prefix_reuse_v1 | Treatment 1 | 30 min | P0 |
| E3 | kv_prefix_reuse_v1 | Treatment 2 (cache-friendly) | 30 min | P0 |
| E4 | kv_prefix_reuse_v1 | Treatment 2 (cache-hostile) | 30 min | P0 |
| E5 | cross_period_financial_v1 | Baseline 2 | 1 hour | P1 |
| E6 | cross_period_financial_v1 | Treatment 1 | 1 hour | P1 |
| E7 | cross_period_financial_v1 | Treatment 2 | 1 hour | P1 |
| E8 | Full formal 25 | Baseline 2 | 3 hours | P2 |
| E9 | Full formal 25 | Treatment 1 | 3 hours | P2 |

**必须跑**: E1-E4 (机制验证)

**推荐跑**: E5-E7 (真实场景)

**可选跑**: E8-E9 (全量验证，如果时间允许)

---

## 3. 指标采集方案

### 3.1 必须采集的指标清单

#### KV 特有指标

| 指标 | 来源 | 采集方式 | 用途 |
|------|------|---------|------|
| `vllm_prefix_cache_queries_total` | vLLM `/metrics` | Before/after delta | 总查询次数 |
| `vllm_prefix_cache_hits_total` | vLLM `/metrics` | Before/after delta | 总命中次数 |
| `vllm_prefix_cache_hit_rate` | 计算 | hits / queries | 命中率（核心指标） |
| `ttft_ms` (p50, p95, max) | Streaming probe | Per-request timestamp | 首 token 延迟 |
| `corpus_prefix_hash_reuse_count` | StateBus telemetry | Continuous report | Corpus 复用次数 |
| `evidence_prefix_hash_reuse_count` | StateBus telemetry | Continuous report | Evidence 复用次数 |
| `estimated_prefix_tokens` | StateBus telemetry | Per-case metadata | 理论 prefix token 数 |

#### 通用质量/性能指标

| 指标 | 来源 | 用途 |
|------|------|------|
| `quality_floor_pass` | Benchmark validator | 质量门（必须 ≥ baseline - 1） |
| `prompt_tokens` | LLM usage | Token 消耗（可能因 shared prefix 略增） |
| `completion_tokens` | LLM usage | 生成 token（应该相同） |
| `total_tokens` | LLM usage | 总 token |
| `task_ms` | Benchmark timer | 端到端延迟（包含网络） |
| `llm_ms` | LLM timer | 纯 LLM 推理时间 |

### 3.2 指标来源详细说明

#### 来源 1: vLLM `/metrics` endpoint

**采集时机**: 每个实验前后

**采集脚本**:
```python
from v2.runtime.vllm_metrics import fetch_vllm_prefix_cache_metrics

metrics_before = fetch_vllm_prefix_cache_metrics("http://localhost:8000/metrics")
# 运行 benchmark
metrics_after = fetch_vllm_prefix_cache_metrics("http://localhost:8000/metrics")

delta = {
    "queries": metrics_after.queries_total - metrics_before.queries_total,
    "hits": metrics_after.hits_total - metrics_before.hits_total,
    "hit_rate": delta["hits"] / delta["queries"] if delta["queries"] > 0 else 0.0,
}
```

**输出**: `experiment_metrics_delta.json`

#### 来源 2: StateBus telemetry

**采集时机**: 每个 case 结束时

**采集路径**: `workspaces/**/logs/telemetry.json`

**关键字段**:
```json
{
  "neural_prefix_reuse": {
    "corpus_prefix_hash": "abc123...",
    "evidence_prefix_hash": "def456...",
    "estimated_prefix_tokens": 2048,
    "cache_hit_count_estimate": 1
  }
}
```

**聚合脚本**: `v2/benchmark/kv_analysis.py::summarize_case_kv_reuse`

#### 来源 3: Streaming TTFT probe

**采集时机**: 每个 LLM 请求时（如果启用 streaming）

**采集方式**:
```python
request_started_ns = time.perf_counter_ns()
stream_response = client.chat.completions.create(..., stream=True)
ttft_ms = 0.0
for chunk in stream_response:
    if chunk.choices[0].delta.content and ttft_ms == 0.0:
        ttft_ms = (time.perf_counter_ns() - request_started_ns) / 1e6
        break
```

**输出**: Per-request `ttft_ms` 写入 telemetry

#### 来源 4: Benchmark report

**采集时机**: 整个 suite 结束时

**采集路径**: `runtime/**/benchmark_reports/*.json`

**关键字段**:
- `layers[2].quality_floor_pass` (L3 quality)
- `layers[2].prompt_tokens` (L3 prompt tokens)
- `waterfall_metrics.task_ms` (端到端延迟)

### 3.3 采集脚本和自动化方案

**自动化脚本**: `scripts/run_kv_experiment.sh`

```bash
#!/bin/bash
set -e

EXPERIMENT_ID="$1"
DATASET="$2"
CONFIG="$3"
OUTPUT_DIR="/home/qcrs/statebus/experiments/${EXPERIMENT_ID}"

mkdir -p "${OUTPUT_DIR}"

# 1. 采集 metrics before
curl -s http://localhost:8000/metrics > "${OUTPUT_DIR}/metrics_before.txt"

# 2. 运行 benchmark
python -m v2.benchmark.live_runner \
  --suite "${DATASET}" \
  --role-path-mode local_vllm \
  --config "${CONFIG}" \
  --output-dir "${OUTPUT_DIR}/run" \
  | tee "${OUTPUT_DIR}/console.log"

# 3. 采集 metrics after
curl -s http://localhost:8000/metrics > "${OUTPUT_DIR}/metrics_after.txt"

# 4. 计算 delta
python scripts/compute_vllm_metrics_delta.py \
  --before "${OUTPUT_DIR}/metrics_before.txt" \
  --after "${OUTPUT_DIR}/metrics_after.txt" \
  --output "${OUTPUT_DIR}/metrics_delta.json"

# 5. 聚合 telemetry
python scripts/aggregate_kv_telemetry.py \
  --run-dir "${OUTPUT_DIR}/run" \
  --output "${OUTPUT_DIR}/kv_summary.json"

echo "Experiment ${EXPERIMENT_ID} completed. Results in ${OUTPUT_DIR}"
```

**使用示例**:
```bash
bash scripts/run_kv_experiment.sh \
  E1 \
  kv_prefix_reuse_v1 \
  configs/local_non_kv_baseline.yaml

bash scripts/run_kv_experiment.sh \
  E2 \
  kv_prefix_reuse_v1 \
  configs/local_kv_prefix_alignment.yaml
```

---

## 4. 实验规模估算

### 4.1 预计运行轮次和时间

| 实验 | 数据集 | Cases | 预计 LLM 调用 | 预计时间 | 累计时间 |
|------|--------|------|--------------|---------|---------|
| E1 | kv_prefix_reuse_v1 | 10 | ~40 | 30 min | 0.5 hr |
| E2 | kv_prefix_reuse_v1 | 10 | ~40 | 30 min | 1.0 hr |
| E3 | kv_prefix_reuse_v1 | 10 | ~40 | 30 min | 1.5 hr |
| E4 | kv_prefix_reuse_v1 | 10 | ~40 | 30 min | 2.0 hr |
| E5 | cross_period_financial_v1 | 18 | ~72 | 60 min | 3.0 hr |
| E6 | cross_period_financial_v1 | 18 | ~72 | 60 min | 4.0 hr |
| E7 | cross_period_financial_v1 | 18 | ~72 | 60 min | 5.0 hr |
| E8 | Full formal 25 | 25 | ~100 | 180 min | 8.0 hr |
| E9 | Full formal 25 | 25 | ~100 | 180 min | 11.0 hr |

**必须跑 (P0)**: E1-E4 = 2 小时

**推荐跑 (P0+P1)**: E1-E7 = 5 小时

**全量跑 (P0+P1+P2)**: E1-E9 = 11 小时

### 4.2 GPU 资源消耗估算

**单个实验**:
- GPU 利用率: 60-80%（推理时）
- VRAM 占用: 68-72 GB (Qwen3-32B fp16 + KV cache)
- 功耗: ~300W

**并行策略**: 不建议并行（StateBus benchmark 顺序执行，KV cache 会互相污染）

**总 GPU 时间**: 11 小时（如果全量跑）

### 4.3 磁盘空间需求

**单个实验产物**:
- Telemetry JSON: ~50 MB
- Benchmark reports: ~10 MB
- Prompt slices: ~100 MB
- vLLM metrics: ~1 MB
- **总计**: ~160 MB per experiment

**全量实验 (9 个)**: ~1.5 GB

**推荐预留**: 5 GB（包含 buffer）

---

## 5. Claim 边界定义

### 5.1 实验成功后可以 claim 什么

#### 如果 Tier 1 (kv_prefix_reuse_v1) 成功

**可以 claim**:
- "StateBus 通过 prefix alignment 和 corpus-aware scheduling，在专门设计的 KV 机制验证数据集上，实现了 vLLM automatic prefix caching 的 X% hit rate，TTFT 降低 Y%"
- "Cache-friendly scheduling 相比 cache-hostile scheduling，TTFT 降低 Z%"

**不能 claim**:
- "KV cache 在真实 formal 场景广泛有效"（只是机制 demo）
- "KV 传递"或"跨 Agent KV 共享"（这是 Engine-Local Prefix Reuse）

#### 如果 Tier 1 + Tier 2 成功

**可以 claim**:
- 上述 Tier 1 claim
- "在真实 formal 场景（cross_period_financial_v1）中，KV 优化在保持质量（≥ N/M）的前提下，TTFT 降低 Y%，cache hit rate X%"

**不能 claim**:
- "所有 formal 场景都有 KV 收益"（只验证了一个 family）

#### 如果 Tier 1 + Tier 2 + Tier 3 成功

**可以 claim**:
- 上述 Tier 1 + Tier 2 claim
- "在全量 formal 25 cases 中，KV 优化保持质量（≥ N/25），平均 TTFT 降低 Y%"

**不能 claim**:
- "KV tensor 传递"或"跨进程 KV 共享"

### 5.2 不能 claim 什么（即使实验成功）

| 错误 claim | 为什么不能说 | 正确说法 |
|-----------|------------|---------|
| "实现了 KV cache 传递" | StateBus 不持有 KV tensor | "实现了 Engine-Local Prefix Reuse 控制面" |
| "跨 Agent KV 共享" | KV 在 vLLM engine 内部，不跨进程 | "Multi-agent prefix alignment 提高了 engine 内部 APC 命中率" |
| "KV 压缩" | 没有修改模型内部 KV | "Input-level evidence pruning 减少了需要 prefill 的 token" |
| "比 API 更快" | 本地 vLLM 可能有网络优势 | "在相同本地环境下，KV 优化相比 Non-KV baseline 降低 TTFT" |
| "所有场景都有收益" | 只验证了部分 family | "在验证的 X 个 family 中，Y 个有显著 KV 收益" |

### 5.3 答辩口径建议

**预期问题 1**: "你的 KV cache 是怎么在 Agent 间传递的？"

**标准回答**:
> "StateBus 的 KV 方向不是传递 KV tensor，而是在 LLM engine 外部提供 prefix alignment、corpus-aware scheduling 和 lease tracking，让 vLLM 的 automatic prefix caching 从偶然命中变成可规划的优化对象。具体来说，我们通过 Prefix Layout Compiler 让多个 Agent 共享相同的 evidence prefix，通过 Corpus-Aware Scheduling 把同文档任务排在一起，提高 cache 驻留时间。实测数据显示，cache hit rate 从 baseline 的 X% 提升到 Y%，TTFT 降低 Z%。"

**预期问题 2**: "你的 KV 优化相比 vLLM 自带的 APC 有什么区别？"

**标准回答**:
> "vLLM APC 是被动命中：只有当两个请求的 prompt 前缀完全相同时才能命中。StateBus 的创新在于主动构造这种前缀相等：我们在 runtime 层面编译 prompt，让 Planner/Retriever/Executor/Summarizer 四个角色共享相同的 evidence prefix，再追加角色后缀；同时通过 corpus-aware scheduling，让同文档任务连续执行，避免 cache 被无关任务挤掉。实验证明，这种主动规划能将 cache hit rate 从 X% 提升到 Y%。"

**预期问题 3**: "为什么不实现真正的跨模型 KV 共享？"

**标准回答**:
> "跨模型 KV tensor 共享有两个基本约束：一是不同模型的 KV 格式不兼容，二是 KV 是模型内部短生命周期对象，跨进程传递成本高。我们的定位是 Cache-Aware Agent Runtime，在不修改 LLM engine 的前提下，通过控制面优化（prefix alignment、scheduling、pruning）来提高 engine 内部 cache 的利用率。这个方向工程可行性高，且对模型和 engine 无侵入。"

