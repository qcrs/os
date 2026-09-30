# 实验结果

StateBus 的实验分为主实验、机制实验和模型侧专项。三组实验使用不同任务集合和对照，结果按各自分母汇总。

| 实验 | 分母 | 对照 | 关键结果 |
| --- | ---: | --- | --- |
| 主实验 | 24 对、48 次执行 | `SB-FULL` / `P-TEXT` | 质量 24/24；requests **降低 31.67%**；provider tokens **降低 39.05%**；Executor generations **降低 52.78%**；repairs **降低 58.33%**；E2E **降低 24.47%** |
| Memory | 16 个位置 | `off` / `on` | 质量 8/8；requests **降低 33.33%**；provider tokens **降低 44.12%**；任务耗时 **降低 27.12%**；4/8 进入 validated replay |
| State | 8 个位置 | `off` / `on` | 质量 4/4；任务耗时 **降低 3.43%**；publish/transfer/consume `10/10/10`；S1 的 behavioral effect 为 `changed` |
| APC | 8 个位置 | `independent` / `shared` | consumer TTFT **降低 89.59%**；hit tokens `48 → 5,168`；task wall **降低 4.29%** |
| 显式 KV | 8 个位置 | `full_replay` / `continuation` | computed prefill **降低 90.37%**；TTFT **降低 60.88%**；request wall **降低 11.88%**；task wall **降低 3.58%** |
| Logit | 12 个位置 | `full` / `compact` / `selective` | logical input **降低 75.21%**；request wall **降低 17.18% / 18.51%**；9 个 resolved case 通过，3 个正确 `abstention` |

详细任务、字段、逐任务对照和计算结果见 [`results.md`](results.md)。精选机器结果见 [`tests/evidence/README.md`](../../tests/evidence/README.md)。

## 阅读顺序

1. 先看主实验，了解同一批 `finance` 和 `service_ops` 任务在两种产品配置下的整体结果。
2. 再看 Memory 和 State，分别查看 Memory 复用漏斗和 State 生命周期事件。
3. 最后看 APC、显式 KV 和 Logit，查看长文本模型服务中的局部计算复用和候选选择。

## 运行入口

```bash
python tests/evidence/summarize_results.py
python tests/evidence/summarize_results.py --json
```

| 实验 | runner | evidence |
| --- | --- | --- |
| 主实验 | `tests/benchmarks/run_statebus.sh mainline-24` | [`mainline/`](../../tests/evidence/mainline/) |
| Memory / State | `tests/benchmarks/run_statebus.sh mainline-mechanisms` | [`mechanisms/`](../../tests/evidence/mechanisms/) |
| APC / KV / Logit | `tests/benchmarks/run_statebus.sh utility --execute --yes` | [`model-assist/`](../../tests/evidence/model-assist/) |
