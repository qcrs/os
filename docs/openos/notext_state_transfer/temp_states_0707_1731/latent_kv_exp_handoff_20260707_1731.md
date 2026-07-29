# 2026-07-07 17:31 Latent KV 实验交接状态

本文档用于另开窗口继续当前工作。工作目录：

```text
/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz
```

## 1. 当前用户目标

近期目标是围绕 B_structured 与 D_latent_kv 的多智能体实验，验证 latent KV / 多智能体链路相对 B 或单模型 baseline 的收益。

已经完成的用户请求包括：

- 在 `SynapseX-wmw71` 容器、物理 GPU2 上跑 `task/lantent/4city.json` 的 B/D 四城市任务。
- 将四城市任务和 `d_vs_b_speedup_over7_10round_20260706.md` 中“交易系统连续事故响应十轮实验”统计到 PPT 材料。
- 用 Qwen3-8B 单模型、非多智能体方式分别跑交易系统和四城市各 10 轮，统计到 `qwen3-8b-only.md`。
- 回答“单模型 2.8 秒/轮是否统计有问题”：结论是 baseline 只做单次 direct JSON decode，负载远小于多智能体，快是预期现象，但不能直接和多智能体端到端耗时等价比较。
- 回答“B 模式效果差的原因”：结论是 B 的 0/10 不是统计误判，而是当前 B 链路没有把 JSON/计算任务合同贯穿到 analyst/executor/summarizer，不能把差距纯归因于状态传递方式。

## 2. 实验环境

宿主机路径：

```text
/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz
```

容器：

```text
SynapseX-wmw71
image: synapsex-wmw71-openeuler-vllm:20260701
status at 2026-07-07 17:31 CST: Up 6 days
```

容器内工作目录：

```text
/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz
```

GPU 状态快照，2026-07-07 17:31 CST：

```text
GPU0: NVIDIA A100 80GB PCIe, used 64390 MB, free 16767 MB, util 0%
GPU1: NVIDIA A100 80GB PCIe, used   439 MB, free 80718 MB, util 0%
GPU2: NVIDIA A100 80GB PCIe, used 23936 MB, free 57221 MB, util 97%
```

用下面命令查过相关进程：

```bash
docker exec SynapseX-wmw71 bash -lc 'ps -eo pid,ppid,stat,etime,cmd | grep -E "latent_kv_model_server|run_4city_bd_latest_stats|run_qwen3_8b_only_baseline|run_incident_response_abd|python" | grep -v grep || true'
```

快照结果：没有匹配到上述实验脚本或 `latent_kv_model_server` 进程。GPU2 仍有利用率和显存占用，可能是其他进程或未被上述 grep 覆盖的进程；另开窗口继续前应重新查完整 `nvidia-smi` / `ps`。

模型与服务口径：

- 模型：`/data/models/Qwen3-8B`
- OpenAI-compatible chat endpoint：`http://localhost:8101/v1/chat/completions`
- 四城市 B/D 使用 `latent_kv_model_server`，port `8101`
- 四城市 D latent 配置：`ANALYST_LATENT_STEPS=64`、`EXECUTOR_LATENT_STEPS=32`、`POST_EXEC_LATENT_STEPS=16`、`SUMMARIZER_LATENT_STEPS=0`，每轮 112 latent steps。

## 3. 主要结果文件

四城市 B/D 最新有效结果：

```text
exp/latent_kv_exp/4city_bd_latest_stats_gpu2_20260707_122042
exp/latent_kv_exp/4city_bd_latest_stats_gpu2_20260707_122042/4city_BD_latest_stats_report.md
exp/latent_kv_exp/4city_bd_latest_stats_gpu2_20260707_122042/all_results.json
exp/latent_kv_exp/4city_bd_latest_stats_gpu2_20260707_122042/mode_B_all_rounds.json
exp/latent_kv_exp/4city_bd_latest_stats_gpu2_20260707_122042/mode_D_all_rounds.json
```

四城市任务文件：

```text
task/lantent/4city.json
```

交易系统 B/D 十轮结果来源：

```text
exp/latent_kv_exp/incident_response_abd_20260705_164545-3.4%
task/lantent/incident_response_10round/incident_response_tasks.json
docs/openos/notext_state_transfer/kv_latent/exp/d_vs_b_speedup_over7_10round_20260706.md
```

