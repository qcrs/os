# Task1 Context Packets A/B 对照实验

生成时间：`2026-06-26T06:49:12.505515+00:00`  
运行容器：`SynapseX-wang`  
模型服务：`vLLM OpenAI-compatible API`，`/data/models/Qwen3-8B`，`max_model_len=8192`  
当前架构：`planner → researcher(s) → analyst → executor → summarizer`  
机器评测链路：`analyst.candidate_answers → executor.final_answer / executor.extracted_answers`，`summary` 只做人类可读总结。  
任务文件：`task/group1_tasks.json`，答案文件：`task/group1_gold.json`

## 实验设置

- **Protocol A**：`mode=text`，纯文本传输。
- **Protocol B**：`mode=structured`，仅启用压缩文本 `context_packets`。
- **B 通道开关**：`ENABLE_CONTEXT_PACKETS=1`，`ENABLE_EMBEDDING_TRANSFER=0`，`ENABLE_HIDDEN_STATE_TRANSFER=0`。
- **记忆隔离**：`PERSISTENT_MEMORY_ENABLED=0`。
- **评测取值**：只读取 executor 的 `final_answer` / `extracted_answers`，不再从 summarizer 的 `summary` 抽取。
- **输出文件**：
  - `exp/comm_exp/task1_protocol_a_text.json`
  - `exp/comm_exp/task1_protocol_b_structured.json`
  - `exp/comm_exp/task1_protocol_a_text.log`
  - `exp/comm_exp/task1_protocol_b_structured.log`

## 总体对比

| 指标 | Protocol A 纯文本 | Protocol B 压缩文本 | 差异 |
| --- | ---: | ---: | ---: |
| LLM 调用 | 60 | 60 | +0 (+0.0%) |
| 输入 tokens | 95,226 | 79,597 | -15,629 (-16.4%) |
| 输出 tokens | 18,795 | 18,825 | +30 (+0.2%) |
| 总 tokens | 114,021 | 98,422 | -15,599 (-13.7%) |
| 总耗时 | 218.69s | 284.01s | +65.32s (+29.9%) |
| 平均每轮 | 21.87s | 28.40s | +6.53s |
| 答案字段准确率 | 2/10 | 2/10 | +0 |
| Context 压缩 | N/A | 104,414 → 41,574 chars，节省 62,840 (60.2%) | — |

## 分 Agent Token 明细

| Agent | A calls | A tokens | B calls | B tokens | B-A tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| analyst | 10 | 49,096 | 10 | 33,806 | -15,290 |
| planner | 10 | 23,439 | 10 | 23,357 | -82 |
| researcher | 30 | 13,097 | 30 | 12,798 | -299 |
| summarizer | 10 | 28,389 | 10 | 28,461 | +72 |

## Context Packet 指标

| 计数器 | Protocol B 值 |
| --- | ---: |
| context_packets_enabled | 30 |
| context_packets_checked | 30 |
| context_packets_reliable | 30 |
| context_packets_rehydrated | 0 |
| context_packets_failed | 0 |
| context_packet_fallback_documents | 0 |
| context_original_chars | 104,414 |
| context_compressed_chars | 41,574 |
| context_saved_chars | 62,840 |
| message_count | 70 |
| param_chars | 59,327 |
| result_chars | 31,152 |
| embedding_transfers | 0 |
| hidden_state_transfers | 0 |

## 正确性评估

- **评测口径**：只比较 `task/group1_gold.json` 中列出的 gold 字段；输出来自 executor 的 `extracted_answers`。
- **归一化规则**：浮点数按 gold 的小数位数四舍五入后比较；布尔值归一化为 `True/False`；未在 gold 中列出的输出字段不计分。
- **Protocol A 正确率**：`2/10` = `20.0%`。
- **Protocol B 正确率**：`2/10` = `20.0%`。
- **正确轮次**：A 和 B 都只在 Round 5、Round 6 命中 gold；其余轮次数值不匹配。

