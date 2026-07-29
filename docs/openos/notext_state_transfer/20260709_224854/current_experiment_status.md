# structured vs kv_latent 当前实验状态

生成时间: 2026-07-09 22:48:54 CST

本文用于换对话后继续追踪当前实验。所有模式命名统一使用 `structured`、`kv_latent`、`kv_latent_0`、`kv_latent_N`，不使用旧代号。

## 1. 当前结论摘要

当前已经完成三类实验：

| 实验 | 任务类型 | 关键结论 |
|---|---|---|
| 涉密数据审计十轮 | 长中间推理，最终短 JSON，允许 executor 工具化算分 | executor 工具化后，`structured` 与 `kv_latent` 都达到 10/10 完全正确；`kv_latent` 更快、Agent 消息更少，但非文本 KV 传输规模很大 |
| 交易系统长日志根因定位一轮 | 长日志证据综合，最终短 JSON，禁止 executor 执行代码/工具 | 非零 latent steps 的 `kv_latent_16+` 全部 3/3 正确；`structured` 和 `kv_latent_0` 都错，但这是一轮结果，不能直接证明 structured 失败就是因为没有 latent KV |
| 交易系统长日志根因定位单 LLM 对照 | 同一任务文件、同一 Qwen3-8B、一次 chat completion、无多 Agent/无工具/无 KV latent | `single_llm` 单轮 3/3 正确，耗时 20.081s；说明该任务在紧凑全上下文 prompt 下，单模型可直接完成 |

最重要的实现判断：

`kv_latent_0` 当前并不等价于 `structured`。它只是把额外 latent forward steps 设为 0，但仍然走 latent KV graph、latent agent、KV handle 传递和 latent summarizer 解码路径。

## 2. 实验环境

| 项目 | 当前记录 |
|---|---|
| 工作目录 | `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz` |
| Docker 容器 | `SynapseX-wmw71` |
| 模型 | `/data/models/Qwen3-8B` |
| latent KV server | `src/latent_kv_model_server.py` |
| latent server 端口 | `8101` |
| OpenAI-compatible endpoint | `http://localhost:8101/v1` |
| backend | `LATENT_KV_BACKEND=real` |
| root-cause rerun GPU | GPU0 |
| root-cause single LLM GPU | GPU1 |
| classified executor-tool 十轮 GPU | GPU1 |
| thinking 设置 | `CHAT_DISABLE_THINKING=1` |

实验结束后 latent KV server 已停止。最近一次 single LLM 对照后，`localhost:8101/health` 不通，且没有残留 `latent_kv_model_server.py` 进程。

## 3. 当前相关文件

| 类型 | 路径 |
|---|---|
| 交易根因定位任务 | `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/task/lantent/trading_root_cause_1round/trading_root_cause_task.json` |
| 交易根因定位 runner | `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/latent_kv_exp/run_trading_root_cause_steps.py` |
| 交易根因定位结果 | `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/latent_kv_exp/trading_root_cause_steps_20260709_rerun_1round` |
| 交易根因定位报告 | `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/latent_kv_exp/trading_root_cause_steps_20260709_rerun_1round/REPORT.md` |
| 交易根因定位单 LLM runner | `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/latent_kv_exp/run_trading_root_cause_single_llm.py` |
| 交易根因定位单 LLM 结果 | `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/latent_kv_exp/trading_root_cause_single_llm_20260709_233045` |
| 交易根因定位单 LLM 报告 | `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/latent_kv_exp/trading_root_cause_single_llm_20260709_233045/REPORT.md` |
| 涉密审计十轮任务 | `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/task/lantent/classified_data_audit_10round/classified_data_audit_tasks.json` |
| 涉密审计 executor 工具化结果 | `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/latent_kv_exp/classified_data_audit_bd_executor_tool_gpu1_20260709_full10` |
| 涉密审计整理文档 | `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/docs/openos/notext_state_transfer/kv_latent/exp/classified_data_audit_bd_executor_tool_10round_20260709.md` |
| 普通 executor | `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/src/agent/executor.py` |
| latent executor/agent | `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/src/agent/latent_kv_agents.py` |
| graph 定义 | `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/src/graph.py` |

## 4. 代码实现状态

### 4.1 no-code executor

为长日志根因定位任务增加了 no-code executor 路径：

