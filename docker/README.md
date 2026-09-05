# StateBus 部署与启动

StateBus 应用运行在单个 openEuler 容器中，模型推理可以选择两条路径：

- 外部 OpenAI-compatible API；
- 宿主机上的 Qwen3-32B vLLM，地址为 `http://127.0.0.1:53334/v1`。

应用容器使用 host network，因此可以直接访问宿主机的 loopback 地址。容器
本身不申请 GPU，Embedding 默认使用 CPU；宿主机 vLLM 默认只使用物理卡 2。

## 1. 文件分工

| 文件 | 用途 |
|:--|:--|
| `requirements-vllm.txt` | 固定宿主机 vLLM 推理环境版本 |
| `deploy/vllm.env.example` | Qwen3-32B、GPU、端口和运行模式配置模板 |
| `deploy/statebus_llm.local_vllm.example` | StateBus 连接本地 vLLM 的角色配置 |
| `deploy/statebus_llm.yaml.example` | StateBus 连接外部 API 的配置模板 |
| `docker/.env.example` | Docker Compose 环境变量模板 |
| `docker/compose.yaml` | StateBus 应用容器定义 |
| `scripts/vllm/start_qwen3_32b.sh` | 前台启动普通 vLLM |
| `scripts/vllm/manage_qwen3_32b.sh` | 后台启停、状态、健康检查和日志入口 |

本仓库没有修改或内置 vLLM 源码。显式 KV 通过 vLLM 0.9.2 的 Connector、
Worker Extension 和 Middleware 扩展入口加载。

## 2. 固定的推理环境

当前实验验证过的宿主机组合如下：

| 组件 | 固定版本 |
|:--|:--|
| Python | 3.11 |
| vLLM | 0.9.2 |
| PyTorch | 2.7.0，运行时标识为 `2.7.0+cu126` |
| Transformers | 4.52.4 |
| Tokenizers | 0.21.4 |
| xFormers | 0.0.30 |
| NumPy | 2.2.6 |

完整的直接依赖版本在仓库根目录的 `requirements-vllm.txt`。如需创建新环境：

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda create -y \
  -p "$HOME/statebus/conda-envs/vllm-qwen-cu121" \
  python=3.11
conda activate "$HOME/statebus/conda-envs/vllm-qwen-cu121"
python -m pip install --upgrade pip
python -m pip install -r requirements-vllm.txt
python -m pip check
```

`vllm-qwen-cu121` 是现有环境沿用的目录名；当前实际运行的 Torch 版本为
`2.7.0+cu126`，以环境中的包信息为准。

安装后可执行只读版本检查：

```bash
"$HOME/statebus/conda-envs/vllm-qwen-cu121/bin/python" - <<'PY'
import torch
import transformers
import vllm

print("vLLM:", vllm.__version__)
print("PyTorch:", torch.__version__)
print("PyTorch CUDA:", torch.version.cuda)
print("Transformers:", transformers.__version__)
PY
```

这套 vLLM 环境运行在宿主机，不安装进 StateBus 应用容器。

## 3. Docker 配置

复制 Compose 配置并写入当前用户的 UID/GID：

```bash
cp docker/.env.example docker/.env
sed -i "s/^STATEBUS_UID=.*/STATEBUS_UID=$(id -u)/" docker/.env
sed -i "s/^STATEBUS_GID=.*/STATEBUS_GID=$(id -g)/" docker/.env
```

`docker/.env` 中最重要的配置如下：

| 配置 | 默认值 | 作用 |
|:--|:--|:--|
| `STATEBUS_DOCKER_TARGET` | `embed` | 使用包含 Runtime、Studio 和 Embedding 的镜像 target |
| `STATEBUS_EMBED_DEVICE` | `cpu` | 避免 Embedding 与 vLLM 争用 GPU |
| `STATEBUS_LLM_CONFIG_FILE` | 本地 vLLM 示例 | 选择外部 API 或本地 vLLM |
| `STATEBUS_PREFIX_ALIGNMENT_MODE` | `independent` | 默认不调整角色 prompt 前缀 |
| `STATEBUS_LOGIT_GATE_MODE` | `off` | 默认不启用 Logit Gate |
| `STATEBUS_ENGINE_LOCAL_KV_MODE` | `off` | 默认不启用显式 KV continuation |

首次运行前创建宿主机数据目录：

```bash
mkdir -p \
  "$HOME/statebus/models" \
  "$HOME/statebus/caches" \
  "$HOME/statebus/logs" \
  "$HOME/statebus/runs" \
  "$HOME/statebus/work/container-home/.local"
```

Compose 默认使用已有镜像
`statebus-dev-openeuler:24.03-lts-sp3-embed`。不重新构建，直接启动：

```bash
docker compose \
  --env-file docker/.env \
  -f docker/compose.yaml \
  up -d --no-build
```

进入应用容器：

```bash
docker compose \
  --env-file docker/.env \
  -f docker/compose.yaml \
  exec statebus-dev bash