PPT 汇总文档：

```text
docs/openos/notext_state_transfer/kv_latent/exp/ppt_doc_2kv_latent_exp.md
```

Qwen3-8B 单模型 baseline 文档：

```text
docs/openos/notext_state_transfer/kv_latent/exp/qwen3-8b-only.md
```

Qwen3-8B 单模型 baseline 结果目录：

```text
exp/latent_kv_exp/qwen3_8b_only_gpu2_20260707_162105
exp/latent_kv_exp/qwen3_8b_only_gpu2_20260707_162105/all_results.json
```

相关脚本：

```text
exp/latent_kv_exp/run_4city_bd_latest_stats.py
exp/latent_kv_exp/run_qwen3_8b_only_baseline.py
exp/latent_kv_exp/run_incident_response_abd.py
```

## 4. 四城市 B/D 实验摘要

实验目录：

```text
exp/latent_kv_exp/4city_bd_latest_stats_gpu2_20260707_122042
```

汇总数据：

| 模式 | 轮数 | 平均耗时(s) | Agent消息/轮 | LLM调用/轮 | Token in/轮 | Token out/轮 | 文本字符/轮 | 非文本传递/轮 | Latent steps/轮 | KV传输/轮(KB) | 路线正确 | 成本正确 | 完全正确 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B_structured | 10 | 115.153 | 7.0 | 6.0 | 5674.4 | 3072.0 | 9127.5 | 3.0 | 0 | 0 | 0/10 | 0/10 | 0/10 |
| D_latent_kv | 10 | 109.779 | 4.0 | 6.0 | 8340.3 | 2816.0 | 6035.8 | 3.0 | 112 | 1210622 | 7/10 | 5/10 | 3/10 |

D 相对 B 加速：

```text
(115.153 - 109.779) / 115.153 = 4.67%
```

重要统计口径：

- `raw_route` / `raw_total_cost` 才是从模型输出解析出的原始答案。
- `route` / `total_cost` 在 raw 不可解析时会用 reference fallback 补全，只用于报告展示。
- 正确率只基于 raw parsed answer，不把 reference fallback 算正确。

B 的关键现象：

- B 10 轮全部 `raw_route: []`、`raw_total_cost: 0`。
- B 每轮 `answer_source` 都是 `reference_fallback_for_reporting`。
- B 原始输出类似：

```json
{"route":["A","..."],"total_cost":"<integer>","verification":"<short string>"}
```

因此 B 的 0/10 不是统计脚本误判，而是模型链路没有产出可解析 route/cost。

D 的关键现象：

- D 10 轮都至少能解析出 raw route。
- D 完全正确 3/10，路线正确 7/10，成本正确 5/10。
- D 输出经常包含重复 JSON、markdown fence 或自相矛盾的 verification；不能视为严格稳定。

## 5. 交易系统连续事故响应实验摘要

结果目录：

```text
exp/latent_kv_exp/incident_response_abd_20260705_164545-3.4%
```

任务文件：

```text
task/lantent/incident_response_10round/incident_response_tasks.json
```

字段：

```text
root_cause_service
root_cause_code
severity
primary_action
report_deadline_minutes
estimated_loss_usd
```

汇总数据：

| 模式 | 轮数 | 平均耗时(s) | 总耗时(s) | LLM调用/轮 | Token in/轮 | Token out/轮 | Latent steps/轮 | KV MB/轮 | 字段命中 | 全字段正确 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_text | 10 | 285.353 | 2853.534 | 6.0 | 10039.1 | 3060.8 | 0 | 0 | 1/60 | 0/10 |
| B_structured | 10 | 303.588 | 3035.877 | 6.0 | 10543.5 | 3052.1 | 0 | 0 | 2/60 | 0/10 |
| D_latent_kv | 10 | 275.548 | 2755.475 | 6.0 | 9842.5 | 2803.7 | 112 | 763.7 | 40/60 | 0/10 |

D 相对 B 加速：

```text
(303.588 - 275.548) / 303.588 = 9.24%
```

结论口径：

- 这是当前速度和字段命中同时优于 B 的十轮 D 结果。
- 但严格全字段正确仍为 0/10，不能宣传为任务完全通过。
- 原始说明里有关键限制：`researcher is text; latent starts at analyst`。