| Round | Task ID | Gold 字段 | Protocol A 输出 → 归一化 | Protocol B 输出 → 归一化 |
| --- | ---: | --- | --- | --- |
| 1 | 129 | std_dev_fare=49.67 | 29.46 → 29.46 ✗ | 29.46 → 29.46 ✗ |
| 2 | 174 | fare_skewness=4.79 | 1.44 → 1.44 ✗ | 4.00 → 4.00 ✗ |
| 3 | 517 | correlation_pclass_fare=-0.55 | -0.68 → -0.68 ✗ | 0.00 → 0.00 ✗ |
| 4 | 516 | skewness_fare=4.79 | 1.55 → 1.55 ✗ | 4.00 → 4.00 ✗ |
| 5 | 130 | is_normal=False | False → False ✓ | False → False ✓ |
| 6 | 304 | normality_test_result=False | False → False ✓ | False → False ✓ |
| 7 | 132 | outlier_count=20 | 0 → 0 ✗ | 2 → 2 ✗ |
| 8 | 175 | outliers_count=2 | 3 → 3 ✗ | 1 → 1 ✗ |
| 9 | 179 | correlation_coefficient=-0.123 | -0.680 → -0.680 ✗ | 0.123 → 0.123 ✗ |
| 10 | 520 | correlation_coefficient=0.02 | -0.23 → -0.23 ✗ | -0.43 → -0.43 ✗ |

## 逐轮结果

| Round | A 耗时 | B 耗时 | B-A | A 抽取 | B 抽取 |
| --- | ---: | ---: | ---: | --- | --- |
| 1 | 31.05s | 25.08s | -5.97s | std_dev_fare: 29.46 / gold 49.67 ✗ | std_dev_fare: 29.46 / gold 49.67 ✗ |
| 2 | 29.43s | 26.87s | -2.56s | fare_skewness: 1.44 / gold 4.79 ✗ | fare_skewness: 4.00 / gold 4.79 ✗ |
| 3 | 27.53s | 28.12s | +0.59s | correlation_pclass_fare: -0.68 / gold -0.55 ✗ | correlation_pclass_fare: 0.00 / gold -0.55 ✗ |
| 4 | 22.69s | 26.11s | +3.42s | skewness_fare: 1.55 / gold 4.79 ✗ | skewness_fare: 4.00 / gold 4.79 ✗ |
| 5 | 16.76s | 27.37s | +10.61s | is_normal: False / gold False ✓ | is_normal: False / gold False ✓ |
| 6 | 20.01s | 30.51s | +10.50s | normality_test_result: False / gold False ✓ | normality_test_result: False / gold False ✓ |
| 7 | 19.55s | 33.50s | +13.95s | outlier_count: 0 / gold 20 ✗ | outlier_count: 2 / gold 20 ✗ |
| 8 | 16.86s | 30.05s | +13.19s | outliers_count: 3 / gold 2 ✗ | outliers_count: 1 / gold 2 ✗ |
| 9 | 16.74s | 25.64s | +8.90s | correlation_coefficient: -0.680 / gold -0.123 ✗ | correlation_coefficient: 0.123 / gold -0.123 ✗ |
| 10 | 18.07s | 30.76s | +12.69s | correlation_coefficient: -0.23 / gold 0.02 ✗ | correlation_coefficient: -0.43 / gold 0.02 ✗ |

## 观察

- 当前架构：`planner → researcher(s) → analyst → executor → summarizer`；`context_packets` 压缩的是 researcher 输出给 analyst 的上下文材料。
- 压缩验证结果：`30/30` packets reliable，`0` packets rehydrated，`0` failed。
- 评测结果来自 executor：`final_answer` 固化为机器评测用 `@field[value]`，`summary` 不再承担格式化评分职责。
- Protocol B 只启用 `context_packets`，关闭 embedding / hidden-state 两个非文本通道。
- 本次 Protocol B 总 tokens 相比 A：-15,599 (-13.7%)；analyst 输入 token 变化主要反映 context packet 对 researcher→analyst 上下文的压缩。
- 数值准确率仍受 Qwen3-8B 对样本数据统计计算能力影响；格式抽取问题已从 summarizer 解耦。

## 原始 Metrics Report 摘要

### Protocol A

