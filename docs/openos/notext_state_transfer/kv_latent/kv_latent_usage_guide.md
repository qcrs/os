# KV Latent 模式适用任务、运行环境与使用说明

生成时间：2026-07-08

本文档说明 `kv_latent` / `D_latent_kv` 模式适合什么任务、需要什么运行环境、如何启动模型服务、如何运行现有实验脚本，以及如何解读输出结果。架构设计细节见同目录的 `kv_latent_detailed_design.md` 和 `D_latent_kv_design.md`。

## 1. 模式定位

`kv_latent` 是一种多 Agent 非文本状态传递模式。当前仓库里的 D 模式采用混合设计：

```text
planner -> researcher(s) -> analyst_latent -> executor_latent -> summarizer_latent
```

前半段保留显式结构化状态：

- planner 输出 `plan`、`sub_queries`。
- researcher 输出 `context_packets`、`evidence_spans`、`doc_key`、`full_doc_ref`。

后半段使用 server-side KV continuation：

- analyst 把显式上下文 prefill 成 KV handle。
- executor 继承 analyst 的 `latent_kv_handle_id`，继续 latent steps 和 CodeAct。
- summarizer 继承 executor 的 KV handle，只解码最终 JSON 或最终答案。

这不是“完全无文本”方案。它的目标是减少后半段长中间状态的显式自然语言传递，同时保留前半段证据链可审计性。

## 2. 适用任务

### 2.1 更适合的任务

`kv_latent` 更适合以下任务：

| 任务特征 | 原因 |
|---|---|
| 多 Agent 串行链路较长 | 上游长分析不必反复 decode/prefill 给下游 |
| 中间推理长、最终答案短 | 最终只需要 JSON/短答案，但 analyst/executor 需要保留大量隐含状态 |
| 需要连续轮次继承 | KV chain 能承载前序约束、决策和计算状态 |
| 有明确 final schema | 可以客观评估 D 模式是否真的保持质量 |
| researcher 证据可结构化 | 前半段可以用 context packet 保留可追溯证据 |
| 下游需要继承工具结果 | executor 的 CodeAct result 可以 inject 回 KV chain |

典型例子：

- 连续事故响应：每轮包含症状、日志、指标、变更、候选根因；最终只输出事故处置 JSON。
- 长链路诊疗/风控/审计：中间需要长证据和因果分析，最终输出结构化决策。
- 组合推理或路径规划：中间需要保留候选集合、约束和计算过程，最终输出路线/成本 JSON。
- 多轮系统设计审查：每轮继承前轮架构约束、风险列表和容量估算。

### 2.2 不太适合的任务

以下任务通常不适合优先使用 `kv_latent`：

| 任务特征 | 原因 |
|---|---|
| 单轮短问答 | 文本 handoff 本身很小，KV server 成本不划算 |
| 每一步都必须给人读完整解释 | latent 中间态不可直接审计，需要额外 decode |
| 强并行 latent 分支后需要无损 merge | 当前实现不支持多个 KV branch 直接合并 |
| 没有 GPU/模型服务资源 | 真实 D 模式依赖 `latent_kv_model_server` |
| 只看最终自然语言流畅度 | D 模式主要验证状态传递，不是文本润色优化 |

## 3. 已有任务集

### 3.1 交易系统连续事故响应十轮实验

任务文件：

```text
task/lantent/incident_response_10round/incident_response_tasks.json
```

Suite：

```text
trading_incident_response_latentmas_10round_v1
```

任务形态：

- 平台：SkyBridge 实时交易与清结算平台。
- 涉及服务：OrderGateway、RiskEngine、MatchingCore、ClearingService、SettlementService、MarketDataFeed、NotificationHub、AuditLogger、PositionManager、RegulatoryReporter。
- 每轮输入一个 `evidence_packet`，包含时间窗口、症状、指标、日志、近期变更和候选根因。
- 10 轮通过 `inherits` 连续继承前序处置上下文。
- researcher 输出长证据报告，analyst 输出长因果分析，executor 输出计算与处置矩阵，summarizer 只输出最终 JSON。

最终 JSON 字段：

```text
root_cause_service
root_cause_code
severity
primary_action
report_deadline_minutes
estimated_loss_usd
```

适合 `kv_latent` 的原因：

- A/B 模式会把 researcher、analyst、executor 的长中间文本反复传给下游。
- D 模式可以从 analyst 之后继承 KV handle，减少长中间状态文本搬运。
- 最终答案是 6 字段 JSON，适合 exact match 评测。

