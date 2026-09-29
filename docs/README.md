# 文档入口

文档只描述 `/home/qcrs/statebus/os` 当前 checkout 的代码、runner、测试和精选 evidence。

## 阅读路径

了解系统：[`architecture/`](architecture/README.md) → [`implementation/`](implementation/README.md) → [`implementation/roles/`](implementation/roles/README.md)

开发和调试：[`implementation/runtime/`](implementation/runtime/) → [`implementation/state/`](implementation/state/) → [`architecture/code-index.md`](architecture/code-index.md)

复现实验：[`experiments/`](experiments/README.md) → [`experiments/evidence-index.md`](experiments/evidence-index.md) → [`tests/benchmarks/README.md`](../tests/benchmarks/README.md)

## 目录职责

| 目录 | 用途 |
| --- | --- |
| [`architecture/`](architecture/) | 稳定系统结构、目录职责、源码索引和 canonical diagram |
| [`implementation/`](implementation/) | 从当前源码整理的调用路径、对象、配置和运行说明 |
| [`experiments/`](experiments/) | 实验分母、控制变量、runner、指标和精选 evidence |
| [`../runs/`](../runs/) | raw run、服务日志和历史运行材料 |
| [`reference/`](reference/) | 赛题、审计和历史参考；不能替代当前运行证据 |

## 结果入口

| 结果 | 精选 evidence | 主要实现 |
| --- | --- | --- |
| 24 轮 / 48 任务主链 | [`tests/evidence/mainline/`](../tests/evidence/mainline/) | `src/statebus/benchmark/contest_dsl_mainline.py` |
| 24 位置 Memory / State 机制 | [`tests/evidence/mechanisms/`](../tests/evidence/mechanisms/) | `contest_mechanisms.py`、`memory_ablation.py` |
| 28 位置 APC / KV / Logit utility | [`tests/evidence/model-assist/`](../tests/evidence/model-assist/) | `benchmark/model_assist_utility/`、`runtime/prefix_*`、`runtime/logit_*` |

`tests/evidence/summarize_results.py` 汇总精选目录；它不会生成或覆盖 raw run。