```text
======================================================================
Performance Metrics Report
======================================================================

--- Task Timings ---
  node_analyst: avg=6.7383s, min=4.8352s, max=8.2857s, count=10
  node_executor: avg=0.0041s, min=0.0039s, max=0.0043s, count=10
  node_planner: avg=2.8772s, min=2.1699s, max=4.3276s, count=10
  node_researcher: avg=6.4582s, min=4.1378s, max=12.2926s, count=30
  node_summarizer: avg=4.6369s, min=3.4082s, max=6.6864s, count=10
  round_1: avg=31.0542s, min=31.0542s, max=31.0542s, count=1
  round_10: avg=18.0709s, min=18.0709s, max=18.0709s, count=1
  round_2: avg=29.4276s, min=29.4276s, max=29.4276s, count=1
  round_3: avg=27.5343s, min=27.5343s, max=27.5343s, count=1
  round_4: avg=22.6913s, min=22.6913s, max=22.6913s, count=1
  round_5: avg=16.7637s, min=16.7637s, max=16.7637s, count=1
  round_6: avg=20.0068s, min=20.0068s, max=20.0068s, count=1
  round_7: avg=19.5523s, min=19.5523s, max=19.5523s, count=1
  round_8: avg=16.8564s, min=16.8564s, max=16.8564s, count=1
  round_9: avg=16.7350s, min=16.7350s, max=16.7350s, count=1

--- Counters ---
  memory_reuse_hits: 47

--- Store Operations ---
  put: 70 ops, avg=0.001128s
  search: 123 ops, avg=0.003369s
  search scores: avg=0.5797, min=0.1051, max=0.8488

--- Communication Overhead Estimate ---

--- LLM Token Usage ---
  Total calls: 60
  Input tokens: 95226
  Output tokens: 18795
  Total tokens: 114021
  analyst: 10 calls, in=45283, out=3813, total=49096
  planner: 10 calls, in=21893, out=1546, total=23439
  researcher: 30 calls, in=2285, out=10812, total=13097
  summarizer: 10 calls, in=25765, out=2624, total=28389

======================================================================
```

### Protocol B

```text
======================================================================
Performance Metrics Report
======================================================================

--- Task Timings ---
  node_analyst: avg=9.6352s, min=7.3168s, max=17.7813s, count=10
  node_executor: avg=0.0039s, min=0.0022s, max=0.0049s, count=10
  node_planner: avg=3.8443s, min=2.6073s, max=4.7300s, count=10
  node_researcher: avg=7.7096s, min=4.8497s, max=9.6244s, count=30
  node_summarizer: avg=6.1574s, min=4.7754s, max=8.4786s, count=10
  round_1: avg=25.0831s, min=25.0831s, max=25.0831s, count=1
  round_10: avg=30.7632s, min=30.7632s, max=30.7632s, count=1
  round_2: avg=26.8721s, min=26.8721s, max=26.8721s, count=1
  round_3: avg=28.1160s, min=28.1160s, max=28.1160s, count=1
  round_4: avg=26.1105s, min=26.1105s, max=26.1105s, count=1
  round_5: avg=27.3737s, min=27.3737s, max=27.3737s, count=1
  round_6: avg=30.5137s, min=30.5137s, max=30.5137s, count=1
  round_7: avg=33.4958s, min=33.4958s, max=33.4958s, count=1
  round_8: avg=30.0504s, min=30.0504s, max=30.0504s, count=1
  round_9: avg=25.6403s, min=25.6403s, max=25.6403s, count=1

--- Counters ---
  context_packets_checked: 30
  context_packets_enabled: 30
  context_packets_failed: 0
  context_packets_rehydrated: 0
  context_packets_reliable: 30
  memory_reuse_hits: 47

--- Store Operations ---
  put: 70 ops, avg=0.001075s
  get: 30 ops, avg=0.000014s
  search: 123 ops, avg=0.003596s
  search scores: avg=0.5708, min=0.1152, max=0.8315

--- Communication Overhead Estimate ---

--- Structured Communication Metrics ---
  Total messages: 70
  Param chars (total): 59327
  Result chars (total): 31152
  Total payload chars: 90479
  Embedding transfers: 0
  Hidden-state transfers: 0
  Action 'analyze': 10 message(s)
  Action 'execute': 10 message(s)
  Action 'plan': 10 message(s)
  Action 'research': 30 message(s)
  Action 'summarize': 10 message(s)

--- Context Compression ---
  Records: 40
  Original chars: 104414
  Compressed chars: 41574
  Saved chars: 62840 (60.2%)
  analyst_prompt: 10 records, saved=60.2%
  researcher: 30 records, saved=60.2%

--- LLM Token Usage ---
  Total calls: 60
  Input tokens: 79597
  Output tokens: 18825
  Total tokens: 98422
  analyst: 10 calls, in=29685, out=4121, total=33806
  planner: 10 calls, in=21769, out=1588, total=23357
  researcher: 30 calls, in=2249, out=10549, total=12798
  summarizer: 10 calls, in=25894, out=2567, total=28461

======================================================================
```
