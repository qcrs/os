# Classified Data Audit structured vs kv_latent 十轮对比实验统计

生成时间: 2026-07-09 15:31:35 CST

## 1. 实验目标

本实验对“合成涉密数据访问审计长中间推理任务集”进行 10 轮 structured 与 kv_latent 对比，统计两种 Agent 通信/状态传递模式在同一任务集上的端到端表现。

| 模式 | 说明 |
|---|---|
| structured | planner/researcher/analyst/executor/summarizer 通过结构化消息、context packet 和少量 embedding 非文本状态传递协作 |
| kv_latent | planner/researcher 使用显式结构化 packet；analyst_latent -> executor_latent -> summarizer_latent 通过 server-side latent KV handle 传递非文本状态 |

本次实验已强化 executor 阶段：当 prompt 中包含 classified audit 的 `Evidence Packet` 和 case points 时，executor 不再让模型自由估算 `risk_score`，而是生成并执行确定性 scorer，严格按公式计算最高风险 case、tier 和 action。

## 2. 原始数据位置

实验结果目录：

```text
/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/latent_kv_exp/classified_data_audit_bd_executor_tool_gpu1_20260709_full10
```

关键结果文件：

| 文件 | 内容 |
|---|---|
| `REPORT.md` | 原始 structured vs kv_latent 十轮报告 |
| `all_results.json` | structured 和 kv_latent 合并结果 |
| `RUN_MANIFEST.json` | 运行配置摘要 |

任务源文件：

```text
/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/task/lantent/classified_data_audit_10round/classified_data_audit_tasks.json
```

## 3. 任务说明

任务集为合成脱敏涉密数据访问审计场景，不包含真实涉密数据、真实人员、真实项目或真实系统口令。每轮给出 3 个候选涉密访问 case，系统需要选择最高风险 case，并输出短 JSON 处置结论。

### 3.1 共享规则

风险公式：

```text
risk_score = sensitivity_points + domain_points + channel_points + anomaly_points + repeat_points - mitigation_points
```

风险分层：

| Tier | 条件 | Action |
|---|---|---|
| CRITICAL | `risk_score >= 70` | `isolate_account_and_open_major_incident` |
| HIGH | `55 <= risk_score < 70` | `freeze_export_and_start_review` |
| MEDIUM | `40 <= risk_score < 55` | `require_manager_reapproval` |
| LOW | `risk_score < 40` | `log_and_monitor` |

最终答案 JSON contract：

```json
{
  "case_id": "<highest risk case id>",
  "risk_score": "<integer risk_score>",
  "tier": "<LOW|MEDIUM|HIGH|CRITICAL>",
  "action": "<one valid action>"
}
```

### 3.2 十轮任务与参考答案

| 轮次 | 任务ID | 标题 | 参考答案 |
|---:|---|---|---|
| 1 | classified_round_01_export_spike | 批量导出突增：识别最高风险涉密访问 | C-002 / 67 / HIGH |
| 2 | classified_round_02_repeat_after_warning | 预警后重复访问：高风险批处理导出 | C-014 / 81 / CRITICAL |
| 3 | classified_round_03_cross_domain_review | 跨域访问复核：源代码与国防项目并行告警 | C-032 / 66 / HIGH |
| 4 | classified_round_04_major_incident_candidate | 重大事件候选：核心涉密项目批量读取 | C-044 / 83 / CRITICAL |
| 5 | classified_round_05_high_tie_break | 高风险近似分数：严格选择最高 risk_score | C-053 / 66 / HIGH |
| 6 | classified_round_06_critical_repeat | 重复主体升级：隔离账号与重大事件 | C-061 / 80 / CRITICAL |
| 7 | classified_round_07_mitigation_misleading | 缓解措施误导：不要只看原始敏感等级 | C-073 / 76 / CRITICAL |
| 8 | classified_round_08_high_not_critical | 高风险但非重大：冻结导出复核 | C-083 / 67 / HIGH |
| 9 | classified_round_09_clear_critical | 明确重大事件：国防项目核心包导出 | C-091 / 85 / CRITICAL |
| 10 | classified_round_10_final_audit_lockdown | 终局审计：多个高敏 case 中选择最高风险 | C-101 / 81 / CRITICAL |

