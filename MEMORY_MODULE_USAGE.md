# 长期记忆模块使用说明

本文档说明当前项目中长期记忆模块的启用方式、运行流程、数据位置、常用命令和结果指标。本文档偏使用说明，不展开完整设计原理；设计说明可参考 `MEMORY_MECHANISM_DESIGN.md`。

## 1. 功能概览

当前长期记忆模块用于在多智能体任务之间复用历史经验。系统会将历史任务中的 `summary` 和 `analysis` 写入 Qdrant-backed memory，然后在后续任务中由 planner 统一检索和校验。

当前主流程为：

```text
analyst / summarizer 写入长期记忆
        ↓
planner 检索 summary / analysis 候选记忆
        ↓
planner 判断候选记忆是否可复用
        ↓
通过校验的记忆进入 validated_memories
        ↓
analyst 将 validated_memories 作为 reusable hints 使用
        ↓
若记忆命中，减少 researcher fan-out
```

需要注意：

- planner 是当前唯一主动读取长期记忆的 agent。
- analyst 当前不主动检索历史 analysis，只消费 planner 传递的 `validated_memories`。
- executor 当前不写入 Qdrant 长期记忆，只写 Runtime Store 中的 execution 记录。
- 记忆不能替代当前任务证据，只能作为分析提示或复用方法。

## 2. 主要环境变量

推荐先加载项目根目录下的 `.env.sh`：

```bash
source .env.sh
```

当前 `.env.sh` 中与记忆模块相关的配置如下：

```bash
export PERSISTENT_MEMORY_ENABLED=0
export LONG_TERM_MEMORY_ENABLED=1
export LONG_TERM_MEMORY_QDRANT_PATH=.memory/memory_module_local_hash/data/qdrant
export LONG_TERM_MEMORY_COLLECTION=shared_memories_local_hash_1024
export LONG_TERM_MEMORY_ADD_LOG_PATH=.memory/memory_module_local_hash/logs/memory_add.jsonl
export LONG_TERM_MEMORY_SEARCH_MODE=bm25
export LONG_TERM_MEMORY_TOP_K=4
export LONG_TERM_MEMORY_BM25_MODEL_PATH=models--Qdrant--bm25
export LONG_TERM_TASK_STATE_ENABLED=0

export PLANNER_MEMORY_CONFIDENCE_THRESHOLD=0.5
export REDUCE_RESEARCH_ON_MEMORY_HIT=1
```

配置项说明：

| 配置项 | 作用 |
| --- | --- |
| `LONG_TERM_MEMORY_ENABLED` | 是否启用 Qdrant 长期记忆 |
| `LONG_TERM_MEMORY_QDRANT_PATH` | Qdrant 本地数据目录 |
| `LONG_TERM_MEMORY_COLLECTION` | Qdrant collection 名称 |
| `LONG_TERM_MEMORY_ADD_LOG_PATH` | 记忆写入日志路径 |
| `LONG_TERM_MEMORY_SEARCH_MODE` | 检索模式，支持 `dense`、`bm25`、`hybrid` |
| `LONG_TERM_MEMORY_TOP_K` | 默认长期记忆检索 top-k |
| `LONG_TERM_MEMORY_BM25_MODEL_PATH` | BM25 模型路径 |
| `LONG_TERM_TASK_STATE_ENABLED` | 是否启用 task_state 长期记忆 |
| `PLANNER_MEMORY_CONFIDENCE_THRESHOLD` | planner 判断记忆可复用的 confidence 阈值 |
| `REDUCE_RESEARCH_ON_MEMORY_HIT` | 记忆命中后是否减少 researcher sub-query |
| `PERSISTENT_MEMORY_ENABLED` | 是否启用原 JSONL + LangGraph Store 持久化 |

当前 planner 对 `summary` 和 `analysis` 的检索会读取 `LONG_TERM_MEMORY_TOP_K`。例如设置 `LONG_TERM_MEMORY_TOP_K=4` 时，planner 会分别检索最多 4 条 summary 候选和 4 条 analysis 候选，然后再由 planner 校验哪些记忆真正可复用。

## 3. 数据保存位置

当前本地长期记忆数据默认保存到：

```text
.memory/memory_module_local_hash/data/qdrant
```

记忆写入日志默认保存到：

```text
.memory/memory_module_local_hash/logs/memory_add.jsonl
```

其中：

- Qdrant 目录保存实际向量库数据。
- `memory_add.jsonl` 记录每次写入的记忆 id、内容摘要、类型和来源信息，适合调试。