## 6. Qwen3-8B 单模型 baseline 摘要

文档：

```text
docs/openos/notext_state_transfer/kv_latent/exp/qwen3-8b-only.md
```

结果目录：

```text
exp/latent_kv_exp/qwen3_8b_only_gpu2_20260707_162105
```

运行口径：

- 单模型、单 prompt、单次 decode / round。
- 不构建 LangGraph。
- 不使用 planner/researcher/analyst/executor/summarizer 多智能体链路。
- 只使用上一轮单模型可解析输出作为 history，不使用 reference answer。
- 直接要求输出最终 JSON，因此负载远小于多智能体。

汇总结果：

| 任务 | 轮数 | 平均耗时(s) | 总耗时(s) | Token in/轮 | Token out/轮 | 正确性 |
|---|---:|---:|---:|---:|---:|---|
| 交易系统连续事故响应 | 10 | 2.8 | 28.2 | 1351 | 55 | 字段命中 39/60；全字段 0/10 |
| 四城市巡检路线 | 10 | 1.6 | 15.5 | 562 | 33 | 路线 5/10；成本 3/10；完全 1/10 |

和多智能体对比：

| 任务 | 方法 | 平均耗时(s) | Token in/轮 | Token out/轮 | 质量 |
|---|---|---:|---:|---:|---|
| 交易系统连续事故响应 | Qwen3-8B 单模型 | 2.8 | 1351 | 55 | 字段 39/60；全字段 0/10 |
| 交易系统连续事故响应 | B_structured 多智能体 | 303.588 | 10543.5 | 3052.1 | 字段 2/60；全字段 0/10 |
| 交易系统连续事故响应 | D_latent_kv 多智能体 | 275.548 | 9842.5 | 2803.7 | 字段 40/60；全字段 0/10 |
| 四城市巡检路线 | Qwen3-8B 单模型 | 1.6 | 562 | 33 | 路线 5/10；成本 3/10；完全 1/10 |
| 四城市巡检路线 | B_structured 多智能体 | 115.153 | 5674.4 | 3072.0 | 路线 0/10；成本 0/10；完全 0/10 |
| 四城市巡检路线 | D_latent_kv 多智能体 | 109.779 | 8340.3 | 2816.0 | 路线 7/10；成本 5/10；完全 3/10 |

解释：

- baseline 单轮 2-3 秒不是统计错误。
- 它每轮只有一次 Qwen3-8B 调用，输出几十个 token；多智能体每轮约 6 次 LLM 调用，并生成 researcher/analyst/executor/summarizer 中间内容。
- baseline 适合检验“多智能体是否带来质量收益”，不适合作为同等生成负载的端到端速度对照。

## 7. 当前实现状态

核心新增/修改点：

```text
src/agent/shared.py
src/agent/analyst.py
src/agent/executor.py
src/agent/summarizer.py
src/agent/planner.py
src/agent/latent_kv_agents.py
src/latent_kv_runtime.py
src/latent_kv_model_server.py
src/graph.py
src/config.py
src/metrics.py
exp/latent_kv_exp/run_4city_bd_latest_stats.py
exp/latent_kv_exp/run_qwen3_8b_only_baseline.py
```

已知实现要点：

- `src/agent/shared.py` 里有 JSON final contract 提取与清洗工具，如 `_extract_json_final_contract_fields()`、`_clean_json_contract_answer()`。
- `src/agent/planner.py` 之前补过 `import json`，避免 JSON 解析相关路径报错。
- `src/agent/executor.py` 已有 JSON contract final answer 构造逻辑，但它只能从 `candidate_answers`、`analysis`、`execution_result` 里抽字段。
- `src/agent/executor.py` 的 CodeAct 仍是通用 evidence/packet metrics，不会真正解析四城市距离矩阵、枚举路线，也不会真正计算交易事故字段。
- `src/agent/summarizer.py` 已识别 JSON contract，但上游没有有效值时可能输出模板占位 JSON。
- `src/agent/researcher.py` 仍是通用 source-material generator，prompt 是生成 3-5 段材料，不是任务求解器。
- `src/agent/latent_kv_agents.py` 的 D 路径是 explicit planner/researcher + latent analyst/executor/summarizer 的混合链路；不是全程纯 latent。
- `src/latent_kv_model_server.py` 之前改过：
  - 支持 `CHAT_DISABLE_THINKING=1` 的 chat template 路径。
  - DELETE `/handle/{id}` 时做 `gc.collect()` 和 `torch.cuda.empty_cache()`，避免 KV handle 删除后显存不释放。

