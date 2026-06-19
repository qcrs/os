# 12 轮连续任务双模式对比实验报告（v4 — 三通道结构化通信协议）

## 最新实验结论（2026-06-18）

本次在容器 `multi-agent_wmw` 中使用本地 `Qwen3-8B` 跑完 12 轮对照实验。Structured 模式同时开启三类结构化通信通道：

```bash
ENABLE_CONTEXT_PACKETS=1
ENABLE_EMBEDDING_TRANSFER=1
ENABLE_HIDDEN_STATE_TRANSFER=1
CHAT_BACKEND=transformers
LOCAL_MODEL_PATH=/data/models/Qwen3-8B
```

说明：容器内未设置 `DASHSCOPE_API_KEY`，因此 embedding 使用 `LocalHashEmbeddings` 本地 fallback；hidden state 使用本地 Transformers 后端在生成前捕获，且通过独立 `hidden_state_payloads` 通道传递。

### 核心 token 对比

| 指标 | 纯文本 text | 三通道 structured | 差异 |
|------|-------------|-------------------|------|
| LLM 调用次数 | 72 | 72 | 0 |
| Input tokens | 32,166 | 19,503 | **-12,663 (-39.37%)** |
| Output tokens | 13,281 | 13,121 | **-160 (-1.20%)** |
| Total tokens | 45,447 | 32,624 | **-12,823 (-28.22%)** |
| Wall-clock 时间 | 633.1s | 636.0s | +2.9s (+0.46%) |

### Structured 三通道启用情况

| 指标 | 数值 |
|------|------|
| `context_packets_enabled` | 36 |
| `context_packets_disabled` | 0 |
| `embedding_transfers` | 36 |
| `embedding_received` | 36 |
| `hidden_state_payloads_sent` | 36 |
| `hidden_state_payloads_received` | 36 |
| `hidden_state_produced_planner` | 12 |
| `hidden_state_produced_retriever` | 36 |
| `hidden_state_used_executor_context_ranking` | 12 |
| `hidden_state_context_packets_skipped` | 12 |
| `hidden_state_context_chars_skipped` | 4,261 |
| `context_original_chars` | 21,227 |
| `context_compressed_chars` | 14,125 |
| `context_saved_chars` | 7,102 |

### Per-Agent token 分布

**纯文本 text：**

| Agent | 调用数 | Input tokens | Output tokens | Total |
|-------|--------|--------------|---------------|-------|
| planner | 12 | 4,920 | 1,761 | 6,681 |
| retriever | 36 | 2,626 | 6,912 | 9,538 |
| executor | 12 | 19,984 | 2,304 | 22,288 |
| summarizer | 12 | 4,636 | 2,304 | 6,940 |
| **合计** | **72** | **32,166** | **13,281** | **45,447** |

**三通道 structured：**

| Agent | 调用数 | Input tokens | Output tokens | Total |
|-------|--------|--------------|---------------|-------|
| planner | 12 | 4,359 | 1,601 | 5,960 |
| retriever | 36 | 2,541 | 6,912 | 9,453 |
| executor | 12 | 7,391 | 2,304 | 9,695 |
| summarizer | 12 | 5,212 | 2,304 | 7,516 |
| **合计** | **72** | **19,503** | **13,121** | **32,624** |

### 结论

三通道 structured 相比纯文本 text 的主要收益来自 **Executor 输入 token 降低**：`19,984 → 7,391`，减少 `12,593` tokens，降幅约 `63.02%`。整体 total tokens 从 `45,447` 降到 `32,624`，减少 `12,823` tokens，降幅 `28.22%`。

这说明三通道结构化通信协议在本次 12 轮本地 Qwen3-8B 实验中确实节省了 LLM token；其中 `context_packets` 提供压缩文本证据，`embedding_payloads` 提供语义排序信号，`hidden_state_payloads` 提供 Planner/Retriever 意图对齐信号。

结果文件：`examples/multi_agent_demo/results_12rounds.json`。

---

## 历史实验记录

### 12 轮连续任务双模式对比实验报告（v3 — 上下文压缩协议）

## 实验设计

### 12 轮递进任务

