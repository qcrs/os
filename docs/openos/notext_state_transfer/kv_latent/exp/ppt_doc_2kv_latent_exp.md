# KV Latent B/D 十轮实验 PPT 统计材料

生成时间：2026-07-07

本文汇总两个可用于 PPT 展示的 B/D 对比实验：

1. 交易系统连续事故响应十轮实验：来自 `exp/latent_kv_exp/incident_response_abd_20260705_164545-3.4%` 原始结果，并用 `exp/latent_kv_exp/incident_response_bd_20260707_1751` 补充通信指标。
2. 四城市巡检路线十轮实验：本次在 `SynapseX-wmw71` 容器、物理 GPU2 上完成的 B/D 对比实验。

## 总览对比

| 实验 | 任务类型 | B 平均耗时(s) | D 平均耗时(s) | D vs B | B 质量 | D 质量 | 主要结论 |
|---|---|---:|---:|---:|---|---|---|
| 交易系统连续事故响应 | 长中间状态、短 JSON 决策 | 303.588 | 275.548 | +9.24% 加速 | 字段命中 2/60；全字段 0/10 | 字段命中 40/60；全字段 0/10 | D 同时快于 B 且字段命中更高，但严格全字段正确仍未达标 |
| 四城市巡检路线 | 小规模组合推理、路线/成本 JSON | 115.153 | 109.779 | +4.67% 加速 | 路线 0/10；成本 0/10；完全 0/10 | 路线 7/10；成本 5/10；完全 3/10 | D 小幅快于 B，且 raw 输出可解析质量显著优于 B |

加速比计算：

```text
D_vs_B_speedup = (B_avg_time - D_avg_time) / B_avg_time * 100%
```

## 1. 交易系统连续事故响应十轮实验

### 实验设置

结果目录：

```text
exp/latent_kv_exp/incident_response_abd_20260705_164545-3.4%
```

任务文件：

```text
task/lantent/incident_response_10round/incident_response_tasks.json
```

任务说明：

- Suite：`trading_incident_response_latentmas_10round_v1`，名称为“交易系统连续事故响应长中间状态任务集”。
- 任务类型：`continuous_incident_response_long_intermediate_reasoning`，目标是模拟真实交易平台在一天内连续发生 10 个生产事故时，多 Agent 需要持续保留证据链、因果判断、处置策略和计算规则。
- 平台背景：SkyBridge 实时交易与清结算平台，覆盖下单准入、风控、撮合、清算、结算、行情、通知、审计、持仓和监管报送链路。
- 涉及服务：OrderGateway、RiskEngine、MatchingCore、ClearingService、SettlementService、MarketDataFeed、NotificationHub、AuditLogger、PositionManager、RegulatoryReporter。
- 每轮输入是一个结构化 `evidence_packet`，包含 `time_window`、用户可见症状、核心指标、关键日志、近期变更和候选根因。例如第 1 轮给出 09:30-09:42 的下单拒绝、401/403 比例、鉴权缓存版本、TTL 变更和候选根因；第 2 轮继承第 1 轮处置记录后继续判断 RiskEngine 规则误拦截。
- 十轮之间不是互相独立样本，而是通过 `inherits` 显式串联：第 1 轮继承 `shared_context`，第 2 轮继承 `round_01_context`，后续每轮继承上一轮上下文，第 10 轮是收盘终审事故，需要综合前序处置原则。
- Agent 工作流强制产生长中间状态：researcher 输出 1200-1600 字证据报告，逐条引用指标、日志、变更和约束；analyst 输出 1000-1400 字因果分析，比较至少 3 个候选根因并排序；executor 输出 600-900 字计算与处置矩阵，计算损失、事故级别和上报时限；summarizer 只输出最终短 JSON。
- 事故等级规则是确定性的：P0 覆盖大规模拒单、重复成交、长时间停机、大额结算阻塞或监管违约；P1 覆盖中等规模拒单、风控误杀、行情偏移、延迟或中等结算阻塞；其余生产影响归 P2。
- 损失计算公式固定：`estimated_loss_usd = rejected_orders * 50 + duplicated_fills * 200 + risk_false_positive_blocks * 35 + floor(settlement_blocked_usd * 0.002) + downtime_minutes * 10000`。
- 上报时限固定：P0 为 15 分钟，P1 为 60 分钟，P2 为 240 分钟。
- 动作空间是封闭集合，包括回滚 OrderGateway 配置、禁用风控规则并 reload、暂停撮合回放并去重、Kafka failover/rebalance、切换行情备源、幂等重启清算批、从 committed offset 恢复持仓消费者、启用通知 fallback 并 backfill、回滚监管 schema 并重报、failover 结算 worker 并冻结窗口。
- 最终 JSON 字段：`root_cause_service`、`root_cause_code`、`severity`、`primary_action`、`report_deadline_minutes`、`estimated_loss_usd`。
- 质量评测是 exact structured match：6 个字段全部精确匹配 `reference_answer` 才算该轮全字段正确；字段命中统计为 10 轮共 60 个字段里的正确数量。
- 这个任务适合 latent KV 的原因是 A/B 模式会反复把 researcher 长证据、analyst 长因果分析和 executor 长计算过程解码成自然语言，再让下游重新 prefill；D 模式理想设计是逐 Agent 追加 latent thoughts 和 KV cache，只在最后解码最终 JSON，从而减少显式文本搬运。
- 当前实验记录中 D 的限制：`researcher is text; latent starts at analyst`。因此该实验展示的是 analyst 之后 latent KV continuation 的部分收益，不是从 researcher 开始的完整理想 D 拓扑。

