# 部署与服务边界

StateBus host Runtime 使用 `statebus_host` 环境；模型服务使用独立的 vLLM 环境；openEuler 应用容器属于共享的部署层。三者的 Python package、GPU ownership 和输出目录不能混用。

## 当前边界

| 组件 | 当前入口 | 说明 |
| --- | --- | --- |
| Host Runtime | `source deploy/activate_statebus_host.sh` | 导入当前 `src/statebus`，用于离线测试和 launcher |
| vLLM | `scripts/vllm/manage_qwen3_32b.sh` | host-side OpenAI-compatible API，默认模型 `qwen3-32b` |
| 应用容器 | 已存在的 `statebus-dev-qcrs` | 由 sibling `project` checkout 管理；本 checkout 不例行重建同名容器 |
| Studio | `scripts/run_statebus_studio.sh` | backend 和 frontend 使用当前 checkout 的源码 |

运行实时实验前先执行只读 preflight：

```bash
command -v conda docker nvidia-smi
nvidia-smi -L
nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free --format=csv
docker ps
```

不能连接 NVIDIA driver 时停止在 preflight；不要通过 kill 其他进程、重启共享容器或修改 GPU ownership 绕过问题。

## vLLM 配置

使用仓库模板创建本地忽略配置：

```bash
[[ -e deploy/vllm.env.local ]] || cp deploy/vllm.env.example deploy/vllm.env.local
scripts/vllm/manage_qwen3_32b.sh print-config
```

保守首轮 profile 为 Qwen3-32B、BF16、single GPU、`max-model-len=4096`、`max-num-seqs=1`、`gpu-memory-utilization=0.82` 和 eager。启动前必须重新选择空闲或获准的物理 GPU，并设置 `STATEBUS_VLLM_CUDA_VISIBLE_DEVICES`；不要把历史默认 GPU 当成当前事实。

服务管理命令：

```bash
scripts/vllm/manage_qwen3_32b.sh start
scripts/vllm/manage_qwen3_32b.sh health
scripts/vllm/manage_qwen3_32b.sh status
scripts/vllm/manage_qwen3_32b.sh logs
scripts/vllm/manage_qwen3_32b.sh stop
```

只有 `/health` 和 `/v1/models` 同时确认模型与 context 后，才可运行 live StateBus runner。vLLM 未通过检查时，runner 失败属于服务前提失败，不能归因于 Runtime。

## 应用容器

`os/AGENTS.md` 指定的 `statebus-dev-qcrs` 容器由 sibling `project` checkout 管理，并挂载 `/home/qcrs/statebus/project`，不自动可见本 `os` checkout。不要从本 checkout 例行执行 `docker compose up`、`--force-recreate` 或 build 来替换共享容器。

如需只检查 Compose 配置：

```bash
docker compose --env-file docker/.env.example -f docker/compose.yaml config
```

针对当前 `os` 源码的 host-side 测试：

```bash
source deploy/activate_statebus_host.sh
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q tests/unit tests/integration tests/benchmarks
```

Live smoke 使用 [`scripts/run_local_vllm_container_check.sh`](../scripts/run_local_vllm_container_check.sh)，正式实验使用 [`tests/benchmarks/run_statebus.sh`](../tests/benchmarks/run_statebus.sh)。

## Runtime 开关

普通主链保持模型侧 utility 关闭：

```dotenv
STATEBUS_PREFIX_ALIGNMENT_MODE=independent
STATEBUS_PREFIX_POLICY=off
STATEBUS_LOGIT_GATE_MODE=off
STATEBUS_ENGINE_LOCAL_KV_MODE=off
```

APC、显式 KV 和 Logit 必须按 utility runner 的 phase/profile 显式启用，并使用各自的 evidence 分母。它们不是 24 轮主链的隐式开关。