| 文件 | 行为 |
|---|---|
| `src/agent/executor.py` | 当 prompt 包含 `executor 阶段不得执行代码`、`禁止 executor 执行代码` 等标记时，不生成和执行 Python 代码，只返回 `no_code_evidence_synthesis` |
| `src/agent/latent_kv_agents.py` | latent executor 遇到 no-code 标记时，不调用 `generate_code` 和 `_run_safe_python`，只注入 no-code executor marker，并返回 evidence synthesis artifact |

这样做是为了满足“长日志根因定位”任务的公平约束：executor 不允许执行代码或工具，只能综合证据。

### 4.2 当前 latent graph

`build_latent_kv_graph()` 当前拓扑：

```text
planner_explicit_for_latent
  -> researcher_explicit_for_latent
  -> analyst_latent
  -> executor_latent
  -> summarizer_latent
```

其中 planner/researcher 复用 structured 逻辑生成显式 packet；analyst/executor/summarizer 走 latent KV handle。

普通 `structured` 拓扑：

```text
planner -> researcher -> analyst -> executor -> summarizer
```

它不使用 latent KV handle。

## 5. 涉密数据审计十轮实验

### 5.1 早期未工具化 executor 结果

结果目录：

```text
/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/latent_kv_exp/classified_data_audit_bd_gpu2_20260709_1240
```

报告文件：

```text
/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/latent_kv_exp/classified_data_audit_bd_gpu2_20260709_1240/REPORT.md
```

| 模式 | 十轮平均耗时 | 字段正确率 | 完全正确 | 消息轮数 | latent steps | KV 非文本传输 |
|---|---:|---:|---:|---:|---:|---:|
| structured | 106.2s | 3/40 | 0/10 | 7.0 | 0 | 0.01 MB |
| kv_latent | 100.9s | 30/40 | 2/10 | 4.0 | 80 | 2447.67 MB |

当时主要错误集中在 `risk_score` 精确算分：经常 case、tier、action 对，但分数有偏差。因此后续强化 executor，让它严格生成并执行计算代码，而不是让模型自由估算分数。

### 5.2 executor 工具化后十轮结果

结果目录：

```text
/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/latent_kv_exp/classified_data_audit_bd_executor_tool_gpu1_20260709_full10
```

本次 executor 工具化：当任务包含 classified audit 的 evidence packet 和分数字段时，executor 使用确定性 scorer 计算：

```text
risk_score = sensitivity_points + domain_points + channel_points + anomaly_points + repeat_points - mitigation_points
```

汇总结果：

| 模式 | 轮数 | 完全正确 | 字段正确率 | 总耗时 | 平均耗时 | Agent消息总数 | 平均消息/轮 | 文本通信字符总数 | 文本 token 估算 | 非文本传递总数 | 非文本规模总量 | latent steps |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| structured | 10 | 10/10 | 40/40 | 1090.615s | 109.061s | 70 | 7.0 | 664080 | 166024 | 30 | 0.117 MB | 0 |
| kv_latent | 10 | 10/10 | 40/40 | 935.011s | 93.501s | 40 | 4.0 | 645892 | 161476 | 60 | 24086.086 MB | 800 |

主要观察：

| 观察 | 说明 |
|---|---|
| 正确率 | executor 工具化后，两种模式都 10/10 完全正确 |
| 速度 | `kv_latent` 总耗时少 155.604s，平均单轮快约 14.268% |
| Agent 消息 | `kv_latent` 从 70 条降到 40 条，平均每轮从 7 条降到 4 条 |
| 文本通信 | `kv_latent` 文本字符和 token 估算略低 |
| 非文本状态 | `kv_latent` 增加大量 latent KV 非文本状态传递，总量约 23.52 GB |

解释：

该实验说明，对于“长中间推理、短 JSON 输出、精确计算交给 executor 工具”的任务，`kv_latent` 可以在不损失正确率的情况下减少显式消息数并提高速度。不过它的代价是显著增加 KV 非文本状态传输规模。

## 6. 长日志根因定位一轮实验

### 6.1 任务说明

任务文件：

```text
/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/task/lantent/trading_root_cause_1round/trading_root_cause_task.json
```

任务设计：