### 十轮任务

| 轮次 | task_id | 标题 |
|---:|---|---|
| 1 | `incident_round_01_ordergateway_auth_cache` | 开盘准入异常：OrderGateway 鉴权缓存回归 |
| 2 | `incident_round_02_risk_rule_false_positive` | 风控误拦截：RiskEngine 规则热加载异常 |
| 3 | `incident_round_03_matching_replay_duplicate_fill` | 撮合回放异常：MatchingCore 重复成交 |
| 4 | `incident_round_04_kafka_isr_settlement_lag` | 消息链路异常：Kafka ISR 丢失导致结算阻塞 |
| 5 | `incident_round_05_marketdata_provider_skew` | 行情偏移：MarketDataFeed 主供应商价格漂移 |
| 6 | `incident_round_06_clearing_batch_stuck` | 清算批处理卡滞：ClearingService 幂等重启决策 |
| 7 | `incident_round_07_position_consumer_stopped` | 持仓更新停滞：PositionManager 消费者恢复 |
| 8 | `incident_round_08_notification_fallback_failure` | 通知降级失败：NotificationHub 合规通知补发 |
| 9 | `incident_round_09_regulatory_schema_reject` | 监管报文拒收：RegulatoryReporter Schema 回滚 |
| 10 | `incident_round_10_settlement_deadlock_close` | 收盘结算阻塞：SettlementService 死锁与冻结窗口 |

### 实验数据

| 模式 | 轮数 | 平均耗时(s) | 总耗时(s) | Agent消息/轮* | 文本字符/轮* | LLM 调用/轮 | LLM 记账 Token in/轮 | LLM 记账 Token out/轮 | Latent steps/轮 | KV MB/轮 | 字段命中 | 全字段正确 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_text | 10 | 285.353 | 2853.534 | 未记录 | 未记录 | 6.0 | 10039.1 | 3060.8 | 0 | 0 | 1/60 | 0/10 |
| B_structured | 10 | 303.588 | 3035.877 | 7.0 | 30627.1 | 6.0 | 10543.5 | 3052.1 | 0 | 0 | 2/60 | 0/10 |
| D_latent_kv | 10 | 275.548 | 2755.475 | 4.0 | 25657.2 | 6.0 | 9842.5 | 2803.7 | 112 | 763.7 | 40/60 | 0/10 |

说明：本表中的 Token in/out 是 LLM 调用 usage 记账口径，不等同于 Agent 间显式文本通信 token。D 模式的 latent decode 会按继承 KV handle 的序列长度计入 input token，因此该指标包含 KV continuation 的工作量代理。

`*`：原始 `incident_response_abd_20260705_164545-3.4%` 结果未落盘 `message_count` 和 `text_comm_chars`，表中 B/D 的 `Agent消息/轮`、`文本字符/轮` 来自 `exp/latent_kv_exp/incident_response_bd_20260707_1751` 指标补跑。A_text 没有对应补跑值。通信列用于补充显式 Agent 通信口径，不与同表 2026-07-05 的耗时/质量列混作同一次严格运行。

D 相对 B：

```text
(303.588 - 275.548) / 303.588 = 9.24%
```

