# 三通道结构化通信协议 12 轮消融实验

## 一、实验目的

本实验用于评估结构化通信协议中三个通道的独立贡献和组合效果：

```bash
ENABLE_CONTEXT_PACKETS=1       # 文本压缩证据通道
ENABLE_EMBEDDING_TRANSFER=1    # 语义向量通道
ENABLE_HIDDEN_STATE_TRANSFER=1 # 隐藏状态特征通道
```

重点回答三个问题：

1. `context_packets` 是否能相对纯文本通信节省 LLM token？
2. `embedding_payloads` 加入后是否带来额外 token 节省或排序收益？
3. `hidden_state_payloads` 加入后是否能通过更强上下文选择进一步减少 token？

## 二、实验环境

| 项目 | 配置 |
|------|------|
| 历史运行容器 | `multi-agent_wmw_ablation`（已删除，当前复现实验请使用 `SynapseX-wmw`） |
| 模型 | `/data/models/Qwen3-8B` |
| 推理后端 | Hugging Face `transformers` |
| 通信链路 | `planner → retriever × 3 → executor → summarizer` |
| 任务轮数 | 12 轮连续任务 |
| 每组 LLM 调用 | 72 次 |
| 输出目录 | `ablation_results/` |
| 汇总文件 | `ablation_results/summary.json` |

说明：本次实验使用本地 Qwen3-8B，`embedding` 在无外部 API key 时使用本地 fallback；五组实验依次运行，因此 wall-clock 时间会受 GPU 负载、采样输出长度和运行顺序影响。

## 三、消融配置

| 实验 | 模式 | `ENABLE_CONTEXT_PACKETS` | `ENABLE_EMBEDDING_TRANSFER` | `ENABLE_HIDDEN_STATE_TRANSFER` | 目的 |
|------|------|--------------------------|------------------------------|---------------------------------|------|
| `text_baseline` | `text` | 0 | 0 | 0 | 纯文本通信基线 |
| `context_only` | `structured` | 1 | 0 | 0 | 只评估文本压缩证据包 |
| `context_embedding` | `structured` | 1 | 1 | 0 | 评估 embedding 在 context 基础上的边际贡献 |
| `context_hidden` | `structured` | 1 | 0 | 1 | 评估 hidden state 在 context 基础上的边际贡献 |
| `all_three` | `structured` | 1 | 1 | 1 | 评估三通道组合效果 |

## 四、核心结果

| 实验 | Context | Embedding | Hidden | Input tokens | Output tokens | Total tokens | 相对 Text | 相对 Context-only | 耗时 |
|------|--------:|----------:|-------:|-------------:|--------------:|-------------:|----------:|------------------:|-----:|
| `text_baseline` | 0 | 0 | 0 | 47,985 | 25,727 | 73,712 | 0 | +18,852 (+34.36%) | 961.0s |
| `context_only` | 1 | 0 | 0 | 28,929 | 25,931 | 54,860 | -18,852 (-25.58%) | 0 | 916.3s |
| `context_embedding` | 1 | 1 | 0 | 29,725 | 26,222 | 55,947 | -17,765 (-24.10%) | +1,087 (+1.98%) | 965.2s |
| `context_hidden` | 1 | 0 | 1 | 21,909 | 22,939 | 44,848 | -28,864 (-39.16%) | -10,012 (-18.25%) | 819.2s |
| `all_three` | 1 | 1 | 1 | 21,452 | 22,578 | 44,030 | -29,682 (-40.27%) | -10,830 (-19.74%) | 807.9s |

## 五、通道使用情况

| 实验 | `context_saved_chars` | `embedding_received` | `hidden_state_payloads_sent` | `hidden_state_used_executor_context_ranking` | `hidden_state_context_chars_skipped` |
|------|----------------------:|---------------------:|-----------------------------:|--------------------------------------------:|-------------------------------------:|
| `text_baseline` | 0 | 0 | 0 | 0 | 0 |
| `context_only` | 21,792 | 0 | 0 | 0 | 0 |
| `context_embedding` | 22,896 | 36 | 0 | 0 | 0 |
| `context_hidden` | 24,547 | 0 | 36 | 12 | 7,931 |
| `all_three` | 23,757 | 36 | 36 | 12 | 7,677 |

## 六、质量侧粗粒度指标