| 项目 | 内容 |
|---|---|
| 输入 | 合成交易系统长日志摘要、指标、变更记录 |
| 目标 | 找出 `root_cause`、`severity`、`first_bad_component` |
| 输出 | 短 JSON |
| 约束 | executor 阶段不得执行代码或工具，只能做证据综合 |
| 公平性 | structured 和 kv_latent 使用同一个任务、同一参考答案、同一 no-code executor 约束 |

参考答案：

```json
{
  "root_cause": "ordergateway_auth_cache_key_normalization",
  "severity": "P1",
  "first_bad_component": "OrderGateway"
}
```

### 6.2 step 配置说明

报告中的 `Steps A/E/P/S` 含义：

| 缩写 | 含义 |
|---|---|
| A | Analyst latent steps |
| E | Executor latent steps |
| P | Post-execution latent steps |
| S | Summarizer latent steps |

例如 `16/16/0/0` 表示 analyst 16 步、executor 16 步、post-execution 0 步、summarizer 0 步，总计 32 latent steps。

### 6.3 一轮 rerun 结果

结果目录：

```text
/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/latent_kv_exp/trading_root_cause_steps_20260709_rerun_1round
```

结果表：

| 模式 | Steps A/E/P/S | Time(s) | Token in | Token out | latent steps | KV MB | Msgs | Text chars | Non-text MB | Fields | Answer |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| structured | - | 201.109 | 36000 | 3072 | 0 | 0.00 | 7 | 290811 | 0.01 | 0/3 | `{"root_cause": "True", "severity": "TRUE", "first_bad_component": "True"}` |
| kv_latent_0 | 0/0/0/0 | 203.028 | 30098 | 2560 | 0 | 2544.75 | 4 | 268508 | 2544.76 | 0/3 | `{"root_cause": "clearing_batch_backpressure", "severity": "P2", "first_bad_component": "AuditLogger"}` |
| kv_latent_16 | 8/8/0/0 | 203.959 | 30114 | 2560 | 16 | 2550.38 | 4 | 270450 | 2550.39 | 3/3 | `{"root_cause": "ordergateway_auth_cache_key_normalization", "severity": "P1", "first_bad_component": "OrderGateway"}` |
| kv_latent_32 | 16/16/0/0 | 186.587 | 30130 | 2560 | 32 | 2556.00 | 4 | 270461 | 2556.01 | 3/3 | `{"root_cause": "ordergateway_auth_cache_key_normalization", "severity": "P1", "first_bad_component": "OrderGateway"}` |
| kv_latent_56 | 32/16/8/0 | 188.647 | 30154 | 2560 | 56 | 2563.88 | 4 | 270439 | 2563.89 | 3/3 | `{"root_cause": "ordergateway_auth_cache_key_normalization", "severity": "P1", "first_bad_component": "OrderGateway"}` |
| kv_latent_80 | 48/24/8/0 | 230.645 | 30178 | 2560 | 80 | 2572.88 | 4 | 270465 | 2572.89 | 3/3 | `{"root_cause": "ordergateway_auth_cache_key_normalization", "severity": "P1", "first_bad_component": "OrderGateway"}` |
| kv_latent_120 | 64/32/16/8 | 191.852 | 30218 | 2560 | 120 | 3457.41 | 4 | 270443 | 3457.42 | 3/3 | `{"root_cause": "ordergateway_auth_cache_key_normalization", "severity": "P1", "first_bad_component": "OrderGateway"}` |

主要观察：

| 观察 | 说明 |
|---|---|
| `structured` | 本轮 0/3，输出了占位式 `True` 值 |
| `kv_latent_0` | 本轮 0/3，但错法不同，说明它不是 structured 等价对照 |
| `kv_latent_16+` | 所有非零 latent step 配置均 3/3 正确 |
| 耗时 | `kv_latent_32` 本轮最快，但单轮有波动，不能仅凭一轮断定 32 步最优 |
| 非文本规模 | `kv_latent` 每轮约 2.5GB 以上 KV 非文本传输，`kv_latent_120` 更高 |

## 7. `kv_latent_0` 是否等价于 `structured`

当前答案：不等价。

`kv_latent_0` 的含义是：

```text
使用 latent KV 拓扑和 KV 状态传递，但额外 latent forward steps 为 0。
```

它仍然会：

