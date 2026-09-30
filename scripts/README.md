# 脚本入口

`scripts/` 包含服务管理、Runtime 容器、Studio、实验 runner 和诊断工具。实验 dispatcher 位于 `tests/benchmarks/run_statebus.sh`，只选择 runner，不替调用方启动模型服务。

相关入口：[`../README.md`](../README.md) 的快速开始、[`../docker/README.md`](../docker/README.md) 的服务配置、[`../demo/README.md`](../demo/README.md) 的 Demo、[`../tests/README.md`](../tests/README.md) 的测试与 benchmark、[`../docs/experiments/README.md`](../docs/experiments/README.md) 的结果说明。

## 主要入口

| 命令 | 作用 |
| --- | --- |
| `tests/benchmarks/run_statebus.sh smoke` | 本地 vLLM / 容器 smoke 路由 |
| `scripts/run_contest_dsl_mainchains.sh` | `SB-FULL` 或 `P-TEXT` 的两个 12 轮 family |
| `scripts/run_contest_mechanisms.sh` | Memory / State 机制矩阵，正式计划 24 个位置 |
| `scripts/experiments/contest_model_assist/run_utility_suite.sh` | APC、显式 KV、Logit utility suite |
| `scripts/start_statebus.sh` | 选择 profile、准备 Runtime 容器并检查服务 |
| `scripts/vllm/manage_qwen3_32b.sh` | 已获准的 vLLM 服务 status/health/logs/启停 |
| `scripts/run_statebus_studio.sh` | Studio FastAPI，默认 `127.0.0.1:50080` |
| `scripts/run_statebus_studio_ui.sh` | Studio Vite，默认 `127.0.0.1:50173` |

服务配置：

| 文件 | 用途 |
| --- | --- |
| `deploy/vllm.env.local` | vLLM 模型、端口、GPU、context 和 service mode |
| `deploy/statebus_llm.yaml.local` | Runtime provider、角色模型和请求参数 |
| `deploy/statebus_llm.env.local` | API key、embedding 和临时环境变量 |

Studio 启动：

```bash
source deploy/activate_statebus_host.sh
scripts/run_statebus_studio.sh

# 另一个终端
cd src/studio-ui
npm ci
cd ../..
scripts/run_statebus_studio_ui.sh
```

入口检查：

```bash
tests/benchmarks/run_statebus.sh mainline-24 --dry-run
tests/benchmarks/run_statebus.sh mainline-mechanisms --dry-run
tests/benchmarks/run_statebus.sh utility --dry-run
```

## 目录导航

```text
scripts/
├── README.md
├── diagnostics/
├── evidence/
├── experiments/
│   ├── contest_model_assist/
│   └── engine_local_kv/
├── vllm/
└── vllm_exporter/
```

目录入口：[`diagnostics/`](diagnostics/)、[`evidence/`](evidence/)、[`experiments/`](experiments/)、[`experiments/contest_model_assist/`](experiments/contest_model_assist/)、[`experiments/engine_local_kv/`](experiments/engine_local_kv/)、[`vllm/`](vllm/)、[`vllm_exporter/`](vllm_exporter/)。

正式 runner 会拒绝复用非空 output 目录，并把失败记录留在该 run 中。GPU、容器和模型服务的启动顺序见 [`docker/README.md`](../docker/README.md)。
