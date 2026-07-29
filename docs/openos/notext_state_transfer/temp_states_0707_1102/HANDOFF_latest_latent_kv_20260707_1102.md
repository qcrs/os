# Latent KV / D 模式当前状态交接

生成时间：2026-07-07 11:03 CST

工作目录：

```text
/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz
```

本交接文档用于另开窗口继续执行，覆盖当前最新实现、实验结果、Docker/GPU 环境、已知问题和建议下一步。

## 1. 当前结论先读

1. D/latent_kv 的 KV 状态传递、latent step 计量、速度统计链路已经跑通。
2. 最终答案链路还没有稳定打通：很多 D 结果是 `final_answer=""`、固定占位，或 `generated_text=""`。
3. 目前最值得保留的十轮正向样例是交易事故响应实验：D 相比 B 快 9.24%，字段命中 D=40/60，B=2/60，但 D 仍然 0/10 全字段完全正确。
4. KV reuse audit 十轮实验 D 快 10.55%，但质量 1/50，且 49/50 输出为空，是失败样例。
5. 7city 十轮实验没有达到 D vs B 加速超过 7%，且质量低；4city 只有 A 模式 6 轮，没有 B/D 对照，不能比较。
6. 当前没有检测到我遗留的 `latent_kv_model_server.py` 或实验 runner 进程。

## 2. 当前 Docker / GPU 环境

主要容器：

```text
SynapseX-wmw71 Up 6 days synapsex-wmw71-openeuler-vllm:20260701
```

当前在 `SynapseX-wmw71` 容器内查到的 GPU 状态：

```text
DATE=2026-07-07 11:03:39 CST
GPU 0, NVIDIA A100 80GB PCIe, total 81920 MB, used 75314 MB, free 5843 MB, util 75%
GPU 1, NVIDIA A100 80GB PCIe, total 81920 MB, used 23980 MB, free 57177 MB, util 100%
GPU 2, NVIDIA A100 80GB PCIe, total 81920 MB, used 439 MB, free 80718 MB, util 0%
```

进程检查：

```text
docker exec SynapseX-wmw71 bash -lc 'ps -eo pid,ppid,stat,etime,cmd | grep -E "latent_kv_model_server|run_kv_reuse_audit|run_7city|run_arch|run_incident|python" | grep -v grep || true'
```

输出为空，表示当前没有匹配到我启动的 latent server 或实验进程。

重要说明：

- `SynapseX-wmw71` 容器内可以看到 GPU 0/1/2。
- 如果用 `CUDA_VISIBLE_DEVICES=1` 启动服务，则 PyTorch 内部的 `cuda:0` 对应被 mask 后的物理 GPU1。
- 之前多次实验使用方式是：宿主/容器设置 `CUDA_VISIBLE_DEVICES=1`，同时服务端设置 `LATENT_KV_SERVER_GPU=0`。
- 早期 7city 当前设计实验目录名含 `gpu2`：`7city_abd_results_current_design_gpu2_10round_20260705_2303`。
- 最近关键十轮 KV reuse audit 是 GPU1 / port 8102；跑完后已停 server。

常用启动命令模板：

```bash
docker exec -it SynapseX-wmw71 bash
cd /data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz
export PYTHONPATH=$PWD/src:$PYTHONPATH
export CUDA_VISIBLE_DEVICES=1
export LATENT_KV_SERVER_GPU=0
export LATENT_KV_SERVER_PORT=8102
export VLLM_MODEL_PATH=/data/models/Qwen3-8B
python3 src/latent_kv_model_server.py
```

释放/检查资源：

```bash
ps -eo pid,ppid,stat,etime,cmd | grep -E 'latent_kv_model_server|run_kv_reuse_audit|run_7city|run_incident' | grep -v grep || true
nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits
```

## 3. 当前实现情况

### 3.1 配置

文件：

```text
src/config.py
```

新增/当前重要环境变量：

