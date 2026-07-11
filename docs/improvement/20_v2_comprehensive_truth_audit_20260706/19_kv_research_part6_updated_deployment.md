# 第三部分：本地部署与测试策略（更新版）

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

### 1.2 可用模型清单

**实际模型路径**: `/data/models/`

```bash
ls /data/models/
```

**可用模型**:
```
Llama-2-7b-hf                  # 7B, fp16 ~14GB
Llama-3.1-8B-Instruct          # 8B, fp16 ~16GB
Llama3-8B                      # 8B, fp16 ~16GB
Qwen1.5-1.8B-Chat              # 1.8B, fp16 ~4GB
Qwen2.5-3B-Instruct-AWQ        # 3B, AWQ 4-bit ~2GB
Qwen2.5-7B-Instruct            # 7B, fp16 ~14GB
Qwen2.5-7B-Instruct-AWQ        # 7B, AWQ 4-bit ~4GB
Qwen2.5-14B-Instruct           # 14B, fp16 ~28GB  ✅ 推荐
Qwen3-0.6B                     # 0.6B, fp16 ~1.2GB
Qwen3-4B-Instruct-2507         # 4B, fp16 ~8GB
Qwen3-8B                       # 8B, fp16 ~16GB
Qwen3-32B                      # 32B, fp16 ~64GB  ✅ 推荐
Qwen3.5-27B                    # 27B (hybrid config)
Qwen3-Embedding-0.6B           # Embedding model (已用于 local embedding)
Qwen3-Reranker-0.6B            # Reranker model
Qwen3-VL-4B-Instruct           # Vision-Language model
```

### 1.3 不同模型的资源需求对比

#### Qwen2.5-14B-Instruct（推荐用于快速迭代）

| 量化方案 | VRAM 需求 | KV Cache (8K ctx) | 推荐场景 |
|---------|-----------|-------------------|---------|
| fp16 | ~28 GB | ~4 GB | 质量验证（单卡 A100 舒适） |
| 可用性 | ✅ 已下载 | - | 立即可用 |

**推荐理由**:
- 单卡 A100 80GB 可舒适运行 fp16
- 质量接近 32B（对 StateBus 结构化任务足够）
- 启动快，适合快速迭代

#### Qwen3-32B（推荐用于正式实验）

| 量化方案 | VRAM 需求 | KV Cache (8K ctx) | 推荐场景 |
|---------|-----------|-------------------|---------|
| fp16 | ~64 GB | ~8 GB | 标准实验（单卡 A100 80GB 可用） |
| 可用性 | ✅ 已下载 | - | 立即可用 |

**推荐理由**:
- 质量最优（32B 参数）
- 单卡 A100 80GB 足够（64GB 模型 + 8GB KV）
- 与 Non-KV API baseline 模型规模相当

#### Qwen3.5-27B（不推荐）

| 问题 | 说明 |
|------|------|
| Hybrid config | 包含 text_config，可能不兼容 vLLM 0.8.0 |
| 兼容性风险 | 需要验证，可能需要特殊处理 |
| 推荐 | 除非 32B 无法运行，否则不使用 |

### 1.4 KV Cache 容量估算

**计算公式**（基于 `v2/runtime/kv_budget.py`）:
```
KV bytes per token = num_layers × 2 (K+V) × num_kv_heads × head_dim × dtype_bytes
```

#### Qwen3-32B fp16

**模型参数**:
- num_layers: 64
- num_kv_heads: 8
- head_dim: 128
- dtype_bytes: 2 (fp16)

**KV bytes per token**: 64 × 2 × 8 × 128 × 2 = 262,144 bytes ≈ **256 KB/token**

**8K context KV cache**: 8192 tokens × 256 KB = **2 GB per sequence**

**单卡 A100 80GB 可并发序列数**:
- 模型权重: 64 GB (fp16)
- 可用 KV cache: 80 - 64 = 16 GB
- 并发序列数 (8K context): 16 GB / 2 GB = **8 sequences**

**评估**: ✅ **足够支持 StateBus benchmark（max_num_seqs=1 已够用）**

#### Qwen2.5-14B-Instruct fp16

**模型参数**:
- num_layers: 48
- num_kv_heads: 2
- head_dim: 128
- dtype_bytes: 2 (fp16)

**KV bytes per token**: 48 × 2 × 2 × 128 × 2 = 49,152 bytes ≈ **48 KB/token**

**8K context KV cache**: 8192 tokens × 48 KB = **0.4 GB per sequence**

**单卡 A100 80GB 可并发序列数**:
- 模型权重: 28 GB (fp16)
- 可用 KV cache: 80 - 28 = 52 GB
- 并发序列数 (8K context): 52 GB / 0.4 GB = **130 sequences**

**评估**: ✅ **非常舒适，适合快速迭代**

---

## 2. 模型选择建议

### 2.1 主模型推荐

**推荐**: Qwen3-32B fp16

