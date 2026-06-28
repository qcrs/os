# 同五 Agent 主图 A/B/C 公平对比实验

## 公平性约束

- 三组都执行同一逻辑拓扑：`planner → researcher_1/researcher_2/researcher_3 → analyst → executor → summarizer`。
- 三组 LLM Agent 调用次数相同：`6` 次，executor 是确定性 CodeAct，不调用 LLM。
- 三组使用同一任务源、同一模型、同一 max tokens、同一 temperature。
- 唯一变化：Agent 间状态传递方式不同。A 传全文文本，B 传结构化摘要/JSON，C 通过 `SharedStorageConnector` 复用长源文档 KV tensors，并传少量 suffix/state。

## 总体指标

| 组别 | 模式 | LLM调用数 | wall_time_sec | logical_prompt_tokens | effective_prompt_tokens | output_tokens | effective_total_tokens | 文本通信tokens | kv_reused_tokens | 最终产物评分 | 编译 | q退出 | WASD试玩 | 产物目录 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| A | `text` | 6 | 427.2786 | 29891 | 29891 | 7454 | 37345 | 29891 | 0 | 0.0 | False | False | False | `exp/kv_cache_exp/five_agent_truekv_fair_recovered_gpu0_20260628_150000/artifacts/text/skyforge_courier_release` |
| B | `structured` | 6 | 428.3351 | 10615 | 10615 | 8192 | 18807 | 10615 | 0 | 0.0 | False | False | False | `exp/kv_cache_exp/five_agent_truekv_fair_recovered_gpu0_20260628_150000/artifacts/structured/skyforge_courier_release` |
| C | `true_kv_transfer` | 6 | 407.507 | 29213 | 9137 | 7286 | 16423 | 9143 | 20076 | 82.0 | True | True | True | `exp/kv_cache_exp/five_agent_truekv_fair_recovered_gpu0_20260628_150000/artifacts/true_kv_transfer/skyforge_courier_release` |


## 每个 LLM Agent 调用明细

| 模式 | Agent | wall_time_sec | logical_prompt | effective_prompt | output | 文本通信tokens | kv_reused |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| text | planner | 43.9943 | 6157 | 6157 | 768 | 6157 | 0 |
| text | researcher_1 | 40.3125 | 3587 | 3587 | 768 | 3587 | 0 |
| text | researcher_2 | 41.0564 | 4343 | 4343 | 768 | 4343 | 0 |
| text | researcher_3 | 42.1712 | 5113 | 5113 | 768 | 5113 | 0 |
| text | analyst | 55.3121 | 5857 | 5857 | 1024 | 5857 | 0 |
| text | summarizer | 184.4944 | 4834 | 4834 | 3358 | 4834 | 0 |
| structured | planner | 39.5301 | 3264 | 3264 | 768 | 3264 | 0 |
| structured | researcher_1 | 39.2383 | 1135 | 1135 | 768 | 1135 | 0 |
| structured | researcher_2 | 38.6446 | 1229 | 1229 | 768 | 1229 | 0 |
| structured | researcher_3 | 38.8483 | 1363 | 1363 | 768 | 1363 | 0 |
| structured | analyst | 52.6072 | 1981 | 1981 | 1024 | 1981 | 0 |
| structured | summarizer | 208.8571 | 1643 | 1643 | 4096 | 1643 | 0 |
| true_kv_transfer | planner | 43.0516 | 6101 | 2755 | 767 | 2756 | 3346 |
| true_kv_transfer | researcher_1 | 41.0151 | 4129 | 783 | 768 | 784 | 3346 |
| true_kv_transfer | researcher_2 | 40.52 | 4275 | 929 | 768 | 930 | 3346 |
| true_kv_transfer | researcher_3 | 40.5244 | 4417 | 1071 | 768 | 1072 | 3346 |
| true_kv_transfer | analyst | 56.2806 | 5290 | 1944 | 1024 | 1945 | 3346 |
| true_kv_transfer | summarizer | 173.7809 | 5001 | 1655 | 3191 | 1656 | 3346 |

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
- producer wall time：`1.4398`
- KV 文件数：`36`
- KV tensor bytes：`493096032`


## 本次公平口径补充

- A/text：长文档作为文本状态进入每个 LLM Agent prompt；文本通信 token 等于完整 prompt token。
- B/structured：长文档被结构化摘要/JSON brief 替代；仍然是文本 token 通信，但不传全文。
- C/trueKV：长文档经 vLLM prefill 后由 SharedStorageConnector 写成 KV tensors；文本侧只传当前 Agent suffix/state，并统计 effective prompt。
- 三组业务 Agent 数量、职责和调用次数一致：均为 planner、3 个 researcher、analyst、executor、summarizer；其中 6 次 LLM 调用，executor 是确定性步骤不调用 LLM。

## 非文本状态传递统计

| 指标 | A/text | B/structured | C/trueKV |
| --- | ---: | ---: | ---: |
| 非文本 KV 写入事件 | 0 | 0 | 1 |
| 非文本 KV 复用事件 | 0 | 0 | 6 |
| 非文本 KV 文件数 | 0 | 0 | 36 |
| 非文本 KV tensor bytes | 0 | 0 | 493096032 |
| source prefix tokens | 0 | 0 | 3346 |

## 运行说明

- 本次有效运行命令：CUDA_VISIBLE_DEVICES=0 VLLM_GPU_MEMORY_UTILIZATION=0.70 VLLM_MAX_MODEL_LEN=8192 VLLM_MAX_NUM_SEQS=1 VLLM_MAX_NUM_BATCHED_TOKENS=4096 python3 -u exp/kv_cache_exp/run_five_agent_truekv_fair_current.py --output-dir exp/kv_cache_exp/five_agent_truekv_fair_recovered_gpu0_20260628_150000 --clean
- 先前尝试 GPU2 + VLLM_GPU_MEMORY_UTILIZATION=0.55 失败，原因是 vLLM 加载模型后没有足够 KV cache block 显存，不计入实验结果。

## 产物索引

| 文件 | 说明 |
| --- | --- |
| `exp/kv_cache_exp/five_agent_truekv_fair_recovered_gpu0_20260628_150000/summary.json` | 汇总指标 |
| `exp/kv_cache_exp/five_agent_truekv_fair_recovered_gpu0_20260628_150000/text.json` | A/text 原始输出 |
| `exp/kv_cache_exp/five_agent_truekv_fair_recovered_gpu0_20260628_150000/structured.json` | B/structured 原始输出 |
| `exp/kv_cache_exp/five_agent_truekv_fair_recovered_gpu0_20260628_150000/true_kv_transfer.json` | C/trueKV 原始输出 |