```python
COMM_MODE = os.getenv("COMM_MODE", "structured")
RESEARCHER_FANOUT = max(1, int(os.getenv("RESEARCHER_FANOUT", "3")))
PLANNER_LATENT_STEPS = int(os.getenv("PLANNER_LATENT_STEPS", "16"))
RESEARCHER_LATENT_STEPS = int(os.getenv("RESEARCHER_LATENT_STEPS", "32"))
ANALYST_LATENT_STEPS = int(os.getenv("ANALYST_LATENT_STEPS", "64"))
EXECUTOR_LATENT_STEPS = int(os.getenv("EXECUTOR_LATENT_STEPS", "32"))
POST_EXEC_LATENT_STEPS = int(os.getenv("POST_EXEC_LATENT_STEPS", "16"))
SUMMARIZER_LATENT_STEPS = int(os.getenv("SUMMARIZER_LATENT_STEPS", "8"))
LATENT_ALIGNMENT = os.getenv("LATENT_ALIGNMENT", "normalized_identity")
LATENT_KV_DOCKER_CONTAINER = os.getenv("LATENT_KV_DOCKER_CONTAINER", "SynapseX-wmw71")
LATENT_KV_USE_DOCKER = os.getenv("LATENT_KV_USE_DOCKER", "1").lower() in {"1", "true", "yes"}
```

### 3.2 Researcher fanout

文件：

```text
src/agent/shared.py
src/agent/planner.py
src/graph.py
```

当前实现：

- `RESEARCHER_FANOUT` 默认 3。
- `_researcher_fanout()` 读取环境变量，范围限制为 1 到 16。
- `_normalize_sub_queries()` 按 fanout 数量补齐/裁剪 sub-queries。
- planner prompt 要求生成 exactly `fanout` 个 sub-query。
- A/B/D 的 LangGraph fanout 都走 `_normalize_sub_queries()`，所以可以保持相同 researcher 数量。

已验证过：

- `RESEARCHER_FANOUT=2` 时 A/B fanout 和 D fanout 都返回 2。
- `RESEARCHER_FANOUT=3` 时 A/B fanout 和 D fanout 都返回 3。

注意：

- `kv_reuse_audit_suite` 不走 LangGraph researcher fanout；它每个 case 固定 5 个 reviewer 问题，因此 `RESEARCHER_FANOUT=3` 对它无效。

### 3.3 D/latent_kv 图

文件：

```text
src/graph.py
src/agent/latent_kv_agents.py
```

当前 D 图大致为：

```text
planner_explicit_for_latent
  -> researcher_explicit_for_latent fanout
  -> analyst_latent
  -> executor_latent
  -> summarizer_latent
```

当前含义：

- planner/researcher 阶段目前是显式结构化输出，不是全程 latent。
- latent KV 主要从 analyst 开始。
- analyst/executor/summarizer 之间传 `latent_kv_handle_id`。
- analyst 不输出长文本，写入 KV state。
- executor 继承 analyst KV，生成代码、执行、注入 result，再运行 post-exec latent steps。
- summarizer 从 inherited KV state decode 最终 summary。

关键问题：

- `executor_latent()` 里的 `final_answer` 是占位逻辑：

```python
final_answer = ""
extracted_answers = {}
answer_pattern = r"@(\w+)\[([^\]]+)\]"
matches = re.findall(answer_pattern, query)
if matches:
    for field, _ in matches:
        extracted_answers[field] = "latent_kv_answer"
    final_answer = " ".join(f"@{k}[{v}]" for k, v in extracted_answers.items())
```

- `summarizer_latent()` 调用 `runtime.generate_summary(...)` 得到 `summary`，但 `final_answer` 仍直接取 executor 的 `state.get("final_answer", "")`。
- 因此很多 D 结果表现为：`summary` 有内容，但 `final_answer` 为空或占位。

### 3.4 Latent KV runtime / model server

文件：

```text
src/latent_kv_runtime.py
src/latent_kv_model_server.py
```

FastAPI server endpoint：

```text
GET    /health
POST   /prefill
POST   /latent_steps
POST   /inject_tokens
POST   /decode
GET    /handle/{handle_id}
DELETE /handle/{handle_id}
GET    /handles
POST   /v1/chat/completions
GET    /v1/models
```

实现特点：

