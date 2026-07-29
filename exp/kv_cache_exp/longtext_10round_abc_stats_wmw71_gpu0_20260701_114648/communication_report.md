# LongText 十轮 A/B/C 通信统计验证

## 实验设置

- 任务源：`task/longtext/skyforge_cache_tasks.json`，共 `10` 轮。
- 逻辑拓扑：`planner → researcher_1/2/3 → analyst → executor → summarizer`。
- 每轮 LLM Agent 调用：`6` 次；executor 是确定性验证步骤，不调用 LLM。
- A/text：传全文长文档和文本状态；B/structured：传压缩 source/state packet 和 typed message；C/trueKV：长源文档通过 `SharedStorageConnector` 预填充 KV，Agent prompt 只把 suffix/state 计为文本通信。
- Agent 间消息数按业务 Agent 边统计，不包含 `summarizer → output`。

## 总体对比

| 组别 | 模式 | 轮数 | LLM调用 | Agent间消息 | 文本通信tokens | 文本通信chars | 非文本状态次数 | 非文本状态bytes | 十轮任务耗时合计(s) | 单任务平均耗时(s) | 模式总耗时含加载(s) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | `text` | 10 | 60 | 80 | 334183 | 844000 | 0 | 0 | 786.7755 | 78.6775 | 815.2352 |
| B | `structured` | 10 | 60 | 80 | 181106 | 609357 | 80 | 12888 | 702.6938 | 70.2694 | 713.1718 |
| C | `true_kv_transfer` | 10 | 60 | 80 | 165104 | 430815 | 61 | 31770488340 | 852.1684 | 85.2168 | 881.598 |

## 单任务逐轮耗时 / 文本tokens / 非文本事件

| round | task_id | A/text | B/structured | C/trueKV |
| ---: | ---: | --- | --- | --- |
| 1 | 9001 | 72.1204s / 24254tok / 0evt | 64.9424s / 7318tok / 8evt | 72.8085s / 4335tok / 6evt |
| 2 | 9002 | 74.0755s / 29201tok / 0evt | 65.8588s / 9340tok / 8evt | 77.9454s / 6870tok / 6evt |
| 3 | 9003 | 77.3569s / 34336tok / 0evt | 66.5094s / 11440tok / 8evt | 79.1526s / 9637tok / 6evt |
| 4 | 9004 | 79.1757s / 37264tok / 0evt | 67.188s / 13696tok / 8evt | 81.8039s / 13005tok / 6evt |
| 5 | 9005 | 78.2096s / 37039tok / 0evt | 67.3111s / 15922tok / 8evt | 84.3143s / 16414tok / 6evt |
| 6 | 9006 | 77.869s / 37078tok / 0evt | 68.4355s / 18664tok / 8evt | 85.5728s / 19557tok / 6evt |
| 7 | 9007 | 76.773s / 32896tok / 0evt | 68.8772s / 21460tok / 8evt | 87.7415s / 22550tok / 6evt |
| 8 | 9008 | 77.3269s / 32764tok / 0evt | 69.4004s / 23854tok / 8evt | 87.4728s / 24123tok / 6evt |
| 9 | 9009 | 76.3172s / 32788tok / 0evt | 70.2256s / 26284tok / 8evt | 87.1751s / 23881tok / 6evt |
| 10 | 9010 | 97.5513s / 36563tok / 0evt | 93.9454s / 33128tok / 8evt | 108.1815s / 24732tok / 6evt |

## Agent 间消息次数分布

| edge | A/text | B/structured | C/trueKV |
| --- | ---: | ---: | ---: |
| `analyst->executor` | 10 | 10 | 10 |
| `executor->summarizer` | 10 | 10 | 10 |
| `planner->researcher_1` | 10 | 10 | 10 |
| `planner->researcher_2` | 10 | 10 | 10 |
| `planner->researcher_3` | 10 | 10 | 10 |
| `researcher_1->analyst` | 10 | 10 | 10 |
| `researcher_2->analyst` | 10 | 10 | 10 |
| `researcher_3->analyst` | 10 | 10 | 10 |

## trueKV 与结构化收益

- C vs A 文本通信 tokens 降低：`50.59%`
- C vs A 文本通信 chars 降低：`48.96%`
- C vs A effective total tokens 降低：`48.56%`
- C vs B 文本通信 tokens 降低：`8.84%`
- B vs A 文本通信 tokens 降低：`45.81%`

## 非文本状态说明

- A/text：无非文本状态传递，统计为 `0`。
- B/structured：非文本状态事件是 typed `AgentMessage`/state packet 的结构化对象，bytes 为 JSON 序列化后的协议对象大小。
- C/trueKV：非文本状态事件包含 1 次 KV tensor store prefill，以及每个 LLM Agent 调用的 KV handle lookup；KV tensor bytes 按 shared storage 实际文件大小统计。
- C/trueKV source prefix tokens：`3346`；producer wall time：`0.4348`；KV 文件数：`1908`；KV tensor bytes：`31770447840`。

## 产物索引

| 文件 | 说明 |
| --- | --- |
| `exp/kv_cache_exp/longtext_10round_abc_stats_wmw71_gpu0_20260701_114648/summary.json` | 总体汇总指标 |
| `exp/kv_cache_exp/longtext_10round_abc_stats_wmw71_gpu0_20260701_114648/text.json` | A/text 指标 |
| `exp/kv_cache_exp/longtext_10round_abc_stats_wmw71_gpu0_20260701_114648/structured.json` | B/structured 指标 |
| `exp/kv_cache_exp/longtext_10round_abc_stats_wmw71_gpu0_20260701_114648/true_kv_transfer.json` | C/trueKV 指标 |
| `exp/kv_cache_exp/longtext_10round_abc_stats_wmw71_gpu0_20260701_114648/metrics` | calls/messages/non_text_events/rounds 明细 |
| `exp/kv_cache_exp/longtext_10round_abc_stats_wmw71_gpu0_20260701_114648/round_outputs` | 每轮各 Agent 原始输出 |
