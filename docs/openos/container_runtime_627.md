# SynapseX-wmw-627 容器运行环境

## 1. 容器定位

后续 SynapseX 项目实验、验证和演示默认在容器 `SynapseX-wmw-627` 内执行，不再依赖宿主机 Python 环境。

容器基础信息：

```text
container: SynapseX-wmw-627
image: hub.oepkgs.net/openeuler/openeuler:24.03-lts-sp3
workdir: /data/mingwei/SynapseX
```

挂载目录：

```text
/data/mingwei/SynapseX -> /data/mingwei/SynapseX
/data/models -> /data/models
```

GPU：

```text
--gpus all
NVIDIA A100 80GB PCIe x 3
```

## 2. 已安装基础工具

容器基于 openEuler 最小镜像创建，已补充安装：

```bash
dnf install -y python3-pip git findutils gcc gcc-c++ make
```

容器内 Git 已配置 safe directory：

```bash
git config --global --add safe.directory /data/mingwei/SynapseX
git config --global --add safe.directory /data/mingwei/SynapseX/third_party/langgraph
git config --global --add safe.directory /data/mingwei/SynapseX/third_party/vllm
```

## 3. Python 依赖

已安装项目基础依赖：

```bash
python3 -m pip install numpy dashscope langchain-core langchain-openai transformers==4.51.3 tokenizers==0.21.4 accelerate
```

已安装本地 LangGraph 子模块：

```bash
python3 -m pip install \
  -e /data/mingwei/SynapseX/third_party/langgraph/libs/checkpoint \
  -e /data/mingwei/SynapseX/third_party/langgraph/libs/prebuilt \
  -e /data/mingwei/SynapseX/third_party/langgraph/libs/sdk-py \
  -e /data/mingwei/SynapseX/third_party/langgraph/libs/langgraph
```

已安装 vLLM：

```bash
python3 -m pip install vllm==0.8.5.post1
```

当前关键版本：

```text
Python: 3.11.6
numpy: 2.2.6
langchain-core: 1.4.8
langchain-openai: 1.3.3
transformers: 4.51.3
compiler toolchain: gcc/g++/make installed for vLLM/Triton JIT
torch: 2.6.0+cu124
vLLM: 0.8.5.post1
CUDA visible to torch: True
CUDA device count: 3
```

## 4. 推荐运行方式

进入容器：

```bash
docker exec -it SynapseX-wmw-627 bash
cd /data/mingwei/SynapseX
```

或者直接执行命令：

```bash
docker exec -w /data/mingwei/SynapseX SynapseX-wmw-627 bash -lc '<command>'
```

推荐 `PYTHONPATH`：

```bash
export PYTHONPATH=/data/mingwei/SynapseX/src:/data/mingwei/SynapseX/third_party/langgraph/libs/langgraph:/data/mingwei/SynapseX/third_party/langgraph/libs/checkpoint
```

本地 Qwen3-8B Transformers 后端环境变量：

```bash
export CHAT_BACKEND=transformers
export CHAT_MODEL=Qwen3-8B
export LOCAL_MODEL_PATH=/data/models/Qwen3-8B
export LOCAL_MODEL_DEVICE=cuda:0
export LOCAL_MODEL_DTYPE=bfloat16
export CHAT_DISABLE_THINKING=1
```

## 5. 轻量验证命令

验证依赖、GPU、项目 graph 导入：

```bash
docker exec -w /data/mingwei/SynapseX SynapseX-wmw-627 bash -lc '
PYTHONPATH=/data/mingwei/SynapseX/src:/data/mingwei/SynapseX/third_party/langgraph/libs/langgraph:/data/mingwei/SynapseX/third_party/langgraph/libs/checkpoint python3 - <<"PY"
import torch, vllm
from graph import build_graph
print("torch", torch.__version__, "cuda", torch.cuda.is_available(), "devices", torch.cuda.device_count())
print("vllm", vllm.__version__)
graph, store = build_graph(mode="structured")
print("build_graph ok", type(graph).__name__, type(store).__name__)
PY
'
```

验证结果应包含：

```text
cuda True
vllm 0.8.5.post1
build_graph ok CompiledStateGraph InMemoryStore
```

## 6. vLLM Cache Handoff 实验

运行 Qwen3-8B/vLLM prefix-cache handoff：

```bash
docker exec -w /data/mingwei/SynapseX SynapseX-wmw-627 bash -lc '
export PYTHONPATH=/data/mingwei/SynapseX/src:/data/mingwei/SynapseX/third_party/langgraph/libs/langgraph:/data/mingwei/SynapseX/third_party/langgraph/libs/checkpoint
export CUDA_VISIBLE_DEVICES=1
export VLLM_GPU_MEMORY_UTILIZATION=0.85
export VLLM_MAX_MODEL_LEN=4096
export VLLM_MAX_NUM_SEQS=16
export VLLM_MAX_NUM_BATCHED_TOKENS=4096
python3 exp/kv_cache_exp/run_cache_handoff.py
'
```

已验证结果包含：

```text
vllm_prefix_cache_created: 1
vllm_prefix_cache_transfers: 5
vllm_prefix_cache_hits: 5
vllm_prefix_cache_prefill_tokens: 851
vllm_prefix_cache_reused_tokens: 8764
```

说明：vLLM public API 不导出稳定 raw KV tensor；当前工程通过 `state_type=vllm_prefix_cache` 的 cache handle 复用同一 vLLM runtime 内部 prefix KV cache。

## 7. 注意事项

- 项目后续实验默认在该容器内执行，宿主机只用于编辑文件和管理 Git。
- `third_party/langgraph` 和 `third_party/vllm` 均为 submodule，不要直接把第三方源码复制进主仓库。
- vLLM 0.8.5.post1 会约束 `torch==2.6.0`，当前容器已按 vLLM 依赖完成安装。
- 若容器重建，需要重新安装基础工具和 Python 依赖，或基于当前容器 commit 成新镜像。