```

容器内先加载运行环境：

```bash
source /usr/local/bin/activate_statebus_container.sh
```

## 4. 使用外部 API

复制 API 配置和密钥模板：

```bash
cp deploy/statebus_llm.yaml.example deploy/statebus_llm.yaml.local
cp deploy/statebus_llm.env.example deploy/statebus_llm.env.local
```

在 `deploy/statebus_llm.yaml.local` 中修改：

- API `base_url`；
- Planner、Retriever、Executor、Summarizer 使用的模型名；
- timeout、temperature 和 max_tokens。

在 `deploy/statebus_llm.env.local` 中填写 API Key。然后把 `docker/.env` 改为：

```dotenv
STATEBUS_LLM_CONFIG_FILE=/workspace/statebus/project/deploy/statebus_llm.yaml.local
```

外部 API 路径无需启动本地 vLLM。远端服务负责 Prefix cache；StateBus 使用标准 API
调用路径。Logit Gate 在服务返回 token log probabilities 时可用。显式 KV continuation
运行在仓库提供的本地 vLLM 扩展模式。

## 5. 使用本地 Qwen3-32B vLLM

复制宿主机 vLLM 配置：

```bash
cp deploy/vllm.env.example deploy/vllm.env.local
scripts/vllm/manage_qwen3_32b.sh print-config
```

默认配置为：

```text
模型目录    /data/models/Qwen3-32B
服务模型名  qwen3-32b
API 地址    http://127.0.0.1:53334/v1
物理 GPU    2
Python 环境 ~/statebus/conda-envs/vllm-qwen-cu121
```

普通模式的启停命令：

```bash
scripts/vllm/manage_qwen3_32b.sh start
scripts/vllm/manage_qwen3_32b.sh status
scripts/vllm/manage_qwen3_32b.sh health
scripts/vllm/manage_qwen3_32b.sh logs
scripts/vllm/manage_qwen3_32b.sh stop
```

`start_qwen3_32b.sh` 是前台启动入口。`manage_qwen3_32b.sh` 在它外层维护 PID、
日志和健康检查，而且不会接管不是由自己启动的同端口进程。

普通模式启用 Automatic Prefix Caching，并允许返回最多 20 个 logprobs。因此
同一个 vLLM 服务可以支持普通主链、Engine-Local Prefix Reuse 和 Logit Gate。

应用容器继续使用 `docker/.env.example` 中的默认配置即可：

```dotenv
STATEBUS_LLM_CONFIG_FILE=/workspace/statebus/project/deploy/statebus_llm.local_vllm.example
```

## 6. Runtime 开关

普通 StateBus 主链保持全部关闭：

```dotenv
STATEBUS_PREFIX_ALIGNMENT_MODE=independent
STATEBUS_PREFIX_POLICY=off
STATEBUS_LOGIT_GATE_MODE=off
STATEBUS_ENGINE_LOCAL_KV_MODE=off
```

启用 Prefix 布局和命中观测：

```dotenv
STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix
STATEBUS_PREFIX_POLICY=observe
```

Logit Gate 可以独立选择只观测或最多重查一次：

```dotenv
STATEBUS_LOGIT_GATE_MODE=telemetry
```

或：

```dotenv
STATEBUS_LOGIT_GATE_MODE=retry_once
```

修改 `docker/.env` 后，不构建镜像，只重建应用容器配置：

```bash
docker compose \
  --env-file docker/.env \
  -f docker/compose.yaml \
  up -d --no-build --force-recreate
```

## 7. 显式 KV continuation

显式 KV 与普通 vLLM 使用同一张 GPU 和同一个端口，通过服务模式切换。KV 模式关闭
Automatic Prefix Caching，使实验中的复用只来自：

```text
produce -> continue -> release
```

先创建私有 bearer token：

```bash
mkdir -p "$HOME/statebus/work/vllm-qwen3-32b"
umask 077
openssl rand -hex 32 \
  > "$HOME/statebus/work/vllm-qwen3-32b/kv_api.token"
chmod 600 "$HOME/statebus/work/vllm-qwen3-32b/kv_api.token"
```

在 `deploy/vllm.env.local` 中设置：

```bash
export STATEBUS_VLLM_SERVICE_MODE="kv"
export STATEBUS_KV_API_TOKEN_FILE="${HOME}/statebus/work/vllm-qwen3-32b/kv_api.token"
export STATEBUS_KV_ENGINE_GENERATION="qwen3-32b-kv-generation-001"
```

切换服务模式：

```bash
scripts/vllm/manage_qwen3_32b.sh stop
scripts/vllm/manage_qwen3_32b.sh start
```

在 `docker/.env` 中配置容器侧 client：

```dotenv
STATEBUS_ENGINE_LOCAL_KV_MODE=continuation
STATEBUS_KV_API_BASE_URL=http://127.0.0.1:53334
STATEBUS_KV_API_TOKEN_FILE=/statebus/work/vllm-qwen3-32b/kv_api.token
STATEBUS_ENGINE_LOCAL_KV_MODEL=qwen3-32b
STATEBUS_ENGINE_LOCAL_KV_PARENT_TOKENS=4096
```

匹配的无 KV 基线使用：

```dotenv
STATEBUS_ENGINE_LOCAL_KV_MODE=full_replay
```

做显式 KV A/B 时，Prefix 应保持 `independent`，避免两个机制同时影响结果。

## 8. 启动 Runtime 和 Studio

容器内执行 Runtime smoke：

```bash
source /usr/local/bin/activate_statebus_container.sh
python -m statebus.runtime.smoke --role-path-mode local_vllm
```

启动 Studio：

```bash
source /usr/local/bin/activate_statebus_container.sh
scripts/run_statebus_studio.sh
```

Studio 默认监听 `http://127.0.0.1:8765`，使用 CPU Embedding，并复用
`docker/.env` 选择的外部 API 或本地 vLLM 配置。