| 差异点 | structured | kv_latent_0 |
|---|---|---|
| graph | `build_graph(mode="structured")` | `build_latent_kv_graph()` |
| analyst | `analyst` | `analyst_latent` |
| executor | `executor` | `executor_latent` |
| summarizer | `summarizer` | `summarizer_latent` |
| 状态传递 | 显式字段、context packet、embedding | 显式 packet + server-side KV handle |
| final decoding | 普通 summarizer | 从 inherited KV state decode |
| root-cause rerun LLM calls | 6 | 5 |
| root-cause rerun messages | 7 | 4 |
| root-cause rerun KV MB | 0 | 2544.75 |

所以 `kv_latent_0` 不是“没有推理”，也不是“structured 的完全等价版本”。它只是没有额外插入非文本 latent step，但模型仍然会在 planner/researcher/summarizer 等文本生成阶段做普通推理，并且状态形态已经变了。

## 8. 长日志根因定位单 LLM 对照

### 8.1 实验目的

这次对照用于回答：

```text
同一个交易根因定位任务，如果不拆成多 Agent，不走 structured graph，也不走 latent KV graph，单个 Qwen3-8B 直接读完整证据并输出最终 JSON，能否完成？
```

### 8.2 运行设置

| 项目 | 内容 |
|---|---|
| 容器 | `SynapseX-wmw71` |
| 模型 | `/data/models/Qwen3-8B` |
| endpoint | `http://localhost:8101/v1` |
| runner | `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/latent_kv_exp/run_trading_root_cause_single_llm.py` |
| 结果目录 | `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/latent_kv_exp/trading_root_cause_single_llm_20260709_233045` |
| temperature | `0.0` |
| max_tokens | `1024` |
| thinking | `CHAT_DISABLE_THINKING=1` |
| graph | 无 LangGraph multi-agent graph |
| executor 工具 | 无 executor，且 prompt 禁止执行代码/工具 |
| latent KV | 无 latent steps，无 KV handle |

重要实现细节：

服务端 `/v1/chat/completions` 当前对输入执行 `truncation=True, max_length=6000`。原始 pretty JSON prompt 约 8635 tokens，会被截断。为了避免截断，本次 single LLM runner 使用行式紧凑 prompt：保留完整 58 条日志摘要、指标、变更、业务影响、候选根因、排除观察和严重性规则，但去掉 JSON 长字段名、缩进和 benchmark 说明。最终 chat prompt 为 5276 input tokens，未超过服务端截断上限。

### 8.3 结果

| Mode | Time(s) | Token in | Token out | Msgs | Handoffs | Text chars | Non-text MB | Fields | Answer |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| single_llm | 20.081 | 5276 | 464 | 2 | 0 | 12369 | 0.00 | 3/3 | `{"root_cause": "ordergateway_auth_cache_key_normalization", "severity": "P1", "first_bad_component": "OrderGateway"}` |

参考答案：

```json
{
  "root_cause": "ordergateway_auth_cache_key_normalization",
  "severity": "P1",
  "first_bad_component": "OrderGateway"
}
```

### 8.4 当前解释

单 LLM 在紧凑全上下文 prompt 下本轮 3/3 正确，且耗时明显低于当前 multi-agent structured/kv_latent 路径。这说明本任务的单轮 evidence 本身并没有超出 Qwen3-8B 在一次有效上下文内完成根因定位的能力。

但该结果不能直接否定 latent KV 的价值，原因是：

| 差异 | 说明 |
|---|---|
| prompt 组织不同 | single LLM 使用避免截断的行式紧凑 prompt；multi-agent runner 使用 graph 内各 agent 的材料组织方式 |
| 工作流目标不同 | single LLM 只测最终 JSON；multi-agent 还产生 planner/researcher/analyst/executor/summarizer 中间产物 |
| 样本仍是一轮 | 目前只有同一个 root-cause 任务的一次 single LLM 结果 |
| 多 Agent 有额外损耗 | structured 错误可能来自 agent 拆分、prompt 截断、输出规整或 graph 状态传递，而不是单模型能力不足 |

更准确的新增结论：

```text
structured 在本轮失败，并不等价于 Qwen3-8B 单模型不能解决该任务；至少在紧凑全上下文单 LLM prompt 下，Qwen3-8B 可以 3/3 完成。
```

