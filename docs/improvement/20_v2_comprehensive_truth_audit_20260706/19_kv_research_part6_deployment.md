# 第三部分：本地部署与测试策略

## 1. GPU 资源评估

### 1.1 当前硬件配置

**检测结果**:
```
3× NVIDIA A100 80GB PCIe
- 单卡显存: 81920 MiB (80 GB)
- Driver 版本: 565.57.01
- Compute Capability: 8.0
- CUDA 版本: 12.1 (cu121)
```

**评估结论**: ✅ **资源充足，支持所有主流模型**

### 1.2 不同模型的资源需求对比

#### Qwen3-8B

| 量化方案 | VRAM 需求 | KV Cache (8K ctx) | 推荐场景 |
|---------|-----------|-------------------|---------|
| fp16 | ~16 GB | ~4 GB | 质量验证（单卡 A100 舒适） |
| AWQ 4-bit | ~5 GB | ~4 GB | 快速迭代（单卡 3090/4090 可用） |
| int8 | ~8 GB | ~4 GB | 平衡方案 |

**推荐**: fp16（质量最优，A100 显存充足）

#### Qwen3-32B

| 量化方案 | VRAM 需求 | KV Cache (8K ctx) | 推荐场景 |
|---------|-----------|-------------------|---------|
| fp16 | ~64 GB | ~8 GB | 标准实验（单卡 A100 80GB 可用） |
| AWQ 4-bit | ~20 GB | ~8 GB | 快速迭代（单卡 A100 舒适） |
| int8 | ~32 GB | ~8 GB | 平衡方案 |

**推荐**: fp16（质量最优，单卡 A100 80GB 足够）

#### Qwen3-72B

| 量化方案 | VRAM 需求 | KV Cache (8K ctx) | 推荐场景 |
|---------|-----------|-------------------|---------|
| fp16 | ~144 GB | ~16 GB | 需要 2 卡（tensor parallel） |
| AWQ 4-bit | ~40 GB | ~16 GB | 单卡 A100 可用 |
| int8 | ~72 GB | ~16 GB | 单卡 A100 勉强（需要 offload） |

**推荐**: AWQ 4-bit（单卡可用，质量损失可接受）

### 1.3 KV Cache 容量估算

**计算公式**（基于 `v2/runtime/kv_budget.py`）:
```
KV bytes per token = num_layers × 2 (K+V) × num_kv_heads × head_dim × dtype_bytes
```

**Qwen3-32B fp16**:
- num_layers: 64
- num_kv_heads: 8
- head_dim: 128
- dtype_bytes: 2 (fp16)
- **KV bytes per token**: 64 × 2 × 8 × 128 × 2 = 262,144 bytes ≈ 256 KB/token

**8K context KV cache**:
- 8192 tokens × 256 KB = 2,097,152 KB ≈ **2 GB per sequence**

**单卡 A100 80GB 可并发序列数**:
- 模型权重: 64 GB (fp16)
- 可用 KV cache: 80 - 64 = 16 GB
- 并发序列数 (8K context): 16 GB / 2 GB = **8 sequences**

**评估**: ✅ **足够支持 StateBus benchmark（max_num_seqs=1 已够用）**

---

## 2. 模型选择建议

### 2.1 主模型推荐

**推荐**: Qwen3-32B fp16

**理由**:
1. **质量充分**: 32B 对 StateBus 的结构化任务（route 选择、数值提取、摘要）能力足够
2. **显存舒适**: 单卡 A100 80GB 可运行 fp16 + 8K context
3. **对比公平**: 与 Non-KV API baseline 使用相同模型规模
4. **社区成熟**: Qwen3 系列在 vLLM 上支持良好

**不推荐 Qwen3-8B** 的原因:
- 质量可能不如 API baseline (通常是 32B+)
- 无法公平对比 Non-KV vs KV

**不推荐 Qwen3-72B** 的原因:
- 需要 tensor parallel（2 卡），部署复杂度高
- 收益不明显（StateBus 任务对 72B vs 32B 增益有限）

### 2.2 备选方案

**备选 1**: Qwen3-32B AWQ 4-bit

**适用场景**: 如果 fp16 OOM 或需要更高并发

**质量验证方法**:
1. 先用 AWQ 4-bit 跑 5 个 formal cases
2. 对比 AWQ vs API 的 quality_floor_pass
3. 如果 AWQ quality < API quality - 2，则改用 fp16