已有结果示例：

```text
exp/latent_kv_exp/incident_response_abd_20260705_164545-3.4%
exp/latent_kv_exp/incident_response_bd_20260707_1751
```

### 3.2 四城市巡检路线十轮实验

任务文件：

```text
task/lantent/4city.json
```

Suite：

```text
4city_reasoning_5round_v1
```

任务形态：

- 城市：A、B、C、D。
- 距离矩阵固定且对称。
- 默认从 A 出发，访问其他城市各一次并返回 A。
- A 固定为起点时，B/C/D 全排列，共 6 条候选巡回路线。
- 每轮改变一个约束，例如道路关闭、必须包含某条边、访问顺序、不返回 A、最长路线、严格第二短路线等。
- 要求模型用 Python 枚举或筛选候选路线，最终输出 JSON。

最终 JSON 字段：

```text
route
total_cost
verification
```

适合 `kv_latent` 的原因：

- 搜索空间小，答案可穷举验证。
- 质量问题容易定位为路线解析失败、成本计算错误或约束筛选错误。
- 适合快速比较 B_structured 和 D_latent_kv 的通信开销、可解析性和正确性。

已有结果示例：

```text
exp/latent_kv_exp/4city_bd_latest_stats_gpu2_20260707_122042
```

## 4. 运行环境

### 4.1 基础路径

仓库路径：

```text
/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz
```

模型路径：

```text
/data/models/Qwen3-8B
```

主要源码：

```text
src/latent_kv_model_server.py
src/latent_kv_runtime.py
src/agent/latent_kv_agents.py
src/graph.py
```

主要实验脚本：

```text
exp/latent_kv_exp/run_incident_response_abd.py
exp/latent_kv_exp/run_4city_bd_latest_stats.py
exp/latent_kv_exp/run_7city_abd.py
exp/latent_kv_exp/run_abd_10round_0707.py
```

### 4.2 PPT 文档中记录的 4city 环境

`exp/ppt_doc_2kv_latent_exp.md` 中记录的四城市实验环境如下：

| 项目 | 值 |
|---|---|
| 容器 | `SynapseX-wmw71` |
| 物理 GPU | GPU2 |
| 模型服务 | `latent_kv_model_server` |
| 服务端口 | `8101` |
| 模型 | `/data/models/Qwen3-8B` |
| 运行模式 | 只跑 `B_structured` 与 `D_latent_kv` |
| D 配置 | `ANALYST_LATENT_STEPS=64`、`EXECUTOR_LATENT_STEPS=32`、`POST_EXEC_LATENT_STEPS=16`、`SUMMARIZER_LATENT_STEPS=0` |
| 每轮 latent steps | 112 |
| 实验脚本 | `exp/latent_kv_exp/run_4city_bd_latest_stats.py` |
| 公平性口径 | B/D 都通过同一个 `latent_kv_model_server` 推理服务 |

注意：仓库里的 `run_latent_kv_server.sh` 默认写的是容器 `SynapseX-wmw71`、端口 `8101`、模型 `/data/models/Qwen3-8B`、`GPU=1`。如果要完全复现 PPT 里的 GPU2 环境，可以手动启动 server 并设置 `CUDA_VISIBLE_DEVICES=2`；在容器内经过 `CUDA_VISIBLE_DEVICES` 重映射后，`LATENT_KV_SERVER_GPU=0`。

### 4.3 推荐环境变量

通用环境：

```bash
cd /data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export CHAT_MODEL=/data/models/Qwen3-8B
export CHAT_API_KEY=token-abc
export CHAT_DISABLE_THINKING=1
```

Latent KV server：

```bash
export LATENT_KV_BACKEND=real
export LATENT_KV_SERVER_HOST=localhost
export LATENT_KV_SERVER_PORT=8101
export LATENT_KV_DOCKER_CONTAINER=SynapseX-wmw71
export VLLM_MODEL_PATH=/data/models/Qwen3-8B
```

D 模式 latent steps：

```bash
export ANALYST_LATENT_STEPS=64
export EXECUTOR_LATENT_STEPS=32
export POST_EXEC_LATENT_STEPS=16
export SUMMARIZER_LATENT_STEPS=0
```

其他常用配置：

```bash
export RESEARCHER_FANOUT=3
export LATENT_ALIGNMENT=normalized_identity
export PERSISTENT_MEMORY_ENABLED=0
```

## 5. 启动模型服务

### 5.1 使用仓库脚本启动

默认脚本：