### 通信指标补充（2026-07-07 BD 指标补跑）

结果目录：

```text
exp/latent_kv_exp/incident_response_bd_20260707_1751
```

该补跑使用同一套交易系统连续事故响应 10 轮任务，并额外落盘 `message_count`、`text_comm_chars`、非文本传递和 context compression 字段。该 run 的平均耗时为 B=86.333s、D=99.904s，因此这里只用于补充通信口径，不替代上面的 2026-07-05 速度/质量结论。

| 指标 | B_structured | D_latent_kv | D 相对 B |
|---|---:|---:|---:|
| Agent消息/轮 | 7.0 | 4.0 | -42.9% |
| 文本字符/轮 | 30627.1 | 25657.2 | -16.2% |
| 文本通信 token 估算/轮 | 7657.2 | 6414.6 | -16.2% |
| 非文本传递/轮 | 3.0 | 6.0 | +100.0% |
| 非文本传递 MB/轮 | 0.01 | 672.30 | D 引入 KV |
| Context 原文/压缩字符/轮 | 13390.6 / 4516.6 | 6784.8 / 2288.2 | D 显式上下文更短 |

口径说明：`文本字符/轮` 对应脚本中的 `text_comm_chars`，由 `run_incident_response_abd.py::estimate_text_comm_chars()` 递归估算显式 state 文本/JSON 字段长度；`文本通信 token 估算/轮` 按 `ceil(chars / 4)` 记录。`Agent消息/轮` 对应 `message_count`。

### PPT 要点

- D 模式平均耗时比 B 快 9.24%，属于速度上可展示的正向案例。
- D 的字段命中 40/60，显著高于 B 的 2/60。
- 通信指标补跑显示，D 的 Agent 消息数从 B 的 7.0 次/轮降到 4.0 次/轮；显式文本字符从 30627.1 字符/轮降到 25657.2 字符/轮，减少 16.2%。
- 严格全字段正确仍为 0/10，说明 D 的最终 JSON 质量还没有达到上线式评测标准。
- 适合表达为“latent KV 路径同时改善速度和部分字段命中，但最终答案约束仍需加强”。

## 2. 四城市巡检路线十轮实验

### 实验设置

结果目录：

```text
exp/latent_kv_exp/4city_bd_latest_stats_gpu2_20260707_122042
```

任务文件：

```text
task/lantent/4city.json
```

运行环境：

- 容器：`SynapseX-wmw71`
- 物理 GPU：GPU2
- 模型服务：`latent_kv_model_server`，port `8101`
- 模型：`/data/models/Qwen3-8B`
- 运行模式：只跑 B_structured 与 D_latent_kv。
- D 配置：`ANALYST_LATENT_STEPS=64`、`EXECUTOR_LATENT_STEPS=32`、`POST_EXEC_LATENT_STEPS=16`、`SUMMARIZER_LATENT_STEPS=0`，每轮共 112 latent steps。
- 公平性：B/D 都通过同一个 `latent_kv_model_server` 推理服务。
- 实验脚本：`exp/latent_kv_exp/run_4city_bd_latest_stats.py`
- 统计口径：对齐最新 `run_abd_10round_0707.py`，额外记录路线/成本正确性。

任务说明：

