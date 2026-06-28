# trueKV 非文本中间状态传递最新设计

## 1. 当前结论

当前只保留一条最新口径：`true_kv_transfer`。

它面向赛题中的“非文本中间状态传递”，核心不是筛选文本、摘要文本或传递 context packet，而是让长文档经过 vLLM prefill 后生成的 KV cache tensors 通过 `SharedStorageConnector` 写入共享存储，再由后续 Agent/LLM 调用复用。

```text
ContextPrefill / KV producer
        │
        │  long document -> vLLM prefill
        │  write KV tensors to shared storage
        ↓
SharedStorageConnector
        │
        │  model.layers.*.self_attn.attn.safetensors
        ↓
Five business Agents / KV consumers
        │
        │  planner -> researcher_1/2/3 -> analyst -> executor -> summarizer
        │  text side sends only suffix/state
        ↓
final artifact / answer
```

当前仓库实现采用“旁路线”隔离方式：主线 `planner.py`、`researcher.py`、`analyst.py`、`executor.py`、`summarizer.py` 不侵入修改；trueKV/cache 实验集中在 `cache_agents.py`、`true_kv_handoff_runtime.py` 和实验脚本中。

## 2. 最新相关文件

| 文件 | 作用 |
|---|---|
| `src/true_kv_handoff_runtime.py` | vLLM `KVTransferConfig`、`SharedStorageConnector`、trueKV handoff handle 构造 |
| `src/agent/cache_agents.py` | cache/trueKV 旁路线的五个业务 Agent 职责函数 |
| `src/vllm_cache_runtime.py` | vLLM cache runtime、suffix/effective-token 统计辅助 |
| `src/graph.py` | `build_cache_graph()` 构造 `context_prefill + 5 Agent` cache 图 |
| `exp/kv_cache_exp/run_five_agent_truekv_fair_current.py` | 最新 A/text、B/structured、C/trueKV 五 Agent 公平对比脚本 |
| `task/longtext/skyforge_cache_tasks.json` | 长上下文连续游戏生成任务源 |
| `exp/kv_cache_exp/five_agent_truekv_fair_recovered_gpu0_20260628_150000/experiment_report.md` | 最新公平实验报告 |

## 3. 五 Agent 拓扑

公平实验中，三组都保持同一业务拓扑：

```text
planner -> researcher_1 / researcher_2 / researcher_3 -> analyst -> executor -> summarizer
```

其中：

- `planner`：生成计划和 3 个研究方向。
- `researcher_1/2/3`：按子方向生成实现材料或证据。
- `analyst`：整合研究材料，输出实现需求、风险和验收测试。
- `executor`：确定性执行/校验步骤，不调用 LLM。
- `summarizer`：生成最终 Python 游戏脚本和说明文档。

trueKV 组额外有一个非业务 producer：

```text
context_prefill -> planner -> researcher_1/2/3 -> analyst -> executor -> summarizer
```

`context_prefill` 只负责写入非文本 KV 状态，不替代任何业务 Agent。统计时它作为非文本状态写入开销单独列出。

## 4. A/B/C 三组状态传递定义

| 组别 | 模式 | 长文档状态传递方式 | 文本侧开销 | 非文本状态 |
|---|---|---|---|---|
| A | `text` | 长文档作为文本状态进入每个 Agent prompt | 全文 prompt tokens | 无 |
| B | `structured` | 长文档被结构化摘要/JSON brief 替代 | 摘要/brief tokens | 无 |
| C | `true_kv_transfer` | 长文档作为 vLLM KV tensors 复用 | 只统计当前 Agent suffix/state | `SharedStorageConnector` KV tensor 文件 |

公平约束：

- 三组业务 Agent 数量一致。
- 三组业务职责一致。
- 三组 LLM Agent 调用次数一致：6 次。
- 三组使用同一任务源、同一 Qwen3-8B、同一 max tokens、同一 temperature。
- 唯一变化是 Agent 间状态传递方式。

## 5. trueKV handoff 机制

### 5.1 vLLM 配置

`src/true_kv_handoff_runtime.py` 使用 vLLM 的 `KVTransferConfig`：

```python
{
    "kv_connector": "SharedStorageConnector",
    "kv_role": "kv_both",
    "kv_connector_extra_config": {
        "shared_storage_path": "..."
    }
}
```

`SharedStorageConnector` 会把各层 KV tensors 写成共享目录中的 `.safetensors` 文件。

### 5.2 handoff handle

trueKV handle 是 control plane，不是文本上下文本身：

```json
{
  "handoff_id": "true-kv-five_agent_context_prefill-5bfb75df4b466bdc",
  "backend": "vllm_kv_transfer",
  "connector": "SharedStorageConnector",
  "storage_path": "exp/kv_cache_exp/.../true_kv_shared_storage",
  "model_path": "/data/models/Qwen3-8B",
  "token_hash": "5bfb75df4b466bdc",
  "prompt_tokens": 3346,
  "producer_agent": "five_agent_context_prefill",
  "prompt_text_required_for_lookup": true
}
```

真正的 data plane 是共享目录中的 KV tensor 文件：

