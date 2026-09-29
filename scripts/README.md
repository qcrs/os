# 脚本入口

`scripts/` 包含服务检查、主链/机制/utility runner、诊断和报告工具。稳定的实验路由是 `tests/benchmarks/run_statebus.sh`；它只选择 runner，不隐式启动或停止模型服务。

## 主要入口

| 命令 | 作用 |
| --- | --- |
| `tests/benchmarks/run_statebus.sh smoke` | 本地 vLLM / 容器 smoke 路由 |
| `scripts/run_contest_dsl_mainchains.sh` | `SB-FULL` 或 `P-TEXT` 的两个 12 轮 family |
| `scripts/run_contest_mechanisms.sh` | Memory / State 机制矩阵，正式计划 24 个位置 |
| `scripts/experiments/contest_model_assist/run_utility_suite.sh` | APC、显式 KV、Logit utility suite |
| `scripts/start_statebus.sh` | 选择 profile、准备 Runtime 容器并检查服务 |
| `scripts/vllm/manage_qwen3_32b.sh` | 已获准的 vLLM 服务 status/health/logs/启停 |
| `scripts/run_statebus_studio.sh` | Studio backend/frontend launcher |

入口检查：

```bash
tests/benchmarks/run_statebus.sh mainline-24 --dry-run
tests/benchmarks/run_statebus.sh mainline-mechanisms --dry-run
tests/benchmarks/run_statebus.sh utility --dry-run
```

正式 runner 会拒绝复用非空 output 目录，并把失败记录留在该 run 中。GPU、容器和模型服务的 preflight 规则见 [`AGENTS.md`](../AGENTS.md)；不要用历史脚本推断当前架构。