## 4. 实验设置

| 项目 | 设置 |
|---|---|
| 容器 | `SynapseX-wmw71` |
| 模型 | `/data/models/Qwen3-8B` |
| 推理服务 | `src/latent_kv_model_server.py` |
| GPU | 宿主 GPU1；容器内通过 `CUDA_VISIBLE_DEVICES=1` 暴露为 `cuda:0` |
| 服务端口 | `8101` |
| 轮数 | structured 10 轮，kv_latent 10 轮 |
| 调用拓扑 | planner -> 3 researchers -> analyst -> executor -> summarizer |
| kv_latent 配置 | analyst=48, executor=24, post_exec=8, summarizer=0，总计 80 latent steps/轮 |
| executor 计算 | `classified_data_audit_scorer` 确定性工具计算 `risk_score/tier/action` |

实验结束后已停止 latent KV server；`localhost:8101/health` 不通，容器进程列表无 `latent_kv_model_server.py` 残留。

## 5. 汇总结果

| 模式 | 轮数 | 完全正确 | 字段正确率 | 总耗时(s) | 平均耗时(s) | 最短/最长(s) | Agent消息总数 | 平均消息/轮 | 文本通信字符总数 | 文本token估算总数 | 非文本传递总数 | 非文本规模总量 | Latent步数总量 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| structured | 10 | 10/10 | 40/40 | 1090.615 | 109.061 | 106.049 / 119.670 | 70 | 7.0 | 664080 | 166024 | 30 | 0.117 MB | 0 |
| kv_latent | 10 | 10/10 | 40/40 | 935.011 | 93.501 | 90.466 / 99.927 | 40 | 4.0 | 645892 | 161476 | 60 | 24086.086 MB | 800 |

补充指标：

| 模式 | 平均 input token | 平均 output token | embedding 非文本传递 | embedding 规模 | latent KV 传递 | latent KV 规模 |
|---|---:|---:|---:|---:|---:|---:|
| structured | 11836.6 | 3072.0 | 30 | 0.117 MB | 0 | 0 MB |
| kv_latent | 12394.2 | 2560.0 | 30 | 0.117 MB | 30 | 24085.969 MB |

## 6. 主要对比

| 对比项 | structured | kv_latent | 变化 |
|---|---:|---:|---:|
| 总耗时 | 1090.615s | 935.011s | kv_latent 少 155.604s |
| 平均单轮耗时 | 109.061s | 93.501s | kv_latent 快 14.268% |
| Agent 消息总数 | 70 | 40 | kv_latent 少 30 条 |
| 平均消息/轮 | 7.0 | 4.0 | kv_latent 少 3.0 条/轮 |
| 文本通信字符总数 | 664080 | 645892 | kv_latent 少 18188 字符 |
| 文本 token 估算总数 | 166024 | 161476 | kv_latent 少 4548 token |
| 非文本传递总数 | 30 | 60 | kv_latent 多 30 次 |
| 非文本规模总量 | 0.117 MB | 24086.086 MB | kv_latent 显著更大，主要为 latent KV |
| 完全正确 | 10/10 | 10/10 | 持平 |

观察：

| 结论 | 说明 |
|---|---|
| kv_latent 端到端更快 | 10 轮总耗时少 155.604s，平均单轮快 14.268% |
| kv_latent 消息更少 | Agent 间消息从 70 降到 40，平均每轮从 7 条降到 4 条 |
| kv_latent 文本通信略低 | 文本字符和 token 估算均小幅下降 |
| kv_latent 非文本状态规模大 | 额外 30 次 latent KV 传递，总量约 23.52 GB；这是本模式用非文本 KV 状态替代部分显式中间文本的主要代价 |
| executor 工具化后正确率持平且满分 | 两种模式均为 10/10 完全正确，risk_score 不再由模型自由估算导致漂移 |