- Suite ID：`4city_reasoning_5round_v1`，名称为“四城市巡检路线简化推理任务集”；虽然 ID 保留了 5round 字样，实际任务列表包含 10 轮。
- 任务类型：`simple_combinatorial_reasoning`，用于在小规模组合优化场景下对比 text、structured 和 latent_kv 三种模式的通信开销、可解析性和答案正确性。
- 城市集合固定为 A、B、C、D，距离矩阵对称：A-B=10、A-C=15、A-D=20、B-C=35、B-D=25、C-D=30。
- 默认规则是从 A 出发，访问其余城市各一次并返回 A；A 固定为起点时，B/C/D 全排列只有 3!=6 条候选巡回路线。
- 基础任务要求必须用 Python 代码枚举全部候选路线、计算每条路线总成本、选择最优结果，不能只靠自然语言猜测。
- 每轮在同一距离矩阵上引入一个小约束变化，考察模型是否能继承规则并重新筛选候选路线：道路关闭、必须包含某条边、访问顺序约束、不返回 A、最长路线、禁止某条边、严格第二短路线、同时包含两条边、固定终点和减少访问城市等。
- 第 1 轮是基础最短巡回；第 2 轮继承第 1 轮上下文并关闭 B-D；第 8 轮也继承第 1 轮最优路线，用于排除最优等价类后求严格第二短路线。
- 正向路线和完全反向路线通常视为同一个环形方案，但带访问顺序约束的轮次会破坏这种等价性，例如第 4 轮要求实际行进方向上先访问 B 再访问 D。
- 第 5 轮和第 10 轮是不闭环路径任务，不要求返回 A；第 10 轮还只要求访问 B、C，不要求访问 D。
- 每轮输出 JSON：`route`、`total_cost`、`verification`。`route` 是城市序列，`total_cost` 是整数成本，`verification` 是简短验证说明。
- 评测只基于模型 raw 可解析输出，不把 reference fallback 计入成功；成功条件是路线和成本都正确，并且 Python 枚举/筛选逻辑能覆盖所有候选路线。
- 这个任务的优势是搜索空间小、答案可穷举验证，质量误差容易定位到“路线解析失败”“成本计算错误”或“约束筛选错误”，适合做通信协议和 latent KV 的快速对照。
- 这个任务不依赖长文领域知识，主要考察中间状态传递是否让模型稳定保留距离矩阵、候选集合、轮次约束和最终 JSON 约束。

评测说明：

- `raw_route` / `raw_total_cost` 是从模型输出中解析出的原始答案。
- `route` / `total_cost` 在模型不可解析时使用 reference fallback 补全，仅用于报告展示。
- 正确率只基于模型 raw 可解析输出，不把 reference fallback 计入成功。
- D 每轮结束后清理 server-side KV handles，避免跨轮残留影响显存和后续结果。

### 十轮任务

| 轮次 | task_id | 标题 | 参考路线 | 参考成本 |
|---:|---|---|---|---:|
| 1 | `route_round_01` | 基础最短巡回路线 | A -> B -> D -> C -> A | 80 |
| 2 | `route_round_02` | 道路关闭后的重新规划 | A -> B -> C -> D -> A | 90 |
| 3 | `route_round_03` | 包含指定道路的最短路线 | A -> C -> D -> B -> A | 80 |
| 4 | `route_round_04` | 带访问先后顺序的巡回路线 | A -> B -> D -> C -> A | 80 |
| 5 | `route_round_05` | 固定终点的最短哈密顿路径 | A -> B -> C -> D | 75 |
| 6 | `route_round_06` | 最大化路径成本 | A -> B -> C -> D -> A | 90 |
| 7 | `route_round_07` | 禁止特定道路 | A -> C -> D -> B -> A | 80 |
| 8 | `route_round_08` | 次优路线 | A -> B -> C -> D -> A | 90 |
| 9 | `route_round_09` | 强制两条道路 | A -> B -> D -> C -> A | 80 |
| 10 | `route_round_10` | 固定起点和终点的路径 | A -> C -> B | 50 |

### 实验数据汇总

| 模式 | 轮数 | 平均耗时(s) | Agent消息/轮 | LLM 调用/轮 | LLM 记账 Token in/轮 | LLM 记账 Token out/轮 | 文本字符/轮 | 非文本传递/轮 | Latent steps/轮 | KV 传输/轮(KB) | 路线正确 | 成本正确 | 完全正确 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B_structured | 10 | 115.153 | 7.0 | 6.0 | 5674.4 | 3072.0 | 9127.5 | 3.0 | 0 | 0 | 0/10 | 0/10 | 0/10 |
| D_latent_kv | 10 | 109.779 | 4.0 | 6.0 | 8340.3 | 2816.0 | 6035.8 | 3.0 | 112 | 1210622 | 7/10 | 5/10 | 3/10 |

说明：上表中的 LLM 记账 Token in/out 不是显式文本通信 token。D 的 input token 包含 latent decode 时继承 KV 序列长度的记账，因此会出现“显式文本通信减少，但 LLM 记账 token_in 增加”的现象。

D 相对 B：

```text
(115.153 - 109.779) / 115.153 = 4.67%
```

通信指标变化：

| 指标 | B_structured | D_latent_kv | D 相对 B |
|---|---:|---:|---:|
| 平均耗时 | 115.153s | 109.779s | -4.67% |
| Agent消息/轮 | 7.0 | 4.0 | -42.9% |
| 文本字符/轮 | 9127.5 | 6035.8 | -33.9% |
| LLM 记账 Token in/轮 | 5674.4 | 8340.3 | +47.0% |
| LLM 记账 Token out/轮 | 3072.0 | 2816.0 | -8.3% |
| Latent steps/轮 | 0 | 112 | D 独有 |
| KV 传输/轮 | 0 KB | 1210622 KB | D 独有 |