**备选 2**: Qwen3-14B fp16

**适用场景**: 如果 32B 质量不如 API，降级到 14B 可能反而更接近

**不推荐**: 除非 32B 验证失败

### 2.3 模型质量验证方案

**目标**: 确保本地模型质量 ≥ API baseline 质量

**验证步骤**:

#### Step 1: Smoke Test (1 case)

```bash
# API baseline (已有结果)
API quality: 1/1 pass

# 本地 vLLM
python -m v2.benchmark.live_runner \
  --suite preflight \
  --role-path-mode local_vllm \
  --llm-base-url http://localhost:8000/v1 \
  --llm-model qwen3-32b
```

**Go/No-go**: 如果 local_vllm quality < 1/1，停止并检查模型部署

#### Step 2: Mini Formal (5 cases)

```bash
python -m v2.benchmark.live_runner \
  --suite formal \
  --benchmark-tier dev \
  --role-path-mode local_vllm \
  --max-cases 5
```

**预期结果**: 5/5 quality pass

**Go/No-go**: 如果 local_vllm quality < 4/5，考虑换更大模型或改用 API

#### Step 3: Full Formal (25 cases)

```bash
python -m v2.benchmark.live_runner \
  --suite formal \
  --benchmark-tier formal \
  --role-path-mode local_vllm
```

**预期结果**: ≥ 24/25 quality pass（与 API baseline 相当）

**Go/No-go**: 如果 local_vllm quality < 22/25，KV 实验结果不可作为 headline

---

## 3. 全局测试策略决策

### 3.1 三种策略对比

#### 选项 A: 全部本地完成

**方案**: Non-KV 和 KV 都在本地 vLLM 上验证

**优点**:
- 环境一致，公平对比
- KV metrics 可采集

**缺点**:
- 本地模型质量可能 < API
- 如果质量不足，Non-KV baseline 也受损

**适用场景**: 本地模型质量 ≥ API 质量

#### 选项 B: Non-KV 用 API，KV 用本地

**方案**: 保留 API 的 25/25 结果，KV 在本地补充

**优点**:
- Non-KV baseline 保持最强质量
- KV 实验独立验证

**缺点**:
- 对比不公平（不同模型）
- KV 收益可能部分来自模型差异

**适用场景**: 本地模型质量 < API 质量

#### 选项 C: 双轨验证（推荐）

**方案**:
1. **Non-KV baseline**: 保留 API 模式的 25/25 结果（已完成）
2. **KV 增量验证**: 在本地 vLLM 上跑 KV vs Non-KV 对比
3. **质量门**: 本地 Non-KV 必须 ≥ 24/25，否则只作为机制验证

**优点**:
- 保留最强 baseline（API 25/25）
- KV 增量收益在同环境下公平对比
- 风险隔离：KV 失败不影响 Non-KV claim

**缺点**:
- 实验设计复杂（需要明确度量 KV 增量收益）

**推荐理由**:
- 赛题三个核心维度已由 Non-KV API 完成
- KV 是创新加分项，不是必选项
- 双轨策略风险最低

### 3.2 推荐方案详细设计

**Phase 1: 本地 Non-KV 质量验证**

```bash
# 目标: 证明本地模型 ≥ API 质量
python -m v2.benchmark.live_runner \
  --suite formal \
  --role-path-mode local_vllm \
  --embedding-mode local
```

**预期**: ≥ 24/25

**如果 < 24/25**: 
- 换更大模型（72B AWQ）
- 或降级 KV claim 为 "mechanism probe only"

**Phase 2: 本地 KV vs Non-KV 对比**

```bash
# Non-KV baseline (local)
python -m v2.benchmark.live_runner \
  --suite formal \
  --role-path-mode local_vllm \
  --prefix-alignment disabled

# KV treatment (local)
export STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix
python -m v2.benchmark.live_runner \
  --suite formal \
  --role-path-mode local_vllm \
  --prefix-alignment enabled
```

**对比指标**:
- Quality: KV 不能损失质量（≥ Non-KV - 1）
- Prompt tokens: KV 应该减少（目标 -10% to -20%）
- TTFT: KV 应该更低（目标 -15% to -30%）
- vLLM prefix_cache_hit_rate: KV > 0.5