如果需要重新开始一组干净实验，可以换一个新的 `LONG_TERM_MEMORY_QDRANT_PATH` 和 `LONG_TERM_MEMORY_COLLECTION`，避免和旧实验数据混在一起。

## 4. 检查记忆模块是否可用

加载环境变量后，可以运行：

```bash
PYTHONPATH=.:src python3 -c "from memory import qdrant_memory_available, get_qdrant_memory; print(qdrant_memory_available()); print(get_qdrant_memory())"
```

正常情况下应输出：

```text
True
<memory_module.module.MemoryModule object at ...>
```

如果输出 `False` 或 `None`，常见原因包括：

- 没有加载 `.env.sh`。
- `PYTHONPATH` 没有包含 `src`。
- `memory_module` 依赖缺失。
- `models--Qdrant--bm25` 路径不存在或不可读。
- `LONG_TERM_MEMORY_ENABLED=0`。

## 5. 如何写入记忆

长期记忆写入由 agent 自动完成，通常不需要手动调用。

当前自动写入路径包括：

| 写入者 | memory_type | 写入内容 |
| --- | --- | --- |
| analyst | `analysis` | 分析结果、候选答案、证据摘要、任务主题 |
| summarizer | `summary` | 任务总结、关键发现、最终答案 |

写入发生在任务运行过程中：

```text
analyst 生成 analysis 后写入 analysis 记忆
summarizer 生成 summary 后写入 summary 记忆
```

executor 当前不写入 Qdrant 长期记忆。

## 6. 如何检索和复用记忆

记忆检索由 planner 自动完成。planner 会从当前任务 query 中提取较短的 memory query，避免把长文本上下文、样例数据和 answer format 一起用于 BM25 检索。

planner 当前会检索：

```text
memory_type = summary
memory_type = analysis
```

检索后，planner 不会直接使用所有候选记忆，而是输出：

```json
{
  "memory_validation": {
    "usable": true,
    "confidence": 0.85,
    "reason": "候选记忆与当前任务属于同一类问题，可以复用分析方法。",
    "reused_memory_ids": ["memory_xxx"]
  }
}
```

本地代码会再次校验：

- `reused_memory_ids` 必须来自候选记忆；
- `usable` 必须为 true；
- `confidence` 必须达到 `PLANNER_MEMORY_CONFIDENCE_THRESHOLD`；
- 通过后才进入 `validated_memories`。

只有 `validated_memories` 会传递给 analyst。

## 7. 记忆命中后的行为

如果 planner 判断存在可复用记忆：

```text
memory_hit = True
```

并且启用：

```bash
export REDUCE_RESEARCH_ON_MEMORY_HIT=1
```

系统会减少 researcher fan-out。原本 planner 通常生成 3 个 sub-query，命中记忆后会缩减为 1 个 verification query。

这样可以减少：

- researcher 调用次数；
- LLM 总调用次数；
- 输入 token；
- 重复上下文传递。

## 8. 常用运行方式

### 8.1 加载环境

```bash
source .env.sh
```

如果在容器中运行，需要确保当前目录挂载到容器内，并且在项目根目录执行命令。

### 8.2 运行 data_anas 对比实验

```bash
PYTHONPATH=.:src python3 task/data_anas/run_group1_comparison.py
```

主要输出：

```text
task/data_anas/result/group1_comparison_memory.json
task/data_anas/result/group1_comparison_no_memory.json
```

### 8.3 运行 company_com 单组实验

示例：

```bash
PYTHONPATH=.:src python3 task/company_com/run_company_graph_single.py \
  --mode structured \
  --companies CDNS \
  --max-sessions 10 \
  --fresh-graph-per-session
```

常见输出位置：

```text
task/company_com/result/
```

不同实验文件名通常包含：

```text
memory / no_memory
text / structured
```

## 9. 结果字段说明

任务结果 JSON 中常见记忆字段如下：

| 字段 | 含义 |
| --- | --- |
| `memory_hit` | 是否存在通过 planner 校验的记忆 |
| `reduced_research` | 是否减少 researcher fan-out |
| `reused_memory_ids` | 检索到的候选记忆 id |
| `memory_validation` | planner 对候选记忆的可复用判断 |
| `validated_memory_ids` | 最终通过校验、允许下游复用的记忆 id |

metrics 中常见字段如下：