当前 `git status --short` 快照里有大量已有改动/未跟踪文件，继续工作时不要随意 revert：

```text
M docs/openos/communication/structured_communication_protocol.md
M src/agent/analyst.py
M src/agent/executor.py
M src/agent/planner.py
M src/agent/shared.py
M src/agent/summarizer.py
M src/config.py
M src/graph.py
M src/metrics.py
?? docs/openos/notext_state_transfer/kv_latent/
?? exp/latent_kv_exp/
?? src/agent/latent_kv_agents.py
?? src/latent_kv_model_server.py
?? src/latent_kv_runtime.py
?? task/lantent/
```

`git status` 里还有其他历史实验目录和文档，详见另开窗口后重新执行 `git status --short`。

## 8. B 模式效果差的最新分析

结论：B 的效果差不只是状态传递方式不同，还包含多个实现和任务契约问题。

### 8.1 统计不是把 B 算错了

四城市最新结果中：

- B 10 轮全部 `raw_route: []`。
- B 10 轮全部 `raw_total_cost: 0`。
- B 10 轮全部 `answer_source: reference_fallback_for_reporting`。
- reference fallback 只用于报告展示，没有计入正确率。

因此 B 的 0/10 是真实链路输出失败，不是统计口径错误。

### 8.2 B 的 analyst 没有识别 JSON final contract

四城市 prompt 使用：

```text
Return only JSON with exactly these fields:
{"route":["A","..."],"total_cost":"<integer>","verification":"<short string>"}
```

但 B 的 `src/agent/analyst.py` 只识别旧格式：

```text
Expected answer format: @field[value]
```

所以 `required_answer_fields` 为空，`candidate_answers` 为空，route/cost 没有进入后续链路。

### 8.3 researcher/analyst 是通用研究链路，不是组合优化求解链路

`src/agent/researcher.py` 会生成 3-5 段 source material。它不保证：

- 保留原始距离矩阵。
- 枚举所有路线。
- 保留每轮约束。
- 输出 machine-readable candidate answer。

对四城市这种小规模精确计算题，通用研究链路会引入解释性文本和信息损耗。

### 8.4 structured context packet 可能压缩掉关键数值约束

B structured 模式传递的是 researcher 生成文本的 context packet，而不是原始任务事实的精确结构化状态。packet 选择和摘要适合长文证据压缩，不适合小矩阵精确计算。

### 8.5 executor 没有任务级确定性工具

`src/agent/executor.py` 现在的 `_build_codeact_program()` 只计算：

```text
evidence_count
supported_claims
unique_doc_keys
reliable_packets
rehydrated_packets
coverage_ratio
analysis_chars
```

它不会：

- 从四城市 prompt 解析距离矩阵。
- 枚举路径。
- 验证路线约束。
- 计算 total_cost。
- 计算交易系统的 deadline/loss/severity 等字段。

因此即使 executor 有 JSON contract 支持，也没有可靠的字段来源。

### 8.6 summarizer 会吐占位 JSON

当上游没有 route/cost 时，summarizer 的 JSON contract 模板会变成：

```json
{"route":["A","..."],"total_cost":"<integer>","verification":"<short string>"}
```

这正是 B 最新十轮里的实际输出形态。

### 8.7 D 也不是干净的纯 state-transfer 对照

D 当前实现是混合链路：

- planner/researcher 仍先走显式 structured 阶段。
- analyst/executor/summarizer 继承 latent KV。
- summarizer 从 inherited KV state decode final JSON。

D 比 B 好，部分原因是最终 decode 能直接看到/继承更多原始上下文并产出 JSON；不能简单说是 latent KV 独立带来了全部推理收益。

D 自身仍有问题：

- 四城市完全正确只有 3/10。
- 多轮 route 对但 cost 错。
- 输出常有重复 JSON、markdown fence、自相矛盾 verification。
- 交易系统字段命中 40/60 但全字段正确仍 0/10。