```text
true_kv_shared_storage/<hash>/model.layers.0.self_attn.attn.safetensors
...
true_kv_shared_storage/<hash>/model.layers.35.self_attn.attn.safetensors
```

### 5.3 当前 vLLM API 限制

当前 vLLM public `LLM.generate()` 还不是理想的：

```python
llm.generate_from_kv(kv_handle=handle, suffix_tokens=current_task)
```

实际使用 `SharedStorageConnector` 时，vLLM 仍需要同一个 token prefix 作为 lookup key。因此报告里必须区分：

| 指标 | 含义 |
|---|---|
| `logical_prompt_tokens` | vLLM 请求中出现的完整 token 序列 |
| `effective_prompt_tokens` | 扣除已复用 KV prefix 后，估算真正需要重新 prefill 的 token |
| `agent_text_transfer_tokens` | Agent 间显式传递的文本 suffix/state token |
| `kv_reused_tokens` | 通过 KV connector 复用的 prefix token |
| KV 文件数 / bytes | 非文本 KV tensor 状态规模 |

## 6. 最新公平实验结果

实验目录：

```text
exp/kv_cache_exp/five_agent_truekv_fair_recovered_gpu0_20260628_150000
```

运行脚本：

```text
exp/kv_cache_exp/run_five_agent_truekv_fair_current.py
```

运行命令：

```bash
CUDA_VISIBLE_DEVICES=0 \
VLLM_GPU_MEMORY_UTILIZATION=0.70 \
VLLM_MAX_MODEL_LEN=8192 \
VLLM_MAX_NUM_SEQS=1 \
VLLM_MAX_NUM_BATCHED_TOKENS=4096 \
python3 -u exp/kv_cache_exp/run_five_agent_truekv_fair_current.py \
  --output-dir exp/kv_cache_exp/five_agent_truekv_fair_recovered_gpu0_20260628_150000 \
  --clean
```

总体指标：

| 组别 | 模式 | LLM 调用数 | wall time | effective total tokens | 文本通信 tokens | KV reused tokens | 最终产物评分 | 编译/q/WASD |
|---|---|---:|---:|---:|---:|---:|---:|---|
| A | `text` | 6 | 427.2786s | 37345 | 29891 | 0 | 0.0 | False / False / False |
| B | `structured` | 6 | 428.3351s | 18807 | 10615 | 0 | 0.0 | False / False / False |
| C | `true_kv_transfer` | 6 | 407.5070s | 16423 | 9143 | 20076 | 82.0 | True / True / True |

C/trueKV 相对收益：

- 相比 A/text，`effective_prompt_tokens` 降低 69.43%。
- 相比 A/text，`effective_total_tokens` 降低 56.02%。
- 相比 A/text，文本通信 tokens 降低 69.41%。
- 相比 B/structured，`effective_total_tokens` 降低 12.68%。
- 相比 B/structured，文本通信 tokens 降低 13.87%。

非文本状态传递统计：

| 指标 | A/text | B/structured | C/trueKV |
|---|---:|---:|---:|
| 非文本 KV 写入事件 | 0 | 0 | 1 |
| 非文本 KV 复用事件 | 0 | 0 | 6 |
| 非文本 KV 文件数 | 0 | 0 | 36 |
| 非文本 KV tensor bytes | 0 | 0 | 493096032 |
| source prefix tokens | 0 | 0 | 3346 |

每个 LLM Agent 调用明细见：

```text
exp/kv_cache_exp/five_agent_truekv_fair_recovered_gpu0_20260628_150000/experiment_report.md
```

## 7. 产物位置

C/trueKV 生成的可运行游戏脚本：

```text
exp/kv_cache_exp/five_agent_truekv_fair_recovered_gpu0_20260628_150000/artifacts/true_kv_transfer/skyforge_courier_release/skyforge_courier_game.py
```

运行方式：

```bash
python3 exp/kv_cache_exp/five_agent_truekv_fair_recovered_gpu0_20260628_150000/artifacts/true_kv_transfer/skyforge_courier_release/skyforge_courier_game.py
```

自动评估结果：

- `py_compile`：通过。
- `q` 退出：通过。
- `WASD` 试玩：通过。

## 8. 当前结论

当前最新 trueKV 方案满足赛题“非文本中间状态传递”的关键要求：

- 有真实 vLLM KV tensor 文件写入共享存储。
- 有 1 次 producer 写入和 6 次 consumer 复用。
- 三组对比保持同一业务 Agent 拓扑、职责和调用次数。
- C/trueKV 的文本通信 token 和 effective token 明显低于 A/text，并且最终产物可编译、可试玩。

需要在论文/报告中诚实说明的限制：

- vLLM `SharedStorageConnector` 仍需要相同 token prefix 作为 lookup key。
- 因此 `logical_prompt_tokens` 不会消失，真正体现收益的是 `effective_prompt_tokens`、`agent_text_transfer_tokens` 和 KV tensor 复用统计。
- 当前实现是工程 proof-of-concept，不是稳定 public API 级别的 `kv_handle + suffix_only` 生成接口。
