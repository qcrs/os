# 精选结果证据

本目录保留可直接阅读或机器处理的精选 evidence；Memory / State 机制结果见 [`mechanisms/results.md`](mechanisms/results.md)，完整 raw run 位于 `runs/`。

```text
mainline/       24 对、48 个 SB-FULL/P-TEXT 任务位置
mechanisms/     16 个 Memory + 8 个 State 计划位置
model-assist/   8 个 APC + 8 个 KV + 12 个 Logit 位置
```

```bash
python tests/evidence/summarize_results.py
python tests/evidence/summarize_results.py --json
```

精选目录不包含逐 slot Runtime 深层目录、服务日志或失败运行树；这些材料按 run ID 保留在 `runs/`。当前 Memory / State 汇总见 [`mechanisms/`](mechanisms/)。`business_quality_passed=true` 只适用于 `model-assist` 的 28 个 utility 位置，不代表主链 48 个任务。