## 9. 建议的下一步

如果继续修实现，优先顺序建议：

1. 修 B 的 JSON contract 贯穿：
   - 让 `analyst.py` 也调用 `_extract_json_final_contract_fields(query)`。
   - JSON contract 存在时，要求 `candidate_answers` 使用这些字段，如 `route`、`total_cost`、`verification`。
   - `_clean_candidate_answers` 或新逻辑要允许 list/int/dict，不要强制 scalar string。

2. 给 executor 加任务级确定性工具：
   - 四城市：从 prompt/任务 JSON 解析 cities、distance_matrix、每轮约束，直接枚举 route 并计算 cost。
   - 交易系统：对字段做确定性规则/公式校验，至少计算 deadline/loss 等数值字段。

3. summarizer 不应接受占位符：
   - 对 `<integer>`、`["A","..."]`、`unknown`、空字符串做 hard fail 或回退 executor final answer。
   - 机器评测任务优先使用 executor final answer，不让 summarizer 自由猜。

4. researcher 对精确计算任务应避免生成二手材料：
   - 四城市可跳过 researcher，或传递原始任务事实 packet。
   - 如果保留 researcher，应要求它输出候选路径表和距离矩阵，不输出泛化研究段落。

5. 重跑公平 ablation：
   - B structured + JSON contract 修复。
   - B structured + deterministic executor。
   - D latent + 同一个 deterministic executor。
   - 单模型 direct-json baseline 保持作为质量下限/上限参考。

6. 论文/PPT 结论表述建议：
   - 当前结果可以说“D 在现有实现中比 B 更快，显式文本通信更少，输出可解析性更好”。
   - 不建议说“D/B 差距纯粹证明 latent KV 状态传递更优”。
   - B 当前有 contract 断裂，是重要混杂因素。

## 10. 继续工作常用命令

查容器：

```bash
docker ps --filter name=^/SynapseX-wmw71$ --format '{{.Names}} {{.Status}} {{.Image}}'
```

查 GPU 与相关进程：

```bash
docker exec SynapseX-wmw71 bash -lc 'export TZ=Asia/Shanghai; date; nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits; ps -eo pid,ppid,stat,etime,cmd | grep -E "latent_kv_model_server|run_4city_bd_latest_stats|run_qwen3_8b_only_baseline|run_incident_response_abd|python" | grep -v grep || true'
```

看四城市 B/D 报告：

```bash
sed -n '1,220p' exp/latent_kv_exp/4city_bd_latest_stats_gpu2_20260707_122042/4city_BD_latest_stats_report.md
```

看单模型 baseline：

```bash
sed -n '1,220p' docs/openos/notext_state_transfer/kv_latent/exp/qwen3-8b-only.md
```

查 B 原始不可解析输出：

```bash
rg -n 'raw_route|raw_total_cost|answer_source|final_answer|summary' exp/latent_kv_exp/4city_bd_latest_stats_gpu2_20260707_122042/round_B_01_route_round_01.json
```

查 D 原始可解析输出：

```bash
rg -n 'raw_route|raw_total_cost|answer_source|final_answer|summary' exp/latent_kv_exp/4city_bd_latest_stats_gpu2_20260707_122042/round_D_01_route_round_01.json
```

查关键代码位置：

```bash
rg -n 'Expected answer format|Return only JSON|candidate_answers|required_answer_fields|_extract_json_final_contract_fields|_build_final_answer|_clean_json_contract_answer' src/agent exp/latent_kv_exp/run_4city_bd_latest_stats.py
```

## 11. 当前最重要的判断

- B 四城市 0/10 是真实输出失败，不是统计错误。
- B 与 D 的差距目前有实现混杂，尤其是 B 的 JSON contract 没贯穿、executor 没任务求解能力。
- D 四城市质量明显好于 B，但还不稳定；D 交易系统字段命中好于 B，但全字段 0/10。
- 单模型 direct-json baseline 速度快是因为负载极小；它对验证多智能体收益有用，但不能直接作为同等端到端延迟对照。
- 下一步如果要让实验结论更硬，必须先修 B 的 contract/executor，再重跑 B/D/D+tool/单模型 ablation。