| 阶段 | 轮次 | 任务描述 | 依赖关系 |
|------|------|----------|----------|
| **Phase 1: Foundation** | R01 | LangGraph 核心概念 | — |
| | R02 | 状态管理机制 | 依赖 R01 记忆 |
| | R03 | 共享记忆系统 | 依赖 R01-R02 记忆 |
| | R04 | 多智能体通信 | 依赖 R01-R03 记忆 |
| **Phase 2: Comparison** | R05 | AutoGen 架构 | 依赖 R01-R04 记忆 |
| | R06 | CrewAI 架构 | 依赖 R01-R05 记忆 |
| | R07 | 三框架对比 | 依赖 R01-R06 记忆 |
| | R08 | 共同瓶颈识别 | 依赖 R01-R07 记忆 |
| **Phase 3: Synthesis** | R09 | 改进架构设计 | 依赖 R01-R08 记忆 |
| | R10 | 实验方案设计 | 依赖 R01-R09 记忆 |
| | R11 | 原型实现 | 依赖 R01-R10 记忆 |
| | R12 | 最终技术报告 | 依赖 R01-R11 记忆 |

### 测试环境

- **模型**: DeepSeek V4 (deepseek-v4-flash)
- **Embedding**: DashScope text-embedding-v4 (1024 维)
- **框架**: LangGraph StateGraph + InMemoryStore
- **运行环境**: Docker 容器 `langgraph-demo`
- **代码位置**: `examples/multi_agent_demo/run_12rounds.py`

### 协议版本

v3 版本引入**检索式上下文压缩协议**：
- `build_context_packet()`: 将完整文档保存在 Store，只在状态中传递可回查 compact packet
- `retrieve_evidence_spans()`: 按 query 从原文抽取短 evidence span，内部保留 offset/hash/source_ref
- `verify_context_packet()`: Python 层验证 evidence 是否可从 Store 全文按 offset/hash 回放
- `select_context_packets()`: 基于词法 + 向量相关性选择最相关的 packet
- `format_context_for_prompt()`: 只把极简 evidence 渲染给 LLM，格式为 `[doc_key#span_id] 原文片段`
- `analysis_digest`: executor 输出的压缩版分析，summarizer 使用 digest 而非全文

---

## 实验结果

### 核心指标对比

| 指标 | Text 模式 | Structured 模式 | 差异 |
|------|-----------|----------------|------|
| **LLM 调用次数** | 72 | 72 | 0 |
| **Input tokens** | 72,202 | 35,400 | **-36,802 (-51.0%)** |
| **Output tokens** | 47,593 | 43,384 | **-4,209 (-8.8%)** |
| **Total tokens** | 119,795 | 78,784 | **-41,011 (-34.2%)** |
| **Wall-clock 时间** | 399.4s | 362.2s | **-37.2s (-9.3%)** |
| Agent 消息数 | 0 | 72 | +72 |
| 协议字符数 | 0 | 40,291 | +40,291 |
| Embedding 传递 | 0 | 36 | +36 |
| 记忆复用命中 | 68 | 68 | 0 |

### Per-Agent Token 分布

**Text 模式:**

| Agent | 调用数 | Input tokens | Output tokens | Total |
|-------|--------|-------------|---------------|-------|
| planner | 12 | 6,148 | 1,855 | 8,003 |
| retriever | 36 | 2,506 | 21,201 | 23,707 |
| executor | 12 | 47,607 | 17,121 | 64,728 |
| summarizer | 12 | 15,941 | 7,416 | 23,357 |
| **合计** | **72** | **72,202** | **47,593** | **119,795** |

**Structured 模式:**

| Agent | 调用数 | Input tokens | Output tokens | Total |
|-------|--------|-------------|---------------|-------|
| planner | 12 | 5,867 | 1,855 | 7,722 |
| retriever | 36 | 2,510 | 20,475 | 22,985 |
| executor | 12 | 12,875 | 15,387 | 28,262 |
| summarizer | 12 | 14,148 | 5,667 | 19,815 |
| **合计** | **72** | **35,400** | **43,384** | **78,784** |

### 上下文压缩效果

| 来源 | 记录数 | 原始字符 | 压缩字符 | 节省 |
|------|--------|----------|----------|------|
| retriever | 36 | — | — | 69.4% |
| executor_prompt | 12 | — | — | 69.3% |
| **总计** | **48** | **92,386** | **28,320** | **64,066 (69.3%)** |

### 证据校验与回查

