# 精选结果证据

本目录保存三组实验的聚合结果和逐位置索引。实验说明见 [`../../docs/experiments/README.md`](../../docs/experiments/README.md)，详细表见 [`../../docs/experiments/results.md`](../../docs/experiments/results.md)，完整 raw run 位于 `runs/`。

```text
mainline/       24 对、48 个 SB-FULL/P-TEXT 任务位置
mechanisms/     16 个 Memory + 8 个 State 计划位置
model-assist/   8 个 APC + 8 个 KV + 12 个 Logit 位置
```

```bash
python tests/evidence/summarize_results.py
python tests/evidence/summarize_results.py --json
```

各目录保存 `results.json`/`metrics.json`、Markdown 摘要和逐位置 `tasks.jsonl`/`tasks.csv`。`business_quality_passed=true` 的 utility 汇总覆盖 28 个位置；标准任务质量见 [`mainline/`](mainline/)。

## 目录导航

```text
tests/evidence/
├── README.md
├── mainline/
├── mechanisms/
└── model-assist/
```

目录入口：[`mainline/`](mainline/)、[`mechanisms/`](mechanisms/)、[`model-assist/`](model-assist/)。