**理由**:
1. **质量充分**: 32B 对 StateBus 的结构化任务（route 选择、数值提取、摘要）能力最优
2. **显存舒适**: 单卡 A100 80GB 可运行 fp16 + 8K context
3. **对比公平**: 与 Non-KV API baseline 使用相同模型规模
4. **立即可用**: `/data/models/Qwen3-32B` 已下载

**不推荐 Qwen2.5-14B** 的原因:
- 质量可能不如 API baseline（通常是 32B+）
- 但可作为快速迭代的备选

**不推荐 Qwen3.5-27B** 的原因:
- Hybrid config 兼容性风险
- 32B 已经可用，无需冒险

### 2.2 备选方案

**备选 1**: Qwen2.5-14B-Instruct fp16

**适用场景**: 
- Phase 1 快速验证（启动快，显存压力小）
- Phase 2 代码调试（快速迭代）

**质量验证方法**:
1. 先用 14B 跑 5 个 formal cases
2. 对比 14B vs API 的 quality_floor_pass
3. 如果 14B quality < API quality - 2，则必须用 32B

**备选 2**: Qwen3-8B fp16

**适用场景**: 
- 仅用于 smoke test 和快速调试
- 不用于正式实验（质量不足）

### 2.3 模型质量验证方案

**目标**: 确保本地模型质量 ≥ API baseline 质量

**验证步骤**:

#### Step 1: Smoke Test (1 case)

```bash
# API baseline (已有结果)
API quality: 1/1 pass

# 本地 vLLM (14B 快速验证)
python -m v2.benchmark.live_runner \
  --suite preflight \
  --role-path-mode local_vllm \
  --llm-base-url http://localhost:8000/v1 \
  --llm-model qwen2.5-14b-instruct
```

**Go/No-go**: 如果 local_vllm quality < 1/1，停止并检查模型部署

#### Step 2: Mini Formal (5 cases)

```bash
# 用 32B 正式验证
python -m v2.benchmark.live_runner \
  --suite formal \
  --benchmark-tier dev \
  --role-path-mode local_vllm \
  --llm-model qwen3-32b \
  --max-cases 5
```

**预期结果**: 5/5 quality pass

**Go/No-go**: 如果 local_vllm quality < 4/5，考虑换更大模型或改用 API

#### Step 3: Full Formal (25 cases)

```bash
python -m v2.benchmark.live_runner \
  --suite formal \
  --benchmark-tier formal \
  --role-path-mode local_vllm \
  --llm-model qwen3-32b
```

**预期结果**: ≥ 24/25 quality pass（与 API baseline 相当）

**Go/No-go**: 如果 local_vllm quality < 22/25，KV 实验结果不可作为 headline

---

## 3. 全局测试策略决策

### 3.1 推荐方案：选项 C（双轨验证）

**方案**:
1. **Non-KV baseline**: 保留 API 模式的 25/25 结果（已完成）
2. **KV 增量验证**: 在本地 vLLM 上跑 KV vs Non-KV 对比
3. **质量门**: 本地 Non-KV 必须 ≥ 24/25，否则只作为机制验证

**优点**:
- 保留最强 baseline（API 25/25）
- KV 增量收益在同环境下公平对比
- 风险隔离：KV 失败不影响 Non-KV claim

**推荐理由**:
- 赛题三个核心维度已由 Non-KV API 完成
- KV 是创新加分项，不是必选项
- 双轨策略风险最低

---

## 4. 本地环境部署清单

### 4.1 Conda 环境激活

**推荐 Conda 环境**: `/home/qcrs/statebus/conda-envs/vllm-qwen-cu121`

```bash
# 激活环境
conda activate /home/qcrs/statebus/conda-envs/vllm-qwen-cu121

# 或者如果已注册为命名环境
conda activate vllm-qwen-cu121

# 验证环境
which python
# 预期: /home/qcrs/statebus/conda-envs/vllm-qwen-cu121/bin/python

python --version
# 预期: Python 3.10+ or 3.11+

nvidia-smi
# 预期: CUDA 12.1 compatible
```

### 4.2 vLLM 安装（如果环境中没有）

**推荐版本**: vLLM 0.8.0+（支持 automatic prefix caching）

```bash
# 在 conda 环境中
conda activate /home/qcrs/statebus/conda-envs/vllm-qwen-cu121

# 检查是否已安装
python -c "import vllm; print(vllm.__version__)"

# 如果未安装或版本过旧
pip install vllm>=0.8.0
pip install openai  # vLLM OpenAI-compatible client
```

**验证**:
```bash
python -c "import vllm; print(vllm.__version__)"
# 预期: 0.8.0 或更高
```

### 4.3 模型路径确认

**推荐路径**: `/data/models/`（已有模型）

```bash
# 确认 Qwen3-32B 存在
ls /data/models/Qwen3-32B/config.json
# 预期: 文件存在

# 确认 Qwen2.5-14B-Instruct 存在
ls /data/models/Qwen2.5-14B-Instruct/config.json
# 预期: 文件存在
```

**不需要下载**: 所有推荐模型已经下载完成

### 4.4 vLLM 启动命令

#### 配置 1: Qwen3-32B fp16（正式实验）