| 字段 | 含义 |
| --- | --- |
| `memory_reuse_attempts` | planner 找到候选记忆的次数 |
| `memory_candidates_found` | 候选记忆数量 |
| `memory_reuse_hits` | planner 校验通过的记忆命中次数 |
| `planner_memory_validated` | planner 判定可复用的次数 |
| `planner_memory_rejected` | planner 拒绝候选记忆的次数 |
| `research_fanout_reduced` | researcher fan-out 被减少的次数 |
| `research_subqueries_saved` | 节省的 researcher sub-query 数量 |
| `llm_calls` | LLM 调用次数 |
| `total_tokens` | 总 token 消耗 |

## 10. 生成实验图

生成记忆命中率和复用漏斗图：

```bash
PYTHONPATH=.:src python3 task/analyze_memory_reuse.py
```

输出：

```text
task/result/memory_reuse_rates.csv
task/result/memory_reuse_rates.json
task/result/memory_hit_rate.png
task/result/memory_reuse_funnel.png
```

生成执行时间和 token 消耗图：

```bash
PYTHONPATH=.:src python3 task/plot_memory_performance.py
```

输出：

```text
task/result/memory_performance_time.png
task/result/memory_performance_tokens.png
task/result/memory_performance_avg.csv
```

## 11. 如何关闭记忆

完全关闭 Qdrant 长期记忆：

```bash
export LONG_TERM_MEMORY_ENABLED=0
```

关闭原 JSONL + Store 持久化：

```bash
export PERSISTENT_MEMORY_ENABLED=0
```

关闭记忆命中后减少 researcher：

```bash
export REDUCE_RESEARCH_ON_MEMORY_HIT=0
```

常用对比设置：

```bash
# 无长期记忆
export LONG_TERM_MEMORY_ENABLED=0
export PERSISTENT_MEMORY_ENABLED=0
export REDUCE_RESEARCH_ON_MEMORY_HIT=0

# 启用长期记忆
export LONG_TERM_MEMORY_ENABLED=1
export PERSISTENT_MEMORY_ENABLED=0
export REDUCE_RESEARCH_ON_MEMORY_HIT=1
```

## 12. 常见问题

### 12.1 qdrant_memory_available 返回 False

检查：

```bash
source .env.sh
PYTHONPATH=.:src python3 -c "from memory import qdrant_memory_available; print(qdrant_memory_available())"
```

如果仍为 False，检查 `memory_module` 依赖、BM25 模型路径和 Qdrant 数据目录。

### 12.2 有记忆文件但没有命中

可能原因：

- planner 检索到了候选，但 confidence 低于阈值；
- 候选记忆与当前任务只是关键词相似，不可复用；
- `PLANNER_MEMORY_CONFIDENCE_THRESHOLD` 设置过高；
- `LONG_TERM_MEMORY_SEARCH_MODE` 不适合当前数据；
- memory query 过短或没有包含关键实体。

可以查看结果 JSON 中：

```text
memory_validation
reused_memory_ids
validated_memory_ids
```

### 12.3 检索候选太多但效果变差

候选记忆过多可能污染 planner 判断和 analyst 上下文。可以调小：

```bash
export LONG_TERM_MEMORY_TOP_K=2
```

该变量会影响 planner 对 summary 和 analysis 候选记忆的检索数量。

### 12.4 token 下降但时间没有明显下降

这是正常现象。执行时间还受到以下因素影响：

- 本地模型推理速度波动；
- Qdrant 检索开销；
- embedding 或 BM25 编码开销；
- Python 调度和 I/O；
- 容器和后端服务状态。

因此评估记忆效率时，应同时查看：

```text
memory_hit_rate
research_subqueries_saved
llm_calls
total_tokens
elapsed_s
accuracy
```

## 13. 推荐实验流程

建议按以下顺序做实验：

1. 加载 `.env.sh`。
2. 确认 `qdrant_memory_available()` 为 True。
3. 先运行一轮启用记忆的任务，让系统写入 summary 和 analysis。
4. 再运行后续任务，观察 planner 是否检索并校验记忆。
5. 查看结果 JSON 中的 `memory_validation` 和 `validated_memory_ids`。
6. 运行 `task/analyze_memory_reuse.py` 统计命中率。
7. 运行 `task/plot_memory_performance.py` 生成时间和 token 图。
8. 对比无记忆、有记忆、text、structured 四组结果。

核心判断标准：

```text
是否检索到候选记忆
是否通过 planner 校验
是否减少 researcher fan-out
是否降低 total_tokens
是否保持或提升 accuracy
```