```bash
cd /data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz
bash run_latent_kv_server.sh
```

检查服务：

```bash
bash run_latent_kv_server.sh --check
docker exec SynapseX-wmw71 curl -s http://localhost:8101/health
```

前台启动查看日志：

```bash
bash run_latent_kv_server.sh --fg
```

停止服务：

```bash
bash run_latent_kv_server.sh --stop
```

### 5.2 手动按 GPU2 启动

如果要使用 PPT 记录的物理 GPU2：

```bash
docker exec -d SynapseX-wmw71 bash -lc '
cd /data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz
export PYTHONPATH=$PWD/src:$PYTHONPATH
export CUDA_VISIBLE_DEVICES=2
export LATENT_KV_SERVER_GPU=0
export LATENT_KV_SERVER_PORT=8101
export VLLM_MODEL_PATH=/data/models/Qwen3-8B
python3 src/latent_kv_model_server.py > /tmp/latent_kv_server_gpu2.log 2>&1
'
```

检查：

```bash
docker exec SynapseX-wmw71 curl -s http://localhost:8101/health
docker exec SynapseX-wmw71 tail -50 /tmp/latent_kv_server_gpu2.log
```

如果端口被占用，可以换端口，例如 `8102`，并同步设置 runner 环境变量：

```bash
export LATENT_KV_SERVER_PORT=8102
```

## 6. 运行实验

### 6.1 四城市 B/D 实验

推荐命令：

```bash
cd /data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LATENT_KV_BACKEND=real
export LATENT_KV_SERVER_PORT=8101
export CHAT_MODEL=/data/models/Qwen3-8B
export CHAT_API_KEY=token-abc
export CHAT_DISABLE_THINKING=1
export ANALYST_LATENT_STEPS=64
export EXECUTOR_LATENT_STEPS=32
export POST_EXEC_LATENT_STEPS=16
export SUMMARIZER_LATENT_STEPS=0

python -u exp/latent_kv_exp/run_4city_bd_latest_stats.py \
  --modes B D \
  --rounds 10
```

指定输出目录：

```bash
python -u exp/latent_kv_exp/run_4city_bd_latest_stats.py \
  --modes B D \
  --rounds 10 \
  --output-dir exp/latent_kv_exp/4city_bd_manual_run
```

输出文件：

```text
all_results.json
mode_B_all_rounds.json
mode_D_all_rounds.json
round_B_*.json
round_D_*.json
REPORT.md
RUN_MANIFEST.json
```

### 6.2 交易事故响应 A/B/D 实验

推荐命令：

```bash
cd /data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LATENT_KV_BACKEND=real
export LATENT_KV_SERVER_PORT=8101
export CHAT_MODEL=/data/models/Qwen3-8B
export CHAT_API_KEY=token-abc
export CHAT_DISABLE_THINKING=1
export ANALYST_LATENT_STEPS=64
export EXECUTOR_LATENT_STEPS=32
export POST_EXEC_LATENT_STEPS=16
export SUMMARIZER_LATENT_STEPS=0

python -u exp/latent_kv_exp/run_incident_response_abd.py \
  --modes A B D \
  --rounds 10
```

只跑 B/D 并指定输出目录：

```bash
python -u exp/latent_kv_exp/run_incident_response_abd.py \
  --modes B D \
  --rounds 10 \
  --output-dir exp/latent_kv_exp/incident_response_bd_manual_run
```

断点续跑：

```bash
python -u exp/latent_kv_exp/run_incident_response_abd.py \
  --modes B D \
  --rounds 10 \
  --output-dir exp/latent_kv_exp/incident_response_bd_manual_run \
  --resume
```

输出文件：

```text
all_results.json
mode_A_all_rounds.json
mode_B_all_rounds.json
mode_D_all_rounds.json
round_A_*.json
round_B_*.json
round_D_*.json
REPORT.md
RUN_MANIFEST.json
```

### 6.3 其他 runner

| 脚本 | 任务 | 常用参数 |
|---|---|---|
| `run_7city_abd.py` | 7 城市路线推理 | `--modes A B D --rounds 10` |
| `run_abd_10round_0707.py` | 10 轮公平对比实验 | `--modes D B A --rounds 10` |
| `run_arch_abd.py` | 架构审计类任务 | 见脚本内参数 |
| `run_medical_abd.py` | 医疗案例类任务 | 见脚本内参数 |
| `run_qwen3_8b_only_baseline.py` | Qwen3-8B 单模型 baseline | 见脚本内参数 |

