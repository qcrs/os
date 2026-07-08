# 本地 vLLM / Qwen 部署说明

更新时间：2026-07-08

这份文档记录当前服务器上 StateBus 接入本地 Qwen/vLLM 的推荐路线。它面向 host-side 开发，不要求 Docker、nsjail 或 openEuler VM。

## 1. 当前结论

- 开发集成优先使用 `Qwen3-8B`：用于打通 OpenAI-compatible API、local_vllm 配置、prefix cache 观测和 StateBus KV 估算链路。
- 真实质量验证优先试 `Qwen3-32B` 单卡 bf16：A100 80G 可试，但要 `max_num_seqs=1`，并控制 `max_model_len`。
- 暂不优先使用 `/data/models/Qwen3.5-27B`：它是 `Qwen3_5ForConditionalGeneration` / hybrid config，不是当前 cu121 + vLLM 0.7.3 的稳妥目标。
- 当前服务器 driver 能跑 cu121 组合；直接安装新 vLLM 会拉 CUDA 13 runtime，出现 `CUDA driver version is insufficient for CUDA runtime version`。
- `vllm==0.7.3` 能配 `torch==2.5.1+cu121`，但对 Qwen3 会走 Transformers fallback；能跑 API，不应把性能或 prefix-cache 效果当最终结论。

## 2. 干净环境

```bash
pkill -f 'vllm serve|uv pip install.*vllm' || true
conda deactivate || true
rm -rf /home/qcrs/statebus/conda-envs/vllm-qwen
rm -rf /home/qcrs/statebus/conda-envs/vllm-qwen-cu121

source "$(conda info --base)/etc/profile.d/conda.sh"
CONDA_PKGS_DIRS=/home/qcrs/statebus/caches/conda-pkgs \
conda create -y -p /home/qcrs/statebus/conda-envs/vllm-qwen-cu121 python=3.11

conda activate /home/qcrs/statebus/conda-envs/vllm-qwen-cu121
python -m pip install -U pip uv

export UV_CACHE_DIR=/home/qcrs/statebus/caches/uv
uv pip install --system "vllm==0.7.3" --torch-backend=cu121
uv pip install --system \
  "transformers==4.51.3" \
  "tokenizers==0.21.1" \
  "huggingface-hub<1.0"
```

检查：

```bash
python - <<'PY'
import torch, vllm, transformers, tokenizers
print("torch", torch.__version__, torch.version.cuda)
print("vllm", vllm.__version__)
print("transformers", transformers.__version__)
print("tokenizers", tokenizers.__version__)
print("cuda available", torch.cuda.is_available())
PY
```

## 3. 8B 开发服务

8B 推荐低显存预留，避免占满 A100：

```bash
CUDA_VISIBLE_DEVICES=1 VLLM_USE_V1=0 vllm serve /data/models/Qwen3-8B \
  --served-model-name qwen3-8b \
  --host 127.0.0.1 \
  --port 53333 \
  --dtype bfloat16 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.35 \
  --max-num-seqs 4 \
  --max-num-batched-tokens 8192 \
  --enable-prefix-caching \
  --enforce-eager
```

当前实测日志口径：

- 权重约 `15.26 GiB`
- `gpu_memory_utilization=0.35` 时总池子约 `27.74 GiB`
- KV cache 预留约 `11.44 GiB`
- 8192 token 请求最大并发估算约 `10x`

## 4. 32B 单卡验证

先用 4096 判断是否稳定：

```bash
CUDA_VISIBLE_DEVICES=2 VLLM_USE_V1=0 vllm serve /data/models/Qwen3-32B \
  --served-model-name qwen3-32b \
  --host 127.0.0.1 \
  --port 53334 \
  --dtype bfloat16 \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.92 \
  --max-num-seqs 1 \
  --max-num-batched-tokens 4096 \
  --enable-prefix-caching \
  --enforce-eager
```

4096 能起再试 8192：

```bash
CUDA_VISIBLE_DEVICES=2 VLLM_USE_V1=0 vllm serve /data/models/Qwen3-32B \
  --served-model-name qwen3-32b \
  --host 127.0.0.1 \
  --port 53334 \
  --dtype bfloat16 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.95 \
  --max-num-seqs 1 \
  --max-num-batched-tokens 8192 \
  --enable-prefix-caching \
  --enforce-eager
```