## 9. 对“latent steps 是否增加思考能力”的当前判断

更准确的说法：

`latent steps` 增加的是不解码成文本的内部 forward 计算轨迹，可能给模型更多机会在 KV 状态里整合证据，但不能直接等同于人类意义上的“思考能力增强”。

当前 root-cause 一轮结果支持一个信号：

```text
非零 latent steps 可能帮助长证据链综合。
```

但当前证据不足以证明因果关系，原因包括：

| 混杂因素 | 说明 |
|---|---|
| 拓扑不同 | `structured` 和 `kv_latent_0` 不是同一实现路径 |
| prompt 拼接不同 | latent analyst/summarizer 使用不同材料组织方式 |
| final JSON 提取路径不同 | structured 和 latent summarizer 的输出规整路径不同 |
| 单轮样本太少 | root-cause 目前只跑了一轮 |
| 随机性 | 即使同模型同任务，单轮耗时和答案仍可能波动 |

因此当前不能说：

```text
structured 答不对可以确认是因为没有 kv_latent。
```

只能说：

```text
在当前这条实现路径和这一轮任务里，非零 latent steps 的 kv_latent 配置表现明显更好。
```

## 10. 下一步建议

如果要验证“latent steps 增加非文本内部计算轨迹，是否帮助长中间推理”，建议增加控制组：

| 控制组 | 目的 |
|---|---|
| `structured_same_prompt` | 尽量让 structured 使用与 latent analyst 相同的压缩 prompt |
| `kv_latent_0` | 保留 latent topology，但不加额外 latent steps |
| `kv_latent_16/32/56/80/120` | 做 step ablation |
| `single_agent_full_context` | 已完成单轮；用于排除多 agent 拆分导致的信息损失 |
| `structured_temperature0` | 降低随机性 |
| `kv_latent_0_equiv` | 如果要真正等价，应直接复用 structured agent，只改变统计标签或增加极小 wrapper |

建议每个配置至少跑 5 到 10 轮，统计：

| 指标 | 说明 |
|---|---|
| 字段正确率 | `root_cause`、`severity`、`first_bad_component` |
| 完全正确率 | 三个字段全对 |
| 单轮耗时 | 每轮 wall time |
| 总耗时 | 所有轮次总和 |
| Agent 消息数 | metrics message count |
| 文本通信字符/token | 当前 runner 已估算 |
| 非文本传递次数/规模 | embedding + latent KV |
| latent steps | A/E/P/S 和总数 |

如果目标是更严格地证明 latent steps 的作用，最关键的是先修正或新增一个真正的等价 0-step control。当前 `kv_latent_0` 不能承担这个角色。

## 11. 复现实验入口

启动 latent KV server 示例：

```bash
docker exec -d SynapseX-wmw71 bash -lc 'cd /data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz && export PYTHONPATH=$PWD/src:$PYTHONPATH && export CUDA_VISIBLE_DEVICES=0 && export LATENT_KV_SERVER_GPU=0 && export LATENT_KV_SERVER_PORT=8101 && export VLLM_MODEL_PATH=/data/models/Qwen3-8B && python3 src/latent_kv_model_server.py > /tmp/latent_kv_server_steps_rerun.log 2>&1'
```

运行长日志根因定位 step ablation：

```bash
docker exec -w /data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz -e LATENT_KV_BACKEND=real -e LATENT_KV_SERVER_PORT=8101 SynapseX-wmw71 python3 -u exp/latent_kv_exp/run_trading_root_cause_steps.py --output-dir exp/latent_kv_exp/<new_dir>
```

运行长日志根因定位 single LLM 对照：

```bash
docker exec SynapseX-wmw71 bash -lc 'cd /data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz && export CHAT_DISABLE_THINKING=1 CHAT_BASE_URL=http://localhost:8101/v1 CHAT_API_KEY=token-abc CHAT_MODEL=/data/models/Qwen3-8B && python3 -u exp/latent_kv_exp/run_trading_root_cause_single_llm.py --output-dir exp/latent_kv_exp/<new_single_llm_dir>'
```

停止 latent KV server：

```bash
docker exec SynapseX-wmw71 bash -lc "pkill -f latent_kv_model_server.py 2>/dev/null || true"
```

注意：实验结束后应确认 health check 已停止且没有残留 server 进程。