| 实验 | `key_findings` 总数 | `analysis_chars` | `summary_chars` |
|------|-------------------:|-----------------:|----------------:|
| `text_baseline` | 36 | 3,616 | 3,636 |
| `context_only` | 36 | 4,478 | 4,052 |
| `context_embedding` | 36 | 4,398 | 3,757 |
| `context_hidden` | 36 | 3,167 | 3,413 |
| `all_three` | 36 | 2,966 | 3,292 |

说明：`key_findings` 总数五组均为 36，表示每轮输出条目数稳定；但它只是粗粒度质量指标，不能证明事实正确率、引用命中率或覆盖率完全一致。

## 七、边际收益分析

### 7.1 `context_packets` 的贡献

`context_only` 相对 `text_baseline`：

- Total tokens：`73,712 → 54,860`
- 绝对节省：`18,852` tokens
- 相对节省：`25.58%`
- Input tokens：`47,985 → 28,929`，下降 `39.71%`

结论：`context_packets` 是直接节省 LLM token 的基础通道。它把全文文档替换为摘要、证据片段、引用和校验信息，减少 Executor prompt 中的长文本。

### 7.2 `embedding_payloads` 的贡献

`context_embedding` 相对 `context_only`：

- Total tokens：`54,860 → 55,947`
- 变化：`+1,087` tokens
- 相对变化：`+1.98%`
- `embedding_received`：`36`

结论：本次实验中 embedding 没有带来 token 节省，反而略微增加 total tokens。原因是 embedding 本身不进入 prompt，但它改变了上下文排序，导致被选中的 evidence/summary 组合略有变化，最终生成文本长度和输入长度略高。embedding 更适合作为语义召回/排序质量信号，而不是直接 token 压缩手段。

### 7.3 `hidden_state_payloads` 的贡献

`context_hidden` 相对 `context_only`：

- Total tokens：`54,860 → 44,848`
- 绝对节省：`10,012` tokens
- 相对节省：`18.25%`
- `hidden_state_payloads_sent`：`36`
- `hidden_state_used_executor_context_ranking`：`12`
- `hidden_state_context_chars_skipped`：`7,931`

结论：hidden state 在本次实验中贡献明显。它用于 Executor 侧上下文重排和 top-k 选择，使系统跳过了更多低相关上下文，从而减少进入 prompt 的文本。

### 7.4 三通道组合效果

`all_three` 相对 `text_baseline`：

- Total tokens：`73,712 → 44,030`
- 绝对节省：`29,682` tokens
- 相对节省：`40.27%`
- Input tokens：`47,985 → 21,452`，下降 `55.29%`

`all_three` 相对 `context_only`：

- 绝对节省：`10,830` tokens
- 相对节省：`19.74%`

结论：三通道全开取得本次实验最佳 token 效率。`context_packets` 负责压缩可读文本，`hidden_state_payloads` 负责意图对齐和上下文过滤，`embedding_payloads` 提供语义排序信号；组合后 Executor 只读取更少、更相关、可回查的证据。

## 八、结论

1. **直接省 token 的主力是 `context_packets`**：单独开启即可节省 `25.58%` total tokens。
2. **hidden state 带来额外压缩收益**：在 context-only 基础上继续节省 `18.25%` total tokens，并跳过 `7,931` 原始上下文字符。
3. **embedding 本次没有体现 token 节省**：它增加了 `1.98%` total tokens，但作为语义排序信号仍可能提升召回质量，需要用引用命中率、人工评分或事实一致性评测进一步验证。
4. **三通道全开效果最好**：相对纯文本节省 `40.27%` total tokens，input tokens 下降 `55.29%`。
5. **质量评估仍需补充**：当前只有 `key_findings` 数量、分析长度和摘要长度等粗指标；如果要证明“更可靠”，还需要事实正确率、引用命中率、证据覆盖率、幻觉率等指标。

## 九、原始结果文件

| 文件 | 内容 |
|------|------|
| `ablation_results/text_baseline.json` | 纯文本基线结果 |
| `ablation_results/context_only.json` | 只开启 context packets 的结果 |
| `ablation_results/context_embedding.json` | context + embedding 结果 |
| `ablation_results/context_hidden.json` | context + hidden state 结果 |
| `ablation_results/all_three.json` | 三通道全开结果 |
| `ablation_results/summary.json` | 本文使用的汇总结果 |