```bash
conda activate /home/qcrs/statebus/conda-envs/vllm-qwen-cu121

python -m vllm.entrypoints.openai.api_server \
  --model /data/models/Qwen3-32B \
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
- `--model /data/models/Qwen3-32B`: 使用实际路径
- `--enable-prefix-caching`: 启用 APC（核心）
- `--max-model-len 8192`: 最大 context（StateBus formal 约 4K）
- `--gpu-memory-utilization 0.85`: 85% VRAM 用于 KV cache
- `--max-num-seqs 1`: StateBus benchmark 顺序执行，不需要批处理

#### 配置 2: Qwen2.5-14B-Instruct fp16（快速迭代）

```bash
conda activate /home/qcrs/statebus/conda-envs/vllm-qwen-cu121

python -m vllm.entrypoints.openai.api_server \
  --model /data/models/Qwen2.5-14B-Instruct \
  --dtype float16 \
  --enable-prefix-caching \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.80 \
  --max-num-seqs 1 \
  --host 0.0.0.0 \
  --port 8000 \
  --served-model-name qwen2.5-14b-instruct
```

#### 后台运行

```bash
conda activate /home/qcrs/statebus/conda-envs/vllm-qwen-cu121

nohup python -m vllm.entrypoints.openai.api_server \
  --model /data/models/Qwen3-32B \
  --dtype float16 \
  --enable-prefix-caching \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.85 \
  --max-num-seqs 1 \
  --host 0.0.0.0 \
  --port 8000 \
  --served-model-name qwen3-32b \
  > /home/qcrs/statebus/logs/vllm_server.log 2>&1 &

# 查看日志
tail -f /home/qcrs/statebus/logs/vllm_server.log
```

### 4.5 配置文件修改

**文件**: `deploy/statebus_llm.yaml.local`

```yaml
# 添加 local_vllm 配置
local_vllm:
  llm_provider: openai_compatible
  base_url: http://localhost:8000/v1
  api_key: "EMPTY"
  model: qwen3-32b  # 或 qwen2.5-14b-instruct
  temperature: 0.0
  max_tokens: 2048
  
  # KV 相关配置
  prefix_alignment_mode: disabled  # 默认关闭，实验时显式启用
  enable_prefix_caching: true
  metrics_url: http://localhost:8000/metrics
  
  # 模型路径（用于 kv_budget 估算）
  model_path: /data/models/Qwen3-32B
  kv_bytes_per_token: 256  # Qwen3-32B fp16
```

### 4.6 验证步骤

#### Step 1: 检查 vLLM 启动

```bash
curl http://localhost:8000/health
# 预期: {"status": "ok"}
```

#### Step 2: 检查模型加载

```bash
curl http://localhost:8000/v1/models
# 预期: 返回 "qwen3-32b" 或 "qwen2.5-14b-instruct"
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
conda activate /home/qcrs/statebus/conda-envs/vllm-qwen-cu121
python -m v2.runtime.smoke --role-path-mode local_vllm
# 预期: exit 0, quality pass
```

---

## 5. 快速启动脚本

创建一个快速启动脚本方便后续使用：

**文件**: `scripts/start_vllm_qwen32b.sh`

```bash
#!/bin/bash
set -e

MODEL=${1:-Qwen3-32B}
PORT=${2:-8000}

echo "Starting vLLM server with model: $MODEL on port: $PORT"

# 激活 conda 环境
source ~/miniconda3/etc/profile.d/conda.sh
conda activate /home/qcrs/statebus/conda-envs/vllm-qwen-cu121

# 创建日志目录
mkdir -p /home/qcrs/statebus/logs

# 启动 vLLM
nohup python -m vllm.entrypoints.openai.api_server \
  --model /data/models/$MODEL \
  --dtype float16 \
  --enable-prefix-caching \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.85 \
  --max-num-seqs 1 \
  --host 0.0.0.0 \
  --port $PORT \
  --served-model-name $(echo $MODEL | tr '[:upper:]' '[:lower:]' | tr '.' '-') \
  > /home/qcrs/statebus/logs/vllm_${MODEL}_${PORT}.log 2>&1 &

VLLM_PID=$!
echo "vLLM started with PID: $VLLM_PID"
echo "Log file: /home/qcrs/statebus/logs/vllm_${MODEL}_${PORT}.log"

# 等待启动
echo "Waiting for vLLM to start..."
for i in {1..30}; do
  if curl -s http://localhost:$PORT/health > /dev/null 2>&1; then
    echo "vLLM is ready!"
    curl http://localhost:$PORT/v1/models
    exit 0
  fi
  sleep 2
done

echo "vLLM failed to start within 60 seconds"
tail -20 /home/qcrs/statebus/logs/vllm_${MODEL}_${PORT}.log
exit 1
```

**使用方法**:
```bash
# 启动 Qwen3-32B
bash scripts/start_vllm_qwen32b.sh Qwen3-32B 8000

# 启动 Qwen2.5-14B-Instruct
bash scripts/start_vllm_qwen32b.sh Qwen2.5-14B-Instruct 8000

# 停止 vLLM
pkill -f "vllm.entrypoints.openai.api_server"
```