- `/prefill`：把文本 prefill 成 server-side KV handle。
- `/latent_steps`：用 `last_hidden -> normalized_identity aligner -> inputs_embeds` 做 latent forward。
- `/inject_tokens`：把角色切换、执行结果等显式文本追加进 KV chain。
- `/decode`：从 KV handle + continuation prompt 解码。
- `/v1/chat/completions`：给 A/B 作为 OpenAI-compatible 本地模型接口，保证同一模型后端。

当前 latent aligner：

```text
normalized_identity
```

它不是训练过的 latent aligner。`kv_reuse_audit_suite/README.md` 已写明：当前 aligner 未训练，额外 latent reasoning steps 会伤害 answer stability。

decode 空字符串问题：

- `_decode_clean()` 会去掉 `<think>...</think>`、未闭合 `<think>` 后的内容、以及特殊 token。
- 如果模型生成 token 主要是 thinking block 或特殊 token，清洗后 `generated_text` 会变成空字符串。
- `kv_reuse_audit` 的 D 就出现了大量这种情况：有 completion tokens，但 `output/generated_text` 是 `""`。

## 4. 最新/重要实验结果

### 4.1 7city A/B/D/D56 十轮实验

结果目录：

```text
exp/latent_kv_exp/7city_abd_3researcher_gpu1_10round_20260706_113117
```

汇总文档：

```text
docs/openos/notext_state_transfer/kv_latent/exp/7city_abd_d120_d56_10round_20260706.md
```

设置：

- 任务：`task/lantent/7city.json`
- 3 researcher fanout。
- A/B/D 均 10 轮。
- D120：analyst=64, executor=32, post_exec=16, summarizer=8，总计 120。
- D56：analyst=32, executor=16, post_exec=8, summarizer=0，总计 56。
- 在 GPU1 上跑过。

结果：

| 模式 | 轮数 | 平均耗时(s) | LLM调用 | Token in | Token out | Latent步数 | KV传输(KB) | 路线正确率 | 成本正确率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_text | 10 | 138.2 | 6 | 7162 | 3072 | 0 | 0 | 0/10 | 1/10 |
| B_structured | 10 | 137.4 | 6 | 7116 | 3072 | 0 | 0 | 0/10 | 1/10 |
| D_latent_kv_120 | 10 | 133.5 | 6 | 9516 | 2816 | 120 | 1825834 | 1/10 | 2/10 |
| D_latent_kv_56 | 10 | 131.2 | 6 | 9437 | 2816 | 56 | 1327205 | 1/10 | 1/10 |

结论：

- D56 最快，但相对 B 只快约 4.5%，未达到 7%。
- 整体质量低，不能作为质量有效结论。
- D 的 `final_answer` 多数/全部为空，结果主要从 `summary` 正则提取。

### 4.2 KV reuse audit A/B/D 十轮实验

结果目录：

```text
exp/latent_kv_exp/kv_reuse_audit_suite/results_abd10_gpu1_20260706_160835
```

人工复核文档：

```text
docs/openos/notext_state_transfer/kv_latent/exp/kv_reuse_audit_abd10_manual_eval_20260706.md
```

任务文件：

```text
task/lantent/kv_reuse_audit_10round/kv_reuse_audit_tasks.json
```

设置：

- 容器：`SynapseX-wmw71`
- GPU：GPU1，服务端端口 8102。
- D latent steps：0。
- 每 case 5 个 reviewer 问题，10 cases，共 50 个问题。
- A/B 重复 prefill 完整状态；D prefill 一次，复用 KV handle 给 reviewer decode。

运行命令形态：

```bash
python3 -u exp/latent_kv_exp/kv_reuse_audit_suite/run_kv_reuse_audit.py \
  --modes A B D \
  --rounds 10 \
  --noise-lines 96 \
  --max-new-tokens 64 \
  --d-latent-steps 0 \
  --task-file task/lantent/kv_reuse_audit_10round/kv_reuse_audit_tasks.json \
  --server-base http://localhost:8102 \
  --output-dir exp/latent_kv_exp/kv_reuse_audit_suite/results_abd10_gpu1_20260706_160835 \
  --min-speedup-pct -999 \
  --min-quality 0
```