## 7. 每轮结果明细

字段说明：

| 字段 | 含义 |
|---|---|
| time | 单轮端到端耗时，单位秒 |
| msgs | Agent 间消息条数 |
| text chars | 估算文本通信字符开销 |
| text tok est | 按 4 chars/token 估算的文本通信 token |
| nontext | 非文本状态传递次数 |
| nontext MB | 非文本状态传递规模 |
| latent | latent steps |
| correct | 字段正确数 |

### 7.1 structured

| 轮次 | time | msgs | text chars | text tok est | nontext | nontext MB | latent | correct |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 116.466 | 7 | 70014 | 17504 | 3 | 0.012 | 0 | 4/4 |
| 2 | 106.925 | 7 | 62525 | 15632 | 3 | 0.012 | 0 | 4/4 |
| 3 | 119.670 | 7 | 71196 | 17799 | 3 | 0.012 | 0 | 4/4 |
| 4 | 107.041 | 7 | 72378 | 18095 | 3 | 0.012 | 0 | 4/4 |
| 5 | 106.049 | 7 | 64780 | 16195 | 3 | 0.012 | 0 | 4/4 |
| 6 | 106.665 | 7 | 65580 | 16395 | 3 | 0.012 | 0 | 4/4 |
| 7 | 107.335 | 7 | 75682 | 18921 | 3 | 0.012 | 0 | 4/4 |
| 8 | 107.598 | 7 | 52337 | 13085 | 3 | 0.012 | 0 | 4/4 |
| 9 | 106.746 | 7 | 51050 | 12763 | 3 | 0.012 | 0 | 4/4 |
| 10 | 106.120 | 7 | 78538 | 19635 | 3 | 0.012 | 0 | 4/4 |

### 7.2 kv_latent

| 轮次 | time | msgs | text chars | text tok est | nontext | nontext MB | latent | correct |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 91.870 | 4 | 63852 | 15963 | 6 | 2390.215 | 80 | 4/4 |
| 2 | 90.584 | 4 | 60331 | 15083 | 6 | 2285.449 | 80 | 4/4 |
| 3 | 90.466 | 4 | 65059 | 16265 | 6 | 2421.293 | 80 | 4/4 |
| 4 | 97.542 | 4 | 65702 | 16426 | 6 | 2460.949 | 80 | 4/4 |
| 5 | 92.683 | 4 | 66946 | 16737 | 6 | 2465.168 | 80 | 4/4 |
| 6 | 90.640 | 4 | 67243 | 16811 | 6 | 2503.559 | 80 | 4/4 |
| 7 | 92.391 | 4 | 50588 | 12647 | 6 | 1898.449 | 80 | 4/4 |
| 8 | 92.711 | 4 | 69268 | 17317 | 6 | 2566.559 | 80 | 4/4 |
| 9 | 96.197 | 4 | 65157 | 16290 | 6 | 2501.027 | 80 | 4/4 |
| 10 | 99.927 | 4 | 71746 | 17937 | 6 | 2593.418 | 80 | 4/4 |

## 8. 结论

在这个“长中间推理、最终短 JSON、且 executor 可确定性计算”的合成涉密数据审计任务上，executor 工具化后 structured 和 kv_latent 都达到 10/10 完全正确。质量持平时，kv_latent 的主要收益体现在端到端耗时和 Agent 消息数量：总耗时下降约 14.3%，消息数从 70 条降到 40 条。

代价是 kv_latent 的非文本状态规模显著增大：10 轮 latent KV 传递约 24085.969 MB。若后续优化，应重点降低 KV handle 传递统计规模、减少固定 decode 开销，并保持 executor 阶段继续使用确定性工具计算高精度字段。
