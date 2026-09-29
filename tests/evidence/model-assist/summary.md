# APC / KV / Logit 结果摘要

正式 run：`longtext-demo-v3-20260929_104844-2545919`  
suite revision：`longtext-demo-v3`  
计分位置：APC 8、KV 8、Logit 12，共 28 个；另有独立 warmup 和 calibration 记录。

## 观测到的机制指标

以下数字来自该 run 的 scored records 和 `mechanism-metrics.md`，不是对 48 项主链的推断。

### APC

- 同一 case 的 `apc_on_independent` 与 `apc_on_shared` 配对比较。
- Consumer TTFT 平均从 `2540.2 ms` 降到 `264.3 ms`，下降 `89.59%`。
- 观测命中 token 平均从 `48` 增加到 `5168`。
- 完整 task wall 平均下降 `4.29%`，但不保证每个 case 单调下降。

### 显式 KV

- `full_replay` 与 `continuation` 配对比较。
- Consumer computed prefill 平均从 `5666.5` 降到 `545.5` tokens，下降 `90.37%`。
- Consumer TTFT 平均从 `2570.6 ms` 降到 `1005.7 ms`，下降 `60.88%`。
- Consumer request wall 平均下降 `11.88%`，完整 task wall 平均下降 `3.58%`。
- continuation 的 store/load 平均约为 `2986.4 ms` / `749.0 ms`，这部分固定开销抵消了端到端收益。

### Logit

- 在 3 个 resolved case 上，compact/selective 的 logical input 比 full context 平均减少 `75.21%`。
- Provider request wall 平均下降：compact `17.18%`，selective `18.51%`。
- unresolved case 通过第二次展开后正确 `abstain`；selective 不是所有 case 都保证更快。

## 执行边界

本 run 的服务切换总耗时约 `145.5 s`，该开销不归因于单个 APC、KV 或 Logit slot。服务日志和逐 slot 运行过程不纳入本精选结果目录。

## 质量边界

`summary.json` 的最终聚合字段为 `demo_completed=true`、`standard_restored=true`、`business_quality_passed=true`。这表示 28 个独立 utility 位置均完成且通过业务质量或正确 abstention gate；它仍不构成 48 项主链的新结果。

机器可读聚合结果见 `metrics.json`，逐项报告见 `report.md`。原始完整目录保存在 `docs/reports/contest-model-assist-utility/longtext-demo-v3-20260929_104844-2545919/`。