也可以用脚本：

```bash
STATEBUS_VLLM_MODEL_PATH=/data/models/Qwen3-32B \
STATEBUS_VLLM_SERVED_MODEL_NAME=qwen3-32b \
STATEBUS_VLLM_PORT=53334 \
STATEBUS_VLLM_MAX_MODEL_LEN=8192 \
STATEBUS_VLLM_MAX_NUM_SEQS=1 \
STATEBUS_VLLM_GPU_MEMORY_UTILIZATION=0.95 \
scripts/start_vllm_qwen3_32b_prefix_cache.sh
```

## 5. StateBus 配置

复制本地 vLLM 配置模板：

```bash
cp deploy/statebus_llm.local_vllm.example deploy/statebus_llm.yaml.local
```

8B 开发时将模型和 endpoint 改成：

```yaml
mode: local_vllm

providers:
  default:
    kind: openai_compatible
    base_url: http://127.0.0.1:53333/v1
    api_key: EMPTY
    timeout_s: 120
    request_max_attempts: 1

roles:
  planner:
    provider: default
    model: qwen3-8b
    json_output: true
    temperature: 0.0
    max_tokens: 1024
```

四个角色都使用同一个 served model name。32B 验证时改为 `http://127.0.0.1:53334/v1` 和 `qwen3-32b`。

## 6. KV 预算估算

不启动 GPU 服务即可估算：

```bash
scripts/inspect_vllm_kv_budget.py /data/models/Qwen3-8B --prompt-tokens 8192
scripts/inspect_vllm_kv_budget.py /data/models/Qwen3-32B --prompt-tokens 8192
```

当前 config 估算：

- Qwen3-8B：KV 约 `144 KiB/token`，8192 token 约 `1.125 GiB/seq`
- Qwen3-32B：KV 约 `256 KiB/token`，8192 token 约 `2.0 GiB/seq`

这解释了为什么 32B 单卡主要瓶颈是权重约 `61 GiB`，而不是单请求 8192 KV。

## 7. 与 StateBus KV 创新点的边界

vLLM 的 prefix caching 是推理引擎内部能力：同一个 engine 中，请求前缀相同才可能复用 prefill KV。StateBus 不导出、传递或修改模型内部 KV tensor。

StateBus 当前做的是上层策略：

- 通过 `corpus_prefix_hash` 稳定识别共享 corpus prefix。
- 通过角色 prompt slice / shared-prefix contract 让 Planner、Retriever、Executor、Summarizer 更容易形成相同前缀。
- 通过 `EvidencePruningHint` 控制哪些证据进入 LLM prompt，估算减少的 prefill/KV token。
- 通过 vLLM metrics probe 读取实际 prefix cache hit 数据，但只有本地 engine 支持并启用 prefix caching 时才可作为机制证据。

shared-prefix prompt contract 默认关闭，避免影响现有 benchmark。需要单独机制验证时可设置：

```bash
export STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix
```

该模式只改变 StateBus 生成 prompt 的前缀布局，不导出或修改 vLLM 的 KV tensor。

不能宣称：

- 已实现跨 Agent KV tensor 直接传递。
- 已实现跨模型 KV 共享。
- API 模式下能控制或测量服务端 KV cache。
- 当前 cu121 + vLLM 0.7.3 的 Qwen3 fallback 性能代表正式 vLLM 原生实现性能。

## 8. 外部参考

- vLLM Automatic Prefix Caching: <https://docs.vllm.ai/en/stable/features/automatic_prefix_caching/>
- vLLM prefix caching design: <https://docs.vllm.ai/en/stable/design/prefix_caching/>
- vLLM Quantized KV Cache: <https://docs.vllm.ai/en/stable/features/quantization/quantized_kvcache/>
- Scissorhands KV cache compression: <https://arxiv.org/abs/2305.17118>
- ChunkKV semantic-preserving KV compression: <https://arxiv.org/abs/2502.00299>