按显式文本通信口径拆分：

| 指标 | B_structured | D_latent_kv | D 相对 B |
|---|---:|---:|---:|
| 文本通信 in 字符/轮 | 5293.5 | 3008.4 | -43.2% |
| 文本通信 out 字符/轮 | 3834.0 | 3027.4 | -21.0% |
| 文本通信总字符/轮 | 9127.5 | 6035.8 | -33.9% |
| 文本通信 token in/轮估算 | 1323.8 | 752.1 | -43.2% |
| 文本通信 token out/轮估算 | 958.9 | 757.1 | -21.0% |
| 文本通信 token 总量/轮估算 | 2282.3 | 1509.2 | -33.9% |

估算口径：当前结果只落盘 `text_chars_param` 和 `text_chars_result`，没有保存每条消息原文 tokenization；这里按每轮 `ceil(chars / 4)` 估算文本通信 token。该表更接近 Agent 间显式文本传递开销。

### D 模式逐轮质量

| 轮次 | 标题 | raw 路线正确 | raw 成本正确 | 完全正确 | raw 成本 |
|---:|---|---|---|---|---:|
| 1 | 基础最短巡回路线 | yes | yes | yes | 80 |
| 2 | 道路关闭后的重新规划 | no | yes | no | 90 |
| 3 | 包含指定道路的最短路线 | yes | no | no | 100 |
| 4 | 带访问先后顺序的巡回路线 | no | yes | no | 80 |
| 5 | 固定终点的最短哈密顿路径 | yes | no | no | 60 |
| 6 | 最大化路径成本 | yes | no | no | 95 |
| 7 | 禁止特定道路 | yes | no | no | 85 |
| 8 | 次优路线 | no | no | no | 85 |
| 9 | 强制两条道路 | yes | yes | yes | 80 |
| 10 | 固定起点和终点的路径 | yes | yes | yes | 50 |

### PPT 要点

- D 模式平均耗时 109.779s，B 模式 115.153s，D 小幅快 4.67%。
- D 的 Agent 消息数从 B 的 7 次/轮降到 4 次/轮；按显式文本通信口径，文本字符和估算文本 token 总量均减少 33.9%。
- D 引入 112 latent steps/轮和约 1.21GB KV 传输/轮；速度收益不大，但输出质量明显优于 B。
- D 的 LLM 记账 token_in 增加 47.0%，原因是 latent decode 记录了继承 KV 序列长度；这不代表显式文本通信增加。
- B 模式 10 轮均返回 JSON 模板，raw 路线/成本不可解析；因此 B 的 raw 正确率为 0/10。
- D 模式 10 轮均可解析 raw 输出，完全正确 3/10，路线正确 7/10，成本正确 5/10。
- 适合表达为“在简单组合推理任务中，D 的输出可解析性和部分正确性优于 B；显式文本通信减少，但 LLM 记账 token_in 因 KV continuation 口径增加，速度收益只有 4.67%”。

## PPT 结论页建议

可用一句话总结：

```text
Latent KV D 模式在两个十轮实验中都比 B 更快，并减少显式 Agent 文本通信；
在交易事故响应中字段命中显著更高，在四城市路线任务中 raw 可解析质量显著更好，
但最终严格正确率仍不足，下一步需要强化最终 JSON 约束和数值校验。
```

建议展示重点：

- 速度：交易事故 D vs B 加速 9.24%，四城市 D vs B 加速 4.67%。
- 通信：交易事故补跑中 D 的 Agent 消息/轮从 7.0 降到 4.0，文本字符/轮从 30627.1 降到 25657.2；四城市 D 文本字符/轮和估算文本通信 token/轮均比 B 少 33.9%，Agent 消息/轮少 42.9%；但 LLM 记账 token_in 因 KV continuation 口径增加 47.0%。
- 质量：交易事故 D 字段命中 40/60 vs B 2/60；四城市 D 完全正确 3/10 vs B 0/10。
- 风险：两组实验都还不能声称最终质量完全达标；D 的优势主要体现在中间状态传递、部分字段/答案可解析性和速度。