结果：

| 模式 | Cases | 平均 case 耗时(s) | 总耗时(s) | 正确数 | 输出为空 |
|---|---:|---:|---:|---:|---:|
| A_text | 10 | 22.143 | 221.426 | 0/50 | 0/50 |
| B_structured | 10 | 22.171 | 221.706 | 0/50 | 0/50 |
| D_latent_kv_reuse | 10 | 19.831 | 198.312 | 1/50 | 49/50 |

D vs B：

```text
(22.171 - 19.831) / 22.171 = 10.55%
```

结论：

- 速度上 D 快 10.55%。
- 质量不合格，D 只有 1/50 正确。
- 49/50 的 D reviewer output 是空字符串。
- 唯一正确：`C03-Q5`，输出 `{"answer":"Q-03-ESC-57","cite":"C03-E015"}`。
- 这是 KV reuse 速度路径参考，不是质量有效结果。

### 4.3 交易系统连续事故响应十轮实验

结果目录：

```text
exp/latent_kv_exp/incident_response_abd_20260705_164545-3.4%
```

任务文件：

```text
task/lantent/incident_response_10round/incident_response_tasks.json
```

Suite：

```text
trading_incident_response_latentmas_10round_v1
```

任务说明：

- 平台：SkyBridge 实时交易与清结算平台。
- 每轮 researcher 长证据、analyst 长因果分析、executor 计算和处置矩阵、summarizer 输出短 JSON。
- 质量字段：`root_cause_service`、`root_cause_code`、`severity`、`primary_action`、`report_deadline_minutes`、`estimated_loss_usd`。
- 当前 D 限制：`researcher is text; latent starts at analyst`。

结果：

| 模式 | 轮数 | 平均耗时(s) | Token in/轮 | Token out/轮 | Latent steps/轮 | KV MB/轮 | 字段命中 | 全字段正确 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A_text | 10 | 285.353 | 10039.1 | 3060.8 | 0 | 0 | 1/60 | 0/10 |
| B_structured | 10 | 303.588 | 10543.5 | 3052.1 | 0 | 0 | 2/60 | 0/10 |
| D_latent_kv | 10 | 275.548 | 9842.5 | 2803.7 | 112 | 763.7 | 40/60 | 0/10 |

D vs B：

```text
(303.588 - 275.548) / 303.588 = 9.24%
```

结论：

- 当前最值得保留的十轮 D 结果。
- 速度和字段命中都优于 B。
- 但严格全字段完全正确仍是 0/10，不能说完全解决质量。

### 4.4 Incident response 3 轮 latent56 GPU1 实验

结果目录：

```text
exp/latent_kv_exp/incident_response_abd_latent56_gpu1_3round_20260706_151234
```

结果摘要：

- A/B/D 各 3 轮。
- D latent steps=56。
- B 平均约 137.497s。
- D 平均约 138.223s。
- D 相对 B 略慢约 0.53%。
- D 字段命中合计 8/18，3 条 D 记录都有非空 answer，但质量仍不稳定。

### 4.5 LongText / Skyforge Courier 早期 ABCD 实验

任务文件：

```text
task/longtext/skyforge_cache_tasks.json
```

结果目录：

```text
exp/kv_cache_exp/longtext_10round_abcd_stats_20260704_123455
exp/kv_cache_exp/longtext_10round_abcd_stats_20260704_130605
```

20260704_123455：

| 模式 | 轮数 | LLM 调用 | 平均耗时(s) | Output tokens | Latent steps |
|---|---:|---:|---:|---:|---:|
| B_structured | 10 | 60 | 70.269 | 14143 | 0 |
| D_latent_kv | 10 | 0 | 18.774 | 0 | 0 |

问题：

- D 是占位/无真实 LLM 调用。
- `final_answer` 固定为 `@round[latent_kv_answer] ...`。
- 表观加速 73.28%，不能作为有效质量结果。

20260704_130605：