**Phase 3: KV 专用数据集验证**

```bash
python -m v2.benchmark.live_runner \
  --family kv_prefix_reuse_v1 \
  --role-path-mode local_vllm \
  --prefix-alignment enabled
```

**对比**: cache-friendly vs cache-hostile scheduling

**预期**: cache-friendly 的 TTFT < cache-hostile 的 TTFT（≥ 20% 差异）

### 3.3 实验公平性保证措施

1. **同一模型**: 本地 KV vs Non-KV 使用完全相同的模型和量化方案
2. **同一 vLLM 配置**: `--max-model-len`, `--gpu-memory-utilization` 固定
3. **同一温度**: temperature=0.0 (deterministic)
4. **同一 random seed**: 如果有采样，固定 seed
5. **隔离运行**: 每组实验单独启动 vLLM，避免 cache 污染
6. **重复验证**: 关键对比至少跑 2 遍

---

## 4. 本地环境部署清单

### 4.1 vLLM 安装

**推荐版本**: vLLM 0.8.0+（支持 automatic prefix caching）

```bash
# 在 host 或容器内
pip install vllm==0.8.0
pip install openai  # vLLM OpenAI-compatible client
```

**验证**:
```bash
python -c "import vllm; print(vllm.__version__)"
```

### 4.2 模型下载

**推荐路径**: `/home/qcrs/statebus/models/`

```bash
# Qwen3-32B fp16
huggingface-cli download Qwen/Qwen3-32B \
  --local-dir /home/qcrs/statebus/models/Qwen3-32B

# 或使用已有模型（如果存在）
ls /home/qcrs/statebus/models/
```

**验证**:
```bash
ls /home/qcrs/statebus/models/Qwen3-32B/config.json
```

### 4.3 vLLM 启动命令

**标准配置**:
```bash
python -m vllm.entrypoints.openai.api_server \
  --model /home/qcrs/statebus/models/Qwen3-32B \
  --dtype float16 \
  --enable-prefix-caching \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.85 \
  --max-num-seqs 1 \
  --host 0.0.0.0 \
  --port 8000 \
  --served-model-name qwen3-32b
```

**参数说明**:
- `--enable-prefix-caching`: 启用 APC（核心）
- `--max-model-len 8192`: 最大 context（StateBus formal 约 4K）
- `--gpu-memory-utilization 0.85`: 85% VRAM 用于 KV cache
- `--max-num-seqs 1`: StateBus benchmark 顺序执行，不需要批处理

**后台运行**:
```bash
nohup python -m vllm.entrypoints.openai.api_server \
  --model /home/qcrs/statebus/models/Qwen3-32B \
  --dtype float16 \
  --enable-prefix-caching \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.85 \
  --max-num-seqs 1 \
  --host 0.0.0.0 \
  --port 8000 \
  --served-model-name qwen3-32b \
  > /home/qcrs/statebus/logs/vllm_server.log 2>&1 &
```

### 4.4 配置文件修改

**文件**: `deploy/statebus_llm.yaml.local`

```yaml
# 添加 local_vllm 配置
local_vllm:
  llm_provider: openai_compatible
  base_url: http://localhost:8000/v1
  api_key: "EMPTY"
  model: qwen3-32b
  temperature: 0.0
  max_tokens: 2048
  
  # KV 相关配置
  prefix_alignment_mode: disabled  # 默认关闭，实验时显式启用
  enable_prefix_caching: true
  metrics_url: http://localhost:8000/metrics
```

### 4.5 验证步骤

#### Step 1: 检查 vLLM 启动

```bash
curl http://localhost:8000/health
# 预期: {"status": "ok"}
```

#### Step 2: 检查模型加载

```bash
curl http://localhost:8000/v1/models
# 预期: 返回 "qwen3-32b"
```

#### Step 3: Smoke test

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-32b",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 10
  }'
# 预期: 返回正常 completion
```

#### Step 4: 检查 prefix cache metrics

```bash
curl http://localhost:8000/metrics 2>/dev/null | grep prefix_cache
# 预期: 返回 vllm:gpu_prefix_cache_* 指标
```

#### Step 5: StateBus smoke test

```bash
python -m v2.runtime.smoke --role-path-mode local_vllm
# 预期: exit 0, quality pass
```

