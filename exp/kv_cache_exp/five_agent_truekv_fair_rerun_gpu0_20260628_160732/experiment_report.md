# 同五 Agent 主图 A/B/C 公平对比实验

## 公平性约束

- 三组都执行同一逻辑拓扑：`planner → researcher_1/researcher_2/researcher_3 → analyst → executor → summarizer`。
- 三组 LLM Agent 调用次数相同：`6` 次，executor 是确定性 CodeAct，不调用 LLM。
- 三组使用同一任务源、同一模型、同一 max tokens、同一 temperature。
- 唯一变化：Agent 间状态传递方式不同。A 传全文文本，B 传结构化摘要/JSON，C 通过 `SharedStorageConnector` 复用长源文档 KV tensors，并传少量 suffix/state。

## 总体指标

| 组别 | 模式 | LLM调用数 | wall_time_sec | logical_prompt_tokens | effective_prompt_tokens | output_tokens | effective_total_tokens | 文本通信tokens | kv_reused_tokens | 最终产物评分 | 编译 | q退出 | WASD试玩 | 产物目录 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| A | `text` | 6 | 434.3341 | 29891 | 29891 | 7454 | 37345 | 29891 | 0 | 0.0 | False | False | False | `exp/kv_cache_exp/five_agent_truekv_fair_rerun_gpu0_20260628_160732/artifacts/text/skyforge_courier_release` |
| B | `structured` | 6 | 376.0349 | 10615 | 10615 | 8192 | 18807 | 10615 | 0 | 0.0 | False | False | False | `exp/kv_cache_exp/five_agent_truekv_fair_rerun_gpu0_20260628_160732/artifacts/structured/skyforge_courier_release` |
| C | `true_kv_transfer` | 6 | 271.0158 | 29213 | 9137 | 7286 | 16423 | 9143 | 20076 | 82.0 | True | True | True | `exp/kv_cache_exp/five_agent_truekv_fair_rerun_gpu0_20260628_160732/artifacts/true_kv_transfer/skyforge_courier_release` |

## trueKV 相对收益

- C vs A effective_prompt_tokens 降低：`69.43%`
- C vs A effective_total_tokens 降低：`56.02%`
- C vs A 文本通信 tokens 降低：`69.41%`
- C vs B effective_prompt_tokens 降低：`13.92%`
- C vs B effective_total_tokens 降低：`12.68%`
- C vs B 文本通信 tokens 降低：`13.87%`

## trueKV 证据

- connector：`SharedStorageConnector`
- source prefix tokens：`3346`
- producer wall time：`1.0076`
- KV 文件数：`36`
- KV tensor bytes：`493096032`

## 产物索引

| 文件 | 说明 |
| --- | --- |
| `exp/kv_cache_exp/five_agent_truekv_fair_rerun_gpu0_20260628_160732/summary.json` | 汇总指标 |
| `exp/kv_cache_exp/five_agent_truekv_fair_rerun_gpu0_20260628_160732/text.json` | A/text 原始输出 |
| `exp/kv_cache_exp/five_agent_truekv_fair_rerun_gpu0_20260628_160732/structured.json` | B/structured 原始输出 |
| `exp/kv_cache_exp/five_agent_truekv_fair_rerun_gpu0_20260628_160732/true_kv_transfer.json` | C/trueKV 原始输出 |