## 7. 结果指标说明

常见结果字段：

| 字段 | 说明 |
|---|---|
| `wall_time_s` | 单轮端到端耗时 |
| `llm_calls` | LLM 调用次数 |
| `input_tokens` / `output_tokens` | 模型服务 usage 记账 token |
| `message_count` | AgentMessage 数量 |
| `text_comm_chars` | 显式 state 文本/JSON 通信字符估算 |
| `text_comm_tokens_est` | `ceil(text_comm_chars / 4)` 的粗略 token 估算 |
| `latent_steps` | D 模式追加的 latent steps |
| `kv_bytes_transfer` | KV 状态传递/继承的估算字节 |
| `nontext_transfer_count` / `nontext_transfer_bytes` | embedding + latent KV 的非文本传递统计 |
| `context_original_chars` / `context_compressed_chars` | context packet 压缩前后字符数 |
| `correct_fields` / `total_fields` | 结构化字段命中数 |
| `ok` | 该轮是否完全正确 |

解读注意事项：

- `input_tokens` 是模型服务记账口径，不等同于 Agent 间显式文本通信。
- D 模式继承 KV handle 后，decode 可能按较长 `seq_len` 记账，因此 `input_tokens` 可能不降反升。
- 判断通信收益时优先看 `message_count`、`text_comm_chars`、`text_comm_tokens_est`。
- 判断真实任务收益时必须同时看 `wall_time_s` 和质量指标，不能只看通信减少。
- D 模式引入 KV bytes，显式文本减少不代表总资源占用一定减少。

## 8. 清理与排障

### 8.1 清理 server-side handles

查看 handles：

```bash
docker exec SynapseX-wmw71 curl -s http://localhost:8101/handles
```

删除单个 handle：

```bash
docker exec SynapseX-wmw71 curl -s -X DELETE http://localhost:8101/handle/HANDLE_ID
```

如果需要清空残留，最简单方式是重启服务：

```bash
bash run_latent_kv_server.sh --stop
bash run_latent_kv_server.sh
```

### 8.2 常见问题

| 现象 | 可能原因 | 处理 |
|---|---|---|
| runner 自动退回 sim backend | server `/health` 不可达 | 检查端口、容器和 `LATENT_KV_SERVER_PORT` |
| GPU 显存持续上涨 | handle 没有及时删除 | 查看 `/handles`，重启 server 或删除 handle |
| B/D 不公平 | B 没有走同一个 server endpoint | 确认 `CHAT_BASE_URL=http://localhost:${LATENT_KV_SERVER_PORT}/v1` |
| D 输出 JSON 不可解析 | final contract 约束弱或 latent drift | 加强 final schema prompt，检查 summary cleanup |
| D 耗时更慢 | latent steps 过多或 KV 太大 | 降低 `ANALYST_LATENT_STEPS` / `EXECUTOR_LATENT_STEPS` |
| `input_tokens` 增加 | inherited KV seq_len 被 usage 记账 | 同时报告显式通信字符和 KV 指标 |

## 9. 推荐报告口径

写实验结论时建议同时报告：

```text
平均耗时
Agent消息/轮
文本字符/轮
LLM usage token in/out
Latent steps/轮
KV MB/轮
字段命中或任务正确率
```

推荐表述：

- “D 模式减少显式 Agent 文本通信。”
- “D 模式引入 server-side KV 状态传递，显式文本少了，但非文本 KV 资源增加。”
- “LLM 记账 token 与 Agent 间文本通信不是同一口径。”
- “最终质量仍需用 exact match / route correctness / field accuracy 验证。”

不推荐表述：

- “D 完全没有文本传递。”
- “D 的 token 一定更少。”
- “D 只要更快就说明质量更好。”
- “KV handle 是可持久化记忆。”

## 10. 快速检查清单

运行前：

- `docker ps` 能看到 `SynapseX-wmw71`。
- `curl http://localhost:8101/health` 返回 `status=ok`。
- `PYTHONPATH` 包含 `$PWD/src`。
- `CHAT_MODEL=/data/models/Qwen3-8B`。
- `LATENT_KV_BACKEND=real`。
- B/D 使用同一个 `LATENT_KV_SERVER_PORT`。
- 设置合适的 latent steps。

运行后：

- 检查 `RUN_MANIFEST.json`。
- 检查 `REPORT.md`。
- 检查 `mode_D_all_rounds.json` 是否有 `latent_steps > 0`。
- 检查是否误用 sim backend。
- 清理 server-side handles 或重启 server。

