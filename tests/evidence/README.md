# StateBus 结果证据

本目录只保留可直接阅读或机器处理的正式结果，不包含历史失败、服务日志、
Prometheus 快照、逐 slot Runtime 目录或其他运行过程文件。

```text
evidence/
├── mainline/       # 24 对、48 个任务的 StateBus / 纯文本主链结果
├── mechanisms/     # Memory 与 State 主链机制实验结果
├── model-assist/   # APC、显式 KV 与 Logit 的 28 个计分位置结果
└── summarize_results.py
```

运行统一汇总：

```bash
python tests/evidence/summarize_results.py
python tests/evidence/summarize_results.py --json
```

`model-assist/metrics.json` 中 `business_quality_passed=true`，表示 28 个独立
utility 位置均完成且通过业务质量或正确 abstention gate。它仍是独立 utility
链结果，不表示 48 个主链任务获得同样的收益。原始完整运行材料仍保存在
`docs/reports/`，不重复复制到本目录。
