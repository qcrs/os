# Evidence 索引

`tests/evidence/` 只保留可直接阅读或机器处理的精选聚合；逐 slot 运行树、服务日志和失败目录仍在 `runs/` 的 raw run 中。

| evidence | 分母 | 入口 | 主要字段 |
| --- | ---: | --- | --- |
| [`mainline/`](../../tests/evidence/mainline/) | 48 个任务、24 对 | `run_statebus.sh mainline-24` | quality、provider request/token、message、state、memory |
| [`mechanisms/`](../../tests/evidence/mechanisms/) | 24 个计划位置 | `run_statebus.sh mainline-mechanisms` | 24/24 质量门通过；Memory off/on、State off/on、机制生命周期 |
| [`model-assist/`](../../tests/evidence/model-assist/) | APC 8、KV 8、Logit 12 | `run_statebus.sh apc|kv|logit|utility` | prefix hit、computed prefill、TTFT、logical input、正确 abstention |

统一汇总：

```bash
python tests/evidence/summarize_results.py
python tests/evidence/summarize_results.py --json
```

每条记录应能从 `tasks.jsonl`/`tasks.csv` 追溯到 `results.json` 或 `metrics.json`，再通过报告中的 raw run ID 追溯到完整运行材料。不要把 `provider tokens` 当成通信 token，也不要把 State 生命周期事件当成业务收益。
