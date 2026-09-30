# 文档入口

这里记录 `/home/qcrs/statebus/os` 的源码结构、运行方式、实验结果和部署配置。结果数字只引用 `tests/evidence/`，执行过程和服务日志保留在 `runs/`。

## 从哪里开始

| 需要查看 | 文档 |
| --- | --- |
| 首页、安装、vLLM、Runtime、Studio、测试 | [`../README.md`](../README.md) |
| 组件关系、进程、对象和数据流 | [`architecture/README.md`](architecture/README.md) |
| Runtime 调用路径、角色、State、Memory 和扩展 | [`implementation/README.md`](implementation/README.md) |
| 实验总览和关键数字 | [`experiments/README.md`](experiments/README.md) |
| 逐组实验表和逐任务结果 | [`experiments/results.md`](experiments/results.md) |
| 赛题原文 | [`reference/题目.md`](reference/题目.md) |

## 运行入口

| 工作 | 命令或路径 |
| --- | --- |
| Host 环境 | `deploy/install_statebus_host.sh`、`deploy/activate_statebus_host.sh` |
| vLLM 服务 | `scripts/vllm/manage_qwen3_32b.sh`；配置在 `deploy/vllm.env.local` |
| Runtime 容器 | `scripts/start_statebus.sh`；profile 在 `deploy/vllm.env.gpu*-u050` |
| Studio API | `scripts/run_statebus_studio.sh`，默认 `127.0.0.1:50080` |
| Studio UI | `scripts/run_statebus_studio_ui.sh`，默认 `127.0.0.1:50173` |
| Demo | [`demo/README.md`](../demo/README.md)；`demo/run_demo.sh --local-vllm` |
| Docker Compose | `docker/compose.yaml`、`docker/.env` |
| 离线测试 | `tests/unit/`、`tests/integration/`、`tests/benchmarks/` |
| Live smoke / benchmark | [`tests/benchmarks/README.md`](../tests/benchmarks/README.md)；`tests/benchmarks/run_statebus.sh` |

## 目录职责

| 目录 | 内容 |
| --- | --- |
| [`architecture/`](architecture/README.md) | Runtime、角色 Worker、对象存储和模型服务的关系 |
| [`implementation/`](implementation/README.md) | 当前源码的接口、字段、调用顺序和运行记录 |
| [`experiments/`](experiments/README.md) | 实验分组、对照、分母、结果表和复现命令 |
| [`../tests/evidence/README.md`](../tests/evidence/README.md) | mainline、mechanisms、model-assist 的精选 JSON/Markdown |
| [`../runs/`](../runs/) | 单次运行的 stdout、telemetry、服务日志和 raw 结果 |
| [`reference/`](reference/) | 赛题和外部参考材料 |

`tests/evidence/summarize_results.py` 只读取精选 evidence 并输出汇总，不修改 `runs/`。

## 目录导航

```text
docs/
├── README.md
├── architecture/
├── experiments/
├── implementation/
├── reference/
├── improvement/
└── assets/
```

目录入口：

| 目录 | 入口 |
| --- | --- |
| `architecture/` | [`architecture/README.md`](architecture/README.md) |
| `experiments/` | [`experiments/README.md`](experiments/README.md) |
| `implementation/` | [`implementation/README.md`](implementation/README.md) |
| `reference/` | [`reference/`](reference/) |
| `improvement/` | [`improvement/25_contest_evidence_closure_20260720/`](improvement/25_contest_evidence_closure_20260720/) |
| `assets/` | [`assets/`](assets/) |