| 指标 | Structured 模式 |
|------|----------------|
| 已检查 context packets | 36 |
| 校验失败 packets | 0 |
| 直接可靠 packets | 0 |
| Store rehydrate packets | 36 |
| Store get 操作 | 36 |

说明：当前 coverage 阈值较保守，36 个 packet 均触发 Store 回查补充；但 prompt 仅暴露极简 evidence，offset/hash/diagnostics 留在 Python 内部，不进入 LLM token。

### 任务完成质量对比

| 质量指标 | Text 模式 | Structured 模式 | 差异 |
|----------|-----------|----------------|------|
| 总 key findings | 62 | 46 | -16 (-25.8%) |
| 平均 findings/轮 | 5.2 | 3.8 | -1.3 |
| 总 analysis 字符 | 7,700 | 7,853 | +153 (+2.0%) |
| 总 summary 字符 | 7,415 | 5,688 | -1,727 (-23.3%) |

### 逐轮对比

| 轮次 | 任务 | Text 时间 | Struct 时间 | Text Findings | Struct Findings |
|------|------|-----------|-------------|---------------|-----------------|
| R01 | LangGraph 核心概念 | 28.1s | 22.7s | 6 | 5 |
| R02 | 状态管理机制 | 34.3s | 29.5s | 5 | 4 |
| R03 | 共享记忆系统 | 32.9s | 29.4s | 7 | 3 |
| R04 | 多智能体通信 | 28.9s | 32.5s | 5 | 5 |
| R05 | AutoGen 架构 | 28.8s | 29.7s | 5 | 5 |
| R06 | CrewAI 架构 | 28.8s | 30.0s | 3 | 4 |
| R07 | 三框架对比 | 35.5s | 29.5s | 3 | 3 |
| R08 | 共同瓶颈识别 | 43.2s | 26.9s | 9 | 3 |
| R09 | 改进架构设计 | 41.4s | 31.6s | 3 | 3 |
| R10 | 实验方案设计 | 31.1s | 35.0s | 4 | 3 |
| R11 | 原型实现 | 31.0s | 33.9s | 5 | 3 |
| R12 | 最终技术报告 | 35.3s | 31.4s | 7 | 5 |

---

## 关键发现

### 1. Token 节省 34.2%

- **Input tokens 节省 51.0%**：极简 evidence prompt 将 executor 输入从 47,607 降至 12,875 tokens
- **Output tokens 节省 8.8%**：structured 模式整体输出从 47,593 降至 43,384 tokens
- **executor 是最大受益者**：input tokens 从 47,607 降至 12,875 (-73.0%)

### 2. 时间节省 9.3%

- 总时间从 399.4s 降至 362.2s，节省 37.2 秒
- 主要来源：executor 平均耗时从 12.1s 降至 10.5s，summarizer 平均耗时从 6.3s 降至 5.1s

### 3. 上下文压缩 69.3%

- 原始文档 92,386 字符 → prompt 可见上下文 28,320 字符
- retriever 压缩率 69.4%（原文 evidence span + 极简引用）
- executor_prompt 压缩率 69.3%（只渲染 `[doc_key#span_id] 原文片段`）

### 4. 质量有明显 trade-off

- key findings 减少 25.8%（46 vs 62）
- analysis 字符基本持平（+2.0%）
- summary 字符减少 23.3%
- **trade-off**: 用 34.2% 的 token 节省换取 findings 数量下降；后续可通过提高 evidence top-k 或放宽 reliable coverage 阈值改善质量

---

## 与之前版本对比

| 版本 | Token 节省率 | 时间差异 | 压缩机制 |
|------|-------------|----------|----------|
| v1 (2 轮, 无压缩) | -10.2% | -1.9% | 仅结构化消息 |
| v2 (12 轮, 无压缩) | -3.0% | -0.1% | 仅结构化消息 |
| **v3 (12 轮, 极简 evidence 压缩)** | **-34.2%** | **-9.3%** | **query-aware evidence + internal verification + minimal prompt** |

---

## 复现方法

```bash
docker start langgraph-demo
docker exec langgraph-demo bash -c '
  export DEEPSEEK_API_KEY="your-key"
  export DASHSCOPE_API_KEY="your-key"
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
  cd /demo
  python3 -u run_12rounds.py
'
```

结果保存至 `/demo/results_12rounds.json`。