| 模式 | 轮数 | LLM 调用 | 平均耗时(s) | Output tokens | Latent steps |
|---|---:|---:|---:|---:|---:|
| B_structured | 10 | 60 | 70.269 | 14143 | 0 |
| D_latent_kv | 10 | 10 | 20.626 | 13875 | 1120 total |

问题：

- 有真实 latent 统计和 decode token。
- 但逐轮 `final_answer` 仍是固定占位。
- 表观加速 70.65%，只能作为通信/计量路径参考，不能作为质量有效结果。

### 4.6 7city / 4city 状态

7city 十轮扫描结果：

| 实验 | B 平均耗时(s) | D 平均耗时(s) | D vs B | 质量备注 |
|---|---:|---:|---:|---|
| `7city_abd_3researcher_gpu1_10round_20260706_113117` | 137.410 | 133.505 | 2.84% | A/B 路线 0/10，D 路线 1/10；D `final_answer` 10/10 为空 |
| `7city_abd_results` | 110.781 | 104.449 | 5.72% | D 路线 0/10、成本 0/10；D `final_answer` 10/10 为空 |
| `7city_abd_results_current_design_gpu2_10round_20260705_2303` | 96.530 | 93.864 | 2.76% | D 路线 0/10、成本 1/10；D `final_answer` 10/10 为空 |
| `7city_abd_results_latent56_gpu1_10round_20260706_003308` | 97.259 | 92.259 | 5.14% | D 路线 0/10、成本 1/10；D `final_answer` 10/10 为空 |

结论：

- 7city 没有 D vs B 超过 7% 的十轮结果。
- 质量整体不合格或不稳定。

4city：

```text
exp/latent_kv_exp/4city_abd_results
```

状态：

- 只有 `A_text` 6 轮结果。
- 没有 `B_structured` / `D_latent_kv` / `all_results.json`。
- 不能比较 D vs B。
- 已有 A 结果路线和成本均未通过解析校验。

## 5. 新增/更新的文档

实验汇总：

```text
docs/openos/notext_state_transfer/kv_latent/exp/7city_abd_d120_d56_10round_20260706.md
docs/openos/notext_state_transfer/kv_latent/exp/kv_reuse_audit_abd10_manual_eval_20260706.md
docs/openos/notext_state_transfer/kv_latent/exp/d_vs_b_speedup_over7_10round_20260706.md
```

D 设计文档：

```text
docs/openos/notext_state_transfer/kv_latent/D_latent_kv_design.md
docs/openos/notext_state_transfer/kv_latent/D_latent_kv_design_v1.md
```

本次交接文档：

```text
docs/openos/notext_state_transfer/temp_states_0707_1102/HANDOFF_latest_latent_kv_20260707_1102.md
```

## 6. 当前 git 状态提醒

工作树是 dirty 的，包含很多未跟踪实验结果和文档。不要随手 reset。

当前 `git status --short` 关键项：

```text
 M src/agent/analyst.py
 M src/agent/executor.py
 M src/agent/planner.py
 M src/agent/shared.py
 M src/agent/summarizer.py
 M src/config.py
 M src/graph.py
 M src/metrics.py
?? docs/openos/notext_state_transfer/kv_latent/
?? docs/openos/notext_state_transfer/temp_states_0705_*/
?? docs/openos/notext_state_transfer/temp_states_0707_1102/
?? exp/latent_kv_exp/
?? exp/kv_cache_exp/longtext_*/
?? src/agent/latent_kv_agents.py
?? src/latent_kv_model_server.py
?? src/latent_kv_runtime.py
?? task/lantent/
```

说明：

- 不要 revert 用户或历史实验文件。
- 如果继续改实现，先读对应文件，避免覆盖已有实验/文档。

## 7. 已知核心问题

### 7.1 D 最终答案 contract 没闭环

当前 D 的 `summary`、`final_answer`、`answer`、`output/generated_text` 字段不统一：

- 7city：`summary` 有内容，`final_answer` 为空。
- longtext：`final_answer` 是 `latent_kv_answer` 占位。
- kv_reuse：`generated_text` 多数为空。
- incident response：部分实验 `answer` 可解析，但仍不稳定。

需要修：

1. summarizer 的 decode 必须按任务 contract 输出统一 JSON。
2. 解析后必须回填 `final_answer` / `answer` / `output` 中 runner 使用的字段。
3. 如果 decode 为空，需要 raw output fallback 或 retry。
4. 保存 `raw_generated_text`，不要只保存清洗后的文本。

### 7.2 `_decode_clean()` 导致空字符串

服务端清洗逻辑会删除 `<think>` 和 special token：

```text
src/latent_kv_model_server.py::_decode_clean
```

如果模型只生成 thinking block 或特殊 token，最终 `generated_text=""`。

建议：

- 在 `/decode` response 中增加 `raw_generated_text`。
- 当 `generated_text==""` 但 `tokens_generated>0` 时不要直接判空，触发二次 decode。
- 对 JSON contract 任务，prompt 中强制 no-thinking / JSON-only，并提高 `max_new_tokens`。

### 7.3 latent aligner 未训练

当前 `normalized_identity` 只是启发式，不是训练过的 latent aligner。

影响：

- latent_steps 越多不一定质量越好。
- 在 KV reuse audit 这种抽取式任务中，推荐先用 `d_latent_steps=0` 验证 KV reuse 基本链路。
- 56 steps 比 120 steps 只小幅加速，端到端耗时主要还受 decode、固定流程、server/GPU 负载影响。

### 7.4 研究者数量和任务 fanout

LangGraph A/B/D 中 `RESEARCHER_FANOUT=3` 能统一 researcher 数量。

但 `kv_reuse_audit_suite` 的 5 reviewer 是任务本身设计，不受 `RESEARCHER_FANOUT` 控制。不要把它误认为 5 researcher。

## 8. 建议下一步

优先级最高：

1. 修 D 输出 contract：
   - `summarizer_latent` 从 `summary` 中解析 JSON 或结构化答案；
   - 回填 `final_answer` 和 `answer`；
   - runner 只评价统一字段；
   - 保存 raw/clean 两份 decode。

2. 修 `/decode` 空输出：
   - response 增加 raw text；
   - 空 clean text 时 retry；
   - 对 JSON 任务使用更强 JSON-only prompt。

3. 做一个小任务验证：
   - 先用 4city 完整跑 A/B/D 三轮或六轮；
   - 目标不是速度，而是确认 D 的最终输出字段不再空。

4. 再重跑正式任务：
   - 先跑 incident_response 3 轮；
   - 再跑 incident_response 10 轮；
   - 最后再考虑 kv_reuse_audit 10 轮。

不要优先做：

- 不要再用 longtext 早期占位结果证明质量。
- 不要只调 latent_steps 期待质量变好。
- 不要把 7city 当前结果当成有效质量样例。

## 9. 快速接手命令

进入容器：

```bash
docker exec -it SynapseX-wmw71 bash
cd /data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz
export PYTHONPATH=$PWD/src:$PYTHONPATH
```

检查 GPU：

```bash
nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits
```

启动 latent KV server 示例：

```bash
export CUDA_VISIBLE_DEVICES=1
export LATENT_KV_SERVER_GPU=0
export LATENT_KV_SERVER_PORT=8102
export VLLM_MODEL_PATH=/data/models/Qwen3-8B
python3 src/latent_kv_model_server.py
```

跑 KV reuse audit 示例：

```bash
python3 -u exp/latent_kv_exp/kv_reuse_audit_suite/run_kv_reuse_audit.py \
  --modes A B D \
  --rounds 10 \
  --noise-lines 96 \
  --max-new-tokens 64 \
  --d-latent-steps 0 \
  --task-file task/lantent/kv_reuse_audit_10round/kv_reuse_audit_tasks.json \
  --server-base http://localhost:8102 \
  --output-dir exp/latent_kv_exp/kv_reuse_audit_suite/results_abd10_gpuX_YYYYMMDD_HHMMSS \
  --min-speedup-pct -999 \
  --min-quality 0
```

停止 server：

```bash
ps -eo pid,ppid,stat,etime,cmd | grep latent_kv_model_server | grep -v grep
kill <pid>
```

确认释放：

```bash
curl -s http://localhost:8102/health || true
nvidia-smi
```
